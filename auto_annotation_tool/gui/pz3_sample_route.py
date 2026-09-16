"""RAW selection in the existing Z2 preview, independent of annotation approval."""
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from ..config import CONFIG
from ..data_models import ImageAnnotation
from ..registry import EvaluationTrackService
from .pz3_participant_audit import BatchProgressDialog


def sample_context(host):
    context = getattr(host, "_pz3_sample_selection_context", None)
    if isinstance(context, dict) and context.get("purpose") == "sample_selection" and context.get("track_id"):
        return context
    return None


def sample_selected(host, ann=None):
    context = sample_context(host)
    if not context:
        return False
    ann = ann if ann is not None else host._get_preview_annotation()
    sha = context["sample_member_sha256"].get(str(getattr(ann, "filename", "")))
    return sha in getattr(host, "_experiment_sample_selected_sha256", set())


def selected_sample_names(host):
    context = sample_context(host)
    if not context:
        return set()
    selected = getattr(host, "_experiment_sample_selected_sha256", set())
    return {name for name, sha in context["sample_member_sha256"].items() if sha in selected}


def sample_counter(host):
    context = sample_context(host)
    return (f"Wybrano: {len(getattr(host, '_experiment_sample_selected_sha256', set()))} / "
            f"{context['candidate_count']}") if context else ""


def sample_badge_text(host, selected):
    return ("✓ W PRÓBIE" if selected else "○ POZA PRÓBĄ") + "\n" + sample_counter(host) + "\nSpacja / klik"


def set_sample_selection(host, selected, actual_indices=None):
    context = sample_context(host)
    if not context or getattr(host, "is_processing", False):
        return
    indices = host._get_selected_preview_actual_indices() if actual_indices is None else actual_indices
    chosen = host._experiment_sample_selected_sha256
    for index in indices:
        if 0 <= int(index) < len(host.current_annotations):
            ann = host.current_annotations[int(index)]
            sha = context["sample_member_sha256"].get(ann.filename)
            if sha:
                chosen.add(sha) if selected else chosen.discard(sha)
    host._sample_selection_version = getattr(host, "_sample_selection_version", 0) + 1
    listbox = getattr(host, "preview_listbox", None)
    filter_var = getattr(host, "_sample_filter_var", None)
    if listbox is not None and filter_var is not None and filter_var.get() == "Wszystkie":
        # Keep group selection and the viewport. A Space press must not rebuild
        # thousands of rows or decode the image again.
        selected_rows = tuple(listbox.curselection())
        active = listbox.index(tk.ACTIVE)
        anchor = listbox.index(tk.ANCHOR)
        for index in indices:
            display = host._get_preview_display_index(int(index))
            if display is not None:
                ann = host.current_annotations[int(index)]
                listbox.delete(display)
                listbox.insert(display, sample_list_text(host, ann, display))
        listbox.selection_clear(0, tk.END)
        for display in selected_rows:
            listbox.selection_set(display)
        listbox.activate(active)
        listbox.selection_anchor(anchor)
    else:
        refresh_sample_list(host)
    refresh_sample_ui(host)


def refresh_sample_list(host):
    previous = host._get_selected_preview_actual_indices()
    host._refresh_preview_list(preserve_selection=True, render_current=True)
    listbox = getattr(host, "preview_listbox", None)
    if listbox is not None and len(previous) > 1:
        listbox.selection_clear(0, tk.END)
        for index in previous:
            display = host._get_preview_display_index(index)
            if display is not None:
                listbox.selection_set(display)


def toggle_sample_badge(host, event=None):
    if not sample_context(host):
        return None
    index = getattr(host, "current_preview_index", None)
    if index is not None:
        set_sample_selection(host, not sample_selected(host), [index])
    host.preview_canvas.focus_set()
    return "break"


def sample_list_entries(host):
    entries = list(enumerate(host.current_annotations))
    mode = host._sample_filter_var.get()
    if mode == "W próbie":
        return [(i, ann) for i, ann in entries if sample_selected(host, ann)]
    if mode == "Poza próbą":
        return [(i, ann) for i, ann in entries if not sample_selected(host, ann)]
    return entries


