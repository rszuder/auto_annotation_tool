#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka ZNAKÓW.
Logicznie podzielona na:
1. Wycinanie tablic (surowe)
2. Wykrywanie znaków i Analiza (OCR/YOLO, Laboratorium Filtrów, Turniej z Cache)
3. Integracje i Dataset YOLO
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
from pathlib import Path
import threading
import xml.etree.ElementTree as ET
import json
import cv2
import os

from ..config import CONFIG, logger
from ..icons import IconManager
from ..character_recognition import PlateGenerator, CharacterDetector, DetectionMethod
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

        # core state
        self.is_processing = False

        # preview/cache state
        self.preview_metadata = {}
        self.preview_plate_ids = []
        self._listbox_pid_by_index = []  # ✅ ZMIANA: index listbox -> pid (żeby nie rozjeżdżało się przy reloadach)
        self._current_photo = None
        self._reloading_preview = False          # ✅ ZMIANA: blokuje render w trakcie przebudowy listy



        # ✅ cache keys (run switching + file changes)
        self._loaded_meta_path = None
        self._loaded_meta_mtime = None

        # ✅ fast test state (separate from extraction)
        self.fast_test_stop = threading.Event()
        self.fast_test_running = False

        # presets (global; later can be project-scoped)
        self.presets_dir = Path(CONFIG.WORKSPACE_DIR) / "8_ocr_presets"
        self.presets_dir.mkdir(parents=True, exist_ok=True)

        # local session
        self.session_file = Path.home() / ".auto_annotation_tool" / "char_tab_session.json"
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.local_session = self._load_local_session()

        def get_val(key, default):
            val = self.local_session.get(key, default)
            return val if val != "" else default

        # vars
        self.detection_method_var = tk.StringVar(value=get_val("char_det_method", "OCR"))
        self.xml_path_var = tk.StringVar(value=get_val("char_xml_path", ""))
        self.images_dir_var = tk.StringVar(value=get_val("char_images_dir", ""))
        self.yolo_model_path_var = tk.StringVar(value=get_val("char_yolo_model", ""))
        self.yolo_device_var = tk.StringVar(value=get_val("char_yolo_device", "auto"))
        self.preview_dir_var = tk.StringVar(value=get_val("char_preview_dir", ""))

        self.ocr_conf_var = tk.DoubleVar(value=float(get_val("char_ocr_conf", 0.25)))
        self.smart_export_var = tk.BooleanVar(value=get_val("char_smart_export", True))

        # lab params
        self.prep_angle_var = tk.DoubleVar(value=float(get_val("char_prep_angle", 0.0)))
        self.prep_height_var = tk.IntVar(value=int(get_val("char_prep_height", 80)))
        self.prep_padding_var = tk.IntVar(value=int(get_val("char_prep_padding", 20)))
        self.prep_clip_var = tk.IntVar(value=int(get_val("char_prep_clip", 255)))
        self.prep_denoise_var = tk.IntVar(value=int(get_val("char_prep_denoise", 0)))
        self.prep_clahe_var = tk.DoubleVar(value=float(get_val("char_prep_clahe", 0.0)))
        self.prep_use_bin_var = tk.BooleanVar(value=get_val("char_prep_use_bin", True))
        self.prep_block_var = tk.IntVar(value=int(get_val("char_prep_block", 15)))
        self.prep_c_var = tk.IntVar(value=int(get_val("char_prep_c", 5)))
        self.prep_erode_var = tk.IntVar(value=int(get_val("char_prep_erode", 0)))
        self.do_clahe_var = tk.BooleanVar(value=get_val("char_do_clahe", True))
        self.interpolation_var = tk.StringVar(value=get_val("char_interpolation", "lanczos4"))

        self._create_widgets()
        self._update_yolo_visibility()

        self.app.root.bind("<Destroy>", self._on_app_close, add="+")
        if self.preview_dir_var.get().strip():
            self.frame.after(100, lambda: self._load_preview_data(quiet=True))

    # =========================================================
    # Small helpers
    # =========================================================

    def _reset_preview_cache(self):
        self.preview_metadata = {}
        self._loaded_meta_path = None
        self._loaded_meta_mtime = None

    def clear_campaign_context(self):
        """
        ✅ ZMIANA: czyści projektowe ścieżki i override’y po wyjściu z projektu.
        Przywraca stan neutralny dla trybu swobodnego.
        """
        # usuń override’y projektowe
        if hasattr(self, "_campaign_chars_dir"):
            self._campaign_chars_dir = None
        if hasattr(self, "_campaign_datasets_dir"):
            self._campaign_datasets_dir = None

        # wyczyść źródła projektu
        self.xml_path_var.set("")
        self.images_dir_var.set("")
        self.preview_dir_var.set("")

        # wyczyść podgląd
        self._reset_preview_cache()
        self.preview_plate_ids = []

        try:
            self.plates_listbox.delete(0, tk.END)
        except Exception:
            pass

        try:
            self.preview_canvas.delete("all")
        except Exception:
            pass

        try:
            self.preview_info_lbl.config(text="Brak wczytanych danych", foreground="#2980b9")
        except Exception:
            pass

    def _atomic_write_json(self, path: Path, data: dict):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def _load_local_session(self):
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_local_setting(self, key, value):
        self.local_session[key] = value
        try:
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(self.local_session, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def _force_save_all(self):
        try:
            for k, var in [
                ("char_det_method", self.detection_method_var),
                ("char_xml_path", self.xml_path_var),
                ("char_images_dir", self.images_dir_var),
                ("char_yolo_model", self.yolo_model_path_var),
                ("char_yolo_device", self.yolo_device_var),
                ("char_preview_dir", self.preview_dir_var),
                ("char_ocr_conf", self.ocr_conf_var),
                ("char_smart_export", self.smart_export_var),
                ("char_prep_angle", self.prep_angle_var),
                ("char_prep_height", self.prep_height_var),
                ("char_prep_padding", self.prep_padding_var),
                ("char_prep_clip", self.prep_clip_var),
                ("char_prep_denoise", self.prep_denoise_var),
                ("char_prep_clahe", self.prep_clahe_var),
                ("char_prep_use_bin", self.prep_use_bin_var),
                ("char_prep_block", self.prep_block_var),
                ("char_prep_c", self.prep_c_var),
                ("char_prep_erode", self.prep_erode_var),
                ("char_do_clahe", self.do_clahe_var),
                ("char_interpolation", self.interpolation_var),
            ]:
                self._save_local_setting(k, var.get())
        except Exception:
            pass

    def _on_app_close(self, event):
        if str(event.widget) == str(self.app.root):
            self._force_save_all()

    def _on_method_change(self, event=None):
        self._update_yolo_visibility()

    def _update_yolo_visibility(self):
        # ✅ fix: używamy self.yolo_panel (bo tak faktycznie nazywasz ten panel)
        if not hasattr(self, "yolo_panel"):
            return
        method = (self.detection_method_var.get() or "OCR").upper().strip()
        if method in ["YOLO", "BOTH"]:
            self.yolo_panel.pack(fill=tk.X, pady=(5, 0))
        else:
            self.yolo_panel.pack_forget()

    def _get_available_devices(self):
        devices = ["auto", "cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    devices.append(f"cuda:{i}")
        except Exception:
            pass
        return devices

    def _device_to_ultralytics(self, s: str):
        if s == "auto":
            return "auto"
        if s == "cpu":
            return "cpu"
        if s.startswith("cuda:"):
            try:
                return int(s.split(":")[1].split()[0])
            except Exception:
                return 0
        return "auto"

    # =========================================================
    # Pickers
    # =========================================================

    def _pick_xml_file(self):
        p = filedialog.askopenfilename(
            initialdir=str(Path(CONFIG.DIR_2_AUTO_ANN).absolute()),
            title="Wybierz annotations.xml",
            filetypes=[("XML", "*.xml")]
        )
        if p:
            self.xml_path_var.set(p)

    def _pick_images_dir(self):
        p = filedialog.askdirectory(
            initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()),
            title="Wybierz folder z obrazami pojazdów"
        )
        if p:
            self.images_dir_var.set(p)

    def _pick_yolo_model(self):
        p = filedialog.askopenfilename(
            initialdir=str(Path(CONFIG.DIR_6_MODELS).absolute()),
            title="Wybierz model YOLO (.pt)",
            filetypes=[("PyTorch", "*.pt")]
        )
        if p:
            self.yolo_model_path_var.set(p)

    def _pick_and_load_preview_dir(self):
        initial = getattr(self, "_campaign_chars_dir", str(Path(CONFIG.DIR_3_CHARS).absolute()))
        p = filedialog.askdirectory(initialdir=str(initial), title="Wybierz folder wyników (zawierający metadata.json)")
        if p:
            self.preview_dir_var.set(p)
            self._force_save_all()
            self._reset_preview_cache()
            self._load_preview_data()

    # =========================================================
    # Logging helper
    # =========================================================

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
                if "✅" in msg:
                    final_tag = "SUCCESS"
                elif "❌" in msg:
                    final_tag = "ERROR"
            txt_widget.insert(tk.END, msg + "\n", final_tag)
            txt_widget.see(tk.END)
        self.frame.after(0, do_log)

    def _get_true_texts_from_filename(self, filename: str) -> list:
        stem = Path(filename).stem.upper()
        import re
        parts = re.findall(r'[A-Z0-9]{4,}', stem)
        if not parts:
            return []
        if len(parts) > 1:
            return parts[:-1]
        return parts

    def _get_current_prep_params(self):
        return {
            "target_height": self.prep_height_var.get(),
            "manual_angle": self.prep_angle_var.get(),
            "clip_thresh": self.prep_clip_var.get(),
            "denoise_h": self.prep_denoise_var.get(),
            "clahe_clip": self.prep_clahe_var.get() if self.do_clahe_var.get() else 0.0,
            "use_binarization": self.prep_use_bin_var.get(),
            "thresh_block": self.prep_block_var.get(),
            "thresh_c": self.prep_c_var.get(),
            "erode_iter": self.prep_erode_var.get(),
            "interpolation": self.interpolation_var.get(),
            "padding_pct": self.prep_padding_var.get(),
        }

    def _get_best_preset(self):
        cache_file = self.presets_dir / "global_ranking.json"
        if not cache_file.exists():
            return None, 0.0
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            best_name, best_acc, best_params = None, -1.0, {}
            for preset_key, stats in data.items():
                acc = float(stats.get("acc", 0.0))
                if acc > best_acc:
                    best_acc, best_name, best_params = acc, str(stats.get("name", preset_key)), stats.get("params", {})
            if best_name:
                return {"name": best_name, "params": best_params}, best_acc
        except Exception:
            pass
        return None, 0.0

    # =========================================================
    # UI build
    # =========================================================

    def _create_widgets(self):
        self.main_nb = ttk.Notebook(self.frame)
        self.main_nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        tab1 = ttk.Frame(self.main_nb)
        self.main_nb.add(tab1, text=f"{self.icon_manager.get('cut')} 1. Wycinanie Tablic")
        self._build_extraction_tab(tab1)

        tab2 = ttk.Frame(self.main_nb)
        self.main_nb.add(tab2, text=f"{self.icon_manager.get('eye')} 2. Wykrywanie Znaków i Analiza")
        self._build_detection_tab(tab2)

        tab3 = ttk.Frame(self.main_nb)
        self.main_nb.add(tab3, text=f"{self.icon_manager.get('save')} 3. Integracje i Dataset (YOLO)")
        self._build_cvat_tab(tab3)

    # =========================================================
    # TAB 1: Extraction
    # =========================================================

    def _build_extraction_tab(self, parent):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)

        lf_paths = ttk.LabelFrame(left, text=" Ścieżki do źródła ", padding=15)
        lf_paths.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(lf_paths, text="annotations.xml (z Zakładki Autoanotacja):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row_xml = ttk.Frame(lf_paths)
        row_xml.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(row_xml, textvariable=self.xml_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row_xml, text="Wybierz", command=self._pick_xml_file).pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Label(lf_paths, text="Folder ze zdjęciami aut (źródło):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        row_img = ttk.Frame(lf_paths)
        row_img.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(row_img, textvariable=self.images_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row_img, text="Wybierz", command=self._pick_images_dir).pack(side=tk.RIGHT, padx=(5, 0))

        lf_run = ttk.LabelFrame(left, text=" Wycinanie Tablic ", padding=15)
        lf_run.pack(fill=tk.X)

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

        HELP.bind_help(row_xml, "t2_xml")
        HELP.bind_help(row_img, "t2_img")
        HELP.bind_help(self.btn_extract, "t2_cut_start")
        HELP.bind_help(lf_logs, "t2_cut_logs")

    def _run_extraction(self):
        self._force_save_all()
        xml_path = Path(self.xml_path_var.get().strip())
        images_dir = Path(self.images_dir_var.get().strip())

        if not xml_path.exists() or not images_dir.exists():
            return messagebox.showerror("Błąd", "Brak plików wejściowych!")

        import datetime
        base_out_dir = Path(getattr(self, "_campaign_chars_dir", str(CONFIG.DIR_3_CHARS)))
        base_out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        counter = 1
        while True:
            run_dir = base_out_dir / f"run_{counter:03d}_{timestamp}"
            if not run_dir.exists():
                break
            counter += 1

        run_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir_var.set(str(run_dir))
        self._reset_preview_cache()
        self._force_save_all()

        try:
            tree = ET.parse(xml_path)
            xml_images = {img.get("name"): img for img in tree.getroot().findall(".//image") if img.get("name")}
        except Exception:
            return messagebox.showerror("Błąd", "Zły plik XML.")

        self.btn_extract.config(state=tk.DISABLED)
        self.btn_ext_stop.config(state=tk.NORMAL)
        self.is_processing = True

        def worker():
            try:
                self._log(self.ext_log, f"\nROZPOCZĘTO WYCINANIE DO: {run_dir.name}\n", "HEADER")
                generator = PlateGenerator(run_dir)
                total = len(xml_images)
                processed = 0

                for img_name, img_el in xml_images.items():
                    if not self.is_processing:
                        break
                    img_path = images_dir / img_name
                    if not img_path.exists():
                        processed += 1
                        continue

                    plates = []
                    for poly in img_el.findall(".//polygon[@label='plate']"):
                        pts = [tuple(map(float, p.split(","))) for p in poly.get("points", "").split(";")]
                        if len(pts) >= 4:
                            plates.append(
                                Detection(
                                    "plate", 1.0,
                                    (min(x for x, y in pts), min(y for x, y in pts), max(x for x, y in pts), max(y for x, y in pts)),
                                    polygon=pts
                                )
                            )

                    if plates:
                        ann = ImageAnnotation(img_name, int(img_el.get("width", 0)), int(img_el.get("height", 0)), plates)
                        generator.generate_from_annotations(
                            img_path, ann,
                            rectify=True,
                            do_deskew=False,
                            enhance_contrast=False,
                            interpolation=self.interpolation_var.get()
                        )

                    processed += 1
                    self.frame.after(0, lambda p=(processed / max(1, total)) * 100: self.ext_progress.config(value=p))
                    self.frame.after(0, lambda c=processed, t=total: self.ext_status.config(text=f"{c}/{t} obrazów..."))

                generator.save_metadata()
                if self.is_processing:
                    self.frame.after(0, lambda: self._load_preview_data(quiet=True))
                    self.frame.after(0, lambda: messagebox.showinfo("Gotowe", "Wycinanie zakończone!"))
            except Exception as e:
                self._log(self.ext_log, f"\n❌ BŁĄD: {e}\n", "ERROR")
            finally:
                self.is_processing = False
                self.frame.after(0, lambda: self.btn_extract.config(state=tk.NORMAL))
                self.frame.after(0, lambda: self.btn_ext_stop.config(state=tk.DISABLED))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 2: Detection + Preview
    # =========================================================

    def _build_detection_tab(self, parent):
        top_frame = ttk.Frame(parent)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(top_frame, text="Paczka do analizy (folder run_XXX):", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Entry(top_frame, textvariable=self.preview_dir_var, width=45, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        ttk.Button(top_frame, text="Otwórz inną paczkę", command=self._pick_and_load_preview_dir).pack(side=tk.LEFT, padx=(0, 5))

        self.preview_info_lbl = ttk.Label(top_frame, text="Wczytano tablic: 0", font=("Segoe UI", 9, "bold"), foreground="#2980b9")
        self.preview_info_lbl.pack(side=tk.RIGHT, padx=10)

        main_pane = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        top_split = ttk.Frame(main_pane, height=450)
        bottom_split = ttk.Frame(main_pane, height=200)
        main_pane.add(top_split, weight=5)
        main_pane.add(bottom_split, weight=0)

        viewer_pane = ttk.PanedWindow(top_split, orient=tk.HORIZONTAL)
        viewer_pane.pack(fill=tk.BOTH, expand=True)

        list_lf = ttk.LabelFrame(viewer_pane, text=" Lista tablic (🟢 Perfekt | 🔴 Błędy) ")
        preview_lf = ttk.LabelFrame(viewer_pane, text=" Podgląd OCR ")
        viewer_pane.add(list_lf, weight=2)
        viewer_pane.add(preview_lf, weight=3)

        self.plates_listbox = tk.Listbox(list_lf, font=("Consolas", 10), selectbackground="#3498db")
        self.plates_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
        scroll = ttk.Scrollbar(list_lf, command=self.plates_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)
        self.plates_listbox.config(yscrollcommand=scroll.set)
        self.plates_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

        self.preview_canvas = tk.Canvas(preview_lf, bg="#1e1e1e", bd=3, relief="sunken", highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, pady=8, padx=8)
        self.preview_canvas.bind("<Configure>", lambda e: self._on_preview_select(None))

        bottom_cols = ttk.Frame(bottom_split)
        bottom_cols.pack(fill=tk.BOTH, expand=True)

        col_left = ttk.Frame(bottom_cols)
        col_mid = ttk.Frame(bottom_cols)
        col_right = ttk.Frame(bottom_cols)

        col_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        col_mid.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        col_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        set_lf = ttk.LabelFrame(col_left, text=" Konfiguracja Rozpoznawania ", padding=10)
        set_lf.pack(fill=tk.BOTH, expand=True)

        row_meth = ttk.Frame(set_lf)
        row_meth.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(row_meth, text="Metoda:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        combo = ttk.Combobox(row_meth, textvariable=self.detection_method_var, values=["OCR", "YOLO", "BOTH"], state="readonly", width=12)
        combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        combo.bind("<<ComboboxSelected>>", self._on_method_change)

        dev_row = ttk.Frame(set_lf)
        dev_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(dev_row, text="Karta (Device):").pack(side=tk.LEFT)
        dev_combo = ttk.Combobox(dev_row, textvariable=self.yolo_device_var, values=self._get_available_devices(), state="readonly", width=12)
        dev_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))

        # YOLO panel (toggle)
        self.yolo_panel = ttk.Frame(set_lf)
        ttk.Label(self.yolo_panel, text="Model YOLO .pt:").pack(anchor=tk.W, pady=(5, 0))
        r_y = ttk.Frame(self.yolo_panel)
        r_y.pack(fill=tk.X)
        ttk.Entry(r_y, textvariable=self.yolo_model_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(r_y, text="Wybierz", command=self._pick_yolo_model).pack(side=tk.RIGHT)

        self._update_yolo_visibility()

        ttk.Separator(set_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(20, 15))
        lab_frame = ttk.Frame(set_lf)
        lab_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(lab_frame, text="Zbyt dużo błędów OCR?", foreground="gray", font=("Segoe UI", 9, "italic")).pack(anchor=tk.W, pady=(0, 5))
        btn_lab = ttk.Button(lab_frame, text="🔬 LABORATORIUM OCR (FILTRY)", command=self._open_filter_lab, style="Accent.TButton")
        btn_lab.pack(fill=tk.X, ipady=8)

        logs_test_lf = ttk.LabelFrame(col_mid, text=" Logi z Analizy i Testów ")
        logs_test_lf.pack(fill=tk.BOTH, expand=True)
        logs_test_lf.pack_propagate(False)
        self.test_log_text = scrolledtext.ScrolledText(logs_test_lf, wrap=tk.WORD, font=("Consolas", 9), bg="#fcfcfc", height=8)
        self.test_log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        actions_lf = ttk.LabelFrame(col_right, text=" Uruchom Przetwarzanie ", padding=10)
        actions_lf.pack(fill=tk.BOTH, expand=True)

        self.winner_name_lbl = ttk.Label(actions_lf, text="BRAK DANYCH", font=("Segoe UI", 11, "bold"), foreground="gray")
        self.winner_name_lbl.pack(anchor=tk.CENTER, pady=(0, 5))
        self.winner_acc_lbl = ttk.Label(actions_lf, text="Skuteczność: 0.0%", font=("Segoe UI", 10))
        self.winner_acc_lbl.pack(anchor=tk.CENTER, pady=(0, 10))

        self.btn_fast_ocr = ttk.Button(actions_lf, text="1. Odczytaj znaki tablic (Szybki Test)", command=self._run_fast_ocr_test, style="Accent.TButton")
        self.btn_fast_ocr.pack(fill=tk.X, ipady=8, pady=(10, 5))

        self.btn_rank_presets = ttk.Button(actions_lf, text="2. Turniej (Zbadaj paczkę Presetami)", command=self._run_preset_ranking)
        self.btn_rank_presets.pack(fill=tk.X, ipady=6)

        self.test_progress = ttk.Progressbar(actions_lf, maximum=100)
        self.test_progress.pack(fill=tk.X, pady=(15, 5))
        self.test_status_lbl = ttk.Label(actions_lf, text="Gotowy do testów", foreground="#2ecc71", font=("Segoe UI", 9, "bold"))
        self.test_status_lbl.pack(anchor=tk.W)

        HELP.bind_help(top_frame, "t2_history")
        HELP.bind_help(self.plates_listbox, "t2_listbox")
        HELP.bind_help(self.preview_canvas, "t2_canvas")
        HELP.bind_help(self.btn_fast_ocr, "t2_fast_test")
        HELP.bind_help(self.btn_rank_presets, "t2_rank")
        HELP.bind_help(combo, "t2_method")
        HELP.bind_help(btn_lab, "t2_lab_btn")
        HELP.bind_help(r_y, "t2_yolo_model")

    def _update_winner_label(self):
        best_preset_data, best_acc = self._get_best_preset()
        if best_preset_data and best_preset_data.get("name"):
            name = best_preset_data.get("name")
            self.winner_name_lbl.config(text=name.upper(), foreground="#27ae60")
            self.winner_acc_lbl.config(text=f"Skuteczność: {best_acc:.1f}%", foreground="black")
        else:
            self.winner_name_lbl.config(text="BRAK DANYCH Z TURNIEJU", foreground="gray")
            self.winner_acc_lbl.config(text="Skuteczność: 0.0%", foreground="gray")

    # =========================================================
    # Preview load + render
    # =========================================================
    def _load_preview_data(self, quiet=False):
        out_dir = Path(self.preview_dir_var.get().strip())
        meta_path = out_dir / "metadata.json"

        self.frame.after(0, self._update_winner_label)

        if not meta_path.exists():
            if not quiet:
                messagebox.showerror("Brak pliku", f"Nie znaleziono metadata.json w folderze:\n{out_dir}")
            self.preview_info_lbl.config(text="Brak wczytanych danych", foreground="red")
            return

        try:
            current_mtime = meta_path.stat().st_mtime
            need_reload = (
                self._loaded_meta_path != meta_path
                or self._loaded_meta_mtime != current_mtime
            )

            if (not self.preview_metadata) or (not quiet) or need_reload:
                with open(meta_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    loaded = {}

                self.preview_metadata = loaded
                self._loaded_meta_path = meta_path
                self._loaded_meta_mtime = current_mtime

                # Normalizacja schematu
                changed = False
                for pid, d in self.preview_metadata.items():
                    if not isinstance(d, dict):
                        continue
                    if "status" not in d:
                        d["status"] = "unknown"
                        changed = True
                    if "characters" not in d or not isinstance(d.get("characters"), list):
                        d["characters"] = []
                        changed = True

                if changed:
                    self._atomic_write_json(meta_path, self.preview_metadata)
                    self._loaded_meta_mtime = meta_path.stat().st_mtime

            # ==========================================================
            # ✅ START BLOKADY - Canvas nie może nic rysować w trakcie tej pętli
            # ==========================================================
            self._reloading_preview = True
            
            self.preview_plate_ids = sorted(list(self.preview_metadata.keys()))
            self.plates_listbox.delete(0, tk.END)
            self._listbox_pid_by_index = []  # Reset mapy PIDów

            for idx, pid in enumerate(self.preview_plate_ids):
                data = self.preview_metadata.get(pid, {})
                status = str(data.get("status", "unknown"))
                chars = data.get("characters", [])

                clean_chars = []
                if isinstance(chars, list):
                    for c in chars:
                        if isinstance(c, dict) and "character" in c and "bbox" in c:
                            bbox = c.get("bbox", [])
                            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                                clean_chars.append(c)

                clean_chars.sort(key=lambda x: float(x["bbox"][0]))
                text = "".join([str(c.get("character", "")).strip() for c in clean_chars])

                icon = "🟢" if status == "perfect" else "🔴" if status == "needs_fix" else "⚪"
                display_text = f"[{idx+1:03d}] {icon} Plik: {pid}  |  Odczyt: [{text}]"
                
                self.plates_listbox.insert(tk.END, display_text)
                self._listbox_pid_by_index.append(pid)  # Mapa 1:1 z wierszem

                current_idx = self.plates_listbox.size() - 1
                if status == "perfect":
                    self.plates_listbox.itemconfig(current_idx, foreground="#27ae60")
                elif status == "needs_fix":
                    self.plates_listbox.itemconfig(current_idx, foreground="#c0392b")

            self.preview_info_lbl.config(
                text=f"Wczytano tablic: {len(self.preview_plate_ids)} z folderu: {out_dir.name}",
                foreground="green"
            )

            if self.preview_plate_ids:
                self.plates_listbox.selection_set(0)
                self._on_preview_select(None)

            self.frame.after(100, self._update_winner_label)

        except Exception as e:
            if not quiet:
                messagebox.showerror("Błąd odświeżania listy", str(e))
            logger.error(f"Błąd _load_preview_data: {e}")
        finally:
            # ==========================================================
            # ✅ KONIEC BLOKADY - Zawsze zdejmij flagę, nawet jak jest błąd
            # ==========================================================
            self._reloading_preview = False

    def _refresh_listbox_rows_from_metadata(self):
        """Pełne odświeżenie tekstów i kolorów listy na podstawie aktualnego self.preview_metadata."""
        if not hasattr(self, "plates_listbox"):
            return

        self._reloading_preview = True
        try:
            current_sel = self.plates_listbox.curselection()
            selected_idx = int(current_sel[0]) if current_sel else None

            self.plates_listbox.delete(0, tk.END)
            self._listbox_pid_by_index = []

            self.preview_plate_ids = sorted(list(self.preview_metadata.keys()))

            for idx, pid in enumerate(self.preview_plate_ids):
                data = self.preview_metadata.get(pid, {})
                status = str(data.get("status", "unknown"))
                chars = data.get("characters", [])

                clean_chars = []
                if isinstance(chars, list):
                    for c in chars:
                        if isinstance(c, dict) and "character" in c and "bbox" in c:
                            bbox = c.get("bbox", [])
                            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                                clean_chars.append(c)

                clean_chars.sort(key=lambda x: float(x.get("bbox", [0])[0]))
                text = "".join([str(c.get("character", "")).strip() for c in clean_chars])

                icon = "🟢" if status == "perfect" else "🔴" if status == "needs_fix" else "⚪"
                display_text = f"[{idx+1:03d}] {icon} Plik: {pid}  |  Odczyt: [{text}]"

                self.plates_listbox.insert(tk.END, display_text)
                self._listbox_pid_by_index.append(pid)

                if status == "perfect":
                    self.plates_listbox.itemconfig(idx, foreground="#27ae60")
                elif status == "needs_fix":
                    self.plates_listbox.itemconfig(idx, foreground="#c0392b")
                else:
                    self.plates_listbox.itemconfig(idx, foreground="#444444")

            # Przywróć zaznaczenie, jeśli było
            if selected_idx is not None and 0 <= selected_idx < self.plates_listbox.size():
                self.plates_listbox.selection_set(selected_idx)
                self.plates_listbox.activate(selected_idx)

        finally:
            self._reloading_preview = False

    def _on_preview_select(self, event=None):
        """Podgląd tablicy + bboxy znaków. PID bierzemy z TEKSTU wiersza listy (zero rozjazdów)."""
        if not PIL_AVAILABLE:
            return

        # ✅ ZMIANA: jeśli akurat przebudowujemy listę - nie renderujemy
        if getattr(self, "_reloading_preview", False):
            return

        sel = self.plates_listbox.curselection()
        if not sel:
            return

        idx = int(sel[0])
        row_text = self.plates_listbox.get(idx)

        # ✅ ZMIANA: wyciągamy pid z wiersza listboxa (zawsze spójne z tym, co widzisz)
        import re
        m = re.search(r"Plik:\s*([^\s|]+)", row_text)
        if not m:
            return
        pid = m.group(1).strip()

        data = self.preview_metadata.get(pid, {})
        chars = data.get("characters", [])

        # ✅ ZMIANA: sort + tekst do podglądu (TA sama logika co lista)
        clean_chars = []
        if isinstance(chars, list):
            for c in chars:
                if isinstance(c, dict) and "character" in c and "bbox" in c:
                    bbox = c.get("bbox", [])
                    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                        clean_chars.append(c)

        clean_chars.sort(key=lambda x: float(x.get("bbox", [0])[0]))
        text_now = "".join([str(c.get("character", "")).strip() for c in clean_chars])

        status = str(data.get("status", "unknown"))
        icon = "🟢" if status == "perfect" else "🔴" if status == "needs_fix" else "⚪"
        display_text = f"[{idx+1:03d}] {icon} Plik: {pid}  |  Odczyt: [{text_now}]"

        # ✅ ZMIANA: samoleczenie listy - jeśli wiersz pokazuje stare `[...]`, nadpisz go
        if row_text != display_text:
            try:
                self._reloading_preview = True
                self.plates_listbox.delete(idx)
                self.plates_listbox.insert(idx, display_text)

                if status == "perfect":
                    self.plates_listbox.itemconfig(idx, foreground="#27ae60")
                elif status == "needs_fix":
                    self.plates_listbox.itemconfig(idx, foreground="#c0392b")
                else:
                    self.plates_listbox.itemconfig(idx, foreground="#000000")

                self.plates_listbox.selection_clear(0, tk.END)
                self.plates_listbox.selection_set(idx)
            finally:
                self._reloading_preview = False

        img_path = Path(self.preview_dir_var.get().strip()) / "images" / f"{pid}.jpg"
        self.preview_canvas.delete("all")
        if not img_path.exists():
            return

        try:
            pil_img = Image.open(img_path)
            orig_w, orig_h = pil_img.size

            c_w = max(50, self.preview_canvas.winfo_width())
            c_h = max(50, self.preview_canvas.winfo_height())

            margin_x, margin_y_top, margin_y_bottom = 80, 40, 140
            scale_w = (c_w - margin_x) / float(orig_w)
            scale_h = (c_h - (margin_y_top + margin_y_bottom)) / float(orig_h)
            SCALE = max(1.0, min(min(scale_w, scale_h), 6.0))

            new_w, new_h = int(orig_w * SCALE), int(orig_h * SCALE)
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            self._current_photo = ImageTk.PhotoImage(pil_img)
            x_off = (c_w - new_w) // 2
            y_off = (c_h - new_h - margin_y_bottom + margin_y_top) // 2

            self.preview_canvas.create_image(x_off, y_off, anchor=tk.NW, image=self._current_photo)
            image_bottom_y = y_off + new_h

            # rysowanie bboxów + znaków
            for c in clean_chars:
                x1, y1, x2, y2 = c.get("bbox", [0, 0, 0, 0])
                cx1, cy1 = (float(x1) * SCALE) + x_off, (float(y1) * SCALE) + y_off
                cx2, cy2 = (float(x2) * SCALE) + x_off, (float(y2) * SCALE) + y_off
                center_x = cx1 + (cx2 - cx1) / 2

                self.preview_canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="#00ff00", width=2)

                text_anchor_y = image_bottom_y + 35
                self.preview_canvas.create_line(center_x, cy2, center_x, text_anchor_y - 20,
                                                fill="#2ecc71", dash=(2, 2))

                char_text = str(c.get("character", ""))
                self.preview_canvas.create_text(center_x + 1, text_anchor_y + 1, text=char_text,
                                                fill="#000000", font=("Segoe UI", 18, "bold"), anchor=tk.CENTER)
                self.preview_canvas.create_text(center_x, text_anchor_y, text=char_text,
                                                fill="#f1c40f", font=("Segoe UI", 18, "bold"), anchor=tk.CENTER)

        except Exception as e:
            logger.error(f"Błąd wyświetlania podglądu tablicy: {e}")

    # =========================================================
    # Fast test UI lock/unlock
    # =========================================================

    def _lock_ui_for_testing(self):
        self.btn_fast_ocr.config(state=tk.DISABLED)
        self.btn_rank_presets.config(state=tk.DISABLED)
        self.plates_listbox.config(state=tk.DISABLED)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            self.preview_canvas.winfo_width() / 2,
            self.preview_canvas.winfo_height() / 2,
            text="Przetwarzanie...",
            fill="gray",
            font=("Arial", 12, "italic")
        )

    def _unlock_ui_after_testing(self):
        self.btn_fast_ocr.config(state=tk.NORMAL)
        self.btn_rank_presets.config(state=tk.NORMAL)
        self.plates_listbox.config(state=tk.NORMAL)

        # ✅ zdejmij napis "Przetwarzanie..." jeśli canvas się nie odrysował
        if self.preview_plate_ids:
            sel = self.plates_listbox.curselection()
            if not sel:
                self.plates_listbox.selection_set(0)
                self.plates_listbox.activate(0)

            try:
                self._on_preview_select(None)
            except Exception as e:
                logger.error(f"Błąd odblokowania podglądu po teście: {e}")
                self.preview_canvas.delete("all")
                self.preview_canvas.create_text(
                    self.preview_canvas.winfo_width() / 2,
                    self.preview_canvas.winfo_height() / 2,
                    text="Nie udało się odświeżyć podglądu",
                    fill="red",
                    font=("Arial", 11, "italic")
                )
        else:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(
                self.preview_canvas.winfo_width() / 2,
                self.preview_canvas.winfo_height() / 2,
                text="Brak danych do podglądu",
                fill="gray",
                font=("Arial", 11, "italic")
            )

    # =========================================================
    # FAST OCR TEST (stable)
    # =========================================================

    def _run_fast_ocr_test(self):
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj paczkę!")

        if self.fast_test_running:
            return

        self._force_save_all()
        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"

        self.test_log_text.delete(1.0, tk.END)
        self._lock_ui_for_testing()

        self.fast_test_stop.clear()
        self.fast_test_running = True

        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "START - Szybki Test Celności\n", "HEADER")

        method_str = (self.detection_method_var.get() or "OCR").strip().lower()
        try:
            method = DetectionMethod(method_str)
        except Exception:
            method = DetectionMethod.OCR

        yolo_model = None
        if method in [DetectionMethod.YOLO, DetectionMethod.BOTH] and YOLO is not None:
            try:
                yolo_model = YOLO(str(self.yolo_model_path_var.get()))
            except Exception as e:
                self._log(self.test_log_text, f"Błąd YOLO: {e}", "ERROR")
                yolo_model = None

        prep_params = self._get_current_prep_params()
        ocr_engine = None
        if method in [DetectionMethod.OCR, DetectionMethod.BOTH]:
            try:
                use_gpu = self.yolo_device_var.get().split()[0].lower().startswith("cuda")
                ocr_engine = PlateOCR(device="cuda" if use_gpu else "cpu", confidence_threshold=self.ocr_conf_var.get())
                ocr_engine.custom_prep_params = prep_params
            except Exception as e:
                self._log(self.test_log_text, f"Błąd OCR Engine: {e}", "ERROR")
                ocr_engine = None

        detector = CharacterDetector(method=method, ocr_engine=ocr_engine, yolo_model=yolo_model)

        def worker():
            try:
                total = len(self.preview_plate_ids)
                stat_perfect = 0

                local_meta = dict(self.preview_metadata) if isinstance(self.preview_metadata, dict) else {}

                for idx, pid in enumerate(self.preview_plate_ids):
                    if self.fast_test_stop.is_set():
                        break

                    img_path = imgs_dir / f"{pid}.jpg"
                    if not img_path.exists():
                        continue

                    img = cv2.imread(str(img_path))
                    if img is None:
                        continue

                    if pid not in local_meta or not isinstance(local_meta.get(pid), dict):
                        local_meta[pid] = {}

                    source_image = local_meta[pid].get("source_image", "") or ""
                    true_texts = self._get_true_texts_from_filename(source_image)

                    chars = detector.detect(img)

                    c_clean = [{
                        "character": str(c.character),
                        "bbox": [float(x) for x in c.bbox],
                        "confidence": float(c.confidence),
                        "method": str(c.method),
                    } for c in chars]

                    local_meta[pid]["characters"] = c_clean

                    if c_clean:
                        c_clean.sort(key=lambda x: float(x["bbox"][0]))
                        txt = "".join([str(c["character"]) for c in c_clean])
                        if txt in true_texts:
                            local_meta[pid]["status"] = "perfect"
                            stat_perfect += 1
                            self._log(self.test_log_text, f"✅ [{idx+1:03d}/{total}] {pid}: {txt}", "SUCCESS")
                        else:
                            local_meta[pid]["status"] = "needs_fix"
                            expected_str = " / ".join(true_texts) if true_texts else "Brak"
                            self._log(self.test_log_text, f"❌ [{idx+1:03d}/{total}] {pid}: Odczyt=[{txt}] (Oczek: [{expected_str}])", "ERROR")
                    else:
                        local_meta[pid]["status"] = "needs_fix"
                        self._log(self.test_log_text, f"❌ [{idx+1:03d}/{total}] {pid}: NIC NIE ZNALEZIONO", "ERROR")

                    self.frame.after(0, lambda p=((idx + 1) / max(1, total)) * 100: self.test_progress.config(value=p))
                    self.frame.after(0, lambda c=idx+1, t=total: self.test_status_lbl.config(text=f"Testuję: {c} z {t}", foreground="#e67e22"))

                meta_file = out_dir / "metadata.json"
                self._atomic_write_json(meta_file, local_meta)
                self.preview_metadata = local_meta

                plates_with_chars = sum(
                    1 for pid in self.preview_plate_ids
                    if isinstance(local_meta.get(pid), dict) and local_meta[pid].get("characters")
                )
                self._log(self.test_log_text, f"\n[DIAG] Tablice z wykrytymi znakami: {plates_with_chars}/{total}", "INFO")

                acc = (stat_perfect / total * 100) if total > 0 else 0
                self._log(self.test_log_text, f"\nSkuteczność: {acc:.1f}% ({stat_perfect}/{total} tablic)", "SUCCESS" if acc >= 80 else "WARNING")

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD: {e}", "ERROR")
            finally:
                def finalize():
                    try:
                        self.fast_test_running = False
                        self.fast_test_stop.clear()

                        # ✅ najpierw odśwież dane
                        self._reset_preview_cache()
                        self._load_preview_data(quiet=True)
                        self._refresh_listbox_rows_from_metadata()

                        # ✅ jeśli nic nie zaznaczone, zaznacz pierwszy wpis
                        if self.plates_listbox.size() > 0:
                            sel = self.plates_listbox.curselection()
                            if not sel:
                                self.plates_listbox.selection_set(0)

                        # ✅ odśwież canvas
                        self._on_preview_select(None)

                        self.test_progress.config(value=100)
                        self.test_status_lbl.config(text="Zakończono Test!", foreground="#2ecc71")

                    except Exception as e:
                        logger.error(f"Błąd finalize() po Szybkim Teście: {e}")
                        self.test_status_lbl.config(text="Błąd odświeżania UI", foreground="#c0392b")

                    finally:
                        # ✅ NAJWAŻNIEJSZE: UI ma się odblokować ZAWSZE, nawet przy błędzie
                        self._unlock_ui_after_testing()

                self.frame.after(200, finalize)

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================
    # TAB 3: CVAT + YOLO exports/imports
    # =========================================================

    def _build_cvat_tab(self, parent):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        export_lf = ttk.LabelFrame(pane, text=" EKSPORTY (Dane Wyjściowe) ", padding=15)
        pane.add(export_lf, weight=1)

        cvat_f = ttk.Frame(export_lf)
        cvat_f.pack(fill=tk.X, pady=(5, 5))
        ttk.Label(cvat_f, text="OPCJA 1: Ręczna poprawa błędów", font=("Segoe UI", 10, "bold"), foreground="#c0392b").pack(anchor=tk.W)
        ttk.Label(cvat_f, text="Generuje plik .ZIP dla programu CVAT. Eksportowane są tylko tablice z błędami (🔴).", foreground="gray").pack(anchor=tk.W, pady=(2, 8))

        cb_smart = ttk.Checkbutton(cvat_f, text="Tylko tablice z błędami (Czerwone)", variable=self.smart_export_var)
        cb_smart.pack(anchor=tk.W)

        btn_cvat = ttk.Button(cvat_f, text="WYGENERUJ .ZIP DLA CVAT", command=self._run_cvat_export, style="Accent.TButton")
        btn_cvat.pack(fill=tk.X, pady=(5, 0), ipady=3)

        ttk.Separator(export_lf, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)

        yolo_f = ttk.Frame(export_lf)
        yolo_f.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(yolo_f, text="OPCJA 2: Fabryka Datasetów (Active Learning)", font=("Segoe UI", 10, "bold"), foreground="#27ae60").pack(anchor=tk.W)
        ttk.Label(yolo_f, text="Zbiera 🟢 perfect i buduje dataset YOLO.", foreground="gray").pack(anchor=tk.W, pady=(2, 8))

        btn_yolo = ttk.Button(yolo_f, text="WYEKSPORTUJ PERFEKCYJNE TABLICE DO YOLO", command=self._run_yolo_gold_export, style="Accent.TButton")
        btn_yolo.pack(fill=tk.X, ipady=4)

        info_lf = ttk.LabelFrame(export_lf, text=" Status i Wskazówki ", padding=5)
        info_lf.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        self.export_console = tk.Text(info_lf, height=10, wrap=tk.WORD, font=("Consolas", 10), bg="#f8f9fa", bd=0)
        self.export_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.export_console.insert(tk.END, "Oczekuje na akcję...")
        self.export_console.config(state=tk.DISABLED)

        import_lf = ttk.LabelFrame(pane, text=" IMPORT (Dane Wejściowe) ", padding=15)
        pane.add(import_lf, weight=1)

        ttk.Label(import_lf, text="Aktualizacja Bazy Danych z CVAT", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(import_lf, text="Wskaż XML z CVAT, aby nadpisać błędy OCR.", foreground="gray").pack(anchor=tk.W, pady=(2, 8))

        row2 = ttk.Frame(import_lf)
        row2.pack(fill=tk.X, pady=5)
        self.import_cvat_xml_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.import_cvat_xml_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row2, text="Wybierz XML", command=lambda: self._pick_file(self.import_cvat_xml_var)).pack(side=tk.RIGHT, padx=(5, 0))

        btn_import = ttk.Button(import_lf, text="ZAKTUALIZUJ BAZĘ", command=self._run_cvat_import, style="Accent.TButton")
        btn_import.pack(fill=tk.X, pady=(10, 5), ipady=3)

        import_console_lf = ttk.LabelFrame(import_lf, text=" Status Importu ", padding=5)
        import_console_lf.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        self.import_console = tk.Text(import_console_lf, height=4, wrap=tk.WORD, font=("Consolas", 10), bg="#f8f9fa", bd=0)
        self.import_console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.import_console.insert(tk.END, "Oczekuje na plik XML...")
        self.import_console.config(state=tk.DISABLED)

        HELP.bind_help(cb_smart, "cvat_smart_exp")
        HELP.bind_help(btn_cvat, "btn_export_cvat")
        HELP.bind_help(btn_yolo, "btn_export_yolo")
        HELP.bind_help(btn_import, "btn_import_cvat")

    def _set_console_text(self, console_widget, text):
        console_widget.config(state=tk.NORMAL)
        console_widget.delete(1.0, tk.END)
        console_widget.insert(tk.END, text)
        console_widget.config(state=tk.DISABLED)
        self.frame.update()

    def _pick_file(self, var):
        initial = self.preview_dir_var.get().strip()
        if not initial or not Path(initial).exists():
            initial = str(CONFIG.WORKSPACE_DIR.absolute())
        p = filedialog.askopenfilename(initialdir=initial, filetypes=[("XML", "*.xml")])
        if p:
            var.set(p)

    def _run_cvat_export(self):
        work_dir = Path(self.preview_dir_var.get().strip())
        meta_path = work_dir / "metadata.json"
        out_xml, out_zip = work_dir / "annotations.xml", work_dir / f"{work_dir.name}_CVAT.zip"

        self._set_console_text(self.export_console, "⌛ Eksportowanie do CVAT w toku...")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if self.smart_export_var.get():
                filtered = {k: v for k, v in metadata.items() if v.get("status") != "perfect"}
                tmp_meta = work_dir / "temp_meta.json"
                with open(tmp_meta, 'w', encoding='utf-8') as f:
                    json.dump(filtered, f, indent=2, ensure_ascii=False)
                source_meta = tmp_meta
            else:
                source_meta = meta_path

            from ..cvat_tools.cvat_character_exporter import CVATCharacterExporter
            from ..cvat_tools.cvat_zip_manager import CVATZipManager

            if CVATCharacterExporter().export(source_meta, out_xml):
                CVATZipManager.create_cvat_import_zip(out_xml, work_dir / "images", out_zip)
                self._set_console_text(self.export_console, f"✅ Wygenerowano ZIP:\n{out_zip}")

            if self.smart_export_var.get() and source_meta.exists():
                source_meta.unlink()

        except Exception as e:
            self._set_console_text(self.export_console, f"❌ BŁĄD EKSPORTU CVAT:\n{e}")

    def _run_yolo_gold_export(self):
        self._set_console_text(self.export_console, "⌛ Zbieranie idealnych tablic...")

        base_chars_dir = Path(getattr(self, "_campaign_chars_dir", str(CONFIG.DIR_3_CHARS)))

        import datetime, uuid, shutil
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        base_datasets_dir = Path(getattr(self, "_campaign_datasets_dir", str(CONFIG.DIR_4_DATASETS)))
        yolo_out = base_datasets_dir / f"YOLO_MegaDataset_Chars_{timestamp}"
        img_out, lbl_out = yolo_out / "images", yolo_out / "labels"

        try:
            img_out.mkdir(parents=True, exist_ok=True)
            lbl_out.mkdir(parents=True, exist_ok=True)

            char_map = {c: i for i, c in enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
            copied, seen = 0, set()

            for run_dir in base_chars_dir.iterdir():
                meta = run_dir / "metadata.json"
                if not meta.exists():
                    continue
                with open(meta, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                for pid, data in {k: v for k, v in metadata.items() if v.get("status") == "perfect"}.items():
                    uk = f"{data.get('source_image', 'u')}_{int(data.get('source_bbox', [0])[0]//10) if data.get('source_bbox') else 0}"
                    if uk in seen:
                        continue
                    seen.add(uk)

                    img_src = run_dir / "images" / f"{pid}.jpg"
                    if not img_src.exists():
                        continue

                    img = cv2.imread(str(img_src))
                    if img is None:
                        continue

                    ih, iw = img.shape[:2]
                    new_pid = f"mega_{uuid.uuid4().hex[:8]}_{pid}"
                    shutil.copy2(img_src, img_out / f"{new_pid}.jpg")

                    txt = []
                    for c in data.get("characters", []):
                        ch = str(c.get("character", "")).upper()
                        if ch not in char_map:
                            continue
                        x1, y1, x2, y2 = c.get("bbox", [0, 0, 0, 0])
                        xc = max(0.0, min(1.0, ((x1 + x2) / 2.0) / iw))
                        yc = max(0.0, min(1.0, ((y1 + y2) / 2.0) / ih))
                        w = max(0.0, min(1.0, (x2 - x1) / iw))
                        h = max(0.0, min(1.0, (y2 - y1) / ih))
                        txt.append(f"{char_map[ch]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")

                    (lbl_out / f"{new_pid}.txt").write_text("\n".join(txt), encoding="utf-8")
                    copied += 1

            if copied == 0:
                msg = (
                    "❌ NIE UDAŁO SIĘ UTWORZYĆ DATASETU YOLO.\n\n"
                    "Powód: w bieżącym projekcie nie znaleziono ani jednej tablicy ze statusem 🟢 perfect.\n\n"
                    "CO DALEJ:\n"
                    "1. Wróć do Autoanotacji i spróbuj ponownie na innych ustawieniach/modelu.\n"
                    "2. Albo pozostań w Zakładce Znaków i popraw OCR / Laboratorium.\n"
                    "3. Trening pozostaje zablokowany do czasu zbudowania poprawnej paczki YOLO."
                )
                self._set_console_text(self.export_console, msg)

                try:
                    from ..campaign_manager import CAMPAIGN
                    if CAMPAIGN.get_active_project_name():
                        CAMPAIGN.set_current_step(3)
                        CAMPAIGN.set_step3_needs_rework()

                        if 'campaign' in self.app.tabs:
                            self.app.tabs['campaign']._refresh_dashboard()

                    self.app.update_status(
                        "Krok 3 wymaga poprawy. Wracasz do Rozkładu Jazdy, aby wybrać ścieżkę naprawczą.",
                        "warning"
                    )

                    # ✅ ZMIANA: automatyczny powrót do Wizarda
                    self.app.notebook.select(0)

                except Exception:
                    pass

                return

            yaml_content = f"path: {yolo_out.absolute().as_posix()}\ntrain: images\nval: images\nnc: 36\nnames:\n"
            for char, class_id in char_map.items():
                yaml_content += f"  {class_id}: '{char}'\n"
            (yolo_out / "data.yaml").write_text(yaml_content, encoding="utf-8")

            self._set_console_text(self.export_console, f"✅ Dataset YOLO gotowy: {yolo_out}")

            try:
                from ..campaign_manager import CAMPAIGN
                if CAMPAIGN.get_active_project_name() and CAMPAIGN.get_current_step() == 3:
                    CAMPAIGN.approve_step3()
                    CAMPAIGN.set_current_step(4)

                    if 'campaign' in self.app.tabs:
                        self.app.tabs['campaign']._refresh_dashboard()

                    # ✅ ZMIANA: po sukcesie też wracamy do Wizarda
                    self.app.update_status(
                        "Paczka YOLO została utworzona poprawnie. Odblokowano Krok 4 (Trening).",
                        "info"
                    )
                    self.app.notebook.select(0)

            except Exception:
                pass
        except Exception as e:
            self._set_console_text(self.export_console, f"❌ BŁĄD EKSPORTU YOLO:\n{e}")

    def _run_cvat_import(self):
        xml_in = Path(self.import_cvat_xml_var.get().strip())
        meta_path = Path(self.preview_dir_var.get().strip()) / "metadata.json"

        if not xml_in.exists():
            self._set_console_text(self.import_console, "❌ BŁĄD: Wybrany plik XML nie istnieje.")
            return

        self._set_console_text(self.import_console, "⌛ Wczytywanie danych z XML...")

        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            root = ET.parse(xml_in).getroot()
            updated = 0

            for image in root.findall('.//image'):
                pid = Path(image.get('name', '')).stem
                if pid not in metadata:
                    continue

                new_chars = []
                for box in image.findall('box'):
                    if box.get('label', '').lower() in ['character', 'char']:
                        t = next((a.text for a in box.findall('attribute') if a.get('name') == 'text'), "?")
                        new_chars.append({
                            "character": t,
                            "bbox": [
                                float(box.get('xtl', 0)),
                                float(box.get('ytl', 0)),
                                float(box.get('xbr', 0)),
                                float(box.get('ybr', 0))
                            ],
                            "confidence": 1.0,
                            "method": "cvat_manual"
                        })

                metadata[pid]["characters"] = new_chars
                metadata[pid]["status"] = "perfect"
                updated += 1

            self._atomic_write_json(meta_path, metadata)
            self._reset_preview_cache()
            self._load_preview_data(quiet=True)

            self._set_console_text(self.import_console, f"✅ Zaktualizowano: {updated} tablic.")

        except Exception as e:
            self._set_console_text(self.import_console, f"❌ BŁĄD IMPORTU:\n{e}")

    # =========================================================
    # Preset ranking (left as-is)
    # =========================================================

    def _run_preset_ranking(self):
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj paczkę danych do testu!")

        preset_files = list(self.presets_dir.glob("*.json"))
        preset_files = [f for f in preset_files if f.name != "global_ranking.json"]
        if not preset_files:
            return messagebox.showinfo("Brak presetów", "Brak presetów! Otwórz Laboratorium i zapisz filtry jako JSON.")

        self.test_log_text.delete(1.0, tk.END)
        self._lock_ui_for_testing()
        self._log(self.test_log_text, "=======================================================", "HEADER")
        self._log(self.test_log_text, "ROZPOCZYNAM TURNIEJ PRESETÓW", "HEADER")

        out_dir = Path(self.preview_dir_var.get().strip())
        imgs_dir = out_dir / "images"
        cache_file = self.presets_dir / "global_ranking.json"

        def worker():
            try:
                ranking_cache = {}
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r', encoding='utf-8') as f:
                            ranking_cache = json.load(f)
                    except Exception:
                        pass

                ocr_engine = PlateOCR(device='cuda' if self.yolo_device_var.get().startswith("cuda") else 'cpu')
                detector = CharacterDetector(method=DetectionMethod.OCR, ocr_engine=ocr_engine)

                results_table = []
                total_imgs = len(self.preview_plate_ids)
                total_presets = len(preset_files)

                for p_idx, p_file in enumerate(preset_files):
                    preset_name = p_file.stem
                    try:
                        with open(p_file, 'r', encoding='utf-8') as f:
                            preset_params = json.load(f)
                    except Exception:
                        continue

                    clean_params = {k: v for k, v in preset_params.items() if not k.startswith("char_do_") and k != "char_ocr_conf"}
                    param_signature = str(sorted(clean_params.items()))

                    if preset_name in ranking_cache and ranking_cache[preset_name].get("signature") == param_signature:
                        results_table.append((ranking_cache[preset_name]["acc"], ranking_cache[preset_name]["matches"], preset_name, True))
                        self.frame.after(0, lambda p=((p_idx + 1) / total_presets) * 100: self.test_progress.config(value=p))
                        continue

                    ocr_engine.custom_prep_params = clean_params
                    if "char_ocr_conf" in preset_params:
                        ocr_engine.confidence_threshold = float(preset_params.get("char_ocr_conf", 0.25))

                    perfect_matches = 0
                    for pid in self.preview_plate_ids:
                        img_path = imgs_dir / f"{pid}.jpg"
                        if not img_path.exists():
                            continue
                        plate_img = cv2.imread(str(img_path))
                        if plate_img is None:
                            continue

                        expected = self._get_true_texts_from_filename(self.preview_metadata.get(pid, {}).get("source_image", ""))
                        chars = detector.detect(plate_img)
                        if "".join([str(c.character) for c in chars]) in expected:
                            perfect_matches += 1

                    acc = (perfect_matches / total_imgs) * 100 if total_imgs > 0 else 0
                    ranking_cache[preset_name] = {
                        "name": preset_name,
                        "acc": acc,
                        "matches": perfect_matches,
                        "signature": param_signature,
                        "params": preset_params
                    }
                    results_table.append((acc, perfect_matches, preset_name, False))
                    self.frame.after(0, lambda p=((p_idx + 1) / total_presets) * 100: self.test_progress.config(value=p))

                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(ranking_cache, f, indent=4, ensure_ascii=False)

                results_table.sort(key=lambda x: x[0], reverse=True)

                self._log(self.test_log_text, "=" * 55, "HEADER")
                for i, (acc, matches, name, from_cache) in enumerate(results_table):
                    self._log(self.test_log_text, f"#{i+1}. {name.ljust(22)} | {acc:5.1f}%  ({matches}/{total_imgs})", "SUCCESS" if i == 0 else "INFO")

                self.frame.after(0, self._update_winner_label)

            except Exception as e:
                self._log(self.test_log_text, f"\n❌ BŁĄD RANKINGU: {e}", "ERROR")
            finally:
                self.frame.after(0, self._unlock_ui_after_testing)
                self.frame.after(0, lambda: self.test_progress.config(value=100))
                self.frame.after(0, lambda: self.test_status_lbl.config(text="Turniej Zakończony!", foreground="#2ecc71"))

        threading.Thread(target=worker, daemon=True).start()

    def _open_filter_lab(self):
        out_dir = Path(self.preview_dir_var.get().strip())
        if not self.preview_plate_ids:
            return messagebox.showinfo("Brak", "Wczytaj najpierw listę tablic.")

        imgs_dir = out_dir / "images"

        def roll_images():
            import random
            s = min(3, len(self.preview_plate_ids))
            ids = random.sample(self.preview_plate_ids, s)
            res = []
            for pid in ids:
                i = cv2.imread(str(imgs_dir / f"{pid}.jpg"))
                if i is not None:
                    res.append((pid, i))
            return res

        self.lab_current_images = roll_images()
        if not self.lab_current_images:
            return

        best_preset_data, best_acc = self._get_best_preset()

        lab_win = tk.Toplevel(self.frame)
        lab_win.title("Laboratorium Filtrów OCR")
        lab_win.geometry("1100x850")

        bottom_bar = ttk.Frame(lab_win, padding=10, relief="raised")
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # ✅ Pasek pomocy dla okna Laboratorium
        lab_help_text = tk.Text(
            bottom_bar, height=2, wrap=tk.WORD,
            bg="#f0f0f0", bd=0, font=("Segoe UI", 10, "italic"), fg="#2980b9"
        )
        lab_help_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        lab_help_text.insert(tk.END, "💡 Najedź myszką na nazwę suwaka, aby zobaczyć podpowiedź...")
        lab_help_text.config(state=tk.DISABLED)

        def update_lab_help(msg):
            if lab_win.winfo_exists():
                lab_help_text.config(state=tk.NORMAL)
                lab_help_text.delete(1.0, tk.END)
                lab_help_text.insert(tk.END, msg)
                lab_help_text.config(state=tk.DISABLED)

        self.old_status_updater = HELP.status_updater
        HELP.status_updater = update_lab_help

        main_content = ttk.Frame(lab_win)
        main_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left_container = ttk.Frame(main_content, width=350)
        left_container.pack(side=tk.LEFT, fill=tk.Y)
        left_container.pack_propagate(False)

        canvas_sliders = tk.Canvas(left_container, highlightthickness=0)
        scroll_sliders = ttk.Scrollbar(left_container, orient="vertical", command=canvas_sliders.yview)
        scrollable_frame = ttk.Frame(canvas_sliders, padding=10)

        frame_id = canvas_sliders.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas_sliders.bind("<Configure>", lambda e: canvas_sliders.itemconfig(frame_id, width=e.width))
        scrollable_frame.bind("<Configure>", lambda e: canvas_sliders.configure(scrollregion=canvas_sliders.bbox("all")))
        canvas_sliders.configure(yscrollcommand=scroll_sliders.set)

        scroll_sliders.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_sliders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right_view_container = ttk.Frame(main_content, padding=10)
        right_view_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        view_canvas = tk.Canvas(right_view_container, bg="#2c3e50", highlightthickness=0)
        view_scroll_v = ttk.Scrollbar(right_view_container, orient=tk.VERTICAL, command=view_canvas.yview)
        view_scroll_h = ttk.Scrollbar(right_view_container, orient=tk.HORIZONTAL, command=view_canvas.xview)

        view_scroll_h.pack(side=tk.BOTTOM, fill=tk.X)
        view_scroll_v.pack(side=tk.RIGHT, fill=tk.Y)
        view_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        view_canvas.configure(yscrollcommand=view_scroll_v.set, xscrollcommand=view_scroll_h.set)

        view_frame = ttk.Frame(view_canvas, style="Card.TFrame")
        view_canvas.create_window((0, 0), window=view_frame, anchor="nw")
        view_frame.bind("<Configure>", lambda e: view_canvas.configure(scrollregion=view_canvas.bbox("all")))

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
            o_lbl = tk.Label(of_frame, bg="#2c3e50", bd=2, relief="sunken")
            o_lbl.pack(anchor=tk.NW)

            pf_frame = ttk.Frame(c)
            pf_frame.pack(side=tk.LEFT, padx=20, fill=tk.BOTH)
            p_lbl = tk.Label(pf_frame, bg="black", bd=2, relief="solid")
            p_lbl.pack(anchor=tk.NW)

            self.lab_image_labels.append({
                "lbl": lbl,
                "orig": o_lbl,
                "proc": p_lbl
            })

        self.lab_photo_refs = []
        active_traces = []

        def update_preview(*args):
            if not lab_win.winfo_exists():
                return
            try:
                th = self.prep_height_var.get()
                ma = self.prep_angle_var.get()
                ct = self.prep_clip_var.get()
                dh = self.prep_denoise_var.get()
                cc = self.prep_clahe_var.get()
                use_bin = self.prep_use_bin_var.get()
                tb = self.prep_block_var.get()
                t_c = self.prep_c_var.get()
                if tb % 2 == 0:
                    tb += 1
                ei = self.prep_erode_var.get()

                interp_str = self.interpolation_var.get()
                interp_map = {
                    "nearest": cv2.INTER_NEAREST,
                    "linear": cv2.INTER_LINEAR,
                    "cubic": cv2.INTER_CUBIC,
                    "lanczos4": cv2.INTER_LANCZOS4
                }
                cv2_interp = interp_map.get(interp_str.lower(), cv2.INTER_LANCZOS4)

                self.lab_photo_refs.clear()

                for idx, (pid, orig_img) in enumerate(self.lab_current_images):
                    if idx >= len(self.lab_image_labels):
                        break

                    if abs(ma) > 0.1:
                        h, w = orig_img.shape[:2]
                        M = cv2.getRotationMatrix2D((w // 2, h // 2), ma, 1.0)
                        rotated = cv2.warpAffine(
                            orig_img, M, (w, h),
                            flags=cv2_interp,
                            borderMode=cv2.BORDER_REPLICATE
                        )
                    else:
                        rotated = orig_img.copy()

                    gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY) if len(rotated.shape) == 3 else rotated.copy()
                    h_g, w_g = gray.shape
                    scale = float(th) / h_g if h_g > 0 else 1.0
                    gray_scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2_interp)

                    po = ImageTk.PhotoImage(Image.fromarray(gray_scaled))

                    if ct < 255:
                        gray_scaled[gray_scaled > ct] = 255

                    den = cv2.fastNlMeansDenoising(
                        gray_scaled, None,
                        h=dh, templateWindowSize=7, searchWindowSize=21
                    ) if dh > 0 else gray_scaled

                    if self.do_clahe_var.get() and cc > 0:
                        clahe = cv2.createCLAHE(clipLimit=cc, tileGridSize=(8, 8))
                        contrasted = clahe.apply(den)
                    else:
                        contrasted = den

                    blurred = cv2.GaussianBlur(contrasted, (3, 3), 0)

                    if use_bin:
                        binary = cv2.adaptiveThreshold(
                            blurred, 255,
                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                            cv2.THRESH_BINARY,
                            blockSize=max(3, tb),
                            C=t_c
                        )
                        if ei > 0:
                            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                            final = cv2.erode(binary, kernel, iterations=ei)
                        else:
                            final = binary
                    else:
                        final = contrasted

                    pad_pct = self.prep_padding_var.get()
                    if pad_pct > 0:
                        py = int(final.shape[0] * (pad_pct / 100.0))
                        px = int(final.shape[1] * (pad_pct / 100.0))
                        final = cv2.copyMakeBorder(final, py, py, px, px, cv2.BORDER_CONSTANT, value=255)

                    pp = ImageTk.PhotoImage(Image.fromarray(final))
                    self.lab_photo_refs.extend([po, pp])

                    ui_row = self.lab_image_labels[idx]
                    ui_row["lbl"].config(text=f"ID: {pid}")
                    ui_row["orig"].config(image=po)
                    ui_row["proc"].config(image=pp)

            except Exception:
                pass

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
                    ttk.Label(
                        lbl_f,
                        text=f"[Zwycięzca: {ghost_str}]",
                        foreground="#2980b9",
                        font=("Segoe UI", 9, "bold italic")
                    ).pack(side=tk.RIGHT)

            s = ttk.Scale(f, from_=from_, to=to_, variable=var, command=update_preview)
            s.pack(side=tk.LEFT, fill=tk.X, expand=True)

            l = ttk.Label(f, width=5)
            l.pack(side=tk.RIGHT)

            def update_lbl(*a):
                if lab_win.winfo_exists():
                    l.config(text=f"{var.get():.{res}f}")

            trace_id = var.trace_add("write", update_lbl)
            active_traces.append((var, trace_id))
            update_lbl()

            if help_key:
                HELP.bind_help(main_label, help_key)
                HELP.bind_help(s, help_key)

        if best_preset_data and best_preset_data.get("name"):
            leader_f = tk.Frame(scrollable_frame, bg="#fff3cd", bd=1, relief="solid")
            leader_f.pack(fill=tk.X, pady=(0, 15))
            tk.Label(
                leader_f,
                text=f"Lider: {best_preset_data.get('name').upper()}",
                bg="#fff3cd", fg="#8a6d3b",
                font=("Arial", 10, "bold")
            ).pack(pady=(5, 0))
            tk.Label(
                leader_f,
                text=f"Skuteczność: {best_acc:.1f}%",
                bg="#fff3cd", fg="#8a6d3b",
                font=("Arial", 9)
            ).pack(pady=(0, 5))
        else:
            ttk.Label(scrollable_frame, text="Dostrojenie Algorytmu", font=("Arial", 12, "bold")).pack(pady=(0, 10))

        geom = ttk.LabelFrame(scrollable_frame, text=" 1. Geometria ", padding=10)
        geom.pack(fill=tk.X, pady=(0, 10))

        angle_row = ttk.Frame(geom)
        angle_row.pack(fill=tk.X)
        add_slider(angle_row, "Ręczna korekta kąta [°]:", self.prep_angle_var, -30, 30, 1, "manual_angle", "lab_angle")
        ttk.Button(geom, text="Reset Kąta", command=lambda: (self.prep_angle_var.set(0.0), update_preview())).pack(anchor=tk.E, pady=(0, 5))

        add_slider(geom, "Wysokość OCR (px):", self.prep_height_var, 40, 150, 0, "target_height", "lab_height")

        filt = ttk.LabelFrame(scrollable_frame, text=" 2. Filtry bazowe ", padding=10)
        filt.pack(fill=tk.X, pady=(0, 10))
        add_slider(filt, "Odcięcie odblasków (255=Wył):", self.prep_clip_var, 100, 255, 0, "clip_thresh", "lab_clip")
        add_slider(filt, "Usuwanie ziarna (0=Wył):", self.prep_denoise_var, 0, 50, 0, "denoise_h", "lab_denoise")
        cb2 = ttk.Checkbutton(filt, text="Wzmacniaj kontrast (CLAHE)", variable=self.do_clahe_var, command=update_preview)
        cb2.pack(anchor=tk.W)
        HELP.bind_help(cb2, "lab_clahe")
        add_slider(filt, "Siła CLAHE:", self.prep_clahe_var, 0.0, 10.0, 1, "clahe_clip", "lab_clahe")

        bina = ttk.LabelFrame(scrollable_frame, text=" 3. Binaryzacja ", padding=10)
        bina.pack(fill=tk.X, pady=(0, 10))
        ttk.Checkbutton(bina, text="Włącz pełną binaryzację", variable=self.prep_use_bin_var, command=update_preview).pack(anchor=tk.W)
        add_slider(bina, "Rozmiar bloku (nieparzyste):", self.prep_block_var, 3, 51, 0, "thresh_block", "lab_block")
        add_slider(bina, "Stała odcięcia (C):", self.prep_c_var, -20, 20, 0, "thresh_c", "lab_c")
        add_slider(bina, "Pogrubianie liter (Erozja):", self.prep_erode_var, 0, 5, 0, "erode_iter", "lab_erode")
        add_slider(bina, "Biała ramka - Padding [%]:", self.prep_padding_var, 0, 50, 0, "padding_pct", "lab_pad")

        ocr_f = ttk.LabelFrame(scrollable_frame, text=" 4. Parametry Sieci (OCR) ", padding=10)
        ocr_f.pack(fill=tk.X, pady=(0, 10))
        add_slider(ocr_f, "Wymagany próg pewności (0-1.0):", self.ocr_conf_var, 0.05, 0.95, 2, "char_ocr_conf", "lab_conf")

        def load_preset():
            p = filedialog.askopenfilename(initialdir=self.presets_dir, filetypes=[("JSON", "*.json")], parent=lab_win)
            if p:
                try:
                    with open(p, 'r') as f: data = json.load(f)
                    if "target_height" in data: self.prep_height_var.set(data["target_height"])
                    if "clip_thresh" in data: self.prep_clip_var.set(data["clip_thresh"])
                    if "thresh_block" in data: self.prep_block_var.set(data["thresh_block"])
                    if "thresh_c" in data: self.prep_c_var.set(data["thresh_c"])
                    if "erode_iter" in data: self.prep_erode_var.set(data["erode_iter"])
                    if "padding_pct" in data: self.prep_padding_var.set(data["padding_pct"])
                    if "char_ocr_conf" in data: self.ocr_conf_var.set(data["char_ocr_conf"])
                    update_preview()
                except: pass

        def save_preset():
            name = simpledialog.askstring("Preset", "Podaj nazwę dla presetu:", parent=lab_win)
            if name:
                p = self.presets_dir / f"{name}.json"
                data = self._get_current_prep_params()
                data["char_ocr_conf"] = self.ocr_conf_var.get()
                with open(p, 'w') as f: json.dump(data, f, indent=4)

        def safe_close():
            for var, tid in active_traces:
                try: var.trace_remove("write", tid)
                except: pass
            self._force_save_all()
            self.lab_photoRefs = []
            HELP.status_updater = self.old_status_updater
            lab_win.destroy()

        lab_win.protocol("WM_DELETE_WINDOW", safe_close)
        ttk.Button(bottom_bar, text="Zapisz Preset", command=save_preset).pack(side=tk.RIGHT)
        ttk.Button(bottom_bar, text="Wczytaj Preset", command=load_preset).pack(side=tk.RIGHT)
        ttk.Button(bottom_bar, text="ZAMKNIJ", command=safe_close, style="Accent.TButton").pack(side=tk.RIGHT, padx=15)

        btn_roll = ttk.Button(
            bottom_bar,
            text="🎲 Losuj inną próbkę",
            command=lambda: (setattr(self, 'lab_current_images', roll_images()), update_preview())
        )
        btn_roll.pack(side=tk.RIGHT, padx=15)

        update_preview()