#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extracted Z2 workflow/state methods for AnnotationTab.

This module intentionally keeps methods as plain functions receiving ``self``.
The owning class delegates to them, which physically reduces tab_annotation.py
without changing the state model or the public method names used by callbacks.
"""

import copy
import csv
import datetime
import json
import logging
import math
import os
import queue
import re
import shutil
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageTk

from ..annotators.runtime_factory import (
    create_combined_plate_annotator,
    create_plate_annotator,
    create_vehicle_annotator,
)
from ..campaign_manager import CAMPAIGN
from ..config import AVAILABLE_DETECT_MODELS, CONFIG, SESSION, YOLO_AVAILABLE, logger
from ..data_models import AnnotationReport, AnnotationStatus, Detection, ImageAnnotation
from ..exporters import CVATExporter, ReportGenerator
from ..icons import IconManager
from ..project_cache import PROJECT_CACHE
from ..quality_metrics import compute_plate_polygon_fit_metrics
from ..rectification.polygon_validator import PolygonValidator
from ..training import DatasetCreator
from ..utils import cleanup_gpu_memory, count_images_in_directory, format_duration, get_image_files, get_image_size
from ..validators import format_yolo_model_identity, validate_model_file
from .canvas_progress_overlay import CanvasProgressOverlay
from .help_manager import HELP
from .inertial_scroll import InertialScrollController
from .section_header_label import SectionHeaderLabel
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors
from .z2_actions import Z2ActionContext, build_z2_primary_actions, build_z2_secondary_actions
from .z2_campaign_flow import (
    apply_campaign_step2_workflow_preset,
    build_z2_cta_state_campaign,
    build_z2_layout_state_campaign,
    build_z2_left_panel_copy_payload_campaign,
    open_campaign_step2_entry as dispatch_open_campaign_step2_entry,
    open_existing_run_for_campaign_review,
    prepare_campaign_workflow_runtime,
)
from .z2_flow_models import Z2CopyPayload, Z2LeftPanelCopyContext
from .z2_free_mode_flow import (
    AUTO_REVIEW_FOLLOWUP_TEXT,
    AUTO_REVIEW_FOLLOWUP_TITLE,
    MANUAL_REVIEW_FOLLOWUP_TEXT,
    MANUAL_REVIEW_FOLLOWUP_TITLE,
    build_z2_cta_state_free_mode,
    build_z2_layout_state_free_mode,
    build_z2_left_panel_copy_payload_free_mode,
    get_manual_review_history_display_entries as dispatch_get_manual_review_history_display_entries,
    jump_to_export_section as dispatch_jump_to_export_section,
    open_existing_run_for_manual_review as dispatch_open_existing_run_for_manual_review,
    prepare_free_mode_workflow_runtime,
    refresh_manual_review_history_ui as dispatch_refresh_manual_review_history_ui,
    remember_manual_review_run as dispatch_remember_manual_review_run,
    select_free_mode_route,
    set_manual_entry_mode as dispatch_set_manual_entry_mode,
)
from .z2_shared_ui import (
    apply_z2_workflow_cta_ui as dispatch_apply_z2_workflow_cta_ui,
    apply_z2_workflow_left_layout as dispatch_apply_z2_workflow_left_layout,
    build_z2_workflow_base_context as dispatch_build_z2_workflow_base_context,
    refresh_workflow_route_cards as dispatch_refresh_workflow_route_cards,
)
from .z2_view_models import Step2CtaViewModel, Step2ViewModel
from .zoomable_canvas import ZoomableCanvas
from .z2_campaign_runtime import (
    _build_campaign_char_effective_source,
    _get_campaign_auto_annotation_bootstrap,
    _collect_campaign_auto_annotation_sources,
    _schedule_deferred_campaign_route_cleanup,
    get_campaign_step2_source_state,
    _get_campaign_step3_preview_source_context,
    _build_campaign_plate_approved_entries_from_run,
    reset_campaign_iteration_route_state,
    _sync_campaign_iteration_artifact_registry,
    _build_campaign_plate_approved_preview_bundle,
    _build_campaign_plate_approved_export_source,
    _prepare_approved_step3_source_from_z2_run,
    _promote_campaign_char_repair_ok_to_approved_pool_before_return,
    _reset_campaign_runtime_state,
    _build_campaign_z2_gate_overlay_state,
    _apply_campaign_plate_auto_model_choice,
)
from .z2_restore_workflow import (
    _restore_preview_from_annotation_run,
    _apply_campaign_project_snapshot,
    _apply_annotation_run_restore_payload,
    _ensure_free_mode_input_workspace_preview,
    _restore_preview_from_session_run,
    _apply_free_mode_session_snapshot,
    _prepare_campaign_source_preview_payload,
    _apply_campaign_source_preview_payload,
    _prepare_annotation_run_restore_payload,
)
from .z2_export_workflow import (
    _start_plate_dataset_export,
    _prompt_z2_export_choice,
    _start_plate_annotation_package_export,
    _prompt_plate_annotation_package_export_options,
    _refresh_plate_dataset_export_sources,
)

NAV_BUTTON_WIDTH = 18
YOLO = None


def _format_t06_signed_count(value: int, singular: str, plural: str) -> str:
    safe_value = int(value or 0)
    sign = "+" if safe_value > 0 else ""
    label = singular if abs(safe_value) == 1 else plural
    return f"{sign}{safe_value} {label}"


def _format_t06_signed_pair(images: int, plates: int) -> str:
    return (
        f"{_format_t06_signed_count(images, 'obraz [OK]', 'obrazów [OK]')} / "
        f"{_format_t06_signed_count(plates, 'tablica', 'tablic')}"
    )


T06_STATUS_OPEN = "OTWARTA"
T06_STATUS_CLOSED = "ZAMKNIĘTA"
T06_LABEL_STATUS = "Status T06"
T06_LABEL_SOURCE = "Już przekazane do puli YOLO"
T06_LABEL_SESSION = "Czeka na przekazanie"
T06_LABEL_TOTAL = "Po przekazaniu do grafu"
T06_LABEL_MISSING = "Do otwarcia bramki brakuje"
T06_LABEL_QUALITY = "Jakość źródła tablic"
T06_DEFAULT_QUALITY = "SŁABY"
T06_TOP_QUALITY_TEXT = "Osiągnięto najwyższy próg jakości"


def _build_t06_counter_rows(
    required_plates: int,
    source_images: int,
    source_plates: int,
    session_images: int,
    session_plates: int,
    total_images: int,
    total_plates: int,
) -> list[tuple[str, str, str]]:
    missing_open = max(0, int(required_plates or 0) - int(total_plates or 0))
    ready = bool(int(total_plates or 0) >= int(required_plates or 0))
    quality_info = CONFIG.describe_yolo_pose_dataset_quality(int(total_plates or 0))
    quality_label = str(quality_info.get("label", T06_DEFAULT_QUALITY) or T06_DEFAULT_QUALITY)
    quality_tone = str(quality_info.get("tone", "error") or "error").strip().lower()
    next_quality_label = str(quality_info.get("next_label", "") or "").strip()
    missing_next_quality = max(0, int(quality_info.get("missing_next", 0) or 0))
    if missing_open > 0:
        missing_label = T06_LABEL_MISSING
        missing_text = f"{missing_open} tablic zatwierdzonych [OK]"
        missing_tone = "warning"
    elif missing_next_quality > 0 and next_quality_label:
        missing_label = f"Do progu {next_quality_label} brakuje"
        missing_text = f"{missing_next_quality} tablic zatwierdzonych [OK]"
        missing_tone = "warning"
    else:
        missing_label = "Progi jakości"
        missing_text = T06_TOP_QUALITY_TEXT
        missing_tone = "success"
    delta_tone = "success" if session_images > 0 or session_plates > 0 else (
        "warning" if session_images < 0 or session_plates < 0 else "muted"
    )
    return [
        (T06_LABEL_STATUS, T06_STATUS_OPEN if ready else T06_STATUS_CLOSED, "success" if ready else "warning"),
        (
            T06_LABEL_SOURCE,
            f"{int(source_images or 0)} obrazów [OK] / {int(source_plates or 0)} tablic",
            "success" if int(source_plates or 0) > 0 else "muted",
        ),
        (
            T06_LABEL_SESSION,
            _format_t06_signed_pair(int(session_images or 0), int(session_plates or 0)),
            delta_tone,
        ),
        (
            T06_LABEL_TOTAL,
            f"{int(total_images or 0)} obrazów [OK] / {int(total_plates or 0)} tablic",
            "success" if ready else "warning",
        ),
        (missing_label, missing_text, missing_tone),
        (T06_LABEL_QUALITY, quality_label, quality_tone),
    ]


def _build_t06_rows_from_campaign_state(required_plates: int) -> list[tuple[str, str, str]] | None:
    try:
        CAMPAIGN.invalidate_step3_char_source_state_cache()
    except Exception:
        pass
    try:
        char_state = dict(CAMPAIGN.get_step3_char_source_state() or {})
    except Exception:
        char_state = {}
    if not char_state:
        return None
    try:
        total_images = max(0, int(char_state.get("images_with_plates", 0) or 0))
        total_plates = max(0, int(char_state.get("total_plates", 0) or 0))
        project_images = max(0, int(char_state.get("project_images_with_plates", 0) or 0))
        project_plates = max(0, int(char_state.get("project_total_plates", 0) or 0))
    except Exception:
        return None
    if total_images <= 0 and total_plates <= 0:
        return None

    project_images = min(project_images, total_images)
    project_plates = min(project_plates, total_plates)
    delta_images = max(0, total_images - project_images)
    delta_plates = max(0, total_plates - project_plates)
    return _build_t06_counter_rows(
        required_plates,
        project_images,
        project_plates,
        delta_images,
        delta_plates,
        total_images,
        total_plates,
    )


def _resolve_t06_project_name_from_run_dir(run_dir: Path | str | None) -> str:
    try:
        active_project = str(CAMPAIGN.get_active_project_name() or "").strip()
    except Exception:
        active_project = ""
    if active_project:
        return active_project

    try:
        safe_run_dir = Path(run_dir).resolve() if run_dir is not None else None
    except Exception:
        try:
            safe_run_dir = Path(run_dir) if run_dir is not None else None
        except Exception:
            safe_run_dir = None
    if safe_run_dir is None:
        return ""

    try:
        projects = dict((CAMPAIGN.state or {}).get("projects", {}) or {})
    except Exception:
        projects = {}
    for project_name, project_data in projects.items():
        if not isinstance(project_data, dict):
            continue
        folder_name = str(project_data.get("folder_name", "") or "").strip()
        if not folder_name:
            continue
        try:
            project_root = (Path(CONFIG.DIR_9_PROJECTS) / folder_name).resolve()
        except Exception:
            project_root = Path(CONFIG.DIR_9_PROJECTS) / folder_name
        try:
            if safe_run_dir == project_root or project_root in safe_run_dir.parents:
                return str(project_name or "").strip()
        except Exception:
            run_text = str(safe_run_dir).lower()
            root_text = str(project_root).lower().rstrip("\\/")
            if run_text == root_text or run_text.startswith(root_text + os.sep):
                return str(project_name or "").strip()
    return ""


def _build_t06_rows_from_strict_approved_state(
    self,
    required_plates: int,
) -> list[tuple[str, str, str]] | None:
    try:
        CAMPAIGN.invalidate_step3_char_source_state_cache()
    except Exception:
        pass

    run_dir = getattr(self, "current_annotation_run_dir", None)
    try:
        safe_run_dir = Path(run_dir) if run_dir is not None else None
    except Exception:
        safe_run_dir = None
    project_name = _resolve_t06_project_name_from_run_dir(safe_run_dir)

    project_counts_by_name: dict[str, int] = {}
    try:
        approved_entries = list(CAMPAIGN.list_plate_approved_entries(project_name or None) or [])
    except Exception:
        approved_entries = []
    for entry in approved_entries:
        if not isinstance(entry, dict):
            continue
        try:
            safe_name = CAMPAIGN._normalize_image_set_name(entry.get("image_name", ""))
        except Exception:
            safe_name = str(entry.get("image_name", "") or "").strip().lower()
        if not safe_name:
            continue
        plate_count = 0
        for plate_entry in list(entry.get("plates") or []):
            if not isinstance(plate_entry, dict):
                continue
            if len(list(plate_entry.get("polygon") or [])) >= 4:
                plate_count += 1
        if plate_count <= 0:
            plate_count = int(entry.get("plate_count", 0) or 0)
        if plate_count > 0:
            project_counts_by_name[safe_name] = max(
                int(project_counts_by_name.get(safe_name, 0) or 0),
                int(plate_count),
            )

    run_delta_counts_by_name: dict[str, int] = {}
    run_delta_image_names: set[str] = set()
    if safe_run_dir is not None:
        try:
            approved_names = set(self._load_annotation_run_approved_filenames(safe_run_dir) or set())
        except Exception:
            approved_names = set()
        try:
            approved_names.update(set(self._get_preview_approved_filenames() or set()))
        except Exception:
            pass
        if approved_names:
            approved_name_lookup = {
                str(name or "").strip().lower()
                for name in set(approved_names or set())
                if str(name or "").strip()
            }
            try:
                for ann in list(getattr(self, "current_annotations", []) or []):
                    safe_name = str(getattr(ann, "filename", "") or "").strip().lower()
                    if not safe_name or safe_name not in approved_name_lookup:
                        continue
                    if safe_name in project_counts_by_name:
                        continue
                    plate_count = len(self._get_plate_detections(ann))
                    if plate_count > 0:
                        run_delta_image_names.add(safe_name)
                        run_delta_counts_by_name[safe_name] = max(
                            int(run_delta_counts_by_name.get(safe_name, 0) or 0),
                            int(plate_count),
                        )
            except Exception:
                pass
            try:
                run_counts = dict(CAMPAIGN._load_run_plate_counts_by_image(safe_run_dir, image_names=approved_names) or {})
            except Exception:
                run_counts = {}
            for image_name, plate_count in run_counts.items():
                safe_name = str(image_name or "").strip().lower()
                if not safe_name or int(plate_count or 0) <= 0:
                    continue
                if safe_name in project_counts_by_name:
                    continue
                run_delta_image_names.add(safe_name)
                run_delta_counts_by_name[safe_name] = max(
                    int(run_delta_counts_by_name.get(safe_name, 0) or 0),
                    int(plate_count),
                )

    project_images = len(project_counts_by_name)
    project_plates = sum(int(count or 0) for count in project_counts_by_name.values())
    delta_images = len(run_delta_image_names)
    delta_plates = sum(int(count or 0) for count in run_delta_counts_by_name.values())

    total_images = project_images + delta_images
    total_plates = project_plates + delta_plates
    return _build_t06_counter_rows(
        required_plates,
        project_images,
        project_plates,
        delta_images,
        delta_plates,
        total_images,
        total_plates,
    )


def _try_update_t06_right_panel_counts_after_approval(self) -> bool:
    """Update only T06 right-panel counter values after an [OK] toggle.

    The full Z2 state refresh rebuilds several containers.  For a simple PPM
    approval change the row layout is already stable, so we only touch cached
    value labels.
    """
    try:
        graph_gate_id = str(
            dict(getattr(self, "_campaign_graph_entry_context", {}) or {}).get("graph_gate_id", "")
            or ""
        ).strip().upper()
    except Exception:
        graph_gate_id = ""
    try:
        graph_context = dict(getattr(self, "_campaign_graph_entry_context", {}) or {})
    except Exception:
        graph_context = {}
    repair_origin_gate_id = str(
        graph_context.get("repair_origin_gate_id")
        or graph_context.get("source_graph_gate_id")
        or ""
    ).strip().upper()
    is_t07_repair = bool(graph_gate_id == "T05" and repair_origin_gate_id == "T07")
    if graph_gate_id != "T06" and not is_t07_repair:
        return False

    host = getattr(self, "approve_hint_table_frame", None)
    cache = getattr(host, "_compact_table_cache", None) if host is not None else None
    if is_t07_repair:
        expected_labels = (
            "Status naprawy",
            "Zatwierdzone [OK]",
            "Do otwarcia bramki brakuje",
            "XML anotacji",
        )
        if not isinstance(cache, dict) or tuple(cache.get("labels") or ()) != expected_labels:
            return False
        try:
            project_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
            previous_images = int(project_stats.get("images", 0) or 0)
            previous_plates = int(project_stats.get("plates", 0) or 0)
        except Exception:
            previous_images = 0
            previous_plates = 0
        try:
            run_ok_images, run_ok_plates = self._get_current_preview_plate_approved_counts()
        except Exception:
            run_ok_images, run_ok_plates = 0, 0
        try:
            count_state = dict(self._get_current_preview_plate_count_state() or {})
            total_images = int(count_state.get("images_with_plates", 0) or 0)
            total_plates = int(count_state.get("total_plates", 0) or 0)
        except Exception:
            total_images, total_plates = 0, 0
        try:
            required_plates = int(getattr(CONFIG, "CAMPAIGN_MIN_PLATE_ANNOTATIONS", 10) or 10)
        except Exception:
            required_plates = 10
        effective_images = max(0, int(previous_images or 0) + int(run_ok_images or 0))
        effective_plates = max(0, int(previous_plates or 0) + int(run_ok_plates or 0))
        missing_plates = max(0, int(required_plates or 0) - effective_plates)
        ready = bool(missing_plates <= 0)
        try:
            approval_context = dict(self._get_campaign_step2_approval_context() or {})
            run_dir = approval_context.get("run_dir") or getattr(self, "current_annotation_run_dir", None)
            xml_exists = bool(run_dir and (Path(run_dir) / "annotations.xml").exists())
        except Exception:
            xml_exists = False
        rows = [
            ("Status naprawy", "OTWARTA" if ready else "W TRAKCIE", "success" if ready else "warning"),
            (
                "Zatwierdzone [OK]",
                f"{effective_images} obrazów / {effective_plates} tablic",
                "success" if effective_plates > 0 else "warning",
            ),
            (
                "Do otwarcia bramki brakuje",
                f"{missing_plates} tablic zatwierdzonych [OK]",
                "success" if missing_plates <= 0 else "warning",
            ),
            (
                "XML anotacji",
                "XML: OK" if xml_exists else f"XML: aktywny run ({int(total_images or 0)} obrazów / {int(total_plates or 0)} tablic)",
                "success" if xml_exists else "warning",
            ),
        ]
        self._render_compact_info_table(
            host,
            rows,
            default_value_tone=("success" if ready else "warning"),
            reuse_existing=True,
            show_header=False,
        )
        try:
            self._set_approve_hint_box_state("success" if ready else "warning")
        except Exception:
            pass
        try:
            self._campaign_step2_gate_overlay_state = {
                **dict(getattr(self, "_campaign_step2_gate_overlay_state", {}) or {}),
                "visible": True,
                "ready": bool(ready),
                "tone": "success" if ready else "warning",
                "title": "NAPRAWA T07",
                "gate_id": "T07",
                "source_gate_id": "T05",
                "status": "OTWARTA" if ready else "ZAMKNIĘTA",
                "approved_images": int(effective_images or 0),
                "approved_plates": int(effective_plates or 0),
                "required_plates": int(required_plates or 0),
                "missing_plates": int(missing_plates or 0),
            }
            self._campaign_step2_approval_ready = bool(ready)
            self._campaign_step2_approval_action = "campaign_graph_t05_repair_from_t07"
            self._campaign_step2_approval_iteration_target = "plate"
            self._campaign_step2_approval_repair_mode = True
        except Exception:
            pass
        try:
            self._render_preview_campaign_gate_overlay()
        except Exception:
            pass
        return True

    cache_labels = tuple(cache.get("labels") or ()) if isinstance(cache, dict) else ()
    if (
        not isinstance(cache, dict)
        or len(cache_labels) not in {6, 7}
        or cache_labels[:4] != (
            T06_LABEL_STATUS,
            T06_LABEL_SOURCE,
            T06_LABEL_SESSION,
            T06_LABEL_TOTAL,
        )
        or (len(cache_labels) >= 1 and cache_labels[-1] != T06_LABEL_QUALITY and T06_LABEL_QUALITY not in cache_labels)
    ):
        return False

    required_plates = int(getattr(CONFIG, "CAMPAIGN_MIN_CHAR_PLATES", 10) or 10)
    run_dir = getattr(self, "current_annotation_run_dir", None)
    try:
        token = f"{Path(run_dir).resolve() if run_dir else ''}|T06"
    except Exception:
        token = f"{run_dir or ''}|T06"

    baseline = getattr(self, "_campaign_t06_entry_approval_baseline", None)
    source_baseline = getattr(self, "_campaign_t06_entry_source_baseline", None)
    if (
        isinstance(baseline, dict)
        and baseline.get("token") == token
        and isinstance(source_baseline, dict)
        and source_baseline.get("token") == token
    ):
        try:
            current_images, current_plates = self._get_current_preview_plate_approved_counts()
        except Exception:
            current_images, current_plates = None, None
        if current_images is not None and current_plates is not None:
            previous_images = max(0, int(source_baseline.get("images", 0) or 0))
            previous_plates = max(0, int(source_baseline.get("plates", 0) or 0))
            baseline_images = int(baseline.get("images", 0) or 0)
            baseline_plates = int(baseline.get("plates", 0) or 0)
            delta_images = int(current_images or 0) - baseline_images
            delta_plates = int(current_plates or 0) - baseline_plates
            total_images = max(0, previous_images + delta_images)
            total_plates = max(0, previous_plates + delta_plates)
            ready = bool(total_plates >= required_plates)
            rows = _build_t06_counter_rows(
                required_plates,
                previous_images,
                previous_plates,
                delta_images,
                delta_plates,
                total_images,
                total_plates,
            )
            self._render_compact_info_table(
                host,
                rows,
                default_value_tone=("success" if ready else "warning"),
                reuse_existing=True,
                show_header=False,
            )
            try:
                self._set_approve_hint_box_state("success" if ready else "warning")
            except Exception:
                pass
            return True

    rows = _build_t06_rows_from_strict_approved_state(self, required_plates)
    if rows is not None:
        ready = bool(
            len(rows) > 0
            and str(rows[0][1] or "").strip().upper() == "OTWARTA"
        )
        self._render_compact_info_table(
            host,
            rows,
            default_value_tone=("success" if ready else "warning"),
            reuse_existing=True,
            show_header=False,
        )
        try:
            self._set_approve_hint_box_state("success" if ready else "warning")
        except Exception:
            pass
        return True

    run_dir = getattr(self, "current_annotation_run_dir", None)
    try:
        token = f"{Path(run_dir).resolve() if run_dir else ''}|T06"
    except Exception:
        token = f"{run_dir or ''}|T06"

    source_cache = getattr(self, "_campaign_t06_previous_source_counts", None)
    if not isinstance(source_cache, dict) or source_cache.get("token") != token:
        return False

    try:
        current_images, current_plates = self._get_current_preview_plate_approved_counts()
    except Exception:
        return False

    baseline = getattr(self, "_campaign_t06_entry_approval_baseline", None)
    if not isinstance(baseline, dict) or baseline.get("token") != token:
        baseline = {
            "token": token,
            "images": int(current_images or 0),
            "plates": int(current_plates or 0),
        }
        try:
            self._campaign_t06_entry_approval_baseline = dict(baseline)
        except Exception:
            pass

    source_images = int(source_cache.get("images", 0) or 0)
    source_plates = int(source_cache.get("plates", 0) or 0)
    baseline_images = int(baseline.get("images", 0) or 0)
    baseline_plates = int(baseline.get("plates", 0) or 0)
    previous_images = max(0, source_images)
    previous_plates = max(0, source_plates)
    delta_images = int(current_images or 0)
    delta_plates = int(current_plates or 0)
    total_images = max(0, previous_images + delta_images)
    total_plates = max(0, previous_plates + delta_plates)
    ready = bool(total_plates >= required_plates)
    rows = _build_t06_counter_rows(
        required_plates,
        previous_images,
        previous_plates,
        delta_images,
        delta_plates,
        total_images,
        total_plates,
    )

    self._render_compact_info_table(
        host,
        rows,
        default_value_tone=("success" if ready else "warning"),
        reuse_existing=True,
        show_header=False,
    )
    try:
        self._set_approve_hint_box_state("success" if ready else "warning")
    except Exception:
        pass
    return True


def _set_selected_preview_images_approved(
    self,
    approved: bool,
    actual_indices: list[int] | None = None,
    *,
    show_warning_modal: bool = True,
    persist_immediately: bool = True,
    refresh_export_sources: bool = True,
    schedule_followup_refresh: bool = False,
) -> None:
    selected_actual_indices = (
        [int(idx) for idx in list(actual_indices or [])]
        if actual_indices is not None
        else self._get_selected_preview_actual_indices()
    )
    if not selected_actual_indices:
        self._update_preview_edit_status("Najpierw zaznacz na liście co najmniej jeden obraz.")
        return

    approved_names = set(self._get_preview_approved_filenames())
    campaign_overlay_bundle = dict(getattr(self, "_campaign_auto_manual_overlay_bundle", {}) or {})
    try:
        initial_graph_gate_id = str(
            dict(getattr(self, "_campaign_graph_entry_context", {}) or {}).get("graph_gate_id", "")
            or ""
        ).strip().upper()
    except Exception:
        initial_graph_gate_id = ""
    if not self._is_free_mode_session_context() and initial_graph_gate_id == "T06":
        run_dir = getattr(self, "current_annotation_run_dir", None)
        try:
            t06_token = f"{Path(run_dir).resolve() if run_dir else ''}|T06"
        except Exception:
            t06_token = f"{run_dir or ''}|T06"
        approval_baseline = getattr(self, "_campaign_t06_entry_approval_baseline", None)
        if not isinstance(approval_baseline, dict) or approval_baseline.get("token") != t06_token:
            try:
                baseline_images, baseline_plates = self._get_current_preview_plate_approved_counts()
            except Exception:
                baseline_images, baseline_plates = 0, 0
            self._campaign_t06_entry_approval_baseline = {
                "token": t06_token,
                "images": int(baseline_images or 0),
                "plates": int(baseline_plates or 0),
            }
        source_baseline = getattr(self, "_campaign_t06_entry_source_baseline", None)
        if not isinstance(source_baseline, dict) or source_baseline.get("token") != t06_token:
            project_name = _resolve_t06_project_name_from_run_dir(run_dir)
            try:
                stats = dict(CAMPAIGN.get_plate_approved_set_stats(project_name or None) or {})
                source_images = int(stats.get("images", 0) or 0)
                source_plates = int(stats.get("plates", 0) or 0)
            except Exception:
                source_images, source_plates = 0, 0
            self._campaign_t06_entry_source_baseline = {
                "token": t06_token,
                "images": int(source_images or 0),
                "plates": int(source_plates or 0),
            }
    changed = 0
    approved_images_delta = 0
    approved_plates_delta = 0
    skipped_without_plate = 0
    cleaned_without_plate = 0
    counted_delta_filenames: set[str] = set()
    approved_changed_filenames: set[str] = set()
    unapproved_changed_filenames: set[str] = set()
    approval_before_by_filename: dict[str, bool] = {}
    for actual_index in selected_actual_indices:
        if actual_index < 0 or actual_index >= len(self.current_annotations or []):
            continue
        ann = self.current_annotations[actual_index]
        filename = str(getattr(ann, "filename", "") or "").strip().lower()
        if not filename:
            continue
        was_approved_for_counts = bool(
            self._preview_annotation_is_explicitly_approved(ann, approved_names=approved_names)
        )
        approval_before_by_filename.setdefault(filename, was_approved_for_counts)
        if approved and not self._preview_annotation_can_be_approved_for_export(ann):
            skipped_without_plate += 1
            if filename in approved_names:
                approved_names.discard(filename)
                cleaned_without_plate += 1
                unapproved_changed_filenames.add(filename)
            try:
                setattr(ann, "_approved_for_training", False)
            except Exception:
                pass
            if not self._is_free_mode_session_context():
                safe_display_name = str(getattr(ann, "filename", "") or "").strip()
                try:
                    campaign_overlay_bundle.pop(safe_display_name, None)
                except Exception:
                    pass
            continue
        try:
            setattr(ann, "_approved_for_training", bool(approved))
        except Exception:
            pass
        if approved:
            newly_approved = filename not in approved_names
            if filename not in approved_names:
                approved_names.add(filename)
                changed += 1
                approved_changed_filenames.add(filename)
            if not self._is_free_mode_session_context():
                safe_display_name = str(getattr(ann, "filename", "") or "").strip()
                needs_overlay_update = bool(
                    newly_approved
                    or (safe_display_name and safe_display_name not in campaign_overlay_bundle)
                )
                if not needs_overlay_update:
                    continue
                try:
                    resolved_path = self._resolve_preview_image_path(ann)
                except Exception:
                    resolved_path = None
                if resolved_path is not None:
                    try:
                        protected_ann = copy.deepcopy(ann)
                        setattr(protected_ann, "_approved_for_training", True)
                        campaign_overlay_bundle[safe_display_name] = (
                            protected_ann,
                            Path(resolved_path),
                        )
                    except Exception:
                        pass
        else:
            if filename in approved_names:
                approved_names.discard(filename)
                changed += 1
                unapproved_changed_filenames.add(filename)
            if not self._is_free_mode_session_context():
                safe_display_name = str(getattr(ann, "filename", "") or "").strip()
                try:
                    if (
                        safe_display_name in campaign_overlay_bundle
                        and not self._preview_annotation_has_manual_touch_direct(ann)
                    ):
                        campaign_overlay_bundle.pop(safe_display_name, None)
                except Exception:
                    pass

    self._preview_approved_filenames = approved_names
    if not self._is_free_mode_session_context():
        self._campaign_pending_approved_filenames = set(approved_names)
        self._campaign_auto_manual_overlay_bundle = campaign_overlay_bundle
    if changed > 0 or cleaned_without_plate > 0:
        self._preview_approval_version = int(getattr(self, "_preview_approval_version", 0) or 0) + 1
    try:
        self._append_z2_trace(
            "approved-mark",
            (
                f"approved={int(bool(approved))} changed={changed} "
                f"selected={len(selected_actual_indices)} total={len(approved_names)} "
                f"sample={sorted(list(approved_names))[:8]}"
            ),
        )
    except Exception:
        pass
    approval_state_changed = bool(changed > 0 or cleaned_without_plate > 0)
    if approval_state_changed:
        for actual_index in selected_actual_indices:
            if actual_index < 0 or actual_index >= len(self.current_annotations or []):
                continue
            ann = self.current_annotations[actual_index]
            filename = str(getattr(ann, "filename", "") or "").strip().lower()
            if not filename or filename in counted_delta_filenames:
                continue
            counted_delta_filenames.add(filename)
            was_approved = bool(approval_before_by_filename.get(filename, False))
            now_approved = bool(
                self._preview_annotation_is_explicitly_approved(ann, approved_names=approved_names)
            )
            delta = int(now_approved) - int(was_approved)
            if delta:
                plate_count = len(self._get_plate_detections(ann))
                if plate_count > 0:
                    approved_images_delta += int(delta)
                    approved_plates_delta += int(delta) * int(plate_count)
    updated_plate_count_cache = False
    if approval_state_changed and (approved_images_delta or approved_plates_delta):
        cache = getattr(self, "_preview_list_summary_cache", None)
        if isinstance(cache, dict):
            cache["approved"] = max(0, int(cache.get("approved", 0) or 0) + int(approved_images_delta))
            self._preview_list_summary_cache = cache
        plate_cache = getattr(self, "_current_preview_plate_count_cache", None)
        if isinstance(plate_cache, dict):
            approved_set = getattr(self, "_preview_approved_filenames", None)
            campaign_approved_set = getattr(self, "_campaign_pending_approved_filenames", None)
            plate_cache["approved_images"] = max(
                0,
                int(plate_cache.get("approved_images", 0) or 0) + int(approved_images_delta),
            )
            plate_cache["approved_plates"] = max(
                0,
                int(plate_cache.get("approved_plates", 0) or 0) + int(approved_plates_delta),
            )
            plate_cache["approval_cache_token"] = (
                int(id(approved_set)) if approved_set is not None else 0,
                int(len(approved_set or set())),
                int(id(campaign_approved_set)) if campaign_approved_set is not None else 0,
                int(len(campaign_approved_set or set())),
                int(getattr(self, "_preview_approval_version", 0) or 0),
            )
            self._current_preview_plate_count_cache = plate_cache
            updated_plate_count_cache = True
    if approval_state_changed and not updated_plate_count_cache:
        self._current_preview_plate_count_cache = None
    if approval_state_changed:
        if persist_immediately:
            self._persist_preview_approved_filenames()
        else:
            self._schedule_preview_approved_persist()
    if not self._is_free_mode_session_context() and approval_state_changed:
        try:
            graph_gate_id = str(
                dict(getattr(self, "_campaign_graph_entry_context", {}) or {}).get("graph_gate_id", "")
                or ""
            ).strip().upper()
        except Exception:
            graph_gate_id = ""
        if graph_gate_id == "T06" and approved_changed_filenames:
            run_dir = getattr(self, "current_annotation_run_dir", None)
            dirty_names = {
                str(name or "").strip().lower()
                for name in set(getattr(self, "_preview_dirty_images", set()) or set())
                if str(name or "").strip()
            }
            if dirty_names.intersection(approved_changed_filenames):
                try:
                    self._save_preview_edits(
                        interactive=False,
                        status_message=None,
                        refresh_list=False,
                        refresh_workflow=False,
                        refresh_export_sources=False,
                    )
                except Exception as exc:
                    logger.debug(f"Nie udalo sie zapisac XML po nadaniu OK w T06: {exc}")
            try:
                self._persist_preview_approved_filenames()
            except Exception as exc:
                logger.debug(f"Nie udalo sie zapisac manifestu OK w T06: {exc}")
            try:
                self._append_z2_trace(
                    "t06-approval-pending",
                    (
                        f"run={run_dir} approved={sorted(approved_changed_filenames)} "
                        "formal_return_required=1"
                    ),
                )
            except Exception:
                pass
        if graph_gate_id == "T06" and unapproved_changed_filenames:
            run_dir = getattr(self, "current_annotation_run_dir", None)
            try:
                self._persist_preview_approved_filenames()
            except Exception as exc:
                logger.debug(f"Nie udalo sie zapisac manifestu po cofnieciu OK w T06: {exc}")
            try:
                self._append_z2_trace(
                    "t06-approval-retracted",
                    (
                        f"run={run_dir} unapproved={sorted(unapproved_changed_filenames)} "
                        "project_source_unchanged=1"
                    ),
                )
            except Exception:
                pass
        if graph_gate_id != "T06":
            self._schedule_campaign_char_effective_source_refresh()

    restored_display_indices = []
    for actual_index in selected_actual_indices:
        try:
            self._refresh_preview_list_row_for_actual_index(actual_index, refresh_summary=False)
        except Exception:
            pass
        display_index = self._get_preview_display_index(actual_index)
        if display_index is None:
            continue
        restored_display_indices.append(display_index)
    try:
        self._clear_listbox_selection_fast(self.preview_listbox)
        for display_index in restored_display_indices:
            self.preview_listbox.selection_set(display_index)
        if restored_display_indices:
            self.preview_listbox.activate(restored_display_indices[-1])
            self.preview_listbox.see(restored_display_indices[-1])
    except Exception:
        pass
    self._refresh_preview_list_summary(lightweight=True)
    self._update_preview_toolbar_state(refresh_summary=False)
    self._queue_free_mode_session_save()
    if approval_state_changed and refresh_export_sources:
        try:
            try:
                graph_gate_id = str(
                    dict(getattr(self, "_campaign_graph_entry_context", {}) or {}).get("graph_gate_id", "")
                    or ""
                ).strip().upper()
            except Exception:
                graph_gate_id = ""
            try:
                graph_context = dict(getattr(self, "_campaign_graph_entry_context", {}) or {})
                repair_origin_gate_id = str(
                    graph_context.get("repair_origin_gate_id")
                    or graph_context.get("source_graph_gate_id")
                    or ""
                ).strip().upper()
            except Exception:
                repair_origin_gate_id = ""
            graph_gate_has_fast_counter = bool(
                graph_gate_id == "T06"
                or (graph_gate_id == "T05" and repair_origin_gate_id == "T07")
            )
            skip_export_refresh = bool(
                not self._is_free_mode_session_context()
                and graph_gate_id in {"T04", "T05", "T06"}
            )
            if not skip_export_refresh:
                active_run_dir = self._get_active_annotation_run_dir(require_xml=True)
                if active_run_dir is not None:
                    self._load_plate_dataset_context_from_run(active_run_dir, force_images_update=True)
                self._refresh_plate_dataset_export_sources()
            fast_t06_update = bool(
                skip_export_refresh
                and graph_gate_has_fast_counter
                and _try_update_t06_right_panel_counts_after_approval(self)
            )
            if not fast_t06_update:
                self._refresh_step2_action_states()
            if self._is_free_mode_session_context():
                self._refresh_free_mode_workflow_ui()
        except Exception:
            try:
                self._refresh_step2_action_states()
            except Exception:
                pass
    elif approval_state_changed and schedule_followup_refresh:
        try:
            graph_gate_id = str(
                dict(getattr(self, "_campaign_graph_entry_context", {}) or {}).get("graph_gate_id", "")
                or ""
            ).strip().upper()
        except Exception:
            graph_gate_id = ""
        try:
            graph_context = dict(getattr(self, "_campaign_graph_entry_context", {}) or {})
            repair_origin_gate_id = str(
                graph_context.get("repair_origin_gate_id")
                or graph_context.get("source_graph_gate_id")
                or ""
            ).strip().upper()
        except Exception:
            repair_origin_gate_id = ""
        graph_gate_has_fast_counter = bool(
            graph_gate_id == "T06"
            or (graph_gate_id == "T05" and repair_origin_gate_id == "T07")
        )
        if not (graph_gate_has_fast_counter and _try_update_t06_right_panel_counts_after_approval(self)):
            self._schedule_preview_approval_followup_refresh()
    if approved and skipped_without_plate > 0:
        if changed > 0:
            status_text = (
                f"Oznaczono jako OK: {changed} obraz(y). "
                f"Pominięto {skipped_without_plate} bez ramki tablicy."
            )
        elif cleaned_without_plate > 0:
            status_text = (
                f"Usunięto błędny status OK z {cleaned_without_plate} obraz(ów) bez ramki tablicy. "
                "Obraz można zatwierdzić dopiero po dodaniu ramki."
            )
        else:
            status_text = (
                "Nie można oznaczyć jako OK: zaznaczone obrazy nie mają ramki tablicy. "
                "Najpierw dodaj i zapisz ramkę."
            )
        if changed <= 0 and show_warning_modal:
            try:
                messagebox.showwarning(
                    "Brak ramki tablicy",
                    (
                        "Nie można oznaczyć obrazu jako OK, jeśli nie ma zapisanej ramki tablicy.\n\n"
                        "Najpierw narysuj lub popraw ramkę, poczekaj na zapis annotations.xml, "
                        "a potem oznacz obraz jako OK."
                    ),
                    parent=self.frame.winfo_toplevel(),
                )
            except Exception:
                pass
    else:
        status_text = (
            (
                f"Oznaczono jako OK: {changed} obraz(y)."
                if approved
                else f"Cofnięto OK dla {changed} obraz(ów)."
            )
            if changed > 0
            else (
                "Zaznaczone obrazy były już oznaczone jako OK."
                if approved
                else "Zaznaczone obrazy nie miały znacznika OK."
            )
        )
    self._update_preview_edit_status(status_text)
    try:
        self._update_preview_canvas_metrics_overlay(force_render=True)
    except Exception:
        pass
    try:
        self._preview_overlay_dock_render_key = None
        self._preview_overlay_dock_size = None
        self._preview_overlay_dock_size_key = None
        self._preview_overlay_dock_pre_gate_key = None
        self._preview_overlay_dock_gate_render_key = None
        self._preview_overlay_dock_inline_gate_state = None
        self._place_preview_overlay_dock(force_render=True)
    except Exception:
        pass
    try:
        if bool(getattr(self, "_preview_fullscreen_active", False)):
            self._hide_preview_image_status_overlay()
            self._hide_preview_campaign_gate_overlay()
        else:
            self._place_preview_image_status_overlay(force_render=True)
            self._place_preview_campaign_gate_overlay(force_render=True)
    except Exception:
        pass

def _rename_selected_preview_image_file(self):
    if not self._ensure_preview_is_editable_for_action():
        self._update_preview_edit_status(
            "Zmiana nazwy pliku będzie dostępna dopiero po przygotowaniu annotations.xml.",
            "warning",
        )
        return

    ann = self._get_preview_annotation()
    if ann is None or self.current_input_dir is None:
        self._update_preview_edit_status("Najpierw wybierz obraz do zmiany nazwy.", "warning")
        return

    current_name = str(getattr(ann, "filename", "") or "").strip()
    if not current_name:
        self._update_preview_edit_status("Wybrany obraz nie ma poprawnej nazwy pliku.", "warning")
        return

    image_path = self._resolve_preview_image_path(ann)
    if image_path is None or not image_path.exists():
        self._update_preview_edit_status(
            "Nie udało się odnaleźć fizycznego pliku obrazu do zmiany nazwy.",
            "warning",
        )
        return

    next_value = self._prompt_z2_text_input(
        title="Nazwa obrazu w Z2",
        prompt=(
            "Podaj nową nazwę pliku obrazu.\n"
            "Program zmieni nazwę pliku na dysku i zapisze ją w aktywnym runie Z2."
        ),
        initial_value=current_name,
        width=560,
    )
    if next_value is None:
        return

    candidate_name = str(next_value or "").strip()
    if not candidate_name:
        self._update_preview_edit_status("Nazwa pliku nie może być pusta.", "warning")
        return
    if "/" in candidate_name or "\\" in candidate_name:
        messagebox.showerror("Nieprawidłowa nazwa", "Podaj samą nazwę pliku bez ścieżki katalogu.")
        return

    current_suffix = str(image_path.suffix or "")
    if current_suffix and not Path(candidate_name).suffix:
        candidate_name = f"{candidate_name}{current_suffix}"
    if candidate_name in {".", ".."}:
        self._update_preview_edit_status("Podaj poprawną nazwę pliku obrazu.", "warning")
        return
    if candidate_name == current_name:
        self._update_preview_edit_status("Nazwa pliku nie uległa zmianie.", "muted")
        return

    duplicate_name = any(
        str(getattr(other, "filename", "") or "").strip().lower() == candidate_name.lower()
        for other in list(self.current_annotations or [])
        if other is not ann
    )
    if duplicate_name:
        messagebox.showerror(
            "Duplikat nazwy",
            "W aktywnym runie Z2 istnieje już obraz o takiej nazwie.",
        )
        return

    try:
        image_path = image_path.resolve()
    except Exception:
        try:
            image_path = image_path.absolute()
        except Exception:
            pass

    target_path = image_path.with_name(candidate_name)
    if target_path.exists():
        messagebox.showerror(
            "Plik już istnieje",
            f"Nie można zmienić nazwy, bo w tym katalogu istnieje już plik:\n{target_path.name}",
        )
        return

    try:
        image_path.rename(target_path)
    except Exception as exc:
        messagebox.showerror(
            "Nie udało się zmienić nazwy pliku",
            f"Nie można zmienić nazwy pliku obrazu na dysku:\n{exc}",
        )
        self._update_preview_edit_status("Zmiana nazwy pliku nie powiodła się.", "warning")
        return

    backup_preview_image_path_map = dict(getattr(self, "_preview_image_path_map", {}) or {})
    backup_pending_source_image_map = dict(getattr(self, "_pending_source_image_map", {}) or {})
    backup_selected_plate = dict(getattr(self, "_preview_selected_plate_by_image", {}) or {})
    backup_selected_vehicle = dict(getattr(self, "_preview_selected_vehicle_by_image", {}) or {})
    backup_dirty = set(getattr(self, "_preview_dirty_images", set()) or set())
    backup_preview_approved = set(getattr(self, "_preview_approved_filenames", set()) or set())
    backup_pending_preview_approved = set(getattr(self, "_pending_preview_approved_filenames", set()) or set())
    backup_campaign_pending_approved = set(getattr(self, "_campaign_pending_approved_filenames", set()) or set())
    backup_iteration_manual = set(getattr(self, "_campaign_iteration_manual_filenames", set()) or set())
    backup_reuse_manual = set(getattr(self, "_campaign_reuse_manual_filenames", set()) or set())
    backup_restore_filename = str(getattr(self, "_preview_session_restore_filename", "") or "")

    ann.filename = candidate_name
    try:
        self._preview_image_path_map = self._replace_preview_filename_in_dict_keys(
            getattr(self, "_preview_image_path_map", {}) or {},
            current_name,
            candidate_name,
        )
        self._preview_image_path_map[candidate_name] = Path(target_path)
    except Exception:
        pass
    try:
        self._pending_source_image_map = self._replace_preview_filename_in_dict_keys(
            getattr(self, "_pending_source_image_map", {}) or {},
            current_name,
            candidate_name,
        )
        if getattr(self, "_pending_source_image_map", None) is not None:
            self._pending_source_image_map[candidate_name] = Path(target_path)
    except Exception:
        pass

    self._preview_selected_plate_by_image = self._replace_preview_filename_in_dict_keys(
        getattr(self, "_preview_selected_plate_by_image", {}) or {},
        current_name,
        candidate_name,
    )
    self._preview_selected_vehicle_by_image = self._replace_preview_filename_in_dict_keys(
        getattr(self, "_preview_selected_vehicle_by_image", {}) or {},
        current_name,
        candidate_name,
    )
    self._preview_dirty_images = self._replace_preview_filename_in_set(
        getattr(self, "_preview_dirty_images", set()) or set(),
        current_name,
        candidate_name,
    )
    self._preview_approved_filenames = self._replace_preview_filename_in_set(
        getattr(self, "_preview_approved_filenames", set()) or set(),
        current_name.lower(),
        candidate_name.lower(),
    )
    self._pending_preview_approved_filenames = self._replace_preview_filename_in_set(
        getattr(self, "_pending_preview_approved_filenames", set()) or set(),
        current_name.lower(),
        candidate_name.lower(),
    )
    self._campaign_pending_approved_filenames = self._replace_preview_filename_in_set(
        getattr(self, "_campaign_pending_approved_filenames", set()) or set(),
        current_name.lower(),
        candidate_name.lower(),
    )
    self._campaign_iteration_manual_filenames = self._replace_preview_filename_in_set(
        getattr(self, "_campaign_iteration_manual_filenames", set()) or set(),
        current_name,
        candidate_name,
    )
    self._campaign_reuse_manual_filenames = self._replace_preview_filename_in_set(
        getattr(self, "_campaign_reuse_manual_filenames", set()) or set(),
        current_name,
        candidate_name,
    )
    if str(getattr(self, "_preview_session_restore_filename", "") or "").strip() == current_name:
        self._preview_session_restore_filename = candidate_name

    self._invalidate_preview_list_frozen_order()
    self._preview_dirty_images.add(candidate_name)

    if not self._save_preview_edits(
        interactive=False,
        status_message=f"Zmieniono nazwę obrazu na {candidate_name} i zapisano zmianę do annotations.xml.",
    ):
        try:
            if target_path.exists() and not image_path.exists():
                target_path.rename(image_path)
        except Exception:
            pass
        ann.filename = current_name
        self._preview_image_path_map = backup_preview_image_path_map
        self._pending_source_image_map = backup_pending_source_image_map
        self._preview_selected_plate_by_image = backup_selected_plate
        self._preview_selected_vehicle_by_image = backup_selected_vehicle
        self._preview_dirty_images = backup_dirty
        self._preview_approved_filenames = backup_preview_approved
        self._pending_preview_approved_filenames = backup_pending_preview_approved
        self._campaign_pending_approved_filenames = backup_campaign_pending_approved
        self._campaign_iteration_manual_filenames = backup_iteration_manual
        self._campaign_reuse_manual_filenames = backup_reuse_manual
        self._preview_session_restore_filename = backup_restore_filename
        self._update_preview_edit_status(
            "Nie udało się zapisać zmiany nazwy obrazu do aktywnego runu Z2. Przywrócono nazwę na dysku.",
            "warning",
        )
        return

    try:
        self._refresh_preview_list(preserve_selection=True, render_current=True)
    except Exception:
        pass

def _refresh_preview_workspace_visibility(self, *, manual_review_active: bool | None = None):
    if manual_review_active is None:
        has_existing_run = self._get_preferred_annotation_run_dir(require_xml=True) is not None
        manual_review_active = bool(self._manual_review_active and has_existing_run)
    free_mode_context = bool(self._is_free_mode_session_context())
    free_mode_screen = self._coerce_free_mode_screen() if free_mode_context else ""
    free_mode_route = str(self._get_workflow_route() or "").strip().lower() if free_mode_context else ""
    free_mode_step = str(self._coerce_workflow_step() or "").strip().lower() if free_mode_context else ""
    campaign_repair_preview_layout = False
    if not free_mode_context:
        try:
            campaign_repair_preview_layout = bool(
                self._is_campaign_char_repair_return_mode()
                or self._is_campaign_plate_step4_repair_return_mode()
            )
        except Exception:
            campaign_repair_preview_layout = False
    processing_overlay_active = bool(getattr(self, "_preview_processing_overlay_active", False))
    preserve_left_scroll = bool(self.is_processing or processing_overlay_active)
    left_scroll_fraction = 0.0
    left_settings_canvas = getattr(self, "left_settings_canvas", None)
    try:
        if left_settings_canvas is not None:
            yview_state = tuple(left_settings_canvas.yview() or ())
            if yview_state:
                left_scroll_fraction = max(0.0, min(1.0, float(yview_state[0])))
    except Exception:
        left_scroll_fraction = 0.0
    has_any_preview = bool(getattr(self, "current_annotations", None))
    allow_workflow_preview_without_xml = bool(
        free_mode_context
        and free_mode_screen == "workflow"
        and (
            (free_mode_route == "auto" and free_mode_step == "auto_start")
            or (free_mode_route == "manual" and free_mode_step == "manual_start")
        )
    )
    has_loaded_preview = bool(
        has_any_preview
        and (
            self._get_current_annotation_xml_path() is not None
            or not free_mode_context
            or allow_workflow_preview_without_xml
        )
    )

    compact_left_column_layout = bool(
        not free_mode_context
        and getattr(self, "_compact_left_column_layout", False)
    )
    if free_mode_context:
        show_preview = bool(
            has_loaded_preview
            and (
                free_mode_screen in {"auto_summary", "manual_review", "export"}
                or allow_workflow_preview_without_xml
            )
        )
    else:
        show_preview = bool(
            manual_review_active and not self._manual_review_export_ready
            or has_loaded_preview
        )
    if processing_overlay_active:
        show_preview = True

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
    if free_mode_context and free_mode_route == "manual":
        try:
            self._sync_main_pane_right_panel_visibility()
            self._refresh_free_mode_manual_right_panel()
        except Exception:
            pass
    left_settings_canvas = getattr(self, "left_settings_canvas", None)
    left_settings_col = getattr(self, "left_settings_col", None)
    workflow_entry_shell = getattr(self, "workflow_entry_shell", None)
    workflow_entry_shell_inner = getattr(self, "workflow_entry_shell_inner", None)
    try:
        if left_settings_col is not None and str(left_settings_col.winfo_manager()) == "pack":
            left_settings_col.pack_configure(
                fill=tk.X,
                expand=False,
                padx=10,
                pady=((2, 2) if compact_left_column_layout else (8, 14)),
            )
    except Exception:
        pass
    try:
        if left_settings_canvas is not None and not preserve_left_scroll:
            left_settings_canvas.yview_moveto(0.0)
    except Exception:
        pass
    try:
        if left_settings_canvas is not None:
            if compact_left_column_layout:
                try:
                    self.left_settings_content.update_idletasks()
                except Exception:
                    pass
                measured_height = self._measure_visible_pack_height(getattr(self, "left_settings_content", None))
                target_height = max(1, int(measured_height) + 4)
                try:
                    left_frame = getattr(self, "main_left_frame", None)
                    available_height = int(left_frame.winfo_height() or 0) if left_frame is not None else 0
                except Exception:
                    available_height = 0
                if show_preview:
                    if available_height > 0:
                        reserved_preview_height = max(
                            (340 if campaign_repair_preview_layout else 280),
                            int(available_height * (0.60 if campaign_repair_preview_layout else 0.52)),
                        )
                        preview_cap = min(
                            max(180, int(available_height * (0.30 if campaign_repair_preview_layout else 0.38))),
                            max(180, int(available_height - reserved_preview_height)),
                        )
                    else:
                        preview_cap = 220 if campaign_repair_preview_layout else 320
                    target_height = min(target_height, int(preview_cap))
                else:
                    target_height = min(target_height, 560)
                left_settings_canvas.configure(height=target_height)
            else:
                left_settings_canvas.configure(height=1)
    except Exception:
        pass
    try:
        if workflow_entry_shell is not None and str(workflow_entry_shell.winfo_manager()) == "pack":
            workflow_entry_shell.pack_configure(
                fill=tk.X,
                pady=((0, 0) if compact_left_column_layout else (0, 10)),
            )
    except Exception:
        pass
    try:
        if workflow_entry_shell_inner is not None:
            workflow_entry_shell_inner.configure(
                padx=3,
                pady=(2 if compact_left_column_layout else 5),
            )
            if str(workflow_entry_shell_inner.winfo_manager()) == "pack":
                workflow_entry_shell_inner.pack_configure(
                    fill=tk.X,
                    expand=False,
                )
    except Exception:
        pass
    self._sync_left_column_pane_layout(
        show_preview=show_preview,
        compact_layout=compact_left_column_layout,
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

    try:
        self._set_preview_processing_overlay(
            processing_overlay_active,
            title="Trwa autoanotacja",
            details="Lista i podgląd pozostają widoczne, ale są zablokowane do końca bieżącego runu.",
        )
    except Exception:
        pass
    try:
        if left_settings_canvas is not None and preserve_left_scroll:
            left_settings_canvas.yview_moveto(left_scroll_fraction)
    except Exception:
        pass

def _populate_preview_list_async(
    self,
    *,
    preserve_selection: bool = False,
    render_current: bool = True,
    batch_size: int = 200,
    on_progress=None,
    on_ready=None,
    on_complete=None,
):
    populate_started = time.perf_counter()
    self._cancel_preview_list_population()
    self._invalidate_preview_runtime_caches()
    self._set_preview_list_population_active(True)

    source_annotations = list(getattr(self, "current_annotations", []) or [])
    if len(source_annotations) >= 1200:
        cache_started = time.perf_counter()
        try:
            self._build_preview_list_render_state_cache(list(enumerate(source_annotations)))
            cache_elapsed_ms = (time.perf_counter() - cache_started) * 1000.0
            if cache_elapsed_ms >= 100.0:
                logger.info(
                    "[Z2 PERF] preview_list_status_cache total=%.0fms entries=%s",
                    cache_elapsed_ms,
                    len(source_annotations),
                )
        except Exception:
            self._preview_list_render_state_cache = None

    entries = self._get_preview_list_entries()
    if len(entries) >= 3000 and int(batch_size or 0) < 900:
        batch_size = 900
    self._preview_list_display_indices = [actual_idx for actual_idx, _ann in entries]
    self._preview_list_display_index_map = {
        int(actual_idx): int(display_idx)
        for display_idx, actual_idx in enumerate(self._preview_list_display_indices)
    }
    completion_called = False
    ready_called = False

    def signal_ready() -> None:
        nonlocal ready_called
        if ready_called:
            return
        ready_called = True
        if callable(on_ready):
            try:
                on_ready()
            except Exception:
                pass

    def finish_population() -> None:
        nonlocal completion_called
        if completion_called:
            return
        completion_called = True
        if callable(on_complete):
            try:
                on_complete()
            except Exception:
                pass

    selected_actual_index = self.current_preview_index if preserve_selection else None
    if selected_actual_index is None and entries:
        selected_actual_index = entries[0][0]
    selected_display_index = self._get_preview_display_index(selected_actual_index)
    if selected_display_index is None and entries:
        selected_actual_index = entries[0][0]
        selected_display_index = 0

    try:
        palette = getattr(self.app, "palette", {}) or {}
        default_fg = (
            palette.get("success", "#27ae60")
            if len(entries) >= 3000
            else palette.get("error", "#c0392b")
        )
        self.preview_listbox.configure(fg=default_fg)
    except Exception:
        pass
    self.preview_listbox.delete(0, tk.END)
    self._refresh_preview_list_summary(lightweight=bool(len(entries) >= 1200))
    signal_ready()

    if not entries:
        self._set_preview_list_population_active(False)
        self.current_preview_index = None
        try:
            self.preview_canvas.clear_image()
        except Exception:
            self.preview_canvas.delete("all")
        self._update_preview_toolbar_state()
        self._update_preview_edit_status()
        finish_population()
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
        self._clear_listbox_selection_fast(self.preview_listbox)
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
        if (
            token != int(getattr(self, "_preview_list_populate_token", 0) or 0)
            or (
                not bool(getattr(self, "_campaign_deferred_run_restore_in_progress", False))
                and not self._is_annotation_tab_selected()
            )
        ):
            self._preview_list_populate_after_id = None
            self._set_preview_list_population_active(False)
            return

        end_index = min(start_index + max(1, int(batch_size)), len(entries))
        total_count = len(entries)
        color_all_rows = bool(total_count < 3000)
        lightweight_labels = bool(total_count >= 1200)
        batch_labels = []
        for idx in range(start_index, end_index):
            _actual_idx, ann = entries[idx]
            batch_labels.append(
                self._preview_list_item_text(
                    ann,
                    display_index=idx,
                    total_count=total_count,
                    lightweight=lightweight_labels,
                )
            )
        if batch_labels:
            try:
                before_size = int(self.preview_listbox.size() or 0)
            except Exception:
                before_size = 0
            try:
                self.preview_listbox.insert(tk.END, *batch_labels)
            except Exception:
                pass
            try:
                after_size = int(self.preview_listbox.size() or 0)
            except Exception:
                after_size = before_size
            inserted_count = max(0, after_size - before_size)
            expected_count = len(batch_labels)
            if inserted_count != expected_count:
                try:
                    if after_size > before_size:
                        self.preview_listbox.delete(before_size, tk.END)
                except Exception:
                    pass
                for label in batch_labels:
                    self.preview_listbox.insert(tk.END, label)
                try:
                    repaired_size = int(self.preview_listbox.size() or 0)
                except Exception:
                    repaired_size = before_size + expected_count
                logger.debug(
                    "[AnnotationTab][PERF] preview_list_batch_repair: "
                    f"expected={expected_count} inserted={inserted_count} repaired_total={repaired_size}"
                )
        for idx in range(start_index, end_index):
            _actual_idx, ann = entries[idx]
            try:
                if not color_all_rows:
                    # On large NEON-like runs the dominant bucket is auto.  The
                    # listbox gets that color globally; only exceptions need a
                    # per-row itemconfig call.
                    if self._preview_annotation_sort_bucket(ann) == "auto":
                        continue
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

        if callable(on_progress):
            try:
                on_progress(end_index, len(entries))
            except Exception:
                pass

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
        try:
            final_size = int(self.preview_listbox.size() or 0)
        except Exception:
            final_size = len(entries)
        try:
            last_label = str(self.preview_listbox.get(tk.END) or "").strip() if final_size > 0 else ""
        except Exception:
            last_label = ""
        self._append_z2_trace(
            "preview-list-async",
            f"entries={len(entries)} listbox={final_size} last={last_label[:120]}",
        )
        elapsed_ms = (time.perf_counter() - populate_started) * 1000.0
        if elapsed_ms >= 500.0:
            try:
                logger.info(
                    "[Z2 PERF] preview_list_async total=%.0fms entries=%s listbox=%s batch=%s",
                    elapsed_ms,
                    len(entries),
                    final_size,
                    int(batch_size),
                )
            except Exception:
                pass
        if final_size != len(entries):
            logger.debug(
                "[AnnotationTab][PERF] preview_list_population_mismatch: "
                f"entries={len(entries)} listbox={final_size}"
            )
        self._set_preview_list_population_active(False)
        finish_population()

    insert_batch(0)

def _refresh_preview_list_legend_theme(self):
    palette = getattr(self.app, "palette", {})
    panel_bg = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    ok_color = palette.get("success", "#27ae60")
    corrected_color = palette.get("warning", "#f39c12")
    err_color = palette.get("error", "#c0392b")
    approved_color = palette.get("accent", "#0e639c")
    muted_color = palette.get("muted", "#c7c7c7")
    fg_color = palette.get("fg", "#f3f3f3")

    for frame_name in (
        "preview_list_meta",
        "preview_list_controls",
        "preview_list_filter_row",
        "preview_list_filter_actions_row",
        "preview_list_section",
        "preview_filter_bar",
        "preview_filter_bar_grid",
        "preview_list_sort_grid",
        "preview_list_legend",
        "preview_list_legend_grid",
        "preview_list_bulk_actions",
    ):
        frame = getattr(self, frame_name, None)
        if frame is None:
            continue
        try:
            frame.configure(style="Panel.TFrame")
        except Exception:
            pass

    try:
        filter_shell = getattr(self, "preview_list_filter_shell", None)
        if filter_shell is not None:
            filter_shell.configure(
                bg=panel_bg,
                highlightbackground=ok_color,
                highlightcolor=ok_color,
            )
    except Exception:
        pass

    for widget_name, fg in (
        ("preview_list_summary_lbl", muted_color),
        ("preview_list_filter_lbl", muted_color),
        ("preview_list_sort_lbl", muted_color),
        ("preview_filter_hint_lbl", muted_color),
        ("preview_list_legend_total_lbl", muted_color),
    ):
        widget = getattr(self, widget_name, None)
        if widget is None:
            continue
        try:
            widget.configure(bg=panel_bg, fg=fg)
        except Exception:
            pass

    active_sort_mode = self._normalize_preview_list_sort_mode()
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
            "Status: A, M, OK, problem",
        ),
        (
            "preview_list_legend_corrected_item",
            "preview_list_legend_corrected_badge",
            "preview_list_legend_corrected_lbl",
            "preview_list_legend_corrected_count_lbl",
            corrected_color,
            "Status: ED, OK, problem",
        ),
        (
            "preview_list_legend_problem_item",
            "preview_list_legend_problem_badge",
            "preview_list_legend_problem_lbl",
            "preview_list_legend_problem_count_lbl",
            err_color,
            "Status: problem, ED, OK",
        ),
        (
            "preview_list_legend_dirty_item",
            "preview_list_legend_dirty_badge",
            "preview_list_legend_dirty_lbl",
            "preview_list_legend_dirty_count_lbl",
            approved_color,
            "Status: OK, ED, problem",
        ),
    )
    active_legend_sort_mode = self._normalize_preview_list_sort_mode()
    for item_name, badge_name, label_name, count_name, accent, linked_sort_mode in legend_items:
        item = getattr(self, item_name, None)
        badge = getattr(self, badge_name, None)
        label = getattr(self, label_name, None)
        count_lbl = getattr(self, count_name, None)
        is_active = str(linked_sort_mode or "").strip() == active_legend_sort_mode
        item_bg = blend_hex_colors(accent, panel_bg, 0.18) if is_active else panel_bg
        item_border = accent if is_active else panel_border
        item_fg = "#1b1b1b" if is_active else fg_color
        count_fg = "#1b1b1b" if is_active else accent
        try:
            if item is not None:
                item.configure(bg=item_bg, highlightbackground=item_border, highlightcolor=item_border)
            if badge is not None:
                badge.configure(bg=accent, fg=("#1b1b1b" if accent == corrected_color else panel_bg))
            if label is not None:
                label.configure(bg=item_bg, fg=item_fg)
            if count_lbl is not None:
                count_lbl.configure(bg=item_bg, fg=count_fg)
        except Exception:
            pass

    try:
        total_item = getattr(self, "preview_list_legend_total_item", None)
        total_lbl = getattr(self, "preview_list_legend_total_lbl", None)
        total_count_lbl = getattr(self, "preview_list_legend_total_count_lbl", None)
        if total_item is not None:
            total_item.configure(bg=panel_bg, highlightbackground=panel_border, highlightcolor=panel_border)
        if total_lbl is not None:
            total_lbl.configure(bg=panel_bg, fg=muted_color)
        if total_count_lbl is not None:
            total_count_lbl.configure(bg=panel_bg, fg=fg_color)
    except Exception:
        pass

    try:
        container_grip = getattr(self, "preview_left_list_resize_grip", None)
        container_grip_line = getattr(self, "preview_left_list_resize_grip_line", None)
        if container_grip is not None:
            container_grip.configure(bg=panel_border)
        if container_grip_line is not None:
            container_grip_line.configure(bg=blend_hex_colors(approved_color, panel_border, 0.42))
    except Exception:
        pass

    try:
        self._refresh_preview_filter_bar_state()
    except Exception:
        pass

def _refresh_preview_list_summary(self, *, lightweight: bool = False):
    annotations = list(self.current_annotations or [])
    visible_entries = list(getattr(self, "_preview_list_display_indices", []) or [])
    visible_count = int(len(visible_entries))
    campaign_context = not self._is_free_mode_session_context()
    approval_context = self._get_campaign_step2_approval_context() if campaign_context else {}
    approval_current_step = int(approval_context.get("current_step") or 0) if isinstance(approval_context, dict) else 0
    approval_iteration_target = str(approval_context.get("iteration_target") or "").strip().lower() if isinstance(approval_context, dict) else ""
    approval_repair_context = bool(
        campaign_context
        and isinstance(approval_context, dict)
        and bool(approval_context.get("repair_mode"))
    )
    char_repair_context = bool(campaign_context and approval_current_step == 3 and approval_iteration_target == "char")
    summary_cache = getattr(self, "_preview_list_summary_cache", None)
    use_cached_counts = bool(
        lightweight
        and isinstance(summary_cache, dict)
        and int(summary_cache.get("total", -1) or -1) == int(len(annotations))
    )
    if lightweight and not use_cached_counts and len(annotations) >= 1200:
        try:
            self.preview_list_summary_var.set(
                f"Zdjęcia: {visible_count}/{len(annotations)} | Tablice: liczenie w tle"
            )
        except Exception:
            pass
        return
    if use_cached_counts:
        reused_manual = int(summary_cache.get("reused_manual", 0) or 0)
        manual_images = int(summary_cache.get("manual", 0) or 0)
        auto_images = int(summary_cache.get("auto", 0) or 0)
        problem_images = int(summary_cache.get("problem", 0) or 0)
        approved_images = int(summary_cache.get("approved", 0) or 0)
        current_manual_count = int(summary_cache.get("current_manual", 0) or 0)
        total_plate_count = int(summary_cache.get("plates_total", 0) or 0)
    else:
        approved_names = self._get_preview_approved_filenames_base()
        reused_manual = 0
        manual_images = 0
        auto_images = 0
        problem_images = 0
        approved_images = 0
        current_manual_count = 0
        total_plate_count = 0
        for ann in annotations:
            try:
                total_plate_count += int(len(self._get_plate_detections(ann)))
            except Exception:
                pass
            if self._preview_annotation_is_reused_from_previous_manual(ann):
                reused_manual += 1

            origin_tag = self._preview_annotation_origin_tag(ann)
            if origin_tag == "manual" or origin_tag == "M":
                manual_images += 1
            elif origin_tag == "auto" or origin_tag == "A":
                auto_images += 1
            else:
                problem_images += 1

            if self._preview_annotation_is_explicitly_approved(ann, approved_names):
                approved_images += 1
    dirty = len(getattr(self, "_preview_dirty_images", set()) or set())
    conf_threshold, fit_threshold = self._get_preview_metric_filter_thresholds()
    filter_parts = []
    if conf_threshold > 0.0:
        filter_parts.append(f"Det >= {conf_threshold:.2f}")
    if fit_threshold > 0.0:
        filter_parts.append(f"Fit >= {fit_threshold:.2f}")
    filter_text = " | ".join(filter_parts)
    visible_plate_count = 0
    visible_manual_images = 0
    visible_auto_images = 0
    visible_problem_images = 0
    visible_approved_images = 0
    try:
        for actual_idx in visible_entries:
            safe_idx = int(actual_idx)
            if 0 <= safe_idx < len(annotations):
                ann = annotations[safe_idx]
                visible_plate_count += int(len(self._get_plate_detections(ann)))
                try:
                    bucket = str(self._preview_annotation_sort_bucket(ann) or "").strip().lower()
                except Exception:
                    bucket = "problem"
                if bucket == "approved":
                    visible_approved_images += 1
                elif bucket == "manual":
                    visible_manual_images += 1
                elif bucket == "auto":
                    visible_auto_images += 1
                else:
                    visible_problem_images += 1
    except Exception:
        visible_plate_count = total_plate_count if visible_count == len(annotations) else 0
        visible_manual_images = manual_images if visible_count == len(annotations) else 0
        visible_auto_images = auto_images if visible_count == len(annotations) else 0
        visible_problem_images = problem_images if visible_count == len(annotations) else 0
        visible_approved_images = approved_images if visible_count == len(annotations) else 0
    left_summary_parts: list[str] = []
    left_summary_parts.append(f"Zdjęcia: {visible_count}/{len(annotations)}")
    left_summary_parts.append(f"Tablice: {visible_plate_count}/{total_plate_count}")
    if filter_text:
        left_summary_parts.append(f"Filtr jakości: {filter_text}")
    left_summary_text = " | ".join(left_summary_parts)
    breakdown_summary_text = ""

    try:
        pending_summary = dict(getattr(self, "_campaign_pending_batch_summary", {}) or {})
        if not use_cached_counts:
            current_manual_count = len(
                self._collect_campaign_current_iteration_manual_filenames(annotations)
            )
        manual_skip_count = max(
            int(pending_summary.get("manual_skip_count", 0) or 0),
            current_manual_count,
        )
    except Exception:
        current_manual_count = 0
        manual_skip_count = 0

    if not use_cached_counts:
        self._preview_list_summary_cache = {
            "total": int(len(annotations)),
            "reused_manual": int(reused_manual),
            "manual": int(manual_images),
            "auto": int(auto_images),
            "problem": int(problem_images),
            "approved": int(approved_images),
            "current_manual": int(current_manual_count),
            "plates_total": int(total_plate_count),
        }

    try:
        self.preview_list_summary_var.set(left_summary_text)
    except Exception:
        pass

    try:
        if hasattr(self, "approve_breakdown_var"):
            self.approve_breakdown_var.set(str(breakdown_summary_text or "").strip())
    except Exception:
        pass

    breakdown_table_rows: list[tuple[str, str, str]] = []

    try:
        free_mode_manual_panel_active = bool(
            self._is_free_mode_session_context()
            and self._should_show_free_mode_manual_right_panel()
        )
    except Exception:
        free_mode_manual_panel_active = False

    try:
        if free_mode_manual_panel_active:
            # In Z2(F) the right-panel breakdown box belongs to the export status
            # panel. The generic preview summary must not hide or overwrite it.
            if not lightweight:
                try:
                    self._refresh_free_mode_manual_right_panel(reuse_existing_tables=True)
                except Exception:
                    pass
        else:
            show_breakdown_text = bool(str(breakdown_summary_text or "").strip())
            show_breakdown_box = bool(
                self._should_show_right_panel()
                and (show_breakdown_text or breakdown_table_rows)
            )
            if not lightweight:
                self._set_widget_packed(
                    getattr(self, "approve_breakdown_box", None),
                    show_breakdown_box,
                    fill=tk.X,
                    pady=(0, 10),
                    before=getattr(self, "approve_btn_frame", None),
                )
                self._set_widget_packed(
                    getattr(self, "approve_breakdown_lbl", None),
                    bool(show_breakdown_box and not breakdown_table_rows),
                    fill=tk.X,
                    pady=(4, 4),
                )
                self._set_widget_packed(
                    getattr(self, "approve_breakdown_table_frame", None),
                    bool(show_breakdown_box and breakdown_table_rows),
                    fill=tk.X,
                    pady=(6, 8),
                )
                self._set_widget_packed(
                    getattr(self, "approve_breakdown_canvas", None),
                    bool(show_breakdown_box),
                    fill=tk.X,
                )
            self._render_compact_info_table(
                getattr(self, "approve_breakdown_table_frame", None),
                breakdown_table_rows,
                default_value_tone="success",
                reuse_existing=lightweight,
            )
            if not lightweight:
                self._normalize_approve_panel_order()
    except Exception:
        pass

    try:
        self._set_widget_packed(
            getattr(self, "preview_list_summary_lbl", None),
            bool(str(left_summary_text or "").strip()),
            anchor=tk.W,
            fill=tk.X,
            pady=(0, 2),
        )
    except Exception:
        pass

    legend_counts = (
        ("preview_list_legend_ok_count_lbl", visible_auto_images),
        ("preview_list_legend_corrected_count_lbl", visible_manual_images),
        ("preview_list_legend_problem_count_lbl", visible_problem_images),
        ("preview_list_legend_dirty_count_lbl", visible_approved_images),
    )
    legend_count_width = max(
        3,
        len(
            str(
                max(
                    int(visible_count or 0),
                    int(visible_auto_images or 0),
                    int(visible_manual_images or 0),
                    int(visible_problem_images or 0),
                    int(visible_approved_images or 0),
                )
            )
        ),
    )
    for widget_name, value in legend_counts:
        widget = getattr(self, widget_name, None)
        if widget is None:
            continue
        try:
            widget.configure(text=str(int(value)), width=legend_count_width)
        except Exception:
            pass
    try:
        total_widget = getattr(self, "preview_list_legend_total_count_lbl", None)
        if total_widget is not None:
            total_text = f"{visible_count} / {len(annotations)}"
            total_widget.configure(text=total_text, width=max(7, len(total_text)))
        total_label = getattr(self, "preview_list_legend_total_lbl", None)
        if total_label is not None:
            total_label.configure(text="Zdjęcia")
    except Exception:
        pass
    try:
        self._sync_preview_left_counter_layout_width()
    except Exception:
        pass

def _parse_cvat_preview_annotations(self, xml_path: Path) -> list[ImageAnnotation]:
    cache_key = None
    try:
        safe_xml_path = Path(xml_path)
        stat = safe_xml_path.stat()
        cache_key = (
            str(safe_xml_path.resolve()).lower(),
            int(getattr(stat, "st_mtime_ns", 0) or 0),
            int(getattr(stat, "st_size", 0) or 0),
        )
        cache = getattr(self, "_cvat_preview_annotation_cache", None)
        if isinstance(cache, dict) and cache.get("key") == cache_key:
            cached_annotations = cache.get("annotations")
            if isinstance(cached_annotations, list):
                return copy.deepcopy(cached_annotations)
    except Exception:
        cache_key = None

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

            polygon = PolygonValidator.fix_polygon(points[:4], quiet=True)
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
            elif polygon_source == "auto":
                attributes.setdefault("annotation_origin", "auto")
                attributes.setdefault("auto_source", "auto_annotation")

            detection = Detection(
                label="plate",
                confidence=confidence,
                bbox=self._bbox_from_polygon(polygon),
                keypoints=self._keypoints_from_polygon(polygon),
                polygon=polygon,
                attributes=attributes,
            )
            try:
                setattr(detection, "_cvat_source", polygon_source or "auto")
            except Exception:
                pass
            detections.append(detection)

        annotations.append(
            ImageAnnotation(
                filename=filename,
                width=width,
                height=height,
                detections=detections,
            status=(
                AnnotationStatus.SUCCESS
                if any(
                    str(det.label or "").strip().lower() in CONFIG.PLATE_LABELS
                    or str(det.label or "").strip().lower() in CONFIG.VEHICLE_LABELS
                    for det in detections
                )
                else AnnotationStatus.NO_PLATE
            ),
            )
        )

    if cache_key is not None and annotations:
        try:
            self._cvat_preview_annotation_cache = {
                "key": cache_key,
                "annotations": copy.deepcopy(annotations),
            }
        except Exception:
            pass

    return annotations

def _open_preview_metric_filter_modal(self):
    if bool(getattr(self, "_plate_auto_scope_modal_open", False)):
        return

    dialog = tk.Toplevel(self.frame)
    try:
        dialog.title("Ustaw filtr jakości listy")
        dialog.transient(getattr(self.app, "root", None) or self.frame.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)
    except Exception:
        pass

    palette = getattr(self.app, "palette", {}) or {}
    panel_bg = palette.get("panel", "#252526")
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    try:
        dialog.configure(bg=panel_bg)
    except Exception:
        pass

    body = tk.Frame(dialog, bg=panel_bg, bd=0, highlightthickness=0)
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

    tk.Label(
        body,
        text="Filtr widoku listy jakości detekcji",
        bg=panel_bg,
        fg=fg,
        font=("Segoe UI", 10, "bold"),
        anchor="w",
        justify=tk.LEFT,
    ).pack(anchor=tk.W, fill=tk.X)

    tk.Label(
        body,
        text="Te progi zmieniają tylko to, które pozycje widzisz na liście Z2. Nie zmieniają zawartości runu.",
        bg=panel_bg,
        fg=muted,
        font=("Segoe UI", 9),
        anchor="w",
        justify=tk.LEFT,
        wraplength=420,
    ).pack(anchor=tk.W, fill=tk.X, pady=(6, 12))

    conf_var = tk.DoubleVar(value=float(self.preview_filter_conf_var.get() or 0.0))
    fit_var = tk.DoubleVar(value=float(self.preview_filter_fit_var.get() or 0.0))

    grid = tk.Frame(body, bg=panel_bg, bd=0, highlightthickness=0)
    grid.pack(fill=tk.X)
    grid.columnconfigure(1, weight=1)

    tk.Label(
        grid,
        text="Min. Det",
        bg=panel_bg,
        fg=fg,
        font=("Segoe UI", 9, "bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="w", pady=(0, 8))
    ttk.Spinbox(
        grid,
        from_=0.0,
        to=1.0,
        increment=0.05,
        width=8,
        format="%.2f",
        textvariable=conf_var,
    ).grid(row=0, column=1, sticky="w", pady=(0, 8))

    tk.Label(
        grid,
        text="Min. Fit",
        bg=panel_bg,
        fg=fg,
        font=("Segoe UI", 9, "bold"),
        anchor="w",
    ).grid(row=1, column=0, sticky="w")
    ttk.Spinbox(
        grid,
        from_=0.0,
        to=1.0,
        increment=0.05,
        width=8,
        format="%.2f",
        textvariable=fit_var,
    ).grid(row=1, column=1, sticky="w")

    buttons = tk.Frame(body, bg=panel_bg, bd=0, highlightthickness=0)
    buttons.pack(fill=tk.X, pady=(14, 0))

    def close_without_save():
        try:
            dialog.destroy()
        except Exception:
            pass

    def save_settings():
        try:
            self.preview_filter_conf_var.set(float(conf_var.get() or 0.0))
            self.preview_filter_fit_var.set(float(fit_var.get() or 0.0))
        except Exception:
            pass
        self._refresh_preview_filter_bar_state()
        close_without_save()

    ttk.Button(buttons, text="Anuluj", command=close_without_save).pack(side=tk.RIGHT)
    ttk.Button(buttons, text="Zapisz", command=save_settings).pack(side=tk.RIGHT, padx=(0, 8))

    try:
        self._fit_borderless_dialog(dialog, parent=self.frame, min_width=480, min_height=240)
        dialog.update_idletasks()
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
    except Exception:
        pass

    try:
        dialog.bind("<Escape>", lambda _e: close_without_save())
    except Exception:
        pass
    dialog.wait_window()

def _get_preview_image_file_metadata(self, ann, canvas: ZoomableCanvas | None = None) -> dict[str, object]:
    metadata: dict[str, object] = {
        "path": "",
        "width": 0,
        "height": 0,
        "dpi_text": "",
        "file_available": False,
    }
    image_path = self._resolve_preview_image_path(ann)
    file_path: Path | None = None
    if image_path is not None:
        try:
            candidate = Path(image_path)
            if candidate.is_file():
                file_path = candidate
        except Exception:
            file_path = None

    cache = getattr(self, "_preview_image_meta_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        self._preview_image_meta_cache = cache

    if file_path is not None:
        try:
            stat = file_path.stat()
            cache_key = ("image-file-meta", str(file_path), int(stat.st_mtime_ns), int(stat.st_size))
        except Exception:
            cache_key = ("image-file-meta", str(file_path), 0, 0)

        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            metadata.update(cached)
        else:
            width = 0
            height = 0
            dpi_text = ""
            try:
                with Image.open(file_path) as image:
                    try:
                        width = max(1, int(getattr(image, "width", 0) or image.size[0] or 0))
                        height = max(1, int(getattr(image, "height", 0) or image.size[1] or 0))
                    except Exception:
                        width = height = 0
                    info = dict(getattr(image, "info", {}) or {})
                    dpi_text = self._format_preview_dpi_value(info.get("dpi"))
                    if not dpi_text:
                        density = info.get("jfif_density")
                        unit = int(info.get("jfif_unit", 0) or 0)
                        if isinstance(density, (list, tuple)) and len(density) >= 2 and unit in {1, 2}:
                            factor = 1.0 if unit == 1 else 2.54
                            dpi_text = self._format_preview_dpi_value(
                                (float(density[0]) * factor, float(density[1]) * factor)
                            )
            except Exception:
                width = height = 0
                dpi_text = ""

            if not dpi_text:
                dpi_text = "DPI: brak w pliku"
            file_metadata = {
                "path": str(file_path),
                "width": int(width),
                "height": int(height),
                "dpi_text": dpi_text,
                "file_available": True,
            }
            metadata.update(file_metadata)
            cache[cache_key] = file_metadata
            if len(cache) > 160:
                try:
                    for key in list(cache.keys())[:40]:
                        cache.pop(key, None)
                except Exception:
                    pass

    width = int(metadata.get("width", 0) or 0)
    height = int(metadata.get("height", 0) or 0)
    dimensions_trusted = bool(width > 0 and height > 0 and bool(metadata.get("file_available")))
    if (width <= 0 or height <= 0) and canvas is not None:
        try:
            original_image = getattr(canvas, "original_image", None)
            if original_image is not None:
                used_canvas_dimensions = False
                if width <= 0:
                    width = max(1, int(getattr(original_image, "width", 0) or 0))
                    used_canvas_dimensions = True
                if height <= 0:
                    height = max(1, int(getattr(original_image, "height", 0) or 0))
                    used_canvas_dimensions = True
                if used_canvas_dimensions and width > 0 and height > 0:
                    dimensions_trusted = True
        except Exception:
            pass
    if width <= 0 or height <= 0:
        try:
            ann_width = int(getattr(ann, "width", 0) or 0)
            ann_height = int(getattr(ann, "height", 0) or 0)
            if width <= 0:
                width = ann_width if ann_width > 0 else 0
            if height <= 0:
                height = ann_height if ann_height > 0 else 0
        except Exception:
            pass

    metadata["width"] = int(width)
    metadata["height"] = int(height)
    if not str(metadata.get("dpi_text", "") or "").strip():
        metadata["dpi_text"] = "DPI: brak w pliku" if bool(metadata.get("file_available")) else "DPI: brak pliku"

    try:
        if ann is not None and dimensions_trusted:
            if width > 0 and int(getattr(ann, "width", 0) or 0) != int(width):
                ann.width = int(width)
            if height > 0 and int(getattr(ann, "height", 0) or 0) != int(height):
                ann.height = int(height)
    except Exception:
        pass
    return metadata

def _update_preview_edit_status(
    self,
    extra_message: str | None = None,
    *,
    refresh_toolbar: bool = True,
    refresh_debug: bool = True,
    refresh_legend: bool = False,
):
    if extra_message:
        self.preview_edit_status_var.set(extra_message)
        if refresh_toolbar:
            self._update_preview_toolbar_state(refresh_summary=False)
        if refresh_debug:
            self._refresh_preview_debug_status()
        if refresh_legend:
            self._refresh_preview_controls_legend()
        return

    ann = self._get_preview_annotation()
    if ann is None:
        self.preview_edit_status_var.set("Po zakończeniu anotacji tutaj poprawisz rogi tablic.")
        if refresh_toolbar:
            self._update_preview_toolbar_state(refresh_summary=False)
        if refresh_legend:
            self._refresh_preview_controls_legend()
        return

    if not self._preview_is_editable():
        self.preview_edit_status_var.set(
            f"{ann.filename} | tryb tylko do podglądu. Najpierw kliknij {self._get_step2_start_action_reference()}, aby przygotować annotations.xml albo uruchomić autoanotację."
            f"{self._preview_campaign_reuse_manual_note(ann, editable=False)}"
        )
        if refresh_toolbar:
            self._update_preview_toolbar_state(refresh_summary=False)
        if refresh_debug:
            self._refresh_preview_debug_status()
        if refresh_legend:
            self._refresh_preview_controls_legend()
        return

    plates = self._get_plate_detections(ann)
    vehicles = self._get_vehicle_detections(ann)
    dirty_note = " | zapis automatyczny w toku" if ann.filename in self._preview_dirty_images else ""
    selected_vehicle_idx = self._get_selected_vehicle_index_for_ann(ann)
    vehicle_hint = ""
    if vehicles:
        vehicle_no = 1 if selected_vehicle_idx is None else (int(selected_vehicle_idx) + 1)
        vehicle_hint = f" Aktywny pojazd {vehicle_no}/{len(vehicles)}."

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
        nav_hint = (
            "Q/E przełącza poprzednią/następną tablicę w zestawie."
            if bool(getattr(self, "_preview_super_correction_active", False))
            else "Q/E przełącza poprzednie/następne zdjęcie na liście."
        )
        self.preview_edit_status_var.set(
            f"{ann.filename} | tablica {plate_no}/{len(plates)}{dirty_note}. "
            "Kliknij polygon, aby go wybrać, przeciągnij róg, aby poprawić geometrię. "
            f"{nav_hint}"
        )
        drag_hint = "Przytrzymaj W i przeciągnij róg, aby poprawić geometrię."
        super_hint = (
            "Y wyłącza super korektę."
            if bool(getattr(self, "_preview_super_correction_active", False))
            else "Y włącza super korektę."
        )
        fullscreen_hint = (
            "Enter wychodzi z pełnego ekranu."
            if self._preview_fullscreen_active
            else "Enter otwiera pełny ekran - najwygodniejszy tryb korekty ramek."
        )
        self.preview_edit_status_var.set(
            f"{ann.filename} | tablica {plate_no}/{len(plates)}{dirty_note}. "
            f"Kliknij polygon, aby go wybrać. {drag_hint} "
            f"{nav_hint} A przełącza tablice lokalnie, Spacja zatwierdza lub cofa zatwierdzenie zdjęcia, R kadruje aktywny polygon, R+LPM robi płynny zoom x2 do punktu, R+PPM cofa ten zoom, F dopasowuje cały obraz do okna podglądu, D rysuje nowy polygon, S uzbraja usuwanie, Del usuwa zdjęcie, Ctrl+Z/Ctrl+Y cofają i ponawiają, Ctrl+S zapisuje poprawki, {super_hint} {fullscreen_hint}{vehicle_hint}"
            f"{self._preview_campaign_reuse_manual_note(ann, editable=True)}"
        )

    if refresh_toolbar:
        self._update_preview_toolbar_state(refresh_summary=False)
    if refresh_debug:
        self._refresh_preview_debug_status()
    if refresh_legend:
        self._refresh_preview_controls_legend()

def _save_preview_edits(
    self,
    *,
    interactive: bool = True,
    status_message: str | None = None,
    refresh_list: bool = True,
    refresh_workflow: bool = True,
    refresh_export_sources: bool = True,
):
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
            messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać poprawek do:\n{xml_path}")
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
            manual_touched_filenames=sorted(self._collect_preview_manually_touched_filenames()),
            approved_filenames=sorted(self._get_preview_approved_filenames()),
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
    try:
        dirty_lookup = {
            str(name or "").strip().lower()
            for name in set(getattr(self, "_preview_dirty_images", set()) or set())
            if str(name or "").strip()
        }
        dirty_manual_now = {
            filename
            for ann in list(self.current_annotations or [])
            for filename in [str(getattr(ann, "filename", "") or "").strip()]
            if filename
            and filename.lower() in dirty_lookup
            and self._preview_annotation_has_manual_touch_direct(ann)
        }
        if dirty_manual_now:
            self._campaign_iteration_manual_filenames = set(
                getattr(self, "_campaign_iteration_manual_filenames", set()) or set()
            )
            self._campaign_iteration_manual_filenames.update(dirty_manual_now)
    except Exception:
        pass

    saved_preview_index = self.current_preview_index
    self._preview_dirty_images.clear()
    if refresh_list:
        self._refresh_preview_list(preserve_selection=True, render_current=False)
    else:
        self._refresh_preview_list_row_for_actual_index(saved_preview_index, refresh_summary=True)

    if refresh_export_sources:
        self._refresh_plate_dataset_export_sources()
    if refresh_workflow:
        self._refresh_step2_action_states()
        if self._is_free_mode_session_context():
            try:
                self._refresh_free_mode_manual_right_panel(reuse_existing_tables=True)
            except Exception:
                pass
            try:
                self._set_plate_annotation_export_button_state()
            except Exception:
                pass
        self._refresh_free_mode_workflow_ui()
    self._push_preview_debug_event("save", f"xml={xml_path.name}")
    self._update_preview_edit_status(
        status_message or "Zapisano poprawki polygonow do annotations.xml. Kolejny etap zobaczy juz nowe rogi."
    )
    self._queue_free_mode_session_save()
    return True

def _clear_selected_preview_auto_plates(self) -> None:
    if not self._ensure_preview_is_editable_for_action():
        self._update_preview_edit_status(
            "Czyszczenie auto będzie dostępne dopiero po przygotowaniu annotations.xml."
        )
        return

    annotations = list(self.current_annotations or [])
    if not annotations:
        self._update_preview_edit_status("Brak obrazów w bieżącym runie Z2.")
        return

    selected_actual_indices = list(range(len(annotations)))
    preserved_display_indices = []
    try:
        if getattr(self, "preview_listbox", None) is not None:
            preserved_display_indices = list(self.preview_listbox.curselection() or ())
    except Exception:
        preserved_display_indices = []

    approved_names = set(self._get_preview_approved_filenames())
    changed_images = 0
    removed_polygons = 0

    for actual_index in selected_actual_indices:
        if actual_index < 0 or actual_index >= len(self.current_annotations or []):
            continue
        ann = self.current_annotations[actual_index]
        plate_detections = self._get_plate_detections(ann)
        if not plate_detections:
            continue

        kept_detections = []
        removed_here = 0
        for det in list(getattr(ann, "detections", []) or []):
            if not self._is_plate_detection_label(getattr(det, "label", "")):
                kept_detections.append(det)
                continue

            attributes = dict(getattr(det, "attributes", {}) or {})
            manually_edited = str(attributes.get("manually_edited", "") or "").strip().lower() == "true"
            manual_source = str(attributes.get("manual_source", "") or "").strip().lower()
            if manually_edited or manual_source:
                kept_detections.append(det)
                continue

            removed_here += 1

        if removed_here <= 0:
            continue

        self._push_preview_history_snapshot(ann)
        ann.detections = kept_detections
        if self._get_plate_detections(ann):
            ann.status = AnnotationStatus.SUCCESS
            ann.status_message = "Usunięto automatyczne polygony tablic; zachowano ręczne poprawki."
        else:
            ann.status = AnnotationStatus.NO_PLATE
            ann.status_message = "Usunięto automatyczne polygony tablic."
        self._set_selected_plate_index_for_ann(ann, None)
        self._mark_preview_image_dirty(ann, refresh_list=False)

        filename = str(getattr(ann, "filename", "") or "").strip().lower()
        if filename and filename in approved_names and not self._get_plate_detections(ann):
            approved_names.discard(filename)
            try:
                setattr(ann, "_approved_for_training", False)
            except Exception:
                pass

        changed_images += 1
        removed_polygons += removed_here

    if changed_images <= 0:
        self._update_preview_edit_status(
            "W bieżącym runie Z2 nie ma automatycznych ramek tablic do usunięcia."
        )
        return

    self._preview_approved_filenames = approved_names
    if not self._is_free_mode_session_context():
        self._campaign_pending_approved_filenames = set(approved_names)
    self._persist_preview_approved_filenames()
    self._refresh_preview_list(preserve_selection=True, render_current=False)

    restored_display_indices = list(preserved_display_indices)
    try:
        self._clear_listbox_selection_fast(self.preview_listbox)
        for display_index in restored_display_indices:
            self.preview_listbox.selection_set(display_index)
        if restored_display_indices:
            self.preview_listbox.activate(restored_display_indices[-1])
            self.preview_listbox.see(restored_display_indices[-1])
    except Exception:
        pass

    try:
        self._load_current_preview_selection(reset_view=False, selection_changed=False)
    except Exception:
        pass

    self._refresh_preview_list_summary(lightweight=bool(len(entries) >= 1200))
    self._refresh_step2_action_states()
    self._update_preview_toolbar_state()
    self._queue_free_mode_session_save()
    self._update_preview_edit_status(
        f"Usunięto automatyczne ramki tablic z całego runu: {changed_images} obrazów ({removed_polygons} polygonów)."
    )
