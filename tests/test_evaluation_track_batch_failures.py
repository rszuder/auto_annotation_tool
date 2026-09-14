import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_annotation_tool.registry.track_service import EvaluationTrackError, EvaluationTrackService


class TrackBatchFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = EvaluationTrackService(self.root / "Workspace")
        self.track = self.service.create_draft(name="batch", target="plate", purpose="validation")
        self.image = self.root / "IMG_001.png"
        self.image.write_bytes(b"source image")
        self.track_root = self.service.workspace / self.service.get_track(self.track)["relative_path"]

    def test_manifest_failure_does_not_delete_committed_images(self):
        with patch.object(self.service, "_write_manifest", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.service.add_members_batch(self.track, [self.image])
        self.assertEqual(len(self.service.list_members(self.track)), 1)
        self.assertEqual((self.track_root / "images" / self.image.name).read_bytes(), self.image.read_bytes())

    def test_failed_database_write_rolls_back_copied_files(self):
        with patch.object(self.service.repository, "add_evaluation_track_members_batch", side_effect=OSError("db failure")):
            with self.assertRaises(OSError):
                self.service.add_members_batch(self.track, [self.image])
        self.assertEqual(self.service.list_members(self.track), [])
        self.assertFalse((self.track_root / "images" / self.image.name).exists())
        self.assertTrue(self.image.exists())

    def test_changed_source_since_audit_cannot_commit_wrong_hash(self):
        import hashlib
        old_sha = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.image.write_bytes(b"changed data")
        with self.assertRaises(EvaluationTrackError):
            self.service.add_members_batch(
                self.track, [self.image], sha256_by_path={str(self.image): old_sha}
            )
        self.assertEqual(self.service.list_members(self.track), [])
        self.assertFalse((self.track_root / "images" / self.image.name).exists())

    def test_case_insensitive_collision_does_not_overwrite(self):
        self.service.add_members_batch(self.track, [self.image])
        second_dir = self.root / "other"
        second_dir.mkdir()
        second = second_dir / "img_001.PNG"
        second.write_bytes(b"different image")
        with self.assertRaises(EvaluationTrackError):
            self.service.add_members_batch(self.track, [second])
        self.assertEqual((self.track_root / "images" / self.image.name).read_bytes(), self.image.read_bytes())


if __name__ == "__main__":
    unittest.main()

