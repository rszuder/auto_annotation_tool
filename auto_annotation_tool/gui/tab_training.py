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
import threading
import datetime
import time
import webbrowser
from pathlib import Path, PurePosixPath

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..campaign_manager import CAMPAIGN
from ..config import CONFIG, YOLO_AVAILABLE, AVAILABLE_POSE_MODELS, AVAILABLE_DETECT_MODELS, PIL_AVAILABLE, logger
from ..icons import IconManager
from ..validators import validate_yolo_dataset, validate_model_file
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..ranking import ModelRanking, ModelRankingEntry
from ..utils import safe_load_yaml, get_image_files
from .help_manager import HELP
from .section_header_label import SectionHeaderLabel
from .web_slim_scrollbar import WebSlimScrollbar
from .zoomable_canvas import ZoomableCanvas

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageTk

try:
    from ultralytics import YOLO
except ImportError:
    pass


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

    def _append_train_log(self, message: str, mirror_global: bool = True):
        """Bezpieczne dopisywanie linii do konsoli treningu z dowolnego wątku."""
        text = "" if message is None else str(message)
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
                self.train_log_console.config(state=tk.NORMAL)
                self.train_log_console.insert(tk.END, text)
                self.train_log_console.see(tk.END)
                self.train_log_console.config(state=tk.DISABLED)
            except Exception:
                pass
        self._ui(update)

    def _append_ranking_log(self, message: str):
        text = str(message or "").strip()
        if not text:
            return
        self._append_train_log(f"[RANKING] {text}")

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
            return "budowa datasetu"
        if bool(getattr(self, "dataset_split_is_running", False)):
            return "dzielenie datasetu"
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
                "Loss porownuj tylko miedzy epokami tego samego treningu - powinien raczej spadac."
            )

        return (
            "Zakresy orientacyjne: kluczowe jest mAP50-95. "
            "< 0.40 = słabo | 0.40 - 0.60 = używalnie | 0.60 - 0.80 = dobrze | > 0.80 = bardzo dobrze. "
            "Dla mAP50: < 0.70 = słabo | 0.70 - 0.85 = używalnie | 0.85 - 0.93 = dobrze | > 0.93 = bardzo dobrze. "
            "Loss porownuj tylko wzgledem poprzednich epok tego samego treningu."
        )

    def _refresh_training_metric_reference(self):
        label = getattr(self, "train_metric_reference_lbl", None)
        if label is None:
            return
        try:
            label.configure(text=self._build_training_metric_reference_text())
        except Exception:
            pass

    def _set_training_metric_interpretation(self, text: str):
        label = getattr(self, "train_metric_hint_lbl", None)
        if label is None:
            return
        try:
            label.configure(text=str(text or "").strip())
        except Exception:
            pass

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
        base_model = self._shorten_training_text(Path(getattr(run, "base_model", "") or "").name or "-", 36)
        created_at = str(getattr(run, "created_at", "") or "").replace("T", " ")

        return [
            ("Status", str(getattr(run, "status", "-") or "-")),
            ("Dataset", dataset_display),
            ("Model bazowy", base_model),
            ("Postep", f"{int(getattr(run, 'current_epoch', 0) or 0)}/{int(getattr(run, 'epochs', 0) or 0)} epok"),
            ("Ustawienia", f"img {int(getattr(run, 'img_size', 0) or 0)} | batch {int(getattr(run, 'batch_size', 0) or 0)} | lr0 {float(getattr(run, 'lr0', 0.0) or 0.0):.4f}"),
            ("Urzadzenie", self._shorten_training_text(str(getattr(run, "device", "") or "-"), 28)),
            ("Najlepsze wagi", best_weights),
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

    def _build_training_recommendation_rows(self) -> tuple[str, list[tuple[str, str, str]], str]:
        recommendation = self._get_training_device_recommendation(self._get_global_training_device_choice())
        memory_gb = float(recommendation.get("memory_gb", 0.0) or 0.0)
        if recommendation.get("effective_raw") == "cpu":
            device_label = "Sprzet wykryty: CPU"
        else:
            device_label = (
                f"Sprzet wykryty: {recommendation.get('device_name', 'GPU')} | "
                f"{memory_gb:.1f} GB VRAM"
            )

        def current_int(var_name: str) -> str:
            try:
                return str(int(getattr(self, var_name).get()))
            except Exception:
                return "-"

        def current_float(var_name: str, digits: int = 4) -> str:
            try:
                return f"{float(getattr(self, var_name).get()):.{digits}f}"
            except Exception:
                return "-"

        rows = [
            ("1. Epoki", current_int("epochs_var"), str(int(recommendation.get("epochs", 0) or 0))),
            ("2. Batch", current_int("batch_var"), str(int(recommendation.get("batch", 0) or 0))),
            ("3. ImgSz", current_int("imgsz_var"), str(int(recommendation.get("imgsz", 0) or 0))),
            ("4. lr0", current_float("lr0_var"), f"{float(recommendation.get('lr0', 0.0) or 0.0):.4f}"),
        ]
        note = "Gdy zabraknie pamieci, zmniejszaj po kolei: 2 -> 3 -> 4."
        return device_label, rows, note

    def _refresh_training_recommendation_table(self):
        hardware_text, rows, note_text = self._build_training_recommendation_rows()
        hardware_label = getattr(self, "train_recommendation_hardware_label", None)
        if hardware_label is not None:
            try:
                hardware_label.configure(text=hardware_text)
            except Exception:
                pass

        cells = list(getattr(self, "_train_recommendation_cells", []) or [])
        for row_index, row_values in enumerate(rows):
            for col_index, value in enumerate(row_values):
                try:
                    cells[row_index][col_index].configure(text=str(value))
                except Exception:
                    pass

        note_var = getattr(self, "train_recommendation_note_var", None)
        if note_var is not None:
            try:
                note_var.set(note_text)
            except Exception:
                pass

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

        for label_name, bg, fg in (
            ("train_recommendation_title_label", title_bg, title_fg),
            ("train_recommendation_hardware_label", hardware_bg, hardware_fg),
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

        for row_index, row_cells in enumerate(list(getattr(self, "_train_recommendation_cells", []) or [])):
            for col_index, label in enumerate(list(row_cells or [])):
                if label is None:
                    continue
                bg = subtle_bg if col_index == 2 else cell_bg
                fg = subtle_fg if col_index == 2 else cell_fg
                if row_index % 2 == 1 and col_index != 2:
                    bg = header_bg
                try:
                    label.configure(bg=bg, fg=fg)
                except Exception:
                    pass

    def _apply_training_device_recommendation(self):
        recommendation = self._get_training_device_recommendation(self._get_global_training_device_choice())
        try:
            self.epochs_var.set(int(recommendation.get("epochs", self.epochs_var.get()) or self.epochs_var.get()))
        except Exception:
            pass
        try:
            self.batch_var.set(int(recommendation.get("batch", self.batch_var.get()) or self.batch_var.get()))
        except Exception:
            pass
        try:
            self.imgsz_var.set(int(recommendation.get("imgsz", self.imgsz_var.get()) or self.imgsz_var.get()))
        except Exception:
            pass
        try:
            self.lr0_var.set(float(recommendation.get("lr0", self.lr0_var.get()) or self.lr0_var.get()))
        except Exception:
            pass
        self._refresh_training_recommendation_table()
        self._refresh_training_start_state()

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

        return True

    def _refresh_training_start_state(self):
        button = getattr(self, "btn_start_train", None)
        if button is None:
            return
        try:
            button.configure(state=(tk.NORMAL if self._is_training_configuration_ready() else tk.DISABLED))
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
            preferred_dir = self._format_workspace_relative_path(self._get_datasets_base_dir())
            return (
                "Tryb projektu: to pole zwykle uzupelnia kampania. Jesli wskazujesz dataset ręcznie, "
                "wybierz katalog zawierajacy plik data.yaml oraz foldery images/ i labels/.\n"
                f"Najczesciej będzie to katalog projektu albo jego datasetowy odpowiednik: {preferred_dir}"
            )

        if selected_target == "plate":
            source_hint = "Dla toru tablic wskaż dataset YOLO Pose wyeksportowany w Z2."
        else:
            source_hint = "Dla toru znaków wskaż dataset YOLO Detect wyeksportowany w Z3/PZ3."

        return (
            "Tryb swobodny: najpierw wybierasz tor treningu, a tutaj wskazujesz gotowy katalog datasetu YOLO.\n"
            "data.yaml to plik konfiguracyjny YOLO, który opisuje splity train/val/test oraz klasy modelu.\n"
            f"{source_hint}\n"
            f"W sztywnym drzewie Workspace szukaj go przede wszystkim w: {workspace_dir}\n"
            "Tutaj wybierz cały folder datasetu, w którym lezy data.yaml oraz podfoldery images/ i labels/. "
            "Jesli dataset nie pasuje do wybranego toru, start treningu zostanie zablokowany."
        )

    def _get_preferred_models_dir(self, target: str | None = None) -> Path:
        normalized_target = CONFIG.normalize_task_target(target or self._get_selected_training_target())

        preferred = CONFIG.get_trained_models_dir(normalized_target)
        return preferred if preferred.exists() else Path(CONFIG.DEFAULT_MODELS_DIR)

    def _pick_base_custom_model(self):
        self._pick_file(
            self.base_custom_var,
            "*.pt",
            self._get_preferred_models_dir(self._get_selected_training_target())
        )
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
            size_label = "bardzo maly"
            warning_body = (
                "Przy tak małej próbce model może nauczyc się zgrubnej lokalizacji tablicy, "
                "ale nie geometrii jej rogów. Częstym objawem są małe lub niestabilne wielokąty "
                "pojawiajace się w okolicy prawdziwej tablicy."
            )
        elif total_images < 30 or train_images < 20 or val_images < 5:
            size_label = "maly"
            warning_body = (
                "To zwykle wystarcza tylko na bardzo wstępny eksperyment. Geometria rogów tablic "
                "może być nadal niestabilna, dlatego przed oceną modelu warto powiększyć zbiór ręcznych anotacji."
            )
        else:
            return ""

        return (
            f"Ostrzezenie: dataset YOLO Pose jest {size_label} "
            f"(train={train_images}, val={val_images}, test={test_images}, razem={total_images}).\n"
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

    def _get_training_scope_hint_text(self) -> str:
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        selected_target = self._get_selected_training_target()
        selected_label = self._format_training_target_label(selected_target)

        if campaign_active:
            return (
                f"Aktywny tor kampanii: {selected_label}. "
                "W kampanii Z4 pracuje na torze wybranym przez workflow projektu."
            )

        dataset_value = getattr(self, "dataset_var", None)
        inferred_target = self._infer_dataset_target(dataset_value.get() if dataset_value is not None else "")
        if inferred_target and inferred_target != selected_target:
            inferred_label = self._format_training_target_label(inferred_target)
            return (
                f"Wybrany tor: {selected_label}. "
                f"Uwaga: wskazany dataset wygląda na tor {inferred_label}. "
                "To pole powinno być zgodne z wyborem kart powyzej."
            )

        return (
            f"Wybrany tor: {selected_label}. "
            "Najpierw wybierz tor, potem dataset zgodny z tym wyborem, a na koncu model bazowy tego samego typu."
        )

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

    def _pick_training_dataset_dir(self):
        self._pick_dir(
            self.dataset_var,
            initialdir=str(CONFIG.get_datasets_dir(self._get_selected_training_target()))
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
        if widget is None:
            return

        try:
            widget.configure(cursor="hand2")
        except Exception:
            pass

        try:
            widget.bind("<Button-1>", lambda _e, m=mode: self._set_step4_dataset_mode(m), add="+")
            widget.bind("<Enter>", lambda _e, m=mode: self._set_training_route_card_hover(m, True), add="+")
            widget.bind("<Leave>", lambda _e, m=mode: self._set_training_route_card_hover(m, False), add="+")
        except Exception:
            pass

    def _set_training_route_card_hover(self, mode: str, enabled: bool):
        self._free_route_hover_mode = mode if enabled else None
        self._refresh_free_training_route_cards()

    def _refresh_free_training_route_cards(self):
        cards = getattr(self, "_free_training_route_cards", {})
        if not cards:
            return

        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        panel_alt = palette.get("panel_alt", "#2d2d30")
        hover_bg = palette.get("button_hover", panel_alt)
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        accent = palette.get("accent", "#0e639c")
        accent_text = palette.get("accent_text", "#ffffff")
        success = palette.get("success", "#4ec9b0")
        surface_info = palette.get("surface_info", hover_bg)
        surface_success = palette.get("surface_success", hover_bg)

        active_mode = self._get_selected_training_target()
        hover_mode = getattr(self, "_free_route_hover_mode", None)

        for mode, widgets in cards.items():
            frame = widgets.get("frame")
            title = widgets.get("title")
            badge = widgets.get("badge")
            desc = widgets.get("desc")
            meta = widgets.get("meta")
            if frame is None:
                continue

            is_active = mode == active_mode
            is_hover = mode == hover_mode
            if mode == "plate":
                accent_color = accent
                active_bg = surface_info
            else:
                accent_color = success
                active_bg = surface_success

            bg = active_bg if is_active else (hover_bg if is_hover else panel_alt)
            frame_border = accent_color if is_active else border
            title_fg = accent_color if is_active else fg
            badge_bg = accent_color if is_active else panel_bg
            badge_fg = accent_text if is_active else muted
            desc_fg = fg if is_active else muted

            try:
                frame.configure(bg=bg, highlightbackground=frame_border, highlightcolor=frame_border)
            except Exception:
                pass
            for label, color in ((title, title_fg), (desc, desc_fg), (meta, muted)):
                try:
                    if label is not None:
                        label.configure(bg=bg, fg=color)
                except Exception:
                    pass
            try:
                if badge is not None:
                    badge.configure(
                        bg=badge_bg,
                        fg=badge_fg,
                        highlightbackground=frame_border,
                        highlightcolor=frame_border
                    )
            except Exception:
                pass

        title = getattr(self, "free_training_route_title_lbl", None)
        if title is not None:
            try:
                title.configure(text=("Co chcesz trenowac?" if not CAMPAIGN.get_active_project_name() else "Wybrany tor treningu"))
            except Exception:
                pass

    def _refresh_free_training_route_ui(self):
        host = getattr(self, "free_training_route_host", None)
        if host is None:
            return

        campaign_active = bool(CAMPAIGN.get_active_project_name())
        try:
            if campaign_active:
                host.pack_forget()
            else:
                host.pack(anchor=tk.W, fill=tk.X, pady=(0, 12), before=self.train_session_name_row)
        except Exception:
            pass

        self._refresh_free_training_route_cards()
        self._refresh_training_start_state()

    def _update_step4_notebook_mode(self):
        if not hasattr(self, "main_nb"):
            return

        campaign_active = bool(CAMPAIGN.get_active_project_name())
        dataset_label = "[PZ1] Produkcja datasetu"
        train_label = "[PZ2] Trening i analiza" if campaign_active else "[PZ1] Trening i analiza"

        try:
            self.main_nb.tab(self.tab_train, text=train_label)
        except Exception:
            pass

        if campaign_active:
            if not getattr(self, "_step4_dataset_tab_visible", False):
                try:
                    self.main_nb.insert(0, self.tab_dataset, text=dataset_label)
                except Exception:
                    try:
                        self.main_nb.add(self.tab_dataset, text=dataset_label)
                    except Exception:
                        pass
                self._step4_dataset_tab_visible = True
            else:
                try:
                    self.main_nb.tab(self.tab_dataset, text=dataset_label)
                except Exception:
                    pass
            return

        if getattr(self, "_step4_dataset_tab_visible", False):
            try:
                self.main_nb.hide(self.tab_dataset)
            except Exception:
                pass
            self._step4_dataset_tab_visible = False

        try:
            if str(self.main_nb.select()) != str(self.tab_train):
                self.main_nb.select(self.tab_train)
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
        dataset_fill = palette.get("accent", "#0e639c")
        split_fill = palette.get("guide", palette.get("warning", "#f0b44c"))
        rank_fill = palette.get("accent_hover", dataset_fill)
        epoch_fill = palette.get("guide", palette.get("warning", "#f0b44c"))
        overall_fill = palette.get("success", "#2ecc71")

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

        split_feedback_frame = getattr(self, "split_feedback_frame", None)
        if split_feedback_frame is not None:
            try:
                self.app.style_ttk_frame_widget(split_feedback_frame, background=shell_bg)
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
    
            #=====================================
    def set_campaign_context(self, runs_dir=None, datasets_dir=None):
        """
        Przełącza TrainingTab na katalogi aktywnego projektu
        i odtwarza stan z4 dla bieżącego projektu.
        """
        campaign_target = CAMPAIGN.get_iteration_target()
        if campaign_target not in ("char", "plate"):
            campaign_target = "char"
            require_route_selection = True
        else:
            require_route_selection = False

        if datasets_dir is not None:
            self._campaign_datasets_dir = str(Path(datasets_dir))

        project_datasets_dir = Path(self._campaign_datasets_dir) if self._campaign_datasets_dir else None

        if runs_dir is None:
            self._reset_step4_transient_ui(
                datasets_dir=project_datasets_dir,
                target=campaign_target,
                require_route_selection=require_route_selection
            )
            try:
                self._restore_step4_campaign_project_state()
            except Exception:
                pass
            return

        new_runs_dir = Path(runs_dir)

        if getattr(self.trainer, "is_training", False):
            logger.warning("Nie można zmienić kontekstu projektu podczas aktywnego treningu.")
            return

        if self._campaign_runs_dir == str(new_runs_dir):
            self._reset_step4_transient_ui(
                datasets_dir=project_datasets_dir,
                target=campaign_target,
                require_route_selection=require_route_selection
            )
            try:
                self._restore_step4_campaign_project_state()
            except Exception:
                pass
            return

        self._campaign_runs_dir = str(new_runs_dir)
        new_runs_dir.mkdir(parents=True, exist_ok=True)

        self.history = TrainingHistory(history_dir=new_runs_dir)
        self.trainer = YOLOPoseTrainer(history=self.history)
        self._bind_trainer_callbacks()

        self._reset_step4_transient_ui(
            datasets_dir=project_datasets_dir,
            target=campaign_target,
            clear_builder_inputs=True,
            require_route_selection=require_route_selection
        )

        try:
            self._restore_step4_campaign_project_state()
        except Exception:
            pass

        logger.info(f"TrainingTab przełączony na projektowy katalog runów: {new_runs_dir}")

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
            "required_images": 2,
            "source_run": "",
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "validation_message": "",
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

        ready_dataset = None
        try:
            ready_candidates = self._find_ready_dataset_candidates(Path(datasets_dir))
            preferred = [rec for rec in ready_candidates if rec[1] == target]
            if preferred:
                ready_dataset, _ready_target, _stamp = max(preferred, key=lambda rec: rec[2])
            elif ready_candidates:
                ready_dataset, _ready_target, _stamp = max(ready_candidates, key=lambda rec: rec[2])
        except Exception:
            ready_dataset = None

        if ready_dataset is not None:
            ready_dataset_str = str(ready_dataset)
            result["ready_dataset"] = ready_dataset_str
            result["dataset_hint"] = ready_dataset_str
            if target == "char":
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
                    result.update(
                        ok=False,
                        reason="invalid_char_dataset",
                        message=(
                            "E4 w torze znaków pozostaje zablokowane, bo ostatni dataset z Z3 nie jest jeszcze gotowy do treningu.\n\n"
                            f"{self._build_training_dataset_validation_message(Path(ready_dataset), validation_msg, validation_stats)}\n\n"
                            "Wróć do Z3 i przebuduj eksport albo split datasetu znaków."
                        ),
                    )
                    return result
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

        auto_dir = CAMPAIGN.get_dir("auto_ann")
        if auto_dir is None:
            result.update(
                ok=False,
                reason="missing_plate_annotations",
                message="E4 w torze tablic pozostaje zablokowane, bo projekt nie ma jeszcze katalogu z zatwierdzona anotacja Z2.",
            )
            return result

        try:
            xml_files = list(Path(auto_dir).rglob("annotations.xml"))
        except Exception:
            xml_files = []

        if not xml_files:
            result.update(
                ok=False,
                reason="missing_plate_annotations",
                message="E4 w torze tablic pozostaje zablokowane, bo nie ma jeszcze zatwierdzonego runu Z2 z plikiem annotations.xml.",
            )
            return result

        latest_xml_path = max(xml_files, key=lambda p: p.stat().st_mtime)
        source_run = str(latest_xml_path.parent.name or "").strip()
        result["source_run"] = source_run

        inspector = DatasetCreator()
        parse_ok, parse_msg, parse_stats = inspector.parse_cvat_xml(latest_xml_path)
        annotated_images = int((parse_stats or {}).get("annotated_images", 0) or 0)
        result["annotated_images"] = annotated_images

        if not parse_ok:
            run_suffix = f" ({source_run})" if source_run else ""
            result.update(
                ok=False,
                reason="invalid_plate_annotations",
                message=(
                    "E4 w torze tablic pozostaje zablokowane, bo ostatni zatwierdzony run Z2"
                    f"{run_suffix} nie zawiera jeszcze poprawnych tablic do budowy datasetu.\n\n"
                    f"Walidacja: {parse_msg}\n"
                    "Wróć do Z2 i dopracuj anotacje."
                ),
            )
            return result

        if annotated_images < 2:
            run_suffix = f" ({source_run})" if source_run else ""
            result.update(
                ok=False,
                reason="insufficient_plate_annotations",
                message=(
                    "E4 w torze tablic wymaga co najmniej 2 oznaczonych obrazów.\n\n"
                    f"Bieżący zatwierdzony run Z2{run_suffix} ma teraz {annotated_images} taki obraz(y).\n"
                    "Wróć do Z2, dodaj brakujące oznaczenia i dopiero wtedy przejdź dalej."
                ),
            )
            return result

        return result

    def open_campaign_step4_entry(self, *, iteration_target: str | None = None) -> dict:
        if not CAMPAIGN.get_active_project_name() or int(CAMPAIGN.get_current_step() or 0) < 4:
            return {"ok": False, "reason": "campaign_inactive"}

        target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
        if target not in {"plate", "char"}:
            target = "char"

        datasets_dir = CAMPAIGN.get_dir("datasets")
        runs_dir = CAMPAIGN.get_dir("runs")
        if datasets_dir is None:
            logger.error("Brak katalogu datasets dla aktywnego projektu.")
            return {"ok": False, "reason": "missing_datasets_dir"}

        try:
            self.set_campaign_training_target(target)
        except Exception:
            pass

        self.set_campaign_context(
            runs_dir=str(runs_dir) if runs_dir is not None else None,
            datasets_dir=str(datasets_dir),
        )

        readiness = self.get_campaign_step4_readiness(iteration_target=target)
        if not readiness.get("ok", False):
            return readiness

        datasets_dir = Path(datasets_dir)
        source_candidates = []
        try:
            for path in self._find_dataset_source_candidates(datasets_dir):
                inferred = self._infer_dataset_target(str(path))
                if target == "char":
                    if inferred != "char":
                        continue
                elif inferred not in {"plate", None}:
                    continue
                source_candidates.append(path)
        except Exception:
            source_candidates = []

        latest_source = max(source_candidates, key=lambda p: p.stat().st_mtime) if source_candidates else None

        if target == "char" and latest_source is not None:
            self.split_src_var.set(str(latest_source))
            self.split_out_var.set(str(latest_source.parent / f"{latest_source.name}_Split_[DATA_I_CZAS]"))
        elif target == "char":
            self.split_src_var.set("")
            self.split_out_var.set(str(datasets_dir / "[BRAK_DATASETU_ZRODLOWEGO]"))

        if target == "plate":
            plate_model = str(CAMPAIGN.get_global_model("plate") or "").strip()
            preferred_pose = "yolo11s-pose"
            try:
                pose_choices = self._get_base_model_choices_for_mode("plate")
            except Exception:
                pose_choices = []

            if plate_model and Path(plate_model).exists():
                self.base_model_var.set("Custom")
                self.base_custom_var.set(plate_model)
            else:
                self.base_model_var.set(
                    preferred_pose if preferred_pose in pose_choices else self._get_default_base_model_for_mode("plate")
                )
                self.base_custom_var.set("")
        else:
            char_model = str(CAMPAIGN.get_global_model("char") or "").strip()
            if char_model and Path(char_model).exists():
                self.base_model_var.set("Custom")
                self.base_custom_var.set(char_model)
            else:
                self.base_model_var.set(self._get_default_base_model_for_mode("char"))
                self.base_custom_var.set("")

        try:
            self._on_base_model_change()
        except Exception:
            pass

        try:
            self.imgsz_var.set(640 if target == "plate" else 256)
        except Exception:
            pass

        try:
            if bool(getattr(self, "_step4_train_unlocked", False)):
                self.main_nb.select(self.tab_train)
                self._select_step4_analysis_tab(self.hist_tab)
            else:
                self.main_nb.select(self.tab_dataset)
        except Exception:
            pass

        dataset_hint = str(self.dataset_var.get() or "").strip()
        return {
            "ok": True,
            "iteration_target": target,
            "latest_source": str(latest_source or ""),
            "dataset_hint": dataset_hint,
            "train_unlocked": bool(getattr(self, "_step4_train_unlocked", False)),
        }



    #=====================================
    def _restore_step4_campaign_project_state(self):
        """
        Odtwarza stan z4 dla aktywnego projektu oryg:
        - czyści ścieżki z poprzedniego projektu,
        - uzupełnia źródło splitu w pz1, jeśli istnieje sensowny zestaw źródłowy,
        - jeśli istnieje gotowy dataset treningowy dla bieżącego projektu,
        przechodzi od razu do pz2,
        - w przeciwnym razie zostawia użytkownika w pz1.
        """
        datasets_dir = Path(self._campaign_datasets_dir) if self._campaign_datasets_dir else None

        try:
            self.split_src_var.set("")
        except Exception:
            pass

        try:
            if datasets_dir is not None:
                self.split_out_var.set(str(datasets_dir / "[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]"))
            else:
                self.split_out_var.set(str(self._get_datasets_base_dir() / "[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]"))
        except Exception:
            pass

        try:
            self.dataset_var.set("")
        except Exception:
            pass

        try:
            if datasets_dir is not None:
                self.ds_out_var.set(str(datasets_dir / "Plates_CVAT_[DATA_I_CZAS]"))
            else:
                self.ds_out_var.set(str(self._get_datasets_base_dir() / "Plates_CVAT_[DATA_I_CZAS]"))
        except Exception:
            pass

        campaign_target = CAMPAIGN.get_iteration_target()
        remembered_target = campaign_target if campaign_target in ("char", "plate") else self.get_campaign_training_target()
        if remembered_target not in ("char", "plate"):
            remembered_target = "char"

        latest_source = None
        ready_dataset = None
        ready_target = remembered_target
        latest_xml = ""
        latest_xml_images = ""
        current_iter_images = ""

        if datasets_dir is not None and datasets_dir.exists():
            source_candidates = self._find_dataset_source_candidates(datasets_dir)
            if source_candidates:
                latest_source = max(source_candidates, key=lambda p: p.stat().st_mtime)

            ready_candidates = self._find_ready_dataset_candidates(datasets_dir)

            preferred = [rec for rec in ready_candidates if rec[1] == remembered_target]
            if preferred:
                ready_dataset, ready_target, _ = max(preferred, key=lambda rec: rec[2])
            elif ready_candidates:
                ready_dataset, ready_target, _ = max(ready_candidates, key=lambda rec: rec[2])

        try:
            auto_dir = CAMPAIGN.get_dir("auto_ann")
            if auto_dir is not None:
                xml_files = list(Path(auto_dir).rglob("annotations.xml"))
                if xml_files:
                    latest_xml_path = max(xml_files, key=lambda p: p.stat().st_mtime)
                    latest_xml = str(latest_xml_path)
                    manifest_path = latest_xml_path.parent / "run_manifest.json"
                    if manifest_path.exists():
                        try:
                            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        except Exception:
                            manifest = {}
                        manifest_input = str(manifest.get("input_dir") or "").strip() if isinstance(manifest, dict) else ""
                        if manifest_input and Path(manifest_input).exists():
                            latest_xml_images = manifest_input
        except Exception:
            latest_xml = ""
            latest_xml_images = ""

        try:
            raw_dir = CAMPAIGN.get_dir("raw")
            if raw_dir is not None:
                iter_num = CAMPAIGN.get_current_iteration_num()
                iter_dir = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
                if iter_dir.exists():
                    current_iter_images = str(iter_dir)
        except Exception:
            current_iter_images = ""

        if latest_source is not None:
            try:
                self.split_src_var.set(str(latest_source))
                split_base = latest_source.parent if latest_source.parent != datasets_dir else Path(self._campaign_datasets_dir)
                self.split_out_var.set(str(split_base / f"{latest_source.name}_Split_[DATA_I_CZAS]"))
            except Exception:
                pass

        try:
            self.cvat_xml_var.set(latest_xml)
        except Exception:
            pass

        try:
            self.cvat_images_var.set(latest_xml_images or current_iter_images)
        except Exception:
            pass

        active_target = campaign_target if campaign_target in ("char", "plate") else ready_target
        self._step4_dataset_mode = active_target
        self.set_campaign_training_target(active_target)
        self._step4_route_selected = bool(campaign_target in ("char", "plate"))
        self._step4_train_unlocked = False
        self._step4_campaign_finish_ready = False

        finish_state = {}
        try:
            finish_state = CAMPAIGN.get_step4_finish_state() or {}
        except Exception:
            finish_state = {}

        finish_ready = bool(finish_state.get("ready", False))
        finish_run_id = str(finish_state.get("run_id", "") or "").strip()
        finish_target = str(finish_state.get("target", "") or "").strip().lower()
        if finish_target not in ("char", "plate"):
            finish_target = active_target

        if finish_ready and finish_target == active_target:
            self._step4_campaign_finish_ready = True
            self._step4_train_unlocked = True
            self.current_run_id = finish_run_id or self.current_run_id

        if ready_dataset is not None:
            try:
                self.dataset_var.set(str(ready_dataset))
            except Exception:
                pass

            try:
                self._append_step4_builder_log(
                    f"[KAMPANIA] Odtworzono gotowy dataset projektu: {ready_dataset.name}. "
                    "Pozostaję w pz1, aby zachować liniowy workflow kroku 4."
                )
            except Exception:
                pass
        else:
            try:
                self._append_step4_builder_log(
                    "[KAMPANIA] Brak gotowego datasetu treningowego dla tego projektu. "
                    "Pozostaję w pz1."
                )
            except Exception:
                pass

        try:
            self._refresh_step4_dataset_mode_ui()
        except Exception:
            pass

        try:
            self._refresh_base_model_choices()
        except Exception:
            pass

        try:
            if active_target == "plate":
                plate_model = str(CAMPAIGN.get_global_model("plate") or "").strip()
                if plate_model and Path(plate_model).exists():
                    self.base_model_var.set("Custom")
                    self.base_custom_var.set(plate_model)
                else:
                    self.base_model_var.set(self._get_default_base_model_for_mode("plate"))
                    self.base_custom_var.set("")
            else:
                char_model = str(CAMPAIGN.get_global_model("char") or "").strip()
                if char_model and Path(char_model).exists():
                    self.base_model_var.set("Custom")
                    self.base_custom_var.set(char_model)
                else:
                    self.base_model_var.set(self._get_default_base_model_for_mode("char"))
                    self.base_custom_var.set("")
            self._on_base_model_change()
        except Exception:
            pass

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        try:
            target_tab = self.tab_dataset if bool(CAMPAIGN.get_active_project_name()) else self.tab_train
            if bool(CAMPAIGN.get_active_project_name()) and self._step4_campaign_finish_ready:
                target_tab = self.tab_train
            self.main_nb.select(target_tab)
        except Exception:
            pass

        try:
            if self._step4_route_selected:
                self._clear_step4_guidance()
            else:
                self._guide_step4_route_selection()
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

    def clear_campaign_context(self):
        """
        Czyści projektowy kontekst treningu i wraca do globalnych katalogów Workspace.
        Dodatkowo czyści kampanijne logi / wyniki widoczne w UI.
        """
        free_mode_target = CONFIG.normalize_task_target(
            getattr(self, "_step4_dataset_mode", getattr(self, "_campaign_training_target", "char"))
        )

        self._campaign_runs_dir = None
        self._campaign_datasets_dir = None

        self._rebind_free_mode_training_storage(target=free_mode_target, reload_history=False)

        self._reset_step4_transient_ui(
            target=free_mode_target,
            clear_builder_inputs=True,
            require_route_selection=False
        )

        try:
            self._update_step4_notebook_mode()
        except Exception:
            pass

        try:
            self._refresh_free_training_route_ui()
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
            self.ds_status.configure(text="Gotowy", foreground="green")
        except Exception:
            pass

        try:
            self.split_progress_var.set(0.0)
        except Exception:
            pass

        try:
            self.split_status.configure(text="Gotowy", foreground="black")
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
        target = (target or "char").strip().lower()
        if target not in ("char", "plate"):
            target = "char"

        self._campaign_training_target = target
        self._refresh_training_metric_reference()

        try:
            label = "znaków" if target == "char" else "tablic"
            self._append_train_log(f"[TARGET] Ustawiono kampanijny target treningu: model {label}.")
        except Exception:
            pass

    def get_campaign_training_target(self) -> str:
        target = getattr(self, "_campaign_training_target", "char")
        return target if target in ("char", "plate") else "char"
    
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
            self.split_feedback_frame.pack(
                fill=tk.X,
                after=self.btn_step4_split_frame
            )
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

    def _train_left_canvas_overflows(self) -> bool:
        canvas = getattr(self, "train_left_canvas", None)
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

        if not self._train_left_canvas_overflows():
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

    def _redirect_child_mousewheel_to_canvas(self, event, canvas):
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
        if units != 0 and self._train_left_canvas_overflows():
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

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        console_border = palette.get("console_border", palette.get("border", "#3c3c3c"))

        try:
            self._configure_train_progress_styles()
        except Exception:
            pass

        for label_name in (
            "free_training_route_title_lbl",
            "train_dataset_title_lbl",
            "train_base_title_lbl",
            "train_params_title_lbl",
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
            if hasattr(self, "train_left_canvas"):
                self.train_left_canvas.configure(
                    bg=palette.get("panel", "#252526"),
                    highlightbackground=console_border,
                    highlightcolor=console_border
                )
        except Exception:
            pass

        for frame_name in (
            "step4_route_panel_frame",
            "btn_step4_next_pulse_frame",
            "btn_step4_create_pulse_frame",
            "btn_step4_split_pulse_frame",
            "btn_step4_start_train_frame",
            "btn_step4_start_train_pulse_frame",
            "btn_step4_finish_pulse_frame",
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
        self._apply_training_recommendation_table_theme()
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
        if not hasattr(self, "right_nb") or not hasattr(self, "ranking_tab"):
            return

        ranking_enabled = self._is_ranking_available_for_selected_target()

        if ranking_enabled:
            if not getattr(self, "_step4_ranking_tab_visible", False):
                try:
                    self.right_nb.add(self.ranking_tab, text="Ranking")
                except Exception:
                    try:
                        self.right_nb.insert("end", self.ranking_tab, text="Ranking")
                    except Exception:
                        pass
                self._step4_ranking_tab_visible = True
            else:
                try:
                    self.right_nb.tab(self.ranking_tab, text="Ranking", state="normal")
                except Exception:
                    pass
            if self._is_ranking_tab_active():
                try:
                    self._prefill_ranking_reference_if_empty()
                except Exception:
                    pass
                try:
                    self._refresh_ranking_reference_ui()
                except Exception:
                    pass
            return

        try:
            if str(self.right_nb.select()) == str(self.ranking_tab):
                self.right_nb.select(self.hist_tab)
        except Exception:
            pass

        if getattr(self, "_step4_ranking_tab_visible", False):
            try:
                self.right_nb.hide(self.ranking_tab)
            except Exception:
                pass
            self._step4_ranking_tab_visible = False

    def _sync_step4_analysis_nav_buttons(self, event=None):
        try:
            self._refresh_step4_analysis_tab_visibility()
        except Exception:
            pass

    def _resolve_step4_guidance_buttons(self, attr_name: str):
        if attr_name == "step4_route_panel_frame":
            return [getattr(self, "btn_choose_plate", None), getattr(self, "btn_choose_char", None)]
        if attr_name == "btn_step4_finish_frame":
            return [
                getattr(self, "btn_step4_finish", None),
                getattr(self, "btn_step4_complete_project", None),
            ]

        candidates = [attr_name]
        if attr_name.endswith("_pulse_frame"):
            candidates.append(attr_name[:-12])
        if attr_name.endswith("_frame"):
            candidates.append(attr_name[:-6])

        resolved = []
        for candidate in candidates:
            widget = getattr(self, candidate, None)
            if isinstance(widget, ttk.Button):
                resolved.append(widget)

        unique_buttons = []
        seen = set()
        for btn in resolved:
            if btn is None:
                continue
            btn_id = str(btn)
            if btn_id not in seen:
                unique_buttons.append(btn)
                seen.add(btn_id)
        return unique_buttons

    def _resolve_step4_guidance_frame(self, attr_name: str):
        if not attr_name:
            return None

        if attr_name == "step4_route_panel_frame":
            return getattr(self, "step4_route_panel_frame", None)

        candidates = []
        if attr_name.endswith("_frame"):
            candidates.append(f"{attr_name[:-6]}_pulse_frame")
        candidates.append(attr_name)

        for candidate in candidates:
            widget = getattr(self, candidate, None)
            if isinstance(widget, tk.Frame):
                return widget

        return None

    def _set_step4_emphasis(self, frame_attr: str, enabled: bool, color: str = "#f39c12"):
        frame = self._resolve_step4_guidance_frame(frame_attr)
        if frame is not None:
            try:
                bg = self.app.palette.get("bg", "#1e1e1e") if frame_attr == "step4_route_panel_frame" else self.app.palette.get("panel", "#252526")
                self.app.set_frame_emphasis(frame, enabled, background=bg)
            except Exception as e:
                logger.debug(f"Nie udało się ustawić podświetlenia ramki dla {frame_attr}: {e}")

        buttons = self._resolve_step4_guidance_buttons(frame_attr)
        for btn in buttons:
            try:
                self.app.set_button_emphasis(btn, enabled)
            except Exception as e:
                logger.debug(f"Nie udało się ustawić podświetlenia przycisku dla {frame_attr}: {e}")

    def _pulse_step4_emphasis(self, frame_attr: str, pulses: int = 8, interval_ms: int = 260, color: str = "#f39c12"):
        frame = self._resolve_step4_guidance_frame(frame_attr)
        if frame is not None:
            try:
                bg = self.app.palette.get("bg", "#1e1e1e") if frame_attr == "step4_route_panel_frame" else self.app.palette.get("panel", "#252526")
                self.app.pulse_frame(frame, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True, background=bg)
            except Exception as e:
                logger.debug(f"Nie udało się pulsować ramki dla {frame_attr}: {e}")

        buttons = self._resolve_step4_guidance_buttons(frame_attr)
        for btn in buttons:
            try:
                self.app.pulse_button(btn, pulses=pulses, interval_ms=interval_ms, keep_emphasis=True)
            except Exception as e:
                logger.debug(f"Nie udało się pulsować przycisku dla {frame_attr}: {e}")

    def _clear_step4_guidance(self):
        for attr_name in (
            "step4_route_panel_frame",
            "btn_step4_create_frame",
            "btn_step4_split_frame",
            "btn_step4_next_frame",
            "btn_step4_start_train_frame",
            "btn_step4_finish_frame",
        ):
            try:
                self._set_step4_emphasis(attr_name, False)
            except Exception:
                pass

    def _guide_step4_route_selection(self):
        if not CAMPAIGN.get_active_project_name():
            return

        self._clear_step4_guidance()
        self._set_step4_emphasis("step4_route_panel_frame", True)
        self._pulse_step4_emphasis("step4_route_panel_frame")

    def _guide_step4_builder_action(self):
        if not CAMPAIGN.get_active_project_name():
            return

        self._clear_step4_guidance()
        frame_attr = "btn_step4_create_frame" if self._step4_dataset_mode == "plate" else "btn_step4_split_frame"
        self._set_step4_emphasis(frame_attr, True)
        self._pulse_step4_emphasis(frame_attr)

    def _guide_step4_next_action(self):
        if not CAMPAIGN.get_active_project_name():
            return

        self._clear_step4_guidance()
        self._set_step4_emphasis("btn_step4_next_frame", True)
        self._pulse_step4_emphasis("btn_step4_next_frame")

    def _guide_step4_training_action(self):
        if not CAMPAIGN.get_active_project_name():
            return

        self._clear_step4_guidance()
        self._set_step4_emphasis("btn_step4_start_train_frame", True)
        self._pulse_step4_emphasis("btn_step4_start_train_frame")

    def _guide_step4_finish_action(self):
        if not CAMPAIGN.get_active_project_name():
            return

        self._clear_step4_guidance()
        self._set_step4_emphasis("btn_step4_finish_frame", True)
        self._pulse_step4_emphasis("btn_step4_finish_frame")

    def _mark_step4_dataset_ready(self, dataset_path: str | Path | None = None):
        if dataset_path:
            try:
                self.dataset_var.set(str(dataset_path))
            except Exception:
                pass

        if CAMPAIGN.get_active_project_name():
            self._step4_train_unlocked = True

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        try:
            self._guide_step4_next_action()
        except Exception:
            pass
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

    def _set_step4_dataset_mode(self, mode: str):
        mode = (mode or "char").strip().lower()
        if mode not in ("char", "plate"):
            mode = "char"

        if mode != str(getattr(self, "_step4_dataset_mode", "char") or "char"):
            active_label = self._get_active_step4_operation_label()
            if active_label:
                messagebox.showinfo(
                    "Proces w toku",
                    "Nie można teraz zmienic toru treningu.\n\n"
                    f"Najpierw poczekaj na zakonczenie: {active_label}.",
                )
                return

        campaign_active = bool(CAMPAIGN.get_active_project_name())
        locked_target = self._get_locked_campaign_training_target()
        if campaign_active and locked_target in ("char", "plate"):
            if mode != locked_target:
                messagebox.showinfo(
                    "Tor zablokowany przez E2",
                    "Tor treningu dla tej iteracji został już ustalony w wizardzie E2.\n\n"
                    f"Ta iteracja pozostaje w torze {self._format_training_target_label(locked_target)}."
                )
            mode = locked_target

        self._step4_dataset_mode = mode
        self.set_campaign_training_target(mode)
        if campaign_active:
            self._step4_route_selected = True
            self._step4_train_unlocked = False
        else:
            self._rebind_free_mode_training_storage(target=mode)
            try:
                self.rank_models_dir.set(str(self._get_ranking_models_default_dir()))
            except Exception:
                pass
        try:
            self._refresh_base_model_choices()
        except Exception:
            pass
        try:
            self._refresh_training_recommendation_table()
        except Exception:
            pass
        self._refresh_step4_dataset_mode_ui()
        self._refresh_step4_campaign_navigation_ui()
        try:
            self._refresh_free_training_route_ui()
        except Exception:
            pass
        try:
            self._update_training_dataset_hint()
        except Exception:
            pass

        try:
            label = "tablic (YOLO Pose)" if mode == "plate" else "znaków (YOLO Detect)"
            self._append_step4_builder_log(f"[TRYB] Wybrano tor budowy datasetu dla modelu {label}.")
        except Exception:
            pass

        if campaign_active:
            try:
                self._guide_step4_builder_action()
            except Exception:
                pass

    def _refresh_step4_campaign_builder_inputs_ui(self):
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        locked_target = self._get_locked_campaign_training_target()
        route_locked = campaign_active and locked_target in ("char", "plate")
        mode = getattr(self, "_step4_dataset_mode", "char")

        try:
            route_manager = str(self.step4_route_panel_frame.winfo_manager())
        except Exception:
            route_manager = ""

        if route_locked:
            if route_manager == "pack":
                try:
                    self.step4_route_panel_frame.pack_forget()
                except Exception:
                    pass
        else:
            if route_manager != "pack":
                try:
                    self.step4_route_panel_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8), before=self.step4_mode_right_host)
                except Exception:
                    pass

        creator_summary = ""
        if campaign_active and mode == "plate":
            xml_value = self._shorten_training_text(self._format_workspace_relative_path(self.cvat_xml_var.get()), 96)
            images_value = self._shorten_training_text(self._format_workspace_relative_path(self.cvat_images_var.get()), 96)
            creator_summary = (
                "Źródła do budowy datasetu tablic zostały już przygotowane wczesniej.\n"
                f"Anotacje tablic: {xml_value}\n"
                f"Obrazy źródłowe: {images_value}"
            )

        split_summary = ""
        if campaign_active and mode == "char":
            split_src_value = self._shorten_training_text(self._format_workspace_relative_path(self.split_src_var.get()), 96)
            split_summary = (
                "Źródło do podziału datasetu znaków zostało już wybrane wcześniej.\n"
                f"Dataset źródłowy: {split_src_value}"
            )

        try:
            if campaign_active and mode == "plate":
                self.creator_xml_row.pack_forget()
                self.creator_images_row.pack_forget()
                self.creator_source_summary_lbl.configure(text=creator_summary)
                if str(self.creator_source_summary_lbl.winfo_manager()) != "pack":
                    self.creator_source_summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
            else:
                if str(self.creator_xml_row.winfo_manager()) != "pack":
                    self.creator_xml_row.pack(fill=tk.X, pady=2, before=self.creator_source_summary_lbl)
                if str(self.creator_images_row.winfo_manager()) != "pack":
                    self.creator_images_row.pack(fill=tk.X, pady=2, before=self.creator_source_summary_lbl)
                if str(self.creator_source_summary_lbl.winfo_manager()) == "pack":
                    self.creator_source_summary_lbl.pack_forget()
        except Exception:
            pass

        try:
            if campaign_active and mode == "char":
                self.split_source_row.pack_forget()
                self.split_source_summary_lbl.configure(text=split_summary)
                if str(self.split_source_summary_lbl.winfo_manager()) != "pack":
                    self.split_source_summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))
            else:
                if str(self.split_source_row.winfo_manager()) != "pack":
                    self.split_source_row.pack(fill=tk.X, pady=2, before=self.split_source_summary_lbl)
                if str(self.split_source_summary_lbl.winfo_manager()) == "pack":
                    self.split_source_summary_lbl.pack_forget()
        except Exception:
            pass

    def _refresh_step4_dataset_mode_ui(self):
        try:
            self._refresh_free_training_route_ui()
        except Exception:
            pass

        try:
            self._refresh_step4_analysis_tab_visibility()
        except Exception:
            pass

        if not hasattr(self, "ds_mode_host"):
            return

        mode = getattr(self, "_step4_dataset_mode", "char")
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        route_selected = bool(getattr(self, "_step4_route_selected", False))
        locked_target = self._get_locked_campaign_training_target()
        route_locked = campaign_active and locked_target in ("char", "plate")

        try:
            self.ds_creator_frame.pack_forget()
        except Exception:
            pass

        try:
            self.ds_split_frame.pack_forget()
        except Exception:
            pass

        try:
            self.ds_mode_waiting_frame.pack_forget()
        except Exception:
            pass

        if campaign_active and not route_selected:
            self.ds_mode_title_var.set("Wybierz tor po lewej stronie")
            self.ds_mode_desc_var.set(
                "W trybie projektu najpierw wybierz tor tablic albo tor znaków. "
                "Dopiero wtedy odblokuje się panel budowy datasetu."
            )
            self.btn_choose_plate.configure(state=tk.NORMAL)
            self.btn_choose_char.configure(state=tk.NORMAL)
            self.ds_mode_waiting_frame.pack(fill=tk.X, expand=False)
            self.btn_step4_next.configure(
                text="Wybierz tor",
                state=tk.DISABLED
            )
            return

        if mode == "plate":
            self.ds_mode_title_var.set("Tor tablic (YOLO Pose)")
            self.ds_mode_desc_var.set(
                "Wybierz ten tor, jeśli chcesz zbudować dataset tablic z XML CVAT "
                "i trenować model tablic rejestracyjnych."
            )
            self.btn_choose_plate.configure(state=tk.DISABLED)
            self.btn_choose_char.configure(state=(tk.DISABLED if route_locked else tk.NORMAL))
            self.ds_creator_frame.pack(fill=tk.X, expand=False)
            self.btn_step4_next.configure(text="Dalej do treningu")
            if route_locked:
                self.ds_mode_desc_var.set(
                    "Ten etap korzysta z zatwierdzonych zrodel projektu i buduje dataset tablic bez ponownego wybierania XML ani obrazów."
                )
        else:
            self.ds_mode_title_var.set("Tor znaków (YOLO Detect)")
            self.ds_mode_desc_var.set(
                "Wybierz ten tor, jeśli chcesz przygotować i podzielić dataset znaków "
                "i trenować model znaków na tablicach."
            )
            self.btn_choose_plate.configure(state=(tk.DISABLED if route_locked else tk.NORMAL))
            self.btn_choose_char.configure(state=tk.DISABLED)
            self.ds_split_frame.pack(fill=tk.X, expand=False)
            self.btn_step4_next.configure(text="Dalej do treningu")
            if route_locked:
                self.ds_mode_desc_var.set(
                    "Ten etap korzysta z gotowego źródła datasetu znaków projektu i prowadzi od razu do podzialu oraz treningu."
                )

        if route_locked:
            self.btn_choose_plate.configure(state=tk.DISABLED)
            self.btn_choose_char.configure(state=tk.DISABLED)
            self.ds_mode_desc_var.set(
                str(self.ds_mode_desc_var.get() or "").strip()
                + " Tor tej iteracji został zatwierdzony w E2 i nie może być zmieniony w Z4."
            )

        try:
            self._refresh_step4_campaign_builder_inputs_ui()
        except Exception:
            pass

    def _step4_dataset_go_next(self):
        if CAMPAIGN.get_active_project_name() and not getattr(self, "_step4_train_unlocked", False):
            return

        try:
            mode = getattr(self, "_step4_dataset_mode", "char")
            self.set_campaign_training_target(mode)
        except Exception:
            pass

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        try:
            self.main_nb.select(self.tab_train)
        except Exception:
            pass

        try:
            self._select_step4_analysis_tab(self.hist_tab)
        except Exception:
            pass

        if CAMPAIGN.get_active_project_name():
            try:
                if getattr(self, "_step4_campaign_finish_ready", False):
                    self._guide_step4_finish_action()
                else:
                    self._guide_step4_training_action()
            except Exception:
                pass

    def _step4_dataset_go_back(self):
        if CAMPAIGN.get_active_project_name():
            return

        self._append_step4_builder_log(
            "[NAWIGACJA] Tryb swobodny: brak poprzedniego kroku wizardowego do otwarcia."
        )

    def _refresh_step4_campaign_navigation_ui(self):
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        train_unlocked = bool(getattr(self, "_step4_train_unlocked", False))
        route_selected = bool(getattr(self, "_step4_route_selected", False))

        try:
            self._update_step4_notebook_mode()
        except Exception:
            pass

        try:
            self._refresh_step4_analysis_tab_visibility()
        except Exception:
            pass

        try:
            if campaign_active and getattr(self, "_step4_dataset_tab_visible", False):
                self.main_nb.tab(self.tab_dataset, state="normal")
            self.main_nb.tab(
                self.tab_train,
                state=("normal" if (not campaign_active or train_unlocked) else "disabled")
            )
        except Exception:
            pass

        try:
            next_state = tk.NORMAL if (not campaign_active or (route_selected and train_unlocked)) else tk.DISABLED
            self.btn_step4_next.configure(state=next_state)
        except Exception:
            pass

        try:
            if campaign_active:
                self.btn_step4_back.grid_remove()
            else:
                self.btn_step4_back.grid()
        except Exception:
            pass

        try:
            if (
                campaign_active
                and getattr(self, "_step4_dataset_tab_visible", False)
                and not train_unlocked
                and str(self.main_nb.select()) == str(self.tab_train)
            ):
                self.main_nb.select(self.tab_dataset)
        except Exception:
            pass

        if not hasattr(self, "step4_train_nav"):
            return

        try:
            if campaign_active:
                self.step4_train_nav.grid()
            else:
                self.step4_train_nav.grid_remove()
        except Exception:
            pass

        try:
            self._update_training_dataset_hint()
        except Exception:
            pass

        try:
            self.btn_step4_train_back.configure(
                state=(tk.NORMAL if campaign_active else tk.DISABLED)
            )
        except Exception:
            pass

        try:
            finish_state = tk.NORMAL if (campaign_active and self._step4_campaign_finish_ready) else tk.DISABLED
            self.btn_step4_finish.configure(state=finish_state)
        except Exception:
            pass

        try:
            complete_state = tk.DISABLED
            if campaign_active and self._step4_campaign_finish_ready:
                active_target = self.get_campaign_training_target()
                active_model = CAMPAIGN.get_global_model(active_target) if active_target in ("char", "plate") else ""
                if active_model and Path(active_model).exists():
                    complete_state = tk.NORMAL
            self.btn_step4_complete_project.configure(state=complete_state)
        except Exception:
            pass


    def _step4_train_go_back(self):
        if CAMPAIGN.get_active_project_name():
            try:
                self.main_nb.select(self.tab_dataset)
                if getattr(self, "_step4_train_unlocked", False):
                    self._guide_step4_next_action()
                return
            except Exception:
                pass


    def _finish_campaign_step4(self):
        if not CAMPAIGN.get_active_project_name():
            return

        if not self._step4_campaign_finish_ready:
            return

        try:
            CAMPAIGN.set_current_step(5)
        except Exception:
            return

        self._step4_campaign_finish_ready = False
        try:
            CAMPAIGN.set_step4_finish_state(False)
        except Exception:
            pass

        try:
            self._append_train_log(
                "[KAMPANIA] Użytkownik domknął etap iteracji. "
                "Cykl iteracji został domknięty i można rozpocząć kolejną iterację."
            )
        except Exception:
            pass

        try:
            self.main_nb.select(self.tab_dataset)
        except Exception:
            pass

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._refresh_dashboard()
        except Exception:
            pass

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        try:
            self.app.update_status(
                "Etap iteracji został zamknięty. W kampanii możesz rozpocząć nową iterację od tego samego zestawu zdjęć (E2) albo od nowego zestawu zdjęć (E1). Aktywne modele projektu pozostały zachowane.",
                "info"
            )
        except Exception:
            pass

        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass

    def _complete_campaign_project(self):
        if not CAMPAIGN.get_active_project_name():
            return

        if not self._step4_campaign_finish_ready:
            return

        should_finish = self.app.themed_confirm(
            "Zakonczenie projektu",
            "Czy oznaczyc ten projekt jako zakończony?\n\n"
            "Projekt pozostanie dostępny do przegladu, ale dashboard nie będzie już prowadzil do nowej iteracji, "
            "dopoki ręcznie go nie wznowisz.",
            parent=self.frame,
            confirm_label="Zakończ projekt",
            tone="info"
        )
        if not should_finish:
            return

        if not CAMPAIGN.complete_project():
            return

        self._step4_campaign_finish_ready = False
        try:
            CAMPAIGN.set_step4_finish_state(False)
        except Exception:
            pass

        try:
            self._append_train_log(
                "[KAMPANIA] Użytkownik oznaczyl projekt jako zakończony. "
                "Nowa iteracja nie zostanie już proponowana, dopoki projekt nie zostanie wznowiony."
            )
        except Exception:
            pass

        try:
            self.main_nb.select(self.tab_dataset)
        except Exception:
            pass

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._refresh_dashboard()
        except Exception:
            pass

        try:
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        try:
            project_name = CAMPAIGN.get_active_project_name()
            if project_name:
                self.app.update_status(
                    f"Projekt '{project_name}' został oznaczony jako zakończony.",
                    "info"
                )
        except Exception:
            pass

        try:
            self.app.update_campaign_tab_access()
        except Exception:
            pass

        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass

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


    def _promote_trained_model_to_campaign_if_needed(self):
        """
        Jeśli aktywny trening dotyczył modelu kampanijnego,
        to po pojawieniu się best.pt promuje model do odpowiedniego
        slotu projektu: best_char_model albo best_plate_model.
        """
        target = (self._pending_campaign_model_type or "").strip().lower()
        if target not in ("char", "plate"):
            return False

        if not self.current_run_id:
            return False

        best_model = self._find_best_weights_for_run(self.current_run_id)
        if best_model is None or not best_model.exists():
            return False

        CAMPAIGN.set_global_model(target, str(best_model))

        try:
            if target == "char":
                self._append_train_log(
                    f"[MODEL] Ustawiono nowy aktywny model znaków projektu: {best_model}"
                )
            else:
                self._append_train_log(
                    f"[MODEL] Ustawiono nowy aktywny model tablic projektu: {best_model}"
                )
        except Exception:
            pass

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._refresh_dashboard()
        except Exception:
            pass

        try:
            self._complete_campaign_step4_if_needed(target)
        except Exception:
            pass

        self._pending_campaign_model_type = None
        return True

    def _complete_campaign_step4_if_needed(self, target: str) -> bool:
        """
        Po promocji modelu kampanijnego tylko sygnalizuje gotowość
        do ręcznego domknięcia etapu iteracji. Nie zamyka etapu automatycznie.
        """
        target = str(target or "").strip().lower()
        if target not in ("char", "plate"):
            return False

        if not CAMPAIGN.get_active_project_name():
            return False

        try:
            label = "znaków" if target == "char" else "tablic"
            self._append_train_log(
                f"[KAMPANIA] Model {label} został wypromowany do projektu. "
                "Możesz teraz domknąć etap iteracji albo oznaczyć cały projekt jako zakończony."
            )
        except Exception:
            pass

        try:
            campaign_tab = self.app.tabs.get("campaign")
            if campaign_tab:
                campaign_tab._refresh_dashboard()
        except Exception:
            pass

        try:
            self.app.update_status(
                f"✅ Zakończono trening toru '{target}'. Model został zapisany w projekcie.",
                "info"
            )
        except Exception:
            pass

        return True

    def _show_training_completion_summary(self, *, promoted: bool, can_finish_step4: bool):
        run_id = str(self.current_run_id or "").strip()
        if not run_id:
            return

        if str(getattr(self, "_last_training_completion_summary_run_id", "") or "").strip() == run_id:
            return

        run = None
        try:
            run = self.history.get_run(run_id)
        except Exception:
            run = None

        target = self.get_campaign_training_target()
        if target not in ("char", "plate"):
            target = str(getattr(self, "_pending_campaign_model_type", "") or "").strip().lower()

        if target == "char":
            target_label = "znaków"
        elif target == "plate":
            target_label = "tablic"
        else:
            target_label = "projektu"

        success = bool(run and str(getattr(run, "status", "") or "").strip().lower() == TrainingStatus.COMPLETED.value)
        title = "Podsumowanie treningu"
        tone = "success" if success else "warning"

        lines = []
        if run is not None:
            lines.append(f"Run: {run.name}")
            lines.append(f"Model bazowy: {run.base_model}")
            lines.append(f"Dataset: {run.dataset_path}")
            if float(getattr(run, "best_map50_95", 0.0) or 0.0) > 0.0:
                lines.append(f"Najlepsze mAP50-95: {float(run.best_map50_95):.3f}")

        if can_finish_step4:
            if promoted:
                lines.append("")
                lines.append(f"Nowy aktywny model {target_label} został zapisany w projekcie.")
            else:
                lines.append("")
                lines.append(f"Aktywny model {target_label} projektu nie został podmieniony.")
            lines.append("Dalej: możesz kliknąć „Zakończ etap iteracji” albo „Zakończ projekt”.")
        else:
            lines.append("")
            if success:
                lines.append("Trening zakończył się poprawnie.")
            else:
                lines.append("Trening został zatrzymany albo zakończył się błędem.")
            lines.append("Dalej: możesz zmienić ustawienia i uruchomić kolejny trening.")

        try:
            self.app.themed_info(
                title,
                "\n".join(lines).strip(),
                parent=self.frame,
                tone=tone,
            )
            self._last_training_completion_summary_run_id = run_id
        except Exception:
            pass

    def _poll_training_completion(self):
        """
        Lekki polling końca treningu:
        - czeka aż trainer.is_training spadnie do False
        - jeśli powstał best.pt, promuje model do projektu
        - w trybie kampanijnym odblokowuje ręczne zakończenie kroku 4
        """
        try:
            is_training = bool(getattr(self.trainer, "is_training", False))

            if is_training:
                self._training_completion_poll_job = self.frame.after(3000, self._poll_training_completion)
                return

            self._training_completion_poll_job = None
            promoted = self._promote_trained_model_to_campaign_if_needed()

            try:
                self._load_history()
            except Exception:
                pass

            campaign_active = bool(CAMPAIGN.get_active_project_name())
            can_finish_step4 = campaign_active and bool(self.current_run_id)

            if can_finish_step4 and promoted:
                self._step4_campaign_finish_ready = True
                finish_target = self.get_campaign_training_target()
                if finish_target not in ("char", "plate"):
                    finish_target = (self._pending_campaign_model_type or "").strip().lower()
                try:
                    CAMPAIGN.set_step4_finish_state(
                        True,
                        run_id=str(self.current_run_id or ""),
                        target=finish_target,
                    )
                except Exception:
                    pass
                self._set_training_ui_idle_state(
                    "Trening zakończony. Kliknij „Zakończ etap iteracji...” albo „Zakończ projekt”.",
                    "#1e8449"
                )
            elif can_finish_step4:
                target = self.get_campaign_training_target()
                if target not in ("char", "plate"):
                    target = (self._pending_campaign_model_type or "").strip().lower()
                target_label = "model projektu" if target not in ("char", "plate") else (
                    "model znaków projektu" if target == "char" else "model tablic projektu"
                )

                self._step4_campaign_finish_ready = True
                try:
                    CAMPAIGN.set_step4_finish_state(
                        True,
                        run_id=str(self.current_run_id or ""),
                        target=target,
                    )
                except Exception:
                    pass
                self._set_training_ui_idle_state(
                    (
                        "Trening zakończony lub zatrzymany bez podmiany aktywnego "
                        f"{target_label}. Możesz domknąć etap iteracji i zdecydować, "
                        "czy kolejna iteracja ma użyć tego samego zestawu zdjęć, czy nowego."
                    ),
                    "#7f8c8d"
                )
                try:
                    self._append_train_log(
                        "[KAMPANIA] Ten run treningu nie wypromował nowego aktywnego modelu projektu. "
                        "Możesz domknąć etap iteracji i rozpocząć kolejną iterację od tego samego "
                        "zestawu zdjęć albo od nowego zestawu zdjęć."
                    )
                except Exception:
                    pass
            else:
                self._step4_campaign_finish_ready = False
                try:
                    if CAMPAIGN.get_active_project_name():
                        CAMPAIGN.set_step4_finish_state(False)
                except Exception:
                    pass
                self._set_training_ui_idle_state("Trening zakończony lub zatrzymany.", "#2c3e50")

            try:
                self._refresh_step4_campaign_navigation_ui()
            except Exception:
                pass

            try:
                self._show_training_completion_summary(promoted=promoted, can_finish_step4=can_finish_step4)
            except Exception:
                pass

            if can_finish_step4:
                try:
                    self._guide_step4_finish_action()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Błąd pollingu końca treningu: {e}")
            self._training_completion_poll_job = None
            self._pending_campaign_model_type = None
            self._step4_campaign_finish_ready = False
            try:
                if CAMPAIGN.get_active_project_name():
                    CAMPAIGN.set_step4_finish_state(False)
            except Exception:
                pass
            self._set_training_ui_idle_state("Błąd monitorowania końca treningu.", "#c0392b")

            try:
                self._refresh_step4_campaign_navigation_ui()
            except Exception:
                pass

    def _set_training_ui_running_state(self):
        try:
            self.btn_start_train.configure(state=tk.DISABLED)
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

    
    def _scan_training_cuda_devices(self) -> list[dict]:
        devices: list[dict] = []
        try:
            import torch

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
            try:
                wanted_index = int(raw.split(":", 1)[1])
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
        if raw in {"auto", "cpu"} or raw.startswith("cuda:"):
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

        if effective_raw == "cpu" or profile is None:
            return {
                "effective_raw": "cpu",
                "device_name": "CPU",
                "memory_gb": 0.0,
                "epochs": 100,
                "batch": 4 if target == "char" else 2,
                "imgsz": 640,
                "lr0": 0.01,
                "note": (
                    "CPU zadziala, ale trening będzie wyraznie wolniejszy. "
                    "Gdy brakuje czasu, lepiej poczekac na GPU CUDA."
                ),
            }

        memory_gb = float(profile.get("memory_gb", 0.0) or 0.0)
        if memory_gb <= 4.5:
            batch = 8 if target == "char" else 4
            imgsz = 640
        elif memory_gb <= 6.5:
            batch = 12 if target == "char" else 8
            imgsz = 640 if target == "char" else 768
        elif memory_gb <= 8.5:
            batch = 16 if target == "char" else 12
            imgsz = 768 if target == "char" else 960
        elif memory_gb <= 12.5:
            batch = 24 if target == "char" else 16
            imgsz = 960
        else:
            batch = 32 if target == "char" else 24
            imgsz = 960 if target == "char" else 1280

        return {
            "effective_raw": effective_raw,
            "device_name": str(profile.get("name", effective_raw)),
            "memory_gb": memory_gb,
            "epochs": 100,
            "batch": batch,
            "imgsz": imgsz,
            "lr0": 0.01,
            "note": (
                "To jest konserwatywny punkt startowy. "
                "Jesli zabraknie VRAM, najpierw zmniejsz batch size, dopiero potem rozdzielczosc."
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
            f"Z4 korzysta z globalnego ustawienia urządzenia. {prefix} Tor: {selected_target}. "
            f"Sugerowany start: epoki {recommendation['epochs']}, batch {recommendation['batch']}, "
            f"rozdzielczosc {recommendation['imgsz']}, lr0 {recommendation['lr0']:.3f}. "
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
            
        item = self.tree.item(sel[0])
        # Wartość z drzewa traktujemy zawsze jako zwykły tekst.
        corrupted_id = str(item["values"][0])
        
        # Porównujemy identyfikatory po usunięciu znaków specjalnych.
        for db_key, run_obj in self.history.runs.items():
            # Usuwamy wszystkie znaki poza literami i cyframi.
            clean_db_key = "".join(filter(str.isalnum, db_key))
            clean_ui_key = "".join(filter(str.isalnum, corrupted_id))
            
            # Jeśli "rdzeń" klucza się zgadza, to znaczy że znaleźliśmy nasz trening!
            if clean_db_key == clean_ui_key:
                return run_obj
                
        # Zachowaj prosty fallback na wypadek rozbieżności w formacie identyfikatora.
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
        self._step4_dataset_tab_visible = True

        self._build_dataset_tab()
        self._build_train_tab()
        self._update_step4_notebook_mode()

    def _build_dataset_tab(self):
        root = ttk.Frame(self.tab_dataset, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.X, expand=False)

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

        self.btn_choose_plate = ttk.Button(
            left,
            text="Tor tablic (YOLO Pose)",
            command=lambda: self._set_step4_dataset_mode("plate")
        )
        self.btn_choose_plate.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            left,
            text=(
                "Buduje dataset tablic z XML CVAT i prowadzi dalej do treningu "
                "modelu tablic rejestracyjnych."
            ),
            wraplength=240,
            justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 12))

        self.btn_choose_char = ttk.Button(
            left,
            text="Tor znaków (YOLO Detect)",
            command=lambda: self._set_step4_dataset_mode("char")
        )
        self.btn_choose_char.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            left,
            text=(
                "Dzieli gotowy dataset znaków i prowadzi dalej do treningu "
                "modelu znaków na tablicach."
            ),
            wraplength=240,
            justify=tk.LEFT
        ).pack(anchor=tk.W)

        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.X, expand=True)
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

        self.ds_mode_host = ttk.Frame(right)
        self.ds_mode_host.pack(fill=tk.X, expand=False, pady=(8, 0))

        self.ds_mode_waiting_frame = ttk.LabelFrame(
            self.ds_mode_host,
            text=" Oczekiwanie na wybór toru ",
            padding=18
        )
        ttk.Label(
            self.ds_mode_waiting_frame,
            text=(
                "Panel zostanie odblokowany po wyborze toru po lewej stronie.\n\n"
                "W trybie projektu najpierw wskaż, czy prowadzisz tor tablic czy tor znaków."
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
        self.step4_builder_nav.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
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

        self.btn_step4_next_pulse_frame = tk.Frame(
            self.btn_step4_next_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_next_pulse_frame.pack(anchor=tk.E)

        self.btn_step4_next = ttk.Button(
            self.btn_step4_next_pulse_frame,
            text="Dalej: Trening i analiza modelu znaków",
            command=self._step4_dataset_go_next,
            style="Accent.TButton"
        )
        self.btn_step4_next.pack()
        self.btn_step4_next.configure(text="Dalej do treningu", padding=(8, 2), width=NAV_BUTTON_WIDTH)

        HELP.bind_help(self.step4_route_panel_frame, "tr_route_panel")
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
        self._set_step4_dataset_mode(initial_mode)

    def _build_creator_ui(self):
        f = self.ds_creator_frame
        palette = getattr(self.app, "palette", {})
        ttk.Label(
            f,
            text="Tworzy strukturę YOLO Pose na podstawie wyeksportowanego pliku annotations.xml.",
            font=("Segoe UI", 9)
        ).pack(anchor=tk.W, pady=(0, 10))
        row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
        self.split_source_row = row1
        self.creator_xml_row = row1
        ttk.Label(row1, text="CVAT XML:").pack(side=tk.LEFT)
        self.cvat_xml_var = tk.StringVar()
        self.cvat_xml_entry = ttk.Entry(row1, textvariable=self.cvat_xml_var)
        self.cvat_xml_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.btn_pick_cvat_xml = ttk.Button(row1, text="Wybierz", command=lambda: self._pick_file(self.cvat_xml_var, "*.xml"))
        self.btn_pick_cvat_xml.pack(side=tk.LEFT)

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        self.creator_images_row = row2
        ttk.Label(row2, text="Folder obrazów:").pack(side=tk.LEFT)
        self.cvat_images_var = tk.StringVar()
        self.cvat_images_entry = ttk.Entry(row2, textvariable=self.cvat_images_var)
        self.cvat_images_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.btn_pick_cvat_images = ttk.Button(row2, text="Wybierz", command=lambda: self._pick_dir(self.cvat_images_var))
        self.btn_pick_cvat_images.pack(side=tk.LEFT)

        self.creator_source_summary_lbl = ttk.Label(
            f,
            text="",
            justify=tk.LEFT,
            wraplength=720
        )

        row3 = ttk.Frame(f); row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Zapis danych:").pack(side=tk.LEFT)
        # Ścieżka docelowa jest wyliczana automatycznie i pozostaje tylko do odczytu.
        self.ds_out_var = tk.StringVar(value=str(self._get_datasets_base_dir() / "Plates_CVAT_[DATA_I_CZAS]"))
        ttk.Entry(row3, textvariable=self.ds_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        creator_ratios = ttk.Frame(f)
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

        self.btn_step4_create_pulse_frame = tk.Frame(
            self.btn_step4_create_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_create_pulse_frame.pack(anchor=tk.W)

        self.btn_step4_create = ttk.Button(
            self.btn_step4_create_pulse_frame,
            text="Stwórz dataset",
            command=self._create_dataset_thread
        )
        self.btn_step4_create.pack()
        
        self.ds_progress_var = tk.DoubleVar(value=0.0)
        self.ds_progress = TrainProgressBar(
            f,
            variable=self.ds_progress_var,
            maximum=100,
            thickness=6,
            trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
            fill_color=palette.get("accent", "#0e639c"),
            bg=palette.get("panel", "#252526"),
            height=10,
        )
        self.ds_progress.pack(fill=tk.X, pady=2)
        
        self.ds_status = ttk.Label(f, text="Gotowy", foreground="green")
        self.ds_status.pack(anchor=tk.W)

        # Powiązania pomocy dla budowy datasetu z CVAT.
        HELP.bind_help(row1, "tr_cvat_xml")
        HELP.bind_help(row2, "tr_cvat_img")
        HELP.bind_help(creator_ratios, "tr_split_ratios")
        HELP.bind_help(self.btn_step4_create, "tr_cvat_btn")

    def _build_splitter_ui(self):
        f = self.ds_split_frame
        palette = getattr(self.app, "palette", {})
        ttk.Label(
            f,
            text="Dzieli zbiór (np. wygenerowany w zakładce Znaków) na foldery train/val potrzebne do treningu.",
            font=("Segoe UI", 9)
        ).pack(anchor=tk.W, pady=(0, 10))
        
        row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Źródło (np. mega-dataset):").pack(side=tk.LEFT)
        self.split_src_var = tk.StringVar()
        self.split_src_entry = ttk.Entry(row1, textvariable=self.split_src_var)
        self.split_src_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.btn_pick_split_src = ttk.Button(row1, text="Wybierz", command=lambda: self._pick_dir(self.split_src_var))
        self.btn_pick_split_src.pack(side=tk.LEFT)

        self.split_source_summary_lbl = ttk.Label(
            f,
            text="",
            justify=tk.LEFT,
            wraplength=720
        )

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Wynik podziału:").pack(side=tk.LEFT)
        # Ścieżka wyniku splitu jest wyliczana automatycznie i pozostaje tylko do odczytu.
        self.split_out_var = tk.StringVar(value=str(self._get_datasets_base_dir() / "[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]"))
        ttk.Entry(row2, textvariable=self.split_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ratios = ttk.Frame(f); ratios.pack(fill=tk.X, pady=10)
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

        self.btn_step4_split_pulse_frame = tk.Frame(
            self.btn_step4_split_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_split_pulse_frame.pack(anchor=tk.W)

        self.btn_step4_split = ttk.Button(
            self.btn_step4_split_pulse_frame,
            text="Rozpocznij Podział (Split)",
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
            fill_color=palette.get("guide", palette.get("warning", "#f0b44c")),
            bg=palette.get("panel", "#252526"),
            height=10,
        )
        self.split_progress.pack(fill=tk.X, pady=2)
        self.split_status = ttk.Label(self.split_feedback_frame, text="Gotowy")
        self.split_status.pack(anchor=tk.W)
        self._set_split_feedback_visibility(False)

        # Powiązania pomocy dla splitu datasetu.
        HELP.bind_help(row1, "tr_split_src")
        HELP.bind_help(ratios, "tr_split_ratios")
        HELP.bind_help(self.btn_step4_split, "tr_split_btn")
        self._update_ratio_labels()

    def _build_train_tab(self):
        palette = getattr(self.app, "palette", {})
        root = ttk.Frame(self.tab_train, padding=5)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.train_pane = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.train_pane.grid(row=0, column=0, sticky="nsew")

        self.left = ttk.LabelFrame(self.train_pane, text=" Trening ", padding=10)
        self.right = ttk.LabelFrame(self.train_pane, text=" Wyniki i narzedzia ", padding=10)
        self.train_pane.add(self.left, weight=0)
        self.train_pane.add(self.right, weight=1)

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
        self._train_left_content_max_width = 560
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
            text="Co chcesz trenowac?",
            fade_ratio=0.74,
        )
        self.free_training_route_title_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        route_intro = ttk.Label(
            self.free_training_route_host,
            text=(
                "Najpierw wybierz tor treningu. Ten wybór ustala, jakiego datasetu oczekuje formularz "
                "i jakiego typu model bazowy ma sens."
            ),
            style="PanelMuted.TLabel",
            wraplength=360,
            justify=tk.LEFT
        )
        route_intro.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))
        self._register_train_left_wrap_target(
            route_intro,
            container=self.free_training_route_host,
            padding=28,
            min_wrap=220,
        )

        self.free_training_route_cards_row = tk.Frame(self.free_training_route_host, bd=0, highlightthickness=0)
        self.free_training_route_cards_row.pack(fill=tk.X)
        self.free_training_route_cards_row.grid_columnconfigure(0, weight=1)
        self.free_training_route_cards_row.grid_columnconfigure(1, weight=1)

        route_specs = (
            (
                "plate",
                "Tablice",
                "YOLO Pose",
                "Trening tablic z keypointami i geometrią rogów.",
                "Oczekiwany dataset: export z Z2",
            ),
            (
                "char",
                "Znaki tablic",
                "YOLO Detect",
                "Trening boxów znaków na wyciętych tablicach.",
                "Oczekiwany dataset: gold pack z Z3/PZ3",
            ),
        )
        self._free_training_route_cards = {}
        for column, (mode, title_text, badge_text, desc_text, meta_text) in enumerate(route_specs):
            card = tk.Frame(self.free_training_route_cards_row, bd=0, highlightthickness=1, padx=14, pady=12)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6 if column == 0 else 0))

            title = tk.Label(card, text=title_text, font=("Segoe UI Semibold", 11), anchor="w", bd=0, highlightthickness=0)
            title.pack(anchor=tk.W)
            badge = tk.Label(card, text=badge_text, font=("Segoe UI", 8, "bold"), padx=8, pady=2, bd=0, highlightthickness=1)
            badge.pack(anchor=tk.W, pady=(8, 8))
            desc = tk.Label(card, text=desc_text, justify=tk.LEFT, anchor="w", wraplength=140, bd=0, highlightthickness=0)
            desc.pack(anchor=tk.W, fill=tk.X)
            meta = tk.Label(card, text=meta_text, justify=tk.LEFT, anchor="w", wraplength=140, bd=0, highlightthickness=0)
            meta.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))
            self._register_train_left_wrap_target(desc, container=card, padding=30, min_wrap=120)
            self._register_train_left_wrap_target(meta, container=card, padding=30, min_wrap=120)

            for widget in (card, title, badge, desc, meta):
                self._bind_training_route_card(widget, mode)

            self._free_training_route_cards[mode] = {
                "frame": card,
                "title": title,
                "badge": badge,
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

        self.train_dataset_title_lbl = SectionHeaderLabel(settings_col, self.app, text="Dataset treningowy")
        self.train_dataset_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.train_dataset_caption_lbl = ttk.Label(
            settings_col,
            text=(
                "Wskaż gotowy folder datasetu z plikiem data.yaml. "
                "Dataset powstaje wczesniej w Z2 albo Z3/PZ3, a tutaj tylko go wybierasz do treningu."
            ),
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=360
        )
        self.train_dataset_caption_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 6))
        self._register_train_left_wrap_target(self.train_dataset_caption_lbl, padding=16, min_wrap=220)
        self.dataset_var = tk.StringVar()
        ds_row = ttk.Frame(settings_col, style="Panel.TFrame")
        ds_row.pack(fill=tk.X, pady=2)
        ttk.Entry(ds_row, textvariable=self.dataset_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(ds_row, text="Wybierz", command=self._pick_training_dataset_dir).pack(side=tk.LEFT, padx=(8, 0))

        self.train_dataset_hint_lbl = ttk.Label(
            settings_col,
            text="",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=320
        )
        self.train_dataset_hint_lbl.pack(
            anchor=tk.W,
            fill=tk.X,
            pady=(4, 8),
        )
        self._register_train_left_wrap_target(
            self.train_dataset_hint_lbl,
            padding=16,
            min_wrap=220,
        )
        self.train_dataset_hint_lbl.bind("<Configure>", self._update_training_dataset_hint_wraplength, add="+")

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

        self.train_base_title_lbl = SectionHeaderLabel(settings_col, self.app, text="Model bazowy (.pt)")
        self.train_base_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.train_base_caption_lbl = ttk.Label(
            settings_col,
            text=(
                "Dla tablic wybieraj modele YOLO Pose. "
                "Dla znaków tablic wybieraj modele YOLO Detect. "
                "Możesz też wskazać własny checkpoint .pt do fine tuningu."
            ),
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
        self.base_model_var.trace_add("write", lambda *args: self._refresh_training_start_state())
        self.base_custom_var.trace_add("write", lambda *args: self._refresh_training_start_state())
        self._refresh_base_model_choices()
        auto_name() # Inicjalizacja pierwszego wpisu        
        
        self._build_train_left_separator(settings_col, pady=(self._train_left_section_gap, self._train_left_section_gap))

        self.train_params_title_lbl = SectionHeaderLabel(settings_col, self.app, text="Parametry treningu YOLO")
        self.train_params_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.train_params_caption_lbl = None

        grid = ttk.Frame(settings_col, style="Panel.TFrame")
        grid.pack(fill=tk.X, pady=(0, 10))
        grid.columnconfigure(0, weight=0)
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="Epoki:", style="Panel.TLabel").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.epochs_var = tk.IntVar(value=100)
        ttk.Spinbox(grid, from_=1, to=5000, textvariable=self.epochs_var, width=8).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Batch Size:", style="Panel.TLabel").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.batch_var = tk.IntVar(value=16)
        ttk.Spinbox(grid, from_=1, to=256, textvariable=self.batch_var, width=8).grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Rozdzielczość (px):", style="Panel.TLabel").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.imgsz_var = tk.IntVar(value=640)
        imgsz_spin = ttk.Spinbox(grid, from_=32, to=2048, increment=32, textvariable=self.imgsz_var, width=8)
        imgsz_spin.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Learning Rate (lr0):", style="Panel.TLabel").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.lr0_var = tk.DoubleVar(value=0.01)
        lr0_spin = ttk.Spinbox(grid, from_=0.0001, to=0.1, increment=0.001, format="%.4f", textvariable=self.lr0_var, width=8)
        lr0_spin.grid(row=3, column=1, sticky=tk.W, padx=5)

        self.train_recommendation_action_row = ttk.Frame(settings_col, style="Panel.TFrame")
        self.train_recommendation_action_row.pack(fill=tk.X, pady=(0, 4))
        self.btn_apply_training_recommendation = ttk.Button(
            self.train_recommendation_action_row,
            text="Ustaw zalecane",
            command=self._apply_training_device_recommendation,
            width=18,
        )
        self.btn_apply_training_recommendation.pack(side=tk.RIGHT)

        self.train_recommendation_table_shell = tk.Frame(settings_col, bd=0, highlightthickness=1)
        self.train_recommendation_table_shell.pack(fill=tk.X, pady=(0, 8))
        self.train_recommendation_grid = tk.Frame(self.train_recommendation_table_shell, bd=0, highlightthickness=0)
        self.train_recommendation_grid.pack(fill=tk.X, padx=1, pady=1)
        self.train_recommendation_grid.grid_columnconfigure(0, weight=1)
        self.train_recommendation_grid.grid_columnconfigure(1, weight=0)
        self.train_recommendation_grid.grid_columnconfigure(2, weight=0)
        header_specs = (
            ("Parametr", tk.W),
            ("Teraz", tk.CENTER),
            ("Zalecane", tk.CENTER),
        )
        self.train_recommendation_title_label = tk.Label(
            self.train_recommendation_grid,
            text="Ustawienia",
            font=("Segoe UI", 8, "bold"),
            anchor=tk.W,
            justify=tk.LEFT,
            bd=0,
            padx=6,
            pady=4,
        )
        self.train_recommendation_title_label.grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="ew",
            padx=(0, 1),
            pady=(0, 1),
        )
        self.train_recommendation_hardware_label = tk.Label(
            self.train_recommendation_grid,
            text="Sprzet wykryty: -",
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
            label.grid(row=2, column=column, sticky="ew", padx=(0, 1), pady=(0, 1))
            self._train_recommendation_header_labels.append(label)

        self._train_recommendation_cells = []
        for row_index in range(4):
            row_cells = []
            for column in range(3):
                anchor = tk.W if column == 0 else tk.CENTER
                label = tk.Label(
                    self.train_recommendation_grid,
                    text="-",
                    font=("Segoe UI", 8),
                    anchor=anchor,
                    justify=tk.LEFT,
                    bd=0,
                    padx=6,
                    pady=2,
                )
                label.grid(
                    row=row_index + 3,
                    column=column,
                    sticky="ew",
                    padx=(0, 1),
                    pady=(0, 1),
                )
                row_cells.append(label)
            self._train_recommendation_cells.append(row_cells)
        self.train_recommendation_tree = None
        self.train_recommendation_note_var = tk.StringVar(value="Zmniejszaj po kolei: 2 -> 3 -> 4.")
        self.train_recommendation_note_lbl = ttk.Label(
            settings_col,
            textvariable=self.train_recommendation_note_var,
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
        )
        self.train_recommendation_note_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 12))
        self.epochs_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.batch_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.imgsz_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
        self.lr0_var.trace_add("write", lambda *args: self._refresh_training_recommendation_table())
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
        
        self.btn_stop_train = ttk.Button(
            self.btn_step4_start_train_frame,
            text="Zatrzymaj",
            command=self._stop_training,
            state=tk.DISABLED,
            width=14,
        )
        self.btn_stop_train.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.train_epoch_progress_var = tk.DoubleVar(value=0.0)
        self.train_progress_var = tk.DoubleVar(value=0.0)
        self.train_progress_shell = tk.Frame(
            settings_col,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
        )
        self.train_progress_shell.pack(fill=tk.X, pady=(10, 0))

        self.train_epoch_progress = TrainProgressBar(
            self.train_progress_shell,
            variable=self.train_epoch_progress_var,
            maximum=100,
            thickness=4,
            trough_color=palette.get("surface_info", palette.get("panel_alt", palette.get("panel", "#252526"))),
            fill_color=palette.get("guide", palette.get("warning", "#f0b44c")),
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            height=8,
        )
        self.train_epoch_progress.pack(fill=tk.X, pady=(0, 3))

        self.train_progress = TrainProgressBar(
            self.train_progress_shell,
            variable=self.train_progress_var,
            maximum=100,
            thickness=4,
            trough_color=palette.get("surface_info", palette.get("panel_alt", palette.get("panel", "#252526"))),
            fill_color=palette.get("success", "#2ecc71"),
            bg=palette.get("panel", palette.get("bg", "#1f1f1f")),
            height=8,
        )
        self.train_progress.pack(fill=tk.X)
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

        hist_top = ttk.Frame(self.hist_tab, padding=(10, 0, 8, 0), style="Panel.TFrame")
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

        hist_tree_shell = ttk.LabelFrame(hist_top, text=" Historia runow ", padding=8)
        hist_tree_shell.pack(fill=tk.BOTH, expand=True)
        columns = ("ID", "Nazwa", "Status", "Epoki", "Best mAP50-95", "Czas")
        self.tree = ttk.Treeview(hist_tree_shell, columns=columns, show="headings", height=10)
        for c in columns:
            self.tree.heading(c, text=c)
        self.tree.column("ID", width=130, stretch=False)
        self.tree.column("Nazwa", width=220, stretch=True)
        self.tree.column("Status", width=100, stretch=False)
        self.tree.column("Epoki", width=80, stretch=False)
        self.tree.column("Best mAP50-95", width=120, stretch=False, anchor=tk.CENTER)
        self.tree.column("Czas", width=100, stretch=False)

        yscroll = WebSlimScrollbar(hist_tree_shell, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_run_selected)
        self.tree.bind("<Double-1>", self._open_selected_run_analysis, add="+")
        self.tree.bind("<Button-3>", self._show_history_context_menu, add="+")
        self.history_context_menu = tk.Menu(self.tree, tearoff=0)
        self.history_context_menu.add_command(label="Otwórz folder", command=self._open_run_folder)
        self.history_context_menu.add_command(label="Usun", command=self._delete_selected)

        hist_details = ttk.Frame(hist_top, style="Panel.TFrame")
        hist_details.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        hist_details.columnconfigure(0, weight=1)
        hist_details.columnconfigure(1, weight=1)
        hist_details.rowconfigure(0, weight=1)

        hist_detail_box = ttk.Frame(hist_details, style="Panel.TFrame")
        hist_detail_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(
            hist_detail_box,
            text="Konfiguracja runu",
            style="Panel.TLabel",
            anchor=tk.W,
            padding=(8, 4),
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
        hist_metric_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(
            hist_metric_box,
            text="Wyniki modelu",
            style="Panel.TLabel",
            anchor=tk.W,
            padding=(8, 4),
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
        self.btn_step4_train_back.pack(side=tk.LEFT)
        self.btn_step4_train_back.configure(text="Wstecz do toru", padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self.btn_step4_finish_frame = tk.Frame(self.step4_train_nav, bd=0, highlightthickness=0)
        self.btn_step4_finish_frame.pack(side=tk.RIGHT)

        self.btn_step4_finish_pulse_frame = tk.Frame(
            self.btn_step4_finish_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_finish_pulse_frame.pack(anchor=tk.E)

        self.btn_step4_complete_project = ttk.Button(
            self.btn_step4_finish_pulse_frame,
            text="Zakończ projekt",
            command=self._complete_campaign_project,
            style="WorkflowCard.TButton",
            state=tk.DISABLED
        )
        self.btn_step4_complete_project.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_step4_complete_project.configure(padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self.btn_step4_finish = ttk.Button(
            self.btn_step4_finish_pulse_frame,
            text="Zakończ etap iteracji i wróć do kampanii",
            command=self._finish_campaign_step4,
            style="Accent.TButton",
            state=tk.DISABLED
        )
        self.btn_step4_finish.pack(side=tk.LEFT)
        self.btn_step4_finish.configure(text="Zakończ etap iteracji", padding=(8, 2), width=NAV_BUTTON_WIDTH)

        self._refresh_step4_campaign_navigation_ui()

        HELP.bind_help(ds_row, "tr_train_ds")
        HELP.bind_help(self.train_dataset_hint_lbl, "tr_train_ds")
        HELP.bind_help(self.base_combo, "tr_train_base")
        HELP.bind_help(grid, "tr_train_params")
        HELP.bind_help(self.train_device_hint_lbl, "tr_train_device")
        
        try:
            HELP.bind_help(grid.grid_slaves(row=0, column=1)[0], "tr_train_ep") 
            HELP.bind_help(grid.grid_slaves(row=1, column=1)[0], "tr_train_bs") 
            HELP.bind_help(imgsz_spin, "tr_train_imgsz")
            HELP.bind_help(lr0_spin, "tr_train_lr0") 
        except Exception as e: 
            logger.debug(f"Błąd podpinania pomocy do siatki: {e}")
        
        HELP.bind_help(self.btn_start_train, "tr_train_btn")
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
        self.frame.bind_all("<MouseWheel>", self._on_train_left_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_train_left_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_train_left_global_mousewheel, add="+")

    def _build_plots_ui(self):
        palette = getattr(self.app, "palette", {})
        self.plots_pane = ttk.PanedWindow(self.plots_tab, orient=tk.HORIZONTAL)
        self.plots_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(self.plots_pane, style="Panel.TFrame")
        right = ttk.Frame(self.plots_pane, style="Panel.TFrame")
        self.plots_pane.add(left, weight=1)
        self.plots_pane.add(right, weight=4) # Poszerzamy pole na wykres

        # Lista obrazów
        self.plots_list = tk.Listbox(left, height=12, font=("Consolas", 10), selectbackground="#3498db")
        self.plots_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.plots_list.bind("<<ListboxSelect>>", self._on_plot_selected)

        canvas_frame = ttk.Frame(right, style="Panel.TFrame")
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        # Inicjalizujemy ZoomableCanvas (ten sam co w przeglądarce tablic)
        self.plot_canvas = ZoomableCanvas(
            canvas_frame,
            bg=palette.get("panel", "#252526"),
            highlightthickness=0,
        )
        self.plot_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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
            text="Wyniki walidacji pojawią się w Terminalu procesu.",
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
            value="Po uruchomieniu walidacji najwazniejsze metryki pojawia się tutaj."
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

    def _extract_validation_metric_rows(self, metrics) -> list[tuple[str, str]]:
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
            return [
                (
                    self._format_validation_metric_name(key),
                    self._format_validation_metric_value(results_dict.get(key)),
                )
                for key in ordered_keys
            ]

        rows: list[tuple[str, str]] = []
        if hasattr(metrics, "box"):
            rows.extend(
                [
                    ("mAP50 (boxy)", self._format_validation_metric_value(getattr(metrics.box, "map50", 0))),
                    ("mAP50-95 (boxy)", self._format_validation_metric_value(getattr(metrics.box, "map", 0))),
                    ("Precision (boxy)", self._format_validation_metric_value(getattr(metrics.box, "mp", 0))),
                    ("Recall (boxy)", self._format_validation_metric_value(getattr(metrics.box, "mr", 0))),
                ]
            )
        if hasattr(metrics, "pose"):
            rows.extend(
                [
                    ("mAP50 (punkty)", self._format_validation_metric_value(getattr(metrics.pose, "map50", 0))),
                    ("mAP50-95 (punkty)", self._format_validation_metric_value(getattr(metrics.pose, "map", 0))),
                ]
            )
        return rows

    def _set_validation_summary(self, title: str, rows: list[tuple[str, str]] | None = None):
        title_var = getattr(self, "val_summary_title_var", None)
        if title_var is not None:
            try:
                title_var.set(str(title))
            except Exception:
                pass

        tree = getattr(self, "val_metrics_tree", None)
        if tree is None:
            return

        try:
            tree.delete(*tree.get_children())
        except Exception:
            pass

        for metric_name, metric_value in rows or []:
            try:
                tree.insert("", tk.END, values=(metric_name, metric_value))
            except Exception:
                continue

    def _build_validation_panel_v2(self, parent):
        shell = ttk.Frame(parent, padding=10, style="Panel.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            shell,
            text=(
                "Walidacja służy do szybkiego sprawdzenia już wytrenowanego modelu na wybranym splicie. "
                "Po uruchomieniu dostajesz czytelna tabele metryk, a pełny log nadal trafia do wspolnego terminala procesu."
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
            text="Uruchom walidacje",
            style="Accent.TButton",
            command=self._run_validation,
        )
        self.btn_run_val.pack(side=tk.LEFT)
        self.val_status = ttk.Label(action_row, text="Gotowy", style="PanelMuted.TLabel")
        self.val_status.pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(
            form_box,
            text="Walidacja korzysta z globalnego ustawienia urzadzenia i nie wymaga dodatkowego wyboru w Z4.",
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
            value="Po uruchomieniu walidacji najwazniejsze metryki pojawia się tutaj."
        )
        self.val_summary_note_var = tk.StringVar(
            value="Tabela pokazuje wynik i jego orientacyjna ocene, zeby latwiej bylo porównać modele."
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
            "Po uruchomieniu walidacji najwazniejsze metryki pojawia się tutaj.",
            [],
            "Tabela pokazuje wynik i jego orientacyjna ocene, zeby latwiej bylo porównać modele.",
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

        return sorted(candidates, key=sort_key)

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

    def _build_plots_ui(self):
        return None

    def _build_ranking_panel(self, parent):
        palette = getattr(self.app, "palette", {})
        ttk.Label(
            parent,
            text="Porownuj wytrenowane modele wzgledem zapisanych poprawek z annotations.xml.",
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

        self.btn_run_rank = ttk.Button(left_f, text="🏆 URUCHOM RANKING", style="Accent.TButton", command=self._run_ranking)
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
            text="Porownaj modele",
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
                    f"Urzadzenie rankingu: {selected_device_display} -> {effective_device_desc} | backend Ultralytics: {device}"
                )
                self._set_ranking_ui_state(
                    status=f"Porownywanie modeli... 0/{total_models}",
                    status_color="gray",
                    button_text="Porownywanie...",
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
                            self.rank_status.config(text=f"Ladowanie {m} ({current}/{total})")
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
                        f"{idx + 1}/{total_models} | Model zaladowany po {time.perf_counter() - model_started_at:.1f}s. "
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
                    self._touch_ranking_watchdog(f"{model_path.name}: eksport i porownanie wyników")
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
                        f"Zakonczono {model_path.name} | Precision={precision:.1f}% | "
                        f"Recall={recall:.1f}% | F1={f1_score:.1f}% | czas: {time.perf_counter() - model_started_at:.1f}s"
                    )

                    if temp_xml_path.exists():
                        temp_xml_path.unlink()

                try:
                    self._touch_ranking_watchdog("zapisywanie wyników rankingu")
                    self.ranking_engine.flush()
                except Exception as save_error:
                    self._append_ranking_log(f"Ostrzezenie: nie udało się zapisac rankingu: {save_error}")
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
                self._set_ranking_ui_state(button_text="Porownaj modele", cancel_enabled=False, preparing=False)
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
        if p: var.set(p)
        
    def _pick_dir(self, var, initialdir=None):
        kwargs = {}
        if initialdir and Path(initialdir).exists():
            kwargs["initialdir"] = str(initialdir)
            
        p = filedialog.askdirectory(**kwargs)
        if p: var.set(p)

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

    def _on_base_model_change(self):
        if self.base_model_var.get() == "Custom":
            self.base_custom_entry.configure(state=tk.NORMAL)
            if hasattr(self, 'base_custom_btn'):
                self.base_custom_btn.configure(state=tk.NORMAL)
        else:
            self.base_custom_entry.configure(state=tk.DISABLED)
            if hasattr(self, 'base_custom_btn'):
                self.base_custom_btn.configure(state=tk.DISABLED)
        try:
            self._refresh_training_start_state()
        except Exception:
            pass

    def _create_dataset_thread(self):
        xml = Path(self.cvat_xml_var.get().strip())
        images_dir = Path(self.cvat_images_var.get().strip())

        if not xml.exists():
            return messagebox.showerror("Błąd", "XML nie istnieje.")
        if not images_dir.exists():
            return messagebox.showerror("Błąd", "Folder obrazów nie istnieje.")

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
            return messagebox.showerror("Błąd", msg)

        train = float(self.train_pct.get()) / 100.0
        val = float(self.val_pct.get()) / 100.0
        ratios = {
            "train": train,
            "val": val,
            "test": max(0.0, 1.0 - train - val)
        }

        if not self._begin_step4_operation("z4.dataset.build", "Z4: budowa datasetu"):
            return
        self.dataset_build_is_running = True

        self.ds_progress_var.set(0)
        self.ds_status.configure(text="Rozpoczynam budowę datasetu...", foreground="black")

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
                    self._ui(lambda: self.ds_status.configure(
                        text=f"{c}/{t} obrazów...",
                        foreground="black"
                    ))

                ok2, msg2, _ = self.creator.create_dataset(images_dir, out_dir, ratios, prog)

                if ok2:
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
                            images_dir,
                            self._get_manual_plate_stage_dir(),
                        )
                        stage_result["ok"] = bool(stage_ok)
                        stage_result["message"] = str(stage_msg or "").strip()
                        if isinstance(stage_stats, dict):
                            stage_result["pending_count"] = int(stage_stats.get("pending_count", 0) or 0)
                            stage_result["stage_images_total"] = int(stage_stats.get("stage_images_total", 0) or 0)
                            stage_result["stage_images_dir"] = str(stage_stats.get("stage_images_dir") or "").strip()
                    self._ui(lambda: self.ds_status.configure(
                        text="Dataset został utworzony!",
                        foreground="green"
                    ))
                    self._ui(lambda: messagebox.showinfo("Sukces", msg2))
                    if stage_result["enabled"] and stage_result["ok"] and stage_result["stage_images_dir"]:
                        self._ui(
                            lambda info=dict(stage_result): messagebox.showinfo(
                                "Stage oczekujacych",
                                (
                                    f"Do stage oczekujacych trafiło {int(info.get('pending_count', 0) or 0)} nieoznaczonych zdjęć.\n\n"
                                    f"Stage zawiera teraz lacznie {int(info.get('stage_images_total', 0) or 0)} obrazów.\n"
                                    f"{info.get('stage_images_dir')}\n\n"
                                    "Ten folder możesz wykorzystać później jako kolejną pulę do ręcznej anotacji."
                                ),
                            )
                        )
                    elif stage_result["enabled"] and (not stage_result["ok"]) and stage_result["message"]:
                        self._ui(lambda warn=str(stage_result["message"]): messagebox.showwarning("Stage oczekujacych", warn))

                    # Po sukcesie od razu podstaw dataset do sekcji treningu.
                    self._ui(lambda p=str(out_dir): self._mark_step4_dataset_ready(p))
                else:
                    self._ui(lambda: self.ds_status.configure(
                        text="Błąd budowy datasetu",
                        foreground="red"
                    ))
                    self._ui(lambda: messagebox.showerror("Błąd", msg2))

            except Exception as e:
                self._ui(lambda: self.ds_status.configure(
                    text="Krytyczny błąd budowy datasetu",
                    foreground="red"
                ))
                self._ui(lambda err=str(e): messagebox.showerror("Krytyczny Błąd", err))

            finally:
                self.dataset_build_is_running = False
                self._end_step4_operation("z4.dataset.build")
                self._ui(self._refresh_training_start_state)

        threading.Thread(target=worker, daemon=True).start()

    def _split_dataset_thread(self):
        src = Path(self.split_src_var.get().strip())

        if not src.exists() or not (src / "images").exists():
            return messagebox.showerror(
                "Błąd",
                "Brak folderu wejściowego (lub brakuje w nim folderu 'images')."
            )

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

        if not self._begin_step4_operation("z4.dataset.split", "Z4: dzielenie datasetu"):
            return
        self.dataset_split_is_running = True

        self.split_progress_var.set(0)
        self.split_status.config(text="Rozpoczynam podział...", foreground="black")

        def worker():
            try:
                def prog(c, t, n):
                    pct = (c / t) * 100 if t > 0 else 0
                    self._ui(lambda: self.split_progress_var.set(pct))
                    self._ui(lambda: self.split_status.configure(
                        text=f"Kopiowanie {c}/{t}...",
                        foreground="black"
                    ))

                ok, msg, _ = self.splitter.split_dataset(src, out, ratios, prog)

                if ok:
                    self._ui(lambda: self.split_status.configure(
                        text="Podział zakończony!",
                        foreground="green"
                    ))
                    self._ui(lambda: messagebox.showinfo("Sukces", msg))

                    # Po sukcesie od razu podstaw dataset do sekcji treningu.
                    self._ui(lambda p=str(out): self._mark_step4_dataset_ready(p))
                else:
                    self._ui(lambda: self.split_status.configure(
                        text="Błąd podziału",
                        foreground="red"
                    ))
                    self._ui(lambda: messagebox.showerror("Błąd", msg))

            except Exception as e:
                self._ui(lambda: self.split_status.configure(
                    text="Krytyczny błąd podziału",
                    foreground="red"
                ))
                self._ui(lambda err=str(e): messagebox.showerror("Krytyczny Błąd", err))

            finally:
                self.dataset_split_is_running = False
                self._end_step4_operation("z4.dataset.split")
                self._ui(self._refresh_training_start_state)

        threading.Thread(target=worker, daemon=True).start()

    def _start_training(self):
        if not YOLO_AVAILABLE:
            return messagebox.showerror("Błąd", "Brak ultralytics.")

        try:
            self._clear_step4_guidance()
        except Exception:
            pass
        
        self._set_step4_process_console_text("Uruchamianie treningu...\n")
        self._latest_training_metrics = {}
        self._set_training_metric_interpretation("Interpretacja pojawi się po pierwszej zakończonej epoce.")

        ds = self.dataset_var.get().strip()
        if not ds:
            return messagebox.showerror("Błąd", "Podaj Dataset.")

        ds_path = Path(ds)
        yaml_path = ds_path / "data.yaml" if ds_path.is_dir() else ds_path
        if not yaml_path.exists():
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
                text="Ostrzezenie: dataset YOLO Pose jest maly. Trening ruszy po potwierdzeniu.",
                foreground="#d35400"
            )
            messagebox.showwarning(
                "Maly dataset YOLO Pose",
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
                        "Zmien karte wyboru toru albo wskaż dataset zgodny z tym wyborem."
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
        device = self._device_to_ultralytics(self.device_var.get())

        # Rozpoznaj, czy wybrany model jest modelem pose.
        is_pose_model = False
        if base_key in AVAILABLE_POSE_MODELS:
            is_pose_model = True
        elif "pose" in str(base_model).lower():
            is_pose_model = True

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

        self._append_train_log("=" * 70)
        self._append_train_log(f"START TRENINGU | Nazwa: {self.name_var.get()}")
        self._append_train_log(f"Dataset: {ds}")
        self._append_train_log(f"Model bazowy: {base_model}")
        self._append_train_log(
            f"Urzadzenie: {selected_device_display} -> {effective_device_desc} | backend Ultralytics: {device}"
        )
        self._append_train_log(
            f"Epoki: {self.epochs_var.get()} | Batch: {self.batch_var.get()} | ImgSz: {self.imgsz_var.get()} | lr0: {self.lr0_var.get()}"
        )
        self._append_train_log("=" * 70)

        if not self._begin_step4_operation("z4.training.run", "Z4: trening modelu"):
            return

        try:
            run_id = self.trainer.start_training(
                name=self.name_var.get(),
                dataset_path=ds,
                base_model=base_model,
                epochs=int(self.epochs_var.get()),
                batch_size=int(self.batch_var.get()),
                img_size=int(self.imgsz_var.get()),
                device=device,
                lr0=float(self.lr0_var.get())
            )
        except Exception as e:
            self._end_step4_operation("z4.training.run")
            logger.exception("Nie udało się wystartować treningu")
            return messagebox.showerror("Błąd", f"Nie udało się uruchomic treningu:\n{e}")

        if not run_id:
            self._end_step4_operation("z4.training.run")
            self._pending_campaign_model_type = None
            self._set_train_progress_values(overall=0.0, epoch=0.0)
            self.train_progress_label.configure(
                text="Nie udało się uruchomić treningu.",
                foreground="#c0392b"
            )
            self._append_train_log("[START] Trening nie wystartowal. Sprawdz dataset, model bazowy i log powyzej.")
            return messagebox.showerror(
                "Nie udało się uruchomić treningu",
                "Trening nie wystartował.\n\nSprawdź poprawność datasetu, modelu bazowego i log w terminalu procesu."
            )

        self.current_run_id = run_id
        self._last_training_completion_summary_run_id = None
        try:
            self._remember_campaign_plate_training_source(dataset_root)
        except Exception as e:
            logger.debug(f"Nie udało się zapamietac źródła treningu tablic: {e}")
        self._step4_campaign_finish_ready = False
        try:
            if CAMPAIGN.get_active_project_name():
                CAMPAIGN.set_step4_finish_state(False)
        except Exception:
            pass
        self._set_train_progress_values(overall=0.0, epoch=0.0)
        self._set_train_live_metrics(None)
        self.btn_start_train.configure(state=tk.DISABLED)
        self.btn_stop_train.configure(state=tk.NORMAL)
        self.train_progress_label.configure(text=f"Run treningu uruchomiony: {run_id}")

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

    def _stop_training(self):
        self.trainer.stop_training()
        self.btn_stop_train.configure(state=tk.DISABLED)
        self.train_progress_label.configure(
            text="Zatrzymywanie treningu...",
            foreground="#c0392b"
        )

    def _bind_trainer_callbacks(self):
        def on_batch_progress(epoch, batch_idx, total_batches, batch_pct):
            run = self.trainer.current_run
            if not run:
                return

            overall_pct = (((max(1, int(epoch)) - 1) + (float(batch_pct) / 100.0)) / max(1, int(run.epochs))) * 100.0
            if int(batch_idx) > 0 and int(total_batches) > 0:
                status_text = f"Trwa trening: Epoka {epoch}/{run.epochs} | batch {batch_idx}/{total_batches}"
            else:
                status_text = f"Trwa trening: Epoka {epoch}/{run.epochs} | przygotowanie batchy"

            def update_ui():
                self._set_train_progress_values(overall=overall_pct, epoch=batch_pct)
                self.train_progress_label.configure(text=status_text)

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
                self.train_progress_label.configure(text=f"Trwa trening: Zakonczono epoke {epoch}/{run.epochs}")
                self._set_training_metric_interpretation(interpretation)
                self._set_train_live_metrics(metrics)
                self._append_training_metric_table_to_global(epoch, run.epochs, metrics)
                
                # Bezpieczne wpisywanie do konsoli
                self.train_log_console.config(state=tk.NORMAL)
                self.train_log_console.insert(tk.END, log_line)
                self.train_log_console.insert(tk.END, f"{interpretation}\n")
                self.train_log_console.see(tk.END)
                self.train_log_console.config(state=tk.DISABLED)
                
            self._ui(update_ui)

        def on_end(success, msg):
            end_line = f"[KONIEC] {'SUKCES' if success else 'BŁĄD/STOP'} | {msg}"
            self._append_train_log(end_line)
            final_interpretation = self._build_training_metric_interpretation(getattr(self, "_latest_training_metrics", {}))
            if getattr(self, "_latest_training_metrics", {}):
                self._append_train_log(f"[OCENA] {final_interpretation}")
            self._end_step4_operation("z4.training.run")

            self._ui(lambda: self.btn_start_train.configure(state=tk.NORMAL))
            self._ui(lambda: self.btn_stop_train.configure(state=tk.DISABLED))
            if success:
                self._ui(lambda: self._set_train_progress_values(overall=100.0, epoch=100.0))
            self._ui(lambda: self._set_training_metric_interpretation(final_interpretation))
            self._ui(lambda: self._set_train_live_metrics(getattr(self, "_latest_training_metrics", {})))
            self._ui(lambda: self.train_progress_label.configure(
                text="Trening zakończony." if success else "Trening zatrzymany / zakończony błędem.",
                foreground="#2c3e50" if success else "#c0392b"
            ))
            self._ui(lambda: self._load_history())
            self._ui(self._refresh_training_start_state)

        self.trainer.on_batch_progress = on_batch_progress
        self.trainer.on_epoch_end = on_epoch
        self.trainer.on_training_end = on_end


    def _load_history(self):
        selected_run = self._selected_run()
        selected_run_id = getattr(selected_run, "id", None)
        self.tree.delete(*self.tree.get_children())
        for run in self.history.get_all_runs():
            # Zachowaj pełne run.id, aby wybór historii i folderów był jednoznaczny.
            best_map = getattr(run, 'best_map50_95', 0.0) or 0.0
            
            self.tree.insert("", tk.END, values=(
                str(run.id), 
                str(run.name)[:30], 
                str(run.status), 
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
                if values and str(values[0]) == str(selected_run_id):
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

    def _on_run_selected_legacy(self, event=None):
        run = self._selected_run()
        self._set_history_run_tables(run)
        if not run:
            return

        self._autofill_validation_inputs_from_run(run)
        
        run_dir = Path(run.output_dir)
        if not run_dir.exists(): return
            
        # Wczytaj artefakty analityczne wygenerowane przez Ultralytics.
        paths = list(run_dir.rglob("*.png")) + list(run_dir.rglob("*.jpg"))
        
        # Zachowaj tylko obrazy przydatne w analizie treningu.
        self._plots_paths = [p for p in paths if "plot" in p.name.lower() or "confusion" in p.name.lower() or "val" in p.name.lower()]
        
        # Odśwież listę artefaktów widocznych w panelu analizy.
        self.plots_list.delete(0, tk.END)
        for p in self._plots_paths: 
            self.plots_list.insert(tk.END, p.name)

    def _on_plot_selected(self, event=None):
        sel = self.plots_list.curselection()
        if sel and self._plots_paths: self._show_plot(self._plots_paths[int(sel[0])])

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
        if not YOLO_AVAILABLE: return messagebox.showerror("Błąd", "Brak modułu YOLO!")
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
                model = YOLO(model_path)
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
                        "Tabela pokazuje najwazniejsze metryki walidacyjne i ich orientacyjna ocene.",
                    )
                )
                self._ui(lambda: messagebox.showinfo("Sukces", "Walidacja zakończona pomyślnie!"))
                
            except Exception as e:
                self._append_train_log(f"\nBŁĄD WALIDACJI:\n{e}")
                self._ui(lambda: self.val_status.config(text="Błąd walidacji", foreground="red"))
                self._ui(
                    lambda err=str(e), model_name=Path(model_path).name:
                    self._set_validation_summary(
                        f"Walidacja nie powiodla się: {model_name}",
                        [("Błąd", self._shorten_training_text(err, 72), "-", "-")],
                        err,
                    )
                )
                logger.error(f"Validation error: {e}")
                
            finally:
                self.val_is_running = False
                self._end_step4_operation("z4.validation.run")
                self._ui(lambda: self.btn_run_val.config(state=tk.NORMAL, text="Uruchom walidacje"))
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
                    self._ui(lambda m=model_path.name: self.rank_status.config(text=f"Testowanie {m} ({idx+1}/{total_models})"))
                    
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
                self._ui(lambda: self.btn_run_rank.config(state=tk.NORMAL, text="🏆 URUCHOM RANKING"))

        threading.Thread(target=worker, daemon=True).start()
