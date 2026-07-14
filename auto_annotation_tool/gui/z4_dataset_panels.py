#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z4 dataset creator and splitter panel builders extracted from tab_training.py."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import datetime
import time
import webbrowser
import csv
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..campaign_manager import CAMPAIGN
from ..config import (
    CONFIG,
    YOLO_AVAILABLE,
    AVAILABLE_POSE_MODELS,
    AVAILABLE_DETECT_MODELS,
    PIL_AVAILABLE,
    get_torch_module,
    get_yolo_class,
    is_cuda_available,
    logger,
)
from ..icons import IconManager
from ..validators import validate_model_file, format_yolo_model_identity
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..ranking import ModelRanking
from ..utils import cleanup_gpu_memory, safe_load_yaml, get_image_files
from .help_manager import HELP
from .inertial_scroll import InertialScrollController
from .section_header_label import SectionHeaderLabel
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors
from .zoomable_canvas import ZoomableCanvas
from .z4_train_progress_bar import TrainProgressBar
from .z4_campaign_flow import (
    build_step4_campaign_navigation_view_model,
    build_step4_dataset_workflow_view_model,
    build_step4_training_inputs_view_model,
    clear_campaign_context,
    complete_campaign_project,
    finish_campaign_step4,
    get_campaign_training_target,
    open_campaign_step4_entry,
    poll_training_completion,
    restore_step4_campaign_project_state,
    set_campaign_context,
    set_campaign_training_target,
)
from .z4_flow_models import (
    CharYoloDatasetSourceAdapter,
    PlateXmlImagesSourceAdapter,
    TrainingSource,
    TrainingSourceStats,
)
from .z4_free_mode_flow import (
    refresh_free_training_route_cards,
    refresh_free_training_route_ui,
    update_step4_notebook_mode,
)
from .z4_shared_ui import (
    accept_training_input_context,
    clear_step4_guidance,
    guide_step4_builder_action,
    guide_step4_finish_action,
    guide_step4_next_action,
    guide_step4_route_selection,
    mark_step4_dataset_ready,
    open_step4_dataset_stage,
    refresh_step4_campaign_builder_inputs_ui,
    refresh_step4_analysis_tab_visibility,
    refresh_step4_campaign_navigation_ui,
    refresh_step4_dataset_mode_ui,
    refresh_step4_training_inputs_mode_ui,
    set_step4_dataset_mode,
    sync_step4_analysis_nav_buttons,
    step4_dataset_go_back,
    step4_dataset_go_next,
    step4_train_go_back,
)
from . import z4_dataset_sources
from . import z4_training_metrics
from . import z4_dataset_builder
from . import z4_analysis_ranking
from . import z4_training_runtime
from . import z4_campaign_state
from . import z4_dataset_validation
from . import z4_layout_runtime
from . import z4_device_runtime
from . import z4_model_export
from . import z4_training_progress
from . import z4_ui_runtime
from . import z4_theme_runtime
from . import z4_tab_shell
from . import z4_history_runtime
from .z4_view_models import (
    Step4CampaignNavigationViewModel,
    Step4DatasetWorkflowViewModel,
    Step4TrainingInputsViewModel,
)

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageFont

YOLO = None


def _get_step4_table_colors(self):
    palette = getattr(self.app, "palette", {})
    panel = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    field = palette.get("field", panel_alt)
    success = palette.get("success", "#4ec9b0")
    border_base = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    border = blend_hex_colors(success, border_base, 0.62)
    return {
        "panel": panel,
        "header": blend_hex_colors(success, panel_alt, 0.84),
        "row": field,
        "row_alt": blend_hex_colors(panel_alt, panel, 0.45),
        "border": border,
        "fg": palette.get("fg", "#f3f3f3"),
        "muted": palette.get("muted", "#c7c7c7"),
        "accent": success,
        "warning": palette.get("warning", "#d7ba7d"),
    }


