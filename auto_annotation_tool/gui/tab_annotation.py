#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Autoanotacja - główne przetwarzanie YOLO (pojazdy + tablice)
Układ 3-kolumnowy z interaktywną przeglądarką na Canvasie.
"""

import copy
import json
from collections import deque
import os
import re
import tkinter as tk
import tkinter.font as tkfont
import xml.etree.ElementTree as ET
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional
import datetime
import threading
import logging
import math
import shutil
import time
import queue
import numpy as np

import cv2
from PIL import Image, ImageTk
from .zoomable_canvas import ZoomableCanvas
from .section_header_label import SectionHeaderLabel

from ..config import CONFIG, logger, YOLO_AVAILABLE, AVAILABLE_DETECT_MODELS, SESSION
from ..icons import IconManager
from ..annotators import PlateAnnotator, CombinedAnnotator, VehicleAnnotator
from ..exporters import CVATExporter, ReportGenerator
from ..training import DatasetCreator
from ..utils import count_images_in_directory, format_duration, get_image_files, get_image_size
from ..validators import validate_model_file
from ..data_models import Detection, AnnotationStatus, ImageAnnotation, AnnotationReport
from ..rectification.polygon_validator import PolygonValidator
from .help_manager import HELP
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors

NAV_BUTTON_WIDTH = 18


class SlimProgressBar(tk.Canvas):
    def __init__(
        self,
        master,
        *,
        maximum: float = 100.0,
        value: float = 0.0,
        thickness: int = 2,
        trough_color: str = "#3c3c3c",
        fill_color: str = "#4ec9b0",
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


class AnnotationTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon = IconManager
        self.frame = ttk.Frame(parent)
        self._startup_ui_ready = False
        session_state = self._load_free_mode_session_snapshot()

        self.annotator = None
        self.dataset_creator = DatasetCreator()
        self.is_processing = False
        self.start_time = None
        self._free_mode_session_restore_in_progress = False
        self._campaign_project_restore_in_progress = False
        self._free_mode_session_save_after_id = None
        self._pre_campaign_free_mode_snapshot = None
        self._ui_dispatch_queue = queue.Queue()
        self._ui_dispatch_after_id = None
        self._progress_update_lock = threading.Lock()
        self._pending_progress_update = None
        self._progress_update_flush_queued = False
        self._pre_progress_after_id = None
        self._pre_progress_tick = 0
        self._progress_update_seen = False
        self._pre_progress_message = ""
        
        # Zmienne do przeglÄ…darki
        self.current_annotations = []
        self.current_input_dir = None
        self._preview_image_path_map = {}
        self._campaign_reuse_manual_filenames = set()
        self._campaign_reuse_manual_summary = {}
        self.current_annotation_run_dir = None
        self.current_annotation_xml_path = None
        self.current_preview_index = None
        self._preview_session_restore_index = None
        self._preview_session_restore_filename = ""
        self._preview_selected_plate_by_image = {}
        self._preview_selected_vehicle_by_image = {}
        self._preview_drag_state = None
        self._preview_pending_vertex_hit = None
        self._preview_corner_drag_modifier_down = False
        self._preview_last_modifier_press_at = 0.0
        self._preview_draw_mode = False
        self._preview_draw_points = []
        self._preview_delete_mode = False
        self._preview_delete_candidate_idx = None
        self._preview_dirty_images = set()
        self._preview_autosave_after_id = None
        self._preview_drag_refresh_after_id = None
        self._preview_fullscreen_active = False
        self._preview_fullscreen_restore_log_visible = False
        self._preview_fullscreen_restore_root_state = False
        self._preview_fullscreen_restore_window_state = "normal"
        self._preview_fullscreen_restore_geometry = ""
        self._preview_polygon_focus_restore_state = None
        self._preview_focus_target = None
        self._preview_force_fit_after_resize = False
        self._preview_debug_enabled = False
        self._preview_debug_events = deque(maxlen=8)
        self._preview_debug_last_drag_update_at = 0.0
        self._preview_debug_log_path = Path(CONFIG.WORKSPACE_DIR) / "z2_debug.log"
        self._preview_layout_restore_after_ids = []
        self._preview_history_undo = {}
        self._preview_history_redo = {}
        self._preview_history_replaying = False
        self._preview_history_limit = 80
        self._preview_list_populate_after_id = None
        self._preview_list_populate_token = 0
        self._preview_list_display_indices = []
        self._preview_list_sort_tiles = {}
        self._run_plate_count_cache = {}
        self._main_pane_layout_after_id = None
        self._main_pane_layout_initialized = False
        self._main_pane_layout_in_progress = False
        self._main_pane_layout_pending_force_defaults = False
        self._left_panel_scroll_after_id = None
        self._current_run_manual_template = False
        self._current_run_manual_vehicle_assist = False
        self._manual_review_active = False
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        self._last_completed_workflow_route = ""
        self.preview_edit_status_var = tk.StringVar(value="Po zakończeniu anotacji tutaj poprawisz rogi tablic.")
        self.preview_list_summary_var = tk.StringVar(
            value="Tablice po korekcie: 0/0\nObrazy z poprawkami: 0/0 | Niezapisane: 0"
        )
        self._preview_list_sort_options = (
            "Status: ED -> OK -> problem",
            "Status: OK -> ED -> problem",
            "Status: problem -> ED -> OK",
            "Nazwa pliku A-Z",
        )
        self.preview_list_sort_var = tk.StringVar(value=self._preview_list_sort_options[0])
        self.preview_debug_var = tk.StringVar(value="DEBUG Z2 | oczekiwanie na zdarzenia")
        self.preview_fullscreen_hint_var = tk.StringVar(value="")

        self.mode_var = tk.StringVar(value=session_state["mode"])
        self.vehicle_model_var = tk.StringVar(value=session_state["vehicle_model"])
        self.character_model_var = tk.StringVar(value=session_state["character_model"])
        self.vehicle_custom_var = tk.StringVar(value=session_state["vehicle_custom"])
        self.plate_custom_var = tk.StringVar(value=session_state["plate_custom"])
        self.character_custom_var = tk.StringVar(value=session_state["character_custom"])
        initial_device = str(session_state.get("device") or "auto").strip() or "auto"
        try:
            app_device_getter = getattr(self.app, "get_global_yolo_device_choice", None)
            if callable(app_device_getter):
                initial_device = str(app_device_getter() or initial_device).strip() or initial_device
        except Exception:
            pass
        self.device_var = tk.StringVar(value=initial_device)
        self.conf_var = tk.DoubleVar(value=session_state["conf"])
        self._campaign_paths_locked = False
        self._annotation_log_visible = False
        self._character_model_options = {}
        self._left_section_separators = []
        self._compact_path_display_vars = []
        self._workflow_step_cards = []
        self._left_path_button_width = 15
        self._left_path_action_minsize = 140
        self.project_paths_info_var = tk.StringVar(value="")
        self.project_paths_rel_var = tk.StringVar(value="")
        self.plate_dataset_run_var = tk.StringVar(value=session_state["plate_dataset_run"])
        self.plate_dataset_images_var = tk.StringVar(value=session_state["plate_dataset_images"])
        self.plate_dataset_out_var = tk.StringVar(value="")
        self.plate_train_pct = tk.DoubleVar(value=session_state["plate_train_pct"])
        self.plate_val_pct = tk.DoubleVar(value=session_state["plate_val_pct"])
        self.plate_export_progress_var = tk.DoubleVar(value=0.0)
        self.progress_counts_var = tk.StringVar(value="udane/przer./caĹ‚oĹ›Ä‡: 0/0/0")
        # DomyĹ›lnie podpowiadaj katalog wejĹ›ciowy z workspace.
        self.input_dir_var = tk.StringVar(value=session_state["input_dir"])
        self.output_dir_var = tk.StringVar(value=session_state["output_dir"])
        self.manual_xml_template_var = tk.BooleanVar(value=bool(session_state["manual_xml_template"]))
        self.manual_vehicle_assist_var = tk.BooleanVar(value=bool(session_state["manual_vehicle_assist"]))
        self.workflow_route_var = tk.StringVar(value=str(session_state.get("workflow_route") or "").strip())
        self.manual_entry_mode_var = tk.StringVar(
            value=str(session_state.get("manual_entry_mode") or "continue").strip() or "continue"
        )
        self.auto_vehicle_choice_var = tk.StringVar(
            value=str(session_state.get("auto_vehicle_choice") or "skip").strip() or "skip"
        )
        self._workflow_route_hover_mode = None
        self.workflow_step_var = tk.StringVar(
            value=str(session_state.get("workflow_step") or "").strip()
        )
        self.free_mode_screen_var = tk.StringVar(
            value=str(session_state.get("free_mode_screen") or "").strip()
        )
        self.manual_entry_title_var = tk.StringVar(value="")
        self.workflow_intro_var = tk.StringVar(value="")
        self.workflow_action_hint_var = tk.StringVar(value="")
        self.workflow_conf_title_var = tk.StringVar(value="")
        self.workflow_conf_hint_var = tk.StringVar(value="")
        self.workflow_vehicle_model_title_var = tk.StringVar(value="")
        self.workflow_vehicle_model_hint_var = tk.StringVar(value="")
        self.auto_vehicle_choice_hint_var = tk.StringVar(value="")
        self.manual_entry_hint_var = tk.StringVar(value="")
        self.manual_history_run_var = tk.StringVar(value="")
        self.manual_history_hint_var = tk.StringVar(value="")
        self.run_output_info_var = tk.StringVar(value="")
        self.manual_xml_template_hint_var = tk.StringVar(value="")
        self.manual_vehicle_assist_hint_var = tk.StringVar(value="")
        self.campaign_reuse_manual_var = tk.BooleanVar(value=False)
        self.campaign_reuse_manual_hint_var = tk.StringVar(value="")
        self.manual_stage_dir_var = tk.StringVar(value="")
        self.manual_stage_status_var = tk.StringVar(value="")
        self.approve_gate_hint_var = tk.StringVar(value="")
        self.detection_mode_hint_var = tk.StringVar(value="")
        self.route_badge_var = tk.StringVar(value="")
        self.route_summary_var = tk.StringVar(value="")
        self.followup_intro_var = tk.StringVar(value="")
        self.export_intro_var = tk.StringVar(value="")
        self._manual_review_history_entries = []
        self._manual_review_history_label_map = {}
        last_preview_run_dir = str(session_state["last_preview_run_dir"] or "").strip()
        self.last_staging_run_dir = Path(last_preview_run_dir) if last_preview_run_dir else None

        self._create_widgets()
        self._ensure_ui_dispatch_pump()
        self._apply_free_mode_session_snapshot(session_state, restore_preview=False)
        self._bind_free_mode_session_observers()
        self.frame.after_idle(self._mark_startup_ui_ready)

    def _mark_startup_ui_ready(self):
        self._startup_ui_ready = True

    def _post_to_ui(self, fn):
        if not callable(fn):
            return

        if threading.current_thread() is threading.main_thread():
            try:
                fn()
            except Exception:
                logger.exception("Blad zadania UI w zakladce Z2")
            return

        try:
            self._ui_dispatch_queue.put_nowait(fn)
        except Exception:
            pass

    def _queue_progress_update(self, pct, current, total, filename, successful=0):
        payload = (
            float(pct),
            int(current),
            int(total),
            str(filename or ""),
            int(successful or 0),
        )

        should_schedule = False
        with self._progress_update_lock:
            self._pending_progress_update = payload
            if not self._progress_update_flush_queued:
                self._progress_update_flush_queued = True
                should_schedule = True

        if should_schedule:
            self._post_to_ui(self._flush_queued_progress_update)

    def _cancel_pre_progress_activity(self):
        pending = getattr(self, "_pre_progress_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._pre_progress_after_id = None

    def _start_pre_progress_activity(self, message: str):
        self._cancel_pre_progress_activity()
        self._progress_update_seen = False
        self._pre_progress_tick = 0
        self._pre_progress_message = str(message or "Inicjalizacja analizy")

        def pulse():
            self._pre_progress_after_id = None
            if not self.is_processing or bool(getattr(self, "_progress_update_seen", False)):
                return

            tick = int(getattr(self, "_pre_progress_tick", 0) or 0)
            dots = "." * ((tick % 3) + 1)
            pulse_value = 1.5 + (tick % 4) * 1.5
            try:
                self.progress.configure(value=pulse_value)
            except Exception:
                pass
            self._set_status_label_state(f"{self._pre_progress_message}{dots}", "neutral")
            self._pre_progress_tick = tick + 1

            try:
                self._pre_progress_after_id = self.frame.after(350, pulse)
            except Exception:
                self._pre_progress_after_id = None

        try:
            self._pre_progress_after_id = self.frame.after(0, pulse)
        except Exception:
            self._pre_progress_after_id = None

    def _flush_queued_progress_update(self):
        payload = None
        with self._progress_update_lock:
            payload = self._pending_progress_update
            self._pending_progress_update = None
            self._progress_update_flush_queued = False

        if payload is None:
            return

        self._update_progress(*payload)

    def _ensure_ui_dispatch_pump(self):
        if getattr(self, "_ui_dispatch_after_id", None):
            return
        try:
            self._ui_dispatch_after_id = self.frame.after(20, self._drain_ui_dispatch_queue)
        except Exception:
            self._ui_dispatch_after_id = None

    def _drain_ui_dispatch_queue(self):
        self._ui_dispatch_after_id = None

        for _ in range(200):
            try:
                fn = self._ui_dispatch_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break

            try:
                fn()
            except Exception:
                logger.exception("Blad podczas obslugi kolejki UI w Z2")

        try:
            self._ui_dispatch_after_id = self.frame.after(20, self._drain_ui_dispatch_queue)
        except Exception:
            self._ui_dispatch_after_id = None

    def is_startup_ui_ready(self) -> bool:
        return bool(getattr(self, "_startup_ui_ready", False))

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
        except: pass
        return devices

    def _normalize_selected_device(self, raw_value: str | None = None, devices=None) -> str:
        available = list(devices or self._get_available_devices())
        current = str(raw_value if raw_value is not None else self.device_var.get() or "").strip()
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
        if hasattr(self, "device_combo"):
            try:
                self.device_combo.configure(values=devices)
            except Exception:
                pass

        normalized = self._normalize_selected_device(devices=devices)
        if normalized:
            self.device_var.set(normalized)

        self._update_device_hint()

    def _device_to_ultralytics(self, device_str: str):
        raw = str(device_str or "").strip().lower()
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
                return int(str(device_str).split(":")[1].split()[0])
            except Exception:
                return 0

        return "cpu"

    def _update_device_hint(self, event=None):
        label = getattr(self, "device_hint_lbl", None)
        if label is None:
            return

        devices = self._get_available_devices()
        normalized = self._normalize_selected_device(devices=devices)
        current = str(self.device_var.get() or "").strip()
        if normalized != current:
            self.device_var.set(normalized)
            current = normalized

        palette = getattr(self.app, "palette", {})
        gpu_devices = [item for item in devices if item.startswith("cuda:")]
        current_lower = current.lower()

        if current_lower.startswith("auto"):
            if gpu_devices:
                text = "Auto preferuje GPU/CUDA, a przy braku akceleracji przejdzie na CPU."
                fg = palette.get("info", "#3498db")
            else:
                text = "Auto: brak CUDA, wiec autoanotacja uruchomi sie na CPU."
                fg = palette.get("warning", "#f39c12")
        elif current_lower.startswith("cpu"):
            text = "CPU wymusza prace bez akceleracji GPU."
            fg = palette.get("muted", "#9a9a9a")
        else:
            text = "Wybrana karta GPU zostanie uzyta do inferencji YOLO."
            fg = palette.get("success", "#27ae60")

        try:
            label.configure(text=text, foreground=fg)
        except Exception:
            pass

    def apply_global_yolo_device_choice(self, value: str):
        normalized = self._normalize_selected_device(raw_value=value)
        try:
            self.device_var.set(normalized)
        except Exception:
            pass
        try:
            self._update_device_hint()
        except Exception:
            pass
        self._queue_free_mode_session_save()

    def _get_effective_yolo_device_choice(self) -> str:
        try:
            app_device_getter = getattr(self.app, "get_global_yolo_device_choice", None)
            if callable(app_device_getter):
                normalized = self._normalize_selected_device(raw_value=app_device_getter())
                if str(self.device_var.get() or "").strip() != normalized:
                    self.device_var.set(normalized)
                return normalized
        except Exception:
            pass

        normalized = self._normalize_selected_device()
        if str(self.device_var.get() or "").strip() != normalized:
            self.device_var.set(normalized)
        return normalized

    def _refresh_confidence_value_labels(self):
        for label in (
            getattr(self, "workflow_conf_value_lbl", None),
            getattr(self, "conf_value_lbl", None),
        ):
            if label is None:
                continue
            try:
                label.configure(text=f"{self.conf_var.get():.2f}")
            except Exception:
                pass

    def _annotation_session_defaults(self) -> dict:
        return {
            "input_dir": str(Path(CONFIG.DIR_1_RAW).absolute()),
            "output_dir": str(Path(CONFIG.get_auto_annotations_dir("plate")).absolute()),
            "mode": "C: Pojazdy + tablice",
            "vehicle_model": "",
            "vehicle_custom": "",
            "plate_custom": "",
            "character_model": "Brak / OCR",
            "character_custom": "",
            "device": "auto",
            "conf": float(CONFIG.DEFAULT_CONFIDENCE),
            "plate_dataset_run": "",
            "plate_dataset_images": "",
            "plate_train_pct": 80.0,
            "plate_val_pct": 10.0,
            "manual_xml_template": False,
            "manual_vehicle_assist": False,
            "workflow_route": "",
            "manual_entry_mode": "continue",
            "auto_vehicle_choice": "skip",
            "workflow_step": "",
            "free_mode_screen": "route_choice",
            "manual_review_active": False,
            "manual_review_from_auto": False,
            "manual_review_export_ready": False,
            "manual_review_history": [],
            "last_preview_run_dir": "",
            "last_preview_index": -1,
            "last_preview_filename": "",
        }

    @staticmethod
    def _normalize_workflow_route_value(route: str | None = None) -> str:
        value = str(route or "").strip().lower()
        if value in {"auto", "manual"}:
            return value
        return ""

    @staticmethod
    def _normalize_manual_entry_mode(mode: str | None = None) -> str:
        value = str(mode or "").strip().lower()
        if value in {"new", "continue", "import"}:
            return value
        return "continue"

    @staticmethod
    def _normalize_auto_vehicle_choice(choice: str | None = None) -> str:
        value = str(choice or "").strip().lower()
        if value in {"use", "skip"}:
            return value
        return "skip"

    @staticmethod
    def _normalize_workflow_step_value(step: str | None = None) -> str:
        value = str(step or "").strip().lower()
        allowed = {
            "auto_plate_model",
            "auto_conf",
            "auto_vehicle_choice",
            "auto_vehicle_model",
            "auto_input",
            "auto_start",
            "manual_entry",
            "manual_history",
            "manual_conf",
            "manual_vehicle_model",
            "manual_input",
            "manual_start",
        }
        return value if value in allowed else ""

    @staticmethod
    def _normalize_free_mode_screen_value(screen: str | None = None) -> str:
        value = str(screen or "").strip().lower()
        allowed = {
            "route_choice",
            "workflow",
            "auto_summary",
            "manual_review",
            "export",
        }
        return value if value in allowed else ""

    def _is_free_mode_session_context(self) -> bool:
        try:
            from ..campaign_manager import CAMPAIGN
            active_project = CAMPAIGN.get_active_project_name()
        except Exception:
            active_project = None

        return bool(getattr(self.app, "campaign_free_mode", False)) or not active_project

    def _get_campaign_annotation_state_path(self, project_name: str | None = None) -> Path | None:
        try:
            from ..campaign_manager import CAMPAIGN

            state_dir = CAMPAIGN.get_project_state_dir(project_name)
        except Exception:
            state_dir = None

        if state_dir is None:
            return None

        return Path(state_dir) / "annotation_ui_state.json"

    @staticmethod
    def _path_value_to_text(path_value) -> str:
        if path_value is None:
            return ""

        try:
            return str(path_value).strip()
        except RecursionError:
            pass
        except Exception:
            pass

        if isinstance(path_value, Path):
            visited: set[int] = set()

            def _flatten(value) -> str:
                if value is None:
                    return ""
                if isinstance(value, str):
                    return value.strip()
                if isinstance(value, bytes):
                    try:
                        return os.fsdecode(value).strip()
                    except Exception:
                        return ""
                if isinstance(value, Path):
                    obj_id = id(value)
                    if obj_id in visited:
                        return ""
                    visited.add(obj_id)
                    raw_parts = getattr(value, "_raw_paths", None) or ()
                    if raw_parts:
                        chunks = [_flatten(item) for item in raw_parts]
                        chunks = [chunk for chunk in chunks if chunk]
                        if not chunks:
                            return ""
                        try:
                            return os.path.join(*chunks).strip()
                        except Exception:
                            return " ".join(chunks).strip()
                try:
                    return os.fsdecode(os.fspath(value)).strip()
                except Exception:
                    try:
                        return str(value).strip()
                    except Exception:
                        return ""

            return _flatten(path_value)

        try:
            return os.fsdecode(os.fspath(path_value)).strip()
        except Exception:
            return ""

    @classmethod
    def _path_value_to_path(cls, path_value) -> Path | None:
        raw_value = cls._path_value_to_text(path_value)
        if not raw_value:
            return None
        try:
            return Path(raw_value)
        except Exception:
            return None

    @classmethod
    def _paths_equivalent(cls, left, right) -> bool:
        left_path = cls._path_value_to_path(left)
        right_path = cls._path_value_to_path(right)
        if left_path is None or right_path is None:
            return False

        try:
            return left_path.resolve() == right_path.resolve()
        except Exception:
            return str(left_path) == str(right_path)

    @classmethod
    def _path_is_within(cls, candidate, root) -> bool:
        candidate_path = cls._path_value_to_path(candidate)
        root_path = cls._path_value_to_path(root)
        if candidate_path is None or root_path is None:
            return False

        try:
            candidate_path = candidate_path.resolve()
            root_path = root_path.resolve()
        except Exception:
            return False

        try:
            candidate_path.relative_to(root_path)
            return True
        except Exception:
            return False

    @classmethod
    def _dedupe_paths(cls, candidates) -> list[Path]:
        unique: list[Path] = []
        seen: set[str] = set()

        for candidate in candidates or []:
            if not candidate:
                continue

            path = cls._path_value_to_path(candidate)
            if path is None:
                continue

            try:
                path = path.resolve()
            except Exception:
                pass

            key = str(path)
            if key in seen:
                continue

            seen.add(key)
            unique.append(path)

        return unique

    def _path_is_within_any(self, candidate, roots) -> bool:
        for root in roots or []:
            if self._path_is_within(candidate, root):
                return True
        return False

    def _get_annotation_output_base_dir(self) -> Path:
        if not self._is_free_mode_session_context():
            try:
                from ..campaign_manager import CAMPAIGN

                if CAMPAIGN.get_active_project_name():
                    stage_dir = CAMPAIGN.get_staging_dir("auto_ann")
                    if stage_dir is not None:
                        return Path(stage_dir)
            except Exception:
                pass

        return Path(CONFIG.get_auto_annotations_dir("plate"))

    def _get_annotation_run_roots(self) -> list[Path]:
        if self._is_free_mode_session_context():
            return self._dedupe_paths([CONFIG.get_auto_annotations_dir("plate")])

        roots = []
        try:
            from ..campaign_manager import CAMPAIGN

            if CAMPAIGN.get_active_project_name():
                roots.extend([
                    CAMPAIGN.get_staging_dir("auto_ann"),
                    CAMPAIGN.get_dir("auto_ann"),
                ])
        except Exception:
            pass

        if not roots:
            roots.append(CONFIG.get_auto_annotations_dir("plate"))

        return self._dedupe_paths(roots)

    def _coerce_annotation_output_dir(self, path_value) -> Path:
        fallback = self._get_annotation_output_base_dir()
        raw_value = self._path_value_to_text(path_value)

        candidate = self._path_value_to_path(raw_value) if raw_value else fallback
        if candidate is None:
            candidate = fallback

        if not self._path_is_within(candidate, fallback):
            if raw_value:
                workspace_root = Path(CONFIG.WORKSPACE_DIR)
                if self._path_is_within(candidate, workspace_root):
                    logger.debug(
                        "Z2 dostosowalo katalog wyjsciowy do aktualnego workspace: %s -> %s",
                        candidate,
                        fallback,
                    )
                else:
                    logger.warning(
                        "Z2 skorygowalo katalog wyjsciowy do bezpiecznego workspace: %s",
                        fallback,
                    )
            return fallback

        try:
            return candidate.resolve()
        except Exception:
            return candidate

    def _resolve_safe_annotation_run_dir(self, path_value, *, require_xml: bool = False) -> Path | None:
        candidate = self._path_value_to_path(path_value)
        if candidate is None:
            return None

        try:
            candidate = candidate.resolve()
        except Exception:
            pass

        if not self._path_is_within_any(candidate, self._get_annotation_run_roots()):
            return None

        try:
            if not candidate.exists() or not candidate.is_dir():
                return None
        except Exception:
            return None

        if require_xml and not (candidate / "annotations.xml").exists():
            return None

        return candidate

    def _get_annotation_session_text(
        self,
        key: str,
        default: str = "",
        *,
        allow_empty: bool = False,
        legacy_key: str | None = None,
    ) -> str:
        value = default
        if SESSION:
            try:
                value = SESSION.get("annotation", key, default)
            except Exception:
                value = default
            if legacy_key and (value is None or not str(value).strip()):
                try:
                    value = SESSION.get("annotation", legacy_key, default)
                except Exception:
                    value = default

        text = "" if value is None else str(value).strip()
        if text or allow_empty:
            return text
        return str(default)

    def _get_annotation_session_float(self, key: str, default: float) -> float:
        value = default
        if SESSION:
            try:
                value = SESSION.get("annotation", key, default)
            except Exception:
                value = default

        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _get_annotation_session_int(self, key: str, default: int) -> int:
        value = default
        if SESSION:
            try:
                value = SESSION.get("annotation", key, default)
            except Exception:
                value = default

        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _get_annotation_session_bool(self, key: str, default: bool) -> bool:
        value = default
        if SESSION:
            try:
                value = SESSION.get("annotation", key, default)
            except Exception:
                value = default

        if isinstance(value, bool):
            return value

        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def _get_annotation_session_list(self, key: str, default: list | None = None) -> list:
        fallback = list(default or [])
        value = fallback
        if SESSION:
            try:
                value = SESSION.get("annotation", key, fallback)
            except Exception:
                value = fallback

        if isinstance(value, list):
            return list(value)

        if isinstance(value, str):
            text = str(value or "").strip()
            if not text:
                return list(fallback)
            try:
                loaded = json.loads(text)
                if isinstance(loaded, list):
                    return loaded
            except Exception:
                return list(fallback)

        return list(fallback)

    def _load_free_mode_session_snapshot(self) -> dict:
        defaults = self._annotation_session_defaults()
        return {
            "input_dir": self._get_annotation_session_text("input_dir", defaults["input_dir"], legacy_key="images_dir"),
            "output_dir": self._get_annotation_session_text("output_dir", defaults["output_dir"]),
            "mode": self._normalize_mode_value(self._get_annotation_session_text("mode", defaults["mode"])),
            "vehicle_model": self._get_annotation_session_text("vehicle_model", defaults["vehicle_model"], allow_empty=True),
            "vehicle_custom": self._get_annotation_session_text("vehicle_custom", defaults["vehicle_custom"], allow_empty=True),
            "plate_custom": self._get_annotation_session_text("plate_custom", defaults["plate_custom"], allow_empty=True),
            "character_model": self._get_annotation_session_text("character_model", defaults["character_model"]),
            "character_custom": self._get_annotation_session_text("character_custom", defaults["character_custom"], allow_empty=True),
            "device": self._get_annotation_session_text("device", defaults["device"]),
            "conf": self._get_annotation_session_float("conf", defaults["conf"]),
            "plate_dataset_run": self._get_annotation_session_text("plate_dataset_run", defaults["plate_dataset_run"], allow_empty=True),
            "plate_dataset_images": self._get_annotation_session_text("plate_dataset_images", defaults["plate_dataset_images"], allow_empty=True),
            "plate_train_pct": self._get_annotation_session_float("plate_train_pct", defaults["plate_train_pct"]),
            "plate_val_pct": self._get_annotation_session_float("plate_val_pct", defaults["plate_val_pct"]),
            "manual_xml_template": self._get_annotation_session_bool("manual_xml_template", defaults["manual_xml_template"]),
            "manual_vehicle_assist": self._get_annotation_session_bool("manual_vehicle_assist", defaults["manual_vehicle_assist"]),
            "workflow_route": self._get_annotation_session_text("workflow_route", defaults["workflow_route"], allow_empty=True),
            "manual_entry_mode": self._get_annotation_session_text("manual_entry_mode", defaults["manual_entry_mode"]),
            "auto_vehicle_choice": self._get_annotation_session_text("auto_vehicle_choice", defaults["auto_vehicle_choice"]),
            "workflow_step": self._get_annotation_session_text("workflow_step", defaults["workflow_step"], allow_empty=True),
            "free_mode_screen": self._get_annotation_session_text("free_mode_screen", defaults["free_mode_screen"]),
            "manual_review_active": self._get_annotation_session_bool("manual_review_active", defaults["manual_review_active"]),
            "manual_review_from_auto": self._get_annotation_session_bool("manual_review_from_auto", defaults["manual_review_from_auto"]),
            "manual_review_export_ready": self._get_annotation_session_bool("manual_review_export_ready", defaults["manual_review_export_ready"]),
            "manual_review_history": self._get_annotation_session_list("manual_review_history", defaults["manual_review_history"]),
            "last_preview_run_dir": self._get_annotation_session_text("last_preview_run_dir", defaults["last_preview_run_dir"], allow_empty=True),
            "last_preview_index": self._get_annotation_session_int("last_preview_index", defaults["last_preview_index"]),
            "last_preview_filename": self._get_annotation_session_text("last_preview_filename", defaults["last_preview_filename"], allow_empty=True),
        }

    def _collect_free_mode_session_snapshot(self) -> dict:
        run_dir_value = ""
        selected_ann = self._get_preview_annotation()
        input_dir_value = str(self.input_dir_var.get() or "").strip()
        if (
            self._normalize_workflow_route_value() == "manual"
            and self._normalize_manual_entry_mode() == "new"
            and not self._manual_review_active
            and not self._manual_review_from_auto
            and not self.is_processing
        ):
            input_dir_value = ""

        for candidate in (
            getattr(self, "current_annotation_run_dir", None),
            getattr(self, "last_staging_run_dir", None),
            str(self.plate_dataset_run_var.get() or "").strip(),
        ):
            safe_run_dir = self._resolve_safe_annotation_run_dir(candidate)
            if safe_run_dir is not None:
                run_dir_value = str(safe_run_dir)
                break

        return {
            "input_dir": input_dir_value,
            "output_dir": str(self._coerce_annotation_output_dir(self.output_dir_var.get() or "")),
            "mode": self._normalize_mode_value(),
            "vehicle_model": str(self.vehicle_model_var.get() or "").strip(),
            "vehicle_custom": str(self.vehicle_custom_var.get() or "").strip(),
            "plate_custom": str(self.plate_custom_var.get() or "").strip(),
            "character_model": str(self.character_model_var.get() or "").strip(),
            "character_custom": str(self.character_custom_var.get() or "").strip(),
            "device": self._get_effective_yolo_device_choice(),
            "conf": float(self.conf_var.get()),
            "plate_dataset_run": str(self._resolve_safe_annotation_run_dir(self.plate_dataset_run_var.get()) or ""),
            "plate_dataset_images": str(self.plate_dataset_images_var.get() or "").strip(),
            "plate_train_pct": float(self.plate_train_pct.get()),
            "plate_val_pct": float(self.plate_val_pct.get()),
            "manual_xml_template": bool(self.manual_xml_template_var.get()),
            "manual_vehicle_assist": bool(self.manual_vehicle_assist_var.get()),
            "workflow_route": self._normalize_workflow_route_value(),
            "manual_entry_mode": self._normalize_manual_entry_mode(),
            "auto_vehicle_choice": self._normalize_auto_vehicle_choice(),
            "workflow_step": self._get_workflow_step(),
            "free_mode_screen": self._coerce_free_mode_screen(),
            "manual_review_active": bool(self._manual_review_active),
            "manual_review_from_auto": bool(self._manual_review_from_auto),
            "manual_review_export_ready": bool(self._manual_review_export_ready),
            "manual_review_history": list(self._manual_review_history_entries or []),
            "last_preview_run_dir": run_dir_value,
            "last_preview_index": (
                int(self.current_preview_index)
                if self.current_preview_index is not None
                else -1
            ),
            "last_preview_filename": str(getattr(selected_ann, "filename", "") or "").strip(),
        }

    def _collect_campaign_project_snapshot(self) -> dict:
        selected_ann = self._get_preview_annotation()
        run_dir_value = ""
        for candidate in (
            getattr(self, "current_annotation_run_dir", None),
            getattr(self, "last_staging_run_dir", None),
            str(self.plate_dataset_run_var.get() or "").strip(),
        ):
            safe_run_dir = self._resolve_safe_annotation_run_dir(candidate)
            if safe_run_dir is not None:
                run_dir_value = str(safe_run_dir)
                break

        try:
            from ..campaign_manager import CAMPAIGN
            active_project = CAMPAIGN.get_active_project_name()
            iteration_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            active_project = ""
            iteration_num = 1

        return {
            "project": str(active_project or "").strip(),
            "iteration": int(iteration_num),
            "input_dir": str(self.input_dir_var.get() or "").strip(),
            "output_dir": str(self._coerce_annotation_output_dir(self.output_dir_var.get() or "")),
            "mode": self._normalize_mode_value(),
            "vehicle_model": str(self.vehicle_model_var.get() or "").strip(),
            "vehicle_custom": str(self.vehicle_custom_var.get() or "").strip(),
            "plate_custom": str(self.plate_custom_var.get() or "").strip(),
            "character_model": str(self.character_model_var.get() or "").strip(),
            "character_custom": str(self.character_custom_var.get() or "").strip(),
            "device": self._get_effective_yolo_device_choice(),
            "conf": float(self.conf_var.get()),
            "plate_dataset_run": str(self._resolve_safe_annotation_run_dir(self.plate_dataset_run_var.get()) or ""),
            "plate_dataset_images": str(self.plate_dataset_images_var.get() or "").strip(),
            "plate_train_pct": float(self.plate_train_pct.get()),
            "plate_val_pct": float(self.plate_val_pct.get()),
            "manual_xml_template": bool(self.manual_xml_template_var.get()),
            "manual_vehicle_assist": bool(self.manual_vehicle_assist_var.get()),
            "workflow_route": self._normalize_workflow_route_value(),
            "manual_entry_mode": self._normalize_manual_entry_mode(),
            "auto_vehicle_choice": self._normalize_auto_vehicle_choice(),
            "workflow_step": self._get_workflow_step(),
            "manual_review_active": bool(self._manual_review_active),
            "manual_review_from_auto": bool(self._manual_review_from_auto),
            "manual_review_export_ready": bool(self._manual_review_export_ready),
            "manual_review_history": list(self._manual_review_history_entries or []),
            "last_preview_run_dir": run_dir_value,
            "last_preview_index": (
                int(self.current_preview_index)
                if self.current_preview_index is not None
                else -1
            ),
            "last_preview_filename": str(getattr(selected_ann, "filename", "") or "").strip(),
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

    def _sanitize_free_mode_session_snapshot(self, session_state: dict | None = None) -> dict:
        defaults = self._annotation_session_defaults()
        state = dict(session_state or {})
        project_root = CONFIG.DIR_9_PROJECTS

        def _sanitize_path_value(key: str, fallback: str = ""):
            raw_value = str(state.get(key) or "").strip()
            if raw_value and self._path_is_within(raw_value, project_root):
                state[key] = fallback
            elif raw_value:
                state[key] = raw_value
            else:
                state[key] = fallback

        _sanitize_path_value("input_dir", defaults["input_dir"])
        _sanitize_path_value("output_dir", defaults["output_dir"])
        _sanitize_path_value("vehicle_custom", "")
        _sanitize_path_value("plate_custom", "")
        _sanitize_path_value("character_custom", "")
        _sanitize_path_value("plate_dataset_run", "")
        _sanitize_path_value("plate_dataset_images", "")
        _sanitize_path_value("last_preview_run_dir", "")

        if not str(state.get("vehicle_custom") or "").strip() and str(state.get("vehicle_model") or "").strip() == "Custom":
            state["vehicle_model"] = defaults["vehicle_model"]

        state["free_mode_screen"] = (
            self._normalize_free_mode_screen_value(state.get("free_mode_screen"))
            or defaults["free_mode_screen"]
        )

        return state

    def capture_free_mode_snapshot_for_project_return(self):
        try:
            snapshot = self._collect_free_mode_session_snapshot()
        except Exception as e:
            logger.debug(f"Nie udalo sie zapisac migawki free mode przed wejsciem w projekt: {e}")
            return

        self._pre_campaign_free_mode_snapshot = self._sanitize_free_mode_session_snapshot(snapshot)

    def _load_campaign_project_snapshot(self) -> dict:
        snapshot_path = self._get_campaign_annotation_state_path()
        if snapshot_path is None or not snapshot_path.exists():
            return {}

        try:
            loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        return loaded if isinstance(loaded, dict) else {}

    def _save_campaign_project_snapshot(self) -> bool:
        snapshot_path = self._get_campaign_annotation_state_path()
        if snapshot_path is None:
            return False

        try:
            payload = self._collect_campaign_project_snapshot()
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            logger.debug(f"Nie udalo sie zapisac projektowego stanu Z2: {e}")
            return False

    def reset_campaign_iteration_route_state(self, new_target: str | None = None) -> dict:
        result = {
            "removed_runs": 0,
            "removed_snapshot": False,
            "removed_stage": False,
        }

        try:
            from ..campaign_manager import CAMPAIGN

            active_project = str(CAMPAIGN.get_active_project_name() or "").strip()
            if not active_project:
                return result

            target = str(new_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
            if target not in {"plate", "char"}:
                target = "plate"

            pending = getattr(self, "_free_mode_session_save_after_id", None)
            if pending:
                try:
                    self.frame.after_cancel(pending)
                except Exception:
                    pass
            self._free_mode_session_save_after_id = None

            candidate_inputs: list[Path] = []
            iteration_raw_dir = CAMPAIGN.get_iteration_raw_dir()
            if iteration_raw_dir is not None:
                candidate_inputs.append(Path(iteration_raw_dir))

            raw_root = CAMPAIGN.get_dir("raw")
            if raw_root is not None:
                iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
                raw_iter_dir = Path(raw_root) / f"Iteracja_{iter_num:03d}"
                candidate_inputs.append(raw_iter_dir if raw_iter_dir.exists() else Path(raw_root))

            try:
                candidate_inputs.append(self._get_manual_plate_stage_images_dir())
            except Exception:
                pass

            stored_manual_source = {}
            try:
                stored_manual_source = CAMPAIGN.get_last_plate_manual_source()
            except Exception:
                stored_manual_source = {}

            manual_run_keep = set()
            for candidate in (
                str(stored_manual_source.get("source_run_path") or "").strip(),
                str(stored_manual_source.get("source_xml_path") or "").strip(),
            ):
                if not candidate:
                    continue
                try:
                    manual_path = Path(candidate)
                    if manual_path.suffix.lower() == ".xml":
                        manual_path = manual_path.parent
                    manual_run_keep.add(str(manual_path.resolve()))
                except Exception:
                    try:
                        manual_run_keep.add(str(Path(candidate)))
                    except Exception:
                        pass

            explicit_run_dirs = set()
            for candidate in (
                str(CAMPAIGN.get_step2_staging_run() or "").strip(),
                str(getattr(self, "current_annotation_run_dir", "") or "").strip(),
                str(getattr(self, "last_staging_run_dir", "") or "").strip(),
                str(self.plate_dataset_run_var.get() or "").strip(),
            ):
                if not candidate:
                    continue
                try:
                    explicit_run_dirs.add(str(Path(candidate).resolve()))
                except Exception:
                    explicit_run_dirs.add(str(Path(candidate)))

            search_roots = []
            for root_candidate in (CAMPAIGN.get_staging_dir("auto_ann"), CAMPAIGN.get_dir("auto_ann")):
                if root_candidate is not None:
                    search_roots.append(Path(root_candidate))

            visited = set()
            for root in search_roots:
                try:
                    if not root.exists() or not root.is_dir():
                        continue
                except Exception:
                    continue

                try:
                    run_paths = list(root.rglob("run_*"))
                except Exception:
                    continue

                for run_dir in run_paths:
                    try:
                        if not run_dir.is_dir():
                            continue
                        run_key = str(run_dir.resolve())
                    except Exception:
                        try:
                            run_key = str(Path(run_dir))
                        except Exception:
                            continue

                    if run_key in visited:
                        continue
                    visited.add(run_key)

                    manifest = {}
                    remove_run = run_key in explicit_run_dirs
                    if not remove_run:
                        manifest = self._load_annotation_run_manifest(run_dir)
                        manifest_input = str(manifest.get("input_dir") or "").strip()
                        if manifest_input:
                            remove_run = any(
                                self._paths_equivalent(manifest_input, candidate_input)
                                for candidate_input in candidate_inputs
                            )

                    if not remove_run or not self._path_is_within(run_dir, root):
                        continue

                    if run_key in manual_run_keep or self._annotation_run_manifest_has_manual_value(manifest):
                        continue

                    try:
                        shutil.rmtree(run_dir)
                        result["removed_runs"] += 1
                    except Exception as e:
                        logger.debug(f"Nie udalo sie usunac runu po zmianie toru E2 ({run_dir}): {e}")

            stage_root = CAMPAIGN.get_staging_dir("plate_stage")
            stage_dir = self._get_manual_plate_stage_dir()
            try:
                if (
                    stage_root is not None
                    and stage_dir.exists()
                    and self._path_is_within(stage_dir, stage_root)
                ):
                    shutil.rmtree(stage_dir)
                    result["removed_stage"] = True
            except Exception as e:
                logger.debug(f"Nie udalo sie wyczyscic stage po zmianie toru E2: {e}")

            snapshot_path = self._get_campaign_annotation_state_path(active_project)
            try:
                if snapshot_path is not None and snapshot_path.exists():
                    snapshot_path.unlink()
                    result["removed_snapshot"] = True
            except Exception as e:
                logger.debug(f"Nie udalo sie usunac snapshotu Z2 po zmianie toru E2: {e}")

            self._preview_session_restore_index = -1
            self._preview_session_restore_filename = ""

            auto_out = CAMPAIGN.get_staging_dir("auto_ann")
            if raw_root is not None and auto_out is not None:
                iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
                input_dir = Path(raw_root) / f"Iteracja_{iter_num:03d}"
                if not input_dir.exists():
                    input_dir = Path(raw_root)

                self.apply_campaign_context(
                    input_dir,
                    Path(auto_out),
                    manual_template=(target == "plate"),
                    mode_text="C: Pojazdy + tablice",
                    restore_project_state=False,
                )
                self.flush_free_mode_session_state()
        except Exception as e:
            logger.debug(f"Nie udalo sie zresetowac stanu iteracji po zmianie toru E2: {e}")

        return result

    @staticmethod
    def _dir_has_images(path_like) -> bool:
        if not path_like:
            return False

        try:
            return bool(get_image_files(Path(path_like)))
        except Exception:
            return False

    def _get_campaign_auto_annotation_bootstrap(self, iteration_target: str | None = None) -> dict:
        bootstrap = {
            "input_dir": None,
            "input_source": "raw",
            "manual_template": False,
            "plate_model_path": "",
            "restore_run_dir": None,
        }

        try:
            from ..campaign_manager import CAMPAIGN

            if not CAMPAIGN.get_active_project_name():
                return bootstrap

            target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
            raw_dir = CAMPAIGN.get_dir("raw")
            if raw_dir is None:
                return bootstrap

            iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
            raw_root = Path(raw_dir)
            iter_dir = raw_root / f"Iteracja_{iter_num:03d}"
            default_input = iter_dir if iter_dir.exists() else raw_root
            auto_dir = CAMPAIGN.get_dir("auto_ann")
            project_start_mode = str(getattr(CAMPAIGN, "get_project_start_mode", lambda *_a, **_k: "fresh")() or "fresh").strip().lower()

            plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
            plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())

            bootstrap["input_dir"] = default_input
            bootstrap["plate_model_path"] = plate_model_path if plate_model_ready else ""
            bootstrap["manual_template"] = bool(target == "plate" and not plate_model_ready)

            manual_source_run = self._find_reused_manual_source_run(default_input)
            if manual_source_run is not None and (manual_source_run / "annotations.xml").exists():
                bootstrap["restore_run_dir"] = manual_source_run
                bootstrap["input_source"] = "manual_source_run"
            elif iter_num == 1 and project_start_mode == "assets":
                stored_manual_source = CAMPAIGN.get_last_plate_manual_source()
                for raw_candidate in (
                    str(stored_manual_source.get("source_run_path") or "").strip(),
                    str(stored_manual_source.get("source_xml_path") or "").strip(),
                ):
                    if not raw_candidate:
                        continue
                    try:
                        run_candidate = Path(raw_candidate)
                        if run_candidate.suffix.lower() == ".xml":
                            run_candidate = run_candidate.parent
                    except Exception:
                        continue
                    if run_candidate.exists() and run_candidate.is_dir() and (run_candidate / "annotations.xml").exists():
                        bootstrap["restore_run_dir"] = run_candidate
                        bootstrap["input_source"] = "project_imported_manual_source"
                        break

                stored_input_path = str(stored_manual_source.get("source_input_path") or "").strip()
                if stored_input_path and not self._dir_has_images(default_input):
                    try:
                        stored_input_dir = Path(stored_input_path)
                    except Exception:
                        stored_input_dir = None
                    if stored_input_dir is not None and self._dir_has_images(stored_input_dir):
                        bootstrap["input_dir"] = stored_input_dir
                        if bootstrap["input_source"] == "raw":
                            bootstrap["input_source"] = "project_imported_images"

            reuse_source_input = None
            try:
                ingest_manifest = CAMPAIGN.load_ingest_manifest(iter_num)
            except Exception:
                ingest_manifest = {}

            if isinstance(ingest_manifest, dict):
                selection_mode = str(ingest_manifest.get("selection_mode") or "").strip().lower()
                try:
                    reused_from_iteration = int(ingest_manifest.get("reused_from_iteration", 0) or 0)
                except (TypeError, ValueError):
                    reused_from_iteration = 0

                if selection_mode == "iteration_reuse" and reused_from_iteration > 0:
                    reuse_source_input = CAMPAIGN.get_iteration_raw_dir(reused_from_iteration)

            if reuse_source_input is not None and auto_dir is not None:
                reuse_source_input = Path(reuse_source_input)
                manual_reuse_run = self._find_reused_manual_source_run(reuse_source_input)
                if manual_reuse_run is not None and (manual_reuse_run / "annotations.xml").exists():
                    bootstrap["restore_run_dir"] = manual_reuse_run
                    bootstrap["input_source"] = "reused_manual_source_run"
                else:
                    training_source_run = self._find_reused_training_source_run(reuse_source_input)
                    if training_source_run is not None and (training_source_run / "annotations.xml").exists():
                        bootstrap["restore_run_dir"] = training_source_run
                        bootstrap["input_source"] = "reused_training_source_run"
                    else:
                        reuse_run = self._find_latest_annotation_run_for_input(
                            reuse_source_input,
                            [Path(auto_dir)],
                        )
                        if reuse_run is not None and (reuse_run / "annotations.xml").exists():
                            bootstrap["restore_run_dir"] = reuse_run
                            bootstrap["input_source"] = "reused_iteration_run"

            if target != "plate":
                return bootstrap

            if self._dir_has_images(default_input):
                return bootstrap

            current_stage = self._get_manual_plate_stage_images_dir()
            if self._dir_has_images(current_stage):
                bootstrap["input_dir"] = current_stage
                bootstrap["input_source"] = "stage_current_iteration"
                return bootstrap

            if iter_num > 1:
                prev_stage = self._get_manual_plate_stage_dir().parent / f"Iteracja_{iter_num - 1:03d}" / "images"
                if self._dir_has_images(prev_stage):
                    bootstrap["input_dir"] = prev_stage
                    bootstrap["input_source"] = "stage_previous_iteration"
                    return bootstrap

            latest_run = None
            if auto_dir is not None:
                latest_run = self._find_latest_annotation_run_dir(Path(auto_dir))

            if latest_run is None:
                return bootstrap

            manifest = self._load_annotation_run_manifest(latest_run)
            manifest_input = str(manifest.get("input_dir") or "").strip()
            if manifest_input and self._dir_has_images(manifest_input):
                bootstrap["input_dir"] = Path(manifest_input)
                bootstrap["input_source"] = "latest_approved_run"
                bootstrap["restore_run_dir"] = latest_run
                return bootstrap

            if (latest_run / "annotations.xml").exists():
                bootstrap["input_source"] = "latest_approved_run"
                bootstrap["restore_run_dir"] = latest_run
        except Exception as e:
            logger.debug(f"Nie udalo sie zbudowac bootstrapu Z2 dla kampanii: {e}")

        return bootstrap

    def _get_campaign_previous_manual_source_bundle(self) -> dict:
        if self._is_free_mode_session_context():
            return {"input_dir": None, "run_dir": None, "xml_path": None, "image_dirs": [], "source_label": "wcześniejszej iteracji"}

        try:
            from ..campaign_manager import CAMPAIGN

            if not CAMPAIGN.get_active_project_name():
                return {"input_dir": None, "run_dir": None, "xml_path": None, "image_dirs": [], "source_label": "wcześniejszej iteracji"}

            stored_manual_source = CAMPAIGN.get_last_plate_manual_source()
            run_dir = None
            xml_path = None

            for raw_candidate in (
                str(stored_manual_source.get("source_run_path") or "").strip(),
                str(stored_manual_source.get("source_xml_path") or "").strip(),
            ):
                if not raw_candidate:
                    continue
                try:
                    candidate = Path(raw_candidate)
                    if candidate.suffix.lower() == ".xml":
                        xml_path = candidate if candidate.exists() else xml_path
                        candidate = candidate.parent
                    if candidate.exists() and candidate.is_dir() and (candidate / "annotations.xml").exists():
                        run_dir = candidate
                        xml_path = candidate / "annotations.xml"
                        break
                except Exception:
                    continue

            if run_dir is None:
                run_dir = self._find_reused_manual_source_run(None)
                if run_dir is not None and (run_dir / "annotations.xml").exists():
                    xml_path = run_dir / "annotations.xml"

            input_dir_candidates = []
            source_input_path = str(stored_manual_source.get("source_input_path") or "").strip()
            if source_input_path:
                input_dir_candidates.append(source_input_path)

            if run_dir is not None:
                manifest = self._load_annotation_run_manifest(run_dir)
                manifest_input_dir = str(manifest.get("input_dir") or "").strip()
                if manifest_input_dir:
                    input_dir_candidates.append(manifest_input_dir)

            resolved_input_dir = None
            resolved_image_dirs: list[Path] = []
            for raw_dir in input_dir_candidates:
                try:
                    candidate_dir = Path(raw_dir)
                except Exception:
                    continue
                if self._dir_has_images(candidate_dir):
                    if all(str(existing) != str(candidate_dir) for existing in resolved_image_dirs):
                        resolved_image_dirs.append(candidate_dir)
                    if resolved_input_dir is None:
                        resolved_input_dir = candidate_dir
            if run_dir is not None:
                run_images_dir = run_dir / "images"
                if self._dir_has_images(run_images_dir):
                    if all(str(existing) != str(run_images_dir) for existing in resolved_image_dirs):
                        resolved_image_dirs.append(run_images_dir)

            source_label = self._extract_iteration_label_from_path(
                resolved_input_dir or run_dir or source_input_path
            )
            return {
                "input_dir": resolved_input_dir,
                "run_dir": run_dir,
                "xml_path": xml_path if xml_path is not None and xml_path.exists() else None,
                "image_dirs": resolved_image_dirs,
                "source_label": source_label,
            }
        except Exception:
            return {"input_dir": None, "run_dir": None, "xml_path": None, "image_dirs": [], "source_label": "wcześniejszej iteracji"}

    @staticmethod
    def _extract_iteration_label_from_path(path_like) -> str:
        if not path_like:
            return "wcześniejszej iteracji"

        try:
            path = Path(path_like)
        except Exception:
            path = None

        for part in reversed(list(path.parts) if path is not None else [str(path_like)]):
            match = re.search(r"iteracja[_\-\s]*0*(\d+)", str(part), flags=re.IGNORECASE)
            if match:
                try:
                    return f"Iteracji {int(match.group(1))}"
                except Exception:
                    return f"Iteracji {match.group(1)}"

        return "wcześniejszej iteracji"

    @staticmethod
    def _load_cvat_plate_annotated_filenames(xml_path: Path | None) -> list[str]:
        if xml_path is None:
            return []
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception:
            return []

        filenames: list[str] = []
        seen: set[str] = set()
        for image_el in root.findall(".//image"):
            filename = str(image_el.get("name", "") or "").strip()
            if not filename or filename in seen:
                continue
            has_plate = False
            for poly_el in image_el.findall("polygon"):
                label = str(poly_el.get("label", "") or "").strip().lower()
                if label in CONFIG.PLATE_LABELS:
                    has_plate = True
                    break
            if not has_plate:
                for box_el in image_el.findall("box"):
                    label = str(box_el.get("label", "") or "").strip().lower()
                    if label in CONFIG.PLATE_LABELS:
                        has_plate = True
                        break
            if has_plate:
                seen.add(filename)
                filenames.append(filename)
        return filenames

    def _collect_campaign_auto_annotation_sources(
        self,
        base_input_dir: Path | None,
        *,
        include_previous: bool | None = None,
    ) -> dict:
        plan = {
            "base_input_dir": None,
            "previous_manual_dir": None,
            "previous_xml_path": None,
            "previous_image_dirs": [],
            "source_label": "wcześniejszej iteracji",
            "image_paths": [],
            "image_map": {},
            "reused_filenames": set(),
            "reused_count": 0,
            "base_count": 0,
            "total_count": 0,
            "has_previous_manual": False,
        }

        try:
            base_dir = Path(base_input_dir) if base_input_dir is not None else None
        except Exception:
            base_dir = None

        previous_bundle = self._get_campaign_previous_manual_source_bundle()
        previous_manual_dir = previous_bundle.get("input_dir")
        if base_dir is not None:
            plan["base_input_dir"] = base_dir
        previous_xml_path = previous_bundle.get("xml_path")
        previous_image_dirs = [
            path
            for path in list(previous_bundle.get("image_dirs") or [])
            if isinstance(path, Path)
        ]

        if isinstance(previous_manual_dir, Path):
            plan["previous_manual_dir"] = previous_manual_dir
            plan["has_previous_manual"] = True
            plan["source_label"] = str(previous_bundle.get("source_label") or self._extract_iteration_label_from_path(previous_manual_dir))
        if isinstance(previous_xml_path, Path) and previous_xml_path.exists():
            plan["previous_xml_path"] = previous_xml_path
        if previous_image_dirs:
            plan["previous_image_dirs"] = previous_image_dirs

        if include_previous is None:
            include_previous = bool(self.campaign_reuse_manual_var.get())

        base_images = get_image_files(base_dir) if base_dir is not None and self._dir_has_images(base_dir) else []
        previous_images = []
        if previous_manual_dir is not None:
            same_dir = False
            if base_dir is not None:
                try:
                    same_dir = previous_manual_dir.resolve() == base_dir.resolve()
                except Exception:
                    same_dir = str(previous_manual_dir) == str(base_dir)
            if not same_dir:
                annotated_filenames = self._load_cvat_plate_annotated_filenames(previous_xml_path)
                if annotated_filenames:
                    resolved_previous_images: list[Path] = []
                    for filename in annotated_filenames:
                        resolved_path = None
                        for image_dir in previous_image_dirs or ([previous_manual_dir] if previous_manual_dir is not None else []):
                            try:
                                candidate = Path(image_dir) / filename
                            except Exception:
                                continue
                            if candidate.exists():
                                resolved_path = candidate
                                break
                        if resolved_path is not None:
                            resolved_previous_images.append(resolved_path)
                    previous_images = resolved_previous_images

        image_paths: list[Path] = []
        image_map: dict[str, Path] = {}
        reused_filenames: set[str] = set()
        seen_names: set[str] = set()

        if include_previous:
            for image_path in previous_images:
                filename = image_path.name
                if filename in seen_names:
                    continue
                seen_names.add(filename)
                image_paths.append(image_path)
                image_map[filename] = image_path
                reused_filenames.add(filename)

        for image_path in base_images:
            filename = image_path.name
            if filename in seen_names:
                continue
            seen_names.add(filename)
            image_paths.append(image_path)
            image_map[filename] = image_path

        plan["image_paths"] = image_paths
        plan["image_map"] = image_map
        plan["reused_filenames"] = reused_filenames
        plan["reused_count"] = len(reused_filenames)
        plan["base_count"] = max(0, len(image_paths) - len(reused_filenames))
        plan["total_count"] = len(image_paths)
        return plan

    def _clear_campaign_manual_reuse_context(self):
        self._campaign_reuse_manual_filenames = set()
        self._campaign_reuse_manual_summary = {}

    @staticmethod
    def _campaign_reuse_manual_badge() -> str:
        return "[RĘ↺]"

    def _apply_campaign_manual_reuse_context(self, source_plan: dict | None = None):
        if not isinstance(source_plan, dict):
            self._clear_campaign_manual_reuse_context()
            return

        reused_filenames = set(source_plan.get("reused_filenames") or set())
        if not reused_filenames:
            self._clear_campaign_manual_reuse_context()
            return

        self._campaign_reuse_manual_filenames = reused_filenames
        self._campaign_reuse_manual_summary = {
            "source_label": str(source_plan.get("source_label") or "wcześniejszej iteracji"),
            "reused_count": int(source_plan.get("reused_count", 0) or 0),
            "base_count": int(source_plan.get("base_count", 0) or 0),
            "total_count": int(source_plan.get("total_count", 0) or 0),
        }

    def _on_campaign_reuse_manual_toggle(self):
        self._refresh_campaign_manual_reuse_option_ui()

        if self._is_free_mode_session_context() or getattr(self, "is_processing", False):
            return

        if getattr(self, "current_annotation_xml_path", None):
            return

        input_dir_raw = str(self.input_dir_var.get() or "").strip()
        if not input_dir_raw:
            return

        try:
            self._prime_campaign_source_preview(Path(input_dir_raw))
        except Exception as e:
            logger.debug(f"Nie udało się odświeżyć podglądu Z2 po zmianie checkboxu dołączania ręcznych zdjęć: {e}")

    def _get_campaign_manual_reuse_ui_state(self) -> dict:
        state = {
            "show_option": False,
            "source_label": "wcześniejszej iteracji",
            "reused_count": 0,
            "base_count": 0,
            "total_count": 0,
        }

        if self._is_free_mode_session_context():
            return state

        try:
            from ..campaign_manager import CAMPAIGN

            target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        except Exception:
            target = ""

        current_input_dir = str(self.input_dir_var.get() or "").strip()
        try:
            current_input_path = Path(current_input_dir) if current_input_dir else None
        except Exception:
            current_input_path = None

        previous_bundle = self._get_campaign_previous_manual_source_bundle()
        previous_manual_dir = previous_bundle.get("input_dir")
        previous_xml_path = previous_bundle.get("xml_path")

        state["source_label"] = str(previous_bundle.get("source_label") or state["source_label"])
        state["reused_count"] = len(self._load_cvat_plate_annotated_filenames(previous_xml_path))
        try:
            state["base_count"] = (
                len(get_image_files(current_input_path))
                if current_input_path is not None and self._dir_has_images(current_input_path)
                else 0
            )
        except Exception:
            state["base_count"] = 0
        state["total_count"] = int(state["base_count"]) + int(state["reused_count"])
        state["show_option"] = bool(
            target == "plate"
            and self._get_workflow_route() == "auto"
            and isinstance(previous_manual_dir, Path)
            and str(previous_manual_dir) != current_input_dir
            and int(state["reused_count"] or 0) > 0
        )
        return state

    def _refresh_campaign_manual_reuse_option_ui(self):
        check = getattr(self, "campaign_reuse_manual_check", None)
        hint = getattr(self, "campaign_reuse_manual_hint_lbl", None)
        if check is None or hint is None:
            return

        ui_state = self._get_campaign_manual_reuse_ui_state()
        show_option = bool(ui_state.get("show_option"))
        source_label = str(ui_state.get("source_label") or "wcześniejszej iteracji")
        reused_count = int(ui_state.get("reused_count", 0) or 0)
        base_count = int(ui_state.get("base_count", 0) or 0)
        total_count = int(ui_state.get("total_count", 0) or 0)

        if not show_option:
            self.campaign_reuse_manual_var.set(False)
            self.campaign_reuse_manual_hint_var.set("")
            try:
                check.configure(text="Dołącz ręcznie anotowane zdjęcia z wcześniejszych iteracji")
            except Exception:
                pass

        self._set_widget_packed(
            check,
            show_option,
            anchor=tk.W,
            pady=(6, 2),
        )
        self._set_widget_packed(
            hint,
            show_option,
            fill=tk.X,
            pady=(0, 6),
        )

        if show_option:
            try:
                check.configure(
                    text=f"Dołącz {reused_count} ręcznie anotowanych zdjęć z {source_label} ({self._campaign_reuse_manual_badge()})"
                )
            except Exception:
                pass

            if bool(self.campaign_reuse_manual_var.get()):
                self.campaign_reuse_manual_hint_var.set(
                    f"Dołączysz {reused_count} ręcznie anotowanych obrazów z {source_label}. Razem do autoanotacji "
                    f"trafi {total_count} obrazów: {base_count} z bieżącej paczki oraz {reused_count} z wcześniejszej iteracji. "
                    f"Na liście po prawej pozycje z wcześniejszej iteracji są oznaczone jako {self._campaign_reuse_manual_badge()}. "
                    "Uwaga: poprzednie ręczne anotacje tych zdjęć "
                    "nie zostaną zachowane w nowym runie."
                )
            else:
                self.campaign_reuse_manual_hint_var.set(
                    f"Możesz dołączyć {reused_count} ręcznie anotowanych obrazów z {source_label}. Po zaznaczeniu "
                    f"checkboxu pojawią się one na liście po prawej z oznaczeniem {self._campaign_reuse_manual_badge()}. Uwaga: poprzednie ręczne "
                    "anotacje tych zdjęć nie zostaną zachowane w nowym runie."
                )

    def _restore_preview_from_annotation_run(self, run_dir: Path | None) -> bool:
        if run_dir is None:
            return False

        run_dir = self._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        if run_dir is None:
            return False

        try:
            xml_path = run_dir / "annotations.xml"
            manifest = self._load_annotation_run_manifest(run_dir)
            annotations = self._parse_cvat_preview_annotations(xml_path)
            if not annotations:
                return False

            image_dir_candidates = []
            seen_candidates = set()
            for raw_value in (
                str(manifest.get("imported_source_input_dir") or "").strip(),
                str(manifest.get("input_dir") or "").strip(),
                str(self.input_dir_var.get() or "").strip(),
                str(self.plate_dataset_images_var.get() or "").strip(),
                str(run_dir / "images"),
                str(run_dir),
            ):
                if not raw_value:
                    continue
                try:
                    candidate = Path(raw_value)
                    candidate_key = str(candidate.resolve())
                except Exception:
                    candidate = Path(raw_value)
                    candidate_key = str(candidate)
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                image_dir_candidates.append(candidate)

            image_dir = None
            fallback_dir = None
            best_match_count = -1
            sample_filenames = [
                str(getattr(ann, "filename", "") or "").strip()
                for ann in annotations
                if str(getattr(ann, "filename", "") or "").strip()
            ][:25]

            for candidate in image_dir_candidates:
                try:
                    if not candidate.exists() or not candidate.is_dir():
                        continue
                except Exception:
                    continue

                if fallback_dir is None:
                    fallback_dir = candidate

                match_count = 0
                for filename in sample_filenames:
                    try:
                        if (candidate / Path(filename)).exists():
                            match_count += 1
                    except Exception:
                        continue

                if match_count > best_match_count:
                    best_match_count = match_count
                    image_dir = candidate

            if image_dir is None:
                image_dir = fallback_dir
            if image_dir is None:
                return False

            self._clear_preview_editor_state(clear_dirty=True)
            self.current_annotations = annotations
            self.current_input_dir = image_dir
            self._preview_image_path_map = {}
            self._clear_campaign_manual_reuse_context()
            self.input_dir_var.set(str(image_dir))
            self.plate_dataset_images_var.set(str(image_dir))
            self.current_annotation_run_dir = run_dir
            self.current_annotation_xml_path = xml_path
            self.last_staging_run_dir = run_dir
            self._load_plate_dataset_context_from_run(run_dir, force_images_update=False)

            try:
                self._restore_campaign_step2_generated_from_run(run_dir, only_when_pending=True)
            except Exception:
                pass

            restore_idx = None
            restore_filename = str(getattr(self, "_preview_session_restore_filename", "") or "").strip()
            if restore_filename:
                for idx, ann in enumerate(annotations):
                    if str(getattr(ann, "filename", "") or "") == restore_filename:
                        restore_idx = idx
                        break
            if restore_idx is None:
                saved_idx = getattr(self, "_preview_session_restore_index", None)
                if isinstance(saved_idx, int) and 0 <= int(saved_idx) < len(annotations):
                    restore_idx = int(saved_idx)
            if restore_idx is None:
                manifest_restore_filename = str(manifest.get("resume_preview_filename") or "").strip()
                if manifest_restore_filename:
                    for idx, ann in enumerate(annotations):
                        if str(getattr(ann, "filename", "") or "") == manifest_restore_filename:
                            restore_idx = idx
                            break
            if restore_idx is None:
                try:
                    manifest_restore_idx = int(manifest.get("resume_preview_index", -1))
                except (TypeError, ValueError):
                    manifest_restore_idx = -1
                if 0 <= manifest_restore_idx < len(annotations):
                    restore_idx = manifest_restore_idx
            if restore_idx is None and annotations:
                restore_idx = 0

            self.current_preview_index = restore_idx
            self._preview_session_restore_index = restore_idx
            self._preview_session_restore_filename = (
                str(getattr(annotations[restore_idx], "filename", "") or "")
                if restore_idx is not None and 0 <= int(restore_idx) < len(annotations)
                else ""
            )

            self._refresh_preview_list(preserve_selection=True, render_current=False)
            self._load_current_preview_selection(reset_view=True, selection_changed=True)
            self._refresh_plate_dataset_export_sources()
            self._refresh_step2_action_states()
            return True
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic podgladu Z2 z runu {run_dir}: {e}")
            return False

    def _finalize_successful_annotation_run_ui(self, run_dir: Path, *, manual_template: bool = False) -> None:
        try:
            restored_preview = False
            if not manual_template:
                restored_preview = self._restore_preview_from_annotation_run(run_dir)

            if not restored_preview:
                if manual_template and bool(getattr(self, "_current_run_manual_vehicle_assist", False)):
                    self._populate_preview_list_async(
                        preserve_selection=False,
                        render_current=False,
                        batch_size=150,
                    )
                    self._set_post_annotation_hint(
                        "Run Z2 z preboxingiem pojazdow jest gotowy. Wybierz obraz na liscie po prawej, aby zaladowac podglad i rozpoczac korekte.",
                        "success",
                    )
                else:
                    self._populate_preview_list()
                self._load_plate_dataset_context_from_run(run_dir, force_images_update=True)

            self._refresh_plate_dataset_export_sources()
            self._queue_free_mode_session_save()
        except Exception:
            logger.exception("Blad finalizacji UI po zakonczonym runie Z2")

    def _apply_campaign_project_snapshot(self, session_state: dict | None = None, restore_preview: bool = True) -> bool:
        state = dict(session_state or self._load_campaign_project_snapshot())
        if not state:
            return False

        try:
            from ..campaign_manager import CAMPAIGN

            active_project = str(CAMPAIGN.get_active_project_name() or "").strip()
            current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            return False

        if active_project and str(state.get("project", "") or "").strip() not in {"", active_project}:
            return False

        try:
            saved_iteration = int(state.get("iteration", current_iteration))
        except (TypeError, ValueError):
            saved_iteration = current_iteration
        if saved_iteration != current_iteration:
            return False

        current_input = str(self.input_dir_var.get() or "").strip()
        snapshot_input = str(state.get("input_dir") or "").strip()
        snapshot_uses_stage = bool(snapshot_input and self._is_manual_plate_stage_input(snapshot_input))
        if current_input and snapshot_input and not self._paths_equivalent(snapshot_input, current_input):
            if not snapshot_uses_stage:
                return False
            try:
                if not Path(snapshot_input).exists():
                    return False
            except Exception:
                return False

        self._campaign_project_restore_in_progress = True
        try:
            safe_run_dir = self._resolve_safe_annotation_run_dir(state.get("plate_dataset_run"), require_xml=True)
            safe_last_preview_run_dir = self._resolve_safe_annotation_run_dir(state.get("last_preview_run_dir"), require_xml=True)
            if snapshot_uses_stage:
                self.input_dir_var.set(snapshot_input)
            self.mode_var.set(self._normalize_mode_value(state.get("mode")))
            self.vehicle_model_var.set(str(state.get("vehicle_model") or "").strip())
            self.vehicle_custom_var.set(str(state.get("vehicle_custom") or "").strip())
            self.plate_custom_var.set(str(state.get("plate_custom") or "").strip())
            self.character_model_var.set(str(state.get("character_model") or "Brak / OCR").strip() or "Brak / OCR")
            self.character_custom_var.set(str(state.get("character_custom") or "").strip())
            self.device_var.set(str(state.get("device") or "auto").strip() or "auto")
            self.conf_var.set(float(state.get("conf", CONFIG.DEFAULT_CONFIDENCE)))
            self.plate_dataset_run_var.set(str(safe_run_dir or ""))
            self.plate_dataset_images_var.set(str(state.get("plate_dataset_images") or "").strip())
            self.plate_train_pct.set(float(state.get("plate_train_pct", 80.0)))
            self.plate_val_pct.set(float(state.get("plate_val_pct", 10.0)))
            self.manual_xml_template_var.set(bool(state.get("manual_xml_template", False)))
            self.manual_vehicle_assist_var.set(bool(state.get("manual_vehicle_assist", False)))
            self.workflow_route_var.set(self._normalize_workflow_route_value(state.get("workflow_route")))
            self.manual_entry_mode_var.set(self._normalize_manual_entry_mode(state.get("manual_entry_mode")))
            self.auto_vehicle_choice_var.set(self._normalize_auto_vehicle_choice(state.get("auto_vehicle_choice")))
            self.workflow_step_var.set(self._normalize_workflow_step_value(state.get("workflow_step")))
            self.free_mode_screen_var.set(
                self._normalize_free_mode_screen_value(state.get("free_mode_screen"))
            )
            self._manual_review_active = bool(state.get("manual_review_active", False))
            self._manual_review_from_auto = bool(state.get("manual_review_from_auto", False))
            self._manual_review_export_ready = False
            self._manual_review_history_entries = self._normalize_manual_review_history_entries(
                state.get("manual_review_history", [])
            )

            self.last_staging_run_dir = safe_last_preview_run_dir
            try:
                self._preview_session_restore_index = int(state.get("last_preview_index", -1))
            except (TypeError, ValueError):
                self._preview_session_restore_index = -1
            self._preview_session_restore_filename = str(state.get("last_preview_filename") or "").strip()

            self.apply_global_yolo_device_choice(self.device_var.get())
            self._refresh_device_options()
            self._update_model_lists()

            if hasattr(self, "vehicle_combo"):
                try:
                    vehicle_values = list(self.vehicle_combo["values"])
                except Exception:
                    vehicle_values = []
                current_vehicle = str(self.vehicle_model_var.get() or "").strip()
                if vehicle_values and current_vehicle not in vehicle_values:
                    preferred_vehicle = "yolo11s" if "yolo11s" in vehicle_values else vehicle_values[0]
                    self.vehicle_model_var.set(preferred_vehicle)

            if hasattr(self, "character_combo"):
                self._refresh_character_model_choices()

            self._refresh_manual_review_history_ui()

            self._on_mode_change()
            self._on_vehicle_model_change()
            self._update_manual_xml_template_ui()
            self._update_plate_dataset_ratio_labels()
            self._refresh_plate_dataset_export_sources()
            self._set_campaign_paths_lock_state(True)

            suppress_preview_restore = False
            try:
                campaign_step = int(CAMPAIGN.get_current_step() or 0)
                campaign_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
                step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
                current_step2_run = self._resolve_safe_annotation_run_dir(
                    CAMPAIGN.get_step2_staging_run(),
                    require_xml=True,
                )
                suppress_preview_restore = bool(
                    campaign_step == 2
                    and campaign_target == "plate"
                    and step2_status in {"", "pending"}
                    and current_step2_run is None
                )
            except Exception:
                suppress_preview_restore = False

            if (
                not suppress_preview_restore
                and not self._should_restore_campaign_generated_step2_run_preview(
                    safe_run_dir or safe_last_preview_run_dir,
                    session_state=state,
                )
            ):
                suppress_preview_restore = True

            if suppress_preview_restore:
                safe_run_dir = None
                safe_last_preview_run_dir = None
                self.plate_dataset_run_var.set("")
                self.last_staging_run_dir = None
                self.current_annotation_run_dir = None
                self.current_annotation_xml_path = None
                self.current_annotations = []
                self._preview_image_path_map = {}
                self._manual_review_active = False
                self._manual_review_from_auto = False
                self._manual_review_export_ready = False

            input_dir_value = str(self.input_dir_var.get() or "").strip()
            self.current_input_dir = Path(input_dir_value) if input_dir_value else None

            if restore_preview and not suppress_preview_restore:
                restored_preview = bool(self._restore_preview_from_session_run())
            else:
                restored_preview = False
            if not restored_preview and self.current_input_dir is not None and not self.current_annotations:
                try:
                    self._prime_campaign_source_preview(self.current_input_dir)
                except Exception as e:
                    logger.debug(f"Nie udało się przygotować podglądu wejściowego Z2 po restarcie: {e}")
            self._manual_review_active = bool(self._manual_review_active and restored_preview)
            self._manual_review_from_auto = bool(self._manual_review_from_auto and self._manual_review_active)
            self._manual_review_export_ready = bool(self._manual_review_export_ready and self._manual_review_active)
            self._refresh_step2_action_states()
        finally:
            self._campaign_project_restore_in_progress = False

        return True

    def _bind_free_mode_session_observers(self):
        observed_vars = (
            self.input_dir_var,
            self.output_dir_var,
            self.mode_var,
            self.vehicle_model_var,
            self.vehicle_custom_var,
            self.plate_custom_var,
            self.character_model_var,
            self.character_custom_var,
            self.device_var,
            self.conf_var,
            self.plate_dataset_run_var,
            self.plate_dataset_images_var,
            self.plate_train_pct,
            self.plate_val_pct,
            self.manual_xml_template_var,
            self.manual_vehicle_assist_var,
            self.workflow_route_var,
            self.manual_entry_mode_var,
            self.auto_vehicle_choice_var,
            self.workflow_step_var,
            self.free_mode_screen_var,
        )
        for var in observed_vars:
            try:
                var.trace_add("write", self._on_free_mode_session_var_changed)
            except Exception:
                pass

    def _on_free_mode_session_var_changed(self, *_args):
        self._queue_free_mode_session_save()

    def _queue_free_mode_session_save(self):
        if self._free_mode_session_restore_in_progress or self._campaign_project_restore_in_progress:
            return

        if self._is_free_mode_session_context():
            if not SESSION:
                return
        else:
            try:
                from ..campaign_manager import CAMPAIGN
                if not CAMPAIGN.get_active_project_name():
                    return
            except Exception:
                return

        pending = getattr(self, "_free_mode_session_save_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass

        try:
            self._free_mode_session_save_after_id = self.frame.after(250, self.flush_free_mode_session_state)
        except Exception:
            self.flush_free_mode_session_state()

    def flush_free_mode_session_state(self):
        pending = getattr(self, "_free_mode_session_save_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._free_mode_session_save_after_id = None

        if self._free_mode_session_restore_in_progress or self._campaign_project_restore_in_progress:
            return

        if self._is_free_mode_session_context():
            if not SESSION:
                return

            try:
                snapshot = self._collect_free_mode_session_snapshot()
                SESSION.set("annotation", "images_dir", snapshot["input_dir"])
                for key, value in snapshot.items():
                    SESSION.set("annotation", key, value)
                SESSION.save_session()
            except Exception as e:
                logger.debug(f"Nie udalo sie zapisac stanu Z2: {e}")
            return

        self._save_campaign_project_snapshot()

    def _apply_free_mode_session_snapshot(self, session_state: dict | None = None, restore_preview: bool = True):
        state = self._sanitize_free_mode_session_snapshot(session_state or self._load_free_mode_session_snapshot())
        self._free_mode_session_restore_in_progress = True
        try:
            restored_route = self._normalize_workflow_route_value(state.get("workflow_route"))
            restored_manual_entry_mode = self._normalize_manual_entry_mode(state.get("manual_entry_mode"))
            safe_output_dir = self._coerce_annotation_output_dir(state.get("output_dir"))
            safe_run_dir = self._resolve_safe_annotation_run_dir(state.get("plate_dataset_run"), require_xml=True)
            safe_last_preview_run_dir = self._resolve_safe_annotation_run_dir(state.get("last_preview_run_dir"), require_xml=True)
            self.input_dir_var.set(str(state.get("input_dir") or self._annotation_session_defaults()["input_dir"]))
            self.output_dir_var.set(str(safe_output_dir))
            self.mode_var.set(self._normalize_mode_value(state.get("mode")))
            self.vehicle_model_var.set(str(state.get("vehicle_model") or "").strip())
            self.vehicle_custom_var.set(str(state.get("vehicle_custom") or "").strip())
            self.plate_custom_var.set(str(state.get("plate_custom") or "").strip())
            self.character_model_var.set(str(state.get("character_model") or "Brak / OCR").strip() or "Brak / OCR")
            self.character_custom_var.set(str(state.get("character_custom") or "").strip())
            self.device_var.set(str(state.get("device") or "auto").strip() or "auto")
            self.conf_var.set(float(state.get("conf", CONFIG.DEFAULT_CONFIDENCE)))
            self.plate_dataset_run_var.set(str(safe_run_dir or ""))
            self.plate_dataset_images_var.set(str(state.get("plate_dataset_images") or "").strip())
            self.plate_train_pct.set(float(state.get("plate_train_pct", 80.0)))
            self.plate_val_pct.set(float(state.get("plate_val_pct", 10.0)))
            self.manual_xml_template_var.set(bool(state.get("manual_xml_template", False)))
            self.manual_vehicle_assist_var.set(bool(state.get("manual_vehicle_assist", False)))
            self.workflow_route_var.set(restored_route)
            self.manual_entry_mode_var.set(restored_manual_entry_mode)
            self.auto_vehicle_choice_var.set(self._normalize_auto_vehicle_choice(state.get("auto_vehicle_choice")))
            self.workflow_step_var.set(self._normalize_workflow_step_value(state.get("workflow_step")))
            self.free_mode_screen_var.set(
                self._normalize_free_mode_screen_value(state.get("free_mode_screen"))
            )
            self._manual_review_active = bool(state.get("manual_review_active", False))
            self._manual_review_from_auto = bool(state.get("manual_review_from_auto", False))
            self._manual_review_export_ready = bool(state.get("manual_review_export_ready", False))
            self._manual_review_history_entries = self._normalize_manual_review_history_entries(
                state.get("manual_review_history", [])
            )

            if restored_route == "manual" and restored_manual_entry_mode == "continue":
                self._manual_review_active = False
                self._manual_review_from_auto = False
                self._manual_review_export_ready = False
                self._clear_preview_editor_state(clear_dirty=True)
                self.current_annotations = []
                self.current_input_dir = None
                self.current_annotation_run_dir = None
                self.current_annotation_xml_path = None

            self.last_staging_run_dir = safe_last_preview_run_dir
            try:
                preview_restore_index = int(state.get("last_preview_index", -1))
            except (TypeError, ValueError):
                preview_restore_index = -1
            self._preview_session_restore_index = preview_restore_index
            self._preview_session_restore_filename = str(state.get("last_preview_filename") or "").strip()

            self.apply_global_yolo_device_choice(self.device_var.get())
            self._refresh_device_options()
            self._update_model_lists()

            if hasattr(self, "vehicle_combo"):
                try:
                    vehicle_values = list(self.vehicle_combo["values"])
                except Exception:
                    vehicle_values = []
                current_vehicle = str(self.vehicle_model_var.get() or "").strip()
                if vehicle_values and current_vehicle not in vehicle_values:
                    preferred_vehicle = "yolo11s" if "yolo11s" in vehicle_values else vehicle_values[0]
                    self.vehicle_model_var.set(preferred_vehicle)

            if hasattr(self, "character_combo"):
                self._refresh_character_model_choices()

            self._refresh_manual_review_history_ui()

            self._on_mode_change()
            self._on_vehicle_model_change()
            self._update_manual_xml_template_ui()
            self._update_plate_dataset_ratio_labels()
            self._refresh_plate_dataset_export_sources()
            self._set_campaign_paths_lock_state(False)

            input_dir_value = str(self.input_dir_var.get() or "").strip()
            self.current_input_dir = Path(input_dir_value) if input_dir_value else None

            if restore_preview and not (restored_route == "manual" and restored_manual_entry_mode == "continue"):
                restored_preview = bool(self._restore_preview_from_session_run())
            else:
                restored_preview = False
            self._manual_review_active = bool(self._manual_review_active and restored_preview)
            self._manual_review_from_auto = bool(self._manual_review_from_auto and self._manual_review_active)
            self._manual_review_export_ready = bool(self._manual_review_export_ready and self._manual_review_active)
            self._refresh_step2_action_states()
            self._refresh_free_mode_workflow_ui()
        finally:
            self._free_mode_session_restore_in_progress = False

    def _parse_cvat_preview_annotations(self, xml_path: Path) -> list[ImageAnnotation]:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        annotations = []

        for image_el in root.findall(".//image"):
            filename = str(image_el.get("name", "") or "").strip()
            try:
                width = int(float(image_el.get("width", 0) or 0))
                height = int(float(image_el.get("height", 0) or 0))
            except (TypeError, ValueError):
                continue

            if not filename or width <= 0 or height <= 0:
                continue

            detections = []
            for box_el in image_el.findall("box"):
                if str(box_el.get("label", "") or "").strip().lower() != "vehicle":
                    continue

                try:
                    bbox = (
                        float(box_el.get("xtl", 0) or 0),
                        float(box_el.get("ytl", 0) or 0),
                        float(box_el.get("xbr", 0) or 0),
                        float(box_el.get("ybr", 0) or 0),
                    )
                except (TypeError, ValueError):
                    continue

                confidence = 1.0
                attributes = {}
                for attr_el in box_el.findall("attribute"):
                    attr_name = str(attr_el.get("name", "") or "").strip()
                    attr_value = str(attr_el.text or "").strip()
                    if not attr_name:
                        continue
                    attributes[attr_name] = attr_value
                    if attr_name == "confidence":
                        try:
                            confidence = float(attr_value)
                        except (TypeError, ValueError):
                            confidence = 1.0

                detections.append(
                    Detection(
                        label="vehicle",
                        confidence=confidence,
                        bbox=bbox,
                        attributes=attributes,
                    )
                )

            for poly_el in image_el.findall("polygon"):
                label = str(poly_el.get("label", "") or "").strip().lower()
                if label not in CONFIG.PLATE_LABELS:
                    continue

                points_text = str(poly_el.get("points", "") or "").strip()
                if not points_text:
                    continue

                points = []
                try:
                    for point_text in points_text.split(";"):
                        if "," not in point_text:
                            continue
                        x_text, y_text = point_text.split(",", 1)
                        points.append((float(x_text), float(y_text)))
                except (TypeError, ValueError):
                    continue

                if len(points) < 4:
                    continue

                polygon = PolygonValidator.fix_polygon(points[:4])
                confidence = 1.0
                attributes = {}
                for attr_el in poly_el.findall("attribute"):
                    attr_name = str(attr_el.get("name", "") or "").strip()
                    attr_value = str(attr_el.text or "").strip()
                    if not attr_name:
                        continue
                    attributes[attr_name] = attr_value
                    if attr_name == "confidence":
                        try:
                            confidence = float(attr_value)
                        except (TypeError, ValueError):
                            confidence = 1.0
                polygon_source = str(poly_el.get("source", "") or "").strip().lower()
                if polygon_source == "manual":
                    attributes.setdefault("manual_source", "preview")
                    attributes.setdefault("manually_edited", "true")

                detections.append(
                    Detection(
                        label="plate",
                        confidence=confidence,
                        bbox=self._bbox_from_polygon(polygon),
                        keypoints=self._keypoints_from_polygon(polygon),
                        polygon=polygon,
                        attributes=attributes,
                    )
                )

            annotations.append(
                ImageAnnotation(
                    filename=filename,
                    width=width,
                    height=height,
                    detections=detections,
                    status=(
                        AnnotationStatus.SUCCESS
                        if any(str(det.label or "").lower() in {"plate", "vehicle"} for det in detections)
                        else AnnotationStatus.NO_PLATE
                    ),
                )
            )

        return annotations

    def _restore_preview_from_session_run(self):
        run_dir = None
        run_dir_text = str(self.plate_dataset_run_var.get() or "").strip()
        if run_dir_text:
            run_dir = self._resolve_safe_annotation_run_dir(run_dir_text, require_xml=True)
        elif getattr(self, "last_staging_run_dir", None):
            run_dir = self._resolve_safe_annotation_run_dir(self.last_staging_run_dir, require_xml=True)

        if run_dir is None:
            return False

        xml_path = run_dir / "annotations.xml"
        if not xml_path.exists():
            return False

        manifest = self._load_annotation_run_manifest(run_dir)
        try:
            annotations = self._parse_cvat_preview_annotations(xml_path)
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic ostatniego runu Z2: {e}")
            return False

        if not annotations:
            return False

        image_dir_candidates = []
        seen_candidates = set()
        for raw_value in (
            str(self.input_dir_var.get() or "").strip(),
            str(self.plate_dataset_images_var.get() or "").strip(),
            str(manifest.get("input_dir") or "").strip(),
        ):
            if not raw_value:
                continue
            try:
                candidate = Path(raw_value)
                candidate_key = str(candidate.resolve())
            except Exception:
                candidate = Path(raw_value)
                candidate_key = str(candidate)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            image_dir_candidates.append(candidate)

        image_dir = None
        fallback_dir = None
        best_match_count = -1
        sample_filenames = [
            str(getattr(ann, "filename", "") or "").strip()
            for ann in annotations
            if str(getattr(ann, "filename", "") or "").strip()
        ][:25]

        for candidate in image_dir_candidates:
            try:
                if not candidate.exists() or not candidate.is_dir():
                    continue
            except Exception:
                continue

            if fallback_dir is None:
                fallback_dir = candidate

            match_count = 0
            for filename in sample_filenames:
                try:
                    if (candidate / Path(filename)).exists():
                        match_count += 1
                except Exception:
                    continue

            if match_count > best_match_count:
                best_match_count = match_count
                image_dir = candidate

        if image_dir is None:
            image_dir = fallback_dir
        if image_dir is None:
            return False

        self._clear_preview_editor_state(clear_dirty=True)
        self.current_annotations = annotations
        self.current_input_dir = image_dir
        self._preview_image_path_map = {}
        self._clear_campaign_manual_reuse_context()
        self.plate_dataset_images_var.set(str(image_dir))
        self.current_annotation_run_dir = run_dir
        self.current_annotation_xml_path = xml_path
        self.last_staging_run_dir = run_dir
        try:
            self._restore_campaign_step2_generated_from_run(run_dir, only_when_pending=True)
        except Exception:
            pass
        restore_idx = None
        restore_filename = str(getattr(self, "_preview_session_restore_filename", "") or "").strip()
        if restore_filename:
            for idx, ann in enumerate(annotations):
                if str(getattr(ann, "filename", "") or "") == restore_filename:
                    restore_idx = idx
                    break
        if restore_idx is None:
            saved_idx = getattr(self, "_preview_session_restore_index", None)
            if isinstance(saved_idx, int) and 0 <= int(saved_idx) < len(annotations):
                restore_idx = int(saved_idx)
        if restore_idx is None:
            manifest_restore_filename = str(manifest.get("resume_preview_filename") or "").strip()
            if manifest_restore_filename:
                for idx, ann in enumerate(annotations):
                    if str(getattr(ann, "filename", "") or "") == manifest_restore_filename:
                        restore_idx = idx
                        break
        if restore_idx is None:
            try:
                manifest_restore_idx = int(manifest.get("resume_preview_index", -1))
            except (TypeError, ValueError):
                manifest_restore_idx = -1
            if 0 <= manifest_restore_idx < len(annotations):
                restore_idx = manifest_restore_idx
        if restore_idx is None and annotations:
            restore_idx = 0

        self.current_preview_index = restore_idx
        self._preview_session_restore_index = restore_idx
        self._preview_session_restore_filename = (
            str(getattr(annotations[restore_idx], "filename", "") or "")
            if restore_idx is not None and 0 <= int(restore_idx) < len(annotations)
            else ""
        )
        self._refresh_preview_list(preserve_selection=True, render_current=False)
        self._load_current_preview_selection(reset_view=True, selection_changed=True)
        self._refresh_step2_action_states()
        self._update_preview_edit_status("Przywrocono ostatni run anotacji Z2 z poprzedniej sesji.")
        return True

    def _sync_right_panel_scrollregion(self, event=None):
        canvas = getattr(self, "right_settings_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _sync_right_panel_canvas_width(self, event=None):
        canvas = getattr(self, "right_settings_canvas", None)
        window_id = getattr(self, "_right_settings_window_id", None)
        if canvas is None or window_id is None:
            return

        width = getattr(event, "width", 0) or canvas.winfo_width()
        if width <= 1:
            return

        try:
            canvas.itemconfigure(window_id, width=width)
        except Exception:
            pass
        self._schedule_main_pane_layout_refresh(force_defaults=False, delay_ms=40)

    def _sync_left_panel_scrollregion(self, event=None):
        canvas = getattr(self, "left_settings_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _sync_left_panel_canvas_width(self, event=None):
        canvas = getattr(self, "left_settings_canvas", None)
        window_id = getattr(self, "_left_settings_window_id", None)
        if canvas is None or window_id is None:
            return

        width = getattr(event, "width", 0) or canvas.winfo_width()
        if width <= 1:
            return

        try:
            canvas.itemconfigure(window_id, width=width)
        except Exception:
            pass
        self._schedule_main_pane_layout_refresh(force_defaults=False, delay_ms=40)

    def _should_show_right_panel(self) -> bool:
        if self._is_free_mode_session_context():
            return False
        if bool(getattr(self, "_preview_fullscreen_active", False)):
            return False
        return bool(getattr(self, "_annotation_right_panel_visible", True))

    def _sync_main_pane_right_panel_visibility(self):
        pane = getattr(self, "main_pane", None)
        right_frame = getattr(self, "main_right_frame", None)
        if pane is None or right_frame is None:
            return

        should_show = self._should_show_right_panel()
        has_right = self._pane_has_child(pane, right_frame)

        try:
            if should_show and not has_right:
                pane.add(right_frame, weight=1)
            elif not should_show and has_right:
                pane.forget(right_frame)
        except Exception:
            pass

    def _get_main_pane_width_limits(self) -> tuple[int, int]:
        left_content_req = 0
        right_content_req = 0
        approve_req = 0
        left_scrollbar_req = 10
        right_scrollbar_req = 10

        try:
            left_content_req = int(getattr(self, "left_settings_content", None).winfo_reqwidth() or 0)
        except Exception:
            left_content_req = 0
        try:
            right_content_req = int(getattr(self, "right_settings_content", None).winfo_reqwidth() or 0)
        except Exception:
            right_content_req = 0
        try:
            approve_req = int(getattr(self, "approve_btn_row", None).winfo_reqwidth() or 0)
        except Exception:
            approve_req = 0
        try:
            left_scrollbar_req = int(getattr(self, "left_settings_scrollbar", None).winfo_reqwidth() or 10)
        except Exception:
            left_scrollbar_req = 10
        try:
            right_scrollbar_req = int(getattr(self, "right_settings_scrollbar", None).winfo_reqwidth() or 10)
        except Exception:
            right_scrollbar_req = 10

        right_content_req = max(int(right_content_req), int(approve_req))
        left_min = max(400, min(560, left_content_req + left_scrollbar_req + 20))
        right_min = max(280, min(380, right_content_req + right_scrollbar_req + 16))
        return int(left_min), int(right_min)

    def _schedule_main_pane_layout_refresh(self, *, force_defaults: bool = False, delay_ms: int = 0):
        if bool(getattr(self, "_main_pane_layout_in_progress", False)):
            self._main_pane_layout_pending_force_defaults = bool(
                getattr(self, "_main_pane_layout_pending_force_defaults", False) or force_defaults
            )
            return

        pending = getattr(self, "_main_pane_layout_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
            self._main_pane_layout_after_id = None

        def _run():
            self._main_pane_layout_after_id = None
            self._apply_main_pane_layout(force_defaults=force_defaults)

        try:
            self._main_pane_layout_after_id = self.frame.after(max(0, int(delay_ms)), _run)
        except Exception:
            _run()

    def _apply_main_pane_layout(self, *, force_defaults: bool = False):
        if bool(getattr(self, "_main_pane_layout_in_progress", False)):
            self._main_pane_layout_pending_force_defaults = bool(
                getattr(self, "_main_pane_layout_pending_force_defaults", False) or force_defaults
            )
            return

        pane = getattr(self, "main_pane", None)
        if pane is None:
            return

        self._main_pane_layout_in_progress = True

        try:
            try:
                self._sync_main_pane_right_panel_visibility()
            except Exception:
                pass

            try:
                pane.update_idletasks()
            except Exception:
                pass

            try:
                if not self._pane_has_child(pane, self.main_left_frame):
                    return
                if not self._pane_has_child(pane, self.main_center_frame):
                    return
            except Exception:
                return

            try:
                total_width = int(pane.winfo_width() or pane.winfo_reqwidth() or 0)
            except Exception:
                total_width = 0
            if total_width <= 0:
                return

            left_min, right_min = self._get_main_pane_width_limits()
            has_right = self._pane_has_child(pane, self.main_right_frame)
            if not has_right:
                center_min = min(820, max(420, total_width - left_min))
                max_left = max(left_min, total_width - center_min)

                try:
                    current_left = int(pane.sashpos(0) or 0)
                except Exception:
                    current_left = left_min

                default_left = min(max_left, max(left_min, min(int(total_width * 0.36), 460)))
                desired_left = (
                    default_left
                    if force_defaults or not self._main_pane_layout_initialized
                    else current_left
                )
                desired_left = max(left_min, min(int(desired_left), max_left))

                try:
                    if abs(int(current_left) - int(desired_left)) > 1:
                        pane.sashpos(0, int(desired_left))
                    self._main_pane_layout_initialized = True
                except Exception:
                    pass
                return

            available_center = max(220, total_width - left_min - right_min)
            center_min = min(640, available_center)

            max_left = max(left_min, total_width - right_min - center_min)
            max_second = max(left_min + center_min, total_width - right_min)

            try:
                current_left = int(pane.sashpos(0) or 0)
            except Exception:
                current_left = left_min
            try:
                current_second = int(pane.sashpos(1) or 0)
            except Exception:
                current_second = max(left_min + center_min, total_width - right_min)

            default_left = min(max_left, max(left_min, min(int(total_width * 0.29), 420)))
            default_right_width = max(right_min, min(int(total_width * 0.16), 290))
            default_second = max(default_left + center_min, total_width - default_right_width)
            default_second = min(default_second, max_second)

            desired_left = default_left if force_defaults or not self._main_pane_layout_initialized else current_left
            desired_second = default_second if force_defaults or not self._main_pane_layout_initialized else current_second

            desired_left = max(left_min, min(int(desired_left), max_left))
            desired_second = max(desired_left + center_min, int(desired_second))
            desired_second = min(desired_second, max_second)

            try:
                if abs(int(current_left) - int(desired_left)) > 1:
                    pane.sashpos(0, int(desired_left))
                if abs(int(current_second) - int(desired_second)) > 1:
                    pane.sashpos(1, int(desired_second))
                self._main_pane_layout_initialized = True
            except Exception:
                pass
        finally:
            self._main_pane_layout_in_progress = False
            pending_force_defaults = bool(getattr(self, "_main_pane_layout_pending_force_defaults", False))
            self._main_pane_layout_pending_force_defaults = False
            if pending_force_defaults:
                try:
                    self.frame.after_idle(lambda: self._schedule_main_pane_layout_refresh(force_defaults=True))
                except Exception:
                    self._schedule_main_pane_layout_refresh(force_defaults=True)

    def _on_main_pane_configure(self, event=None):
        self._schedule_main_pane_layout_refresh(force_defaults=not bool(getattr(self, "_main_pane_layout_initialized", False)))

    def _on_main_pane_drag_motion(self, event=None):
        self._schedule_main_pane_layout_refresh(force_defaults=False)

    def _on_main_pane_drag_release(self, event=None):
        self._schedule_main_pane_layout_refresh(force_defaults=False)

    def _sync_approve_hint_wraplength(self, event=None):
        label = getattr(self, "approve_gate_hint_lbl", None)
        host = getattr(self, "approve_btn_row", None)
        if label is None or host is None:
            return

        width = getattr(event, "width", 0) or host.winfo_width()
        if width <= 1:
            return

        try:
            label.configure(wraplength=max(220, int(width) - 34))
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

    def _get_preview_pointer_canvas_position(self):
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return None

        try:
            x_root = int(canvas.winfo_pointerx())
            y_root = int(canvas.winfo_pointery())
        except Exception:
            return None

        if not self._widget_contains_point(canvas, x_root, y_root):
            return None

        try:
            local_x = float(x_root - int(canvas.winfo_rootx()))
            local_y = float(y_root - int(canvas.winfo_rooty()))
            return (
                float(canvas.canvasx(local_x)),
                float(canvas.canvasy(local_y)),
            )
        except Exception:
            return None

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

    def _panel_canvas_overflows(self, canvas) -> bool:
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

    def _scroll_panel_canvas_if_targeted(self, canvas, event):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

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

        if not self._panel_canvas_overflows(canvas):
            return None

        try:
            canvas.yview_scroll(units, "units")
        except Exception:
            return "break"
        return "break"

    def _on_left_panel_global_mousewheel(self, event):
        return self._scroll_panel_canvas_if_targeted(
            getattr(self, "left_settings_canvas", None),
            event
        )

    def _on_right_panel_global_mousewheel(self, event):
        return self._scroll_panel_canvas_if_targeted(
            getattr(self, "right_settings_canvas", None),
            event
        )

    def _restore_scroll_canvas_focus(self, canvas):
        if canvas is None:
            return
        try:
            canvas.focus_set()
        except Exception:
            pass

    def _redirect_child_mousewheel_to_canvas(self, event, canvas):
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

        units = self._mousewheel_units(event)
        if units != 0 and self._panel_canvas_overflows(canvas):
            try:
                canvas.yview_scroll(units, "units")
            except Exception:
                return "break"

        self._restore_scroll_canvas_focus(canvas)
        return "break"

    def _bind_scroll_canvas_children(self, root, canvas):
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
                widget.bind("<MouseWheel>", lambda e, c=canvas: self._redirect_child_mousewheel_to_canvas(e, c), add="+")
                widget.bind("<Button-4>", lambda e, c=canvas: self._redirect_child_mousewheel_to_canvas(e, c), add="+")
                widget.bind("<Button-5>", lambda e, c=canvas: self._redirect_child_mousewheel_to_canvas(e, c), add="+")
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

    def _build_left_section_separator(self, parent, pady=(0, 0)):
        if parent is None:
            return None

        palette = getattr(self.app, "palette", {})
        host = tk.Frame(
            parent,
            height=4,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", "#252526"),
        )
        host.pack(fill=tk.X, pady=pady)
        host.pack_propagate(False)

        accent_line = tk.Frame(
            host,
            height=1,
            bd=0,
            highlightthickness=0,
            bg=palette.get("surface_info", palette.get("accent", "#0e639c")),
        )
        accent_line.pack(fill=tk.X, side=tk.TOP)

        shadow_line = tk.Frame(
            host,
            height=1,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel_border", palette.get("border", "#3c3c3c")),
        )
        shadow_line.pack(fill=tk.X, side=tk.TOP, pady=(1, 0))

        self._left_section_separators.append(
            {
                "host": host,
                "accent": accent_line,
                "shadow": shadow_line,
            }
        )
        return host

    def _build_left_path_row(
        self,
        parent,
        textvariable,
        *,
        state: str = "normal",
        button_text: str | None = None,
        button_command=None,
    ):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill=tk.X, pady=(2, 8))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, minsize=int(getattr(self, "_left_path_action_minsize", 140)))

        entry = ttk.Entry(row, textvariable=textvariable, state=state)
        entry.grid(row=0, column=0, sticky="ew")

        button = None
        if button_text and button_command is not None:
            button = ttk.Button(
                row,
                text=button_text,
                width=int(getattr(self, "_left_path_button_width", 15)),
                command=button_command,
            )
            button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        return row, entry, button

    def _bind_workflow_card(self, card_widget, route: str):
        if card_widget is None:
            return

        widgets = [card_widget]
        try:
            widgets.extend(list(card_widget.winfo_children()))
        except Exception:
            pass

        for widget in widgets:
            try:
                widget.bind(
                    "<Button-1>",
                    lambda _event, selected_route=route: self._select_workflow_route(selected_route),
                    add="+",
                )
                widget.bind(
                    "<Enter>",
                    lambda _event, selected_route=route: self._set_workflow_route_card_hover(selected_route, True),
                    add="+",
                )
                widget.bind(
                    "<Leave>",
                    lambda _event, selected_route=route: self._set_workflow_route_card_hover(selected_route, False),
                    add="+",
                )
            except Exception:
                pass

    def _bind_preview_sort_tile(self, tile_widget, sort_mode: str):
        if tile_widget is None:
            return

        widgets = [tile_widget]
        try:
            widgets.extend(list(tile_widget.winfo_children()))
        except Exception:
            pass

        for widget in widgets:
            try:
                widget.bind(
                    "<Button-1>",
                    lambda _event, selected_sort=sort_mode: self._set_preview_list_sort_mode(selected_sort),
                    add="+",
                )
            except Exception:
                pass

    def _set_preview_list_sort_mode(self, sort_mode: str):
        normalized = str(sort_mode or "").strip()
        if not normalized:
            return
        current = str(self.preview_list_sort_var.get() or "").strip()
        if current == normalized:
            self._refresh_preview_list_legend_theme()
            return

        self.preview_list_sort_var.set(normalized)
        if len(self.current_annotations or []) >= 500:
            self._populate_preview_list_async(
                preserve_selection=True,
                render_current=False,
                batch_size=200,
            )
        else:
            self._refresh_preview_list(preserve_selection=True, render_current=False)
        self._refresh_preview_list_legend_theme()
        self._update_preview_toolbar_state()

    def _set_workflow_route_card_hover(self, route: str, enabled: bool):
        self._workflow_route_hover_mode = route if enabled else None
        self._refresh_workflow_route_cards()

    def _select_workflow_route(self, route: str):
        if self._is_free_mode_session_context():
            self._select_free_mode_route(route)
            return

        normalized_route = self._normalize_workflow_route_value(route)
        if normalized_route not in {"auto", "manual"}:
            return

        try:
            from ..campaign_manager import CAMPAIGN

            if not CAMPAIGN.get_active_project_name() or int(CAMPAIGN.get_current_step() or 0) != 2:
                return
            iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        except Exception:
            return

        self._apply_campaign_step2_workflow_preset(
            iteration_target=iteration_target,
            manual_template=(normalized_route == "manual"),
        )

        if normalized_route == "manual":
            try:
                input_dir_value = str(self.input_dir_var.get() or "").strip()
                if input_dir_value and not getattr(self, "current_annotation_xml_path", None):
                    self._prime_campaign_source_preview(Path(input_dir_value))
            except Exception as e:
                logger.debug(f"Nie udało się odświeżyć podglądu po wyborze ręcznej anotacji w kampanii: {e}")

        try:
            self.app.update_status(
                (
                    "W kampanii wybrano ręczną anotację tej paczki w Z2."
                    if normalized_route == "manual"
                    else "W kampanii wybrano autoanotację tej paczki w Z2."
                ),
                "info",
            )
        except Exception:
            pass

    def _build_workflow_step_card(self, parent):
        palette = getattr(self.app, "palette", {})
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        return tk.Frame(
            parent,
            bd=0,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
            bg=palette.get("panel_alt", palette.get("panel", "#252526")),
            padx=14,
            pady=12,
        )

    @staticmethod
    def _bind_card_help_recursive(widget, index_key: str):
        if widget is None:
            return
        try:
            HELP.bind_help(widget, index_key)
        except Exception:
            pass
        try:
            for child in widget.winfo_children():
                try:
                    HELP.bind_help(child, index_key)
                except Exception:
                    pass
        except Exception:
            pass

    def _register_workflow_step_card(
        self,
        key: str,
        card,
        *,
        title=None,
        labels=None,
        child_frames=None,
        step_keys=None,
        style_targets=None,
    ):
        if card is None:
            return
        self._workflow_step_cards.append(
            {
                "key": str(key or "").strip(),
                "card": card,
                "title": title,
                "labels": list(labels or []),
                "child_frames": list(child_frames or []),
                "step_keys": {str(item).strip() for item in (step_keys or []) if str(item).strip()},
                "style_targets": list(style_targets or []),
            }
        )

    def _apply_workflow_step_widget_style(self, widget, kind: str, style_name: str, background: str):
        if widget is None or not style_name:
            return

        style = getattr(getattr(self, "app", None), "style", None)
        if style is None:
            return

        palette = getattr(self.app, "palette", {})
        fg = palette.get("fg", "#f3f3f3")
        field = palette.get("field", "#3c3c3c")
        panel_alt = palette.get("panel_alt", "#2d2d30")
        panel = palette.get("panel", "#252526")
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        success = palette.get("success", "#4ec9b0")
        success_surface = palette.get("surface_success", blend_hex_colors(background, success, 0.24))
        muted_dim = palette.get("muted_dim", palette.get("muted", "#8c8c8c"))
        field_bg = blend_hex_colors(background, field, 0.58)
        disabled_field_bg = blend_hex_colors(background, panel, 0.35)
        control_arrow = success
        control_arrow_disabled = muted_dim

        try:
            if kind == "frame":
                style.configure(style_name, background=background)
            elif kind == "checkbutton":
                style.configure(
                    style_name,
                    background=background,
                    foreground=fg,
                    focuscolor=background,
                    indicatorcolor=field,
                )
                style.map(
                    style_name,
                    background=[("active", background), ("disabled", background)],
                    foreground=[("disabled", muted_dim)],
                    indicatorcolor=[
                        ("selected", success),
                        ("active", field),
                        ("!selected", field),
                        ("disabled", panel_alt),
                    ],
                )
            elif kind == "radiobutton":
                style.configure(
                    style_name,
                    background=background,
                    foreground=fg,
                    focuscolor=background,
                    indicatorcolor=field,
                )
                style.map(
                    style_name,
                    background=[("active", background), ("disabled", background)],
                    foreground=[("disabled", muted_dim)],
                    indicatorcolor=[
                        ("selected", success),
                        ("active", field),
                        ("!selected", field),
                        ("disabled", panel_alt),
                    ],
                )
            elif kind == "scale":
                self.app.style_ttk_scale_widget(widget, background=background, base_style=style_name)
            elif kind == "entry":
                style.configure(
                    style_name,
                    fieldbackground=field_bg,
                    foreground=fg,
                    bordercolor=border,
                    lightcolor=border,
                    darkcolor=border,
                )
                style.map(
                    style_name,
                    fieldbackground=[
                        ("readonly", field_bg),
                        ("disabled", disabled_field_bg),
                    ],
                    foreground=[
                        ("readonly", fg),
                        ("disabled", muted_dim),
                    ],
                    selectbackground=[
                        ("readonly", success_surface),
                        ("disabled", disabled_field_bg),
                    ],
                    selectforeground=[
                        ("readonly", fg),
                        ("disabled", muted_dim),
                    ],
                )
            elif kind == "combobox":
                style.configure(
                    style_name,
                    fieldbackground=field_bg,
                    background=field_bg,
                    foreground=fg,
                    bordercolor=border,
                    lightcolor=border,
                    darkcolor=border,
                    arrowsize=14,
                    arrowcolor=control_arrow,
                )
                style.map(
                    style_name,
                    fieldbackground=[
                        ("readonly", field_bg),
                        ("disabled", disabled_field_bg),
                    ],
                    background=[
                        ("readonly", field_bg),
                        ("disabled", disabled_field_bg),
                    ],
                    selectbackground=[
                        ("readonly", success_surface),
                        ("disabled", disabled_field_bg),
                    ],
                    selectforeground=[
                        ("readonly", fg),
                        ("disabled", muted_dim),
                    ],
                    foreground=[
                        ("readonly", fg),
                        ("disabled", muted_dim),
                    ],
                    arrowcolor=[
                        ("readonly", control_arrow),
                        ("active", control_arrow),
                        ("disabled", control_arrow_disabled),
                    ],
                )
            elif kind == "title_label":
                style.configure(
                    style_name,
                    background=background,
                    foreground=fg,
                    font=("Segoe UI Semibold", 10),
                )
                style.map(
                    style_name,
                    background=[("disabled", background)],
                    foreground=[("disabled", muted_dim)],
                )
            elif kind == "label":
                style.configure(
                    style_name,
                    background=background,
                    foreground=fg,
                    font=("Segoe UI", 10),
                )
                style.map(
                    style_name,
                    background=[("disabled", background)],
                    foreground=[("disabled", muted_dim)],
                )
            elif kind == "muted_label":
                style.configure(
                    style_name,
                    background=background,
                    foreground=palette.get("muted", "#9a9a9a"),
                    font=("Segoe UI", 10),
                )
                style.map(
                    style_name,
                    background=[("disabled", background)],
                    foreground=[("disabled", muted_dim)],
                )
            elif kind == "progressbar":
                trough = blend_hex_colors(background, field, 0.6)
                fill = blend_hex_colors(success, background, 0.12)
                style.configure(
                    style_name,
                    troughcolor=trough,
                    background=fill,
                    lightcolor=fill,
                    darkcolor=fill,
                    bordercolor=border,
                )
                style.map(
                    style_name,
                    troughcolor=[("disabled", trough)],
                    background=[("disabled", disabled_field_bg)],
                    lightcolor=[("disabled", disabled_field_bg)],
                    darkcolor=[("disabled", disabled_field_bg)],
                )
            else:
                return

            widget.configure(style=style_name)
        except Exception:
            pass

    def _refresh_workflow_button_styles(self):
        style = getattr(getattr(self, "app", None), "style", None)
        if style is None:
            return

        palette = getattr(self.app, "palette", {})
        panel_alt = palette.get("panel_alt", palette.get("panel", "#252526"))
        hover_bg = palette.get("button_hover", panel_alt)
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("fg", "#f3f3f3")
        primary_bg = blend_hex_colors(panel_alt, hover_bg, 0.35)
        disabled_bg = palette.get("panel", "#252526")
        muted_dim = palette.get("muted_dim", palette.get("muted", "#8c8c8c"))

        style.configure(
            "WorkflowCard.TButton",
            background=panel_alt,
            foreground=fg,
            bordercolor=panel_border,
            lightcolor=panel_border,
            darkcolor=panel_border,
            padding=8,
            borderwidth=1,
            relief=tk.SOLID,
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "WorkflowCard.TButton",
            background=[
                ("active", hover_bg),
                ("pressed", hover_bg),
                ("disabled", disabled_bg),
            ],
            foreground=[("disabled", muted_dim)],
            bordercolor=[
                ("active", panel_border),
                ("pressed", panel_border),
                ("disabled", panel_border),
            ],
            lightcolor=[
                ("active", panel_border),
                ("pressed", panel_border),
                ("disabled", panel_border),
            ],
            darkcolor=[
                ("active", panel_border),
                ("pressed", panel_border),
                ("disabled", panel_border),
            ],
        )

        style.configure(
            "WorkflowCardPrimary.TButton",
            background=primary_bg,
            foreground=fg,
            bordercolor=panel_border,
            lightcolor=panel_border,
            darkcolor=panel_border,
            padding=8,
            borderwidth=1,
            relief=tk.SOLID,
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "WorkflowCardPrimary.TButton",
            background=[
                ("active", hover_bg),
                ("pressed", hover_bg),
                ("disabled", disabled_bg),
            ],
            foreground=[("disabled", muted_dim)],
            bordercolor=[
                ("active", panel_border),
                ("pressed", panel_border),
                ("disabled", panel_border),
            ],
            lightcolor=[
                ("active", panel_border),
                ("pressed", panel_border),
                ("disabled", panel_border),
            ],
            darkcolor=[
                ("active", panel_border),
                ("pressed", panel_border),
                ("disabled", panel_border),
            ],
        )

        for attr_name, style_name in {
            "workflow_plate_browse_btn": "WorkflowCard.TButton",
            "workflow_vehicle_custom_browse_btn": "WorkflowCard.TButton",
            "manual_history_open_btn": "WorkflowCardPrimary.TButton",
            "manual_history_import_btn": "WorkflowCard.TButton",
            "workflow_input_browse_btn": "WorkflowCard.TButton",
            "workflow_back_btn": "WorkflowCard.TButton",
            "workflow_next_btn": "Accent.TButton",
            "start_btn": "WorkflowCardPrimary.TButton",
            "stop_btn": "WorkflowCard.TButton",
            "enter_manual_review_btn": "WorkflowCardPrimary.TButton",
            "jump_to_export_btn": "WorkflowCard.TButton",
            "open_run_dir_btn": "WorkflowCard.TButton",
            "manual_stage_use_btn": "WorkflowCard.TButton",
            "manual_stage_add_btn": "WorkflowCard.TButton",
            "manual_stage_export_btn": "WorkflowCard.TButton",
            "plate_dataset_run_btn": "WorkflowCard.TButton",
            "plate_dataset_images_btn": "WorkflowCard.TButton",
            "export_back_btn": "WorkflowCard.TButton",
            "export_plate_dataset_btn": "WorkflowCardPrimary.TButton",
        }.items():
            button = getattr(self, attr_name, None)
            if button is None:
                continue
            try:
                button.configure(style=style_name)
            except Exception:
                pass

        try:
            self._refresh_auto_vehicle_choice_ui()
        except Exception:
            pass

    def _refresh_workflow_progress_style(self, background: str | None = None):
        progress = getattr(self, "progress", None)
        if progress is None:
            return

        palette = getattr(self.app, "palette", {})
        card_bg = str(
            background
            or getattr(getattr(self, "workflow_start_section", None), "cget", lambda _key: None)("bg")
            or palette.get("panel_alt", palette.get("panel", "#252526"))
        )
        field = palette.get("field", palette.get("panel", "#252526"))
        success = palette.get("success", "#4ec9b0")
        trough = blend_hex_colors(card_bg, field, 0.6)
        fill = blend_hex_colors(success, card_bg, 0.1)

        try:
            progress.configure(
                trough_color=trough,
                fill_color=fill,
                bg=card_bg,
            )
        except Exception:
            pass

    def _refresh_workflow_step_cards(self):
        cards = getattr(self, "_workflow_step_cards", [])
        if not cards:
            return

        palette = getattr(self.app, "palette", {})
        panel = palette.get("panel_alt", palette.get("panel", "#252526"))
        hover_bg = palette.get("button_hover", panel)
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("fg", "#f3f3f3")
        active_bg = blend_hex_colors(panel, hover_bg, 0.30)
        current_step = self._coerce_workflow_step()

        for entry in cards:
            card = entry.get("card")
            if card is None:
                continue

            step_keys = entry.get("step_keys", set())
            is_active = bool(current_step and current_step in step_keys and self._widget_is_packed(card))
            card_bg = active_bg if is_active else panel
            card_border = panel_border
            title_fg = fg

            try:
                card.configure(
                    bg=card_bg,
                    highlightbackground=card_border,
                    highlightcolor=card_border,
                )
            except Exception:
                pass

            title_widget = entry.get("title")
            if title_widget is not None:
                try:
                    title_widget.configure(bg=card_bg, fg=title_fg, font=("Segoe UI Semibold", 11))
                except Exception:
                    pass

            for child_frame in entry.get("child_frames", []):
                if child_frame is None:
                    continue
                try:
                    child_frame.configure(bg=card_bg)
                except Exception:
                    pass

            for label in entry.get("labels", []):
                if label is None:
                    continue
                try:
                    label.configure(bg=card_bg)
                except Exception:
                    pass
                try:
                    tone = getattr(label, "_inline_tone", "muted")
                    emphasis = getattr(label, "_inline_emphasis", False)
                    text_value = None
                    try:
                        if not label.cget("textvariable"):
                            text_value = label.cget("text")
                    except Exception:
                        text_value = label.cget("text")
                    self._set_inline_label_state(label, text=text_value, tone=tone, emphasis=emphasis)
                except Exception:
                    pass

            for target in entry.get("style_targets", []):
                if not isinstance(target, dict):
                    continue
                self._apply_workflow_step_widget_style(
                    target.get("widget"),
                    str(target.get("kind") or "").strip(),
                    str(target.get("style") or "").strip(),
                    card_bg,
                )

            if str(entry.get("key") or "").strip() == "workflow_manual_stage":
                self._refresh_manual_stage_export_box_style()

            if str(entry.get("key") or "").strip() == "workflow_start":
                self._refresh_workflow_progress_style(card_bg)

    @staticmethod
    def _widget_is_packed(widget) -> bool:
        try:
            return str(widget.winfo_manager()) == "pack"
        except Exception:
            return False

    def _set_widget_packed(self, widget, visible: bool, **pack_kwargs):
        if widget is None:
            return

        try:
            is_packed = str(widget.winfo_manager()) == "pack"
        except Exception:
            is_packed = False

        if visible:
            if not is_packed:
                safe_pack_kwargs = dict(pack_kwargs)
                for ref_key in ("before", "after"):
                    ref_widget = safe_pack_kwargs.get(ref_key)
                    if ref_widget is None:
                        continue
                    try:
                        if str(ref_widget.winfo_manager()) != "pack":
                            safe_pack_kwargs.pop(ref_key, None)
                    except Exception:
                        safe_pack_kwargs.pop(ref_key, None)

                try:
                    widget.pack(**safe_pack_kwargs)
                except tk.TclError:
                    safe_pack_kwargs.pop("before", None)
                    safe_pack_kwargs.pop("after", None)
                    widget.pack(**safe_pack_kwargs)
        elif is_packed:
            widget.pack_forget()

    def _scroll_left_panel_to_widget(self, widget):
        canvas = getattr(self, "left_settings_canvas", None)
        content = getattr(self, "left_settings_content", None)
        if canvas is None or content is None or widget is None:
            return

        try:
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if not bbox:
                return

            top_y = 0
            current = widget
            while current is not None and current != content:
                top_y += int(current.winfo_y())
                parent_name = str(current.winfo_parent() or "").strip()
                if not parent_name:
                    break
                try:
                    current = current.nametowidget(parent_name)
                except Exception:
                    current = None

            total_height = max(1, int(bbox[3] - bbox[1]))
            fraction = max(0.0, min(1.0, float(top_y) / float(total_height)))
            canvas.yview_moveto(fraction)
        except Exception:
            pass

    def _schedule_left_panel_scroll_to_widget(self, widget, *, delay_ms: int = 0):
        pending = getattr(self, "_left_panel_scroll_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
            self._left_panel_scroll_after_id = None

        if widget is None:
            return

        def _run():
            self._left_panel_scroll_after_id = None
            self._scroll_left_panel_to_widget(widget)

        try:
            self._left_panel_scroll_after_id = self.frame.after(max(0, int(delay_ms)), _run)
        except Exception:
            _run()

    def _create_widgets(self):
        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        pane = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        self.main_pane = pane

        left_frame = ttk.Frame(pane, style="Panel.TFrame")
        center_frame = ttk.Frame(pane, style="Panel.TFrame")
        right_frame = ttk.Frame(pane, style="Panel.TFrame")
        self.main_left_frame = left_frame
        self.main_center_frame = center_frame
        self.main_right_frame = right_frame
        self._annotation_right_panel_visible = True

        pane.add(left_frame, weight=2)
        pane.add(center_frame, weight=6)
        pane.add(right_frame, weight=1)
        pane.bind("<Configure>", self._on_main_pane_configure, add="+")
        pane.bind("<B1-Motion>", self._on_main_pane_drag_motion, add="+")
        pane.bind("<ButtonRelease-1>", self._on_main_pane_drag_release, add="+")

        # --- LEWA KOLUMNA ---
        left_scroll_shell = tk.Frame(
            left_frame,
            bg=panel_bg,
            bd=0,
            highlightthickness=1,
            highlightbackground=panel_border,
            highlightcolor=panel_border,
        )
        left_scroll_shell.pack(fill=tk.BOTH, expand=True)
        self.left_scroll_shell = left_scroll_shell

        left_scroll_host = ttk.Frame(left_scroll_shell, style="Panel.TFrame")
        left_scroll_host.pack(fill=tk.BOTH, expand=True)
        self.left_scroll_host = left_scroll_host

        self.left_settings_canvas = tk.Canvas(left_scroll_host, bg=panel_bg, highlightthickness=0, bd=0)
        self.left_settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.left_settings_scrollbar = WebSlimScrollbar(
            left_scroll_host,
            command=self.left_settings_canvas.yview
        )
        self.left_settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.left_settings_canvas.configure(yscrollcommand=self.left_settings_scrollbar.set)

        self.left_settings_content = ttk.Frame(self.left_settings_canvas, style="Panel.TFrame")
        self._left_settings_window_id = self.left_settings_canvas.create_window(
            (0, 0),
            window=self.left_settings_content,
            anchor="nw"
        )
        self.left_settings_content.bind("<Configure>", self._sync_left_panel_scrollregion)
        self.left_settings_canvas.bind("<Configure>", self._sync_left_panel_canvas_width)

        self.preview_left_list_shell = tk.Frame(
            left_frame,
            bg=panel_bg,
            bd=0,
            highlightthickness=1,
            highlightbackground=panel_border,
            highlightcolor=panel_border,
        )
        self.preview_left_list_host = ttk.Frame(self.preview_left_list_shell, style="Panel.TFrame")
        self.preview_left_list_host.pack(fill=tk.BOTH, expand=True)

        settings_col = ttk.Frame(self.left_settings_content, style="Panel.TFrame")
        settings_col.pack(fill=tk.X, expand=True, padx=12, pady=(14, 20))
        self.left_settings_col = settings_col

        workflow_shell_border = blend_hex_colors(
            palette.get("accent", "#4f8de3"),
            panel_border,
            0.62,
        )
        workflow_shell_fill = blend_hex_colors(
            palette.get("surface_info", panel_bg),
            panel_bg,
            0.80,
        )
        self.workflow_entry_shell = tk.Frame(
            settings_col,
            bg=workflow_shell_border,
            bd=0,
            highlightthickness=0,
            padx=1,
            pady=1,
        )
        self.workflow_entry_shell.pack(fill=tk.X, pady=(0, 16))

        self.workflow_entry_shell_inner = tk.Frame(
            self.workflow_entry_shell,
            bg=workflow_shell_fill,
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=12,
        )
        self.workflow_entry_shell_inner.pack(fill=tk.X, expand=True)

        self.workflow_entry_section = ttk.Frame(self.workflow_entry_shell_inner, style="Panel.TFrame")
        self.workflow_entry_section.pack(fill=tk.X)
        self.workflow_entry_title_lbl = SectionHeaderLabel(
            self.workflow_entry_section,
            self.app,
            text="Co chcesz zrobic?",
        )
        self.workflow_entry_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.workflow_intro_lbl = tk.Label(
            self.workflow_entry_section,
            textvariable=self.workflow_intro_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.workflow_intro_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))
        self._set_inline_label_state(self.workflow_intro_lbl, tone="muted", emphasis=False)

        self.workflow_cards_frame = ttk.Frame(self.workflow_entry_section, style="Panel.TFrame")
        self.workflow_cards_frame.pack(fill=tk.X)

        palette = getattr(self.app, "palette", {})
        workflow_card_bg = palette.get("panel_alt", palette.get("panel", "#252526"))
        workflow_card_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        workflow_card_fg = palette.get("fg", "#f3f3f3")
        workflow_card_muted = palette.get("muted", "#c7c7c7")

        self.auto_route_card = tk.Frame(
            self.workflow_cards_frame,
            bd=0,
            highlightthickness=1,
            highlightbackground=workflow_card_border,
            highlightcolor=workflow_card_border,
            bg=workflow_card_bg,
            padx=14,
            pady=12,
            cursor="hand2",
        )
        self.auto_route_card.pack(fill=tk.X, pady=(0, 8))
        self.auto_route_card_title = tk.Label(
            self.auto_route_card,
            text="Autoanotacja tablic",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI Semibold", 11),
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            bg=workflow_card_bg,
            fg=workflow_card_fg,
        )
        self.auto_route_card_title.pack(anchor=tk.W, fill=tk.X)
        self.auto_route_card_desc = tk.Label(
            self.auto_route_card,
            text="Uruchom YOLO, zapisz run anotacji Z2 w workspace i przejdź potem do korekty oraz splitu.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=336,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            bg=workflow_card_bg,
            fg=workflow_card_muted,
        )
        self.auto_route_card_desc.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

        self.manual_route_card = tk.Frame(
            self.workflow_cards_frame,
            bd=0,
            highlightthickness=1,
            highlightbackground=workflow_card_border,
            highlightcolor=workflow_card_border,
            bg=workflow_card_bg,
            padx=14,
            pady=12,
            cursor="hand2",
        )
        self.manual_route_card.pack(fill=tk.X)
        self.manual_route_card_title = tk.Label(
            self.manual_route_card,
            text="Anotacja ręczna tablic",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI Semibold", 11),
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            bg=workflow_card_bg,
            fg=workflow_card_fg,
        )
        self.manual_route_card_title.pack(anchor=tk.W, fill=tk.X)
        self.manual_route_card_desc = tk.Label(
            self.manual_route_card,
            text="Kontynuuj istniejący XML albo utwórz nowy run anotacji do ręcznych poprawek i kolejnych iteracji.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=336,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            bg=workflow_card_bg,
            fg=workflow_card_muted,
        )
        self.manual_route_card_desc.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

        self._bind_workflow_card(self.auto_route_card, "auto")
        self._bind_workflow_card(self.manual_route_card, "manual")
        self._refresh_workflow_route_cards()
        self.workflow_entry_separator = self._build_left_section_separator(settings_col, pady=(16, 20))

        workflow_nav_panel = ttk.Frame(self.workflow_entry_shell_inner, style="Panel.TFrame")
        workflow_nav_panel.pack(fill=tk.X, pady=(12, 0))
        self.workflow_nav_panel = workflow_nav_panel

        source_section = ttk.Frame(settings_col, style="Panel.TFrame")
        self.source_section = source_section
        source_section.pack(fill=tk.X)
        self.sources_title_lbl = SectionHeaderLabel(
            source_section,
            self.app,
            text="1. Wejście i zapis runu anotacji Z2",
        )
        self.sources_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.input_dir_title_lbl = ttk.Label(
            source_section,
            text="Folder obrazów wejściowych",
            style="Panel.TLabel"
        )
        self.input_dir_title_lbl.pack(anchor=tk.W, fill=tk.X)
        row_in, self.input_dir_entry, self.input_dir_browse_btn = self._build_left_path_row(
            source_section,
            self.input_dir_var,
            button_text="Wybierz obrazy",
            button_command=self._select_input_dir,
        )

        self.project_paths_info_lbl = tk.Label(
            source_section,
            textvariable=self.project_paths_info_var,
            font=("Segoe UI", 9),
            wraplength=360,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.project_paths_info_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))
        self._set_inline_label_state(self.project_paths_info_lbl, tone="muted", emphasis=False)

        self.project_paths_rel_lbl = tk.Label(
            source_section,
            textvariable=self.project_paths_rel_var,
            wraplength=360,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.project_paths_rel_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 10))
        self._set_inline_label_state(self.project_paths_rel_lbl, tone="muted", emphasis=False)

        self.output_dir_title_lbl = ttk.Label(
            source_section,
            text="Folder, w którym Z2 zapisuje runy anotacji",
            style="Panel.TLabel"
        )
        self.output_dir_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.output_dir_var.set(str(Path(CONFIG.get_auto_annotations_dir("plate"))))
        row_out, self.output_dir_entry, _ = self._build_left_path_row(
            source_section,
            self.output_dir_var,
            state="readonly",
        )
        self._enable_compact_path_entry(
            self.output_dir_entry,
            self.output_dir_var,
            title="Pełna ścieżka katalogu runów anotacji Z2",
        )

        self.source_section_separator = self._build_left_section_separator(settings_col, pady=(16, 20))

        actions_lf = ttk.Frame(self.workflow_entry_shell_inner, style="Panel.TFrame")
        self.actions_section = actions_lf
        actions_lf.pack(fill=tk.X)
        self.run_title_lbl = SectionHeaderLabel(
            actions_lf,
            self.app,
            text="2. Wybierz tor i uruchom Z2",
        )
        self.run_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.route_badge_lbl = tk.Label(
            actions_lf,
            textvariable=self.route_badge_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.route_badge_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))
        self._set_inline_label_state(self.route_badge_lbl, tone="success", emphasis=True)

        self.route_summary_lbl = tk.Label(
            actions_lf,
            textvariable=self.route_summary_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.route_summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_label_state(self.route_summary_lbl, tone="muted", emphasis=False)

        self.workflow_action_hint_lbl = tk.Label(
            actions_lf,
            textvariable=self.workflow_action_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.workflow_action_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_label_state(self.workflow_action_hint_lbl, tone="muted", emphasis=False)

        self.return_to_campaign_btn = ttk.Button(
            actions_lf,
            text="Wróć do wizarda",
            style="WorkflowCard.TButton",
            command=self._return_to_campaign_wizard,
        )
        self.return_to_campaign_btn.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self.return_to_campaign_btn.configure(padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self.route_selector_frame = ttk.Frame(actions_lf, style="Panel.TFrame")
        self.route_selector_frame.pack(fill=tk.X, pady=(2, 2))

        self.auto_route_radio = ttk.Radiobutton(
            self.route_selector_frame,
            text="Autoanotacja runu anotacji Z2",
            variable=self.manual_xml_template_var,
            value=False,
            command=self._update_manual_xml_template_ui
        )
        self.auto_route_radio.pack(anchor=tk.W)

        self.manual_route_radio = ttk.Radiobutton(
            self.route_selector_frame,
            text="Ręczna anotacja tablic",
            variable=self.manual_xml_template_var,
            value=True,
            command=self._update_manual_xml_template_ui
        )
        self.manual_route_radio.pack(anchor=tk.W, pady=(2, 0))

        self.manual_vehicle_assist_check = ttk.Checkbutton(
            self.route_selector_frame,
            text="Dodaj tylko boxy pojazdów jako pomoc",
            variable=self.manual_vehicle_assist_var,
            command=self._update_manual_xml_template_ui
        )

        self.manual_vehicle_assist_hint_lbl = tk.Label(
            self.route_selector_frame,
            textvariable=self.manual_vehicle_assist_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=340,
            bd=0,
            highlightthickness=0
        )

        self.manual_xml_template_hint_lbl = tk.Label(
            actions_lf,
            textvariable=self.manual_xml_template_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.manual_xml_template_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        self.auto_plate_model_section = self._build_workflow_step_card(actions_lf)
        self.auto_plate_model_title_lbl = tk.Label(
            self.auto_plate_model_section,
            text="1. Wskaz model tablic (YOLO Pose)",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.auto_plate_model_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.auto_plate_model_hint_lbl = tk.Label(
            self.auto_plate_model_section,
            text="Ten model jest wymagany, aby uruchomić autoanotację tablic.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0,
        )
        self.auto_plate_model_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        self._set_inline_label_state(self.auto_plate_model_hint_lbl, tone="muted", emphasis=False)
        (
            self.workflow_plate_path_row,
            self.workflow_plate_path_entry,
            self.workflow_plate_browse_btn,
        ) = self._build_left_path_row(
            self.auto_plate_model_section,
            self.plate_custom_var,
            button_text="Wybierz",
            button_command=self._select_plate_custom,
        )
        self.workflow_plate_path_row.configure(style="WorkflowPlatePath.TFrame")
        self._register_workflow_step_card(
            "auto_plate_model",
            self.auto_plate_model_section,
            title=self.auto_plate_model_title_lbl,
            labels=[self.auto_plate_model_hint_lbl],
            style_targets=[
                {"widget": self.workflow_plate_path_row, "kind": "frame", "style": "WorkflowPlatePath.TFrame"},
                {"widget": self.workflow_plate_path_entry, "kind": "entry", "style": "WorkflowPlatePath.TEntry"},
            ],
            step_keys={"auto_plate_model"},
        )

        self.workflow_conf_section = self._build_workflow_step_card(actions_lf)
        self.workflow_conf_title_lbl = tk.Label(
            self.workflow_conf_section,
            textvariable=self.workflow_conf_title_var,
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_conf_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.workflow_conf_hint_lbl = tk.Label(
            self.workflow_conf_section,
            textvariable=self.workflow_conf_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_conf_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        self._set_inline_label_state(self.workflow_conf_hint_lbl, tone="muted", emphasis=False)
        self.workflow_conf_row = tk.Frame(self.workflow_conf_section, bd=0, highlightthickness=0)
        self.workflow_conf_row.pack(fill=tk.X)
        self.workflow_conf_scale = ttk.Scale(
            self.workflow_conf_row,
            from_=0.1,
            to=0.9,
            variable=self.conf_var,
            orient=tk.HORIZONTAL,
            style="WorkflowConf.Horizontal.TScale",
        )
        self.workflow_conf_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.workflow_conf_value_lbl = tk.Label(
            self.workflow_conf_row,
            width=4,
            anchor="e",
            justify=tk.RIGHT,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_conf_value_lbl.pack(side=tk.RIGHT, padx=(5, 0))
        self.conf_var.trace_add("write", lambda *a: self._refresh_confidence_value_labels())
        self._refresh_confidence_value_labels()
        self._register_workflow_step_card(
            "workflow_conf",
            self.workflow_conf_section,
            title=self.workflow_conf_title_lbl,
            labels=[self.workflow_conf_hint_lbl, self.workflow_conf_value_lbl],
            child_frames=[self.workflow_conf_row],
            style_targets=[
                {"widget": self.workflow_conf_scale, "kind": "scale", "style": "WorkflowConf.Horizontal.TScale"},
            ],
            step_keys={"auto_conf", "manual_conf"},
        )

        self.auto_vehicle_choice_section = self._build_workflow_step_card(actions_lf)
        self.auto_vehicle_choice_title_lbl = tk.Label(
            self.auto_vehicle_choice_section,
            text="Czy dodać model pojazdów (YOLO Box)?",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.auto_vehicle_choice_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.auto_vehicle_choice_row = tk.Frame(self.auto_vehicle_choice_section, bd=0, highlightthickness=0)
        self.auto_vehicle_choice_row.columnconfigure(0, weight=1)
        self.auto_vehicle_choice_skip_check = ttk.Checkbutton(
            self.auto_vehicle_choice_row,
            text="Pomijam model pojazdów i wykrywam tylko tablice",
            style="WorkflowAutoVehicleChoice.TCheckbutton",
            variable=self.auto_vehicle_choice_var,
            onvalue="skip",
            offvalue="use",
            command=self._on_auto_vehicle_skip_toggle,
        )
        self.auto_vehicle_choice_skip_check.grid(row=0, column=0, sticky="w")
        self.auto_vehicle_choice_row.pack(fill=tk.X, pady=(6, 0))

        self.auto_vehicle_choice_hint_lbl = tk.Label(
            self.auto_vehicle_choice_section,
            textvariable=self.auto_vehicle_choice_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.auto_vehicle_choice_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self._set_inline_label_state(self.auto_vehicle_choice_hint_lbl, tone="muted", emphasis=False)
        self._register_workflow_step_card(
            "auto_vehicle_choice",
            self.auto_vehicle_choice_section,
            title=self.auto_vehicle_choice_title_lbl,
            labels=[self.auto_vehicle_choice_hint_lbl],
            child_frames=[self.auto_vehicle_choice_row],
            style_targets=[
                {
                    "widget": self.auto_vehicle_choice_skip_check,
                    "kind": "checkbutton",
                    "style": "WorkflowAutoVehicleChoice.TCheckbutton",
                },
            ],
            step_keys={"auto_vehicle_choice"},
        )

        self.workflow_vehicle_model_section = self._build_workflow_step_card(actions_lf)
        self.workflow_vehicle_model_title_lbl = tk.Label(
            self.workflow_vehicle_model_section,
            textvariable=self.workflow_vehicle_model_title_var,
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_vehicle_model_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.workflow_vehicle_model_hint_lbl = tk.Label(
            self.workflow_vehicle_model_section,
            textvariable=self.workflow_vehicle_model_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_vehicle_model_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        self._set_inline_label_state(self.workflow_vehicle_model_hint_lbl, tone="muted", emphasis=False)
        self.workflow_vehicle_combo = ttk.Combobox(
            self.workflow_vehicle_model_section,
            textvariable=self.vehicle_model_var,
            style="WorkflowVehicleModel.TCombobox",
            state="readonly",
        )
        self.workflow_vehicle_combo.pack(fill=tk.X, pady=(0, 2))
        self.workflow_vehicle_combo.bind("<<ComboboxSelected>>", self._on_vehicle_model_change)
        self.workflow_vehicle_custom_row = tk.Frame(self.workflow_vehicle_model_section, bd=0, highlightthickness=0)
        self.workflow_vehicle_custom_entry = ttk.Entry(
            self.workflow_vehicle_custom_row,
            textvariable=self.vehicle_custom_var,
            style="WorkflowVehicleCustom.TEntry",
        )
        self.workflow_vehicle_custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.workflow_vehicle_custom_browse_btn = ttk.Button(
            self.workflow_vehicle_custom_row,
            text="Wybierz",
            style="WorkflowCard.TButton",
            command=self._select_vehicle_custom,
        )
        self.workflow_vehicle_custom_browse_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self._register_workflow_step_card(
            "workflow_vehicle_model",
            self.workflow_vehicle_model_section,
            title=self.workflow_vehicle_model_title_lbl,
            labels=[self.workflow_vehicle_model_hint_lbl],
            child_frames=[self.workflow_vehicle_custom_row],
            style_targets=[
                {"widget": self.workflow_vehicle_combo, "kind": "combobox", "style": "WorkflowVehicleModel.TCombobox"},
                {"widget": self.workflow_vehicle_custom_entry, "kind": "entry", "style": "WorkflowVehicleCustom.TEntry"},
            ],
            step_keys={"auto_vehicle_model", "manual_vehicle_model"},
        )

        self.manual_entry_section = self._build_workflow_step_card(actions_lf)
        self.manual_entry_mode_row = tk.Frame(self.manual_entry_section, bd=0, highlightthickness=0)
        self.manual_entry_mode_row.columnconfigure(0, weight=1)
        self.manual_entry_title_lbl = tk.Label(
            self.manual_entry_section,
            textvariable=self.manual_entry_title_var,
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.manual_entry_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.manual_entry_new_radio = ttk.Radiobutton(
            self.manual_entry_mode_row,
            text="Nowa anotacja",
            style="WorkflowManualEntry.TRadiobutton",
            value="new",
            variable=self.manual_entry_mode_var,
            command=self._on_manual_entry_mode_change,
        )
        self.manual_entry_new_radio.grid(row=0, column=0, sticky="w")
        self.manual_entry_continue_radio = ttk.Radiobutton(
            self.manual_entry_mode_row,
            text="Kontynuuj anotację",
            style="WorkflowManualEntry.TRadiobutton",
            value="continue",
            variable=self.manual_entry_mode_var,
            command=self._on_manual_entry_mode_change,
        )
        self.manual_entry_continue_radio.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.manual_entry_import_radio = ttk.Radiobutton(
            self.manual_entry_mode_row,
            text="Wskaż dowolny run anotacji Z2",
            style="WorkflowManualEntry.TRadiobutton",
            value="import",
            variable=self.manual_entry_mode_var,
            command=self._on_manual_entry_mode_change,
        )
        self.manual_entry_import_radio.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.manual_entry_mode_row.pack(fill=tk.X, pady=(6, 0))

        self.manual_entry_hint_lbl = tk.Label(
            self.manual_entry_section,
            textvariable=self.manual_entry_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.manual_entry_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self._set_inline_label_state(self.manual_entry_hint_lbl, tone="muted", emphasis=False)
        self._register_workflow_step_card(
            "manual_entry",
            self.manual_entry_section,
            title=self.manual_entry_title_lbl,
            labels=[self.manual_entry_hint_lbl],
            child_frames=[self.manual_entry_mode_row],
            style_targets=[
                {
                    "widget": self.manual_entry_new_radio,
                    "kind": "radiobutton",
                    "style": "WorkflowManualEntry.TRadiobutton",
                },
                {
                    "widget": self.manual_entry_continue_radio,
                    "kind": "radiobutton",
                    "style": "WorkflowManualEntry.TRadiobutton",
                },
                {
                    "widget": self.manual_entry_import_radio,
                    "kind": "radiobutton",
                    "style": "WorkflowManualEntry.TRadiobutton",
                },
            ],
            step_keys={"manual_entry"},
        )

        self.manual_history_section = self._build_workflow_step_card(actions_lf)
        self.manual_history_title_lbl = tk.Label(
            self.manual_history_section,
            text="Historia runów autoanotacji Z2",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.manual_history_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.manual_history_combo = ttk.Combobox(
            self.manual_history_section,
            textvariable=self.manual_history_run_var,
            style="WorkflowManualHistory.TCombobox",
            state="readonly",
        )
        self.manual_history_combo.pack(fill=tk.X, pady=(4, 4))
        self.manual_history_combo.bind("<<ComboboxSelected>>", self._on_manual_history_selection_changed)
        self.manual_history_open_btn = ttk.Button(
            self.manual_history_section,
            text="Otwórz run anotacji z historii",
            style="WorkflowCardPrimary.TButton",
            command=self._open_selected_manual_review_history_run,
        )
        self.manual_history_open_btn.pack(fill=tk.X)
        self.manual_history_import_btn = ttk.Button(
            self.manual_history_section,
            text="Wskaż run autoanotacji Z2",
            style="WorkflowCard.TButton",
            command=self._import_or_open_manual_review_run_from_dialog,
        )
        self.manual_history_import_btn.pack(fill=tk.X, pady=(0, 4))
        self.manual_history_hint_lbl = tk.Label(
            self.manual_history_section,
            textvariable=self.manual_history_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0,
        )
        self.manual_history_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self._set_inline_label_state(self.manual_history_hint_lbl, tone="muted", emphasis=False)
        self._register_workflow_step_card(
            "manual_history",
            self.manual_history_section,
            title=self.manual_history_title_lbl,
            labels=[self.manual_history_hint_lbl],
            style_targets=[
                {"widget": self.manual_history_combo, "kind": "combobox", "style": "WorkflowManualHistory.TCombobox"},
            ],
            step_keys={"manual_history"},
        )

        self.workflow_input_section = self._build_workflow_step_card(actions_lf)
        self.workflow_input_title_lbl = tk.Label(
            self.workflow_input_section,
            text="Folder obrazów",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_input_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.workflow_input_hint_lbl = tk.Label(
            self.workflow_input_section,
            text="Wybierz folder z obrazami, na których ma pracować aktualny tor Z2.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_input_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        self._set_inline_label_state(self.workflow_input_hint_lbl, tone="muted", emphasis=False)
        self.workflow_manual_vehicle_assist_check = ttk.Checkbutton(
            self.workflow_input_section,
            text="Opcjonalnie: dodaj boxy pojazdów jako pomoc",
            style="WorkflowManualAssist.TCheckbutton",
            variable=self.manual_vehicle_assist_var,
            command=self._update_manual_xml_template_ui,
        )
        self.workflow_manual_vehicle_assist_hint_lbl = tk.Label(
            self.workflow_input_section,
            textvariable=self.manual_vehicle_assist_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=340,
            bd=0,
            highlightthickness=0,
        )
        self._set_inline_label_state(self.workflow_manual_vehicle_assist_hint_lbl, tone="muted", emphasis=False)
        (
            self.workflow_input_row,
            self.workflow_input_entry,
            self.workflow_input_browse_btn,
        ) = self._build_left_path_row(
            self.workflow_input_section,
            self.input_dir_var,
            button_text="Wybierz obrazy",
            button_command=self._select_input_dir,
        )
        self.workflow_input_row.configure(style="WorkflowInputPath.TFrame")

        self.campaign_reuse_manual_check = ttk.Checkbutton(
            self.workflow_input_section,
            text="Dołącz ręcznie anotowane zdjęcia z wcześniejszych iteracji",
            variable=self.campaign_reuse_manual_var,
            command=self._on_campaign_reuse_manual_toggle,
        )
        self.campaign_reuse_manual_hint_lbl = tk.Label(
            self.workflow_input_section,
            textvariable=self.campaign_reuse_manual_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=340,
            bd=0,
            highlightthickness=0,
        )
        self._set_inline_label_state(self.campaign_reuse_manual_hint_lbl, tone="warning", emphasis=False)
        self._register_workflow_step_card(
            "workflow_input",
            self.workflow_input_section,
            title=self.workflow_input_title_lbl,
            labels=[
                self.workflow_input_hint_lbl,
                self.workflow_manual_vehicle_assist_hint_lbl,
                self.campaign_reuse_manual_hint_lbl,
            ],
            child_frames=[self.workflow_input_row],
            style_targets=[
                {
                    "widget": self.workflow_manual_vehicle_assist_check,
                    "kind": "checkbutton",
                    "style": "WorkflowManualAssist.TCheckbutton",
                },
                {
                    "widget": self.campaign_reuse_manual_check,
                    "kind": "checkbutton",
                    "style": "WorkflowManualAssist.TCheckbutton",
                },
                {"widget": self.workflow_input_row, "kind": "frame", "style": "WorkflowInputPath.TFrame"},
                {"widget": self.workflow_input_entry, "kind": "entry", "style": "WorkflowInputPath.TEntry"},
            ],
            step_keys={"auto_input", "manual_input"},
        )

        self.workflow_nav_row = ttk.Frame(workflow_nav_panel, style="Panel.TFrame")
        self.workflow_nav_row.columnconfigure(0, weight=1)
        self.workflow_nav_row.columnconfigure(1, weight=1)
        self.workflow_nav_row.pack(fill=tk.X)
        self.workflow_back_btn = ttk.Button(
            self.workflow_nav_row,
            text="Wstecz",
            style="WorkflowCard.TButton",
            command=self._go_to_previous_workflow_step,
        )
        self.workflow_back_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.workflow_back_btn.configure(padding=(8, 2), width=NAV_BUTTON_WIDTH)
        self.workflow_next_btn = ttk.Button(
            self.workflow_nav_row,
            text="Dalej",
            style="Accent.TButton",
            command=self._go_to_next_workflow_step,
        )
        self.workflow_next_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.workflow_next_btn.configure(padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self.workflow_start_section = self._build_workflow_step_card(actions_lf)
        self.workflow_start_title_lbl = tk.Label(
            self.workflow_start_section,
            text="Uruchom proces Z2",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_start_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.start_btn_row = tk.Frame(self.workflow_start_section, bd=0, highlightthickness=0)
        self.start_btn_row.pack(fill=tk.X, pady=(6, 0))
        self.start_btn_row.columnconfigure(0, weight=3)
        self.start_btn_row.columnconfigure(1, weight=2)

        self.start_btn_frame = tk.Frame(self.start_btn_row, bd=0, highlightthickness=0)
        self.start_btn_frame.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.start_btn_pulse_frame = tk.Frame(
            self.start_btn_frame,
            bd=0,
            highlightthickness=1
        )
        self.start_btn_pulse_frame.pack(fill=tk.X)

        self.start_btn = ttk.Button(
            self.start_btn_pulse_frame,
            text="Wybierz tor",
            command=self._start_annotation,
            style="WorkflowCardPrimary.TButton"
        )
        self.start_btn.pack(fill=tk.X)

        self.stop_btn = ttk.Button(
            self.start_btn_row,
            text="ZATRZYMAJ",
            style="WorkflowCard.TButton",
            command=self._stop_annotation,
            state=tk.DISABLED
        )
        self.stop_btn.grid(row=0, column=1, sticky="ew")

        self.workflow_start_action_hint_lbl = tk.Label(
            self.workflow_start_section,
            textvariable=self.workflow_action_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0,
        )
        self.workflow_start_action_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self._set_inline_label_state(self.workflow_start_action_hint_lbl, tone="muted", emphasis=False)

        progress_info_row = tk.Frame(self.workflow_start_section, bd=0, highlightthickness=0)
        self.progress_info_row = progress_info_row
        progress_info_row.pack(fill=tk.X, pady=(10, 4))

        self.status_label = tk.Label(
            progress_info_row,
            text="Gotowy",
            anchor="w",
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0
        )
        self.status_label.pack(side=tk.LEFT, anchor=tk.W)
        self._set_inline_label_state(self.status_label, text="Gotowy", tone="neutral", emphasis=True)

        self.progress_counts_lbl = tk.Label(
            progress_info_row,
            textvariable=self.progress_counts_var,
            anchor="e",
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=0
        )
        self.progress_counts_lbl.pack(side=tk.RIGHT, anchor=tk.E)
        self._set_inline_label_state(self.progress_counts_lbl, tone="muted", emphasis=False)

        self.progress = SlimProgressBar(
            self.workflow_start_section,
            maximum=100,
            value=0,
            thickness=2
        )
        self.progress.pack(fill=tk.X, pady=(0, 2))
        self._refresh_workflow_progress_style()
        self._set_progress_counters(0, 0, 0)
        self._register_workflow_step_card(
            "workflow_start",
            self.workflow_start_section,
            title=self.workflow_start_title_lbl,
            labels=[self.status_label, self.progress_counts_lbl, self.workflow_start_action_hint_lbl],
            child_frames=[self.start_btn_row, self.start_btn_frame, self.start_btn_pulse_frame, self.progress_info_row],
            step_keys={"auto_start", "manual_start"},
        )

        self.actions_section_separator = self._build_left_section_separator(self.workflow_entry_shell_inner, pady=(16, 20))

        self.followup_section = self._build_workflow_step_card(self.workflow_entry_shell_inner)
        self.followup_section.pack(fill=tk.X)
        self.followup_title_lbl = SectionHeaderLabel(
            self.followup_section,
            self.app,
            text="3. Reczne poprawki i iteracje",
        )
        self.followup_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.followup_intro_lbl = tk.Label(
            self.followup_section,
            textvariable=self.followup_intro_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.followup_intro_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_label_state(self.followup_intro_lbl, tone="muted", emphasis=False)

        self.followup_actions_row = ttk.Frame(self.followup_section, style="Panel.TFrame")
        self.followup_actions_row.pack(fill=tk.X, pady=(0, 8))
        self.followup_actions_row.columnconfigure(0, weight=1)
        self.followup_actions_row.columnconfigure(1, weight=1)
        self.enter_manual_review_btn = ttk.Button(
            self.followup_actions_row,
            text="Przegladaj i koryguj",
            style="WorkflowCardPrimary.TButton",
            command=self._enter_manual_review_from_auto,
        )
        self.enter_manual_review_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.jump_to_export_btn = ttk.Button(
            self.followup_actions_row,
            text="Utworz dataset",
            style="WorkflowCard.TButton",
            command=self._jump_to_export_section,
        )
        self.jump_to_export_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.run_output_info_lbl = tk.Label(
            self.followup_section,
            textvariable=self.run_output_info_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self._set_inline_label_state(self.run_output_info_lbl, tone="muted", emphasis=False)
        self._bind_full_path_dialog_on_click(
            self.run_output_info_lbl,
            lambda: self._get_preferred_annotation_run_dir(require_xml=True),
            title="Pelna sciezka runu anotacji Z2",
        )

        self.open_run_dir_btn = ttk.Button(
            self.followup_section,
            text="Otworz folder runu anotacji",
            style="WorkflowCard.TButton",
            command=self._open_current_run_dir,
        )

        self.post_annotation_hint_lbl = tk.Label(
            self.followup_section,
            text="",
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self._register_workflow_step_card(
            "workflow_followup",
            self.followup_section,
            labels=[
                self.followup_intro_lbl,
                self.run_output_info_lbl,
                self.post_annotation_hint_lbl,
            ],
            style_targets=[
                {
                    "widget": self.followup_actions_row,
                    "kind": "frame",
                    "style": "WorkflowFollowupActions.TFrame",
                },
            ],
        )

        self.manual_stage_section = self._build_workflow_step_card(self.workflow_entry_shell_inner)
        self.manual_stage_section.pack(fill=tk.X)
        self.manual_stage_title_lbl = SectionHeaderLabel(
            self.manual_stage_section,
            self.app,
            text="Stage kolejnej iteracji",
        )
        self.manual_stage_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.manual_stage_help_lbl = tk.Label(
            self.manual_stage_section,
            text=(
                "Stage to pomocnicza pula zdjec do kolejnej iteracji recznej. "
                "Po eksporcie moga trafia tu nieoznaczone obrazy, a recznie mozesz tez "
                "dolozyc nowa paczke bez mieszania z gotowym runem."
            ),
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.manual_stage_help_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        self._set_inline_label_state(self.manual_stage_help_lbl, tone="muted", emphasis=False)

        self.manual_stage_path_title_lbl = ttk.Label(
            self.manual_stage_section,
            text="Folder stage (kolejna pula do anotacji):",
            style="Panel.TLabel"
        )
        self.manual_stage_path_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.manual_stage_path_row, self.manual_stage_path_entry, _ = self._build_left_path_row(
            self.manual_stage_section,
            self.manual_stage_dir_var,
            state="readonly",
        )
        self._enable_compact_path_entry(
            self.manual_stage_path_entry,
            self.manual_stage_dir_var,
            title="Pelna sciezka folderu stage",
        )

        self.manual_stage_status_lbl = tk.Label(
            self.manual_stage_section,
            textvariable=self.manual_stage_status_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.manual_stage_status_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_label_state(self.manual_stage_status_lbl, tone="muted", emphasis=False)

        self.manual_stage_buttons_row = ttk.Frame(self.manual_stage_section, style="Panel.TFrame")
        self.manual_stage_buttons_row.pack(fill=tk.X, pady=(0, 2))
        self.manual_stage_buttons_row.columnconfigure(0, weight=1)
        self.manual_stage_buttons_row.columnconfigure(1, weight=1)

        self.manual_stage_use_btn = ttk.Button(
            self.manual_stage_buttons_row,
            text="Uzyj stage jako wejscia Z2",
            style="WorkflowCard.TButton",
            command=self._use_manual_plate_stage_as_input,
        )
        self.manual_stage_use_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.manual_stage_add_btn = ttk.Button(
            self.manual_stage_buttons_row,
            text="Dodaj zdjecia do stage",
            style="WorkflowCard.TButton",
            command=self._add_images_to_manual_plate_stage,
        )
        self.manual_stage_add_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self._register_workflow_step_card(
            "workflow_manual_stage",
            self.manual_stage_section,
            labels=[
                self.manual_stage_help_lbl,
                self.manual_stage_status_lbl,
            ],
            style_targets=[
                {
                    "widget": self.manual_stage_path_title_lbl,
                    "kind": "title_label",
                    "style": "WorkflowManualStagePathTitle.TLabel",
                },
                {
                    "widget": self.manual_stage_path_row,
                    "kind": "frame",
                    "style": "WorkflowManualStagePath.TFrame",
                },
                {
                    "widget": self.manual_stage_path_entry,
                    "kind": "entry",
                    "style": "WorkflowManualStagePath.TEntry",
                },
                {
                    "widget": self.manual_stage_buttons_row,
                    "kind": "frame",
                    "style": "WorkflowManualStageButtons.TFrame",
                },
            ],
        )

        self.manual_stage_separator = self._build_left_section_separator(self.workflow_entry_shell_inner, pady=(18, 20))

        self.manual_stage_export_box = tk.Frame(
            self.workflow_entry_shell_inner,
            bd=0,
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        self.manual_stage_export_box.pack(fill=tk.X, pady=(0, 12))

        self.manual_stage_export_title_lbl = tk.Label(
            self.manual_stage_export_box,
            text="Trening modelu YOLO Pose",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            font=("Segoe UI", 9),
        )
        self.manual_stage_export_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))

        self.manual_stage_export_help_lbl = tk.Label(
            self.manual_stage_export_box,
            text=(
                "Jesli chcesz od razu trenowac model YOLO Pose wykrywajacy obrys tablic "
                "rejestracyjnych, ustaw split i wyeksportuj dataset. Potem przejdz do Z4, "
                "gdzie uruchomisz trening."
            ),
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
        )
        self.manual_stage_export_help_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))

        self.manual_stage_export_btn = ttk.Button(
            self.manual_stage_export_box,
            text="Split i eksport",
            style="WorkflowCard.TButton",
            command=self._jump_to_export_section,
        )
        self.manual_stage_export_btn.pack(anchor=tk.W, pady=(2, 0))

        export_lf = self._build_workflow_step_card(self.workflow_entry_shell_inner)
        self.export_section = export_lf
        export_lf.pack(fill=tk.X)
        self.export_title_lbl = SectionHeaderLabel(
            export_lf,
            self.app,
            text="4. Split i eksport datasetu z gotowego runu anotacji",
        )
        self.export_title_lbl.pack(anchor=tk.W, fill=tk.X)

        self.export_intro_lbl = tk.Label(
            export_lf,
            textvariable=self.export_intro_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.export_intro_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_inline_label_state(self.export_intro_lbl, tone="muted", emphasis=False)

        run_row = ttk.Frame(export_lf, style="Panel.TFrame")
        run_row.pack(fill=tk.X, pady=(0, 4))
        self.plate_dataset_run_title_lbl = ttk.Label(
            run_row,
            text="Folder runu anotacji Z2",
            style="Panel.TLabel"
        )
        self.plate_dataset_run_title_lbl.pack(anchor=tk.W)
        run_input, self.plate_dataset_run_entry, self.plate_dataset_run_btn = self._build_left_path_row(
            run_row,
            self.plate_dataset_run_var,
            button_text="WskaĹĽ inny run anotacji",
            button_command=self._select_plate_dataset_run_dir,
        )
        if self.plate_dataset_run_btn is not None:
            self.plate_dataset_run_btn.configure(style="WorkflowCard.TButton")

        img_row = ttk.Frame(export_lf, style="Panel.TFrame")
        img_row.pack(fill=tk.X, pady=(0, 4))
        self.plate_dataset_images_title_lbl = ttk.Label(
            img_row,
            text="Folder obrazow dla wybranego runu anotacji",
            style="Panel.TLabel"
        )
        self.plate_dataset_images_title_lbl.pack(anchor=tk.W)
        img_input, self.plate_dataset_images_entry, self.plate_dataset_images_btn = self._build_left_path_row(
            img_row,
            self.plate_dataset_images_var,
            button_text="WskaĹĽ obrazy",
            button_command=self._select_plate_dataset_images_dir,
        )
        if self.plate_dataset_images_btn is not None:
            self.plate_dataset_images_btn.configure(style="WorkflowCard.TButton")

        out_row = ttk.Frame(export_lf, style="Panel.TFrame")
        out_row.pack(fill=tk.X, pady=(0, 8))
        self.plate_dataset_out_title_lbl = ttk.Label(
            out_row,
            text="Docelowy katalog datasetu",
            style="Panel.TLabel"
        )
        self.plate_dataset_out_title_lbl.pack(anchor=tk.W)
        out_input, self.plate_dataset_out_entry, _ = self._build_left_path_row(
            out_row,
            self.plate_dataset_out_var,
            state="readonly",
        )
        self._enable_compact_path_entry(
            self.plate_dataset_out_entry,
            self.plate_dataset_out_var,
            title="Pelna sciezka katalogu datasetu",
        )

        split_lf = ttk.Frame(export_lf, style="Panel.TFrame")
        split_lf.pack(fill=tk.X, pady=(0, 8))
        self.split_title_lbl = SectionHeaderLabel(
            split_lf,
            self.app,
            text="Podzial train / val / test",
        )
        self.split_title_lbl.pack(anchor=tk.W, fill=tk.X)

        split_grid = ttk.Frame(split_lf, style="Panel.TFrame")
        split_grid.pack(fill=tk.X)

        self.plate_train_title_lbl = ttk.Label(split_grid, text="Train %", style="Panel.TLabel")
        self.plate_train_title_lbl.grid(row=0, column=0, sticky=tk.W)
        self.plate_train_scale = ttk.Scale(
            split_grid,
            from_=50,
            to=90,
            variable=self.plate_train_pct,
            command=lambda e: self._update_plate_dataset_ratio_labels()
        )
        self.plate_train_scale.grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.plate_train_lbl = ttk.Label(split_grid, text="80%", style="Panel.TLabel")
        self.plate_train_lbl.grid(row=0, column=2, sticky=tk.W)

        self.plate_val_title_lbl = ttk.Label(split_grid, text="Val %", style="Panel.TLabel")
        self.plate_val_title_lbl.grid(row=1, column=0, sticky=tk.W)
        self.plate_val_scale = ttk.Scale(
            split_grid,
            from_=5,
            to=40,
            variable=self.plate_val_pct,
            command=lambda e: self._update_plate_dataset_ratio_labels()
        )
        self.plate_val_scale.grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.plate_val_lbl = ttk.Label(split_grid, text="10%", style="Panel.TLabel")
        self.plate_val_lbl.grid(row=1, column=2, sticky=tk.W)

        self.plate_test_title_lbl = ttk.Label(split_grid, text="Test %", style="Panel.TLabel")
        self.plate_test_title_lbl.grid(row=2, column=0, sticky=tk.W)
        self.plate_test_auto_lbl = ttk.Label(
            split_grid,
            text="liczony automatycznie",
            style="PanelMuted.TLabel",
        )
        self.plate_test_auto_lbl.grid(row=2, column=1, sticky=tk.W, padx=5)
        self.plate_test_lbl = ttk.Label(split_grid, text="Test: 10%", style="Panel.TLabel")
        self.plate_test_lbl.grid(row=2, column=2, sticky=tk.W)
        split_grid.columnconfigure(1, weight=1)

        self.export_plate_dataset_btn = ttk.Button(
            export_lf,
            text="EKSPORTUJ DATASET",
            style="WorkflowCardPrimary.TButton",
            command=self._start_plate_dataset_export
        )
        self.export_plate_dataset_btn.pack(fill=tk.X)

        self.plate_export_progress = ttk.Progressbar(
            export_lf,
            style="WorkflowExport.Horizontal.TProgressbar",
            variable=self.plate_export_progress_var,
            maximum=100
        )
        self.plate_export_progress.pack(fill=tk.X, pady=(8, 4))

        self.plate_export_status_lbl = tk.Label(
            export_lf,
            text="WskaĹĽ run anotacji i obrazy do eksportu datasetu.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.plate_export_status_lbl.pack(anchor=tk.W, fill=tk.X)
        self._set_inline_label_state(
            self.plate_export_status_lbl,
            tone="muted",
            emphasis=False
        )

        self.export_back_btn = ttk.Button(
            export_lf,
            text="Wroc do podsumowania wynikow autoanotacji",
            style="WorkflowCard.TButton",
            command=self._close_export_followup,
        )
        self.export_back_btn.pack(fill=tk.X, pady=(10, 0))
        self._register_workflow_step_card(
            "workflow_export",
            self.export_section,
            labels=[
                self.export_intro_lbl,
                self.plate_export_status_lbl,
            ],
            style_targets=[
                {"widget": run_row, "kind": "frame", "style": "WorkflowExportRunRow.TFrame"},
                {
                    "widget": self.plate_dataset_run_title_lbl,
                    "kind": "title_label",
                    "style": "WorkflowExportRunTitle.TLabel",
                },
                {"widget": run_input, "kind": "frame", "style": "WorkflowExportRunInput.TFrame"},
                {
                    "widget": self.plate_dataset_run_entry,
                    "kind": "entry",
                    "style": "WorkflowExportRunInput.TEntry",
                },
                {"widget": img_row, "kind": "frame", "style": "WorkflowExportImagesRow.TFrame"},
                {
                    "widget": self.plate_dataset_images_title_lbl,
                    "kind": "title_label",
                    "style": "WorkflowExportImagesTitle.TLabel",
                },
                {"widget": img_input, "kind": "frame", "style": "WorkflowExportImagesInput.TFrame"},
                {
                    "widget": self.plate_dataset_images_entry,
                    "kind": "entry",
                    "style": "WorkflowExportImagesInput.TEntry",
                },
                {"widget": out_row, "kind": "frame", "style": "WorkflowExportOutRow.TFrame"},
                {
                    "widget": self.plate_dataset_out_title_lbl,
                    "kind": "title_label",
                    "style": "WorkflowExportOutTitle.TLabel",
                },
                {"widget": out_input, "kind": "frame", "style": "WorkflowExportOutInput.TFrame"},
                {
                    "widget": self.plate_dataset_out_entry,
                    "kind": "entry",
                    "style": "WorkflowExportOutInput.TEntry",
                },
                {"widget": split_lf, "kind": "frame", "style": "WorkflowExportSplit.TFrame"},
                {"widget": split_grid, "kind": "frame", "style": "WorkflowExportSplitGrid.TFrame"},
                {
                    "widget": self.plate_train_title_lbl,
                    "kind": "title_label",
                    "style": "WorkflowExportTrainTitle.TLabel",
                },
                {
                    "widget": self.plate_train_scale,
                    "kind": "scale",
                    "style": "WorkflowExportTrain.Horizontal.TScale",
                },
                {
                    "widget": self.plate_train_lbl,
                    "kind": "label",
                    "style": "WorkflowExportTrainValue.TLabel",
                },
                {
                    "widget": self.plate_val_title_lbl,
                    "kind": "title_label",
                    "style": "WorkflowExportValTitle.TLabel",
                },
                {
                    "widget": self.plate_val_scale,
                    "kind": "scale",
                    "style": "WorkflowExportVal.Horizontal.TScale",
                },
                {
                    "widget": self.plate_val_lbl,
                    "kind": "label",
                    "style": "WorkflowExportValValue.TLabel",
                },
                {
                    "widget": self.plate_test_title_lbl,
                    "kind": "title_label",
                    "style": "WorkflowExportTestTitle.TLabel",
                },
                {
                    "widget": self.plate_test_auto_lbl,
                    "kind": "muted_label",
                    "style": "WorkflowExportTestAuto.TLabel",
                },
                {
                    "widget": self.plate_test_lbl,
                    "kind": "label",
                    "style": "WorkflowExportTestValue.TLabel",
                },
                {
                    "widget": self.plate_export_progress,
                    "kind": "progressbar",
                    "style": "WorkflowExport.Horizontal.TProgressbar",
                },
            ],
        )

        self._update_plate_dataset_ratio_labels()
        self._refresh_plate_dataset_export_sources()
        self._refresh_left_panel_route_copy()

        # --- ŚRODKOWA KOLUMNA (PODGLĄD + TERMINAL PROCESU) ---
        preview_host = ttk.Frame(center_frame)
        self.preview_host = preview_host
        preview_host.pack(fill=tk.BOTH, expand=True, padx=5, pady=0)

        list_lf = ttk.LabelFrame(self.preview_left_list_host, text=" Lista wyników anotacji ", padding=8)
        self.preview_list_lf = list_lf
        list_lf.pack(fill=tk.BOTH, expand=True)
        preview_list_meta = ttk.Frame(list_lf, style="Panel.TFrame")
        self.preview_list_meta = preview_list_meta
        preview_list_meta.pack(fill=tk.X, pady=(0, 6))
        self.preview_list_summary_lbl = tk.Label(
            preview_list_meta,
            textvariable=self.preview_list_summary_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=260,
            bd=0,
            highlightthickness=0,
        )

        preview_list_controls = ttk.Frame(preview_list_meta, style="Panel.TFrame")
        self.preview_list_controls = preview_list_controls
        preview_list_controls.pack(fill=tk.X, pady=(0, 4))
        self.preview_list_sort_lbl = tk.Label(
            preview_list_controls,
            text="Kolejność listy",
            anchor="w",
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
        )
        self.preview_list_sort_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
        preview_list_sort_grid = ttk.Frame(preview_list_controls, style="Panel.TFrame")
        self.preview_list_sort_grid = preview_list_sort_grid
        preview_list_sort_grid.pack(fill=tk.X)
        preview_list_sort_grid.columnconfigure(0, weight=1)
        preview_list_sort_grid.columnconfigure(1, weight=1)

        def _build_preview_sort_tile(parent, row, column, sort_mode, title, desc):
            tile = tk.Frame(
                parent,
                bd=0,
                highlightthickness=1,
                padx=8,
                pady=7,
                cursor="hand2",
            )
            tile.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 4, 4 if column == 0 else 0),
                pady=(0, 4),
            )
            title_lbl = tk.Label(
                tile,
                text=title,
                anchor="w",
                justify=tk.LEFT,
                bd=0,
                highlightthickness=0,
                cursor="hand2",
                font=("Segoe UI Semibold", 9),
            )
            title_lbl.pack(anchor=tk.W, fill=tk.X)
            self._preview_list_sort_tiles[sort_mode] = {
                "tile": tile,
                "title": title_lbl,
                "desc": None,
            }
            self._bind_preview_sort_tile(tile, sort_mode)

        _build_preview_sort_tile(
            preview_list_sort_grid,
            0,
            0,
            "Status: ED -> OK -> problem",
            "ED na górze",
            "Najpierw poprawione ręcznie",
        )
        _build_preview_sort_tile(
            preview_list_sort_grid,
            0,
            1,
            "Status: OK -> ED -> problem",
            "OK na górze",
            "Najpierw gotowe obrazy",
        )
        _build_preview_sort_tile(
            preview_list_sort_grid,
            1,
            0,
            "Status: problem -> ED -> OK",
            "Problem na górze",
            "Najpierw brak lub błąd",
        )
        _build_preview_sort_tile(
            preview_list_sort_grid,
            1,
            1,
            "Nazwa pliku A-Z",
            "Nazwa A-Z",
            "Kolejność alfabetyczna",
        )

        preview_list_legend = ttk.Frame(preview_list_meta, style="Panel.TFrame")
        self.preview_list_legend = preview_list_legend
        preview_list_legend.pack(fill=tk.X, pady=(6, 0))
        preview_list_legend_grid = ttk.Frame(preview_list_legend, style="Panel.TFrame")
        self.preview_list_legend_grid = preview_list_legend_grid
        preview_list_legend_grid.pack(fill=tk.X)
        preview_list_legend_grid.columnconfigure(0, weight=1)
        preview_list_legend_grid.columnconfigure(1, weight=1)

        def _build_preview_list_legend_item(parent, row, column, badge_text, text):
            item = tk.Frame(parent, bd=0, highlightthickness=1, padx=6, pady=3)
            item.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 4, 4 if column == 0 else 0),
                pady=(0, 4),
            )
            badge = tk.Label(
                item,
                text=badge_text,
                width=3,
                anchor="center",
                justify=tk.CENTER,
                bd=0,
                highlightthickness=0,
                font=("Segoe UI", 8, "bold"),
                padx=4,
                pady=1,
            )
            badge.pack(side=tk.LEFT)
            label = tk.Label(
                item,
                text=text,
                anchor="w",
                justify=tk.LEFT,
                bd=0,
                highlightthickness=0,
                wraplength=118,
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
            count_lbl = tk.Label(
                item,
                text="0",
                anchor="e",
                justify=tk.RIGHT,
                bd=0,
                highlightthickness=0,
                font=("Segoe UI Semibold", 10),
                width=3,
            )
            count_lbl.pack(side=tk.RIGHT, padx=(8, 0))
            return item, badge, label, count_lbl

        (
            self.preview_list_legend_ok_item,
            self.preview_list_legend_ok_badge,
            self.preview_list_legend_ok_lbl,
            self.preview_list_legend_ok_count_lbl,
        ) = _build_preview_list_legend_item(preview_list_legend_grid, 0, 0, "OK", "Gotowe")
        (
            self.preview_list_legend_corrected_item,
            self.preview_list_legend_corrected_badge,
            self.preview_list_legend_corrected_lbl,
            self.preview_list_legend_corrected_count_lbl,
        ) = _build_preview_list_legend_item(preview_list_legend_grid, 0, 1, "ED", "Po korekcie")
        (
            self.preview_list_legend_problem_item,
            self.preview_list_legend_problem_badge,
            self.preview_list_legend_problem_lbl,
            self.preview_list_legend_problem_count_lbl,
        ) = _build_preview_list_legend_item(preview_list_legend_grid, 1, 0, "--", "Brak / problem")
        (
            self.preview_list_legend_dirty_item,
            self.preview_list_legend_dirty_badge,
            self.preview_list_legend_dirty_lbl,
            self.preview_list_legend_dirty_count_lbl,
        ) = _build_preview_list_legend_item(preview_list_legend_grid, 1, 1, "*", "Niezapisane")
        list_frame = ttk.Frame(list_lf)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_listbox = tk.Listbox(list_frame, font=("Consolas", 9), selectbackground="#3498db", height=16)
        self.preview_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = WebSlimScrollbar(list_frame, command=self.preview_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_listbox.config(yscrollcommand=scroll.set)
        self.preview_listbox.bind("<<ListboxSelect>>", self._on_preview_select)
        self._refresh_preview_list_legend_theme()
        self._refresh_preview_list_summary()

        preview_lf = ttk.LabelFrame(preview_host, text=" Podgląd anotacji ", padding=8)
        self.preview_lf = preview_lf
        preview_lf.pack(fill=tk.BOTH, expand=True)
        preview_tools = ttk.Frame(preview_lf, style="Panel.TFrame")
        self.preview_tools = preview_tools
        self.preview_tools_primary_row = ttk.Frame(preview_tools, style="Panel.TFrame")
        self.preview_tools_primary_row.pack(fill=tk.X)
        self.preview_tools_primary_left = ttk.Frame(self.preview_tools_primary_row, style="Panel.TFrame")
        self.preview_tools_primary_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.preview_tools_primary_right = ttk.Frame(self.preview_tools_primary_row, style="Panel.TFrame")
        self.preview_tools_primary_right.pack(side=tk.RIGHT)
        self.preview_tools_secondary_row = ttk.Frame(preview_tools, style="Panel.TFrame")
        self.preview_tools_secondary_row.pack(fill=tk.X, pady=(6, 0))

        self.preview_prev_btn = ttk.Button(
            self.preview_tools_primary_left,
            text="Poprzednie (Q)",
            command=lambda: self._select_preview_relative(-1),
            state=tk.DISABLED
        )
        self.preview_prev_btn.pack(side=tk.LEFT)

        self.preview_next_btn = ttk.Button(
            self.preview_tools_primary_left,
            text="Nastepne (E)",
            command=lambda: self._select_preview_relative(1),
            state=tk.DISABLED
        )
        self.preview_next_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.preview_fit_btn = ttk.Button(
            self.preview_tools_primary_left,
            text="Dopasuj",
            command=self._fit_preview_image_to_view,
            state=tk.DISABLED
        )
        self.preview_fit_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.preview_draw_btn = ttk.Button(
            self.preview_tools_primary_left,
            text="Nowy polygon 4 pkt (D)",
            command=self._toggle_preview_draw_mode,
            state=tk.DISABLED
        )
        self.preview_draw_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.preview_fullscreen_btn = ttk.Button(
            self.preview_tools_primary_right,
            text="Pełny ekran (Enter)",
            command=self._toggle_preview_fullscreen,
            state=tk.DISABLED
        )
        self.preview_fullscreen_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self.preview_move_stage_btn = ttk.Button(
            self.preview_tools_secondary_row,
            text="Przenies do stage",
            command=self._move_current_preview_image_to_stage,
            state=tk.DISABLED
        )
        self.preview_move_stage_btn.pack(side=tk.LEFT)

        self.preview_delete_image_btn = ttk.Button(
            self.preview_tools_secondary_row,
            text="Usun zdjecie (Del)",
            command=self._delete_current_preview_image_hard,
            state=tk.DISABLED
        )
        self.preview_delete_image_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.preview_fullscreen_hint_lbl = tk.Label(
            preview_lf,
            textvariable=self.preview_fullscreen_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=780,
            bd=0,
            highlightthickness=0
        )
        self.preview_fullscreen_hint_var.set(
            "Wybierz obraz, aby włączyć pełny ekran i narzędzia edycji podglądu."
        )
        self._set_inline_label_state(self.preview_fullscreen_hint_lbl, tone="muted", emphasis=False)
        self.preview_fullscreen_hint_lbl.pack(fill=tk.X, pady=(0, 8))

        self.preview_save_btn = ttk.Button(
            self.preview_tools_primary_right,
            text="Zapisz (Ctrl+S)",
            command=self._save_preview_edits,
            state=tk.DISABLED
        )
        self.preview_save_btn.pack(side=tk.RIGHT)

        preview_hint_frame = ttk.Frame(preview_lf, style="Panel.TFrame")
        self.preview_hint_frame = preview_hint_frame
        self.preview_controls_canvas = tk.Canvas(
            preview_hint_frame,
            height=84,
            bg="#14181d",
            bd=0,
            highlightthickness=0
        )
        self.preview_controls_canvas.pack(fill=tk.X)
        self.preview_controls_canvas.bind(
            "<Configure>",
            lambda _event: self._refresh_preview_controls_legend(),
            add="+"
        )

        canvas_frame = ttk.Frame(preview_lf)
        self.canvas_frame = canvas_frame
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas = ZoomableCanvas(canvas_frame, bg="#1e1e1e", highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas.show_info = False
        self.preview_canvas.reset_shortcut_enabled = False
        self.preview_canvas.max_zoom = 12.0
        self.preview_canvas.set_overlay_renderer(self._draw_annotation_preview_overlay)
        self.preview_canvas.set_interaction_delegate(self)
        self.preview_canvas.bind("<Button-1>", lambda _e: self.preview_canvas.focus_set(), add="+")
        self.preview_canvas.bind("<Button-3>", self._on_preview_canvas_right_click, add="+")
        self.preview_canvas.bind("<FocusOut>", self._on_preview_canvas_focus_out, add="+")
        self._bind_preview_shortcuts()
        self._refresh_preview_controls_legend()

        self.preview_edit_status_lbl = ttk.Label(
            preview_lf,
            textvariable=self.preview_edit_status_var,
            style="PanelMuted.TLabel",
            justify=tk.LEFT,
            wraplength=780
        )
        self.preview_edit_status_lbl.pack(fill=tk.X, pady=(8, 0))
        try:
            self.app.ensure_adaptive_wrap(self.preview_fullscreen_hint_lbl, container=preview_lf, padding=28, min_wrap=280)
            self.app.ensure_adaptive_wrap(self.preview_edit_status_lbl, container=preview_lf, padding=28, min_wrap=280)
        except Exception:
            pass

        self.preview_debug_lbl = tk.Label(
            preview_lf,
            textvariable=self.preview_debug_var,
            font=("Consolas", 8),
            justify=tk.LEFT,
            anchor="w",
            wraplength=780,
            bd=0,
            highlightthickness=0
        )
        try:
            self.app.ensure_adaptive_wrap(self.preview_debug_lbl, container=preview_lf, padding=28, min_wrap=320)
        except Exception:
            pass
        if self._preview_debug_enabled:
            self.preview_debug_lbl.pack(fill=tk.X, pady=(6, 0))
            self._set_inline_label_state(self.preview_debug_lbl, tone="muted", emphasis=False)
        self._refresh_preview_debug_status()

        log_tools = ttk.Frame(center_frame)
        self.log_tools = log_tools
        self.btn_toggle_annotation_log = None

        self.btn_toggle_annotation_log = ttk.Button(
            log_tools,
            text="PokaĹĽ terminal",
            command=self._toggle_annotation_process_log
        )
        self.btn_toggle_annotation_log.pack_forget()

        ttk.Label(
            log_tools,
            text="Terminal procesu jest dostÄ™pny na ĹĽÄ…danie uĹĽytkownika.",
            style="Muted.TLabel"
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.annotation_log_overlay = tk.Frame(
            preview_host,
            bg="#0b0f14",
            bd=1,
            highlightthickness=1,
            highlightbackground="#313b46",
            highlightcolor="#313b46",
        )
        self.annotation_log_frame = ttk.LabelFrame(self.annotation_log_overlay, text=" Terminal procesu ", padding=6)
        self.annotation_log_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        self.annotation_log_host = ttk.Frame(self.annotation_log_frame, style="Panel.TFrame")
        self.annotation_log_host.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            self.annotation_log_host,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#161616",
            fg="#f3f3f3",
            insertbackground="#f3f3f3",
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.annotation_log_scrollbar = WebSlimScrollbar(
            self.annotation_log_host,
            orient=tk.VERTICAL,
            command=self.log_text.yview,
            auto_hide=False,
        )
        self.annotation_log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=self.annotation_log_scrollbar.set)
        self.log_text.web_vbar = self.annotation_log_scrollbar
        self._redirect_logs()
        self._set_annotation_process_log_visibility(False)
        try:
            self.log_tools.pack_forget()
        except Exception:
            pass

        # --- PRAWA KOLUMNA ---
        right_scroll_shell = tk.Frame(
            right_frame,
            bg=panel_bg,
            bd=0,
            highlightthickness=1,
            highlightbackground=panel_border,
            highlightcolor=panel_border,
        )
        right_scroll_shell.pack(fill=tk.BOTH, expand=True)
        self.right_scroll_shell = right_scroll_shell

        right_scroll_host = ttk.Frame(right_scroll_shell, style="Panel.TFrame")
        self.right_scroll_host = right_scroll_host
        right_scroll_host.pack(fill=tk.BOTH, expand=True)

        self.right_settings_canvas = tk.Canvas(right_scroll_host, bg=panel_bg, highlightthickness=0, bd=0)
        self.right_settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.right_settings_scrollbar = WebSlimScrollbar(
            right_scroll_host,
            command=self.right_settings_canvas.yview
        )
        self.right_settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_settings_canvas.configure(yscrollcommand=self.right_settings_scrollbar.set)

        self.right_settings_content = ttk.Frame(self.right_settings_canvas, style="Panel.TFrame")
        self._right_settings_window_id = self.right_settings_canvas.create_window(
            (0, 0),
            window=self.right_settings_content,
            anchor="nw"
        )
        self.right_settings_content.bind("<Configure>", self._sync_right_panel_scrollregion)
        self.right_settings_canvas.bind("<Configure>", self._sync_right_panel_canvas_width)

        settings_lf = ttk.LabelFrame(self.right_settings_content, text=" Konfiguracja Detekcji ", padding=15)
        self.detection_settings_lf = settings_lf
        settings_lf.pack(fill=tk.BOTH, expand=True)

        self.approve_btn_row = ttk.LabelFrame(right_scroll_shell, text=" Domkniecie E2 ", padding=10)
        self.approve_btn_row.pack(fill=tk.X, pady=(8, 0))
        self.approve_btn_row.bind("<Configure>", self._sync_approve_hint_wraplength, add="+")

        self.approve_hint_box = tk.Frame(
            self.approve_btn_row,
            bd=0,
            highlightthickness=1
        )
        self.approve_hint_box.pack(fill=tk.X, pady=(0, 10))

        self.approve_gate_hint_lbl = tk.Label(
            self.approve_hint_box,
            textvariable=self.approve_gate_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=320,
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=8
        )
        self.approve_gate_hint_lbl.pack(fill=tk.X)
        self._set_inline_label_state(self.approve_gate_hint_lbl, tone="muted", emphasis=False)
        self._set_approve_hint_box_state("muted")

        self.mode_title_lbl = ttk.Label(settings_lf, text="Tryb pracy:", font=("Segoe UI", 9, "bold"))
        self.mode_title_lbl.pack(anchor=tk.W, pady=(0, 2))
        modes = ["B: Tylko tablice", "C: Pojazdy + tablice"]
        self.mode_combo = ttk.Combobox(settings_lf, textvariable=self.mode_var, values=modes, state="readonly")
        self.mode_combo.pack(fill=tk.X, pady=(0, 4))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)
        self.mode_hint_lbl = tk.Label(
            settings_lf,
            textvariable=self.detection_mode_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=340,
            bd=0,
            highlightthickness=0,
        )
        self.mode_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 12))

        self.veh_frame = ttk.LabelFrame(settings_lf, text=" Model pojazdów (Detect) ", padding=10)
        self.veh_frame.pack(fill=tk.X, pady=(0, 10))
        self.vehicle_combo = ttk.Combobox(self.veh_frame, textvariable=self.vehicle_model_var, state="readonly")
        self.vehicle_combo.pack(fill=tk.X, pady=2)
        self.vehicle_combo.bind("<<ComboboxSelected>>", self._on_vehicle_model_change)
        self.veh_custom_row = ttk.Frame(self.veh_frame)
        ttk.Entry(self.veh_custom_row, textvariable=self.vehicle_custom_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self.veh_custom_row, text="Wybierz", command=self._select_vehicle_custom).pack(side=tk.RIGHT, padx=(5,0))
        self.veh_custom_row.pack(fill=tk.X, pady=(5,0))

        self.pla_frame = ttk.LabelFrame(settings_lf, text=" Model Tablic (.pt / Pose) ", padding=10)
        self.pla_frame.pack(fill=tk.X, pady=(0, 10))
        self.pla_custom_row = ttk.Frame(self.pla_frame)
        self.pla_custom_row.pack(fill=tk.X, pady=2)
        self.plate_path_entry = ttk.Entry(self.pla_custom_row, textvariable=self.plate_custom_var)
        self.plate_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.plate_browse_btn = ttk.Button(self.pla_custom_row, text="Wybierz", command=self._select_plate_custom)
        self.plate_browse_btn.pack(side=tk.RIGHT, padx=(5,0))

        param_frame = ttk.LabelFrame(settings_lf, text=" Parametry ", padding=10)
        self.param_frame = param_frame
        param_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(param_frame, text="Pewność (Confidence):").pack(anchor=tk.W)
        row_conf = ttk.Frame(param_frame)
        row_conf.pack(fill=tk.X, pady=2)
        ttk.Scale(row_conf, from_=0.1, to=0.9, variable=self.conf_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.conf_value_lbl = ttk.Label(row_conf, width=4)
        self.conf_value_lbl.pack(side=tk.RIGHT, padx=(5,0))
        self.conf_var.trace_add("write", lambda *a: self._refresh_confidence_value_labels())
        self._refresh_confidence_value_labels()

        ttk.Label(param_frame, text="Urządzenie (Device):").pack(anchor=tk.W, pady=(10, 0))
        self.device_combo = ttk.Combobox(param_frame, textvariable=self.device_var, values=self._get_available_devices(), state="readonly")
        self.device_combo.pack(fill=tk.X, pady=2)
        self.device_combo.bind("<<ComboboxSelected>>", self._update_device_hint, add="+")

        self.device_hint_lbl = ttk.Label(
            param_frame,
            text="",
            foreground="gray",
            font=("Segoe UI", 8),
            wraplength=320,
            justify=tk.LEFT
        )
        self.device_hint_lbl.pack(fill=tk.X, pady=(0, 4))

        self.approve_btn_frame = tk.Frame(self.approve_btn_row, bd=0, highlightthickness=0)
        self.approve_btn_frame.pack(fill=tk.X)

        self.approve_btn_pulse_frame = tk.Frame(
            self.approve_btn_frame,
            bd=0,
            highlightthickness=1
        )
        self.approve_btn_pulse_frame.pack(fill=tk.X)

        self.approve_btn = ttk.Button(
            self.approve_btn_pulse_frame,
            text="DOMKNIJ ETAP E2",
            command=self._approve_annotation_stage,
            state=tk.DISABLED
        )
        self.approve_btn.pack(fill=tk.X)

        # Podpinanie systemu pomocy pod lokalnÄ… konsolÄ™
        HELP.bind_help(self.input_dir_title_lbl, "tab1_input")
        HELP.bind_help(row_in, "tab1_input")
        HELP.bind_help(self.output_dir_title_lbl, "tab1_output")
        HELP.bind_help(row_out, "tab1_output")
        HELP.bind_help(self.run_title_lbl, "tab1_start")
        HELP.bind_help(self.route_badge_lbl, "tab1_start")
        HELP.bind_help(self.route_summary_lbl, "tab1_start")
        HELP.bind_help(self.auto_plate_model_section, "tab1_model_pla")
        HELP.bind_help(self.workflow_plate_path_entry, "tab1_model_pla")
        HELP.bind_help(self.workflow_conf_row, "tab1_conf")
        HELP.bind_help(self.auto_vehicle_choice_title_lbl, "tab1_model_veh")
        HELP.bind_help(self.auto_vehicle_choice_row, "tab1_model_veh")
        HELP.bind_help(self.workflow_vehicle_model_section, "tab1_model_veh")
        HELP.bind_help(self.workflow_vehicle_combo, "tab1_model_veh")
        HELP.bind_help(self.workflow_manual_vehicle_assist_check, "tab1_model_veh")
        HELP.bind_help(self.workflow_input_section, "tab1_input")
        HELP.bind_help(self.workflow_input_entry, "tab1_input")
        HELP.bind_help(self.workflow_nav_row, "tab1_start")
        HELP.bind_help(self.auto_route_radio, "tab1_start")
        HELP.bind_help(self.manual_route_radio, "tab1_start")
        HELP.bind_help(self.mode_combo, "tab1_mode")
        HELP.bind_help(self.vehicle_combo, "tab1_model_veh")
        HELP.bind_help(self.pla_frame, "tab1_model_pla")
        HELP.bind_help(self.plate_path_entry, "tab1_model_pla")
        HELP.bind_help(self.export_title_lbl, "tab1_dataset_export")
        HELP.bind_help(self.plate_dataset_run_title_lbl, "tab1_dataset_run")
        HELP.bind_help(run_row, "tab1_dataset_run")
        HELP.bind_help(self.plate_dataset_images_title_lbl, "tab1_dataset_images")
        HELP.bind_help(img_row, "tab1_dataset_images")
        HELP.bind_help(self.plate_dataset_out_title_lbl, "tab1_dataset_export")
        HELP.bind_help(self.split_title_lbl, "tab1_dataset_split")
        HELP.bind_help(split_lf, "tab1_dataset_split")
        HELP.bind_help(self.export_plate_dataset_btn, "tab1_dataset_export")
        HELP.bind_help(self.followup_section, "tab1_dataset_export")
        HELP.bind_help(self.followup_title_lbl, "tab1_dataset_export")
        HELP.bind_help(self.followup_intro_lbl, "tab1_dataset_export")
        HELP.bind_help(self.post_annotation_hint_lbl, "tab1_dataset_export")
        HELP.bind_help(self.manual_stage_section, "tab1_stage")
        HELP.bind_help(self.manual_stage_title_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_help_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_path_title_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_path_entry, "tab1_stage")
        HELP.bind_help(self.manual_stage_status_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_use_btn, "tab1_stage_use")
        HELP.bind_help(self.manual_stage_add_btn, "tab1_stage_add")
        HELP.bind_help(self.manual_stage_export_box, "tab1_dataset_export")
        HELP.bind_help(self.manual_stage_export_title_lbl, "tab1_dataset_export")
        HELP.bind_help(self.manual_stage_export_help_lbl, "tab1_dataset_export")
        HELP.bind_help(self.manual_stage_export_btn, "tab1_dataset_export")
        HELP.bind_help(self.export_back_btn, "tab1_dataset_export")
        HELP.bind_help(self.plate_browse_btn, "tab1_model_pla")
        HELP.bind_help(row_conf, "tab1_conf") 
        HELP.bind_help(self.device_combo, "tab1_device")
        HELP.bind_help(self.start_btn, "tab1_start")
        HELP.bind_help(self.stop_btn, "tab1_stop")
        HELP.bind_help(self.btn_toggle_annotation_log, "tab1_logs")
        HELP.bind_help(self.preview_listbox, "tab1_preview_list")
        HELP.bind_help(self.preview_canvas, "tab1_preview_canvas")
        HELP.bind_help(self.veh_custom_row, "tab1_custom_model")
        HELP.bind_help(self.approve_btn, "tab1_approve")
        self._bind_scroll_canvas_children(self.left_settings_content, self.left_settings_canvas)
        self._bind_scroll_canvas_children(self.right_settings_content, self.right_settings_canvas)
        self.frame.after_idle(self._sync_left_panel_canvas_width)
        self.frame.after_idle(self._sync_left_panel_scrollregion)
        self.frame.after_idle(self._sync_right_panel_canvas_width)
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self.frame.after_idle(self._sync_approve_hint_wraplength)
        self.frame.after_idle(lambda: self._schedule_main_pane_layout_refresh(force_defaults=True))
        self.frame.bind_all("<MouseWheel>", self._on_left_panel_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_left_panel_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_left_panel_global_mousewheel, add="+")
        self.frame.bind_all("<MouseWheel>", self._on_right_panel_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_right_panel_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_right_panel_global_mousewheel, add="+")
        self._sync_main_pane_right_panel_visibility()
        self._refresh_free_mode_workflow_ui()

    def _normalize_mode_value(self, mode: str | None = None) -> str:
        raw = str(mode if mode is not None else self.mode_var.get() or "").strip()
        if raw.startswith("B:"):
            return "B: Tylko tablice"
        return "C: Pojazdy + tablice"

    def _mode_uses_vehicle(self, mode: str | None = None) -> bool:
        return self._normalize_mode_value(mode).startswith("C:")

    def _mode_uses_plate(self, mode: str | None = None) -> bool:
        normalized = self._normalize_mode_value(mode)
        return normalized.startswith("B:") or normalized.startswith("C:")

    def _vehicle_model_controls_enabled(self, mode: str | None = None) -> bool:
        if self._manual_xml_template_enabled():
            return True
        return self._mode_uses_vehicle(mode)

    def _plate_model_controls_enabled(self, mode: str | None = None) -> bool:
        if self._manual_xml_template_enabled():
            return False
        return self._mode_uses_plate(mode)

    def _refresh_detection_configuration_ui(self):
        mode = self._normalize_mode_value()
        manual_enabled = self._manual_xml_template_enabled()
        vehicle_assist_enabled = self._manual_vehicle_assist_enabled()

        if hasattr(self, "mode_combo"):
            try:
                self.mode_combo.configure(state="disabled" if manual_enabled else "readonly")
            except Exception:
                pass

        if hasattr(self, "mode_hint_lbl"):
            if manual_enabled:
                if vehicle_assist_enabled:
                    self.detection_mode_hint_var.set(
                        "Przy recznej anotacji wybor B/C jest ignorowany. Z2 uzyje zapamietanego modelu YOLO pojazdow tylko do utworzenia nowego XML z boxami pojazdow."
                    )
                else:
                    self.detection_mode_hint_var.set(
                        "Przy recznej anotacji wybor B/C jest ignorowany. Z2 zapamietuje wybrane YOLO pojazdow, ale wykorzysta je dopiero po wlaczeniu wstepnego boxowania pojazdow."
                    )
                self._set_inline_label_state(self.mode_hint_lbl, tone="info", emphasis=False)
            else:
                self.detection_mode_hint_var.set(
                    "Tryb B/C decyduje, czy Z2 ma uzyc tylko modelu tablic, czy modelu pojazdow i tablic."
                )
                self._set_inline_label_state(self.mode_hint_lbl, tone="muted", emphasis=False)

        vehicle_combo_state = "readonly" if self._vehicle_model_controls_enabled(mode) else "disabled"
        for combo in (
            getattr(self, "vehicle_combo", None),
            getattr(self, "workflow_vehicle_combo", None),
        ):
            if combo is None:
                continue
            try:
                combo.config(state=vehicle_combo_state)
            except Exception:
                pass

        self._on_vehicle_model_change(refresh_workflow=False)
        self._set_plate_model_controls_state(self._plate_model_controls_enabled(mode))

    def _set_progress_counters(self, successful: int, current: int, total: int):
        try:
            self.progress_counts_var.set(
                f"udane/przer./caĹ‚oĹ›Ä‡: {int(successful)}/{int(current)}/{int(total)}"
            )
        except Exception:
            pass

    def _on_mode_change(self, event=None):
        mode = self._normalize_mode_value()
        if mode != self.mode_var.get():
            self.mode_var.set(mode)
        self._refresh_detection_configuration_ui()

    def _update_model_lists(self):
        if YOLO_AVAILABLE:
            v_keys = sorted(list(AVAILABLE_DETECT_MODELS.keys()))
            vehicle_values = v_keys + ["Custom"]
            for combo in (
                getattr(self, "vehicle_combo", None),
                getattr(self, "workflow_vehicle_combo", None),
            ):
                if combo is None:
                    continue
                try:
                    combo["values"] = vehicle_values
                except Exception:
                    pass
            if not self.vehicle_model_var.get() and v_keys:
                preferred_vehicle = "yolo11s" if "yolo11s" in v_keys else v_keys[0]
                self.vehicle_model_var.set(preferred_vehicle)

        if hasattr(self, "character_combo"):
            self._refresh_character_model_choices()

    def _on_vehicle_model_change(self, event=None, *, refresh_workflow: bool = True):
        for combo, custom_row in (
            (getattr(self, "vehicle_combo", None), getattr(self, "veh_custom_row", None)),
            (
                getattr(self, "workflow_vehicle_combo", None),
                getattr(self, "workflow_vehicle_custom_row", None),
            ),
        ):
            if combo is None or custom_row is None:
                continue

            try:
                combo_state = str(combo.cget("state"))
            except Exception:
                combo_state = "readonly"

            should_show = self.vehicle_model_var.get() == "Custom" and combo_state != "disabled"
            if should_show:
                custom_row.pack(fill=tk.X, pady=(5, 0))
            else:
                custom_row.pack_forget()

        if refresh_workflow and self._is_free_mode_session_context():
            current_step = self._coerce_workflow_step()
            if current_step in {"manual_entry", "manual_input", "auto_vehicle_model", "manual_vehicle_model"}:
                self._refresh_left_panel_route_copy()
                self._refresh_step2_action_states()
                self._refresh_free_mode_workflow_ui()

    def _set_plate_model_controls_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"

        for widget in (
            getattr(self, "plate_path_entry", None),
            getattr(self, "plate_browse_btn", None),
            getattr(self, "workflow_plate_path_entry", None),
            getattr(self, "workflow_plate_browse_btn", None),
        ):
            if widget is None:
                continue
            try:
                widget.configure(state=state)
            except Exception:
                pass

    def _get_bound_character_model_path(self) -> str:
        try:
            from ..campaign_manager import CAMPAIGN
            model_path = CAMPAIGN.get_global_model("char")
            if model_path and Path(model_path).exists():
                return str(Path(model_path))
        except Exception:
            pass

        try:
            tab_char = getattr(self.app, "tabs", {}).get("characters")
            if tab_char is not None:
                model_path = (tab_char.yolo_model_path_var.get() or "").strip()
                if model_path and model_path != "Brak modelu znakow w projekcie" and Path(model_path).exists():
                    return str(Path(model_path))
        except Exception:
            pass

        return ""

    def _collect_character_model_candidates(self, active_path: str = ""):
        candidates = []
        for chars_dir in CONFIG.get_model_search_dirs("char"):
            if not chars_dir.exists():
                continue
            candidates.extend(
                sorted(
                    chars_dir.rglob("*.pt"),
                    key=lambda p: (str(p.parent).lower(), p.name.lower())
                )
            )

        if active_path:
            active_model = Path(active_path)
            if active_model.exists() and active_model not in candidates:
                candidates.append(active_model)

        unique = []
        seen = set()
        for candidate in candidates:
            key = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)

        return unique

    def _refresh_character_model_choices(self):
        if not hasattr(self, "character_combo"):
            return

        current_path = (self._get_selected_character_model_path() or "").strip()
        if not current_path:
            current_path = self._get_bound_character_model_path()

        options = {"Brak / OCR": ""}
        for model_path in self._collect_character_model_candidates(current_path):
            label = model_path.name
            if label in options:
                label = f"{model_path.parent.name}/{model_path.name}"
            if label in options:
                label = str(model_path)
            options[label] = str(model_path)

        options["Custom"] = "__custom__"
        self._character_model_options = options
        self.character_combo["values"] = list(options.keys())

        if current_path:
            for label, model_path in options.items():
                if model_path == current_path:
                    self.character_model_var.set(label)
                    break
            else:
                self.character_model_var.set("Custom")
                self.character_custom_var.set(current_path)
        elif not self.character_model_var.get() or self.character_model_var.get() not in options:
            self.character_model_var.set("Brak / OCR")

        self._on_character_model_change(propagate=False)

    def _get_selected_character_model_path(self) -> str:
        selected = (self.character_model_var.get() or "").strip()
        if selected == "Custom":
            return (self.character_custom_var.get() or "").strip()
        return self._character_model_options.get(selected, "")

    def _apply_character_model_selection(self):
        if not hasattr(self, "character_combo"):
            return

        selected_path = (self._get_selected_character_model_path() or "").strip()
        effective_path = selected_path if selected_path and Path(selected_path).exists() else ""

        try:
            from ..campaign_manager import CAMPAIGN
            if CAMPAIGN.get_active_project_name():
                CAMPAIGN.set_global_model("char", effective_path)
                try:
                    campaign_tab = getattr(self.app, "tabs", {}).get("campaign")
                    if campaign_tab is not None:
                        campaign_tab._refresh_dashboard()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            tab_char = getattr(self.app, "tabs", {}).get("characters")
            if tab_char is not None:
                tab_char.yolo_model_path_var.set(effective_path)

                if effective_path:
                    try:
                        version, size = tab_char._infer_yolo_arch_from_model_path(effective_path)
                        if version in {"8", "11", "26"}:
                            tab_char.yolo_model_version_var.set(version)
                        if size in {"n", "s", "m", "l", "x"}:
                            tab_char.yolo_model_size_var.set(size)
                    except Exception:
                        pass

                try:
                    tab_char._sync_yolo_model_binding()
                except Exception:
                    pass

                try:
                    tab_char._update_yolo_visibility()
                except Exception:
                    pass

                try:
                    tab_char._force_save_all()
                except Exception:
                    pass
        except Exception:
            pass

    def _on_character_model_change(self, event=None, propagate=True):
        if not hasattr(self, "char_custom_row"):
            return

        if self.character_model_var.get() == "Custom" and str(self.character_combo.cget("state")) != "disabled":
            self.char_custom_row.pack(fill=tk.X, pady=(5,0))
        else:
            self.char_custom_row.pack_forget()
            if self.character_model_var.get() != "Custom":
                self.character_custom_var.set("")

        if propagate:
            self._apply_character_model_selection()

    # WĹ‚asne modele wybieramy domyĹ›lnie z katalogu modeli.
    def _select_vehicle_custom(self):
        initial_dir = CONFIG.get_trained_models_dir("vehicle")
        if not initial_dir.exists():
            initial_dir = CONFIG.DIR_6_MODELS
        p = filedialog.askopenfilename(initialdir=str(Path(initial_dir).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p:
            self.vehicle_custom_var.set(p)
            if self._is_free_mode_session_context():
                current_step = self._coerce_workflow_step()
                if current_step == "auto_vehicle_model":
                    self._go_to_next_workflow_step()
                elif current_step in {"manual_entry", "manual_input", "manual_vehicle_model"}:
                    self._refresh_left_panel_route_copy()
                    self._refresh_detection_configuration_ui()
                    self._refresh_step2_action_states()
                    self._refresh_free_mode_workflow_ui()

    def _select_plate_custom(self):
        initial_dir = CONFIG.get_trained_models_dir("plate")
        if not initial_dir.exists():
            initial_dir = CONFIG.DIR_6_MODELS
        p = filedialog.askopenfilename(initialdir=str(Path(initial_dir).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p:
            self.plate_custom_var.set(p)
            if self._is_free_mode_session_context() and self._get_workflow_step() == "auto_plate_model":
                self._go_to_next_workflow_step()

    def _select_character_custom(self):
        initial_dir = CONFIG.get_trained_models_dir("char")
        if not initial_dir.exists():
            initial_dir = CONFIG.DIR_6_MODELS
        p = filedialog.askopenfilename(initialdir=str(Path(initial_dir).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p:
            self.character_custom_var.set(p)
            self.character_model_var.set("Custom")
            self._on_character_model_change()

    def _select_input_dir(self):
        p = filedialog.askdirectory(initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()))
        if p:
            self._switch_annotation_input_dir(Path(p), show_hint=False)

    def _format_workspace_relative_path(self, path_like) -> str:
        raw_text = self._path_value_to_text(path_like)
        if not raw_text:
            return ""

        try:
            path = Path(raw_text).resolve()
            workspace = Path(CONFIG.WORKSPACE_DIR).resolve()
            rel = path.relative_to(workspace)
            return str(Path("Workspace") / rel)
        except Exception:
            try:
                path = Path(raw_text).resolve()
            except Exception:
                try:
                    path = Path(raw_text)
                except Exception:
                    return raw_text

            try:
                parts = [
                    str(part or "").strip().replace(":", "")
                    for part in path.parts
                    if str(part or "").strip() not in {"", ".", "..", "/", "\\", str(path.anchor or "").strip()}
                ]
                if not parts:
                    return str(path.name or raw_text)
                if len(parts) <= 3:
                    return str(Path(*parts))
                return str(Path("...") / Path(*parts[-3:]))
            except Exception:
                return raw_text

    def _get_annotation_run_storage_display_path(self) -> str:
        try:
            base_dir = self._get_annotation_output_base_dir()
        except Exception:
            return "Workspace"
        return self._format_workspace_relative_path(base_dir) or str(base_dir)

    def _get_annotation_run_definition_text(self) -> str:
        return (
            "Run autoanotacji Z2 to katalog z plikiem annotations.xml i zgodnymi obrazami "
            "(najczesciej w folderze images/ albo obok XML). Taki run moze tez zawierac "
            "report.txt i run_manifest.json. To nie jest dataset treningowy ani katalog eksportu."
        )

    def _show_full_path_dialog(self, path_like, *, title: str = "Pelna sciezka"):
        full_path = str(path_like or "").strip()
        if not full_path:
            return

        dialog = tk.Toplevel(self.frame)
        dialog.title(title)
        try:
            dialog.transient(getattr(self.app, "root", None) or self.frame.winfo_toplevel())
        except Exception:
            pass
        try:
            dialog.grab_set()
        except Exception:
            pass
        dialog.resizable(True, False)

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text="Pelna sciezka", style="Panel.TLabel").pack(anchor=tk.W, fill=tk.X)

        text = tk.Text(body, height=4, wrap=tk.NONE, bd=1, highlightthickness=0)
        text.pack(fill=tk.BOTH, expand=True, pady=(8, 10))
        text.insert("1.0", full_path)
        text.configure(state="disabled")

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        def copy_path():
            try:
                dialog.clipboard_clear()
                dialog.clipboard_append(full_path)
                dialog.update_idletasks()
            except Exception:
                pass

        ttk.Button(buttons, text="Kopiuj", command=copy_path).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Zamknij", command=dialog.destroy).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _bind_full_path_dialog_on_click(self, widget, path_provider, *, title: str):
        if widget is None or not callable(path_provider):
            return

        def open_dialog(_event=None):
            try:
                path_value = path_provider()
            except Exception:
                path_value = ""
            if str(path_value or "").strip():
                self._show_full_path_dialog(path_value, title=title)
            return "break"

        try:
            widget.configure(cursor="hand2")
        except Exception:
            pass

        for sequence in ("<Button-1>", "<Return>", "<space>"):
            try:
                widget.bind(sequence, open_dialog, add="+")
            except Exception:
                pass

    def _enable_compact_path_entry(self, entry, path_var, *, title: str):
        if entry is None or path_var is None:
            return

        display_var = tk.StringVar(value=self._format_workspace_relative_path(path_var.get()))
        self._compact_path_display_vars.append(display_var)

        def sync_display(*_args):
            try:
                display_var.set(self._format_workspace_relative_path(path_var.get()))
            except Exception:
                pass

        try:
            path_var.trace_add("write", sync_display)
        except Exception:
            pass

        try:
            entry.configure(textvariable=display_var, state="readonly", cursor="hand2")
        except Exception:
            return

        self._bind_full_path_dialog_on_click(
            entry,
            lambda: str(path_var.get() or "").strip(),
            title=title,
        )

    def _annotation_run_manifest_path(self, run_dir: Path) -> Path:
        return Path(run_dir) / "run_manifest.json"

    def _write_annotation_run_manifest(self, run_dir: Path, input_dir: Path):
        run_dir = self._resolve_safe_annotation_run_dir(run_dir)
        if run_dir is None:
            return

        manifest_path = self._annotation_run_manifest_path(run_dir)
        payload = {
            "input_dir": str(Path(input_dir).resolve()),
            "run_dir": str(Path(run_dir).resolve()),
            "mode": str(self.mode_var.get() or "").strip(),
            "device": str(self.device_var.get() or "").strip(),
            "annotation_run_type": (
                "manual_template" if getattr(self, "_current_run_manual_template", False) else "auto_annotation"
            ),
            "manual_xml_template": bool(getattr(self, "_current_run_manual_template", False)),
            "manual_vehicle_assist": bool(getattr(self, "_current_run_manual_vehicle_assist", False)),
            "has_manual_edits": False,
            "last_manual_edit_at": "",
            "last_manual_edit_kind": "",
            "run_status": "created",
            "completed_at": "",
            "last_error": "",
            "result_total_images": 0,
            "result_successful_images": 0,
            "result_total_plates": 0,
            "resume_preview_index": -1,
            "resume_preview_filename": "",
            "resume_preview_saved_at": "",
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _load_annotation_run_manifest(self, run_dir: Path) -> dict:
        manifest_path = self._annotation_run_manifest_path(run_dir)
        if not manifest_path.exists():
            return {}
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _update_annotation_run_manifest(self, run_dir: Path, **fields) -> bool:
        run_dir = self._resolve_safe_annotation_run_dir(run_dir)
        if run_dir is None:
            return False

        manifest = self._load_annotation_run_manifest(run_dir)
        if not isinstance(manifest, dict):
            manifest = {}

        for key, value in fields.items():
            manifest[key] = value

        try:
            self._annotation_run_manifest_path(run_dir).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

    def _collect_preview_resume_manifest_fields(self) -> dict:
        selected_ann = self._get_preview_annotation()
        return {
            "resume_preview_index": (
                int(self.current_preview_index)
                if self.current_preview_index is not None
                else -1
            ),
            "resume_preview_filename": str(getattr(selected_ann, "filename", "") or "").strip(),
            "resume_preview_saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

    def _remember_annotation_run_resume_state(self, run_dir: Path | None = None) -> bool:
        candidate = run_dir
        if candidate is None:
            candidate = getattr(self, "current_annotation_run_dir", None)
        if candidate is None:
            candidate = getattr(self, "last_staging_run_dir", None)
        if candidate is None:
            run_dir_value = str(self.plate_dataset_run_var.get() or "").strip()
            candidate = Path(run_dir_value) if run_dir_value else None

        if candidate is None:
            return False

        candidate = self._resolve_safe_annotation_run_dir(candidate)
        if candidate is None:
            return False

        return self._update_annotation_run_manifest(
            candidate,
            **self._collect_preview_resume_manifest_fields(),
        )

    def _mark_annotation_run_completed(
        self,
        run_dir: Path | None,
        annotations: list[ImageAnnotation] | None = None,
        *,
        manual_template: bool = False,
        report: AnnotationReport | None = None,
    ) -> bool:
        if run_dir is None:
            return False

        records = list(annotations or [])
        total_images = len(records)
        successful_images = (
            total_images
            if manual_template
            else sum(1 for ann in records if getattr(ann, "is_successful", False))
        )
        total_plates = sum(len(self._get_plate_detections(ann)) for ann in records)

        return self._update_annotation_run_manifest(
            run_dir,
            run_status="completed",
            completed_at=datetime.datetime.now().isoformat(timespec="seconds"),
            last_error="",
            result_total_images=int(total_images),
            result_successful_images=int(successful_images),
            result_total_plates=int(total_plates),
            result_report_errors=int(getattr(report, "errors", 0) or 0),
            result_report_skipped=int(getattr(report, "skipped", 0) or 0),
        )

    def _restore_campaign_step2_generated_from_run(
        self,
        run_dir: Path | None = None,
        *,
        only_when_pending: bool = False,
    ) -> bool:
        try:
            from ..campaign_manager import CAMPAIGN
        except Exception:
            return False

        if not CAMPAIGN.get_active_project_name():
            return False

        try:
            current_step = int(CAMPAIGN.get_current_step() or 0)
        except Exception:
            current_step = 0

        if current_step != 2:
            return False

        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
        if only_when_pending and step2_status not in {"", "pending"}:
            return False

        candidate = self._resolve_existing_run_dir(run_dir)
        if candidate is None:
            candidate = self._resolve_existing_run_dir(getattr(self, "current_annotation_run_dir", None))
        if candidate is None:
            candidate = self._resolve_existing_run_dir(getattr(self, "last_staging_run_dir", None))
        if candidate is None:
            return False

        xml_path = candidate / "annotations.xml"
        if not xml_path.exists():
            return False

        try:
            staging_root = CAMPAIGN.get_staging_dir("auto_ann")
        except Exception:
            staging_root = None

        if staging_root is not None and not self._path_is_within(candidate, staging_root):
            return False

        current_saved_run = str(CAMPAIGN.get_step2_staging_run() or "").strip()
        if current_saved_run and self._paths_equivalent(current_saved_run, candidate) and step2_status == "generated":
            return False

        CAMPAIGN.set_step2_generated(str(candidate))
        return True

    @staticmethod
    def _annotation_run_manifest_has_manual_value(manifest: dict | None) -> bool:
        if not isinstance(manifest, dict):
            return False

        if bool(manifest.get("has_manual_edits", False)):
            return True

        if bool(manifest.get("manual_xml_template", False)):
            return True

        annotation_run_type = str(manifest.get("annotation_run_type") or "").strip().lower()
        return annotation_run_type == "manual_template"

    def _get_active_annotation_run_dir(self, *, require_xml: bool = False) -> Path | None:
        for candidate in (
            getattr(self, "current_annotation_run_dir", None),
            getattr(self, "last_staging_run_dir", None),
        ):
            safe_run_dir = self._resolve_safe_annotation_run_dir(candidate, require_xml=require_xml)
            if safe_run_dir is not None:
                return safe_run_dir
        return None

    def _has_active_manual_template_run(self) -> bool:
        run_dir = self._get_active_annotation_run_dir(require_xml=True)
        if run_dir is None:
            return False

        current_input_dir = str(self.input_dir_var.get() or "").strip()
        if not current_input_dir:
            return False

        try:
            manifest = self._load_annotation_run_manifest(run_dir)
        except Exception:
            manifest = {}

        manifest_input_dir = str(manifest.get("input_dir") or "").strip() if isinstance(manifest, dict) else ""
        if manifest_input_dir and not self._paths_equivalent(manifest_input_dir, current_input_dir):
            return False

        if bool(getattr(self, "_current_run_manual_template", False)):
            return True

        try:
            manifest = self._load_annotation_run_manifest(run_dir)
        except Exception:
            manifest = {}
        return bool(self._annotation_run_manifest_has_manual_value(manifest))

    def _remember_campaign_manual_plate_source(
        self,
        run_dir: Path | None = None,
        xml_path: Path | None = None,
        input_dir: Path | None = None,
    ) -> None:
        try:
            from ..campaign_manager import CAMPAIGN

            if not CAMPAIGN.get_active_project_name():
                return
        except Exception:
            return

        source_run = Path(run_dir) if run_dir is not None else None
        source_xml = Path(xml_path) if xml_path is not None else None
        source_input = Path(input_dir) if input_dir is not None else None

        if source_xml is None and source_run is not None:
            source_xml = source_run / "annotations.xml"
        if source_run is None and source_xml is not None:
            source_run = source_xml.parent
        if source_input is None and getattr(self, "current_input_dir", None) is not None:
            try:
                source_input = Path(self.current_input_dir)
            except Exception:
                source_input = None

        try:
            CAMPAIGN.set_last_plate_manual_source(
                source_run_path=(str(source_run.resolve()) if source_run is not None and source_run.exists() else str(source_run or "")),
                source_xml_path=(str(source_xml.resolve()) if source_xml is not None and source_xml.exists() else str(source_xml or "")),
                source_input_path=(str(source_input.resolve()) if source_input is not None and source_input.exists() else str(source_input or "")),
            )
        except Exception:
            pass

    @staticmethod
    def _plate_dataset_source_manifest_path(dataset_dir: Path) -> Path:
        return Path(dataset_dir) / "dataset_source_manifest.json"

    def _load_plate_dataset_source_manifest(self, dataset_dir: Path) -> dict:
        manifest_path = self._plate_dataset_source_manifest_path(dataset_dir)
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_plate_dataset_source_manifest(
        self,
        dataset_dir: Path,
        *,
        source_kind: str,
        source_run_dir: Path | None = None,
        source_xml_path: Path | None = None,
        source_images_dir: Path | None = None,
    ) -> None:
        try:
            dataset_dir = Path(dataset_dir)
        except Exception:
            return

        if not self._path_is_within(dataset_dir, self._get_plate_dataset_base_dir()):
            return

        payload = {
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "project": "",
            "iteration": 0,
            "dataset_dir": str(dataset_dir.resolve()),
            "source_kind": str(source_kind or "").strip(),
            "source_run_dir": "",
            "source_run_name": "",
            "source_xml_path": "",
            "source_images_dir": "",
        }

        try:
            from ..campaign_manager import CAMPAIGN

            payload["project"] = str(CAMPAIGN.get_active_project_name() or "").strip()
            payload["iteration"] = int(CAMPAIGN.get_current_iteration_num() or 0)
        except Exception:
            pass

        if source_run_dir is not None:
            try:
                source_run_dir = Path(source_run_dir)
                payload["source_run_dir"] = str(source_run_dir.resolve())
                payload["source_run_name"] = source_run_dir.name
            except Exception:
                payload["source_run_dir"] = str(source_run_dir)
                payload["source_run_name"] = str(Path(source_run_dir).name)

        if source_xml_path is not None:
            try:
                payload["source_xml_path"] = str(Path(source_xml_path).resolve())
            except Exception:
                payload["source_xml_path"] = str(source_xml_path)

        if source_images_dir is not None:
            try:
                payload["source_images_dir"] = str(Path(source_images_dir).resolve())
            except Exception:
                payload["source_images_dir"] = str(source_images_dir)

        manifest_path = self._plate_dataset_source_manifest_path(dataset_dir)
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _resolve_plate_source_run_from_dataset(self, dataset_path: Path | None) -> Path | None:
        if dataset_path is None:
            return None

        try:
            dataset_path = Path(dataset_path)
        except Exception:
            return None

        try:
            if not dataset_path.exists() or not dataset_path.is_dir():
                return None
        except Exception:
            return None

        manifest = self._load_plate_dataset_source_manifest(dataset_path)
        for raw_path in (
            str(manifest.get("source_run_dir") or "").strip(),
            str(manifest.get("source_xml_path") or "").strip(),
        ):
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if candidate.suffix.lower() == ".xml":
                candidate = candidate.parent
            if candidate.exists() and candidate.is_dir() and (candidate / "annotations.xml").exists():
                return candidate

        run_name = str(manifest.get("source_run_name") or "").strip()
        if not run_name:
            match = re.match(r"^Plates_Z2_(.+)_\d{8}_\d{6}$", dataset_path.name)
            if match:
                run_name = str(match.group(1) or "").strip()

        if not run_name:
            return None

        search_roots = []
        try:
            from ..campaign_manager import CAMPAIGN

            for root_candidate in (CAMPAIGN.get_dir("auto_ann"), CAMPAIGN.get_staging_dir("auto_ann")):
                if root_candidate is not None:
                    search_roots.append(Path(root_candidate))
        except Exception:
            return None

        candidates = []
        for root in search_roots:
            try:
                if not root.exists() or not root.is_dir():
                    continue
                for candidate in root.rglob(run_name):
                    if (
                        candidate.is_dir()
                        and candidate.name == run_name
                        and (candidate / "annotations.xml").exists()
                    ):
                        candidates.append(candidate)
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    def _find_reused_manual_source_run(self, expected_input_dir: Path | None) -> Path | None:
        def matches_expected_input(run_dir: Path | None) -> bool:
            if run_dir is None:
                return False
            if expected_input_dir is None:
                return True
            try:
                return self._annotation_run_matches_input(run_dir, expected_input_dir)
            except Exception:
                return False

        try:
            from ..campaign_manager import CAMPAIGN

            stored_source = CAMPAIGN.get_last_plate_manual_source()
        except Exception:
            stored_source = {}

        for candidate in (
            str(stored_source.get("source_run_path") or "").strip(),
            str(stored_source.get("source_xml_path") or "").strip(),
        ):
            if not candidate:
                continue
            try:
                run_dir = Path(candidate)
                if run_dir.suffix.lower() == ".xml":
                    run_dir = run_dir.parent
            except Exception:
                continue
            if run_dir.exists() and run_dir.is_dir() and (run_dir / "annotations.xml").exists() and matches_expected_input(run_dir):
                return run_dir

        try:
            from ..campaign_manager import CAMPAIGN

            search_roots = []
            for root_candidate in (CAMPAIGN.get_dir("auto_ann"), CAMPAIGN.get_staging_dir("auto_ann")):
                if root_candidate is not None:
                    search_roots.append(Path(root_candidate))
        except Exception:
            search_roots = []

        candidates = []
        for root in search_roots:
            try:
                if not root.exists() or not root.is_dir():
                    continue
                run_paths = list(root.rglob("run_*"))
            except Exception:
                continue

            for run_dir in run_paths:
                try:
                    if (
                        not run_dir.is_dir()
                        or not (run_dir / "annotations.xml").exists()
                        or not matches_expected_input(run_dir)
                    ):
                        continue
                except Exception:
                    continue

                manifest = self._load_annotation_run_manifest(run_dir)
                if not self._annotation_run_manifest_has_manual_value(manifest):
                    continue

                stamp = str(manifest.get("last_manual_edit_at") or "").strip()
                try:
                    score = datetime.datetime.fromisoformat(stamp).timestamp() if stamp else float(run_dir.stat().st_mtime)
                except Exception:
                    try:
                        score = float(run_dir.stat().st_mtime)
                    except Exception:
                        score = 0.0
                candidates.append((score, run_dir.name, run_dir))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    def _find_reused_training_source_run(self, expected_input_dir: Path | None) -> Path | None:
        def matches_expected_input(run_dir: Path | None) -> bool:
            if run_dir is None:
                return False
            if expected_input_dir is None:
                return True
            try:
                return self._annotation_run_matches_input(run_dir, expected_input_dir)
            except Exception:
                return False

        try:
            from ..campaign_manager import CAMPAIGN

            stored_source = CAMPAIGN.get_last_plate_training_source()
        except Exception:
            stored_source = {}

        stored_run = self._resolve_existing_run_dir(stored_source.get("source_run_path"))
        if matches_expected_input(stored_run):
            return stored_run

        stored_dataset = str(stored_source.get("dataset_path") or "").strip()
        if stored_dataset:
            dataset_run = self._resolve_plate_source_run_from_dataset(Path(stored_dataset))
            if matches_expected_input(dataset_run):
                return dataset_run

        try:
            from ..campaign_manager import CAMPAIGN
            from ..training import TrainingHistory

            runs_root = CAMPAIGN.get_dir("runs")
            if runs_root is None:
                return None

            history = TrainingHistory(history_dir=Path(runs_root) / "plates")
            for run in history.get_all_runs():
                dataset_value = str(getattr(run, "dataset_path", "") or "").strip()
                if not dataset_value:
                    continue
                dataset_run = self._resolve_plate_source_run_from_dataset(Path(dataset_value))
                if matches_expected_input(dataset_run):
                    return dataset_run
        except Exception as e:
            logger.debug(f"Nie udalo sie odczytac historii treningow tablic: {e}")

        return None

    def _find_latest_annotation_run_dir(self, base_dir: Path | None = None) -> Path | None:
        roots = []
        if base_dir is not None:
            try:
                candidate_root = Path(base_dir)
            except Exception:
                candidate_root = None
            if candidate_root is not None and self._path_is_within_any(candidate_root, self._get_annotation_run_roots()):
                roots.append(candidate_root)
        else:
            roots.extend(self._get_annotation_run_roots())

        roots = self._dedupe_paths(roots)
        if not roots:
            return None

        candidates = []
        for root in roots:
            try:
                if not root.exists() or not root.is_dir():
                    continue
            except Exception:
                continue

            try:
                for path in root.rglob("run_*"):
                    if not path.is_dir():
                        continue
                    if not (path / "annotations.xml").exists():
                        continue
                    try:
                        stamp = path.stat().st_mtime
                    except Exception:
                        stamp = 0
                    candidates.append((stamp, path.name, path))
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    def _annotation_run_matches_input(self, run_dir: Path, input_dir: Path | None) -> bool:
        if input_dir is None:
            return True

        manifest = self._load_annotation_run_manifest(run_dir)
        manifest_input = str(manifest.get("input_dir") or "").strip()
        if not manifest_input:
            return False

        try:
            return Path(manifest_input).resolve() == Path(input_dir).resolve()
        except Exception:
            return str(Path(manifest_input)) == str(Path(input_dir))

    def _find_latest_annotation_run_for_input(
        self,
        input_dir: Path | None,
        search_roots: list[Path] | None = None,
    ) -> Path | None:
        if input_dir is None:
            return None

        candidates = []
        roots = list(search_roots or [])
        allowed_roots = self._get_annotation_run_roots()

        for root in roots:
            try:
                root = Path(root)
            except Exception:
                continue

            if not self._path_is_within_any(root, allowed_roots):
                continue

            try:
                if not root.exists() or not root.is_dir():
                    continue
            except Exception:
                continue

            try:
                run_paths = list(root.rglob("run_*"))
            except Exception:
                continue

            for path in run_paths:
                try:
                    if not path.is_dir() or not (path / "annotations.xml").exists():
                        continue
                    if not self._annotation_run_matches_input(path, input_dir):
                        continue
                    stamp = path.stat().st_mtime
                except Exception:
                    continue
                candidates.append((stamp, path.name, path))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    def _get_plate_dataset_base_dir(self) -> Path:
        if not self._is_free_mode_session_context():
            try:
                from ..campaign_manager import CAMPAIGN

                if CAMPAIGN.get_active_project_name():
                    datasets_dir = CAMPAIGN.get_dir("datasets")
                    if datasets_dir is not None:
                        return Path(datasets_dir)
            except Exception:
                pass

        return Path(CONFIG.get_datasets_dir("plate"))

    def _get_manual_plate_stage_dir(self) -> Path:
        if not self._is_free_mode_session_context():
            try:
                from ..campaign_manager import CAMPAIGN

                if CAMPAIGN.get_active_project_name():
                    base_dir = CAMPAIGN.get_staging_dir("plate_stage")
                    if base_dir is not None:
                        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
                        return Path(base_dir) / f"Iteracja_{iter_num:03d}"
            except Exception:
                pass

        return Path(CONFIG.get_auto_annotations_dir("plate")) / "_manual_stage"

    def _get_manual_plate_stage_images_dir(self) -> Path:
        return self._get_manual_plate_stage_dir() / "images"

    def _build_campaign_auto_annotation_merge_dir(self, base_input_dir: Path) -> Path:
        from ..campaign_manager import CAMPAIGN

        source_plan = self._collect_campaign_auto_annotation_sources(
            Path(base_input_dir),
            include_previous=True,
        )
        previous_manual_dir = source_plan.get("previous_manual_dir")
        if previous_manual_dir is None:
            return base_input_dir
        if not bool(self.campaign_reuse_manual_var.get()):
            return base_input_dir

        merge_root = CAMPAIGN.get_staging_dir("auto_ann")
        if merge_root is None:
            return base_input_dir

        merge_root = Path(merge_root)
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        merge_dir = merge_root / "_campaign_input_merge" / f"Iteracja_{iter_num:03d}"

        try:
            if merge_dir.exists() and self._path_is_within(merge_dir, merge_root):
                shutil.rmtree(merge_dir)
        except Exception as e:
            logger.debug(f"Nie udało się wyczyścić katalogu merge wejścia Z2: {e}")

        merge_dir.mkdir(parents=True, exist_ok=True)
        copied_names: set[str] = set()

        for image_path in source_plan.get("image_paths", []) or []:
            target_path = merge_dir / image_path.name
            if image_path.name in copied_names:
                continue
            try:
                shutil.copy2(image_path, target_path)
                copied_names.add(image_path.name)
            except Exception as e:
                logger.debug(f"Nie udało się dołączyć obrazu do merge wejścia Z2 ({image_path}): {e}")

        self._apply_campaign_manual_reuse_context(source_plan)

        return merge_dir if copied_names else base_input_dir

    def _is_manual_plate_stage_input(self, path_like) -> bool:
        if not path_like:
            return False
        try:
            return Path(path_like).resolve() == self._get_manual_plate_stage_images_dir().resolve()
        except Exception:
            return str(Path(path_like)) == str(self._get_manual_plate_stage_images_dir())

    def _load_manual_plate_stage_manifest(self) -> dict:
        manifest_path = self._get_manual_plate_stage_dir() / "stage_manifest.json"
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _refresh_manual_plate_stage_ui(self):
        section = getattr(self, "manual_stage_section", None)
        if section is None:
            return

        manual_enabled = self._manual_xml_template_enabled()
        separator = getattr(self, "manual_stage_separator", None)
        if not self._is_free_mode_session_context():
            if manual_enabled:
                if separator is not None and not str(separator.winfo_manager()):
                    separator.pack(fill=tk.X, pady=(18, 20))
                if not str(section.winfo_manager()):
                    pack_kwargs = {"fill": tk.X}
                    if separator is not None:
                        pack_kwargs["before"] = separator
                    section.pack(**pack_kwargs)
            else:
                if separator is not None and str(separator.winfo_manager()):
                    separator.pack_forget()
                if str(section.winfo_manager()):
                    section.pack_forget()
                return

        stage_dir = self._get_manual_plate_stage_dir()
        stage_images_dir = stage_dir / "images"
        manifest = self._load_manual_plate_stage_manifest()
        stage_images = get_image_files(stage_images_dir)
        stage_count = len(stage_images)
        current_is_stage = self._is_manual_plate_stage_input(self.input_dir_var.get())

        self.manual_stage_dir_var.set(str(stage_images_dir))

        updated_at = str(manifest.get("updated_at") or "").strip()
        updated_suffix = f" Ostatnia synchronizacja: {updated_at}." if updated_at else ""

        if current_is_stage and stage_count == 0:
            status_text = (
                "Stage jest aktualnym wejsciem Z2, ale nie ma w nim jeszcze zadnych zdjec. "
                "Dodaj nowe obrazy do stage albo wroc do glownej paczki." + updated_suffix
            )
            tone = "warning"
        elif stage_count > 0:
            stage_rel = self._format_workspace_relative_path(stage_images_dir)
            status_text = (
                f"Stage zawiera {stage_count} zdjec oczekujacych na kolejna runde recznej anotacji. "
                f"Możesz przełączyć Z2 na {stage_rel} albo dołożyć nową paczkę zdjęć." + updated_suffix
            )
            tone = "success"
        else:
            status_text = (
                "Stage jest pusty. Po eksporcie datasetu trafia tutaj tylko nieoznaczona czesc obrazow. "
                "Mozesz tez dolozyc nowe zdjecia do kolejnej iteracji." + updated_suffix
            )
            tone = "muted"

        self._set_inline_label_state(
            self.manual_stage_status_lbl,
            text=status_text,
            tone=tone,
            emphasis=False,
        )

        if current_is_stage:
            self.manual_stage_use_btn.configure(text="Stage jest aktywnym wejsciem Z2", state=tk.DISABLED)
        elif stage_count > 0:
            self.manual_stage_use_btn.configure(text="Uzyj stage jako wejscia Z2", state=tk.NORMAL)
        else:
            self.manual_stage_use_btn.configure(text="Uzyj stage jako wejscia Z2", state=tk.DISABLED)

        self.manual_stage_add_btn.configure(state=tk.NORMAL)

    def _refresh_manual_review_followup_ui(self, *, from_auto: bool, active_run: bool):
        title_label = getattr(self, "manual_stage_title_lbl", None)
        help_label = getattr(self, "manual_stage_help_lbl", None)
        path_title = getattr(self, "manual_stage_path_title_lbl", None)
        path_row = getattr(self, "manual_stage_path_row", None)
        status_label = getattr(self, "manual_stage_status_lbl", None)
        buttons_row = getattr(self, "manual_stage_buttons_row", None)
        campaign_context = not self._is_free_mode_session_context()
        compact_followup = bool(active_run or from_auto or campaign_context)

        if compact_followup:
            current_run_dir = self._get_preferred_annotation_run_dir(require_xml=True)
            current_run_name = (
                str(getattr(current_run_dir, "name", "") or "").strip()
                if current_run_dir is not None
                else ""
            )
            current_input_dir = str(self.input_dir_var.get() or "").strip()
            try:
                title_label.configure(
                    text=(
                        "Aktywny run recznej korekty"
                        if (campaign_context or active_run)
                        else "Korekta reczna zakonczona?"
                    )
                )
            except Exception:
                pass
            self._set_inline_label_state(
                help_label,
                text=(
                    (
                        "To jest biezacy run Z2 tej iteracji. Po prawej poprawiasz polygony aktualnego runu, "
                        "a po zakonczeniu zmian domykasz E2. Stage kolejnej iteracji nie jest aktywnym krokiem "
                        "na tym ekranie."
                    )
                    if campaign_context
                    else "Po prawej poprawiasz polygony biezacego runu Z2. "
                    "Wstecz wraca do wejscia do korekty, a do eksportu datasetu przejdziesz przyciskiem Eksport w mini-flow."
                ),
                tone="muted",
                emphasis=False,
            )
            self._set_widget_packed(help_label, True, anchor=tk.W, fill=tk.X, pady=(0, 6))
            self._set_widget_packed(path_title, False)
            self._set_widget_packed(path_row, False)
            run_chunks = []
            if current_run_name:
                run_chunks.append(f"Run: {current_run_name}")
            if current_input_dir:
                run_chunks.append(
                    f"Obrazy: {self._format_workspace_relative_path(current_input_dir)}"
                )
            if campaign_context or run_chunks:
                self._set_inline_label_state(
                    status_label,
                    text=(" | ".join(run_chunks) if run_chunks else "Trwa korekta biezacego runu Z2."),
                    tone=("success" if campaign_context else "muted"),
                    emphasis=False,
                )
                self._set_widget_packed(status_label, True, anchor=tk.W, fill=tk.X, pady=(0, 8))
            else:
                self._set_widget_packed(status_label, False)
            self._set_widget_packed(buttons_row, False)
            try:
                if str(self.manual_stage_use_btn.winfo_manager()) == "grid":
                    self.manual_stage_use_btn.grid_remove()
            except Exception:
                pass
            try:
                if str(self.manual_stage_add_btn.winfo_manager()) == "grid":
                    self.manual_stage_add_btn.grid_remove()
            except Exception:
                pass
            return

        try:
            title_label.configure(text="Stage kolejnej iteracji")
        except Exception:
            pass
        self._set_inline_label_state(
            help_label,
            text=(
                "Stage to pomocnicza pula zdjec do kolejnej iteracji recznej. "
                "Po eksporcie moga trafiac tu nieoznaczone obrazy, a recznie mozesz tez "
                "dolozyc nowa paczke bez mieszania z gotowym runem."
            ),
            tone="muted",
            emphasis=False,
        )
        self._set_widget_packed(help_label, True, anchor=tk.W, fill=tk.X, pady=(0, 6))
        self._set_widget_packed(path_title, True, anchor=tk.W, fill=tk.X)
        self._set_widget_packed(path_row, True, fill=tk.X, pady=(2, 8))
        self._set_widget_packed(status_label, True, anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_widget_packed(buttons_row, True, fill=tk.X, pady=(0, 2))
        try:
            if str(self.manual_stage_use_btn.winfo_manager()) != "grid":
                self.manual_stage_use_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        except Exception:
            pass
        try:
            if str(self.manual_stage_add_btn.winfo_manager()) != "grid":
                self.manual_stage_add_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        except Exception:
            pass

    def _refresh_preview_workspace_visibility(self, *, manual_review_active: bool | None = None):
        if manual_review_active is None:
            has_existing_run = self._get_preferred_annotation_run_dir(require_xml=True) is not None
            manual_review_active = bool(self._manual_review_active and has_existing_run)

        show_preview = bool(
            not self._is_free_mode_session_context()
            or (manual_review_active and not self._manual_review_export_ready)
        )

        if not show_preview and bool(getattr(self, "_preview_fullscreen_active", False)):
            try:
                self._set_preview_fullscreen(False)
            except Exception:
                pass

        self._set_widget_packed(
            getattr(self, "preview_host", None),
            show_preview,
            fill=tk.BOTH,
            expand=True,
            padx=5,
            pady=0,
        )
        self._set_widget_packed(
            getattr(self, "preview_left_list_shell", None),
            show_preview,
            fill=tk.BOTH,
            pady=(8, 0),
        )

        show_log_tools = False
        self._set_widget_packed(
            getattr(self, "log_tools", None),
            show_log_tools,
            fill=tk.X,
            padx=5,
            pady=(8, 0),
        )

        if not show_log_tools and getattr(self, "_annotation_log_visible", False):
            self._set_annotation_process_log_visibility(False)

    def _refresh_export_followup_ui(self, *, compact_active_run: bool):
        title_label = getattr(self, "export_title_lbl", None)
        intro_label = getattr(self, "export_intro_lbl", None)
        run_row = getattr(getattr(self, "plate_dataset_run_title_lbl", None), "master", None)
        images_row = getattr(getattr(self, "plate_dataset_images_title_lbl", None), "master", None)
        output_row = getattr(getattr(self, "plate_dataset_out_title_lbl", None), "master", None)
        back_btn = getattr(self, "export_back_btn", None)
        campaign_context = not self._is_free_mode_session_context()
        focused_export = bool(campaign_context and self._manual_review_export_ready)
        manual_review_active = bool(
            getattr(self, "_manual_review_active", False)
            and self._get_preferred_annotation_run_dir(require_xml=True) is not None
        )

        try:
            if back_btn is not None:
                back_btn.configure(
                    text=(
                        "Wroc do korekty"
                        if (not campaign_context and manual_review_active)
                        else "Wroc do podsumowania wynikow autoanotacji"
                        if not campaign_context
                        else "Wroc do stage"
                    )
                )
        except Exception:
            pass

        if compact_active_run:
            try:
                title_label.configure(text="4. Ustaw split i wyeksportuj dataset")
            except Exception:
                pass
            self._set_widget_packed(intro_label, False)
            self._set_widget_packed(run_row, False)
            self._set_widget_packed(images_row, False)
            self._set_widget_packed(output_row, False)
            return

        try:
            title_label.configure(
                text=(
                    "4. Dataset do Z4"
                    if focused_export
                    else "4. Opcjonalny eksport datasetu do Z4"
                    if campaign_context
                    else "4. Split i eksport datasetu z gotowego runu"
                )
            )
        except Exception:
            pass
        if focused_export:
            self.export_intro_var.set(
                "Opcjonalnie przygotuj dataset tablic z gotowego runu Z2, aby przekazac go do treningu w Z4."
            )
        self._set_widget_packed(intro_label, True, anchor=tk.W, fill=tk.X, pady=(0, 8))
        self._set_widget_packed(run_row, True, fill=tk.X, pady=(0, 4))
        self._set_widget_packed(images_row, True, fill=tk.X, pady=(0, 4))
        self._set_widget_packed(output_row, True, fill=tk.X, pady=(0, 8))

    def _switch_annotation_input_dir(self, input_dir: Path, *, show_hint: bool = True) -> bool:
        input_dir = Path(input_dir)
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("Brak obrazow", "Wybrany folder obrazow nie istnieje.")
            return False

        if not self._ensure_preview_edits_saved("zmiana puli obrazow Z2"):
            return False

        self.input_dir_var.set(str(input_dir))
        self.plate_dataset_images_var.set(str(input_dir))
        self.plate_dataset_run_var.set("")
        self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
        self._reset_campaign_runtime_state(input_dir)
        self.current_input_dir = input_dir

        if not self._is_free_mode_session_context():
            self._set_campaign_paths_lock_state(True)

        self._refresh_plate_dataset_export_sources()
        self._refresh_manual_plate_stage_ui()

        if show_hint:
            if self._is_manual_plate_stage_input(input_dir):
                self._set_post_annotation_hint(
                    f"Stage został ustawiony jako nowa pula obrazów Z2. Kliknij {self._get_step2_start_action_reference()}, aby utworzyć kolejny run anotacji Z2 dla tych zdjęć.",
                    "success",
                )
            else:
                self._set_post_annotation_hint("")

        self._queue_free_mode_session_save()
        return True

    def _use_manual_plate_stage_as_input(self):
        stage_images_dir = self._get_manual_plate_stage_images_dir()
        stage_images = get_image_files(stage_images_dir)
        if not stage_images:
            messagebox.showinfo(
                "Stage jest puste",
                "Stage nie zawiera jeszcze zadnych zdjec. Najpierw wyeksportuj dataset lub dodaj nowa paczke zdjec do stage."
            )
            return

        if self._switch_annotation_input_dir(stage_images_dir):
            self._set_plate_export_status(
                f"Dla aktualnego stage nie ma jeszcze runu anotacji Z2. Kliknij {self._get_step2_start_action_reference()}, aby utworzyć nowy run anotacji dla tej puli obrazów.",
                "success",
            )

    def _add_images_to_manual_plate_stage(self):
        stage_dir = self._get_manual_plate_stage_dir()
        stage_images_dir = stage_dir / "images"
        initialdir = self.input_dir_var.get().strip() or str(CONFIG.DIR_1_RAW)
        path = filedialog.askdirectory(initialdir=initialdir)
        if not path:
            return

        source_dir = Path(path)
        ok, msg, stats = self.dataset_creator.add_images_to_stage(source_dir, stage_dir)
        self._refresh_manual_plate_stage_ui()

        if not ok:
            messagebox.showerror("Blad stage", msg)
            return

        stage_total = int(stats.get("stage_images_total", 0) or 0)
        added = int(stats.get("added", 0) or 0)
        updated = int(stats.get("updated", 0) or 0)
        messagebox.showinfo(
            "Stage zaktualizowane",
            (
                f"Stage zawiera teraz {stage_total} obrazow.\n"
                f"{stage_images_dir}\n\n"
                f"Dodane nowe pliki: {added}\n"
                f"Odswiezone istniejace wpisy: {updated}"
            )
        )

        if self._is_manual_plate_stage_input(self.input_dir_var.get()):
            self._set_post_annotation_hint(
                f"Dołożono nowe zdjęcia do aktywnego stage. Kliknij {self._get_step2_start_action_reference()}, aby utworzyć kolejny run anotacji Z2 dla tej rozszerzonej puli.",
                "success",
            )

    def _plate_dataset_output_preview(self, run_dir: Path | None = None) -> str:
        run_name = run_dir.name if isinstance(run_dir, Path) else "run_xxx"
        return str(self._get_plate_dataset_base_dir() / f"Plates_Z2_{run_name}_[DATA_I_CZAS]")

    def _clear_active_annotation_run_context(self, *, preserve_input_dir: bool = True):
        input_dir_value = str(self.input_dir_var.get() or "").strip() if preserve_input_dir else ""
        try:
            preserved_input_dir = Path(input_dir_value) if input_dir_value else None
        except Exception:
            preserved_input_dir = None

        self.current_annotations = []
        self._clear_preview_editor_state(clear_dirty=True)
        self.last_staging_run_dir = None
        self._current_run_manual_template = False
        self._current_run_manual_vehicle_assist = False
        self._manual_review_active = False
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        self._preview_session_restore_index = -1
        self._preview_session_restore_filename = ""
        self.current_input_dir = preserved_input_dir

        try:
            self.plate_dataset_run_var.set("")
        except Exception:
            pass

        try:
            self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
        except Exception:
            pass

    def _set_plate_export_status(self, text: str, tone: str = "muted"):
        self._set_inline_label_state(
            self.plate_export_status_lbl,
            text=text,
            tone=tone,
            emphasis=False
        )

    def _set_post_annotation_hint(self, text: str = "", tone: str = "muted"):
        label = getattr(self, "post_annotation_hint_lbl", None)
        if label is None:
            return

        has_text = bool(str(text or "").strip())
        try:
            if has_text:
                if not str(label.winfo_manager()):
                    label.pack(fill=tk.X, pady=(6, 0))
            else:
                if str(label.winfo_manager()):
                    label.pack_forget()
        except Exception:
            pass

        self._set_inline_label_state(
            label,
            text=str(text or ""),
            tone=tone,
            emphasis=False
        )

    @staticmethod
    def _resolve_existing_run_dir(path_value) -> Path | None:
        candidate = AnnotationTab._path_value_to_path(path_value)
        if candidate is None:
            return None

        try:
            if candidate.exists() and candidate.is_dir():
                return candidate
        except Exception:
            return None
        return None

    @staticmethod
    def _resolve_existing_dir(path_value) -> Path | None:
        candidate = AnnotationTab._path_value_to_path(path_value)
        if candidate is None:
            return None

        try:
            if candidate.exists() and candidate.is_dir():
                return candidate
        except Exception:
            return None
        return None

    def _allocate_annotation_run_dir(self, base_out_dir: Path, *, suffix: str = "") -> Path:
        base_out_dir = self._coerce_annotation_output_dir(base_out_dir)
        base_out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix_text = f"_{suffix}" if str(suffix or "").strip() else ""
        counter = 1
        while True:
            run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}{suffix_text}"
            if not run_dir.exists():
                run_dir.mkdir(parents=True, exist_ok=False)
                return run_dir
            counter += 1

    def _get_manual_review_import_initial_dir(self) -> str:
        try:
            base_dir = self._resolve_existing_dir(self._get_annotation_output_base_dir())
        except Exception:
            base_dir = None
        if base_dir is not None:
            return str(base_dir)

        candidates = [
            self._get_selected_manual_review_history_run_dir(),
            getattr(self, "current_annotation_run_dir", None),
            getattr(self, "last_staging_run_dir", None),
            str(self.input_dir_var.get() or "").strip(),
            Path.cwd(),
        ]

        for candidate in candidates:
            existing_run = self._resolve_existing_run_dir(candidate)
            if existing_run is not None:
                parent_dir = self._resolve_existing_dir(existing_run.parent)
                if parent_dir is not None:
                    return str(parent_dir)

            existing_dir = self._resolve_existing_dir(candidate)
            if existing_dir is not None:
                return str(existing_dir)

        try:
            return str(Path.home())
        except Exception:
            return str(Path.cwd())

    @staticmethod
    def _build_safe_imported_image_relative_path(
        path_value,
        *,
        index: int,
        used_paths: set[str],
    ) -> Path:
        try:
            raw_path = Path(str(path_value or "").strip())
        except Exception:
            raw_path = Path("")

        clean_parts: list[str] = []
        anchor = str(getattr(raw_path, "anchor", "") or "").strip()
        for part in getattr(raw_path, "parts", ()):
            normalized = str(part or "").strip()
            if not normalized or normalized in {".", "..", "/", "\\"}:
                continue
            if anchor and normalized == anchor:
                continue
            normalized = normalized.replace(":", "")
            if not normalized:
                continue
            clean_parts.append(normalized)

        if not clean_parts:
            clean_parts = [f"image_{int(index) + 1:05d}.jpg"]

        candidate = Path(*clean_parts)
        if candidate.is_absolute():
            candidate = Path(candidate.name or f"image_{int(index) + 1:05d}.jpg")

        key = str(candidate).lower()
        if key in used_paths:
            stem = candidate.stem or f"image_{int(index) + 1:05d}"
            suffix = candidate.suffix
            duplicate_counter = 1
            while True:
                deduped = candidate.with_name(f"{stem}_{duplicate_counter:02d}{suffix}")
                key = str(deduped).lower()
                if key not in used_paths:
                    candidate = deduped
                    break
                duplicate_counter += 1

        used_paths.add(str(candidate).lower())
        return candidate

    def _get_external_run_image_roots(
        self,
        source_run_dir: Path,
        source_manifest: dict | None = None,
        compatible_images_dir: Path | str | None = None,
    ) -> list[Path]:
        manifest = source_manifest if isinstance(source_manifest, dict) else {}
        candidates = [
            compatible_images_dir,
            str(manifest.get("input_dir") or "").strip(),
            source_run_dir / "images",
            source_run_dir,
        ]
        return self._dedupe_paths(candidates)

    def _get_external_run_images_initial_dir(self, source_run_dir: Path, source_manifest: dict | None = None) -> str:
        for candidate in self._get_external_run_image_roots(source_run_dir, source_manifest):
            try:
                if candidate.exists() and candidate.is_dir():
                    return str(candidate)
            except Exception:
                continue

        try:
            return str(source_run_dir.parent if source_run_dir.parent.exists() else source_run_dir)
        except Exception:
            return self._get_manual_review_import_initial_dir()

    def _get_external_run_expected_image_count(self, source_run_dir: Path | str | None) -> int:
        source_run_dir = self._resolve_existing_run_dir(source_run_dir)
        if source_run_dir is None:
            return 0

        source_xml_path = source_run_dir / "annotations.xml"
        if not source_xml_path.exists():
            return 0

        try:
            return len(self._parse_cvat_preview_annotations(source_xml_path))
        except Exception:
            return 0

    def _resolve_external_run_source_images(
        self,
        annotations: list[ImageAnnotation],
        image_roots: list[Path],
    ) -> tuple[list[tuple[str, Path, Path]], list[str]]:
        resolved_images: list[tuple[str, Path, Path]] = []
        missing_images: list[str] = []
        basename_index: dict[str, Path | None] = {}

        for idx, ann in enumerate(annotations):
            filename = str(getattr(ann, "filename", "") or "").strip()
            if not filename:
                missing_images.append("<brak_nazwy>")
                continue

            raw_path = Path(filename)
            source_image_path = None
            try:
                if raw_path.is_absolute() and raw_path.exists() and raw_path.is_file():
                    source_image_path = raw_path
            except Exception:
                source_image_path = None

            if source_image_path is None:
                for image_root in image_roots:
                    candidate_path = image_root / raw_path
                    try:
                        if candidate_path.exists() and candidate_path.is_file():
                            source_image_path = candidate_path
                            break
                    except Exception:
                        continue

            if source_image_path is None:
                basename = raw_path.name.lower()
                indexed_candidate = basename_index.get(basename, "__missing__")
                if indexed_candidate == "__missing__":
                    matches: list[Path] = []
                    for image_root in image_roots:
                        try:
                            if not image_root.exists() or not image_root.is_dir():
                                continue
                        except Exception:
                            continue
                        try:
                            matches.extend(path for path in image_root.rglob(raw_path.name) if path.is_file())
                        except Exception:
                            continue
                        if len(matches) > 1:
                            break

                    if len(matches) == 1:
                        basename_index[basename] = matches[0]
                    else:
                        basename_index[basename] = None

                    indexed_candidate = basename_index.get(basename)

                if indexed_candidate not in {None, "__missing__"}:
                    source_image_path = indexed_candidate

            if source_image_path is None:
                missing_images.append(filename)
                continue

            resolved_images.append((filename, raw_path, source_image_path))

        return resolved_images, missing_images

    def _import_external_annotation_run_to_workspace(
        self,
        source_run_dir: Path | str | None,
        *,
        compatible_images_dir: Path | str | None = None,
    ) -> tuple[Path | None, str, bool]:
        source_run_dir = self._resolve_existing_run_dir(source_run_dir)
        if source_run_dir is None:
            return None, "Nie znaleziono wskazanego katalogu runu.", False

        source_xml_path = source_run_dir / "annotations.xml"
        if not source_xml_path.exists():
            return None, "Wybrany katalog nie zawiera pliku annotations.xml.", False

        try:
            annotations = self._parse_cvat_preview_annotations(source_xml_path)
        except Exception as e:
            return None, f"Nie udalo sie odczytac annotations.xml:\n{e}", False

        if not annotations:
            return None, "Wybrany run nie zawiera obrazow do recznej korekty.", False

        source_manifest = self._load_annotation_run_manifest(source_run_dir)
        image_roots = self._get_external_run_image_roots(
            source_run_dir,
            source_manifest,
            compatible_images_dir=compatible_images_dir,
        )

        resolved_images, missing_images = self._resolve_external_run_source_images(
            annotations,
            image_roots,
        )
        relative_name_map: dict[str, str] = {}
        used_import_paths: set[str] = set()
        for idx, (filename, _raw_path, source_image_path) in enumerate(resolved_images):
            relative_path = self._build_safe_imported_image_relative_path(
                filename,
                index=idx,
                used_paths=used_import_paths,
            )
            relative_name_map[filename] = str(relative_path).replace("\\", "/")
            resolved_images[idx] = (filename, relative_path, source_image_path)

        if missing_images:
            preview_missing = "\n".join(missing_images[:5])
            extra_missing = len(missing_images) - min(len(missing_images), 5)
            suffix = f"\n... i jeszcze {extra_missing} plikow." if extra_missing > 0 else ""
            return (
                None,
                "Nie mozna bezpiecznie zaimportowac tego runu, bo brakuje obrazow "
                f"wzgledem annotations.xml.\n\nBrakujace pliki:\n{preview_missing}{suffix}",
                True,
            )

        imported_run_dir = None
        try:
            imported_run_dir = self._allocate_annotation_run_dir(
                self._get_annotation_output_base_dir(),
                suffix="import",
            )
            imported_images_dir = imported_run_dir / "images"
            imported_images_dir.mkdir(parents=True, exist_ok=True)

            for _original_name, relative_path, source_image_path in resolved_images:
                target_image_path = imported_images_dir / relative_path
                target_image_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_image_path, target_image_path)

            imported_xml_path = imported_run_dir / "annotations.xml"
            xml_tree = ET.parse(source_xml_path)
            xml_root = xml_tree.getroot()
            for image_el in xml_root.findall(".//image"):
                original_name = str(image_el.get("name", "") or "").strip()
                if original_name in relative_name_map:
                    image_el.set("name", relative_name_map[original_name])
            xml_tree.write(imported_xml_path, encoding="utf-8", xml_declaration=True)

            source_report_path = source_run_dir / "report.txt"
            if source_report_path.exists():
                shutil.copy2(source_report_path, imported_run_dir / "report.txt")

            now_iso = datetime.datetime.now().isoformat(timespec="seconds")
            successful_images = sum(1 for ann in annotations if bool(getattr(ann, "is_successful", False)))
            _images_with_plates, total_plates = self._count_plate_annotations(annotations)
            imported_manifest = {
                "input_dir": str(imported_images_dir.resolve()),
                "run_dir": str(imported_run_dir.resolve()),
                "mode": str(source_manifest.get("mode") or self.mode_var.get() or "").strip(),
                "device": str(source_manifest.get("device") or self._get_effective_yolo_device_choice() or "").strip(),
                "annotation_run_type": str(source_manifest.get("annotation_run_type") or "imported_run").strip() or "imported_run",
                "manual_xml_template": bool(source_manifest.get("manual_xml_template", False)),
                "manual_vehicle_assist": bool(source_manifest.get("manual_vehicle_assist", False)),
                "has_manual_edits": bool(source_manifest.get("has_manual_edits", False)),
                "last_manual_edit_at": str(source_manifest.get("last_manual_edit_at") or "").strip(),
                "last_manual_edit_kind": str(source_manifest.get("last_manual_edit_kind") or "import").strip(),
                "run_status": "completed",
                "completed_at": str(source_manifest.get("completed_at") or source_manifest.get("generated_at") or now_iso).strip(),
                "last_error": "",
                "result_total_images": len(annotations),
                "result_successful_images": successful_images,
                "result_total_plates": total_plates,
                "resume_preview_index": -1,
                "resume_preview_filename": "",
                "resume_preview_saved_at": "",
                "generated_at": str(source_manifest.get("generated_at") or now_iso).strip(),
                "imported_at": now_iso,
                "imported_from_run_dir": str(source_run_dir.resolve()),
                "imported_source_input_dir": (
                    str(Path(compatible_images_dir).resolve())
                    if compatible_images_dir
                    else str(source_manifest.get("input_dir") or "").strip()
                ),
            }
            self._annotation_run_manifest_path(imported_run_dir).write_text(
                json.dumps(imported_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return imported_run_dir, "", False
        except Exception as e:
            if imported_run_dir is not None:
                try:
                    shutil.rmtree(imported_run_dir)
                except Exception:
                    pass
            return None, f"Nie udalo sie zaimportowac runu do workspace:\n{e}", False

    def _import_or_open_manual_review_run_from_dialog(self):
        initialdir = self._get_manual_review_import_initial_dir()
        path = filedialog.askdirectory(initialdir=initialdir)
        if not path:
            return

        selected_run_dir = self._resolve_existing_run_dir(path)
        if selected_run_dir is None or not (selected_run_dir / "annotations.xml").exists():
            messagebox.showerror(
                "Nieprawidlowy run anotacji",
                "Wskaz run autoanotacji Z2 zawierajacy plik annotations.xml i zgodne obrazy.\n\n"
                f"{self._get_annotation_run_definition_text()}\n\n"
                f"Domyslny katalog runow anotacji Z2: {self._get_annotation_run_storage_display_path()}",
            )
            return

        safe_run_dir = self._resolve_safe_annotation_run_dir(selected_run_dir, require_xml=True)
        if safe_run_dir is not None:
            self._open_existing_run_for_manual_review(
                run_dir=safe_run_dir,
                allow_fallback=False,
                show_dialog=True,
            )
            return

        imported_run_dir, error_message, needs_image_dir = self._import_external_annotation_run_to_workspace(selected_run_dir)
        compatible_images_dir = None
        if imported_run_dir is None and needs_image_dir:
            source_manifest = self._load_annotation_run_manifest(selected_run_dir)
            expected_image_count = self._get_external_run_expected_image_count(selected_run_dir)
            expected_count_hint = ""
            if expected_image_count > 0:
                expected_count_hint = (
                    f"\n\nProgram oczekuje katalogu z okolo {expected_image_count} zgodnymi obrazami "
                    "wynikajacymi z annotations.xml."
                )
            messagebox.showinfo(
                "Wskaz folder obrazow",
                "Wybrano zewnetrzny run autoanotacji Z2, ale nie ma on kompletu zgodnych obrazow "
                "w standardowych lokalizacjach.\n\n"
                f"{self._get_annotation_run_definition_text()}\n\n"
                "Wskaz folder z kompatybilnymi zdjeciami. Program sprawdzi zgodnosc z annotations.xml "
                f"i skopiuje poprawny zestaw do lokalnego runu w workspace Z2.{expected_count_hint}\n\n"
                f"Domyslny katalog runow anotacji Z2: {self._get_annotation_run_storage_display_path()}",
            )
            compatible_images_dir = filedialog.askdirectory(
                initialdir=self._get_external_run_images_initial_dir(selected_run_dir, source_manifest)
            )
            if not compatible_images_dir:
                return
            imported_run_dir, error_message, _needs_image_dir = self._import_external_annotation_run_to_workspace(
                selected_run_dir,
                compatible_images_dir=compatible_images_dir,
            )
        if imported_run_dir is None:
            messagebox.showerror(
                "Blad importu runu anotacji",
                error_message or "Nie udalo sie zaimportowac wskazanego runu anotacji do workspace Z2.",
            )
            return

        if not self._open_existing_run_for_manual_review(
            run_dir=imported_run_dir,
            allow_fallback=False,
            show_dialog=False,
        ):
            return

        messagebox.showinfo(
            "Run anotacji zaimportowany",
            (
                "Zaimportowano run autoanotacji Z2 do workspace i otwarto go do recznej korekty.\n\n"
                f"{self._get_annotation_run_definition_text()}\n\n"
                f"Run zrodlowy autoanotacji: {selected_run_dir}\n"
                + (
                    f"Folder zgodnych obrazow: {compatible_images_dir}\n"
                    if compatible_images_dir
                    else ""
                )
                + f"Lokalna kopia runu: {imported_run_dir}\n"
                + f"Domyslny katalog runow anotacji Z2: {self._get_annotation_run_storage_display_path()}"
            ),
        )

    def _count_plate_annotations(self, annotations: list[ImageAnnotation] | None = None) -> tuple[int, int]:
        images_with_plates = 0
        total_plates = 0

        for ann in list(annotations if annotations is not None else (self.current_annotations or [])):
            plate_count = len(self._get_plate_detections(ann))
            if plate_count > 0:
                images_with_plates += 1
                total_plates += plate_count

        return images_with_plates, total_plates

    def _build_auto_followup_summary(self) -> str:
        annotations = list(getattr(self, "current_annotations", []) or [])
        total_images = len(annotations)
        successful_images = sum(1 for ann in annotations if getattr(ann, "is_successful", False))
        images_with_plates, total_plates = self._count_plate_annotations(annotations)

        if total_images <= 0:
            return "Autoanotacja zostala zakonczona. Run anotacji Z2 jest zapisany w workspace projektu."

        return (
            f"Autoanotacja zakonczona. Przetworzono {total_images} obrazow, "
            f"wynik dodatni uzyskano dla {successful_images}, a tablice wykryto na {images_with_plates} obrazach "
            f"(lacznie {total_plates} tablic)."
        )

    def _get_run_plate_annotation_counts(self, run_dir: Path | None) -> tuple[int, int]:
        if run_dir is None:
            return 0, 0

        try:
            run_dir = Path(run_dir)
        except Exception:
            return 0, 0

        current_run_dir = getattr(self, "current_annotation_run_dir", None)
        if (
            current_run_dir is not None
            and self.current_annotations
            and self._paths_equivalent(run_dir, current_run_dir)
        ):
            return self._count_plate_annotations(self.current_annotations)

        xml_path = run_dir / "annotations.xml"
        if not xml_path.exists():
            return 0, 0

        try:
            cache_run_key = str(run_dir.resolve())
        except Exception:
            cache_run_key = str(run_dir)

        cache_stamp = None
        try:
            stat = xml_path.stat()
            cache_stamp = (int(getattr(stat, "st_mtime_ns", 0) or 0), int(getattr(stat, "st_size", 0) or 0))
        except Exception:
            cache_stamp = None

        cache_entry = self._run_plate_count_cache.get(cache_run_key)
        if (
            isinstance(cache_entry, dict)
            and cache_stamp is not None
            and cache_entry.get("stamp") == cache_stamp
        ):
            return (
                int(cache_entry.get("images_with_plates", 0) or 0),
                int(cache_entry.get("total_plates", 0) or 0),
            )

        try:
            annotations = self._parse_cvat_preview_annotations(xml_path)
        except Exception:
            return 0, 0

        images_with_plates, total_plates = self._count_plate_annotations(annotations)
        if cache_stamp is not None:
            self._run_plate_count_cache[cache_run_key] = {
                "stamp": cache_stamp,
                "images_with_plates": int(images_with_plates),
                "total_plates": int(total_plates),
            }
        return images_with_plates, total_plates

    def _get_campaign_step2_approval_context(self) -> dict:
        context = {
            "project_active": False,
            "current_step": 0,
            "iteration_target": "",
            "run_dir": None,
            "source_kind": "",
        }

        try:
            from ..campaign_manager import CAMPAIGN

            context["project_active"] = bool(CAMPAIGN.get_active_project_name())
            context["current_step"] = int(CAMPAIGN.get_current_step() or 0)
            context["iteration_target"] = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        except Exception:
            return context

        if not context["project_active"] or context["current_step"] != 2:
            return context

        staging_candidate = self._resolve_existing_run_dir(CAMPAIGN.get_step2_staging_run())
        if staging_candidate is not None and (staging_candidate / "annotations.xml").exists():
            context["run_dir"] = staging_candidate
            context["source_kind"] = "staging"
            return context

        if context["iteration_target"] != "char":
            return context

        allowed_roots = []
        try:
            staging_root = CAMPAIGN.get_staging_dir("auto_ann")
            if staging_root is not None:
                allowed_roots.append(Path(staging_root))
        except Exception:
            pass
        try:
            auto_root = CAMPAIGN.get_dir("auto_ann")
            if auto_root is not None:
                allowed_roots.append(Path(auto_root))
        except Exception:
            pass

        bootstrap_candidate = None
        try:
            bootstrap = self._get_campaign_auto_annotation_bootstrap("char")
            bootstrap_candidate = bootstrap.get("restore_run_dir")
        except Exception:
            bootstrap_candidate = None

        for raw_candidate in (
            getattr(self, "current_annotation_run_dir", None),
            bootstrap_candidate,
            getattr(self, "last_staging_run_dir", None),
        ):
            candidate = self._resolve_existing_run_dir(raw_candidate)
            if candidate is None or not (candidate / "annotations.xml").exists():
                continue
            if allowed_roots and not any(self._path_is_within(candidate, root) for root in allowed_roots):
                continue
            context["run_dir"] = candidate
            context["source_kind"] = "existing"
            return context

        return context

    def _refresh_step2_action_states(self):
        dataset_run_dir = self._resolve_safe_annotation_run_dir(self.plate_dataset_run_var.get())
        if dataset_run_dir is None:
            dataset_run_dir = self._resolve_safe_annotation_run_dir(getattr(self, "current_annotation_run_dir", None))
        if dataset_run_dir is None:
            dataset_run_dir = self._resolve_safe_annotation_run_dir(getattr(self, "last_staging_run_dir", None))

        dataset_images_dir = self._resolve_existing_dir(self.plate_dataset_images_var.get())
        if dataset_images_dir is None:
            dataset_images_dir = self._resolve_existing_dir(self.input_dir_var.get())

        dataset_xml_exists = bool(dataset_run_dir and (dataset_run_dir / "annotations.xml").exists())
        _dataset_images_with_plates, dataset_total_plates = self._get_run_plate_annotation_counts(dataset_run_dir)
        manual_route = bool(self._manual_xml_template_enabled())
        dataset_ready = bool(
            dataset_xml_exists
            and dataset_images_dir is not None
            and dataset_total_plates > 0
        )
        if self.is_processing:
            dataset_ready = False

        try:
            self.export_plate_dataset_btn.configure(state=(tk.NORMAL if dataset_ready else tk.DISABLED))
        except Exception:
            pass

        if dataset_xml_exists and dataset_images_dir is not None and dataset_total_plates <= 0:
            self._set_plate_export_status(
                (
                    "Run recznej anotacji Z2 istnieje, ale nie ma jeszcze zapisanej ani jednej tablicy. "
                    "Dodaj i zapisz co najmniej jeden polygon 'plate', aby odblokowac eksport datasetu YOLO Pose."
                    if manual_route
                    else "Run anotacji Z2 istnieje, ale nie ma jeszcze zapisanej ani jednej tablicy. "
                    "Popraw wynik albo dodaj co najmniej jedna tablice 'plate', aby odblokowac eksport datasetu YOLO Pose."
                ),
                "warning",
            )

        approval_context = self._get_campaign_step2_approval_context()
        approval_run_dir = approval_context.get("run_dir")
        project_active = bool(approval_context.get("project_active"))
        current_step = int(approval_context.get("current_step") or 0)
        approval_iteration_target = str(approval_context.get("iteration_target") or "").strip().lower()

        approval_xml_exists = bool(approval_run_dir and (approval_run_dir / "annotations.xml").exists())
        approval_images_with_plates, approval_total_plates = self._get_run_plate_annotation_counts(approval_run_dir)
        min_approval_images = 2
        approve_ready = bool(
            project_active
            and current_step == 2
            and approval_xml_exists
            and approval_total_plates > 0
            and int(approval_images_with_plates or 0) >= int(min_approval_images)
            and not self.is_processing
        )

        try:
            if approval_iteration_target == "char":
                self.approve_btn_row.configure(text=" Tablice gotowe -> znaki ")
                self.approve_btn.configure(text="TABLICE GOTOWE -> PRZEJDZ DO ZNAKOW (Z3)")
            else:
                self.approve_btn_row.configure(text=" Domkniecie E2 ")
                self.approve_btn.configure(text="DOMKNIJ ETAP E2")
            self.approve_btn.config(state=(tk.NORMAL if approve_ready else tk.DISABLED))
        except Exception:
            pass

        approve_hint_text = ""
        approve_hint_tone = "muted"
        campaign_context = not self._is_free_mode_session_context()
        if project_active and current_step == 2 and approval_xml_exists:
            if approval_total_plates > 0 and int(approval_images_with_plates or 0) >= int(min_approval_images):
                if approval_iteration_target == "char":
                    approve_hint_text = (
                        f"Tablice sa gotowe do przejscia do znakow. Oznaczone obrazy: {approval_images_with_plates}. "
                        f"Zapisanych tablic: {approval_total_plates}. Mozesz teraz przejsc do pracy nad znakami w Z3."
                    )
                else:
                    approve_hint_text = (
                        f"Gotowe do zamkniecia E2. Oznaczone obrazy: {approval_images_with_plates}. Zapisanych tablic: {approval_total_plates}. "
                        + (
                            "Mozesz teraz od razu domknac ten etap."
                            if campaign_context
                            else "Mozesz teraz wyeksportowac dataset YOLO Pose albo od razu domknac ten etap."
                        )
                    )
                approve_hint_tone = "success"
            elif approval_total_plates > 0:
                missing_images = max(0, int(min_approval_images) - int(approval_images_with_plates or 0))
                if approval_iteration_target == "char":
                    approve_hint_text = (
                        "Aby przejsc z tablic do znakow, potrzebujesz co najmniej 2 oznaczonych obrazow. "
                        f"Obecnie: {approval_images_with_plates}/2. "
                        + (
                            f"Brakuje jeszcze {missing_images} obrazu z zapisana tablica 'plate'. "
                            if missing_images > 0
                            else ""
                        )
                        + "Przy jednej tablicy nie przygotujesz potem poprawnego train i val dla treningu znakow."
                    )
                else:
                    approve_hint_text = (
                        "Aby odblokowac domkniecie E2 w torze tablic, potrzebujesz co najmniej 2 oznaczonych obrazow. "
                        f"Obecnie: {approval_images_with_plates}/2. "
                        + (
                            f"Brakuje jeszcze {missing_images} obrazu z zapisana tablica 'plate'. "
                            if missing_images > 0
                            else ""
                        )
                        + "Dodaj brakujace oznaczenia i zapisz zmiany."
                    )
                approve_hint_tone = "warning"
            else:
                if approval_iteration_target == "char":
                    approve_hint_text = (
                        "Aby przejsc do znakow w Z3, to zrodlo musi zawierac co najmniej jedna zapisana tablice 'plate'. "
                        + (
                            "Dodaj i zapisz przynajmniej jeden polygon recznie. "
                            if manual_route
                            else "Popraw wynik albo dodaj przynajmniej jedna tablice recznie. "
                        )
                    )
                else:
                    approve_hint_text = (
                        "Aby odblokowac domkniecie E2, run musi zawierac co najmniej jedna tablice 'plate'. "
                        + (
                            "Dodaj i zapisz przynajmniej jeden polygon recznie. "
                            if manual_route
                            else "Popraw wynik albo dodaj przynajmniej jedna tablice recznie. "
                        )
                        + (
                            "Ten sam warunek odblokowuje tez eksport datasetu YOLO Pose."
                            if not campaign_context
                            else "To warunek konieczny do domkniecia E2."
                        )
                    )
                approve_hint_tone = "warning"

        try:
            self.approve_gate_hint_var.set(approve_hint_text)
        except Exception:
            pass

        approve_hint_lbl = getattr(self, "approve_gate_hint_lbl", None)
        if approve_hint_lbl is not None:
            self._set_inline_label_state(approve_hint_lbl, tone=approve_hint_tone, emphasis=False)
        self._set_approve_hint_box_state(approve_hint_tone if approve_hint_text else "muted")

    def _build_annotation_success_next_steps(self) -> str:
        annotations = list(getattr(self, "current_annotations", []) or [])
        total_plates = sum(int(getattr(ann, "num_plates", 0) or 0) for ann in annotations)

        if getattr(self, "_current_run_manual_template", False):
            return (
                "Utworzono run recznej anotacji Z2. Wybierz obraz w podgladzie po prawej i uzyj "
                "'Nowy polygon 4 pkt (D)', aby dorysowaÄ‡ tablice. Po zapisaniu zmian moĹĽesz niĹĽej "
                "wyeksportować dataset YOLO Pose do [Z4]. Ręczne polygony są zapisywane w XML "
                "z etykietÄ… 'plate'."
            )

        if total_plates <= 0:
            return (
                "Run anotacji zostal zapisany, ale nie wykryto tablic gotowych do dalszego przeplywu. "
                "Możesz przejrzeć wyniki w podglądzie albo uruchomić autoanotację ponownie z innymi ustawieniami."
            )

        return (
            "Co dalej: możesz od razu przejść do [Z3]/[PZ1], aby wyodrębnić i rektyfikować tablice, "
            "a następnie kontynuować pracę nad znakami. "
            "Jeśli chcesz trenować model tablic, możesz też zostać w [Z2] i niżej wyeksportować dataset YOLO Pose do [Z4]."
        )

    def _build_annotation_success_next_steps(self) -> str:
        annotations = list(getattr(self, "current_annotations", []) or [])
        total_plates = sum(len(self._get_plate_detections(ann)) for ann in annotations)
        campaign_context = not self._is_free_mode_session_context()

        if getattr(self, "_current_run_manual_template", False):
            return (
                "Nowy run recznej anotacji Z2 jest gotowy. Poprawiaj polygony bezposrednio w podgladzie, "
                "uzywaj Del do twardego usuwania zlych obrazow i zapisuj korekty na biezaco do annotations.xml."
                + (
                    " Po zapisaniu zmian domknij E2; dataset i trening wykonasz potem w [Z4]."
                    if campaign_context
                    else ""
                )
            )

        if total_plates <= 0:
            return (
                "Run anotacji Z2 zostal zapisany, ale bez gotowych tablic. Mozesz przejrzec wyniki, poprawic je recznie "
                "albo uruchomic autoanotacje ponownie z innymi ustawieniami."
            )

        return (
            "Run anotacji Z2 jest gotowy. W sekcji 3 mozesz przejsc do korekty recznej."
            + (
                " Po domknieciu E2 przygotujesz dataset i trening w [Z4]."
                if campaign_context
                else " W sekcji 4 uruchomisz split i eksport gotowego zbioru."
            )
        )

    def _load_plate_dataset_context_from_run(self, run_dir: Path, force_images_update: bool = False):
        run_dir = self._resolve_safe_annotation_run_dir(run_dir)
        if run_dir is None:
            return

        try:
            self.plate_dataset_run_var.set(str(run_dir))
        except Exception:
            pass

        self.plate_dataset_out_var.set(self._plate_dataset_output_preview(run_dir))

        current_images = Path(self.plate_dataset_images_var.get().strip()) if self.plate_dataset_images_var.get().strip() else None
        current_valid = bool(current_images and current_images.exists())

        if current_valid and not force_images_update:
            return

        manifest = self._load_annotation_run_manifest(run_dir)
        input_dir = str(manifest.get("input_dir") or "").strip()
        if input_dir and Path(input_dir).exists():
            self.plate_dataset_images_var.set(input_dir)
            return

        if getattr(self, "current_input_dir", None):
            try:
                current_input = Path(self.current_input_dir)
                if current_input.exists():
                    self.plate_dataset_images_var.set(str(current_input))
            except Exception:
                pass

    def _refresh_plate_dataset_export_sources(self):
        run_dir = None
        run_value = str(self.plate_dataset_run_var.get() or "").strip()
        input_value = str(self.input_dir_var.get() or "").strip()
        current_input_dir = Path(input_value) if input_value else None
        if run_value:
            run_dir = self._resolve_safe_annotation_run_dir(run_value)

        project_active = False
        if run_dir is None:
            try:
                from ..campaign_manager import CAMPAIGN

                project_active = bool(CAMPAIGN.get_active_project_name()) and not self._is_free_mode_session_context()
                if project_active:
                    candidate = self._resolve_safe_annotation_run_dir(CAMPAIGN.get_step2_staging_run())
                    if candidate is not None and self._annotation_run_matches_input(candidate, current_input_dir):
                        run_dir = candidate

                    if run_dir is None:
                        search_roots = []
                        for root_candidate in (CAMPAIGN.get_staging_dir("auto_ann"), CAMPAIGN.get_dir("auto_ann")):
                            if root_candidate is not None:
                                search_roots.append(Path(root_candidate))

                        run_dir = self._find_latest_annotation_run_for_input(current_input_dir, search_roots)
            except Exception:
                project_active = False

        if run_dir is None and getattr(self, "last_staging_run_dir", None) and not project_active:
            candidate = self._resolve_safe_annotation_run_dir(self.last_staging_run_dir)
            if candidate is not None and (
                current_input_dir is None or self._annotation_run_matches_input(candidate, current_input_dir)
            ):
                run_dir = candidate

        if run_dir is None and current_input_dir is None:
            run_dir = self._find_latest_annotation_run_dir()

        if run_dir is not None:
            self._load_plate_dataset_context_from_run(run_dir, force_images_update=project_active)
            xml_path = run_dir / "annotations.xml"
            images_text = str(self.plate_dataset_images_var.get() or "").strip()
            if xml_path.exists():
                if images_text and Path(images_text).exists():
                    self._set_plate_export_status(
                        f"Gotowe do eksportu datasetu: {run_dir.name} + obrazy z {self._format_workspace_relative_path(images_text)}.",
                        "success"
                    )
                else:
                    self._set_plate_export_status(
                        "Wybrano run anotacji Z2, ale trzeba jeszcze wskazac folder zrodlowych obrazow dla tego runu anotacji.",
                        "warning"
                    )
            else:
                self._set_plate_export_status(
                    "Wybrany folder runu anotacji nie zawiera pliku annotations.xml.",
                    "error"
                )
            self._refresh_manual_plate_stage_ui()
            self._refresh_step2_action_states()
            return

        if current_input_dir is not None:
            self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
            self._set_plate_export_status(
                f"Dla aktualnego folderu obrazów nie ma jeszcze runu anotacji Z2. Kliknij {self._get_step2_start_action_reference()}, aby utworzyć nowy run anotacji dla tej puli albo wskaż run anotacji ręcznie.",
                "muted"
            )
            self._refresh_manual_plate_stage_ui()
            self._refresh_step2_action_states()
            return

        self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
        self._set_plate_export_status(
            f"Brak runu anotacji Z2. Najpierw kliknij {self._get_step2_start_action_reference()}, aby utworzyć nowy run autoanotacji Z2, albo wskaż istniejący folder runu anotacji ręcznie.",
            "muted"
        )
        self._refresh_manual_plate_stage_ui()
        self._refresh_step2_action_states()

    def _select_plate_dataset_run_dir(self):
        initialdir = self.plate_dataset_run_var.get().strip()
        if not initialdir:
            try:
                from ..campaign_manager import CAMPAIGN

                if CAMPAIGN.get_active_project_name() and not self._is_free_mode_session_context():
                    auto_dir = CAMPAIGN.get_dir("auto_ann")
                    staging_dir = CAMPAIGN.get_staging_dir("auto_ann")
                    initialdir = str(auto_dir or staging_dir or "")
            except Exception:
                initialdir = ""
        if not initialdir:
            initialdir = self.output_dir_var.get().strip() or str(CONFIG.get_auto_annotations_dir("plate"))
        path = filedialog.askdirectory(initialdir=initialdir)
        if not path:
            return

        run_dir = self._resolve_safe_annotation_run_dir(path, require_xml=True)
        if run_dir is None:
            return messagebox.showerror(
                "Bledny run anotacji",
                "Wybrany folder runu anotacji musi lezec w aktywnym workspace Z2 i zawierac annotations.xml.",
            )
        self._load_plate_dataset_context_from_run(run_dir, force_images_update=True)
        self._refresh_plate_dataset_export_sources()

    def _select_plate_dataset_images_dir(self):
        initialdir = self.plate_dataset_images_var.get().strip() or self.input_dir_var.get().strip() or str(CONFIG.DIR_1_RAW)
        path = filedialog.askdirectory(initialdir=initialdir)
        if not path:
            return

        self.plate_dataset_images_var.set(path)
        self._refresh_plate_dataset_export_sources()

    def _update_plate_dataset_ratio_labels(self):
        train = float(self.plate_train_pct.get())
        val = float(self.plate_val_pct.get())
        max_train_plus_val = 95.0
        if train + val > max_train_plus_val:
            val = max(5.0, max_train_plus_val - train)
            self.plate_val_pct.set(val)

        test = max(5.0, 100.0 - train - val)
        self.plate_train_lbl.configure(text=f"{train:.0f}%")
        self.plate_val_lbl.configure(text=f"{val:.0f}%")
        self.plate_test_lbl.configure(text=f"Test: {test:.0f}%")

    def _start_plate_dataset_export(self):
        if not self._ensure_preview_edits_saved("eksport datasetu tablic"):
            return

        run_dir_value = str(self.plate_dataset_run_var.get() or "").strip()
        images_dir_value = str(self.plate_dataset_images_var.get() or "").strip()

        if not run_dir_value:
            return messagebox.showerror("Brak runu anotacji", "Wskaz folder runu anotacji Z2 zawierajacy annotations.xml.")
        if not images_dir_value:
            return messagebox.showerror("Brak obrazow", "Wskaz folder obrazow, na ktorych powstal wybrany run anotacji.")

        run_dir = self._resolve_safe_annotation_run_dir(run_dir_value, require_xml=True)
        images_dir = Path(images_dir_value)

        if run_dir is None:
            return messagebox.showerror(
                "Bledny run anotacji",
                "Wybrany folder runu anotacji musi lezec w aktywnym workspace Z2 i zawierac annotations.xml.",
            )
        if not images_dir.exists() or not images_dir.is_dir():
            return messagebox.showerror("Brak obrazow", "Wybrany folder obrazow nie istnieje.")

        xml_path = run_dir / "annotations.xml"

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = self._get_plate_dataset_base_dir() / f"Plates_Z2_{run_dir.name}_{timestamp}"
        self.plate_dataset_out_var.set(str(out_dir))
        self.plate_export_progress_var.set(0.0)
        self._dataset_export_completed = False
        self.export_plate_dataset_btn.configure(state=tk.DISABLED)
        self._set_plate_export_status("Rozpoczynam eksport datasetu YOLO Pose...", "success")

        train = float(self.plate_train_pct.get()) / 100.0
        val = float(self.plate_val_pct.get()) / 100.0
        ratios = {
            "train": train,
            "val": val,
            "test": max(0.0, 1.0 - train - val)
        }

        def worker():
            try:
                logger.info("=" * 50)
                logger.info("START EKSPORTU DATASETU TABLIC (Z2 -> YOLO Pose)")
                logger.info("=" * 50)
                logger.info(f"Run: {run_dir}")
                logger.info(f"Obrazy: {images_dir}")
                logger.info(f"Output: {out_dir}")
                run_manifest = self._load_annotation_run_manifest(run_dir)
                manual_stage_enabled = bool(
                    run_manifest.get("manual_xml_template", False)
                    and not self._is_free_mode_session_context()
                )
                stage_result = {
                    "enabled": manual_stage_enabled,
                    "ok": False,
                    "message": "",
                    "pending_count": 0,
                    "stage_images_total": 0,
                    "stage_images_dir": "",
                }

                self.dataset_creator.annotations = []
                ok, msg, _ = self.dataset_creator.parse_cvat_xml(xml_path)
                if not ok:
                    self._post_to_ui(lambda: messagebox.showerror("Bledny XML", msg))
                    self._post_to_ui(lambda: self._set_plate_export_status(msg, "error"))
                    return

                def prog(current, total, image_name):
                    pct = (current / total) * 100 if total > 0 else 0
                    self._post_to_ui(lambda: self.plate_export_progress_var.set(pct))
                    self._post_to_ui(
                        lambda: self._set_plate_export_status(
                            f"Eksport datasetu: {current}/{total} obrazow... ({image_name})",
                            "success"
                        )
                    )

                ok, msg, _ = self.dataset_creator.create_dataset(images_dir, out_dir, ratios, prog)
                if not ok:
                    self._post_to_ui(lambda: messagebox.showerror("Blad eksportu", msg))
                    self._post_to_ui(lambda: self._set_plate_export_status(msg, "error"))
                    return

                try:
                    self._write_plate_dataset_source_manifest(
                        out_dir,
                        source_kind="z2_run_export",
                        source_run_dir=run_dir,
                        source_xml_path=xml_path,
                        source_images_dir=images_dir,
                    )
                except Exception as e:
                    logger.debug(f"Nie udalo sie zapisac manifestu zrodla datasetu tablic: {e}")

                if manual_stage_enabled:
                    stage_ok, stage_msg, stage_stats = self.dataset_creator.sync_pending_stage(
                        images_dir,
                        self._get_manual_plate_stage_dir(),
                    )
                    stage_result["ok"] = bool(stage_ok)
                    stage_result["message"] = str(stage_msg or "").strip()
                    if isinstance(stage_stats, dict):
                        stage_result["pending_count"] = int(stage_stats.get("pending_count", 0) or 0)
                        stage_result["stage_images_total"] = int(stage_stats.get("stage_images_total", 0) or 0)
                        stage_result["stage_images_dir"] = str(stage_stats.get("stage_images_dir") or "").strip()
                    if stage_ok:
                        logger.info(stage_msg)
                    else:
                        logger.warning(stage_msg)

                logger.info(f"[OK] Dataset YOLO Pose gotowy: {out_dir}")

                def finish_success():
                    self.plate_export_progress_var.set(100.0)
                    self._dataset_export_completed = True
                    stage_note = ""
                    stage_hint = ""
                    if stage_result.get("enabled"):
                        pending_count = int(stage_result.get("pending_count", 0) or 0)
                        stage_total = int(stage_result.get("stage_images_total", pending_count) or pending_count)
                        stage_images_dir = str(stage_result.get("stage_images_dir") or "").strip()
                        stage_rel = self._format_workspace_relative_path(stage_images_dir) if stage_images_dir else ""
                        if stage_result.get("ok"):
                            if pending_count > 0:
                                stage_note = (
                                    f" Do stage oczekujacych trafilo {pending_count} nieoznaczonych zdjec. "
                                    f"Stage zawiera teraz {stage_total} obrazow: {stage_rel}."
                                )
                                stage_hint = (
                                    f" Stage oczekujacych zawiera teraz {stage_total} obrazow. "
                                    f"Do kolejnej rundy recznej anotacji wykorzystaj folder {stage_rel}."
                                )
                            else:
                                stage_note = " Wszystkie zdjecia z tej paczki maja juz oznaczone tablice."
                                stage_hint = stage_note
                        else:
                            stage_note = f" Dataset powstal, ale stage oczekujacych nie zostal zaktualizowany: {stage_result.get('message')}"
                            stage_hint = stage_note
                    next_step_text = (
                        f"Dataset gotowy: {self._format_workspace_relative_path(out_dir)}. "
                        "Możesz teraz przejść do [Z4], aby rozpocząć trening modelu tablic."
                    )
                    self._set_plate_export_status(
                        next_step_text,
                        "success"
                    )
                    if stage_note:
                        self._set_plate_export_status(next_step_text + stage_note, "success")
                    self._refresh_manual_plate_stage_ui()
                    training_tab = getattr(getattr(self, "app", None), "tabs", {}).get("training")
                    dataset_preloaded = False
                    if training_tab is not None and hasattr(training_tab, "dataset_var"):
                        try:
                            training_tab.dataset_var.set(str(out_dir))
                            if hasattr(training_tab, "_update_training_dataset_hint"):
                                training_tab._update_training_dataset_hint()
                            dataset_preloaded = True
                        except Exception:
                            pass
                    if dataset_preloaded:
                        self._set_post_annotation_hint(
                            "Dataset tablic jest już gotowy i został podstawiony w [Z4]. Możesz przejść do treningu modelu.",
                            "success"
                        )
                    if dataset_preloaded and stage_hint:
                        self._set_post_annotation_hint(
                            "Dataset tablic jest juz gotowy i zostal podstawiony w [Z4]. Mozesz przejsc do treningu modelu."
                            + stage_hint,
                            "success"
                        )
                    messagebox.showinfo(
                        "Sukces",
                        (
                            "Dataset YOLO Pose zostaĹ‚ utworzony poprawnie.\n\n"
                            f"{out_dir}\n\n"
                            "Możesz teraz przejść do [Z4], aby rozpocząć trening modelu tablic."
                            + ("\nŚcieżka datasetu została już podstawiona w Z4." if dataset_preloaded else "")
                        )
                    )

                    if stage_result.get("enabled") and stage_result.get("ok") and str(stage_result.get("stage_images_dir") or "").strip():
                        pending_count = int(stage_result.get("pending_count", 0) or 0)
                        stage_total = int(stage_result.get("stage_images_total", pending_count) or pending_count)
                        messagebox.showinfo(
                            "Stage oczekujacych",
                            (
                                f"Do stage oczekujacych trafilo {pending_count} nieoznaczonych zdjec z tej paczki.\n\n"
                                f"Stage zawiera teraz lacznie {stage_total} obrazow.\n"
                                f"{stage_result.get('stage_images_dir')}\n\n"
                                "Ten folder mozesz wykorzystac pozniej jako kolejna pule do recznej anotacji."
                            )
                        )
                    elif stage_result.get("enabled") and not stage_result.get("ok") and str(stage_result.get("message") or "").strip():
                        messagebox.showwarning(
                            "Stage oczekujacych",
                            stage_result.get("message"),
                        )
                    self._refresh_free_mode_workflow_ui()
                    self._queue_free_mode_session_save()

                self._post_to_ui(finish_success)
            except Exception as e:
                logger.error(f"Blad eksportu datasetu tablic: {e}")
                self._post_to_ui(lambda err=str(e): messagebox.showerror("Krytyczny blad", err))
                self._post_to_ui(
                    lambda err=str(e): self._set_plate_export_status(
                        f"Krytyczny blad eksportu: {err}",
                        "error"
                    )
                )
            finally:
                self._post_to_ui(self._refresh_step2_action_states)

        threading.Thread(target=worker, daemon=True).start()

    def _redirect_logs(self):
        if getattr(self, "_annotation_log_handlers_attached", False):
            return

        def append_annotation_log(message: str):
            text = "" if message is None else str(message)
            if not text:
                return
            if not text.endswith("\n"):
                text += "\n"

            def update():
                try:
                    if hasattr(self.app, "append_global_terminal"):
                        self.app.append_global_terminal(text.rstrip("\n"), source="Z2")
                except Exception:
                    pass
                try:
                    self.log_text.insert(tk.END, text)
                    self.log_text.see(tk.END)
                except Exception:
                    pass

            if threading.current_thread() is threading.main_thread():
                try:
                    self.frame.after_idle(update)
                except Exception:
                    try:
                        update()
                    except Exception:
                        pass
            else:
                self._post_to_ui(update)

        class TextHandler(logging.Handler):
            def __init__(self, owner):
                super().__init__()
                self.owner = owner

            def emit(self, record):
                try:
                    msg = self.format(record)
                    if msg:
                        append_annotation_log(msg)
                except Exception:
                    pass
                 
        formatter = logging.Formatter('%(asctime)s | %(message)s', '%H:%M:%S')

        self._annotation_app_log_handler = TextHandler(self)
        self._annotation_app_log_handler.setFormatter(formatter)
        logger.addHandler(self._annotation_app_log_handler)

        try:
            self._annotation_ultralytics_log_handler = TextHandler(self)
            self._annotation_ultralytics_log_handler.setFormatter(formatter)
            self._annotation_ultralytics_logger = logging.getLogger("ultralytics")
            self._annotation_ultralytics_logger.addHandler(self._annotation_ultralytics_log_handler)
        except Exception:
            pass

        self._annotation_log_handlers_attached = True

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        for label_name in (
            "workflow_entry_title_lbl",
            "sources_title_lbl",
            "run_title_lbl",
            "followup_title_lbl",
            "manual_stage_title_lbl",
            "export_title_lbl",
            "split_title_lbl",
        ):
            label = getattr(self, label_name, None)
            if label is None or not hasattr(label, "apply_theme"):
                continue
            try:
                label.apply_theme()
            except Exception:
                pass

        try:
            self.app.style_panel_surface(self.frame, background=palette.get("panel", "#252526"))
        except Exception:
            pass

        try:
            self.app.style_text_widget(self.log_text, role="console")
        except Exception:
            pass

        try:
            self.app.style_listbox_widget(self.preview_listbox, bordercolor=panel_border)
            self._refresh_preview_list(preserve_selection=True, render_current=False)
        except Exception:
            pass

        try:
            self._refresh_preview_list_legend_theme()
            self._refresh_preview_list_summary()
        except Exception:
            pass

        try:
            self.app.style_canvas_widget(
                self.preview_canvas,
                background=palette.get("panel", "#1e1e1e"),
                bordercolor=panel_border
            )
        except Exception:
            pass

        try:
            legend_theme = self._get_preview_legend_theme()
            self.preview_controls_canvas.configure(bg=legend_theme["canvas_bg"])
            self._refresh_preview_controls_legend()
        except Exception:
            pass

        try:
            self.left_settings_canvas.configure(
                bg=palette.get("panel", "#252526"),
                highlightthickness=0,
                bd=0,
            )
        except Exception:
            pass

        try:
            self.right_settings_canvas.configure(
                bg=palette.get("panel", "#252526"),
                highlightthickness=0,
                bd=0,
            )
        except Exception:
            pass

        for shell_name in ("left_scroll_shell", "preview_left_list_shell", "right_scroll_shell"):
            shell = getattr(self, shell_name, None)
            if shell is None:
                continue
            try:
                shell.configure(
                    bg=palette.get("panel", "#252526"),
                    highlightbackground=panel_border,
                    highlightcolor=panel_border,
                )
            except Exception:
                pass

        try:
            workflow_shell_border = blend_hex_colors(
                palette.get("accent", "#4f8de3"),
                panel_border,
                0.62,
            )
            workflow_shell_fill = blend_hex_colors(
                palette.get("surface_info", palette.get("panel", "#252526")),
                palette.get("panel", "#252526"),
                0.80,
            )
            if hasattr(self, "workflow_entry_shell"):
                self.workflow_entry_shell.configure(bg=workflow_shell_border)
            if hasattr(self, "workflow_entry_shell_inner"):
                self.workflow_entry_shell_inner.configure(bg=workflow_shell_fill)
                self.app.style_panel_surface(
                    self.workflow_entry_shell_inner,
                    background=workflow_shell_fill,
                )
        except Exception:
            pass

        try:
            self.app.style_web_scrollbar(
                self.left_settings_scrollbar,
                track_color=palette.get("panel", "#252526"),
            )
        except Exception:
            pass

        try:
            self.app.style_web_scrollbar(
                self.right_settings_scrollbar,
                track_color=palette.get("panel", "#252526"),
            )
        except Exception:
            pass

        try:
            self._update_device_hint()
        except Exception:
            pass

        try:
            self._refresh_detection_configuration_ui()
        except Exception:
            pass

        try:
            self._refresh_confidence_value_labels()
        except Exception:
            pass

        try:
            self._refresh_workflow_route_cards()
        except Exception:
            pass

        try:
            self._refresh_workflow_button_styles()
        except Exception:
            pass

        try:
            self._refresh_workflow_progress_style()
        except Exception:
            pass

        for line in getattr(self, "_left_section_separators", []):
            if not isinstance(line, dict):
                continue
            try:
                host = line.get("host")
                accent = line.get("accent")
                shadow = line.get("shadow")
                if host is not None:
                    host.configure(bg=palette.get("panel", "#252526"))
                if accent is not None:
                    accent.configure(bg=palette.get("surface_info", palette.get("accent", "#0e639c")))
                if shadow is not None:
                    shadow.configure(bg=panel_border)
            except Exception:
                pass

        frame_backgrounds = {
            "start_btn_frame": palette.get("panel", "#252526"),
            "approve_btn_frame": palette.get("panel", "#252526"),
        }
        for frame_name, background in frame_backgrounds.items():
            frame = getattr(self, frame_name, None)
            if frame is None:
                continue
            try:
                frame.configure(bg=background)
            except Exception:
                pass

        pulse_backgrounds = {
            "start_btn_pulse_frame": palette.get("panel", "#252526"),
            "approve_btn_pulse_frame": palette.get("panel", "#252526"),
        }
        for frame_name, background in pulse_backgrounds.items():
            frame = getattr(self, frame_name, None)
            if frame is None:
                continue
            try:
                self.app.style_guidance_frame(frame, background=background)
            except Exception:
                pass

        inline_label_defaults = {
            "project_paths_info_lbl": ("muted", False),
            "project_paths_rel_lbl": ("muted", False),
            "status_label": ("neutral", True),
            "progress_counts_lbl": ("muted", False),
            "post_annotation_hint_lbl": ("muted", False),
            "plate_export_status_lbl": ("muted", False),
        }
        for label_name, (default_tone, default_emphasis) in inline_label_defaults.items():
            label = getattr(self, label_name, None)
            if label is None or not isinstance(label, tk.Label):
                continue
            try:
                text_value = label.cget("text")
                try:
                    if label.cget("textvariable"):
                        text_value = None
                except Exception:
                    pass
                self._set_inline_label_state(
                    label,
                    text=text_value,
                    tone=getattr(label, "_inline_tone", default_tone),
                    emphasis=getattr(label, "_inline_emphasis", default_emphasis),
                )
            except Exception:
                pass

        try:
            self._refresh_workflow_step_cards()
        except Exception:
            pass

    def _set_inline_label_state(self, widget, text: str | None = None, tone: str = "neutral", emphasis: bool = False) -> bool:
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
                bg_candidate = ttk.Style().lookup(candidate.winfo_class(), "background")
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
        }
        if text is not None:
            config_kwargs["text"] = text

        widget._inline_tone = tone_key
        widget._inline_emphasis = bool(emphasis)
        widget.config(**config_kwargs)
        return True

    def _set_approve_hint_box_state(self, tone: str = "muted"):
        box = getattr(self, "approve_hint_box", None)
        if box is None:
            return

        palette = getattr(self.app, "palette", {})
        tone_key = str(tone or "").strip().lower()
        bg = palette.get("panel_alt", palette.get("panel", palette.get("bg", "#1f1f1f")))
        border = {
            "default": palette.get("border", "#3a3a3a"),
            "neutral": palette.get("border", "#3a3a3a"),
            "muted": palette.get("border", "#3a3a3a"),
            "info": palette.get("info", palette.get("accent", "#4aa3ff")),
            "success": palette.get("success", "#2ecc71"),
            "warning": palette.get("warning", "#f39c12"),
            "error": palette.get("error", "#e74c3c"),
        }.get(tone_key, palette.get("border", "#3a3a3a"))

        try:
            box.configure(bg=bg, highlightbackground=border, highlightcolor=border)
        except Exception:
            pass

    def _refresh_manual_stage_export_box_style(self):
        box = getattr(self, "manual_stage_export_box", None)
        if box is None:
            return

        palette = getattr(self.app, "palette", {})
        box_bg = palette.get("panel", palette.get("bg", "#1f1f1f"))
        border = palette.get("panel_border", palette.get("border", "#3a3a3a"))
        title_fg = palette.get("muted", "#9a9a9a")
        muted = palette.get("muted_dim", palette.get("muted", "#9a9a9a"))

        try:
            box.configure(bg=box_bg, highlightbackground=border, highlightcolor=border)
        except Exception:
            pass

        for label, color in (
            (getattr(self, "manual_stage_export_title_lbl", None), title_fg),
            (getattr(self, "manual_stage_export_help_lbl", None), muted),
        ):
            if label is None:
                continue
            try:
                label.configure(bg=box_bg, fg=color)
            except Exception:
                pass

    def _set_status_label_state(self, text: str, tone: str = "neutral"):
        if not self._set_inline_label_state(self.status_label, text=text, tone=tone, emphasis=True):
            style_map = {
                "neutral": "PanelStatusNeutral.TLabel",
                "info": "PanelStatusInfo.TLabel",
                "success": "PanelStatusSuccess.TLabel",
                "warning": "PanelStatusWarning.TLabel",
                "error": "PanelStatusError.TLabel",
            }
            self.status_label.config(
                text=text,
                style=style_map.get(str(tone or "").lower(), "PanelStatusNeutral.TLabel")
            )

    def _set_annotation_process_log_visibility(self, visible: bool):
        if not hasattr(self, "annotation_log_overlay"):
            return

        self._annotation_log_visible = bool(visible)
        try:
            self.annotation_log_overlay.place_forget()
        except Exception:
            pass

        if self._annotation_log_visible:
            try:
                if hasattr(self.app, "show_global_terminal"):
                    self.app.show_global_terminal()
            except Exception:
                pass

        if hasattr(self, "btn_toggle_annotation_log"):
            try:
                self.btn_toggle_annotation_log.configure(text="Terminal")
            except Exception:
                pass
        return

        if self._annotation_log_visible:
            try:
                self.annotation_log_overlay.place(
                    relx=0.015,
                    rely=0.02,
                    relwidth=0.97,
                    relheight=0.96,
                )
                self.annotation_log_overlay.lift()
            except Exception:
                pass
            try:
                self.annotation_log_overlay.update_idletasks()
                self.annotation_log_frame.update_idletasks()
                self.annotation_log_host.update_idletasks()
            except Exception:
                pass
            if hasattr(self, "btn_toggle_annotation_log"):
                self.btn_toggle_annotation_log.configure(text="Ukryj terminal")
        else:
            try:
                self.annotation_log_overlay.place_forget()
            except Exception:
                pass
            if hasattr(self, "btn_toggle_annotation_log"):
                self.btn_toggle_annotation_log.configure(text="PokaĹĽ terminal")

    def _toggle_annotation_process_log(self):
        try:
            if hasattr(self.app, "toggle_global_terminal"):
                self.app.toggle_global_terminal()
                return
        except Exception:
            pass
        self._set_annotation_process_log_visibility(
            not getattr(self, "_annotation_log_visible", False)
        )

    def _validate_models(self):
        mode = self._normalize_mode_value()
        if self._mode_uses_vehicle(mode):
            if self.vehicle_model_var.get() == "Custom":
                p = self.vehicle_custom_var.get()
                if not p or not Path(p).exists(): raise ValueError("Nie znaleziono wĹ‚asnego modelu pojazdĂłw!")
                if not validate_model_file(Path(p))[0]: raise ValueError("Model pojazdĂłw jest uszkodzony!")
        
        if self._mode_uses_plate(mode):
            p = (self.plate_custom_var.get() or "").strip()
            if not p or not Path(p).exists(): raise ValueError("WskaĹĽ wytrenowany model tablic (.pt)!")
            if not validate_model_file(Path(p))[0]: raise ValueError("Model tablic jest uszkodzony!")

    def _validate_vehicle_model_selection(self):
        if self.vehicle_model_var.get() == "Custom":
            p = (self.vehicle_custom_var.get() or "").strip()
            if not p or not Path(p).exists():
                raise ValueError("Nie znaleziono wlasnego modelu pojazdow!")
            if not validate_model_file(Path(p))[0]:
                raise ValueError("Model pojazdow jest uszkodzony!")

    def clear_campaign_context(self):
        """
        Przywraca neutralny stan zakĹ‚adki Autoanotacji po wyjĹ›ciu z projektu
        i czyĹ›ci wszystkie artefakty poprzedniego projektu z UI.
        """
        self._set_campaign_paths_lock_state(False)

        try:
            self.project_paths_info_var.set("")
        except Exception:
            pass

        try:
            self.project_paths_rel_var.set("")
        except Exception:
            pass

        self.current_annotations = []
        self._clear_preview_editor_state(clear_dirty=True)
        self.is_processing = False

        try:
            self.current_input_dir = Path(self.input_dir_var.get().strip())
        except Exception:
            self.current_input_dir = None

        try:
            self.preview_listbox.delete(0, tk.END)
        except Exception:
            pass

        try:
            self.preview_canvas.delete("all")
        except Exception:
            pass

        try:
            self.log_text.delete("1.0", tk.END)
        except Exception:
            pass

        try:
            self.progress.configure(value=0)
        except Exception:
            pass

        try:
            self._set_status_label_state("Gotowy do uruchomienia", "neutral")
        except Exception:
            pass

        try:
            self._set_post_annotation_hint("")
        except Exception:
            pass

        try:
            self._set_progress_counters(0, 0, 0)
        except Exception:
            pass

        try:
            self.start_btn.config(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.stop_btn.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.approve_btn.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self._set_annotation_process_log_visibility(False)
        except Exception:
            pass

        try:
            snapshot = getattr(self, "_pre_campaign_free_mode_snapshot", None)
            self._pre_campaign_free_mode_snapshot = None
            self._apply_free_mode_session_snapshot(
                session_state=snapshot,
                restore_preview=bool(snapshot is None),
            )
            if snapshot is not None:
                self._clear_free_mode_route_selection()
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic ostatniego stanu Z2 po wyjsciu z projektu: {e}")

    def _format_project_relative_path(self, path_value: str) -> str:
        try:
            from ..campaign_manager import CAMPAIGN
            root = CAMPAIGN.get_active_project_root_dir()
            p = Path(path_value)

            if root is not None:
                try:
                    return str(p.relative_to(root))
                except Exception:
                    pass

            return str(p)
        except Exception:
            return str(path_value)

    def _set_campaign_paths_lock_state(self, locked: bool):
        self._campaign_paths_locked = bool(locked)

        try:
            self.input_dir_entry.configure(state=("readonly" if locked else "normal"))
        except Exception:
            pass

        try:
            self.input_dir_browse_btn.configure(state=(tk.DISABLED if locked else tk.NORMAL))
        except Exception:
            pass

        if locked:
            try:
                self.input_dir_entry.selection_clear()
            except Exception:
                pass

        if locked:
            self.project_paths_info_var.set(
                "Ścieżki zostały uzupełnione automatycznie z aktywnego projektu."
            )
            self.project_paths_rel_var.set(
                f"IN:  {self._format_project_relative_path(self.input_dir_var.get().strip())}\n"
                f"OUT: {self._format_project_relative_path(self.output_dir_var.get().strip())}"
            )
        else:
            self.project_paths_info_var.set("")
            self.project_paths_rel_var.set("")

    def _reset_campaign_runtime_state(self, input_dir: Path | None = None):
        self.current_annotations = []
        self._preview_image_path_map = {}
        self._clear_campaign_manual_reuse_context()
        self._clear_preview_editor_state(clear_dirty=True)
        self.is_processing = False
        self._current_run_manual_template = False
        self.current_annotation_run_dir = None
        self.current_annotation_xml_path = None
        self.last_staging_run_dir = None

        try:
            self.current_input_dir = Path(input_dir) if input_dir is not None else None
        except Exception:
            self.current_input_dir = None

        try:
            self.preview_listbox.delete(0, tk.END)
        except Exception:
            pass

        try:
            self.preview_canvas.delete("all")
        except Exception:
            pass

        try:
            self.progress.configure(value=0)
        except Exception:
            pass

        try:
            self._set_progress_counters(0, 0, 0)
        except Exception:
            pass

        try:
            self._set_status_label_state("Gotowy do uruchomienia", "neutral")
        except Exception:
            pass

        try:
            self._set_post_annotation_hint("")
        except Exception:
            pass

        try:
            self.start_btn.config(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.stop_btn.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.approve_btn.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.export_plate_dataset_btn.config(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.approve_gate_hint_var.set("")
        except Exception:
            pass

        approve_hint_lbl = getattr(self, "approve_gate_hint_lbl", None)
        if approve_hint_lbl is not None:
            self._set_inline_label_state(approve_hint_lbl, tone="muted", emphasis=False)
        self._set_approve_hint_box_state("muted")

    def _apply_campaign_step2_workflow_preset(
        self,
        *,
        iteration_target: str | None = None,
        manual_template: bool | None = None,
    ) -> None:
        if self._is_free_mode_session_context():
            return

        target = str(iteration_target or "").strip().lower()
        if target not in {"plate", "char"}:
            try:
                from ..campaign_manager import CAMPAIGN
                target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
            except Exception:
                target = ""
        if target not in {"plate", "char"}:
            target = "plate"

        input_ready = bool(str(self.input_dir_var.get() or "").strip())
        plate_ready = bool(str(self.plate_custom_var.get() or "").strip())
        campaign_default_manual = False
        try:
            from ..campaign_manager import CAMPAIGN

            campaign_default_manual = bool(
                CAMPAIGN.get_active_project_name()
                and int(CAMPAIGN.get_current_step() or 0) == 2
                and target in {"plate", "char"}
            )
        except Exception:
            campaign_default_manual = False

        if manual_template is not None:
            use_manual_route = bool(manual_template)
        else:
            use_manual_route = bool(campaign_default_manual or (target == "plate"))

        self._manual_review_active = False
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        self._last_completed_workflow_route = ""

        if use_manual_route:
            self.workflow_route_var.set("manual")
            self.manual_entry_mode_var.set("new")
            self.manual_xml_template_var.set(True)
            try:
                self.manual_vehicle_assist_var.set(False)
            except Exception:
                pass
            self.workflow_step_var.set("manual_start" if input_ready else "manual_input")
        else:
            self.workflow_route_var.set("auto")
            self.manual_xml_template_var.set(False)
            try:
                auto_choice = "use" if str(self.mode_var.get() or "").strip() == "C: Pojazdy + tablice" else "skip"
                self.auto_vehicle_choice_var.set(self._normalize_auto_vehicle_choice(auto_choice))
            except Exception:
                pass
            if not plate_ready:
                next_step = "auto_plate_model"
            elif not input_ready:
                next_step = "auto_input"
            else:
                next_step = "auto_start"
            self.workflow_step_var.set(next_step)

        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()

    def restore_campaign_context_from_project(self) -> bool:
        try:
            from ..campaign_manager import CAMPAIGN

            active_project = CAMPAIGN.get_active_project_name()
            if not active_project:
                return False
            if int(CAMPAIGN.get_current_step() or 1) < 2:
                snapshot_path = self._get_campaign_annotation_state_path(active_project)
                if snapshot_path is None or not snapshot_path.exists():
                    return False

            raw_dir = CAMPAIGN.get_dir("raw")
            auto_out = CAMPAIGN.get_staging_dir("auto_ann")
            if raw_dir is None or auto_out is None:
                return False

            iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
            campaign_mode_text = "B: Tylko tablice"
            bootstrap = self._get_campaign_auto_annotation_bootstrap(iteration_target)
            input_dir = Path(bootstrap.get("input_dir") or Path(raw_dir))
            manual_template = bool(bootstrap.get("manual_template", iteration_target == "plate"))
            plate_bootstrap_model = str(bootstrap.get("plate_model_path") or "").strip()
            restore_run_dir = bootstrap.get("restore_run_dir")
            snapshot_state = self._load_campaign_project_snapshot()
            if not self._should_restore_existing_campaign_step2_run(iteration_target):
                restore_run_dir = None
                bootstrap["restore_run_dir"] = None
            elif not self._should_restore_campaign_generated_step2_run_preview(
                restore_run_dir,
                session_state=snapshot_state,
                iteration_target=iteration_target,
            ):
                restore_run_dir = None
                bootstrap["restore_run_dir"] = None

            restored_snapshot = self.apply_campaign_context(
                input_dir,
                Path(auto_out),
                manual_template=manual_template,
                mode_text=campaign_mode_text,
                restore_project_state=True,
            )

            v_mod = CAMPAIGN.get_global_model("vehicle")
            p_mod = CAMPAIGN.get_global_model("plate")

            if not restored_snapshot:
                if v_mod and Path(v_mod).exists():
                    self.vehicle_model_var.set("Custom")
                    self.vehicle_custom_var.set(v_mod)
                else:
                    try:
                        vehicle_values = list(self.vehicle_combo["values"]) if hasattr(self, "vehicle_combo") else []
                    except Exception:
                        vehicle_values = []
                    detect_values = [value for value in vehicle_values if value != "Custom"]
                    default_vehicle = "yolo11s" if "yolo11s" in detect_values else (detect_values[0] if detect_values else "")
                    if default_vehicle:
                        self.vehicle_model_var.set(default_vehicle)
                    self.vehicle_custom_var.set("")

                if (
                    iteration_target == "char" and p_mod and Path(p_mod).exists()
                ) or (
                    iteration_target == "plate" and plate_bootstrap_model and Path(plate_bootstrap_model).exists()
                ):
                    self.plate_custom_var.set(plate_bootstrap_model if iteration_target == "plate" else p_mod)
                else:
                    self.plate_custom_var.set("")

                self.mode_var.set(campaign_mode_text)
                self._on_mode_change()

                if restore_run_dir is not None:
                    self._restore_preview_from_annotation_run(restore_run_dir)
                self._apply_campaign_step2_workflow_preset(
                    iteration_target=iteration_target,
                    manual_template=manual_template,
                )
            elif not self._get_workflow_route():
                self._apply_campaign_step2_workflow_preset(
                    iteration_target=iteration_target,
                    manual_template=manual_template,
                )
            return True
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic projektowego kontekstu Z2: {e}")
            return False

    def open_campaign_step2_entry(
        self,
        *,
        iteration_target: str | None = None,
        entry_strategy: str | None = None,
        restore_preview: bool = True,
        open_existing_run: bool = True,
    ) -> dict:
        try:
            from ..campaign_manager import CAMPAIGN

            active_project = CAMPAIGN.get_active_project_name()
            if not active_project or int(CAMPAIGN.get_current_step() or 0) < 2:
                return {"ok": False, "reason": "campaign_inactive"}

            target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
            if target not in {"plate", "char"}:
                return {"ok": False, "reason": "missing_iteration_target"}
            campaign_mode_text = "B: Tylko tablice"

            raw_dir = CAMPAIGN.get_dir("raw")
            auto_out = CAMPAIGN.get_staging_dir("auto_ann")
            if auto_out is not None:
                Path(auto_out).mkdir(parents=True, exist_ok=True)

            if raw_dir is None or auto_out is None:
                return {"ok": False, "reason": "missing_campaign_dirs"}

            vehicle_model_path = str(CAMPAIGN.get_global_model("vehicle") or "").strip()
            plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
            if target == "char" and (not plate_model_path or not Path(plate_model_path).exists()):
                messagebox.showwarning(
                    "Brak modelu tablic",
                    "Tor znakow wymaga gotowego modelu tablic Pose przypisanego do projektu.\n\n"
                    "Najpierw wytrenuj model tablic w torze A, a potem wroc do toru B."
                )
                return {"ok": False, "reason": "missing_plate_model"}

            iter_num = CAMPAIGN.get_current_iteration_num()
            folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
            input_dir = folder if folder.exists() else Path(raw_dir)
            base_input_dir = input_dir

            bootstrap = {}
            try:
                bootstrap = self._get_campaign_auto_annotation_bootstrap(target)
            except Exception:
                bootstrap = {}

            strategy = str(entry_strategy or "").strip().lower()
            if target == "plate" and strategy == "raw":
                bootstrap = dict(bootstrap) if isinstance(bootstrap, dict) else {}
                bootstrap["input_dir"] = base_input_dir
                bootstrap["restore_run_dir"] = None
                bootstrap["input_source"] = "raw_forced"
                bootstrap["manual_template"] = bool(not (plate_model_path and Path(plate_model_path).exists()))
                bootstrap["plate_model_path"] = plate_model_path if plate_model_path and Path(plate_model_path).exists() else ""

            input_dir = Path(bootstrap.get("input_dir") or input_dir)
            manual_template = bool(bootstrap.get("manual_template", target == "plate"))
            plate_bootstrap_model = str(bootstrap.get("plate_model_path") or "").strip()
            restore_run_dir = bootstrap.get("restore_run_dir")
            input_source = str(bootstrap.get("input_source") or "raw").strip()
            snapshot_state = self._load_campaign_project_snapshot()
            if not self._should_restore_existing_campaign_step2_run(target):
                restore_run_dir = None
                bootstrap["restore_run_dir"] = None
            elif not self._should_restore_campaign_generated_step2_run_preview(
                restore_run_dir,
                session_state=snapshot_state,
                iteration_target=target,
            ):
                restore_run_dir = None
                bootstrap["restore_run_dir"] = None
            open_detected_run = bool(
                open_existing_run
                and
                restore_run_dir is not None
                and strategy != "raw"
                and (
                    target == "plate"
                    or (target == "char" and not restore_preview)
                )
            )
            opened_existing_run = False

            restored_snapshot = self.apply_campaign_context(
                input_dir,
                Path(auto_out),
                manual_template=manual_template,
                mode_text=campaign_mode_text,
                restore_preview=restore_preview,
            )

            if not restored_snapshot and not open_detected_run:
                if vehicle_model_path and Path(vehicle_model_path).exists():
                    self.vehicle_model_var.set("Custom")
                    self.vehicle_custom_var.set(vehicle_model_path)
                else:
                    try:
                        vehicle_values = list(self.vehicle_combo["values"]) if hasattr(self, "vehicle_combo") else []
                    except Exception:
                        vehicle_values = []
                    detect_values = [value for value in vehicle_values if value != "Custom"]
                    default_vehicle = "yolo11s" if "yolo11s" in detect_values else (detect_values[0] if detect_values else "")
                    if default_vehicle:
                        self.vehicle_model_var.set(default_vehicle)
                    self.vehicle_custom_var.set("")

                if (
                    target == "char" and plate_model_path and Path(plate_model_path).exists()
                ) or (
                    target == "plate" and plate_bootstrap_model and Path(plate_bootstrap_model).exists()
                ):
                    self.plate_custom_var.set(plate_bootstrap_model if target == "plate" else plate_model_path)
                else:
                    self.plate_custom_var.set("")

                self.mode_var.set(campaign_mode_text)
                self._on_mode_change()

            if open_detected_run:
                try:
                    if self._is_free_mode_session_context():
                        opened_existing_run = self._open_existing_run_for_manual_review(
                            run_dir=restore_run_dir,
                            allow_fallback=False,
                            from_auto=False,
                            show_dialog=False,
                        )
                    else:
                        opened_existing_run = self._open_existing_run_for_campaign_review(
                            run_dir=restore_run_dir,
                            iteration_target=target,
                            manual_template=manual_template,
                        )
                except Exception:
                    opened_existing_run = False

            if not opened_existing_run and not restored_snapshot:
                self._apply_campaign_step2_workflow_preset(
                    iteration_target=target,
                    manual_template=manual_template,
                )
            elif not opened_existing_run and not self._get_workflow_route():
                self._apply_campaign_step2_workflow_preset(
                    iteration_target=target,
                    manual_template=manual_template,
                )

            try:
                self._refresh_free_mode_workflow_ui()
            except Exception:
                pass

            try:
                self._scroll_left_panel_to_widget(
                    getattr(self, "workflow_start_section", None)
                    or getattr(self, "source_section", None)
                    or getattr(self, "actions_section", None)
                )
            except Exception:
                pass

            try:
                self._refresh_step2_action_states()
            except Exception:
                pass

            return {
                "ok": True,
                "iteration_target": target,
                "input_dir": str(input_dir),
                "auto_out": str(auto_out),
                "manual_template": bool(manual_template),
                "input_source": input_source,
                "restored_snapshot": bool(restored_snapshot),
                "opened_existing_run": bool(opened_existing_run),
                "restore_run_dir": str(restore_run_dir or ""),
                "plate_model_path": plate_model_path,
            }
        except Exception as e:
            logger.error(f"Nie udalo sie otworzyc punktu startowego Z2: {e}")
            return {"ok": False, "reason": "exception", "error": str(e)}

    def _apply_campaign_iteration_model_defaults(self, iteration_target: str | None = None) -> None:
        try:
            from ..campaign_manager import CAMPAIGN

            if not CAMPAIGN.get_active_project_name():
                return

            target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
            if target not in {"plate", "char"}:
                return

            vehicle_model_path = str(CAMPAIGN.get_global_model("vehicle") or "").strip()
            plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        except Exception:
            return

        try:
            vehicle_values = list(self.vehicle_combo["values"]) if hasattr(self, "vehicle_combo") else []
        except Exception:
            vehicle_values = []

        current_vehicle = str(self.vehicle_model_var.get() or "").strip()
        current_vehicle_custom = str(self.vehicle_custom_var.get() or "").strip()
        vehicle_selection_invalid = False

        if current_vehicle == "Custom":
            vehicle_selection_invalid = not current_vehicle_custom or not Path(current_vehicle_custom).exists()
        elif current_vehicle:
            vehicle_selection_invalid = bool(vehicle_values) and current_vehicle not in vehicle_values
        else:
            vehicle_selection_invalid = True

        if vehicle_selection_invalid:
            if vehicle_model_path and Path(vehicle_model_path).exists():
                self.vehicle_model_var.set("Custom")
                self.vehicle_custom_var.set(vehicle_model_path)
            else:
                detect_values = [value for value in vehicle_values if value != "Custom"]
                default_vehicle = "yolo11s" if "yolo11s" in detect_values else (detect_values[0] if detect_values else "")
                if default_vehicle:
                    self.vehicle_model_var.set(default_vehicle)
                self.vehicle_custom_var.set("")

        if target == "char" and plate_model_path and Path(plate_model_path).exists():
            current_plate = str(self.plate_custom_var.get() or "").strip()
            if not current_plate or not Path(current_plate).exists():
                self.plate_custom_var.set(plate_model_path)

        try:
            self._on_vehicle_model_change()
        except Exception:
            pass

    def _enforce_campaign_plate_only_auto_default(self, iteration_target: str | None = None) -> None:
        if self._is_free_mode_session_context():
            return

        try:
            from ..campaign_manager import CAMPAIGN

            target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
        except Exception:
            target = str(iteration_target or "").strip().lower()

        if target not in {"plate", "char"}:
            return
        if self._manual_xml_template_enabled():
            return
        if self._get_workflow_route() != "auto":
            return
        if getattr(self, "current_annotation_xml_path", None) is not None:
            return

        changed = False
        if str(self.mode_var.get() or "").strip() != "B: Tylko tablice":
            self.mode_var.set("B: Tylko tablice")
            changed = True
        if self._get_auto_vehicle_choice() != "skip":
            self.auto_vehicle_choice_var.set("skip")
            changed = True

        if changed:
            self._refresh_auto_vehicle_choice_ui()
            self._refresh_left_panel_route_copy()
            self._refresh_detection_configuration_ui()
            self._refresh_step2_action_states()
            self._refresh_free_mode_workflow_ui()

    def _should_restore_existing_campaign_step2_run(self, iteration_target: str | None = None) -> bool:
        if self._is_free_mode_session_context():
            return True

        try:
            from ..campaign_manager import CAMPAIGN

            target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
            campaign_step = int(CAMPAIGN.get_current_step() or 0)
            step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
            current_step2_run = self._resolve_safe_annotation_run_dir(
                CAMPAIGN.get_step2_staging_run(),
                require_xml=True,
            )
        except Exception:
            return True

        if (
            target == "plate"
            and campaign_step == 2
            and step2_status in {"", "pending"}
            and current_step2_run is None
        ):
            return False

        return True

    def _should_restore_campaign_generated_step2_run_preview(
        self,
        run_dir: Path | None,
        *,
        session_state: dict | None = None,
        iteration_target: str | None = None,
    ) -> bool:
        if self._is_free_mode_session_context():
            return True

        try:
            from ..campaign_manager import CAMPAIGN

            target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
            campaign_step = int(CAMPAIGN.get_current_step() or 0)
            step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
            current_step2_run = self._resolve_safe_annotation_run_dir(
                CAMPAIGN.get_step2_staging_run(),
                require_xml=True,
            )
        except Exception:
            return True

        candidate = self._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        if (
            target != "plate"
            or campaign_step != 2
            or step2_status != "generated"
            or candidate is None
            or current_step2_run is None
        ):
            return True

        try:
            same_run = self._paths_equivalent(candidate, current_step2_run)
        except Exception:
            same_run = False
        if not same_run:
            return True

        try:
            manifest = self._load_annotation_run_manifest(candidate)
        except Exception:
            manifest = {}

        if self._annotation_run_manifest_has_manual_value(manifest):
            return True

        state = dict(session_state or {})
        if bool(state.get("manual_review_active", False)):
            return True

        workflow_route = self._normalize_workflow_route_value(state.get("workflow_route"))
        if workflow_route == "manual":
            return True

        return False

    def _refresh_campaign_workflow_input_lock_state(self, *, campaign_context: bool, current_step: str):
        entry = getattr(self, "workflow_input_entry", None)
        browse_btn = getattr(self, "workflow_input_browse_btn", None)
        title_lbl = getattr(self, "workflow_input_title_lbl", None)

        lock_input = bool(
            campaign_context
            and self._get_workflow_route() == "auto"
            and current_step == "auto_start"
        )

        if title_lbl is not None:
            try:
                title_lbl.configure(
                    text=("Folder obrazów tej iteracji" if lock_input else "4. Wskaż katalog obrazów")
                )
            except Exception:
                pass

        if entry is not None:
            try:
                entry.configure(state=("readonly" if lock_input else "normal"))
            except Exception:
                pass

        if browse_btn is not None:
            try:
                if lock_input:
                    browse_btn.grid_remove()
                else:
                    browse_btn.grid()
            except Exception:
                try:
                    browse_btn.configure(state=(tk.DISABLED if lock_input else tk.NORMAL))
                except Exception:
                    pass

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

    def _resolve_guidance_frame(self, attr_name: str):
        if not attr_name:
            return None

        candidates = [attr_name]
        if attr_name.endswith("_frame"):
            candidates.insert(0, f"{attr_name[:-6]}_pulse_frame")

        for candidate in candidates:
            widget = getattr(self, candidate, None)
            if isinstance(widget, tk.Frame):
                return widget

        return None

    def _pulse_action_frame(self, frame_attr: str, pulses: int = 8, interval_ms: int = 260, color: str = "#f39c12"):
        if str(frame_attr or "").strip() == "start_btn_pulse_frame":
            return

        btn = self._resolve_guidance_button(frame_attr)
        frame = self._resolve_guidance_frame(frame_attr)

        if frame is not None:
            try:
                self.app.pulse_frame(frame, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True)
            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ pulsowaÄ‡ ramki dla {frame_attr}: {e}")

        if btn is None:
            return

        try:
            self.app.pulse_button(btn, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True)
        except Exception as e:
            logger.debug(f"Nie udaĹ‚o siÄ™ pulsowaÄ‡ przycisku dla {frame_attr}: {e}")

    def apply_campaign_context(
        self,
        input_dir: Path,
        output_dir: Path,
        *,
        manual_template: bool = False,
        mode_text: str = "C: Pojazdy + tablice",
        restore_project_state: bool = True,
        restore_preview: bool = True,
    ):
        self._campaign_project_restore_in_progress = True
        restored_snapshot = False
        try:
            self.input_dir_var.set(str(input_dir))
            self.output_dir_var.set(str(self._coerce_annotation_output_dir(output_dir)))
            self.plate_dataset_images_var.set(str(input_dir))
            self.plate_dataset_run_var.set("")
            self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
            self.plate_custom_var.set("")
            self.manual_xml_template_var.set(bool(manual_template))
            self.manual_vehicle_assist_var.set(bool(manual_template))
            self.mode_var.set(self._normalize_mode_value(mode_text))
            self.character_model_var.set("Brak / OCR")
            self.character_custom_var.set("")
            self._reset_campaign_runtime_state(input_dir)
            self._update_manual_xml_template_ui()
            self._on_mode_change()
            self._set_campaign_paths_lock_state(True)
            self._refresh_plate_dataset_export_sources()
            if hasattr(self, "character_combo"):
                self._refresh_character_model_choices()
        finally:
            self._campaign_project_restore_in_progress = False

        if restore_project_state:
            restored_snapshot = self._apply_campaign_project_snapshot(restore_preview=restore_preview)

        if restore_preview and not restored_snapshot:
            self._restore_preview_from_session_run()

        if not restored_snapshot and not getattr(self, "current_annotations", None):
            try:
                self._prime_campaign_source_preview(input_dir)
            except Exception as e:
                logger.debug(f"Nie udało się przygotować podglądu paczki Z2: {e}")

        try:
            self._apply_campaign_iteration_model_defaults()
        except Exception:
            pass

        try:
            self._enforce_campaign_plate_only_auto_default()
        except Exception:
            pass

        self._refresh_step2_action_states()
        self._pulse_action_frame("start_btn_pulse_frame")
        return restored_snapshot

    def _prime_campaign_source_preview(self, input_dir: Path | None) -> bool:
        if input_dir is None:
            return False

        try:
            source_dir = Path(input_dir)
        except Exception:
            return False

        source_plan = self._collect_campaign_auto_annotation_sources(
            source_dir,
            include_previous=bool(self.campaign_reuse_manual_var.get()),
        )
        image_paths = list(source_plan.get("image_paths") or [])
        if not image_paths:
            image_paths = get_image_files(source_dir)
        if not image_paths:
            return False

        previous_annotations_by_name = {}
        if bool(self.campaign_reuse_manual_var.get()):
            try:
                previous_bundle = self._get_campaign_previous_manual_source_bundle()
                previous_xml_path = previous_bundle.get("xml_path")
                if isinstance(previous_xml_path, Path) and previous_xml_path.exists():
                    previous_annotations = self._parse_cvat_preview_annotations(previous_xml_path)
                    previous_annotations_by_name = {
                        str(getattr(ann, "filename", "") or "").strip(): ann
                        for ann in previous_annotations
                        if str(getattr(ann, "filename", "") or "").strip()
                    }
            except Exception as e:
                logger.debug(f"Nie udało się wczytać poprzednich ręcznych anotacji do podglądu kampanijnego Z2: {e}")

        preview_annotations: list[ImageAnnotation] = []
        for image_path in image_paths:
            filename = image_path.name
            previous_ann = previous_annotations_by_name.get(filename)
            if previous_ann is not None and filename in set(source_plan.get("reused_filenames") or set()):
                preview_annotations.append(copy.deepcopy(previous_ann))
            else:
                width, height = get_image_size(image_path)
                preview_annotations.append(
                    ImageAnnotation(
                        filename=filename,
                        width=max(1, int(width)),
                        height=max(1, int(height)),
                        detections=[],
                        status=AnnotationStatus.NO_PLATE,
                        status_message="Obraz źródłowy gotowy do przygotowania XML lub autoanotacji.",
                    )
                )

        self.current_input_dir = source_dir
        self._preview_image_path_map = {
            str(name): Path(path)
            for name, path in dict(source_plan.get("image_map") or {}).items()
        }
        self._apply_campaign_manual_reuse_context(source_plan)
        self.current_annotations = preview_annotations
        self.current_preview_index = None
        try:
            self._populate_preview_list()
        except Exception:
            self._refresh_preview_list(preserve_selection=False, render_current=True)
        try:
            self._set_progress_counters(0, 0, len(preview_annotations))
        except Exception:
            pass
        try:
            self._set_status_label_state(
                f"Wczytano paczkę zdjęć. Kliknij {self._get_step2_start_action_reference()}, aby przygotować XML albo uruchomić autoanotację.",
                "neutral",
            )
        except Exception:
            pass
        try:
            self._refresh_preview_workspace_visibility(manual_review_active=False)
        except Exception:
            pass
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass
        return True

    def _get_workflow_route(self) -> str:
        return self._normalize_workflow_route_value(self.workflow_route_var.get())

    def _get_manual_entry_mode(self) -> str:
        return self._normalize_manual_entry_mode(self.manual_entry_mode_var.get())

    def _get_auto_vehicle_choice(self) -> str:
        return self._normalize_auto_vehicle_choice(self.auto_vehicle_choice_var.get())

    def _get_workflow_step(self) -> str:
        return self._normalize_workflow_step_value(self.workflow_step_var.get())

    def _get_free_mode_screen(self) -> str:
        return self._normalize_free_mode_screen_value(self.free_mode_screen_var.get())

    def _coerce_free_mode_screen(self, screen: str | None = None) -> str:
        if not self._is_free_mode_session_context():
            return ""

        route = self._get_workflow_route()
        requested = self._normalize_free_mode_screen_value(
            self._get_free_mode_screen() if screen is None else screen
        )
        has_existing_run = self._get_preferred_annotation_run_dir(require_xml=True) is not None
        manual_review_active = bool(self._manual_review_active and has_existing_run)
        export_active = bool(self._manual_review_export_ready or self._dataset_export_completed)
        auto_completed = bool(
            route == "auto"
            and has_existing_run
            and not self.is_processing
            and self._last_completed_workflow_route == "auto"
        )

        if not route:
            return "route_choice"

        if requested == "route_choice":
            return "workflow"

        if requested == "workflow":
            if export_active:
                return "export"
            if manual_review_active:
                return "manual_review"
            return "workflow"

        if requested == "auto_summary":
            if export_active:
                return "export"
            if manual_review_active:
                return "manual_review"
            return "auto_summary" if (route == "auto" and has_existing_run) else "workflow"

        if requested == "manual_review":
            if export_active:
                return "export"
            if manual_review_active:
                return "manual_review"
            return "auto_summary" if auto_completed else "workflow"

        if requested == "export":
            if export_active:
                return "export"
            if manual_review_active:
                return "manual_review"
            return "auto_summary" if auto_completed else "workflow"

        if export_active:
            return "export"
        if manual_review_active:
            return "manual_review"
        if auto_completed:
            return "auto_summary"
        return "workflow"

    def _get_workflow_progress_display(self) -> tuple[int, int]:
        route = self._get_workflow_route()
        current_step = self._coerce_workflow_step()
        steps = self._get_current_workflow_steps()
        current_index = steps.index(current_step) + 1 if current_step in steps else 0
        total_steps = len(steps)

        if not self._is_free_mode_session_context():
            if bool(getattr(self, "_manual_review_active", False)):
                return 0, 0
            return current_index, total_steps

        screen = self._coerce_free_mode_screen()
        manual_entry_mode = self._get_manual_entry_mode()

        if route == "manual":
            if manual_entry_mode == "continue":
                total_steps = 4
                if screen == "manual_review":
                    return 3, total_steps
                if screen == "export":
                    return 4, total_steps
                if current_step == "manual_entry":
                    return 1, total_steps
                if current_step == "manual_history":
                    return 2, total_steps
            elif manual_entry_mode == "import":
                total_steps = 3
                if screen == "manual_review":
                    return 2, total_steps
                if screen == "export":
                    return 3, total_steps
                if current_step == "manual_entry":
                    return 1, total_steps
            elif manual_entry_mode == "new":
                total_steps = 5
                if screen == "manual_review":
                    return 4, total_steps
                if screen == "export":
                    return 5, total_steps
                if current_step == "manual_entry":
                    return 1, total_steps
                if current_step == "manual_input":
                    return 2, total_steps
                if current_step == "manual_start":
                    return 3, total_steps

        if route == "auto" and screen == "auto_summary":
            return len(steps) + 1, len(steps) + 1

        return current_index, total_steps

    def _resolve_manual_review_history_created_at(self, entry: dict, safe_run_dir: Path) -> str:
        created_at = str(entry.get("created_at") or "").strip()
        if created_at:
            return created_at
        manifest = self._load_annotation_run_manifest(safe_run_dir)
        for candidate in (
            str(manifest.get("generated_at") or "").strip(),
            str(manifest.get("completed_at") or "").strip(),
            str(manifest.get("created_at") or "").strip(),
        ):
            if candidate:
                return candidate

        try:
            return datetime.datetime.fromtimestamp(safe_run_dir.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            return ""

    def _normalize_manual_review_history_entries(self, entries) -> list[dict]:
        normalized: list[dict] = []
        seen: set[str] = set()

        for entry in entries or []:
            if isinstance(entry, str):
                entry = {"run_dir": entry}
            if not isinstance(entry, dict):
                continue

            safe_run_dir = self._resolve_safe_annotation_run_dir(entry.get("run_dir"), require_xml=True)
            if safe_run_dir is None:
                continue

            run_dir_text = str(safe_run_dir)
            if run_dir_text in seen:
                continue

            seen.add(run_dir_text)
            normalized.append(
                {
                    "run_dir": run_dir_text,
                    "created_at": self._resolve_manual_review_history_created_at(entry, safe_run_dir),
                    "source": str(entry.get("source") or "").strip(),
                }
            )

        normalized.sort(
            key=lambda item: (
                str(item.get("created_at") or "").strip(),
                str(item.get("run_dir") or "").strip().lower(),
            ),
            reverse=True,
        )
        return normalized[:20]

    def _format_manual_review_history_label(self, entry: dict) -> str:
        run_dir = str(entry.get("run_dir") or "").strip()
        safe_run_dir = self._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        if safe_run_dir is None:
            return ""

        created_at = str(entry.get("created_at") or "").strip()
        label = safe_run_dir.name
        if created_at:
            try:
                created_dt = datetime.datetime.fromisoformat(created_at)
                created_text = created_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                created_text = created_at.replace("T", " ").strip()
            if created_text:
                label = f"{label} | {created_text}"
        return label

    def _refresh_manual_review_history_ui(self):
        values = []
        label_map = {}

        for entry in self._manual_review_history_entries or []:
            label = self._format_manual_review_history_label(entry)
            if not label:
                continue
            values.append(label)
            label_map[label] = str(entry.get("run_dir") or "").strip()

        self._manual_review_history_label_map = label_map

        combo = getattr(self, "manual_history_combo", None)
        if combo is not None:
            try:
                combo.configure(values=values)
            except Exception:
                pass

        current_value = str(self.manual_history_run_var.get() or "").strip()
        if current_value not in label_map:
            preferred_value = ""
            for candidate_run in (
                getattr(self, "current_annotation_run_dir", None),
                getattr(self, "last_staging_run_dir", None),
                str(self.plate_dataset_run_var.get() or "").strip(),
            ):
                current_run = self._resolve_safe_annotation_run_dir(candidate_run, require_xml=True)
                if current_run is None:
                    continue
                for label, run_dir in label_map.items():
                    if run_dir == str(current_run):
                        preferred_value = label
                        break
                if preferred_value:
                    break
            if not preferred_value and values and self._get_manual_entry_mode() == "continue":
                preferred_value = values[0]
            self.manual_history_run_var.set(preferred_value)

        hint_text = ""
        run_definition = self._get_annotation_run_definition_text()
        default_storage = self._get_annotation_run_storage_display_path()
        try:
            self.manual_history_title_lbl.configure(text="2. Historia runow autoanotacji Z2")
        except Exception:
            pass
        if values and self._manual_review_active and self._get_manual_entry_mode() == "continue":
            hint_text = (
                "Aktywny run jest juz otwarty w podgladzie. Wstecz wraca do historii, a Dalej przechodzi do eksportu datasetu. "
                "Mozesz tez zaznaczyc inny run i otworzyc go ponownie.\n\n"
                f"{run_definition}\n\n"
                f"Domyslny katalog runow anotacji Z2: {default_storage}"
            )
        elif values:
            hint_text = (
                "Wybierz run anotacji z historii i kliknij Dalej, aby otworzyc go do korekty. "
                "Jesli szukanego runu tu nie ma, wroc o krok i wybierz tor wskazania dowolnego runu.\n\n"
                f"{run_definition}\n\n"
                f"Domyslny katalog runow anotacji Z2: {default_storage}"
            )
        elif self._get_manual_entry_mode() == "continue":
            hint_text = (
                "Historia recznych korekt jest pusta. Wroc o krok i wybierz nowa anotacje "
                "albo tor wskazania dowolnego runu autoanotacji Z2.\n\n"
                f"{run_definition}\n\n"
                f"Domyslny katalog runow anotacji Z2: {default_storage}"
            )
        elif self._manual_review_active or self._manual_review_from_auto:
            hint_text = "Brak zapisanej historii korekt dla aktualnego runu anotacji."
        self._set_inline_label_state(
            getattr(self, "manual_history_hint_lbl", None),
            text=hint_text,
            tone=("muted" if values else "warning" if self._get_manual_entry_mode() == "continue" and hint_text else "muted"),
            emphasis=False,
        )

        try:
            self.manual_history_open_btn.configure(
                state=(tk.NORMAL if bool(str(self.manual_history_run_var.get() or "").strip()) else tk.DISABLED)
            )
        except Exception:
            pass

    def _remember_manual_review_run(self, run_dir: Path | str | None, *, source: str = "manual", created_at: str | None = None):
        safe_run_dir = self._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        if safe_run_dir is None:
            return

        timestamp = str(created_at or "").strip() or self._resolve_manual_review_history_created_at({}, safe_run_dir)
        updated_entries = [
            {
                "run_dir": str(safe_run_dir),
                "created_at": timestamp,
                "source": str(source or "").strip(),
            }
        ]

        for entry in self._manual_review_history_entries or []:
            if str(entry.get("run_dir") or "").strip() == str(safe_run_dir):
                continue
            updated_entries.append(entry)

        self._manual_review_history_entries = self._normalize_manual_review_history_entries(updated_entries)
        self._refresh_manual_review_history_ui()
        try:
            safe_run_dir_text = str(safe_run_dir)
            for label, run_dir in self._manual_review_history_label_map.items():
                if run_dir == safe_run_dir_text:
                    self.manual_history_run_var.set(label)
                    break
        except Exception:
            pass
        self._queue_free_mode_session_save()
        if self._is_free_mode_session_context():
            try:
                if SESSION:
                    SESSION.set("annotation", "manual_review_history", list(self._manual_review_history_entries or []))
                    SESSION.set("annotation", "manual_review_active", bool(self._manual_review_active))
                    SESSION.set("annotation", "manual_review_from_auto", bool(self._manual_review_from_auto))
                    SESSION.set("annotation", "manual_review_export_ready", bool(self._manual_review_export_ready))
                    SESSION.set("annotation", "workflow_route", self._normalize_workflow_route_value())
                    SESSION.set("annotation", "manual_entry_mode", self._normalize_manual_entry_mode())
                    SESSION.set("annotation", "workflow_step", self._get_workflow_step())
                    SESSION.set("annotation", "plate_dataset_run", str(safe_run_dir))
                    SESSION.set("annotation", "last_preview_run_dir", str(safe_run_dir))
                    SESSION.save_session()
                self.flush_free_mode_session_state()
            except Exception:
                pass

    def _get_selected_manual_review_history_run_dir(self) -> Path | None:
        selected_label = str(self.manual_history_run_var.get() or "").strip()
        selected_run = self._manual_review_history_label_map.get(selected_label)
        if selected_run:
            return self._resolve_safe_annotation_run_dir(selected_run, require_xml=True)
        return None

    def _open_selected_manual_review_history_run(self):
        selected_run = self._get_selected_manual_review_history_run_dir()
        if selected_run is None:
            return
        self._open_existing_run_for_manual_review(
            run_dir=selected_run,
            allow_fallback=False,
            show_dialog=False,
        )

    def _on_manual_history_selection_changed(self, event=None):
        selected = bool(self._get_selected_manual_review_history_run_dir() is not None)
        try:
            self.manual_history_open_btn.configure(
                state=(tk.NORMAL if selected else tk.DISABLED)
            )
        except Exception:
            pass
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        self._queue_free_mode_session_save()

    def _get_auto_workflow_steps(self) -> list[str]:
        steps = [
            "auto_plate_model",
            "auto_conf",
            "auto_vehicle_choice",
        ]
        if self._get_auto_vehicle_choice() == "use":
            steps.append("auto_vehicle_model")
        steps.extend([
            "auto_input",
            "auto_start",
        ])
        return steps

    def _get_manual_workflow_steps(self) -> list[str]:
        steps = ["manual_entry"]
        manual_entry_mode = self._get_manual_entry_mode()
        if manual_entry_mode == "new":
            steps.extend(["manual_input", "manual_start"])
        elif manual_entry_mode == "continue":
            steps.append("manual_history")
        return steps

    def _get_current_workflow_steps(self) -> list[str]:
        route = self._get_workflow_route()
        if route == "auto":
            return self._get_auto_workflow_steps()
        if route == "manual":
            return self._get_manual_workflow_steps()
        return []

    def _get_default_workflow_step(self) -> str:
        route = self._get_workflow_route()
        if route == "auto":
            if not str(self.plate_custom_var.get() or "").strip():
                return "auto_plate_model"
            return "auto_conf"
        if route == "manual":
            return "manual_entry"
        return ""

    def _coerce_workflow_step(self, step: str | None = None) -> str:
        route = self._get_workflow_route()
        current = self._normalize_workflow_step_value(
            self._get_workflow_step() if step is None else step
        )
        steps = self._get_current_workflow_steps()
        if not route or not steps:
            return ""

        if not current:
            return self._get_default_workflow_step()

        if current == "auto_plate_model":
            return current if route == "auto" else self._get_default_workflow_step()
        if current in {"auto_conf", "auto_vehicle_choice"}:
            if route != "auto":
                return self._get_default_workflow_step()
            return current if str(self.plate_custom_var.get() or "").strip() else "auto_plate_model"
        if current == "auto_vehicle_model":
            if route != "auto":
                return self._get_default_workflow_step()
            if not str(self.plate_custom_var.get() or "").strip():
                return "auto_plate_model"
            return current if self._get_auto_vehicle_choice() == "use" else "auto_vehicle_choice"
        if current in {"auto_input", "auto_start"}:
            if route != "auto":
                return self._get_default_workflow_step()
            if not str(self.plate_custom_var.get() or "").strip():
                return "auto_plate_model"
            if self._get_auto_vehicle_choice() == "use" and "auto_vehicle_model" in steps and current == "auto_start":
                return current
            return current
        if current == "manual_entry":
            return current if route == "manual" else self._get_default_workflow_step()
        if current == "manual_history":
            if route != "manual":
                return self._get_default_workflow_step()
            return current if self._get_manual_entry_mode() == "continue" else "manual_entry"
        if current in {"manual_conf", "manual_vehicle_model"}:
            if route != "manual":
                return self._get_default_workflow_step()
            return "manual_input" if self._get_manual_entry_mode() == "new" else "manual_entry"
        if current == "manual_input":
            if route != "manual":
                return self._get_default_workflow_step()
            return current if self._get_manual_entry_mode() == "new" else "manual_entry"
        if current == "manual_start":
            if route != "manual":
                return self._get_default_workflow_step()
            return current if self._get_manual_entry_mode() == "new" else "manual_entry"

        return self._get_default_workflow_step()

    def _set_workflow_step(
        self,
        step: str,
        *,
        refresh: bool = True,
        save: bool = True,
        refresh_detection_ui: bool = False,
    ):
        normalized = self._coerce_workflow_step(step)
        self.workflow_step_var.set(normalized)
        if refresh:
            self._refresh_left_panel_route_copy()
            if refresh_detection_ui:
                self._refresh_detection_configuration_ui()
            self._refresh_step2_action_states()
            self._refresh_free_mode_workflow_ui()
            anchor = {
                "auto_plate_model": getattr(self, "auto_plate_model_section", None),
                "auto_conf": getattr(self, "workflow_conf_section", None),
                "auto_vehicle_choice": getattr(self, "auto_vehicle_choice_section", None),
                "auto_vehicle_model": getattr(self, "workflow_vehicle_model_section", None),
                "auto_input": getattr(self, "workflow_input_section", None),
                "auto_start": getattr(self, "workflow_start_section", None),
                "manual_entry": getattr(self, "manual_entry_section", None),
                "manual_history": getattr(self, "manual_history_section", None),
                "manual_conf": getattr(self, "workflow_conf_section", None),
                "manual_vehicle_model": getattr(self, "workflow_vehicle_model_section", None),
                "manual_input": getattr(self, "workflow_input_section", None),
                "manual_start": getattr(self, "workflow_start_section", None),
            }.get(normalized)
            self._schedule_left_panel_scroll_to_widget(anchor or getattr(self, "actions_section", None))
        if save:
            self._queue_free_mode_session_save()

    def _clear_free_mode_route_selection(self):
        self.workflow_route_var.set("")
        self.workflow_step_var.set("")
        self.free_mode_screen_var.set("route_choice")
        self.manual_history_run_var.set("")
        self._manual_review_active = False
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        self._last_completed_workflow_route = ""
        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        self._scroll_left_panel_to_widget(
            getattr(self, "workflow_entry_shell", None)
            or getattr(self, "workflow_entry_section", None)
        )
        self._queue_free_mode_session_save()

    def _exit_manual_review_stage(self):
        self._manual_review_export_ready = False
        self._dataset_export_completed = False

        if self._manual_review_from_auto:
            self._manual_review_active = False
            self._manual_review_from_auto = False
            self.workflow_route_var.set("auto")
            self.workflow_step_var.set("auto_start")
            self.free_mode_screen_var.set("auto_summary")
            self._last_completed_workflow_route = "auto"
            self._refresh_left_panel_route_copy()
            self._refresh_detection_configuration_ui()
            self._refresh_step2_action_states()
            self._refresh_free_mode_workflow_ui()
            self._scroll_left_panel_to_widget(getattr(self, "followup_section", None) or getattr(self, "actions_section", None))
            self._queue_free_mode_session_save()
            return

        self._manual_review_active = False
        self._manual_review_from_auto = False
        self.free_mode_screen_var.set("workflow")
        self._set_workflow_step(
            "manual_history" if self._get_manual_entry_mode() == "continue" else "manual_entry"
        )

    def _is_workflow_step_complete(self, step: str | None = None) -> bool:
        current = self._coerce_workflow_step(step)
        has_existing_run = self._get_preferred_annotation_run_dir(require_xml=True) is not None
        input_dir_value = str(self.input_dir_var.get() or "").strip()
        input_ready = bool(input_dir_value and Path(input_dir_value).exists())
        vehicle_model_value = str(self.vehicle_model_var.get() or "").strip()
        vehicle_custom_value = str(self.vehicle_custom_var.get() or "").strip()
        vehicle_model_ready = bool(vehicle_model_value)
        if vehicle_model_ready and vehicle_model_value == "Custom":
            vehicle_model_ready = bool(vehicle_custom_value and Path(vehicle_custom_value).exists())

        if current == "auto_plate_model":
            return bool(str(self.plate_custom_var.get() or "").strip())
        if current == "auto_conf":
            return True
        if current == "auto_vehicle_choice":
            return True
        if current in {"auto_vehicle_model", "manual_vehicle_model"}:
            return vehicle_model_ready
        if current == "auto_input":
            return input_ready
        if current == "manual_entry":
            return True
        if current == "manual_history":
            return self._get_selected_manual_review_history_run_dir() is not None
        if current == "manual_input":
            if not input_ready:
                return False
            if self._manual_vehicle_assist_enabled():
                return vehicle_model_ready
            return True
        if current == "manual_conf":
            return True
        if current in {"auto_start", "manual_start"}:
            return False
        return False

    def _go_to_previous_workflow_step(self):
        if self.is_processing:
            return

        if self._is_free_mode_session_context():
            screen = self._coerce_free_mode_screen()
            if screen == "export":
                self._close_export_followup()
                return
            if screen == "manual_review":
                self._exit_manual_review_stage()
                return
            if screen == "auto_summary":
                self.free_mode_screen_var.set("workflow")
                if self._get_workflow_route() == "auto":
                    self._set_workflow_step("auto_start")
                    return
                self._refresh_left_panel_route_copy()
                self._refresh_detection_configuration_ui()
                self._refresh_step2_action_states()
                self._refresh_free_mode_workflow_ui()
                self._scroll_left_panel_to_widget(
                    getattr(self, "workflow_start_section", None)
                    or getattr(self, "actions_section", None)
                )
                self._queue_free_mode_session_save()
                return

        if self._manual_review_export_ready:
            self._close_export_followup()
            return

        if self._dataset_export_completed:
            return

        if self._manual_review_active:
            self._exit_manual_review_stage()
            return

        current = self._coerce_workflow_step()
        steps = self._get_current_workflow_steps()
        if current not in steps:
            if self._is_free_mode_session_context() and self._get_workflow_route():
                self._clear_free_mode_route_selection()
            return
        idx = steps.index(current)
        if idx <= 0:
            if self._is_free_mode_session_context() and self._get_workflow_route():
                self._clear_free_mode_route_selection()
            return
        self._set_workflow_step(steps[idx - 1])

    def _close_export_followup(self):
        if self.is_processing:
            return

        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        if self._is_free_mode_session_context():
            has_existing_run = self._get_preferred_annotation_run_dir(require_xml=True) is not None
            if self._manual_review_active and has_existing_run:
                self.free_mode_screen_var.set("manual_review")
            elif self._get_workflow_route() == "auto" and has_existing_run:
                self.free_mode_screen_var.set("auto_summary")
            else:
                self.free_mode_screen_var.set("workflow")
        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        scroll_target = None
        if self._is_free_mode_session_context():
            screen = self._coerce_free_mode_screen()
            if screen == "auto_summary":
                scroll_target = getattr(self, "followup_section", None)
            elif screen == "manual_review":
                scroll_target = (
                    getattr(self, "manual_stage_export_box", None)
                    or getattr(self, "manual_stage_section", None)
                )
            elif self._get_manual_entry_mode() == "continue":
                scroll_target = getattr(self, "manual_history_section", None)
            else:
                scroll_target = getattr(self, "actions_section", None)
        self._scroll_left_panel_to_widget(
            scroll_target
            or getattr(self, "manual_stage_section", None)
            or getattr(self, "followup_section", None)
        )
        self._queue_free_mode_session_save()

    def _go_to_next_workflow_step(self):
        if self._is_free_mode_session_context():
            screen = self._coerce_free_mode_screen()
            if screen == "auto_summary":
                if self._get_preferred_annotation_run_dir(require_xml=True) is not None:
                    self._enter_manual_review_from_auto()
                return
            if screen == "manual_review":
                self._jump_to_export_section()
                return
            if screen == "export":
                if self._dataset_export_completed:
                    self._clear_free_mode_route_selection()
                else:
                    self._start_plate_dataset_export()
                return

        if self._dataset_export_completed and self._is_free_mode_session_context():
            self._clear_free_mode_route_selection()
            return

        current = self._coerce_workflow_step()
        route = self._get_workflow_route()
        manual_entry_mode = self._get_manual_entry_mode()
        if route == "manual" and current == "manual_entry" and manual_entry_mode == "new":
            self._clear_active_annotation_run_context(preserve_input_dir=True)
        if self._manual_review_active and route == "manual":
            if current == "manual_history":
                self._jump_to_export_section()
                return
            if current == "manual_entry" and manual_entry_mode == "import":
                self._jump_to_export_section()
                return
        if route == "manual" and current == "manual_entry" and manual_entry_mode == "import":
            self._import_or_open_manual_review_run_from_dialog()
            return
        if route == "manual" and current == "manual_history":
            self._open_selected_manual_review_history_run()
            return
        steps = self._get_current_workflow_steps()
        if current not in steps or not self._is_workflow_step_complete(current):
            return
        idx = steps.index(current)
        if idx >= len(steps) - 1:
            return
        self._set_workflow_step(steps[idx + 1])

    def _get_preferred_annotation_run_dir(self, *, require_xml: bool = False) -> Path | None:
        for candidate in (
            getattr(self, "current_annotation_run_dir", None),
            getattr(self, "last_staging_run_dir", None),
            str(self.plate_dataset_run_var.get() or "").strip(),
        ):
            safe_run_dir = self._resolve_safe_annotation_run_dir(candidate, require_xml=require_xml)
            if safe_run_dir is not None:
                return safe_run_dir

        current_input = getattr(self, "current_input_dir", None)
        if current_input is not None:
            run_dir = self._find_latest_annotation_run_for_input(Path(current_input), self._get_annotation_run_roots())
            run_dir = self._resolve_safe_annotation_run_dir(run_dir, require_xml=require_xml)
            if run_dir is not None:
                return run_dir

        return self._find_latest_annotation_run_dir() if not require_xml else self._resolve_safe_annotation_run_dir(
            self._find_latest_annotation_run_dir(),
            require_xml=True,
        )

    def _refresh_workflow_route_cards(self):
        palette = getattr(self.app, "palette", {})
        route = self._get_workflow_route()
        hover_route = getattr(self, "_workflow_route_hover_mode", None)

        panel_alt = palette.get("panel_alt", "#2d2d30")
        hover_bg = palette.get("button_hover", panel_alt)
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        accent = palette.get("accent", "#0e639c")
        success = palette.get("success", "#4ec9b0")
        surface_info = palette.get("surface_info", hover_bg)
        surface_success = palette.get("surface_success", hover_bg)

        config = {
            "auto": {
                "card": getattr(self, "auto_route_card", None),
                "title": getattr(self, "auto_route_card_title", None),
                "desc": getattr(self, "auto_route_card_desc", None),
                "accent": accent,
                "active_bg": surface_info,
            },
            "manual": {
                "card": getattr(self, "manual_route_card", None),
                "title": getattr(self, "manual_route_card_title", None),
                "desc": getattr(self, "manual_route_card_desc", None),
                "accent": success,
                "active_bg": surface_success,
            },
        }

        for key, widgets in config.items():
            card = widgets["card"]
            title = widgets["title"]
            desc = widgets["desc"]
            if card is None:
                continue

            is_active = route == key
            is_hover = hover_route == key
            accent_color = widgets.get("accent", accent)
            active_bg = widgets.get("active_bg", surface_info)
            frame_bg = active_bg if is_active else (hover_bg if is_hover else panel_alt)
            frame_border = accent_color if is_active else border
            title_fg = accent_color if is_active else fg
            desc_fg = fg if is_active else muted

            try:
                card.configure(
                    bg=frame_bg,
                    highlightbackground=frame_border,
                    highlightcolor=frame_border,
                )
            except Exception:
                pass

            for widget, color in ((title, title_fg), (desc, desc_fg)):
                if widget is None:
                    continue
                try:
                    widget.configure(bg=frame_bg, fg=color)
                except Exception:
                    pass

    def _select_free_mode_route(self, route: str):
        normalized_route = self._normalize_workflow_route_value(route)
        if not normalized_route:
            return

        self.workflow_route_var.set(normalized_route)
        self.free_mode_screen_var.set("workflow")
        self._manual_review_active = False
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        self._last_completed_workflow_route = ""

        if normalized_route == "auto":
            self.manual_xml_template_var.set(False)
            self.auto_vehicle_choice_var.set(self._get_auto_vehicle_choice())
        else:
            default_entry_mode = "continue"
            self.manual_entry_mode_var.set(default_entry_mode)
            self.manual_xml_template_var.set(default_entry_mode == "new")
            self.manual_history_run_var.set("")
            if default_entry_mode != "new":
                self.manual_vehicle_assist_var.set(False)
        default_step = "auto_plate_model" if normalized_route == "auto" else "manual_entry"
        self.workflow_step_var.set(default_step)
        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        if normalized_route == "manual":
            self._refresh_manual_review_history_ui()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        self._scroll_left_panel_to_widget(
            getattr(
                self,
                "auto_plate_model_section" if normalized_route == "auto" else "manual_entry_section",
                None,
            )
            or getattr(self, "actions_section", None)
        )
        self._queue_free_mode_session_save()

    def _set_manual_entry_mode(self, mode: str):
        previous_mode = self._get_manual_entry_mode()
        normalized_mode = self._normalize_manual_entry_mode(mode)
        self.workflow_route_var.set("manual")
        self.free_mode_screen_var.set("workflow")
        self.manual_entry_mode_var.set(normalized_mode)
        self.manual_xml_template_var.set(normalized_mode == "new")
        if normalized_mode in {"continue", "import"} and not self._manual_review_active:
            self.manual_history_run_var.set("")
        elif (
            normalized_mode == "new"
            and previous_mode != "new"
            and not self._manual_review_active
            and not self._manual_review_from_auto
            and not self.is_processing
        ):
            self.input_dir_var.set("")
        self._manual_review_active = False
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        if normalized_mode != "new":
            self.manual_vehicle_assist_var.set(False)
        else:
            self._clear_active_annotation_run_context(preserve_input_dir=True)
        self.workflow_step_var.set("manual_entry")
        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_manual_review_history_ui()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        self._scroll_left_panel_to_widget(
            getattr(self, "manual_entry_section", None) or getattr(self, "actions_section", None)
        )
        self._queue_free_mode_session_save()

    def _on_manual_entry_mode_change(self):
        self._set_manual_entry_mode(self.manual_entry_mode_var.get())

    def _on_manual_start_new_toggle(self):
        self._on_manual_entry_mode_change()

    def _on_auto_vehicle_skip_toggle(self):
        normalized_choice = self._normalize_auto_vehicle_choice(self.auto_vehicle_choice_var.get())
        self.workflow_route_var.set("auto")
        self.free_mode_screen_var.set("workflow")
        self.auto_vehicle_choice_var.set(normalized_choice)
        self.manual_xml_template_var.set(False)
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        if normalized_choice == "skip":
            self.mode_var.set("B: Tylko tablice")
        else:
            self.mode_var.set("C: Pojazdy + tablice")
        self._refresh_auto_vehicle_choice_ui()
        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()

    def _refresh_auto_vehicle_choice_ui(self):
        skip_check = getattr(self, "auto_vehicle_choice_skip_check", None)
        if skip_check is None:
            return

        try:
            skip_check.grid_configure(row=0, column=0, columnspan=1, sticky="w")
        except Exception:
            pass

    def _refresh_run_output_info(self, run_dir: Path | None = None):
        if run_dir is None:
            run_dir = self._get_preferred_annotation_run_dir(require_xml=True)
        if run_dir is None:
            self.run_output_info_var.set("")
            return

        pretty_path = self._format_workspace_relative_path(run_dir)
        self.run_output_info_var.set(
            f"Ostatni run anotacji Z2 jest zapisany w: {pretty_path}"
        )

    def _open_current_run_dir(self):
        run_dir = self._get_preferred_annotation_run_dir(require_xml=True)
        if run_dir is None:
            messagebox.showinfo("Brak runu anotacji", "Najpierw utworz albo otworz run anotacji Z2.")
            return

        try:
            if os.name == "nt":
                os.startfile(str(run_dir))
            else:
                messagebox.showinfo("Info", f"Folder runu anotacji:\n{run_dir}")
        except Exception as e:
            messagebox.showerror("Nie mozna otworzyc folderu", f"{run_dir}\n\n{e}")

    def _jump_to_export_section(self):
        campaign_context = not self._is_free_mode_session_context()

        if self._manual_review_active and not self._ensure_preview_edits_saved("przejscie do splitu i eksportu"):
            return

        self._dataset_export_completed = False
        self._manual_review_export_ready = True
        if not campaign_context:
            self.free_mode_screen_var.set("export")
        self._refresh_plate_dataset_export_sources()
        self._refresh_free_mode_workflow_ui()
        self._scroll_left_panel_to_widget(getattr(self, "export_section", None))
        if not self._manual_review_active:
            try:
                self.app.pulse_button(self.export_plate_dataset_btn, pulses=6, interval_ms=220, keep_emphasis=True)
            except Exception:
                pass

    def _open_existing_run_for_manual_review(
        self,
        run_dir: Path | None = None,
        *,
        allow_fallback: bool = True,
        from_auto: bool = False,
        show_dialog: bool = True,
    ) -> bool:
        target_run_dir = self._resolve_safe_annotation_run_dir(
            run_dir if run_dir is not None else (
                self._get_preferred_annotation_run_dir(require_xml=True)
                if allow_fallback
                else None
            ),
            require_xml=True,
        )
        if target_run_dir is None:
            messagebox.showwarning(
                "Brak runu anotacji do korekty",
                "Nie znaleziono jeszcze zadnego runu autoanotacji Z2 z annotations.xml do kontynuacji."
            )
            return False

        if not self._restore_preview_from_annotation_run(target_run_dir):
            messagebox.showerror(
                "Blad podgladu",
                f"Nie udalo sie otworzyc runu anotacji do korekty:\n{target_run_dir}"
            )
            return False

        self.workflow_route_var.set("manual")
        self.manual_entry_mode_var.set("continue")
        self.workflow_step_var.set("manual_history")
        self.free_mode_screen_var.set("manual_review")
        self.manual_xml_template_var.set(False)
        self.manual_vehicle_assist_var.set(False)
        self._manual_review_active = True
        self._manual_review_from_auto = bool(from_auto)
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        self._last_completed_workflow_route = "manual"

        if self.current_input_dir is not None:
            self.input_dir_var.set(str(self.current_input_dir))

        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_run_output_info()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        self._remember_manual_review_run(
            target_run_dir,
            source=("auto" if from_auto else "manual"),
            created_at=str(
                self._load_annotation_run_manifest(target_run_dir).get("generated_at")
                or self._load_annotation_run_manifest(target_run_dir).get("completed_at")
                or ""
            ).strip(),
        )
        self._queue_free_mode_session_save()

        if from_auto:
            self._set_post_annotation_hint(
                "Jestes w torze recznej korekty. Del usuwa zdjecie z dysku i z XML, a poprawki polygonow sa od razu zapisywane.",
                "muted",
            )

        if show_dialog:
            messagebox.showinfo(
                "Korekta reczna",
                f"Otworzono run anotacji do korekty recznej:\n{target_run_dir}"
            )
        return True

    def _open_existing_run_for_campaign_review(
        self,
        run_dir: Path | None = None,
        *,
        iteration_target: str | None = None,
        manual_template: bool = False,
    ) -> bool:
        target_run_dir = self._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        if target_run_dir is None:
            return False

        if not self._restore_preview_from_annotation_run(target_run_dir):
            return False

        self._apply_campaign_step2_workflow_preset(
            iteration_target=iteration_target,
            manual_template=manual_template,
        )
        self.workflow_route_var.set("manual")
        self.manual_entry_mode_var.set("continue")
        self._manual_review_active = True
        self._manual_review_from_auto = False
        self._manual_review_export_ready = False
        self._dataset_export_completed = False
        self._last_completed_workflow_route = ""
        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_run_output_info()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        return True

    def _enter_manual_review_from_auto(self):
        self._open_existing_run_for_manual_review(from_auto=True, show_dialog=False)

    def _refresh_free_mode_workflow_ui(self):
        if bool(getattr(self, "_workflow_ui_refresh_in_progress", False)):
            self._workflow_ui_refresh_pending = True
            return

        self._workflow_ui_refresh_in_progress = True
        self._refresh_workflow_route_cards()
        preferred_run_dir = self._get_preferred_annotation_run_dir(require_xml=True)
        self._refresh_run_output_info(preferred_run_dir)

        route = self._get_workflow_route()
        manual_entry_mode = self._get_manual_entry_mode()
        auto_vehicle_choice = self._get_auto_vehicle_choice()
        plate_model_selected = bool(str(self.plate_custom_var.get() or "").strip())
        input_dir_value = str(self.input_dir_var.get() or "").strip()
        input_dir_ready = bool(input_dir_value and Path(input_dir_value).exists())
        vehicle_assist_enabled = self._manual_vehicle_assist_enabled()
        has_existing_run = preferred_run_dir is not None
        manual_setup = route == "manual" and manual_entry_mode == "new"
        manual_continue = route == "manual" and manual_entry_mode == "continue"
        manual_import = route == "manual" and manual_entry_mode == "import"
        manual_run_already_created = bool(manual_setup and self._has_active_manual_template_run())
        current_step = self._coerce_workflow_step()
        if self.workflow_step_var.get() != current_step:
            self.workflow_step_var.set(current_step)
        manual_review_active = bool(self._manual_review_active and has_existing_run)
        manual_review_from_auto = bool(manual_review_active and self._manual_review_from_auto)
        auto_completed = bool(
            route == "auto"
            and has_existing_run
            and not self.is_processing
            and self._last_completed_workflow_route == "auto"
        )
        campaign_context = not self._is_free_mode_session_context()
        if campaign_context and not route and manual_review_active:
            route = "manual"
        campaign_stage = 0
        campaign_iteration_target = ""
        if campaign_context:
            try:
                from ..campaign_manager import CAMPAIGN
                campaign_stage = int(CAMPAIGN.get_current_step() or 0)
                campaign_iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
            except Exception:
                campaign_stage = 0
                campaign_iteration_target = ""

        free_mode_screen = ""
        if not campaign_context:
            free_mode_screen = self._coerce_free_mode_screen()
            if self.free_mode_screen_var.get() != free_mode_screen:
                self.free_mode_screen_var.set(free_mode_screen)

        if campaign_context:
            campaign_stage2 = int(campaign_stage or 0) == 2
            show_export_followup = bool(self._manual_review_export_ready)
            show_auto_followup = bool(
                auto_completed
                and not manual_review_active
                and not show_export_followup
            )
            show_manual_review_followup = bool(manual_review_active and not show_export_followup)
            show_route_choice = bool(
                campaign_stage2
                and campaign_iteration_target in {"plate", "char"}
                and not show_manual_review_followup
                and not show_auto_followup
                and not show_export_followup
            )
            show_stage_export_cta = bool(
                campaign_stage2
                and campaign_iteration_target == "plate"
                and not show_export_followup
                and (manual_review_active or auto_completed)
            )
            compact_export_followup = False
            show_workflow_steps = bool(
                (
                    route
                    and not show_manual_review_followup
                    and not auto_completed
                    and not show_export_followup
                )
                or (
                    campaign_stage2
                    and not has_existing_run
                    and not show_manual_review_followup
                    and not show_auto_followup
                    and not show_export_followup
                )
            )
        else:
            show_route_choice = free_mode_screen == "route_choice"
            show_export_followup = free_mode_screen == "export"
            show_auto_followup = free_mode_screen == "auto_summary"
            show_manual_review_followup = bool(
                free_mode_screen == "manual_review" and manual_review_active
            )
            show_stage_export_cta = False
            compact_export_followup = bool(show_export_followup)
            show_workflow_steps = bool(free_mode_screen == "workflow" and route)

        show_campaign_context_header = bool(
            campaign_context
            and not show_workflow_steps
            and bool(route or manual_review_active or has_existing_run or campaign_stage >= 3)
        )

        show_nav_panel = bool(
            (not campaign_context)
            and (
                show_workflow_steps
                or show_auto_followup
                or show_export_followup
                or (free_mode_screen == "manual_review" and manual_review_active)
            )
        )
        show_workflow_entry_shell = bool(
            show_route_choice
            or show_workflow_steps
            or show_nav_panel
            or show_campaign_context_header
        )
        show_right_panel = bool(
            campaign_context
            and int(campaign_stage or 0) == 2
            and not show_route_choice
            and not show_workflow_steps
            and not show_export_followup
        )
        self._annotation_right_panel_visible = show_right_panel
        self._sync_main_pane_right_panel_visibility()
        if show_workflow_steps:
            nav_anchor = self.actions_section
        elif show_export_followup:
            nav_anchor = self.export_section
        elif free_mode_screen == "manual_review" and show_stage_export_cta:
            nav_anchor = self.manual_stage_export_box
        elif show_manual_review_followup:
            nav_anchor = self.manual_stage_section
        elif show_auto_followup:
            nav_anchor = self.followup_section
        else:
            nav_anchor = self.workflow_entry_section
        self._set_widget_packed(
            self.workflow_entry_shell,
            show_workflow_entry_shell,
            fill=tk.X,
            pady=(0, 16),
        )
        self._set_widget_packed(
            self.workflow_nav_panel,
            False,
        )
        self._set_widget_packed(
            self.workflow_entry_section,
            show_route_choice,
            fill=tk.X,
            before=(self.actions_section if show_workflow_steps else self.workflow_nav_panel),
        )
        self._set_widget_packed(self.workflow_entry_separator, False)
        self._set_widget_packed(self.workflow_intro_lbl, False)
        self._set_widget_packed(self.source_section, False)
        self._set_widget_packed(self.source_section_separator, False)
        self._set_widget_packed(
            self.actions_section,
            (show_workflow_steps or show_campaign_context_header),
            fill=tk.X,
            before=self.workflow_nav_panel,
        )
        self._set_widget_packed(self.actions_section_separator, False)
        self._set_widget_packed(self.followup_section, show_auto_followup, fill=tk.X)
        self._set_widget_packed(
            self.followup_actions_row,
            show_auto_followup and campaign_context,
            fill=tk.X,
            pady=(0, 8),
        )
        self._set_widget_packed(
            self.manual_stage_section,
            show_manual_review_followup,
            fill=tk.X,
        )
        self._set_widget_packed(
            self.manual_stage_separator,
            show_stage_export_cta,
            fill=tk.X,
            pady=(18, 20),
        )
        self._set_widget_packed(
            self.manual_stage_export_box,
            show_stage_export_cta,
            fill=tk.X,
            pady=(0, 12),
        )
        try:
            if campaign_context:
                self.manual_stage_export_title_lbl.configure(text="Trening modelu YOLO Pose")
                self.manual_stage_export_help_lbl.configure(
                    text=(
                        "Jesli chcesz od razu trenowac model YOLO Pose wykrywajacy obrys tablic "
                        "rejestracyjnych, ustaw split i wyeksportuj dataset. Potem przejdz do Z4, "
                        "gdzie uruchomisz trening."
                    )
                )
            elif manual_review_active:
                self.manual_stage_export_title_lbl.configure(text="Trening modelu YOLO Pose")
                self.manual_stage_export_help_lbl.configure(
                    text=(
                        "Jesli korekta runu anotacji jest gotowa i chcesz od razu trenowac model "
                        "YOLO Pose wykrywajacy obrys tablic rejestracyjnych, ustaw split i "
                        "wyeksportuj dataset. Potem przejdz do Z4, gdzie uruchomisz trening."
                    )
                )
            else:
                self.manual_stage_export_title_lbl.configure(text="Trening modelu YOLO Pose")
                self.manual_stage_export_help_lbl.configure(
                    text=(
                        "Jesli chcesz od razu trenowac model YOLO Pose wykrywajacy obrys tablic "
                        "rejestracyjnych, ustaw split i wyeksportuj dataset. Potem przejdz do Z4, "
                        "gdzie uruchomisz trening."
                    )
                )
        except Exception:
            pass
        self._set_widget_packed(
            self.export_section,
            show_export_followup,
            fill=tk.X,
        )
        self._set_widget_packed(
            self.export_back_btn,
            show_export_followup and campaign_context,
            fill=tk.X,
            pady=(10, 0),
        )
        self._set_widget_packed(
            self.export_plate_dataset_btn,
            show_export_followup and campaign_context,
            fill=tk.X,
        )
        self._set_widget_packed(
            self.workflow_nav_panel,
            show_nav_panel,
            fill=tk.X,
            pady=(12, 0),
            after=nav_anchor,
        )

        self._set_widget_packed(self.route_selector_frame, False)
        self._set_widget_packed(
            self.run_title_lbl,
            show_workflow_steps or show_campaign_context_header or ((not campaign_context) and show_nav_panel),
            anchor=tk.W,
            fill=tk.X,
        )
        self._set_widget_packed(
            self.route_badge_lbl,
            (show_workflow_steps or show_campaign_context_header),
            anchor=tk.W,
            fill=tk.X,
            pady=(0, 2),
        )
        self._set_widget_packed(
            self.route_summary_lbl,
            (show_workflow_steps or show_campaign_context_header),
            anchor=tk.W,
            fill=tk.X,
            pady=(0, 8),
        )
        self._set_widget_packed(
            self.workflow_action_hint_lbl,
            (show_workflow_steps or show_campaign_context_header)
            and bool(str(self.workflow_action_hint_var.get() or "").strip()),
            anchor=tk.W,
            fill=tk.X,
            pady=(0, 8),
        )
        if campaign_context and campaign_stage >= 3:
            try:
                self.return_to_campaign_btn.configure(
                    text=(f"Wroc do wizarda (E{campaign_stage})" if campaign_stage <= 4 else "Wroc do wizarda")
                )
            except Exception:
                pass
        self._set_widget_packed(
            self.return_to_campaign_btn,
            bool(show_campaign_context_header and campaign_stage >= 3),
            anchor=tk.W,
            fill=tk.X,
            pady=(0, 8),
        )
        self._set_widget_packed(
            self.auto_plate_model_section,
            show_workflow_steps and current_step == "auto_plate_model",
            fill=tk.X,
            pady=(0, 10),
        )
        self._refresh_auto_vehicle_choice_ui()
        self._set_widget_packed(
            self.auto_vehicle_choice_section,
            show_workflow_steps and current_step == "auto_vehicle_choice",
            fill=tk.X,
            pady=(0, 10),
        )
        self._set_widget_packed(
            self.manual_entry_section,
            show_workflow_steps and current_step == "manual_entry",
            fill=tk.X,
            pady=(0, 10),
        )
        self._set_widget_packed(
            self.manual_history_section,
            show_workflow_steps
            and current_step == "manual_history"
            and manual_continue,
            fill=tk.X,
            pady=(0, 10),
        )
        self._set_widget_packed(
            self.manual_history_open_btn,
            False,
        )
        self._set_widget_packed(
            self.manual_history_import_btn,
            False,
        )
        self._set_widget_packed(
            self.manual_xml_template_hint_lbl,
            False,
        )
        self._set_widget_packed(
            self.workflow_manual_vehicle_assist_check,
            show_workflow_steps and current_step == "manual_input" and manual_setup,
            anchor=tk.W,
            pady=(6, 2),
        )
        self._set_widget_packed(
            self.workflow_manual_vehicle_assist_hint_lbl,
            show_workflow_steps and current_step == "manual_input" and manual_setup,
            fill=tk.X,
            pady=(0, 6),
        )
        self._set_widget_packed(
            self.workflow_conf_section,
            show_workflow_steps
            and (
                current_step == "auto_conf"
                or current_step == "manual_conf"
                or (
                    current_step == "manual_input"
                    and manual_setup
                    and vehicle_assist_enabled
                )
            ),
            fill=tk.X,
            pady=(0, 10),
        )
        self._set_widget_packed(
            self.workflow_vehicle_model_section,
            show_workflow_steps
            and (
                current_step == "auto_vehicle_model"
                or current_step == "manual_vehicle_model"
                or (
                    current_step == "manual_input"
                    and manual_setup
                    and vehicle_assist_enabled
                )
            ),
            fill=tk.X,
            pady=(0, 10),
        )
        show_campaign_auto_input_section = bool(
            campaign_context
            and current_step == "auto_start"
            and self._get_workflow_route() == "auto"
        )
        self._set_widget_packed(
            self.workflow_input_section,
            bool(show_workflow_steps and current_step in {"auto_input", "manual_input"}) or show_campaign_auto_input_section,
            fill=tk.X,
            pady=(0, 10),
        )
        self._refresh_campaign_workflow_input_lock_state(
            campaign_context=campaign_context,
            current_step=current_step,
        )
        self._refresh_campaign_manual_reuse_option_ui()
        self._set_widget_packed(
            self.run_output_info_lbl,
            show_auto_followup,
            fill=tk.X,
            pady=(0, 8),
        )
        self._set_widget_packed(
            self.open_run_dir_btn,
            show_auto_followup,
            anchor=tk.W,
            pady=(0, 8),
        )

        self._set_widget_packed(self.right_scroll_host, False)
        self._set_widget_packed(self.approve_btn_row, show_right_panel, fill=tk.X, pady=(8, 0))
        self._set_widget_packed(self.mode_title_lbl, False)
        self._set_widget_packed(self.mode_combo, False)
        self._set_widget_packed(self.mode_hint_lbl, False)
        self._set_widget_packed(self.pla_frame, False)
        self._set_widget_packed(self.veh_frame, False)
        self._set_widget_packed(self.param_frame, False)
        self._refresh_manual_review_followup_ui(
            from_auto=manual_review_from_auto,
            active_run=manual_review_active,
        )
        self._refresh_preview_workspace_visibility(manual_review_active=manual_review_active)
        self._refresh_export_followup_ui(compact_active_run=compact_export_followup)
        try:
            if campaign_context:
                if str(self.jump_to_export_btn.winfo_manager()) == "grid":
                    self.jump_to_export_btn.grid_remove()
                self.enter_manual_review_btn.grid_configure(column=0, columnspan=2, sticky="ew", padx=(0, 0))
            else:
                if str(self.jump_to_export_btn.winfo_manager()) != "grid":
                    self.jump_to_export_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))
                self.enter_manual_review_btn.grid_configure(column=0, columnspan=1, sticky="ew", padx=(0, 6))
        except Exception:
            pass
        try:
            self.manual_stage_export_btn.configure(
                state=(tk.NORMAL if show_stage_export_cta and not self.is_processing else tk.DISABLED)
            )
        except Exception:
            pass
        try:
            self.export_back_btn.configure(
                state=(tk.NORMAL if show_export_followup and not self.is_processing else tk.DISABLED)
            )
        except Exception:
            pass
        self._refresh_manual_stage_export_box_style()
        show_progress_ui = bool(
            self.is_processing
            or show_auto_followup
            or manual_review_active
            or show_export_followup
        )
        self._set_widget_packed(
            self.progress_info_row,
            show_progress_ui,
            fill=tk.X,
            pady=(10, 4),
        )
        self._set_widget_packed(
            self.progress,
            show_progress_ui,
            fill=tk.X,
            pady=(0, 2),
        )

        show_start_controls = bool(
            show_workflow_steps
            and (
                current_step in {"auto_start", "manual_start"}
                or (
                    campaign_context
                    and current_step in {"auto_input", "manual_input"}
                )
            )
        )
        self._set_widget_packed(
            self.workflow_start_section,
            show_start_controls,
            fill=tk.X,
            pady=(0, 10),
        )
        self._set_widget_packed(
            self.workflow_start_title_lbl,
            show_start_controls,
            anchor=tk.W,
            fill=tk.X,
        )
        show_nav_controls = show_workflow_steps and bool(current_step) and not self.is_processing
        self._set_widget_packed(
            self.start_btn_row,
            show_start_controls,
            fill=tk.X,
            pady=(6, 0),
        )
        self._set_widget_packed(
            self.workflow_start_action_hint_lbl,
            show_start_controls and bool(str(self.workflow_action_hint_var.get() or "").strip()),
            anchor=tk.W,
            fill=tk.X,
            pady=(6, 0),
        )

        start_enabled = not self.is_processing and bool(route)
        start_text = "Wybierz tor"
        if route == "auto":
            if not plate_model_selected:
                start_enabled = False
                start_text = "Wybierz model"
            elif not input_dir_ready:
                start_enabled = False
                start_text = "Wybierz obrazy"
            elif auto_vehicle_choice == "skip":
                start_text = "Uruchom autoanotację tablic"
            else:
                start_text = "Uruchom autoanotację tablic + pojazdów"
        elif manual_setup:
            if manual_run_already_created:
                start_enabled = False
                start_text = "Run istnieje"
            elif not input_dir_ready:
                start_enabled = False
                start_text = "Wybierz obrazy"
            else:
                start_text = (
                    "Utwórz XML + boxy"
                    if self._manual_vehicle_assist_enabled()
                    else "Utwórz XML"
                )

        try:
            self.start_btn.configure(text=start_text, state=(tk.NORMAL if start_enabled else tk.DISABLED))
        except Exception:
            pass

        steps = self._get_current_workflow_steps()
        current_index = steps.index(current_step) if current_step in steps else -1
        next_text = "Dalej"
        if campaign_context:
            back_enabled = False
            next_enabled = False
        elif free_mode_screen == "workflow":
            back_enabled = bool(
                not self.is_processing
                and (
                    self._manual_review_export_ready
                    or self._manual_review_active
                    or bool(route)
                )
            )
            next_enabled = bool(
                self._dataset_export_completed
            ) or bool(
                show_nav_controls and (not show_start_controls) and self._is_workflow_step_complete(current_step)
            )
            if self._dataset_export_completed:
                next_text = "Powrot"
            if route == "manual" and current_step == "manual_entry" and not self._dataset_export_completed:
                next_text = "Dalej"
            elif route == "manual" and current_step == "manual_history" and not self._dataset_export_completed:
                next_text = "Dalej" if manual_review_active else "Otworz run"
        elif free_mode_screen == "auto_summary":
            back_enabled = bool(not self.is_processing)
            next_enabled = bool(not self.is_processing and has_existing_run)
            next_text = "Korekta"
        elif free_mode_screen == "manual_review":
            back_enabled = bool(not self.is_processing)
            next_enabled = bool(not self.is_processing)
            next_text = "Eksport"
        elif free_mode_screen == "export":
            back_enabled = bool(not self.is_processing)
            next_enabled = bool(not self.is_processing)
            if self._dataset_export_completed:
                next_text = "Zakoncz"
            else:
                next_text = "Eksportuj"
        else:
            back_enabled = False
            next_enabled = False
        try:
            self.workflow_back_btn.configure(
                state=(tk.NORMAL if back_enabled else tk.DISABLED),
                text="Wstecz",
                width=NAV_BUTTON_WIDTH,
            )
            self.workflow_next_btn.configure(
                state=(tk.NORMAL if next_enabled else tk.DISABLED),
                text=next_text,
                width=NAV_BUTTON_WIDTH,
            )
        except Exception:
            pass

        try:
            self.stop_btn.configure(
                text="ZATRZYMAJ",
                command=self._stop_annotation,
                state=(tk.NORMAL if self.is_processing else tk.DISABLED),
            )
        except Exception:
            pass

        self._refresh_workflow_button_styles()
        self._refresh_workflow_step_cards()

        self._workflow_ui_refresh_in_progress = False
        if bool(getattr(self, "_workflow_ui_refresh_pending", False)):
            self._workflow_ui_refresh_pending = False
            try:
                self.frame.after_idle(self._refresh_free_mode_workflow_ui)
            except Exception:
                self._refresh_free_mode_workflow_ui()

    def _manual_xml_template_enabled(self) -> bool:
        return bool(self.manual_xml_template_var.get())

    def _manual_vehicle_assist_enabled(self) -> bool:
        return self._manual_xml_template_enabled() and bool(self.manual_vehicle_assist_var.get())

    def _return_to_campaign_wizard(self):
        try:
            from ..campaign_manager import CAMPAIGN
        except Exception:
            return

        if not CAMPAIGN.get_active_project_name():
            return

        stage_num = int(CAMPAIGN.get_current_step() or 0)
        stage_label = f"E{stage_num}" if stage_num > 0 else "aktualnego etapu"

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab is not None:
                campaign_tab._refresh_dashboard()
        except Exception:
            pass

        try:
            self.app.select_tab("campaign")
            self.app.update_campaign_tab_access()
            self.app.update_status(
                f"Wracam do wizarda na etap {stage_label}.",
                "info",
            )
        except Exception as e:
            logger.debug(f"Nie udalo sie wrocic do wizarda kampanii: {e}")

    def _refresh_left_panel_route_copy(self):
        manual_enabled = self._manual_xml_template_enabled()
        vehicle_assist_enabled = self._manual_vehicle_assist_enabled()
        campaign_context = not self._is_free_mode_session_context()

        if manual_enabled:
            badge_text = "Aktywny tor: ręczna anotacja tablic"
            badge_tone = "warning"
            followup_title = "3. Ręczna anotacja i iteracje"
            if vehicle_assist_enabled:
                route_text = (
                    "Ten przycisk przygotuje nowy run ręcznej anotacji Z2 do ręcznego rysowania poligonów tablic "
                    "i doda boksy pojazdów jako pomoc w podglądzie."
                )
            else:
                route_text = (
                    "Ten przycisk przygotuje nowy run ręcznej anotacji Z2 do ręcznego rysowania poligonów tablic. "
                    "Pełna autoanotacja YOLO tablic pozostaje w tym torze wyłączona."
                )
            route_tone = "muted"
            followup_text = (
                "Po utworzeniu runu ręcznej anotacji poprawiasz poligony w podglądzie i zapisujesz zmiany do XML. "
                "Stage poniżej służy tylko do kolejnych ręcznych iteracji."
            )
            if campaign_context:
                export_text = (
                    "To krok opcjonalny. Z gotowego runu anotacji Z2 możesz zbudować dataset YOLO Pose "
                    "i przekazać go do [Z4] jako materiał do treningu modelu tablic. "
                    "Warto go uruchomić wtedy, gdy chcesz od razu trenować kolejną wersję modelu na wynikach tej iteracji. "
                    "Nie jest to wymagane do domknięcia E2."
                )
            else:
                export_text = (
                    "Eksport uruchamiasz dopiero z gotowego runu anotacji, po zapisaniu zmian w annotations.xml."
                )
            start_text = "Utwórz XML"
        else:
            badge_text = "Aktywny tor: autoanotacja"
            badge_tone = "success"
            followup_title = "3. Ręczne poprawki po autoanotacji"
            route_text = (
                "Ten przycisk uruchomi wybrany tryb YOLO i zapisze gotowy run anotacji Z2. "
                "Ręczne poprawki wykonujesz dopiero w sekcji 3."
            )
            route_tone = "muted"
            followup_text = (
                "Po autoanotacji tutaj poprawiasz wynik ręcznie albo przygotowujesz stage "
                "do kolejnej paczki. Ten blok nie zmienia działania głównego przycisku."
            )
            if campaign_context:
                export_text = (
                    "To krok opcjonalny. Z gotowego runu Z2 możesz zbudować dataset YOLO Pose "
                    "i od razu przekazać go do [Z4] jako materiał do dalszego treningu modelu tablic. "
                    "Ten eksport ma sens wtedy, gdy chcesz wykorzystać wyniki tej iteracji do uczenia kolejnej wersji modelu. "
                    "Nie jest to wymagane do domknięcia E2."
                )
            else:
                export_text = (
                    "Eksport datasetu jest osobnym krokiem z ostatniego albo ręcznie wskazanego runu anotacji Z2."
                )
            start_text = "Uruchom autoanotację"

        self._set_inline_label_state(self.route_badge_lbl, text=badge_text, tone=badge_tone, emphasis=True)
        self._set_inline_label_state(self.route_summary_lbl, text=route_text, tone=route_tone, emphasis=False)
        self._set_inline_label_state(self.followup_intro_lbl, text=followup_text, tone="muted", emphasis=False)
        self._set_inline_label_state(self.export_intro_lbl, text=export_text, tone="muted", emphasis=False)
        try:
            self.followup_title_lbl.configure(text=followup_title)
        except Exception:
            pass

        try:
            self.start_btn.configure(text=start_text)
        except Exception:
            pass

    def _update_manual_xml_template_ui(self):
        manual_enabled = self._manual_xml_template_enabled()
        vehicle_assist_enabled = self._manual_vehicle_assist_enabled()
        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()

        if manual_enabled:
            if getattr(self, "manual_vehicle_assist_check", None) is not None and not str(self.manual_vehicle_assist_check.winfo_manager()):
                self.manual_vehicle_assist_check.pack(
                    anchor=tk.W,
                    pady=(0, 2),
                    padx=(18, 0),
                    after=self.manual_route_radio,
                )
            if getattr(self, "manual_vehicle_assist_hint_lbl", None) is not None and not str(self.manual_vehicle_assist_hint_lbl.winfo_manager()):
                self.manual_vehicle_assist_hint_lbl.pack(
                    anchor=tk.W,
                    fill=tk.X,
                    pady=(0, 6),
                    padx=(18, 0),
                    after=self.manual_vehicle_assist_check,
                )

            if vehicle_assist_enabled:
                self.manual_vehicle_assist_hint_var.set(
                    f"Dotyczy tylko nowego runu ręcznej anotacji po kliknięciu {self._get_step2_start_action_reference()}. Z2 użyje modelu pojazdów, zapisze boxy aut do nowego XML i pozwoli przechodzić po nich klawiszem Spacja."
                )
                self.manual_xml_template_hint_var.set(
                    "Z2 pominie model tablic, ale przygotuje annotations.xml dla wszystkich obrazów z auto-boksami pojazdów. "
                    "Spacja kadruje i przełącza kolejne pojazdy, a ręcznie dodane tablice zapisują się z etykietą 'plate'. "
                    "Każde ponowne uruchomienie tworzy nowy run anotacji run_* i nie nadpisuje starszych XML-i; starsze runy zostają na dysku."
                )
                if hasattr(self, "start_btn"):
                    self.start_btn.configure(text="Utwórz XML + boxy")
                self._set_inline_label_state(self.manual_vehicle_assist_hint_lbl, tone="info", emphasis=False)
            else:
                self.manual_vehicle_assist_hint_var.set(
                    "Ten checkbox zadziała dopiero dla nowego runu ręcznej anotacji po kliknięciu głównego przycisku. Nie modyfikuje już utworzonych XML-i."
                )
                self.manual_xml_template_hint_var.set(
                    "Z2 pominie YOLO dla tablic i przygotuje run ręcznej anotacji z pustym annotations.xml dla wszystkich obrazów. "
                    "Potem dodasz poligony tablic ręcznie w podglądzie. Ręcznie dodane tablice zapisują się w XML z etykietą 'plate'. "
                    "Każde ponowne uruchomienie tworzy nowy run anotacji run_* i nie nadpisuje starszych XML-i; starsze runy zostają na dysku."
                )
                if hasattr(self, "start_btn"):
                    self.start_btn.configure(text="Utwórz XML")
                self._set_inline_label_state(self.manual_vehicle_assist_hint_lbl, tone="muted", emphasis=False)
            self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone="warning", emphasis=False)
            self._refresh_manual_plate_stage_ui()
            return

        self.manual_vehicle_assist_var.set(False)
        self.manual_vehicle_assist_hint_var.set("")
        for widget in (
            getattr(self, "manual_vehicle_assist_check", None),
            getattr(self, "manual_vehicle_assist_hint_lbl", None),
        ):
            if widget is not None:
                try:
                    widget.pack_forget()
                except Exception:
                    pass
        self.manual_xml_template_hint_var.set(
            (
                "Ten etap uruchomi modele YOLO, zapisze nowy run autoanotacji Z2, a potem od razu otworzy wynik do ręcznej korekty polygonów tablic."
                if campaign_context
                else "Standardowy tryb Z2: uruchamia modele YOLO i zapisuje run autoanotacji tablic Z2."
            )
        )
        if hasattr(self, "start_btn"):
            self.start_btn.configure(text="Uruchom autoanotację")
        self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone="muted", emphasis=False)
        self._refresh_manual_plate_stage_ui()
        return

        if manual_enabled:
            self.manual_xml_template_hint_var.set(
                "Z2 pominie YOLO i przygotuje run recznej anotacji z pustym annotations.xml dla wszystkich obrazow. "
                "Potem dodasz polygony tablic ręcznie w podglądzie. "
                "Ręcznie dodane tablice zapisują się w XML z etykietą 'plate'."
            )
            if hasattr(self, "start_btn"):
                self.start_btn.configure(text="UTWÓRZ XML DO ANOTACJI RĘCZNEJ")
            self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone="warning", emphasis=False)
        else:
            self.manual_xml_template_hint_var.set(
                "Standardowy tryb Z2: uruchamia modele YOLO i zapisuje run autoanotacji tablic Z2."
            )
            if hasattr(self, "start_btn"):
                self.start_btn.configure(text="STARTUJ AUTOANOTACJĘ")
            self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone="muted", emphasis=False)

    def _refresh_left_panel_route_copy(self):
        route = self._get_workflow_route()
        manual_entry_mode = self._get_manual_entry_mode()
        manual_import = route == "manual" and manual_entry_mode == "import"
        vehicle_assist_enabled = self._manual_vehicle_assist_enabled()
        auto_vehicle_choice = self._get_auto_vehicle_choice()
        has_existing_run = self._get_preferred_annotation_run_dir(require_xml=True) is not None
        plate_model_selected = bool(str(self.plate_custom_var.get() or "").strip())
        campaign_context = not self._is_free_mode_session_context()
        current_step = self._coerce_workflow_step()
        current_index, total_steps = self._get_workflow_progress_display()
        has_manual_history = bool(self._manual_review_history_entries)
        auto_completed = bool(
            route == "auto"
            and has_existing_run
            and not self.is_processing
            and self._last_completed_workflow_route == "auto"
        )
        manual_review_active = bool(self._manual_review_active and has_existing_run)

        self.workflow_intro_var.set("")

        badge_text = "Wybierz tor pracy"
        badge_tone = "muted"
        route_text = "Na starcie widzisz tylko dwa kafle: autoanotacja albo anotacja ręczna."
        route_tone = "muted"
        action_text = ""
        auto_choice_hint = ""
        manual_hint = ""
        manual_hint_tone = "muted"
        manual_template_hint = ""
        manual_template_tone = "muted"
        manual_vehicle_hint = ""
        manual_vehicle_tone = "muted"
        followup_title = "3. Co dalej po autoanotacji"
        followup_text = (
            "Po zakończeniu runu anotacji Z2 odblokujesz tutaj przejście do korekty ręcznej."
        )
        export_text = "Split i eksport są osobnym krokiem na gotowym runie anotacji Z2."
        workflow_conf_title = "2. Ustaw confidence"
        workflow_conf_hint = ""
        workflow_vehicle_title = "Model pojazdów (YOLO Box)"
        workflow_vehicle_hint = ""
        workflow_input_title = "Folder obrazów"
        workflow_input_hint = "Najpierw wybierz folder z obrazami, na których ma pracować aktualny tor Z2."
        workflow_start_title = "Uruchom proces Z2"
        manual_entry_title = "1. Wybierz tor recznej anotacji"
        run_title = "Kreator Z2"

        if route == "auto":
            run_title = "Autoanotacja i korekta tablic" if campaign_context else "Autoanotacja tablic"
            badge_text = "Aktywny tor: przygotowanie tablic" if campaign_context else "Aktywny tor: autoanotacja tablic"
            badge_tone = "success"
            route_tone = "muted"
            workflow_conf_title = "2. Ustaw pewność detekcji"
            workflow_conf_hint = (
                "Ten próg dotyczy bieżącego runu anotacji Z2. Po wyborze modelu tablic możesz od razu go dopasować."
            )
            workflow_vehicle_title = "3a. Wskaż model pojazdów (YOLO Box)"
            workflow_vehicle_hint = (
                "Ten model jest opcjonalny. Jeśli go pominiesz, run autoanotacji Z2 wykona tylko autoanotację tablic."
            )
            workflow_input_title = "4. Wskaż folder obrazów"
            workflow_input_hint = (
                "To przedostatni krok przed uruchomieniem autoanotacji."
                if not campaign_context
                else "To paczka obrazów tej iteracji. Opcjonalnie możesz tu też dołączyć ręcznie anotowane zdjęcia z wcześniejszych iteracji, a po uruchomieniu runu od razu przejdziesz do ręcznej korekty wyniku."
            )
            workflow_start_title = (
                "5. Uruchom autoanotację i przejdź do korekty"
                if campaign_context
                else "5. Uruchom proces autoanotacji"
            )
            if not plate_model_selected:
                route_text = "Najpierw wskaż model tablic YOLO Pose."
                action_text = "Po zapisaniu ścieżki do modelu tablic odblokujesz kolejne kroki konfiguracji."
            elif auto_vehicle_choice == "skip":
                if campaign_context:
                    route_text = "Najpierw uruchomisz autoanotację samych tablic, opcjonalnie także na dołączonych ręcznych zdjęciach z wcześniejszych iteracji, a potem sprawdzisz i poprawisz wynik ręcznie w tym samym Z2."
                    action_text = "Po zapisaniu runu Z2 od razu otworzy listę i podgląd do ręcznej korekty polygonów tablic dla całej bieżącej puli. Jeśli wolisz, możesz też pominąć autoanotację i przejść od razu do ręcznej anotacji tej samej paczki."
                else:
                    route_text = "Domyślnie pomijasz boxowanie pojazdów i uruchomisz tylko autoanotację tablic."
                    action_text = "Jeśli chcesz dodać pojazdy, odznacz pole pomijania. W następnym kroku wybierzesz wtedy model pojazdów."
                auto_choice_hint = "Zaznaczone pole oznacza wariant: tylko tablice."
            else:
                if campaign_context:
                    route_text = "Najpierw uruchomisz autoanotację tablic i pojazdów, opcjonalnie także na dołączonych ręcznych zdjęciach z wcześniejszych iteracji, a potem sprawdzisz i poprawisz wynik ręcznie w tym samym Z2."
                    action_text = "Po zapisaniu runu Z2 od razu otworzy listę i podgląd do ręcznej korekty polygonów tablic dla całej bieżącej puli. Jeśli wolisz, możesz też pominąć autoanotację i przejść od razu do ręcznej anotacji tej samej paczki."
                else:
                    route_text = "Run anotacji Z2 zostanie wykonany dla tablic i pojazdów."
                    action_text = "W następnym kroku wybierzesz model pojazdów, potem wskażesz folder z obrazami i uruchomisz autoanotację tablic + pojazdów."
                auto_choice_hint = "Odznaczone pole oznacza wariant: pojazdy + tablice."
            manual_template_hint = ""
            if campaign_context:
                followup_title = "3. Po uruchomieniu przejdziesz do ręcznej korekty"
                followup_text = (
                    "Ten tor nie kończy się na samym uruchomieniu modeli. Po zapisaniu runu Z2 od razu sprawdzisz wynik, "
                    "poprawisz polygony tablic ręcznie i dopiero potem domkniesz E2. To obejmuje również zdjęcia dołączone checkboxem z wcześniejszych iteracji."
                )
                export_text = "Split i eksport datasetu są kolejnym krokiem dopiero na gotowym, sprawdzonym runie Z2."
            if auto_completed:
                followup_title = "3. Podsumowanie wyniku autoanotacji"
                followup_text = self._build_auto_followup_summary()
                export_text = (
                    "Po domknięciu E2 przygotujesz dataset i trening modelu tablic w [Z4]."
                    if campaign_context
                    else "Po wyborze ścieżki dataset zostanie przygotowany z gotowego runu anotacji Z2."
                )
        elif route == "manual":
            run_title = "Anotacja ręczna tablic"
            badge_text = "Aktywny tor: anotacja ręczna tablic"
            badge_tone = "warning"
            route_tone = "muted"
            followup_title = "3. Ręczna korekta i stage"
            followup_text = (
                "W tym torze pracujesz bez mieszania z autoanotacją. Po otwarciu runu anotacji możesz kasować obrazy, przenosić je do stage i poprawiać polygony."
            )
            export_text = (
                "Po zapisaniu zmian domkniesz E2, a dataset i trening wykonasz potem w [Z4]."
                if campaign_context
                else "Split i eksport odblokowują się dopiero na gotowym runie anotacji po zapisaniu zmian."
            )
            workflow_input_title = "2. Wskaż folder obrazów"
            workflow_input_hint = "Najpierw wybierz folder obrazów. Ten folder będzie bazą nowego ręcznego runu anotacji Z2."
            if campaign_context and manual_review_active:
                route_text = "Korygujesz bieżący run Z2 tej iteracji."
                action_text = "Po prawej poprawiasz polygony aktywnego runu i po zakończeniu zmian domykasz E2."
                manual_hint = (
                    "To nie jest osobny mini-workflow. Z2 jest już otwarte w trybie korekty aktywnego runu kampanii."
                )
                manual_hint_tone = "muted"
                workflow_start_title = "Aktywna korekta runu Z2"
                workflow_input_title = "Aktywny run kampanii"
                workflow_input_hint = "Bieżący run Z2 jest już wczytany i gotowy do poprawiania."
            elif current_step == "manual_entry":
                if manual_import:
                    manual_hint = (
                        "Po kliknięciu Dalej wskażesz dowolny run autoanotacji Z2 do korekty. "
                        "Jeśli leży poza workspace, program bezpiecznie skopiuje go do lokalnego importu."
                    )
                elif manual_entry_mode == "continue":
                    manual_hint = (
                        "Po kliknięciu Dalej przejdziesz do historii runów autoanotacji Z2 "
                        "i wybierzesz run anotacji do wznowienia korekty."
                    )
                else:
                    manual_hint = (
                        "Po kliknięciu Dalej przejdziesz do tworzenia nowego runu ręcznej anotacji Z2 dla ręcznej anotacji tablic."
                    )
                manual_hint_tone = "muted"
                manual_template_hint = ""
                manual_template_tone = "muted"
            if manual_entry_mode == "continue":
                if current_step == "manual_history":
                    workflow_start_title = "2. Otwórz run anotacji do korekty"
                    route_text = "Na tym etapie wybierasz wyłącznie run autoanotacji Z2 z historii korekt."
                    action_text = (
                        "Zaznacz run anotacji z historii i kliknij Dalej, aby otworzyć go w edytorze."
                        if has_manual_history
                        else "Historia jest pusta. Wróć i wybierz nową anotację albo wskaż dowolny run autoanotacji Z2."
                    )
                    manual_hint = (
                        "Podgląd pozostaje wyłączony, dopóki nie otworzysz konkretnego runu anotacji z historii."
                        if has_manual_history
                        else "Jeśli nie masz jeszcze historii korekt, cofnij się i wybierz inny tor wejścia."
                    )
                    manual_hint_tone = "muted" if has_manual_history else "warning"
                    manual_template_hint = (
                        "Run anotacji do kontynuacji to katalog z annotations.xml i zgodnymi obrazami. "
                        f"Domyślnie runy autoanotacji Z2 są zapisywane w: {self._get_annotation_run_storage_display_path()}."
                    )
                    manual_template_tone = "muted"
            elif manual_import:
                route_text = "Wybrano tor wskazania dowolnego runu autoanotacji Z2 do korekty."
                action_text = "Kliknij Dalej, aby wskazać run anotacji i ewentualnie zaimportować go do workspace Z2."
                manual_hint = (
                    "Program przyjmie tylko run autoanotacji Z2 z annotations.xml i zgodnymi obrazami. "
                    "Jeśli run anotacji leży poza workspace, zostanie bezpiecznie skopiowany do lokalnego runu anotacji import_*."
                )
                manual_hint_tone = "muted"
                manual_template_hint = (
                    f"Domyślny katalog runów autoanotacji Z2: {self._get_annotation_run_storage_display_path()}."
                )
                manual_template_tone = "muted"
            else:
                workflow_input_title = "2. Wskaż folder obrazów i opcje pomocy"
                workflow_input_hint = (
                    "Tutaj wybierasz obrazy dla nowego runu ręcznej anotacji Z2 oraz opcjonalnie włączasz pomocnicze boxy pojazdów."
                )
                workflow_start_title = "3. Utwórz ręczny run anotacji Z2"
                route_text = "Wybrano nową anotację, więc przygotujesz nowy run ręcznej anotacji Z2."
                action_text = "Wskaż folder obrazów, opcjonalnie włącz boxy pojazdów i przejdź do utworzenia nowego XML."
                manual_hint = "Ten tor tworzy nowy run ręcznej anotacji Z2 i nie nadpisuje starszych XML-i."
                manual_hint_tone = "muted"
                manual_template_hint = "Nowy run ręcznej anotacji Z2 nie nadpisuje starszych XML-i i jest zapisywany w workspace Z2."
                manual_template_tone = "muted"
                manual_vehicle_hint = "Opcjonalne boxy pojazdów są tylko pomocą przy ręcznej pracy."
                manual_vehicle_tone = "muted"
                if vehicle_assist_enabled:
                    workflow_conf_title = "Pewność pomocniczych boxów pojazdów"
                    workflow_conf_hint = (
                        "Ten próg dotyczy tylko pomocniczego boxowania pojazdów w nowym XML."
                    )
                    workflow_vehicle_title = "Model pojazdów do pomocniczego boxowania"
                    workflow_vehicle_hint = (
                        "Model pojazdów posłuży tylko jako wsparcie przy ręcznym rysowaniu tablic."
                    )

        if route and current_index and total_steps:
            run_title = f"{run_title} | Krok {current_index} z {total_steps}"

        if route == "manual" and current_step == "manual_entry" and manual_template_hint:
            manual_hint = (
                f"{manual_hint}\n\n{manual_template_hint}"
                if manual_hint
                else manual_template_hint
            )
            manual_template_hint = ""
            manual_template_tone = "muted"

        self.auto_vehicle_choice_hint_var.set(auto_choice_hint)
        self.manual_entry_title_var.set(manual_entry_title)
        self.manual_entry_hint_var.set(manual_hint)
        self.manual_xml_template_hint_var.set(manual_template_hint)
        self.manual_vehicle_assist_hint_var.set(manual_vehicle_hint)
        self.workflow_conf_title_var.set(workflow_conf_title)
        self.workflow_conf_hint_var.set(workflow_conf_hint)
        self.workflow_vehicle_model_title_var.set(workflow_vehicle_title)
        self.workflow_vehicle_model_hint_var.set(workflow_vehicle_hint)
        self._set_inline_label_state(self.route_badge_lbl, text=badge_text, tone=badge_tone, emphasis=True)
        self._set_inline_label_state(self.route_summary_lbl, text=route_text, tone=route_tone, emphasis=False)
        self._set_inline_label_state(self.workflow_action_hint_lbl, text=action_text, tone="muted", emphasis=False)
        self._set_inline_label_state(self.followup_intro_lbl, text=followup_text, tone="muted", emphasis=False)
        self._set_inline_label_state(self.export_intro_lbl, text=export_text, tone="muted", emphasis=False)
        self._set_inline_label_state(self.auto_vehicle_choice_hint_lbl, tone="muted", emphasis=False)
        self._set_inline_label_state(self.manual_entry_hint_lbl, tone=manual_hint_tone, emphasis=False)
        self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone=manual_template_tone, emphasis=False)
        self._set_inline_label_state(self.manual_vehicle_assist_hint_lbl, tone=manual_vehicle_tone, emphasis=False)
        self._set_inline_label_state(
            self.workflow_manual_vehicle_assist_hint_lbl,
            tone=manual_vehicle_tone,
            emphasis=False,
        )
        self._set_inline_label_state(
            self.workflow_conf_hint_lbl,
            tone="muted",
            emphasis=False,
        )
        self._set_inline_label_state(
            self.workflow_vehicle_model_hint_lbl,
            tone="muted",
            emphasis=False,
        )
        try:
            self.run_title_lbl.configure(text=run_title)
        except Exception:
            pass
        try:
            self.workflow_input_title_lbl.configure(text=workflow_input_title)
        except Exception:
            pass
        try:
            self.auto_vehicle_choice_title_lbl.configure(text="3. Dodaj opcjonalne boxowanie pojazdów")
        except Exception:
            pass
        self._set_inline_label_state(
            self.workflow_input_hint_lbl,
            text=workflow_input_hint,
            tone="muted",
            emphasis=False,
        )
        try:
            self.workflow_start_title_lbl.configure(text=workflow_start_title)
        except Exception:
            pass
        try:
            self.followup_title_lbl.configure(text=followup_title)
        except Exception:
            pass

    def _update_manual_xml_template_ui(self):
        if self._get_workflow_route() == "manual" and self._get_manual_entry_mode() != "new":
            self.manual_xml_template_var.set(False)

        if not self._manual_xml_template_enabled():
            self.manual_vehicle_assist_var.set(False)

        self._refresh_left_panel_route_copy()
        self._refresh_detection_configuration_ui()
        self._refresh_manual_plate_stage_ui()
        self._refresh_free_mode_workflow_ui()

    def _get_model_path(self, model_type: str) -> Path:
        if model_type == "vehicle":
            if self.vehicle_model_var.get() == "Custom": return Path(self.vehicle_custom_var.get())
            else: return CONFIG.get_base_models_dir("vehicle") / AVAILABLE_DETECT_MODELS[self.vehicle_model_var.get()]["file"]
        else:
            return Path(self.plate_custom_var.get())

    def _collect_pending_model_downloads(self, mode_text: str):
        pending = []

        if self._mode_uses_vehicle(mode_text) and self.vehicle_model_var.get() != "Custom":
            model_key = (self.vehicle_model_var.get() or "").strip()
            model_info = AVAILABLE_DETECT_MODELS.get(model_key, {})
            target_path = self._get_model_path("vehicle")

            if model_info and target_path and not Path(target_path).exists():
                pending.append(
                    {
                        "role": "pojazdy",
                        "label": model_info.get("name", model_key or "model pojazdów"),
                        "asset_name": model_info.get("file", Path(target_path).name),
                        "target_path": Path(target_path),
                    }
                )

        return pending

    def _confirm_and_download_missing_models(self, pending_downloads) -> bool:
        if not pending_downloads:
            return True

        details = "\n".join(
            f"- {item['label']} -> {item['target_path']}"
            for item in pending_downloads
        )

        consent = messagebox.askyesno(
            "Pobieranie modelu z sieci",
            (
                "Brakuje lokalnych modeli potrzebnych do uruchomienia Z2.\n\n"
                f"{details}\n\n"
                "Aplikacja może pobrać te pliki z internetu dopiero po Twojej zgodzie.\n"
                "Jeśli się zgodzisz, przebieg pobierania będzie logowany w terminalu procesu w Z2.\n"
                "Możesz go obserwować w globalnym terminalu z ikony w dolnym pasku.\n\n"
                "Czy chcesz pobrać brakujące modele teraz?"
            ),
            parent=self.frame.winfo_toplevel()
        )

        if not consent:
            logger.warning("Uruchomienie Z2 anulowane: użytkownik nie wyraził zgody na pobranie brakujących modeli.")
            self._set_status_label_state("Anulowano: brak zgody na pobranie modelu", "warning")
            return False

        self._set_annotation_process_log_visibility(True)
        self._set_status_label_state("Pobieranie modeli: szczegóły w terminalu procesu", "info")
        logger.info("Użytkownik wyraził zgodę na pobranie brakujących modeli dla Z2.")
        logger.info("Postęp pobierania jest widoczny w terminalu procesu Z2.")
        logger.info("Jeśli terminal był zwinięty, został właśnie otwarty do podglądu pobierania.")

        from ultralytics.utils.downloads import attempt_download_asset

        for item in pending_downloads:
            target_path = Path(item["target_path"])
            asset_name = str(item.get("asset_name") or target_path.name)
            label = str(item.get("label") or target_path.name)

            logger.info(f"Rozpoczynam pobieranie modelu: {label}")
            logger.info(f"Docelowa ścieżka modelu: {target_path}")

            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise RuntimeError(f"Nie udało się przygotować katalogu dla modelu {label}: {e}") from e

            try:
                downloaded_path = Path(
                    attempt_download_asset(str(target_path.parent / asset_name))
                )
            except Exception as e:
                raise RuntimeError(f"Nie udało się pobrać modelu {label}: {e}") from e

            if not downloaded_path.exists():
                raise RuntimeError(f"Pobieranie modelu {label} nie zakończyło się utworzeniem pliku.")

            logger.info(f"Pobieranie zakończone: {downloaded_path}")

        return True

    def _start_annotation(self):
        in_d = self.input_dir_var.get().strip()
        if not in_d or not Path(in_d).exists():
            return messagebox.showerror("Błąd", "Wybierz folder z obrazami wejściowymi.")
        
        try:
            mode_text = self._normalize_mode_value()
            self.mode_var.set(mode_text)
            manual_template = self._manual_xml_template_enabled()
            manual_vehicle_assist = self._manual_vehicle_assist_enabled()
            selected_device = self._normalize_selected_device()
            self.device_var.set(selected_device)
            dev = self._device_to_ultralytics(selected_device)
            conf = self.conf_var.get()
            v_p = None
            p_p = None

            if not manual_template:
                self._validate_models()

                pending_downloads = self._collect_pending_model_downloads(mode_text)
                if not self._confirm_and_download_missing_models(pending_downloads):
                    return

                v_p = self._get_model_path("vehicle") if self._mode_uses_vehicle(mode_text) else None
                p_p = self._get_model_path("plate") if self._mode_uses_plate(mode_text) else None
            elif manual_vehicle_assist:
                self._validate_vehicle_model_selection()
                pending_downloads = self._collect_pending_model_downloads("C: Pojazdy + tablice")
                if not self._confirm_and_download_missing_models(pending_downloads):
                    return
                v_p = self._get_model_path("vehicle")

            if self._preview_draw_mode and self._preview_draw_points:
                return messagebox.showwarning(
                    "Rysowanie w toku",
                    "Dokończ albo anuluj rozpoczęty polygon przed uruchomieniem nowego runu Z2."
                )

            if self._preview_dirty_images:
                decision = messagebox.askyesnocancel(
                    "Niezapisane poprawki",
                    "Masz niezapisane poprawki poprzedniego runu Z2.\n\n"
                    "Tak: zapisz poprawki i uruchom nowy run.\n"
                    "Nie: porzuc poprawki i uruchom nowy run.\n"
                    "Anuluj: wroc do podgladu bez uruchamiania procesu."
                )
                if decision is None:
                    return
                if decision:
                    self._set_status_label_state("Zapisywanie poprzednich poprawek...", "info")
                    try:
                        self.frame.update_idletasks()
                    except Exception:
                        pass
                    if not self._save_preview_edits(
                        interactive=True,
                        status_message="Zapisano poprawki polygonów przed uruchomieniem nowego runu Z2.",
                    ):
                        return
                else:
                    self._cancel_preview_autosave()
                    self._preview_dirty_images.clear()
                    self._preview_draw_mode = False
                    self._preview_draw_points = []
                    self._update_preview_edit_status(
                        "Porzucono niezapisane poprawki poprzedniego runu Z2."
                    )

            if self.annotator is not None:
                try:
                    self.annotator.unload_models()
                except Exception:
                    pass
                self.annotator = None

            if not manual_template:
                if self._mode_uses_vehicle(mode_text):
                    self.annotator = CombinedAnnotator(v_p, p_p, conf, conf, CONFIG.PLATE_INSIDE_THRESHOLD, dev)
                else:
                    self.annotator = PlateAnnotator(p_p, conf, dev)

                success, msg = self.annotator.load_models()
            elif manual_vehicle_assist:
                self.annotator = VehicleAnnotator(v_p, conf, dev)
                success, msg = self.annotator.load_models()
            if not success: raise RuntimeError(f"Błąd silnika YOLO: {msg}")

            # Nowy run autoanotacji uniewaĹĽnia poprzednie zatwierdzenie kroku 2.
            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name():
                    CAMPAIGN.reset_step2()
                    if 'campaign' in self.app.tabs:
                        self.app.tabs['campaign']._refresh_dashboard()
            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ zresetowaÄ‡ stanu Kroku 2: {e}")

            self._current_run_manual_template = manual_template
            self._current_run_manual_vehicle_assist = manual_vehicle_assist
            safe_output_dir = self._coerce_annotation_output_dir(self.output_dir_var.get())
            self.output_dir_var.set(str(safe_output_dir))
            app = getattr(self, "app", None)
            if app is not None and hasattr(app, "try_begin_exclusive_operation"):
                ok, busy_message = app.try_begin_exclusive_operation("z2.annotation.run", "Z2: przygotowanie anotacji")
                if not ok:
                    return messagebox.showinfo("Proces w toku", busy_message)
            else:
                self.app.set_processing(True)
            self.is_processing = True
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.approve_btn.config(state=tk.DISABLED)
            self.export_plate_dataset_btn.config(state=tk.DISABLED)
            self.progress.configure(value=0)
            self._set_progress_counters(0, 0, 0)
            self._set_post_annotation_hint("")
            
            self.preview_listbox.delete(0, tk.END)
            self.preview_canvas.delete("all")
            self.current_annotations = []
            self._clear_preview_editor_state(clear_dirty=True)
            
            logger.info("="*50)
            logger.info(
                "ROZPOCZÄTO PRZYGOTOWANIE XML DO RÄCZNEJ ANOTACJI TABLIC"
                if manual_template
                else "ROZPOCZÄTO AUTOANOTACJÄ OBRAZĂ“W (YOLO)"
            )
            logger.info("="*50)
            logger.info(
                (
                    f"Tryb Z2: reczna anotacja + auto-boxy pojazdow | obrazy: {in_d}"
                    if manual_vehicle_assist
                    else f"Tryb Z2: reczna anotacja | obrazy: {in_d}"
                )
                if manual_template
                else f"Urzadzenie Z2: {selected_device} -> runtime={dev}"
            )
            
            threading.Thread(
                target=self._process_thread,
                args=(Path(in_d), safe_output_dir, manual_template, manual_vehicle_assist),
                daemon=True
            ).start()
            
        except Exception as e:
            logger.error(f"Nie można wystartować: {e}")
            messagebox.showerror("BĹ‚Ä…d Startu", str(e))

    def _start_annotation(self):
        route = self._get_workflow_route()
        manual_entry_mode = self._get_manual_entry_mode()
        if self._is_free_mode_session_context() and not route:
            return messagebox.showwarning("Wybierz tor", "Najpierw wybierz autoanotacje albo anotacje reczna.")

        if route == "manual" and manual_entry_mode == "continue":
            selected_run = self._get_selected_manual_review_history_run_dir()
            if selected_run is None:
                return messagebox.showwarning(
                    "Wybierz run anotacji",
                    "W trybie recznej kontynuacji wybierz run anotacji z historii korekt.",
                )
            return self._open_existing_run_for_manual_review(
                run_dir=selected_run,
                allow_fallback=False,
                show_dialog=False,
            )

        in_d = self.input_dir_var.get().strip()
        if not in_d or not Path(in_d).exists():
            return messagebox.showerror("Blad", "Wybierz folder z obrazami wejsciowymi.")

        try:
            mode_text = self._normalize_mode_value()
            if route == "auto":
                if self._get_auto_vehicle_choice() == "skip":
                    mode_text = "B: Tylko tablice"
                elif self._get_auto_vehicle_choice() == "use":
                    mode_text = "C: Pojazdy + tablice"
            self.mode_var.set(mode_text)
            manual_template = self._manual_xml_template_enabled()
            manual_vehicle_assist = self._manual_vehicle_assist_enabled()
            if route == "manual" and manual_entry_mode == "new" and manual_template and self._has_active_manual_template_run():
                self._refresh_free_mode_workflow_ui()
                return messagebox.showinfo(
                    "Run juz istnieje",
                    "Dla tego stanu Z2 run recznej anotacji jest juz utworzony.\n\n"
                    "Przejdz do edycji istniejacego runu zamiast tworzyc kolejny XML."
                )
            effective_input_dir = Path(in_d)
            if not manual_template and not self._is_free_mode_session_context():
                try:
                    effective_input_dir = self._build_campaign_auto_annotation_merge_dir(effective_input_dir)
                except Exception as e:
                    logger.debug(f"Nie udało się przygotować łączonej paczki wejściowej Z2: {e}")
                    effective_input_dir = Path(in_d)
            selected_device = self._get_effective_yolo_device_choice()
            dev = self._device_to_ultralytics(selected_device)
            success, msg = True, ""
            conf = self.conf_var.get()
            v_p = None
            p_p = None

            if not manual_template:
                self._validate_models()

                pending_downloads = self._collect_pending_model_downloads(mode_text)
                if not self._confirm_and_download_missing_models(pending_downloads):
                    return

                v_p = self._get_model_path("vehicle") if self._mode_uses_vehicle(mode_text) else None
                p_p = self._get_model_path("plate") if self._mode_uses_plate(mode_text) else None
            elif manual_vehicle_assist:
                self._validate_vehicle_model_selection()
                pending_downloads = self._collect_pending_model_downloads("C: Pojazdy + tablice")
                if not self._confirm_and_download_missing_models(pending_downloads):
                    return
                v_p = self._get_model_path("vehicle")

            if self.annotator is not None:
                try:
                    self.annotator.unload_models()
                except Exception:
                    pass
                self.annotator = None

            if not manual_template:
                if self._mode_uses_vehicle(mode_text):
                    self.annotator = CombinedAnnotator(v_p, p_p, conf, conf, CONFIG.PLATE_INSIDE_THRESHOLD, dev)
                else:
                    self.annotator = PlateAnnotator(p_p, conf, dev)
            elif manual_vehicle_assist:
                self.annotator = VehicleAnnotator(v_p, conf, dev)

            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name():
                    CAMPAIGN.reset_step2()
                    if "campaign" in self.app.tabs:
                        self.app.tabs["campaign"]._refresh_dashboard()
            except Exception as e:
                logger.debug(f"Nie udalo sie zresetowac stanu Kroku 2: {e}")

            self._manual_review_active = False
            self._manual_review_from_auto = False
            self._manual_review_export_ready = False
            self._current_run_manual_template = manual_template
            self._current_run_manual_vehicle_assist = manual_vehicle_assist
            safe_output_dir = self._coerce_annotation_output_dir(self.output_dir_var.get())
            self.output_dir_var.set(str(safe_output_dir))
            app = getattr(self, "app", None)
            if app is not None and hasattr(app, "try_begin_exclusive_operation"):
                ok, busy_message = app.try_begin_exclusive_operation("z2.annotation.run", "Z2: przygotowanie anotacji")
                if not ok:
                    return messagebox.showinfo("Proces w toku", busy_message)
            else:
                self.app.set_processing(True)
            self.is_processing = True
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.approve_btn.config(state=tk.DISABLED)
            self.export_plate_dataset_btn.config(state=tk.DISABLED)
            self.progress.configure(value=0)
            self._set_progress_counters(0, 0, 0)
            self._set_status_label_state(
                (
                    "Ladowanie modelu pojazdow..."
                    if manual_template and manual_vehicle_assist
                    else "Ladowanie modeli YOLO..."
                    if not manual_template
                    else "Przygotowywanie szablonu anotacji..."
                ),
                "info",
            )
            self._set_post_annotation_hint("")
            with self._progress_update_lock:
                self._pending_progress_update = None
                self._progress_update_flush_queued = False
            self._progress_update_seen = False

            self.preview_listbox.delete(0, tk.END)
            self.preview_canvas.delete("all")
            self._clear_preview_editor_state(clear_dirty=True)
            self.current_annotations = []
            self._refresh_free_mode_workflow_ui()

            logger.info("=" * 50)
            logger.info(
                "ROZPOCZETO PRZYGOTOWANIE XML DO RECZNEJ ANOTACJI TABLIC"
                if manual_template
                else "ROZPOCZETO AUTOANOTACJE OBRAZOW (YOLO)"
            )
            logger.info("=" * 50)
            logger.info(
                (
                    f"Tryb Z2: reczna anotacja + auto-boxy pojazdow | obrazy: {effective_input_dir}"
                    if manual_vehicle_assist
                    else f"Tryb Z2: reczna anotacja | obrazy: {effective_input_dir}"
                )
                if manual_template
                else f"Urzadzenie Z2: {selected_device} -> runtime={dev}"
            )

            self._start_pre_progress_activity(
                "Inicjalizacja modelu i analiza pierwszego obrazu"
                if (manual_vehicle_assist or not manual_template)
                else "Przygotowywanie szablonu dla pierwszego obrazu"
            )

            worker_thread = threading.Thread(
                target=self._process_thread,
                args=(Path(effective_input_dir), safe_output_dir, manual_template, manual_vehicle_assist),
                daemon=True,
            )
            self._annotation_worker_thread = worker_thread

            def launch_worker():
                try:
                    print("Z2 TRACE | before worker.start()", flush=True)
                except Exception:
                    pass
                try:
                    worker_thread.start()
                except Exception as e:
                    logger.exception("Z2 worker: start() nie powiodlo sie")
                    self._post_to_ui(lambda err=str(e): messagebox.showerror("Blad Startu", err))
                    return
                try:
                    print("Z2 TRACE | after worker.start()", flush=True)
                except Exception:
                    pass

            try:
                self.frame.after_idle(launch_worker)
            except Exception:
                launch_worker()

        except Exception as e:
            if getattr(self, "is_processing", False):
                self.is_processing = False
                if hasattr(self.app, "end_exclusive_operation"):
                    self.app.end_exclusive_operation("z2.annotation.run")
                else:
                    self.app.set_processing(False)
            logger.error(f"Nie mozna wystartowac: {e}")
            messagebox.showerror("Blad Startu", str(e))

    def _build_manual_annotations_template(
        self,
        in_dir: Path,
        progress_callback,
    ) -> tuple[list[ImageAnnotation], AnnotationReport]:
        image_paths = get_image_files(in_dir)
        annotations: list[ImageAnnotation] = []
        report = AnnotationReport()
        total = len(image_paths)

        for idx, image_path in enumerate(image_paths, start=1):
            if not self.is_processing:
                raise KeyboardInterrupt("Anulowano")

            width, height = get_image_size(image_path)
            ann = ImageAnnotation(
                filename=image_path.name,
                width=max(1, int(width)),
                height=max(1, int(height)),
                detections=[],
                status=AnnotationStatus.NO_PLATE,
                status_message="Obraz przygotowany do recznej anotacji tablic.",
            )
            annotations.append(ann)
            report.add_result(ann)

            if callable(progress_callback):
                progress_callback(idx, total, image_path.name, idx)

        return annotations, report

    def _build_manual_annotations_template_from_vehicle_seed(
        self,
        in_dir: Path,
        seed_annotations: list[ImageAnnotation] | None,
    ) -> tuple[list[ImageAnnotation], AnnotationReport]:
        image_paths = get_image_files(in_dir)
        annotations: list[ImageAnnotation] = []
        report = AnnotationReport()
        seed_map = {
            str(getattr(ann, "filename", "") or ""): ann
            for ann in (seed_annotations or [])
            if str(getattr(ann, "filename", "") or "").strip()
        }

        for image_path in image_paths:
            if not self.is_processing:
                raise KeyboardInterrupt("Anulowano")

            source_ann = seed_map.get(image_path.name)
            if source_ann is not None:
                width = max(1, int(getattr(source_ann, "width", 0) or 0))
                height = max(1, int(getattr(source_ann, "height", 0) or 0))
            else:
                width, height = get_image_size(image_path)
                width = max(1, int(width))
                height = max(1, int(height))

            vehicle_detections = []
            if source_ann is not None:
                for det in getattr(source_ann, "detections", []) or []:
                    if str(getattr(det, "label", "") or "").lower() != "vehicle":
                        continue
                    vehicle_detections.append(
                        Detection(
                            label="vehicle",
                            confidence=float(getattr(det, "confidence", 1.0) or 1.0),
                            bbox=tuple(float(v) for v in (getattr(det, "bbox", ()) or (0.0, 0.0, 0.0, 0.0))[:4]),
                            attributes=dict(getattr(det, "attributes", {}) or {}),
                        )
                    )

            if vehicle_detections:
                status = AnnotationStatus.SUCCESS
                status_message = (
                    f"Wykryto {len(vehicle_detections)} pojazdow. "
                    "Spacja kadruje kolejne auta, a D dodaje reczna tablice."
                )
            else:
                status = AnnotationStatus.NO_PLATE
                status_message = (
                    "Nie wykryto pojazdu automatycznie. Nadal mozesz recznie dodac tablice polygonem 4 pkt."
                )

            ann = ImageAnnotation(
                filename=image_path.name,
                width=width,
                height=height,
                detections=vehicle_detections,
                status=status,
                status_message=status_message,
            )
            annotations.append(ann)
            report.add_result(ann)

        return annotations, report

    def _process_thread(
        self,
        in_dir: Path,
        base_out_dir: Path,
        manual_template: bool = False,
        manual_vehicle_assist: bool = False,
    ):
        success = False
        message = ""
        run_dir = None
        
        try:
            try:
                print("Z2 TRACE | entered _process_thread", flush=True)
            except Exception:
                pass
            try:
                print(f"Z2 TRACE | output_dir={base_out_dir}", flush=True)
            except Exception:
                pass
            self._post_to_ui(lambda: self._set_status_label_state("Skanowanie folderu obrazow...", "neutral"))
            try:
                print("Z2 TRACE | before count_images", flush=True)
            except Exception:
                pass
            total_images = count_images_in_directory(in_dir)
            try:
                print(f"Z2 TRACE | after count_images total={total_images}", flush=True)
            except Exception:
                pass
            if total_images == 0:
                self._post_to_ui(lambda: self._finish(False, "Brak obrazĂłw we wskazanym folderze wejĹ›ciowym."))
                return
            self._post_to_ui(lambda total=total_images: self._set_progress_counters(0, 0, total))

            annotator = getattr(self, "annotator", None)
            try:
                print(
                    f"Z2 TRACE | annotator={type(annotator).__name__ if annotator is not None else 'None'}",
                    flush=True,
                )
            except Exception:
                pass
            if annotator is not None:
                load_started_at = datetime.datetime.now()
                try:
                    print("Z2 TRACE | before annotator.load_models()", flush=True)
                except Exception:
                    pass
                load_ok, load_msg = annotator.load_models()
                try:
                    print(f"Z2 TRACE | after annotator.load_models() ok={load_ok}", flush=True)
                except Exception:
                    pass
                if not load_ok:
                    message = f"Blad silnika YOLO: {load_msg}"
                    success = False
                    return
                load_elapsed_s = max(
                    0.0,
                    (datetime.datetime.now() - load_started_at).total_seconds(),
                )
                uses_accelerator = str(getattr(annotator, "device", "") or "").strip().lower() != "cpu"
                first_image_hint = (
                    " Pierwszy obraz moze potrwac dluzej przez inicjalizacje CUDA."
                    if uses_accelerator
                    else ""
                )
                self._post_to_ui(
                    lambda total=total_images, load_elapsed_s=load_elapsed_s, first_image_hint=first_image_hint:
                        self._set_status_label_state(
                            f"Model zaladowany ({load_elapsed_s:.1f}s). Rozpoczynam analize 1/{total}.{first_image_hint}",
                            "neutral",
                        )
                )
                if annotator.is_stopped() or not self.is_processing:
                    message = "Anulowano przez uzytkownika."
                    success = False
                    return
                
            self.start_time = datetime.datetime.now()
            
            def prog_cb(current, total, filename, successful=0):
                if not self.is_processing: raise KeyboardInterrupt("Anulowano")
                pct = (current / total) * 100 if total > 0 else 0
                self._queue_progress_update(pct, current, total, filename, successful)
            
            if manual_template and not manual_vehicle_assist:
                annotations, report = self._build_manual_annotations_template(in_dir, prog_cb)
            elif manual_template:
                vehicle_annotations, _vehicle_report = self.annotator.process_directory(in_dir, prog_cb)
                annotations, report = self._build_manual_annotations_template_from_vehicle_seed(
                    in_dir,
                    vehicle_annotations,
                )
            else:
                annotations, report = self.annotator.process_directory(in_dir, prog_cb)
            
            if ((not manual_template) or manual_vehicle_assist) and (self.annotator.is_stopped() or not self.is_processing):
                message = "Przetwarzanie przerwane przez uĹĽytkownika."
                success = False
                return

            self.current_annotations = annotations
            self.current_input_dir = in_dir
            self._preview_image_path_map = {}

            base_out_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            counter = 1
            while True:
                run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}"
                if not run_dir.exists(): break
                counter += 1
                
            run_dir.mkdir(parents=True, exist_ok=True)
            cvat_xml_path = run_dir / "annotations.xml"

            logger.info(
                (
                    "Zapisywanie annotations.xml z boxami pojazdow do recznej anotacji tablic..."
                    if manual_vehicle_assist
                    else "Zapisywanie pustego annotations.xml do recznej anotacji..."
                )
                if manual_template
                else "Zapisywanie bazy detekcji (annotations.xml)..."
            )
            CVATExporter().export(
                annotations,
                cvat_xml_path,
                only_successful=not manual_template,
            )
            self.current_annotation_run_dir = run_dir
            self.current_annotation_xml_path = cvat_xml_path

            logger.info("Generowanie raportu statystycznego...")
            ReportGenerator.generate_text_report(report, run_dir / "report.txt")

            try:
                self._write_annotation_run_manifest(run_dir, in_dir)
            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ zapisaÄ‡ manifestu runu Z2: {e}")

            elapsed = format_duration((datetime.datetime.now() - self.start_time).total_seconds())

            # Zachowaj Ĺ›cieĹĽkÄ™ do ostatniego runu w stagingu.
            self.last_staging_run_dir = run_dir

            message = (
                f"Przygotowano XML do rÄ™cznej anotacji: {run_dir.name} (w czasie {elapsed})"
                if manual_template
                else f"ZakoĹ„czono! Zapisano do: {run_dir.name} (w czasie {elapsed})"
            )
            success = True

            try:
                self._mark_annotation_run_completed(
                    run_dir,
                    annotations,
                    manual_template=manual_template,
                    report=report,
                )
            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ oznaczyÄ‡ runu Z2 jako zakoĹ„czonego: {e}")

            try:
                self._restore_campaign_step2_generated_from_run(run_dir)
            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ przywrĂłciÄ‡ stanu Kroku 2 z gotowego runu Z2: {e}")

            try:
                self._post_to_ui(
                    lambda run_dir=run_dir, manual_template=manual_template: self._finalize_successful_annotation_run_ui(
                        run_dir,
                        manual_template=manual_template,
                    )
                )
            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ zaplanowaÄ‡ odĹ›wieĹĽenia UI po zakoĹ„czeniu Z2: {e}")

            logger.info(f"[OK] {message}")
            
        except KeyboardInterrupt:
            message = "Anulowano przez uĹĽytkownika."
            try:
                if run_dir is not None:
                    self._update_annotation_run_manifest(
                        run_dir,
                        run_status="cancelled",
                        last_error=message,
                    )
            except Exception:
                pass
            success = False
        except Exception as e:
            message = f"Krytyczny bĹ‚Ä…d: {e}"
            try:
                if run_dir is not None:
                    self._update_annotation_run_manifest(
                        run_dir,
                        run_status="failed",
                        last_error=str(e),
                    )
            except Exception:
                pass
            success = False
        finally:
            try:
                self._post_to_ui(lambda: self._finish(success, message))
            except Exception:
                pass

    # ==========================================================
    # LOGIKA PRZEGLÄ„DARKI (CANVAS)
    # ==========================================================
    def _populate_preview_list(self):
        self.preview_listbox.delete(0, tk.END)
        palette = getattr(self.app, "palette", {})
        ok_color = palette.get("success", "#27ae60")
        err_color = palette.get("error", "#c0392b")
        for idx, ann in enumerate(self.current_annotations):
            icon = "đźź˘" if ann.is_successful else "đź”´"
            self.preview_listbox.insert(tk.END, f"{icon} {ann.filename}")
            
            # Bezpieczne dla Pythona 3.12
            if ann.is_successful:
                self.preview_listbox.itemconfig('end', foreground=ok_color)
            else:
                self.preview_listbox.itemconfig('end', foreground=err_color)
                
        if self.current_annotations:
            self.preview_listbox.selection_set(0)
            self._on_preview_select(None)

    def _resolve_preview_image_path(self, ann) -> Path | None:
        filename = str(getattr(ann, "filename", "") or "").strip()
        if not filename:
            return None

        image_map = dict(getattr(self, "_preview_image_path_map", {}) or {})
        mapped_path = image_map.get(filename)
        if mapped_path is not None:
            try:
                mapped_candidate = Path(mapped_path)
                if mapped_candidate.exists():
                    return mapped_candidate
            except Exception:
                pass

        current_input_dir = getattr(self, "current_input_dir", None)
        if current_input_dir is None:
            return None

        try:
            candidate = Path(current_input_dir) / filename
        except Exception:
            return None
        return candidate

    def _on_preview_select(self, event):
        sel = self.preview_listbox.curselection()
        if not sel or not self.current_annotations: return
            
        idx = sel[0]
        ann = self.current_annotations[idx]
        img_path = self._resolve_preview_image_path(ann)
        
        if img_path is None or not img_path.exists():
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(20, 20, text="Plik nie istnieje na dysku!", fill="red")
            return
            
        try:
            img = cv2.imread(str(img_path))
            if img is None: return
            
            for det in ann.detections:
                label_name = det.label.lower()
                conf = det.confidence
                
                if label_name == "vehicle":
                    x1, y1, x2, y2 = map(int, det.bbox)
                    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(img, f"Vehicle {conf:.2f}", (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                                
                elif label_name == "plate":
                    if det.polygon and len(det.polygon) == 4:
                        pts = np.array(det.polygon, np.int32).reshape((-1, 1, 2))
                        cv2.polylines(img, [pts], isClosed=True, color=(0, 0, 255), thickness=3)
                        min_y, min_x = int(min([p[1] for p in det.polygon])), int(min([p[0] for p in det.polygon]))
                        cv2.putText(img, f"Plate {conf:.2f}", (min_x, max(0, min_y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    else:
                        x1, y1, x2, y2 = map(int, det.bbox)
                        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
                        cv2.putText(img, f"Plate {conf:.2f}", (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            self.preview_canvas.set_image(Image.fromarray(img_rgb))
            
        except Exception as e: logger.error(f"Błąd rysowania podglądu YOLO: {e}")

    def _preview_list_item_text(self, ann, *, display_index: int | None = None, total_count: int | None = None) -> str:
        dirty_prefix = "*" if ann.filename in self._preview_dirty_images else " "
        status_text = self._preview_annotation_status_tag(ann)
        if display_index is None:
            order_text = "--."
        else:
            width = max(2, len(str(max(1, int(total_count or (display_index + 1))))))
            order_text = f"{int(display_index) + 1:0{width}d}."
        reuse_prefix = f"{self._campaign_reuse_manual_badge()} " if self._preview_annotation_is_reused_from_previous_manual(ann) else ""
        return f"{dirty_prefix} {order_text} [{status_text}] {reuse_prefix}{ann.filename}"

    def _preview_annotation_is_reused_from_previous_manual(self, ann) -> bool:
        filename = str(getattr(ann, "filename", "") or "").strip()
        if not filename:
            return False
        return filename in set(getattr(self, "_campaign_reuse_manual_filenames", set()) or set())

    @staticmethod
    def _preview_annotation_is_manually_corrected(ann) -> bool:
        return AnnotationTab._preview_annotation_manual_plate_count(ann) > 0

    @staticmethod
    def _preview_annotation_status_tag(ann) -> str:
        if AnnotationTab._preview_annotation_is_manually_corrected(ann):
            return "ED"
        if getattr(ann, "is_successful", False):
            return "OK"
        return "--"

    @staticmethod
    def _preview_annotation_manual_plate_count(ann) -> int:
        if ann is None:
            return 0

        corrected = 0
        for det in getattr(ann, "detections", []) or []:
            if str(getattr(det, "label", "") or "").lower() != "plate":
                continue
            attributes = dict(getattr(det, "attributes", {}) or {})
            manually_edited = str(attributes.get("manually_edited", "") or "").strip().lower() == "true"
            manual_source = str(attributes.get("manual_source", "") or "").strip().lower()
            if manually_edited or manual_source == "preview":
                corrected += 1

        return corrected

    def _preview_list_item_color(self, ann) -> str:
        palette = getattr(self.app, "palette", {})
        reuse_color = palette.get("warning", "#f39c12")
        corrected_color = palette.get("warning", "#f39c12")
        ok_color = palette.get("success", "#27ae60")
        err_color = palette.get("error", "#c0392b")

        if self._preview_annotation_is_reused_from_previous_manual(ann):
            return reuse_color
        if self._preview_annotation_is_manually_corrected(ann):
            return corrected_color
        if getattr(ann, "is_successful", False):
            return ok_color
        return err_color

    def _preview_annotation_sort_bucket(self, ann) -> str:
        if self._preview_annotation_is_manually_corrected(ann):
            return "ed"
        if getattr(ann, "is_successful", False):
            return "ok"
        return "problem"

    def _preview_list_status_priority(self) -> dict[str, int]:
        sort_mode = str(self.preview_list_sort_var.get() or "").strip()
        if sort_mode == "Status: OK -> ED -> problem":
            return {"ok": 0, "ed": 1, "problem": 2}
        if sort_mode == "Status: problem -> ED -> OK":
            return {"problem": 0, "ed": 1, "ok": 2}
        return {"ed": 0, "ok": 1, "problem": 2}

    def _get_preview_list_entries(self) -> list[tuple[int, ImageAnnotation]]:
        entries = list(enumerate(list(self.current_annotations or [])))
        sort_mode = str(self.preview_list_sort_var.get() or "").strip()

        if sort_mode == "Nazwa pliku A-Z":
            entries.sort(
                key=lambda item: (
                    0 if str(getattr(item[1], "filename", "") or "") in self._preview_dirty_images else 1,
                    str(getattr(item[1], "filename", "") or "").lower(),
                )
            )
            return entries

        priority = self._preview_list_status_priority()
        entries.sort(
            key=lambda item: (
                0 if str(getattr(item[1], "filename", "") or "") in self._preview_dirty_images else 1,
                priority.get(self._preview_annotation_sort_bucket(item[1]), 99),
                str(getattr(item[1], "filename", "") or "").lower(),
            )
        )
        return entries

    def _get_preview_display_index(self, actual_index: int | None) -> int | None:
        if actual_index is None:
            return None
        indices = list(getattr(self, "_preview_list_display_indices", []) or [])
        try:
            return indices.index(int(actual_index))
        except Exception:
            return None

    def _get_preview_actual_index_from_display(self, display_index: int | None) -> int | None:
        indices = list(getattr(self, "_preview_list_display_indices", []) or [])
        if display_index is None:
            return None
        try:
            safe_index = int(display_index)
        except Exception:
            return None
        if safe_index < 0 or safe_index >= len(indices):
            return None
        return int(indices[safe_index])

    def _on_preview_list_sort_changed(self, event=None):
        self._set_preview_list_sort_mode(self.preview_list_sort_var.get())

    def _refresh_preview_list_summary(self):
        annotations = list(self.current_annotations or [])
        reused_manual = sum(1 for ann in annotations if self._preview_annotation_is_reused_from_previous_manual(ann))
        corrected_images = sum(1 for ann in annotations if self._preview_annotation_is_manually_corrected(ann))
        ok_images = sum(
            1
            for ann in annotations
            if getattr(ann, "is_successful", False) and not self._preview_annotation_is_manually_corrected(ann)
        )
        problem_images = sum(
            1
            for ann in annotations
            if not getattr(ann, "is_successful", False) and not self._preview_annotation_is_manually_corrected(ann)
        )
        dirty = len(getattr(self, "_preview_dirty_images", set()) or set())

        try:
            summary = {}
            if reused_manual > 0:
                summary = dict(getattr(self, "_campaign_reuse_manual_summary", {}) or {})
            if reused_manual > 0 and summary:
                source_label = str(summary.get("source_label") or "wcześniejszej iteracji")
                base_count = int(summary.get("base_count", max(0, len(annotations) - reused_manual)) or 0)
                total_count = int(summary.get("total_count", len(annotations)) or len(annotations))
                self.preview_list_summary_var.set(
                    f"Bieżąca paczka: {base_count} | {self._campaign_reuse_manual_badge()} {source_label}: {reused_manual}\n"
                    f"Razem do autoanotacji: {total_count}"
                )
            else:
                self.preview_list_summary_var.set("")
        except Exception:
            pass

        legend_counts = (
            ("preview_list_legend_ok_count_lbl", ok_images),
            ("preview_list_legend_corrected_count_lbl", corrected_images),
            ("preview_list_legend_problem_count_lbl", problem_images),
            ("preview_list_legend_dirty_count_lbl", dirty),
        )
        for widget_name, value in legend_counts:
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(text=str(int(value)))
            except Exception:
                pass

    def _refresh_preview_list_legend_theme(self):
        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        panel_alt = palette.get("panel_alt", "#2d2d30")
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        ok_color = palette.get("success", "#27ae60")
        corrected_color = palette.get("warning", "#f39c12")
        err_color = palette.get("error", "#c0392b")
        muted_color = palette.get("muted", "#c7c7c7")
        fg_color = palette.get("fg", "#f3f3f3")

        for frame_name in (
            "preview_list_meta",
            "preview_list_controls",
            "preview_list_sort_grid",
            "preview_list_legend",
            "preview_list_legend_grid",
        ):
            frame = getattr(self, frame_name, None)
            if frame is None:
                continue
            try:
                frame.configure(style="Panel.TFrame")
            except Exception:
                pass

        for widget_name, fg in (
            ("preview_list_summary_lbl", muted_color),
            ("preview_list_sort_lbl", muted_color),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(bg=panel_bg, fg=fg)
            except Exception:
                pass

        active_sort_mode = str(self.preview_list_sort_var.get() or "").strip()
        active_sort_bg = blend_hex_colors(corrected_color, panel_bg, 0.18)
        active_sort_border = corrected_color
        active_sort_title_fg = "#1b1b1b"
        active_sort_desc_fg = blend_hex_colors("#1b1b1b", active_sort_bg, 0.28)
        inactive_sort_bg = panel_bg
        inactive_sort_border = panel_border
        inactive_sort_title_fg = fg_color
        inactive_sort_desc_fg = muted_color

        for sort_mode, widgets in dict(getattr(self, "_preview_list_sort_tiles", {}) or {}).items():
            tile = widgets.get("tile")
            title_lbl = widgets.get("title")
            desc_lbl = widgets.get("desc")
            is_active = str(sort_mode or "").strip() == active_sort_mode
            tile_bg = active_sort_bg if is_active else inactive_sort_bg
            tile_border = active_sort_border if is_active else inactive_sort_border
            title_fg = active_sort_title_fg if is_active else inactive_sort_title_fg
            desc_fg = active_sort_desc_fg if is_active else inactive_sort_desc_fg
            try:
                if tile is not None:
                    tile.configure(bg=tile_bg, highlightbackground=tile_border, highlightcolor=tile_border)
                if title_lbl is not None:
                    title_lbl.configure(bg=tile_bg, fg=title_fg)
                if desc_lbl is not None:
                    desc_lbl.configure(bg=tile_bg, fg=desc_fg)
            except Exception:
                pass

        legend_items = (
            (
                "preview_list_legend_ok_item",
                "preview_list_legend_ok_badge",
                "preview_list_legend_ok_lbl",
                "preview_list_legend_ok_count_lbl",
                ok_color,
            ),
            (
                "preview_list_legend_corrected_item",
                "preview_list_legend_corrected_badge",
                "preview_list_legend_corrected_lbl",
                "preview_list_legend_corrected_count_lbl",
                corrected_color,
            ),
            (
                "preview_list_legend_problem_item",
                "preview_list_legend_problem_badge",
                "preview_list_legend_problem_lbl",
                "preview_list_legend_problem_count_lbl",
                err_color,
            ),
            (
                "preview_list_legend_dirty_item",
                "preview_list_legend_dirty_badge",
                "preview_list_legend_dirty_lbl",
                "preview_list_legend_dirty_count_lbl",
                muted_color,
            ),
        )
        for item_name, badge_name, label_name, count_name, accent in legend_items:
            item = getattr(self, item_name, None)
            badge = getattr(self, badge_name, None)
            label = getattr(self, label_name, None)
            count_lbl = getattr(self, count_name, None)
            try:
                if item is not None:
                    item.configure(bg=panel_bg, highlightbackground=panel_border, highlightcolor=panel_border)
                if badge is not None:
                    badge.configure(bg=accent, fg=("#1b1b1b" if accent == corrected_color else panel_bg))
                if label is not None:
                    label.configure(bg=panel_bg, fg=fg_color)
                if count_lbl is not None:
                    count_lbl.configure(bg=panel_bg, fg=accent)
            except Exception:
                pass

    def _get_preview_annotation(self, idx: int | None = None):
        if not self.current_annotations:
            return None
        index = self.current_preview_index if idx is None else idx
        if index is None or index < 0 or index >= len(self.current_annotations):
            return None
        return self.current_annotations[index]

    @staticmethod
    def _get_plate_detections(ann) -> list[Detection]:
        if ann is None:
            return []
        return [det for det in ann.detections if str(det.label or "").lower() == "plate"]

    @staticmethod
    def _detection_polygon(det: Detection) -> list[tuple[float, float]]:
        if det.polygon and len(det.polygon) >= 4:
            return [(float(x), float(y)) for x, y in det.polygon[:4]]

        x1, y1, x2, y2 = det.bbox
        return [
            (float(x1), float(y1)),
            (float(x2), float(y1)),
            (float(x2), float(y2)),
            (float(x1), float(y2)),
        ]

    @staticmethod
    def _bbox_from_polygon(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
        xs = [float(x) for x, _y in points]
        ys = [float(y) for _x, y in points]
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _keypoints_from_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
        return [(float(x), float(y), 1.0) for x, y in points[:4]]

    def _get_selected_plate_index_for_ann(self, ann) -> int | None:
        plates = self._get_plate_detections(ann)
        if not plates:
            self._preview_selected_plate_by_image.pop(getattr(ann, "filename", ""), None)
            return None

        filename = str(getattr(ann, "filename", "") or "")
        idx = self._preview_selected_plate_by_image.get(filename, 0)
        if idx is None:
            idx = 0
        idx = max(0, min(int(idx), len(plates) - 1))
        self._preview_selected_plate_by_image[filename] = idx
        return idx

    def _set_selected_plate_index_for_ann(self, ann, plate_idx: int | None):
        plates = self._get_plate_detections(ann)
        filename = str(getattr(ann, "filename", "") or "")
        if not plates or plate_idx is None:
            self._preview_selected_plate_by_image.pop(filename, None)
            return None

        safe_idx = max(0, min(int(plate_idx), len(plates) - 1))
        self._preview_selected_plate_by_image[filename] = safe_idx
        return safe_idx

    @staticmethod
    def _get_vehicle_detections(ann) -> list[Detection]:
        if ann is None:
            return []
        return [det for det in ann.detections if str(det.label or "").lower() == "vehicle"]

    def _get_selected_vehicle_index_for_ann(self, ann) -> int | None:
        vehicles = self._get_vehicle_detections(ann)
        if not vehicles:
            self._preview_selected_vehicle_by_image.pop(getattr(ann, "filename", ""), None)
            return None

        filename = str(getattr(ann, "filename", "") or "")
        idx = self._preview_selected_vehicle_by_image.get(filename, 0)
        if idx is None:
            idx = 0
        idx = max(0, min(int(idx), len(vehicles) - 1))
        self._preview_selected_vehicle_by_image[filename] = idx
        return idx

    def _set_selected_vehicle_index_for_ann(self, ann, vehicle_idx: int | None):
        vehicles = self._get_vehicle_detections(ann)
        filename = str(getattr(ann, "filename", "") or "")
        if not vehicles or vehicle_idx is None:
            self._preview_selected_vehicle_by_image.pop(filename, None)
            return None

        safe_idx = max(0, min(int(vehicle_idx), len(vehicles) - 1))
        self._preview_selected_vehicle_by_image[filename] = safe_idx
        return safe_idx

    def _set_preview_focus_target(self, kind: str | None, index: int | None = None):
        filename = self._get_preview_focus_image_key()
        if not kind or index is None or not filename:
            self._preview_focus_target = None
            return
        self._preview_focus_target = {
            "filename": filename,
            "kind": str(kind),
            "index": int(index),
        }

    def _get_preview_focus_target(self) -> dict | None:
        target = getattr(self, "_preview_focus_target", None)
        if not isinstance(target, dict):
            return None
        if str(target.get("filename", "") or "") != self._get_preview_focus_image_key():
            return None
        return target

    def _mark_preview_image_dirty(self, ann, refresh_list: bool = True):
        if ann is None:
            return
        was_dirty = ann.filename in self._preview_dirty_images
        self._preview_dirty_images.add(ann.filename)
        if refresh_list and not was_dirty:
            self._refresh_preview_list(preserve_selection=True, render_current=False)
        elif not was_dirty:
            self._update_preview_toolbar_state()

    def _get_preview_history_image_key(self, ann=None) -> str:
        target_ann = self._get_preview_annotation() if ann is None else ann
        return str(getattr(target_ann, "filename", "") or "").strip()

    def _clone_preview_annotation_history_snapshot(self, ann=None):
        target_ann = self._get_preview_annotation() if ann is None else ann
        image_key = self._get_preview_history_image_key(target_ann)
        if target_ann is None or not image_key:
            return None
        return {
            "annotation": copy.deepcopy(target_ann),
            "selected_plate_idx": self._get_selected_plate_index_for_ann(target_ann),
            "selected_vehicle_idx": self._get_selected_vehicle_index_for_ann(target_ann),
        }

    def _get_preview_history_stack(self, kind: str, image_key: str | None = None, create: bool = False):
        key = str(image_key or self._get_preview_history_image_key() or "").strip()
        if not key:
            return None
        store_attr = "_preview_history_undo" if str(kind).lower() == "undo" else "_preview_history_redo"
        store = getattr(self, store_attr, None)
        if not isinstance(store, dict):
            store = {}
            setattr(self, store_attr, store)
        if create:
            return store.setdefault(key, [])
        return store.get(key)

    def _push_preview_history_snapshot(self, ann=None):
        if bool(getattr(self, "_preview_history_replaying", False)):
            return
        image_key = self._get_preview_history_image_key(ann)
        if not image_key:
            return

        snapshot = self._clone_preview_annotation_history_snapshot(ann)
        if snapshot is None:
            return

        undo_stack = self._get_preview_history_stack("undo", image_key, create=True)
        if isinstance(undo_stack, list) and undo_stack and undo_stack[-1] == snapshot:
            return

        undo_stack.append(snapshot)
        limit = max(10, int(getattr(self, "_preview_history_limit", 80) or 80))
        if len(undo_stack) > limit:
            del undo_stack[:-limit]

        redo_stack = self._get_preview_history_stack("redo", image_key, create=True)
        if isinstance(redo_stack, list):
            redo_stack.clear()

    def _restore_preview_annotation_history_snapshot(self, snapshot, *, action_label: str):
        ann = self._get_preview_annotation()
        image_key = self._get_preview_history_image_key(ann)
        if ann is None or not image_key or self.current_preview_index is None:
            return False

        restored_ann = None
        if isinstance(snapshot, dict):
            candidate = snapshot.get("annotation")
            if isinstance(candidate, ImageAnnotation):
                restored_ann = copy.deepcopy(candidate)
        if restored_ann is None:
            return False

        self._preview_history_replaying = True
        try:
            safe_index = int(self.current_preview_index)
            if safe_index < 0 or safe_index >= len(self.current_annotations):
                return False

            self.current_annotations[safe_index] = restored_ann
            selected_plate_idx = snapshot.get("selected_plate_idx") if isinstance(snapshot, dict) else None
            selected_vehicle_idx = snapshot.get("selected_vehicle_idx") if isinstance(snapshot, dict) else None
            self._set_selected_plate_index_for_ann(restored_ann, selected_plate_idx)
            self._set_selected_vehicle_index_for_ann(restored_ann, selected_vehicle_idx)
            self._preview_drag_state = None
            self._preview_pending_vertex_hit = None
            self._preview_draw_mode = False
            self._preview_draw_points = []
            self._preview_delete_mode = False
            self._preview_delete_candidate_idx = None
            self._mark_preview_image_dirty(restored_ann, refresh_list=True)
            self._refresh_preview_canvas()
            self._update_preview_toolbar_state()
            if self._save_preview_edits(interactive=False, status_message=action_label):
                self._update_preview_edit_status(action_label)
            else:
                self._update_preview_edit_status(
                    f"{action_label} Nie udalo sie od razu zapisac annotations.xml. Uzyj Ctrl+S."
                )
            self._remember_annotation_run_resume_state()
            self._queue_free_mode_session_save()
            try:
                self.preview_canvas.focus_set()
            except Exception:
                pass
            return True
        finally:
            self._preview_history_replaying = False

    def _clear_preview_editor_state(self, clear_dirty: bool = True):
        self._cancel_preview_list_population()
        has_pending_preview_save = bool(getattr(self, "_preview_dirty_images", None))
        has_unfinished_draw = bool(self._preview_draw_mode and self._preview_draw_points)
        if has_pending_preview_save and not has_unfinished_draw:
            try:
                self._save_preview_edits(
                    interactive=False,
                    status_message="Zapisano poprawki polygonow przed zamknieciem podgladu.",
                )
            except Exception:
                self._cancel_preview_autosave()
        else:
            self._cancel_preview_autosave()
        self._cancel_preview_drag_refresh()
        self._cancel_preview_layout_restore_jobs()
        if getattr(self, "_preview_fullscreen_active", False):
            self._set_preview_fullscreen(False)
        try:
            self.preview_canvas.grab_release()
        except Exception:
            pass
        try:
            self.preview_canvas.clear_image()
        except Exception:
            try:
                self.preview_canvas.original_image = None
                self.preview_canvas.photo_image = None
                self.preview_canvas.image_id = None
                self.preview_canvas.delete("all")
            except Exception:
                pass
        self.current_preview_index = None
        self._preview_drag_state = None
        self._preview_pending_vertex_hit = None
        self._preview_corner_drag_modifier_down = False
        self._preview_last_modifier_press_at = 0.0
        self._preview_draw_mode = False
        self._preview_draw_points = []
        self._preview_delete_mode = False
        self._preview_delete_candidate_idx = None
        self._preview_polygon_focus_restore_state = None
        self._preview_selected_plate_by_image = {}
        self._preview_selected_vehicle_by_image = {}
        self._preview_focus_target = None
        self._preview_history_undo = {}
        self._preview_history_redo = {}
        self._preview_history_replaying = False
        self._preview_list_display_indices = []
        if clear_dirty:
            self._preview_dirty_images.clear()
        self.current_annotation_run_dir = None
        self.current_annotation_xml_path = None
        self._refresh_preview_list_summary()
        self._update_preview_edit_status()

    def _cancel_preview_list_population(self):
        pending = getattr(self, "_preview_list_populate_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._preview_list_populate_after_id = None
        self._preview_list_populate_token = int(getattr(self, "_preview_list_populate_token", 0) or 0) + 1

    def _populate_preview_list_async(
        self,
        *,
        preserve_selection: bool = False,
        render_current: bool = True,
        batch_size: int = 200,
    ):
        self._cancel_preview_list_population()

        entries = self._get_preview_list_entries()
        self._preview_list_display_indices = [actual_idx for actual_idx, _ann in entries]
        selected_actual_index = self.current_preview_index if preserve_selection else None
        if selected_actual_index is None and entries:
            selected_actual_index = entries[0][0]
        selected_display_index = self._get_preview_display_index(selected_actual_index)
        if selected_display_index is None and entries:
            selected_actual_index = entries[0][0]
            selected_display_index = 0

        self.preview_listbox.delete(0, tk.END)
        self._refresh_preview_list_summary()

        if not entries:
            self.current_preview_index = None
            try:
                self.preview_canvas.clear_image()
            except Exception:
                self.preview_canvas.delete("all")
            self._update_preview_toolbar_state()
            self._update_preview_edit_status()
            return

        token = int(getattr(self, "_preview_list_populate_token", 0) or 0)
        selection_applied = False

        def apply_selection():
            nonlocal selection_applied
            if (
                selection_applied
                or selected_actual_index is None
                or selected_display_index is None
            ):
                return
            if token != int(getattr(self, "_preview_list_populate_token", 0) or 0):
                return

            previous_idx = self.current_preview_index
            self.preview_listbox.selection_clear(0, tk.END)
            self.preview_listbox.selection_set(selected_display_index)
            self.preview_listbox.activate(selected_display_index)
            self.preview_listbox.see(selected_display_index)
            self.current_preview_index = int(selected_actual_index)
            selection_applied = True

            if render_current:
                self._load_current_preview_selection(
                    reset_view=not preserve_selection,
                    selection_changed=(int(selected_actual_index) != previous_idx),
                )
            else:
                self._update_preview_toolbar_state()
                self._update_preview_edit_status()

        def insert_batch(start_index: int = 0):
            if token != int(getattr(self, "_preview_list_populate_token", 0) or 0):
                return

            end_index = min(start_index + max(1, int(batch_size)), len(entries))
            total_count = len(entries)
            for idx in range(start_index, end_index):
                _actual_idx, ann = entries[idx]
                self.preview_listbox.insert(
                    tk.END,
                    self._preview_list_item_text(
                        ann,
                        display_index=idx,
                        total_count=total_count,
                    ),
                )
                try:
                    item_color = self._preview_list_item_color(ann)
                    self.preview_listbox.itemconfig(idx, foreground=item_color)
                except Exception:
                    pass

            if (
                not selection_applied
                and selected_display_index is not None
                and selected_display_index < end_index
            ):
                apply_selection()

            if end_index < len(entries):
                try:
                    self._preview_list_populate_after_id = self.frame.after(
                        1,
                        lambda next_index=end_index: insert_batch(next_index),
                    )
                except Exception:
                    self._preview_list_populate_after_id = None
                    insert_batch(end_index)
                return

            self._preview_list_populate_after_id = None
            if not selection_applied:
                apply_selection()

        insert_batch(0)

    def _refresh_preview_list(self, preserve_selection: bool = True, render_current: bool = False):
        self._cancel_preview_list_population()
        entries = self._get_preview_list_entries()
        self._preview_list_display_indices = [actual_idx for actual_idx, _ann in entries]
        selected_actual_index = self.current_preview_index if preserve_selection else None
        if selected_actual_index is None and entries:
            selected_actual_index = entries[0][0]
        selected_display_index = self._get_preview_display_index(selected_actual_index)
        if selected_display_index is None and entries:
            selected_actual_index = entries[0][0]
            selected_display_index = 0

        self.preview_listbox.delete(0, tk.END)
        self._refresh_preview_list_summary()

        total_count = len(entries)
        for idx, (_actual_idx, ann) in enumerate(entries):
            self.preview_listbox.insert(
                tk.END,
                self._preview_list_item_text(
                    ann,
                    display_index=idx,
                    total_count=total_count,
                ),
            )
            try:
                item_color = self._preview_list_item_color(ann)
                self.preview_listbox.itemconfig(idx, foreground=item_color)
            except Exception:
                pass

        self.preview_listbox.selection_clear(0, tk.END)
        if selected_display_index is not None and selected_actual_index is not None and entries:
            self.preview_listbox.selection_set(selected_display_index)
            self.preview_listbox.activate(selected_display_index)
            self.preview_listbox.see(selected_display_index)
            self.current_preview_index = int(selected_actual_index)
            if render_current:
                self._load_current_preview_selection(reset_view=not preserve_selection, selection_changed=True)
        else:
            self.current_preview_index = None
            try:
                self.preview_canvas.clear_image()
            except Exception:
                self.preview_canvas.delete("all")
            self._update_preview_toolbar_state()
            self._update_preview_edit_status()

    def _populate_preview_list(self):
        if len(self.current_annotations or []) >= 500:
            self._populate_preview_list_async(
                preserve_selection=False,
                render_current=True,
                batch_size=200,
            )
            return
        self._refresh_preview_list(preserve_selection=False, render_current=True)

    def _select_preview_index(self, idx: int):
        if not self.current_annotations:
            return
        safe_idx = max(0, min(int(idx), len(self.current_annotations) - 1))
        previous_idx = self.current_preview_index
        display_idx = self._get_preview_display_index(safe_idx)
        if display_idx is None:
            display_idx = max(0, min(safe_idx, max(0, self.preview_listbox.size() - 1)))
        self.preview_listbox.selection_clear(0, tk.END)
        self.preview_listbox.selection_set(display_idx)
        self.preview_listbox.activate(display_idx)
        self.preview_listbox.see(display_idx)
        self.current_preview_index = safe_idx
        self._preview_session_restore_index = safe_idx
        self._preview_session_restore_filename = str(getattr(self.current_annotations[safe_idx], "filename", "") or "")
        self._remember_annotation_run_resume_state()
        self._load_current_preview_selection(reset_view=True, selection_changed=(safe_idx != previous_idx))
        self._queue_free_mode_session_save()
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass

    def _select_preview_relative(self, step: int):
        if not self.current_annotations:
            return "break"
        display_indices = list(getattr(self, "_preview_list_display_indices", []) or [])
        if not display_indices:
            current = 0 if self.current_preview_index is None else int(self.current_preview_index)
            self._select_preview_index(current + int(step))
            return "break"

        current_display = self._get_preview_display_index(self.current_preview_index)
        if current_display is None:
            current_display = 0
        target_display = max(0, min(int(current_display) + int(step), len(display_indices) - 1))
        target_actual = self._get_preview_actual_index_from_display(target_display)
        if target_actual is None:
            return "break"
        self._select_preview_index(target_actual)
        return "break"

    def _fit_preview_image_to_view(self):
        self._preview_polygon_focus_restore_state = None
        self._preview_focus_target = None
        try:
            if self.preview_canvas.original_image is not None:
                self.preview_canvas.fit_to_view()
                self.preview_canvas.focus_set()
        except Exception:
            pass
        self._push_preview_debug_event("fit", "dopasowano obraz do widoku")

    def _get_preview_legend_font(self, size: int, weight: str = "normal"):
        cache = getattr(self, "_preview_legend_font_cache", None)
        if cache is None:
            cache = {}
            self._preview_legend_font_cache = cache

        key = (int(size), str(weight))
        font_obj = cache.get(key)
        if font_obj is None:
            font_obj = tkfont.Font(self.frame, family="Segoe UI", size=int(size), weight=str(weight))
            cache[key] = font_obj
        return font_obj

    @staticmethod
    def _truncate_preview_filename(filename: str, max_chars: int = 44) -> str:
        text = str(filename or "").strip()
        if len(text) <= max_chars:
            return text
        head = max(10, (max_chars // 2) - 2)
        tail = max(10, max_chars - head - 3)
        return f"{text[:head]}...{text[-tail:]}"

    def _get_preview_legend_context(self):
        ann = self._get_preview_annotation()
        filename = self._truncate_preview_filename(getattr(ann, "filename", "Brak obrazu"))
        plates = self._get_plate_detections(ann)
        vehicles = self._get_vehicle_detections(ann)
        selected_idx = self._get_selected_plate_index_for_ann(ann) if ann is not None else None
        selected_vehicle_idx = self._get_selected_vehicle_index_for_ann(ann) if ann is not None else None
        current_no = 0 if not plates else ((int(selected_idx) + 1) if selected_idx is not None else 1)
        current_vehicle_no = 0 if not vehicles else ((int(selected_vehicle_idx) + 1) if selected_vehicle_idx is not None else 1)
        total_images = len(self.current_annotations or [])
        current_image_no = 0
        if self.current_preview_index is not None and total_images > 0:
            current_image_no = max(0, min(int(self.current_preview_index), total_images - 1)) + 1
        return {
            "filename": filename or "Brak obrazu",
            "image_text": f"Zdjecie: {current_image_no}/{total_images}",
            "vehicle_text": f"Pojazd: {current_vehicle_no}/{len(vehicles)}",
            "plate_text": f"Tablica: {current_no}/{len(plates)}",
        }

    def _draw_preview_overlay_badge(
        self,
        canvas,
        x: float,
        y: float,
        text: str,
        *,
        fill: str,
        outline: str,
        text_fill: str,
        fixed_width: float | None = None,
    ):
        font_obj = self._get_preview_legend_font(9, "bold")
        badge_width = None if fixed_width is None else max(24.0, float(fixed_width))
        badge_text = str(text)
        if badge_width is not None:
            badge_text = self._fit_preview_text_to_width(badge_text, badge_width - 22.0, font_obj)
        text_id = canvas.create_text(
            x + 11,
            y + 12,
            text=badge_text,
            fill=text_fill,
            anchor="w",
            font=font_obj,
            tags=("preview_overlay",)
        )
        bbox = canvas.bbox(text_id) or (x, y, x + 40, y + 18)
        rect_id = canvas.create_rectangle(
            x,
            y,
            (x + badge_width) if badge_width is not None else (bbox[2] + 7),
            max(y + 24, bbox[3] + 5),
            fill=fill,
            outline=outline,
            width=1,
            tags=("preview_overlay",)
        )
        canvas.tag_lower(rect_id, text_id)
        final_bbox = canvas.bbox(rect_id) or bbox
        return float(final_bbox[2] - final_bbox[0]), float(final_bbox[3] - final_bbox[1])

    def _fit_preview_text_to_width(self, text: str, max_width: float, font_obj) -> str:
        content = str(text or "")
        if not content:
            return ""
        try:
            limit = max(0.0, float(max_width or 0.0))
            if limit <= 0.0 or float(font_obj.measure(content)) <= limit:
                return content
            ellipsis = "..."
            if float(font_obj.measure(ellipsis)) > limit:
                return ""
            trimmed = content
            while trimmed and float(font_obj.measure(f"{trimmed}{ellipsis}")) > limit:
                trimmed = trimmed[:-1]
            return f"{trimmed.rstrip()}{ellipsis}" if trimmed else ellipsis
        except Exception:
            return content

    def _draw_preview_overlay_context(self, canvas: ZoomableCanvas):
        context = self._get_preview_legend_context()
        theme = self._get_preview_legend_theme()
        badge_font = self._get_preview_legend_font(9, "bold")
        fixed_tail_widths = (108.0, 108.0, 96.0)
        badge_specs = [
            (f"Plik: {context['filename']}", theme["badge_file_fill"], theme["badge_file_outline"], None),
            (context["image_text"], theme["badge_image_fill"], theme["badge_image_outline"], fixed_tail_widths[0]),
            (context["vehicle_text"], theme["badge_image_fill"], theme["badge_image_outline"], fixed_tail_widths[1]),
            (context["plate_text"], theme["badge_plate_fill"], theme["badge_plate_outline"], fixed_tail_widths[2]),
        ]

        try:
            max_row_width = max(260.0, float(canvas.winfo_width() or 0.0) - 14.0)
        except Exception:
            max_row_width = 720.0

        file_width = max(
            150.0,
            min(
                280.0,
                max_row_width - sum(fixed_tail_widths) - (8.0 * 3.0) - 28.0,
            ),
        )
        badge_specs[0] = (
            badge_specs[0][0],
            badge_specs[0][1],
            badge_specs[0][2],
            file_width,
        )

        x = 14.0
        y = 14.0
        gap = 8.0
        row_bottom = y
        for badge_text, badge_fill, badge_outline, badge_width in badge_specs:
            estimated_width = max(44.0, float(badge_width or (float(badge_font.measure(str(badge_text))) + 22.0)))
            if x > 14.0 and (x + estimated_width) > max_row_width:
                x = 14.0
                y = row_bottom + 8.0
            badge_width, badge_height = self._draw_preview_overlay_badge(
                canvas,
                x,
                y,
                badge_text,
                fill=badge_fill,
                outline=badge_outline,
                text_fill=self._get_preview_legend_text_color(badge_fill),
                fixed_width=estimated_width,
            )
            row_bottom = max(row_bottom, y + badge_height)
            x += badge_width + gap

    @staticmethod
    def _legend_color_is_light(color: str) -> bool:
        value = str(color or "").strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        if len(value) != 6:
            return False
        try:
            red = int(value[0:2], 16)
            green = int(value[2:4], 16)
            blue = int(value[4:6], 16)
        except Exception:
            return False
        luminance = ((0.2126 * red) + (0.7152 * green) + (0.0722 * blue)) / 255.0
        return luminance >= 0.62

    def _get_preview_legend_text_color(self, fill: str) -> str:
        palette = getattr(self.app, "palette", {})
        if self._legend_color_is_light(fill):
            return palette.get("fg", "#111111")
        return palette.get("accent_text", "#ffffff")

    def _get_preview_legend_theme(self) -> dict:
        palette = getattr(self.app, "palette", {})
        panel = palette.get("panel", "#252526")
        panel_alt = palette.get("panel_alt", panel)
        field = palette.get("field", panel)
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        accent = palette.get("accent", "#0e639c")
        success = palette.get("success", "#2fbf71")
        warning = palette.get("warning", "#f59e0b")

        return {
            "canvas_bg": panel,
            "panel_fill": panel_alt,
            "panel_outline": border,
            "label_fill": palette.get("fg", "#f3f3f3"),
            "muted_fill": palette.get("muted_dim", palette.get("muted", "#8f98a3")),
            "entry_fill": blend_hex_colors(panel_alt, panel, 0.28),
            "entry_text": palette.get("fg", "#f3f3f3"),
            "token_fill": field,
            "token_text": palette.get("fg", "#f8fafc"),
            "badge_file_fill": palette.get("surface_info", blend_hex_colors(accent, panel_alt, 0.72)),
            "badge_file_outline": accent,
            "badge_image_fill": palette.get("surface_warning", blend_hex_colors(warning, panel_alt, 0.72)),
            "badge_image_outline": warning,
            "badge_plate_fill": palette.get("surface_success", blend_hex_colors(success, panel_alt, 0.72)),
            "badge_plate_outline": success,
        }

    def _measure_preview_legend_token(self, token_kind: str, token_text: str, font_obj) -> float:
        if token_kind == "mouse":
            return max(48.0, float(font_obj.measure(str(token_text))) + 38.0)
        return max(26.0, float(font_obj.measure(str(token_text))) + 14.0)

    def _draw_preview_legend_badge(self, canvas, x: float, y: float, text: str, *, fill: str, outline: str, text_fill: str):
        font_obj = self._get_preview_legend_font(10, "bold")
        text_id = canvas.create_text(
            x + 12,
            y + 9,
            text=str(text),
            fill=text_fill,
            anchor="nw",
            font=font_obj,
            tags=("preview_legend",)
        )
        bbox = canvas.bbox(text_id) or (x, y, x + 40, y + 18)
        rect_id = canvas.create_rectangle(
            bbox[0] - 8,
            bbox[1] - 5,
            bbox[2] + 8,
            bbox[3] + 5,
            fill=fill,
            outline=outline,
            width=1,
            tags=("preview_legend",)
        )
        canvas.tag_lower(rect_id, text_id)
        final_bbox = canvas.bbox(rect_id) or bbox
        return float(final_bbox[2] - final_bbox[0]), float(final_bbox[3] - final_bbox[1])

    def _draw_preview_legend_keycap(self, canvas, x: float, y: float, text: str, *, fill: str, outline: str, text_fill: str):
        font_obj = self._get_preview_legend_font(9, "bold")
        width = self._measure_preview_legend_token("key", text, font_obj)
        height = 24.0
        rect_id = canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            fill=fill,
            outline=outline,
            width=1,
            tags=("preview_legend",)
        )
        canvas.create_line(
            x + 1,
            y + 1,
            x + width - 1,
            y + 1,
            fill="#ffffff",
            width=1,
            tags=("preview_legend",)
        )
        canvas.create_text(
            x + (width / 2.0),
            y + (height / 2.0) + 0.5,
            text=str(text),
            fill=text_fill,
            anchor="center",
            font=font_obj,
            tags=("preview_legend",)
        )
        return float(width), float(height)

    def _draw_preview_legend_mousecap(self, canvas, x: float, y: float, text: str, *, fill: str, outline: str, text_fill: str):
        font_obj = self._get_preview_legend_font(7, "bold")
        width = self._measure_preview_legend_token("mouse", text, font_obj)
        height = 24.0
        rect_id = canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            fill=fill,
            outline=outline,
            width=1,
            tags=("preview_legend",)
        )
        body_left = x + 7
        body_top = y + 3
        body_right = body_left + 16
        body_bottom = y + 21
        center_x = (body_left + body_right) / 2.0
        highlight_left = str(text).upper() == "LPM"
        highlight_right = str(text).upper() == "PPM"
        canvas.create_oval(
            body_left,
            body_top,
            body_right,
            body_bottom,
            fill="#f7f9fb",
            outline=outline,
            width=1,
            tags=("preview_legend",)
        )
        canvas.create_rectangle(
            body_left + 1,
            body_top + 1,
            center_x - 1,
            body_top + 8,
            fill=(outline if highlight_left else "#f7f9fb"),
            outline="",
            tags=("preview_legend",)
        )
        canvas.create_rectangle(
            center_x + 1,
            body_top + 1,
            body_right - 1,
            body_top + 8,
            fill=(outline if highlight_right else "#f7f9fb"),
            outline="",
            tags=("preview_legend",)
        )
        canvas.create_line(
            center_x,
            body_top + 1,
            center_x,
            body_top + 9,
            fill=outline,
            width=1,
            tags=("preview_legend",)
        )
        canvas.create_text(
            body_right + 8,
            y + (height / 2.0) + 0.5,
            text=str(text),
            fill=text_fill,
            anchor="w",
            font=font_obj,
            tags=("preview_legend",)
        )
        canvas.tag_lower(rect_id)
        return float(width), float(height)

    def _build_preview_legend_entries(self):
        return [
            {"tokens": [("key", "Q"), ("key", "E")], "connector": "/", "label": "zdjecie", "accent": "#2f80ed"},
            {"tokens": [("key", "A")], "connector": "", "label": "tablica", "accent": "#14b8a6"},
            {"tokens": [("key", "Spacja")], "connector": "", "label": "pojazd", "accent": "#16a34a"},
            {"tokens": [("key", "R")], "connector": "", "label": "plate box", "accent": "#f59e0b"},
            {"tokens": [("key", "F")], "connector": "", "label": "dopasuj", "accent": "#64748b"},
            {"tokens": [("key", "W"), ("mouse", "LPM")], "connector": "+", "label": "rog", "accent": "#fb923c"},
            {"tokens": [("key", "D")], "connector": "", "label": "nowa", "accent": "#22c55e"},
            {"tokens": [("key", "S")], "connector": "", "label": "zaznacz", "accent": "#ef4444"},
            {"tokens": [("mouse", "PPM")], "connector": "", "label": "usun tablice", "accent": "#dc2626"},
            {"tokens": [("key", "Ctrl+Z"), ("key", "Ctrl+Y")], "connector": "/", "label": "historia", "accent": "#a855f7"},
            {"tokens": [("key", "Ctrl+S")], "connector": "", "label": "zapisz", "accent": "#0ea5e9"},
            {"tokens": [("key", "Enter"), ("key", "Esc")], "connector": "/", "label": "fullscreen", "accent": "#94a3b8"},
        ]

    def _refresh_preview_controls_legend(self):
        canvas = getattr(self, "preview_controls_canvas", None)
        if canvas is None:
            return

        if not bool(getattr(self, "_preview_fullscreen_active", False)):
            try:
                canvas.delete("all")
                canvas.configure(height=1)
            except Exception:
                pass
            return

        try:
            canvas.update_idletasks()
        except Exception:
            pass

        width = max(420.0, float(canvas.winfo_width() or 0.0))
        canvas.delete("all")
        legend_theme = self._get_preview_legend_theme()
        bg_fill = legend_theme["panel_fill"]
        bg_outline = legend_theme["panel_outline"]
        label_fill = legend_theme["label_fill"]
        plus_fill = legend_theme["muted_fill"]
        try:
            canvas.configure(bg=legend_theme["canvas_bg"])
        except Exception:
            pass
        desc_font = self._get_preview_legend_font(9, "normal")

        background_id = canvas.create_rectangle(
            1,
            1,
            width - 2,
            80,
            fill=bg_fill,
            outline=bg_outline,
            width=1,
            tags=("preview_legend",)
        )

        entries = self._build_preview_legend_entries()
        x = 14.0
        y = 10.0
        token_gap = 10.0
        entry_gap_x = 7.0
        entry_gap_y = 7.0
        entry_pad_x = 8.0
        entry_pad_top = 6.0
        entry_pad_bottom = 5.0
        label_gap_y = 4.0
        label_font = self._get_preview_legend_font(8, "bold")
        label_height = float(label_font.metrics("linespace"))
        token_row_height = 24.0
        entry_height = entry_pad_top + token_row_height + label_gap_y + label_height + entry_pad_bottom
        bottom = y + entry_height

        for entry in entries:
            token_specs = list(entry.get("tokens", []))
            connector_text = str(entry.get("connector", "") or "")
            accent = str(entry.get("accent", "#3498db"))
            label = str(entry.get("label", "") or "")
            token_widths = []
            token_width = 0.0
            for idx, (token_kind, token_text) in enumerate(token_specs):
                if idx > 0:
                    token_width += token_gap
                token_font = self._get_preview_legend_font(7 if token_kind == "mouse" else 9, "bold")
                current_width = self._measure_preview_legend_token(token_kind, token_text, token_font)
                token_widths.append(float(current_width))
                token_width += float(current_width)
            label_width = float(label_font.measure(label))
            content_width = max(token_width, label_width)
            entry_width = content_width + (entry_pad_x * 2.0)

            if x > 14.0 and (x + entry_width) > (width - 18.0):
                x = 14.0
                y += entry_height + entry_gap_y

            entry_rect = canvas.create_rectangle(
                x,
                y,
                x + entry_width,
                y + entry_height,
                fill=legend_theme["entry_fill"],
                outline=accent,
                width=1,
                tags=("preview_legend",)
            )

            token_x = x + entry_pad_x + max(0.0, (content_width - token_width) / 2.0)
            token_y = y + entry_pad_top
            prev_right = None
            for idx, (token_kind, token_text) in enumerate(token_specs):
                if idx > 0:
                    if connector_text:
                        plus_x = float(prev_right) + (token_gap / 2.0)
                        canvas.create_text(
                            plus_x,
                            token_y + 13.5,
                            text=connector_text,
                            fill=plus_fill,
                            anchor="center",
                            font=self._get_preview_legend_font(8, "bold"),
                            tags=("preview_legend",)
                        )
                token_w = token_widths[idx]
                if token_kind == "mouse":
                    _drawn_w, _token_h = self._draw_preview_legend_mousecap(
                        canvas,
                        token_x,
                        token_y,
                        token_text,
                        fill=legend_theme["token_fill"],
                        outline=accent,
                        text_fill=legend_theme["token_text"],
                    )
                else:
                    _drawn_w, _token_h = self._draw_preview_legend_keycap(
                        canvas,
                        token_x,
                        token_y,
                        token_text,
                        fill=legend_theme["token_fill"],
                        outline=accent,
                        text_fill=legend_theme["token_text"],
                    )
                prev_right = token_x + token_w
                if idx < (len(token_specs) - 1):
                    token_x = prev_right + token_gap

            canvas.create_text(
                x + (entry_width / 2.0),
                y + entry_pad_top + token_row_height + label_gap_y + (label_height / 2.0),
                text=label,
                fill=legend_theme["entry_text"],
                anchor="center",
                font=label_font,
                tags=("preview_legend",)
            )
            canvas.tag_lower(entry_rect)
            bottom = max(bottom, y + entry_height)
            x += entry_width + entry_gap_x

        total_height = max(62.0, bottom + 10.0)
        canvas.coords(background_id, 1, 1, width - 2, total_height - 2)
        try:
            canvas.configure(height=int(total_height))
        except Exception:
            pass
        canvas.tag_lower(background_id)

    def _get_preview_focus_image_key(self, ann=None) -> str:
        target_ann = self._get_preview_annotation() if ann is None else ann
        return str(getattr(target_ann, "filename", "") or "")

    def _preview_focus_restore_matches_current_image(self) -> bool:
        state = getattr(self, "_preview_polygon_focus_restore_state", None)
        if not isinstance(state, dict):
            return False
        return str(state.get("filename", "") or "") == self._get_preview_focus_image_key()

    def _capture_preview_view_state(self):
        if getattr(self.preview_canvas, "original_image", None) is None:
            return None
        state = dict(self.preview_canvas.get_view_state())
        state["filename"] = self._get_preview_focus_image_key()
        return state

    def _compute_preview_bbox_focus_view_state(
        self,
        bbox: tuple[float, float, float, float],
        *,
        pad_x_ratio: float = 0.20,
        pad_y_ratio: float = 0.25,
        min_padding: float = 16.0,
    ):
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None or canvas.original_image is None or not bbox:
            return None

        try:
            canvas.update_idletasks()
        except Exception:
            pass

        canvas_width = max(1.0, float(canvas.winfo_width()))
        canvas_height = max(1.0, float(canvas.winfo_height()))
        if canvas_width <= 1.0 or canvas_height <= 1.0:
            return None

        min_x, min_y, max_x, max_y = [float(v) for v in bbox]
        box_width = max(1.0, float(max_x) - float(min_x))
        box_height = max(1.0, float(max_y) - float(min_y))
        padding_x = max(float(min_padding), box_width * float(pad_x_ratio))
        padding_y = max(float(min_padding), box_height * float(pad_y_ratio))

        image_width = max(1.0, float(canvas.original_image.width))
        image_height = max(1.0, float(canvas.original_image.height))
        box_min_x = max(0.0, float(min_x) - padding_x)
        box_min_y = max(0.0, float(min_y) - padding_y)
        box_max_x = min(image_width - 1.0, float(max_x) + padding_x)
        box_max_y = min(image_height - 1.0, float(max_y) + padding_y)
        box_width = max(1.0, box_max_x - box_min_x)
        box_height = max(1.0, box_max_y - box_min_y)

        zoom_level = min(
            canvas_width / box_width,
            canvas_height / box_height,
            float(getattr(canvas, "max_zoom", 5.0) or 5.0),
        )
        zoom_level = max(float(getattr(canvas, "min_zoom", 0.1) or 0.1), float(zoom_level))

        center_x = (box_min_x + box_max_x) / 2.0
        center_y = (box_min_y + box_max_y) / 2.0
        origin_x = (canvas_width / 2.0) - (center_x * zoom_level)
        origin_y = (canvas_height / 2.0) - (center_y * zoom_level)

        return {
            "zoom_level": float(zoom_level),
            "origin_x": float(origin_x),
            "origin_y": float(origin_y),
        }

    def _compute_preview_plate_focus_view_state(self, polygon: list[tuple[float, float]]):
        if not polygon:
            return None
        return self._compute_preview_bbox_focus_view_state(
            self._bbox_from_polygon(polygon),
            pad_x_ratio=0.20,
            pad_y_ratio=0.25,
            min_padding=16.0,
        )

    def _focus_preview_plate(
        self,
        plate_idx: int | None = None,
        *,
        store_restore: bool = True,
        push_debug: bool = True,
        status_message: str | None = None,
    ) -> bool:
        ann = self._get_preview_annotation()
        canvas = getattr(self, "preview_canvas", None)
        if ann is None or canvas is None or canvas.original_image is None:
            return False

        plate_detections = self._get_plate_detections(ann)
        if not plate_detections:
            return False

        if not self._preview_focus_restore_matches_current_image():
            self._preview_polygon_focus_restore_state = None

        if plate_idx is None:
            plate_idx = self._get_selected_plate_index_for_ann(ann)
        if plate_idx is None:
            plate_idx = 0

        safe_idx = self._set_selected_plate_index_for_ann(ann, int(plate_idx))
        if safe_idx is None:
            return False

        if store_restore and self._preview_polygon_focus_restore_state is None:
            self._preview_polygon_focus_restore_state = self._capture_preview_view_state()

        polygon = self._detection_polygon(plate_detections[int(safe_idx)])
        view_state = self._compute_preview_plate_focus_view_state(polygon)
        if not isinstance(view_state, dict):
            return False

        if not canvas.set_view_state(view_state, redraw=True):
            return False

        self._set_preview_focus_target("plate", int(safe_idx))

        if push_debug:
            self._push_preview_debug_event(
                "focus-plate",
                (
                    f"p{int(safe_idx) + 1} zoom={float(view_state.get('zoom_level', 0.0)):.3f} "
                    f"origin=({float(view_state.get('origin_x', 0.0)):.1f},{float(view_state.get('origin_y', 0.0)):.1f})"
                )
            )
        if status_message:
            self._update_preview_edit_status(status_message)
        else:
            self._update_preview_edit_status()
        try:
            canvas.focus_set()
        except Exception:
            pass
        return True

    def _focus_preview_vehicle(
        self,
        vehicle_idx: int | None = None,
        *,
        store_restore: bool = True,
        push_debug: bool = True,
        status_message: str | None = None,
    ) -> bool:
        ann = self._get_preview_annotation()
        canvas = getattr(self, "preview_canvas", None)
        if ann is None or canvas is None or canvas.original_image is None:
            return False

        vehicle_detections = self._get_vehicle_detections(ann)
        if not vehicle_detections:
            return False

        if not self._preview_focus_restore_matches_current_image():
            self._preview_polygon_focus_restore_state = None

        if vehicle_idx is None:
            vehicle_idx = self._get_selected_vehicle_index_for_ann(ann)
        if vehicle_idx is None:
            vehicle_idx = 0

        safe_idx = self._set_selected_vehicle_index_for_ann(ann, int(vehicle_idx))
        if safe_idx is None:
            return False

        if store_restore and self._preview_polygon_focus_restore_state is None:
            self._preview_polygon_focus_restore_state = self._capture_preview_view_state()

        view_state = self._compute_preview_bbox_focus_view_state(
            tuple(float(v) for v in vehicle_detections[int(safe_idx)].bbox[:4]),
            pad_x_ratio=0.015,
            pad_y_ratio=0.02,
            min_padding=6.0,
        )
        if not isinstance(view_state, dict):
            return False

        if not canvas.set_view_state(view_state, redraw=True):
            return False

        self._set_preview_focus_target("vehicle", int(safe_idx))

        if push_debug:
            self._push_preview_debug_event(
                "focus-vehicle",
                (
                    f"v{int(safe_idx) + 1} zoom={float(view_state.get('zoom_level', 0.0)):.3f} "
                    f"origin=({float(view_state.get('origin_x', 0.0)):.1f},{float(view_state.get('origin_y', 0.0)):.1f})"
                )
            )
        if status_message:
            self._update_preview_edit_status(status_message)
        else:
            self._update_preview_edit_status()
        try:
            canvas.focus_set()
        except Exception:
            pass
        return True

    def _restore_preview_focus_view(self, status_message: str | None = None) -> bool:
        if not self._preview_focus_restore_matches_current_image():
            self._preview_polygon_focus_restore_state = None
            self._preview_focus_target = None
            return False

        restore_state = dict(self._preview_polygon_focus_restore_state or {})
        self._preview_polygon_focus_restore_state = None
        self._preview_focus_target = None
        if not self.preview_canvas.set_view_state(restore_state, redraw=True):
            return False

        self._push_preview_debug_event(
            "focus-restore",
            (
                f"zoom={float(restore_state.get('zoom_level', 0.0)):.3f} "
                f"origin=({float(restore_state.get('origin_x', 0.0)):.1f},{float(restore_state.get('origin_y', 0.0)):.1f})"
            )
        )
        if status_message:
            self._update_preview_edit_status(status_message)
        else:
            self._update_preview_edit_status()
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass
        return True

    def _restore_preview_layout_view_after_resize(self):
        if bool(getattr(self, "_preview_force_fit_after_resize", False)):
            self._preview_force_fit_after_resize = False
            self._preview_polygon_focus_restore_state = None
            self._preview_focus_target = None
            self._fit_preview_image_to_view()
            return

        if self._preview_focus_restore_matches_current_image():
            ann = self._get_preview_annotation()
            focus_target = self._get_preview_focus_target()
            focus_kind = str((focus_target or {}).get("kind", "") or "")
            focus_index = (focus_target or {}).get("index")
            if focus_kind == "vehicle":
                if self._focus_preview_vehicle(focus_index, store_restore=False, push_debug=False, status_message=None):
                    self._push_preview_debug_event("focus-layout", "odswiezono fokus pojazdu po zmianie ukladu")
                    return
            else:
                selected_idx = self._get_selected_plate_index_for_ann(ann) if ann is not None else None
                if focus_index is not None:
                    selected_idx = int(focus_index)
                if self._focus_preview_plate(selected_idx, store_restore=False, push_debug=False, status_message=None):
                    self._push_preview_debug_event("focus-layout", "odswiezono fokus polygonu po zmianie ukladu")
                    return
            self._preview_polygon_focus_restore_state = None
            self._preview_focus_target = None

        self._fit_preview_image_to_view()

    def _cancel_preview_layout_restore_jobs(self):
        pending = list(getattr(self, "_preview_layout_restore_after_ids", []) or [])
        self._preview_layout_restore_after_ids = []
        for after_id in pending:
            try:
                self.frame.after_cancel(after_id)
            except Exception:
                pass

    def _schedule_preview_layout_restore_after_resize(self):
        self._cancel_preview_layout_restore_jobs()

        def schedule(delay_ms: int, attempt: int, last_size: tuple[int, int] | None = None, stable_count: int = 0):
            try:
                after_id = self.frame.after(
                    int(delay_ms),
                    lambda a=attempt, ls=last_size, sc=stable_count: self._stabilize_preview_layout_after_resize(a, ls, sc),
                )
                self._preview_layout_restore_after_ids.append(after_id)
            except Exception:
                pass

        schedule(0, 0, None, 0)

    def _stabilize_preview_layout_after_resize(
        self,
        attempt: int = 0,
        last_size: tuple[int, int] | None = None,
        stable_count: int = 0,
    ):
        self._preview_layout_restore_after_ids = [
            after_id
            for after_id in (getattr(self, "_preview_layout_restore_after_ids", []) or [])
            if after_id
        ]

        try:
            canvas = self.preview_canvas
        except Exception:
            return

        if canvas is None or getattr(canvas, "original_image", None) is None:
            self._cancel_preview_layout_restore_jobs()
            return

        try:
            canvas.update_idletasks()
        except Exception:
            pass

        try:
            current_size = (max(1, int(canvas.winfo_width() or 1)), max(1, int(canvas.winfo_height() or 1)))
        except Exception:
            current_size = (1, 1)

        self._restore_preview_layout_view_after_resize()

        next_stable = (stable_count + 1) if last_size == current_size else 0
        if attempt >= 8 or next_stable >= 2:
            self._cancel_preview_layout_restore_jobs()
            return

        try:
            after_id = self.frame.after(
                70,
                lambda a=attempt + 1, ls=current_size, sc=next_stable: self._stabilize_preview_layout_after_resize(a, ls, sc),
            )
            self._preview_layout_restore_after_ids.append(after_id)
        except Exception:
            pass

    def _format_preview_debug_vertex_ref(self, plate_idx: int | None, vertex_idx: int | None) -> str:
        if plate_idx is None or int(plate_idx) < 0:
            return "-"
        vertex_part = "-" if vertex_idx is None or int(vertex_idx) < 0 else f"v{int(vertex_idx) + 1}"
        return f"p{int(plate_idx) + 1}:{vertex_part}"

    def _format_preview_debug_pending(self) -> str:
        pending = getattr(self, "_preview_pending_vertex_hit", None)
        if not isinstance(pending, dict):
            return "-"
        return (
            f"{self._format_preview_debug_vertex_ref(pending.get('plate_idx'), pending.get('vertex_idx'))} "
            f"anchor=({float(pending.get('anchor_canvas_x', 0.0)):.1f},{float(pending.get('anchor_canvas_y', 0.0)):.1f})"
        )

    def _format_preview_debug_drag(self) -> str:
        drag_state = getattr(self, "_preview_drag_state", None)
        if not isinstance(drag_state, dict):
            return "-"
        return (
            f"{self._format_preview_debug_vertex_ref(drag_state.get('plate_idx'), drag_state.get('vertex_idx'))} "
            f"started={int(bool(drag_state.get('drag_started', False)))} "
            f"moved={int(bool(drag_state.get('was_moved', False)))} "
            f"press=({float(drag_state.get('press_canvas_x', 0.0)):.1f},{float(drag_state.get('press_canvas_y', 0.0)):.1f})"
        )

    def _build_preview_debug_lines(self, history_limit: int = 4):
        ann = self._get_preview_annotation()
        filename = str(getattr(ann, "filename", "-") or "-")
        selected_plate = self._get_selected_plate_index_for_ann(ann) if ann is not None else None
        if selected_plate is None:
            selected_plate_text = "-"
        else:
            selected_plate_text = str(int(selected_plate) + 1)

        zoom_value = float(getattr(self.preview_canvas, "zoom_level", 0.0) or 0.0)
        try:
            origin_x, origin_y = self.preview_canvas.get_image_origin()
        except Exception:
            origin_x, origin_y = 0.0, 0.0

        history = list(getattr(self, "_preview_debug_events", []) or [])
        history_text = " | ".join(history[:history_limit]) if history else "-"
        return [
            "DEBUG Z2",
            (
                f"img={filename} idx={self.current_preview_index if self.current_preview_index is not None else '-'} "
                f"sel_plate={selected_plate_text} zoom={zoom_value:.3f} origin=({origin_x:.1f},{origin_y:.1f})"
            ),
            (
                f"flags: W={int(bool(self._preview_corner_drag_modifier_down))} "
                f"draw={int(bool(self._preview_draw_mode))} delete={int(bool(self._preview_delete_mode))} "
                f"fullscreen={int(bool(self._preview_fullscreen_active))} "
                f"focus={int(bool(self._preview_focus_restore_matches_current_image()))} "
                f"dirty={len(self._preview_dirty_images)}"
            ),
            f"pending: {self._format_preview_debug_pending()}",
            f"drag: {self._format_preview_debug_drag()}",
            f"history: {history_text}",
        ]

    def _refresh_preview_debug_status(self):
        if not bool(getattr(self, "_preview_debug_enabled", False)):
            return
        self.preview_debug_var.set("\n".join(self._build_preview_debug_lines(history_limit=4)))

    def _print_preview_debug_console(self, event_name: str, detail: str = ""):
        if not bool(getattr(self, "_preview_debug_enabled", False)):
            return
        summary = f"[DEBUG Z2] event={event_name}"
        if detail:
            summary += f" {detail}"
        output_lines = [summary]
        for line in self._build_preview_debug_lines(history_limit=6)[1:]:
            output_lines.append(f"[DEBUG Z2] {line}")
        if event_name in {"select", "zoom", "press-target", "press-handle", "press-polygon", "press-miss"}:
            output_lines.append(f"[DEBUG Z2] {self._describe_selected_polygon_vertices_debug()}")
        for line in output_lines:
            print(line, flush=True)
        try:
            log_path = Path(getattr(self, "_preview_debug_log_path", Path(CONFIG.WORKSPACE_DIR) / "z2_debug.log"))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(output_lines))
                fh.write("\n")
        except Exception:
            pass

    def _push_preview_debug_event(self, event_name: str, detail: str = "", refresh_only: bool = False):
        if not bool(getattr(self, "_preview_debug_enabled", False)):
            return

        if not refresh_only:
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            event_text = f"{stamp} {event_name}"
            if detail:
                event_text += f" {detail}"
            self._preview_debug_events.appendleft(event_text)
        self._refresh_preview_debug_status()
        if not refresh_only:
            self._print_preview_debug_console(event_name, detail)

    @staticmethod
    def _widget_is_descendant_of(widget, ancestor) -> bool:
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = getattr(current, "master", None)
        return False

    @staticmethod
    def _event_has_control_modifier(event=None) -> bool:
        if event is None:
            return False
        try:
            return bool(int(getattr(event, "state", 0) or 0) & 0x0004)
        except Exception:
            return False

    def _preview_shortcuts_enabled(self, event=None, allow_when_fullscreen: bool = False) -> bool:
        if allow_when_fullscreen and bool(getattr(self, "_preview_fullscreen_active", False)):
            return True

        if self._preview_drag_state is not None or self._preview_corner_drag_modifier_down or self._preview_delete_mode:
            return True

        target_widget = getattr(event, "widget", None)
        if target_widget is None:
            try:
                target_widget = self.frame.focus_get()
            except Exception:
                target_widget = None

        if self._widget_is_descendant_of(target_widget, getattr(self, "preview_host", None)):
            return True

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
        except Exception:
            return False

        for widget in (
            getattr(self, "preview_canvas", None),
            getattr(self, "preview_listbox", None),
            getattr(self, "preview_host", None),
        ):
            if self._widget_contains_point(widget, x_root, y_root):
                return True

        return False

    @staticmethod
    def _pane_has_child(pane, child) -> bool:
        try:
            return str(child) in [str(item) for item in pane.panes()]
        except Exception:
            return False

    def _bind_preview_shortcuts(self):
        bindings = (
            ("<KeyPress-w>", self._on_preview_edit_modifier_press),
            ("<KeyPress-W>", self._on_preview_edit_modifier_press),
            ("<KeyRelease-w>", self._on_preview_edit_modifier_release),
            ("<KeyRelease-W>", self._on_preview_edit_modifier_release),
            ("<KeyPress-d>", self._on_preview_draw_toggle_shortcut),
            ("<KeyPress-D>", self._on_preview_draw_toggle_shortcut),
            ("<KeyPress-s>", self._on_preview_delete_mode_shortcut),
            ("<KeyPress-S>", self._on_preview_delete_mode_shortcut),
            ("<KeyPress-r>", self._on_preview_focus_toggle_shortcut),
            ("<KeyPress-R>", self._on_preview_focus_toggle_shortcut),
            ("<KeyPress-f>", self._on_preview_fit_shortcut),
            ("<KeyPress-F>", self._on_preview_fit_shortcut),
            ("<KeyPress-a>", self._on_preview_cycle_plate_shortcut),
            ("<KeyPress-A>", self._on_preview_cycle_plate_shortcut),
            ("<KeyPress-space>", self._on_preview_cycle_vehicle_shortcut),
            ("<KeyPress-q>", self._on_preview_prev_shortcut),
            ("<KeyPress-Q>", self._on_preview_prev_shortcut),
            ("<KeyPress-e>", self._on_preview_next_shortcut),
            ("<KeyPress-E>", self._on_preview_next_shortcut),
            ("<Delete>", self._on_preview_delete_image_shortcut),
            ("<Control-s>", self._on_preview_save_shortcut),
            ("<Control-S>", self._on_preview_save_shortcut),
            ("<Control-z>", self._on_preview_undo_shortcut),
            ("<Control-Z>", self._on_preview_undo_shortcut),
            ("<Control-y>", self._on_preview_redo_shortcut),
            ("<Control-Y>", self._on_preview_redo_shortcut),
            ("<Return>", self._on_preview_enter_fullscreen_shortcut),
            ("<Escape>", self._on_preview_escape_shortcut),
        )
        preview_widgets = (
            getattr(self, "preview_canvas", None),
            getattr(self, "preview_listbox", None),
        )
        for sequence, handler in bindings:
            for widget in preview_widgets:
                if widget is not None:
                    widget.bind(sequence, handler, add="+")
            self.frame.bind_all(sequence, handler, add="+")

    def _on_preview_prev_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        return self._select_preview_relative(-1)

    def _on_preview_next_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        return self._select_preview_relative(1)

    def _on_preview_edit_modifier_press(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        self._set_preview_corner_drag_modifier(True)
        return "break"

    def _on_preview_edit_modifier_release(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        self._set_preview_corner_drag_modifier(False)
        return "break"

    def _on_preview_draw_toggle_shortcut(self, event=None):
        if self._event_has_control_modifier(event):
            return None
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        self._toggle_preview_draw_mode()
        return "break"

    def _on_preview_delete_mode_shortcut(self, event=None):
        if self._event_has_control_modifier(event):
            return None
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        self._toggle_preview_delete_mode()
        return "break"

    def _on_preview_delete_image_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if not self._preview_is_editable():
            self._update_preview_edit_status(
                "Usuwanie obrazu jest dostepne dopiero po przygotowaniu annotations.xml."
            )
            return "break"
        return self._delete_current_preview_image_hard(event)

    def _on_preview_save_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if not self._preview_is_editable():
            self._update_preview_edit_status(
                "Zapis poprawek bedzie dostepny po przygotowaniu annotations.xml."
            )
            return "break"
        self._save_preview_edits()
        return "break"

    def _on_preview_undo_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if not self._preview_is_editable():
            return "break"
        return self._undo_preview_edit(event)

    def _on_preview_redo_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if not self._preview_is_editable():
            return "break"
        return self._redo_preview_edit(event)

    def _on_preview_fit_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        self._fit_preview_image_to_view()
        self._update_preview_edit_status()
        return "break"

    def _on_preview_focus_toggle_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if self._preview_draw_mode:
            self._update_preview_edit_status(
                "Dokoncz albo anuluj rysowanie nowego polygonu przed uzyciem R."
            )
            return "break"

        if self._preview_focus_restore_matches_current_image():
            self._restore_preview_focus_view(
                "Przywrócono poprzedni kadr. R ponownie zbliża aktywny polygon."
            )
            return "break"

        ann = self._get_preview_annotation()
        plates = self._get_plate_detections(ann)
        if not plates:
            self._update_preview_edit_status("Na tym obrazie nie ma polygonu tablicy do zblizenia klawiszem R.")
            return "break"

        selected_idx = self._get_selected_plate_index_for_ann(ann)
        self._focus_preview_plate(
            selected_idx,
            store_restore=True,
            push_debug=True,
            status_message="Widok został dopasowany do aktywnego polygonu. R wraca do poprzedniego kadru, A przełącza tablice.",
        ) or self._update_preview_edit_status("Nie udalo sie dopasowac widoku do aktywnego polygonu.")
        return "break"

    def _on_preview_cycle_plate_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if self._preview_draw_mode:
            self._update_preview_edit_status(
                "Dokoncz albo anuluj rysowanie nowego polygonu przed uzyciem A."
            )
            return "break"

        ann = self._get_preview_annotation()
        plates = self._get_plate_detections(ann)
        if not plates:
            self._update_preview_edit_status("Na tym obrazie nie ma polygonów tablicy do przełączania klawiszem A.")
            return "break"

        current_idx = self._get_selected_plate_index_for_ann(ann)
        if current_idx is None:
            current_idx = -1
        target_idx = (int(current_idx) + 1) % len(plates)

        if not self._preview_focus_restore_matches_current_image():
            self._preview_polygon_focus_restore_state = self._capture_preview_view_state()

        if self._focus_preview_plate(
            target_idx,
            store_restore=False,
            push_debug=False,
            status_message=(
                f"Aktywna tablica {int(target_idx) + 1}/{len(plates)}. "
                "A przełącza kolejne polygony, R wraca do poprzedniego kadru."
            ),
        ):
            self._push_preview_debug_event("cycle-plate", f"p{int(target_idx) + 1}/{len(plates)}")
        else:
            self._update_preview_edit_status("Nie udalo sie dopasowac widoku do wybranej tablicy.")
        return "break"

    def _on_preview_cycle_vehicle_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if self._preview_draw_mode:
            self._update_preview_edit_status(
                "Dokoncz albo anuluj rysowanie nowego polygonu przed uzyciem Spacji."
            )
            return "break"

        ann = self._get_preview_annotation()
        vehicles = self._get_vehicle_detections(ann)
        if not vehicles:
            self._update_preview_edit_status("Na tym obrazie nie ma boxów pojazdów do przełączania klawiszem Spacja.")
            return "break"

        current_idx = self._get_selected_vehicle_index_for_ann(ann)
        focus_active = self._preview_focus_restore_matches_current_image()
        if focus_active:
            if current_idx is None:
                current_idx = -1
            target_idx = (int(current_idx) + 1) % len(vehicles)
        else:
            target_idx = 0 if current_idx is None else int(current_idx)
            self._preview_polygon_focus_restore_state = self._capture_preview_view_state()

        if self._focus_preview_vehicle(
            target_idx,
            store_restore=False,
            push_debug=False,
            status_message=(
                f"Aktywny pojazd {int(target_idx) + 1}/{len(vehicles)}. "
                "Spacja przełącza kolejne auta, D dodaje tablicę, R kadruje aktywną tablicę."
            ),
        ):
            self._push_preview_debug_event("cycle-vehicle", f"v{int(target_idx) + 1}/{len(vehicles)}")
        else:
            self._update_preview_edit_status("Nie udalo sie dopasowac widoku do wybranego pojazdu.")
        return "break"

    def _on_preview_enter_fullscreen_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        self._set_preview_fullscreen(True)
        return "break"

    def _on_preview_escape_shortcut(self, event=None):
        if not bool(getattr(self, "_preview_fullscreen_active", False)):
            return None
        self._set_preview_fullscreen(False)
        return "break"

    def _toggle_preview_fullscreen(self):
        self._set_preview_fullscreen(not bool(getattr(self, "_preview_fullscreen_active", False)))

    def _apply_preview_fullscreen_chrome(self):
        preview_tools = getattr(self, "preview_tools", None)
        preview_hint_label = getattr(self, "preview_fullscreen_hint_lbl", None)
        preview_hint_frame = getattr(self, "preview_hint_frame", None)
        canvas_frame = getattr(self, "canvas_frame", None)
        status_label = getattr(self, "preview_edit_status_lbl", None)
        debug_label = getattr(self, "preview_debug_lbl", None)
        log_tools = getattr(self, "log_tools", None)

        if bool(getattr(self, "_preview_fullscreen_active", False)):
            try:
                if preview_tools is not None:
                    preview_tools.pack_forget()
            except Exception:
                pass
            try:
                if preview_hint_label is not None:
                    preview_hint_label.pack_forget()
            except Exception:
                pass
            try:
                if status_label is not None:
                    status_label.pack_forget()
            except Exception:
                pass
            try:
                if debug_label is not None:
                    debug_label.pack_forget()
            except Exception:
                pass
            try:
                if log_tools is not None:
                    log_tools.pack_forget()
            except Exception:
                pass
            try:
                if preview_hint_frame is not None and not str(preview_hint_frame.winfo_manager()):
                    preview_hint_frame.pack(fill=tk.X, pady=(0, 8), before=canvas_frame)
                    self._refresh_preview_controls_legend()
            except Exception:
                pass
            return

        try:
            if preview_hint_frame is not None and str(preview_hint_frame.winfo_manager()):
                preview_hint_frame.pack_forget()
        except Exception:
            pass
        try:
            hint_text = str(self.preview_fullscreen_hint_var.get() or "").strip() if preview_hint_label is not None else ""
            if preview_hint_label is not None:
                if hint_text:
                    if not str(preview_hint_label.winfo_manager()):
                        preview_hint_label.pack(fill=tk.X, pady=(0, 8), before=canvas_frame)
                elif str(preview_hint_label.winfo_manager()):
                    preview_hint_label.pack_forget()
        except Exception:
            pass
        try:
            if status_label is not None and not str(status_label.winfo_manager()):
                status_label.pack(fill=tk.X, pady=(8, 0), after=canvas_frame)
        except Exception:
            pass
        try:
            if log_tools is not None and str(log_tools.winfo_manager()):
                log_tools.pack_forget()
        except Exception:
            pass
        if bool(getattr(self, "_preview_debug_enabled", False)):
            try:
                if debug_label is not None and not str(debug_label.winfo_manager()):
                    debug_label.pack(fill=tk.X, pady=(6, 0), after=status_label)
            except Exception:
                pass

    def _set_preview_fullscreen(self, active: bool):
        next_state = bool(active)
        if next_state == bool(getattr(self, "_preview_fullscreen_active", False)):
            if next_state:
                try:
                    self.preview_canvas.focus_set()
                except Exception:
                    pass
            return

        has_image = getattr(self.preview_canvas, "original_image", None) is not None
        if next_state and not has_image:
            self._update_preview_edit_status("Pełny ekran jest dostępny po załadowaniu obrazu podglądu.")
            return

        root = getattr(self.app, "root", None)
        try:
            windowing_system = str(self.frame.tk.call("tk", "windowingsystem")).lower()
        except Exception:
            windowing_system = ""
        use_native_root_fullscreen = windowing_system not in {"win32"}

        if next_state:
            self._preview_fullscreen_restore_log_visible = bool(getattr(self, "_annotation_log_visible", False))
            try:
                self._preview_fullscreen_restore_root_state = bool(root.attributes("-fullscreen")) if root is not None else False
            except Exception:
                self._preview_fullscreen_restore_root_state = False
            try:
                self._preview_fullscreen_restore_window_state = str(root.state()) if root is not None else "normal"
            except Exception:
                self._preview_fullscreen_restore_window_state = "normal"
            try:
                self._preview_fullscreen_restore_geometry = str(root.geometry()) if root is not None else ""
            except Exception:
                self._preview_fullscreen_restore_geometry = ""

            if self._pane_has_child(self.main_pane, self.main_left_frame):
                self.main_pane.forget(self.main_left_frame)
            if self._pane_has_child(self.main_pane, self.main_right_frame):
                self.main_pane.forget(self.main_right_frame)
            self._set_annotation_process_log_visibility(False)
            if root is not None:
                try:
                    if use_native_root_fullscreen:
                        root.attributes("-fullscreen", True)
                    else:
                        root.attributes("-fullscreen", False)
                        try:
                            root.state("zoomed")
                        except Exception:
                            screen_w = int(root.winfo_screenwidth())
                            screen_h = int(root.winfo_screenheight())
                            root.geometry(f"{screen_w}x{screen_h}+0+0")
                except Exception:
                    pass
            self._preview_fullscreen_active = True
        else:
            if root is not None:
                try:
                    if use_native_root_fullscreen:
                        root.attributes("-fullscreen", bool(getattr(self, "_preview_fullscreen_restore_root_state", False)))
                    else:
                        root.attributes("-fullscreen", False)
                        restore_state = str(getattr(self, "_preview_fullscreen_restore_window_state", "normal") or "normal")
                        restore_geometry = str(getattr(self, "_preview_fullscreen_restore_geometry", "") or "")
                        try:
                            root.state(restore_state if restore_state in {"normal", "zoomed"} else "normal")
                        except Exception:
                            pass
                        if restore_state != "zoomed" and restore_geometry:
                            try:
                                root.geometry(restore_geometry)
                            except Exception:
                                pass
                except Exception:
                    pass

            self._preview_polygon_focus_restore_state = None
            self._preview_focus_target = None
            self._preview_force_fit_after_resize = True
            if not self._pane_has_child(self.main_pane, self.main_left_frame):
                self.main_pane.insert(0, self.main_left_frame, weight=2)
            if self._should_show_right_panel() and not self._pane_has_child(self.main_pane, self.main_right_frame):
                self.main_pane.add(self.main_right_frame, weight=1)

            self._set_annotation_process_log_visibility(bool(getattr(self, "_preview_fullscreen_restore_log_visible", False)))
            self._preview_fullscreen_active = False

        self._update_preview_toolbar_state()
        self._update_preview_edit_status()
        self._apply_preview_fullscreen_chrome()
        self._push_preview_debug_event(
            "fullscreen",
            f"active={int(bool(self._preview_fullscreen_active))} mode={'native' if use_native_root_fullscreen else 'zoomed'} ws={windowing_system or '-'}"
        )
        self._schedule_preview_layout_restore_after_resize()
        if not self._preview_fullscreen_active:
            self._schedule_main_pane_layout_refresh(force_defaults=False, delay_ms=80)
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass

    def _toggle_preview_draw_mode(self):
        ann = self._get_preview_annotation()
        if ann is None or self.preview_canvas.original_image is None:
            return
        if not self._preview_is_editable():
            self._update_preview_edit_status(
                f"Ten podgląd jest tylko informacyjny. Najpierw kliknij {self._get_step2_start_action_reference()}, aby przygotować annotations.xml."
            )
            return

        if self._preview_draw_mode:
            self._preview_draw_mode = False
            self._preview_draw_points = []
        else:
            self._preview_delete_mode = False
            self._preview_delete_candidate_idx = None
            self._preview_drag_state = None
            self._preview_draw_mode = True
            self._preview_draw_points = []

        self._refresh_preview_canvas()
        self._update_preview_edit_status()
        self._update_preview_toolbar_state()
        self._push_preview_debug_event("draw-mode", f"{'on' if self._preview_draw_mode else 'off'}")
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass

    def _toggle_preview_delete_mode(self):
        ann = self._get_preview_annotation()
        if ann is None or self.preview_canvas.original_image is None:
            return
        if not self._preview_is_editable():
            self._update_preview_edit_status(
                f"Ten podgląd jest tylko informacyjny. Najpierw kliknij {self._get_step2_start_action_reference()}, aby przygotować annotations.xml."
            )
            return

        plates = self._get_plate_detections(ann)
        if not self._preview_delete_mode and not plates:
            self._update_preview_edit_status("Na tym obrazie nie ma polygonu tablicy do usunięcia.")
            return

        if self._preview_delete_mode:
            self._preview_delete_mode = False
            self._preview_delete_candidate_idx = None
        else:
            if self._preview_draw_mode:
                self._preview_draw_mode = False
                self._preview_draw_points = []
            if self._preview_drag_state is not None:
                self._finish_preview_vertex_drag(
                    mark_dirty=bool(self._preview_drag_state.get("was_moved", False))
                )
            self._set_preview_corner_drag_modifier(False)
            self._preview_pending_vertex_hit = None
            pointer_canvas = self._get_preview_pointer_canvas_position()
            hovered_idx = None
            if pointer_canvas is not None:
                hovered_idx = self._find_preview_polygon_hit(float(pointer_canvas[0]), float(pointer_canvas[1]))

            if hovered_idx is None:
                self._preview_delete_mode = False
                self._preview_delete_candidate_idx = None
                self._refresh_preview_canvas()
                self._update_preview_edit_status(
                    "Najedz kursorem na wnetrze polygonu i nacisnij S, aby od razu uzbroic usuwanie tej tablicy."
                )
                self._push_preview_debug_event("delete-mode", "off no-hover-target")
                try:
                    self.preview_canvas.focus_set()
                except Exception:
                    pass
                return

            self._preview_delete_mode = True
            self._preview_delete_candidate_idx = int(hovered_idx)
            self._set_selected_plate_index_for_ann(ann, int(hovered_idx))

        self._refresh_preview_canvas()
        self._update_preview_edit_status()
        self._update_preview_toolbar_state()
        if self._preview_delete_mode and self._preview_delete_candidate_idx is not None:
            self._push_preview_debug_event("delete-mode", f"on p{int(self._preview_delete_candidate_idx) + 1}")
        else:
            self._push_preview_debug_event("delete-mode", "off")
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass

    def _set_preview_corner_drag_modifier(self, active: bool):
        next_state = bool(active)
        if bool(getattr(self, "_preview_corner_drag_modifier_down", False)) == next_state:
            return

        self._preview_corner_drag_modifier_down = next_state
        if next_state:
            self._preview_last_modifier_press_at = time.monotonic()
        else:
            self._preview_last_modifier_press_at = 0.0
        try:
            self.preview_canvas.pan_data["press_x"] = None
            self.preview_canvas.pan_data["press_y"] = None
        except Exception:
            pass
        self._sync_preview_canvas_cursor()
        if not next_state:
            self._preview_pending_vertex_hit = None
        if not next_state and self._preview_drag_state is not None:
            self._finish_preview_vertex_drag(
                mark_dirty=bool(self._preview_drag_state.get("was_moved", False))
            )
            return
        if not next_state and self._preview_drag_state is None and self._preview_dirty_images:
            self._schedule_preview_autosave(delay_ms=120)

        self._push_preview_debug_event("modifier", f"W={'on' if next_state else 'off'}")
        self._refresh_preview_canvas()
        self._update_preview_edit_status()

    def _preview_modifier_active(self) -> bool:
        return bool(getattr(self, "_preview_corner_drag_modifier_down", False))

    def _begin_preview_vertex_drag(
        self,
        plate_idx: int,
        vertex_idx: int,
        anchor_canvas_x: float,
        anchor_canvas_y: float,
    ):
        # Szybka seria korekt nie powinna byc przerywana opoznionym zapisem poprzedniego ruchu.
        self._cancel_preview_autosave()
        self._preview_last_modifier_press_at = time.monotonic()
        start_cursor_x = 0.0
        start_cursor_y = 0.0
        start_vertex_x = 0.0
        start_vertex_y = 0.0

        ann = self._get_preview_annotation()
        if ann is not None and self.preview_canvas.original_image is not None:
            plate_detections = self._get_plate_detections(ann)
            if 0 <= int(plate_idx) < len(plate_detections):
                polygon = self._detection_polygon(plate_detections[int(plate_idx)])
                if 0 <= int(vertex_idx) < len(polygon):
                    start_vertex_x, start_vertex_y = polygon[int(vertex_idx)]
                    start_cursor_x, start_cursor_y = self.preview_canvas.canvas_to_image_coords(
                        anchor_canvas_x,
                        anchor_canvas_y,
                        clamp=True,
                    )

        self._preview_drag_state = {
            "plate_idx": int(plate_idx),
            "vertex_idx": int(vertex_idx),
            "press_canvas_x": float(anchor_canvas_x),
            "press_canvas_y": float(anchor_canvas_y),
            "start_cursor_x": float(start_cursor_x),
            "start_cursor_y": float(start_cursor_y),
            "start_vertex_x": float(start_vertex_x),
            "start_vertex_y": float(start_vertex_y),
            "drag_started": False,
            "was_moved": False,
        }
        self._preview_pending_vertex_hit = None

        try:
            self.preview_canvas.pan_data["press_x"] = None
            self.preview_canvas.pan_data["press_y"] = None
            self.preview_canvas.grab_set()
        except Exception:
            pass

    def _on_preview_canvas_focus_out(self, event=None):
        try:
            self.preview_canvas.pan_data["press_x"] = None
            self.preview_canvas.pan_data["press_y"] = None
        except Exception:
            pass

        try:
            self.preview_canvas.grab_release()
        except Exception:
            pass

        self._preview_pending_vertex_hit = None
        if self._preview_drag_state is not None:
            self._finish_preview_vertex_drag(
                mark_dirty=bool(self._preview_drag_state.get("was_moved", False))
            )
        self._push_preview_debug_event("focus-out", "canvas utracil fokus")

    def on_zoomable_canvas_should_block_pan(self, canvas: ZoomableCanvas, event):
        if canvas is not self.preview_canvas:
            return False

        if self._preview_draw_mode:
            return True

        if self._preview_delete_mode:
            return True

        if self._preview_drag_state is not None:
            return True

        if self._preview_pending_vertex_hit is not None:
            return True

        return bool(self._preview_corner_drag_modifier_down)

    def on_zoomable_canvas_zoom(self, canvas: ZoomableCanvas, event):
        if canvas is not self.preview_canvas:
            return False
        self._push_preview_debug_event(
            "zoom",
            f"level={float(getattr(canvas, 'zoom_level', 0.0) or 0.0):.3f} at=({float(getattr(event, 'x', 0.0)):.1f},{float(getattr(event, 'y', 0.0)):.1f})"
        )
        return False

    def _get_preview_canvas_cursor(self) -> str:
        if bool(getattr(self, "_preview_draw_mode", False)):
            return "crosshair"
        if bool(getattr(self, "_preview_corner_drag_modifier_down", False)):
            return "crosshair"
        return "arrow"

    def _undo_preview_edit(self, event=None):
        image_key = self._get_preview_history_image_key()
        undo_stack = self._get_preview_history_stack("undo", image_key, create=False)
        if not image_key or not isinstance(undo_stack, list) or not undo_stack:
            self._update_preview_edit_status("Brak zmian do cofniecia.")
            return "break"

        current_snapshot = self._clone_preview_annotation_history_snapshot()
        redo_stack = self._get_preview_history_stack("redo", image_key, create=True)
        if current_snapshot is not None:
            redo_stack.append(current_snapshot)

        target_snapshot = undo_stack.pop()
        self._restore_preview_annotation_history_snapshot(
            target_snapshot,
            action_label="Cofnieto ostatnia zmiane polygonow tablic.",
        )
        return "break"

    def _redo_preview_edit(self, event=None):
        image_key = self._get_preview_history_image_key()
        redo_stack = self._get_preview_history_stack("redo", image_key, create=False)
        if not image_key or not isinstance(redo_stack, list) or not redo_stack:
            self._update_preview_edit_status("Brak zmian do ponowienia.")
            return "break"

        current_snapshot = self._clone_preview_annotation_history_snapshot()
        undo_stack = self._get_preview_history_stack("undo", image_key, create=True)
        if current_snapshot is not None:
            undo_stack.append(current_snapshot)

        target_snapshot = redo_stack.pop()
        self._restore_preview_annotation_history_snapshot(
            target_snapshot,
            action_label="Przywrócono ostatnią cofniętą zmianę polygonów tablic.",
        )
        return "break"

    def _sync_preview_canvas_cursor(self):
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return

        desired_cursor = self._get_preview_canvas_cursor()
        try:
            canvas.current_cursor = desired_cursor
        except Exception:
            pass

        try:
            if canvas.pan_data.get("press_x") is None and canvas.pan_data.get("press_y") is None:
                canvas.config(cursor=desired_cursor)
        except Exception:
            try:
                canvas.config(cursor=desired_cursor)
            except Exception:
                pass

    def _preview_is_editable(self) -> bool:
        if self._get_preview_annotation() is None:
            return False
        return self._get_current_annotation_xml_path() is not None

    def _get_step2_start_action_label(self) -> str:
        try:
            route = self._get_workflow_route()
        except Exception:
            route = ""

        if route == "manual":
            try:
                if self._get_manual_entry_mode() == "new":
                    return "Utwórz XML + boxy" if self._manual_vehicle_assist_enabled() else "Utwórz XML"
            except Exception:
                pass
        elif route == "auto":
            try:
                return (
                    "Uruchom autoanotację tablic"
                    if self._get_auto_vehicle_choice() == "skip"
                    else "Uruchom autoanotację tablic + pojazdów"
                )
            except Exception:
                pass

        try:
            label = str(self.start_btn.cget("text") or "").strip()
        except Exception:
            label = ""
        generic_labels = {
            "",
            "START",
            "Start",
            "Wybierz tor",
            "Wybierz model",
            "Wybierz obrazy",
            "Run istnieje",
        }
        return "" if label in generic_labels else label

    def _get_step2_start_action_reference(self) -> str:
        label = self._get_step2_start_action_label()
        if label:
            return f"„{label}”"
        return "główny przycisk po lewej stronie"

    def _update_preview_toolbar_state(self):
        total = len(self.current_annotations)
        has_selection = self.current_preview_index is not None and total > 0
        has_image = has_selection and getattr(self.preview_canvas, "original_image", None) is not None
        can_edit = bool(has_image and self._preview_is_editable())
        display_total = len(getattr(self, "_preview_list_display_indices", []) or [])
        current_display_index = self._get_preview_display_index(self.current_preview_index) if has_selection else None
        navigation_total = max(display_total, total)
        can_go_prev = has_selection and current_display_index is not None and int(current_display_index) > 0
        can_go_next = (
            has_selection
            and current_display_index is not None
            and int(current_display_index) < (navigation_total - 1)
        )
        has_dirty = bool(self._preview_dirty_images)
        can_move_to_stage = bool(
            can_edit
            and getattr(self, "current_input_dir", None) is not None
            and not self._is_manual_plate_stage_input(self.current_input_dir)
        )
        self._refresh_preview_list_summary()

        try:
            self.preview_prev_btn.configure(state=(tk.NORMAL if can_go_prev else tk.DISABLED))
            self.preview_next_btn.configure(state=(tk.NORMAL if can_go_next else tk.DISABLED))
            self.preview_fit_btn.configure(state=(tk.NORMAL if has_image else tk.DISABLED))
            self.preview_draw_btn.configure(state=(tk.NORMAL if can_edit else tk.DISABLED))
            self.preview_draw_btn.configure(text=("Anuluj rysowanie (D)" if self._preview_draw_mode else "Nowy polygon 4 pkt (D)"))
            if hasattr(self, "preview_fullscreen_btn"):
                self.preview_fullscreen_btn.configure(
                    state=(tk.NORMAL if has_image else tk.DISABLED),
                    text=("Wyjdź z pełnego ekranu (Esc)" if self._preview_fullscreen_active else "Pełny ekran (Enter)")
                )
            if hasattr(self, "preview_move_stage_btn"):
                self.preview_move_stage_btn.configure(state=(tk.NORMAL if can_move_to_stage else tk.DISABLED))
            if hasattr(self, "preview_delete_image_btn"):
                self.preview_delete_image_btn.configure(state=(tk.NORMAL if can_edit else tk.DISABLED))
            self.preview_save_btn.configure(state=(tk.NORMAL if (can_edit and has_dirty) else tk.DISABLED))
        except Exception:
            pass

        try:
            if self._preview_fullscreen_active:
                self.preview_fullscreen_hint_var.set("")
                self._set_inline_label_state(self.preview_fullscreen_hint_lbl, tone="info", emphasis=False)
            elif has_image:
                self.preview_fullscreen_hint_var.set(
                    "Pełny ekran włączysz klawiszem Enter. Po włączeniu zobaczysz pasek skrótów, a Esc przywraca zwykły widok."
                )
                self._set_inline_label_state(self.preview_fullscreen_hint_lbl, tone="info", emphasis=False)
            else:
                self.preview_fullscreen_hint_var.set(
                    "Wybierz obraz, aby włączyć pełny ekran i narzędzia edycji podglądu."
                )
                self._set_inline_label_state(self.preview_fullscreen_hint_lbl, tone="muted", emphasis=False)
        except Exception:
            pass

        self._sync_preview_canvas_cursor()

    @staticmethod
    def _preview_draw_corner_label(point_idx: int) -> str:
        labels = {
            1: "1 rog",
            2: "2 rog",
            3: "3 rog",
            4: "4 rog",
        }
        return labels.get(int(point_idx), f"{int(point_idx)} rog")

    def _preview_campaign_reuse_manual_note(self, ann, *, editable: bool) -> str:
        if not self._preview_annotation_is_reused_from_previous_manual(ann):
            return ""

        summary = dict(getattr(self, "_campaign_reuse_manual_summary", {}) or {})
        source_label = str(summary.get("source_label") or "wcześniejszej iteracji")
        if editable:
            return f" To zdjęcie oznaczone jako {self._campaign_reuse_manual_badge()} pochodzi z ręcznej anotacji z {source_label}."
        return (
            f" To zdjęcie oznaczone jako {self._campaign_reuse_manual_badge()} pochodzi z ręcznej anotacji z {source_label}; "
            "nowy run autoanotacji nadpisze poprzednie ręczne oznaczenia."
        )

    def _update_preview_edit_status(self, extra_message: str | None = None):
        if extra_message:
            self.preview_edit_status_var.set(extra_message)
            self._update_preview_toolbar_state()
            self._refresh_preview_debug_status()
            self._refresh_preview_controls_legend()
            return

        ann = self._get_preview_annotation()
        if ann is None:
            self.preview_edit_status_var.set("Po zakończeniu anotacji tutaj poprawisz rogi tablic.")
            self._update_preview_toolbar_state()
            self._refresh_preview_controls_legend()
            return

        if not self._preview_is_editable():
            self.preview_edit_status_var.set(
                f"{ann.filename} | tryb tylko do podglądu. Najpierw kliknij {self._get_step2_start_action_reference()}, aby przygotować annotations.xml albo uruchomić autoanotację."
                f"{self._preview_campaign_reuse_manual_note(ann, editable=False)}"
            )
            self._update_preview_toolbar_state()
            self._refresh_preview_debug_status()
            self._refresh_preview_controls_legend()
            return

        plates = self._get_plate_detections(ann)
        vehicles = self._get_vehicle_detections(ann)
        dirty_note = " | niezapisane zmiany" if ann.filename in self._preview_dirty_images else ""
        selected_vehicle_idx = self._get_selected_vehicle_index_for_ann(ann)
        vehicle_hint = ""
        if vehicles:
            vehicle_no = 1 if selected_vehicle_idx is None else (int(selected_vehicle_idx) + 1)
            vehicle_hint = f" Aktywny pojazd {vehicle_no}/{len(vehicles)}. Spacja kadruje kolejne pojazdy."

        if self._preview_draw_mode:
            clicked_points = len(self._preview_draw_points)
            next_idx = clicked_points + 1
            next_corner = self._preview_draw_corner_label(next_idx)
            self.preview_edit_status_var.set(
                f"{ann.filename} | tryb rysowania aktywny{dirty_note}. "
                f"Kliknij w {next_corner} tablicy ({next_idx}/4). "
                f"Po zaznaczeniu 4 punktow polygon domknie sie automatycznie. D anuluje rysowanie.{vehicle_hint}"
            )
        elif self._preview_delete_mode:
            if self._preview_delete_candidate_idx is not None:
                self.preview_edit_status_var.set(
                    f"{ann.filename} | tryb usuwania aktywny{dirty_note}. Polygon {int(self._preview_delete_candidate_idx) + 1}/{len(plates)} jest zaznaczony na czerwono. "
                    "Kliknij PPM, aby go usunac, albo nacisnij S, aby anulowac tryb usuwania."
                )
            else:
                self.preview_edit_status_var.set(
                    f"{ann.filename} | tryb usuwania aktywny{dirty_note}. Kliknij wewnątrz polygonu, aby zaznaczyć tablicę do usunięcia. "
                    "PPM usuwa zaznaczony polygon, S anuluje tryb."
                )
        elif not plates:
            self.preview_edit_status_var.set(
                f"{ann.filename} | brak wykrytej tablicy{dirty_note}. "
                f"Użyj 'Nowy polygon 4 pkt (D)', aby dodać ręczną anotację.{vehicle_hint}"
            )
        else:
            selected_idx = self._get_selected_plate_index_for_ann(ann)
            plate_no = 0 if selected_idx is None else selected_idx + 1
            self.preview_edit_status_var.set(
                f"{ann.filename} | tablica {plate_no}/{len(plates)}{dirty_note}. "
                "Kliknij polygon, aby go wybrać, przeciągnij róg, aby poprawić geometrię. "
                "Q/E przełączają zdjęcia."
            )
            drag_hint = (
                "W wciśnięte: możesz przeciągać rogi."
                if self._preview_corner_drag_modifier_down
                else "Przytrzymaj W i przeciągnij róg, aby poprawić geometrię."
            )
            fullscreen_hint = (
                "Esc wychodzi z pełnego ekranu."
                if self._preview_fullscreen_active
                else "Enter włącza pełny ekran."
            )
            self.preview_edit_status_var.set(
                f"{ann.filename} | tablica {plate_no}/{len(plates)}{dirty_note}. "
                f"Kliknij polygon, aby go wybrać. {drag_hint} "
                f"Q/E przełączają zdjęcia, A przełącza tablice, Spacja kadruje pojazdy, R kadruje aktywny polygon, F dopasowuje widok, D rysuje nowy polygon, S uzbraja usuwanie, Del usuwa zdjęcie, Ctrl+Z/Ctrl+Y cofają i ponawiają, Ctrl+S zapisuje poprawki. {fullscreen_hint}{vehicle_hint}"
                f"{self._preview_campaign_reuse_manual_note(ann, editable=True)}"
            )

        self._update_preview_toolbar_state()
        self._refresh_preview_debug_status()
        self._refresh_preview_controls_legend()

    def _load_current_preview_selection(self, reset_view: bool = True, selection_changed: bool = True):
        ann = self._get_preview_annotation()
        if ann is None:
            try:
                self.preview_canvas.clear_image()
            except Exception:
                pass
            self._update_preview_edit_status()
            self._update_preview_toolbar_state()
            return

        if selection_changed:
            try:
                self.preview_canvas.grab_release()
            except Exception:
                pass
            self._preview_drag_state = None
            self._preview_pending_vertex_hit = None
            self._preview_draw_mode = False
            self._preview_draw_points = []
            self._preview_delete_mode = False
            self._preview_delete_candidate_idx = None
            self._preview_polygon_focus_restore_state = None
            self._preview_focus_target = None
            self._push_preview_debug_event(
                "select",
                f"idx={self.current_preview_index if self.current_preview_index is not None else '-'} file={getattr(ann, 'filename', '-')}"
            )

        self._render_preview_image(ann, reset_view=reset_view)
        self._update_preview_edit_status()
        self._update_preview_toolbar_state()

    def _render_preview_image(self, ann, reset_view: bool = True):
        img_path = self._resolve_preview_image_path(ann)

        if img_path is None or not img_path.exists():
            self.preview_canvas.clear_image()
            self.preview_canvas.create_text(20, 20, text="Plik nie istnieje na dysku!", fill="red", anchor="nw")
            self._update_preview_toolbar_state()
            return

        try:
            img = cv2.imread(str(img_path))
            if img is None:
                raise ValueError("Nie można załadować obrazu do podglądu.")

            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            self.preview_canvas.set_image(Image.fromarray(img_rgb))
            if reset_view:
                self.preview_canvas.fit_to_view()
                self._preview_force_fit_after_resize = True
                self._schedule_preview_layout_restore_after_resize()
        except Exception as e:
            logger.error(f"Blad rysowania podgladu YOLO: {e}")
            self.preview_canvas.clear_image()
            self.preview_canvas.create_text(20, 20, text=f"Blad podgladu: {e}", fill="red", anchor="nw")

    def _refresh_preview_canvas(self, rerender_image: bool = False):
        try:
            if self.preview_canvas.original_image is not None:
                if rerender_image:
                    self.preview_canvas._update_display()
                else:
                    self.preview_canvas.refresh_overlay_only()
        except Exception:
            pass

    def _cancel_preview_drag_refresh(self):
        pending = getattr(self, "_preview_drag_refresh_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._preview_drag_refresh_after_id = None

    def _schedule_preview_drag_refresh(self, delay_ms: int = 0):
        if getattr(self, "_preview_drag_refresh_after_id", None):
            return

        def _flush():
            self._preview_drag_refresh_after_id = None
            self._refresh_preview_canvas()

        try:
            self._preview_drag_refresh_after_id = self.frame.after(max(0, int(delay_ms)), _flush)
        except Exception:
            self._preview_drag_refresh_after_id = None
            self._refresh_preview_canvas()

    def _draw_annotation_preview_overlay(self, canvas: ZoomableCanvas):
        ann = self._get_preview_annotation()
        if ann is None or canvas.original_image is None:
            return

        drag_active = isinstance(getattr(self, "_preview_drag_state", None), dict)
        vehicle_color = "#2ecc71"
        plate_color = "#e74c3c"
        active_color = "#f1c40f"
        delete_color = "#ff4d4d"
        handle_fill = "#ffffff"
        handle_outline = "#111111"
        label_fill = "#f8f8f8"
        label_bg = "#111111"

        vehicle_detections = self._get_vehicle_detections(ann)
        selected_vehicle_idx = self._get_selected_vehicle_index_for_ann(ann)
        plate_detections = self._get_plate_detections(ann)
        selected_plate_idx = self._get_selected_plate_index_for_ann(ann)
        delete_candidate_idx = (
            int(self._preview_delete_candidate_idx)
            if self._preview_delete_mode and self._preview_delete_candidate_idx is not None
            else None
        )

        for vehicle_idx, det in enumerate(vehicle_detections):
            if drag_active and selected_vehicle_idx is not None and vehicle_idx != selected_vehicle_idx:
                continue
            x1, y1, x2, y2 = det.bbox
            cx1, cy1 = canvas.image_to_canvas_coords(x1, y1)
            cx2, cy2 = canvas.image_to_canvas_coords(x2, y2)
            is_selected_vehicle = selected_vehicle_idx == vehicle_idx
            vehicle_outline = active_color if is_selected_vehicle else vehicle_color
            vehicle_width = 3 if is_selected_vehicle else 2
            vehicle_dash = None if is_selected_vehicle else (6, 4)
            canvas.create_rectangle(
                cx1,
                cy1,
                cx2,
                cy2,
                outline=vehicle_outline,
                width=vehicle_width,
                dash=vehicle_dash,
                tags=("preview_overlay",)
            )
            if not drag_active:
                canvas.create_text(
                    cx1 + 6,
                    max(10, cy1 - 8),
                    text=f"Vehicle {vehicle_idx + 1}/{len(vehicle_detections)}",
                    fill=vehicle_outline,
                    anchor="sw",
                    font=("Segoe UI", 9, "bold"),
                    tags=("preview_overlay",)
                )

        for plate_idx, det in enumerate(plate_detections):
            polygon = self._detection_polygon(det)
            points = []
            for px, py in polygon:
                cx, cy = canvas.image_to_canvas_coords(px, py)
                points.extend([cx, cy])

            is_selected = selected_plate_idx == plate_idx
            is_delete_candidate = delete_candidate_idx == plate_idx
            if is_delete_candidate:
                canvas.create_polygon(
                    points,
                    outline="",
                    fill=delete_color,
                    stipple="gray25",
                    width=0,
                    tags=("preview_overlay",)
                )
            outline = delete_color if is_delete_candidate else (active_color if is_selected else plate_color)
            width = 2 if (is_selected or is_delete_candidate) else 1
            dash = None if (is_selected or is_delete_candidate) else (5, 3)
            canvas.create_polygon(
                points,
                outline=outline,
                fill="",
                width=width,
                dash=dash,
                tags=("preview_overlay",)
            )

            if not drag_active:
                min_x = min(points[0::2]) if points else 0
                min_y = min(points[1::2]) if points else 0
                canvas.create_rectangle(
                    min_x,
                    max(0, min_y - 22),
                    min_x + 104,
                    max(18, min_y - 2),
                    outline="",
                    fill=label_bg,
                    tags=("preview_overlay",)
                )
                canvas.create_text(
                    min_x + 6,
                    max(10, min_y - 7),
                    text=f"Plate {det.confidence:.2f}",
                    fill=label_fill,
                    anchor="sw",
                    font=("Segoe UI", 9, "bold"),
                    tags=("preview_overlay",)
                )

            if is_selected and not is_delete_candidate:
                zoom_level = max(0.01, float(getattr(canvas, "zoom_level", 1.0) or 1.0))
                radius = 5.0 if zoom_level <= 2.0 else min(8.0, 5.0 + ((zoom_level - 2.0) * 1.0))
                for vertex_idx, (px, py) in enumerate(polygon):
                    cx, cy = canvas.image_to_canvas_coords(px, py)
                    canvas.create_oval(
                        cx - radius,
                        cy - radius,
                        cx + radius,
                        cy + radius,
                        outline=handle_outline,
                        fill=handle_fill,
                        width=1,
                        tags=("preview_overlay",)
                    )
                    canvas.create_text(
                        cx,
                        cy - 12,
                        text=str(vertex_idx + 1),
                        fill=active_color,
                        font=("Segoe UI", 8, "bold"),
                        tags=("preview_overlay",)
                    )

        if self._preview_draw_mode and self._preview_draw_points:
            draw_points = []
            for idx, (px, py) in enumerate(self._preview_draw_points):
                cx, cy = canvas.image_to_canvas_coords(px, py)
                draw_points.extend([cx, cy])
                canvas.create_oval(
                    cx - 5,
                    cy - 5,
                    cx + 5,
                    cy + 5,
                    outline="#111111",
                    fill=active_color,
                    width=1,
                    tags=("preview_overlay",)
                )
                canvas.create_text(
                    cx + 10,
                    cy - 10,
                    text=str(idx + 1),
                    fill=active_color,
                    font=("Segoe UI", 8, "bold"),
                    anchor="sw",
                    tags=("preview_overlay",)
                )

            if len(draw_points) >= 4:
                canvas.create_polygon(
                    draw_points,
                    outline=active_color,
                    fill="",
                    width=1,
                    dash=(4, 2),
                    tags=("preview_overlay",)
                )
            elif len(draw_points) >= 2:
                canvas.create_line(
                    draw_points,
                    fill=active_color,
                    width=1,
                    dash=(4, 2),
                    tags=("preview_overlay",)
                )

        if not drag_active:
            self._draw_preview_overlay_context(canvas)
            self._draw_preview_bottom_hint(canvas)

    def _draw_preview_enter_fullscreen_hint(self, canvas: ZoomableCanvas):
        try:
            canvas_width = int(canvas.winfo_width() or 0)
        except Exception:
            canvas_width = 0
        if canvas_width <= 80:
            return

        if self._manual_xml_template_enabled():
            hint_text = "Do recznej edycji wlacz pelny ekran klawiszem Enter."
            accent = "#f39c12"
        else:
            hint_text = "Pełny ekran podglądu włączysz klawiszem Enter."
            accent = "#3498db"

        text_width = max(240, min(canvas_width - 72, 640))
        center_x = max(40, canvas_width // 2)
        text_id = canvas.create_text(
            center_x,
            18,
            text=hint_text,
            fill="#f3f3f3",
            anchor="n",
            justify=tk.CENTER,
            width=text_width,
            font=("Segoe UI", 10, "bold"),
            tags=("preview_overlay",)
        )
        try:
            bbox = canvas.bbox(text_id)
        except Exception:
            bbox = None
        if not bbox:
            return

        x1, y1, x2, y2 = bbox
        box_id = canvas.create_rectangle(
            x1 - 14,
            y1 - 8,
            x2 + 14,
            y2 + 8,
            fill="#111111",
            outline=accent,
            width=1,
            tags=("preview_overlay",)
        )
        canvas.tag_lower(box_id, text_id)

    def _get_preview_bottom_hint_text(self) -> str:
        ann = self._get_preview_annotation()
        if ann is None:
            return ""

        plates = self._get_plate_detections(ann)
        vehicles = self._get_vehicle_detections(ann)
        selected_vehicle_idx = self._get_selected_vehicle_index_for_ann(ann)
        vehicle_suffix = ""
        if vehicles:
            vehicle_no = 1 if selected_vehicle_idx is None else (int(selected_vehicle_idx) + 1)
            vehicle_suffix = f" Pojazd {vehicle_no}/{len(vehicles)}."

        if self._preview_draw_mode:
            clicked_points = len(self._preview_draw_points)
            next_idx = clicked_points + 1
            next_corner = self._preview_draw_corner_label(next_idx)
            base = (
                f"Rysowanie tablicy: kliknij w {next_corner} ({next_idx}/4). "
                "D anuluje."
            )
        elif self._preview_delete_mode:
            if self._preview_delete_candidate_idx is not None:
                base = "Usuwanie: PPM usuwa zaznaczony polygon, S anuluje tryb."
            else:
                base = "Usuwanie: kliknij polygon tablicy, potem PPM usuwa. S anuluje tryb."
        elif not plates:
            base = "Brak tablicy. D dodaje nowy polygon tablicy."
        else:
            selected_idx = self._get_selected_plate_index_for_ann(ann)
            plate_no = 0 if selected_idx is None else (int(selected_idx) + 1)
            drag_hint = (
                "Przeciagnij rog aktywnej tablicy."
                if self._preview_corner_drag_modifier_down
                else "Przytrzymaj W i przeciagnij rog."
            )
            base = (
                f"Tablica {plate_no}/{len(plates)}. {drag_hint} "
                "A zmienia tablice, Spacja pojazdy, R kadr, F dopasuj, D nowa, S usuń, Del kasuje obraz, Ctrl+Z/Ctrl+Y cofają i ponawiają, Ctrl+S zapisuje."
            )

        return f"{base}{vehicle_suffix}"

    def _draw_preview_bottom_hint(self, canvas: ZoomableCanvas):
        hint_text = str(self._get_preview_bottom_hint_text() or "").strip()
        if not hint_text:
            return

        try:
            canvas_width = int(canvas.winfo_width() or 0)
            canvas_height = int(canvas.winfo_height() or 0)
        except Exception:
            canvas_width = 0
            canvas_height = 0
        if canvas_width <= 120 or canvas_height <= 80:
            return

        accent = "#6f6330" if self._manual_xml_template_enabled() else "#3d5d73"
        text_width = max(280, min(canvas_width - 56, 980))
        center_x = max(40, canvas_width // 2)
        text_id = canvas.create_text(
            center_x,
            canvas_height - 14,
            text=hint_text,
            fill="#d7dde4",
            anchor="s",
            justify=tk.CENTER,
            width=text_width,
            font=("Segoe UI", 8, "normal"),
            tags=("preview_overlay",)
        )
        try:
            bbox = canvas.bbox(text_id)
        except Exception:
            bbox = None
        if not bbox:
            return

        x1, y1, x2, y2 = bbox
        pad_x = 12
        pad_y = 8
        box_id = canvas.create_rectangle(
            max(8, x1 - pad_x),
            max(8, y1 - pad_y),
            min(canvas_width - 8, x2 + pad_x),
            min(canvas_height - 8, y2 + pad_y),
            fill="#101419",
            outline=accent,
            width=1,
            tags=("preview_overlay",)
        )
        canvas.tag_lower(box_id, text_id)

    def _clamp_preview_point(self, x: float, y: float) -> tuple[float, float]:
        if self.preview_canvas.original_image is None:
            return float(x), float(y)
        width = max(1.0, float(self.preview_canvas.original_image.width) - 1.0)
        height = max(1.0, float(self.preview_canvas.original_image.height) - 1.0)
        return (
            min(max(0.0, float(x)), width),
            min(max(0.0, float(y)), height),
        )

    def _find_preview_vertex_hit(self, canvas_x: float, canvas_y: float):
        ann = self._get_preview_annotation()
        if ann is None:
            return None

        plate_detections = self._get_plate_detections(ann)
        if not plate_detections:
            return None

        selected_idx = self._get_selected_plate_index_for_ann(ann)
        ordered_indices = list(range(len(plate_detections)))
        if selected_idx is not None and selected_idx in ordered_indices:
            ordered_indices.remove(selected_idx)
            ordered_indices.insert(0, selected_idx)

        handle_radius = self._get_preview_vertex_hit_radius()
        best_hit = None
        best_dist = None
        for plate_idx in ordered_indices:
            polygon = self._detection_polygon(plate_detections[plate_idx])
            for vertex_idx, (px, py) in enumerate(polygon):
                point_x, point_y = self.preview_canvas.image_to_canvas_coords(px, py)
                dist = math.hypot(float(canvas_x) - point_x, float(canvas_y) - point_y)
                if dist <= handle_radius and (best_dist is None or dist < best_dist):
                    best_hit = (plate_idx, vertex_idx)
                    best_dist = dist
        return best_hit

    def _get_nearest_preview_vertex(self, plate_idx: int, canvas_x: float, canvas_y: float):
        ann = self._get_preview_annotation()
        if ann is None:
            return None

        plate_detections = self._get_plate_detections(ann)
        if plate_idx < 0 or plate_idx >= len(plate_detections):
            return None

        polygon = self._detection_polygon(plate_detections[plate_idx])
        best_vertex_idx = None
        best_dist = None
        for vertex_idx, (px, py) in enumerate(polygon):
            point_x, point_y = self.preview_canvas.image_to_canvas_coords(px, py)
            dist = math.hypot(float(canvas_x) - point_x, float(canvas_y) - point_y)
            if best_dist is None or dist < best_dist:
                best_vertex_idx = vertex_idx
                best_dist = dist

        if best_vertex_idx is None:
            return None
        return plate_idx, int(best_vertex_idx), float(best_dist if best_dist is not None else 0.0)

    def _find_preview_polygon_hit(self, canvas_x: float, canvas_y: float):
        ann = self._get_preview_annotation()
        if ann is None or self.preview_canvas.original_image is None:
            return None

        img_x, img_y = self.preview_canvas.canvas_to_image_coords(canvas_x, canvas_y, clamp=False)
        plate_detections = self._get_plate_detections(ann)
        if not plate_detections:
            return None

        threshold_img = max(2.0, 8.0 / max(0.01, float(self.preview_canvas.zoom_level)))
        best_idx = None
        best_dist = None

        for plate_idx, det in enumerate(plate_detections):
            polygon = np.array(self._detection_polygon(det), dtype=np.float32)
            try:
                dist = cv2.pointPolygonTest(polygon, (float(img_x), float(img_y)), True)
            except Exception:
                continue
            if dist >= -threshold_img and (best_dist is None or dist > best_dist):
                best_idx = plate_idx
                best_dist = dist

        return best_idx

    def _find_preview_vehicle_hit(self, canvas_x: float, canvas_y: float):
        ann = self._get_preview_annotation()
        if ann is None or self.preview_canvas.original_image is None:
            return None

        img_x, img_y = self.preview_canvas.canvas_to_image_coords(canvas_x, canvas_y, clamp=False)
        vehicle_detections = self._get_vehicle_detections(ann)
        if not vehicle_detections:
            return None

        zoom_level = max(0.01, float(getattr(self.preview_canvas, "zoom_level", 1.0) or 1.0))
        threshold_img = max(3.0, 8.0 / zoom_level)
        best_idx = None
        best_area = None

        for vehicle_idx, det in enumerate(vehicle_detections):
            x1, y1, x2, y2 = [float(v) for v in det.bbox[:4]]
            if (
                (x1 - threshold_img) <= float(img_x) <= (x2 + threshold_img)
                and (y1 - threshold_img) <= float(img_y) <= (y2 + threshold_img)
            ):
                area = max(1.0, (x2 - x1) * (y2 - y1))
                if best_area is None or area < best_area:
                    best_idx = vehicle_idx
                    best_area = area

        return best_idx

    def _get_global_nearest_preview_vertex(self, canvas_x: float, canvas_y: float):
        ann = self._get_preview_annotation()
        if ann is None:
            return None

        plate_detections = self._get_plate_detections(ann)
        best_candidate = None
        best_dist = None
        for plate_idx in range(len(plate_detections)):
            candidate = self._get_nearest_preview_vertex(plate_idx, canvas_x, canvas_y)
            if candidate is None:
                continue

            _plate_idx, _vertex_idx, dist = candidate
            if best_dist is None or dist < best_dist:
                best_candidate = candidate
                best_dist = dist

        return best_candidate

    def _get_preview_vertex_canvas_position(self, plate_idx: int, vertex_idx: int):
        ann = self._get_preview_annotation()
        if ann is None:
            return None

        plate_detections = self._get_plate_detections(ann)
        if plate_idx < 0 or plate_idx >= len(plate_detections):
            return None

        polygon = self._detection_polygon(plate_detections[plate_idx])
        if vertex_idx < 0 or vertex_idx >= len(polygon):
            return None

        px, py = polygon[vertex_idx]
        return self.preview_canvas.image_to_canvas_coords(px, py)

    def _describe_preview_hit_debug(self, canvas_x: float, canvas_y: float, event=None) -> str:
        if self.preview_canvas.original_image is None:
            return ""

        img_x, img_y = self.preview_canvas.canvas_to_image_coords(canvas_x, canvas_y, clamp=False)
        handle_radius = self._get_preview_vertex_hit_radius()

        parts = [
            f"img=({float(img_x):.1f},{float(img_y):.1f})",
            f"hit<={handle_radius:.1f}",
        ]
        if event is not None:
            norm_source = str(getattr(event, "norm_source", "raw") or "raw")
            raw_x = getattr(event, "raw_x", None)
            raw_y = getattr(event, "raw_y", None)
            pointer_local_x = getattr(event, "pointer_local_x", None)
            pointer_local_y = getattr(event, "pointer_local_y", None)
            event_local_x = getattr(event, "event_local_x", None)
            event_local_y = getattr(event, "event_local_y", None)
            canvas_event_x = getattr(event, "canvas_x", None)
            canvas_event_y = getattr(event, "canvas_y", None)
            canvas_offset_x = getattr(event, "canvas_offset_x", None)
            canvas_offset_y = getattr(event, "canvas_offset_y", None)
            parts.append(f"src={norm_source}")
            if raw_x is not None and raw_y is not None:
                parts.append(f"raw=({float(raw_x):.1f},{float(raw_y):.1f})")
            if event_local_x is not None and event_local_y is not None:
                parts.append(f"event_local=({float(event_local_x):.1f},{float(event_local_y):.1f})")
            if pointer_local_x is not None and pointer_local_y is not None:
                parts.append(f"pointer_local=({float(pointer_local_x):.1f},{float(pointer_local_y):.1f})")
            if canvas_event_x is not None and canvas_event_y is not None:
                parts.append(f"canvas_event=({float(canvas_event_x):.1f},{float(canvas_event_y):.1f})")
            if canvas_offset_x is not None and canvas_offset_y is not None:
                parts.append(f"canvas_offset=({float(canvas_offset_x):.1f},{float(canvas_offset_y):.1f})")

        ann = self._get_preview_annotation()
        selected_idx = self._get_selected_plate_index_for_ann(ann) if ann is not None else None
        selected_candidate = None
        if selected_idx is not None:
            selected_candidate = self._get_nearest_preview_vertex(int(selected_idx), canvas_x, canvas_y)
            if selected_candidate is not None:
                plate_idx, vertex_idx, dist = selected_candidate
                point = self._get_preview_vertex_canvas_position(int(plate_idx), int(vertex_idx))
                if point is not None:
                    point_x, point_y = point
                    parts.append(
                        f"sel={self._format_preview_debug_vertex_ref(plate_idx, vertex_idx)} "
                        f"dist={float(dist):.1f} pt=({float(point_x):.1f},{float(point_y):.1f})"
                    )

        global_candidate = self._get_global_nearest_preview_vertex(canvas_x, canvas_y)
        if global_candidate is not None:
            plate_idx, vertex_idx, dist = global_candidate
            is_same_as_selected = (
                selected_candidate is not None
                and int(selected_candidate[0]) == int(plate_idx)
                and int(selected_candidate[1]) == int(vertex_idx)
            )
            if not is_same_as_selected:
                point = self._get_preview_vertex_canvas_position(int(plate_idx), int(vertex_idx))
                if point is not None:
                    point_x, point_y = point
                    parts.append(
                        f"global={self._format_preview_debug_vertex_ref(plate_idx, vertex_idx)} "
                        f"dist={float(dist):.1f} pt=({float(point_x):.1f},{float(point_y):.1f})"
                    )

        return " ".join(parts)

    def _describe_selected_polygon_vertices_debug(self) -> str:
        ann = self._get_preview_annotation()
        if ann is None:
            return "verts=-"

        selected_idx = self._get_selected_plate_index_for_ann(ann)
        if selected_idx is None:
            return "verts=-"

        plate_detections = self._get_plate_detections(ann)
        if selected_idx < 0 or selected_idx >= len(plate_detections):
            return "verts=-"

        polygon = self._detection_polygon(plate_detections[selected_idx])
        parts = []
        for vertex_idx, (img_x, img_y) in enumerate(polygon):
            canvas_point = self._get_preview_vertex_canvas_position(int(selected_idx), int(vertex_idx))
            if canvas_point is None:
                continue
            canvas_x, canvas_y = canvas_point
            parts.append(
                f"v{int(vertex_idx) + 1}=img({float(img_x):.1f},{float(img_y):.1f})/canvas({float(canvas_x):.1f},{float(canvas_y):.1f})"
            )

        if not parts:
            return "verts=-"
        return f"verts[p{int(selected_idx) + 1}]: " + " ".join(parts)

    def _get_preview_vertex_hit_radius(self) -> float:
        zoom_level = max(0.01, float(getattr(self.preview_canvas, "zoom_level", 1.0) or 1.0))
        if self._preview_modifier_active():
            # Przy duzym zoomie klik jest "blisko" rogu w obrazie, ale daleko w pikselach canvasa.
            # Skalujemy hitbox z zoomem, zamiast trzymac sztywny promien ekranowy.
            return max(12.0, min(30.0, 6.0 * zoom_level))
        return 8.0

    def _resolve_preview_drag_target(self, canvas_x: float, canvas_y: float):
        vertex_hit = self._find_preview_vertex_hit(canvas_x, canvas_y)
        if vertex_hit is not None:
            plate_idx, vertex_idx = vertex_hit
            return int(plate_idx), int(vertex_idx), "handle"
        return None

    def _finish_preview_vertex_drag(self, mark_dirty: bool = True):
        drag_state = self._preview_drag_state
        ann = self._get_preview_annotation()
        if not isinstance(drag_state, dict) or ann is None:
            try:
                self.preview_canvas.grab_release()
            except Exception:
                pass
            self._cancel_preview_drag_refresh()
            self._preview_drag_state = None
            self._preview_pending_vertex_hit = None
            self._refresh_preview_canvas()
            self._update_preview_edit_status()
            return False

        plate_detections = self._get_plate_detections(ann)
        plate_idx = int(drag_state.get("plate_idx", -1))
        if 0 <= plate_idx < len(plate_detections):
            det = plate_detections[plate_idx]
            fixed_polygon = PolygonValidator.fix_polygon(self._detection_polygon(det))
            det.polygon = fixed_polygon
            det.bbox = self._bbox_from_polygon(fixed_polygon)
            det.keypoints = self._keypoints_from_polygon(fixed_polygon)
            det.attributes["manually_edited"] = "true"
            det.attributes["manual_source"] = "preview"
            if mark_dirty:
                # Podczas seryjnej korekty rogĂłw nie odswiezamy od razu calej listy
                # wynikow, bo to bylo odczuwalne wlasnie przed drugim chwytem.
                self._mark_preview_image_dirty(
                    ann,
                    refresh_list=not self._preview_modifier_active(),
                )

        try:
            self.preview_canvas.grab_release()
        except Exception:
            pass
        self._cancel_preview_drag_refresh()
        self._preview_drag_state = None
        self._preview_pending_vertex_hit = None
        self._refresh_preview_canvas()
        self._update_preview_edit_status()
        if mark_dirty:
            # Przytrzymane W oznacza sesje szybkiej korekty wielu rogĂłw.
            # Nie zapisujemy wtedy po kazdym puszczeniu myszy, bo to wcinalo
            # sie w chwyt kolejnego punktu. Zapis wraca po puszczeniu W.
            if not self._preview_modifier_active():
                self._schedule_preview_autosave(delay_ms=260)
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass
        return True

    def _persist_preview_structural_change(self, success_message: str, fallback_message: str | None = None):
        if self._save_preview_edits():
            self._update_preview_edit_status(success_message)
            return True

        self._update_preview_edit_status(
            fallback_message
            or "Zmiana została wprowadzona w podglądzie, ale nie udało się od razu zapisać annotations.xml. Użyj Ctrl+S."
        )
        return False

    def _delete_preview_polygon(self, plate_idx: int, autosave: bool = True):
        ann = self._get_preview_annotation()
        if ann is None:
            return False

        plate_detections = self._get_plate_detections(ann)
        if plate_idx < 0 or plate_idx >= len(plate_detections):
            return False

        self._push_preview_history_snapshot(ann)
        target_detection = plate_detections[int(plate_idx)]
        try:
            ann.detections.remove(target_detection)
        except ValueError:
            return False

        remaining_plates = self._get_plate_detections(ann)
        if remaining_plates:
            self._set_selected_plate_index_for_ann(ann, min(int(plate_idx), len(remaining_plates) - 1))
            ann.status = AnnotationStatus.SUCCESS
        else:
            self._set_selected_plate_index_for_ann(ann, None)
            ann.status = AnnotationStatus.NO_PLATE

        ann.status_message = "Polygon tablicy usuniety recznie."
        self._preview_drag_state = None
        self._preview_pending_vertex_hit = None
        self._preview_delete_mode = False
        self._preview_delete_candidate_idx = None
        self._mark_preview_image_dirty(ann, refresh_list=True)
        self._refresh_preview_canvas()
        self._push_preview_debug_event("delete", f"p{int(plate_idx) + 1}")

        if autosave:
            return self._persist_preview_structural_change(
                "Usunieto polygon tablicy i zapisano zmiane do annotations.xml.",
                "Usunieto polygon tablicy, ale nie udalo sie od razu zapisac annotations.xml. Uzyj Ctrl+S."
            )

        self._update_preview_edit_status("Usunieto polygon tablicy. Uzyj Ctrl+S, aby zapisac zmiane do annotations.xml.")
        return True

    def _commit_new_preview_polygon(self):
        ann = self._get_preview_annotation()
        if ann is None or len(self._preview_draw_points) != 4:
            return

        points = [self._clamp_preview_point(x, y) for x, y in self._preview_draw_points[:4]]
        fixed_points = PolygonValidator.fix_polygon(points)
        if not PolygonValidator.is_valid_quad(fixed_points):
            self._preview_draw_points = []
            self._update_preview_edit_status("Nowy polygon jest zbyt maly albo nieprawidlowy. Sprobuj ponownie.")
            self._refresh_preview_canvas()
            return

        self._push_preview_history_snapshot(ann)
        new_det = Detection(
            label="plate",
            confidence=1.0,
            bbox=self._bbox_from_polygon(fixed_points),
            keypoints=self._keypoints_from_polygon(fixed_points),
            polygon=fixed_points,
        )
        new_det.attributes["manually_edited"] = "true"
        new_det.attributes["manual_source"] = "preview"
        ann.detections.append(new_det)
        ann.status = AnnotationStatus.SUCCESS
        ann.status_message = "Dodano recznie polygon tablicy."

        plates = self._get_plate_detections(ann)
        self._set_selected_plate_index_for_ann(ann, len(plates) - 1)
        self._mark_preview_image_dirty(ann, refresh_list=True)
        self._preview_draw_mode = False
        self._preview_draw_points = []
        self._refresh_preview_canvas()
        self._push_preview_debug_event("add", f"p{len(plates)}")
        self._persist_preview_structural_change(
            "Dodano nowy polygon tablicy i zapisano go do annotations.xml.",
            "Dodano nowy polygon tablicy, ale nie udalo sie od razu zapisac annotations.xml. Uzyj Ctrl+S."
        )

    def _get_current_annotation_xml_path(self) -> Path | None:
        candidates = []

        if getattr(self, "current_annotation_xml_path", None):
            try:
                current_xml_path = Path(self.current_annotation_xml_path)
                safe_run_dir = self._resolve_safe_annotation_run_dir(current_xml_path.parent)
                if safe_run_dir is not None and current_xml_path.name.lower() == "annotations.xml":
                    candidates.append(safe_run_dir / "annotations.xml")
            except Exception:
                pass

        for run_candidate in (
            getattr(self, "current_annotation_run_dir", None),
            getattr(self, "last_staging_run_dir", None),
            str(self.plate_dataset_run_var.get() or "").strip(),
        ):
            safe_run_dir = self._resolve_safe_annotation_run_dir(run_candidate)
            if safe_run_dir is not None:
                candidates.append(safe_run_dir / "annotations.xml")

        seen = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                if candidate.exists() or candidate.parent.exists():
                    return candidate
            except Exception:
                continue

        return candidates[0] if candidates else None

    def _save_preview_edits(self):
        if self._preview_draw_mode and self._preview_draw_points:
            messagebox.showwarning(
                "Rysowanie w toku",
                "Dokoncz albo anuluj rysowanie 4-punktowego polygonu przed zapisem."
            )
            return False

        if not self._preview_dirty_images:
            self._update_preview_edit_status("Brak niezapisanych poprawek w podglądzie.")
            return True

        xml_path = self._get_current_annotation_xml_path()
        if xml_path is None:
            messagebox.showerror("Brak XML", "Nie znaleziono docelowego pliku annotations.xml do zapisania poprawek.")
            return False

        try:
            xml_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        success = CVATExporter().export(
            self.current_annotations,
            xml_path,
            include_confidence=True,
            only_successful=False,
        )
        if not success:
            messagebox.showerror("Blad zapisu", f"Nie udalo sie zapisac poprawek do:\n{xml_path}")
            return False

        self.current_annotation_xml_path = xml_path
        self.current_annotation_run_dir = xml_path.parent
        self.last_staging_run_dir = xml_path.parent
        try:
            self._update_annotation_run_manifest(
                xml_path.parent,
                has_manual_edits=True,
                last_manual_edit_at=datetime.datetime.now().isoformat(timespec="seconds"),
                last_manual_edit_kind="preview_save",
                **self._collect_preview_resume_manifest_fields(),
            )
        except Exception:
            pass
        try:
            self._remember_campaign_manual_plate_source(
                run_dir=xml_path.parent,
                xml_path=xml_path,
                input_dir=self.current_input_dir,
            )
        except Exception:
            pass
        self._preview_dirty_images.clear()
        self._refresh_preview_list(preserve_selection=True, render_current=False)
        self._refresh_plate_dataset_export_sources()
        self._refresh_step2_action_states()
        self._push_preview_debug_event("save", f"xml={xml_path.name}")
        self._update_preview_edit_status("Zapisano poprawki polygonow do annotations.xml. Kolejny etap zobaczy juz nowe rogi.")
        self._queue_free_mode_session_save()
        return True

    def _ensure_preview_edits_saved(self, action_label: str) -> bool:
        if not self._preview_dirty_images:
            return True

        if self._save_preview_edits():
            return True

        messagebox.showerror(
            "Blad zapisu poprawek",
            f"Nie udalo sie zapisac zmian przed operacja: {action_label}."
        )
        return False

    def _cancel_preview_autosave(self):
        pending = getattr(self, "_preview_autosave_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._preview_autosave_after_id = None

    def _schedule_preview_autosave(self, delay_ms: int = 120):
        self._cancel_preview_autosave()
        try:
            self._preview_autosave_after_id = self.frame.after(
                int(delay_ms),
                lambda: self._save_preview_edits(
                    interactive=False,
                    status_message="Zapisano korekte polygonu do annotations.xml.",
                ),
            )
        except Exception:
            self._preview_autosave_after_id = None

    def _remove_image_from_stage_manifest(self, image_path: Path):
        if image_path is None or not self._is_manual_plate_stage_input(image_path.parent):
            return

        manifest_path = self._get_manual_plate_stage_dir() / "stage_manifest.json"
        manifest = self.dataset_creator._load_stage_manifest(manifest_path)
        entries = manifest.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}

        stage_key = self.dataset_creator._path_key(image_path)
        filtered_entries = {}
        for entry_key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            stage_name = str(entry.get("stage_name") or "").strip()
            if entry_key == stage_key or stage_name == image_path.name:
                continue
            filtered_entries[entry_key] = entry

        stage_images = get_image_files(self._get_manual_plate_stage_images_dir())
        manifest["entries"] = filtered_entries
        manifest["pending_images"] = len(stage_images)
        manifest["stage_images_total"] = len(stage_images)
        manifest["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            self.dataset_creator._save_stage_manifest(manifest_path, manifest)
        except Exception as e:
            logger.debug(f"Nie udalo sie odswiezyc manifestu stage po usunieciu obrazu: {e}")

    def _save_preview_edits(self, *, interactive: bool = True, status_message: str | None = None):
        self._cancel_preview_autosave()

        if self._preview_draw_mode and self._preview_draw_points:
            if interactive:
                messagebox.showwarning(
                    "Rysowanie w toku",
                    "Dokoncz albo anuluj rysowanie 4-punktowego polygonu przed zapisem."
                )
            return False

        if not self._preview_dirty_images:
            if interactive:
                self._update_preview_edit_status("Brak niezapisanych poprawek w podglądzie.")
            return True

        xml_path = self._get_current_annotation_xml_path()
        if xml_path is None:
            if interactive:
                messagebox.showerror("Brak XML", "Nie znaleziono docelowego pliku annotations.xml do zapisania poprawek.")
            return False

        try:
            xml_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        success = CVATExporter().export(
            self.current_annotations,
            xml_path,
            include_confidence=True,
            only_successful=False,
        )
        if not success:
            if interactive:
                messagebox.showerror("Blad zapisu", f"Nie udalo sie zapisac poprawek do:\n{xml_path}")
            return False

        self.current_annotation_xml_path = xml_path
        self.current_annotation_run_dir = xml_path.parent
        self.last_staging_run_dir = xml_path.parent
        try:
            self._update_annotation_run_manifest(
                xml_path.parent,
                has_manual_edits=True,
                last_manual_edit_at=datetime.datetime.now().isoformat(timespec="seconds"),
                last_manual_edit_kind="preview_save",
                **self._collect_preview_resume_manifest_fields(),
            )
        except Exception:
            pass
        try:
            self._remember_campaign_manual_plate_source(
                run_dir=xml_path.parent,
                xml_path=xml_path,
                input_dir=self.current_input_dir,
            )
        except Exception:
            pass
        self._remember_manual_review_run(xml_path.parent, source="manual")

        self._preview_dirty_images.clear()
        self._refresh_preview_list(preserve_selection=True, render_current=False)
        self._refresh_plate_dataset_export_sources()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        self._push_preview_debug_event("save", f"xml={xml_path.name}")
        self._update_preview_edit_status(
            status_message or "Zapisano poprawki polygonow do annotations.xml. Kolejny etap zobaczy juz nowe rogi."
        )
        self._queue_free_mode_session_save()
        return True

    def _delete_current_preview_image_hard(self, event=None):
        if event is not None and not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        if not self._preview_is_editable():
            self._update_preview_edit_status(
                "Usuwanie obrazu bedzie dostepne dopiero po przygotowaniu annotations.xml."
            )
            return "break" if event is not None else False

        ann = self._get_preview_annotation()
        if ann is None or self.current_input_dir is None:
            return "break" if event is not None else False

        image_path = Path(self.current_input_dir) / str(getattr(ann, "filename", "") or "")
        delete_index = int(self.current_preview_index or 0)
        backup_annotations = list(self.current_annotations)
        backup_dirty = set(self._preview_dirty_images)
        backup_selected_plate = dict(self._preview_selected_plate_by_image)
        backup_selected_vehicle = dict(self._preview_selected_vehicle_by_image)

        self.current_annotations = [item for idx, item in enumerate(self.current_annotations) if idx != delete_index]
        self._preview_dirty_images.discard(str(getattr(ann, "filename", "") or ""))
        self._preview_selected_plate_by_image.pop(str(getattr(ann, "filename", "") or ""), None)
        self._preview_selected_vehicle_by_image.pop(str(getattr(ann, "filename", "") or ""), None)

        if not self._save_preview_edits(interactive=False, status_message="Usunieto obraz z annotations.xml."):
            self.current_annotations = backup_annotations
            self._preview_dirty_images = backup_dirty
            self._preview_selected_plate_by_image = backup_selected_plate
            self._preview_selected_vehicle_by_image = backup_selected_vehicle
            self._refresh_preview_list(preserve_selection=True, render_current=True)
            messagebox.showerror("Blad usuwania", "Nie udalo sie usunac wpisu obrazu z annotations.xml.")
            return "break" if event is not None else False

        try:
            if image_path.exists():
                image_path.unlink()
        except Exception as e:
            self.current_annotations = backup_annotations
            self._preview_dirty_images = backup_dirty
            self._preview_selected_plate_by_image = backup_selected_plate
            self._preview_selected_vehicle_by_image = backup_selected_vehicle
            self._preview_dirty_images.add(str(getattr(ann, "filename", "") or ""))
            self._save_preview_edits(interactive=False)
            self._refresh_preview_list(preserve_selection=True, render_current=True)
            messagebox.showerror("Blad usuwania", f"Nie udalo sie usunac pliku z dysku:\n{image_path}\n\n{e}")
            return "break" if event is not None else False

        self._remove_image_from_stage_manifest(image_path)
        self._refresh_manual_plate_stage_ui()

        if self.current_annotations:
            new_index = min(delete_index, len(self.current_annotations) - 1)
            self.current_preview_index = new_index
            self._refresh_preview_list(preserve_selection=True, render_current=True)
            self._select_preview_index(new_index)
        else:
            self._clear_preview_editor_state(clear_dirty=True)
            self.preview_listbox.delete(0, tk.END)
            self._update_preview_edit_status("Usunieto ostatnie zdjecie z aktywnego runu.")

        self._refresh_plate_dataset_export_sources()
        self._refresh_step2_action_states()
        self._refresh_free_mode_workflow_ui()
        self._update_preview_edit_status("Usunieto zdjecie z dysku i z annotations.xml.")
        return "break" if event is not None else True

    def _move_current_preview_image_to_stage(self):
        ann = self._get_preview_annotation()
        if ann is None or self.current_input_dir is None:
            return False

        image_path = Path(self.current_input_dir) / str(getattr(ann, "filename", "") or "")
        if not image_path.exists():
            messagebox.showerror("Brak obrazu", f"Plik nie istnieje:\n{image_path}")
            return False

        if self._is_manual_plate_stage_input(image_path.parent):
            messagebox.showinfo("Stage", "To zdjecie jest juz w stage.")
            return False

        stage_dir = self._get_manual_plate_stage_dir()
        temp_dir = stage_dir / "_incoming_preview" / datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_copy = temp_dir / image_path.name

        try:
            shutil.copy2(image_path, temp_copy)
            ok, msg, _stats = self.dataset_creator.add_images_to_stage(temp_dir, stage_dir)
        except Exception as e:
            ok = False
            msg = str(e)
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

        if not ok:
            messagebox.showerror("Blad stage", f"Nie udalo sie przeniesc obrazu do stage:\n{msg}")
            return False

        delete_ok = self._delete_current_preview_image_hard()
        if not delete_ok:
            messagebox.showwarning(
                "Czesciowe przeniesienie",
                "Obraz zostal skopiowany do stage, ale nie udalo sie usunac go z biezacego runu."
            )
            return False

        self._refresh_manual_plate_stage_ui()
        self._update_preview_edit_status("Przeniesiono obraz do stage i usunieto go z aktywnego runu.")
        return True

    def _on_preview_canvas_right_click(self, event):
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return None

        try:
            canvas.focus_set()
        except Exception:
            pass

        ann = self._get_preview_annotation()
        if ann is None or canvas.original_image is None:
            return "break"

        canvas_x = float(canvas.canvasx(getattr(event, "x", 0.0)))
        canvas_y = float(canvas.canvasy(getattr(event, "y", 0.0)))

        if self._preview_draw_mode:
            self._preview_draw_mode = False
            self._preview_draw_points = []
            self._refresh_preview_canvas()
            self._push_preview_debug_event("draw-cancel", "PPM anulowal nowy polygon")
            self._update_preview_edit_status("Anulowano rysowanie nowego polygonu.")
            return "break"

        if not self._preview_delete_mode:
            self._update_preview_edit_status(
                "Usuwanie polygonu jest dwuetapowe: naciśnij S, kliknij wewnątrz polygonu, a potem PPM usunie zaznaczoną tablicę."
            )
            return "break"

        target_idx = self._preview_delete_candidate_idx
        if target_idx is None:
            self._update_preview_edit_status(
                "Tryb usuwania jest aktywny. Kliknij najpierw wewnątrz polygonu, aby zaznaczyć go na czerwono."
            )
            return "break"

        self._set_selected_plate_index_for_ann(ann, int(target_idx))
        self._refresh_preview_canvas()
        self._push_preview_debug_event("delete-request", f"p{int(target_idx) + 1} PPM")
        self._delete_preview_polygon(int(target_idx), autosave=True)
        return "break"

    def on_zoomable_canvas_press(self, canvas: ZoomableCanvas, event):
        if canvas is not self.preview_canvas:
            return False

        ann = self._get_preview_annotation()
        if ann is None or canvas.original_image is None:
            return False

        canvas_x = float(getattr(event, "canvas_x", getattr(event, "x", 0.0)))
        canvas_y = float(getattr(event, "canvas_y", getattr(event, "y", 0.0)))

        try:
            canvas.focus_set()
        except Exception:
            pass

        if self._preview_draw_mode:
            if not canvas.point_is_inside_image(canvas_x, canvas_y):
                return True

            point = self._clamp_preview_point(*canvas.canvas_to_image_coords(canvas_x, canvas_y, clamp=True))
            self._preview_draw_points.append(point)
            if len(self._preview_draw_points) >= 4:
                self._commit_new_preview_polygon()
            else:
                self._refresh_preview_canvas()
                self._update_preview_edit_status()
            return True

        if self._preview_delete_mode:
            polygon_hit = self._find_preview_polygon_hit(canvas_x, canvas_y)
            if polygon_hit is not None:
                self._preview_delete_candidate_idx = int(polygon_hit)
                self._preview_pending_vertex_hit = None
                self._set_selected_plate_index_for_ann(ann, int(polygon_hit))
                self._push_preview_debug_event(
                    "delete-select",
                    (
                        f"p{int(polygon_hit) + 1} canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                        f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                    )
                )
                self._refresh_preview_canvas()
                self._update_preview_edit_status(
                    f"Polygon {int(polygon_hit) + 1}/{len(self._get_plate_detections(ann))} jest zaznaczony do usunięcia. Kliknij PPM, aby go usunąć."
                )
                return True

            self._preview_delete_candidate_idx = None
            self._push_preview_debug_event(
                "delete-miss",
                (
                    f"canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                    f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                )
            )
            self._refresh_preview_canvas()
            self._update_preview_edit_status(
                "Tryb usuwania aktywny: kliknij wewnątrz polygonu, aby zaznaczyć tablicę do usunięcia."
            )
            return True

        if self._preview_modifier_active():
            drag_target = self._resolve_preview_drag_target(canvas_x, canvas_y)
            if drag_target is not None:
                plate_idx, vertex_idx, target_mode = drag_target
                previously_selected_plate = self._get_selected_plate_index_for_ann(ann)
                self._set_selected_plate_index_for_ann(ann, plate_idx)
                self._begin_preview_vertex_drag(plate_idx, vertex_idx, canvas_x, canvas_y)
                self._push_preview_debug_event(
                    "press-target",
                    (
                        f"{self._format_preview_debug_vertex_ref(plate_idx, vertex_idx)} "
                        f"mode={target_mode} canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                        f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                    )
                )
                if previously_selected_plate != int(plate_idx):
                    self._refresh_preview_canvas()
                self._update_preview_edit_status(
                    "Tryb W aktywny: uchwyt złapany. Przeciągnij mysz, aby poprawić róg."
                )
                return True

        vertex_hit = self._find_preview_vertex_hit(canvas_x, canvas_y)
        if vertex_hit is not None:
            plate_idx, vertex_idx = vertex_hit
            self._preview_pending_vertex_hit = None
            self._set_selected_plate_index_for_ann(ann, plate_idx)
            self._push_preview_debug_event(
                "press-handle",
                (
                    f"bez W {self._format_preview_debug_vertex_ref(plate_idx, vertex_idx)} "
                    f"canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                    f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                )
            )
            self._refresh_preview_canvas()
            self._update_preview_edit_status(
                "Aby przesuwać rogi tablicy, przytrzymaj W i przeciągaj uchwyt myszą."
            )
            return True

        polygon_hit = self._find_preview_polygon_hit(canvas_x, canvas_y)
        if polygon_hit is not None:
            self._preview_pending_vertex_hit = None
            self._set_selected_plate_index_for_ann(ann, polygon_hit)
            self._push_preview_debug_event(
                "press-polygon",
                (
                    f"p{int(polygon_hit) + 1} canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                    f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                )
            )
            self._refresh_preview_canvas()
            self._update_preview_edit_status()
            return True

        vehicle_hit = self._find_preview_vehicle_hit(canvas_x, canvas_y)
        if vehicle_hit is not None:
            self._preview_pending_vertex_hit = None
            self._set_selected_vehicle_index_for_ann(ann, vehicle_hit)
            self._push_preview_debug_event(
                "press-vehicle",
                (
                    f"v{int(vehicle_hit) + 1} canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                    f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                )
            )
            self._refresh_preview_canvas()
            self._update_preview_edit_status(
                f"Wybrano pojazd {int(vehicle_hit) + 1}/{len(self._get_vehicle_detections(ann))}. "
                "Spacja kadruje ten pojazd i przeskakuje do kolejnych aut."
            )
            return False

        self._preview_pending_vertex_hit = None
        if self._preview_corner_drag_modifier_down:
            self._push_preview_debug_event(
                "press-miss",
                (
                    f"W=on canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                    f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                )
            )
            self._update_preview_edit_status(
                "Tryb W aktywny: obraz jest zablokowany. Kliknij bezpośrednio uchwyt rogu, aby przesunąć wierzchołek."
            )
            return True

        return False

    def on_zoomable_canvas_drag(self, canvas: ZoomableCanvas, event):
        if canvas is not self.preview_canvas:
            return False

        canvas_x = float(getattr(event, "canvas_x", getattr(event, "x", 0.0)))
        canvas_y = float(getattr(event, "canvas_y", getattr(event, "y", 0.0)))
        drag_state = self._preview_drag_state
        ann = self._get_preview_annotation()
        if isinstance(drag_state, dict) and (ann is None or canvas.original_image is None):
            return self._finish_preview_vertex_drag(mark_dirty=False)

        if not isinstance(drag_state, dict) or ann is None or canvas.original_image is None:
            pending_hit = self._preview_pending_vertex_hit
            if (
                isinstance(pending_hit, dict)
                and ann is not None
                and canvas.original_image is not None
                and self._preview_modifier_active()
            ):
                plate_idx = int(pending_hit.get("plate_idx", -1))
                vertex_idx = int(pending_hit.get("vertex_idx", -1))
                anchor_canvas_x = float(pending_hit.get("anchor_canvas_x", canvas_x))
                anchor_canvas_y = float(pending_hit.get("anchor_canvas_y", canvas_y))
                if plate_idx >= 0 and vertex_idx >= 0:
                    self._set_selected_plate_index_for_ann(ann, plate_idx)
                    self._refresh_preview_canvas()
                    self._begin_preview_vertex_drag(plate_idx, vertex_idx, anchor_canvas_x, anchor_canvas_y)
                    self._push_preview_debug_event(
                        "drag-begin",
                        f"{self._format_preview_debug_vertex_ref(plate_idx, vertex_idx)} anchor=({anchor_canvas_x:.1f},{anchor_canvas_y:.1f})"
                    )
                    drag_state = self._preview_drag_state
                else:
                    self._preview_pending_vertex_hit = None
                    if self._preview_corner_drag_modifier_down:
                        return True
                    return False
            else:
                if self._preview_corner_drag_modifier_down:
                    return True
                return False

        if not isinstance(drag_state, dict):
            if self._preview_corner_drag_modifier_down:
                return True
            return False

        plate_detections = self._get_plate_detections(ann)
        plate_idx = int(drag_state.get("plate_idx", -1))
        vertex_idx = int(drag_state.get("vertex_idx", -1))
        if plate_idx < 0 or plate_idx >= len(plate_detections):
            return self._finish_preview_vertex_drag(mark_dirty=False)

        det = plate_detections[plate_idx]
        polygon = self._detection_polygon(det)
        if vertex_idx < 0 or vertex_idx >= len(polygon):
            return self._finish_preview_vertex_drag(mark_dirty=False)

        press_canvas_x = float(drag_state.get("press_canvas_x", canvas_x))
        press_canvas_y = float(drag_state.get("press_canvas_y", canvas_y))
        if not bool(drag_state.get("drag_started", False)):
            motion_canvas_dist = math.hypot(float(canvas_x) - press_canvas_x, float(canvas_y) - press_canvas_y)
            # Nizszy prog sprawia, ze chwyt zaczyna dzialac praktycznie od razu.
            if motion_canvas_dist < 1.5:
                self._push_preview_debug_event("drag-threshold", f"d={motion_canvas_dist:.2f}", refresh_only=True)
                return True
            drag_state["drag_started"] = True
            self._push_preview_history_snapshot(ann)
            self._push_preview_debug_event(
                "drag-start",
                f"{self._format_preview_debug_vertex_ref(plate_idx, vertex_idx)} d={motion_canvas_dist:.2f}"
            )

        cursor_x, cursor_y = canvas.canvas_to_image_coords(canvas_x, canvas_y, clamp=True)
        start_cursor_x = float(drag_state.get("start_cursor_x", cursor_x))
        start_cursor_y = float(drag_state.get("start_cursor_y", cursor_y))
        start_vertex_x = float(drag_state.get("start_vertex_x", polygon[vertex_idx][0]))
        start_vertex_y = float(drag_state.get("start_vertex_y", polygon[vertex_idx][1]))

        polygon[vertex_idx] = self._clamp_preview_point(
            start_vertex_x + (float(cursor_x) - start_cursor_x),
            start_vertex_y + (float(cursor_y) - start_cursor_y),
        )
        det.polygon = polygon
        det.bbox = self._bbox_from_polygon(polygon)
        det.keypoints = self._keypoints_from_polygon(polygon)
        det.attributes["manually_edited"] = "true"
        det.attributes["manual_source"] = "preview"
        ann.status = AnnotationStatus.SUCCESS
        ann.status_message = "Poligon tablicy poprawiony recznie."
        self._preview_last_modifier_press_at = time.monotonic()
        drag_state["was_moved"] = True

        # Zapis wykonujemy dopiero po zakonczeniu przeciagania, zeby nie mielic XML-a
        # przy kazdym ruchu kursora i nie powodowac lagow podczas edycji.
        self._schedule_preview_drag_refresh(delay_ms=0)
        now = time.monotonic()
        if (now - float(getattr(self, "_preview_debug_last_drag_update_at", 0.0) or 0.0)) >= 0.2:
            self._preview_debug_last_drag_update_at = now
            self._push_preview_debug_event("drag-move", refresh_only=True)
        return True

    def on_zoomable_canvas_release(self, canvas: ZoomableCanvas, event):
        if canvas is not self.preview_canvas:
            return False

        if self._preview_drag_state is None:
            if self._preview_pending_vertex_hit is not None:
                self._preview_pending_vertex_hit = None
                self._refresh_preview_canvas()
                self._update_preview_edit_status()
                self._push_preview_debug_event("release", "pending cleared without drag")
                return True
            return False

        self._push_preview_debug_event(
            "release",
            f"moved={int(bool(self._preview_drag_state.get('was_moved', False)))} "
            f"{self._format_preview_debug_vertex_ref(self._preview_drag_state.get('plate_idx'), self._preview_drag_state.get('vertex_idx'))}"
        )
        return self._finish_preview_vertex_drag(
            mark_dirty=bool(self._preview_drag_state.get("was_moved", False))
        )

    def _on_preview_select(self, event):
        sel = self.preview_listbox.curselection()
        if not sel or not self.current_annotations:
            return

        idx = self._get_preview_actual_index_from_display(int(sel[0]))
        if idx is None:
            return
        previous_idx = self.current_preview_index
        self.current_preview_index = idx
        self._preview_session_restore_index = idx
        self._preview_session_restore_filename = str(getattr(self.current_annotations[idx], "filename", "") or "")
        self._remember_annotation_run_resume_state()
        self._load_current_preview_selection(reset_view=True, selection_changed=(idx != previous_idx))
        self._queue_free_mode_session_save()
        try:
            self.preview_canvas.focus_set()
        except Exception:
            pass

    def _update_progress(self, pct, current, total, filename, successful=0):
        self._progress_update_seen = True
        self._cancel_pre_progress_activity()
        self.progress.configure(value=pct)
        self._set_progress_counters(successful, current, total)
        self._set_status_label_state(
            f"Przetwarzanie {current}/{total} ({int(pct)}%)",
            "success"
        )

    def _finish(self, success, msg):
        self.is_processing = False
        self._progress_update_seen = False
        self._cancel_pre_progress_activity()
        with self._progress_update_lock:
            self._pending_progress_update = None
            self._progress_update_flush_queued = False
        if hasattr(self.app, "end_exclusive_operation"):
            self.app.end_exclusive_operation("z2.annotation.run")
        else:
            self.app.set_processing(False)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.export_plate_dataset_btn.config(state=tk.NORMAL)
        self.progress.configure(value=(100 if success else 0))
        if success:
            total = len(getattr(self, "current_annotations", []) or [])
            if getattr(self, "_current_run_manual_template", False):
                successful = total
            else:
                successful = sum(1 for ann in (self.current_annotations or []) if getattr(ann, "is_successful", False))
            self._set_progress_counters(successful, total, total)
        else:
            self._set_progress_counters(0, 0, 0)
        
        if success:
            self._set_status_label_state("ZakoĹ„czono pomyĹ›lnie!", "success")
            next_steps = self._build_annotation_success_next_steps()
            self._set_post_annotation_hint(next_steps, "success")

            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name() and CAMPAIGN.get_current_step() == 2:
                    # Etap zostaĹ‚ wygenerowany, ale wymaga jeszcze rÄ™cznego zatwierdzenia.
                    staging_run = getattr(self, "last_staging_run_dir", None)
                    if staging_run is not None:
                        CAMPAIGN.set_step2_generated(str(staging_run))

                    # odblokuj przycisk rÄ™cznego zatwierdzania
                    self.approve_btn.config(state=tk.NORMAL)
                    self._pulse_action_frame("approve_btn_pulse_frame")

                    if 'campaign' in self.app.tabs:
                        self.app.tabs['campaign']._refresh_dashboard()

            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ zaktualizowaÄ‡ stanu kroku 2: {e}")

            self._refresh_step2_action_states()
            messagebox.showinfo("Koniec", f"{msg}\n\n{next_steps}")
        else:
            self._set_status_label_state("Przerwano / BĹ‚Ä…d", "error")
            self._set_post_annotation_hint("")
            self._refresh_step2_action_states()
            messagebox.showerror("Zatrzymano", msg)

    def _finish(self, success, msg):
        self.is_processing = False
        self._progress_update_seen = False
        self._cancel_pre_progress_activity()
        with self._progress_update_lock:
            self._pending_progress_update = None
            self._progress_update_flush_queued = False
        if hasattr(self.app, "end_exclusive_operation"):
            self.app.end_exclusive_operation("z2.annotation.run")
        else:
            self.app.set_processing(False)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.export_plate_dataset_btn.config(state=tk.NORMAL)
        self.progress.configure(value=(100 if success else 0))
        if success:
            total = len(getattr(self, "current_annotations", []) or [])
            if getattr(self, "_current_run_manual_template", False):
                successful = total
            else:
                successful = sum(1 for ann in (self.current_annotations or []) if getattr(ann, "is_successful", False))
            self._set_progress_counters(successful, total, total)
        else:
            self._set_progress_counters(0, 0, 0)

        if success:
            self._last_completed_workflow_route = self._get_workflow_route() or (
                "manual" if getattr(self, "_current_run_manual_template", False) else "auto"
            )
            self._manual_review_active = bool(getattr(self, "_current_run_manual_template", False))
            self._manual_review_from_auto = False
            self._manual_review_export_ready = False
            if self._is_free_mode_session_context():
                self.free_mode_screen_var.set(
                    "manual_review" if self._manual_review_active else "auto_summary"
                )
            self._set_status_label_state("Zakonczono pomyslnie!", "success")
            next_steps = self._build_annotation_success_next_steps()
            self._set_post_annotation_hint(next_steps, "success")

            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name() and CAMPAIGN.get_current_step() == 2:
                    staging_run = getattr(self, "last_staging_run_dir", None)
                    _staging_images_with_plates, staging_total_plates = self._get_run_plate_annotation_counts(staging_run)
                    if staging_run is not None:
                        CAMPAIGN.set_step2_generated(str(staging_run))
                    if staging_total_plates > 0:
                        self.approve_btn.config(state=tk.NORMAL)
                        self._pulse_action_frame("approve_btn_pulse_frame")
                    if "campaign" in self.app.tabs:
                        self.app.tabs["campaign"]._refresh_dashboard()
            except Exception as e:
                logger.debug(f"Nie udalo sie zaktualizowac stanu kroku 2: {e}")

            self._refresh_step2_action_states()
            self._refresh_left_panel_route_copy()
            self._refresh_free_mode_workflow_ui()
            if self._is_free_mode_session_context():
                try:
                    self.app.update_status(f"{msg} {next_steps}", "success")
                except Exception:
                    pass
            else:
                try:
                    self.app.update_status(f"{msg} {next_steps}", "success")
                except Exception:
                    pass
        else:
            self._set_status_label_state("Przerwano / Blad", "error")
            self._manual_review_active = False
            self._manual_review_from_auto = False
            self._manual_review_export_ready = False
            if self._is_free_mode_session_context():
                self.free_mode_screen_var.set("workflow" if self._get_workflow_route() else "route_choice")
            self._set_post_annotation_hint("")
            self._refresh_step2_action_states()
            self._refresh_left_panel_route_copy()
            self._refresh_free_mode_workflow_ui()
            try:
                parent_window = self.frame.winfo_toplevel()
            except Exception:
                parent_window = getattr(self.app, "root", None)

            def _show_error_dialog():
                messagebox.showerror("Zatrzymano", msg, parent=parent_window)

            try:
                self.frame.after_idle(_show_error_dialog)
            except Exception:
                _show_error_dialog()

    def _approve_annotation_stage(self):
        """
        Domyka etap E2 i przenosi staging runu anotacji do katalogu docelowego projektu.
        """
        try:
            from ..campaign_manager import CAMPAIGN
            import shutil

            if not self._ensure_preview_edits_saved("domkniecie etapu E2"):
                return

            if not CAMPAIGN.get_active_project_name():
                return messagebox.showwarning("Brak projektu", "Nie ma aktywnego projektu.")

            approval_context = self._get_campaign_step2_approval_context()
            staging_run = approval_context.get("run_dir")
            approval_source_kind = str(approval_context.get("source_kind") or "").strip().lower()
            approval_iteration_target = str(approval_context.get("iteration_target") or "").strip().lower()

            if staging_run is None:
                return messagebox.showwarning("Brak danych", "Nie znaleziono wygenerowanego staging runu anotacji do domkniecia E2.")

            staging_run = Path(staging_run)
            if not staging_run.exists():
                return messagebox.showerror("Brak folderu", f"Folder stagingu nie istnieje:\n{staging_run}")
            if approval_source_kind == "staging":
                staging_root = CAMPAIGN.get_staging_dir("auto_ann")
                if staging_root is None or not self._path_is_within(staging_run, staging_root):
                    return messagebox.showerror(
                        "Bledny staging",
                        "Run anotacji do zatwierdzenia lezy poza projektowym workspace stagingu.",
                    )

            _approval_images_with_plates, approval_total_plates = self._get_run_plate_annotation_counts(staging_run)
            if approval_total_plates <= 0:
                self._refresh_step2_action_states()
                return messagebox.showwarning(
                    "Brak tablic do zatwierdzenia",
                    (
                        "Ten run anotacji Z2 nie zawiera jeszcze ani jednej zapisanej tablicy 'plate'.\n\n"
                        "Dodaj i zapisz co najmniej jedna tablice, a dopiero potem zatwierdz E2."
                        if bool(self._manual_xml_template_enabled())
                        else "Ten run anotacji Z2 nie zawiera jeszcze ani jednej zapisanej tablicy 'plate'.\n\n"
                        "Popraw wynik albo dodaj co najmniej jedna tablice recznie, a dopiero potem zatwierdz E2."
                    ),
                )

            if approval_iteration_target in {"plate", "char"} and int(_approval_images_with_plates or 0) < 2:
                self._refresh_step2_action_states()
                return messagebox.showwarning(
                    "Za malo oznaczonych obrazow",
                    (
                        "Aby domknac E2 w torze tablic i przejsc do E4, potrzebujesz co najmniej 2 oznaczonych obrazow.\n\n"
                        f"Ten run ma teraz {_approval_images_with_plates} taki obraz(y).\n"
                        "Wroc do Z2, dodaj brakujace oznaczenia i dopiero wtedy zatwierdz etap."
                    )
                    if approval_iteration_target == "plate"
                    else (
                        "Aby przejsc z tablic do znakow, potrzebujesz co najmniej 2 oznaczonych obrazow.\n\n"
                        f"Ten run ma teraz {_approval_images_with_plates} taki obraz(y).\n"
                        "Wroc do Z2, dodaj brakujace oznaczenia i dopiero wtedy przejdz dalej. "
                        "Przy jednej tablicy nie przygotujesz potem poprawnego train i val dla znakow."
                    ),
                )

            final_auto_dir = CAMPAIGN.get_dir("auto_ann")
            if final_auto_dir is None:
                return messagebox.showerror("BĹ‚Ä…d", "Nie udaĹ‚o siÄ™ ustaliÄ‡ katalogu docelowego autoanotacji dla projektu.")

            final_auto_dir = Path(final_auto_dir)
            final_auto_dir.mkdir(parents=True, exist_ok=True)
            if not self._path_is_within(final_auto_dir, CAMPAIGN.get_active_project_root_dir()):
                return messagebox.showerror(
                    "Bledny katalog docelowy",
                    "Docelowy katalog autoanotacji lezy poza workspace aktywnego projektu.",
                )

            target_dir = staging_run

            # jeĹ›li ktoĹ› zatwierdza drugi raz, najpierw czyĹ›cimy stare
            if approval_source_kind == "staging":
                target_dir = final_auto_dir / staging_run.name
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.move(str(staging_run), str(target_dir))
            elif not self._path_is_within(target_dir, final_auto_dir):
                return messagebox.showerror(
                    "Bledny run anotacji",
                    "Run wybrany do dalszej pracy nie lezy w projektowym katalogu autoanotacji.",
                )
            self.current_annotation_run_dir = target_dir
            self.current_annotation_xml_path = target_dir / "annotations.xml"
            self.last_staging_run_dir = target_dir
            try:
                manifest = self._load_annotation_run_manifest(target_dir)
                if self._annotation_run_manifest_has_manual_value(manifest):
                    self._remember_campaign_manual_plate_source(
                        run_dir=target_dir,
                        xml_path=target_dir / "annotations.xml",
                        input_dir=self.current_input_dir,
                    )
            except Exception:
                pass
            try:
                if Path(str(self.plate_dataset_run_var.get() or "").strip()) == staging_run:
                    self.plate_dataset_run_var.set(str(target_dir))
                    self._refresh_plate_dataset_export_sources()
            except Exception:
                pass

            self._queue_free_mode_session_save()

            CAMPAIGN.approve_step2()
            next_step = 4 if CAMPAIGN.get_iteration_target() == "plate" else 3
            CAMPAIGN.set_current_step(next_step)

            self.approve_btn.config(state=tk.DISABLED)
            self._refresh_step2_action_states()

            if 'campaign' in self.app.tabs:
                self.app.tabs['campaign']._refresh_dashboard()
                if next_step == 3:
                    self.app.update_status(
                        "Tablice zostaly zatwierdzone jako zrodlo dla toru znakow. Otwieram Z3.",
                        "info"
                    )
                    messagebox.showinfo(
                        "Tablice gotowe",
                        f"Zrodlo tablic zostalo zatwierdzone.\n\nPrzechodze do pracy nad znakami w Z3.\n\nRun zrodlowy:\n{target_dir}"
                    )
                    try:
                        source_context = {"restore_run_dir": str(target_dir)}
                        if self.current_input_dir is not None:
                            source_context["input_dir"] = str(self.current_input_dir)
                    except Exception:
                        source_context = {"restore_run_dir": str(target_dir)}
                    try:
                        campaign_tab = self.app.tabs.get("campaign")
                        if campaign_tab is not None:
                            campaign_tab._step_goto_characters(preferred_source_context=source_context)
                    except Exception as e:
                        logger.debug(f"Nie udalo sie przejsc z Z2 do Z3 po zatwierdzeniu toru znakow: {e}")
                    return

            next_step_label = "E4 / trening tablic" if next_step == 4 else "E3 / tor znakĂłw"
            self.app.update_status(
                "Domknieto etap E2 anotacji. Wyniki przeniesiono z katalogu stagingu do "
                f"2_auto_annotations projektu. Kolejny krok: {next_step_label}.",
                "info"
            )
            # po zatwierdzeniu wracamy do Wizarda
            try:
                self.app.select_tab("campaign")
                self.app.update_campaign_tab_access()
            except Exception as e:
                logger.debug(f"Nie udaĹ‚o siÄ™ wrĂłciÄ‡ do zakĹ‚adki Wizarda: {e}")

            messagebox.showinfo("Sukces", f"Etap E2 anotacji zostal domkniety.\n\nWyniki przeniesiono do:\n{target_dir}")

        except Exception as e:
            messagebox.showerror("Blad domkniecia E2", str(e))

    def _stop_annotation(self):
        self.is_processing = False
        if self.annotator and hasattr(self.annotator, 'stop'):
            self.annotator.stop()
        self._set_status_label_state("Zatrzymywanie...", "warning")

