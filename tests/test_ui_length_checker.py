import unittest

from utils.ui_length_checker import check_ui_length, compute_ui_length_budget, is_short_ui_candidate


class UILengthCheckerTests(unittest.TestCase):
    def test_short_ui_candidate_requires_ui_and_short_source(self):
        self.assertTrue(is_short_ui_candidate("消息推送", "Push Notifications", True))
        self.assertFalse(is_short_ui_candidate("这是一整句说明文本", "This is a full sentence of explanation.", True))
        self.assertFalse(is_short_ui_candidate("消息推送", "Push Notifications", False))

    def test_budget_for_english_short_ui_is_tighter_than_freeform_sentence(self):
        self.assertEqual(compute_ui_length_budget(4, lang="en"), 12)
        self.assertEqual(compute_ui_length_budget(4, lang="idn"), 13)

    def test_flags_over_budget_english_ui_text(self):
        results = check_ui_length(
            row_id=1,
            original="消息推送",
            translation="Push Notifications",
            is_ui=True,
            lang="en",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].check_type, "ui_length_overflow")
        self.assertEqual(results[0].source_length, 4)
        self.assertEqual(results[0].target_length, 17)
        self.assertEqual(results[0].budget, 12)

    def test_accepts_compact_ui_translation_within_budget(self):
        results = check_ui_length(
            row_id=2,
            original="消息推送",
            translation="Push Alerts",
            is_ui=True,
            lang="en",
        )

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
