import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_annotation_tool.config import CONFIG
from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.bootstrap import (
    project_id_from_folder_name,
    registry_run_id,
)
from auto_annotation_tool.registry.runtime_service import register_exported_model, sync_training_run
from auto_annotation_tool.training.model_provenance import build_training_dataset_snapshot
from auto_annotation_tool.training.training_history import TrainingHistory


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RuntimeTrainingRegistryTests(unittest.TestCase):
    def _dataset(self, workspace: Path, name: str = "set_a", image_bytes: bytes = b"image") -> Path:
        root = workspace / "4_training_datasets" / "plates" / name
        for split in ("train", "val", "test"):
            (root / "images" / split).mkdir(parents=True, exist_ok=True)
            (root / "labels" / split).mkdir(parents=True, exist_ok=True)
        (root / "images" / "train" / "one.jpg").write_bytes(image_bytes)
        (root / "labels" / "train" / "one.txt").write_text(
            "0 0.5 0.5 0.5 0.5\n",
            encoding="utf-8",
        )
        (root / "data.yaml").write_text(
            "train: images/train\n"
            "val: images/val\n"
            "test: images/test\n"
            "names: [plate]\n",
            encoding="utf-8",
        )
        (root / "dataset_manifest.json").write_text(
            json.dumps({"source_images": 1}),
            encoding="utf-8",
        )
        return root

    def _input_checkpoint(self) -> dict:
        return {
            "sha256": "c" * 64,
            "provenance_status": "complete",
        }

    def test_create_run_registers_run_dataset_and_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            dataset = self._dataset(workspace)
            snapshot = build_training_dataset_snapshot(dataset, target="plate")
            history_dir = workspace / "5_training_runs" / "plates"

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                history = TrainingHistory(history_dir)
                run = history.create_run(
                    "runtime",
                    dataset_path=str(dataset),
                    base_model="yolo11s-pose.pt",
                    training_target="plate",
                    training_dataset_snapshot=snapshot,
                    training_dataset_input_snapshot=dict(snapshot),
                    input_checkpoint_snapshot=self._input_checkpoint(),
                )

            repo = RegistryRepository.for_workspace(workspace)
            self.assertEqual(repo.table_count("training_runs"), 1)
            self.assertEqual(repo.table_count("datasets"), 1)
            self.assertEqual(repo.table_count("dataset_members"), 1)
            row = repo.fetch_rows("SELECT * FROM training_runs")[0]
            self.assertEqual(row["dataset_id"], snapshot["dataset_id"])
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["provenance_status"], "complete")
            self.assertTrue(row["run_id"].startswith("RUN-"))
            self.assertNotEqual(row["run_id"], run.id)

    def test_prepared_dataset_change_updates_run_dataset_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            dataset = self._dataset(workspace, image_bytes=b"before")
            snapshot_before = build_training_dataset_snapshot(dataset, target="plate")
            history_dir = workspace / "5_training_runs" / "plates"

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                history = TrainingHistory(history_dir)
                run = history.create_run(
                    "prepared",
                    dataset_path=str(dataset),
                    base_model="yolo11s-pose.pt",
                    training_target="plate",
                    training_dataset_snapshot=snapshot_before,
                    training_dataset_input_snapshot=dict(snapshot_before),
                    input_checkpoint_snapshot=self._input_checkpoint(),
                )
                (dataset / "images" / "train" / "one.jpg").write_bytes(b"after")
                snapshot_after = build_training_dataset_snapshot(dataset, target="plate")
                self.assertNotEqual(snapshot_before["dataset_id"], snapshot_after["dataset_id"])
                history.update_run(
                    run.id,
                    training_dataset_snapshot=snapshot_after,
                    dataset_preparation={
                        "status": "verified_before_first_epoch",
                        "content_changed_during_preparation": True,
                    },
                )

            repo = RegistryRepository.for_workspace(workspace)
            row = repo.fetch_rows("SELECT * FROM training_runs")[0]
            self.assertEqual(row["dataset_id"], snapshot_after["dataset_id"])
            self.assertEqual(repo.table_count("datasets"), 2)

    def test_completed_run_registers_best_checkpoint_as_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            dataset = self._dataset(workspace)
            snapshot = build_training_dataset_snapshot(dataset, target="plate")
            history_dir = workspace / "5_training_runs" / "plates"

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                history = TrainingHistory(history_dir)
                run = history.create_run(
                    "model",
                    dataset_path=str(dataset),
                    base_model="yolo11s-pose.pt",
                    training_target="plate",
                    training_dataset_snapshot=snapshot,
                    training_dataset_input_snapshot=dict(snapshot),
                    input_checkpoint_snapshot=self._input_checkpoint(),
                )
                best = Path(run.output_dir) / "train" / "weights" / "best.pt"
                best.parent.mkdir(parents=True, exist_ok=True)
                model_bytes = b"trained-checkpoint"
                best.write_bytes(model_bytes)
                digest = _sha(model_bytes)
                history.update_run(
                    run.id,
                    status="completed",
                    finished_at="2026-09-12T15:00:00",
                    best_weights=str(best),
                    output_checkpoint_snapshot={
                        "best_checkpoint_sha256": digest,
                        "best": {
                            "sha256": digest,
                            "provenance_status": "complete",
                        },
                        "provenance_status": "complete",
                    },
                )

            repo = RegistryRepository.for_workspace(workspace)
            self.assertEqual(repo.table_count("models"), 1)
            self.assertEqual(repo.table_count("model_locations"), 1)
            model = repo.fetch_rows("SELECT * FROM models")[0]
            run_row = repo.fetch_rows("SELECT * FROM training_runs")[0]
            self.assertEqual(model["run_id"], run_row["run_id"])
            self.assertEqual(model["target"], "plate")
            self.assertEqual(model["task_type"], "pose")
            self.assertEqual(model["yolo_family"], "YOLO11")
            self.assertEqual(model["yolo_scale"], "s")
            self.assertEqual(model["sha256"], digest)
            self.assertEqual(model["provenance_status"], "complete")
            self.assertEqual(run_row["provenance_status"], "complete")

    def test_completed_run_without_output_snapshot_becomes_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            dataset = self._dataset(workspace)
            snapshot = build_training_dataset_snapshot(dataset, target="plate")
            history_dir = workspace / "5_training_runs" / "plates"

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                history = TrainingHistory(history_dir)
                run = history.create_run(
                    "partial",
                    dataset_path=str(dataset),
                    base_model="yolo11s-pose.pt",
                    training_target="plate",
                    training_dataset_snapshot=snapshot,
                    training_dataset_input_snapshot=dict(snapshot),
                    input_checkpoint_snapshot=self._input_checkpoint(),
                )
                repo = RegistryRepository.for_workspace(workspace)
                before = repo.fetch_rows("SELECT provenance_status FROM training_runs")[0]
                self.assertEqual(before["provenance_status"], "complete")
                history.update_run(
                    run.id,
                    status="completed",
                    finished_at="2026-09-12T15:00:00",
                    output_checkpoint_snapshot={},
                )

            after = repo.fetch_rows("SELECT provenance_status FROM training_runs")[0]
            self.assertEqual(after["provenance_status"], "partial")

    def test_project_run_and_fine_tune_parent_use_namespaced_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            folder = "Projekt_A_ABC123"
            project_root = workspace / "9_projects" / folder
            history_dir = project_root / "5_training_runs" / "plates"
            history_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "campaigns_registry.json").write_text(
                json.dumps(
                    {
                        "active_project": "",
                        "projects": {
                            "Projekt A": {
                                "folder_name": folder,
                                "created_at": "2026-09-01T10:00:00",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            parent = {
                "id": "20260912_120000",
                "name": "parent",
                "status": "completed",
                "training_target": "plate",
                "lineage_mode": "new",
                "output_dir": str(history_dir / "20260912_120000"),
            }
            child = {
                "id": "20260912_130000",
                "name": "child",
                "status": "running",
                "training_target": "plate",
                "lineage_mode": "fine_tune",
                "parent_run_id": parent["id"],
                "parent_model_target": "plate",
                "output_dir": str(history_dir / "20260912_130000"),
            }

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                sync_training_run(history_dir, parent)
                sync_training_run(history_dir, child)

            repo = RegistryRepository.for_workspace(workspace)
            project_id = project_id_from_folder_name(folder)
            expected_parent = registry_run_id(parent["id"], project_id=project_id, target="plate")
            expected_child = registry_run_id(child["id"], project_id=project_id, target="plate")
            child_row = repo.fetch_rows(
                "SELECT * FROM training_runs WHERE run_id = ?",
                (expected_child,),
            )[0]
            self.assertEqual(child_row["parent_run_id"], expected_parent)
            self.assertEqual(child_row["project_id"], project_id)
            project_row = repo.fetch_rows("SELECT * FROM projects")[0]
            self.assertEqual(project_row["display_name"], "Projekt A")

    def test_mismatched_current_dataset_does_not_claim_historical_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            dataset = self._dataset(workspace, image_bytes=b"snapshot")
            snapshot = build_training_dataset_snapshot(dataset, target="plate")
            (dataset / "images" / "train" / "one.jpg").write_bytes(b"changed-after-snapshot")
            history_dir = workspace / "5_training_runs" / "plates"
            run = {
                "id": "20260912_140000",
                "name": "mismatch",
                "status": "pending",
                "dataset_path": str(dataset),
                "base_model": "yolo11s-pose.pt",
                "training_target": "plate",
                "training_dataset_snapshot": snapshot,
                "input_checkpoint_snapshot": self._input_checkpoint(),
                "output_dir": str(history_dir / "20260912_140000"),
            }

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                result = sync_training_run(history_dir, run)

            repo = RegistryRepository.for_workspace(workspace)
            self.assertEqual(repo.table_count("datasets"), 1)
            self.assertEqual(repo.table_count("dataset_members"), 0)
            self.assertTrue(result.warnings)


    def test_exported_copy_reuses_model_identity_and_adds_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            dataset = self._dataset(workspace)
            snapshot = build_training_dataset_snapshot(dataset, target="plate")
            folder = "Projekt_A_ABC123"
            project_root = workspace / "9_projects" / folder
            history_dir = project_root / "5_training_runs" / "plates"
            history_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "campaigns_registry.json").write_text(
                json.dumps(
                    {
                        "active_project": "",
                        "projects": {
                            "Projekt A": {
                                "folder_name": folder,
                                "created_at": "2026-09-01T10:00:00",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                history = TrainingHistory(history_dir)
                run = history.create_run(
                    "export",
                    dataset_path=str(dataset),
                    base_model="yolo11s-pose.pt",
                    training_target="plate",
                    training_dataset_snapshot=snapshot,
                    training_dataset_input_snapshot=dict(snapshot),
                    input_checkpoint_snapshot=self._input_checkpoint(),
                )
                best = Path(run.output_dir) / "train" / "weights" / "best.pt"
                best.parent.mkdir(parents=True, exist_ok=True)
                payload = b"same-model-content"
                best.write_bytes(payload)
                digest = _sha(payload)
                history.update_run(
                    run.id,
                    status="completed",
                    finished_at="2026-09-12T15:00:00",
                    best_weights=str(best),
                    output_checkpoint_snapshot={
                        "best_checkpoint_sha256": digest,
                        "best": {"sha256": digest, "provenance_status": "complete"},
                        "provenance_status": "complete",
                    },
                )

                exported = workspace / "6_models" / "trained" / "plates" / "exported.pt"
                exported.parent.mkdir(parents=True, exist_ok=True)
                exported.write_bytes(payload)
                register_exported_model(
                    history_dir,
                    history.get_run(run.id),
                    exported,
                    target="plate",
                )

            repo = RegistryRepository.for_workspace(workspace)
            self.assertEqual(repo.table_count("models"), 1)
            self.assertEqual(repo.table_count("model_locations"), 2)
            locations = repo.fetch_rows(
                "SELECT project_id, relative_path FROM model_locations ORDER BY relative_path"
            )
            self.assertTrue(any(row["project_id"] is None for row in locations))
            project_id = project_id_from_folder_name(folder)
            self.assertTrue(any(row["project_id"] == project_id for row in locations))

    def test_history_outside_workspace_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "Workspace"
            outside = root / "outside" / "plates"
            run = {
                "id": "20260912_150000",
                "name": "outside",
                "training_target": "plate",
            }

            with patch.object(CONFIG, "WORKSPACE_DIR", workspace):
                result = sync_training_run(outside, run)

            self.assertTrue(result.skipped)
            self.assertFalse((workspace / "_registry" / "alpr_registry.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
