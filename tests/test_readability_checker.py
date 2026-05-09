import unittest

from utils.readability_checker import check_readability


class ReadabilityCheckerTests(unittest.TestCase):
    def _types(self, translation):
        return {
            issue.check_type
            for issue in check_readability(
                row_id=1,
                original="请输入举报原因",
                translation=translation,
                lang="en",
            )
        }

    def test_flags_opaque_ui_abbreviations(self):
        self.assertIn("opaque_abbreviation", self._types("PERR"))
        self.assertIn("opaque_abbreviation", self._types("DTT"))
        self.assertIn("opaque_abbreviation", self._types("IJA"))

    def test_flags_code_like_abbreviation_with_placeholders(self):
        self.assertIn("opaque_abbreviation", self._types("CL##1##2"))

    def test_flags_clipped_words_from_over_compression(self):
        issues = self._types("Coll imme afte purc")

        self.assertIn("clipped_word", issues)

    def test_flags_title_case_overuse_for_error_or_status_messages(self):
        issues = {
            issue.check_type
            for issue in check_readability(
                row_id=2,
                original="该账号角色过多",
                translation="Too Many Roles",
                lang="en",
            )
        }

        self.assertIn("title_case_overuse", issues)

    def test_title_case_overuse_suggests_sentence_case(self):
        issues = check_readability(
            row_id=3,
            original="系统错误",
            translation="System Error",
            lang="en",
        )

        self.assertEqual(issues[0].auto_fix, "System error")

    def test_flags_login_truncation(self):
        self.assertIn("clipped_word", self._types("Logi time"))

    def test_allows_stable_game_abbreviations_and_plain_ui_copy(self):
        self.assertEqual(self._types("HP"), set())
        self.assertEqual(self._types("ATK"), set())
        self.assertEqual(self._types("PVP"), set())
        self.assertEqual(self._types("More Info"), set())

    def test_allows_reasonable_title_case_labels(self):
        issues = check_readability(
            row_id=4,
            original="战令",
            translation="Battle Pass",
            lang="en",
        )

        self.assertEqual(issues, [])

    def test_allows_reasonable_login_feature_title(self):
        issues = check_readability(
            row_id=5,
            original="七日登录",
            translation="7-Day Login",
            lang="en",
        )

        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
