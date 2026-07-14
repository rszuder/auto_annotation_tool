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
from ..validators import validate_model_file, format_yolo_model_identity
from ..training import (
    YOLOPoseTrainer,
    TrainingHistory,
    TrainingStatus,
    DatasetCreator,
    DatasetSplitter,
    format_resource_sample_line,
)
from ..ranking import ModelRanking, format_ranking_model_label
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
    complete_campaign_step4_if_needed,
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
from .z4_view_models import (
    Step4CampaignNavigationViewModel,
    Step4DatasetWorkflowViewModel,
    Step4TrainingInputsViewModel,
)

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageFont

YOLO = None
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
    self._last_training_resource_log_at = 0.0
    try:
        self._set_training_widget_text(
            getattr(self, "train_resource_label", None),
            "Zasoby w czasie treningu",
        )
        self._set_training_resource_sample(None)
    except Exception:
        pass

    source_state = self._validate_active_training_source_for_pz2()
    if not bool(source_state.get("ok")):
        yaml_path_candidate = source_state.get("yaml_path")
        dataset_root_candidate = source_state.get("dataset_root")
        check_path = dataset_root_candidate or yaml_path_candidate
        if check_path is not None and self._looks_like_char_classification_dataset(check_path):
            return messagebox.showerror(
                "Nieobsługiwany typ datasetu",
                self._char_classification_dataset_message(),
            )
        validation_msg = str(source_state.get("message") or "Dataset niegotowy do treningu.")
        dataset_root = source_state.get("dataset_root")
        validation_stats = dict(source_state.get("stats") or {})
        if dataset_root is not None:
            validation_details = self._build_training_dataset_validation_message(
                Path(dataset_root),
                validation_msg,
                validation_stats,
            )
        else:
            validation_details = validation_msg
        self._append_train_log(f"[WALIDACJA] {validation_msg}")
        self._append_train_log(validation_details)
        self.train_progress_label.configure(
            text="Dataset wymaga poprawy przed treningiem.",
            foreground="#c0392b"
        )
        return messagebox.showerror("Dataset niegotowy do treningu", validation_details)

    yaml_path = Path(source_state["yaml_path"])
    dataset_root = Path(source_state["dataset_root"])
    validation_msg = str(source_state.get("message") or "Dataset OK")
    validation_stats = dict(source_state.get("stats") or {})
    try:
        self.dataset_var.set(str(dataset_root))
    except Exception:
        pass

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
        inferred_target = self._infer_dataset_target(str(dataset_root)) or ("plate" if is_pose_dataset else "char")
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

    dataset_path = str(dataset_root)
    base_key = self.base_model_var.get().strip()
    base_model = self.base_custom_var.get().strip() if self._is_custom_base_model_key(base_key) else base_key
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
    self._append_train_log(f"Dataset: {dataset_path}")
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
            dataset_path=dataset_path,
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
    try:
        self._set_training_widget_text(getattr(self, "train_resource_label", None), "Zasoby w czasie treningu")
        self._set_training_resource_sample(None)
    except Exception:
        pass
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
        if not success and CAMPAIGN.get_active_project_name():
            self._step4_campaign_finish_ready = False
            try:
                CAMPAIGN.set_step4_finish_state(False)
            except Exception:
                pass

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

    def on_resource_sample(sample):
        summary = str((sample or {}).get("summary_text") or format_resource_sample_line(sample or {})).strip()
        if not summary:
            return
        now = time.perf_counter()

        def update_ui():
            self._set_training_widget_text(
                getattr(self, "train_resource_label", None),
                "Zasoby w czasie treningu",
            )
            self._set_training_resource_sample(sample or {})

        self._ui(update_ui)
        if now - float(getattr(self, "_last_training_resource_log_at", 0.0) or 0.0) >= 15.0:
            self._last_training_resource_log_at = now
            self._append_train_log(f"[ZASOBY] {summary}")

    def on_resource_report(report):
        summary = str((report or {}).get("summary_text") or "").strip()
        report_path = str((report or {}).get("report_path") or "").strip()

        def update_ui():
            self._set_training_widget_text(
                getattr(self, "train_resource_label", None),
                "Raport zasobów po treningu",
            )
            self._set_training_resource_report(report or {})

        self._ui(
            update_ui
        )
        self._append_train_log(f"[RAPORT ZASOBÓW] {summary or 'zapisany'}")
        if report_path:
            self._append_train_log(f"[RAPORT ZASOBÓW] Plik: {report_path}")

    self.trainer.on_batch_progress = on_batch_progress
    self.trainer.on_epoch_end = on_epoch
    self.trainer.on_training_end = on_end
    self.trainer.on_resource_sample = on_resource_sample
    self.trainer.on_resource_report = on_resource_report

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
    if not hasattr(self, "tree"):
        return
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

    def _format_history_datetime(value: str | None, *, fallback: str = "-") -> str:
        raw = str(value or "").strip()
        if not raw:
            return fallback
        try:
            return datetime.datetime.fromisoformat(raw).strftime("%d.%m %H:%M")
        except Exception:
            return raw.replace("T", " ")[:16] or fallback

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
        run_label = run_name or str(getattr(run, "id", "") or "")
        started_short = _format_history_datetime(
            getattr(run, "started_at", None),
            fallback=_format_history_datetime(getattr(run, "created_at", None)),
        )

        self.tree.insert("", tk.END, iid=str(run.id), values=(
            target_label,
            started_short,
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
    try:
        _refresh_campaign_training_result_selector(self)
    except Exception:
        pass

def _delete_selected(self):
    run = self._selected_run()
    if run and messagebox.askyesno("Potwierdź", "Usunąć run treningu?"):
        self.history.delete_run(run.id, delete_files=True)
        self._load_history()

def _open_run_folder(self):
    run = self._selected_run()
    if run and Path(run.output_dir).exists():
        self._open_path(Path(run.output_dir))

def _campaign_training_result_target(self) -> str:
    target = str(self.get_campaign_training_target() or CAMPAIGN.get_iteration_target() or "").strip().lower()
    return target if target in {"plate", "char"} else ""

def _campaign_training_result_candidates(self) -> list:
    if not CAMPAIGN.get_active_project_name():
        return []
    try:
        self._reload_history_snapshot_from_disk()
    except Exception:
        pass
    target = _campaign_training_result_target(self)
    result = []
    try:
        runs = list(self.history.get_all_runs() or [])
    except Exception:
        runs = []
    for run in runs:
        try:
            if str(getattr(run, "status", "") or "").strip().lower() != TrainingStatus.COMPLETED.value:
                continue
            if target and not self._does_history_run_match_active_campaign_target(run):
                continue
            if self._resolve_history_run_best_weights(run) is None:
                continue
            result.append(run)
        except Exception:
            continue

    def _run_sort_key(run) -> tuple[str, str]:
        finished = str(getattr(run, "finished_at", "") or "").strip()
        created = str(getattr(run, "created_at", "") or "").strip()
        run_id = str(getattr(run, "id", "") or "").strip()
        return (finished or created or "", run_id)

    return sorted(result, key=_run_sort_key, reverse=True)

def _campaign_training_result_choice_label(self, run) -> str:
    run_id = str(getattr(run, "id", "") or "").strip() or "-"
    started = str(getattr(run, "started_at", "") or getattr(run, "created_at", "") or "").strip()
    started_short = ""
    if started:
        try:
            started_short = datetime.datetime.fromisoformat(started).strftime("%d.%m %H:%M")
        except Exception:
            started_short = started.replace("T", " ")[:16]
    try:
        score = float(getattr(run, "best_map50_95", 0.0) or 0.0)
    except Exception:
        score = 0.0
    dataset_name = Path(str(getattr(run, "dataset_path", "") or "")).name or "-"
    return f"start {started_short or run_id} | mAP50-95 {score:.3f} | {dataset_name} | {run_id}"

def _campaign_training_result_detail_text(self, run) -> str:
    if run is None:
        return ""
    try:
        target = str(self._infer_history_run_target(run) or "").strip().lower()
    except Exception:
        target = ""
    target_label = "model tablic" if target == "plate" else "model znaków" if target == "char" else "model"
    try:
        best_weights = self._resolve_history_run_best_weights(run)
    except Exception:
        best_weights = None
    try:
        score = float(getattr(run, "best_map50_95", 0.0) or 0.0)
    except Exception:
        score = 0.0
    started = str(getattr(run, "started_at", "") or getattr(run, "created_at", "") or "").strip()
    if started:
        try:
            started_text = datetime.datetime.fromisoformat(started).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            started_text = started.replace("T", " ")
    else:
        started_text = "-"
    return (
        f"{target_label} | run: {str(getattr(run, 'id', '') or '-')} | "
        f"start: {started_text} | "
        f"epoki: {getattr(run, 'current_epoch', '-')}/{getattr(run, 'epochs', '-')} | "
        f"mAP50-95: {score:.3f} | best.pt: {Path(best_weights).name if best_weights else '-'}"
    )

def _selected_campaign_training_result_run(self):
    choice_var = getattr(self, "campaign_training_result_var", None)
    try:
        choice = str(choice_var.get() or "").strip()
    except Exception:
        choice = ""
    choices = getattr(self, "_campaign_training_result_choices", {}) or {}
    run_id = str(choices.get(choice, "") or "").strip()
    if not run_id:
        return None
    try:
        self._reload_history_snapshot_from_disk()
    except Exception:
        pass
    try:
        return self.history.get_run(run_id)
    except Exception:
        return None

def _refresh_campaign_training_result_selector(self):
    selector = getattr(self, "campaign_training_result_entry", None)
    if selector is None:
        selector = getattr(self, "campaign_training_result_combo", None)
    dropdown_btn = getattr(self, "campaign_training_result_dropdown_btn", None)
    dropdown_menu = getattr(self, "campaign_training_result_menu", None)
    status_lbl = getattr(self, "campaign_training_result_status_lbl", None)
    detail_lbl = getattr(self, "campaign_training_result_detail_lbl", None)
    action_btn = getattr(self, "btn_use_campaign_training_result", None)
    if selector is None:
        return
    palette = getattr(self.app, "palette", {}) if getattr(self, "app", None) is not None else {}
    success = palette.get("success", "#2ecc71")
    warning = palette.get("warning", "#f39c12")
    muted = palette.get("muted", "#888888")
    panel = palette.get("panel", "#252526")
    fg = palette.get("fg", "#f3f3f3")

    def _set_status(text: str, tone: str) -> None:
        if status_lbl is None:
            return
        color = success if tone == "success" else warning if tone == "warning" else muted
        try:
            status_lbl.configure(
                text=text,
                bg=blend_hex_colors(color, panel, 0.78),
                fg=fg,
                highlightbackground=blend_hex_colors(color, panel, 0.35),
                highlightcolor=blend_hex_colors(color, panel, 0.35),
            )
        except Exception:
            pass

    def _set_selector_enabled(enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        try:
            selector.configure(state=state)
        except Exception:
            pass
        if dropdown_btn is not None:
            try:
                dropdown_btn.configure(state=state)
            except Exception:
                pass

    def _select_campaign_result_label(label: str) -> None:
        try:
            self.campaign_training_result_var.set(str(label or ""))
        except Exception:
            pass
        _refresh_campaign_training_result_selector(self)

    def _rebuild_campaign_result_menu(labels: list[str]) -> None:
        if dropdown_menu is None:
            try:
                selector.configure(values=tuple(labels))
            except Exception:
                pass
            return
        try:
            dropdown_menu.delete(0, tk.END)
            for label in labels:
                dropdown_menu.add_command(
                    label=str(label or ""),
                    command=lambda value=label: _select_campaign_result_label(value),
                )
        except Exception:
            pass

    def _scroll_result_selector_start() -> None:
        try:
            if selector is None or not selector.winfo_exists():
                return
            selector.icursor(0)
            selector.xview_moveto(0.0)
        except Exception:
            pass

    if not CAMPAIGN.get_active_project_name():
        _rebuild_campaign_result_menu([])
        _set_selector_enabled(False)
        if detail_lbl is not None:
            detail_lbl.configure(text="Wybór wyniku bramki T06 jest dostępny tylko w kampanii.")
        if action_btn is not None:
            action_btn.configure(state=tk.DISABLED, text="Wybierz ten model jako wynik T06")
        _set_status("POZA KAMPANIĄ", "muted")
        return

    candidates = _campaign_training_result_candidates(self)
    choices: dict[str, str] = {}
    labels: list[str] = []
    for run in candidates:
        label = _campaign_training_result_choice_label(self, run)
        base_label = label
        suffix = 2
        while label in choices:
            label = f"{base_label} ({suffix})"
            suffix += 1
        choices[label] = str(getattr(run, "id", "") or "").strip()
        labels.append(label)
    self._campaign_training_result_choices = choices
    _rebuild_campaign_result_menu(labels)
    _set_selector_enabled(bool(labels))

    try:
        finish_state = dict(self.get_campaign_step4_finish_state(iteration_target=_campaign_training_result_target(self)) or {})
    except Exception:
        try:
            finish_state = dict(CAMPAIGN.get_step4_finish_state() or {})
        except Exception:
            finish_state = {}
    finish_run_id = str(finish_state.get("run_id", "") or "").strip() if bool(finish_state.get("ready")) else ""

    try:
        selected_label = str(self.campaign_training_result_var.get() or "").strip()
    except Exception:
        selected_label = ""
    if selected_label not in choices and finish_run_id and finish_run_id in set(choices.values()):
        for label, run_id in choices.items():
            if run_id == finish_run_id:
                selected_label = label
                break
    elif selected_label not in choices and labels:
        selected_label = labels[0]
    if labels:
        try:
            self.campaign_training_result_var.set(selected_label)
        except Exception:
            pass
        try:
            selector.after_idle(_scroll_result_selector_start)
        except Exception:
            pass

    selected_run_id = str(choices.get(selected_label, "") or "").strip()
    selected_run = None
    if selected_run_id:
        try:
            selected_run = self.history.get_run(selected_run_id)
        except Exception:
            selected_run = None

    if not labels:
        if detail_lbl is not None:
            detail_lbl.configure(text="Brak ukończonych runów pasujących do aktywnego toru bramki T06.")
        if action_btn is not None:
            action_btn.configure(state=tk.DISABLED, text="Wybierz ten model jako wynik T06")
        _set_status("BRAK KANDYDATA", "warning")
        return

    detail_text = _campaign_training_result_detail_text(self, selected_run)
    if selected_run_id and selected_run_id == finish_run_id:
        if action_btn is not None:
            action_btn.configure(state=tk.DISABLED, text="Wynik T06 wybrany")
        _set_status("WYNIK WYBRANY", "success")
        if detail_text:
            detail_text = (
                f"{detail_text}\n"
                "Model jest już wskazany jako wynik T06. Wróć do grafu i zatwierdź bramkę."
            )
    else:
        if action_btn is not None:
            action_btn.configure(state=tk.NORMAL, text="Wybierz ten model jako wynik T06")
        _set_status("DO WYBORU", "warning")
        if detail_text:
            detail_text = (
                f"{detail_text}\n"
                "Jeśli to właściwy model, wybierz go jako wynik T06. To jeszcze nie zamyka bramki."
            )
    if detail_lbl is not None:
        detail_lbl.configure(text=detail_text)

def _on_campaign_training_result_choice(self, event=None):
    _refresh_campaign_training_result_selector(self)

def _use_campaign_training_result_choice(self):
    run = _selected_campaign_training_result_run(self)
    if run is None:
        return messagebox.showwarning(
            "Brak runu",
            "Najpierw wybierz kandydata na wynik treningu dla bramki T06.",
        )
    run_id = str(getattr(run, "id", "") or "").strip()
    selected_ok = False
    try:
        if hasattr(self, "tree") and run_id:
            self.tree.selection_set(run_id)
            self.tree.focus(run_id)
            self.tree.see(run_id)
            selected_ok = run_id in {str(item) for item in self.tree.selection()}
    except Exception:
        selected_ok = False
    if not selected_ok:
        return messagebox.showwarning(
            "Nie wybrano runu",
            "Nie udało się zaznaczyć wybranego runu w historii treningu. Odśwież historię i spróbuj ponownie.",
        )
    try:
        result = self._promote_selected_run_model_to_campaign()
    finally:
        try:
            _refresh_campaign_training_result_selector(self)
        except Exception:
            pass
    return result

def _promote_selected_run_model_to_campaign(self):
    run = self._selected_run()
    if run is None:
        return messagebox.showwarning(
            "Brak runu",
            "Najpierw wybierz zakończony run treningu z historii."
        )
    if not CAMPAIGN.get_active_project_name():
        return messagebox.showwarning(
            "Brak projektu",
            "Model projektu można wskazać tylko w aktywnej kampanii."
        )

    status_value = str(getattr(run, "status", "") or "").strip().lower()
    if status_value != TrainingStatus.COMPLETED.value:
        return messagebox.showwarning(
            "Run nie jest gotowy",
            "Jako model projektu można wskazać tylko trening zakończony sukcesem."
        )
    if not self._does_history_run_match_active_campaign_target(run):
        active_target = str(self.get_campaign_training_target() or CAMPAIGN.get_iteration_target() or "").strip().lower()
        active_label = "tablic" if active_target == "plate" else "znaków" if active_target == "char" else "bieżącego toru"
        return messagebox.showerror(
            "Niezgodny tor modelu",
            f"Wybrany run nie pasuje do aktywnego toru {active_label}."
        )

    target = self._infer_history_run_target(run)
    if target not in {"plate", "char"}:
        target = str(self.get_campaign_training_target() or CAMPAIGN.get_iteration_target() or "").strip().lower()
    if target not in {"plate", "char"}:
        return messagebox.showerror(
            "Nie rozpoznano toru",
            "Nie mogę ustalić, czy wybrany model dotyczy tablic czy znaków."
        )

    best_weights = self._resolve_history_run_best_weights(run)
    if best_weights is None or not Path(best_weights).exists():
        return messagebox.showerror(
            "Brak best.pt",
            "Wybrany run nie ma dostępnego pliku best.pt."
        )

    run_id = str(getattr(run, "id", "") or "").strip()
    if not run_id:
        return messagebox.showerror(
            "Brak identyfikatora runu",
            "Wybrany wpis historii nie ma identyfikatora runu."
        )

    try:
        iteration_num = int(CAMPAIGN.get_current_iteration_num() or 0)
    except Exception:
        iteration_num = 0

    CAMPAIGN.set_global_model(target, str(best_weights))
    CAMPAIGN.set_step4_finish_state(
        True,
        run_id=run_id,
        target=target,
        iteration_num=iteration_num,
        selection_confirmed=True,
        model_path=str(best_weights),
    )
    self.current_run_id = run_id
    self._pending_campaign_model_type = None
    self._step4_campaign_finish_ready = True

    try:
        complete_campaign_step4_if_needed(self, target)
    except Exception:
        pass
    try:
        self._refresh_step4_campaign_navigation_ui()
    except Exception:
        pass
    try:
        campaign_tab = self.app.tabs.get("campaign")
        if campaign_tab:
            campaign_tab._refresh_dashboard()
    except Exception:
        pass

    target_label = "znaków" if target == "char" else "tablic"
    try:
        self._append_train_log(
            f"[MODEL] Jawnie wybrano model {target_label} projektu: {best_weights}"
        )
    except Exception:
        pass
    try:
        _refresh_campaign_training_result_selector(self)
    except Exception:
        pass
    return messagebox.showinfo(
        "Wynik T06 wybrany",
        (
            f"Wybrano model {target_label} jako wynik bramki T06:\n{Path(best_weights).name}\n\n"
            "To wybór artefaktu. Wróć do grafu i użyj pola Zatwierdź na bramce T06, "
            "aby formalnie zamknąć przejście."
        )
    )

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
            "Wybrany run należy do innego toru treningu niż aktualnie otwarty węzeł treningowy.\n\n"
            f"W tej chwili możesz wznowić tylko runy dla toru {active_label}."
        )

    last_weights = str(getattr(run, "last_weights", "") or "").strip()
    if not last_weights or not Path(last_weights).exists():
        try:
            fallback_last = Path(str(getattr(run, "output_dir", "") or "")) / "train" / "weights" / "last.pt"
            if fallback_last.exists():
                last_weights = str(fallback_last)
                try:
                    run.last_weights = last_weights
                    self.history.update_run(str(run.id), last_weights=last_weights)
                except Exception:
                    pass
        except Exception:
            pass
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
    promotable = False
    if selected_run is not None:
        try:
            exportable = bool(
                self._infer_history_run_target(selected_run) in {"plate", "char", "vehicle"}
                and self._resolve_history_run_best_weights(selected_run) is not None
            )
        except Exception:
            exportable = False
        try:
            promotable = bool(
                CAMPAIGN.get_active_project_name()
                and str(getattr(selected_run, "status", "") or "").strip().lower() == TrainingStatus.COMPLETED.value
                and self._infer_history_run_target(selected_run) in {"plate", "char"}
                and self._resolve_history_run_best_weights(selected_run) is not None
                and self._does_history_run_match_active_campaign_target(selected_run)
            )
        except Exception:
            promotable = False
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
        menu.entryconfigure(
            "Użyj best.pt jako model projektu",
            state=(tk.NORMAL if promotable else tk.DISABLED),
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

def _close_run_details_dialog(self):
    dialog = getattr(self, "_run_details_dialog", None)
    if dialog is None:
        return
    try:
        dialog.withdraw()
    except Exception:
        pass

def _open_current_run_details_analysis(self):
    run = None
    run_id = str(getattr(self, "_run_details_current_run_id", "") or "").strip()
    if run_id:
        try:
            run = self.history.get_run(run_id)
        except Exception:
            run = None
    if run is None:
        run = self._selected_run()
    if run is None:
        return
    return self._open_run_analysis_window(run)

def _open_current_run_details_folder(self):
    run = None
    run_id = str(getattr(self, "_run_details_current_run_id", "") or "").strip()
    if run_id:
        try:
            run = self.history.get_run(run_id)
        except Exception:
            run = None
    if run is None:
        run = self._selected_run()
    if run is None:
        return messagebox.showwarning(
            "Brak runu",
            "Najpierw wybierz run z historii treningu.",
        )
    output_dir = str(getattr(run, "output_dir", "") or "").strip()
    if not output_dir:
        return messagebox.showwarning(
            "Brak folderu",
            "Wybrany run nie ma zapisanego folderu wynikowego.",
        )
    return self._open_path(Path(output_dir))

def _open_run_details_modal(self, run):
    if run is None:
        return messagebox.showwarning(
            "Brak runu",
            "Najpierw wybierz run z historii treningu.",
        )

    run_id = str(getattr(run, "id", "") or "").strip()
    run_name = str(getattr(run, "name", "") or run_id or "run").strip()
    palette = getattr(self.app, "palette", {}) if getattr(self, "app", None) is not None else {}

    dialog = getattr(self, "_run_details_dialog", None)
    dialog_exists = False
    if dialog is not None:
        try:
            dialog_exists = bool(dialog.winfo_exists())
        except Exception:
            dialog_exists = False

    if not dialog_exists:
        dialog = tk.Toplevel(self.frame)
        dialog.title("Szczegóły runu treningowego")
        dialog.geometry("1180x760")
        dialog.minsize(980, 640)
        dialog.transient(self.frame.winfo_toplevel())
        dialog.resizable(True, True)
        dialog.protocol("WM_DELETE_WINDOW", self._close_run_details_dialog)
        self._run_details_dialog = dialog

        shell = ttk.Frame(dialog, padding=12, style="Panel.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(shell, style="Panel.TFrame")
        header.pack(fill=tk.X, pady=(0, 10))
        header.columnconfigure(0, weight=1)
        self.run_details_title_lbl = ttk.Label(
            header,
            text="Szczegóły runu",
            style="PanelTitle.TLabel",
            anchor=tk.W,
        )
        self.run_details_title_lbl.grid(row=0, column=0, sticky="ew")
        self.run_details_subtitle_lbl = ttk.Label(
            header,
            text="Konfiguracja i wyniki modelu są dostępne tutaj, a historia zostaje czysta do szybkiego wyboru.",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
        )
        self.run_details_subtitle_lbl.grid(row=1, column=0, sticky="ew", pady=(3, 0))

        body = ttk.Frame(shell, style="Panel.TFrame")
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        config_box = ttk.LabelFrame(body, text=" Konfiguracja runu ", padding=8)
        config_box.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        metric_box = ttk.LabelFrame(body, text=" Wyniki modelu ", padding=8)
        metric_box.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        self.run_details_config_tree = self._create_metric_table(
            config_box,
            [
                ("Pole", 230, tk.W),
                ("Wartość", 820, tk.W),
            ],
            height=8,
        )
        self.run_details_metric_tree = self._create_metric_table(
            metric_box,
            [
                ("Metryka", 260, tk.W),
                ("Ostatnia", 150, tk.CENTER),
                ("Najlepsza", 150, tk.CENTER),
                ("Ocena", 220, tk.CENTER),
            ],
            height=9,
        )

        actions = ttk.Frame(shell, style="Panel.TFrame")
        actions.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(
            actions,
            text="Pokaż wykresy treningu",
            command=self._open_current_run_details_analysis,
            style="WorkflowCard.TButton",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            actions,
            text="Otwórz folder runu",
            command=self._open_current_run_details_folder,
            style="WorkflowCard.TButton",
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            actions,
            text="Zamknij",
            command=self._close_run_details_dialog,
        ).pack(side=tk.RIGHT)

    self._run_details_current_run_id = run_id
    try:
        self.run_details_title_lbl.configure(text=f"Szczegóły runu: {self._shorten_training_text(run_name, 72)}")
    except Exception:
        pass
    try:
        target_label = self._format_history_run_target_label(self._infer_history_run_target(run))
        status_label = self._format_history_run_status_label(run)
        self.run_details_subtitle_lbl.configure(text=f"{target_label} | {status_label}")
    except Exception:
        pass

    self._set_metric_table_rows(
        getattr(self, "run_details_config_tree", None),
        self._build_training_run_detail_rows(run),
    )
    self._set_metric_table_rows(
        getattr(self, "run_details_metric_tree", None),
        self._build_training_run_metric_rows(run),
    )

    try:
        dialog.title(f"Szczegóły runu | {self._shorten_training_text(run_name, 48)}")
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
    except Exception:
        pass

def _open_selected_run_details(self, event=None):
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
        return messagebox.showwarning(
            "Brak runu",
            "Najpierw wybierz run z historii treningu.",
        )
    return self._open_run_details_modal(run)

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
    selected_scope = str(getattr(getattr(self, "rank_scope_var", None), "get", lambda: "Wszystkie")() or "Wszystkie").strip()

    try:
        project_root = CAMPAIGN.get_active_project_root_dir()
        project_root = Path(project_root).resolve() if project_root is not None else None
    except Exception:
        project_root = None

    def normalize_path(path_like: str) -> str:
        raw = str(path_like or "").strip()
        if not raw:
            return ""
        try:
            return str(Path(raw).resolve())
        except Exception:
            return str(Path(raw))

    project_model_paths: set[str] = set()
    if CAMPAIGN.get_active_project_name():
        try:
            for candidate in self._collect_project_plate_ranking_model_candidates():
                try:
                    project_model_paths.add(str(Path(candidate).resolve()).lower())
                except Exception:
                    project_model_paths.add(str(Path(candidate)).lower())
        except Exception:
            project_model_paths = set()

    def entry_scope(entry) -> str:
        model_path_raw = str(getattr(entry, "model_path", "") or "").strip()
        if not model_path_raw:
            return "Globalne"
        try:
            model_path = Path(model_path_raw).resolve()
            model_key = str(model_path).lower()
            if model_key in project_model_paths:
                return "Projekt"
            if project_root is not None and (model_path == project_root or project_root in model_path.parents):
                return "Projekt"
        except Exception:
            pass
        return "Globalne"

    def entry_decision(entry, scope: str, index: int) -> str:
        if scope == "Projekt":
            return "Kandydat projektu" if index > 0 else "Najlepszy kandydat"
        if scope == "Globalne":
            return "Model referencyjny"
        return "Kandydat"

    def set_leader(title: str, hint: str, *, tone: str = "muted"):
        title_label = getattr(self, "rank_leader_title", None)
        hint_label = getattr(self, "rank_leader_hint", None)
        palette = getattr(getattr(self, "app", None), "palette", {}) or {}
        tone_fg = {
            "success": palette.get("success", "#2ecc71"),
            "warning": palette.get("warning", "#f0b44c"),
            "danger": palette.get("error", "#e05d5d"),
            "muted": palette.get("fg", "#f3f3f3"),
        }.get(tone, palette.get("fg", "#f3f3f3"))
        if title_label is not None:
            try:
                title_label.configure(text=title, fg=tone_fg)
            except Exception:
                pass
        if hint_label is not None:
            try:
                hint_label.configure(text=hint)
            except Exception:
                pass

    filtered_entries = [e for e in entries if getattr(e, 'task_type', '') == "Tablice (Pose)"]
    if selected_reference_raw and not selected_reference.get("ok"):
        filtered_entries = []
    elif selected_reference_path:
        filtered_entries = [
            e for e in filtered_entries
            if normalize_path(getattr(e, "reference_path", "")) == normalize_path(selected_reference_path)
        ]
    if selected_scope in {"Projekt", "Globalne"}:
        filtered_entries = [e for e in filtered_entries if entry_scope(e) == selected_scope]
    filtered_entries.sort(key=lambda x: getattr(x, 'f1_score', 0), reverse=True)

    if not filtered_entries:
        scope_hint = selected_scope.lower()
        if selected_reference_raw and not selected_reference.get("ok"):
            set_leader(
                "Brak wyników: zestaw odniesienia nie jest gotowy",
                str(selected_reference.get("message") or "Wskaż poprawny folder runu odniesienia."),
                tone="warning",
            )
        else:
            set_leader(
                f"Brak wyników dla zakresu: {selected_scope}",
                f"Uruchom ranking albo przełącz zakres. Zakres {scope_hint} nie zawiera jeszcze porównanych modeli.",
                tone="muted",
            )
        return

    best = filtered_entries[0]
    best_scope = entry_scope(best)
    best_reference = str(getattr(best, "reference_name", "") or "").strip()
    if not best_reference:
        best_reference = Path(str(getattr(best, "reference_path", "") or "-")).name or "-"
    best_model_label = format_ranking_model_label(
        getattr(best, "model_name", ""),
        getattr(best, "model_path", ""),
        getattr(best, "task_type", ""),
    )
    set_leader(
        f"Lider: {best_model_label} | F1 {float(getattr(best, 'f1_score', 0) or 0):.1f}%",
        (
            f"Zakres: {best_scope}. Zestaw odniesienia: {best_reference}. "
            "To rekomendacja rankingu, nie automatyczny wybór modelu projektowego."
        ),
        tone="success" if best_scope == "Projekt" else "warning",
    )

    for i, rep in enumerate(filtered_entries):
        reference_name = str(getattr(rep, "reference_name", "") or "").strip()
        if not reference_name:
            reference_name = Path(str(getattr(rep, "reference_path", "") or "-")).name or "-"
        scope = entry_scope(rep)
        row_tags = ("leader",) if i == 0 else ("project" if scope == "Projekt" else "global",)
        model_label = format_ranking_model_label(
            getattr(rep, "model_name", ""),
            getattr(rep, "model_path", ""),
            getattr(rep, "task_type", ""),
        )
        self.rank_tree.insert("", tk.END, values=(
            i + 1,
            scope,
            model_label,
            f"{float(getattr(rep, 'f1_score', 0) or 0):.1f}%",
            f"{float(getattr(rep, 'precision', 0) or 0):.1f}%",
            f"{float(getattr(rep, 'recall', 0) or 0):.1f}%",
            int(getattr(rep, 'total_images', 0) or 0),
            reference_name,
            entry_decision(rep, scope, i),
        ), tags=row_tags)
