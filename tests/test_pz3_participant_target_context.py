import unittest

from auto_annotation_tool.gui.pz3_participant_audit import (
    participant_target_context,
)


class ParticipantTargetContextTests(unittest.TestCase):
    def test_char_context_is_explicitly_mz_and_character(self):
        context = participant_target_context("char")
        self.assertIn("MZ", context["window_title"])
        self.assertIn("znak", context["window_title"].lower())
        self.assertIn("MZ", context["header"])
        self.assertIn("char", context["header"])
        self.assertIn("Detect", context["header"])
        self.assertIn("znak", context["description"].lower())
        self.assertEqual(context["model_column"], "Model znakowy")
        self.assertEqual(context["selection_label"], "Wybrane modele MZ")

    def test_plate_context_remains_explicitly_mt(self):
        context = participant_target_context("plate")
        self.assertIn("MT", context["window_title"])
        self.assertIn("plate", context["header"])
        self.assertIn("Pose", context["header"])

    def test_unknown_context_keeps_generic_fallback(self):
        context = participant_target_context("other")
        self.assertEqual(context["model_column"], "Model")
        self.assertEqual(context["selection_label"], "Wybrane modele")


if __name__ == "__main__":
    unittest.main()
