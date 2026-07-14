#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z4 trained model export helpers extracted from tab_training.py."""

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
from ..validators import validate_model_file, format_yolo_model_identity, write_model_metadata_sidecar
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..ranking import ModelRanking
from ..utils import cleanup_gpu_memory, safe_load_yaml, get_image_files
from .help_manager import HELP
from .inertial_scroll import InertialScrollController
from .section_header_label import SectionHeaderLabel
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors
from .zoomable_canvas import ZoomableCanvas
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
from .z4_view_models import (
    Step4CampaignNavigationViewModel,
    Step4DatasetWorkflowViewModel,
    Step4TrainingInputsViewModel,
)

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageFont

YOLO = None


def _infer_history_run_target(self, run) -> str:
    target = ""
    try:
        infer_target = getattr(self.history, "_infer_run_target", None)
        if callable(infer_target):
            target = str(infer_target(run) or "").strip().lower()
    except Exception:
        target = ""

    if target not in {"plate", "char", "vehicle"}:
        try:
            target = str(self._infer_dataset_target(getattr(run, "dataset_path", "")) or "").strip().lower()
        except Exception:
            target = ""

    if target not in {"plate", "char", "vehicle"}:
        try:
            merged = " ".join(
                str(value or "")
                for value in (
                    getattr(run, "dataset_path", ""),
                    getattr(run, "base_model", ""),
                    getattr(run, "name", ""),
                    getattr(run, "output_dir", ""),
                )
            )
            infer_from_text = getattr(TrainingHistory, "_infer_target_from_text", None)
            if callable(infer_from_text):
                target = str(infer_from_text(merged) or "").strip().lower()
        except Exception:
            target = ""

    return target if target in {"plate", "char", "vehicle"} else ""

def _resolve_history_run_best_weights(self, run) -> Path | None:
    if run is None:
        return None
    status_value = str(getattr(run, "status", "") or "").strip().lower()
    if status_value != TrainingStatus.COMPLETED.value:
        return None

    for raw_path in (
        getattr(run, "best_weights", ""),
        Path(str(getattr(run, "output_dir", "") or "")) / "train" / "weights" / "best.pt",
    ):
        text = str(raw_path or "").strip()
        if not text:
            continue
        try:
            candidate = Path(text)
        except Exception:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate

    try:
        return self._find_best_weights_for_run(str(getattr(run, "id", "") or "").strip())
    except Exception:
        return None

def _build_history_run_metric_summary(self, run) -> dict:
    rows = list(getattr(run, "metrics_history", []) or [])
    latest = dict(rows[-1]) if rows and isinstance(rows[-1], dict) else {}
    best_row: dict = {}
    best_score = -1.0

    for row in rows:
        if not isinstance(row, dict):
            continue
        score = self._training_metric_value(
            row,
            (
                "map50_95",
                "box_map50_95",
                "metrics/mAP50-95(B)",
                "metrics/mAP50-95",
                "pose_map50_95",
                "metrics/mAP50-95(P)",
            ),
        )
        if score is None:
            score = self._training_metric_value(
                row,
                (
                    "map50",
                    "box_map50",
                    "metrics/mAP50(B)",
                    "metrics/mAP50",
                    "pose_map50",
                    "metrics/mAP50(P)",
                ),
            )
        if score is not None and score > best_score:
            best_score = score
            best_row = dict(row)

    best_map50 = self._training_metric_float(getattr(run, "best_map50", None))
    best_map50_95 = self._training_metric_float(getattr(run, "best_map50_95", None))
    if best_map50 is None:
        best_map50 = self._training_metric_value(best_row, ("map50", "box_map50", "metrics/mAP50(B)", "metrics/mAP50", "pose_map50", "metrics/mAP50(P)"))
    if best_map50_95 is None:
        best_map50_95 = self._training_metric_value(
            best_row,
            ("map50_95", "box_map50_95", "metrics/mAP50-95(B)", "metrics/mAP50-95", "pose_map50_95", "metrics/mAP50-95(P)"),
        )

    epoch = self._training_metric_value(best_row, ("epoch", "Epoch"))
    if epoch is None:
        epoch = self._training_metric_float(getattr(run, "current_epoch", None))

    return {
        "best_map50": best_map50,
        "best_map50_95": best_map50_95,
        "best_epoch": epoch,
        "latest": latest,
        "best_row": best_row,
        "history_rows": rows,
    }

