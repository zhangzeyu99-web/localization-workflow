"""Adversarial checks at the actual relay, cache and XLSX import boundaries."""
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook, load_workbook

from utils.large_text_multilingual_executor import OpenAICompatibleClient, _cached_requests, _validate_response
from utils.large_text_multilingual_gate import cache_lint, pair_integrity_issues
from utils.relay_runtime import FatalRelayError, RelayError, RelayRuntime, ResponseTooLarge
from utils.large_text_multilingual_proofread import _validate_audit, _validate_suggestions
from utils.structured_text_template import parse_template, render_translations, translation_slots
from utils.workflow_progress import queue_status, update_progress
from utils.xlsx_translation_writeback import write_translation_workbooks


def relay(tmp_path, body):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'base_url': 'https://example.invalid', 'model': 'test'}), encoding='utf-8')
    client = OpenAICompatibleClient(config, runtime=RelayRuntime(tmp_path, max_attempts=1))
    with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode())) as send:
        try:
            return client._chat_json('Test', {'rows': []})
        finally:
            assert send.call_count == 1


@pytest.mark.parametrize('choice', [
    {'finish_reason': 'content_filter', 'message': {'content': '{"rows":[]}'}},
    {'finish_reason': 'tool_calls', 'message': {'content': '{"rows":[]}'}},
    {'finish_reason': 'stop', 'message': {'content': '{"rows":[]}', 'refusal': 'Refused'}},
    {'finish_reason': None, 'message': {'content': '{"rows":[]}'}},
])
def test_incomplete_or_refused_even_valid_json_is_not_accepted(tmp_path, choice):
    with pytest.raises(FatalRelayError):
        relay(tmp_path, {'choices': [choice]})


def test_length_finish_never_accepts_parseable_partial_json(tmp_path):
    with pytest.raises(ResponseTooLarge):
        relay(tmp_path, {'choices': [{'finish_reason': 'length', 'message': {'content': '{"rows":[]}'}}]})


@pytest.mark.parametrize('content', ['{"rows":[],"rows":[{}]}', '{"rows":[],"score":NaN}'])
def test_response_json_does_not_silently_discard_duplicate_fields(tmp_path, content):
    with pytest.raises(RelayError, match='invalid relay response'):
        relay(tmp_path, {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})


@pytest.mark.parametrize('reason', ['stop', 'omitted'])
def test_complete_response_and_legacy_missing_finish_metadata(tmp_path, reason):
    choice = {'message': {'content': '{"rows":[]}'}}
    if reason != 'omitted':
        choice['finish_reason'] = reason
    assert relay(tmp_path, {'choices': [choice]}) == {'rows': []}


@pytest.mark.parametrize('translations', [{'EN': 'Reward', 'en': 'Cut'}, {'EN': 123}, {'EN': None}])
def test_translation_schema_rejects_lossy_coercion_and_language_alias_collision(translations):
    with pytest.raises(ValueError):
        _validate_response([{'request_key': 'a', 'cn': 'Reward'}],
                           [{'request_key': 'a', 'translations': translations}], ['EN'])


@pytest.mark.parametrize('values', [{}, {'0': ''}, {'0': 'Reward', 'unexpected': 'Dropped'}])
def test_template_never_discards_missing_blank_or_extra_slots(values):
    template = parse_template('<b>奖励</b>')
    with pytest.raises(ValueError):
        render_translations(template, translation_slots(template), values)


@pytest.mark.parametrize('target', ['</b>Reward<b>', '<b>Reward</b><i>', '<b>Reward</b>\r'])
def test_plain_markup_and_physical_line_endings_are_protected(target):
    assert pair_integrity_issues({'cn': '<b>奖励</b>'}, 'EN', target)


@pytest.mark.parametrize('target', ['x' * 32768, 'x\x01y', 'x\ud800y', '_x0041_', '_x005F_'],
                         ids=['oversize', 'control', 'surrogate', 'excel-escape', 'excel-underscore'])
def test_bad_storage_text_cannot_enter_checkpoint_or_cache(tmp_path, target):
    row = {'request_key': 'a', 'key': 'a', 'cn': 'Reward', 'translations': {'EN': target}}
    checkpoint = tmp_path / 'old.json'
    checkpoint.write_text(json.dumps({'rows': [row]}), encoding='utf-8')
    with pytest.raises(ValueError):
        _cached_requests(tmp_path, [{'request_key': 'a', 'cn': 'Reward'}], ['EN'])
    with patch('utils.large_text_multilingual_gate.read_jsonl', return_value=[row]):
        result = cache_lint(Path('unused'), target_langs=['EN'])
    assert not result['ok_to_apply']


