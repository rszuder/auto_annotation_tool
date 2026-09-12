import math
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.ranking.corner_metrics import (
    evaluate_pose_corner_metrics,
)


def _xml(path: Path, images):
    parts = ["<annotations>"]
    for image_id, (name, polygons) in enumerate(images):
        parts.append(
            f'<image id="{image_id}" name="{name}" width="300" height="200">'
        )
        for points, attrs in polygons:
            parts.append(
                f'<polygon label="plate" points="{points}">'
            )
            for key, value in dict(attrs or {}).items():
                parts.append(
                    f'<attribute name="{key}">{value}</attribute>'
                )
            parts.append("</polygon>")
        parts.append("</image>")
    parts.append("</annotations>")
    path.write_text("".join(parts), encoding="utf-8")


class MtCornerMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _evaluate(self, pred_images, gt_images, **kwargs):
        pred = self.root / "pred.xml"
        gt = self.root / "gt.xml"
        _xml(pred, pred_images)
        _xml(gt, gt_images)
        return evaluate_pose_corner_metrics(
            pred,
            gt,
            **kwargs,
        )

    def test_perfect_corners_are_zero(self):
        points = "0,0;10,0;10,10;0,10"
        stats = self._evaluate(
            [("one.jpg", [(points, {})])],
            [("one.jpg", [(points, {})])],
        )
        self.assertEqual(stats["corner_metric_status"], "OK")
        self.assertEqual(stats["corner_error_count"], 1)
        self.assertAlmostEqual(stats["corner_error_mean"], 0.0)
        self.assertAlmostEqual(stats["corner_error_p95"], 0.0)
        self.assertAlmostEqual(stats["corner_error_max"], 0.0)

    def test_uniform_shift_uses_gt_bbox_diagonal(self):
        gt = "0,0;10,0;10,10;0,10"
        pred = "1,0;11,0;11,10;1,10"
        stats = self._evaluate(
            [("one.jpg", [(pred, {})])],
            [("one.jpg", [(gt, {})])],
        )
        expected = 1.0 / math.hypot(10.0, 10.0)
        self.assertAlmostEqual(
            stats["corner_error_mean"],
            expected,
            places=9,
        )

    def test_corner_permutation_is_not_corrected(self):
        gt = "0,0;10,0;10,10;0,10"
        cyclic = "10,0;10,10;0,10;0,0"
        stats = self._evaluate(
            [("one.jpg", [(cyclic, {})])],
            [("one.jpg", [(gt, {})])],
        )
        self.assertGreater(stats["corner_error_mean"], 0.5)

    def test_pair_below_iou_threshold_does_not_contribute(self):
        gt = "0,0;10,0;10,10;0,10"
        pred = "100,100;110,100;110,110;100,110"
        stats = self._evaluate(
            [("one.jpg", [(pred, {})])],
            [("one.jpg", [(gt, {})])],
        )
        self.assertEqual(
            stats["corner_metric_status"],
            "NO_VALID_CORNERS",
        )
        self.assertEqual(stats["corner_error_count"], 0)
        self.assertEqual(stats["corner_matched_pairs"], 0)

    def test_percentiles_are_linear_interpolation(self):
        gt_images = []
        pred_images = []
        diagonal = math.hypot(100.0, 100.0)
        for shift in range(5):
            name = f"{shift}.jpg"
            gt = "0,0;100,0;100,100;0,100"
            pred = (
                f"{shift},0;"
                f"{100 + shift},0;"
                f"{100 + shift},100;"
                f"{shift},100"
            )
            gt_images.append((name, [(gt, {})]))
            pred_images.append((name, [(pred, {})]))

        stats = self._evaluate(pred_images, gt_images)
        self.assertEqual(stats["corner_error_count"], 5)
        self.assertAlmostEqual(
            stats["corner_error_mean"],
            2.0 / diagonal,
            places=9,
        )
        self.assertAlmostEqual(
            stats["corner_error_p50"],
            2.0 / diagonal,
            places=9,
        )
        self.assertAlmostEqual(
            stats["corner_error_p90"],
            3.6 / diagonal,
            places=9,
        )
        self.assertAlmostEqual(
            stats["corner_error_p95"],
            3.8 / diagonal,
            places=9,
        )
        self.assertAlmostEqual(
            stats["corner_error_max"],
            4.0 / diagonal,
            places=9,
        )

    def test_controlled_mode_requires_pose_marker(self):
        points = "0,0;10,0;10,10;0,10"
        stats = self._evaluate(
            [(
                "one.jpg",
                [(
                    points,
                    {
                        "corner_source": "bbox_fallback",
                        "corner_order": "tl_tr_br_bl",
                    },
                )],
            )],
            [("one.jpg", [(points, {})])],
            require_prediction_pose_marker=True,
        )
        self.assertEqual(
            stats["corner_metric_status"],
            "NO_VALID_CORNERS",
        )
        self.assertEqual(stats["corner_missing_pose_pairs"], 1)

    def test_pose_marker_allows_controlled_corner_metric(self):
        points = "0,0;10,0;10,10;0,10"
        stats = self._evaluate(
            [(
                "one.jpg",
                [(
                    points,
                    {
                        "corner_source": "pose",
                        "corner_order": "tl_tr_br_bl",
                    },
                )],
            )],
            [("one.jpg", [(points, {})])],
            require_prediction_pose_marker=True,
        )
        self.assertEqual(stats["corner_metric_status"], "OK")
        self.assertEqual(stats["corner_error_count"], 1)


if __name__ == "__main__":
    unittest.main()
