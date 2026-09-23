"""Selection and group approval actions for the PZ2 plate list."""
import time
import tkinter as tk

from . import z3_review_runtime as review
from .z3_metadata_cache import mark_preview_metadata_changed


def selected_plate_ids(host):
    ids = getattr(host, "_listbox_pid_by_index", []) or []
    return [ids[int(index)] for index in host.plates_listbox.curselection() if 0 <= int(index) < len(ids)]


def capture_selection(host):
    ids = getattr(host, "_listbox_pid_by_index", []) or []
    box = host.plates_listbox
    def pid_at(kind):
        try:
            index = int(box.index(kind))
            return ids[index] if 0 <= index < len(ids) else None
        except (tk.TclError, ValueError):
            return None
    return {"selected": selected_plate_ids(host), "active": pid_at(tk.ACTIVE),
            "anchor": pid_at(tk.ANCHOR), "view": box.yview()[0]}


def restore_selection(host, saved, *, default_first=True):
    ids = getattr(host, "_listbox_pid_by_index", []) or []
    positions = {pid: index for index, pid in enumerate(ids)}
    rows = [positions[pid] for pid in saved.get("selected", []) if pid in positions]
    if not rows and ids and default_first:
        rows = [0]
    box = host.plates_listbox
    host._clear_listbox_selection_fast(box)
    for row in rows:
        box.selection_set(row)
    active = positions.get(saved.get("active"))
    if active not in rows:
        active = rows[0] if rows else None
    if active is not None:
        box.activate(active)
        box.selection_anchor(positions.get(saved.get("anchor"), active))
    box.yview_moveto(saved.get("view", 0))
    return active


def select_all(host, event=None):
    if getattr(host, "_preview_review_batch_running", False):
        return "break"
    host.plates_listbox.selection_set(0, tk.END)
    return "break"


def change_plate_approval(host, plate_id, approved):
    data = host.preview_metadata.get(plate_id)
    if not isinstance(data, dict):
        return {"ok": False, "reason": "missing_plate"}
    status = review.get_review_state_status(data)
    if not approved:
        if status != review.REVIEW_APPROVED:
            return {"ok": True, "unchanged": True}
        review.mark_review_edit_started(host, data)
        data["status"] = "needs_fix"
        return {"ok": True}
    if (status == review.REVIEW_APPROVED and host._review_approval_is_current(data)
            and host._get_review_quality_status(data) == "perfect"):
        return {"ok": True, "unchanged": True}
    if not status and not data.get("characters"):
        return {"ok": False, "reason": "working_annotation_missing"}
    elif status != review.REVIEW_IN_PROGRESS:
        review.mark_review_edit_started(host, data)
    return review.confirm_review_gold(host, plate_id, persist=False, quiet=True, refresh=False)


