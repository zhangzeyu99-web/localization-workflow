from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.reference_suggestion_workflow import (
    _assert_safe_outputs,
    build_reference_cache,
    export_review,
    import_review,
    load_reference_cache,
    prepare_review,
    query_reference_cache,
    verify_export,
)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    command_started = time.perf_counter()
    parser = argparse.ArgumentParser(description="Competitor reference lookup and reviewed suggestion-table workflow")
    commands = parser.add_subparsers(dest="command", required=True)

    cache_build = commands.add_parser("cache-build", help="Build or explicitly refresh a persistent local reference cache")
    cache_build.add_argument("--config", required=True, type=Path)
    cache_build.add_argument("--output", required=True, type=Path)

    query = commands.add_parser("query", help="Query a fresh reference cache by exact CN/EN text, then bounded similarity")
    query.add_argument("--cache", required=True, type=Path)
    query.add_argument("--text", action="append", required=True)
    query.add_argument("--module", default="")
    query.add_argument("--top", type=int, default=3)
    query.add_argument("--similarity-threshold", type=float, default=0.72)
    query.add_argument("--output", type=Path)

    prepare = commands.add_parser("prepare", help="Snapshot a fixed-layout task and write one candidate per actual target cell")
    prepare.add_argument("--config", required=True, type=Path)
    prepare.add_argument("--work-dir", required=True, type=Path)

    review_import = commands.add_parser("import", help="Validate a complete two-stage review before workbook export")
    review_import.add_argument("--manifest", required=True, type=Path)
    review_import.add_argument("--review", required=True, type=Path)
    review_import.add_argument("--output", required=True, type=Path)
    review_import.add_argument("--report", required=True, type=Path)

    export = commands.add_parser("export", help="Export an accepted review with Artifact Tool")
    export.add_argument("--manifest", required=True, type=Path)
    export.add_argument("--accepted-review", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--work-dir", required=True, type=Path)
    export.add_argument("--mark-artifact-operation", action="store_true", help="Run the spreadsheet artifact-operation marker immediately before authoring")

    verify = commands.add_parser("verify", help="Read back and verify source preservation, suggestions, notes, and source freshness")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--accepted-review", required=True, type=Path)
    verify.add_argument("--output", required=True, type=Path)
    verify.add_argument("--report", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "cache-build":
        result = build_reference_cache(args.config, args.output)
        _print({
            "status": "built", "output": str(args.output.resolve()), "record_count": result["record_count"],
            "source_count": len(result["sources"]), "content_sha256": result["content_sha256"],
            "elapsed_seconds": round(time.perf_counter() - command_started, 6),
        })
    elif args.command == "query":
        result = query_reference_cache(args.cache, args.text, module_hint=args.module, top_k=args.top, similarity_threshold=args.similarity_threshold)
        if args.output:
            cache = load_reference_cache(args.cache, verify_sources=True)
            _assert_safe_outputs(
                [args.output],
                [args.cache, Path(str(cache["config_path"])), *(Path(str(row["path"])) for row in cache["sources"])],
                "query",
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.output:
            _print({
                "status": "written", "output": str(args.output.resolve()), "query_count": len(result["queries"]),
                "exact_queries": sum(row["status"] == "exact_text" for row in result["queries"]),
                "similar_queries": sum(row["status"] == "similar_candidates" for row in result["queries"]),
                "no_match_queries": sum(row["status"] == "no_reliable_match" for row in result["queries"]),
                "hit_count": sum(len(row["hits"]) for row in result["queries"]),
                "elapsed_seconds": round(time.perf_counter() - command_started, 6),
            })
        else:
            result["command_elapsed_seconds"] = round(time.perf_counter() - command_started, 6)
            _print(result)
    elif args.command == "prepare":
        result = prepare_review(args.config, args.work_dir)
        _print({
            "status": "prepared", "manifest": result["manifest_path"], "batch_id": result["batch_id"],
            "candidate_count": result["candidates"]["count"], "sheet_count": len(result["sheets"]),
            "physical_rows": {row["name"]: row["physical_rows"] for row in result["sheets"]},
            "elapsed_seconds": round(time.perf_counter() - command_started, 6),
        })
    elif args.command == "import":
        _print(import_review(args.manifest, args.review, args.output, args.report))
    elif args.command == "export":
        builder = Path(__file__).with_name("reference_suggestion_export.mjs")
        _print(export_review(args.manifest, args.accepted_review, args.output, args.work_dir, builder, mark_operation=args.mark_artifact_operation))
    elif args.command == "verify":
        _print(verify_export(args.manifest, args.accepted_review, args.output, args.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
