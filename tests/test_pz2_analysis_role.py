from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from auto_annotation_tool.gui import z4_analysis_ranking as ranking
from auto_annotation_tool.gui.z4_analysis_role import AnalysisRoleBanner, analysis_role, open_pz3_tracks
from auto_annotation_tool.gui.z4_shared_ui import refresh_step4_analysis_tab_visibility
from auto_annotation_tool.gui.tab_training import TrainingTab
from auto_annotation_tool.ranking import ModelRanking
from auto_annotation_tool.registry import EvaluationTrackError
from test_pz3_final_hardening import Value


def context_for(reference, paths):
    return dict(track_id="TRACK-PZ3",name="MT-n vs MT-s",target="plate",
                reference_path=str(reference),model_ids=["M1","M2"],model_paths=list(map(str,paths)))


class AnalysisRoleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared_root=tk.Tk()
        cls.shared_root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.shared_root.destroy()

    def tearDown(self):
        self.root.update_idletasks()
        for child in list(self.root.winfo_children()):
            child.destroy()
        self.root.withdraw()

    def setUp(self):
        self.root=self.shared_root
        self.root.withdraw()
        self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.addCleanup(lambda:self.assertFalse(self.errors))
        self.host=SimpleNamespace(_pz3_comparison_context=None,
            _ensure_step4_tracks_tab_built=Mock(),main_nb=ttk.Notebook(self.root),
            _ranking_results_modal=None)
        self.host.tab_train=ttk.Frame(self.host.main_nb)
        self.host.tab_tracks=ttk.Frame(self.host.main_nb)
        self.host.main_nb.add(self.host.tab_train,text="PZ2")
        self.host.main_nb.add(self.host.tab_tracks,text="PZ3")
        self.banner=AnalysisRoleBanner(self.host,self.root)
        self.banner.frame.pack()
        self.root.update()

    def test_pz2_standalone_shows_working_analysis_banner(self):
        self.assertEqual(self.banner.title.cget("text"),"Analiza robocza modeli")
        self.assertEqual(self.banner.status.cget("text"),"Tryb roboczy — bez pieczęci PZ3")
        self.assertIn("nie stanowią",self.banner.description.cget("text"))

    def test_pz2_standalone_cta_routes_to_existing_pz3_tab(self):
        self.banner.button.invoke()
        self.host._ensure_step4_tracks_tab_built.assert_called_once()
        self.assertEqual(self.host.main_nb.select(),str(self.host.tab_tracks))
        self.assertEqual(len(self.host.main_nb.tabs()),2)
        self.assertIsNone(self.host._pz3_comparison_context)

    def test_pz3_route_closes_results_window_without_clearing_context(self):
        self.host._pz3_comparison_context=context_for("reference",["a.pt","b.pt"])
        before=self.host._pz3_comparison_context
        self.host._ranking_results_modal=object()
        self.host._ranking_results_modal_close=Mock()
        open_pz3_tracks(self.host)
        self.host._ranking_results_modal_close.assert_called_once()
        self.assertIs(self.host._pz3_comparison_context,before)

    def test_pz3_context_shows_controlled_badge_and_counts(self):
        self.host._pz3_comparison_context=context_for("reference",["a.pt","b.pt"])
        self.banner.refresh({"image_count":1000})
        self.assertEqual(self.banner.title.cget("text"),"Eksperyment kontrolowany")
        self.assertEqual(self.banner.status.cget("text"),"CONTROLLED / SEALED")
        text=self.banner.description.cget("text")
        for expected in ("TRACK-PZ3","MT-n vs MT-s","1000 obrazów","2 uczestników"):
            self.assertIn(expected,text)
        self.assertFalse(self.banner.cta.winfo_manager())

    def test_sealed_source_without_context_is_still_working(self):
        role=analysis_role(self.host,{"track_id":"TRACK-PZ3","status":"SEALED","image_count":1000})
        self.assertFalse(role["controlled"])
        self.assertEqual(role["source_label"],"Źródło analizy roboczej")
        self.assertEqual(role["models_label"],"Modele do analizy")

    def test_pz2_tab_label_is_model_analysis_even_after_reshow(self):
        self.host.right_nb=ttk.Notebook(self.root)
        self.host.hist_tab=ttk.Frame(self.host.right_nb)
        self.host.ranking_tab=ttk.Frame(self.host.right_nb)
        self.host.right_nb.add(self.host.hist_tab,text="Historia treningów")
        self.host.right_nb.add(self.host.ranking_tab,text="old")
        self.host._step4_ranking_tab_visible=True
        self.host._is_ranking_available_for_selected_target=lambda:True
        self.host._is_ranking_tab_active=lambda:False
        refresh_step4_analysis_tab_visibility(self.host)
        self.assertEqual(self.host.right_nb.tab(self.host.ranking_tab,"text"),"Analiza modeli")
        self.host.right_nb.hide(self.host.ranking_tab)
        self.host._step4_ranking_tab_visible=False
        refresh_step4_analysis_tab_visibility(self.host)
        self.assertEqual(self.host.right_nb.tab(self.host.ranking_tab,"text"),"Analiza modeli")
        self.assertTrue(self.host.right_nb.tab(self.host.ranking_tab,"image"))

    def test_real_panel_standalone_labels_and_dynamic_start(self):
        host=Mock()
        host.app=SimpleNamespace(palette={})
        host.frame=ttk.Frame(self.root)
        host.rank_scope_var=tk.StringVar(self.root,"Globalne")
        host._pz3_comparison_context=None
        host._get_ranking_models_default_dir.return_value=Path(".")
        host._get_ranking_task_label.return_value="Tablice"
        host._get_ranking_task_target.return_value="plate"
        ranking._build_ranking_panel_v2(host,host.frame)
        host.frame.pack(fill="both",expand=True)
        self.root.geometry("1040x780")
        self.root.deiconify()
        self.root.update()
        self.assertEqual(host.btn_open_rank_participants.cget("text"),"Modele do analizy")
        self.assertEqual(host.btn_open_rank_track.cget("text"),"Źródło analizy roboczej")
        host.rank_is_running=False
        host._is_ranking_available_for_selected_target.return_value=True
        host._resolve_ranking_reference_source.return_value={"ok":True}
        host._collect_ranking_participant_candidates.return_value=[Path("M1.pt")]
        host._filter_enabled_ranking_participants.side_effect=lambda models:models
        TrainingTab._refresh_ranking_start_state(host)
        self.assertEqual(host.btn_run_rank.cget("text"),"Uruchom analizę roboczą")
        host._pz3_comparison_context=context_for("ref",["M1.pt","M2.pt"])
        TrainingTab._refresh_ranking_start_state(host)
        self.assertEqual(host.btn_run_rank.cget("text"),"Uruchom porównanie")


class AnalysisReportRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.reference=self.root/"sealed_reference"
        self.reference.mkdir()
        self.paths=[self.root/"n.pt",self.root/"s.pt"]
        self.entries=[self.entry("M1",self.paths[0]),self.entry("M2",self.paths[1])]
        self.host=SimpleNamespace(
            _pz3_comparison_context=None,
            rank_scope_var=Value("Globalne"),rank_models_dir=Value(""),
            rank_data_dir=Value(str(self.reference)),
            _ensure_plate_ranking_engine=lambda:None,
            _get_ranking_task_target=lambda:"plate",
            _get_ranking_task_label=lambda *args:"Tablice",
            _resolve_ranking_reference_source=lambda:dict(ok=True,reference_dir=str(self.reference),
                selected_path=str(self.reference),reference_name="Sealed pool",image_count=1000,status="SEALED"),
            ranking_engine=SimpleNamespace(entries=self.entries,get_unique_entries=lambda:self.entries),
        )
        self.enterContext(patch.object(ranking,"_collect_ranking_participant_candidates",return_value=self.paths))
        self.enterContext(patch.object(ranking,"_ranking_report_model_label",
                                      side_effect=lambda host,entry,target:(entry.model_id,Path(entry.model_path).name)))

    def entry(self, model_id, path, **overrides):
        fields=dict(model_id=model_id,model_path=str(path),task_type="Tablice",
            reference_path=str(self.reference),comparison_scope="Globalne",
            experiment_id="EXP-1",experiment_mode="controlled",track_id="TRACK-PZ3",
            track_manifest_sha256="a"*64,protocol_sha256="b"*64,model_sha256="c"*64,
            precision=90,recall=80,f1_score=84.706,ranking_score=82,
            evidence_status="CONTROLLED",date_evaluated="2026-09-16T12:00:00")
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def test_standalone_report_is_marked_working_analysis_even_for_sealed_source(self):
        report=ranking._collect_current_ranking_report_context(self.host)
        self.assertEqual(report["analysis_mode"],"working")
        self.assertEqual(report["track_id"],"")
        markdown=ranking._ranking_report_markdown(report)
        self.assertTrue(markdown.startswith("# Analiza robocza"))
        self.assertIn("Źródło analizy roboczej",markdown)
        self.assertNotIn("**CONTROLLED / SEALED**",markdown)

    def test_controlled_report_is_marked_controlled_and_contains_frozen_contract(self):
        self.host._pz3_comparison_context=context_for(self.reference,self.paths)
        report=ranking._collect_current_ranking_report_context(self.host)
        markdown=ranking._ranking_report_markdown(report)
        for expected in ("# Eksperyment kontrolowany PZ3","CONTROLLED / SEALED",
                         "TRACK-PZ3","M1","M2",str(self.reference),"a"*64,"c"*64):
            self.assertIn(expected,markdown)

    def test_controlled_report_does_not_adopt_working_or_other_track_entries(self):
        self.host._pz3_comparison_context=context_for(self.reference,self.paths)
        self.entries.extend([
            self.entry("M1",self.paths[0],experiment_mode="",experiment_id=""),
            self.entry("M2",self.paths[1],track_id="OTHER"),
            self.entry("M3",self.root/"extra.pt"),
        ])
        report=ranking._collect_current_ranking_report_context(self.host)
        self.assertEqual([row["model_id"] for row in report["rows"]],["M1","M2"])

    def test_report_cannot_hide_changed_controlled_reference(self):
        self.host._pz3_comparison_context=context_for(self.reference,self.paths)
        self.host.rank_data_dir.set(str(self.root/"other"))
        with self.assertRaises(EvaluationTrackError):
            ranking._collect_current_ranking_report_context(self.host)

    def test_report_does_not_change_saved_metrics_or_evidence(self):
        before=[vars(entry).copy() for entry in self.entries]
        report=ranking._collect_current_ranking_report_context(self.host)
        ranking._ranking_report_markdown(report)
        self.assertEqual([vars(entry) for entry in self.entries],before)


