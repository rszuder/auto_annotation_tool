import unittest
from pathlib import Path

from auto_annotation_tool.gui.source_filename_review_dialog import (
    SourceReviewRow,
    source_review_sort_key,
)


class SourceFilenameReviewSortingTests(unittest.TestCase):
    def row(
        self,
        name,
        *,
        problem="Błąd",
        action="DO DECYZJI",
        unresolved=True,
    ):
        return SourceReviewRow(
            path=Path(name),
            display_name=name,
            problem=problem,
            action=action,
            unresolved=unresolved,
        )

    def test_file_sort_is_natural(self):
        rows = [
            self.row("IMG_010.jpg"),
            self.row("IMG_002.jpg"),
            self.row("IMG_001.jpg"),
        ]
        result = sorted(
            rows,
            key=lambda row: source_review_sort_key(row, "#0"),
        )
        self.assertEqual(
            [row.display_name for row in result],
            ["IMG_001.jpg", "IMG_002.jpg", "IMG_010.jpg"],
        )

    def test_validation_sort_puts_unresolved_first(self):
        rows = [
            self.row(
                "B.jpg",
                problem="✓ nowa nazwa spełnia kontrakt",
                unresolved=False,
            ),
            self.row(
                "A.jpg",
                problem="Niepoprawny identyfikator",
                unresolved=True,
            ),
        ]
        result = sorted(
            rows,
            key=lambda row: source_review_sort_key(row, "problem"),
        )
        self.assertTrue(result[0].unresolved)

    def test_action_sort_groups_decision_before_rename_before_reject(self):
        rows = [
            self.row("C.jpg", action="ODRZUĆ", unresolved=False),
            self.row("B.jpg", action="→ ABC_001.jpg", unresolved=False),
            self.row("A.jpg", action="DO DECYZJI", unresolved=True),
        ]
        result = sorted(
            rows,
            key=lambda row: source_review_sort_key(row, "action"),
        )
        self.assertEqual(
            [row.action for row in result],
            ["DO DECYZJI", "→ ABC_001.jpg", "ODRZUĆ"],
        )


if __name__ == "__main__":
    unittest.main()
