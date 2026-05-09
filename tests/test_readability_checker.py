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

    def test_allows_stable_game_abbreviations_and_plain_ui_copy(self):
        self.assertEqual(self._types("HP"), set())
        self.assertEqual(self._types("ATK"), set())
        self.assertEqual(self._types("PVP"), set())
        self.assertEqual(self._types("More Info"), set())


if __name__ == "__main__":
    unittest.main()
