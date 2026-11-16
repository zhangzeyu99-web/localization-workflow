import json
from pathlib import Path

import pytest

from utils.large_text_multilingual_proofread import (
    _is_high_risk_review_row, _review_item_key, _review_row, _validate_audit,
    run_deep_proofread,
)
from utils.large_text_multilingual_runner import build_manifest
from utils.localization_quality_policy import (
    QUALITY_POLICY_VERSION, localization_quality_policy, requires_name_semantic_check,
)
from utils.relay_runtime import IncompletePhase
from utils.translation_harness import _load_translation_cache


def evidence(text):
    return {
        'semantic_check': {
            'target_text': text, 'source_meaning': 'The queen associated with hearts.',
            'final_meaning': 'The queen associated with hearts.', 'meaning_preserved': True,
            'roles_preserved': True, 'tone_preserved': True, 'head_and_modifiers_preserved': True,
            'no_invented_entities': True, 'natural_target': True,
        },
        'independent_target_reading': {
            'text': text, 'meaning': 'The queen associated with hearts.',
            'predicate_object': 'Queen is the head; of hearts identifies her.', 'tone': 'Title',
        },
    }


@pytest.mark.parametrize('row,expected', [
    ({'cn': '春日欢庆'}, False),
    ({'context': {'text_type': '称号'}}, True),
    ({'context': '{"type":"ui_skill_name"}'}, True),
    ({'context': {'text_type': '技能描述'}}, False),
    ({'context': {'note': '称号'}}, False),
    ({'text_type': 'name_or_item', 'cn': '这是一个普通的提示文本'}, False),
    ({'risk_flags': ['modifier_attachment']}, True),
    ({'cn': '红心女王', 'term_hits': [{'source': '红心女王', 'category': '英雄名'}]}, True),
    ({'cn': '红心女王到了', 'term_hits': [{'source': '红心女王', 'category': '英雄名'}]}, False),
])
def test_semantic_routing_requires_explicit_evidence(row, expected):
    assert requires_name_semantic_check(row) is expected


def test_name_evidence_covers_keep_revise_and_real_revert_without_banning_of():
    fix = {'review_key': 'a', 'lang': 'EN', 'cn': '红心女王', 'current': 'Queen of Hearts',
           'suggested': 'Queen of Hearts', 'status': 'KEEP', 'semantic_check_required': True,
           'name_semantic_check_required': True}
    decision = {'review_key': 'a', 'lang': 'EN', 'decision': 'ACCEPT', 'final': 'Queen of Hearts'}
    with pytest.raises(ValueError, match='semantic'):
        _validate_audit([fix], [decision])
    good = {**decision, **evidence(decision['final'])}
    assert _validate_audit([fix], [good])
    for field in ('head_and_modifiers_preserved', 'no_invented_entities', 'natural_target'):
        bad = {**good, 'semantic_check': {**good['semantic_check'], field: False}}
        with pytest.raises(ValueError, match='name semantic'):
            _validate_audit([fix], [bad])
    with pytest.raises(ValueError, match='selected final'):
        _validate_audit([fix], [{**good, 'decision': 'REVISE', 'final': 'Heart Queen'}])
    with pytest.raises(ValueError, match='reading must be bound'):
        _validate_audit([fix], [{**good, 'independent_target_reading': {
            **good['independent_target_reading'], 'text': 'Heart Queen'}}])
    # REVERT validates the actual current value, not the model's unused final field.
    reverted = {**good, 'decision': 'REVERT', 'final': 'unused'}
    assert _validate_audit([{**fix, 'status': 'FIX'}], [reverted])
    with pytest.raises(ValueError, match='name semantic'):
        _validate_audit([{**fix, 'status': 'FIX', 'current': 'Another queen'}], [reverted])


