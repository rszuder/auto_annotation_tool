#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka ZNAKÓW.
Logicznie podzielona na:
1. Wycinanie tablic (surowe)
2. Wykrywanie znaków i Analiza (OCR/YOLO, Laboratorium Filtrów, Turniej z Cache)
3. CVAT Export/Import
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
from pathlib import Path
import threading
import xml.etree.ElementTree as ET
import json
import cv2
import numpy as np
import os

# Importy lokalne
from ..config import CONFIG, logger, CV2_AVAILABLE
try:
    from ..config import SESSION
except ImportError:
    SESSION = None

from ..icons import IconManager
from ..character_recognition import (
    PlateGenerator, CharacterDetector, CharacterAnnotator, DetectionMethod
)
from ..ocr import PlateOCR
from ..data_models import ImageAnnotation, Detection

from .help_manager import HELP

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class CharacterAnnotationTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)
        
        self.is_processing = False
        self.preview_metadata = {}
        self.preview_plate_ids = []
        self._current_photo = None 
        self.help_var = tk.StringVar(value="Gotowy")
        
        self.presets_dir = Path(CONFIG.WORKSPACE_DIR) / "8_ocr_presets"
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        
        # --- BEZPIECZNE ŁADOWANIE SESJI ---
        self.session_file = Path.home() / ".auto_annotation_tool" / "char_tab_session.json"
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.local_session = self._load_local_session()

        def get_val(key, default):
            val = self.local_session.get(key, default)
            return val if val != "" else default

        # Zmienne główne
        self.detection_method_var = tk.StringVar(value=get_val("char_det_method", "OCR"))
        self.xml_path_var = tk.StringVar(value=get_val("char_xml_path", ""))
        self.images_dir_var = tk.StringVar(value=get_val("char_images_dir", ""))
        self.yolo_model_path_var = tk.StringVar(value=get_val("char_yolo_model", ""))
        self.yolo_device_var = tk.StringVar(value=get_val("char_yolo_device", "auto"))
        self.preview_dir_var = tk.StringVar(value=get_val("char_preview_dir", ""))
        self.ocr_conf_var = tk.DoubleVar(value=float(get_val("char_ocr_conf", 0.25)))
        self.smart_export_var = tk.BooleanVar(value=get_val("char_smart_export", True))
        
        # Zmienne Laboratorium OCR
        self.prep_angle_var = tk.DoubleVar(value=float(get_val("char_prep_angle", 0.0)))
        self.prep_height_var = tk.IntVar(value=int(get_val("char_prep_height", 80)))
        self.prep_clip_var = tk.IntVar(value=int(get_val("char_prep_clip", 255)))
        self.prep_denoise_var = tk.IntVar(value=int(get_val("char_prep_denoise", 0)))
        self.prep_clahe_var = tk.DoubleVar(value=float(get_val("char_prep_clahe", 0.0)))
        self.prep_use_bin_var = tk.BooleanVar(value=get_val("char_prep_use_bin", True))
        self.prep_block_var = tk.IntVar(value=int(get_val("char_prep_block", 15)))
        self.prep_c_var = tk.IntVar(value=int(get_val("char_prep_c", 5)))
        self.prep_erode_var = tk.IntVar(value=int(get_val("char_prep_erode", 0)))
        self.do_deskew_var = tk.BooleanVar(value=get_val("char_do_deskew", True))
        self.do_clahe_var = tk.BooleanVar(value=get_val("char_do_clahe", True))
        self.interpolation_var = tk.StringVar(value=get_val("char_interpolation", "lanczos4"))

        self._create_widgets()

        from .help_manager import HELP
        HELP.status_updater = self._set_help
        
        self._update_yolo_visibility()
        self.app.root.bind("<Destroy>", self._on_app_close, add="+")
        
        # Ciche wczytywanie zapamiętanej paczki po starcie
        if self.preview_dir_var.get().strip():
            self.frame.after(100, lambda: self._load_preview_data(quiet=True))

    # ============================================================
    # SYSTEM SESJI & HELPERY
    # ============================================================
    def _load_local_session(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f: return json.load(f)
            except Exception: pass
        return {}

    def _save_local_setting(self, key, value):
        self.local_session[key] = value
        try:
            with open(self.session_file, 'w', encoding='utf-8') as f: json.dump(self.local_session, f, indent=4)
        except Exception: pass

    def _force_save_all(self):
        try:
            for k, var in [
                ("char_det_method", self.detection_method_var), ("char_xml_path", self.xml_path_var),
                ("char_images_dir", self.images_dir_var), ("char_yolo_model", self.yolo_model_path_var),
                ("char_yolo_device", self.yolo_device_var), ("char_preview_dir", self.preview_dir_var),
                ("char_ocr_conf", self.ocr_conf_var), ("char_smart_export", self.smart_export_var),
                ("char_prep_angle", self.prep_angle_var), ("char_prep_height", self.prep_height_var),
                ("char_prep_clip", self.prep_clip_var), ("char_prep_denoise", self.prep_denoise_var),
                ("char_prep_clahe", self.prep_clahe_var), ("char_prep_use_bin", self.prep_use_bin_var),
                ("char_prep_block", self.prep_block_var), ("char_prep_c", self.prep_c_var),
                ("char_prep_erode", self.prep_erode_var), ("char_do_deskew", self.do_deskew_var),
                ("char_do_clahe", self.do_clahe_var), ("char_interpolation", self.interpolation_var)
            ]:
                self._save_local_setting(k, var.get())
        except Exception: pass

    def _on_app_close(self, event):
        if str(event.widget) == str(self.app.root): self._force_save_all()

    def _on_method_change(self, event=None):
        self._update_yolo_visibility()

    def _update_yolo_visibility(self):
        method = self.detection_method_var.get()
        if hasattr(self, 'yolo_labelframe'):
            if method in ["YOLO", "BOTH"]: self.yolo_labelframe.pack(fill=tk.X, pady=(0, 10))
            else: self.yolo_labelframe.pack_forget()

    def _get_available_devices(self):
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()): devices.append(f"cuda:{i}")
        except: pass
        return devices

    def _device_to_ultralytics(self, s: str):
        if s == "auto": return "auto"
        if s == "cpu": return "cpu"
        if s.startswith("cuda:"):
            try: return int(s.split(":")[1].split()[0])
            except: return 0
        return "auto"

    def _pick_xml_file(self):
        p = filedialog.askopenfilename(title="Wybierz annotations.xml", filetypes=[("XML", "*.xml")])
        if p: self.xml_path_var.set(p)

    def _pick_images_dir(self):
        p = filedialog.askdirectory(title="Wybierz folder z obrazami pojazdów")
        if p: self.images_dir_var.set(p)

    def _pick_yolo_model(self):
        p = filedialog.askopenfilename(title="Wybierz model YOLO (.pt)", filetypes=[("PyTorch", "*.pt")])
        if p: self.yolo_model_path_var.set(p)

    def _pick_and_load_preview_dir(self):
        p = filedialog.askdirectory(title="Wybierz folder wyników (zawierający metadata.json)")
        if p:
            self.preview_dir_var.set(p)
            self._force_save_all()
            self._load_preview_data()

    def _stop_processing(self):
        self.is_processing = False
        self._log(self.log_text, "\nOtrzymano żądanie przerwania...", "WARNING")
        self._update_status("Zatrzymuję po obecnym pliku...", "#e67e22")

    def _log(self, txt_widget, msg: str, tag: str = "INFO"):
        def do_log():
            if not txt_widget.tag_names():
                txt_widget.tag_config("SUCCESS", foreground="#27ae60", font=("Consolas", 9, "bold"))
                txt_widget.tag_config("ERROR", foreground="#c0392b", font=("Consolas", 9, "bold"))
                txt_widget.tag_config("WARNING", foreground="#d35400", font=("Consolas", 9, "bold"))
                txt_widget.tag_config("INFO", foreground="#2980b9", font=("Consolas", 9))
                txt_widget.tag_config("HEADER", foreground="#8e44ad", font=("Consolas", 10, "bold"))

            final_tag = tag
            if tag == "INFO":
                if "✅" in msg or "SUKCES" in msg or "[OK]" in msg: final_tag = "SUCCESS"
                elif "❌" in msg or "BŁĄD" in msg or "[ERR]" in msg: final_tag = "ERROR"
                elif "⚠️" in msg: final_tag = "WARNING"
                elif "===" in msg or "🚀" in msg or "🏆" in msg: final_tag = "HEADER"
            txt_widget.insert(tk.END, msg + "\n", final_tag)
            txt_widget.see(tk.END)
        self.frame.after(0, do_log)

    def _update_status(self, text: str, color: str = "#2ecc71"):
        self.frame.after(0, lambda: self.status_label.config(text=text, foreground=color))

    def _update_progress(self, value: float):
        self.frame.after(0, lambda: self.progress.config(value=value))

    def _set_help(self, text: str):
        self.help_var.set(text)    

    def _get_true_texts_from_filename(self, filename: str) -> list:
        stem = Path(filename).stem.upper()
        parts = stem.split('_')
        if len(parts) == 1:
            clean = "".join([c for c in parts[0] if c.isalnum()])
            return [clean] if clean else []
        true_plates = ["".join([c for c in p if c.isalnum()]) for p in parts[:-1] if "".join([c for c in p if c.isalnum()])]
        if not true_plates:
            clean = "".join([c for c in parts[-1] if c.isalnum()])
            if clean: true_plates.append(clean)
        return true_plates

    def _get_current_prep_params(self):
        return {
            "target_height": self.prep_height_var.get(), "manual_angle": self.prep_angle_var.get(),
            "clip_thresh": self.prep_clip_var.get(), "denoise_h": self.prep_denoise_var.get(),
            "clahe_clip": self.prep_clahe_var.get() if self.do_clahe_var.get() else 0.0, 
            "use_binarization": self.prep_use_bin_var.get(),
            "thresh_block": self.prep_block_var.get(), "thresh_c": self.prep_c_var.get(),
            "erode_iter": self.prep_erode_var.get(), "interpolation": self.interpolation_var.get()
        }

    def _get_best_preset(self):
        """Pobiera z pliku cache dane najlepszego presetu."""
        out_dir = Path(self.preview_dir_var.get().strip())
        cache_file = out_dir / "ranking_cache.json"
        
        if not cache_file.exists(): 
            return None, 0.0
            
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if not data: 
                return None, 0.0
                
            best_name = None
            best_acc = -1.0
            best_params = {}
            
            # Wyszukiwanie Lidera w słowniku Cache
            for preset_key, stats in data.items():
                # Zabezpieczenie przed uszkodzonymi/starymi wpisami w jsonie
                acc = float(stats.get("acc", 0.0))
                if acc > best_acc:
                    best_acc = acc
                    best_name = str(stats.get("name", preset_key)) # Pobiera 'name' lub klucz główny
                    best_params = stats.get("params", {})
                    
            if best_name:
                # Sklejamy to w zgrabny słownik, który na pewno zadziała, nawet jeśli params są puste (bo był to "Ostatni Test")
                result = {
                    "name": best_name,
                    "params": best_params if isinstance(best_params, dict) else {}
                }
                return result, best_acc
                
        except Exception as e:
            logger.debug(f"Błąd odczytu Lidera z cache: {e}")
            
        return None, 0.0

    # ============================================================
    # TWORZENIE GUI
    # ============================================================
    def _create_widgets(self):
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        tab1 = ttk.Frame(self.main_nb)
        self.main_nb.add(tab1, text=f"{self.icon_manager.get('cut')} 1. Wycinanie Tablic")
        self._build_extraction_tab(tab1)
        
        tab2 = ttk.Frame(self.main_nb)
        self.main_nb.add(tab2, text=f"{self.icon_manager.get('eye')} 2. Wykrywanie Znaków i Analiza")
        self._build_detection_tab(tab2)
        
        tab3 = ttk.Frame(self.main_nb)
        self.main_nb.add(tab3, text=f"{self.icon_manager.get('save')} 3. Eksport CVAT")
        self._build_cvat_tab(tab3)
        help_bar = ttk.Label(
            self.frame,
            textvariable=self.help_var,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        help_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 4))        

    # ============================================================
    # ZAKŁADKA 1: TYLKO WYCINANIE TABLIC
    # ============================================================
    def _build_extraction_tab(self, parent):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)

        lf_paths = ttk.LabelFrame(left, text=" Ścieżki do źródła ", padding=15)
        lf_paths.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(lf_paths, text="annotations.xml (z Zakładki Autoanotacja):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row = ttk.Frame(lf_paths)
        row.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(row, textvariable=self.xml_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Wybierz", command=self._pick_xml_file).pack(side=tk.RIGHT, padx=(5,0))

        ttk.Label(lf_paths, text="Folder ze zdjęciami aut (źródło):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row = ttk.Frame(lf_paths)
        row.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(row, textvariable=self.images_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Wybierz", command=self._pick_images_dir).pack(side=tk.RIGHT, padx=(5,0))

        lf_run = ttk.LabelFrame(left, text=" Wycinanie Tablic ", padding=15)
        lf_run.pack(fill=tk.X)
        
        ttk.Label(lf_run, text="Zapis do: Workspace/3_cropped_characters/run_XXX", foreground="gray").pack(anchor=tk.W, pady=(0,10))

        self.btn_extract = ttk.Button(lf_run, text="START (Wytnij tablice z paczki)", command=self._run_extraction, style="Accent.TButton")
        self.btn_extract.pack(fill=tk.X, ipady=5)

        self.btn_ext_stop = ttk.Button(lf_run, text="ZATRZYMAJ", command=lambda: setattr(self, 'is_processing', False), state=tk.DISABLED)
        self.btn_ext_stop.pack(fill=tk.X, pady=5)

        self.ext_progress = ttk.Progressbar(lf_run, maximum=100)
        self.ext_progress.pack(fill=tk.X, pady=(15, 5))

        self.ext_status = ttk.Label(lf_run, text="Gotowy", foreground="#2ecc71", font=("Segoe UI", 10, "bold"))
        self.ext_status.pack(anchor=tk.W)

        lf_logs = ttk.LabelFrame(right, text=" Logi z Wycinania ", padding=10)
        lf_logs.pack(fill=tk.BOTH, expand=True)
        self.ext_log = scrolledtext.ScrolledText(lf_logs, wrap=tk.WORD, font=("Consolas", 10), bg="#fdfdfd")
        self.ext_log.pack(fill=tk.BOTH, expand=True)

    def _run_extraction(self):
        self._force_save_all()
        xml_path = Path(self.xml_path_var.get().strip())
        images_dir = Path(self.images_dir_var.get().strip())

        if not xml_path.exists() or not images_dir.exists():
            return messagebox.showerror("Błąd", "Brak plików wejściowych!")

        import datetime
        base_out_dir = Path(CONFIG.DIR_3_CHARS)
        base_out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        counter = 1
        while True:
            run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}"
            if not run_dir.exists(): break
            counter += 1
            
        run_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir_var.set(str(run_dir))
        self._force_save_all()

        try:
            tree = ET.parse(xml_path)
            xml_images = {img.get("name"): img for img in tree.getroot().findall(".//image") if img.get("name")}
        except: return messagebox.showerror("Błąd", "Zły plik XML.")

        self.btn_extract.config(state=tk.DISABLED)
        self.btn_ext_stop.config(state=tk.NORMAL)
        self.is_processing = True

        def worker():
            try:
                self._log(self.ext_log, f"\nROZPOCZĘTO WYCINANIE TABLIC DO: {run_dir.name}\n", "HEADER")
                generator = PlateGenerator(run_dir)
                total = len(xml_images)
                
                processed = 0
                self.generated_plates = 0
                for img_name, img_el in xml_images.items():
                    if not self.is_processing: 
                        self._log(self.ext_log, "\nPRZERWANO.", "WARNING")
                        break
                    
                    img_path = images_dir / img_name
                    if not img_path.exists(): 
                        processed += 1; continue

                    plates = []
                    for poly in img_el.findall(".//polygon[@label='plate']"):
                        pts = [tuple(map(float, p.split(","))) for p in poly.get("points", "").split(";")]
                        if len(pts) >= 4:
                            plates.append(Detection("plate", 1.0, (min(x for x,y in pts), min(y for x,y in pts), max(x for x,y in pts), max(y for x,y in pts)), polygon=pts))

                    if plates:
                        ann = ImageAnnotation(img_name, int(img_el.get("width",0)), int(img_el.get("height",0)), plates)
                        cropped = generator.generate_from_annotations(img_path, ann, rectify=True, do_deskew=False, enhance_contrast=False, interpolation=self.interpolation_var.get())
                        self.generated_plates += len(cropped)
                        
                        self._log(self.ext_log, f"Wykryto i wycięto: {len(cropped)} tablic z obrazka {img_name}", "INFO")

                    processed += 1
                    self.frame.after(0, lambda p=(processed/total)*100: self.ext_progress.config(value=p))
                    self.frame.after(0, lambda c=processed, t=total, gp=self.generated_plates: self.ext_status.config(text=f"{c}/{t} obrazów... Wycięto {gp} tablic"))

                generator.save_metadata()
                if self.is_processing:
                    self._log(self.ext_log, f"\n✅ ZAKOŃCZONO. Wycięto łącznie {self.generated_plates} tablic.\n", "SUCCESS")
                    self.frame.after(0, lambda: self._load_preview_data(quiet=True))
                    self.frame.after(0, lambda: messagebox.showinfo("Gotowe", "Wycinanie zakończone!\nWygenerowana paczka została wczytana do zakładki 'Wykrywanie Znaków'."))

            except Exception as e:
                self._log(self.ext_log, f"\n❌ BŁĄD: {e}\n", "ERROR")
            finally:
                self.is_processing = False
                self.frame.after(0, lambda: self.btn_extract.config(state=tk.NORMAL))
                self.frame.after(0, lambda: self.btn_ext_stop.config(state=tk.DISABLED))

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # ZAKŁADKA 2: WYKRYWANIE ZNAKÓW I ANALIZA
    # ============================================================
    def _build_detection_tab(self, parent):
        top_frame = ttk.Frame(parent)
        top_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(top_frame, text="Paczka do analizy (folder run_XXX):", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Entry(top_frame, textvariable=self.preview_dir_var, width=45, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        
        btn_pick = ttk.Button(top_frame, text="Otwórz inną paczkę z historii", command=self._pick_and_load_preview_dir)
        btn_pick.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(top_frame, text="(Szukaj w: Workspace/3_cropped_characters/)", font=("Segoe UI", 8, "italic"), foreground="gray").pack(side=tk.LEFT, padx=(0, 15))
        
        self.preview_info_lbl = ttk.Label(top_frame, text="Wczytano tablic: 0", font=("Segoe UI", 9, "bold"), foreground="#2980b9")
        self.preview_info_lbl.pack(side=tk.RIGHT, padx=10)

        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        left_frame = ttk.Frame(pane)
        center_frame = ttk.Frame(pane)
        right_frame = ttk.Frame(pane)
        pane.add(left_frame, weight=1)
        pane.add(center_frame, weight=2)
        pane.add(right_frame, weight=1)

        # LEWA: Lista tablic
        list_lf = ttk.LabelFrame(left_frame, text=" Lista tablic (🟢 Perfekt | 🔴 Błędy) ")
        list_lf.pack(fill=tk.BOTH, expand=True)

        self.plates_listbox = tk.Listbox(list_lf, font=("Consolas", 11), selectbackground="#3498db")
        self.plates_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5,0), pady=5)
        scroll = ttk.Scrollbar(list_lf, command=self.plates_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,5), pady=5)
        self.plates_listbox.config(yscrollcommand=scroll.set)
        self.plates_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

        # ŚRODEK: Podgląd Wizualny + Logi Testu
        preview_lf = ttk.LabelFrame(center_frame, text=" Podgląd OCR ")
        preview_lf.pack(fill=tk.X, expand=False, pady=(0, 10))
        
        self.preview_canvas = tk.Canvas(preview_lf, bg="#1e1e1e", height=180, bd=3, relief="sunken", highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=False, pady=8, padx=8)
        self.preview_canvas.bind("<Configure>", lambda e: self._on_preview_select(None))

        cols = ("znak", "metoda", "pewnosc")
        self.chars_tree = ttk.Treeview(center_frame, columns=cols, show="headings", height=5)
        self.chars_tree.heading("znak", text="Znak")
        self.chars_tree.heading("metoda", text="Metoda")
        self.chars_tree.heading("pewnosc", text="Pewność (%)")
        self.chars_tree.column("znak", width=80, anchor=tk.CENTER)
        self.chars_tree.column("metoda", width=100, anchor=tk.CENTER)
        self.chars_tree.column("pewnosc", width=80, anchor=tk.CENTER)
        self.chars_tree.pack(fill=tk.X, padx=5, pady=(0, 10))

        logs_test_lf = ttk.LabelFrame(center_frame, text=" Logi z Analizy i Testów ")
        logs_test_lf.pack(fill=tk.BOTH, expand=True)
        self.test_log_text = scrolledtext.ScrolledText(logs_test_lf, wrap=tk.WORD, font=("Consolas", 9), bg="#fcfcfc")
        self.test_log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # PRAWA: Zwycięzca, Ustawienia OCR / Laboratorium / Przyciski
        self.winner_lf = ttk.LabelFrame(right_frame, text=" Aktualny Lider ", padding=10)
        self.winner_lf.pack(fill=tk.X, pady=(0, 10))
        self.winner_name_lbl = ttk.Label(self.winner_lf, text="BRAK DANYCH Z TURNIEJU", font=("Segoe UI", 12, "bold"), foreground="gray")
        self.winner_name_lbl.pack(anchor=tk.CENTER)
        self.winner_acc_lbl = ttk.Label(self.winner_lf, text="Skuteczność: 0.0%", font=("Segoe UI", 10))
        self.winner_acc_lbl.pack(anchor=tk.CENTER)

        actions_lf = ttk.LabelFrame(right_frame, text=" Uruchom Przetwarzanie ", padding=15)
        actions_lf.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(actions_lf, text="Analizuj paczkę tablic:", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 8))
        
        self.btn_fast_ocr = ttk.Button(actions_lf, text="1. Szybki Test (Obecne Filtry z Labu)", command=self._run_fast_ocr_test, style="Accent.TButton")
        self.btn_fast_ocr.pack(fill=tk.X, ipady=6, pady=(0, 10))

        self.btn_rank_presets = ttk.Button(actions_lf, text="2. Turniej (Zbadaj paczkę wszystkimi Presetami)", command=self._run_preset_ranking)
        self.btn_rank_presets.pack(fill=tk.X, ipady=5)

        # ✅ NOWOŚĆ: PASEK POSTĘPU DLA TESTÓW
        self.test_progress = ttk.Progressbar(actions_lf, maximum=100)
        self.test_progress.pack(fill=tk.X, pady=(15, 5))
        self.test_status_lbl = ttk.Label(actions_lf, text="Gotowy do testów", foreground="#2ecc71", font=("Segoe UI", 9, "bold"))
        self.test_status_lbl.pack(anchor=tk.W)

        set_lf = ttk.LabelFrame(right_frame, text=" Konfiguracja Rozpoznawania ", padding=15)
        set_lf.pack(fill=tk.BOTH, expand=True)

        ttk.Label(set_lf, text="Metoda odczytu:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 5))
        combo = ttk.Combobox(set_lf, textvariable=self.detection_method_var, values=["OCR", "YOLO", "BOTH"], state="readonly")
        combo.pack(fill=tk.X, pady=(2, 10))
        combo.bind("<<ComboboxSelected>>", self._on_method_change)

        dev_row = ttk.Frame(set_lf)
        dev_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(dev_row, text="Urządzenie:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        dev_combo = ttk.Combobox(dev_row, textvariable=self.yolo_device_var, values=self._get_available_devices(), state="readonly", width=15)
        dev_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5,0))
        dev_combo.bind("<<ComboboxSelected>>", lambda e: self._force_save_all())

        self.yolo_panel = ttk.Frame(set_lf)
        ttk.Label(self.yolo_panel, text="Ścieżka do YOLO .pt:").pack(anchor=tk.W, pady=(5,0))
        r_y = ttk.Frame(self.yolo_panel)
        r_y.pack(fill=tk.X)
        ttk.Entry(r_y, textvariable=self.yolo_model_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(r_y, text="Wybierz", command=self._pick_yolo_model).pack(side=tk.RIGHT)

        if self.detection_method_var.get() not in ["YOLO", "BOTH"]:
            self.yolo_panel.pack_forget()
        else:
            self.yolo_panel.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Separator(set_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(15, 10))
        
        ttk.Button(set_lf, text="Laboratorium OCR (Ustaw Filtry & Presety)", command=self._open_filter_lab).pack(fill=tk.X, ipady=5)

        if not self.preview_plate_ids:
            intro_text = (
                "Witaj w module: Wykrywanie Znaków i Analiza!\n\n"
                "Aktualnie nie masz wczytanej żadnej paczki testowej do pamięci.\n\n"
                "Co powinieneś zrobić?\n"
                "  1. Przejdź do pierwszej pod-zakładki '1. Wycinanie Tablic'.\n"
                "     - Gdy algorytm wytnie tablice, wrócą one TU AUTOMATYCZNIE.\n"
                "     LUB\n"
                "  2. Kliknij przycisk 'Otwórz inną paczkę z historii' na samej górze.\n"
                "     - Przejdź do folderu 'Workspace/3_cropped_characters/'.\n"
                "     - Wybierz folder z Twojego poprzedniego eksperymentu (np. run_001_...).\n\n"
                "Gdy to zrobisz, będziesz mógł stroić filtry OCR w Laboratorium,\n"
                "a następnie przeprowadzać masowe testy celności (True Accuracy)!"
            )
            self._log(self.test_log_text, intro_text, "INFO")

    def _update_winner_label(self):
        """Aktualizuje pole Zwycięzcy z cache po każdym teście/turnieju."""
        best_preset_data, best_acc = self._get_best_preset()
        
        if best_preset_data and best_preset_data.get("name"):
            name = best_preset_data.get("name")
            self.winner_name_lbl.config(text=name.upper(), foreground="#27ae60")
            self.winner_acc_lbl.config(text=f"Skuteczność: {best_acc:.1f}%", foreground="black")
        else:
            self.winner_name_lbl.config(text="BRAK DANYCH Z TURNIEJU", foreground="gray")
            self.winner_acc_lbl.config(text="Skuteczność: 0.0%", foreground="gray")

    def _load_preview_data(self, quiet=False):
        out_dir = Path(self.preview_dir_var.get().strip())
        meta_path = out_dir / "metadata.json"
        
        # OD RAZU PRÓBA ODCZYTU LIDERA Z CACHE DLA BIEŻĄCEGO KATALOGU
        self.frame.after(0, self._update_winner_label)
        
        if not meta_path.exists():
            if not quiet: messagebox.showerror("Brak pliku", f"Nie znaleziono metadata.json w folderze:\n{out_dir}")
            self.preview_info_lbl.config(text="Brak wczytanych danych", foreground="red")
            
            if not quiet and not self.preview_plate_ids:
                intro_text = (
                    "Witaj w module: Wykrywanie Znaków i Analiza!\n\n"
                    "Aktualnie nie masz wczytanej żadnej paczki testowej do pamięci.\n\n"
                    "Co powinieneś zrobić?\n"
                    "  1. Przejdź do pierwszej pod-zakładki '1. Wycinanie Tablic'.\n"
                    "     - Gdy algorytm wytnie tablice, wrócą one TU AUTOMATYCZNIE.\n"
                    "     LUB\n"
                    "  2. Kliknij przycisk 'Otwórz inną paczkę z historii' na samej górze.\n"
                    "     - Wybierz folder z Twojego poprzedniego eksperymentu (np. run_001_...).\n\n"
                )
                self._log(self.test_log_text, intro_text, "INFO")
            return
            
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                self.preview_metadata = json.load(f)
                
            self.preview_plate_ids = list(self.preview_metadata.keys())
            self.plates_listbox.delete(0, tk.END)
            
            for pid in self.preview_plate_ids:
                data = self.preview_metadata[pid]
                chars = data.get("characters", [])
                status = data.get("status", "unknown")
                text = "".join([str(c.get("character", "?")) for c in chars])
                
                icon = "🟢" if status == "perfect" else "🔴" if status == "needs_fix" else "⚪"
                display_text = f"{icon} {pid} [{text}]"
                self.plates_listbox.insert(tk.END, display_text)
                
                if status == "perfect": self.plates_listbox.itemconfig(tk.END, {'fg': 'green'})
                elif status == "needs_fix": self.plates_listbox.itemconfig(tk.END, {'fg': 'red'})
                
            self.preview_info_lbl.config(text=f"Wczytano tablic: {len(self.preview_plate_ids)} z folderu: {out_dir.name}", foreground="green")
            
            if self.preview_plate_ids:
                self.plates_listbox.selection_set(0)
                self._on_preview_select(None)
                
            # Na koniec, jeszcze raz wymuszamy odświeżenie panelu zwycięzcy po wczytaniu GUI
            self.frame.after(100, self._update_winner_label)
                
        except Exception as e:
            if not quiet: messagebox.showerror("Błąd", str(e))

    def _on_preview_select(self, event):
        sel = self.plates_listbox.curselection()
        if not sel or not self.preview_plate_ids: return
        
        pid = self.preview_plate_ids[sel[0]]
        data = self.preview_metadata[pid]
        img_path = Path(self.preview_dir_var.get().strip()) / "images" / f"{pid}.jpg"
        
        self.preview_canvas.delete("all")
        for i in self.chars_tree.get_children(): self.chars_tree.delete(i)
            
        if not img_path.exists():
            self.preview_canvas.create_text(20, 20, text="Plik nie istnieje na dysku!", fill="red")
            return
            
        try:
            pil_img = Image.open(img_path)
            orig_w, orig_h = pil_img.size
            
            c_w = max(50, self.preview_canvas.winfo_width())
            c_h = max(50, self.preview_canvas.winfo_height())
            
            # Wymuszone gigantyczne marginesy na płótnie! (Szeroki oddech z dołu)
            margin_x = 80
            margin_y_top = 40
            margin_y_bottom = 140 
            
            scale_w = (c_w - margin_x) / float(orig_w)
            scale_h = (c_h - (margin_y_top + margin_y_bottom)) / float(orig_h)
            SCALE = max(1.0, min(min(scale_w, scale_h), 6.0))
            
            new_w, new_h = int(orig_w * SCALE), int(orig_h * SCALE)
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            self._current_photo = ImageTk.PhotoImage(pil_img)
            
            # Obrazek jest wycentrowany na szerokości, ale w pionie przesunięty nieco w górę, by zrobić miejsce na tekst!
            x_off = (c_w - new_w) // 2
            y_off = (c_h - new_h - margin_y_bottom + margin_y_top) // 2
            
            # Rysujemy zdjęcie tablicy
            self.preview_canvas.create_image(x_off, y_off, anchor=tk.NW, image=self._current_photo)
            
            # Sztywna dolna krawędź samego powiększonego obrazka (pod nią w jednej linii będą podpisy)
            image_bottom_y = y_off + new_h
            
            chars = data.get("characters", [])
            for c in chars:
                # bbox z oryginału
                x1, y1, x2, y2 = c["bbox"]
                
                # Bbox przeskalowany
                cx1, cy1 = (x1 * SCALE) + x_off, (y1 * SCALE) + y_off
                cx2, cy2 = (x2 * SCALE) + x_off, (y2 * SCALE) + y_off
                
                # Środek w poziomie do zaczepienia napisu
                center_x = cx1 + (cx2 - cx1) / 2
                
                # 1. Obwódka znaku
                self.preview_canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="#00ff00", width=2)
                
                # 2. Cienka, naprowadzająca linia od dołu litery do samego podpisu
                text_anchor_y = image_bottom_y + 35 # Odsunięte sztywno w dół od krawędzi tablicy
                self.preview_canvas.create_line(center_x, cy2, center_x, text_anchor_y - 20, fill="#2ecc71", dash=(2, 2))
                
                # 3. Wyraźny napis z cieniem, by dobrze odcinał się od tła!
                char_text = str(c.get("character", "?"))
                
                # Cień napisu
                self.preview_canvas.create_text(center_x + 1, text_anchor_y + 1, text=char_text, fill="#000000", font=("Segoe UI", 18, "bold"), anchor=tk.CENTER)
                # Główny napis
                self.preview_canvas.create_text(center_x, text_anchor_y, text=char_text, fill="#f1c40f", font=("Segoe UI", 18, "bold"), anchor=tk.CENTER)
                
                # 4. Uzupełnienie Tabelki Poniżej
                conf = float(c.get("confidence", 0.0))
                self.chars_tree.insert("", tk.END, values=(char_text, str(c.get("method", "N/A")), f"{conf*100:.1f}%"))
                
        except Exception as e:
            logger.error(f"Błąd wyświetlania podglądu tablicy: {e}")
    # ============================================================
    # BLOKADY INTERFEJSU
    # ============================================================
    def _lock_ui_for_testing(self):
        """Blokuje interfejs podczas działania ciężkich testów."""
        self.btn_fast_ocr.config(state=tk.DISABLED)
        self.btn_rank_presets.config(state=tk.DISABLED)
        self.plates_listbox.config(state=tk.DISABLED)  # <-- O to prosiłeś!
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            self.preview_canvas.winfo_width() / 2, 
            self.preview_canvas.winfo_height() / 2, 
            text="Przetwarzanie w toku...\n(Podgląd zablokowany)", 
            fill="gray", font=("Arial", 12, "italic"), justify=tk.CENTER
        )

    def _unlock_ui_after_testing(self):
        """Odblokowuje interfejs po zakończeniu testu."""
        self.btn_fast_ocr.config(state=tk.NORMAL)
        self.btn_rank_presets.config(state=tk.NORMAL)
        self.plates_listbox.config(state=tk.NORMAL)
        # Przywrócenie ostatniego wybranego elementu i rysunku
        if self.preview_plate_ids:
            sel = self.plates_listbox.curselection()
            if not sel:
                self.plates_listbox.selection_set(0)
            self._on_preview_select(None)
    # ============================================================
    # SZYBKI TEST OCR NA BAZIE (Z TRUE ACCURACY + PROGRESS BAR)
    # ============================================================
    def _run_fast_ocr_test(self):
        if not self.preview_plate_ids: return messagebox.showinfo("Brak", "Wczytaj paczkę!")
            
        self._force_save_all()
        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        
        self._lock_ui_for_testing()
        self.test_log_text.delete(1.0, tk.END)
        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "START - Szybki Test Celności (Obecne Filtry)\n", "HEADER")

        method_str = self.detection_method_var.get().lower()
        method = DetectionMethod(method_str) if method_str else DetectionMethod.OCR
        
        yolo_model = None
        if method in [DetectionMethod.YOLO, DetectionMethod.BOTH]:
            try:
                device = self._device_to_ultralytics(self.yolo_device_var.get().split()[0].lower())
                yolo_model = YOLO(str(self.yolo_model_path_var.get()))
                yolo_model.to(device)
            except Exception as e: self._log(self.test_log_text, f"Błąd YOLO: {e}", "ERROR")

        prep_params = self._get_current_prep_params()
        ocr_engine = None
        if method in [DetectionMethod.OCR, DetectionMethod.BOTH]:
            use_gpu = self.yolo_device_var.get().split()[0].lower().startswith("cuda")
            ocr_engine = PlateOCR(device='cuda' if use_gpu else 'cpu', confidence_threshold=self.ocr_conf_var.get())
            ocr_engine.custom_prep_params = prep_params

        detector = CharacterDetector(method=method, ocr_engine=ocr_engine, yolo_model=yolo_model)
        
        def worker():
            try:
                import re
                total = len(self.preview_plate_ids)
                stat_total_chars, stat_sum_confidence, stat_valid, stat_perfect = 0, 0.0, 0, 0
                silent_streak = 0
                
                self._log(self.test_log_text, f"Źródło: {out_dir.name}")
                self._log(self.test_log_text, f"Rozmiar paczki testowej: {total} wyciętych tablic", "INFO")
                self._log(self.test_log_text, f" Przetwarzanie...", "INFO")
                
                for idx, pid in enumerate(self.preview_plate_ids):
                    if self.is_processing: break
                    
                    img_path = imgs_dir / f"{pid}.jpg"
                    if not img_path.exists(): continue
                    img = cv2.imread(str(img_path))
                    if img is None: continue
                    
                    true_texts = self._get_true_texts_from_filename(self.preview_metadata[pid].get("source_image", ""))
                    chars = detector.detect(img)
                    
                    c_clean = []
                    for c in chars:
                        c_clean.append({"character": str(c.character), "bbox": [float(x) for x in c.bbox], "confidence": float(c.confidence), "method": str(c.method)})
                        
                    self.preview_metadata[pid]["characters"] = c_clean
                    
                    if c_clean:
                        txt = "".join([c["character"] for c in c_clean])
                        stat_total_chars += len(c_clean)
                        stat_sum_confidence += sum([c["confidence"] for c in c_clean])
                        if re.match(r'^[A-Z]{2,3}[A-Z0-9]{4,5}$', txt): stat_valid += 1
                        
                        if txt in true_texts:
                            self.preview_metadata[pid]["status"] = "perfect"
                            stat_perfect += 1
                            true_texts.remove(txt)
                            silent_streak += 1
                            if total <= 20 or silent_streak >= 10:
                                self._log(self.test_log_text, f"   ✅ [{idx+1}/{total}] {pid}: {txt}", "SUCCESS")
                                silent_streak = 0
                        else:
                            self.preview_metadata[pid]["status"] = "needs_fix"
                            silent_streak = 0
                            expected_str = " / ".join(true_texts) if true_texts else "Brak/Zła nazwa"
                            self._log(self.test_log_text, f"   ❌ [{idx+1}/{total}] {pid}: {txt}  (Oczek: {expected_str})", "ERROR")
                    else:
                        self.preview_metadata[pid]["status"] = "needs_fix"
                        silent_streak = 0
                        self._log(self.test_log_text, f"   ❌ [{idx+1}/{total}] {pid}: BARDZO SŁABO - NIC NIE ZNALEZIONO", "ERROR")

                    # AKTUALIZACJA PASKA POSTĘPU
                    pct = ((idx + 1) / total) * 100
                    self.frame.after(0, lambda p=pct, c=idx+1, t=total: self.test_progress.config(value=p))
                    self.frame.after(0, lambda c=idx+1, t=total: self.test_status_lbl.config(text=f"Testuję: {c} z {t}", foreground="#e67e22"))

                with open(out_dir / "metadata.json", 'w', encoding='utf-8') as f:
                    json.dump(self.preview_metadata, f, indent=2, ensure_ascii=False)
                    
                acc = (stat_perfect / total * 100) if total > 0 else 0
                avg_conf = (stat_sum_confidence / stat_total_chars * 100) if stat_total_chars > 0 else 0
                avg_chars = (stat_total_chars / total) if total > 0 else 0
                format_rate = (stat_valid / total * 100) if total > 0 else 0
                
                tag_main = "SUCCESS" if acc >= 80 else "WARNING" if acc >= 50 else "ERROR"
                self._log(self.test_log_text, "\n" + "="*55, "HEADER")
                self._log(self.test_log_text, f"WYNIK KOŃCOWY (TRUE ACCURACY)", "HEADER")
                self._log(self.test_log_text, "="*55, "HEADER")
                self._log(self.test_log_text, f"Skuteczność bezbłędna: {acc:.1f}% ({stat_perfect}/{total} tablic)", tag_main)
                self._log(self.test_log_text, f"Błędy OCR (do poprawy): {total - stat_perfect} szt.", "ERROR" if acc < 80 else "INFO")
                self._log(self.test_log_text, "-"*55)
                self._log(self.test_log_text, f"• Średnia pewność AI:    {avg_conf:.1f}%")
                self._log(self.test_log_text, f"• Długość tablic:        {avg_chars:.1f} znaków (Ideał: ~7)")
                self._log(self.test_log_text, f"• Zgodny format PL/EU:   {format_rate:.1f}% ({stat_valid} szt.)")
                self._log(self.test_log_text, "="*55 + "\n")

                cache_file = out_dir / "ranking_cache.json"
                cache_data = {}
                if cache_file.exists():
                    try: 
                        with open(cache_file, 'r', encoding='utf-8') as cf: cache_data = json.load(cf)
                    except: pass
                cache_data["Ostatni Test"] = {
                    "name": "Ostatni Test OCR", "acc": acc, "matches": stat_perfect, "params": prep_params
                }
                with open(cache_file, 'w', encoding='utf-8') as cf: json.dump(cache_data, cf, indent=4)
                
                self.frame.after(0, self._load_preview_data)

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD: {e}", "ERROR")
            finally:
                self.frame.after(0, self._unlock_ui_after_testing)
                self.frame.after(0, lambda: self.test_status_lbl.config(text="Zakończono Test!", foreground="#2ecc71"))

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # RANKING PRESETÓW W TLE (Z PROGRESS BAREM)
    # ============================================================
    def _run_preset_ranking(self):
        if not self.preview_plate_ids: return messagebox.showinfo("Brak", "Wczytaj paczkę danych do testu!")
            
        preset_files = list(self.presets_dir.glob("*.json"))
        if not preset_files: return messagebox.showinfo("Brak presetów", "Nie masz zapisanych żadnych presetów! Otwórz Laboratorium i zapisz filtry jako JSON.")

        self._lock_ui_for_testing()
        self.test_log_text.delete(1.0, tk.END)
        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, f"ROZPOCZYNAM TURNIEJ PRESETÓW (Z PAMIĘCIĄ CACHE)", "HEADER")
        self._log(self.test_log_text, "=======================================================", "HEADER")

        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        cache_file = out_dir / "ranking_cache.json"

        chosen_device = self.yolo_device_var.get().split()[0].lower()
        use_gpu = chosen_device.startswith("cuda")
        
        def worker():
            try:
                ranking_cache = {}
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            ranking_cache = json.load(f)
                    except: pass

                ocr_engine = PlateOCR(device='cuda' if use_gpu else 'cpu')
                detector = CharacterDetector(method=DetectionMethod.OCR, ocr_engine=ocr_engine)
                
                results_table = []
                total_imgs = len(self.preview_plate_ids)
                total_presets = len(preset_files)
                
                self._log(self.test_log_text, f"Źródło danych: {out_dir.name}")
                self._log(self.test_log_text, f"Rozmiar paczki: {total_imgs} wyciętych tablic")
                self._log(self.test_log_text, f"⚔️ Zgłoszeni rywale (Presety): {total_presets}\n", "INFO")

                tested_new = 0

                for p_idx, p_file in enumerate(preset_files):
                    preset_name = p_file.stem
                    
                    try: file_mtime = p_file.stat().st_mtime 
                    except: file_mtime = 0

                    try:
                        with open(p_file, 'r', encoding='utf-8') as f: preset_params = json.load(f)
                    except: continue
                    
                    clean_params = {k: v for k, v in preset_params.items() if not k.startswith("char_do_") and k != "char_ocr_conf"}
                    param_signature = str(sorted(clean_params.items()))
                    
                    if preset_name in ranking_cache and ranking_cache[preset_name].get("signature") == param_signature:
                        cached_data = ranking_cache[preset_name]
                        results_table.append((cached_data["acc"], cached_data["matches"], preset_name, True))
                        self._log(self.test_log_text, f"[{p_idx+1}/{total_presets}] {preset_name.ljust(20)} -> Gotowe z pamięci Cache", "INFO")
                        
                        # Aktualizacja paska za wczytanie z Cache (szybki strzał)
                        self.frame.after(0, lambda p=((p_idx+1)/total_presets)*100: self.test_progress.config(value=p))
                        self.frame.after(0, lambda c=p_idx+1, t=total_presets: self.test_status_lbl.config(text=f"Ranking: {c} / {t} presetów", foreground="#e67e22"))
                        continue

                    tested_new += 1
                    ocr_engine.custom_prep_params = clean_params
                    if "char_ocr_conf" in preset_params: ocr_engine.confidence_threshold = float(preset_params.get("char_ocr_conf", 0.25))

                    self._log(self.test_log_text, f"[{p_idx+1}/{total_presets}] Analizuję preset: {preset_name} ...", "WARNING")
                    perfect_matches = 0
                    
                    for img_idx, pid in enumerate(self.preview_plate_ids):
                        if not self.is_processing and False: break
                            
                        img_path = imgs_dir / f"{pid}.jpg"
                        if not img_path.exists(): continue
                        plate_img = cv2.imread(str(img_path))
                        if plate_img is None: continue
                        
                        source_image_name = self.preview_metadata[pid].get("source_image", "")
                        expected_plates = self._get_true_texts_from_filename(source_image_name)

                        chars = detector.detect(plate_img)
                        text_found = "".join([str(c.character) for c in chars])
                        
                        if text_found in expected_plates:
                            perfect_matches += 1
                            expected_plates.remove(text_found)
                            
                        # Sub-aktualizacja paska wewnątrz testowania pojedynczego presetu!
                        if img_idx % 5 == 0:
                            sub_pct = ((p_idx + (img_idx / total_imgs)) / total_presets) * 100
                            self.frame.after(0, lambda p=sub_pct: self.test_progress.config(value=p))

                    acc = (perfect_matches / total_imgs) * 100 if total_imgs > 0 else 0
                    ranking_cache[preset_name] = {"name": preset_name, "acc": acc, "matches": perfect_matches, "signature": param_signature, "params": preset_params}
                    results_table.append((acc, perfect_matches, preset_name, False))
                    
                    if acc > 80: tag = "SUCCESS"
                    elif acc > 40: tag = "WARNING"
                    else: tag = "ERROR"
                    self._log(self.test_log_text, f"   └─ Zbadano! Skuteczność True Accuracy: {acc:.1f}%\n", tag)
                    
                    self.frame.after(0, lambda p=((p_idx+1)/total_presets)*100: self.test_progress.config(value=p))
                    self.frame.after(0, lambda c=p_idx+1, t=total_presets: self.test_status_lbl.config(text=f"Ranking: {c} / {t} presetów", foreground="#e67e22"))

                with open(cache_file, 'w', encoding='utf-8') as f: json.dump(ranking_cache, f, indent=4)

                results_table.sort(key=lambda x: x[0], reverse=True)

                self._log(self.test_log_text, "="*55, "HEADER")
                self._log(self.test_log_text, "TABELA WYNIKÓW (RANKING PRESETÓW OCR)", "HEADER")
                self._log(self.test_log_text, "="*55, "HEADER")
                
                for i, (acc, matches, name, from_cache) in enumerate(results_table):
                    tag = "SUCCESS" if i == 0 else "INFO"
                    medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "  "
                    c_tag = "(Cache)" if from_cache else "(NOWY)"
                    self._log(self.test_log_text, f"{medal} #{i+1}. {name.ljust(22)} | {acc:5.1f}%  ({matches}/{total_imgs} tablic) {c_tag}", tag)

                if tested_new == 0: self._log(self.test_log_text, "\n Wszystkie presety wczytano z pamięci podręcznej!", "WARNING")
                else: self._log(self.test_log_text, f"\nPrzetestowano na nowo {tested_new} presetów. Reszta z cache.", "INFO")
                    
                self.frame.after(0, self._update_winner_label)
                self.frame.after(0, lambda: self.test_progress.config(value=100))
                self.frame.after(0, lambda: self.test_status_lbl.config(text="Turniej Zakończony!", foreground="#2ecc71"))

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD RANKINGU: {e}", "ERROR")
            finally:
                self.frame.after(0, self._unlock_ui_after_testing)
                self.frame.after(0, lambda: self.test_progress.config(value=100))
                self.frame.after(0, lambda: self.test_status_lbl.config(text="Turniej Zakończony!", foreground="#2ecc71"))

        threading.Thread(target=worker, daemon=True).start()
    

    # ============================================================
    # LABORATORIUM PRE-PROCESSINGU (Z DUCHEM LIDERA)
    # ============================================================
    def _open_filter_lab(self):
        out_dir = Path(self.preview_dir_var.get().strip())
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak Danych", "Wczytaj najpierw listę tablic w zakładce Analiza, by mieć na czym eksperymentować.")

        imgs_dir = out_dir / "images"

        def roll_images():
            import random
            s = min(3, len(self.preview_plate_ids))
            ids = random.sample(self.preview_plate_ids, s)
            res = []
            for pid in ids:
                i = cv2.imread(str(imgs_dir / f"{pid}.jpg"))
                if i is not None: res.append((pid, i))
            return res

        self.lab_current_images = roll_images()
        if not self.lab_current_images: return

        best_preset_data, best_acc = self._get_best_preset()
        best_name = best_preset_data.get('name', 'Brak') if best_preset_data else 'Brak'
        def g(key, default=""): 
            if not best_preset_data: return default
            params = best_preset_data.get('params', {})
            return params.get(key, default)

        lab_win = tk.Toplevel(self.frame)
        lab_win.title("Laboratorium Filtrów OCR (Zarządzanie Presetami)")
        lab_win.geometry("1100x850")
        lab_win.minsize(900, 700)
        
        bottom_bar = ttk.Frame(lab_win, padding=10, relief="raised")
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        main_content = ttk.Frame(lab_win)
        main_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        left_container = ttk.Frame(main_content, width=350)
        left_container.pack(side=tk.LEFT, fill=tk.Y)
        left_container.pack_propagate(False)

        canvas_sliders = tk.Canvas(left_container, highlightthickness=0)
        scroll_sliders = ttk.Scrollbar(left_container, orient="vertical", command=canvas_sliders.yview)
        scrollable_frame = ttk.Frame(canvas_sliders, padding=10)

        frame_id = canvas_sliders.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        def _on_canvas_resize(event):
            canvas_sliders.itemconfig(frame_id, width=event.width)
        canvas_sliders.bind('<Configure>', _on_canvas_resize)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas_sliders.configure(scrollregion=canvas_sliders.bbox("all")))
        canvas_sliders.configure(yscrollcommand=scroll_sliders.set)

        scroll_sliders.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_sliders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        right_view_container = ttk.Frame(main_content, padding=10)
        right_view_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(right_view_container, text="Podgląd wpływu filtrów na losową próbkę:", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 10))

        view_canvas = tk.Canvas(right_view_container, bg="#2c3e50", highlightthickness=0)
        view_scroll_v = ttk.Scrollbar(right_view_container, orient=tk.VERTICAL, command=view_canvas.yview)
        view_scroll_h = ttk.Scrollbar(right_view_container, orient=tk.HORIZONTAL, command=view_canvas.xview)
        
        view_scroll_h.pack(side=tk.BOTTOM, fill=tk.X)
        view_scroll_v.pack(side=tk.RIGHT, fill=tk.Y)
        view_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        view_canvas.configure(yscrollcommand=view_scroll_v.set, xscrollcommand=view_scroll_h.set)
        
        view_frame = ttk.Frame(view_canvas, style="Card.TFrame")
        view_window = view_canvas.create_window((0, 0), window=view_frame, anchor="nw")
        
        def _on_view_frame_configure(event): view_canvas.configure(scrollregion=view_canvas.bbox("all"))
        view_frame.bind("<Configure>", _on_view_frame_configure)

        self.lab_image_labels = []
        for i in range(3):
            f = ttk.LabelFrame(view_frame, text=f" Obraz testowy {i+1} ", padding=10)
            f.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)
            lbl = ttk.Label(f, font=("Consolas", 10, "bold"))
            lbl.pack(anchor=tk.W, pady=(0, 5))
            c = ttk.Frame(f)
            c.pack(fill=tk.BOTH, expand=True)
            
            of_frame = ttk.Frame(c)
            of_frame.pack(side=tk.LEFT, padx=10, fill=tk.BOTH)
            ttk.Label(of_frame, text="Oryginał:", font=("Arial", 9)).pack(anchor=tk.W)
            o_lbl = tk.Label(of_frame, bg="#2c3e50", bd=2, relief="sunken")
            o_lbl.pack(anchor=tk.NW)
            
            pf_frame = ttk.Frame(c)
            pf_frame.pack(side=tk.LEFT, padx=20, fill=tk.BOTH)
            ttk.Label(pf_frame, text="Zbinaryzowany (Dla OCR):", font=("Arial", 9)).pack(anchor=tk.W)
            p_lbl = tk.Label(pf_frame, bg="black", bd=2, relief="solid")
            p_lbl.pack(anchor=tk.NW)
            
            self.lab_image_labels.append({"lbl": lbl, "orig": o_lbl, "proc": p_lbl})

        self.lab_photo_refs = []
        active_traces = []

        def update_preview(*args):
            if not lab_win.winfo_exists(): return
            try:
                th = self.prep_height_var.get()
                ma = self.prep_angle_var.get()
                ct = self.prep_clip_var.get()
                dh = self.prep_denoise_var.get()
                cc = self.prep_clahe_var.get()
                use_bin = self.prep_use_bin_var.get()
                tb = self.prep_block_var.get()
                if tb % 2 == 0: tb += 1
                t_c = self.prep_c_var.get()
                ei = self.prep_erode_var.get()
                
                interp_str = self.interpolation_var.get()
                interp_map = {"nearest": cv2.INTER_NEAREST, "linear": cv2.INTER_LINEAR, "cubic": cv2.INTER_CUBIC, "lanczos4": cv2.INTER_LANCZOS4}
                cv2_interp = interp_map.get(interp_str.lower(), cv2.INTER_LANCZOS4)

                self.lab_photo_refs.clear()

                for idx, (pid, orig_img) in enumerate(self.lab_current_images):
                    if idx >= len(self.lab_image_labels): break
                    
                    if abs(ma) > 0.1:
                        h, w = orig_img.shape[:2]
                        M = cv2.getRotationMatrix2D((w//2, h//2), ma, 1.0)
                        rotated = cv2.warpAffine(orig_img, M, (w, h), flags=cv2_interp, borderMode=cv2.BORDER_REPLICATE)
                    else: rotated = orig_img.copy()

                    gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY) if len(rotated.shape) == 3 else rotated.copy()
                    h_g, w_g = gray.shape
                    scale = float(th) / h_g if h_g > 0 else 1.0
                    gray_scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2_interp)
                    
                    po = ImageTk.PhotoImage(Image.fromarray(gray_scaled))
                    
                    if ct < 255: gray_scaled[gray_scaled > ct] = 255
                    den = cv2.fastNlMeansDenoising(gray_scaled, None, h=dh, templateWindowSize=7, searchWindowSize=21) if dh > 0 else gray_scaled
                    
                    if self.do_clahe_var.get() and cc > 0:
                        clahe = cv2.createCLAHE(clipLimit=cc, tileGridSize=(8, 8))
                        contrasted = clahe.apply(den)
                    else: contrasted = den
                        
                    blurred = cv2.GaussianBlur(contrasted, (3, 3), 0)
                    
                    if use_bin:
                        binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize=max(3, tb), C=t_c)
                        if ei > 0:
                            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                            final = cv2.erode(binary, kernel, iterations=ei)
                        else: final = binary
                    else: final = contrasted

                    pp = ImageTk.PhotoImage(Image.fromarray(final))
                    self.lab_photo_refs.extend([po, pp])
                    
                    ui_row = self.lab_image_labels[idx]
                    ui_row["lbl"].config(text=f"ID: {pid}")
                    ui_row["orig"].config(image=po)
                    ui_row["proc"].config(image=pp)

                for idx in range(len(self.lab_current_images), len(self.lab_image_labels)):
                    self.lab_image_labels[idx]["lbl"].config(text="")
                    self.lab_image_labels[idx]["orig"].config(image='')
                    self.lab_image_labels[idx]["proc"].config(image='')
            except Exception: pass

        # --- FUNKCJA TWORZĄCA SUWAKI Z DUCHEM LIDERA ---
        def add_slider(parent, label, var, from_, to_, res, ghost_key="", help_key=""):
            f = ttk.Frame(parent)
            f.pack(fill=tk.X, pady=4)
            lbl_f = ttk.Frame(f)
            lbl_f.pack(fill=tk.X)
            
            main_label = ttk.Label(lbl_f, text=label)
            main_label.pack(side=tk.LEFT)
            
            if ghost_key and best_preset_data and isinstance(best_preset_data.get("params"), dict):
                params_dict = best_preset_data["params"]
                if ghost_key in params_dict:
                    val = params_dict[ghost_key]
                    ghost_str = f"{val:.1f}" if isinstance(val, float) else str(val)
                    ttk.Label(lbl_f, text=f"[Zwycięzca: {ghost_str}]", foreground="#2980b9", font=("Segoe UI", 9, "bold italic")).pack(side=tk.RIGHT)
            
            s = ttk.Scale(f, from_=from_, to=to_, variable=var, command=update_preview)
            s.pack(side=tk.LEFT, fill=tk.X, expand=True)
            l = ttk.Label(f, width=5)
            l.pack(side=tk.RIGHT)
            
            def update_lbl(*a): 
                if lab_win.winfo_exists(): l.config(text=f"{var.get():.{res}f}")
            trace_id = var.trace_add("write", update_lbl)
            active_traces.append((var, trace_id))
            update_lbl()

            # ✅ MAGICZNE PODPIĘCIE POMOCY DO SUWAKA I ETYKIETY
            if help_key:
                HELP.bind_help(main_label, help_key)
                HELP.bind_help(s, help_key)

        # LEWY PANEL - NAGŁÓWEK LIDERA
        if best_preset_data and best_preset_data.get("name"):
            leader_f = tk.Frame(scrollable_frame, bg="#fff3cd", bd=1, relief="solid")
            leader_f.pack(fill=tk.X, pady=(0, 15))
            tk.Label(leader_f, text=f"Lider: {best_preset_data.get('name').upper()}", bg="#fff3cd", fg="#8a6d3b", font=("Arial", 10, "bold")).pack(pady=(5,0))
            tk.Label(leader_f, text=f"Skuteczność: {best_acc:.1f}%", bg="#fff3cd", fg="#8a6d3b", font=("Arial", 9)).pack(pady=(0,5))
        else:
            ttk.Label(scrollable_frame, text="Dostrojenie Algorytmu", font=("Arial", 12, "bold")).pack(pady=(0,10))

        # ==================================
        # BLOKI UI (PRZEKAZANIE KLUCZY DUCHA)
        # Przekazujemy czyste nazwy kluczy, takie jakie występują w _get_current_prep_params()!
        # ==================================
        geom = ttk.LabelFrame(scrollable_frame, text=" 1. Geometria (Kąt i Rozmiar) ", padding=10)
        geom.pack(fill=tk.X, pady=(0,10))
        angle_row = ttk.Frame(geom)
        angle_row.pack(fill=tk.X)
        add_slider(angle_row, "Ręczna korekta kąta [°]:", self.prep_angle_var, -30, 30, 1, "manual_angle", "lab_angle")
        ttk.Button(geom, text="Reset Kąta", command=lambda: (self.prep_angle_var.set(0.0), update_preview())).pack(anchor=tk.E, pady=(0,5))
        
        ttk.Label(geom, text="Interpolacja:").pack(anchor=tk.W, pady=(5,2))
        cmb_int = ttk.Combobox(geom, textvariable=self.interpolation_var, values=["nearest", "linear", "cubic", "lanczos4"], state="readonly")
        cmb_int.pack(fill=tk.X)
        cmb_int.bind("<<ComboboxSelected>>", lambda e: update_preview())
        
        # Duch dla Interpolacji (wymaga ręcznego podpięcia bo nie jest suwakiem)
        if best_preset_data and "interpolation" in best_preset_data.get("params", {}):
            ttk.Label(geom, text=f"[Zwycięzca: {best_preset_data['params']['interpolation']}]", foreground="#2980b9", font=("Segoe UI", 9, "bold italic")).pack(anchor=tk.E)
        
        add_slider(geom, "Wysokość OCR (px) [Rek: 60-80]:", self.prep_height_var, 40, 150, 0, "target_height", "lab_height")

        filt = ttk.LabelFrame(scrollable_frame, text=" 2. Filtry bazowe ", padding=10)
        filt.pack(fill=tk.X, pady=(0,10))
        add_slider(filt, "Odcięcie odblasków (255=Wył):", self.prep_clip_var, 100, 255, 0, "clip_thresh", "lab_clip")
        add_slider(filt, "Usuwanie ziarna (0=Wył):", self.prep_denoise_var, 0, 50, 0, "denoise_h", "lab_denoise")
        
        cb2 = ttk.Checkbutton(filt, text="Wzmacniaj kontrast (CLAHE)", variable=self.do_clahe_var, command=update_preview)
        cb2.pack(anchor=tk.W, pady=(8,2))
        
        if best_preset_data and "clahe_clip" in best_preset_data.get("params", {}):
            is_clahe_on = "WŁĄCZONE" if float(best_preset_data["params"]["clahe_clip"]) > 0 else "WYŁĄCZONE"
            ttk.Label(filt, text=f"[Zwycięzca: {is_clahe_on}]", foreground="#2980b9", font=("Segoe UI", 9, "bold italic")).pack(anchor=tk.E)
            
        add_slider(filt, "Siła CLAHE:", self.prep_clahe_var, 0.0, 10.0, 1, "clahe_clip", "lab_clahe")

        bina = ttk.LabelFrame(scrollable_frame, text=" 3. Binaryzacja (Dla OCR) ", padding=10)
        bina.pack(fill=tk.X, pady=(0,10))
        cb_bin = ttk.Checkbutton(bina, text="Włącz pełną binaryzację", variable=self.prep_use_bin_var, command=update_preview)
        cb_bin.pack(anchor=tk.W, pady=(0,5))
        
        if best_preset_data and "use_binarization" in best_preset_data.get("params", {}):
            is_bin_on = "WŁĄCZONE" if best_preset_data["params"]["use_binarization"] else "WYŁĄCZONE"
            ttk.Label(bina, text=f"[Zwycięzca: {is_bin_on}]", foreground="#2980b9", font=("Segoe UI", 9, "bold italic")).pack(anchor=tk.E)
            
        add_slider(bina, "Rozmiar bloku (nieparzyste):", self.prep_block_var, 3, 51, 0, "thresh_block", "lab_block")
        add_slider(bina, "Stała odcięcia (C):", self.prep_c_var, -20, 20, 0, "thresh_c", "lab_c")
        add_slider(bina, "Pogrubianie liter (Erozja):", self.prep_erode_var, 0, 5, 0, "erode_iter", "lab_erode")

        def load_preset():
            p = filedialog.askopenfilename(initialdir=self.presets_dir, filetypes=[("JSON", "*.json")], parent=lab_win)
            if p:
                try:
                    with open(p, 'r') as f: data = json.load(f)
                    if "target_height" in data: self.prep_height_var.set(data["target_height"])
                    if "manual_angle" in data: self.prep_angle_var.set(data["manual_angle"])
                    if "clip_thresh" in data: self.prep_clip_var.set(data["clip_thresh"])
                    if "denoise_h" in data: self.prep_denoise_var.set(data["denoise_h"])
                    if "use_binarization" in data: self.prep_use_bin_var.set(data["use_binarization"])
                    if "thresh_block" in data: self.prep_block_var.set(data["thresh_block"])
                    if "thresh_c" in data: self.prep_c_var.set(data["thresh_c"])
                    if "erode_iter" in data: self.prep_erode_var.set(data["erode_iter"])
                    if "interpolation" in data: self.interpolation_var.set(data["interpolation"])
                    if "clahe_clip" in data:
                        val = data["clahe_clip"]
                        self.prep_clahe_var.set(val)
                        self.do_clahe_var.set(True if val > 0 else False)
                    update_preview()
                    messagebox.showinfo("Załadowano", f"Wczytano preset: {Path(p).stem}", parent=lab_win)
                except Exception as e: messagebox.showerror("Błąd", str(e), parent=lab_win)

        def save_preset():
            name = simpledialog.askstring("Preset", "Podaj nazwę dla presetu (bez spacji):", parent=lab_win)
            if name:
                clean_name = "".join([c for c in name if c.isalnum() or c == "_"])
                if not clean_name: clean_name = "default_preset"
                p = self.presets_dir / f"{clean_name}.json"
                data = self._get_current_prep_params()
                data["char_ocr_conf"] = self.ocr_conf_var.get()
                try:
                    with open(p, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
                    messagebox.showinfo("Zapisano", f"Zapisano preset jako:\n{p.name}", parent=lab_win)
                except Exception as e: messagebox.showerror("Błąd", str(e), parent=lab_win)

        def safe_close():
            for var, trace_id in active_traces:
                try: var.trace_remove("write", trace_id)
                except: pass
            self._force_save_all()
            lab_win.destroy()

        lab_win.protocol("WM_DELETE_WINDOW", safe_close)

        btn_roll = ttk.Button(bottom_bar, text="🎲 Losuj inną próbkę (3 szt.)", command=lambda: (setattr(self, 'lab_current_images', roll_images()), update_preview()))
        btn_roll.pack(side=tk.LEFT, padx=20, ipady=4)

        btn_confirm = ttk.Button(bottom_bar, text="✅ ZASTOSUJ DO TESTU I ZAMKNIJ", command=safe_close, style="Accent.TButton")
        btn_confirm.pack(side=tk.RIGHT, padx=10, ipady=4)
        btn_save = ttk.Button(bottom_bar, text="Zapisz jako Preset", command=save_preset)
        btn_save.pack(side=tk.RIGHT, padx=5, ipady=4)
        btn_load = ttk.Button(bottom_bar, text="Wczytaj Preset", command=load_preset)
        btn_load.pack(side=tk.RIGHT, padx=5, ipady=4)

        update_preview()

    # ============================================================
    # ZAKŁADKA 3: CVAT EXPORT/IMPORT (SMART EXPORT)
    # ============================================================
    # ============================================================
    # ZAKŁADKA 3: EKSPORT (CVAT / YOLO ACTIVE LEARNING)
    # ============================================================
    def _build_cvat_tab(self, parent):
        info = ttk.LabelFrame(parent, text=" Architektura Active Learning ", padding=12)
        info.pack(fill=tk.X, padx=15, pady=(15, 10))
        ttk.Label(info, text=(
            "Dwie ścieżki eksportu:\n"
            "1. SMART CVAT: Eksportuj TYLKO 🔴 Błędne tablice. Wgraj je do CVAT, popraw ręcznie i zaimportuj by naprawić zbiór.\n"
            "2. AUTO-DATASET YOLO: Skoro OCR odczytał 7% paczki perfekcyjnie (zgodnie z nazwą pliku), "
            "wyeksportuj te 🟢 Złote Strzały jako gotowy zbiór uczący! Wytrenuj na nim YOLO i użyj go w miejsce OCR, "
            "by w kolejnej iteracji uzyskać 30%, potem 80% skuteczności!"
        ), justify=tk.LEFT, foreground="#2c3e50").pack(anchor=tk.W)

        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        export_lf = ttk.LabelFrame(pane, text="EKSPORTY (CVAT / YOLO) ", padding=15)
        pane.add(export_lf, weight=1)

        ttk.Label(export_lf, text="Katalog roboczy:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        ttk.Entry(export_lf, textvariable=self.preview_dir_var, state="readonly").pack(fill=tk.X, pady=5)
        
        # Opcja 1: Do CVAT (Błędne)
        cvat_f = ttk.Frame(export_lf)
        cvat_f.pack(fill=tk.X, pady=(15, 5))
        ttk.Checkbutton(cvat_f, text="SMART EXPORT: Tylko tablice z błędami (Czerwone)", variable=self.smart_export_var).pack(anchor=tk.W, pady=(0, 5))
        btn_export = ttk.Button(cvat_f, text="1. WYGENERUJ .ZIP DLA CVAT (Do poprawy)", style="Accent.TButton", command=self._run_cvat_export)
        btn_export.pack(fill=tk.X, ipady=5)

        ttk.Separator(export_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=20)
        
        # Opcja 2: Do YOLO (Złote, Perfekcyjne)
        yolo_f = ttk.Frame(export_lf)
        yolo_f.pack(fill=tk.X)
        ttk.Label(yolo_f, text="Gotowy Dataset dla YOLO (Automatyczna pętla nauki!):", font=("Segoe UI", 9, "bold"), foreground="#27ae60").pack(anchor=tk.W, pady=(0, 5))
        btn_yolo_export = ttk.Button(yolo_f, text="2. WYEKSPORTUJ 🟢 PERFEKCYJNE TABLICE DO YOLO", style="Accent.TButton", command=self._run_yolo_gold_export)
        btn_yolo_export.pack(fill=tk.X, ipady=8)

        self.export_status = ttk.Label(export_lf, text="Oczekuje...", foreground="gray")
        self.export_status.pack(anchor=tk.W, pady=(10, 0))


        import_lf = ttk.LabelFrame(pane, text=" IMPORT (Z CVAT) ", padding=15)
        pane.add(import_lf, weight=1)

        ttk.Label(import_lf, text="Poprawiony annotations.xml pobrany z CVAT:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        row2 = ttk.Frame(import_lf)
        row2.pack(fill=tk.X, pady=5)
        self.import_cvat_xml_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.import_cvat_xml_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wybierz", command=lambda: self._pick_file(self.import_cvat_xml_var)).pack(side=tk.RIGHT, padx=(5,0))

        btn_import = ttk.Button(import_lf, text="ZAKTUALIZUJ BAZĘ DANYCH POPRAWKAMI", style="Accent.TButton", command=self._run_cvat_import)
        btn_import.pack(fill=tk.X, pady=(20, 5), ipady=5)
        self.import_status = ttk.Label(import_lf, text="Oczekuje...", foreground="gray")
        self.import_status.pack(anchor=tk.W)

    def _pick_file(self, var):
        p = filedialog.askopenfilename(title="Wybierz plik XML", filetypes=[("XML", "*.xml")])
        if p: var.set(p)

    def _run_cvat_export(self):
        work_dir = Path(self.preview_dir_var.get().strip())
        meta_path = work_dir / "metadata.json"
        if not meta_path.exists(): return messagebox.showerror("Błąd", "Brak metadata.json")

        out_xml = work_dir / "annotations.xml"
        out_zip = work_dir / f"{work_dir.name}_CVAT.zip"
        
        self.export_status.config(text="Eksportowanie do CVAT...", foreground="blue")
        self.frame.update()
        try:
            with open(meta_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
                
            if self.smart_export_var.get():
                filtered = {k: v for k, v in metadata.items() if v.get("status") != "perfect"}
                temp_meta = work_dir / "temp_meta.json"
                with open(temp_meta, 'w', encoding='utf-8') as f: json.dump(filtered, f)
                source_meta = temp_meta
            else:
                source_meta = meta_path

            from ..cvat_tools.cvat_character_exporter import CVATCharacterExporter
            if CVATCharacterExporter().export(source_meta, out_xml):
                from ..cvat_tools.cvat_zip_manager import CVATZipManager
                ok, msg, _ = CVATZipManager.create_cvat_import_zip(out_xml, work_dir / "images", out_zip)
                if ok:
                    self.export_status.config(text=f"Zapisano CVAT ZIP: {out_zip.name}", foreground="green")
                    messagebox.showinfo("Sukces", "ZIP dla CVAT wygenerowany! Przeciągnij go do zadania.")
            if self.smart_export_var.get() and temp_meta.exists(): temp_meta.unlink()
        except Exception as e: messagebox.showerror("Błąd", str(e))

    # =================================================================
    # MAGIA ACTIVE LEARNING: EKSPORT PERFEKCYJNYCH Z CAŁEGO WORKSPACE!
    # =================================================================
    def _run_yolo_gold_export(self):
        """Zbiera tablice o statusie 'perfect' ze wszystkich runów, ucina duble, 
           generuje Bounding Boxy i Portable data.yaml dla YOLO Character Detection."""
        base_chars_dir = Path(CONFIG.DIR_3_CHARS)
        
        if not base_chars_dir.exists(): 
            return messagebox.showerror("Błąd", f"Katalog główny znaków nie istnieje:\n{base_chars_dir}")

        self.export_status.config(text="Zbiórka perfekcyjnych tablic ze wszystkich runów...", foreground="blue")
        self.frame.update()
        
        try:
            import shutil
            import uuid
            import datetime
            
            # Globalny folder docelowy dla wielkiego datasetu
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            yolo_out = Path(CONFIG.DIR_4_DATASETS) / f"YOLO_MegaDataset_Chars_{timestamp}"
            
            # W YOLO najprostsza działająca struktura to zrzucenie wszystkich obrazów 
            # do jednego wora (images) i etykiet do drugiego (labels), 
            # by móc je potem przemielić przez Twój Splitter na train/val.
            img_out = yolo_out / "images"
            lbl_out = yolo_out / "labels"
            
            img_out.mkdir(parents=True, exist_ok=True)
            lbl_out.mkdir(parents=True, exist_ok=True)

            # Mapowanie 36 znaków alfanumerycznych na unikalne ID klas dla YOLO.
            # Kolejność jest kluczowa! To ona definiuje "wiedzę" sieci.
            all_chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            char_map = {c: i for i, c in enumerate(all_chars)}

            copied = 0
            
            # Słownik śledzący unikalność. Zabezpiecza przed dublami jeśli obrobiłeś 
            # ten sam plik pojazdu w kilku runach!
            seen_unique_plates = set()
            
            # Przeszukujemy każdy podfolder run_XXX
            for run_dir in base_chars_dir.iterdir():
                if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                    continue
                    
                meta_path = run_dir / "metadata.json"
                if not meta_path.exists():
                    continue
                    
                with open(meta_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    
                # Filtrujemy tylko złote (perfekcyjnie odczytane w Szybkim Teście lub poprawione z CVAT)
                perfect_plates = {k: v for k, v in metadata.items() if v.get("status") == "perfect"}
                
                for pid, data in perfect_plates.items():
                    # Tworzymy unikalny klucz z nazwy oryginału i przybliżonego X boxa tablicy na aucie
                    src_img = data.get("source_image", "unknown")
                    bbox_approx = int(data.get("source_bbox", [0])[0] // 10) if data.get("source_bbox") else 0
                    unique_key = f"{src_img}_{bbox_approx}"
                    
                    if unique_key in seen_unique_plates:
                        continue 
                    seen_unique_plates.add(unique_key)
                    
                    # Fizyczne kopiowanie wyciętej tablicy
                    img_src_path = run_dir / "images" / f"{pid}.jpg"
                    if not img_src_path.exists(): continue

                    img_cv2 = cv2.imread(str(img_src_path))
                    if img_cv2 is None: continue
                    img_h, img_w = img_cv2.shape[:2]

                    # Generujemy nowy, anonimowy klucz dla obrazka, by pominąć kolizje plików
                    new_pid = f"mega_{uuid.uuid4().hex[:8]}_{pid}"
                    shutil.copy2(img_src_path, img_out / f"{new_pid}.jpg")
                    
                    # Generowanie fizycznego pliku etykiet .txt dla znaków YOLO Format
                    txt_content = []
                    for c in data.get("characters", []):
                        character = str(c.get("character", "")).upper()
                        if character not in char_map: continue
                        class_id = char_map[character]
                        
                        x1, y1, x2, y2 = c.get("bbox", [0,0,0,0])
                        # Przelicz do YOLO normalized coordinates: (X_center, Y_center, Width, Height)
                        x_c = ((x1 + x2) / 2.0) / img_w
                        y_c = ((y1 + y2) / 2.0) / img_h
                        bw = (x2 - x1) / img_w
                        bh = (y2 - y1) / img_h
                        
                        # Ograniczenie wartości od 0.0 do 1.0 (zabezpieczenie)
                        x_c, y_c = max(0.0, min(1.0, x_c)), max(0.0, min(1.0, y_c))
                        bw, bh = max(0.0, min(1.0, bw)), max(0.0, min(1.0, bh))
                        
                        txt_content.append(f"{class_id} {x_c:.6f} {y_c:.6f} {bw:.6f} {bh:.6f}")

                    with open(lbl_out / f"{new_pid}.txt", "w", encoding="utf-8") as f:
                        f.write("\n".join(txt_content))
                        
                    copied += 1

            if copied == 0:
                self.export_status.config(text="Brak nowych perfekcyjnych tablic.", foreground="red")
                return messagebox.showinfo("Pusto", "W całym Workspace nie znaleziono ŻADNEJ tablicy ze statusem 'perfect'!")

            # -------------------------------------------------------------
            # MAGIA PRZENOŚNEGO YAMLA DLA 36 KLAS! (Żadnych twardych ścieżek)
            # -------------------------------------------------------------
            yaml_content = f"""# YOLO Character Detection MEGA-Dataset
# Auto-wygenerowano z pewnych anotacji znaków
train: images
val: images

nc: {len(all_chars)}
names:
"""
            for char, class_id in char_map.items():
                yaml_content += f"  {class_id}: '{char}'\n"

            with open(yolo_out / "data.yaml", "w", encoding="utf-8") as f:
                f.write(yaml_content)

            self.export_status.config(text=f"Sukces! Złożono {copied} potężnych tablic uczących.", foreground="green")
            messagebox.showinfo(
                "Zebrano Mega-Dataset!", 
                f"Przeszukano WSZYSTKIE eksperymenty w Workspace!\n"
                f"Zebrano: {copied} unikalnych, 100% poprawnych tablic.\n\n"
                f"Utworzono MEGA-dataset w:\n{yolo_out}\n\n"
                f"Przejdź teraz do zakładki 3 (Trening), do pod-zakładki Splitter, wskaż ten folder by rozbić go na train/val, a potem wytrenuj swój potężny detektor znaków!"
            )

        except Exception as e:
            messagebox.showerror("Błąd", str(e))
            self.export_status.config(text="Błąd eksportu.", foreground="red")


    # Import z CVAT
    def _run_cvat_import(self):
        xml_in = Path(self.import_cvat_xml_var.get().strip())
        work_dir = Path(self.preview_dir_var.get().strip())
        meta_path = work_dir / "metadata.json"

        if not xml_in.exists() or not meta_path.exists(): return messagebox.showerror("Błąd", "Brak XML lub metadata.json")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
            root = ET.parse(xml_in).getroot()
            updated = 0
            
            for image in root.findall('.//image'):
                pid = Path(image.get('name', '')).stem 
                if pid not in metadata: continue
                    
                new_chars = []
                for box in image.findall('box'):
                    if box.get('label', '').lower() in ['character', 'char']:
                        text = next((a.text for a in box.findall('attribute') if a.get('name') == 'text'), "?")
                        new_chars.append({"character": text, "bbox": [float(box.get('xtl', 0)), float(box.get('ytl', 0)), float(box.get('xbr', 0)), float(box.get('ybr', 0))], "confidence": 1.0, "method": "cvat_manual"})
                
                metadata[pid]["characters"] = new_chars
                metadata[pid]["status"] = "perfect" 
                updated += 1

            with open(meta_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=2, ensure_ascii=False)
            self.import_status.config(text=f"Zaktualizowano {updated} tablic", foreground="green")
            messagebox.showinfo("Sukces", "Zastąpiono wyniki OCR perfekcyjnymi danymi z CVAT.\nMożesz teraz wygenerować zaktualizowany Dataset YOLO klikając zielony przycisk.")
            self._load_preview_data()
        except Exception as e: messagebox.showerror("Błąd", str(e))

    def _pick_file(self, var):
        p = filedialog.askopenfilename(title="Wybierz plik XML", filetypes=[("XML", "*.xml")])
        if p: var.set(p)

    def _run_cvat_export(self):
        work_dir = Path(self.preview_dir_var.get().strip())
        meta_path = work_dir / "metadata.json"
        if not meta_path.exists(): return messagebox.showerror("Błąd", "Brak metadata.json")

        out_xml = work_dir / "annotations.xml"
        out_zip = work_dir / f"{work_dir.name}_CVAT.zip"
        
        self.export_status.config(text="Eksportowanie...", foreground="blue")
        self.frame.update()
        try:
            with open(meta_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
                
            if self.smart_export_var.get():
                filtered = {k: v for k, v in metadata.items() if v.get("status") != "perfect"}
                temp_meta = work_dir / "temp_meta.json"
                with open(temp_meta, 'w', encoding='utf-8') as f: json.dump(filtered, f)
                source_meta = temp_meta
            else:
                source_meta = meta_path

            from ..cvat_tools.cvat_character_exporter import CVATCharacterExporter
            if CVATCharacterExporter().export(source_meta, out_xml):
                from ..cvat_tools.cvat_zip_manager import CVATZipManager
                ok, msg, _ = CVATZipManager.create_cvat_import_zip(out_xml, work_dir / "images", out_zip)
                if ok:
                    self.export_status.config(text=f"Zapisano: {out_zip.name}", foreground="green")
                    messagebox.showinfo("Sukces", "ZIP wygenerowany! Przeciągnij go do CVAT.")
            if self.smart_export_var.get() and temp_meta.exists(): temp_meta.unlink()
        except Exception as e: messagebox.showerror("Błąd", str(e))

    def _run_cvat_import(self):
        xml_in = Path(self.import_cvat_xml_var.get().strip())
        work_dir = Path(self.preview_dir_var.get().strip())
        meta_path = work_dir / "metadata.json"

        if not xml_in.exists() or not meta_path.exists(): return messagebox.showerror("Błąd", "Brak XML lub metadata.json")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
            root = ET.parse(xml_in).getroot()
            updated = 0
            
            for image in root.findall('.//image'):
                pid = Path(image.get('name', '')).stem 
                if pid not in metadata: continue
                    
                new_chars = []
                for box in image.findall('box'):
                    if box.get('label', '').lower() in ['character', 'char']:
                        text = next((a.text for a in box.findall('attribute') if a.get('name') == 'text'), "?")
                        new_chars.append({"character": text, "bbox": [float(box.get('xtl', 0)), float(box.get('ytl', 0)), float(box.get('xbr', 0)), float(box.get('ybr', 0))], "confidence": 1.0, "method": "cvat_manual"})
                
                metadata[pid]["characters"] = new_chars
                metadata[pid]["status"] = "perfect" 
                updated += 1

            with open(meta_path, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=2, ensure_ascii=False)
            self.import_status.config(text=f"Zaktualizowano {updated} tablic", foreground="green")
            messagebox.showinfo("Sukces", "Zastąpiono wyniki OCR perfekcyjnymi danymi z CVAT.\nMożesz teraz przejść do Budowy Datasetu.")
            self._load_preview_data()
        except Exception as e: messagebox.showerror("Błąd", str(e))