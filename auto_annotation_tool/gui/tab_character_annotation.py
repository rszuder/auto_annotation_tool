#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka ZNAKÓW.
Logicznie podzielona na:
1. Wycinanie tablic (surowe)
2. Wykrywanie znaków i Analiza (OCR/YOLO, Laboratorium Filtrów, Turniej z Cache)
3. Integracje i Dataset YOLO
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path, PurePosixPath
import threading
import xml.etree.ElementTree as ET
import json
import cv2
import os
import random
import shutil

from ..config import CONFIG, logger
from ..campaign_manager import CAMPAIGN
from ..icons import IconManager
from ..character_recognition import PlateGenerator, CharacterDetector, CharacterDetection, DetectionMethod
from ..ocr import PlateOCR
from ..data_models import ImageAnnotation, Detection
from .help_manager import HELP
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

PREVIEW_BOX_MODE_OPTIONS = [
    ("AUTO", "Auto (wg metody)"),
    ("FINAL", "Wynik koncowy"),
    ("YOLO_FILTERED", "YOLO po filtrze sekwencji"),
    ("YOLO_NMS", "YOLO po NMS"),
    ("YOLO_RAW", "YOLO surowe"),
]
PREVIEW_BOX_MODE_LABELS = {key: label for key, label in PREVIEW_BOX_MODE_OPTIONS}
PREVIEW_BOX_MODE_BY_LABEL = {label: key for key, label in PREVIEW_BOX_MODE_OPTIONS}

PREVIEW_SORT_OPTIONS = [
    ("DEFAULT", "Domyślne"),
    ("PERFECT", "Perfect"),
    ("YOLO", "YOLO"),
    ("RES", "RES"),
    ("OCR", "OCR"),
]
PREVIEW_SORT_LABELS = {key: label for key, label in PREVIEW_SORT_OPTIONS}

PERFECT_STRATEGY_BUCKETS = [
    ("ocr_exact", "OCR exact"),
    ("yolo_exact", "YOLO exact"),
    ("ocr_yolo_rescue", "OCR + YOLO rescue"),
    ("other_perfect", "Manual / inne perfect"),
]
PERFECT_STRATEGY_LABELS = {key: label for key, label in PERFECT_STRATEGY_BUCKETS}
CHAR_CLASS_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

DETECTION_METHOD_OPTIONS = [
    ("OCR", "OCR"),
    ("YOLO", "YOLO"),
    ("BOTH", "Hybryda OCR/YOLO"),
]
DETECTION_METHOD_LABELS = {key: label for key, label in DETECTION_METHOD_OPTIONS}
DETECTION_METHOD_KEY_BY_LABEL = {label: key for key, label in DETECTION_METHOD_OPTIONS}


class SlimProgressBar(tk.Canvas):
    def __init__(
        self,
        master,
        *,
        maximum: float = 100.0,
        value: float = 0.0,
        thickness: int = 2,
        trough_color: str = "#3c3c3c",
        fill_color: str = "#0e639c",
        **kwargs,
    ):
        canvas_height = max(int(kwargs.pop("height", thickness + 4)), int(thickness) + 4)
        bg = kwargs.pop("bg", kwargs.pop("background", trough_color))
        super().__init__(
            master,
            height=canvas_height,
            bg=bg,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )
        self._maximum = max(1.0, float(maximum))
        self._value = 0.0
        self._thickness = max(1, int(thickness))
        self._trough_color = str(trough_color)
        self._fill_color = str(fill_color)
        self._trough_id = self.create_line(0, 0, 0, 0, capstyle=tk.ROUND)
        self._fill_id = self.create_line(0, 0, 0, 0, capstyle=tk.ROUND)
        self.bind("<Configure>", lambda _event: self._redraw(), add="+")
        self.configure(value=value)

    def _redraw(self):
        width = max(1.0, float(self.winfo_width()))
        height = max(1.0, float(self.winfo_height()))
        center_y = height / 2.0
        half_thickness = max(0.5, float(self._thickness) / 2.0)
        left = half_thickness + 1.0
        right = max(left, width - half_thickness - 1.0)
        ratio = max(0.0, min(1.0, float(self._value) / max(1.0, float(self._maximum))))
        fill_right = left + ((right - left) * ratio)

        self.coords(self._trough_id, left, center_y, right, center_y)
        self.coords(self._fill_id, left, center_y, max(left, fill_right), center_y)
        self.itemconfigure(self._trough_id, fill=self._trough_color, width=self._thickness)
        self.itemconfigure(self._fill_id, fill=self._fill_color, width=self._thickness)

    def configure(self, cnf=None, **kwargs):
        if cnf is not None and not isinstance(cnf, dict):
            return super().configure(cnf, **kwargs)

        merged = {}
        if isinstance(cnf, dict):
            merged.update(cnf)
        merged.update(kwargs)

        if "maximum" in merged:
            self._maximum = max(1.0, float(merged.pop("maximum")))
        if "value" in merged:
            self._value = max(0.0, float(merged.pop("value")))
        if "thickness" in merged:
            self._thickness = max(1, int(merged.pop("thickness")))
            merged.setdefault("height", self._thickness + 4)
        if "trough_color" in merged:
            self._trough_color = str(merged.pop("trough_color"))
        if "fill_color" in merged:
            self._fill_color = str(merged.pop("fill_color"))

        background = merged.pop("background", None)
        bg = merged.pop("bg", None)
        resolved_bg = background if background is not None else bg
        if resolved_bg is not None:
            super().configure(bg=resolved_bg)

        result = super().configure(**merged) if merged else None
        self._redraw()
        return result

    config = configure


class CharacterAnnotationTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)

        # core state
        self.is_processing = False
        self._step3_linear_mode = False

        # preview/cache state
        self.preview_metadata = {}
        self.preview_plate_ids = []
        self._preview_base_plate_ids = []
        self._listbox_pid_by_index = []
        self._current_photo = None
        self._reloading_preview = False
        self.preview_box_mode_rows = []
        self.gold_export_filter_rows = []
        self.yolo_option_rows = []
        self.preview_sort_buttons = {}
        self._preview_sort_hover_key = None
        self._preview_active_pid = None
        self._preview_zoom_level = 1.0
        self._preview_zoom_min = 1.0
        self._preview_zoom_max = 6.0
        self._preview_zoom_step = 1.15
        self._preview_pan_x = 0.0
        self._preview_pan_y = 0.0
        self._preview_render_state = {}
        self._preview_badge_offsets = {}
        self._preview_badge_runtime = {}
        self._preview_badge_drag_state = None
        self._preview_pan_drag_state = None
        self._preview_selected_badge_key = None
        self._preview_vertical_split_ready = False



        # Cache kluczy dla przełączania runów i zmian plików.
        self._loaded_meta_path = None
        self._loaded_meta_mtime = None

        # Stan szybkiego testu OCR niezależny od procesu wycinania.
        self.fast_test_stop = threading.Event()
        self.fast_test_running = False
        self._project_reset_token = 0
        self._detection_log_visible = False
        self._source_binding_after_id = None
        self._source_binding_sync_in_progress = False

        # presets (global; later can be project-scoped)
        self.presets_dir = Path(CONFIG.WORKSPACE_DIR) / "8_ocr_presets"
        self.presets_dir.mkdir(parents=True, exist_ok=True)

        # local session
        self.session_file = Path.home() / ".auto_annotation_tool" / "char_tab_session.json"
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.local_session = self._load_local_session()

        def get_val(key, default):
            val = self.local_session.get(key, default)
            return val if val != "" else default

        saved_preview_box_mode = str(get_val("char_preview_box_mode", "AUTO") or "AUTO").strip()
        saved_preview_box_mode = PREVIEW_BOX_MODE_LABELS.get(saved_preview_box_mode.upper(), saved_preview_box_mode)
        if saved_preview_box_mode not in PREVIEW_BOX_MODE_BY_LABEL:
            saved_preview_box_mode = PREVIEW_BOX_MODE_LABELS["AUTO"]
        saved_preview_sort_mode = str(get_val("char_preview_sort_mode", "DEFAULT") or "DEFAULT").strip().upper()
        if saved_preview_sort_mode not in PREVIEW_SORT_LABELS:
            saved_preview_sort_mode = "DEFAULT"
        saved_detection_method = self._normalize_detection_method_key(get_val("char_det_method", "OCR"))
        saved_hybrid_rescue_max_chars = max(1, min(5, int(get_val("char_hybrid_rescue_max_chars", 2) or 2)))
        saved_hybrid_yolo_box_backend = bool(get_val("char_hybrid_yolo_box_backend", True))
        saved_gold_export_split = bool(get_val("char_gold_export_split", False))
        saved_gold_export_train_pct = max(50.0, min(90.0, float(get_val("char_gold_export_train_pct", 80.0) or 80.0)))
        saved_gold_export_val_pct = max(5.0, min(45.0, float(get_val("char_gold_export_val_pct", 10.0) or 10.0)))

        # vars
        self.detection_method_var = tk.StringVar(value=DETECTION_METHOD_LABELS.get(saved_detection_method, "OCR"))
        self.xml_path_var = tk.StringVar(value=get_val("char_xml_path", ""))
        self.images_dir_var = tk.StringVar(value=get_val("char_images_dir", ""))
        self.yolo_model_path_var = tk.StringVar(value=get_val("char_yolo_model", ""))
        self.yolo_device_var = tk.StringVar(value=get_val("char_yolo_device", "auto"))
        self.yolo_conf_var = tk.DoubleVar(value=float(get_val("char_yolo_conf", 0.25)))
        self.yolo_iou_var = tk.DoubleVar(value=float(get_val("char_yolo_iou", 0.45)))
        self.yolo_overlap_var = tk.DoubleVar(value=float(get_val("char_yolo_overlap", 0.70)))
        self.yolo_agnostic_nms_var = tk.BooleanVar(value=bool(get_val("char_yolo_agnostic_nms", False)))
        self.yolo_seq_center_y_var = tk.DoubleVar(value=float(get_val("char_yolo_seq_center_y", 0.60)))
        self.yolo_seq_min_h_ratio_var = tk.DoubleVar(value=float(get_val("char_yolo_seq_min_h_ratio", 0.55)))
        self.yolo_seq_max_h_ratio_var = tk.DoubleVar(value=float(get_val("char_yolo_seq_max_h_ratio", 1.80)))
        self.yolo_seq_max_w_ratio_var = tk.DoubleVar(value=float(get_val("char_yolo_seq_max_w_ratio", 2.60)))
        self.yolo_seq_soft_overlap_var = tk.DoubleVar(value=float(get_val("char_yolo_seq_soft_overlap", 0.18)))
        self.yolo_seq_hard_overlap_var = tk.DoubleVar(value=float(get_val("char_yolo_seq_hard_overlap", 0.30)))
        self.hybrid_rescue_max_chars_var = tk.IntVar(value=saved_hybrid_rescue_max_chars)
        self.hybrid_yolo_box_backend_var = tk.BooleanVar(value=saved_hybrid_yolo_box_backend)
        self.preview_dir_var = tk.StringVar(value=get_val("char_preview_dir", ""))
        self.preview_box_mode_var = tk.StringVar(value=saved_preview_box_mode)
        self.preview_sort_mode_var = tk.StringVar(value=saved_preview_sort_mode)

        self.ocr_conf_var = tk.DoubleVar(value=float(get_val("char_ocr_conf", 0.25)))
        self.smart_export_var = tk.BooleanVar(value=get_val("char_smart_export", True))
        self.gold_include_ocr_exact_var = tk.BooleanVar(value=bool(get_val("char_gold_include_ocr_exact", True)))
        self.gold_include_yolo_exact_var = tk.BooleanVar(value=bool(get_val("char_gold_include_yolo_exact", True)))
        self.gold_include_ocr_yolo_rescue_var = tk.BooleanVar(value=bool(get_val("char_gold_include_ocr_yolo_rescue", True)))
        self.gold_include_other_perfect_var = tk.BooleanVar(value=bool(get_val("char_gold_include_other_perfect", True)))
        self.gold_export_split_var = tk.BooleanVar(value=saved_gold_export_split)
        self.gold_export_train_pct_var = tk.DoubleVar(value=saved_gold_export_train_pct)
        self.gold_export_val_pct_var = tk.DoubleVar(value=saved_gold_export_val_pct)

        # lab params
        self.prep_angle_var = tk.DoubleVar(value=float(get_val("char_prep_angle", 0.0)))
        self.prep_height_var = tk.IntVar(value=int(get_val("char_prep_height", 80)))
        self.prep_padding_var = tk.IntVar(value=int(get_val("char_prep_padding", 20)))
        self.prep_clip_var = tk.IntVar(value=int(get_val("char_prep_clip", 255)))
        self.prep_denoise_var = tk.IntVar(value=int(get_val("char_prep_denoise", 0)))
        self.prep_clahe_var = tk.DoubleVar(value=float(get_val("char_prep_clahe", 0.0)))
        self.prep_use_bin_var = tk.BooleanVar(value=get_val("char_prep_use_bin", True))
        self.prep_block_var = tk.IntVar(value=int(get_val("char_prep_block", 15)))
        self.prep_c_var = tk.IntVar(value=int(get_val("char_prep_c", 5)))
        self.prep_erode_var = tk.IntVar(value=int(get_val("char_prep_erode", 0)))
        self.do_clahe_var = tk.BooleanVar(value=get_val("char_do_clahe", True))
        self.interpolation_var = tk.StringVar(value=get_val("char_interpolation", "lanczos4"))
        self.preview_box_mode_var.trace_add("write", self._on_preview_box_mode_var_write)
        self.yolo_agnostic_nms_var.trace_add("write", self._on_yolo_option_var_write)
        self.hybrid_yolo_box_backend_var.trace_add("write", self._on_yolo_option_var_write)
        for filter_var in (
            self.gold_include_ocr_exact_var,
            self.gold_include_yolo_exact_var,
            self.gold_include_ocr_yolo_rescue_var,
            self.gold_include_other_perfect_var,
        ):
            filter_var.trace_add("write", self._on_gold_export_filter_var_write)
        self.gold_export_split_var.trace_add("write", self._on_gold_export_split_var_write)
        self.gold_export_train_pct_var.trace_add("write", self._on_gold_export_split_var_write)
        self.gold_export_val_pct_var.trace_add("write", self._on_gold_export_split_var_write)

        self._create_widgets()
        self._bind_source_path_watchers()
  
        self._update_step3_source_path_lock()
        self._update_preview_path_lock()
        self.reset_subtab_flow()
        self._schedule_source_binding_refresh(delay_ms=0)

        if not CAMPAIGN.get_active_project_name():
            self._clear_project_bound_session_values(clear_ui=True)
            self.reset_subtab_flow()

        self._update_yolo_visibility()
        self.app.root.bind("<Destroy>", self._on_app_close, add="+")
        if self.preview_dir_var.get().strip():
            self.frame.after(100, lambda: self._load_preview_data(quiet=True))

    # =========================================================
    # Small helpers
    # =========================================================

    def _reset_preview_cache(self):
        self.preview_metadata = {}
        self._preview_base_plate_ids = []
        self._loaded_meta_path = None
        self._loaded_meta_mtime = None
        self._preview_active_pid = None
        self._preview_zoom_level = 1.0
        self._preview_pan_x = 0.0
        self._preview_pan_y = 0.0
        self._preview_render_state = {}
        self._preview_badge_offsets = {}
        self._preview_badge_runtime = {}
        self._preview_badge_drag_state = None
        self._preview_pan_drag_state = None
        self._preview_selected_badge_key = None

    def _reset_preview_view_state(self):
        self._preview_zoom_level = 1.0
        self._preview_pan_x = 0.0
        self._preview_pan_y = 0.0
        self._preview_render_state = {}
        self._preview_badge_runtime = {}
        self._preview_badge_drag_state = None
        self._preview_pan_drag_state = None
        self._preview_selected_badge_key = None

    def _get_preview_badge_offsets_for_plate(self, plate_id: str):
        if not plate_id:
            return {}
        return self._preview_badge_offsets.setdefault(str(plate_id), {})

    def _get_preview_badge_offset(self, plate_id: str, badge_key: str):
        offsets = self._get_preview_badge_offsets_for_plate(plate_id)
        entry = offsets.get(str(badge_key), {})
        return float(entry.get("dx", 0.0)), float(entry.get("dy", 0.0))

    def _set_preview_badge_offset(self, plate_id: str, badge_key: str, dx: float, dy: float):
        offsets = self._get_preview_badge_offsets_for_plate(plate_id)
        offsets[str(badge_key)] = {"dx": float(dx), "dy": float(dy)}

    def _clamp_preview_badge_offset(self, badge_key: str, dx: float, dy: float):
        runtime = self._preview_badge_runtime.get(str(badge_key), {})
        base_left = float(runtime.get("base_left", 0.0))
        base_top = float(runtime.get("base_top", 0.0))
        badge_width = float(runtime.get("badge_width", 0.0))
        left_limit = float(runtime.get("left_limit", base_left))
        right_limit = float(runtime.get("right_limit", base_left + badge_width))
        top_limit = float(runtime.get("top_limit", 46.0))

        min_dx = left_limit - base_left
        max_dx = (right_limit - badge_width) - base_left
        if max_dx < min_dx:
            max_dx = min_dx

        dx = max(min_dx, min(max_dx, float(dx)))
        dy = max(float(top_limit) - base_top, float(dy))
        return float(dx), float(dy)

    def _clamp_preview_image_position(
        self,
        x_off: float,
        y_off: float,
        *,
        image_w: float,
        image_h: float,
        canvas_w: float,
        canvas_h: float,
        top_reserved: float,
    ):
        min_visible = 48.0
        canvas_w = max(min_visible, float(canvas_w))
        canvas_h = max(min_visible, float(canvas_h))
        image_w = max(1.0, float(image_w))
        image_h = max(1.0, float(image_h))
        top_reserved = max(0.0, float(top_reserved))

        min_x = float(min_visible) - image_w
        max_x = canvas_w - float(min_visible)
        if max_x < min_x:
            center_x = (canvas_w - image_w) / 2.0
            min_x = center_x
            max_x = center_x

        min_y = top_reserved
        max_y = canvas_h - float(min_visible)
        if max_y < min_y:
            max_y = min_y

        x_off = max(min_x, min(max_x, float(x_off)))
        y_off = max(min_y, min(max_y, float(y_off)))
        return float(x_off), float(y_off)

    def _reset_current_preview_view(self):
        plate_id = str(getattr(self, "_preview_active_pid", "") or "")
        if plate_id:
            self._preview_badge_offsets.pop(plate_id, None)
        self._reset_preview_view_state()
        if getattr(self, "preview_canvas", None) is not None:
            self._on_preview_select(None)

    def _init_preview_vertical_split(self):
        pane = getattr(self, "preview_vertical_split", None)
        if pane is None or self._preview_vertical_split_ready:
            return

        try:
            total_h = int(pane.winfo_height() or 0)
            if total_h < 120:
                self.frame.after(120, self._init_preview_vertical_split)
                return
            total_h = max(420, total_h)
            target_y = int(total_h * 0.34)
            min_top = 180
            min_bottom = 240
            target_y = max(min_top, min(target_y, total_h - min_bottom))
            pane.sash_place(0, 1, target_y)
            self._preview_vertical_split_ready = True
        except Exception:
            pass

    def _apply_preview_badge_selection_style(self):
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        selected_color = palette.get("accent_hover", palette.get("accent", "#ffd166"))

        for badge_key, runtime in getattr(self, "_preview_badge_runtime", {}).items():
            is_selected = str(badge_key) == str(getattr(self, "_preview_selected_badge_key", None))
            box_color = selected_color if is_selected else str(runtime.get("box_color", "#cccccc"))
            line_color = selected_color if is_selected else str(runtime.get("line_color", "#cccccc"))
            box_width = 3 if is_selected else int(runtime.get("box_width", 2))
            line_width = 2 if is_selected else int(runtime.get("line_width", 1))

            try:
                canvas.itemconfigure(runtime.get("box_id"), outline=box_color, width=box_width)
            except Exception:
                pass

            try:
                canvas.itemconfigure(runtime.get("line_id"), fill=line_color, width=line_width)
            except Exception:
                pass

    def _set_preview_selected_badge(self, badge_key: str = None):
        self._preview_selected_badge_key = str(badge_key) if badge_key else None
        self._apply_preview_badge_selection_style()

    def _move_preview_badge_to_offset(self, badge_key: str, dx: float, dy: float):
        runtime = self._preview_badge_runtime.get(str(badge_key))
        canvas = getattr(self, "preview_canvas", None)
        if runtime is None or canvas is None:
            return

        dx, dy = self._clamp_preview_badge_offset(badge_key, dx, dy)

        prev_dx = float(runtime.get("offset_dx", 0.0))
        prev_dy = float(runtime.get("offset_dy", 0.0))
        delta_x = float(dx) - prev_dx
        delta_y = float(dy) - prev_dy

        if abs(delta_x) > 0.001 or abs(delta_y) > 0.001:
            try:
                canvas.move(runtime["tag"], delta_x, delta_y)
            except Exception:
                pass

        runtime["offset_dx"] = float(dx)
        runtime["offset_dy"] = float(dy)

        try:
            canvas.coords(
                runtime["line_id"],
                float(runtime["base_center_x"]) + float(dx),
                float(runtime["base_bottom_y"]) + float(dy),
                float(runtime["box_center_x"]),
                float(runtime["box_top_y"]),
            )
        except Exception:
            pass

    def _extract_preview_badge_key_from_current_item(self):
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return None

        try:
            tags = canvas.gettags("current")
        except Exception:
            return None

        for tag in tags:
            if str(tag).startswith("preview_badge::"):
                return str(tag).split("preview_badge::", 1)[1]
        return None

    def _extract_preview_action_from_current_item(self):
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return None

        try:
            tags = canvas.gettags("current")
        except Exception:
            return None

        for tag in tags:
            if str(tag).startswith("preview_action::"):
                return str(tag).split("preview_action::", 1)[1]
        return None

    def _on_preview_canvas_press(self, event):
        action_key = self._extract_preview_action_from_current_item()
        if action_key == "reset_view":
            self._reset_current_preview_view()
            return "break"

        badge_key = self._extract_preview_badge_key_from_current_item()
        if not badge_key:
            if not getattr(self, "_preview_render_state", None):
                return
            self._set_preview_selected_badge(None)
            self._preview_badge_drag_state = None
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
            return "break"

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

    def _on_preview_canvas_drag(self, event):
        drag_state = self._preview_badge_drag_state
        if isinstance(drag_state, dict):
            badge_key = drag_state.get("badge_key")
            new_dx = float(drag_state.get("start_dx", 0.0)) + (float(event.x) - float(drag_state.get("start_x", 0.0)))
            new_dy = float(drag_state.get("start_dy", 0.0)) + (float(event.y) - float(drag_state.get("start_y", 0.0)))
            new_dx, new_dy = self._clamp_preview_badge_offset(badge_key, new_dx, new_dy)
            self._set_preview_badge_offset(self._preview_active_pid, badge_key, new_dx, new_dy)
            self._move_preview_badge_to_offset(badge_key, new_dx, new_dy)
            return "break"

        pan_state = self._preview_pan_drag_state
        if not isinstance(pan_state, dict):
            return

        self._preview_pan_x = float(pan_state.get("start_pan_x", 0.0)) + (float(event.x) - float(pan_state.get("start_x", 0.0)))
        self._preview_pan_y = float(pan_state.get("start_pan_y", 0.0)) + (float(event.y) - float(pan_state.get("start_y", 0.0)))
        self._on_preview_select(None)
        return "break"

    def _on_preview_canvas_release(self, event):
        if self._preview_badge_drag_state is None and self._preview_pan_drag_state is None:
            return
        self._preview_badge_drag_state = None
        self._preview_pan_drag_state = None
        try:
            self.preview_canvas.configure(cursor="arrow")
        except Exception:
            pass
        return "break"

    def _on_preview_canvas_mousewheel(self, event):
        if not getattr(self, "_preview_render_state", None):
            return
        if self._preview_badge_drag_state is not None or self._preview_pan_drag_state is not None:
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

        current_zoom = float(self._preview_zoom_level)
        target_zoom = current_zoom * self._preview_zoom_step if delta > 0 else current_zoom / self._preview_zoom_step
        target_zoom = max(self._preview_zoom_min, min(self._preview_zoom_max, target_zoom))
        if abs(target_zoom - current_zoom) < 1e-6:
            return "break"

        state = dict(self._preview_render_state)
        canvas_x = float(event.x)
        canvas_y = float(event.y)
        image_left = float(state.get("image_left", 0.0))
        image_top = float(state.get("image_top", 0.0))
        image_right = float(state.get("image_right", image_left))
        image_bottom = float(state.get("image_bottom", image_top))
        current_scale = max(0.001, float(state.get("scale", 1.0)))
        orig_w = max(1.0, float(state.get("orig_w", 1.0)))
        orig_h = max(1.0, float(state.get("orig_h", 1.0)))

        if image_left <= canvas_x <= image_right and image_top <= canvas_y <= image_bottom:
            rel_x = (canvas_x - image_left) / current_scale
            rel_y = (canvas_y - image_top) / current_scale
            anchor_x = canvas_x
            anchor_y = canvas_y
        else:
            rel_x = orig_w / 2.0
            rel_y = orig_h / 2.0
            anchor_x = float(getattr(self.preview_canvas, "winfo_width", lambda: 0)() or 0) / 2.0
            anchor_y = float(getattr(self.preview_canvas, "winfo_height", lambda: 0)() or 0) / 2.0

        fit_scale = max(0.001, float(state.get("fit_scale", current_scale)))
        fit_x_off = float(state.get("fit_x_off", image_left))
        fit_y_off = float(state.get("fit_y_off", image_top))
        fit_new_w = max(1.0, float(state.get("fit_new_w", orig_w * fit_scale)))
        fit_new_h = max(1.0, float(state.get("fit_new_h", orig_h * fit_scale)))

        next_scale = fit_scale * target_zoom
        next_w = orig_w * next_scale
        next_h = orig_h * next_scale
        base_x_off = fit_x_off - ((next_w - fit_new_w) / 2.0)
        base_y_off = fit_y_off - ((next_h - fit_new_h) / 2.0)

        self._preview_zoom_level = float(target_zoom)
        self._preview_pan_x = anchor_x - base_x_off - (rel_x * next_scale)
        self._preview_pan_y = anchor_y - base_y_off - (rel_y * next_scale)
        self._on_preview_select(None)
        return "break"

    def _char_record_to_symbol_and_x(self, rec, fallback_index: int = 0):
        symbol = ""
        x_key = float(fallback_index)

        if isinstance(rec, dict):
            symbol = str(
                rec.get("character")
                or rec.get("text")
                or rec.get("char")
                or ""
            )

            bbox = rec.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                try:
                    x_key = (float(bbox[0]) + float(bbox[2])) / 2.0
                except Exception:
                    pass

            return symbol, x_key

        if isinstance(rec, str):
            return rec, x_key

        try:
            symbol = str(getattr(rec, "character", getattr(rec, "text", "")) or "")
        except Exception:
            symbol = ""

        try:
            bbox = getattr(rec, "bbox", None)
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                x_key = (float(bbox[0]) + float(bbox[2])) / 2.0
        except Exception:
            pass

        return symbol, x_key
        
    def _find_latest_preview_run_dir(self) -> str:
        """
        Szuka najnowszej poprawnej paczki preview w katalogu chars projektu.
        Poprawna paczka to katalog zawierający:
        - metadata.json
        - images/
        """
        chars_root = getattr(self, "_campaign_chars_dir", None)
        if not chars_root:
            return ""

        root = Path(chars_root)
        if not root.exists() or not root.is_dir():
            return ""

        candidates = []
        try:
            for p in root.rglob("*"):
                if not p.is_dir():
                    continue

                meta_file = p / "metadata.json"
                images_dir = p / "images"

                if meta_file.exists() and images_dir.exists() and images_dir.is_dir():
                    candidates.append(p)
        except Exception:
            return ""

        if not candidates:
            return ""

        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])
        
    def _restore_preview_context_from_project(self):
        """
        Przywraca ostatnią paczkę preview projektu, jeśli istnieje.
        """
        preview_dir = self._find_latest_preview_run_dir()
        if not preview_dir:
            return False

        try:
            self.preview_dir_var.set(preview_dir)
            self._reset_preview_cache()
            self._load_preview_data(quiet=True)
            return True
        except Exception as e:
            logger.debug(f"Nie udało się przywrócić preview paczki projektu: {e}")
            return False

    def _metadata_has_detection_results(self, metadata_map) -> bool:
        for _, data in (metadata_map or {}).items():
            if not isinstance(data, dict):
                continue

            status = str(data.get("status", "unknown")).strip().lower()
            if status in ("perfect", "needs_fix"):
                return True

            if isinstance(data.get("characters"), list) and data.get("characters"):
                return True

            for key in ("yolo_detections", "yolo_nms_detections", "yolo_raw_detections"):
                if isinstance(data.get(key), list) and data.get(key):
                    return True

            if str(data.get("fusion_strategy", "") or "").strip():
                return True

        return False

    def _preview_dir_has_completed_detection_output(self, preview_dir=None) -> bool:
        preview_dir_raw = str(preview_dir if preview_dir is not None else (self.preview_dir_var.get() or "")).strip()
        if not preview_dir_raw:
            return False

        try:
            meta_path = Path(preview_dir_raw) / "metadata.json"
            if not meta_path.exists():
                return False

            with open(meta_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                return False

            return self._metadata_has_detection_results(loaded)
        except Exception:
            return False

    def _sync_step3_access_from_preview_state(self, metadata_map=None):
        stage1_ready = False
        stage2_ready = False

        try:
            stage1_ready = self.can_restore_step3_substep(2)
        except Exception:
            stage1_ready = False

        if metadata_map is not None:
            stage2_ready = self._metadata_has_detection_results(metadata_map)
        if not stage2_ready:
            stage2_ready = self._preview_dir_has_completed_detection_output()

        if stage1_ready:
            try:
                self._set_button_state("btn_to_detect", True)
                self._set_subtab_state(self.tab_detect, "normal")
            except Exception:
                pass
            if self._step3_linear_mode:
                try:
                    CAMPAIGN.set_step3_stage1_done(True)
                except Exception:
                    pass

        if stage2_ready:
            try:
                self._set_button_state("btn_to_dataset", True)
                self._set_subtab_state(self.tab_dataset, "normal")
            except Exception:
                pass
            if self._step3_linear_mode:
                try:
                    CAMPAIGN.set_step3_stage2_done(True)
                except Exception:
                    pass

        try:
            self._sync_step3_nav_buttons()
        except Exception:
            pass

        try:
            self._update_step3_finish_button_state()
        except Exception:
            pass

    def _sort_character_records_by_x(self, chars):
        if not isinstance(chars, list):
            return []

        prepared = []
        for i, rec in enumerate(chars):
            _, x_key = self._char_record_to_symbol_and_x(rec, fallback_index=i)
            prepared.append((x_key, i, rec))

        prepared.sort(key=lambda item: (item[0], item[1]))
        return [rec for _, _, rec in prepared]

    def _normalize_character_source_tag(self, raw_tag=None, method=None) -> str:
        tag = str(raw_tag or "").strip().lower().replace("-", "_")
        method_name = str(method or "").strip().lower()

        if tag in ("yolo_rescue", "rescue", "yolorescue"):
            return "yolo_rescue"
        if tag == "yolo":
            return "yolo"
        if tag == "ocr":
            return "ocr"

        if method_name == "yolo":
            return "yolo"
        return "ocr"

    def _build_character_source_tags(self, chars, fusion_strategy="", fusion_details=None):
        ordered = self._sort_character_records_by_x(list(chars or []))
        rescue_positions = set()
        if str(fusion_strategy or "").strip().lower() == "ocr_yolo_rescue" and isinstance(fusion_details, dict):
            try:
                rescue_positions = {
                    int(idx) for idx in (fusion_details.get("mismatch_positions", []) or [])
                    if str(idx).strip() != ""
                }
            except Exception:
                rescue_positions = set()

        tags = []
        for idx, rec in enumerate(ordered):
            method_name = ""
            raw_tag = None
            if isinstance(rec, dict):
                raw_tag = rec.get("source_tag")
                method_name = rec.get("method", "")
            else:
                raw_tag = getattr(rec, "source_tag", None)
                method_name = getattr(rec, "method", "")

            normalized = self._normalize_character_source_tag(raw_tag=raw_tag, method=method_name)
            if idx in rescue_positions:
                normalized = "yolo_rescue"
            tags.append(normalized)

        return tags

    def _serialize_character_records(self, chars, fusion_strategy="", fusion_details=None):
        ordered = self._sort_character_records_by_x(list(chars or []))
        source_tags = self._build_character_source_tags(ordered, fusion_strategy=fusion_strategy, fusion_details=fusion_details)
        clean = []

        for idx, c in enumerate(ordered):
            source_tag = source_tags[idx] if idx < len(source_tags) else self._normalize_character_source_tag(
                method=(c.get("method", "") if isinstance(c, dict) else getattr(c, "method", ""))
            )
            clean.append({
                "character": str(c["character"] if isinstance(c, dict) else c.character),
                "bbox": [float(x) for x in (c["bbox"] if isinstance(c, dict) else c.bbox)],
                "confidence": float(c["confidence"] if isinstance(c, dict) else c.confidence),
                "method": str(c["method"] if isinstance(c, dict) else c.method),
                "source_tag": str(source_tag),
            })

        return clean

    def _get_character_source_tag(self, rec, data=None, fallback_index: int = 0) -> str:
        raw_tag = None
        method_name = ""

        if isinstance(rec, dict):
            raw_tag = rec.get("source_tag")
            method_name = rec.get("method", "")
        else:
            raw_tag = getattr(rec, "source_tag", None)
            method_name = getattr(rec, "method", "")

        normalized = self._normalize_character_source_tag(raw_tag=raw_tag, method=method_name)
        if raw_tag:
            return normalized

        if isinstance(data, dict):
            strategy = str(data.get("fusion_strategy", "") or "").strip().lower()
            if strategy == "ocr_yolo_rescue":
                details = data.get("fusion_details", {})
                if isinstance(details, dict):
                    mismatch_positions = details.get("mismatch_positions", []) or []
                    try:
                        if int(fallback_index) in {int(idx) for idx in mismatch_positions}:
                            return "yolo_rescue"
                    except Exception:
                        pass

        return normalized

    def _count_character_sources(self, chars, data=None):
        counts = {"ocr": 0, "yolo": 0, "yolo_rescue": 0}
        for idx, rec in enumerate(list(chars or [])):
            tag = self._get_character_source_tag(rec, data=data, fallback_index=idx)
            if tag not in counts:
                continue
            counts[tag] += 1
        return counts

    def _get_perfect_strategy_bucket(self, data: dict) -> str:
        if not isinstance(data, dict):
            return "other_perfect"

        raw_strategy = str(data.get("fusion_strategy", "") or "").strip().lower()
        if raw_strategy in ("ocr_exact", "ocr_only"):
            return "ocr_exact"
        if raw_strategy in ("yolo_exact", "yolo_only"):
            return "yolo_exact"
        if raw_strategy == "ocr_yolo_rescue":
            return "ocr_yolo_rescue"

        return "other_perfect"

    def _empty_perfect_strategy_counts(self):
        return {key: 0 for key, _ in PERFECT_STRATEGY_BUCKETS}

    def _format_perfect_strategy_counts(self, counts: dict) -> str:
        safe_counts = counts if isinstance(counts, dict) else {}
        parts = [
            f"{label}: {int(safe_counts.get(key, 0))}"
            for key, label in PERFECT_STRATEGY_BUCKETS
        ]
        return "Perfect wg strategii: " + " | ".join(parts)

    def _get_selected_gold_export_strategy_buckets(self):
        selected = set()
        if bool(getattr(self, "gold_include_ocr_exact_var", None).get() if hasattr(self, "gold_include_ocr_exact_var") else True):
            selected.add("ocr_exact")
        if bool(getattr(self, "gold_include_yolo_exact_var", None).get() if hasattr(self, "gold_include_yolo_exact_var") else True):
            selected.add("yolo_exact")
        if bool(getattr(self, "gold_include_ocr_yolo_rescue_var", None).get() if hasattr(self, "gold_include_ocr_yolo_rescue_var") else True):
            selected.add("ocr_yolo_rescue")
        if bool(getattr(self, "gold_include_other_perfect_var", None).get() if hasattr(self, "gold_include_other_perfect_var") else True):
            selected.add("other_perfect")
        return selected

    def _format_selected_gold_export_strategy_labels(self) -> str:
        selected = self._get_selected_gold_export_strategy_buckets()
        labels = [label for key, label in PERFECT_STRATEGY_BUCKETS if key in selected]
        return ", ".join(labels) if labels else "brak"

    def _count_exportable_characters_in_data(self, data: dict) -> int:
        if not isinstance(data, dict):
            return 0

        valid_chars = set(CHAR_CLASS_ALPHABET)
        count = 0
        for rec in list(data.get("characters", []) or []):
            if isinstance(rec, dict):
                symbol = rec.get("character", "")
            else:
                symbol = getattr(rec, "character", "")
            symbol = str(symbol or "").strip().upper()
            if symbol and symbol in valid_chars:
                count += 1
        return count

    def _count_statuses_in_metadata_mapping(self, metadata_map):
        perfect = 0
        needs_fix = 0
        unknown = 0
        strategy_counts = self._empty_perfect_strategy_counts()
        strategy_char_counts = self._empty_perfect_strategy_counts()

        for _, data in (metadata_map or {}).items():
            if not isinstance(data, dict):
                unknown += 1
                continue

            status = str(data.get("status", "unknown")).strip().lower()
            if status == "perfect":
                perfect += 1
                bucket = self._get_perfect_strategy_bucket(data)
                strategy_counts[bucket] += 1
                strategy_char_counts[bucket] += self._count_exportable_characters_in_data(data)
            elif status == "needs_fix":
                needs_fix += 1
            else:
                unknown += 1

        return {
            "perfect": perfect,
            "needs_fix": needs_fix,
            "unknown": unknown,
            "total": perfect + needs_fix + unknown,
            "strategy_counts": strategy_counts,
            "strategy_char_counts": strategy_char_counts,
        }

    def _char_record_bbox(self, rec):
        bbox = None

        if isinstance(rec, dict):
            bbox = rec.get("bbox")
        else:
            try:
                bbox = getattr(rec, "bbox", None)
            except Exception:
                bbox = None

        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            return None

        try:
            return tuple(float(v) for v in bbox[:4])
        except Exception:
            return None

    def _char_record_width(self, rec) -> float:
        bbox = self._char_record_bbox(rec)
        if not bbox:
            return 0.0
        return max(0.0, float(bbox[2]) - float(bbox[0]))

    def _char_record_height(self, rec) -> float:
        bbox = self._char_record_bbox(rec)
        if not bbox:
            return 0.0
        return max(0.0, float(bbox[3]) - float(bbox[1]))

    def _char_record_confidence(self, rec) -> float:
        if isinstance(rec, dict):
            try:
                return float(rec.get("confidence", 0.0))
            except Exception:
                return 0.0

        try:
            return float(getattr(rec, "confidence", 0.0))
        except Exception:
            return 0.0

    def _clone_character_detection(self, rec, character=None, method=None):
        symbol, _ = self._char_record_to_symbol_and_x(rec)
        bbox = self._char_record_bbox(rec) or (0.0, 0.0, 1.0, 1.0)
        confidence = self._char_record_confidence(rec)

        return CharacterDetection(
            character=str(character if character is not None else symbol or ""),
            bbox=tuple(float(v) for v in bbox[:4]),
            confidence=float(confidence),
            method=str(method if method is not None else getattr(rec, "method", "ocr") if not isinstance(rec, dict) else rec.get("method", "ocr")),
        )

    def _levenshtein_distance(self, left: str, right: str) -> int:
        left = str(left or "")
        right = str(right or "")

        if left == right:
            return 0
        if not left:
            return len(right)
        if not right:
            return len(left)

        previous = list(range(len(right) + 1))
        for i, left_char in enumerate(left, start=1):
            current = [i]
            for j, right_char in enumerate(right, start=1):
                cost = 0 if left_char == right_char else 1
                current.append(
                    min(
                        previous[j] + 1,
                        current[j - 1] + 1,
                        previous[j - 1] + cost,
                    )
                )
            previous = current

        return previous[-1]

    def _best_text_distance(self, candidate_text: str, true_texts) -> int:
        normalized = [str(item or "").strip().upper() for item in (true_texts or []) if str(item or "").strip()]
        if not normalized:
            return 10 ** 9

        candidate = str(candidate_text or "").strip().upper()
        return min(self._levenshtein_distance(candidate, truth) for truth in normalized)

    def _pick_best_true_text(self, candidate_text: str, true_texts, same_length_only: bool = False) -> str:
        normalized = [str(item or "").strip().upper() for item in (true_texts or []) if str(item or "").strip()]
        if same_length_only:
            normalized = [item for item in normalized if len(item) == len(str(candidate_text or ""))]

        if not normalized:
            return ""

        candidate = str(candidate_text or "").strip().upper()
        return min(
            normalized,
            key=lambda item: (
                self._levenshtein_distance(candidate, item),
                abs(len(candidate) - len(item)),
                item,
            )
        )

    def _get_text_mismatch_positions(self, candidate_text: str, expected_text: str):
        candidate = str(candidate_text or "").strip().upper()
        expected = str(expected_text or "").strip().upper()

        if not candidate or not expected or len(candidate) != len(expected):
            return []

        return [idx for idx, (left, right) in enumerate(zip(candidate, expected)) if left != right]

    def _find_best_yolo_rescue_index(self, slot_index: int, expected_char: str, ocr_detections, yolo_detections, used_indices, min_index: int | None = None):
        if slot_index < 0 or slot_index >= len(ocr_detections):
            return None

        expected_char = str(expected_char or "").strip().upper()
        if not expected_char:
            return None

        _, slot_center_x = self._char_record_to_symbol_and_x(ocr_detections[slot_index], fallback_index=slot_index)
        ocr_width = max(1.0, self._char_record_width(ocr_detections[slot_index]))
        all_ocr_widths = [self._char_record_width(det) for det in ocr_detections if self._char_record_width(det) > 0.0]
        if all_ocr_widths:
            sorted_widths = sorted(all_ocr_widths)
            median_width = float(sorted_widths[len(sorted_widths) // 2])
        else:
            median_width = ocr_width

        allowed_gap = max(6.0, ocr_width * 0.85, median_width * 0.75)

        if slot_index < len(yolo_detections) and slot_index not in used_indices:
            aligned_det = yolo_detections[slot_index]
            aligned_char, aligned_center_x = self._char_record_to_symbol_and_x(aligned_det, fallback_index=slot_index)
            if (min_index is None or slot_index >= int(min_index)) and str(aligned_char or "").strip().upper() == expected_char:
                if abs(aligned_center_x - slot_center_x) <= allowed_gap * 1.35:
                    return slot_index

        best_index = None
        best_score = None

        for idx, det in enumerate(yolo_detections):
            if idx in used_indices:
                continue
            if min_index is not None and idx < int(min_index):
                continue

            det_char, det_center_x = self._char_record_to_symbol_and_x(det, fallback_index=idx)
            if str(det_char or "").strip().upper() != expected_char:
                continue

            center_gap = abs(float(det_center_x) - float(slot_center_x))
            if center_gap > allowed_gap * 1.35:
                continue

            score = (
                (center_gap / allowed_gap)
                + (0.12 * abs(idx - slot_index))
                - min(0.20, self._char_record_confidence(det) * 0.10)
            )

            if best_score is None or score < best_score:
                best_index = idx
                best_score = score

        return best_index

    def _apply_yolo_box_backend(self, base_detections, yolo_detections):
        ordered_base = self._sort_character_records_by_x(list(base_detections or []))
        ordered_yolo = self._sort_character_records_by_x(list(yolo_detections or []))

        if not ordered_base or not ordered_yolo:
            return ordered_base, None

        expected_text = self._characters_to_text(ordered_base)
        if not expected_text:
            return ordered_base, None

        base_widths = [self._char_record_width(det) for det in ordered_base if self._char_record_width(det) > 0.0]
        base_heights = [self._char_record_height(det) for det in ordered_base if self._char_record_height(det) > 0.0]
        base_center_ys = []
        for det in ordered_base:
            bbox = self._char_record_bbox(det)
            if bbox:
                base_center_ys.append((float(bbox[1]) + float(bbox[3])) / 2.0)

        median_width = float(sorted(base_widths)[len(base_widths) // 2]) if base_widths else 0.0
        median_height = float(sorted(base_heights)[len(base_heights) // 2]) if base_heights else 0.0
        median_center_y = float(sorted(base_center_ys)[len(base_center_ys) // 2]) if base_center_ys else 0.0

        used_yolo_indices = set()
        replaced = [self._clone_character_detection(det) for det in ordered_base]
        replaced_positions = []
        last_yolo_index = -1

        for slot_index, det in enumerate(ordered_base):
            expected_char = expected_text[slot_index] if slot_index < len(expected_text) else ""
            rescue_index = self._find_best_yolo_rescue_index(
                slot_index,
                expected_char,
                ordered_base,
                ordered_yolo,
                used_yolo_indices,
                min_index=last_yolo_index + 1,
            )
            if rescue_index is None:
                continue

            candidate = ordered_yolo[rescue_index]
            candidate_bbox = self._char_record_bbox(candidate)
            reference_bbox = self._char_record_bbox(det)
            if not candidate_bbox or not reference_bbox:
                continue

            candidate_width = max(1.0, self._char_record_width(candidate))
            candidate_height = max(1.0, self._char_record_height(candidate))
            reference_width = max(1.0, self._char_record_width(det))
            reference_height = max(1.0, self._char_record_height(det))
            candidate_center_y = (float(candidate_bbox[1]) + float(candidate_bbox[3])) / 2.0
            reference_center_y = (float(reference_bbox[1]) + float(reference_bbox[3])) / 2.0

            width_ratio = candidate_width / max(reference_width, median_width * 0.85, 1.0)
            height_ratio = candidate_height / max(reference_height, median_height * 0.85, 1.0)
            center_y_gap = abs(candidate_center_y - reference_center_y)
            median_center_y_gap = abs(candidate_center_y - median_center_y) if median_center_y > 0.0 else 0.0
            allowed_center_y_gap = max(6.0, reference_height * 0.30, median_height * 0.28)

            if width_ratio < 0.35 or width_ratio > 2.25:
                continue
            if height_ratio < 0.55 or height_ratio > 1.90:
                continue
            if center_y_gap > allowed_center_y_gap:
                continue
            if median_center_y > 0.0 and median_center_y_gap > max(8.0, median_height * 0.34):
                continue
            if self._char_record_confidence(candidate) < 0.18:
                continue

            replaced[slot_index] = self._clone_character_detection(
                candidate,
                character=expected_char,
                method="yolo",
            )
            used_yolo_indices.add(rescue_index)
            replaced_positions.append(slot_index)
            last_yolo_index = rescue_index

        if not replaced_positions:
            return ordered_base, None

        replaced = self._sort_character_records_by_x(replaced)
        if self._characters_to_text(replaced) != expected_text:
            return ordered_base, None

        details = {
            "box_backend": "yolo",
            "box_backend_positions": list(replaced_positions),
            "box_backend_count": int(len(replaced_positions)),
        }
        return replaced, details

    def _repair_ocr_with_yolo_boxes(self, ocr_detections, yolo_detections, true_texts, max_mismatch_count: int = 2):
        ordered_ocr = self._sort_character_records_by_x(list(ocr_detections or []))
        ordered_yolo = self._sort_character_records_by_x(list(yolo_detections or []))

        if not ordered_ocr or not ordered_yolo:
            return None, None

        max_mismatch_count = max(1, min(5, int(max_mismatch_count or 2)))

        ocr_text = self._characters_to_text(ordered_ocr)
        expected_text = self._pick_best_true_text(ocr_text, true_texts, same_length_only=True)
        if not expected_text:
            return None, None

        mismatch_positions = self._get_text_mismatch_positions(ocr_text, expected_text)
        if not mismatch_positions or len(mismatch_positions) > max_mismatch_count:
            return None, None

        repaired = [self._clone_character_detection(det) for det in ordered_ocr]
        used_yolo_indices = set()

        for slot_index in mismatch_positions:
            rescue_index = self._find_best_yolo_rescue_index(
                slot_index,
                expected_text[slot_index],
                ordered_ocr,
                ordered_yolo,
                used_yolo_indices,
            )
            if rescue_index is None:
                return None, None

            used_yolo_indices.add(rescue_index)
            repaired[slot_index] = self._clone_character_detection(
                ordered_yolo[rescue_index],
                character=expected_text[slot_index],
                method="yolo",
            )

        repaired = self._sort_character_records_by_x(repaired)
        repaired_text = self._characters_to_text(repaired)
        if repaired_text != expected_text:
            return None, None

        details = {
            "ocr_text": ocr_text,
            "yolo_text": self._characters_to_text(ordered_yolo),
            "expected_text": expected_text,
            "mismatch_positions": list(mismatch_positions),
            "max_mismatch_count": int(max_mismatch_count),
        }
        return repaired, details

    def _resolve_canonical_detections(self, method, combined_detections, ocr_detections, yolo_detections, true_texts, hybrid_rescue_max_chars: int = 2, prefer_yolo_box_positions: bool = False):
        ordered_combined = self._sort_character_records_by_x(list(combined_detections or []))
        ordered_ocr = self._sort_character_records_by_x(list(ocr_detections or []))
        ordered_yolo = self._sort_character_records_by_x(list(yolo_detections or []))
        normalized_truths = [
            str(item or "").strip().upper()
            for item in (true_texts or [])
            if str(item or "").strip()
        ]

        if method == DetectionMethod.OCR:
            return ordered_ocr or ordered_combined, "ocr_only", None

        if method == DetectionMethod.YOLO:
            return ordered_yolo or ordered_combined, "yolo_only", None

        if normalized_truths:
            ocr_text = self._characters_to_text(ordered_ocr)
            yolo_text = self._characters_to_text(ordered_yolo)

            if ocr_text and ocr_text in normalized_truths:
                details = {"final_text": ocr_text}
                if prefer_yolo_box_positions:
                    rebuilt, backend_details = self._apply_yolo_box_backend(ordered_ocr, ordered_yolo)
                    if backend_details:
                        details.update(backend_details)
                        return rebuilt, "ocr_exact", details
                return ordered_ocr, "ocr_exact", details

            if yolo_text and yolo_text in normalized_truths:
                return ordered_yolo, "yolo_exact", {"final_text": yolo_text}

            rescued, rescue_details = self._repair_ocr_with_yolo_boxes(
                ordered_ocr,
                ordered_yolo,
                normalized_truths,
                max_mismatch_count=hybrid_rescue_max_chars,
            )
            if rescued:
                if prefer_yolo_box_positions:
                    rebuilt, backend_details = self._apply_yolo_box_backend(rescued, ordered_yolo)
                    if backend_details:
                        if not isinstance(rescue_details, dict):
                            rescue_details = {}
                        rescue_details.update(backend_details)
                        return rebuilt, "ocr_yolo_rescue", rescue_details
                return rescued, "ocr_yolo_rescue", rescue_details

            best_source = ordered_ocr or ordered_yolo or ordered_combined
            best_strategy = "ocr_fallback" if ordered_ocr else ("yolo_fallback" if ordered_yolo else "both_combined")
            best_distance = self._best_text_distance(self._characters_to_text(best_source), normalized_truths)

            for candidate_source, candidate_strategy in (
                (ordered_yolo, "yolo_fallback"),
                (ordered_combined, "both_combined"),
            ):
                if not candidate_source:
                    continue

                candidate_distance = self._best_text_distance(self._characters_to_text(candidate_source), normalized_truths)
                if candidate_distance < best_distance:
                    best_source = candidate_source
                    best_strategy = candidate_strategy
                    best_distance = candidate_distance

            return best_source, best_strategy, {"distance": best_distance}

        return ordered_combined, "both_combined_no_gt", None

    def _get_preview_box_mode_key(self) -> str:
        raw_value = str((getattr(self, "preview_box_mode_var", None).get() if hasattr(self, "preview_box_mode_var") else "AUTO") or "AUTO").strip()
        if not raw_value:
            return "AUTO"

        direct_key = raw_value.upper()
        if direct_key in PREVIEW_BOX_MODE_LABELS:
            return direct_key

        return PREVIEW_BOX_MODE_BY_LABEL.get(raw_value, "AUTO")

    def _normalize_detection_method_key(self, raw_value=None) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return "OCR"

        upper_value = value.upper()
        if upper_value in DETECTION_METHOD_LABELS:
            return upper_value

        return DETECTION_METHOD_KEY_BY_LABEL.get(value, "OCR")

    def _get_detection_method_key(self) -> str:
        raw_value = getattr(self, "detection_method_var", None).get() if hasattr(self, "detection_method_var") else "OCR"
        return self._normalize_detection_method_key(raw_value)

    def _get_hybrid_rescue_max_chars(self) -> int:
        try:
            value = int(self.hybrid_rescue_max_chars_var.get())
        except Exception:
            value = 2
        return max(1, min(5, value))

    def _use_hybrid_yolo_box_backend(self) -> bool:
        try:
            return bool(self.hybrid_yolo_box_backend_var.get())
        except Exception:
            return True

    def _get_hybrid_detection_status_text(self) -> str:
        rescue_chars = self._get_hybrid_rescue_max_chars()
        backend_state = "ON" if self._use_hybrid_yolo_box_backend() else "OFF"
        return f"Tryb hybrydowy: OCR+YOLO rescue <= {rescue_chars}, poprawa boxow: {backend_state}"

    def _get_preview_box_mode_label(self, key=None) -> str:
        resolved_key = (key or self._get_preview_box_mode_key() or "AUTO").upper().strip()
        return PREVIEW_BOX_MODE_LABELS.get(resolved_key, PREVIEW_BOX_MODE_LABELS["AUTO"])

    def _get_preview_sort_mode_key(self) -> str:
        raw_value = str((getattr(self, "preview_sort_mode_var", None).get() if hasattr(self, "preview_sort_mode_var") else "DEFAULT") or "DEFAULT").strip().upper()
        return raw_value if raw_value in PREVIEW_SORT_LABELS else "DEFAULT"

    def _get_preview_sort_priority(self, pid: str, data: dict, original_index: int):
        mode_key = self._get_preview_sort_mode_key()
        status = str((data or {}).get("status", "unknown")).strip().lower()
        strategy_bucket = self._get_perfect_strategy_bucket(data)

        if mode_key == "DEFAULT":
            return (0, int(original_index))

        if mode_key == "PERFECT":
            if status == "perfect":
                return (0, int(original_index))
            if status == "needs_fix":
                return (1, int(original_index))
            return (2, int(original_index))

        preferred_bucket = {
            "YOLO": "yolo_exact",
            "RES": "ocr_yolo_rescue",
            "OCR": "ocr_exact",
        }.get(mode_key)

        if preferred_bucket:
            if status == "perfect" and strategy_bucket == preferred_bucket:
                return (0, int(original_index))
            if status == "perfect":
                return (1, int(original_index))
            if status == "needs_fix":
                return (2, int(original_index))
            return (3, int(original_index))

        return (0, int(original_index))

    def _get_sorted_preview_plate_ids(self, ordered_pids):
        base_order = list(ordered_pids or [])
        mode_key = self._get_preview_sort_mode_key()
        if mode_key == "DEFAULT":
            return base_order

        indexed = list(enumerate(base_order))
        indexed.sort(
            key=lambda item: self._get_preview_sort_priority(
                item[1],
                self.preview_metadata.get(item[1], {}),
                item[0],
            )
        )
        return [pid for _, pid in indexed]

    def _set_preview_sort_hover(self, mode_key: str, hovered: bool):
        normalized_key = str(mode_key or "").strip().upper()
        if hovered:
            self._preview_sort_hover_key = normalized_key
        elif self._preview_sort_hover_key == normalized_key:
            self._preview_sort_hover_key = None
        self._apply_preview_sort_bar_style()

    def _get_readable_text_color(self, background: str, preferred: str = None) -> str:
        def _normalize_hex(color_value):
            raw = str(color_value or "").strip()
            if not raw.startswith("#"):
                return None
            hex_part = raw[1:]
            if len(hex_part) == 3:
                hex_part = "".join(ch * 2 for ch in hex_part)
            if len(hex_part) != 6:
                return None
            try:
                return tuple(int(hex_part[i:i + 2], 16) for i in (0, 2, 4))
            except Exception:
                return None

        def _relative_luminance(rgb):
            channels = []
            for channel in rgb:
                normalized = channel / 255.0
                if normalized <= 0.03928:
                    channels.append(normalized / 12.92)
                else:
                    channels.append(((normalized + 0.055) / 1.055) ** 2.4)
            return (0.2126 * channels[0]) + (0.7152 * channels[1]) + (0.0722 * channels[2])

        def _contrast_ratio(color_a, color_b):
            lum_a = _relative_luminance(color_a)
            lum_b = _relative_luminance(color_b)
            lighter = max(lum_a, lum_b)
            darker = min(lum_a, lum_b)
            return (lighter + 0.05) / (darker + 0.05)

        bg_rgb = _normalize_hex(background)
        if bg_rgb is None:
            return preferred or "#ffffff"

        preferred_rgb = _normalize_hex(preferred)
        if preferred_rgb is not None and _contrast_ratio(bg_rgb, preferred_rgb) >= 4.5:
            return preferred

        dark_text = "#111111"
        light_text = "#ffffff"
        dark_rgb = _normalize_hex(dark_text)
        light_rgb = _normalize_hex(light_text)
        if dark_rgb is None or light_rgb is None:
            return preferred or light_text

        dark_ratio = _contrast_ratio(bg_rgb, dark_rgb)
        light_ratio = _contrast_ratio(bg_rgb, light_rgb)
        return dark_text if dark_ratio >= light_ratio else light_text

    def _apply_preview_sort_bar_style(self):
        palette = getattr(self.app, "palette", {})
        frame = getattr(self, "preview_sort_bar", None)
        label = getattr(self, "preview_sort_title_lbl", None)
        if frame is not None:
            try:
                frame.configure(
                    bg=palette.get("panel_alt", palette.get("panel", "#252526")),
                    highlightbackground=palette.get("border", "#3c3c3c"),
                    highlightcolor=palette.get("border", "#3c3c3c"),
                )
            except Exception:
                pass
        if label is not None:
            try:
                label.configure(
                    bg=palette.get("panel_alt", palette.get("panel", "#252526")),
                    fg=palette.get("muted", "#a0a0a0"),
                )
            except Exception:
                pass
        buttons_frame = getattr(self, "preview_sort_buttons_frame", None)
        if buttons_frame is not None:
            try:
                buttons_frame.configure(bg=palette.get("panel_alt", palette.get("panel", "#252526")))
            except Exception:
                pass
            for child in buttons_frame.winfo_children():
                if isinstance(child, tk.Frame):
                    try:
                        child.configure(bg=palette.get("border", "#3c3c3c"))
                    except Exception:
                        pass

        active_key = self._get_preview_sort_mode_key()
        hover_key = str(getattr(self, "_preview_sort_hover_key", "") or "").strip().upper()
        for mode_key, button in getattr(self, "preview_sort_buttons", {}).items():
            if button is None:
                continue
            is_active = mode_key == active_key
            is_hovered = mode_key == hover_key
            bg = palette.get("panel_alt", palette.get("panel", "#2d2d30"))
            fg = palette.get("fg", "#f3f3f3")
            relief = tk.RAISED
            border = 1

            if is_active:
                bg = palette.get("surface_info", palette.get("button_hover", "#3a3d41"))
                relief = tk.SUNKEN
            elif is_hovered:
                bg = palette.get("button_hover", palette.get("surface_info", "#34373b"))

            resolved_fg = self._get_readable_text_color(bg, preferred=fg)
            active_bg = bg if is_active else palette.get("button_hover", bg)
            active_fg = self._get_readable_text_color(active_bg, preferred=resolved_fg)

            try:
                button.configure(
                    bg=bg,
                    fg=resolved_fg,
                    activebackground=active_bg,
                    activeforeground=active_fg,
                    relief=relief,
                    bd=border,
                    highlightbackground=palette.get("border", "#3c3c3c"),
                    highlightcolor=palette.get("border", "#3c3c3c"),
                    disabledforeground=resolved_fg,
                )
            except Exception:
                pass

    def _on_preview_sort_mode_change(self, mode_key: str = None):
        normalized_key = str(mode_key or self._get_preview_sort_mode_key()).strip().upper()
        if normalized_key not in PREVIEW_SORT_LABELS:
            normalized_key = "DEFAULT"

        try:
            if self.preview_sort_mode_var.get() != normalized_key:
                self.preview_sort_mode_var.set(normalized_key)
        except Exception:
            pass

        try:
            self._save_local_setting("char_preview_sort_mode", normalized_key)
        except Exception:
            pass

        self._apply_preview_sort_bar_style()

        if hasattr(self, "plates_listbox"):
            self._rebuild_preview_listbox(preserve_selection=True)
            try:
                self._on_preview_select(None)
            except Exception:
                pass

    def _get_preview_box_variants(self, data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}
        canonical_chars = self._sort_character_records_by_x(data.get("characters", []))
        yolo_filtered = self._sort_character_records_by_x(data.get("yolo_detections", []))
        yolo_nms = self._sort_character_records_by_x(data.get("yolo_nms_detections", []))
        yolo_raw = self._sort_character_records_by_x(data.get("yolo_raw_detections", []))

        if not yolo_filtered:
            yolo_from_canonical = [
                rec for rec in canonical_chars
                if isinstance(rec, dict) and str(rec.get("method", "")).strip().lower() == "yolo"
            ]
            yolo_filtered = self._sort_character_records_by_x(yolo_from_canonical)

        return {
            "FINAL": canonical_chars,
            "YOLO_FILTERED": yolo_filtered,
            "YOLO_NMS": yolo_nms,
            "YOLO_RAW": yolo_raw,
        }

    def _get_preview_box_records(self, data: dict):
        variants = self._get_preview_box_variants(data)
        method_name = self._get_detection_method_key()
        mode_key = self._get_preview_box_mode_key()

        if mode_key == "AUTO":
            if method_name == "YOLO":
                for candidate_key in ("YOLO_FILTERED", "YOLO_NMS", "YOLO_RAW"):
                    candidate_records = variants.get(candidate_key, [])
                    if candidate_records:
                        return candidate_records, candidate_key
            return variants.get("FINAL", []), "FINAL"

        return variants.get(mode_key, []), mode_key

    def _get_preview_box_palette(self, index: int):
        palettes = [
            ("#ff6b6b", "#ffc1c1", "#ffe9e9"),
            ("#4ecdc4", "#a6f4ef", "#e8fffd"),
            ("#ffd166", "#ffe29a", "#fff7db"),
            ("#6c5ce7", "#c8bfff", "#f0edff"),
            ("#00b894", "#7ee6ca", "#ebfff8"),
            ("#0984e3", "#74b9ff", "#ecf7ff"),
            ("#e17055", "#fab1a0", "#fff1ec"),
            ("#a29bfe", "#d6d1ff", "#f5f4ff"),
            ("#e84393", "#ffb0d5", "#fff0f7"),
            ("#2d98da", "#8fd0ff", "#eef8ff"),
        ]
        return palettes[index % len(palettes)]

    def _on_preview_box_mode_var_write(self, *_args):
        self._apply_preview_mode_radio_style()

    def _on_yolo_option_var_write(self, *_args):
        self._apply_yolo_option_check_style()
        try:
            self._save_local_setting("char_yolo_agnostic_nms", bool(self.yolo_agnostic_nms_var.get()))
        except Exception:
            pass
        try:
            self._save_local_setting("char_hybrid_yolo_box_backend", bool(self.hybrid_yolo_box_backend_var.get()))
        except Exception:
            pass
        if self._get_detection_method_key() == "BOTH" and hasattr(self, "test_status_lbl"):
            self._set_test_status(self._get_hybrid_detection_status_text(), "info")

    def _on_gold_export_filter_var_write(self, *_args):
        self._apply_gold_export_filter_check_style()

    def _on_gold_export_split_var_write(self, *_args):
        self._on_gold_export_split_change()

    def _draw_selection_indicator(self, canvas, kind: str, selected: bool, background: str):
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        outline = palette.get("border", "#5a5a5a")
        accent = palette.get("accent", "#4ecdc4")
        success = palette.get("success", "#4ec9b0")

        try:
            canvas.configure(bg=background)
            canvas.delete("all")
        except Exception:
            return

        if kind == "radio":
            canvas.create_oval(2, 2, 14, 14, outline=outline, width=2, fill=background)
            if selected:
                canvas.create_oval(5, 5, 11, 11, outline=success, width=1, fill=success)
            else:
                canvas.create_oval(5, 5, 11, 11, outline=background, width=1, fill=background)
            return

        canvas.create_rectangle(2, 2, 14, 14, outline=(success if selected else outline), width=2, fill=background)
        if selected:
            canvas.create_line(
                4, 8, 7, 11, 12, 5,
                fill=success,
                width=2,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND
            )

    def _set_selection_row_hover(self, row_info: dict, hovered: bool):
        if not isinstance(row_info, dict):
            return
        row_info["hovered"] = bool(hovered)
        self._refresh_selection_row(row_info)

    def _refresh_selection_row(self, row_info: dict):
        if not isinstance(row_info, dict):
            return

        frame = row_info.get("frame")
        label = row_info.get("label")
        indicator = row_info.get("indicator")
        if frame is None or label is None or indicator is None:
            return

        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", palette.get("bg", "#252526"))
        hover_bg = palette.get("surface_info", palette.get("button_hover", palette.get("panel_alt", "#2d2d30")))
        fg = palette.get("fg", "#f3f3f3")
        muted_fg = palette.get("muted_dim", palette.get("muted", "#a0a0a0"))
        selected = bool(row_info.get("selected_getter", lambda: False)())
        enabled = bool(row_info.get("enabled", True))
        hovered = bool(row_info.get("hovered", False))
        row_bg = hover_bg if hovered else panel_bg
        row_fg = fg if enabled else muted_fg

        try:
            frame.configure(bg=row_bg)
        except Exception:
            pass
        try:
            label.configure(bg=row_bg, fg=row_fg)
        except Exception:
            pass

        self._draw_selection_indicator(indicator, row_info.get("kind", "radio"), selected, row_bg)

    def _apply_preview_mode_radio_style(self):
        for row_info in getattr(self, "preview_box_mode_rows", []):
            self._refresh_selection_row(row_info)

    def _apply_yolo_option_check_style(self):
        for row_info in getattr(self, "yolo_option_rows", []):
            self._refresh_selection_row(row_info)

    def _apply_gold_export_filter_check_style(self):
        for row_info in getattr(self, "gold_export_filter_rows", []):
            self._refresh_selection_row(row_info)

    def _apply_gold_export_split_check_style(self):
        row_info = getattr(self, "gold_export_split_row_info", None)
        if isinstance(row_info, dict):
            self._refresh_selection_row(row_info)

    def _apply_plates_legend_style(self):
        palette = getattr(self.app, "palette", {})
        bg = palette.get("panel", palette.get("bg", "#252526"))
        fg = palette.get("fg", "#f3f3f3")
        muted_fg = palette.get("muted", "#a0a0a0")
        success_fg = palette.get("success", "#2ecc71")
        error_fg = palette.get("error", "#e74c3c")

        frame = getattr(self, "plates_legend_frame", None)
        if frame is not None:
            try:
                frame.configure(bg=bg)
            except Exception:
                pass

        label_configs = (
            ("plates_legend_title_lbl", {"bg": bg, "fg": fg, "font": ("Segoe UI", 9, "bold")}),
            ("plates_legend_perfect_dot_lbl", {"bg": bg, "fg": success_fg, "font": ("Segoe UI", 11, "bold")}),
            ("plates_legend_perfect_text_lbl", {"bg": bg, "fg": fg, "font": ("Segoe UI", 9, "bold")}),
            ("plates_legend_sep_lbl", {"bg": bg, "fg": muted_fg, "font": ("Segoe UI", 9)}),
            ("plates_legend_error_dot_lbl", {"bg": bg, "fg": error_fg, "font": ("Segoe UI", 11, "bold")}),
            ("plates_legend_error_text_lbl", {"bg": bg, "fg": fg, "font": ("Segoe UI", 9, "bold")}),
        )
        for name, config in label_configs:
            widget = getattr(self, name, None)
            if widget is None:
                continue
            try:
                widget.configure(**config)
            except Exception:
                pass

    def _apply_preview_info_stats_style(self):
        palette = getattr(self.app, "palette", {})
        bg = palette.get("panel", palette.get("bg", "#252526"))
        fg = palette.get("fg", "#f3f3f3")
        muted_fg = palette.get("muted", "#a0a0a0")
        success_fg = palette.get("success", "#2ecc71")
        error_fg = palette.get("error", "#e74c3c")

        frame = getattr(self, "preview_counts_frame", None)
        if frame is not None:
            try:
                frame.configure(bg=bg)
            except Exception:
                pass

        label_configs = (
            ("preview_perfect_dot_lbl", {"bg": bg, "fg": success_fg, "font": ("Segoe UI", 11, "bold")}),
            ("preview_perfect_count_lbl", {"bg": bg, "fg": fg, "font": ("Segoe UI", 9, "bold")}),
            ("preview_counts_sep1_lbl", {"bg": bg, "fg": muted_fg, "font": ("Segoe UI", 9)}),
            ("preview_error_dot_lbl", {"bg": bg, "fg": error_fg, "font": ("Segoe UI", 11, "bold")}),
            ("preview_error_count_lbl", {"bg": bg, "fg": fg, "font": ("Segoe UI", 9, "bold")}),
            ("preview_counts_sep2_lbl", {"bg": bg, "fg": muted_fg, "font": ("Segoe UI", 9)}),
            ("preview_unknown_dot_lbl", {"bg": bg, "fg": muted_fg, "font": ("Segoe UI", 11, "bold")}),
            ("preview_unknown_count_lbl", {"bg": bg, "fg": fg, "font": ("Segoe UI", 9)}),
        )
        for name, config in label_configs:
            widget = getattr(self, name, None)
            if widget is None:
                continue
            try:
                widget.configure(**config)
            except Exception:
                pass

    def _get_preview_source_visual_style(self, source_tag: str):
        palette = getattr(self.app, "palette", {})
        normalized = self._normalize_character_source_tag(raw_tag=source_tag)

        styles = {
            "ocr": {
                "outline": palette.get("info", "#56b6ff"),
                "guide": "#9fd8ff",
                "char": "#dff4ff",
                "badge_bg": "#163346",
                "badge_fg": "#bfe9ff",
                "label": "O",
                "legend": "OCR",
            },
            "yolo": {
                "outline": palette.get("warning", "#f4c27a"),
                "guide": "#ffd79c",
                "char": "#fff1d6",
                "badge_bg": "#4d3310",
                "badge_fg": "#ffe3af",
                "label": "Y",
                "legend": "YOLO",
            },
            "yolo_rescue": {
                "outline": palette.get("success", "#2ecc71"),
                "guide": "#8be7b1",
                "char": "#ddffe9",
                "badge_bg": "#123b25",
                "badge_fg": "#bff5d1",
                "label": "R",
                "legend": "Rescue",
            },
        }
        return styles.get(normalized, styles["ocr"])

    def _draw_preview_text_badge(
        self,
        canvas,
        x: float,
        y: float,
        text: str,
        fill_color: str,
        *,
        anchor=tk.NW,
        font=("Segoe UI", 8, "bold"),
        outline_color: str = None,
        text_color: str = None,
        pad_x: int = 4,
        pad_y: int = 2,
        tags=None,
    ):
        if canvas is None or not text:
            return None, None

        resolved_fill = str(fill_color or "#3c3c3c")
        resolved_outline = str(outline_color or resolved_fill)
        resolved_text = str(text_color or self._get_readable_text_color(resolved_fill, preferred="#ffffff"))

        try:
            text_id = canvas.create_text(
                x,
                y,
                text=text,
                fill=resolved_text,
                font=font,
                anchor=anchor,
            )
            text_bbox = canvas.bbox(text_id)
            if not text_bbox:
                return text_id, None

            bg_id = canvas.create_rectangle(
                text_bbox[0] - pad_x,
                text_bbox[1] - pad_y,
                text_bbox[2] + pad_x,
                text_bbox[3] + pad_y,
                fill=resolved_fill,
                outline=resolved_outline,
                width=1,
            )
            canvas.tag_raise(text_id, bg_id)
            if tags:
                for tag in list(tags):
                    try:
                        canvas.addtag_withtag(str(tag), text_id)
                        canvas.addtag_withtag(str(tag), bg_id)
                    except Exception:
                        pass
            return text_id, bg_id
        except Exception:
            return None, None

    def _measure_preview_text_badge(
        self,
        canvas,
        text: str,
        *,
        font=("Segoe UI", 8, "bold"),
        pad_x: int = 4,
        pad_y: int = 2,
    ):
        if canvas is None or not text:
            return 0, 0

        temp_id = None
        try:
            temp_id = canvas.create_text(
                -1000,
                -1000,
                text=text,
                font=font,
                anchor=tk.NW,
            )
            bbox = canvas.bbox(temp_id)
            if not bbox:
                return 0, 0
            width = max(0, int(bbox[2] - bbox[0])) + (pad_x * 2)
            height = max(0, int(bbox[3] - bbox[1])) + (pad_y * 2)
            return width, height
        except Exception:
            return 0, 0
        finally:
            if temp_id is not None:
                try:
                    canvas.delete(temp_id)
                except Exception:
                    pass

    def _get_preview_badge_layout_metrics(self):
        return {
            "font": ("Segoe UI", 6, "normal"),
            "pad_x": 2,
            "pad_y": 1,
            "col_gap": 3,
            "row_gap": 2,
        }

    def _estimate_preview_badge_layout(self, canvas, badge_specs, image_width: float):
        if canvas is None or image_width <= 0:
            return 1, 12

        metrics = self._get_preview_badge_layout_metrics()
        prepared = []
        max_height = 0

        for spec in sorted(list(badge_specs or []), key=lambda item: float(item.get("center_ref", item.get("center_x", 0.0)))):
            text = str(spec.get("text", "") or "").strip()
            if not text:
                continue

            width, height = self._measure_preview_text_badge(
                canvas,
                text,
                font=metrics["font"],
                pad_x=metrics["pad_x"],
                pad_y=metrics["pad_y"],
            )
            if width <= 0 or height <= 0:
                continue

            center_ref = spec.get("center_ref", spec.get("center_x", 0.0))
            try:
                center_ref = float(center_ref)
            except Exception:
                center_ref = 0.0

            prepared.append({
                "center_ref": center_ref,
                "width": float(width),
            })
            max_height = max(max_height, int(height))

        if not prepared:
            return 1, max(10, max_height or 12)

        row_last_right = []
        for spec in prepared:
            width = float(spec["width"])
            desired_left = (float(spec["center_ref"]) * float(image_width)) - (width / 2.0)
            desired_left = max(0.0, min(desired_left, float(image_width) - width))

            placed = False
            for row_idx in range(len(row_last_right)):
                candidate_left = max(desired_left, row_last_right[row_idx] + metrics["col_gap"])
                if candidate_left + width <= float(image_width):
                    row_last_right[row_idx] = candidate_left + width
                    placed = True
                    break

            if not placed:
                row_last_right.append(desired_left + width)

        return max(1, len(row_last_right)), max(10, max_height or 12)

    def _draw_preview_source_legend(self, canvas, x: float, y: float):
        if canvas is None:
            return float(x)

        text_fg = getattr(self.app, "palette", {}).get("muted", "#b0b0b0")
        badge_font = ("Segoe UI", 7, "bold")
        label_font = ("Segoe UI", 8, "normal")
        badge_pad_x = 2
        badge_pad_y = 1
        item_gap = 12
        current_x = float(x)

        for source_key in ("ocr", "yolo", "yolo_rescue"):
            style = self._get_preview_source_visual_style(source_key)
            badge_text = str(style.get("label", "") or "").strip()
            legend_text = str(style.get("legend", "") or badge_text).strip()

            badge_width, badge_height = self._measure_preview_text_badge(
                canvas,
                badge_text,
                font=badge_font,
                pad_x=badge_pad_x,
                pad_y=badge_pad_y,
            )

            self._draw_preview_text_badge(
                canvas,
                current_x,
                y,
                badge_text,
                fill_color=style.get("outline", "#3c3c3c"),
                outline_color=style.get("outline", "#3c3c3c"),
                text_color=self._get_readable_text_color(style.get("outline", "#3c3c3c"), preferred=style.get("badge_fg", "#ffffff")),
                font=badge_font,
                anchor=tk.NW,
                pad_x=badge_pad_x,
                pad_y=badge_pad_y,
            )

            label_x = current_x + badge_width + 5
            label_y = y + max(0, badge_height / 2.0)
            label_id = canvas.create_text(
                label_x,
                label_y,
                text=legend_text,
                fill=text_fg,
                font=label_font,
                anchor=tk.W,
            )
            label_bbox = canvas.bbox(label_id)
            if label_bbox:
                current_x = float(label_bbox[2]) + item_gap
            else:
                current_x = label_x + item_gap

        return current_x

    def _draw_preview_top_badges(
        self,
        canvas,
        badge_specs,
        *,
        image_left: float,
        image_right: float,
        image_top: float,
        top_limit: float,
    ):
        if canvas is None:
            return

        metrics = self._get_preview_badge_layout_metrics()
        badge_font = metrics["font"]
        pad_x = metrics["pad_x"]
        pad_y = metrics["pad_y"]
        col_gap = metrics["col_gap"]
        row_gap = metrics["row_gap"]
        prepared = []

        for spec in sorted(list(badge_specs or []), key=lambda item: float(item.get("center_x", 0.0))):
            text = str(spec.get("text", "") or "").strip()
            if not text:
                continue
            width, height = self._measure_preview_text_badge(
                canvas,
                text,
                font=badge_font,
                pad_x=pad_x,
                pad_y=pad_y,
            )
            if width <= 0 or height <= 0:
                continue
            prepared.append({
                **spec,
                "text": text,
                "width": width,
                "height": height,
            })

        if not prepared:
            return

        badge_height = max(item["height"] for item in prepared)
        row_tops = []
        next_row_top = float(image_top) - 4 - badge_height
        while next_row_top >= float(top_limit):
            row_tops.append(next_row_top)
            next_row_top -= badge_height + row_gap

        if not row_tops:
            row_tops.append(max(float(top_limit), float(image_top) - 4 - badge_height))

        row_last_right = [float(image_left) - col_gap for _ in row_tops]

        for spec in prepared:
            desired_left = float(spec["center_x"]) - (float(spec["width"]) / 2.0)
            desired_left = max(float(image_left), min(desired_left, float(image_right) - float(spec["width"])))

            placed_row_idx = None
            placed_left = None
            for row_idx, row_top in enumerate(row_tops):
                candidate_left = max(desired_left, row_last_right[row_idx] + col_gap)
                if candidate_left + float(spec["width"]) <= float(image_right):
                    placed_row_idx = row_idx
                    placed_left = candidate_left
                    break

            if placed_row_idx is None:
                extra_row_top = row_tops[-1] - (badge_height + row_gap)
                if extra_row_top >= float(top_limit):
                    row_tops.append(extra_row_top)
                    row_last_right.append(float(image_left) - col_gap)
                    placed_row_idx = len(row_tops) - 1
                    placed_left = max(
                        float(image_left),
                        min(desired_left, float(image_right) - float(spec["width"]))
                    )

            if placed_row_idx is None:
                best_row_idx = min(range(len(row_tops)), key=lambda idx: row_last_right[idx])
                fallback_left = max(float(image_left), min(desired_left, float(image_right) - float(spec["width"])))
                fallback_left = max(fallback_left, row_last_right[best_row_idx] + col_gap)
                fallback_left = min(fallback_left, float(image_right) - float(spec["width"]))
                placed_row_idx = best_row_idx
                placed_left = fallback_left

            row_last_right[placed_row_idx] = placed_left + float(spec["width"])
            badge_top = row_tops[placed_row_idx]
            badge_key = str(spec.get("badge_key", spec.get("text", "")))
            offset_dx, offset_dy = self._get_preview_badge_offset(self._preview_active_pid, badge_key)
            badge_left = float(placed_left) + float(offset_dx)
            badge_top = float(badge_top) + float(offset_dy)
            badge_center_x = badge_left + (float(spec["width"]) / 2.0)
            badge_bottom_y = badge_top + badge_height

            line_id = None
            try:
                line_id = canvas.create_line(
                    badge_center_x,
                    badge_bottom_y,
                    float(spec["center_x"]),
                    float(spec.get("box_top_y", image_top)),
                    fill=str(spec.get("guide_color", spec.get("fill_color", "#cccccc"))),
                    dash=(2, 2),
                    width=1,
                )
            except Exception:
                pass

            badge_tag = f"preview_badge::{badge_key}"
            self._draw_preview_text_badge(
                canvas,
                badge_left,
                badge_top,
                spec["text"],
                fill_color=str(spec.get("fill_color", "#3c3c3c")),
                outline_color=str(spec.get("outline_color", spec.get("fill_color", "#3c3c3c"))),
                text_color=str(spec.get("text_color", "#ffffff")),
                font=badge_font,
                anchor=tk.NW,
                pad_x=pad_x,
                pad_y=pad_y,
                tags=("preview_badge", badge_tag),
            )

            self._preview_badge_runtime[badge_key] = {
                "tag": badge_tag,
                "line_id": line_id,
                "box_id": spec.get("box_id"),
                "box_color": str(spec.get("box_color", spec.get("fill_color", "#cccccc"))),
                "line_color": str(spec.get("guide_color", spec.get("fill_color", "#cccccc"))),
                "box_width": 2,
                "line_width": 1,
                "badge_width": float(spec["width"]),
                "badge_height": float(badge_height),
                "left_limit": float(image_left),
                "right_limit": float(image_right),
                "top_limit": float(top_limit),
                "base_left": float(placed_left),
                "base_top": float(row_tops[placed_row_idx]),
                "base_center_x": float(placed_left) + (float(spec["width"]) / 2.0),
                "base_bottom_y": float(row_tops[placed_row_idx]) + badge_height,
                "box_center_x": float(spec["center_x"]),
                "box_top_y": float(spec.get("box_top_y", image_top)),
                "offset_dx": float(offset_dx),
                "offset_dy": float(offset_dy),
            }

    def _draw_preview_canvas_info_overlay(
        self,
        canvas,
        canvas_width: int,
        data: dict,
        box_chars,
        has_boxes: bool,
    ):
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        panel_border = palette.get("border", "#3c3c3c")
        title_fg = palette.get("fg", "#f3f3f3")
        muted_fg = palette.get("muted", "#b0b0b0")
        success_fg = palette.get("success", "#2ecc71")
        error_fg = palette.get("error", "#e74c3c")
        warning_fg = palette.get("warning", "#f4c27a")

        status = str((data or {}).get("status", "unknown") or "unknown").strip().lower()
        status_text = {
            "perfect": "Perfect",
            "needs_fix": "Błędy",
        }.get(status, "Nieocenione")
        status_color = {
            "perfect": success_fg,
            "needs_fix": error_fg,
        }.get(status, muted_fg)

        final_text = self._characters_to_text((data or {}).get("characters", []))
        final_text = final_text if final_text else "brak"
        source_counts = self._count_character_sources(box_chars, data=data)
        source_line = (
            f"O={int(source_counts.get('ocr', 0))} | "
            f"Y={int(source_counts.get('yolo', 0))} | "
            f"R={int(source_counts.get('yolo_rescue', 0))}"
        )
        bar_height = 32
        canvas.create_rectangle(
            0,
            0,
            max(40, int(canvas_width)),
            bar_height,
            fill=panel_bg,
            outline=panel_border,
            width=1
        )

        reset_text_id, reset_bg_id = self._draw_preview_text_badge(
            canvas,
            10,
            6,
            "Reset widoku",
            fill_color=panel_border,
            outline_color=panel_border,
            text_color=self._get_readable_text_color(panel_border, preferred=title_fg),
            font=("Segoe UI", 8, "bold"),
            anchor=tk.NW,
            pad_x=6,
            pad_y=2,
            tags=("preview_overlay_action", "preview_action::reset_view"),
        )
        reset_bbox = None
        try:
            reset_bbox = canvas.bbox(reset_bg_id or reset_text_id)
        except Exception:
            reset_bbox = None

        title_x = (float(reset_bbox[2]) + 12.0) if reset_bbox else 110.0
        title_id = canvas.create_text(
            title_x,
            16,
            text=f"Wynik: [{final_text}]",
            fill=title_fg,
            font=("Segoe UI", 9, "bold"),
            anchor=tk.W
        )
        title_bbox = canvas.bbox(title_id)

        legend_x = (float(title_bbox[2]) + 12.0) if title_bbox else (title_x + 120.0)
        self._draw_preview_source_legend(canvas, legend_x, 8)

        source_id = canvas.create_text(
            max(20, int(canvas_width) - 10),
            16,
            text=source_line,
            fill=(warning_fg if not has_boxes else muted_fg),
            font=("Segoe UI", 9),
            anchor=tk.E
        )
        source_bbox = canvas.bbox(source_id)
        canvas.create_text(
            max(20, int((source_bbox[0] - 10) if source_bbox else (int(canvas_width) - 160))),
            16,
            text=status_text,
            fill=status_color,
            font=("Segoe UI", 9, "bold"),
            anchor=tk.E
        )

    def _get_yolo_runtime_settings(self):
        conf = float(self.yolo_conf_var.get())
        iou = float(self.yolo_iou_var.get())
        overlap = float(self.yolo_overlap_var.get())
        seq_center_y = float(self.yolo_seq_center_y_var.get())
        seq_min_h = float(self.yolo_seq_min_h_ratio_var.get())
        seq_max_h = float(self.yolo_seq_max_h_ratio_var.get())
        seq_max_w = float(self.yolo_seq_max_w_ratio_var.get())
        seq_soft_overlap = float(self.yolo_seq_soft_overlap_var.get())
        seq_hard_overlap = float(self.yolo_seq_hard_overlap_var.get())

        if not (0.0 <= conf <= 1.0):
            raise ValueError("Próg confidence YOLO musi być w zakresie 0.00-1.00.")
        if not (0.01 <= iou <= 0.99):
            raise ValueError("Próg NMS IoU musi być w zakresie 0.01-0.99.")
        if not (0.0 <= overlap <= 1.0):
            raise ValueError("Próg nakładania boxów musi być w zakresie 0.00-1.00.")
        if not (0.10 <= seq_center_y <= 1.50):
            raise ValueError("Tolerancja osi Y dla filtra sekwencji musi być w zakresie 0.10-1.50.")
        if not (0.20 <= seq_min_h <= 1.00):
            raise ValueError("Minimalna zgodnosc wysokosci znaku musi byc w zakresie 0.20-1.00.")
        if not (1.00 <= seq_max_h <= 3.50):
            raise ValueError("Maksymalna wysokosc znaku wzgledem mediany musi byc w zakresie 1.00-3.50.")
        if seq_min_h >= seq_max_h:
            raise ValueError("Minimalna zgodnosc wysokosci musi byc mniejsza od maksymalnej wysokosci wzgledem mediany.")
        if not (1.00 <= seq_max_w <= 4.50):
            raise ValueError("Maksymalna szerokosc znaku wzgledem mediany musi byc w zakresie 1.00-4.50.")
        if not (0.0 <= seq_soft_overlap <= 1.0):
            raise ValueError("Miekki prog konfliktu nakladania musi byc w zakresie 0.00-1.00.")
        if not (0.0 <= seq_hard_overlap <= 1.0):
            raise ValueError("Twardy prog konfliktu nakladania musi byc w zakresie 0.00-1.00.")
        if seq_soft_overlap > seq_hard_overlap:
            raise ValueError("Miekki prog konfliktu nie moze byc wiekszy od twardego progu konfliktu.")

        return {
            "conf": conf,
            "iou": iou,
            "overlap": overlap,
            "agnostic_nms": bool(self.yolo_agnostic_nms_var.get()),
            "seq_center_y": seq_center_y,
            "seq_min_h": seq_min_h,
            "seq_max_h": seq_max_h,
            "seq_max_w": seq_max_w,
            "seq_soft_overlap": seq_soft_overlap,
            "seq_hard_overlap": seq_hard_overlap,
        }


    def _characters_to_text(self, chars) -> str:
        if chars is None:
            return ""

        if isinstance(chars, str):
            return chars

        if not isinstance(chars, list):
            return str(chars)

        prepared = []
        for i, rec in enumerate(self._sort_character_records_by_x(chars)):
            symbol, x_key = self._char_record_to_symbol_and_x(rec, fallback_index=i)
            if symbol:
                prepared.append((x_key, symbol))

        prepared.sort(key=lambda item: item[0])
        return "".join(symbol for _, symbol in prepared)


    def _format_plate_listbox_label(self, plate_id: str, data: dict) -> str:
        status = str(data.get("status", "unknown")).strip().lower()
        chars_txt = self._characters_to_text(data.get("characters", []))

        if status == "perfect":
            icon = "🟢"
        elif status == "needs_fix":
            icon = "🔴"
        else:
            icon = "⚪"

        label = f"{icon} {plate_id}"
        if chars_txt:
            label += f" [{chars_txt}]"
        return label
    
    def _get_plate_row_foreground(self, status: str) -> str:
        status = str(status or "unknown").strip().lower()
        palette = getattr(self.app, "palette", {})

        if status == "perfect":
            return palette.get("success", "#27ae60")
        if status == "needs_fix":
            return palette.get("error", "#c0392b")
        return palette.get("muted_dim", "#444444")


    def _apply_plate_listbox_row_style(self, row_index: int, status: str):
        try:
            fg = self._get_plate_row_foreground(status)
            self.plates_listbox.itemconfig(
                row_index,
                foreground=fg,
                selectforeground="#ffffff"
            )
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stylu wiersza listy [{row_index}]: {e}")

    def _update_preview_info_label(self):
        try:
            counts = self._count_preview_statuses()
            self._set_preview_info(f"Wczytano tablic: {counts['total']}", "info")
            self._set_preview_counts_info(
                perfect=counts["perfect"],
                needs_fix=counts["needs_fix"],
                unknown=counts["unknown"],
            )
            self._set_preview_fusion_info(
                self._format_perfect_strategy_counts(counts.get("strategy_counts", {})),
                "muted"
            )
            self._refresh_gold_export_filter_labels()
            self._refresh_gold_export_scope_label()
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć preview_info_lbl: {e}")

    def _update_preview_box_info_label(
        self,
        plate_id=None,
        mode_key=None,
        shown_count=None,
        yolo_raw_count=None,
        yolo_nms_count=None,
        yolo_filtered_count=None,
    ):
        if not plate_id:
            self._set_preview_box_info("Tryb boxow: brak zaznaczonej tablicy", "muted")
            return

        label = self._get_preview_box_mode_label(mode_key)
        details = [f"{plate_id}", label]

        if shown_count is not None:
            details.append(f"pokazano: {int(shown_count)}")

        yolo_parts = []
        if yolo_raw_count is not None:
            yolo_parts.append(f"raw={int(yolo_raw_count)}")
        if yolo_nms_count is not None:
            yolo_parts.append(f"nms={int(yolo_nms_count)}")
        if yolo_filtered_count is not None:
            yolo_parts.append(f"filtr={int(yolo_filtered_count)}")
        if yolo_parts:
            details.append("YOLO: " + ", ".join(yolo_parts))

        tone = "info" if shown_count else "warning"
        self._set_preview_box_info(" | ".join(details), tone)

    def _on_preview_box_mode_change(self, event=None):
        try:
            self._save_local_setting("char_preview_box_mode", self._get_preview_box_mode_key())
        except Exception:
            pass
        self._on_preview_select(None)

    def _rebuild_preview_listbox(self, preserve_selection: bool = True):
        selected_pid = None

        if preserve_selection:
            try:
                sel = self.plates_listbox.curselection()
                if sel:
                    idx = sel[0]
                    if 0 <= idx < len(self._listbox_pid_by_index):
                        selected_pid = self._listbox_pid_by_index[idx]
            except Exception:
                selected_pid = None

        current_order = [pid for pid in self._preview_base_plate_ids if pid in self.preview_metadata]
        appended = [pid for pid in self.preview_metadata.keys() if pid not in current_order]
        self._preview_base_plate_ids = current_order + appended
        self.preview_plate_ids = list(self._preview_base_plate_ids)
        self._listbox_pid_by_index = self._get_sorted_preview_plate_ids(self.preview_plate_ids)

        self._reloading_preview = True
        try:
            self.plates_listbox.delete(0, tk.END)
            for idx, pid in enumerate(self._listbox_pid_by_index):
                data = self.preview_metadata.get(pid, {})
                status = str(data.get("status", "unknown")).strip().lower()
                label = self._format_plate_listbox_label(pid, data)

                self.plates_listbox.insert(tk.END, label)
                self._apply_plate_listbox_row_style(idx, status)

            restore_idx = None
            if selected_pid and selected_pid in self._listbox_pid_by_index:
                restore_idx = self._listbox_pid_by_index.index(selected_pid)
            elif self._listbox_pid_by_index:
                restore_idx = 0

            if restore_idx is not None:
                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(restore_idx)
                self.plates_listbox.activate(restore_idx)
                self.plates_listbox.see(restore_idx)
                try:
                    self.frame.after_idle(
                        lambda: self.plates_listbox.event_generate("<<ListboxSelect>>")
                    )
                except Exception:
                    pass

            self._update_preview_info_label()

            try:
                self.plates_listbox.update_idletasks()
            except Exception:
                pass
            try:
                self.frame.update_idletasks()
            except Exception:
                pass

        finally:
            self._reloading_preview = False

    def _clear_project_bound_session_values(self, clear_ui: bool = False):
        """
        Usuwa z local_session ścieżki, które w trybie kampanii są sterowane przez Wizard.
        """
        project_bound_keys = (
            "char_xml_path",
            "char_images_dir",
            "char_preview_dir",
            "char_yolo_model",
        )

        for key in project_bound_keys:
            self.local_session.pop(key, None)

        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self.local_session, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

        if clear_ui:
            try:
                self.xml_path_var.set("")
            except Exception:
                pass
            try:
                self.images_dir_var.set("")
            except Exception:
                pass
            try:
                self.preview_dir_var.set("")
            except Exception:
                pass
            try:
                self.yolo_model_path_var.set("")
            except Exception:
                pass


    def _apply_preview_metadata_update(self, new_meta: dict, preserve_selection: bool = True):
        self.preview_metadata = new_meta
        current_order = [pid for pid in self._preview_base_plate_ids if pid in self.preview_metadata]
        appended = [pid for pid in self.preview_metadata.keys() if pid not in current_order]
        self._preview_base_plate_ids = current_order + appended
        self.preview_plate_ids = list(self._preview_base_plate_ids)
        self._rebuild_preview_listbox(preserve_selection=preserve_selection)

        try:
            self._on_preview_select(None)
        except Exception:
            pass


    def _refresh_plate_rows_in_place(self):
        """
        Odświeża TYLKO tekst istniejących wierszy listy tablic,
        bez przebudowy całego runu i bez resetowania selekcji.
        """
        try:
            self._reloading_preview = True

            # fallback: jeśli mapowanie indeks->pid nie istnieje, zbuduj je z preview_plate_ids
            if not getattr(self, "_listbox_pid_by_index", None):
                self._listbox_pid_by_index = list(self.preview_plate_ids)

            row_count = self.plates_listbox.size()
            pid_count = len(self._listbox_pid_by_index)
            limit = min(row_count, pid_count)

            for idx in range(limit):
                plate_id = self._listbox_pid_by_index[idx]
                data = self.preview_metadata.get(plate_id, {})
                status = str(data.get("status", "unknown")).strip().lower()
                label = self._format_plate_listbox_label(plate_id, data)

                try:
                    self.plates_listbox.delete(idx)
                    self.plates_listbox.insert(idx, label)
                    self._apply_plate_listbox_row_style(idx, status)
                except Exception:
                    pass

            # jeśli z jakiegoś powodu lista w UI była krótsza, dopełnij brakujące rekordy
            if pid_count > row_count:
                for idx in range(row_count, pid_count):
                    plate_id = self._listbox_pid_by_index[idx]
                    data = self.preview_metadata.get(plate_id, {})
                    status = str(data.get("status", "unknown")).strip().lower()
                    label = self._format_plate_listbox_label(plate_id, data)

                    try:
                        self.plates_listbox.insert(tk.END, label)
                        self._apply_plate_listbox_row_style(idx, status)
                    except Exception:
                        pass

            self._update_preview_info_label()

        finally:
            self._reloading_preview = False

    def _refresh_plates_listbox(self, preserve_selection: bool = True):
        """
        Wrapper kompatybilności.
        Kanoniczny pełny rebuild listy tablic wykonuje _rebuild_preview_listbox().
        """
        self._rebuild_preview_listbox(preserve_selection=preserve_selection)

    def _set_detection_process_log_visibility(self, visible: bool):
        self._detection_log_visible = bool(visible)

        try:
            if self._detection_log_visible:
                self.detection_log_frame.grid()
                self.btn_toggle_detection_log.config(text="Ukryj terminal")
            else:
                self.detection_log_frame.grid_remove()
                self.btn_toggle_detection_log.config(text="Pokaz terminal")
                self.btn_toggle_detection_log.config(text="Pokaż terminal")
        except Exception:
            pass

        try:
            self.btn_toggle_detection_log.config(
                text="Ukryj terminal" if self._detection_log_visible else "Pokaz terminal"
            )
        except Exception:
            pass

    def _toggle_detection_process_log(self):
        self._set_detection_process_log_visibility(
            not getattr(self, "_detection_log_visible", False)
        )



    def clear_campaign_context(self):
        """
        Czyści projektowy kontekst UI po wyjściu z projektu.
        Oprócz pól wejściowych czyści też preview, metadata, log testów
        i local_session powiązany z projektem.
        """
        self._project_reset_token += 1
        self.is_processing = False
        self._reloading_preview = False

        if hasattr(self, "_campaign_chars_dir"):
            self._campaign_chars_dir = None

        if hasattr(self, "_campaign_datasets_dir"):
            self._campaign_datasets_dir = None

        try:
            self._clear_project_bound_session_values(clear_ui=False)
        except Exception:
            pass

        try:
            self.xml_path_var.set("")
        except Exception:
            pass

        try:
            self.images_dir_var.set("")
        except Exception:
            pass

        try:
            self.preview_dir_var.set("")
        except Exception:
            pass

        try:
            self.yolo_model_path_var.set("")
        except Exception:
            pass

        self._reset_preview_cache()
        self.preview_metadata = {}
        self.preview_plate_ids = []
        self._preview_base_plate_ids = []
        self._listbox_pid_by_index = []

        try:
            self.plates_listbox.delete(0, tk.END)
        except Exception:
            pass

        try:
            self.preview_canvas.delete("all")
        except Exception:
            pass

        try:
            self._set_preview_info("Brak wczytanych danych", "muted")
            self._set_preview_counts_info(0, 0, 0)
        except Exception:
            pass

        try:
            self._set_preview_box_info("Tryb boxow: brak wczytanych danych", "muted")
        except Exception:
            pass

        try:
            self.test_log_text.configure(state=tk.NORMAL)
            self.test_log_text.delete("1.0", tk.END)
            self.test_log_text.configure(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self._set_detection_process_log_visibility(False)
        except Exception:
            pass

        try:
            self.fast_test_running = False
            self.fast_test_stop.set()
        except Exception:
            pass

        try:
            self.test_progress.config(value=0)
            self._set_test_progress_counter()
        except Exception:
            pass

        try:
            self._set_test_status("Gotowy do testów", "neutral")
        except Exception:
            pass

        try:
            self.ext_log.configure(state=tk.NORMAL)
            self.ext_log.delete("1.0", tk.END)
            self.ext_log.configure(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.ext_progress.config(value=0)
        except Exception:
            pass

        try:
            self._set_extraction_status("Gotowy", "neutral")
        except Exception:
            pass

        try:
            self.btn_extract.config(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.btn_ext_stop.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.import_cvat_xml_var.set("")
        except Exception:
            pass

        try:
            self._set_console_text(self.export_console, "Oczekuję na akcję...")
        except Exception:
            pass

        try:
            self._set_console_text(self.import_console, "Oczekuję na plik XML...")
        except Exception:
            pass

        try:
            self._set_winner_name("BRAK DANYCH Z TURNIEJU", "neutral")
        except Exception:
            pass

        try:
            self._set_winner_acc("Skuteczność detekcji OCR: 0.0%", "error")
        except Exception:
            pass

        try:
            if hasattr(self, "btn_finish_step3"):
                self.btn_finish_step3.config(
                    text="Zakończ krok 3 i wróć do Wizarda",
                    state=tk.DISABLED
                )
        except Exception:
            pass

        try:
            if hasattr(self, "btn_back_to_wizard_step3"):
                self.btn_back_to_wizard_step3.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self._set_button_emphasis("btn_finish_step3_frame", False)
        except Exception:
            pass

        try:
            self.reset_subtab_flow()
        except Exception as e:
            logger.debug(f"Nie udało się zresetować liniowego flow kroku 3: {e}")

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        console_border = palette.get("console_border", palette.get("border", "#3c3c3c"))

        try:
            self.app.style_panel_surface(self.frame, background=palette.get("panel", "#252526"))
        except Exception:
            pass

        self._apply_preview_sort_bar_style()
        self._apply_preview_mode_radio_style()
        self._apply_yolo_option_check_style()
        self._apply_gold_export_filter_check_style()
        self._apply_gold_export_split_check_style()
        self._apply_plates_legend_style()
        self._apply_preview_info_stats_style()

        for widget_name in ("ext_log", "test_log_text", "export_console", "import_console"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                self.app.style_text_widget(widget, role="console")
            except Exception:
                pass

        try:
            if hasattr(self, "ext_log_scrollbar"):
                self.app.style_web_scrollbar(
                    self.ext_log_scrollbar,
                    track_color=palette.get("console_bg", "#252526"),
                )
        except Exception:
            pass

        try:
            self.app.style_listbox_widget(self.plates_listbox, bordercolor=console_border)
            for idx, pid in enumerate(getattr(self, "_listbox_pid_by_index", [])):
                status = str(self.preview_metadata.get(pid, {}).get("status", "unknown")).strip().lower()
                self._apply_plate_listbox_row_style(idx, status)
        except Exception:
            pass

        try:
            self.app.style_canvas_widget(
                self.preview_canvas,
                background=palette.get("panel", "#1e1e1e"),
                bordercolor=console_border
            )
        except Exception:
            pass

        try:
            if hasattr(self, "extract_left_canvas"):
                self.extract_left_canvas.configure(
                    bg=palette.get("panel", "#252526"),
                    highlightbackground=console_border,
                    highlightcolor=console_border,
                )
        except Exception:
            pass

        try:
            if hasattr(self, "extract_left_scrollbar"):
                thumb = blend_hex_colors(
                    palette.get("accent_hover", "#4f8de3"),
                    palette.get("accent_text", "#ffffff"),
                    0.28,
                )
                thumb_hover = blend_hex_colors(
                    thumb,
                    palette.get("accent_text", "#ffffff"),
                    0.22,
                )
                self.extract_left_scrollbar.configure_style(
                    track_color=palette.get("panel", "#252526"),
                    thumb_color=thumb,
                    thumb_hover_color=thumb_hover,
                )
            if hasattr(self, "extract_left_scroll_host"):
                self.extract_left_scroll_host.configure(style="Panel.TFrame")
            if hasattr(self, "extract_left_content"):
                self.extract_left_content.configure(style="Panel.TFrame")
        except Exception:
            pass

        try:
            self.app.style_canvas_widget(
                self.cvat_export_canvas,
                background=palette.get("panel", "#1e1e1e"),
                bordercolor=console_border
            )
        except Exception:
            pass

        try:
            if hasattr(self, "preview_vertical_split"):
                self.preview_vertical_split.configure(
                    background=console_border,
                    sashwidth=8,
                    sashrelief=tk.RAISED,
                    sashcursor="sb_v_double_arrow",
                )
        except Exception:
            pass

        try:
            if hasattr(self, "test_progress") and isinstance(self.test_progress, SlimProgressBar):
                self.test_progress.configure(
                    bg=palette.get("panel", "#252526"),
                    trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
                    fill_color=palette.get("accent", "#0e639c"),
                    thickness=2,
                )
        except Exception:
            pass

        try:
            if hasattr(self, "detect_right_canvas"):
                self.detect_right_canvas.configure(
                    bg=palette.get("panel", "#252526"),
                    highlightbackground=console_border,
                    highlightcolor=console_border
                )
        except Exception:
            pass

        for frame_name in (
            "btn_to_detect_frame",
            "btn_run_detection_frame",
            "btn_run_detection_pulse_frame",
            "btn_to_dataset_frame",
            "btn_to_dataset_pulse_frame",
            "btn_finish_step3_frame",
            "btn_finish_step3_pulse_frame",
        ):
            frame = getattr(self, frame_name, None)
            if frame is None:
                continue
            try:
                frame.configure(bg=palette.get("panel", "#252526"))
            except Exception:
                pass

        for label_name, style_name in (
            ("cvat_option1_title_lbl", "PanelStatusError.TLabel"),
            ("cvat_option2_title_lbl", "PanelStatusSuccess.TLabel"),
            ("cvat_option1_desc_lbl", "PanelMuted.TLabel"),
            ("cvat_option2_desc_lbl", "PanelMuted.TLabel"),
            ("cvat_import_desc_lbl", "PanelMuted.TLabel"),
        ):
            label = getattr(self, label_name, None)
            if label is None or isinstance(label, tk.Label):
                continue
            try:
                label.configure(style=style_name)
            except Exception:
                pass

        inline_label_defaults = {
            "ext_status": ("neutral", True),
            "source_binding_status_lbl": ("warning", False),
            "test_status_lbl": ("neutral", False),
            "test_progress_count_lbl": ("muted", True),
            "winner_name_lbl": ("neutral", True),
            "winner_acc_lbl": ("muted", False),
            "preview_info_lbl": ("info", False),
            "preview_fusion_info_lbl": ("muted", False),
            "preview_box_mode_info_lbl": ("muted", False),
            "footer_test_status_lbl": ("neutral", True),
            "cvat_option1_title_lbl": ("error", True),
            "cvat_option2_title_lbl": ("success", True),
            "cvat_option1_desc_lbl": ("muted", False),
            "cvat_option2_desc_lbl": ("muted", False),
            "cvat_import_title_lbl": ("default", True),
            "cvat_import_desc_lbl": ("muted", False),
            "gold_export_scope_lbl": ("muted", False),
        }

        for label_name, (default_tone, default_emphasis) in inline_label_defaults.items():
            label = getattr(self, label_name, None)
            if label is None or not isinstance(label, tk.Label):
                continue
            try:
                self._set_inline_status_label_state(
                    label,
                    text=label.cget("text"),
                    tone=getattr(label, "_inline_status_tone", default_tone),
                    emphasis=getattr(label, "_inline_status_emphasis", default_emphasis),
                )
            except Exception:
                pass

    def _sync_detect_right_scrollregion(self, event=None):
        if not hasattr(self, "detect_right_canvas") or self.detect_right_canvas is None:
            return

        try:
            self.detect_right_canvas.configure(scrollregion=self.detect_right_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_extract_left_scrollregion(self, event=None):
        if not hasattr(self, "extract_left_canvas") or self.extract_left_canvas is None:
            return

        try:
            self.extract_left_canvas.configure(scrollregion=self.extract_left_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_extract_left_canvas_width(self, event=None):
        if not hasattr(self, "extract_left_canvas") or self.extract_left_canvas is None:
            return

        try:
            width = max(50, int(self.extract_left_canvas.winfo_width()))
            self.extract_left_canvas.itemconfigure(self.extract_left_content_window, width=width)
        except Exception:
            pass

    def _sync_detect_right_canvas_width(self, event=None):
        if not hasattr(self, "detect_right_canvas") or self.detect_right_canvas is None:
            return

        try:
            width = max(50, int(self.detect_right_canvas.winfo_width()))
            self.detect_right_canvas.itemconfigure(self.detect_right_content_window, width=width)
        except Exception:
            pass

    def _sync_cvat_export_scrollregion(self, event=None):
        if not hasattr(self, "cvat_export_canvas") or self.cvat_export_canvas is None:
            return

        try:
            self.cvat_export_canvas.configure(scrollregion=self.cvat_export_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_cvat_export_canvas_width(self, event=None):
        if not hasattr(self, "cvat_export_canvas") or self.cvat_export_canvas is None:
            return

        try:
            width = max(50, int(self.cvat_export_canvas.winfo_width()))
            self.cvat_export_canvas.itemconfigure(self.cvat_export_content_window, width=width)
        except Exception:
            pass

    def _widget_contains_point(self, widget, x_root: int, y_root: int) -> bool:
        if widget is None:
            return False
        try:
            wx = int(widget.winfo_rootx())
            wy = int(widget.winfo_rooty())
            return wx <= x_root < (wx + int(widget.winfo_width())) and wy <= y_root < (wy + int(widget.winfo_height()))
        except Exception:
            return False

    def _mousewheel_units(self, event) -> int:
        event_num = getattr(event, "num", None)
        if event_num == 4:
            return -1
        if event_num == 5:
            return 1

        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            return 0
        if abs(delta) >= 120:
            units = -int(delta / 120)
        else:
            units = -1 if delta > 0 else 1
        return units if units != 0 else (-1 if delta > 0 else 1)

    def _detect_right_canvas_overflows(self) -> bool:
        canvas = getattr(self, "detect_right_canvas", None)
        if canvas is None:
            return False

        try:
            bbox = canvas.bbox("all")
            if not bbox:
                return False
            content_height = int(bbox[3]) - int(bbox[1])
            viewport_height = int(canvas.winfo_height())
            return content_height > viewport_height + 1
        except Exception:
            return False

    def _on_detect_right_global_mousewheel(self, event):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

        canvas = getattr(self, "detect_right_canvas", None)
        if canvas is None:
            return None

        units = self._mousewheel_units(event)
        if units == 0:
            return None

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
        except Exception:
            return None

        if not self._widget_contains_point(canvas, x_root, y_root):
            return None

        if not self._detect_right_canvas_overflows():
            return None

        try:
            canvas.yview_scroll(units, "units")
        except Exception:
            return "break"
        return "break"

    def _cvat_export_canvas_overflows(self) -> bool:
        canvas = getattr(self, "cvat_export_canvas", None)
        if canvas is None:
            return False

        try:
            bbox = canvas.bbox("all")
            if not bbox:
                return False
            content_height = int(bbox[3]) - int(bbox[1])
            viewport_height = int(canvas.winfo_height())
            return content_height > viewport_height + 1
        except Exception:
            return False

    def _extract_left_canvas_overflows(self) -> bool:
        canvas = getattr(self, "extract_left_canvas", None)
        if canvas is None:
            return False

        try:
            bbox = canvas.bbox("all")
            if not bbox:
                return False
            content_height = int(bbox[3]) - int(bbox[1])
            viewport_height = int(canvas.winfo_height())
            return content_height > viewport_height + 1
        except Exception:
            return False

    def _on_cvat_export_global_mousewheel(self, event):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

        canvas = getattr(self, "cvat_export_canvas", None)
        if canvas is None:
            return None

        units = self._mousewheel_units(event)
        if units == 0:
            return None

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
        except Exception:
            return None

        if not self._widget_contains_point(canvas, x_root, y_root):
            return None

        if not self._cvat_export_canvas_overflows():
            return None

        try:
            canvas.yview_scroll(units, "units")
        except Exception:
            return "break"
        return "break"

    def _restore_scroll_canvas_focus(self, canvas):
        if canvas is None:
            return
        try:
            canvas.focus_set()
        except Exception:
            pass

    def _redirect_child_mousewheel_to_canvas(self, event, canvas, overflow_checker=None):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

        if canvas is None:
            return None

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
        except Exception:
            return None

        if not self._widget_contains_point(canvas, x_root, y_root):
            return None

        can_scroll = True
        if callable(overflow_checker):
            try:
                can_scroll = bool(overflow_checker())
            except Exception:
                can_scroll = True

        units = self._mousewheel_units(event)
        if units != 0 and can_scroll:
            try:
                canvas.yview_scroll(units, "units")
            except Exception:
                return "break"

        self._restore_scroll_canvas_focus(canvas)
        return "break"

    def _bind_scroll_canvas_children(self, root, canvas, overflow_checker=None):
        if root is None or canvas is None:
            return

        release_focus_classes = {
            "TButton",
            "Button",
            "TCheckbutton",
            "Checkbutton",
            "TRadiobutton",
            "Radiobutton",
            "TScale",
            "Scale",
            "TCombobox",
            "Spinbox",
        }

        def _walk(widget):
            try:
                widget.bind(
                    "<MouseWheel>",
                    lambda e, c=canvas, oc=overflow_checker: self._redirect_child_mousewheel_to_canvas(e, c, oc),
                    add="+"
                )
                widget.bind(
                    "<Button-4>",
                    lambda e, c=canvas, oc=overflow_checker: self._redirect_child_mousewheel_to_canvas(e, c, oc),
                    add="+"
                )
                widget.bind(
                    "<Button-5>",
                    lambda e, c=canvas, oc=overflow_checker: self._redirect_child_mousewheel_to_canvas(e, c, oc),
                    add="+"
                )
            except Exception:
                pass

            try:
                class_name = str(widget.winfo_class())
            except Exception:
                class_name = ""

            if class_name in release_focus_classes:
                try:
                    widget.configure(takefocus=0)
                except Exception:
                    pass
                try:
                    widget.bind("<ButtonRelease-1>", lambda _e, c=canvas: self._restore_scroll_canvas_focus(c), add="+")
                except Exception:
                    pass
                if class_name == "TCombobox":
                    try:
                        widget.bind("<<ComboboxSelected>>", lambda _e, c=canvas: self._restore_scroll_canvas_focus(c), add="+")
                    except Exception:
                        pass

            for child in widget.winfo_children():
                _walk(child)

        _walk(root)

    def _panel_style_name(self, tone: str = "neutral", emphasis: bool = False) -> str:
        tone_key = str(tone or "").strip().lower()
        if emphasis:
            return {
                "neutral": "PanelStatusNeutral.TLabel",
                "info": "PanelStatusInfo.TLabel",
                "success": "PanelStatusSuccess.TLabel",
                "warning": "PanelStatusWarning.TLabel",
                "error": "PanelStatusError.TLabel",
                "muted": "PanelStatusNeutral.TLabel",
            }.get(tone_key, "PanelStatusNeutral.TLabel")

        return {
            "neutral": "PanelMuted.TLabel",
            "muted": "PanelMuted.TLabel",
            "info": "PanelInfo.TLabel",
            "success": "PanelSuccess.TLabel",
            "warning": "PanelStatusWarning.TLabel",
            "error": "PanelError.TLabel",
        }.get(tone_key, "PanelMuted.TLabel")

    def _set_themed_label_state(self, widget, text: str | None = None, tone: str = "neutral", emphasis: bool = False):
        if widget is None:
            return

        config_kwargs = {"style": self._panel_style_name(tone=tone, emphasis=emphasis)}
        if text is not None:
            config_kwargs["text"] = text

        widget.config(**config_kwargs)

    def _set_inline_status_label_state(self, widget, text: str | None = None, tone: str = "neutral", emphasis: bool = False) -> bool:
        if widget is None or not isinstance(widget, tk.Label):
            return False

        palette = getattr(self.app, "palette", {})
        bg = palette.get("bg", "#1f1f1f")
        try:
            parent = widget.nametowidget(widget.winfo_parent())
        except Exception:
            parent = None

        for candidate in (parent, widget):
            if candidate is None:
                continue
            try:
                bg_candidate = candidate.cget("bg")
                if bg_candidate:
                    bg = bg_candidate
                    break
            except Exception:
                pass
            try:
                bg_candidate = candidate.cget("background")
                if bg_candidate:
                    bg = bg_candidate
                    break
            except Exception:
                pass
            try:
                style_name = str(candidate.cget("style") or "").strip()
                if style_name:
                    bg_candidate = self.app.style.lookup(style_name, "background")
                    if bg_candidate:
                        bg = bg_candidate
                        break
            except Exception:
                pass
            try:
                style_name = candidate.winfo_class()
                bg_candidate = ttk.Style().lookup(style_name, "background")
                if bg_candidate:
                    bg = bg_candidate
                    break
            except Exception:
                pass

        tone_key = str(tone or "").strip().lower()
        fg = {
            "default": palette.get("fg", "#f3f3f3"),
            "neutral": palette.get("muted", "#9a9a9a"),
            "muted": palette.get("muted", "#9a9a9a"),
            "info": palette.get("info", palette.get("accent", "#4aa3ff")),
            "success": palette.get("success", "#2ecc71"),
            "warning": palette.get("warning", "#f39c12"),
            "error": palette.get("error", "#e74c3c"),
        }.get(tone_key, palette.get("muted", "#9a9a9a"))

        config_kwargs = {
            "bg": bg,
            "fg": fg,
            "font": ("Segoe UI", 10, "bold") if emphasis else ("Segoe UI", 9),
        }
        if text is not None:
            config_kwargs["text"] = text

        widget._inline_status_tone = tone_key
        widget._inline_status_emphasis = bool(emphasis)
        widget.config(**config_kwargs)
        return True

    def _set_extraction_status(self, text: str, tone: str = "neutral"):
        label = getattr(self, "ext_status", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=True)

    def _set_source_binding_status(self, text: str, tone: str = "warning"):
        label = getattr(self, "source_binding_status_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _set_test_status(self, text: str, tone: str = "neutral"):
        label = getattr(self, "test_status_lbl", None)
        fixed_tone = "neutral"
        if not self._set_inline_status_label_state(label, text=text, tone=fixed_tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=fixed_tone, emphasis=False)

    def _set_test_progress_counter(
        self,
        current: int | None = None,
        total: int | None = None,
        perfect_count: int | None = None,
    ):
        label = getattr(self, "test_progress_count_lbl", None)
        if label is None:
            return

        if current is None or total is None or total <= 0:
            text = ""
            tone = "muted"
        else:
            current = max(0, min(int(current), int(total)))
            perfect_value = max(0, min(int(perfect_count or 0), current))
            text = f"{perfect_value}/{current}/{int(total)}"
            tone = "info" if current < int(total) else "success"

        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=True)

    def _update_detection_progress_ui(self, current: int, total: int, perfect_count: int = 0, session_token=None):
        if session_token is not None and session_token != self._project_reset_token:
            return

        pct = ((max(0, int(current)) / max(1, int(total))) * 100.0) if total else 0.0

        try:
            self.test_progress.config(value=pct)
        except Exception:
            pass

        self._set_test_progress_counter(current, total, perfect_count=perfect_count)
        self._set_test_status("Detekcja w toku", "warning")

    def _set_preview_info(self, text: str, tone: str = "info"):
        label = getattr(self, "preview_info_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _set_preview_counts_info(self, perfect: int = 0, needs_fix: int = 0, unknown: int = 0):
        label_map = (
            ("preview_perfect_count_lbl", f"Perfect {int(perfect)}"),
            ("preview_error_count_lbl", f"Błędy {int(needs_fix)}"),
            ("preview_unknown_count_lbl", f"Nieocenione {int(unknown)}"),
        )
        for attr_name, value_text in label_map:
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                widget.configure(text=value_text)
            except Exception:
                pass

    def _set_preview_fusion_info(self, text: str, tone: str = "muted"):
        label = getattr(self, "preview_fusion_info_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _set_preview_box_info(self, text: str, tone: str = "muted"):
        label = getattr(self, "preview_box_mode_info_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _set_gold_export_scope_info(self, text: str, tone: str = "muted"):
        label = getattr(self, "gold_export_scope_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _refresh_gold_export_scope_label(self):
        selected = self._get_selected_gold_export_strategy_buckets()
        if not selected:
            self._set_gold_export_scope_info("Do eksportu gold packa nie wybrano żadnej strategii.", "warning")
            return

        counts = self._count_preview_statuses()
        selected_labels = self._format_selected_gold_export_strategy_labels()
        selected_count = sum(
            int(counts.get("strategy_counts", {}).get(bucket, 0))
            for bucket in selected
        )
        selected_chars = sum(
            int(counts.get("strategy_char_counts", {}).get(bucket, 0))
            for bucket in selected
        )

        self._set_gold_export_scope_info(
            f"Do gold packa: {selected_labels} | perfect: {selected_count} | znaki: {selected_chars} | {self._format_gold_export_split_summary()}",
            "muted"
        )

    def _format_gold_export_split_summary(self) -> str:
        if not bool(getattr(self, "gold_export_split_var", None).get() if hasattr(self, "gold_export_split_var") else False):
            return "split: wyl."

        train_pct, val_pct, test_pct = self._get_gold_export_split_percentages()
        return f"split: {train_pct:.0f}/{val_pct:.0f}/{test_pct:.0f}"

    def _get_gold_export_split_percentages(self):
        train = float(getattr(self, "gold_export_train_pct_var", tk.DoubleVar(value=80.0)).get())
        val = float(getattr(self, "gold_export_val_pct_var", tk.DoubleVar(value=10.0)).get())
        max_train_plus_val = 95.0
        if train + val > max_train_plus_val:
            val = max(5.0, max_train_plus_val - train)
            try:
                self.gold_export_val_pct_var.set(val)
            except Exception:
                pass

        test = max(5.0, 100.0 - train - val)
        return train, val, test

    def _update_gold_export_split_labels(self):
        train_pct, val_pct, test_pct = self._get_gold_export_split_percentages()

        for widget_name, text in (
            ("gold_export_train_pct_lbl", f"{train_pct:.0f}%"),
            ("gold_export_val_pct_lbl", f"{val_pct:.0f}%"),
            ("gold_export_test_pct_lbl", f"Test: {test_pct:.0f}%"),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(text=text)
            except Exception:
                pass

        enabled = bool(getattr(self, "gold_export_split_var", None).get() if hasattr(self, "gold_export_split_var") else False)
        state = tk.NORMAL if enabled else tk.DISABLED
        for widget_name in ("gold_export_train_scale", "gold_export_val_scale"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(state=state)
            except Exception:
                pass

        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        label_fg = palette.get("muted", palette.get("fg", "#f3f3f3"))

        for widget_name in ("gold_export_train_pct_lbl", "gold_export_val_pct_lbl", "gold_export_test_pct_lbl"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(foreground=label_fg)
            except Exception:
                try:
                    widget.configure(fg=label_fg, bg=panel_bg)
                except Exception:
                    pass

        helper = getattr(self, "gold_export_test_hint_lbl", None)
        if helper is not None:
            try:
                helper.configure(foreground=label_fg)
            except Exception:
                try:
                    helper.configure(fg=label_fg, bg=panel_bg)
                except Exception:
                    pass

    def _on_gold_export_split_change(self):
        try:
            self._save_local_setting("char_gold_export_split", bool(self.gold_export_split_var.get()))
            self._save_local_setting("char_gold_export_train_pct", float(self.gold_export_train_pct_var.get()))
            self._save_local_setting("char_gold_export_val_pct", float(self.gold_export_val_pct_var.get()))
        except Exception:
            pass

        self._apply_gold_export_split_check_style()
        self._update_gold_export_split_labels()
        self._refresh_gold_export_scope_label()

    def _refresh_gold_export_filter_labels(self):
        counts = self._count_preview_statuses()
        strategy_counts = counts.get("strategy_counts", {}) if isinstance(counts, dict) else {}
        strategy_char_counts = counts.get("strategy_char_counts", {}) if isinstance(counts, dict) else {}

        for row_info in getattr(self, "gold_export_filter_rows", []):
            if not isinstance(row_info, dict):
                continue

            label_widget = row_info.get("label")
            bucket_key = str(row_info.get("bucket_key", "") or "").strip()
            base_label = str(row_info.get("base_label", "") or "").strip()
            if label_widget is None or not bucket_key or not base_label:
                continue

            plate_count = int(strategy_counts.get(bucket_key, 0) or 0)
            char_count = int(strategy_char_counts.get(bucket_key, 0) or 0)
            label_text = f"{base_label} [{plate_count} tablic | {char_count} znakow]"
            try:
                label_widget.configure(text=label_text)
            except Exception:
                pass

    def _on_gold_export_filter_change(self):
        try:
            self._save_local_setting("char_gold_include_ocr_exact", bool(self.gold_include_ocr_exact_var.get()))
            self._save_local_setting("char_gold_include_yolo_exact", bool(self.gold_include_yolo_exact_var.get()))
            self._save_local_setting("char_gold_include_ocr_yolo_rescue", bool(self.gold_include_ocr_yolo_rescue_var.get()))
            self._save_local_setting("char_gold_include_other_perfect", bool(self.gold_include_other_perfect_var.get()))
        except Exception:
            pass

        self._refresh_gold_export_scope_label()

    def _set_winner_name(self, text: str, tone: str = "neutral"):
        label = getattr(self, "winner_name_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=True)

    def _set_winner_acc(self, text: str, tone: str = "muted"):
        label = getattr(self, "winner_acc_lbl", None)
        if not self._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
            self._set_themed_label_state(label, text=text, tone=tone, emphasis=False)

    def _get_campaign_char_model_path(self) -> str:
        """
        Zwraca ścieżkę do modelu znaków przypiętego do aktywnego projektu.
        """
        try:
            model_path = CAMPAIGN.get_global_model("char")
            if model_path and Path(model_path).exists():
                return str(Path(model_path))
        except Exception:
            pass
        return ""


    def _get_effective_yolo_model_path(self) -> str:
        """
        Zwraca rzeczywistą ścieżkę modelu YOLO używaną do detekcji.
        W trybie kampanii źródłem prawdy jest projekt, nie local session.
        """
        if getattr(self, "_step3_linear_mode", False):
            return self._get_campaign_char_model_path()

        raw = (self.yolo_model_path_var.get() or "").strip()
        if raw and raw != "Brak modelu znaków w projekcie" and Path(raw).exists():
            return raw
        return ""


    def _sync_yolo_model_binding(self):
        """
        Ustawia zawartość pola ścieżki modelu YOLO zgodnie z aktualnym trybem.
        """
        if getattr(self, "_step3_linear_mode", False):
            project_model = self._get_campaign_char_model_path()
            if project_model:
                self.yolo_model_path_var.set(project_model)
            else:
                self.yolo_model_path_var.set("Brak modelu znaków w projekcie")
        else:
            if (self.yolo_model_path_var.get() or "").strip() == "Brak modelu znaków w projekcie":
                self.yolo_model_path_var.set("")

    def _infer_yolo_arch_from_model_path(self, model_path: str):
        """
        Próbuje odczytać wydanie i rozmiar YOLO z nazwy pliku, np.:
        - yolo11s.pt
        - best_yolo26m.pt
        - chars_yolo8n_last.pt
        """
        raw = (model_path or "").strip().lower()
        if not raw:
            return None, None

        name = Path(raw).name.lower()

        import re
        match = re.search(r"yolo(8|11|26)([nsmlx])", name)
        if not match:
            return None, None

        version = match.group(1)
        size = match.group(2)
        return version, size
    def _set_widget_state(self, widget, state: str):
        if widget is None:
            return
        try:
            widget.config(state=state)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu widgetu: {e}")

    def _update_step3_source_path_lock(self):
        """
        W aktywnym, liniowym kroku 3 źródła wejściowe ustawia Wizard,
        więc użytkownik nie powinien ich ręcznie zmieniać.
        W trybie swobodnym pola mają być edytowalne.
        """
        locked = bool(getattr(self, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

        entry_state = "disabled" if locked else "normal"
        button_state = "disabled" if locked else "normal"

        for attr_name in ("xml_path_entry", "images_dir_entry"):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                widget.config(state=entry_state)
            except Exception as e:
                logger.debug(f"Nie udało się ustawić stanu {attr_name}: {e}")

        for attr_name in ("xml_path_browse_btn", "images_dir_browse_btn"):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                widget.config(state=button_state)
            except Exception as e:
                logger.debug(f"Nie udało się ustawić stanu {attr_name}: {e}")

    def _bind_source_path_watchers(self):
        if getattr(self, "_source_binding_watchers_bound", False):
            return

        self._source_binding_watchers_bound = True
        for var in (self.xml_path_var, self.images_dir_var):
            try:
                var.trace_add("write", self._on_source_path_var_changed)
            except Exception as e:
                logger.debug(f"Nie udało się podpiąć watcherów źródeł Z3/PZ1: {e}")

    def _on_source_path_var_changed(self, *_args):
        if getattr(self, "_source_binding_sync_in_progress", False):
            return
        self._schedule_source_binding_refresh()

    def _schedule_source_binding_refresh(self, delay_ms: int = 150):
        if not hasattr(self, "frame") or self.frame is None:
            return

        pending = getattr(self, "_source_binding_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass

        self._source_binding_after_id = self.frame.after(delay_ms, self._refresh_source_binding_status)

    def _normalize_xml_image_relpath(self, raw_name: str) -> str:
        raw = str(raw_name or "").strip().replace("\\", "/")
        while raw.startswith("./"):
            raw = raw[2:]

        parts = [part for part in PurePosixPath(raw).parts if part not in ("", ".")]
        return "/".join(parts)

    def _xml_relpath_to_path(self, rel_path: str) -> Path:
        parts = [part for part in PurePosixPath(rel_path).parts if part not in ("", ".")]
        return Path(*parts) if parts else Path()

    def _read_xml_image_names(self, xml_path: Path) -> list[str]:
        tree = ET.parse(xml_path)
        names = []

        for image_el in tree.getroot().findall(".//image"):
            normalized = self._normalize_xml_image_relpath(image_el.get("name") or "")
            if normalized:
                names.append(normalized)

        return list(dict.fromkeys(names))

    def _evaluate_images_dir_for_xml(self, images_dir: Path, xml_image_names: list[str]) -> dict:
        matched = 0
        missing = []

        for rel_name in xml_image_names:
            candidate = images_dir / self._xml_relpath_to_path(rel_name)
            if candidate.exists() and candidate.is_file():
                matched += 1
            else:
                missing.append(rel_name)

        return {
            "images_dir": images_dir,
            "total": len(xml_image_names),
            "matched": matched,
            "missing_count": len(missing),
            "missing": missing,
        }

    def _summarize_missing_xml_images(self, missing: list[str], limit: int = 3) -> str:
        if not missing:
            return ""

        preview = ", ".join(missing[:limit])
        if len(missing) > limit:
            preview += ", ..."
        return f"Brakuje {len(missing)} plików z XML, np. {preview}."

    def _is_path_within(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    def _get_preferred_source_roots(self) -> list[Path]:
        roots = []

        try:
            campaign_raw = CAMPAIGN.get_dir("raw")
            if campaign_raw:
                roots.append(Path(campaign_raw))
        except Exception:
            pass

        try:
            roots.append(Path(CONFIG.DIR_1_RAW))
        except Exception:
            pass

        unique = []
        seen = set()
        for root in roots:
            try:
                resolved = str(root.resolve())
            except Exception:
                resolved = str(root)
            if resolved in seen:
                continue
            seen.add(resolved)
            if root.exists() and root.is_dir():
                unique.append(root)

        return unique

    def _is_recommended_images_dir(self, images_dir: Path) -> bool:
        for root in self._get_preferred_source_roots():
            if self._is_path_within(images_dir, root):
                return True
        return False

    def _derive_candidate_root_for_match(self, found_file: Path, xml_rel_name: str) -> Path | None:
        parts = [part for part in PurePosixPath(xml_rel_name).parts if part not in ("", ".")]
        if not parts:
            return None

        ascend_levels = len(parts) - 1
        parents = found_file.parents
        if ascend_levels >= len(parents):
            return None

        candidate_root = parents[ascend_levels]
        try:
            candidate_target = (candidate_root / self._xml_relpath_to_path(xml_rel_name)).resolve()
            if candidate_target != found_file.resolve():
                return None
        except Exception:
            return None

        return candidate_root

    def _find_matching_images_dir_for_xml(self, xml_image_names: list[str]) -> dict | None:
        if not xml_image_names:
            return None

        search_roots = self._get_preferred_source_roots()
        if not search_roots:
            return None

        sample_names = xml_image_names[: min(24, len(xml_image_names))]
        sample_by_basename = {}
        for rel_name in sample_names:
            sample_by_basename.setdefault(PurePosixPath(rel_name).name, []).append(rel_name)

        candidate_hits = {}

        for search_root in search_roots:
            try:
                for file_path in search_root.rglob("*"):
                    if not file_path.is_file():
                        continue

                    candidate_rel_names = sample_by_basename.get(file_path.name)
                    if not candidate_rel_names:
                        continue

                    for rel_name in candidate_rel_names:
                        candidate_root = self._derive_candidate_root_for_match(file_path, rel_name)
                        if candidate_root is None:
                            continue

                        try:
                            key = str(candidate_root.resolve())
                        except Exception:
                            key = str(candidate_root)

                        entry = candidate_hits.setdefault(
                            key,
                            {
                                "images_dir": candidate_root,
                                "sample_hits": set(),
                            },
                        )
                        entry["sample_hits"].add(rel_name)
            except Exception as e:
                logger.debug(f"Nie udało się przeskanować {search_root} podczas auto-odnajdywania paczki obrazów: {e}")

        if not candidate_hits:
            return None

        ranked_candidates = sorted(
            candidate_hits.values(),
            key=lambda item: (len(item["sample_hits"]), -len(str(item["images_dir"]))),
            reverse=True,
        )

        best_match = None
        best_score = None

        for candidate in ranked_candidates[:8]:
            stats = self._evaluate_images_dir_for_xml(candidate["images_dir"], xml_image_names)
            stats["sample_hits"] = len(candidate["sample_hits"])
            score = (stats["matched"], -stats["missing_count"], stats["sample_hits"])

            if best_match is None or score > best_score:
                best_match = stats
                best_score = score

        return best_match

    def _refresh_source_binding_status(self, allow_autofind: bool = True) -> dict:
        self._source_binding_after_id = None

        xml_raw = (self.xml_path_var.get() or "").strip()
        images_raw = (self.images_dir_var.get() or "").strip()
        base_note = "Plik annotations.xml i paczka obrazów są nierozerwalnie powiązane."

        result = {
            "ok": False,
            "tone": "warning",
            "message": "",
            "matched": 0,
            "total": 0,
            "missing_count": 0,
        }

        if not xml_raw:
            result["message"] = (
                f"{base_note} Wskaż annotations.xml, a system spróbuje odnaleźć właściwą paczkę w "
                "Workspace/1_raw_images/."
            )
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        xml_path = Path(xml_raw)
        if not xml_path.exists():
            result["tone"] = "error"
            result["message"] = (
                f"Nie znaleziono pliku annotations.xml. {base_note} Wskaż poprawny XML wygenerowany dla tej samej paczki."
            )
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        try:
            xml_image_names = self._read_xml_image_names(xml_path)
        except Exception as e:
            result["tone"] = "error"
            result["message"] = f"Nie mogę odczytać annotations.xml: {e}"
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        if not xml_image_names:
            result["tone"] = "error"
            result["message"] = (
                "Ten plik XML nie zawiera listy obrazów, więc nie da się powiązać go z paczką źródłową."
            )
            self._set_source_binding_status(result["message"], result["tone"])
            return result

        current_images_dir = Path(images_raw) if images_raw else None
        current_stats = None

        if current_images_dir and current_images_dir.exists() and current_images_dir.is_dir():
            current_stats = self._evaluate_images_dir_for_xml(current_images_dir, xml_image_names)
        elif current_images_dir:
            result["tone"] = "error"
            result["message"] = (
                f"Nie znaleziono wskazanej paczki obrazów: {current_images_dir}. {base_note}"
            )

        best_candidate = None
        need_autofind = allow_autofind and (
            current_stats is None or current_stats["matched"] < current_stats["total"]
        )

        if need_autofind:
            best_candidate = self._find_matching_images_dir_for_xml(xml_image_names)
            if best_candidate and best_candidate["matched"] == best_candidate["total"]:
                candidate_dir = Path(best_candidate["images_dir"])
                same_as_current = False
                if current_images_dir:
                    try:
                        same_as_current = candidate_dir.resolve() == current_images_dir.resolve()
                    except Exception:
                        same_as_current = candidate_dir == current_images_dir

                if not same_as_current:
                    self._source_binding_sync_in_progress = True
                    try:
                        self.images_dir_var.set(str(candidate_dir))
                    finally:
                        self._source_binding_sync_in_progress = False
                    try:
                        self._force_save_all()
                    except Exception:
                        pass

                current_images_dir = candidate_dir
                current_stats = best_candidate
                result["auto_found"] = True

        if current_stats and current_stats["matched"] == current_stats["total"]:
            recommended = self._is_recommended_images_dir(Path(current_stats["images_dir"]))
            result.update(
                {
                    "ok": True,
                    "tone": "success" if recommended else "warning",
                    "matched": current_stats["matched"],
                    "total": current_stats["total"],
                    "missing_count": 0,
                }
            )

            if result.get("auto_found"):
                result["message"] = (
                    f"Powiązanie potwierdzone. Auto-odnaleziono paczkę obrazów: "
                    f"{current_stats['matched']}/{current_stats['total']} plików z XML w "
                    f"{current_stats['images_dir']}."
                )
            elif recommended:
                result["message"] = (
                    f"Powiązanie potwierdzone: {current_stats['matched']}/{current_stats['total']} plików z XML "
                    f"znaleziono w tej paczce obrazów."
                )
            else:
                result["message"] = (
                    f"Powiązanie XML-paczka jest poprawne ({current_stats['matched']}/{current_stats['total']}), "
                    f"ale źródła są poza Workspace/1_raw_images/. To działa w trybie swobodnym, lecz nie jest zalecane."
                )

            self._set_source_binding_status(result["message"], result["tone"])
            return result

        if current_stats:
            missing_hint = self._summarize_missing_xml_images(current_stats["missing"])
            result.update(
                {
                    "matched": current_stats["matched"],
                    "total": current_stats["total"],
                    "missing_count": current_stats["missing_count"],
                    "tone": "error",
                }
            )
            result["message"] = (
                f"Wybrana paczka obrazów nie pasuje do tego XML: znaleziono "
                f"{current_stats['matched']}/{current_stats['total']} wymaganych plików. {missing_hint}"
            ).strip()

            if best_candidate and best_candidate["matched"] > current_stats["matched"]:
                result["message"] += (
                    f" Najlepszy kandydat w Workspace/1_raw_images/ daje "
                    f"{best_candidate['matched']}/{best_candidate['total']} dopasowań."
                )

            self._set_source_binding_status(result["message"], result["tone"])
            return result

        if best_candidate and best_candidate["matched"] > 0:
            result.update(
                {
                    "matched": best_candidate["matched"],
                    "total": best_candidate["total"],
                    "missing_count": best_candidate["missing_count"],
                    "tone": "warning",
                    "message": (
                        f"Nie udało się jednoznacznie potwierdzić paczki obrazów. Najlepszy kandydat w "
                        f"Workspace/1_raw_images/ zawiera {best_candidate['matched']}/{best_candidate['total']} plików z XML."
                    ),
                }
            )
        elif not images_raw:
            result["message"] = (
                f"{base_note} Wskaż paczkę obrazów, na których wykonano anotacje. "
                "Jeśli leży w Workspace/1_raw_images/, system odnajdzie ją automatycznie."
            )

        self._set_source_binding_status(result["message"], result["tone"])
        return result

    def _count_preview_statuses(self):
        return self._count_statuses_in_metadata_mapping(self.preview_metadata)


    def _get_step3_summary_dir(self) -> Path:
        """
        Katalog, w którym zapisujemy podsumowanie kroku 3.
        Priorytet:
        1. aktywny run preview
        2. projektowy chars dir
        3. fallback do DIR_3_CHARS
        """
        preview_dir = Path(self.preview_dir_var.get().strip()) if self.preview_dir_var.get().strip() else None
        if preview_dir and preview_dir.exists():
            return preview_dir

        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if campaign_chars_dir:
            p = Path(campaign_chars_dir)
            p.mkdir(parents=True, exist_ok=True)
            return p

        fallback = Path(CONFIG.DIR_3_CHARS).absolute()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    
    def _is_valid_step3_training_dataset_dir(self, dataset_dir: Path | None) -> bool:
        """
        Sprawdza, czy katalog wygląda jak realny dataset treningowy znaków
        gotowy do użycia w etapie 4.
        """
        if dataset_dir is None:
            return False

        try:
            if not dataset_dir.exists() or not dataset_dir.is_dir():
                return False

            data_yaml = dataset_dir / "data.yaml"
            images_dir = dataset_dir / "images"
            labels_dir = dataset_dir / "labels"

            if not data_yaml.exists():
                return False

            if not images_dir.exists() or not images_dir.is_dir():
                return False

            if not labels_dir.exists() or not labels_dir.is_dir():
                return False

            return True
        except Exception:
            return False

    def _get_preferred_step3_training_dataset_dir(self) -> Path | None:
        """
        Zwraca najlepszy dostępny dataset znaków dla finału kroku 3.

        Priorytet:
        1. char_merged_pool
        2. najnowszy poprawny dataset z katalogu projektowych datasetów
        """
        merged_dir = self._get_char_merged_pool_dir()
        if self._is_valid_step3_training_dataset_dir(merged_dir):
            return merged_dir

        campaign_datasets_dir = getattr(self, "_campaign_datasets_dir", None)
        if not campaign_datasets_dir:
            return None

        ds_root = Path(campaign_datasets_dir)
        if not ds_root.exists() or not ds_root.is_dir():
            return None

        try:
            candidates = [
                p for p in ds_root.iterdir()
                if p.is_dir() and self._is_valid_step3_training_dataset_dir(p)
            ]
            if not candidates:
                return None

            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        except Exception:
            return None


    def _build_step3_export_summary(
        self,
        gold_dataset_path: str | None = None,
        review_pack_path: str | None = None,
        retry_pack_path: str | None = None,
        note: str = ""
    ):
        counts = self._count_preview_statuses()

        gold_exists = bool(gold_dataset_path and Path(gold_dataset_path).exists())
        review_exists = bool(review_pack_path and Path(review_pack_path).exists())
        retry_exists = bool(retry_pack_path and Path(retry_pack_path).exists())

        return {
            "gold_dataset_created": gold_exists,
            "gold_dataset_path": str(gold_dataset_path or ""),
            "review_pack_created": review_exists,
            "review_pack_path": str(review_pack_path or ""),
            "retry_pack_created": retry_exists,
            "retry_pack_path": str(retry_pack_path or ""),
            "perfect_count": counts["perfect"],
            "needs_fix_count": counts["needs_fix"],
            "unknown_count": counts["unknown"],
            "total_count": counts["total"],
            "perfect_strategy_counts": counts.get("strategy_counts", self._empty_perfect_strategy_counts()),
            "selected_gold_export_strategies": sorted(self._get_selected_gold_export_strategy_buckets()),
            "note": note,
        }


    def _write_step3_export_summary(self, summary: dict) -> Path:
        summary_dir = self._get_step3_summary_dir()
        summary_path = summary_dir / "export_summary.json"
        self._atomic_write_json(summary_path, summary)
        return summary_path


    def _return_step3_result_to_wizard(self, summary: dict):
        """
        Jeden kontrakt zwrotny do wizarda:
        - jeśli istnieje gold dataset -> approve + krok 4
        - jeśli nie -> needs_rework
        """
        gold_ok = bool(summary.get("gold_dataset_created"))

        if gold_ok:
            CAMPAIGN.approve_step3()
            CAMPAIGN.set_current_step(4)
            status_msg = (
                "Krok 3 zakończony sukcesem. "
                "Powstał dataset treningowy i odblokowano etap 4."
            )
            status_kind = "success"
        else:
            CAMPAIGN.set_step3_needs_rework()
            status_msg = (
                "Krok 3 nie utworzył datasetu treningowego. "
                "Wracasz do wizarda w trybie poprawy."
            )
            status_kind = "warning"

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._rebuild_roadmap_ui()
                campaign_tab._refresh_dashboard()
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć Wizarda po kroku 3: {e}")

        try:
            self.app.select_tab("campaign")
            self.app.update_campaign_tab_access()
        except Exception as e:
            logger.debug(f"Nie udało się wrócić do Wizarda po kroku 3: {e}")

        try:
            self.app.update_status(status_msg, status_kind)
        except Exception:
            pass


    def _finalize_step3_from_existing_outputs(self):
        """
        Miękki finał kroku 3:
        - nie tworzy datasetu sam,
        - tylko ocenia to, co już istnieje po eksporcie z zakładki 3
        - zapisuje export_summary.json
        - zwraca wynik do wizarda
        """
        counts = self._count_preview_statuses()

        gold_dataset_path = ""
        review_pack_path = ""

        preferred_dataset_dir = self._get_preferred_step3_training_dataset_dir()
        if preferred_dataset_dir is not None:
            gold_dataset_path = str(preferred_dataset_dir)

        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if campaign_chars_dir:
            chars_root = Path(campaign_chars_dir)
            review_dir = chars_root / "review"
            if review_dir.exists():
                review_pack_path = str(review_dir)

        summary = self._build_step3_export_summary(
            gold_dataset_path=gold_dataset_path,
            review_pack_path=review_pack_path,
            retry_pack_path="",
            note="Finalizacja kroku 3 na podstawie najlepszego dostępnego datasetu znaków projektu (merged preferowany, fallback do istniejącego datasetu)."
        )

        self._write_step3_export_summary(summary)
        self._return_step3_result_to_wizard(summary)

    def _get_char_manual_pool_dir(self) -> Path | None:
        """
        Katalog na ręcznie poprawione paczki znaków importowane z CVAT.
        """
        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if not campaign_chars_dir:
            return None

        root = Path(campaign_chars_dir)
        root.mkdir(parents=True, exist_ok=True)

        pool_dir = root / "manual_char_pool"
        pool_dir.mkdir(parents=True, exist_ok=True)
        return pool_dir


    def _get_char_gold_pool_dir(self) -> Path | None:
        """
        Katalog na złotą paczkę znaków projektu.
        """
        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if not campaign_chars_dir:
            return None

        root = Path(campaign_chars_dir)
        root.mkdir(parents=True, exist_ok=True)

        pool_dir = root / "gold_char_pool"
        pool_dir.mkdir(parents=True, exist_ok=True)
        return pool_dir


    def _get_char_merged_pool_dir(self) -> Path | None:
        """
        Katalog na scaloną pulę znaków: gold + manual.
        """
        campaign_datasets_dir = getattr(self, "_campaign_datasets_dir", None)
        if not campaign_datasets_dir:
            return None

        root = Path(campaign_datasets_dir)
        root.mkdir(parents=True, exist_ok=True)

        pool_dir = root / "char_merged_pool"
        pool_dir.mkdir(parents=True, exist_ok=True)
        return pool_dir
    def _is_valid_step3_training_dataset_dir(self, dataset_dir: Path | None) -> bool:
        """
        Sprawdza, czy katalog wygląda jak realny dataset treningowy znaków
        gotowy do użycia w etapie 4.
        """
        if dataset_dir is None:
            return False

        try:
            if not dataset_dir.exists() or not dataset_dir.is_dir():
                return False

            data_yaml = dataset_dir / "data.yaml"
            images_dir = dataset_dir / "images"
            labels_dir = dataset_dir / "labels"

            if not data_yaml.exists():
                return False

            if not images_dir.exists() or not images_dir.is_dir():
                return False

            if not labels_dir.exists() or not labels_dir.is_dir():
                return False

            return True
        except Exception:
            return False

    def _get_preferred_step3_training_dataset_dir(self) -> Path | None:
        """
        Zwraca najlepszy dostępny dataset znaków dla finiszu kroku 3.

        Priorytet:
        1. char_merged_pool
        2. najnowszy poprawny dataset z katalogu projektowych datasetów
        """
        merged_dir = self._get_char_merged_pool_dir()
        if self._is_valid_step3_training_dataset_dir(merged_dir):
            return merged_dir

        campaign_datasets_dir = getattr(self, "_campaign_datasets_dir", None)
        if not campaign_datasets_dir:
            return None

        ds_root = Path(campaign_datasets_dir)
        if not ds_root.exists() or not ds_root.is_dir():
            return None

        try:
            candidates = [
                p for p in ds_root.iterdir()
                if p.is_dir() and self._is_valid_step3_training_dataset_dir(p)
            ]
            if not candidates:
                return None

            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        except Exception:
            return None
        
    def _get_project_review_dir(self) -> Path | None:
        """
        Projektowy katalog review dla eksportów CVAT z kroku 3.
        """
        campaign_chars_dir = getattr(self, "_campaign_chars_dir", None)
        if not campaign_chars_dir:
            return None

        root = Path(campaign_chars_dir)
        root.mkdir(parents=True, exist_ok=True)

        review_dir = root / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        return review_dir
    def _store_current_preview_in_manual_char_pool(self, metadata: dict):
        """
        Zapisuje aktualnie poprawioną paczkę preview do manual_char_pool,
        aby mogła później zasilić trening modelu znaków.
        """
        manual_pool_dir = self._get_char_manual_pool_dir()
        if manual_pool_dir is None:
            raise RuntimeError("Brak katalogu manual_char_pool dla aktywnego projektu.")

        preview_dir = Path((self.preview_dir_var.get() or "").strip())
        if not preview_dir.exists() or not preview_dir.is_dir():
            raise RuntimeError("Brak poprawnego katalogu preview do zapisania w manual_char_pool.")

        preview_name = preview_dir.name if preview_dir.name else "manual_import"
        target_dir = manual_pool_dir / preview_name
        target_images_dir = target_dir / "images"

        target_dir.mkdir(parents=True, exist_ok=True)
        target_images_dir.mkdir(parents=True, exist_ok=True)

        # zapis metadata
        target_meta = target_dir / "metadata.json"
        self._atomic_write_json(target_meta, metadata)

        # kopiowanie obrazów źródłowych preview
        source_images_dir = preview_dir / "images"
        if source_images_dir.exists() and source_images_dir.is_dir():
            for img_file in source_images_dir.iterdir():
                if not img_file.is_file():
                    continue
                dst = target_images_dir / img_file.name
                shutil.copy2(img_file, dst)

        return target_dir
    def _has_char_manual_imports(self) -> bool:
        pool_dir = self._get_char_manual_pool_dir()
        if pool_dir is None or not pool_dir.exists():
            return False

        try:
            return any(p.exists() for p in pool_dir.iterdir())
        except Exception:
            return False


    def _has_char_gold_exports(self) -> bool:
        pool_dir = self._get_char_gold_pool_dir()
        if pool_dir is None or not pool_dir.exists():
            return False

        try:
            return any(p.exists() for p in pool_dir.iterdir())
        except Exception:
            return False
    def _has_any_step3_export_outputs(self) -> bool:
        """
        Krok 3 można zakończyć dopiero wtedy, gdy istnieje realny dataset
        treningowy znaków dla etapu 4.

        Sam review export do CVAT nie wystarcza.
        """
        try:
            return self._get_preferred_step3_training_dataset_dir() is not None
        except Exception:
            return False
    
    def _return_to_wizard_for_step3_rework(self):
        try:
            if CAMPAIGN.get_active_project_name():
                CAMPAIGN.set_current_step(3)
                CAMPAIGN.set_step3_needs_rework()
        except Exception as e:
            logger.debug(f"Nie udało się ustawić trybu poprawy kroku 3: {e}")

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._rebuild_roadmap_ui()
                campaign_tab._refresh_dashboard()
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć wizarda dla rework kroku 3: {e}")

        try:
            self.app.select_tab("campaign")
            self.app.update_campaign_tab_access()
            self.app.update_status(
                "Wracasz do wizarda w trybie poprawy kroku 3.",
                "warning"
            )
        except Exception as e:
            logger.debug(f"Nie udało się wrócić do wizarda dla rework kroku 3: {e}")

    def _resolve_guidance_button(self, attr_name: str):
        if not attr_name:
            return None

        candidates = [attr_name]
        if attr_name.endswith("_pulse_frame"):
            candidates.append(attr_name[:-12])
        if attr_name.endswith("_frame"):
            candidates.append(attr_name[:-6])

        for candidate in candidates:
            widget = getattr(self, candidate, None)
            if isinstance(widget, ttk.Button):
                return widget

        return None

    def _pulse_button_emphasis(self, frame_attr: str, pulses: int = 8, interval_ms: int = 260, color: str = "#f39c12"):
        btn = self._resolve_guidance_button(frame_attr)
        if btn is None:
            return

        try:
            self.app.pulse_button(btn, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True)
        except Exception as e:
            logger.debug(f"Nie udało się pulsować przycisku dla {frame_attr}: {e}")

    def _update_step3_finish_button_state(self):
        btn = getattr(self, "btn_finish_step3", None)
        back_btn = getattr(self, "btn_back_to_wizard_step3", None)

        if btn is None:
            return

        enabled = self._has_any_step3_export_outputs()

        rework_return_mode = False
        try:
            rework_return_mode = bool(
                getattr(self, "_step3_linear_mode", False)
                and CAMPAIGN.get_active_project_name()
                and CAMPAIGN.get_step3_status() == "needs_rework"
                and not enabled
            )
        except Exception:
            rework_return_mode = False

        try:
            if rework_return_mode:
                btn.config(
                    text="Powrót do wizarda",
                    command=self._return_to_wizard_for_step3_rework,
                    state="normal"
                )
                self._set_button_emphasis("btn_finish_step3_frame", True)
                self._pulse_button_emphasis("btn_finish_step3_frame")

                if back_btn is not None:
                    back_btn.config(state="normal")
                return

            btn.config(
                text="Zakończ krok 3 i wróć do Wizarda",
                command=self._finalize_step3_from_existing_outputs,
                state=("normal" if enabled else "disabled")
            )

            if enabled:
                self._set_button_emphasis("btn_finish_step3_frame", True)
                self._pulse_button_emphasis("btn_finish_step3_frame")
            else:
                self._set_button_emphasis("btn_finish_step3_frame", False)

            if back_btn is not None:
                back_btn.config(state="disabled")

        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu btn_finish_step3: {e}")

    def _update_preview_path_lock(self):
        """
        W aktywnym, liniowym kroku 3 użytkownik nie powinien ręcznie
        zmieniać paczki preview ani ścieżki do niej.
        W trybie swobodnym pole ma być readonly, a przycisk aktywny.
        """
        locked = bool(getattr(self, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

        try:
            if hasattr(self, "preview_dir_entry"):
                self.preview_dir_entry.config(state="disabled" if locked else "readonly")
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu preview_dir_entry: {e}")

        try:
            if hasattr(self, "preview_dir_browse_btn"):
                self.preview_dir_browse_btn.config(state="disabled" if locked else "normal")
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu preview_dir_browse_btn: {e}")

    def _set_button_state(self, attr_name: str, enabled: bool):
        btn = getattr(self, attr_name, None)
        if btn is None:
            return

        try:
            btn.config(state="normal" if enabled else "disabled")
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu przycisku '{attr_name}': {e}")       

    def _set_subtab_state(self, tab_widget, state: str):
        try:
            self.main_nb.tab(str(tab_widget), state=state)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić stanu podzakładki: {e}")

    def _get_subtab_state(self, tab_widget) -> str:
        try:
            return str(self.main_nb.tab(str(tab_widget), "state"))
        except Exception:
            return "normal"

    def _select_subtab(self, tab_widget):
        try:
            self.main_nb.select(str(tab_widget))
        except Exception as e:
            logger.debug(f"Nie udało się przełączyć podzakładki: {e}")

    # --- STEP3 NOTEBOOK PERSIST ---
    def _on_main_nb_tab_changed(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.main_nb:
            return

        if not getattr(self, "_step3_linear_mode", False):
            return

        if not CAMPAIGN.get_active_project_name():
            return

        self._persist_step3_progress()

    def _sync_step3_nav_buttons(self):
        detect_enabled = self._get_subtab_state(self.tab_detect) == "normal"
        dataset_enabled = self._get_subtab_state(self.tab_dataset) == "normal"

        if hasattr(self, "btn_to_detect"):
            self.btn_to_detect.config(state=tk.NORMAL if detect_enabled else tk.DISABLED)

        if hasattr(self, "btn_to_dataset"):
            self.btn_to_dataset.config(state=tk.NORMAL if dataset_enabled else tk.DISABLED)

    def enter_campaign_step3_mode(self):
        """
        Start kroku 3 od początku.
        """
        CAMPAIGN.reset_step3_progress()
        self.restore_campaign_step3_mode()
        self._set_button_emphasis("btn_to_detect_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)
        try:
            self._sync_yolo_model_binding()
        except Exception:
            pass

    def reset_subtab_flow(self):
        """
        Stan neutralny poza liniowym workflow kampanii.
        W trybie swobodnym wszystkie podzakładki i przyciski nawigacyjne są dostępne.
        """
        self._step3_linear_mode = False

        # podzakładki
        self._set_subtab_state(self.tab_extract, "normal")
        self._set_subtab_state(self.tab_detect, "normal")
        self._set_subtab_state(self.tab_dataset, "normal")

        # nawigacja między podzakładkami ma działać w free mode
        self._set_button_state("btn_to_detect", True)
        self._set_button_state("btn_to_dataset", True)

        # akcje operacyjne też mają być aktywne
        self._set_button_state("btn_run_detection", True)
        self._set_button_state("btn_rank_presets", True)
        self._set_button_state("btn_ocr_lab", True)

        # zdejmij podświetlenia akcji
        self._set_button_emphasis("btn_to_detect_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)
        self._set_button_emphasis("btn_run_detection_frame", False)

        # odblokuj pola ścieżek
        try:
            self._update_preview_path_lock()
        except Exception:
            pass

        try:
            self._sync_step3_access_from_preview_state()
        except Exception:
            pass

        try:
            self._update_step3_source_path_lock()
        except Exception:
            pass

        try:
            self._update_yolo_visibility()
        except Exception:
            pass

        # wyczyść stan ostatniego testu
        try:
            self.test_progress.config(value=0)
            self._set_test_progress_counter()
        except Exception:
            pass

        try:
            self._set_test_status("Gotowy do testów", "neutral")
        except Exception:
            pass

        # jeśli konsola była zablokowana po teście, przywróć normalny stan logowania
        try:
            self.fast_test_running = False
            self.fast_test_stop.clear()
        except Exception:
            pass

    def unlock_detection_subtab(self):
        self._set_button_state("btn_to_detect", True)
        self._set_button_emphasis("btn_to_detect_frame", True)
        self._pulse_button_emphasis("btn_to_detect_frame")

        if self._step3_linear_mode:
            CAMPAIGN.set_step3_stage1_done(True)
            self._persist_step3_progress()
        

    def unlock_dataset_subtab(self):
        self._set_button_state("btn_to_dataset", True)
        self._set_button_emphasis("btn_run_detection_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", True)
        self._pulse_button_emphasis("btn_to_dataset_frame")

        if self._step3_linear_mode:
            CAMPAIGN.set_step3_stage2_done(True)
            self._persist_step3_progress()

    def go_to_substep_2(self):
        if self._step3_linear_mode:
            btn = getattr(self, "btn_to_detect", None)
            if btn is not None and str(btn.cget("state")) != "normal":
                return

            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "normal")
            self._set_subtab_state(self.tab_dataset, "disabled")

            CAMPAIGN.set_step3_substep(2)

        self._select_subtab(self.tab_detect)
        self._persist_step3_progress()
        self._pulse_button_emphasis("btn_run_detection_frame")

    def go_to_substep_3(self):
        if self._step3_linear_mode:
            btn = getattr(self, "btn_to_dataset", None)
            if btn is not None and str(btn.cget("state")) != "normal":
                return

            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "normal")

            CAMPAIGN.set_step3_substep(3)

        self._select_subtab(self.tab_dataset)
        self._persist_step3_progress()
        self._set_button_emphasis("btn_run_detection_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)

    def back_to_substep_1(self):
        """
        Cofnięcie do 1 blokuje 2 i 3 tylko w trybie kampanii.
        """
        if self._step3_linear_mode:
            self._set_subtab_state(self.tab_extract, "normal")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._set_button_state("btn_to_detect", False)
            self._set_button_state("btn_to_dataset", False)

            self._set_button_emphasis("btn_to_detect_frame", False)
            self._set_button_emphasis("btn_to_dataset_frame", False)

            CAMPAIGN.set_step3_substep(1)

        self._select_subtab(self.tab_extract)
        self._persist_step3_progress()


    def back_to_substep_2(self):
        """
        Cofnięcie do 2 blokuje 3 tylko w trybie kampanii.
        """
        if self._step3_linear_mode:
            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "normal")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._set_button_state("btn_to_dataset", False)

            self._set_button_emphasis("btn_to_dataset_frame", False)

            CAMPAIGN.set_step3_substep(2)

        self._select_subtab(self.tab_detect)
        self._persist_step3_progress()
        self._pulse_button_emphasis("btn_run_detection_frame")

    def _persist_step3_progress(self):
        if not getattr(self, "_step3_linear_mode", False):
            return

        current_substep = 1
        try:
            selected = str(self.main_nb.select())
            if selected == str(self.tab_extract):
                current_substep = 1
            elif selected == str(self.tab_detect):
                current_substep = 2
            elif selected == str(self.tab_dataset):
                current_substep = 3
        except Exception:
            current_substep = 1

        CAMPAIGN.set_step3_substep(current_substep)

        stage1_done = False
        stage2_done = False

        try:
            btn = getattr(self, "btn_to_detect", None)
            if btn is not None:
                stage1_done = str(btn.cget("state")) == "normal"
        except Exception:
            pass

        try:
            btn = getattr(self, "btn_to_dataset", None)
            if btn is not None:
                stage2_done = str(btn.cget("state")) == "normal"
        except Exception:
            pass

        CAMPAIGN.set_step3_stage1_done(stage1_done)
        CAMPAIGN.set_step3_stage2_done(stage2_done)


    def restore_campaign_step3_mode(self):
        """
        Przywraca zapisany postęp kroku 3 aktywnego projektu.
        """
        self._step3_linear_mode = True

        saved_substep = CAMPAIGN.get_step3_substep()
        stage1_done = CAMPAIGN.is_step3_stage1_done()
        stage2_done = CAMPAIGN.is_step3_stage2_done()

        if saved_substep > 1 and not (self.preview_dir_var.get() or "").strip():
            try:
                self._restore_preview_context_from_project()
            except Exception:
                pass

        try:
            if self.can_restore_step3_substep(2):
                stage1_done = True
        except Exception:
            pass

        try:
            if self._preview_dir_has_completed_detection_output():
                stage2_done = True
        except Exception:
            pass

        try:
            if stage1_done:
                CAMPAIGN.set_step3_stage1_done(True)
            if stage2_done:
                CAMPAIGN.set_step3_stage2_done(True)
        except Exception:
            pass
        # jeśli zapisany stan nie ma pokrycia w realnych artefaktach, wracamy do substepu 1
        if not self.can_restore_step3_substep(saved_substep):
            saved_substep = 1
            stage1_done = False
            stage2_done = False

            try:
                CAMPAIGN.reset_step3_progress()
            except Exception:
                pass

        self._set_button_state("btn_to_detect", stage1_done)
        self._set_button_state("btn_to_dataset", stage2_done)

        if saved_substep <= 1:
            self._set_subtab_state(self.tab_extract, "normal")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._select_subtab(self.tab_extract)

        elif saved_substep == 2:
            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "normal")
            self._set_subtab_state(self.tab_dataset, "disabled")
            self._select_subtab(self.tab_detect)

        else:
            self._set_subtab_state(self.tab_extract, "disabled")
            self._set_subtab_state(self.tab_detect, "disabled")
            self._set_subtab_state(self.tab_dataset, "normal")
            self._select_subtab(self.tab_dataset)

        self._set_button_emphasis("btn_run_detection_frame", False)
        self._set_button_emphasis("btn_to_dataset_frame", False)

        if saved_substep == 2 and not stage2_done:
            self._set_button_emphasis("btn_run_detection_frame", True)
            self._pulse_button_emphasis("btn_run_detection_frame")
        elif saved_substep == 2 and stage2_done:
            self._set_button_emphasis("btn_to_dataset_frame", True)
            self._pulse_button_emphasis("btn_to_dataset_frame")
        elif saved_substep == 3:
            self._update_step3_finish_button_state()

        try:
            self._update_preview_path_lock()
        except Exception:
            pass

        try:
            self._update_step3_source_path_lock()
        except Exception:
            pass

        try:
            self._sync_yolo_model_binding()
        except Exception:
            pass

        try:
            self._update_yolo_visibility()
        except Exception:
            pass

        try:
            self._update_step3_finish_button_state()
        except Exception:
            pass      

    def can_restore_step3_substep(self, substep: int) -> bool:
        """
        Sprawdza, czy dla zapisanego substepu istnieją realne artefakty
        pozwalające wejść do tego miejsca workflow.
        """
        substep = int(substep)

        # substep 1 zawsze można otworzyć, jeśli mamy źródła z wizarda
        if substep <= 1:
            xml_ok = bool((self.xml_path_var.get() or "").strip())
            img_ok = bool((self.images_dir_var.get() or "").strip())
            return xml_ok and img_ok

        # substep 2 i 3 wymagają paczki preview z metadata i katalogiem images
        preview_dir_raw = (self.preview_dir_var.get() or "").strip()
        if not preview_dir_raw:
            return False

        preview_dir = Path(preview_dir_raw)
        if not preview_dir.exists() or not preview_dir.is_dir():
            return False

        meta_file = preview_dir / "metadata.json"
        images_dir = preview_dir / "images"

        if not meta_file.exists():
            return False

        if not images_dir.exists() or not images_dir.is_dir():
            return False

        # substep 3 dodatkowo wymaga, żeby etap 2 był realnie zakończony
        if substep >= 3:
            try:
                if bool(CAMPAIGN.is_step3_stage2_done()):
                    return True
            except Exception:
                pass
            return self._preview_dir_has_completed_detection_output(preview_dir)

        return True

    def _atomic_write_json(self, path: Path, data: dict):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def _load_local_session(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_local_setting(self, key, value):
        self.local_session[key] = value
        try:
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(self.local_session, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def _prune_legacy_yolo_arch_session_keys(self):
        legacy_keys = ("char_yolo_size", "char_yolo_version")
        removed = False
        for key in legacy_keys:
            if key in self.local_session:
                self.local_session.pop(key, None)
                removed = True

        if not removed:
            return

        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self.local_session, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def _force_save_all(self):
        try:
            always_saved = [
                ("char_yolo_device", self.yolo_device_var),
                ("char_yolo_conf", self.yolo_conf_var),
                ("char_yolo_iou", self.yolo_iou_var),
                ("char_yolo_overlap", self.yolo_overlap_var),
                ("char_yolo_agnostic_nms", self.yolo_agnostic_nms_var),
                ("char_yolo_seq_center_y", self.yolo_seq_center_y_var),
                ("char_yolo_seq_min_h_ratio", self.yolo_seq_min_h_ratio_var),
                ("char_yolo_seq_max_h_ratio", self.yolo_seq_max_h_ratio_var),
                ("char_yolo_seq_max_w_ratio", self.yolo_seq_max_w_ratio_var),
                ("char_yolo_seq_soft_overlap", self.yolo_seq_soft_overlap_var),
                ("char_yolo_seq_hard_overlap", self.yolo_seq_hard_overlap_var),
                ("char_hybrid_rescue_max_chars", self.hybrid_rescue_max_chars_var),
                ("char_hybrid_yolo_box_backend", self.hybrid_yolo_box_backend_var),
                ("char_ocr_conf", self.ocr_conf_var),
                ("char_smart_export", self.smart_export_var),
                ("char_gold_include_ocr_exact", self.gold_include_ocr_exact_var),
                ("char_gold_include_yolo_exact", self.gold_include_yolo_exact_var),
                ("char_gold_include_ocr_yolo_rescue", self.gold_include_ocr_yolo_rescue_var),
                ("char_gold_include_other_perfect", self.gold_include_other_perfect_var),
                ("char_gold_export_split", self.gold_export_split_var),
                ("char_gold_export_train_pct", self.gold_export_train_pct_var),
                ("char_gold_export_val_pct", self.gold_export_val_pct_var),
                ("char_prep_angle", self.prep_angle_var),
                ("char_prep_height", self.prep_height_var),
                ("char_prep_padding", self.prep_padding_var),
                ("char_prep_clip", self.prep_clip_var),
                ("char_prep_denoise", self.prep_denoise_var),
                ("char_prep_clahe", self.prep_clahe_var),
                ("char_prep_use_bin", self.prep_use_bin_var),
                ("char_prep_block", self.prep_block_var),
                ("char_prep_c", self.prep_c_var),
                ("char_prep_erode", self.prep_erode_var),
                ("char_do_clahe", self.do_clahe_var),
                ("char_interpolation", self.interpolation_var),
            ]

            for k, var in always_saved:
                self._save_local_setting(k, var.get())

            self._save_local_setting("char_det_method", self._get_detection_method_key())

            self._prune_legacy_yolo_arch_session_keys()

            self._save_local_setting("char_preview_box_mode", self._get_preview_box_mode_key())
            self._save_local_setting("char_preview_sort_mode", self._get_preview_sort_mode_key())

            # ścieżki wejściowe zapisujemy tylko poza liniowym workflow kampanii
            if not getattr(self, "_step3_linear_mode", False):
                for k, var in [
                    ("char_xml_path", self.xml_path_var),
                    ("char_images_dir", self.images_dir_var),
                    ("char_yolo_model", self.yolo_model_path_var),
                    ("char_preview_dir", self.preview_dir_var),
                ]:
                    self._save_local_setting(k, var.get())

        except Exception:
            pass

    def _on_app_close(self, event):
        if str(event.widget) == str(self.app.root):
            self._force_save_all()

    def _on_method_change(self, event=None):
        self._update_yolo_visibility()

    def _update_yolo_visibility(self):
        if not hasattr(self, "yolo_panel"):
            return

        method = self._get_detection_method_key()

        try:
            self._sync_yolo_model_binding()
        except Exception:
            pass

        is_ocr = method == "OCR"
        is_yolo = method == "YOLO"
        is_hybrid = method == "BOTH"

        if hasattr(self, "hybrid_rescue_frame"):
            if is_hybrid:
                self.hybrid_rescue_frame.pack(fill=tk.X, pady=(0, 8))
            else:
                self.hybrid_rescue_frame.pack_forget()

        # panel YOLO pokazujemy dla YOLO i HYBRYDY
        if is_yolo or is_hybrid:
            self.yolo_panel.pack(fill=tk.X, pady=(5, 0))
        else:
            self.yolo_panel.pack_forget()

        for attr_name in (
            "yolo_conf_spin",
            "yolo_iou_spin",
            "yolo_overlap_spin",
            "yolo_seq_center_y_scale",
            "yolo_seq_min_h_scale",
            "yolo_seq_max_h_scale",
            "yolo_seq_max_w_scale",
            "yolo_seq_soft_overlap_scale",
            "yolo_seq_hard_overlap_scale",
        ):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                self._set_widget_state(
                    widget,
                    "normal" if (is_yolo or is_hybrid) else "disabled"
                )

        for attr_name in ("hybrid_rescue_scale",):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                self._set_widget_state(widget, "normal" if is_hybrid else "disabled")

        if hasattr(self, "hybrid_yolo_box_backend_row_info"):
            self.hybrid_yolo_box_backend_row_info["enabled"] = bool(is_hybrid)
            self._refresh_selection_row(self.hybrid_yolo_box_backend_row_info)

        if hasattr(self, "yolo_agnostic_row_info"):
            self.yolo_agnostic_row_info["enabled"] = bool(is_yolo or is_hybrid)
            self._refresh_selection_row(self.yolo_agnostic_row_info)

        # w trybie kampanii ścieżka modelu jest sterowana z Wizarda
        path_locked = bool(getattr(self, "_step3_linear_mode", False))

        if hasattr(self, "det_yolo_model_entry"):
            self._set_widget_state(
                self.det_yolo_model_entry,
                "disabled" if path_locked else "readonly"
            )

        if hasattr(self, "det_yolo_model_browse_btn"):
            self._set_widget_state(
                self.det_yolo_model_browse_btn,
                "disabled" if path_locked else "normal"
            )

        # Laboratorium OCR:
        # - OCR: aktywne
        # - YOLO: nieaktywne
        # - BOTH: aktywne
        if hasattr(self, "btn_ocr_lab"):
            self._set_widget_state(self.btn_ocr_lab, "disabled" if is_yolo else "normal")

        # Turniej presetow OCR:
        # - tylko dla czystego OCR
        if hasattr(self, "btn_rank_presets"):
            self._set_widget_state(self.btn_rank_presets, "normal" if is_ocr else "disabled")

        # Panel zwyciezcy rankingu dotyczy wylacznie rankingu OCR.
        if hasattr(self, "winner_name_lbl") and hasattr(self, "winner_acc_lbl"):
            if is_ocr:
                self._update_winner_label()
            elif is_yolo:
                self._set_winner_name("Brak rankingu OCR", "neutral")
                self._set_winner_acc("Tryb YOLO nie bierze udzialu w turnieju OCR", "muted")
            else:  # BOTH
                self._set_winner_name("Brak rankingu OCR", "neutral")
                self._set_winner_acc("Tryb hybrydowy nie ustala zwyciezcy turnieju OCR", "muted")

        if hasattr(self, "test_status_lbl"):
            if is_yolo:
                self._set_test_status(
                    "Tryb YOLO: wskaz wytrenowany model znakow .pt i uzyj 'Uruchom detekcje'",
                    "muted"
                )
            elif is_hybrid:
                self._set_test_status(self._get_hybrid_detection_status_text(), "info")
            else:
                self._set_test_status(
                    "Tryb OCR: mozesz uruchomic detekcje lub turniej presetow OCR",
                    "success"
                )
            return

    def _auto_device_label(self) -> str:
        return "auto (prefer GPU/CUDA, fallback CPU)"

    def _get_available_devices(self):
        devices = [self._auto_device_label(), "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    name = torch.cuda.get_device_name(i)
                    devices.append(f"cuda:{i} ({name})")
        except Exception:
            pass
        return devices

    def _normalize_selected_device(self, raw_value: str | None = None, devices=None) -> str:
        available = list(devices or self._get_available_devices())
        current = str(raw_value if raw_value is not None else self.yolo_device_var.get() or "").strip()
        current_lower = current.lower()

        if not current or current_lower.startswith("auto"):
            return available[0] if available else "auto"
        if current_lower.startswith("cpu"):
            return "cpu"
        if current_lower.startswith("cuda:"):
            prefix = current.split()[0]
            for option in available:
                if option.startswith(prefix):
                    return option

        return current if current in available else (available[0] if available else "auto")

    def _refresh_device_options(self):
        devices = self._get_available_devices()
        if hasattr(self, "det_device_combo"):
            try:
                self.det_device_combo.configure(values=devices)
            except Exception:
                pass

        normalized = self._normalize_selected_device(devices=devices)
        if normalized:
            self.yolo_device_var.set(normalized)

        self._update_device_hint()

    def _device_to_ultralytics(self, s: str):
        raw = str(s or "").strip().lower()
        if not raw or raw.startswith("auto"):
            try:
                import torch
                if torch.cuda.is_available():
                    return 0
            except Exception:
                pass
            return "cpu"
        if raw.startswith("cpu"):
            return "cpu"
        if raw.startswith("cuda:"):
            try:
                return int(str(s).split(":")[1].split()[0])
            except Exception:
                return 0
        return "cpu"

    def _device_to_ocr(self, s: str) -> str:
        return "cuda" if self._device_to_ultralytics(s) != "cpu" else "cpu"

    def _update_device_hint(self, event=None):
        label = getattr(self, "det_device_hint_lbl", None)
        if label is None:
            return

        devices = self._get_available_devices()
        normalized = self._normalize_selected_device(devices=devices)
        current = str(self.yolo_device_var.get() or "").strip()
        if normalized != current:
            self.yolo_device_var.set(normalized)
            current = normalized

        gpu_devices = [item for item in devices if item.startswith("cuda:")]
        current_lower = current.lower()

        if current_lower.startswith("auto"):
            if gpu_devices:
                text = f"Auto najpierw sprobuje akceleracji na {gpu_devices[0]}. Gdy GPU/CUDA nie bedzie dostepne, system spadnie do CPU."
                tone = "info"
            else:
                text = "Auto nie wykrylo karty CUDA, wiec zostanie uzyty CPU."
                tone = "warning"
        elif current_lower.startswith("cpu"):
            text = "CPU wymusza prace bez akceleracji GPU. To wolniejsze, ale przewidywalne."
            tone = "muted"
        else:
            text = f"Wybrana karta: {current}. YOLO i OCR sprobuja uzyc tej akceleracji."
            tone = "success"

        self._set_themed_label_state(label, text=text, tone=tone)
    
    def _set_button_emphasis(self, frame_attr: str, enabled: bool, color: str = "#f39c12"):
        btn = self._resolve_guidance_button(frame_attr)
        if btn is None:
            return

        try:
            self.app.set_button_emphasis(btn, enabled)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić podświetlenia przycisku dla {frame_attr}: {e}")

    def _ensure_yolo_model_available(self) -> str:
        """Zachowane dla kompatybilnosci wstecznej; deleguje do checkpoint-only resolvera."""
        return self._ensure_yolo_model_checkpoint()

    # =========================================================
    # Resolvers
    # =========================================================

    def _ensure_yolo_model_checkpoint(self) -> str:
        """
        Zwraca ścieżkę do wytrenowanego checkpointu YOLO znaków.
        Z3/PZ2 nie korzysta z niewytrenowanych wariantów architektury.
        """
        effective_model = self._get_effective_yolo_model_path()
        if effective_model and Path(effective_model).exists():
            model_path = Path(effective_model)
            if model_path.suffix.lower() != ".pt":
                raise RuntimeError("Model YOLO znaków musi mieć rozszerzenie .pt.")
            self._log(self.test_log_text, f"[INFO] Używam lokalnego modelu: {model_path}", "INFO")
            return str(model_path)

        if getattr(self, "_step3_linear_mode", False):
            raise RuntimeError(
                "Brak wytrenowanego modelu znaków przypiętego do projektu. "
                "Najpierw przygotuj i wytrenuj model w Z4."
            )

        raise RuntimeError(
            "Wskaż wytrenowany model YOLO znaków (.pt). "
            "W Z3/PZ2 nie korzystamy z niewytrenowanych wariantów architektury."
        )

    # =========================================================
    # Pickers
    # =========================================================

    def _pick_xml_file(self):
        p = filedialog.askopenfilename(
            initialdir=str(Path(CONFIG.get_auto_annotations_dir("plate")).absolute()),
            title="Wybierz annotations.xml dla tej samej paczki obrazów",
            filetypes=[("XML", "*.xml")]
        )
        if p:
            self.xml_path_var.set(p)

    def _pick_images_dir(self):
        p = filedialog.askdirectory(
            initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()),
            title="Wybierz paczkę obrazów powiązaną z annotations.xml"
        )
        if p:
            self.images_dir_var.set(p)

    def _pick_yolo_model(self):
        initial_dir = CONFIG.get_trained_models_dir("char")
        if not initial_dir.exists():
            initial_dir = CONFIG.DIR_6_MODELS
        p = filedialog.askopenfilename(
            initialdir=str(Path(initial_dir).absolute()),
            title="Wybierz model YOLO (.pt)",
            filetypes=[("PyTorch", "*.pt")]
        )
        if p:
            self.yolo_model_path_var.set(p)

    def _pick_and_load_preview_dir(self):
        initial = getattr(self, "_campaign_chars_dir", str(Path(CONFIG.DIR_3_CHARS).absolute()))
        p = filedialog.askdirectory(initialdir=str(initial), title="Wybierz folder wyników (zawierający metadata.json)")
        if p:
            self.preview_dir_var.set(p)
            self._force_save_all()
            self._reset_preview_cache()
            self._load_preview_data()

    # =========================================================
    # Logging helper
    # =========================================================

    def _log(self, txt_widget, msg: str, tag: str = "INFO"):
        def do_log():
            try:
                txt_widget.configure(state="normal")

                if not txt_widget.tag_names():
                    txt_widget.tag_config("SUCCESS", foreground="#27ae60", font=("Consolas", 9, "bold"))
                    txt_widget.tag_config("ERROR", foreground="#c0392b", font=("Consolas", 9, "bold"))
                    txt_widget.tag_config("WARNING", foreground="#d35400", font=("Consolas", 9, "bold"))
                    txt_widget.tag_config("INFO", foreground="#2980b9", font=("Consolas", 9))
                    txt_widget.tag_config("HEADER", foreground="#8e44ad", font=("Consolas", 10, "bold"))

                final_tag = tag
                if tag == "INFO":
                    if "✅" in msg:
                        final_tag = "SUCCESS"
                    elif "❌" in msg:
                        final_tag = "ERROR"

                txt_widget.insert(tk.END, msg + "\n", final_tag)
                txt_widget.see(tk.END)
                txt_widget.update_idletasks()

            finally:
                try:
                    txt_widget.configure(state="disabled")
                except Exception:
                    pass

        self.frame.after(0, do_log)

    def _get_true_texts_from_filename(self, filename: str) -> list:
        stem = Path(filename).stem.upper()
        import re
        parts = re.findall(r'[A-Z0-9]{4,}', stem)
        if not parts:
            return []
        if len(parts) > 1:
            return parts[:-1]
        return parts

    def _get_current_prep_params(self):
        return {
            "target_height": self.prep_height_var.get(),
            "manual_angle": self.prep_angle_var.get(),
            "clip_thresh": self.prep_clip_var.get(),
            "denoise_h": self.prep_denoise_var.get(),
            "clahe_clip": self.prep_clahe_var.get() if self.do_clahe_var.get() else 0.0,
            "use_binarization": self.prep_use_bin_var.get(),
            "thresh_block": self.prep_block_var.get(),
            "thresh_c": self.prep_c_var.get(),
            "erode_iter": self.prep_erode_var.get(),
            "interpolation": self.interpolation_var.get(),
            "padding_pct": self.prep_padding_var.get(),
        }

    def _get_best_preset(self):
        cache_file = self.presets_dir / "global_ranking.json"
        if not cache_file.exists():
            return None, 0.0
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            best_name, best_acc, best_params = None, -1.0, {}
            for preset_key, stats in data.items():
                acc = float(stats.get("acc", 0.0))
                if acc > best_acc:
                    best_acc, best_name, best_params = acc, str(stats.get("name", preset_key)), stats.get("params", {})
            if best_name:
                return {"name": best_name, "params": best_params}, best_acc
        except Exception:
            pass
        return None, 0.0

    # =========================================================
    # UI build
    # =========================================================

    def _create_widgets(self):
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 0))

        self.tab_extract = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_extract, text="[PZ1] Wycinanie tablic")
        self._build_extraction_tab(self.tab_extract)

        self.tab_detect = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_detect, text="[PZ2] Wykrywanie znaków i analiza")
        self._build_detection_tab(self.tab_detect)

        self.tab_dataset = ttk.Frame(self.main_nb)
        self.main_nb.add(self.tab_dataset, text="[PZ3] Integracje i dataset (YOLO)")
        self._build_cvat_tab(self.tab_dataset)
        self.main_nb.bind("<<NotebookTabChanged>>", self._on_main_nb_tab_changed, add="+")

    # =========================================================
    # TAB 1: Extraction
    # =========================================================

    def _build_extraction_tab(self, parent):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)

        self.extract_left_scroll_host = ttk.Frame(left, style="Panel.TFrame")
        self.extract_left_scroll_host.pack(fill=tk.BOTH, expand=True)
        self.extract_left_scroll_host.grid_rowconfigure(0, weight=1)
        self.extract_left_scroll_host.grid_columnconfigure(0, weight=1)

        self.extract_left_canvas = tk.Canvas(
            self.extract_left_scroll_host,
            bg="#252526",
            bd=0,
            highlightthickness=0,
        )
        self.extract_left_canvas.grid(row=0, column=0, sticky="nsew")

        self.extract_left_scrollbar = WebSlimScrollbar(
            self.extract_left_scroll_host,
            command=self.extract_left_canvas.yview,
            width=10,
        )
        self.extract_left_scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self.extract_left_canvas.configure(yscrollcommand=self.extract_left_scrollbar.set)

        self.extract_left_content = ttk.Frame(self.extract_left_canvas, style="Panel.TFrame")
        self.extract_left_content.grid_columnconfigure(0, weight=1)
        self.extract_left_content_window = self.extract_left_canvas.create_window(
            (0, 0),
            window=self.extract_left_content,
            anchor="nw",
        )
        self.extract_left_content.bind("<Configure>", self._sync_extract_left_scrollregion, add="+")
        self.extract_left_canvas.bind("<Configure>", self._sync_extract_left_canvas_width, add="+")
        self.extract_left_canvas.bind(
            "<MouseWheel>",
            lambda e: self._redirect_child_mousewheel_to_canvas(e, self.extract_left_canvas, self._extract_left_canvas_overflows),
            add="+",
        )
        self.extract_left_canvas.bind(
            "<Button-4>",
            lambda e: self._redirect_child_mousewheel_to_canvas(e, self.extract_left_canvas, self._extract_left_canvas_overflows),
            add="+",
        )
        self.extract_left_canvas.bind(
            "<Button-5>",
            lambda e: self._redirect_child_mousewheel_to_canvas(e, self.extract_left_canvas, self._extract_left_canvas_overflows),
            add="+",
        )

        lf_paths = ttk.LabelFrame(self.extract_left_content, text=" Źródła do wycinania tablic ", padding=15)
        lf_paths.pack(fill=tk.X, pady=(0, 15))

        self.extract_paths_intro_lbl = ttk.Label(
            lf_paths,
            text=(
                "Z3/PZ1 działa zawsze na zgodnej parze źródeł: pliku annotations.xml oraz folderze "
                "oryginalnych obrazów, na których wykonano te anotacje. Jeśli para nie jest zgodna, "
                "wycinanie nie wystartuje."
            ),
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
            wraplength=430,
        )
        self.extract_paths_intro_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

        ttk.Label(
            lf_paths,
            text="Plik annotations.xml:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))
        row_xml = ttk.Frame(lf_paths)
        row_xml.pack(fill=tk.X, pady=(0, 10))
        self.xml_path_entry = ttk.Entry(row_xml, textvariable=self.xml_path_var)
        self.xml_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.xml_path_browse_btn = ttk.Button(
            row_xml,
            text="Wybierz",
            command=self._pick_xml_file
        )
        self.xml_path_browse_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.extract_xml_hint_lbl = ttk.Label(
            lf_paths,
            text=(
                "To pojedynczy plik XML z anotacjami tablic. Najczęściej pochodzi z runu Z2 albo z CVAT. "
                "Musi opisywać dokładnie te same obrazy, które wskażesz poniżej."
            ),
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
            wraplength=430,
        )
        self.extract_xml_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

        ttk.Label(
            lf_paths,
            text="Folder oryginalnych obrazów powiązanych z XML:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))
        row_img = ttk.Frame(lf_paths)
        row_img.pack(fill=tk.X, pady=(0, 10))

        self.images_dir_entry = ttk.Entry(row_img, textvariable=self.images_dir_var)
        self.images_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.images_dir_browse_btn = ttk.Button(
            row_img,
            text="Wybierz",
            command=self._pick_images_dir
        )
        self.images_dir_browse_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.extract_images_hint_lbl = ttk.Label(
            lf_paths,
            text=(
                "To folder ze zdjęciami źródłowymi .jpg/.png, na których wykonano anotacje zapisane w XML. "
                "W trybie swobodnym najlepiej, aby paczka leżała w Workspace/1_raw_images/. "
                "Wtedy system potrafi ją odnaleźć automatycznie."
            ),
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
            wraplength=430,
        )
        self.extract_images_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

        self.source_binding_status_lbl = tk.Label(
            lf_paths,
            text=(
                "Plik annotations.xml i paczka obrazów są nierozerwalnie powiązane. "
                "System może automatycznie odnaleźć paczkę w Workspace/1_raw_images/."
            ),
            justify=tk.LEFT,
            anchor="w",
            wraplength=430,
            bd=0,
            highlightthickness=0,
        )
        self.source_binding_status_lbl.pack(fill=tk.X, pady=(0, 6))
        self._set_source_binding_status(
            "Plik annotations.xml i paczka obrazów są nierozerwalnie powiązane. "
            "System może automatycznie odnaleźć paczkę w Workspace/1_raw_images/.",
            "warning",
        )

        lf_run = ttk.LabelFrame(self.extract_left_content, text=" Wycinanie tablic ", padding=15)
        lf_run.pack(fill=tk.X)

        self.extract_result_hint_lbl = ttk.Label(
            lf_run,
            text=(
                "Po kliknięciu Start powstanie nowy folder run_XXX w Workspace/3_cropped_characters/. "
                "W środku znajdą się wycięte i zrektyfikowane tablice oraz plik metadata.json. "
                "Ta paczka staje się później źródłem dla Z3/PZ2."
            ),
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
            wraplength=430,
        )
        self.extract_result_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

        self.btn_extract = ttk.Button(lf_run, text="START (Wytnij tablice z paczki)", command=self._run_extraction, style="Accent.TButton")
        self.btn_extract.pack(fill=tk.X, ipady=5)

        self.btn_ext_stop = ttk.Button(lf_run, text="ZATRZYMAJ", command=lambda: setattr(self, 'is_processing', False), state=tk.DISABLED)
        self.btn_ext_stop.pack(fill=tk.X, pady=5)

        self.ext_progress = ttk.Progressbar(lf_run, maximum=100)
        self.ext_progress.pack(fill=tk.X, pady=(15, 5))
        self.ext_status = tk.Label(
            lf_run,
            text="Gotowy",
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.ext_status.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.ext_status, text="Gotowy", tone="neutral", emphasis=True)

        lf_logs = ttk.LabelFrame(right, text=" Terminal procesu ", padding=10)
        lf_logs.pack(fill=tk.BOTH, expand=True)

        self.ext_log_host = ttk.Frame(lf_logs, style="Panel.TFrame")
        self.ext_log_host.pack(fill=tk.BOTH, expand=True)

        self.ext_log = tk.Text(
            self.ext_log_host,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg="#161616",
            fg="#f3f3f3",
            insertbackground="#f3f3f3",
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.ext_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.ext_log_scrollbar = WebSlimScrollbar(
            self.ext_log_host,
            orient=tk.VERTICAL,
            command=self.ext_log.yview,
            auto_hide=False,
        )
        self.ext_log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.ext_log.configure(yscrollcommand=self.ext_log_scrollbar.set)
        self.ext_log.web_vbar = self.ext_log_scrollbar

        HELP.bind_help(lf_paths, "t2_sources")
        HELP.bind_help(row_xml, "t2_xml")
        HELP.bind_help(row_img, "t2_img")
        HELP.bind_help(self.btn_extract, "t2_cut_start")
        HELP.bind_help(lf_logs, "t2_cut_logs")

        self._bind_scroll_canvas_children(
            self.extract_left_content,
            self.extract_left_canvas,
            self._extract_left_canvas_overflows,
        )
        self.frame.after_idle(self._sync_extract_left_scrollregion)
        self.frame.after_idle(self._sync_extract_left_canvas_width)

        nav = ttk.Frame(parent)
        nav.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.btn_back_to_wizard_step3 = ttk.Button(
            nav,
            text="← Wstecz",
            command=self._return_to_wizard_for_step3_rework,
            state=tk.DISABLED
        )
        self.btn_back_to_wizard_step3.pack(side=tk.LEFT)

        self.btn_to_detect_frame = tk.Frame(nav, bd=0, highlightthickness=0)
        self.btn_to_detect_frame.pack(side=tk.RIGHT)

        self.btn_to_detect = ttk.Button(
            self.btn_to_detect_frame,
            text="Dalej → Wykrywanie Znaków i Analiza",
            command=self.go_to_substep_2,
            state=tk.DISABLED
        )
        self.btn_to_detect.pack()

    def _run_extraction(self):
        self._force_save_all()
        validation = self._refresh_source_binding_status(allow_autofind=True)
        if not validation.get("ok"):
            return messagebox.showerror("Niezgodne źródła Z3/PZ1", validation.get("message", "Źródła wejściowe są niepoprawne."))

        xml_path = Path(self.xml_path_var.get().strip())
        images_dir = Path(self.images_dir_var.get().strip())
        session_token = self._project_reset_token

        if not xml_path.exists() or not images_dir.exists():
            return messagebox.showerror(
                "Błąd",
                "Brak plików wejściowych. annotations.xml i paczka obrazów muszą pochodzić z tego samego zestawu."
            )

        import datetime
        base_out_dir = Path(getattr(self, "_campaign_chars_dir", str(CONFIG.DIR_3_CHARS)))
        base_out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        counter = 1
        while True:
            run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}"
            if not run_dir.exists():
                break
            counter += 1

        run_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir_var.set(str(run_dir))
        self._reset_preview_cache()
        self._force_save_all()

        try:
            tree = ET.parse(xml_path)
            xml_images = {img.get("name"): img for img in tree.getroot().findall(".//image") if img.get("name")}
        except Exception:
            return messagebox.showerror("Błąd", "Zły plik XML.")

        self.btn_extract.config(state=tk.DISABLED)
        self.btn_ext_stop.config(state=tk.NORMAL)
        self.is_processing = True
        self._set_extraction_status("Start wycinania...", "info")

        def worker():
            try:
                if session_token != self._project_reset_token:
                    return

                self._log(self.ext_log, f"\nROZPOCZĘTO WYCINANIE DO: {run_dir.name}\n", "HEADER")
                generator = PlateGenerator(run_dir)
                total = len(xml_images)
                processed = 0

                for img_name, img_el in xml_images.items():
                    if (not self.is_processing) or session_token != self._project_reset_token:
                        break
                    img_path = images_dir / img_name
                    if not img_path.exists():
                        processed += 1
                        continue

                    plates = []
                    for poly in img_el.findall(".//polygon[@label='plate']"):
                        pts = [tuple(map(float, p.split(","))) for p in poly.get("points", "").split(";")]
                        if len(pts) >= 4:
                            plates.append(
                                Detection(
                                    "plate", 1.0,
                                    (min(x for x, y in pts), min(y for x, y in pts), max(x for x, y in pts), max(y for x, y in pts)),
                                    polygon=pts
                                )
                            )

                    if plates:
                        ann = ImageAnnotation(img_name, int(img_el.get("width", 0)), int(img_el.get("height", 0)), plates)
                        generator.generate_from_annotations(
                            img_path, ann,
                            rectify=True,
                            do_deskew=False,
                            enhance_contrast=False,
                            interpolation=self.interpolation_var.get()
                        )

                    processed += 1
                    self.frame.after(
                        0,
                        lambda p=(processed / max(1, total)) * 100: (
                            self.ext_progress.config(value=p)
                            if session_token == self._project_reset_token else None
                        )
                    )
                    self.frame.after(
                        0,
                        lambda c=processed, t=total: (
                            self._set_extraction_status(f"{c}/{t} obrazów...", "info")
                            if session_token == self._project_reset_token else None
                        )
                    )

                generator.save_metadata()
                if self.is_processing and session_token == self._project_reset_token:
                    self.frame.after(0, lambda: self._set_extraction_status("Wycinanie zakończone", "success"))
                    self.frame.after(0, lambda: self._load_preview_data(quiet=True))
                    self.frame.after(0, self.unlock_detection_subtab)
                    self.frame.after(0, lambda: messagebox.showinfo(
                        "Gotowe",
                        "Wycinanie zakończone!\n\nOdblokowano etap 2: Wykrywanie Znaków i Analiza."
                    ))
            except Exception as e:
                if session_token == self._project_reset_token:
                    self.frame.after(0, lambda: self._set_extraction_status("Błąd wycinania", "error"))
                    self._log(self.ext_log, f"\n❌ BŁĄD: {e}\n", "ERROR")
            finally:
                if session_token == self._project_reset_token:
                    self.is_processing = False
                    self.frame.after(0, lambda: self.btn_extract.config(state=tk.NORMAL))
                    self.frame.after(0, lambda: self.btn_ext_stop.config(state=tk.DISABLED))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 2: Detection + Preview
    # =========================================================

    def _build_detection_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_columnconfigure(0, weight=1)

        content_frame = ttk.Frame(parent)
        content_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(0, 10))
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_rowconfigure(1, weight=0)
        content_frame.grid_rowconfigure(2, weight=0)
        content_frame.grid_columnconfigure(0, weight=1)

        split = ttk.PanedWindow(content_frame, orient=tk.HORIZONTAL)
        split.grid(row=0, column=0, sticky="nsew")

        left_panel = ttk.Frame(split)
        right_panel = ttk.Frame(split)
        split.add(left_panel, weight=3)
        split.add(right_panel, weight=2)

        palette = getattr(self.app, "palette", {})

        left_panel.grid_rowconfigure(0, weight=1)
        left_panel.grid_columnconfigure(0, weight=1)

        self.preview_vertical_split = tk.PanedWindow(
            left_panel,
            orient=tk.VERTICAL,
            sashwidth=8,
            sashrelief=tk.RAISED,
            sashcursor="sb_v_double_arrow",
            showhandle=True,
            opaqueresize=True,
            bd=0,
            relief=tk.FLAT,
            background=palette.get("border", "#3c3c3c"),
        )
        self.preview_vertical_split.grid(row=0, column=0, sticky="nsew")

        preview_lf = ttk.LabelFrame(self.preview_vertical_split, text="", padding=8)
        preview_lf.grid_rowconfigure(0, weight=1)
        preview_lf.grid_columnconfigure(0, weight=1)
        preview_lf.grid_columnconfigure(1, weight=0)

        self.preview_canvas = tk.Canvas(
            preview_lf,
            bg="#1e1e1e",
            bd=3,
            relief="sunken",
            highlightthickness=0
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda e: self._on_preview_select(None))
        self.preview_canvas.bind("<ButtonPress-1>", self._on_preview_canvas_press, add="+")
        self.preview_canvas.bind("<B1-Motion>", self._on_preview_canvas_drag, add="+")
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_preview_canvas_release, add="+")
        self.preview_canvas.bind("<MouseWheel>", self._on_preview_canvas_mousewheel, add="+")
        self.preview_canvas.bind("<Button-4>", self._on_preview_canvas_mousewheel, add="+")
        self.preview_canvas.bind("<Button-5>", self._on_preview_canvas_mousewheel, add="+")

        self.preview_mode_lf = ttk.LabelFrame(preview_lf, text=" Tryby podglądu tablic ", padding=6)
        self.preview_mode_lf.grid(row=0, column=1, sticky="ns", padx=(8, 0))

        list_lf = ttk.LabelFrame(self.preview_vertical_split, text="", padding=8)
        list_lf.grid_rowconfigure(2, weight=1)
        list_lf.grid_columnconfigure(0, weight=1)

        self.preview_vertical_split.add(list_lf, minsize=180)
        self.preview_vertical_split.add(preview_lf, minsize=220)

        self.preview_sort_bar = tk.Frame(
            list_lf,
            bd=1,
            relief=tk.SOLID,
            highlightthickness=1,
        )
        self.preview_sort_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.preview_sort_bar.grid_columnconfigure(1, weight=1)

        self.preview_sort_title_lbl = tk.Label(
            self.preview_sort_bar,
            text="Sortuj:",
            anchor="w",
            bd=0,
            highlightthickness=0,
            padx=6,
            font=("Segoe UI", 8),
        )
        self.preview_sort_title_lbl.grid(row=0, column=0, sticky="w")

        self.preview_sort_buttons_frame = tk.Frame(self.preview_sort_bar, bd=0, highlightthickness=0)
        self.preview_sort_buttons_frame.grid(row=0, column=1, sticky="w", padx=(0, 4), pady=1)

        self.preview_sort_buttons = {}
        for idx, (mode_key, mode_label) in enumerate(PREVIEW_SORT_OPTIONS):
            btn_column = idx * 2
            btn = tk.Button(
                self.preview_sort_buttons_frame,
                text=mode_label,
                font=("Segoe UI", 8),
                padx=8,
                pady=1,
                bd=1,
                relief=tk.RAISED,
                cursor="hand2",
                takefocus=0,
                command=lambda target_key=mode_key: self._on_preview_sort_mode_change(target_key),
            )
            btn.grid(row=0, column=btn_column, sticky="w")
            btn.bind("<Enter>", lambda _event, target_key=mode_key: self._set_preview_sort_hover(target_key, True))
            btn.bind("<Leave>", lambda _event, target_key=mode_key: self._set_preview_sort_hover(target_key, False))
            self.preview_sort_buttons[mode_key] = btn
            if idx < len(PREVIEW_SORT_OPTIONS) - 1:
                sep = tk.Frame(self.preview_sort_buttons_frame, width=1, bd=0, highlightthickness=0)
                sep.grid(row=0, column=btn_column + 1, sticky="ns", pady=2)
        self._apply_preview_sort_bar_style()

        self.plates_legend_frame = tk.Frame(list_lf, bd=0, highlightthickness=0)
        self.plates_legend_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.plates_legend_title_lbl = tk.Label(self.plates_legend_frame, text="Lista tablic", bd=0, highlightthickness=0)
        self.plates_legend_title_lbl.pack(side=tk.LEFT, padx=(0, 12))
        self.plates_legend_perfect_dot_lbl = tk.Label(self.plates_legend_frame, text="●", bd=0, highlightthickness=0)
        self.plates_legend_perfect_dot_lbl.pack(side=tk.LEFT)
        self.plates_legend_perfect_text_lbl = tk.Label(self.plates_legend_frame, text="Perfect", bd=0, highlightthickness=0)
        self.plates_legend_perfect_text_lbl.pack(side=tk.LEFT, padx=(4, 10))
        self.plates_legend_sep_lbl = tk.Label(self.plates_legend_frame, text="|", bd=0, highlightthickness=0)
        self.plates_legend_sep_lbl.pack(side=tk.LEFT, padx=(0, 10))
        self.plates_legend_error_dot_lbl = tk.Label(self.plates_legend_frame, text="●", bd=0, highlightthickness=0)
        self.plates_legend_error_dot_lbl.pack(side=tk.LEFT)
        self.plates_legend_error_text_lbl = tk.Label(self.plates_legend_frame, text="Błędy", bd=0, highlightthickness=0)
        self.plates_legend_error_text_lbl.pack(side=tk.LEFT, padx=(4, 0))
        self._apply_plates_legend_style()

        self.plates_listbox = tk.Listbox(
            list_lf,
            font=("Consolas", 10),
            selectbackground="#3498db",
            exportselection=False
        )
        self.plates_listbox.grid(row=2, column=0, sticky="nsew", padx=(0, 6), pady=0)

        scroll = WebSlimScrollbar(list_lf, command=self.plates_listbox.yview)
        scroll.grid(row=2, column=1, sticky="ns")

        self.plates_listbox.config(yscrollcommand=scroll.set)
        self.plates_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

        self.preview_box_mode_rows = []
        for mode_key, mode_label in PREVIEW_BOX_MODE_OPTIONS:
            row = tk.Frame(self.preview_mode_lf, bd=0, highlightthickness=0, cursor="hand2")
            row.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
            indicator = tk.Canvas(
                row,
                width=16,
                height=16,
                bd=0,
                highlightthickness=0,
                cursor="hand2"
            )
            indicator.pack(side=tk.LEFT, padx=(0, 6))
            label = tk.Label(
                row,
                text=mode_label,
                anchor="w",
                justify=tk.LEFT,
                bd=0,
                highlightthickness=0,
                cursor="hand2"
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def _select_preview_mode(_event=None, target_label=mode_label):
                self.preview_box_mode_var.set(target_label)
                self._on_preview_box_mode_change()

            for widget in (row, indicator, label):
                widget.bind("<Button-1>", _select_preview_mode)

            row_info = {
                "kind": "radio",
                "frame": row,
                "indicator": indicator,
                "label": label,
                "selected_getter": (lambda target_label=mode_label: self.preview_box_mode_var.get() == target_label),
                "hovered": False,
            }
            for widget in (row, indicator, label):
                widget.bind("<Enter>", lambda _event, info=row_info: self._set_selection_row_hover(info, True))
                widget.bind("<Leave>", lambda _event, info=row_info: self._set_selection_row_hover(info, False))
            self.preview_box_mode_rows.append(row_info)
        self._apply_preview_mode_radio_style()

        right_panel.grid_rowconfigure(0, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)

        palette = getattr(self.app, "palette", {})
        self.detect_right_scroll_host = ttk.Frame(right_panel)
        self.detect_right_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.detect_right_scroll_host.grid_rowconfigure(0, weight=1)
        self.detect_right_scroll_host.grid_columnconfigure(0, weight=1)

        self.detect_right_canvas = tk.Canvas(
            self.detect_right_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.detect_right_canvas.grid(row=0, column=0, sticky="nsew")

        self.detect_right_scrollbar = WebSlimScrollbar(
            self.detect_right_scroll_host,
            command=self.detect_right_canvas.yview
        )
        self.detect_right_scrollbar.grid(row=0, column=1, sticky="ns")
        self.detect_right_canvas.configure(yscrollcommand=self.detect_right_scrollbar.set)

        self.detect_right_content = ttk.Frame(self.detect_right_canvas)
        self.detect_right_content.grid_columnconfigure(0, weight=1)
        self.detect_right_content_window = self.detect_right_canvas.create_window(
            (0, 0),
            window=self.detect_right_content,
            anchor="nw"
        )
        self.detect_right_content.bind("<Configure>", self._sync_detect_right_scrollregion, add="+")
        self.detect_right_canvas.bind("<Configure>", self._sync_detect_right_canvas_width, add="+")

        set_lf = ttk.LabelFrame(self.detect_right_content, text=" Konfiguracja Rozpoznawania ", padding=8)
        set_lf.grid(row=2, column=0, sticky="ew")

        row_meth = ttk.Frame(set_lf)
        row_meth.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(
            row_meth,
            text="Metoda detekcji znaków:",
            font=("Segoe UI", 9, "bold")
        ).pack(side=tk.LEFT)

        self.det_method_combo = ttk.Combobox(
            row_meth,
            textvariable=self.detection_method_var,
            values=[label for _, label in DETECTION_METHOD_OPTIONS],
            state="readonly",
            width=18
        )
        self.det_method_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        self.det_method_combo.bind("<<ComboboxSelected>>", self._on_method_change)

        self.det_device_row = ttk.Frame(set_lf)
        self.det_device_row.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(self.det_device_row, text="Urzadzenie obliczen:").pack(side=tk.LEFT)

        self.det_device_combo = ttk.Combobox(
            self.det_device_row,
            textvariable=self.yolo_device_var,
            values=self._get_available_devices(),
            state="readonly",
            width=12
        )
        self.det_device_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        self.det_device_combo.bind("<<ComboboxSelected>>", self._update_device_hint, add="+")

        self._refresh_device_options()

        self.hybrid_rescue_frame = ttk.Frame(set_lf)

        ttk.Label(
            self.hybrid_rescue_frame,
            text="YOLO rescue dla znaków niewykrytych przez OCR:"
        ).pack(anchor=tk.W, pady=(0, 2))

        self.hybrid_rescue_slider_row = ttk.Frame(self.hybrid_rescue_frame)
        self.hybrid_rescue_slider_row.pack(fill=tk.X, pady=(0, 6))

        self._hybrid_rescue_scale_updating = False

        def _on_hybrid_rescue_scale_change(raw_value=None):
            if getattr(self, "_hybrid_rescue_scale_updating", False):
                return

            try:
                snapped = int(round(float(raw_value)))
            except Exception:
                snapped = self._get_hybrid_rescue_max_chars()

            snapped = max(1, min(5, snapped))

            try:
                self._hybrid_rescue_scale_updating = True
                if int(self.hybrid_rescue_max_chars_var.get()) != snapped:
                    self.hybrid_rescue_max_chars_var.set(snapped)
                if hasattr(self, "hybrid_rescue_scale"):
                    self.hybrid_rescue_scale.set(float(snapped))
            except Exception:
                pass
            finally:
                self._hybrid_rescue_scale_updating = False

        self.hybrid_rescue_scale = ttk.Scale(
            self.hybrid_rescue_slider_row,
            from_=1,
            to=5,
            orient=tk.HORIZONTAL,
            variable=self.hybrid_rescue_max_chars_var,
            command=_on_hybrid_rescue_scale_change,
            style="Horizontal.TScale",
        )
        self.hybrid_rescue_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.hybrid_rescue_value_lbl = ttk.Label(self.hybrid_rescue_slider_row, width=2, anchor="e")
        self.hybrid_rescue_value_lbl.pack(side=tk.RIGHT, padx=(8, 0))

        def _refresh_hybrid_rescue_value(*_args):
            try:
                current_value = self._get_hybrid_rescue_max_chars()
                self.hybrid_rescue_value_lbl.configure(text=str(current_value))
                if self._get_detection_method_key() == "BOTH" and hasattr(self, "test_status_lbl"):
                    self._set_test_status(self._get_hybrid_detection_status_text(), "info")
            except Exception:
                self.hybrid_rescue_value_lbl.configure(text="2")

        try:
            self.hybrid_rescue_max_chars_var.trace_add("write", _refresh_hybrid_rescue_value)
        except Exception:
            pass
        _on_hybrid_rescue_scale_change(self.hybrid_rescue_max_chars_var.get())
        _refresh_hybrid_rescue_value()

        self.hybrid_yolo_box_backend_row = tk.Frame(self.hybrid_rescue_frame, bd=0, highlightthickness=0, cursor="hand2")
        self.hybrid_yolo_box_backend_row.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
        self.hybrid_yolo_box_backend_indicator = tk.Canvas(
            self.hybrid_yolo_box_backend_row,
            width=16,
            height=16,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.hybrid_yolo_box_backend_indicator.pack(side=tk.LEFT, padx=(0, 6))
        self.hybrid_yolo_box_backend_lbl = tk.Label(
            self.hybrid_yolo_box_backend_row,
            text="Popraw pozycje boxow",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.hybrid_yolo_box_backend_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _toggle_hybrid_yolo_box_backend(_event=None):
            if not getattr(self, "hybrid_yolo_box_backend_row_info", {}).get("enabled", True):
                return "break"
            try:
                self.hybrid_yolo_box_backend_var.set(not bool(self.hybrid_yolo_box_backend_var.get()))
                if self._get_detection_method_key() == "BOTH" and hasattr(self, "test_status_lbl"):
                    self._set_test_status(self._get_hybrid_detection_status_text(), "info")
            except Exception:
                self.hybrid_yolo_box_backend_var.set(True)
            return "break"

        for widget in (self.hybrid_yolo_box_backend_row, self.hybrid_yolo_box_backend_indicator, self.hybrid_yolo_box_backend_lbl):
            widget.bind("<Button-1>", _toggle_hybrid_yolo_box_backend)

        hybrid_yolo_box_backend_row_info = {
            "kind": "check",
            "frame": self.hybrid_yolo_box_backend_row,
            "indicator": self.hybrid_yolo_box_backend_indicator,
            "label": self.hybrid_yolo_box_backend_lbl,
            "selected_getter": lambda: bool(self.hybrid_yolo_box_backend_var.get()),
            "enabled": True,
            "hovered": False,
        }
        for widget in (self.hybrid_yolo_box_backend_row, self.hybrid_yolo_box_backend_indicator, self.hybrid_yolo_box_backend_lbl):
            widget.bind("<Enter>", lambda _event, info=hybrid_yolo_box_backend_row_info: self._set_selection_row_hover(info, True))
            widget.bind("<Leave>", lambda _event, info=hybrid_yolo_box_backend_row_info: self._set_selection_row_hover(info, False))
        self.hybrid_yolo_box_backend_row_info = hybrid_yolo_box_backend_row_info
        self.yolo_option_rows.append(hybrid_yolo_box_backend_row_info)
        self._apply_yolo_option_check_style()

        self.yolo_panel = ttk.Frame(set_lf)

        ttk.Label(
            self.yolo_panel,
            text="Wytrenowany model YOLO znakow (.pt):",
            style="Muted.TLabel"
        ).pack(anchor=tk.W, pady=(5, 0))

        self.yolo_model_row = ttk.Frame(self.yolo_panel)
        self.yolo_model_row.pack(fill=tk.X)

        self.det_yolo_model_entry = ttk.Entry(
            self.yolo_model_row,
            textvariable=self.yolo_model_path_var,
            state="readonly"
        )
        self.det_yolo_model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.det_yolo_model_browse_btn = ttk.Button(
            self.yolo_model_row,
            text="Wybierz",
            command=self._pick_yolo_model
        )
        self.det_yolo_model_browse_btn.pack(side=tk.RIGHT)

        self.yolo_tuning_lf = ttk.LabelFrame(self.yolo_panel, text=" Strojenie YOLO ", padding=8)
        self.yolo_tuning_lf.pack(fill=tk.X, pady=(10, 0))

        def add_yolo_scale(attr_name, parent, label_text, variable, from_, to_, digits=2):
            row = ttk.Frame(parent)
            row.pack(fill=tk.X, pady=(0, 4))

            ttk.Label(row, text=label_text).pack(side=tk.LEFT)

            scale = ttk.Scale(row, from_=from_, to=to_, variable=variable)
            scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
            setattr(self, attr_name, scale)

            value_lbl = ttk.Label(row, width=6, anchor="e")
            value_lbl.pack(side=tk.RIGHT)

            fmt = "{:." + str(int(digits)) + "f}"

            def refresh_value(*_args):
                try:
                    value_lbl.config(text=fmt.format(float(variable.get())))
                except Exception:
                    value_lbl.config(text=str(variable.get()))

            try:
                variable.trace_add("write", refresh_value)
            except Exception:
                pass
            refresh_value()

        ttk.Label(
            self.yolo_tuning_lf,
            text="Te progi pomagają odsiać słabe boxy i usuwać duplikaty na jednym znaku.",
            style="Muted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_conf_row = ttk.Frame(self.yolo_tuning_lf)
        self.yolo_conf_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.yolo_conf_row, text="Confidence:").pack(side=tk.LEFT)
        self.yolo_conf_spin = ttk.Spinbox(
            self.yolo_conf_row,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.yolo_conf_var,
            width=8
        )
        self.yolo_conf_spin.pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Wyzej: mniej slabych i falszywych boxow, ale mozna zgubic trudne znaki. Nizej: wiecej trafien, ale rosnie ryzyko dubli i szumu.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_iou_row = ttk.Frame(self.yolo_tuning_lf)
        self.yolo_iou_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.yolo_iou_row, text="NMS IoU:").pack(side=tk.LEFT)
        self.yolo_iou_spin = ttk.Spinbox(
            self.yolo_iou_row,
            from_=0.01,
            to=0.99,
            increment=0.05,
            textvariable=self.yolo_iou_var,
            width=8
        )
        self.yolo_iou_spin.pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Nizej: NMS agresywniej scala podobne ramki i mocniej wycina duble. Wyzej: zostawia wiecej zblizonych boxow, co pomaga przy ciasnych znakach, ale moze dublowac.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_overlap_row = ttk.Frame(self.yolo_tuning_lf)
        self.yolo_overlap_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.yolo_overlap_row, text="Nakladanie boxow:").pack(side=tk.LEFT)
        self.yolo_overlap_spin = ttk.Spinbox(
            self.yolo_overlap_row,
            from_=0.0,
            to=1.0,
            increment=0.05,
            textvariable=self.yolo_overlap_var,
            width=8
        )
        self.yolo_overlap_spin.pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Nizej: system szybciej uzna dwa boxy za ten sam znak i odrzuci slabszy. Wyzej: dwa boxy musza sie mocniej pokrywac, wiec wiecej dubli moze zostac.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        ttk.Label(
            self.yolo_tuning_lf,
            text="Prog liczony jako wspolna czesc powierzchni mniejszego boxa dla dwoch detekcji.",
            style="Muted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        self.yolo_agnostic_nms_row = tk.Frame(self.yolo_tuning_lf, bd=0, highlightthickness=0, cursor="hand2")
        self.yolo_agnostic_nms_row.pack(anchor=tk.W, fill=tk.X)
        self.yolo_agnostic_nms_indicator = tk.Canvas(
            self.yolo_agnostic_nms_row,
            width=16,
            height=16,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.yolo_agnostic_nms_indicator.pack(side=tk.LEFT, padx=(0, 6))
        self.yolo_agnostic_nms_lbl = tk.Label(
            self.yolo_agnostic_nms_row,
            text="Class agnostic",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.yolo_agnostic_nms_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _toggle_yolo_agnostic(_event=None):
            if not getattr(self, "yolo_agnostic_row_info", {}).get("enabled", True):
                return "break"
            try:
                self.yolo_agnostic_nms_var.set(not bool(self.yolo_agnostic_nms_var.get()))
            except Exception:
                self.yolo_agnostic_nms_var.set(True)
            return "break"

        for widget in (self.yolo_agnostic_nms_row, self.yolo_agnostic_nms_indicator, self.yolo_agnostic_nms_lbl):
            widget.bind("<Button-1>", _toggle_yolo_agnostic)

        yolo_agnostic_row_info = {
            "kind": "check",
            "frame": self.yolo_agnostic_nms_row,
            "indicator": self.yolo_agnostic_nms_indicator,
            "label": self.yolo_agnostic_nms_lbl,
            "selected_getter": lambda: bool(self.yolo_agnostic_nms_var.get()),
            "enabled": True,
            "hovered": False,
        }
        for widget in (self.yolo_agnostic_nms_row, self.yolo_agnostic_nms_indicator, self.yolo_agnostic_nms_lbl):
            widget.bind("<Enter>", lambda _event, info=yolo_agnostic_row_info: self._set_selection_row_hover(info, True))
            widget.bind("<Leave>", lambda _event, info=yolo_agnostic_row_info: self._set_selection_row_hover(info, False))
        self.yolo_agnostic_row_info = yolo_agnostic_row_info
        self.yolo_option_rows.append(yolo_agnostic_row_info)
        self._apply_yolo_option_check_style()

        ttk.Label(
            self.yolo_tuning_lf,
            text="Wlacz, gdy ten sam znak dostaje kilka klas naraz, np. B i 8. Wylacz, gdy model zbyt mocno skleja sasiednie, podobne znaki.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(4, 0))

        self.yolo_seq_lf = ttk.LabelFrame(self.yolo_tuning_lf, text=" Filtr sekwencji znakow ", padding=8)
        self.yolo_seq_lf.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(
            self.yolo_seq_lf,
            text="Po klasycznym NMS system dodatkowo sprawdza, czy boxy ukladaja sie w wiarygodna sekwencje znakow na tablicy.",
            style="Muted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        add_yolo_scale("yolo_seq_center_y_scale", self.yolo_seq_lf, "Tolerancja osi Y:", self.yolo_seq_center_y_var, 0.10, 1.50, digits=2)
        ttk.Label(
            self.yolo_seq_lf,
            text="Nizej: znaki musza lezec blizej jednej linii. Wyzej: filtr jest bardziej wyrozumialy dla krzywych lub nierownych tablic.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        add_yolo_scale("yolo_seq_min_h_scale", self.yolo_seq_lf, "Min. zgodnosc wysokosci:", self.yolo_seq_min_h_ratio_var, 0.20, 1.00, digits=2)
        ttk.Label(
            self.yolo_seq_lf,
            text="Nizej: latwiej przepuscic male lub uszkodzone boxy. Wyzej: filtr mocniej odrzuca znaki o wyraznie innej wysokosci.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        add_yolo_scale("yolo_seq_max_h_scale", self.yolo_seq_lf, "Max. wysokosc wzgledem mediany:", self.yolo_seq_max_h_ratio_var, 1.00, 3.50, digits=2)
        ttk.Label(
            self.yolo_seq_lf,
            text="Nizej: szybciej wylatuja podejrzanie wysokie boxy. Wyzej: latwiej zostawic znaki z duzym marginesem lub przeskalowaniem.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        add_yolo_scale("yolo_seq_max_w_scale", self.yolo_seq_lf, "Max. szerokosc wzgledem mediany:", self.yolo_seq_max_w_ratio_var, 1.00, 4.50, digits=2)
        ttk.Label(
            self.yolo_seq_lf,
            text="Nizej: system mocniej odcina szerokie smieci lub zlane znaki. Wyzej: zostawia wiecej nietypowych, szerokich liter.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        add_yolo_scale("yolo_seq_soft_overlap_scale", self.yolo_seq_lf, "Miekki konflikt nakladania:", self.yolo_seq_soft_overlap_var, 0.00, 1.00, digits=2)
        ttk.Label(
            self.yolo_seq_lf,
            text="Nizej: nawet lekkie wchodzenie jednego boxa w drugi uruchamia rywalizacje sasiednich znakow. Wyzej: filtr rzadziej uznaje konflikt.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        add_yolo_scale("yolo_seq_hard_overlap_scale", self.yolo_seq_lf, "Twardy konflikt nakladania:", self.yolo_seq_hard_overlap_var, 0.00, 1.00, digits=2)
        ttk.Label(
            self.yolo_seq_lf,
            text="Nizej: mocno nachodzace boxy sa szybciej traktowane jako dubel lub blad. Wyzej: system dluzej toleruje ciezkie nakladanie sasiednich znakow.",
            style="PanelMuted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 2))

        self._update_yolo_visibility()

        self.actions_lf = ttk.LabelFrame(self.detect_right_content, text=" Panel OCR ", padding=8)
        self.actions_lf.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

        ocr_top_row = ttk.Frame(self.actions_lf)
        ocr_top_row.pack(fill=tk.X)
        ocr_top_row.grid_columnconfigure(0, weight=3)
        ocr_top_row.grid_columnconfigure(1, weight=2)

        leader_block = ttk.Frame(ocr_top_row)
        leader_block.grid(row=0, column=0, sticky="nsew")

        actions_block = ttk.Frame(ocr_top_row)
        actions_block.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        ttk.Label(
            leader_block,
            text="Lider OCR:",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))

        self.winner_name_lbl = tk.Label(
            leader_block,
            text="BRAK DANYCH",
            width=30,
            anchor="w",
            justify="left",
            wraplength=340,
            bd=0,
            highlightthickness=0
        )
        self.winner_name_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_status_label_state(self.winner_name_lbl, text="BRAK DANYCH", tone="neutral", emphasis=True)

        ttk.Label(
            leader_block,
            text="Status rankingu OCR:",
            style="PanelMuted.TLabel"
        ).pack(anchor=tk.W, pady=(0, 2))

        self.winner_acc_lbl = tk.Label(
            leader_block,
            text="0.0%",
            width=30,
            anchor="w",
            justify="left",
            wraplength=340,
            bd=0,
            highlightthickness=0
        )
        self.winner_acc_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_status_label_state(self.winner_acc_lbl, text="0.0%", tone="muted", emphasis=False)

        self.btn_ocr_lab = ttk.Button(
            actions_block,
            text="Laboratorium OCR (filtry)",
            command=self._open_filter_lab,
            style="Accent.TButton"
        )
        self.btn_ocr_lab.pack(fill=tk.X, ipady=4, pady=(0, 6))

        self.btn_rank_presets = ttk.Button(
            actions_block,
            text="Turniej presetów OCR",
            command=self._run_preset_ranking
        )
        self.btn_rank_presets.pack(fill=tk.X, ipady=3, pady=(0, 6))

        self.test_status_lbl = ttk.Label(
            actions_block,
            text="Gotowy do testów",
            style="PanelStatusNeutral.TLabel",
            width=30,
            anchor="w",
            justify="left",
            wraplength=340
        )
        self.test_status_lbl.pack(anchor=tk.W, fill=tk.X)
        self._set_inline_status_label_state(self.test_status_lbl, text="Gotowy do testow", tone="neutral", emphasis=False)
        self.test_status_lbl.pack_forget()

        package_lf = ttk.LabelFrame(self.detect_right_content, text=" Źródło paczki tablic ", padding=8)
        package_lf.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        package_lf.grid_columnconfigure(0, weight=1)
        try:
            package_lf.configure(text=" Folder wyciętych tablic ")
        except Exception:
            pass

        self.preview_dir_hint_lbl = ttk.Label(
            package_lf,
            text="Domyślnie: Workspace/3_cropped_characters/run_XXX_*",
            font=("Segoe UI", 9, "bold")
        )
        self.preview_dir_hint_lbl.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.preview_dir_entry = ttk.Entry(
            package_lf,
            textvariable=self.preview_dir_var,
            state="readonly"
        )
        self.preview_dir_entry.grid(row=1, column=0, sticky="ew")

        self.preview_dir_browse_btn = ttk.Button(
            package_lf,
            text="Otwórz inną paczkę",
            command=self._pick_and_load_preview_dir
        )
        self.preview_dir_browse_btn.grid(row=2, column=0, sticky="w", pady=(6, 4))
        try:
            self.preview_dir_browse_btn.configure(text="Wskaż inną paczkę tablic")
        except Exception:
            pass

        try:
            self.preview_dir_browse_btn.configure(text="Wskaż folder")
        except Exception:
            pass

        self.preview_info_lbl = tk.Label(
            package_lf,
            text="Wczytano tablic: 0",
            justify="left",
            wraplength=360,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.preview_info_lbl.grid(row=3, column=0, sticky="w")
        self._set_inline_status_label_state(self.preview_info_lbl, text="Wczytano tablic: 0", tone="info", emphasis=False)

        self.preview_counts_frame = tk.Frame(package_lf, bd=0, highlightthickness=0)
        self.preview_counts_frame.grid(row=4, column=0, sticky="w", pady=(2, 0))
        self.preview_counts_frame.grid_columnconfigure(0, weight=0)

        self.preview_perfect_dot_lbl = tk.Label(self.preview_counts_frame, text="●", bd=0, highlightthickness=0)
        self.preview_perfect_dot_lbl.pack(side=tk.LEFT)
        self.preview_perfect_count_lbl = tk.Label(self.preview_counts_frame, text="Perfect 0", bd=0, highlightthickness=0)
        self.preview_perfect_count_lbl.pack(side=tk.LEFT, padx=(4, 10))
        self.preview_counts_sep1_lbl = tk.Label(self.preview_counts_frame, text="|", bd=0, highlightthickness=0)
        self.preview_counts_sep1_lbl.pack(side=tk.LEFT, padx=(0, 10))
        self.preview_error_dot_lbl = tk.Label(self.preview_counts_frame, text="●", bd=0, highlightthickness=0)
        self.preview_error_dot_lbl.pack(side=tk.LEFT)
        self.preview_error_count_lbl = tk.Label(self.preview_counts_frame, text="Błędy 0", bd=0, highlightthickness=0)
        self.preview_error_count_lbl.pack(side=tk.LEFT, padx=(4, 10))
        self.preview_counts_sep2_lbl = tk.Label(self.preview_counts_frame, text="|", bd=0, highlightthickness=0)
        self.preview_counts_sep2_lbl.pack(side=tk.LEFT, padx=(0, 10))
        self.preview_unknown_dot_lbl = tk.Label(self.preview_counts_frame, text="●", bd=0, highlightthickness=0)
        self.preview_unknown_dot_lbl.pack(side=tk.LEFT)
        self.preview_unknown_count_lbl = tk.Label(self.preview_counts_frame, text="Nieocenione 0", bd=0, highlightthickness=0)
        self.preview_unknown_count_lbl.pack(side=tk.LEFT, padx=(4, 0))
        self._apply_preview_info_stats_style()

        self.preview_fusion_info_lbl = tk.Label(
            package_lf,
            text=self._format_perfect_strategy_counts(self._empty_perfect_strategy_counts()),
            justify="left",
            wraplength=360,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.preview_fusion_info_lbl.grid(row=5, column=0, sticky="w", pady=(4, 0))
        self._set_inline_status_label_state(
            self.preview_fusion_info_lbl,
            text=self._format_perfect_strategy_counts(self._empty_perfect_strategy_counts()),
            tone="muted",
            emphasis=False
        )

        self.preview_box_mode_info_lbl = tk.Label(
            package_lf,
            text="Tryb boxow: brak zaznaczonej tablicy",
            justify="left",
            wraplength=360,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.preview_box_mode_info_lbl.grid(row=6, column=0, sticky="w", pady=(4, 0))
        self._set_inline_status_label_state(
            self.preview_box_mode_info_lbl,
            text="Tryb boxow: brak zaznaczonej tablicy",
            tone="muted",
            emphasis=False
        )

        detection_log_tools = ttk.Frame(content_frame)
        detection_log_tools.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.btn_toggle_detection_log = ttk.Button(
            detection_log_tools,
            text="Pokaż terminal",
            command=self._toggle_detection_process_log
        )
        self.btn_toggle_detection_log.pack(side=tk.LEFT)

        ttk.Label(
            detection_log_tools,
            text="Terminal procesu jest dostępny na żądanie użytkownika.",
            style="Muted.TLabel"
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.detection_log_frame = ttk.LabelFrame(content_frame, text=" Terminal procesu ", padding=10)
        self.detection_log_frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

        self.detection_log_host = ttk.Frame(self.detection_log_frame, style="Panel.TFrame")
        self.detection_log_host.pack(fill=tk.BOTH, expand=True)

        self.test_log_text = tk.Text(
            self.detection_log_host,
            height=7,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.test_log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.detection_log_scrollbar = WebSlimScrollbar(
            self.detection_log_host,
            orient=tk.VERTICAL,
            command=self.test_log_text.yview,
            auto_hide=False,
        )
        self.detection_log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.test_log_text.configure(yscrollcommand=self.detection_log_scrollbar.set)
        self.test_log_text.web_vbar = self.detection_log_scrollbar

        try:
            self.test_log_text.insert(tk.END, "Gotowy do uruchomienia detekcji znaków.\n")
            self.test_log_text.configure(state="disabled")
        except Exception:
            pass

        self._set_detection_process_log_visibility(False)
        detection_log_tools.grid_remove()

        footer_nav = ttk.Frame(content_frame)
        footer_nav.grid(row=1, column=0, sticky="sew", pady=(2, 0))
        footer_nav.grid_rowconfigure(0, weight=1)
        footer_nav.grid_columnconfigure(0, weight=0)
        footer_nav.grid_columnconfigure(1, weight=0)
        footer_nav.grid_columnconfigure(2, weight=0)
        footer_nav.grid_columnconfigure(3, weight=1)
        footer_nav.grid_columnconfigure(4, weight=0)

        self.btn_back_to_extract = ttk.Button(
            footer_nav,
            text="← Wstecz do Wycinania Tablic",
            command=self.back_to_substep_1
        )
        self.btn_back_to_extract.grid(row=0, column=0, sticky="sw")
        self.btn_back_to_extract.configure(padding=(8, 2))

        self.btn_run_detection_frame = tk.Frame(footer_nav, bd=0, highlightthickness=0)
        self.btn_run_detection_frame.grid(row=0, column=2, sticky="sw", padx=(10, 0))

        self.btn_run_detection_pulse_frame = tk.Frame(
            self.btn_run_detection_frame,
            bd=0,
            highlightthickness=0
        )
        self.btn_run_detection_pulse_frame.pack(anchor=tk.W)

        self.btn_run_detection = ttk.Button(
            self.btn_run_detection_pulse_frame,
            text="Uruchom detekcję",
            command=self._run_detection_stage,
            style="Accent.TButton"
        )
        self.btn_run_detection.pack(fill=tk.X)
        self.btn_run_detection.configure(padding=(10, 2))

        self.detect_run_status_frame = ttk.Frame(footer_nav)
        self.detect_run_status_frame.grid(row=0, column=3, sticky="sew", padx=(12, 0))
        self.detect_run_status_frame.grid_columnconfigure(0, weight=1)
        self.detect_run_status_frame.grid_columnconfigure(1, weight=0)

        self.test_status_lbl = tk.Label(
            self.detect_run_status_frame,
            text="Gotowy do testÄ‚Ĺ‚w",
            anchor="w",
            justify="left",
            bd=0,
            highlightthickness=0
        )
        self.test_status_lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self._set_inline_status_label_state(self.test_status_lbl, text="Gotowy do testow", tone="neutral", emphasis=False)

        self.test_progress = SlimProgressBar(
            self.detect_run_status_frame,
            maximum=100,
            value=0,
            thickness=2,
            trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
            fill_color=palette.get("accent", "#0e639c"),
            bg=palette.get("panel", "#252526"),
            width=240,
            height=6,
        )
        self.test_progress.grid(row=1, column=0, sticky="ew")

        self.test_progress_count_lbl = tk.Label(
            self.detect_run_status_frame,
            text="",
            anchor="e",
            width=14,
            bd=0,
            highlightthickness=0
        )
        self.test_progress_count_lbl.grid(row=1, column=1, sticky="e", padx=(8, 0))
        self._set_inline_status_label_state(self.test_progress_count_lbl, text="", tone="muted", emphasis=True)

        self.footer_test_status_lbl = tk.Label(
            footer_nav,
            text="Gotowy do testĂłw",
            anchor="w",
            justify="left",
            wraplength=460,
            bd=0,
            highlightthickness=0
        )
        self.footer_test_status_lbl.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=(4, 0))
        self._set_inline_status_label_state(self.footer_test_status_lbl, text="Gotowy do testow", tone="neutral", emphasis=True)
        self.footer_test_status_lbl.grid_remove()
        self._set_test_progress_counter()

        self.btn_toggle_detection_log = ttk.Button(
            footer_nav,
            text="PokaĹĽ terminal",
            command=self._toggle_detection_process_log
        )
        self.btn_toggle_detection_log.grid(row=0, column=1, sticky="sw", padx=(10, 0))
        self.btn_toggle_detection_log.configure(text="Pokaz terminal", padding=(8, 2))

        self.btn_to_dataset_frame = tk.Frame(footer_nav, bd=0, highlightthickness=0)
        self.btn_to_dataset_frame.grid(row=0, column=4, sticky="se", padx=(10, 0))

        self.btn_to_dataset_pulse_frame = tk.Frame(
            self.btn_to_dataset_frame,
            bd=0,
            highlightthickness=0
        )
        self.btn_to_dataset_pulse_frame.pack(anchor=tk.E)

        self.btn_to_dataset = ttk.Button(
            self.btn_to_dataset_pulse_frame,
            text="Dalej → Integracje i dataset",
            command=self.go_to_substep_3,
            state=tk.DISABLED
        )
        self.btn_to_dataset.pack()
        self.btn_to_dataset.configure(padding=(10, 2))

        # =========================
        # HELP BINDS
        # =========================
        HELP.bind_help(self.btn_run_detection, "t2_fast_test")
        HELP.bind_help(self.btn_rank_presets, "t2_rank")
        HELP.bind_help(self.det_method_combo, "t2_method")
        HELP.bind_help(self.det_device_combo, "t2_device")
        HELP.bind_help(self.btn_ocr_lab, "t2_lab_btn")
        HELP.bind_help(self.yolo_model_row, "t2_yolo_model")
        HELP.bind_help(self.yolo_tuning_lf, "t2_yolo_tuning")
        HELP.bind_help(self.btn_toggle_detection_log, "t2_cut_logs")
        HELP.bind_help(self.plates_listbox, "t2_listbox")
        HELP.bind_help(self.preview_canvas, "t2_canvas")
        HELP.bind_help(self.preview_dir_hint_lbl, "t2_preview_run")
        HELP.bind_help(self.preview_dir_entry, "t2_preview_run")
        HELP.bind_help(self.preview_dir_browse_btn, "t2_preview_run")
        HELP.bind_help(self.preview_mode_lf, "t2_preview_mode")
        HELP.bind_help(self.preview_info_lbl, "t2_preview_info")
        HELP.bind_help(self.preview_fusion_info_lbl, "t2_preview_info")

        self._bind_scroll_canvas_children(
            self.detect_right_content,
            self.detect_right_canvas,
            self._detect_right_canvas_overflows
        )
        self.frame.after_idle(self._sync_detect_right_scrollregion)
        self.frame.after_idle(self._sync_detect_right_canvas_width)
        self.frame.after_idle(self._init_preview_vertical_split)
        self.frame.bind_all("<MouseWheel>", self._on_detect_right_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_detect_right_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_detect_right_global_mousewheel, add="+")

    def _run_detection_stage(self):
        method = self._get_detection_method_key()

        if method in ("YOLO", "BOTH"):
            try:
                yolo_runtime = self._get_yolo_runtime_settings()
            except Exception as e:
                messagebox.showwarning("Bledne parametry YOLO", str(e))
                return

            try:
                resolved_model = self._ensure_yolo_model_checkpoint()
                self.yolo_model_path_var.set(resolved_model)
                version, size = self._infer_yolo_arch_from_model_path(resolved_model)
                model_name = Path(resolved_model).name
                model_desc = f"{model_name} (YOLOv{version}{size})" if version and size else model_name

                self._log(
                    self.test_log_text,
                    f"[INFO] Model detekcji znakow: {model_desc}",
                    "INFO"
                )
                self._log(
                    self.test_log_text,
                    f"[INFO] Model gotowy do użycia: {resolved_model}",
                    "INFO"
                )
                self._log(
                    self.test_log_text,
                    "[INFO] Urzadzenie: "
                    f"{self._normalize_selected_device()} | "
                    f"YOLO={self._device_to_ultralytics(self.yolo_device_var.get())} | "
                    f"OCR={self._device_to_ocr(self.yolo_device_var.get())}",
                    "INFO"
                )
                self._log(
                    self.test_log_text,
                    "[INFO] Parametry YOLO: "
                    f"conf={yolo_runtime['conf']:.2f}, "
                    f"nms_iou={yolo_runtime['iou']:.2f}, "
                    f"overlap={yolo_runtime['overlap']:.2f}, "
                    f"agnostic_nms={yolo_runtime['agnostic_nms']}, "
                    f"seq_y={yolo_runtime['seq_center_y']:.2f}, "
                    f"seq_h_min={yolo_runtime['seq_min_h']:.2f}, "
                    f"seq_h_max={yolo_runtime['seq_max_h']:.2f}, "
                    f"seq_w_max={yolo_runtime['seq_max_w']:.2f}, "
                    f"seq_soft={yolo_runtime['seq_soft_overlap']:.2f}, "
                    f"seq_hard={yolo_runtime['seq_hard_overlap']:.2f}",
                    "INFO"
                )
            except Exception as e:
                messagebox.showwarning(
                    "Błąd modelu YOLO",
                    f"Nie udało się przygotować modelu YOLO:\n{e}"
                )
                self._log(self.test_log_text, f"[ERROR] {e}", "ERROR")
                return

        self._run_fast_ocr_test()

    def _update_winner_label(self):
        best_preset_data, best_acc = self._get_best_preset()
        if best_preset_data and best_preset_data.get("name"):
            name = best_preset_data.get("name")
            self._set_winner_name(f"Lider: {name.upper()} .json", "success")
            self._set_winner_acc(f" Skuteczność najlepszego presetu: {best_acc:.1f}% ", "success")
        else:
            self._set_winner_name("BRAK DANYCH Z TURNIEJU", "neutral")
            self._set_winner_acc("Skuteczność detekcji OCR: 0.0%", "error")

    # =========================================================
    # Preview load + render
    # =========================================================
    def _load_preview_data(self, quiet=False):
        out_dir = Path(self.preview_dir_var.get().strip())
        meta_path = out_dir / "metadata.json"

        try:
            self.frame.after(0, self._update_winner_label)
        except Exception:
            pass

        if not meta_path.exists():
            if not quiet:
                messagebox.showerror("Brak pliku", f"Nie znaleziono metadata.json w folderze:\n{out_dir}")
            try:
                self._set_preview_info("Brak wczytanych danych", "error")
                self._set_preview_counts_info(0, 0, 0)
                self._set_preview_box_info("Tryb boxow: brak wczytanych danych", "muted")
            except Exception:
                pass
            return

        try:
            current_mtime = meta_path.stat().st_mtime
            need_reload = (
                self._loaded_meta_path != meta_path
                or self._loaded_meta_mtime != current_mtime
            )

            if (not self.preview_metadata) or (not quiet) or need_reload:
                with open(meta_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)

                if not isinstance(loaded, dict):
                    loaded = {}

                changed = False
                for pid, d in loaded.items():
                    if not isinstance(d, dict):
                        continue
                    if "status" not in d:
                        d["status"] = "unknown"
                        changed = True
                    if "characters" not in d or not isinstance(d.get("characters"), list):
                        d["characters"] = []
                        changed = True
                    else:
                        sorted_chars = self._sort_character_records_by_x(d.get("characters", []))
                        if sorted_chars != d.get("characters", []):
                            d["characters"] = sorted_chars
                            changed = True
                    for yolo_key in ("yolo_detections", "yolo_nms_detections", "yolo_raw_detections"):
                        if yolo_key not in d:
                            continue
                        if not isinstance(d.get(yolo_key), list):
                            d[yolo_key] = []
                            changed = True
                            continue
                        sorted_yolo = self._sort_character_records_by_x(d.get(yolo_key, []))
                        if sorted_yolo != d.get(yolo_key, []):
                            d[yolo_key] = sorted_yolo
                            changed = True

                if changed:
                    self._atomic_write_json(meta_path, loaded)
                    current_mtime = meta_path.stat().st_mtime

                self.preview_metadata = loaded
                self._loaded_meta_path = meta_path
                self._loaded_meta_mtime = current_mtime

            self._apply_preview_metadata_update(self.preview_metadata, preserve_selection=True)
            self._sync_step3_access_from_preview_state(self.preview_metadata)

            try:
                self.frame.after(100, self._update_winner_label)
            except Exception:
                pass

        except Exception as e:
            if not quiet:
                messagebox.showerror("Błąd odświeżania listy", str(e))
            logger.error(f"Błąd _load_preview_data: {e}")
        finally:
            self._reloading_preview = False

        try:
            if self.preview_plate_ids and self.plates_listbox.curselection():
                self.frame.after_idle(lambda: self._on_preview_select(None))
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć preview po _load_preview_data: {e}")


    def _refresh_listbox_rows_from_metadata(self):
        """Pełne odświeżenie listy i preview na podstawie aktualnego self.preview_metadata."""
        if not hasattr(self, "plates_listbox"):
            return

        try:
            self._apply_preview_metadata_update(self.preview_metadata, preserve_selection=True)
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć listy tablic: {e}")

        try:
            if self._listbox_pid_by_index and self.plates_listbox.curselection():
                self.frame.after_idle(lambda: self._on_preview_select(None))
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć preview po _refresh_listbox_rows_from_metadata: {e}")

    def _on_preview_select(self, event=None):
        """Podgląd tablicy + bboxy znaków."""
        if not PIL_AVAILABLE:
            return

        # jeśli akurat przebudowujemy listę - nie renderujemy
        if getattr(self, "_reloading_preview", False):
            return

        pid_map = getattr(self, "_listbox_pid_by_index", [])
        sel = self.plates_listbox.curselection()
        if not sel:
            try:
                active_idx = int(self.plates_listbox.index(tk.ACTIVE))
            except Exception:
                active_idx = -1

            if 0 <= active_idx < len(pid_map):
                try:
                    self.plates_listbox.selection_clear(0, tk.END)
                    self.plates_listbox.selection_set(active_idx)
                    self.plates_listbox.activate(active_idx)
                    self.plates_listbox.see(active_idx)
                except Exception:
                    pass
                sel = (active_idx,)
            else:
                self._update_preview_box_info_label()
                return

        try:
            idx = int(sel[0])
        except Exception:
            return

        if not (0 <= idx < len(pid_map)):
            return

        pid = pid_map[idx]
        data = self.preview_metadata.get(pid, {})
        if pid != self._preview_active_pid:
            self._preview_active_pid = pid
            self._reset_preview_view_state()
            self._preview_active_pid = pid
        box_chars, box_source = self._get_preview_box_records(data)
        yolo_variants = self._get_preview_box_variants(data)
        yolo_raw_count = len(yolo_variants.get("YOLO_RAW", []))
        yolo_nms_count = len(yolo_variants.get("YOLO_NMS", []))
        yolo_filtered_count = len(yolo_variants.get("YOLO_FILTERED", []))
        self._update_preview_box_info_label(
            plate_id=pid,
            mode_key=box_source,
            shown_count=len(box_chars),
            yolo_raw_count=yolo_raw_count,
            yolo_nms_count=yolo_nms_count,
            yolo_filtered_count=yolo_filtered_count,
        )
        display_text = self._format_plate_listbox_label(pid, data)

        # Jeśli tekst listy jest nieaktualny, zsynchronizuj go z bieżącym metadata.
        try:
            row_text = self.plates_listbox.get(idx)
        except Exception:
            row_text = None

        if row_text != display_text:
            try:
                self._reloading_preview = True
                self.plates_listbox.delete(idx)
                self.plates_listbox.insert(idx, display_text)

                status = str(data.get("status", "unknown")).strip().lower()
                if hasattr(self, "_apply_plate_listbox_row_style"):
                    self._apply_plate_listbox_row_style(idx, status)
                else:
                    if status == "perfect":
                        self.plates_listbox.itemconfig(idx, foreground="#27ae60")
                    elif status == "needs_fix":
                        self.plates_listbox.itemconfig(idx, foreground="#c0392b")
                    else:
                        self.plates_listbox.itemconfig(idx, foreground="#444444")

                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(idx)
                self.plates_listbox.activate(idx)
                self.plates_listbox.see(idx)
            finally:
                self._reloading_preview = False

        img_path = Path(self.preview_dir_var.get().strip()) / "images" / f"{pid}.jpg"

        self.preview_canvas.delete("all")
        self._preview_render_state = {}
        self._preview_badge_runtime = {}
        if not img_path.exists():
            self._set_preview_box_info(f"{pid} | {self._get_preview_box_mode_label(box_source)} | brak obrazu podgladu", "error")
            return

        try:
            pil_img = Image.open(img_path)
            orig_w, orig_h = pil_img.size

            c_w = max(50, self.preview_canvas.winfo_width())
            c_h = max(50, self.preview_canvas.winfo_height())

            info_bar_height = 32
            margin_x = max(84, int(c_w * 0.18))
            badge_plan_specs = []
            estimated_image_width = max(80, min(c_w - margin_x, int(c_w * 0.78)))
            for box_idx, c in enumerate(box_chars):
                if not isinstance(c, dict):
                    continue

                bbox = c.get("bbox", [0, 0, 0, 0])
                if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                    continue

                x1, _y1, x2, _y2 = bbox[:4]
                center_ratio = ((float(x1) + float(x2)) * 0.5) / max(1.0, float(orig_w))
                source_tag = self._get_character_source_tag(c, data=data, fallback_index=box_idx)
                source_style = self._get_preview_source_visual_style(source_tag)
                is_yolo_box = source_tag in ("yolo", "yolo_rescue") or str(c.get("method", "")).strip().lower() == "yolo"

                badge_text = source_style["label"]
                if is_yolo_box:
                    try:
                        badge_text = f"{source_style['label']} {float(c.get('confidence', 0.0)):.2f}"
                    except Exception:
                        badge_text = source_style["label"]

                badge_plan_specs.append({
                    "center_ref": center_ratio,
                    "text": badge_text,
                })

            estimated_badge_rows, estimated_badge_height = self._estimate_preview_badge_layout(
                self.preview_canvas,
                badge_plan_specs,
                estimated_image_width,
            )
            badge_metrics = self._get_preview_badge_layout_metrics()
            box_label_clearance = max(
                52,
                10 + (estimated_badge_rows * estimated_badge_height) + (max(0, estimated_badge_rows - 1) * badge_metrics["row_gap"])
            )
            margin_y_top = max(info_bar_height + box_label_clearance, int(c_h * 0.18))
            margin_y_bottom = max(128, int(c_h * 0.26))

            for _ in range(2):
                usable_w = max(80, min(c_w - margin_x, int(c_w * 0.78)))
                usable_h = max(60, c_h - (margin_y_top + margin_y_bottom))

                scale_w = usable_w / float(orig_w)
                scale_h = usable_h / float(orig_h)
                SCALE = max(1.0, min(min(scale_w, scale_h), 5.0))

                new_w, new_h = int(orig_w * SCALE), int(orig_h * SCALE)
                reevaluated_rows, reevaluated_badge_height = self._estimate_preview_badge_layout(
                    self.preview_canvas,
                    badge_plan_specs,
                    max(80, new_w),
                )
                required_clearance = max(
                    52,
                    10 + (reevaluated_rows * reevaluated_badge_height) + (max(0, reevaluated_rows - 1) * badge_metrics["row_gap"])
                )
                if required_clearance <= box_label_clearance:
                    break
                box_label_clearance = required_clearance
                margin_y_top = max(info_bar_height + box_label_clearance, int(c_h * 0.18))

            fit_scale = float(SCALE)
            fit_new_w = int(orig_w * fit_scale)
            fit_new_h = int(orig_h * fit_scale)
            fit_x_off = (c_w - fit_new_w) / 2.0
            fit_y_off = (c_h - fit_new_h - margin_y_bottom + margin_y_top) / 2.0
            fit_y_off = max(float(info_bar_height + box_label_clearance), fit_y_off)

            self._preview_zoom_level = max(self._preview_zoom_min, min(self._preview_zoom_max, float(self._preview_zoom_level)))
            render_scale = fit_scale * float(self._preview_zoom_level)
            new_w = max(1, int(orig_w * render_scale))
            new_h = max(1, int(orig_h * render_scale))
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            self._current_photo = ImageTk.PhotoImage(pil_img)
            base_x_off = fit_x_off - ((new_w - fit_new_w) / 2.0)
            base_y_off = fit_y_off - ((new_h - fit_new_h) / 2.0)
            top_reserved = float(info_bar_height + box_label_clearance)
            x_off = base_x_off + float(self._preview_pan_x)
            y_off = base_y_off + float(self._preview_pan_y)
            x_off, y_off = self._clamp_preview_image_position(
                x_off,
                y_off,
                image_w=new_w,
                image_h=new_h,
                canvas_w=c_w,
                canvas_h=c_h,
                top_reserved=top_reserved,
            )
            self._preview_pan_x = float(x_off - base_x_off)
            self._preview_pan_y = float(y_off - base_y_off)
            self._preview_render_state = {
                "plate_id": pid,
                "orig_w": float(orig_w),
                "orig_h": float(orig_h),
                "fit_scale": float(fit_scale),
                "scale": float(render_scale),
                "fit_new_w": float(fit_new_w),
                "fit_new_h": float(fit_new_h),
                "fit_x_off": float(fit_x_off),
                "fit_y_off": float(fit_y_off),
                "top_reserved": float(top_reserved),
                "info_bar_height": float(info_bar_height),
                "image_left": float(x_off),
                "image_top": float(y_off),
                "image_right": float(x_off + new_w),
                "image_bottom": float(y_off + new_h),
            }

            self.preview_canvas.create_image(x_off, y_off, anchor=tk.NW, image=self._current_photo)

            self._preview_badge_runtime = {}
            badge_specs = []
            image_bottom_y = y_off + new_h
            self._draw_preview_canvas_info_overlay(
                self.preview_canvas,
                c_w,
                data=data,
                box_chars=box_chars,
                has_boxes=bool(box_chars),
            )

            # rysowanie bboxów + znaków
            for box_idx, c in enumerate(box_chars):
                if not isinstance(c, dict):
                    continue

                bbox = c.get("bbox", [0, 0, 0, 0])
                if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                    continue

                x1, y1, x2, y2 = bbox[:4]
                cx1, cy1 = (float(x1) * render_scale) + x_off, (float(y1) * render_scale) + y_off
                cx2, cy2 = (float(x2) * render_scale) + x_off, (float(y2) * render_scale) + y_off

                center_x = cx1 + (cx2 - cx1) / 2
                source_tag = self._get_character_source_tag(c, data=data, fallback_index=box_idx)
                source_style = self._get_preview_source_visual_style(source_tag)
                is_yolo_box = source_tag in ("yolo", "yolo_rescue") or str(c.get("method", "")).strip().lower() == "yolo"
                box_color = source_style["outline"]
                guide_color = source_style["guide"]
                char_fill = source_style["char"]

                box_id = self.preview_canvas.create_rectangle(
                    cx1, cy1, cx2, cy2,
                    outline=box_color,
                    width=2
                )

                badge_text = source_style["label"]
                if is_yolo_box:
                    try:
                        badge_text = f"{source_style['label']} {float(c.get('confidence', 0.0)):.2f}"
                    except Exception:
                        badge_text = source_style["label"]
                badge_specs.append({
                    "badge_key": f"{box_source}:{box_idx}",
                    "center_x": center_x,
                    "box_top_y": cy1,
                    "box_id": box_id,
                    "box_color": box_color,
                    "text": badge_text,
                    "fill_color": box_color,
                    "outline_color": box_color,
                    "text_color": self._get_readable_text_color(box_color, preferred=source_style["badge_fg"]),
                    "guide_color": guide_color,
                })

                text_anchor_y = min(c_h - 24, image_bottom_y + 35)
                self.preview_canvas.create_line(
                    center_x, cy2,
                    center_x, text_anchor_y - 20,
                    fill=guide_color,
                    dash=(2, 2)
                )

                char_text = str(c.get("character", ""))
                self.preview_canvas.create_text(
                    center_x + 1, text_anchor_y + 1,
                    text=char_text,
                    fill="#000000",
                    font=("Segoe UI", 18, "bold"),
                    anchor=tk.CENTER
                )
                self.preview_canvas.create_text(
                    center_x, text_anchor_y,
                    text=char_text,
                    fill=char_fill,
                    font=("Segoe UI", 18, "bold"),
                    anchor=tk.CENTER
                )

            self._draw_preview_top_badges(
                self.preview_canvas,
                badge_specs,
                image_left=x_off,
                image_right=x_off + new_w,
                image_top=y_off,
                top_limit=info_bar_height + 6,
            )
            self._apply_preview_badge_selection_style()
            self.preview_canvas.create_text(
                10,
                max(14, c_h - 10),
                text="Podgląd tablicy",
                fill=getattr(self.app, "palette", {}).get("muted", "#b0b0b0"),
                font=("Segoe UI", 8, "bold"),
                anchor=tk.SW
            )

        except Exception as e:
            logger.error(f"Błąd wyświetlania podglądu tablicy: {e}")

    # =========================================================
    # Fast test UI lock/unlock
    # =========================================================

    def _lock_ui_for_testing(self):
        self.is_processing = True

        # główne akcje
        for attr_name in ("btn_run_detection", "btn_rank_presets", "btn_ocr_lab"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.config(state=tk.DISABLED)
                except Exception:
                    pass

        # na czas detekcji blokujemy też nawigację workflow
        for attr_name in ("btn_to_detect", "btn_to_dataset"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.config(state=tk.DISABLED)
                except Exception:
                    pass

        # lista tablic ma być zablokowana tylko na czas testu
        try:
            self.plates_listbox.config(state=tk.DISABLED)
        except Exception:
            pass

        # zdejmij podświetlenie głównej akcji na czas pracy
        try:
            self._set_button_emphasis("btn_run_detection_frame", False)
        except Exception:
            pass

    def _unlock_ui_after_testing(self):
        # NAJWAŻNIEJSZE: kończymy stan "processing"
        self.is_processing = False
        self.fast_test_running = False

        try:
            self.fast_test_stop.clear()
        except Exception:
            pass

        # lista tablic ma znowu działać zawsze po zakończeniu testu
        try:
            self.plates_listbox.config(state=tk.NORMAL)
        except Exception:
            pass

        # przyciski operacyjne
        for attr_name in ("btn_run_detection", "btn_rank_presets", "btn_ocr_lab"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.config(state=tk.NORMAL)
                except Exception:
                    pass

        # odśwież blokady/odblokowania pól ścieżek zgodnie z aktualnym trybem
        try:
            self._update_preview_path_lock()
        except Exception:
            pass

        try:
            self._update_step3_source_path_lock()
        except Exception:
            pass

        try:
            self._update_yolo_visibility()
        except Exception:
            pass

        # różne zachowanie dla kampanii i trybu swobodnego
        in_campaign = bool(getattr(self, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

        if not in_campaign:
            # w trybie swobodnym wszystko ma działać
            for attr_name in ("btn_to_detect", "btn_to_dataset"):
                widget = getattr(self, attr_name, None)
                if widget is not None:
                    try:
                        widget.config(state=tk.NORMAL)
                    except Exception:
                        pass

            try:
                self._set_subtab_state(self.tab_extract, "normal")
                self._set_subtab_state(self.tab_detect, "normal")
                self._set_subtab_state(self.tab_dataset, "normal")
            except Exception:
                pass
        else:
            # w kampanii zostawiamy workflow tak, jak ustawiły go wcześniejsze kroki
            pass

        try:
            self.test_progress.update_idletasks()
        except Exception:
            pass
    # =========================================================
    # FAST OCR TEST (stable)
    # =========================================================

    def _run_fast_ocr_test(self):
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj paczkę!")

        if self.fast_test_running:
            return

        self._force_save_all()
        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        session_token = self._project_reset_token

        self.test_log_text.delete(1.0, tk.END)
        self._lock_ui_for_testing()
        self._set_test_status("Start detekcji...", "info")
        self.test_progress.config(value=0)
        self._set_test_progress_counter(0, len(self.preview_plate_ids), perfect_count=0)

        self.fast_test_stop.clear()
        self.fast_test_running = True

        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "START - Szybki Test Celności\n", "HEADER")

        method_str = self._get_detection_method_key().strip().lower()
        try:
            method = DetectionMethod(method_str)
        except Exception:
            method = DetectionMethod.OCR

        yolo_model = None
        if method in [DetectionMethod.YOLO, DetectionMethod.BOTH] and YOLO is not None:
            try:
                effective_model_path = self._get_effective_yolo_model_path()
                if not effective_model_path:
                    raise RuntimeError("Brak aktywnej ścieżki modelu YOLO dla detekcji znaków.")
                yolo_model = YOLO(str(effective_model_path))
            except Exception as e:
                self._log(self.test_log_text, f"Błąd YOLO: {e}", "ERROR")
                yolo_model = None

        prep_params = self._get_current_prep_params()
        ocr_engine = None
        if method in [DetectionMethod.OCR, DetectionMethod.BOTH]:
            try:
                ocr_device = self._device_to_ocr(self.yolo_device_var.get())
                ocr_engine = PlateOCR(
                    device=ocr_device,
                    confidence_threshold=self.ocr_conf_var.get()
                )
                ocr_engine.custom_prep_params = prep_params
            except Exception as e:
                self._log(self.test_log_text, f"Błąd OCR Engine: {e}", "ERROR")
                ocr_engine = None

        try:
            yolo_runtime = self._get_yolo_runtime_settings()
        except Exception as e:
            self._log(self.test_log_text, f"Błąd parametrów YOLO: {e}", "ERROR")
            yolo_runtime = {
                "conf": 0.25,
                "iou": 0.45,
                "overlap": 0.70,
                "agnostic_nms": False,
                "seq_center_y": 0.60,
                "seq_min_h": 0.55,
                "seq_max_h": 1.80,
                "seq_max_w": 2.60,
                "seq_soft_overlap": 0.18,
                "seq_hard_overlap": 0.30,
            }

        detector = CharacterDetector(
            method=method,
            ocr_engine=ocr_engine,
            yolo_model=yolo_model,
            yolo_device=self._device_to_ultralytics(self.yolo_device_var.get()),
            yolo_confidence=yolo_runtime["conf"],
            yolo_iou=yolo_runtime["iou"],
            yolo_agnostic_nms=yolo_runtime["agnostic_nms"],
            yolo_overlap_threshold=yolo_runtime["overlap"],
            yolo_sequence_center_y_tolerance=yolo_runtime["seq_center_y"],
            yolo_sequence_min_height_ratio=yolo_runtime["seq_min_h"],
            yolo_sequence_max_height_ratio=yolo_runtime["seq_max_h"],
            yolo_sequence_max_width_ratio=yolo_runtime["seq_max_w"],
            yolo_sequence_soft_overlap=yolo_runtime["seq_soft_overlap"],
            yolo_sequence_hard_overlap=yolo_runtime["seq_hard_overlap"],
        )

        def worker():
            local_meta = dict(self.preview_metadata) if isinstance(self.preview_metadata, dict) else {}
            total = len(self.preview_plate_ids)
            stat_perfect = 0
            yolo_raw_total = 0
            yolo_nms_total = 0
            yolo_filtered_total = 0

            try:
                for idx, pid in enumerate(self.preview_plate_ids):
                    if self.fast_test_stop.is_set() or session_token != self._project_reset_token:
                        break

                    img_path = imgs_dir / f"{pid}.jpg"
                    if not img_path.exists():
                        self.frame.after(
                            0,
                            lambda c=idx + 1, t=total, p=stat_perfect, token=session_token: self._update_detection_progress_ui(c, t, perfect_count=p, session_token=token)
                        )
                        continue

                    img = cv2.imread(str(img_path))
                    if img is None:
                        self.frame.after(
                            0,
                            lambda c=idx + 1, t=total, p=stat_perfect, token=session_token: self._update_detection_progress_ui(c, t, perfect_count=p, session_token=token)
                        )
                        continue

                    if pid not in local_meta or not isinstance(local_meta.get(pid), dict):
                        local_meta[pid] = {}

                    source_image = local_meta[pid].get("source_image", "") or ""
                    true_texts = self._get_true_texts_from_filename(source_image)

                    chars = detector.detect(img)
                    if session_token != self._project_reset_token:
                        break

                    ocr_chars = self._sort_character_records_by_x(list(getattr(detector, "last_ocr_detections", [])))
                    yolo_chars = self._sort_character_records_by_x(list(getattr(detector, "last_yolo_detections", [])))
                    chars, fusion_strategy, fusion_details = self._resolve_canonical_detections(
                        method,
                        chars,
                        ocr_chars,
                        yolo_chars,
                        true_texts,
                        hybrid_rescue_max_chars=self._get_hybrid_rescue_max_chars(),
                        prefer_yolo_box_positions=(method == DetectionMethod.BOTH and self._use_hybrid_yolo_box_backend()),
                    )

                    c_clean = self._serialize_character_records(
                        chars,
                        fusion_strategy=fusion_strategy,
                        fusion_details=fusion_details,
                    )
                    yolo_clean = self._serialize_character_records(getattr(detector, "last_yolo_detections", []))
                    yolo_nms_clean = self._serialize_character_records(getattr(detector, "last_yolo_nms_detections", []))
                    yolo_raw_clean = self._serialize_character_records(getattr(detector, "last_yolo_raw_detections", []))

                    yolo_raw_total += len(getattr(detector, "last_yolo_raw_detections", []))
                    yolo_nms_total += len(getattr(detector, "last_yolo_nms_detections", []))
                    yolo_filtered_total += len(getattr(detector, "last_yolo_detections", []))

                    # WAŻNE: sortujemy znaki po X PRZED zapisem do metadata

                    local_meta[pid]["characters"] = c_clean
                    local_meta[pid]["yolo_detections"] = yolo_clean
                    local_meta[pid]["yolo_nms_detections"] = yolo_nms_clean
                    local_meta[pid]["yolo_raw_detections"] = yolo_raw_clean
                    local_meta[pid]["fusion_strategy"] = str(fusion_strategy or "")
                    if isinstance(fusion_details, dict) and fusion_details:
                        local_meta[pid]["fusion_details"] = fusion_details
                    else:
                        local_meta[pid].pop("fusion_details", None)

                    if fusion_strategy == "yolo_exact":
                        self._log(
                            self.test_log_text,
                            f"[HYBRID] {pid}: YOLO trafilo idealnie i przejelo finalne boxy.",
                            "INFO"
                        )
                    elif fusion_strategy == "ocr_yolo_rescue":
                        repaired_text = self._characters_to_text(c_clean)
                        ocr_text = ""
                        if isinstance(fusion_details, dict):
                            ocr_text = str(fusion_details.get("ocr_text", "") or "")
                        self._log(
                            self.test_log_text,
                            f"[HYBRID] {pid}: OCR=[{ocr_text}] -> naprawa YOLO -> [{repaired_text}]",
                            "INFO"
                        )

                    if isinstance(fusion_details, dict) and int(fusion_details.get("box_backend_count", 0) or 0) > 0:
                        self._log(
                            self.test_log_text,
                            f"[HYBRID] {pid}: YOLO poprawilo pozycje {int(fusion_details.get('box_backend_count', 0))} boxow.",
                            "INFO"
                        )

                    if c_clean:
                        txt = "".join(str(c.get("character", "")) for c in c_clean)
                        if txt in true_texts:
                            local_meta[pid]["status"] = "perfect"
                            stat_perfect += 1
                            self._log(self.test_log_text, f"✅ [{idx+1:03d}/{total}] {pid}: {txt}", "SUCCESS")
                        else:
                            local_meta[pid]["status"] = "needs_fix"
                            expected_str = " / ".join(true_texts) if true_texts else "Brak"
                            self._log(
                                self.test_log_text,
                                f"❌ [{idx+1:03d}/{total}] {pid}: Odczyt=[{txt}] (Oczek: [{expected_str}])",
                                "ERROR"
                            )
                    else:
                        local_meta[pid]["status"] = "needs_fix"
                        self._log(
                            self.test_log_text,
                            f"❌ [{idx+1:03d}/{total}] {pid}: NIC NIE ZNALEZIONO",
                            "ERROR"
                        )

                    self.frame.after(
                        0,
                        lambda c=idx + 1, t=total, p=stat_perfect, token=session_token: self._update_detection_progress_ui(c, t, perfect_count=p, session_token=token)
                    )

                if session_token != self._project_reset_token:
                    return

                meta_file = out_dir / "metadata.json"
                self._atomic_write_json(meta_file, local_meta)

                plates_with_chars = sum(
                    1 for pid in self.preview_plate_ids
                    if isinstance(local_meta.get(pid), dict) and local_meta[pid].get("characters")
                )
                self._log(
                    self.test_log_text,
                    f"\n[DIAG] Tablice z wykrytymi znakami: {plates_with_chars}/{total}",
                    "INFO"
                )

                if method in [DetectionMethod.YOLO, DetectionMethod.BOTH]:
                    self._log(
                        self.test_log_text,
                        f"[DIAG] YOLO boxy: raw={yolo_raw_total}, po NMS={yolo_nms_total}, po filtracji={yolo_filtered_total}",
                        "INFO"
                    )

                strategy_counts = self._count_statuses_in_metadata_mapping(local_meta).get("strategy_counts", {})
                self._log(
                    self.test_log_text,
                    "[DIAG] Perfect wg strategii: "
                    f"OCR={int(strategy_counts.get('ocr_exact', 0))}, "
                    f"YOLO={int(strategy_counts.get('yolo_exact', 0))}, "
                    f"rescue={int(strategy_counts.get('ocr_yolo_rescue', 0))}, "
                    f"inne={int(strategy_counts.get('other_perfect', 0))}",
                    "INFO"
                )

                acc = (stat_perfect / total * 100) if total > 0 else 0
                self._log(
                    self.test_log_text,
                    f"\nSkuteczność: {acc:.1f}% ({stat_perfect}/{total} tablic)",
                    "SUCCESS" if acc >= 80 else "WARNING"
                )

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD: {e}", "ERROR")

            finally:
                def finalize():
                    if session_token != self._project_reset_token:
                        return

                    try:
                        self.fast_test_running = False
                        self.fast_test_stop.clear()

                        # Lista musi byc aktywna przed przebudowa, inaczej repaint potrafi opoznic sie
                        # do chwili kolejnej interakcji myszą lub klawiaturą.
                        try:
                            self.plates_listbox.config(state=tk.NORMAL)
                        except Exception:
                            pass

                        # Odśwież listę i preview na podstawie aktualnego metadata.
                        self._apply_preview_metadata_update(local_meta, preserve_selection=True)
                        self._loaded_meta_path = out_dir / "metadata.json"
                        try:
                            self._loaded_meta_mtime = self._loaded_meta_path.stat().st_mtime
                        except Exception:
                            self._loaded_meta_mtime = None

                        try:
                            method_name = self._get_detection_method_key()

                            if method_name == "OCR":
                                self._set_winner_name("Brak zwycięzcy turnieju", "neutral")
                                self._set_winner_acc("Uruchom turniej presetów OCR", "muted")
                            elif method_name == "YOLO":
                                self._set_winner_name("Brak rankingu OCR", "neutral")
                                self._set_winner_acc("Tryb YOLO nie bierze udziału w turnieju OCR", "muted")
                            else:  # BOTH
                                self._set_winner_name("Brak rankingu OCR", "neutral")
                                self._set_winner_acc("Tryb hybrydowy nie ustala zwycięzcy turnieju OCR", "muted")
                        except Exception:
                            pass

                        try:
                            summary_msg = (
                                f"Podsumowanie detekcji: perfect={stat_perfect}/{total}, "
                                f"skuteczność={acc:.1f}%"
                            )
                            self._log(self.test_log_text, summary_msg, "INFO")
                        except Exception:
                            pass

                        self.test_progress.config(value=100)
                        self._set_test_progress_counter(total, total, perfect_count=stat_perfect)
                        self._set_test_status(
                            f"Zakończono detekcję — skuteczność {acc:.1f}%",
                            "success"
                        )

                        try:
                            self.frame.update_idletasks()
                        except Exception:
                            pass

                        # 7. odblokuj dalszy krok
                        self.unlock_dataset_subtab()

                        # 7. odblokuj dalszy krok
                        self.unlock_dataset_subtab()

                    except Exception as e:
                        logger.error(f"Błąd finalize() po Szybkim Teście: {e}")
                        self._set_test_status("Błąd odświeżania UI", "error")

                    finally:
                        self._unlock_ui_after_testing()

                self.frame.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 3: CVAT + YOLO exports/imports
    # =========================================================

    def _build_cvat_tab(self, parent):
        palette = getattr(self.app, "palette", {})

        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        export_host = ttk.Frame(pane)
        export_host.grid_rowconfigure(0, weight=1)
        export_host.grid_columnconfigure(0, weight=1)
        pane.add(export_host, weight=1)

        self.cvat_export_canvas = tk.Canvas(
            export_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.cvat_export_canvas.grid(row=0, column=0, sticky="nsew")

        self.cvat_export_scrollbar = WebSlimScrollbar(
            export_host,
            command=self.cvat_export_canvas.yview
        )
        self.cvat_export_scrollbar.grid(row=0, column=1, sticky="ns")
        self.cvat_export_canvas.configure(yscrollcommand=self.cvat_export_scrollbar.set)

        self.cvat_export_content = ttk.Frame(self.cvat_export_canvas)
        self.cvat_export_content_window = self.cvat_export_canvas.create_window(
            (0, 0),
            window=self.cvat_export_content,
            anchor="nw"
        )
        self.cvat_export_content.bind("<Configure>", self._sync_cvat_export_scrollregion, add="+")
        self.cvat_export_canvas.bind("<Configure>", self._sync_cvat_export_canvas_width, add="+")

        export_lf = ttk.LabelFrame(self.cvat_export_content, text=" Eksporty (dane wyjściowe) ", padding=15)
        export_lf.pack(fill=tk.BOTH, expand=True)

        cvat_f = ttk.Frame(export_lf)
        cvat_f.pack(fill=tk.X, pady=(5, 5))
        self.cvat_option1_title_lbl = tk.Label(
            cvat_f,
            text="OPCJA 1: Ręczna poprawa błędów",
            anchor="w",
            justify="left",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option1_title_lbl.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.cvat_option1_title_lbl, tone="error", emphasis=True)
        self.cvat_option1_desc_lbl = tk.Label(
            export_lf,
            text="Eksport do CVAT obejmuje wyłącznie tablice oznaczone jako błędne (czerwone).",
            wraplength=320,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option1_desc_lbl.pack(anchor=tk.W, pady=(0, 8))
        self._set_inline_status_label_state(self.cvat_option1_desc_lbl, tone="muted", emphasis=False)



        btn_cvat = ttk.Button(cvat_f, text="WYGENERUJ .ZIP DLA CVAT", command=self._run_cvat_export, style="Accent.TButton")
        btn_cvat.pack(fill=tk.X, pady=(5, 0), ipady=3)

        ttk.Separator(export_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)

        yolo_f = ttk.Frame(export_lf)
        yolo_f.pack(fill=tk.X, pady=(0, 5))
        self.cvat_option2_title_lbl = tk.Label(
            yolo_f,
            text="OPCJA 2: Budowa datasetu (active learning)",
            anchor="w",
            justify="left",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option2_title_lbl.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.cvat_option2_title_lbl, tone="success", emphasis=True)
        self.cvat_option2_desc_lbl = tk.Label(
            yolo_f,
            text="Zbiera perfekcyjne tablice i buduje dataset YOLO.",
            wraplength=320,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.cvat_option2_desc_lbl.pack(anchor=tk.W, pady=(2, 8))
        self._set_inline_status_label_state(self.cvat_option2_desc_lbl, tone="muted", emphasis=False)

        self.gold_export_filters_lf = ttk.LabelFrame(yolo_f, text=" Źródła perfect do gold packa ", padding=8)
        self.gold_export_filters_lf.pack(fill=tk.X, pady=(0, 8))

        self.gold_export_filter_rows = []
        for bucket_key, filter_label, filter_var in (
            ("ocr_exact", PERFECT_STRATEGY_LABELS["ocr_exact"], self.gold_include_ocr_exact_var),
            ("yolo_exact", PERFECT_STRATEGY_LABELS["yolo_exact"], self.gold_include_yolo_exact_var),
            ("ocr_yolo_rescue", PERFECT_STRATEGY_LABELS["ocr_yolo_rescue"], self.gold_include_ocr_yolo_rescue_var),
            ("other_perfect", PERFECT_STRATEGY_LABELS["other_perfect"], self.gold_include_other_perfect_var),
        ):
            row = tk.Frame(self.gold_export_filters_lf, bd=0, highlightthickness=0, cursor="hand2")
            row.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))
            indicator = tk.Canvas(
                row,
                width=16,
                height=16,
                bd=0,
                highlightthickness=0,
                cursor="hand2"
            )
            indicator.pack(side=tk.LEFT, padx=(0, 6))
            label = tk.Label(
                row,
                text=filter_label,
                anchor="w",
                justify=tk.LEFT,
                bd=0,
                highlightthickness=0,
                cursor="hand2"
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def _toggle_gold_filter(_event=None, target_var=filter_var):
                target_var.set(not bool(target_var.get()))
                self._on_gold_export_filter_change()

            for widget in (row, indicator, label):
                widget.bind("<Button-1>", _toggle_gold_filter)

            row_info = {
                "kind": "check",
                "frame": row,
                "indicator": indicator,
                "label": label,
                "bucket_key": bucket_key,
                "base_label": filter_label,
                "selected_getter": (lambda target_var=filter_var: bool(target_var.get())),
                "hovered": False,
            }
            for widget in (row, indicator, label):
                widget.bind("<Enter>", lambda _event, info=row_info: self._set_selection_row_hover(info, True))
                widget.bind("<Leave>", lambda _event, info=row_info: self._set_selection_row_hover(info, False))
            self.gold_export_filter_rows.append(row_info)
        self._apply_gold_export_filter_check_style()
        self._refresh_gold_export_filter_labels()

        self.gold_export_scope_lbl = tk.Label(
            self.gold_export_filters_lf,
            text="Do gold packa: OCR exact, YOLO exact, OCR + YOLO rescue, Manual / inne perfect",
            justify="left",
            wraplength=320,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.gold_export_scope_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self._set_inline_status_label_state(
            self.gold_export_scope_lbl,
            text="Do gold packa: OCR exact, YOLO exact, OCR + YOLO rescue, Manual / inne perfect",
            tone="muted",
            emphasis=False
        )
        self._refresh_gold_export_scope_label()

        self.gold_export_split_lf = ttk.LabelFrame(yolo_f, text=" Opcjonalny split datasetu ", padding=8)
        self.gold_export_split_lf.pack(fill=tk.X, pady=(8, 8))

        self.gold_export_split_row = tk.Frame(
            self.gold_export_split_lf,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.gold_export_split_row.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))

        self.gold_export_split_indicator = tk.Canvas(
            self.gold_export_split_row,
            width=16,
            height=16,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.gold_export_split_indicator.pack(side=tk.LEFT, padx=(0, 6))

        self.gold_export_split_label = tk.Label(
            self.gold_export_split_row,
            text="Po eksporcie podziel paczke na train / val / test",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.gold_export_split_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _toggle_gold_export_split(_event=None):
            try:
                self.gold_export_split_var.set(not bool(self.gold_export_split_var.get()))
            except Exception:
                self.gold_export_split_var.set(False)
            return "break"

        for widget in (self.gold_export_split_row, self.gold_export_split_indicator, self.gold_export_split_label):
            widget.bind("<Button-1>", _toggle_gold_export_split)

        self.gold_export_split_row_info = {
            "kind": "check",
            "frame": self.gold_export_split_row,
            "indicator": self.gold_export_split_indicator,
            "label": self.gold_export_split_label,
            "selected_getter": lambda: bool(self.gold_export_split_var.get()),
            "hovered": False,
        }
        for widget in (self.gold_export_split_row, self.gold_export_split_indicator, self.gold_export_split_label):
            widget.bind("<Enter>", lambda _event, info=self.gold_export_split_row_info: self._set_selection_row_hover(info, True))
            widget.bind("<Leave>", lambda _event, info=self.gold_export_split_row_info: self._set_selection_row_hover(info, False))
        self._apply_gold_export_split_check_style()

        ratios = ttk.Frame(self.gold_export_split_lf)
        ratios.pack(fill=tk.X)

        ttk.Label(ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
        self.gold_export_train_scale = ttk.Scale(
            ratios,
            from_=50,
            to=90,
            variable=self.gold_export_train_pct_var,
            orient=tk.HORIZONTAL
        )
        self.gold_export_train_scale.grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.gold_export_train_pct_lbl = ttk.Label(ratios, text="80%")
        self.gold_export_train_pct_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
        self.gold_export_val_scale = ttk.Scale(
            ratios,
            from_=5,
            to=45,
            variable=self.gold_export_val_pct_var,
            orient=tk.HORIZONTAL
        )
        self.gold_export_val_scale.grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.gold_export_val_pct_lbl = ttk.Label(ratios, text="10%")
        self.gold_export_val_pct_lbl.grid(row=1, column=2, sticky=tk.W)

        ttk.Label(ratios, text="Test %").grid(row=2, column=0, sticky=tk.W)
        self.gold_export_test_hint_lbl = ttk.Label(ratios, text="liczony automatycznie")
        self.gold_export_test_hint_lbl.grid(row=2, column=1, sticky=tk.W, padx=5)
        self.gold_export_test_pct_lbl = ttk.Label(ratios, text="Test: 10%")
        self.gold_export_test_pct_lbl.grid(row=2, column=2, sticky=tk.W)
        ratios.columnconfigure(1, weight=1)
        self._update_gold_export_split_labels()

        btn_yolo = ttk.Button(yolo_f, text="WYEKSPORTUJ PERFEKCYJNE TABLICE DO YOLO", command=self._run_yolo_gold_export, style="Accent.TButton")
        btn_yolo.pack(fill=tk.X, ipady=4)

        info_lf = ttk.LabelFrame(export_lf, text=" Status i wskazówki ", padding=5)
        info_lf.pack(fill=tk.X, expand=False, pady=(15, 0))
        self.export_console = tk.Text(
            info_lf,
            height=5,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg=palette.get("console_bg", "#252526"),
            fg=palette.get("console_fg", "#f3f3f3"),
            insertbackground=palette.get("console_fg", "#f3f3f3"),
            bd=0
        )
        self.export_console.pack(fill=tk.X, expand=False, padx=5, pady=5)
        self.export_console.insert(tk.END, "Oczekuję na akcję...")
        self.export_console.config(state=tk.DISABLED)

        import_lf = ttk.LabelFrame(pane, text=" Import poprawek znaków z CVAT ", padding=15)
        pane.add(import_lf, weight=1)

        self.cvat_import_title_lbl = tk.Label(
            import_lf,
            text="Importuj poprawki znaków z CVAT",
            anchor="w",
            justify="left",
            bd=0,
            highlightthickness=0
        )
        self.cvat_import_title_lbl.pack(anchor=tk.W)
        self._set_inline_status_label_state(self.cvat_import_title_lbl, tone="default", emphasis=True)
        self.cvat_import_desc_lbl = tk.Label(
            import_lf,
            text=(
                "Ten import służy wyłącznie do wczytywania ręcznie poprawionych "
                "adnotacji znaków z CVAT.\n"
                "Zaimportowane dane zostaną dołączone do puli treningowej modelu znaków. "
                "Wskaż plik *.xml z poprawkami."
            ),
            wraplength=320,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.cvat_import_desc_lbl.pack(anchor=tk.W, pady=(2, 8))
        self._set_inline_status_label_state(self.cvat_import_desc_lbl, tone="muted", emphasis=False)

        row2 = ttk.Frame(import_lf)
        row2.pack(fill=tk.X, pady=5)
        self.import_cvat_xml_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.import_cvat_xml_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wybierz XML", command=lambda: self._pick_file(self.import_cvat_xml_var)).pack(side=tk.RIGHT, padx=(5, 0))

        btn_import = ttk.Button(import_lf, text="Importuj", command=self._run_cvat_import, style="Accent.TButton")
        btn_import.pack(fill=tk.X, pady=(10, 5), ipady=3)

        import_console_lf = ttk.LabelFrame(import_lf, text=" Status importu ", padding=5)
        import_console_lf.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        self.import_console = tk.Text(
            import_console_lf,
            height=4,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg=palette.get("console_bg", "#252526"),
            fg=palette.get("console_fg", "#f3f3f3"),
            insertbackground=palette.get("console_fg", "#f3f3f3"),
            bd=0
        )
        self.import_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.import_console.insert(tk.END, "Oczekuję na plik XML...")
        self.import_console.config(state=tk.DISABLED)

        
        HELP.bind_help(btn_cvat, "btn_export_cvat")
        HELP.bind_help(btn_yolo, "btn_export_yolo")
        HELP.bind_help(self.gold_export_filters_lf, "btn_export_yolo")
        HELP.bind_help(self.gold_export_split_lf, "btn_export_yolo")
        HELP.bind_help(btn_import, "btn_import_cvat")

        self._bind_scroll_canvas_children(
            self.cvat_export_content,
            self.cvat_export_canvas,
            self._cvat_export_canvas_overflows
        )
        self.frame.after_idle(self._sync_cvat_export_scrollregion)
        self.frame.after_idle(self._sync_cvat_export_canvas_width)
        self.frame.bind_all("<MouseWheel>", self._on_cvat_export_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_cvat_export_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_cvat_export_global_mousewheel, add="+")

        nav = ttk.Frame(parent)
        nav.pack(fill=tk.X, padx=15, pady=(0, 10))

        ttk.Button(
            nav,
            text="← Wstecz do Wykrywania i Analizy",
            command=self.back_to_substep_2
        ).pack(side=tk.LEFT)

        self.btn_finish_step3_frame = tk.Frame(nav, bd=0, highlightthickness=0)
        self.btn_finish_step3_frame.pack(side=tk.RIGHT)

        self.btn_finish_step3_pulse_frame = tk.Frame(
            self.btn_finish_step3_frame,
            bd=0,
            highlightthickness=0
        )
        self.btn_finish_step3_pulse_frame.pack(anchor=tk.E)

        self.btn_finish_step3 = ttk.Button(
            self.btn_finish_step3_pulse_frame,
            text="Zakończ krok 3 i wróć do Wizarda",
            command=self._finalize_step3_from_existing_outputs,
            style="Accent.TButton",
            state=tk.DISABLED
        )
        self.btn_finish_step3.pack()

    def _set_console_text(self, console_widget, text):
        console_widget.config(state=tk.NORMAL)
        console_widget.delete(1.0, tk.END)
        console_widget.insert(tk.END, text)
        console_widget.config(state=tk.DISABLED)
        self.frame.update()

    def _pick_file(self, var):
        initial = self.preview_dir_var.get().strip()
        if not initial or not Path(initial).exists():
            initial = str(CONFIG.WORKSPACE_DIR.absolute())
        p = filedialog.askopenfilename(initialdir=initial, filetypes=[("XML", "*.xml")])
        if p:
            var.set(p)

    def _run_cvat_export(self):
        work_dir = Path(self.preview_dir_var.get().strip())

        export_dir = work_dir

        project_review_dir = self._get_project_review_dir()
        if project_review_dir is not None:
            try:
                preview_name = work_dir.name if work_dir.name else "review_pack"
            except Exception:
                preview_name = "review_pack"

            export_dir = project_review_dir / preview_name
            export_dir.mkdir(parents=True, exist_ok=True)
        meta_path = work_dir / "metadata.json"
        out_xml = export_dir / "annotations.xml"
        out_zip = export_dir / "cvat_export.zip"

        self._set_console_text(self.export_console, "⌛ Eksportowanie do CVAT w toku...")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if self.smart_export_var.get():
                filtered = {k: v for k, v in metadata.items() if v.get("status") != "perfect"}
                tmp_meta = work_dir / "temp_meta.json"
                with open(tmp_meta, 'w', encoding='utf-8') as f:
                    json.dump(filtered, f, indent=2, ensure_ascii=False)
                source_meta = tmp_meta
            else:
                source_meta = meta_path

            from ..cvat_tools.cvat_character_exporter import CVATCharacterExporter
            from ..cvat_tools.cvat_zip_manager import CVATZipManager

            if CVATCharacterExporter().export(source_meta, out_xml):
                CVATZipManager.create_cvat_import_zip(out_xml, work_dir / "images", out_zip)
                self._set_console_text(self.export_console, f"✅ Wygenerowano ZIP:\n{out_zip}")
                try:
                    self._log(
                        self.export_console,
                        f"[INFO] Review pack zapisano w katalogu projektu: {export_dir}",
                        "INFO"
                    )
                except Exception:
                    pass
                try:
                    self._update_step3_finish_button_state()
                except Exception:
                    pass

                if self.smart_export_var.get() and source_meta.exists():
                    source_meta.unlink()

        except Exception as e:
            self._set_console_text(self.export_console, f"❌ BŁĄD EKSPORTU CVAT:\n{e}")

    def _run_yolo_gold_export(self):
        selected_buckets = self._get_selected_gold_export_strategy_buckets()
        selected_labels = self._format_selected_gold_export_strategy_labels()

        if not selected_buckets:
            self._set_console_text(
                self.export_console,
                "❌ Nie wybrano żadnej strategii perfect do eksportu gold packa.\n\n"
                "Zaznacz co najmniej jedną z opcji: OCR exact, YOLO exact, OCR + YOLO rescue lub Manual / inne perfect."
            )
            return

        self._set_console_text(
            self.export_console,
            f"⌛ Zbieranie idealnych tablic...\nFiltr strategii: {selected_labels}"
        )

        base_chars_dir = Path(getattr(self, "_campaign_chars_dir", str(CONFIG.DIR_3_CHARS)))

        import datetime, uuid, shutil
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        base_datasets_dir = Path(getattr(self, "_campaign_datasets_dir", str(CONFIG.get_datasets_dir("char"))))
        yolo_out = base_datasets_dir / f"YOLO_MegaDataset_Chars_{timestamp}"
        img_out, lbl_out = yolo_out / "images", yolo_out / "labels"

        try:
            img_out.mkdir(parents=True, exist_ok=True)
            lbl_out.mkdir(parents=True, exist_ok=True)

            char_map = {c: i for i, c in enumerate(CHAR_CLASS_ALPHABET)}
            copied, seen = 0, set()
            total_strategy_counts = self._empty_perfect_strategy_counts()
            copied_strategy_counts = self._empty_perfect_strategy_counts()

            meta_candidates = []
            for meta in base_chars_dir.rglob("metadata.json"):
                run_dir = meta.parent
                if (run_dir / "images").exists():
                    meta_candidates.append(meta)

            meta_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            for meta in meta_candidates:
                run_dir = meta.parent
                with open(meta, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                for pid, data in {k: v for k, v in metadata.items() if v.get("status") == "perfect"}.items():
                    strategy_bucket = self._get_perfect_strategy_bucket(data)
                    total_strategy_counts[strategy_bucket] += 1
                    if strategy_bucket not in selected_buckets:
                        continue

                    uk = f"{data.get('source_image', 'u')}_{int(data.get('source_bbox', [0])[0]//10) if data.get('source_bbox') else 0}"
                    if uk in seen:
                        continue
                    seen.add(uk)

                    img_src = run_dir / "images" / f"{pid}.jpg"
                    if not img_src.exists():
                        continue

                    img = cv2.imread(str(img_src))
                    if img is None:
                        continue

                    ih, iw = img.shape[:2]
                    new_pid = f"mega_{uuid.uuid4().hex[:8]}_{pid}"
                    shutil.copy2(img_src, img_out / f"{new_pid}.jpg")

                    txt = []
                    for c in data.get("characters", []):
                        ch = str(c.get("character", "")).upper()
                        if ch not in char_map:
                            continue
                        x1, y1, x2, y2 = c.get("bbox", [0, 0, 0, 0])
                        xc = max(0.0, min(1.0, ((x1 + x2) / 2.0) / iw))
                        yc = max(0.0, min(1.0, ((y1 + y2) / 2.0) / ih))
                        w = max(0.0, min(1.0, (x2 - x1) / iw))
                        h = max(0.0, min(1.0, (y2 - y1) / ih))
                        txt.append(f"{char_map[ch]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")

                    (lbl_out / f"{new_pid}.txt").write_text("\n".join(txt), encoding="utf-8")
                    copied += 1
                    copied_strategy_counts[strategy_bucket] += 1

            if copied == 0:
                msg = (
                    "❌ NIE UDAŁO SIĘ UTWORZYĆ DATASETU YOLO.\n\n"
                    f"Powód: po filtrze strategii ({selected_labels}) nie znaleziono ani jednej tablicy ze statusem 🟢 perfect.\n\n"
                    f"Dostępne perfect wg strategii:\n{self._format_perfect_strategy_counts(total_strategy_counts)}\n\n"
                    "CO DALEJ:\n"
                    "1. Możesz rozszerzyć zaznaczone strategie w pz3.\n"
                    "2. Możesz wrócić do pz2 i poprawić OCR / Laboratorium.\n"
                    "3. Możesz wykonać eksport do CVAT i później zaimportować poprawki.\n"
                    "4. Możesz też wrócić do wizarda i skorzystać z trybów naprawczych."
                )
                self._set_console_text(self.export_console, msg)

                try:
                    if self._step3_linear_mode and CAMPAIGN.get_active_project_name():
                        CAMPAIGN.set_step3_needs_rework()
                except Exception:
                    pass

                try:
                    self._update_step3_finish_button_state()
                except Exception:
                    pass

                try:
                    self.app.update_status(
                        "Nie utworzono gold packa — pozostajesz w z3/pz3, aby kontynuować pracę.",
                        "warning"
                    )
                except Exception:
                    pass

                return

            yaml_content = f"path: {yolo_out.absolute().as_posix()}\ntrain: images\nval: images\nnc: 36\nnames:\n"
            for char, class_id in char_map.items():
                yaml_content += f"  {class_id}: '{char}'\n"
            (yolo_out / "data.yaml").write_text(yaml_content, encoding="utf-8")

            self._set_console_text(
                self.export_console,
                f"✅ Dataset YOLO gotowy: {yolo_out}\n"
                f"Filtr strategii: {selected_labels}\n"
                f"Wyeksportowano: {copied}\n"
                f"{self._format_perfect_strategy_counts(copied_strategy_counts)}"
            )
            self._log(
                self.export_console,
                f"[INFO] Dostępne perfect wg strategii przed filtrem: {self._format_perfect_strategy_counts(total_strategy_counts)}",
                "INFO"
            )
            try:
                self._update_step3_finish_button_state()
                self._set_button_emphasis("btn_finish_step3_frame", True)
                self._pulse_button_emphasis("btn_finish_step3_frame")
            except Exception:
                pass

            try:
                self.app.update_status(
                    "Paczka YOLO została utworzona poprawnie. Możesz zakończyć ten krok przyciskiem finish.",
                    "info"
                )
            except Exception:
                pass
        except Exception as e:
            self._set_console_text(self.export_console, f"❌ BŁĄD EKSPORTU YOLO:\n{e}")

    def _run_yolo_gold_export(self):
        selected_buckets = self._get_selected_gold_export_strategy_buckets()
        selected_labels = self._format_selected_gold_export_strategy_labels()
        split_enabled = bool(self.gold_export_split_var.get())
        train_pct, val_pct, test_pct = self._get_gold_export_split_percentages()

        if not selected_buckets:
            self._set_console_text(
                self.export_console,
                "❌ Nie wybrano żadnej strategii perfect do eksportu gold packa.\n\n"
                "Zaznacz co najmniej jedną z opcji: OCR exact, YOLO exact, OCR + YOLO rescue lub Manual / inne perfect."
            )
            return

        split_line = (
            f"Split: włączony ({train_pct:.0f}/{val_pct:.0f}/{test_pct:.0f})"
            if split_enabled
            else "Split: wyłączony"
        )
        self._set_console_text(
            self.export_console,
            f"⏳ Zbieranie idealnych tablic...\nFiltr strategii: {selected_labels}\n{split_line}"
        )

        base_chars_dir = Path(getattr(self, "_campaign_chars_dir", str(CONFIG.DIR_3_CHARS)))

        import datetime, uuid, shutil
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        base_datasets_dir = Path(getattr(self, "_campaign_datasets_dir", str(CONFIG.get_datasets_dir("char"))))
        yolo_out = base_datasets_dir / f"YOLO_MegaDataset_Chars_{timestamp}"

        try:
            char_map = {c: i for i, c in enumerate(CHAR_CLASS_ALPHABET)}
            seen = set()
            total_strategy_counts = self._empty_perfect_strategy_counts()
            copied_strategy_counts = self._empty_perfect_strategy_counts()
            export_entries = []

            meta_candidates = []
            for meta in base_chars_dir.rglob("metadata.json"):
                run_dir = meta.parent
                if (run_dir / "images").exists():
                    meta_candidates.append(meta)

            meta_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            for meta in meta_candidates:
                run_dir = meta.parent
                with open(meta, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                for pid, data in {k: v for k, v in metadata.items() if v.get("status") == "perfect"}.items():
                    strategy_bucket = self._get_perfect_strategy_bucket(data)
                    total_strategy_counts[strategy_bucket] += 1
                    if strategy_bucket not in selected_buckets:
                        continue

                    uk = f"{data.get('source_image', 'u')}_{int(data.get('source_bbox', [0])[0]//10) if data.get('source_bbox') else 0}"
                    if uk in seen:
                        continue
                    seen.add(uk)

                    img_src = run_dir / "images" / f"{pid}.jpg"
                    if not img_src.exists():
                        continue

                    img = cv2.imread(str(img_src))
                    if img is None:
                        continue

                    ih, iw = img.shape[:2]
                    new_pid = f"mega_{uuid.uuid4().hex[:8]}_{pid}"

                    txt = []
                    for c in data.get("characters", []):
                        ch = str(c.get("character", "")).upper()
                        if ch not in char_map:
                            continue
                        x1, y1, x2, y2 = c.get("bbox", [0, 0, 0, 0])
                        xc = max(0.0, min(1.0, ((x1 + x2) / 2.0) / iw))
                        yc = max(0.0, min(1.0, ((y1 + y2) / 2.0) / ih))
                        w = max(0.0, min(1.0, (x2 - x1) / iw))
                        h = max(0.0, min(1.0, (y2 - y1) / ih))
                        txt.append(f"{char_map[ch]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")

                    export_entries.append(
                        {
                            "pid": new_pid,
                            "img_src": img_src,
                            "label_text": "\n".join(txt),
                            "strategy_bucket": strategy_bucket,
                        }
                    )
                    copied_strategy_counts[strategy_bucket] += 1

            copied = len(export_entries)
            if copied == 0:
                msg = (
                    "❌ NIE UDAŁO SIĘ UTWORZYĆ DATASETU YOLO.\n\n"
                    f"Powód: po filtrze strategii ({selected_labels}) nie znaleziono ani jednej tablicy ze statusem perfect.\n\n"
                    f"Dostępne perfect wg strategii:\n{self._format_perfect_strategy_counts(total_strategy_counts)}\n\n"
                    "CO DALEJ:\n"
                    "1. Możesz rozszerzyć zaznaczone strategie w pz3.\n"
                    "2. Możesz wrócić do pz2 i poprawić OCR / Laboratorium.\n"
                    "3. Możesz wykonać eksport do CVAT i później zaimportować poprawki.\n"
                    "4. Możesz też wrócić do wizarda i skorzystać z trybów naprawczych."
                )
                self._set_console_text(self.export_console, msg)

                try:
                    if self._step3_linear_mode and CAMPAIGN.get_active_project_name():
                        CAMPAIGN.set_step3_needs_rework()
                except Exception:
                    pass

                try:
                    self._update_step3_finish_button_state()
                except Exception:
                    pass

                try:
                    self.app.update_status(
                        "Nie utworzono gold packa — pozostajesz w z3/pz3, aby kontynuować pracę.",
                        "warning"
                    )
                except Exception:
                    pass

                return

            split_stats = {}
            if split_enabled:
                random.Random(42).shuffle(export_entries)
                ratios = {
                    "train": train_pct / 100.0,
                    "val": val_pct / 100.0,
                    "test": test_pct / 100.0,
                }
                total_entries = len(export_entries)
                split_entries = {}
                start_idx = 0
                split_names = list(ratios.keys())
                for split_name in split_names:
                    n_split = int(total_entries * ratios[split_name])
                    if split_name == split_names[-1]:
                        n_split = total_entries - start_idx
                    split_entries[split_name] = export_entries[start_idx:start_idx + n_split]
                    start_idx += n_split

                for split_name, items in split_entries.items():
                    (yolo_out / "images" / split_name).mkdir(parents=True, exist_ok=True)
                    (yolo_out / "labels" / split_name).mkdir(parents=True, exist_ok=True)
                    split_stats[split_name] = len(items)
                    for item in items:
                        shutil.copy2(item["img_src"], yolo_out / "images" / split_name / f"{item['pid']}.jpg")
                        (yolo_out / "labels" / split_name / f"{item['pid']}.txt").write_text(
                            item["label_text"],
                            encoding="utf-8"
                        )
            else:
                img_out, lbl_out = yolo_out / "images", yolo_out / "labels"
                img_out.mkdir(parents=True, exist_ok=True)
                lbl_out.mkdir(parents=True, exist_ok=True)
                for item in export_entries:
                    shutil.copy2(item["img_src"], img_out / f"{item['pid']}.jpg")
                    (lbl_out / f"{item['pid']}.txt").write_text(item["label_text"], encoding="utf-8")

            yaml_content = f"path: {yolo_out.absolute().as_posix()}\n"
            if split_enabled:
                yaml_content += "train: images/train\nval: images/val\ntest: images/test\n"
            else:
                yaml_content += "train: images\nval: images\n"
            yaml_content += "nc: 36\nnames:\n"
            for char, class_id in char_map.items():
                yaml_content += f"  {class_id}: '{char}'\n"
            (yolo_out / "data.yaml").write_text(yaml_content, encoding="utf-8")

            split_info = (
                f"\nSplit: train={split_stats.get('train', 0)}, val={split_stats.get('val', 0)}, test={split_stats.get('test', 0)}"
                if split_enabled
                else "\nSplit: wyłączony (flat images/labels)"
            )

            self._set_console_text(
                self.export_console,
                f"✅ Dataset YOLO gotowy: {yolo_out}\n"
                f"Filtr strategii: {selected_labels}\n"
                f"Wyeksportowano: {copied}\n"
                f"{self._format_perfect_strategy_counts(copied_strategy_counts)}"
                f"{split_info}"
            )
            self._log(
                self.export_console,
                f"[INFO] Dostępne perfect wg strategii przed filtrem: {self._format_perfect_strategy_counts(total_strategy_counts)}",
                "INFO"
            )
            try:
                self._update_step3_finish_button_state()
                self._set_button_emphasis("btn_finish_step3_frame", True)
                self._pulse_button_emphasis("btn_finish_step3_frame")
            except Exception:
                pass

            try:
                self.app.update_status(
                    "Paczka YOLO została utworzona poprawnie. Możesz zakończyć ten krok przyciskiem finish.",
                    "info"
                )
            except Exception:
                pass
        except Exception as e:
            self._set_console_text(self.export_console, f"❌ BŁĄD EKSPORTU YOLO:\n{e}")

    def _run_cvat_import(self):
        xml_in = Path(self.import_cvat_xml_var.get().strip())
        meta_path = Path(self.preview_dir_var.get().strip()) / "metadata.json"

        if not xml_in.exists():
            self._set_console_text(self.import_console, "❌ BŁĄD: Wybrany plik XML nie istnieje.")
            return

        self._set_console_text(self.import_console, "⌛ Wczytywanie danych z XML...")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            root = ET.parse(xml_in).getroot()
            updated = 0

            for image in root.findall('.//image'):
                pid = Path(image.get('name', '')).stem
                if pid not in metadata:
                    continue

                new_chars = []
                for box in image.findall('box'):
                    if box.get('label', '').lower() in ['character', 'char']:
                        t = next((a.text for a in box.findall('attribute') if a.get('name') == 'text'), "?")
                        new_chars.append({
                            "character": t,
                            "bbox": [
                                float(box.get('xtl', 0)),
                                float(box.get('ytl', 0)),
                                float(box.get('xbr', 0)),
                                float(box.get('ybr', 0))
                            ],
                            "confidence": 1.0,
                            "method": "cvat_manual"
                        })

                metadata[pid]["characters"] = self._sort_character_records_by_x(new_chars)
                metadata[pid]["status"] = "perfect"
                updated += 1

            self._atomic_write_json(meta_path, metadata)
            self._apply_preview_metadata_update(metadata, preserve_selection=True)
            self._loaded_meta_path = meta_path
            try:
                self._loaded_meta_mtime = meta_path.stat().st_mtime
            except Exception:
                self._loaded_meta_mtime = None

            self._set_console_text(self.import_console, f"✅ Zaktualizowano: {updated} tablic.")
            try:
                stored_dir = self._store_current_preview_in_manual_char_pool(metadata)
                self._set_console_text(
                    self.import_console,
                    f"✅ Zaktualizowano: {updated} tablic.\n\n"
                    f"📦 Poprawki zapisano do puli ręcznej:\n{stored_dir}"
                )
            except Exception as e:
                logger.debug(f"Nie udało się zapisać paczki do manual_char_pool: {e}")
            try:
                self._update_step3_finish_button_state()
            except Exception:
                pass

        except Exception as e:
            self._set_console_text(self.import_console, f"❌ BŁĄD IMPORTU:\n{e}")

    # =========================================================
    # Ranking presetów OCR
    # =========================================================

    def _run_preset_ranking(self):
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj paczkę danych do testu!")

        preset_files = list(self.presets_dir.glob("*.json"))
        preset_files = [f for f in preset_files if f.name != "global_ranking.json"]
        if not preset_files:
            return messagebox.showinfo("Brak presetów", "Brak presetów! Otwórz Laboratorium i zapisz filtry jako JSON.")

        self.test_log_text.delete(1.0, tk.END)
        self._lock_ui_for_testing()
        self._set_test_progress_counter()
        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "ROZPOCZYNAM TURNIEJ PRESETÓW", "HEADER")

        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        cache_file = self.presets_dir / "global_ranking.json"
        session_token = self._project_reset_token

        def worker():
            try:
                ranking_cache = {}
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            ranking_cache = json.load(f)
                    except Exception:
                        pass

                ocr_engine = PlateOCR(device=self._device_to_ocr(self.yolo_device_var.get()))
                detector = CharacterDetector(method=DetectionMethod.OCR, ocr_engine=ocr_engine)

                results_table = []
                total_imgs = len(self.preview_plate_ids)
                total_presets = len(preset_files)

                for p_idx, p_file in enumerate(preset_files):
                    if session_token != self._project_reset_token:
                        return

                    preset_name = p_file.stem
                    try:
                        with open(p_file, 'r', encoding='utf-8') as f:
                            preset_params = json.load(f)
                    except Exception:
                        continue

                    clean_params = {k: v for k, v in preset_params.items() if not k.startswith("char_do_") and k != "char_ocr_conf"}
                    param_signature = str(sorted(clean_params.items()))

                    if preset_name in ranking_cache and ranking_cache[preset_name].get("signature") == param_signature:
                        results_table.append((ranking_cache[preset_name]["acc"], ranking_cache[preset_name]["matches"], preset_name, True))
                        self.frame.after(
                            0,
                            lambda p=((p_idx + 1) / total_presets) * 100: (
                                self.test_progress.config(value=p)
                                if session_token == self._project_reset_token else None
                            )
                        )
                        continue

                    ocr_engine.custom_prep_params = clean_params
                    if "char_ocr_conf" in preset_params:
                        ocr_engine.confidence_threshold = float(preset_params.get("char_ocr_conf", 0.25))

                    perfect_matches = 0
                    for pid in self.preview_plate_ids:
                        if session_token != self._project_reset_token:
                            return

                        img_path = imgs_dir / f"{pid}.jpg"
                        if not img_path.exists():
                            continue
                        plate_img = cv2.imread(str(img_path))
                        if plate_img is None:
                            continue

                        expected = self._get_true_texts_from_filename(self.preview_metadata.get(pid, {}).get("source_image", ""))
                        chars = detector.detect(plate_img)
                        if "".join([str(c.character) for c in chars]) in expected:
                            perfect_matches += 1

                    acc = (perfect_matches / total_imgs) * 100 if total_imgs > 0 else 0
                    ranking_cache[preset_name] = {
                        "name": preset_name,
                        "acc": acc,
                        "matches": perfect_matches,
                        "signature": param_signature,
                        "params": preset_params
                    }
                    results_table.append((acc, perfect_matches, preset_name, False))
                    self.frame.after(
                        0,
                        lambda p=((p_idx + 1) / total_presets) * 100: (
                            self.test_progress.config(value=p)
                            if session_token == self._project_reset_token else None
                        )
                    )

                if session_token != self._project_reset_token:
                    return

                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(ranking_cache, f, indent=4, ensure_ascii=False)

                results_table.sort(key=lambda x: x[0], reverse=True)

                self._log(self.test_log_text, "=" * 55, "HEADER")
                for i, (acc, matches, name, from_cache) in enumerate(results_table):
                    self._log(self.test_log_text, f"#{i+1}. {name.ljust(22)} | {acc:5.1f}%  ({matches}/{total_imgs})", "SUCCESS" if i == 0 else "INFO")

                self.frame.after(0, self._update_winner_label)

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD RANKINGU: {e}", "ERROR")
            finally:
                def finalize():
                    if session_token != self._project_reset_token:
                        return

                    if self._step3_linear_mode and CAMPAIGN.get_active_project_name():
                        self.unlock_dataset_subtab()

                    self.test_progress.config(value=100)
                    self._set_test_status("Turniej Zakończony!", "success")
                    self._unlock_ui_after_testing()

                self.frame.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    def _open_filter_lab(self):
        out_dir = Path(self.preview_dir_var.get().strip())
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj najpierw listę tablic.")

        imgs_dir = out_dir / "images"

        def roll_images():
            import random
            s = min(3, len(self.preview_plate_ids))
            ids = random.sample(self.preview_plate_ids, s)
            res = []
            for pid in ids:
                i = cv2.imread(str(imgs_dir / f"{pid}.jpg"))
                if i is not None:
                    res.append((pid, i))
            return res

        self.lab_current_images = roll_images()
        if not self.lab_current_images:
            return

        best_preset_data, best_acc = self._get_best_preset()
        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        panel_alt_bg = palette.get("panel_alt", "#2d2d30")
        field_bg = palette.get("field", panel_alt_bg)
        doc_bg = palette.get("doc_bg", field_bg)
        doc_fg = palette.get("doc_fg", palette.get("fg", "#f3f3f3"))
        fg = palette.get("fg", "#f3f3f3")
        muted_fg = palette.get("muted", "#c7c7c7")
        info_fg = palette.get("info", palette.get("accent", "#2980b9"))
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        lab_win = tk.Toplevel(self.frame)
        lab_win.title("Laboratorium Filtrów OCR")
        lab_win.geometry("1100x850")
        try:
            lab_win.configure(bg=palette.get("bg", panel_bg))
        except Exception:
            pass

        bottom_bar = ttk.Frame(lab_win, padding=10, relief="raised")
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Lokalny pasek pomocy dla okna laboratorium.
        lab_help_text = tk.Text(
            bottom_bar, height=2, wrap=tk.WORD,
            bg=doc_bg, bd=0, font=("Segoe UI", 10), fg=doc_fg, insertbackground=doc_fg
        )
        lab_help_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        lab_help_text.insert(tk.END, "💡 Najedź myszką na nazwę suwaka, aby zobaczyć podpowiedź...")
        lab_help_text.config(state=tk.DISABLED)

        def update_lab_help(msg):
            if lab_win.winfo_exists():
                lab_help_text.config(state=tk.NORMAL)
                lab_help_text.delete(1.0, tk.END)
                lab_help_text.insert(tk.END, msg)
                lab_help_text.config(state=tk.DISABLED)

        self.old_status_updater = HELP.status_updater
        HELP.status_updater = update_lab_help

        main_content = ttk.Frame(lab_win)
        main_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_container = ttk.Frame(main_content, width=350)
        left_container.pack(side=tk.LEFT, fill=tk.Y)
        left_container.pack_propagate(False)

        canvas_sliders = tk.Canvas(left_container, highlightthickness=0, bd=0, bg=panel_bg)
        scroll_sliders = WebSlimScrollbar(left_container, orient=tk.VERTICAL, command=canvas_sliders.yview)
        scrollable_frame = ttk.Frame(canvas_sliders, padding=10, style="Panel.TFrame")

        frame_id = canvas_sliders.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas_sliders.bind("<Configure>", lambda e: canvas_sliders.itemconfig(frame_id, width=e.width))
        scrollable_frame.bind("<Configure>", lambda e: canvas_sliders.configure(scrollregion=canvas_sliders.bbox("all")))
        canvas_sliders.configure(yscrollcommand=scroll_sliders.set)

        scroll_sliders.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_sliders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_view_container = ttk.Frame(main_content, padding=10)
        right_view_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        view_canvas = tk.Canvas(right_view_container, bg=panel_alt_bg, highlightthickness=0, bd=0)
        view_scroll_v = WebSlimScrollbar(right_view_container, orient=tk.VERTICAL, command=view_canvas.yview)
        view_scroll_h = WebSlimScrollbar(right_view_container, orient=tk.HORIZONTAL, command=view_canvas.xview)

        view_scroll_h.pack(side=tk.BOTTOM, fill=tk.X)
        view_scroll_v.pack(side=tk.RIGHT, fill=tk.Y)
        view_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        view_canvas.configure(yscrollcommand=view_scroll_v.set, xscrollcommand=view_scroll_h.set)

        view_frame = ttk.Frame(view_canvas, style="Card.TFrame")
        view_canvas.create_window((0, 0), window=view_frame, anchor="nw")
        view_frame.bind("<Configure>", lambda e: view_canvas.configure(scrollregion=view_canvas.bbox("all")))

        def _lab_canvas_overflows(target_canvas) -> bool:
            try:
                bbox = target_canvas.bbox("all")
                if not bbox:
                    return False
                content_height = int(bbox[3]) - int(bbox[1])
                viewport_height = int(target_canvas.winfo_height())
                return content_height > viewport_height + 1
            except Exception:
                return False

        def _on_lab_mousewheel(event):
            units = self._mousewheel_units(event)
            if units == 0:
                return None

            try:
                x_root = int(getattr(event, "x_root", 0) or lab_win.winfo_pointerx())
                y_root = int(getattr(event, "y_root", 0) or lab_win.winfo_pointery())
            except Exception:
                return None

            for target_canvas in (canvas_sliders, view_canvas):
                if not self._widget_contains_point(target_canvas, x_root, y_root):
                    continue
                if not _lab_canvas_overflows(target_canvas):
                    return None
                try:
                    target_canvas.yview_scroll(units, "units")
                except Exception:
                    return "break"
                return "break"
            return None

        lab_win.bind("<MouseWheel>", _on_lab_mousewheel, add="+")
        lab_win.bind("<Button-4>", _on_lab_mousewheel, add="+")
        lab_win.bind("<Button-5>", _on_lab_mousewheel, add="+")
        self._bind_scroll_canvas_children(
            scrollable_frame,
            canvas_sliders,
            lambda: _lab_canvas_overflows(canvas_sliders)
        )

        self.lab_image_labels = []
        for i in range(3):
            f = ttk.LabelFrame(view_frame, text=f" Obraz testowy {i+1} ", padding=10)
            f.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)

            lbl = ttk.Label(f, font=("Consolas", 10, "bold"))
            lbl.pack(anchor=tk.W, pady=(0, 5))

            c = ttk.Frame(f)
            c.pack(fill=tk.BOTH, expand=True)

            of_frame = ttk.Frame(c)
            of_frame.pack(side=tk.LEFT, padx=10, fill=tk.BOTH)
            o_lbl = tk.Label(of_frame, bg=field_bg, bd=1, relief="solid", highlightthickness=0)
            o_lbl.pack(anchor=tk.NW)

            pf_frame = ttk.Frame(c)
            pf_frame.pack(side=tk.LEFT, padx=20, fill=tk.BOTH)
            p_lbl = tk.Label(pf_frame, bg=field_bg, bd=1, relief="solid", highlightthickness=0)
            p_lbl.pack(anchor=tk.NW)

            self.lab_image_labels.append({
                "lbl": lbl,
                "orig": o_lbl,
                "proc": p_lbl
            })

        self.lab_photo_refs = []
        active_traces = []

        def update_preview(*args):
            if not lab_win.winfo_exists():
                return
            try:
                th = self.prep_height_var.get()
                ma = self.prep_angle_var.get()
                ct = self.prep_clip_var.get()
                dh = self.prep_denoise_var.get()
                cc = self.prep_clahe_var.get()
                use_bin = self.prep_use_bin_var.get()
                tb = self.prep_block_var.get()
                t_c = self.prep_c_var.get()
                if tb % 2 == 0:
                    tb += 1
                ei = self.prep_erode_var.get()

                interp_str = self.interpolation_var.get()
                interp_map = {
                    "nearest": cv2.INTER_NEAREST,
                    "linear": cv2.INTER_LINEAR,
                    "cubic": cv2.INTER_CUBIC,
                    "lanczos4": cv2.INTER_LANCZOS4
                }
                cv2_interp = interp_map.get(interp_str.lower(), cv2.INTER_LANCZOS4)

                self.lab_photo_refs.clear()

                for idx, (pid, orig_img) in enumerate(self.lab_current_images):
                    if idx >= len(self.lab_image_labels):
                        break

                    if abs(ma) > 0.1:
                        h, w = orig_img.shape[:2]
                        M = cv2.getRotationMatrix2D((w // 2, h // 2), ma, 1.0)
                        rotated = cv2.warpAffine(
                            orig_img, M, (w, h),
                            flags=cv2_interp,
                            borderMode=cv2.BORDER_REPLICATE
                        )
                    else:
                        rotated = orig_img.copy()

                    gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY) if len(rotated.shape) == 3 else rotated.copy()
                    h_g, w_g = gray.shape
                    scale = float(th) / h_g if h_g > 0 else 1.0
                    gray_scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2_interp)

                    po = ImageTk.PhotoImage(Image.fromarray(gray_scaled))

                    if ct < 255:
                        gray_scaled[gray_scaled > ct] = 255

                    den = cv2.fastNlMeansDenoising(
                        gray_scaled, None,
                        h=dh, templateWindowSize=7, searchWindowSize=21
                    ) if dh > 0 else gray_scaled

                    if self.do_clahe_var.get() and cc > 0:
                        clahe = cv2.createCLAHE(clipLimit=cc, tileGridSize=(8, 8))
                        contrasted = clahe.apply(den)
                    else:
                        contrasted = den

                    blurred = cv2.GaussianBlur(contrasted, (3, 3), 0)

                    if use_bin:
                        binary = cv2.adaptiveThreshold(
                            blurred, 255,
                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY,
                            blockSize=max(3, tb),
                            C=t_c
                        )
                        if ei > 0:
                            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                            final = cv2.erode(binary, kernel, iterations=ei)
                        else:
                            final = binary
                    else:
                        final = contrasted

                    pad_pct = self.prep_padding_var.get()
                    if pad_pct > 0:
                        py = int(final.shape[0] * (pad_pct / 100.0))
                        px = int(final.shape[1] * (pad_pct / 100.0))
                        final = cv2.copyMakeBorder(final, py, py, px, px, cv2.BORDER_CONSTANT, value=255)

                    pp = ImageTk.PhotoImage(Image.fromarray(final))
                    self.lab_photo_refs.extend([po, pp])

                    ui_row = self.lab_image_labels[idx]
                    ui_row["lbl"].config(text=f"ID: {pid}")
                    ui_row["orig"].config(image=po)
                    ui_row["proc"].config(image=pp)

            except Exception:
                pass

        def add_slider(parent, label, var, from_, to_, res, ghost_key="", help_key=""):
            f = ttk.Frame(parent)
            f.pack(fill=tk.X, pady=4)

            lbl_f = ttk.Frame(f)
            lbl_f.pack(fill=tk.X)

            main_label = ttk.Label(lbl_f, text=label)
            main_label.pack(side=tk.LEFT)

            if ghost_key and best_preset_data and isinstance(best_preset_data.get("params"), dict):
                params_dict = best_preset_data["params"]
                if ghost_key in params_dict:
                    val = params_dict[ghost_key]
                    ghost_str = f"{val:.1f}" if isinstance(val, float) else str(val)
                    ttk.Label(
                        lbl_f,
                        text=f"[Zwycięzca: {ghost_str}]",
                        foreground=info_fg,
                        font=("Segoe UI", 9, "bold")
                    ).pack(side=tk.RIGHT)

            s = ttk.Scale(f, from_=from_, to=to_, variable=var, command=update_preview)
            s.pack(side=tk.LEFT, fill=tk.X, expand=True)

            l = ttk.Label(f, width=5)
            l.pack(side=tk.RIGHT)

            def update_lbl(*a):
                if lab_win.winfo_exists():
                    l.config(text=f"{var.get():.{res}f}")

            trace_id = var.trace_add("write", update_lbl)
            active_traces.append((var, trace_id))
            update_lbl()

            if help_key:
                HELP.bind_help(main_label, help_key)
                HELP.bind_help(s, help_key)

        if best_preset_data and best_preset_data.get("name"):
            leader_f = tk.Frame(
                scrollable_frame,
                bg=panel_bg,
                bd=0,
                highlightthickness=1,
                highlightbackground=border,
                highlightcolor=border
            )
            leader_f.pack(fill=tk.X, pady=(0, 15))
            tk.Label(
                leader_f,
                text=f"Lider: {best_preset_data.get('name').upper()}",
                bg=panel_bg, fg=fg,
                font=("Segoe UI", 10, "bold")
            ).pack(pady=(5, 0))
            tk.Label(
                leader_f,
                text=f"Skuteczność: {best_acc:.1f}%",
                bg=panel_bg, fg=muted_fg,
                font=("Segoe UI", 9)
            ).pack(pady=(0, 5))
        else:
            ttk.Label(scrollable_frame, text="Dostrojenie Algorytmu", font=("Segoe UI", 12, "bold")).pack(pady=(0, 10))

        geom = ttk.LabelFrame(scrollable_frame, text=" 1. Geometria ", padding=10)
        geom.pack(fill=tk.X, pady=(0, 10))

        angle_row = ttk.Frame(geom)
        angle_row.pack(fill=tk.X)
        add_slider(angle_row, "Ręczna korekta kąta [°]:", self.prep_angle_var, -30, 30, 1, "manual_angle", "lab_angle")
        ttk.Button(geom, text="Reset Kąta", command=lambda: (self.prep_angle_var.set(0.0), update_preview())).pack(anchor=tk.E, pady=(0, 5))

        add_slider(geom, "Wysokość OCR (px):", self.prep_height_var, 40, 150, 0, "target_height", "lab_height")

        filt = ttk.LabelFrame(scrollable_frame, text=" 2. Filtry bazowe ", padding=10)
        filt.pack(fill=tk.X, pady=(0, 10))
        add_slider(filt, "Odcięcie odblasków (255=Wył):", self.prep_clip_var, 100, 255, 0, "clip_thresh", "lab_clip")
        add_slider(filt, "Usuwanie ziarna (0=Wył):", self.prep_denoise_var, 0, 50, 0, "denoise_h", "lab_denoise")
        cb2 = ttk.Checkbutton(filt, text="Wzmacniaj kontrast (CLAHE)", variable=self.do_clahe_var, command=update_preview)
        cb2.pack(anchor=tk.W)
        HELP.bind_help(cb2, "lab_clahe")
        add_slider(filt, "Siła CLAHE:", self.prep_clahe_var, 0.0, 10.0, 1, "clahe_clip", "lab_clahe")

        bina = ttk.LabelFrame(scrollable_frame, text=" 3. Binaryzacja ", padding=10)
        bina.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(bina, text="Włącz pełną binaryzację", variable=self.prep_use_bin_var, command=update_preview).pack(anchor=tk.W)
        add_slider(bina, "Rozmiar bloku (nieparzyste):", self.prep_block_var, 3, 51, 0, "thresh_block", "lab_block")
        add_slider(bina, "Stała odcięcia (C):", self.prep_c_var, -20, 20, 0, "thresh_c", "lab_c")
        add_slider(bina, "Pogrubianie liter (Erozja):", self.prep_erode_var, 0, 5, 0, "erode_iter", "lab_erode")
        add_slider(bina, "Biała ramka - Padding [%]:", self.prep_padding_var, 0, 50, 0, "padding_pct", "lab_pad")

        ocr_f = ttk.LabelFrame(scrollable_frame, text=" 4. Parametry Sieci (OCR) ", padding=10)
        ocr_f.pack(fill=tk.X, pady=(0, 10))
        add_slider(ocr_f, "Wymagany próg pewności (0-1.0):", self.ocr_conf_var, 0.05, 0.95, 2, "char_ocr_conf", "lab_conf")

        def load_preset():
            p = filedialog.askopenfilename(initialdir=self.presets_dir, filetypes=[("JSON", "*.json")], parent=lab_win)
            if p:
                try:
                    with open(p, 'r') as f: data = json.load(f)
                    if "target_height" in data: self.prep_height_var.set(data["target_height"])
                    if "clip_thresh" in data: self.prep_clip_var.set(data["clip_thresh"])
                    if "thresh_block" in data: self.prep_block_var.set(data["thresh_block"])
                    if "thresh_c" in data: self.prep_c_var.set(data["thresh_c"])
                    if "erode_iter" in data: self.prep_erode_var.set(data["erode_iter"])
                    if "padding_pct" in data: self.prep_padding_var.set(data["padding_pct"])
                    if "char_ocr_conf" in data: self.ocr_conf_var.set(data["char_ocr_conf"])
                    update_preview()
                except: pass

        def save_preset():
            name = simpledialog.askstring("Preset", "Podaj nazwę dla presetu:", parent=lab_win)
            if name:
                p = self.presets_dir / f"{name}.json"
                data = self._get_current_prep_params()
                data["char_ocr_conf"] = self.ocr_conf_var.get()
                with open(p, 'w') as f: json.dump(data, f, indent=4)

        def safe_close():
            for var, tid in active_traces:
                try: var.trace_remove("write", tid)
                except: pass
            self._force_save_all()
            self.lab_photoRefs = []
            HELP.status_updater = self.old_status_updater
            lab_win.destroy()

        lab_win.protocol("WM_DELETE_WINDOW", safe_close)
        ttk.Button(bottom_bar, text="Zapisz Preset", command=save_preset).pack(side=tk.RIGHT)
        ttk.Button(bottom_bar, text="Wczytaj Preset", command=load_preset).pack(side=tk.RIGHT)
        ttk.Button(bottom_bar, text="ZAMKNIJ", command=safe_close, style="Accent.TButton").pack(side=tk.RIGHT, padx=15)

        btn_roll = ttk.Button(
            bottom_bar,
            text="🎲 Losuj inną próbkę",
            command=lambda: (setattr(self, 'lab_current_images', roll_images()), update_preview())
        )
        btn_roll.pack(side=tk.RIGHT, padx=15)

        try:
            self.app.style_panel_surface(lab_win, background=panel_bg)
            self.app.style_text_widget(lab_help_text, role="doc")
            self.app.style_canvas_widget(canvas_sliders, background=panel_bg, bordercolor=border)
            self.app.style_canvas_widget(view_canvas, background=panel_alt_bg, bordercolor=border)
        except Exception:
            pass

        update_preview()
