#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka Treningu: Budowa datasetu + trening YOLO + analiza modeli.
"""

from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path, PurePosixPath

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from ..campaign_manager import CAMPAIGN
from ..config import CONFIG, YOLO_AVAILABLE, AVAILABLE_POSE_MODELS, AVAILABLE_DETECT_MODELS, PIL_AVAILABLE, logger
from ..icons import IconManager
from ..validators import validate_yolo_dataset, validate_model_file
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..ranking import ModelRanking, ModelRankingEntry
from ..utils import safe_load_yaml
from .help_manager import HELP
from .zoomable_canvas import ZoomableCanvas

if PIL_AVAILABLE:
    from PIL import Image, ImageTk

try:
    from ultralytics import YOLO
except ImportError:
    pass

class TrainingTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager

        self.frame = ttk.Frame(parent)

        self.trainer = YOLOPoseTrainer()
        self.history: TrainingHistory = self.trainer.history
        self.creator = DatasetCreator()
        self.splitter = DatasetSplitter()
        self.ranking_engine = ModelRanking()

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
        
        self.val_is_running = False
        self.rank_is_running = False

        self._build_ui()
        self._attach_training_log_handlers()
        self._bind_trainer_callbacks()
        self._load_history()
        self._load_ranking()
        self._on_base_model_change()

    def _ui(self, fn):
        self.frame.after(0, fn)

    def _append_train_log(self, message: str):
        """Bezpieczne dopisywanie linii do konsoli treningu z dowolnego wątku."""
        def update():
            try:
                self.train_log_console.config(state=tk.NORMAL)
                self.train_log_console.insert(tk.END, message.rstrip() + "\n")
                self.train_log_console.see(tk.END)
                self.train_log_console.config(state=tk.DISABLED)
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
                    if msg.strip():
                        self.owner._append_train_log(msg)
                except Exception:
                    pass

        fmt = logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S")

        # Handler dla loggera aplikacji.
        self._gui_app_log_handler = GuiLogHandler(self)
        self._gui_app_log_handler.setFormatter(fmt)
        logger.addHandler(self._gui_app_log_handler)

        # Handler dla loggera Ultralytics.
        self._gui_yolo_log_handler = GuiLogHandler(self)
        self._gui_yolo_log_handler.setFormatter(fmt)

        self._ultralytics_logger = logging.getLogger("ultralytics")
        self._ultralytics_logger.addHandler(self._gui_yolo_log_handler)

        self._training_log_handlers_attached = True
    def _get_datasets_base_dir(self) -> Path:
        """Zwraca bazowy katalog datasetów dla aktywnego projektu albo globalny fallback."""
        if self._campaign_datasets_dir:
            return Path(self._campaign_datasets_dir)
        return Path(CONFIG.DEFAULT_DATASETS_DIR)

    def _get_runs_base_dir(self) -> Path:
        """Zwraca bazowy katalog runów treningowych dla aktywnego projektu albo globalny fallback."""
        if self._campaign_runs_dir:
            return Path(self._campaign_runs_dir)
        return Path(CONFIG.DEFAULT_TRAINING_DIR)

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
        workspace_dir = self._format_workspace_relative_path(CONFIG.DIR_4_DATASETS)

        if campaign_active:
            preferred_dir = self._format_workspace_relative_path(self._get_datasets_base_dir())
            return (
                "Tryb projektu: to pole zwykle uzupelnia kampania. Jesli wskazujesz dataset recznie, "
                "wybierz katalog zawierajacy plik data.yaml oraz foldery images/ i labels/.\n"
                f"Najczesciej bedzie to katalog projektu albo jego datasetowy odpowiednik: {preferred_dir}"
            )

        return (
            "Tryb swobodny: wskazujesz tutaj gotowy katalog datasetu YOLO, a nie plik modelu.\n"
            "data.yaml to plik konfiguracyjny YOLO, ktory opisuje splity train/val/test oraz klasy modelu.\n"
            "Skad go wziac: utworz dataset w Z4/PZ1. Dla toru znakow plik powstaje po splicie datasetu, "
            "a dla toru tablic po budowie datasetu z XML CVAT.\n"
            f"W sztywnym drzewie Workspace szukaj go przede wszystkim w: {workspace_dir}\n"
            "Tutaj wybierz caly folder datasetu, w ktorym lezy data.yaml oraz podfoldery images/ i labels/."
        )

    def _update_training_dataset_hint(self):
        label = getattr(self, "train_dataset_hint_lbl", None)
        if label is None:
            return

        try:
            label.configure(text=self._get_training_dataset_hint_text())
        except Exception:
            pass

        self._update_training_dataset_hint_wraplength()

    def _update_training_dataset_hint_wraplength(self, event=None):
        label = getattr(self, "train_dataset_hint_lbl", None)
        if label is None:
            return

        width = 0
        try:
            width = int(label.winfo_width())
        except Exception:
            width = 0

        if width <= 1:
            try:
                inset = max(0, int(getattr(self, "_train_left_content_inset", 0)))
                width = int(self.train_left_canvas.winfo_width()) - (4 * inset)
            except Exception:
                width = 0

        target = max(120, width - 2)
        try:
            current = int(float(label.cget("wraplength")))
        except Exception:
            current = 0

        if abs(current - target) <= 2:
            return

        try:
            label.configure(wraplength=target)
        except Exception:
            pass
    
            #=====================================
    def set_campaign_context(self, runs_dir=None, datasets_dir=None):
        """
        Przełącza TrainingTab na katalogi aktywnego projektu
        i odtwarza stan z4 dla bieżącego projektu.
        """
        if datasets_dir is not None:
            self._campaign_datasets_dir = str(Path(datasets_dir))

        project_datasets_dir = Path(self._campaign_datasets_dir) if self._campaign_datasets_dir else None

        if runs_dir is None:
            self._reset_step4_transient_ui(
                datasets_dir=project_datasets_dir,
                require_route_selection=True
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
                require_route_selection=True
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
            target="char",
            clear_builder_inputs=True,
            require_route_selection=True
        )

        try:
            self._restore_step4_campaign_project_state()
        except Exception:
            pass

        logger.info(f"TrainingTab przełączony na projektowy katalog runów: {new_runs_dir}")



    #=====================================
    def _restore_step4_campaign_project_state(self):
        """
        Odtwarza stan z4 dla aktywnego projektu oryg:
        - czyści ścieżki z poprzedniego projektu,
        - uzupełnia źródło splitu w pz1, jeśli istnieje sensowna paczka źródłowa,
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
                self.split_out_var.set(f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]")
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
                self.ds_out_var.set(f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/Plates_CVAT_[DATA_I_CZAS]")
        except Exception:
            pass

        remembered_target = self.get_campaign_training_target()
        if remembered_target not in ("char", "plate"):
            remembered_target = "char"

        latest_source = None
        ready_dataset = None
        ready_target = remembered_target
        latest_xml = ""
        current_iter_images = ""

        if datasets_dir is not None and datasets_dir.exists():
            try:
                source_candidates = [
                    p for p in datasets_dir.iterdir()
                    if p.is_dir()
                    and "_Split_" not in p.name
                    and (p / "images").exists()
                ]
                if source_candidates:
                    latest_source = max(source_candidates, key=lambda p: p.stat().st_mtime)
            except Exception:
                latest_source = None

            ready_candidates = []
            try:
                for p in datasets_dir.iterdir():
                    if not p.is_dir():
                        continue

                    yaml_path = p / "data.yaml"
                    if not yaml_path.exists():
                        continue

                    try:
                        cfg = safe_load_yaml(yaml_path) or {}
                    except Exception:
                        continue

                    is_pose = "kpt_shape" in cfg
                    target = "plate" if is_pose else "char"
                    ready_candidates.append((p, target, p.stat().st_mtime))
            except Exception:
                ready_candidates = []

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
                    latest_xml = str(max(xml_files, key=lambda p: p.stat().st_mtime))
        except Exception:
            latest_xml = ""

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
                self.split_out_var.set(str(Path(self._campaign_datasets_dir) / f"{latest_source.name}_Split_[DATA_I_CZAS]"))
            except Exception:
                pass

        try:
            self.cvat_xml_var.set(latest_xml)
        except Exception:
            pass

        try:
            self.cvat_images_var.set(current_iter_images)
        except Exception:
            pass

        self._step4_dataset_mode = ready_target
        self.set_campaign_training_target(ready_target)
        self._step4_route_selected = False
        self._step4_train_unlocked = False

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
            self._refresh_step4_campaign_navigation_ui()
        except Exception:
            pass

        try:
            self.main_nb.select(self.tab_dataset)
        except Exception:
            pass

        try:
            self._guide_step4_route_selection()
        except Exception:
            pass

    def clear_campaign_context(self):
        """
        Czyści projektowy kontekst treningu i wraca do globalnych katalogów Workspace.
        Dodatkowo czyści kampanijne logi / wyniki widoczne w UI.
        """
        self._campaign_runs_dir = None
        self._campaign_datasets_dir = None

        self.history = TrainingHistory(history_dir=Path(CONFIG.DEFAULT_TRAINING_DIR))
        self.trainer = YOLOPoseTrainer(history=self.history)
        self._bind_trainer_callbacks()

        self._reset_step4_transient_ui(
            target="char",
            clear_builder_inputs=True,
            require_route_selection=False
        )

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
            else f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]"
        )
        ds_out_default = (
            str(datasets_dir / "Plates_CVAT_[DATA_I_CZAS]")
            if datasets_dir is not None
            else f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/Plates_CVAT_[DATA_I_CZAS]"
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
            self.train_progress_var.set(0.0)
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
            self.rank_models_dir.set(str(Path(CONFIG.DEFAULT_MODELS_DIR)))
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

        self._load_history()
        self._set_training_ui_idle_state()

        try:
            self._set_step4_builder_log_visibility(False)
        except Exception:
            pass

        try:
            self._set_step4_train_log_visibility(False)
        except Exception:
            pass

        try:
            self.main_nb.select(self.tab_dataset)
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

        if self._step4_builder_log_visible:
            self.step4_builder_log_frame.pack(
                fill=tk.BOTH,
                expand=True,
                pady=(8, 0),
                before=self.step4_builder_nav
            )
            try:
                self.btn_toggle_step4_log.grid_remove()
            except Exception:
                pass
        else:
            self.step4_builder_log_frame.pack_forget()
            try:
                self.btn_toggle_step4_log.grid()
            except Exception:
                pass

    def _toggle_step4_builder_log(self):
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
            width = max(50, int(canvas.winfo_width()) - (2 * inset))
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

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        console_border = palette.get("console_border", palette.get("border", "#3c3c3c"))

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

    def _set_step4_train_log_visibility(self, visible: bool):
        if not hasattr(self, "step4_train_log_frame"):
            return

        self._step4_train_log_visible = bool(visible)

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

    def _sync_step4_analysis_nav_buttons(self, event=None):
        if not hasattr(self, "right_nb"):
            return

        try:
            selected = str(self.right_nb.select())
        except Exception:
            selected = ""

        mapping = (
            ("btn_step4_nav_hist", getattr(self, "hist_tab", None)),
            ("btn_step4_nav_plots", getattr(self, "plots_tab", None)),
            ("btn_step4_nav_val", getattr(self, "val_tab", None)),
            ("btn_step4_nav_rank", getattr(self, "ranking_tab", None)),
        )

        for attr_name, tab_widget in mapping:
            btn = getattr(self, attr_name, None)
            if btn is None or tab_widget is None:
                continue

            try:
                btn.configure(state=(tk.DISABLED if selected == str(tab_widget) else tk.NORMAL))
            except Exception:
                pass

    def _resolve_step4_guidance_buttons(self, attr_name: str):
        if attr_name == "step4_route_panel_frame":
            return [getattr(self, "btn_choose_plate", None), getattr(self, "btn_choose_char", None)]

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

    def _set_step4_dataset_mode(self, mode: str):
        mode = (mode or "char").strip().lower()
        if mode not in ("char", "plate"):
            mode = "char"

        campaign_active = bool(CAMPAIGN.get_active_project_name())

        self._step4_dataset_mode = mode
        self.set_campaign_training_target(mode)
        if campaign_active:
            self._step4_route_selected = True
            self._step4_train_unlocked = False
        self._refresh_step4_dataset_mode_ui()
        self._refresh_step4_campaign_navigation_ui()

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

    def _refresh_step4_dataset_mode_ui(self):
        if not hasattr(self, "ds_mode_host"):
            return

        mode = getattr(self, "_step4_dataset_mode", "char")
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        route_selected = bool(getattr(self, "_step4_route_selected", False))

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
                text="Dalej: najpierw wybierz tor",
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
            self.btn_choose_char.configure(state=tk.NORMAL)
            self.ds_creator_frame.pack(fill=tk.X, expand=False)
            self.btn_step4_next.configure(text="Dalej: Trening i analiza modelu tablic")
        else:
            self.ds_mode_title_var.set("Tor znaków (YOLO Detect)")
            self.ds_mode_desc_var.set(
                "Wybierz ten tor, jeśli chcesz przygotować i podzielić dataset znaków "
                "i trenować model znaków na tablicach."
            )
            self.btn_choose_plate.configure(state=tk.NORMAL)
            self.btn_choose_char.configure(state=tk.DISABLED)
            self.ds_split_frame.pack(fill=tk.X, expand=False)
            self.btn_step4_next.configure(text="Dalej: Trening i analiza modelu znaków")

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
            try:
                self.app.open_controlled_tab("campaign")
                return
            except Exception:
                pass

        self._append_step4_builder_log(
            "[NAWIGACJA] Tryb swobodny: brak poprzedniego kroku wizardowego do otwarcia."
        )

    def _refresh_step4_campaign_navigation_ui(self):
        campaign_active = bool(CAMPAIGN.get_active_project_name())
        train_unlocked = bool(getattr(self, "_step4_train_unlocked", False))
        route_selected = bool(getattr(self, "_step4_route_selected", False))

        try:
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
            if campaign_active and not train_unlocked and str(self.main_nb.select()) == str(self.tab_train):
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
            self._append_train_log(
                "[KAMPANIA] Użytkownik zakończył krok 4. "
                "Cykl iteracji został domknięty."
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
        do ręcznego zakończenia kroku 4. Nie zamyka kroku automatycznie.
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
                f"Możesz teraz zakończyć krok 4 z poziomu z4."
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

            if CAMPAIGN.get_active_project_name() and promoted:
                self._step4_campaign_finish_ready = True
                self._set_training_ui_idle_state(
                    "Trening zakończony. Kliknij „Zakończ krok 4 i wróć do kampanii”.",
                    "#1e8449"
                )
            else:
                self._step4_campaign_finish_ready = False
                self._set_training_ui_idle_state("Trening zakończony lub zatrzymany.", "#2c3e50")

            try:
                self._refresh_step4_campaign_navigation_ui()
            except Exception:
                pass

            if CAMPAIGN.get_active_project_name() and promoted:
                try:
                    self._guide_step4_finish_action()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Błąd pollingu końca treningu: {e}")
            self._training_completion_poll_job = None
            self._pending_campaign_model_type = None
            self._step4_campaign_finish_ready = False
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
            self.btn_start_train.configure(state=tk.NORMAL)
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

    
    def _get_available_devices(self):
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()): devices.append(f"cuda:{i}")
        except Exception: pass
        return devices

    def _device_to_ultralytics(self, device_str: str):
        if not device_str or device_str == "auto": return "auto"
        if device_str == "cpu": return "cpu"
        if device_str.startswith("cuda:"):
            try: return int(device_str.split(":")[1].split()[0])
            except: return 0
        return "auto"

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
        self.main_nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tab_dataset = ttk.Frame(self.main_nb)
        self.tab_train = ttk.Frame(self.main_nb)
        self.tab_val = None
        self.tab_ranking = None

        self.main_nb.add(self.tab_dataset, text="[PZ1] Budowa datasetu")
        self.main_nb.add(self.tab_train, text="[PZ2] Trening i analiza")

        self._build_dataset_tab()
        self._build_train_tab()

    def _build_dataset_tab(self):
        root = ttk.Frame(self.tab_dataset, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.X, expand=False)

        self.step4_route_panel_frame = tk.Frame(top, bd=0, highlightthickness=1)
        self.step4_route_panel_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

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

        self.step4_builder_log_text = scrolledtext.ScrolledText(
            self.step4_builder_log_frame,
            wrap=tk.WORD,
            height=10,
            font=("Consolas", 10)
        )
        self.step4_builder_log_text.pack(fill=tk.BOTH, expand=True)
        self.step4_builder_log_text.configure(state=tk.DISABLED)

        self.step4_builder_nav = ttk.Frame(root)
        self.step4_builder_nav.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self.step4_builder_nav.grid_columnconfigure(0, weight=0)
        self.step4_builder_nav.grid_columnconfigure(1, weight=0)
        self.step4_builder_nav.grid_columnconfigure(2, weight=1)
        self.step4_builder_nav.grid_columnconfigure(3, weight=0)

        self.btn_step4_back = ttk.Button(
            self.step4_builder_nav,
            text="Wstecz",
            command=self._step4_dataset_go_back
        )
        self.btn_step4_back.grid(row=0, column=0, sticky="w")

        self.btn_toggle_step4_log = ttk.Button(
            self.step4_builder_nav,
            text="Pokaż terminal",
            command=self._toggle_step4_builder_log
        )
        self.btn_toggle_step4_log.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.btn_step4_next_frame = tk.Frame(self.step4_builder_nav, bd=0, highlightthickness=0)
        self.btn_step4_next_frame.grid(row=0, column=3, sticky="e", padx=(10, 0))

        self.btn_step4_next_pulse_frame = tk.Frame(
            self.btn_step4_next_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_next_pulse_frame.pack(anchor=tk.E)

        self.btn_step4_next = ttk.Button(
            self.btn_step4_next_pulse_frame,
            text="Dalej: Trening i analiza modelu znaków",
            command=self._step4_dataset_go_next
        )
        self.btn_step4_next.pack()

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
        ttk.Label(
            f,
            text="Tworzy strukturę YOLO Pose na podstawie wyeksportowanego pliku annotations.xml.",
            font=("Segoe UI", 9)
        ).pack(anchor=tk.W, pady=(0, 10))
        row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="CVAT XML:").pack(side=tk.LEFT)
        self.cvat_xml_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.cvat_xml_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row1, text="Wybierz", command=lambda: self._pick_file(self.cvat_xml_var, "*.xml")).pack(side=tk.LEFT)

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Folder obrazów:").pack(side=tk.LEFT)
        self.cvat_images_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.cvat_images_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row2, text="Wybierz", command=lambda: self._pick_dir(self.cvat_images_var)).pack(side=tk.LEFT)

        row3 = ttk.Frame(f); row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Zapis danych:").pack(side=tk.LEFT)
        # Ścieżka docelowa jest wyliczana automatycznie i pozostaje tylko do odczytu.
        self.ds_out_var = tk.StringVar(value=f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/Plates_CVAT_[DATA_I_CZAS]")
        ttk.Entry(row3, textvariable=self.ds_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

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
        self.ds_progress = ttk.Progressbar(f, variable=self.ds_progress_var, maximum=100)
        self.ds_progress.pack(fill=tk.X, pady=2)
        
        self.ds_status = ttk.Label(f, text="Gotowy", foreground="green")
        self.ds_status.pack(anchor=tk.W)

        # Powiązania pomocy dla budowy datasetu z CVAT.
        HELP.bind_help(row1, "tr_cvat_xml")
        HELP.bind_help(row2, "tr_cvat_img")
        HELP.bind_help(self.btn_step4_create, "tr_cvat_btn")

    def _build_splitter_ui(self):
        f = self.ds_split_frame
        ttk.Label(
            f,
            text="Dzieli zbiór (np. wygenerowany w zakładce Znaków) na foldery train/val potrzebne do treningu.",
            font=("Segoe UI", 9)
        ).pack(anchor=tk.W, pady=(0, 10))
        
        row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Źródło (np. mega-dataset):").pack(side=tk.LEFT)
        self.split_src_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.split_src_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row1, text="Wybierz", command=lambda: self._pick_dir(self.split_src_var)).pack(side=tk.LEFT)

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Wynik podziału:").pack(side=tk.LEFT)
        # Ścieżka wyniku splitu jest wyliczana automatycznie i pozostaje tylko do odczytu.
        self.split_out_var = tk.StringVar(value=f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]")
        ttk.Entry(row2, textvariable=self.split_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ratios = ttk.Frame(f); ratios.pack(fill=tk.X, pady=10)
        ttk.Label(ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
        self.train_pct = tk.DoubleVar(value=80.0)
        ttk.Scale(ratios, from_=50, to=90, variable=self.train_pct, command=lambda e: self._update_ratio_labels()).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.train_lbl = ttk.Label(ratios, text="80%"); self.train_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
        self.val_pct = tk.DoubleVar(value=10.0)
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
        self.split_progress = ttk.Progressbar(self.split_feedback_frame, variable=self.split_progress_var, maximum=100)
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
        root = ttk.Frame(self.tab_train, padding=5)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.train_pane = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.train_pane.grid(row=0, column=0, sticky="nsew")

        self.left = ttk.LabelFrame(self.train_pane, text=" Konfiguracja Treningu ", padding=10)
        self.right = ttk.LabelFrame(self.train_pane, text=" Analiza i narzędzia ", padding=10)
        self.train_pane.add(self.left, weight=0)
        self.train_pane.add(self.right, weight=1)

        self.left.grid_rowconfigure(0, weight=1)
        self.left.grid_columnconfigure(0, weight=1)

        self.train_left_scroll_host = ttk.Frame(self.left)
        self.train_left_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.train_left_scroll_host.grid_rowconfigure(0, weight=1)
        self.train_left_scroll_host.grid_columnconfigure(0, weight=1)

        self.train_left_canvas = tk.Canvas(
            self.train_left_scroll_host,
            bg="#252526",
            bd=0,
            highlightthickness=0
        )
        self.train_left_canvas.grid(row=0, column=0, sticky="nsew")

        self.train_left_scrollbar = ttk.Scrollbar(
            self.train_left_scroll_host,
            orient=tk.VERTICAL,
            command=self.train_left_canvas.yview
        )
        self.train_left_scrollbar.grid(row=0, column=1, sticky="ns")
        self.train_left_canvas.configure(yscrollcommand=self.train_left_scrollbar.set)

        self._train_left_content_inset = 12
        self.train_left_content = ttk.Frame(self.train_left_canvas)
        self.train_left_content.grid_columnconfigure(0, weight=1)
        self.train_left_content_window = self.train_left_canvas.create_window(
            (self._train_left_content_inset, 0),
            window=self.train_left_content,
            anchor="nw"
        )
        self.train_left_content.bind("<Configure>", self._sync_train_left_scrollregion, add="+")
        self.train_left_canvas.bind("<Configure>", self._sync_train_left_canvas_width, add="+")

        settings_col = ttk.Frame(self.train_left_content)
        settings_col.pack(fill=tk.BOTH, expand=True, pady=(0, 2))

        ttk.Label(settings_col, text="Nazwa sesji treningowej:").pack(anchor=tk.W)
        self.name_var = tk.StringVar()
        ttk.Entry(settings_col, textvariable=self.name_var, width=35).pack(fill=tk.X, pady=2)
        


        ttk.Label(settings_col, text="Gotowy dataset (katalog z plikiem data.yaml):").pack(anchor=tk.W, pady=(8, 0))
        self.dataset_var = tk.StringVar()
        ds_row = ttk.Frame(settings_col)
        ds_row.pack(fill=tk.X, pady=2)
        ttk.Entry(ds_row, textvariable=self.dataset_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(ds_row, text="Wybierz", command=lambda: self._pick_dir(self.dataset_var)).pack(side=tk.LEFT, padx=5)

        self.train_dataset_hint_box = ttk.Frame(
            settings_col,
            padding=(self._train_left_content_inset, 8, self._train_left_content_inset, 8)
        )
        self.train_dataset_hint_box.pack(anchor=tk.W, fill=tk.X, pady=(4, 8))

        self.train_dataset_hint_lbl = ttk.Label(
            self.train_dataset_hint_box,
            text="",
            style="Muted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=320
        )
        self.train_dataset_hint_lbl.pack(anchor=tk.W, fill=tk.X)
        self.train_dataset_hint_box.bind("<Configure>", self._update_training_dataset_hint_wraplength, add="+")
        self.train_dataset_hint_lbl.bind("<Configure>", self._update_training_dataset_hint_wraplength, add="+")
        self._update_training_dataset_hint()

        ttk.Label(settings_col, text="Architektura (model bazowy):").pack(anchor=tk.W, pady=(8, 0))
        self.base_model_var = tk.StringVar()
        
        base_values = list(AVAILABLE_DETECT_MODELS.keys()) + list(AVAILABLE_POSE_MODELS.keys()) + ["Custom"]
        
        self.base_combo = ttk.Combobox(settings_col, textvariable=self.base_model_var, values=base_values, state="readonly")
        self.base_combo.pack(fill=tk.X, pady=2)
        self.base_model_var.set("yolo11n.pt") 
        self.base_combo.bind("<<ComboboxSelected>>", lambda e: self._on_base_model_change())

        # Pozwól wskazać własny model do fine-tuningu z katalogu modeli.
        self.base_custom_var = tk.StringVar()
        self.custom_row = ttk.Frame(settings_col)
        self.custom_row.pack(fill=tk.X, pady=2)
        
        self.base_custom_entry = ttk.Entry(self.custom_row, textvariable=self.base_custom_var, state=tk.DISABLED)
        self.base_custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.base_custom_btn = ttk.Button(self.custom_row, text="Wybierz .pt", state=tk.DISABLED, 
                                          command=lambda: self._pick_file(self.base_custom_var, "*.pt", CONFIG.DIR_6_MODELS))
        self.base_custom_btn.pack(side=tk.LEFT, padx=(5,0))

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
        auto_name() # Inicjalizacja pierwszego wpisu        
        
        grid = ttk.Frame(settings_col)
        grid.pack(fill=tk.X, pady=10)
        ttk.Label(grid, text="Epoki:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.epochs_var = tk.IntVar(value=100)
        ttk.Spinbox(grid, from_=1, to=5000, textvariable=self.epochs_var, width=8).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Batch Size:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.batch_var = tk.IntVar(value=16)
        ttk.Spinbox(grid, from_=1, to=256, textvariable=self.batch_var, width=8).grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Rozdzielczość (px):").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.imgsz_var = tk.IntVar(value=640)
        imgsz_spin = ttk.Spinbox(grid, from_=32, to=2048, increment=32, textvariable=self.imgsz_var, width=8)
        imgsz_spin.grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Learning Rate (lr0):").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.lr0_var = tk.DoubleVar(value=0.01)
        lr0_spin = ttk.Spinbox(grid, from_=0.0001, to=0.1, increment=0.001, format="%.4f", textvariable=self.lr0_var, width=8)
        lr0_spin.grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Device:").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.device_var = tk.StringVar(value="auto")
        ttk.Combobox(grid, textvariable=self.device_var, values=self._get_available_devices(), state="readonly", width=15).grid(row=4, column=1, sticky=tk.W, padx=5)

        self.btn_step4_start_train_frame = tk.Frame(settings_col, bd=0, highlightthickness=0)
        self.btn_step4_start_train_frame.pack(fill=tk.X, pady=(15, 5))

        self.btn_step4_start_train_pulse_frame = tk.Frame(
            self.btn_step4_start_train_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_start_train_pulse_frame.pack(fill=tk.X)

        self.btn_start_train = ttk.Button(
            self.btn_step4_start_train_pulse_frame,
            text="▶ ROZPOCZNIJ TRENING",
            command=self._start_training,
            style="Accent.TButton"
        )
        self.btn_start_train.pack(fill=tk.X)
        
        self.btn_stop_train = ttk.Button(settings_col, text="ZATRZYMAJ", command=self._stop_training, state=tk.DISABLED)
        self.btn_stop_train.pack(fill=tk.X, pady=2)

        self.train_progress_var = tk.DoubleVar(value=0.0)
        self.train_progress = ttk.Progressbar(settings_col, variable=self.train_progress_var, maximum=100)
        self.train_progress.pack(fill=tk.X, pady=(15, 2))
        
        self.train_progress_label = ttk.Label(settings_col, text="Czekam na start...", font=("Segoe UI", 9))
        self.train_progress_label.pack(anchor=tk.W)

        terminal_tools = ttk.Frame(root)
        terminal_tools.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.btn_toggle_step4_train_log = ttk.Button(
            terminal_tools,
            text="Pokaż terminal",
            command=self._toggle_step4_train_log
        )
        self.btn_toggle_step4_train_log.pack(side=tk.LEFT)

        ttk.Label(
            terminal_tools,
            text="Wspólny terminal procesu dla treningu i walidacji jest dostępny na żądanie.",
            foreground="gray"
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.step4_train_log_host = ttk.Frame(root)
        self.step4_train_log_host.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        self.step4_train_log_frame = ttk.LabelFrame(
            self.step4_train_log_host,
            text=" Terminal procesu ",
            padding=6
        )
        self.train_log_console = scrolledtext.ScrolledText(
            self.step4_train_log_frame,
            width=50,
            height=10,
            font=("Consolas", 10),
            bg="#1e1e1e", fg="#ecf0f1", bd=2, relief="sunken"
        )
        self.train_log_console.pack(fill=tk.BOTH, expand=True)
        self._set_step4_process_console_text(
            "Oczekuję na rozpoczęcie treningu lub walidacji...\n"
            "Terminal procesu jest gotowy na dane z Ultralytics.\n"
        )
        self._set_step4_train_log_visibility(False)

        self.right_nb = ttk.Notebook(self.right)
        self.right_nb.pack(fill=tk.BOTH, expand=True)

        self.hist_tab = ttk.Frame(self.right_nb)
        self.plots_tab = ttk.Frame(self.right_nb)
        self.val_tab = ttk.Frame(self.right_nb)
        self.ranking_tab = ttk.Frame(self.right_nb)
        self.right_nb.add(self.hist_tab, text="Historia treningów")
        self.right_nb.add(self.plots_tab, text="Analiza (wykresy)")
        self.right_nb.add(self.val_tab, text="Walidacja")
        self.right_nb.add(self.ranking_tab, text="Ranking")
        self.right_nb.bind("<<NotebookTabChanged>>", self._sync_step4_analysis_nav_buttons)

        hist_top = ttk.Frame(self.hist_tab)
        hist_top.pack(fill=tk.BOTH, expand=True)
        columns = ("ID", "Nazwa", "Status", "Epoki", "mAP50", "Czas")
        self.tree = ttk.Treeview(hist_top, columns=columns, show="headings")
        for c in columns: self.tree.heading(c, text=c)
        self.tree.column("ID", width=130, stretch=False)
        self.tree.column("Nazwa", width=180, stretch=True)
        self.tree.column("Status", width=100, stretch=False)
        self.tree.column("Epoki", width=80, stretch=False)
        self.tree.column("mAP50", width=80, stretch=False)
        self.tree.column("Czas", width=100, stretch=False)

        yscroll = ttk.Scrollbar(hist_top, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_run_selected)

        hist_btns = ttk.Frame(self.hist_tab)
        hist_btns.pack(fill=tk.X, pady=5)
        ttk.Button(hist_btns, text="Usuń", command=self._delete_selected).pack(side=tk.LEFT)
        ttk.Button(hist_btns, text="Otwórz folder", command=self._open_run_folder).pack(side=tk.RIGHT)

        self.step4_analysis_nav = ttk.Frame(self.right)
        self.step4_analysis_nav.pack(fill=tk.X, pady=(8, 0))

        self.btn_step4_nav_hist = ttk.Button(
            self.step4_analysis_nav,
            text="Historia",
            command=lambda: self._select_step4_analysis_tab(self.hist_tab)
        )
        self.btn_step4_nav_hist.pack(side=tk.LEFT)

        self.btn_step4_nav_plots = ttk.Button(
            self.step4_analysis_nav,
            text="Wykresy",
            command=lambda: self._select_step4_analysis_tab(self.plots_tab)
        )
        self.btn_step4_nav_plots.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_step4_nav_val = ttk.Button(
            self.step4_analysis_nav,
            text="Walidacja",
            command=lambda: self._select_step4_analysis_tab(self.val_tab)
        )
        self.btn_step4_nav_val.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_step4_nav_rank = ttk.Button(
            self.step4_analysis_nav,
            text="Ranking",
            command=lambda: self._select_step4_analysis_tab(self.ranking_tab)
        )
        self.btn_step4_nav_rank.pack(side=tk.LEFT, padx=(6, 0))

        self._build_plots_ui()
        self._build_validation_panel(self.val_tab)
        self._build_ranking_panel(self.ranking_tab)
        self._sync_step4_analysis_nav_buttons()

        self.step4_train_nav = ttk.Frame(root)
        self.step4_train_nav.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        self.btn_step4_train_back = ttk.Button(
            self.step4_train_nav,
            text="← Wstecz do wyboru toru",
            command=self._step4_train_go_back
        )
        self.btn_step4_train_back.pack(side=tk.LEFT)

        self.btn_step4_finish_frame = tk.Frame(self.step4_train_nav, bd=0, highlightthickness=0)
        self.btn_step4_finish_frame.pack(side=tk.RIGHT)

        self.btn_step4_finish_pulse_frame = tk.Frame(
            self.btn_step4_finish_frame,
            bd=0,
            highlightthickness=1
        )
        self.btn_step4_finish_pulse_frame.pack(anchor=tk.E)

        self.btn_step4_finish = ttk.Button(
            self.btn_step4_finish_pulse_frame,
            text="Zakończ krok 4 i wróć do kampanii",
            command=self._finish_campaign_step4,
            style="Accent.TButton",
            state=tk.DISABLED
        )
        self.btn_step4_finish.pack()

        self._refresh_step4_campaign_navigation_ui()

        HELP.bind_help(ds_row, "tr_train_ds")
        HELP.bind_help(self.train_dataset_hint_lbl, "tr_train_ds")
        HELP.bind_help(self.base_combo, "tr_train_base")
        
        try:
            HELP.bind_help(grid.grid_slaves(row=0, column=1)[0], "tr_train_ep") 
            HELP.bind_help(grid.grid_slaves(row=1, column=1)[0], "tr_train_bs") 
            HELP.bind_help(imgsz_spin, "tr_train_imgsz")
            HELP.bind_help(lr0_spin, "tr_train_lr0") 
        except Exception as e: 
            logger.debug(f"Błąd podpinania pomocy do siatki: {e}")
        
        HELP.bind_help(self.btn_start_train, "tr_train_btn")
        HELP.bind_help(self.tree, "tr_train_tree")
        HELP.bind_help(self.plots_tab, "tr_train_plot")
        HELP.bind_help(self.custom_row, "tr_train_custom")
        HELP.bind_help(self.btn_toggle_step4_train_log, "tr_train_log")
        HELP.bind_help(self.step4_analysis_nav, "tr_analysis_nav")
        HELP.bind_help(self.btn_step4_train_back, "tr_train_back")
        HELP.bind_help(self.btn_step4_finish, "tr_train_finish")

        self.frame.after_idle(self._sync_train_left_scrollregion)
        self.frame.after_idle(self._sync_train_left_canvas_width)
        self.frame.bind_all("<MouseWheel>", self._on_train_left_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_train_left_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_train_left_global_mousewheel, add="+")

    def _build_plots_ui(self):
        self.plots_pane = ttk.PanedWindow(self.plots_tab, orient=tk.HORIZONTAL)
        self.plots_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(self.plots_pane)
        right = ttk.Frame(self.plots_pane)
        self.plots_pane.add(left, weight=1)
        self.plots_pane.add(right, weight=4) # Poszerzamy pole na wykres

        # Lista obrazów
        self.plots_list = tk.Listbox(left, height=12, font=("Consolas", 10), selectbackground="#3498db")
        self.plots_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.plots_list.bind("<<ListboxSelect>>", self._on_plot_selected)

        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        # Inicjalizujemy ZoomableCanvas (ten sam co w przeglądarce tablic)
        self.plot_canvas = ZoomableCanvas(canvas_frame, bg="#1e1e1e", highlightthickness=0)
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
        ttk.Button(row1, text="Wybierz", command=lambda: self._pick_file(self.val_model_var, "*.pt")).pack(side=tk.RIGHT, padx=(5,0))
        
        ttk.Label(parent, text="Dataset testowy (data.yaml):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(15, 2))
        row2 = ttk.Frame(parent)
        row2.pack(fill=tk.X)
        self.val_data_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.val_data_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wybierz", command=lambda: self._pick_dir(self.val_data_var)).pack(side=tk.RIGHT, padx=(5,0))

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

    def _build_ranking_panel(self, parent):
        ttk.Label(
            parent,
            text="Porównuj wytrenowane modele względem ground truth z annotations.xml.",
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

        ttk.Label(left_f, text="Kategoria testu:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0,5))
        self.rank_category_var = tk.StringVar(value="Tablice (Pose)")
        cat_combo = ttk.Combobox(left_f, textvariable=self.rank_category_var, 
                                 values=["Pojazdy (Detect)", "Tablice (Pose)", "Znaki/Litery (Detect)"], 
                                 state="readonly")
        cat_combo.pack(fill=tk.X, pady=(0, 15))
        cat_combo.bind("<<ComboboxSelected>>", lambda e: self._load_ranking())

        ttk.Label(left_f, text="Katalog z modelami (.pt):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        row1 = ttk.Frame(left_f)
        row1.pack(fill=tk.X, pady=2)
        self.rank_models_dir = tk.StringVar(value=str(Path(CONFIG.DEFAULT_MODELS_DIR)))
        ttk.Entry(row1, textvariable=self.rank_models_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row1, text="Wyb", command=lambda: self._pick_dir(self.rank_models_dir)).pack(side=tk.RIGHT, padx=(2,0))

        ttk.Label(left_f, text="Dataset z CVAT (Ground Truth):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(10,0))
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
        self.rank_progress = ttk.Progressbar(left_f, mode="determinate", variable=self.rank_progress_var)
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

        yscroll = ttk.Scrollbar(right_f, orient=tk.VERTICAL, command=self.rank_tree.yview)
        self.rank_tree.configure(yscrollcommand=yscroll.set)
        self.rank_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        HELP.bind_help(cat_combo, "tr_rank_cat")
        HELP.bind_help(self.btn_run_rank, "tr_rank_btn")

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
        self.train_lbl.configure(text=f"{train:.0f}%")
        self.val_lbl.configure(text=f"{val:.0f}%")
        self.test_lbl.configure(text=f"Test: {test:.0f}%")

    def _on_base_model_change(self):
        if self.base_model_var.get() == "Custom":
            self.base_custom_entry.configure(state=tk.NORMAL)
            if hasattr(self, 'base_custom_btn'):
                self.base_custom_btn.configure(state=tk.NORMAL)
        else:
            self.base_custom_entry.configure(state=tk.DISABLED)
            if hasattr(self, 'base_custom_btn'):
                self.base_custom_btn.configure(state=tk.DISABLED)

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

        self.ds_progress_var.set(0)
        self.ds_status.configure(text="Rozpoczynam budowę datasetu...", foreground="black")

        def worker():
            try:
                def prog(c, t, n):
                    pct = (c / t) * 100 if t > 0 else 0
                    self._ui(lambda: self.ds_progress_var.set(pct))
                    self._ui(lambda: self.ds_status.configure(
                        text=f"{c}/{t} obrazów...",
                        foreground="black"
                    ))

                ok2, msg2, _ = self.creator.create_dataset(images_dir, out_dir, ratios, prog)

                if ok2:
                    self._ui(lambda: self.ds_status.configure(
                        text="Dataset został utworzony!",
                        foreground="green"
                    ))
                    self._ui(lambda: messagebox.showinfo("Sukces", msg2))

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

        threading.Thread(target=worker, daemon=True).start()

    def _start_training(self):
        if not YOLO_AVAILABLE:
            return messagebox.showerror("Błąd", "Brak ultralytics.")

        try:
            self._clear_step4_guidance()
        except Exception:
            pass
        
        self._set_step4_process_console_text("Uruchamianie treningu...\n")

        ds = self.dataset_var.get().strip()
        if not ds:
            return messagebox.showerror("Błąd", "Podaj Dataset.")

        ds_path = Path(ds)
        yaml_path = ds_path / "data.yaml" if ds_path.is_dir() else ds_path
        if not yaml_path.exists():
            return messagebox.showerror("Błąd", "Nie znaleziono pliku data.yaml.")

        # Rozpoznaj typ datasetu na podstawie zawartości data.yaml.
        try:
            cfg = safe_load_yaml(yaml_path)
            is_pose_dataset = "kpt_shape" in cfg

            # W kampanii trening detekcji znaków powinien promować model toru char.
            self._current_training_dataset_is_pose = bool(is_pose_dataset)

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
                "Wybrany dataset jest typu DETECT (bboxy, np. znaki), ale model bazowy jest typu POSE.\n\n"
                "Dla znaków wybierz zwykły model detect, np. 'yolo11n' lub 'yolo11s'."
            )

        # Zapisz czytelny nagłówek sesji w terminalu procesu.
        self._append_train_log("=" * 70)
        self._append_train_log(f"START TRENINGU | Nazwa: {self.name_var.get()}")
        self._append_train_log(f"Dataset: {ds}")
        self._append_train_log(f"Model bazowy: {base_model}")
        self._append_train_log(f"Device: {device} | Epochs: {self.epochs_var.get()} | Batch: {self.batch_var.get()} | ImgSz: {self.imgsz_var.get()} | lr0: {self.lr0_var.get()}")
        self._append_train_log("=" * 70)

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

        if run_id:
            self.current_run_id = run_id
            self._step4_campaign_finish_ready = False
            self.btn_start_train.configure(state=tk.DISABLED)
            self.btn_stop_train.configure(state=tk.NORMAL)
            self.train_progress_label.configure(text=f"Trening uruchomiony: {run_id}")

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
        def on_epoch(epoch, metrics):
            run = self.trainer.current_run
            if not run: return
            pct = (epoch / max(1, run.epochs)) * 100.0
            
            # Pobieranie wyników mAP
            map50 = metrics.get('map50', 0)
            map50_95 = metrics.get('map50_95', 0)
            loss = metrics.get('loss', 0)
            
            # Formatowanie logu na żywo
            log_line = f"Epoka {epoch}/{run.epochs} | Strata(Loss): {loss:.3f} | mAP50: {map50:.3f} | mAP50-95: {map50_95:.3f}\n"
            
            # Aktualizacja UI w głównym wątku
            def update_ui():
                self.train_progress_var.set(pct)
                self.train_progress_label.configure(text=f"Trwa trening: Epoka {epoch}/{run.epochs}")
                
                # Bezpieczne wpisywanie do konsoli
                self.train_log_console.config(state=tk.NORMAL)
                self.train_log_console.insert(tk.END, log_line)
                self.train_log_console.see(tk.END)
                self.train_log_console.config(state=tk.DISABLED)
                
            self._ui(update_ui)

        def on_end(success, msg):
            end_line = f"[KONIEC] {'SUKCES' if success else 'BŁĄD/STOP'} | {msg}"
            self._append_train_log(end_line)

            self._ui(lambda: self.btn_start_train.configure(state=tk.NORMAL))
            self._ui(lambda: self.btn_stop_train.configure(state=tk.DISABLED))
            self._ui(lambda: self.train_progress_label.configure(
                text="Trening zakończony." if success else "Trening zatrzymany / zakończony błędem.",
                foreground="#2c3e50" if success else "#c0392b"
            ))
            self._ui(lambda: self._load_history())

        self.trainer.on_epoch_end = on_epoch
        self.trainer.on_training_end = on_end


    def _load_history(self):
        self.tree.delete(*self.tree.get_children())
        for run in self.history.get_all_runs():
            # Zachowaj pełne run.id, aby wybór historii i folderów był jednoznaczny.
            best_map = getattr(run, 'best_map50', 0.0) or 0.0
            
            self.tree.insert("", tk.END, values=(
                str(run.id), 
                str(run.name)[:30], 
                str(run.status), 
                f"{run.current_epoch}/{run.epochs}", 
                f"{float(best_map):.3f}", 
                str(run.duration_str)
            ))

    def _delete_selected(self):
        run = self._selected_run()
        if run and messagebox.askyesno("Potwierdź", "Usunąć run?"):
            self.history.delete_run(run.id, delete_files=True)
            self._load_history()

    def _open_run_folder(self):
        run = self._selected_run()
        if run and Path(run.output_dir).exists():
            self._open_path(Path(run.output_dir))

    def _on_run_selected(self, event=None):
        run = self._selected_run()
        if not run: return
        
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

    def _change_zoom(self, factor):
        self.zoom_var.set(max(0.1, min(float(self.zoom_var.get()) * factor, 8.0)))
        if self._plot_original_path: self._show_plot(Path(self._plot_original_path))

    def _show_plot(self, path):
        """Wczytuje fizyczny obraz z folderu Ultralytics i przekazuje do płynnej nawigacji."""
        if not PIL_AVAILABLE: return
        try:
            self._plot_original_path = str(path)
            img = Image.open(path)
            
            # ZoomableCanvas sam zarządza skalą i przesuwaniem obrazu.
            self.plot_canvas.set_image(img)
            
            # Przy nowym obrazie wróć do domyślnego widoku.
            self.plot_canvas.reset_view()
        except Exception as e: 
            logger.error(f"Nie udało się wyświetlić wykresu: {e}")

    def _change_zoom(self, factor):
        pass

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

        self.val_is_running = True
        self.btn_run_val.config(state=tk.DISABLED, text="Walidacja w toku...")
        self.val_status.config(text="Walidacja w toku...", foreground="#d35400")
        self._set_step4_process_console_text(
            f"Inicjalizowanie silnika YOLO do ewaluacji...\n"
            f"Model: {Path(model_path).name}\n"
            f"Dataset: {Path(data_path).parent.name}\n\n"
        )

        def worker():
            try:
                model = YOLO(model_path)
                metrics = model.val(data=data_path, split=self.val_split_var.get())
                
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
                self._ui(lambda: messagebox.showinfo("Sukces", "Walidacja zakończona pomyślnie!"))
                
            except Exception as e:
                self._append_train_log(f"\nBŁĄD WALIDACJI:\n{e}")
                self._ui(lambda: self.val_status.config(text="Błąd walidacji", foreground="red"))
                logger.error(f"Validation error: {e}")
                
            finally:
                self.val_is_running = False
                self._ui(lambda: self.btn_run_val.config(state=tk.NORMAL, text="🚀 PRZEPROWADŹ WALIDACJĘ"))
                
        threading.Thread(target=worker, daemon=True).start()

    def _load_ranking(self):
        entries = getattr(self.ranking_engine, 'entries', [])
        self.rank_tree.delete(*self.rank_tree.get_children())
        
        category = self.rank_category_var.get()
        task_filter = "Tablice (Pose)"
        if "Pojazdy" in category: task_filter = "Pojazdy (Detect)"
        elif "Znaki" in category: task_filter = "Znaki/Litery (Detect)"
        
        filtered_entries = [e for e in entries if getattr(e, 'task_type', '') == task_filter]
        filtered_entries.sort(key=lambda x: getattr(x, 'f1_score', 0), reverse=True)

        for i, rep in enumerate(filtered_entries):
            score = f"{getattr(rep, 'f1_score', 0):.3f}"
            self.rank_tree.insert("", tk.END, values=(
                i+1, 
                getattr(rep, 'model_name', 'Nieznany'), 
                getattr(rep, 'task_type', 'unknown'),
                score, 
                f"{getattr(rep, 'precision', 0):.3f}", 
                f"{getattr(rep, 'recall', 0):.3f}"
            ))

    def _run_ranking(self):
        if self.rank_is_running: return
        models_dir = Path(self.rank_models_dir.get().strip())
        data_dir = Path(self.rank_data_dir.get().strip())
        
        if not models_dir.exists() or not data_dir.exists():
            return messagebox.showerror("Błąd", "Sprawdź ścieżki do modeli i folderu z obrazami testowymi!")

        gt_xml = data_dir / "annotations.xml"
        if not gt_xml.exists():
            return messagebox.showerror("Błąd", f"W folderze testowym brakuje pliku annotations.xml (Ground Truth):\n{gt_xml}")

        category = self.rank_category_var.get()
        target_task = "Tablice (Pose)"
        if "Pojazdy" in category: target_task = "Pojazdy (Detect)"
        elif "Znaki" in category: target_task = "Znaki/Litery (Detect)"
        
        is_pose_task = ("Pose" in target_task)

        self.rank_is_running = True
        self.btn_run_rank.config(state=tk.DISABLED, text="Testowanie modeli...")
        self.rank_progress_var.set(0)

        def worker():
            from ..ranking.annotation_comparator import AnnotationComparator
            from ..annotators import VehicleAnnotator, PlateAnnotator
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
                    
                    if is_pose_task: annotator = PlateAnnotator(model_path, conf_thresh, device)
                    else: annotator = VehicleAnnotator(model_path, conf_thresh, device)
                        
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
