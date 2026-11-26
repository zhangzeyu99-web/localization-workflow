from __future__ import annotations

import http.server
import io
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.large_text_multilingual_executor import (
    OpenAICompatibleClient,
    _compact_context_fragments,
)
from utils.large_text_multilingual_pipeline import run_pipeline
from utils.large_text_multilingual_proofread import run_deep_proofread
from utils.large_text_multilingual_runner import build_manifest
from utils.relay_runtime import RelayError, RelayRuntime


def test_review_and_audit_prompts_enforce_concise_reasons():
    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.model, client.base_url, client.api_key, client.timeout = "test", "https://example.invalid", "", 1
    client.runtime = RelayRuntime()
    client.checkpoint_identity = "concise-prompt-test"

    captured_systems: list[str] = []

    def fake_urlopen(request, **kwargs):
        body = json.loads(request.data.decode("utf-8"))
        captured_systems.append(body["messages"][0]["content"])
        wire = json.loads(body["messages"][1]["content"])
        if "rows" in wire:
            out = {"rows": [{"review_key": r["review_key"], "lang": "EN", "status": "KEEP", "suggested": r["translations"]["EN"], "reason": "ok"} for r in wire["rows"]]}
        else:
            out = {"rows": [{"review_key": r["review_key"], "lang": r["lang"], "decision": "ACCEPT", "final": r["current"], "reason": "ok"} for r in wire["suggestions"]]}
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(out)}}]}).encode("utf-8"))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.review_batch([{"review_key": "k1", "cn": "你好", "translations": {"EN": "Hello"}}], ["EN"])
        client.audit_batch([{"review_key": "k1", "lang": "EN", "cn": "你好", "current": "Hello", "suggested": "Hello", "status": "KEEP", "reason": "ok"}])

    assert "Keep reason concise: use 'ok' for KEEP" in captured_systems[0]
    assert "Keep reason concise: <=15 words" in captured_systems[1]


def test_context_fragments_deduplicates_dialogue_neighbor_labels_and_lines_losslessly():
    lines = [
        "这趟旅途比我们想象的还要漫长一些。",
        "前面的山谷好像起雾了，大家小心脚下。",
        "别担心，我带了备用照明灯和地图。",
        "那我们先在营地门口休整十分钟吧。",
        "好主意，顺便检查一下补给箱里的饮用水。",
        "刚才路过的小溪边似乎还有几处脚印。",
        "你确定那是之前探险队留下来的痕迹吗？",
        "看起来很新，应该不会超过半天时间。",
        "那我们更要保持警惕，尽量别掉队。",
        "明白，准备好了就马上继续出发。",
    ]
    rule = "剧情正文：对白、心声或动作旁白，按当前句语用判定，不擅自添加说话人；"
    rows = []
    for idx, line in enumerate(lines):
        prev2 = lines[idx - 2] if idx >= 2 else "开场白：准备集合出发。"
        prev1 = lines[idx - 1] if idx >= 1 else "开场白：准备集合出发。"
        next1 = lines[idx + 1] if idx + 1 < len(lines) else "尾声：队伍消失在雾中。"
        next2 = lines[idx + 2] if idx + 2 < len(lines) else "尾声：队伍消失在雾中。"
        tt = (
            f"{rule}来源 Story!{idx + 10}。"
            f"｜同场景-2行（仅上下文，不翻入当前行）：{prev2}"
            f"｜同场景-1行（仅上下文，不翻入当前行）：{prev1}"
            f"｜同场景+1行（仅上下文，不翻入当前行）：{next1}"
            f"｜同场景+2行（仅上下文，不翻入当前行）：{next2}"
        )
        rows.append({"review_key": f"r{idx}", "cn": line, "context": {"text_type": tt}})

    payload = {"rows": rows}
    before = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    compacted = _compact_context_fragments(payload)
    after = len(json.dumps(compacted, ensure_ascii=False, separators=(",", ":")))
    assert "shared_context_fragments" in compacted
    frags = compacted["shared_context_fragments"]
    frag_values = set(frags.values())
    assert "同场景-1行（仅上下文，不翻入当前行）：" in frag_values
    assert "同场景+1行（仅上下文，不翻入当前行）：" in frag_values
    # At least some repeated dialogue neighbor lines (appearing 4 times in 10 rows) are deduplicated.
    assert any(line in frag_values for line in lines)
    # Neighbor labels + repeated lines cut even a small 10-row batch by >30%.
    assert after < before * 0.70

    for actual, expected in zip(compacted["rows"], payload["rows"], strict=True):
        restored = actual["context"]["text_type"]
        for fid, seg in frags.items():
            restored = restored.replace(f"[{fid}]", seg)
        assert restored == expected["context"]["text_type"]


