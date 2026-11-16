from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook, load_workbook

from utils.large_text_multilingual_executor import _request_signature
from utils.large_text_multilingual_pack import prepare_pack
from utils.large_text_multilingual_pipeline import resume_pipeline, run_pipeline
from utils.large_text_multilingual_proofread import _audit_item_key, _review_item_key
from utils.large_text_multilingual_runner import main


def source_workbook(path: Path, text_type_header: str = "TextType") -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "UI"
    sheet.append(["ID", "CN", "EN", text_type_header])
    sheet.append(["1", "欢迎", None, "提示"])
    sheet.append(["2", "入口", None, None])
    workbook.save(path)
    workbook.close()


@pytest.mark.parametrize("header", ["文本类型", "文案类型", "text_type", "TextType"])
def test_prepare_pack_carries_only_explicit_text_types(tmp_path, header):
    source = tmp_path / "source.xlsx"
    source_workbook(source, header)
    result = prepare_pack(inputs=[source], term_base=None, history_dirs=[], target_langs=["EN"],
                          work_dir=tmp_path / "work")
    rows = [json.loads(line) for line in result.items_jsonl.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["context"] == {"type": "ui", "text_type": "提示"}
    assert rows[1]["context"] == "ui"


def test_prepare_pack_cli_reads_utf8_bom_and_binds_all_semantic_keys(tmp_path):
    source = tmp_path / "source.xlsx"
    source_workbook(source)
    hint = tmp_path / "project.txt"
    hint.write_text("标题保留中心词。\n自然表达，保持含义。", encoding="utf-8-sig")
    work = tmp_path / "work"
    assert main(["prepare-pack", "--input", str(source), "--target-langs", "EN",
                 "--work-dir", str(work), "--style-hint-file", str(hint)]) == 0
    row = json.loads((work / "items.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["context"] == {"type": "ui", "text_type": "提示",
                              "project_style": "标题保留中心词。\n自然表达，保持含义。"}
    altered = {**row, "context": {**row["context"], "project_style": "Use sentence case."}}
    assert _request_signature(row) != _request_signature(altered)
    assert _review_item_key(row, "EN") != _review_item_key(altered, "EN")
    assert _audit_item_key({**row, "lang": "EN"}) != _audit_item_key({**altered, "lang": "EN"})


class RecordingClient:
    def __init__(self):
        self.contexts = {"translate": [], "review": [], "audit": []}

    def translate_batch(self, rows, target_langs):
        self.contexts["translate"].extend(row["context"] for row in rows)
        return [{"request_key": row["request_key"], "translations": {
            lang: {"欢迎": "Welcome.", "入口": "Entrance"}[row["cn"]] for lang in target_langs
        }} for row in rows]

    def review_batch(self, rows, target_langs):
        self.contexts["review"].extend(row["context"] for row in rows)
        return [dict(review_key=row["review_key"], lang=lang, status="KEEP",
                     suggested=row["translations"][lang], reason="Meaning and natural wording checked")
                for row in rows for lang in target_langs]

    def audit_batch(self, rows):
        self.contexts["audit"].extend(row["context"] for row in rows)
        return [dict(review_key=row["review_key"], lang=row["lang"], decision="ACCEPT",
                     final=row["suggested"], reason="Independently checked source and project guidance")
                for row in rows]


def test_run_cli_delivers_style_to_all_roles_and_resume_checks_actual_content(tmp_path):
    source = tmp_path / "source.xlsx"
    source_workbook(source)
    hint = tmp_path / "project.txt"
    hint.write_text("Use concise UI copy.", encoding="utf-8-sig")
    client = RecordingClient()
    real_run = run_pipeline

    def local_run(**kwargs):
        return real_run(**{**kwargs, "relay_config": None}, translation_client=client,
                        reviewer=client, auditor=client)

    with patch("utils.large_text_multilingual_pipeline.run_pipeline", side_effect=local_run):
        assert main(["run", "--input", str(source), "--target-langs", "EN", "--task-dir", str(tmp_path),
                     "--relay-config", str(tmp_path / "unused.json"), "--proofread-mode", "full",
                     "--style-hint-file", str(hint)]) == 0
    for contexts in client.contexts.values():
        assert len(contexts) == 2
        assert all(context["project_style"] == "Use concise UI copy." for context in contexts)
    work = tmp_path / "_work" / "large_text_multilingual"
    manifest = work / "large_text_multilingual_manifest.json"
    config_path = work / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["arguments"]["style_hint_file"] == str(hint.resolve())
    assert config["style_hint"] == "Use concise UI copy."
    result = resume_pipeline(manifest)
    workbook = load_workbook(result.delivery_dir / source.name, read_only=True)
    try:
        assert workbook.active["C2"].value == "Welcome."
    finally:
        workbook.close()
    assert json.loads((work / "resume_verification.json").read_text(encoding="utf-8"))["new_api_requests"] == 0
    original_config = config_path.read_bytes()
    stat = hint.stat()
    hint.write_text("Use natural UI copy.", encoding="utf-8-sig")
    os.utime(hint, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert hint.stat().st_size == stat.st_size
    with patch("utils.large_text_multilingual_pipeline._run_pipeline") as execute:
        with pytest.raises(ValueError, match="project style hint changed"):
            resume_pipeline(manifest)
        execute.assert_not_called()
    assert config_path.read_bytes() == original_config
    hint.unlink()
    with patch("utils.large_text_multilingual_pipeline.OpenAICompatibleClient") as api:
        with pytest.raises(FileNotFoundError):
            resume_pipeline(manifest)
        api.assert_not_called()


def test_missing_style_file_fails_before_prepare_or_api(tmp_path):
    missing = tmp_path / "missing.txt"
    with patch("utils.large_text_multilingual_pipeline._run_pipeline") as execute:
        with pytest.raises(FileNotFoundError):
            run_pipeline(task_dir=tmp_path, style_hint_file=missing)
        execute.assert_not_called()
    with patch("utils.large_text_multilingual_pack.prepare_pack") as prepare:
        with pytest.raises(FileNotFoundError):
            main(["prepare-pack", "--input", "unused.xlsx", "--target-langs", "EN",
                  "--work-dir", str(tmp_path), "--style-hint-file", str(missing)])
        prepare.assert_not_called()


def test_legacy_saved_run_without_style_hint_remains_compatible(tmp_path):
    directory = tmp_path / "_work" / "large_text_multilingual"
    directory.mkdir(parents=True)
    config_path = directory / "run_config.json"
    config_path.write_text(json.dumps({"arguments": {"task_dir": str(tmp_path)}, "source_snapshot": []}),
                           encoding="utf-8")
    with patch("utils.large_text_multilingual_pipeline._run_pipeline", side_effect=RuntimeError("reached executor")):
        with pytest.raises(RuntimeError, match="reached executor"):
            resume_pipeline(directory / "large_text_multilingual_manifest.json")