def workbook_and_row(root, name='input.xlsx', text='Accepted'):
    source = root / name
    wb = Workbook()
    wb.active.append(['ID', 'CN', 'EN', 'Note'])
    wb.active.append([1, 'Reward', None, 'Unchanged'])
    wb.save(source)
    wb.close()
    return source, {'source_file': name, 'sheet': 'Sheet', 'row': 2, 'id': '1', 'cn': 'Reward',
                    'translations': {'EN': text}}


def write(root, inputs, rows, output=None):
    cache = root / 'cache.jsonl'
    cache.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    return write_translation_workbooks(inputs=inputs, cache_jsonl=cache, target_langs=['EN'],
                                       output_dir=output or root / 'delivery')


@pytest.mark.parametrize('target', ['x' * 32768, '\U0001f600' * 16384, 'x\x01y', 'x\ud800y', 123, {'text': 'Reward'}, '_x0041_'],
                         ids=['oversize', 'utf16-limit', 'control', 'surrogate', 'number', 'object', 'excel-escape'])
def test_writer_rejects_unrepresentable_values_before_output(tmp_path, target):
    source, row = workbook_and_row(tmp_path, text=target)
    before = source.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        write(tmp_path, [source], [row])
    assert source.read_bytes() == before
    assert not (tmp_path / 'delivery' / source.name).exists()


def test_later_workbook_failure_does_not_leave_earlier_importable_output(tmp_path):
    first, a = workbook_and_row(tmp_path, 'a.xlsx')
    second, b = workbook_and_row(tmp_path, 'b.xlsx', '')
    with pytest.raises(ValueError):
        write(tmp_path, [first, second], [a, b])
    assert not (tmp_path / 'delivery' / 'a.xlsx').exists()


def test_target_readback_failure_blocks_publication(tmp_path):
    import utils.xlsx_translation_writeback as module
    source, row = workbook_and_row(tmp_path)
    original = module._patch_row
    def corrupt(body, prefix, changes):
        return original(body, prefix, [(r, c, v[:-1]) for r, c, v in changes])
    with patch.object(module, '_patch_row', side_effect=corrupt), pytest.raises(ValueError, match='readback'):
        write(tmp_path, [source], [row])
    assert not (tmp_path / 'delivery' / source.name).exists()


def test_source_overwrite_is_rejected_even_when_values_are_valid(tmp_path):
    source, row = workbook_and_row(tmp_path)
    before = source.read_bytes()
    with pytest.raises(ValueError, match='source'):
        write(tmp_path, [source], [row], tmp_path)
    assert source.read_bytes() == before


def test_duplicate_physical_cache_cell_is_not_last_write_wins(tmp_path):
    source, row = workbook_and_row(tmp_path)
    with pytest.raises(ValueError, match='duplicate'):
        write(tmp_path, [source], [row, {**row, 'translations': {'EN': 'Different'}}])
    assert not (tmp_path / 'delivery' / source.name).exists()


@pytest.mark.parametrize('target', [
    'x' * 32767, ' \tGröße & <tag> "quote"\r\n next\\n\r ',
    '=1+1', '\U0001f600' * 100, 'Ordenshalle der unsterblichen Wächter',
], ids=['limit', 'whitespace', 'formula-text', 'unicode', 'proper-name'])
def test_writer_exact_values_and_non_targets_not_clipped_or_formula_converted(tmp_path, target):
    source, row = workbook_and_row(tmp_path, text=target)
    write(tmp_path, [source], [row])
    wb = load_workbook(tmp_path / 'delivery' / source.name)
    try:
        assert wb.active['C2'].value == target
        assert wb.active['C2'].data_type == 's'
        assert wb.active['B2'].value == 'Reward'
        assert wb.active['D2'].value == 'Unchanged'
    finally:
        wb.close()


@pytest.mark.parametrize('seconds', [float('nan'), float('inf'), -1])
def test_progress_rejects_unusable_timing_before_eta(seconds):
    with pytest.raises(ValueError):
        update_progress({}, 'api_translate', total=100, accepted=20, reused=0, seconds=seconds)


def test_uppercase_paused_queue_never_suggests_restarting_completed_work():
    assert queue_status({'state': 'PAUSED', 'items': [{'id': 'a', 'state': 'pending'}]})['next_runnable'] is None


@pytest.mark.parametrize('target', [123, 'x' * 32768, 'x\x01y'], ids=['number', 'oversize', 'control'])
def test_review_and_audit_cannot_accept_unwritable_text(target):
    request = {'review_key': 'a', 'cn': 'Reward', 'translations': {'EN': 'Reward'}}
    with pytest.raises(ValueError):
        _validate_suggestions([request], [{'review_key': 'a', 'lang': 'EN', 'status': 'FIX',
                                          'suggested': target}], ['EN'])
    fix = {'review_key': 'a', 'lang': 'EN', 'cn': 'Reward', 'current': 'Reward', 'suggested': 'Reward', 'status': 'FIX'}
    with pytest.raises(ValueError):
        _validate_audit([fix], [{'review_key': 'a', 'lang': 'EN', 'decision': 'ACCEPT', 'final': target}])


