"""Bind independent target readings to the text actually selected by audit."""
from copy import deepcopy

import pytest

from utils.large_text_multilingual_executor import OpenAICompatibleClient
from utils.large_text_multilingual_proofread import _validate_audit


class ScriptedAuditor(OpenAICompatibleClient):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def _chat_json(self, system, payload, *, stage):
        self.calls.append((stage, system, deepcopy(payload)))
        return {'rows': next(self.responses)}


def suggestion(key='title', **overrides):
    return {'review_key': key, 'lang': 'EN', 'cn': '英勇的女王',
            'current': 'Brave Queen', 'suggested': 'Valiant Queen', 'status': 'FIX',
            'semantic_check_required': True, **overrides}


def reading(key='title', **overrides):
    return {'review_key': key, 'lang': 'EN', 'meaning': 'A brave queen.',
            'predicate_object': 'Queen is the head; valiant describes the queen.',
            'tone': 'Natural heroic title.', **overrides}


def decision(key='title', text='Valiant Queen', action='ACCEPT', **overrides):
    return {'review_key': key, 'lang': 'EN', 'decision': action, 'final': text,
            'reason': 'The selected wording preserves the supplied meaning.',
            'semantic_check': {'target_text': text, 'source_meaning': 'A brave queen.',
                               'final_meaning': 'A brave queen.', 'meaning_preserved': True,
                               'roles_preserved': True, 'tone_preserved': True,
                               'head_and_modifiers_preserved': True,
                               'no_invented_entities': True, 'natural_target': True}, **overrides}


def test_unchanged_official_title_keeps_single_audit_and_controller_bound_text():
    row = suggestion(cn='红心王后', current='Queen of Hearts', suggested='Queen of Hearts',
                     status='KEEP', name_semantic_check_required=True, seed_origin='glossary_exact')
    client = ScriptedAuditor([[reading(text='FORGED MODEL BINDING')],
                             [decision(text='Queen of Hearts')]])
    result = client.audit_batch([row])
    assert [call[0] for call in client.calls] == ['blind', 'audit']
    assert client.calls[0][2] == {'rows': [{'review_key': 'title', 'lang': 'EN', 'text': 'Queen of Hearts'}]}
    assert result[0]['independent_target_reading']['text'] == 'Queen of Hearts'
    assert _validate_audit([row], result)[('title', 'EN')]['final'] == 'Queen of Hearts'
    assert 'head noun' in client.calls[0][1]
    assert 'glossary_semantic_conflict' in client.calls[1][1]


@pytest.mark.parametrize('action,selected,wire_final', [
    ('REVISE', 'Courageous Queen', 'Courageous Queen'),
    ('REVERT', 'Brave Queen', 'Ignored model final'),
])
def test_changed_actual_selection_only_rereads_and_reaudits_changed_cell(action, selected, wire_final):
    row = suggestion(name_semantic_check_required=True)
    steady = suggestion('steady', cn='红心王后', current='Queen of Hearts', suggested='Queen of Hearts', status='KEEP')
    client = ScriptedAuditor([
        [reading(), reading('steady')],
        [decision(text=wire_final, action=action), decision('steady', text='Queen of Hearts')],
        [reading(text='FORGED AGAIN')],
        [decision(text=selected, action=action)],
    ])
    result = client.audit_batch([row, steady])
    assert [call[0] for call in client.calls] == ['blind', 'audit', 'blind', 'audit']
    assert client.calls[2][2] == {'rows': [{'review_key': 'title', 'lang': 'EN', 'text': selected}]}
    assert [item['review_key'] for item in client.calls[3][2]['suggestions']] == ['title']
    assert client.calls[3][2]['suggestions'][0]['prior_audit']['final'] == selected
    final = next(item for item in result if item['review_key'] == 'title')
    assert final['independent_target_reading']['text'] == selected
    assert _validate_audit([row, steady], result)[('title', 'EN')]['decision'] == action


def test_second_changed_final_fails_only_that_cell_validation():
    row = suggestion()
    steady = suggestion('steady', semantic_check_required=False)
    client = ScriptedAuditor([
        [reading()],
        [decision(text='Courageous Queen', action='REVISE'), decision('steady')],
        [reading()],
        [decision(text='Fearless Queen', action='REVISE')],
    ])
    results = {item['review_key']: item for item in client.audit_batch([row, steady])}
    assert len(client.calls) == 4
    assert _validate_audit([steady], [results['steady']])
    with pytest.raises(ValueError, match='semantic evidence is not bound'):
        _validate_audit([row], [results['title']])
    assert results['title']['independent_target_reading']['text'] == 'Courageous Queen'


def test_reported_glossary_conflict_is_not_reaudited_or_silently_reset():
    row = suggestion(seed_origin='glossary_exact')
    client = ScriptedAuditor([
        [reading()], [decision(unresolved_issues=['glossary_semantic_conflict'])],
    ])
    result = client.audit_batch([row])
    assert [call[0] for call in client.calls] == ['blind', 'audit']
    with pytest.raises(ValueError, match='glossary_semantic_conflict'):
        _validate_audit([row], result)


def test_blind_reading_rejects_unbound_model_keys():
    client = ScriptedAuditor([[reading('unexpected')]])
    with pytest.raises(ValueError, match='invalid blind semantic reading'):
        client.audit_batch([suggestion()])


def test_changed_text_does_not_reuse_previous_blind_reading_cache():
    from utils.relay_runtime import RelayRuntime

    client = ScriptedAuditor([[reading()], [reading(meaning='A different queen.')]])
    client.runtime = RelayRuntime()
    client.checkpoint_identity = 'anonymous-binding-test'
    original = {'review_key': 'title', 'lang': 'EN', 'text': 'Valiant Queen'}
    revised = {**original, 'text': 'Courageous Queen'}
    first = client._read_target_texts([original])
    assert client._read_target_texts([original]) == first
    second = client._read_target_texts([revised])
    assert len(client.calls) == 2
    assert second[('title', 'EN')]['text'] == 'Courageous Queen'
    assert second[('title', 'EN')]['meaning'] == 'A different queen.'
