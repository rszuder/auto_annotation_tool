#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Autoanotacja - Główne przetwarzanie YOLO (pojazdy + tablice)
Układ 3-kolumnowy z interaktywną przeglądarką na Canvasie.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
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
from ..annotators import VehicleAnnotator, PlateAnnotator, CombinedAnnotator
from ..exporters import CVATExporter, ReportGenerator
from ..utils import count_images_in_directory, format_duration
from ..validators import validate_model_file
from .help_manager import HELP

class AnnotationTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon = IconManager
        self.frame = ttk.Frame(parent)
        
        self.annotator = None
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
        self.project_paths_info_var = tk.StringVar(value="")
        self.project_paths_rel_var = tk.StringVar(value="")
        # Domyślnie podpowiadaj katalog wejściowy z workspace.
        self.input_dir_var = tk.StringVar(value=str(Path(CONFIG.DIR_1_RAW).absolute()))
        self.output_dir_var = tk.StringVar(value=str(Path(CONFIG.DEFAULT_OUTPUT_DIR)))

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
        paths_lf = ttk.LabelFrame(left_frame, text=" Ścieżki danych ", padding=15)
        paths_lf.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(paths_lf, text="Folder wejściowy (obrazy):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row_in = ttk.Frame(paths_lf)
        row_in.pack(fill=tk.X, pady=(0, 6))

        self.input_dir_entry = ttk.Entry(row_in, textvariable=self.input_dir_var)
        self.input_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.input_dir_browse_btn = ttk.Button(row_in, text="Wybierz", command=self._select_input_dir)
        self.input_dir_browse_btn.pack(side=tk.RIGHT, padx=(5,0))

        self.project_paths_info_lbl = tk.Label(
            paths_lf,
            textvariable=self.project_paths_info_var,
            font=("Segoe UI", 9, "bold"),
            wraplength=360,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.project_paths_info_lbl.pack(anchor=tk.W, fill=tk.X)
        self._set_inline_label_state(self.project_paths_info_lbl, tone="info", emphasis=True)

        self.project_paths_rel_lbl = tk.Label(
            paths_lf,
            textvariable=self.project_paths_rel_var,
            wraplength=360,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0
        )
        self.project_paths_rel_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 10))
        self._set_inline_label_state(self.project_paths_rel_lbl, tone="muted", emphasis=False)

        ttk.Label(paths_lf, text="Katalog docelowy (tworzony automatycznie):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row_out = ttk.Frame(paths_lf)
        row_out.pack(fill=tk.X, pady=(0, 5))
        self.output_dir_var.set(str(Path(CONFIG.DIR_2_AUTO_ANN)))
        ttk.Entry(row_out, textvariable=self.output_dir_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)

        actions_lf = ttk.LabelFrame(left_frame, text=" Przetwarzanie YOLO ", padding=15)
        actions_lf.pack(fill=tk.X)

        self.start_btn_row = ttk.Frame(actions_lf)
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
            text="STARTUJ – AUTOANOTACJĘ",
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

        self.progress = ttk.Progressbar(actions_lf, mode='determinate', maximum=100)
        self.progress.pack(fill=tk.X, pady=(15, 5))
        self.status_label = tk.Label(
            actions_lf,
            text="Gotowy",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            bd=0,
            highlightthickness=0
        )
        self.status_label.pack(anchor=tk.W)
        self._set_inline_label_state(self.status_label, text="Gotowy", tone="neutral", emphasis=True)

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
        scroll = ttk.Scrollbar(list_frame, command=self.preview_listbox.yview)
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
        self.log_text = scrolledtext.ScrolledText(
            self.annotation_log_frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#161616",
            fg="#f3f3f3",
            insertbackground="#f3f3f3"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self._redirect_logs()
        self._set_annotation_process_log_visibility(False)

        # --- PRAWA KOLUMNA ---
        settings_lf = ttk.LabelFrame(right_frame, text=" Konfiguracja Detekcji ", padding=15)
        settings_lf.pack(fill=tk.BOTH, expand=True)

        self.approve_btn_row = ttk.Frame(right_frame)
        self.approve_btn_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.approve_btn_row.columnconfigure(0, weight=1)

        ttk.Label(settings_lf, text="Tryb pracy:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        modes = ["A: Tylko pojazdy", "B: Tylko tablice", "C: Pojazdy + tablice"]
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
        ttk.Label(
            self.pla_frame,
            text="Wskaz wytrenowany model YOLO Pose (.pt) dla detekcji tablic.",
            style="Muted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 4))
        self.pla_custom_row = ttk.Frame(self.pla_frame)
        self.pla_custom_row.pack(fill=tk.X, pady=2)
        self.plate_path_entry = ttk.Entry(self.pla_custom_row, textvariable=self.plate_custom_var)
        self.plate_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.plate_browse_btn = ttk.Button(self.pla_custom_row, text="Wybierz", command=self._select_plate_custom)
        self.plate_browse_btn.pack(side=tk.RIGHT, padx=(5,0))

        self.char_frame = ttk.LabelFrame(settings_lf, text=" Model Znakow (YOLO / Z3) ", padding=10)
        self.char_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            self.char_frame,
            text="Opcjonalny model dla kroku Z3 / kampanii.",
            style="Muted.TLabel",
            wraplength=320,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 4))
        self.character_combo = ttk.Combobox(self.char_frame, textvariable=self.character_model_var, state="readonly")
        self.character_combo.pack(fill=tk.X, pady=2)
        self.character_combo.bind("<<ComboboxSelected>>", self._on_character_model_change)
        self.char_custom_row = ttk.Frame(self.char_frame)
        ttk.Entry(self.char_custom_row, textvariable=self.character_custom_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self.char_custom_row, text="Wybierz", command=self._select_character_custom).pack(side=tk.RIGHT, padx=(5,0))
        self.char_custom_row.pack(fill=tk.X, pady=(5,0))

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
        HELP.bind_help(row_in, "tab1_input")
        HELP.bind_help(row_out, "tab1_output")
        HELP.bind_help(self.mode_combo, "tab1_mode")
        HELP.bind_help(self.vehicle_combo, "tab1_model_veh")
        HELP.bind_help(self.pla_frame, "tab1_model_pla")
        HELP.bind_help(self.plate_path_entry, "tab1_model_pla")
        HELP.bind_help(self.plate_browse_btn, "tab1_model_pla")
        HELP.bind_help(self.character_combo, "tab1_model_char")
        HELP.bind_help(row_conf, "tab1_conf") 
        HELP.bind_help(self.device_combo, "tab1_device")
        HELP.bind_help(self.start_btn, "tab1_start")
        HELP.bind_help(self.stop_btn, "tab1_stop")
        HELP.bind_help(self.btn_toggle_annotation_log, "tab1_logs")
        HELP.bind_help(self.preview_listbox, "tab1_preview_list")
        HELP.bind_help(self.preview_canvas, "tab1_preview_canvas")
        HELP.bind_help(self.veh_custom_row, "tab1_custom_model")
        HELP.bind_help(self.char_custom_row, "tab1_custom_model")

    def _on_mode_change(self, event=None):
        mode = self.mode_var.get()
        if "A:" in mode or "C:" in mode:
            self.vehicle_combo.config(state="readonly")
            self._on_vehicle_model_change() 
        else:
            self.vehicle_combo.config(state=tk.DISABLED)
            self.veh_custom_row.pack_forget()

        if "B:" in mode or "C:" in mode:
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
        chars_dir = Path(CONFIG.DIR_6_MODELS_CHARS)
        if chars_dir.exists():
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

        return candidates

    def _refresh_character_model_choices(self):
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
        p = filedialog.askopenfilename(initialdir=str(Path(CONFIG.DIR_6_MODELS).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p: self.vehicle_custom_var.set(p)

    def _select_plate_custom(self):
        p = filedialog.askopenfilename(initialdir=str(Path(CONFIG.DIR_6_MODELS).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p: self.plate_custom_var.set(p)

    def _select_character_custom(self):
        p = filedialog.askopenfilename(initialdir=str(Path(CONFIG.DIR_6_MODELS).absolute()), filetypes=[("YOLO Model", "*.pt")])
        if p:
            self.character_custom_var.set(p)
            self.character_model_var.set("Custom")
            self._on_character_model_change()

    def _select_input_dir(self):
        p = filedialog.askdirectory(initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()))
        if p: self.input_dir_var.set(p)

    def _redirect_logs(self):
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
                except: pass
                
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s', '%H:%M:%S'))
        logger.addHandler(handler)

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

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
            self._update_device_hint()
        except Exception:
            pass

        frame_backgrounds = {
            "start_btn_frame": palette.get("panel", "#252526"),
            "approve_btn_frame": palette.get("bg", "#1f1f1f"),
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
            "approve_btn_pulse_frame": palette.get("bg", "#1f1f1f"),
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
            "project_paths_info_lbl": ("info", True),
            "project_paths_rel_lbl": ("muted", False),
            "status_label": ("neutral", True),
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
        mode = self.mode_var.get()
        if "A:" in mode or "C:" in mode:
            if self.vehicle_model_var.get() == "Custom":
                p = self.vehicle_custom_var.get()
                if not p or not Path(p).exists(): raise ValueError("Nie znaleziono własnego modelu pojazdów!")
                if not validate_model_file(Path(p))[0]: raise ValueError("Model pojazdów jest uszkodzony!")
        
        if "B:" in mode or "C:" in mode:
            p = (self.plate_custom_var.get() or "").strip()
            if not p or not Path(p).exists(): raise ValueError("Wskaż wytrenowany model tablic (.pt)!")
            if not validate_model_file(Path(p))[0]: raise ValueError("Model tablic jest uszkodzony!")

    def clear_campaign_context(self):
        """
        Przywraca neutralny stan zakładki Autoanotacji po wyjściu z projektu
        i czyści wszystkie artefakty poprzedniego projektu z UI.
        """
        self.input_dir_var.set(str(Path(CONFIG.DIR_1_RAW).absolute()))
        self.output_dir_var.set(str(Path(CONFIG.DIR_2_AUTO_ANN).absolute()))

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
            self._set_plate_model_controls_state("B:" in self.mode_var.get() or "C:" in self.mode_var.get())
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
            self.progress["value"] = 0
        except Exception:
            pass

        try:
            self._set_status_label_state("Gotowy do uruchomienia", "neutral")
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
        self._refresh_character_model_choices()
        self._pulse_action_frame("start_btn_pulse_frame")

    def _get_model_path(self, model_type: str) -> Path:
        if model_type == "vehicle":
            if self.vehicle_model_var.get() == "Custom": return Path(self.vehicle_custom_var.get())
            else: return Path(CONFIG.DEFAULT_MODELS_DIR) / AVAILABLE_DETECT_MODELS[self.vehicle_model_var.get()]["file"]
        else:
            return Path(self.plate_custom_var.get())

    def _start_annotation(self):
        in_d = self.input_dir_var.get().strip()
        if not in_d or not Path(in_d).exists():
            return messagebox.showerror("Błąd", "Wybierz folder z obrazami wejściowymi.")
        
        try:
            self._validate_models()
            mode_text = self.mode_var.get()
            conf = self.conf_var.get()
            selected_device = self._normalize_selected_device()
            self.device_var.set(selected_device)
            dev = self._device_to_ultralytics(selected_device)
            
            v_p = self._get_model_path("vehicle") if ("A:" in mode_text or "C:" in mode_text) else None
            p_p = self._get_model_path("plate") if ("B:" in mode_text or "C:" in mode_text) else None

            if self.annotator is not None:
                try: self.annotator.unload_models()
                except: pass

            if "A:" in mode_text: self.annotator = VehicleAnnotator(v_p, conf, dev)
            elif "B:" in mode_text: self.annotator = PlateAnnotator(p_p, conf, dev)
            else: self.annotator = CombinedAnnotator(v_p, p_p, conf, conf, CONFIG.PLATE_INSIDE_THRESHOLD, dev)
            
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
            self.progress['value'] = 0
            
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
            
            def prog_cb(current, total, filename):
                if not self.is_processing: raise KeyboardInterrupt("Anulowano")
                pct = (current / total) * 100 if total > 0 else 0
                self.frame.after(0, lambda: self._update_progress(pct, current, total, filename))
            
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

            elapsed = format_duration((datetime.datetime.now() - self.start_time).total_seconds())

            # Zachowaj ścieżkę do ostatniego runu w stagingu.
            self.last_staging_run_dir = run_dir

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

    def _update_progress(self, pct, current, total, filename):
        self.progress['value'] = pct
        self._set_status_label_state(
            f"Przetwarzanie {current}/{total} ({int(pct)}%)",
            "info"
        )

    def _finish(self, success, msg):
        self.is_processing = False
        self.app.set_processing(False)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.progress['value'] = 100 if success else 0
        
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
