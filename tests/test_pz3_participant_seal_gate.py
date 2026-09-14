import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from auto_annotation_tool.gui.z4_evaluation_tracks import EvaluationTracksPanel


class ParticipantSealGateTests(unittest.TestCase):
    def make_panel(self):
        return object.__new__(EvaluationTracksPanel)

    def test_validation_never_requires_participant_audit(self):
        panel = self.make_panel()
        issue = panel._participant_audit_seal_issue(
            "TRK-1",
            {"purpose": "validation"},
        )
        self.assertEqual(issue, "")

    def test_lightweight_legacy_gui_fixture_can_test_other_seal_logic(self):
        panel = self.make_panel()
        issue = panel._participant_audit_seal_issue(
            "TRK-1",
            {"purpose": "ranking"},
        )
        self.assertEqual(issue, "")

    def test_real_panel_without_service_is_blocked(self):
        panel = self.make_panel()
        panel.workspace = object()
        panel.repository = object()
        issue = panel._participant_audit_seal_issue(
            "TRK-1",
            {"purpose": "ranking"},
        )
        self.assertIn("Nie zainicjalizowano", issue)

    def test_ranking_calls_participant_audit_gate(self):
        panel = self.make_panel()
        panel.participant_audit = SimpleNamespace(
            assert_track_audit_ready=Mock()
        )
        panel.participant_audit.assert_track_audit_ready.return_value = None
        issue = panel._participant_audit_seal_issue(
            "TRK-1",
            {"purpose": "ranking"},
        )
        self.assertEqual(issue, "")
        panel.participant_audit.assert_track_audit_ready.assert_called_once_with(
            "TRK-1"
        )

    def test_gate_error_is_returned_as_user_message(self):
        panel = self.make_panel()
        panel.participant_audit = SimpleNamespace(
            assert_track_audit_ready=Mock()
        )
        panel.participant_audit.assert_track_audit_ready.side_effect = RuntimeError(
            "audyt STALE"
        )
        issue = panel._participant_audit_seal_issue(
            "TRK-1",
            {"purpose": "final_test"},
        )
        self.assertEqual(issue, "audyt STALE")


if __name__ == "__main__":
    unittest.main()
