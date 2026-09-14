import unittest
from dataclasses import dataclass, field

from auto_annotation_tool.gui.pz3_audit_results_dialog import (
    audit_status_label,
    audit_summary_counts,
    build_audit_table_rows,
    compact_source_pool_audit_followup_text,
)


@dataclass
class FakeItem:
    candidate_path: str
    status: str
    reason: str = ""
    reference_matches: list[dict] = field(default_factory=list)


@dataclass
class FakeReport:
    items: list[FakeItem]


class PZ3AuditResultsDialogTests(unittest.TestCase):
    def test_status_labels_are_methodologically_precise(self):
        self.assertEqual(audit_status_label("DEPENDENT"), "ZALEŻNY")
        self.assertEqual(
            audit_status_label("NO_DETECTED_DEPENDENCE"),
            "BRAK WYKRYTEJ ZALEŻNOŚCI",
        )

    def test_table_rows_expose_reference_and_phash_distance(self):
        report = FakeReport(
            items=[
                FakeItem(
                    "IMG_004.jpg",
                    "SUSPECT_DERIVATIVE",
                    "podobny pHash",
                    reference_matches=[
                        {
                            "dataset_id": "DS-MT-1",
                            "split": "train",
                            "phash_distance": 4,
                        }
                    ],
                )
            ]
        )
        rows = build_audit_table_rows(report)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["filename"], "IMG_004.jpg")
        self.assertIn("DS-MT-1/train", rows[0]["reference"])
        self.assertEqual(rows[0]["phash_distance"], "4")

    def test_counts_are_derived_from_items(self):
        report = FakeReport(
            items=[
                FakeItem("A_001.jpg", "DEPENDENT"),
                FakeItem("B_001.jpg", "SUSPECT_DERIVATIVE"),
                FakeItem("C_001.jpg", "NO_DETECTED_DEPENDENCE"),
                FakeItem("D_001.jpg", "UNKNOWN"),
            ]
        )
        counts = audit_summary_counts(report)
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["dependent"], 1)
        self.assertEqual(counts["suspect"], 1)
        self.assertEqual(counts["no_detected"], 1)
        self.assertEqual(counts["unknown"], 1)

    def test_followup_text_does_not_call_no_overlap_independent(self):
        report = FakeReport(
            items=[
                FakeItem("IMG_004.jpg", "NO_DETECTED_DEPENDENCE"),
            ]
        )
        text = compact_source_pool_audit_followup_text(report)
        self.assertIn("Nie wykryto zależności", text)
        self.assertNotIn("niezależny", text.lower())


if __name__ == "__main__":
    unittest.main()