def sample_list_text(host, ann, display_index=None):
    status = "W PRÓBIE" if sample_selected(host, ann) else "POZA PRÓBĄ"
    number = f"{display_index + 1}. " if display_index is not None else ""
    return f"{number}[{status}] {ann.filename}"


def _hide(host, attr):
    widget = getattr(host, attr, None)
    if widget is None:
        return
    manager = widget.winfo_manager()
    if manager not in {"pack", "grid", "place"}:
        return
    saved = host._sample_hidden_widgets
    if widget not in saved:
        if manager == "pack":
            host._sample_pack_orders.setdefault(widget.master, list(widget.master.pack_slaves()))
        saved[widget] = (manager, getattr(widget, manager + "_info")())
    getattr(widget, manager + "_forget")()


def show_sample_workspace(host):
    if not sample_context(host):
        return
    host._set_widget_packed(host.preview_host, True, fill=tk.BOTH, expand=True, padx=5, pady=0)
    host._sync_left_column_pane_layout(show_preview=True, compact_layout=False)
    host._sync_main_pane_right_panel_visibility()
    for attr in (
        "workflow_entry_shell", "manual_entry_section", "preview_tools", "preview_list_legend",
        "preview_filter_bar", "preview_list_filter_shell", "preview_list_sort_shell", "preview_list_sort_lbl",
        "preview_hint_frame", "preview_metrics_frame", "preview_overlay_dock",
        "preview_campaign_gate_frame", "_experiment_gt_bar",
    ):
        _hide(host, attr)
    host.preview_list_lf.configure(text=" Kandydaci do próby ")
    host.preview_lf.configure(text=" Podgląd obrazu ")
    refresh_sample_ui(host)


def refresh_sample_ui(host):
    context = sample_context(host)
    if not context:
        return
    label = getattr(host, "_sample_title_label", None)
    if label is not None and label.winfo_exists():
        label.configure(text=f"Wybór próby · {context.get('name') or context['track_id']}\n"
                             + sample_counter(host))
    summary = getattr(host, "preview_list_summary_var", None)
    if summary is not None:
        summary.set("Surowe obrazy · " + sample_counter(host))
    fullscreen = getattr(host, "_sample_fullscreen_button", None)
    if fullscreen is not None and fullscreen.winfo_exists():
        fullscreen.configure(text="Wyjdź z pełnego ekranu" if getattr(host, "_preview_fullscreen_active", False)
                             else "Pełny ekran (Enter)")
    host._place_preview_image_status_overlay(force_render=True)


_SNAPSHOT_FIELDS = (
    "current_annotations", "current_input_dir", "_preview_image_path_map", "current_preview_index",
    "current_annotation_run_dir", "current_annotation_xml_path", "last_staging_run_dir",
    "_experiment_gt_context", "_experiment_gt_workflow_active", "_manual_review_active",
    "_preview_approved_filenames", "_campaign_pending_approved_filenames", "_preview_super_correction_active",
    "_preview_session_restore_index", "_preview_session_restore_filename",
)
_SNAPSHOT_VARS = ("input_dir_var", "plate_dataset_images_var", "plate_dataset_run_var",
                  "free_mode_screen_var", "workflow_route_var", "workflow_step_var")


