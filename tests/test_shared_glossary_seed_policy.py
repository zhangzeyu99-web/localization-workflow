import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from utils.large_text_multilingual_executor import OpenAICompatibleClient
from utils.large_text_multilingual_pack import prepare_pack
from utils.large_text_multilingual_proofread import _validate_audit, run_deep_proofread
from utils.large_text_multilingual_runner import build_manifest
from utils.relay_runtime import IncompletePhase


@pytest.mark.parametrize('source,term,category,revised,locked', [
    ('强化', 'Enhance', 'soft 系统名', 'Refine', False),
    ('领取', 'Claim', '', 'Collect', False),
    ('姥姥', 'Grandma', '角色', 'Granny', False),
    ('士兵', 'Soldier', '角色', 'Trooper', False),
    ('强化', 'Enhance', '系统名', 'Refine', True),
    ('艾拉', 'Ella', '主角', 'Emma', True),
])
def test_real_pack_review_respects_exact_seed_strength(tmp_path, source, term, category, revised, locked):
    source_path = tmp_path / 'input.xlsx'
    terms_path = tmp_path / 'terms.xlsx'
    for path, headers, data in (
        (source_path, ['ID', 'CN', 'EN'], ['1', source, None]),
        (terms_path, ['CN', 'EN', '分类'], [source, term, category]),
    ):
        book = Workbook()
        book.active.append(headers)
        book.active.append(data)
        book.save(path)
        book.close()
    pack = prepare_pack(inputs=[source_path], term_base=terms_path, history_dirs=[],
                        target_langs=['EN'], work_dir=tmp_path / 'pack')
    row = json.loads(pack.items_jsonl.read_text(encoding='utf-8'))
    assert row['seed_origin'] == 'glossary_exact'
    seeds = json.loads((tmp_path / 'pack' / 'seed_memory.json').read_text(encoding='utf-8'))
    row['translations'] = seeds[source]
    initial = tmp_path / 'initial.jsonl'
    initial.write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
    manifest = build_manifest(work_dir=tmp_path / 'run', items_jsonl=pack.items_jsonl,
                              source_rows_jsonl=pack.source_rows_jsonl, target_langs=['EN'],
                              workbook_count=1, relay_config=None, proofread_mode='full')

    class Reviewer:
        def review_batch(self, rows, target_langs):
            return [{'review_key': item['review_key'], 'lang': 'EN', 'status': 'FIX',
                     'suggested': revised, 'reason': 'Contextual wording correction.'} for item in rows]

    class Auditor:
        def audit_batch(self, rows):
            return [{
                'review_key': item['review_key'], 'lang': item['lang'], 'decision': 'ACCEPT',
                'final': item['suggested'], 'reason': 'Checked against the supplied source.',
                'semantic_check': {
                    'source_meaning': source, 'final_meaning': revised, 'target_text': revised,
                    'meaning_preserved': True, 'roles_preserved': True, 'tone_preserved': True,
                    'head_and_modifiers_preserved': True, 'no_invented_entities': True,
                    'natural_target': True,
                },
                'independent_target_reading': {
                    'text': revised, 'meaning': revised, 'predicate_object': 'UI label', 'tone': 'neutral',
                },
            } for item in rows]

    def run():
        return run_deep_proofread(Path(manifest['manifest_path']), initial_cache=initial,
                                  reviewer=Reviewer(), auditor=Auditor())

    if locked:
        with pytest.raises(IncompletePhase, match='glossary_semantic_conflict'):
            run()
        assert not (tmp_path / 'run' / 'deep_proofread' / 'final_cache.jsonl').exists()
    else:
        summary = run()
        final = json.loads(summary.final_cache.read_text(encoding='utf-8'))
        assert final['translations']['EN'] == revised
        assert summary.changed_cells == 1
    assert json.loads(initial.read_text(encoding='utf-8'))['translations']['EN'] == term


@pytest.mark.parametrize('hits', [
    [],
    [{'source': '其他', 'category': 'soft', 'translations': {'EN': 'Claim'}}],
    [{'source': '领取', 'translations': {'EN': 'Claim'}}],
    [{'source': '领取', 'category': 'soft', 'translations': {'FR': 'Recevoir'}}],
])
def test_exact_seed_without_bound_classification_keeps_legacy_protection(hits):
    fix = {'review_key': '1', 'lang': 'EN', 'cn': '领取', 'current': 'Claim',
           'status': 'FIX', 'seed_origin': 'glossary_exact', 'term_hits': hits}
    decision = {'review_key': '1', 'lang': 'EN', 'decision': 'ACCEPT',
                'final': 'Collect', 'reason': 'Wording correction.'}
    with pytest.raises(ValueError, match='glossary_semantic_conflict'):
        _validate_audit([fix], [decision])


@pytest.mark.parametrize('category,locked', [('soft 系统名', False), ('系统名', True)])
def test_api_audit_prompt_uses_controller_classification(category, locked):
    class CapturingAuditor(OpenAICompatibleClient):
        def __init__(self):
            self.calls = []

        def _chat_json(self, system, payload, *, stage):
            self.calls.append((system, payload))
            return {'rows': [{'review_key': '1', 'lang': 'EN', 'decision': 'ACCEPT',
                              'final': 'Refine', 'reason': 'Context checked.'}]}

    row = {'review_key': '1', 'lang': 'EN', 'cn': '强化', 'current': 'Enhance',
           'suggested': 'Refine', 'status': 'FIX', 'seed_origin': 'glossary_exact',
           'glossary_seed_locked': not locked,
           'term_hits': [{'source': '强化', 'category': category, 'translations': {'EN': 'Enhance'}}]}
    client = CapturingAuditor()
    client.audit_batch([row])
    prompt, payload = client.calls[0]
    assert payload['suggestions'][0]['glossary_seed_locked'] is locked
    assert 'For glossary_seed_locked=true' in prompt
    assert 'For glossary_seed_locked=false' in prompt
    assert 'softness is not approval' in prompt
    assert 'For seed_origin=glossary_exact, only' not in prompt
