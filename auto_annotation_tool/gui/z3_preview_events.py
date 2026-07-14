#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canvas event handlers for Z3/PZ2 preview."""

import tkinter as tk
import copy
import math
import time
from pathlib import Path

from .z3_preview_ui import _get_cached_preview_photo, _get_cached_preview_source_image


def _push_preview_char_drag_history_snapshot(host, drag_state: dict) -> None:
    if not isinstance(drag_state, dict) or bool(drag_state.get("history_pushed")):
        return

    chars = host._get_preview_active_character_records(create=False)
    try:
        char_idx = int(drag_state.get("index", -1))
    except Exception:
        char_idx = -1

    original_record = drag_state.get("original_record")
    if not (0 <= char_idx < len(chars)) or not isinstance(original_record, dict):
        host._push_preview_history_snapshot()
        drag_state["history_pushed"] = True
        return

    current_record = chars[char_idx]
    try:
        chars[char_idx] = copy.deepcopy(original_record)
        host._push_preview_history_snapshot()
    finally:
        chars[char_idx] = current_record
        drag_state["history_pushed"] = True


def on_preview_list_mouse_primary(host, event):
    self = host
    try:
        self.plates_listbox.focus_set()
    except Exception:
        pass
    try:
        modifier_state = int(getattr(event, "state", 0) or 0)
    except Exception:
        modifier_state = 0

    try:
        target_index = int(self.plates_listbox.nearest(getattr(event, "y", 0)))
    except Exception:
        return None

    try:
        size = int(self.plates_listbox.size() or 0)
    except Exception:
        size = 0
    if size <= 0 or target_index < 0 or target_index >= size:
        return "break"

    # PZ2 is an editor for one plate at a time. Keeping range selection here
    # makes delayed Tk events feel like an accidental Shift-click under load.
    shift_pressed = False
    control_pressed = False
    preserve_index = self._get_current_preview_list_index()
    if preserve_index is not None and not (0 <= int(preserve_index) < size):
        preserve_index = None
    preserve_preview = False

    try:
        if shift_pressed:
            try:
                anchor_index = int(self.plates_listbox.index(tk.ANCHOR))
            except Exception:
                anchor_index = -1
            if anchor_index < 0 or anchor_index >= size:
                try:
                    anchor_index = int(self.plates_listbox.index(tk.ACTIVE))
                except Exception:
                    anchor_index = target_index
            anchor_index = max(0, min(anchor_index, size - 1))
            start_index = min(anchor_index, target_index)
            end_index = max(anchor_index, target_index)
            if not control_pressed:
                self._clear_listbox_selection_fast(self.plates_listbox)
            self.plates_listbox.selection_set(start_index, end_index)
            if preserve_index is not None:
                self.plates_listbox.activate(preserve_index)
            else:
                self.plates_listbox.activate(anchor_index)
            self.plates_listbox.see(target_index)
            preserve_preview = True
        elif control_pressed:
            if self.plates_listbox.selection_includes(target_index):
                self.plates_listbox.selection_clear(target_index)
            else:
                self.plates_listbox.selection_set(target_index)
            self.plates_listbox.selection_anchor(target_index)
            if preserve_index is not None:
                self.plates_listbox.activate(preserve_index)
            else:
                self.plates_listbox.activate(target_index)
            self.plates_listbox.see(target_index)
            preserve_preview = True
        else:
            self._suppress_preview_reload_on_list_select = True
            self._preview_fast_select_render = True
            self._clear_listbox_selection_fast(self.plates_listbox)
            self.plates_listbox.selection_set(target_index)
            self.plates_listbox.selection_anchor(target_index)
            self.plates_listbox.activate(target_index)
            self.plates_listbox.see(target_index)
    except Exception:
        return "break"

    if preserve_preview:
        self._suppress_preview_reload_on_list_select = True
        self._refresh_preview_editor_toolbar()
        return "break"

    try:
        scheduler = getattr(self, "_schedule_preview_select_render", None)
        if callable(scheduler):
            scheduler(delay_ms=1)
        else:
            self._suppress_preview_reload_on_list_select = False
            self._on_preview_select(None)
    except Exception:
        self._suppress_preview_reload_on_list_select = False
        self._on_preview_select(None)
    return "break"


def on_preview_canvas_motion(host, event=None):
    self = host
    if event is None:
        return
    click_add_state = getattr(self, "_preview_char_add_state", None)
    if isinstance(click_add_state, dict) and bool(click_add_state.get("click_draw")):
        if self._preview_point_inside_image(event.x, event.y):
            img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
            preview_bbox = [
                float(click_add_state.get("start_img_x", img_x)),
                float(click_add_state.get("start_img_y", img_y)),
                float(img_x),
                float(img_y),
            ]
            normalized_preview_bbox = self._normalize_preview_char_bbox(preview_bbox)
            click_add_state["bbox"] = normalized_preview_bbox if normalized_preview_bbox is not None else preview_bbox
            click_add_state["dirty"] = True
            if not self._redraw_preview_add_box_overlay_only():
                self._on_preview_select(None)
        self._apply_preview_canvas_cursor("crosshair")
        return
    if (
        self._preview_badge_drag_state is not None
        or getattr(self, "_preview_layout_separator_drag_state", None) is not None
        or self._preview_pan_drag_state is not None
        or self._preview_char_drag_state is not None
        or self._preview_char_add_state is not None
    ):
        return

    action_key = self._extract_preview_action_from_current_item()
    if action_key in {"reset_view", "edit_source_filename", "toggle_plate_layout", "toggle_fullscreen"}:
        previous_hover_box = getattr(self, "_preview_char_hover_index", None)
        previous_hover_label = getattr(self, "_preview_char_hover_label_index", None)
        had_hover = bool(
            previous_hover_box is not None
            or previous_hover_label is not None
        )
        self._preview_char_hover_index = None
        if not bool(getattr(self, "_preview_char_label_mode", False)):
            self._preview_char_hover_label_index = None
        self._apply_preview_canvas_cursor("hand2")
        if had_hover and bool(
            getattr(self, "_preview_char_label_mode", False)
            or getattr(self, "_preview_char_label_active_index", None) is not None
        ):
            affected = {idx for idx in (previous_hover_box, previous_hover_label) if idx is not None}
            redrawn = False
            for idx in affected:
                redrawn = self._redraw_preview_character_overlay_only(int(idx)) or redrawn
        return

    if bool(getattr(self, "_preview_char_edit_mode", False)) and not bool(getattr(self, "_preview_char_label_mode", False)):
        if self._find_preview_character_handle_hit(event.x, event.y) is not None:
            self._apply_preview_canvas_cursor("crosshair")
            return

    if self._find_preview_layout_separator_handle_hit(event.x, event.y):
        self._apply_preview_canvas_cursor("sb_v_double_arrow")
        return

    self._apply_preview_canvas_cursor()
    label_mode_active = bool(getattr(self, "_preview_char_label_mode", False))
    next_hover_box = self._find_preview_character_box_hit(event.x, event.y)
    next_hover_label = self._find_preview_char_label_hit(event.x, event.y)
    if label_mode_active:
        next_hover_label = next_hover_box if next_hover_box is not None else next_hover_label
    elif bool(getattr(self, "_preview_char_edit_mode", False)) and getattr(self, "_preview_char_label_active_index", None) is None:
        next_hover_label = None
    if (
        next_hover_box == getattr(self, "_preview_char_hover_index", None)
        and next_hover_label == getattr(self, "_preview_char_hover_label_index", None)
    ):
        return

    previous_hover_box = getattr(self, "_preview_char_hover_index", None)
    previous_hover_label = getattr(self, "_preview_char_hover_label_index", None)
    self._preview_char_hover_index = next_hover_box
    self._preview_char_hover_label_index = next_hover_label
    if label_mode_active or getattr(self, "_preview_char_label_active_index", None) is not None:
        affected = {
            idx for idx in (previous_hover_box, previous_hover_label, next_hover_box, next_hover_label)
            if idx is not None
        }
        redrawn = False
        for idx in affected:
            redrawn = self._redraw_preview_character_overlay_only(int(idx)) or redrawn


