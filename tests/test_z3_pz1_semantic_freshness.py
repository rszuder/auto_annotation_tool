import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from auto_annotation_tool.character_recognition.plate_generator import PlateGenerator
from auto_annotation_tool.data_models import Detection, ImageAnnotation
from auto_annotation_tool.gui.z3_extraction_sources import (
    count_xml_plate_cut_targets,
    current_extract_source_payload_with_signature,
    extract_manifest_matches_current_source,
    prepare_plate_cut_detections_for_source,
)


def write_xml(path: Path, gt: str) -> Path:
    path.write_text(
        (
            "<annotations>"
            "<image id='0' name='source.png' width='80' height='40'>"
            "<polygon label='plate' points='10,10;60,10;60,26;10,26'>"
            "<attribute name='plate_annotation_id'>plate-ann-fixed</attribute>"
            f"<attribute name='ground_truth_text'>{gt}</attribute>"
            "<attribute name='ground_truth_source'>manual_z2</attribute>"
            "</polygon>"
            "</image>"
            "</annotations>"
        ),
        encoding="utf-8",
    )
    return path


class Var:
    def __init__(self, value):
        self.value = str(value)

    def get(self):
        return self.value


class Host(SimpleNamespace):
    def _paths_equivalent(self, left, right):
        try:
            return Path(left).resolve() == Path(right).resolve()
        except Exception:
            return str(left) == str(right)


def make_host(xml_path: Path, images_dir: Path) -> Host:
    return Host(
        annotation_run_dir_var=Var(xml_path.parent),
        xml_path_var=Var(xml_path),
        images_dir_var=Var(images_dir),
    )


def plate(attributes=None):
    return Detection(
        label="plate",
        confidence=1.0,
        bbox=(10.0, 10.0, 60.0, 26.0),
        polygon=[
            (10.0, 10.0),
            (60.0, 10.0),
            (60.0, 26.0),
            (10.0, 26.0),
        ],
        attributes=dict(attributes or {}),
    )


def test_gt_only_xml_change_changes_gt_hash_not_geometry_hash(tmp_path):
    xml_path = write_xml(tmp_path / "annotations.xml", "ABC123")
    before = count_xml_plate_cut_targets(xml_path)

    write_xml(xml_path, "ABC124")
    after = count_xml_plate_cut_targets(xml_path)

    assert before["xml_plate_geometry_hash"] == after["xml_plate_geometry_hash"]
    assert before["xml_plate_gt_hash"] != after["xml_plate_gt_hash"]


def test_extract_manifest_becomes_stale_after_gt_only_change(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    xml_path = write_xml(tmp_path / "annotations.xml", "ABC123")

    before_host = make_host(xml_path, images)
    manifest = {
        "kind": "pz1_plate_extraction",
        "status": "completed",
        "plate_count": 1,
        "source": current_extract_source_payload_with_signature(before_host),
    }
    assert extract_manifest_matches_current_source(before_host, manifest)

    write_xml(xml_path, "ABC124")
    after_host = make_host(xml_path, images)
    assert not extract_manifest_matches_current_source(after_host, manifest)


def test_per_plate_semantic_hashes_are_added_before_pz1():
    det = plate(
        {
            "plate_annotation_id": "plate-ann-fixed",
            "ground_truth_text": "ABC123",
            "ground_truth_source": "manual_z2",
        }
    )
    host = SimpleNamespace(
        _plate_cut_reading_order_key=lambda pair: pair[0],
    )

    prepare_plate_cut_detections_for_source(
        host,
        "source.png",
        [det],
    )

    assert len(det.attributes["source_geometry_hash"]) == 64
    assert len(det.attributes["source_gt_hash"]) == 64

    geometry_hash = det.attributes["source_geometry_hash"]
    gt_hash = det.attributes["source_gt_hash"]

    det.attributes["ground_truth_text"] = "ABC124"
    prepare_plate_cut_detections_for_source(
        host,
        "source.png",
        [det],
    )

    assert det.attributes["source_geometry_hash"] == geometry_hash
    assert det.attributes["source_gt_hash"] != gt_hash


def test_plate_generator_carries_source_identity_and_semantic_hashes(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (80, 40), (20, 40, 60)).save(image_path)

    det = plate(
        {
            "plate_annotation_id": "plate-ann-fixed",
            "ground_truth_text": "ABC123",
            "ground_truth_source": "manual_z2",
            "source_geometry_hash": "g" * 64,
            "source_gt_hash": "t" * 64,
        }
    )
    ann = ImageAnnotation(
        image_path.name,
        80,
        40,
        [det],
    )

    generator = PlateGenerator(tmp_path / "pz1")
    results = generator.generate_from_annotations(
        image_path,
        ann,
        rectify=False,
    )

    assert len(results) == 1
    record = generator.metadata["plate_000000"]

    assert str(record["source_image_id"]).startswith("img-sha256-")
    assert len(record["source_file_sha256"]) == 64
    assert record["source_annotation_id"] == "plate-ann-fixed"
    assert record["source_geometry_hash"] == "g" * 64
    assert record["source_gt_hash"] == "t" * 64
    assert record["ground_truth_text"] == "ABC123"
