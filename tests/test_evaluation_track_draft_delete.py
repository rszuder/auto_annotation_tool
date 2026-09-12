import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from auto_annotation_tool.gui.z4_evaluation_tracks import (
    EvaluationTracksPanel,
    action_state_for_status,
)
from auto_annotation_tool.registry import (
    EvaluationTrackError,
    EvaluationTrackService,
)
from auto_annotation_tool.registry.track_service import (
    STATUS_DRAFT,
    STATUS_SEALED,
    STATUS_VERIFIED,
)


class EvaluationTrackDraftDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.service = EvaluationTrackService(self.workspace)
        self.repo = self.service.repository

    def tearDown(self):
        self.temp.cleanup()

    def _draft(self, name="delete-me"):
        return self.service.create_draft(
            name=name,
            target="plate",
            purpose="ranking",
            scope="global",
            reservation_policy="reserve_from_training",
        )

    def test_action_state_allows_delete_only_for_draft(self):
        self.assertTrue(
            action_state_for_status(
                STATUS_DRAFT
            ).can_delete_draft
        )
        self.assertFalse(
            action_state_for_status(
                STATUS_VERIFIED
            ).can_delete_draft
        )
        self.assertFalse(
            action_state_for_status(
                STATUS_SEALED
            ).can_delete_draft
        )

    def test_delete_empty_draft_removes_row_and_directory(self):
        track_id = self._draft()
        track = self.service.get_track(track_id)
        track_root = (
            self.workspace
            / str(track["relative_path"])
        )
        self.assertTrue(track_root.is_dir())

        self.service.delete_draft(track_id)

        self.assertIsNone(
            self.repo.get_evaluation_track(track_id)
        )
        self.assertFalse(track_root.exists())

    def test_delete_draft_removes_track_artifact_but_preserves_source_identity(self):
        track_id = self._draft()
        image = Path(self.temp.name) / "sample.jpg"
        image.write_bytes(b"independent-test-image")
        self.service.add_member(track_id, image)

        member = self.service.list_members(track_id)[0]
        source_id = str(member["source_image_id"])
        track_artifact_id = str(
            member["track_artifact_id"]
        )

        self.service.delete_draft(track_id)

        with self.repo.database.read_connection() as connection:
            source = connection.execute(
                """
                SELECT source_image_id
                FROM source_images
                WHERE source_image_id = ?
                """,
                (source_id,),
            ).fetchone()
            artifact = connection.execute(
                """
                SELECT artifact_id
                FROM image_artifacts
                WHERE artifact_id = ?
                """,
                (track_artifact_id,),
            ).fetchone()
            member_row = connection.execute(
                """
                SELECT 1
                FROM evaluation_track_members
                WHERE track_id = ?
                """,
                (track_id,),
            ).fetchone()

        self.assertIsNotNone(source)
        self.assertIsNone(artifact)
        self.assertIsNone(member_row)

    def test_non_draft_cannot_be_deleted(self):
        track_id = self._draft()
        track = self.service.get_track(track_id)
        track_root = (
            self.workspace
            / str(track["relative_path"])
        )
        self.repo.update_evaluation_track(
            track_id,
            status=STATUS_VERIFIED,
        )

        with self.assertRaises(EvaluationTrackError):
            self.service.delete_draft(track_id)

        self.assertIsNotNone(
            self.repo.get_evaluation_track(track_id)
        )
        self.assertTrue(track_root.exists())

    def test_repository_failure_restores_draft_directory(self):
        track_id = self._draft()
        track = self.service.get_track(track_id)
        track_root = (
            self.workspace
            / str(track["relative_path"])
        )

        with patch.object(
            self.repo,
            "delete_draft_evaluation_track",
            side_effect=RuntimeError("db failed"),
        ):
            with self.assertRaises(EvaluationTrackError):
                self.service.delete_draft(track_id)

        self.assertTrue(track_root.is_dir())
        self.assertIsNotNone(
            self.repo.get_evaluation_track(track_id)
        )

    def test_gui_delete_draft_confirms_and_refreshes(self):
        panel = object.__new__(EvaluationTracksPanel)
        panel.parent = object()
        panel.current_track_id = "TRK-TEST"
        panel.service = Mock()
        panel.service.get_track.return_value = {
            "track_id": "TRK-TEST",
            "name": "E1A_MT_n_vs_s",
            "status": STATUS_DRAFT,
        }
        panel._require_current_track = Mock(
            return_value="TRK-TEST"
        )
        panel.refresh_tracks = Mock()
        panel._set_status = Mock()
        panel._show_error = Mock()

        with patch(
            "auto_annotation_tool.gui.z4_evaluation_tracks."
            "messagebox.askyesno",
            return_value=True,
        ) as ask:
            panel.delete_draft()

        ask.assert_called_once()
        panel.service.delete_draft.assert_called_once_with(
            "TRK-TEST"
        )
        self.assertEqual(panel.current_track_id, "")
        panel.refresh_tracks.assert_called_once_with()
        panel._show_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
