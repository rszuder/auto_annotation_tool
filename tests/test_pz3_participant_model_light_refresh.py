import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from auto_annotation_tool.gui.z4_evaluation_tracks import (
    EvaluationTracksPanel,
)


class ParticipantModelLightRefreshTests(unittest.TestCase):
    def test_refresh_uses_light_catalog_without_bootstrap(self):
        panel = object.__new__(EvaluationTracksPanel)
        models = [
            SimpleNamespace(model_id="MODEL-A"),
            SimpleNamespace(model_id="MODEL-B"),
        ]
        panel.participant_audit = SimpleNamespace(
            list_participant_catalog=Mock(return_value=models)
        )

        result, message = panel._refresh_participant_model_registry("plate")

        self.assertEqual(result, models)
        panel.participant_audit.list_participant_catalog.assert_called_once_with(
            "plate"
        )
        self.assertIn("2", message)
        self.assertIn("rejestru", message.lower())


if __name__ == "__main__":
    unittest.main()
