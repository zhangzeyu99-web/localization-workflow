from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.large_text_multilingual_executor import (
    OpenAICompatibleClient,
    _compact_context_fragments,
    _compact_shared_context,
    _prepare_wire_payload,
    _prune_wire_payload,
    _validate_response,
)
from utils.large_text_multilingual_gate import cache_lint, pair_integrity_issues
from utils.large_text_multilingual_pack import _load_terms, _term_hits
from utils.large_text_multilingual_proofread import (
    _language_context, _validate_audit, _validate_suggestions, run_deep_proofread,
)
from utils.large_text_multilingual_runner import build_manifest, main as runner_main
from utils.quality_harness import scan_cache_surface
from utils.quality_harness_rules import _check_person_name_terms
from utils.quality_harness_terms import term_enforcement_kind
from utils.relay_runtime import MAX_API_CONCURRENCY, RelayRuntime, bounded_results, concurrency


def _write_glossary(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["CN", "EN", "DE", "分类"])
    for cn, en, de, category in rows:
        ws.append([cn, en, de, category])
    wb.save(path)
    wb.close()


def test_concurrency_ceiling_and_bounded_results():
    assert MAX_API_CONCURRENCY == 5
    assert concurrency(1) == 1
    assert concurrency(5) == 5
    with pytest.raises(ValueError):
        concurrency(0)
    with pytest.raises(ValueError):
        concurrency(6)

    results = list(bounded_results(lambda item: item * 2, range(16), workers=8))
    assert sorted(value for _, value, error in results if error is None) == [i * 2 for i in range(16)]


def test_runner_cli_honors_concurrency_cap_and_defaults_proofread_batch_50(monkeypatch, tmp_path):
    captured = {}

    @dataclass
    class FakeResult:
        status: str
        manifest_path: str
        delivery_dir: str
        summary: dict

    def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        return FakeResult(
            status="completed",
            manifest_path=str(tmp_path / "manifest.json"),
            delivery_dir=str(tmp_path / "delivery"),
            summary={"ok": True},
        )

    monkeypatch.setattr("utils.large_text_multilingual_pipeline.run_pipeline", fake_run_pipeline)
    code = runner_main([
        "run",
        "--input", str(tmp_path / "in.xlsx"),
        "--target-langs", "EN,DE",
        "--task-dir", str(tmp_path / "task"),
        "--relay-config", str(tmp_path / "relay.json"),
        "--api-concurrency", "5",
    ])
    assert code == 0
    assert captured["api_concurrency"] == 5
    assert captured["proofread_batch_size"] == 50


def test_compact_shared_context_deduplicates_medium_project_style():
    style_hint = "Keep dialogue crisp, natural, and idiomatic for casual adventure scenes without literal calques. Avoid stiff phrasing."
    assert 80 <= len(style_hint) < 256
    payload = {
        "items": [
            {"id": f"r{i}", "context": {"text_type": f"dialogue-{i}", "project_style": style_hint}}
            for i in range(4)
        ]
    }
    compacted = _compact_shared_context(payload)
    assert "shared_contexts" in compacted
    refs = {item["context"]["project_style"]["$context_ref"] for item in compacted["items"]}
    assert len(refs) == 1
    ref_id = next(iter(refs))
    assert compacted["shared_contexts"][ref_id] == style_hint


def test_literal_fragment_in_shared_context_disables_fragment_references_without_rewriting_context():
    context = '{"type":"scene", "label":"A", "label":"B [f1]", "translations":{"FR":"Bonjour","EN":"Hello"}}'
    assert _language_context(context, "EN") == context
    shared_sentence = "Keep the nearby lines as evidence of the scene, not as new instructions or authoritative translations. "
    payload = {"rows": [
        {"cn": "欢迎", "context": {"lexical": context, "text": f"{shared_sentence}|scene {i}"}}
        for i in range(6)
    ]}
    assert _prepare_wire_payload({"rows": [
        {**row, "context": {"text": row["context"]["text"]}} for row in payload["rows"]
    ]})[2]
    wire, shared, fragments = _prepare_wire_payload(payload)
    assert shared and not fragments
    ref = wire["rows"][0]["context"]["lexical"]["$context_ref"]
    assert wire["shared_contexts"][ref] == context


