"""RAW selection in the existing Z2 preview, independent of annotation approval."""
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from ..config import CONFIG
from ..data_models import ImageAnnotation
from ..registry import EvaluationTrackService
from .pz3_participant_audit import BatchProgressDialog
from ..registry.sample_labels import SampleLabels
from ..registry.sample_selection import save_sample_review_draft, clear_sample_review_draft
from .pz3_sample_labels_ui import label_state, SampleLabelsPanel, build_label_menu


def sample_context(host):
    context = getattr(host, "_pz3_sample_selection_context", None)
    if isinstance(context, dict) and context.get("purpose") == "sample_selection" and context.get("track_id"):
        return context
    return None


def persist_sample_review_draft(host):
    context = sample_context(host)
    if not context or not context.get("workspace") or getattr(host, "is_processing", False):
        return False
    state = getattr(host, "_sample_label_state", None)
    if not isinstance(state, SampleLabels):
        state = label_state(host)
    try:
        service = EvaluationTrackService(context.get("workspace") or CONFIG.WORKSPACE_DIR)
        save_sample_review_draft(
            service,
            context["track_id"],
            selected_sha256=set(host._experiment_sample_selected_sha256),
            sample_labels=state.payload(context["track_id"]),
            active_label=state.active_id,
            expected_member_sha256=context["sample_member_sha256"],
        )
        host._sample_draft_save_error = ""
        return True
    except Exception as exc:
        host._sample_draft_save_error = str(exc)
        return False


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
    indices = [int(i) for i in indices if 0 <= int(i) < len(host.current_annotations)]
    shas = [context["sample_member_sha256"].get(host.current_annotations[i].filename) for i in indices]
    label_state(host).set_membership((sha for sha in shas if sha), selected)
    persist_sample_review_draft(host)
    refresh_sample_rows(host, indices, membership_changed=True)
    refresh_sample_ui(host)


