#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z4 validation panel helpers extracted from tab_training.py."""

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
from . import z4_dataset_panels
from .z4_view_models import (
    Step4CampaignNavigationViewModel,
    Step4DatasetWorkflowViewModel,
    Step4TrainingInputsViewModel,
)

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageFont

YOLO = None


def _format_validation_metric_name(raw_name: str) -> str:
    raw = str(raw_name or "").strip()
    mapping = {
        "metrics/precision(B)": "Precision (boxy)",
        "metrics/recall(B)": "Recall (boxy)",
        "metrics/mAP50(B)": "mAP50 (boxy)",
        "metrics/mAP50-95(B)": "mAP50-95 (boxy)",
        "metrics/precision(P)": "Precision (punkty)",
        "metrics/recall(P)": "Recall (punkty)",
        "metrics/mAP50(P)": "mAP50 (punkty)",
        "metrics/mAP50-95(P)": "mAP50-95 (punkty)",
        "fitness": "Fitness",
    }
    if raw in mapping:
        return mapping[raw]

    pretty = raw.replace("metrics/", "").replace("(B)", " (boxy)").replace("(P)", " (punkty)")
    pretty = pretty.replace("_", " ")
    return pretty or "Metryka"

def _format_validation_metric_value(value) -> str:
    try:
        return f"{float(value):.4f}"
    except Exception:
        return str(value)

