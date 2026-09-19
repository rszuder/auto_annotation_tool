import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from auto_annotation_tool.gui.pz3_participant_audit import (
    participant_architecture_context_label,
    participant_target_context,
)
from auto_annotation_tool.gui import z4_evaluation_tracks as tracks


class ParticipantModelContextTests(unittest.TestCase):
    def test_char_architecture_row_contains_char_detect(self):
        item = SimpleNamespace(
            family="YOLO26",
            scale="n",
            target="char",
            task_type="detect",
        )
        self.assertEqual(
            participant_architecture_context_label(item),
            "YOLO26 · n · char/detect",
        )

    def test_plate_architecture_row_contains_plate_pose(self):
        item = SimpleNamespace(
            family="YOLO26",
            scale="s",
            target="plate",
            task_type="pose",
        )
        self.assertEqual(
            participant_architecture_context_label(item),
            "YOLO26 · s · plate/pose",
        )

    def test_char_column_header_is_explicit(self):
        context = participant_target_context("char")
        self.assertEqual(
            context["architecture_column"],
            "Architektura · char/detect",
        )

    def test_char_picker_prefers_char_trained_models_directory(self):
        char_dir = Path("C:/Workspace/6_models/trained/chars")
        with patch.object(
            tracks.CONFIG,
            "normalize_task_target",
            return_value="char",
        ), patch.object(
            tracks.CONFIG,
            "get_trained_models_dir",
            return_value=char_dir,
        ), patch.object(
            Path,
            "is_dir",
            return_value=True,
        ):
            result = tracks.participant_model_picker_initial_dir("char")
        self.assertEqual(result, char_dir)


if __name__ == "__main__":
    unittest.main()