def _make_step4_action_shell(self, parent, *, title: str, description: str):
    palette = getattr(self.app, "palette", {})
    panel = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", panel)
    border = blend_hex_colors(palette.get("success", "#2fa36b"), palette.get("panel_border", "#3c3c3c"), 0.68)
    bg = blend_hex_colors(panel_alt, panel, 0.60)
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    success = palette.get("success", "#4ec9b0")

    shell = tk.Frame(parent, bg=border, padx=1, pady=1, bd=0, highlightthickness=0)
    inner = tk.Frame(shell, bg=bg, padx=12, pady=10, bd=0, highlightthickness=0)
    inner.pack(fill=tk.X, expand=True)
    setattr(shell, "_step4_action_inner", inner)
    setattr(shell, "_step4_action_bg", bg)

    tk.Label(
        inner,
        text=title,
        font=("Segoe UI Semibold", 10),
        fg=success,
        bg=bg,
        anchor="w",
        justify=tk.LEFT,
        bd=0,
        highlightthickness=0,
    ).pack(anchor=tk.W, fill=tk.X)
    tk.Label(
        inner,
        text=description,
        font=("Segoe UI", 9),
        fg=muted,
        bg=bg,
        wraplength=720,
        anchor="w",
        justify=tk.LEFT,
        bd=0,
        highlightthickness=0,
    ).pack(anchor=tk.W, fill=tk.X, pady=(4, 10))

    return shell, inner, bg


