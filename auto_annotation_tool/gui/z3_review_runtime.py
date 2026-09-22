#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jawny przepływ Z3/PZ2: RAW -> REVIEW -> GOLD."""

from __future__ import annotations

import copy
from datetime import datetime
from tkinter import messagebox

from .z3_gt_contract import revision_ids_from_data

REVIEW_SCHEMA = "alpr.pz2.review.v1"
REVIEW_IN_PROGRESS = "in_progress"
REVIEW_APPROVED = "approved"

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def get_review_state_status(data: dict | None) -> str:
    if not isinstance(data, dict):
        return ""
    state = data.get("review_state")
    if not isinstance(state, dict):
        return ""
    return str(state.get("status", "") or "").strip().lower()


def _normalize_reference_text(value) -> str:
    return str(value or "").strip().upper()


def build_review_reference_snapshot(data: dict | None) -> dict:
    source = data if isinstance(data, dict) else {}
    attrs = source.get("plate_attributes")
    if not isinstance(attrs, dict):
        attrs = {}

    ground_truth_text = _normalize_reference_text(
        source.get("ground_truth_text")
        or attrs.get("ground_truth_text")
    )

    source_annotation_id = str(
        source.get("source_annotation_id")
        or attrs.get("source_annotation_id")
        or ""
    ).strip()
    plate_annotation_id = str(
        source.get("plate_annotation_id")
        or attrs.get("plate_annotation_id")
        or ""
    ).strip()
    ground_truth_source = str(
        source.get("ground_truth_source")
        or attrs.get("ground_truth_source")
        or ""
    ).strip()

    return {
        "gt_hash": str(source.get("source_gt_hash") or "").strip(),
        "gt_revision_ids": revision_ids_from_data(
            source,
            "source_gt_revision_ids",
            "source_gt_revision_id",
        ),
        "geometry_revision_ids": revision_ids_from_data(
            source,
            "source_geometry_revision_ids",
            "source_geometry_revision_id",
        ),
        "ground_truth_text": ground_truth_text,
        "source_annotation_id": source_annotation_id,
        "plate_annotation_id": plate_annotation_id,
        "ground_truth_source": ground_truth_source,
    }


