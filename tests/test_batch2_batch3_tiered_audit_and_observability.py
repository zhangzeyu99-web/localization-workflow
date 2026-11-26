from __future__ import annotations

import inspect
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.large_text_multilingual_executor import OpenAICompatibleClient, translate_manifest
from utils.large_text_multilingual_proofread import _requires_independent_audit, run_deep_proofread
from utils.large_text_multilingual_runner import build_manifest, main as runner_main
from utils.relay_runtime import RelayRuntime


def test_requires_independent_audit_never_skips_any_risk_category():
    base_keep = {
        "review_key": "k1",
        "lang": "EN",
        "status": "KEEP",
        "cn": "欢迎来到营地。",
        "current": "Welcome to the camp.",
        "suggested": "Welcome to the camp.",
        "source_mode": "cn",
        "seed_origin": "",
        "risk_flags": [],
        "term_hits": [],
        "protected_tokens": [],
        "dialogue_evidence": {},
        "semantic_check_required": False,
        "name_semantic_check_required": False,
        "unresolved_issues": [],
    }
    # Pure low-risk KEEP with 0% sample rate is auto-accepted.
    assert _requires_independent_audit(base_keep, low_risk_sample_rate=0.0) == (False, "auto_keep_low_risk")
    # With 100% sample rate it is sampled into audit.
    assert _requires_independent_audit(base_keep, low_risk_sample_rate=1.0) == (True, "low_risk_sample")

    # Every single high-risk trigger MUST force independent audit even at 0% low-risk sample rate.
    high_risk_variants = [
        ({**base_keep, "status": "FIX"}, "reviewer_fix"),
        ({**base_keep, "unresolved_issues": ["omission"]}, "unresolved_issues"),
        ({**base_keep, "semantic_check_required": True}, "semantic_check_required"),
        ({**base_keep, "name_semantic_check_required": True}, "semantic_check_required"),
        ({**base_keep, "seed_origin": "glossary_exact"}, "glossary_exact"),
        ({**base_keep, "source_mode": "en"}, "multi_source"),
        ({**base_keep, "source_mode": "cn+en"}, "multi_source"),
        ({**base_keep, "risk_flags": ["idiom"]}, "risk_flags"),
        ({**base_keep, "term_hits": [{"source": "营地", "translations": {"EN": "Camp"}}]}, "term_hits"),
        ({**base_keep, "protected_tokens": ["{0}"]}, "protected_tokens"),
        ({**base_keep, "review_key": "sig:segment:0"}, "structured_segment"),
        ({**base_keep, "dialogue_evidence": {"turns": [{"cn": "上一句"}]}}, "dialogue_evidence"),
        ({**base_keep, "cn": "冷却时间3秒"}, "numeric_or_markup"),
        ({**base_keep, "current": "Cooldown {0}s"}, "numeric_or_markup"),
    ]
    for variant, expected_tier in high_risk_variants:
        needs_api, tier = _requires_independent_audit(variant, low_risk_sample_rate=0.0)
        assert needs_api is True
        assert tier == expected_tier


