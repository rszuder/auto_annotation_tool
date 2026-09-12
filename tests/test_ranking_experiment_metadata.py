import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.ranking.model_ranking import ModelRanking


class RankingExperimentMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_add_entry_accepts_experiment_context(self):
        ranking = ModelRanking(self.root)
        entry = ranking.add_entry(
            model_name="model.pt",
            model_path=str(self.root / "model.pt"),
            comparison_stats={
                "precision": 80,
                "recall": 70,
            },
            experiment_context={
                "experiment_id": "EXP-1",
                "experiment_mode": "controlled",
                "model_id": "MODEL-1",
                "model_sha256": "a" * 64,
                "track_id": "TRK-1",
                "protocol_sha256": "b" * 64,
                "track_manifest_sha256": "c" * 64,
                "independence_status": "PASS",
            },
        )

        self.assertEqual(entry.experiment_id, "EXP-1")
        self.assertEqual(entry.model_id, "MODEL-1")
        self.assertEqual(entry.track_id, "TRK-1")
        self.assertEqual(entry.independence_status, "PASS")

    def test_experiment_metadata_roundtrips_through_json(self):
        ranking = ModelRanking(self.root)
        ranking.add_entry(
            model_name="model.pt",
            model_path=str(self.root / "model.pt"),
            comparison_stats={"map50_95": 0.5},
            experiment_context={
                "experiment_id": "EXP-2",
                "model_id": "MODEL-2",
                "model_sha256": "d" * 64,
                "track_id": "TRK-2",
                "protocol_sha256": "e" * 64,
                "track_manifest_sha256": "f" * 64,
                "independence_status": "PASS",
            },
        )

        reloaded = ModelRanking(self.root)
        self.assertEqual(len(reloaded.entries), 1)
        entry = reloaded.entries[0]
        self.assertEqual(entry.experiment_id, "EXP-2")
        self.assertEqual(entry.model_sha256, "d" * 64)
        self.assertEqual(entry.protocol_sha256, "e" * 64)

    def test_legacy_entry_without_experiment_fields_still_loads(self):
        path = self.root / ModelRanking.RANKING_FILE
        path.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "entries": [
                        {
                            "model_name": "legacy.pt",
                            "model_path": "legacy.pt",
                            "date_evaluated": "2026-01-01T00:00:00",
                            "precision": 50,
                            "recall": 50,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        ranking = ModelRanking(self.root)
        self.assertEqual(len(ranking.entries), 1)
        entry = ranking.entries[0]
        self.assertEqual(entry.experiment_id, "")
        self.assertEqual(entry.model_id, "")
        self.assertEqual(entry.independence_status, "")


if __name__ == "__main__":
    unittest.main()
