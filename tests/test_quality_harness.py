import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from utils.quality_harness import load_fixture, run_fixture, scan_workbook


class QualityHarnessTests(unittest.TestCase):
    def test_fixture_detects_known_bad_and_good_cases(self):
        fixture = {
            "cases": [
                {
                    "id": "bad-title-case",
                    "source": "该帐号创角过多",
                    "translation": "Too Many Roles",
                    "expected_issues": ["title_case_overuse"],
                },
                {
                    "id": "bad-internal-token",
                    "source": "调试残留",
                    "translation": "ZXN37Q",
                    "expected_issues": ["internal_token_leak"],
                },
                {
                    "id": "good-feature-title",
                    "source": "七日登录",
                    "translation": "7-Day Login",
                    "expected_issues": [],
                },
            ]
        }

        result = run_fixture(fixture)

        self.assertTrue(result.passed, result.failures)
        self.assertEqual(result.total_cases, 3)
        self.assertEqual(result.issue_counts["title_case_overuse"], 1)
        self.assertEqual(result.issue_counts["internal_token_leak"], 1)

    def test_fixture_reports_expectation_mismatch(self):
        fixture = {
            "cases": [
                {
                    "id": "bad-clipped-word",
                    "source": "登录超时",
                    "translation": "Logi time",
                    "expected_issues": [],
                }
            ]
        }

        result = run_fixture(fixture)

        self.assertFalse(result.passed)
        self.assertEqual(result.failures[0]["id"], "bad-clipped-word")
        self.assertIn("clipped_word", result.failures[0]["actual_issues"])

    def test_load_fixture_reads_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            path.write_text(json.dumps({"cases": []}), encoding="utf-8")

            self.assertEqual(load_fixture(path), {"cases": []})

    def test_scan_workbook_reports_hard_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.append(["ID", "CN", "EN"])
            ws.append([1, "系统错误", "System Error"])
            ws.append([2, "战令", "Battle Pass"])
            wb.save(path)

            result = scan_workbook(path)

            self.assertFalse(result.passed)
            self.assertEqual(result.issue_counts["title_case_overuse"], 1)
            self.assertEqual(result.rows_scanned, 2)
            self.assertEqual(result.issues[0]["row"], 2)

    def test_runtime_placeholder_sentence_does_not_trigger_leading_lowercase(self):
        fixture = {
            "cases": [
                {
                    "id": "runtime-message",
                    "source": "<color=#457B9F>##1</color>已同意<color=#457B9F>##2</color>加入军团！",
                    "translation": "<color=#457B9F>##1</color> approved <color=#457B9F>##2</color> to join the Legion!",
                    "expected_issues": [],
                }
            ]
        }

        result = run_fixture(fixture)

        self.assertTrue(result.passed, result.failures)

    def test_number_unit_prefix_does_not_trigger_leading_lowercase(self):
        fixture = {
            "cases": [
                {
                    "id": "voice-limit",
                    "source": "限30秒语音\\n松手发送\\n划开取消发送",
                    "translation": "30s Voice Limit\\nRelease to Send\\nSlide Away to Cancel",
                    "expected_issues": [],
                }
            ]
        }

        result = run_fixture(fixture)

        self.assertTrue(result.passed, result.failures)

    def test_hash_code_and_placeholder_compaction_are_hard_issues(self):
        fixture = {
            "cases": [
                {
                    "id": "blacklist-limit-code",
                    "source": "黑名单数量已达上限",
                    "translation": "#BRUL",
                    "expected_issues": ["hash_code_abbreviation"],
                },
                {
                    "id": "spend-item-code",
                    "source": "花费##1个##2",
                    "translation": "S##1##2",
                    "expected_issues": ["placeholder_compaction"],
                },
                {
                    "id": "employed-glue-code",
                    "source": "##1上岗##2位居民",
                    "translation": "##1Employed##2",
                    "expected_issues": ["placeholder_word_glue"],
                },
            ]
        }

        result = run_fixture(fixture)

        self.assertTrue(result.passed, result.failures)


if __name__ == "__main__":
    unittest.main()