def test_seed_reuse_keeps_accepted_boundary_spaces_without_api(tmp_path):
    from utils.large_text_multilingual_executor import translate_manifest
    from utils.large_text_multilingual_runner import build_manifest
    items = tmp_path / 'items.jsonl'
    items.write_text(json.dumps({'key': 'a', 'cn': 'Reward'}) + '\n', encoding='utf-8')
    manifest = build_manifest(work_dir=tmp_path / 'work', items_jsonl=items, source_rows_jsonl=None,
                              target_langs=['EN'], workbook_count=1, relay_config=None, proofread_mode='basic')
    accepted = '\t Reward \r\n'
    (tmp_path / 'work/seed_memory.json').write_text(json.dumps({'Reward': {'EN': accepted}}), encoding='utf-8')
    class NoAPI:
        def translate_batch(self, *args):
            pytest.fail('accepted seed must not trigger API')
    result = translate_manifest(Path(manifest['manifest_path']), relay_config=None, client=NoAPI())
    assert json.loads(result.cache_jsonl.read_text(encoding='utf-8'))['translations']['EN'] == accepted


@pytest.mark.parametrize('target', ['x' * 32768, '<b>Reward</b><i>'], ids=['oversize', 'markup'])
def test_formal_harness_cannot_bypass_format_blocks(target):
    from utils.quality_harness import check_row, DEFAULT_HARD_ISSUES
    issues = {item.check_type for item in check_row('1', '<b>奖励</b>', target)}
    assert issues & {'excel_text_too_long', 'markup_binding_mismatch'} & DEFAULT_HARD_ISSUES


def test_plain_import_parser_rejects_duplicate_json_and_nontext_values(tmp_path):
    from utils.translation_harness import parse_translation_response
    path = tmp_path / 'response.jsonl'
    for text in ('{"id":1,"translation":"Whole","translation":"Cut"}', '{"id":1,"translation":123}'):
        path.write_text(text, encoding='utf-8')
        with pytest.raises(ValueError):
            parse_translation_response(path)


def test_plain_import_blocks_oversize_before_openpyxl_can_truncate():
    from utils.translation_harness import _validate_response_surface, _newline_shape
    with pytest.raises(ValueError, match='32767'):
        _validate_response_surface([{'id': 1, 'placeholders': [], 'tags': [],
                                     'newline_shape': _newline_shape('')}], {1: 'x' * 32768})


def test_writeback_row_bound_check_does_not_rescan_entire_sheet_per_row(tmp_path):
    from openpyxl.worksheet.worksheet import Worksheet
    source = tmp_path / 'input.xlsx'
    wb = Workbook()
    wb.active.append(['ID', 'CN', 'EN'])
    rows = []
    for index in range(120):
        wb.active.append([index + 1, 'Reward', ''])
        rows.append({'source_file': source.name, 'sheet': 'Sheet', 'row': index + 2,
                     'id': str(index + 1), 'cn': 'Reward', 'translations': {'EN': 'Reward'}})
    wb.save(source)
    wb.close()
    original = Worksheet.max_row.fget
    calls = []
    def count(sheet):
        calls.append(1)
        return original(sheet)
    with patch.object(Worksheet, 'max_row', property(count)):
        write(tmp_path, [source], rows)
    assert len(calls) < 10  # Must depend on workbook count, not translated row count.


def test_history_extraction_preserves_accepted_whitespace(tmp_path):
    from utils.large_text_multilingual_pack import _load_history
    wb = Workbook()
    wb.active.append(['ID', 'CN', 'EN'])
    wb.active.append([1, 'Reward', ' Reward \r\n'])
    wb.save(tmp_path / 'history.xlsx')
    wb.close()
    assert _load_history([tmp_path], ['EN'])['Reward']['EN'] == ' Reward \r\n'


@pytest.mark.parametrize('source,target', [('<b>奖励</b>', '</b>Reward<b>'),
                                           ('{"text":"奖励","count":1}', '{"text":"Reward"}'),
                                           ('Source\r', 'Target')])
def test_plain_import_cannot_bypass_richtext_json_or_cr_integrity(source, target):
    from utils.translation_harness import _validate_response_surface, _newline_shape
    with pytest.raises(ValueError):
        _validate_response_surface([{'id': 1, 'source': source, 'placeholders': [], 'tags': [],
                                     'newline_shape': _newline_shape(source)}], {1: target})


def test_plain_import_does_not_convert_translation_to_formula(tmp_path):
    from utils.translation_harness import _write_translations_to_workbook
    source, _ = workbook_and_row(tmp_path)
    _write_translations_to_workbook(source, {1: '=1+1'}, 0)
    wb = load_workbook(source)
    try:
        assert wb.active['C2'].value == '=1+1'
        assert wb.active['C2'].data_type == 's'
    finally:
        wb.close()