class WorkingExecutionTests(unittest.TestCase):
    def test_standalone_sealed_source_does_not_prepare_controlled_experiment(self):
        from pz3_final_hardening_smoke import ControlledRankingAnnotator
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            reference=root/"sealed"
            reference.mkdir()
            (reference/"seal.json").write_text('{"status":"SEALED"}')
            image=reference/"TEST.png"
            Image.new("RGB",(96,64),"gray").save(image)
            gt=reference/"annotations.xml"
            gt.write_text('<annotations><image id="0" name="TEST.png" width="96" height="64">'
                          '<polygon label="plate" points="10,10;80,10;80,40;10,40"/>'
                          '</image></annotations>',encoding="utf-8")
            model=root/"model.pt"
            model.write_bytes(b"fixture")
            work=root/"working"
            work.mkdir()
            host=Mock()
            host._pz3_comparison_context=None
            host.rank_is_running=False
            host.rank_cancel_requested=False
            host.rank_data_dir=Value(str(reference))
            host.rank_models_dir=Value(str(root))
            host.rank_scope_var=Value("Globalne")
            host.device_var=Value("CPU")
            host._get_ranking_task_target.return_value="plate"
            host._get_ranking_task_label.return_value="Tablice"
            host._get_effective_training_device_profile.return_value=("cpu",None)
            host._device_to_ultralytics.return_value="cpu"
            host._resolve_ranking_reference_source.return_value=dict(ok=True,reference_dir=str(reference),
                selected_path=str(reference),reference_name="SEALED source",image_count=1,
                image_paths=[image],xml_path=str(gt))
            host._collect_ranking_participant_candidates.return_value=[model]
            host._ui.side_effect=lambda action:action()
            host.ranking_engine=ModelRanking(root/"rankings")
            with patch.object(ranking.tk,"StringVar",Value), \
                 patch.object(ranking.threading,"Thread") as worker, \
                 patch.object(ranking,"RankingExperimentBridge") as bridge, \
                 patch("auto_annotation_tool.annotators.runtime_factory.create_plate_annotator",
                       return_value=ControlledRankingAnnotator()), \
                 patch.object(ranking.messagebox,"showerror") as error:
                bridge.return_value.working_temp_xml_path.return_value=work/"auto.xml"
                bridge.return_value.prepare.side_effect=AssertionError("Standalone cannot prepare controlled experiment")
                ranking._run_ranking_v2(host)
                worker.call_args.kwargs["target"]()
            error.assert_not_called()
            bridge.return_value.prepare.assert_not_called()
            bridge.return_value.record_result.assert_not_called()
            self.assertEqual(len(host.ranking_engine.entries),1)
            entry=host.ranking_engine.entries[0]
            self.assertEqual(entry.experiment_id,"")
            self.assertEqual(entry.experiment_mode,"")
            self.assertEqual(entry.track_id,"")
            self.assertFalse(host.rank_is_running)


if __name__=="__main__":
    unittest.main()
