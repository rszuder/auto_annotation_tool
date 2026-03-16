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

# Autentyczny import Rankingu!
from ..ranking import ModelRanking, ModelRankingEntry

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

        # Backend
        self.trainer = YOLOPoseTrainer()
        self.history: TrainingHistory = self.trainer.history
        self.creator = DatasetCreator()
        self.splitter = DatasetSplitter()
        self.ranking_engine = ModelRanking()

        self.current_run_id = None

        # Plot preview state
        self._plots_paths = []
        self._plot_photo = None
        self._plot_img_id = None
        self._plot_original_path = None
        
        self.val_is_running = False
        self.rank_is_running = False

        self._build_ui()
        self._bind_trainer_callbacks()
        self._load_history()
        self._load_ranking()
        self._on_base_model_change()

    # ============================================================
    # Helpers
    # ============================================================
    def _ui(self, fn):
        self.frame.after(0, fn)

    def _get_available_devices(self):
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    name = torch.cuda.get_device_name(i)
                    devices.append(f"cuda:{i} ({name})")
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
            if os.name == "nt":
                os.startfile(str(path))
            else:
                webbrowser.open(path.as_uri())
        except Exception as e:
            messagebox.showinfo("Info", f"Nie mogę otworzyć: {path}\n\n{e}")

    def _selected_run(self):
        sel = self.tree.selection()
        if not sel: return None
        item = self.tree.item(sel[0])
        short_id = str(item["values"][0])
        full_run_id = next((r.id for r in self.history.get_all_runs() if r.id.endswith(short_id)), None)
        return self.history.get_run(full_run_id) if full_run_id else None

    # ============================================================
    # MAIN UI
    # ============================================================
    def _build_ui(self):
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

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

    # ------------------------------------------------------------
    # 1. DATASET TAB
    # ------------------------------------------------------------
    def _build_dataset_tab(self):
        info = ttk.LabelFrame(self.tab_dataset, text="Wskazówka", padding=8)
        info.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(info, text=(
            "Aby stworzyć dataset do treningu YOLO:\n"
            "• Eksportuj zaznaczone dane z CVAT jako plik XML\n"
            "• Wskaż folder ze zdjęciami\n"
            "Ustaw proporcje i kliknij 'Stwórz dataset'."
        ), justify=tk.LEFT).pack(fill=tk.X, expand=True)

        self.ds_pane = ttk.PanedWindow(self.tab_dataset, orient=tk.VERTICAL)
        self.ds_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.ds_creator_frame = ttk.LabelFrame(self.ds_pane, text=" Generator Datasetu z CVAT ", padding=10)
        self.ds_split_frame = ttk.LabelFrame(self.ds_pane, text=" Splitter Istniejącego Datasetu ", padding=10)
        self.ds_pane.add(self.ds_creator_frame, weight=1)
        self.ds_pane.add(self.ds_split_frame, weight=1)

        self._build_creator_ui()
        self._build_splitter_ui()

    def _build_creator_ui(self):
        f = self.ds_creator_frame
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
        ttk.Label(row3, text="Wyjście (dataset):").pack(side=tk.LEFT)
        self.ds_out_var = tk.StringVar(value=str(Path(CONFIG.DEFAULT_DATASETS_DIR) / "yolo_dataset"))
        ttk.Entry(row3, textvariable=self.ds_out_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row3, text="Wybierz", command=lambda: self._pick_dir(self.ds_out_var)).pack(side=tk.LEFT)

        ratios = ttk.Frame(f); ratios.pack(fill=tk.X, pady=6)
        ttk.Label(ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
        self.train_pct = tk.DoubleVar(value=80.0)
        ttk.Scale(ratios, from_=50, to=95, variable=self.train_pct, command=lambda e: self._update_ratio_labels()).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.train_lbl = ttk.Label(ratios, text="80%"); self.train_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
        self.val_pct = tk.DoubleVar(value=20.0)
        ttk.Scale(ratios, from_=5, to=50, variable=self.val_pct, command=lambda e: self._update_ratio_labels()).grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.val_lbl = ttk.Label(ratios, text="20%"); self.val_lbl.grid(row=1, column=2, sticky=tk.W)

        self.use_test = tk.BooleanVar(value=False)
        ttk.Checkbutton(ratios, text="Test (resztka %)", variable=self.use_test, command=self._update_ratio_labels).grid(row=2, column=0, columnspan=2, sticky=tk.W)
        self.test_lbl = ttk.Label(ratios, text="Test: 0%"); self.test_lbl.grid(row=2, column=2, sticky=tk.W)
        ratios.columnconfigure(1, weight=1)

        ttk.Button(f, text="Stwórz Dataset", command=self._create_dataset_thread, style="Accent.TButton").pack(anchor=tk.W, pady=5)
        self.ds_progress_var = tk.DoubleVar(value=0.0)
        self.ds_progress = ttk.Progressbar(f, variable=self.ds_progress_var, maximum=100)
        self.ds_progress.pack(fill=tk.X, pady=2)
        self.ds_status = ttk.Label(f, text="Gotowy", foreground="green")
        self.ds_status.pack(anchor=tk.W)

    def _build_splitter_ui(self):
        f = self.ds_split_frame
        row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Źródło (Dataset):").pack(side=tk.LEFT)
        self.split_src_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.split_src_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row1, text="Wybierz", command=lambda: self._pick_dir(self.split_src_var)).pack(side=tk.LEFT)

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Wynik (Nowy Podział):").pack(side=tk.LEFT)
        self.split_out_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.split_out_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row2, text="Wybierz", command=lambda: self._pick_dir(self.split_out_var)).pack(side=tk.LEFT)
        
        ttk.Button(f, text="Rozpocznij Podział", command=self._split_dataset_thread).pack(anchor=tk.W, pady=10)
        self.split_status = ttk.Label(f, text="Gotowy")
        self.split_status.pack(anchor=tk.W)

    # ------------------------------------------------------------
    # 2. TRAIN TAB
    # ------------------------------------------------------------
    def _build_train_tab(self):
        self.train_pane = ttk.PanedWindow(self.tab_train, orient=tk.HORIZONTAL)
        self.train_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.left = ttk.LabelFrame(self.train_pane, text=" Konfiguracja Treningu ", padding=10)
        self.right = ttk.LabelFrame(self.train_pane, text=" Historia i Wykresy ", padding=10)
        self.train_pane.add(self.left, weight=0)
        self.train_pane.add(self.right, weight=1)

        ttk.Label(self.left, text="Nazwa sesji treningowej:").pack(anchor=tk.W)
        self.name_var = tk.StringVar(value="YOLO_Training_Run")
        ttk.Entry(self.left, textvariable=self.name_var).pack(fill=tk.X, pady=2)

        ttk.Label(self.left, text="Dataset (Katalog zawierający data.yaml):").pack(anchor=tk.W, pady=(8, 0))
        self.dataset_var = tk.StringVar()
        ds_row = ttk.Frame(self.left)
        ds_row.pack(fill=tk.X, pady=2)
        ttk.Entry(ds_row, textvariable=self.dataset_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(ds_row, text="Wybierz", command=lambda: self._pick_dir(self.dataset_var)).pack(side=tk.LEFT, padx=5)

        ttk.Label(self.left, text="Architektura (Model Bazowy):").pack(anchor=tk.W, pady=(8, 0))
        self.base_model_var = tk.StringVar()
        base_values = ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11n-pose.pt", "yolo11s-pose.pt", "Custom"]
        self.base_combo = ttk.Combobox(self.left, textvariable=self.base_model_var, values=base_values, state="readonly")
        self.base_combo.pack(fill=tk.X, pady=2)
        self.base_model_var.set(base_values[4])
        self.base_combo.bind("<<ComboboxSelected>>", lambda e: self._on_base_model_change())

        self.base_custom_var = tk.StringVar()
        self.base_custom_entry = ttk.Entry(self.left, textvariable=self.base_custom_var, state=tk.DISABLED)
        self.base_custom_entry.pack(fill=tk.X, pady=2)
        
        grid = ttk.Frame(self.left)
        grid.pack(fill=tk.X, pady=10)
        ttk.Label(grid, text="Epoki:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.epochs_var = tk.IntVar(value=100)
        ttk.Spinbox(grid, from_=1, to=5000, textvariable=self.epochs_var, width=8).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Batch Size:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.batch_var = tk.IntVar(value=16)
        ttk.Spinbox(grid, from_=1, to=256, textvariable=self.batch_var, width=8).grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Device:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.device_var = tk.StringVar(value="auto")
        ttk.Combobox(grid, textvariable=self.device_var, values=self._get_available_devices(), state="readonly", width=15).grid(row=2, column=1, sticky=tk.W, padx=5)

        self.btn_start_train = ttk.Button(self.left, text="▶ ROZPOCZNIJ TRENING", command=self._start_training, style="Accent.TButton")
        self.btn_start_train.pack(fill=tk.X, pady=10, ipady=4)
        self.btn_stop_train = ttk.Button(self.left, text="ZATRZYMAJ", command=self._stop_training, state=tk.DISABLED)
        self.btn_stop_train.pack(fill=tk.X, pady=2)

        self.train_progress_var = tk.DoubleVar(value=0.0)
        self.train_progress = ttk.Progressbar(self.left, variable=self.train_progress_var, maximum=100)
        self.train_progress.pack(fill=tk.X, pady=(15, 2))
        self.train_progress_label = ttk.Label(self.left, text="Czekam na start...")
        self.train_progress_label.pack(anchor=tk.W)

        # RIGHT: notebook historii
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
        self.tree.column("ID", width=80, stretch=False)
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

    def _build_plots_ui(self):
        self.plots_pane = ttk.PanedWindow(self.plots_tab, orient=tk.HORIZONTAL)
        self.plots_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(self.plots_pane)
        right = ttk.Frame(self.plots_pane)
        self.plots_pane.add(left, weight=1)
        self.plots_pane.add(right, weight=3)

        self.plots_list = tk.Listbox(left, height=12)
        self.plots_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.plots_list.bind("<<ListboxSelect>>", self._on_plot_selected)

        topbar = ttk.Frame(right)
        topbar.pack(fill=tk.X)
        ttk.Label(topbar, text="Powiększenie:").pack(side=tk.LEFT)
        self.zoom_var = tk.DoubleVar(value=1.0)
        ttk.Button(topbar, text="-", width=3, command=lambda: self._change_zoom(0.8)).pack(side=tk.LEFT, padx=2)
        ttk.Button(topbar, text="+", width=3, command=lambda: self._change_zoom(1.25)).pack(side=tk.LEFT, padx=2)

        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        self.plot_canvas = tk.Canvas(canvas_frame, background="#ecf0f1")
        self.plot_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------
    # 3. WALIDACJA MODELI (Ewaluacja) TAB
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # 4. RANKING TAB (Z PODZIAŁEM NA KATEGORIE)
    # ------------------------------------------------------------
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

        # Tabela w prawej kolumnie
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

    # ============================================================
    # Logika Metod Współdzielonych
    # ============================================================
    def _pick_file(self, var, ext):
        p = filedialog.askopenfilename(filetypes=[("File", ext)])
        if p: var.set(p)
        
    def _pick_dir(self, var):
        p = filedialog.askdirectory()
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

    def _on_base_model_change(self):
        if self.base_model_var.get() == "Custom":
            self.base_custom_entry.configure(state=tk.NORMAL)
        else:
            self.base_custom_entry.configure(state=tk.DISABLED)

    # ============================================================
    # LOGIKA - BUDOWA DATASETU
    # ============================================================
    def _create_dataset_thread(self):
        xml = Path(self.cvat_xml_var.get().strip())
        images_dir = Path(self.cvat_images_var.get().strip())
        out_dir = Path(self.ds_out_var.get().strip())

        if not xml.exists(): return messagebox.showerror("Błąd", "XML nie istnieje.")
        if not images_dir.exists(): return messagebox.showerror("Błąd", "Folder images nie istnieje.")

        if not self.creator.annotations:
            ok, msg, _ = self.creator.parse_cvat_xml(xml)
            if not ok: return messagebox.showerror("Błąd", msg)

        train = float(self.train_pct.get()) / 100.0
        val = float(self.val_pct.get()) / 100.0
        ratios = {"train": train, "val": val, "test": max(0, 1.0 - train - val)} if self.use_test.get() else {"train": train / max(0.0001, train + val), "val": val / max(0.0001, train + val)}

        def worker():
            def prog(c, t, n):
                self._ui(lambda: self.ds_progress_var.set((c/t)*100))
                self._ui(lambda: self.ds_status.configure(text=f"{c}/{t} obrazów..."))
            ok, msg, _ = self.creator.create_dataset(images_dir, out_dir, ratios, prog)
            self._ui(lambda: messagebox.showinfo("Info", msg))
            self._ui(lambda: self.ds_status.configure(text="Zakończono!"))
            
        threading.Thread(target=worker, daemon=True).start()

    def _split_dataset_thread(self):
        messagebox.showinfo("Splitter", "Podłącz swoją klasę DatasetSplitter w tej funkcji.")

    # ============================================================
    # LOGIKA - TRENING
    # ============================================================
    def _start_training(self):
        if not YOLO_AVAILABLE: return messagebox.showerror("Błąd", "Brak ultralytics.")
        ds = self.dataset_var.get().strip()
        if not ds: return messagebox.showerror("Błąd", "Podaj Dataset.")
        
        base_key = self.base_model_var.get()
        base_model = self.base_custom_var.get() if base_key == "Custom" else base_key
        device = self._device_to_ultralytics(self.device_var.get())

        run_id = self.trainer.start_training(
            name=self.name_var.get(), dataset_path=ds, base_model=base_model,
            epochs=int(self.epochs_var.get()), batch_size=int(self.batch_var.get()),
            img_size=int(self.imgsz_var.get()), device=device,
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
            self._ui(lambda: self.train_progress_var.set(pct))
            self._ui(lambda: self.train_progress_label.configure(text=f"Epoka {epoch}/{run.epochs} | mAP={metrics.get('map50',0):.3f}"))
        def on_end(success, msg):
            self._ui(lambda: self.btn_start_train.configure(state=tk.NORMAL))
            self._ui(lambda: self.btn_stop_train.configure(state=tk.DISABLED))
            self._ui(lambda: self._load_history())
        self.trainer.on_epoch_end = on_epoch
        self.trainer.on_training_end = on_end

    def _load_history(self):
        self.tree.delete(*self.tree.get_children())
        for run in self.history.get_all_runs():
            self.tree.insert("", tk.END, values=(
                run.id[-8:], run.name[:30], run.status, f"{run.current_epoch}/{run.epochs}", f"{run.best_map50:.3f}", run.duration_str
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

    # Wykresy i Plots
    def _on_run_selected(self, event=None):
        run = self._selected_run()
        if not run: return
        run_dir = Path(run.output_dir)
        paths = list(run_dir.rglob("*.png")) + list(run_dir.rglob("*.jpg"))
        self._plots_paths = [p for p in paths if "plot" in p.name.lower() or "confusion" in p.name.lower() or "val" in p.name.lower()]
        self.plots_list.delete(0, tk.END)
        for p in self._plots_paths: self.plots_list.insert(tk.END, p.name)

    def _on_plot_selected(self, event=None):
        sel = self.plots_list.curselection()
        if sel and self._plots_paths: self._show_plot(self._plots_paths[int(sel[0])])

    def _change_zoom(self, factor):
        self.zoom_var.set(max(0.1, min(float(self.zoom_var.get()) * factor, 8.0)))
        if self._plot_original_path: self._show_plot(Path(self._plot_original_path))

    def _show_plot(self, path):
        if not PIL_AVAILABLE: return
        try:
            self._plot_original_path = str(path)
            img = Image.open(path)
            w, h = img.size
            z = self.zoom_var.get()
            img = img.resize((int(w*z), int(h*z)), Image.Resampling.LANCZOS)
            self._plot_photo = ImageTk.PhotoImage(img)
            self.plot_canvas.delete("all")
            self.plot_canvas.create_image(0, 0, anchor=tk.NW, image=self._plot_photo)
        except: pass

        # ============================================================
    # LOGIKA - WALIDACJA
    # ============================================================
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
                # Uruchomienie oficjalnej walidacji YOLO na testowym/walidacyjnym zbiorze (YOLO samo znajdzie pliki yaml i etykiety)
                metrics = model.val(data=data_path, split=self.val_split_var.get())
                
                res = "\n=== OFICJALNE WYNIKI WALIDACJI YOLO ===\n"
                
                # YOLO Metrics object różni się w zależności od wersji (v8 vs v11)
                # Sprawdzamy czy ma wbudowany słownik z wynikami:
                if hasattr(metrics, 'results_dict'):
                    for k, v in metrics.results_dict.items(): 
                        res += f"• {k}: {v:.4f}\n"
                else:
                    # Alternatywne bezpieczne wyciąganie popularnych metryk, jeśli properties istnieją
                    if hasattr(metrics, 'box'):
                        res += f"• mAP50:     {metrics.box.map50:.4f}\n"
                        res += f"• mAP50-95:  {metrics.box.map:.4f}\n"
                        res += f"• Precision: {metrics.box.mp:.4f} (Mean Precision)\n"
                        res += f"• Recall:    {metrics.box.mr:.4f} (Mean Recall)\n"
                    elif hasattr(metrics, 'pose'): # Dla modeli Pose
                        res += f"• Pose mAP50: {metrics.pose.map50:.4f}\n"
                        res += f"• Pose mAP:   {metrics.pose.map:.4f}\n"
                        if hasattr(metrics, 'box'):
                            res += f"• Box mAP50:  {metrics.box.map50:.4f}\n"
                    else:
                        # Fallback jeśli API YOLO jest inne
                        res += str(metrics)
                        
                self._ui(lambda r=res: self.val_log_text.insert(tk.END, r))
                self._ui(lambda: messagebox.showinfo("Sukces", "Walidacja zakończona pomyślnie!"))
                
            except Exception as e:
                # Tutaj była ta pułapka z Lambdą! Przekazujemy 'e' twardo jako argument 'err=e'
                self._ui(lambda err=e: self.val_log_text.insert(tk.END, f"\nBŁĄD WALIDACJI:\n{err}"))
                logger.error(f"Validation error: {e}")
                
            finally:
                self.val_is_running = False
                self._ui(lambda: self.btn_run_val.config(state=tk.NORMAL, text="🚀 PRZEPROWADŹ WALIDACJĘ"))
                
        threading.Thread(target=worker, daemon=True).start()
    # ============================================================
    # LOGIKA - RANKING
    # ============================================================
    def _load_ranking(self):
        entries = getattr(self.ranking_engine, 'entries', [])
        self.rank_tree.delete(*self.rank_tree.get_children())
        
        category = self.rank_category_var.get()
        task_filter = "Tablice (Pose)" # default
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
        target_task = "Tablice (Pose)" # default
        if "Pojazdy" in category: target_task = "Pojazdy (Detect)"
        elif "Znaki" in category: target_task = "Znaki/Litery (Detect)"
        
        # Odrzucamy modele które z nazwy ewidentnie nie pasują do zadania (prosta heurystyka)
        is_pose_task = ("Pose" in target_task)

        self.rank_is_running = True
        self.btn_run_rank.config(state=tk.DISABLED, text="Testowanie modeli...")
        self.rank_progress_var.set(0)

        def worker():
            from ..ranking.annotation_comparator import AnnotationComparator
            from ..annotators import VehicleAnnotator, PlateAnnotator
            from ..data_models import ImageAnnotation, Detection
            
            try:
                # 1. Zebranie modeli do przetestowania
                model_files = list(models_dir.glob("*.pt"))
                models_to_test = []
                for mf in model_files:
                    # Filtrujemy na podstawie nazwy - pose do tablic, reszta do pojazdów/znaków
                    is_pose_model = "pose" in mf.name.lower()
                    if is_pose_task and not is_pose_model:
                        continue
                    if not is_pose_task and is_pose_model:
                        continue
                    models_to_test.append(mf)
                
                if not models_to_test:
                    self._ui(lambda: messagebox.showinfo("Info", "Brak modeli .pt pasujących do wybranej kategorii (Pose/Detect)."))
                    return
                
                total_models = len(models_to_test)
                comparator = AnnotationComparator()
                device = self._device_to_ultralytics(self.device_var.get())
                conf_thresh = self.rank_conf.get()

                # Folder roboczy na tymczasowe wyniki eksportu
                temp_xml_path = data_dir / "temp_ranking_auto.xml"
                
                for idx, model_path in enumerate(models_to_test):
                    if not self.rank_is_running: break
                    
                    self._ui(lambda m=model_path.name: self.rank_status.config(text=f"Testowanie {m} ({idx+1}/{total_models})"))
                    
                    # 2. Utworzenie odpowiedniego Annotatora
                    if is_pose_task:
                        annotator = PlateAnnotator(model_path, conf_thresh, device)
                    else:
                        annotator = VehicleAnnotator(model_path, conf_thresh, device)
                        
                    success, msg = annotator.load_models()
                    if not success:
                        logger.warning(f"Nie udało się załadować modelu {model_path.name}: {msg}")
                        continue
                        
                    # 3. Przepuszczenie modelu przez obrazy w folderze (bez zapisywania wizualizacji by było szybko)
                    images = list(data_dir.glob("*.jpg")) + list(data_dir.glob("*.png"))
                    auto_annotations = []
                    
                    for img_idx, img_path in enumerate(images):
                        if not self.rank_is_running: break
                        
                        ann = annotator.process_image(img_path)
                        auto_annotations.append(ann)
                        
                        # Pasek postępu
                        sub_pct = ((idx + (img_idx / len(images))) / total_models) * 100
                        self._ui(lambda p=sub_pct: self.rank_progress_var.set(p))
                        
                    annotator.unload_models()
                    
                    # 4. Eksport do tymczasowego XML
                    from ..exporters.cvat_exporter import CVATExporter
                    exporter = CVATExporter()
                    exporter.export(auto_annotations, temp_xml_path, include_confidence=True)
                    
                    # 5. Porównanie z Ground Truth (annotations.xml od użytkownika)
                    stats = comparator.compare(
                        auto_xml_path=temp_xml_path,
                        corrected_xml_path=gt_xml
                    )
                    
                    # 6. Dodanie do bazy ModelRanking
                    self.ranking_engine.add_entry(
                        model_name=model_path.name,
                        model_path=str(model_path),
                        comparison_stats=stats,
                        task_type=target_task
                    )
                    
                    # Czystka tymczasowego pliku
                    if temp_xml_path.exists():
                        temp_xml_path.unlink()
                
                self._ui(lambda: self.rank_progress_var.set(100))
                self._ui(lambda: self._load_ranking())
                self._ui(lambda: self.rank_status.config(text="Ranking zakończony.", foreground="green"))
                self._ui(lambda: messagebox.showinfo("Sukces", "Testowanie zakończone, ranking zaktualizowany!"))
                
            except Exception as e:
                self._ui(lambda: messagebox.showerror("Błąd", f"Błąd w trakcie rankingu:\n{e}"))
                self._ui(lambda: self.rank_status.config(text="Błąd rankingu", foreground="red"))
            finally:
                self.rank_is_running = False
                self._ui(lambda: self.btn_run_rank.config(state=tk.NORMAL, text="🏆 URUCHOM RANKING"))

        threading.Thread(target=worker, daemon=True).start()