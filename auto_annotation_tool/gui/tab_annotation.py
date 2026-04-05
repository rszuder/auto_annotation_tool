#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Autoanotacja - Główne przetwarzanie YOLO (pojazdy + tablice)
Układ 3-kolumnowy z interaktywną przeglądarką na Canvasie.
"""

import json
from collections import deque
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
import numpy as np

import cv2
from PIL import Image, ImageTk
from .zoomable_canvas import ZoomableCanvas

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
        
        # Zmienne do przeglądarki
        self.current_annotations = []
        self.current_input_dir = None
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
        self._main_pane_layout_after_id = None
        self._main_pane_layout_initialized = False
        self._current_run_manual_template = False
        self._current_run_manual_vehicle_assist = False
        self.preview_edit_status_var = tk.StringVar(value="Po zakończeniu autoanotacji tutaj poprawisz rogi tablic.")
        self.preview_debug_var = tk.StringVar(value="DEBUG Z2 | oczekiwanie na zdarzenia")
        self.preview_fullscreen_hint_var = tk.StringVar(value="")

        self.mode_var = tk.StringVar(value=session_state["mode"])
        self.vehicle_model_var = tk.StringVar(value=session_state["vehicle_model"])
        self.character_model_var = tk.StringVar(value=session_state["character_model"])
        self.vehicle_custom_var = tk.StringVar(value=session_state["vehicle_custom"])
        self.plate_custom_var = tk.StringVar(value=session_state["plate_custom"])
        self.character_custom_var = tk.StringVar(value=session_state["character_custom"])
        self.device_var = tk.StringVar(value=session_state["device"])
        self.conf_var = tk.DoubleVar(value=session_state["conf"])
        self._campaign_paths_locked = False
        self._annotation_log_visible = False
        self._character_model_options = {}
        self._left_section_separators = []
        self._left_title_underlines = []
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
        self.progress_counts_var = tk.StringVar(value="udane/przer./całość: 0/0/0")
        # Domyślnie podpowiadaj katalog wejściowy z workspace.
        self.input_dir_var = tk.StringVar(value=session_state["input_dir"])
        self.output_dir_var = tk.StringVar(value=session_state["output_dir"])
        self.manual_xml_template_var = tk.BooleanVar(value=bool(session_state["manual_xml_template"]))
        self.manual_vehicle_assist_var = tk.BooleanVar(value=bool(session_state["manual_vehicle_assist"]))
        self.manual_xml_template_hint_var = tk.StringVar(value="")
        self.manual_vehicle_assist_hint_var = tk.StringVar(value="")
        self.manual_stage_dir_var = tk.StringVar(value="")
        self.manual_stage_status_var = tk.StringVar(value="")
        self.approve_gate_hint_var = tk.StringVar(value="")
        self.detection_mode_hint_var = tk.StringVar(value="")
        last_preview_run_dir = str(session_state["last_preview_run_dir"] or "").strip()
        self.last_staging_run_dir = Path(last_preview_run_dir) if last_preview_run_dir else None

        self._create_widgets()
        self._apply_free_mode_session_snapshot(session_state, restore_preview=True)
        self._bind_free_mode_session_observers()
        self.frame.after_idle(self._mark_startup_ui_ready)

    def _mark_startup_ui_ready(self):
        self._startup_ui_ready = True

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
            "last_preview_run_dir": "",
            "last_preview_index": -1,
            "last_preview_filename": "",
        }

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
    def _paths_equivalent(left, right) -> bool:
        if not left or not right:
            return False

        try:
            return Path(left).resolve() == Path(right).resolve()
        except Exception:
            return str(Path(left)) == str(Path(right))

    @staticmethod
    def _path_is_within(candidate, root) -> bool:
        if not candidate or not root:
            return False

        try:
            candidate_path = Path(candidate).resolve()
            root_path = Path(root).resolve()
        except Exception:
            return False

        try:
            candidate_path.relative_to(root_path)
            return True
        except Exception:
            return False

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
            "last_preview_run_dir": self._get_annotation_session_text("last_preview_run_dir", defaults["last_preview_run_dir"], allow_empty=True),
            "last_preview_index": self._get_annotation_session_int("last_preview_index", defaults["last_preview_index"]),
            "last_preview_filename": self._get_annotation_session_text("last_preview_filename", defaults["last_preview_filename"], allow_empty=True),
        }

    def _collect_free_mode_session_snapshot(self) -> dict:
        run_dir_value = ""
        selected_ann = self._get_preview_annotation()
        for candidate in (
            getattr(self, "current_annotation_run_dir", None),
            getattr(self, "last_staging_run_dir", None),
            str(self.plate_dataset_run_var.get() or "").strip(),
        ):
            if not candidate:
                continue
            try:
                run_dir_value = str(Path(candidate))
                break
            except Exception:
                continue

        return {
            "input_dir": str(self.input_dir_var.get() or "").strip(),
            "output_dir": str(self.output_dir_var.get() or "").strip(),
            "mode": self._normalize_mode_value(),
            "vehicle_model": str(self.vehicle_model_var.get() or "").strip(),
            "vehicle_custom": str(self.vehicle_custom_var.get() or "").strip(),
            "plate_custom": str(self.plate_custom_var.get() or "").strip(),
            "character_model": str(self.character_model_var.get() or "").strip(),
            "character_custom": str(self.character_custom_var.get() or "").strip(),
            "device": str(self.device_var.get() or "").strip(),
            "conf": float(self.conf_var.get()),
            "plate_dataset_run": str(self.plate_dataset_run_var.get() or "").strip(),
            "plate_dataset_images": str(self.plate_dataset_images_var.get() or "").strip(),
            "plate_train_pct": float(self.plate_train_pct.get()),
            "plate_val_pct": float(self.plate_val_pct.get()),
            "manual_xml_template": bool(self.manual_xml_template_var.get()),
            "manual_vehicle_assist": bool(self.manual_vehicle_assist_var.get()),
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
            if not candidate:
                continue
            try:
                run_dir_value = str(Path(candidate))
                break
            except Exception:
                continue

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
            "output_dir": str(self.output_dir_var.get() or "").strip(),
            "mode": self._normalize_mode_value(),
            "vehicle_model": str(self.vehicle_model_var.get() or "").strip(),
            "vehicle_custom": str(self.vehicle_custom_var.get() or "").strip(),
            "plate_custom": str(self.plate_custom_var.get() or "").strip(),
            "character_model": str(self.character_model_var.get() or "").strip(),
            "character_custom": str(self.character_custom_var.get() or "").strip(),
            "device": str(self.device_var.get() or "").strip(),
            "conf": float(self.conf_var.get()),
            "plate_dataset_run": str(self.plate_dataset_run_var.get() or "").strip(),
            "plate_dataset_images": str(self.plate_dataset_images_var.get() or "").strip(),
            "plate_train_pct": float(self.plate_train_pct.get()),
            "plate_val_pct": float(self.plate_val_pct.get()),
            "manual_xml_template": bool(self.manual_xml_template_var.get()),
            "manual_vehicle_assist": bool(self.manual_vehicle_assist_var.get()),
            "last_preview_run_dir": run_dir_value,
            "last_preview_index": (
                int(self.current_preview_index)
                if self.current_preview_index is not None
                else -1
            ),
            "last_preview_filename": str(getattr(selected_ann, "filename", "") or "").strip(),
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

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

            plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
            plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())

            bootstrap["input_dir"] = default_input
            bootstrap["plate_model_path"] = plate_model_path if plate_model_ready else ""
            bootstrap["manual_template"] = bool(target == "plate" and not plate_model_ready)

            manual_source_run = self._find_reused_manual_source_run(default_input)
            if manual_source_run is not None and (manual_source_run / "annotations.xml").exists():
                bootstrap["restore_run_dir"] = manual_source_run
                bootstrap["input_source"] = "manual_source_run"

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

    def _restore_preview_from_annotation_run(self, run_dir: Path | None) -> bool:
        if run_dir is None:
            return False

        try:
            run_dir = Path(run_dir)
        except Exception:
            return False

        xml_path = run_dir / "annotations.xml"
        if not run_dir.exists() or not run_dir.is_dir() or not xml_path.exists():
            return False

        try:
            self._load_plate_dataset_context_from_run(run_dir, force_images_update=True)
            self._restore_preview_from_session_run()
            self._refresh_plate_dataset_export_sources()
            return True
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic podgladu Z2 z runu {run_dir}: {e}")
            return False

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
            self.plate_dataset_run_var.set(str(state.get("plate_dataset_run") or "").strip())
            self.plate_dataset_images_var.set(str(state.get("plate_dataset_images") or "").strip())
            self.plate_train_pct.set(float(state.get("plate_train_pct", 80.0)))
            self.plate_val_pct.set(float(state.get("plate_val_pct", 10.0)))
            self.manual_xml_template_var.set(bool(state.get("manual_xml_template", False)))
            self.manual_vehicle_assist_var.set(bool(state.get("manual_vehicle_assist", False)))

            last_preview_run_dir = str(state.get("last_preview_run_dir") or "").strip()
            self.last_staging_run_dir = Path(last_preview_run_dir) if last_preview_run_dir else None
            try:
                self._preview_session_restore_index = int(state.get("last_preview_index", -1))
            except (TypeError, ValueError):
                self._preview_session_restore_index = -1
            self._preview_session_restore_filename = str(state.get("last_preview_filename") or "").strip()

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

            self._on_mode_change()
            self._on_vehicle_model_change()
            self._update_manual_xml_template_ui()
            self._update_plate_dataset_ratio_labels()
            self._refresh_plate_dataset_export_sources()
            self._set_campaign_paths_lock_state(True)

            input_dir_value = str(self.input_dir_var.get() or "").strip()
            self.current_input_dir = Path(input_dir_value) if input_dir_value else None

            if restore_preview:
                self._restore_preview_from_session_run()
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
        state = dict(session_state or self._load_free_mode_session_snapshot())
        self._free_mode_session_restore_in_progress = True
        try:
            self.input_dir_var.set(str(state.get("input_dir") or self._annotation_session_defaults()["input_dir"]))
            self.output_dir_var.set(str(state.get("output_dir") or self._annotation_session_defaults()["output_dir"]))
            self.mode_var.set(self._normalize_mode_value(state.get("mode")))
            self.vehicle_model_var.set(str(state.get("vehicle_model") or "").strip())
            self.vehicle_custom_var.set(str(state.get("vehicle_custom") or "").strip())
            self.plate_custom_var.set(str(state.get("plate_custom") or "").strip())
            self.character_model_var.set(str(state.get("character_model") or "Brak / OCR").strip() or "Brak / OCR")
            self.character_custom_var.set(str(state.get("character_custom") or "").strip())
            self.device_var.set(str(state.get("device") or "auto").strip() or "auto")
            self.conf_var.set(float(state.get("conf", CONFIG.DEFAULT_CONFIDENCE)))
            self.plate_dataset_run_var.set(str(state.get("plate_dataset_run") or "").strip())
            self.plate_dataset_images_var.set(str(state.get("plate_dataset_images") or "").strip())
            self.plate_train_pct.set(float(state.get("plate_train_pct", 80.0)))
            self.plate_val_pct.set(float(state.get("plate_val_pct", 10.0)))
            self.manual_xml_template_var.set(bool(state.get("manual_xml_template", False)))
            self.manual_vehicle_assist_var.set(bool(state.get("manual_vehicle_assist", False)))

            last_preview_run_dir = str(state.get("last_preview_run_dir") or "").strip()
            self.last_staging_run_dir = Path(last_preview_run_dir) if last_preview_run_dir else None
            try:
                preview_restore_index = int(state.get("last_preview_index", -1))
            except (TypeError, ValueError):
                preview_restore_index = -1
            self._preview_session_restore_index = preview_restore_index
            self._preview_session_restore_filename = str(state.get("last_preview_filename") or "").strip()

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

            self._on_mode_change()
            self._on_vehicle_model_change()
            self._update_manual_xml_template_ui()
            self._update_plate_dataset_ratio_labels()
            self._refresh_plate_dataset_export_sources()
            self._set_campaign_paths_lock_state(False)

            input_dir_value = str(self.input_dir_var.get() or "").strip()
            self.current_input_dir = Path(input_dir_value) if input_dir_value else None

            if restore_preview:
                self._restore_preview_from_session_run()
            self._refresh_step2_action_states()
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
            candidate = Path(run_dir_text)
            if candidate.exists() and candidate.is_dir():
                run_dir = candidate
        elif getattr(self, "last_staging_run_dir", None):
            candidate = Path(self.last_staging_run_dir)
            if candidate.exists() and candidate.is_dir():
                run_dir = candidate

        if run_dir is None:
            return

        xml_path = run_dir / "annotations.xml"
        if not xml_path.exists():
            return

        manifest = self._load_annotation_run_manifest(run_dir)
        try:
            annotations = self._parse_cvat_preview_annotations(xml_path)
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic ostatniego runu Z2: {e}")
            return

        if not annotations:
            return

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
            return

        self._clear_preview_editor_state(clear_dirty=True)
        self.current_annotations = annotations
        self.current_input_dir = image_dir
        self.plate_dataset_images_var.set(str(image_dir))
        self.current_annotation_run_dir = run_dir
        self.current_annotation_xml_path = xml_path
        self.last_staging_run_dir = run_dir
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
        self._refresh_preview_list(preserve_selection=True, render_current=True)
        self._refresh_step2_action_states()
        self._update_preview_edit_status("Przywrocono ostatni run Z2 z poprzedniej sesji.")

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
        pane = getattr(self, "main_pane", None)
        if pane is None:
            return

        try:
            pane.update_idletasks()
        except Exception:
            pass

        try:
            if not self._pane_has_child(pane, self.main_left_frame):
                return
            if not self._pane_has_child(pane, self.main_center_frame):
                return
            if not self._pane_has_child(pane, self.main_right_frame):
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
            pane.sashpos(0, int(desired_left))
            pane.sashpos(1, int(desired_second))
            self._main_pane_layout_initialized = True
        except Exception:
            pass

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

    def _build_left_title_underline(self, parent, label_widget, pady=(2, 4)):
        if parent is None or label_widget is None:
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

        line_width = 120
        try:
            label_font = tkfont.Font(font=label_widget.cget("font"))
            label_text = str(label_widget.cget("text") or "").strip()
            if label_text:
                line_width = max(72, min(280, label_font.measure(label_text) + 6))
        except Exception:
            pass

        accent_line = tk.Frame(
            host,
            width=line_width,
            height=1,
            bd=0,
            highlightthickness=0,
            bg=palette.get("success", palette.get("accent", "#0e639c")),
        )
        accent_line.pack(anchor=tk.W)

        self._left_title_underlines.append(
            {
                "host": host,
                "accent": accent_line,
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

    def _create_widgets(self):
        pane = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        self.main_pane = pane

        left_frame = ttk.Frame(pane)
        center_frame = ttk.Frame(pane)
        right_frame = ttk.Frame(pane)
        self.main_left_frame = left_frame
        self.main_center_frame = center_frame
        self.main_right_frame = right_frame

        pane.add(left_frame, weight=2)
        pane.add(center_frame, weight=6)
        pane.add(right_frame, weight=1)
        pane.bind("<Configure>", self._on_main_pane_configure, add="+")
        pane.bind("<B1-Motion>", self._on_main_pane_drag_motion, add="+")
        pane.bind("<ButtonRelease-1>", self._on_main_pane_drag_release, add="+")

        # --- LEWA KOLUMNA ---
        left_scroll_host = ttk.Frame(left_frame, style="Panel.TFrame")
        left_scroll_host.pack(fill=tk.BOTH, expand=True)

        self.left_settings_canvas = tk.Canvas(left_scroll_host, highlightthickness=0, bd=0)
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

        settings_col = ttk.Frame(self.left_settings_content, style="Panel.TFrame")
        settings_col.pack(fill=tk.X, expand=True, padx=12, pady=(14, 20))

        source_section = ttk.Frame(settings_col, style="Panel.TFrame")
        source_section.pack(fill=tk.X)
        self.sources_title_lbl = ttk.Label(
            source_section,
            text="Źródło obrazów i folder wyników Z2",
            style="Panel.TLabel"
        )
        self.sources_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._build_left_title_underline(source_section, self.sources_title_lbl, pady=(2, 4))

        self.input_dir_title_lbl = ttk.Label(
            source_section,
            text="Wybierz folder obrazów do autoanotacji",
            style="Panel.TLabel"
        )
        self.input_dir_title_lbl.pack(anchor=tk.W, fill=tk.X)
        row_in, self.input_dir_entry, self.input_dir_browse_btn = self._build_left_path_row(
            source_section,
            self.input_dir_var,
            button_text="Wybierz",
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
            text="Folder wyników Z2 (tu powstają foldery run_XXX):",
            style="Panel.TLabel"
        )
        self.output_dir_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.output_dir_var.set(str(Path(CONFIG.get_auto_annotations_dir("plate"))))
        row_out, self.output_dir_entry, _ = self._build_left_path_row(
            source_section,
            self.output_dir_var,
            state="readonly",
        )

        self._build_left_section_separator(settings_col, pady=(16, 20))

        actions_lf = ttk.Frame(settings_col, style="Panel.TFrame")
        actions_lf.pack(fill=tk.X)
        self.run_title_lbl = ttk.Label(
            actions_lf,
            text="Krok 1: Utwórz run autoanotacji tablic",
            style="Panel.TLabel"
        )
        self.run_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._build_left_title_underline(actions_lf, self.run_title_lbl, pady=(2, 4))

        self.manual_xml_template_check = ttk.Checkbutton(
            actions_lf,
            text="Utwórz pusty XML do ręcznej anotacji tablic",
            variable=self.manual_xml_template_var,
            command=self._update_manual_xml_template_ui
        )
        self.manual_xml_template_check.pack(anchor=tk.W, pady=(2, 2))

        self.manual_vehicle_assist_check = ttk.Checkbutton(
            actions_lf,
            text="Wstepnie autoanotuj same pojazdy (bez tablic)",
            variable=self.manual_vehicle_assist_var,
            command=self._update_manual_xml_template_ui
        )

        self.manual_vehicle_assist_hint_lbl = tk.Label(
            actions_lf,
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

        self.start_btn_row = ttk.Frame(actions_lf, style="Panel.TFrame")
        self.start_btn_row.pack(fill=tk.X, pady=(5, 0))
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
            text="STARTUJ AUTOANOTACJĘ",
            command=self._start_annotation,
            style="Accent.TButton"
        )
        self.start_btn.pack(fill=tk.X)

        self.stop_btn = ttk.Button(
            self.start_btn_row,
            text="ZATRZYMAJ",
            command=self._stop_annotation,
            state=tk.DISABLED
        )
        self.stop_btn.grid(row=0, column=1, sticky="ew")

        progress_info_row = ttk.Frame(actions_lf, style="Panel.TFrame")
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
            actions_lf,
            maximum=100,
            value=0,
            thickness=2
        )
        self.progress.pack(fill=tk.X, pady=(0, 2))
        self._set_progress_counters(0, 0, 0)

        self.post_annotation_hint_lbl = tk.Label(
            actions_lf,
            text="",
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )

        self.manual_stage_section = ttk.Frame(settings_col, style="Panel.TFrame")
        self.manual_stage_section.pack(fill=tk.X)
        self.manual_stage_title_lbl = ttk.Label(
            self.manual_stage_section,
            text="Stage oczekujacych recznej anotacji",
            style="Panel.TLabel"
        )
        self.manual_stage_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._build_left_title_underline(self.manual_stage_section, self.manual_stage_title_lbl, pady=(2, 4))

        self.manual_stage_help_lbl = tk.Label(
            self.manual_stage_section,
            text=(
                "Stage to pomocnicza kolejka zdjec odlozonych na kolejna iteracje. "
                "Po eksporcie datasetu trafia tu nieoznaczona czesc paczki, a recznie mozesz "
                "tez dolozyc nowe zdjecia bez mieszania ich z juz oznaczonym zbiorem."
            ),
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
            bd=0,
            highlightthickness=0
        )
        self.manual_stage_help_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        self._set_inline_label_state(self.manual_stage_help_lbl, tone="info", emphasis=False)

        self.manual_stage_path_title_lbl = ttk.Label(
            self.manual_stage_section,
            text="Folder stage (kolejna pula do anotacji):",
            style="Panel.TLabel"
        )
        self.manual_stage_path_title_lbl.pack(anchor=tk.W, fill=tk.X)
        _, self.manual_stage_path_entry, _ = self._build_left_path_row(
            self.manual_stage_section,
            self.manual_stage_dir_var,
            state="readonly",
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
            command=self._use_manual_plate_stage_as_input,
        )
        self.manual_stage_use_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.manual_stage_add_btn = ttk.Button(
            self.manual_stage_buttons_row,
            text="Dodaj zdjecia do stage",
            command=self._add_images_to_manual_plate_stage,
        )
        self.manual_stage_add_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.manual_stage_separator = self._build_left_section_separator(settings_col, pady=(18, 20))

        export_lf = ttk.Frame(settings_col, style="Panel.TFrame")
        export_lf.pack(fill=tk.X)
        self.export_title_lbl = ttk.Label(
            export_lf,
            text="Krok 2: Z istniejącego runu zbuduj dataset YOLO Pose",
            style="Panel.TLabel"
        )
        self.export_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._build_left_title_underline(export_lf, self.export_title_lbl, pady=(2, 4))

        run_row = ttk.Frame(export_lf, style="Panel.TFrame")
        run_row.pack(fill=tk.X, pady=(0, 4))
        self.plate_dataset_run_title_lbl = ttk.Label(
            run_row,
            text="Run autoanotacji tablic (produkt przycisku Start):",
            style="Panel.TLabel"
        )
        self.plate_dataset_run_title_lbl.pack(anchor=tk.W)
        run_input, self.plate_dataset_run_entry, self.plate_dataset_run_btn = self._build_left_path_row(
            run_row,
            self.plate_dataset_run_var,
            button_text="Wskaż inny run",
            button_command=self._select_plate_dataset_run_dir,
        )

        img_row = ttk.Frame(export_lf, style="Panel.TFrame")
        img_row.pack(fill=tk.X, pady=(0, 4))
        self.plate_dataset_images_title_lbl = ttk.Label(
            img_row,
            text="Folder źródłowych obrazów dla wybranego runu:",
            style="Panel.TLabel"
        )
        self.plate_dataset_images_title_lbl.pack(anchor=tk.W)
        img_input, self.plate_dataset_images_entry, self.plate_dataset_images_btn = self._build_left_path_row(
            img_row,
            self.plate_dataset_images_var,
            button_text="Wskaż obrazy",
            button_command=self._select_plate_dataset_images_dir,
        )

        out_row = ttk.Frame(export_lf, style="Panel.TFrame")
        out_row.pack(fill=tk.X, pady=(0, 8))
        self.plate_dataset_out_title_lbl = ttk.Label(
            out_row,
            text="Docelowy katalog datasetu YOLO Pose:",
            style="Panel.TLabel"
        )
        self.plate_dataset_out_title_lbl.pack(anchor=tk.W)
        out_input, self.plate_dataset_out_entry, _ = self._build_left_path_row(
            out_row,
            self.plate_dataset_out_var,
            state="readonly",
        )

        split_lf = ttk.Frame(export_lf, style="Panel.TFrame")
        split_lf.pack(fill=tk.X, pady=(0, 8))
        self.split_title_lbl = ttk.Label(split_lf, text="Split treningowy", style="Panel.TLabel")
        self.split_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._build_left_title_underline(split_lf, self.split_title_lbl, pady=(2, 4))

        split_grid = ttk.Frame(split_lf, style="Panel.TFrame")
        split_grid.pack(fill=tk.X)

        ttk.Label(split_grid, text="Train %", style="Panel.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Scale(
            split_grid,
            from_=50,
            to=90,
            variable=self.plate_train_pct,
            command=lambda e: self._update_plate_dataset_ratio_labels()
        ).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.plate_train_lbl = ttk.Label(split_grid, text="80%", style="Panel.TLabel")
        self.plate_train_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(split_grid, text="Val %", style="Panel.TLabel").grid(row=1, column=0, sticky=tk.W)
        ttk.Scale(
            split_grid,
            from_=5,
            to=40,
            variable=self.plate_val_pct,
            command=lambda e: self._update_plate_dataset_ratio_labels()
        ).grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.plate_val_lbl = ttk.Label(split_grid, text="10%", style="Panel.TLabel")
        self.plate_val_lbl.grid(row=1, column=2, sticky=tk.W)

        ttk.Label(split_grid, text="Test %", style="Panel.TLabel").grid(row=2, column=0, sticky=tk.W)
        ttk.Label(split_grid, text="liczony automatycznie", style="PanelMuted.TLabel").grid(row=2, column=1, sticky=tk.W, padx=5)
        self.plate_test_lbl = ttk.Label(split_grid, text="Test: 10%", style="Panel.TLabel")
        self.plate_test_lbl.grid(row=2, column=2, sticky=tk.W)
        split_grid.columnconfigure(1, weight=1)

        self.export_plate_dataset_btn = ttk.Button(
            export_lf,
            text="WYEKSPORTUJ DATASET TABLIC",
            command=self._start_plate_dataset_export
        )
        self.export_plate_dataset_btn.pack(fill=tk.X)

        self.plate_export_progress = ttk.Progressbar(
            export_lf,
            variable=self.plate_export_progress_var,
            maximum=100
        )
        self.plate_export_progress.pack(fill=tk.X, pady=(8, 4))

        self.plate_export_status_lbl = tk.Label(
            export_lf,
            text="Wskaż run i obrazy do eksportu datasetu.",
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

        self._update_plate_dataset_ratio_labels()
        self._refresh_plate_dataset_export_sources()

        # --- ŚRODKOWA KOLUMNA (PODGLĄD + TERMINAL PROCESU) ---
        preview_host = ttk.Frame(center_frame)
        self.preview_host = preview_host
        preview_host.pack(fill=tk.BOTH, expand=True, padx=5, pady=0)

        preview_pane = ttk.PanedWindow(preview_host, orient=tk.HORIZONTAL)
        self.preview_pane = preview_pane
        preview_pane.pack(fill=tk.BOTH, expand=True)

        list_lf = ttk.LabelFrame(preview_pane, text=" Lista wyników autoanotacji ", padding=8)
        self.preview_list_lf = list_lf
        preview_pane.add(list_lf, weight=1)
        list_frame = ttk.Frame(list_lf)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_listbox = tk.Listbox(list_frame, font=("Consolas", 9), selectbackground="#3498db")
        self.preview_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = WebSlimScrollbar(list_frame, command=self.preview_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_listbox.config(yscrollcommand=scroll.set)
        self.preview_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

        preview_lf = ttk.LabelFrame(preview_pane, text=" Podgląd autoanotacji ", padding=8)
        self.preview_lf = preview_lf
        preview_pane.add(preview_lf, weight=4)
        preview_tools = ttk.Frame(preview_lf)
        self.preview_tools = preview_tools

        self.preview_prev_btn = ttk.Button(
            preview_tools,
            text="Poprzednie (Q)",
            command=lambda: self._select_preview_relative(-1),
            state=tk.DISABLED
        )
        self.preview_prev_btn.pack(side=tk.LEFT)

        self.preview_next_btn = ttk.Button(
            preview_tools,
            text="Nastepne (E)",
            command=lambda: self._select_preview_relative(1),
            state=tk.DISABLED
        )
        self.preview_next_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.preview_fit_btn = ttk.Button(
            preview_tools,
            text="Dopasuj",
            command=self._fit_preview_image_to_view,
            state=tk.DISABLED
        )
        self.preview_fit_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.preview_draw_btn = ttk.Button(
            preview_tools,
            text="Nowy polygon 4 pkt (D)",
            command=self._toggle_preview_draw_mode,
            state=tk.DISABLED
        )
        self.preview_draw_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.preview_fullscreen_btn = ttk.Button(
            preview_tools,
            text="Pelny ekran (Enter)",
            command=self._toggle_preview_fullscreen,
            state=tk.DISABLED
        )
        self.preview_fullscreen_btn.pack(side=tk.LEFT, padx=(10, 0))

        self.preview_fullscreen_hint_lbl = tk.Label(
            preview_lf,
            textvariable=self.preview_fullscreen_hint_var,
            anchor="w",
            justify=tk.LEFT,
            wraplength=780,
            bd=0,
            highlightthickness=0
        )
        self._set_inline_label_state(self.preview_fullscreen_hint_lbl, tone="info", emphasis=False)

        self.preview_save_btn = ttk.Button(
            preview_tools,
            text="Zapisz (Ctrl+S)",
            command=self._save_preview_edits,
            state=tk.DISABLED
        )
        self.preview_save_btn.pack(side=tk.RIGHT)

        preview_hint_frame = ttk.Frame(preview_lf)
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
        if self._preview_debug_enabled:
            self.preview_debug_lbl.pack(fill=tk.X, pady=(6, 0))
            self._set_inline_label_state(self.preview_debug_lbl, tone="muted", emphasis=False)
        self._refresh_preview_debug_status()

        log_tools = ttk.Frame(center_frame)
        self.log_tools = log_tools
        log_tools.pack(fill=tk.X, padx=5, pady=(8, 0))

        self.btn_toggle_annotation_log = ttk.Button(
            log_tools,
            text="Pokaż terminal",
            command=self._toggle_annotation_process_log
        )
        self.btn_toggle_annotation_log.pack(side=tk.LEFT)

        ttk.Label(
            log_tools,
            text="Terminal procesu jest dostępny na żądanie użytkownika.",
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

        # --- PRAWA KOLUMNA ---
        right_scroll_host = ttk.Frame(right_frame)
        right_scroll_host.pack(fill=tk.BOTH, expand=True)

        self.right_settings_canvas = tk.Canvas(right_scroll_host, highlightthickness=0, bd=0)
        self.right_settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.right_settings_scrollbar = WebSlimScrollbar(
            right_scroll_host,
            command=self.right_settings_canvas.yview
        )
        self.right_settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_settings_canvas.configure(yscrollcommand=self.right_settings_scrollbar.set)

        self.right_settings_content = ttk.Frame(self.right_settings_canvas)
        self._right_settings_window_id = self.right_settings_canvas.create_window(
            (0, 0),
            window=self.right_settings_content,
            anchor="nw"
        )
        self.right_settings_content.bind("<Configure>", self._sync_right_panel_scrollregion)
        self.right_settings_canvas.bind("<Configure>", self._sync_right_panel_canvas_width)

        settings_lf = ttk.LabelFrame(self.right_settings_content, text=" Konfiguracja Detekcji ", padding=15)
        settings_lf.pack(fill=tk.BOTH, expand=True)

        self.approve_btn_row = ttk.LabelFrame(right_frame, text=" Zatwierdzenie E2 ", padding=10)
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

        ttk.Label(settings_lf, text="Tryb pracy:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
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

        self.veh_frame = ttk.LabelFrame(settings_lf, text=" Model Pojazdów (Detect) ", padding=10)
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
        param_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(param_frame, text="Pewność (Confidence):").pack(anchor=tk.W)
        row_conf = ttk.Frame(param_frame)
        row_conf.pack(fill=tk.X, pady=2)
        ttk.Scale(row_conf, from_=0.1, to=0.9, variable=self.conf_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        lbl_conf = ttk.Label(row_conf, width=4)
        lbl_conf.pack(side=tk.RIGHT, padx=(5,0))
        self.conf_var.trace_add("write", lambda *a: lbl_conf.config(text=f"{self.conf_var.get():.2f}"))
        lbl_conf.config(text=f"{self.conf_var.get():.2f}")

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
            text="ZATWIERDŹ KROK AUTOANOTACJI",
            command=self._approve_annotation_stage,
            state=tk.DISABLED
        )
        self.approve_btn.pack(fill=tk.X)

        # Podpinanie systemu pomocy pod lokalną konsolę
        HELP.bind_help(self.input_dir_title_lbl, "tab1_input")
        HELP.bind_help(row_in, "tab1_input")
        HELP.bind_help(self.output_dir_title_lbl, "tab1_output")
        HELP.bind_help(row_out, "tab1_output")
        HELP.bind_help(self.run_title_lbl, "tab1_start")
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
        HELP.bind_help(self.manual_stage_section, "tab1_stage")
        HELP.bind_help(self.manual_stage_title_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_help_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_path_title_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_path_entry, "tab1_stage")
        HELP.bind_help(self.manual_stage_status_lbl, "tab1_stage")
        HELP.bind_help(self.manual_stage_use_btn, "tab1_stage_use")
        HELP.bind_help(self.manual_stage_add_btn, "tab1_stage_add")
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

        if hasattr(self, "vehicle_combo"):
            try:
                self.vehicle_combo.config(
                    state="readonly" if self._vehicle_model_controls_enabled(mode) else "disabled"
                )
            except Exception:
                pass

        self._on_vehicle_model_change()
        self._set_plate_model_controls_state(self._plate_model_controls_enabled(mode))

    def _set_progress_counters(self, successful: int, current: int, total: int):
        try:
            self.progress_counts_var.set(
                f"udane/przer./całość: {int(successful)}/{int(current)}/{int(total)}"
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
            self.vehicle_combo['values'] = v_keys + ["Custom"]
            if not self.vehicle_model_var.get() and v_keys:
                preferred_vehicle = "yolo11s" if "yolo11s" in v_keys else v_keys[0]
                self.vehicle_model_var.set(preferred_vehicle)

        if hasattr(self, "character_combo"):
            self._refresh_character_model_choices()

    def _on_vehicle_model_change(self, event=None):
        if self.vehicle_model_var.get() == "Custom" and str(self.vehicle_combo.cget("state")) != "disabled":
            self.veh_custom_row.pack(fill=tk.X, pady=(5,0))
        else:
            self.veh_custom_row.pack_forget()

    def _set_plate_model_controls_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"

        for widget in (
            getattr(self, "plate_path_entry", None),
            getattr(self, "plate_browse_btn", None),
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

    # Własne modele wybieramy domyślnie z katalogu modeli.
    def _select_vehicle_custom(self):
        initial_dir = CONFIG.get_trained_models_dir("vehicle")
        if not initial_dir.exists():
            initial_dir = CONFIG.DIR_6_MODELS
        p = filedialog.askopenfilename(initialdir=str(Path(initial_dir).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p: self.vehicle_custom_var.set(p)

    def _select_plate_custom(self):
        initial_dir = CONFIG.get_trained_models_dir("plate")
        if not initial_dir.exists():
            initial_dir = CONFIG.DIR_6_MODELS
        p = filedialog.askopenfilename(initialdir=str(Path(initial_dir).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p: self.plate_custom_var.set(p)

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
        try:
            path = Path(path_like).resolve()
            workspace = Path(CONFIG.WORKSPACE_DIR).resolve()
            rel = path.relative_to(workspace)
            return str(Path("Workspace") / rel)
        except Exception:
            try:
                return str(Path(path_like))
            except Exception:
                return str(path_like)

    def _annotation_run_manifest_path(self, run_dir: Path) -> Path:
        return Path(run_dir) / "run_manifest.json"

    def _write_annotation_run_manifest(self, run_dir: Path, input_dir: Path):
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
        try:
            run_dir = Path(run_dir)
        except Exception:
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

        try:
            candidate = Path(candidate)
        except Exception:
            return False

        if not candidate.exists() or not candidate.is_dir():
            return False

        return self._update_annotation_run_manifest(
            candidate,
            **self._collect_preview_resume_manifest_fields(),
        )

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
        try:
            root = Path(base_dir or self.output_dir_var.get().strip() or CONFIG.get_auto_annotations_dir("plate"))
        except Exception:
            root = Path(CONFIG.get_auto_annotations_dir("plate"))

        try:
            if not root.exists() or not root.is_dir():
                return None
        except Exception:
            return None

        candidates = []
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
            return None

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

        for root in roots:
            try:
                root = Path(root)
            except Exception:
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
        if manual_enabled:
            if not str(section.winfo_manager()):
                pack_kwargs = {"fill": tk.X}
                if separator is not None:
                    pack_kwargs["before"] = separator
                section.pack(**pack_kwargs)
        else:
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
                f"Możesz przelaczyc Z2 na {stage_rel} albo dolozyc nowa paczke zdjec." + updated_suffix
            )
            tone = "info"
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
                    "Stage zostal ustawiony jako nowa pula obrazow Z2. Kliknij Start, aby utworzyc kolejny run XML dla tych zdjec.",
                    "info",
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
                "Dla aktualnego stage nie ma jeszcze runu Z2. Kliknij Start, aby utworzyc nowy run dla tej puli obrazow.",
                "info",
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
                "Dolozono nowe zdjecia do aktywnego stage. Kliknij Start, aby utworzyc kolejny run XML dla tej rozszerzonej puli.",
                "info",
            )

    def _plate_dataset_output_preview(self, run_dir: Path | None = None) -> str:
        run_name = run_dir.name if isinstance(run_dir, Path) else "run_xxx"
        return str(self._get_plate_dataset_base_dir() / f"Plates_Z2_{run_name}_[DATA_I_CZAS]")

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
        raw_value = str(path_value or "").strip()
        if not raw_value:
            return None

        try:
            candidate = Path(raw_value)
        except Exception:
            return None

        try:
            if candidate.exists() and candidate.is_dir():
                return candidate
        except Exception:
            return None
        return None

    @staticmethod
    def _resolve_existing_dir(path_value) -> Path | None:
        raw_value = str(path_value or "").strip()
        if not raw_value:
            return None

        try:
            candidate = Path(raw_value)
        except Exception:
            return None

        try:
            if candidate.exists() and candidate.is_dir():
                return candidate
        except Exception:
            return None
        return None

    def _count_plate_annotations(self, annotations: list[ImageAnnotation] | None = None) -> tuple[int, int]:
        images_with_plates = 0
        total_plates = 0

        for ann in list(annotations if annotations is not None else (self.current_annotations or [])):
            plate_count = len(self._get_plate_detections(ann))
            if plate_count > 0:
                images_with_plates += 1
                total_plates += plate_count

        return images_with_plates, total_plates

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
            annotations = self._parse_cvat_preview_annotations(xml_path)
        except Exception:
            return 0, 0

        return self._count_plate_annotations(annotations)

    def _refresh_step2_action_states(self):
        dataset_run_dir = self._resolve_existing_run_dir(self.plate_dataset_run_var.get())
        if dataset_run_dir is None:
            dataset_run_dir = self._resolve_existing_run_dir(getattr(self, "current_annotation_run_dir", None))
        if dataset_run_dir is None:
            dataset_run_dir = self._resolve_existing_run_dir(getattr(self, "last_staging_run_dir", None))

        dataset_images_dir = self._resolve_existing_dir(self.plate_dataset_images_var.get())
        if dataset_images_dir is None:
            dataset_images_dir = self._resolve_existing_dir(self.input_dir_var.get())

        dataset_xml_exists = bool(dataset_run_dir and (dataset_run_dir / "annotations.xml").exists())
        _dataset_images_with_plates, dataset_total_plates = self._get_run_plate_annotation_counts(dataset_run_dir)
        manual_route = bool(self._manual_xml_template_enabled())
        dataset_ready = bool(dataset_xml_exists and dataset_images_dir is not None)
        if manual_route:
            dataset_ready = bool(dataset_ready and dataset_total_plates > 0)
        if self.is_processing:
            dataset_ready = False

        try:
            self.export_plate_dataset_btn.configure(state=(tk.NORMAL if dataset_ready else tk.DISABLED))
        except Exception:
            pass

        if manual_route and dataset_xml_exists and dataset_images_dir is not None and dataset_total_plates <= 0:
            self._set_plate_export_status(
                "Run recznej anotacji istnieje, ale nie ma jeszcze zapisanej ani jednej tablicy. "
                "Dodaj i zapisz co najmniej jeden polygon 'plate', aby odblokowac eksport datasetu YOLO Pose.",
                "warning",
            )

        approval_run_dir = None
        project_active = False
        current_step = 0
        try:
            from ..campaign_manager import CAMPAIGN

            project_active = bool(CAMPAIGN.get_active_project_name())
            current_step = int(CAMPAIGN.get_current_step() or 0)
            approval_run_dir = self._resolve_existing_run_dir(CAMPAIGN.get_step2_staging_run())
        except Exception:
            project_active = False
            current_step = 0

        approval_xml_exists = bool(approval_run_dir and (approval_run_dir / "annotations.xml").exists())
        _approval_images_with_plates, approval_total_plates = self._get_run_plate_annotation_counts(approval_run_dir)
        approve_ready = bool(project_active and current_step == 2 and approval_xml_exists and not self.is_processing)
        if manual_route:
            approve_ready = bool(approve_ready and approval_total_plates > 0)

        try:
            self.approve_btn.config(state=(tk.NORMAL if approve_ready else tk.DISABLED))
        except Exception:
            pass

        approve_hint_text = ""
        approve_hint_tone = "muted"
        if project_active and current_step == 2 and manual_route and approval_xml_exists:
            if approval_total_plates > 0:
                approve_hint_text = (
                    f"Gotowe do zamkniecia E2. Zapisanych tablic: {approval_total_plates}. "
                    "Mozesz teraz wyeksportowac dataset YOLO Pose albo od razu zatwierdzic ten run."
                )
                approve_hint_tone = "success"
            else:
                approve_hint_text = (
                    "Aby odblokowac zatwierdzenie E2, zapisz co najmniej jedna tablice 'plate'. "
                    "Ten sam warunek odblokowuje tez eksport datasetu YOLO Pose."
                )
                approve_hint_tone = "warning"
        elif project_active and current_step == 2 and approval_xml_exists:
            approve_hint_text = "Run Z2 jest gotowy do zatwierdzenia w E2."
            approve_hint_tone = "info"

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
                "Utworzono run do ręcznej anotacji. Wybierz obraz w podglądzie po prawej i użyj "
                "'Nowy polygon 4 pkt (D)', aby dorysować tablice. Po zapisaniu zmian możesz niżej "
                "wyeksportować dataset YOLO Pose do [Z4]. Ręczne polygony są zapisywane w XML "
                "z etykietą 'plate'."
            )

        if total_plates <= 0:
            return (
                "Run został zapisany, ale nie wykryto tablic gotowych do dalszego przepływu. "
                "Możesz przejrzeć wyniki w podglądzie albo uruchomić autoanotację ponownie z innymi ustawieniami."
            )

        return (
            "Co dalej: możesz od razu przejść do [Z3]/[PZ1], aby wyodrębnić i rektyfikować tablice, "
            "a następnie kontynuować pracę nad znakami. "
            "Jeśli chcesz trenować model tablic, możesz też zostać w [Z2] i niżej wyeksportować dataset YOLO Pose do [Z4]."
        )

    def _load_plate_dataset_context_from_run(self, run_dir: Path, force_images_update: bool = False):
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
            candidate = Path(run_value)
            if candidate.exists() and candidate.is_dir():
                run_dir = candidate

        project_active = False
        if run_dir is None:
            try:
                from ..campaign_manager import CAMPAIGN

                project_active = bool(CAMPAIGN.get_active_project_name())
                if project_active:
                    step2_staging = str(CAMPAIGN.get_step2_staging_run() or "").strip()
                    if step2_staging:
                        candidate = Path(step2_staging)
                        if (
                            candidate.exists()
                            and candidate.is_dir()
                            and self._annotation_run_matches_input(candidate, current_input_dir)
                        ):
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
            candidate = Path(self.last_staging_run_dir)
            if (
                candidate.exists()
                and candidate.is_dir()
                and (current_input_dir is None or self._annotation_run_matches_input(candidate, current_input_dir))
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
                        "info"
                    )
                else:
                    self._set_plate_export_status(
                        "Wybrano run Z2, ale trzeba jeszcze wskazać folder źródłowych obrazów dla tego runu.",
                        "warning"
                    )
            else:
                self._set_plate_export_status(
                    "Wybrany folder run nie zawiera pliku annotations.xml.",
                    "error"
                )
            self._refresh_manual_plate_stage_ui()
            self._refresh_step2_action_states()
            return

        if current_input_dir is not None:
            self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
            self._set_plate_export_status(
                "Dla aktualnego folderu obrazow nie ma jeszcze runu Z2. Kliknij Start, aby utworzyc nowy run dla tej puli albo wskaz run recznie.",
                "muted"
            )
            self._refresh_manual_plate_stage_ui()
            self._refresh_step2_action_states()
            return

        self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
        self._set_plate_export_status(
            "Brak runu Z2. Najpierw uruchom Start, aby utworzyć nowy run autoanotacji, albo wskaż istniejący folder run ręcznie.",
            "muted"
        )
        self._refresh_manual_plate_stage_ui()
        self._refresh_step2_action_states()

    def _select_plate_dataset_run_dir(self):
        initialdir = self.plate_dataset_run_var.get().strip()
        if not initialdir:
            try:
                from ..campaign_manager import CAMPAIGN

                if CAMPAIGN.get_active_project_name():
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

        run_dir = Path(path)
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
            return messagebox.showerror("Brak runu", "Wskaz folder run Z2 zawierajacy annotations.xml.")
        if not images_dir_value:
            return messagebox.showerror("Brak obrazow", "Wskaz folder obrazow, na ktorych powstal wybrany run.")

        run_dir = Path(run_dir_value)
        images_dir = Path(images_dir_value)
        xml_path = run_dir / "annotations.xml"

        if not run_dir.exists() or not run_dir.is_dir():
            return messagebox.showerror("Bledny run", "Wybrany folder run nie istnieje.")
        if not xml_path.exists():
            return messagebox.showerror("Brak XML", "Wybrany folder run nie zawiera pliku annotations.xml.")
        if not images_dir.exists() or not images_dir.is_dir():
            return messagebox.showerror("Brak obrazow", "Wybrany folder obrazow nie istnieje.")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = self._get_plate_dataset_base_dir() / f"Plates_Z2_{run_dir.name}_{timestamp}"
        self.plate_dataset_out_var.set(str(out_dir))
        self.plate_export_progress_var.set(0.0)
        self.export_plate_dataset_btn.configure(state=tk.DISABLED)
        self._set_plate_export_status("Rozpoczynam eksport datasetu YOLO Pose...", "info")

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
                manual_stage_enabled = bool(run_manifest.get("manual_xml_template", False))
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
                    self.frame.after(
                        0,
                        lambda: messagebox.showerror("Bledny XML", msg)
                    )
                    self.frame.after(0, lambda: self._set_plate_export_status(msg, "error"))
                    return

                def prog(current, total, image_name):
                    pct = (current / total) * 100 if total > 0 else 0
                    self.frame.after(0, lambda: self.plate_export_progress_var.set(pct))
                    self.frame.after(
                        0,
                        lambda: self._set_plate_export_status(
                            f"Eksport datasetu: {current}/{total} obrazow... ({image_name})",
                            "info"
                        )
                    )

                ok, msg, _ = self.dataset_creator.create_dataset(images_dir, out_dir, ratios, prog)
                if not ok:
                    self.frame.after(0, lambda: messagebox.showerror("Blad eksportu", msg))
                    self.frame.after(0, lambda: self._set_plate_export_status(msg, "error"))
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
                            "Dataset YOLO Pose został utworzony poprawnie.\n\n"
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

                self.frame.after(0, finish_success)
            except Exception as e:
                logger.error(f"Blad eksportu datasetu tablic: {e}")
                self.frame.after(0, lambda err=str(e): messagebox.showerror("Krytyczny blad", err))
                self.frame.after(
                    0,
                    lambda err=str(e): self._set_plate_export_status(
                        f"Krytyczny blad eksportu: {err}",
                        "error"
                    )
                )
            finally:
                self.frame.after(0, self._refresh_step2_action_states)

        threading.Thread(target=worker, daemon=True).start()

    def _redirect_logs(self):
        if getattr(self, "_annotation_log_handlers_attached", False):
            return

        class TextHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget
            def emit(self, record):
                try:
                    if self.widget.winfo_exists():
                        msg = self.format(record)
                        self.widget.after(0, self._safe_insert, msg)
                except: pass
            def _safe_insert(self, msg):
                try:
                    if self.widget.winfo_exists():
                        self.widget.insert(tk.END, msg + "\n")
                        self.widget.see(tk.END)
                        self.widget.update_idletasks()
                except: pass
                 
        formatter = logging.Formatter('%(asctime)s | %(message)s', '%H:%M:%S')

        self._annotation_app_log_handler = TextHandler(self.log_text)
        self._annotation_app_log_handler.setFormatter(formatter)
        logger.addHandler(self._annotation_app_log_handler)

        try:
            self._annotation_ultralytics_log_handler = TextHandler(self.log_text)
            self._annotation_ultralytics_log_handler.setFormatter(formatter)
            self._annotation_ultralytics_logger = logging.getLogger("ultralytics")
            self._annotation_ultralytics_logger.addHandler(self._annotation_ultralytics_log_handler)
        except Exception:
            pass

        self._annotation_log_handlers_attached = True

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

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
            self.app.style_canvas_widget(
                self.left_settings_canvas,
                background=palette.get("panel", "#252526"),
                bordercolor=panel_border
            )
        except Exception:
            pass

        try:
            self.app.style_canvas_widget(
                self.right_settings_canvas,
                background=palette.get("panel", "#252526"),
                bordercolor=panel_border
            )
        except Exception:
            pass

        try:
            self._update_device_hint()
        except Exception:
            pass

        try:
            self.progress.configure(
                trough_color=palette.get("border", "#3c3c3c"),
                fill_color=palette.get("accent", "#0e639c"),
                bg=palette.get("panel", "#252526"),
            )
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

        for line in getattr(self, "_left_title_underlines", []):
            if not isinstance(line, dict):
                continue
            try:
                host = line.get("host")
                accent = line.get("accent")
                if host is not None:
                    host.configure(bg=palette.get("panel", "#252526"))
                if accent is not None:
                    accent.configure(bg=palette.get("success", palette.get("accent", "#0e639c")))
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
                self.btn_toggle_annotation_log.configure(text="Pokaż terminal")

    def _toggle_annotation_process_log(self):
        self._set_annotation_process_log_visibility(
            not getattr(self, "_annotation_log_visible", False)
        )

    def _validate_models(self):
        mode = self._normalize_mode_value()
        if self._mode_uses_vehicle(mode):
            if self.vehicle_model_var.get() == "Custom":
                p = self.vehicle_custom_var.get()
                if not p or not Path(p).exists(): raise ValueError("Nie znaleziono własnego modelu pojazdów!")
                if not validate_model_file(Path(p))[0]: raise ValueError("Model pojazdów jest uszkodzony!")
        
        if self._mode_uses_plate(mode):
            p = (self.plate_custom_var.get() or "").strip()
            if not p or not Path(p).exists(): raise ValueError("Wskaż wytrenowany model tablic (.pt)!")
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
        Przywraca neutralny stan zakładki Autoanotacji po wyjściu z projektu
        i czyści wszystkie artefakty poprzedniego projektu z UI.
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
            self._apply_free_mode_session_snapshot(restore_preview=True)
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
            bootstrap = self._get_campaign_auto_annotation_bootstrap(iteration_target)
            input_dir = Path(bootstrap.get("input_dir") or Path(raw_dir))
            manual_template = bool(bootstrap.get("manual_template", iteration_target == "plate"))
            plate_bootstrap_model = str(bootstrap.get("plate_model_path") or "").strip()
            restore_run_dir = bootstrap.get("restore_run_dir")

            restored_snapshot = self.apply_campaign_context(
                input_dir,
                Path(auto_out),
                manual_template=manual_template,
                mode_text="C: Pojazdy + tablice",
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

                self.mode_var.set("C: Pojazdy + tablice")
                self._on_mode_change()

                if restore_run_dir is not None:
                    self._restore_preview_from_annotation_run(restore_run_dir)
            return True
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic projektowego kontekstu Z2: {e}")
            return False

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
        btn = self._resolve_guidance_button(frame_attr)
        frame = self._resolve_guidance_frame(frame_attr)

        if frame is not None:
            try:
                self.app.pulse_frame(frame, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True)
            except Exception as e:
                logger.debug(f"Nie udało się pulsować ramki dla {frame_attr}: {e}")

        if btn is None:
            return

        try:
            self.app.pulse_button(btn, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True)
        except Exception as e:
            logger.debug(f"Nie udało się pulsować przycisku dla {frame_attr}: {e}")

    def apply_campaign_context(
        self,
        input_dir: Path,
        output_dir: Path,
        *,
        manual_template: bool = False,
        mode_text: str = "C: Pojazdy + tablice",
        restore_project_state: bool = True,
    ):
        self._campaign_project_restore_in_progress = True
        restored_snapshot = False
        try:
            self.input_dir_var.set(str(input_dir))
            self.output_dir_var.set(str(output_dir))
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
            restored_snapshot = self._apply_campaign_project_snapshot(restore_preview=True)

        if not restored_snapshot:
            self._restore_preview_from_session_run()

        try:
            self._apply_campaign_iteration_model_defaults()
        except Exception:
            pass

        self._refresh_step2_action_states()
        self._pulse_action_frame("start_btn_pulse_frame")
        return restored_snapshot

    def _manual_xml_template_enabled(self) -> bool:
        return bool(self.manual_xml_template_var.get())

    def _manual_vehicle_assist_enabled(self) -> bool:
        return self._manual_xml_template_enabled() and bool(self.manual_vehicle_assist_var.get())

    def _update_manual_xml_template_ui(self):
        manual_enabled = self._manual_xml_template_enabled()
        vehicle_assist_enabled = self._manual_vehicle_assist_enabled()
        self._refresh_detection_configuration_ui()

        if manual_enabled:
            if getattr(self, "manual_vehicle_assist_check", None) is not None and not str(self.manual_vehicle_assist_check.winfo_manager()):
                self.manual_vehicle_assist_check.pack(
                    anchor=tk.W,
                    pady=(0, 2),
                    padx=(18, 0),
                    after=self.manual_xml_template_check,
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
                    "Dotyczy tylko nowego runu po kliknieciu Start. Z2 uzyje modelu pojazdow, zapisze boxy aut do nowego XML i pozwoli przechodzic po nich klawiszem Spacja."
                )
                self.manual_xml_template_hint_var.set(
                    "Z2 pominie model tablic, ale przygotuje annotations.xml dla wszystkich obrazow z auto-boxami pojazdow. "
                    "Spacja kadruje i przelacza kolejne pojazdy, a recznie dodane tablice zapisuja sie z etykieta 'plate'. "
                    "Kazde ponowne uruchomienie tworzy nowy run_* i nie nadpisuje starszych XML-i; starsze runy zostaja na dysku."
                )
                if hasattr(self, "start_btn"):
                    self.start_btn.configure(text="UTWORZ XML + BOXY POJAZDOW")
                self._set_inline_label_state(self.manual_vehicle_assist_hint_lbl, tone="info", emphasis=False)
            else:
                self.manual_vehicle_assist_hint_var.set(
                    "Ten checkbox zadziala dopiero dla nowego runu po kliknieciu Start. Nie modyfikuje juz utworzonych XML-i."
                )
                self.manual_xml_template_hint_var.set(
                    "Z2 pominie YOLO dla tablic i przygotuje run z pustym annotations.xml dla wszystkich obrazow. "
                    "Potem dodasz polygony tablic recznie w podgladzie. Recznie dodane tablice zapisuja sie w XML z etykieta 'plate'. "
                    "Kazde ponowne uruchomienie tworzy nowy run_* i nie nadpisuje starszych XML-i; starsze runy zostaja na dysku."
                )
                if hasattr(self, "start_btn"):
                    self.start_btn.configure(text="UTWORZ XML DO ANOTACJI RECZNEJ")
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
            "Standardowy tryb Z2: uruchamia modele YOLO i zapisuje run autoanotacji tablic."
        )
        if hasattr(self, "start_btn"):
            self.start_btn.configure(text="STARTUJ AUTOANOTACJE")
        self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone="muted", emphasis=False)
        self._refresh_manual_plate_stage_ui()
        return

        if manual_enabled:
            self.manual_xml_template_hint_var.set(
                "Z2 pominie YOLO i przygotuje run z pustym annotations.xml dla wszystkich obrazów. "
                "Potem dodasz polygony tablic ręcznie w podglądzie. "
                "Ręcznie dodane tablice zapisują się w XML z etykietą 'plate'."
            )
            if hasattr(self, "start_btn"):
                self.start_btn.configure(text="UTWÓRZ XML DO ANOTACJI RĘCZNEJ")
            self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone="warning", emphasis=False)
        else:
            self.manual_xml_template_hint_var.set(
                "Standardowy tryb Z2: uruchamia modele YOLO i zapisuje run autoanotacji tablic."
            )
            if hasattr(self, "start_btn"):
                self.start_btn.configure(text="STARTUJ AUTOANOTACJĘ")
            self._set_inline_label_state(self.manual_xml_template_hint_lbl, tone="muted", emphasis=False)

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
                "Możesz go obserwować przyciskiem 'Pokaż terminal'.\n\n"
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

                success, msg = self.annotator.load_models()
            elif manual_vehicle_assist:
                self.annotator = VehicleAnnotator(v_p, conf, dev)
                success, msg = self.annotator.load_models()
            if not success: raise RuntimeError(f"Błąd silnika YOLO: {msg}")

            # Nowy run autoanotacji unieważnia poprzednie zatwierdzenie kroku 2.
            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name():
                    CAMPAIGN.reset_step2()
                    if 'campaign' in self.app.tabs:
                        self.app.tabs['campaign']._refresh_dashboard()
            except Exception as e:
                logger.debug(f"Nie udało się zresetować stanu Kroku 2: {e}")

            self._current_run_manual_template = manual_template
            self._current_run_manual_vehicle_assist = manual_vehicle_assist
            self.is_processing = True
            self.app.set_processing(True)
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
                "ROZPOCZĘTO PRZYGOTOWANIE XML DO RĘCZNEJ ANOTACJI TABLIC"
                if manual_template
                else "ROZPOCZĘTO AUTOANOTACJĘ OBRAZÓW (YOLO)"
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
                args=(Path(in_d), Path(self.output_dir_var.get()), manual_template, manual_vehicle_assist),
                daemon=True
            ).start()
            
        except Exception as e:
            logger.error(f"Nie można wystartować: {e}")
            messagebox.showerror("Błąd Startu", str(e))

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
        
        try:
            total_images = count_images_in_directory(in_dir)
            if total_images == 0:
                self.frame.after(0, lambda: self._finish(False, "Brak obrazów we wskazanym folderze wejściowym."))
                return
                
            self.start_time = datetime.datetime.now()
            
            def prog_cb(current, total, filename, successful=0):
                if not self.is_processing: raise KeyboardInterrupt("Anulowano")
                pct = (current / total) * 100 if total > 0 else 0
                self.frame.after(0, lambda: self._update_progress(pct, current, total, filename, successful))
            
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
                message = "Przetwarzanie przerwane przez użytkownika."
                success = False
                return

            self.current_annotations = annotations
            self.current_input_dir = in_dir

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
                logger.debug(f"Nie udało się zapisać manifestu runu Z2: {e}")

            elapsed = format_duration((datetime.datetime.now() - self.start_time).total_seconds())

            # Zachowaj ścieżkę do ostatniego runu w stagingu.
            self.last_staging_run_dir = run_dir
            self.frame.after(0, self._populate_preview_list)
            self.frame.after(0, lambda run_dir=run_dir: self._load_plate_dataset_context_from_run(run_dir, force_images_update=True))
            self.frame.after(0, self._refresh_plate_dataset_export_sources)
            self.frame.after(0, self._queue_free_mode_session_save)
            self.frame.after(0, self.flush_free_mode_session_state)

            message = (
                f"Przygotowano XML do ręcznej anotacji: {run_dir.name} (w czasie {elapsed})"
                if manual_template
                else f"Zakończono! Zapisano do: {run_dir.name} (w czasie {elapsed})"
            )
            logger.info(f"✅ {message}")
            success = True
            
        except KeyboardInterrupt:
            message = "Anulowano przez użytkownika."
            success = False
        except Exception as e:
            message = f"Krytyczny błąd: {e}"
            success = False
        finally:
            self.frame.after(0, lambda: self._finish(success, message))

    # ==========================================================
    # LOGIKA PRZEGLĄDARKI (CANVAS)
    # ==========================================================
    def _populate_preview_list(self):
        self.preview_listbox.delete(0, tk.END)
        palette = getattr(self.app, "palette", {})
        ok_color = palette.get("success", "#27ae60")
        err_color = palette.get("error", "#c0392b")
        for idx, ann in enumerate(self.current_annotations):
            icon = "🟢" if ann.is_successful else "🔴"
            self.preview_listbox.insert(tk.END, f"{icon} {ann.filename}")
            
            # Bezpieczne dla Pythona 3.12
            if ann.is_successful:
                self.preview_listbox.itemconfig('end', foreground=ok_color)
            else:
                self.preview_listbox.itemconfig('end', foreground=err_color)
                
        if self.current_annotations:
            self.preview_listbox.selection_set(0)
            self._on_preview_select(None)

    def _on_preview_select(self, event):
        sel = self.preview_listbox.curselection()
        if not sel or not self.current_annotations: return
            
        idx = sel[0]
        ann = self.current_annotations[idx]
        img_path = self.current_input_dir / ann.filename
        
        if not img_path.exists():
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

    def _preview_list_item_text(self, ann) -> str:
        dirty_prefix = "*" if ann.filename in self._preview_dirty_images else " "
        status_text = "OK" if ann.is_successful else "--"
        return f"{dirty_prefix} [{status_text}] {ann.filename}"

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

    def _clear_preview_editor_state(self, clear_dirty: bool = True):
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
        if clear_dirty:
            self._preview_dirty_images.clear()
        self.current_annotation_run_dir = None
        self.current_annotation_xml_path = None
        self._update_preview_edit_status()

    def _refresh_preview_list(self, preserve_selection: bool = True, render_current: bool = False):
        selected_index = self.current_preview_index if preserve_selection else None
        if selected_index is None and self.current_annotations:
            selected_index = 0

        if selected_index is not None and self.current_annotations:
            selected_index = max(0, min(int(selected_index), len(self.current_annotations) - 1))

        self.preview_listbox.delete(0, tk.END)
        palette = getattr(self.app, "palette", {})
        ok_color = palette.get("success", "#27ae60")
        err_color = palette.get("error", "#c0392b")
        warn_color = palette.get("warning", "#f39c12")

        for idx, ann in enumerate(self.current_annotations):
            self.preview_listbox.insert(tk.END, self._preview_list_item_text(ann))
            try:
                item_color = warn_color if ann.filename in self._preview_dirty_images else (ok_color if ann.is_successful else err_color)
                self.preview_listbox.itemconfig(idx, foreground=item_color)
            except Exception:
                pass

        self.preview_listbox.selection_clear(0, tk.END)
        if selected_index is not None and self.current_annotations:
            self.preview_listbox.selection_set(selected_index)
            self.preview_listbox.activate(selected_index)
            self.preview_listbox.see(selected_index)
            self.current_preview_index = selected_index
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
        self._refresh_preview_list(preserve_selection=False, render_current=True)

    def _select_preview_index(self, idx: int):
        if not self.current_annotations:
            return
        safe_idx = max(0, min(int(idx), len(self.current_annotations) - 1))
        previous_idx = self.current_preview_index
        self.preview_listbox.selection_clear(0, tk.END)
        self.preview_listbox.selection_set(safe_idx)
        self.preview_listbox.activate(safe_idx)
        self.preview_listbox.see(safe_idx)
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
        current = 0 if self.current_preview_index is None else int(self.current_preview_index)
        self._select_preview_index(current + int(step))
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
            return max(58.0, float(font_obj.measure(str(token_text))) + 46.0)
        return max(32.0, float(font_obj.measure(str(token_text))) + 18.0)

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
        font_obj = self._get_preview_legend_font(10, "bold")
        width = self._measure_preview_legend_token("key", text, font_obj)
        height = 28.0
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
        font_obj = self._get_preview_legend_font(8, "bold")
        width = self._measure_preview_legend_token("mouse", text, font_obj)
        height = 28.0
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
        body_top = y + 4
        body_right = body_left + 16
        body_bottom = y + 24
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
            {"tokens": [("key", "Q"), ("key", "E")], "connector": "/", "label": "zmien zdjecie", "accent": "#2f80ed"},
            {"tokens": [("key", "A")], "connector": "", "label": "zmien tablice", "accent": "#14b8a6"},
            {"tokens": [("key", "Spacja")], "connector": "", "label": "kadruj pojazd", "accent": "#16a34a"},
            {"tokens": [("key", "R")], "connector": "", "label": "kadruj tablice", "accent": "#f59e0b"},
            {"tokens": [("key", "F")], "connector": "", "label": "dopasuj widok", "accent": "#64748b"},
            {"tokens": [("key", "W"), ("mouse", "LPM")], "connector": "+", "label": "przesun rog", "accent": "#fb923c"},
            {"tokens": [("key", "D")], "connector": "", "label": "nowa tablica", "accent": "#22c55e"},
            {"tokens": [("key", "S")], "connector": "", "label": "zaznacz tablice", "accent": "#ef4444"},
            {"tokens": [("mouse", "PPM")], "connector": "", "label": "usun tablice", "accent": "#dc2626"},
            {"tokens": [("key", "Ctrl"), ("key", "S")], "connector": "+", "label": "zapisz zmiany", "accent": "#0ea5e9"},
            {"tokens": [("key", "Enter"), ("key", "Esc")], "connector": "/", "label": "pelny ekran", "accent": "#94a3b8"},
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

        width = max(520.0, float(canvas.winfo_width() or 0.0))
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

        context = self._get_preview_legend_context()
        x = 14.0
        y = 10.0
        badge_gap = 8.0
        badge_font = self._get_preview_legend_font(10, "bold")
        badge_specs = [
            (f"Plik: {context['filename']}", legend_theme["badge_file_fill"], legend_theme["badge_file_outline"]),
            (context["image_text"], legend_theme["badge_image_fill"], legend_theme["badge_image_outline"]),
            (context["vehicle_text"], legend_theme["badge_image_fill"], legend_theme["badge_image_outline"]),
            (context["plate_text"], legend_theme["badge_plate_fill"], legend_theme["badge_plate_outline"]),
        ]
        badge_height = 0.0
        badge_bottom = y
        for badge_text, badge_fill, badge_outline in badge_specs:
            estimated_badge_width = max(40.0, float(badge_font.measure(str(badge_text))) + 24.0)
            if x > 14.0 and (x + estimated_badge_width) > (width - 14.0):
                x = 14.0
                y = badge_bottom + 8.0
            badge_width, current_badge_height = self._draw_preview_legend_badge(
                canvas,
                x,
                y,
                badge_text,
                fill=badge_fill,
                outline=badge_outline,
                text_fill=self._get_preview_legend_text_color(badge_fill),
            )
            badge_height = max(badge_height, current_badge_height)
            badge_bottom = max(badge_bottom, y + current_badge_height)
            x += badge_width + badge_gap

        entries = self._build_preview_legend_entries()
        x = 14.0
        y = badge_bottom + 12.0
        token_gap = 16.0
        entry_gap_x = 10.0
        entry_gap_y = 10.0
        entry_pad_x = 10.0
        entry_pad_top = 7.0
        entry_pad_bottom = 6.0
        label_gap_y = 6.0
        label_font = self._get_preview_legend_font(9, "bold")
        label_height = float(label_font.metrics("linespace"))
        token_row_height = 28.0
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
                token_font = self._get_preview_legend_font(8 if token_kind == "mouse" else 10, "bold")
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
                            font=self._get_preview_legend_font(9, "bold"),
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

        total_height = max(74.0, bottom + 12.0)
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
            ("<Control-s>", self._on_preview_save_shortcut),
            ("<Control-S>", self._on_preview_save_shortcut),
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

    def _on_preview_save_shortcut(self, event=None):
        if not self._preview_shortcuts_enabled(event, allow_when_fullscreen=True):
            return None
        self._save_preview_edits()
        return "break"

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
                "Przywrocono poprzedni kadr. R ponownie zbliza aktywny polygon."
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
            status_message="Widok zostal dopasowany do aktywnego polygonu. R wraca do poprzedniego kadru, A przelacza tablice.",
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
            self._update_preview_edit_status("Na tym obrazie nie ma polygonow tablicy do przelaczania klawiszem A.")
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
                "A przelacza kolejne polygony, R wraca do poprzedniego kadru."
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
            self._update_preview_edit_status("Na tym obrazie nie ma boxow pojazdow do przelaczania klawiszem Spacja.")
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
                "Spacja przelacza kolejne auta, D dodaje tablice, R kadruje aktywna tablice."
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
            if status_label is not None and not str(status_label.winfo_manager()):
                status_label.pack(fill=tk.X, pady=(8, 0), after=canvas_frame)
        except Exception:
            pass
        try:
            if log_tools is not None and not str(log_tools.winfo_manager()):
                log_tools.pack(fill=tk.X, padx=5, pady=(8, 0))
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
            self._update_preview_edit_status("Pelny ekran jest dostepny po zaladowaniu obrazu podgladu.")
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
            if self._pane_has_child(self.preview_pane, self.preview_list_lf):
                self.preview_pane.forget(self.preview_list_lf)

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
            if not self._pane_has_child(self.main_pane, self.main_right_frame):
                self.main_pane.add(self.main_right_frame, weight=1)
            if not self._pane_has_child(self.preview_pane, self.preview_list_lf):
                self.preview_pane.insert(0, self.preview_list_lf, weight=1)

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

        plates = self._get_plate_detections(ann)
        if not self._preview_delete_mode and not plates:
            self._update_preview_edit_status("Na tym obrazie nie ma polygonu tablicy do usuniecia.")
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

    def _update_preview_toolbar_state(self):
        total = len(self.current_annotations)
        has_selection = self.current_preview_index is not None and total > 0
        has_image = has_selection and getattr(self.preview_canvas, "original_image", None) is not None
        can_go_prev = has_selection and int(self.current_preview_index) > 0
        can_go_next = has_selection and int(self.current_preview_index) < (total - 1)
        has_dirty = bool(self._preview_dirty_images)

        try:
            self.preview_prev_btn.configure(state=(tk.NORMAL if can_go_prev else tk.DISABLED))
            self.preview_next_btn.configure(state=(tk.NORMAL if can_go_next else tk.DISABLED))
            self.preview_fit_btn.configure(state=(tk.NORMAL if has_image else tk.DISABLED))
            self.preview_draw_btn.configure(state=(tk.NORMAL if has_image else tk.DISABLED))
            self.preview_draw_btn.configure(text=("Anuluj rysowanie (D)" if self._preview_draw_mode else "Nowy polygon 4 pkt (D)"))
            if hasattr(self, "preview_fullscreen_btn"):
                self.preview_fullscreen_btn.configure(
                    state=(tk.NORMAL if has_image else tk.DISABLED),
                    text=("Wyjdz z pelnego ekranu (Esc)" if self._preview_fullscreen_active else "Pelny ekran (Enter)")
                )
            self.preview_save_btn.configure(state=(tk.NORMAL if has_dirty else tk.DISABLED))
        except Exception:
            pass

        try:
            self.preview_fullscreen_hint_var.set("")
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

    def _update_preview_edit_status(self, extra_message: str | None = None):
        if extra_message:
            self.preview_edit_status_var.set(extra_message)
            self._update_preview_toolbar_state()
            self._refresh_preview_debug_status()
            self._refresh_preview_controls_legend()
            return

        ann = self._get_preview_annotation()
        if ann is None:
            self.preview_edit_status_var.set("Po zakończeniu autoanotacji tutaj poprawisz rogi tablic.")
            self._update_preview_toolbar_state()
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
                    f"{ann.filename} | tryb usuwania aktywny{dirty_note}. Kliknij wewnatrz polygonu, aby zaznaczyc tablice do usuniecia. "
                    "PPM usuwa zaznaczony polygon, S anuluje tryb."
                )
        elif not plates:
            self.preview_edit_status_var.set(
                f"{ann.filename} | brak wykrytej tablicy{dirty_note}. "
                f"Uzyj 'Nowy polygon 4 pkt (D)', aby dodac reczna anotacje.{vehicle_hint}"
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
                "W wcisniete: mozesz przeciagac rogi."
                if self._preview_corner_drag_modifier_down
                else "Przytrzymaj W i przeciagnij rog, aby poprawic geometrie."
            )
            fullscreen_hint = (
                "Esc wychodzi z pelnego ekranu."
                if self._preview_fullscreen_active
                else "Enter wlacza pelny ekran."
            )
            self.preview_edit_status_var.set(
                f"{ann.filename} | tablica {plate_no}/{len(plates)}{dirty_note}. "
                f"Kliknij polygon, aby go wybrac. {drag_hint} "
                f"Q/E przelaczaja zdjecia, A przelacza tablice, Spacja kadruje pojazdy, R kadruje aktywny polygon, F dopasowuje widok, D rysuje nowy polygon, S uzbraja usuwanie, Ctrl+S zapisuje poprawki. {fullscreen_hint}{vehicle_hint}"
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
        img_path = self.current_input_dir / ann.filename if self.current_input_dir else None

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

    def _draw_annotation_preview_overlay(self, canvas: ZoomableCanvas):
        ann = self._get_preview_annotation()
        if ann is None or canvas.original_image is None:
            return

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
            x1, y1, x2, y2 = det.bbox
            cx1, cy1 = canvas.image_to_canvas_coords(x1, y1)
            cx2, cy2 = canvas.image_to_canvas_coords(x2, y2)
            is_selected_vehicle = selected_vehicle_idx == vehicle_idx
            vehicle_outline = active_color if is_selected_vehicle else vehicle_color
            vehicle_width = 3 if is_selected_vehicle else 2
            vehicle_dash = None if is_selected_vehicle else (6, 4)
            if is_selected_vehicle:
                canvas.create_rectangle(
                    cx1,
                    cy1,
                    cx2,
                    cy2,
                    outline="",
                    fill=vehicle_color,
                    stipple="gray12",
                    width=0,
                    tags=("preview_overlay",)
                )
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

        self._draw_preview_bottom_hint(canvas)
        if not bool(getattr(self, "_preview_fullscreen_active", False)):
            self._draw_preview_enter_fullscreen_hint(canvas)

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
            hint_text = "Pelny ekran podgladu wlaczysz klawiszem Enter."
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
                "A zmienia tablice, Spacja pojazdy, R kadr, F dopasuj, D nowa, S usun, Ctrl+S zapisz."
            )

        fullscreen_hint = (
            " Esc wychodzi z pelnego ekranu."
            if self._preview_fullscreen_active
            else " Enter wlacza pelny ekran."
        )
        return f"{base}{fullscreen_hint}{vehicle_suffix}"

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
                self._mark_preview_image_dirty(ann, refresh_list=True)

        try:
            self.preview_canvas.grab_release()
        except Exception:
            pass
        self._preview_drag_state = None
        self._preview_pending_vertex_hit = None
        self._refresh_preview_canvas()
        self._update_preview_edit_status()
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
            or "Zmiana zostala wprowadzona w podgladzie, ale nie udalo sie od razu zapisac annotations.xml. Uzyj Ctrl+S."
        )
        return False

    def _delete_preview_polygon(self, plate_idx: int, autosave: bool = True):
        ann = self._get_preview_annotation()
        if ann is None:
            return False

        plate_detections = self._get_plate_detections(ann)
        if plate_idx < 0 or plate_idx >= len(plate_detections):
            return False

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
            candidates.append(Path(self.current_annotation_xml_path))
        if getattr(self, "current_annotation_run_dir", None):
            candidates.append(Path(self.current_annotation_run_dir) / "annotations.xml")
        if getattr(self, "last_staging_run_dir", None):
            candidates.append(Path(self.last_staging_run_dir) / "annotations.xml")

        run_dir_value = str(self.plate_dataset_run_var.get() or "").strip()
        if run_dir_value:
            candidates.append(Path(run_dir_value) / "annotations.xml")

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
            self._update_preview_edit_status("Brak niezapisanych poprawek w podgladzie.")
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
                "Usuwanie polygonu jest dwuetapowe: nacisnij S, kliknij wewnatrz polygonu, a potem PPM usunie zaznaczona tablice."
            )
            return "break"

        target_idx = self._preview_delete_candidate_idx
        if target_idx is None:
            self._update_preview_edit_status(
                "Tryb usuwania jest aktywny. Kliknij najpierw wewnatrz polygonu, aby zaznaczyc go na czerwono."
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
                    f"Polygon {int(polygon_hit) + 1}/{len(self._get_plate_detections(ann))} jest zaznaczony do usuniecia. Kliknij PPM, aby go usunac."
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
                "Tryb usuwania aktywny: kliknij wewnatrz polygonu, aby zaznaczyc tablice do usuniecia."
            )
            return True

        if self._preview_modifier_active():
            drag_target = self._resolve_preview_drag_target(canvas_x, canvas_y)
            if drag_target is not None:
                plate_idx, vertex_idx, target_mode = drag_target
                self._set_selected_plate_index_for_ann(ann, plate_idx)
                self._preview_pending_vertex_hit = {
                    "plate_idx": int(plate_idx),
                    "vertex_idx": int(vertex_idx),
                    "anchor_canvas_x": float(canvas_x),
                    "anchor_canvas_y": float(canvas_y),
                }
                self._push_preview_debug_event(
                    "press-target",
                    (
                        f"{self._format_preview_debug_vertex_ref(plate_idx, vertex_idx)} "
                        f"mode={target_mode} canvas=({float(canvas_x):.1f},{float(canvas_y):.1f}) "
                        f"{self._describe_preview_hit_debug(canvas_x, canvas_y, event)}"
                    )
                )
                self._refresh_preview_canvas()
                if target_mode == "handle":
                    self._update_preview_edit_status(
                        "Tryb W aktywny: punkt wybrany. Przeciagnij mysz, aby rozpoczac edycje."
                    )
                else:
                    self._update_preview_edit_status(
                        "Tryb W aktywny: punkt wybrany. Przeciagnij mysz, aby rozpoczac edycje."
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
                "Aby przesuwac rogi tablicy, przytrzymaj W i przeciagaj uchwyt mysza."
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
                "Tryb W aktywny: obraz jest zablokowany. Kliknij bezposrednio uchwyt rogu, aby przesunac wierzcholek."
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
            if motion_canvas_dist < 3.0:
                self._push_preview_debug_event("drag-threshold", f"d={motion_canvas_dist:.2f}", refresh_only=True)
                return True
            drag_state["drag_started"] = True
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

        self._mark_preview_image_dirty(ann, refresh_list=False)
        self._refresh_preview_canvas()
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

        idx = int(sel[0])
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
        self.progress.configure(value=pct)
        self._set_progress_counters(successful, current, total)
        self._set_status_label_state(
            f"Przetwarzanie {current}/{total} ({int(pct)}%)",
            "info"
        )

    def _finish(self, success, msg):
        self.is_processing = False
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
            self._set_status_label_state("Zakończono pomyślnie!", "success")
            next_steps = self._build_annotation_success_next_steps()
            self._set_post_annotation_hint(next_steps, "success")

            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name() and CAMPAIGN.get_current_step() == 2:
                    # Etap został wygenerowany, ale wymaga jeszcze ręcznego zatwierdzenia.
                    staging_run = getattr(self, "last_staging_run_dir", None)
                    if staging_run is not None:
                        CAMPAIGN.set_step2_generated(str(staging_run))

                    # odblokuj przycisk ręcznego zatwierdzania
                    self.approve_btn.config(state=tk.NORMAL)
                    self._pulse_action_frame("approve_btn_pulse_frame")

                    if 'campaign' in self.app.tabs:
                        self.app.tabs['campaign']._refresh_dashboard()

            except Exception as e:
                logger.debug(f"Nie udało się zaktualizować stanu kroku 2: {e}")

            self._refresh_step2_action_states()
            messagebox.showinfo("Koniec", f"{msg}\n\n{next_steps}")
        else:
            self._set_status_label_state("Przerwano / Błąd", "error")
            self._set_post_annotation_hint("")
            self._refresh_step2_action_states()
            messagebox.showerror("Zatrzymano", msg)

    def _approve_annotation_stage(self):
        """
        Zatwierdza staging autoanotacji i przenosi go do katalogu docelowego projektu.
        """
        try:
            from ..campaign_manager import CAMPAIGN
            import shutil

            if not self._ensure_preview_edits_saved("zatwierdzenie kroku autoanotacji"):
                return

            if not CAMPAIGN.get_active_project_name():
                return messagebox.showwarning("Brak projektu", "Nie ma aktywnego projektu.")

            staging_run_str = CAMPAIGN.get_step2_staging_run()
            if not staging_run_str:
                return messagebox.showwarning("Brak danych", "Nie znaleziono wygenerowanego staging runu do zatwierdzenia.")

            staging_run = Path(staging_run_str)
            if not staging_run.exists():
                return messagebox.showerror("Brak folderu", f"Folder stagingu nie istnieje:\n{staging_run}")

            final_auto_dir = CAMPAIGN.get_dir("auto_ann")
            if final_auto_dir is None:
                return messagebox.showerror("Błąd", "Nie udało się ustalić katalogu docelowego autoanotacji dla projektu.")

            final_auto_dir = Path(final_auto_dir)
            final_auto_dir.mkdir(parents=True, exist_ok=True)

            target_dir = final_auto_dir / staging_run.name

            # jeśli ktoś zatwierdza drugi raz, najpierw czyścimy stare
            if target_dir.exists():
                shutil.rmtree(target_dir)

            shutil.move(str(staging_run), str(target_dir))
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

            next_step_label = "E4 / trening tablic" if next_step == 4 else "E3 / tor znaków"
            self.app.update_status(
                "Zatwierdzono krok autoanotacji. Wyniki przeniesiono z katalogu stagingu do "
                f"2_auto_annotations projektu. Kolejny krok: {next_step_label}.",
                "info"
            )
            # po zatwierdzeniu wracamy do Wizarda
            try:
                self.app.select_tab("campaign")
                self.app.update_campaign_tab_access()
            except Exception as e:
                logger.debug(f"Nie udało się wrócić do zakładki Wizarda: {e}")

            messagebox.showinfo("Sukces", f"Krok autoanotacji został zatwierdzony.\n\nWyniki przeniesiono do:\n{target_dir}")

        except Exception as e:
            messagebox.showerror("Błąd zatwierdzania", str(e))

    def _stop_annotation(self):
        self.is_processing = False
        if self.annotator and hasattr(self.annotator, 'stop'):
            self.annotator.stop()
        self._set_status_label_state("Zatrzymywanie...", "warning")
