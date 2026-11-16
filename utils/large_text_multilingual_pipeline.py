"""One-command orchestration for large multilingual XLSX localization packs."""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from utils.large_text_multilingual_executor import (
    ExecutionSummary,
    OpenAICompatibleClient,
    TranslationClient,
    _atomic_write_text,
    _read_jsonl,
    _write_jsonl,
    complete_phase,
    fail_phase,
    start_phase,
    translate_manifest,
)
from utils.large_text_multilingual_gate import apply_dry_run, cache_lint, readback_gate
from utils.large_text_multilingual_pack import PackArtifacts, load_style_hint, prepare_pack
from utils.relay_runtime import RelayRuntime, atomic_json, concurrency, task_lock
from utils.large_text_multilingual_proofread import AuditClient, ReviewClient, run_deep_proofread
from utils.large_text_residue_repair import repair_cache_residue
from utils.large_text_multilingual_runner import build_manifest, load_manifest, save_manifest
from utils.xlsx_translation_writeback import verify_translation_cache, write_translation_workbooks
from utils.quality_harness import scan_cache_surface


@dataclass(frozen=True)
class PipelineResult:
    manifest: Path
    delivery_dir: Path
    retro_metrics: Path
    source_rows: int
    unique_items: int
    hard_blockers: int
    elapsed_seconds: float


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _run_gate_phase(
    manifest_path: Path,
    phase: str,
    callback: Any,
) -> Any:
    manifest = load_manifest(manifest_path)
    started = time.perf_counter()
    start_phase(manifest, phase)
    try:
        result = callback()
        complete_phase(manifest, phase, started=started)
        return result
    except BaseException as exc:
        fail_phase(manifest, phase, exc)
        raise