def run_selected_review_action(host, approved=True):
    if (getattr(host, "_preview_review_batch_running", False)
            or getattr(host, "is_processing", False) or getattr(host, "fast_test_running", False)):
        return None
    ids = selected_plate_ids(host)
    if not ids:
        return None
    metadata = host.preview_metadata
    reset_token = getattr(host, "_project_reset_token", None)
    result = {"total": len(ids), "processed": 0, "changed": [], "unchanged": 0,
              "failed": [], "dirty": [], "approved": bool(approved), "done": False}
    host._preview_review_batch_running = True
    host._preview_review_batch_result = result
    host._refresh_detection_review_controls()
    def destroyed(event):
        if event.widget is host.frame:
            job = result.get("after_id")
            if job:
                host.frame.after_cancel(job)
            host._preview_review_batch_running = False
            result.update(done=True, cancelled=True)
    destroy_binding = host.frame.bind("<Destroy>", destroyed, add="+")

    def detach_callback():
        host.frame.unbind("<Destroy>", destroy_binding)

    def step():
        result["after_id"] = None
        if metadata is not host.preview_metadata or reset_token != getattr(host, "_project_reset_token", None):
            result.update(done=True, cancelled=True)
            host._preview_review_batch_running = False
            host._refresh_detection_review_controls()
            detach_callback()
            return
        deadline = time.perf_counter() + .015
        chunk_start = result["processed"]
        while result["processed"] < len(ids):
            pid = ids[result["processed"]]
            try:
                outcome = change_plate_approval(host, pid, approved)
            except Exception as exc:
                outcome = {"ok": False, "reason": "validation_error", "error": str(exc)}
            if outcome.get("unchanged"):
                result["unchanged"] += 1
            elif outcome.get("ok"):
                result["changed"].append(pid)
            else:
                result["failed"].append({"plate_id": pid, "reason": outcome.get("reason", "review_not_perfect")})
            if not outcome.get("unchanged") and outcome.get("reason") not in {"missing_plate", "missing_raw_detection"}:
                result["dirty"].append(pid)
            host._refresh_preview_listbox_row(pid)
            result["processed"] += 1
            if time.perf_counter() >= deadline or result["processed"] - chunk_start >= 25:
                break
        pending = getattr(host, "_preview_pending_save_pids", None)
        if not isinstance(pending, set):
            pending = host._preview_pending_save_pids = set()
        pending.update(result["dirty"])
        if result["processed"] < len(ids):
            # Coalesce writes while working; leaving the run can still flush
            # completed rows through the existing autosave lifecycle.
            if pending:
                host._schedule_preview_metadata_save(delay_ms=180)
            host._update_preview_edit_status(f"Aktualizacja zatwierdzeń: {result['processed']}/{len(ids)}", tone="info")
            result["after_id"] = host.frame.after(1, step)
            return

        host._preview_review_batch_running = False
        # Failed approval can still create a valid, unfinished working review.
        mark_preview_metadata_changed(host)
        if pending:
            host._schedule_preview_metadata_save(delay_ms=30)
        host.preview_box_mode_var.set(host._get_preview_box_mode_label("AUTO"))
        host._refresh_detection_review_controls()
        host._update_preview_info_label()
        host._sync_step3_access_from_preview_state(metadata)
        host._on_preview_select(None)
        verb = "Zatwierdzono" if approved else "Cofnięto zatwierdzenie"
        message = f"{verb}: {len(result['changed'])}/{len(ids)}."
        if result["unchanged"]:
            message += f" Bez zmian: {result['unchanged']}."
        if result["failed"]:
            examples = ", ".join(item["plate_id"] for item in result["failed"][:3])
            message += f" Wymaga poprawy: {len(result['failed'])} ({examples})."
        host._update_preview_edit_status(message, tone="warning" if result["failed"] else "success")
        result["done"] = True
        detach_callback()

    result["after_id"] = host.frame.after(1, step)
    return result


def show_context_menu(host, event):
    if getattr(host, "_preview_review_batch_running", False):
        return "break"
    box = host.plates_listbox
    if not box.size():
        return "break"
    index = int(box.nearest(event.y))
    bounds = box.bbox(index)
    if bounds is None or not bounds[1] <= event.y < bounds[1] + bounds[3]:
        return "break"
    if not box.selection_includes(index):
        host._clear_listbox_selection_fast(box)
        box.selection_set(index)
        box.selection_anchor(index)
    box.activate(index)
    box.focus_set()
    host._schedule_preview_select_render(delay_ms=1)
    old = getattr(host, "_preview_list_context_menu", None)
    if old is not None:
        old.destroy()
    menu = host._preview_list_context_menu = tk.Menu(box, tearoff=False)
    total = len(selected_plate_ids(host))
    busy = bool(getattr(host, "is_processing", False) or getattr(host, "fast_test_running", False))
    state = tk.DISABLED if busy else tk.NORMAL
    menu.add_command(label=f"Zatwierdź zaznaczone ({total})", state=state,
                     command=lambda: run_selected_review_action(host, True))
    menu.add_command(label=f"Cofnij zatwierdzenie ({total})", state=state,
                     command=lambda: run_selected_review_action(host, False))
    menu.add_separator()
    menu.add_command(label="Zaznacz wszystkie", accelerator="Ctrl+A", command=lambda: select_all(host))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
    return "break"
