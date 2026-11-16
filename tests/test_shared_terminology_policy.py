import json

import pytest
from openpyxl import Workbook

from utils.ai_checker import _make_prompt_header, format_recheck_prompt
from utils.large_text_multilingual_gate import cache_lint
from utils.large_text_multilingual_pack import STRICT_TERM_CATEGORIES, _load_terms, _term_hits
from utils.localization_quality_policy import requires_name_semantic_check
from utils.quality_harness_terms import _collect_term_context
from utils.translation_harness import prepare_translation_harness


@pytest.mark.parametrize('category', sorted(STRICT_TERM_CATEGORIES))
def test_existing_character_categories_also_require_name_semantics(category):
    hit = {'source': '星海守卫', 'category': category}
    assert requires_name_semantic_check({'cn': '星海守卫', 'term_hits': [hit]})
    assert not requires_name_semantic_check({'cn': '星海守卫来了。', 'term_hits': [hit]})


def glossary(path, rows):
    book = Workbook()
    book.active.append(['CN', 'EN', '分类'])
    for row in rows:
        book.active.append(row)
    book.save(path)
    book.close()


@pytest.mark.parametrize('source,term,category,target,missing', [
    ('烈焰斩', 'Flame Strike', '技能名', 'Flame Strike', False),
    ('烈焰斩', 'Flame Strike', '技能名', 'Cold Blow', True),
    ('高塔', 'Watch Tower', '建筑名', 'watch towers', False),
    ('高塔', 'Watch Tower', '建筑名', 'Farm', True),
    ('森林', 'Emerald Forest', '地名', 'Desert', True),
    ('强化', 'Enhance', '系统名', 'Refine', True),
    ('强化', 'Enhance', 'soft 系统名', 'Refine', False),
    ('艾拉', 'Ella', 'soft 角色名', 'Emma', False),
    ('领取', 'Claim', '', 'Collect', False),
])
def test_v2_reuses_standalone_term_strength_and_natural_matching(tmp_path, source, term, category, target, missing):
    term_file = tmp_path / 'terms.xlsx'
    glossary(term_file, [(source, term, category)])
    terms = _load_terms(term_file, ['EN'])
    row = {'key': '1', 'cn': source, 'term_hits': _term_hits(source, terms), 'translations': {'EN': target}}
    cache = tmp_path / 'cache.jsonl'
    cache.write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
    report = cache_lint(cache, target_langs=['EN'], term_base=term_file)
    assert ('term_missing' in report['hard_by_type']) is missing


def test_shared_strength_keeps_dialogue_scope_and_exact_cell_waiver(tmp_path):
    term_file = tmp_path / 'terms.xlsx'
    glossary(term_file, [('高塔', 'Watch Tower', '建筑名'), ('艾拉', 'Ella', '主角'),
                         ('姥姥', 'Grandma', '角色')])
    terms = _load_terms(term_file, ['EN'])
    rows = [
        {'key': 'prose', 'cn': '高塔附近见。', 'translations': {'EN': 'See you there.'}},
        {'key': 'name', 'cn': '艾拉，快来！', 'translations': {'EN': 'Emma, come here!'}},
        {'key': 'kinship', 'cn': '看望姥姥', 'translations': {'EN': 'Visit her.'}},
    ]
    for row in rows:
        row['term_hits'] = _term_hits(row['cn'], terms)
    cache = tmp_path / 'cache.jsonl'
    cache.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')
    report = cache_lint(cache, target_langs=['EN'], term_base=term_file)
    assert [(issue['key'], issue['type']) for issue in report['issues']] == [('name', 'term_missing')]
    row = rows[1]
    row['term_waivers'] = [{'source': '艾拉', 'lang': 'EN', 'target': row['translations']['EN'],
                           'cn': row['cn'], 'translation_source': row['cn'], 'context': '',
                           'reason': 'Approved identity in this scoped dialogue only.'}]
    cache.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')
    assert cache_lint(cache, target_langs=['EN'], term_base=term_file)['hard_blockers'] == 0
    row['translations']['EN'] = 'Another person, come here!'
    cache.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')
    assert cache_lint(cache, target_langs=['EN'], term_base=term_file)['hard_by_type'] == {'term_missing': 1}


def test_explicit_variants_remain_available_in_multilingual_term_matching(tmp_path):
    term_file = tmp_path / 'terms.xlsx'
    book = Workbook()
    book.active.append(['CN', 'FR', 'FR_2', '分类'])
    book.active.append(['高塔', 'Tour de garde', 'Tours de garde', '建筑名'])
    book.save(term_file)
    book.close()
    terms = _load_terms(term_file, ['FR'])
    row = {'key': '1', 'cn': '高塔', 'term_hits': terms, 'translations': {'FR': 'Tours de garde'}}
    cache = tmp_path / 'cache.jsonl'
    cache.write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
    assert cache_lint(cache, target_langs=['FR'], term_base=term_file)['hard_blockers'] == 0


def test_explicit_contextual_enforcement_is_not_softened(tmp_path):
    term_file = tmp_path / 'terms.xlsx'
    glossary(term_file, [('高塔', 'Watch Tower', '强术语')])
    terms = _load_terms(term_file, ['EN'])
    row = {'key': '1', 'cn': '在高塔附近见。', 'term_hits': terms,
           'translations': {'EN': 'See you there.'}}
    cache = tmp_path / 'cache.jsonl'
    cache.write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
    assert cache_lint(cache, target_langs=['EN'], term_base=term_file)['hard_by_type'] == {'term_missing': 1}
    row['translations']['EN'] = 'See you near the watch tower.'
    cache.write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
    assert cache_lint(cache, target_langs=['EN'], term_base=term_file)['hard_blockers'] == 0


def test_explicit_soft_name_is_not_promoted_by_ordinary_harness():
    book = Workbook()
    book.active.title = 'Glossary'
    book.active.append(['CN', 'EN', '分类'])
    book.active.append(['艾拉', 'Ella', 'soft 角色名'])
    context = _collect_term_context(book, None)
    assert context['person_names'] == []
    assert '艾拉' in context['soft']
    book.close()


def test_name_policy_reaches_ordinary_translation_review_and_recheck(tmp_path):
    path = tmp_path / 'input.xlsx'
    book = Workbook()
    book.active.append(['ID', 'CN', 'EN'])
    book.active.append([1, '红心女王', None])
    book.save(path)
    book.close()
    prepared = prepare_translation_harness(path, output_dir=tmp_path / 'work')
    packet = json.loads(prepared.workpack_path.read_text(encoding='utf-8'))
    prompts = [packet['language_quality_policy'], _make_prompt_header('en'),
               format_recheck_prompt([], 1, 1, lang='en')]
    assert all('head noun' in prompt and 'unresolved_issues' in prompt for prompt in prompts)
