
import unittest

from auto_annotation_tool.gui import z4_analysis_ranking as ranking


class RankingResultsAnalysisTests(unittest.TestCase):
    def rows(self):
        common = {
            "scope": "Globalne",
            "evidence_label": "CONTROLLED",
            "registry_experiment_status": "COMPLETED",
            "score": 94.0,
            "sample": 100,
            "corner_metric_status": "OK",
            "corner_error_count": 90,
            "corner_matched_pairs": 90,
            "corner_skipped_pairs": 0,
            "plates_unchanged": 20,
            "plates_minor_fix": 60,
            "plates_major_fix": 10,
            "plates_added": 5,
            "plates_removed": 5,
        }
        a = {
            **common,
            "rank": 1,
            "label": "Model A",
            "model_file": "a.pt",
            "f1": 94.0,
            "precision": 92.0,
            "recall": 96.0,
            "accuracy": 85.0,
            "corner_error_mean": 0.04,
            "corner_error_p50": 0.02,
            "corner_error_p90": 0.08,
            "corner_error_p95": 0.16,
            "corner_error_max": 0.40,
            "benchmark_group_metrics": {
                "groups": [
                    {
                        "group_id": "ALL",
                        "label_name": "Wszystkie",
                        "sample_count": 100,
                        "f1": 94.0,
                    },
                    {
                        "group_id": "LABEL:L1",
                        "label_id": "L1",
                        "label_name": "Noc",
                        "sample_count": 40,
                        "precision": 90.0,
                        "recall": 94.0,
                        "f1": 91.96,
                        "accuracy": 80.0,
                        "corner_metric_status": "OK",
                        "corner_error_mean": 0.05,
                        "corner_error_p50": 0.03,
                        "corner_error_p90": 0.10,
                        "corner_error_p95": 0.21,
                        "corner_error_max": 0.50,
                    },
                ]
            },
        }
        b = {
            **common,
            "rank": 2,
            "label": "Model B",
            "model_file": "b.pt",
            "f1": 93.9,
            "precision": 91.0,
            "recall": 97.0,
            "accuracy": 84.0,
            "corner_error_mean": 0.03,
            "corner_error_p50": 0.015,
            "corner_error_p90": 0.09,
            "corner_error_p95": 0.10,
            "corner_error_max": 0.35,
            "benchmark_group_metrics": {
                "groups": [
                    {
                        "group_id": "ALL",
                        "label_name": "Wszystkie",
                        "sample_count": 100,
                        "f1": 93.9,
                    },
                    {
                        "group_id": "LABEL:L1",
                        "label_id": "L1",
                        "label_name": "Noc",
                        "sample_count": 40,
                        "precision": 89.0,
                        "recall": 96.0,
                        "f1": 92.37,
                        "accuracy": 83.0,
                        "corner_metric_status": "OK",
                        "corner_error_mean": 0.03,
                        "corner_error_p50": 0.02,
                        "corner_error_p90": 0.08,
                        "corner_error_p95": 0.11,
                        "corner_error_max": 0.30,
                    },
                ]
            },
        }
        return [a, b]

    def test_flattens_saved_label_metrics(self):
        rows = ranking._ranking_label_metric_rows(self.rows())
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["label_name"] for row in rows}, {"Noc"})
        self.assertEqual({row["model_file"] for row in rows}, {"a.pt", "b.pt"})

    def test_report_contains_deep_corner_and_label_analysis(self):
        context = {
            "rows": self.rows(),
            "target": "plate",
            "analysis_mode": "controlled",
            "target_task": "Tablice (Pose)",
            "scope_label": "Workspace MT",
            "reference_name": "Fixture",
            "reference_path": "fixture",
            "participant_ids": ["A", "B"],
            "track_id": "TRK-1",
            "reference_info": {"image_count": 100},
            "pending_count": 0,
        }
        text = ranking._ranking_report_markdown(context)
        self.assertIn("Metryki według etykiet próbki", text)
        self.assertIn("Noc", text)
        self.assertIn("p90", text)
        self.assertIn("p95", text)
        self.assertIn("IoU≥0.8", text)
        self.assertIn("ranking_label_metrics.csv", text)

    def test_new_svgs_render_label_and_corner_metrics(self):
        rows = self.rows()
        corners = ranking._ranking_report_corner_svg(rows, title="Corners")
        labels = ranking._ranking_report_label_metric_svg(
            rows,
            title="Labels",
            metric_key="f1",
            metric_label="F1",
        )
        self.assertIn("p95", corners)
        self.assertIn("Noc", labels)
        self.assertIn("b.pt", labels)


if __name__ == "__main__":
    unittest.main()
