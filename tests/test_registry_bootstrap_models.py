import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.bootstrap import (
    bootstrap_workspace_registry,
    project_id_from_folder_name,
    registry_run_id,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RegistryBootstrapRunsAndModelsTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "Workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _project(
        self,
        workspace: Path,
        *,
        name: str = "Projekt A",
        folder: str = "Projekt_A_ABC123",
        append: bool = False,
    ) -> Path:
        registry_path = workspace / "campaigns_registry.json"
        payload = {"active_project": "", "projects": {}}
        if append and registry_path.exists():
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        payload["projects"][name] = {
            "folder_name": folder,
            "created_at": "2026-09-01T10:00:00",
        }
        registry_path.write_text(json.dumps(payload), encoding="utf-8")
        root = workspace / "9_projects" / folder
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _history(
        self,
        runs_root: Path,
        target_dir: str,
        runs: dict,
    ) -> Path:
        history_dir = runs_root / target_dir
        history_dir.mkdir(parents=True, exist_ok=True)
        path = history_dir / "training_history.json"
        path.write_text(
            json.dumps({"version": "1.0", "runs": runs}),
            encoding="utf-8",
        )
        return path

    def _run(
        self,
        run_id: str,
        *,
        target: str,
        output_sha: str,
        parent_run_id: str = "",
        scale: str = "s",
    ) -> dict:
        return {
            "id": run_id,
            "name": f"run {run_id}",
            "created_at": "2026-09-01T10:00:00",
            "started_at": "2026-09-01T10:01:00",
            "finished_at": "2026-09-01T10:10:00",
            "status": "completed",
            "dataset_path": "",
            "base_model": f"yolo11{scale}-pose.pt" if target == "plate" else f"yolo11{scale}.pt",
            "epochs": 10,
            "batch_size": 4,
            "img_size": 640,
            "device": "cpu",
            "lr0": 0.01,
            "training_target": target,
            "lineage_mode": "fine_tune" if parent_run_id else "new",
            "parent_run_id": parent_run_id,
            "training_dataset_snapshot": {
                "dataset_id": f"DS-{'MT' if target == 'plate' else 'MZ'}-{run_id[-6:]}",
                "name": f"dataset_{run_id}",
                "target": target,
                "manifest_sha256": "a" * 64,
                "split_sha256": "b" * 64,
                "provenance_status": "complete",
                "snapshot_source": "frozen_at_training_start",
            },
            "input_checkpoint_snapshot": {
                "sha256": "c" * 64,
                "provenance_status": "complete",
            },
            "output_checkpoint_snapshot": {
                "best_checkpoint_sha256": output_sha,
                "best": {
                    "sha256": output_sha,
                    "provenance_status": "complete",
                },
                "provenance_status": "complete",
            },
        }

    def _model_sidecar(
        self,
        model: Path,
        *,
        task: str = "pose",
        family: str = "YOLO11",
        scale: str = "s",
    ) -> None:
        stat = model.stat()
        path = model.with_suffix(".pt.metadata.json")
        path.write_text(
            json.dumps(
                {
                    "schema": "auto_annotation_tool.model_metadata.v1",
                    "model": {
                        "file_name": model.name,
                        "path": str(model),
                        "fingerprint": {
                            "file_name": model.name,
                            "path": str(model),
                            "size": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns,
                        },
                        "validation_ok": True,
                        "validation_message": "OK",
                        "info": {
                            "task": task,
                            "yolo_family": family,
                            "yolo_size": scale,
                            "architecture_label": f"{family}{scale} {'Pose' if task == 'pose' else 'Detect'}",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_project_run_and_exported_model_are_linked_by_checkpoint_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            project_root = self._project(workspace)

            model_bytes = b"trained-model"
            model_sha = _sha(model_bytes)
            run_id = "20260901_100100"
            run = self._run(
                run_id,
                target="plate",
                output_sha=model_sha,
                scale="s",
            )
            self._history(
                project_root / "5_training_runs",
                "plates",
                {run_id: run},
            )

            model = (
                project_root
                / "6_models"
                / "trained"
                / "plates"
                / f"plate_{run_id}_map90.pt"
            )
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_bytes(model_bytes)
            self._model_sidecar(model, task="pose", scale="s")

            report = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)

            self.assertEqual(report.training_runs_registered, 1)
            self.assertEqual(report.models_registered, 1)
            self.assertEqual(report.model_locations_registered, 1)
            self.assertEqual(repo.table_count("training_runs"), 1)
            self.assertEqual(repo.table_count("models"), 1)
            self.assertEqual(repo.table_count("model_locations"), 1)
            self.assertEqual(repo.table_count("datasets"), 1)

            project_id = project_id_from_folder_name("Projekt_A_ABC123")
            expected_run_id = registry_run_id(
                run_id,
                project_id=project_id,
                target="plate",
            )
            model_row = repo.fetch_rows(
                "SELECT * FROM models"
            )[0]
            self.assertEqual(model_row["run_id"], expected_run_id)
            self.assertEqual(model_row["project_id"], project_id)
            self.assertEqual(model_row["target"], "plate")
            self.assertEqual(model_row["task_type"], "pose")
            self.assertEqual(model_row["yolo_family"], "YOLO11")
            self.assertEqual(model_row["yolo_scale"], "s")
            self.assertEqual(model_row["provenance_status"], "complete")

    def test_identical_model_copy_has_one_model_and_two_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            project_root = self._project(workspace)

            model_bytes = b"same-model"
            global_model = workspace / "6_models" / "trained" / "plates" / "copy.pt"
            project_model = project_root / "6_models" / "trained" / "plates" / "copy.pt"
            global_model.parent.mkdir(parents=True, exist_ok=True)
            project_model.parent.mkdir(parents=True, exist_ok=True)
            global_model.write_bytes(model_bytes)
            project_model.write_bytes(model_bytes)

            report = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)

            self.assertEqual(report.models_discovered, 2)
            self.assertEqual(report.models_registered, 1)
            self.assertEqual(report.model_locations_registered, 2)
            self.assertEqual(repo.table_count("models"), 1)
            self.assertEqual(repo.table_count("model_locations"), 2)

    def test_same_source_run_id_in_two_projects_does_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            project_a = self._project(
                workspace,
                name="A",
                folder="A_AAAAAA",
            )
            project_b = self._project(
                workspace,
                name="B",
                folder="B_BBBBBB",
                append=True,
            )

            raw_id = "20260901_101010"
            self._history(
                project_a / "5_training_runs",
                "plates",
                {
                    raw_id: self._run(
                        raw_id,
                        target="plate",
                        output_sha="1" * 64,
                    )
                },
            )
            self._history(
                project_b / "5_training_runs",
                "plates",
                {
                    raw_id: self._run(
                        raw_id,
                        target="plate",
                        output_sha="2" * 64,
                    )
                },
            )

            report = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)

            self.assertEqual(report.training_runs_registered, 2)
            rows = repo.fetch_rows(
                "SELECT run_id, project_id FROM training_runs ORDER BY project_id"
            )
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]["run_id"], rows[1]["run_id"])

    def test_fine_tune_parent_is_linked_after_all_runs_are_inserted(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            project_root = self._project(workspace)
            parent_id = "20260901_090000"
            child_id = "20260901_100000"

            parent = self._run(
                parent_id,
                target="plate",
                output_sha="1" * 64,
            )
            child = self._run(
                child_id,
                target="plate",
                output_sha="2" * 64,
                parent_run_id=parent_id,
            )
            self._history(
                project_root / "5_training_runs",
                "plates",
                {
                    child_id: child,
                    parent_id: parent,
                },
            )

            bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)
            project_id = project_id_from_folder_name("Projekt_A_ABC123")
            expected_parent = registry_run_id(
                parent_id,
                project_id=project_id,
                target="plate",
            )
            expected_child = registry_run_id(
                child_id,
                project_id=project_id,
                target="plate",
            )
            child_row = repo.fetch_rows(
                "SELECT * FROM training_runs WHERE run_id = ?",
                (expected_child,),
            )[0]
            self.assertEqual(child_row["parent_run_id"], expected_parent)

    def test_legacy_base_model_without_run_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            model = (
                workspace
                / "6_models"
                / "base"
                / "pose"
                / "yolo11n-pose.pt"
            )
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_bytes(b"official-base-fixture")

            report = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)

            self.assertEqual(report.models_registered, 1)
            row = repo.fetch_rows("SELECT * FROM models")[0]
            self.assertIsNone(row["run_id"])
            self.assertEqual(row["target"], "plate")
            self.assertEqual(row["task_type"], "pose")
            self.assertEqual(row["yolo_family"], "YOLO11")
            self.assertEqual(row["yolo_scale"], "n")
            self.assertEqual(row["checkpoint_kind"], "base")
            self.assertEqual(row["provenance_status"], "legacy_unknown")

    def test_runs_and_models_bootstrap_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            project_root = self._project(workspace)
            run_id = "20260901_110000"
            model_bytes = b"idempotent-model"
            model_sha = _sha(model_bytes)

            self._history(
                project_root / "5_training_runs",
                "plates",
                {
                    run_id: self._run(
                        run_id,
                        target="plate",
                        output_sha=model_sha,
                    )
                },
            )
            model = (
                project_root
                / "6_models"
                / "trained"
                / "plates"
                / f"plate_{run_id}_map90.pt"
            )
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_bytes(model_bytes)

            bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)
            before = {
                name: repo.table_count(name)
                for name in (
                    "datasets",
                    "training_runs",
                    "models",
                    "model_locations",
                )
            }

            bootstrap_workspace_registry(workspace)
            after = {
                name: repo.table_count(name)
                for name in before
            }

            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