def _make_step4_flow_strip(self, parent):
    colors = _get_step4_table_colors(self)
    strip = tk.Frame(parent, bg=colors["panel"], bd=0, highlightthickness=0)
    strip.pack(fill=tk.X, pady=(0, 12))
    steps = (
        ("1", "Materia\u0142"),
        ("2", "Split"),
        ("3", "Powi\u0119kszenie"),
        ("4", "Wariant"),
    )
    for index, (number, label) in enumerate(steps):
        pill = tk.Frame(
            strip,
            bg=colors["row_alt"],
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["border"],
            padx=8,
            pady=5,
        )
        pill.pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(
            pill,
            text=number,
            bg=colors["header"],
            fg=colors["accent"],
            font=("Segoe UI Semibold", 8),
            width=2,
            bd=0,
            highlightthickness=0,
        ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(
            pill,
            text=label,
            bg=colors["row_alt"],
            fg=colors["fg"],
            font=("Segoe UI", 8),
            bd=0,
            highlightthickness=0,
        ).pack(side=tk.LEFT)
        if index < len(steps) - 1:
            tk.Label(
                strip,
                text="\u203a",
                bg=colors["panel"],
                fg=colors["muted"],
                font=("Segoe UI Semibold", 11),
                bd=0,
                highlightthickness=0,
            ).pack(side=tk.LEFT, padx=(0, 6))
    return strip


def _build_step4_augmentation_controls(self, parent, *, target: str):
    normalized_target = CONFIG.normalize_task_target(target)
    prefix = "creator" if normalized_target == "plate" else "split"
    target_label = "tablic" if normalized_target == "plate" else "znaków"

    frame = ttk.LabelFrame(parent, text=" Syntetyczne zwiększanie datasetu ", padding=8)
    frame.configure(text=f" 3. Syntetyczne powiększenie train ({target_label}) ")
    frame.pack(fill=tk.X, pady=(6, 6))
    target_label = "tablic" if normalized_target == "plate" else "znak\u00f3w"
    frame.configure(text=f" 3. Syntetyczne powi\u0119kszenie train ({target_label}) ")
    setattr(self, f"{prefix}_augmentation_frame", frame)

    try:
        self._ensure_step4_augmentation_profile(normalized_target)
    except Exception:
        pass

    augmentation_intro_label = ttk.Label(
        frame,
        text=(
            "Opcjonalnie powiększ wyłącznie część train aktualnego wariantu datasetu. "
            "Wygenerowane obrazy służą tylko treningowi tego wariantu: nie trafiają do puli obrazów "
            "projektu i nie są bazą kolejnej iteracji. Val i test pozostają oryginalne."
        ),
        justify=tk.LEFT,
        wraplength=700,
    )
    augmentation_intro_label.grid(row=0, column=0, columnspan=3, sticky=tk.EW, pady=(0, 6))

    try:
        augmentation_profile = self._ensure_step4_augmentation_profile(normalized_target)
    except Exception:
        augmentation_profile = None
    initial_extra = max(0, int(getattr(augmentation_profile, "extra_count", 0) or 0))
    initial_sample = max(1, int(getattr(augmentation_profile, "sample_size", 1) or 1))
    enabled_var = tk.BooleanVar(value=bool(getattr(augmentation_profile, "enabled", False) and initial_extra > 0))
    extra_var = tk.IntVar(value=initial_extra)
    sample_var = tk.IntVar(value=initial_sample)
    class_var = tk.StringVar(value=str(getattr(augmentation_profile, "class_name", "") or ("plate" if normalized_target == "plate" else "")))
    setattr(self, f"{prefix}_aug_enabled_var", enabled_var)
    setattr(self, f"{prefix}_aug_extra_var", extra_var)
    setattr(self, f"{prefix}_aug_sample_var", sample_var)
    if normalized_target == "plate":
        setattr(self, f"{prefix}_class_name_var", class_var)

    def _on_plan_change(*_args):
        try:
            self._refresh_step4_augmentation_summary(normalized_target)
        except Exception:
            pass

    for plan_var in (enabled_var, extra_var, class_var):
        try:
            plan_var.trace_add("write", _on_plan_change)
        except Exception:
            pass

    plan_frame = ttk.Frame(frame)
    plan_frame.grid(row=1, column=0, columnspan=3, sticky=tk.EW, pady=(0, 8))
    plan_frame.columnconfigure(1, weight=0)
    plan_frame.columnconfigure(2, weight=0)
    plan_frame.columnconfigure(3, weight=1)
    ttk.Checkbutton(
        plan_frame,
        text="W\u0142\u0105cz syntetyczne powi\u0119kszenie train",
        variable=enabled_var,
    ).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 4))
    ttk.Label(plan_frame, text="Generuj dodatkowo").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=2)
    ttk.Spinbox(plan_frame, from_=0, to=100000, textvariable=extra_var, width=9).grid(row=1, column=1, sticky=tk.W, pady=2)
    ttk.Label(plan_frame, text="obraz\u00f3w train").grid(row=1, column=2, sticky=tk.W, padx=(8, 0), pady=2)
    if normalized_target == "plate":
        ttk.Label(plan_frame, text="Klasa YOLO").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(4, 0))
        ttk.Entry(plan_frame, textvariable=class_var, width=18).grid(row=2, column=1, sticky=tk.W, pady=(4, 0))
        ttk.Label(
            plan_frame,
            text="Etykieta klasy zapisana w data.yaml, np. plate albo pl.",
            foreground="#6b7280",
        ).grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(2, 0))

    balance_vars = {
        "current": tk.StringVar(value="-"),
        "extra": tk.StringVar(value="+0"),
        "total": tk.StringVar(value="-"),
    }
    for key, var in balance_vars.items():
        setattr(self, f"{prefix}_aug_balance_{key}_var", var)

    table_colors = _get_step4_table_colors(self)
    balance_frame = tk.Frame(
        frame,
        bg=table_colors["border"],
        padx=1,
        pady=1,
        bd=0,
        highlightthickness=0,
    )
    balance_frame.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(2, 8))
    for column in range(3):
        balance_frame.columnconfigure(column, weight=1, uniform=f"{prefix}_aug_balance")
    for column, title in enumerate(("Teraz w train", "Dodajemy", "Po powi\u0119kszeniu")):
        tk.Label(
            balance_frame,
            text=title,
            anchor=tk.CENTER,
            padx=9,
            pady=5,
            bg=table_colors["header"],
            fg=table_colors["accent"],
            font=("Segoe UI Semibold", 8),
            bd=0,
            highlightthickness=1,
            highlightbackground=table_colors["border"],
            highlightcolor=table_colors["border"],
        ).grid(row=0, column=column, sticky=tk.EW)
    for column, key in enumerate(("current", "extra", "total")):
        tk.Label(
            balance_frame,
            textvariable=balance_vars[key],
            anchor=tk.CENTER,
            padx=9,
            pady=7,
            bg=(table_colors["row"] if column % 2 == 0 else table_colors["row_alt"]),
            fg=table_colors["fg"],
            font=("Segoe UI", 10, "bold"),
            bd=0,
            highlightthickness=1,
            highlightbackground=table_colors["border"],
            highlightcolor=table_colors["border"],
        ).grid(row=1, column=column, sticky=tk.EW)

    summary_var = tk.StringVar(
        value="Powiększenie syntetyczne jest wyłączone. Dataset powstanie tylko z materiału źródłowego projektu."
    )
    setattr(self, f"{prefix}_aug_summary_var", summary_var)
    ttk.Label(frame, textvariable=summary_var, justify=tk.LEFT, wraplength=520).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))
    configure_aug_button = ttk.Button(
        plan_frame,
        text="Skonfiguruj powiększenie",
        command=lambda t=normalized_target: self._open_step4_augmentation_modal(t),
    )
    configure_aug_button.grid(row=1, column=3, sticky=tk.W, padx=(12, 0), pady=2)
    configure_aug_button.configure(text="Edytuj efekty bazowe")
    configure_aug_button.configure(state=(tk.NORMAL if bool(enabled_var.get()) and int(extra_var.get() or 0) > 0 else tk.DISABLED))
    setattr(self, f"{prefix}_aug_configure_button", configure_aug_button)
    frame.columnconfigure(0, weight=1)
    try:
        self._refresh_step4_augmentation_summary(normalized_target)
    except Exception:
        pass
    try:
        HELP.bind_help(frame, "tr_split_ratios")
    except Exception:
        pass
    return