def on_preview_canvas_leave(host, event=None):
    self = host
    if (
        getattr(self, "_preview_char_drag_state", None) is not None
        or getattr(self, "_preview_char_add_state", None) is not None
        or getattr(self, "_preview_layout_separator_drag_state", None) is not None
    ):
        return
    if (
        getattr(self, "_preview_char_hover_index", None) is None
        and getattr(self, "_preview_char_hover_label_index", None) is None
    ):
        self._apply_preview_canvas_cursor()
        return
    previous_hover_box = getattr(self, "_preview_char_hover_index", None)
    previous_hover_label = getattr(self, "_preview_char_hover_label_index", None)
    self._preview_char_hover_index = None
    self._preview_char_hover_label_index = None
    self._apply_preview_canvas_cursor()
    if bool(
        getattr(self, "_preview_char_label_mode", False)
        or getattr(self, "_preview_char_label_active_index", None) is not None
    ):
        affected = {idx for idx in (previous_hover_box, previous_hover_label) if idx is not None}
        redrawn = False
        for idx in affected:
            redrawn = self._redraw_preview_character_overlay_only(int(idx)) or redrawn


def on_preview_canvas_keypress(host, event=None):
    self = host
    if event is None:
        return None

    keysym = str(getattr(event, "keysym", "") or "").lower()
    if keysym in {"alt_l", "alt_r", "option_l", "option_r"}:
        self._preview_alt_modifier_down = True
        return "break"

    label_mode_active = bool(getattr(self, "_preview_char_label_mode", False))
    if self._event_has_control_modifier(event):
        if keysym == "z":
            return self._undo_preview_edit(event)
        if keysym == "y":
            return self._redo_preview_edit(event)

    active_label_idx = getattr(self, "_preview_char_label_active_index", None)
    if keysym in {"left", "right"} and (label_mode_active or active_label_idx is not None):
        step = -1 if keysym == "left" else 1
        return self._cycle_preview_character_selection(step, activate_label=True)
    if keysym in {"up", "down"} and (label_mode_active or active_label_idx is not None):
        direction = -1 if keysym == "up" else 1
        return self._cycle_preview_character_row(direction, activate_label=True)
    typed_symbol = self._sanitize_preview_char_symbol(getattr(event, "char", ""))
    if active_label_idx is not None and typed_symbol:
        if self._assign_character_to_active_preview_label(typed_symbol):
            return "break"

    if keysym in {"return", "kp_enter"}:
        return self._on_preview_enter_fullscreen_shortcut(event)
    if keysym == "escape":
        return self._on_preview_escape_shortcut(event)
    if keysym == "q":
        return self._on_preview_prev_shortcut(event)
    if keysym == "e":
        return self._on_preview_next_shortcut(event)
    if keysym == "f":
        return self._on_preview_fit_shortcut(event)
    if keysym == "space":
        step = -1 if self._event_has_shift_modifier(event) else 1
        return self._cycle_preview_character_selection(
            step,
            activate_label=bool(getattr(self, "_preview_char_label_mode", False)),
        )
    if keysym == "d":
        if active_label_idx is None:
            if self._get_preview_active_data(create=False) is None:
                self._set_preview_box_info("Najpierw wybierz tablicę z listy.", "warning")
                return "break"
            self._ensure_preview_final_box_mode(render_preview=False)
            previous_selected_index = getattr(self, "_preview_char_selected_index", None)
            self._preview_char_add_click_armed = True
            self._preview_char_add_modifier_down = False
            self._preview_char_add_mode = False
            self._preview_char_add_state = None
            self._preview_char_edit_mode = False
            self._preview_char_label_mode = False
            self._preview_char_label_active_index = None
            self._preview_char_hover_label_index = None
            self._refresh_preview_editor_toolbar()
            self._apply_preview_canvas_cursor()
            self._update_preview_edit_status(
                "D uzbrojone. Kliknij pierwszy narożnik boxa, przesuń mysz i kliknij drugi narożnik.",
                tone="info",
            )
            if previous_selected_index is not None:
                try:
                    self._redraw_preview_character_overlay_only(int(previous_selected_index))
                except Exception:
                    pass
            return "break"
        return None
    if keysym == "n":
        if active_label_idx is None:
            return self._toggle_preview_char_add_mode(event)
        return None
    if keysym == "s":
        if not bool(getattr(self, "_preview_char_label_mode", False)):
            return self._select_hovered_preview_char_box(event)
        return None
    if keysym == "t":
        if active_label_idx is None:
            return self._edit_selected_preview_char_symbol(event)
        return None
    return None


def on_preview_canvas_keyrelease(host, event=None):
    self = host
    if event is None:
        return None
    keysym = str(getattr(event, "keysym", "") or "").lower()
    if keysym in {"alt_l", "alt_r", "option_l", "option_r"}:
        self._preview_alt_modifier_down = False
        return "break"
    if keysym == "d" and bool(getattr(self, "_preview_char_add_modifier_down", False)):
        self._preview_char_add_modifier_down = False
        self._apply_preview_canvas_cursor()
        if getattr(self, "_preview_char_add_state", None) is None:
            self._update_preview_edit_status()
        return "break"
    return None


