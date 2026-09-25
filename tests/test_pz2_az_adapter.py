import unittest

from auto_annotation_tool.registry.pz2_az_adapter import (
    derive_pz2_revision_context,
    pz2_metadata_to_az_payload,
)


IDENTITY = "a" * 64


class PZ2AZAdapterTests(unittest.TestCase):
    def base(self):
        return {
            "crop_identity_sha256": IDENTITY,
            "plate_image_width": 256,
            "plate_image_height": 64,
            "characters": [
                {
                    "character": "b",
                    "bbox": [100, 8, 140, 56],
                    "confidence": 0.91,
                    "method": "manual",
                    "source_kind": "local_manual",
                    "reading_row": 1,
                    "reading_col": 2,
                },
                {
                    "character": "a",
                    "bbox": [20, 8, 60, 56],
                    "confidence": 0.95,
                    "method": "manual",
                    "source_kind": "local_manual",
                    "reading_row": 1,
                    "reading_col": 1,
                },
            ],
            "plate_layout": "single_row",
            "layout_row_count": 1,
            "layout_source": "manual_override",
            "plate_layout_override": "single_row",
            "gold_state": {
                "approved": True,
                "excluded": False,
                "candidate": True,
            },
            "status": "perfect",
            "ground_truth_text": "AB",
            "source_info": {
                "bucket": "local_manual",
                "origin": "preview_editor",
            },
        }

    def test_pixel_bboxes_are_normalized_and_sorted(self):
        payload = pz2_metadata_to_az_payload(self.base())

        self.assertEqual(
            [c["character"] for c in payload["characters"]],
            ["A", "B"],
        )
        self.assertEqual(
            payload["characters"][0]["bbox"],
            [0.078125, 0.125, 0.234375, 0.875],
        )
        self.assertEqual(payload["characters"][0]["row"], 1)

    def test_layout_and_gold_state_are_preserved_semantically(self):
        payload = pz2_metadata_to_az_payload(self.base())

        self.assertEqual(payload["layout"]["kind"], "single_row")
        self.assertTrue(payload["layout"]["confirmed"])
        self.assertTrue(payload["gold_state"]["approved"])
        self.assertFalse(payload["gold_state"]["excluded"])
        self.assertTrue(payload["gold_state"]["candidate"])
        self.assertEqual(payload["status"], "perfect")
        self.assertEqual(payload["expected_text"], "AB")

    def test_explicit_dimensions_can_be_used_without_runtime_metadata(self):
        data = self.base()
        data.pop("plate_image_width")
        data.pop("plate_image_height")

        payload = pz2_metadata_to_az_payload(
            data,
            image_width=256,
            image_height=64,
        )
        self.assertEqual(len(payload["characters"]), 2)

    def test_nonempty_characters_require_dimensions(self):
        data = self.base()
        data.pop("plate_image_width")
        data.pop("plate_image_height")

        with self.assertRaises(ValueError):
            pz2_metadata_to_az_payload(data)

    def test_empty_characters_do_not_require_dimensions(self):
        data = self.base()
        data["characters"] = []
        data.pop("plate_image_width")
        data.pop("plate_image_height")

        payload = pz2_metadata_to_az_payload(data)
        self.assertEqual(payload["characters"], [])

    def test_requires_az003_crop_identity(self):
        data = self.base()
        data.pop("crop_identity_sha256")

        with self.assertRaises(ValueError):
            pz2_metadata_to_az_payload(data)

    def test_two_row_reading_rows_survive_canonicalization(self):
        data = self.base()
        data["plate_image_height"] = 128
        data["plate_layout"] = "two_row"
        data["plate_layout_override"] = "two_row"
        data["characters"][0]["bbox"] = [100, 70, 140, 120]
        data["characters"][0]["reading_row"] = 2
        data["characters"][0]["reading_col"] = 1
        data["characters"][1]["bbox"] = [20, 8, 60, 56]
        data["characters"][1]["reading_row"] = 1
        data["characters"][1]["reading_col"] = 1

        payload = pz2_metadata_to_az_payload(data)

        self.assertEqual(payload["layout"]["kind"], "two_row")
        self.assertEqual(
            [c["row"] for c in payload["characters"]],
            [1, 2],
        )

    def test_cvat_context_is_external_reviewed(self):
        data = self.base()
        data["characters"][0]["source_kind"] = "cvat_manual"
        data["source_info"] = {
            "bucket": "cvat_manual",
            "origin": "cvat_import",
        }

        context = derive_pz2_revision_context(data)

        self.assertEqual(context.source_kind, "cvat_manual")
        self.assertEqual(context.trust_state, "external_reviewed")
        self.assertEqual(context.effective_status, "approved")

    def test_excluded_wins_effective_status(self):
        data = self.base()
        data["gold_state"]["approved"] = False
        data["gold_state"]["excluded"] = True
        data["status"] = "needs_fix"

        context = derive_pz2_revision_context(data)

        self.assertEqual(context.effective_status, "excluded")

    def test_detected_context_defaults_to_auto(self):
        data = self.base()
        for rec in data["characters"]:
            rec["source_kind"] = "yolo"
            rec["method"] = "yolo"
        data["source_info"] = {
            "bucket": "auto_preview",
            "origin": "pz2_detect",
        }
        data["gold_state"]["approved"] = False

        context = derive_pz2_revision_context(data)

        self.assertEqual(context.source_kind, "pz2_detect")
        self.assertEqual(context.trust_state, "auto")
        self.assertEqual(context.effective_status, "ready")


if __name__ == "__main__":
    unittest.main()