def _build_creator_ui(self):
    f = self.ds_creator_frame
    palette = getattr(self.app, "palette", {})
    self.creator_intro_lbl = ttk.Label(
        f,
        text=(
            "Sprawdź źródło, ustaw split i utwórz wariant do treningu modelu tablic."
        ),
        font=("Segoe UI", 9),
        wraplength=720,
        justify=tk.LEFT,
    )
    self.creator_intro_lbl.pack(anchor=tk.W, pady=(0, 10))
    self.creator_intro_lbl.configure(
        text=(
            "Sprawdź źródło, ustaw split i utwórz wariant do treningu modelu tablic. "
            "Augmentacja powiększa tylko część train."
        )
    )
    self.creator_flow_strip = _make_step4_flow_strip(self, f)

    summary_colors = _get_step4_table_colors(self)
    self.creator_campaign_summary_title = tk.Label(
        f,
        text="1. Materia\u0142 projektu dla bramki T07",
        font=("Segoe UI Semibold", 9),
        padx=2,
        pady=2,
        anchor="w",
        bd=0,
        highlightthickness=0,
        bg=palette.get("panel", "#252526"),
        fg=summary_colors["fg"],
    )
    self.creator_campaign_summary_title.pack(fill=tk.X, pady=(0, 4))
    self.creator_campaign_summary_frame = tk.Frame(
        f,
        bd=0,
        padx=1,
        pady=1,
        bg=summary_colors["border"],
        highlightthickness=0,
    )
    self.creator_campaign_summary_frame.pack(fill=tk.X, pady=(0, 10))
    self.creator_campaign_summary_grid = tk.Frame(
        self.creator_campaign_summary_frame,
        bd=0,
        highlightthickness=0,
        bg=summary_colors["border"],
    )
    self.creator_campaign_summary_grid.pack(fill=tk.X)
    self.creator_campaign_summary_grid.grid_columnconfigure(0, weight=0, minsize=150)
    self.creator_campaign_summary_grid.grid_columnconfigure(1, weight=1)
    self._creator_campaign_summary_header_widgets = []
    self._creator_campaign_summary_rows = {}
    for column, text in enumerate(("Krok", "Stan")):
        header_cell = tk.Label(
            self.creator_campaign_summary_grid,
            text=text,
            font=("Segoe UI Semibold", 8),
            padx=9,
            pady=5,
            anchor="w",
            bd=0,
            highlightthickness=1,
            bg=summary_colors["header"],
            fg=summary_colors["accent"],
            highlightbackground=summary_colors["border"],
            highlightcolor=summary_colors["border"],
        )
        header_cell.grid(row=0, column=column, sticky="nsew")
        self._creator_campaign_summary_header_widgets.append(header_cell)
    for row_index, (key, label_text) in enumerate(
        (
            ("target", "Cel bramki"),
            ("source", "Materiał projektu"),
            ("material", "Dane wejściowe"),
            ("variant", "Wariant datasetu"),
        ),
        start=1,
    ):
        label_cell = tk.Label(
            self.creator_campaign_summary_grid,
            text=label_text,
            font=("Segoe UI", 8),
            padx=9,
            pady=5,
            anchor="w",
            bd=0,
            highlightthickness=1,
            bg=(summary_colors["row"] if row_index % 2 else summary_colors["row_alt"]),
            fg=summary_colors["muted"],
            highlightbackground=summary_colors["border"],
            highlightcolor=summary_colors["border"],
        )
        label_cell.grid(row=row_index, column=0, sticky="nsew")
        if key == "material":
            value_cell = tk.Frame(
                self.creator_campaign_summary_grid,
                padx=9,
                pady=4,
                bd=0,
                highlightthickness=1,
                bg=(summary_colors["row"] if row_index % 2 else summary_colors["row_alt"]),
                highlightbackground=summary_colors["border"],
                highlightcolor=summary_colors["border"],
            )
        else:
            value_cell = tk.Label(
                self.creator_campaign_summary_grid,
                text="-",
                font=("Segoe UI", 8),
                padx=9,
                pady=5,
                anchor="w",
                justify=tk.LEFT,
                bd=0,
                highlightthickness=1,
                bg=(summary_colors["row"] if row_index % 2 else summary_colors["row_alt"]),
                fg=summary_colors["fg"],
                highlightbackground=summary_colors["border"],
                highlightcolor=summary_colors["border"],
            )
        value_cell.grid(row=row_index, column=1, sticky="nsew")
        self._creator_campaign_summary_rows[key] = (label_cell, value_cell)

    self.creator_source_mode_var = tk.StringVar(value="xml")
    self.creator_source_mode_frame = ttk.LabelFrame(f, text=" Źródło datasetu ", padding=8)
    ttk.Label(
        self.creator_source_mode_frame,
        text="",
        justify=tk.LEFT,
        wraplength=700,
    )
    self.creator_source_ready_radio = ttk.Radiobutton(
        self.creator_source_mode_frame,
        text="Użyj gotowego splitu tablic",
        value="ready",
        variable=self.creator_source_mode_var,
        command=self._on_creator_source_mode_change,
    )
    self.creator_source_xml_radio = ttk.Radiobutton(
        self.creator_source_mode_frame,
        text="Utwórz split z anotacji XML i zdjęć",
        value="xml",
        variable=self.creator_source_mode_var,
        command=self._on_creator_source_mode_change,
    )

    self.creator_ready_dataset_lbl = ttk.Label(
        f,
        text="",
        justify=tk.LEFT,
        wraplength=720
    )

    row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
    self.creator_xml_row = row1
    ttk.Label(row1, text="Anotacje tablic XML:").pack(side=tk.LEFT)
    self.cvat_xml_var = tk.StringVar()
    self.cvat_xml_entry = ttk.Entry(row1, textvariable=self.cvat_xml_var)
    self.cvat_xml_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    self.btn_pick_cvat_xml = ttk.Button(
        row1,
        text="Wybierz plik",
        command=lambda: self._pick_file(
            self.cvat_xml_var,
            "*.xml",
            initialdir=self._get_plate_xml_picker_dir(),
        ),
    )
    self.btn_pick_cvat_xml.pack(side=tk.LEFT)

    self.creator_auto_match_hint_lbl = ttk.Label(
        f,
        text=(
            "Po wyborze XML program spróbuje dopasować katalog zdjęć po nazwach plików."
        ),
        justify=tk.LEFT,
        wraplength=720,
    )

    row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
    self.creator_images_row = row2
    ttk.Label(row2, text="Zdjęcia zgodne z XML:").pack(side=tk.LEFT)
    self.cvat_images_var = tk.StringVar()
    self.cvat_images_entry = ttk.Entry(row2, textvariable=self.cvat_images_var)
    self.cvat_images_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    self.btn_pick_cvat_images = ttk.Button(
        row2,
        text="Wybierz katalog",
        command=lambda: self._pick_dir(
            self.cvat_images_var,
            initialdir=self._get_plate_images_picker_dir(),
        ),
    )
    self.btn_pick_cvat_images.pack(side=tk.LEFT)

    self.creator_source_summary_lbl = ttk.Label(
        f,
        text="",
        justify=tk.LEFT,
        wraplength=720
    )

    row3 = ttk.Frame(f); row3.pack(fill=tk.X, pady=2)
    self.creator_output_row = row3
    ttk.Label(row3, text="Folder wariantu:").pack(side=tk.LEFT)
    # Ścieżka docelowa jest wyliczana automatycznie i pozostaje tylko do odczytu.
    self.ds_out_var = tk.StringVar(value=str(self._get_datasets_base_dir() / "Plates_CVAT_[DATA_I_CZAS]"))
    ttk.Entry(row3, textvariable=self.ds_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    creator_ratios = ttk.LabelFrame(f, text=" 2. Podział tworzonego wariantu ", padding=8)
    self.creator_ratios_frame = creator_ratios
    creator_ratios.pack(fill=tk.X, pady=(8, 6))
    ttk.Label(
        creator_ratios,
        text="Ustal proporcje wariantu: train uczy, val kontroluje, test zostaje do oceny.",
        justify=tk.LEFT,
        wraplength=700,
    ).grid(row=0, column=0, columnspan=3, sticky=tk.EW, pady=(0, 9))
    ttk.Label(creator_ratios, text="Train %").grid(row=1, column=0, sticky=tk.W, pady=2)
    ttk.Scale(
        creator_ratios,
        from_=50,
        to=90,
        variable=self.train_pct,
        command=lambda e: self._update_ratio_labels(),
    ).grid(row=1, column=1, sticky=tk.EW, padx=8, pady=2)
    self.creator_train_lbl = ttk.Label(creator_ratios, text="80%")
    self.creator_train_lbl.grid(row=1, column=2, sticky=tk.W, pady=2)

    ttk.Label(creator_ratios, text="Val %").grid(row=2, column=0, sticky=tk.W, pady=2)
    ttk.Scale(
        creator_ratios,
        from_=5,
        to=50,
        variable=self.val_pct,
        command=lambda e: self._update_ratio_labels(),
    ).grid(row=2, column=1, sticky=tk.EW, padx=8, pady=2)
    self.creator_val_lbl = ttk.Label(creator_ratios, text="10%")
    self.creator_val_lbl.grid(row=2, column=2, sticky=tk.W, pady=2)

    ttk.Label(creator_ratios, text="Test %").grid(row=3, column=0, sticky=tk.W, pady=2)
    ttk.Label(creator_ratios, text="liczony automatycznie").grid(row=3, column=1, sticky=tk.W, padx=8, pady=2)
    self.creator_test_lbl = ttk.Label(creator_ratios, text="Test: 10%")
    self.creator_test_lbl.grid(row=3, column=2, sticky=tk.W, pady=2)
    self.creator_split_bar = tk.Canvas(
        creator_ratios,
        height=26,
        bd=0,
        highlightthickness=0,
        bg=summary_colors["panel"],
    )
    self.creator_split_bar.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(11, 3))
    self.creator_split_bar.bind("<Configure>", lambda _event: self._update_ratio_labels(), add="+")
    self.creator_split_bar_legend = ttk.Label(
        creator_ratios,
        text="Podzia\u0142 zostanie zapisany w tworzonym wariancie datasetu.",
        justify=tk.LEFT,
        wraplength=700,
    )
    self.creator_split_bar_legend.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=(1, 0))
    creator_ratios.columnconfigure(1, weight=1)
    try:
        self._update_ratio_labels()
    except Exception:
        pass

    self._build_step4_augmentation_controls(f, target="plate")

    create_shell, create_inner, create_bg = _make_step4_action_shell(
        self,
        f,
        title="4. Utwórz wariant datasetu tablic",
        description=(
            "Zapisuje wariant gotowy do treningu modelu tablic."
        ),
    )
    self.btn_step4_create_frame = create_shell
    self.step4_creator_action_inner = create_inner
    self.btn_step4_create_frame.pack(fill=tk.X, pady=(12, 10))
    decision_bg = blend_hex_colors(summary_colors["accent"], create_bg, 0.82)
    self.creator_decision_summary_var = tk.StringVar(
        value="Train 80% | Val 10% | Test 10% | bez syntetycznego powi\u0119kszenia"
    )
    self.creator_decision_summary_frame = tk.Frame(
        create_inner,
        bg=summary_colors["border"],
        bd=0,
        highlightthickness=0,
        padx=1,
        pady=1,
    )
    self.creator_decision_summary_frame.pack(fill=tk.X, pady=(0, 10))
    decision_inner = tk.Frame(
        self.creator_decision_summary_frame,
        bg=decision_bg,
        bd=0,
        highlightthickness=0,
        padx=10,
        pady=8,
    )
    decision_inner.pack(fill=tk.X)
    tk.Label(
        decision_inner,
        text="Podsumowanie decyzji",
        bg=decision_bg,
        fg=summary_colors["accent"],
        font=("Segoe UI Semibold", 8),
        anchor="w",
        justify=tk.LEFT,
        bd=0,
        highlightthickness=0,
    ).pack(fill=tk.X)
    tk.Label(
        decision_inner,
        textvariable=self.creator_decision_summary_var,
        bg=decision_bg,
        fg=summary_colors["fg"],
        font=("Segoe UI Semibold", 10),
        anchor="w",
        justify=tk.LEFT,
        wraplength=700,
        bd=0,
        highlightthickness=0,
    ).pack(fill=tk.X, pady=(3, 0))
    create_button_row = tk.Frame(create_inner, bg=create_bg, bd=0, highlightthickness=0)
    create_button_row.pack(anchor=tk.W, fill=tk.X)

    self.btn_step4_create = ttk.Button(
        create_button_row,
        text="Utwórz split treningowy",
        command=self._create_dataset_thread,
        style="Accent.TButton",
    )
    self.btn_step4_create.pack(anchor=tk.W, fill=tk.X, ipady=2)
    self.btn_step4_create.configure(text="Utw\u00f3rz wariant datasetu tablic")
    try:
        self._refresh_step4_creator_decision_summary()
    except Exception:
        pass

    self.ds_progress_var = tk.DoubleVar(value=0.0)
    self.ds_progress = TrainProgressBar(
        create_inner,
        variable=self.ds_progress_var,
        maximum=100,
        thickness=6,
        trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
        fill_color=palette.get("success", "#2ecc71"),
        bg=palette.get("panel", "#252526"),
        height=10,
    )
    self.ds_progress.pack(fill=tk.X, pady=(10, 2))

    self.ds_status = ttk.Label(create_inner, text="Gotowy", style="TrainSplitSuccess.TLabel")
    self.ds_status.pack(anchor=tk.W)
    self._style_training_success_label(self.ds_status)

    try:
        self.cvat_xml_var.trace_add("write", lambda *_args: self._on_cvat_xml_source_changed())
        self.cvat_images_var.trace_add("write", lambda *_args: self._on_cvat_images_source_changed())
    except Exception:
        pass
    self._refresh_dataset_creator_cta_state()

    # Powiązania pomocy dla budowy datasetu z CVAT.
    HELP.bind_help(row1, "tr_cvat_xml")
    HELP.bind_help(self.creator_source_mode_frame, "tr_cvat_source_mode")
    HELP.bind_help(self.creator_source_ready_radio, "tr_cvat_source_mode")
    HELP.bind_help(self.creator_source_xml_radio, "tr_cvat_source_mode")
    HELP.bind_help(self.btn_pick_cvat_xml, "tr_cvat_xml")
    HELP.bind_help(self.creator_auto_match_hint_lbl, "tr_cvat_img")
    HELP.bind_help(row2, "tr_cvat_img")
    HELP.bind_help(self.btn_pick_cvat_images, "tr_cvat_img")
    HELP.bind_help(self.creator_source_summary_lbl, "tr_cvat_source_mode")
    HELP.bind_help(creator_ratios, "tr_split_ratios")
    HELP.bind_help(self.btn_step4_create, "tr_cvat_btn")