def on_preview_canvas_press(host, event):
    self = host
    self._focus_preview_canvas()
    action_key = self._extract_preview_action_from_current_item()
    if action_key == "reset_view":
        self._reset_current_preview_view()
        return "break"
    if action_key == "toggle_fullscreen":
        self._toggle_preview_fullscreen()
        return "break"
    if action_key == "edit_source_filename":
        return self._edit_preview_source_filename(event)
    if action_key == "toggle_plate_layout":
        return self._cycle_preview_plate_layout_override(event)

    badge_key = self._extract_preview_badge_key_from_current_item()
    if badge_key:
        self._set_preview_selected_badge(badge_key)
        self._preview_pan_drag_state = None
        start_dx, start_dy = self._get_preview_badge_offset(self._preview_active_pid, badge_key)
        self._preview_badge_drag_state = {
            "badge_key": str(badge_key),
            "start_x": float(event.x),
            "start_y": float(event.y),
            "start_dx": float(start_dx),
            "start_dy": float(start_dy),
        }
        try:
            self.preview_canvas.configure(cursor="hand2")
        except Exception:
            pass
        return "break"

    if not getattr(self, "_preview_render_state", None):
        return

    if _preview_has_clearable_canvas_action(self) and not _preview_point_inside_image_with_padding(
        self,
        event.x,
        event.y,
        padding=18.0,
    ):
        return self._clear_preview_canvas_action(event)

    if getattr(self, "_preview_selected_badge_key", None) is not None:
        self._set_preview_selected_badge(None)
    self._preview_badge_drag_state = None
    self._preview_pan_drag_state = None
    edit_mode = bool(getattr(self, "_preview_char_edit_mode", False))
    label_mode = bool(getattr(self, "_preview_char_label_mode", False))

    click_add_state = getattr(self, "_preview_char_add_state", None)
    if isinstance(click_add_state, dict) and bool(click_add_state.get("click_draw")):
        if not self._preview_point_inside_image(event.x, event.y):
            self._update_preview_edit_status(
                "Drugi narożnik boxa musi być wewnątrz tablicy.",
                tone="warning",
            )
            return "break"
        img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
        click_add_state["bbox"] = [
            float(click_add_state.get("start_img_x", img_x)),
            float(click_add_state.get("start_img_y", img_y)),
            float(img_x),
            float(img_y),
        ]
        click_add_state["dirty"] = True
        click_add_state["click_finalize"] = True
        return self._finalize_preview_char_add_state()

    if bool(getattr(self, "_preview_char_add_click_armed", False)):
        if not self._preview_point_inside_image(event.x, event.y):
            self._update_preview_edit_status(
                "Kliknij pierwszy narożnik boxa wewnątrz tablicy.",
                tone="warning",
            )
            return "break"
        self._preview_char_edit_mode = False
        self._preview_char_add_mode = False
        self._preview_char_add_modifier_down = False
        img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
        self._preview_char_selected_index = None
        self._preview_char_add_state = {
            "start_img_x": float(img_x),
            "start_img_y": float(img_y),
            "bbox": [float(img_x), float(img_y), float(img_x), float(img_y)],
            "dirty": False,
            "click_draw": True,
        }
        self._refresh_preview_editor_toolbar()
        self._apply_preview_canvas_cursor("crosshair")
        self._update_preview_edit_status(
            "Pierwszy narożnik ustawiony. Przesuń mysz i kliknij drugi narożnik boxa.",
            tone="info",
        )
        if not self._redraw_preview_add_box_overlay_only():
            self._on_preview_select(None)
        return "break"

    if edit_mode and not label_mode:
        handle_hit = self._find_preview_character_handle_hit(event.x, event.y)
        if handle_hit is not None:
            char_idx, handle_name = handle_hit
            if self._start_preview_character_box_drag(
                char_idx,
                "resize",
                event,
                handle_name=handle_name,
                cursor="crosshair",
            ):
                return "break"

    separator_handle = self._find_preview_layout_separator_handle_hit(event.x, event.y)
    if separator_handle:
        self._push_preview_history_snapshot()
        self._preview_pan_drag_state = None
        self._preview_badge_drag_state = None
        separator_runtime = getattr(self, "_preview_layout_separator_runtime", None)
        start_separator = {}
        if isinstance(separator_runtime, dict):
            start_separator = copy.deepcopy(separator_runtime.get("separator", {}) or {})
        self._preview_layout_separator_drag_state = {
            "handle": str(separator_handle),
            "start_separator": start_separator,
            "start_canvas_x": float(event.x),
            "start_canvas_y": float(event.y),
            "dirty": False,
        }
        try:
            self.preview_canvas.configure(cursor="sb_v_double_arrow")
        except Exception:
            pass
        return "break"

    label_hit = self._find_preview_char_label_hit(event.x, event.y)
    box_hit = self._find_preview_character_box_hit(event.x, event.y)

    if label_mode:
        target_idx = label_hit if label_hit is not None else box_hit
        if target_idx is not None:
            return self._select_preview_character_box(
                int(target_idx),
                activate_label=True,
                status_message="Wpisywanie znaków: wpisz 0-9 lub A-Z, aby nadpisać znak w aktywnym boxie.",
            )

    if label_hit is not None and getattr(self, "_preview_char_label_active_index", None) is not None:
        self._preview_char_edit_mode = True
        self._preview_char_selected_index = int(label_hit)
        self._preview_char_hover_label_index = int(label_hit)
        self._refresh_preview_editor_toolbar()
        self._activate_preview_char_label_input(
            int(label_hit),
            status_message="Pole znaku pozostaje aktywne. Wpisz 0-9 lub A-Z, aby nadpisać etykietę, albo Esc aby wyjść.",
        )
        return "break"

    if getattr(self, "_preview_char_label_active_index", None) is not None:
        self._preview_char_label_active_index = None

    if self._preview_char_add_requested() and self._preview_point_inside_image(event.x, event.y):
        self._preview_char_edit_mode = False
        img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
        self._preview_char_selected_index = None
        self._preview_char_add_state = {
            "start_img_x": float(img_x),
            "start_img_y": float(img_y),
            "bbox": [float(img_x), float(img_y), float(img_x), float(img_y)],
            "dirty": False,
        }
        self._refresh_preview_editor_toolbar()
        try:
            self.preview_canvas.configure(cursor="crosshair")
        except Exception:
            pass
        try:
            self.preview_canvas.delete("preview_char_add_preview")
        except Exception:
            pass
        return "break"

    handle_hit = None
    if handle_hit is not None and edit_mode and not label_mode:
        char_idx, handle_name = handle_hit
        chars = self._get_preview_active_character_records(create=False)
        if 0 <= int(char_idx) < len(chars):
            rec = chars[int(char_idx)]
            bbox = self._char_record_bbox(rec)
            if bbox:
                img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
                self._preview_char_selected_index = int(char_idx)
                self._preview_char_drag_state = {
                    "index": int(char_idx),
                    "mode": "resize",
                    "handle": str(handle_name),
                    "start_img_x": float(img_x),
                    "start_img_y": float(img_y),
                    "start_bbox": list(bbox),
                    "dirty": False,
                    "history_pushed": False,
                }
                self._bind_preview_char_drag_session()
                self._refresh_preview_editor_toolbar()
                try:
                    self.preview_canvas.configure(cursor="crosshair")
                except Exception:
                    pass
                self._redraw_preview_character_overlay_only(int(char_idx))
                self._update_preview_edit_status(
                    "Przeciągasz uchwyt rogu boxa. Zwolnij LPM, aby zapisać korektę.",
                    tone="info",
                )
                return "break"

    if box_hit is not None:
        if (
            edit_mode
            and getattr(self, "_preview_char_selected_index", None) is not None
            and int(self._preview_char_selected_index) == int(box_hit)
        ):
            if self._start_preview_character_box_drag(box_hit, "move", event, cursor="fleur"):
                return "break"
            chars = self._get_preview_active_character_records(create=False)
            if 0 <= int(box_hit) < len(chars):
                rec = chars[int(box_hit)]
                bbox = self._char_record_bbox(rec)
                if bbox:
                    img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
                    self._preview_char_drag_state = {
                        "index": int(box_hit),
                        "mode": "move",
                        "start_img_x": float(img_x),
                        "start_img_y": float(img_y),
                        "start_bbox": list(bbox),
                        "dirty": False,
                        "history_pushed": False,
                    }
                    self._bind_preview_char_drag_session()
                    try:
                        self.preview_canvas.configure(cursor="fleur")
                    except Exception:
                        pass
            self._redraw_preview_character_overlay_only(int(box_hit))
            self._update_preview_edit_status(
                "Przesuwasz zaznaczony box. Zwolnij LPM, aby zapisać korektę.",
                tone="info",
            )
            return "break"

        self._update_preview_edit_status(
            "Najedź kursorem na box i naciśnij S, aby go zaznaczyć. Zaznaczony box przesuniesz LPM, zmienisz uchwytami i usuniesz PPM.",
            tone="info",
        )
        if edit_mode or label_mode:
            return "break"

    previous_selected_index = getattr(self, "_preview_char_selected_index", None)
    self._preview_char_selected_index = None
    self._refresh_preview_editor_toolbar()
    self._preview_pan_drag_state = {
        "start_x": float(event.x),
        "start_y": float(event.y),
        "start_pan_x": float(self._preview_pan_x),
        "start_pan_y": float(self._preview_pan_y),
    }
    try:
        self.preview_canvas.configure(cursor="fleur")
    except Exception:
        pass
    if previous_selected_index is not None:
        try:
            self._redraw_preview_character_overlay_only(int(previous_selected_index))
        except Exception:
            pass
    return "break"


def _preview_has_clearable_canvas_action(host) -> bool:
    return bool(
        getattr(host, "_preview_char_label_mode", False)
        or getattr(host, "_preview_char_label_active_index", None) is not None
        or getattr(host, "_preview_char_add_state", None) is not None
        or getattr(host, "_preview_char_add_click_armed", False)
        or getattr(host, "_preview_char_add_modifier_down", False)
        or getattr(host, "_preview_char_add_mode", False)
    )


