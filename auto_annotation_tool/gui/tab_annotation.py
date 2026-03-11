#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka anotacji.
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
from ..exporters import CVATExporter, ReportGenerator
from ..utils import count_images_in_directory, format_duration
from ..data_models import AnnotationReport
from ..validators import validate_model_file


class AnnotationTab:
    """Zakładka anotacji."""
    
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        
        self.frame = ttk.Frame(parent)
        
        self.annotator = None
        self.is_processing = False
        self.start_time = None
        
        self._create_widgets()
        self._update_model_lists()
    
    def _get_available_devices(self):
        """Pobiera listę dostępnych urządzeń (CPU, cuda:0, cuda:1...)."""
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    devices.append(f"cuda:{i}")
        except ImportError:
            pass
        return devices

    def _create_widgets(self):
        """Tworzy interfejs z użyciem PanedWindow dla ruchomych belek."""
        self.paned_window = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        left_frame = ttk.LabelFrame(self.paned_window, text="Ustawienia anotacji", padding=10)
        right_frame = ttk.LabelFrame(self.paned_window, text="Podgląd i raport", padding=10)
        
        self.paned_window.add(left_frame, weight=0) 
        self.paned_window.add(right_frame, weight=1) 
        
        # --- ZAWARTOŚĆ LEWEGO PANELU ---
        # Tryb
        ttk.Label(left_frame, text="Tryb:").pack(anchor=tk.W)
        self.mode_var = tk.StringVar(value="combined")
        modes = [
            ("A: Tylko pojazdy", "vehicle"),
            ("B: Tylko tablice", "plate"),
            ("C: Pojazdy + tablice", "combined")
        ]
        self.mode_combo = ttk.Combobox(left_frame, textvariable=self.mode_var, values=[m[0] for m in modes], state="readonly", width=28)
        self.mode_combo.pack(fill=tk.X, pady=2)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)
        
        # Modele
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)
        
        ttk.Label(left_frame, text="Model pojazdów:").pack(anchor=tk.W)
        self.vehicle_model_var = tk.StringVar()
        self.vehicle_combo = ttk.Combobox(left_frame, textvariable=self.vehicle_model_var, state="readonly", width=28)
        self.vehicle_combo.pack(fill=tk.X, pady=2)
        self.vehicle_combo.bind("<<ComboboxSelected>>", self._on_vehicle_model_change)
        
        self.vehicle_custom_var = tk.StringVar()
        self.vehicle_custom_entry = ttk.Entry(left_frame, textvariable=self.vehicle_custom_var, width=30, state=tk.DISABLED)
        self.vehicle_custom_entry.pack(fill=tk.X, pady=2)
        self.vehicle_custom_btn = ttk.Button(left_frame, text=f"{self.icon_manager.get('file')} Wybierz custom .pt", 
                                             command=self._select_vehicle_custom, state=tk.DISABLED)
        self.vehicle_custom_btn.pack(fill=tk.X, pady=2)
        
        ttk.Label(left_frame, text="Model tablic:").pack(anchor=tk.W)
        self.plate_model_var = tk.StringVar()
        self.plate_combo = ttk.Combobox(left_frame, textvariable=self.plate_model_var, state="readonly", width=28)
        self.plate_combo.pack(fill=tk.X, pady=2)
        self.plate_combo.bind("<<ComboboxSelected>>", self._on_plate_model_change)
        
        self.plate_custom_var = tk.StringVar()
        self.plate_custom_entry = ttk.Entry(left_frame, textvariable=self.plate_custom_var, width=30, state=tk.DISABLED)
        self.plate_custom_entry.pack(fill=tk.X, pady=2)
        self.plate_custom_btn = ttk.Button(left_frame, text=f"{self.icon_manager.get('file')} Wybierz custom .pt", 
                                           command=self._select_plate_custom, state=tk.DISABLED)
        self.plate_custom_btn.pack(fill=tk.X, pady=2)
        
        # Parametry detekcji
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)
        ttk.Label(left_frame, text="Confidence:").pack(anchor=tk.W)
        self.conf_var = tk.DoubleVar(value=CONFIG.DEFAULT_CONFIDENCE)
        conf_scale = ttk.Scale(left_frame, from_=0.1, to=0.9, variable=self.conf_var, orient=tk.HORIZONTAL)
        conf_scale.pack(fill=tk.X, pady=2)
        ttk.Label(left_frame, textvariable=self.conf_var).pack(anchor=tk.W)
        
        # Wybór Urządzenia (CPU/GPU)
        ttk.Label(left_frame, text="Urządzenie (Device):").pack(anchor=tk.W, pady=(5, 0))
        self.device_var = tk.StringVar(value="auto")
        available_devices = self._get_available_devices()
        self.device_combo = ttk.Combobox(left_frame, textvariable=self.device_var, values=available_devices, state="readonly", width=28)
        self.device_combo.pack(fill=tk.X, pady=2)
        
        # Foldery
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)
        ttk.Label(left_frame, text="Folder z obrazami:").pack(anchor=tk.W)
        self.input_dir_var = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.input_dir_var).pack(fill=tk.X, pady=2)
        ttk.Button(left_frame, text=f"{self.icon_manager.get('folder')} Wybierz", command=self._select_input_dir).pack(fill=tk.X, pady=2)
        
        ttk.Label(left_frame, text="Folder wyjściowy:").pack(anchor=tk.W)
        self.output_dir_var = tk.StringVar(value=str(Path(CONFIG.DEFAULT_OUTPUT_DIR)))
        ttk.Entry(left_frame, textvariable=self.output_dir_var).pack(fill=tk.X, pady=2)
        ttk.Button(left_frame, text=f"{self.icon_manager.get('folder')} Wybierz", command=self._select_output_dir).pack(fill=tk.X, pady=2)
        
        # Przyciski akcji
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)
        self.start_btn = ttk.Button(left_frame, text=f"{self.icon_manager.get('play')} Rozpocznij anotację", command=self._start_annotation)
        self.start_btn.pack(fill=tk.X, pady=2)
        self.stop_btn = ttk.Button(left_frame, text=f"{self.icon_manager.get('stop')} Zatrzymaj", command=self._stop_annotation, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X, pady=2)
        
        # --- ZAWARTOŚĆ PRAWEGO PANELU ---
        stats_frame = ttk.Frame(right_frame)
        stats_frame.pack(fill=tk.X, pady=5)
        self.stats_label = ttk.Label(stats_frame, text=f"{self.icon_manager.get('info')} Wybierz folder wejściowy")
        self.stats_label.pack(side=tk.LEFT)
        
        log_frame = ttk.LabelFrame(right_frame, text="Logi", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self._redirect_logs()
    
    def _update_model_lists(self):
        if YOLO_AVAILABLE:
            vehicle_keys = sorted(list(AVAILABLE_DETECT_MODELS.keys()))
            self.vehicle_combo['values'] = vehicle_keys + ["Custom"]
            self.vehicle_model_var.set(vehicle_keys[0] if vehicle_keys else "Custom")
            self.vehicle_combo.config(state=tk.NORMAL)
            
            plate_keys = sorted(list(AVAILABLE_POSE_MODELS.keys()))
            self.plate_combo['values'] = plate_keys + ["Custom"]
            default_plate = "yolo26m-pose" if "yolo26m-pose" in plate_keys else (plate_keys[0] if plate_keys else "Custom")
            self.plate_model_var.set(default_plate)
            self.plate_combo.config(state=tk.NORMAL)
        else:
            self.vehicle_combo['values'] = ["Custom (YOLO niedostępny)"]
            self.plate_combo['values'] = ["Custom (YOLO niedostępny)"]
            self.vehicle_model_var.set("Custom (YOLO niedostępny)")
            self.plate_model_var.set("Custom (YOLO niedostępny)")
            self.vehicle_combo.config(state=tk.DISABLED)
            self.plate_combo.config(state=tk.DISABLED)
            
    def _on_mode_change(self, event=None):
        mode = self.mode_var.get()
        if "vehicle" in mode:
            self.vehicle_combo.config(state=tk.NORMAL)
            self.plate_combo.config(state=tk.DISABLED)
            self.plate_custom_entry.config(state=tk.DISABLED)
            self.plate_custom_btn.config(state=tk.DISABLED)
            self._on_vehicle_model_change()
        elif "plate" in mode:
            self.vehicle_combo.config(state=tk.DISABLED)
            self.vehicle_custom_entry.config(state=tk.DISABLED)
            self.vehicle_custom_btn.config(state=tk.DISABLED)
            self.plate_combo.config(state=tk.NORMAL)
            self._on_plate_model_change()
        else:
            self.vehicle_combo.config(state=tk.NORMAL)
            self.plate_combo.config(state=tk.NORMAL)
            self._on_vehicle_model_change()
            self._on_plate_model_change()
    
    def _on_vehicle_model_change(self, event=None):
        if self.vehicle_model_var.get() == "Custom":
            self.vehicle_custom_entry.config(state=tk.NORMAL)
            self.vehicle_custom_btn.config(state=tk.NORMAL)
        else:
            self.vehicle_custom_entry.config(state=tk.DISABLED)
            self.vehicle_custom_btn.config(state=tk.DISABLED)
            self.vehicle_custom_var.set("")
            
    def _on_plate_model_change(self, event=None):
        if self.plate_model_var.get() == "Custom":
            self.plate_custom_entry.config(state=tk.NORMAL)
            self.plate_custom_btn.config(state=tk.NORMAL)
        else:
            self.plate_custom_entry.config(state=tk.DISABLED)
            self.plate_custom_btn.config(state=tk.DISABLED)
            self.plate_custom_var.set("")
    
    def _select_vehicle_custom(self):
        file_path = filedialog.askopenfilename(title="Wybierz model pojazdów .pt", filetypes=[("PyTorch models", "*.pt")])
        if file_path:
            self.vehicle_custom_var.set(file_path)
            success, msg, stats = validate_model_file(Path(file_path))
            if success:
                self.app.update_status(f"Custom pojazd OK: {stats['type']} ({stats['num_classes']} klas)", "check")
            else:
                messagebox.showwarning("Ostrzeżenie", f"Custom model ostrzeżenie: {msg}")
    
    def _select_plate_custom(self):
        file_path = filedialog.askopenfilename(title="Wybierz model tablic .pt", filetypes=[("PyTorch models", "*.pt")])
        if file_path:
            self.plate_custom_var.set(file_path)
            success, msg, stats = validate_model_file(Path(file_path))
            if success and stats.get('keypoints', False):
                self.app.update_status(f"Custom tablica OK: Pose ({stats['kpt_shape']})", "check")
            else:
                messagebox.showwarning("Ostrzeżenie", f"Custom model ostrzeżenie: {msg} (powinien być Pose)")
    
    def _select_input_dir(self):
        dir_path = filedialog.askdirectory(title="Wybierz folder z obrazami")
        if dir_path:
            self.input_dir_var.set(dir_path)
            self._update_stats()
    
    def _select_output_dir(self):
        dir_path = filedialog.askdirectory(title="Wybierz folder wyjściowy")
        if dir_path:
            self.output_dir_var.set(dir_path)
    
    def _update_stats(self):
        input_dir = Path(self.input_dir_var.get())
        count = count_images_in_directory(input_dir)
        self.stats_label.config(text=f"{self.icon_manager.get('image')} Obrazów: {count}")
    
    def _redirect_logs(self):
        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                self.text_widget.config(state=tk.DISABLED)
            
            def emit(self, record):
                msg = self.format(record)
                self.text_widget.config(state=tk.NORMAL)
                self.text_widget.insert(tk.END, msg + '\n')
                self.text_widget.see(tk.END)
                self.text_widget.config(state=tk.DISABLED)
                self.text_widget.update_idletasks()
        
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.addHandler(handler)
    
    def _start_annotation(self):
        if not YOLO_AVAILABLE:
            messagebox.showerror("Błąd", "YOLO niedostępny. Zainstaluj: pip install ultralytics")
            return
        
        input_dir = Path(self.input_dir_var.get())
        if not input_dir.exists() or str(input_dir) == ".":
            messagebox.showerror("Błąd", "Wybierz prawidłowy folder wejściowy")
            return
        
        output_dir = Path(self.output_dir_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)
        
        mode = self.mode_var.get()
        conf = self.conf_var.get()
        
        # Używamy urządzenia wybranego przez użytkownika z comboboxa
        device = self.device_var.get()
        if device == "auto":
            device = "cuda" if CONFIG.CUDA_AVAILABLE else "cpu"
        
        try:
            vehicle_path = None
            plate_path = None
            
            if "vehicle" in mode or "combined" in mode:
                v_model = self.vehicle_model_var.get()
                if v_model == "Custom":
                    vehicle_path = Path(self.vehicle_custom_var.get())
                    if not vehicle_path.exists():
                        raise FileNotFoundError("Custom model pojazdów nie istnieje. Wybierz plik.")
                    success, msg, _ = validate_model_file(vehicle_path)
                    if not success:
                        raise ValueError(f"Custom model pojazdów niepoprawny: {msg}")
                else:
                    if v_model in AVAILABLE_DETECT_MODELS:
                        vehicle_path = Path(CONFIG.DEFAULT_MODELS_DIR) / AVAILABLE_DETECT_MODELS[v_model]["file"]
                    else:
                        raise ValueError(f"Nieznany model pojazdów: {v_model}")
            
            if "plate" in mode or "combined" in mode:
                p_model = self.plate_model_var.get()
                if p_model == "Custom":
                    plate_path = Path(self.plate_custom_var.get())
                    if not plate_path.exists():
                        raise FileNotFoundError("Custom model tablic nie istnieje. Wybierz plik.")
                    success, msg, stats = validate_model_file(plate_path)
                    if not success or not stats.get('keypoints', False):
                        raise ValueError(f"Custom model tablic niepoprawny (powinien być Pose z keypoints): {msg}")
                else:
                    if p_model in AVAILABLE_POSE_MODELS:
                        plate_path = Path(CONFIG.DEFAULT_MODELS_DIR) / AVAILABLE_POSE_MODELS[p_model]["file"]
                    else:
                        raise ValueError(f"Nieznany model tablic: {p_model}")
            
            if "vehicle" in mode:
                self.annotator = VehicleAnnotator(vehicle_path, conf, device)
            elif "plate" in mode:
                self.annotator = PlateAnnotator(plate_path, conf, device)
            else:  
                self.annotator = CombinedAnnotator(vehicle_path, plate_path, conf, conf, CONFIG.PLATE_INSIDE_THRESHOLD, device)
            
            success, msg = self.annotator.load_models()
            if not success:
                messagebox.showerror("Błąd", f"Nie można załadować modeli: {msg}")
                return
            
            self.is_processing = True
            self.app.set_processing(True)
            self.start_time = datetime.datetime.now()
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.app.update_status(f"Przetwarzanie na urządzeniu: {device.upper()}...", "play")
            
            thread = threading.Thread(target=self._process_thread, args=(input_dir, output_dir), daemon=True)
            thread.start()
            
        except Exception as e:
            messagebox.showerror("Błąd konfiguracji", str(e))
            logger.error(f"Błąd anotacji: {e}")
    
    def _process_thread(self, input_dir: Path, output_dir: Path):
        try:
            def progress_cb(current, total, filename):
                pct = (current / total) * 100 if total > 0 else 0
                self.app.update_status(f"Przetworzono {current}/{total} ({pct:.1f}%) - {filename}", "play")
                self.log_text.insert(tk.END, f"{current}/{total}: {filename}\n")
                self.log_text.see(tk.END)
                self.parent.update_idletasks()
            
            annotations, report = self.annotator.process_directory(input_dir, progress_cb)
            
            xml_path = output_dir / "annotations.xml"
            exporter = CVATExporter("Auto-annotation")
            exporter.export(annotations, xml_path)
            
            report_path = output_dir / "report.txt"
            ReportGenerator.generate_text_report(report, report_path)
            
            csv_path = output_dir / "results.csv"
            ReportGenerator.generate_csv_report(annotations, csv_path)
            
            failed_path = output_dir / "failed_images.txt"
            ReportGenerator.generate_failed_images_list(report, failed_path)
            
            self._finish_processing(success=True, report=report, output_dir=output_dir)
            
        except Exception as e:
            logger.error(f"Błąd przetwarzania: {e}")
            self._finish_processing(success=False, error=str(e))
    
    def _finish_processing(self, success: bool, report: Optional[AnnotationReport] = None, output_dir: Optional[Path] = None, error: str = ""):
        self.is_processing = False
        if self.annotator:
            self.annotator.unload_models()
            self.annotator = None
        
        self.app.set_processing(False)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        
        if success:
            duration = format_duration((datetime.datetime.now() - self.start_time).total_seconds())
            self.app.update_status(f"Zakończono ({duration})", "success")
            self.log_text.insert(tk.END, f"\n{report.to_text()}\nWyniki w: {output_dir}\n")
            self.log_text.see(tk.END)
            messagebox.showinfo("Sukces", f"Anotacja zakończona!\n\n{report.to_text()}")
        else:
            self.app.update_status(f"Błąd: {error}", "error")
            messagebox.showerror("Błąd", error)
    
    def _stop_annotation(self):
        self.is_processing = False
        self.app.set_processing(False)
        self.app.update_status("Zatrzymano", "stop")
        messagebox.showinfo("Zatrzymano", "Anotacja zatrzymana. Modele zostaną zwolnione.")