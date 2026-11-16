"""Exercise lossless ingestion and manifest binding through real file adapters."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook, load_workbook

from utils.excel_reader import read_language_file
from utils.translation_harness import apply_translation_response, prepare_translation_harness
from utils.announcement_docx_apply import _read_ai_response_rows, _write_ai_responses_to_workbook
from utils.process_language_outputs import _build_result_full, write_outputs
from utils.process_language_review import RowState


def language_book(path):
    book = Workbook()
    book.active.append(['ID', 'CN', 'EN', 'Note'])
    book.active.append(['001', 'Claim', '', 'Keep'])
    book.active.append(['002', 'Exit', '', 'Keep'])
    book.save(path)
    book.close()


@pytest.mark.parametrize('extension', ['xlsx', 'csv'])
def test_reader_preserves_na_literals_and_string_ids(tmp_path, extension):
    path = tmp_path / f'input.{extension}'
    rows = [['ID', 'CN', 'EN'], ['001', 'NA', 'NULL'], ['002', 'nan', 'N/A'], ['003', '', '']]
    if extension == 'xlsx':
        book = Workbook()
        for row in rows:
            book.active.append(row)
        book.save(path)
        book.close()
    else:
        path.write_text('\n'.join(','.join(row) for row in rows), encoding='utf-8')
    frame, _ = read_language_file(str(path))
    assert frame.values.tolist() == rows[1:]


@pytest.mark.parametrize('damage', ['missing', 'empty', 'dropped_row', 'changed_source'])
def test_plain_import_rejects_incomplete_or_changed_workpack(tmp_path, damage):
    source = tmp_path / 'input.xlsx'
    language_book(source)
    prepared = prepare_translation_harness(source, output_dir=tmp_path / 'work')
    rows = [json.loads(line) for line in prepared.workpack_path.read_text(encoding='utf-8').splitlines()]
    if damage == 'missing':
        prepared.workpack_path.unlink()
        rows = []
    elif damage == 'empty':
        rows = []
    elif damage == 'dropped_row':
        rows = rows[:1]
    else:
        rows[0]['source'] = rows[0]['source_cn'] = 'Changed'
    if damage != 'missing':
        prepared.workpack_path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    response = tmp_path / 'response.jsonl'
    response.write_text('\n'.join(json.dumps({'id': row['id'], 'translation': 'Target'}) for row in rows), encoding='utf-8')
    with pytest.raises(ValueError, match='workpack|manifest'):
        apply_translation_response(source, prepared.manifest_path, response, tmp_path / 'delivery')
    assert not list((tmp_path / 'delivery').glob('*.xlsx'))
    assert not (tmp_path / '.translation_cache').exists()


def test_plain_import_writes_all_text_ids_not_a_zero_cell_success(tmp_path):
    source = tmp_path / 'input.xlsx'
    language_book(source)
    prepared = prepare_translation_harness(source, output_dir=tmp_path / 'work')
    rows = [json.loads(line) for line in prepared.workpack_path.read_text(encoding='utf-8').splitlines()]
    response = tmp_path / 'response.jsonl'
    response.write_text('\n'.join(json.dumps({'id': row['id'], 'translation': 'Target'}) for row in rows), encoding='utf-8')
    result = apply_translation_response(source, prepared.manifest_path, response, tmp_path / 'delivery')
    book = load_workbook(result.final_workbook_path)
    try:
        assert [book.active.cell(row, 3).value for row in (2, 3)] == ['Target', 'Target']
        assert [book.active.cell(row, 1).value for row in (2, 3)] == ['001', '002']
    finally:
        book.close()


@pytest.mark.parametrize('payload', [
    '{"para_id":"p1","translation":"Whole","translation":"Cut"}',
    '{"para_id":"p1","translation":123}',
])
def test_announcement_response_rejects_lossy_json(tmp_path, payload):
    response = tmp_path / 'response.jsonl'
    response.write_text(payload, encoding='utf-8')
    with pytest.raises(ValueError):
        _read_ai_response_rows(response, [{'para_id': 'p1'}])


def test_announcement_response_retains_boundary_whitespace(tmp_path):
    response = tmp_path / 'response.jsonl'
    value = ' Target \r\n'
    response.write_text(json.dumps({'para_id': 'p1', 'translation': value}), encoding='utf-8')
    assert _read_ai_response_rows(response, [{'para_id': 'p1'}])[0]['translation'] == value


@pytest.mark.parametrize('value', ['x' * 32768, '_x0041_', '=1+1'], ids=['oversize', 'escape', 'formula'])
def test_announcement_excel_import_never_clips_or_converts_formulas(tmp_path, value):
    path = tmp_path / 'translation.xlsx'
    book = Workbook()
    book.active.title = 'Translations'
    book.active.append(['para_id', 'EN', 'Note'])
    book.active.append(['p1', 'Previous', 'Keep'])
    book.save(path)
    book.close()
    before = path.read_bytes()
    if value != '=1+1':
        with pytest.raises(ValueError):
            _write_ai_responses_to_workbook(path, {'p1': {}}, {'EN': {'p1': value}})
        assert path.read_bytes() == before
    else:
        _write_ai_responses_to_workbook(path, {'p1': {}}, {'EN': {'p1': value}})
        book = load_workbook(path)
        try:
            assert book.active['B2'].value == value
            assert book.active['B2'].data_type == 's'
            assert book.active['C2'].value == 'Keep'
        finally:
            book.close()


@pytest.mark.parametrize('locked_attempts', [1, 3])
def test_announcement_replace_lock_is_bounded_and_preserves_previous_file(tmp_path, locked_attempts):
    path = tmp_path / 'translation.xlsx'
    book = Workbook()
    book.active.title = 'Translations'
    book.active.append(['para_id', 'EN'])
    book.active.append(['p1', 'Previous'])
    book.save(path)
    book.close()
    before = path.read_bytes()
    replace = Path.replace
    attempts = []
    def locked(source, target):
        if target == path:
            attempts.append(1)
            if len(attempts) <= locked_attempts:
                raise PermissionError('simulated destination lock')
        return replace(source, target)
    with patch.object(Path, 'replace', locked), patch('utils.announcement_docx_apply.time.sleep'):
        if locked_attempts == 3:
            with pytest.raises(PermissionError):
                _write_ai_responses_to_workbook(path, {'p1': {}}, {'EN': {'p1': 'Target'}})
            assert path.read_bytes() == before
        else:
            _write_ai_responses_to_workbook(path, {'p1': {}}, {'EN': {'p1': 'Target'}})
    assert len(attempts) == min(3, locked_attempts + 1)


@pytest.mark.parametrize('value', ['x' * 32768, '=1+1'], ids=['oversize', 'formula'])
def test_main_output_preserves_previous_languages_and_validates_before_writing(tmp_path, value):
    import pandas as pd
    frame = pd.DataFrame([[1, 'Claim', 'Previous']], columns=['ID', 'CN', 'EN'])
    columns = {'id_col': 'ID', 'original_col': 'CN', 'languages': [{'translation_col': 'EN'}]}
    state = RowState(1, 'Claim', 'Previous')
    state.fixed_translation = value
    out = tmp_path / 'delivery'
    out.mkdir()
    previous = out / 'result_fr.xlsx'
    previous.write_bytes(b'previous-language-sentinel')
    if len(value) > 32767:
        with pytest.raises(ValueError):
            write_outputs(frame, columns, {1: state}, [], str(tmp_path / 'source.xlsx'), output_dir=str(out))
        assert not (out / 'result_en.xlsx').exists()
    else:
        result = write_outputs(frame, columns, {1: state}, [], str(tmp_path / 'source.xlsx'), output_dir=str(out))
        book = load_workbook(result['result_path'])
        try:
            assert book.worksheets[0]['C2'].value == value
            assert book.worksheets[0]['C2'].data_type == 's'
        finally:
            book.close()
    assert previous.read_bytes() == b'previous-language-sentinel'


def test_main_result_updates_by_position_without_repeated_id_scans():
    import pandas as pd
    frame = pd.DataFrame([
        ['001', 'Claim', 'Previous', 'Keep'],
        ['001', 'Claim', 'Previous', 'Keep'],
        ['002', 'Exit', 'Previous', 'Keep'],
    ], columns=['ID', 'CN', 'EN', 'Note'])
    columns = {'id_col': 'ID', 'languages': [{'translation_col': 'EN'}]}
    state = RowState('001', 'Claim', 'Previous')
    state.fixed_translation = 'Target'
    state.notes = ['Reviewed']
    scans = []
    original_eq = pd.Series.__eq__
    def count_scans(series, other):
        scans.append(len(series))
        return original_eq(series, other)
    with patch.object(pd.Series, '__eq__', count_scans):
        result = _build_result_full(frame, columns, {'001': state})
    assert result['EN'].tolist() == ['Target', 'Target', 'Previous']
    assert result.iloc[:, -1].tolist() == ['Reviewed', 'Reviewed', '']
    assert result['Note'].tolist() == ['Keep'] * 3
    assert frame['EN'].tolist() == ['Previous'] * 3
    assert scans == []