def _build_free_mode_model_export_path(self, run, target: str, target_dir: Path, source_path: Path) -> Path:
    prefix = {
        "plate": "pose",
        "char": "char",
        "vehicle": "vehicle",
    }.get(target, "model")
    run_name = self._safe_model_export_slug(getattr(run, "name", "") or getattr(run, "id", ""), fallback=prefix)
    run_id = self._safe_model_export_slug(getattr(run, "id", ""), fallback=datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    metric_summary = self._build_history_run_metric_summary(run)
    metric_value = metric_summary.get("best_map50_95")
    if metric_value is None:
        metric_value = metric_summary.get("best_map50")
    metric_tag = ""
    if metric_value is not None:
        try:
            clamped = max(0.0, min(1.0, float(metric_value)))
            metric_tag = f"_map{int(round(clamped * 100)):03d}"
        except Exception:
            metric_tag = ""
    suffix = source_path.suffix if source_path.suffix else ".pt"
    return target_dir / f"{prefix}_{run_name}_{run_id}{metric_tag}{suffix}"

def _build_exported_model_metadata(self, run, target: str, source_path: Path, destination_path: Path) -> dict:
    metric_summary = self._build_history_run_metric_summary(run)
    run_dict = {}
    try:
        if hasattr(run, "to_dict"):
            run_dict = run.to_dict()
    except Exception:
        run_dict = {}
    if not run_dict:
        run_dict = {
            key: getattr(run, key, None)
            for key in (
                "id",
                "name",
                "created_at",
                "status",
                "dataset_path",
                "base_model",
                "epochs",
                "batch_size",
                "img_size",
                "device",
                "lr0",
                "current_epoch",
                "best_map50",
                "best_map50_95",
                "output_dir",
                "best_weights",
                "last_weights",
                "started_at",
                "finished_at",
                "paused_at",
                "metrics_history",
                "error_message",
                "report_html",
                "plots_dir",
            )
        }

    validation_ok = False
    validation_message = ""
    model_info = {}
    identity = ""
    try:
        validation_ok, validation_message, model_info = validate_model_file(destination_path)
        identity = format_yolo_model_identity(model_info, include_ultralytics_version=True)
    except Exception as e:
        validation_message = str(e)
        model_info = {}

    return self._json_safe_training_value(
        {
            "schema": "auto_annotation_tool.exported_model.v1",
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "exported_for": "free_mode",
            "target": target,
            "target_label": self._format_training_target_label(target),
            "model": {
                "file_name": destination_path.name,
                "path": str(destination_path),
                "directory": str(destination_path.parent),
                "identity": identity,
                "validation_ok": validation_ok,
                "validation_message": validation_message,
                "info": model_info,
            },
            "source": {
                "best_weights": str(source_path),
                "run_output_dir": str(getattr(run, "output_dir", "") or ""),
                "training_history_dir": str(getattr(getattr(self, "history", None), "history_dir", "") or ""),
            },
            "training": {
                "run_id": str(getattr(run, "id", "") or ""),
                "run_name": str(getattr(run, "name", "") or ""),
                "status": str(getattr(run, "status", "") or ""),
                "created_at": str(getattr(run, "created_at", "") or ""),
                "started_at": str(getattr(run, "started_at", "") or ""),
                "finished_at": str(getattr(run, "finished_at", "") or ""),
                "dataset_path": str(getattr(run, "dataset_path", "") or ""),
                "base_model": str(getattr(run, "base_model", "") or ""),
                "epochs": getattr(run, "epochs", None),
                "current_epoch": getattr(run, "current_epoch", None),
                "batch_size": getattr(run, "batch_size", None),
                "img_size": getattr(run, "img_size", None),
                "device": str(getattr(run, "device", "") or ""),
                "lr0": getattr(run, "lr0", None),
                "report_html": str(getattr(run, "report_html", "") or ""),
                "plots_dir": str(getattr(run, "plots_dir", "") or ""),
            },
            "metrics": {
                "best_map50": metric_summary.get("best_map50"),
                "best_map50_95": metric_summary.get("best_map50_95"),
                "best_epoch": metric_summary.get("best_epoch"),
                "latest": metric_summary.get("latest") or {},
                "best_row": metric_summary.get("best_row") or {},
            },
            "run_snapshot": run_dict,
        }
    )

def _export_selected_run_model_to_free_mode(self):
    run = self._selected_run()
    if run is None:
        return messagebox.showwarning(
            "Brak runu",
            "Najpierw wybierz run treningu z historii."
        )

    target = self._infer_history_run_target(run)
    if target not in {"plate", "char", "vehicle"}:
        return messagebox.showerror(
            "Nie rozpoznano toru",
            "Nie mogę jednoznacznie ustalić, czy wybrany run dotyczy tablic, znaków czy pojazdów.\n\n"
            "Eksport do modeli trybu swobodnego jest dostępny tylko dla rozpoznanych runów YOLO."
        )

    best_weights = self._resolve_history_run_best_weights(run)
    if best_weights is None:
        return messagebox.showerror(
            "Brak best.pt",
            "Wybrany run nie ma dostępnego pliku best.pt.\n\n"
            "Eksport jest możliwy dopiero po treningu, który zapisał najlepsze wagi modelu."
        )

    try:
        target_dir = Path(CONFIG.get_trained_models_dir(target))
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.exception("Nie udało się przygotować katalogu eksportu modelu")
        return messagebox.showerror(
            "Błąd katalogu eksportu",
            f"Nie udało się przygotować katalogu modeli trybu swobodnego:\n{e}"
        )

    destination = self._build_free_mode_model_export_path(run, target, target_dir, best_weights)
    metadata_path = destination.with_suffix(".json")

    if destination.exists() or metadata_path.exists():
        overwrite = messagebox.askyesno(
            "Model już istnieje",
            "W katalogu modeli trybu swobodnego istnieje już eksport dla tego runu.\n\n"
            f"Model: {destination.name}\n"
            f"Parametry: {metadata_path.name}\n\n"
            "Nadpisać te pliki?"
        )
        if not overwrite:
            return

    try:
        shutil.copy2(best_weights, destination)
        metadata = self._build_exported_model_metadata(run, target, best_weights, destination)
        with metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, ensure_ascii=False)
        model_meta = metadata.get("model") if isinstance(metadata.get("model"), dict) else {}
        write_model_metadata_sidecar(
            destination,
            model_meta.get("info") if isinstance(model_meta.get("info"), dict) else {},
            validation_ok=bool(model_meta.get("validation_ok", True)),
            validation_message=str(model_meta.get("validation_message") or ""),
            extra={
                "exported_metadata_path": str(metadata_path),
                "target": target,
                "metrics": metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {},
                "training": metadata.get("training") if isinstance(metadata.get("training"), dict) else {},
            },
        )
    except Exception as e:
        logger.exception("Nie udało się wyeksportować modelu do trybu swobodnego")
        return messagebox.showerror(
            "Błąd eksportu modelu",
            f"Nie udało się wyeksportować modelu:\n{e}"
        )

    try:
        self._append_train_log(
            f"[EXPORT] best.pt wyeksportowany do modeli trybu swobodnego: {destination}"
        )
    except Exception:
        pass

    return messagebox.showinfo(
        "Model wyeksportowany",
        "Model jest teraz dostępny w trybie swobodnym.\n\n"
        f"Tor: {self._format_training_target_label(target)}\n"
        f"Model: {destination}\n"
        f"Parametry: {metadata_path}"
    )
