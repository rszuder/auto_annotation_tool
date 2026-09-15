"""Jawne wejście PZ3 do istniejącego edytora anotacji Z2."""
from pathlib import Path
from tkinter import ttk, messagebox

from ..config import CONFIG
from ..registry import EvaluationTrackService
from ..registry.experiment_gt_workspace import publish_working_gt
from ..registry.experiment_workspace import experiment_workspace_for_track


def experiment_context(host):
    context = getattr(host, "_experiment_gt_context", None)
    if isinstance(context, dict) and context.get("source") == "pz3" and context.get("track_id"):
        return context
    return None


def enter_experiment_gt_workspace(host, context):
    if getattr(host, "is_processing", False):
        raise RuntimeError("Poczekaj na zakończenie bieżącej anotacji.")
    service = EvaluationTrackService(CONFIG.WORKSPACE_DIR)
    track_id = str(context.get("track_id") or "")
    state = service.get_preparation_state(track_id)
    if not state.can_prepare_gt or state.target != "plate":
        raise RuntimeError(state.next_step)
    track = service.get_track(track_id)
    paths = experiment_workspace_for_track(service.workspace, track)
    xml = Path(context["annotation_path"])
    if not service._is_within(xml, paths.annotation_runs) or not xml.is_file():
        raise RuntimeError("Nie znaleziono roboczego XML należącego do tego toru.")
    if getattr(host, "_preview_dirty_images", None):
        if not host._save_preview_edits(interactive=True):
            return False

    host._experiment_gt_context = dict(context)
    host._experiment_gt_workflow_active = True
    host._experiment_gt_track_id = track_id
    host._experiment_gt_workflow_mode = str(context.get("gt_mode") or "manual")
    host.input_dir_var.set(str(paths.source_images))
    host.plate_dataset_images_var.set(str(paths.source_images))
    host.current_input_dir = paths.source_images
    # Ten sam edytor i parser XML, ale wejście ma już wybrany run i kontekst.
    opened = host._open_existing_run_for_manual_review(
        run_dir=xml.parent, allow_fallback=False, show_dialog=False, entry_mode="continue",
        from_auto=False,
    )
    if not opened:
        host._experiment_gt_context = {}
        host._experiment_gt_workflow_active = False
        raise RuntimeError("Nie udało się otworzyć edytora Ground Truth.")
    refresh_experiment_gt_ui(host)
    if context.get("gt_mode") == "preannotation" and not context.get("gt_existing"):
        host.frame.after_idle(lambda: start_preannotation(host))
    return True


def start_preannotation(host):
    if not experiment_context(host) or getattr(host, "is_processing", False):
        return
    from ..registry.gt_preannotation import get_gt_preparation_summary, write_gt_workflow_session
    context = experiment_context(host)
    summary = get_gt_preparation_summary(CONFIG.WORKSPACE_DIR, context["track_id"])
    if summary.get("snapshot_exists"):
        messagebox.showinfo(
            "Preanotacja", "Pierwszy wynik AUTO jest już zapisany. Kontynuuj ręczną korektę GT.",
            parent=host.frame,
        )
        return
    write_gt_workflow_session(
        CONFIG.WORKSPACE_DIR, context["track_id"], mode="preannotation",
        dataset_profile=summary.get("dataset_profile", "unspecified"),
        custom_profile=summary.get("custom_profile", ""),
    )
    host._experiment_gt_workflow_mode = "preannotation"
    host.workflow_route_var.set("auto")
    host.manual_xml_template_var.set(False)
    host.workflow_step_var.set("auto_start")
    host._start_annotation()