def _build_validation_panel_v2(self, parent):
    shell = ttk.Frame(parent, padding=10, style="Panel.TFrame")
    shell.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        shell,
        text=(
            "Walidacja służy do szybkiego sprawdzenia wytrenowanego modelu na wybranym splicie. "
            "Po uruchomieniu zobaczysz czytelną tabelę metryk, a pełny log nadal trafi do wspólnego terminala procesu."
        ),
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=760,
    ).pack(anchor=tk.W, fill=tk.X, pady=(0, 12))

    form_box = ttk.LabelFrame(shell, text=" Konfiguracja walidacji ", padding=10)
    form_box.pack(fill=tk.X)

    self.val_model_var = tk.StringVar()
    row1 = ttk.Frame(form_box, style="Panel.TFrame")
    row1.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(row1, text="Wytrenowany model (.pt):", style="Panel.TLabel").pack(anchor=tk.W, fill=tk.X)
    row1_input = ttk.Frame(row1, style="Panel.TFrame")
    row1_input.pack(fill=tk.X, pady=(4, 0))
    ttk.Entry(row1_input, textvariable=self.val_model_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Button(
        row1_input,
        text="Wybierz",
        command=lambda: self._pick_file(
            self.val_model_var,
            "*.pt",
            initialdir=self._get_validation_model_picker_dir(),
        ),
    ).pack(side=tk.LEFT, padx=(8, 0))

    self.val_data_var = tk.StringVar()
    row2 = ttk.Frame(form_box, style="Panel.TFrame")
    row2.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(row2, text="Dataset testowy (folder lub data.yaml):", style="Panel.TLabel").pack(anchor=tk.W, fill=tk.X)
    row2_input = ttk.Frame(row2, style="Panel.TFrame")
    row2_input.pack(fill=tk.X, pady=(4, 0))
    ttk.Entry(row2_input, textvariable=self.val_data_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Button(
        row2_input,
        text="Wybierz",
        command=lambda: self._pick_dir(
            self.val_data_var,
            initialdir=self._get_validation_dataset_picker_dir(),
        ),
    ).pack(side=tk.LEFT, padx=(8, 0))

    split_row = ttk.Frame(form_box, style="Panel.TFrame")
    split_row.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(split_row, text="Sprawdzany split:", style="Panel.TLabel").pack(side=tk.LEFT)
    self.val_split_var = tk.StringVar(value="val")
    split_combo = ttk.Combobox(
        split_row,
        textvariable=self.val_split_var,
        values=["val", "test", "train"],
        state="readonly",
        width=12,
    )
    split_combo.pack(side=tk.LEFT, padx=(8, 0))

    action_row = ttk.Frame(form_box, style="Panel.TFrame")
    action_row.pack(fill=tk.X, pady=(10, 0))
    self.btn_run_val = ttk.Button(
        action_row,
        text="Uruchom walidację",
        style="Accent.TButton",
        command=self._run_validation,
    )
    self.btn_run_val.pack(side=tk.LEFT)
    self.val_status = ttk.Label(action_row, text="Gotowy", style="PanelMuted.TLabel")
    self.val_status.pack(side=tk.LEFT, padx=(10, 0))

    ttk.Label(
        form_box,
        text="Walidacja korzysta z globalnego ustawienia urządzenia i nie wymaga dodatkowego wyboru w Z4.",
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=720,
    ).pack(anchor=tk.W, fill=tk.X, pady=(10, 0))

    HELP.bind_help(row1_input, "tr_val_model")
    HELP.bind_help(row2_input, "tr_val_data")
    HELP.bind_help(self.btn_run_val, "tr_val_btn")
    HELP.bind_help(split_combo, "tr_val_split")

    summary_box = ttk.LabelFrame(shell, text=" Ostatni wynik walidacji ", padding=10)
    summary_box.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

    self.val_summary_title_var = tk.StringVar(
        value="Po uruchomieniu walidacji najważniejsze metryki pojawią się tutaj."
    )
    self.val_summary_note_var = tk.StringVar(
        value="Tabela pokazuje wynik i jego orientacyjną ocenę, żeby łatwiej porównywać modele."
    )
    ttk.Label(
        summary_box,
        textvariable=self.val_summary_title_var,
        style="Panel.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=760,
    ).pack(anchor=tk.W, fill=tk.X)
    ttk.Label(
        summary_box,
        textvariable=self.val_summary_note_var,
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=760,
    ).pack(anchor=tk.W, fill=tk.X, pady=(4, 8))

    self.val_metrics_tree = self._create_metric_table(
        summary_box,
        [
            ("Metryka", 220, tk.W),
            ("Wartosc", 90, tk.CENTER),
            ("Ocena", 110, tk.CENTER),
            ("Zakres", 120, tk.CENTER),
        ],
        height=9,
    )
    self._set_validation_summary(
        "Po uruchomieniu walidacji najważniejsze metryki pojawią się tutaj.",
        [],
        "Tabela pokazuje wynik i jego orientacyjną ocenę, żeby łatwiej porównywać modele.",
    )

def _format_validation_metric_band(self, raw_name: str, value) -> tuple[str, str]:
    raw = str(raw_name or "").strip().lower()
    if "map50-95" in raw:
        return self._format_training_metric_band("map50_95", value)
    if "map50" in raw:
        return self._format_training_metric_band("map50", value)
    if "precision" in raw:
        return self._format_training_metric_band("precision", value)
    if "recall" in raw:
        return self._format_training_metric_band("recall", value)
    if "fitness" in raw:
        return "monitoruj", "syntetyczna"
    return "-", "-"

def _extract_validation_metric_rows(self, metrics) -> list[tuple[str, str, str, str]]:
    preferred_order = [
        "metrics/precision(B)",
        "metrics/recall(B)",
        "metrics/mAP50(B)",
        "metrics/mAP50-95(B)",
        "metrics/precision(P)",
        "metrics/recall(P)",
        "metrics/mAP50(P)",
        "metrics/mAP50-95(P)",
        "fitness",
    ]

    results_dict = getattr(metrics, "results_dict", None)
    if isinstance(results_dict, dict) and results_dict:
        ordered_keys = [key for key in preferred_order if key in results_dict]
        ordered_keys.extend(key for key in results_dict.keys() if key not in ordered_keys)
        rows: list[tuple[str, str, str, str]] = []
        for key in ordered_keys:
            band, range_text = self._format_validation_metric_band(key, results_dict.get(key))
            rows.append(
                (
                    self._format_validation_metric_name(key),
                    self._format_validation_metric_value(results_dict.get(key)),
                    band,
                    range_text,
                )
            )
        return rows

    rows: list[tuple[str, str, str, str]] = []
    if hasattr(metrics, "box"):
        box_rows = [
            ("mAP50 (boxy)", getattr(metrics.box, "map50", 0)),
            ("mAP50-95 (boxy)", getattr(metrics.box, "map", 0)),
            ("Precision (boxy)", getattr(metrics.box, "mp", 0)),
            ("Recall (boxy)", getattr(metrics.box, "mr", 0)),
        ]
        for name, value in box_rows:
            band, range_text = self._format_validation_metric_band(name, value)
            rows.append((name, self._format_validation_metric_value(value), band, range_text))
    if hasattr(metrics, "pose"):
        pose_rows = [
            ("mAP50 (punkty)", getattr(metrics.pose, "map50", 0)),
            ("mAP50-95 (punkty)", getattr(metrics.pose, "map", 0)),
        ]
        for name, value in pose_rows:
            band, range_text = self._format_validation_metric_band(name, value)
            rows.append((name, self._format_validation_metric_value(value), band, range_text))
    return rows

def _set_validation_summary(
    self,
    title: str,
    rows: list[tuple[str, str, str, str]] | None = None,
    note: str = "",
):
    title_var = getattr(self, "val_summary_title_var", None)
    if title_var is not None:
        try:
            title_var.set(str(title))
        except Exception:
            pass

    note_var = getattr(self, "val_summary_note_var", None)
    if note_var is not None:
        try:
            note_var.set(str(note or "").strip())
        except Exception:
            pass

    self._set_metric_table_rows(getattr(self, "val_metrics_tree", None), rows or [])
