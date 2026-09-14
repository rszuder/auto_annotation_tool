import unittest

from auto_annotation_tool.gui.pz3_participant_audit import (
    training_history_label,
)


class Pz3TrainingHistoryLabelTests(unittest.TestCase):
    def test_complete_is_user_friendly(self):
        self.assertEqual(training_history_label("complete"), "Pełna")

    def test_known_is_explicitly_manual(self):
        self.assertEqual(
            training_history_label("known"),
            "Potwierdzona ręcznie",
        )

    def test_partial_is_user_friendly(self):
        self.assertEqual(training_history_label("partial"), "Częściowa")

    def test_legacy_unknown_is_not_shown_as_internal_token(self):
        self.assertEqual(
            training_history_label("legacy_unknown"),
            "Nieustalona",
        )

    def test_empty_is_not_shown_as_dash(self):
        self.assertEqual(training_history_label(""), "Nieustalona")


if __name__ == "__main__":
    unittest.main()