def enter_sample_selection(host, context):
    if getattr(host, "is_processing", False):
        raise RuntimeError("Poczekaj na zakończenie bieżącej operacji Z2.")
    current = sample_context(host)
    if current:
        if current["track_id"] == context["track_id"] and current["sample_member_sha256"] == context["sample_member_sha256"]:
            return True
        raise RuntimeError("Zakończ albo anuluj wybór bieżącej próby.")
    if getattr(host, "_preview_dirty_images", None) and not host._save_preview_edits(interactive=True):
        return False
    host._sample_previous_state = {name: getattr(host, name, None) for name in _SNAPSHOT_FIELDS}
    host._sample_previous_vars = {name: getattr(host, name).get() for name in _SNAPSHOT_VARS if hasattr(host, name)}
    host._sample_hidden_widgets = {}
    host._sample_pack_orders = {}
    host._sample_previous_labels = {
        "preview_list_lf": host.preview_list_lf.cget("text"),
        "preview_lf": host.preview_lf.cget("text"),
    }
    host._sample_previous_menu = host.preview_list_context_menu
    host._clear_preview_editor_state(clear_dirty=True)
    host._pz3_sample_selection_context = dict(context)
    sessions = getattr(host, "_sample_sessions", {})
    saved = sessions.get(context["track_id"], {})
    host._experiment_sample_selected_sha256 = (
        set(saved.get("selected", ())) if saved.get("members") == context["sample_member_sha256"] else set()
    )
    host._experiment_gt_context = {}
    host._experiment_gt_workflow_active = False
    host._manual_review_active = False
    host._preview_super_correction_active = False
    host._preview_approved_filenames = set()
    host._campaign_pending_approved_filenames = set()
    host.current_annotation_run_dir = host.current_annotation_xml_path = host.last_staging_run_dir = None
    host.current_input_dir = Path(context["source_dir"])
    host.current_preview_index = None
    host._preview_image_path_map = {name: Path(path) for name, path in context["sample_image_paths"].items()}
    host.current_annotations = [
        ImageAnnotation(filename=name, width=1, height=1, detections=[])
        for name in context["sample_member_sha256"]
    ]
    host.input_dir_var.set(context["source_dir"])
    host.plate_dataset_images_var.set(context["source_dir"])
    host.plate_dataset_run_var.set("")
    host._sample_filter_var = tk.StringVar(host.frame, "Wszystkie")
    bar = host._sample_bar = ttk.Frame(host.frame, padding=(10, 8))
    siblings = host.frame.pack_slaves()
    bar.pack(side="top", fill="x", before=siblings[0] if siblings else None)
    host._sample_title_label = ttk.Label(bar)
    host._sample_title_label.pack(side="left", fill="x", expand=True)
    ttk.Button(bar, text="Zatwierdź próbę i wróć do PZ3",
               command=lambda: return_sample_to_pz3(host)).pack(side="right")
    ttk.Button(bar, text="Anuluj i wróć",
               command=lambda: cancel_sample_review(host)).pack(side="right", padx=6)
    host._sample_fullscreen_button = ttk.Button(bar, command=host._toggle_preview_fullscreen)
    host._sample_fullscreen_button.pack(side="right", padx=6)
    filters = host._sample_filter_bar = ttk.Frame(host.preview_list_lf, padding=(0, 4))
    first = host.preview_list_lf.pack_slaves()
    filters.pack(fill="x", before=first[0] if first else None)
    select_filter = ttk.Combobox(filters, textvariable=host._sample_filter_var, state="readonly",
                                values=("Wszystkie", "W próbie", "Poza próbą"), width=14)
    select_filter.pack(side="left")
    select_filter.bind("<<ComboboxSelected>>",
                      lambda event: refresh_sample_list(host))
    ttk.Button(filters, text="+ Do próby", command=lambda: set_sample_selection(host, True)).pack(side="left", padx=4)
    ttk.Button(filters, text="− Z próby", command=lambda: set_sample_selection(host, False)).pack(side="left")
    menu = host.preview_list_context_menu = tk.Menu(host.preview_listbox, tearoff=0)
    menu.add_command(label="Dodaj zaznaczone do próby", command=lambda: set_sample_selection(host, True))
    menu.add_command(label="Usuń zaznaczone z próby", command=lambda: set_sample_selection(host, False))
    menu.add_separator()
    menu.add_command(label="Zaznacz widoczne", command=lambda: host.preview_listbox.selection_set(0, tk.END))
    show_sample_workspace(host)
    host._populate_preview_list(on_complete=lambda: refresh_sample_ui(host))
    return True


