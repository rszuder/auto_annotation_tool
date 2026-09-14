import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from auto_annotation_tool.gui.z4_evaluation_tracks import (
    EvaluationTracksPanel,
    STATUS_DRAFT,
)


class ParticipantEntryGateTests(unittest.TestCase):
    def _panel(self, participants=()):
        panel = object.__new__(EvaluationTracksPanel)
        panel.current_track_id = "TRK-1"
        panel.participant_audit = SimpleNamespace(
            load_participants=Mock(return_value=tuple(participants))
        )
        return panel

    def test_ranking_without_participants_is_not_ready(self):
        panel = self._panel(())
        self.assertFalse(
            panel._participant_entry_ready(
                {
                    "track_id": "TRK-1",
                    "status": STATUS_DRAFT,
                    "purpose": "ranking",
                }
            )
        )

    def test_final_test_with_participant_is_ready(self):
        panel = self._panel((object(),))
        self.assertTrue(
            panel._participant_entry_ready(
                {
                    "track_id": "TRK-1",
                    "status": STATUS_DRAFT,
                    "purpose": "final_test",
                }
            )
        )

    def test_validation_does_not_require_participants(self):
        panel = self._panel(())
        self.assertTrue(
            panel._participant_entry_ready(
                {
                    "track_id": "TRK-1",
                    "status": STATUS_DRAFT,
                    "purpose": "validation",
                }
            )
        )

    def test_status_hint_explains_required_order(self):
        panel = self._panel(())
        text = panel._status_hint_for_track(
            {
                "track_id": "TRK-1",
                "status": STATUS_DRAFT,
                "purpose": "ranking",
            },
            "UNKNOWN",
        ).lower()
        self.assertIn("najpierw", text)
        self.assertIn("modele uczestniczące", text)
        self.assertIn("obrazy", text)


if __name__ == "__main__":
    unittest.main()
