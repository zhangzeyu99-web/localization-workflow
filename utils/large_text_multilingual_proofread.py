"""Suggestion-only deep proofreading with controller-owned audit and apply."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from utils.relay_runtime import (
    FatalRelayError,
    IncompletePhase,
    MAX_API_CONCURRENCY,
    RequestBudgetExceeded,
    ResponseTooLarge,
    bounded_results,
)
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from utils.large_text_multilingual_executor import (
    _atomic_write_text,
    _read_jsonl,
    _write_jsonl,
    _partition_requests,
    complete_phase,
    fail_phase,
    start_phase,
    record_progress,
)
from utils.large_text_multilingual_runner import load_manifest
from utils.language_config import SUPPORTED_TRANSLATION_LANGUAGES
from utils.localization_quality_policy import requires_name_semantic_check
from utils.quality_harness_terms import is_fixed_glossary_seed
from utils.structured_text_template import (
    ParsedTemplate,
    ReviewSlot,
    aligned_review_slots,
    parse_template,
    render_reviewed_target,
    should_use_template,
)


class ReviewClient(Protocol):
    def review_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]: ...


class AuditClient(Protocol):
    def audit_batch(
        self,
        suggestions: list[dict[str, object]],
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class ProofreadSummary:
    final_cache: Path
    suggestions_jsonl: Path
    audit_jsonl: Path
    summary_json: Path
    reviewed_rows: int
    reviewed_cells: int
    suggested_changes: int
    reverted_changes: int
    changed_rows: int
    changed_cells: int
    elapsed_seconds: float


def _attach_dialogue_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 只使用显式场景边界；既有译文是待审证据，不是人物配置真值。
    groups: dict[tuple[str, str, str], list[int]] = {}
    contexts: dict[int, dict] = {}
    for index, row in enumerate(rows):
        raw = row.get("context") or ""
        try:
            context = raw if isinstance(raw, dict) else json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(context, dict) or context.get("type") != "dialogue" or not context.get("scene") or should_use_template(row):
            continue
        contexts[index] = context
        key = (str(row.get("source_file") or ""), str(row.get("sheet") or ""), str(context["scene"]))
        groups.setdefault(key, []).append(index)
    result = [dict(row) for row in rows]
    for indices in groups.values():
        indices.sort(key=lambda index: (int(rows[index].get("row") or index), index))
        for position, index in enumerate(indices):
            selected = indices if len(indices) <= 48 else indices[max(0, position - 8):position + 9]
            context = contexts[index]
            result[index]["dialogue_evidence"] = {
                "scene": context["scene"], "complete_scene": len(selected) == len(indices),
                "speaker": context.get("speaker", "unknown"),
                "addressee": context.get("addressee", "unknown"),
                "turns": [{field: rows[item].get(field) for field in (
                    "key", "id", "row", "cn", "translation_source", "reference_en", "translations"
                )} for item in selected],
            }
    return result


def _review_signature(row: dict[str, Any], target_langs: list[str]) -> str:
    raw = json.dumps(
        {
            "cn": row.get("cn", ""),
            "translation_source": row.get("translation_source", row.get("cn", "")),
            "source_mode": row.get("source_mode", "cn"),
            "reference_en": row.get("reference_en", ""),
            "reference_en_status": row.get("reference_en_status", "not_requested"),
            "context": row.get("context", ""),
            "dialogue_evidence": row.get("dialogue_evidence") or {},
            "risk_flags": row.get("risk_flags") or [],
            "tokens": row.get("tokens") or [],
            "term_hits": row.get("term_hits") or [],
            "seed_origin": row.get("seed_origin", ""),
            "translations": {
                lang: (row.get("translations") or {}).get(lang, "") for lang in target_langs
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _language_evidence(evidence: object, lang: str) -> dict:
    if not isinstance(evidence, dict):
        return {}
    return {**evidence, "turns": [
        {**turn, "translations": {lang: (turn.get("translations") or {}).get(lang, "")}}
        for turn in evidence.get("turns", [])
    ]}


def _language_context(value: Any, lang: str, *, english_reference: bool = False) -> Any:
    def project(node: Any) -> Any:
        if isinstance(node, list):
            return [project(item) for item in node]
        if isinstance(node, dict):
            result = {}
            for field, item in node.items():
                if (field == 'translations' and isinstance(item, dict)
                        and all(str(key).lower() in SUPPORTED_TRANSLATION_LANGUAGES for key in item)):
                    wanted = {lang, 'EN'} if english_reference else {lang}
                    result[field] = {key: text for key, text in item.items() if str(key).upper() in wanted}
                else:
                    result[field] = project(item)
            return result
        return node

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if not isinstance(parsed, (dict, list)):
            return value
        projected = project(parsed)
        return value if projected == parsed else json.dumps(projected, ensure_ascii=False, sort_keys=True)
    return project(value)


def _language_review_row(row: dict[str, Any], lang: str) -> dict[str, Any]:
    return {**row, 'translations': {lang: (row.get('translations') or {}).get(lang, '')},
            'context': _language_context(row.get('context') or '', lang),
            'term_hits': _language_context(row.get('term_hits') or [], lang, english_reference=True),
            'dialogue_evidence': _language_evidence(row.get('dialogue_evidence'), lang)}


def _review_item_key(row: dict[str, Any], lang: str) -> str:
    projected = _language_review_row(row, lang)
    projected['tokens'] = row.get('tokens') or row.get('protected_tokens') or []
    return _review_signature(projected, [lang])


def _review_row(row: dict[str, Any], review_key: str, target_langs: list[str]) -> dict[str, object]:
    return {
        "review_key": review_key,
        "cn": str(row.get("cn") or ""),
        "translation_source": str(row.get("translation_source") or row.get("cn") or ""),
        "source_mode": str(row.get("source_mode") or "cn"),
        "reference_en": str(row.get("reference_en") or ""),
        "reference_en_status": str(row.get("reference_en_status") or "not_requested"),
        "context": row.get("context") or "",
        "dialogue_evidence": row.get("dialogue_evidence") or {},
        "risk_flags": row.get("risk_flags") or [],
        "protected_tokens": row.get("tokens") or [],
        "term_hits": row.get("term_hits") or [],
        "seed_origin": row.get("seed_origin") or "",
        "name_semantic_check_required": requires_name_semantic_check(row),
        "translations": {
            lang: str((row.get("translations") or {}).get(lang) or "") for lang in target_langs
        },
    }


def _is_high_risk_review_row(row: dict[str, object]) -> bool:
    source = str(row.get("translation_source") or row.get("cn") or "")
    explicit = row.get("risk_flags") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    return bool(
        len(source) > 300
        or len(row.get("protected_tokens") or []) >= 3
        or len(row.get("term_hits") or []) >= 3
        or explicit
        or row.get('name_semantic_check_required')
    )


def _select_sampled_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    high_risk = [row for row in rows if _is_high_risk_review_row(row)]
    low_risk = [row for row in rows if not _is_high_risk_review_row(row)]
    sample_count = max(1, (len(low_risk) + 9) // 10) if low_risk else 0
    sampled_low = sorted(low_risk, key=lambda row: str(row["review_key"]))[:sample_count]
    selected = {str(row["review_key"]) for row in [*high_risk, *sampled_low]}
    return [row for row in rows if str(row["review_key"]) in selected]


def _preserves_protected_tokens(before: str, after: str, tokens: object) -> bool:
    if not isinstance(tokens, list):
        return True
    from utils.large_text_multilingual_gate import _protected_text_parts, protected_token_counts, protected_tokens
    if not _protected_text_parts(before)[0]:
        return all(before.count(str(token)) == after.count(str(token)) for token in tokens if str(token))
    normalized = protected_tokens({'cn': before, 'tokens': tokens})
    return protected_token_counts(before, normalized) == protected_token_counts(
        after, normalized, reference=before)


def _batch_checkpoint(path: Path, version: str, rows: list[dict[str, Any]]) -> Path:
    raw = json.dumps(
        {"version": version, "rows": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return path / f"{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}.jsonl"


def _client_checkpoint_identity(client: object) -> str:
    return str(
        getattr(
            client,
            "checkpoint_identity",
            f"{type(client).__module__}.{type(client).__qualname__}",
        )
    )


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        # Windows os.kill is not a read-only process probe. Query without signaling.
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _acquire_proofread_lock(proof_dir: Path) -> Path:
    lock_path = proof_dir / "proofread.lock"
    payload = json.dumps({"pid": os.getpid(), "started_at": time.time()})
    for _ in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
                existing_pid = int(existing.get("pid") or 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                existing_pid = 0
            if _pid_is_running(existing_pid):
                raise RuntimeError(
                    f"deep proofreading is already running under pid {existing_pid}"
                )
            lock_path.unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        return lock_path
    raise RuntimeError("could not acquire deep proofreading lock")


def _release_proofread_lock(lock_path: Path) -> None:
    try:
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return
    if int(existing.get("pid") or 0) == os.getpid():
        lock_path.unlink(missing_ok=True)


def _load_review_item_checkpoints(
    checkpoint_dir: Path,
    target_langs: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    reusable: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: set[tuple[str, str]] = set()
    allowed_langs = set(target_langs)
    for checkpoint in sorted(checkpoint_dir.glob("*.jsonl")):
        try:
            rows = _read_jsonl(checkpoint)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for row in rows:
            review_key = str(row.get("review_key") or "")
            lang = str(row.get("lang") or "").upper()
            if not review_key or lang not in allowed_langs:
                continue
            try:
                normalized = _validate_suggestions(
                    [{"review_key": review_key}],
                    [row],
                    [lang],
                )[0]
            except ValueError:
                continue
            cache_key = str(row.get('cache_key') or review_key)
            normalized.update(review_key=cache_key, cache_key=cache_key)
            item_key = (cache_key, lang)
            previous = reusable.get(item_key)
            if previous is not None and previous != normalized:
                conflicts.add(item_key)
                continue
            reusable[item_key] = normalized
    for item_key in conflicts:
        reusable.pop(item_key, None)
    return reusable


def _audit_item_key(fix: dict[str, Any]) -> str:
    payload = {key: value for key, value in fix.items() if key not in {'review_key', 'cache_key'}}
    return _batch_checkpoint(Path('.'), 'audit-cell-v1', [payload]).stem


def _rekey_audit(row: dict[str, Any], review_key: str) -> dict[str, Any]:
    result = {**row, 'review_key': review_key}
    for field in ('independent_target_reading', 'rejected_model_decision'):
        if isinstance(result.get(field), dict) and 'review_key' in result[field]:
            result[field] = {**result[field], 'review_key': review_key}
    return result


def _load_audit_item_checkpoints(checkpoint_dir: Path, fixes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    expected = {_audit_item_key(fix): fix for fix in fixes}
    reusable: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for checkpoint in sorted(checkpoint_dir.glob('*.jsonl')):
        try:
            records = _read_jsonl(checkpoint)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for record in records:
            key = str(record.get('cache_key') or '')
            fix = expected.get(key)
            if fix is None:
                continue
            try:
                normalized = _validate_audit([fix], [_rekey_audit(record, fix['review_key'])])[(fix['review_key'], fix['lang'])]
            except ValueError:
                continue
            normalized = _rekey_audit(normalized, key)
            if key in reusable and reusable[key] != normalized:
                conflicts.add(key)
            reusable[key] = normalized
    return {key: row for key, row in reusable.items() if key not in conflicts}


def _validate_suggestions(
    request_rows: list[dict[str, object]],
    suggestions: list[dict[str, object]],
    target_langs: list[str],
) -> list[dict[str, Any]]:
    trusted_by_key = {str(row["review_key"]): row for row in request_rows}
    current_by_cell = {
        (str(row["review_key"]), lang): str(
            ((row.get("translations") or {}).get(lang) or "")
        )
        for row in request_rows
        for lang in target_langs
    }
    expected = {
        (str(row["review_key"]), lang) for row in request_rows for lang in target_langs
    }
    actual = {
        (str(row.get("review_key") or ""), str(row.get("lang") or "").upper())
        for row in suggestions
    }
    if expected != actual or len(suggestions) != len(expected):
        raise ValueError(
            f"review coverage mismatch: missing={sorted(expected - actual)}, extras={sorted(actual - expected)}"
        )
    validated: list[dict[str, Any]] = []
    for row in suggestions:
        from utils.review_findings import unresolved_review_detail
        unresolved = unresolved_review_detail(row)
        if unresolved:
            raise ValueError(unresolved)
        status = str(row.get("status") or "").upper()
        if status not in {"KEEP", "FIX"}:
            raise ValueError(f"invalid review status: {status}")
        if row.get('suggested') is not None and not isinstance(row['suggested'], str):
            raise ValueError('review suggestion must be text, not context references or objects')
        suggested = str(row.get("suggested") or "")
        if not suggested.strip():
            cell = (str(row["review_key"]), str(row["lang"]).upper())
            if status == "KEEP":
                suggested = current_by_cell.get(cell, "")
            if not suggested.strip():
                raise ValueError("review suggestion cannot be blank")
        current = current_by_cell.get((str(row["review_key"]), str(row["lang"]).upper()), "")
        if status == "KEEP" and current and suggested != current:
            raise ValueError("KEEP must preserve the current target exactly; use FIX for a change")
        from utils.structured_text_template import json_structure_issues
        from utils.xlsx_translation_writeback import cell_text_issues
        if storage := cell_text_issues(suggested):
            raise ValueError(f'review suggestion storage integrity failed: {storage}')
        trusted = trusted_by_key[str(row['review_key'])]
        integrity = json_structure_issues(str(trusted.get('cn') or ''), suggested)
        if integrity:
            raise ValueError(f"review suggestion JSON integrity failed: {integrity}")
        validated.append(
            {
                "review_key": str(row["review_key"]),
                "lang": str(row["lang"]).upper(),
                "status": status,
                "suggested": suggested,
                "reason": str(row.get("reason") or ""),
                "owner": str(row.get("owner") or "api"),
            }
        )
    return validated


def _validate_audit(
    fixes: list[dict[str, Any]],
    decisions: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, Any]]:
    expected = {(row["review_key"], row["lang"]) for row in fixes}
    actual = {
        (str(row.get("review_key") or ""), str(row.get("lang") or "").upper())
        for row in decisions
    }
    if expected != actual or len(decisions) != len(expected):
        raise ValueError(
            f"audit coverage mismatch: missing={sorted(expected - actual)}, extras={sorted(actual - expected)}"
        )
    result: dict[tuple[str, str], dict[str, Any]] = {}
    trusted_fixes = {(row["review_key"], row["lang"]): row for row in fixes}
    for row in decisions:
        from utils.review_findings import unresolved_review_detail
        unresolved = unresolved_review_detail(row)
        if unresolved:
            raise ValueError(unresolved)
        decision = str(row.get("decision") or "").upper()
        if decision not in {"ACCEPT", "REVERT", "REVISE"}:
            raise ValueError(f"invalid audit decision: {decision}")
        if row.get('final') is not None and not isinstance(row['final'], str):
            raise ValueError('audit final must be text, not context references or objects')
        final = str(row.get("final") or "")
        if decision in {"ACCEPT", "REVISE"} and not final.strip():
            raise ValueError("accepted audit decision requires final text")
        fix = trusted_fixes[(str(row["review_key"]), str(row["lang"]).upper())]
        from utils.structured_text_template import json_structure_issues
        selected = str(fix.get('current', fix.get('original', '')) or '') if decision == 'REVERT' else final
        from utils.xlsx_translation_writeback import cell_text_issues
        if storage := cell_text_issues(selected):
            raise ValueError(f'audit final storage integrity failed: {storage}')
        integrity = json_structure_issues(str(fix.get('cn') or ''), selected)
        if integrity:
            raise ValueError(f"audit {decision} JSON integrity failed: {integrity}")
        if fix.get('status') == 'KEEP' and decision == 'REVERT':
            raise ValueError('A KEEP audit must ACCEPT the current target or REVISE it; REVERT is unresolved')
        if is_fixed_glossary_seed(fix) and selected != str(fix.get('current') or ''):
            raise ValueError('glossary_semantic_conflict: do not silently change or restore an exact glossary seed. '
                             'For style-only edits, audit the current term; for a meaning defect, report '
                             'unresolved_issues, resolve the actual glossary, and recheck the affected scope '
                             'in a new task directory when the source snapshot changes.')
        from utils.semantic_regression import known_semantic_regressions

        if known_semantic_regressions(fix, str(row["lang"]), selected):
            raise ValueError("known semantic regression in accepted audit final")
        check = row.get("semantic_check")
        if fix.get("semantic_check_required") and decision in {"ACCEPT", "REVISE"}:
            if not isinstance(check, dict) or any(
                not isinstance(check.get(field), str) or not check[field].strip()
                for field in ("source_meaning", "final_meaning")
            ) or any(check.get(field) is not True for field in (
                "meaning_preserved", "roles_preserved", "tone_preserved"
            )):
                raise ValueError("dialogue semantic evidence missing or contradicts accepted change")
        if fix.get('name_semantic_check_required'):
            if not _preserves_protected_tokens(str(fix.get('cn') or ''), selected, fix.get('protected_tokens')):
                raise ValueError('name final must preserve protected tokens; cannot restore an unaudited target')
            if not isinstance(check, dict) or check.get('target_text') != selected or any(
                not isinstance(check.get(field), str) or not check[field].strip()
                for field in ('source_meaning', 'final_meaning')
            ) or any(check.get(field) is not True for field in (
                'meaning_preserved', 'roles_preserved', 'tone_preserved',
                'head_and_modifiers_preserved', 'no_invented_entities', 'natural_target'
            )):
                raise ValueError('name semantic evidence missing or contradicts selected final')
            reading = row.get('independent_target_reading')
            if not isinstance(reading, dict) or reading.get('text') != selected or any(
                not isinstance(reading.get(field), str) or not reading[field].strip()
                for field in ('meaning', 'predicate_object', 'tone')
            ):
                raise ValueError('name semantic reading must be bound to the selected final text')
        normalized = {
            "review_key": str(row["review_key"]),
            "lang": str(row["lang"]).upper(),
            "decision": decision,
            "final": final,
            "reason": str(row.get("reason") or ""),
            **({"semantic_check": check} if isinstance(check, dict) else {}),
            **({"independent_target_reading": row["independent_target_reading"]}
               if isinstance(row.get("independent_target_reading"), dict) else {}),
            **({"rejected_model_decision": row["rejected_model_decision"]}
               if isinstance(row.get("rejected_model_decision"), dict) else {}),
        }
        result[(normalized["review_key"], normalized["lang"])] = normalized
    return result


def _retry_validated_cells(
    batch: list[dict[str, Any]],
    request: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    validate: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    checkpoint: Path,
    cache_keys: dict[tuple[str, str], str],
    *, phase: str = 'review', max_attempts: int = 3, runtime=None,
) -> list[dict[str, Any]]:
    """Checkpoint sound cells immediately; retry only unresolved input cells."""
    def cell(row):
        return str(row.get('review_key') or ''), str(row.get('lang') or '').upper()

    trusted = {cell(row): row for row in batch}
    accepted: dict[tuple[str, str], dict[str, Any]] = {}
    feedback: dict[tuple[str, str], str] = {}
    blocked: set[tuple[str, str]] = set()
    for attempt in range(max_attempts):
        previous_feedback = feedback
        pending = {key: row for key, row in trusted.items() if key not in accepted and key not in blocked}
        if not pending:
            break
        wire_rows = [{**row, **({'validation_feedback': feedback[key]} if key in feedback else {})}
                     for key, row in pending.items()]
        try:
            response = request(wire_rows)
            if not isinstance(response, list) or any(not isinstance(row, dict) for row in response):
                raise ValueError(f'{phase} coverage mismatch: response must be an array of cell objects')
            counts = Counter(cell(row) for row in response)
            extras = counts.keys() - pending.keys()
            if extras:
                # Unbound output cannot be silently dropped to claim full coverage.
                raise ValueError(f'{phase} coverage mismatch: unexpected cells={sorted(extras)}; return only requested cells')
        except RequestBudgetExceeded as exc:
            blocked.update(exc.cells or pending.keys())
            feedback.update({key: str(exc) for key in blocked})
            continue
        except ResponseTooLarge:
            if len(wire_rows) <= 1 or attempt + 1 >= max_attempts:
                raise
            midpoint = len(wire_rows) // 2
            for suffix, child in (('left', wire_rows[:midpoint]), ('right', wire_rows[midpoint:])):
                values = _retry_validated_cells(child, request, validate,
                    checkpoint.with_name(checkpoint.stem + '.' + suffix + '.jsonl'), cache_keys,
                    phase=phase, max_attempts=max_attempts - attempt - 1, runtime=runtime)
                accepted.update({cell(row): row for row in values})
            _write_jsonl(checkpoint, [{**row, 'cache_key': cache_keys[key]} for key, row in accepted.items()])
            if not blocked:
                return [accepted[key] for key in trusted]
            break
        except ValueError as exc:
            feedback = {key: str(exc) for key in pending}
        else:
            by_cell = {cell(row): row for row in response}
            feedback = {}
            for key, row in pending.items():
                if counts[key] != 1:
                    feedback[key] = f'{phase} coverage mismatch: expected exactly one result for {key}, got {counts[key]}'
                    continue
                try:
                    accepted[key] = validate(row, by_cell[key])
                except ValueError as exc:
                    feedback[key] = str(exc)
            if accepted:
                _write_jsonl(checkpoint, [{**row, 'cache_key': cache_keys[key]} for key, row in accepted.items()])
            if not feedback and not blocked:
                return [accepted[key] for key in trusted]
        if runtime:
            runtime.note_validation(phase, feedback)
        if feedback == previous_feedback:
            break
    raise ValueError(f'cell validation failed after {attempt + 1} attempts: {feedback}; exhausted={sorted(blocked)}')


VALID_AUDIT_POLICIES = ("all", "risk_tiered")
_NUMERIC_OR_SYMBOL_RISK_RE = re.compile(r"(?:\d|%|％|\{[^{}]*\}|<[^>]+>)")


def _requires_independent_audit(
    fix: dict[str, Any],
    *,
    low_risk_sample_rate: float = 0.10,
) -> tuple[bool, str]:
    """Classify whether a reviewed cell requires independent LLM audit under risk_tiered policy."""
    if str(fix.get("status") or "").upper() != "KEEP":
        return True, "reviewer_fix"
    if fix.get("unresolved_issues"):
        return True, "unresolved_issues"
    if fix.get("semantic_check_required") or fix.get("name_semantic_check_required"):
        return True, "semantic_check_required"
    if str(fix.get("seed_origin") or "") == "glossary_exact":
        return True, "glossary_exact"
    if str(fix.get("source_mode") or "cn") != "cn":
        return True, "multi_source"
    if fix.get("risk_flags"):
        return True, "risk_flags"
    if fix.get("term_hits"):
        return True, "term_hits"
    if fix.get("protected_tokens"):
        return True, "protected_tokens"
    review_key = str(fix.get("review_key") or "")
    context = fix.get("context")
    if ":segment:" in review_key or (isinstance(context, dict) and "whole_cell_proposed" in context):
        return True, "structured_segment"
    evidence = fix.get("dialogue_evidence")
    if isinstance(evidence, dict) and evidence.get("turns"):
        return True, "dialogue_evidence"
    source = str(fix.get("cn") or "")
    current = str(fix.get("current") or "")
    if _NUMERIC_OR_SYMBOL_RISK_RE.search(source) or _NUMERIC_OR_SYMBOL_RISK_RE.search(current):
        return True, "numeric_or_markup"
    rate = max(0.0, min(1.0, float(low_risk_sample_rate)))
    if rate > 0.0:
        bucket = hashlib.sha256(f"{review_key}:{fix.get('lang', '')}".encode("utf-8")).digest()[0] / 256.0
        if bucket < rate:
            return True, "low_risk_sample"
    return False, "auto_keep_low_risk"


def run_deep_proofread(
    manifest_path: Path,
    *,
    initial_cache: Path,
    reviewer: ReviewClient,
    auditor: AuditClient,
    batch_size: int = 60,
    workers: int = 4,
    audit_policy: str = "all",
    low_risk_audit_sample_rate: float = 0.10,
) -> ProofreadSummary:
    if audit_policy not in VALID_AUDIT_POLICIES:
        raise ValueError(f"unsupported audit_policy: {audit_policy}; expected one of {VALID_AUDIT_POLICIES}")
    overall_started = time.perf_counter()
    manifest = load_manifest(manifest_path)
    target_langs = [str(lang).upper() for lang in manifest["inputs"]["target_languages"]]
    rows = _attach_dialogue_evidence(_read_jsonl(initial_cache))
    signatures = [_review_signature(row, target_langs) for row in rows]
    representatives: dict[str, dict[str, Any]] = {}
    for row, signature in zip(rows, signatures, strict=True):
        representatives.setdefault(signature, row)
    source_review_rows = [
        _review_row(row, signature, target_langs)
        for signature, row in representatives.items()
    ]
    if str(manifest.get("inputs", {}).get("proofread_mode") or "full") == "sampled":
        source_review_rows = _select_sampled_rows(source_review_rows)
    selected_signatures = [str(row["review_key"]) for row in source_review_rows]
    review_rows: list[dict[str, object]] = []
    structured_cells: dict[
        tuple[str, str], tuple[ParsedTemplate, list[ReviewSlot]]
    ] = {}
    structured_signatures: set[str] = set()
    for signature in selected_signatures:
        row = representatives[signature]
        if not should_use_template(row):
            review_rows.append(_review_row(row, signature, target_langs))
            continue
        per_language: dict[str, tuple[ParsedTemplate, list[ReviewSlot]]] = {}
        source_text = str(row.get("translation_source") or row.get("cn") or "")
        for lang in target_langs:
            target_text = str((row.get("translations") or {}).get(lang) or "")
            per_language[lang] = aligned_review_slots(source_text, target_text)
        slot_count = len(per_language[target_langs[0]][1])
        if not slot_count or any(len(value[1]) != slot_count for value in per_language.values()):
            raise ValueError(f"structured review slot mismatch for source row {row.get('key')}")
        structured_signatures.add(signature)
        for lang, value in per_language.items():
            structured_cells[(signature, lang)] = value
        for index in range(slot_count):
            slots = {lang: per_language[lang][1][index] for lang in target_langs}
            source_slot = slots[target_langs[0]].source
            if any(slot.source != source_slot for slot in slots.values()):
                raise ValueError(f"structured review source slot mismatch for row {row.get('key')}")
            review_key = f"{signature}:segment:{index}"
            term_hits = [
                hit
                for hit in (row.get("term_hits") or [])
                if isinstance(hit, dict)
                and str(hit.get("source") or hit.get("CN") or hit.get("term") or "")
                in source_slot
            ]
            context = row.get('context')
            slot_context = {**context, 'segment_source_context': slots[target_langs[0]].source_context} if isinstance(context, dict) else slots[target_langs[0]].source_context
            slot_name_check = requires_name_semantic_check({**row, 'cn': source_slot, 'term_hits': term_hits})
            review_rows.append(
                {
                    "review_key": review_key,
                    "cn": source_slot,
                    "translation_source": source_slot,
                    "source_mode": "cn",
                    "reference_en": "",
                    "reference_en_status": "not_requested",
                    "context": slot_context,
                    "seed_origin": row.get('seed_origin') or '',
                    "name_semantic_check_required": slot_name_check,
                    "risk_flags": row.get("risk_flags") or [],
                    "protected_tokens": [],
                    "term_hits": term_hits,
                    "translations": {lang: slots[lang].target for lang in target_langs},
                }
            )
    proof_dir = Path(manifest["work_dir"]) / "deep_proofread"
    proof_dir.mkdir(parents=True, exist_ok=True)
    proofread_lock = _acquire_proofread_lock(proof_dir)
    suggestions_path = proof_dir / "review_suggestions.jsonl"
    audit_path = proof_dir / "audit_decisions.jsonl"
    final_cache = proof_dir / "final_cache.jsonl"
    summary_path = proof_dir / "proofread_apply_summary.json"

    review_started = time.perf_counter()
    try:
        start_phase(manifest, "subagent_review")
        suggestions: list[dict[str, object]] = []
        review_scope = hashlib.sha256(
            f"review-v7-existing-short-baseline:{_client_checkpoint_identity(reviewer)}".encode("utf-8")
        ).hexdigest()[:16]
        review_checkpoint_dir = proof_dir / "review_batches" / review_scope
        review_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        saved_items = _load_review_item_checkpoints(review_checkpoint_dir, target_langs)
        review_cache_keys = {(str(row['review_key']), lang): _review_item_key(row, lang)
                             for row in review_rows for lang in target_langs}
        reusable: dict[tuple[str, str], dict[str, Any]] = {}
        for row in review_rows:
            for lang in target_langs:
                cell = (str(row['review_key']), lang)
                cached = saved_items.get((review_cache_keys[cell], lang)) or saved_items.get(cell)
                if cached is None:
                    continue
                try:
                    reusable[cell] = _validate_suggestions([row], [{**cached, 'review_key': cell[0]}], [lang])[0]
                except ValueError:
                    continue
        if reusable:
            _write_jsonl(review_checkpoint_dir / 'reused_items.jsonl', [
                {**row, 'cache_key': review_cache_keys[cell]} for cell, row in reusable.items()
            ])
        reused_review_cells = len(reusable)
        def review_progress():
            record_progress(manifest, 'subagent_review', total=len(review_cache_keys),
                            accepted=len(reusable), reused=reused_review_cells, started=review_started)
        review_progress()
        review_jobs: list[tuple[list[dict[str, object]], str, Path]] = []
        for lang in target_langs:
            missing = [
                _language_review_row(row, lang)
                for row in review_rows
                if (str(row["review_key"]), lang) not in reusable
            ]
            for batch in _partition_requests(missing, max_rows=batch_size, max_chars=48000, output_languages=1):
                checkpoint = _batch_checkpoint(
                    review_checkpoint_dir,
                    f"review-v2:{lang}",
                    batch,
                )
                review_jobs.append((batch, lang, checkpoint))

        def review_missing(
            job: tuple[list[dict[str, object]], str, Path],
        ) -> list[dict[str, Any]]:
            batch, lang, checkpoint = job
            return _retry_validated_cells(
                [{**row, 'lang': lang} for row in batch],
                lambda pending: reviewer.review_batch(pending, [lang]),
                lambda row, suggestion: _validate_suggestions([row], [suggestion], [lang])[0],
                checkpoint, review_cache_keys,
                runtime=getattr(reviewer, 'runtime', None),
            )

        # Prepare audit helpers early so multi-language runs can stream finished languages
        # directly into audit without waiting for slow sibling languages to finish review.
        trusted_rows = {str(row['review_key']): row for row in review_rows}
        audit_scope = hashlib.sha256(
            f"audit-v10-existing-short-baseline:{_client_checkpoint_identity(auditor)}".encode("utf-8")
        ).hexdigest()[:16]
        audit_checkpoint_dir = proof_dir / "audit_batches" / audit_scope
        audit_checkpoint_dir.mkdir(parents=True, exist_ok=True)

        def plain_leaves(text: str) -> list[str]:
            return [''.join(part.value for part in parts if part.kind == 'text')
                    for parts in parse_template(text).leaves.values()]

        def build_lang_audit_plan(
            lang: str,
            lang_validated: list[dict[str, Any]],
        ) -> tuple[
            list[dict[str, Any]],
            dict[tuple[str, str], dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, object]],
            list[tuple[list[dict[str, Any]], Path]],
            dict[tuple[str, str], str],
            Counter[str],
            int,
            int,
        ]:
            suggested_cells = {(row['review_key'], row['lang']): row['suggested'] for row in lang_validated}
            whole_contexts: dict[tuple[str, str], dict[str, Any]] = {}
            for (signature, cell_lang), (template, slots) in structured_cells.items():
                if cell_lang != lang:
                    continue
                values = {slot.slot_key: suggested_cells[(f'{signature}:segment:{index}', lang)]
                          for index, slot in enumerate(slots)}
                proposed = render_reviewed_target(template, slots, values)
                whole_contexts[(signature, lang)] = {
                    'whole_cell_source': plain_leaves(str(representatives[signature].get('translation_source') or representatives[signature]['cn'])),
                    'whole_cell_proposed': plain_leaves(proposed),
                }
            lang_fixes: list[dict[str, Any]] = []
            lang_legacy_fixes: dict[tuple[str, str], dict[str, Any]] = {}
            for suggestion in lang_validated:
                trusted = trusted_rows[suggestion['review_key']]
                fix = {
                    **suggestion,
                    **{field: trusted.get(field) for field in (
                        'cn', 'translation_source', 'source_mode', 'reference_en',
                        'reference_en_status', 'context', 'risk_flags',
                        'protected_tokens', 'term_hits', 'dialogue_evidence',
                        'seed_origin', 'name_semantic_check_required',
                    )},
                    'current': (trusted.get('translations') or {}).get(suggestion['lang'], ''),
                    'dialogue_evidence': _language_evidence(trusted.get('dialogue_evidence'), suggestion['lang']),
                    'semantic_check_required': bool(trusted.get('dialogue_evidence')) or bool(trusted.get('name_semantic_check_required')) or any(
                        'dialogue' in str(flag).lower() or 'idiom' in str(flag).lower()
                        for flag in (trusted.get('risk_flags') or [])
                    ),
                }
                lang_legacy_fixes[(fix['review_key'], fix['lang'])] = {**fix, 'context': str(fix.get('context') or '')}
                fix['context'] = _language_context(fix.get('context') or '', fix['lang'])
                signature = str(fix['review_key']).split(':segment:')[0]
                if (signature, fix['lang']) in whole_contexts:
                    fix['context'] = {'segment_context': fix['context'], **whole_contexts[(signature, fix['lang'])]}
                fix['term_hits'] = _language_context(fix.get('term_hits') or [], fix['lang'], english_reference=True)
                lang_fixes.append(fix)

            lang_decisions: list[dict[str, object]] = []
            lang_tiers: Counter[str] = Counter()
            lang_api_fixes: list[dict[str, Any]] = []
            lang_auto_low = 0
            lang_sampled_low = 0
            if audit_policy == "risk_tiered":
                for fix in lang_fixes:
                    needs_api, tier = _requires_independent_audit(
                        fix, low_risk_sample_rate=low_risk_audit_sample_rate
                    )
                    lang_tiers[tier] += 1
                    if needs_api:
                        if tier == "low_risk_sample":
                            lang_sampled_low += 1
                        lang_api_fixes.append(fix)
                    else:
                        lang_auto_low += 1
                        lang_decisions.append(
                            {
                                "review_key": fix["review_key"],
                                "lang": fix["lang"],
                                "decision": "ACCEPT",
                                "final": fix["current"],
                                "reason": "Auto-accepted low-risk KEEP under risk_tiered audit policy.",
                                "audit_tier": tier,
                            }
                        )
            else:
                lang_api_fixes = list(lang_fixes)
                lang_tiers["all_full_audit"] = len(lang_fixes)

            lang_cache_keys = {(row['review_key'], row['lang']): _audit_item_key(row) for row in lang_api_fixes}
            lang_reusable_audits = _load_audit_item_checkpoints(audit_checkpoint_dir, lang_api_fixes)
            lang_audit_jobs: list[tuple[list[dict[str, Any]], Path]] = []
            for batch in _partition_requests(lang_api_fixes, max_rows=batch_size, max_chars=48000, output_languages=1):
                missing = [row for row in batch if lang_cache_keys[(row['review_key'], row['lang'])] not in lang_reusable_audits]
                if missing:
                    legacy = _batch_checkpoint(
                        audit_checkpoint_dir,
                        'audit-v1',
                        [lang_legacy_fixes[(row['review_key'], row['lang'])] for row in batch],
                    )
                    if legacy.exists():
                        records = _read_jsonl(legacy)
                        if not any('cache_key' in row for row in records):
                            accepted = _validate_audit(batch, records)
                            _write_jsonl(_batch_checkpoint(audit_checkpoint_dir, 'audit-v1', batch), [
                                {**row, 'cache_key': lang_cache_keys[cell]} for cell, row in accepted.items()
                            ])
                            lang_decisions.extend(accepted.values())
                            continue
                for row in batch:
                    cached = lang_reusable_audits.get(lang_cache_keys[(row['review_key'], row['lang'])])
                    if cached is not None:
                        lang_decisions.append(_rekey_audit(cached, row['review_key']))
                if missing:
                    lang_audit_jobs.append((missing, _batch_checkpoint(audit_checkpoint_dir, 'audit-v1', missing)))
            return (
                lang_fixes,
                lang_legacy_fixes,
                lang_api_fixes,
                lang_decisions,
                lang_audit_jobs,
                lang_cache_keys,
                lang_tiers,
                lang_auto_low,
                lang_sampled_low,
            )

        streaming_pipeline = len(target_langs) > 1 and max(1, workers) > 1 and bool(review_jobs)
        streamed_audit_state: dict[str, Any] = {
            "enabled": False,
            "fixes": [],
            "api_audit_fixes": [],
            "decisions": [],
            "audit_jobs": [],
            "audit_failures": [],
            "audit_tier_breakdown": Counter(),
            "auto_accepted_low_risk_cells": 0,
            "sampled_low_risk_cells": 0,
            "merge_started": None,
            "reused_audit_cells": 0,
        }

        if streaming_pipeline:
            streamed_audit_state["enabled"] = True
            streamed_audit_state["merge_started"] = time.perf_counter()
            pool_workers = max(1, min(MAX_API_CONCURRENCY, workers))
            remaining_by_lang: Counter[str] = Counter(lang for _, lang, _ in review_jobs)
            failed_langs: set[str] = set()
            review_failures: list[dict[str, str]] = []
            audit_failures: list[dict[str, str]] = []
            audit_cache_keys_all: dict[tuple[str, str], str] = {}
            queued_reviews = deque(review_jobs)
            queued_audits = deque()
            launched_audit_langs: set[str] = set()

            def enqueue_lang_audit(lang: str) -> None:
                if lang in launched_audit_langs or lang in failed_langs:
                    return
                launched_audit_langs.add(lang)
                lang_suggestions = [reusable[(str(row["review_key"]), lang)] for row in review_rows]
                lang_validated = _validate_suggestions(review_rows, lang_suggestions, [lang])
                (
                    lang_fixes,
                    _lang_legacy,
                    lang_api_fixes,
                    lang_decisions,
                    lang_audit_jobs,
                    lang_cache_keys,
                    lang_tiers,
                    lang_auto_low,
                    lang_sampled_low,
                ) = build_lang_audit_plan(lang, lang_validated)
                streamed_audit_state["fixes"].extend(lang_fixes)
                streamed_audit_state["api_audit_fixes"].extend(lang_api_fixes)
                streamed_audit_state["decisions"].extend(lang_decisions)
                streamed_audit_state["reused_audit_cells"] += len(lang_decisions)
                streamed_audit_state["audit_jobs"].extend(lang_audit_jobs)
                streamed_audit_state["audit_tier_breakdown"].update(lang_tiers)
                streamed_audit_state["auto_accepted_low_risk_cells"] += lang_auto_low
                streamed_audit_state["sampled_low_risk_cells"] += lang_sampled_low
                audit_cache_keys_all.update(lang_cache_keys)
                queued_audits.extend(lang_audit_jobs)

            def run_streamed_audit(job: tuple[list[dict[str, Any]], Path]) -> list[dict[str, object]]:
                batch, checkpoint = job
                return _retry_validated_cells(
                    batch,
                    auditor.audit_batch,
                    lambda row, decision: _validate_audit([row], [decision])[(row['review_key'], row['lang'])],
                    checkpoint,
                    audit_cache_keys_all,
                    phase='audit',
                    runtime=getattr(auditor, 'runtime', None),
                )

            # Languages already 100% reused in review can enter audit immediately.
            for lang in target_langs:
                if remaining_by_lang[lang] == 0:
                    enqueue_lang_audit(lang)

            pool = ThreadPoolExecutor(max_workers=pool_workers)
            pending_futures: dict[Any, tuple[str, Any]] = {}
            try:
                def fill_pool() -> None:
                    while len(pending_futures) < pool_workers and (queued_audits or queued_reviews):
                        if queued_audits:
                            kind, job, fn = "audit", queued_audits.popleft(), run_streamed_audit
                        else:
                            kind, job, fn = "review", queued_reviews.popleft(), review_missing
                        pending_futures[pool.submit(fn, job)] = (kind, job)

                fill_pool()
                while pending_futures:
                    done, _ = wait(pending_futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        kind, job = pending_futures.pop(future)
                        try:
                            output = future.result()
                        except FatalRelayError:
                            raise
                        except Exception as exc:
                            if kind == "review":
                                _, lang, checkpoint = job
                                failed_langs.add(lang)
                                remaining_by_lang[lang] -= 1
                                review_failures.append({'checkpoint': str(checkpoint), 'error': str(exc)})
                            else:
                                audit_failures.append({'checkpoint': str(job[1]), 'error': str(exc)})
                        else:
                            if kind == "review":
                                _, lang, _ = job
                                for suggestion in output:
                                    reusable[(suggestion["review_key"], suggestion["lang"])] = suggestion
                                remaining_by_lang[lang] -= 1
                                review_progress()
                                if remaining_by_lang[lang] == 0 and lang not in failed_langs:
                                    enqueue_lang_audit(lang)
                            else:
                                streamed_audit_state["decisions"].extend(output)
                    fill_pool()
            finally:
                for future in pending_futures:
                    future.cancel()
                pool.shutdown(wait=True, cancel_futures=True)

            streamed_audit_state["audit_failures"] = audit_failures
            _atomic_write_text(proof_dir / 'review_failures.json', json.dumps(review_failures, ensure_ascii=False))
            if review_failures:
                raise IncompletePhase(
                    f"{len(review_failures)} review batches unresolved; healthy cells saved; {review_failures[0]['error']}"
                )
        elif review_jobs:
            failures = []
            for job, batch_suggestions, error in bounded_results(review_missing, review_jobs, workers=workers):
                if error:
                    failures.append({'checkpoint': str(job[2]), 'error': str(error)})
                else:
                    for suggestion in batch_suggestions:
                        reusable[(suggestion["review_key"], suggestion["lang"])] = suggestion
                review_progress()
            _atomic_write_text(proof_dir / 'review_failures.json', json.dumps(failures, ensure_ascii=False))
            if failures:
                raise IncompletePhase(f"{len(failures)} review batches unresolved; healthy cells saved; {failures[0]['error']}")
        suggestions = [
            reusable[(str(row["review_key"]), lang)]
            for row in review_rows
            for lang in target_langs
        ]
        validated = _validate_suggestions(review_rows, suggestions, target_langs)
        _write_jsonl(suggestions_path, validated)
        complete_phase(
            manifest,
            "subagent_review",
            started=review_started,
            metrics={
                "reviewed_unique_rows": len(source_review_rows),
                "reviewed_text_segments": len(review_rows),
                "reviewed_cells": len(validated),
                "review_api_batches": len(review_jobs),
                "review_reused_cells": len(validated)
                - sum(len(batch) for batch, _, _ in review_jobs),
                "streaming_language_pipeline": streamed_audit_state["enabled"],
            },
        )
    except BaseException as exc:
        fail_phase(manifest, "subagent_review", exc)
        _release_proofread_lock(proofread_lock)
        raise

    merge_started = streamed_audit_state["merge_started"] or time.perf_counter()
    try:
        start_phase(manifest, "controller_merge")
        if streamed_audit_state["enabled"]:
            fixes = streamed_audit_state["fixes"]
            api_audit_fixes = streamed_audit_state["api_audit_fixes"]
            decisions = streamed_audit_state["decisions"]
            audit_jobs = streamed_audit_state["audit_jobs"]
            audit_tier_breakdown = streamed_audit_state["audit_tier_breakdown"]
            auto_accepted_low_risk_cells = streamed_audit_state["auto_accepted_low_risk_cells"]
            sampled_low_risk_cells = streamed_audit_state["sampled_low_risk_cells"]
            reused_audit_cells = streamed_audit_state["reused_audit_cells"]
            audit_failures = streamed_audit_state["audit_failures"]
            record_progress(manifest, 'controller_merge', total=len(fixes),
                            accepted=len(decisions), reused=reused_audit_cells, started=merge_started)
            _atomic_write_text(proof_dir / 'audit_failures.json', json.dumps(audit_failures, ensure_ascii=False))
            if audit_failures:
                raise IncompletePhase(
                    f"{len(audit_failures)} audit batches unresolved; healthy cells saved; {audit_failures[0]['error']}"
                )
        else:
            fixes = []
            api_audit_fixes = []
            decisions = []
            audit_jobs = []
            audit_cache_keys: dict[tuple[str, str], str] = {}
            audit_tier_breakdown = Counter()
            auto_accepted_low_risk_cells = 0
            sampled_low_risk_cells = 0
            for lang in target_langs:
                lang_validated = [item for item in validated if item["lang"] == lang]
                (
                    lang_fixes,
                    _lang_legacy,
                    lang_api_fixes,
                    lang_decisions,
                    lang_audit_jobs,
                    lang_cache_keys,
                    lang_tiers,
                    lang_auto_low,
                    lang_sampled_low,
                ) = build_lang_audit_plan(lang, lang_validated)
                fixes.extend(lang_fixes)
                api_audit_fixes.extend(lang_api_fixes)
                decisions.extend(lang_decisions)
                audit_jobs.extend(lang_audit_jobs)
                audit_cache_keys.update(lang_cache_keys)
                audit_tier_breakdown.update(lang_tiers)
                auto_accepted_low_risk_cells += lang_auto_low
                sampled_low_risk_cells += lang_sampled_low

            def audit_missing(
                job: tuple[list[dict[str, Any]], Path],
            ) -> list[dict[str, object]]:
                batch, checkpoint = job
                return _retry_validated_cells(
                    batch, auditor.audit_batch,
                    lambda row, decision: _validate_audit([row], [decision])[(row['review_key'], row['lang'])],
                    checkpoint, audit_cache_keys, phase='audit', runtime=getattr(auditor, 'runtime', None),
                )

            reused_audit_cells = len(decisions)
            def audit_progress():
                record_progress(manifest, 'controller_merge', total=len(fixes),
                                accepted=len(decisions), reused=reused_audit_cells, started=merge_started)
            audit_progress()
            if audit_jobs:
                failures = []
                for job, batch_decisions, error in bounded_results(audit_missing, audit_jobs, workers=workers):
                    if error:
                        failures.append({'checkpoint': str(job[1]), 'error': str(error)})
                    else:
                        decisions.extend(batch_decisions)
                    audit_progress()
                _atomic_write_text(proof_dir / 'audit_failures.json', json.dumps(failures, ensure_ascii=False))
                if failures:
                    raise IncompletePhase(f"{len(failures)} audit batches unresolved; healthy cells saved; {failures[0]['error']}")
        audit = _validate_audit(fixes, decisions)
        _write_jsonl(audit_path, list(audit.values()))
        suggestions_by_cell = {
            (row["review_key"], row["lang"]): row for row in validated
        }
        changed_rows = 0
        changed_cells = 0
        changed_by_lang: Counter[str] = Counter()
        output_rows: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        for row, signature in zip(rows, signatures, strict=True):
            translations = dict(row.get("translations") or {})
            row_changed = False
            for lang in target_langs:
                before = str(translations.get(lang) or "")
                reasons: list[str] = []
                audit_reasons: list[str] = []
                if signature in structured_signatures:
                    target_template, slots = structured_cells[(signature, lang)]
                    values = {slot.slot_key: slot.target for slot in slots}
                    for index, slot in enumerate(slots):
                        review_key = f"{signature}:segment:{index}"
                        suggestion = suggestions_by_cell.get((review_key, lang))
                        if suggestion is None:
                            continue
                        decision = audit[(review_key, lang)]
                        if decision["decision"] == "REVERT":
                            continue
                        values[slot.slot_key] = decision["final"] or suggestion["suggested"]
                        reasons.append(suggestion["reason"])
                        audit_reasons.append(decision["reason"])
                    final_text = render_reviewed_target(target_template, slots, values)
                else:
                    suggestion = suggestions_by_cell.get((signature, lang))
                    if suggestion is None:
                        continue
                    decision = audit[(signature, lang)]
                    if decision["decision"] == "REVERT":
                        continue
                    final_text = decision["final"] or suggestion["suggested"]
                    reasons.append(suggestion["reason"])
                    audit_reasons.append(decision["reason"])
                if not _preserves_protected_tokens(str(row.get('cn') or before), final_text, row.get("tokens") or []):
                    final_text = before
                if final_text != before:
                    issues.append(
                        {
                            "key": row.get("key"),
                            "lang": lang,
                            "before": before,
                            "after": final_text,
                            "reason": "; ".join(dict.fromkeys(reasons)),
                            "audit_reason": "; ".join(dict.fromkeys(audit_reasons)),
                        }
                    )
                    translations[lang] = final_text
                    changed_cells += 1
                    changed_by_lang[lang] += 1
                    row_changed = True
            changed_rows += int(row_changed)
            output_rows.append({**row, "translations": translations})
        _write_jsonl(final_cache, output_rows)
        elapsed = round(time.perf_counter() - overall_started, 3)
        summary = ProofreadSummary(
            final_cache=final_cache,
            suggestions_jsonl=suggestions_path,
            audit_jsonl=audit_path,
            summary_json=summary_path,
            reviewed_rows=len(source_review_rows),
            reviewed_cells=len(validated),
            suggested_changes=sum(row["status"] == "FIX" for row in fixes),
            reverted_changes=sum(1 for row in fixes if row["status"] == "FIX" and audit[(row["review_key"], row["lang"])]["decision"] == "REVERT"),
            changed_rows=changed_rows,
            changed_cells=changed_cells,
            elapsed_seconds=elapsed,
        )
        payload = {
            **asdict(summary),
            "final_cache": str(final_cache),
            "suggestions_jsonl": str(suggestions_path),
            "audit_jsonl": str(audit_path),
            "summary_json": str(summary_path),
            "audit_policy": audit_policy,
            "audited_cells": len(audit),
            "audit_api_cells": len(api_audit_fixes),
            "audit_auto_accepted_low_risk_cells": auto_accepted_low_risk_cells,
            "audit_sampled_low_risk_cells": sampled_low_risk_cells,
            "audit_tier_breakdown": dict(sorted(audit_tier_breakdown.items())),
            "audit_reused_cells": len(api_audit_fixes) - sum(len(batch) for batch, _ in audit_jobs),
            "audited_keep_cells": sum(row["status"] == "KEEP" for row in fixes),
            "changed_by_language": dict(sorted(changed_by_lang.items())),
            "issues": issues,
        }
        _atomic_write_text(summary_path, json.dumps(payload, ensure_ascii=False, indent=2))
        manifest.setdefault("artifacts", {})["final_cache"] = str(final_cache)
        manifest["artifacts"]["proofread_summary"] = str(summary_path)
        complete_phase(
            manifest,
            "controller_merge",
            started=merge_started,
            metrics={
                "audit_policy": audit_policy,
                "suggested_changes": summary.suggested_changes,
                "reverted_changes": summary.reverted_changes,
                "changed_cells": summary.changed_cells,
                "audit_api_batches": len(audit_jobs),
                "audit_api_cells": len(api_audit_fixes),
                "audit_auto_accepted_low_risk_cells": auto_accepted_low_risk_cells,
                "audit_sampled_low_risk_cells": sampled_low_risk_cells,
                "audit_reused_cells": len(api_audit_fixes) - sum(len(batch) for batch, _ in audit_jobs),
            },
        )
        _release_proofread_lock(proofread_lock)
        return summary
    except BaseException as exc:
        fail_phase(manifest, "controller_merge", exc)
        _release_proofread_lock(proofread_lock)
        raise
