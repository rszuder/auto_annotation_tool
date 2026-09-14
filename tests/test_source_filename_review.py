import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.gui.source_filename_review_dialog import (
    apply_source_review_actions,
)
from auto_annotation_tool.source_filename_contract import (
    validate_source_image_directory,
)


class SourceFilenameReviewTests(unittest.TestCase):
    def test_rename_invalid_file_to_valid_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pool"
            root.mkdir()
            bad = root / "IMG.jpg"
            bad.write_bytes(b"x")

            result = apply_source_review_actions(
                root,
                rename_stems={str(bad): "AS93_001"},
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.renamed, 1)
            self.assertFalse(bad.exists())
            self.assertTrue((root / "AS93_001.jpg").exists())
            self.assertTrue(
                validate_source_image_directory(root).valid
            )

    def test_reject_moves_file_outside_resource_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pool"
            root.mkdir()
            good = root / "AS93_001.jpg"
            bad = root / "bad.jpg"
            good.write_bytes(b"good")
            bad.write_bytes(b"bad")

            result = apply_source_review_actions(
                root,
                rejected_paths={str(bad)},
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.rejected, 1)
            self.assertFalse(bad.exists())
            quarantine = Path(result.quarantine_dir)
            self.assertTrue((quarantine / "bad.jpg").exists())
            self.assertEqual(
                (quarantine / "bad.jpg").read_bytes(),
                b"bad",
            )
            self.assertTrue(
                validate_source_image_directory(root).valid
            )

    def test_invalid_new_name_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pool"
            root.mkdir()
            bad = root / "bad.jpg"
            bad.write_bytes(b"x")

            result = apply_source_review_actions(
                root,
                rename_stems={str(bad): "stillbad"},
            )

            self.assertFalse(result.ok)
            self.assertTrue(bad.exists())

    def test_collision_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pool"
            root.mkdir()
            bad = root / "bad.jpg"
            existing = root / "AS93_001.jpg"
            bad.write_bytes(b"x")
            existing.write_bytes(b"y")

            result = apply_source_review_actions(
                root,
                rename_stems={str(bad): "AS93_001"},
            )

            self.assertFalse(result.ok)
            self.assertTrue(bad.exists())
            self.assertEqual(existing.read_bytes(), b"y")


if __name__ == "__main__":
    unittest.main()
