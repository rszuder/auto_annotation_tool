import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.participant_model_registry import (
    eligible_training_runs,
    register_existing_participant_model,
)


class _FakeRepository:
    def __init__(self, *, provenance="complete", target="plate"):
        self.run = {
            "run_id": "RUN-1",
            "project_id": "PRJ-1",
            "target": target,
            "dataset_id": "DS-1",
            "provenance_status": provenance,
            "finished_at": "2026-09-14T10:00:00+00:00",
        }
        self.saved = None
        self.existing = None

    def initialize(self):
        return 1

    def list_training_runs_for_target(self, target):
        return [self.run] if self.run["target"] == target else []

    def get_training_run(self, run_id):
        return self.run if run_id == "RUN-1" else None

    def get_model_by_sha256(self, sha256):
        return self.existing

    def upsert_model_location(self, **kwargs):
        self.saved = dict(kwargs)
        return kwargs["model_id"]


class ParticipantModelRegistryTests(unittest.TestCase):
    def test_eligible_runs_require_known_provenance_and_dataset(self):
        repo = _FakeRepository()
        self.assertEqual(len(eligible_training_runs(repo, "plate")), 1)
        repo.run["provenance_status"] = "legacy_unknown"
        self.assertEqual(eligible_training_runs(repo, "plate"), [])

    def test_manual_registration_is_known_and_attested(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            model = workspace / "external_yolo26m.pt"
            model.write_bytes(b"checkpoint")
            repo = _FakeRepository()

            result = register_existing_participant_model(
                workspace,
                model,
                run_id="RUN-1",
                target="plate",
                repository=repo,
            )

            self.assertTrue(result.model_id.startswith("MODEL-"))
            self.assertEqual(result.provenance_status, "known")
            self.assertEqual(repo.saved["run_id"], "RUN-1")
            self.assertEqual(repo.saved["provenance_status"], "known")
            self.assertEqual(repo.saved["yolo_family"], "YOLO26")
            self.assertEqual(repo.saved["yolo_scale"], "m")

            log = workspace / "_registry" / "manual_model_run_attestations.jsonl"
            row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["run_id"], "RUN-1")
            self.assertEqual(row["dataset_id"], "DS-1")

    def test_target_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "yolo26n.pt"
            model.write_bytes(b"x")
            with self.assertRaises(ValueError):
                register_existing_participant_model(
                    tmp,
                    model,
                    run_id="RUN-1",
                    target="plate",
                    repository=_FakeRepository(target="char"),
                )

    def test_incomplete_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "yolo26n.pt"
            model.write_bytes(b"x")
            with self.assertRaises(ValueError):
                register_existing_participant_model(
                    tmp,
                    model,
                    run_id="RUN-1",
                    target="plate",
                    repository=_FakeRepository(provenance="partial"),
                )


if __name__ == "__main__":
    unittest.main()
