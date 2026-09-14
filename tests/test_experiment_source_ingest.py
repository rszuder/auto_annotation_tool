import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from auto_annotation_tool.gui import z2_session_runtime
from auto_annotation_tool.gui.z4_evaluation_tracks import (
    can_prepare_ground_truth,
)
from auto_annotation_tool.registry.experiment_workspace import (
    activate_z2_experiment_context,
)
from auto_annotation_tool.registry.track_service import (
    EvaluationTrackError,
    EvaluationTrackService,
    STATUS_DRAFT,
)


class ExperimentSourceIngestTests(unittest.TestCase):
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

    def test_ingest_copies_source_and_adds_track_member(self):
        track_id = self._draft()
        original = Path(self.temp.name) / "img001.jpg"
        original.write_bytes(b"independent-image-001")

        member_index = self.service.ingest_member_source(
            track_id,
            original,
        )

        self.assertEqual(member_index, 0)
        paths = self.service.get_experiment_workspace(
            track_id,
            create=False,
        )
        staged = Path(paths["source_images"]) / "img001.jpg"
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), original.read_bytes())

        members = self.service.list_members(track_id)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["original_name"], "img001.jpg")

    def test_ingest_does_not_overwrite_same_name_with_other_content(self):
        track_id = self._draft()
        first = Path(self.temp.name) / "a" / "same.jpg"
        second = Path(self.temp.name) / "b" / "same.jpg"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_bytes(b"first")
        second.write_bytes(b"second")

        self.service.ingest_member_source(track_id, first)
        with self.assertRaises(EvaluationTrackError):
            self.service.ingest_member_source(track_id, second)

        paths = self.service.get_experiment_workspace(
            track_id,
            create=False,
        )
        staged = Path(paths["source_images"]) / "same.jpg"
        self.assertEqual(staged.read_bytes(), b"first")
        self.assertEqual(len(self.service.list_members(track_id)), 1)

    def test_activation_requires_at_least_one_track_member(self):
        track_id = self._draft()
        with self.assertRaises(EvaluationTrackError):
            self.service.activate_z2_context(track_id)

    def test_activation_backfills_source_staging_for_legacy_draft_member(self):
        track_id = self._draft()
        original = Path(self.temp.name) / "legacy.jpg"
        original.write_bytes(b"legacy-member")
        self.service.add_member(track_id, original)

        paths = self.service.get_experiment_workspace(
            track_id,
            create=False,
        )
        staged = Path(paths["source_images"]) / "legacy.jpg"
        self.assertFalse(staged.exists())

        context = self.service.activate_z2_context(track_id)

        self.assertEqual(context["track_id"], track_id)
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), b"legacy-member")

    def test_prepare_gt_is_enabled_only_after_plate_draft_has_members(self):
        track = {
            "status": STATUS_DRAFT,
            "target": "plate",
            "member_count": 0,
        }
        self.assertFalse(
            can_prepare_ground_truth(track, member_count=0)
        )
        self.assertTrue(
            can_prepare_ground_truth(track, member_count=1)
        )
        self.assertFalse(
            can_prepare_ground_truth(
                {**track, "target": "char"},
                member_count=1,
            )
        )

    def test_experiment_session_defaults_keep_full_z2_contract(self):
        track = {
            "track_id": "TRK-TEST",
            "name": "E1A_MT_n_vs_s",
            "target": "plate",
            "purpose": "ranking",
            "relative_path": (
                "10_experiments/tracks/plate/e1a__v001__TEST"
            ),
        }
        context = activate_z2_experiment_context(
            self.workspace,
            track,
        )

        old_workspace = z2_session_runtime.CONFIG.WORKSPACE_DIR
        try:
            z2_session_runtime.CONFIG.WORKSPACE_DIR = self.workspace
            with patch(
                "auto_annotation_tool.campaign_manager."
                "CAMPAIGN.get_active_project_name",
                return_value="",
            ):
                defaults = z2_session_runtime._annotation_session_defaults(
                    SimpleNamespace()
                )
        finally:
            z2_session_runtime.CONFIG.WORKSPACE_DIR = old_workspace

        self.assertEqual(defaults["input_dir"], context["source_dir"])
        self.assertEqual(defaults["output_dir"], context["annotation_dir"])
        for key in (
            "vehicle_custom",
            "plate_custom",
            "conf",
            "workflow_route",
            "manual_entry_mode",
            "free_mode_screen",
            "manual_review_history",
            "plate_model_identity",
        ):
            self.assertIn(key, defaults)


if __name__ == "__main__":
    unittest.main()
