"""Z2 review controls for selecting the final PZ3 sample and its GT."""
from tkinter import messagebox, ttk

from ..config import CONFIG
from ..registry import EvaluationTrackService
from .pz3_participant_audit import BatchProgressDialog


def sample_context(host):
    context = getattr(host, "_experiment_gt_context", None)
    if isinstance(context, dict) and context.get("source") == "pz3" and context.get("sample_selection"):
        return context
    return None


def approved_sample_names(host):
    context = sample_context(host)
    if not context:
        return set()
    lookup = context.get("_sample_name_lookup")
    if lookup is None:
        lookup = {name.casefold(): name for name in context["sample_member_sha256"]}
        context["_sample_name_lookup"] = lookup
    names = host._get_preview_approved_filenames_base()
    return {lookup[name.casefold()] for name in names if name.casefold() in lookup}


def sample_counter(host):
    context = sample_context(host)
    if not context:
        return ""
    return f"Zatwierdzone: {len(approved_sample_names(host))} / {context['candidate_count']}"


def sample_badge_text(host, approved):
    return ("✓ W PRÓBIE" if approved else "○ POZA PRÓBĄ") + "\n" + sample_counter(host) + "\nSpacja / klik"


def toggle_sample_badge(host, event=None):
    if not sample_context(host):
        return None
    host.preview_canvas.focus_set()
    return host._on_preview_toggle_image_approval_shortcut()


def refresh_sample_ui(host):
    context = sample_context(host)
    if not context:
        button = getattr(host, "_sample_cancel_button", None)
        if button is not None:
            button.pack_forget()
        return
    label = getattr(host, "_experiment_gt_bar_label", None)
    if label is not None:
        label.configure(text=f"Próba i Ground Truth · {context.get('name') or context['track_id']}\n"
                             + sample_counter(host))
    button = getattr(host, "_experiment_gt_return_button", None)
    if button is not None:
        button.configure(text="Przekaż zatwierdzone do PZ3")
    bar = getattr(host, "_experiment_gt_bar", None)
    cancel = getattr(host, "_sample_cancel_button", None)
    if bar is not None:
        if cancel is None or not cancel.winfo_exists():
            cancel = host._sample_cancel_button = ttk.Button(
                bar, text="Wróć bez przekazania", command=lambda: cancel_sample_review(host))
        cancel.pack(side="right", padx=(0, 8))
        cancel.configure(state="disabled" if getattr(host, "is_processing", False) else "normal")
    hint = getattr(host, "manual_stage_help_lbl", None)
    if hint is not None:
        hint.configure(text="Sprawdź ramki i narożniki. Spacja zatwierdza lub cofa zatwierdzenie zdjęcia. "
                            "Do próby i GT trafią wyłącznie zatwierdzone zdjęcia.")
    status = getattr(host, "preview_image_status_lbl", None)
    ann = host._get_preview_annotation()
    if status is not None and ann is not None:
        status.configure(text=sample_badge_text(host, host._preview_annotation_is_explicitly_approved(ann)))
    place = getattr(host, "_place_preview_image_status_overlay", None)
    if callable(place):
        place(force_render=True)


def _return_to_pz3(host, track_id, status):
    if getattr(host, "_preview_fullscreen_active", False):
        host._toggle_preview_fullscreen()
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
    panel = training.evaluation_tracks_panel
    panel.refresh_tracks(select_track_id=track_id)
    panel._set_status(status)
    host.app.update_status(status, "success")


def cancel_sample_review(host):
    context = sample_context(host)
    if not context or getattr(host, "is_processing", False):
        return
    if not host._save_preview_edits(interactive=True):
        return
    EvaluationTrackService(CONFIG.WORKSPACE_DIR).deactivate_z2_context(track_id=context["track_id"])
    _return_to_pz3(host, context["track_id"], "Wrócono do PZ3. Skład draftu pozostaje bez zmian.")


def return_sample_to_pz3(host):
    context = sample_context(host)
    if not context or getattr(host, "is_processing", False):
        return
    names = approved_sample_names(host)
    if not names:
        messagebox.showwarning("Próba eksperymentalna", "Zatwierdź co najmniej jedno zdjęcie.", parent=host.frame)
        return
    if not messagebox.askyesno(
        "Przekazać próbę i GT do PZ3?",
        f"Pula po audycie: {context['candidate_count']}\n"
        f"Zatwierdzone do próby i GT: {len(names)}\n"
        f"Usuwane z draftu: {context['candidate_count'] - len(names)}\n\n"
        "Oryginalne pliki źródłowe pozostaną bez zmian.\n"
        "Po przekazaniu ponownie audytuj finalną próbę przed VERIFY i SEAL.",
        parent=host.frame,
    ):
        return
    if not host._save_preview_edits(interactive=True):
        return
    xml = host._get_current_annotation_xml_path()
    service = EvaluationTrackService(CONFIG.WORKSPACE_DIR)
    progress = BatchProgressDialog(host.frame, title="Przekazywanie próby i GT")
    try:
        result = progress.run(lambda update: service.commit_reviewed_sample(
            context["track_id"],
            keep_sha256={context["sample_member_sha256"][name] for name in names},
            expected_member_sha256=context["sample_member_sha256"],
            expected_audit_id=context["sample_audit_id"],
            working_xml=xml, progress=update,
        ))
    except Exception as exc:
        progress.close()
        messagebox.showerror("Przekazanie próby i GT", str(exc), parent=host.frame)
        return
    progress.close()
    # Refresh Z2 against the committed subset so reopening the tab cannot expose
    # stale candidates whose working copies have just been removed.
    host._experiment_gt_context = {**context, "sample_selection": False}
    try:
        reopened = host._open_existing_run_for_manual_review(
            run_dir=xml.parent, allow_fallback=False, show_dialog=False,
            entry_mode="continue", from_auto=False,
        )
    except Exception:
        reopened = False
    _return_to_pz3(
        host, context["track_id"],
        f"Przekazano próbę i GT: {result['selected_count']} z {result['candidate_count']} zdjęć. "
        "Ponownie audytuj finalną pulę przed weryfikacją.",
    )
    if not reopened:
        messagebox.showwarning(
            "Próba i GT zapisane",
            "Zapis zakończył się poprawnie, ale podgląd Z2 wymaga ponownego otwarcia z PZ3.",
            parent=host.app.root,
        )
