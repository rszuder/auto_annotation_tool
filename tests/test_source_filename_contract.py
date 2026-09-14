import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.campaign_ingest_planner import CampaignIngestPlanner
from auto_annotation_tool.gui.z3_extraction_sources import (
    extract_source_plate_tokens_from_filename,
)
from auto_annotation_tool.source_filename_contract import (
    PLATE_CROP_KIND,
    SOURCE_IMAGE_KIND,
    extract_plate_tokens_from_source_filename,
    parse_plate_crop_filename,
    parse_source_image_filename,
    validate_plate_crop_directory,
    validate_source_image_directory,
    validate_source_image_paths,
)


class SourceFilenameContractTests(unittest.TestCase):
    def test_single_plate_source_name(self):
        item = parse_source_image_filename("AS93_001.jpg")
        self.assertTrue(item.valid)
        self.assertEqual(item.kind, SOURCE_IMAGE_KIND)
        self.assertEqual(item.plate_tokens, ("AS93",))
        self.assertEqual(item.sequence_id, "001")

    def test_three_digit_registration_is_valid(self):
        item = parse_source_image_filename("365_001.jpg")
        self.assertTrue(item.valid)
        self.assertEqual(item.plate_tokens, ("365",))

    def test_multi_plate_source_name(self):
        item = parse_source_image_filename("2TT0978_WI905PW_001.jpg")
        self.assertTrue(item.valid)
        self.assertEqual(item.plate_tokens, ("2TT0978", "WI905PW"))

    def test_four_digit_sequence_is_supported(self):
        item = parse_source_image_filename("ABC1234_0001.jpg")
        self.assertTrue(item.valid)
        self.assertEqual(item.sequence_id, "0001")

    def test_letters_only_registration_token_is_valid(self):
        item = parse_source_image_filename("IMG_004.jpg")
        self.assertTrue(item.valid)
        self.assertEqual(item.plate_tokens, ("IMG",))
        self.assertEqual(item.sequence_id, "004")

    def test_missing_sequence_is_rejected(self):
        self.assertFalse(parse_source_image_filename("AS93.jpg").valid)

    def test_directory_is_atomic_when_one_name_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AS93_001.jpg").write_bytes(b"a")
            (root / "bad.jpg").write_bytes(b"b")
            report = validate_source_image_directory(root)
            self.assertFalse(report.valid)
            self.assertEqual(report.total_count, 2)
            self.assertEqual(report.invalid_count, 1)

    def test_paths_report_preserves_all_items(self):
        report = validate_source_image_paths(
            [Path("AS93_001.jpg"), Path("365_002.png")]
        )
        self.assertTrue(report.valid)
        self.assertEqual(report.valid_count, 2)

    def test_crop_name_contract(self):
        item = parse_plate_crop_filename("plate_000123.jpg")
        self.assertTrue(item.valid)
        self.assertEqual(item.kind, PLATE_CROP_KIND)
        self.assertFalse(parse_plate_crop_filename("plate_123.jpg").valid)

    def test_crop_directory_requires_metadata_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            images = run / "images"
            images.mkdir(parents=True)
            (images / "plate_000001.jpg").write_bytes(b"crop")

            report = validate_plate_crop_directory(run)
            self.assertFalse(report.valid)
            self.assertTrue(report.metadata_error)

            (run / "metadata.json").write_text(
                json.dumps(
                    {
                        "plate_000001": {
                            "source_image": "AS93_001.jpg"
                        }
                    }
                ),
                encoding="utf-8",
            )
            report = validate_plate_crop_directory(run)
            self.assertTrue(report.valid)
            self.assertEqual(report.valid_count, 1)

    def test_shared_parsers_use_central_contract(self):
        planner = CampaignIngestPlanner()
        expected = ["365", "WF3799Y"]
        name = "365_WF3799Y_001.jpg"
        self.assertEqual(
            planner.extract_true_texts_from_filename(name),
            expected,
        )
        self.assertEqual(
            extract_source_plate_tokens_from_filename(name),
            expected,
        )
        self.assertEqual(
            extract_plate_tokens_from_source_filename(name),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
