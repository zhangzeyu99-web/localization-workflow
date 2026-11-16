import json
from unittest.mock import patch

from openpyxl import Workbook

from utils.localization_quality_policy import QUALITY_POLICY_VERSION
from utils.translation_harness import (
    _load_translation_cache,
    _term_hits,
    _update_translation_cache,
    prepare_translation_harness,
)


def write_cache(root, rows):
    path = root / '.translation_cache' / 'en.jsonl'
    path.parent.mkdir(exist_ok=True)
    path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')


def test_prepare_uses_current_glossary_to_reject_old_ui_short_name_cache(tmp_path):
    source = tmp_path / 'input.xlsx'
    terms = tmp_path / 'terms.xlsx'
    for path, rows in (
        (source, [['ID', 'CN', 'EN'], [1, '红心女王', None], [2, '继续', None]]),
        (terms, [['CN', 'EN', '分类'], ['红心女王', 'Queen of Hearts', '英雄名']]),
    ):
        workbook = Workbook()
        for row in rows:
            workbook.active.append(row)
        workbook.save(path)
        workbook.close()
    write_cache(tmp_path, [
        {'source': '红心女王', 'text_type': 'ui_short', 'translation': 'Queen of Hearts'},
        {'source': '继续', 'text_type': 'ui_short', 'translation': 'Continue'},
    ])
    result = prepare_translation_harness(source, terms, lang='en', output_dir=tmp_path / 'prepared')
    rows = [json.loads(line) for line in result.workpack_path.read_text(encoding='utf-8').splitlines()]
    assert [row['cache_hit'] for row in rows] == [False, True]
    assert rows[1]['cached_translation'] == 'Continue'


def test_name_cache_requires_current_term_snapshot_and_changes_only_affected_name(tmp_path):
    terms = {
        '红心女王': {'primary': 'Queen of Hearts', 'category': '英雄名'},
        '白塔守卫': {'primary': 'Tower Guard', 'category': '角色名'},
    }
    workpack = [
        {'id': 1, 'source': '红心女王', 'text_type': 'ui_short', 'term_hits': _term_hits('红心女王', terms)},
        {'id': 2, 'source': '白塔守卫', 'text_type': 'ui_short', 'term_hits': _term_hits('白塔守卫', terms)},
        {'id': 3, 'source': '继续', 'text_type': 'ui_short', 'term_hits': []},
    ]
    responses = {1: 'Queen of Hearts', 2: 'Tower Guard', 3: 'Continue'}
    cache_path = _update_translation_cache(tmp_path, 'en', workpack, responses)
    assert len(_load_translation_cache(tmp_path, 'en', term_lookup=terms)) == 3
    updated = {**terms, '红心女王': {**terms['红心女王'], 'primary': 'Heart Queen'}}
    available = _load_translation_cache(tmp_path, 'en', term_lookup=updated)
    assert set(available.values()) == {'Tower Guard', 'Continue'}
    saved = [json.loads(line) for line in cache_path.read_text(encoding='utf-8').splitlines()]
    assert next(row for row in saved if row['source'] == '红心女王')['term_hits'] == workpack[0]['term_hits']
    # A policy marker without its actual glossary snapshot does not approve a name.
    write_cache(tmp_path, [{'source': '红心女王', 'text_type': 'ui_short', 'translation': 'Queen of Hearts',
                            'language_quality_policy_version': QUALITY_POLICY_VERSION}])
    assert not _load_translation_cache(tmp_path, 'en', term_lookup=terms)


def test_unclassified_prose_cache_is_not_invalidated_by_name_policy(tmp_path):
    write_cache(tmp_path, [
        {'source': '这是一个普通的提示文本', 'text_type': 'name_or_item', 'translation': 'A normal prompt'},
        {'source': '继续', 'text_type': 'ui_short', 'translation': 'Continue'},
    ])
    terms = {'继续': {'primary': 'Proceed', 'category': '通用词'}}
    with patch('utils.translation_harness._term_hits', side_effect=AssertionError('unnecessary glossary scan')):
        assert set(_load_translation_cache(tmp_path, 'en', term_lookup=terms).values()) == {'A normal prompt', 'Continue'}