def _qa_summary(
    path: Path,
    *,
    source_rows: int,
    unique_items: int,
    target_langs: list[str],
    cache_result: dict[str, Any],
    readback_result: dict[str, Any] | None,
    proof_summary: Any,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet.append(["Metric", "Value"])
    values = [
        ("Source rows", source_rows),
        ("Unique items", unique_items),
        ("Target languages", ", ".join(target_langs)),
        ("Estimated target cells", source_rows * len(target_langs)),
        ("Cache hard blockers", cache_result.get("hard_blockers", 0)),
        ("Readback hard blockers", (readback_result or {}).get("hard_blockers", "pending")),
        ("Deep proofreading", "completed" if proof_summary else "not triggered"),
        ("Suggested changes", getattr(proof_summary, "suggested_changes", 0)),
        ("Reverted changes", getattr(proof_summary, "reverted_changes", 0)),
        ("Final changed cells", getattr(proof_summary, "changed_cells", 0)),
    ]
    for row in values:
        sheet.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def run_pipeline(*, task_dir: Path, api_concurrency: int = 4, retry_failed: bool = False,
                 style_hint_file: Path | None = None, **kwargs) -> PipelineResult:
    concurrency(api_concurrency)
    style_hint_path = Path(style_hint_file).resolve() if style_hint_file is not None else None
    style_hint = load_style_hint(style_hint_path)
    work_dir = task_dir / "_work" / "large_text_multilingual"
    with task_lock(work_dir):
        runtime = RelayRuntime(work_dir, limit=api_concurrency, retry_failed=retry_failed)
        config = {key: value for key, value in kwargs.items()
                  if key not in {"translation_client", "reviewer", "auditor"}}
        config.update(task_dir=task_dir, api_concurrency=api_concurrency)
        if style_hint_path is not None:
            config['style_hint_file'] = style_hint_path
        serializable = json.loads(json.dumps(config, default=str))
        snapshot = []
        for path in [*kwargs.get('inputs', []), kwargs.get('term_base'), kwargs.get('glossary_receipt')]:
            if path is not None:
                stat = Path(path).stat()
                snapshot.append({'path': str(Path(path).resolve()), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
        saved_config = work_dir / 'run_config.json'
        reuse_prepared = saved_config.exists()
        if saved_config.exists():
            previous = json.loads(saved_config.read_text(encoding='utf-8'))
            if previous.get('style_hint', '') != style_hint:
                raise ValueError('project style hint changed; use a new task directory, existing checkpoints preserved')
            if previous.get('source_snapshot') != snapshot:
                raise ValueError('source/terminology changed; use a new task directory, existing checkpoints preserved')
            for field, default in [('task_mode', 'translate'), ('source_mode', 'cn'),
                                   ('proofread_mode', 'basic'), ('target_langs', [])]:
                if previous['arguments'].get(field, default) != serializable.get(field, default):
                    raise ValueError(f'task binding changed: {field}; use a new task directory')
        atomic_json(saved_config, {'arguments': serializable, 'source_snapshot': snapshot, 'style_hint': style_hint})
        try:
            previous_result = work_dir / 'pipeline_result.json'
            previous_manifest = work_dir / 'large_text_multilingual_manifest.json'
            if previous_result.exists() and previous_manifest.exists():
                saved_manifest = load_manifest(previous_manifest)
                if saved_manifest.get('status') == 'complete':
                    accepted = json.loads(previous_result.read_text(encoding='utf-8'))
                    directory = Path(accepted['delivery_dir'])
                    languages = kwargs['target_langs']
                    readback = readback_gate(directory, target_langs=languages)
                    cache = Path(saved_manifest['artifacts'].get('final_cache') or saved_manifest['artifacts']['initial_cache'])
                    exact = verify_translation_cache(directory, cache, languages)
                    if readback.get('hard_blockers') or exact.get('hard_blockers'):
                        raise ValueError('completed delivery changed or failed readback; inspect before regenerating')
                    atomic_json(work_dir / 'resume_verification.json', {'readback': readback, 'exact': exact, 'new_api_requests': 0})
                    for field in ('manifest', 'delivery_dir', 'retro_metrics'):
                        accepted[field] = Path(accepted[field])
                    return PipelineResult(**accepted)
            result = _run_pipeline(task_dir=task_dir, runtime=runtime, reuse_prepared=reuse_prepared,
                                   style_hint=style_hint, **kwargs)
            atomic_json(work_dir / 'pipeline_result.json', json.loads(json.dumps(asdict(result), default=str)))
            return result
        finally:
            runtime.progress(force=True)


def resume_pipeline(manifest_path: Path, *, retry_failed: bool = False,
                    api_concurrency: int | None = None) -> PipelineResult:
    config = json.loads((manifest_path.parent / 'run_config.json').read_text(encoding='utf-8'))['arguments']
    for name in ('task_dir', 'term_base', 'glossary_receipt', 'relay_config', 'review_relay_config',
                 'audit_relay_config', 'delivery_dir', 'style_hint_file'):
        if config.get(name) is not None:
            config[name] = Path(config[name])
    for name in ('inputs', 'history_dirs'):
        config[name] = [Path(path) for path in config.get(name, [])]
    if api_concurrency is not None:
        config['api_concurrency'] = api_concurrency
    return run_pipeline(**config, retry_failed=retry_failed)


def _run_pipeline(
    *,
    inputs: list[Path],
    term_base: Path | None,
    history_dirs: list[Path],
    target_langs: list[str],
    task_dir: Path,
    relay_config: Path | None,
    proofread_mode: str,
    translation_client: TranslationClient | None = None,
    reviewer: ReviewClient | None = None,
    auditor: AuditClient | None = None,
    delivery_dir: Path | None = None,
    batch_size: int = 60,
    workers: int = 4,
    proofread_batch_size: int | None = None,
    proofread_workers: int | None = None,
    source_mode: str = "cn",
    glossary_receipt: Path | None = None,
    task_mode: str = 'translate',
    review_relay_config: Path | None = None,
    audit_relay_config: Path | None = None,
    runtime: RelayRuntime | None = None,
    reuse_prepared: bool = False,
    style_hint: str = "",
) -> PipelineResult:
    started = time.perf_counter()
    target_langs = [str(lang).upper() for lang in target_langs]
    if task_mode == 'review' and proofread_mode == 'basic':
        proofread_mode = 'full'
    glossary_acceptance = None
    if glossary_receipt is not None:
        from utils.glossary_enrichment import verify_receipt
        glossary_acceptance = verify_receipt(
            glossary_receipt, inputs=inputs, term_base=term_base, target_langs=target_langs,
        )
    reserved_names = {"qa摘要.xlsx", "qa_summary.xlsx"}
    conflicts = sorted(path.name for path in inputs if path.name.casefold() in reserved_names)
    if conflicts:
        raise ValueError(f"input uses reserved delivery file name: {conflicts}")
    work_dir = task_dir / "_work" / "large_text_multilingual"
    existing_manifest = work_dir / 'large_text_multilingual_manifest.json'
    stats_path = work_dir / 'prepare_stats.json'
    if reuse_prepared and existing_manifest.exists() and stats_path.exists():
        stats = json.loads(stats_path.read_text(encoding='utf-8'))
        values = {field: stats[field] for field in PackArtifacts.__dataclass_fields__}
        for field in ('items_jsonl', 'source_rows_jsonl', 'prepare_stats'):
            values[field] = Path(values[field])
        pack = PackArtifacts(**values)
    else:
        pack = prepare_pack(
            inputs=inputs,
            term_base=term_base,
            history_dirs=history_dirs,
            target_langs=target_langs,
            work_dir=work_dir,
            source_mode=source_mode,
            task_mode=task_mode,
            style_hint=style_hint,
        )
    manifest = load_manifest(existing_manifest) if reuse_prepared and existing_manifest.exists() else build_manifest(
        work_dir=work_dir,
        items_jsonl=pack.items_jsonl,
        source_rows_jsonl=pack.source_rows_jsonl,
        target_langs=target_langs,
        workbook_count=len(inputs),
        relay_config=relay_config,
        proofread_mode=proofread_mode,
        source_mode=source_mode,
    )
    manifest_path = Path(manifest["manifest_path"])
    manifest['execution_backend'] = 'relay'
    manifest['inputs']['task_mode'] = task_mode
    if style_hint:
        manifest['inputs']['style_hint'] = style_hint
    manifest['subagent_strategy'] = {'enabled': False, 'owner': 'relay_api', 'mode': proofread_mode}
    manifest['api_strategy']['concurrency_limit'] = runtime.limit if runtime else 4
    save_manifest(manifest)
    if glossary_acceptance is not None:
        if 'glossary_enrichment' not in manifest['critical_path']:
            manifest['critical_path'].insert(0, 'glossary_enrichment')
        manifest['phase_status']['glossary_enrichment'] = 'done'
        manifest.setdefault('artifacts', {})['glossary_receipt'] = str(glossary_receipt)
        manifest.setdefault('phase_metrics', {})['glossary_enrichment'] = {
            'approved_terms': glossary_acceptance['approved_terms'],
            'rejected_terms': glossary_acceptance['rejected_terms'],
        }
        save_manifest(manifest)
    shared_client = translation_client
    if shared_client is None:
        if relay_config is None:
            raise ValueError("relay_config is required for a real pipeline run")
        shared_client = OpenAICompatibleClient(relay_config, runtime=runtime)
    elif isinstance(shared_client, OpenAICompatibleClient) and runtime is not None:
        shared_client.runtime = runtime
    if task_mode == 'review':
        existing_rows = _read_jsonl(pack.items_jsonl)
        gaps = [{'key': row['key'], 'lang': lang} for row in existing_rows for lang in target_langs
                if not str(row.get('translations', {}).get(lang, '')).strip()]
        atomic_json(work_dir / 'review_missing_cells.json', gaps)
        if gaps:
            raise ValueError(f'review-only input contains {len(gaps)} empty target cells; no implicit translation')
        cache = work_dir / 'initial_cache.jsonl'
        _write_jsonl(cache, existing_rows)
        translation = ExecutionSummary(cache, work_dir / 'translation_metrics.json', len(existing_rows), 0, 0, 0, 0, 0)
        manifest['phase_status']['api_translate'] = 'skipped'
        manifest['phase_status']['api_smoke'] = 'skipped'
        save_manifest(manifest)
    else:
        translation = translate_manifest(
            manifest_path,
            relay_config=relay_config,
            client=shared_client,
            batch_size=batch_size,
            workers=min(workers, runtime.limit if runtime else 5),
        )

    residue_report_path = work_dir / "local_residue_repairs.json"
    residue_report = repair_cache_residue(
        translation.cache_jsonl,
        target_langs=target_langs,
        report_path=residue_report_path,
    )
    manifest = load_manifest(manifest_path)
    manifest.setdefault("artifacts", {})["local_residue_repairs"] = str(residue_report_path)
    manifest.setdefault("phase_metrics", {})["local_residue_repair"] = {
        "changed_cells": residue_report["changed_cells"]
    }
    save_manifest(manifest)

    initial_lint_path = work_dir / "cache_lint.json"

    def lint_initial() -> dict[str, Any]:
        result = cache_lint(
            translation.cache_jsonl,
            target_langs=target_langs,
            term_base=term_base,
        )
        _write_json(initial_lint_path, result)
        surface = scan_cache_surface(_read_jsonl(translation.cache_jsonl), target_langs)
        _write_json(work_dir / 'initial_surface_precheck.json', surface)
        if result["hard_blockers"] and task_mode != 'review':
            raise ValueError(f"cache-lint failed with {result['hard_blockers']} hard blockers")
        if surface['hard_blockers'] and proofread_mode not in {'sampled', 'full'}:
            raise ValueError(f"surface precheck failed with {surface['hard_blockers']} hard blockers")
        return result

    lint_result = _run_gate_phase(manifest_path, "incremental_cache_lint", lint_initial)
    final_cache = translation.cache_jsonl
    proof_summary = None
    if proofread_mode in {"sampled", "full"}:
        effective_reviewer = reviewer or (OpenAICompatibleClient(review_relay_config, runtime=runtime) if review_relay_config else shared_client)
        effective_auditor = auditor or (OpenAICompatibleClient(audit_relay_config, runtime=runtime) if audit_relay_config else shared_client)
        for client in (effective_reviewer, effective_auditor):
            if isinstance(client, OpenAICompatibleClient) and runtime is not None:
                client.runtime = runtime
        if not hasattr(effective_reviewer, "review_batch") or not hasattr(effective_auditor, "audit_batch"):
            raise ValueError("deep proofreading requires reviewer and auditor clients")
        proof_summary = run_deep_proofread(
            manifest_path,
            initial_cache=translation.cache_jsonl,
            reviewer=effective_reviewer,  # type: ignore[arg-type]
            auditor=effective_auditor,  # type: ignore[arg-type]
            batch_size=proofread_batch_size or batch_size,
            workers=min(proofread_workers or workers, runtime.limit if runtime else 5),
        )
        final_cache = proof_summary.final_cache
        final_lint_path = work_dir / "final_cache_lint.json"

        def lint_final() -> dict[str, Any]:
            result = cache_lint(
                final_cache,
                target_langs=target_langs,
                term_base=term_base,
            )
            _write_json(final_lint_path, result)
            surface = scan_cache_surface(_read_jsonl(final_cache), target_langs)
            _write_json(work_dir / 'final_surface_precheck.json', surface)
            if result["hard_blockers"]:
                raise ValueError(
                    f"final cache-lint failed with {result['hard_blockers']} hard blockers"
                )
            if surface['hard_blockers']:
                raise ValueError(f"surface precheck failed with {surface['hard_blockers']} hard blockers; repair affected cache cells before export")
            return result

        lint_result = _run_gate_phase(manifest_path, "final_cache_lint", lint_final)

    dry_dir = work_dir / "apply_dry_run"
    dry_dir.mkdir(parents=True, exist_ok=True)

    def dry_run_all() -> list[dict[str, Any]]:
        results = [
            apply_dry_run(source, dry_dir / source.name)
            for source in inputs
        ]
        _write_json(work_dir / "apply_dry_run.json", {"ok": True, "files": results})
        return results

    _run_gate_phase(manifest_path, "apply_dry_run", dry_run_all)

    if delivery_dir is None:
        delivery_dir = task_dir / (
            f"{task_dir.name}_multilingual_delivery_{datetime.now():%Y%m%d_%H%M%S}"
        )
    if delivery_dir.exists() and any(delivery_dir.iterdir()):
        raise FileExistsError(f"delivery directory is not empty: {delivery_dir}")

    def write_outputs() -> Any:
        return write_translation_workbooks(
            inputs=inputs,
            cache_jsonl=final_cache,
            target_langs=target_langs,
            output_dir=delivery_dir,
        )

    write_result = _run_gate_phase(manifest_path, "write_outputs", write_outputs)
    qa_path = delivery_dir / "QA摘要.xlsx"
    _qa_summary(
        qa_path,
        source_rows=pack.source_rows,
        unique_items=pack.unique_items,
        target_langs=target_langs,
        cache_result=lint_result,
        readback_result=None,
        proof_summary=proof_summary,
    )

    readback_path = work_dir / "readback_gate.json"

    def verify_delivery() -> dict[str, Any]:
        result = readback_gate(delivery_dir, target_langs=target_langs)
        exact = verify_translation_cache(delivery_dir, final_cache, target_langs)
        result["cache_readback"] = exact
        result["issues"].extend(exact["issues"])
        result["hard_blockers"] += exact["hard_blockers"]
        result["hard_by_type"] = dict(
            sorted(Counter(issue["type"] for issue in result["issues"]).items())
        )
        result["readback_verified"] = result["hard_blockers"] == 0
        _write_json(readback_path, result)
        if result["hard_blockers"]:
            raise ValueError(
                f"readback-gate failed with {result['hard_blockers']} hard blockers"
            )
        return result

    readback_result = _run_gate_phase(manifest_path, "readback_gate", verify_delivery)
    _qa_summary(
        qa_path,
        source_rows=pack.source_rows,
        unique_items=pack.unique_items,
        target_langs=target_langs,
        cache_result=lint_result,
        readback_result=readback_result,
        proof_summary=proof_summary,
    )

    retro_dir = work_dir / "retro"
    retro_path = retro_dir / "large_text_multilingual_retro_metrics.json"
    manifest = load_manifest(manifest_path)
    retro_started = time.perf_counter()
    start_phase(manifest, "retro_metrics")
    complete_phase(manifest, "retro_metrics", started=retro_started)
    manifest = load_manifest(manifest_path)
    manifest["status"] = "complete"
    manifest["delivery_dir"] = str(delivery_dir)
    manifest.setdefault("artifacts", {})["retro_metrics"] = str(retro_path)
    save_manifest(manifest)
    retro = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_rows": pack.source_rows,
        "unique_items": pack.unique_items,
        "target_languages": target_langs,
        "estimated_target_cells": pack.estimated_target_cells,
        "prepare_seconds": pack.elapsed_seconds,
        "translation": asdict(translation),
        "proofread": asdict(proof_summary) if proof_summary else {"status": "not_triggered"},
        "writeback": asdict(write_result),
        "cache_lint": lint_result,
        "readback_gate": readback_result,
        "phase_metrics": manifest.get("phase_metrics", {}),
        "total_seconds": round(time.perf_counter() - started, 3),
    }
    _write_json(retro_path, retro)
    return PipelineResult(
        manifest=manifest_path,
        delivery_dir=delivery_dir,
        retro_metrics=retro_path,
        source_rows=pack.source_rows,
        unique_items=pack.unique_items,
        hard_blockers=int(readback_result["hard_blockers"]),
        elapsed_seconds=round(time.perf_counter() - started, 3),
    )
