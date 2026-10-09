import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pytest

from utils.glossary_archive import archive_glossaries, sha256


def assets(tmp_path):
    current, old = tmp_path / 'current.xlsx', tmp_path / 'old.xlsx'
    with ZipFile(current, 'w') as archive:
        archive.writestr('xl/workbook.xml', '<workbook/>')
    old.write_bytes(b'previous glossary unchanged')
    return {'project_dir': tmp_path, 'current': current, 'previous': [old],
            'expected_current_sha256': sha256(current)}


def test_plan_is_read_only(tmp_path):
    args = assets(tmp_path)
    result = archive_glossaries(**args)
    assert result['status'] == 'planned'
    assert args['previous'][0].exists()
    assert not (tmp_path / '_archive').exists()


def test_archive_preserves_bytes_and_other_files(tmp_path):
    args = assets(tmp_path)
    old = args['previous'][0]
    digest = sha256(old)
    unrelated = tmp_path / 'different_project.xlsx'
    unrelated.write_bytes(b'do not move')
    snapshot = tmp_path / '_work' / 'snapshot.xlsx'
    snapshot.parent.mkdir()
    snapshot.write_bytes(b'keep historical snapshot')
    result = archive_glossaries(**args, apply=True)
    assert result['status'] == 'complete' and not old.exists()
    target = Path(result['files'][0]['destination'])
    assert sha256(target) == digest and args['current'].exists()
    assert unrelated.exists() and snapshot.exists()
    assert json.loads((target.parent / 'archive_receipt.json').read_text(encoding='utf-8'))['status'] == 'complete'


@pytest.mark.parametrize('mode', ['wrong_hash', 'current_as_old', 'duplicate', 'outside', 'nested', 'invalid_current'])
def test_invalid_preflight_never_moves(tmp_path, mode):
    args = assets(tmp_path)
    old = args['previous'][0]
    if mode == 'wrong_hash':
        args['expected_current_sha256'] = '0' * 64
    elif mode == 'current_as_old':
        args['previous'] = [args['current']]
    elif mode == 'duplicate':
        args['previous'] *= 2
    elif mode == 'outside':
        outside = tmp_path.parent / (tmp_path.name + '_outside.xlsx')
        outside.write_bytes(b'outside')
        args['previous'] = [outside]
    elif mode == 'nested':
        nested = tmp_path / '_work' / 'old.xlsx'
        nested.parent.mkdir()
        nested.write_bytes(b'snapshot')
        args['previous'] = [nested]
    else:
        args['current'].write_bytes(b'not xlsx')
        args['expected_current_sha256'] = sha256(args['current'])
    with pytest.raises((ValueError, BadZipFile)):
        archive_glossaries(**args, apply=True)
    assert old.exists() and not (tmp_path / '_archive').exists()