def refresh_sample_rows(host, indices, *, membership_changed=False):
    """Touch only affected Listbox rows; do not re-render the current image."""
    from bisect import bisect_left
    host._sample_selection_version = getattr(host, "_sample_selection_version", 0) + 1
    listbox = getattr(host, "preview_listbox", None)
    filter_var = getattr(host, "_sample_filter_var", None)
    if listbox is None or not indices:
        return
    active, anchor = listbox.index(tk.ACTIVE), listbox.index(tk.ANCHOR)
    view = listbox.yview()
    mode = filter_var.get() if filter_var is not None else "Wszystkie"
    mapping = getattr(host, "_preview_list_display_index_map", None)
    if membership_changed and mode != "Wszystkie":
        visible = list(getattr(host, "_preview_list_display_indices", ()))
        previous = list(visible)
        for index in sorted(set(indices), reverse=True):
            position = bisect_left(visible, index)
            present = position < len(visible) and visible[position] == index
            included = sample_selected(host, host.current_annotations[index]) == (mode == "W próbie")
            if present and not included:
                visible.pop(position)
                listbox.delete(position)
            elif not present and included:
                visible.insert(position, index)
                listbox.insert(position, sample_list_text(host, host.current_annotations[index]))
        host._preview_list_display_indices = visible
        mapping = host._preview_list_display_index_map = {index: row for row, index in enumerate(visible)}
        if previous:
            active = mapping.get(previous[min(active, len(previous)-1)], min(active, max(0, len(visible)-1)))
            anchor = mapping.get(previous[min(anchor, len(previous)-1)], active)
    for index in set(indices):
        # The general Z2 accessor copies its whole lookup; use the existing map.
        display = mapping.get(index) if isinstance(mapping, dict) else host._get_preview_display_index(index)
        if display is not None:
            selected = listbox.selection_includes(display)
            listbox.delete(display)
            listbox.insert(display, sample_list_text(host, host.current_annotations[index]))
            if selected:
                listbox.selection_set(display)
    listbox.activate(active)
    listbox.selection_anchor(anchor)
    if view:
        listbox.yview_moveto(view[0])


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
    state = getattr(host, "_sample_label_state", None)
    context = sample_context(host)
    label = state.label_for(context["sample_member_sha256"].get(ann.filename)) if state else ""
    label = label if len(label) <= 18 else label[:17] + "…"
    return f"{'[' + status + ']':<13} {label:<18} {ann.filename}"


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
        state = label_state(host)
        active = state.labels.get(state.active_id, "")
        active = (active[:23] + "…") if len(active) > 24 else active
        active_text = f" · Aktywna: {active}" if active else ""
        label.configure(text=f"Wybór próby · {context.get('name') or context['track_id']}\n"
                             + sample_counter(host) + active_text)
    summary = getattr(host, "preview_list_summary_var", None)
    if summary is not None:
        summary.set("Surowe obrazy · " + sample_counter(host))
    fullscreen = getattr(host, "_sample_fullscreen_button", None)
    if fullscreen is not None and fullscreen.winfo_exists():
        fullscreen.configure(text="Wyjdź z pełnego ekranu" if getattr(host, "_preview_fullscreen_active", False)
                             else "Pełny ekran (Enter)")
    labels = getattr(host, "_sample_labels_panel", None)
    if labels is not None:
        labels.refresh()
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
    host._sample_previous_list_font = host.preview_listbox.cget("font")
    host._sample_previous_xscroll = host.preview_listbox.cget("xscrollcommand")
    host._clear_preview_editor_state(clear_dirty=True)
    host._pz3_sample_selection_context = dict(context)
    sessions = getattr(host, "_sample_sessions", {})
    saved = sessions.get(context["track_id"], {})
    host._experiment_sample_selected_sha256 = (
        set(saved.get("selected", ())) if saved.get("members") == context["sample_member_sha256"]
        else set(context.get("sample_initial_selected_sha256", context.get("sample_committed_sha256", ())))
    )
    saved_labels = saved.get("labels") if saved.get("members") == context["sample_member_sha256"] else context.get("sample_labels")
    host._sample_label_state = SampleLabels(host._experiment_sample_selected_sha256, saved_labels,
                                           track_id=context["track_id"])
    session_matches = saved.get("members") == context["sample_member_sha256"]
    active_label = (saved.get("active_label", "") if session_matches
                    else context.get("sample_active_label", ""))
    if active_label in host._sample_label_state.labels:
        host._sample_label_state.activate(active_label)
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
    host._sample_actual_by_sha = {context["sample_member_sha256"][ann.filename]: i
                                 for i, ann in enumerate(host.current_annotations)}
    host.preview_listbox.configure(font=("Consolas", 9))
    host._sample_list_hscroll = ttk.Scrollbar(host.preview_list_frame, orient="horizontal",
                                             command=host.preview_listbox.xview)
    def scroll_columns(first, last):
        scrollbar = host._sample_list_hscroll
        scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            scrollbar.pack_forget()
        else:
            scrollbar.pack(side="bottom", fill="x", before=host.preview_listbox)
    host.preview_listbox.configure(xscrollcommand=scroll_columns)
    host._sample_xscroll_callback = host.preview_listbox.cget("xscrollcommand")
    host.input_dir_var.set(context["source_dir"])
    host.plate_dataset_images_var.set(context["source_dir"])
    host.plate_dataset_run_var.set("")
    host._sample_filter_var = tk.StringVar(host.frame, "Wszystkie")
    bar = host._sample_bar = ttk.Frame(host.frame, padding=(10, 8))
    siblings = host.frame.pack_slaves()
    bar.pack(side="top", fill="x", before=siblings[0] if siblings else None)
    bar.columnconfigure(0, weight=1)
    host._sample_title_label = ttk.Label(bar, width=1, wraplength=300)
    host._sample_title_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    host._sample_title_label.bind("<Configure>", lambda event:
                                 host._sample_title_label.configure(wraplength=max(1, event.width)))
    actions = ttk.Frame(bar)
    actions.grid(row=0, column=1, sticky="e")
    ttk.Button(actions, text="Zatwierdź próbę i wróć do PZ3",
               command=lambda: return_sample_to_pz3(host)).pack(side="right")
    ttk.Button(actions, text="Anuluj i wróć",
               command=lambda: cancel_sample_review(host)).pack(side="right", padx=6)
    host._sample_fullscreen_button = ttk.Button(actions, command=host._toggle_preview_fullscreen)
    host._sample_fullscreen_button.pack(side="right", padx=6)
    host._sample_bar_stacked = None
    def fit_bar(event):
        stacked = event.width < actions.winfo_reqwidth() + int(240 * bar.tk.call("tk", "scaling") / 1.333)
        if stacked != host._sample_bar_stacked:
            host._sample_bar_stacked = stacked
            host._sample_title_label.grid_configure(columnspan=2 if stacked else 1,
                                                    pady=(0, 6) if stacked else 0)
            actions.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1,
                                   columnspan=2 if stacked else 1)
    bar.bind("<Configure>", fit_bar)
    filters = host._sample_filter_bar = ttk.Frame(host.preview_list_lf, padding=(0, 4))
    first = host.preview_list_lf.pack_slaves()
    filters.pack(fill="x", before=first[0] if first else None)
    select_filter = ttk.Combobox(filters, textvariable=host._sample_filter_var, state="readonly",
                                values=("Wszystkie", "W próbie", "Poza próbą"), width=14)
    select_filter.grid(row=0, column=0, sticky="w")
    select_filter.bind("<<ComboboxSelected>>",
                      lambda event: refresh_sample_list(host))
    ttk.Button(filters, text="+ Do próby", command=lambda: set_sample_selection(host, True)).grid(row=0, column=1, padx=4)
    ttk.Button(filters, text="− Z próby", command=lambda: set_sample_selection(host, False)).grid(row=0, column=2)
    ttk.Label(filters, text=f"{'STAN':<13} {'ETYKIETA':<18} PLIK", font=("Consolas", 9)).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
    host._sample_labels_panel = SampleLabelsPanel(host, host.preview_list_lf)
    host._sample_labels_panel.pack(fill="x", before=filters)
    menu = host.preview_list_context_menu = tk.Menu(host.preview_listbox, tearoff=0)
    menu.add_command(label="Dodaj zaznaczone do próby", command=lambda: set_sample_selection(host, True))
    menu.add_command(label="Usuń zaznaczone z próby", command=lambda: set_sample_selection(host, False))
    host._sample_labels_menu = build_label_menu(host, menu)
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
        "labels": label_state(host).payload(context["track_id"]),
        "active_label": label_state(host).active_id,
    }
    host._sample_sessions = sessions
    host._cancel_preview_list_population()
    host._clear_preview_editor_state(clear_dirty=True)
    host._pz3_sample_selection_context = {}
    host._experiment_sample_selected_sha256 = set()
    host._sample_bar.destroy()
    host._sample_filter_bar.destroy()
    host._sample_labels_panel.destroy()
    host._sample_labels_panel = None
    host._sample_label_state = None
    host._sample_actual_by_sha = {}
    host.preview_listbox.configure(font=host._sample_previous_list_font)
    host.preview_listbox.configure(xscrollcommand=host._sample_previous_xscroll)
    host.preview_listbox.deletecommand(host._sample_xscroll_callback)
    host._sample_list_hscroll.destroy()
    host.preview_listbox.xview_moveto(0)
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
    state = getattr(host, "_sample_label_state", None)
    labels = state.payload(context["track_id"]) if isinstance(state, SampleLabels) else None
    metadata_only = (selected == set(context.get("sample_committed_sha256", ()))
                     and labels is not None and (bool(labels["labels"]) or context.get("sample_labels") is not None))
    next_step = ("Skład próby i wynik audytu pozostaną bez zmian." if metadata_only else
                 "Po zatwierdzeniu ponownie audytuj próbę przed przygotowaniem GT.")
    if not messagebox.askyesno(
        "Zatwierdzić próbę eksperymentalną?",
        f"Pula po audycie: {context['candidate_count']}\nWybrano: {len(selected)}\n"
        f"Usuwane z draftu: {context['candidate_count'] - len(selected)}\n\n"
        "Oryginalne pliki źródłowe pozostaną bez zmian.\n"
        + next_step,
        parent=host.frame,
    ):
        return
    service = EvaluationTrackService(context.get("workspace") or CONFIG.WORKSPACE_DIR)
    progress = BatchProgressDialog(host.frame, title="Zapisywanie próby")
    try:
        if metadata_only:
            result = progress.run(lambda update: service.save_sample_labels(
                context["track_id"], sample_labels=labels,
                expected_member_sha256=context["sample_member_sha256"]))
        else:
            label_args = {"sample_labels": labels} if labels is not None else {}
            result = progress.run(lambda update: service.commit_sample_selection(
                context["track_id"], keep_sha256=selected,
                expected_member_sha256=context["sample_member_sha256"],
                expected_audit_id=context["sample_audit_id"], progress=update, **label_args,
            ))
    except Exception as exc:
        progress.close()
        messagebox.showerror("Zapis próby", str(exc), parent=host.frame)
        return
    progress.close()
    try:
        clear_sample_review_draft(service, context["track_id"])
    except Exception:
        pass
    _return_to_pz3(
        host, context["track_id"],
        ("Zapisano etykiety próbki. Skład próby i audyt pozostają bez zmian." if metadata_only else
         f"Wybrano próbę: {result['selected_count']} z {result['candidate_count']} zdjęć. "
         "Ponownie audytuj finalną pulę przed przygotowaniem GT."),
    )
