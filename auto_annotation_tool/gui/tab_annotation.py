#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka anotacji - Poprawiona obsługa trybów i wyboru modeli.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional
import datetime
import threading
import logging

from ..config import CONFIG, logger, YOLO_AVAILABLE, AVAILABLE_DETECT_MODELS, AVAILABLE_POSE_MODELS
from ..icons import IconManager
from ..annotators import VehicleAnnotator, PlateAnnotator, CombinedAnnotator
from ..exporters import CVATExporter, ReportGenerator, YOLOPosePlate4Exporter
from ..utils import count_images_in_directory, format_duration
from ..data_models import AnnotationReport
from ..validators import validate_model_file


class ScrollableFrame(ttk.Frame):
    """Przewijany panel boczny dla ustawień."""
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")
        
        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Lokalne bindowanie scrolla (bezpieczniejsze niż bind_all)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class AnnotationTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon = IconManager
        self.frame = ttk.Frame(parent)
        
        self.annotator = None
        self.is_processing = False
        self.start_time = None
        
        # Zmienne sterujące
        self.export_format_var = tk.StringVar(value="CVAT XML 1.1")
        self.copy_images_yolo_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="C: Pojazdy + tablice")
        self.vehicle_model_var = tk.StringVar()
        self.plate_model_var = tk.StringVar()
        self.vehicle_custom_var = tk.StringVar()
        self.plate_custom_var = tk.StringVar()
        self.device_var = tk.StringVar(value="auto")
        self.conf_var = tk.DoubleVar(value=CONFIG.DEFAULT_CONFIDENCE)
        self.input_dir_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(Path(CONFIG.DEFAULT_OUTPUT_DIR)))

        self._create_widgets()
        self._update_model_lists()
        # Wymuszenie odświeżenia stanów na starcie
        self._on_mode_change()

    def _get_available_devices(self):
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    devices.append(f"cuda:{i}")
        except: pass
        return devices

    def _create_widgets(self):
        self.paned = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.left_container = ttk.Frame(self.paned)
        self.scroll_frame = ScrollableFrame(self.left_container)
        self.scroll_frame.pack(fill=tk.BOTH, expand=True)
        
        left = ttk.LabelFrame(self.scroll_frame.inner, text="Konfiguracja", padding=10)
        left.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        right = ttk.LabelFrame(self.paned, text="Logi i postęp", padding=10)
        
        self.paned.add(self.left_container, weight=0)
        self.paned.add(right, weight=1)
        
        # --- TRYB ---
        ttk.Label(left, text="Tryb pracy:").pack(anchor=tk.W)
        modes = ["A: Tylko pojazdy", "B: Tylko tablice", "C: Pojazdy + tablice"]
        self.mode_combo = ttk.Combobox(left, textvariable=self.mode_var, values=modes, state="readonly")
        self.mode_combo.pack(fill=tk.X, pady=2)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)
        
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        
        # --- POJAZDY ---
        self.lbl_v = ttk.Label(left, text="Model pojazdów:")
        self.lbl_v.pack(anchor=tk.W)
        self.vehicle_combo = ttk.Combobox(left, textvariable=self.vehicle_model_var, state="readonly")
        self.vehicle_combo.pack(fill=tk.X, pady=2)
        self.vehicle_combo.bind("<<ComboboxSelected>>", self._on_vehicle_model_change)
        
        self.vehicle_custom_entry = ttk.Entry(left, textvariable=self.vehicle_custom_var)
        self.vehicle_custom_entry.pack(fill=tk.X, pady=2)
        self.vehicle_custom_btn = ttk.Button(left, text="Wybierz .pt (Pojazdy)", command=self._select_vehicle_custom)
        self.vehicle_custom_btn.pack(fill=tk.X, pady=2)
        
        # --- TABLICE ---
        self.lbl_p = ttk.Label(left, text="Model tablic:")
        self.lbl_p.pack(anchor=tk.W, pady=(10,0))
        self.plate_combo = ttk.Combobox(left, textvariable=self.plate_model_var, state="readonly")
        self.plate_combo.pack(fill=tk.X, pady=2)
        self.plate_combo.bind("<<ComboboxSelected>>", self._on_plate_model_change)
        
        self.plate_custom_entry = ttk.Entry(left, textvariable=self.plate_custom_var)
        self.plate_custom_entry.pack(fill=tk.X, pady=2)
        self.plate_custom_btn = ttk.Button(left, text="Wybierz .pt (Tablice)", command=self._select_plate_custom)
        self.plate_custom_btn.pack(fill=tk.X, pady=2)
        
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        
        # --- PARAMETRY ---
        ttk.Label(left, text="Pewność (Confidence):").pack(anchor=tk.W)
        ttk.Scale(left, from_=0.1, to=0.9, variable=self.conf_var, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=2)
        
        ttk.Label(left, text="Urządzenie (Device):").pack(anchor=tk.W, pady=(5, 0))
        self.device_combo = ttk.Combobox(left, textvariable=self.device_var, values=self._get_available_devices(), state="readonly")
        self.device_combo.pack(fill=tk.X, pady=2)
        
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        
        # --- ŚCIEŻKI ---
        ttk.Label(left, text="Folder wejściowy:").pack(anchor=tk.W)
        ttk.Entry(left, textvariable=self.input_dir_var).pack(fill=tk.X, pady=2)
        ttk.Button(left, text="Wybierz folder wejściowy", command=self._select_input_dir).pack(fill=tk.X, pady=2)
        
        ttk.Label(left, text="Folder wyjściowy:").pack(anchor=tk.W, pady=(5,0))
        ttk.Entry(left, textvariable=self.output_dir_var).pack(fill=tk.X, pady=2)
        ttk.Button(left, text="Wybierz folder zapisu", command=self._select_output_dir).pack(fill=tk.X, pady=2)
        
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        
        # --- EKSPORT ---
        ttk.Label(left, text="Format eksportu:").pack(anchor=tk.W)
        ttk.Combobox(left, textvariable=self.export_format_var, state="readonly",
                     values=["CVAT XML 1.1", "YOLO Pose (plate4)", "CVAT + YOLO Pose (plate4)"]).pack(fill=tk.X, pady=2)
        ttk.Checkbutton(left, text="Kopiuj zdjęcia do YOLO", variable=self.copy_images_yolo_var).pack(anchor=tk.W)
        
        # --- AKCJA ---
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(left, text="URUCHOM AUTOMATYCZNĄ ANOTACJĘ", command=self._start_annotation)
        self.start_btn.pack(fill=tk.X, pady=5, ipady=10)
        self.stop_btn = ttk.Button(left, text="ZATRZYMAJ", command=self._stop_annotation, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X, pady=2)
        
        # --- PRAWY PANEL ---
        self.status_label = ttk.Label(right, text="Gotowy.")
        self.status_label.pack(anchor=tk.W, pady=(0, 5))
        self.log_text = tk.Text(right, wrap=tk.WORD, bg="#f4f4f4")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._redirect_logs()

    def _on_mode_change(self, event=None):
        """Poprawiona logika odblokowywania list modeli."""
        mode_text = self.mode_var.get()
        
        # Logika: A = Tylko pojazdy, B = Tylko tablice, C = Oba
        enable_vehicle = "A:" in mode_text or "C:" in mode_text
        enable_plate = "B:" in mode_text or "C:" in mode_text
        
        v_state = tk.NORMAL if enable_vehicle else tk.DISABLED
        p_state = tk.NORMAL if enable_plate else tk.DISABLED
        
        self.vehicle_combo.config(state=v_state)
        self.plate_combo.config(state=p_state)
        
        self._on_vehicle_model_change()
        self._on_plate_model_change()

    def _update_model_lists(self):
        if YOLO_AVAILABLE:
            v_keys = sorted(list(AVAILABLE_DETECT_MODELS.keys()))
            self.vehicle_combo['values'] = v_keys + ["Custom"]
            if not self.vehicle_model_var.get(): self.vehicle_model_var.set(v_keys[0])
            
            p_keys = sorted(list(AVAILABLE_POSE_MODELS.keys()))
            self.plate_combo['values'] = p_keys + ["Custom"]
            if not self.plate_model_var.get(): self.plate_model_var.set("yolo26m-pose" if "yolo26m-pose" in p_keys else p_keys[0])

    def _on_vehicle_model_change(self, event=None):
        is_custom = self.vehicle_model_var.get() == "Custom"
        is_active = str(self.vehicle_combo.cget("state")) == tk.NORMAL
        st = tk.NORMAL if (is_custom and is_active) else tk.DISABLED
        self.vehicle_custom_entry.config(state=st)
        self.vehicle_custom_btn.config(state=st)

    def _on_plate_model_change(self, event=None):
        is_custom = self.plate_model_var.get() == "Custom"
        is_active = str(self.plate_combo.cget("state")) == tk.NORMAL
        st = tk.NORMAL if (is_custom and is_active) else tk.DISABLED
        self.plate_custom_entry.config(state=st)
        self.plate_custom_btn.config(state=st)

    def _select_vehicle_custom(self):
        p = filedialog.askopenfilename(filetypes=[("YOLO Model", "*.pt")])
        if p: self.vehicle_custom_var.set(p)

    def _select_plate_custom(self):
        p = filedialog.askopenfilename(filetypes=[("YOLO Model", "*.pt")])
        if p: self.plate_custom_var.set(p)

    def _select_input_dir(self):
        p = filedialog.askdirectory()
        if p: self.input_dir_var.set(p)

    def _select_output_dir(self):
        p = filedialog.askdirectory()
        if p: self.output_dir_var.set(p)

    def _redirect_logs(self):
        class TextHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget
            def emit(self, record):
                msg = self.format(record)
                self.widget.insert(tk.END, msg + "\n")
                self.widget.see(tk.END)
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', '%H:%M:%S'))
        logger.addHandler(handler)

    def _start_annotation(self):
        in_d = self.input_dir_var.get().strip()
        if not in_d or not Path(in_d).exists():
            messagebox.showerror("Błąd", "Wybierz folder z obrazami.")
            return
        
        try:
            mode_text = self.mode_var.get()
            conf = self.conf_var.get()
            dev = self.device_var.get()
            
            # Pobieranie ścieżek
            v_p = self.vehicle_custom_var.get() if self.vehicle_model_var.get() == "Custom" else \
                  Path(CONFIG.DEFAULT_MODELS_DIR) / AVAILABLE_DETECT_MODELS[self.vehicle_model_var.get()]["file"]
            
            p_p = self.plate_custom_var.get() if self.plate_model_var.get() == "Custom" else \
                  Path(CONFIG.DEFAULT_MODELS_DIR) / AVAILABLE_POSE_MODELS[self.plate_model_var.get()]["file"]

            if "A:" in mode_text:
                self.annotator = VehicleAnnotator(v_p, conf, dev)
            elif "B:" in mode_text:
                self.annotator = PlateAnnotator(p_p, conf, dev)
            else:
                self.annotator = CombinedAnnotator(v_p, p_p, conf, conf, CONFIG.PLATE_INSIDE_THRESHOLD, dev)
            
            if not self.annotator.load_models()[0]:
                raise RuntimeError("Nie udało się załadować silnika YOLO.")

            self.is_processing = True
            self.app.set_processing(True)
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            
            threading.Thread(target=self._process_thread, args=(Path(in_d), Path(self.output_dir_var.get())), daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Błąd", str(e))

    def _process_thread(self, in_dir: Path, out_dir: Path):
        try:
            def prog_cb(c, t, f):
                self.app.update_status(f"Przetwarzanie {c}/{t}...", "play")

            annotations, report = self.annotator.process_directory(in_dir, prog_cb)
            
            out_dir.mkdir(parents=True, exist_ok=True)
            fmt = self.export_format_var.get()
            
            if "CVAT" in fmt:
                CVATExporter().export(annotations, out_dir / "annotations.xml")
            if "YOLO" in fmt:
                y_out = out_dir / "yolo_dataset"
                YOLOPosePlate4Exporter(copy_images=self.copy_images_yolo_var.get()).export(annotations, in_dir, y_out)

            ReportGenerator.generate_text_report(report, out_dir / "report.txt")
            self.frame.after(0, lambda: self._finish(True, "Zakończono pomyślnie."))
        except Exception as e:
            self.frame.after(0, lambda: self._finish(False, str(e)))

    def _finish(self, success, msg):
        self.is_processing = False
        self.app.set_processing(False)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        if success: messagebox.showinfo("Koniec", msg)
        else: messagebox.showerror("Błąd", msg)

    def _stop_annotation(self):
        self.is_processing = False
        self.app.update_status("Zatrzymano.", "stop")