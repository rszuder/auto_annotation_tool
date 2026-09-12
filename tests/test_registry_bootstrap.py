import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import (
    RegistryRepository,
    bootstrap_workspace_registry,
    project_id_from_folder_name,
)


class RegistryBootstrapTests(unittest.TestCase):
    def _write_dataset(
        self,
        root: Path,
        *,
        image_bytes: bytes = b"image",
    ) -> Path:
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
            "names: [sample]\n",
            encoding="utf-8",
        )
        (root / "dataset_manifest.json").write_text(
            json.dumps({"source_images": 1}),
            encoding="utf-8",
        )
        return root

    def _write_project_registry(
        self,
        workspace: Path,
        *,
        name: str = "Projekt A",
        folder_name: str = "Projekt_A_ABC123",
    ) -> Path:
        (workspace / "9_projects" / folder_name).mkdir(parents=True, exist_ok=True)
        (workspace / "campaigns_registry.json").write_text(
            json.dumps(
                {
                    "active_project": "",
                    "projects": {
                        name: {
                            "folder_name": folder_name,
                            "created_at": "2026-09-01T10:00:00",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return workspace / "9_projects" / folder_name

    def test_bootstrap_indexes_global_and_project_datasets(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            global_dataset = self._write_dataset(
                workspace / "4_training_datasets" / "plates" / "global_set",
                image_bytes=b"global",
            )
            project_root = self._write_project_registry(workspace)
            project_dataset = self._write_dataset(
                project_root / "4_training_datasets" / "chars" / "project_set",
                image_bytes=b"project",
            )

            report = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)

            self.assertEqual(report.projects_registered, 1)
            self.assertEqual(report.datasets_registered, 2)
            self.assertEqual(report.warnings, [])
            self.assertEqual(repo.table_count("projects"), 1)
            self.assertEqual(repo.table_count("datasets"), 2)
            self.assertEqual(repo.table_count("dataset_locations"), 2)
            self.assertEqual(repo.table_count("source_images"), 2)
            self.assertEqual(repo.table_count("image_artifacts"), 2)
            self.assertEqual(repo.table_count("dataset_members"), 2)

            project_id = project_id_from_folder_name("Projekt_A_ABC123")
            project_rows = repo.fetch_rows(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            )
            self.assertEqual(len(project_rows), 1)
            self.assertEqual(project_rows[0]["display_name"], "Projekt A")

            locations = repo.fetch_rows(
                """
                SELECT project_id, relative_path
                FROM dataset_locations
                ORDER BY relative_path
                """
            )
            self.assertEqual(len(locations), 2)
            self.assertTrue(
                any(row["project_id"] is None for row in locations)
            )
            self.assertTrue(
                any(row["project_id"] == project_id for row in locations)
            )

    def test_bootstrap_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            self._write_dataset(
                workspace / "4_training_datasets" / "plates" / "set_a"
            )
            self._write_project_registry(workspace)

            first = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)
            counts_before = {
                table: repo.table_count(table)
                for table in (
                    "projects",
                    "datasets",
                    "dataset_locations",
                    "source_images",
                    "image_artifacts",
                    "dataset_members",
                )
            }

            second = bootstrap_workspace_registry(workspace)
            counts_after = {
                table: repo.table_count(table)
                for table in counts_before
            }

            self.assertEqual(first.datasets_registered, 1)
            self.assertEqual(second.datasets_registered, 1)
            self.assertEqual(counts_before, counts_after)

    def test_identical_dataset_copy_gets_two_locations_but_one_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            self._write_dataset(
                workspace / "4_training_datasets" / "plates" / "same",
                image_bytes=b"same",
            )
            project_root = self._write_project_registry(workspace)
            self._write_dataset(
                project_root / "4_training_datasets" / "plates" / "same",
                image_bytes=b"same",
            )

            report = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)

            self.assertEqual(report.datasets_registered, 2)
            self.assertEqual(repo.table_count("datasets"), 1)
            self.assertEqual(repo.table_count("dataset_locations"), 2)
            self.assertEqual(repo.table_count("source_images"), 1)
            self.assertEqual(repo.table_count("image_artifacts"), 1)
            self.assertEqual(repo.table_count("dataset_members"), 1)

    def test_missing_project_directory_is_reported_but_project_stays_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            (workspace / "campaigns_registry.json").parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            (workspace / "campaigns_registry.json").write_text(
                json.dumps(
                    {
                        "active_project": "",
                        "projects": {
                            "Missing": {
                                "folder_name": "Missing_ABC123",
                                "created_at": "2026-09-01T10:00:00",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = bootstrap_workspace_registry(workspace)
            repo = RegistryRepository.for_workspace(workspace)

            self.assertEqual(report.projects_registered, 1)
            self.assertEqual(repo.table_count("projects"), 1)
            self.assertTrue(
                any("brak katalogu" in warning for warning in report.warnings)
            )


if __name__ == "__main__":
    unittest.main()
