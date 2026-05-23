#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka Treningu: trening YOLO + analiza modeli.

W trybie swobodnym Z4 konsumuje gotowy dataset z Z2 lub Z3.
Pomost datasetowy pozostaje tylko na potrzeby kampanii.
"""

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
from ..validators import validate_yolo_dataset, validate_model_file, format_yolo_model_identity
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..ranking import ModelRanking, ModelRankingEntry
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
    TrainingInputContext,
    Z4CampaignRuntimeState,
    Z4CtaState,
    Z4FreeModeRuntimeState,
    Z4LayoutState,
)
from .z4_free_mode_flow import (
    bind_training_route_card,
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
from .z4_view_models import (
    Step4CampaignNavigationViewModel,
    Step4DatasetWorkflowViewModel,
    Step4TrainingInputsViewModel,
)

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageTk, ImageDraw, ImageFont

YOLO = None


class TrainProgressBar(tk.Canvas):
    def __init__(
        self,
        master,
        *,
        variable=None,
        maximum: float = 100.0,
        value: float = 0.0,
        mode: str = "determinate",
        thickness: int = 6,
        trough_color: str = "#3c3c3c",
        fill_color: str = "#4ec9b0",
        segment_ratio: float = 0.28,
        **kwargs,
    ):
        canvas_height = max(int(kwargs.pop("height", thickness + 6)), int(thickness) + 6)
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
        self._mode = str(mode or "determinate").strip().lower() or "determinate"
        self._thickness = max(1, int(thickness))
        self._trough_color = str(trough_color)
        self._fill_color = str(fill_color)
        self._segment_ratio = max(0.12, min(0.50, float(segment_ratio)))
        self._variable = None
        self._variable_trace_id = None
        self._indeterminate_after_id = None
        self._indeterminate_running = False
        self._indeterminate_interval_ms = 40
        self._indeterminate_phase = 0.0

        self._trough_id = self.create_line(0, 0, 0, 0, capstyle=tk.ROUND)
        self._fill_id = self.create_line(0, 0, 0, 0, capstyle=tk.ROUND)
        self.bind("<Configure>", lambda _event: self._redraw(), add="+")

        self._set_variable(variable)
        self.configure(value=value)

    def _set_variable(self, variable):
        if self._variable is variable:
            return

        if self._variable is not None and self._variable_trace_id is not None:
            try:
                self._variable.trace_remove("write", self._variable_trace_id)
            except Exception:
                pass

        self._variable = variable
        self._variable_trace_id = None

        if variable is None:
            return

        try:
            self._variable_trace_id = variable.trace_add("write", lambda *_args: self._sync_variable_value())
        except Exception:
            self._variable_trace_id = None

        self._sync_variable_value()

    def _sync_variable_value(self):
        variable = getattr(self, "_variable", None)
        if variable is None:
            return

        try:
            self._value = max(0.0, float(variable.get()))
        except Exception:
            return

        self._redraw()

    def _redraw(self):
        width = max(1.0, float(self.winfo_width()))
        height = max(1.0, float(self.winfo_height()))
        center_y = height / 2.0
        half_thickness = max(0.5, float(self._thickness) / 2.0)
        left = half_thickness + 1.0
        right = max(left, width - half_thickness - 1.0)

        self.coords(self._trough_id, left, center_y, right, center_y)
        self.itemconfigure(self._trough_id, fill=self._trough_color, width=self._thickness)

        if self._mode == "indeterminate":
            if self._indeterminate_running:
                span = max(12.0, (right - left) * self._segment_ratio)
                travel = max(1.0, (right - left) + span)
                start = left - span + (travel * self._indeterminate_phase)
                end = start + span
                visible_start = max(left, start)
                visible_end = min(right, end)
                if visible_end <= visible_start:
                    visible_start = left
                    visible_end = left
            else:
                visible_start = left
                visible_end = left
        else:
            ratio = max(0.0, min(1.0, float(self._value) / max(1.0, float(self._maximum))))
            visible_start = left
            visible_end = left + ((right - left) * ratio)

        self.coords(self._fill_id, visible_start, center_y, max(visible_start, visible_end), center_y)
        self.itemconfigure(self._fill_id, fill=self._fill_color, width=self._thickness)

    def _tick_indeterminate(self):
        self._indeterminate_after_id = None
        if not self._indeterminate_running:
            return

        self._indeterminate_phase = (float(self._indeterminate_phase) + 0.04) % 1.0
        self._redraw()

        try:
            self._indeterminate_after_id = self.after(
                max(16, int(self._indeterminate_interval_ms)),
                self._tick_indeterminate,
            )
        except Exception:
            self._indeterminate_after_id = None

    def start(self, interval: int | None = None):
        if interval is not None:
            try:
                self._indeterminate_interval_ms = max(16, int(interval))
            except Exception:
                pass

        self._indeterminate_running = True
        if self._indeterminate_after_id is None:
            self._tick_indeterminate()

    def stop(self):
        self._indeterminate_running = False
        pending = self._indeterminate_after_id
        self._indeterminate_after_id = None
        if pending is not None:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._redraw()

    def configure(self, cnf=None, **kwargs):
        if cnf is not None and not isinstance(cnf, dict):
            return super().configure(cnf, **kwargs)

        merged = {}
        if isinstance(cnf, dict):
            merged.update(cnf)
        merged.update(kwargs)

        if "variable" in merged:
            self._set_variable(merged.pop("variable"))
        if "maximum" in merged:
            self._maximum = max(1.0, float(merged.pop("maximum")))
        if "value" in merged:
            self._value = max(0.0, float(merged.pop("value")))
        if "mode" in merged:
            self._mode = str(merged.pop("mode") or "determinate").strip().lower() or "determinate"
            if self._mode != "indeterminate":
                self.stop()
        if "thickness" in merged:
            self._thickness = max(1, int(merged.pop("thickness")))
            merged.setdefault("height", self._thickness + 6)
        if "trough_color" in merged:
            self._trough_color = str(merged.pop("trough_color"))
        if "fill_color" in merged:
            self._fill_color = str(merged.pop("fill_color"))

        background = merged.pop("background", None)
        bg = merged.pop("bg", None)
        resolved_bg = background if background is not None else bg
        if resolved_bg is not None:
            super().configure(bg=resolved_bg)

        result = super().configure(**merged)
        self._redraw()
        return result

    config = configure

    def destroy(self):
        self.stop()
        if self._variable is not None and self._variable_trace_id is not None:
            try:
                self._variable.trace_remove("write", self._variable_trace_id)
            except Exception:
                pass
        self._variable = None
        self._variable_trace_id = None
        super().destroy()


class TrainingTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager

        self.frame = ttk.Frame(parent)
        self._inertial_scroll = InertialScrollController(self.frame)
        self._startup_ui_ready = False

        self.history = TrainingHistory(history_dir=Path(CONFIG.get_training_runs_dir("char")))
        self.trainer = YOLOPoseTrainer(history=self.history)
        self.creator = DatasetCreator()
        self.splitter = DatasetSplitter()
        self.ranking_engine = ModelRanking(ranking_dir=Path(CONFIG.get_ranking_dir("plate")))

        self.current_run_id = None
        self._pending_campaign_model_type = None
        self._campaign_training_target = "char"
        self._step4_dataset_mode = "char"
        self._step4_builder_log_visible = False
        self._step4_train_log_visible = False
        self._current_training_dataset_is_pose = None
        self._step4_campaign_finish_ready = False
        self._step4_route_selected = False
        self._step4_train_unlocked = False
        self._training_completion_poll_job = None
        # Kontekst projektu jest ustawiany przez wizard kampanii.
        self._campaign_runs_dir = None
        self._campaign_datasets_dir = None
        self._plots_paths = []
        self._plot_photo = None
        self._plot_img_id = None
        self._plot_original_path = None
        self._free_route_hover_mode = None
        self._free_training_route_cards = {}
        self._training_device_profiles = []
        self._training_device_label_map = {}
        self._training_auto_device_label = "Auto"
        self._training_cpu_device_label = "CPU"
        self._step4_ranking_tab_visible = False
        self._train_left_wrap_targets = []
        self._train_left_section_separators = []
        self._latest_training_metrics = {}
        self._last_training_completion_summary_run_id = None
        self._dynamic_metric_tables = []
        self._analysis_dialog = None
        self._analysis_dialog_shell = None
        self._analysis_plot_paths = []
        self._analysis_plot_canvas = None
        self._analysis_plots_list = None
        self._ui_dispatch_queue = queue.Queue()
        self._ui_dispatch_after_id = None
        self._train_pane_layout_initialized = False
        self._training_visible_layout_after_id = None
        self._training_started_monotonic = None
        self._training_started_wall_clock = None
        self._training_eta_seconds = None
        self._training_last_epoch = 0
        self._training_last_total_epochs = 0
        self._training_last_batch = 0
        self._training_last_total_batches = 0

        self.is_processing = False
        self.dataset_build_is_running = False
        self.dataset_split_is_running = False
        self.val_is_running = False
        self.rank_is_running = False
        self.rank_cancel_requested = False
        self._rank_watchdog_job = None
        self._rank_watchdog_last_touch = 0.0
        self._rank_watchdog_last_notice = 0.0
        self._rank_watchdog_stage = ""
        self._rank_watchdog_warn_after_s = 15.0
        self._rank_watchdog_repeat_s = 15.0

        self._build_ui()
        self._ensure_ui_dispatch_pump()
        self._attach_training_log_handlers()
        self._bind_trainer_callbacks()
        self._load_history()
        self._load_ranking()
        self._on_base_model_change()
        self.frame.after_idle(self._mark_startup_ui_ready)

    def _mark_startup_ui_ready(self):
        try:
            self._configure_train_progress_styles()
        except Exception:
            pass
        self._startup_ui_ready = True

    def is_startup_ui_ready(self) -> bool:
        return bool(getattr(self, "_startup_ui_ready", False))

    def _ui(self, fn):
        if not callable(fn):
            return

        if threading.current_thread() is threading.main_thread():
            try:
                self.frame.after(0, fn)
            except Exception:
                try:
                    fn()
                except Exception:
                    pass
            return

        try:
            self._ui_dispatch_queue.put_nowait(fn)
        except Exception:
            pass

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
                pass

        try:
            self._ui_dispatch_after_id = self.frame.after(20, self._drain_ui_dispatch_queue)
        except Exception:
            self._ui_dispatch_after_id = None

    @staticmethod
    def _capture_text_widget_view_state(text_widget) -> dict:
        state = {
            "insert": None,
            "x_first": 0.0,
            "y_first": 0.0,
            "view_at_end": True,
            "insert_at_end": True,
            "sel_first": None,
            "sel_last": None,
        }
        if text_widget is None:
            return state

        try:
            state["insert"] = text_widget.index(tk.INSERT)
        except Exception:
            state["insert"] = None

        try:
            x_first, _x_last = text_widget.xview()
            state["x_first"] = float(x_first)
        except Exception:
            state["x_first"] = 0.0

        try:
            y_first, y_last = text_widget.yview()
            state["y_first"] = float(y_first)
            state["view_at_end"] = float(y_last) >= 0.999
        except Exception:
            state["y_first"] = 0.0
            state["view_at_end"] = True

        try:
            state["insert_at_end"] = bool(text_widget.compare(tk.INSERT, ">=", "end-2c"))
        except Exception:
            state["insert_at_end"] = True

        try:
            state["sel_first"] = text_widget.index("sel.first")
            state["sel_last"] = text_widget.index("sel.last")
        except Exception:
            state["sel_first"] = None
            state["sel_last"] = None

        return state

    @staticmethod
    def _restore_text_widget_view_state(text_widget, state: dict) -> None:
        if text_widget is None or not isinstance(state, dict):
            return

        try:
            insert_index = state.get("insert")
            if insert_index:
                text_widget.mark_set(tk.INSERT, str(insert_index))
        except Exception:
            pass

        try:
            text_widget.xview_moveto(float(state.get("x_first", 0.0) or 0.0))
        except Exception:
            pass

        try:
            text_widget.yview_moveto(float(state.get("y_first", 0.0) or 0.0))
        except Exception:
            pass

        try:
            text_widget.tag_remove(tk.SEL, "1.0", tk.END)
            sel_first = state.get("sel_first")
            sel_last = state.get("sel_last")
            if sel_first and sel_last:
                text_widget.tag_add(tk.SEL, str(sel_first), str(sel_last))
        except Exception:
            pass

    def _append_to_step4_process_console(self, text: str, *, autoscroll_if_at_end: bool = True) -> None:
        widget = getattr(self, "train_log_console", None)
        if widget is None:
            return

        payload = self._sanitize_training_text(text)
        if not payload:
            return

        try:
            state_before = self._capture_text_widget_view_state(widget)
            follow_end = bool(autoscroll_if_at_end and state_before.get("view_at_end") and state_before.get("insert_at_end"))
            widget.config(state=tk.NORMAL)
            widget.insert(tk.END, payload)
            if follow_end:
                widget.see(tk.END)
            else:
                self._restore_text_widget_view_state(widget, state_before)
        except Exception:
            pass
        finally:
            try:
                widget.config(state=tk.DISABLED)
            except Exception:
                pass

    def _append_train_log(self, message: str, mirror_global: bool = True):
        """Bezpieczne dopisywanie linii do konsoli treningu z dowolnego wątku."""
        text = self._sanitize_training_text(message)
        if not text:
            return
        if not text.endswith("\n"):
            text += "\n"

        if mirror_global:
            self._ui(
                lambda message=text.rstrip("\n"): (
                    self.app.append_global_terminal(message, source="Z4")
                    if hasattr(self.app, "append_global_terminal")
                    else None
                )
            )

        def update():
            try:
                self._append_to_step4_process_console(text)
            except Exception:
                pass
        self._ui(update)

    def _append_ranking_log(self, message: str):
        text = str(message or "").strip()
        if not text:
            return
        self._append_train_log(f"[RANKING] {text}")

    @staticmethod
    def _sanitize_training_text(message) -> str:
        text = "" if message is None else str(message)
        if not text:
            return ""
        suspicious_tokens = ("Ä", "Å", "Ĺ", "Ă", "â", "Ђ", "€", "™", "�")
        if any(token in text for token in suspicious_tokens):
            candidates = [text]
            for source_encoding in ("latin1", "cp1252"):
                try:
                    repaired = text.encode(source_encoding, errors="ignore").decode("utf-8", errors="ignore")
                    if repaired:
                        candidates.append(repaired)
                except Exception:
                    pass

            def score(candidate: str) -> tuple[int, int]:
                suspicious = sum(candidate.count(token) for token in suspicious_tokens)
                replacement = candidate.count("�") + candidate.count("?")
                return (suspicious + replacement, -len(candidate))

            try:
                text = min(candidates, key=score)
            except Exception:
                pass

        replacements = {
            "â": "–",
            "â": "—",
            "â¦": "…",
            "â": "„",
            "â": "\"",
            "â": "\"",
            "â": "'",
            "â": "'",
            "Â ": " ",
        }
        for broken, fixed in replacements.items():
            if broken in text:
                text = text.replace(broken, fixed)
        return text

    def _set_training_widget_text(self, widget, text) -> None:
        if widget is None:
            return
        try:
            widget.configure(text=self._sanitize_training_text(text))
        except Exception:
            pass

    def _set_training_stringvar_text(self, variable, text) -> None:
        if variable is None:
            return
        try:
            variable.set(self._sanitize_training_text(text))
        except Exception:
            pass

    def _start_ranking_watchdog(self, stage: str):
        self._stop_ranking_watchdog()
        self._touch_ranking_watchdog(stage)
        try:
            self._rank_watchdog_job = self.frame.after(3000, self._poll_ranking_watchdog)
        except Exception:
            self._rank_watchdog_job = None

    def _touch_ranking_watchdog(self, stage: str | None = None):
        self._rank_watchdog_last_touch = time.perf_counter()
        if stage is not None:
            self._rank_watchdog_stage = str(stage or "").strip()

    def _stop_ranking_watchdog(self):
        job = getattr(self, "_rank_watchdog_job", None)
        self._rank_watchdog_job = None
        if job is not None:
            try:
                self.frame.after_cancel(job)
            except Exception:
                pass

    def _poll_ranking_watchdog(self):
        self._rank_watchdog_job = None
        if not (getattr(self, "rank_is_running", False) or getattr(self, "rank_cancel_requested", False)):
            return

        now = time.perf_counter()
        last_touch = float(getattr(self, "_rank_watchdog_last_touch", 0.0) or 0.0)
        stalled_for = max(0.0, now - last_touch)
        warn_after = float(getattr(self, "_rank_watchdog_warn_after_s", 15.0) or 15.0)
        repeat_after = float(getattr(self, "_rank_watchdog_repeat_s", 15.0) or 15.0)

        if stalled_for >= warn_after:
            last_notice = float(getattr(self, "_rank_watchdog_last_notice", 0.0) or 0.0)
            if (last_notice <= 0.0) or ((now - last_notice) >= repeat_after):
                stage = str(getattr(self, "_rank_watchdog_stage", "") or "nieznany etap")
                seconds = int(round(stalled_for))
                self._rank_watchdog_last_notice = now
                if getattr(self, "rank_cancel_requested", False):
                    self._append_ranking_log(
                        f"Watchdog: nadal czekam na zatrzymanie od {seconds}s | ostatni etap: {stage}."
                    )
                else:
                    self._append_ranking_log(
                        f"Watchdog: brak nowego postepu od {seconds}s | etap: {stage}. "
                        "Możesz poczekac albo kliknac 'Anuluj ranking'."
                    )
                self._set_ranking_ui_state(
                    status=(
                        f"Czekam na zatrzymanie od {seconds}s | {stage}"
                        if getattr(self, "rank_cancel_requested", False)
                        else f"Bez nowego postepu od {seconds}s | {stage}"
                    ),
                    status_color="#d35400",
                    cancel_enabled=not getattr(self, "rank_cancel_requested", False),
                )

        if getattr(self, "rank_is_running", False) or getattr(self, "rank_cancel_requested", False):
            try:
                self._rank_watchdog_job = self.frame.after(3000, self._poll_ranking_watchdog)
            except Exception:
                self._rank_watchdog_job = None

    def _get_active_step4_operation_label(self) -> str:
        if bool(getattr(self.trainer, "is_training", False)):
            return "trening modelu"
        if bool(getattr(self, "dataset_build_is_running", False)):
            return "przygotowanie datasetu tablic"
        if bool(getattr(self, "dataset_split_is_running", False)):
            return "przygotowanie datasetu znaków"
        if bool(getattr(self, "val_is_running", False)):
            return "walidacja modelu"
        if bool(getattr(self, "rank_is_running", False)):
            return "ranking modeli"
        if bool(getattr(self, "is_processing", False)):
            return "operacja Z4"
        return ""

    def _step4_has_active_operation(self) -> bool:
        return bool(self._get_active_step4_operation_label())

    def _begin_step4_operation(self, owner: str, label: str) -> bool:
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "try_begin_exclusive_operation"):
            ok, busy_message = app.try_begin_exclusive_operation(owner, label)
            if not ok:
                messagebox.showinfo("Proces w toku", busy_message)
                return False
        else:
            try:
                self.app.set_processing(True)
            except Exception:
                pass
        self.is_processing = True
        try:
            self._refresh_training_start_state()
        except Exception:
            pass
        return True

    def _end_step4_operation(self, owner: str):
        self.is_processing = False
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "end_exclusive_operation"):
            app.end_exclusive_operation(owner)
        else:
            try:
                self.app.set_processing(False)
            except Exception:
                pass
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

    def _set_ranking_ui_state(
        self,
        *,
        status: str | None = None,
        status_color: str | None = None,
        button_text: str | None = None,
        cancel_enabled: bool | None = None,
        preparing: bool | None = None,
        progress_value: float | None = None,
    ):
        def update():
            if button_text is not None and hasattr(self, "btn_run_rank"):
                try:
                    self.btn_run_rank.config(text=button_text)
                except Exception:
                    pass

            if cancel_enabled is not None and hasattr(self, "btn_cancel_rank"):
                try:
                    self.btn_cancel_rank.config(state=(tk.NORMAL if cancel_enabled else tk.DISABLED))
                except Exception:
                    pass

            if status is not None and hasattr(self, "rank_status"):
                try:
                    kwargs = {"text": status}
                    if status_color is not None:
                        kwargs["foreground"] = status_color
                    self.rank_status.configure(**kwargs)
                except Exception:
                    pass

            progress = getattr(self, "rank_progress", None)
            if progress is not None and preparing is not None:
                try:
                    progress.stop()
                except Exception:
                    pass
                try:
                    progress.configure(mode="indeterminate" if preparing else "determinate")
                except Exception:
                    pass
                if preparing:
                    try:
                        progress.start(12)
                    except Exception:
                        pass

            if progress_value is not None:
                try:
                    self.rank_progress_var.set(float(progress_value))
                except Exception:
                    pass

        self._ui(update)

    def _attach_training_log_handlers(self):
        """Przekierowuje logi aplikacji i Ultralytics do konsoli treningu w GUI."""
        if getattr(self, "_training_log_handlers_attached", False):
            return

        import logging

        class GuiLogHandler(logging.Handler):
            def __init__(self, owner):
                super().__init__()
                self.owner = owner

            def emit(self, record):
                try:
                    msg = self.format(record)
                    if msg:
                        self.owner._append_train_log(msg, mirror_global=False)
                except Exception:
                    pass

        fmt = logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S")
        raw_fmt = logging.Formatter("%(message)s")

        # Handler dla loggera aplikacji.
        self._gui_app_log_handler = GuiLogHandler(self)
        self._gui_app_log_handler.setFormatter(fmt)
        logger.addHandler(self._gui_app_log_handler)

        # Handler dla loggera Ultralytics.
        self._gui_yolo_log_handler = GuiLogHandler(self)
        self._gui_yolo_log_handler.setFormatter(raw_fmt)

        self._ultralytics_logger = logging.getLogger("ultralytics")
        self._ultralytics_logger.addHandler(self._gui_yolo_log_handler)

        self._training_log_handlers_attached = True

    @staticmethod
    def _metric_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _describe_metric_band(value: float, profile: str) -> tuple[str, str]:
        val = max(0.0, min(1.0, float(value)))
        if profile == "strict_map":
            if val < 0.40:
                return "slaby", "< 0.40"
            if val < 0.60:
                return "używalny", "0.40 - 0.60"
            if val < 0.80:
                return "dobry", "0.60 - 0.80"
            return "bardzo dobry", "> 0.80"

        if profile == "loose_map":
            if val < 0.70:
                return "slaby", "< 0.70"
            if val < 0.85:
                return "używalny", "0.70 - 0.85"
            if val < 0.93:
                return "dobry", "0.85 - 0.93"
            return "bardzo dobry", "> 0.93"

        if val < 0.60:
            return "slaby", "< 0.60"
        if val < 0.75:
            return "używalny", "0.60 - 0.75"
        if val < 0.90:
            return "dobry", "0.75 - 0.90"
        return "bardzo dobry", "> 0.90"

    def _build_training_metric_reference_text(self) -> str:
        target = self.get_campaign_training_target()
        if target == "plate":
            return (
                "Zakresy orientacyjne dla tablic: kluczowe jest pose mAP50-95 (rogi). "
                "< 0.40 = słabo | 0.40 - 0.60 = używalnie | 0.60 - 0.80 = dobrze | > 0.80 = bardzo dobrze. "
                "Dla mAP50: < 0.70 = słabo | 0.70 - 0.85 = używalnie | 0.85 - 0.93 = dobrze | > 0.93 = bardzo dobrze. "
                "Loss porównuj tylko między epokami tego samego treningu - z czasem powinien raczej spadać."
            )

        return (
            "Zakresy orientacyjne: kluczowe jest mAP50-95. "
            "< 0.40 = słabo | 0.40 - 0.60 = używalnie | 0.60 - 0.80 = dobrze | > 0.80 = bardzo dobrze. "
            "Dla mAP50: < 0.70 = słabo | 0.70 - 0.85 = używalnie | 0.85 - 0.93 = dobrze | > 0.93 = bardzo dobrze. "
            "Loss porównuj tylko względem poprzednich epok tego samego treningu."
        )

    def _refresh_training_metric_reference(self):
        label = getattr(self, "train_metric_reference_lbl", None)
        if label is None:
            return
        self._set_training_widget_text(label, self._build_training_metric_reference_text())

    def _set_training_metric_interpretation(self, text: str):
        label = getattr(self, "train_metric_hint_lbl", None)
        if label is None:
            return
        self._set_training_widget_text(label, str(text or "").strip())

    def _build_training_metric_interpretation(self, metrics: dict | None) -> str:
        if not isinstance(metrics, dict) or not metrics:
            return "Interpretacja pojawi się po pierwszej zakończonej epoce."

        target = self.get_campaign_training_target()
        loss = self._metric_float(metrics.get("loss", 0.0))

        if target == "plate":
            strict_value = self._metric_float(metrics.get("pose_map50_95", metrics.get("map50_95", 0.0)))
            loose_value = self._metric_float(metrics.get("pose_map50", metrics.get("map50", 0.0)))
            strict_name = "pose mAP50-95 (rogi)"

            strict_label, strict_range = self._describe_metric_band(strict_value, "strict_map")
            loose_label, loose_range = self._describe_metric_band(loose_value, "loose_map")

            if strict_value < 0.40:
                note = "Model dopiero uczy się precyzji rogów; do rektyfikacji będzie jeszcze dużo poprawek ręcznych."
            elif strict_value < 0.60:
                note = "Wynik jest już używalny do dalszej autoanotacji, ale rogi tablic nadal będą wymagaly korekt."
            elif strict_value < 0.80:
                note = "Rogi są lokalizowane dobrze; model nadaje się do codziennej pracy i dalszego dotrenowania."
            else:
                note = "Rogi są lapane bardzo dobrze; to mocny poziom do autoanotacji i rektyfikacji."

            return (
                f"Interpretacja: {strict_name} = {strict_value:.3f} -> {strict_label} ({strict_range}); "
                f"mAP50 = {loose_value:.3f} -> {loose_label} ({loose_range}); "
                f"loss = {loss:.3f} i powinien z czasem spadac. {note}"
            )

        strict_value = self._metric_float(metrics.get("map50_95", 0.0))
        loose_value = self._metric_float(metrics.get("map50", 0.0))
        strict_label, strict_range = self._describe_metric_band(strict_value, "strict_map")
        loose_label, loose_range = self._describe_metric_band(loose_value, "loose_map")

        if strict_value < 0.40:
            note = "Model wykrywa jeszcze zbyt malo stabilnie, wiec potrzeba dalszego treningu albo lepszego datasetu."
        elif strict_value < 0.60:
            note = "Wynik jest już używalny, ale model nadal będzie się mylic w trudniejszych przypadkach."
        elif strict_value < 0.80:
            note = "Model wykrywa dobrze i nadaje się do praktycznej pracy."
        else:
            note = "Model wykrywa bardzo dobrze i jest gotowy do mocnego użycia."

        return (
            f"Interpretacja: mAP50-95 = {strict_value:.3f} -> {strict_label} ({strict_range}); "
            f"mAP50 = {loose_value:.3f} -> {loose_label} ({loose_range}); "
            f"loss = {loss:.3f} i powinien z czasem spadac. {note}"
        )

    @staticmethod
    def _shorten_training_text(value, limit: int = 58) -> str:
        text = str(value or "").strip()
        if not text:
            return "-"
        if len(text) <= int(limit):
            return text
        if int(limit) <= 3:
            return text[:limit]
        return text[: max(1, int(limit) - 3)] + "..."

    @staticmethod
    def _format_training_metric_name(metric_key: str) -> str:
        mapping = {
            "loss": "Loss",
            "map50": "mAP50",
            "map50_95": "mAP50-95",
            "precision": "Precision",
            "recall": "Recall",
            "box_map50": "Box mAP50",
            "box_map50_95": "Box mAP50-95",
            "box_precision": "Box precision",
            "box_recall": "Box recall",
            "pose_map50": "Pose mAP50",
            "pose_map50_95": "Pose mAP50-95",
            "pose_precision": "Pose precision",
            "pose_recall": "Pose recall",
        }
        return mapping.get(str(metric_key or "").strip(), str(metric_key or "").strip() or "Metryka")

    def _resolve_training_metric_profile(self, metric_key: str) -> str | None:
        raw = str(metric_key or "").strip().lower()
        if not raw:
            return None
        if raw == "loss":
            return None
        if "map50_95" in raw or raw.endswith("map"):
            return "strict_map"
        if "map50" in raw:
            return "loose_map"
        if "precision" in raw or "recall" in raw:
            return "standard"
        return None

    def _format_training_metric_value(self, metric_key: str, value) -> str:
        if value in (None, "", "-"):
            return "-"
        try:
            numeric = float(value)
        except Exception:
            return str(value)
        if str(metric_key or "").strip().lower() == "loss":
            return f"{numeric:.3f}"
        return f"{numeric:.3f}"

    def _format_training_metric_band(self, metric_key: str, value) -> tuple[str, str]:
        raw = str(metric_key or "").strip().lower()
        if value in (None, "", "-"):
            return "-", "-"
        if raw == "loss":
            return "monitoruj", "powinien spadac"
        try:
            numeric = float(value)
        except Exception:
            return "-", "-"

        profile = self._resolve_training_metric_profile(raw)
        if not profile:
            return "-", "-"

        label, range_text = self._describe_metric_band(numeric, profile)
        return label, range_text

    def _iter_training_metric_keys(self, target: str | None = None) -> list[str]:
        normalized_target = CONFIG.normalize_task_target(target or self.get_campaign_training_target())
        if normalized_target == "plate":
            return [
                "pose_map50_95",
                "pose_map50",
                "box_map50_95",
                "box_map50",
                "loss",
            ]
        return [
            "map50_95",
            "map50",
            "precision",
            "recall",
            "loss",
        ]

    def _build_training_metric_rows(self, metrics: dict | None, target: str | None = None) -> list[tuple[str, str, str, str]]:
        if not isinstance(metrics, dict) or not metrics:
            return []

        rows: list[tuple[str, str, str, str]] = []
        for key in self._iter_training_metric_keys(target):
            value = metrics.get(key)
            if value is None and key == "pose_map50_95":
                value = metrics.get("map50_95")
            elif value is None and key == "pose_map50":
                value = metrics.get("map50")
            elif value is None and key == "box_map50_95":
                value = metrics.get("map50_95")
            elif value is None and key == "box_map50":
                value = metrics.get("map50")

            if value is None:
                continue

            band, range_text = self._format_training_metric_band(key, value)
            rows.append(
                (
                    self._format_training_metric_name(key),
                    self._format_training_metric_value(key, value),
                    band,
                    range_text,
                )
            )
        return rows

    def _build_training_run_detail_rows(self, run) -> list[tuple[str, str]]:
        if run is None:
            return []

        dataset_display = self._shorten_training_text(
            self._format_workspace_relative_path(getattr(run, "dataset_path", "")),
            72,
        )
        best_weights = self._shorten_training_text(Path(getattr(run, "best_weights", "") or "").name or "-", 36)
        last_weights_raw = str(getattr(run, "last_weights", "") or "").strip()
        last_weights_name = self._shorten_training_text(Path(last_weights_raw).name or "-", 36) if last_weights_raw else "-"
        base_model = self._shorten_training_text(Path(getattr(run, "base_model", "") or "").name or "-", 36)
        created_at = str(getattr(run, "created_at", "") or "").replace("T", " ")
        resumable = self._is_history_run_resume_allowed(run)
        technically_resumable = self._is_history_run_resumable(run)

        return [
            ("Status", self._format_history_run_status_label(run)),
            ("Dataset", dataset_display),
            ("Model bazowy", base_model),
            ("Postep", f"{int(getattr(run, 'current_epoch', 0) or 0)}/{int(getattr(run, 'epochs', 0) or 0)} epok"),
            (
                "Ustawienia",
                (
                    f"rozdzielczosc wejsciowa {int(getattr(run, 'img_size', 0) or 0)} px | "
                    f"rozmiar partii {int(getattr(run, 'batch_size', 0) or 0)} | "
                    f"wspolczynnik uczenia {float(getattr(run, 'lr0', 0.0) or 0.0):.4f}"
                ),
            ),
            ("Urządzenie", self._shorten_training_text(str(getattr(run, "device", "") or "-"), 28)),
            ("Najlepsze wagi", best_weights),
            ("Checkpoint last.pt", last_weights_name),
            (
                "Wznowienie",
                "TAK"
                if resumable
                else "NIE (archiwalny paused)"
                if technically_resumable
                else "NIE",
            ),
            ("Utworzono", self._shorten_training_text(created_at or "-", 32)),
        ]

    def _build_training_run_metric_rows(self, run) -> list[tuple[str, str, str, str]]:
        if run is None:
            return []

        history = list(getattr(run, "metrics_history", []) or [])
        if not history:
            latest_map = getattr(run, "best_map50", 0.0) or 0.0
            latest_map95 = getattr(run, "best_map50_95", 0.0) or 0.0
            fallback_metrics = {
                "map50": latest_map,
                "map50_95": latest_map95,
            }
            live_rows = self._build_training_metric_rows(fallback_metrics, self._infer_dataset_target(getattr(run, "dataset_path", "")))
            return [(label, value, value, band) for label, value, band, _range in live_rows]

        latest = history[-1]
        target = self._infer_dataset_target(getattr(run, "dataset_path", "")) or self.get_campaign_training_target()
        rows: list[tuple[str, str, str, str]] = []

        for key in self._iter_training_metric_keys(target):
            numeric_values: list[float] = []
            for item in history:
                try:
                    if key in item:
                        numeric_values.append(float(item[key]))
                    elif key == "pose_map50_95" and "map50_95" in item:
                        numeric_values.append(float(item["map50_95"]))
                    elif key == "pose_map50" and "map50" in item:
                        numeric_values.append(float(item["map50"]))
                    elif key == "box_map50_95" and "map50_95" in item:
                        numeric_values.append(float(item["map50_95"]))
                    elif key == "box_map50" and "map50" in item:
                        numeric_values.append(float(item["map50"]))
                except Exception:
                    continue

            latest_value = latest.get(key)
            if latest_value is None and key == "pose_map50_95":
                latest_value = latest.get("map50_95")
            elif latest_value is None and key == "pose_map50":
                latest_value = latest.get("map50")
            elif latest_value is None and key == "box_map50_95":
                latest_value = latest.get("map50_95")
            elif latest_value is None and key == "box_map50":
                latest_value = latest.get("map50")

            if latest_value is None and not numeric_values:
                continue

            if str(key).lower() == "loss":
                best_value = min(numeric_values) if numeric_values else latest_value
            else:
                best_value = max(numeric_values) if numeric_values else latest_value

            band, _range_text = self._format_training_metric_band(key, best_value)
            rows.append(
                (
                    self._format_training_metric_name(key),
                    self._format_training_metric_value(key, latest_value),
                    self._format_training_metric_value(key, best_value),
                    band,
                )
            )

        return rows

    def _set_train_live_metrics(self, metrics: dict | None):
        rows = self._build_training_metric_rows(metrics)
        self._set_metric_table_rows(getattr(self, "train_live_metrics_tree", None), rows)

    def _build_training_recommendation_rows(self) -> tuple[str, str, list[tuple[str, ...]], str]:
        recommendation = self._get_training_device_recommendation(self._get_global_training_device_choice())
        memory_gb = float(recommendation.get("memory_gb", 0.0) or 0.0)
        if recommendation.get("effective_raw") == "cpu":
            device_label = "Wykryty sprzęt: CPU"
        else:
            device_label = (
                f"Wykryty sprzęt: {recommendation.get('device_name', 'GPU')} | "
                f"{memory_gb:.1f} GB VRAM"
            )
        model_label = str(recommendation.get("model_detected_label") or "").strip()
        if not model_label:
            model_label = self._build_training_recommendation_model_text()

        model_identity = str(
            recommendation.get("model_identity_label")
            or recommendation.get("model_detected_label")
            or recommendation.get("model_label")
            or ""
        ).strip()
        if not model_identity:
            model_identity = self._build_training_recommendation_model_text().replace("Model:", "", 1).strip() or "-"

        model_variant_parts = [
            str(recommendation.get("model_version_label") or "").strip(),
            str(recommendation.get("model_size_label") or "").strip(),
        ]
        model_params_text = str(recommendation.get("model_params_text") or "").strip()
        if model_params_text:
            model_variant_parts.append(f"{model_params_text} param.")
        model_variant_text = " | ".join(part for part in model_variant_parts if part) or "Nie rozpoznano z nazwy/pliku .pt"

        rows = [
            ("Model bazowy", model_identity, "punkt odniesienia"),
            ("Wersja / rozmiar", model_variant_text, "większy model = niższy batch"),
            ("1. Epoki (ustawiasz ręcznie)", "Twoja decyzja"),
            ("2. Rozmiar partii", str(int(recommendation.get("batch", 0) or 0))),
            ("3. Rozdzielczość wejściowa", str(int(recommendation.get("imgsz", 0) or 0))),
            ("4. Współczynnik uczenia", f"{float(recommendation.get('lr0', 0.0) or 0.0):.4f}"),
        ]
        note = str(
            recommendation.get("note")
            or "Jeśli zabraknie pamięci, najpierw zmniejsz rozmiar partii, a potem rozdzielczość wejściową."
        )
        return device_label, model_label, rows, note

    def _refresh_training_recommendation_table(self):
        hardware_text, model_text, rows, note_text = self._build_training_recommendation_rows()
        hardware_label = getattr(self, "train_recommendation_hardware_label", None)
        self._set_training_widget_text(hardware_label, hardware_text)
        model_label = getattr(self, "train_recommendation_model_label", None)
        self._set_training_widget_text(model_label, model_text)

        cells = list(getattr(self, "_train_recommendation_cells", []) or [])
        for row_index, row_values in enumerate(rows):
            if len(row_values) >= 3:
                label_text, current_text, recommended_text = row_values[:3]
            else:
                label_text, recommended_text = row_values[:2]
                current_text = None
            if row_index >= len(cells):
                continue
            row = cells[row_index]
            self._set_training_widget_text(row.get("key"), str(label_text))
            if current_text is not None:
                self._set_training_widget_text(row.get("current"), str(current_text))
            self._set_training_widget_text(row.get("recommended"), str(recommended_text))

        note_var = getattr(self, "train_recommendation_note_var", None)
        self._set_training_stringvar_text(note_var, note_text)

    def _apply_training_recommendation_table_theme(self):
        palette = getattr(self.app, "palette", {})
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        header_bg = palette.get("panel_alt", "#2d2d30")
        header_fg = palette.get("muted", "#c7c7c7")
        cell_bg = palette.get("panel", "#252526")
        cell_fg = palette.get("fg", "#f3f3f3")
        title_bg = palette.get("panel_alt", "#2d2d30")
        title_fg = palette.get("fg", "#f3f3f3")
        hardware_bg = palette.get("panel", "#252526")
        hardware_fg = palette.get("muted", "#c7c7c7")
        subtle_bg = palette.get("surface_success", header_bg)
        subtle_fg = palette.get("fg", "#f3f3f3")

        shell = getattr(self, "train_recommendation_table_shell", None)
        grid = getattr(self, "train_recommendation_grid", None)
        title_row = getattr(self, "train_recommendation_title_row", None)
        if shell is not None:
            try:
                shell.configure(bg=border, highlightbackground=border, highlightcolor=border)
            except Exception:
                pass
        if grid is not None:
            try:
                grid.configure(bg=border)
            except Exception:
                pass
        if title_row is not None:
            try:
                title_row.configure(bg=title_bg)
            except Exception:
                pass

        for label_name, bg, fg in (
            ("train_recommendation_title_label", title_bg, title_fg),
            ("train_recommendation_hardware_label", hardware_bg, hardware_fg),
            ("train_recommendation_model_label", hardware_bg, hardware_fg),
        ):
            label = getattr(self, label_name, None)
            if label is None:
                continue
            try:
                label.configure(bg=bg, fg=fg)
            except Exception:
                pass

        for label in list(getattr(self, "_train_recommendation_header_labels", []) or []):
            if label is None:
                continue
            try:
                label.configure(bg=header_bg, fg=header_fg)
            except Exception:
                pass

        for row_index, row in enumerate(list(getattr(self, "_train_recommendation_cells", []) or [])):
            key_widget = row.get("key")
            current_widget = row.get("current")
            editor_host = row.get("editor_host")
            recommended_widget = row.get("recommended")
            key_bg = header_bg if row_index % 2 == 1 else cell_bg
            editor_bg = header_bg if row_index % 2 == 1 else cell_bg
            if key_widget is not None:
                try:
                    key_widget.configure(bg=key_bg, fg=cell_fg)
                except Exception:
                    pass
            if editor_host is not None:
                try:
                    editor_host.configure(bg=editor_bg, highlightbackground=editor_bg, highlightcolor=editor_bg)
                except Exception:
                    pass
            if current_widget is not None:
                try:
                    current_widget.configure(bg=editor_bg, fg=cell_fg)
                except Exception:
                    pass
            if recommended_widget is not None:
                try:
                    recommended_widget.configure(bg=subtle_bg, fg=subtle_fg)
                except Exception:
                    pass

    def _apply_training_device_recommendation(self):
        self._apply_training_recommended_start_params()

    def _on_training_base_model_value_write(self, *_args):
        try:
            self._refresh_training_base_model_selection_ui()
        except Exception:
            pass
        try:
            self._refresh_training_execution_summary()
        except Exception:
            pass
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

    def _schedule_step4_deferred_model_refresh(self):
        frame = getattr(self, "frame", None)
        if frame is None:
            return

        pending_job = getattr(self, "_step4_deferred_model_refresh_job", None)
        if pending_job is not None:
            try:
                frame.after_cancel(pending_job)
            except Exception:
                pass

        def run_refresh():
            self._step4_deferred_model_refresh_job = None
            try:
                self._refresh_base_model_choices()
            except Exception:
                pass
            try:
                self._apply_training_recommended_start_params()
            except Exception:
                pass
            try:
                self._refresh_training_execution_summary()
            except Exception:
                pass

        try:
            self._step4_deferred_model_refresh_job = frame.after(25, run_refresh)
        except Exception:
            self._step4_deferred_model_refresh_job = None

    def _apply_training_recommended_start_params(self):
        recommendation = self._get_training_device_recommendation(self._get_global_training_device_choice())
        try:
            current_batch = self._safe_training_int_value("batch_var", default=16, minimum=1)
            self.batch_var.set(int(recommendation.get("batch", current_batch) or current_batch))
        except Exception:
            pass
        try:
            current_imgsz = self._safe_training_int_value("imgsz_var", default=640, minimum=32)
            self.imgsz_var.set(int(recommendation.get("imgsz", current_imgsz) or current_imgsz))
        except Exception:
            pass
        try:
            current_lr0 = self._safe_training_float_value("lr0_var", default=0.01, minimum=0.0001)
            self.lr0_var.set(float(recommendation.get("lr0", current_lr0) or current_lr0))
        except Exception:
            pass
        self._refresh_training_recommendation_table()
        self._refresh_training_start_state()

    def _safe_training_numeric_var_value(
        self,
        attr_name: str,
        *,
        default,
        cast,
        minimum=None,
    ):
        var_obj = getattr(self, attr_name, None)
        raw_value = None
        if var_obj is not None:
            try:
                raw_value = var_obj.get()
            except Exception:
                raw_value = None

        try:
            value = cast(raw_value)
        except Exception:
            value = cast(default)

        if minimum is not None:
            try:
                value = max(cast(minimum), value)
            except Exception:
                pass
        return value

    def _safe_training_int_value(self, attr_name: str, *, default: int, minimum: int | None = None) -> int:
        return int(
            self._safe_training_numeric_var_value(
                attr_name,
                default=int(default),
                cast=lambda value: int(float(value)),
                minimum=minimum,
            )
        )

    def _safe_training_float_value(self, attr_name: str, *, default: float, minimum: float | None = None) -> float:
        return float(
            self._safe_training_numeric_var_value(
                attr_name,
                default=float(default),
                cast=float,
                minimum=minimum,
            )
        )

    def _resolve_training_dataset_yaml_path(self) -> Path | None:
        dataset_value = str(getattr(self, "dataset_var", tk.StringVar()).get() or "").strip()
        if not dataset_value:
            return None

        candidate = Path(dataset_value)
        if candidate.is_dir():
            yaml_path = candidate / "data.yaml"
            return yaml_path if yaml_path.exists() else None
        if candidate.is_file() and candidate.name.lower() == "data.yaml":
            return candidate
        return None

    def _looks_like_char_classification_dataset(self, path_like) -> bool:
        try:
            path = Path(path_like)
        except Exception:
            return False

        if path.is_file():
            if path.name.lower() == "manifest.json":
                manifest_path = path
                root = path.parent
            else:
                root = path.parent
                manifest_path = root / "manifest.json"
        else:
            root = path
            manifest_path = root / "manifest.json"

        if not manifest_path.exists():
            return False

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            dataset_type = str(data.get("dataset_type") or "").strip().lower()
            if dataset_type == "char_classification":
                return True
        except Exception:
            pass

        try:
            has_class_splits = all((root / split).exists() for split in ("train", "val", "test"))
            has_yolo_shape = (root / "images").exists() or (root / "labels").exists() or (root / "data.yaml").exists()
            return bool(has_class_splits and not has_yolo_shape)
        except Exception:
            return False

    def _char_classification_dataset_message(self) -> str:
        return (
            "Wybrane źródło wygląda na dataset OCR/klasyfikacyjny znaków (manifest.json). "
            "Z4/PZ1/PZ2 trenuje tutaj modele YOLO, więc wymaga datasetu YOLO Detect: "
            "folderu z images/labels oraz data.yaml. Wybierz np. katalog YOLO_MegaDataset_Chars_* "
            "albo najpierw wygeneruj/wyeksportuj dataset YOLO dla znaków. "
            "Datasety klasyfikacyjne są odkładane osobno w 4_training_datasets/4_char_classification."
        )

    def _is_training_configuration_ready(self) -> bool:
        if not YOLO_AVAILABLE:
            return False
        if self._step4_has_active_operation():
            return False
        if bool(getattr(self.trainer, "is_training", False)):
            return False

        yaml_path = self._resolve_training_dataset_yaml_path()
        if yaml_path is None:
            return False
        if not CAMPAIGN.get_active_project_name():
            if not self._is_free_training_dataset_variant_selected(yaml_path.parent):
                return False

        selected_target = self._get_selected_training_target()
        inferred_target = self._infer_dataset_target(str(yaml_path.parent))
        if inferred_target and inferred_target != selected_target:
            return False

        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        if not base_key:
            return False
        if base_key == "Custom":
            custom_model = str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()
            if not custom_model or not Path(custom_model).exists():
                return False
            valid_selection, _selection_message = self._validate_training_base_model_target_compatibility(
                target=selected_target,
                show_dialog=False,
            )
            if not valid_selection:
                return False

        return True

    def _validate_training_base_model_target_compatibility(
        self,
        *,
        target: str | None = None,
        show_dialog: bool = False,
    ) -> tuple[bool, str]:
        normalized_target = CONFIG.normalize_task_target(target or self._get_selected_training_target())
        if normalized_target not in {"char", "plate"}:
            return True, ""

        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        if not base_key:
            return False, "Nie wybrano modelu bazowego."

        base_model = (
            str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()
            if base_key == "Custom"
            else base_key
        )
        if not base_model:
            return False, "Nie wybrano modelu bazowego."

        if base_key == "Custom":
            try:
                model_path = Path(base_model)
            except Exception:
                model_path = None
            if model_path is None or not model_path.exists():
                return False, "Wskaż poprawny plik modelu .pt."

            ok, message, _info = validate_model_file(model_path)
            if not ok:
                if show_dialog:
                    messagebox.showerror(
                        "Nieprawidłowy model",
                        f"Nie udało się użyć wybranego modelu:\n{message}",
                    )
                return False, message

        is_pose_model = self._is_pose_base_model(base_key, base_model)
        if normalized_target == "plate" and not is_pose_model:
            message = (
                "Tor tablic wymaga modelu POSE.\n\n"
                "Wybierz model z dopiskiem '-pose' albo model .pt wytrenowany wcześniej dla tablic."
            )
            if show_dialog:
                messagebox.showerror("Niezgodny model bazowy", message)
            return False, message

        if normalized_target == "char" and is_pose_model:
            message = (
                "Tor znaków wymaga zwykłego modelu DETECT.\n\n"
                "Wybierz model typu detect, np. `yolo11n` albo `yolo11s`, "
                "zamiast modelu pose."
            )
            if show_dialog:
                messagebox.showerror("Niezgodny model bazowy", message)
            return False, message

        return True, ""

    def _refresh_training_start_state(self):
        button = getattr(self, "btn_start_train", None)
        if button is None:
            return
        try:
            button.configure(state=(tk.NORMAL if self._is_training_configuration_ready() else tk.DISABLED))
        except Exception:
            pass
        try:
            self._refresh_training_execution_summary()
        except Exception:
            pass
        try:
            self._refresh_training_base_model_identity_ui()
        except Exception:
            pass

    def _refresh_training_base_model_identity_ui(self):
        label = getattr(self, "train_base_identity_lbl", None)
        if label is None:
            return

        lines = self._build_selected_training_base_model_identity_lines()
        text = "\n".join(lines).strip()
        try:
            label.configure(text=text)
        except Exception:
            pass
        try:
            if text:
                if not str(label.winfo_manager()):
                    label.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))
            else:
                label.pack_forget()
        except Exception:
            pass

    def _resolve_selected_training_base_model_display(self) -> str:
        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        if not base_key:
            return "Nie wybrano modelu"
        if base_key != "Custom":
            return base_key

        custom_model = str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()
        if not custom_model:
            return "Custom (brak pliku .pt)"
        try:
            return f"Custom -> {Path(custom_model).name}"
        except Exception:
            return f"Custom -> {custom_model}"

    def _resolve_selected_training_base_model_path(self) -> Path | None:
        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        if base_key != "Custom":
            return None

        custom_model = str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()
        if not custom_model:
            return None

        try:
            model_path = Path(custom_model)
        except Exception:
            return None
        return model_path if model_path.exists() else None

    def _resolve_selected_training_base_model_inspection_path(self) -> Path | None:
        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        if not base_key:
            return None
        if base_key == "Custom":
            return self._resolve_selected_training_base_model_path()

        target = self._get_selected_training_target()
        catalog = AVAILABLE_POSE_MODELS if target == "plate" else AVAILABLE_DETECT_MODELS
        entry = catalog.get(base_key, {}) if isinstance(catalog, dict) else {}
        candidate_names = [str(entry.get("file") or "").strip(), base_key]
        search_roots = [Path.cwd(), CONFIG.get_base_models_dir(target)]

        for candidate_name in candidate_names:
            if not candidate_name:
                continue
            try:
                direct_path = Path(candidate_name)
            except Exception:
                continue
            if direct_path.exists():
                return direct_path
            for root in search_roots:
                try:
                    candidate_path = root / candidate_name
                except Exception:
                    continue
                if candidate_path.exists():
                    return candidate_path
        return None

    def _resolve_selected_training_base_model_info(self) -> tuple[Path | None, dict]:
        model_path = self._resolve_selected_training_base_model_inspection_path()
        if model_path is None or not model_path.exists():
            return None, {}
        ok, _message, info = validate_model_file(model_path)
        return model_path, info if ok and isinstance(info, dict) else {}

    def _build_selected_training_base_model_identity_lines(self) -> list[str]:
        model_path, info = self._resolve_selected_training_base_model_info()
        if model_path is None or not info:
            return []

        lines: list[str] = []
        identity_label = format_yolo_model_identity(info)
        if identity_label:
            lines.append(f"Wykryto z pliku .pt: {identity_label}")

        source_architecture = str(info.get("source_architecture_label") or "").strip()
        source_model_name = str(info.get("source_model_name") or "").strip()
        source_display = source_architecture or source_model_name
        is_checkpoint_like = (
            model_path.name.lower() == "best.pt"
            or model_path.stem.lower().startswith("epoch")
        )
        if is_checkpoint_like and source_display and source_model_name:
            lines.append(f"Model po wcześniejszym treningu: {source_display}")

        return lines

    def _build_training_recommendation_model_text(self) -> str:
        model_path, info = self._resolve_selected_training_base_model_info()
        base_display = self._resolve_selected_training_base_model_display()
        identity_label = format_yolo_model_identity(info)
        if not identity_label:
            return f"Model: {base_display}"

        source_architecture = str(info.get("source_architecture_label") or "").strip()
        source_model_name = str(info.get("source_model_name") or "").strip()
        source_display = source_architecture or source_model_name
        is_checkpoint_like = bool(
            model_path is not None
            and (
                model_path.name.lower() == "best.pt"
                or model_path.stem.lower().startswith("epoch")
            )
        )

        text = f"Model: {identity_label}"
        if is_checkpoint_like and source_display:
            text += f" | po wcześniejszym treningu: {source_display}"
        return text

    @staticmethod
    def _format_training_model_run_label(run) -> str:
        if run is None:
            return "-"
        run_name = str(getattr(run, "name", "") or "").strip()
        run_id = str(getattr(run, "id", "") or "").strip()
        if run_name and run_id and run_name != run_id:
            return f"{run_name} [{run_id}]"
        return run_name or run_id or "-"

    @staticmethod
    def _format_training_model_size_label(raw_size: str | None) -> str:
        size = str(raw_size or "").strip().lower()
        labels = {
            "n": "n (najmniejszy)",
            "s": "s (mały)",
            "m": "m (średni)",
            "l": "l (duży)",
            "x": "x (bardzo duży)",
        }
        return labels.get(size, size)

    def _build_training_model_summary_value(self, base_display: str, info: dict | None) -> str:
        if not isinstance(info, dict) or not info:
            return base_display

        identity_label = format_yolo_model_identity(info)
        version = str(info.get("yolo_version") or "").strip()
        size = self._format_training_model_size_label(
            str(info.get("yolo_size") or info.get("model_scale") or "").strip().lower()
        )

        extras: list[str] = []
        if version:
            extras.append(f"wersja {version}")
        if size:
            extras.append(f"rozmiar {size}")

        if identity_label and extras:
            return f"{identity_label} | {', '.join(extras)}"
        if identity_label:
            return identity_label
        return base_display

    @staticmethod
    def _resolve_training_model_version_from_info(info: dict | None) -> str:
        if not isinstance(info, dict):
            return ""
        version = str(info.get("yolo_version") or "").strip()
        return f"YOLO {version}" if version else ""

    def _resolve_training_model_size_from_info(self, info: dict | None) -> str:
        if not isinstance(info, dict):
            return ""
        return self._format_training_model_size_label(
            str(info.get("yolo_size") or info.get("model_scale") or "").strip().lower()
        )

    @staticmethod
    def _get_pose_model_memory_bucket(info: dict | None) -> str:
        if not isinstance(info, dict):
            return ""
        size = str(info.get("yolo_size") or info.get("model_scale") or "").strip().lower()
        if size in {"n", "s", "m", "l", "x"}:
            return size

        architecture = str(info.get("architecture_label") or info.get("source_architecture_label") or "").strip().lower()
        for candidate in ("x", "l", "m", "s", "n"):
            if f"yolo26{candidate}" in architecture or f"yolo11{candidate}" in architecture or f"yolov8{candidate}" in architecture:
                return candidate
        return ""

    def _get_training_gpu_capacity_block_reason(
        self,
        *,
        is_pose_dataset: bool,
        base_model_info: dict | None,
        effective_device_profile: dict | None,
    ) -> str:
        if not is_pose_dataset:
            return ""
        if not isinstance(effective_device_profile, dict):
            return ""

        try:
            memory_gb = float(effective_device_profile.get("memory_gb", 0.0) or 0.0)
        except Exception:
            memory_gb = 0.0
        if memory_gb <= 0.0:
            return ""

        bucket = self._get_pose_model_memory_bucket(base_model_info)
        if bucket not in {"m", "l", "x"}:
            return ""
        if memory_gb > 4.5:
            return ""

        architecture_label = format_yolo_model_identity(base_model_info) or "duży model YOLO Pose"
        gpu_name = str(effective_device_profile.get("name") or "GPU").strip()
        return (
            f"Wybrany model bazowy to {architecture_label}, a aktywne urządzenie to {gpu_name} "
            f"z około {memory_gb:.1f} GB VRAM.\n\n"
            "Ten rozmiar modelu pose na 4 GB VRAM w obecnym środowisku kończy się błędami pamięci CUDA "
            "jeszcze przed stabilnym startem treningu albo w pierwszych batchach.\n\n"
            "Aby trening miał realną szansę powodzenia:\n"
            "1. wybierz mniejszy model pose, najlepiej `yolo11s-pose` albo `yolo26s-pose`,\n"
            "2. albo uruchom trening na CPU,\n"
            "3. albo użyj GPU z większym VRAM, jeśli chcesz kontynuować właśnie ten model."
        )

    def _resolve_training_run_from_model_path(self, model_path: Path | None):
        if model_path is None:
            return None

        try:
            resolved_model_path = model_path.resolve()
        except Exception:
            resolved_model_path = model_path

        history = getattr(self, "history", None)
        if history is None:
            return None

        try:
            runs = list(history.get_all_runs() or [])
        except Exception:
            runs = []

        for run in runs:
            best_weights = str(getattr(run, "best_weights", "") or "").strip()
            if not best_weights:
                continue
            try:
                if Path(best_weights).resolve() == resolved_model_path:
                    return run
            except Exception:
                continue

        for run in runs:
            output_dir = str(getattr(run, "output_dir", "") or "").strip()
            if not output_dir:
                continue
            try:
                resolved_output_dir = Path(output_dir).resolve()
                if resolved_output_dir == resolved_model_path or resolved_output_dir in resolved_model_path.parents:
                    return run
            except Exception:
                continue

        try:
            model_parts = {str(part) for part in resolved_model_path.parts}
        except Exception:
            model_parts = set()

        for run in runs:
            run_id = str(getattr(run, "id", "") or "").strip()
            if run_id and run_id in model_parts:
                return run

        return None

    def _format_training_model_reference(self, model_value) -> str:
        text = str(model_value or "").strip()
        if not text:
            return "-"

        try:
            model_path = Path(text)
        except Exception:
            return text

        display = str(model_path.name or text).strip() or text
        if model_path.name.lower() != "best.pt":
            return display

        source_run = self._resolve_training_run_from_model_path(model_path)
        if source_run is None:
            return display

        run_name = str(getattr(source_run, "name", "") or "").strip()
        run_id = str(getattr(source_run, "id", "") or "").strip()
        if run_name and run_id and run_name != run_id:
            return f"{display} ({run_name})"
        if run_name:
            return f"{display} ({run_name})"
        if run_id:
            return f"{display} ({run_id})"
        return display

    def _build_selected_training_base_model_origin_rows(self, base_model_path: Path | None) -> list[tuple[str, str]]:
        if base_model_path is None or base_model_path.name.lower() != "best.pt":
            return []

        source_run = self._resolve_training_run_from_model_path(base_model_path)
        if source_run is None:
            return []

        run_label = self._format_training_model_run_label(source_run)
        return [("Pochodzenie modelu", f"Model z wcześniejszego treningu: {run_label}")]

    @staticmethod
    def _format_training_file_created_at(path: Path | None) -> str:
        if path is None:
            return "-"
        try:
            return datetime.datetime.fromtimestamp(path.stat().st_ctime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "-"

    def _append_training_execution_summary_row_widget(self, row_index: int) -> None:
        summary_grid = getattr(self, "train_run_summary_grid", None)
        if summary_grid is None:
            return

        palette = getattr(self.app, "palette", {}) or {}
        key_label = tk.Label(
            summary_grid,
            text="",
            font=("Segoe UI", 8, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=3,
            bg=palette.get("panel", "#252526"),
            fg=palette.get("fg", "#f3f3f3"),
        )
        key_label.grid(row=row_index + 1, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
        value_label = tk.Label(
            summary_grid,
            text="",
            font=("Segoe UI", 8),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=3,
            wraplength=250,
            bg=palette.get("panel_alt", palette.get("panel", "#252526")),
            fg=palette.get("muted", "#c7c7c7"),
        )
        value_label.grid(row=row_index + 1, column=1, sticky="nsew", padx=(0, 1), pady=(0, 1))
        self._register_train_left_wrap_target(value_label, container=self.train_run_summary_shell, padding=140, min_wrap=180)
        self._train_run_summary_row_widgets.append({"key": key_label, "value": value_label, "row_index": row_index})

    def _ensure_training_execution_summary_row_capacity(self, required_rows: int) -> None:
        summary_grid = getattr(self, "train_run_summary_grid", None)
        if summary_grid is None:
            return
        row_widgets = getattr(self, "_train_run_summary_row_widgets", None)
        if not isinstance(row_widgets, list):
            self._train_run_summary_row_widgets = []
            row_widgets = self._train_run_summary_row_widgets
        while len(row_widgets) < max(0, int(required_rows)):
            self._append_training_execution_summary_row_widget(len(row_widgets))

    def _build_training_execution_summary_rows(self) -> list[tuple[str, str]]:
        target = self._get_selected_training_target()
        target_label = self._format_training_target_label(target)
        base_model_display = self._resolve_selected_training_base_model_display()
        base_model_inspection_path, base_model_info = self._resolve_selected_training_base_model_info()
        dataset_yaml = self._resolve_training_dataset_yaml_path()
        epochs_value = self._safe_training_int_value("epochs_var", default=100, minimum=1)

        rows = [
            ("Tor", target_label),
            ("Model YOLO", self._build_training_model_summary_value(base_model_display, base_model_info)),
        ]
        model_version = self._resolve_training_model_version_from_info(base_model_info)
        if model_version:
            rows.append(("Wersja modelu", model_version))
        model_size = self._resolve_training_model_size_from_info(base_model_info)
        if model_size:
            rows.append(("Rozmiar modelu", model_size))
        if base_model_inspection_path is not None:
            rows.append(("Plik .pt", str(base_model_inspection_path.name or "-")))
            try:
                file_size_mb = float(base_model_info.get("file_size_mb", 0.0) or 0.0)
            except Exception:
                file_size_mb = 0.0
            if file_size_mb > 0.0:
                rows.append(("Wielkość pliku", f"{file_size_mb:.1f} MB"))
            rows.extend(self._build_selected_training_base_model_origin_rows(base_model_inspection_path))

        if dataset_yaml is None:
            rows.extend(
                [
                    ("Dataset", "Nie wskazano jeszcze poprawnego folderu z plikiem data.yaml."),
                    ("Statystyki zestawu", "Brak danych do odczytu."),
                    ("Split treningu", "Po wskazaniu datasetu YOLO trening ruszy na `train`, a metryki po epokach będą liczone na `val`."),
                    ("Plan runu", f"{epochs_value} epok."),
                ]
            )
            return rows

        dataset_root = dataset_yaml.parent
        dataset_rel = self._format_workspace_relative_path(dataset_root)
        counts = self._get_dataset_split_image_counts(dataset_root)
        total_images = int(counts.get("total", 0) or 0)
        train_images = int(counts.get("train", 0) or 0)
        val_images = int(counts.get("val", 0) or 0)
        test_images = int(counts.get("test", 0) or 0)

        try:
            cfg = safe_load_yaml(dataset_yaml) or {}
        except Exception:
            cfg = {}

        class_names = self._extract_dataset_class_names(cfg)
        class_count = len(class_names)
        if class_count <= 0:
            try:
                class_count = max(0, int(cfg.get("nc", 0) or 0))
            except Exception:
                class_count = 0
        dataset_task = "YOLO Pose" if bool(cfg.get("kpt_shape")) else "YOLO Detect"

        def _pct(value: int) -> str:
            if total_images <= 0:
                return "0.0%"
            return f"{(float(value) / float(total_images)) * 100.0:.1f}%"

        split_usage = (
            f"train={train_images} ({_pct(train_images)}), "
            f"val={val_images} ({_pct(val_images)}), "
            f"test={test_images} ({_pct(test_images)})"
        )

        rows.extend(
            [
                ("Dataset", dataset_rel),
                ("Typ datasetu", dataset_task + (f" | klasy: {class_count}" if class_count > 0 else "")),
                ("Statystyki zestawu", f"razem={total_images}, train={train_images}, val={val_images}, test={test_images}"),
                ("Split treningu", f"Uczenie na `train`, pomiar po każdej epoce na `val`, rezerwa w `test` | {split_usage}"),
                ("Plan runu", f"{epochs_value} epok."),
            ]
        )
        return rows

    def _refresh_training_execution_summary(self):
        rows = self._build_training_execution_summary_rows()
        self._ensure_training_execution_summary_row_capacity(len(rows))
        row_widgets = list(getattr(self, "_train_run_summary_row_widgets", []) or [])
        if not row_widgets:
            return
        for row_index, widgets in enumerate(row_widgets):
            key_label = widgets.get("key")
            value_label = widgets.get("value")
            row_visible = row_index < len(rows)
            if row_visible:
                key_text, value_text = rows[row_index]
            else:
                key_text, value_text = "", ""
            try:
                if key_label is not None:
                    if row_visible:
                        key_label.grid()
                    else:
                        key_label.grid_remove()
                    key_label.configure(text=str(key_text or ""))
            except Exception:
                pass
            try:
                if value_label is not None:
                    if row_visible:
                        value_label.grid()
                    else:
                        value_label.grid_remove()
                    value_label.configure(text=str(value_text or ""))
            except Exception:
                pass

    @staticmethod
    def _terminal_metric_tag(band: str) -> str:
        normalized = str(band or "").strip().lower()
        if normalized in {"bardzo dobry", "dobry"}:
            return "terminal_success"
        if normalized in {"używalny", "monitoruj"}:
            return "terminal_warning"
        if normalized == "slaby":
            return "terminal_error"
        return "terminal_default"

    @staticmethod
    def _format_terminal_table_line(values: list[str], widths: list[int], alignments: list[str]) -> str:
        cells = []
        for value, width, alignment in zip(values, widths, alignments):
            text = str(value or "")
            if alignment == "center":
                cells.append(text.center(width))
            elif alignment == "right":
                cells.append(text.rjust(width))
            else:
                cells.append(text.ljust(width))
        return "| " + " | ".join(cells) + " |"

    def _build_training_metric_terminal_entries(self, epoch: int, total_epochs: int, metrics: dict | None) -> list[tuple[str, str]]:
        rows = self._build_training_metric_rows(metrics)
        if not rows:
            return []

        headers = ["Metryka", "Wynik", "Ocena", "Zakres"]
        alignments = ["left", "center", "center", "center"]
        widths = []
        for idx, header in enumerate(headers):
            max_width = len(header)
            for row in rows:
                max_width = max(max_width, len(str(row[idx] if idx < len(row) else "")))
            widths.append(max_width)

        separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
        header_row = self._format_terminal_table_line(headers, widths, alignments)
        entries: list[tuple[str, str]] = []

        target_label = "tablice" if self.get_campaign_training_target() == "plate" else "znaki"
        entries.append((f"[Z4] BIEZACE WYNIKI | epoka {int(epoch)}/{int(total_epochs)} | tor: {target_label}", "terminal_info"))
        entries.append((separator, "terminal_border"))
        entries.append((header_row, "terminal_header"))
        entries.append((separator, "terminal_border"))

        for row in rows:
            band = str(row[2] or "")
            entries.append(
                (
                    self._format_terminal_table_line([str(cell) for cell in row], widths, alignments),
                    self._terminal_metric_tag(band),
                )
            )

        entries.append((separator, "terminal_border"))
        return entries

    def _append_training_metric_table_to_global(self, epoch: int, total_epochs: int, metrics: dict | None):
        try:
            entries = self._build_training_metric_terminal_entries(epoch, total_epochs, metrics)
            if not entries:
                return
            if hasattr(self.app, "append_global_terminal_entries"):
                self.app.append_global_terminal_entries(entries + [("", "terminal_default")])
        except Exception:
            pass

    def _set_history_run_tables(self, run):
        if run is None:
            self._set_metric_table_rows(getattr(self, "hist_detail_tree", None), [])
            self._set_metric_table_rows(getattr(self, "hist_metrics_tree", None), [])
            return

        self._set_metric_table_rows(
            getattr(self, "hist_detail_tree", None),
            self._build_training_run_detail_rows(run),
        )
        self._set_metric_table_rows(
            getattr(self, "hist_metrics_tree", None),
            self._build_training_run_metric_rows(run),
        )

    def _get_datasets_base_dir(self) -> Path:
        """Zwraca bazowy katalog datasetów dla aktywnego projektu albo globalny fallback."""
        if self._campaign_datasets_dir:
            return Path(self._campaign_datasets_dir)
        target = getattr(self, "_step4_dataset_mode", getattr(self, "_campaign_training_target", "char"))
        return Path(CONFIG.get_datasets_dir(target))

    def _get_manual_plate_stage_dir(self) -> Path:
        if CAMPAIGN.get_active_project_name():
            base_dir = CAMPAIGN.get_staging_dir("plate_stage")
            if base_dir is not None:
                iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
                return Path(base_dir) / f"Iteracja_{iter_num:03d}"
        return Path(CONFIG.get_auto_annotations_dir("plate")) / "_manual_stage"

    def _iter_dataset_search_roots(self, base_dir: Path | None = None) -> list[Path]:
        root = Path(base_dir or self._get_datasets_base_dir())
        candidates = [root, root / "plates", root / "chars", root / "vehicles"]
        unique: list[Path] = []
        seen: set[str] = set()

        for candidate in candidates:
            try:
                resolved = str(candidate.resolve())
            except Exception:
                resolved = str(candidate)
            if resolved in seen or not candidate.exists() or not candidate.is_dir():
                continue
            seen.add(resolved)
            unique.append(candidate)

        return unique

    def _find_dataset_source_candidates(self, base_dir: Path | None = None) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        for search_root in self._iter_dataset_search_roots(base_dir):
            try:
                for path in search_root.iterdir():
                    if not path.is_dir() or "_Split_" in path.name or not (path / "images").exists():
                        continue
                    key = str(path.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(path)
            except Exception:
                continue

        return candidates

    def _find_ready_dataset_candidates(self, base_dir: Path | None = None) -> list[tuple[Path, str, float]]:
        candidates: list[tuple[Path, str, float]] = []
        seen: set[str] = set()

        for search_root in self._iter_dataset_search_roots(base_dir):
            try:
                for path in search_root.iterdir():
                    if not path.is_dir():
                        continue

                    yaml_path = path / "data.yaml"
                    if not yaml_path.exists():
                        continue

                    key = str(path.resolve())
                    if key in seen:
                        continue
                    seen.add(key)

                    target = self._infer_dataset_target(str(path)) or "char"
                    candidates.append((path, target, path.stat().st_mtime))
            except Exception:
                continue

        return candidates

    def _get_free_dataset_variant_choices(self) -> list[dict]:
        selected_target = self._get_selected_training_target()
        candidates = self._find_ready_dataset_candidates(self._get_datasets_base_dir())
        variants: list[dict] = []
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        approved_plate_images = 0
        if campaign_active and selected_target == "plate":
            try:
                approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
                approved_plate_images = int(approved_stats.get("images", 0) or 0)
            except Exception:
                approved_plate_images = 0

        for path, target, stamp in candidates:
            if target != selected_target:
                continue
            counts = self._get_dataset_split_image_counts(path)
            total = int(counts.get("total", 0) or 0)
            if campaign_active and selected_target == "plate" and approved_plate_images > 0 and total != approved_plate_images:
                continue
            try:
                label_path = self._format_workspace_relative_path(path)
            except Exception:
                label_path = str(path)
            label = (
                f"{path.name} | train={int(counts.get('train', 0) or 0)}, "
                f"val={int(counts.get('val', 0) or 0)}, "
                f"test={int(counts.get('test', 0) or 0)}"
            )
            if total <= 0:
                label = f"{path.name} | data.yaml"
            variants.append(
                {
                    "label": label,
                    "path": str(path),
                    "display_path": label_path,
                    "stamp": float(stamp or 0),
                }
            )

        variants.sort(key=lambda item: float(item.get("stamp", 0) or 0), reverse=True)
        return variants

    def _refresh_dataset_variant_choices(self):
        combo = getattr(self, "dataset_variant_combo", None)
        if combo is None:
            return

        variants = self._get_free_dataset_variant_choices()
        self._dataset_variant_choices = variants
        labels = [str(item.get("label") or "") for item in variants]

        try:
            combo.configure(values=labels)
        except Exception:
            pass

        try:
            combo.configure(state=("readonly" if labels else tk.DISABLED))
        except Exception:
            pass

        self._sync_dataset_variant_selection()

    def _normalize_dataset_variant_root(self, value: str | Path | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            path = Path(raw)
            if path.is_file() and path.name.lower() == "data.yaml":
                path = path.parent
            return str(path.resolve())
        except Exception:
            return raw

    def _is_free_training_dataset_variant_selected(self, dataset_value: str | Path | None = None) -> bool:
        if CAMPAIGN.get_active_project_name():
            return True

        current_root = self._normalize_dataset_variant_root(
            dataset_value if dataset_value is not None else getattr(self, "dataset_var", tk.StringVar()).get()
        )
        if not current_root:
            return False

        for item in list(self._get_free_dataset_variant_choices() or []):
            item_root = self._normalize_dataset_variant_root(item.get("path"))
            if item_root and item_root == current_root:
                return True
        return False

    def _sync_dataset_variant_selection(self):
        var = getattr(self, "dataset_variant_var", None)
        if var is None:
            return

        current = str(getattr(self, "dataset_var", tk.StringVar()).get() or "").strip()
        current_resolved = self._normalize_dataset_variant_root(current)

        selected_label = ""
        for item in list(getattr(self, "_dataset_variant_choices", []) or []):
            item_path = str(item.get("path") or "")
            item_resolved = self._normalize_dataset_variant_root(item_path)
            if current_resolved and item_resolved == current_resolved:
                selected_label = str(item.get("label") or "")
                break

        try:
            var.set(selected_label)
        except Exception:
            pass

    def _on_dataset_variant_selected(self, event=None):
        selected = str(getattr(self, "dataset_variant_var", tk.StringVar()).get() or "").strip()
        if not selected:
            return

        for item in list(getattr(self, "_dataset_variant_choices", []) or []):
            if str(item.get("label") or "") != selected:
                continue
            path = str(item.get("path") or "").strip()
            if path:
                try:
                    accepted = self._accept_training_input_context(
                        source="pz2_variant",
                        target=self._get_selected_training_target(),
                        dataset_path=path,
                        select_training=False,
                    )
                except Exception:
                    accepted = False
                if not accepted:
                    try:
                        self.dataset_var.set(path)
                    except Exception:
                        pass
                    try:
                        self._last_training_input_context = TrainingInputContext(
                            source="pz2_variant",
                            target=self._get_selected_training_target(),
                            dataset_path=path,
                            ready=True,
                        )
                    except Exception:
                        pass
            return

    def _get_dataset_split_image_counts(self, dataset_path: Path | str | None) -> dict[str, int]:
        counts = {"train": 0, "val": 0, "test": 0, "total": 0}
        if dataset_path is None:
            return counts

        try:
            root = Path(dataset_path)
        except Exception:
            return counts

        if root.is_file():
            root = root.parent

        images_root = root / "images"
        if not images_root.exists() or not images_root.is_dir():
            return counts

        total = 0
        for split_name in ("train", "val", "test"):
            split_dir = images_root / split_name
            if not split_dir.exists() or not split_dir.is_dir():
                continue
            try:
                split_count = len(get_image_files(split_dir))
            except Exception:
                split_count = 0
            counts[split_name] = int(split_count)
            total += int(split_count)

        counts["total"] = int(total)
        return counts

    def _resolve_step4_dataset_summary_source(self) -> tuple[str, str, str]:
        dataset_path = ""
        source_label = "Aktywny split"
        target = str(getattr(self, "_step4_dataset_mode", "char") or "char").strip().lower()

        try:
            dataset_path = str(getattr(self, "dataset_var", tk.StringVar()).get() or "").strip()
        except Exception:
            dataset_path = ""

        context = getattr(self, "_last_training_input_context", None)
        if not dataset_path and context is not None:
            dataset_path = str(getattr(context, "dataset_path", "") or "").strip()
            context_target = str(getattr(context, "target", "") or "").strip().lower()
            if context_target in {"plate", "char"}:
                target = context_target
            if dataset_path:
                source_label = "Ostatnio przygotowany"

        return dataset_path, target, source_label

    def _refresh_step4_dataset_summary_table(self):
        frame = getattr(self, "step4_dataset_summary_frame", None)
        rows = getattr(self, "_step4_dataset_summary_rows", None)
        if frame is None or not rows:
            return

        if CAMPAIGN.get_active_project_name():
            try:
                frame.pack_forget()
            except Exception:
                pass
            return

        try:
            if str(frame.winfo_manager()) != "pack":
                before_widget = getattr(self, "ds_mode_scroll_host", None)
                if before_widget is not None:
                    frame.pack(fill=tk.X, pady=(8, 0), before=before_widget)
                else:
                    frame.pack(fill=tk.X, pady=(8, 0))
        except Exception:
            pass

        palette = getattr(self.app, "palette", {})
        panel = palette.get("panel", "#252526")
        panel_alt = palette.get("panel_alt", "#2d2d30")
        field = palette.get("field", panel_alt)
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        success = palette.get("success", "#4ec9b0")
        warning = palette.get("warning", "#d7ba7d")
        danger = palette.get("danger", "#f48771")
        accent = palette.get("accent", success)
        accent_text = palette.get("accent_text", "#ffffff")

        dataset_path, target, source_label = self._resolve_step4_dataset_summary_source()
        target = CONFIG.normalize_task_target(target)
        target_label = self._format_training_target_label(target)
        display_path = "Brak wybranego datasetu"
        data_yaml_text = "-"
        counts = {"train": 0, "val": 0, "test": 0, "total": 0}
        ready = False

        if dataset_path:
            try:
                root = Path(dataset_path)
                if root.is_file() and root.name.lower() == "data.yaml":
                    root = root.parent
                data_yaml = root / "data.yaml"
                ready = bool(data_yaml.exists())
                data_yaml_text = "jest" if ready else "brak"
                display_path = self._format_workspace_relative_path(root)
                counts = self._get_dataset_split_image_counts(root)
            except Exception:
                display_path = str(dataset_path)
                data_yaml_text = "brak"

        status_text = "Split gotowy" if ready else "Brak wybranego datasetu"
        status_fg = success if ready else warning
        if dataset_path and not ready:
            status_text = "Wymaga data.yaml"
            status_fg = danger

        values = {
            "status": status_text,
            "target": target_label,
            "source": source_label if dataset_path else "-",
            "path": display_path,
            "yaml": data_yaml_text,
            "total": str(int(counts.get("total", 0) or 0)),
        }
        self._step4_dataset_summary_split_counts = dict(counts)

        try:
            frame.configure(bg=panel, highlightbackground=border, highlightcolor=border)
            self.step4_dataset_summary_title_lbl.configure(bg=panel, fg=fg)
            self.step4_dataset_summary_grid.configure(bg=panel)
        except Exception:
            pass

        for index, (key, widgets) in enumerate(rows.items()):
            label_widget, value_widget = widgets
            bg = field if index % 2 == 0 else panel_alt
            value_fg = status_fg if key == "status" else fg
            if key in {"source", "path"} and not dataset_path:
                value_fg = muted
            try:
                label_widget.configure(bg=bg, fg=muted, highlightbackground=border, highlightcolor=border)
                if key == "split":
                    value_widget.configure(bg=bg, highlightbackground=border, highlightcolor=border)
                    self._draw_step4_dataset_split_bar(value_widget)
                    continue
                value_widget.configure(
                    bg=bg,
                    fg=value_fg,
                    highlightbackground=border,
                    highlightcolor=border,
                    wraplength=620 if key == "path" else 260,
                )
            except Exception:
                pass

        header_widgets = getattr(self, "_step4_dataset_summary_header_widgets", ())
        for widget in header_widgets:
            try:
                widget.configure(bg=accent, fg=accent_text, highlightbackground=border, highlightcolor=border)
            except Exception:
                pass

        for key, value in values.items():
            if key in rows:
                try:
                    rows[key][1].configure(text=value)
                except Exception:
                    pass

    def _draw_step4_dataset_split_bar(self, canvas=None):
        if canvas is None:
            try:
                canvas = self._step4_dataset_summary_rows["split"][1]
            except Exception:
                return

        try:
            counts = dict(getattr(self, "_step4_dataset_summary_split_counts", {}) or {})
        except Exception:
            counts = {}

        palette = getattr(self.app, "palette", {})
        panel_alt = palette.get("panel_alt", "#2d2d30")
        field = palette.get("field", panel_alt)
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        success = palette.get("success", "#4ec9b0")
        warning = palette.get("warning", "#d7ba7d")
        accent = palette.get("accent", "#569cd6")

        try:
            width = max(180, int(canvas.winfo_width() or 0))
            height = max(26, int(canvas.winfo_height() or 0))
        except Exception:
            width, height = 360, 28

        try:
            canvas.delete("all")
            canvas.configure(bg=field, highlightbackground=border, highlightcolor=border)
        except Exception:
            return

        train = int(counts.get("train", 0) or 0)
        val = int(counts.get("val", 0) or 0)
        test = int(counts.get("test", 0) or 0)
        total = int(counts.get("total", 0) or (train + val + test))

        if total <= 0:
            canvas.create_text(
                10,
                height // 2,
                text="brak danych splitu",
                fill=muted,
                anchor="w",
                font=("Segoe UI", 8),
            )
            return

        usable = max(1, width - 2)
        min_segment = max(18, min(46, usable // 10))
        segments = [
            ("train", train, success),
            ("val", val, warning),
            ("test", test, accent),
        ]
        widths = {
            name: (float(count) / float(total)) * usable if count > 0 else 0.0
            for name, count, _color in segments
        }

        for name, count, _color in segments:
            if count > 0 and widths[name] < min_segment:
                widths[name] = float(min_segment)

        overflow = sum(widths.values()) - usable
        while overflow > 0.5:
            adjustable = [
                name
                for name, count, _color in segments
                if count > 0 and widths.get(name, 0.0) > min_segment
            ]
            if not adjustable:
                scale = usable / max(1.0, sum(widths.values()))
                for name in widths:
                    widths[name] *= scale
                break
            largest = max(adjustable, key=lambda item: widths.get(item, 0.0))
            cut = min(overflow, widths[largest] - min_segment)
            widths[largest] -= cut
            overflow -= cut

        x = 1.0
        bar_top = 4
        bar_bottom = max(bar_top + 16, height - 4)
        for name, count, color in segments:
            segment_width = widths.get(name, 0.0)
            if count <= 0 or segment_width <= 0:
                continue
            x2 = min(float(width - 1), x + segment_width)
            canvas.create_rectangle(x, bar_top, x2, bar_bottom, fill=color, outline=field)
            text = f"{name} {count}"
            text_fill = "#111111" if name in {"train", "val"} else fg
            if x2 - x >= 58:
                canvas.create_text(
                    (x + x2) / 2,
                    (bar_top + bar_bottom) / 2,
                    text=text,
                    fill=text_fill,
                    anchor="center",
                    font=("Segoe UI", 8),
                )
            else:
                canvas.create_text(
                    x + 3,
                    (bar_top + bar_bottom) / 2,
                    text=str(count),
                    fill=text_fill,
                    anchor="w",
                    font=("Segoe UI", 7),
                )
            x = x2

    @staticmethod
    def _median_int(values: list[int]) -> int:
        cleaned = sorted(int(value) for value in (values or []) if int(value) > 0)
        if not cleaned:
            return 0
        middle = len(cleaned) // 2
        if len(cleaned) % 2 == 1:
            return int(cleaned[middle])
        return int(round((cleaned[middle - 1] + cleaned[middle]) / 2.0))

    @staticmethod
    def _nearest_training_imgsz(value: int, *, minimum: int = 384, maximum: int = 1280) -> int:
        allowed = [256, 320, 384, 416, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024, 1280]
        minimum = max(32, int(minimum or 32))
        maximum = max(minimum, int(maximum or minimum))
        target = max(minimum, min(maximum, int(value or minimum)))
        candidates = [candidate for candidate in allowed if minimum <= candidate <= maximum]
        if not candidates:
            snapped = int(round(target / 32.0) * 32)
            return max(minimum, min(maximum, max(32, snapped)))
        return min(candidates, key=lambda candidate: (abs(candidate - target), candidate))

    @staticmethod
    def _parse_training_model_params_millions(raw_value) -> float:
        text = str(raw_value or "").strip().lower().replace(",", ".")
        if not text:
            return 0.0
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except Exception:
            return 0.0

    def _normalize_training_model_catalog_key(self, model_value, catalog: dict[str, dict] | None = None) -> str:
        catalog = dict(catalog or {})
        if not catalog:
            return ""

        raw_text = str(model_value or "").strip()
        if not raw_text:
            return ""

        lowered = raw_text.lower()
        try:
            stem = Path(raw_text).stem.lower()
        except Exception:
            stem = lowered

        for key, meta in catalog.items():
            key_text = str(key or "").strip().lower()
            file_text = str((meta or {}).get("file", "") or "").strip().lower()
            try:
                file_stem = Path(file_text).stem.lower()
            except Exception:
                file_stem = file_text

            if lowered in {key_text, file_text}:
                return str(key)
            if stem in {key_text, file_stem}:
                return str(key)

        return ""

    @staticmethod
    def _infer_training_model_bucket(
        model_label: str = "",
        *,
        params_m: float = 0.0,
        file_size_mb: float = 0.0,
    ) -> str:
        label = str(model_label or "").strip().lower()
        try:
            stem = Path(label).stem.lower()
        except Exception:
            stem = label

        match = re.search(r"([nsmxl])(?:-pose)?$", stem)
        if match:
            return str(match.group(1))

        if params_m > 0:
            if params_m <= 4.5:
                return "n"
            if params_m <= 12.0:
                return "s"
            if params_m <= 24.0:
                return "m"
            if params_m <= 40.0:
                return "l"
            return "x"

        if file_size_mb > 0:
            if file_size_mb <= 8.0:
                return "n"
            if file_size_mb <= 20.0:
                return "s"
            if file_size_mb <= 40.0:
                return "m"
            if file_size_mb <= 80.0:
                return "l"
            return "x"

        return "s"

    @staticmethod
    def _infer_training_model_version_size_from_text(raw_text: str | Path | None) -> tuple[str, str]:
        text = str(raw_text or "").strip().lower()
        if not text:
            return "", ""
        try:
            text = f"{text} {Path(text).stem.lower()}"
        except Exception:
            pass

        match = re.search(r"yolo(?:v)?(8|11|26)([nsmxl])", text)
        if not match:
            return "", ""
        return str(match.group(1) or "").strip(), str(match.group(2) or "").strip().lower()

    @staticmethod
    def _format_training_model_version_label(raw_version: str | None) -> str:
        version = str(raw_version or "").strip().lower()
        if version.startswith("v"):
            version = version[1:]
        if not version:
            return ""
        if version == "8":
            return "YOLOv8"
        return f"YOLO{version}"

    def _resolve_selected_training_base_model_profile(self) -> dict:
        target = self._get_selected_training_target()
        catalog = AVAILABLE_POSE_MODELS if target == "plate" else AVAILABLE_DETECT_MODELS
        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        custom_model_path = self._resolve_selected_training_base_model_path()
        inspection_path, inspection_info = self._resolve_selected_training_base_model_info()

        resolved_key = ""
        params_m = 0.0
        file_size_mb = 0.0
        source_label = base_key

        if base_key != "Custom":
            resolved_key = self._normalize_training_model_catalog_key(base_key, catalog)
            source_label = resolved_key or base_key
        else:
            source_run = self._resolve_training_run_from_model_path(custom_model_path)
            source_base_model = str(getattr(source_run, "base_model", "") or "").strip() if source_run is not None else ""
            if source_base_model:
                resolved_key = self._normalize_training_model_catalog_key(source_base_model, catalog)
                source_label = resolved_key or source_base_model
            elif custom_model_path is not None:
                resolved_key = self._normalize_training_model_catalog_key(custom_model_path.name, catalog)
                source_label = resolved_key or custom_model_path.name

            if custom_model_path is not None:
                try:
                    file_size_mb = round(float(custom_model_path.stat().st_size) / (1024.0 ** 2), 2)
                except Exception:
                    file_size_mb = 0.0

        catalog_meta = catalog.get(resolved_key, {}) if resolved_key in catalog else {}
        catalog_params_text = str((catalog_meta or {}).get("params") or "").strip()
        catalog_version = str((catalog_meta or {}).get("version") or "").strip()
        detected_label = format_yolo_model_identity(inspection_info)
        detected_source_label = str(inspection_info.get("source_architecture_label") or "").strip()
        detected_scale = str(inspection_info.get("model_scale") or inspection_info.get("yolo_size") or "").strip().lower()
        if base_key == "Custom":
            if detected_source_label:
                source_label = detected_source_label
            elif detected_label:
                source_label = detected_label

        if resolved_key in catalog:
            params_m = self._parse_training_model_params_millions(catalog_params_text)

        model_version = str(inspection_info.get("yolo_version") or "").strip()
        model_size = detected_scale if detected_scale in {"n", "s", "m", "l", "x"} else ""
        identity_candidates = [
            detected_label,
            detected_source_label,
            source_label,
            resolved_key,
            base_key,
            custom_model_path.name if custom_model_path is not None else "",
            str(inspection_path.name if inspection_path is not None else ""),
        ]
        if not model_version and catalog_version:
            model_version = catalog_version
        for candidate in identity_candidates:
            inferred_version, inferred_size = self._infer_training_model_version_size_from_text(candidate)
            if not model_version and inferred_version:
                model_version = inferred_version
            if not model_size and inferred_size:
                model_size = inferred_size
            if model_version and model_size:
                break

        if model_size in {"n", "s", "m", "l", "x"}:
            bucket = model_size
        else:
            bucket = self._infer_training_model_bucket(
                source_label,
                params_m=params_m,
                file_size_mb=file_size_mb,
            )
            model_size = bucket

        return {
            "target": target,
            "base_key": base_key,
            "catalog_key": resolved_key,
            "label": source_label,
            "bucket": bucket,
            "params_m": params_m,
            "file_size_mb": file_size_mb,
            "custom": bool(base_key == "Custom"),
            "detected_label": detected_label,
            "detected_source_label": detected_source_label,
            "detected_scale": detected_scale,
            "model_version": model_version,
            "model_version_label": self._format_training_model_version_label(model_version),
            "model_size": model_size,
            "model_size_label": self._format_training_model_size_label(model_size),
            "params_text": catalog_params_text,
            "inspection_path": str(inspection_path) if inspection_path is not None else "",
        }

    def _get_training_dataset_profile(self, dataset_yaml_path: Path | None = None) -> dict:
        result = {
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "total_images": 0,
            "train_label_files": 0,
            "val_label_files": 0,
            "test_label_files": 0,
            "total_label_files": 0,
            "train_objects": 0,
            "val_objects": 0,
            "test_objects": 0,
            "total_objects": 0,
            "sampled_images": 0,
            "median_width": 0,
            "median_height": 0,
            "median_long_edge": 0,
            "max_long_edge": 0,
        }

        yaml_path = dataset_yaml_path or self._resolve_training_dataset_yaml_path()
        if yaml_path is None or not yaml_path.exists():
            return result

        dataset_root = yaml_path.parent
        train_dir = dataset_root / "images" / "train"
        val_dir = dataset_root / "images" / "val"
        test_dir = dataset_root / "images" / "test"
        train_labels_dir = dataset_root / "labels" / "train"
        val_labels_dir = dataset_root / "labels" / "val"
        test_labels_dir = dataset_root / "labels" / "test"

        try:
            cache_root = str(dataset_root.resolve())
        except Exception:
            cache_root = str(dataset_root)

        try:
            yaml_mtime = int(yaml_path.stat().st_mtime)
        except Exception:
            yaml_mtime = 0
        try:
            train_mtime = int(train_dir.stat().st_mtime) if train_dir.exists() else 0
        except Exception:
            train_mtime = 0
        try:
            val_mtime = int(val_dir.stat().st_mtime) if val_dir.exists() else 0
        except Exception:
            val_mtime = 0
        try:
            test_mtime = int(test_dir.stat().st_mtime) if test_dir.exists() else 0
        except Exception:
            test_mtime = 0
        label_mtimes = []
        for label_dir in (train_labels_dir, val_labels_dir, test_labels_dir):
            try:
                label_mtimes.append(int(label_dir.stat().st_mtime) if label_dir.exists() else 0)
            except Exception:
                label_mtimes.append(0)

        cache_key = (
            f"{cache_root}|{yaml_mtime}|{train_mtime}|{val_mtime}|{test_mtime}|"
            + "|".join(str(value) for value in label_mtimes)
        )
        cached_key = str(getattr(self, "_training_dataset_profile_cache_key", "") or "")
        cached_profile = getattr(self, "_training_dataset_profile_cache", None)
        if cache_key == cached_key and isinstance(cached_profile, dict):
            return dict(cached_profile)

        counts = self._get_dataset_split_image_counts(dataset_root)
        result["train_images"] = int(counts.get("train", 0) or 0)
        result["val_images"] = int(counts.get("val", 0) or 0)
        result["test_images"] = int(counts.get("test", 0) or 0)
        result["total_images"] = int(counts.get("total", 0) or 0)

        for split_name, label_dir in (
            ("train", train_labels_dir),
            ("val", val_labels_dir),
            ("test", test_labels_dir),
        ):
            label_files = 0
            object_count = 0
            if label_dir.exists() and label_dir.is_dir():
                try:
                    paths = [path for path in label_dir.iterdir() if path.is_file() and path.suffix.lower() == ".txt"]
                except Exception:
                    paths = []
                label_files = len(paths)
                for label_path in paths:
                    try:
                        with open(label_path, "r", encoding="utf-8", errors="ignore") as handle:
                            object_count += sum(1 for line in handle if str(line or "").strip())
                    except Exception:
                        continue
            result[f"{split_name}_label_files"] = int(label_files)
            result[f"{split_name}_objects"] = int(object_count)
            result["total_label_files"] += int(label_files)
            result["total_objects"] += int(object_count)

        sample_paths: list[Path] = []
        for split_dir in (train_dir, val_dir, test_dir):
            if len(sample_paths) >= 24:
                break
            if not split_dir.exists() or not split_dir.is_dir():
                continue
            try:
                sample_paths.extend(list(get_image_files(split_dir))[: max(0, 24 - len(sample_paths))])
            except Exception:
                continue

        widths: list[int] = []
        heights: list[int] = []
        long_edges: list[int] = []
        if PIL_AVAILABLE:
            for image_path in sample_paths[:24]:
                try:
                    with Image.open(image_path) as image_obj:
                        width, height = image_obj.size
                except Exception:
                    continue
                width = int(width or 0)
                height = int(height or 0)
                if width <= 0 or height <= 0:
                    continue
                widths.append(width)
                heights.append(height)
                long_edges.append(max(width, height))

        result["sampled_images"] = len(long_edges)
        result["median_width"] = self._median_int(widths)
        result["median_height"] = self._median_int(heights)
        result["median_long_edge"] = self._median_int(long_edges)
        result["max_long_edge"] = max(long_edges) if long_edges else 0

        self._training_dataset_profile_cache_key = cache_key
        self._training_dataset_profile_cache = dict(result)
        return dict(result)

    def _get_campaign_plate_builder_source(self) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}
        if str(self.get_campaign_training_target() or "").strip().lower() != "plate":
            return {}

        try:
            annotation_tab = self.app.tabs.get("annotation")
        except Exception:
            annotation_tab = None

        if annotation_tab is None or not hasattr(annotation_tab, "_build_campaign_plate_approved_export_source"):
            return {}

        try:
            source = annotation_tab._build_campaign_plate_approved_export_source()
        except Exception:
            source = {}

        return dict(source or {}) if isinstance(source, dict) else {}

    def _load_step4_training_ui_state(self) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}
        try:
            entry = dict(CAMPAIGN.get_iteration_state() or {})
        except Exception:
            return {}
        payload = entry.get("step4_ui_state", {})
        return payload if isinstance(payload, dict) else {}

    def _save_step4_training_ui_state(self, payload: dict) -> None:
        if not CAMPAIGN.get_active_project_name():
            return
        try:
            CAMPAIGN.upsert_iteration_state(
                iteration_num=CAMPAIGN.get_current_iteration_num(),
                updates={"step4_ui_state": dict(payload or {})},
            )
        except Exception as e:
            logger.debug(f"Nie udało się zapisać stanu UI treningu Z4 do rejestru iteracji: {e}")

    def _get_preferred_plate_pose_base_model(self) -> str:
        for preferred in ("yolo26s-pose", "yolo11s-pose", "yolov8s-pose"):
            if preferred in self._get_base_model_choices_for_mode("plate"):
                return preferred
        return self._get_default_base_model_for_mode("plate")

    def _resolve_saved_step4_training_model_selection(self, target: str | None = None) -> dict:
        normalized_target = str(target or self.get_campaign_training_target() or "").strip().lower()
        if normalized_target not in ("char", "plate"):
            return {}
        payload = self._load_step4_training_ui_state()
        models = payload.get("models", {}) if isinstance(payload, dict) else {}
        if not isinstance(models, dict):
            return {}
        entry = models.get(normalized_target, {})
        return dict(entry or {}) if isinstance(entry, dict) else {}

    def _apply_saved_step4_training_model_selection(self, target: str | None = None) -> bool:
        normalized_target = str(target or self.get_campaign_training_target() or "").strip().lower()
        if normalized_target not in ("char", "plate"):
            return False

        saved = self._resolve_saved_step4_training_model_selection(normalized_target)
        base_key = str(saved.get("base_model_key", "") or "").strip()
        custom_path = str(saved.get("base_custom_path", "") or "").strip()
        if not base_key:
            return False

        if base_key == "Custom":
            if not custom_path or not Path(custom_path).exists():
                return False
            self.base_model_var.set("Custom")
            self.base_custom_var.set(custom_path)
            return True

        choices = self._get_base_model_choices_for_mode(normalized_target)
        if base_key not in choices:
            return False
        self.base_model_var.set(base_key)
        self.base_custom_var.set("")
        return True

    def _remember_current_step4_training_model_selection(self) -> None:
        if not CAMPAIGN.get_active_project_name():
            return
        if bool(getattr(self, "_step4_suppress_base_model_state_save", False)):
            return

        target = str(self.get_campaign_training_target() or "").strip().lower()
        if target not in ("char", "plate"):
            return

        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        custom_value = str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()
        payload = self._load_step4_training_ui_state()
        if not isinstance(payload, dict):
            payload = {}
        models = payload.get("models", {})
        if not isinstance(models, dict):
            models = {}
        models[target] = {
            "base_model_key": base_key,
            "base_custom_path": custom_value if base_key == "Custom" else "",
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        payload["models"] = models
        self._save_step4_training_ui_state(payload)

    def _resolve_campaign_plate_ready_dataset(self, datasets_dir: Path | None = None) -> dict:
        result = {
            "path": None,
            "counts": {"train": 0, "val": 0, "test": 0, "total": 0},
            "stale": False,
        }

        if not CAMPAIGN.get_active_project_name():
            return result

        try:
            approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
        except Exception:
            approved_stats = {}
        approved_images = int(approved_stats.get("images", 0) or 0)

        candidate_paths: list[Path] = []
        seen: set[str] = set()

        stored = dict(CAMPAIGN.get_last_plate_training_source() or {})
        stored_dataset_path = str(stored.get("dataset_path", "") or "").strip()
        if stored_dataset_path:
            try:
                stored_path = Path(stored_dataset_path)
            except Exception:
                stored_path = None
            if stored_path is not None and stored_path.exists():
                key = str(stored_path.resolve())
                seen.add(key)
                candidate_paths.append(stored_path)

        if datasets_dir is not None and datasets_dir.exists():
            try:
                ready_candidates = self._find_ready_dataset_candidates(datasets_dir)
            except Exception:
                ready_candidates = []
            ready_candidates.sort(key=lambda rec: rec[2], reverse=True)
            for path, target, _stamp in ready_candidates:
                if target != "plate":
                    continue
                try:
                    key = str(path.resolve())
                except Exception:
                    key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                candidate_paths.append(path)

        stale_path = None
        stale_counts = None

        for path in candidate_paths:
            counts = self._get_dataset_split_image_counts(path)
            total_images = int(counts.get("total", 0) or 0)
            if total_images <= 0:
                continue
            if approved_images > 0 and total_images == approved_images:
                result["path"] = path
                result["counts"] = counts
                return result
            if stale_path is None:
                stale_path = path
                stale_counts = counts

        if stale_path is not None and approved_images > 0:
            result["path"] = stale_path
            result["counts"] = stale_counts or result["counts"]
            result["stale"] = True

        return result

    def _get_runs_base_dir(self) -> Path:
        """Zwraca bazowy katalog runów treningowych dla aktywnego projektu albo globalny fallback."""
        if self._campaign_runs_dir:
            return Path(self._campaign_runs_dir)
        target = getattr(self, "_step4_dataset_mode", getattr(self, "_campaign_training_target", "char"))
        return Path(CONFIG.get_training_runs_dir(target))

    def _rebind_free_mode_training_storage(self, target: str | None = None, reload_history: bool = True):
        if CAMPAIGN.get_active_project_name():
            return

        normalized_target = CONFIG.normalize_task_target(target or getattr(self, "_step4_dataset_mode", "char"))

        runs_dir = Path(CONFIG.get_training_runs_dir(normalized_target))
        self.history = TrainingHistory(history_dir=runs_dir)
        self.trainer = YOLOPoseTrainer(history=self.history)
        self._bind_trainer_callbacks()

        if reload_history and hasattr(self, "tree"):
            try:
                self._load_history()
            except Exception:
                pass
        if reload_history and hasattr(self, "rank_tree"):
            try:
                if normalized_target == "plate" and self._is_ranking_tab_active():
                    self._load_ranking()
            except Exception:
                pass

    def _format_workspace_relative_path(self, path_like) -> str:
        try:
            path = Path(path_like).resolve()
            workspace = Path(CONFIG.WORKSPACE_DIR).resolve()
            rel = path.relative_to(workspace)
            rel_posix = PurePosixPath(rel.as_posix())
            return str(PurePosixPath("Workspace") / rel_posix)
        except Exception:
            try:
                return Path(path_like).as_posix()
            except Exception:
                return str(path_like)

    def _get_training_dataset_hint_text(self) -> str:
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        selected_target = self._get_selected_training_target()
        workspace_dir = self._format_workspace_relative_path(CONFIG.get_datasets_dir(selected_target))

        if campaign_active:
            return f"Katalog splitów: {workspace_dir}"

        if selected_target == "plate":
            source_hint = (
                "Splity YOLO Pose do treningu tablic."
            )
        else:
            source_hint = (
                "Splity YOLO Detect do treningu znaków. Dataset OCR/klasyfikacyjny nie jest wejściem treningu YOLO."
            )

        return (
            f"{source_hint}\n"
            f"Katalog splitów: {workspace_dir}"
        )

    def _get_training_dataset_quality_thresholds(self, target: str | None = None) -> dict:
        normalized = CONFIG.normalize_task_target(target or self._get_selected_training_target())
        if normalized == "plate":
            return {
                "object_label": "anotacje tablic",
                "min_images": int(getattr(CONFIG, "CAMPAIGN_MIN_PLATE_ANNOTATIONS", 10) or 10),
                "min_train": 8,
                "min_val": 1,
                "min_objects": int(getattr(CONFIG, "CAMPAIGN_MIN_PLATE_ANNOTATIONS", 10) or 10),
                "recommended_images": int(getattr(CONFIG, "YOLO_POSE_AVERAGE_PLATES", 50) or 50),
                "recommended_train": 40,
                "recommended_val": 5,
                "recommended_objects": int(getattr(CONFIG, "YOLO_POSE_GOOD_PLATES", 200) or 200),
            }
        return {
            "object_label": "boxy znaków",
            "min_images": int(getattr(CONFIG, "YOLO_CHAR_AVERAGE_PLATES", 10) or 10),
            "min_train": 8,
            "min_val": 1,
            "min_objects": int(getattr(CONFIG, "YOLO_CHAR_AVERAGE_BOXES", 100) or 100),
            "recommended_images": int(getattr(CONFIG, "YOLO_CHAR_GOOD_PLATES", 50) or 50),
            "recommended_train": 40,
            "recommended_val": 5,
            "recommended_objects": int(getattr(CONFIG, "YOLO_CHAR_GOOD_BOXES", 1000) or 1000),
        }

    @staticmethod
    def _format_dataset_quality_need(current: int, expected: int) -> str:
        current = max(0, int(current or 0))
        expected = max(0, int(expected or 0))
        if expected <= 0:
            return str(current)
        return f"{current}/{expected}"

    def _build_training_dataset_quality_summary(self) -> dict:
        target = self._get_selected_training_target()
        thresholds = self._get_training_dataset_quality_thresholds(target)
        dataset_yaml = self._resolve_training_dataset_yaml_path()
        if dataset_yaml is None:
            return {
                "visible": not bool(CAMPAIGN.get_active_project_name()),
                "tone": "muted",
                "status": "Wybierz wariant",
                "rows": [
                    ("Status", "Brak aktywnego wariantu datasetu."),
                    ("Minimum testowe", "Po wyborze wariantu pokażę licznik obrazów i anotacji."),
                    ("Zalecane", "Progi są orientacyjne i nie blokują treningu w trybie swobodnym."),
                ],
            }

        profile = self._get_training_dataset_profile(dataset_yaml)
        train_images = int(profile.get("train_images", 0) or 0)
        val_images = int(profile.get("val_images", 0) or 0)
        test_images = int(profile.get("test_images", 0) or 0)
        total_images = int(profile.get("total_images", 0) or 0)
        total_objects = int(profile.get("total_objects", 0) or 0)
        object_label = str(thresholds.get("object_label") or "anotacje")

        min_ready = (
            total_images >= int(thresholds["min_images"])
            and train_images >= int(thresholds["min_train"])
            and val_images >= int(thresholds["min_val"])
            and total_objects >= int(thresholds["min_objects"])
        )
        recommended_ready = (
            total_images >= int(thresholds["recommended_images"])
            and train_images >= int(thresholds["recommended_train"])
            and val_images >= int(thresholds["recommended_val"])
            and total_objects >= int(thresholds["recommended_objects"])
        )

        if CONFIG.normalize_task_target(target) == "plate":
            quality_info = CONFIG.describe_yolo_pose_dataset_quality(total_objects)
        else:
            quality_info = CONFIG.describe_yolo_char_dataset_quality(
                perfect_plates=total_images,
                char_boxes=total_objects,
            )
        quality_label = str(quality_info.get("label", "SŁABY") or "SŁABY").strip()
        quality_ranges = str(quality_info.get("range_text", "") or "").strip()

        if recommended_ready:
            tone = "success"
            status = f"Jakość zbioru: {quality_label}. Dataset wygląda sensownie do treningu."
        elif min_ready:
            tone = "warning"
            status = f"Jakość zbioru: {quality_label}. Dataset nadaje się do testowego startu, ale warto go powiększyć."
        else:
            tone = "danger"
            status = f"Jakość zbioru: {quality_label}. Dataset jest za mały na sensowny trening."

        rows = [
            ("Status", status),
            ("Aktualnie", f"obrazy {total_images} | train {train_images}, val {val_images}, test {test_images} | {object_label}: {total_objects}"),
            (
                "Minimum testowe",
                " | ".join(
                    [
                        f"obrazy {self._format_dataset_quality_need(total_images, thresholds['min_images'])}",
                        f"train {self._format_dataset_quality_need(train_images, thresholds['min_train'])}",
                        f"val {self._format_dataset_quality_need(val_images, thresholds['min_val'])}",
                        f"{object_label} {self._format_dataset_quality_need(total_objects, thresholds['min_objects'])}",
                    ]
                ),
            ),
            (
                "Próg DOBRY",
                " | ".join(
                    [
                        f"obrazy {self._format_dataset_quality_need(total_images, thresholds['recommended_images'])}",
                        f"train {self._format_dataset_quality_need(train_images, thresholds['recommended_train'])}",
                        f"val {self._format_dataset_quality_need(val_images, thresholds['recommended_val'])}",
                        f"{object_label} {self._format_dataset_quality_need(total_objects, thresholds['recommended_objects'])}",
                    ]
                ),
            ),
            ("Przedziały jakości", quality_ranges),
            ("Uwaga", "To podpowiedź jakości, nie blokada. Mały dataset pozwala sprawdzić pipeline, ale zwykle nie daje stabilnego modelu."),
        ]
        return {"visible": not bool(CAMPAIGN.get_active_project_name()), "tone": tone, "status": status, "rows": rows}

    def _get_preferred_models_dir(self, target: str | None = None) -> Path:
        normalized_target = CONFIG.normalize_task_target(target or self._get_selected_training_target())

        preferred = CONFIG.get_trained_models_dir(normalized_target)
        return preferred if preferred.exists() else Path(CONFIG.DEFAULT_MODELS_DIR)

    def _pick_base_custom_model(self):
        if CAMPAIGN.get_active_project_name():
            return
        previous_value = str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()
        self._pick_file(
            self.base_custom_var,
            "*.pt",
            self._get_preferred_models_dir(self._get_selected_training_target())
        )
        selected_value = str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()
        if selected_value and selected_value != previous_value:
            selection_ok, _selection_message = self._validate_training_base_model_target_compatibility(
                target=self._get_selected_training_target(),
                show_dialog=True,
            )
            if not selection_ok:
                self.base_custom_var.set(previous_value)
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

    def _get_selected_training_target(self) -> str:
        if CAMPAIGN.get_active_project_name():
            target = self.get_campaign_training_target()
            return target if target in ("char", "plate") else "char"

        target = CONFIG.normalize_task_target(getattr(self, "_step4_dataset_mode", "char"))
        return target if target in ("char", "plate") else "char"

    def _get_locked_campaign_training_target(self) -> str | None:
        if not CAMPAIGN.get_active_project_name():
            return None

        target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        return target if target in ("char", "plate") else None

    @staticmethod
    def _is_finish_eligible_training_status(status: str | None) -> bool:
        value = str(status or "").strip().lower()
        return value in {
            TrainingStatus.COMPLETED.value,
            TrainingStatus.FAILED.value,
            TrainingStatus.CANCELLED.value,
            "stopped",
        }

    def _get_campaign_history_for_finish_recovery(self) -> TrainingHistory | None:
        if not CAMPAIGN.get_active_project_name():
            return None

        runs_dir = CAMPAIGN.get_dir("runs")
        if runs_dir is None:
            return None

        try:
            runs_path = Path(runs_dir).resolve()
        except Exception:
            runs_path = Path(runs_dir)

        try:
            if self.history is not None and str(Path(getattr(self.history, "history_dir", "")).resolve()) == str(runs_path):
                return self.history
        except Exception:
            pass

        try:
            return TrainingHistory(history_dir=runs_path)
        except Exception:
            return None

    def _validate_campaign_finish_run(
        self,
        run_id: str,
        *,
        target: str | None = None,
        history: TrainingHistory | None = None,
    ) -> dict:
        normalized_target = str(target or self.get_campaign_training_target() or "").strip().lower()
        if normalized_target not in ("char", "plate"):
            return {}

        expected_dataset_path = ""
        if normalized_target == "plate":
            try:
                stored_plate_source = dict(CAMPAIGN.get_last_plate_training_source() or {})
            except Exception:
                stored_plate_source = {}
            expected_dataset_path = str(stored_plate_source.get("dataset_path", "") or "").strip()
        else:
            try:
                readiness = self.get_campaign_step4_readiness(iteration_target=normalized_target) or {}
            except Exception:
                readiness = {}
            expected_dataset_path = str(readiness.get("ready_dataset", "") or "").strip()

        history_source = history or self._get_campaign_history_for_finish_recovery()
        if history_source is None:
            return {}

        try:
            run = history_source.get_run(str(run_id or "").strip())
        except Exception:
            run = None
        if run is None:
            return {}

        status_value = str(getattr(run, "status", "") or "").strip().lower()
        if not self._is_finish_eligible_training_status(status_value):
            return {}

        run_target = ""
        infer_target = getattr(history_source, "_infer_run_target", None)
        try:
            if callable(infer_target):
                run_target = str(infer_target(run) or "").strip().lower()
        except Exception:
            run_target = ""
        if run_target not in ("char", "plate"):
            try:
                run_target = str(
                    self._infer_dataset_target(getattr(run, "dataset_path", "")) or ""
                ).strip().lower()
            except Exception:
                run_target = ""
        if run_target != normalized_target:
            return {}

        if expected_dataset_path:
            try:
                expected_dataset_resolved = str(Path(expected_dataset_path).resolve())
            except Exception:
                expected_dataset_resolved = expected_dataset_path
            run_dataset_raw = str(getattr(run, "dataset_path", "") or "").strip()
            try:
                run_dataset_resolved = str(Path(run_dataset_raw).resolve()) if run_dataset_raw else ""
            except Exception:
                run_dataset_resolved = run_dataset_raw
            if run_dataset_resolved and run_dataset_resolved != expected_dataset_resolved:
                return {}

        best_weights = str(getattr(run, "best_weights", "") or "").strip()
        last_weights = str(getattr(run, "last_weights", "") or "").strip()
        output_dir = str(getattr(run, "output_dir", "") or "").strip()
        try:
            has_artifacts = bool(
                (best_weights and Path(best_weights).exists())
                or (last_weights and Path(last_weights).exists())
                or (output_dir and Path(output_dir).exists())
            )
        except Exception:
            has_artifacts = bool(best_weights or last_weights or output_dir)
        if not has_artifacts:
            return {}

        return {
            "ready": True,
            "run_id": str(getattr(run, "id", "") or "").strip(),
            "target": normalized_target,
            "status": status_value,
        }

    def _recover_campaign_finish_state_from_history(
        self,
        target: str | None = None,
        *,
        history: TrainingHistory | None = None,
    ) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}

        try:
            current_step = int(CAMPAIGN.get_current_step() or 0)
        except Exception:
            current_step = 0
        if current_step < 4:
            return {}

        normalized_target = str(target or self.get_campaign_training_target() or "").strip().lower()
        if normalized_target not in ("char", "plate"):
            return {}

        expected_dataset_path = ""
        if normalized_target == "plate":
            try:
                stored_plate_source = dict(CAMPAIGN.get_last_plate_training_source() or {})
            except Exception:
                stored_plate_source = {}
            expected_dataset_path = str(stored_plate_source.get("dataset_path", "") or "").strip()
            try:
                expected_dataset_path = str(Path(expected_dataset_path).resolve()) if expected_dataset_path else ""
            except Exception:
                pass
        else:
            try:
                readiness = self.get_campaign_step4_readiness(iteration_target=normalized_target) or {}
            except Exception:
                readiness = {}
            expected_dataset_path = str(readiness.get("ready_dataset", "") or "").strip()
            try:
                expected_dataset_path = str(Path(expected_dataset_path).resolve()) if expected_dataset_path else ""
            except Exception:
                pass

        history_source = history or self._get_campaign_history_for_finish_recovery()
        try:
            all_runs = list(history_source.get_all_runs() or []) if history_source is not None else []
        except Exception:
            all_runs = []
        if not all_runs:
            return {}

        infer_target = getattr(history_source, "_infer_run_target", None)
        for run in all_runs:
            if not self._is_finish_eligible_training_status(getattr(run, "status", "")):
                continue

            run_target = ""
            try:
                if callable(infer_target):
                    run_target = str(infer_target(run) or "").strip().lower()
            except Exception:
                run_target = ""
            if run_target not in ("char", "plate"):
                try:
                    run_target = str(
                        self._infer_dataset_target(getattr(run, "dataset_path", "")) or ""
                    ).strip().lower()
                except Exception:
                    run_target = ""
            if run_target != normalized_target:
                continue

            if expected_dataset_path:
                run_dataset_raw = str(getattr(run, "dataset_path", "") or "").strip()
                try:
                    run_dataset_path = str(Path(run_dataset_raw).resolve()) if run_dataset_raw else ""
                except Exception:
                    run_dataset_path = run_dataset_raw
                if run_dataset_path and run_dataset_path != expected_dataset_path:
                    continue

            best_weights = str(getattr(run, "best_weights", "") or "").strip()
            output_dir = str(getattr(run, "output_dir", "") or "").strip()
            try:
                has_artifacts = bool(
                    (best_weights and Path(best_weights).exists())
                    or (output_dir and Path(output_dir).exists())
                )
            except Exception:
                has_artifacts = bool(best_weights or output_dir)
            if not has_artifacts:
                continue

            return {
                "ready": True,
                "run_id": str(getattr(run, "id", "") or "").strip(),
                "target": normalized_target,
                "status": str(getattr(run, "status", "") or "").strip().lower(),
            }

        return {}

    def get_campaign_step4_finish_state(self, *, iteration_target: str | None = None) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {"ready": False, "run_id": "", "target": "", "iteration": 0}

        target = str(iteration_target or CAMPAIGN.get_iteration_target() or self.get_campaign_training_target() or "").strip().lower()
        if target not in ("char", "plate"):
            target = "char"
        try:
            current_iteration = int(CAMPAIGN.get_current_iteration_num() or 0)
        except Exception:
            current_iteration = 0
        current_iteration_state = {}
        current_iteration_step4 = {}
        try:
            current_iteration_state = dict(CAMPAIGN.get_iteration_state(iteration_num=current_iteration) or {})
            current_iteration_step4 = dict(current_iteration_state.get("step4_training") or {})
        except Exception:
            current_iteration_state = {}
            current_iteration_step4 = {}
        if not current_iteration_step4:
            try:
                current_bundle = dict(CAMPAIGN.get_iteration_artifact_bundle(iteration_num=current_iteration) or {})
                current_iteration_step4 = dict(current_bundle.get("step4_training") or {})
            except Exception:
                current_iteration_step4 = {}

        stored = {}
        try:
            stored = CAMPAIGN.get_step4_finish_state() or {}
        except Exception:
            stored = {}

        history_source = self._get_campaign_history_for_finish_recovery()
        stored_ready = bool(stored.get("ready", False))
        stored_run_id = str(stored.get("run_id", "") or "").strip()
        stored_target = str(stored.get("target", "") or "").strip().lower()
        stored_iteration = int(stored.get("iteration", 0) or 0)
        if stored_target not in ("char", "plate"):
            stored_target = target

        bundle_run_id = str(current_iteration_step4.get("run_id", "") or "").strip()
        bundle_target = str(current_iteration_step4.get("target", "") or "").strip().lower()
        bundle_status = str(current_iteration_step4.get("status", "") or "").strip().lower()
        iteration_training_matches = bool(
            bundle_run_id
            and bundle_target == target
            and self._is_finish_eligible_training_status(bundle_status)
        )

        if (
            stored_ready
            and stored_run_id
            and stored_iteration == current_iteration
            and iteration_training_matches
            and bundle_run_id == stored_run_id
        ):
            validated = self._validate_campaign_finish_run(
                stored_run_id,
                target=stored_target,
                history=history_source,
            )
            if validated:
                if stored_target != target and target in ("char", "plate"):
                    validated["target"] = target
                validated["iteration"] = current_iteration
                return validated

        recovered = (
            self._recover_campaign_finish_state_from_history(target, history=history_source)
            if iteration_training_matches
            else {}
        )
        if recovered:
            recovered_run_id = str(recovered.get("run_id", "") or "").strip()
            if recovered_run_id != bundle_run_id:
                recovered = {}
        if recovered:
            recovered["iteration"] = current_iteration
            try:
                CAMPAIGN.set_step4_finish_state(
                    True,
                    run_id=str(recovered.get("run_id", "") or "").strip(),
                    target=str(recovered.get("target", target) or "").strip().lower(),
                    iteration_num=current_iteration,
                )
            except Exception:
                pass
            return recovered

        if stored_ready or stored_run_id:
            try:
                CAMPAIGN.set_step4_finish_state(False)
            except Exception:
                pass

        return {"ready": False, "run_id": "", "target": target, "iteration": current_iteration}

    def _build_training_dataset_validation_message(self, dataset_root: Path, msg: str, stats: dict | None = None) -> str:
        stats = stats or {}
        target = self._get_selected_training_target()
        train_images = int(stats.get("train_images", 0) or 0)
        val_images = int(stats.get("val_images", 0) or 0)
        test_images = int(stats.get("test_images", 0) or 0)
        dataset_label = self._format_training_target_label(target)
        dataset_rel = self._format_workspace_relative_path(dataset_root)

        guidance = (
            "Popraw dataset i uruchom trening ponownie."
        )
        if msg == "Brak obrazów w images/val":
            if target == "plate":
                guidance = (
                    "Ten dataset ma pusty split walidacyjny `images/val`. "
                    "Przebuduj dataset tablic w Z2, aby co najmniej 1 oznaczony obraz trafił do walidacji. "
                    "Przy bardzo małych próbkach oznacz przynajmniej 2 obrazy, a praktycznie 3+."
                )
            else:
                guidance = (
                    "Ten dataset ma pusty split walidacyjny `images/val`. "
                    "Przebuduj lub podziel dataset ponownie tak, aby co najmniej 1 obraz trafił do walidacji."
                )
        elif msg == "Brak obrazów w images/train":
            guidance = (
                "Dataset nie ma zadnych obrazów treningowych. "
                "Przebuduj go tak, aby folder `images/train` zawieral dane do nauki modelu."
            )
        elif msg.startswith("Brak: images/"):
            missing_split = msg.split("Brak:", 1)[-1].strip()
            guidance = (
                f"Dataset nie zawiera wymaganego folderu `{missing_split}`. "
                "Przebuduj dataset, aby YOLO mial komplet wymaganych splitow."
            )

        unlock_note = ""
        if CAMPAIGN.get_active_project_name():
            unlock_note = (
                "\n\nDopoki trening w E4 nie wystartuje poprawnie, iteracja nie odblokuje zakończenia kroku 4."
            )

        return (
            "Dataset nie jest jeszcze gotowy do treningu.\n\n"
            f"Tor: {dataset_label}\n"
            f"Dataset: {dataset_rel}\n"
            f"train={train_images}, val={val_images}, test={test_images}\n"
            f"Walidacja: {msg}\n\n"
            f"{guidance}"
            f"{unlock_note}"
        )

    def _get_pose_dataset_size_warning(self, dataset_root: Path | None = None, stats: dict | None = None) -> str:
        try:
            root = Path(dataset_root or str(self.dataset_var.get() or "").strip())
        except Exception:
            return ""

        if not str(root):
            return ""

        yaml_path = root / "data.yaml"
        if not yaml_path.exists():
            return ""

        try:
            cfg = safe_load_yaml(yaml_path)
        except Exception:
            cfg = None

        if not isinstance(cfg, dict) or "kpt_shape" not in cfg:
            return ""

        loaded_stats = dict(stats or {})
        if not loaded_stats:
            is_valid, _validation_msg, validation_stats = self.trainer.validate_dataset(root)
            if not is_valid:
                return ""
            loaded_stats = dict(validation_stats or {})

        train_images = int(loaded_stats.get("train_images", 0) or 0)
        val_images = int(loaded_stats.get("val_images", 0) or 0)
        test_images = int(loaded_stats.get("test_images", 0) or 0)
        total_images = train_images + val_images + test_images

        if total_images <= 0:
            return ""

        if total_images <= 10 or train_images < 8 or val_images < 2:
            size_label = "bardzo mały"
            warning_body = (
                "Przy tak małej próbce model może nauczyć się zgrubnej lokalizacji tablicy, "
                "ale nie geometrii jej rogów. Częstym objawem są małe lub niestabilne wielokąty "
                "pojawiające się w okolicy prawdziwej tablicy."
            )
        elif total_images < 30 or train_images < 20 or val_images < 5:
            size_label = "mały"
            warning_body = (
                "To zwykle wystarcza tylko na bardzo wstępny eksperyment. Geometria rogów tablic "
                "może być nadal niestabilna, dlatego przed oceną modelu warto powiększyć zbiór ręcznych anotacji."
            )
        else:
            return ""

        return (
            f"Ostrzeżenie: dataset YOLO Pose jest {size_label} "
            f"(train={train_images}, val={val_images}, test={test_images}, razem={total_images}).\n"
            f"Przy tak małym zbiorze split 80/10/10 może naturalnie dać np. {train_images}/{val_images}/{test_images}; "
            "to nie jest błąd splitu, tylko skutek małej liczby obrazów.\n"
            f"{warning_body}"
        )

    @staticmethod
    def _extract_dataset_class_names(cfg: dict | None) -> list[str]:
        if not isinstance(cfg, dict):
            return []

        names = cfg.get("names", [])
        if isinstance(names, dict):
            try:
                ordered_keys = sorted(
                    names.keys(),
                    key=lambda item: int(item) if str(item).isdigit() else str(item)
                )
                names = [names[key] for key in ordered_keys]
            except Exception:
                names = list(names.values())
        elif not isinstance(names, (list, tuple)):
            names = []

        return [str(name).strip() for name in names if str(name).strip()]

    @staticmethod
    def _looks_like_character_alphabet(class_names: list[str]) -> bool:
        if len(class_names) < 8:
            return False

        import string

        allowed = set(string.ascii_uppercase + string.digits)
        for name in class_names:
            token = str(name).strip().upper()
            if len(token) != 1 or token not in allowed:
                return False

        return True

    def _infer_detect_dataset_target(self, cfg: dict | None, path_like) -> str:
        path_str = str(path_like or "").replace("\\", "/").lower()
        vehicle_keywords = (
            "vehicle", "vehicles", "pojazd", "pojazdy", "car", "cars", "truck", "trucks",
            "bus", "buses", "motorcycle", "motorbike", "bike", "van", "pickup", "suv",
            "samochod", "samochody"
        )
        char_keywords = (
            "char", "chars", "character", "characters", "znak", "znaki", "litera", "litery"
        )

        class_names = self._extract_dataset_class_names(cfg)
        joined_names = " ".join(name.lower() for name in class_names)

        if any(keyword in path_str for keyword in vehicle_keywords):
            return "vehicle"
        if any(keyword in joined_names for keyword in vehicle_keywords):
            return "vehicle"
        plate_class_names = {"plate", "plates", "license_plate", "license-plate", "tablica", "tablice"}
        if class_names and all(str(name).strip().lower() in plate_class_names for name in class_names):
            return "plate"
        if self._looks_like_character_alphabet(class_names):
            return "char"
        if any(keyword in path_str for keyword in char_keywords):
            return "char"

        return "char"

    def _infer_dataset_target(self, dataset_value: str | None = None) -> str | None:
        if dataset_value is None:
            var = getattr(self, "dataset_var", None)
            dataset_value = var.get() if var is not None else ""
        dataset_value = str(dataset_value).strip()
        if not dataset_value:
            return None

        dataset_path = Path(dataset_value)
        yaml_path = dataset_path / "data.yaml" if dataset_path.is_dir() else dataset_path
        cfg = None

        if yaml_path.exists():
            try:
                cfg = safe_load_yaml(yaml_path)
            except Exception:
                cfg = None

        if isinstance(cfg, dict) and "kpt_shape" in cfg:
            return "plate"

        return self._infer_detect_dataset_target(cfg, yaml_path if yaml_path.exists() else dataset_path)

    def _get_effective_training_target(self) -> str:
        if CAMPAIGN.get_active_project_name():
            return self.get_campaign_training_target()

        inferred = self._infer_dataset_target()
        if inferred in ("char", "plate", "vehicle"):
            return inferred

        fallback = CONFIG.normalize_task_target(getattr(self, "_step4_dataset_mode", "char"))
        return fallback if fallback in ("char", "plate", "vehicle") else "char"

    @staticmethod
    def _format_training_target_label(target: str) -> str:
        normalized = CONFIG.normalize_task_target(target)
        labels = {
            "plate": "tablice (YOLO Pose)",
            "char": "znaki tablic (YOLO Detect)",
            "vehicle": "pojazdy (YOLO Detect)",
        }
        return labels.get(normalized, "znaki tablic (YOLO Detect)")

    @staticmethod
    def _format_history_run_target_label(target: str) -> str:
        normalized = CONFIG.normalize_task_target(target)
        labels = {
            "plate": "Tablice",
            "char": "Znaki",
            "vehicle": "Pojazdy",
        }
        return labels.get(normalized, "Inny")

    def _get_training_scope_hint_text(self) -> str:
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        selected_target = self._get_selected_training_target()
        selected_label = self._format_training_target_label(selected_target)

        if campaign_active:
            dataset_value = str(getattr(self, "dataset_var", tk.StringVar()).get() or "").strip()
            dataset_counts = self._get_dataset_split_image_counts(dataset_value)
            total_images = int(dataset_counts.get("total", 0) or 0)
            if total_images > 0:
                return (
                    f"Tor kampanii: {selected_label}. "
                    f"train={dataset_counts.get('train', 0)}, "
                    f"val={dataset_counts.get('val', 0)}, "
                    f"test={dataset_counts.get('test', 0)}, "
                    f"razem={total_images}."
                )
            return f"Tor kampanii: {selected_label}."

        dataset_value = getattr(self, "dataset_var", None)
        inferred_target = self._infer_dataset_target(dataset_value.get() if dataset_value is not None else "")
        if inferred_target and inferred_target != selected_target:
            inferred_label = self._format_training_target_label(inferred_target)
            return (
                f"Tor: {selected_label}. Dataset wygląda na: {inferred_label}."
            )

        return f"Tor: {selected_label}."

    def _get_base_model_choices_for_mode(self, mode: str | None = None) -> list[str]:
        normalized = CONFIG.normalize_task_target(mode or self._get_selected_training_target())
        if normalized == "plate":
            return list(AVAILABLE_POSE_MODELS.keys()) + ["Custom"]
        return list(AVAILABLE_DETECT_MODELS.keys()) + ["Custom"]

    def _get_default_base_model_for_mode(self, mode: str | None = None) -> str:
        choices = self._get_base_model_choices_for_mode(mode)
        for choice in choices:
            if choice != "Custom":
                return choice
        return "Custom"

    def _is_pose_base_model(self, base_key: str, base_model: str) -> bool:
        base_key = str(base_key or "").strip()
        base_model = str(base_model or "").strip()

        if base_key in AVAILABLE_POSE_MODELS:
            return True
        if base_key in AVAILABLE_DETECT_MODELS:
            return False

        model_text = base_model.lower()
        if "pose" in model_text:
            return True

        try:
            model_path = Path(base_model)
        except Exception:
            model_path = None

        if model_path is not None and model_path.suffix.lower() == ".pt" and model_path.exists():
            ok, _message, info = validate_model_file(model_path)
            if ok:
                task = str(info.get("task") or "").strip().lower()
                inferred_type = str(info.get("type") or "").strip().lower()
                if bool(info.get("keypoints")) or task == "pose" or inferred_type == "pose":
                    return True

        return False

    def _refresh_base_model_choices(self):
        combo = getattr(self, "base_combo", None)
        var = getattr(self, "base_model_var", None)
        if combo is None or var is None:
            return

        choices = self._get_base_model_choices_for_mode()
        current = str(var.get() or "").strip()

        try:
            combo.configure(values=choices)
        except Exception:
            pass

        if current not in choices:
            var.set(self._get_default_base_model_for_mode())

        self._on_base_model_change()
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

    def _refresh_training_base_model_selection_ui(self):
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        base_key = str(getattr(self, "base_model_var", tk.StringVar()).get() or "").strip()
        custom_value = str(getattr(self, "base_custom_var", tk.StringVar()).get() or "").strip()

        base_combo = getattr(self, "base_combo", None)
        custom_row = getattr(self, "custom_row", None)
        custom_entry = getattr(self, "base_custom_entry", None)
        custom_btn = getattr(self, "base_custom_btn", None)

        show_custom_row = True
        if campaign_active:
            show_custom_row = bool(base_key == "Custom" and custom_value)

        if custom_row is not None:
            try:
                if show_custom_row:
                    if not str(custom_row.winfo_manager()):
                        custom_row.pack(fill=tk.X, pady=2, after=base_combo)
                else:
                    custom_row.pack_forget()
            except Exception:
                pass

        if custom_entry is not None:
            try:
                if base_key == "Custom":
                    custom_entry.configure(state=("readonly" if campaign_active else tk.NORMAL))
                else:
                    custom_entry.configure(state=tk.DISABLED)
            except Exception:
                pass

        if custom_btn is not None:
            try:
                if campaign_active:
                    custom_btn.pack_forget()
                    custom_btn.configure(state=tk.DISABLED)
                else:
                    if not str(custom_btn.winfo_manager()):
                        custom_btn.pack(side=tk.LEFT, padx=(8, 0))
                    custom_btn.configure(state=(tk.NORMAL if base_key == "Custom" else tk.DISABLED))
            except Exception:
                pass

        try:
            self._refresh_training_base_model_identity_ui()
        except Exception:
            pass

    def _pick_training_dataset_dir(self):
        if CAMPAIGN.get_active_project_name():
            return
        self._pick_dir(
            self.dataset_var,
            initialdir=self._get_training_dataset_picker_dir(),
        )

    def _pick_training_dataset_yaml(self):
        if CAMPAIGN.get_active_project_name():
            return
        self._pick_file(
            self.dataset_var,
            "*.yaml",
            initialdir=self._get_training_dataset_picker_dir(),
        )

    def _prepare_picker_initial_dir(self, path: Path | str | None) -> str:
        if path is None:
            return ""
        try:
            candidate = Path(path)
            if candidate.suffix and not candidate.is_dir():
                candidate = candidate.parent
            candidate.mkdir(parents=True, exist_ok=True)
            return str(candidate.resolve())
        except Exception:
            try:
                return str(path)
            except Exception:
                return ""

    def _get_current_picker_parent(self, var_name: str) -> str:
        var = getattr(self, var_name, None)
        if var is None:
            return ""
        try:
            raw = str(var.get() or "").strip()
        except Exception:
            raw = ""
        if not raw:
            return ""
        try:
            path = Path(raw)
            if path.is_file():
                path = path.parent
            elif not path.exists() and path.suffix:
                path = path.parent
            if path.exists() and path.is_dir():
                return str(path.resolve())
        except Exception:
            pass
        return ""

    def _get_first_picker_dir(self, *candidates: Path | str | None) -> str:
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                path = Path(candidate)
                if path.exists() and path.is_dir():
                    return str(path.resolve())
            except Exception:
                continue
        for candidate in candidates:
            if candidate is not None:
                return self._prepare_picker_initial_dir(candidate)
        return ""

    def _get_plate_xml_picker_dir(self) -> str:
        current = self._get_current_picker_parent("cvat_xml_var")
        if current:
            return current

        campaign_auto_dir = None
        campaign_staging_auto_dir = None
        try:
            campaign_auto_dir = CAMPAIGN.get_dir("auto_ann")
        except Exception:
            campaign_auto_dir = None
        try:
            campaign_staging_auto_dir = CAMPAIGN.get_staging_dir("auto_ann")
        except Exception:
            campaign_staging_auto_dir = None

        return self._get_first_picker_dir(
            campaign_auto_dir,
            campaign_staging_auto_dir,
            CONFIG.get_auto_annotations_dir("plate"),
        )

    def _get_plate_images_picker_dir(self) -> str:
        current = self._get_current_picker_parent("cvat_images_var")
        if current:
            return current

        iteration_images_dir = None
        iteration_raw_dir = None
        master_pool_dir = None
        campaign_raw_dir = None
        try:
            iteration_images_dir = CAMPAIGN.get_iteration_image_source_dir()
        except Exception:
            iteration_images_dir = None
        try:
            iteration_raw_dir = CAMPAIGN.get_iteration_raw_dir()
        except Exception:
            iteration_raw_dir = None
        try:
            master_pool_dir = CAMPAIGN.get_master_pool_dir()
        except Exception:
            master_pool_dir = None
        try:
            campaign_raw_dir = CAMPAIGN.get_dir("raw")
        except Exception:
            campaign_raw_dir = None

        return self._get_first_picker_dir(
            iteration_images_dir,
            iteration_raw_dir,
            master_pool_dir,
            campaign_raw_dir,
            CONFIG.DIR_1_RAW,
        )

    def _get_char_dataset_source_picker_dir(self) -> str:
        current = self._get_current_picker_parent("split_src_var")
        if current:
            return current

        campaign_datasets_dir = None
        try:
            campaign_datasets_dir = CAMPAIGN.get_dir("datasets")
        except Exception:
            campaign_datasets_dir = None

        return self._get_first_picker_dir(
            campaign_datasets_dir,
            CONFIG.get_datasets_dir("char"),
        )

    def _count_yolo_image_label_pairs(self, source_dir: Path) -> dict:
        source_dir = Path(source_dir)
        stats = {
            "total": 0,
            "flat": 0,
            "train": 0,
            "val": 0,
            "test": 0,
            "images_without_labels": 0,
        }
        seen_images: set[str] = set()

        for split in ("train", "val", "test", ""):
            candidates = []
            if split:
                candidates.extend(
                    [
                        (source_dir / "images" / split, source_dir / "labels" / split),
                        (source_dir / split / "images", source_dir / split / "labels"),
                    ]
                )
            else:
                candidates.append((source_dir / "images", source_dir / "labels"))

            for image_dir, label_dir in candidates:
                if not image_dir.exists() or not image_dir.is_dir():
                    continue

                for image_path in image_dir.iterdir():
                    if image_path.suffix.lower() not in CONFIG.IMAGE_EXTENSIONS:
                        continue
                    try:
                        image_key = str(image_path.resolve())
                    except Exception:
                        image_key = str(image_path)
                    if image_key in seen_images:
                        continue
                    seen_images.add(image_key)
                    label_path = label_dir / f"{image_path.stem}.txt"
                    if label_path.exists():
                        key = split or "flat"
                        stats[key] = int(stats.get(key, 0) or 0) + 1
                        stats["total"] += 1
                    else:
                        stats["images_without_labels"] += 1

        return stats

    def _has_supported_yolo_label_layout(self, source_dir: Path) -> bool:
        source_dir = Path(source_dir)
        if (source_dir / "images").exists() and (source_dir / "labels").exists():
            return True
        for split in ("train", "val", "test"):
            if (source_dir / split / "images").exists() and (source_dir / split / "labels").exists():
                return True
        return False

    def _find_char_yolo_dataset_root_candidates(self, source_dir: Path, *, max_depth: int = 2) -> list[dict]:
        source_dir = Path(source_dir)
        candidates: list[dict] = []
        seen: set[str] = set()

        def visit(path: Path, depth: int):
            try:
                resolved = str(path.resolve())
            except Exception:
                resolved = str(path)
            if resolved in seen:
                return
            seen.add(resolved)

            if self._has_supported_yolo_label_layout(path) and not self._looks_like_char_classification_dataset(path):
                stats = self._count_yolo_image_label_pairs(path)
                if int(stats.get("total", 0) or 0) > 0:
                    try:
                        stamp = float(path.stat().st_mtime)
                    except Exception:
                        stamp = 0.0
                    candidates.append({"path": path, "stats": stats, "stamp": stamp})
                    return

            if depth >= max_depth:
                return
            try:
                children = [child for child in path.iterdir() if child.is_dir()]
            except Exception:
                children = []
            for child in children:
                visit(child, depth + 1)

        visit(source_dir, 0)
        candidates.sort(key=lambda item: float(item.get("stamp", 0) or 0), reverse=True)
        return candidates

    def _write_char_yolo_data_yaml_if_missing(self, source_dir: Path, *, overwrite: bool = False) -> dict:
        source_dir = Path(source_dir)
        yaml_path = source_dir / "data.yaml"
        if yaml_path.exists() and not overwrite:
            return {"ok": True, "created": False, "path": yaml_path, "message": ""}

        has_canonical_split_layout = any((source_dir / "images" / split).exists() for split in ("train", "val", "test"))
        has_nested_split_layout = any((source_dir / split / "images").exists() for split in ("train", "val", "test"))
        lines = [f"path: {source_dir.resolve().as_posix()}"]
        if has_nested_split_layout:
            lines.append("train: train/images")
            lines.append("val: val/images")
            if (source_dir / "test" / "images").exists():
                lines.append("test: test/images")
        elif has_canonical_split_layout:
            lines.append("train: images/train")
            lines.append("val: images/val")
            if (source_dir / "images" / "test").exists():
                lines.append("test: images/test")
        else:
            lines.append("train: images")
            lines.append("val: images")

        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        lines.append(f"nc: {len(alphabet)}")
        lines.append("names:")
        for class_id, char in enumerate(alphabet):
            lines.append(f"  {class_id}: '{char}'")

        try:
            yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:
            return {
                "ok": False,
                "created": False,
                "path": yaml_path,
                "message": f"Dataset wygląda poprawnie, ale nie udało się dopisać data.yaml:\n{exc}",
            }

        return {"ok": True, "created": True, "path": yaml_path, "message": ""}

    def _validate_char_yolo_split_source(
        self,
        source_raw: str | Path | None = None,
        *,
        create_missing_yaml: bool = False,
        overwrite_incompatible_yaml: bool = False,
        resolve_nested_dataset: bool = False,
    ) -> dict:
        result = {
            "ok": False,
            "src": None,
            "stats": {},
            "reason": "",
            "yaml_created": False,
            "yaml_rewritten": False,
            "candidate": None,
            "candidate_count": 0,
            "message": (
                "Wskaż dataset znaków: katalog z obrazami i etykietami albo plik data.yaml."
            ),
        }

        raw = str(source_raw if source_raw is not None else getattr(self, "split_src_var", tk.StringVar()).get() or "").strip()
        if not raw:
            return result

        try:
            src = Path(raw)
        except Exception:
            result["message"] = "Nie udało się odczytać ścieżki źródłowego datasetu."
            return result

        if src.is_file() and src.name.lower() == "data.yaml":
            src = src.parent
        elif src.is_file() and src.name.lower() == "manifest.json":
            result["message"] = self._char_classification_dataset_message()
            return result

        if self._looks_like_char_classification_dataset(src):
            result["message"] = self._char_classification_dataset_message()
            return result

        if not src.exists() or not src.is_dir():
            result["message"] = "Wskazana ścieżka nie jest katalogiem datasetu znaków."
            return result

        if not self._has_supported_yolo_label_layout(src):
            nested_candidates = self._find_char_yolo_dataset_root_candidates(src)
            if nested_candidates:
                best = dict(nested_candidates[0])
                if not resolve_nested_dataset:
                    result.update(
                        {
                            "src": src,
                            "stats": dict(best.get("stats") or {}),
                            "reason": "nested_yolo_dataset_found",
                            "candidate": best.get("path"),
                            "candidate_count": len(nested_candidates),
                            "message": (
                                "Wskazany katalog nie jest bezpośrednim katalogiem datasetu znaków, "
                                "ale program znalazł poprawny dataset wewnątrz."
                            ),
                        }
                    )
                    return result
                src = Path(best.get("path"))
            else:
                result["message"] = (
                    "Wskaż dataset znaków: katalog musi zawierać obrazy oraz odpowiadające im etykiety."
                )
                return result

        if not self._has_supported_yolo_label_layout(src):
            result["message"] = (
                "Wskaż dataset znaków: katalog musi zawierać obrazy oraz odpowiadające im etykiety."
            )
            return result

        stats = self._count_yolo_image_label_pairs(src)
        if int(stats.get("total", 0) or 0) <= 0:
            result["message"] = (
                "Dataset ma katalogi obrazów i etykiet, ale nie znaleziono zgodnych par plików. "
                "Sprawdź, czy etykiety mają te same nazwy bazowe co obrazy."
            )
            return result

        yaml_created = False
        if not (src / "data.yaml").exists():
            if not create_missing_yaml:
                result.update(
                    {
                        "src": src,
                        "stats": stats,
                        "reason": "missing_yaml",
                        "message": (
                            "Dataset ma poprawne pary obraz + etykieta, ale brakuje pliku data.yaml. "
                            "Ten plik jest wymagany do przygotowania splitu treningowego."
                        ),
                    }
                )
                return result

            yaml_state = self._write_char_yolo_data_yaml_if_missing(src)
            if not bool(yaml_state.get("ok")):
                result["message"] = str(yaml_state.get("message") or "Nie udało się przygotować data.yaml.")
                return result
            yaml_created = bool(yaml_state.get("created"))

        yaml_rewritten = False
        try:
            inferred_target = str(self._infer_dataset_target(str(src)) or "").strip().lower()
        except Exception:
            inferred_target = ""
        if inferred_target in {"plate", "vehicle"}:
            if not overwrite_incompatible_yaml:
                result.update(
                    {
                        "src": src,
                        "stats": stats,
                        "reason": "incompatible_yaml",
                        "message": (
                            "Folder ma poprawne pary obraz + etykieta, ale istniejący data.yaml "
                            f"opisuje tor {self._format_training_target_label(inferred_target)}, a nie znaki."
                        ),
                    }
                )
                return result
            yaml_state = self._write_char_yolo_data_yaml_if_missing(src, overwrite=True)
            if not bool(yaml_state.get("ok")):
                result["message"] = str(yaml_state.get("message") or "Nie udało się zastąpić data.yaml.")
                return result
            yaml_rewritten = True

        result.update(
            {
                "ok": True,
                "src": src,
                "stats": stats,
                "yaml_created": yaml_created,
                "yaml_rewritten": yaml_rewritten,
                "message": (
                    "Dataset znaków jest poprawny. "
                    f"Znaleziono {int(stats.get('total', 0) or 0)} par obraz + etykieta."
                    + (" Dopisano brakujący plik data.yaml." if yaml_created else "")
                    + (" Zastąpiono niezgodny plik data.yaml." if yaml_rewritten else "")
                ),
            }
        )
        return result

    def _show_char_split_source_validation_modal(self):
        info = self._validate_char_yolo_split_source()
        validation_ok = False
        created_yaml_after_confirmation = False
        rewritten_yaml_after_confirmation = False
        nested_dataset_after_confirmation = False

        while str(info.get("reason") or "") in {"nested_yolo_dataset_found", "missing_yaml", "incompatible_yaml"}:
            reason = str(info.get("reason") or "")
            stats = dict(info.get("stats") or {})
            src = info.get("src")
            try:
                display_path = self._format_workspace_relative_path(src)
            except Exception:
                display_path = str(src or "")
            if reason == "nested_yolo_dataset_found":
                candidate = info.get("candidate")
                try:
                    candidate_display = self._format_workspace_relative_path(candidate)
                except Exception:
                    candidate_display = str(candidate or "")
                title = "Znaleziono dataset znaków"
                body = (
                    "Wskazany katalog nie jest bezpośrednim katalogiem datasetu znaków, "
                    "ale program znalazł poprawny dataset wewnątrz.\n\n"
                    f"Wskazany folder: {display_path}\n"
                    f"Proponowany dataset: {candidate_display}\n"
                    f"Liczba znalezionych datasetów w środku: {int(info.get('candidate_count', 0) or 0)}\n"
                    f"Pary obraz + etykieta: {int(stats.get('total', 0) or 0)}\n\n"
                    "Czy podpiąć ten znaleziony dataset jako źródło PZ1?"
                )
                if not messagebox.askyesno(title, body, parent=getattr(self, "frame", None)):
                    messagebox.showinfo(
                        "Nie podpięto datasetu",
                        "Źródło nie zostało zmienione. Wskaż bezpośredni katalog datasetu znaków "
                        "albo wybierz proponowany dataset przy kolejnym wskazaniu.",
                        parent=getattr(self, "frame", None),
                    )
                    try:
                        self._refresh_dataset_split_cta_state()
                    except Exception:
                        pass
                    return False
                try:
                    self.split_src_var.set(str(candidate))
                except Exception:
                    pass
                nested_dataset_after_confirmation = True
                info = self._validate_char_yolo_split_source(candidate)
                continue

            if reason == "missing_yaml":
                title = "Brak pliku data.yaml"
                body = (
                    "Wybrany katalog wygląda na dataset znaków, ale nie ma pliku data.yaml.\n\n"
                    f"Folder: {display_path}\n"
                    f"Pary obraz + etykieta: {int(stats.get('total', 0) or 0)}\n\n"
                    "data.yaml opisuje klasy znaków oraz podział train/val/test.\n\n"
                    "Czy program ma utworzyć brakujący plik data.yaml w tym folderze?"
                )
                decline_title = "Nie utworzono data.yaml"
                decline_body = (
                    "Plik data.yaml nie został utworzony, więc to źródło pozostaje niegotowe dla PZ1/Z4.\n\n"
                    "Możesz wybrać inny dataset albo wrócić do tego folderu i ponownie zaakceptować utworzenie pliku."
                )
            else:
                title = "Niezgodny plik data.yaml"
                body = (
                    "Wybrany katalog ma pary obraz + etykieta, ale istniejący data.yaml nie opisuje toru znaków.\n\n"
                    f"Folder: {display_path}\n"
                    f"Pary obraz + etykieta: {int(stats.get('total', 0) or 0)}\n\n"
                    "To mogło powstać po dawnym fallbacku splitu albo po wskazaniu datasetu z innego toru.\n\n"
                    "Czy program ma zastąpić data.yaml poprawnym opisem datasetu znaków?"
                )
                decline_title = "Nie zastąpiono data.yaml"
                decline_body = (
                    "Plik data.yaml nie został zmieniony, więc to źródło pozostaje niegotowe dla toru znaków.\n\n"
                    "Możesz wybrać inny dataset albo ponownie zaakceptować zastąpienie pliku."
                )
            should_create = messagebox.askyesno(
                title,
                body,
                parent=getattr(self, "frame", None),
            )
            if should_create:
                info = self._validate_char_yolo_split_source(
                    create_missing_yaml=(reason == "missing_yaml"),
                    overwrite_incompatible_yaml=(reason == "incompatible_yaml"),
                )
                created_yaml_after_confirmation = bool(info.get("ok")) and bool(info.get("yaml_created"))
                rewritten_yaml_after_confirmation = bool(info.get("ok")) and bool(info.get("yaml_rewritten"))
                continue
            else:
                messagebox.showinfo(
                    decline_title,
                    decline_body,
                    parent=getattr(self, "frame", None),
                )
                try:
                    self._refresh_dataset_split_cta_state()
                except Exception:
                    pass
                return False

        if bool(info.get("ok")):
            validation_ok = True
            stats = dict(info.get("stats") or {})
            src = info.get("src")
            try:
                display_path = self._format_workspace_relative_path(src)
            except Exception:
                display_path = str(src or "")
            yaml_line = (
                "\nPlik data.yaml: zastąpiony poprawnym opisem znaków."
                if bool(info.get("yaml_rewritten"))
                else
                "\nPlik data.yaml: utworzony po potwierdzeniu."
                if bool(info.get("yaml_created"))
                else "\nPlik data.yaml: obecny."
            )
            title = (
                "Zastąpiono data.yaml"
                if rewritten_yaml_after_confirmation
                else "Utworzono data.yaml"
                if created_yaml_after_confirmation
                else "Podpięto dataset znaków"
                if nested_dataset_after_confirmation
                else "Dataset znaków OK"
            )
            intro = (
                "Zastąpiono niezgodny plik data.yaml i źródło datasetu znaków jest gotowe."
                if rewritten_yaml_after_confirmation
                else
                "Utworzono brakujący plik data.yaml i źródło datasetu znaków jest gotowe."
                if created_yaml_after_confirmation
                else
                "Podpięto znaleziony dataset i źródło datasetu znaków jest gotowe."
                if nested_dataset_after_confirmation
                else "Źródło datasetu znaków jest poprawne."
            )
            messagebox.showinfo(
                title,
                f"{intro}\n\n"
                f"Folder: {display_path}\n"
                f"Pary obraz + etykieta: {int(stats.get('total', 0) or 0)}\n"
                f"train={int(stats.get('train', 0) or 0)}, "
                f"val={int(stats.get('val', 0) or 0)}, "
                f"test={int(stats.get('test', 0) or 0)}, "
                f"flat={int(stats.get('flat', 0) or 0)}"
                f"{yaml_line}\n\n"
                "Możesz teraz utworzyć split treningowy.",
                parent=getattr(self, "frame", None),
            )
        else:
            messagebox.showerror(
                "Dataset znaków niegotowy",
                str(info.get("message") or "Wybrane źródło nie przeszło walidacji."),
                parent=getattr(self, "frame", None),
            )

        try:
            self._refresh_dataset_split_cta_state()
        except Exception:
            pass
        try:
            self.frame.after_idle(self._refresh_dataset_split_cta_state)
        except Exception:
            pass
        return validation_ok

    def _pick_char_split_source_dir(self):
        previous_value = str(getattr(self, "split_src_var", tk.StringVar()).get() or "").strip()
        selected = self._pick_dir(
            self.split_src_var,
            initialdir=self._get_char_dataset_source_picker_dir(),
        )
        if selected:
            if not self._show_char_split_source_validation_modal():
                try:
                    self.split_src_var.set(previous_value)
                except Exception:
                    pass
                try:
                    self._refresh_dataset_split_cta_state()
                except Exception:
                    pass

    def _pick_char_split_source_yaml(self):
        previous_value = str(getattr(self, "split_src_var", tk.StringVar()).get() or "").strip()
        selected = self._pick_file(
            self.split_src_var,
            "*.yaml",
            initialdir=self._get_char_dataset_source_picker_dir(),
        )
        if selected:
            if not self._show_char_split_source_validation_modal():
                try:
                    self.split_src_var.set(previous_value)
                except Exception:
                    pass
                try:
                    self._refresh_dataset_split_cta_state()
                except Exception:
                    pass

    def _get_training_dataset_picker_dir(self) -> str:
        current = self._get_current_picker_parent("dataset_var")
        if current:
            return current
        return self._get_first_picker_dir(
            CONFIG.get_datasets_dir(self._get_selected_training_target()),
        )

    def _get_validation_model_picker_dir(self) -> str:
        current_value = str(getattr(self, "val_model_var", tk.StringVar()).get() or "").strip()
        if current_value:
            current_path = Path(current_value)
            if current_path.is_file():
                current_path = current_path.parent
            if current_path.exists():
                return str(current_path)
        return str(self._get_preferred_models_dir(self._get_selected_training_target()))

    def _get_validation_dataset_picker_dir(self) -> str:
        current_value = str(getattr(self, "val_data_var", tk.StringVar()).get() or "").strip()
        if current_value:
            current_path = Path(current_value)
            if current_path.is_file() and current_path.name.lower() == "data.yaml":
                current_path = current_path.parent
            if current_path.exists():
                return str(current_path)
        return str(CONFIG.get_datasets_dir(self._get_selected_training_target()))

    def _get_ranking_models_default_dir(self) -> Path:
        return self._get_preferred_models_dir("plate")

    def _get_ranking_models_picker_dir(self) -> str:
        current_value = str(getattr(self, "rank_models_dir", tk.StringVar()).get() or "").strip()
        if current_value:
            current_path = Path(current_value)
            if current_path.is_file():
                current_path = current_path.parent
            if current_path.exists():
                return str(current_path)
        return str(self._get_ranking_models_default_dir())

    def _ensure_plate_ranking_engine(self):
        ranking_dir = Path(CONFIG.get_ranking_dir("plate"))
        current_dir = Path(getattr(self.ranking_engine, "ranking_dir", ranking_dir))
        try:
            same_dir = current_dir.resolve() == ranking_dir.resolve()
        except Exception:
            same_dir = current_dir == ranking_dir

        if not same_dir:
            self.ranking_engine = ModelRanking(ranking_dir=ranking_dir)

    def _get_default_ranking_reference_dir(self) -> str:
        candidates: list[Path] = []

        try:
            dataset_yaml = self._resolve_training_dataset_yaml_path()
            if dataset_yaml is not None:
                source_info = self._resolve_plate_training_source_from_dataset(dataset_yaml)
                source_run = str(source_info.get("source_run_path") or "").strip()
                if source_run:
                    candidates.append(Path(source_run))
        except Exception:
            pass

        try:
            stored = CAMPAIGN.get_last_plate_training_source()
            source_run = str((stored or {}).get("source_run_path") or "").strip()
            if source_run:
                candidates.append(Path(source_run))
        except Exception:
            pass

        for candidate in candidates:
            try:
                if candidate.exists():
                    return str(candidate.resolve())
            except Exception:
                continue

        return ""

    def _get_ranking_reference_picker_dir(self) -> str:
        current_value = str(getattr(self, "rank_data_dir", tk.StringVar()).get() or "").strip()
        if current_value:
            try:
                current_path = Path(current_value)
                if current_path.is_file():
                    current_path = current_path.parent
                if current_path.exists():
                    parent_dir = current_path.parent
                    if parent_dir.exists():
                        return str(parent_dir.resolve())
                    return str(current_path.resolve())
            except Exception:
                pass

        try:
            campaign_auto_dir = CAMPAIGN.get_dir("auto_ann")
            if campaign_auto_dir is not None and Path(campaign_auto_dir).exists():
                return str(Path(campaign_auto_dir).resolve())
        except Exception:
            pass

        try:
            default_dir = Path(CONFIG.get_auto_annotations_dir("plate"))
            if default_dir.exists():
                return str(default_dir.resolve())
        except Exception:
            pass

        return ""

    def _prefill_ranking_reference_if_empty(self):
        var = getattr(self, "rank_data_dir", None)
        if var is None:
            return

        current_value = str(var.get() or "").strip()
        if current_value:
            try:
                if Path(current_value).exists():
                    return
            except Exception:
                pass

        default_value = self._get_default_ranking_reference_dir()
        if not default_value:
            return

        try:
            var.set(default_value)
        except Exception:
            pass

    def _resolve_ranking_reference_source(self, raw_value: str | None = None) -> dict:
        selected_raw = str(
            raw_value if raw_value is not None else getattr(self, "rank_data_dir", tk.StringVar()).get()
        ).strip()
        result = {
            "ok": False,
            "selected_path": selected_raw,
            "reference_dir": "",
            "reference_name": "",
            "xml_path": "",
            "images_dir": "",
            "image_paths": [],
            "image_count": 0,
            "message": (
                "Wskaż folder runu Z2/PZ2, w którym po sprawdzeniu tablic zapisano zmiany. "
                "To zwykle katalog z plikiem annotations.xml oraz zgodnymi obrazami."
            ),
        }
        if not selected_raw:
            return result

        try:
            selected_path = Path(selected_raw)
        except Exception:
            result["message"] = "Nie udało się odczytać wskazanego folderu runu."
            return result

        if not selected_path.exists():
            result["message"] = f"Nie znaleziono wskazanego folderu runu: {selected_path}"
            return result

        xml_path: Path | None = None
        reference_dir: Path | None = None

        if selected_path.is_file() and selected_path.name.lower() == "annotations.xml":
            xml_path = selected_path
            reference_dir = selected_path.parent
        elif selected_path.is_dir():
            direct_xml = selected_path / "annotations.xml"
            if direct_xml.exists():
                xml_path = direct_xml
                reference_dir = selected_path
            else:
                try:
                    xml_candidates = sorted(
                        [path for path in selected_path.rglob("annotations.xml") if path.is_file()],
                        key=lambda path: (0 if path.parent == selected_path else 1, len(str(path))),
                    )
                except Exception:
                    xml_candidates = []
                if xml_candidates:
                    xml_path = xml_candidates[0]
                    reference_dir = xml_path.parent

        if xml_path is None or reference_dir is None:
            result["message"] = (
                "W tym folderze nie ma zapisanych zmian tablic. "
                "Wskaż run Z2/PZ2, który został przejrzany i zapisany po poprawkach."
            )
            return result

        manifest = {}
        manifest_path = reference_dir / "run_manifest.json"
        if manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    manifest = payload
            except Exception:
                manifest = {}

        candidate_dirs: list[Path] = []
        seen_dirs: set[str] = set()

        def add_candidate_dir(path_like):
            if not path_like:
                return
            try:
                candidate = Path(path_like)
            except Exception:
                return
            try:
                key = str(candidate.resolve())
            except Exception:
                key = str(candidate)
            if key in seen_dirs:
                return
            seen_dirs.add(key)
            candidate_dirs.append(candidate)

        add_candidate_dir(manifest.get("input_dir"))
        add_candidate_dir(reference_dir / "images")
        add_candidate_dir(reference_dir)
        if selected_path.is_dir():
            add_candidate_dir(selected_path)

        image_paths: list[Path] = []
        resolved_images_dir = ""
        for candidate_dir in candidate_dirs:
            try:
                files = get_image_files(candidate_dir)
            except Exception:
                files = []
            if files:
                image_paths = files
                try:
                    resolved_images_dir = str(candidate_dir.resolve())
                except Exception:
                    resolved_images_dir = str(candidate_dir)
                break

        if not image_paths and selected_path.is_dir():
            try:
                recursive_images = sorted(
                    [
                        path for path in selected_path.rglob("*")
                        if path.is_file() and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
                    ]
                )
            except Exception:
                recursive_images = []
            if recursive_images:
                image_paths = recursive_images
                try:
                    resolved_images_dir = str(selected_path.resolve())
                except Exception:
                    resolved_images_dir = str(selected_path)

        if not image_paths:
            result["message"] = "W wybranym zestawie testowym nie znaleziono obrazów do porównania modeli."
            return result

        try:
            reference_dir_value = str(reference_dir.resolve())
        except Exception:
            reference_dir_value = str(reference_dir)

        result.update(
            {
                "ok": True,
                "reference_dir": reference_dir_value,
                "reference_name": reference_dir.name,
                "xml_path": str(xml_path.resolve()) if xml_path.exists() else str(xml_path),
                "images_dir": resolved_images_dir,
                "image_paths": image_paths,
                "image_count": len(image_paths),
                "message": (
                    f"Gotowy zestaw: {reference_dir.name} | {len(image_paths)} obrazów. "
                    "System użyje zapisanych zmian z annotations.xml jako punktu odniesienia."
                ),
            }
        )
        return result

    def _refresh_ranking_start_state(self):
        button = getattr(self, "btn_run_rank", None)
        cancel_button = getattr(self, "btn_cancel_rank", None)
        if button is None:
            return

        ready = False
        if self._is_ranking_available_for_selected_target() and not getattr(self, "rank_is_running", False):
            models_dir_raw = str(getattr(self, "rank_models_dir", tk.StringVar()).get() or "").strip()
            reference_info = self._resolve_ranking_reference_source()
            try:
                models_dir = Path(models_dir_raw)
                ready = (
                    models_dir.exists()
                    and models_dir.is_dir()
                    and any("pose" in path.name.lower() for path in models_dir.glob("*.pt"))
                    and reference_info["ok"]
                )
            except Exception:
                ready = False

        try:
            button.configure(state=(tk.NORMAL if ready else tk.DISABLED))
        except Exception:
            pass
        if cancel_button is not None:
            try:
                cancel_button.configure(state=(tk.NORMAL if getattr(self, "rank_is_running", False) else tk.DISABLED))
            except Exception:
                pass

    def _is_ranking_tab_active(self) -> bool:
        if not hasattr(self, "right_nb") or not hasattr(self, "ranking_tab"):
            return False
        if not getattr(self, "_step4_ranking_tab_visible", False):
            return False

        try:
            return str(self.right_nb.select()) == str(self.ranking_tab)
        except Exception:
            return False

    def _refresh_ranking_reference_ui(self, *_args):
        if not self._is_ranking_available_for_selected_target():
            return
        if not self._is_ranking_tab_active():
            return

        info = self._resolve_ranking_reference_source()

        hint_label = getattr(self, "rank_reference_hint_lbl", None)
        if hint_label is not None:
            try:
                hint_label.configure(text=info["message"])
            except Exception:
                pass

        self._refresh_ranking_start_state()

        try:
            self._load_ranking()
        except Exception:
            pass

    def _bind_training_route_card(self, widget, mode: str):
        bind_training_route_card(self, widget, mode)

    def _refresh_free_training_route_cards(self):
        refresh_free_training_route_cards(self)

    def _refresh_free_training_route_ui(self):
        refresh_free_training_route_ui(self)

    def _update_step4_notebook_mode(self):
        update_step4_notebook_mode(self)

    def _ensure_training_dataset_quality_rows(self, required_rows: int) -> None:
        grid = getattr(self, "train_dataset_quality_grid", None)
        if grid is None:
            return
        rows = getattr(self, "_train_dataset_quality_row_widgets", None)
        if not isinstance(rows, list):
            self._train_dataset_quality_row_widgets = []
            rows = self._train_dataset_quality_row_widgets

        palette = getattr(self.app, "palette", {})
        while len(rows) < max(0, int(required_rows)):
            row_index = len(rows) + 1
            key_label = tk.Label(
                grid,
                text="",
                font=("Segoe UI", 8, "bold"),
                anchor=tk.W,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=3,
                bg=palette.get("panel", "#252526"),
                fg=palette.get("fg", "#f3f3f3"),
            )
            key_label.grid(row=row_index, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
            value_label = tk.Label(
                grid,
                text="",
                font=("Segoe UI", 8),
                anchor=tk.W,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=3,
                wraplength=260,
                bg=palette.get("panel_alt", palette.get("panel", "#252526")),
                fg=palette.get("muted", "#c7c7c7"),
            )
            value_label.grid(row=row_index, column=1, sticky="nsew", padx=(0, 1), pady=(0, 1))
            self._register_train_left_wrap_target(value_label, container=grid, padding=150, min_wrap=180)
            rows.append({"key": key_label, "value": value_label, "row_index": row_index})

    def _refresh_training_dataset_quality_summary(self) -> None:
        shell = getattr(self, "train_dataset_quality_shell", None)
        title = getattr(self, "train_dataset_quality_title_lbl", None)
        if shell is None:
            return

        summary = self._build_training_dataset_quality_summary()
        visible = bool(summary.get("visible", True))
        try:
            is_visible = bool(str(shell.winfo_manager()))
        except Exception:
            is_visible = False
        if visible and not is_visible:
            try:
                shell.pack(anchor=tk.W, fill=tk.X, pady=(2, 8), after=getattr(self, "train_dataset_hint_lbl", None))
            except Exception:
                try:
                    shell.pack(anchor=tk.W, fill=tk.X, pady=(2, 8))
                except Exception:
                    pass
        elif not visible and is_visible:
            try:
                shell.pack_forget()
            except Exception:
                pass

        rows = list(summary.get("rows", []) or [])
        self._ensure_training_dataset_quality_rows(len(rows))
        row_widgets = list(getattr(self, "_train_dataset_quality_row_widgets", []) or [])
        if title is not None:
            self._set_training_widget_text(title, "Czy dataset ma sens?")

        for row_index, widgets in enumerate(row_widgets):
            row_visible = row_index < len(rows)
            key_label = widgets.get("key")
            value_label = widgets.get("value")
            if row_visible:
                key_text, value_text = rows[row_index]
            else:
                key_text, value_text = "", ""
            for widget in (key_label, value_label):
                if widget is None:
                    continue
                try:
                    if row_visible:
                        widget.grid()
                    else:
                        widget.grid_remove()
                except Exception:
                    pass
            self._set_training_widget_text(key_label, key_text)
            self._set_training_widget_text(value_label, value_text)

        try:
            self._apply_training_dataset_quality_theme(str(summary.get("tone") or "muted"))
        except Exception:
            pass

    def _apply_training_dataset_quality_theme(self, tone: str = "muted") -> None:
        palette = getattr(self.app, "palette", {})
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        shell_bg = palette.get("panel", "#252526")
        title_bg = palette.get("panel_alt", "#2d2d30")
        title_fg = palette.get("fg", "#f3f3f3")
        key_bg = palette.get("panel", "#252526")
        key_fg = palette.get("fg", "#f3f3f3")
        value_bg = palette.get("panel_alt", palette.get("panel", "#252526"))
        value_fg = palette.get("muted", "#c7c7c7")
        success_fg = palette.get("success", "#4ec9b0")
        warning_fg = palette.get("warning", "#d7ba7d")
        danger_fg = palette.get("danger", palette.get("error", "#f48771"))
        tone_fg = {
            "success": success_fg,
            "warning": warning_fg,
            "danger": danger_fg,
        }.get(str(tone or "").strip().lower(), value_fg)

        for attr_name, bg, fg in (
            ("train_dataset_quality_shell", border, title_fg),
            ("train_dataset_quality_grid", border, title_fg),
            ("train_dataset_quality_title_row", title_bg, title_fg),
            ("train_dataset_quality_title_lbl", title_bg, title_fg),
        ):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                if isinstance(widget, tk.Label):
                    widget.configure(bg=bg, fg=fg)
                else:
                    widget.configure(bg=bg, highlightbackground=border, highlightcolor=border)
            except Exception:
                pass

        for row_index, widgets in enumerate(list(getattr(self, "_train_dataset_quality_row_widgets", []) or [])):
            row_bg = value_bg if row_index % 2 else shell_bg
            key_label = widgets.get("key")
            value_label = widgets.get("value")
            if key_label is not None:
                try:
                    key_label.configure(bg=key_bg, fg=key_fg)
                except Exception:
                    pass
            if value_label is not None:
                try:
                    value_label.configure(
                        bg=row_bg,
                        fg=(tone_fg if row_index == 0 else value_fg),
                    )
                except Exception:
                    pass

    def _update_training_dataset_hint(self):
        label = getattr(self, "train_dataset_hint_lbl", None)
        if label is not None:
            try:
                label.configure(text=self._get_training_dataset_hint_text())
            except Exception:
                pass

        scope_label = getattr(self, "train_scope_hint_lbl", None)
        if scope_label is not None:
            try:
                scope_label.configure(text=self._get_training_scope_hint_text())
            except Exception:
                pass

        warning_label = getattr(self, "train_pose_warning_lbl", None)
        if warning_label is not None:
            warning_text = self._get_pose_dataset_size_warning()
            try:
                warning_label.configure(text=warning_text)
            except Exception:
                pass

            try:
                is_visible = bool(str(warning_label.winfo_manager()))
            except Exception:
                is_visible = False

            if warning_text:
                if not is_visible:
                    try:
                        warning_label.pack(anchor=tk.W, fill=tk.X, pady=(0, self._train_left_section_gap))
                    except Exception:
                        pass
            else:
                if is_visible:
                    try:
                        warning_label.pack_forget()
                    except Exception:
                        pass

        try:
            self._refresh_training_dataset_quality_summary()
        except Exception:
            pass

        self._update_training_dataset_hint_wraplength()
        try:
            self._refresh_training_device_hint()
        except Exception:
            pass

    def _register_train_left_wrap_target(
        self,
        widget,
        *,
        container=None,
        padding: int = 20,
        min_wrap: int = 140,
    ):
        if widget is None:
            return

        try:
            self._train_left_wrap_targets.append(
                {
                    "widget": widget,
                    "container": container,
                    "padding": int(padding),
                    "min_wrap": int(min_wrap),
                }
            )
        except Exception:
            return

        for bind_target in (widget, container):
            if bind_target is None:
                continue
            try:
                bind_target.bind("<Configure>", self._update_training_dataset_hint_wraplength, add="+")
            except Exception:
                pass

    def _build_train_left_separator(self, parent, pady=(0, 0)):
        if parent is None:
            return None

        palette = getattr(self.app, "palette", {})
        spacer = tk.Frame(
            parent,
            height=1,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", "#252526"),
        )
        spacer.pack(fill=tk.X, pady=pady)
        spacer.pack_propagate(False)
        return spacer

    def _init_train_pane_layout(self):
        pane = getattr(self, "train_pane", None)
        if pane is None or bool(getattr(self, "_train_pane_layout_initialized", False)):
            return

        try:
            total_width = int(pane.winfo_width() or 0)
        except Exception:
            total_width = 0

        if total_width < 900:
            try:
                self.frame.after(120, self._init_train_pane_layout)
            except Exception:
                pass
            return

        preferred_left = max(560, int(total_width * 0.49))
        preferred_left = min(preferred_left, max(620, total_width - 460))
        preferred_left = max(480, min(preferred_left, total_width - 340))

        try:
            pane.sashpos(0, int(preferred_left))
            self._train_pane_layout_initialized = True
        except Exception:
            pass

    def _create_metric_table(
        self,
        parent,
        columns: list[tuple[str, int, str]],
        *,
        height: int | None = None,
    ) -> ttk.Treeview:
        host = ttk.Frame(parent, style="Panel.TFrame")
        host.pack(fill=tk.BOTH, expand=True)

        tree = ttk.Treeview(
            host,
            columns=tuple(name for name, _width, _anchor in columns),
            show="headings",
            height=height,
        )

        for name, width, anchor in columns:
            tree.heading(name, text=name)
            tree.column(name, width=width, anchor=anchor, stretch=(anchor == tk.W))

        scrollbar = WebSlimScrollbar(host, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        try:
            self._dynamic_metric_tables.append({"tree": tree, "host": host, "scrollbar": scrollbar})
        except Exception:
            pass
        return tree

    def _set_metric_table_rows(self, tree, rows: list[tuple]):
        if tree is None:
            return

        try:
            tree.delete(*tree.get_children())
        except Exception:
            pass

        for row in rows or []:
            try:
                tree.insert("", tk.END, values=tuple(row))
            except Exception:
                continue

    def _update_training_dataset_hint_wraplength(self, event=None):
        label = getattr(self, "train_dataset_hint_lbl", None)
        scope_label = getattr(self, "train_scope_hint_lbl", None)
        warning_label = getattr(self, "train_pose_warning_lbl", None)
        device_label = getattr(self, "train_device_hint_lbl", None)
        extra_targets = getattr(self, "_train_left_wrap_targets", [])
        if label is None and scope_label is None and warning_label is None and device_label is None and not extra_targets:
            return

        base_width = 0
        try:
            inset = max(0, int(getattr(self, "_train_left_content_inset", 0)))
            base_width = int(self.train_left_canvas.winfo_width()) - (2 * inset)
        except Exception:
            base_width = 0

        specs = []
        for widget in (label, scope_label, warning_label, device_label):
            if widget is not None:
                specs.append((widget, None, 2, 120))

        for spec in extra_targets:
            specs.append(
                (
                    spec.get("widget"),
                    spec.get("container"),
                    int(spec.get("padding", 20)),
                    int(spec.get("min_wrap", 140)),
                )
            )

        seen: set[int] = set()
        for widget, container, padding, min_wrap in specs:
            if widget is None:
                continue

            widget_id = id(widget)
            if widget_id in seen:
                continue
            seen.add(widget_id)

            width = 0
            try:
                if container is not None:
                    width = int(container.winfo_width())
            except Exception:
                width = 0

            if width <= 1:
                try:
                    width = int(widget.winfo_width())
                except Exception:
                    width = 0

            if width <= 1:
                width = base_width

            target = max(int(min_wrap), int(width) - int(padding))
            try:
                current = int(float(widget.cget("wraplength")))
            except Exception:
                current = 0

            if abs(current - target) <= 2:
                continue

            try:
                widget.configure(wraplength=target)
            except Exception:
                pass

    def _configure_train_progress_styles(self):
        style = getattr(self.app, "style", None) or ttk.Style()
        palette = getattr(self.app, "palette", {})
        trough = palette.get("surface_info", palette.get("panel_alt", palette.get("panel", "#252526")))
        shell_bg = palette.get("panel", palette.get("bg", "#1f1f1f"))
        border = shell_bg
        dataset_fill = palette.get("success", "#2ecc71")
        split_fill = palette.get("success", "#2ecc71")
        rank_fill = palette.get("accent_hover", dataset_fill)
        epoch_fill = palette.get("guide", palette.get("warning", "#f0b44c"))
        overall_fill = palette.get("success", "#2ecc71")
        success_fg = self._get_training_success_fg()

        try:
            style.configure(
                "TrainSplitSuccess.TLabel",
                background=palette.get("panel", "#252526"),
                foreground=success_fg,
                padding=2,
            )
            style.map(
                "TrainSplitSuccess.TLabel",
                foreground=[("disabled", success_fg), ("active", success_fg)],
                background=[
                    ("disabled", palette.get("panel", "#252526")),
                    ("active", palette.get("panel", "#252526")),
                ],
            )
        except Exception:
            pass

        try:
            style.configure(
                "TrainEpoch.Horizontal.TProgressbar",
                thickness=4,
                background=epoch_fill,
                troughcolor=trough,
                bordercolor=border,
                lightcolor=epoch_fill,
                darkcolor=epoch_fill,
            )
            style.configure(
                "TrainOverall.Horizontal.TProgressbar",
                thickness=4,
                background=overall_fill,
                troughcolor=trough,
                bordercolor=border,
                lightcolor=overall_fill,
                darkcolor=overall_fill,
            )
            style.configure(
                "TrainDataset.Horizontal.TProgressbar",
                thickness=8,
                background=dataset_fill,
                troughcolor=trough,
                bordercolor=border,
                lightcolor=dataset_fill,
                darkcolor=dataset_fill,
            )
            style.configure(
                "TrainSplit.Horizontal.TProgressbar",
                thickness=8,
                background=split_fill,
                troughcolor=trough,
                bordercolor=border,
                lightcolor=split_fill,
                darkcolor=split_fill,
            )
            style.configure(
                "TrainRank.Horizontal.TProgressbar",
                thickness=8,
                background=rank_fill,
                troughcolor=trough,
                bordercolor=border,
                lightcolor=rank_fill,
                darkcolor=rank_fill,
            )
        except Exception:
            pass

        progress_configs = {
            "train_epoch_progress": {
                "bg": shell_bg,
                "trough_color": trough,
                "fill_color": epoch_fill,
                "thickness": 4,
            },
            "train_progress": {
                "bg": shell_bg,
                "trough_color": trough,
                "fill_color": overall_fill,
                "thickness": 4,
            },
            "ds_progress": {
                "bg": palette.get("panel", "#252526"),
                "trough_color": palette.get("panel_alt", palette.get("panel", "#252526")),
                "fill_color": dataset_fill,
                "thickness": 6,
            },
            "split_progress": {
                "bg": palette.get("panel", "#252526"),
                "trough_color": palette.get("panel_alt", palette.get("panel", "#252526")),
                "fill_color": split_fill,
                "thickness": 6,
            },
            "rank_progress": {
                "bg": palette.get("panel", "#252526"),
                "trough_color": palette.get("panel_alt", palette.get("panel", "#252526")),
                "fill_color": rank_fill,
                "thickness": 6,
            },
        }

        style_targets = {
            "train_epoch_progress": "TrainEpoch.Horizontal.TProgressbar",
            "train_progress": "TrainOverall.Horizontal.TProgressbar",
            "ds_progress": "TrainDataset.Horizontal.TProgressbar",
            "split_progress": "TrainSplit.Horizontal.TProgressbar",
            "rank_progress": "TrainRank.Horizontal.TProgressbar",
        }

        for widget_name, config in progress_configs.items():
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            if isinstance(widget, TrainProgressBar):
                try:
                    widget.configure(**config)
                except Exception:
                    pass
                continue
            try:
                widget.configure(style=style_targets.get(widget_name, "Horizontal.TProgressbar"))
            except Exception:
                pass

        shell = getattr(self, "train_progress_shell", None)
        if shell is not None:
            try:
                shell.configure(bg=shell_bg, highlightbackground=shell_bg, highlightcolor=shell_bg)
            except Exception:
                pass

        for widget_name in ("train_epoch_progress_row", "train_overall_progress_row"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(bg=shell_bg, highlightbackground=shell_bg, highlightcolor=shell_bg)
            except Exception:
                pass

        for widget_name in ("train_epoch_progress_measure_lbl", "train_progress_measure_lbl"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(bg=shell_bg, fg=palette.get("muted", "#c7c7c7"))
            except Exception:
                pass

        for widget_name in ("train_epoch_progress_hint_lbl", "train_progress_hint_lbl"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(bg=shell_bg, fg=palette.get("muted_dim", palette.get("muted", "#9a9a9a")))
            except Exception:
                pass

        split_feedback_frame = getattr(self, "split_feedback_frame", None)
        if split_feedback_frame is not None:
            try:
                self.app.style_ttk_frame_widget(split_feedback_frame, background=shell_bg)
            except Exception:
                pass
        for widget_name in (
            "train_lbl",
            "val_lbl",
            "test_lbl",
            "creator_train_lbl",
            "creator_val_lbl",
            "creator_test_lbl",
            "ds_status",
            "split_status",
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.configure(style="TrainSplitSuccess.TLabel")
            except Exception:
                pass
            try:
                widget.configure(foreground=success_fg)
            except Exception:
                pass

    def _get_training_success_fg(self) -> str:
        try:
            palette = getattr(self.app, "palette", {})
            success = str(palette.get("success", "#2ecc71"))
            is_dark = bool(getattr(self.app, "is_dark_theme", lambda: False)())
            return blend_hex_colors(success, "#ffffff", 0.18) if is_dark else success
        except Exception:
            return "#2ecc71"

    def _style_training_success_label(self, widget) -> None:
        if widget is None:
            return
        success_fg = self._get_training_success_fg()
        try:
            widget.configure(style="TrainSplitSuccess.TLabel")
        except Exception:
            pass
        try:
            widget.configure(foreground=success_fg)
        except Exception:
            pass

    def _style_training_error_label(self, widget) -> None:
        if widget is None:
            return
        palette = getattr(self.app, "palette", {})
        error_fg = palette.get("error", palette.get("danger", "#e05d5d"))
        try:
            widget.configure(style="PanelError.TLabel")
        except Exception:
            pass
        try:
            widget.configure(foreground=error_fg)
        except Exception:
            pass

    def _set_train_progress_values(self, *, overall: float | None = None, epoch: float | None = None):
        if overall is not None:
            try:
                self.train_progress_var.set(max(0.0, min(100.0, float(overall))))
            except Exception:
                pass

        if epoch is not None:
            try:
                self.train_epoch_progress_var.set(max(0.0, min(100.0, float(epoch))))
            except Exception:
                pass

    @staticmethod
    def _format_training_eta(seconds: float | None) -> str:
        if seconds is None:
            return "-"
        try:
            total_seconds = max(0, int(round(float(seconds))))
        except Exception:
            return "-"
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        if minutes > 0:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _reset_training_runtime_progress(self) -> None:
        self._training_started_monotonic = None
        self._training_started_wall_clock = None
        self._training_eta_seconds = None
        self._training_last_epoch = 0
        self._training_last_total_epochs = 0
        self._training_last_batch = 0
        self._training_last_total_batches = 0
        try:
            self.train_epoch_progress_measure_lbl.configure(text="Bieżąca epoka")
        except Exception:
            pass
        try:
            self.train_epoch_progress_hint_lbl.configure(
                text="Po starcie zobaczysz numer epoki i liczbę batchy w bieżącej epoce."
            )
        except Exception:
            pass
        try:
            self.train_progress_measure_lbl.configure(text="Cały run")
        except Exception:
            pass
        try:
            self.train_progress_hint_lbl.configure(
                text="Po starcie pojawi się szacowany czas do końca treningu."
            )
        except Exception:
            pass

    def _update_training_progress_meta(
        self,
        *,
        epoch: int | None = None,
        total_epochs: int | None = None,
        batch_idx: int | None = None,
        total_batches: int | None = None,
        overall_pct: float | None = None,
        epoch_pct: float | None = None,
        eta_seconds: float | None = None,
    ) -> None:
        if epoch is not None:
            self._training_last_epoch = max(0, int(epoch))
        if total_epochs is not None:
            self._training_last_total_epochs = max(0, int(total_epochs))
        if batch_idx is not None:
            self._training_last_batch = max(0, int(batch_idx))
        if total_batches is not None:
            self._training_last_total_batches = max(0, int(total_batches))
        if eta_seconds is not None:
            self._training_eta_seconds = max(0.0, float(eta_seconds))

        epoch_value = int(self._training_last_epoch or 0)
        total_epoch_value = int(self._training_last_total_epochs or 0)
        batch_value = int(self._training_last_batch or 0)
        total_batch_value = int(self._training_last_total_batches or 0)

        if total_epoch_value > 0 and total_batch_value > 0:
            epoch_text = f"Epoka {epoch_value}/{total_epoch_value} | batch {batch_value}/{total_batch_value}"
        elif total_epoch_value > 0:
            epoch_text = f"Epoka {epoch_value}/{total_epoch_value}"
        else:
            epoch_text = "Bieżąca epoka"
        try:
            self.train_epoch_progress_measure_lbl.configure(text=epoch_text)
        except Exception:
            pass

        if total_batch_value > 0:
            safe_epoch_pct = max(0.0, min(100.0, float(epoch_pct or 0.0)))
            epoch_hint = f"Bieżąca epoka: {safe_epoch_pct:.1f}% | batch {batch_value}/{total_batch_value}"
        else:
            epoch_hint = "Przygotowanie batchy dla bieżącej epoki..."
        try:
            self.train_epoch_progress_hint_lbl.configure(text=epoch_hint)
        except Exception:
            pass

        if total_epoch_value > 0:
            overall_text = f"Cały run {max(0.0, min(100.0, float(overall_pct or 0.0))):.1f}%"
        else:
            overall_text = "Cały run"
        try:
            self.train_progress_measure_lbl.configure(text=overall_text)
        except Exception:
            pass

        eta_text = self._format_training_eta(self._training_eta_seconds)
        started_text = (
            self._training_started_wall_clock.strftime("%H:%M:%S")
            if isinstance(self._training_started_wall_clock, datetime.datetime)
            else "--:--:--"
        )
        try:
            self.train_progress_hint_lbl.configure(text=f"Start: {started_text} | ETA: {eta_text}")
        except Exception:
            pass

    def _is_memory_failure_text(self, message: str | None) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        needles = (
            "out of memory",
            "outofmemory",
            "memory allocation failure",
            "unable to allocate",
            "defaultcpuallocator: not enough memory",
            "not enough memory",
            "taskalignedassigner",
            "cuda error: unknown error",
        )
        return any(needle in normalized for needle in needles)

    def _is_cuda_runtime_broken_text(self, message: str | None) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        needles = (
            "cuda error: unknown error",
            "unable to find an engine to execute this computation",
            "get was unable to find an engine to execute this computation",
            "utracił sprawny stan cuda",
        )
        return any(needle in normalized for needle in needles)

    def _get_training_gpu_memory_snapshot(self, device_value: str | None = None) -> dict:
        snapshot = {
            "available": False,
            "device_name": "",
            "free_mib": 0.0,
            "used_mib": 0.0,
            "total_mib": 0.0,
            "source": "",
            "error": "",
        }

        effective_raw, profile = self._get_effective_training_device_profile(device_value)
        if effective_raw == "cpu" or profile is None:
            snapshot["error"] = "Trening nie używa GPU CUDA."
            return snapshot

        device_name = str(profile.get("name", effective_raw) or effective_raw)
        snapshot["device_name"] = device_name

        try:
            device_index = int(profile.get("index", 0) or 0)
        except Exception:
            device_index = 0

        torch = get_torch_module()
        if is_cuda_available() and torch is not None:
            try:
                if torch.cuda.is_available():
                    free_bytes, total_bytes = torch.cuda.mem_get_info(device_index)
                    free_mib = float(free_bytes) / (1024.0 ** 2)
                    total_mib = float(total_bytes) / (1024.0 ** 2)
                    used_mib = max(0.0, total_mib - free_mib)
                    snapshot.update(
                        available=True,
                        free_mib=free_mib,
                        used_mib=used_mib,
                        total_mib=total_mib,
                        source="torch.cuda.mem_get_info",
                    )
                    return snapshot
            except Exception as e:
                snapshot["error"] = str(e)

        try:
            completed = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            output = str(completed.stdout or "").strip()
            if completed.returncode == 0 and output:
                rows = [row.strip() for row in output.splitlines() if row.strip()]
                if rows:
                    chosen_row = rows[min(device_index, len(rows) - 1)]
                    parts = [part.strip() for part in chosen_row.split(",")]
                    if len(parts) >= 4:
                        snapshot.update(
                            available=True,
                            device_name=str(parts[0] or device_name),
                            total_mib=float(parts[1] or 0.0),
                            used_mib=float(parts[2] or 0.0),
                            free_mib=float(parts[3] or 0.0),
                            source="nvidia-smi",
                            error="",
                        )
                        return snapshot
            if not snapshot["error"]:
                snapshot["error"] = str(completed.stderr or "Nie udało się odczytać danych z nvidia-smi.").strip()
        except Exception as e:
            if not snapshot["error"]:
                snapshot["error"] = str(e)

        return snapshot

    def _build_training_gpu_memory_lines(self, device_value: str | None = None) -> list[str]:
        snapshot = self._get_training_gpu_memory_snapshot(device_value)
        if not snapshot.get("available"):
            if snapshot.get("error"):
                return [f"Stan GPU: {snapshot['error']}"]
            return []

        device_name = str(snapshot.get("device_name", "") or "GPU CUDA")
        free_mib = float(snapshot.get("free_mib", 0.0) or 0.0)
        used_mib = float(snapshot.get("used_mib", 0.0) or 0.0)
        total_mib = float(snapshot.get("total_mib", 0.0) or 0.0)
        source = str(snapshot.get("source", "") or "").strip()

        line = (
            f"{device_name}: wolne {free_mib:.0f} MiB / {total_mib:.0f} MiB, "
            f"zajęte {used_mib:.0f} MiB."
        )
        if source:
            line += f" (źródło: {source})"
        return [line]

    def _build_training_failure_message(self, run) -> str:
        if run is None:
            return (
                "Trening zakończył się błędem.\n\n"
                "Sprawdź terminal procesu i spróbuj ponownie na lżejszych ustawieniach."
            )

        error_text = self._sanitize_training_text(getattr(run, "error_message", "") or "")
        lines = [
            "Co się stało:",
            "Trening nie został ukończony i run ma status FAILED.",
            "",
            "Dlaczego:",
        ]

        if self._is_memory_failure_text(error_text):
            lines.append(
                "Podczas treningu zabrakło pamięci GPU albo pamięci roboczej alokowanej przez PyTorch."
            )
            lines.extend(
                [
                    "",
                    "Co możesz zrobić:",
                    "1. Ustaw batch = 1.",
                    "2. Zmniejsz rozdzielczość wejściową do 384 albo nawet 256 dla YOLO Pose tablic na 4 GB VRAM.",
                    "3. Jeśli to nadal za dużo, użyj lżejszego modelu bazowego n/s zamiast m/l/x.",
                    "4. Zamknij inne procesy używające GPU i spróbuj ponownie.",
                ]
            )
            if "defaultcpuallocator" in error_text.lower() or "alloc_cpu" in error_text.lower():
                lines.extend(
                    [
                        "5. Ten konkretny błąd pochodzi z alokatora CPU PyTorch i bywa skutkiem ubocznym wcześniejszych OOM na GPU albo wyczerpanej pamięci wirtualnej systemu.",
                        "6. Po takim błędzie najlepiej zamknąć i uruchomić ponownie aplikację przed kolejną próbą treningu.",
                    ]
                )
            if self._is_cuda_runtime_broken_text(error_text):
                lines.extend(
                    [
                        "7. Zamknij i uruchom ponownie aplikację przed kolejną próbą na GPU.",
                    ]
                )
        else:
            lines.append(
                "Run zakończył się wyjątkiem po stronie Ultralytics, CUDA albo konfiguracji treningu."
            )
            lines.extend(
                [
                    "",
                    "Co możesz zrobić:",
                    "1. Sprawdź terminal procesu i ostatni traceback.",
                    "2. Spróbuj ponownie na mniejszym batchu lub niższym imgsz.",
                    "3. Jeśli wznawiasz z checkpointu, upewnij się, że dataset i model nadal istnieją.",
                ]
            )
            if self._is_cuda_runtime_broken_text(error_text):
                lines.append("4. Zamknij i uruchom ponownie aplikację przed następną próbą GPU.")

        lines.extend(
            [
                "",
                f"Run: {getattr(run, 'name', '-')}",
                f"Model bazowy: {getattr(run, 'base_model', '-')}",
                f"Dataset: {getattr(run, 'dataset_path', '-')}",
                f"Parametry: batch={int(getattr(run, 'batch_size', 0) or 0)}, imgsz={int(getattr(run, 'img_size', 0) or 0)}, lr0={float(getattr(run, 'lr0', 0.0) or 0.0):.4f}",
            ]
        )
        gpu_lines = self._build_training_gpu_memory_lines(getattr(run, "device", None))
        if gpu_lines:
            lines.extend(["", "Stan GPU przy awarii:"])
            lines.extend(gpu_lines)
        if error_text:
            lines.extend(["", "Szczegóły błędu:", error_text.strip()])
        return "\n".join(lines).strip()

    #=====================================
    def set_campaign_context(self, runs_dir=None, datasets_dir=None):
        set_campaign_context(self, runs_dir=runs_dir, datasets_dir=datasets_dir)

    def get_campaign_step4_readiness(self, *, iteration_target: str | None = None) -> dict:
        target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
        if target not in {"plate", "char"}:
            target = "char"

        result = {
            "ok": True,
            "reason": "",
            "message": "",
            "iteration_target": target,
            "ready_dataset": "",
            "dataset_hint": "",
            "annotated_images": 0,
            "required_images": 0,
            "required_plates": int(getattr(CONFIG, "CAMPAIGN_MIN_PLATE_ANNOTATIONS", 10) or 10),
            "source_run": "",
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "validation_message": "",
            "project_approved_images": 0,
            "project_approved_plates": 0,
            "project_manual_images": 0,
            "project_auto_accepted_images": 0,
        }

        if not CAMPAIGN.get_active_project_name():
            result.update(
                ok=False,
                reason="campaign_inactive",
                message="Brak aktywnego projektu kampanii.",
            )
            return result

        datasets_dir = CAMPAIGN.get_dir("datasets")
        if datasets_dir is None:
            logger.error("Brak katalogu datasets dla aktywnego projektu.")
            result.update(
                ok=False,
                reason="missing_datasets_dir",
                message="Projekt nie ma jeszcze poprawnie przygotowanego katalogu datasetow.",
            )
            return result

        if target == "char":
            ready_dataset = None
            invalid_ready_result = None
            try:
                ready_candidates = self._find_ready_dataset_candidates(Path(datasets_dir))
                preferred = [rec for rec in ready_candidates if rec[1] == target]
                if preferred:
                    ready_dataset, _ready_target, _stamp = max(preferred, key=lambda rec: rec[2])
            except Exception:
                ready_dataset = None

            if ready_dataset is not None:
                ready_dataset_str = str(ready_dataset)
                result["ready_dataset"] = ready_dataset_str
                result["dataset_hint"] = ready_dataset_str
                validation_stats = {}
                try:
                    is_valid_dataset, validation_msg, validation_stats = self.trainer.validate_dataset(Path(ready_dataset))
                except Exception as e:
                    is_valid_dataset = False
                    validation_msg = f"Błąd walidacji datasetu: {e}"
                    validation_stats = {}

                validation_stats = dict(validation_stats or {})
                result["train_images"] = int(validation_stats.get("train_images", 0) or 0)
                result["val_images"] = int(validation_stats.get("val_images", 0) or 0)
                result["test_images"] = int(validation_stats.get("test_images", 0) or 0)
                result["validation_message"] = str(validation_msg or "").strip()

                if not is_valid_dataset:
                    invalid_ready_result = {
                        "ok": False,
                        "reason": "invalid_char_dataset",
                        "message": (
                            "E4 w torze znaków nie ma jeszcze gotowego wariantu treningowego train/val.\n\n"
                            f"{self._build_training_dataset_validation_message(Path(ready_dataset), validation_msg, validation_stats)}\n\n"
                            "Jeżeli to jest źródłowy dataset z PZ3, przejdź do Z4/PZ1 i utwórz wariant datasetu ze splitem."
                        ),
                    }
                else:
                    return result

            latest_source = None
            latest_source_info = {}
            try:
                source_candidates = []
                for path in self._find_dataset_source_candidates(Path(datasets_dir)):
                    try:
                        inferred = self._infer_dataset_target(str(path))
                    except Exception:
                        inferred = "char"
                    if inferred != "char":
                        continue
                    info = self._validate_char_yolo_split_source(
                        path,
                        create_missing_yaml=False,
                        overwrite_incompatible_yaml=False,
                        resolve_nested_dataset=True,
                    )
                    if not bool(info.get("ok")):
                        continue
                    src = info.get("src") or path
                    try:
                        stamp = float(Path(src).stat().st_mtime)
                    except Exception:
                        stamp = float(Path(path).stat().st_mtime)
                    source_candidates.append((Path(src), dict(info), stamp))
                if source_candidates:
                    latest_source, latest_source_info, _stamp = max(source_candidates, key=lambda rec: rec[2])
            except Exception:
                latest_source = None
                latest_source_info = {}

            if latest_source is not None:
                source_stats = dict(latest_source_info.get("stats") or {})
                dataset_hint = str(latest_source)
                result.update(
                    ok=True,
                    reason="source_dataset_ready_for_split",
                    ready_dataset="",
                    dataset_hint=dataset_hint,
                    source_dataset=dataset_hint,
                    train_images=0,
                    val_images=0,
                    test_images=0,
                    source_image_label_pairs=int(source_stats.get("total", 0) or 0),
                    validation_message=(
                        "Źródłowy dataset YOLO Detect znaków jest gotowy. "
                        "W Z4/PZ1 utwórz wariant treningowy train/val/test."
                    ),
                )
                return result

            if invalid_ready_result is not None:
                result.update(invalid_ready_result)
                return result

        if target != "plate":
            dataset_hint = self._format_workspace_relative_path(Path(datasets_dir))
            result.update(
                ok=False,
                reason="missing_char_dataset",
                dataset_hint=dataset_hint,
                message=(
                    "E4 w torze znaków pozostaje zablokowane, bo Z3 nie przygotowalo jeszcze poprawnego datasetu treningowego.\n\n"
                    f"Katalog datasetow projektu: {dataset_hint}\n\n"
                    "Wróć do Z3, wyeksportuj albo podziel dataset znaków i upewnij się, ze zawiera niepuste obrazy w train i val."
                ),
            )
            return result

        try:
            approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats() or {})
        except Exception:
            approved_stats = {}

        approved_images = int(approved_stats.get("images", 0) or 0)
        approved_plates = int(approved_stats.get("plates", 0) or 0)
        result["project_approved_images"] = approved_images
        result["project_approved_plates"] = approved_plates
        result["project_manual_images"] = int(approved_stats.get("manual_images", 0) or 0)
        result["project_auto_accepted_images"] = int(approved_stats.get("auto_accepted_images", 0) or 0)
        result["annotated_images"] = approved_images
        result["source_run"] = "ApprovedSet projektu"

        if approved_images <= 0:
            result.update(
                ok=False,
                reason="missing_plate_annotations",
                message=(
                    "E4 w torze tablic pozostaje zablokowane, bo zbiór zatwierdzonych tablic projektu "
                    "jest jeszcze pusty.\n\n"
                    "Najpierw przygotuj i zatwierdź ręcznie pierwszy zestaw zdjęć w Z2. "
                    "Dopiero wtedy projekt będzie miał własne źródło do budowy datasetu YOLO Pose."
                ),
            )
            return result

        min_plate_approval_plates = int(getattr(CONFIG, "CAMPAIGN_MIN_PLATE_ANNOTATIONS", 10) or 10)
        if approved_plates < min_plate_approval_plates:
            manual_images = int(result.get("project_manual_images", 0) or 0)
            auto_images = int(result.get("project_auto_accepted_images", 0) or 0)
            missing_plates = max(0, int(min_plate_approval_plates) - int(approved_plates or 0))
            result.update(
                ok=False,
                reason="insufficient_plate_annotations",
                message=(
                    f"E4 w torze tablic wymaga co najmniej {min_plate_approval_plates} zatwierdzonych tablic.\n\n"
                    f"Zatwierdzony zbiór projektu ma teraz {approved_images} obraz(y) i {approved_plates} tablic(e).\n"
                    f"Brakuje jeszcze: {missing_plates} tablic.\n"
                    f"W tym: ręczne {manual_images}, zaakceptowane po autoanotacji {auto_images}.\n"
                    "Wróć do Z2, dodaj brakujące oznaczenia albo zaakceptuj kolejne obrazy i dopiero wtedy przejdź dalej."
                ),
            )
            return result

        plate_dataset_info = self._resolve_campaign_plate_ready_dataset(Path(datasets_dir))
        ready_dataset = plate_dataset_info.get("path")
        ready_counts = dict(plate_dataset_info.get("counts") or {})
        if ready_dataset is not None and not bool(plate_dataset_info.get("stale")):
            result["ready_dataset"] = str(ready_dataset)
            result["dataset_hint"] = str(ready_dataset)
            result["train_images"] = int(ready_counts.get("train", 0) or 0)
            result["val_images"] = int(ready_counts.get("val", 0) or 0)
            result["test_images"] = int(ready_counts.get("test", 0) or 0)
            return result

        if ready_dataset is not None and bool(plate_dataset_info.get("stale")):
            stale_total = int(ready_counts.get("total", 0) or 0)
            result.update(
                ok=False,
                reason="stale_plate_dataset",
                message=(
                    "Z4 w torze tablic widzi nowszy ApprovedSet projektu niż ostatnio przygotowany dataset treningowy.\n\n"
                    f"Aktualny ApprovedSet: {approved_images} obraz(y), {approved_plates} tablic(e).\n"
                    f"Ostatni gotowy dataset: {stale_total} obraz(y).\n\n"
                    "Wróć do PZ1 i przebuduj dataset tablic, aby trening korzystał z aktualnego zbioru projektu."
                ),
            )
            return result

        return result

    def open_campaign_step4_entry(
        self,
        *,
        iteration_target: str | None = None,
        preferred_subtab: str | None = None,
    ) -> dict:
        return open_campaign_step4_entry(
            self,
            iteration_target=iteration_target,
            preferred_subtab=preferred_subtab,
        )



    #=====================================
    def _restore_step4_campaign_project_state(self):
        restore_step4_campaign_project_state(self)

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
        dataset_dir = Path(dataset_dir)
        payload = {
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "project": str(CAMPAIGN.get_active_project_name() or "").strip(),
            "iteration": int(CAMPAIGN.get_current_iteration_num() or 0) if CAMPAIGN.get_active_project_name() else 0,
            "dataset_dir": str(dataset_dir.resolve()),
            "source_kind": str(source_kind or "").strip(),
            "source_run_dir": "",
            "source_run_name": "",
            "source_xml_path": "",
            "source_images_dir": "",
        }

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

        self._plate_dataset_source_manifest_path(dataset_dir).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _resolve_plate_training_source_from_dataset(self, dataset_path: Path | None) -> dict:
        result = {
            "dataset_path": "",
            "source_run_path": "",
            "source_xml_path": "",
        }
        if dataset_path is None:
            return result

        try:
            dataset_path = Path(dataset_path)
        except Exception:
            return result

        try:
            if not dataset_path.exists():
                return result
        except Exception:
            return result

        result["dataset_path"] = str(dataset_path.resolve()) if dataset_path.exists() else str(dataset_path)

        if dataset_path.is_file():
            dataset_path = dataset_path.parent

        manifest = self._load_plate_dataset_source_manifest(dataset_path)
        source_run_path = str(manifest.get("source_run_dir") or "").strip()
        source_xml_path = str(manifest.get("source_xml_path") or "").strip()

        if source_run_path and Path(source_run_path).exists():
            result["source_run_path"] = str(Path(source_run_path).resolve())
        if source_xml_path and Path(source_xml_path).exists():
            result["source_xml_path"] = str(Path(source_xml_path).resolve())

        if result["source_run_path"] or result["source_xml_path"]:
            return result

        run_name = str(manifest.get("source_run_name") or "").strip()
        if not run_name:
            match = re.match(r"^Plates_Z2_(.+)_\d{8}_\d{6}$", dataset_path.name)
            if match:
                run_name = str(match.group(1) or "").strip()

        if not run_name:
            return result

        auto_dir = CAMPAIGN.get_dir("auto_ann")
        if auto_dir is None:
            return result

        candidates = []
        try:
            for candidate in Path(auto_dir).rglob(run_name):
                if (
                    candidate.is_dir()
                    and candidate.name == run_name
                    and (candidate / "annotations.xml").exists()
                ):
                    candidates.append(candidate)
        except Exception:
            candidates = []

        if not candidates:
            return result

        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        best = candidates[0]
        result["source_run_path"] = str(best.resolve())
        result["source_xml_path"] = str((best / "annotations.xml").resolve())
        return result

    def _remember_campaign_plate_training_source(self, dataset_path: Path | None) -> None:
        if not CAMPAIGN.get_active_project_name():
            return
        if str(self.get_campaign_training_target() or "").strip().lower() != "plate":
            return

        source_info = self._resolve_plate_training_source_from_dataset(dataset_path)
        CAMPAIGN.set_last_plate_training_source(
            dataset_path=source_info.get("dataset_path", ""),
            source_run_path=source_info.get("source_run_path", ""),
            source_xml_path=source_info.get("source_xml_path", ""),
        )

    def _remember_campaign_training_run_in_registry(
        self,
        *,
        run_id: str | None = None,
        status: str | None = None,
        target: str | None = None,
    ) -> None:
        if not CAMPAIGN.get_active_project_name():
            return

        normalized_target = str(target or self.get_campaign_training_target() or "").strip().lower()
        if normalized_target not in ("char", "plate"):
            normalized_target = "char"

        resolved_run_id = str(run_id or self.current_run_id or "").strip()
        run = None
        if resolved_run_id:
            try:
                run = self.history.get_run(resolved_run_id)
            except Exception:
                run = None

        status_value = str(
            status
            or (getattr(run, "status", "") if run is not None else "")
            or ""
        ).strip().lower()

        payload = {
            "run_id": resolved_run_id,
            "target": normalized_target,
            "status": status_value,
            "dataset_path": str(getattr(run, "dataset_path", "") or "").strip() if run is not None else "",
            "output_dir": str(getattr(run, "output_dir", "") or "").strip() if run is not None else "",
            "best_weights": str(getattr(run, "best_weights", "") or "").strip() if run is not None else "",
            "last_weights": str(getattr(run, "last_weights", "") or "").strip() if run is not None else "",
            "current_epoch": int(getattr(run, "current_epoch", 0) or 0) if run is not None else 0,
            "epochs": int(getattr(run, "epochs", 0) or 0) if run is not None else 0,
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

        try:
            CAMPAIGN.upsert_iteration_state(
                iteration_num=CAMPAIGN.get_current_iteration_num(),
                updates={"step4_training": payload},
            )
        except Exception as e:
            logger.debug(f"Nie udało się zapisać runu treningowego do iteracyjnego rejestru: {e}")
        try:
            CAMPAIGN.upsert_iteration_artifact_bundle(
                iteration_num=CAMPAIGN.get_current_iteration_num(),
                updates={"step4_training": payload},
            )
        except Exception:
            pass

    def clear_campaign_context(self):
        clear_campaign_context(self)

    def _reset_step4_transient_ui(
        self,
        datasets_dir: Path | None = None,
        target: str | None = None,
        clear_builder_inputs: bool = False,
        require_route_selection: bool | None = None,
    ):
        if target is not None:
            target = str(target).strip().lower()
            if target not in ("char", "plate"):
                target = "char"
            self._campaign_training_target = target
            self._step4_dataset_mode = target

        if require_route_selection is None:
            require_route_selection = bool(CAMPAIGN.get_active_project_name())

        self._step4_route_selected = not bool(require_route_selection)
        self._step4_train_unlocked = False

        split_out_default = (
            str(datasets_dir / "[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]")
            if datasets_dir is not None
            else str(self._get_datasets_base_dir() / "[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]")
        )
        ds_out_default = (
            str(datasets_dir / "Plates_CVAT_[DATA_I_CZAS]")
            if datasets_dir is not None
            else str(self._get_datasets_base_dir() / "Plates_CVAT_[DATA_I_CZAS]")
        )

        try:
            self.split_src_var.set("")
        except Exception:
            pass

        try:
            self.split_out_var.set(split_out_default)
        except Exception:
            pass

        try:
            self.dataset_var.set("")
        except Exception:
            pass

        try:
            self.ds_out_var.set(ds_out_default)
        except Exception:
            pass

        if clear_builder_inputs:
            try:
                self.cvat_xml_var.set("")
            except Exception:
                pass

            try:
                self.cvat_images_var.set("")
            except Exception:
                pass

        self.current_run_id = None
        self._plots_paths = []
        self._plot_original_path = None
        self._plot_photo = None
        self._plot_img_id = None
        try:
            self._close_analysis_dialog()
        except Exception:
            pass
        self._pending_campaign_model_type = None
        self._step4_builder_log_visible = False
        self._step4_train_log_visible = False
        self._current_training_dataset_is_pose = None
        self._step4_campaign_finish_ready = False

        try:
            self.plots_list.delete(0, tk.END)
        except Exception:
            pass

        try:
            if hasattr(self, "plot_canvas"):
                self.plot_canvas.original_image = None
                self.plot_canvas.photo_image = None
                self.plot_canvas.image_id = None
                self.plot_canvas.delete("all")
        except Exception:
            pass

        try:
            self.tree.selection_remove(*self.tree.selection())
        except Exception:
            pass

        try:
            self._set_train_progress_values(overall=0.0, epoch=0.0)
        except Exception:
            pass

        try:
            self._set_step4_process_console_text(
                "Oczekuję na rozpoczęcie treningu lub walidacji...\n"
                "Terminal procesu jest gotowy na dane z Ultralytics.\n"
            )
        except Exception:
            pass

        try:
            self.ds_progress_var.set(0.0)
        except Exception:
            pass

        try:
            self._style_training_success_label(self.ds_status)
            self.ds_status.configure(text="Gotowy")
        except Exception:
            pass

        try:
            self.split_progress_var.set(0.0)
        except Exception:
            pass

        try:
            self._style_training_success_label(self.split_status)
            self.split_status.configure(text="Gotowy")
        except Exception:
            pass

        try:
            self._set_split_feedback_visibility(False)
        except Exception:
            pass

        try:
            self.step4_builder_log_text.configure(state=tk.NORMAL)
            self.step4_builder_log_text.delete(1.0, tk.END)
            self.step4_builder_log_text.configure(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.val_model_var.set("")
        except Exception:
            pass

        try:
            self.val_data_var.set("")
        except Exception:
            pass

        try:
            self.val_split_var.set("val")
        except Exception:
            pass

        try:
            self.val_status.configure(text="Gotowy", foreground="gray")
        except Exception:
            pass

        try:
            self.rank_progress_var.set(0.0)
        except Exception:
            pass

        try:
            self.rank_status.configure(text="Gotowy", foreground="gray")
        except Exception:
            pass

        try:
            self.rank_models_dir.set(str(self._get_ranking_models_default_dir()))
        except Exception:
            pass

        try:
            self.rank_data_dir.set("")
        except Exception:
            pass

        if self._training_completion_poll_job is not None:
            try:
                self.frame.after_cancel(self._training_completion_poll_job)
            except Exception:
                pass
            self._training_completion_poll_job = None

        try:
            self._load_history()
        except Exception:
            pass

        try:
            self._set_training_ui_idle_state()
        except Exception:
            pass

        try:
            self._set_step4_builder_log_visibility(False)
        except Exception:
            pass

        try:
            self._set_step4_train_log_visibility(False)
        except Exception:
            pass

        try:
            target_tab = self.tab_dataset if CAMPAIGN.get_active_project_name() else self.tab_train
            self.main_nb.select(target_tab)
        except Exception:
            pass

        try:
            self.right_nb.select(self.hist_tab)
        except Exception:
            pass

        try:
            self._sync_step4_analysis_nav_buttons()
        except Exception:
            pass

        try:
            self._refresh_step4_dataset_mode_ui()
        except Exception:
            pass

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        try:
            self._update_training_dataset_hint()
        except Exception:
            pass

        try:
            if require_route_selection:
                self._guide_step4_route_selection()
            else:
                self._clear_step4_guidance()
        except Exception:
            pass

    def set_campaign_training_target(self, target: str):
        set_campaign_training_target(self, target)

    def get_campaign_training_target(self) -> str:
        return get_campaign_training_target(self)
    
    def _append_step4_builder_log(self, message: str):
        if not hasattr(self, "step4_builder_log_text"):
            return

        try:
            self.step4_builder_log_text.configure(state=tk.NORMAL)
            self.step4_builder_log_text.insert(tk.END, message.rstrip() + "\n")
            self.step4_builder_log_text.see(tk.END)
            self.step4_builder_log_text.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _set_step4_builder_log_visibility(self, visible: bool):
        if not hasattr(self, "step4_builder_log_frame"):
            return

        self._step4_builder_log_visible = bool(visible)
        try:
            self.step4_builder_log_frame.pack_forget()
        except Exception:
            pass
        try:
            if hasattr(self, "step4_builder_tools"):
                self.step4_builder_tools.pack_forget()
        except Exception:
            pass

        if self._step4_builder_log_visible:
            try:
                if hasattr(self.app, "show_global_terminal"):
                    self.app.show_global_terminal()
            except Exception:
                pass
        return

    def _toggle_step4_builder_log(self):
        try:
            if hasattr(self.app, "toggle_global_terminal"):
                self.app.toggle_global_terminal()
                return
        except Exception:
            pass
        self._set_step4_builder_log_visibility(
            not getattr(self, "_step4_builder_log_visible", False)
        )

    def _set_split_feedback_visibility(self, visible: bool):
        if not hasattr(self, "split_feedback_frame"):
            return

        if visible:
            try:
                self.split_feedback_frame.pack_forget()
            except Exception:
                pass
            self.split_feedback_frame.pack(
                fill=tk.X,
                pady=(0, 8),
                after=self.btn_step4_split_frame
            )
            try:
                self._configure_train_progress_styles()
            except Exception:
                pass
        else:
            self.split_feedback_frame.pack_forget()

    def _set_step4_process_console_text(self, message: str):
        if not hasattr(self, "train_log_console"):
            return

        try:
            self.train_log_console.config(state=tk.NORMAL)
            self.train_log_console.delete(1.0, tk.END)
            if message:
                self.train_log_console.insert(tk.END, message)
            self.train_log_console.config(state=tk.DISABLED)
        except Exception:
            pass

    def _sync_train_left_scrollregion(self, event=None):
        canvas = getattr(self, "train_left_canvas", None)
        if canvas is None:
            return

        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _sync_dataset_mode_scrollregion(self, event=None):
        canvas = getattr(self, "ds_mode_canvas", None)
        if canvas is None:
            return

        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _sync_train_left_canvas_width(self, event=None):
        canvas = getattr(self, "train_left_canvas", None)
        if canvas is None:
            return

        try:
            inset = max(0, int(getattr(self, "_train_left_content_inset", 0)))
            available_width = max(50, int(canvas.winfo_width()) - (2 * inset))
            max_width = max(50, int(getattr(self, "_train_left_content_max_width", available_width)))
            width = min(available_width, max_width)
            canvas.coords(self.train_left_content_window, inset, 0)
            canvas.itemconfigure(self.train_left_content_window, width=width)
        except Exception:
            pass

        try:
            self._update_training_dataset_hint_wraplength()
        except Exception:
            pass

        try:
            content = getattr(self, "train_left_content", None)
            if content is not None:
                content.update_idletasks()
        except Exception:
            pass

        try:
            self._sync_train_left_scrollregion()
        except Exception:
            pass

    def _sync_dataset_mode_canvas_width(self, event=None):
        canvas = getattr(self, "ds_mode_canvas", None)
        if canvas is None:
            return

        try:
            width = max(50, int(canvas.winfo_width()) - 2)
            canvas.itemconfigure(self.ds_mode_host_window, width=width)
        except Exception:
            pass

        try:
            content = getattr(self, "ds_mode_host", None)
            if content is not None:
                content.update_idletasks()
        except Exception:
            pass

        try:
            self._sync_dataset_mode_scrollregion()
        except Exception:
            pass

    def ensure_visible_layout_ready(self, *, force: bool = False) -> bool:
        canvas = getattr(self, "train_left_canvas", None)
        if canvas is None:
            return False

        try:
            if not force and not bool(self.frame.winfo_ismapped()):
                return False
        except Exception:
            if not force:
                return False

        def _run_sync():
            self._training_visible_layout_after_id = None

            try:
                self.frame.update_idletasks()
            except Exception:
                pass

            try:
                self._sync_train_left_canvas_width()
            except Exception:
                pass

            try:
                self._sync_train_left_scrollregion()
            except Exception:
                pass

            try:
                self._init_train_pane_layout()
            except Exception:
                pass

            try:
                self._refresh_step4_analysis_tab_visibility()
            except Exception:
                pass

            try:
                self._sync_step4_analysis_nav_buttons()
            except Exception:
                pass

            try:
                self.frame.update_idletasks()
            except Exception:
                pass

            try:
                self._sync_train_left_scrollregion()
            except Exception:
                pass

        try:
            pending = getattr(self, "_training_visible_layout_after_id", None)
            if pending is not None:
                self.frame.after_cancel(pending)
        except Exception:
            pass
        self._training_visible_layout_after_id = None

        _run_sync()

        try:
            self._training_visible_layout_after_id = self.frame.after(90, _run_sync)
        except Exception:
            pass

        return True

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
        return self._inertial_scroll.mousewheel_units(event)

    def _train_left_canvas_overflows(self) -> bool:
        canvas = getattr(self, "train_left_canvas", None)
        return self._scroll_canvas_overflows(canvas)

    def _dataset_mode_canvas_overflows(self) -> bool:
        canvas = getattr(self, "ds_mode_canvas", None)
        return self._scroll_canvas_overflows(canvas)

    def _scroll_canvas_overflows(self, canvas) -> bool:
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

    def _on_train_left_global_mousewheel(self, event):
        canvas = getattr(self, "train_left_canvas", None)
        if canvas is None:
            return None

        if self._training_combobox_scroll_guard_active():
            return "break"
        if self._mousewheel_event_from_combobox(event):
            return "break"

        if self._inertial_scroll.scroll_canvas_if_targeted(
            canvas,
            event,
            pointer_widget=self.frame,
            overflow_checker=self._train_left_canvas_overflows,
        ):
            return "break"
        return None

    def _on_dataset_mode_global_mousewheel(self, event):
        canvas = getattr(self, "ds_mode_canvas", None)
        if canvas is None:
            return None

        if self._training_combobox_scroll_guard_active():
            return "break"
        if self._mousewheel_event_from_combobox(event):
            return "break"

        if self._inertial_scroll.scroll_canvas_if_targeted(
            canvas,
            event,
            pointer_widget=self.frame,
            overflow_checker=self._dataset_mode_canvas_overflows,
        ):
            return "break"
        return None

    def _restore_scroll_canvas_focus(self, canvas):
        if canvas is None:
            return
        try:
            canvas.focus_set()
        except Exception:
            pass

    def _redirect_child_mousewheel_to_canvas(self, event, canvas):
        if canvas is None:
            return None

        if self._inertial_scroll.redirect_child_mousewheel_to_canvas(
            event,
            canvas,
            pointer_widget=self.frame,
            overflow_checker=lambda c=canvas: self._scroll_canvas_overflows(c),
        ):
            self._restore_scroll_canvas_focus(canvas)
            return "break"

        self._restore_scroll_canvas_focus(canvas)
        return "break"

    def _redirect_combobox_mousewheel_to_canvas(self, event, canvas):
        # Zamknięty Combobox w Tk potrafi zmienić wartość samym kółkiem myszy.
        # W Z4 to zbyt ryzykowne: scroll nad polem ma przewijać panel, a wybór
        # modelu ma następować dopiero po świadomym rozwinięciu listy.
        widget = getattr(event, "widget", None)
        if self._combobox_popdown_visible(widget):
            self._mark_training_combobox_scroll_guard(widget)
            return "break"

        self._mark_training_combobox_scroll_guard(widget, hold_ms=250)
        if self._inertial_scroll.redirect_child_mousewheel_to_canvas(
            event,
            canvas,
            pointer_widget=self.frame,
            overflow_checker=lambda c=canvas: self._scroll_canvas_overflows(c),
        ):
            self._restore_scroll_canvas_focus(canvas)
            return "break"

        self._restore_scroll_canvas_focus(canvas)
        return "break"

    def _register_training_scroll_guard_combobox(self, widget) -> None:
        if widget is None or bool(getattr(widget, "_training_scroll_guard_bound", False)):
            return

        try:
            widget._training_scroll_guard_bound = True
        except Exception:
            pass

        registered = list(getattr(self, "_training_scroll_guard_comboboxes", []) or [])
        if widget not in registered:
            registered.append(widget)
            self._training_scroll_guard_comboboxes = registered

        def _mark(_event=None, w=widget):
            self._mark_training_combobox_scroll_guard(w)
            return None

        def _release(_event=None):
            self._schedule_training_combobox_guard_poll(delay_ms=120)
            return None

        for sequence in ("<ButtonPress-1>", "<KeyPress-Down>", "<Alt-Down>", "<FocusIn>"):
            try:
                widget.bind(sequence, _mark, add="+")
            except Exception:
                pass
        for sequence in ("<<ComboboxSelected>>", "<Escape>", "<Return>", "<FocusOut>"):
            try:
                widget.bind(sequence, _release, add="+")
            except Exception:
                pass

    def _mark_training_combobox_scroll_guard(self, widget=None, *, hold_ms: int = 1200) -> None:
        try:
            self._training_combobox_scroll_guard_widget = widget
            self._training_combobox_scroll_guard_until = time.perf_counter() + (max(150, int(hold_ms)) / 1000.0)
        except Exception:
            return
        self._schedule_training_combobox_guard_poll(delay_ms=120)

    def _schedule_training_combobox_guard_poll(self, *, delay_ms: int = 180) -> None:
        frame = getattr(self, "frame", None)
        if frame is None:
            return

        pending = getattr(self, "_training_combobox_scroll_guard_after_id", None)
        if pending is not None:
            try:
                frame.after_cancel(pending)
            except Exception:
                pass

        try:
            self._training_combobox_scroll_guard_after_id = frame.after(
                max(50, int(delay_ms)),
                self._poll_training_combobox_scroll_guard,
            )
        except Exception:
            self._training_combobox_scroll_guard_after_id = None

    def _poll_training_combobox_scroll_guard(self) -> None:
        self._training_combobox_scroll_guard_after_id = None
        if self._any_training_combobox_popdown_visible():
            self._mark_training_combobox_scroll_guard(
                getattr(self, "_training_combobox_scroll_guard_widget", None),
                hold_ms=900,
            )
            return

        try:
            if time.perf_counter() >= float(getattr(self, "_training_combobox_scroll_guard_until", 0.0) or 0.0):
                self._training_combobox_scroll_guard_until = 0.0
                self._training_combobox_scroll_guard_widget = None
                return
        except Exception:
            self._training_combobox_scroll_guard_until = 0.0
            self._training_combobox_scroll_guard_widget = None
            return

        self._schedule_training_combobox_guard_poll(delay_ms=180)

    def _combobox_popdown_visible(self, widget) -> bool:
        if widget is None:
            return False
        try:
            if not bool(widget.winfo_exists()):
                return False
        except Exception:
            return False

        try:
            popdown = widget.tk.call("ttk::combobox::PopdownWindow", str(widget))
            return bool(int(widget.tk.call("winfo", "viewable", popdown)))
        except Exception:
            return False

    def _any_training_combobox_popdown_visible(self) -> bool:
        for widget in list(getattr(self, "_training_scroll_guard_comboboxes", []) or []):
            if self._combobox_popdown_visible(widget):
                return True
        return False

    def _training_combobox_scroll_guard_active(self) -> bool:
        if self._any_training_combobox_popdown_visible():
            return True
        try:
            return time.perf_counter() < float(getattr(self, "_training_combobox_scroll_guard_until", 0.0) or 0.0)
        except Exception:
            return False

    def _widget_is_combobox_or_popdown(self, widget) -> bool:
        visited = set()
        while widget is not None and id(widget) not in visited:
            visited.add(id(widget))
            try:
                class_name = str(widget.winfo_class())
            except Exception:
                class_name = ""
            try:
                widget_path = str(widget).lower()
            except Exception:
                widget_path = ""

            if class_name in {"TCombobox", "ComboboxPopdown"}:
                return True
            if class_name in {"Listbox", "Toplevel", "Frame"} and (
                "popdown" in widget_path or "combobox" in widget_path
            ):
                return True

            try:
                widget = widget.master
            except Exception:
                widget = None
        return False

    def _mousewheel_event_from_combobox(self, event) -> bool:
        if self._widget_is_combobox_or_popdown(getattr(event, "widget", None)):
            self._mark_training_combobox_scroll_guard(getattr(event, "widget", None))
            return True

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
            root = self.frame.winfo_toplevel()
            pointer_widget = root.winfo_containing(x_root, y_root)
        except Exception:
            pointer_widget = None

        if self._widget_is_combobox_or_popdown(pointer_widget):
            self._mark_training_combobox_scroll_guard(pointer_widget)
            return True
        return False

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
                class_name = str(widget.winfo_class())
            except Exception:
                class_name = ""

            if class_name != "TCombobox":
                try:
                    widget.bind("<MouseWheel>", lambda e, c=canvas: self._redirect_child_mousewheel_to_canvas(e, c), add="+")
                    widget.bind("<Button-4>", lambda e, c=canvas: self._redirect_child_mousewheel_to_canvas(e, c), add="+")
                    widget.bind("<Button-5>", lambda e, c=canvas: self._redirect_child_mousewheel_to_canvas(e, c), add="+")
                except Exception:
                    pass

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
                        self._register_training_scroll_guard_combobox(widget)
                    except Exception:
                        pass
                    try:
                        widget.bind("<MouseWheel>", lambda e, c=canvas: self._redirect_combobox_mousewheel_to_canvas(e, c), add="+")
                        widget.bind("<Button-4>", lambda e, c=canvas: self._redirect_combobox_mousewheel_to_canvas(e, c), add="+")
                        widget.bind("<Button-5>", lambda e, c=canvas: self._redirect_combobox_mousewheel_to_canvas(e, c), add="+")
                    except Exception:
                        pass
                    try:
                        widget.bind("<<ComboboxSelected>>", lambda _e, c=canvas: self._restore_scroll_canvas_focus(c), add="+")
                    except Exception:
                        pass

            for child in widget.winfo_children():
                _walk(child)

        _walk(root)

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        console_border = palette.get("console_border", palette.get("border", "#3c3c3c"))

        try:
            self._configure_train_progress_styles()
        except Exception:
            pass

        for label_name in ("free_training_route_title_lbl",):
            label = getattr(self, label_name, None)
            if label is None or not hasattr(label, "apply_theme"):
                continue
            try:
                label.apply_theme()
            except Exception:
                pass

        for label_name in (
            "train_dataset_title_lbl",
            "train_base_title_lbl",
            "train_params_title_lbl",
        ):
            label = getattr(self, label_name, None)
            if label is None:
                continue
            try:
                label.configure(
                    bg=palette.get("panel", "#252526"),
                    fg=palette.get("fg", "#f3f3f3"),
                )
            except Exception:
                pass

        try:
            self.app.style_panel_surface(self.frame, background=palette.get("panel", "#252526"))
        except Exception:
            pass
        try:
            self._configure_train_progress_styles()
        except Exception:
            pass

        for widget_name in ("step4_builder_log_text", "train_log_console"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                self.app.style_text_widget(widget, role="console")
            except Exception:
                pass

        try:
            self.app.style_listbox_widget(self.plots_list, bordercolor=console_border)
        except Exception:
            pass

        try:
            self.app.style_canvas_widget(
                self.plot_canvas,
                background=palette.get("panel", "#252526"),
                bordercolor=console_border
            )
        except Exception:
            pass

        try:
            for canvas_name in ("train_left_canvas", "ds_mode_canvas"):
                canvas = getattr(self, canvas_name, None)
                if canvas is None:
                    continue
                canvas.configure(
                    bg=palette.get("panel", "#252526"),
                    highlightbackground=console_border,
                    highlightcolor=console_border
                )
        except Exception:
            pass

        for frame_name in (
            "step4_route_panel_frame",
            "btn_step4_next_frame",
            "btn_step4_create_frame",
            "btn_step4_split_frame",
            "btn_step4_start_train_frame",
            "btn_step4_finish_frame",
        ):
            frame = getattr(self, frame_name, None)
            if frame is None:
                continue
            try:
                bg = palette.get("bg", "#1e1e1e") if frame_name == "step4_route_panel_frame" else palette.get("panel", "#252526")
                self.app.style_guidance_frame(frame, background=bg)
            except Exception:
                pass

        try:
            summary_shell = getattr(self, "train_run_summary_shell", None)
            summary_title_row = getattr(self, "train_run_summary_title_row", None)
            summary_title = getattr(self, "train_run_summary_title_lbl", None)
            summary_grid = getattr(self, "train_run_summary_grid", None)
            summary_header_key = getattr(self, "train_run_summary_header_key_lbl", None)
            summary_header_value = getattr(self, "train_run_summary_header_value_lbl", None)
            summary_bg = palette.get("panel_alt", palette.get("panel", "#252526"))
            summary_title_bg = palette.get("panel", "#252526")
            summary_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
            if summary_shell is not None:
                summary_shell.configure(
                    bg=summary_bg,
                    highlightbackground=summary_border,
                    highlightcolor=summary_border,
                )
            if summary_title_row is not None:
                summary_title_row.configure(bg=summary_title_bg)
            if summary_title is not None:
                summary_title.configure(
                    bg=summary_title_bg,
                    fg=palette.get("fg", "#f3f3f3"),
                )
            if summary_grid is not None:
                summary_grid.configure(bg=summary_bg)
            for header_widget in (summary_header_key, summary_header_value):
                if header_widget is not None:
                    header_widget.configure(
                        bg=palette.get("panel", "#252526"),
                        fg=palette.get("fg", "#f3f3f3"),
                    )
            for row in list(getattr(self, "_train_run_summary_row_widgets", []) or []):
                key_widget = row.get("key")
                value_widget = row.get("value")
                row_index = int(row.get("row_index", 0) or 0)
                row_bg = palette.get("panel", "#252526") if row_index % 2 == 0 else palette.get("panel_alt", "#2d2d30")
                value_bg = blend_hex_colors(row_bg, palette.get("surface_info", "#213a4d"), 0.18)
                if key_widget is not None:
                    key_widget.configure(
                        bg=row_bg,
                        fg=palette.get("fg", "#f3f3f3"),
                    )
                if value_widget is not None:
                    value_widget.configure(
                        bg=value_bg,
                        fg=palette.get("muted", "#c7c7c7"),
                    )
        except Exception:
            pass

        try:
            if hasattr(self, "free_training_route_host"):
                self.free_training_route_host.configure(style="TLabelframe")
        except Exception:
            pass

        try:
            cards = getattr(self, "_free_training_route_cards", {})
            for widgets in cards.values():
                frame = widgets.get("frame")
                if frame is not None:
                    frame.configure(bg=palette.get("panel_alt", "#2d2d30"))
        except Exception:
            pass

        try:
            if hasattr(self, "free_training_route_cards_row"):
                self.free_training_route_cards_row.configure(bg=palette.get("panel", "#252526"))
        except Exception:
            pass

        menu = getattr(self, "history_context_menu", None)
        if menu is not None:
            try:
                menu.configure(
                    bg=palette.get("panel", "#252526"),
                    fg=palette.get("fg", "#f3f3f3"),
                    activebackground=palette.get("button_hover", "#37373d"),
                    activeforeground=palette.get("fg", "#f3f3f3"),
                    bd=0,
                    relief=tk.FLAT,
                )
            except Exception:
                pass

        for line in getattr(self, "_train_left_section_separators", []):
            if line is None:
                continue
            try:
                if isinstance(line, dict):
                    host = line.get("host")
                    accent = line.get("accent")
                    shadow = line.get("shadow")
                    if host is not None:
                        host.configure(bg=palette.get("panel", "#252526"))
                    if accent is not None:
                        accent.configure(bg=palette.get("surface_info", palette.get("accent", "#0e639c")))
                    if shadow is not None:
                        shadow.configure(bg=palette.get("panel_border", palette.get("border", "#3c3c3c")))
                else:
                    line.configure(bg=palette.get("surface_info", palette.get("accent", "#0e639c")))
            except Exception:
                pass

        self._refresh_free_training_route_cards()
        try:
            self._refresh_step4_dataset_mode_ui()
        except Exception:
            pass
        self._apply_training_recommendation_table_theme()
        try:
            self._refresh_training_dataset_quality_summary()
        except Exception:
            pass
        self._style_analysis_dialog()

    def _set_step4_train_log_visibility(self, visible: bool):
        if not hasattr(self, "step4_train_log_frame"):
            return

        self._step4_train_log_visible = bool(visible)
        try:
            self.step4_train_log_frame.pack_forget()
        except Exception:
            pass
        if hasattr(self, "step4_train_log_host"):
            try:
                self.step4_train_log_host.grid_remove()
            except Exception:
                pass

        if self._step4_train_log_visible:
            try:
                if hasattr(self.app, "show_global_terminal"):
                    self.app.show_global_terminal()
            except Exception:
                pass

        if hasattr(self, "btn_toggle_step4_train_log"):
            try:
                self.btn_toggle_step4_train_log.configure(text="Terminal")
            except Exception:
                pass
        return

        if self._step4_train_log_visible:
            if hasattr(self, "step4_train_log_host"):
                try:
                    self.step4_train_log_host.grid()
                except Exception:
                    pass
            self.step4_train_log_frame.pack(fill=tk.BOTH, expand=False)
            if hasattr(self, "btn_toggle_step4_train_log"):
                self.btn_toggle_step4_train_log.configure(text="Ukryj terminal")
        else:
            self.step4_train_log_frame.pack_forget()
            if hasattr(self, "step4_train_log_host"):
                try:
                    self.step4_train_log_host.grid_remove()
                except Exception:
                    pass
            if hasattr(self, "btn_toggle_step4_train_log"):
                self.btn_toggle_step4_train_log.configure(text="Pokaż terminal")

    def _toggle_step4_train_log(self):
        try:
            if hasattr(self.app, "toggle_global_terminal"):
                self.app.toggle_global_terminal()
                return
        except Exception:
            pass
        self._set_step4_train_log_visibility(
            not getattr(self, "_step4_train_log_visible", False)
        )

    def _select_step4_analysis_tab(self, tab_widget):
        if not hasattr(self, "right_nb"):
            return

        try:
            self.right_nb.select(tab_widget)
            self._sync_step4_analysis_nav_buttons()
        except Exception:
            pass

    def _is_ranking_available_for_selected_target(self) -> bool:
        return CONFIG.normalize_task_target(self._get_selected_training_target()) == "plate"

    def _refresh_step4_analysis_tab_visibility(self):
        refresh_step4_analysis_tab_visibility(self)

    def _sync_step4_analysis_nav_buttons(self, event=None):
        sync_step4_analysis_nav_buttons(self, event=event)

    def _clear_step4_guidance(self):
        clear_step4_guidance(self)

    def _guide_step4_route_selection(self):
        guide_step4_route_selection(self)

    def _guide_step4_builder_action(self):
        guide_step4_builder_action(self)

    def _guide_step4_next_action(self):
        guide_step4_next_action(self)

    def _guide_step4_training_action(self):
        guide_step4_training_action(self)

    def _guide_step4_finish_action(self):
        guide_step4_finish_action(self)

    def _open_step4_dataset_stage(self):
        open_step4_dataset_stage(self)

    def _mark_step4_dataset_ready(self, dataset_path: str | Path | None = None):
        mark_step4_dataset_ready(self, dataset_path=dataset_path)

    def _accept_training_input_context(
        self,
        *,
        source: str = "",
        target: str = "",
        dataset_path: str | Path | None = None,
        select_training: bool = False,
    ) -> bool:
        return accept_training_input_context(
            self,
            source=source,
            target=target,
            dataset_path=dataset_path,
            select_training=select_training,
        )

    def _set_step4_dataset_mode(self, mode: str, *, show_locked_message: bool = True):
        set_step4_dataset_mode(self, mode, show_locked_message=show_locked_message)

    def _get_step4_dataset_workflow_view_model(self) -> Step4DatasetWorkflowViewModel:
        return build_step4_dataset_workflow_view_model(self)

    def _get_step4_training_inputs_view_model(self) -> Step4TrainingInputsViewModel:
        return build_step4_training_inputs_view_model(self)

    def _get_step4_campaign_navigation_view_model(self) -> Step4CampaignNavigationViewModel:
        return build_step4_campaign_navigation_view_model(self)

    def _refresh_step4_campaign_builder_inputs_ui(self):
        refresh_step4_campaign_builder_inputs_ui(self)

    def _refresh_step4_training_inputs_mode_ui(self):
        refresh_step4_training_inputs_mode_ui(self)

    def _refresh_step4_dataset_mode_ui(self):
        refresh_step4_dataset_mode_ui(self)

    def _step4_dataset_go_next(self):
        step4_dataset_go_next(self)

    def _step4_dataset_go_back(self):
        step4_dataset_go_back(self)

    def _toggle_step4_char_split_details(self):
        self._step4_char_split_details_visible = not bool(getattr(self, "_step4_char_split_details_visible", False))
        try:
            self._refresh_step4_campaign_builder_inputs_ui()
        except Exception:
            pass

    def _refresh_step4_campaign_navigation_ui(self):
        refresh_step4_campaign_navigation_ui(self)


    def _step4_train_go_back(self):
        step4_train_go_back(self)

    def _finish_campaign_step4(self):
        return finish_campaign_step4(self)

    def _complete_campaign_project(self):
        complete_campaign_project(self)

    def _get_run_dir_for_run_id(self, run_id: str) -> Path | None:
        if not run_id:
            return None

        base = self._get_runs_base_dir()
        candidate = base / run_id
        if candidate.exists() and candidate.is_dir():
            return candidate

        # fallback: szukaj po stemie / nazwie zawierającej run_id
        try:
            matches = [p for p in base.iterdir() if p.is_dir() and run_id in p.name]
            if matches:
                matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return matches[0]
        except Exception:
            pass

        return None


    def _find_best_weights_for_run(self, run_id: str) -> Path | None:
        run_dir = self._get_run_dir_for_run_id(run_id)
        if run_dir is None:
            return None

        direct = run_dir / "weights" / "best.pt"
        if direct.exists():
            return direct

        try:
            candidates = list(run_dir.rglob("best.pt"))
            if candidates:
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return candidates[0]
        except Exception:
            pass

        return None

    @staticmethod
    def _json_safe_training_value(value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): TrainingTab._json_safe_training_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [TrainingTab._json_safe_training_value(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _training_metric_float(value) -> float | None:
        if value in (None, "", "-"):
            return None
        try:
            numeric = float(str(value).strip().replace(",", "."))
        except Exception:
            return None
        return numeric if numeric == numeric else None

    @classmethod
    def _training_metric_value(cls, mapping: dict | None, keys: tuple[str, ...]) -> float | None:
        if not isinstance(mapping, dict):
            return None

        for key in keys:
            if key in mapping:
                value = cls._training_metric_float(mapping.get(key))
                if value is not None:
                    return value

        lowered = {str(k or "").strip().lower(): v for k, v in mapping.items()}
        for key in keys:
            value = cls._training_metric_float(lowered.get(str(key or "").strip().lower()))
            if value is not None:
                return value
        return None

    @staticmethod
    def _safe_model_export_slug(value: str, fallback: str = "model") -> str:
        text = str(value or "").strip()
        if not text:
            text = fallback
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
        return (slug or fallback)[:48]

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


    def _poll_training_completion(self):
        poll_training_completion(self)

    def _set_training_ui_running_state(self):
        try:
            self.btn_start_train.configure(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.btn_pause_train.configure(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.btn_stop_train.configure(state=tk.NORMAL)
        except Exception:
            pass

        try:
            self.train_progress_label.configure(
                text="Trening w toku...",
                foreground="#d35400"
            )
        except Exception:
            pass

    def _set_training_ui_idle_state(self, status_text="Czekam na start...", color="gray"):
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

        try:
            self.btn_pause_train.configure(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.btn_stop_train.configure(state=tk.DISABLED)
        except Exception:
            pass

        try:
            self.train_progress_label.configure(
                text=status_text,
                foreground=color
            )
        except Exception:
            pass
        try:
            self._reset_training_runtime_progress()
        except Exception:
            pass

    
    def _scan_training_cuda_devices(self) -> list[dict]:
        devices: list[dict] = []
        if not bool(getattr(self, "_startup_ui_ready", False)):
            return devices
        try:
            torch = get_torch_module()
            if torch is None:
                return devices

            if not torch.cuda.is_available():
                return devices

            for index in range(torch.cuda.device_count()):
                name = f"CUDA:{index}"
                total_memory_gb = 0.0
                try:
                    props = torch.cuda.get_device_properties(index)
                    name = str(getattr(props, "name", name) or name)
                    total_memory = float(getattr(props, "total_memory", 0) or 0)
                    total_memory_gb = total_memory / (1024 ** 3) if total_memory > 0 else 0.0
                except Exception:
                    pass

                devices.append(
                    {
                        "raw": f"cuda:{index}",
                        "index": index,
                        "name": name,
                        "memory_gb": total_memory_gb,
                    }
                )
        except Exception:
            pass
        return devices

    def _get_available_devices(self):
        profiles = self._scan_training_cuda_devices()
        self._training_device_profiles = profiles
        self._training_device_label_map = {}

        auto_label = "Auto - preferuj GPU CUDA, inaczej CPU" if profiles else "Auto - CPU (brak CUDA)"
        cpu_label = "CPU - procesor"

        self._training_auto_device_label = auto_label
        self._training_cpu_device_label = cpu_label

        labels = [auto_label, cpu_label]
        self._training_device_label_map[auto_label] = "auto"
        self._training_device_label_map[cpu_label] = "cpu"

        for profile in profiles:
            mem = float(profile.get("memory_gb", 0.0) or 0.0)
            mem_text = f"{mem:.1f} GB VRAM" if mem > 0 else "VRAM ?"
            label = f"GPU {profile['index']} - {profile['name']} ({mem_text})"
            labels.append(label)
            self._training_device_label_map[label] = str(profile["raw"])

        return labels

    def _get_global_training_device_choice(self) -> str:
        getter = getattr(self.app, "get_global_yolo_device_choice", None)
        if callable(getter):
            try:
                value = str(getter() or "").strip()
                if value:
                    return value
            except Exception:
                pass

        try:
            value = str(self.device_var.get() or "").strip()
            if value:
                return value
        except Exception:
            pass

        return "auto"

    def apply_global_yolo_device_choice(self, value: str):
        normalized = str(value or "").strip() or "auto"
        normalizer = getattr(self.app, "normalize_global_yolo_device_choice", None)
        if callable(normalizer):
            try:
                normalized = str(normalizer(normalized) or "auto").strip() or "auto"
            except Exception:
                normalized = str(value or "").strip() or "auto"

        if not hasattr(self, "device_var"):
            self.device_var = tk.StringVar(value=normalized)
        else:
            try:
                self.device_var.set(normalized)
            except Exception:
                pass

        try:
            self._refresh_training_device_hint()
        except Exception:
            pass

    def _normalize_training_device_choice(self, device_value: str | None = None) -> str:
        value = str(device_value or "").strip()
        if not value:
            return self._training_auto_device_label
        if value in self._training_device_label_map:
            return value

        raw = value.lower()
        if raw == "auto":
            return self._training_auto_device_label
        if raw == "cpu":
            return self._training_cpu_device_label

        for label, mapped in self._training_device_label_map.items():
            if str(mapped).lower() == raw:
                return label

        if raw.startswith("cuda:"):
            raw_token = raw.split()[0]
            try:
                wanted_index = int(raw_token.split(":", 1)[1])
            except Exception:
                wanted_index = 0
            for profile in self._training_device_profiles:
                if int(profile.get("index", -1)) == wanted_index:
                    for label, mapped in self._training_device_label_map.items():
                        if mapped == profile.get("raw"):
                            return label

        return self._training_auto_device_label

    def _get_selected_training_device_raw(self, device_value: str | None = None) -> str:
        if device_value is None:
            try:
                current_value = self.device_var.get()
            except Exception:
                current_value = self._get_global_training_device_choice()
        else:
            current_value = device_value

        value = str(current_value).strip()
        if not value:
            return "auto"
        if value in self._training_device_label_map:
            return str(self._training_device_label_map.get(value, "auto"))

        raw = value.lower()
        if raw.startswith("auto"):
            return "auto"
        if raw.startswith("cpu"):
            return "cpu"
        if raw.startswith("cuda:"):
            return raw.split()[0]
        if raw in {"auto", "cpu"}:
            return raw
        return "auto"

    def _get_effective_training_device_profile(self, device_value: str | None = None) -> tuple[str, dict | None]:
        profiles = self._training_device_profiles or self._scan_training_cuda_devices()
        selected_raw = self._get_selected_training_device_raw(device_value)

        if selected_raw == "auto":
            if profiles:
                return str(profiles[0].get("raw", "cuda:0")), profiles[0]
            return "cpu", None

        if selected_raw == "cpu":
            return "cpu", None

        for profile in profiles:
            if str(profile.get("raw")) == selected_raw:
                return selected_raw, profile

        return "cpu", None

    def _get_training_device_recommendation(self, device_value: str | None = None) -> dict:
        target = self._get_selected_training_target()
        effective_raw, profile = self._get_effective_training_device_profile(device_value)
        dataset_profile = self._get_training_dataset_profile()
        model_profile = self._resolve_selected_training_base_model_profile()
        model_bucket = str(model_profile.get("bucket", "s") or "s").strip().lower()
        model_detected_label = str(model_profile.get("detected_label", "") or "").strip()
        model_label = str(model_profile.get("label", "") or "").strip()
        model_identity_label = model_detected_label or model_label
        model_version_label = str(model_profile.get("model_version_label", "") or "").strip()
        model_size_label = str(model_profile.get("model_size_label", "") or "").strip()
        model_params_text = str(model_profile.get("params_text", "") or "").strip()
        train_images = int(dataset_profile.get("train_images", 0) or 0)
        val_images = int(dataset_profile.get("val_images", 0) or 0)
        total_images = int(dataset_profile.get("total_images", 0) or 0)
        median_long_edge = int(dataset_profile.get("median_long_edge", 0) or 0)
        sampled_images = int(dataset_profile.get("sampled_images", 0) or 0)

        if effective_raw == "cpu" or profile is None:
            cpu_imgsz = 512 if target == "char" else 640
            return {
                "effective_raw": "cpu",
                "device_name": "CPU",
                "memory_gb": 0.0,
                "epochs": 100,
                "batch": 2 if target == "char" else 1,
                "imgsz": cpu_imgsz,
                "lr0": 0.004 if target == "char" else 0.003,
                "model_detected_label": model_detected_label,
                "model_label": model_label,
                "model_identity_label": model_identity_label,
                "model_version_label": model_version_label,
                "model_size_label": model_size_label,
                "model_params_text": model_params_text,
                "model_bucket": model_bucket,
                "note": (
                    "Zalecenie awaryjne dla CPU. Uwzglednia tor i konserwatywny start bez ryzyka OOM. "
                    "Trening bedzie wyraznie wolniejszy niz na GPU CUDA."
                ),
            }

        memory_gb = float(profile.get("memory_gb", 0.0) or 0.0)
        if target == "char":
            if median_long_edge <= 0:
                desired_imgsz = 640
            elif median_long_edge <= 192:
                desired_imgsz = 416
            elif median_long_edge <= 320:
                desired_imgsz = 512
            elif median_long_edge <= 512:
                desired_imgsz = 576
            elif median_long_edge <= 768:
                desired_imgsz = 640
            else:
                desired_imgsz = 768
            min_imgsz = 416
        else:
            if median_long_edge <= 0:
                desired_imgsz = 768
            elif median_long_edge <= 768:
                desired_imgsz = 640
            elif median_long_edge <= 1024:
                desired_imgsz = 768
            elif median_long_edge <= 1400:
                desired_imgsz = 960
            elif median_long_edge <= 1800:
                desired_imgsz = 1024
            else:
                desired_imgsz = 1280
            min_imgsz = 640

        if target == "plate" and memory_gb <= 4.5:
            desired_imgsz = min(int(desired_imgsz), 256 if total_images >= 120 else 320)
            min_imgsz = 256

        if memory_gb <= 4.5:
            base_cap_imgsz = 640
        elif memory_gb <= 6.5:
            base_cap_imgsz = 768
        elif memory_gb <= 8.5:
            base_cap_imgsz = 896
        elif memory_gb <= 12.5:
            base_cap_imgsz = 960
        elif memory_gb <= 16.5:
            base_cap_imgsz = 1024
        else:
            base_cap_imgsz = 1280

        cap_steps = [256, 320, 384, 416, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024, 1280]
        cap_minimum = 256 if (target == "plate" and memory_gb <= 4.5) else 384
        cap_anchor = self._nearest_training_imgsz(base_cap_imgsz, minimum=cap_minimum, maximum=1280)
        try:
            cap_index = cap_steps.index(cap_anchor)
        except ValueError:
            cap_index = len(cap_steps) - 1

        model_penalty = {"n": 0, "s": 0, "m": 1, "l": 2, "x": 3}.get(model_bucket, 1)
        task_penalty = 1 if target == "plate" else 0
        if train_images > 0 and train_images < 25:
            dataset_penalty = 2
        elif train_images > 0 and train_images < 80:
            dataset_penalty = 1
        else:
            dataset_penalty = 0
        cap_index = max(0, cap_index - model_penalty - task_penalty - dataset_penalty)
        cap_imgsz = max(min_imgsz, cap_steps[cap_index])
        imgsz = self._nearest_training_imgsz(
            min(desired_imgsz, cap_imgsz),
            minimum=min_imgsz,
            maximum=1280,
        )

        if target == "char":
            if memory_gb <= 4.5:
                base_batch = 8
            elif memory_gb <= 6.5:
                base_batch = 10
            elif memory_gb <= 8.5:
                base_batch = 14
            elif memory_gb <= 12.5:
                base_batch = 18
            elif memory_gb <= 16.5:
                base_batch = 24
            else:
                base_batch = 28
            reference_imgsz = 640.0
            batch_ceiling = 32
        else:
            if memory_gb <= 4.5:
                base_batch = 2
            elif memory_gb <= 6.5:
                base_batch = 4
            elif memory_gb <= 8.5:
                base_batch = 6
            elif memory_gb <= 12.5:
                base_batch = 8
            elif memory_gb <= 16.5:
                base_batch = 10
            else:
                base_batch = 12
            reference_imgsz = 768.0
            batch_ceiling = 16

        if target == "plate" and memory_gb <= 4.5:
            base_batch = 1
            reference_imgsz = 512.0
            batch_ceiling = 1

        model_factor = {"n": 1.15, "s": 1.0, "m": 0.80, "l": 0.65, "x": 0.50}.get(model_bucket, 0.85)
        resolution_factor = (reference_imgsz / float(max(imgsz, 1))) ** 2
        resolution_factor = max(0.25, min(1.25, resolution_factor))
        batch = int(base_batch * model_factor * resolution_factor)

        if total_images < 24:
            batch = min(batch, 4 if target == "char" else 2)
        elif total_images < 64:
            batch = min(batch, 8 if target == "char" else 4)
        elif total_images < 120:
            batch = min(batch, 12 if target == "char" else 6)

        if train_images > 0:
            batch = min(batch, train_images)

        batch = max(1, min(batch_ceiling, int(batch)))

        # Dodatkowy bezpiecznik dla cięższych checkpointów pose na mniejszym VRAM.
        # W praktyce właśnie takie konfiguracje najczęściej wywracają się na plate/pose
        # przy mosaic=1 jeszcze przed końcem pierwszej epoki.
        if (
            target == "plate"
            and model_bucket in {"m", "l", "x"}
            and memory_gb <= 6.5
            and total_images >= 1000
        ):
            batch = 1
            imgsz = min(int(imgsz), 512)

        if target == "plate" and memory_gb <= 4.5:
            batch = 1
            imgsz = min(int(imgsz), 256 if total_images >= 120 else 320)

        lr0 = 0.0100 if target == "char" else 0.0080
        if batch <= 2:
            lr0 *= 0.55
        elif batch <= 4:
            lr0 *= 0.70
        elif batch <= 8:
            lr0 *= 0.82
        elif batch <= 16:
            lr0 *= 0.92

        if model_bucket in {"l", "x"}:
            lr0 *= 0.85
        elif model_bucket == "m":
            lr0 *= 0.92

        if train_images > 0 and train_images < 50:
            lr0 *= 0.80
        elif train_images > 0 and train_images < 100:
            lr0 *= 0.90

        if target == "plate" and imgsz >= 960:
            lr0 *= 0.90

        lr0 = round(max(0.0025, min(0.0100, lr0)), 4)

        factor_bits = [f"aktywny tor to {self._format_training_target_label(target)}"]
        if model_detected_label:
            factor_bits.append(f"wybrany model to {model_detected_label}")
        elif model_label:
            factor_bits.append(f"wybrany model to {model_label}")
        else:
            factor_bits.append(f"klasa modelu to {model_bucket.upper()}")
        variant_bits = [bit for bit in (model_version_label, model_size_label) if bit]
        if variant_bits:
            factor_bits.append(f"wariant modelu to {' / '.join(variant_bits)}")
        if model_params_text:
            factor_bits.append(f"katalogowo model ma ok. {model_params_text} parametrów")
        factor_bits.append(f"dostępne VRAM to {memory_gb:.1f} GB")
        if sampled_images > 0 and median_long_edge > 0:
            factor_bits.append(f"mediana dłuższego boku obrazu wynosi {median_long_edge}px")
        if train_images > 0 or val_images > 0:
            factor_bits.append(f"split train/val ma układ {train_images}/{val_images}")

        return {
            "effective_raw": effective_raw,
            "device_name": str(profile.get("name", effective_raw)),
            "memory_gb": memory_gb,
            "epochs": 100,
            "batch": batch,
            "imgsz": imgsz,
            "lr0": lr0,
            "model_bucket": model_bucket,
            "model_detected_label": model_detected_label,
            "model_label": model_label,
            "model_identity_label": model_identity_label,
            "model_version_label": model_version_label,
            "model_size_label": model_size_label,
            "model_params_text": model_params_text,
            "train_images": train_images,
            "val_images": val_images,
            "total_images": total_images,
            "median_long_edge": median_long_edge,
            "note": (
                "To bezpieczny punkt startowy. Zalecenie uwzględnia, że "
                + ", ".join(factor_bits)
                + ". Jeśli mimo to zabraknie pamięci VRAM, najpierw zmniejsz rozmiar partii, "
                  "a dopiero potem rozdzielczość wejściową."
            ),
        }

    def _build_training_device_hint_text(self) -> str:
        selected_display = self._normalize_training_device_choice(
            self._get_global_training_device_choice()
        )
        selected_raw = self._get_selected_training_device_raw(selected_display)
        recommendation = self._get_training_device_recommendation(selected_display)
        selected_target = self._format_training_target_label(self._get_selected_training_target())

        if selected_raw == "auto":
            if recommendation["effective_raw"] == "cpu":
                prefix = "AUTO użyje CPU, bo nie wykryto GPU CUDA."
            else:
                prefix = (
                    f"AUTO użyje {recommendation['device_name']} "
                    f"({recommendation['memory_gb']:.1f} GB VRAM)."
                )
        elif recommendation["effective_raw"] == "cpu":
            prefix = "Wybrano trening na CPU."
        else:
            prefix = (
                f"Wybrano {recommendation['device_name']} "
                f"({recommendation['memory_gb']:.1f} GB VRAM)."
            )

        return (
            f"Z4 korzysta z globalnego ustawienia urządzenia. {prefix} "
            f"Aktywny tor: {selected_target}. "
            f"Na początek warto ustawić: rozmiar partii {recommendation['batch']}, "
            f"rozdzielczość wejściową {recommendation['imgsz']} "
            f"oraz współczynnik uczenia {recommendation['lr0']:.3f}. "
            "Liczbę epok ustawiasz samodzielnie. "
            f"{recommendation['note']}"
        )

    def _refresh_training_device_hint(self):
        combo = getattr(self, "device_combo", None)
        if combo is not None:
            try:
                combo.configure(values=self._get_available_devices())
            except Exception:
                pass

        if hasattr(self, "device_var"):
            try:
                normalized = self._get_global_training_device_choice()
                if self.device_var.get() != normalized:
                    self.device_var.set(normalized)
            except Exception:
                pass

        label = getattr(self, "train_device_hint_lbl", None)
        if label is not None:
            try:
                label.configure(text="")
                if str(label.winfo_manager()):
                    label.pack_forget()
            except Exception:
                pass
        try:
            self._refresh_training_recommendation_table()
        except Exception:
            pass

    @staticmethod
    def _is_history_run_resumable(run) -> bool:
        if run is None:
            return False
        status_value = str(getattr(run, "status", "") or "").strip().lower()
        if status_value not in {TrainingStatus.PAUSED.value, TrainingStatus.FAILED.value}:
            return False
        last_weights = str(getattr(run, "last_weights", "") or "").strip()
        return bool(last_weights and Path(last_weights).exists())

    def _get_latest_campaign_resumable_run_id(self) -> str:
        if not CAMPAIGN.get_active_project_name():
            return ""

        try:
            runs = list(self.history.get_all_runs() or [])
        except Exception:
            runs = []

        for run in runs:
            if not self._is_history_run_resumable(run):
                continue
            if not self._does_history_run_match_active_campaign_target(run):
                continue
            return str(getattr(run, "id", "") or "").strip()
        return ""

    def _is_history_run_resume_allowed(self, run) -> bool:
        if not self._is_history_run_resumable(run):
            return False
        if not self._does_history_run_match_active_campaign_target(run):
            return False
        if not CAMPAIGN.get_active_project_name():
            return True
        return bool(str(getattr(run, "id", "") or "").strip() == self._get_latest_campaign_resumable_run_id())

    def _format_history_run_status_label(self, run) -> str:
        if run is None:
            return "-"
        status_value = str(getattr(run, "status", "") or "").strip().lower()
        if status_value == TrainingStatus.PAUSED.value:
            if self._is_history_run_resume_allowed(run):
                return "paused (resume)"
            if self._is_history_run_resumable(run):
                return "paused (archiwalny)"
            return "paused (brak last.pt)"
        return str(getattr(run, "status", "-") or "-")

    def _does_history_run_match_active_campaign_target(self, run) -> bool:
        if run is None:
            return False
        if not CAMPAIGN.get_active_project_name():
            return True

        active_target = str(self.get_campaign_training_target() or CAMPAIGN.get_iteration_target() or "").strip().lower()
        if active_target not in {"char", "plate"}:
            return True

        run_target = ""
        try:
            infer_target = getattr(self.history, "_infer_run_target", None)
            if callable(infer_target):
                run_target = str(infer_target(run) or "").strip().lower()
        except Exception:
            run_target = ""
        if run_target not in {"char", "plate"}:
            try:
                run_target = str(
                    self._infer_dataset_target(getattr(run, "dataset_path", "")) or ""
                ).strip().lower()
            except Exception:
                run_target = ""
        return bool(run_target == active_target)

    def _device_to_ultralytics(self, device_str: str):
        effective_raw, _ = self._get_effective_training_device_profile(device_str)
        if effective_raw == "cpu":
            return "cpu"
        if effective_raw.startswith("cuda:"):
            try:
                return int(effective_raw.split(":")[1].split()[0])
            except Exception:
                return 0
        return "cpu"

    def _open_path(self, path: Path):
        try:
            if os.name == "nt": os.startfile(str(path))
            else: webbrowser.open(path.as_uri())
        except Exception as e:
            messagebox.showinfo("Info", f"Nie mogę otworzyć: {path}\n\n{e}")

    def _selected_run(self):
        sel = self.tree.selection()
        if not sel: 
            return None

        try:
            self._reload_history_snapshot_from_disk()
        except Exception:
            pass

        item_id = str(sel[0] or "").strip()
        if not item_id:
            return None

        run = self.history.get_run(item_id)
        if run is not None:
            return run

        # Fallback dla starszych wpisów / ewentualnych niespójności.
        for db_key, run_obj in self.history.runs.items():
            if str(db_key or "").strip() == item_id:
                return run_obj
        return None

    def _build_ui(self):


        # Główny notatnik powyżej paska pomocy
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 4))

        self.tab_dataset = ttk.Frame(self.main_nb)
        self.tab_train = ttk.Frame(self.main_nb)
        self.tab_val = None
        self.tab_ranking = None

        self.main_nb.add(self.tab_dataset, text="[PZ1] Budowa datasetu")
        self.main_nb.add(self.tab_train, text="[PZ2] Trening i wyniki")
        self.main_nb.bind("<<NotebookTabChanged>>", self._on_main_nb_tab_changed, add="+")
        self._step4_dataset_tab_visible = True

        self._build_dataset_tab()
        self._build_train_tab()
        self._update_step4_notebook_mode()

    def _on_main_nb_tab_changed(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.main_nb:
            return
        try:
            notify = getattr(self.app, "notify_free_mode_assistant_context_changed", None)
            if callable(notify):
                notify()
        except Exception:
            pass

    def get_free_mode_assistant_context(self) -> dict:
        try:
            selected_tab = str(self.main_nb.select())
        except Exception:
            selected_tab = ""

        if selected_tab == str(getattr(self, "tab_dataset", "")):
            return {
                "location": "[Z4] Trening i analiza / [PZ1] Budowa datasetu",
                "goal": "Ta podzakładka przygotowuje split treningowy dostępny później w PZ2.",
                "workflow": (
                    "Wybierz tor: tablice YOLO Pose albo znaki YOLO Detect.",
                    "Wskaż właściwe źródło: dla tablic XML + zgodne obrazy albo gotowy wariant, dla znaków dataset YOLO z data.yaml.",
                    "Utwórz split treningowy. PZ2 pracuje na gotowych splitach.",
                    "Po sukcesie przeczytaj modal i przejdź do PZ2, gdzie split pojawi się na liście wyboru.",
                ),
                "glossary": (
                    "wariant = konkretna wersja datasetu",
                    "split = train / val / test",
                    "data.yaml = opis datasetu YOLO",
                ),
                "caution": "W trybie swobodnym warto testować różne warianty bez ponownego eksportu z Z2/Z3.",
            }
        if selected_tab == str(getattr(self, "tab_train", "")):
            return {
                "location": "[Z4] Trening i analiza / [PZ2] Trening i wyniki",
                "goal": "Ta podzakładka korzysta ze splitu przygotowanego w PZ1, wybiera model bazowy i uruchamia trening oraz porównanie wyników.",
                "workflow": (
                    "Wybierz split zgodny z aktualnym torem.",
                    "Wybierz model bazowy albo checkpoint zgodny z torem tablic lub znaków.",
                    "Ustaw parametry startowe: epoki, batch, rozdzielczość, learning rate i urządzenie.",
                    "Uruchom trening i obserwuj postęp oraz terminal procesu.",
                    "Po treningu sprawdź historię runów, wykonaj walidację lub porównaj wyniki w rankingu.",
                ),
                "glossary": (
                    "epoka = pełne przejście po danych",
                    "val = walidacja jakości",
                    "ranking = porównanie modeli",
                ),
                "caution": "Jeśli trening ma używać innego splitu, wróć do PZ1 i wybierz albo utwórz inny wariant.",
            }
        return {
            "location": "[Z4] Trening i analiza",
            "goal": "Ta zakładka prowadzi od przygotowania splitu do treningu modelu i analizy wyników.",
            "workflow": (
                "PZ1 buduje lub wybiera split zgodny z aktualnym torem.",
                "PZ2 używa tego splitu do treningu, walidacji i porównania modeli.",
                "Jeśli chcesz testować inny split, wróć do PZ1 i utwórz kolejny wariant.",
            ),
            "glossary": ("PZ1 = budowa datasetu", "PZ2 = trening i wyniki", "ranking = porównanie modeli"),
            "caution": "PZ2 trenuje na splicie wybranym z listy. Nowe splity przygotowuje PZ1.",
        }

    def _build_dataset_tab(self):
        root = ttk.Frame(self.tab_dataset, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.BOTH, expand=True)

        self.step4_route_panel_frame = tk.Frame(top, bd=0, highlightthickness=1)
        self.step4_route_panel_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        self.step4_dataset_top = top

        left = ttk.LabelFrame(self.step4_route_panel_frame, text=" Wybór ścieżki treningowej ", padding=10)
        left.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            left,
            text="Najpierw wybierz, który model chcesz prowadzić w tej iteracji.",
            font=("Segoe UI", 9),
            wraplength=240,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 12))

        self._step4_route_choice_cards = {}
        route_palette = getattr(self.app, "palette", {})
        route_initial_badge_bg = route_palette.get("panel", "#252526")
        route_initial_badge_fg = route_palette.get("muted", "#c7c7c7")
        route_initial_badge_border = route_palette.get("panel_border", route_palette.get("border", "#3c3c3c"))

        self.step4_plate_route_card = tk.Frame(left, bd=0, highlightthickness=1, padx=10, pady=8)
        self.step4_plate_route_card.pack(fill=tk.X, pady=(0, 10))
        self.step4_plate_route_title_row = tk.Frame(self.step4_plate_route_card, bd=0, highlightthickness=0)
        self.step4_plate_route_title_row.pack(fill=tk.X)
        self.step4_plate_route_title_lbl = tk.Label(
            self.step4_plate_route_title_row,
            text="Tor tablic",
            font=("Segoe UI Semibold", 10),
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        self.step4_plate_route_title_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.step4_plate_route_badge_lbl = tk.Label(
            self.step4_plate_route_title_row,
            text="DO WYBORU",
            font=("Segoe UI", 8, "bold"),
            width=10,
            anchor=tk.CENTER,
            padx=7,
            pady=2,
            bd=0,
            highlightthickness=1,
            bg=route_initial_badge_bg,
            fg=route_initial_badge_fg,
            highlightbackground=route_initial_badge_border,
            highlightcolor=route_initial_badge_border,
        )
        self.step4_plate_route_badge_lbl.pack(side=tk.RIGHT, padx=(6, 0))
        self.step4_plate_route_desc_lbl = tk.Label(
            self.step4_plate_route_card,
            text="YOLO Pose. Dataset tablic może pochodzić z eksportu Z2 albo z alternatywnego kreatora XML.",
            wraplength=220,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        self.step4_plate_route_desc_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self.btn_choose_plate = ttk.Button(
            left,
            text="Wybierz tor tablic",
            command=lambda: self._set_step4_dataset_mode("plate")
        )

        self.step4_char_route_card = tk.Frame(left, bd=0, highlightthickness=1, padx=10, pady=8)
        self.step4_char_route_card.pack(fill=tk.X)
        self.step4_char_route_title_row = tk.Frame(self.step4_char_route_card, bd=0, highlightthickness=0)
        self.step4_char_route_title_row.pack(fill=tk.X)
        self.step4_char_route_title_lbl = tk.Label(
            self.step4_char_route_title_row,
            text="Tor znaków",
            font=("Segoe UI Semibold", 10),
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        self.step4_char_route_title_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.step4_char_route_badge_lbl = tk.Label(
            self.step4_char_route_title_row,
            text="DO WYBORU",
            font=("Segoe UI", 8, "bold"),
            width=10,
            anchor=tk.CENTER,
            padx=7,
            pady=2,
            bd=0,
            highlightthickness=1,
            bg=route_initial_badge_bg,
            fg=route_initial_badge_fg,
            highlightbackground=route_initial_badge_border,
            highlightcolor=route_initial_badge_border,
        )
        self.step4_char_route_badge_lbl.pack(side=tk.RIGHT, padx=(6, 0))
        self.step4_char_route_desc_lbl = tk.Label(
            self.step4_char_route_card,
            text="YOLO Detect. Split gotowego datasetu znaków i trening modelu rozpoznającego znaki.",
            wraplength=220,
            justify=tk.LEFT,
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        self.step4_char_route_desc_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))
        self.btn_choose_char = ttk.Button(
            left,
            text="Wybierz tor znaków",
            command=lambda: self._set_step4_dataset_mode("char")
        )

        self._step4_route_choice_cards = {
            "plate": {
                "frame": self.step4_plate_route_card,
                "title_row": self.step4_plate_route_title_row,
                "title": self.step4_plate_route_title_lbl,
                "badge": self.step4_plate_route_badge_lbl,
                "desc": self.step4_plate_route_desc_lbl,
            },
            "char": {
                "frame": self.step4_char_route_card,
                "title_row": self.step4_char_route_title_row,
                "title": self.step4_char_route_title_lbl,
                "badge": self.step4_char_route_badge_lbl,
                "desc": self.step4_char_route_desc_lbl,
            },
        }
        for route_mode, widgets in self._step4_route_choice_cards.items():
            for widget in widgets.values():
                try:
                    widget.configure(cursor="hand2")
                except Exception:
                    pass
                try:
                    widget.bind("<Button-1>", lambda _event, mode=route_mode: self._set_step4_dataset_mode(mode), add="+")
                except Exception:
                    pass

        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.step4_mode_right_host = right

        header = ttk.LabelFrame(right, text=" Aktywny tor ", padding=10)
        header.pack(fill=tk.X)

        self.ds_mode_title_var = tk.StringVar(value="Tor znaków (YOLO Detect)")
        self.ds_mode_desc_var = tk.StringVar(value="")

        ttk.Label(
            header,
            textvariable=self.ds_mode_title_var,
            font=("Segoe UI", 11, "bold")
        ).pack(anchor=tk.W)

        ttk.Label(
            header,
            textvariable=self.ds_mode_desc_var,
            wraplength=700,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(6, 0))

        summary_palette = getattr(self.app, "palette", {})
        summary_panel = summary_palette.get("panel", "#252526")
        summary_border = summary_palette.get("panel_border", summary_palette.get("border", "#3c3c3c"))
        self.step4_dataset_summary_frame = tk.Frame(
            right,
            bd=0,
            highlightthickness=1,
            padx=10,
            pady=8,
            bg=summary_panel,
            highlightbackground=summary_border,
            highlightcolor=summary_border,
        )
        self.step4_dataset_summary_frame.pack(fill=tk.X, pady=(8, 0))
        self.step4_dataset_summary_title_lbl = tk.Label(
            self.step4_dataset_summary_frame,
            text="Podsumowanie splitu",
            font=("Segoe UI Semibold", 10),
            anchor="w",
            bd=0,
            highlightthickness=0,
            bg=summary_panel,
        )
        self.step4_dataset_summary_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        self.step4_dataset_summary_grid = tk.Frame(
            self.step4_dataset_summary_frame,
            bd=0,
            highlightthickness=0,
            bg=summary_panel,
        )
        self.step4_dataset_summary_grid.pack(fill=tk.X)
        self.step4_dataset_summary_grid.grid_columnconfigure(0, weight=0, minsize=130)
        self.step4_dataset_summary_grid.grid_columnconfigure(1, weight=1)

        self._step4_dataset_summary_header_widgets = []
        self._step4_dataset_summary_rows = {}
        for column, text in enumerate(("Parametr", "Wartość")):
            header_cell = tk.Label(
                self.step4_dataset_summary_grid,
                text=text,
                font=("Segoe UI Semibold", 8),
                padx=8,
                pady=4,
                anchor="w",
                bd=0,
                highlightthickness=1,
            )
            header_cell.grid(row=0, column=column, sticky="nsew")
            self._step4_dataset_summary_header_widgets.append(header_cell)

        summary_rows = (
            ("status", "Status"),
            ("target", "Tor"),
            ("source", "Pochodzenie"),
            ("path", "Folder"),
            ("yaml", "data.yaml"),
            ("split", "Split"),
            ("total", "Razem"),
        )
        for row_index, (key, label_text) in enumerate(summary_rows, start=1):
            label_cell = tk.Label(
                self.step4_dataset_summary_grid,
                text=label_text,
                font=("Segoe UI", 8),
                padx=8,
                pady=4,
                anchor="w",
                bd=0,
                highlightthickness=1,
            )
            label_cell.grid(row=row_index, column=0, sticky="nsew")
            if key == "split":
                value_cell = tk.Canvas(
                    self.step4_dataset_summary_grid,
                    height=30,
                    bd=0,
                    highlightthickness=1,
                )
                value_cell.bind(
                    "<Configure>",
                    lambda _event, canvas=value_cell: self._draw_step4_dataset_split_bar(canvas),
                    add="+",
                )
            else:
                value_cell = tk.Label(
                    self.step4_dataset_summary_grid,
                    text="-",
                    font=("Segoe UI", 8),
                    padx=8,
                    pady=4,
                    anchor="w",
                    justify=tk.LEFT,
                    bd=0,
                    highlightthickness=1,
                )
            value_cell.grid(row=row_index, column=1, sticky="nsew")
            self._step4_dataset_summary_rows[key] = (label_cell, value_cell)
        if CAMPAIGN.get_active_project_name():
            try:
                self.step4_dataset_summary_frame.pack_forget()
            except Exception:
                pass

        self.ds_mode_scroll_host = ttk.Frame(right)
        self.ds_mode_scroll_host.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.ds_mode_scroll_host.grid_rowconfigure(0, weight=1)
        self.ds_mode_scroll_host.grid_columnconfigure(0, weight=1)

        palette = getattr(self.app, "palette", {})
        self.ds_mode_canvas = tk.Canvas(
            self.ds_mode_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
        )
        self.ds_mode_canvas.grid(row=0, column=0, sticky="nsew")

        self.ds_mode_scrollbar = WebSlimScrollbar(
            self.ds_mode_scroll_host,
            command=self.ds_mode_canvas.yview,
        )
        self.ds_mode_scrollbar.grid(row=0, column=1, sticky="ns")
        self.ds_mode_canvas.configure(yscrollcommand=self.ds_mode_scrollbar.set)

        self.ds_mode_host = ttk.Frame(self.ds_mode_canvas)
        self.ds_mode_host_window = self.ds_mode_canvas.create_window(
            (0, 0),
            window=self.ds_mode_host,
            anchor="nw",
        )
        self.ds_mode_host.bind("<Configure>", self._sync_dataset_mode_scrollregion, add="+")
        self.ds_mode_canvas.bind("<Configure>", self._sync_dataset_mode_canvas_width, add="+")

        self.ds_mode_waiting_frame = ttk.LabelFrame(
            self.ds_mode_host,
            text=" Oczekiwanie na wybór toru ",
            padding=18
        )
        ttk.Label(
            self.ds_mode_waiting_frame,
            text=(
                "Panel zostanie odblokowany po wyborze toru po lewej stronie.\n\n"
                "W trybie projektu najpierw wskaż, czy chcesz prowadzić tor tablic, czy tor znaków."
            ),
            foreground="gray",
            justify=tk.LEFT,
            wraplength=520
        ).pack(anchor=tk.W)

        self.ds_creator_frame = ttk.LabelFrame(
            self.ds_mode_host,
            text=" Budowa datasetu tablic (YOLO Pose) ",
            padding=10
        )
        self.ds_split_frame = ttk.LabelFrame(
            self.ds_mode_host,
            text=" Przygotowanie datasetu znaków (YOLO Detect) ",
            padding=10
        )

        self.train_pct = tk.DoubleVar(value=80.0)
        self.val_pct = tk.DoubleVar(value=10.0)

        self._build_creator_ui()
        self._build_splitter_ui()
        self._bind_scroll_canvas_children(self.ds_mode_host, self.ds_mode_canvas)
        try:
            self.ds_mode_canvas.bind(
                "<MouseWheel>",
                lambda event, canvas=self.ds_mode_canvas: self._redirect_child_mousewheel_to_canvas(event, canvas),
                add="+",
            )
            self.ds_mode_canvas.bind(
                "<Button-4>",
                lambda event, canvas=self.ds_mode_canvas: self._redirect_child_mousewheel_to_canvas(event, canvas),
                add="+",
            )
            self.ds_mode_canvas.bind(
                "<Button-5>",
                lambda event, canvas=self.ds_mode_canvas: self._redirect_child_mousewheel_to_canvas(event, canvas),
                add="+",
            )
        except Exception:
            pass
        try:
            self.frame.bind_all("<MouseWheel>", self._on_dataset_mode_global_mousewheel, add="+")
            self.frame.bind_all("<Button-4>", self._on_dataset_mode_global_mousewheel, add="+")
            self.frame.bind_all("<Button-5>", self._on_dataset_mode_global_mousewheel, add="+")
        except Exception:
            pass

        self.step4_builder_log_frame = ttk.LabelFrame(root, text=" Terminal procesu ", padding=6)
        self.step4_builder_log_toolbar = ttk.Frame(self.step4_builder_log_frame)
        self.step4_builder_log_toolbar.pack(fill=tk.X, pady=(0, 6))

        self.btn_hide_step4_log = ttk.Button(
            self.step4_builder_log_toolbar,
            text="Ukryj terminal",
            command=self._toggle_step4_builder_log
        )
        self.btn_hide_step4_log.pack(side=tk.LEFT)

        self.step4_builder_log_host = ttk.Frame(self.step4_builder_log_frame, style="Panel.TFrame")
        self.step4_builder_log_host.pack(fill=tk.BOTH, expand=True)

        self.step4_builder_log_text = tk.Text(
            self.step4_builder_log_host,
            wrap=tk.WORD,
            height=10,
            font=("Consolas", 10),
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.step4_builder_log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.step4_builder_log_scrollbar = WebSlimScrollbar(
            self.step4_builder_log_host,
            orient=tk.VERTICAL,
            command=self.step4_builder_log_text.yview,
            auto_hide=False,
        )
        self.step4_builder_log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.step4_builder_log_text.configure(yscrollcommand=self.step4_builder_log_scrollbar.set)
        self.step4_builder_log_text.web_vbar = self.step4_builder_log_scrollbar
        self.step4_builder_log_text.configure(state=tk.DISABLED)

        self.step4_builder_tools = ttk.Frame(root)
        self.step4_builder_tools.pack_forget()

        self.step4_builder_nav = ttk.Frame(root)
        self.step4_builder_nav.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0), before=self.step4_dataset_top)
        self.step4_builder_nav.grid_columnconfigure(0, weight=0)
        self.step4_builder_nav.grid_columnconfigure(1, weight=1)
        self.step4_builder_nav.grid_columnconfigure(2, weight=0)

        self.btn_step4_back = ttk.Button(
            self.step4_builder_nav,
            text="Wstecz",
            command=self._step4_dataset_go_back,
            style="WorkflowCard.TButton"
        )
        self.btn_step4_back.grid(row=0, column=0, sticky="w")
        self.btn_step4_back.configure(padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self.btn_toggle_step4_log = ttk.Button(
            self.step4_builder_tools,
            text="Pokaż terminal",
            command=self._toggle_step4_builder_log
        )
        self.btn_toggle_step4_log.pack_forget()

        self.btn_step4_next_frame = tk.Frame(self.step4_builder_nav, bd=0, highlightthickness=0)
        self.btn_step4_next_frame.grid(row=0, column=2, sticky="e", padx=(10, 0))

        self.btn_step4_next = ttk.Button(
            self.btn_step4_next_frame,
            text="Dalej: Trening i analiza modelu znaków",
            command=self._step4_dataset_go_next,
            style="Accent.TButton"
        )
        self.btn_step4_next.pack()
        self.btn_step4_next.configure(text="Dalej do treningu", padding=(8, 2), width=NAV_BUTTON_WIDTH)

        HELP.bind_help(self.step4_route_panel_frame, "tr_route_panel")
        HELP.bind_help(self.step4_plate_route_card, "tr_route_plate")
        HELP.bind_help(self.step4_char_route_card, "tr_route_char")
        HELP.bind_help(self.btn_choose_plate, "tr_route_plate")
        HELP.bind_help(self.btn_choose_char, "tr_route_char")
        HELP.bind_help(self.btn_toggle_step4_log, "tr_builder_log")
        HELP.bind_help(self.btn_hide_step4_log, "tr_builder_log")
        HELP.bind_help(self.btn_step4_next, "tr_builder_next")

        initial_mode = self.get_campaign_training_target()
        if initial_mode not in ("char", "plate"):
            initial_mode = "char"

        self._step4_builder_log_visible = False
        self._step4_route_selected = True
        self._step4_train_unlocked = True
        self._set_step4_builder_log_visibility(False)
        self._set_step4_dataset_mode(initial_mode, show_locked_message=False)
        try:
            self.frame.after_idle(self._refresh_step4_dataset_mode_ui)
            self.frame.after(80, self._refresh_step4_dataset_mode_ui)
        except Exception:
            pass

    def _build_creator_ui(self):
        f = self.ds_creator_frame
        palette = getattr(self.app, "palette", {})
        self.creator_intro_lbl = ttk.Label(
            f,
            text=(
                "Utwórz wariant splitu wybranego datasetu tablic, który został wyprodukowany w Z2."
            ),
            font=("Segoe UI", 9),
            wraplength=720,
            justify=tk.LEFT,
        )
        self.creator_intro_lbl.pack(anchor=tk.W, pady=(0, 10))

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

        creator_ratios = ttk.Frame(f)
        self.creator_ratios_frame = creator_ratios
        creator_ratios.pack(fill=tk.X, pady=10)
        ttk.Label(creator_ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
        ttk.Scale(
            creator_ratios,
            from_=50,
            to=90,
            variable=self.train_pct,
            command=lambda e: self._update_ratio_labels(),
        ).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.creator_train_lbl = ttk.Label(creator_ratios, text="80%")
        self.creator_train_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(creator_ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
        ttk.Scale(
            creator_ratios,
            from_=5,
            to=50,
            variable=self.val_pct,
            command=lambda e: self._update_ratio_labels(),
        ).grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.creator_val_lbl = ttk.Label(creator_ratios, text="10%")
        self.creator_val_lbl.grid(row=1, column=2, sticky=tk.W)

        ttk.Label(creator_ratios, text="Test %").grid(row=2, column=0, sticky=tk.W)
        ttk.Label(creator_ratios, text="liczony automatycznie").grid(row=2, column=1, sticky=tk.W, padx=5)
        self.creator_test_lbl = ttk.Label(creator_ratios, text="Test: 10%")
        self.creator_test_lbl.grid(row=2, column=2, sticky=tk.W)
        creator_ratios.columnconfigure(1, weight=1)

        self.btn_step4_create_frame = tk.Frame(f, bd=0, highlightthickness=0)
        self.btn_step4_create_frame.pack(anchor=tk.W, pady=(10, 5))

        self.btn_step4_create = ttk.Button(
            self.btn_step4_create_frame,
            text="Utwórz split treningowy",
            command=self._create_dataset_thread
        )
        self.btn_step4_create.pack(anchor=tk.W)
        
        self.ds_progress_var = tk.DoubleVar(value=0.0)
        self.ds_progress = TrainProgressBar(
            f,
            variable=self.ds_progress_var,
            maximum=100,
            thickness=6,
            trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
            fill_color=palette.get("success", "#2ecc71"),
            bg=palette.get("panel", "#252526"),
            height=10,
        )
        self.ds_progress.pack(fill=tk.X, pady=2)
        
        self.ds_status = ttk.Label(f, text="Gotowy", style="TrainSplitSuccess.TLabel")
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
            text="Utwórz wariant splitu wybranego datasetu znaków, który został wyprodukowany w Z3/PZ2.",
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
        
        ratios = ttk.Frame(f); ratios.pack(fill=tk.X, pady=10)
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

        self.btn_step4_split_frame = tk.Frame(f, bd=0, highlightthickness=0)
        self.btn_step4_split_frame.pack(anchor=tk.W, pady=10)

        self.btn_step4_split = ttk.Button(
            self.btn_step4_split_frame,
            text="Utwórz split treningowy",
            command=self._split_dataset_thread,
            style="Accent.TButton"
        )
        self.btn_step4_split.pack()
        
        self.split_progress_var = tk.DoubleVar(value=0.0)
        self.split_feedback_frame = ttk.Frame(f)
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

    def _build_train_tab(self):
        palette = getattr(self.app, "palette", {})
        root = ttk.Frame(self.tab_train, padding=5)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.train_pane = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.train_pane.grid(row=0, column=0, sticky="nsew")

        self.left = ttk.LabelFrame(self.train_pane, text=" Trening ", padding=9)
        self.right = ttk.LabelFrame(self.train_pane, text=" Wyniki i narzedzia ", padding=8)
        self.train_pane.add(self.left, weight=6)
        self.train_pane.add(self.right, weight=7)

        self.left.grid_rowconfigure(0, weight=1)
        self.left.grid_columnconfigure(0, weight=1)

        self.train_left_scroll_host = ttk.Frame(self.left, style="Panel.TFrame")
        self.train_left_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.train_left_scroll_host.grid_rowconfigure(0, weight=1)
        self.train_left_scroll_host.grid_columnconfigure(0, weight=1)

        self.train_left_canvas = tk.Canvas(
            self.train_left_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.train_left_canvas.grid(row=0, column=0, sticky="nsew")

        self.train_left_scrollbar = WebSlimScrollbar(
            self.train_left_scroll_host,
            command=self.train_left_canvas.yview
        )
        self.train_left_scrollbar.grid(row=0, column=1, sticky="ns")
        self.train_left_canvas.configure(yscrollcommand=self.train_left_scrollbar.set)

        self._train_left_content_inset = 14
        self._train_left_hint_inset = 10
        self._train_left_section_gap = 12
        self._train_left_content_max_width = 660
        self.train_left_content = ttk.Frame(self.train_left_canvas, style="Panel.TFrame")
        self.train_left_content.grid_columnconfigure(0, weight=1)
        self.train_left_content_window = self.train_left_canvas.create_window(
            (self._train_left_content_inset, 0),
            window=self.train_left_content,
            anchor="nw"
        )
        self.train_left_content.bind("<Configure>", self._sync_train_left_scrollregion, add="+")
        self.train_left_canvas.bind("<Configure>", self._sync_train_left_canvas_width, add="+")

        self.train_left_settings_col = ttk.Frame(self.train_left_content, style="Panel.TFrame")
        settings_col = self.train_left_settings_col
        settings_col.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        self.free_training_route_host = ttk.LabelFrame(settings_col, text=" ", padding=12)
        self.free_training_route_title_lbl = SectionHeaderLabel(
            self.free_training_route_host,
            self.app,
            text="Wejście treningowe",
            fade_ratio=0.74,
        )
        self.free_training_route_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        route_intro = ttk.Label(
            self.free_training_route_host,
            text=(
                "Trening korzysta z aktywnego wariantu datasetu."
            ),
            style="PanelMuted.TLabel",
            wraplength=360,
            justify=tk.LEFT
        )
        self.free_training_route_intro_lbl = route_intro
        route_intro.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))
        self._register_train_left_wrap_target(
            route_intro,
            container=self.free_training_route_host,
            padding=28,
            min_wrap=220,
        )

        self.training_input_summary_frame = tk.Frame(
            self.free_training_route_host,
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=8,
        )
        self.training_input_summary_frame.pack(fill=tk.X, pady=(0, 8))
        self.training_input_badge_lbl = tk.Label(
            self.training_input_summary_frame,
            text="PZ1",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
            bd=0,
            highlightthickness=1,
        )
        self.training_input_badge_lbl.pack(anchor=tk.W)
        self.training_input_route_lbl = tk.Label(
            self.training_input_summary_frame,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=340,
            bd=0,
            highlightthickness=0,
        )
        self.training_input_route_lbl.pack(anchor=tk.W, fill=tk.X, pady=(7, 0))
        self.training_input_dataset_lbl = tk.Label(
            self.training_input_summary_frame,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=340,
            bd=0,
            highlightthickness=0,
        )
        self.training_input_dataset_lbl.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))
        self.training_input_source_lbl = tk.Label(
            self.training_input_summary_frame,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=340,
            bd=0,
            highlightthickness=0,
        )
        self.training_input_source_lbl.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))
        self.training_input_change_btn = ttk.Button(
            self.training_input_summary_frame,
            text="Wróć do PZ1",
            command=self._open_step4_dataset_stage,
        )
        for summary_label in (
            self.training_input_route_lbl,
            self.training_input_dataset_lbl,
            self.training_input_source_lbl,
        ):
            self._register_train_left_wrap_target(
                summary_label,
                container=self.training_input_summary_frame,
                padding=24,
                min_wrap=180,
            )

        self.free_training_route_cards_row = tk.Frame(self.free_training_route_host, bd=0, highlightthickness=0)
        self.free_training_route_cards_row.pack_forget()
        self.free_training_route_cards_row.grid_columnconfigure(0, weight=1)
        self.free_training_route_cards_row.grid_columnconfigure(1, weight=1)

        route_specs = (
            (
                "plate",
                "Tablice",
                "YOLO Pose",
                "Model tablic z geometrią rogów.",
                "Dataset z Z2",
            ),
            (
                "char",
                "Znaki tablic",
                "YOLO Detect",
                "Model znaków na wyciętych tablicach.",
                "Dataset z Z3/PZ3",
            ),
        )
        self._free_training_route_cards = {}
        for column, (mode, title_text, badge_text, desc_text, meta_text) in enumerate(route_specs):
            card = tk.Frame(self.free_training_route_cards_row, bd=0, highlightthickness=1, padx=14, pady=12)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6 if column == 0 else 0))

            title = tk.Label(card, text=title_text, font=("Segoe UI Semibold", 11), anchor="w", bd=0, highlightthickness=0)
            title.pack(anchor=tk.W)
            badge_row = tk.Frame(card, bd=0, highlightthickness=0)
            badge_row.pack(anchor=tk.W, fill=tk.X, pady=(8, 8))
            badge = tk.Label(
                badge_row,
                text=badge_text,
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=2,
                bd=0,
                highlightthickness=1,
            )
            badge.pack(side=tk.LEFT)
            choice_badge = tk.Label(
                badge_row,
                text="DO WYBORU",
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=2,
                bd=0,
                highlightthickness=1,
            )
            choice_badge.pack(side=tk.LEFT, padx=(6, 0))
            desc = tk.Label(card, text=desc_text, justify=tk.LEFT, anchor="w", wraplength=140, bd=0, highlightthickness=0)
            desc.pack(anchor=tk.W, fill=tk.X)
            meta = tk.Label(card, text=meta_text, justify=tk.LEFT, anchor="w", wraplength=140, bd=0, highlightthickness=0)
            meta.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))
            self._register_train_left_wrap_target(desc, container=card, padding=30, min_wrap=120)
            self._register_train_left_wrap_target(meta, container=card, padding=30, min_wrap=120)

            for widget in (card, title, badge_row, badge, choice_badge, desc, meta):
                self._bind_training_route_card(widget, mode)

            self._free_training_route_cards[mode] = {
                "frame": card,
                "title": title,
                "badge_row": badge_row,
                "badge": badge,
                "choice_badge": choice_badge,
                "desc": desc,
                "meta": meta,
            }
            try:
                HELP.bind_help(card, "tr_route_plate" if mode == "plate" else "tr_route_char")
            except Exception:
                pass

        self.train_session_name_row = ttk.Frame(settings_col, style="Panel.TFrame")
        self.train_session_name_row.pack(fill=tk.X, pady=(0, self._train_left_section_gap))
        ttk.Label(self.train_session_name_row, text="Nazwa sesji treningowej:", style="Panel.TLabel").pack(anchor=tk.W, fill=tk.X)
        self.name_var = tk.StringVar()
        ttk.Entry(self.train_session_name_row, textvariable=self.name_var, width=35).pack(fill=tk.X, pady=2)
        self._build_train_left_separator(settings_col, pady=(0, self._train_left_section_gap))

        self.train_dataset_section_frame = ttk.LabelFrame(
            settings_col,
            text=" Dataset treningowy ",
            padding=8,
        )
        self.train_dataset_section_frame.pack(fill=tk.X, pady=(0, self._train_left_section_gap))

        self.train_dataset_title_lbl = tk.Label(
            self.train_dataset_section_frame,
            text="Wybór splitu",
            font=("Segoe UI Semibold", 10),
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        self.train_dataset_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))
        self.train_dataset_required_lbl = ttk.Label(
            self.train_dataset_section_frame,
            text="",
            style="Panel.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360,
        )
        self._register_train_left_wrap_target(self.train_dataset_required_lbl, padding=16, min_wrap=220)
        self.train_dataset_caption_lbl = ttk.Label(
            self.train_dataset_section_frame,
            text="Wybierz split do treningu. Nowy split przygotujesz w PZ1.",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self.train_dataset_caption_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 4))
        self._register_train_left_wrap_target(self.train_dataset_caption_lbl, padding=16, min_wrap=220)
        self.dataset_var = tk.StringVar()
        self.train_dataset_path_lbl = ttk.Label(
            self.train_dataset_section_frame,
            text="Ścieżka gotowego datasetu:",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
        )
        ds_row = ttk.Frame(self.train_dataset_section_frame, style="Panel.TFrame")
        self.train_dataset_row = ds_row
        # PZ2 przechowuje dataset_var wewnętrznie, ale użytkownik wybiera już tylko gotowe warianty z comboboxa.
        self.train_dataset_entry = ttk.Entry(ds_row, textvariable=self.dataset_var)
        self.train_dataset_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.train_dataset_pick_btn = ttk.Button(ds_row, text="Folder datasetu", command=self._pick_training_dataset_dir)
        self.train_dataset_yaml_btn = ttk.Button(ds_row, text="Plik data.yaml", command=self._pick_training_dataset_yaml)

        self.dataset_variant_row = ttk.Frame(self.train_dataset_section_frame, style="Panel.TFrame")
        self.dataset_variant_row.pack(fill=tk.X, pady=(4, 2))
        self.dataset_variant_title_lbl = ttk.Label(
            self.dataset_variant_row,
            text="Dostępne splity:",
            style="PanelMuted.TLabel",
        )
        self.dataset_variant_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.dataset_variant_caption_lbl = ttk.Label(
            self.dataset_variant_row,
            text="",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=340,
        )
        self._register_train_left_wrap_target(self.dataset_variant_caption_lbl, padding=16, min_wrap=220)
        self.dataset_variant_var = tk.StringVar()
        self.dataset_variant_combo = ttk.Combobox(
            self.dataset_variant_row,
            textvariable=self.dataset_variant_var,
            state="readonly",
            values=[],
        )
        self.dataset_variant_combo.pack(fill=tk.X, pady=(2, 0))
        self.dataset_variant_combo.bind("<<ComboboxSelected>>", self._on_dataset_variant_selected)
        self.dataset_variant_refresh_btn = ttk.Button(
            self.dataset_variant_row,
            text="",
            command=self._refresh_dataset_variant_choices,
        )

        self.train_dataset_hint_lbl = ttk.Label(
            self.train_dataset_section_frame,
            text="",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=320
        )
        self._register_train_left_wrap_target(
            self.train_dataset_hint_lbl,
            padding=16,
            min_wrap=220,
        )
        self.train_dataset_hint_lbl.bind("<Configure>", self._update_training_dataset_hint_wraplength, add="+")

        self.train_dataset_quality_shell = tk.Frame(
            self.train_dataset_section_frame,
            bd=0,
            highlightthickness=1,
        )
        self.train_dataset_quality_shell.pack(anchor=tk.W, fill=tk.X, pady=(2, 8))
        self.train_dataset_quality_grid = tk.Frame(
            self.train_dataset_quality_shell,
            bd=0,
            highlightthickness=0,
        )
        self.train_dataset_quality_grid.pack(fill=tk.X, padx=1, pady=1)
        self.train_dataset_quality_grid.grid_columnconfigure(0, weight=0, minsize=112)
        self.train_dataset_quality_grid.grid_columnconfigure(1, weight=1)
        self.train_dataset_quality_title_row = tk.Frame(
            self.train_dataset_quality_grid,
            bd=0,
            highlightthickness=0,
        )
        self.train_dataset_quality_title_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(0, 1), pady=(0, 1))
        self.train_dataset_quality_title_lbl = tk.Label(
            self.train_dataset_quality_title_row,
            text="Czy dataset ma sens?",
            font=("Segoe UI", 8, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=4,
        )
        self.train_dataset_quality_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._train_dataset_quality_row_widgets = []

        self.train_scope_hint_lbl = ttk.Label(
            settings_col,
            text="",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self.train_scope_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, self._train_left_section_gap))
        self._register_train_left_wrap_target(self.train_scope_hint_lbl, padding=16, min_wrap=220)

        self.train_pose_warning_lbl = ttk.Label(
            settings_col,
            text="",
            style="PanelStatusWarning.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self._register_train_left_wrap_target(self.train_pose_warning_lbl, padding=16, min_wrap=220)

        self._update_training_dataset_hint()
        self._refresh_free_training_route_ui()

        self._build_train_left_separator(settings_col, pady=(0, self._train_left_section_gap))

        self.train_base_title_lbl = tk.Label(
            settings_col,
            text="Model bazowy (.pt)",
            font=("Segoe UI Semibold", 10),
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        self.train_base_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))
        self.train_base_caption_lbl = ttk.Label(
            settings_col,
            text="Wybierz model zgodny z torem: tablice = Pose, znaki = Detect.",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self.train_base_caption_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 6))
        self._register_train_left_wrap_target(self.train_base_caption_lbl, padding=16, min_wrap=220)
        self.base_model_var = tk.StringVar()
        
        base_values = list(AVAILABLE_DETECT_MODELS.keys()) + list(AVAILABLE_POSE_MODELS.keys()) + ["Custom"]
        
        self.base_combo = ttk.Combobox(settings_col, textvariable=self.base_model_var, values=base_values, state="readonly")
        self.base_combo.pack(fill=tk.X, pady=2)
        self.base_model_var.set("yolo11n.pt") 
        self.base_combo.bind("<<ComboboxSelected>>", lambda e: self._on_base_model_change())

        # Pozwól wskazać własny model do fine-tuningu z katalogu modeli.
        self.base_custom_var = tk.StringVar()
        self.custom_row = ttk.Frame(settings_col, style="Panel.TFrame")
        self.custom_row.pack(fill=tk.X, pady=2)
        
        self.base_custom_entry = ttk.Entry(self.custom_row, textvariable=self.base_custom_var, state=tk.DISABLED)
        self.base_custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.base_custom_btn = ttk.Button(
            self.custom_row,
            text="Wybierz .pt",
            state=tk.DISABLED,
            command=self._pick_base_custom_model
        )
        self.base_custom_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.train_base_identity_lbl = ttk.Label(
            settings_col,
            text="",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360,
        )
        self._register_train_left_wrap_target(self.train_base_identity_lbl, padding=16, min_wrap=220)

        def auto_name(*args):
            ds_name = Path(self.dataset_var.get()).name if self.dataset_var.get() else "UnknownDS"
            model_name = self.base_model_var.get()
            if model_name == "Custom": model_name = Path(self.base_custom_var.get()).stem if self.base_custom_var.get() else "Custom"
            import datetime
            ts = datetime.datetime.now().strftime("%d%b_%H%M")
            self.name_var.set(f"Train_{model_name}_{ds_name}_{ts}")

        self.dataset_var.trace_add("write", auto_name)
        self.base_model_var.trace_add("write", auto_name)
        self.base_custom_var.trace_add("write", auto_name)
        self.dataset_var.trace_add("write", lambda *args: self._update_training_dataset_hint())
        self.dataset_var.trace_add("write", lambda *args: self._refresh_training_start_state())
        self.dataset_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.dataset_var.trace_add("write", lambda *args: self._refresh_step4_dataset_mode_ui())
        self.dataset_var.trace_add("write", lambda *args: self._sync_dataset_variant_selection())
        self.base_model_var.trace_add("write", self._on_training_base_model_value_write)
        self.base_model_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.base_custom_var.trace_add("write", self._on_training_base_model_value_write)
        self.base_custom_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.base_model_var.trace_add("write", lambda *args: self._remember_current_step4_training_model_selection())
        self.base_custom_var.trace_add("write", lambda *args: self._remember_current_step4_training_model_selection())
        self._refresh_base_model_choices()
        auto_name() # Inicjalizacja pierwszego wpisu        
        self._refresh_step4_training_inputs_mode_ui()
        self._refresh_dataset_variant_choices()
        
        self._build_train_left_separator(settings_col, pady=(self._train_left_section_gap, self._train_left_section_gap))

        self.train_params_title_lbl = tk.Label(
            settings_col,
            text="Parametry treningu YOLO",
            font=("Segoe UI Semibold", 10),
            anchor="w",
            bd=0,
            highlightthickness=0,
        )
        self.train_params_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))
        self.train_params_caption_lbl = None

        self.epochs_var = tk.IntVar(value=100)
        self.batch_var = tk.IntVar(value=16)
        self.imgsz_var = tk.IntVar(value=640)
        self.lr0_var = tk.DoubleVar(value=0.01)

        self.train_recommendation_table_shell = tk.Frame(settings_col, bd=0, highlightthickness=1)
        self.train_recommendation_table_shell.pack(fill=tk.X, pady=(0, 8))
        self.train_recommendation_grid = tk.Frame(self.train_recommendation_table_shell, bd=0, highlightthickness=0)
        self.train_recommendation_grid.pack(fill=tk.X, padx=1, pady=1)
        self.train_recommendation_grid.grid_columnconfigure(0, weight=0, minsize=118)
        self.train_recommendation_grid.grid_columnconfigure(1, weight=1)
        self.train_recommendation_grid.grid_columnconfigure(2, weight=0, minsize=86)
        header_specs = (
            ("Parametr", tk.W),
            ("Teraz", tk.CENTER),
            ("Zalecane", tk.CENTER),
        )
        self.train_recommendation_title_row = tk.Frame(
            self.train_recommendation_grid,
            bd=0,
            highlightthickness=0,
        )
        self.train_recommendation_title_row.grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="ew",
            padx=(0, 1),
            pady=(0, 1),
        )
        self.train_recommendation_title_row.grid_columnconfigure(0, weight=1)
        self.train_recommendation_title_label = tk.Label(
            self.train_recommendation_title_row,
            text="Ustawienia",
            font=("Segoe UI", 8, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=4,
        )
        self.train_recommendation_title_label.grid(row=0, column=0, sticky="w")
        self.btn_apply_training_recommendation = ttk.Button(
            self.train_recommendation_title_row,
            text="Ustaw zalecane",
            command=self._apply_training_device_recommendation,
            width=16,
        )
        self.btn_apply_training_recommendation.grid(row=0, column=1, sticky="e", padx=(8, 6), pady=3)
        self.train_recommendation_hardware_label = tk.Label(
            self.train_recommendation_grid,
            text="Wykryty sprzęt: -",
            font=("Segoe UI", 8),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=3,
        )
        self.train_recommendation_hardware_label.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            padx=(0, 1),
            pady=(0, 1),
        )
        self.train_recommendation_model_label = tk.Label(
            self.train_recommendation_grid,
            text="Model: -",
            font=("Segoe UI", 8),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=3,
        )
        self.train_recommendation_model_label.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="ew",
            padx=(0, 1),
            pady=(0, 1),
        )
        self._train_recommendation_header_labels = []
        for column, (text_value, anchor) in enumerate(header_specs):
            label = tk.Label(
                self.train_recommendation_grid,
                text=text_value,
                font=("Segoe UI", 8, "bold"),
                anchor=anchor,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=3,
            )
            label.grid(row=3, column=column, sticky="ew", padx=(0, 1), pady=(0, 1))
            self._train_recommendation_header_labels.append(label)

        self._train_recommendation_cells = []
        info_specs = (
            ("Model bazowy", "-", "-", "model_context"),
            ("Wersja / rozmiar", "-", "-", "model_variant"),
        )
        for row_index, (param_text, current_text, recommended_text, param_key) in enumerate(info_specs):
            grid_row = row_index + 4
            key_label = tk.Label(
                self.train_recommendation_grid,
                text=param_text,
                font=("Segoe UI", 8),
                anchor=tk.W,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=2,
            )
            key_label.grid(row=grid_row, column=0, sticky="ew", padx=(0, 1), pady=(0, 1))

            current_label = tk.Label(
                self.train_recommendation_grid,
                text=current_text,
                font=("Segoe UI", 8),
                anchor=tk.W,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=2,
            )
            current_label.grid(row=grid_row, column=1, sticky="ew", padx=(0, 1), pady=(0, 1))

            recommended_label = tk.Label(
                self.train_recommendation_grid,
                text=recommended_text,
                font=("Segoe UI", 8),
                anchor=tk.CENTER,
                justify=tk.CENTER,
                bd=0,
                padx=6,
                pady=2,
            )
            recommended_label.grid(row=grid_row, column=2, sticky="ew", padx=(0, 1), pady=(0, 1))

            self._train_recommendation_cells.append(
                {
                    "key": key_label,
                    "current": current_label,
                    "recommended": recommended_label,
                    "param_key": param_key,
                    "static": True,
                }
            )

        editor_specs = (
            ("1. Epoki (ręcznie)", self.epochs_var, {"from_": 1, "to": 5000, "width": 8}, "epochs"),
            ("2. Rozmiar partii", self.batch_var, {"from_": 1, "to": 256, "width": 8}, "batch"),
            ("3. Rozdzielczość wejściowa", self.imgsz_var, {"from_": 32, "to": 2048, "increment": 32, "width": 8}, "imgsz"),
            ("4. Współczynnik uczenia", self.lr0_var, {"from_": 0.0001, "to": 0.1, "increment": 0.001, "format": "%.4f", "width": 8}, "lr0"),
        )
        editor_start_row = 4 + len(info_specs)
        for row_index, (param_text, variable, spinbox_kwargs, param_key) in enumerate(editor_specs):
            key_label = tk.Label(
                self.train_recommendation_grid,
                text=param_text,
                font=("Segoe UI", 8),
                anchor=tk.W,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=2,
            )
            key_label.grid(
                row=editor_start_row + row_index,
                column=0,
                sticky="ew",
                padx=(0, 1),
                pady=(0, 1),
            )

            editor_host = tk.Frame(
                self.train_recommendation_grid,
                bd=0,
                highlightthickness=0,
                padx=4,
                pady=2,
            )
            editor_host.grid(
                row=editor_start_row + row_index,
                column=1,
                sticky="ew",
                padx=(0, 1),
                pady=(0, 1),
            )
            editor_host.grid_columnconfigure(0, weight=1)
            editor_host.grid_columnconfigure(1, weight=0)
            editor_host.grid_columnconfigure(2, weight=1)
            editor = ttk.Spinbox(
                editor_host,
                textvariable=variable,
                justify=tk.CENTER,
                **spinbox_kwargs,
            )
            editor.grid(row=0, column=1, sticky="", padx=(2, 2))

            recommended_label = tk.Label(
                self.train_recommendation_grid,
                text="-",
                font=("Segoe UI", 8),
                anchor=tk.CENTER,
                justify=tk.CENTER,
                bd=0,
                padx=6,
                pady=2,
            )
            recommended_label.grid(
                row=editor_start_row + row_index,
                column=2,
                sticky="ew",
                padx=(0, 1),
                pady=(0, 1),
            )

            self._train_recommendation_cells.append(
                {
                    "key": key_label,
                    "editor_host": editor_host,
                    "editor": editor,
                    "recommended": recommended_label,
                    "param_key": param_key,
                }
            )
        self.train_recommendation_tree = None
        self.train_recommendation_note_var = tk.StringVar(value="Brak VRAM? Zmniejszaj kolejno: batch -> imgsz -> epoki.")
        self.train_recommendation_note_lbl = ttk.Label(
            settings_col,
            textvariable=self.train_recommendation_note_var,
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360,
        )
        self.train_recommendation_note_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 12))
        self._register_train_left_wrap_target(self.train_recommendation_note_lbl, padding=16, min_wrap=220)
        self.epochs_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.epochs_var.trace_add("write", lambda *args: self._refresh_training_execution_summary())
        self.batch_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.imgsz_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.lr0_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self._apply_training_recommended_start_params()
        self._apply_training_recommendation_table_theme()

        self.device_var = tk.StringVar(value=self._get_global_training_device_choice())

        self.train_device_hint_lbl = ttk.Label(
            settings_col,
            text="",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self.train_device_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 12))
        self._register_train_left_wrap_target(self.train_device_hint_lbl, padding=16, min_wrap=220)
        self._refresh_training_device_hint()

        self.train_run_summary_shell = tk.Frame(
            settings_col,
            bd=0,
            highlightthickness=1,
            bg=palette.get("panel_alt", palette.get("panel", "#252526")),
        )
        self.train_run_summary_shell.pack(fill=tk.X, pady=(0, 12))
        self.train_run_summary_title_row = tk.Frame(
            self.train_run_summary_shell,
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=8,
            bg=palette.get("panel", "#252526"),
        )
        self.train_run_summary_title_row.pack(fill=tk.X)
        self.train_run_summary_title_lbl = tk.Label(
            self.train_run_summary_title_row,
            text="Podsumowanie tego treningu",
            font=("Segoe UI", 9, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", "#252526"),
            fg=palette.get("fg", "#f3f3f3"),
        )
        self.train_run_summary_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.train_run_summary_grid = tk.Frame(
            self.train_run_summary_shell,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel_alt", palette.get("panel", "#252526")),
        )
        self.train_run_summary_grid.pack(fill=tk.X, padx=10, pady=(10, 10))
        self.train_run_summary_grid.grid_columnconfigure(0, weight=0, minsize=110)
        self.train_run_summary_grid.grid_columnconfigure(1, weight=1)

        self.train_run_summary_header_key_lbl = tk.Label(
            self.train_run_summary_grid,
            text="Pole",
            font=("Segoe UI", 8, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=4,
            bg=palette.get("panel", "#252526"),
            fg=palette.get("fg", "#f3f3f3"),
        )
        self.train_run_summary_header_key_lbl.grid(row=0, column=0, sticky="ew", padx=(0, 1), pady=(0, 1))
        self.train_run_summary_header_value_lbl = tk.Label(
            self.train_run_summary_grid,
            text="Wartość",
            font=("Segoe UI", 8, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=4,
            bg=palette.get("panel", "#252526"),
            fg=palette.get("fg", "#f3f3f3"),
        )
        self.train_run_summary_header_value_lbl.grid(row=0, column=1, sticky="ew", padx=(0, 1), pady=(0, 1))

        self._train_run_summary_row_widgets = []
        for row_index in range(10):
            key_label = tk.Label(
                self.train_run_summary_grid,
                text="",
                font=("Segoe UI", 8, "bold"),
                anchor=tk.W,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=3,
                bg=palette.get("panel", "#252526"),
                fg=palette.get("fg", "#f3f3f3"),
            )
            key_label.grid(row=row_index + 1, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
            value_label = tk.Label(
                self.train_run_summary_grid,
                text="",
                font=("Segoe UI", 8),
                anchor=tk.W,
                justify=tk.LEFT,
                bd=0,
                padx=6,
                pady=3,
                wraplength=250,
                bg=palette.get("panel_alt", palette.get("panel", "#252526")),
                fg=palette.get("muted", "#c7c7c7"),
            )
            value_label.grid(row=row_index + 1, column=1, sticky="nsew", padx=(0, 1), pady=(0, 1))
            self._register_train_left_wrap_target(value_label, container=self.train_run_summary_shell, padding=140, min_wrap=180)
            self._train_run_summary_row_widgets.append({"key": key_label, "value": value_label, "row_index": row_index})

        self.btn_step4_start_train_frame = tk.Frame(
            settings_col,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", "#252526"),
        )
        self.btn_step4_start_train_frame.pack(fill=tk.X, pady=(15, 6))
        self.btn_step4_start_train_frame.grid_columnconfigure(0, weight=1)

        self.btn_step4_start_train_pulse_frame = tk.Frame(
            self.btn_step4_start_train_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_start_train_pulse_frame.grid(row=0, column=0, sticky="ew")

        self.btn_start_train = ttk.Button(
            self.btn_step4_start_train_pulse_frame,
            text="▶ ROZPOCZNIJ TRENING",
            command=self._start_training,
            style="Accent.TButton"
        )
        self.btn_start_train.pack(fill=tk.X)

        self.btn_pause_train = ttk.Button(
            self.btn_step4_start_train_frame,
            text="Pauza",
            command=self._pause_training,
            state=tk.DISABLED,
            width=12,
        )
        self.btn_pause_train.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.btn_stop_train = ttk.Button(
            self.btn_step4_start_train_frame,
            text="Stop",
            command=self._stop_training,
            state=tk.DISABLED,
            width=12,
        )
        self.btn_stop_train.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.train_epoch_progress_var = tk.DoubleVar(value=0.0)
        self.train_progress_var = tk.DoubleVar(value=0.0)
        self.train_progress_shell = tk.Frame(
            settings_col,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
        )
        self.train_progress_shell.pack(fill=tk.X, pady=(10, 0))

        self.train_epoch_progress_row = tk.Frame(
            self.train_progress_shell,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
        )
        self.train_epoch_progress_row.pack(fill=tk.X, pady=(0, 3))
        self.train_epoch_progress = TrainProgressBar(
            self.train_epoch_progress_row,
            variable=self.train_epoch_progress_var,
            maximum=100,
            thickness=4,
            trough_color=palette.get("surface_info", palette.get("panel_alt", palette.get("panel", "#252526"))),
            fill_color=palette.get("guide", palette.get("warning", "#f0b44c")),
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            height=8,
        )
        self.train_epoch_progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.train_epoch_progress_measure_lbl = tk.Label(
            self.train_epoch_progress_row,
            text="Bieżąca epoka (partie danych)",
            font=("Segoe UI", 8),
            anchor=tk.E,
            justify=tk.RIGHT,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            fg=palette.get("muted", "#c7c7c7"),
            padx=8,
        )
        self.train_epoch_progress_measure_lbl.pack(side=tk.LEFT)
        self.train_epoch_progress_hint_lbl = tk.Label(
            self.train_progress_shell,
            text="Pokazuje, ile partii danych zostało wykonanych w aktualnej epoce.",
            font=("Segoe UI", 8),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            fg=palette.get("muted_dim", palette.get("muted", "#9a9a9a")),
            padx=2,
        )
        self.train_epoch_progress_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(1, 6))

        self.train_overall_progress_row = tk.Frame(
            self.train_progress_shell,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
        )
        self.train_overall_progress_row.pack(fill=tk.X)
        self.train_progress = TrainProgressBar(
            self.train_overall_progress_row,
            variable=self.train_progress_var,
            maximum=100,
            thickness=4,
            trough_color=palette.get("surface_info", palette.get("panel_alt", palette.get("panel", "#252526"))),
            fill_color=palette.get("success", "#2ecc71"),
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            height=8,
        )
        self.train_progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.train_progress_measure_lbl = tk.Label(
            self.train_overall_progress_row,
            text="Cały run (epoki)",
            font=("Segoe UI", 8),
            anchor=tk.E,
            justify=tk.RIGHT,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            fg=palette.get("muted", "#c7c7c7"),
            padx=8,
        )
        self.train_progress_measure_lbl.pack(side=tk.LEFT)
        self.train_progress_hint_lbl = tk.Label(
            self.train_progress_shell,
            text="Pokazuje, ile epok całego runu zostało już domkniętych względem planu.",
            font=("Segoe UI", 8),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            fg=palette.get("muted_dim", palette.get("muted", "#9a9a9a")),
            padx=2,
        )
        self.train_progress_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(1, 0))
        self._configure_train_progress_styles()
        
        self.train_progress_label = ttk.Label(settings_col, text="Czekam na start...", font=("Segoe UI", 9), style="Panel.TLabel")
        self.train_metric_hint_lbl = ttk.Label(
            settings_col,
            text="Interpretacja pojawi się po pierwszej zakończonej epoce.",
            style="Panel.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self.train_metric_reference_lbl = ttk.Label(
            settings_col,
            text="",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self._refresh_training_metric_reference()
        self.train_live_metrics_tree = None
        self._refresh_training_recommendation_table()
        self._refresh_training_start_state()

        terminal_tools = ttk.Frame(root, style="Panel.TFrame")
        terminal_tools.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.btn_toggle_step4_train_log = ttk.Button(
            terminal_tools,
            text="Pokaż terminal",
            command=self._toggle_step4_train_log
        )
        self.btn_toggle_step4_train_log.pack_forget()

        ttk.Label(
            terminal_tools,
            text="Wspólny terminal procesu dla treningu i walidacji jest dostępny na żądanie.",
            foreground="gray"
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.step4_train_log_host = ttk.Frame(root, style="Panel.TFrame")
        self.step4_train_log_host.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        self.step4_train_log_frame = ttk.LabelFrame(
            self.step4_train_log_host,
            text=" Terminal procesu ",
            padding=6
        )
        self.step4_train_log_console_host = ttk.Frame(self.step4_train_log_frame, style="Panel.TFrame")
        self.step4_train_log_console_host.pack(fill=tk.BOTH, expand=True)

        self.train_log_console = tk.Text(
            self.step4_train_log_console_host,
            width=50,
            height=10,
            wrap=tk.NONE,
            font=("Consolas", 10),
            bg=palette.get("console_bg", palette.get("field", "#1e1e1e")),
            fg=palette.get("console_fg", palette.get("fg", "#ecf0f1")),
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.step4_train_log_hscrollbar = WebSlimScrollbar(
            self.step4_train_log_console_host,
            orient=tk.HORIZONTAL,
            command=self.train_log_console.xview,
            auto_hide=False,
        )
        self.step4_train_log_hscrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.train_log_console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.step4_train_log_scrollbar = WebSlimScrollbar(
            self.step4_train_log_console_host,
            orient=tk.VERTICAL,
            command=self.train_log_console.yview,
            auto_hide=False,
        )
        self.step4_train_log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.train_log_console.configure(
            yscrollcommand=self.step4_train_log_scrollbar.set,
            xscrollcommand=self.step4_train_log_hscrollbar.set,
        )
        self.train_log_console.web_vbar = self.step4_train_log_scrollbar
        self.train_log_console.web_hbar = self.step4_train_log_hscrollbar
        self._set_step4_process_console_text(
            "Oczekuję na rozpoczęcie treningu lub walidacji...\n"
            "Terminal procesu jest gotowy na dane z Ultralytics.\n"
        )
        self._set_step4_train_log_visibility(False)
        try:
            terminal_tools.grid_remove()
        except Exception:
            pass

        self.right_nb = ttk.Notebook(self.right)
        self.right_nb.pack(fill=tk.BOTH, expand=True)

        self.hist_tab = ttk.Frame(self.right_nb)
        self.val_tab = ttk.Frame(self.right_nb)
        self.ranking_tab = ttk.Frame(self.right_nb)
        self.right_nb.add(self.hist_tab, text="Historia treningow")
        self.right_nb.add(self.val_tab, text="Walidacja")
        self.right_nb.add(self.ranking_tab, text="Ranking")
        self._step4_ranking_tab_visible = True
        self.right_nb.bind("<<NotebookTabChanged>>", self._sync_step4_analysis_nav_buttons)

        hist_top = ttk.Frame(self.hist_tab, padding=(8, 0, 6, 0), style="Panel.TFrame")
        hist_top.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            hist_top,
            text=(
                "Historia służy jako główny panel wyników. "
                "Podwójne kliknięcie LPM na wpisie otwiera osobne okno analizy z wykresami treningu."
            ),
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=760,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

        hist_tree_shell = ttk.LabelFrame(hist_top, text=" Historia runow ", padding=6)
        hist_tree_shell.pack(fill=tk.BOTH, expand=True)
        columns = ("Tor", "Run", "Status", "Epoki", "Best mAP50-95", "Czas")
        self.tree = ttk.Treeview(hist_tree_shell, columns=columns, show="headings", height=10)
        for c in columns:
            self.tree.heading(c, text=c)
        self.tree.column("Tor", width=92, stretch=False, anchor=tk.CENTER)
        self.tree.column("Run", width=210, stretch=True)
        self.tree.column("Status", width=148, stretch=False)
        self.tree.column("Epoki", width=64, stretch=False)
        self.tree.column("Best mAP50-95", width=102, stretch=False, anchor=tk.CENTER)
        self.tree.column("Czas", width=76, stretch=False)

        yscroll = WebSlimScrollbar(hist_tree_shell, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_run_selected)
        self.tree.bind("<Double-1>", self._open_selected_run_analysis, add="+")
        self.tree.bind("<Button-3>", self._show_history_context_menu, add="+")
        self.history_context_menu = tk.Menu(self.tree, tearoff=0)
        self.history_context_menu.add_command(label="Wznów trening", command=self._resume_selected_run)
        self.history_context_menu.add_command(label="Otwórz folder", command=self._open_run_folder)
        self.history_context_menu.add_command(
            label="Eksportuj best.pt do modeli trybu swobodnego",
            command=self._export_selected_run_model_to_free_mode,
        )
        self.history_context_menu.add_command(label="Usun", command=self._delete_selected)

        hist_details = ttk.Frame(hist_top, style="Panel.TFrame")
        hist_details.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        hist_details.columnconfigure(0, weight=1)
        hist_details.columnconfigure(1, weight=1)
        hist_details.rowconfigure(0, weight=1)

        hist_detail_box = ttk.Frame(hist_details, style="Panel.TFrame")
        hist_detail_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ttk.Label(
            hist_detail_box,
            text="Konfiguracja runu",
            style="Panel.TLabel",
            anchor=tk.W,
            padding=(6, 4),
        ).pack(fill=tk.X, pady=(0, 4))
        self.hist_detail_tree = self._create_metric_table(
            hist_detail_box,
            [
                ("Pole", 160, tk.W),
                ("Wartosc", 310, tk.W),
            ],
            height=7,
        )

        hist_metric_box = ttk.Frame(hist_details, style="Panel.TFrame")
        hist_metric_box.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ttk.Label(
            hist_metric_box,
            text="Wyniki modelu",
            style="Panel.TLabel",
            anchor=tk.W,
            padding=(6, 4),
        ).pack(fill=tk.X, pady=(0, 4))
        self.hist_metrics_tree = self._create_metric_table(
            hist_metric_box,
            [
                ("Metryka", 145, tk.W),
                ("Ostatnia", 80, tk.CENTER),
                ("Najlepsza", 80, tk.CENTER),
                ("Ocena", 100, tk.CENTER),
            ],
            height=7,
        )

        self._build_validation_panel_v2(self.val_tab)
        self._build_ranking_panel_v2(self.ranking_tab)
        self._refresh_step4_analysis_tab_visibility()
        self._sync_step4_analysis_nav_buttons()
        self._set_history_run_tables(None)

        self.step4_train_nav = ttk.Frame(root)
        self.step4_train_nav.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        self.btn_step4_train_back = ttk.Button(
            self.step4_train_nav,
            text="← Wstecz do wyboru toru",
            command=self._step4_train_go_back,
            style="WorkflowCard.TButton"
        )
        self.btn_step4_train_back.pack(side=tk.RIGHT, padx=(8, 0))
        self.btn_step4_train_back.configure(text="Wstecz do toru", padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self.btn_step4_finish_frame = tk.Frame(self.step4_train_nav, bd=0, highlightthickness=0)
        self.btn_step4_finish_frame.pack(side=tk.RIGHT)

        self.btn_step4_complete_project = ttk.Button(
            self.btn_step4_finish_frame,
            text="Zakończ projekt",
            command=self._complete_campaign_project,
            style="WorkflowCard.TButton",
            state=tk.DISABLED
        )
        self.btn_step4_complete_project.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_step4_complete_project.configure(padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self.btn_step4_finish = ttk.Button(
            self.btn_step4_finish_frame,
            text="Ustaw inny split",
            command=self._open_step4_dataset_stage,
            style="Accent.TButton",
            state=tk.DISABLED
        )
        self.btn_step4_finish.pack(side=tk.LEFT)
        self.btn_step4_finish.configure(text="Ustaw inny split", padding=(8, 2), width=22)

        self._refresh_step4_campaign_navigation_ui()

        HELP.bind_help(ds_row, "tr_train_ds")
        HELP.bind_help(self.training_input_summary_frame, "tr_train_input_summary")
        HELP.bind_help(self.training_input_change_btn, "tr_train_input_summary")
        HELP.bind_help(self.train_dataset_section_frame, "tr_train_ds")
        HELP.bind_help(self.train_dataset_entry, "tr_train_ds")
        HELP.bind_help(self.train_dataset_pick_btn, "tr_train_ds")
        HELP.bind_help(self.train_dataset_yaml_btn, "tr_train_ds")
        HELP.bind_help(self.dataset_variant_row, "tr_dataset_variant")
        HELP.bind_help(self.dataset_variant_combo, "tr_dataset_variant")
        HELP.bind_help(self.dataset_variant_refresh_btn, "tr_dataset_variant")
        HELP.bind_help(self.train_dataset_hint_lbl, "tr_train_ds")
        HELP.bind_help(self.base_combo, "tr_train_base")
        HELP.bind_help(self.base_custom_btn, "tr_train_custom")
        HELP.bind_help(self.train_recommendation_grid, "tr_train_params")
        HELP.bind_help(self.btn_apply_training_recommendation, "tr_train_recommendation")
        HELP.bind_help(self.train_device_hint_lbl, "tr_train_device")
        HELP.bind_help(self.btn_step4_back, "tr_builder_back")
        
        try:
            recommendation_rows = [
                row for row in list(getattr(self, "_train_recommendation_cells", []) or [])
                if row.get("editor") is not None
            ]
            help_keys = ("tr_train_ep", "tr_train_bs", "tr_train_imgsz", "tr_train_lr0")
            for row, help_key in zip(recommendation_rows, help_keys):
                HELP.bind_help(row.get("editor"), help_key)
        except Exception as e: 
            logger.debug(f"Błąd podpinania pomocy do siatki: {e}")
        
        HELP.bind_help(self.btn_start_train, "tr_train_btn")
        HELP.bind_help(self.btn_pause_train, "tr_train_control")
        HELP.bind_help(self.btn_stop_train, "tr_train_control")
        HELP.bind_help(self.tree, "tr_train_tree")
        HELP.bind_help(self.custom_row, "tr_train_custom")
        HELP.bind_help(self.btn_toggle_step4_train_log, "tr_train_log")
        HELP.bind_help(self.btn_step4_train_back, "tr_train_back")
        HELP.bind_help(self.btn_step4_finish, "tr_train_finish")
        HELP.bind_help(self.btn_step4_complete_project, "tr_train_finish")

        self._bind_scroll_canvas_children(self.train_left_content, self.train_left_canvas)
        self.frame.after_idle(self._sync_train_left_scrollregion)
        self.frame.after_idle(self._update_training_dataset_hint_wraplength)
        self.frame.after_idle(self._sync_train_left_canvas_width)
        self.frame.after_idle(self._init_train_pane_layout)
        self.frame.bind_all("<MouseWheel>", self._on_train_left_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_train_left_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_train_left_global_mousewheel, add="+")

    def _build_validation_panel(self, parent):
        ttk.Label(
            parent,
            text="Sprawdź jakość wytrenowanego modelu YOLO na wybranym zbiorze testowym.",
            font=("Segoe UI", 10),
            wraplength=360,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 15))

        ttk.Label(parent, text="Wytrenowany model (.pt):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(5, 2))
        row1 = ttk.Frame(parent)
        row1.pack(fill=tk.X)
        self.val_model_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.val_model_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            row1,
            text="Wybierz",
            command=lambda: self._pick_file(
                self.val_model_var,
                "*.pt",
                initialdir=self._get_validation_model_picker_dir(),
            ),
        ).pack(side=tk.RIGHT, padx=(5,0))
        
        ttk.Label(parent, text="Dataset testowy (data.yaml):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(15, 2))
        row2 = ttk.Frame(parent)
        row2.pack(fill=tk.X)
        self.val_data_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.val_data_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            row2,
            text="Wybierz",
            command=lambda: self._pick_dir(
                self.val_data_var,
                initialdir=self._get_validation_dataset_picker_dir(),
            ),
        ).pack(side=tk.RIGHT, padx=(5,0))

        ttk.Label(parent, text="Przetestuj na podzbiorze:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(15, 2))
        self.val_split_var = tk.StringVar(value="val")
        split_combo = ttk.Combobox(parent, textvariable=self.val_split_var, values=["val", "test", "train"], state="readonly", width=15)
        split_combo.pack(anchor=tk.W)

        action_row = ttk.Frame(parent)
        action_row.pack(fill=tk.X, pady=(20, 4))

        self.btn_run_val = ttk.Button(action_row, text="🚀 PRZEPROWADŹ WALIDACJĘ", style="Accent.TButton", command=self._run_validation)
        self.btn_run_val.pack(side=tk.LEFT, ipady=4)

        self.val_status = ttk.Label(action_row, text="Gotowy", foreground="gray")
        self.val_status.pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(
            parent,
            text="Wyniki walidacji pojawią się we wspólnym terminalu procesu.",
            foreground="gray",
            wraplength=360,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(8, 0))

        HELP.bind_help(row1, "tr_val_model")
        HELP.bind_help(row2, "tr_val_data")
        HELP.bind_help(self.btn_run_val, "tr_val_btn")

        HELP.bind_help(split_combo, "tr_val_split")

        summary_box = ttk.LabelFrame(parent, text=" Ostatni wynik walidacji ", padding=8)
        summary_box.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        self.val_summary_title_var = tk.StringVar(
            value="Po uruchomieniu walidacji najważniejsze metryki pojawią się tutaj."
        )
        self.val_summary_title_lbl = ttk.Label(
            summary_box,
            textvariable=self.val_summary_title_var,
            style="Muted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self.val_summary_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        summary_tree_host = ttk.Frame(summary_box)
        summary_tree_host.pack(fill=tk.BOTH, expand=True)

        self.val_metrics_tree = ttk.Treeview(
            summary_tree_host,
            columns=("metric", "value"),
            show="headings",
            height=8
        )
        self.val_metrics_tree.heading("metric", text="Metryka")
        self.val_metrics_tree.heading("value", text="Wartosc")
        self.val_metrics_tree.column("metric", width=210, anchor=tk.W)
        self.val_metrics_tree.column("value", width=100, anchor=tk.CENTER, stretch=False)

        val_tree_scroll = WebSlimScrollbar(
            summary_tree_host,
            command=self.val_metrics_tree.yview
        )
        self.val_metrics_tree.configure(yscrollcommand=val_tree_scroll.set)
        self.val_metrics_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        val_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    @staticmethod
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

    @staticmethod
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

    def _collect_run_analysis_paths(self, run) -> list[Path]:
        if run is None:
            return []

        run_dir = Path(getattr(run, "output_dir", "") or "")
        if not run_dir.exists():
            return []

        priority_order = (
            "results",
            "confusion_matrix",
            "pr_curve",
            "f1_curve",
            "p_curve",
            "r_curve",
            "labels",
            "val",
            "train",
        )

        candidates: list[Path] = []
        for path in run_dir.rglob("*"):
            if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            lower_name = path.name.lower()
            if any(token in lower_name for token in priority_order):
                candidates.append(path)

        def sort_key(path: Path):
            lower_name = path.name.lower()
            priority = next((idx for idx, token in enumerate(priority_order) if token in lower_name), len(priority_order))
            return (priority, lower_name)

        native_paths = sorted(candidates, key=sort_key)
        if native_paths:
            return native_paths

        return self._build_fallback_run_analysis_paths(run)

    def _load_run_results_csv_rows(self, run) -> list[dict[str, str]]:
        if run is None:
            return []

        run_dir = Path(getattr(run, "output_dir", "") or "")
        csv_path = run_dir / "train" / "results.csv"
        if not csv_path.exists():
            return []

        rows: list[dict[str, str]] = []
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    if isinstance(row, dict):
                        rows.append({str(k or "").strip(): str(v or "").strip() for k, v in row.items()})
        except Exception as e:
            logger.debug(f"Nie udało się odczytać results.csv dla analizy runu: {e}")
            return []
        return rows

    @staticmethod
    def _run_analysis_font():
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    def _wrap_run_analysis_line(self, label: str, value: str, width: int = 110) -> list[str]:
        base = f"{label}: {value}".strip()
        if not base:
            return [""]
        return textwrap.wrap(base, width=width, break_long_words=False, break_on_hyphens=False) or [base]

    def _render_run_analysis_sheet(
        self,
        title: str,
        sections: list[tuple[str, list[str]]],
        out_path: Path,
        *,
        width: int = 1500,
    ) -> Path | None:
        if not PIL_AVAILABLE:
            return None

        font = self._run_analysis_font()
        line_height = 24
        section_gap = 18
        top_pad = 28
        left_pad = 30
        right_pad = 30
        bottom_pad = 28

        total_lines = 2
        for heading, lines in sections:
            total_lines += 1
            total_lines += max(1, len(lines))
            total_lines += 1

        height = max(420, top_pad + bottom_pad + total_lines * line_height + max(0, len(sections) - 1) * section_gap)
        img = Image.new("RGB", (int(width), int(height)), color="#1f2933")
        draw = ImageDraw.Draw(img)

        title_color = "#e8f6ef"
        heading_color = "#8fd19e"
        text_color = "#d8dee9"
        muted_color = "#94a3b8"
        accent_color = "#2d6a4f"

        y = top_pad
        draw.text((left_pad, y), title, fill=title_color, font=font)
        y += line_height + 8
        draw.line((left_pad, y, width - right_pad, y), fill=accent_color, width=2)
        y += 16

        for heading, lines in sections:
            draw.text((left_pad, y), heading, fill=heading_color, font=font)
            y += line_height
            section_lines = lines or ["Brak danych."]
            for line in section_lines:
                color = muted_color if str(line or "").strip() == "Brak danych." else text_color
                draw.text((left_pad + 10, y), str(line or ""), fill=color, font=font)
                y += line_height
            y += section_gap

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(out_path)
            return out_path
        except Exception as e:
            logger.debug(f"Nie udało się zapisać syntetycznej planszy analizy runu: {e}")
            return None

    def _build_fallback_run_analysis_paths(self, run) -> list[Path]:
        if run is None or not PIL_AVAILABLE:
            return []

        run_dir = Path(getattr(run, "output_dir", "") or "")
        if not run_dir.exists():
            return []

        cache_dir = run_dir / "_analysis_cache"
        detail_rows = self._build_training_run_detail_rows(run)
        metric_rows = self._build_training_run_metric_rows(run)
        csv_rows = self._load_run_results_csv_rows(run)

        sections_summary: list[tuple[str, list[str]]] = [
            (
                "Podsumowanie runu",
                [
                    line
                    for label, value in detail_rows
                    for line in self._wrap_run_analysis_line(label, value, width=118)
                ] or ["Brak danych."],
            ),
            (
                "Najważniejsze metryki",
                [
                    f"{label}: ostatnia {current} | najlepsza {best} | ocena {band}"
                    for label, current, best, band in metric_rows
                ] or ["Brak danych."],
            ),
        ]

        epoch_lines: list[str] = []
        if csv_rows:
            for row in csv_rows[-12:]:
                epoch_value = str(row.get("epoch", "") or row.get("Epoch", "") or "-").strip()
                loss_value = str(
                    row.get("train/box_loss", "")
                    or row.get("train/loss", "")
                    or row.get("loss", "")
                    or "-"
                ).strip()
                map50_value = str(
                    row.get("metrics/mAP50(B)", "")
                    or row.get("metrics/mAP50", "")
                    or row.get("map50", "")
                    or "-"
                ).strip()
                map95_value = str(
                    row.get("metrics/mAP50-95(B)", "")
                    or row.get("metrics/mAP50-95", "")
                    or row.get("map50_95", "")
                    or "-"
                ).strip()
                epoch_lines.append(
                    f"Epoka {epoch_value}: loss {loss_value} | mAP50 {map50_value} | mAP50-95 {map95_value}"
                )
        else:
            history = list(getattr(run, "metrics_history", []) or [])
            for item in history[-12:]:
                epoch_lines.append(
                    "Epoka "
                    f"{int(item.get('epoch', 0) or 0)}: "
                    f"loss {float(item.get('loss', 0.0) or 0.0):.4f} | "
                    f"mAP50 {float(item.get('map50', 0.0) or 0.0):.4f} | "
                    f"mAP50-95 {float(item.get('map50_95', 0.0) or 0.0):.4f}"
                )

        sections_epochs: list[tuple[str, list[str]]] = [
            (
                "Przebieg epok",
                epoch_lines or ["Brak danych epok w results.csv ani metrics_history."],
            ),
            (
                "Artefakty runu",
                [
                    f"Folder runu: {self._format_workspace_relative_path(run_dir)}",
                    f"Plik wyników CSV: {self._format_workspace_relative_path(run_dir / 'train' / 'results.csv') if (run_dir / 'train' / 'results.csv').exists() else 'brak'}",
                    f"Najlepsze wagi: {self._format_workspace_relative_path(getattr(run, 'best_weights', '') or '-')}",
                    f"Checkpoint last.pt: {self._format_workspace_relative_path(getattr(run, 'last_weights', '') or '-')}",
                ],
            ),
        ]

        generated: list[Path] = []
        summary_path = cache_dir / "00_podsumowanie_runu.png"
        epochs_path = cache_dir / "01_przebieg_epok.png"

        rendered_summary = self._render_run_analysis_sheet(
            "Analiza runu treningowego",
            sections_summary,
            summary_path,
        )
        if rendered_summary is not None:
            generated.append(rendered_summary)

        rendered_epochs = self._render_run_analysis_sheet(
            "Przebieg treningu i artefakty",
            sections_epochs,
            epochs_path,
        )
        if rendered_epochs is not None:
            generated.append(rendered_epochs)

        return generated

    def _close_analysis_dialog(self):
        dialog = getattr(self, "_analysis_dialog", None)
        if dialog is not None:
            try:
                dialog.destroy()
            except Exception:
                pass
        self._analysis_dialog = None
        self._analysis_dialog_shell = None
        self._analysis_plot_paths = []
        self._analysis_plot_canvas = None
        self._analysis_plots_list = None

    def _style_analysis_dialog(self):
        dialog = getattr(self, "_analysis_dialog", None)
        if dialog is None:
            return
        try:
            if not dialog.winfo_exists():
                return
        except Exception:
            return

        palette = getattr(self.app, "palette", {})
        try:
            dialog.configure(bg=palette.get("bg", "#1e1e1e"))
        except Exception:
            pass
        try:
            self.app.style_panel_surface(
                getattr(self, "_analysis_dialog_shell", None),
                background=palette.get("panel", "#252526"),
            )
        except Exception:
            pass
        try:
            self.app.style_listbox_widget(
                getattr(self, "_analysis_plots_list", None),
                bordercolor=palette.get("console_border", palette.get("border", "#3c3c3c")),
            )
        except Exception:
            pass
        try:
            self.app.style_canvas_widget(
                getattr(self, "_analysis_plot_canvas", None),
                background=palette.get("panel", "#252526"),
                bordercolor=palette.get("console_border", palette.get("border", "#3c3c3c")),
            )
        except Exception:
            pass

    def _populate_analysis_dialog(self, plot_paths: list[Path]):
        self._analysis_plot_paths = list(plot_paths or [])
        listbox = getattr(self, "_analysis_plots_list", None)
        if listbox is None:
            return

        try:
            listbox.delete(0, tk.END)
        except Exception:
            pass

        for path in self._analysis_plot_paths:
            try:
                listbox.insert(tk.END, path.name)
            except Exception:
                continue

        if self._analysis_plot_paths:
            try:
                listbox.selection_clear(0, tk.END)
                listbox.selection_set(0)
                listbox.activate(0)
            except Exception:
                pass
            self._show_analysis_plot(self._analysis_plot_paths[0])

    def _open_run_analysis_window(self, run):
        palette = getattr(self.app, "palette", {})
        plot_paths = self._collect_run_analysis_paths(run)
        if not plot_paths:
            return messagebox.showinfo(
                "Brak wykresow",
                "Dla wybranego runu nie znaleziono artefaktow analitycznych Ultralytics.",
            )

        if not PIL_AVAILABLE:
            self._open_run_folder()
            return messagebox.showinfo(
                "Brak podgladu obrazów",
                "Brakuje biblioteki PIL, wiec otworzylem folder runu zamiast podgladu wykresow.",
            )

        dialog = getattr(self, "_analysis_dialog", None)
        dialog_exists = False
        if dialog is not None:
            try:
                dialog_exists = bool(dialog.winfo_exists())
            except Exception:
                dialog_exists = False

        if not dialog_exists:
            dialog = tk.Toplevel(self.frame)
            dialog.title("Analiza treningu")
            dialog.geometry("1180x720")
            dialog.minsize(960, 560)
            dialog.transient(self.frame.winfo_toplevel())
            dialog.resizable(True, True)
            dialog.protocol("WM_DELETE_WINDOW", self._close_analysis_dialog)
            self._analysis_dialog = dialog

            shell = ttk.Frame(dialog, padding=10, style="Panel.TFrame")
            shell.pack(fill=tk.BOTH, expand=True)
            self._analysis_dialog_shell = shell

            ttk.Label(
                shell,
                text="Artefakty treningu Ultralytics dla wybranego runu. Po lewej wybierasz wykres, po prawej masz powiekszalny podglad.",
                style="PanelMuted.TLabel",
                anchor=tk.W,
                justify=tk.LEFT,
                wraplength=980,
            ).pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

            pane = ttk.PanedWindow(shell, orient=tk.HORIZONTAL)
            pane.pack(fill=tk.BOTH, expand=True)

            left = ttk.LabelFrame(pane, text=" Wykresy ", padding=8)
            right = ttk.LabelFrame(pane, text=" Podglad ", padding=8)
            pane.add(left, weight=1)
            pane.add(right, weight=4)

            list_shell = ttk.Frame(left, style="Panel.TFrame")
            list_shell.pack(fill=tk.BOTH, expand=True)
            self._analysis_plots_list = tk.Listbox(
                list_shell,
                height=16,
                font=("Consolas", 10),
                activestyle="none",
                exportselection=False,
            )
            self._analysis_plots_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            list_scroll = WebSlimScrollbar(list_shell, orient=tk.VERTICAL, command=self._analysis_plots_list.yview)
            list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self._analysis_plots_list.configure(yscrollcommand=list_scroll.set)
            self._analysis_plots_list.bind("<<ListboxSelect>>", self._on_analysis_plot_selected)

            canvas_shell = ttk.Frame(right, style="Panel.TFrame")
            canvas_shell.pack(fill=tk.BOTH, expand=True)
            self._analysis_plot_canvas = ZoomableCanvas(
                canvas_shell,
                bg=palette.get("panel", "#252526"),
                highlightthickness=0,
            )
            self._analysis_plot_canvas.pack(fill=tk.BOTH, expand=True)

        try:
            self._analysis_dialog.title(f"Analiza treningu | {self._shorten_training_text(getattr(run, 'name', ''), 48)}")
            self._analysis_dialog.deiconify()
            self._analysis_dialog.lift()
            self._analysis_dialog.focus_force()
        except Exception:
            pass

        self._style_analysis_dialog()
        self._populate_analysis_dialog(plot_paths)

    def _open_selected_run_analysis(self, event=None):
        if event is not None and hasattr(self, "tree") and getattr(event, "y", None) is not None:
            try:
                row_id = self.tree.identify_row(event.y)
            except Exception:
                row_id = ""
            if not row_id:
                return
            try:
                self.tree.selection_set(row_id)
                self.tree.focus(row_id)
            except Exception:
                pass
            self._on_run_selected()

        run = self._selected_run()
        if run is None:
            return
        self._open_run_analysis_window(run)

    def _on_analysis_plot_selected(self, event=None):
        listbox = getattr(self, "_analysis_plots_list", None)
        if listbox is None or not self._analysis_plot_paths:
            return
        selection = listbox.curselection()
        if not selection:
            return
        index = int(selection[0])
        if 0 <= index < len(self._analysis_plot_paths):
            self._show_analysis_plot(self._analysis_plot_paths[index])

    def _show_analysis_plot(self, path):
        if not PIL_AVAILABLE:
            return
        try:
            img = Image.open(path)
            self._analysis_plot_canvas.set_image(img)
            self._analysis_plot_canvas.fit_to_view()
        except Exception as e:
            logger.error(f"Nie udało się wyswietlic wykresu: {e}")

    def _build_ranking_panel(self, parent):
        palette = getattr(self.app, "palette", {})
        ttk.Label(
            parent,
            text="Porównuj wytrenowane modele względem zapisanych poprawek z annotations.xml.",
            font=("Segoe UI", 10),
            wraplength=520,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 15))

        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        left_f = ttk.Frame(pane, padding=2)
        right_f = ttk.Frame(pane, padding=2)
        pane.add(left_f, weight=1)
        pane.add(right_f, weight=3)

        ttk.Label(left_f, text="Obslugiwany ranking:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0,5))
        self.rank_category_info_lbl = ttk.Label(
            left_f,
            text="Tablice (Pose, annotations.xml z CVAT)",
            style="Muted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=220
        )
        self.rank_category_info_lbl.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(left_f, text="Katalog z modelami (.pt):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        row1 = ttk.Frame(left_f)
        row1.pack(fill=tk.X, pady=2)
        self.rank_models_dir = tk.StringVar(value=str(self._get_ranking_models_default_dir()))
        ttk.Entry(row1, textvariable=self.rank_models_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            row1,
            text="Wyb",
            command=lambda: self._pick_dir(
                self.rank_models_dir,
                initialdir=self._get_ranking_models_picker_dir(),
            ),
        ).pack(side=tk.RIGHT, padx=(2,0))

        ttk.Label(left_f, text="Folder z annotations.xml dla tablic:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(10,0))
        row2 = ttk.Frame(left_f)
        row2.pack(fill=tk.X, pady=2)
        self.rank_data_dir = tk.StringVar()
        ttk.Entry(row2, textvariable=self.rank_data_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wyb", command=lambda: self._pick_dir(self.rank_data_dir)).pack(side=tk.RIGHT, padx=(2,0))

        ttk.Label(left_f, text="Min. Confidence:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(10,0))
        self.rank_conf = tk.DoubleVar(value=CONFIG.DEFAULT_CONFIDENCE)
        
        conf_row = ttk.Frame(left_f)
        conf_row.pack(fill=tk.X)
        ttk.Scale(conf_row, from_=0.1, to=0.9, variable=self.rank_conf).pack(side=tk.LEFT, fill=tk.X, expand=True)
        lbl_conf = ttk.Label(conf_row, width=4)
        lbl_conf.pack(side=tk.RIGHT, padx=(5,0))
        self.rank_conf.trace_add("write", lambda *a: lbl_conf.config(text=f"{self.rank_conf.get():.2f}"))
        lbl_conf.config(text=f"{self.rank_conf.get():.2f}")

        self.btn_run_rank = ttk.Button(left_f, text="Uruchom ranking", style="Accent.TButton", command=self._run_ranking)
        self.btn_run_rank.pack(fill=tk.X, pady=(20,5), ipady=4)
        
        self.rank_progress_var = tk.DoubleVar(value=0.0)
        self.rank_progress = TrainProgressBar(
            left_f,
            variable=self.rank_progress_var,
            mode="determinate",
            thickness=6,
            trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
            fill_color=palette.get("accent_hover", palette.get("accent", "#0e639c")),
            bg=palette.get("panel", "#252526"),
            height=10,
        )
        self.rank_progress.pack(fill=tk.X)
        self.rank_status = ttk.Label(left_f, text="Gotowy", foreground="gray")
        self.rank_status.pack(anchor=tk.W)

        ttk.Label(right_f, text="Tabela wyników", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 6))
        cols = ("Miejsce", "Model", "Zadanie", "F1-Score", "Precision", "Recall")
        self.rank_tree = ttk.Treeview(right_f, columns=cols, show="headings")
        for c in cols: self.rank_tree.heading(c, text=c)
        self.rank_tree.column("Miejsce", width=50, anchor=tk.CENTER)
        self.rank_tree.column("Model", width=160, anchor=tk.W)
        self.rank_tree.column("Zadanie", width=120, anchor=tk.CENTER)
        self.rank_tree.column("F1-Score", width=70, anchor=tk.CENTER)
        self.rank_tree.column("Precision", width=70, anchor=tk.CENTER)
        self.rank_tree.column("Recall", width=70, anchor=tk.CENTER)

        yscroll = WebSlimScrollbar(right_f, orient=tk.VERTICAL, command=self.rank_tree.yview)
        self.rank_tree.configure(yscrollcommand=yscroll.set)
        self.rank_tree.configure(yscrollcommand=yscroll.set)
        self.rank_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        HELP.bind_help(self.rank_category_info_lbl, "tr_rank_cat")
        HELP.bind_help(self.btn_run_rank, "tr_rank_btn")
        HELP.bind_help(row1, "tr_rank_models")
        HELP.bind_help(row2, "tr_rank_reference")
        HELP.bind_help(conf_row, "tr_rank_conf")
        HELP.bind_help(self.rank_tree, "tr_rank_table")

    def _build_ranking_panel_v2(self, parent):
        palette = getattr(self.app, "palette", {})
        shell = ttk.Frame(parent, padding=10, style="Panel.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            shell,
            text=(
                "Ranking dla tablic porównuje kilka modeli YOLO Pose na jednym runie Z2/PZ2, "
                "w którym po sprawdzeniu tablic zapisano zmiany. Wskazujesz folder modeli oraz "
                "folder tego runu, a system sam odczyta obrazy i zapisane poprawki z annotations.xml."
            ),
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=760,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 12))

        pane = ttk.PanedWindow(shell, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        left_f = ttk.Frame(pane, padding=(2, 0, 8, 0), style="Panel.TFrame")
        right_f = ttk.Frame(pane, padding=(8, 0, 0, 0), style="Panel.TFrame")
        pane.add(left_f, weight=1)
        pane.add(right_f, weight=3)

        config_box = ttk.LabelFrame(left_f, text=" Ranking modeli tablic ", padding=10)
        config_box.pack(fill=tk.X)

        ttk.Label(config_box, text="Folder modeli (.pt):", style="Panel.TLabel").pack(anchor=tk.W)
        row1 = ttk.Frame(config_box, style="Panel.TFrame")
        row1.pack(fill=tk.X, pady=(4, 8))
        self.rank_models_dir = tk.StringVar(value=str(self._get_ranking_models_default_dir()))
        ttk.Entry(row1, textvariable=self.rank_models_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            row1,
            text="Wybierz",
            command=lambda: self._pick_dir(
                self.rank_models_dir,
                initialdir=self._get_ranking_models_picker_dir(),
            ),
        ).pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Label(config_box, text="Folder runu po sprawdzeniu tablic:", style="Panel.TLabel").pack(anchor=tk.W)
        row2 = ttk.Frame(config_box, style="Panel.TFrame")
        row2.pack(fill=tk.X, pady=(4, 0))
        self.rank_data_dir = tk.StringVar()
        ttk.Entry(row2, textvariable=self.rank_data_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            row2,
            text="Wybierz",
            command=lambda: self._pick_dir(
                self.rank_data_dir,
                initialdir=self._get_ranking_reference_picker_dir(),
            ),
        ).pack(side=tk.RIGHT, padx=(8, 0))

        self.rank_reference_hint_lbl = ttk.Label(
            config_box,
            text=(
                "Wybierz folder runu Z2/PZ2, w którym po przejrzeniu tablic zapisales zmiany. "
                "W srodku powinny być obrazy i plik annotations.xml."
            ),
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=280,
        )
        self.rank_reference_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 10))

        ttk.Label(
            config_box,
            text=f"Ranking używa domyślnego progu wykrycia: {float(CONFIG.DEFAULT_CONFIDENCE):.2f}.",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=280,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

        rank_actions = ttk.Frame(config_box, style="Panel.TFrame")
        rank_actions.pack(fill=tk.X, pady=(0, 6))
        rank_actions.columnconfigure(0, weight=1)
        rank_actions.columnconfigure(1, weight=1)

        self.btn_run_rank = ttk.Button(
            rank_actions,
            text="Porównaj modele",
            style="Accent.TButton",
            command=self._run_ranking_v2,
        )
        self.btn_run_rank.grid(row=0, column=0, sticky="ew", padx=(0, 4), ipady=4)
        self.btn_cancel_rank = ttk.Button(
            rank_actions,
            text="Anuluj ranking",
            command=self._cancel_ranking_v2,
            state=tk.DISABLED,
        )
        self.btn_cancel_rank.grid(row=0, column=1, sticky="ew", padx=(4, 0), ipady=4)

        self.rank_progress_var = tk.DoubleVar(value=0.0)
        self.rank_progress = TrainProgressBar(
            config_box,
            variable=self.rank_progress_var,
            mode="determinate",
            thickness=6,
            trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
            fill_color=palette.get("accent_hover", palette.get("accent", "#0e639c")),
            bg=palette.get("panel", "#252526"),
            height=10,
        )
        self.rank_progress.pack(fill=tk.X)
        self.rank_status = ttk.Label(config_box, text="Gotowy", style="PanelMuted.TLabel")
        self.rank_status.pack(anchor=tk.W, pady=(4, 0))

        ttk.Label(
            right_f,
            text="Wyniki dla aktywnego zestawu testowego",
            style="Panel.TLabel",
            anchor=tk.W,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        cols = ("Miejsce", "Model", "F1", "Precision", "Recall", "Obrazy", "Zestaw")
        self.rank_tree = ttk.Treeview(right_f, columns=cols, show="headings")
        for c in cols:
            self.rank_tree.heading(c, text=c)
        self.rank_tree.column("Miejsce", width=58, anchor=tk.CENTER, stretch=False)
        self.rank_tree.column("Model", width=200, anchor=tk.W, stretch=True)
        self.rank_tree.column("F1", width=78, anchor=tk.CENTER, stretch=False)
        self.rank_tree.column("Precision", width=82, anchor=tk.CENTER, stretch=False)
        self.rank_tree.column("Recall", width=82, anchor=tk.CENTER, stretch=False)
        self.rank_tree.column("Obrazy", width=70, anchor=tk.CENTER, stretch=False)
        self.rank_tree.column("Zestaw", width=150, anchor=tk.W, stretch=False)

        yscroll = WebSlimScrollbar(right_f, orient=tk.VERTICAL, command=self.rank_tree.yview)
        self.rank_tree.configure(yscrollcommand=yscroll.set)
        self.rank_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        HELP.bind_help(self.btn_run_rank, "tr_rank_btn")
        HELP.bind_help(self.btn_cancel_rank, "tr_rank_btn")
        HELP.bind_help(row1, "tr_rank_models")
        HELP.bind_help(row2, "tr_rank_reference")
        HELP.bind_help(self.rank_reference_hint_lbl, "tr_rank_reference")
        HELP.bind_help(config_box, "tr_rank_conf")
        HELP.bind_help(self.rank_tree, "tr_rank_table")
        self.rank_models_dir.trace_add("write", self._refresh_ranking_reference_ui)
        self.rank_data_dir.trace_add("write", self._refresh_ranking_reference_ui)
        self._prefill_ranking_reference_if_empty()
        self._refresh_ranking_reference_ui()

    def _run_ranking_v2(self):
        if self.rank_is_running:
            return

        self._ensure_plate_ranking_engine()
        models_dir_raw = str(getattr(self, "rank_models_dir", tk.StringVar()).get() or "").strip()
        reference_raw = str(getattr(self, "rank_data_dir", tk.StringVar()).get() or "").strip()
        models_dir = Path(models_dir_raw)

        if not models_dir.exists() or not models_dir.is_dir():
            return messagebox.showerror("Błąd", "Wskaż poprawny folder z modelami .pt.")

        target_task = "Tablice (Pose)"
        if not self._begin_step4_operation("z4.ranking.run", "Z4: ranking modeli"):
            return
        self.rank_is_running = True
        self.rank_cancel_requested = False
        try:
            self.btn_run_rank.config(state=tk.DISABLED)
        except Exception:
            pass
        try:
            self.rank_progress_var.set(0)
        except Exception:
            pass
        self._set_ranking_ui_state(
            status="Przygotowuję ranking...",
            status_color="gray",
            button_text="Przygotowanie...",
            cancel_enabled=True,
            preparing=True,
            progress_value=0,
        )
        self._append_ranking_log("Start przygotowania rankingu modeli tablic.")
        self._append_ranking_log(f"Folder modeli: {models_dir}")
        if reference_raw:
            self._append_ranking_log(f"Wybrany folder runu: {reference_raw}")
        else:
            self._append_ranking_log("Nie wskazano jeszcze folderu runu do porównania.")
        self._start_ranking_watchdog("start przygotowania rankingu")

        def worker():
            from ..ranking.annotation_comparator import AnnotationComparator
            from ..annotators import PlateAnnotator
            from ..exporters.cvat_exporter import CVATExporter

            try:
                ranking_started_at = time.perf_counter()
                cancelled = False
                self._touch_ranking_watchdog("sprawdzanie folderu runu i zapisanych zmian")
                self._set_ranking_ui_state(
                    status="Sprawdzam folder runu i zapisane zmiany...",
                    status_color="gray",
                    button_text="Przygotowanie...",
                    cancel_enabled=True,
                    preparing=True,
                )
                reference_info = self._resolve_ranking_reference_source(reference_raw)
                if not reference_info.get("ok"):
                    self._append_ranking_log(str(reference_info.get("message") or "Nie udało się przygotować folderu runu."))
                    self._ui(
                        lambda: messagebox.showerror(
                            "Błąd",
                            str(reference_info.get("message") or "Wskaż poprawny folder runu po sprawdzeniu tablic."),
                        )
                    )
                    return
                if not self.rank_is_running:
                    cancelled = True
                    self._append_ranking_log("Przerwano ranking po przygotowaniu folderu runu.")
                    return

                self._append_ranking_log(
                    f"Run odniesienia: {reference_info.get('reference_name') or '-'} | "
                    f"obrazy: {int(reference_info.get('image_count', 0) or 0)}"
                )
                self._append_ranking_log(
                    f"Przygotowanie folderu runu zajelo {time.perf_counter() - ranking_started_at:.1f}s."
                )
                self._touch_ranking_watchdog("szukanie modeli YOLO Pose")

                self._set_ranking_ui_state(
                    status="Szukam modeli YOLO Pose...",
                    status_color="gray",
                    button_text="Przygotowanie...",
                    cancel_enabled=True,
                    preparing=True,
                )
                model_files = sorted(models_dir.glob("*.pt"))
                models_to_test = [mf for mf in model_files if "pose" in mf.name.lower()]
                if not self.rank_is_running:
                    cancelled = True
                    self._append_ranking_log("Przerwano ranking po odczytaniu listy modeli.")
                    return

                if not models_to_test:
                    self._append_ranking_log("Nie znaleziono modeli YOLO Pose w wybranym folderze.")
                    self._ui(lambda: messagebox.showinfo("Info", "Brak modeli YOLO Pose (.pt) w wybranym folderze."))
                    return

                gt_xml = Path(str(reference_info.get("xml_path") or "").strip())
                images = list(reference_info.get("image_paths") or [])
                if not gt_xml.exists() or not images:
                    self._append_ranking_log("Wybrany folder runu nie zawiera kompletu obrazów i zapisanych zmian tablic.")
                    self._ui(
                        lambda: messagebox.showerror(
                            "Błąd",
                            "Wybrany folder nie zawiera kompletu obrazów i zapisanych zmian tablic.",
                        )
                    )
                    return

                comparator = AnnotationComparator()
                selected_device_display = self._normalize_training_device_choice(self.device_var.get())
                effective_device_raw, effective_device_profile = self._get_effective_training_device_profile(selected_device_display)
                device = self._device_to_ultralytics(self.device_var.get())
                if effective_device_profile is not None:
                    effective_device_desc = (
                        f"{effective_device_profile.get('name', effective_device_raw)} "
                        f"({float(effective_device_profile.get('memory_gb', 0.0) or 0.0):.1f} GB VRAM)"
                    )
                else:
                    effective_device_desc = "CPU"
                conf_thresh = float(CONFIG.DEFAULT_CONFIDENCE)
                total_models = len(models_to_test)
                temp_xml_path = Path(str(reference_info.get("reference_dir") or models_dir)) / "temp_ranking_auto.xml"
                self._append_ranking_log(
                    f"Przygotowanie zakończone. Modele pose: {total_models} | obrazy do porównania: {len(images)}"
                )
                self._append_ranking_log(
                    f"Urządzenie rankingu: {selected_device_display} -> {effective_device_desc} | backend Ultralytics: {device}"
                )
                self._set_ranking_ui_state(
                    status=f"Porównywanie modeli... 0/{total_models}",
                    status_color="gray",
                    button_text="Porównywanie...",
                    cancel_enabled=True,
                    preparing=False,
                    progress_value=0,
                )

                for idx, model_path in enumerate(models_to_test):
                    if not self.rank_is_running:
                        cancelled = True
                        break

                    model_started_at = time.perf_counter()
                    self._touch_ranking_watchdog(f"ladowanie modelu {model_path.name}")
                    self._append_ranking_log(f"{idx + 1}/{total_models} | Start modelu: {model_path.name}")
                    self._ui(
                        lambda m=model_path.name, current=idx + 1, total=total_models:
                            self.rank_status.config(text=f"Ładowanie modelu {m} ({current}/{total})")
                    )

                    annotator = PlateAnnotator(model_path, conf_thresh, device)
                    success, _msg = annotator.load_models()
                    if not self.rank_is_running:
                        cancelled = True
                        try:
                            annotator.unload_models()
                        except Exception:
                            pass
                        break
                    if not success:
                        self._append_ranking_log(f"Pominieto model {model_path.name}: nie udało się go załadować.")
                        continue
                    self._append_ranking_log(
                        f"{idx + 1}/{total_models} | Model załadowany po {time.perf_counter() - model_started_at:.1f}s. "
                        f"Start analizy {len(images)} obrazów."
                    )
                    self._touch_ranking_watchdog(f"{model_path.name}: start analizy obrazów")

                    auto_annotations = []
                    for img_idx, img_path in enumerate(images):
                        if not self.rank_is_running:
                            cancelled = True
                            break
                        self._touch_ranking_watchdog(
                            f"{model_path.name}: analiza obrazu {img_idx + 1}/{len(images)}"
                        )
                        auto_annotations.append(annotator.process_image(img_path))
                        sub_pct = ((idx + ((img_idx + 1) / max(1, len(images)))) / max(1, total_models)) * 100
                        self._ui(lambda p=sub_pct: self.rank_progress_var.set(p))
                        if (img_idx == 0) or ((img_idx + 1) % 10 == 0) or (img_idx + 1 == len(images)):
                            self._set_ranking_ui_state(
                                status=(
                                    f"Model {model_path.name} | obraz {img_idx + 1}/{len(images)} "
                                    f"({idx + 1}/{total_models})"
                                ),
                                status_color="gray",
                            )
                        if ((img_idx + 1) % 25 == 0) or (img_idx + 1 == len(images)):
                            self._append_ranking_log(
                                f"{idx + 1}/{total_models} | {model_path.name} | obrazy: {img_idx + 1}/{len(images)}"
                            )

                    annotator.unload_models()
                    if cancelled:
                        break
                    self._touch_ranking_watchdog(f"{model_path.name}: eksport i porównanie wyników")
                    self._set_ranking_ui_state(
                        status=f"Analiza wyników {model_path.name}...",
                        status_color="gray",
                    )

                    exporter = CVATExporter()
                    exporter.export(auto_annotations, temp_xml_path, include_confidence=True)

                    stats = comparator.compare(auto_xml_path=temp_xml_path, corrected_xml_path=gt_xml)
                    self.ranking_engine.add_entry(
                        model_name=model_path.name,
                        model_path=str(model_path),
                        comparison_stats=stats,
                        task_type=target_task,
                        reference_name=str(reference_info.get("reference_name") or ""),
                        reference_path=str(reference_info.get("reference_dir") or ""),
                        save=False,
                    )
                    precision = float(stats.get("precision", 0) or 0)
                    recall = float(stats.get("recall", 0) or 0)
                    f1_score = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
                    self._append_ranking_log(
                        f"Zakończono {model_path.name} | Precision={precision:.1f}% | "
                        f"Recall={recall:.1f}% | F1={f1_score:.1f}% | czas: {time.perf_counter() - model_started_at:.1f}s"
                    )

                    if temp_xml_path.exists():
                        temp_xml_path.unlink()

                try:
                    self._touch_ranking_watchdog("zapisywanie wyników rankingu")
                    self.ranking_engine.flush()
                except Exception as save_error:
                    self._append_ranking_log(f"Ostrzeżenie: nie udało się zapisać rankingu: {save_error}")
                if cancelled or self.rank_cancel_requested:
                    self._append_ranking_log("Ranking anulowany przez użytkownika.")
                    self._ui(lambda: self._load_ranking())
                    self._ui(lambda: self.rank_status.config(text="Ranking anulowany.", foreground="#d35400"))
                else:
                    self._append_ranking_log("Ranking zakończony.")
                    self._ui(lambda: self.rank_progress_var.set(100))
                    self._ui(lambda: self._load_ranking())
                    self._ui(lambda: self.rank_status.config(text="Ranking zakończony.", foreground="green"))

            except Exception as e:
                self._append_ranking_log(f"Błąd rankingu: {e}")
                self._ui(lambda err=e: messagebox.showerror("Błąd", f"Błąd w trakcie rankingu:\n{err}"))
                self._ui(lambda: self.rank_status.config(text="Błąd rankingu", foreground="red"))
            finally:
                self._stop_ranking_watchdog()
                self.rank_is_running = False
                self.rank_cancel_requested = False
                self._end_step4_operation("z4.ranking.run")
                self._set_ranking_ui_state(button_text="Porównaj modele", cancel_enabled=False, preparing=False)
                self._ui(lambda: self._refresh_ranking_start_state())
                self._ui(self._refresh_training_start_state)

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_ranking_v2(self):
        if not getattr(self, "rank_is_running", False):
            return

        self.rank_cancel_requested = True
        self.rank_is_running = False
        self._touch_ranking_watchdog("przerywanie rankingu")
        self._append_ranking_log("Użytkownik zazadal przerwania rankingu. Czekam na bezpieczne zatrzymanie...")
        self._set_ranking_ui_state(
            status="Przerywanie rankingu...",
            status_color="#d35400",
            button_text="Przerywanie...",
            cancel_enabled=False,
            preparing=False,
        )

    def _pick_file(self, var, ext, initialdir=None):
        kwargs = {"filetypes": [("File", ext)]}
        if initialdir and Path(initialdir).exists():
            kwargs["initialdir"] = str(initialdir)
            
        p = filedialog.askopenfilename(**kwargs)
        if p:
            var.set(p)
            try:
                self._refresh_dataset_creator_cta_state()
            except Exception:
                pass
            try:
                self._refresh_dataset_split_cta_state()
            except Exception:
                pass
        return p
        
    def _pick_dir(self, var, initialdir=None):
        kwargs = {}
        if initialdir and Path(initialdir).exists():
            kwargs["initialdir"] = str(initialdir)
            
        p = filedialog.askdirectory(**kwargs)
        if p:
            var.set(p)
            try:
                self._refresh_dataset_creator_cta_state()
            except Exception:
                pass
            try:
                self._refresh_dataset_split_cta_state()
            except Exception:
                pass
        return p

    def _update_ratio_labels(self):
        train = float(self.train_pct.get())
        val = float(self.val_pct.get())
        max_train_plus_val = 95.0
        if train + val > max_train_plus_val:
            val = max(5.0, max_train_plus_val - train)
            self.val_pct.set(val)

        test = max(5.0, 100.0 - train - val)
        for attr_name, value in (
            ("train_lbl", f"{train:.0f}%"),
            ("val_lbl", f"{val:.0f}%"),
            ("test_lbl", f"Test: {test:.0f}%"),
            ("creator_train_lbl", f"{train:.0f}%"),
            ("creator_val_lbl", f"{val:.0f}%"),
            ("creator_test_lbl", f"Test: {test:.0f}%"),
        ):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.configure(text=value)
                except Exception:
                    pass
                self._style_training_success_label(widget)

    def _on_base_model_change(self):
        try:
            self._refresh_training_base_model_selection_ui()
        except Exception:
            pass
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

    def _on_cvat_xml_source_changed(self):
        try:
            self._refresh_dataset_creator_cta_state()
        except Exception:
            pass
        try:
            self._cvat_source_binding_generation = int(getattr(self, "_cvat_source_binding_generation", 0) or 0) + 1
        except Exception:
            self._cvat_source_binding_generation = 1
        try:
            self._schedule_cvat_source_binding_refresh()
        except Exception:
            pass

    def _on_cvat_images_source_changed(self):
        try:
            self._refresh_dataset_creator_cta_state()
        except Exception:
            pass
        try:
            self._cvat_source_binding_generation = int(getattr(self, "_cvat_source_binding_generation", 0) or 0) + 1
        except Exception:
            self._cvat_source_binding_generation = 1
        pending = getattr(self, "_cvat_source_binding_after_id", None)
        if pending and hasattr(self, "frame") and self.frame is not None:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._cvat_source_binding_after_id = None

    def _schedule_cvat_source_binding_refresh(self, delay_ms: int = 180):
        if not hasattr(self, "frame") or self.frame is None:
            return
        try:
            if self._get_creator_source_mode() != "xml":
                return
        except Exception:
            pass

        pending = getattr(self, "_cvat_source_binding_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass

        try:
            token = int(getattr(self, "_cvat_source_binding_generation", 0) or 0)
        except Exception:
            token = 0

        self._cvat_source_binding_after_id = self.frame.after(
            max(0, int(delay_ms)),
            lambda expected_token=token: self._auto_bind_cvat_images_dir_from_xml(expected_token),
        )

    def _normalize_cvat_xml_image_relpath(self, raw_name: str) -> str:
        raw = str(raw_name or "").strip().replace("\\", "/")
        while raw.startswith("./"):
            raw = raw[2:]

        parts = [part for part in PurePosixPath(raw).parts if part not in ("", ".")]
        return "/".join(parts)

    def _cvat_xml_relpath_to_path(self, rel_path: str) -> Path:
        parts = [part for part in PurePosixPath(rel_path).parts if part not in ("", ".")]
        return Path(*parts) if parts else Path()

    def _read_cvat_xml_image_names(self, xml_path: Path) -> list[str]:
        tree = ET.parse(xml_path)
        names: list[str] = []
        for image_el in tree.getroot().findall(".//image"):
            normalized = self._normalize_cvat_xml_image_relpath(image_el.get("name") or "")
            if normalized:
                names.append(normalized)
        return list(dict.fromkeys(names))

    def _evaluate_images_dir_for_cvat_xml(self, images_dir: Path, xml_image_names: list[str]) -> dict:
        matched = 0
        missing: list[str] = []
        for rel_name in xml_image_names:
            candidate = Path(images_dir) / self._cvat_xml_relpath_to_path(rel_name)
            if candidate.exists() and candidate.is_file():
                matched += 1
            else:
                missing.append(rel_name)
        return {
            "images_dir": Path(images_dir),
            "total": len(xml_image_names),
            "matched": matched,
            "missing_count": len(missing),
            "missing": missing,
        }

    def _get_cvat_image_source_roots(self) -> list[Path]:
        roots: list[Path] = []

        for getter in (
            lambda: CAMPAIGN.get_iteration_image_source_dir(),
            lambda: CAMPAIGN.get_iteration_raw_dir(),
            lambda: CAMPAIGN.get_master_pool_dir(),
            lambda: CAMPAIGN.get_dir("raw"),
        ):
            try:
                candidate = getter()
                if candidate:
                    roots.append(Path(candidate))
            except Exception:
                pass

        try:
            roots.append(Path(CONFIG.DIR_1_RAW))
        except Exception:
            pass

        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            try:
                resolved = str(root.resolve())
            except Exception:
                resolved = str(root)
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                if root.exists() and root.is_dir():
                    unique.append(root)
            except Exception:
                pass
        return unique

    def _derive_cvat_candidate_root_for_match(self, found_file: Path, xml_rel_name: str) -> Path | None:
        parts = [part for part in PurePosixPath(xml_rel_name).parts if part not in ("", ".")]
        if not parts:
            return None

        ascend_levels = len(parts) - 1
        parents = found_file.parents
        if ascend_levels >= len(parents):
            return None

        candidate_root = parents[ascend_levels]
        try:
            expected_path = (candidate_root / self._cvat_xml_relpath_to_path(xml_rel_name)).resolve()
            if expected_path != found_file.resolve():
                return None
        except Exception:
            return None

        return candidate_root

    def _find_matching_images_dir_for_cvat_xml(self, xml_image_names: list[str]) -> dict | None:
        if not xml_image_names:
            return None

        search_roots = self._get_cvat_image_source_roots()
        if not search_roots:
            return None

        sample_names = xml_image_names[: min(24, len(xml_image_names))]
        sample_by_basename: dict[str, list[str]] = {}
        for rel_name in sample_names:
            sample_by_basename.setdefault(PurePosixPath(rel_name).name, []).append(rel_name)

        candidate_hits: dict[str, dict] = {}
        for search_root in search_roots:
            try:
                for file_path in search_root.rglob("*"):
                    if not file_path.is_file():
                        continue
                    candidate_rel_names = sample_by_basename.get(file_path.name)
                    if not candidate_rel_names:
                        continue
                    for rel_name in candidate_rel_names:
                        candidate_root = self._derive_cvat_candidate_root_for_match(file_path, rel_name)
                        if candidate_root is None:
                            continue
                        try:
                            key = str(candidate_root.resolve())
                        except Exception:
                            key = str(candidate_root)
                        entry = candidate_hits.setdefault(
                            key,
                            {"images_dir": candidate_root, "sample_hits": set()},
                        )
                        entry["sample_hits"].add(rel_name)
            except Exception as exc:
                logger.debug(f"Nie udało się przeskanować {search_root} przy dopasowaniu obrazów do XML: {exc}")

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
            stats = self._evaluate_images_dir_for_cvat_xml(candidate["images_dir"], xml_image_names)
            stats["sample_hits"] = len(candidate["sample_hits"])
            score = (stats["matched"], -stats["missing_count"], stats["sample_hits"])
            if best_match is None or score > best_score:
                best_match = stats
                best_score = score
        return best_match

    def _auto_bind_cvat_images_dir_from_xml(self, expected_token: int | None = None):
        self._cvat_source_binding_after_id = None

        try:
            current_token = int(getattr(self, "_cvat_source_binding_generation", 0) or 0)
            if expected_token is not None and int(expected_token) != current_token:
                return
        except Exception:
            pass

        try:
            if self._get_creator_source_mode() != "xml":
                return
        except Exception:
            pass

        xml_raw = str(getattr(self, "cvat_xml_var", tk.StringVar()).get() or "").strip()
        if not xml_raw:
            return
        try:
            xml_path = Path(xml_raw)
        except Exception:
            return
        if not xml_path.exists() or not xml_path.is_file():
            return

        try:
            xml_image_names = self._read_cvat_xml_image_names(xml_path)
        except Exception as exc:
            logger.debug(f"Nie udało się odczytać nazw obrazów z XML dla PZ1: {exc}")
            return
        if not xml_image_names:
            return

        images_raw = str(getattr(self, "cvat_images_var", tk.StringVar()).get() or "").strip()
        if images_raw:
            try:
                current_dir = Path(images_raw)
                if current_dir.exists() and current_dir.is_dir():
                    current_stats = self._evaluate_images_dir_for_cvat_xml(current_dir, xml_image_names)
                    if current_stats["matched"] == current_stats["total"]:
                        return
            except Exception:
                pass

        best_candidate = self._find_matching_images_dir_for_cvat_xml(xml_image_names)
        if not best_candidate or best_candidate.get("matched") != best_candidate.get("total"):
            return

        try:
            current_token = int(getattr(self, "_cvat_source_binding_generation", 0) or 0)
            if expected_token is not None and int(expected_token) != current_token:
                return
        except Exception:
            pass

        # Użytkownik mógł wskazać folder ręcznie w czasie oczekiwania na automatyczne dopasowanie.
        # Wtedy nie pokazujemy spóźnionego modala, nawet jeśli folder wymaga dalszej walidacji.
        latest_images_raw = str(getattr(self, "cvat_images_var", tk.StringVar()).get() or "").strip()
        if latest_images_raw and latest_images_raw != images_raw:
            return

        candidate_dir = Path(best_candidate["images_dir"])
        try:
            display_dir = self._format_workspace_relative_path(candidate_dir)
        except Exception:
            display_dir = str(candidate_dir)

        attach = messagebox.askyesno(
            "Znaleziono zgodny folder obrazów",
            (
                "Na podstawie pliku XML znaleziono folder zawierający komplet zgodnych obrazów.\n\n"
                f"Dopasowanie: {best_candidate['matched']}/{best_candidate['total']} plików z XML\n"
                f"Folder: {display_dir}\n\n"
                "Czy podpiąć ten folder jako źródło obrazów dla kreatora PZ1?"
            ),
            parent=getattr(self, "frame", None),
        )
        if not attach:
            try:
                status = getattr(self, "ds_status", None)
                if status is not None:
                    self._style_training_success_label(status)
                    self._set_training_widget_text(
                        status,
                        "Znaleziono zgodny folder obrazów, ale podpięcie anulowano. Wskaż folder ręcznie albo wybierz XML ponownie.",
                    )
            except Exception:
                pass
            return

        try:
            self.cvat_images_var.set(str(candidate_dir.resolve()))
        except Exception:
            self.cvat_images_var.set(str(candidate_dir))

        try:
            status = getattr(self, "ds_status", None)
            if status is not None:
                self._style_training_success_label(status)
                self._set_training_widget_text(
                    status,
                    f"Podpięto zgodny folder obrazów: {best_candidate['matched']}/{best_candidate['total']} plików z XML w {display_dir}.",
                )
        except Exception:
            pass

    def _get_creator_source_mode(self) -> str:
        try:
            mode = str(self.creator_source_mode_var.get() or "").strip().lower()
        except Exception:
            mode = ""
        return mode if mode in {"ready", "xml"} else "xml"

    def _set_creator_source_mode(self, mode: str):
        normalized = str(mode or "").strip().lower()
        if normalized not in {"ready", "xml"}:
            normalized = "xml"
        try:
            self.creator_source_mode_var.set(normalized)
        except Exception:
            pass

    def _on_creator_source_mode_change(self):
        try:
            self._refresh_step4_dataset_mode_ui()
        except Exception:
            pass
        try:
            self._refresh_dataset_creator_cta_state()
        except Exception:
            pass

    def _resolve_dataset_creator_inputs(self) -> dict:
        result = {
            "ok": False,
            "xml": None,
            "images_dir": None,
            "message": "W trybie budowy z XML wymagane są dwa zgodne źródła: plik XML i folder obrazów.",
        }

        xml_raw = str(getattr(self, "cvat_xml_var", tk.StringVar()).get() or "").strip()
        images_raw = str(getattr(self, "cvat_images_var", tk.StringVar()).get() or "").strip()

        if not xml_raw:
            return result
        try:
            xml_path = Path(xml_raw)
        except Exception:
            result["message"] = "Nie udało się odczytać ścieżki pliku XML."
            return result
        if not xml_path.exists() or not xml_path.is_file() or xml_path.suffix.lower() != ".xml":
            result["message"] = "Wskaż istniejący plik anotacji XML."
            return result

        if not images_raw:
            result["message"] = "Wskaż folder obrazów dla tego pliku XML."
            return result
        try:
            images_dir = Path(images_raw)
        except Exception:
            result["message"] = "Nie udało się odczytać ścieżki folderu obrazów."
            return result
        if not images_dir.exists() or not images_dir.is_dir():
            result["message"] = "Wskaż istniejący folder obrazów."
            return result

        result.update(
            {
                "ok": True,
                "xml": xml_path,
                "images_dir": images_dir,
                "message": "Gotowy do utworzenia wariantu datasetu treningowego.",
            }
        )
        return result

    @staticmethod
    def _normalize_xml_image_name(image_name: str) -> str:
        return str(image_name or "").strip().replace("\\", "/")

    def _validate_dataset_creator_xml_images_alignment(self, images_dir: Path) -> dict:
        result = {
            "ok": False,
            "message": "Nie udało się porównać XML z folderem obrazów.",
            "missing": [],
            "extra_count": 0,
        }

        try:
            images_dir = Path(images_dir)
        except Exception:
            return result

        if not images_dir.exists() or not images_dir.is_dir():
            result["message"] = "Folder obrazów nie istnieje."
            return result

        xml_names = {
            self._normalize_xml_image_name(name)
            for name in set(getattr(self.creator, "xml_image_names", set()) or set())
            if str(name or "").strip()
        }
        annotated_names = {
            self._normalize_xml_image_name(name)
            for name in set(self.creator.get_annotated_image_names() or set())
            if str(name or "").strip()
        }
        required_names = xml_names or annotated_names
        if not required_names:
            result["message"] = "XML nie zawiera obrazów do walidacji."
            return result

        missing = []
        for image_name in sorted(required_names):
            candidate = images_dir / Path(image_name)
            if not candidate.exists() or not candidate.is_file():
                missing.append(image_name)

        if missing:
            sample = ", ".join(missing[:8])
            more = "" if len(missing) <= 8 else f" oraz {len(missing) - 8} więcej"
            result["missing"] = missing
            result["message"] = (
                "Plik XML i folder obrazów nie są zgodne.\n\n"
                f"W XML jest {len(required_names)} obraz(ów), ale w wybranym folderze brakuje {len(missing)}.\n"
                f"Przykłady brakujących: {sample}{more}.\n\n"
                "Wskaż folder, względem którego nazwy obrazów z XML istnieją dokładnie tak samo."
            )
            return result

        try:
            direct_image_names = {path.name for path in get_image_files(images_dir)}
            xml_basenames = {Path(name).name for name in required_names}
            extra_count = len([name for name in direct_image_names if name not in xml_basenames])
        except Exception:
            extra_count = 0

        result.update(
            {
                "ok": True,
                "message": (
                    f"XML i folder obrazów są zgodne: {len(required_names)} obraz(ów) z XML "
                    "ma odpowiadający plik źródłowy."
                ),
                "extra_count": int(extra_count),
            }
        )
        return result

    def _refresh_dataset_creator_cta_state(self):
        btn = getattr(self, "btn_step4_create", None)
        if btn is None:
            return

        try:
            in_campaign = bool(CAMPAIGN.get_active_project_name())
        except Exception:
            in_campaign = False
        if not in_campaign and self._get_creator_source_mode() == "ready":
            try:
                btn.configure(state=tk.DISABLED)
            except Exception:
                pass
            status = getattr(self, "ds_status", None)
            if status is not None:
                try:
                    self._style_training_success_label(status)
                    self._set_training_widget_text(
                        status,
                        "Gotowy dataset jest już wejściem treningowym. Przejdź dalej do PZ2.",
                    )
                except Exception:
                    pass
            return

        info = self._resolve_dataset_creator_inputs()
        try:
            busy = bool(self._step4_has_active_operation())
        except Exception:
            busy = False

        enabled = bool(info.get("ok")) and not busy
        try:
            btn.configure(state=(tk.NORMAL if enabled else tk.DISABLED))
        except Exception:
            pass

        status = getattr(self, "ds_status", None)
        if status is None:
            return
        try:
            if busy:
                self._style_training_success_label(status)
                self._set_training_widget_text(status, "Przygotowanie datasetu jest w toku...")
            elif enabled:
                self._style_training_success_label(status)
                self._set_training_widget_text(status, str(info.get("message") or "Gotowy."))
            else:
                self._style_training_success_label(status)
                self._set_training_widget_text(status, str(info.get("message") or "Uzupełnij źródło datasetu."))
        except Exception:
            pass

    def _resolve_dataset_split_inputs(self) -> dict:
        result = {
            "ok": False,
            "src": None,
            "message": (
                "Wskaż źródło YOLO Detect dla znaków: folder z images/labels albo plik data.yaml. "
                "Dataset OCR/klasyfikacyjny z manifest.json nie jest wejściem tego kroku."
            ),
        }

        src_raw = str(getattr(self, "split_src_var", tk.StringVar()).get() or "").strip()
        if not src_raw:
            return result

        validation = self._validate_char_yolo_split_source(src_raw, resolve_nested_dataset=True)
        if not bool(validation.get("ok")):
            result["message"] = str(validation.get("message") or result["message"])
            return result

        result.update(
            {
                "ok": True,
                "src": validation.get("src"),
                "message": str(validation.get("message") or "Gotowy do utworzenia wariantu datasetu treningowego."),
            }
        )
        return result

    def _refresh_dataset_split_cta_state(self):
        btn = getattr(self, "btn_step4_split", None)
        if btn is None:
            return

        info = self._resolve_dataset_split_inputs()
        try:
            busy = bool(self._step4_has_active_operation())
        except Exception:
            busy = False

        enabled = bool(info.get("ok")) and not busy
        try:
            btn.configure(state=(tk.NORMAL if enabled else tk.DISABLED))
        except Exception:
            pass

        status = getattr(self, "split_status", None)
        if status is None:
            return
        try:
            if busy:
                self._style_training_success_label(status)
                self._set_training_widget_text(status, "Przygotowanie datasetu jest w toku...")
            elif enabled:
                self._style_training_success_label(status)
                self._set_training_widget_text(status, str(info.get("message") or "Gotowy."))
            else:
                self._style_training_success_label(status)
                self._set_training_widget_text(status, str(info.get("message") or "Uzupełnij źródło datasetu."))
        except Exception:
            pass

    def _can_open_pz2_after_dataset_result(self) -> bool:
        if CAMPAIGN.get_active_project_name():
            return bool(getattr(self, "_step4_train_unlocked", False))
        return True

    def _show_step4_dataset_result_modal(
        self,
        *,
        title: str,
        body: str,
        allow_pz2: bool = True,
        primary_text: str = "Przejdź do PZ2",
        secondary_text: str = "Zostań w PZ1",
    ) -> bool:
        parent = getattr(self, "frame", None)
        root = parent.winfo_toplevel() if parent is not None else None
        dialog = tk.Toplevel(root or parent)
        dialog.title(title)
        dialog.resizable(False, False)
        try:
            dialog.transient(root)
            dialog.grab_set()
        except Exception:
            pass

        result = {"go_pz2": False}
        container = ttk.Frame(dialog, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            container,
            text=title,
            font=("Segoe UI Semibold", 11),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X)
        ttk.Label(
            container,
            text=str(body or "").strip(),
            justify=tk.LEFT,
            wraplength=500,
        ).pack(anchor=tk.W, fill=tk.X, pady=(10, 14))

        buttons = ttk.Frame(container)
        buttons.pack(anchor=tk.E, fill=tk.X)

        def close(go_pz2: bool = False):
            result["go_pz2"] = bool(go_pz2)
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        pz2_btn = ttk.Button(
            buttons,
            text=primary_text,
            command=lambda: close(True),
            state=(tk.NORMAL if allow_pz2 else tk.DISABLED),
        )
        pz2_btn.pack(side=tk.RIGHT)
        ttk.Button(
            buttons,
            text=secondary_text,
            command=lambda: close(False),
        ).pack(side=tk.RIGHT, padx=(0, 8))

        dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
        try:
            dialog.update_idletasks()
            if root is not None:
                x = root.winfo_rootx() + max(40, (root.winfo_width() - dialog.winfo_width()) // 2)
                y = root.winfo_rooty() + max(40, (root.winfo_height() - dialog.winfo_height()) // 2)
                dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass

        try:
            dialog.wait_window()
        except Exception:
            pass
        return bool(result.get("go_pz2"))

    def _format_step4_dataset_result_path(self, dataset_path: str | Path | None) -> str:
        raw = str(dataset_path or "").strip()
        if not raw:
            return ""
        try:
            return self._format_workspace_relative_path(raw)
        except Exception:
            return raw

    def _open_pz2_from_dataset_result(self):
        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass
        try:
            self._step4_dataset_go_next()
        except Exception:
            try:
                self.main_nb.select(self.tab_train)
            except Exception:
                pass

    def _handle_step4_dataset_success_result(
        self,
        *,
        dataset_path: str | Path,
        message: str,
        target: str,
        counts: dict | None = None,
    ):
        self._mark_step4_dataset_ready(dataset_path)
        target_label = self._format_training_target_label(target)
        path_text = self._format_step4_dataset_result_path(dataset_path)
        counts = counts or {}
        split_text = ""
        if counts:
            split_text = (
                "\n\nSplit wariantu: "
                f"train={int(counts.get('train', 0) or 0)}, "
                f"val={int(counts.get('val', 0) or 0)}, "
                f"test={int(counts.get('test', 0) or 0)}."
            )

        body = "Dataset został utworzony."
        details = []
        if target_label:
            details.append(f"Tor: {target_label}.")
        if path_text:
            details.append(f"Dataset: {path_text}")
        if split_text:
            details.append(split_text.strip())
        if details:
            body += "\n\n" + "\n".join(details)
        extra = str(message or "").strip()
        if extra:
            body += f"\n\nKomunikat procesu: {extra}"

        if self._show_step4_dataset_result_modal(
            title="Tworzenie datasetu",
            body=body,
            allow_pz2=True,
        ):
            self._open_pz2_from_dataset_result()

    def _handle_step4_dataset_failure_result(
        self,
        *,
        message: str,
        target: str,
        critical: bool = False,
    ):
        target_label = self._format_training_target_label(target)
        allow_pz2 = self._can_open_pz2_after_dataset_result()
        reason = str(message or "Nieznany błąd").strip()
        body = (
            "Dataset nie został utworzony.\n\n"
            f"Przyczyna niepowodzenia: {reason}"
        )

        if self._show_step4_dataset_result_modal(
            title="Tworzenie datasetu",
            body=body,
            allow_pz2=allow_pz2,
        ):
            self._open_pz2_from_dataset_result()

    def _create_dataset_thread(self):
        source_info = self._resolve_dataset_creator_inputs()
        if not bool(source_info.get("ok")):
            self._refresh_dataset_creator_cta_state()
            self._handle_step4_dataset_failure_result(
                message=str(source_info.get("message") or "Najpierw wskaż plik anotacji XML i folder obrazów."),
                target="plate",
                critical=False,
            )
            return

        xml = Path(source_info["xml"])
        images_dir = Path(source_info["images_dir"])
        stage_source_images_dir = images_dir
        stage_source_image_paths = None

        try:
            if bool(CAMPAIGN.get_active_project_name()) and self._get_selected_training_target() == "plate":
                campaign_iter_raw = CAMPAIGN.get_iteration_image_source_dir() or CAMPAIGN.get_iteration_raw_dir()
                if campaign_iter_raw is not None and Path(campaign_iter_raw).exists():
                    stage_source_images_dir = Path(campaign_iter_raw)
                try:
                    manifest_count = int(CAMPAIGN.get_iteration_manifest_image_count() or 0)
                except Exception:
                    manifest_count = 0
                if manifest_count > 0:
                    stage_source_image_paths = list(
                        CAMPAIGN.get_iteration_manifest_image_paths(base_dir=stage_source_images_dir) or []
                    )
        except Exception:
            stage_source_images_dir = images_dir
            stage_source_image_paths = None

        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Dataset zapisuj w katalogu projektu albo w przestrzeni globalnej.
        base_datasets_dir = self._get_datasets_base_dir()
        out_dir = base_datasets_dir / f"Plates_CVAT_{timestamp}"

        # Pokaż użytkownikowi docelową ścieżkę zapisu.
        self.ds_out_var.set(str(out_dir))

        # Wyczyść poprzedni stan parsera przed nowym odczytem XML.
        try:
            if hasattr(self.creator, "annotations"):
                self.creator.annotations = []
        except Exception:
            pass

        ok, msg, _ = self.creator.parse_cvat_xml(xml)
        if not ok:
            self._handle_step4_dataset_failure_result(
                message=str(msg or "Nie udało się odczytać pliku XML."),
                target="plate",
                critical=False,
            )
            return

        alignment = self._validate_dataset_creator_xml_images_alignment(images_dir)
        if not bool(alignment.get("ok")):
            self._style_training_error_label(self.ds_status)
            self._set_training_widget_text(self.ds_status, "XML i folder obrazów nie są zgodne.")
            self._handle_step4_dataset_failure_result(
                message=str(alignment.get("message") or "Wskaż zgodny plik XML i folder obrazów."),
                target="plate",
                critical=False,
            )
            return
        try:
            self._append_step4_builder_log(f"[WALIDACJA] {alignment.get('message')}")
        except Exception:
            pass

        train = float(self.train_pct.get()) / 100.0
        val = float(self.val_pct.get()) / 100.0
        ratios = {
            "train": train,
            "val": val,
            "test": max(0.0, 1.0 - train - val)
        }

        if not self._begin_step4_operation("z4.dataset.build", "Z4: przygotowanie datasetu tablic"):
            return
        self.dataset_build_is_running = True

        self._configure_train_progress_styles()
        self.ds_progress_var.set(0)
        self._style_training_success_label(self.ds_status)
        self._set_training_widget_text(self.ds_status, "Rozpoczynam przygotowanie datasetu...")

        def worker():
            try:
                stage_result = {
                    "enabled": bool(CAMPAIGN.get_active_project_name()) and self._get_selected_training_target() == "plate",
                    "ok": False,
                    "message": "",
                    "pending_count": 0,
                    "stage_images_total": 0,
                    "stage_images_dir": "",
                }
                def prog(c, t, n):
                    pct = (c / t) * 100 if t > 0 else 0
                    self._ui(lambda: self.ds_progress_var.set(pct))
                    self._ui(lambda: self._style_training_success_label(self.ds_status))
                    self._ui(lambda c=int(c), t=int(t): self._set_training_widget_text(self.ds_status, f"{c}/{t} obrazów..."))

                ok2, msg2, _ = self.creator.create_dataset(images_dir, out_dir, ratios, prog)

                if ok2:
                    dataset_counts = self._get_dataset_split_image_counts(out_dir)
                    try:
                        source_run_dir = xml.parent if xml.name.lower() == "annotations.xml" else None
                        self._write_plate_dataset_source_manifest(
                            out_dir,
                            source_kind="z4_cvat_builder",
                            source_run_dir=source_run_dir,
                            source_xml_path=xml,
                            source_images_dir=images_dir,
                        )
                    except Exception as e:
                        logger.debug(f"Nie udało się zapisac manifestu źródła datasetu Z4: {e}")

                    if stage_result["enabled"]:
                        stage_ok, stage_msg, stage_stats = self.creator.sync_pending_stage(
                            stage_source_images_dir,
                            self._get_manual_plate_stage_dir(),
                            source_image_paths=stage_source_image_paths,
                        )
                        stage_result["ok"] = bool(stage_ok)
                        stage_result["message"] = str(stage_msg or "").strip()
                        if isinstance(stage_stats, dict):
                            stage_result["pending_count"] = int(stage_stats.get("pending_count", 0) or 0)
                            stage_result["stage_images_total"] = int(stage_stats.get("stage_images_total", 0) or 0)
                            stage_result["stage_images_dir"] = str(stage_stats.get("stage_images_dir") or "").strip()
                    self._ui(lambda: self._style_training_success_label(self.ds_status))
                    self._ui(lambda: self._set_training_widget_text(self.ds_status, "Dataset treningowy został przygotowany!"))
                    if stage_result["enabled"] and (not stage_result["ok"]) and stage_result["message"]:
                        logger.debug(f"Synchronizacja zdjęć oczekujących po utworzeniu datasetu: {stage_result['message']}")

                    self._ui(lambda: self._style_training_success_label(self.ds_status))
                    self._ui(
                        lambda counts=dict(dataset_counts): self._set_training_widget_text(
                            self.ds_status,
                            (
                                "Dataset został utworzony: "
                                f"train={int(counts.get('train', 0) or 0)}, "
                                f"val={int(counts.get('val', 0) or 0)}, "
                                f"test={int(counts.get('test', 0) or 0)}"
                            ),
                        )
                    )

                    self._ui(
                        lambda p=str(out_dir), msg=str(msg2), counts=dict(dataset_counts): self._handle_step4_dataset_success_result(
                            dataset_path=p,
                            message=msg,
                            target="plate",
                            counts=counts,
                        )
                    )
                else:
                    self._ui(lambda: self._style_training_error_label(self.ds_status))
                    self._ui(lambda: self._set_training_widget_text(self.ds_status, "Błąd przygotowania datasetu"))
                    self._ui(
                        lambda msg=str(msg2): self._handle_step4_dataset_failure_result(
                            message=msg,
                            target="plate",
                            critical=False,
                        )
                    )

            except Exception as e:
                self._ui(lambda: self._style_training_error_label(self.ds_status))
                self._ui(lambda: self._set_training_widget_text(self.ds_status, "Krytyczny błąd przygotowania datasetu"))
                self._ui(
                    lambda err=str(e): self._handle_step4_dataset_failure_result(
                        message=err,
                        target="plate",
                        critical=True,
                    )
                )

            finally:
                self.dataset_build_is_running = False
                self._end_step4_operation("z4.dataset.build")
                self._ui(self._refresh_dataset_creator_cta_state)
                self._ui(self._refresh_training_start_state)

        threading.Thread(target=worker, daemon=True).start()

    def _split_dataset_thread(self):
        source_info = self._resolve_dataset_split_inputs()
        if not bool(source_info.get("ok")):
            self._refresh_dataset_split_cta_state()
            self._handle_step4_dataset_failure_result(
                message=str(source_info.get("message") or "Najpierw wskaż źródłowy dataset znaków."),
                target="char",
                critical=False,
            )
            return

        src = Path(source_info["src"])

        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Wynik splitu zapisuj obok innych datasetów projektu.
        base_datasets_dir = self._get_datasets_base_dir()
        out = base_datasets_dir / f"{src.name}_Split_{timestamp}"

        # Pokaż użytkownikowi docelową ścieżkę splitu.
        self.split_out_var.set(str(out))
        self._set_split_feedback_visibility(True)

        train = float(self.train_pct.get()) / 100.0
        val = float(self.val_pct.get()) / 100.0
        ratios = {
            "train": train,
            "val": val,
            "test": max(0.0, 1.0 - train - val)
        }

        if not self._begin_step4_operation("z4.dataset.split", "Z4: przygotowanie datasetu znaków"):
            return
        self.dataset_split_is_running = True

        self._set_split_feedback_visibility(True)
        self.split_progress_var.set(0)
        self._style_training_success_label(self.split_status)
        self._set_training_widget_text(self.split_status, "Rozpoczynam przygotowanie datasetu...")
        try:
            self.frame.update_idletasks()
        except Exception:
            pass

        def worker():
            try:
                def prog(c, t, n):
                    pct = (c / t) * 100 if t > 0 else 0
                    self._ui(lambda: self.split_progress_var.set(pct))
                    self._ui(lambda: self._style_training_success_label(self.split_status))
                    self._ui(lambda c=int(c), t=int(t): self._set_training_widget_text(self.split_status, f"Kopiowanie {c}/{t}..."))

                ok, msg, _ = self.splitter.split_dataset(src, out, ratios, prog)

                if ok:
                    dataset_counts = self._get_dataset_split_image_counts(out)
                    self._ui(lambda: self._style_training_success_label(self.split_status))
                    self._ui(lambda: self._set_training_widget_text(self.split_status, "Dataset treningowy został przygotowany!"))
                    self._ui(
                        lambda p=str(out), msg=str(msg), counts=dict(dataset_counts): self._handle_step4_dataset_success_result(
                            dataset_path=p,
                            message=msg,
                            target="char",
                            counts=counts,
                        )
                    )
                else:
                    self._ui(lambda: self._style_training_error_label(self.split_status))
                    self._ui(lambda: self._set_training_widget_text(self.split_status, "Błąd przygotowania datasetu"))
                    self._ui(
                        lambda msg=str(msg): self._handle_step4_dataset_failure_result(
                            message=msg,
                            target="char",
                            critical=False,
                        )
                    )

            except Exception as e:
                self._ui(lambda: self._style_training_error_label(self.split_status))
                self._ui(lambda: self._set_training_widget_text(self.split_status, "Krytyczny błąd przygotowania datasetu"))
                self._ui(
                    lambda err=str(e): self._handle_step4_dataset_failure_result(
                        message=err,
                        target="char",
                        critical=True,
                    )
                )

            finally:
                self.dataset_split_is_running = False
                self._end_step4_operation("z4.dataset.split")
                self._ui(self._refresh_dataset_split_cta_state)
                self._ui(self._refresh_training_start_state)

        threading.Thread(target=worker, daemon=True).start()

    def _release_gpu_resources_before_training(self):
        """Oddaje VRAM zajęty przez wcześniejszą pracę w Z2/Z3 przed startem Z4."""
        released_tabs: list[str] = []
        app_tabs = getattr(getattr(self, "app", None), "tabs", {}) or {}
        for tab_key, label in (("annotation", "Z2"), ("characters", "Z3")):
            tab = app_tabs.get(tab_key)
            if tab is None:
                continue
            releaser = getattr(tab, "release_gpu_resources_for_training", None)
            if not callable(releaser):
                continue
            try:
                releaser()
                released_tabs.append(label)
            except Exception as e:
                logger.debug(f"Nie udało się zwolnić GPU z {label} przed treningiem: {e}")
        try:
            cleanup_gpu_memory()
        except Exception as e:
            logger.debug(f"Nie udało się wykonać końcowego cleanup GPU przed treningiem: {e}")
        if released_tabs:
            self._append_train_log(
                "[INFO] Zwolniono pamięć GPU przed treningiem z modułów: "
                + ", ".join(released_tabs)
            )

    def _start_training(self):
        if not YOLO_AVAILABLE:
            return messagebox.showerror("Błąd", "Brak ultralytics.")

        try:
            self._clear_step4_guidance()
        except Exception:
            pass
        
        self._set_step4_process_console_text("Uruchamianie treningu...\n")
        self._latest_training_metrics = {}
        self._set_training_metric_interpretation("Interpretacja pojawi się po zakończeniu pierwszej epoki.")

        ds = self.dataset_var.get().strip()
        if not ds:
            return messagebox.showerror("Błąd", "Najpierw wskaż dataset treningowy.")

        ds_path = Path(ds)
        yaml_path = ds_path / "data.yaml" if ds_path.is_dir() else ds_path
        if not yaml_path.exists():
            if self._looks_like_char_classification_dataset(ds_path):
                return messagebox.showerror(
                    "Nieobsługiwany typ datasetu",
                    self._char_classification_dataset_message(),
                )
            return messagebox.showerror("Błąd", "Nie znaleziono pliku data.yaml.")
        dataset_root = yaml_path.parent

        is_valid_dataset, validation_msg, validation_stats = self.trainer.validate_dataset(dataset_root)
        if not is_valid_dataset:
            validation_details = self._build_training_dataset_validation_message(
                dataset_root,
                validation_msg,
                validation_stats,
            )
            self._append_train_log(f"[WALIDACJA] {validation_msg}")
            self._append_train_log(validation_details)
            self.train_progress_label.configure(
                text="Dataset wymaga poprawy przed treningiem.",
                foreground="#c0392b"
            )
            return messagebox.showerror("Dataset niegotowy do treningu", validation_details)

        pose_dataset_warning = self._get_pose_dataset_size_warning(dataset_root, validation_stats)
        if pose_dataset_warning:
            self._append_train_log(f"[OSTRZEZENIE] {pose_dataset_warning}")
            self.train_progress_label.configure(
                text="Ostrzeżenie: dataset YOLO Pose jest mały. Trening ruszy po potwierdzeniu.",
                foreground="#d35400"
            )
            messagebox.showwarning(
                "Mały dataset YOLO Pose",
                pose_dataset_warning + "\n\nTrening zostanie mimo to uruchomiony."
            )

        # Rozpoznaj typ datasetu na podstawie zawartości data.yaml.
        try:
            cfg = safe_load_yaml(yaml_path)
            is_pose_dataset = "kpt_shape" in cfg

            self._current_training_dataset_is_pose = bool(is_pose_dataset)
            inferred_target = self._infer_dataset_target(ds) or ("plate" if is_pose_dataset else "char")
            selected_target = self._get_selected_training_target()

            if not CAMPAIGN.get_active_project_name():
                if inferred_target != selected_target:
                    selected_label = self._format_training_target_label(selected_target)
                    inferred_label = self._format_training_target_label(inferred_target)
                    return messagebox.showerror(
                        "Niezgodny tor treningu",
                        "Wybrany tor treningu nie pasuje do wskazanego datasetu.\n\n"
                        f"Wybrany tor: {selected_label}\n"
                        f"Rozpoznany dataset: {inferred_label}\n\n"
                        "Zmień tor treningu albo wskaż dataset zgodny z tym wyborem."
                    )
                self._rebind_free_mode_training_storage(target=selected_target)

            if CAMPAIGN.get_active_project_name() and not is_pose_dataset:
                self._pending_campaign_model_type = "char"
            else:
                self._pending_campaign_model_type = None            
        except Exception as e:
            return messagebox.showerror("Błąd", f"Nie udało się odczytać data.yaml:\n{e}")

        base_key = self.base_model_var.get().strip()
        base_model = self.base_custom_var.get().strip() if base_key == "Custom" else base_key
        base_model_display = self._resolve_selected_training_base_model_display()
        _base_model_info_path, base_model_info = self._resolve_selected_training_base_model_info()
        device = self._device_to_ultralytics(self.device_var.get())

        selection_ok, _selection_message = self._validate_training_base_model_target_compatibility(
            target=selected_target,
            show_dialog=True,
        )
        if not selection_ok:
            return

        # Rozpoznaj, czy wybrany model jest modelem pose.
        is_pose_model = self._is_pose_base_model(base_key, base_model)

        # Zablokuj niezgodne pary dataset-model przed startem treningu.
        if is_pose_dataset and not is_pose_model:
            return messagebox.showerror(
                "Niezgodność typu treningu",
                "Wybrany dataset jest typu POSE (z keypointami), ale model bazowy NIE jest modelem pose.\n\n"
                "Wybierz model z dopiskiem '-pose'."
            )

        if not is_pose_dataset and is_pose_model:
            return messagebox.showerror(
                "Niezgodność typu treningu",
                "Wybrany dataset jest typu DETECT, ale model bazowy jest typu POSE.\n\n"
                "Dla znaków tablic wybierz zwykły model detect, np. 'yolo11n' lub 'yolo11s'."
            )

        try:
            requested_imgsz = self._safe_training_int_value("imgsz_var", default=640, minimum=0)
        except Exception:
            requested_imgsz = 0
        if is_pose_dataset and requested_imgsz < 256:
            return messagebox.showerror(
                "Zbyt mała rozdzielczość wejściowa",
                "Dla treningu POSE rozdzielczość wejściowa musi mieć co najmniej 256 px.\n\n"
                "Praktyczny bezpieczny start dla tego projektu to zwykle 512 albo 640."
            )

        # Zapisz czytelny nagłówek sesji w terminalu procesu.
        selected_device_display = self._normalize_training_device_choice(self.device_var.get())
        effective_device_raw, effective_device_profile = self._get_effective_training_device_profile(selected_device_display)
        if effective_device_profile is not None:
            effective_device_desc = (
                f"{effective_device_profile.get('name', effective_device_raw)} "
                f"({float(effective_device_profile.get('memory_gb', 0.0) or 0.0):.1f} GB VRAM)"
            )
        else:
            effective_device_desc = "CPU"

        gpu_capacity_block_reason = self._get_training_gpu_capacity_block_reason(
            is_pose_dataset=bool(is_pose_dataset),
            base_model_info=base_model_info,
            effective_device_profile=effective_device_profile,
        )
        if gpu_capacity_block_reason and device != "cpu":
            self._append_train_log("[BLOKADA STARTU] " + gpu_capacity_block_reason.replace("\n", " "))
            self.train_progress_label.configure(
                text="Wybrany model jest zbyt ciężki dla aktywnego GPU.",
                foreground="#c0392b"
            )
            return messagebox.showerror(
                "Model zbyt ciężki dla GPU",
                gpu_capacity_block_reason
            )

        self._append_train_log("=" * 70)
        self._append_train_log(f"START TRENINGU | Nazwa: {self.name_var.get()}")
        self._append_train_log(f"Dataset: {ds}")
        self._append_train_log(f"Wybór w polu 'Model bazowy (.pt)': {base_model_display}")
        self._append_train_log(f"Model przekazany do treningu: {base_model}")
        self._append_train_log(
            f"Urządzenie: {selected_device_display} -> {effective_device_desc} | backend Ultralytics: {device}"
        )
        self._append_train_log(
            f"Epoki: {self._safe_training_int_value('epochs_var', default=100, minimum=1)} | "
            f"Rozmiar partii: {self._safe_training_int_value('batch_var', default=16, minimum=1)} | "
            f"Rozdzielczość wejściowa: {self._safe_training_int_value('imgsz_var', default=640, minimum=32)} | "
            f"Współczynnik uczenia: {self._safe_training_float_value('lr0_var', default=0.01, minimum=0.0001)}"
        )
        self._append_train_log("=" * 70)
        self._release_gpu_resources_before_training()

        if not self._begin_step4_operation("z4.training.run", "Z4: trening modelu"):
            return

        try:
            run_id = self.trainer.start_training(
                name=self.name_var.get(),
                dataset_path=ds,
                base_model=base_model,
                epochs=self._safe_training_int_value("epochs_var", default=100, minimum=1),
                batch_size=self._safe_training_int_value("batch_var", default=16, minimum=1),
                img_size=self._safe_training_int_value("imgsz_var", default=640, minimum=32),
                device=device,
                lr0=self._safe_training_float_value("lr0_var", default=0.01, minimum=0.0001)
            )
        except Exception as e:
            self._end_step4_operation("z4.training.run")
            logger.exception("Nie udało się wystartować treningu")
            return messagebox.showerror("Błąd", f"Nie udało się uruchomić treningu:\n{e}")

        if not run_id:
            self._end_step4_operation("z4.training.run")
            self._pending_campaign_model_type = None
            self._set_train_progress_values(overall=0.0, epoch=0.0)
            self.train_progress_label.configure(
                text="Nie udało się uruchomić treningu.",
                foreground="#c0392b"
            )
            self._append_train_log("[START] Trening nie wystartował. Sprawdź dataset, model bazowy i log powyżej.")
            return messagebox.showerror(
                "Nie udało się uruchomić treningu",
                "Trening nie wystartował.\n\nSprawdź poprawność datasetu, modelu bazowego i log w terminalu procesu."
            )

        self.current_run_id = run_id
        self._last_training_completion_summary_run_id = None
        try:
            self._remember_campaign_plate_training_source(dataset_root)
        except Exception as e:
            logger.debug(f"Nie udało się zapamiętać źródła treningu tablic: {e}")
        self._step4_campaign_finish_ready = False
        try:
            if CAMPAIGN.get_active_project_name():
                CAMPAIGN.set_step4_finish_state(False)
        except Exception:
            pass
        self._set_train_progress_values(overall=0.0, epoch=0.0)
        self._reset_training_runtime_progress()
        self._set_train_live_metrics(None)
        self.btn_start_train.configure(state=tk.DISABLED)
        self.btn_pause_train.configure(state=tk.NORMAL)
        self.btn_stop_train.configure(state=tk.NORMAL)
        self._set_training_widget_text(self.train_progress_label, f"Uruchomiono run treningowy: {run_id}")
        self._training_started_monotonic = time.perf_counter()
        self._training_started_wall_clock = datetime.datetime.now()

        try:
            self._remember_campaign_training_run_in_registry(
                run_id=str(run_id or "").strip(),
                status=TrainingStatus.PENDING.value,
                target=self.get_campaign_training_target(),
            )
        except Exception:
            pass

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        if CAMPAIGN.get_active_project_name():
            self._pending_campaign_model_type = self.get_campaign_training_target()
            try:
                label = "znaków" if self._pending_campaign_model_type == "char" else "tablic"
                self._append_train_log(
                    f"[TARGET] Ten trening zostanie zapisany jako aktywny model {label} projektu."
                )
            except Exception:
                pass
        else:
            self._pending_campaign_model_type = None

        # Uruchom polling zakończenia treningu, aby odblokować dalszy workflow.
        if self._training_completion_poll_job is not None:
            try:
                self.frame.after_cancel(self._training_completion_poll_job)
            except Exception:
                pass
            self._training_completion_poll_job = None

        self._training_completion_poll_job = self.frame.after(3000, self._poll_training_completion)

    def _pause_training(self):
        self.trainer.pause_training()
        self.btn_pause_train.configure(state=tk.DISABLED)
        self.btn_stop_train.configure(state=tk.DISABLED)
        self.train_progress_label.configure(foreground="#d35400")
        self._set_training_widget_text(self.train_progress_label, "Wstrzymywanie treningu...")

    def _stop_training(self):
        self.trainer.stop_training()
        self.btn_pause_train.configure(state=tk.DISABLED)
        self.btn_stop_train.configure(state=tk.DISABLED)
        self.train_progress_label.configure(foreground="#c0392b")
        self._set_training_widget_text(self.train_progress_label, "Zatrzymywanie treningu...")

    def _resolve_training_end_feedback(self, success: bool, msg: str) -> tuple[str, str]:
        normalized = str(msg or "").strip().lower()
        if success:
            return "Trening zakończony.", "#2c3e50"
        if normalized == "wstrzymano":
            return "Trening wstrzymany.", "#d35400"
        if normalized == "zatrzymano":
            return "Trening zatrzymany.", "#c0392b"
        if self._is_memory_failure_text(msg):
            return "Trening przerwany przez błąd pamięci.", "#c0392b"
        return "Trening zakończony błędem.", "#c0392b"

    def _bind_trainer_callbacks(self):
        def on_batch_progress(epoch, batch_idx, total_batches, batch_pct):
            run = self.trainer.current_run
            if not run:
                return

            overall_pct = (((max(1, int(epoch)) - 1) + (float(batch_pct) / 100.0)) / max(1, int(run.epochs))) * 100.0
            if int(batch_idx) > 0 and int(total_batches) > 0:
                status_text = f"Trwa trening: Epoka {epoch}/{run.epochs} | partia {batch_idx}/{total_batches}"
            else:
                status_text = f"Trwa trening: Epoka {epoch}/{run.epochs} | przygotowanie partii"

            started = getattr(self, "_training_started_monotonic", None)
            if started is None:
                self._training_started_monotonic = time.perf_counter()
                self._training_started_wall_clock = datetime.datetime.now()
                started = self._training_started_monotonic
            eta_seconds = None
            try:
                overall_fraction = max(0.0, min(1.0, float(overall_pct) / 100.0))
                if started is not None and overall_fraction >= 0.01:
                    elapsed = max(0.001, time.perf_counter() - float(started))
                    eta_seconds = max(0.0, (elapsed / overall_fraction) - elapsed)
            except Exception:
                eta_seconds = None

            def update_ui():
                self._set_train_progress_values(overall=overall_pct, epoch=batch_pct)
                self._update_training_progress_meta(
                    epoch=int(epoch),
                    total_epochs=int(run.epochs),
                    batch_idx=int(batch_idx),
                    total_batches=int(total_batches),
                    overall_pct=float(overall_pct),
                    epoch_pct=float(batch_pct),
                    eta_seconds=eta_seconds,
                )
                self._set_training_widget_text(self.train_progress_label, status_text)

            self._ui(update_ui)

        def on_epoch(epoch, metrics):
            run = self.trainer.current_run
            if not run: return
            pct = (epoch / max(1, run.epochs)) * 100.0
            self._latest_training_metrics = dict(metrics or {})
            
            # Pobieranie wyników mAP
            map50 = metrics.get('map50', 0)
            map50_95 = metrics.get('map50_95', 0)
            loss = metrics.get('loss', 0)
            interpretation = self._build_training_metric_interpretation(metrics)
            
            # Formatowanie logu na żywo
            if self.get_campaign_training_target() == "plate":
                pose_map50 = self._metric_float(metrics.get("pose_map50", map50))
                pose_map50_95 = self._metric_float(metrics.get("pose_map50_95", map50_95))
                box_map50 = self._metric_float(metrics.get("box_map50", map50))
                box_map50_95 = self._metric_float(metrics.get("box_map50_95", map50_95))
                log_line = (
                    f"Epoka {epoch}/{run.epochs} | Strata(Loss): {loss:.3f} | "
                    f"Box mAP50: {box_map50:.3f} | Box mAP50-95: {box_map50_95:.3f} | "
                    f"Pose mAP50: {pose_map50:.3f} | Pose mAP50-95: {pose_map50_95:.3f}\n"
                )
            else:
                log_line = f"Epoka {epoch}/{run.epochs} | Strata(Loss): {loss:.3f} | mAP50: {map50:.3f} | mAP50-95: {map50_95:.3f}\n"
            
            # Aktualizacja UI w głównym wątku
            def update_ui():
                self._set_train_progress_values(overall=pct, epoch=100.0)
                self._update_training_progress_meta(
                    epoch=int(epoch),
                    total_epochs=int(run.epochs),
                    batch_idx=int(getattr(self, "_training_last_total_batches", 0) or 0),
                    total_batches=int(getattr(self, "_training_last_total_batches", 0) or 0),
                    overall_pct=float(pct),
                    epoch_pct=100.0,
                    eta_seconds=0.0,
                )
                self._set_training_widget_text(self.train_progress_label, f"Trening trwa: zakończono epokę {epoch}/{run.epochs}")
                self._set_training_metric_interpretation(interpretation)
                self._set_train_live_metrics(metrics)
                self._append_training_metric_table_to_global(epoch, run.epochs, metrics)
                self._append_to_step4_process_console(log_line)
                self._append_to_step4_process_console(f"{interpretation}\n")
                
            self._ui(update_ui)

        def on_end(success, msg):
            safe_msg = self._sanitize_training_text(msg)
            end_line = f"[KONIEC] {'SUKCES' if success else 'BŁĄD/STOP'} | {safe_msg}"
            self._append_train_log(end_line)
            if not success:
                for gpu_line in self._build_training_gpu_memory_lines(
                    getattr(getattr(self, "trainer", None), "current_run", None).device
                    if getattr(getattr(self, "trainer", None), "current_run", None) is not None
                    else None
                ):
                    self._append_train_log(f"[GPU] {gpu_line}")
            final_interpretation = self._build_training_metric_interpretation(getattr(self, "_latest_training_metrics", {}))
            if getattr(self, "_latest_training_metrics", {}):
                self._append_train_log(f"[OCENA] {final_interpretation}")
            self._end_step4_operation("z4.training.run")

            status_text, status_color = self._resolve_training_end_feedback(success, safe_msg)

            self._ui(lambda: self.btn_start_train.configure(state=tk.NORMAL))
            self._ui(lambda: self.btn_pause_train.configure(state=tk.DISABLED))
            self._ui(lambda: self.btn_stop_train.configure(state=tk.DISABLED))
            if success:
                self._ui(lambda: self._set_train_progress_values(overall=100.0, epoch=100.0))
            self._ui(lambda: self._set_training_metric_interpretation(final_interpretation))
            self._ui(lambda: self._set_train_live_metrics(getattr(self, "_latest_training_metrics", {})))
            self._ui(lambda: self.train_progress_label.configure(
                text=status_text,
                foreground=status_color,
            ))
            if not success:
                self._ui(lambda: self._update_training_progress_meta(eta_seconds=0.0))
            self._ui(lambda: self._load_history())
            self._ui(self._refresh_training_start_state)

        self.trainer.on_batch_progress = on_batch_progress
        self.trainer.on_epoch_end = on_epoch
        self.trainer.on_training_end = on_end

    def _reload_history_snapshot_from_disk(self) -> bool:
        history_obj = getattr(self, "history", None)
        history_dir = getattr(history_obj, "history_dir", None)
        if not history_dir:
            return False

        try:
            refreshed = TrainingHistory(history_dir=Path(history_dir))
        except Exception as e:
            logger.debug(f"Nie udało się przeładować historii treningu z dysku: {e}")
            return False

        self.history = refreshed

        try:
            trainer = getattr(self, "trainer", None)
            if trainer is not None:
                trainer.history = refreshed
                current_run_id = str(getattr(self, "current_run_id", "") or "").strip()
                if current_run_id:
                    refreshed_run = refreshed.get_run(current_run_id)
                    if refreshed_run is not None:
                        trainer.current_run = refreshed_run
        except Exception:
            pass

        return True

    def _load_history(self):
        selected_run_id = ""
        try:
            selection = self.tree.selection()
            if selection:
                selected_run_id = str(selection[0] or "").strip()
        except Exception:
            selected_run_id = ""

        try:
            self._reload_history_snapshot_from_disk()
        except Exception:
            pass

        self.tree.delete(*self.tree.get_children())
        for run in self.history.get_all_runs():
            # Zachowaj pełne run.id, aby wybór historii i folderów był jednoznaczny.
            best_map = getattr(run, 'best_map50_95', 0.0) or 0.0
            run_target = ""
            try:
                infer_target = getattr(self.history, "_infer_run_target", None)
                if callable(infer_target):
                    run_target = str(infer_target(run) or "").strip().lower()
            except Exception:
                run_target = ""
            if not run_target:
                try:
                    run_target = str(
                        self._infer_dataset_target(getattr(run, "dataset_path", "")) or ""
                    ).strip().lower()
                except Exception:
                    run_target = ""
            target_label = self._format_history_run_target_label(run_target)
            run_name = str(getattr(run, "name", "") or "").strip()
            created_at = str(getattr(run, "created_at", "") or "").strip()
            created_short = ""
            if created_at:
                try:
                    created_short = datetime.datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
                except Exception:
                    created_short = created_at.replace("T", " ")[:16]
            if created_short:
                run_label = self._shorten_training_text(f"{run_name} | {created_short}", 34)
            else:
                run_label = self._shorten_training_text(run_name or str(getattr(run, "id", "") or ""), 34)
            
            self.tree.insert("", tk.END, iid=str(run.id), values=(
                target_label,
                run_label,
                self._format_history_run_status_label(run),
                f"{run.current_epoch}/{run.epochs}", 
                f"{float(best_map):.3f}", 
                str(run.duration_str)
            ))

        if selected_run_id:
            for item_id in self.tree.get_children():
                try:
                    values = self.tree.item(item_id, "values")
                except Exception:
                    values = ()
                if str(item_id) == str(selected_run_id):
                    try:
                        self.tree.selection_set(item_id)
                        self.tree.focus(item_id)
                    except Exception:
                        pass
                    break

        self._on_run_selected()

    def _delete_selected(self):
        run = self._selected_run()
        if run and messagebox.askyesno("Potwierdź", "Usunąć run treningu?"):
            self.history.delete_run(run.id, delete_files=True)
            self._load_history()

    def _open_run_folder(self):
        run = self._selected_run()
        if run and Path(run.output_dir).exists():
            self._open_path(Path(run.output_dir))

    def _resume_selected_run(self):
        run = self._selected_run()
        if run is None:
            return

        if not self._is_history_run_resume_allowed(run):
            if self._is_history_run_resumable(run) and CAMPAIGN.get_active_project_name():
                return messagebox.showerror(
                    "Wznowienie niedostępne",
                    "W kampanii możesz wznowić tylko ostatni wznowialny run aktywnego toru.\n\n"
                    "Starsze wstrzymane runy pozostają w historii jako archiwum, ale nie są już ścieżką roboczą tej iteracji."
                )

        if not self._does_history_run_match_active_campaign_target(run):
            active_target = str(self.get_campaign_training_target() or CAMPAIGN.get_iteration_target() or "").strip().lower()
            active_label = "tablic" if active_target == "plate" else "znaków" if active_target == "char" else "bieżącego toru"
            return messagebox.showerror(
                "Niezgodny tor wznowienia",
                "Wybrany run należy do innego toru treningu niż aktualnie otwarty etap E4.\n\n"
                f"W tej chwili możesz wznowić tylko runy dla toru {active_label}."
            )

        last_weights = str(getattr(run, "last_weights", "") or "").strip()
        if not last_weights or not Path(last_weights).exists():
            return messagebox.showerror(
                "Brak checkpointu do wznowienia",
                "Wybrany run nie ma poprawnego pliku last.pt.\n\n"
                "Tego treningu nie da się wznowić od miejsca pauzy."
            )

        if not self._begin_step4_operation("z4.training.run", "Z4: wznowienie treningu"):
            return

        try:
            resumed_run_id = self.trainer.resume_training(str(run.id))
        except Exception as e:
            self._end_step4_operation("z4.training.run")
            logger.exception("Nie udało się wznowić treningu")
            return messagebox.showerror("Błąd wznowienia", f"Nie udało się wznowić treningu:\n{e}")

        if not resumed_run_id:
            self._end_step4_operation("z4.training.run")
            return messagebox.showerror(
                "Nie udało się wznowić treningu",
                "Wznowienie treningu nie wystartowało.\n\n"
                "Sprawdź, czy run nadal ma poprawny checkpoint `last.pt`."
            )

        self.current_run_id = resumed_run_id
        self._last_training_completion_summary_run_id = None
        self._step4_campaign_finish_ready = False
        try:
            if CAMPAIGN.get_active_project_name():
                CAMPAIGN.set_step4_finish_state(False)
        except Exception:
            pass
        self._set_train_progress_values(overall=0.0, epoch=0.0)
        self._reset_training_runtime_progress()
        self._set_train_live_metrics(None)
        self.btn_start_train.configure(state=tk.DISABLED)
        self.btn_pause_train.configure(state=tk.NORMAL)
        self.btn_stop_train.configure(state=tk.NORMAL)
        self.train_progress_label.configure(
            text=f"Wznowiono run treningu: {resumed_run_id}",
            foreground="#2c3e50"
        )
        self._training_started_monotonic = time.perf_counter()
        self._training_started_wall_clock = datetime.datetime.now()
        self._append_train_log(f"[RESUME] Wznowiono trening z checkpointu: {last_weights}")
        if CAMPAIGN.get_active_project_name():
            self._pending_campaign_model_type = self.get_campaign_training_target()
        else:
            self._pending_campaign_model_type = None

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        if self._training_completion_poll_job is not None:
            try:
                self.frame.after_cancel(self._training_completion_poll_job)
            except Exception:
                pass
            self._training_completion_poll_job = None
        self._training_completion_poll_job = self.frame.after(3000, self._poll_training_completion)

    def _show_history_context_menu(self, event=None):
        if event is None or not hasattr(self, "tree"):
            return

        try:
            row_id = self.tree.identify_row(event.y)
        except Exception:
            row_id = ""
        if not row_id:
            return

        try:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
        except Exception:
            pass

        try:
            self._on_run_selected()
        except Exception:
            pass

        menu = getattr(self, "history_context_menu", None)
        if menu is None:
            return

        selected_run = self._selected_run()
        resumable = bool(selected_run is not None and self._is_history_run_resume_allowed(selected_run))
        exportable = False
        if selected_run is not None:
            try:
                exportable = bool(
                    self._infer_history_run_target(selected_run) in {"plate", "char", "vehicle"}
                    and self._resolve_history_run_best_weights(selected_run) is not None
                )
            except Exception:
                exportable = False
        try:
            menu.entryconfigure("Wznów trening", state=(tk.NORMAL if resumable else tk.DISABLED))
        except Exception:
            pass
        try:
            menu.entryconfigure(
                "Eksportuj best.pt do modeli trybu swobodnego",
                state=(tk.NORMAL if exportable else tk.DISABLED),
            )
        except Exception:
            pass

        try:
            menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _autofill_validation_inputs_from_run(self, run):
        if run is None:
            return

        model_candidates = []
        for candidate in (
            getattr(run, "best_weights", ""),
            getattr(run, "last_weights", ""),
        ):
            candidate_str = str(candidate or "").strip()
            if candidate_str:
                model_candidates.append(Path(candidate_str))

        selected_model = next((path for path in model_candidates if path.exists()), None)
        if selected_model is not None and hasattr(self, "val_model_var"):
            try:
                self.val_model_var.set(str(selected_model))
            except Exception:
                pass

        dataset_value = str(getattr(run, "dataset_path", "") or "").strip()
        if dataset_value and hasattr(self, "val_data_var"):
            dataset_path = Path(dataset_value)
            if dataset_path.exists():
                try:
                    self.val_data_var.set(str(dataset_path))
                except Exception:
                    pass

    def _show_plot(self, path):
        """Wczytuje fizyczny obraz z folderu Ultralytics i przekazuje do płynnej nawigacji."""
        if not PIL_AVAILABLE: return
        try:
            self._plot_original_path = str(path)
            img = Image.open(path)
            
            # ZoomableCanvas sam zarządza skalą i przesuwaniem obrazu.
            self.plot_canvas.set_image(img)
            
            # Przy nowym obrazie pokaż cały wykres dopasowany do aktualnego okna.
            self.plot_canvas.fit_to_view()
        except Exception as e: 
            logger.error(f"Nie udało się wyświetlić wykresu: {e}")

    def _on_run_selected(self, event=None):
        run = self._selected_run()
        self._set_history_run_tables(run)
        if run is None:
            return
        self._autofill_validation_inputs_from_run(run)

    def _run_validation(self):
        if not YOLO_AVAILABLE:
            return messagebox.showerror("Błąd", "Brak modułu YOLO!")
        YoloClass = get_yolo_class()
        if YoloClass is None:
            return messagebox.showerror("Błąd", "Nie udało się załadować modułu YOLO.")
        if self.val_is_running: return
        
        model_path = self.val_model_var.get().strip()
        data_path = self.val_data_var.get().strip()
        
        if not Path(model_path).exists(): return messagebox.showerror("Błąd", "Wskazany plik modelu nie istnieje.")
        if Path(data_path).is_dir() and (Path(data_path)/"data.yaml").exists():
            data_path = str(Path(data_path)/"data.yaml")
        if not Path(data_path).exists() or not data_path.endswith(".yaml"):
            return messagebox.showerror("Błąd", "Wskaż plik data.yaml lub folder zawierający ten plik.")

        if not self._begin_step4_operation("z4.validation.run", "Z4: walidacja modelu"):
            return

        self.val_is_running = True
        self.btn_run_val.config(state=tk.DISABLED, text="Walidacja w toku...")
        self.val_status.config(text="Walidacja w toku...", foreground="#d35400")
        self._set_validation_summary(
            f"Trwa walidacja: {Path(model_path).name} | split: {self.val_split_var.get()}",
            [],
            "Model jest sprawdzany na wskazanym splicie. Po zakończeniu tabela odświeży wynik automatycznie.",
        )
        self._set_step4_process_console_text(
            f"Inicjalizowanie silnika YOLO do ewaluacji...\n"
            f"Model: {Path(model_path).name}\n"
            f"Dataset: {Path(data_path).parent.name}\n\n"
        )

        def worker():
            try:
                model = YoloClass(model_path)
                metrics = model.val(data=data_path, split=self.val_split_var.get())
                metric_rows = self._extract_validation_metric_rows(metrics)
                
                res = "\n=== OFICJALNE WYNIKI WALIDACJI YOLO ===\n"
                
                if hasattr(metrics, 'results_dict'):
                    for k, v in metrics.results_dict.items(): 
                        res += f"• {k}: {v:.4f}\n"
                else:
                    if hasattr(metrics, 'box'):
                        res += f"• mAP50:     {metrics.box.map50:.4f}\n"
                        res += f"• mAP50-95:  {metrics.box.map:.4f}\n"
                        res += f"• Precision: {metrics.box.mp:.4f} (Mean Precision)\n"
                        res += f"• Recall:    {metrics.box.mr:.4f} (Mean Recall)\n"
                    elif hasattr(metrics, 'pose'):
                        res += f"• Pose mAP50: {metrics.pose.map50:.4f}\n"
                        res += f"• Pose mAP:   {metrics.pose.map:.4f}\n"
                        if hasattr(metrics, 'box'):
                            res += f"• Box mAP50:  {metrics.box.map50:.4f}\n"
                    else:
                        res += str(metrics)
                        
                self._append_train_log(res.rstrip())
                self._ui(lambda: self.val_status.config(text="Walidacja zakończona.", foreground="green"))
                self._ui(
                    lambda rows=metric_rows, model_name=Path(model_path).name, split_name=self.val_split_var.get():
                    self._set_validation_summary(
                        f"Walidacja zakończona: {model_name} | split: {split_name}",
                        rows,
                        "Tabela pokazuje najważniejsze metryki walidacyjne i ich orientacyjną ocenę.",
                    )
                )
                self._ui(lambda: messagebox.showinfo("Sukces", "Walidacja zakończona pomyślnie!"))
                
            except Exception as e:
                self._append_train_log(f"\nBŁĄD WALIDACJI:\n{e}")
                self._ui(lambda: self.val_status.config(text="Błąd walidacji", foreground="red"))
                self._ui(
                    lambda err=str(e), model_name=Path(model_path).name:
                    self._set_validation_summary(
                        f"Walidacja nie powiodła się: {model_name}",
                        [("Błąd", self._shorten_training_text(err, 72), "-", "-")],
                        err,
                    )
                )
                logger.error(f"Validation error: {e}")
                
            finally:
                self.val_is_running = False
                self._end_step4_operation("z4.validation.run")
                self._ui(lambda: self.btn_run_val.config(state=tk.NORMAL, text="Uruchom walidację"))
                self._ui(self._refresh_training_start_state)
                
        threading.Thread(target=worker, daemon=True).start()

    def _load_ranking(self):
        if not hasattr(self, "rank_tree"):
            return
        self._ensure_plate_ranking_engine()
        entries = getattr(self.ranking_engine, 'entries', [])
        self.rank_tree.delete(*self.rank_tree.get_children())

        selected_reference = self._resolve_ranking_reference_source()
        selected_reference_path = str(selected_reference.get("reference_dir") or "").strip()
        selected_reference_raw = str(selected_reference.get("selected_path") or "").strip()

        def normalize_path(path_like: str) -> str:
            raw = str(path_like or "").strip()
            if not raw:
                return ""
            try:
                return str(Path(raw).resolve())
            except Exception:
                return str(Path(raw))

        filtered_entries = [e for e in entries if getattr(e, 'task_type', '') == "Tablice (Pose)"]
        if selected_reference_raw and not selected_reference.get("ok"):
            filtered_entries = []
        elif selected_reference_path:
            filtered_entries = [
                e for e in filtered_entries
                if normalize_path(getattr(e, "reference_path", "")) == normalize_path(selected_reference_path)
            ]
        filtered_entries.sort(key=lambda x: getattr(x, 'f1_score', 0), reverse=True)

        for i, rep in enumerate(filtered_entries):
            reference_name = str(getattr(rep, "reference_name", "") or "").strip()
            if not reference_name:
                reference_name = Path(str(getattr(rep, "reference_path", "") or "-")).name or "-"
            self.rank_tree.insert("", tk.END, values=(
                i + 1,
                getattr(rep, 'model_name', 'Nieznany'),
                f"{float(getattr(rep, 'f1_score', 0) or 0):.1f}%",
                f"{float(getattr(rep, 'precision', 0) or 0):.1f}%",
                f"{float(getattr(rep, 'recall', 0) or 0):.1f}%",
                int(getattr(rep, 'total_images', 0) or 0),
                reference_name,
            ))

    def _run_ranking(self):
        if self.rank_is_running: return
        self._ensure_plate_ranking_engine()
        models_dir = Path(self.rank_models_dir.get().strip())
        data_dir = Path(self.rank_data_dir.get().strip())
        
        if not models_dir.exists() or not data_dir.exists():
            return messagebox.showerror("Błąd", "Sprawdź ścieżki do modeli i folderu z obrazami testowymi!")

        gt_xml = data_dir / "annotations.xml"
        if not gt_xml.exists():
            return messagebox.showerror("Błąd", f"W wybranym folderze brakuje pliku annotations.xml z zapisanymi poprawkami:\n{gt_xml}")

        target_task = "Tablice (Pose)"
        is_pose_task = True

        self.rank_is_running = True
        self.btn_run_rank.config(state=tk.DISABLED, text="Testowanie modeli...")
        self.rank_progress_var.set(0)

        def worker():
            from ..ranking.annotation_comparator import AnnotationComparator
            from ..annotators import PlateAnnotator
            from ..data_models import ImageAnnotation, Detection
            
            try:
                model_files = list(models_dir.glob("*.pt"))
                models_to_test = []
                for mf in model_files:
                    is_pose_model = "pose" in mf.name.lower()
                    if is_pose_task and not is_pose_model: continue
                    if not is_pose_task and is_pose_model: continue
                    models_to_test.append(mf)
                
                if not models_to_test:
                    self._ui(lambda: messagebox.showinfo("Info", "Brak modeli .pt pasujących do wybranej kategorii (Pose/Detect)."))
                    return
                
                total_models = len(models_to_test)
                comparator = AnnotationComparator()
                device = self._device_to_ultralytics(self.device_var.get())
                conf_thresh = self.rank_conf.get()

                temp_xml_path = data_dir / "temp_ranking_auto.xml"
                
                for idx, model_path in enumerate(models_to_test):
                    if not self.rank_is_running: break
                    self._ui(lambda m=model_path.name: self.rank_status.config(text=f"Testowanie modelu {m} ({idx+1}/{total_models})"))
                    
                    annotator = PlateAnnotator(model_path, conf_thresh, device)
                        
                    success, msg = annotator.load_models()
                    if not success: continue
                        
                    images = list(data_dir.glob("*.jpg")) + list(data_dir.glob("*.png"))
                    auto_annotations = []
                    
                    for img_idx, img_path in enumerate(images):
                        if not self.rank_is_running: break
                        ann = annotator.process_image(img_path)
                        auto_annotations.append(ann)
                        sub_pct = ((idx + (img_idx / len(images))) / total_models) * 100
                        self._ui(lambda p=sub_pct: self.rank_progress_var.set(p))
                        
                    annotator.unload_models()
                    
                    from ..exporters.cvat_exporter import CVATExporter
                    exporter = CVATExporter()
                    exporter.export(auto_annotations, temp_xml_path, include_confidence=True)
                    
                    stats = comparator.compare(auto_xml_path=temp_xml_path, corrected_xml_path=gt_xml)
                    self.ranking_engine.add_entry(model_name=model_path.name, model_path=str(model_path), comparison_stats=stats, task_type=target_task)
                    
                    if temp_xml_path.exists(): temp_xml_path.unlink()
                
                self._ui(lambda: self.rank_progress_var.set(100))
                self._ui(lambda: self._load_ranking())
                self._ui(lambda: self.rank_status.config(text="Ranking zakończony.", foreground="green"))
                
            except Exception as e:
                self._ui(lambda err=e: messagebox.showerror("Błąd", f"Błąd w trakcie rankingu:\n{err}"))
                self._ui(lambda: self.rank_status.config(text="Błąd rankingu", foreground="red"))
            finally:
                self.rank_is_running = False
                self._ui(lambda: self.btn_run_rank.config(state=tk.NORMAL, text="Uruchom ranking"))

        threading.Thread(target=worker, daemon=True).start()