def _preview_point_inside_image_with_padding(host, canvas_x: float, canvas_y: float, *, padding: float = 18.0) -> bool:
    state = getattr(host, "_preview_render_state", None) or {}
    try:
        pad = max(0.0, float(padding))
        return bool(
            float(state.get("image_left", 0.0)) - pad <= float(canvas_x) <= float(state.get("image_right", -1.0)) + pad
            and float(state.get("image_top", 0.0)) - pad <= float(canvas_y) <= float(state.get("image_bottom", -1.0)) + pad
        )
    except Exception:
        return False


def on_preview_canvas_drag(host, event):
    self = host
    separator_drag_state = getattr(self, "_preview_layout_separator_drag_state", None)
    if isinstance(separator_drag_state, dict):
        separator_handle = str(separator_drag_state.get("handle", "left") or "left").strip().lower()
        if separator_handle == "line":
            separator = self._move_preview_layout_separator_from_canvas_delta(
                separator_drag_state.get("start_separator", {}),
                float(separator_drag_state.get("start_canvas_x", event.x) or event.x),
                float(separator_drag_state.get("start_canvas_y", event.y) or event.y),
                event.x,
                event.y,
            )
        else:
            separator = self._set_preview_layout_separator_handle_y_from_canvas(
                separator_handle,
                event.x,
                event.y,
            )
        if isinstance(separator, dict):
            separator_drag_state["dirty"] = True
            self._draw_preview_layout_separator(self._get_preview_active_data(create=False))
        return "break"

    drag_state = self._preview_badge_drag_state
    if isinstance(drag_state, dict):
        badge_key = drag_state.get("badge_key")
        new_dx = float(drag_state.get("start_dx", 0.0)) + (float(event.x) - float(drag_state.get("start_x", 0.0)))
        new_dy = float(drag_state.get("start_dy", 0.0)) + (float(event.y) - float(drag_state.get("start_y", 0.0)))
        new_dx, new_dy = self._clamp_preview_badge_offset(badge_key, new_dx, new_dy)
        self._set_preview_badge_offset(self._preview_active_pid, badge_key, new_dx, new_dy)
        self._move_preview_badge_to_offset(badge_key, new_dx, new_dy)
        return "break"

    char_drag_state = getattr(self, "_preview_char_drag_state", None)
    if isinstance(char_drag_state, dict):
        chars = self._get_preview_active_character_records(create=False)
        char_idx = int(char_drag_state.get("index", -1))
        if 0 <= char_idx < len(chars):
            rec = chars[char_idx]
            bbox = list(char_drag_state.get("start_bbox", rec.get("bbox", [0, 0, 0, 0])))
            img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
            mode = str(char_drag_state.get("mode", "move") or "move").lower()

            if mode == "move":
                start_x = float(char_drag_state.get("start_img_x", img_x))
                start_y = float(char_drag_state.get("start_img_y", img_y))
                delta_x = float(img_x) - start_x
                delta_y = float(img_y) - start_y
                width = max(1.0, float(bbox[2]) - float(bbox[0]))
                height = max(1.0, float(bbox[3]) - float(bbox[1]))
                state = getattr(self, "_preview_render_state", None) or {}
                max_w = max(width, float(state.get("orig_w", width)))
                max_h = max(height, float(state.get("orig_h", height)))
                new_x1 = min(max(0.0, float(bbox[0]) + delta_x), max_w - width)
                new_y1 = min(max(0.0, float(bbox[1]) + delta_y), max_h - height)
                new_bbox = [new_x1, new_y1, new_x1 + width, new_y1 + height]
            else:
                handle_name = str(char_drag_state.get("handle", "se") or "se").lower()
                x1, y1, x2, y2 = bbox
                if "w" in handle_name:
                    x1 = float(img_x)
                else:
                    x2 = float(img_x)
                if "n" in handle_name:
                    y1 = float(img_y)
                else:
                    y2 = float(img_y)
                new_bbox = [x1, y1, x2, y2]

            normalized_bbox = self._normalize_preview_char_bbox(new_bbox)
            if normalized_bbox is not None:
                active_data = self._get_preview_active_data(create=False)
                normalized_bbox = self._constrain_preview_char_bbox_to_layout_separator(
                    normalized_bbox,
                    data=active_data,
                    row=char_drag_state.get("layout_row"),
                    min_size=4.0,
                )
            if normalized_bbox is not None:
                current_bbox = self._char_record_bbox(rec)
                try:
                    if current_bbox and all(
                        abs(float(current_bbox[i]) - float(normalized_bbox[i])) < 0.25
                        for i in range(4)
                    ):
                        return "break"
                except Exception:
                    pass
                rec["bbox"] = normalized_bbox
                if not bool(char_drag_state.get("manual_marked")):
                    self._mark_preview_char_record_manual(rec)
                    char_drag_state["manual_marked"] = True
                char_drag_state["dirty"] = True
                visual_ids = char_drag_state.get("visual_ids")
                now = time.monotonic()
                last_visual_at = float(char_drag_state.get("last_visual_at", 0.0) or 0.0)
                should_draw_visual = (
                    not isinstance(visual_ids, dict)
                    or (now - last_visual_at) >= 0.024
                )
                if should_draw_visual:
                    char_drag_state["last_visual_at"] = now
                    if not self._update_preview_character_drag_visual(char_idx, rec, normalized_bbox):
                        self._on_preview_select(None)
        return "break"

    char_add_state = getattr(self, "_preview_char_add_state", None)
    if isinstance(char_add_state, dict):
        img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
        preview_bbox = [
            float(char_add_state.get("start_img_x", img_x)),
            float(char_add_state.get("start_img_y", img_y)),
            float(img_x),
            float(img_y),
        ]
        normalized_preview_bbox = self._normalize_preview_char_bbox(preview_bbox)
        char_add_state["bbox"] = normalized_preview_bbox if normalized_preview_bbox is not None else preview_bbox
        char_add_state["dirty"] = True
        if not self._redraw_preview_add_box_overlay_only():
            self._on_preview_select(None)
        return "break"

    pan_state = self._preview_pan_drag_state
    if not isinstance(pan_state, dict):
        return

    state = getattr(self, "_preview_render_state", None) or {}
    canvas = getattr(self, "preview_canvas", None)
    if not state or canvas is None:
        return "break"

    old_left = float(state.get("image_left", 0.0) or 0.0)
    old_top = float(state.get("image_top", 0.0) or 0.0)
    image_w = max(1.0, float(state.get("image_right", old_left + 1.0) or old_left + 1.0) - old_left)
    image_h = max(1.0, float(state.get("image_bottom", old_top + 1.0) or old_top + 1.0) - old_top)
    base_x_off = float(state.get("fit_x_off", old_left) or old_left) - ((image_w - float(state.get("fit_new_w", image_w) or image_w)) / 2.0)
    base_y_off = float(state.get("fit_y_off", old_top) or old_top) - ((image_h - float(state.get("fit_new_h", image_h) or image_h)) / 2.0)
    target_x = base_x_off + float(pan_state.get("start_pan_x", 0.0)) + (float(event.x) - float(pan_state.get("start_x", 0.0)))
    target_y = base_y_off + float(pan_state.get("start_pan_y", 0.0)) + (float(event.y) - float(pan_state.get("start_y", 0.0)))
    try:
        canvas_w = float(canvas.winfo_width() or 0)
        canvas_h = float(canvas.winfo_height() or 0)
    except Exception:
        canvas_w = canvas_h = 0.0
    target_x, target_y = self._clamp_preview_image_position(
        target_x,
        target_y,
        image_w=image_w,
        image_h=image_h,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        top_reserved=float(state.get("top_reserved", 0.0) or 0.0),
        bottom_reserved=float(state.get("bottom_reserved", 0.0) or 0.0),
        preferred_x=base_x_off,
        preferred_y=base_y_off,
    )
    dx = float(target_x) - old_left
    dy = float(target_y) - old_top
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return "break"

    self._preview_pan_x = float(target_x - base_x_off)
    self._preview_pan_y = float(target_y - base_y_off)
    state["image_left"] = float(target_x)
    state["image_top"] = float(target_y)
    state["image_right"] = float(target_x + image_w)
    state["image_bottom"] = float(target_y + image_h)
    self._preview_render_state = state
    for tag in (
        "preview_plate_image",
        "preview_char",
        "preview_fast_detail",
        "preview_badge",
        "preview_plate_status_frame",
        "preview_layout_separator",
        "preview_char_drag_preview",
        "preview_char_add_preview",
    ):
        try:
            canvas.move(tag, dx, dy)
        except Exception:
            pass
    for runtime in (getattr(self, "_preview_badge_runtime", {}) or {}).values():
        if not isinstance(runtime, dict):
            continue
        for key in ("base_center_x", "base_line_y", "base_bottom_y", "box_anchor_y"):
            if key not in runtime:
                continue
            try:
                runtime[key] = float(runtime.get(key, 0.0) or 0.0) + (dy if key != "base_center_x" else dx)
            except Exception:
                pass
    for badge_key, runtime in list((getattr(self, "_preview_badge_runtime", {}) or {}).items()):
        if not isinstance(runtime, dict):
            continue
        try:
            saved_dx, saved_dy = self._get_preview_badge_offset(getattr(self, "_preview_active_pid", ""), str(badge_key))
            self._move_preview_badge_to_offset(
                str(badge_key),
                float(saved_dx),
                float(saved_dy),
            )
        except Exception:
            pass
    return "break"


