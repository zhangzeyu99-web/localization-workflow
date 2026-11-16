import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from utils.quality_harness import scan_cache_surface, scan_workbook


class CacheSurfaceTests(unittest.TestCase):
    def test_same_rules_before_export_and_no_cross_sheet_id_merge(self):
        rows = [
            {'id': '1', 'cn': '领取奖励', 'translations': {'EN': 'Claim all rewards now immediately'}},
            {'id': '2', 'cn': '登录超时', 'translations': {'EN': 'Logi time'}},
            {'id': '3', 'cn': '宝石-1', 'translations': {'EN': 'Gem-1'}},
            {'id': '4', 'cn': '宝石-2', 'translations': {'EN': 'Gem-2'}},
            {'id': '5', 'cn': '宝石-3', 'translations': {'EN': 'Jewel-3'}},
        ]
        for index, row in enumerate(rows, 2):
            row.update(source_file='source.xlsx', sheet='Text', row=index)
        early = scan_cache_surface(rows, ['EN'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.xlsx'
            wb = Workbook()
            ws = wb.active
            ws.title = 'Text'
            ws.append(['ID', 'CN', 'EN'])
            for row in rows:
                ws.append([row['id'], row['cn'], row['translations']['EN']])
            wb.save(path)
            wb.close()
            final = scan_workbook(path, auto_discover_terms=False)
        self.assertEqual(early['issue_counts'], dict(final.issue_counts))
        self.assertGreater(early['hard_blockers'], 0)
        self.assertFalse(early['replaces_final_harness'])
        split = [dict(row, sheet=str(index), id='same') for index, row in enumerate(rows[2:])]
        self.assertNotIn('numbered_term_inconsistency', scan_cache_surface(split, ['EN'])['issue_counts'])

    def test_series_findings_keep_language_and_physical_identity(self):
        rows = [{'id': 'same', 'source_file': 'a.xlsx', 'sheet': 'Body', 'row': n,
                 'cn': '奖励' + numeral, 'translations': {'EN': target}}
                for n, numeral, target in [(2, 'I', 'Reward I'), (3, 'II', 'Prize II')]]
        result = scan_cache_surface(rows, ['EN'])
        series = [item for item in result['issues'] if item['check_type'] == 'ui_series_inconsistency']
        self.assertEqual({(item['row'], item['lang']) for item in series}, {(2, 'EN'), (3, 'EN')})

    def test_json_keys_and_markup_are_not_visible_sentence_initials(self):
        from utils.quality_harness import check_row
        source = '{"text":"请领取今天的所有奖励。"}'
        valid = '{"text":"<b>Collect all rewards today.</b>"}'
        invalid = '{"text":"<b>collect all rewards today.</b>"}'
        self.assertNotIn('leading_lowercase', {i.check_type for i in check_row('1', source, valid)})
        self.assertIn('leading_lowercase', {i.check_type for i in check_row('1', source, invalid)})

    def test_unresolved_ui_overflow_blocks_before_any_workbook_write(self):
        from unittest.mock import patch
        from utils.large_text_multilingual_pipeline import run_pipeline

        class Keep:
            def review_batch(self, rows, languages):
                return [dict(review_key=row['review_key'], lang=lang, status='KEEP',
                             suggested=row['translations'][lang], reason='keep')
                        for row in rows for lang in languages]

            def audit_batch(self, rows):
                return [dict(review_key=row['review_key'], lang=row['lang'], decision='ACCEPT',
                             final=row['suggested'], reason='accept') for row in rows]

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'input.xlsx'
            wb = Workbook()
            wb.active.append(['ID', 'CN', 'EN'])
            wb.active.append(['1', '领取奖励', 'Claim all rewards now immediately'])
            wb.save(source)
            wb.close()
            client = Keep()
            with patch('utils.large_text_multilingual_pipeline.write_translation_workbooks') as write:
                with self.assertRaisesRegex(ValueError, 'surface precheck'):
                    run_pipeline(inputs=[source], target_langs=['EN'], task_dir=root,
                                 term_base=None, history_dirs=[], relay_config=None,
                                 task_mode='review', proofread_mode='full',
                                 translation_client=client, reviewer=client, auditor=client)
                write.assert_not_called()
            self.assertTrue((root / '_work/large_text_multilingual/final_surface_precheck.json').exists())


if __name__ == '__main__':
    unittest.main()