def finish_experiment_gt_run(host, run_dir):
    if not experiment_context(host):
        return False
    from .experiment_gt_workflow import capture_experiment_gt_preannotation_snapshot
    capture_experiment_gt_preannotation_snapshot(host, run_dir)
    from ..registry.experiment_gt_workspace import merge_preannotation_working_copy
    service = EvaluationTrackService(CONFIG.WORKSPACE_DIR)
    working_xml = merge_preannotation_working_copy(
        service, experiment_context(host)["track_id"], Path(run_dir) / "annotations.xml",
    )
    if not host._open_existing_run_for_manual_review(
        run_dir=working_xml.parent, allow_fallback=False, show_dialog=False,
        from_auto=True, entry_mode="continue",
    ):
        raise RuntimeError("Nie udało się otworzyć wyniku preanotacji do ręcznej korekty.")
    refresh_experiment_gt_ui(host)
    return True


def return_gt_to_pz3(host):
    context = experiment_context(host) or {}
    if not context or getattr(host, "is_processing", False):
        return
    try:
        if not host._save_preview_edits(interactive=True):
            return
        service = EvaluationTrackService(CONFIG.WORKSPACE_DIR)
        xml = host._get_current_annotation_xml_path()
        if xml is None:
            raise RuntimeError("Brak roboczego XML Ground Truth.")
        publish_working_gt(service, context["track_id"], xml)
        service.deactivate_z2_context(track_id=context["track_id"])
        host._experiment_gt_context = {}
        host._experiment_gt_workflow_active = False
        bar = getattr(host, "_experiment_gt_bar", None)
        if bar is not None:
            bar.pack_forget()
        loader = getattr(host.app, "_ensure_tab_loaded", None)
        training = loader("training", select=False) if callable(loader) else host.app.tabs["training"]
        host.app.notebook.select(training.frame)
        training._ensure_step4_tracks_tab_built()
        training.main_nb.select(training.tab_tracks)
        training.evaluation_tracks_panel.refresh_tracks(select_track_id=context["track_id"])
        host.app.update_status("Zapisano GT w torze. W PZ3 potwierdź kompletność i zweryfikuj GT.", "success")
    except Exception as exc:
        messagebox.showerror("Zapis Ground Truth", str(exc), parent=host.frame)


def refresh_experiment_gt_ui(host):
    context = experiment_context(host)
    bar = getattr(host, "_experiment_gt_bar", None)
    if not context:
        if bar is not None and bar.winfo_exists():
            bar.pack_forget()
        return
    if bar is None or not bar.winfo_exists():
        siblings = host.frame.pack_slaves()
        bar = ttk.Frame(host.frame, padding=(10, 8))
        host._experiment_gt_bar = bar
        label = ttk.Label(bar, text="Ground Truth eksperymentu", style="PanelMuted.TLabel")
        label.pack(side="left", fill="x", expand=True)
        host._experiment_gt_bar_label = label
        button = ttk.Button(
            bar, text="Zapisz GT i wróć do PZ3", style="Accent.TButton",
            command=lambda: return_gt_to_pz3(host),
        )
        button.pack(side="right")
        host._experiment_gt_return_button = button
        auto_button = ttk.Button(bar, text="Preanotacja…", command=lambda: start_preannotation(host))
        auto_button.pack(side="right", padx=(0, 8))
        host._experiment_gt_auto_button = auto_button
        bar.pack(side="top", fill="x", before=siblings[0] if siblings else None)
    elif not bar.winfo_manager():
        siblings = host.frame.pack_slaves()
        bar.pack(side="top", fill="x", before=siblings[0] if siblings else None)
    host._experiment_gt_bar_label.configure(text=f"Ground Truth · {context.get('name') or context['track_id']}")
    control_state = "disabled" if getattr(host, "is_processing", False) else "normal"
    host._experiment_gt_return_button.configure(state=control_state)
    host._experiment_gt_auto_button.configure(state=control_state)
    for attr in ("workflow_entry_shell", "manual_entry_section"):
        widget = getattr(host, attr, None)
        if widget is not None and widget.winfo_manager() == "pack":
            widget.pack_forget()
    for attr in ("manual_stage_help_lbl",):
        widget = getattr(host, attr, None)
        if widget is not None:
            widget.configure(text="Oznacz wszystkie tablice i narożniki. Zapisz GT w PZ3 po pełnym ręcznym przeglądzie puli.")