def _build_splitter_ui(self):
    f = self.ds_split_frame
    palette = getattr(self.app, "palette", {})
    self.split_intro_lbl = ttk.Label(
        f,
        text=(
            "Wskaż źródło, ustaw split i utwórz wariant do treningu modelu znaków."
        ),
        font=("Segoe UI", 9),
        wraplength=720,
        justify=tk.LEFT,
    )
    self.split_intro_lbl.pack(anchor=tk.W, pady=(0, 10))

    self._step4_char_split_details_visible = False
    self.btn_step4_split_toggle = ttk.Button(
        f,
        text="Popraw split",
        command=self._toggle_step4_char_split_details,
        style="WorkflowCard.TButton"
    )

    self.split_source_hint_lbl = ttk.Label(
        f,
        text="",
        justify=tk.LEFT,
        wraplength=720,
    )

    row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
    self.split_source_row = row1
    ttk.Label(row1, text="Dataset znaków:").pack(side=tk.LEFT)
    self.split_src_var = tk.StringVar()
    self.split_src_entry = ttk.Entry(row1, textvariable=self.split_src_var)
    self.split_src_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    self.btn_pick_split_src = ttk.Button(
        row1,
        text="Wybierz katalog",
        command=self._pick_char_split_source_dir,
    )
    self.btn_pick_split_src.pack(side=tk.LEFT)
    self.btn_pick_split_yaml = ttk.Button(
        row1,
        text="Wybierz data.yaml",
        command=self._pick_char_split_source_yaml,
    )
    self.btn_pick_split_yaml.pack(side=tk.LEFT, padx=(6, 0))

    self.split_source_summary_lbl = ttk.Label(
        f,
        text="",
        justify=tk.LEFT,
        wraplength=720
    )

    row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
    self.split_output_row = row2
    ttk.Label(row2, text="Folder wariantu:").pack(side=tk.LEFT)
    # Ścieżka wariantu splitu jest wyliczana automatycznie i pozostaje tylko do odczytu.
    self.split_out_var = tk.StringVar(value=str(self._get_datasets_base_dir() / "[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]"))
    ttk.Entry(row2, textvariable=self.split_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    ratios = ttk.LabelFrame(f, text=" Split train / val / test ", padding=8)
    ratios.pack(fill=tk.X, pady=(8, 6))
    self.split_ratios_frame = ratios
    ttk.Label(ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
    ttk.Scale(ratios, from_=50, to=90, variable=self.train_pct, command=lambda e: self._update_ratio_labels()).grid(row=0, column=1, sticky=tk.EW, padx=5)
    self.train_lbl = ttk.Label(ratios, text="80%"); self.train_lbl.grid(row=0, column=2, sticky=tk.W)

    ttk.Label(ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
    ttk.Scale(ratios, from_=5, to=50, variable=self.val_pct, command=lambda e: self._update_ratio_labels()).grid(row=1, column=1, sticky=tk.EW, padx=5)
    self.val_lbl = ttk.Label(ratios, text="10%"); self.val_lbl.grid(row=1, column=2, sticky=tk.W)

    ttk.Label(ratios, text="Test %").grid(row=2, column=0, sticky=tk.W)
    ttk.Label(ratios, text="liczony automatycznie").grid(row=2, column=1, sticky=tk.W, padx=5)
    self.test_lbl = ttk.Label(ratios, text="Test: 10%"); self.test_lbl.grid(row=2, column=2, sticky=tk.W)
    ratios.columnconfigure(1, weight=1)

    self._build_step4_augmentation_controls(f, target="char")

    split_shell, split_inner, split_bg = _make_step4_action_shell(
        self,
        f,
        title="Budowa wariantu datasetu znaków",
        description=(
            "Tworzy wariant train / val / test dla YOLO Detect."
        ),
    )
    self.btn_step4_split_frame = split_shell
    self.step4_split_action_inner = split_inner
    self.btn_step4_split_frame.pack(fill=tk.X, pady=(12, 10))
    split_button_row = tk.Frame(split_inner, bg=split_bg, bd=0, highlightthickness=0)
    split_button_row.pack(anchor=tk.W, fill=tk.X)

    self.btn_step4_split = ttk.Button(
        split_button_row,
        text="Utwórz split treningowy",
        command=self._split_dataset_thread,
        style="Accent.TButton"
    )
    self.btn_step4_split.pack()

    self.split_progress_var = tk.DoubleVar(value=0.0)
    self.split_feedback_frame = tk.Frame(split_inner, bg=split_bg, bd=0, highlightthickness=0)
    self.split_progress = TrainProgressBar(
        self.split_feedback_frame,
        variable=self.split_progress_var,
        maximum=100,
        thickness=6,
        trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
        fill_color=palette.get("success", "#2ecc71"),
        bg=palette.get("panel", "#252526"),
        height=10,
    )
    self.split_progress.pack(fill=tk.X, pady=2)
    self.split_status = ttk.Label(self.split_feedback_frame, text="Gotowy")
    self.split_status.pack(anchor=tk.W)
    self._set_split_feedback_visibility(False)
    try:
        self.split_src_var.trace_add("write", lambda *_args: self._refresh_dataset_split_cta_state())
    except Exception:
        pass
    self._refresh_dataset_split_cta_state()

    # Powiązania pomocy dla splitu datasetu.
    HELP.bind_help(row1, "tr_split_src")
    HELP.bind_help(self.split_intro_lbl, "tr_split_src")
    HELP.bind_help(self.split_source_hint_lbl, "tr_split_src")
    HELP.bind_help(self.btn_pick_split_src, "tr_split_src")
    HELP.bind_help(self.btn_pick_split_yaml, "tr_split_src")
    HELP.bind_help(self.split_source_summary_lbl, "tr_split_src")
    HELP.bind_help(ratios, "tr_split_ratios")
    HELP.bind_help(self.btn_step4_split_toggle, "tr_split_ratios")
    HELP.bind_help(self.btn_step4_split, "tr_split_btn")
    self._update_ratio_labels()
    self._configure_train_progress_styles()
