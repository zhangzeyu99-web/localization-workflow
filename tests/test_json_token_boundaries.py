"""Compact JSON syntax is not a placeholder; decoded leaf contracts still hold."""
import json

import pytest
from openpyxl import Workbook, load_workbook

from utils.large_text_multilingual_gate import TOKEN_RE, pair_integrity_issues, protected_tokens
from utils.large_text_multilingual_pipeline import run_pipeline
from utils.large_text_multilingual_proofread import _preserves_protected_tokens


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def codes(source, target, tokens=None):
    return {code for code, _ in pair_integrity_issues(
        {'cn': source, 'tokens': tokens or []}, 'EN', target)}


@pytest.mark.parametrize('payload,translated', [
    ({'text': '奖励。', 'code': 'READY…'}, {'text': 'Reward.', 'code': 'READY…'}),
    ({'text': '奖励。', 'levels': [1, 2]}, {'text': 'Reward.', 'levels': [1, 2]}),
])
def test_compact_json_and_legacy_pseudo_tokens_pass(payload, translated):
    source, target = compact(payload), compact(translated)
    legacy = TOKEN_RE.findall(source)
    assert protected_tokens({'cn': source}) == []
    assert not codes(source, target)
    assert not codes(source, target, legacy)
    assert _preserves_protected_tokens(source, target, legacy)


def test_json_leaf_tokens_and_unknown_explicit_constraints_remain_protected():
    source = compact({'text': '奖励 {count} {count} %s ##1 [RED] <b><@0></b>'})
    target = compact({'text': 'Reward {count} {count} %s ##1 [RED] <b><@0></b>'})
    assert not codes(source, target)
    for removed in ('{count}', '%s', '##1', '[RED]', '<@0>'):
        assert 'protected_token_missing' in codes(source, target.replace(removed, '', 1))
    assert 'protected_token_extra' in codes(source, target.replace('Reward', 'Reward {other}'))
    assert 'protected_token_missing' in codes(source, target, ['EXPLICIT_CONSTRAINT'])
    literal = compact({'text': '奖励 {literal}', 'code': '{"x":1}'})
    assert '{"x":1}' in protected_tokens({'cn': literal, 'tokens': ['{"x":1}']})
    # Placeholder-looking JSON keys remain fixed by the structural gate.
    assert '{KEY}' in protected_tokens({'cn': compact({'{KEY}': '奖励'}), 'tokens': ['{KEY}']})


def test_json_decoded_escape_tokens_do_not_confuse_literal_and_actual_newlines():
    source = compact({'text': '奖励\n<b title="x">奖励</b>\\n奖励'})
    target = compact({'text': 'Reward\n<b title="x">Reward</b>\\nReward'})
    legacy = TOKEN_RE.findall(source)
    assert not codes(source, target, legacy)
    assert _preserves_protected_tokens(source, target, legacy)
    for leaf in ('Reward<b title="x">Reward</b>\\nReward',
                 'Reward\n<b title="x">Reward</b>Reward'):
        changed = compact({'text': leaf})
        assert 'protected_token_missing' in codes(source, changed, legacy)
        assert not _preserves_protected_tokens(source, changed, legacy)
    changed_tag = target.replace('title=\\\"x\\\"', 'title=\\\"y\\\"')
    assert codes(source, changed_tag, legacy)
    assert not _preserves_protected_tokens(source, changed_tag, legacy)


def test_json_token_scope_and_strict_structure_still_block():
    source = compact({'text': '<b><@0></b>奖励', 'other': '奖励', 'fixed': 'READY…'})
    target = compact({'text': '<b><@0></b>Reward', 'other': 'Reward', 'fixed': 'READY…'})
    assert not codes(source, target)
    assert codes(source, target.replace('<b><@0></b>', '<b></b><@0>'))
    moved = compact({'text': 'Reward', 'other': '<b><@0></b>Reward', 'fixed': 'READY…'})
    assert codes(source, moved)
    assert codes(source, target.replace('READY…', 'READY...'))
    assert codes(source, target + ' trailing')
    assert codes(source, target.replace('Reward', 'Reward…', 1))
    assert not codes('奖励 {count} %s', 'Reward {count} %s')
    assert 'protected_token_missing' in codes('奖励 {count}', 'Reward')


