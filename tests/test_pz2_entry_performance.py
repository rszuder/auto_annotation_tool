"""Regression for PZ2 entry cost and content deduplication freshness."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from auto_annotation_tool.gui import z4_analysis_ranking as ranking
from auto_annotation_tool.gui.tab_training import TrainingTab
from auto_annotation_tool.config import CONFIG, SESSION
from auto_annotation_tool.campaign_manager import CAMPAIGN


class RankingContentCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory/"model.pt"
        self.path.write_bytes(b"checkpoint-v1")
        self.cache = {}

    def key(self, path=None):
        return ranking._ranking_model_content_key(path or self.path, self.cache)

    def test_unchanged_checkpoint_is_not_read_again(self):
        expected = self.key()
        with patch.object(Path, "open", side_effect=AssertionError("duplicate read")):
            self.assertEqual(self.key(), expected)

    def test_same_size_modified_checkpoint_is_rehashed(self):
        previous = self.key()
        stamp = self.path.stat().st_mtime_ns
        self.path.write_bytes(b"checkpoint-v2")
        os.utime(self.path, ns=(stamp+1000000, stamp+1000000))
        self.assertNotEqual(self.key(), previous)
        self.assertEqual(self.key(), hashlib.sha256(b"checkpoint-v2").hexdigest())

    def test_atomic_replacement_invalidates_even_with_preserved_size_and_mtime(self):
        previous = self.key()
        stamp = self.path.stat().st_mtime_ns
        replacement = self.directory/"replacement.pt"
        replacement.write_bytes(b"checkpoint-v2")
        os.utime(replacement, ns=(stamp, stamp))
        replacement.replace(self.path)
        self.assertNotEqual(self.key(), previous)

    def test_removed_file_does_not_reuse_hash_and_reappearance_is_read(self):
        previous = self.key()
        self.path.unlink()
        self.assertTrue(self.key().startswith("path:"))
        self.assertFalse(self.cache)
        self.path.write_bytes(b"new checkpoint")
        self.assertNotEqual(self.key(), previous)

    def test_read_failure_is_not_cached(self):
        with patch.object(Path, "open", side_effect=PermissionError("busy")):
            self.assertTrue(self.key().startswith("path:"))
        self.assertFalse(self.cache)
        self.assertEqual(self.key(), hashlib.sha256(b"checkpoint-v1").hexdigest())

    def test_same_content_copies_still_deduplicate(self):
        copy = self.directory/"copy.pt"
        copy.write_bytes(self.path.read_bytes())
        self.assertEqual(self.key(), self.key(copy))

    def test_file_changed_during_hash_is_not_cached(self):
        real_sha = hashlib.sha256
        changed = False
        def new_digest():
            digest = real_sha()
            wrapper = Mock(wraps=digest)
            def update(chunk):
                nonlocal changed
                digest.update(chunk)
                if not changed:
                    changed = True
                    self.path.write_bytes(b"different-length-checkpoint")
            wrapper.update.side_effect = update
            return wrapper
        with patch.object(ranking.hashlib, "sha256", side_effect=new_digest):
            self.key()
        self.assertFalse(self.cache)
        self.assertEqual(self.key(), real_sha(self.path.read_bytes()).hexdigest())

    def test_controlled_context_bypasses_catalog_and_ui_hash_cache(self):
        host = SimpleNamespace(_pz3_comparison_context={
            "track_id":"T", "reference_path":str(self.directory),
            "model_paths":[str(self.path)], "target":"plate",
        })
        with patch.object(ranking, "ModelComparisonCatalog", side_effect=AssertionError("catalog")):
            with patch.object(ranking, "_ranking_model_content_key", side_effect=AssertionError("UI hash")):
                self.assertEqual(ranking._collect_ranking_participant_candidates(
                    host, self.directory, "plate", "Globalne"), [self.path])


class PZ2EntryRefreshTests(unittest.TestCase):
    def test_hidden_analysis_does_not_collect_models_or_read_reference(self):
        host = SimpleNamespace(
            _rank_target_syncing=False, _ranking_results_modal=None,
            _pz3_comparison_context=None,
            _is_ranking_available_for_selected_target=lambda:True,
            _is_ranking_tab_active=lambda:False,
            _get_ranking_task_target=Mock(side_effect=AssertionError("hidden refresh")),
        )
        TrainingTab._refresh_ranking_reference_ui(host)
        host._get_ranking_task_target.assert_not_called()

    def test_target_sync_traces_do_not_restart_refresh(self):
        host = SimpleNamespace(_rank_target_syncing=True)
        TrainingTab._refresh_ranking_reference_ui(host)

    def test_real_pz2_construction_defers_catalog_until_analysis_opens(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            directory = Path(temp)
            root = tk.Tk()
            root.withdraw()
            stack.callback(root.destroy)
            errors=[]
            root.report_callback_exception=lambda *args:errors.append(args)
            stack.enter_context(patch.object(CAMPAIGN,"get_active_project_name",return_value=""))
            stack.enter_context(patch.object(SESSION,"get",side_effect=lambda *args,**kw:args[2] if len(args)>2 else kw.get("default")))
            stack.enter_context(patch.object(SESSION,"set"))
            for name in ("save","_save","save_session","flush"):
                if hasattr(SESSION,name):
                    stack.enter_context(patch.object(SESSION,name))
            workspace = Path(CONFIG.WORKSPACE_DIR)
            for name,value in list(vars(CONFIG).items()):
                if isinstance(value,Path) and value.is_relative_to(workspace):
                    stack.enter_context(patch.object(CONFIG,name,directory/value.relative_to(workspace)))
            stack.enter_context(patch.object(CONFIG,"DIR_9_PROJECTS",directory/"projects"))
            for method in ("get_training_runs_dir","get_datasets_dir","get_models_dir","get_ranking_dir"):
                if hasattr(CONFIG,method):
                    stack.enter_context(patch.object(CONFIG,method,side_effect=lambda target="plate",method=method:directory/method/target))
            stack.enter_context(patch.object(TrainingTab,"_get_free_dataset_variant_choices",return_value=[]))
            collect=stack.enter_context(patch.object(ranking,"_collect_ranking_participant_candidates",return_value=[]))
            notebook=ttk.Notebook(root)
            app=SimpleNamespace(root=root,palette={},get_available_yolo_device_profiles=lambda:[],
                                notify_free_mode_assistant_context_changed=lambda:None)
            host=TrainingTab(notebook,app)
            notebook.add(host.frame,text="Z4")
            self.assertTrue(host._ensure_step4_train_tab_built())
            host.main_nb.select(host.tab_train)
            root.update()
            collect.assert_not_called()
            self.assertEqual(str(host.btn_run_rank.cget("state")), "disabled")
            # Direct PZ3 entry may be the first use of this lazy analysis view.
            reference = str(directory/"frozen-track")
            host._pz3_comparison_context = {
                "track_id":"T", "name":"Frozen", "target":"plate",
                "reference_path":reference, "model_paths":[str(directory/"M.pt")], "model_ids":["M"],
            }
            host.rank_data_dir.set(reference)
            self.assertEqual(host.rank_data_dir.get(),reference)
            self.assertEqual(host._analysis_role_banner.title.cget("text"), "Eksperyment kontrolowany")
            host._pz3_comparison_context=None
            host.rank_data_dir.set("")
            collect.reset_mock()
            host.right_nb.select(host.ranking_tab)
            root.update()
            self.assertGreater(collect.call_count,0)
            self.assertEqual(str(host.btn_run_rank.cget("state")), "disabled")
            host.right_nb.select(host.hist_tab)
            root.update()
            host.rank_models_dir.set(str(directory/"new-models"))
            host.rank_data_dir.set("")
            collect.reset_mock()
            host.right_nb.select(host.ranking_tab)
            root.update()
            collect.assert_called()
            self.assertEqual(host.rank_models_dir.get(),str(directory/"new-models"))
            self.assertFalse(errors,errors)


if __name__ == "__main__":
    unittest.main()