def on_preview_canvas_release(host, event):
    self = host
    separator_drag_state = getattr(self, "_preview_layout_separator_drag_state", None)
    if isinstance(separator_drag_state, dict):
        self._preview_layout_separator_drag_state = None
        try:
            self.preview_canvas.configure(cursor="arrow")
        except Exception:
            pass
        if bool(separator_drag_state.get("dirty")):
            data = self._get_preview_active_data(create=True)
            if isinstance(data, dict):
                chars = list(data.get("characters", []) or []) if isinstance(data.get("characters"), list) else []
                chars = self._apply_preview_layout_separator_constraints_to_chars(data, chars)
                ordered_chars = self._sort_character_records_by_x(chars, data=data)
                self._update_preview_plate_layout_metadata(data, ordered_chars)
                ordered_chars = self._annotate_preview_character_reading_positions(ordered_chars, data=data)
                data["characters"] = ordered_chars
                data["status"] = self._derive_preview_status_from_data(data, ordered_chars)
                try:
                    self._persist_preview_metadata(success_message=None, refresh_list=False)
                except Exception:
                    self._schedule_preview_metadata_save(delay_ms=450)
                self._refresh_preview_live_metadata_ui(
                    status_message="Zaktualizowano linię podziału rzędów tablicy.",
                    status_tone="info",
                    render_preview=True,
                )
        else:
            self._on_preview_select(None)
        return "break"

    char_drag_state = getattr(self, "_preview_char_drag_state", None)
    if isinstance(char_drag_state, dict):
        self._unbind_preview_char_drag_session()
        try:
            self.preview_canvas.configure(cursor="arrow")
        except Exception:
            pass
        if bool(char_drag_state.get("dirty")):
            try:
                chars = self._get_preview_active_character_records(create=False)
                char_idx = int(char_drag_state.get("index", -1))
                selected_record = chars[char_idx] if 0 <= char_idx < len(chars) else None
                _push_preview_char_drag_history_snapshot(self, char_drag_state)
                # Keep the drag preview visible until the canonical box is rebuilt.
                self._persist_active_preview_characters(
                    selected_record=selected_record,
                success_message="Zapisano ręczna korekte boxu znaku w metadata.json.",
                    render_preview=False,
                    save_immediately=True,
                    refresh_row=False,
                    light_redraw_indices="selected",
                )
            finally:
                self._clear_preview_character_drag_visual()
                self._preview_char_drag_state = None
        else:
            self._clear_preview_character_drag_visual()
            self._preview_char_drag_state = None
            self._on_preview_select(None)
        return "break"

    char_add_state = getattr(self, "_preview_char_add_state", None)
    if isinstance(char_add_state, dict):
        if bool(char_add_state.get("click_draw")) and not bool(char_add_state.get("click_finalize")):
            return "break"
        return self._finalize_preview_char_add_state()

    if self._preview_badge_drag_state is None and self._preview_pan_drag_state is None:
        return
    self._preview_badge_drag_state = None
    self._preview_pan_drag_state = None
    try:
        self.preview_canvas.configure(cursor=("crosshair" if self._preview_char_add_requested() else "arrow"))
    except Exception:
        pass
    return "break"


def _preview_zoom_interaction_blocked(host) -> bool:
    return bool(
        getattr(host, "_preview_badge_drag_state", None) is not None
        or getattr(host, "_preview_layout_separator_drag_state", None) is not None
        or getattr(host, "_preview_pan_drag_state", None) is not None
        or getattr(host, "_preview_char_drag_state", None) is not None
        or getattr(host, "_preview_char_add_state", None) is not None
    )


def _get_preview_safe_zoom_max(host, state: dict | None = None) -> float:
    source_state = state if isinstance(state, dict) else (getattr(host, "_preview_render_state", {}) or {})
    try:
        safe_zoom_max = float(
            source_state.get(
                "safe_zoom_max",
                getattr(host, "_preview_safe_zoom_max", getattr(host, "_preview_zoom_max", 2.4)),
            )
        )
    except Exception:
        safe_zoom_max = float(getattr(host, "_preview_zoom_max", 2.4) or 2.4)
    return max(1.0, min(float(getattr(host, "_preview_zoom_max", 2.4) or 2.4), safe_zoom_max))


def _capture_preview_zoom_anchor(host, event, state: dict) -> dict:
    image_left = float(state.get("image_left", 0.0))
    image_top = float(state.get("image_top", 0.0))
    image_right = float(state.get("image_right", image_left))
    image_bottom = float(state.get("image_bottom", image_top))
    current_display_w = max(1.0, image_right - image_left)
    current_display_h = max(1.0, image_bottom - image_top)

    # Zoom w edytorze ma stabilizowac aktualne polozenie tablicy, a nie
    # "podplywac" pod kursor. Kotwiczymy wiec srodek aktualnego widoku tablicy.
    rel_x = 0.5
    rel_y = 0.5
    anchor_x = image_left + (current_display_w / 2.0)
    anchor_y = image_top + (current_display_h / 2.0)

    return {
        "plate_id": str(state.get("plate_id", "") or ""),
        "rel_x": float(max(0.0, min(1.0, rel_x))),
        "rel_y": float(max(0.0, min(1.0, rel_y))),
        "anchor_x": float(anchor_x),
        "anchor_y": float(anchor_y),
    }