def test_deep_proofread_risk_tiered_policy_skips_only_unsampled_low_risk_keep(tmp_path):
    draft_rows = [
        {
            "key": f"low_{i}",
            "id": f"low_{i}",
            "cn": f"普通低风险欢迎提示语第{chr(ord('甲') + i)}条。",
            "translations": {"EN": f"Simple welcome greeting item {chr(ord('A') + i)}."},
            "term_hits": [],
        }
        for i in range(10)
    ]
    # Add 2 high-risk rows: one numeric, one that reviewer turns into FIX.
    draft_rows.append({
        "key": "num_1",
        "id": "num_1",
        "cn": "每次升级提升15%攻击力。",
        "translations": {"EN": "Increases Attack by 15% per level."},
        "term_hits": [],
    })
    draft_rows.append({
        "key": "fix_1",
        "id": "fix_1",
        "cn": "打开宝箱",
        "translations": {"EN": "Open box"},
        "term_hits": [],
    })
    draft_path = tmp_path / "draft.jsonl"
    draft_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in draft_rows) + "\n", encoding="utf-8")

    class FakeReviewer:
        checkpoint_identity = "tiered-reviewer"

        def review_batch(self, rows, langs):
            out = []
            for row in rows:
                if row["cn"] == "打开宝箱":
                    out.append({
                        "review_key": row["review_key"],
                        "lang": langs[0],
                        "status": "FIX",
                        "suggested": "Open Chest",
                        "reason": "Use chest terminology",
                    })
                else:
                    out.append({
                        "review_key": row["review_key"],
                        "lang": langs[0],
                        "status": "KEEP",
                        "suggested": row["translations"][langs[0]],
                        "reason": "ok",
                    })
            return out

    audited_cns: list[str] = []

    class FakeAuditor:
        checkpoint_identity = "tiered-auditor"

        def audit_batch(self, rows):
            audited_cns.extend(row["cn"] for row in rows)
            return [
                {
                    "review_key": row["review_key"],
                    "lang": row["lang"],
                    "decision": "ACCEPT",
                    "final": row["suggested"],
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
        target_langs=["EN"],
        workbook_count=1,
        relay_config=None,
        proofread_mode="full",
    )

    summary = run_deep_proofread(
        Path(manifest["manifest_path"]),
        initial_cache=draft_path,
        reviewer=FakeReviewer(),
        auditor=FakeAuditor(),
        batch_size=50,
        workers=2,
        audit_policy="risk_tiered",
        low_risk_audit_sample_rate=0.0,
    )
    # Only the numeric row and the FIX row should hit the auditor API (2 of 12).
    assert set(audited_cns) == {"每次升级提升15%攻击力。", "打开宝箱"}
    summary_data = json.loads(summary.summary_json.read_text(encoding="utf-8"))
    assert summary_data["audit_policy"] == "risk_tiered"
    assert summary_data["audit_api_cells"] == 2
    assert summary_data["audit_auto_accepted_low_risk_cells"] == 10
    assert summary_data["audited_cells"] == 12
    assert summary.changed_cells == 1


def test_runner_cli_passes_audit_policy(monkeypatch, tmp_path):
    captured = {}

    @dataclass
    class FakeResult:
        status: str
        manifest_path: str
        delivery_dir: str
        summary: dict

    def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        return FakeResult("completed", str(tmp_path / "m.json"), str(tmp_path / "d"), {})

    monkeypatch.setattr("utils.large_text_multilingual_pipeline.run_pipeline", fake_run_pipeline)
    code = runner_main([
        "run",
        "--input", str(tmp_path / "in.xlsx"),
        "--target-langs", "EN",
        "--task-dir", str(tmp_path / "task"),
        "--relay-config", str(tmp_path / "relay.json"),
        "--proofread-mode", "full",
        "--audit-policy", "risk_tiered",
    ])
    assert code == 0
    assert captured["audit_policy"] == "risk_tiered"


def test_blind_reading_deduplicates_identical_target_texts_and_records_observability(tmp_path):
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.model, client.base_url, client.api_key, client.timeout = "test", "https://example.invalid", "", 1
    client.runtime = RelayRuntime(tmp_path)
    client.checkpoint_identity = "blind-dedup-test"

    sent_batches: list[list[dict]] = []

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        wire = json.loads(body["messages"][1]["content"])
        sent_batches.append(wire["rows"])
        result = {
            "rows": [
                {
                    "review_key": row["review_key"],
                    "lang": row["lang"],
                    "meaning": f"Meaning of {row['text']}",
                    "predicate_object": "acts on target",
                    "tone": "neutral",
                }
                for row in wire["rows"]
            ]
        }
        return io.BytesIO(json.dumps({
            "choices": [{"message": {"content": json.dumps(result)}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }).encode("utf-8"))

    blind_rows = [
        {"review_key": "k1", "lang": "EN", "text": "Stay sharp."},
        {"review_key": "k2", "lang": "EN", "text": "Stay sharp."},
        {"review_key": "k3", "lang": "EN", "text": "Stay sharp."},
        {"review_key": "k4", "lang": "EN", "text": "Move forward."},
    ]
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        first = client._read_target_texts(blind_rows)
        # Second call with a brand-new review_key for the exact same (lang, text) should hit cache with 0 API calls!
        second = client._read_target_texts([{"review_key": "k99", "lang": "EN", "text": "Stay sharp."}])

    assert len(sent_batches) == 1
    assert len(sent_batches[0]) == 2  # Deduplicated from 4 rows to 2 unique texts.
    assert set(first.keys()) == {("k1", "EN"), ("k2", "EN"), ("k3", "EN"), ("k4", "EN")}
    assert first[("k2", "EN")]["review_key"] == "k2"
    assert first[("k2", "EN")]["meaning"] == "Meaning of Stay sharp."
    assert second[("k99", "EN")]["review_key"] == "k99"
    assert second[("k99", "EN")]["meaning"] == "Meaning of Stay sharp."

    progress = client.runtime.progress(force=True)
    assert progress["stage_requests"] == {"blind": 1}
    assert progress["context_compression"]["wire_chars_before"] > 0
    assert progress["context_compression"]["wire_chars_after"] <= progress["context_compression"]["wire_chars_before"]


def test_translate_manifest_default_max_batch_chars_is_48000():
    sig = inspect.signature(translate_manifest)
    assert sig.parameters["max_batch_chars"].default == 48000