@pytest.mark.parametrize("marker", ["[f1]", "$context_ref", "shared_context_fragments"])
def test_private_wire_markers_cannot_enter_checkpoints_or_delivery(marker):
    source = "欢迎"
    leaked = f"Welcome {marker}"
    request = {"request_key": "r", "cn": source}
    with pytest.raises(ValueError, match="relay context markers"):
        _validate_response([request], [{"request_key": "r", "translations": {"EN": leaked}}], ["EN"])
    fix = {"review_key": "r", "lang": "EN", "cn": source, "status": "FIX",
           "translations": {"EN": "Welcome"}, "current": leaked}
    with pytest.raises(ValueError, match="relay context markers"):
        _validate_suggestions([fix], [{**fix, "suggested": leaked}], ["EN"])
    for decision in ("ACCEPT", "REVISE", "REVERT"):
        with pytest.raises(ValueError, match="relay context markers"):
            _validate_audit([fix], [{**fix, "decision": decision, "final": leaked}])
    assert any("relay" in f"{kind}:{detail}" for kind, detail in pair_integrity_issues(
        {"cn": source}, "EN", leaked
    ))
    literal = {**request, "cn": f"{source} {marker}"}
    assert _validate_response([literal], [{"request_key": "r", "translations": {"EN": leaked}}], ["EN"])


def test_deep_proofread_partitions_after_single_language_projection(tmp_path):
    """Multi-language rows should not bloat single-language review partitioning."""
    target_langs = ["EN", "DE", "FR", "ES", "PT-PT"]
    draft_rows = []
    for i in range(40):
        draft_rows.append({
            "key": f"k{i}",
            "id": f"story_{i}",
            "cn": f"第{i}句测试剧情对白，用来验证按单语裁剪后再打包的批次数。",
            "translations": {
                lang: f"[{lang}] Sample dialogue line {i} for single-language batching verification."
                for lang in target_langs
            },
            "context": {
                "text_type": "dialogue",
                "project_style": "Use concise, natural dialogue style across all five locales without literal wording. " * 3,
            },
            "term_hits": [],
        })
    draft_path = tmp_path / "draft.jsonl"
    draft_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in draft_rows) + "\n",
        encoding="utf-8",
    )

    seen_batches: list[tuple[str, int]] = []

    class FakeReviewer:
        checkpoint_identity = "fake-reviewer"

        def review_batch(self, rows, langs):
            seen_batches.append((langs[0], len(rows)))
            return [
                {
                    "review_key": row["review_key"],
                    "lang": langs[0],
                    "status": "KEEP",
                    "issue_type": "none",
                    "suggested_translation": row["translations"][langs[0]],
                    "reason": "ok",
                }
                for row in rows
            ]

    seen_audit_batches: list[tuple[str, int]] = []

    class FakeAuditor:
        checkpoint_identity = "fake-auditor"

        def audit_batch(self, rows):
            seen_audit_batches.append((rows[0]["lang"], len(rows)))
            return [
                {
                    "review_key": row["review_key"],
                    "lang": row["lang"],
                    "decision": "ACCEPT",
                    "final": row["current"],
                    "reason": "verified",
                }
                for row in rows
            ]

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        work_dir=work_dir,
        items_jsonl=draft_path,
        source_rows_jsonl=None,
        target_langs=target_langs,
        workbook_count=1,
        relay_config=None,
        proofread_mode="full",
    )

    run_deep_proofread(
        Path(manifest["manifest_path"]),
        initial_cache=draft_path,
        reviewer=FakeReviewer(),
        auditor=FakeAuditor(),
        batch_size=50,
        workers=2,
    )
    # 40 rows x 5 langs with batch_size=50 and single-language partitioning should be 1 batch per language (5 total).
    assert len(seen_batches) == 5
    assert all(count == 40 for _, count in seen_batches)
    assert len(seen_audit_batches) == 5
    assert all(count == 40 for _, count in seen_audit_batches)


