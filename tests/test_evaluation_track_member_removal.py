import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.gui.z4_evaluation_tracks import action_state_for_status
from auto_annotation_tool.registry.track_service import (
    EvaluationTrackError,
    EvaluationTrackService,
    STATUS_DRAFT,
    STATUS_VERIFIED,
)


class EvaluationTrackMemberRemovalTests(unittest.TestCase):
    def test_action_is_only_available_for_draft(self):
        self.assertTrue(action_state_for_status(STATUS_DRAFT).can_remove_images)
        self.assertFalse(action_state_for_status(STATUS_VERIFIED).can_remove_images)

    def test_remove_member_updates_registry_and_internal_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            service = EvaluationTrackService(workspace)
            track_id = service.create_draft(
                name="remove-test",
                target="plate",
                purpose="ranking",
            )
            source = workspace / "AS93_001.jpg"
            source.write_bytes(b"image-a")
            index = service.add_member(track_id, source)

            track = service.get_track(track_id)
            copied = service._track_root(track) / "images" / source.name
            self.assertTrue(copied.exists())

            summary = service.remove_members(track_id, [index])

            self.assertEqual(summary["removed_count"], 1)
            self.assertEqual(service.list_members(track_id), [])
            self.assertFalse(copied.exists())
            self.assertTrue(source.exists())

    def test_remove_member_invalidates_draft_gt(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            service = EvaluationTrackService(workspace)
            track_id = service.create_draft(
                name="remove-gt-test",
                target="plate",
                purpose="validation",  # Artifact invalidation; final sample gates have separate coverage.
            )
            source = workspace / "IMG_004.jpg"
            source.write_bytes(b"image-b")
            index = service.add_member(track_id, source)

            gt = workspace / "gt.xml"
            gt.write_text("<annotations/>", encoding="utf-8")
            service.set_ground_truth(track_id, gt, gt_format="cvat_xml")

            summary = service.remove_members(track_id, [index])
            track = service.get_track(track_id)

            self.assertTrue(summary["ground_truth_invalidated"])
            self.assertFalse(str(track.get("gt_relative_path") or ""))
            self.assertFalse(str(track.get("gt_sha256") or ""))
            self.assertEqual(int(track.get("object_count") or 0), 0)

    def test_non_draft_removal_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            service = EvaluationTrackService(workspace)
            track_id = service.create_draft(
                name="remove-block-test",
                target="plate",
                purpose="ranking",
            )
            source = workspace / "ABC_001.jpg"
            source.write_bytes(b"image-c")
            index = service.add_member(track_id, source)

            service.repository.update_evaluation_track(
                track_id,
                status=STATUS_VERIFIED,
            )

            with self.assertRaises(EvaluationTrackError):
                service.remove_members(track_id, [index])


if __name__ == "__main__":
    unittest.main()
