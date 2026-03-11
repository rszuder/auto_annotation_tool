#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka treningu + dataset builder + wykresy w GUI.
(Wersja poprawiona: wszystkie metody są wewnątrz klasy, brak zagnieżdżonych def.)
"""

from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..config import CONFIG, YOLO_AVAILABLE, AVAILABLE_POSE_MODELS, PIL_AVAILABLE
from ..icons import IconManager
from ..validators import validate_yolo_dataset, validate_model_file
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..training.training_report import TrainingReportGenerator

if PIL_AVAILABLE:
    from PIL import Image, ImageTk


class TrainingTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager

        self.frame = ttk.Frame(parent)

        # backend
        self.trainer = YOLOPoseTrainer()
        self.history: TrainingHistory = self.trainer.history
        self.creator = DatasetCreator()
        self.splitter = DatasetSplitter()

        self.current_run_id = None

        # plot preview state
        self._plots_paths = []
        self._plot_photo = None
        self._plot_img_id = None
        self._plot_original_path = None

        self._build_ui()
        self._bind_trainer_callbacks()
        self._load_history()
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
        except Exception:
            pass
        return devices

    def _device_to_ultralytics(self, device_str: str):
        if not device_str:
            return "auto"
        if device_str == "auto":
            return "auto"
        if device_str == "cpu":
            return "cpu"
        if device_str.startswith("cuda:"):
            try:
                idx = int(device_str.split(":")[1].split()[0])
                return idx
            except Exception:
                return 0
        return device_str

    def _open_path(self, path: Path):
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.as_uri())
        except Exception as e:
            messagebox.showinfo("Info", f"Nie mogę otworzyć: {path}\n\n{e}")

    def _selected_run(self):
        sel = self.tree.selection()
        if not sel:
            return None
        item = self.tree.item(sel[0])
        short_id = str(item["values"][0])
        full_run_id = next((r.id for r in self.history.get_all_runs() if r.id.endswith(short_id)), None)
        if not full_run_id:
            return None
        return self.history.get_run(full_run_id)

    # ============================================================
    # UI
    # ============================================================

    def _build_ui(self):
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tab_train = ttk.Frame(self.main_nb)
        self.tab_dataset = ttk.Frame(self.main_nb)

        self.main_nb.add(self.tab_train, text="Trening")
        self.main_nb.add(self.tab_dataset, text="Dataset")

        self._build_train_tab()
        self._build_dataset_tab()

    # -------------------- TRAIN TAB --------------------

    def _build_train_tab(self):
        # Baner podpowiedzi
        hint = ttk.LabelFrame(self.tab_train, text="Jak zacząć?", padding=8)
        hint.pack(fill=tk.X, padx=5, pady=(5, 0))

        hint_text = (
            "1) Wybierz gotowy dataset YOLO (folder z data.yaml + images/train, images/val)\n"
            "albo\n"
            "2) Przejdź do zakładki „Dataset” i utwórz dataset z CVAT XML + folderu images/.\n"
        )
        ttk.Label(hint, text=hint_text, justify=tk.LEFT, wraplength=900).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(hint, text="Przejdź do „Dataset”", command=lambda: self.main_nb.select(self.tab_dataset)).pack(side=tk.RIGHT, padx=10)

        self.train_pane = ttk.PanedWindow(self.tab_train, orient=tk.HORIZONTAL)
        self.train_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.left = ttk.LabelFrame(self.train_pane, text="Konfiguracja treningu", padding=10)
        self.right = ttk.LabelFrame(self.train_pane, text="Historia / Wykresy", padding=10)

        self.train_pane.add(self.left, weight=0)
        self.train_pane.add(self.right, weight=1)

        # LEFT
        ttk.Label(self.left, text="Nazwa treningu:").pack(anchor=tk.W)
        self.name_var = tk.StringVar(value="Trening tablic")
        ttk.Entry(self.left, textvariable=self.name_var).pack(fill=tk.X, pady=2)

        ttk.Label(self.left, text="Dataset (folder z data.yaml):").pack(anchor=tk.W, pady=(6, 0))
        self.dataset_var = tk.StringVar()
        ds_row = ttk.Frame(self.left)
        ds_row.pack(fill=tk.X, pady=2)
        ttk.Entry(ds_row, textvariable=self.dataset_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(ds_row, text="Wybierz", command=self._pick_dataset).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.left, text="Waliduj dataset", command=self._validate_dataset).pack(fill=tk.X, pady=(0, 6))

        ttk.Separator(self.left).pack(fill=tk.X, pady=6)

        ttk.Label(self.left, text="Model bazowy (Pose):").pack(anchor=tk.W)
        self.base_model_var = tk.StringVar()
        model_keys = sorted(list(AVAILABLE_POSE_MODELS.keys())) if AVAILABLE_POSE_MODELS else []
        base_values = model_keys + ["Custom"] if model_keys else ["Custom"]

        self.base_combo = ttk.Combobox(self.left, textvariable=self.base_model_var, values=base_values, state="readonly")
        self.base_combo.pack(fill=tk.X, pady=2)

        default_model = self.trainer.get_recommended_model()
        self.base_model_var.set(default_model if default_model in base_values else base_values[0])
        self.base_combo.bind("<<ComboboxSelected>>", lambda e: self._on_base_model_change())

        self.base_custom_var = tk.StringVar()
        self.base_custom_entry = ttk.Entry(self.left, textvariable=self.base_custom_var, state=tk.DISABLED)
        self.base_custom_entry.pack(fill=tk.X, pady=2)
        self.base_custom_btn = ttk.Button(self.left, text="Wybierz custom .pt", command=self._pick_base_custom, state=tk.DISABLED)
        self.base_custom_btn.pack(fill=tk.X, pady=(0, 6))

        ttk.Separator(self.left).pack(fill=tk.X, pady=6)

        grid = ttk.Frame(self.left)
        grid.pack(fill=tk.X)

        ttk.Label(grid, text="Epoki:").grid(row=0, column=0, sticky=tk.W)
        self.epochs_var = tk.IntVar(value=100)
        ttk.Spinbox(grid, from_=1, to=5000, textvariable=self.epochs_var, width=8).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Batch:").grid(row=1, column=0, sticky=tk.W)
        self.batch_var = tk.IntVar(value=16)
        ttk.Spinbox(grid, from_=1, to=256, textvariable=self.batch_var, width=8).grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="ImgSz:").grid(row=2, column=0, sticky=tk.W)
        self.imgsz_var = tk.IntVar(value=640)
        ttk.Spinbox(grid, from_=160, to=2048, textvariable=self.imgsz_var, width=8).grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(grid, text="Device:").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
        self.device_var = tk.StringVar(value="auto")
        self.device_combo = ttk.Combobox(grid, textvariable=self.device_var, values=self._get_available_devices(), state="readonly", width=25)
        self.device_combo.grid(row=3, column=1, sticky=tk.W, padx=5, pady=(6, 0))

        ttk.Separator(self.left).pack(fill=tk.X, pady=6)

        self.btn_start = ttk.Button(self.left, text="Start", command=self._start_training, state=tk.NORMAL)
        self.btn_start.pack(fill=tk.X, pady=2)

        self.btn_pause = ttk.Button(self.left, text="Pauza", command=self._pause_training, state=tk.DISABLED)
        self.btn_pause.pack(fill=tk.X, pady=2)

        self.btn_stop = ttk.Button(self.left, text="Stop", command=self._stop_training, state=tk.DISABLED)
        self.btn_stop.pack(fill=tk.X, pady=2)

        ttk.Separator(self.left).pack(fill=tk.X, pady=6)
        self.model_info = ttk.Label(self.left, text="", justify=tk.LEFT, wraplength=320)
        self.model_info.pack(fill=tk.X)

        # RIGHT: notebook
        self.right_nb = ttk.Notebook(self.right)
        self.right_nb.pack(fill=tk.BOTH, expand=True)

        self.hist_tab = ttk.Frame(self.right_nb)
        self.plots_tab = ttk.Frame(self.right_nb)
        self.right_nb.add(self.hist_tab, text="Historia")
        self.right_nb.add(self.plots_tab, text="Wykresy")

        # tree
        hist_top = ttk.Frame(self.hist_tab)
        hist_top.pack(fill=tk.BOTH, expand=True)

        columns = ("ID", "Nazwa", "Status", "Epoki", "mAP50", "Czas")
        self.tree = ttk.Treeview(hist_top, columns=columns, show="headings")
        for c in columns:
            self.tree.heading(c, text=c)

        self.tree.column("ID", width=80, stretch=False)
        self.tree.column("Nazwa", width=220, stretch=True)
        self.tree.column("Status", width=130, stretch=False)
        self.tree.column("Epoki", width=90, stretch=False)
        self.tree.column("mAP50", width=80, stretch=False)
        self.tree.column("Czas", width=100, stretch=False)

        yscroll = ttk.Scrollbar(hist_top, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_run_selected)

        hist_btns = ttk.Frame(self.hist_tab)
        hist_btns.pack(fill=tk.X, pady=5)
        ttk.Button(hist_btns, text="Odśwież", command=self._load_history).pack(side=tk.LEFT)
        ttk.Button(hist_btns, text="Wznów", command=self._resume_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(hist_btns, text="Usuń", command=self._delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(hist_btns, text="Otwórz folder runa", command=self._open_run_folder).pack(side=tk.RIGHT)
        ttk.Button(hist_btns, text="Otwórz raport HTML", command=self._open_run_report).pack(side=tk.RIGHT, padx=5)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(self.right, variable=self.progress_var, maximum=100)
        self.progress.pack(fill=tk.X, pady=(6, 2))
        self.progress_label = ttk.Label(self.right, text="Brak aktywnego treningu")
        self.progress_label.pack(anchor=tk.W)

        self._build_plots_ui()

    def _build_plots_ui(self):
        self.plots_pane = ttk.PanedWindow(self.plots_tab, orient=tk.HORIZONTAL)
        self.plots_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(self.plots_pane)
        right = ttk.Frame(self.plots_pane)
        self.plots_pane.add(left, weight=0)
        self.plots_pane.add(right, weight=1)

        ttk.Label(left, text="Pliki wykresów:").pack(anchor=tk.W)
        self.plots_list = tk.Listbox(left, height=12)
        self.plots_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.plots_list.yview)
        self.plots_list.configure(yscrollcommand=scr.set)
        scr.pack(side=tk.RIGHT, fill=tk.Y)

        self.plots_list.bind("<<ListboxSelect>>", self._on_plot_selected)

        topbar = ttk.Frame(right)
        topbar.pack(fill=tk.X)
        ttk.Label(topbar, text="Zoom:").pack(side=tk.LEFT)
        self.zoom_var = tk.DoubleVar(value=1.0)
        ttk.Button(topbar, text=" - ", width=4, command=lambda: self._change_zoom(0.8)).pack(side=tk.LEFT, padx=2)
        ttk.Button(topbar, text=" + ", width=4, command=lambda: self._change_zoom(1.25)).pack(side=tk.LEFT, padx=2)
        ttk.Label(topbar, textvariable=self.zoom_var).pack(side=tk.LEFT, padx=6)

        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        self.plot_canvas = tk.Canvas(canvas_frame, background="#ffffff")
        self.plot_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        yscroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.plot_canvas.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        xscroll = ttk.Scrollbar(right, orient=tk.HORIZONTAL, command=self.plot_canvas.xview)
        xscroll.pack(fill=tk.X)

        self.plot_canvas.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.plot_canvas.bind("<MouseWheel>", self._on_mousewheel_canvas)

    # -------------------- DATASET TAB --------------------

    def _build_dataset_tab(self):
        info = ttk.LabelFrame(self.tab_dataset, text="Wskazówka", padding=8)
        info.pack(fill=tk.X, padx=5, pady=(5, 0))

        txt = (
            "Aby stworzyć dataset do treningu tablic:\n"
            "• Export z CVAT: annotations.xml (CVAT for images 1.1)\n"
            "• Tablice muszą być polygonem z 4 punktami (rogi)\n"
            "• Wskaż folder images/ z exportu CVAT\n"
            "Następnie ustaw split suwakiem i kliknij „Stwórz dataset”."
        )
        ttk.Label(info, text=txt, justify=tk.LEFT, wraplength=900).pack(fill=tk.X, expand=True)

        self.ds_pane = ttk.PanedWindow(self.tab_dataset, orient=tk.VERTICAL)
        self.ds_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.ds_creator_frame = ttk.LabelFrame(self.ds_pane, text="CVAT XML + images → Dataset YOLO Pose", padding=10)
        self.ds_split_frame = ttk.LabelFrame(self.ds_pane, text="Podział istniejącego datasetu YOLO (splitter)", padding=10)

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
        ttk.Button(row1, text="Wybierz", command=self._pick_cvat_xml).pack(side=tk.LEFT)

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Folder images/:").pack(side=tk.LEFT)
        self.cvat_images_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.cvat_images_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row2, text="Wybierz", command=self._pick_cvat_images).pack(side=tk.LEFT)

        row3 = ttk.Frame(f); row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Output dataset:").pack(side=tk.LEFT)
        self.ds_out_var = tk.StringVar(value=str(Path(CONFIG.DEFAULT_DATASETS_DIR) / "plates_pose"))
        ttk.Entry(row3, textvariable=self.ds_out_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row3, text="Wybierz", command=self._pick_ds_out).pack(side=tk.LEFT)

        ttk.Separator(f).pack(fill=tk.X, pady=6)

        ratios = ttk.Frame(f); ratios.pack(fill=tk.X)
        ratios.columnconfigure(1, weight=1)

        ttk.Label(ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
        self.train_pct = tk.DoubleVar(value=80.0)
        ttk.Scale(ratios, from_=50, to=95, variable=self.train_pct, command=lambda e: self._update_ratio_labels()).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.train_lbl = ttk.Label(ratios, text="80%"); self.train_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
        self.val_pct = tk.DoubleVar(value=20.0)
        ttk.Scale(ratios, from_=5, to=50, variable=self.val_pct, command=lambda e: self._update_ratio_labels()).grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.val_lbl = ttk.Label(ratios, text="20%"); self.val_lbl.grid(row=1, column=2, sticky=tk.W)

        self.use_test = tk.BooleanVar(value=False)
        ttk.Checkbutton(ratios, text="Utwórz test (reszta %)", variable=self.use_test, command=self._update_ratio_labels).grid(row=2, column=0, columnspan=2, sticky=tk.W)
        self.test_lbl = ttk.Label(ratios, text="Test: 0%"); self.test_lbl.grid(row=2, column=2, sticky=tk.W)

        self._update_ratio_labels()

        ttk.Separator(f).pack(fill=tk.X, pady=6)

        btns = ttk.Frame(f); btns.pack(fill=tk.X)
        ttk.Button(btns, text="Parsuj XML", command=self._parse_cvat_xml).pack(side=tk.LEFT)
        ttk.Button(btns, text="Stwórz dataset", command=self._create_dataset_thread).pack(side=tk.LEFT, padx=5)

        self.ds_progress_var = tk.DoubleVar(value=0.0)
        self.ds_progress = ttk.Progressbar(f, variable=self.ds_progress_var, maximum=100)
        self.ds_progress.pack(fill=tk.X, pady=(8, 2))
        self.ds_status = ttk.Label(f, text="Status: gotowy")
        self.ds_status.pack(anchor=tk.W)

        self.ds_log = tk.Text(f, height=8, wrap=tk.WORD)
        self.ds_log.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

    def _build_splitter_ui(self):
        f = self.ds_split_frame

        row1 = ttk.Frame(f); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Źródło dataset:").pack(side=tk.LEFT)
        self.split_src_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.split_src_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row1, text="Wybierz", command=self._pick_split_src).pack(side=tk.LEFT)

        row2 = ttk.Frame(f); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Output split:").pack(side=tk.LEFT)
        self.split_out_var = tk.StringVar(value=str(Path(CONFIG.DEFAULT_DATASETS_DIR) / "split_out"))
        ttk.Entry(row2, textvariable=self.split_out_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(row2, text="Wybierz", command=self._pick_split_out).pack(side=tk.LEFT)

        ttk.Separator(f).pack(fill=tk.X, pady=6)

        ratios = ttk.Frame(f); ratios.pack(fill=tk.X)
        ratios.columnconfigure(1, weight=1)

        ttk.Label(ratios, text="Train %").grid(row=0, column=0, sticky=tk.W)
        self.split_train = tk.DoubleVar(value=70.0)
        ttk.Scale(ratios, from_=50, to=90, variable=self.split_train, command=lambda e: self._update_split_labels()).grid(row=0, column=1, sticky=tk.EW, padx=5)
        self.split_train_lbl = ttk.Label(ratios, text="70%"); self.split_train_lbl.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(ratios, text="Val %").grid(row=1, column=0, sticky=tk.W)
        self.split_val = tk.DoubleVar(value=20.0)
        ttk.Scale(ratios, from_=5, to=40, variable=self.split_val, command=lambda e: self._update_split_labels()).grid(row=1, column=1, sticky=tk.EW, padx=5)
        self.split_val_lbl = ttk.Label(ratios, text="20%"); self.split_val_lbl.grid(row=1, column=2, sticky=tk.W)

        self.split_use_test = tk.BooleanVar(value=True)
        ttk.Checkbutton(ratios, text="Test (reszta %)", variable=self.split_use_test, command=self._update_split_labels).grid(row=2, column=0, columnspan=2, sticky=tk.W)
        self.split_test_lbl = ttk.Label(ratios, text="Test: 10%"); self.split_test_lbl.grid(row=2, column=2, sticky=tk.W)

        self._update_split_labels()

        ttk.Separator(f).pack(fill=tk.X, pady=6)
        ttk.Button(f, text="Wykonaj split", command=self._split_dataset_thread).pack(anchor=tk.W)

        self.split_progress_var = tk.DoubleVar(value=0.0)
        self.split_progress = ttk.Progressbar(f, variable=self.split_progress_var, maximum=100)
        self.split_progress.pack(fill=tk.X, pady=(6, 2))
        self.split_status = ttk.Label(f, text="Status: gotowy")
        self.split_status.pack(anchor=tk.W)

    # ============================================================
    # Training logic
    # ============================================================

    def _on_base_model_change(self):
        key = self.base_model_var.get()
        if key == "Custom":
            self.base_custom_entry.configure(state=tk.NORMAL)
            self.base_custom_btn.configure(state=tk.NORMAL)
        else:
            self.base_custom_entry.configure(state=tk.DISABLED)
            self.base_custom_btn.configure(state=tk.DISABLED)
            self.base_custom_var.set("")

        if key in AVAILABLE_POSE_MODELS:
            info = AVAILABLE_POSE_MODELS[key]
            txt = f"{info.get('name', key)}\n{info.get('description','')}"
        elif key == "Custom":
            p = self.base_custom_var.get().strip()
            txt = f"Custom model: {Path(p).name if p else '(nie wybrano)'}"
        else:
            txt = f"Model: {key}"
        self.model_info.configure(text=txt)

    def _pick_dataset(self):
        p = filedialog.askdirectory(title="Wybierz dataset YOLO (folder z data.yaml)")
        if p:
            self.dataset_var.set(p)

    def _validate_dataset(self):
        p = Path(self.dataset_var.get().strip())
        ok, msg, stats = validate_yolo_dataset(p)
        if ok:
            messagebox.showinfo("Dataset OK", f"{msg}\n\n{stats}")
        else:
            messagebox.showerror("Dataset błąd", f"{msg}\n\n{stats}")

    def _pick_base_custom(self):
        p = filedialog.askopenfilename(title="Wybierz custom model Pose .pt", filetypes=[("PyTorch", "*.pt")])
        if p:
            self.base_custom_var.set(p)
            ok, msg, stats = validate_model_file(Path(p))
            if not ok or not stats.get("keypoints", False):
                messagebox.showwarning("Uwaga", f"Model może nie być Pose/keypoints.\n{msg}")
        self._on_base_model_change()

    def _start_training(self):
        if not YOLO_AVAILABLE:
            messagebox.showerror("Błąd", "Brak ultralytics/YOLO.")
            return

        dataset = self.dataset_var.get().strip()
        if not dataset:
            if messagebox.askyesno("Brak datasetu", "Nie wybrano datasetu.\nPrzejść do zakładki Dataset, aby go stworzyć?"):
                self.main_nb.select(self.tab_dataset)
            return

        base_key = self.base_model_var.get()
        if base_key == "Custom":
            base = self.base_custom_var.get().strip()
            if not base:
                messagebox.showerror("Błąd", "Wybierz custom model .pt.")
                return
            ok, msg, stats = validate_model_file(Path(base))
            if not ok or not stats.get("keypoints", False):
                messagebox.showerror("Błąd", f"Custom model nie wygląda na Pose/keypoints:\n{msg}")
                return
            base_model = base
        else:
            base_model = base_key

        device = self._device_to_ultralytics(self.device_var.get())
        run_id = self.trainer.start_training(
            name=self.name_var.get(),
            dataset_path=dataset,
            base_model=base_model,
            epochs=int(self.epochs_var.get()),
            batch_size=int(self.batch_var.get()),
            img_size=int(self.imgsz_var.get()),
            device=device,
        )
        if run_id:
            self.current_run_id = run_id
            self.btn_start.configure(state=tk.DISABLED)
            self.btn_pause.configure(state=tk.NORMAL)
            self.btn_stop.configure(state=tk.NORMAL)
            self.progress_label.configure(text=f"Trening uruchomiony: {run_id}")
        else:
            messagebox.showerror("Błąd", "Nie udało się wystartować treningu (sprawdź logi).")

    def _pause_training(self):
        self.trainer.pause_training()
        self.btn_pause.configure(state=tk.DISABLED)

    def _stop_training(self):
        self.trainer.stop_training()
        self.btn_stop.configure(state=tk.DISABLED)

    def _bind_trainer_callbacks(self):
        def on_epoch_end(epoch, metrics):
            def upd():
                run = self.trainer.current_run
                if not run:
                    return
                pct = (epoch / max(1, run.epochs)) * 100.0
                self.progress_var.set(pct)
                self.progress_label.configure(text=f"Epoka {epoch}/{run.epochs} | mAP50={metrics.get('map50',0):.3f}")
            self._ui(upd)

        def on_training_end(success, msg):
            def upd():
                self.btn_start.configure(state=tk.NORMAL)
                self.btn_pause.configure(state=tk.DISABLED)
                self.btn_stop.configure(state=tk.DISABLED)
                self.progress_label.configure(text=msg)
                self._load_history()
                if success:
                    self.progress_var.set(100.0)
                self._select_and_load_latest_run()
            self._ui(upd)

        def on_progress(pct, msg):
            def upd():
                self.progress_var.set(float(pct))
                self.progress_label.configure(text=msg)
            self._ui(upd)

        self.trainer.on_epoch_end = on_epoch_end
        self.trainer.on_training_end = on_training_end
        self.trainer.on_progress = on_progress

    def _load_history(self):
        runs = self.history.get_all_runs()
        self.tree.delete(*self.tree.get_children())

        for run in runs:
            icon = {
                TrainingStatus.RUNNING.value: self.icon_manager.get("play"),
                TrainingStatus.COMPLETED.value: self.icon_manager.get("check"),
                TrainingStatus.FAILED.value: self.icon_manager.get("error"),
                TrainingStatus.PAUSED.value: self.icon_manager.get("pause"),
            }.get(run.status, self.icon_manager.get("info"))

            self.tree.insert("", tk.END, values=(
                run.id[-8:],
                run.name[:30],
                f"{icon} {run.status}",
                f"{run.current_epoch}/{run.epochs}",
                f"{run.best_map50:.3f}",
                run.duration_str
            ))

    def _select_and_load_latest_run(self):
        children = self.tree.get_children()
        if not children:
            return
        first = children[0]
        self.tree.selection_set(first)
        self.tree.focus(first)
        self.tree.see(first)
        self._on_run_selected()

    def _resume_selected(self):
        run = self._selected_run()
        if not run:
            messagebox.showwarning("Info", "Zaznacz trening w tabeli.")
            return
        new_id = self.trainer.resume_training(run.id)
        if not new_id:
            messagebox.showerror("Błąd", "Nie można wznowić (brak checkpointu albo zły status).")

    def _delete_selected(self):
        run = self._selected_run()
        if not run:
            return
        if messagebox.askyesno("Potwierdź", "Usunąć trening (i pliki)?"):
            self.history.delete_run(run.id, delete_files=True)
            self._load_history()

    def _open_run_folder(self):
        run = self._selected_run()
        if not run:
            return
        p = Path(run.output_dir)
        if p.exists():
            self._open_path(p)

    def _open_run_report(self):
        run = self._selected_run()
        if not run:
            return
        report = getattr(run, "report_html", "") or (Path(run.output_dir) / "training_report.html")
        report = Path(str(report))
        if report.exists():
            self._open_path(report)
        else:
            messagebox.showinfo("Info", "Brak training_report.html (czy wdrożyłeś training_report.py + poprawiony trainer.py?)")

    # ============================================================
    # Plots in GUI
    # ============================================================

    def _on_run_selected(self, event=None):
        run = self._selected_run()
        if not run:
            return

        run_dir = Path(run.output_dir)
        plots_dir = run_dir / "plots"
        train_dir = run_dir / "train"

        paths = TrainingReportGenerator.find_plots(plots_dir) if plots_dir.exists() else TrainingReportGenerator.find_plots(train_dir)

        self._plots_paths = paths
        self.plots_list.delete(0, tk.END)
        for p in paths:
            self.plots_list.insert(tk.END, p.name)

        if paths:
            self.right_nb.select(self.plots_tab)

    def _on_plot_selected(self, event=None):
        if not self._plots_paths:
            return
        sel = self.plots_list.curselection()
        if not sel:
            return

        img_path = self._plots_paths[int(sel[0])]
        if isinstance(img_path, str):
            img_path = Path(img_path)

        self._show_plot(img_path)

    def _on_mousewheel_canvas(self, event):
        if event.state & 0x0001:
            self.plot_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        else:
            self.plot_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _change_zoom(self, factor: float):
        if not PIL_AVAILABLE:
            return
        new_zoom = float(self.zoom_var.get()) * factor
        new_zoom = max(0.1, min(new_zoom, 8.0))
        self.zoom_var.set(round(new_zoom, 2))
        if self._plot_original_path:
            self._show_plot(Path(self._plot_original_path))

    def _show_plot(self, img_path: Path):
        if not PIL_AVAILABLE:
            messagebox.showinfo("Info", f"PIL niedostępny. Wykres w pliku:\n{img_path}")
            return
        try:
            self._plot_original_path = str(img_path)
            img = Image.open(img_path)

            zoom = float(self.zoom_var.get())
            w, h = img.size
            img = img.resize((max(1, int(w * zoom)), max(1, int(h * zoom))))

            self._plot_photo = ImageTk.PhotoImage(img)

            self.plot_canvas.delete("all")
            self._plot_img_id = self.plot_canvas.create_image(0, 0, anchor="nw", image=self._plot_photo)
            self.plot_canvas.config(scrollregion=(0, 0, img.width, img.height))
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się wczytać wykresu:\n{img_path.name}\n\n{e}")

    # ============================================================
    # Dataset Creator / Splitter logic
    # ============================================================

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

    def _pick_cvat_xml(self):
        p = filedialog.askopenfilename(title="Wybierz CVAT XML", filetypes=[("CVAT XML", "*.xml")])
        if p:
            self.cvat_xml_var.set(p)

    def _pick_cvat_images(self):
        p = filedialog.askdirectory(title="Wybierz folder images/ z exportu CVAT")
        if p:
            self.cvat_images_var.set(p)

    def _pick_ds_out(self):
        p = filedialog.askdirectory(title="Wybierz output dataset")
        if p:
            self.ds_out_var.set(p)

    def _parse_cvat_xml(self):
        xml = Path(self.cvat_xml_var.get().strip())
        if not xml.exists():
            messagebox.showerror("Błąd", "XML nie istnieje.")
            return
        ok, msg, stats = self.creator.parse_cvat_xml(xml)
        self.ds_log.insert(tk.END, f"[parse] {msg}\n{stats}\n\n")
        self.ds_log.see(tk.END)
        if not ok:
            messagebox.showerror("Błąd", msg)

    def _create_dataset_thread(self):
        xml = Path(self.cvat_xml_var.get().strip())
        images_dir = Path(self.cvat_images_var.get().strip())
        out_dir = Path(self.ds_out_var.get().strip())

        if not xml.exists():
            messagebox.showerror("Błąd", "XML nie istnieje.")
            return
        if not images_dir.exists():
            messagebox.showerror("Błąd", "Folder images nie istnieje.")
            return

        if not self.creator.annotations:
            ok, msg, _ = self.creator.parse_cvat_xml(xml)
            if not ok:
                messagebox.showerror("Błąd", msg)
                return

        train = float(self.train_pct.get()) / 100.0
        val = float(self.val_pct.get()) / 100.0

        if self.use_test.get():
            if train + val > 0.99:
                messagebox.showerror("Błąd", "Train+Val za duże – brak miejsca na test.")
                return
            ratios = {"train": train, "val": val, "test": 1.0 - train - val}
        else:
            s = max(0.0001, train + val)
            ratios = {"train": train / s, "val": val / s}

        def worker():
            def progress(cur, total, name):
                pct = (cur / max(1, total)) * 100.0
                self._ui(lambda: self.ds_progress_var.set(pct))
                self._ui(lambda: self.ds_status.configure(text=f"Status: {cur}/{total}  {name}"))

            ok, msg, stats = self.creator.create_dataset(
                images_dir=images_dir,
                output_dir=out_dir,
                split_ratios=ratios,
                progress_callback=progress
            )

            def done():
                self.ds_progress_var.set(100.0 if ok else 0.0)
                self.ds_status.configure(text=f"Status: {msg}")
                self.ds_log.insert(tk.END, f"[create] {msg}\n{stats}\n\n")
                self.ds_log.see(tk.END)
                if ok:
                    messagebox.showinfo("Sukces", msg)
                else:
                    messagebox.showerror("Błąd", msg)

            self._ui(done)

        self.ds_status.configure(text="Status: start...")
        self.ds_progress_var.set(0.0)
        threading.Thread(target=worker, daemon=True).start()

    def _update_split_labels(self):
        tr = float(self.split_train.get())
        va = float(self.split_val.get())
        te = max(0.0, 100.0 - tr - va) if self.split_use_test.get() else 0.0

        if self.split_use_test.get() and tr + va > 100.0:
            va = max(5.0, 100.0 - tr)
            self.split_val.set(va)
            te = max(0.0, 100.0 - tr - va)

        self.split_train_lbl.configure(text=f"{tr:.0f}%")
        self.split_val_lbl.configure(text=f"{va:.0f}%")
        self.split_test_lbl.configure(text=f"Test: {te:.0f}%")

    def _pick_split_src(self):
        p = filedialog.askdirectory(title="Wybierz źródłowy dataset YOLO")
        if p:
            self.split_src_var.set(p)

    def _pick_split_out(self):
        p = filedialog.askdirectory(title="Wybierz output split dataset")
        if p:
            self.split_out_var.set(p)

    def _split_dataset_thread(self):
        src = Path(self.split_src_var.get().strip())
        out = Path(self.split_out_var.get().strip())
        if not src.exists():
            messagebox.showerror("Błąd", "Źródło nie istnieje.")
            return

        tr = float(self.split_train.get()) / 100.0
        va = float(self.split_val.get()) / 100.0

        if self.split_use_test.get():
            if tr + va > 0.99:
                messagebox.showerror("Błąd", "Train+Val za duże – brak miejsca na test.")
                return
            ratios = {"train": tr, "val": va, "test": 1.0 - tr - va}
        else:
            s = max(0.0001, tr + va)
            ratios = {"train": tr / s, "val": va / s}

        def worker():
            def progress(cur, total, name):
                pct = (cur / max(1, total)) * 100.0
                self._ui(lambda: self.split_progress_var.set(pct))
                self._ui(lambda: self.split_status.configure(text=f"Status: {cur}/{total}  {name}"))

            ok, msg, _ = self.splitter.split_dataset(
                source_dir=src,
                output_dir=out,
                ratios=ratios,
                progress_callback=progress
            )

            def done():
                self.split_progress_var.set(100.0 if ok else 0.0)
                self.split_status.configure(text=f"Status: {msg}")
                if ok:
                    messagebox.showinfo("Sukces", msg)
                else:
                    messagebox.showerror("Błąd", msg)

            self._ui(done)

        self.split_status.configure(text="Status: start...")
        self.split_progress_var.set(0.0)
        threading.Thread(target=worker, daemon=True).start()