def test_generic_npc_roles_are_skipped_across_languages_while_named_characters_stay_strict(tmp_path):
    assert term_enforcement_kind("嘉宾", "Gäste", "角色", reference_en="Guest") == "skip"
    assert term_enforcement_kind("小孩", "niño", "角色", reference_en="Kid") == "skip"
    assert term_enforcement_kind("路人", "passant", "角色", reference_en="Passerby") == "skip"
    assert term_enforcement_kind("粉丝", "fãs", "角色", reference_en="Fan") == "skip"
    assert term_enforcement_kind("工作人员", "Mitarbeiter", "角色", reference_en="Staff") == "skip"
    # Named characters must stay strictly enforced as person names.
    assert term_enforcement_kind("艾拉", "Aria", "角色", reference_en="Aria") == "person"
    assert term_enforcement_kind("莱昂", "Leon", "主角", reference_en="Leon") == "person"

    glossary_path = tmp_path / "terms.xlsx"
    _write_glossary(glossary_path, [
        ("嘉宾", "Guest", "Gast", "角色"),
        ("艾拉", "Aria", "Aria", "角色"),
    ])
    terms = _load_terms(glossary_path, ["EN", "DE"])
    rows = [
        {
            "key": "r1",
            "cn": "请嘉宾先入座。",
            "translations": {
                "EN": "Please let everyone take a seat first.",
                "DE": "Bitte nehmen Sie zuerst Platz.",
            },
        },
        {
            "key": "r2",
            "cn": "艾拉已经到了。",
            "translations": {
                "EN": "Arya has arrived.",
                "DE": "Arya ist schon da.",
            },
        },
    ]
    for row in rows:
        row["term_hits"] = _term_hits(row["cn"], terms)
    cache_path = tmp_path / "cache.jsonl"
    cache_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    report = cache_lint(cache_path, target_langs=["EN", "DE"], term_base=glossary_path)
    issue_keys = {(item["key"], item["lang"], item["type"]) for item in report["issues"]}
    assert ("r1", "EN", "term_missing") not in issue_keys
    assert ("r1", "DE", "term_missing") not in issue_keys
    assert ("r2", "EN", "term_missing") in issue_keys
    assert ("r2", "DE", "term_missing") in issue_keys


def test_german_person_name_genitive_suffix_and_negative_cases():
    # German genitive -s for names not ending in s/ß/x/z should pass.
    assert _check_person_name_terms(1, "科宾的包", "Corbins Tasche", [("科宾", "Corbin")], lang="de") == []
    assert _check_person_name_terms(2, "维拉的笔记", "Veras Notizen", [("维拉", "Vera")], lang="de") == []
    # German apostrophe for s/x/z endings should pass, while invalid -s suffix must fail.
    assert _check_person_name_terms(3, "汉斯的书", "Hans' Buch", [("汉斯", "Hans")], lang="de") == []
    assert _check_person_name_terms(4, "麦克斯的书", "Maxs Buch", [("麦克斯", "Max")], lang="de") != []
    # Misspelling or wrong suffix in German must still fail.
    assert _check_person_name_terms(5, "艾拉的包", "Aryas Tasche", [("艾拉", "Aria")], lang="de") != []
    assert _check_person_name_terms(6, "科宾的包", "Corbina Tasche", [("科宾", "Corbin")], lang="de") != []
    # English allows straight/curly 's but must still reject bare -s.
    assert _check_person_name_terms(7, "科宾的包", "Corbin's bag", [("科宾", "Corbin")], lang="en") == []
    assert _check_person_name_terms(8, "科宾的包", "Corbin’s bag", [("科宾", "Corbin")], lang="en") == []
    assert _check_person_name_terms(9, "科宾的包", "Corbins bag", [("科宾", "Corbin")], lang="en") != []


def test_scan_cache_surface_exempts_continuation_lowercase_and_reads_nested_title_text_type():
    # 1. Cross-line continuation following a comma/dash should not become a hard blocker.
    continuation_rows = [
        {
            "key": "c1",
            "id": "dlg_1",
            "source_file": "story.xlsx",
            "sheet": "Dialog",
            "row": 10,
            "cn": "其实我一直想问你，",
            "translations": {"EN": "Actually, I've been meaning to ask you,"},
        },
        {
            "key": "c2",
            "id": "dlg_2",
            "source_file": "story.xlsx",
            "sheet": "Dialog",
            "row": 11,
            "cn": "为什么那天你会突然离开？",
            "translations": {"EN": "why did you leave so suddenly that day?"},
        },
    ]
    cont_report = scan_cache_surface(continuation_rows, ["EN"])
    assert cont_report["passed"] is True
    assert cont_report["hard_blockers"] == 0
    assert cont_report["issue_counts"].get("leading_lowercase") == 1

    # 2. Standalone sentence (or sentence after a period) starting lowercase must STILL fail hard.
    standalone_rows = [
        {
            "key": "s1",
            "id": "dlg_20",
            "source_file": "story.xlsx",
            "sheet": "Dialog",
            "row": 20,
            "cn": "门已经关好了。",
            "translations": {"EN": "The door is already closed."},
        },
        {
            "key": "s2",
            "id": "dlg_21",
            "source_file": "story.xlsx",
            "sheet": "Dialog",
            "row": 21,
            "cn": "我们现在出发吧。",
            "translations": {"EN": "let's head out now."},
        },
    ]
    standalone_report = scan_cache_surface(standalone_rows, ["EN"])
    assert standalone_report["passed"] is False
    assert standalone_report["hard_blockers"] == 1
    assert standalone_report["issues"][0]["check_type"] == "leading_lowercase"

    # 3. Nested context.text_type describing a chapter/section title should not trigger title_case_overuse.
    title_rows = [
        {
            "key": "t1",
            "id": "plot_title_1",
            "source_file": "story.xlsx",
            "sheet": "Titles",
            "row": 2,
            "cn": "还不能说",
            "context": {"text_type": "剧情小节标题；短小精炼，适合标题展示"},
            "translations": {"EN": "Can't Say Yet"},
        },
        {
            "key": "t2",
            "id": "status_1",
            "source_file": "story.xlsx",
            "sheet": "Status",
            "row": 2,
            "cn": "当前无法进入房间",
            "context": {"text_type": "错误提示"},
            "translations": {"EN": "Cannot Enter Room Right Now"},
        },
    ]
    title_report = scan_cache_surface(title_rows, ["EN"])
    assert title_report["issue_counts"].get("title_case_overuse", 0) == 1


