import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auto_annotation_tool.gui import z4_analysis_ranking as ranking
from auto_annotation_tool.gui import z4_training_runtime as runtime
from auto_annotation_tool.gui.pz3_comparison import comparison_context, validate_comparison_context
from auto_annotation_tool.registry import EvaluationTrackError


class Value:
    def __init__(self, value=""):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class ComparisonContextHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / "sealed"
        self.reference.mkdir()
        self.models = [self.root / "n.pt", self.root / "s.pt"]
        for i, model in enumerate(self.models):
            model.write_bytes(str(i).encode())
        self.context = dict(track_id="TRK-FROZEN", name="MT n vs s", target="plate",
                            reference_path=str(self.reference), model_paths=list(map(str, self.models)),
                            model_ids=["M1", "M2"])
        self.host = Mock()
        self.host._pz3_comparison_context = self.context
        self.host.rank_data_dir = Value(str(self.reference))
        self.host.rank_models_dir = Value("")
        self.host.rank_scope_var = Value("Globalne")
        self.host.rank_is_running = False
        self.host._get_ranking_task_target.return_value = "plate"
        self.host._get_ranking_task_label.return_value = "Tablice"
        self.host._resolve_ranking_reference_source.return_value = dict(ok=True)
        self.host._begin_step4_operation.return_value = True
        self.host._collect_ranking_participant_candidates.return_value = list(self.models)
        self.host._ui.side_effect = lambda callback: callback()

    def test_track_selector_is_locked_even_after_path_tampering(self):
        for path in (str(self.reference), str(self.root / "other")):
            with self.subTest(path=path), patch.object(ranking.messagebox, "showinfo") as info, \
                 patch.object(ranking.tk, "Toplevel") as dialog:
                self.host.rank_data_dir.set(path)
                ranking._open_ranking_track_modal(self.host)
                dialog.assert_not_called()
                self.assertIn("TRK-FROZEN", info.call_args.args[1])
                self.assertIs(comparison_context(self.host), self.context)

    def test_participant_selector_stays_locked_after_path_tampering(self):
        self.host.rank_data_dir.set(str(self.root / "other"))
        with patch.object(ranking.messagebox, "showinfo") as info, patch.object(ranking.tk, "Toplevel") as dialog:
            ranking._open_ranking_participants_modal(self.host)
        dialog.assert_not_called()
        self.assertIn("M1", info.call_args.args[1])

    def test_manual_reference_change_or_clear_refuses_start_before_engine(self):
        for path in (str(self.root / "other"), ""):
            with self.subTest(path=path), patch.object(ranking.messagebox, "showerror") as error, \
                 patch.object(ranking.threading, "Thread") as thread:
                self.host.rank_data_dir.set(path)
                ranking._run_ranking_v2(self.host)
                self.assertIn("kontekst", error.call_args.args[0].lower())
                thread.assert_not_called()
                self.host._ensure_plate_ranking_engine.assert_not_called()
                self.assertFalse(self.host.rank_is_running)

    def test_valid_reference_starts_worker(self):
        self.host.rank_data_dir.set(str(self.reference / ".." / "sealed"))
        with patch.object(ranking.tk, "StringVar", Value), \
             patch.object(ranking.threading, "Thread") as thread, \
             patch.object(ranking.messagebox, "showerror") as error:
            ranking._run_ranking_v2(self.host)
        error.assert_not_called()
        thread.return_value.start.assert_called_once()
        self.host._begin_step4_operation.assert_called_once()
        self.assertTrue(self.host.rank_is_running)

    def test_ordinary_ranking_can_open_track_selector(self):
        self.host._pz3_comparison_context = None
        self.host._ranking_track_modal = None
        with patch.object(ranking.tk, "Toplevel", side_effect=RuntimeError("selector reached")) as dialog, \
             patch.object(ranking.messagebox, "showinfo") as info:
            with self.assertRaisesRegex(RuntimeError, "selector reached"):
                ranking._open_ranking_track_modal(self.host)
        dialog.assert_called_once()
        info.assert_not_called()
        self.assertIsNone(validate_comparison_context(self.host))

    def test_model_set_must_match_exactly(self):
        for models in (self.models[:1], self.models + [self.models[0]], [self.root / "replacement.pt", self.models[1]]):
            with self.subTest(models=models), self.assertRaises(EvaluationTrackError):
                validate_comparison_context(self.host, model_paths=models)
        self.assertIs(validate_comparison_context(self.host, model_paths=list(reversed(self.models))), self.context)

    def test_worker_refuses_changed_models_before_bridge_or_inference(self):
        self.host._collect_ranking_participant_candidates.return_value = [self.root / "replacement.pt"]
        with patch.object(ranking.tk, "StringVar", Value), \
             patch.object(ranking.threading, "Thread") as thread, \
             patch.object(ranking, "RankingExperimentBridge") as bridge, \
             patch("auto_annotation_tool.annotators.runtime_factory.create_plate_annotator") as annotator, \
             patch.object(ranking.messagebox, "showerror") as error:
            ranking._run_ranking_v2(self.host)
            thread.call_args.kwargs["target"]()
        bridge.assert_not_called()
        annotator.assert_not_called()
        self.assertIn("lista modeli", error.call_args.args[1])
        self.assertFalse(self.host.rank_is_running)

    def test_worker_rechecks_reference_after_start(self):
        with patch.object(ranking.tk, "StringVar", Value), \
             patch.object(ranking.threading, "Thread") as thread, \
             patch.object(ranking, "RankingExperimentBridge") as bridge, \
             patch.object(ranking.messagebox, "showerror") as error:
            ranking._run_ranking_v2(self.host)
            self.host.rank_data_dir.set(str(self.root / "other"))
            thread.call_args.kwargs["target"]()
        bridge.assert_not_called()
        self.assertIn("zapieczętowany tor", error.call_args.args[1])

    def test_controlled_context_cannot_use_legacy_bridge_result(self):
        self.host._get_effective_training_device_profile.return_value = ("cpu", None)
        with patch.object(ranking.tk, "StringVar", Value), \
             patch.object(ranking.threading, "Thread") as thread, \
             patch.object(ranking, "RankingExperimentBridge") as bridge, \
             patch("auto_annotation_tool.annotators.runtime_factory.create_plate_annotator") as annotator, \
             patch.object(ranking.messagebox, "showerror") as error:
            bridge.return_value.prepare.return_value = None
            ranking._run_ranking_v2(self.host)
            thread.call_args.kwargs["target"]()
        annotator.assert_not_called()
        self.assertIn("zapieczętowanego toru", error.call_args.args[1])
        self.assertFalse(self.host.rank_is_running)


class RankingCollectorsHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first = self.root / "plate_yolo26n-pose.pt"
        self.copy = self.root / "plate_copy_yolo26n-pose.pt"
        self.other = self.root / "plate_yolo26s-pose.pt"
        self.first.write_bytes(b"checkpoint-n")
        self.copy.write_bytes(self.first.read_bytes())
        self.other.write_bytes(b"checkpoint-s")
        self.host = SimpleNamespace(_get_ranking_task_target=lambda: "plate")

    def test_legacy_collector_returns_models_and_deduplicates_content(self):
        with patch.object(ranking, "_collect_project_ranking_model_candidates", return_value=[]), \
             patch.object(ranking, "is_plate_pose_model_path", return_value=True):
            paths = ranking._collect_ranking_model_candidates(self.host, self.root)
        self.assertEqual(len(paths), 2)
        self.assertEqual({path.read_bytes() for path in paths}, {b"checkpoint-n", b"checkpoint-s"})

    def test_project_alias_and_directory_copy_share_one_candidate(self):
        with patch.object(ranking, "_collect_project_ranking_model_candidates", return_value=[self.copy]), \
             patch.object(ranking, "is_plate_pose_model_path", return_value=True):
            paths = ranking._collect_ranking_model_candidates(self.host, self.root)
        self.assertEqual(len(paths), 2)

    def test_content_key_uses_sha_and_per_collection_cache(self):
        cache = {}
        expected = hashlib.sha256(self.first.read_bytes()).hexdigest()
        self.assertEqual(ranking._ranking_model_content_key(self.first, cache), expected)
        with patch.object(Path, "open", side_effect=AssertionError("cached file read twice")):
            self.assertEqual(ranking._ranking_model_content_key(self.first, cache), expected)
        self.assertEqual(ranking._ranking_model_content_key(self.copy), expected)

    def test_global_scope_lists_project_candidates_without_extra_directory(self):
        host = Mock()
        host._pz3_comparison_context = None
        host.ranking_engine.get_unique_entries.return_value = []
        host.rank_tree.get_children.return_value = []
        host._resolve_ranking_reference_source.return_value = {}
        host._get_ranking_task_target.return_value = "plate"
        host._get_ranking_task_label.return_value = "Tablice"
        host._get_ranking_scope.return_value = "Globalne"
        host.rank_models_dir = Value("")
        host._collect_ranking_participant_candidates.return_value = [self.first]
        host._collect_project_ranking_model_candidates.return_value = [self.first]
        host._filter_enabled_ranking_participants.side_effect = lambda paths: paths
        host._resolve_training_run_from_model_path.return_value = None
        host.app.palette = {}
        with patch.object(runtime.CAMPAIGN, "get_active_project_name", return_value="project"), \
             patch.object(runtime.CAMPAIGN, "get_active_project_root_dir", return_value=self.root):
            runtime._load_ranking(host)
        host._collect_ranking_participant_candidates.assert_called_once_with(None, "plate", "Globalne")
        host.rank_tree.insert.assert_called_once()
        self.assertIn("czeka na test", host.rank_tree.insert.call_args.kwargs["values"])

    def test_legacy_all_scope_is_normalized_to_global(self):
        host = SimpleNamespace(rank_scope_var=Value("Wszystkie"))
        with patch.object(ranking.CAMPAIGN, "get_active_project_name", return_value="project"):
            self.assertEqual(ranking._get_ranking_scope(host), "Globalne")


if __name__ == "__main__":
    unittest.main()