def _apply_preview_zoom_view(host, target_zoom: float, anchor: dict | None) -> bool:
    self = host
    state = dict(getattr(self, "_preview_render_state", None) or {})
    if not state:
        return False
    safe_zoom_max = _get_preview_safe_zoom_max(self, state)
    target_zoom = max(float(getattr(self, "_preview_zoom_min", 0.72) or 0.72), min(safe_zoom_max, float(target_zoom)))

    if not isinstance(anchor, dict):
        image_left = float(state.get("image_left", 0.0) or 0.0)
        image_top = float(state.get("image_top", 0.0) or 0.0)
        image_right = float(state.get("image_right", image_left) or image_left)
        image_bottom = float(state.get("image_bottom", image_top) or image_top)
        anchor = {
            "rel_x": 0.5,
            "rel_y": 0.5,
            "anchor_x": image_left + (max(1.0, image_right - image_left) / 2.0),
            "anchor_y": image_top + (max(1.0, image_bottom - image_top) / 2.0),
            "plate_id": str(state.get("plate_id", "") or ""),
        }

    try:
        orig_w = max(1.0, float(state.get("orig_w", 1.0)))
        orig_h = max(1.0, float(state.get("orig_h", 1.0)))
        fit_scale = max(0.001, float(state.get("fit_scale", state.get("scale", 1.0))))
        fit_x_off = float(state.get("fit_x_off", state.get("image_left", 0.0)))
        fit_y_off = float(state.get("fit_y_off", state.get("image_top", 0.0)))
        fit_new_w = max(1.0, float(state.get("fit_new_w", max(1, int(orig_w * fit_scale)))))
        fit_new_h = max(1.0, float(state.get("fit_new_h", max(1, int(orig_h * fit_scale)))))
        next_scale = fit_scale * float(target_zoom)
        next_w = max(1.0, float(max(1, int(orig_w * next_scale))))
        next_h = max(1.0, float(max(1, int(orig_h * next_scale))))
        base_x_off = fit_x_off - ((next_w - fit_new_w) / 2.0)
        base_y_off = fit_y_off - ((next_h - fit_new_h) / 2.0)
        canvas_w = float(getattr(self.preview_canvas, "winfo_width", lambda: 0)() or 0)
        canvas_h = float(getattr(self.preview_canvas, "winfo_height", lambda: 0)() or 0)
        rel_x = float(anchor.get("rel_x", 0.5))
        rel_y = float(anchor.get("rel_y", 0.5))
        anchor_x = float(anchor.get("anchor_x", canvas_w / 2.0))
        anchor_y = float(anchor.get("anchor_y", canvas_h / 2.0))
    except Exception:
        return False

    self._preview_zoom_level = float(target_zoom)
    self._preview_pan_x = anchor_x - base_x_off - (rel_x * next_w)
    self._preview_pan_y = anchor_y - base_y_off - (rel_y * next_h)
    self._preview_zoom_pending_state = {
        "plate_id": str(state.get("plate_id", "") or ""),
        "zoom": float(self._preview_zoom_level),
        "pan_x": float(self._preview_pan_x),
        "pan_y": float(self._preview_pan_y),
    }
    if _render_preview_zoom_frame(self):
        return True
    self._preview_fast_select_render = True
    self._on_preview_select(None)
    return False


def _clear_preview_zoom_animation(host) -> None:
    canvas = getattr(host, "preview_canvas", None)
    after_id = getattr(host, "_preview_zoom_anim_after_id", None)
    if after_id and canvas is not None:
        try:
            canvas.after_cancel(after_id)
        except Exception:
            pass
    host._preview_zoom_anim_after_id = None
    host._preview_zoom_velocity = 0.0
    host._preview_zoom_last_ts = None
    host._preview_zoom_last_input_ts = None


def _schedule_preview_zoom_animation(host, delay_ms: int = 0) -> None:
    canvas = getattr(host, "preview_canvas", None)
    if canvas is None:
        return
    if getattr(host, "_preview_zoom_anim_after_id", None):
        return
    try:
        host._preview_zoom_anim_after_id = canvas.after(
            max(1, int(delay_ms)),
            lambda: _animate_preview_zoom_step(host),
        )
    except Exception:
        host._preview_zoom_anim_after_id = None


def _settle_preview_zoom_without_full_redraw(host) -> None:
    canvas = getattr(host, "preview_canvas", None)
    if canvas is None:
        return
    try:
        pending_detail_after = getattr(host, "_preview_detail_render_after_id", None)
        if pending_detail_after:
            host.frame.after_cancel(pending_detail_after)
            host._preview_detail_render_after_id = None
    except Exception:
        pass
    try:
        canvas.tag_lower("preview_plate_image")
        canvas.tag_raise("preview_char")
        canvas.tag_raise("preview_badge")
        canvas.tag_raise("preview_plate_status_frame")
        canvas.tag_raise("preview_layout_separator")
        canvas.tag_raise("preview_overlay")
        canvas.tag_raise("preview_overlay_action")
    except Exception:
        pass
    try:
        host._apply_preview_badge_selection_style()
    except Exception:
        pass
    try:
        host._apply_preview_canvas_cursor()
        host._refresh_preview_editor_toolbar()
    except Exception:
        pass


def _animate_preview_zoom_step(host) -> None:
    self = host
    self._preview_zoom_anim_after_id = None
    state = dict(getattr(self, "_preview_render_state", None) or {})
    if not state or _preview_zoom_interaction_blocked(self):
        _clear_preview_zoom_animation(self)
        return

    anchor = getattr(self, "_preview_zoom_anchor", None)
    if isinstance(anchor, dict):
        anchor_pid = str(anchor.get("plate_id", "") or "")
        current_pid = str(state.get("plate_id", "") or "")
        if anchor_pid and current_pid and anchor_pid != current_pid:
            _clear_preview_zoom_animation(self)
            return

    now = time.perf_counter()
    last_ts = getattr(self, "_preview_zoom_last_ts", None)
    if not isinstance(last_ts, (int, float)):
        dt = 0.024
    else:
        dt = max(0.010, min(0.045, float(now) - float(last_ts)))
    self._preview_zoom_last_ts = float(now)

    current_zoom = float(getattr(self, "_preview_zoom_level", 1.0) or 1.0)
    safe_zoom_max = _get_preview_safe_zoom_max(self, state)
    target_zoom = max(
        float(getattr(self, "_preview_zoom_min", 0.72) or 0.72),
        min(safe_zoom_max, float(getattr(self, "_preview_zoom_target", current_zoom) or current_zoom)),
    )
    velocity = float(getattr(self, "_preview_zoom_velocity", 0.0) or 0.0)
    stiffness = float(getattr(self, "_preview_zoom_stiffness", 34.0) or 34.0)
    damping = float(getattr(self, "_preview_zoom_damping", 10.5) or 10.5)
    last_input_ts = getattr(self, "_preview_zoom_last_input_ts", None)
    try:
        input_age = float(now) - float(last_input_ts) if isinstance(last_input_ts, (int, float)) else 0.0
    except Exception:
        input_age = 0.0
    max_tail_s = max(0.15, float(getattr(self, "_preview_zoom_max_tail_s", 1.0) or 1.0))

    velocity += (target_zoom - current_zoom) * stiffness * dt
    velocity *= math.exp(-damping * dt)
    next_zoom = current_zoom + (velocity * dt)
    min_zoom = float(getattr(self, "_preview_zoom_min", 0.72) or 0.72)
    if next_zoom <= min_zoom:
        next_zoom = min_zoom
        velocity = 0.0
    elif next_zoom >= safe_zoom_max:
        next_zoom = safe_zoom_max
        velocity = 0.0

    close_enough = abs(target_zoom - next_zoom) < 0.010 and abs(velocity) < 0.075
    if input_age >= max_tail_s:
        close_enough = True
    if close_enough:
        next_zoom = target_zoom
        velocity = 0.0

    self._preview_zoom_velocity = float(velocity)
    self._preview_zoom_target = float(target_zoom)
    if not _apply_preview_zoom_view(self, next_zoom, anchor):
        _clear_preview_zoom_animation(self)
        return

    if close_enough:
        self._preview_zoom_anim_after_id = None
        self._preview_zoom_last_ts = None
        self._preview_zoom_velocity = 0.0
        self._preview_zoom_pending_state = None
        self._preview_fast_select_render = False
        _settle_preview_zoom_without_full_redraw(self)
        return

    frame_ms = int(getattr(self, "_preview_zoom_frame_ms", 22) or 22)
    _schedule_preview_zoom_animation(self, delay_ms=frame_ms)