def review_approval_is_current(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False

    state = data.get("review_state")
    if not isinstance(state, dict):
        return False
    if str(state.get("status", "") or "").strip().lower() != REVIEW_APPROVED:
        return False

    approved_reference = state.get("approved_reference")
    if not isinstance(approved_reference, dict):
        return False

    return approved_reference == build_review_reference_snapshot(data)


def reconcile_review_approval(data: dict | None) -> bool:
    """
    Reopen REVIEW when GT/reference identity changed after human GOLD approval.
    A new RAW run is intentionally ignored here.
    """
    if not isinstance(data, dict):
        return False

    state = data.get("review_state")
    if not isinstance(state, dict):
        return False
    if str(state.get("status", "") or "").strip().lower() != REVIEW_APPROVED:
        return False
    if review_approval_is_current(data):
        return False

    now = _now_iso()
    previous_reference = copy.deepcopy(state.get("approved_reference"))

    state["status"] = REVIEW_IN_PROGRESS
    state["approved_at"] = None
    state["modified_at"] = now
    state["approval_invalidated_at"] = now
    state["approval_invalidated_reason"] = "reference_changed"
    state["invalidated_approved_reference"] = previous_reference
    state["current_reference"] = build_review_reference_snapshot(data)

    data["status"] = "needs_fix"

    gold_state = data.get("gold_state")
    if not isinstance(gold_state, dict):
        gold_state = {}
        data["gold_state"] = gold_state
    gold_state["candidate"] = False
    gold_state["approved"] = False

    return True



def reconcile_review_gold_integrity(data: dict | None) -> bool:
    """
    Keep persisted REVIEW/GOLD state fail-closed and internally consistent.

    Legacy records without review_state are intentionally untouched.
    """
    if not isinstance(data, dict):
        return False

    state = data.get("review_state")
    if not isinstance(state, dict):
        return False

    changed = False
    review_status = str(state.get("status", "") or "").strip().lower()

    gold_state = data.get("gold_state")
    if not isinstance(gold_state, dict):
        gold_state = {}
        data["gold_state"] = gold_state
        changed = True

    if review_status == REVIEW_APPROVED:
        if not review_approval_is_current(data):
            return bool(reconcile_review_approval(data) or changed)

        persisted_status = str(
            data.get("status", "unknown") or "unknown"
        ).strip().lower()
        gold_approved = bool(gold_state.get("approved", False))
        if persisted_status != "perfect" or not gold_approved:
            now = _now_iso()
            previous_reference = copy.deepcopy(
                state.get("approved_reference")
            )
            state["status"] = REVIEW_IN_PROGRESS
            state["approved_at"] = None
            state["modified_at"] = now
            state["approval_invalidated_at"] = now
            state["approval_invalidated_reason"] = (
                "approval_state_incomplete"
            )
            state["invalidated_approved_reference"] = previous_reference
            state["current_reference"] = build_review_reference_snapshot(data)
            data["status"] = "needs_fix"
            gold_state["candidate"] = False
            gold_state["approved"] = False
            return True

        if not bool(gold_state.get("candidate", False)):
            gold_state["candidate"] = True
            changed = True
        return changed

    if review_status == REVIEW_IN_PROGRESS:
        if str(data.get("status", "") or "").strip().lower() != "needs_fix":
            data["status"] = "needs_fix"
            changed = True
        if state.get("approved_at") is not None:
            state["approved_at"] = None
            changed = True
        if "approved_reference" in state:
            state.pop("approved_reference", None)
            changed = True
        if bool(gold_state.get("candidate", False)):
            gold_state["candidate"] = False
            changed = True
        if bool(gold_state.get("approved", False)):
            gold_state["approved"] = False
            changed = True
        return changed

    now = _now_iso()
    state["schema"] = REVIEW_SCHEMA
    state["status"] = REVIEW_IN_PROGRESS
    state["approved_at"] = None
    state["modified_at"] = now
    state["approval_invalidated_at"] = now
    state["approval_invalidated_reason"] = "invalid_review_state"
    state.pop("approved_reference", None)
    data["status"] = "needs_fix"
    gold_state["candidate"] = False
    gold_state["approved"] = False
    return True


def _resolve_plate(host, plate_id=None):
    pid = str(plate_id or getattr(host, "_preview_active_pid", "") or "").strip()
    metadata = getattr(host, "preview_metadata", None)
    if not pid or not isinstance(metadata, dict):
        return "", None
    data = metadata.get(pid)
    return pid, data if isinstance(data, dict) else None

def _refresh_after_change(host, pid: str, *, persist: bool, message: str = "") -> None:
    if persist:
        host._persist_preview_metadata(
            success_message=None,
            refresh_list=False,
            sync_access=True,
        )
    try:
        host._refresh_preview_listbox_row(pid)
    except Exception:
        pass
    try:
        if host._get_preview_box_mode_key() != "FINAL":
            label = (
                host._get_preview_box_mode_label("FINAL")
                if hasattr(host, "_get_preview_box_mode_label")
                else "Końcowe ramki treningowe"
            )
            host.preview_box_mode_var.set(label)
    except Exception:
        pass
    try:
        host._refresh_detection_review_controls()
    except Exception:
        pass
    try:
        host._on_preview_select(None)
    except Exception:
        pass
    if message:
        try:
            host._update_preview_edit_status(message, tone="info")
        except Exception:
            pass

def start_review_from_raw(
    host,
    plate_id=None,
    *,
    overwrite: bool = False,
    persist: bool = True,
    quiet: bool = False,
):
    """Create mutable REVIEW as a deep copy of frozen RAW."""
    pid, data = _resolve_plate(host, plate_id)
    if not isinstance(data, dict):
        result = {"ok": False, "reason": "no_active_plate", "plate_id": pid}
        if not quiet:
            messagebox.showinfo("REVIEW", "Wybierz tablicę w PZ2.")
        return result

    raw_detection = data.get("raw_detection")
    if not isinstance(raw_detection, dict):
        result = {"ok": False, "reason": "missing_raw_detection", "plate_id": pid}
        if not quiet:
            messagebox.showinfo(
                "REVIEW",
                "Ta tablica nie ma jeszcze wyniku RAW. Najpierw uruchom RAW.",
            )
        return result

    raw_chars = raw_detection.get("characters", [])
    if not isinstance(raw_chars, list):
        raw_chars = []

    current_review_status = get_review_state_status(data)
    existing_chars = data.get("characters", [])
    existing_chars = existing_chars if isinstance(existing_chars, list) else []

    if not overwrite and (current_review_status or existing_chars):
        result = {
            "ok": False,
            "reason": "review_exists",
            "plate_id": pid,
            "review_status": current_review_status,
            "character_count": len(existing_chars),
        }
        if not quiet:
            messagebox.showinfo(
                "REVIEW już istnieje",
                "Nie nadpisano istniejącej warstwy REVIEW/GOLD.",
            )
        return result

    review_chars = copy.deepcopy(raw_chars)
    try:
        host._update_preview_plate_layout_metadata(data, review_chars)
    except Exception:
        pass
    try:
        review_chars = host._annotate_preview_character_reading_positions(
            host._sort_character_records_by_x(review_chars, data=data),
            data=data,
        )
    except Exception:
        try:
            review_chars = host._sort_character_records_by_x(review_chars, data=data)
        except Exception:
            pass

    now = _now_iso()
    raw_hash = str(raw_detection.get("result_hash", "") or "").strip()

    data["characters"] = review_chars
    data["status"] = "needs_fix"
    data["fusion_strategy"] = "review_from_raw"
    data["fusion_details"] = {
        "source": "raw_detection",
        "raw_result_hash": raw_hash,
    }
    data["review_state"] = {
        "schema": REVIEW_SCHEMA,
        "status": REVIEW_IN_PROGRESS,
        "source": "raw_detection",
        "raw_result_hash": raw_hash,
        "started_at": now,
        "modified_at": now,
        "approved_at": None,
    }

    gold_state = data.get("gold_state")
    if not isinstance(gold_state, dict):
        gold_state = {}
        data["gold_state"] = gold_state
    gold_state["candidate"] = False
    gold_state["approved"] = False
    gold_state["approved_from_bucket"] = str(
        gold_state.get("approved_from_bucket", "") or ""
    )

    try:
        host._ensure_plate_source_metadata(
            data,
            plate_id=pid,
            default_bucket="auto_preview",
            default_origin="pz2_detect",
            modified_by="human",
        )
    except Exception:
        pass

    _refresh_after_change(
        host,
        pid,
        persist=persist,
        message="Rozpoczęto REVIEW z zamrożonego wyniku RAW.",
    )
    return {
        "ok": True,
        "reason": "",
        "plate_id": pid,
        "review_status": REVIEW_IN_PROGRESS,
        "character_count": len(review_chars),
        "raw_result_hash": raw_hash,
    }

def mark_review_edit_started(host, data: dict | None):
    """Any human edit opens/reopens REVIEW and invalidates GOLD approval."""
    if not isinstance(data, dict):
        return None

    now = _now_iso()
    raw = data.get("raw_detection")
    raw_hash = str(raw.get("result_hash", "") or "").strip() if isinstance(raw, dict) else ""

    state = data.get("review_state")
    previous_status = (
        str(state.get("status", "") or "").strip().lower()
        if isinstance(state, dict)
        else ""
    )
    if not isinstance(state, dict):
        state = {
            "schema": REVIEW_SCHEMA,
            "source": "raw_detection" if isinstance(raw, dict) else "manual_editor",
            "raw_result_hash": raw_hash,
            "started_at": now,
        }
        data["review_state"] = state

    state["schema"] = REVIEW_SCHEMA
    state["status"] = REVIEW_IN_PROGRESS
    state["modified_at"] = now
    state["approved_at"] = None
    state.pop("approved_reference", None)
    if not str(state.get("source", "") or "").strip():
        state["source"] = "raw_detection" if isinstance(raw, dict) else "manual_editor"
    if raw_hash and not str(state.get("raw_result_hash", "") or "").strip():
        state["raw_result_hash"] = raw_hash
    if not str(state.get("started_at", "") or "").strip():
        state["started_at"] = now
    if previous_status == REVIEW_APPROVED:
        state["reopened_at"] = now

    gold_state = data.get("gold_state")
    if not isinstance(gold_state, dict):
        gold_state = {}
        data["gold_state"] = gold_state
    gold_state["candidate"] = False
    gold_state["approved"] = False
    return state

def confirm_review_gold(
    host,
    plate_id=None,
    *,
    persist: bool = True,
    quiet: bool = False,
):
    """Explicit human approval. Only a valid REVIEW may become GOLD/perfect."""
    pid, data = _resolve_plate(host, plate_id)
    if not isinstance(data, dict):
        result = {"ok": False, "reason": "no_active_plate", "plate_id": pid}
        if not quiet:
            messagebox.showinfo("GOLD", "Wybierz tablicę w PZ2.")
        return result

    state = data.get("review_state")
    if not isinstance(state, dict) or get_review_state_status(data) != REVIEW_IN_PROGRESS:
        result = {"ok": False, "reason": "review_not_in_progress", "plate_id": pid}
        if not quiet:
            messagebox.showinfo("GOLD", "Najpierw rozpocznij lub wykonaj korektę REVIEW.")
        return result

    chars = data.get("characters", [])
    if not isinstance(chars, list) or not chars:
        result = {"ok": False, "reason": "empty_review", "plate_id": pid}
        if not quiet:
            messagebox.showwarning(
                "Nie można zatwierdzić GOLD",
                "REVIEW nie zawiera żadnych ramek znaków.",
            )
        return result

    probe = copy.deepcopy(data)
    probe_state = dict(probe.get("review_state") or {})
    probe_state["status"] = REVIEW_APPROVED
    probe["review_state"] = probe_state

    try:
        resolved_status = str(
            host._derive_preview_status_from_data(probe, chars) or "needs_fix"
        ).strip().lower()
    except Exception:
        resolved_status = "needs_fix"

    if resolved_status != "perfect":
        data["status"] = "needs_fix"
        result = {
            "ok": False,
            "reason": "review_not_perfect",
            "plate_id": pid,
            "resolved_status": resolved_status,
        }
        if not quiet:
            messagebox.showwarning(
                "REVIEW nadal wymaga korekty",
                "Aktualne boxy/znaki nie spełniają warunku perfect. "
                "Popraw REVIEW i zatwierdź ponownie.",
            )
        return result

    now = _now_iso()
    state["schema"] = REVIEW_SCHEMA
    state["status"] = REVIEW_APPROVED
    state["approved_at"] = now
    state["modified_at"] = now
    state["approved_by"] = "human"
    state["approved_reference"] = build_review_reference_snapshot(data)
    state.pop("approval_invalidated_at", None)
    state.pop("approval_invalidated_reason", None)
    state.pop("invalidated_approved_reference", None)
    state.pop("current_reference", None)
    data["status"] = "perfect"

    try:
        host._ensure_plate_source_metadata(data, plate_id=pid, modified_by="human")
    except Exception:
        pass

    gold_state = data.get("gold_state")
    if not isinstance(gold_state, dict):
        gold_state = {}
        data["gold_state"] = gold_state
    gold_state["candidate"] = True
    gold_state["approved"] = True
    try:
        bucket = str(host._get_plate_source_bucket(data) or "").strip()
    except Exception:
        source_info = data.get("source_info")
        bucket = (
            str(source_info.get("bucket", "") or "").strip()
            if isinstance(source_info, dict)
            else ""
        )
    if bucket:
        gold_state["approved_from_bucket"] = bucket

    _refresh_after_change(
        host,
        pid,
        persist=persist,
        message="REVIEW zatwierdzony jako GOLD.",
    )

    if not quiet:
        try:
            messagebox.showinfo("GOLD", "Tablica została jawnie zatwierdzona jako GOLD.")
        except Exception:
            pass

    return {
        "ok": True,
        "reason": "",
        "plate_id": pid,
        "review_status": REVIEW_APPROVED,
        "status": "perfect",
    }
