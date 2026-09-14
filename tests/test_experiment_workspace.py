import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auto_annotation_tool.config import Config
from auto_annotation_tool.gui import z2_export_workflow
from auto_annotation_tool.registry.experiment_workspace import (
    load_active_z2_experiment_context,
)
from auto_annotation_tool.registry.track_service import EvaluationTrackService


class _Var:
    def __init__(self, value=""):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class ExperimentWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.service = EvaluationTrackService(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def _draft(self):
        return self.service.create_draft(
            name="E1A_MT_n_vs_s",
            target="plate",
            purpose="ranking",
            scope="global",
            reservation_policy="reserve_from_training",
        )

    def test_config_uses_experiment_tree_for_tracks(self):
        config = Config()
        self.assertEqual(config.DIR_10_EXPERIMENTS.name, "10_experiments")
        self.assertEqual(
            config.DIR_10_EVALUATION_TRACKS,
            config.DIR_10_EXPERIMENT_TRACKS,
        )

    def test_new_draft_creates_experiment_staging(self):
        track_id = self._draft()
        track = self.service.get_track(track_id)
        self.assertIn(
            "10_experiments/tracks/",
            str(track["relative_path"]).replace("\\", "/"),
        )
        paths = self.service.get_experiment_workspace(track_id)
        for key in (
            "source_images",
            "annotation_runs",
            "experiment_runs",
            "experiment_results",
        ):
            self.assertTrue(Path(paths[key]).is_dir(), key)

    def test_legacy_track_root_is_still_accepted(self):
        legacy = (
            self.workspace
            / "10_evaluation_tracks"
            / "plate"
            / "legacy__v001__ABC"
        )
        legacy.mkdir(parents=True)
        track = {
            "relative_path": (
                "10_evaluation_tracks/plate/legacy__v001__ABC"
            )
        }
        self.assertEqual(self.service._track_root(track), legacy)

    def test_activation_marks_context_as_non_training(self):
        track_id = self._draft()

        image = Path(self.temp.name) / "activation.jpg"
        image.write_bytes(b"independent-activation-image")
        self.service.ingest_member_source(
            track_id,
            image,
        )

        context = self.service.activate_z2_context(
            track_id
        )

        self.assertEqual(
            context["track_id"],
            track_id,
        )
        self.assertFalse(
            context["training_dataset_export_allowed"]
        )
        self.assertTrue(
            Path(context["source_dir"]).is_dir()
        )
        self.assertTrue(
            Path(context["annotation_dir"]).is_dir()
        )

    def test_delete_draft_removes_staging_and_context(self):
        track_id = self._draft()

        image = Path(self.temp.name) / "delete.jpg"
        image.write_bytes(b"independent-delete-image")
        self.service.ingest_member_source(
            track_id,
            image,
        )

        paths = self.service.get_experiment_workspace(
            track_id
        )
        self.service.activate_z2_context(track_id)

        self.service.delete_draft(track_id)

        for key in (
            "source_images",
            "annotation_runs",
            "experiment_runs",
            "experiment_results",
        ):
            self.assertFalse(Path(paths[key]).exists())

        self.assertEqual(
            load_active_z2_experiment_context(
                self.workspace
            ),
            {},
        )

    def test_z2_training_export_is_hard_blocked_for_experiment_run(self):
        run_dir = (
            self.workspace
            / "10_experiments"
            / "annotations"
            / "plate"
            / "e1"
            / "run"
        )
        images_dir = run_dir / "images"
        images_dir.mkdir(parents=True)
        (run_dir / "annotations.xml").write_text(
            "<annotations/>",
            encoding="utf-8",
        )

        fake = SimpleNamespace(
            plate_dataset_run_var=_Var(str(run_dir)),
            plate_dataset_images_var=_Var(str(images_dir)),
        )
        fake._ensure_preview_edits_saved = Mock(return_value=True)
        fake._is_free_mode_session_context = Mock(return_value=True)
        fake._resolve_safe_annotation_run_dir = Mock(return_value=run_dir)
        fake._load_annotation_run_manifest = Mock(
            return_value={
                "experiment_bound": True,
                "evaluation_track_id": "TRK-E1A",
                "training_dataset_export_allowed": False,
            }
        )
        fake._get_run_plate_strict_approved_state = Mock(
            side_effect=AssertionError(
                "guard powinien zatrzymać eksport wcześniej"
            )
        )

        with patch.object(
            z2_export_workflow.messagebox,
            "showerror",
        ) as showerror:
            z2_export_workflow._start_plate_dataset_export(fake)

        showerror.assert_called_once()
        self.assertIn(
            "zablokowany",
            str(showerror.call_args).lower(),
        )
        fake._get_run_plate_strict_approved_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
