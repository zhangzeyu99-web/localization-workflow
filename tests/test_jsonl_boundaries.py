"""JSONL records split at LF, never at Unicode separators inside JSON strings."""
import json

import pytest
from openpyxl import Workbook, load_workbook

from utils import large_text_multilingual_executor as executor
from utils import large_text_residue_repair as residue
from utils import translation_harness as harness
from utils.announcement_docx_apply import _read_ai_response_rows
from utils.large_text_multilingual_gate import read_jsonl
from utils.large_text_multilingual_runner import build_manifest
from utils.large_text_multilingual_pipeline import run_pipeline
from utils.name_collision_gate import _read as read_names
from utils.reference_suggestion_workflow import _read_records
from utils.relay_runtime import RelayRuntime
from utils.xlsx_translation_writeback import _read_jsonl as read_writeback


READERS = [executor._read_jsonl, residue._read_jsonl, harness._read_jsonl,
           read_jsonl, read_writeback, read_names, _read_records]
WRITERS = [executor._write_jsonl, residue._write_jsonl, harness._write_jsonl]
VALUE = ' First\u0085next\u2028line\u2029last\r\n '


@pytest.mark.parametrize('reader', READERS)
@pytest.mark.parametrize('writer', WRITERS)
def test_jsonl_roundtrip_preserves_unicode_separators(tmp_path, reader, writer):
    path = tmp_path / 'records.jsonl'
    rows = [{'id': 1, 'translation': VALUE}, {'id': 2, 'translation': 'Control'}]
    writer(path, rows)
    assert reader(path) == rows


@pytest.mark.parametrize('reader', READERS)
def test_jsonl_accepts_crlf_records_but_rejects_malformed_record(tmp_path, reader):
    path = tmp_path / 'records.jsonl'
    valid = json.dumps({'id': 1, 'translation': VALUE}, ensure_ascii=False)
    path.write_bytes((valid + '\r\n\r\n').encode('utf-8'))
    assert reader(path) == [{'id': 1, 'translation': VALUE}]
    path.write_bytes((valid + '\n{"broken":\n').encode('utf-8'))
    with pytest.raises(ValueError):
        reader(path)


def test_plain_and_announcement_responses_preserve_same_text(tmp_path):
    path = tmp_path / 'response.jsonl'
    path.write_text(json.dumps({'id': 1, 'translation': VALUE}, ensure_ascii=False), encoding='utf-8')
    assert harness.parse_translation_response(path) == {1: VALUE}
    path.write_text(json.dumps({'para_id': 'p1', 'translation': VALUE}, ensure_ascii=False), encoding='utf-8')
    assert _read_ai_response_rows(path, [{'para_id': 'p1'}])[0]['translation'] == VALUE


def test_manifest_and_blind_read_cache_preserve_unicode_separators(tmp_path):
    items = tmp_path / 'items.jsonl'
    executor._write_jsonl(items, [{'key': 'one', 'cn': '奖励\u2028说明', 'context': VALUE,
                                 'translations': {}, 'source_mode': 'cn'}])
    manifest = build_manifest(work_dir=tmp_path, items_jsonl=items, source_rows_jsonl=None,
                              target_langs=['EN'], workbook_count=1, relay_config=None,
                              proofread_mode='basic')
    assert manifest['inputs']['source_mode'] == 'cn'
    runtime = RelayRuntime(tmp_path)
    record = {'meaning': VALUE, 'text': VALUE}
    runtime.save_blind_readings({'reading': record})
    assert RelayRuntime(tmp_path).blind_readings == {'reading': record}


@pytest.mark.parametrize('source_text,target_text', [
    ('领取\u2028奖励', 'Claim\u2028reward'),
    ('{"text": "奖励。", "code": "READY…"}', '{"text": "Reward.", "code": "READY…"}'),
])
def test_v2_text_survives_pipeline_export_and_resume(tmp_path, source_text, target_text):
    source = tmp_path / 'source.xlsx'
    book = Workbook()
    book.active.append(['ID', 'CN', 'EN'])
    book.active.append([1, source_text, None])
    book.save(source)
    book.close()

    class Client:
        calls = 0

        def translate_batch(self, rows, target_langs):
            self.calls += 1
            return [{'request_key': row['request_key'],
                     'translations': {lang: 'Reward' if row['cn'] == '奖励' else target_text
                                      for lang in target_langs}} for row in rows]

    client = Client()
    kwargs = dict(inputs=[source], term_base=None, history_dirs=[], target_langs=['EN'],
                  task_dir=tmp_path / 'task', relay_config=None, proofread_mode='basic',
                  translation_client=client)
    result = run_pipeline(**kwargs)
    book = load_workbook(result.delivery_dir / source.name)
    try:
        assert book.active['B2'].value == source_text
        assert book.active['C2'].value == target_text
    finally:
        book.close()
    calls = client.calls
    assert run_pipeline(**kwargs).delivery_dir == result.delivery_dir
    assert client.calls == calls