def leave_sample_selection(host):
    context = sample_context(host)
    if not context:
        return
    if getattr(host, "_preview_fullscreen_active", False):
        host._toggle_preview_fullscreen()
    sessions = getattr(host, "_sample_sessions", {})
    sessions[context["track_id"]] = {
        "members": context["sample_member_sha256"],
        "selected": set(host._experiment_sample_selected_sha256),
    }
    host._sample_sessions = sessions
    host._cancel_preview_list_population()
    host._clear_preview_editor_state(clear_dirty=True)
    host._pz3_sample_selection_context = {}
    host._experiment_sample_selected_sha256 = set()
    host._sample_bar.destroy()
    host._sample_filter_bar.destroy()
    host.preview_list_context_menu.destroy()
    host.preview_list_context_menu = host._sample_previous_menu
    for name, value in host._sample_previous_state.items():
        setattr(host, name, value)
    for name, value in host._sample_previous_vars.items():
        getattr(host, name).set(value)
    for widget, (manager, info) in host._sample_hidden_widgets.items():
        if widget.winfo_exists():
            getattr(widget, manager)(**info)
    for order in host._sample_pack_orders.values():
        following = None
        for widget in reversed(order):
            if widget.winfo_exists() and widget.winfo_manager() == "pack":
                if following is not None:
                    widget.pack_configure(before=following)
                following = widget
    host._sample_hidden_widgets = {}
    host._sample_pack_orders = {}
    for name, text in host._sample_previous_labels.items():
        getattr(host, name).configure(text=text)
    host._sample_title_label = host._sample_fullscreen_button = None
    host._refresh_preview_list(preserve_selection=True, render_current=True)
    host._refresh_preview_workspace_visibility()
    from .pz3_gt_route import refresh_experiment_gt_ui
    refresh_experiment_gt_ui(host)


def _return_to_pz3(host, track_id, status):
    leave_sample_selection(host)
    loader = getattr(host.app, "_ensure_tab_loaded", None)
    training = loader("training", select=False) if callable(loader) else host.app.tabs["training"]
    host.app.notebook.select(training.frame)
    training._ensure_step4_tracks_tab_built()
    training.main_nb.select(training.tab_tracks)
    panel = training.evaluation_tracks_panel
    panel.refresh_tracks(select_track_id=track_id)
    panel._set_status(status)
    host.app.update_status(status, "success")


def cancel_sample_review(host):
    context = sample_context(host)
    if context and not getattr(host, "is_processing", False):
        _return_to_pz3(host, context["track_id"], "Anulowano przekazanie próby. Skład draftu pozostaje bez zmian.")


def return_sample_to_pz3(host):
    context = sample_context(host)
    if not context or getattr(host, "is_processing", False):
        return
    selected = set(host._experiment_sample_selected_sha256)
    if not selected:
        messagebox.showwarning("Próba eksperymentalna", "Wybierz co najmniej jedno zdjęcie.", parent=host.frame)
        return
    if not messagebox.askyesno(
        "Zatwierdzić próbę eksperymentalną?",
        f"Pula po audycie: {context['candidate_count']}\nWybrano: {len(selected)}\n"
        f"Usuwane z draftu: {context['candidate_count'] - len(selected)}\n\n"
        "Oryginalne pliki źródłowe pozostaną bez zmian.\n"
        "Po zatwierdzeniu ponownie audytuj próbę przed przygotowaniem GT.",
        parent=host.frame,
    ):
        return
    service = EvaluationTrackService(context.get("workspace") or CONFIG.WORKSPACE_DIR)
    progress = BatchProgressDialog(host.frame, title="Zapisywanie próby")
    try:
        result = progress.run(lambda update: service.commit_sample_selection(
            context["track_id"], keep_sha256=selected,
            expected_member_sha256=context["sample_member_sha256"],
            expected_audit_id=context["sample_audit_id"], progress=update,
        ))
    except Exception as exc:
        progress.close()
        messagebox.showerror("Zapis próby", str(exc), parent=host.frame)
        return
    progress.close()
    _return_to_pz3(
        host, context["track_id"],
        f"Wybrano próbę: {result['selected_count']} z {result['candidate_count']} zdjęć. "
        "Ponownie audytuj finalną pulę przed przygotowaniem GT.",
    )
