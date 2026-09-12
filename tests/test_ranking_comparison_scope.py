import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.ranking.model_ranking import ModelRanking


class RankingComparisonScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = self.root / "model.pt"
        self.model.write_bytes(b"model")

    def tearDown(self):
        self.temp.cleanup()

    def _add(self, scope, project_id=""):
        ranking = ModelRanking(self.root)
        return ranking.add_entry(
            model_name=self.model.name,
            model_path=str(self.model),
            comparison_stats={
                "precision": 80,
                "recall": 70,
            },
            reference_name="track",
            reference_path=str(self.root / "track"),
            experiment_context={
                "comparison_scope": scope,
                "comparison_project_id": project_id,
            },
        )

    def test_scope_metadata_is_saved(self):
        entry = self._add("Projekt", "PRJ-1")
        self.assertEqual(entry.comparison_scope, "Projekt")
        self.assertEqual(
            entry.comparison_project_id,
            "PRJ-1",
        )

    def test_scope_metadata_roundtrips(self):
        self._add("Globalne")
        ranking = ModelRanking(self.root)
        self.assertEqual(
            ranking.entries[0].comparison_scope,
            "Globalne",
        )

    def test_project_and_workspace_results_do_not_overwrite(self):
        ranking = ModelRanking(self.root)
        common = dict(
            model_name=self.model.name,
            model_path=str(self.model),
            comparison_stats={"precision": 80, "recall": 70},
            reference_name="track",
            reference_path=str(self.root / "track"),
        )
        ranking.add_entry(
            **common,
            experiment_context={
                "comparison_scope": "Projekt",
                "comparison_project_id": "PRJ-1",
            },
        )
        ranking.add_entry(
            **common,
            experiment_context={
                "comparison_scope": "Globalne",
            },
        )
        self.assertEqual(len(ranking.entries), 2)

    def test_repeated_same_scope_replaces_previous_entry(self):
        ranking = ModelRanking(self.root)
        common = dict(
            model_name=self.model.name,
            model_path=str(self.model),
            reference_name="track",
            reference_path=str(self.root / "track"),
            experiment_context={
                "comparison_scope": "Projekt",
                "comparison_project_id": "PRJ-1",
            },
        )
        ranking.add_entry(
            **common,
            comparison_stats={"precision": 10, "recall": 10},
        )
        ranking.add_entry(
            **common,
            comparison_stats={"precision": 90, "recall": 90},
        )
        self.assertEqual(len(ranking.entries), 1)
        self.assertEqual(ranking.entries[0].precision, 90)


if __name__ == "__main__":
    unittest.main()
