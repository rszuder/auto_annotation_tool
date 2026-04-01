#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Autoanotacja - Główne przetwarzanie YOLO (pojazdy + tablice)
Układ 3-kolumnowy z interaktywną przeglądarką na Canvasie.
"""

import json
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional
import datetime
import threading
import logging
import numpy as np

import cv2
from PIL import Image, ImageTk
from .zoomable_canvas import ZoomableCanvas

from ..config import CONFIG, logger, YOLO_AVAILABLE, AVAILABLE_DETECT_MODELS
from ..icons import IconManager
from ..annotators import PlateAnnotator, CombinedAnnotator
from ..exporters import CVATExporter, ReportGenerator
from ..training import DatasetCreator
from ..utils import count_images_in_directory, format_duration
from ..validators import validate_model_file
from .help_manager import HELP
from .web_slim_scrollbar import WebSlimScrollbar


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
        
        self.annotator = None
        self.dataset_creator = DatasetCreator()
        self.is_processing = False
        self.start_time = None
        
        # Zmienne do przeglądarki
        self.current_annotations = []
        self.current_input_dir = None
        
        self.mode_var = tk.StringVar(value="C: Pojazdy + tablice")
        self.vehicle_model_var = tk.StringVar()
        self.character_model_var = tk.StringVar()
        self.vehicle_custom_var = tk.StringVar()
        self.plate_custom_var = tk.StringVar()
        self.character_custom_var = tk.StringVar()
        self.device_var = tk.StringVar(value="auto")
        self.conf_var = tk.DoubleVar(value=CONFIG.DEFAULT_CONFIDENCE)
        self._campaign_paths_locked = False
        self._annotation_log_visible = False
        self._character_model_options = {}
        self._left_section_separators = []
        self._left_title_underlines = []
        self._left_path_button_width = 15
        self._left_path_action_minsize = 140
        self.project_paths_info_var = tk.StringVar(value="")
        self.project_paths_rel_var = tk.StringVar(value="")
        self.plate_dataset_run_var = tk.StringVar(value="")
        self.plate_dataset_images_var = tk.StringVar(value="")
        self.plate_dataset_out_var = tk.StringVar(value="")
        self.plate_train_pct = tk.DoubleVar(value=80.0)
        self.plate_val_pct = tk.DoubleVar(value=10.0)
        self.plate_export_progress_var = tk.DoubleVar(value=0.0)
        self.progress_counts_var = tk.StringVar(value="udane/przer./całość: 0/0/0")
        # Domyślnie podpowiadaj katalog wejściowy z workspace.
        self.input_dir_var = tk.StringVar(value=str(Path(CONFIG.DIR_1_RAW).absolute()))
        self.output_dir_var = tk.StringVar(value=str(Path(CONFIG.get_auto_annotations_dir("plate"))))

        self._create_widgets()
        self._refresh_device_options()
        self._update_model_lists()
        self._on_mode_change()

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

        left_frame = ttk.Frame(pane)
        center_frame = ttk.Frame(pane)
        right_frame = ttk.Frame(pane)

        pane.add(left_frame, weight=2)
        pane.add(center_frame, weight=4) # Środek ma więcej miejsca na zdjęcia
        pane.add(right_frame, weight=2)

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
            text="Etap 1: Utwórz run autoanotacji tablic",
            style="Panel.TLabel"
        )
        self.run_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._build_left_title_underline(actions_lf, self.run_title_lbl, pady=(2, 4))

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

        self._build_left_section_separator(settings_col, pady=(18, 20))

        export_lf = ttk.Frame(settings_col, style="Panel.TFrame")
        export_lf.pack(fill=tk.X)
        self.export_title_lbl = ttk.Label(
            export_lf,
            text="Etap 2: Z istniejącego runu zbuduj dataset YOLO Pose",
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
        preview_host.pack(fill=tk.BOTH, expand=True, padx=5, pady=0)

        preview_pane = ttk.PanedWindow(preview_host, orient=tk.HORIZONTAL)
        preview_pane.pack(fill=tk.BOTH, expand=True)

        list_lf = ttk.LabelFrame(preview_pane, text=" Lista wyników autoanotacji ", padding=8)
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
        preview_pane.add(preview_lf, weight=4)
        canvas_frame = ttk.Frame(preview_lf)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas = ZoomableCanvas(canvas_frame, bg="#1e1e1e", highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        log_tools = ttk.Frame(center_frame)
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

        self.annotation_log_frame = ttk.LabelFrame(center_frame, text=" Terminal procesu ", padding=6)
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

        self.approve_btn_row = ttk.Frame(right_frame)
        self.approve_btn_row.pack(fill=tk.X, pady=(8, 0))
        self.approve_btn_row.columnconfigure(0, weight=1)

        ttk.Label(settings_lf, text="Tryb pracy:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        modes = ["B: Tylko tablice", "C: Pojazdy + tablice"]
        self.mode_combo = ttk.Combobox(settings_lf, textvariable=self.mode_var, values=modes, state="readonly")
        self.mode_combo.pack(fill=tk.X, pady=(0, 15))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

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
        self.approve_btn_frame.grid(row=0, column=1, sticky="e")

        self.approve_btn_pulse_frame = tk.Frame(
            self.approve_btn_frame,
            bd=0,
            highlightthickness=1
        )
        self.approve_btn_pulse_frame.pack(anchor=tk.E)

        self.approve_btn = ttk.Button(
            self.approve_btn_pulse_frame,
            text="ZATWIERDŹ ETAP AUTOANOTACJI",
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
        HELP.bind_help(self.plate_browse_btn, "tab1_model_pla")
        HELP.bind_help(row_conf, "tab1_conf") 
        HELP.bind_help(self.device_combo, "tab1_device")
        HELP.bind_help(self.start_btn, "tab1_start")
        HELP.bind_help(self.stop_btn, "tab1_stop")
        HELP.bind_help(self.btn_toggle_annotation_log, "tab1_logs")
        HELP.bind_help(self.preview_listbox, "tab1_preview_list")
        HELP.bind_help(self.preview_canvas, "tab1_preview_canvas")
        HELP.bind_help(self.veh_custom_row, "tab1_custom_model")
        self._bind_scroll_canvas_children(self.left_settings_content, self.left_settings_canvas)
        self._bind_scroll_canvas_children(self.right_settings_content, self.right_settings_canvas)
        self.frame.after_idle(self._sync_left_panel_canvas_width)
        self.frame.after_idle(self._sync_left_panel_scrollregion)
        self.frame.after_idle(self._sync_right_panel_canvas_width)
        self.frame.after_idle(self._sync_right_panel_scrollregion)
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

        if self._mode_uses_vehicle(mode):
            self.vehicle_combo.config(state="readonly")
            self._on_vehicle_model_change() 
        else:
            self.vehicle_combo.config(state=tk.DISABLED)
            self.veh_custom_row.pack_forget()

        if self._mode_uses_plate(mode):
            self._set_plate_model_controls_state(True)
        else:
            self._set_plate_model_controls_state(False)

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
        if p: self.input_dir_var.set(p)

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

    def _plate_dataset_output_preview(self, run_dir: Path | None = None) -> str:
        run_name = run_dir.name if isinstance(run_dir, Path) else "run_xxx"
        return str(CONFIG.get_datasets_dir("plate") / f"Plates_Z2_{run_name}_[DATA_I_CZAS]")

    def _set_plate_export_status(self, text: str, tone: str = "muted"):
        self._set_inline_label_state(
            self.plate_export_status_lbl,
            text=text,
            tone=tone,
            emphasis=False
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
        if run_value:
            candidate = Path(run_value)
            if candidate.exists() and candidate.is_dir():
                run_dir = candidate

        if run_dir is None and getattr(self, "last_staging_run_dir", None):
            candidate = Path(self.last_staging_run_dir)
            if candidate.exists() and candidate.is_dir():
                run_dir = candidate

        if run_dir is None:
            run_dir = self._find_latest_annotation_run_dir()

        if run_dir is not None:
            self._load_plate_dataset_context_from_run(run_dir)
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
            return

        self.plate_dataset_out_var.set(self._plate_dataset_output_preview())
        self._set_plate_export_status(
            "Brak runu Z2. Najpierw uruchom Start, aby utworzyć nowy run autoanotacji, albo wskaż istniejący folder run ręcznie.",
            "muted"
        )

    def _select_plate_dataset_run_dir(self):
        initialdir = self.plate_dataset_run_var.get().strip() or self.output_dir_var.get().strip() or str(CONFIG.get_auto_annotations_dir("plate"))
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
        out_dir = CONFIG.get_datasets_dir("plate") / f"Plates_Z2_{run_dir.name}_{timestamp}"
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

                logger.info(f"[OK] Dataset YOLO Pose gotowy: {out_dir}")

                def finish_success():
                    self.plate_export_progress_var.set(100.0)
                    self._set_plate_export_status(
                        f"Dataset gotowy: {self._format_workspace_relative_path(out_dir)}",
                        "success"
                    )
                    training_tab = getattr(getattr(self, "app", None), "tabs", {}).get("training")
                    if training_tab is not None and hasattr(training_tab, "dataset_var"):
                        try:
                            training_tab.dataset_var.set(str(out_dir))
                            if hasattr(training_tab, "_update_training_dataset_hint"):
                                training_tab._update_training_dataset_hint()
                        except Exception:
                            pass
                    messagebox.showinfo(
                        "Sukces",
                        f"Dataset YOLO Pose zostal utworzony poprawnie.\n\n{out_dir}"
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
                self.frame.after(0, lambda: self.export_plate_dataset_btn.configure(state=tk.NORMAL))

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

            ok_color = palette.get("success", "#27ae60")
            err_color = palette.get("error", "#c0392b")
            for idx, ann in enumerate(getattr(self, "current_annotations", [])):
                try:
                    self.preview_listbox.itemconfig(
                        idx,
                        foreground=ok_color if ann.is_successful else err_color
                    )
                except Exception:
                    pass
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
        if not hasattr(self, "annotation_log_frame"):
            return

        self._annotation_log_visible = bool(visible)

        if self._annotation_log_visible:
            self.annotation_log_frame.pack(fill=tk.BOTH, expand=False, padx=5, pady=(8, 0))
            if hasattr(self, "btn_toggle_annotation_log"):
                self.btn_toggle_annotation_log.configure(text="Ukryj terminal")
        else:
            self.annotation_log_frame.pack_forget()
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

    def clear_campaign_context(self):
        """
        Przywraca neutralny stan zakładki Autoanotacji po wyjściu z projektu
        i czyści wszystkie artefakty poprzedniego projektu z UI.
        """
        self.input_dir_var.set(str(Path(CONFIG.DIR_1_RAW).absolute()))
        self.output_dir_var.set(str(Path(CONFIG.get_auto_annotations_dir("plate")).absolute()))

        self.mode_var.set("C: Pojazdy + tablice")
        self.device_var.set("auto")
        try:
            self._refresh_device_options()
        except Exception:
            pass

        try:
            if YOLO_AVAILABLE:
                v_keys = sorted(list(AVAILABLE_DETECT_MODELS.keys()))

                if v_keys:
                    preferred_vehicle = "yolo11s" if "yolo11s" in v_keys else v_keys[0]
                    self.vehicle_model_var.set(preferred_vehicle)
        except Exception:
            pass

        try:
            self.character_model_var.set("Brak / OCR")
            self.character_custom_var.set("")
            self._refresh_character_model_choices()
        except Exception:
            pass

        try:
            self.vehicle_custom_var.set("")
        except Exception:
            pass

        try:
            self.plate_custom_var.set("")
        except Exception:
            pass

        try:
            self._on_mode_change()
        except Exception:
            pass

        try:
            self._refresh_device_options()
        except Exception:
            pass

        try:
            self._on_vehicle_model_change()
        except Exception:
            pass

        try:
            self._set_plate_model_controls_state(self._mode_uses_plate())
        except Exception:
            pass

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

    def apply_campaign_context(self, input_dir: Path, output_dir: Path):
        self.input_dir_var.set(str(input_dir))
        self.output_dir_var.set(str(output_dir))
        self.mode_var.set("C: Pojazdy + tablice")
        self.character_model_var.set("Brak / OCR")
        self.character_custom_var.set("")
        self._on_mode_change()
        self._set_campaign_paths_lock_state(True)
        if hasattr(self, "character_combo"):
            self._refresh_character_model_choices()
        self._pulse_action_frame("start_btn_pulse_frame")

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
            self._validate_models()
            mode_text = self._normalize_mode_value()
            self.mode_var.set(mode_text)
            conf = self.conf_var.get()
            selected_device = self._normalize_selected_device()
            self.device_var.set(selected_device)
            dev = self._device_to_ultralytics(selected_device)

            pending_downloads = self._collect_pending_model_downloads(mode_text)
            if not self._confirm_and_download_missing_models(pending_downloads):
                return
            
            v_p = self._get_model_path("vehicle") if self._mode_uses_vehicle(mode_text) else None
            p_p = self._get_model_path("plate") if self._mode_uses_plate(mode_text) else None

            if self.annotator is not None:
                try: self.annotator.unload_models()
                except: pass

            if self._mode_uses_vehicle(mode_text):
                self.annotator = CombinedAnnotator(v_p, p_p, conf, conf, CONFIG.PLATE_INSIDE_THRESHOLD, dev)
            else:
                self.annotator = PlateAnnotator(p_p, conf, dev)
            
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

            self.is_processing = True
            self.app.set_processing(True)
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.approve_btn.config(state=tk.DISABLED)
            self.export_plate_dataset_btn.config(state=tk.DISABLED)
            self.progress.configure(value=0)
            self._set_progress_counters(0, 0, 0)
            
            self.preview_listbox.delete(0, tk.END)
            self.preview_canvas.delete("all")
            self.current_annotations = []
            
            logger.info("="*50)
            logger.info("ROZPOCZĘTO AUTOANOTACJĘ OBRAZÓW (YOLO)")
            logger.info("="*50)
            logger.info(f"Urzadzenie Z2: {selected_device} -> runtime={dev}")
            
            threading.Thread(target=self._process_thread, args=(Path(in_d), Path(self.output_dir_var.get())), daemon=True).start()
            
        except Exception as e:
            logger.error(f"Nie można wystartować: {e}")
            messagebox.showerror("Błąd Startu", str(e))

    def _process_thread(self, in_dir: Path, base_out_dir: Path):
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
            
            annotations, report = self.annotator.process_directory(in_dir, prog_cb)
            
            if self.annotator.is_stopped() or not self.is_processing:
                message = "Przetwarzanie przerwane przez użytkownika."
                success = False
                return

            self.current_annotations = annotations
            self.current_input_dir = in_dir
            self.frame.after(0, self._populate_preview_list)

            base_out_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            counter = 1
            while True:
                run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}"
                if not run_dir.exists(): break
                counter += 1
                
            run_dir.mkdir(parents=True, exist_ok=True)
            cvat_xml_path = run_dir / "annotations.xml"

            logger.info("Zapisywanie bazy detekcji (annotations.xml)...")
            CVATExporter().export(annotations, cvat_xml_path)

            logger.info("Generowanie raportu statystycznego...")
            ReportGenerator.generate_text_report(report, run_dir / "report.txt")

            try:
                self._write_annotation_run_manifest(run_dir, in_dir)
            except Exception as e:
                logger.debug(f"Nie udało się zapisać manifestu runu Z2: {e}")

            elapsed = format_duration((datetime.datetime.now() - self.start_time).total_seconds())

            # Zachowaj ścieżkę do ostatniego runu w stagingu.
            self.last_staging_run_dir = run_dir
            self.frame.after(0, self._refresh_plate_dataset_export_sources)

            message = f"Zakończono! Zapisano do: {run_dir.name} (w czasie {elapsed})"
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
            successful = sum(1 for ann in (self.current_annotations or []) if getattr(ann, "is_successful", False))
            self._set_progress_counters(successful, total, total)
        else:
            self._set_progress_counters(0, 0, 0)
        
        if success:
            self._set_status_label_state("Zakończono pomyślnie!", "success")

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

            messagebox.showinfo("Koniec", msg)
        else:
            self._set_status_label_state("Przerwano / Błąd", "error")
            messagebox.showerror("Zatrzymano", msg)

    def _approve_annotation_stage(self):
        """
        Zatwierdza staging autoanotacji i przenosi go do katalogu docelowego projektu.
        """
        try:
            from ..campaign_manager import CAMPAIGN
            import shutil

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

            CAMPAIGN.approve_step2()
            CAMPAIGN.set_current_step(3)

            self.approve_btn.config(state=tk.DISABLED)

            if 'campaign' in self.app.tabs:
                self.app.tabs['campaign']._refresh_dashboard()

            self.app.update_status(
                "Zatwierdzono etap autoanotacji. Wyniki przeniesiono z katalogu stagingu do 2_auto_annotations projektu.",
                "info"
            )
            # po zatwierdzeniu wracamy do Wizarda
            try:
                self.app.select_tab("campaign")
                self.app.update_campaign_tab_access()
            except Exception as e:
                logger.debug(f"Nie udało się wrócić do zakładki Wizarda: {e}")

            messagebox.showinfo("Sukces", f"Etap autoanotacji został zatwierdzony.\n\nWyniki przeniesiono do:\n{target_dir}")

        except Exception as e:
            messagebox.showerror("Błąd zatwierdzania", str(e))

    def _stop_annotation(self):
        self.is_processing = False
        if self.annotator and hasattr(self.annotator, 'stop'):
            self.annotator.stop()
        self._set_status_label_state("Zatrzymywanie...", "warning")
