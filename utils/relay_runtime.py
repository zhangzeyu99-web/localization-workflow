"""Bounded local relay execution shared by translation, review and audit."""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import urllib.error
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


class RelayError(RuntimeError):
    def __init__(self, category: str, message: str, retry_after: float = 0):
        super().__init__(message)
        self.category = category
        self.retry_after = retry_after


class FatalRelayError(RelayError):
    pass


class ResponseTooLarge(ValueError):
    pass


class RequestBudgetExceeded(ValueError):
    def __init__(self, message: str, cells=None):
        super().__init__(message)
        self.cells = set(cells or [])


class IncompletePhase(ValueError):
    pass


def concurrency(value: int) -> int:
    if not 1 <= value <= 5:
        raise ValueError("API concurrency must be between 1 and 5")
    return value


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return 0


def classify_error(exc: Exception) -> RelayError:
    if isinstance(exc, RelayError):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        # Do not persist response bodies: gateways may echo credentials or customer text.
        code = ''
        if exc.code in {400, 429}:
            try:
                body = json.loads(exc.read().decode('utf-8'))
                error = body.get('error', {})
                code = str(error.get('code', '')) if isinstance(error, dict) else ''
            except (ValueError, OSError):
                pass
        if code in {'context_length_exceeded', 'input_too_large', 'max_tokens_exceeded'}:
            raise ResponseTooLarge('relay context/output limit exceeded') from exc
        if exc.code == 413:
            raise ResponseTooLarge("relay request exceeds provider size limit") from exc
        if exc.code in {401, 403, 402}:
            return FatalRelayError("auth_or_balance", f"relay HTTP {exc.code}; check credentials/balance")
        if exc.code == 429:
            if code in {"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached",
                        "daily_limit_exceeded", "daily_quota_exceeded", "insufficient_balance"}:
                return FatalRelayError("balance", "relay quota exhausted")
            return RelayError("rate_limit", "relay HTTP 429", _retry_after(exc.headers.get("Retry-After")))
        if exc.code == 408 or 500 <= exc.code < 600:
            return RelayError("transient", f"relay HTTP {exc.code}")
        return FatalRelayError("configuration", f"relay HTTP {exc.code}; verify model and request settings")
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, OSError)):
        return RelayError("transient", f"relay transport error: {type(exc).__name__}")
    return RelayError("response", f"invalid relay response: {type(exc).__name__}")