def on_preview_canvas_mousewheel(host, event):
    self = host
    if not getattr(self, "_preview_render_state", None):
        return
    if _preview_zoom_interaction_blocked(self):
        return "break"

    delta = 0
    if hasattr(event, "delta") and event.delta:
        delta = int(event.delta)
    elif hasattr(event, "num"):
        if int(event.num) == 4:
            delta = 120
        elif int(event.num) == 5:
            delta = -120

    if delta == 0:
        return

    pending_detail = getattr(self, "_preview_detail_render_after_id", None)
    if pending_detail:
        try:
            self.frame.after_cancel(pending_detail)
        except Exception:
            pass
        self._preview_detail_render_after_id = None

    state = dict(self._preview_render_state)
    safe_zoom_max = _get_preview_safe_zoom_max(self, state)
    current_zoom = float(getattr(self, "_preview_zoom_level", 1.0) or 1.0)
    target_base = current_zoom
    try:
        impulse = max(-4.0, min(4.0, float(delta) / 120.0))
    except Exception:
        impulse = 1.0 if delta > 0 else -1.0
    target_zoom = target_base * (float(getattr(self, "_preview_zoom_step", 1.16) or 1.16) ** impulse)
    target_zoom = max(float(getattr(self, "_preview_zoom_min", 0.72) or 0.72), min(safe_zoom_max, target_zoom))
    if abs(target_zoom - current_zoom) < 1e-6 and abs(float(getattr(self, "_preview_zoom_velocity", 0.0) or 0.0)) < 1e-6:
        return "break"

    previous_after_id = getattr(self, "_preview_zoom_render_after_id", None)
    if previous_after_id:
        try:
            self.preview_canvas.after_cancel(previous_after_id)
        except Exception:
            pass
        self._preview_zoom_render_after_id = None

    _clear_preview_zoom_animation(self)
    anchor = _capture_preview_zoom_anchor(self, event, state)
    self._preview_zoom_anchor = anchor
    self._preview_zoom_target = float(target_zoom)
    self._preview_zoom_last_input_ts = time.perf_counter()
    self._preview_zoom_velocity = 0.0
    self._preview_zoom_last_ts = None
    if _apply_preview_zoom_view(self, target_zoom, anchor):
        self._preview_zoom_pending_state = None
        self._preview_fast_select_render = False
        _settle_preview_zoom_without_full_redraw(self)
    else:
        _clear_preview_zoom_animation(self)
    return "break"


def _transform_preview_zoom_overlay_items(host, canvas, previous_state: dict, next_state: dict) -> None:
    try:
        old_left = float(previous_state.get("image_left", 0.0) or 0.0)
        old_top = float(previous_state.get("image_top", 0.0) or 0.0)
        old_scale = max(0.0001, float(previous_state.get("scale", 1.0) or 1.0))
        new_left = float(next_state.get("image_left", old_left) or old_left)
        new_top = float(next_state.get("image_top", old_top) or old_top)
        new_scale = max(0.0001, float(next_state.get("scale", old_scale) or old_scale))
        factor = float(new_scale / old_scale)
    except Exception:
        return

    if not (0.05 <= factor <= 20.0):
        return

    dx = float(new_left - old_left)
    dy = float(new_top - old_top)
    overlay_tags = (
        "preview_char",
        "preview_badge",
        "preview_plate_status_frame",
        "preview_layout_separator",
        "preview_char_drag_preview",
        "preview_char_add_preview",
    )
    for tag in overlay_tags:
        try:
            if not canvas.find_withtag(tag):
                continue
            canvas.scale(tag, old_left, old_top, factor, factor)
            canvas.move(tag, dx, dy)
        except Exception:
            pass

    def _tx(value):
        return new_left + ((float(value) - old_left) * factor)

    def _ty(value):
        return new_top + ((float(value) - old_top) * factor)

    for runtime in (getattr(host, "_preview_badge_runtime", {}) or {}).values():
        if not isinstance(runtime, dict):
            continue
        for key in (
            "left_limit",
            "right_limit",
            "base_left",
            "base_center_x",
            "box_center_x",
        ):
            if key in runtime:
                try:
                    runtime[key] = _tx(runtime[key])
                except Exception:
                    pass
        for key in (
            "top_limit",
            "bottom_limit",
            "base_top",
            "base_bottom_y",
            "base_line_y",
            "box_top_y",
            "box_bottom_y",
            "box_anchor_y",
        ):
            if key in runtime:
                try:
                    runtime[key] = _ty(runtime[key])
                except Exception:
                    pass

    separator_runtime = getattr(host, "_preview_layout_separator_runtime", None)
    if isinstance(separator_runtime, dict):
        for key in ("left_point", "right_point"):
            point = separator_runtime.get(key)
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                continue
            try:
                separator_runtime[key] = (_tx(point[0]), _ty(point[1]))
            except Exception:
                pass


def _render_preview_zoom_frame(host) -> bool:
    self = host
    canvas = getattr(self, "preview_canvas", None)
    state = dict(getattr(self, "_preview_render_state", None) or {})
    if canvas is None or not state:
        return False

    pid = str(state.get("plate_id", "") or getattr(self, "_preview_active_pid", "") or "").strip()
    if not pid:
        return False
    try:
        img_path = Path(str(self.preview_dir_var.get() or "").strip()) / "images" / f"{pid}.jpg"
    except Exception:
        return False
    if not img_path.exists():
        return False

    try:
        pil_img, orig_w, orig_h, source_image_key = _get_cached_preview_source_image(self, img_path)
        fit_scale = max(0.001, float(state.get("fit_scale", state.get("scale", 1.0)) or 1.0))
        fit_new_w = max(1.0, float(state.get("fit_new_w", max(1, int(orig_w * fit_scale))) or 1.0))
        fit_new_h = max(1.0, float(state.get("fit_new_h", max(1, int(orig_h * fit_scale))) or 1.0))
        fit_x_off = float(state.get("fit_x_off", 0.0) or 0.0)
        fit_y_off = float(state.get("fit_y_off", 0.0) or 0.0)
        render_scale = fit_scale * float(getattr(self, "_preview_zoom_level", 1.0) or 1.0)
        new_w = max(1, int(float(orig_w) * render_scale))
        new_h = max(1, int(float(orig_h) * render_scale))
        photo = _get_cached_preview_photo(self, source_image_key, pil_img, new_w, new_h)
        canvas_w = max(50, int(canvas.winfo_width() or 50))
        canvas_h = max(50, int(canvas.winfo_height() or 50))
        base_x_off = fit_x_off - ((float(new_w) - fit_new_w) / 2.0)
        base_y_off = fit_y_off - ((float(new_h) - fit_new_h) / 2.0)
        x_off = base_x_off + float(getattr(self, "_preview_pan_x", 0.0) or 0.0)
        y_off = base_y_off + float(getattr(self, "_preview_pan_y", 0.0) or 0.0)
        x_off, y_off = self._clamp_preview_image_position(
            x_off,
            y_off,
            image_w=float(new_w),
            image_h=float(new_h),
            canvas_w=float(canvas_w),
            canvas_h=float(canvas_h),
            top_reserved=float(state.get("top_reserved", 0.0) or 0.0),
            bottom_reserved=float(state.get("bottom_reserved", 0.0) or 0.0),
            preferred_x=base_x_off,
            preferred_y=base_y_off,
        )
    except Exception:
        return False

    previous_state = dict(state)
    self._current_photo = photo
    self._preview_pan_x = float(x_off - base_x_off)
    self._preview_pan_y = float(y_off - base_y_off)
    state.update(
        {
            "plate_id": pid,
            "orig_w": float(orig_w),
            "orig_h": float(orig_h),
            "scale": float(render_scale),
            "image_left": float(x_off),
            "image_top": float(y_off),
            "image_right": float(x_off + float(new_w)),
            "image_bottom": float(y_off + float(new_h)),
        }
    )
    self._preview_render_state = state

    _transform_preview_zoom_overlay_items(self, canvas, previous_state, state)

    for tag in ("preview_plate_image", "preview_fast_detail", "preview_canvas_caption"):
        try:
            canvas.delete(tag)
        except Exception:
            pass

    try:
        canvas.create_image(
            float(x_off),
            float(y_off),
            anchor=tk.NW,
            image=self._current_photo,
            tags=("preview_plate_image", "preview_movable_plate"),
        )
    except Exception:
        return False

    data = self._get_preview_active_data(create=False)
    if not isinstance(data, dict):
        data = {}

    try:
        if self._should_preview_use_two_row_layers(data) and not canvas.find_withtag("preview_layout_separator"):
            self._draw_preview_layout_separator(data)
    except Exception:
        pass

    try:
        canvas.create_text(
            10,
            max(14, canvas_h - 10),
            text="Podgląd tablicy",
            fill=getattr(self.app, "palette", {}).get("muted", "#b0b0b0"),
            font=("Segoe UI", 8, "bold"),
            anchor=tk.SW,
            tags=("preview_canvas_caption",),
        )
        canvas.tag_lower("preview_plate_image")
        canvas.tag_raise("preview_char")
        canvas.tag_raise("preview_badge")
        canvas.tag_raise("preview_plate_status_frame")
        canvas.tag_raise("preview_layout_separator")
        canvas.tag_raise("preview_overlay")
        canvas.tag_raise("preview_overlay_action")
    except Exception:
        pass
    return True


