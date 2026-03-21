#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka Treningu: Dataset Builder + Trening YOLO + Walidacja + Ranking Modelów.
"""

from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


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
        # ✅ ZMIANA: kontekst aktywnego projektu (ustawiany przez Wizard)
        self._campaign_runs_dir = None
        self._campaign_datasets_dir = None
        self._plots_paths = []
        self._plot_photo = None
        self._plot_img_id = None
        self._plot_original_path = None
        
        self.val_is_running = False
        self.rank_is_running = False

        self._build_ui()
        self._attach_training_log_handlers()  # ✅ ZMIANA
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

        # ✅ ZMIANA: handler dla naszego loggera
        self._gui_app_log_handler = GuiLogHandler(self)
        self._gui_app_log_handler.setFormatter(fmt)
        logger.addHandler(self._gui_app_log_handler)

        # ✅ ZMIANA: handler dla loggera Ultralytics
        self._gui_yolo_log_handler = GuiLogHandler(self)
        self._gui_yolo_log_handler.setFormatter(fmt)

        self._ultralytics_logger = logging.getLogger("ultralytics")
        self._ultralytics_logger.addHandler(self._gui_yolo_log_handler)

        self._training_log_handlers_attached = True
        
        #Konteksty katalogów
        #=================================

    def _get_datasets_base_dir(self) -> Path:
        """✅ ZMIANA: bazowy katalog datasetów dla aktywnego projektu lub globalny fallback."""
        if self._campaign_datasets_dir:
            return Path(self._campaign_datasets_dir)
        return Path(CONFIG.DEFAULT_DATASETS_DIR)

    def _get_runs_base_dir(self) -> Path:
        """✅ ZMIANA: bazowy katalog runów treningowych dla aktywnego projektu lub globalny fallback."""
        if self._campaign_runs_dir:
            return Path(self._campaign_runs_dir)
        return Path(CONFIG.DEFAULT_TRAINING_DIR)
    
    #=====================================

    def set_campaign_context(self, runs_dir=None, datasets_dir=None):
        """
        ✅ ZMIANA: przełącza TrainingTab na katalogi aktywnego projektu.
        - runs_dir: katalog projektu 5_training_runs
        - datasets_dir: katalog projektu 4_training_datasets

        Działanie:
        1. zapisuje kontekst katalogów projektu,
        2. przełącza historię treningów na katalog projektu,
        3. tworzy nowy obiekt trenera spięty z nową historią,
        4. ponownie podpina callbacki UI,
        5. odświeża historię i czyści bieżący stan podglądu.
        """
        # ------------------------------------------------------
        # Krok 1: zapamiętaj katalog datasetów projektu
        # ------------------------------------------------------
        if datasets_dir is not None:
            self._campaign_datasets_dir = str(Path(datasets_dir))

        # ------------------------------------------------------
        # Krok 2: jeśli nie podano runs_dir, nic więcej nie rób
        # ------------------------------------------------------
        if runs_dir is None:
            return

        new_runs_dir = Path(runs_dir)

        # ------------------------------------------------------
        # Krok 3: nie przełączaj kontekstu w trakcie aktywnego treningu
        # ------------------------------------------------------
        if getattr(self.trainer, "is_training", False):
            logger.warning("Nie można zmienić kontekstu projektu podczas aktywnego treningu.")
            return

        # ------------------------------------------------------
        # Krok 4: jeśli kontekst runów jest już taki sam, tylko odśwież historię
        # ------------------------------------------------------
        if self._campaign_runs_dir == str(new_runs_dir):
            self._load_history()
            return

        # ------------------------------------------------------
        # Krok 5: zapisz nowy katalog runów projektu
        # ------------------------------------------------------
        self._campaign_runs_dir = str(new_runs_dir)
        new_runs_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------
        # Krok 6: przełącz historię treningów na katalog projektu
        # ------------------------------------------------------
        self.history = TrainingHistory(history_dir=new_runs_dir)

        # ------------------------------------------------------
        # Krok 7: utwórz nowy trener spięty z projektową historią
        # ------------------------------------------------------
        self.trainer = YOLOPoseTrainer(history=self.history)

        # ------------------------------------------------------
        # Krok 8: ponownie podepnij callbacki do nowego obiektu trenera
        # ------------------------------------------------------
        self._bind_trainer_callbacks()

        # ------------------------------------------------------
        # Krok 9: wyczyść lokalny stan zakładki związany z poprzednim projektem
        # ------------------------------------------------------
        self.current_run_id = None
        self._plots_paths = []
        self._plot_original_path = None
        self._plot_photo = None
        self._plot_img_id = None

        try:
            self.plots_list.delete(0, tk.END)
        except Exception:
            pass

        try:
            self.tree.selection_remove(*self.tree.selection())
        except Exception:
            pass

        # ------------------------------------------------------
        # Krok 10: odśwież historię z nowego katalogu projektu
        # ------------------------------------------------------
        self._load_history()

        logger.info(f"TrainingTab przełączony na projektowy katalog runów: {new_runs_dir}")

    def clear_campaign_context(self):
        """
        ✅ ZMIANA: czyści projektowy kontekst treningu i wraca do globalnych katalogów Workspace.
        """
        self._campaign_runs_dir = None
        self._campaign_datasets_dir = None

        # przywróć globalną historię
        self.history = TrainingHistory(history_dir=Path(CONFIG.DEFAULT_TRAINING_DIR))
        self.trainer = YOLOPoseTrainer(history=self.history)
        self._bind_trainer_callbacks()

        # wyczyść pola ścieżek zależnych od projektu
        self.split_src_var.set("")
        self.split_out_var.set(f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]")
        self.dataset_var.set("")
        self.ds_out_var.set(f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/Plates_CVAT_[DATA_I_CZAS]")

        self.current_run_id = None
        self._plots_paths = []
        self._plot_original_path = None

        try:
            self.plots_list.delete(0, tk.END)
        except Exception:
            pass

        self._load_history()
    
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
        # Tkinter zjadł podkreślenie? Nieważne. Zamieniamy na stringa.
        corrupted_id = str(item["values"][0])
        
        # ✅ PANCERNE SZUKANIE: Porównujemy klucze bez żadnych znaków specjalnych
        for db_key, run_obj in self.history.runs.items():
            # Usuwamy wszystko co nie jest literą/cyfrą do sprawdzenia (np. z 2026_03 robimy 202603)
            clean_db_key = "".join(filter(str.isalnum, db_key))
            clean_ui_key = "".join(filter(str.isalnum, corrupted_id))
            
            # Jeśli "rdzeń" klucza się zgadza, to znaczy że znaleźliśmy nasz trening!
            if clean_db_key == clean_ui_key:
                return run_obj
                
        # Fallback (Gdyby jakoś to zawiodło)
        return None

    def _build_ui(self):


        # Główny notatnik powyżej paska pomocy
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tab_dataset = ttk.Frame(self.main_nb)
        self.tab_train = ttk.Frame(self.main_nb)
        self.tab_val = ttk.Frame(self.main_nb)
        self.tab_ranking = ttk.Frame(self.main_nb)

        self.main_nb.add(self.tab_dataset, text="1. Budowa Datasetu")
        self.main_nb.add(self.tab_train, text="2. Trening Modelu")
        self.main_nb.add(self.tab_val, text="3. Walidacja / Test Modelu")
        self.main_nb.add(self.tab_ranking, text=f"{self.icon_manager.get('trophy')} 4. Ranking Modelów")

        self._build_dataset_tab()
        self._build_train_tab()
        self._build_validation_tab()
        self._build_ranking_tab()

    def _build_dataset_tab(self):
        self.ds_pane = ttk.PanedWindow(self.tab_dataset, orient=tk.VERTICAL)
        self.ds_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.ds_creator_frame = ttk.LabelFrame(self.ds_pane, text=" Opcja A: Budowa Datasetu Tablic (Z XML CVAT) ", padding=10)
        self.ds_split_frame = ttk.LabelFrame(self.ds_pane, text=" Opcja B: Podział Gotowego Datasetu (np. Mega-Dataset Znaków) ", padding=10)
        self.ds_pane.add(self.ds_creator_frame, weight=1)
        self.ds_pane.add(self.ds_split_frame, weight=1)

        self._build_creator_ui()
        self._build_splitter_ui()

    def _build_creator_ui(self):
        f = self.ds_creator_frame
        ttk.Label(f, text="Tworzy strukturę YOLO Pose z wyeksportowanego pliku annotations.xml", font=("Arial", 9, "italic")).pack(anchor=tk.W, pady=(0, 10))
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
        ttk.Label(row3, text="Zapisze się do:").pack(side=tk.LEFT)
        # ✅ ZMIANA: Twardo zablokowana ścieżka z automatycznym, unikalnym dopiskiem (Plates_CVAT)
        self.ds_out_var = tk.StringVar(value=f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/Plates_CVAT_[DATA_I_CZAS]")
        ttk.Entry(row3, textvariable=self.ds_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # ✅ ZMIANA: Przycisk zyskał nazwę (btn_create), by można go było podpiąć pod pomoc
        btn_create = ttk.Button(f, text="Stwórz Dataset", command=self._create_dataset_thread)
        btn_create.pack(anchor=tk.W, pady=(10, 5))
        
        self.ds_progress_var = tk.DoubleVar(value=0.0)
        self.ds_progress = ttk.Progressbar(f, variable=self.ds_progress_var, maximum=100)
        self.ds_progress.pack(fill=tk.X, pady=2)
        
        self.ds_status = ttk.Label(f, text="Gotowy", foreground="green")
        self.ds_status.pack(anchor=tk.W)

        # ✅ PODPIĘCIE POMOCY DO OPCJI A (BUDOWA Z CVAT)
        HELP.bind_help(row1, "tr_cvat_xml")
        HELP.bind_help(row2, "tr_cvat_img")
        HELP.bind_help(btn_create, "tr_cvat_btn") # Teraz HELP wie, pod jaki przycisk się podpiąć!

    def _build_splitter_ui(self):
        f = self.ds_split_frame
        ttk.Label(f, text="Dzieli zbiór (np. wygenerowany w Zakładce Znaków) na foldery train/val potrzebne dla maszyny.", font=("Arial", 9, "italic")).pack(anchor=tk.W, pady=(0, 10))
        
        row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Źródło (np. Mega-Dataset):").pack(side=tk.LEFT)
        self.split_src_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.split_src_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row1, text="Wybierz", command=lambda: self._pick_dir(self.split_src_var)).pack(side=tk.LEFT)

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Wynik Podziału:").pack(side=tk.LEFT)
        # ✅ ZMIANA: Twardo zablokowana ścieżka z automatycznym, unikalnym dopiskiem (Split)
        self.split_out_var = tk.StringVar(value=f"{Path(CONFIG.DEFAULT_DATASETS_DIR)}/[NAZWA_ZRODLA]_Split_[DATA_I_CZAS]")
        ttk.Entry(row2, textvariable=self.split_out_var, state="readonly", foreground="gray").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        ratios = ttk.Frame(f); ratios.pack(fill=tk.X, pady=10)
        ttk.Label(ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
        self.train_pct = tk.DoubleVar(value=80.0)
        ttk.Scale(ratios, from_=50, to=95, variable=self.train_pct, command=lambda e: self._update_ratio_labels()).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.train_lbl = ttk.Label(ratios, text="80%"); self.train_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
        self.val_pct = tk.DoubleVar(value=20.0)
        ttk.Scale(ratios, from_=5, to=50, variable=self.val_pct, command=lambda e: self._update_ratio_labels()).grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.val_lbl = ttk.Label(ratios, text="20%"); self.val_lbl.grid(row=1, column=2, sticky=tk.W)

        self.use_test = tk.BooleanVar(value=False)
        ttk.Checkbutton(ratios, text="Wydziel też zbiór Testowy", variable=self.use_test, command=self._update_ratio_labels).grid(row=2, column=0, columnspan=2, sticky=tk.W)
        self.test_lbl = ttk.Label(ratios, text="Test: 0%"); self.test_lbl.grid(row=2, column=2, sticky=tk.W)
        ratios.columnconfigure(1, weight=1)

        btn_split = ttk.Button(f, text="Rozpocznij Podział (Split)", command=self._split_dataset_thread, style="Accent.TButton")
        btn_split.pack(anchor=tk.W, pady=10)
        
        self.split_progress_var = tk.DoubleVar(value=0.0)
        self.split_progress = ttk.Progressbar(f, variable=self.split_progress_var, maximum=100)
        self.split_progress.pack(fill=tk.X, pady=2)
        self.split_status = ttk.Label(f, text="Gotowy")
        self.split_status.pack(anchor=tk.W)

        # ✅ PODPIĘCIE POMOCY:
        HELP.bind_help(row1, "tr_split_src")
        HELP.bind_help(ratios, "tr_split_ratios")
        HELP.bind_help(btn_split, "tr_split_btn")

    def _build_train_tab(self):
        self.train_pane = ttk.PanedWindow(self.tab_train, orient=tk.HORIZONTAL)
        self.train_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.left = ttk.LabelFrame(self.train_pane, text=" Konfiguracja Treningu ", padding=10)
        self.right = ttk.LabelFrame(self.train_pane, text=" Historia i Wykresy ", padding=10)
        self.train_pane.add(self.left, weight=0)
        self.train_pane.add(self.right, weight=1)

        # =======================================================
        # NOWY UKŁAD: Dwie kolumny wewnątrz "Konfiguracji"
        # =======================================================
        settings_col = ttk.Frame(self.left)
        settings_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        console_col = ttk.Frame(self.left)
        console_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # --- KOLUMNA LEWA: Ustawienia ---
        # ✅ ZMIANA: Automatyczne generowanie nazwy treningu
        ttk.Label(settings_col, text="Nazwa sesji treningowej:").pack(anchor=tk.W)
        self.name_var = tk.StringVar()
        ttk.Entry(settings_col, textvariable=self.name_var, width=35).pack(fill=tk.X, pady=2)
        


        ttk.Label(settings_col, text="Gotowy Dataset (Katalog z data.yaml):").pack(anchor=tk.W, pady=(8, 0))
        self.dataset_var = tk.StringVar()
        ds_row = ttk.Frame(settings_col)
        ds_row.pack(fill=tk.X, pady=2)
        ttk.Entry(ds_row, textvariable=self.dataset_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(ds_row, text="Wybierz", command=lambda: self._pick_dir(self.dataset_var)).pack(side=tk.LEFT, padx=5)

        ttk.Label(settings_col, text="Architektura (Model Bazowy):").pack(anchor=tk.W, pady=(8, 0))
        self.base_model_var = tk.StringVar()
        
        base_values = list(AVAILABLE_DETECT_MODELS.keys()) + list(AVAILABLE_POSE_MODELS.keys()) + ["Custom"]
        
        self.base_combo = ttk.Combobox(settings_col, textvariable=self.base_model_var, values=base_values, state="readonly")
        self.base_combo.pack(fill=tk.X, pady=2)
        self.base_model_var.set("yolo11n.pt") 
        self.base_combo.bind("<<ComboboxSelected>>", lambda e: self._on_base_model_change())

        # ✅ ZMIANA: Dodano wiersz z przyciskiem do wyboru modelu Fine-Tuningu (.pt) z folderu 6_models
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

        self.btn_start_train = ttk.Button(settings_col, text="▶ ROZPOCZNIJ TRENING", command=self._start_training, style="Accent.TButton")
        self.btn_start_train.pack(fill=tk.X, pady=(15, 5), ipady=6)
        
        self.btn_stop_train = ttk.Button(settings_col, text="ZATRZYMAJ", command=self._stop_training, state=tk.DISABLED)
        self.btn_stop_train.pack(fill=tk.X, pady=2)

        self.train_progress_var = tk.DoubleVar(value=0.0)
        self.train_progress = ttk.Progressbar(settings_col, variable=self.train_progress_var, maximum=100)
        self.train_progress.pack(fill=tk.X, pady=(15, 2))
        
        self.train_progress_label = ttk.Label(settings_col, text="Czekam na start...", font=("Segoe UI", 8, "italic"))
        self.train_progress_label.pack(anchor=tk.W)

        # --- KOLUMNA PRAWA: Terminal na żywo ---
        ttk.Label(console_col, text="Terminal Treningu (Live):", font=("Segoe UI", 9, "bold"), foreground="#2980b9").pack(anchor=tk.W, pady=(0, 2))
        
        self.train_log_console = scrolledtext.ScrolledText(
            console_col, width=50, height=18, font=("Consolas", 10), 
            bg="#1e1e1e", fg="#ecf0f1", bd=2, relief="sunken"
        )
        self.train_log_console.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.train_log_console.insert(tk.END, "Oczekuje na rozpoczęcie treningu...\nGotowy na dane z Ultralytics.\n")
        self.train_log_console.config(state=tk.DISABLED)

        # RIGHT: notebook historii (Prawa, wielka kolumna główna)
        self.right_nb = ttk.Notebook(self.right)
        self.right_nb.pack(fill=tk.BOTH, expand=True)

        self.hist_tab = ttk.Frame(self.right_nb)
        self.plots_tab = ttk.Frame(self.right_nb)
        self.right_nb.add(self.hist_tab, text="Historia Treningów")
        self.right_nb.add(self.plots_tab, text="Analiza (Wykresy)")

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
        ttk.Button(hist_btns, text="Otwórz Folder", command=self._open_run_folder).pack(side=tk.RIGHT)

        self._build_plots_ui()

        # ✅ PRZYWRÓCONE, ZABEZPIECZONE PODPIĘCIE POMOCY
        HELP.bind_help(ds_row, "tr_train_ds")
        HELP.bind_help(self.base_combo, "tr_train_base")
        
        # Ochrona na wypadek błędów siatki (Tkinter Grid)
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
        # ✅ ZMIANA: Podpięcie nowego przycisku pod system pomocy
        HELP.bind_help(self.custom_row, "tr_train_custom")

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

        # ✅ ZMIANA: Usunięto topbar z guzikami - i +. Od razu wrzucamy potężny ZoomableCanvas!
        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        # Inicjalizujemy ZoomableCanvas (ten sam co w przeglądarce tablic)
        self.plot_canvas = ZoomableCanvas(canvas_frame, bg="#ecf0f1", highlightthickness=0)
        self.plot_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_validation_tab(self):
        main_f = ttk.Frame(self.tab_val, padding=10)
        main_f.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_f, text="Sprawdź jakość dowolnego wytrenowanego modelu YOLO na zbiorze testowym.", font=("Segoe UI", 10, "italic")).pack(anchor=tk.W, pady=(0, 15))
        
        ttk.Label(main_f, text="Wytrenowany Model (.pt):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(5,2))
        row1 = ttk.Frame(main_f)
        row1.pack(fill=tk.X)
        self.val_model_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.val_model_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row1, text="Wybierz", command=lambda: self._pick_file(self.val_model_var, "*.pt")).pack(side=tk.RIGHT, padx=(5,0))
        
        ttk.Label(main_f, text="Dataset Testowy (data.yaml):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(15,2))
        row2 = ttk.Frame(main_f)
        row2.pack(fill=tk.X)
        self.val_data_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.val_data_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wybierz", command=lambda: self._pick_dir(self.val_data_var)).pack(side=tk.RIGHT, padx=(5,0))

        ttk.Label(main_f, text="Przetestuj na podzbiorze:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(15,2))
        self.val_split_var = tk.StringVar(value="val")
        ttk.Combobox(main_f, textvariable=self.val_split_var, values=["val", "test", "train"], state="readonly", width=15).pack(anchor=tk.W)

        ttk.Separator(main_f, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=20)
        
        self.btn_run_val = ttk.Button(main_f, text="🚀 PRZEPROWADŹ WALIDACJĘ", style="Accent.TButton", command=self._run_validation)
        self.btn_run_val.pack(anchor=tk.W, ipady=4)
        
        log_f = ttk.LabelFrame(main_f, text=" Wyniki Walidacji ", padding=5)
        log_f.pack(fill=tk.BOTH, expand=True, pady=(15,0))
        self.val_log_text = scrolledtext.ScrolledText(log_f, wrap=tk.WORD, font=("Consolas", 10), bg="#f8f9fa")
        self.val_log_text.pack(fill=tk.BOTH, expand=True)


        
        # ✅ PODPIĘCIE POMOCY:
        HELP.bind_help(row1, "tr_val_model")
        HELP.bind_help(row2, "tr_val_data")    # <-- Nowe (Dataset)
        HELP.bind_help(self.btn_run_val, "tr_val_btn")
        
        # Bezpieczne łapanie Comboboxa (szuka po klasie)
        for child in main_f.winfo_children():
            if isinstance(child, ttk.Combobox):
                HELP.bind_help(child, "tr_val_split") # <-- Nowe (Combo)

    def _build_ranking_tab(self):
        pane = ttk.PanedWindow(self.tab_ranking, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        left_f = ttk.LabelFrame(pane, text=" Testowane Modele ", padding=10)
        right_f = ttk.LabelFrame(pane, text=" Tabela Wyników ", padding=10)
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

        # ✅ PODPIĘCIE POMOCY:
        HELP.bind_help(cat_combo, "tr_rank_cat")
        HELP.bind_help(self.btn_run_rank, "tr_rank_btn")

    # ✅ ZMIANA: Obsługa domyślnego folderu startowego (initialdir)
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
        test = max(0.0, 100.0 - train - val) if self.use_test.get() else 0.0
        if self.use_test.get() and train + val > 100.0:
            val = max(5.0, 100.0 - train)
            self.val_pct.set(val)
            test = max(0.0, 100.0 - train - val)
        self.train_lbl.configure(text=f"{train:.0f}%")
        self.val_lbl.configure(text=f"{val:.0f}%")
        self.test_lbl.configure(text=f"Test: {test:.0f}%")

    # ✅ ZMIANA: Zabezpieczone włączanie i wyłączanie guzika Custom
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

        # ✅ ZMIANA: katalog datasetów zależny od kampanii/projektu
        base_datasets_dir = self._get_datasets_base_dir()
        out_dir = base_datasets_dir / f"Plates_CVAT_{timestamp}"

        # ✅ ZMIANA: pokaż w UI faktyczną ścieżkę docelową
        self.ds_out_var.set(str(out_dir))

        # ✅ ZMIANA: zawsze parsujemy świeżo wskazany XML
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

        if self.use_test.get():
            ratios = {
                "train": train,
                "val": val,
                "test": max(0.0, 1.0 - train - val)
            }
        else:
            denom = max(0.0001, train + val)
            ratios = {
                "train": train / denom,
                "val": val / denom
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
                        text="Dataset utworzony!",
                        foreground="green"
                    ))
                    self._ui(lambda: messagebox.showinfo("Sukces", msg2))

                    # ✅ ZMIANA: po sukcesie od razu podstaw gotowy dataset do sekcji Treningu
                    self._ui(lambda p=str(out_dir): self.dataset_var.set(p))
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
        # ✅ ZMIANA: jawnie definiujemy źródło splitu
        src = Path(self.split_src_var.get().strip())

        if not src.exists() or not (src / "images").exists():
            return messagebox.showerror(
                "Błąd",
                "Brak folderu wejściowego (lub brakuje w nim folderu 'images')."
            )

        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # ✅ ZMIANA: wynik splitu zapisujemy w katalogu datasetów aktywnego projektu
        base_datasets_dir = self._get_datasets_base_dir()
        out = base_datasets_dir / f"{src.name}_Split_{timestamp}"

        # ✅ ZMIANA: pokaż w UI faktyczną ścieżkę wyniku
        self.split_out_var.set(str(out))

        train = float(self.train_pct.get()) / 100.0
        val = float(self.val_pct.get()) / 100.0

        if self.use_test.get():
            ratios = {
                "train": train,
                "val": val,
                "test": max(0.0, 1.0 - train - val)
            }
        else:
            denom = max(0.0001, train + val)
            ratios = {
                "train": train / denom,
                "val": val / denom
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

                    # ✅ ZMIANA: po udanym splicie od razu podstaw gotowy dataset do sekcji Treningu
                    self._ui(lambda p=str(out): self.dataset_var.set(p))
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
        
        # ✅ ZMIANA: czyścimy terminal live przed nowym treningiem
        self.train_log_console.config(state=tk.NORMAL)
        self.train_log_console.delete(1.0, tk.END)
        self.train_log_console.insert(tk.END, "Uruchamianie treningu...\n")
        self.train_log_console.config(state=tk.DISABLED)

        ds = self.dataset_var.get().strip()
        if not ds:
            return messagebox.showerror("Błąd", "Podaj Dataset.")

        ds_path = Path(ds)
        yaml_path = ds_path / "data.yaml" if ds_path.is_dir() else ds_path
        if not yaml_path.exists():
            return messagebox.showerror("Błąd", "Nie znaleziono pliku data.yaml.")

        # ✅ ZMIANA: rozpoznanie typu datasetu (POSE vs DETECT)
        try:
            cfg = safe_load_yaml(yaml_path)
            is_pose_dataset = "kpt_shape" in cfg
        except Exception as e:
            return messagebox.showerror("Błąd", f"Nie udało się odczytać data.yaml:\n{e}")

        base_key = self.base_model_var.get().strip()
        base_model = self.base_custom_var.get().strip() if base_key == "Custom" else base_key
        device = self._device_to_ultralytics(self.device_var.get())

        # ✅ ZMIANA: rozpoznanie typu modelu
        is_pose_model = False
        if base_key in AVAILABLE_POSE_MODELS:
            is_pose_model = True
        elif "pose" in str(base_model).lower():
            is_pose_model = True

        # ✅ ZMIANA: twarda walidacja zgodności dataset <-> model
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

        # ✅ ZMIANA: czytelny nagłówek sesji
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
            self.btn_start_train.configure(state=tk.DISABLED)
            self.btn_stop_train.configure(state=tk.NORMAL)
            self.train_progress_label.configure(text=f"Trening uruchomiony: {run_id}")

    def _stop_training(self):
        self.trainer.stop_training()
        self.btn_stop_train.configure(state=tk.DISABLED)

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
            # ✅ ZMIANA: komunikat końcowy też ląduje w terminalu live
            end_line = f"[KONIEC] {'SUKCES' if success else 'BŁĄD/STOP'} | {msg}"
            self._append_train_log(end_line)

            self._ui(lambda: self.btn_start_train.configure(state=tk.NORMAL))
            self._ui(lambda: self.btn_stop_train.configure(state=tk.DISABLED))
            self._ui(lambda: self._load_history())

    def _load_history(self):
        self.tree.delete(*self.tree.get_children())
        for run in self.history.get_all_runs():
            # ✅ ZMIANA: Twardo wstawiamy pełne run.id. Zabezpiecza to klikanie i wyszukiwanie folderów.
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
            
        # Szukamy wykresów wygenerowanych przez Ultralytics
        paths = list(run_dir.rglob("*.png")) + list(run_dir.rglob("*.jpg"))
        
        # Filtrujemy tylko wartościowe obrazki (odrzucamy np. surowe zdjęcia z batchy, zostawiamy analizy)
        self._plots_paths = [p for p in paths if "plot" in p.name.lower() or "confusion" in p.name.lower() or "val" in p.name.lower()]
        
        # Wrzucamy nazwy wykresów na listę UI po lewej stronie
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
            
            # ✅ ZMIANA: Nie musimy przeliczać zooma ręcznie. ZoomableCanvas sam to robi!
            # Po prostu ładujemy obrazek (najlepiej ze zmienioną flagą na wysoką jakość w pamięci)
            self.plot_canvas.set_image(img)
            
            # Resetujemy zoom do 1.0 przy ładowaniu nowego zdjęcia (opcjonalne, ale wygodne)
            self.plot_canvas.reset_view()
        except Exception as e: 
            logger.error(f"Nie udało się wyświetlić wykresu: {e}")

    # ✅ ZMIANA: Ta stara funkcja była od przycisków + i -, więc możemy ją usunąć, ale wstawmy dla bezpieczeństwa "dummy" metodę, by uniknąć ewentualnego błędu w pamięci Tkintera.
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
        self.val_log_text.delete(1.0, tk.END)
        self.val_log_text.insert(tk.END, f"Inicjalizowanie silnika YOLO do ewaluacji...\nModel: {Path(model_path).name}\nDataset: {Path(data_path).parent.name}\n\n")

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
                        
                self._ui(lambda r=res: self.val_log_text.insert(tk.END, r))
                self._ui(lambda: messagebox.showinfo("Sukces", "Walidacja zakończona pomyślnie!"))
                
            except Exception as e:
                self._ui(lambda err=e: self.val_log_text.insert(tk.END, f"\nBŁĄD WALIDACJI:\n{err}"))
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