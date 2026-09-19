import unittest

from auto_annotation_tool.gui import z4_analysis_ranking as ranking


class MzResultsUiTests(unittest.TestCase):
    def rows(self):
        return [
            {
                "rank": 1,
                "label": "MZ-n",
                "model_file": "mz_n.pt",
                "exact_match_pct": 94.0,
                "cer": 0.018,
                "precision": 98.0,
                "recall": 97.0,
                "f1": 97.5,
                "sample": 100,
                "exact_match_count": 94,
                "no_read_count": 2,
                "correct_characters": 690,
                "incorrect_characters": 5,
                "missing_characters": 4,
                "extra_characters": 3,
                "character_confusion": [
                    {"ground_truth": "0", "prediction": "O", "count": 3},
                    {"ground_truth": "8", "prediction": "B", "count": 1},
                ],
                "benchmark_group_metrics": {
                    "groups": [
                        {
                            "group_id": "ALL",
                            "label_name": "Wszystkie",
                            "sample_count": 100,
                            "exact_match_pct": 94.0,
                            "cer": 0.018,
                        },
                        {
                            "group_id": "LABEL:NIGHT",
                            "label_id": "NIGHT",
                            "label_name": "Noc",
                            "sample_count": 30,
                            "exact_match_pct": 90.0,
                            "cer": 0.032,
                            "precision": 96.0,
                            "recall": 95.0,
                            "f1": 95.5,
                            "no_read_count": 2,
                            "correct_characters": 198,
                            "incorrect_characters": 4,
                            "missing_characters": 3,
                            "extra_characters": 2,
                        },
                    ]
                },
            },
            {
                "rank": 2,
                "label": "MZ-s",
                "model_file": "mz_s.pt",
                "exact_match_pct": 92.0,
                "cer": 0.024,
                "precision": 97.0,
                "recall": 96.0,
                "f1": 96.5,
                "sample": 100,
                "exact_match_count": 92,
                "no_read_count": 3,
                "correct_characters": 684,
                "incorrect_characters": 7,
                "missing_characters": 6,
                "extra_characters": 4,
                "character_confusion": [
                    {"ground_truth": "0", "prediction": "O", "count": 5},
                ],
                "benchmark_group_metrics": {
                    "groups": [
                        {
                            "group_id": "ALL",
                            "label_name": "Wszystkie",
                            "sample_count": 100,
                            "exact_match_pct": 92.0,
                            "cer": 0.024,
                        },
                        {
                            "group_id": "LABEL:NIGHT",
                            "label_id": "NIGHT",
                            "label_name": "Noc",
                            "sample_count": 30,
                            "exact_match_pct": 86.67,
                            "cer": 0.041,
                            "precision": 94.0,
                            "recall": 93.0,
                            "f1": 93.5,
                            "no_read_count": 3,
                            "correct_characters": 192,
                            "incorrect_characters": 6,
                            "missing_characters": 5,
                            "extra_characters": 3,
                        },
                    ]
                },
            },
        ]

    def context(self):
        return {
            "rows": self.rows(),
            "target": "char",
            "analysis_mode": "controlled",
            "target_task": "Znaki (Detect)",
            "reference_name": "MZ fixture",
            "reference_path": "fixture",
            "participant_ids": ["MZ-N", "MZ-S"],
            "track_id": "TRK-MZ",
            "report_title": "Eksperyment kontrolowany PZ3",
        }

    def test_char_markdown_uses_exact_match_and_cer_not_corner_metrics(self):
        text = ranking._ranking_report_markdown(self.context())
        self.assertIn("Exact Match", text)
        self.assertIn("CER", text)
        self.assertIn("Struktura błędów znakowych", text)
        self.assertIn("Najczęstsze pomyłki znaków", text)
        self.assertIn("Noc", text)
        self.assertNotIn("E_corner", text)
        self.assertNotIn("IoU≥0.8", text)

    def test_confusion_rows_are_flattened_and_sorted(self):
        rows = ranking._ranking_character_confusion_rows(self.rows())
        self.assertEqual(rows[0]["ground_truth"], "0")
        self.assertEqual(rows[0]["prediction"], "O")
        self.assertEqual(rows[0]["count"], 5)
        self.assertEqual(
            {row["model_file"] for row in rows},
            {"mz_n.pt", "mz_s.pt"},
        )

    def test_char_quality_svg_contains_both_metrics(self):
        svg = ranking._ranking_report_char_quality_svg(
            self.rows(),
            title="MZ quality",
        )
        self.assertIn("Exact", svg)
        self.assertIn("CER", svg)
        self.assertIn("MZ-n", svg)
        self.assertIn("MZ-s", svg)

    def test_label_rows_keep_exact_match_and_cer(self):
        rows = ranking._ranking_label_metric_rows(self.rows())
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["label_name"] for row in rows}, {"Noc"})
        self.assertTrue(all("exact_match_pct" in row for row in rows))
        self.assertTrue(all("cer" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
