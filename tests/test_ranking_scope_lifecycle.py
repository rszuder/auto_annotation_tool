import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auto_annotation_tool.gui import z4_analysis_ranking as ranking
from auto_annotation_tool.gui.pz3_comparison import (
    clear_pz3_comparison_context, comparison_context, open_comparison,
    validate_comparison_context,
)
from auto_annotation_tool.registry import EvaluationTrackError, RegistryRepository
from auto_annotation_tool.registry.bootstrap import project_id_from_folder_name
from test_pz3_final_hardening import Value


class ProjectScopeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "Workspace"
        self.projects = self.workspace / "9_projects"
        self.project_a = self.projects / "Project_A"
        self.project_b = self.projects / "Project_B"
        self.global_dir = self.workspace / "6_models" / "trained" / "plates"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()
        for folder in (self.project_a, self.project_b):
            self.repo.upsert_project(
                project_id=project_id_from_folder_name(folder.name), campaign_key=folder.name,
                folder_name=folder.name, display_name=folder.name,
            )
        self.model_a = self.project_a / "6_models" / "trained" / "plates" / "A.pt"
        self.model_b = self.project_b / "6_models" / "trained" / "plates" / "B.pt"
        self.model_g = self.global_dir / "G.pt"
        self.register("MODEL-A", self.model_a, b"A", self.project_a)
        self.register("MODEL-B", self.model_b, b"B", self.project_b)
        self.register("MODEL-G", self.model_g, b"G")
        self.host = SimpleNamespace(history=None, _pz3_comparison_context=None,
                                    _get_ranking_task_target=lambda: "plate")
        self.enterContext(patch.object(ranking.CONFIG, "WORKSPACE_DIR", self.workspace))
        self.enterContext(patch.object(ranking.CONFIG, "DIR_9_PROJECTS", self.projects))
        self.enterContext(patch.object(ranking.CAMPAIGN, "get_active_project_name", return_value="Project_A"))
        self.enterContext(patch.object(ranking.CAMPAIGN, "get_active_project_root_dir", return_value=self.project_a))
        self.enterContext(patch.object(ranking.CAMPAIGN, "get_dir", return_value=None))
        self.enterContext(patch.object(ranking.CAMPAIGN, "get_global_model", return_value=""))

    def register(self, model_id, path, payload, project=None, *, location="primary"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        owner = project_id_from_folder_name(project.name) if project else None
        self.repo.upsert_model_location(
            model_id=model_id, sha256=hashlib.sha256(payload).hexdigest(), project_id=owner,
            run_id=None, target="plate", task_type="pose", yolo_family="YOLO26",
            yolo_scale="n", checkpoint_kind="trained_export", provenance_status="complete",
            created_at="2026-09-15T00:00:00", location_key=location,
            relative_path=path.relative_to(self.workspace).as_posix(), external_path=None,
            is_primary=True,
            location_project_id=owner if self.project_a in path.parents or self.project_b in path.parents else None,
        )

    def collect(self, scope):
        return ranking._collect_ranking_participant_candidates(self.host, self.global_dir, "plate", scope)

    def test_project_scope_isolation(self):
        self.assertEqual(self.collect("Projekt"), [self.model_a.resolve()])

    def test_global_scope_all_projects(self):
        self.assertEqual(set(self.collect("Globalne")),
                         {self.model_a.resolve(), self.model_b.resolve(), self.model_g.resolve()})

    def test_global_scope_deduplicates_project_and_global_copy(self):
        alias = self.global_dir / "original_A.pt"
        self.register("MODEL-A", alias, self.model_a.read_bytes(), self.project_a, location="global-copy")
        paths = self.collect("Globalne")
        self.assertEqual(len(paths), 3)
        self.assertEqual({path.read_bytes() for path in paths}, {b"A", b"B", b"G"})
        self.assertEqual(self.collect("Projekt"), [self.model_a.resolve()])

    def test_project_fallback_does_not_scan_other_projects_without_catalog(self):
        with patch.object(ranking, "ModelComparisonCatalog", side_effect=OSError("catalog unavailable")):
            self.assertEqual(self.collect("Projekt"), [self.model_a.resolve()])


class Pz3ComparisonLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / "track_A"
        self.reference.mkdir()
        self.seal = self.reference / "seal.json"
        self.seal.write_bytes(b"frozen fixture")
        self.context = dict(track_id="TRACK-A", name="Track A", target="plate",
                            reference_path=str(self.reference), model_ids=["MODEL-A"],
                            model_paths=[str(self.root / "A.pt")])
        self.host = Mock()
        self.host._pz3_comparison_context = self.context
        self.host.rank_is_running = False
        self.host.rank_cancel_requested = False
        self.host.rank_data_dir = Value(str(self.reference))
        self.host.rank_models_dir = Value("")
        self.host.rank_scope_var = Value("Globalne")
        self.host._ranking_results_modal = None
        self.host._ranking_track_modal = None
        self.host._ranking_participants_modal = None
        self.host._get_ranking_task_target.return_value = "plate"
        self.host._get_ranking_task_label.return_value = "Tablice"
        self.host._resolve_ranking_reference_source.return_value = dict(ok=True)
        self.host._begin_step4_operation.return_value = True

    def test_clear_pz3_comparison_context(self):
        frozen = copy.deepcopy(self.context)
        entries = [{"experiment_id":"EXP-A", "track_id":"TRACK-A"}]
        self.host.ranking_engine.entries = entries
        clear_pz3_comparison_context(self.host)
        self.assertIsNone(comparison_context(self.host))
        self.assertIsNone(validate_comparison_context(self.host))
        self.assertEqual(self.host.rank_data_dir.get(), "")
        self.assertEqual(self.context, frozen)
        self.assertIs(self.host.ranking_engine.entries, entries)
        self.assertEqual(self.seal.read_bytes(), b"frozen fixture")
        self.host._refresh_ranking_reference_ui.assert_called_once()
        self.host._refresh_ranking_start_state.assert_called_once()
        self.host._load_ranking.assert_called_once()

    def test_cannot_clear_pz3_context_while_running(self):
        self.host.rank_is_running = True
        with self.assertRaises(EvaluationTrackError):
            clear_pz3_comparison_context(self.host)
        self.assertIs(comparison_context(self.host), self.context)
        self.assertEqual(self.host.rank_data_dir.get(), str(self.reference))
        self.host._load_ranking.assert_not_called()

    def test_cannot_clear_while_cancellation_is_finishing(self):
        self.host.rank_cancel_requested = True
        with self.assertRaises(EvaluationTrackError):
            clear_pz3_comparison_context(self.host)
        self.assertIs(comparison_context(self.host), self.context)
        self.host._load_ranking.assert_not_called()

    def test_selectors_open_after_explicit_exit(self):
        clear_pz3_comparison_context(self.host)
        for selector in (ranking._open_ranking_track_modal, ranking._open_ranking_participants_modal):
            with self.subTest(selector=selector.__name__), \
                 patch.object(ranking.tk, "Toplevel", side_effect=RuntimeError("selector opened")) as dialog, \
                 patch.object(ranking.messagebox, "showinfo") as info:
                with self.assertRaisesRegex(RuntimeError, "selector opened"):
                    selector(self.host)
                dialog.assert_called_once()
                info.assert_not_called()

    def test_ordinary_ranking_starts_after_explicit_exit_with_another_reference(self):
        clear_pz3_comparison_context(self.host)
        self.host.rank_data_dir.set(str(self.root / "ordinary_reference"))
        with patch.object(ranking.tk, "StringVar", Value), \
             patch.object(ranking.threading, "Thread") as worker, \
             patch.object(ranking.messagebox, "showerror") as error:
            ranking._run_ranking_v2(self.host)
        worker.return_value.start.assert_called_once()
        error.assert_not_called()
        self.assertIsNone(comparison_context(self.host))

    def test_reenter_pz3_after_legacy(self):
        context_b = dict(self.context, track_id="TRACK-B", name="Track B",
                         reference_path=str(self.root / "track_B"),
                         model_ids=["MODEL-B"], model_paths=[str(self.root / "B.pt")])
        panel = Mock()
        panel.host = self.host
        panel._require_current_track.side_effect = ["TRACK-A", "TRACK-B"]
        with patch("auto_annotation_tool.gui.pz3_comparison.resolve_comparison",
                   side_effect=[self.context, context_b]), \
             patch.object(ranking, "_open_ranking_results_modal") as show:
            open_comparison(panel)
            self.assertIs(comparison_context(self.host), self.context)
            clear_pz3_comparison_context(self.host)
            open_comparison(panel)
        self.assertEqual(show.call_count, 2)
        panel._show_error.assert_not_called()
        self.assertEqual(comparison_context(self.host), context_b)
        self.assertEqual(self.host.rank_data_dir.get(), context_b["reference_path"])
        self.assertEqual(self.host.rank_scope_var.get(), "Globalne")


if __name__ == "__main__":
    unittest.main()
