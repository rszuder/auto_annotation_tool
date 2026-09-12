import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.track_service import (
    EvaluationTrackError,
    EvaluationTrackService,
)


class PoseCornerTrackContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.service = EvaluationTrackService(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def _make_track(self, shape: str):
        image = Path(self.temp.name) / "one.jpg"
        image.write_bytes(b"image")
        gt = Path(self.temp.name) / "gt.xml"
        gt.write_text(
            (
                "<annotations>"
                '<image id="0" name="one.jpg" width="100" height="50">'
                + shape
                + "</image></annotations>"
            ),
            encoding="utf-8",
        )
        track_id = self.service.create_draft(
            name="E1A MT",
            target="plate",
            purpose="final_test",
            reservation_policy="reserve_from_training",
        )
        self.service.add_member(track_id, image)
        self.service.set_ground_truth(track_id, gt)
        return track_id

    def test_canonical_quad_records_fixed_corner_order(self):
        track_id = self._make_track(
            '<polygon label="plate" '
            'points="0,0;10,0;10,10;0,10"/>'
        )
        verification = self.service.verify(track_id)
        self.assertTrue(verification["pose_corner_ready"])
        self.assertEqual(
            verification["pose_corner_order"],
            "tl_tr_br_bl",
        )
        self.service.seal(track_id)
        ref = self.service.build_controlled_reference(
            track_id,
            required_target="plate",
            require_pose_corners=True,
        )
        self.assertTrue(ref.pose_corner_ready)
        self.assertEqual(ref.pose_corner_order, "tl_tr_br_bl")

    def test_cyclic_order_is_not_pose_corner_ready(self):
        track_id = self._make_track(
            '<polygon label="plate" '
            'points="10,0;10,10;0,10;0,0"/>'
        )
        verification = self.service.verify(track_id)
        self.assertFalse(verification["pose_corner_ready"])
        self.assertEqual(
            verification["unordered_quad_polygon_count"],
            1,
        )
        self.service.seal(track_id)
        with self.assertRaises(EvaluationTrackError):
            self.service.build_controlled_reference(
                track_id,
                required_target="plate",
                require_pose_corners=True,
            )

    def test_box_only_gt_can_be_legacy_but_not_corner_controlled(self):
        track_id = self._make_track(
            '<box label="plate" '
            'xtl="0" ytl="0" xbr="10" ybr="10"/>'
        )
        verification = self.service.verify(track_id)
        self.assertFalse(verification["pose_corner_ready"])
        self.service.seal(track_id)
        with self.assertRaises(EvaluationTrackError):
            self.service.build_controlled_reference(
                track_id,
                required_target="plate",
                require_pose_corners=True,
            )

    def test_nonfinite_quad_is_rejected_during_verify(self):
        track_id = self._make_track(
            '<polygon label="plate" '
            'points="0,0;10,0;10,nan;0,10"/>'
        )
        with self.assertRaises(EvaluationTrackError):
            self.service.verify(track_id)


if __name__ == "__main__":
    unittest.main()