def test_exact_glossary_changes_cannot_silently_restore_or_override_old_text(tmp_path):
    row = {'key': '1', 'cn': '忠城卫士', 'context': 'ui', 'seed_origin': 'glossary_exact',
           'translations': {'EN': 'Guardian of the Loyal City'}}
    path = tmp_path / 'initial.jsonl'
    path.write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
    manifest = build_manifest(work_dir=tmp_path / 'work', items_jsonl=path, source_rows_jsonl=None,
                              target_langs=['EN'], workbook_count=1, relay_config=None, proofread_mode='full')

    class Reviewer:
        def review_batch(self, rows, target_langs):
            return [{'review_key': r['review_key'], 'lang': 'EN', 'status': 'FIX',
                     'suggested': 'Loyal City Guardian', 'reason': 'The guardian is loyal, not the city.'}
                    for r in rows]

    class Auditor:
        def audit_batch(self, rows):
            return [{'review_key': r['review_key'], 'lang': r['lang'], 'decision': 'ACCEPT',
                     'final': r['suggested'], 'reason': 'Modifier attachment corrected.'} for r in rows]

    with pytest.raises(IncompletePhase, match='glossary_semantic_conflict'):
        run_deep_proofread(Path(manifest['manifest_path']), initial_cache=path,
                          reviewer=Reviewer(), auditor=Auditor())
    assert not (tmp_path / 'work' / 'deep_proofread' / 'final_cache.jsonl').exists()
    assert json.loads(path.read_text(encoding='utf-8')) == row
    # A supplied glossary update changes the semantic key without deleting any checkpoints.
    changed = {**row, 'translations': {'EN': 'Loyal City Guardian'}}
    assert _review_item_key(row, 'EN') != _review_item_key(changed, 'EN')


def test_explicit_name_is_in_sampled_review_and_preserves_seed_provenance():
    row = {'cn': '红心女王', 'context': {'text_type': '称号'}, 'seed_origin': 'glossary_exact'}
    request = _review_row(row, 'a', ['EN'])
    assert request['seed_origin'] == 'glossary_exact'
    assert request['name_semantic_check_required'] is True
    assert _is_high_risk_review_row(request)
    assert _review_item_key(row, 'EN') != _review_item_key({**row, 'seed_origin': ''}, 'EN')


@pytest.mark.parametrize('seed_origin', ['', 'glossary_exact'])
def test_structured_name_keeps_project_guidance_and_audits_real_selected_text(tmp_path, seed_origin):
    row = {'key': 'name', 'cn': '["红心女王"]', 'source_mode': 'cn',
           'context': {'type': 'ui', 'text_type': '称号', 'project_style': 'Use the established title.'},
           'seed_origin': seed_origin, 'translations': {'EN': '["Queen of Hearts"]'}}
    path = tmp_path / 'initial.jsonl'
    path.write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
    manifest = build_manifest(work_dir=tmp_path / 'work', items_jsonl=path, source_rows_jsonl=None,
                              target_langs=['EN'], workbook_count=1, relay_config=None, proofread_mode='full')

    class Client:
        def review_batch(self, rows, languages):
            assert len(rows) == 1
            request = rows[0]
            assert request['context']['project_style'] == 'Use the established title.'
            assert request['cn'] == '红心女王'
            assert request['name_semantic_check_required'] is True
            assert request['seed_origin'] == seed_origin
            return [{'review_key': request['review_key'], 'lang': 'EN', 'status': 'KEEP',
                     'suggested': 'Queen of Hearts', 'reason': 'Established title.'}]

        def audit_batch(self, rows):
            request = rows[0]
            assert request['semantic_check_required'] is True
            assert request['context']['segment_context']['project_style'] == 'Use the established title.'
            assert request['seed_origin'] == seed_origin
            return [{'review_key': request['review_key'], 'lang': 'EN', 'decision': 'ACCEPT',
                     'final': 'Queen of Hearts', **evidence('Queen of Hearts')}]

    client = Client()
    summary = run_deep_proofread(Path(manifest['manifest_path']), initial_cache=path,
                                reviewer=client, auditor=client)
    assert json.loads(summary.final_cache.read_text(encoding='utf-8'))['translations'] == row['translations']
    assert summary.changed_cells == 0


def test_normal_name_cache_is_policy_bound_but_unaffected_prose_stays_reusable(tmp_path):
    directory = tmp_path / '.translation_cache'
    directory.mkdir()
    rows = [
        {'source': '红心女王', 'text_type': 'name', 'translation': 'Queen of Hearts'},
        {'source': '你好。', 'text_type': 'sentence', 'translation': 'Hello.'},
    ]
    path = directory / 'en.jsonl'
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    assert list(_load_translation_cache(tmp_path, 'en').values()) == ['Hello.']
    rows[0]['language_quality_policy_version'] = QUALITY_POLICY_VERSION
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows), encoding='utf-8')
    assert 'Queen of Hearts' in _load_translation_cache(tmp_path, 'en').values()
    for lang in ('en', 'es', 'pt', 'fr', 'de', 'ru'):
        assert 'head noun' in localization_quality_policy(lang)
        assert 'unresolved_issues' in localization_quality_policy(lang)
