import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.participant_model_registry import (
    unregister_manual_participant_model,
)
from auto_annotation_tool.registry.repository import RegistryRepository


class ParticipantModelUnregisterTests(unittest.TestCase):
    def _register_model(
        self,
        workspace: Path,
        *,
        model_id: str = "MODEL-MANUAL",
        checkpoint_kind: str = "manual_registered",
        relative_path: str | None = None,
        external_path: str | None = None,
    ):
        repo = RegistryRepository.for_workspace(workspace)
        repo.initialize()
        model_path = workspace / "external_model.pt"
        model_path.write_bytes(b"manual-checkpoint")
        sha = hashlib.sha256(model_path.read_bytes()).hexdigest()

        if relative_path is None and external_path is None:
            external_path = str(model_path.resolve())

        repo.upsert_model_location(
            model_id=model_id,
            sha256=sha,
            project_id=None,
            run_id=None,
            target="plate",
            task_type="pose",
            yolo_family="YOLO26",
            yolo_scale="n",
            checkpoint_kind=checkpoint_kind,
            provenance_status="known",
            created_at=None,
            location_key="test-location",
            relative_path=relative_path,
            external_path=external_path,
            is_primary=True,
        )
        return repo, model_path, sha

    def test_repository_get_model_by_sha256_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo, _model_path, sha = self._register_model(workspace)
            row = repo.get_model_by_sha256(sha)
            self.assertIsNotNone(row)
            self.assertEqual(str(row["model_id"]), "MODEL-MANUAL")

    def test_manual_external_model_can_be_unregistered_without_deleting_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo, model_path, _sha = self._register_model(workspace)

            result = unregister_manual_participant_model(
                workspace,
                "MODEL-MANUAL",
                repository=repo,
            )

            self.assertEqual(result.model_id, "MODEL-MANUAL")
            self.assertTrue(model_path.exists())
            self.assertIsNone(repo.get_model("MODEL-MANUAL"))
            self.assertEqual(repo.list_model_locations("MODEL-MANUAL"), [])

            audit_path = (
                workspace
                / "_registry"
                / "manual_model_run_attestations.jsonl"
            )
            rows = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(rows[-1]["action"], "unregister")

    def test_automatically_managed_model_cannot_be_unregistered(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo, _model_path, _sha = self._register_model(
                workspace,
                checkpoint_kind="trained_export",
            )
            with self.assertRaises(ValueError):
                unregister_manual_participant_model(
                    workspace,
                    "MODEL-MANUAL",
                    repository=repo,
                )
            self.assertIsNotNone(repo.get_model("MODEL-MANUAL"))

    def test_model_used_by_track_participants_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo, _model_path, _sha = self._register_model(workspace)

            track_root = workspace / "10_experiments" / "tracks" / "TRK-1"
            track_root.mkdir(parents=True)
            repo.create_evaluation_track(
                track_id="TRK-1",
                owner_project_id=None,
                name="Ranking",
                target="plate",
                purpose="ranking",
                scope="global",
                status="DRAFT",
                version=1,
                parent_track_id=None,
                relative_path=str(
                    track_root.relative_to(workspace)
                ).replace("\\", "/"),
                reservation_policy="reserve_from_training",
                created_at=None,
            )
            (track_root / "participants.json").write_text(
                json.dumps(
                    {
                        "participants": [
                            {"model_id": "MODEL-MANUAL"}
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                unregister_manual_participant_model(
                    workspace,
                    "MODEL-MANUAL",
                    repository=repo,
                )
            self.assertIn("uczestnikiem", str(ctx.exception).lower())
            self.assertIsNotNone(repo.get_model("MODEL-MANUAL"))

    def test_managed_6_models_location_is_not_silently_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            managed_rel = "6_models/imported/model.pt"
            managed_path = workspace / managed_rel
            managed_path.parent.mkdir(parents=True)
            managed_path.write_bytes(b"managed")
            sha = hashlib.sha256(managed_path.read_bytes()).hexdigest()

            repo = RegistryRepository.for_workspace(workspace)
            repo.initialize()
            repo.upsert_model_location(
                model_id="MODEL-MANAGED-MANUAL",
                sha256=sha,
                project_id=None,
                run_id=None,
                target="plate",
                task_type="pose",
                yolo_family="YOLO26",
                yolo_scale="n",
                checkpoint_kind="manual_registered",
                provenance_status="known",
                created_at=None,
                location_key="managed-location",
                relative_path=managed_rel,
                external_path=None,
                is_primary=True,
            )

            with self.assertRaises(ValueError) as ctx:
                unregister_manual_participant_model(
                    workspace,
                    "MODEL-MANAGED-MANUAL",
                    repository=repo,
                )
            self.assertIn("6_models", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
