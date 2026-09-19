
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from auto_annotation_tool.data_models import Detection, ImageAnnotation
from auto_annotation_tool.exporters.cvat_exporter import CVATExporter
from auto_annotation_tool.pose_corners import (
    is_canonical_quad_tl_tr_br_bl,
    parse_quad_points,
)


class Pz3GtPoseNormalizationTests(unittest.TestCase):
    def test_cvat_exporter_canonicalizes_plate_polygon(self):
        with tempfile.TemporaryDirectory() as temp:
            xml = Path(temp) / "annotations.xml"
            detection = Detection(
                label="plate",
                confidence=0.9,
                bbox=(10.0, 10.0, 80.0, 40.0),
                polygon=[
                    (80.0, 40.0),
                    (10.0, 10.0),
                    (10.0, 40.0),
                    (80.0, 10.0),
                ],
            )
            annotation = ImageAnnotation(
                filename="POSE.png",
                width=100,
                height=60,
                detections=[detection],
            )

            self.assertTrue(
                CVATExporter().export(
                    [annotation],
                    xml,
                    include_confidence=True,
                    only_successful=False,
                )
            )

            polygon = ET.parse(xml).getroot().find(".//polygon")
            self.assertIsNotNone(polygon)
            points = parse_quad_points(polygon.get("points"))
            self.assertIsNotNone(points)
            self.assertTrue(
                is_canonical_quad_tl_tr_br_bl(points)
            )

    def test_exporter_keeps_same_four_geometric_corners(self):
        with tempfile.TemporaryDirectory() as temp:
            xml = Path(temp) / "annotations.xml"
            original = {
                (10.0, 10.0),
                (80.0, 10.0),
                (80.0, 40.0),
                (10.0, 40.0),
            }
            detection = Detection(
                label="plate",
                confidence=0.9,
                bbox=(10.0, 10.0, 80.0, 40.0),
                polygon=[
                    (80.0, 10.0),
                    (10.0, 40.0),
                    (10.0, 10.0),
                    (80.0, 40.0),
                ],
            )
            annotation = ImageAnnotation(
                filename="POSE.png",
                width=100,
                height=60,
                detections=[detection],
            )

            self.assertTrue(
                CVATExporter().export(
                    [annotation],
                    xml,
                    include_confidence=False,
                    only_successful=False,
                )
            )
            polygon = ET.parse(xml).getroot().find(".//polygon")
            points = parse_quad_points(polygon.get("points"))
            self.assertEqual(set(points), original)


if __name__ == "__main__":
    unittest.main()
