import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.gui.pz3_source_ingest_ui import (
    collect_folder_candidates,
    format_candidate_preflight_summary,
    preflight_deduplicate_candidates,
)
from auto_annotation_tool.gui.source_filename_review_dialog import (
    build_source_review_rows,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PZ3SourceIngestUiTests(unittest.TestCase):
    def test_folder_selection_is_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AS93_001.jpg").write_bytes(b"a")
            nested = root / "nested"
            nested.mkdir()
            (nested / "WX12_002.jpg").write_bytes(b"b")
            self.assertEqual(
                [item.name for item in collect_folder_candidates(root)],
                ["AS93_001.jpg"],
            )

    def test_same_sha_already_in_track_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "IMG_004.jpg"
            path.write_bytes(b"same")
            result = preflight_deduplicate_candidates(
                [path],
                [{
                    "original_name": "OLD_001.jpg",
                    "sha256": sha256(path),
                    "source_image_id": "SRC-1",
                }],
            )
            self.assertEqual(result.candidates, ())
            self.assertEqual(len(result.already_in_track), 1)

    def test_same_bytes_twice_in_selection_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "AAA_001.jpg"
            second = root / "BBB_002.jpg"
            first.write_bytes(b"same")
            second.write_bytes(b"same")
            result = preflight_deduplicate_candidates([first, second], [])
            self.assertEqual(result.candidates, (first,))
            self.assertEqual(len(result.batch_duplicates), 1)
            self.assertEqual(result.batch_duplicates[0].duplicate_of, first.name)

    def test_same_name_different_bytes_is_name_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AAA_001.jpg"
            path.write_bytes(b"new")
            result = preflight_deduplicate_candidates(
                [path],
                [{
                    "original_name": "AAA_001.jpg",
                    "sha256": hashlib.sha256(b"old").hexdigest(),
                }],
            )
            self.assertEqual(result.candidates, ())
            self.assertEqual(len(result.name_collisions), 1)

    def test_summary_does_not_call_duplicate_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "IMG_004.jpg"
            path.write_bytes(b"same")
            result = preflight_deduplicate_candidates(
                [path],
                [{"original_name": "OLD_001.jpg", "sha256": sha256(path)}],
            )
            text = format_candidate_preflight_summary(result)
            self.assertIn("już obecne w torze: 1", text)
            self.assertIn("nowe kandydaty do audytu train/val: 0", text)
            self.assertNotIn("niezależne", text.lower())

    def test_planned_valid_rename_stays_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BAD.jpg"
            path.write_bytes(b"x")
            rows = build_source_review_rows(
                [path],
                rename_stems={str(path): "IMG_004"},
            )
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].unresolved)
            self.assertIn("IMG_004.jpg", rows[0].action)
            self.assertIn("spełnia kontrakt", rows[0].problem)


if __name__ == "__main__":
    unittest.main()