class RelayRuntime:
    def __init__(self, work_dir: Path | None = None, *, limit: int = 4,
                 max_attempts: int = 3, retry_failed: bool = False,
                 clock=time.monotonic, jitter=random.random,
                 backoff_base: float = 1, cooldown_seconds: float = 60):
        self.limit = concurrency(limit)
        self.effective_limit = self.limit
        self.max_attempts = max_attempts
        if not 1 <= max_attempts <= 3:
            raise ValueError('request attempts must be between 1 and 3')
        self.work_dir = work_dir
        self.clock, self.jitter = clock, jitter
        self.backoff_base, self.cooldown_seconds = backoff_base, cooldown_seconds
        self.condition = threading.Condition()
        self.active = self.peak_active = 0
        self.cooldown_until = 0.0
        self.outage_started: float | None = None
        self.failure_streak = self.success_streak = 0
        self.fatal: FatalRelayError | None = None
        self.attempts: dict[str, int] = {}
        self.requests = self.retries = self.failed_requests = 0
        self.validation_failures = 0
        self.usage: dict[str, int] = {}
        self.usage_unknown = 0
        self.last_progress = 0.0
        self.blind_readings: dict[str, dict] = {}
        self.journal = work_dir / "relay_requests.jsonl" if work_dir else None
        blind_path = work_dir / 'blind_readings.jsonl' if work_dir else None
        if blind_path and blind_path.exists():
            for line in blind_path.read_text(encoding='utf-8').splitlines():
                try:
                    record = json.loads(line)
                    self.blind_readings[record['key']] = record['value']
                except (ValueError, KeyError):
                    continue
        if self.journal and self.journal.exists():
            for line in self.journal.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # A process may have stopped during the last append.
                if event.get("event") == "reset_exhausted":
                    for key in event["keys"]:
                        self.attempts[key] = 0
                elif event.get("event") == "send":
                    for key in event["keys"]:
                        self.attempts[key] = self.attempts.get(key, 0) + 1
            if retry_failed:
                exhausted = [key for key, count in self.attempts.items() if count >= max_attempts]
                self._append({"event": "reset_exhausted", "keys": exhausted})
                for key in exhausted:
                    self.attempts[key] = 0

    def _append(self, event: dict) -> None:
        if self.journal:
            event = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), **event}
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with self.journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def keys(self, identity: str, stage: str, payload: dict) -> list[str]:
        keys = []
        for row in payload.get("rows", payload.get("suggestions", [])):
            trusted = {k: v for k, v in row.items() if k != "validation_feedback"}
            text = json.dumps(trusted, ensure_ascii=False, sort_keys=True)
            langs = [row["lang"]] if row.get("lang") else payload.get("target_languages", [""])
            for lang in langs:
                binding = json.dumps([identity, stage, lang], ensure_ascii=False) + text
                keys.append(hashlib.sha256(binding.encode("utf-8")).hexdigest())
        if not keys:
            binding = json.dumps([identity, stage, payload], ensure_ascii=False, sort_keys=True)
            keys.append(hashlib.sha256(binding.encode("utf-8")).hexdigest())
        return keys

    def save_blind_readings(self, records: dict[str, dict]) -> None:
        with self.condition:
            self.blind_readings.update(records)
            if self.work_dir and records:
                with (self.work_dir / 'blind_readings.jsonl').open('a', encoding='utf-8') as stream:
                    for key, value in records.items():
                        stream.write(json.dumps({'key': key, 'value': value}, ensure_ascii=False) + '\n')

    def note_validation(self, stage: str, feedback: dict) -> None:
        if not feedback:
            return
        with self.condition:
            self.validation_failures += len(feedback)
            self._append({'event': 'validation', 'stage': stage, 'failed_cells': len(feedback),
                          'reasons': list(dict.fromkeys(str(value)[:500] for value in feedback.values()))[:10]})

    def request(self, identity: str, stage: str, payload: dict, send):
        keys = self.keys(identity, stage, payload)
        while True:
            with self.condition:
                while True:
                    if self.fatal:
                        raise self.fatal
                    if self.outage_started is not None and self.clock() - self.outage_started >= 900:
                        self.fatal = FatalRelayError("unavailable", "relay unavailable for 15 minutes; resume later")
                        self.progress(force=True)
                        raise self.fatal
                    if any(self.attempts.get(key, 0) >= self.max_attempts for key in keys):
                        exhausted = []
                        for row in payload.get('rows', payload.get('suggestions', [])):
                            langs = [row['lang']] if row.get('lang') else payload.get('target_languages', [''])
                            for lang in langs:
                                single = {'rows': [row], 'target_languages': [lang]}
                                if any(self.attempts.get(key, 0) >= self.max_attempts for key in self.keys(identity, stage, single)):
                                    exhausted.append((str(row.get('request_key', row.get('review_key', ''))), str(lang)))
                        raise RequestBudgetExceeded("request budget exhausted; use explicit retry-failed after diagnosis", exhausted)
                    delay = self.cooldown_until - self.clock()
                    if self.active < self.effective_limit and delay <= 0:
                        break
                    self.condition.wait(timeout=min(max(delay, .05), 1.0))
                previous = max(self.attempts.get(key, 0) for key in keys)
                self._append({"event": "send", "stage": stage, "keys": keys})
                for key in keys:
                    self.attempts[key] = self.attempts.get(key, 0) + 1
                self.active += 1
                self.peak_active = max(self.peak_active, self.active)
                self.requests += 1
                self.retries += int(previous > 0)
                self.progress(force=True)
            started = self.clock()
            try:
                result, metadata = send()
            except ResponseTooLarge:
                with self.condition:
                    self.failed_requests += 1
                    self.usage_unknown += 1
                    self._append({'event': 'error', 'stage': stage, 'category': 'size'})
                raise
            except Exception as exc:
                error = classify_error(exc)
                with self.condition:
                    self.failed_requests += 1
                    self.usage_unknown += 1
                    self._append({"event": "error", "stage": stage, "category": error.category,
                                  "elapsed": round(self.clock() - started, 3)})
                    if isinstance(error, FatalRelayError):
                        self.fatal = error
                    elif error.category in {"transient", "rate_limit"}:
                        self.failure_streak += 1
                        self.success_streak = 0
                        if self.outage_started is None:
                            self.outage_started = self.clock()
                        delay = max(error.retry_after, self.backoff_base * (min(30, 2 ** previous) + self.jitter()))
                        if error.category == "rate_limit" or self.failure_streak >= 3:
                            self.effective_limit = max(1, self.effective_limit // 2)
                        if self.failure_streak >= 3:
                            delay = max(delay, self.cooldown_seconds)
                        self.cooldown_until = max(self.cooldown_until, self.clock() + delay)
                if isinstance(error, FatalRelayError):
                    raise error from exc
                if previous + 1 >= self.max_attempts:
                    raise error from exc
                # Shared cooldown handles transport failures; malformed output has no fixed delay.
                continue
            else:
                with self.condition:
                    self.failure_streak = 0
                    self.outage_started = None
                    self.success_streak += 1
                    if self.success_streak >= 20:
                        self.effective_limit = min(self.limit, self.effective_limit + 1)
                        self.success_streak = 0
                    usage = metadata.get("usage")
                    if isinstance(usage, dict) and usage:
                        for name, value in usage.items():
                            if isinstance(value, int):
                                self.usage[name] = self.usage.get(name, 0) + value
                    else:
                        self.usage_unknown += 1
                    self._append({"event": "result", "stage": stage,
                                  "elapsed": round(self.clock() - started, 3), "usage": usage,
                                  "model": metadata.get("model")})
                return result
            finally:
                with self.condition:
                    self.active -= 1
                    self.condition.notify_all()
                    self.progress(force=self.fatal is not None or self.active == 0)

    def progress(self, *, force: bool = False) -> dict:
        result = {"backend": "relay", "concurrency_limit": self.limit,
                  "pid": os.getpid(), "updated_at": datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  "effective_concurrency": self.effective_limit, "active": self.active,
                  "peak_active": self.peak_active, "requests": self.requests, "retries": self.retries,
                  "failed_requests": self.failed_requests, "usage": self.usage,
                  "validation_failed_cells": self.validation_failures,
                  "usage_unknown_requests": self.usage_unknown,
                  "stop_reason": self.fatal.category if self.fatal else None}
        if self.work_dir and (force or self.clock() - self.last_progress >= 30):
            atomic_json(self.work_dir / "relay_progress.json", result)
            self.last_progress = self.clock()
        return result


def bounded_results(function, jobs, *, workers: int):
    """At most 2 * workers queued jobs; isolate row failures, stop on global failures."""
    workers = max(1, min(5, workers))
    iterator = iter(jobs)
    pool = ThreadPoolExecutor(max_workers=workers)
    pending = {}
    try:
        def fill():
            while len(pending) < 2 * workers:
                try:
                    job = next(iterator)
                except StopIteration:
                    break
                pending[pool.submit(function, job)] = job
        fill()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                try:
                    value = future.result()
                except FatalRelayError:
                    raise
                except Exception as exc:
                    yield job, None, exc
                else:
                    yield job, value, None
            fill()
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)


@contextmanager
def task_lock(work_dir: Path):
    from utils.large_text_multilingual_proofread import _pid_is_running
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "task.lock"
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                owner = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise RuntimeError("task lock is unreadable; inspect it before resuming") from exc
            if _pid_is_running(int(owner.get("pid", 0))):
                raise RuntimeError(f"task already running under pid {owner['pid']}")
            path.unlink()
    else:
        raise RuntimeError("could not acquire task lock")
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid()}, stream)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
