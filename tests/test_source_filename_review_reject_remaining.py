import unittest
from pathlib import Path

from auto_annotation_tool.gui.source_filename_review_dialog import (
    source_review_rejectable_paths,
)


class SourceFilenameRejectRemainingTests(unittest.TestCase):
    def test_valid_planned_rename_is_not_rejected(self):
        paths = [
            Path("BAD.jpg"),
            Path("ALSO_BAD.jpg"),
        ]
        rename_stems = {
            str(paths[0]): "ABC123_001",
        }

        rejectable = source_review_rejectable_paths(
            paths,
            rename_stems=rename_stems,
            root=Path("."),
        )

        self.assertNotIn(paths[0], rejectable)
        self.assertIn(paths[1], rejectable)

    def test_already_rejected_item_is_not_rejected_again(self):
        path = Path("BAD.jpg")
        rejectable = source_review_rejectable_paths(
            [path],
            rejected_paths={str(path)},
            root=Path("."),
        )
        self.assertEqual(rejectable, ())


if __name__ == "__main__":
    unittest.main()
