#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Autoanotacja - Główne przetwarzanie YOLO (pojazdy + tablice)
Układ 3-kolumnowy.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
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
from ..validators import validate_model_file
from .help_manager import HELP

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
        self.export_format_var = tk.StringVar(value="CVAT + YOLO Pose (plate4)")
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
        self._on_mode_change() # Wymuszenie odświeżenia UI na starcie

    def _get_available_devices(self):
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    name = torch.cuda.get_device_name(i)
                    devices.append(f"cuda:{i} ({name})")
        except: pass
        return devices

    def _device_to_ultralytics(self, device_str: str):
        if not device_str or device_str == "auto": return "auto"
        if device_str == "cpu": return "cpu"
        if device_str.startswith("cuda:"):
            try: return int(device_str.split(":")[1].split()[0])
            except: return 0
        return "auto"

    def _create_widgets(self):
        pane = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_frame = ttk.Frame(pane)
        center_frame = ttk.Frame(pane)
        right_frame = ttk.Frame(pane)

        # Proporcje kolumn
        pane.add(left_frame, weight=2)
        pane.add(center_frame, weight=3)
        pane.add(right_frame, weight=2)

        # ==========================================================
        # LEWA KOLUMNA: Ścieżki i Przetwarzanie
        # ==========================================================
        paths_lf = ttk.LabelFrame(left_frame, text=" Ścieżki danych ", padding=15)
        paths_lf.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(paths_lf, text="Folder wejściowy (obrazy):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row = ttk.Frame(paths_lf)
        row.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(row, textvariable=self.input_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Wybierz", command=self._select_input_dir).pack(side=tk.RIGHT, padx=(5,0))

        ttk.Label(paths_lf, text="Katalog docelowy (tworzony automatycznie):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row = ttk.Frame(paths_lf)
        row.pack(fill=tk.X, pady=(0, 5))
        
        # Wymuszamy domyślną ścieżkę z Configu
        self.output_dir_var.set(str(Path(CONFIG.DIR_2_AUTO_ANN)))
        
        # Tworzymy zablokowane pole (tylko do odczytu)
        entry_out = ttk.Entry(row, textvariable=self.output_dir_var, state="readonly")
        entry_out.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Brak przycisku "Wybierz" - pełna automatyzacja!

        actions_lf = ttk.LabelFrame(left_frame, text=" Przetwarzanie YOLO ", padding=15)
        actions_lf.pack(fill=tk.X)

        self.start_btn = ttk.Button(actions_lf, text="STARTUJ – AUTOANOTACJĘ", command=self._start_annotation, style="Accent.TButton")
        self.start_btn.pack(fill=tk.X, pady=5, ipady=4)

        self.stop_btn = ttk.Button(actions_lf, text="ZATRZYMAJ", command=self._stop_annotation, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X, pady=5)

        self.progress = ttk.Progressbar(actions_lf, mode='determinate', maximum=100)
        self.progress.pack(fill=tk.X, pady=(15, 5))

        self.status_label = ttk.Label(actions_lf, text="Gotowy", foreground="#2ecc71", font=("Segoe UI", 10, "bold"))
        self.status_label.pack(anchor=tk.W)

        # ==========================================================
        # ŚRODKOWA KOLUMNA: Logi
        # ==========================================================
        logs_lf = ttk.LabelFrame(center_frame, text=" Logi systemu YOLO ", padding=10)
        logs_lf.pack(fill=tk.BOTH, expand=True, padx=10)

        self.log_text = scrolledtext.ScrolledText(logs_lf, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self._redirect_logs()

        # ==========================================================
        # PRAWA KOLUMNA: Ustawienia
        # ==========================================================
        settings_lf = ttk.LabelFrame(right_frame, text=" Konfiguracja Detekcji ", padding=15)
        settings_lf.pack(fill=tk.BOTH, expand=True)

        # --- Tryb ---
        ttk.Label(settings_lf, text="Tryb pracy:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        modes = ["A: Tylko pojazdy", "B: Tylko tablice", "C: Pojazdy + tablice"]
        self.mode_combo = ttk.Combobox(settings_lf, textvariable=self.mode_var, values=modes, state="readonly")
        self.mode_combo.pack(fill=tk.X, pady=(0, 15))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        # --- Pojazdy ---
        self.veh_frame = ttk.LabelFrame(settings_lf, text=" Model Pojazdów (Detect) ", padding=10)
        self.veh_frame.pack(fill=tk.X, pady=(0, 10))
        self.vehicle_combo = ttk.Combobox(self.veh_frame, textvariable=self.vehicle_model_var, state="readonly")
        self.vehicle_combo.pack(fill=tk.X, pady=2)
        self.vehicle_combo.bind("<<ComboboxSelected>>", self._on_vehicle_model_change)
        
        self.veh_custom_row = ttk.Frame(self.veh_frame)
        ttk.Entry(self.veh_custom_row, textvariable=self.vehicle_custom_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self.veh_custom_row, text="Wybierz .pt", command=self._select_vehicle_custom).pack(side=tk.RIGHT, padx=(5,0))
        self.veh_custom_row.pack(fill=tk.X, pady=(5,0))

        # --- Tablice ---
        self.pla_frame = ttk.LabelFrame(settings_lf, text=" Model Tablic (Pose) ", padding=10)
        self.pla_frame.pack(fill=tk.X, pady=(0, 10))
        self.plate_combo = ttk.Combobox(self.pla_frame, textvariable=self.plate_model_var, state="readonly")
        self.plate_combo.pack(fill=tk.X, pady=2)
        self.plate_combo.bind("<<ComboboxSelected>>", self._on_plate_model_change)
        
        self.pla_custom_row = ttk.Frame(self.pla_frame)
        ttk.Entry(self.pla_custom_row, textvariable=self.plate_custom_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self.pla_custom_row, text="Wybierz .pt", command=self._select_plate_custom).pack(side=tk.RIGHT, padx=(5,0))
        self.pla_custom_row.pack(fill=tk.X, pady=(5,0))

        # --- Parametry Ogólne ---
        param_frame = ttk.LabelFrame(settings_lf, text=" Parametry ", padding=10)
        param_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(param_frame, text="Pewność (Confidence):").pack(anchor=tk.W)
        row = ttk.Frame(param_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Scale(row, from_=0.1, to=0.9, variable=self.conf_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        lbl_conf = ttk.Label(row, width=4)
        lbl_conf.pack(side=tk.RIGHT, padx=(5,0))
        self.conf_var.trace_add("write", lambda *a: lbl_conf.config(text=f"{self.conf_var.get():.2f}"))
        lbl_conf.config(text=f"{self.conf_var.get():.2f}")

        ttk.Label(param_frame, text="Urządzenie (Device):").pack(anchor=tk.W, pady=(10, 0))
        self.device_combo = ttk.Combobox(param_frame, textvariable=self.device_var, values=self._get_available_devices(), state="readonly")
        self.device_combo.pack(fill=tk.X, pady=2)

        # --- Eksport ---
        exp_frame = ttk.LabelFrame(settings_lf, text=" Eksport po procesie ", padding=10)
        exp_frame.pack(fill=tk.X)
        
        ttk.Label(exp_frame, text="Zapisz jako:").pack(anchor=tk.W)
        ttk.Combobox(exp_frame, textvariable=self.export_format_var, state="readonly",
                     values=["CVAT XML 1.1", "YOLO Pose (plate4)", "CVAT + YOLO Pose (plate4)"]).pack(fill=tk.X, pady=2)
        ttk.Checkbutton(exp_frame, text="Kopiuj obrazy do zestawu YOLO", variable=self.copy_images_yolo_var).pack(anchor=tk.W, pady=(5,0))
        # ✅ PODPIĘCIE SYSTEMU POMOCY DO ZAKŁADKI 1
        from .help_manager import HELP
        HELP.bind_help(self.mode_combo, "tab1_mode")
        HELP.bind_help(row, "tab1_conf") # Podpinamy pod cały rządek suwaka pewności
        HELP.bind_help(self.device_combo, "tab1_device")
        HELP.bind_help(self.start_btn, "tab1_start")

    # ==========================================================
    # LOGIKA INTERFEJSU
    # ==========================================================

    def _on_mode_change(self, event=None):
        """Włącza/wyłącza ramki modeli w zależności od trybu."""
        mode = self.mode_var.get()
        
        # Pojazdy
        if "A:" in mode or "C:" in mode:
            self.vehicle_combo.config(state="readonly")
            self._on_vehicle_model_change() # Aktualizuje widoczność custom entry
        else:
            self.vehicle_combo.config(state=tk.DISABLED)
            self.veh_custom_row.pack_forget()

        # Tablice
        if "B:" in mode or "C:" in mode:
            self.plate_combo.config(state="readonly")
            self._on_plate_model_change()
        else:
            self.plate_combo.config(state=tk.DISABLED)
            self.pla_custom_row.pack_forget()

    def _update_model_lists(self):
        if YOLO_AVAILABLE:
            v_keys = sorted(list(AVAILABLE_DETECT_MODELS.keys()))
            self.vehicle_combo['values'] = v_keys + ["Custom"]
            if not self.vehicle_model_var.get() and v_keys: 
                self.vehicle_model_var.set(v_keys[0])
            
            p_keys = sorted(list(AVAILABLE_POSE_MODELS.keys()))
            self.plate_combo['values'] = p_keys + ["Custom"]
            if not self.plate_model_var.get() and p_keys: 
                # Preferujemy yolo11s-pose jako default do tablic
                self.plate_model_var.set("yolo11s-pose" if "yolo11s-pose" in p_keys else p_keys[0])

    def _on_vehicle_model_change(self, event=None):
        if self.vehicle_model_var.get() == "Custom" and str(self.vehicle_combo.cget("state")) != "disabled":
            self.veh_custom_row.pack(fill=tk.X, pady=(5,0))
        else:
            self.veh_custom_row.pack_forget()

    def _on_plate_model_change(self, event=None):
        if self.plate_model_var.get() == "Custom" and str(self.plate_combo.cget("state")) != "disabled":
            self.pla_custom_row.pack(fill=tk.X, pady=(5,0))
        else:
            self.pla_custom_row.pack_forget()

    def _select_vehicle_custom(self):
        p = filedialog.askopenfilename(filetypes=[("YOLO Model", "*.pt")])
        if p: self.vehicle_custom_var.set(p)

    def _select_plate_custom(self):
        p = filedialog.askopenfilename(filetypes=[("YOLO Model", "*.pt")])
        if p: self.plate_custom_var.set(p)

    def _select_input_dir(self):
        p = filedialog.askdirectory()
        if p: self.input_dir_var.set(p)

    def _redirect_logs(self):
        """Kieruje główne logi aplikacji do okienka tekstowego."""
        class TextHandler(logging.Handler):
            def __init__(self, widget):
                super().__init__()
                self.widget = widget
                
            def emit(self, record):
                try:
                    if self.widget.winfo_exists():
                        msg = self.format(record)
                        # ✅ ZMIANA: Zlecamy wpisanie tekstu głównemu wątkowi (after)
                        self.widget.after(0, self._safe_insert, msg)
                except: pass
                
            def _safe_insert(self, msg):
                # Ta metoda wykona się bezpiecznie w wątku UI
                try:
                    if self.widget.winfo_exists():
                        self.widget.insert(tk.END, msg + "\n")
                        self.widget.see(tk.END)
                except: pass
                
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s', '%H:%M:%S'))
        logger.addHandler(handler)


    # ==========================================================
    # LOGIKA PRZETWARZANIA YOLO
    # ==========================================================

    def _validate_models(self):
        mode = self.mode_var.get()
        
        if "A:" in mode or "C:" in mode:
            if self.vehicle_model_var.get() == "Custom":
                p = self.vehicle_custom_var.get()
                if not p or not Path(p).exists(): raise ValueError("Nie znaleziono własnego modelu pojazdów!")
                if not validate_model_file(Path(p))[0]: raise ValueError("Model pojazdów jest uszkodzony!")
        
        if "B:" in mode or "C:" in mode:
            if self.plate_model_var.get() == "Custom":
                p = self.plate_custom_var.get()
                if not p or not Path(p).exists(): raise ValueError("Nie znaleziono własnego modelu tablic!")
                if not validate_model_file(Path(p))[0]: raise ValueError("Model tablic jest uszkodzony!")

    def _get_model_path(self, model_type: str) -> Path:
        if model_type == "vehicle":
            if self.vehicle_model_var.get() == "Custom":
                return Path(self.vehicle_custom_var.get())
            else:
                f = AVAILABLE_DETECT_MODELS[self.vehicle_model_var.get()]["file"]
                return Path(CONFIG.DEFAULT_MODELS_DIR) / f
        else:
            if self.plate_model_var.get() == "Custom":
                return Path(self.plate_custom_var.get())
            else:
                f = AVAILABLE_POSE_MODELS[self.plate_model_var.get()]["file"]
                return Path(CONFIG.DEFAULT_MODELS_DIR) / f

    def _start_annotation(self):
        in_d = self.input_dir_var.get().strip()
        if not in_d or not Path(in_d).exists():
            messagebox.showerror("Błąd", "Wybierz folder z obrazami wejściowymi.")
            return
        
        try:
            self._validate_models()
            
            mode_text = self.mode_var.get()
            conf = self.conf_var.get()
            raw_dev = self.device_var.get().split()[0].lower()
            dev = self._device_to_ultralytics(raw_dev)
            
            v_p = self._get_model_path("vehicle") if ("A:" in mode_text or "C:" in mode_text) else None
            p_p = self._get_model_path("plate") if ("B:" in mode_text or "C:" in mode_text) else None

            # ✅ ZMIANA: Zwalniamy stary model z VRAM zanim załadujemy nowy
            if self.annotator is not None:
                try:
                    self.annotator.unload_models()
                except:
                    pass

            if "A:" in mode_text:
                self.annotator = VehicleAnnotator(v_p, conf, dev)
            elif "B:" in mode_text:
                self.annotator = PlateAnnotator(p_p, conf, dev)
            else:
                self.annotator = CombinedAnnotator(v_p, p_p, conf, conf, CONFIG.PLATE_INSIDE_THRESHOLD, dev)
            
            success, msg = self.annotator.load_models()
            if not success:
                raise RuntimeError(f"Błąd silnika YOLO: {msg}")

            self.is_processing = True
            self.app.set_processing(True)
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.progress['value'] = 0
            
            logger.info("="*50)
            logger.info("ROZPOCZĘTO AUTOANOTACJĘ OBRAZÓW (YOLO)")
            logger.info("="*50)
            
            threading.Thread(target=self._process_thread, args=(Path(in_d), Path(self.output_dir_var.get())), daemon=True).start()
            
        except Exception as e:
            logger.error(f"Nie można wystartować: {e}")
            messagebox.showerror("Błąd Startu", str(e))

    def _process_thread(self, in_dir: Path, base_out_dir: Path):
        success = False
        message = ""
        
        try:
            total_images = count_images_in_directory(in_dir)
            if total_images == 0:
                self.frame.after(0, lambda: self._finish(False, "Brak obrazów we wskazanym folderze wejściowym."))
                return
                
            logger.info(f"Znaleziono {total_images} obrazów do przetworzenia.")
            self.start_time = datetime.datetime.now()
            
            def prog_cb(current, total, filename):
                if not self.is_processing:
                    raise KeyboardInterrupt("Anulowano")
                pct = (current / total) * 100 if total > 0 else 0
                self.frame.after(0, lambda: self._update_progress(pct, current, total, filename))
            
            # URUCHOMIENIE ANOTATORA
            annotations, report = self.annotator.process_directory(in_dir, prog_cb)
            
            if self.annotator.is_stopped() or not self.is_processing:
                message = "Przetwarzanie przerwane przez użytkownika."
                success = False
                return

            # =======================================================
            # GENEROWANIE UNIKALNEGO FOLDERU "RUN"
            # =======================================================
            # =======================================================
            # GENEROWANIE UNIKALNEGO FOLDERU "RUN" (Z DATĄ I CZASEM)
            # =======================================================
            base_out_dir.mkdir(parents=True, exist_ok=True)
            
            # Pobierz aktualną datę i godzinę (np. 20241026_143025)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            counter = 1
            while True:
                # Format: run_001_20241026_143025
                run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}"
                if not run_dir.exists():
                    break
                counter += 1
                
            run_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Utworzono unikalny folder na wyniki: {run_dir.name}")

            fmt = self.export_format_var.get()
            
            # Ścieżka do XML żyje w bezpiecznym, nowym folderze
            cvat_xml_path = run_dir / "annotations.xml"

            if "CVAT" in fmt:
                logger.info("Zapisywanie CVAT XML...")
                CVATExporter().export(annotations, cvat_xml_path)
                
            if "YOLO" in fmt:
                logger.info("Zapisywanie YOLO Dataset...")
                y_out = run_dir / "yolo_dataset"
                YOLOPosePlate4Exporter(copy_images=self.copy_images_yolo_var.get()).export(annotations, in_dir, y_out)

            logger.info("Generowanie raportu statystycznego...")
            ReportGenerator.generate_text_report(report, run_dir / "report.txt")

            # Automatyczny Export do ZIP (jeśli zaznaczono opcję na GUI)
            if "CVAT" in fmt and getattr(self, 'create_zip_var', None) and self.create_zip_var.get():
                logger.info("Pakowanie danych do formatu .ZIP dla CVAT...")
                from auto_annotation_tool.cvat_tools.cvat_zip_manager import CVATZipManager
                
                zip_output_file = run_dir / f"CVAT_Import_Ready_{run_dir.name}.zip"
                ok, zip_msg = CVATZipManager.create_cvat_import_zip(
                    xml_path=cvat_xml_path,
                    images_dir=in_dir, 
                    output_zip_path=zip_output_file
                )
                if ok: logger.info(f"✅ {zip_msg}")
                else: logger.error(f"❌ {zip_msg}")

            # Bezpieczne obliczanie czasu (zabezpieczone .total_seconds() przed blędem datetime)
            elapsed = format_duration((datetime.datetime.now() - self.start_time).total_seconds())
            message = f"Zakończono! Zapisano do: {run_dir.name} (w czasie {elapsed})"
            logger.info(f"✅ {message}")
            success = True
            
        except KeyboardInterrupt:
            message = "Anulowano przez użytkownika."
            logger.warning(message)
            success = False
        except Exception as e:
            logger.exception("Błąd w trakcie przetwarzania obrazów.")
            message = f"Krytyczny błąd: {e}"
            success = False
        finally:
            self.frame.after(0, lambda: self._finish(success, message))

    def _update_progress(self, pct, current, total, filename):
        self.progress['value'] = pct
        self.status_label.config(text=f"Przetwarzanie {current}/{total} ({int(pct)}%)")

    def _finish(self, success, msg):
        self.is_processing = False
        self.app.set_processing(False)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.progress['value'] = 100 if success else 0
        
        if success:
            self.status_label.config(text="Zakończono pomyślnie!", foreground="#2ecc71")
            messagebox.showinfo("Koniec", msg)
        else:
            self.status_label.config(text="Przerwano / Błąd", foreground="#e74c3c")
            messagebox.showerror("Zatrzymano", msg)

    def _stop_annotation(self):
        self.is_processing = False
        if self.annotator and hasattr(self.annotator, 'stop'):
            self.annotator.stop()
        self.status_label.config(text="Zatrzymywanie...", foreground="#e67e22")