def _schedule_preview_zoom_details(host) -> None:
    self = host
    try:
        pending_after = getattr(self, "_preview_detail_render_after_id", None)
        if pending_after:
            self.frame.after_cancel(pending_after)
            self._preview_detail_render_after_id = None
    except Exception:
        pass
    active_pid = str(getattr(self, "_preview_active_pid", "") or "")
    try:
        generation = int(getattr(self, "_preview_select_generation", 0) or 0)
    except Exception:
        generation = 0

    def _render_zoom_details_once():
        self._preview_detail_render_after_id = None
        if str(getattr(self, "_preview_active_pid", "") or "") != active_pid:
            return
        try:
            if int(getattr(self, "_preview_select_generation", 0) or 0) != int(generation):
                return
        except Exception:
            return
        if getattr(self, "_preview_zoom_render_after_id", None):
            return
        if (
            getattr(self, "_preview_badge_drag_state", None) is not None
            or getattr(self, "_preview_layout_separator_drag_state", None) is not None
            or getattr(self, "_preview_pan_drag_state", None) is not None
            or getattr(self, "_preview_char_drag_state", None) is not None
            or getattr(self, "_preview_char_add_state", None) is not None
        ):
            return
        try:
            self._draw_preview_fast_render_details(active_pid)
        except Exception:
            pass

    try:
        self._preview_detail_render_after_id = self.frame.after(420, _render_zoom_details_once)
    except Exception:
        self._preview_detail_render_after_id = None


def start_preview_character_box_drag(host, char_idx, mode, event, *, handle_name=None, cursor="fleur") -> bool:
    self = host
    chars = self._get_preview_active_character_records(create=False)
    try:
        char_idx = int(char_idx)
    except Exception:
        return False
    if not (0 <= char_idx < len(chars)):
        return False

    rec = chars[char_idx]
    bbox = self._char_record_bbox(rec)
    if not bbox:
        return False
    active_data = self._get_preview_active_data(create=False)
    layout_row = None
    if isinstance(rec, dict):
        try:
            raw_row = int(rec.get("reading_row", 0) or 0)
            layout_row = raw_row if raw_row in (1, 2) else None
        except Exception:
            layout_row = None
    if layout_row is None:
        layout_row = self._get_preview_row_for_bbox(bbox, data=active_data)
    try:
        original_record = copy.deepcopy(rec)
    except Exception:
        original_record = dict(rec) if isinstance(rec, dict) else {}

    img_x, img_y = self._preview_canvas_to_image_point(event.x, event.y)
    self._preview_char_label_active_index = None
    self._preview_char_selected_index = int(char_idx)
    drag_state = {
        "index": int(char_idx),
        "mode": str(mode),
        "start_img_x": float(img_x),
        "start_img_y": float(img_y),
        "start_bbox": list(bbox),
        "dirty": False,
        "history_pushed": False,
        "original_record": original_record,
        "last_visual_at": 0.0,
        "layout_row": layout_row,
    }
    if handle_name:
        drag_state["handle"] = str(handle_name)
    self._preview_char_drag_state = drag_state
    self._bind_preview_char_drag_session()
    try:
        self.preview_canvas.configure(cursor=str(cursor))
    except Exception:
        pass
    return True


def on_preview_canvas_secondary_press(host, event=None):
    self = host
    self._focus_preview_canvas()
    if event is None or not getattr(self, "_preview_render_state", None):
        return None

    box_hit = self._find_preview_character_box_hit(event.x, event.y)
    if box_hit is None:
        if getattr(self, "_preview_char_label_active_index", None) is not None:
            self._preview_char_label_active_index = None
            self._update_preview_edit_status("Zamknieto aktywne pole znaku.", tone="muted")
            self._on_preview_select(None)
            return "break"
        return None

    selected_idx = getattr(self, "_preview_char_selected_index", None)
    if selected_idx is None or int(selected_idx) != int(box_hit):
        self._update_preview_edit_status(
            "PPM usuwa tylko aktywny box. Najedź kursorem na wybrany box i naciśnij S, aby go zaznaczyć.",
            tone="warning",
        )
        self._on_preview_select(None)
        return "break"

    self._preview_char_label_active_index = None
    self._preview_char_hover_label_index = None
    self._refresh_preview_editor_toolbar()
    return self._delete_selected_preview_char_box(event)


def finalize_preview_char_add_state(host) -> str:
    self = host
    char_add_state = getattr(self, "_preview_char_add_state", None)
    if not isinstance(char_add_state, dict):
        return "break"

    click_draw = bool(char_add_state.get("click_draw"))
    self._preview_char_add_state = None
    if click_draw:
        self._preview_char_add_click_armed = False
        self._preview_char_add_modifier_down = False
        self._preview_char_add_mode = False

    try:
        self.preview_canvas.configure(cursor=("crosshair" if self._preview_char_add_requested() else "arrow"))
    except Exception:
        pass

    bbox = self._normalize_preview_char_bbox(char_add_state.get("bbox"))
    if bbox is None:
        if click_draw:
            self._preview_char_add_click_armed = True
        try:
            self.preview_canvas.delete("preview_char_add_preview")
        except Exception:
            pass
        return "break"

    width = float(bbox[2]) - float(bbox[0])
    height = float(bbox[3]) - float(bbox[1])
    if width < 6.0 or height < 6.0:
        if click_draw:
            self._preview_char_add_click_armed = True
        self._set_preview_box_info("Nowy box jest zbyt mały. Spróbuj ponownie.", "warning")
        self._update_preview_edit_status("Nowy box jest zbyt mały. Wskaż pierwszy narożnik ponownie.", tone="warning")
        self._apply_preview_canvas_cursor("crosshair" if click_draw else None)
        try:
            self.preview_canvas.delete("preview_char_add_preview")
        except Exception:
            pass
        return "break"

    chars = self._get_preview_active_character_records(create=True)
    self._push_preview_history_snapshot()
    new_record = {
        "character": "",
        "bbox": bbox,
        "confidence": 1.0,
        "method": "manual",
        "source_tag": "ocr",
    }
    chars.append(new_record)
    self._mark_preview_char_record_manual(new_record)
    self._preview_char_edit_mode = True
    self._preview_char_label_active_index = None
    self._preview_char_hover_label_index = None
    try:
        self.preview_canvas.delete("preview_char_add_preview")
    except Exception:
        pass
    self._persist_active_preview_characters(
        selected_record=new_record,
        success_message="Dodano nowy box znaku do metadata.json.",
        render_preview=False,
        refresh_row=True,
        light_redraw_indices=None,
    )
    if click_draw:
        status_message = "Dodano nowy box. Tryb rysowania z D został wyłączony."
    else:
        status_message = "Dodano nowy box. Pozostaje zaznaczony do dalszej korekty, ale nie włącza pola wpisywania znaku."
    self._update_preview_edit_status(status_message, tone="success")
    return "break"
