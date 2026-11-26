"""Resumable OpenAI-compatible executor for large multilingual packs."""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from utils.relay_runtime import (
    RelayRuntime, ResponseTooLarge, FatalRelayError, RequestBudgetExceeded,
    IncompletePhase, bounded_results,
)
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from utils.ai_checker import SHORT_TRANSLATION_REVIEW_POLICY
from utils.localization_quality_policy import QUALITY_POLICY_VERSION, localization_quality_policy
from utils.quality_harness_terms import is_fixed_glossary_seed
from utils.large_text_multilingual_runner import load_manifest, save_manifest
from utils.workflow_progress import update_progress
from utils.structured_text_template import (
    ParsedTemplate,
    TranslationSlot,
    parse_template,
    render_translations,
    should_use_template,
    translation_slots,
)


class TranslationClient(Protocol):
    def translate_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class ExecutionSummary:
    cache_jsonl: Path
    metrics_json: Path
    source_rows: int
    unique_api_rows: int
    seeded_rows: int
    batch_count: int
    reused_batches: int
    elapsed_seconds: float


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    from utils.structured_text_template import _strict_json_loads
    return _strict_json_loads(path.read_text(encoding="utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").split('\n')
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_write_text(
        path,
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record_progress(manifest: dict, phase: str, *, total: int, accepted: int,
                    reused: int, started: float) -> None:
    update_progress(manifest, phase, total=total, accepted=accepted, reused=reused,
                    seconds=time.perf_counter() - started)
    save_manifest(manifest)


def start_phase(manifest: dict[str, Any], phase: str) -> None:
    manifest.setdefault("phase_status", {})[phase] = "running"
    manifest.setdefault("phase_events", []).append(
        {"phase": phase, "event": "start", "at": _now()}
    )
    manifest["status"] = f"{phase}_running"
    save_manifest(manifest)


def complete_phase(
    manifest: dict[str, Any],
    phase: str,
    *,
    started: float,
    metrics: dict[str, Any] | None = None,
) -> None:
    elapsed = round(time.perf_counter() - started, 3)
    manifest.setdefault("phase_status", {})[phase] = "done"
    manifest.setdefault("phase_events", []).append(
        {"phase": phase, "event": "done", "at": _now(), "seconds": elapsed}
    )
    manifest.setdefault("phase_metrics", {})[phase] = {
        "seconds": elapsed,
        **(metrics or {}),
    }
    manifest["status"] = f"{phase}_done"
    save_manifest(manifest)


def fail_phase(manifest: dict[str, Any], phase: str, exc: BaseException) -> None:
    manifest.setdefault("phase_status", {})[phase] = "failed"
    manifest.setdefault("phase_events", []).append(
        {"phase": phase, "event": "failed", "at": _now(), "error": str(exc)[:500]}
    )
    manifest["status"] = f"{phase}_failed"
    save_manifest(manifest)


def _flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("lws_settings", "openai", "provider", "translation_provider"):
        nested = data.get(key)
        if isinstance(nested, dict):
            merged = dict(nested)
            for name in ("base_url", "model", "api_key"):
                if data.get(name) not in (None, ""):
                    merged[name] = data[name]
            return merged
    return data


_ORIG_URLOPEN = urllib.request.urlopen
_CONTEXT_FRAGMENT_SPLIT = re.compile(r'(?<=[；。：！？\n])|(?=[｜|])|(?<=[｜|])')
_FRAGMENT_TOKEN_RE = re.compile(r'\[f\d+\]')
_MAX_CONTEXT_FRAGMENTS = 40


def _prune_term_hit_for_wire(hit: Any) -> Any:
    if not isinstance(hit, dict):
        return hit
    translations = hit.get('translations')
    single_target = None
    if isinstance(translations, dict) and len(translations) == 1:
        single_target = next(iter(translations.values()))
    pruned: dict[str, Any] = {}
    for key, value in hit.items():
        if key in {'enforcement', 'required'}:
            continue
        if value in (None, '', [], {}):
            continue
        if key == 'reference_en' and single_target and str(value).strip() == str(single_target).strip():
            continue
        pruned[key] = value
    return pruned


def _prune_row_for_wire(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    source_mode = str(row.get('source_mode') or 'cn')
    cn = row.get('cn')
    seed_origin = str(row.get('seed_origin') or '')
    pruned: dict[str, Any] = {}
    for key, value in row.items():
        if key == 'translation_source' and source_mode == 'cn' and value == cn:
            continue
        if key == 'source_mode' and value == 'cn':
            continue
        if key == 'reference_en' and value in (None, ''):
            continue
        if key == 'reference_en_status' and value in (None, '', 'not_requested'):
            continue
        if key in {'risk_flags', 'protected_tokens', 'term_hits', 'unresolved_issues'} and not value:
            continue
        if key == 'dialogue_evidence':
            if not value or (isinstance(value, dict) and not value.get('turns') and len(value) == 1):
                continue
        if key == 'seed_origin' and not value:
            continue
        if key == 'context' and value in (None, '', {}):
            continue
        if key in {'name_semantic_check_required', 'semantic_check_required'} and value is False:
            continue
        if key == 'glossary_seed_locked' and value is False and seed_origin != 'glossary_exact':
            continue
        if key == 'independent_target_reading' and value is None:
            continue
        if key in {'owner', 'cache_key'}:
            continue
        if key == 'term_hits' and isinstance(value, list):
            value = [_prune_term_hit_for_wire(item) for item in value]
        pruned[key] = value
    return pruned


def _prune_wire_payload(payload: dict[str, object]) -> dict[str, object]:
    """Drop lossless empty/default/mirrored/internal fields on wire copies only."""
    if not isinstance(payload, dict):
        return payload
    changed = False
    out = dict(payload)
    for list_key in ('rows', 'suggestions'):
        items = payload.get(list_key)
        if isinstance(items, list):
            pruned_items = [_prune_row_for_wire(item) for item in items]
            if pruned_items != items:
                out[list_key] = pruned_items
                changed = True
    return out if changed else payload


def _compact_context_fragments(payload: dict[str, object]) -> dict[str, object]:
    """Deduplicate long repeated sentence fragments inside context strings losslessly."""
    if not isinstance(payload, dict) or 'shared_context_fragments' in payload:
        return payload
    counts: Counter[str] = Counter()
    has_conflict = False

    def walk_count(value: Any, in_context: bool = False) -> None:
        nonlocal has_conflict
        if has_conflict:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'shared_contexts', 'shared_context_fragments'}:
                    continue
                walk_count(item, in_context or key == 'context')
        elif isinstance(value, list):
            for item in value:
                walk_count(item, in_context)
        elif in_context and isinstance(value, str):
            if _FRAGMENT_TOKEN_RE.search(value):
                has_conflict = True
                return
            if len(value) >= 80:
                for segment in _CONTEXT_FRAGMENT_SPLIT.split(value):
                    if len(segment) >= 12:
                        counts[segment] += 1

    walk_count(payload)
    if has_conflict:
        return payload
    scored = [
        ((len(segment) - 5) * count - (len(segment) + 12), segment)
        for segment, count in counts.items()
        if count >= 3 and (len(segment) - 5) * count - (len(segment) + 12) > 0
    ]
    scored.sort(key=lambda pair: (-pair[0], -len(pair[1]), pair[1]))
    selected = [segment for _, segment in scored[:_MAX_CONTEXT_FRAGMENTS]]
    if not selected:
        return payload
    fragments = {f'f{index + 1}': segment for index, segment in enumerate(selected)}
    reverse = {segment: f'[{frag_id}]' for frag_id, segment in fragments.items()}

    def walk_replace(value: Any, in_context: bool = False) -> Any:
        if isinstance(value, dict):
            return {
                key: (item if key == 'shared_contexts' else walk_replace(item, in_context or key == 'context'))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [walk_replace(item, in_context) for item in value]
        if in_context and isinstance(value, str) and len(value) >= 80:
            return ''.join(reverse.get(part, part) for part in _CONTEXT_FRAGMENT_SPLIT.split(value))
        return value

    compacted = walk_replace(payload)
    compacted['shared_context_fragments'] = fragments
    before_len = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    after_len = len(json.dumps(compacted, ensure_ascii=False, separators=(',', ':')))
    if before_len - after_len < 120:
        return payload
    return compacted


def _prepare_wire_payload(payload: dict[str, object]) -> tuple[dict[str, object], bool, bool]:
    """Produce a lossless compact wire copy without mutating caller payloads."""
    pruned = _prune_wire_payload(payload)
    shared = _compact_shared_context(pruned)
    used_shared = shared is not pruned and 'shared_contexts' in shared
    final = _compact_context_fragments(shared)
    used_fragments = final is not shared and 'shared_context_fragments' in final
    return final, used_shared, used_fragments


def _compact_shared_context(payload: dict[str, object]) -> dict[str, object]:
    fields = {'context', 'dialogue_evidence', 'term_hits'}
    reserved = False

    def normalize(value: Any, field: str = '') -> Any:
        nonlocal reserved
        if field == 'context' and isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    value = parsed
            except (ValueError, TypeError):
                pass
        if isinstance(value, dict):
            reserved |= '$context_ref' in value or 'shared_contexts' in value
            return {key: normalize(item, key) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    normalized = normalize(payload)
    if reserved:
        return payload
    counts: Counter[str] = Counter()

    def signature(value: Any, field: str = '') -> str:
        if not isinstance(value, (dict, list, str)):
            return ''
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return encoded if len(encoded) >= 64 else ''

    def count(value: Any, eligible: bool = False, field: str = '') -> None:
        if eligible and (key := signature(value, field)):
            counts[key] += 1
        if isinstance(value, dict):
            for child_field, item in value.items():
                count(item, eligible or child_field in fields, child_field)
        elif isinstance(value, list):
            for item in value:
                count(item, eligible)

    count(normalized)
    shared: dict[str, Any] = {}
    references: dict[str, str] = {}

    def children(value: Any, eligible: bool) -> Any:
        if isinstance(value, dict):
            return {child_field: compact(item, eligible or child_field in fields, child_field)
                    for child_field, item in value.items()}
        if isinstance(value, list):
            return [compact(item, eligible) for item in value]
        return value

    def compact(value: Any, eligible: bool = False, field: str = '') -> Any:
        key = signature(value, field) if eligible else ''
        if key and counts[key] > 1:
            if key not in references:
                ref = references[key] = f'context-{len(references) + 1}'
                shared[ref] = children(value, eligible)
            return {'$context_ref': references[key]}
        return children(value, eligible)

    result = compact(normalized)
    if not shared:
        return payload
    result['shared_contexts'] = shared
    if (
        len(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
        >= len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    ):
        return payload
    return result


class OpenAICompatibleClient:
    def __init__(self, config_path: Path, *, timeout: int = 180,
                 runtime: RelayRuntime | None = None) -> None:
        config = _flatten_config(_read_json(config_path))
        self.base_url = str(config.get("base_url") or "").rstrip("/")
        self.model = str(config.get("model") or "")
        self.api_key = str(config.get("api_key") or "")
        self.checkpoint_identity = f"openai-compatible:{self.base_url}:{self.model}:{QUALITY_POLICY_VERSION}"
        self.timeout = timeout
        self.runtime = runtime or RelayRuntime()
        if not self.base_url or not self.model:
            raise ValueError("relay config requires base_url and model")

    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return self.base_url + "/chat/completions"
        return self.base_url + "/v1/chat/completions"

    def _has_proxy_env(self) -> bool:
        return any(
            os.environ.get(name)
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
        )

    def _post_json_bytes(self, url: str, body_bytes: bytes, headers: dict[str, str]) -> str:
        # Respect monkeypatched urlopen in unit tests and system proxy environments.
        if urllib.request.urlopen is not _ORIG_URLOPEN or self._has_proxy_env():
            request = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8")

        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            request = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8")

        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        tls = getattr(self, "_tls", None)
        if tls is None:
            tls = threading.local()
            self._tls = tls
        pool_key = (parsed.scheme, parsed.hostname, parsed.port)
        keepalive_headers = {**headers, "Connection": "keep-alive"}

        conn = getattr(tls, "conn", None)
        if conn is None or getattr(tls, "pool_key", None) != pool_key:
            if conn is not None:
                conn.close()
            conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
            conn = conn_cls(parsed.hostname, parsed.port, timeout=self.timeout)
            tls.conn = conn
            tls.pool_key = pool_key
        try:
            conn.request("POST", path, body=body_bytes, headers=keepalive_headers)
            resp = conn.getresponse()
            raw = resp.read()
        except (OSError, http.client.HTTPException):
            tls.conn = None
            conn.close()
            # A dropped response may follow a processed POST. Only RelayRuntime can schedule a retry.
            raise
        if 200 <= resp.status < 300:
            return raw.decode("utf-8")
        raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, io.BytesIO(raw))

    def _chat_json(self, system: str, user_payload: dict[str, object], *, stage: str = "chat") -> object:
        raw_user_chars = len(json.dumps(user_payload, ensure_ascii=False))
        compact, used_shared, used_fragments = _prepare_wire_payload(user_payload)
        compact_user_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        if hasattr(self.runtime, "note_wire_compression"):
            self.runtime.note_wire_compression(raw_user_chars, len(compact_user_json))
        if used_shared:
            system += (
                ' Input uses shared_contexts: recursively resolve each {"$context_ref":"id"} '
                'to that complete table value before reviewing its row. References replace only '
                'repeated context/evidence, never omit it. Existing scene translations are still '
                'unverified evidence, not speaker configuration. Return original row keys and '
                'the requested response schema, never context references.'
            )
        if used_fragments:
            system += (
                ' Context strings may contain [fN] placeholders defined in shared_context_fragments; '
                'expand each [fN] verbatim before reading and never output [fN].'
            )
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": compact_user_json,
                },
            ],
        }
        def send():
            body_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            }
            from utils.structured_text_template import _strict_json_loads
            body = _strict_json_loads(self._post_json_bytes(self._endpoint(), body_bytes, headers))
            choices = body.get("choices") if isinstance(body, dict) else None
            if not isinstance(choices, list) or not choices:
                # Some gateways report exhausted quota inside an HTTP 200 body.
                detail = body.get('error') if isinstance(body, dict) else None
                detail = detail if isinstance(detail, dict) else body if isinstance(body, dict) else {}
                code = str(detail.get('code', '')).lower()
                message = str(detail.get('message', '')).lower()
                if code in {'insufficient_quota', 'quota_exceeded', 'billing_hard_limit_reached',
                            'daily_limit_exceeded', 'daily_quota_exceeded', 'insufficient_balance'} or any(
                    text in message for text in ('quota exhausted', 'quota exceeded', 'insufficient quota',
                        'insufficient balance', 'daily limit', 'daily quota', '额度已达到上限',
                        '额度已达上限', '额度不足', '余额不足', '配额已用尽')
                ):
                    raise FatalRelayError('balance', 'relay quota exhausted; check provider daily limit/balance')
                raise RuntimeError("relay response is missing choices")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise ValueError('relay choice must be an object')
            if choice.get("finish_reason") == "length":
                raise ResponseTooLarge("relay output truncated")
            if 'finish_reason' in choice and choice['finish_reason'] != 'stop':
                raise FatalRelayError('incomplete_response', 'relay did not finish normally; inspect provider response status')
            message = choice.get("message")
            if not isinstance(message, dict) or "content" not in message:
                raise RuntimeError("relay response is missing message content")
            if message.get('refusal') or message.get('tool_calls') or message.get('function_call'):
                raise FatalRelayError('incomplete_response', 'relay returned a refusal or tool call instead of the requested result')
            content = message["content"]
            result = _strict_json_loads(content) if isinstance(content, str) else content
            return result, {"usage": body.get("usage"), "model": body.get("model")}
        return self.runtime.request(self.checkpoint_identity, stage, user_payload, send)

    def translate_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]:
        parsed = self._chat_json(
            (
                "You are a senior mobile-game localizer. Translate every row into every "
                "requested language. Preserve tokens, numbers, tags, and terminology. "
                "Rows may include source_mode, translation_source, and reference_en. For cn+en, "
                "Chinese is authoritative and English is a reviewed terminology/style reference. "
                "For en, translation_source/reference_en is primary and Chinese is an omission "
                "and gameplay-condition backcheck. Do not propagate conflicts or omissions. "
                "Rows marked as structured text segments contain only readable text: return only "
                "translated prose for them and never add markup, placeholders, or JSON syntax. "
                "Return strict JSON: {\"rows\":[{\"request_key\":...,"
                "\"translations\":{LANG:TEXT}}]}. Do not omit or add rows. "
                "If validation_feedback is present, fix only the requested failing cells."
                + localization_quality_policy(target_langs)
            ),
            {"target_languages": target_langs, "rows": rows},
            stage="translate",
        )
        result = parsed.get("rows") if isinstance(parsed, dict) else parsed
        if not isinstance(result, list):
            raise ValueError("relay response must contain a rows array")
        return result

    def review_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]:
        parsed = self._chat_json(
            (
                "Act as an independent line-by-line mobile-game localization reviewer. "
                "Check meaning, omissions, terminology, fluency, length, tokens, tags, and numbers. "
                "Rows may include source_mode and reference_en. For cn+en, Chinese is authoritative "
                "and English is supporting evidence. For en, English is primary and Chinese is an "
                "omission/gameplay-condition backcheck. Do not preserve an error merely because it "
                "appears in the English reference. "
                "For structured text segments, review only the readable text and never add markup, "
                "placeholders, or JSON syntax to suggested. "
                "Do not rewrite correct text. "
                + SHORT_TRANSLATION_REVIEW_POLICY
                +
                "If validation_feedback is supplied, correct that failure and return only the requested cells. "
                "For dialogue, distinguish the speaker, addressee, and grammatical antecedent. "
                "A gender or address change must cite concrete supplied context in reason; never "
                "guess from an isolated line or assume alternating speakers. If context is insufficient, "
                "KEEP the current form and state the uncertainty in reason. Preserve idiomatic meaning, "
                "emotional intent (instead of copying the surface metaphor), and explicit quantities, "
                "units, hit counts, and per-hit effects. Report any unresolved omission or semantic "
                "defect in unresolved_issues (an array; empty only when none remain). "
                "Do not call a known unresolved defect KEEP or hide it in a QA handoff note. "
                "Keep reason concise: use 'ok' for KEEP (unless briefly noting context uncertainty), "
                "and <=20 words naming the concrete defect for FIX. "
                "Return strict JSON with one item per row and language: "
                "{\"rows\":[{\"review_key\":...,\"lang\":...,\"status\":\"KEEP|FIX\","
                "\"suggested\":...,\"reason\":...}]}."
                + localization_quality_policy(target_langs)
            ),
            {"target_languages": target_langs, "rows": rows},
            stage="review",
        )
        result = parsed.get("rows") if isinstance(parsed, dict) else parsed
        if not isinstance(result, list):
            raise ValueError("review response must contain a rows array")
        return result

    def _read_target_texts(self, blind_rows: list[dict[str, object]]) -> dict:
        requested = {(str(row['review_key']), str(row['lang']).upper()): row for row in blind_rows}
        readings = {}
        runtime = getattr(self, 'runtime', None)
        legacy_keys = {key: runtime.keys(self.checkpoint_identity, 'blind', {'rows': [row]})[0]
                       for key, row in requested.items()} if runtime else {}
        text_keys = {
            key: runtime.keys(self.checkpoint_identity, 'blind-text',
                              {'lang': key[1], 'text': str(row.get('text') or '')})[0]
            for key, row in requested.items()
        } if runtime else {}
        if runtime:
            for key in requested:
                cached = runtime.blind_readings.get(text_keys[key]) or runtime.blind_readings.get(legacy_keys[key])
                if cached is not None:
                    readings[key] = {**cached, 'review_key': key[0], 'lang': key[1], 'text': requested[key]['text']}
        # Deduplicate identical (lang, text) pairs within the same batch so blind reading is never duplicated.
        pending_groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
        dedup_blind_rows: list[dict[str, object]] = []
        for key, row in requested.items():
            if key in readings:
                continue
            signature = (key[1], str(row.get('text') or ''))
            if signature not in pending_groups:
                pending_groups[signature] = []
                dedup_blind_rows.append(row)
            pending_groups[signature].append(key)
        if dedup_blind_rows:
            blind = self._chat_json(
                "Read these target-language sentences independently, without assuming an intended source. "
                "Describe what the actual grammar says in plain English. Identify who acts, the predicate, "
                "and its exact object/complement; report tone and ambiguity. Do not silently repair an odd "
                "sentence into a familiar English idiom. In particular distinguish worrying about a person "
                "or body part from worrying about a situation. For a name or title, identify its head noun, "
                "what each modifier describes, and any named entity or place the wording implies. Describe "
                "whether it reads naturally as a target-language name, without inventing a source meaning. "
                "Return JSON {\"rows\":[{\"review_key\":...,"
                "\"lang\":...,\"meaning\":...,\"predicate_object\":...,\"tone\":...}]}.",
                {"rows": dedup_blind_rows},
                stage="blind",
            )
            blind = blind.get("rows") if isinstance(blind, dict) else blind
            if not isinstance(blind, list) or len(blind) != len(dedup_blind_rows) or any(not isinstance(row, dict) for row in blind):
                raise ValueError("blind semantic reading coverage mismatch")
            dedup_requested = {(str(row['review_key']), str(row['lang']).upper()): row for row in dedup_blind_rows}
            rep_readings: dict[tuple[str, str], dict] = {}
            for reading in blind:
                key = (str(reading.get("review_key")), str(reading.get("lang")).upper())
                if key not in dedup_requested or key in rep_readings or any(
                    not isinstance(reading.get(field), str) or not reading[field].strip()
                    for field in ("meaning", "predicate_object", "tone")
                ):
                    raise ValueError("invalid blind semantic reading")
                rep_readings[key] = reading
            if set(dedup_requested) != set(rep_readings):
                raise ValueError("blind semantic reading key mismatch")
            to_save: dict[str, dict] = {}
            for rep_key, reading in rep_readings.items():
                signature = (rep_key[1], str(dedup_requested[rep_key].get('text') or ''))
                for member_key in pending_groups[signature]:
                    member_value = {
                        **reading,
                        'review_key': member_key[0],
                        'lang': member_key[1],
                        'text': requested[member_key]['text'],
                    }
                    readings[member_key] = member_value
                    if runtime:
                        to_save[text_keys[member_key]] = member_value
                        to_save[legacy_keys[member_key]] = member_value
            if runtime and to_save:
                runtime.save_blind_readings(to_save)
        return readings

    def _audit_with_readings(self, suggestions: list[dict[str, object]], readings: dict) -> list[dict[str, object]]:
        audit_input = [{**row, "glossary_seed_locked": is_fixed_glossary_seed(row),
                        "independent_target_reading": readings.get((str(row["review_key"]), str(row["lang"]).upper()))}
                       for row in suggestions]
        parsed = self._chat_json(
            (
                "Audit localization change suggestions conservatively. "
                + SHORT_TRANSLATION_REVIEW_POLICY
                + "For existing short copy, REVERT expansions that only restore reasonably omitted "
                "wording or change style without fixing a concrete player-facing or language defect. "
                "If validation_feedback is supplied, fix that failure and return only the requested cells. "
                "Revert changes that narrow "
                "meaning, force terminology into the wrong context, damage tokens/numbers, or are "
                "not a clear improvement. "
                "Review every supplied cell, including KEEP rows; KEEP is not evidence of correctness. "
                "For KEEP, ACCEPT only if the current target is correct or REVISE it; never REVERT a KEEP. "
                "For glossary_seed_locked=true, only an independently validated current term may pass. "
                "REVERT a purely stylistic FIX to current. If the existing term conflicts with the supplied "
                "meaning/context, report glossary_semantic_conflict in unresolved_issues and require the "
                "actual project glossary and affected references to be corrected; never approve the known "
                "bad current merely to preserve its spelling. For glossary_seed_locked=false, a soft or "
                "exempt exact glossary seed may be improved for its actual context, but it still requires "
                "the same independent meaning, tone, and technical-integrity checks; softness is not approval. "
                "REVISE an incorrect KEEP target. Check numbered entities, action conditions, enemy/ally "
                "ownership, negation, limits, per-hit effects, and quantities against the source. "
                "Use the controller-supplied source, current translation, and context to check each "
                "suggestion independently; the reviewer reason is a claim to verify, not evidence. "
                "If context includes whole_cell_proposed, check that complete reconstructed prose for "
                "omissions, duplicated clauses, word joins and grammar, not only this segment. "
                "Return only this segment's final text; never copy the whole cell into a segment. "
                "For dialogue gender/address changes require explicit speaker/addressee evidence; "
                "REVERT speculative changes based only on a likely speaker. Compare idioms by meaning "
                "and tone, not by literal imagery. First paraphrase the primary source WITHOUT its metaphor, "
                "then independently paraphrase the actual final target wording back into plain English. "
                "Check the predicate and its object: the thing worried about, the person causing an effect, "
                "and the person affected must not change. A pretty metaphor cannot excuse a wrong object. "
                "Use independent_target_reading (obtained without source or reviewer reason) to detect "
                "anchoring: if it reveals a different predicate/object, REVERT or REVISE the wording. "
                "Read target-language antecedents in dialogue_evidence; these are unverified translations, "
                "not authoritative speaker labels. Do not infer alternating speakers. "
                "When prior_audit is supplied, recheck its selected final against the newly supplied target "
                "reading; the original reviewer suggestion remains separate evidence. Preserve that final "
                "if valid instead of introducing further stylistic changes. "
                "For semantic_check_required=true, every decision, including REVERT to current, must include "
                "semantic_check.target_text equal to the exact selected final and nonempty "
                "source_meaning and final_meaning plain-English paraphrases, and boolean meaning_preserved, "
                "roles_preserved, tone_preserved. For name_semantic_check_required=true, also verify boolean "
                "head_and_modifiers_preserved, no_invented_entities, and natural_target. Check which noun "
                "each modifier describes; a title must not invent a named place/entity by attaching a "
                "character trait to its setting. All must be true for the selected wording; otherwise fix "
                "it or report unresolved_issues. Do not rubber-stamp these fields from reviewer reason. "
                "Structured text suggestions are prose-only; never add "
                "markup, placeholders, or JSON syntax to final. Return strict JSON: {\"rows\":[{\"review_key\":...,"
                "\"lang\":...,\"decision\":\"ACCEPT|REVERT|REVISE\",\"final\":...,"
                "\"reason\":...,\"semantic_check\":{\"target_text\":...,\"source_meaning\":...,\"final_meaning\":...,"
                "\"meaning_preserved\":true,\"roles_preserved\":true,\"tone_preserved\":true}}]}. "
                "Always return final explicitly, including for ACCEPT. "
                "Keep reason concise: <=15 words naming the concrete audit verdict or defect; "
                "keep semantic_check paraphrases crisp (<=20 words each)."
                + localization_quality_policy([row.get('lang', '') for row in suggestions])
            ),
            {"suggestions": audit_input},
            stage="audit",
        )
        result = parsed.get("rows") if isinstance(parsed, dict) else parsed
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise ValueError("audit response must contain a rows array of objects")
        for row in result:
            key = (str(row.get("review_key")), str(row.get("lang")).upper())
            reading = readings.get(key)
            if reading:
                row["independent_target_reading"] = reading
            original = next((item for item in suggestions if (str(item["review_key"]), str(item["lang"]).upper()) == key), None)
            if original and str(row.get("decision")).upper() in {"ACCEPT", "REVISE"}:
                from utils.semantic_regression import known_semantic_regressions

                regressions = known_semantic_regressions(original, key[1], str(row.get("final") or ""))
                if regressions:
                    row["rejected_model_decision"] = dict(row)
                    row.update(decision="REVERT", final=original.get("current", ""),
                               reason="Known semantic regression blocked: " + ", ".join(regressions))
                    row.pop("semantic_check", None)
        return result

    def audit_batch(
        self,
        suggestions: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        def key(row):
            return str(row.get('review_key')), str(row.get('lang')).upper()

        originals = {key(row): row for row in suggestions}
        readings = self._read_target_texts([
            {'review_key': row['review_key'], 'lang': row['lang'], 'text': row['suggested']}
            for row in suggestions if row.get('semantic_check_required')
        ])
        results = self._audit_with_readings(suggestions, readings)
        changed = {}
        counts = Counter(key(row) for row in results)
        for row in results:
            cell = key(row)
            original = originals.get(cell)
            if not original or counts[cell] != 1 or not original.get('semantic_check_required') or row.get('unresolved_issues'):
                continue
            decision = str(row.get('decision')).upper()
            selected = original.get('current') if decision == 'REVERT' else row.get('final')
            if decision in {'ACCEPT', 'REVISE', 'REVERT'} and isinstance(selected, str) and selected.strip() and readings[cell]['text'] != selected:
                changed[cell] = {**original, 'prior_audit': {**row, 'final': selected}}
        if not changed:
            return results
        # Only changed cells get a second target-only reading and audit, not the whole batch.
        rereadings = self._read_target_texts([
            {'review_key': row['review_key'], 'lang': row['lang'], 'text': row['prior_audit']['final']}
            for row in changed.values()
        ])
        rechecked = self._audit_with_readings(list(changed.values()), rereadings)
        for row in rechecked:
            cell = key(row)
            original = originals.get(cell)
            if cell not in changed or not original:
                continue
            decision = str(row.get('decision')).upper()
            selected = original.get('current') if decision == 'REVERT' else row.get('final')
            if decision in {'ACCEPT', 'REVISE', 'REVERT'} and rereadings[cell]['text'] != selected:
                # Existing per-cell validation retries this item while checkpointing sound siblings.
                unresolved = row.get('unresolved_issues', [])
                row['unresolved_issues'] = (unresolved if isinstance(unresolved, list) else [str(unresolved)]) + [
                    'Final target changed after independent reading; semantic evidence is not bound to final text.'
                ]
            rejected = changed[cell]['prior_audit'].get('rejected_model_decision')
            if rejected:
                row.setdefault('rejected_model_decision', rejected)
        return [row for row in results if key(row) not in changed] + rechecked


def _request_signature(row: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "cn": row.get("cn", ""),
            "translation_source": row.get("translation_source", row.get("cn", "")),
            "source_mode": row.get("source_mode", "cn"),
            "reference_en": row.get("reference_en", ""),
            "reference_en_status": row.get("reference_en_status", "not_requested"),
            "context": row.get("context", ""),
            "term_hits": row.get("term_hits") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _request_row(row: dict[str, Any], request_key: str) -> dict[str, object]:
    return {
        "request_key": request_key,
        "cn": str(row.get("cn") or ""),
        "translation_source": str(row.get("translation_source") or row.get("cn") or ""),
        "source_mode": str(row.get("source_mode") or "cn"),
        "reference_en": str(row.get("reference_en") or ""),
        "reference_en_status": str(row.get("reference_en_status") or "not_requested"),
        "context": row.get("context") or "",
        "protected_tokens": row.get("tokens") or [],
        "term_hits": row.get("term_hits") or [],
    }


def _template_request_row(
    row: dict[str, Any],
    request_key: str,
    slot: TranslationSlot,
) -> dict[str, object]:
    term_hits = [
        hit
        for hit in (row.get("term_hits") or [])
        if isinstance(hit, dict)
        and str(hit.get("source") or hit.get("CN") or hit.get("term") or "") in slot.source
    ]
    return {
        "request_key": request_key,
        "cn": slot.source,
        "translation_source": slot.source,
        "source_mode": "cn",
        "reference_en": "",
        "reference_en_status": "not_requested",
        "context": f"{row.get('context') or ''}; structured text segment; {slot.context}",
        "protected_tokens": [],
        "term_hits": term_hits,
    }


def _validate_response(
    requested: list[dict[str, object]],
    response: list[dict[str, object]],
    target_langs: list[str],
) -> dict[str, dict[str, str]]:
    requested_keys = {str(row["request_key"]) for row in requested}
    response_keys = {str(row.get("request_key") or "") for row in response}
    if requested_keys != response_keys or len(response) != len(requested):
        raise ValueError(
            f"response keys do not match request keys: requested={sorted(requested_keys)}, "
            f"response={sorted(response_keys)}"
        )
    validated: dict[str, dict[str, str]] = {}
    trusted_by_key = {str(row["request_key"]): row for row in requested}
    for row in response:
        request_key = str(row["request_key"])
        translations = row.get("translations")
        if not isinstance(translations, dict):
            raise ValueError(f"missing translations object for {request_key}")
        if any(isinstance(value, (dict, list)) for value in translations.values()):
            raise ValueError('translation values must be text, not context references or objects')
        if any(not isinstance(value, str) for value in translations.values()):
            raise ValueError("translation values must be strings")
        normalized = {str(key).upper(): value for key, value in translations.items()}
        if len(normalized) != len(translations):
            raise ValueError(f'duplicate normalized language keys for {request_key}')
        missing = [lang for lang in target_langs if not normalized.get(lang, "").strip()]
        extras = sorted(set(normalized) - set(target_langs))
        if missing or extras:
            raise ValueError(
                f"language mismatch for {request_key}: missing={missing}, extras={extras}"
            )
        from utils.structured_text_template import json_structure_issues
        source = str(trusted_by_key[request_key].get("cn") or "")
        for lang in target_langs:
            from utils.xlsx_translation_writeback import cell_text_issues
            if storage := cell_text_issues(normalized[lang]):
                raise ValueError(f'translation storage integrity failed for {request_key}/{lang}: {storage}')
            integrity = json_structure_issues(source, normalized[lang])
            if integrity:
                raise ValueError(f"translation JSON integrity failed for {request_key}/{lang}: {integrity}")
        validated[request_key] = {lang: normalized[lang] for lang in target_langs}
    return validated


def _checkpoint_name(batch: list[dict[str, object]]) -> str:
    keys = "\n".join(str(row["request_key"]) for row in batch)
    return hashlib.sha256(keys.encode("utf-8")).hexdigest()[:20] + ".json"


def _partition_requests(
    rows: list[dict[str, object]],
    *,
    max_rows: int,
    max_chars: int,
    compact_contexts: bool = True,
    output_languages: int = 0,
) -> list[list[dict[str, object]]]:
    batches: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_chars = 0
    current_output = 0
    for row in rows:
        row_chars = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        over_chars = current_chars + row_chars > max_chars
        if compact_contexts and current and over_chars and len(current) < max_rows:
            candidate, _, _ = _prepare_wire_payload({'rows': [*current, row]})
            over_chars = len(json.dumps(candidate, ensure_ascii=False, separators=(',', ':'))) > max_chars
        output_chars = (80 + output_languages * (24 + 3 * len(str(row.get('cn', ''))))) if output_languages else 0
        if current and (len(current) >= max_rows or over_chars or current_output + output_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
            current_output = 0
        current.append(row)
        current_chars += row_chars
        current_output += output_chars
    if current:
        batches.append(current)
    return batches


def _cached_requests(
    checkpoint_dir: Path,
    requested: list[dict[str, object]],
    target_langs: list[str],
) -> dict[str, dict[str, str]]:
    by_key = {str(row['request_key']): row for row in requested}
    cached: dict[str, dict[str, str]] = {}
    # Scope already binds provider, model, prompt and languages; keys bind source/context/terms.
    for path in sorted(checkpoint_dir.glob('*.json')):
        if path.name.endswith('.split.json'):
            continue
        for row in _read_json(path).get('rows') or []:
            key = str(row.get('request_key') or '')
            if key not in by_key:
                continue
            languages = list((row.get('translations') or {}).keys())
            if not languages or set(languages) - set(target_langs):
                continue
            value = _validate_response([by_key[key]], [row], languages)[key]
            existing = cached.setdefault(key, {})
            if any(lang in existing and existing[lang] != text for lang, text in value.items()):
                raise ValueError(f'conflicting translation checkpoints for {key}')
            existing.update(value)
    return cached


def _execute_batch(
    client: TranslationClient,
    batch: list[dict[str, object]],
    target_langs: list[str],
    checkpoint_dir: Path,
    max_attempts: int,
    cached_requests: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, dict[str, str]], bool]:
    checkpoint = checkpoint_dir / _checkpoint_name(batch)
    cached_requests = cached_requests if cached_requests is not None else _cached_requests(checkpoint_dir, batch, target_langs)
    accepted = {str(row['request_key']): dict(cached_requests.get(str(row['request_key']), {})) for row in batch}
    feedback: dict[tuple[str, str], str] = {}
    blocked: set[tuple[str, str]] = set()
    called = False
    for _attempt in range(max_attempts):
        groups: dict[tuple[str, ...], list[dict[str, object]]] = {}
        for row in batch:
            key = str(row['request_key'])
            missing = tuple(lang for lang in target_langs if lang not in accepted[key] and (key, lang) not in blocked)
            if missing:
                pending = dict(row)
                errors = [feedback[(key, lang)] for lang in missing if (key, lang) in feedback]
                if errors:
                    pending['validation_feedback'] = '; '.join(dict.fromkeys(errors))
                groups.setdefault(missing, []).append(pending)
        if not groups:
            break
        for languages, pending in groups.items():
            called = True
            try:
                response = client.translate_batch(pending, list(languages))
            except FatalRelayError:
                raise
            except ResponseTooLarge:
                if len(pending) <= 1 or _attempt + 1 >= max_attempts:
                    raise
                midpoint = len(pending) // 2
                for child in (pending[:midpoint], pending[midpoint:]):
                    values, _ = _execute_batch(client, child, list(languages), checkpoint_dir,
                                               max_attempts - _attempt - 1, accepted)
                    for key, translations in values.items():
                        accepted[key].update(translations)
                continue
            except Exception as exc:
                for row in pending:
                    for lang in languages:
                        cell = (str(row['request_key']), lang)
                        if isinstance(exc, RequestBudgetExceeded) and exc.cells and cell not in exc.cells:
                            continue
                        feedback[cell] = str(exc)
                        if isinstance(exc, RequestBudgetExceeded) or not isinstance(exc, ValueError):
                            blocked.add(cell)
                continue
            by_key = {str(row['request_key']): row for row in pending}
            returned: dict[str, list[dict]] = {}
            invalid_envelope = not isinstance(response, list)
            for item in response if isinstance(response, list) else []:
                if not isinstance(item, dict) or str(item.get('request_key', '')) not in by_key:
                    invalid_envelope = True
                    continue
                returned.setdefault(str(item['request_key']), []).append(item)
            for key, trusted in by_key.items():
                matches = returned.get(key, [])
                for lang in languages:
                    try:
                        if invalid_envelope or len(matches) != 1:
                            raise ValueError('response keys missing, duplicate or unbound')
                        translations = matches[0].get('translations')
                        if not isinstance(translations, dict) or set(translations) - set(languages):
                            raise ValueError('unexpected translation languages')
                        value = _validate_response([trusted], [{'request_key': key, 'translations': {lang: translations.get(lang)}}], [lang])[key][lang]
                        accepted[key][lang] = value
                        feedback.pop((key, lang), None)
                    except ValueError as exc:
                        previous = feedback.get((key, lang))
                        feedback[(key, lang)] = str(exc)
                        if previous == str(exc):
                            blocked.add((key, lang))
            _atomic_write_text(checkpoint, json.dumps({'rows': [
                {'request_key': key, 'translations': value} for key, value in accepted.items() if value
            ]}, ensure_ascii=False))
            if getattr(client, 'runtime', None):
                client.runtime.note_validation('translate', feedback)
    missing = [(key, lang) for key in accepted for lang in target_langs if lang not in accepted[key]]
    if missing:
        raise IncompletePhase(f'translation cells unresolved: {missing[:10]}; accepted cells checkpointed; {list(feedback.values())[:1]}')
    return accepted, not called


def translate_manifest(
    manifest_path: Path,
    *,
    relay_config: Path | None,
    client: TranslationClient | None = None,
    batch_size: int = 60,
    max_batch_chars: int = 48000,
    workers: int = 4,
    max_attempts: int = 3,
) -> ExecutionSummary:
    started = time.perf_counter()
    manifest = load_manifest(manifest_path)
    start_phase(manifest, "api_translate")
    try:
        work_dir = Path(manifest["work_dir"])
        items = _read_jsonl(Path(manifest["inputs"]["items_jsonl"]))
        target_langs = [str(lang).upper() for lang in manifest["inputs"]["target_languages"]]
        seed_memory = _read_json(work_dir / "seed_memory.json")
        representatives: dict[str, dict[str, Any]] = {}
        row_signatures: list[str] = []
        seeded: dict[str, dict[str, str]] = {}
        for row in items:
            signature = _request_signature(row)
            row_signatures.append(signature)
            source = str(row.get("cn") or "")
            seed = seed_memory.get(source)
            normalized_seed = (
                {str(key).upper(): value for key, value in seed.items()}
                if isinstance(seed, dict)
                else {}
            )
            if all(isinstance(normalized_seed.get(lang), str) and normalized_seed[lang].strip() for lang in target_langs):
                seeded[signature] = _validate_response(
                    [_request_row(row, signature)],
                    [{'request_key': signature, 'translations': {lang: normalized_seed[lang] for lang in target_langs}}],
                    target_langs,
                )[signature]
            else:
                representatives.setdefault(signature, row)

        request_by_key: dict[str, dict[str, object]] = {}
        template_specs: dict[str, tuple[ParsedTemplate, list[TranslationSlot]]] = {}
        template_slot_keys: dict[tuple[str, str], str] = {}
        for signature, row in representatives.items():
            if signature in seeded:
                continue
            if should_use_template(row):
                template = parse_template(str(row.get("translation_source") or row.get("cn") or ""))
                slots = translation_slots(template)
                if not slots:
                    raise ValueError(
                        f"structured source row {row.get('key')} has no translatable text slots"
                    )
                template_specs[signature] = (template, slots)
                for slot in slots:
                    segment = _template_request_row(row, "", slot)
                    segment_key = _request_signature(segment)
                    segment["request_key"] = segment_key
                    request_by_key.setdefault(segment_key, segment)
                    template_slot_keys[(signature, slot.slot_key)] = segment_key
            else:
                request_by_key.setdefault(signature, _request_row(row, signature))
        request_rows = list(request_by_key.values())
        if client is None:
            if relay_config is None:
                raise ValueError("relay_config is required when client is not injected")
            client = OpenAICompatibleClient(relay_config, runtime=RelayRuntime(work_dir, limit=min(5, workers)))
        partition_options = {'output_languages': len(target_langs)}
        if not isinstance(client, OpenAICompatibleClient):
            partition_options['compact_contexts'] = False
        smoke_size = min(20, batch_size)
        smoke_candidates = _partition_requests(
            request_rows[:smoke_size],
            max_rows=smoke_size,
            max_chars=max_batch_chars,
            **partition_options,
        )
        smoke_batch = smoke_candidates[0] if smoke_candidates else []
        batches = _partition_requests(
            request_rows[len(smoke_batch):],
            max_rows=batch_size,
            max_chars=max_batch_chars,
            **partition_options,
        )
        client_identity = str(
            getattr(
                client,
                "checkpoint_identity",
                f"{type(client).__module__}.{type(client).__qualname__}",
            )
        )
        strategy = manifest.get("api_strategy") or {}
        model = str(strategy.get("model") or "injected")
        scope = hashlib.sha256(
            json.dumps(
                {
                    "model": model,
                    "provider_host": strategy.get("base_url_host", ""),
                    "provider_path": strategy.get("base_url_path", ""),
                    "client_identity": client_identity,
                    "target_langs": target_langs,
                    "prompt": "translate-v3-program-owned-structure",
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        checkpoint_dir = work_dir / "translation_batches" / scope
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        cached_requests = _cached_requests(checkpoint_dir, request_rows, target_langs)

        translated: dict[str, dict[str, str]] = {}
        reused_cells = sum(len(values) for values in cached_requests.values())
        accepted_cells = reused_cells
        def translation_progress():
            record_progress(manifest, 'api_translate', total=len(request_rows) * len(target_langs),
                            accepted=accepted_cells, reused=reused_cells, started=started)
        translation_progress()
        reused_batches = 0
        batch_count = len(batches) + int(bool(smoke_batch))
        if smoke_batch:
            values, reused = _execute_batch(
                client,
                smoke_batch,
                target_langs,
                checkpoint_dir,
                max_attempts,
                cached_requests,
            )
            translated.update(values)
            accepted_cells += sum(len(value) - len(cached_requests.get(key, {})) for key, value in values.items())
            translation_progress()
            reused_batches += int(reused)
            manifest.setdefault("phase_status", {})["api_smoke"] = "done"
            manifest["api_smoke"] = {
                "ok": True,
                "schema_ok": True,
                "rows": len(smoke_batch),
                "reused_checkpoint": reused,
                "recorded_at": _now(),
            }
            save_manifest(manifest)
        if batches:
            failures = []
            def execute(batch):
                return _execute_batch(client, batch, target_langs, checkpoint_dir, max_attempts, cached_requests)
            for batch, result, error in bounded_results(execute, batches, workers=workers):
                if error:
                    failures.append({'keys': [row['request_key'] for row in batch], 'error': str(error)})
                else:
                    values, reused = result
                    translated.update(values)
                    accepted_cells += sum(len(value) - len(cached_requests.get(key, {})) for key, value in values.items())
                    reused_batches += int(reused)
                translation_progress()
            _atomic_write_text(work_dir / 'translation_failures.json', json.dumps(failures, ensure_ascii=False))
            if failures:
                raise IncompletePhase(f'{len(failures)} translation batches unresolved; healthy batches saved')
        rebuilt: dict[str, dict[str, str]] = {}
        for signature, (template, slots) in template_specs.items():
            rebuilt[signature] = {
                lang: render_translations(
                    template,
                    slots,
                    {
                        slot.slot_key: translated[
                            template_slot_keys[(signature, slot.slot_key)]
                        ][lang]
                        for slot in slots
                    },
                    lang=lang,
                )
                for lang in target_langs
            }
        resolved = {**translated, **rebuilt, **seeded}
        output_rows: list[dict[str, Any]] = []
        for row, signature in zip(items, row_signatures, strict=True):
            if signature not in resolved:
                raise ValueError(f"missing translation for source row {row.get('key')}")
            output_rows.append({**row, "translations": resolved[signature]})

        cache_path = work_dir / "initial_cache.jsonl"
        metrics_path = work_dir / "translation_metrics.json"
        _write_jsonl(cache_path, output_rows)
        summary = ExecutionSummary(
            cache_jsonl=cache_path,
            metrics_json=metrics_path,
            source_rows=len(items),
            unique_api_rows=len(request_rows),
            seeded_rows=len(items) - sum(1 for signature in row_signatures if signature not in seeded),
            batch_count=batch_count,
            reused_batches=reused_batches,
            elapsed_seconds=round(time.perf_counter() - started, 3),
        )
        _atomic_write_text(
            metrics_path,
            json.dumps({**asdict(summary), "cache_jsonl": str(cache_path), "metrics_json": str(metrics_path)}, ensure_ascii=False, indent=2),
        )
        manifest.setdefault("artifacts", {})["initial_cache"] = str(cache_path)
        manifest["artifacts"]["translation_metrics"] = str(metrics_path)
        manifest.setdefault("phase_status", {})["api_smoke"] = "done"
        complete_phase(
            manifest,
            "api_translate",
            started=started,
            metrics={
                "source_rows": summary.source_rows,
                "unique_api_rows": summary.unique_api_rows,
                "batch_count": summary.batch_count,
                "reused_batches": summary.reused_batches,
                "structured_source_rows": len(template_specs),
                "structured_text_segments": len(template_slot_keys),
            },
        )
        return summary
    except BaseException as exc:
        fail_phase(manifest, "api_translate", exc)
        raise