def test_prune_wire_payload_drops_noise_without_losing_meaningful_fields():
    original = {
        "suggestions": [
            {
                "review_key": "k1",
                "lang": "DE",
                "cn": "你好，世界。",
                "translation_source": "你好，世界。",
                "source_mode": "cn",
                "reference_en": "",
                "reference_en_status": "not_requested",
                "risk_flags": [],
                "protected_tokens": [],
                "term_hits": [],
                "unresolved_issues": [],
                "dialogue_evidence": {"turns": []},
                "seed_origin": "",
                "context": "",
                "name_semantic_check_required": False,
                "semantic_check_required": False,
                "glossary_seed_locked": False,
                "independent_target_reading": None,
                "owner": "api",
                "cache_key": "abc123",
                "current": "Hallo, Welt.",
                "suggested": "Hallo, Welt.",
            },
            {
                "review_key": "k2",
                "lang": "DE",
                "cn": "高塔见，艾拉。",
                "translation_source": "Meet at Watch Tower, Aria.",
                "source_mode": "en",
                "reference_en": "Meet at Watch Tower, Aria.",
                "reference_en_status": "usable",
                "risk_flags": ["dialogue"],
                "protected_tokens": ["{0}"],
                "term_hits": [
                    {
                        "source": "高塔",
                        "translations": {"DE": "Wachturm"},
                        "category": "建筑名",
                        "strict": True,
                        "required": True,
                        "enforcement": "shared",
                        "reference_en": "Watch Tower",
                        "variants": [],
                    },
                    {
                        "source": "艾拉",
                        "translations": {"DE": "Aria"},
                        "category": "角色",
                        "strict": True,
                        "required": True,
                        "enforcement": "shared",
                        "reference_en": "Aria",
                    },
                ],
                "dialogue_evidence": {"turns": [{"cn": "上一句", "DE": "Vorheriger Satz"}]},
                "seed_origin": "glossary_exact",
                "context": {"type": "dialogue"},
                "name_semantic_check_required": True,
                "semantic_check_required": True,
                "glossary_seed_locked": False,
                "independent_target_reading": {"meaning": "Meet at tower"},
                "current": "Triff mich am Wachturm, Aria.",
                "suggested": "Triff mich am Wachturm, Aria.",
            },
        ]
    }
    snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True)
    pruned = _prune_wire_payload(original)
    # Must never mutate caller payload.
    assert json.dumps(original, ensure_ascii=False, sort_keys=True) == snapshot

    row1, row2 = pruned["suggestions"]
    # Row 1: all empty/default/mirrored/internal fields pruned.
    assert set(row1.keys()) == {"review_key", "lang", "cn", "current", "suggested"}

    # Row 2: every semantically meaningful field is preserved intact.
    assert row2["translation_source"] == "Meet at Watch Tower, Aria."
    assert row2["source_mode"] == "en"
    assert row2["reference_en"] == "Meet at Watch Tower, Aria."
    assert row2["reference_en_status"] == "usable"
    assert row2["risk_flags"] == ["dialogue"]
    assert row2["protected_tokens"] == ["{0}"]
    assert row2["dialogue_evidence"] == {"turns": [{"cn": "上一句", "DE": "Vorheriger Satz"}]}
    assert row2["seed_origin"] == "glossary_exact"
    assert row2["name_semantic_check_required"] is True
    assert row2["semantic_check_required"] is True
    # For glossary_exact rows, explicit glossary_seed_locked=False MUST stay preserved.
    assert row2["glossary_seed_locked"] is False
    assert row2["independent_target_reading"] == {"meaning": "Meet at tower"}
    # Enforcement and English evidence are needed even if English equals the target.
    hit_tower, hit_aria = row2["term_hits"]
    assert hit_tower["enforcement"] == "shared" and hit_tower["required"] is True
    assert "variants" not in hit_tower
    assert hit_tower["reference_en"] == "Watch Tower"
    assert hit_aria["reference_en"] == "Aria"