def test_keepalive_reuses_connection(monkeypatch):
    # Ensure proxy env vars do not bypass direct keep-alive in test.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)

    seen_ports: list[int] = []
    req_count = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass

        def do_POST(self):
            nonlocal req_count
            req_count += 1
            seen_ports.append(self.client_address[1])
            length = int(self.headers.get("Content-Length", "0"))
            _ = self.rfile.read(length)
            body = json.dumps({"ok": req_count}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
        client.model, client.base_url, client.api_key, client.timeout = "test", f"http://127.0.0.1:{port}/v1", "", 5
        client.runtime = RelayRuntime()
        client.checkpoint_identity = "keepalive-test"

        r1 = json.loads(client._post_json_bytes(f"http://127.0.0.1:{port}/v1/chat/completions", b"{}", {"Content-Type": "application/json"}))
        r2 = json.loads(client._post_json_bytes(f"http://127.0.0.1:{port}/v1/chat/completions", b"{}", {"Content-Type": "application/json"}))
        assert r1 == {"ok": 1}
        assert r2 == {"ok": 2}
        # Same TCP source port proves HTTP/1.1 Keep-Alive connection reuse!
        assert len(seen_ports) == 2 and seen_ports[0] == seen_ports[1]
    finally:
        server.shutdown()
        server.server_close()


def test_keepalive_disconnect_uses_only_the_runtime_post_budget(monkeypatch):
    attempted = []

    class ClosingConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            attempted.append(self)

        def getresponse(self):
            raise http.client.RemoteDisconnected("POST processed but response dropped")

        def close(self):
            pass

    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.timeout = 1
    monkeypatch.setattr(client, "_has_proxy_env", lambda: False)
    monkeypatch.setattr(http.client, "HTTPConnection", ClosingConnection)
    runtime = RelayRuntime(max_attempts=3, backoff_base=0)
    with pytest.raises(RelayError) as error:
        runtime.request(
            "test", "review", {"rows": [{"review_key": "k", "lang": "EN"}]},
            lambda: (client._post_json_bytes("http://127.0.0.1/test", b"{}", {}), {}),
        )
    assert isinstance(error.value.__cause__, http.client.RemoteDisconnected)
    assert len(attempted) == len(set(attempted)) == runtime.requests == 3


def test_streaming_language_pipeline_starts_fast_language_audit_before_slow_language_review_ends(tmp_path):
    target_langs = ["EN", "DE"]
    draft_rows = [
        {
            "key": f"k{i}",
            "id": f"id_{i}",
            "cn": f"测试句子{i}",
            "translations": {"EN": f"Test sentence {i}", "DE": f"Testsatz {i}"},
            "term_hits": [],
        }
        for i in range(12)
    ]
    draft_path = tmp_path / "draft.jsonl"
    draft_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in draft_rows) + "\n", encoding="utf-8")

    timestamps: dict[str, float] = {}
    german_batches_completed = []
    german_batches_before_en_audit = []
    lock = threading.Lock()

    class StaggeredReviewer:
        checkpoint_identity = "staggered-reviewer"

        def review_batch(self, rows, langs):
            lang = langs[0]
            if lang == "DE":
                time.sleep(0.02)
            else:
                time.sleep(0.01)
            with lock:
                timestamps[f"review_end:{lang}"] = time.perf_counter()
                if lang == "DE":
                    german_batches_completed.append(1)
            return [
                {
                    "review_key": row["review_key"],
                    "lang": lang,
                    "status": "KEEP",
                    "suggested": row["translations"][lang],
                    "reason": "ok",
                }
                for row in rows
            ]

    class RecordingAuditor:
        checkpoint_identity = "recording-auditor"

        def audit_batch(self, rows):
            lang = rows[0]["lang"]
            with lock:
                timestamps.setdefault(f"audit_start:{lang}", time.perf_counter())
                if lang == "EN":
                    german_batches_before_en_audit.append(len(german_batches_completed))
            return [
                {
                    "review_key": row["review_key"],
                    "lang": row["lang"],
                    "decision": "ACCEPT",
                    "final": row["current"],
                    "reason": "ok",
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

    summary = run_deep_proofread(
        Path(manifest["manifest_path"]),
        initial_cache=draft_path,
        reviewer=StaggeredReviewer(),
        auditor=RecordingAuditor(),
        batch_size=1,
        workers=2,
    )
    assert summary.reviewed_cells == 24
    # Fast language EN must begin auditing BEFORE slow language DE finishes reviewing!
    assert timestamps["audit_start:EN"] < timestamps["review_end:DE"]
    assert german_batches_before_en_audit[0] < 6


@pytest.mark.parametrize("source_mode", ["cn", "cn+en", "en"])
def test_retranslate_marked_routes_only_source_changed_rows_to_clean_translation(tmp_path, source_mode):
    source_xlsx = tmp_path / "revision.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Story"
    ws.append(["ID", "CN", "EN", "FR", "文本类型", "修改状态", "校对状态", "备注"])
    ws.append(["row_1", "欢迎回家。", "Welcome home.", "Bienvenue à la maison.", "剧情正文", ""])
    ws.append(["row_2", "今天天气真好。", "Stale unrelated sentence.", "Ancienne réplique.", "剧情正文", "中文大改"])
    ws.append(["row_3", "我们出发吧。", "", "", "剧情正文；【中文修改】以最新中文为准", ""])
    ws.append(["row_4", "再次见面。", "Meet again.", "On se retrouve.", "剧情正文", "不重译"])
    ws.append(["row_5", "欢迎回来。", "Stale text.", "Ancienne traduction.", "", "", "11.25中文修改", ""])
    ws.append(["row_6", "一切就绪。", "Stale text.", "Ancienne traduction.", "", "", "", "修改"])
    ws.append(["row_7", "稍等。", "Wait a moment.", "Un instant.", "【中文修改】", "", "中文修改", "无需重译"])
    ws.append(["row_8", "再见。", "See you.", "Au revoir.", "", "", "", "仅修改备注的措辞"])
    wb.save(source_xlsx)
    wb.close()

    translated_cns: list[str] = []

    class FakeTranslator:
        checkpoint_identity = "retrans-translator"

        def translate_batch(self, rows, target_langs):
            assert all(row["source_mode"] == "cn" and not row.get("reference_en")
                       and row["translation_source"] == row["cn"] for row in rows)
            translated_cns.extend(row["cn"] for row in rows)
            mapping = {
                "今天天气真好。": "Il fait très beau aujourd'hui.", "我们出发吧。": "En route !",
                "欢迎回来。": "Bon retour.", "一切就绪。": "Tout est prêt.",
            }
            return [
                {"request_key": row["request_key"], "translations": {"FR": mapping[row["cn"]]}}
                for row in rows
            ]

    # 1. Without --retranslate-marked, empty cell row_3 MUST still raise (no implicit translation).
    with pytest.raises(ValueError, match="empty target cells|requires complete usable English"):
        run_pipeline(
            inputs=[source_xlsx],
            term_base=None,
            history_dirs=[],
            target_langs=["FR"],
            task_dir=tmp_path / "task_default",
            relay_config=None,
            proofread_mode="basic",
            task_mode="review",
            source_mode=source_mode,
            translation_client=FakeTranslator(),
            retranslate_marked=False,
        )

    class FakeReviewer:
        checkpoint_identity = "retrans-reviewer"

        def review_batch(self, rows, target_langs):
            return [
                {
                    "review_key": row["review_key"],
                    "lang": lang,
                    "status": "KEEP",
                    "suggested": row["translations"][lang],
                    "reason": "ok",
                }
                for row in rows
                for lang in target_langs
            ]

    class FakeAuditor:
        checkpoint_identity = "retrans-auditor"

        def audit_batch(self, rows):
            return [
                {
                    "review_key": row["review_key"],
                    "lang": row["lang"],
                    "decision": "ACCEPT",
                    "final": row["current"],
                    "reason": "ok",
                }
                for row in rows
            ]

    # Marked rows disregard stale EN, while unmarked rows retain the requested source mode and existing FR.
    result = run_pipeline(
        inputs=[source_xlsx],
        term_base=None,
        history_dirs=[],
        target_langs=["FR"],
        task_dir=tmp_path / "task_marked",
        relay_config=None,
        proofread_mode="full",
        task_mode="review",
        source_mode=source_mode,
        translation_client=FakeTranslator(),
        reviewer=FakeReviewer(),
        auditor=FakeAuditor(),
        retranslate_marked=True,
    )
    assert set(translated_cns) == {"今天天气真好。", "我们出发吧。", "欢迎回来。", "一切就绪。"}
    delivered = result.delivery_dir / "revision.xlsx"
    from openpyxl import load_workbook
    out_wb = load_workbook(delivered, data_only=True)
    try:
        out_rows = list(out_wb["Story"].iter_rows(min_row=2, values_only=True))
    finally:
        out_wb.close()
    by_id = {row[0]: row[3] for row in out_rows}
    assert by_id["row_1"] == "Bienvenue à la maison."
    assert by_id["row_2"] == "Il fait très beau aujourd'hui."
    assert by_id["row_3"] == "En route !"
    assert by_id["row_4"] == "On se retrouve."
    assert by_id["row_5"] == "Bon retour."
    assert by_id["row_6"] == "Tout est prêt."
    assert by_id["row_7"] == "Un instant."
    assert by_id["row_8"] == "Au revoir."
    assert out_rows[1][2] == "Stale unrelated sentence."
    assert out_rows[4][2:] == ("Stale text.", "Bon retour.", None, None, "11.25中文修改", None)
