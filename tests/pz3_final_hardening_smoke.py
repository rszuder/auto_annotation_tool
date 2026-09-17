"""Final hardening smoke: real preannotation; controlled ranking predictions; temporary Workspace."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import traceback
import json
import sqlite3
import shutil
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from pz3_test_support import PZ3Fixture
from pz3_gui_capture import capture_window
from auto_annotation_tool.config import CONFIG, SESSION
from auto_annotation_tool.campaign_manager import CAMPAIGN
from auto_annotation_tool.gui.app import AutoAnnotationApp
from auto_annotation_tool.gui.app_style_setup import setup_style
from auto_annotation_tool.gui.app_theme_definitions import THEME_DEFINITIONS, get_theme_palette
from auto_annotation_tool.gui.tab_annotation import AnnotationTab
from auto_annotation_tool.gui.tab_training import TrainingTab
from auto_annotation_tool.gui.experiment_gt_workflow import ExperimentGtEntryDecision
from auto_annotation_tool.gui.pz3_gt_route import return_gt_to_pz3
from auto_annotation_tool.gui.z4_analysis_ranking import _collect_ranking_participant_candidates



def descendants(widget):
    yield widget
    for child in widget.winfo_children():
        yield from descendants(child)


def button(dialog, label):
    return next(widget for widget in descendants(dialog)
                if "text" in widget.keys() and str(widget.cget("text")) == label
                and callable(getattr(widget, "invoke", None)))


def preannotation_with_project_model(host, root, fixture, settle):
    from auto_annotation_tool.gui.pz3_gt_route import start_preannotation
    from auto_annotation_tool.registry.gt_preannotation import get_gt_preparation_summary, snapshot_xml_path
    original, chosen = fixture.workspace / "M1.pt", fixture.workspace / "M2.pt"
    participants = fixture.audit.load_participants(fixture.track)
    failures = []
    host.plate_custom_var.set("")
    host._clear_plate_model_runtime_meta()
    host._set_auto_vehicle_choice_state("skip", campaign_context=False)

    def choose():
        dialog = host._plate_auto_scope_active_dialog
        try:
            assert dialog.title() == "Preanotacja Ground Truth"
            picker = button(dialog, "Wybierz model…")
            assert picker.winfo_ismapped()
            entry = next(child for child in picker.master.winfo_children() if isinstance(child, ttk.Entry))
            assert Path(entry.get()) == original
            capture_window(dialog, "output/pz3_final_gt_project_default.png")
            with patch("auto_annotation_tool.gui.z2_auto_scope_modal.filedialog.askopenfilename",
                       return_value=str(chosen)):
                picker.invoke()
            settle()
            assert Path(entry.get()) == chosen
            capture_window(dialog, "output/pz3_final_gt_selected_model.png")
            button(dialog, "Uruchom preanotację").invoke()
        except BaseException as exc:
            failures.append(exc)
            button(dialog, "Anuluj").invoke()

    with patch.object(CAMPAIGN, "get_active_project_name", return_value="Isolated GT smoke"), \
         patch.object(CAMPAIGN, "get_global_model", side_effect=lambda target: str(original) if target=="plate" else ""), \
         patch.object(CAMPAIGN, "set_global_model") as adopt, \
         patch.object(host, "_get_effective_yolo_device_choice", return_value="CPU"):
        root.after(600, choose)
        start_preannotation(host)
        deadline = time.monotonic() + 180
        while host.is_processing and time.monotonic() < deadline:
            settle()
        assert not host.is_processing, "Preannotation timed out"
        settle()
        assert not failures, failures
        adopt.assert_not_called()
    summary = get_gt_preparation_summary(fixture.workspace, fixture.track)
    assert summary["snapshot_exists"], summary
    assert summary["model_sha256"] == fixture.service._sha256(chosen), summary
    assert Path(host.plate_custom_var.get()) == chosen
    assert fixture.audit.load_participants(fixture.track) == participants
    track_root = fixture.workspace / fixture.service.get_track(fixture.track)["relative_path"]
    snapshot = snapshot_xml_path(track_root)
    print("PREANNOTATION PASS: actual local weights on CPU, project default replaced, AUTO and model SHA saved", flush=True)
    return snapshot, fixture.service._sha256(snapshot)


def check_frozen_comparison(host, fixture):
    from auto_annotation_tool.gui import z4_analysis_ranking as ranking
    from auto_annotation_tool.gui.pz3_comparison import validate_comparison_context, resolve_comparison
    context = validate_comparison_context(host)
    for action in (ranking._open_ranking_track_modal, ranking._open_ranking_participants_modal,
                   ranking._open_ranking_advanced_modal):
        with patch.object(ranking.messagebox, "showinfo") as info, patch.object(ranking.tk, "Toplevel") as dialog:
            action(host)
            info.assert_called_once()
            dialog.assert_not_called()
    host.rank_data_dir.set(str(fixture.workspace / "other"))
    with patch.object(ranking.messagebox, "showerror") as error, patch.object(ranking.threading, "Thread") as worker:
        ranking._run_ranking_v2(host)
        error.assert_called_once()
        worker.assert_not_called()
    host.rank_data_dir.set(context["reference_path"])
    validate_comparison_context(host, model_paths=context["model_paths"])
    assert resolve_comparison(fixture.service, fixture.track)["model_ids"] == context["model_ids"]
    checkpoint = Path(context["model_paths"][0])
    original_size = checkpoint.stat().st_size
    try:
        with checkpoint.open("ab") as output:
            output.write(b"tamper")
        try:
            resolve_comparison(fixture.service, fixture.track)
        except Exception as exc:
            assert "checkpoint" in str(exc)
        else:
            raise AssertionError("Changed checkpoint SHA accepted")
    finally:
        with checkpoint.open("r+b") as output:
            output.truncate(original_size)
    print("CONTRACT PASS: frozen selectors, changed reference refused, changed checkpoint SHA refused", flush=True)


class ControlledRankingAnnotator:
    """Deterministic predictions for exercising persistence; not scientific measurements."""
    def load_models(self):
        return True, "deterministic smoke fixture"

    def process_image(self, path):
        from PIL import Image
        from auto_annotation_tool.data_models import ImageAnnotation, Detection
        with Image.open(path) as image:
            width, height = image.size
        points = [(10, 10), (80, 10), (80, 40), (10, 40)]
        return ImageAnnotation(filename=Path(path).name, width=width, height=height, detections=[
            Detection(label="plate", confidence=0.9, bbox=(10, 10, 80, 40), polygon=points,
                      attributes={"corner_source":"pose", "corner_order":"tl_tr_br_bl"}),
        ])

    def unload_models(self):
        pass


def main():
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        fixture = PZ3Fixture(temporary)
        original_workspace = Path(CONFIG.WORKSPACE_DIR).resolve()
        real_models = []
        registry = original_workspace / "_registry" / "alpr_registry.sqlite3"
        with sqlite3.connect(registry.as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            for scale in ("n", "s"):
                rows = connection.execute(
                    "SELECT m.model_id,m.sha256,l.relative_path,l.external_path "
                    "FROM models m JOIN model_locations l ON l.model_id=m.model_id "
                    "WHERE m.target='plate' AND m.yolo_scale=? AND m.yolo_family='YOLO26' "
                    "AND m.provenance_status='complete' ORDER BY l.is_primary DESC",
                    (scale,),
                ).fetchall()
                found = None
                for row in rows:
                    candidates = []
                    if row["relative_path"]:
                        candidates.append(original_workspace / row["relative_path"])
                    if row["external_path"]:
                        candidates.append(Path(row["external_path"]))
                    for path in candidates:
                        if path.is_file():
                            found = path
                            break
                    if found:
                        break
                if found is None:
                    raise RuntimeError("Missing real YOLO26 " + scale + " checkpoint")
                real_models.append(found)
        for attr in dir(CONFIG):
            if attr.startswith("_"):
                continue
            value = getattr(CONFIG, attr)
            if isinstance(value, Path):
                try:
                    relative = value.resolve().relative_to(original_workspace)
                except ValueError:
                    continue
                stack.enter_context(patch.object(CONFIG, attr, fixture.workspace / relative))
        stack.enter_context(patch.object(CONFIG, "WORKSPACE_DIR", fixture.workspace))
        stack.enter_context(patch.object(CAMPAIGN, "get_active_project_name", return_value=""))
        stack.enter_context(patch.object(SESSION, "get", side_effect=lambda *args, **kw: args[2] if len(args)>2 else kw.get("default")))
        stack.enter_context(patch.object(SESSION, "set"))
        for method in ("save", "_save", "save_session", "flush"):
            if hasattr(SESSION, method):
                stack.enter_context(patch.object(SESSION, method))
        stack.enter_context(patch.object(AnnotationTab, "_queue_free_mode_session_save"))
        stack.enter_context(patch.object(AnnotationTab, "_restore_preview_from_session_run", return_value=False))
        for key in ("get_auto_annotations_dir", "get_training_runs_dir", "get_datasets_dir", "get_ranking_dir", "get_models_dir"):
            if hasattr(CONFIG, key):
                def location(target="plate", key=key, **kw):
                    path = fixture.workspace / key / str(target)
                    path.mkdir(parents=True, exist_ok=True)
                    return path
                stack.enter_context(patch.object(CONFIG, key, side_effect=location))

        images = [fixture.image(f"TEST_{i:03}.png", seed=800+i) for i in range(3)]
        report = fixture.audit.audit_paths(fixture.track, images)
        fixture.service.add_members_batch(fixture.track, images)
        fixture.audit.record_ingested_report(fixture.track, report, images)
        for i, model_id in enumerate(("M1", "M2")):
            path = fixture.workspace / f"{model_id}.pt"
            if real_models:
                shutil.copy2(real_models[i], path)
                with fixture.repo.database.transaction() as connection:
                    connection.execute("UPDATE models SET sha256=? WHERE model_id=?",
                                       (fixture.service._sha256(path), model_id))
            else:
                path.write_bytes(model_id.encode())
            fixture.repo.upsert_model_location(
                model_id=model_id, sha256=fixture.service._sha256(path), project_id=None,
                run_id=f"R{i+1}", target="plate", task_type="pose",
                yolo_family="YOLO26", yolo_scale=("n","s")[i],
                checkpoint_kind="trained_export", provenance_status="complete",
                created_at="2026-09-15T00:00:00", location_key="smoke",
                relative_path=path.name, external_path=None, is_primary=True,
            )

        if real_models:
            fixture.audit.save_participants(fixture.track, ["M1", "M2"])
            report = fixture.audit.audit_paths(fixture.track, images)
            fixture.audit.record_ingested_report(fixture.track, report, images)

        fixture.select_and_reaudit()

        root = tk.Tk()
        root.title("PZ3 — controlled experiment flow smoke")
        root.geometry("1380x880+20+20")
        errors = []
        stack.enter_context(patch("tkinter.messagebox.showerror",
                                 side_effect=lambda title, message, **kw: errors.append((title, str(message)))))
        stack.enter_context(patch("tkinter.messagebox.showinfo", return_value=None))
        stack.enter_context(patch("tkinter.messagebox.showwarning", return_value=None))
        def report_callback_error(*args):
            errors.append(args)
            traceback.print_exception(*args)
        root.report_callback_exception = report_callback_error
        app = AutoAnnotationApp.__new__(AutoAnnotationApp)
        app.root = root
        app.themes = THEME_DEFINITIONS
        app.style = ttk.Style(root)
        app.palette = get_theme_palette("light_visual_cs")
        app.current_theme_key = "light_visual_cs"
        app.tabs = {}
        app.campaign_free_mode = True
        app.update_status = lambda *args, **kw: None
        app.append_global_terminal = lambda *args, **kw: None
        app.set_processing = lambda *args, **kw: None
        app.begin_exclusive_operation = lambda *args, **kw: True
        app.try_begin_exclusive_operation = lambda *args, **kw: (True, "")
        app.end_exclusive_operation = lambda *args, **kw: None
        app._ensure_tab_loaded = lambda key, **kw: app.tabs[key]
        setup_style(app, "light_visual_cs")
        app.notebook = ttk.Notebook(root)
        app.notebook.pack(fill="both", expand=True)

        def settle():
            ready = tk.BooleanVar(root, False)
            root.after(300, lambda: ready.set(True))
            root.wait_variable(ready)

        failures = []
        def exercise():
            try:
                annotation = AnnotationTab(app.notebook, app)
                app.tabs["annotation"] = annotation
                app.notebook.add(annotation.frame, text="Z2")
                training = TrainingTab(app.notebook, app)
                app.tabs["training"] = training
                real_rank_log = training._append_ranking_log
                def rank_log(message):
                    print("RANK: " + str(message), flush=True)
                    return real_rank_log(message)
                training._append_ranking_log = rank_log
                app.notebook.add(training.frame, text="Z4")
                training._ensure_step4_tracks_tab_built()
                panel = training.evaluation_tracks_panel
                panel.refresh_tracks(select_track_id=fixture.track)
                app.notebook.select(training.frame)
                training.main_nb.select(training.tab_tracks)
                settle()
                with patch("auto_annotation_tool.gui.z4_evaluation_tracks.show_experiment_gt_entry",
                           return_value=ExperimentGtEntryDecision("manual", "unspecified")), \
                     patch.object(panel, "_show_error", side_effect=lambda title, exc: (_ for _ in ()).throw(exc)):
                    panel.btn_prepare_z2.invoke()
                settle()
                assert annotation._experiment_gt_context["track_id"] == fixture.track
                assert annotation.free_mode_screen_var.get() == "manual_review"
                assert len(annotation.current_annotations) == 3
                assert annotation._experiment_gt_return_button.winfo_ismapped()
                assert annotation.preview_host.winfo_ismapped()
                capture_window(root, "output/pz3_scope_gt_editor.png")

                snapshot, snapshot_sha = preannotation_with_project_model(annotation, root, fixture, settle)

                xml = Path(annotation._experiment_gt_context["annotation_path"])
                tree = ET.parse(xml)
                for node in tree.getroot().findall("image"):
                    ET.SubElement(node, "polygon", label="plate", points="10,10;80,10;80,40;10,40")
                tree.write(xml, encoding="utf-8", xml_declaration=True)
                assert annotation._open_existing_run_for_manual_review(
                    run_dir=xml.parent, allow_fallback=False, show_dialog=False, entry_mode="continue")
                annotation._preview_dirty_images = {ann.filename for ann in annotation.current_annotations}
                with patch("auto_annotation_tool.gui.pz3_gt_route.messagebox.showerror",
                           side_effect=lambda title, message, **kw: (_ for _ in ()).throw(AssertionError(message))):
                    annotation._experiment_gt_return_button.invoke()
                settle()
                assert fixture.service.get_track(fixture.track)["gt_relative_path"]
                assert not annotation._experiment_gt_context
                with patch("auto_annotation_tool.gui.z4_evaluation_tracks.messagebox.askyesno", return_value=True):
                    panel.btn_verify.invoke()
                assert fixture.service.get_track(fixture.track)["status"] == "VERIFIED"
                fixture.service.attest_independent_acquisition(fixture.track, source_pool="synthetic_gui_fixture")
                fixture.service.seal(fixture.track)
                assert fixture.service._sha256(snapshot) == snapshot_sha
                panel.refresh_tracks(select_track_id=fixture.track)
                settle()
                assert str(panel.btn_compare["state"]) == "normal"
                capture_window(root, "output/pz3_scope_ready_compare.png")
                with patch.object(panel, "_show_error", side_effect=lambda title, exc: (_ for _ in ()).throw(exc)):
                    panel.btn_compare.invoke()
                settle()
                assert training._get_ranking_task_target() == "plate"
                models = _collect_ranking_participant_candidates(training, None, "plate", "Globalne")
                assert {path.name for path in models} == {"M1.pt", "M2.pt"}
                assert training._ranking_results_modal.winfo_exists()
                assert len(training.rank_tree.get_children()) == 2
                assert str(annotation.main_right_frame) not in annotation.main_pane.panes()
                capture_window(training._ranking_results_modal, "output/pz3_scope_comparison.png")
                check_frozen_comparison(training, fixture)
                if real_models:
                    invoked_models = []
                    def create_fixture_annotator(path, *args, **kwargs):
                        invoked_models.append(Path(path))
                        return ControlledRankingAnnotator()
                    stack.enter_context(patch("auto_annotation_tool.annotators.runtime_factory.create_plate_annotator", side_effect=create_fixture_annotator))
                    training.device_var.set("CPU")
                    training._run_ranking_v2()
                    deadline = time.monotonic() + 150
                    while training.rank_is_running and time.monotonic() < deadline:
                        settle()
                    assert not training.rank_is_running, "Inference smoke timed out"
                    settle()
                    with fixture.repo.database.read_connection() as connection:
                        results = [dict(row) for row in connection.execute(
                            "SELECT r.* FROM experiment_results r JOIN experiments e "
                            "ON e.experiment_id=r.experiment_id WHERE e.track_id=?",
                            (fixture.track,),
                        )]
                    assert {row["model_id"] for row in results} == {"M1", "M2"}, (results, errors)
                    assert set(invoked_models) == {fixture.workspace / "M1.pt", fixture.workspace / "M2.pt"}
                    assert not errors, errors
                    Path("output/pz3_final_hardening_smoke.json").write_text(
                        json.dumps({"scope": "Real preannotation CPU; deterministic ranking predictions; synthetic GUI fixture, not thesis measurements",
                                    "real_checkpoints": [str(path) for path in real_models],
                                    "results": results}, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                    capture_window(training._ranking_results_modal, "output/pz3_final_hardening_results.png")
                    print("RANKING PASS: exact frozen checkpoints, deterministic predictions, two results persisted")
                from pz3_scope_lifecycle_probe import exercise_scope_lifecycle
                exercise_scope_lifecycle(training, panel, fixture, settle)
                assert not errors, errors
                print("SMOKE PASS: real Z2 editor, fixed XML, saved GT, verified/sealed track, exact frozen participants and comparison window")
            except BaseException as exc:
                failures.append(exc)
                traceback.print_exc()
            finally:
                for job in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", job)
                root.tk.call("destroy", root._w)
        root.after(0, exercise)
        root.mainloop()
        if failures:
            raise failures[0]


if __name__ == "__main__":
    main()