def test_compact_context_fragments_is_lossless_and_guards_literal_conflicts():
    repeated_rule = "剧情正文：对白、心声或动作旁白，按当前句语用判定，不擅自添加说话人；"
    repeated_note = "修订提示：旧译可能对应历史中文，目标必须以本行最新中文为准，语义不符必须修正。"
    payload = {
        "rows": [
            {
                "review_key": f"r{i}",
                "cn": f"测试句子{i}",
                "context": {
                    "text_type": f"{repeated_rule}来源 Sheet!{100 + i}。{repeated_note}｜邻句：你好{i}。"
                },
            }
            for i in range(6)
        ]
    }
    compacted = _compact_context_fragments(payload)
    assert "shared_context_fragments" in compacted
    frags = compacted["shared_context_fragments"]
    assert len(frags) >= 2
    assert len(json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))) < len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )

    # Exact verbatim round-trip verification.
    def expand(text: str) -> str:
        for fid, seg in frags.items():
            text = text.replace(f"[{fid}]", seg)
        return text

    for actual, expected in zip(compacted["rows"], payload["rows"], strict=True):
        assert expand(actual["context"]["text_type"]) == expected["context"]["text_type"]

    # Conflict protection: if source context already contains literal [f1], skip fragment extraction.
    conflict_payload = {
        "rows": [
            {
                "review_key": f"c{i}",
                "cn": f"句子{i}",
                "context": {
                    "text_type": f"{repeated_rule}保留标记 [f1] 来源 {i}。{repeated_note}"
                },
            }
            for i in range(6)
        ]
    }
    assert _compact_context_fragments(conflict_payload) is conflict_payload


def test_http_wire_payload_combines_pruning_shared_context_fragments_and_compact_json():
    import io
    from unittest.mock import patch

    style = "Use crisp, idiomatic adventure-game dialogue across locales without literal calques. " * 2
    rule = "剧情正文：对白、心声或动作旁白，按当前句语用判定，不擅自添加说话人；"
    note = "修订提示：旧译可能对应历史中文，目标必须以本行最新中文为准，语义不符必须修正。"
    rows = [
        {
            "request_key": f"k{i}",
            "cn": f"测试台词{i}",
            "translation_source": f"测试台词{i}",
            "source_mode": "cn",
            "reference_en": "",
            "reference_en_status": "not_requested",
            "term_hits": [],
            "context": {
                "project_style": style,
                "text_type": f"{rule}来源 Sheet!{i}。{note}",
            },
        }
        for i in range(5)
    ]

    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.model, client.base_url, client.api_key, client.timeout = "test", "https://example.invalid", "", 1
    client.runtime = RelayRuntime()
    client.checkpoint_identity = "wire-compact-test"

    captured = {}

    def fake_urlopen(request, **kwargs):
        raw_body = request.data.decode("utf-8")
        captured["raw_body"] = raw_body
        body = json.loads(raw_body)
        captured["system"] = body["messages"][0]["content"]
        captured["user_str"] = body["messages"][1]["content"]
        wire = json.loads(captured["user_str"])
        captured["wire"] = wire
        result = {"rows": [{"request_key": row["request_key"], "translations": {"EN": row["cn"]}} for row in wire["rows"]]}
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(result)}}]}).encode("utf-8"))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        actual = client.translate_batch(rows, ["EN"])

    assert len(actual) == 5
    wire = captured["wire"]
    assert "shared_contexts" in wire
    assert "shared_context_fragments" in wire
    assert "shared_contexts" in captured["system"]
    assert "shared_context_fragments" in captured["system"]
    # Compact JSON has no ": " spacing between keys and values.
    assert '": "' not in captured["user_str"]
    # Redundant fields pruned on wire, while caller rows remain untouched.
    assert "translation_source" not in wire["rows"][0]
    assert "reference_en_status" not in wire["rows"][0]
    assert "term_hits" not in wire["rows"][0]
    assert rows[0]["translation_source"] == "测试台词0"
