import unittest
from pathlib import Path
from unittest.mock import patch

from utils.large_text_multilingual_gate import cache_lint
from utils.structured_text_template import (
    aligned_review_slots, parse_template, render_reviewed_target,
    render_translations, source_template_diagnostics, translation_slots,
)


class StructuredBoundaryTests(unittest.TestCase):
    def test_opaque_payload_requires_exact_boundary_whitespace(self):
        source = ' \t_payload\r\n'
        for target, expected in ((source, 0), (source.strip(), 1)):
            with self.subTest(target=target):
                rows = [{'key': 'opaque', 'cn': source, 'opaque_payload_preserved': True,
                         'translations': {'EN': target}}]
                with patch('utils.large_text_multilingual_gate.read_jsonl', return_value=rows):
                    result = cache_lint(Path('unused.jsonl'), target_langs=['EN'])
                self.assertEqual(result['hard_blockers'], expected)

    def test_translation_preserves_spaces_next_to_program_owned_tags(self):
        source = '<p>等级<@0>级，奖励<b>金币</b>。</p>'
        template = parse_template(source)
        slots = translation_slots(template)
        result = render_translations(template, slots,
                                     {'0': 'Level ', '1': ', reward ', '2': 'gold'}, lang='DE')
        self.assertEqual(result, '<p>Level <@0>, reward <b>gold</b>.</p>')

    def test_review_fix_and_keep_retain_approved_spaces_and_cr(self):
        source = '<p>等级<@0>级</p>'
        before = '<p>Level <@0> required\r\n</p>'
        template, slots = aligned_review_slots(source, before)
        kept = render_reviewed_target(template, slots, {slot.slot_key: slot.target for slot in slots})
        self.assertEqual(kept, before)
        changed = render_reviewed_target(template, slots, {'0': 'Rank', '1': 'needed '})
        self.assertEqual(changed, '<p>Rank <@0> needed \r\n</p>')

    def test_fixed_source_token_variants_are_not_normalized(self):
        template = parse_template('<p>｛0｝奖励，</p>')
        slots = translation_slots(template)
        self.assertEqual(render_translations(template, slots, {'0': 'Reward'}, lang='EN'),
                         '<p>｛0｝Reward,</p>')

    def test_source_preflight_exposes_brace_ambiguity_and_invalid_json(self):
        findings = source_template_diagnostics([
            {'key': 'human', 'cn': '<p>{金币不足}</p>'},
            {'key': 'literal', 'cn': '<p>获得｛0｝奖励</p>'},
            {'key': 'broken', 'cn': '{"text":"奖励"'},
            {'key': 'valid', 'cn': '{"text":"奖励<@0>"}'},
        ])
        self.assertEqual({item['key']: item['type'] for item in findings}, {
            'human': 'ambiguous_natural_brace', 'literal': 'source_token_variant',
            'broken': 'source_template_invalid'})


if __name__ == '__main__':
    unittest.main()
