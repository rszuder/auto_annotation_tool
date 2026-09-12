import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.ranking.comparison_catalog import (
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
    ModelComparisonCatalog,
    active_project_id_from_root,
    comparison_scope_label,
    normalize_comparison_scope,
)
from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.bootstrap import (
    project_id_from_folder_name,
)


class ModelComparisonCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()

        self.project_a_root = (
            self.workspace / "9_projects" / "alpha"
        )
        self.project_b_root = (
            self.workspace / "9_projects" / "beta"
        )
        self.project_a_root.mkdir(parents=True)
        self.project_b_root.mkdir(parents=True)
        self.project_a = project_id_from_folder_name("alpha")
        self.project_b = project_id_from_folder_name("beta")

        self.repo.upsert_project(
            project_id=self.project_a,
            campaign_key="alpha",
            folder_name="alpha",
            display_name="Alpha",
        )
        self.repo.upsert_project(
            project_id=self.project_b,
            campaign_key="beta",
            folder_name="beta",
            display_name="Beta",
        )
        self.catalog = ModelComparisonCatalog(
            self.workspace,
            repository=self.repo,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _add_model(
        self,
        model_id,
        sha,
        *,
        target="plate",
        owner_project_id=None,
        locations=(),
    ):
        for index, item in enumerate(locations):
            path = Path(item["path"])
            if item.get("create", True):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    item.get("payload", model_id.encode("utf-8"))
                )
            try:
                relative = path.resolve().relative_to(
                    self.workspace.resolve()
                ).as_posix()
                external = None
            except Exception:
                relative = None
                external = str(path)

            self.repo.upsert_model_location(
                model_id=model_id,
                sha256=sha,
                project_id=owner_project_id,
                run_id=None,
                target=target,
                task_type="pose" if target == "plate" else "detect",
                yolo_family="yolo11",
                yolo_scale="n",
                checkpoint_kind="trained_export",
                provenance_status="complete",
                created_at="2026-01-01T00:00:00",
                location_key=f"{model_id}-{index}",
                relative_path=relative,
                external_path=external,
                is_primary=bool(item.get("primary", True)),
                location_project_id=item.get("project_id"),
            )

    def test_active_project_id_comes_from_project_folder(self):
        self.assertEqual(
            active_project_id_from_root(self.project_a_root),
            self.project_a,
        )

    def test_project_scope_requires_active_project(self):
        self._add_model(
            "MODEL-A",
            "a" * 64,
            owner_project_id=self.project_a,
            locations=(
                {
                    "path": self.project_a_root / "6_models" / "a.pt",
                    "project_id": self.project_a,
                },
            ),
        )
        rows = self.catalog.list_candidates(
            target="plate",
            scope=SCOPE_PROJECT,
        )
        self.assertEqual(rows, [])

    def test_project_scope_contains_only_active_project_models(self):
        self._add_model(
            "MODEL-A",
            "a" * 64,
            owner_project_id=self.project_a,
            locations=(
                {
                    "path": self.project_a_root / "6_models" / "a.pt",
                    "project_id": self.project_a,
                },
            ),
        )
        self._add_model(
            "MODEL-B",
            "b" * 64,
            owner_project_id=self.project_b,
            locations=(
                {
                    "path": self.project_b_root / "6_models" / "b.pt",
                    "project_id": self.project_b,
                },
            ),
        )
        rows = self.catalog.list_candidates(
            target="plate",
            scope=SCOPE_PROJECT,
            active_project_root=self.project_a_root,
        )
        self.assertEqual(
            [row.model_id for row in rows],
            ["MODEL-A"],
        )

    def test_workspace_scope_contains_models_from_all_projects(self):
        self._add_model(
            "MODEL-A",
            "a" * 64,
            owner_project_id=self.project_a,
            locations=(
                {
                    "path": self.project_a_root / "6_models" / "a.pt",
                    "project_id": self.project_a,
                },
            ),
        )
        self._add_model(
            "MODEL-B",
            "b" * 64,
            owner_project_id=self.project_b,
            locations=(
                {
                    "path": self.project_b_root / "6_models" / "b.pt",
                    "project_id": self.project_b,
                },
            ),
        )
        rows = self.catalog.list_candidates(
            target="plate",
            scope=SCOPE_WORKSPACE,
        )
        self.assertEqual(
            {row.model_id for row in rows},
            {"MODEL-A", "MODEL-B"},
        )

    def test_workspace_scope_prefers_global_location(self):
        project_path = self.project_a_root / "6_models" / "a.pt"
        global_path = (
            self.workspace
            / "6_models"
            / "trained"
            / "plates"
            / "a.pt"
        )
        self._add_model(
            "MODEL-A",
            "a" * 64,
            owner_project_id=self.project_a,
            locations=(
                {
                    "path": project_path,
                    "project_id": self.project_a,
                },
                {
                    "path": global_path,
                    "project_id": None,
                },
            ),
        )
        row = self.catalog.list_candidates(
            target="plate",
            scope=SCOPE_WORKSPACE,
        )[0]
        self.assertEqual(row.path.resolve(), global_path.resolve())

    def test_project_scope_prefers_project_location(self):
        project_path = self.project_a_root / "6_models" / "a.pt"
        global_path = (
            self.workspace
            / "6_models"
            / "trained"
            / "plates"
            / "a.pt"
        )
        self._add_model(
            "MODEL-A",
            "a" * 64,
            owner_project_id=self.project_a,
            locations=(
                {
                    "path": global_path,
                    "project_id": None,
                },
                {
                    "path": project_path,
                    "project_id": self.project_a,
                },
            ),
        )
        row = self.catalog.list_candidates(
            target="plate",
            scope=SCOPE_PROJECT,
            active_project_root=self.project_a_root,
        )[0]
        self.assertEqual(row.path.resolve(), project_path.resolve())

    def test_target_filter_is_shared_by_both_scopes(self):
        self._add_model(
            "MODEL-MT",
            "a" * 64,
            target="plate",
            owner_project_id=self.project_a,
            locations=(
                {
                    "path": self.project_a_root / "6_models" / "mt.pt",
                    "project_id": self.project_a,
                },
            ),
        )
        self._add_model(
            "MODEL-MZ",
            "b" * 64,
            target="char",
            owner_project_id=self.project_a,
            locations=(
                {
                    "path": self.project_a_root / "6_models" / "mz.pt",
                    "project_id": self.project_a,
                },
            ),
        )
        rows = self.catalog.list_candidates(
            target="char",
            scope=SCOPE_WORKSPACE,
        )
        self.assertEqual(
            [row.model_id for row in rows],
            ["MODEL-MZ"],
        )

    def test_missing_locations_are_not_offered(self):
        missing = self.workspace / "6_models" / "missing.pt"
        self._add_model(
            "MODEL-MISSING",
            "c" * 64,
            locations=(
                {
                    "path": missing,
                    "project_id": None,
                    "create": False,
                },
            ),
        )
        self.assertEqual(
            self.catalog.list_candidates(
                target="plate",
                scope=SCOPE_WORKSPACE,
            ),
            [],
        )

    def test_scope_normalization_and_labels(self):
        self.assertEqual(
            normalize_comparison_scope(
                SCOPE_PROJECT,
                has_active_project=False,
            ),
            SCOPE_WORKSPACE,
        )
        self.assertEqual(
            comparison_scope_label(SCOPE_PROJECT, "plate"),
            "Projektowe MT",
        )
        self.assertEqual(
            comparison_scope_label(SCOPE_WORKSPACE, "char"),
            "Workspace MZ",
        )


if __name__ == "__main__":
    unittest.main()