@pytest.mark.parametrize('mode', ['basic', 'full'])
def test_compact_json_v2_export_and_deep_review(tmp_path, mode):
    source_text = compact({'text': '奖励。', 'code': 'READY…', 'levels': [1, 2]})
    target_text = compact({'text': 'Reward.', 'code': 'READY…', 'levels': [1, 2]})
    source = tmp_path / 'source.xlsx'
    book = Workbook()
    book.active.append(['ID', 'CN', 'EN'])
    book.active.append([1, source_text, None])
    book.save(source)
    book.close()

    class Client:
        calls = 0
        reviewed = 0
        audited = 0

        def translate_batch(self, rows, target_langs):
            self.calls += 1
            return [{'request_key': row['request_key'],
                     'translations': {lang: 'Reward' for lang in target_langs}} for row in rows]

        def review_batch(self, rows, target_langs):
            self.reviewed += len(rows)
            assert all('{' not in row['cn'] for row in rows)
            return [{'review_key': row['review_key'], 'lang': target_langs[0],
                     'status': 'KEEP', 'suggested': row['translations'][target_langs[0]],
                     'reason': 'meaning preserved'} for row in rows]

        def audit_batch(self, suggestions):
            self.audited += len(suggestions)
            return [{'review_key': row['review_key'], 'lang': row['lang'],
                     'decision': 'ACCEPT', 'final': row['suggested'],
                     'reason': 'meaning preserved'} for row in suggestions]

    client = Client()
    kwargs = dict(inputs=[source], term_base=None, history_dirs=[], target_langs=['EN'],
                  task_dir=tmp_path / 'task', relay_config=None, proofread_mode=mode,
                  translation_client=client, reviewer=client, auditor=client)
    result = run_pipeline(**kwargs)
    book = load_workbook(result.delivery_dir / source.name)
    try:
        assert book.active['B2'].value == source_text
        assert book.active['C2'].value == target_text
    finally:
        book.close()
    if mode == 'full':
        assert client.reviewed and client.audited
    calls = (client.calls, client.reviewed, client.audited)
    assert run_pipeline(**kwargs).delivery_dir == result.delivery_dir
    assert (client.calls, client.reviewed, client.audited) == calls


def test_legacy_compact_metadata_does_not_revert_valid_deep_review(tmp_path):
    from utils.large_text_multilingual_executor import _write_jsonl
    from utils.large_text_multilingual_gate import read_jsonl
    from utils.large_text_multilingual_proofread import run_deep_proofread
    from utils.large_text_multilingual_runner import build_manifest

    source = compact({'text': '每日礼包', 'code': 'READY…'})
    initial_text = compact({'text': 'Daily Pack', 'code': 'READY…'})
    rows = [{'key': 'legacy', 'cn': source, 'tokens': TOKEN_RE.findall(source),
             'translations': {'EN': initial_text}, 'term_hits': []}]
    items, initial = tmp_path / 'items.jsonl', tmp_path / 'initial.jsonl'
    _write_jsonl(items, rows)
    _write_jsonl(initial, rows)
    manifest = build_manifest(work_dir=tmp_path / 'work', items_jsonl=items,
                              source_rows_jsonl=None, target_langs=['EN'],
                              workbook_count=1, relay_config=None, proofread_mode='full')

    class Review:
        def review_batch(self, rows, target_langs):
            return [{'review_key': row['review_key'], 'lang': target_langs[0],
                     'status': 'FIX', 'suggested': 'Daily Bundle',
                     'reason': 'use natural package name'} for row in rows]

        def audit_batch(self, rows):
            return [{'review_key': row['review_key'], 'lang': row['lang'],
                     'decision': 'ACCEPT', 'final': row['suggested'],
                     'reason': 'meaning and daily scope preserved'} for row in rows]

    from pathlib import Path
    review = Review()
    summary = run_deep_proofread(Path(manifest['manifest_path']), initial_cache=initial,
                                reviewer=review, auditor=review)
    final = read_jsonl(summary.final_cache)[0]['translations']['EN']
    assert final == compact({'text': 'Daily Bundle', 'code': 'READY…'})
    assert summary.changed_cells == 1
    assert not codes(source, final, rows[0]['tokens'])
