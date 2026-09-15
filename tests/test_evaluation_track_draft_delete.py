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
        ) as ask, patch(
            "auto_annotation_tool.gui.z4_evaluation_tracks.BatchProgressDialog"
        ) as dialog:
            update = Mock()
            dialog.return_value.run.side_effect = lambda operation: operation(update)
            panel.delete_draft()

        ask.assert_called_once()
        dialog.return_value.run.assert_called_once()
        dialog.return_value.close.assert_called_once()
        panel.service.delete_draft.assert_called_once_with(
            "TRK-TEST", progress=update
        )
        self.assertEqual(panel.current_track_id, "")
        panel.refresh_tracks.assert_called_once_with()
        panel._show_error.assert_not_called()



    def test_delete_preserves_artifacts_referenced_by_other_tracks_or_children(self):
        track_id = self._draft()
        other_id = self._draft("keep")
        for i in range(3):
            image = Path(self.temp.name) / f"image-{i}.jpg"
            image.write_bytes(f"image-{i}".encode())
            self.service.add_member(track_id, image)
        members = self.service.list_members(track_id)
        with self.repo.database.transaction() as db:
            for i in range(2):
                row = members[i]
                db.execute(
                    """INSERT INTO evaluation_track_members(
                           track_id, member_index, source_image_id, source_artifact_id,
                           track_artifact_id, sha256) VALUES (?, ?, ?, ?, ?, ?)""",
                    (other_id, i, row["source_image_id"],
                     row["track_artifact_id"] if i == 0 else row["source_artifact_id"],
                     row["track_artifact_id"] if i == 1 else None, row["sha256"]),
                )
            db.execute(
                """INSERT INTO image_artifacts(artifact_id, source_image_id, sha256,
                       derived_from_artifact_id) VALUES ('child', ?, ?, ?)""",
                (members[2]["source_image_id"], members[2]["sha256"], members[2]["track_artifact_id"]),
            )
        self.service.delete_draft(track_id)
        with self.repo.database.read_connection() as db:
            for row in members:
                self.assertIsNotNone(db.execute(
                    "SELECT 1 FROM image_artifacts WHERE artifact_id = ?",
                    (row["track_artifact_id"],),
                ).fetchone())
            self.assertEqual(len(db.execute("PRAGMA foreign_key_check").fetchall()), 0)
        self.assertEqual(len(self.service.list_members(other_id)), 2)

    def test_dataset_reference_rolls_back_deletion_and_restores_files(self):
        track_id = self._draft()
        image = Path(self.temp.name) / "sample.jpg"
        image.write_bytes(b"image")
        self.service.add_member(track_id, image)
        row = self.service.list_members(track_id)[0]
        track_root = self.workspace / self.service.get_track(track_id)["relative_path"]
        with self.repo.database.transaction() as db:
            db.execute("INSERT INTO datasets(dataset_id) VALUES ('keep')")
            db.execute(
                """INSERT INTO dataset_members(dataset_id, artifact_id, source_image_id, split)
                   VALUES ('keep', ?, ?, 'train')""",
                (row["track_artifact_id"], row["source_image_id"]),
            )
        with self.assertRaises(EvaluationTrackError):
            self.service.delete_draft(track_id)
        self.assertTrue((track_root / row["track_relative_path"]).exists())
        self.assertEqual(len(self.service.list_members(track_id)), 1)
        with self.repo.database.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dataset_members").fetchone()[0], 1)
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_large_draft_deletion_has_bounded_database_work(self):
        # A VM-instruction budget catches repeated full-table scans without a
        # fragile wall-clock limit or dependence on the disk's speed.
        track_ids = (self._draft(), self._draft("keep"))
        count = 600
        with self.repo.database.transaction() as db:
            db.executemany("INSERT INTO source_images(source_image_id) VALUES (?)",
                           ((f"S{i}",) for i in range(count * 2)))
            db.executemany(
                """INSERT INTO image_artifacts(artifact_id, source_image_id, sha256, kind)
                   VALUES (?, ?, ?, 'evaluation_track_image')""",
                ((f"A{i}", f"S{i}", str(i)) for i in range(count * 2)),
            )
            db.executemany(
                """INSERT INTO evaluation_track_members(track_id, member_index,
                       source_image_id, track_artifact_id, sha256) VALUES (?, ?, ?, ?, ?)""",
                ((track_ids[i // count], i % count, f"S{i}", f"A{i}", str(i))
                 for i in range(count * 2)),
            )
            db.execute("INSERT INTO datasets(dataset_id) VALUES ('keep')")
            db.executemany(
                """INSERT INTO dataset_members(dataset_id, artifact_id, source_image_id, split)
                   VALUES ('keep', ?, ?, 'train')""",
                ((f"A{i}", f"S{i}") for i in range(count, count * 2)),
            )
        calls = 0
        def budget():
            nonlocal calls
            calls += 1
            return int(calls > 500)  # At most 500,000 SQLite VM instructions.
        connect = self.repo.database.connect
        def counted_connection():
            db = connect()
            db.set_progress_handler(budget, 1000)
            return db
        with patch.object(self.repo.database, "connect", side_effect=counted_connection):
            removed = self.repo.delete_draft_evaluation_track(track_ids[0])
        self.assertEqual(len(removed), count)
        self.assertEqual(len(self.service.list_members(track_ids[1])), count)
        with self.repo.database.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_images").fetchone()[0], count * 2)
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_progress_reports_success_only_after_file_cleanup(self):
        track_id = self._draft()
        progress = Mock()
        with patch("auto_annotation_tool.registry.track_service.shutil.rmtree",
                   side_effect=PermissionError("file locked")):
            with self.assertRaises(EvaluationTrackError):
                self.service.delete_draft(track_id, progress=progress)
        self.assertIsNone(self.repo.get_evaluation_track(track_id))
        self.assertTrue(progress.called)
        self.assertNotEqual(progress.call_args.args[0], "DRAFT usunięty")

    def test_gui_deletion_runs_off_tk_thread_and_keeps_event_loop_alive(self):
        import threading
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        panel = object.__new__(EvaluationTracksPanel)
        panel.parent = root
        panel.current_track_id = "TRK"
        panel.service = Mock()
        panel.service.get_track.return_value = {"name": "draft", "status": STATUS_DRAFT}
        panel._require_current_track = Mock(return_value="TRK")
        panel.refresh_tracks = Mock()
        panel._set_status = Mock()
        panel._show_error = Mock()
        started = threading.Event()
        responsive = threading.Event()
        main_thread = threading.get_ident()
        def delete(track_id, *, progress):
            self.assertNotEqual(threading.get_ident(), main_thread)
            progress("Usuwanie wpisów", 0, 0)
            started.set()
            self.assertTrue(responsive.wait(2), "Tk event loop was blocked by deletion")
            progress("DRAFT usunięty", 1, 1)
        panel.service.delete_draft.side_effect = delete
        def tick():
            if started.is_set():
                responsive.set()
            else:
                root.after(10, tick)
        root.after(10, tick)
        try:
            with patch("auto_annotation_tool.gui.z4_evaluation_tracks.messagebox.askyesno",
                       return_value=True):
                panel.delete_draft()
            self.assertTrue(responsive.is_set())
            panel._show_error.assert_not_called()
            panel.refresh_tracks.assert_called_once_with()
            self.assertEqual(panel.current_track_id, "")
        finally:
            root.destroy()

    def test_gui_cleanup_error_refreshes_the_registry_and_closes_progress(self):
        panel = object.__new__(EvaluationTracksPanel)
        panel.parent = object()
        panel.current_track_id = "TRK"
        panel.service = Mock()
        panel.service.get_track.return_value = {"name": "draft", "status": STATUS_DRAFT}
        panel.service.delete_draft.side_effect = EvaluationTrackError("cleanup failed")
        panel._require_current_track = Mock(return_value="TRK")
        panel.refresh_tracks = Mock()
        panel._set_status = Mock()
        panel._show_error = Mock()
        with patch("auto_annotation_tool.gui.z4_evaluation_tracks.messagebox.askyesno", return_value=True), \
             patch("auto_annotation_tool.gui.z4_evaluation_tracks.BatchProgressDialog") as dialog:
            dialog.return_value.run.side_effect = lambda operation: operation(Mock())
            panel.delete_draft()
        dialog.return_value.close.assert_called_once()
        panel.refresh_tracks.assert_called_once_with(select_track_id="TRK")
        panel._show_error.assert_called_once()
        panel._set_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
