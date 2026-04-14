import unittest

from process_language import RowState, _run_ui_length_checks


class ProcessLanguageUILengthTests(unittest.TestCase):
    def test_run_ui_length_checks_marks_over_budget_ui_rows_for_review(self):
        state = RowState(1, "消息推送", "Push Notifications")
        state.is_ui = True
        states = {1: state}

        _run_ui_length_checks(states, lang="en")

        self.assertTrue(state.needs_human_review)
        self.assertEqual(state.issues[0].check_type, "ui_length_overflow")
        self.assertEqual(state.review_confidence, 0.9)

    def test_run_ui_length_checks_ignores_non_ui_rows(self):
        state = RowState(2, "消息推送", "Push Notifications")
        state.is_ui = False
        states = {2: state}

        _run_ui_length_checks(states, lang="en")

        self.assertEqual(state.issues, [])
        self.assertFalse(state.needs_human_review)


if __name__ == "__main__":
    unittest.main()
