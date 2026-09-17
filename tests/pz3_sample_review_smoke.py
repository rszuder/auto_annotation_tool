"""RAW sample selection first; real preannotation only on the final sample."""
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

        images = [fixture.image(f"TEST_{i:03}.png", seed=800+i) for i in range(20)]
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
                from auto_annotation_tool.gui.pz3_sample_route import (
                    sample_context, selected_sample_names, sample_counter, cancel_sample_review)
                original_bytes = {path: path.read_bytes() for path in images}
                raw_approval_calls = []
                original_approval_check = annotation._preview_annotation_can_be_approved_for_export
                def approval_check(ann):
                    if sample_context(annotation):
                        raw_approval_calls.append(str(getattr(ann, "filename", "")))
                    return original_approval_check(ann)
                with patch("auto_annotation_tool.registry.experiment_gt_workspace.prepare_gt_workspace",
                           side_effect=AssertionError("GT must not be prepared during RAW selection")) as prepare_gt, \
                     patch("auto_annotation_tool.annotators.runtime_factory.create_plate_annotator",
                           side_effect=AssertionError("No inference during RAW selection")) as inference, \
                     patch.object(annotation, "_preview_annotation_can_be_approved_for_export",
                                  side_effect=approval_check):
                    assert str(panel.btn_prepare_z2["state"]) == "disabled"
                    assert str(panel.btn_set_gt["state"]) == "disabled"
                    panel.btn_sample_selection.invoke()
                    for _ in range(3):
                        settle()
                    assert sample_context(annotation)["track_id"] == fixture.track, errors
                    assert not annotation._experiment_gt_context
                    assert len(annotation.current_annotations) == 20
                    assert all(not ann.detections for ann in annotation.current_annotations)
                    assert annotation.current_annotation_xml_path is None
                    assert not list(fixture.workspace.rglob("annotations.xml"))
                    assert not annotation.preview_tools.winfo_ismapped()
                    from auto_annotation_tool.gui.pz3_sample_labels_ui import add_sample_label, label_state
                    label_id = add_sample_label(annotation, "Noc")
                    def select(index):
                        annotation.preview_listbox.selection_clear(0, tk.END)
                        annotation.preview_listbox.selection_set(index)
                        annotation.preview_listbox.activate(index)
                        annotation.preview_listbox.event_generate("<<ListboxSelect>>")
                        annotation.preview_listbox.focus_force()
                        settle()
                        assert annotation.current_preview_index == index
                    select(0)
                    annotation.preview_listbox.event_generate("<KeyPress-space>")
                    annotation.preview_listbox.event_generate("<KeyRelease-space>")
                    settle()
                    assert len(selected_sample_names(annotation)) == 1, sample_counter(annotation)
                    annotation.preview_listbox.selection_clear(0, tk.END)
                    annotation.preview_listbox.selection_set(1, 5)
                    menu = annotation.preview_list_context_menu
                    x, y, width, height = annotation.preview_listbox.bbox(3)
                    # Exercise the real right-click handler and menu command.
                    # Native Windows menu tracking can wait for physical input.
                    with patch.object(menu, "tk_popup") as popup:
                        annotation.preview_listbox.event_generate("<Button-3>", x=x + 15, y=y + height // 2)
                        popup.assert_called_once()
                    menu.invoke("Dodaj zaznaczone do próby")
                    settle()
                    assert len(selected_sample_names(annotation)) == 6, sample_counter(annotation)
                    assert label_state(annotation).counts[label_id] == 6
                    app._schedule_z2_main_tab_entry_refresh("annotation")
                    settle()
                    assert sample_context(annotation)
                    assert not annotation._experiment_gt_context
                    annotation._select_preview_index(9)
                    settle()
                    assert len(annotation.preview_listbox.curselection()) == 5
                    assert len(selected_sample_names(annotation)) == 6
                    annotation._sample_filter_var.set("W próbie")
                    annotation._refresh_preview_list(preserve_selection=True, render_current=False)
                    settle()
                    assert annotation.preview_listbox.size() == 6
                    assert "6 / 20" in sample_counter(annotation)
                    annotation._sample_filter_var.set("Wszystkie")
                    annotation._refresh_preview_list(preserve_selection=True, render_current=False)
                    settle()
                    select(9)
                    capture_window(root, "output/pz3_raw_sample_normal.png")
                    annotation._toggle_preview_fullscreen()
                    for _ in range(3):
                        settle()
                    badge = annotation.preview_image_status_lbl
                    assert annotation._preview_fullscreen_active
                    assert badge.winfo_ismapped()
                    assert "6 / 20" in badge.cget("text"), badge.cget("text")
                    badge.event_generate("<Button-1>")
                    settle()
                    assert len(selected_sample_names(annotation)) == 7
                    badge.event_generate("<Button-1>")
                    settle()
                    annotation.preview_canvas.focus_force()
                    annotation.preview_canvas.event_generate("<KeyPress-space>")
                    annotation.preview_canvas.event_generate("<KeyRelease-space>")
                    settle()
                    assert len(selected_sample_names(annotation)) == 7
                    annotation.preview_canvas.event_generate("<KeyPress-space>")
                    annotation.preview_canvas.event_generate("<KeyRelease-space>")
                    settle()
                    assert len(selected_sample_names(annotation)) == 6
                    capture_window(root, "output/pz3_raw_sample_fullscreen.png")
                    expected_names = selected_sample_names(annotation)
                    assert not annotation._preview_approved_filenames
                    assert all(not getattr(ann, "_approved_for_training", False)
                               for ann in annotation.current_annotations)
                    cancel_sample_review(annotation)
                    settle()
                    assert len(fixture.service.list_members(fixture.track)) == 20
                    assert fixture.audit.get_track_audit_state(fixture.track)["status"] == "CURRENT"
                    panel.btn_sample_selection.invoke()
                    for _ in range(3):
                        settle()
                    assert selected_sample_names(annotation) == expected_names
                    assert label_state(annotation).active_id == label_id
                    assert label_state(annotation).counts[label_id] == 6
                    button(annotation._sample_bar, "Zapisz roboczą próbę i wróć do PZ3").invoke()
                    settle()
                    assert not errors, errors
                    prepare_gt.assert_not_called()
                    inference.assert_not_called()
                assert not sample_context(annotation)
                track = fixture.service.get_track(fixture.track)
                assert track["gt_relative_path"] is None
                assert track["gt_sha256"] is None
                assert len(fixture.service.list_members(fixture.track)) == 20
                assert fixture.audit.get_track_audit_state(fixture.track)["status"] == "CURRENT"
                labels_path = fixture.workspace / track["relative_path"] / "sample_labels.json"
                assert not labels_path.exists()
                panel.refresh_tracks(select_track_id=fixture.track)
                assert str(panel.btn_audit_pool["state"]) == "disabled"
                assert str(panel.btn_sample_selection["state"]) == "normal"
                assert str(panel.btn_finalize_sample["state"]) == "normal"
                assert str(panel.btn_prepare_z2["state"]) == "disabled"
                with patch("auto_annotation_tool.gui.z4_evaluation_tracks.messagebox.askyesno", return_value=True):
                    panel.btn_finalize_sample.invoke()
                settle()
                assert not errors, errors
                assert {r["original_name"] for r in fixture.service.list_members(fixture.track)} == expected_names
                assert fixture.audit.get_track_audit_state(fixture.track)["status"] == "CURRENT"
                labels_payload = json.loads(labels_path.read_text(encoding="utf-8"))
                assert labels_payload["labels"] == [{"id": label_id, "name": "Noc"}]
                assert set(labels_payload["assignments"]) == {
                    member["sha256"] for member in fixture.service.list_members(fixture.track)}
                assert not list(fixture.workspace.rglob("annotations.xml"))
                assert str(panel.btn_audit_pool["state"]) == "disabled"
                assert str(panel.btn_sample_selection["state"]) == "disabled"
                assert str(panel.btn_finalize_sample["state"]) == "disabled"
                assert str(panel.btn_prepare_z2["state"]) == "normal"
                assert str(panel.btn_set_gt["state"]) == "normal"
                for path, content in original_bytes.items():
                    assert path.read_bytes() == content
                print("RAW PASS: szeroka pula zachowana podczas edycji; finalizacja podzbioru zachowuje audit CURRENT", flush=True)
                print("RAW approval guard calls:", raw_approval_calls, flush=True)
                assert not raw_approval_calls, raw_approval_calls
                capture_window(root, "output/pz3_raw_sample_draft.png")
                with patch("auto_annotation_tool.gui.z4_evaluation_tracks.show_experiment_gt_entry",
                           return_value=ExperimentGtEntryDecision("manual", "unspecified")):
                    panel.btn_prepare_z2.invoke()
                settle()
                assert len(annotation.current_annotations) == 6
                assert not sample_context(annotation)
                snapshot, snapshot_sha = preannotation_with_project_model(annotation, root, fixture, settle)
                xml = Path(annotation._experiment_gt_context["annotation_path"])
                tree = ET.parse(xml)
                assert len(tree.getroot().findall("image")) == 6
                for node in tree.getroot().findall("image"):
                    ET.SubElement(node, "polygon", label="plate", points="10,10;80,10;80,40;10,40")
                tree.write(xml, encoding="utf-8", xml_declaration=True)
                assert annotation._open_existing_run_for_manual_review(
                    run_dir=xml.parent, allow_fallback=False, show_dialog=False, entry_mode="continue")
                annotation._preview_dirty_images = {ann.filename for ann in annotation.current_annotations}
                annotation._experiment_gt_return_button.invoke()
                settle()
                assert fixture.service.get_track(fixture.track)["gt_relative_path"]
                with patch("auto_annotation_tool.gui.z4_evaluation_tracks.messagebox.askyesno", return_value=True):
                    panel.btn_verify.invoke()
                assert fixture.service.get_track(fixture.track)["status"] == "VERIFIED"
                fixture.service.attest_independent_acquisition(fixture.track, source_pool="synthetic_gui_fixture")
                fixture.service.seal(fixture.track)
                assert fixture.service._sha256(snapshot) == snapshot_sha
                panel.refresh_tracks(select_track_id=fixture.track)
                settle()
                assert str(panel.btn_compare["state"]) == "normal"
                capture_window(root, "output/pz3_sample_ready_compare.png")
                with patch.object(panel, "_show_error", side_effect=lambda title, exc: (_ for _ in ()).throw(exc)):
                    panel.btn_compare.invoke()
                settle()
                assert training._get_ranking_task_target() == "plate"
                models = _collect_ranking_participant_candidates(training, None, "plate", "Globalne")
                assert {path.name for path in models} == {"M1.pt", "M2.pt"}
                assert training._ranking_results_modal.winfo_exists()
                assert len(training.rank_tree.get_children()) == 2
                assert str(annotation.main_right_frame) not in annotation.main_pane.panes()
                capture_window(training._ranking_results_modal, "output/pz3_sample_comparison.png")
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
                    Path("output/pz3_raw_sample_smoke.json").write_text(
                        json.dumps({"scope": "Real preannotation CPU; deterministic ranking predictions; synthetic GUI fixture, not thesis measurements",
                                    "real_checkpoints": [str(path) for path in real_models],
                                    "selected_names": sorted(expected_names), "candidate_count": 20, "selected_count": 6, "results": results}, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                    capture_window(training._ranking_results_modal, "output/pz3_sample_results.png")
                    print("RANKING PASS: exact frozen checkpoints, deterministic predictions, two results persisted")
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
