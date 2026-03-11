#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Prostowanie tablic (warpPerspective) z precyzyjnymi liniami podglądu.
"""

from __future__ import annotations
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..config import CONFIG, CV2_AVAILABLE, cv2, PIL_AVAILABLE, np
from ..icons import IconManager
from ..rectification import PlateRectifier

if PIL_AVAILABLE:
    from PIL import Image, ImageTk


class ScrollableFrame(ttk.Frame):
    """Pomocnicza klasa dla scrollowanego panelu bocznego."""
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")
        
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class RectificationTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon = IconManager
        self.frame = ttk.Frame(parent)

        # Zmienne ścieżek
        self.images_dir = tk.StringVar()
        self.xml_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path(CONFIG.DEFAULT_OUTPUT_DIR) / "rectified_plates"))

        # Zmienne parametrów (bezpieczne)
        self.px_per_mm = tk.DoubleVar(value=2.0)
        self.plate_w_mm = tk.DoubleVar(value=520.0)
        self.plate_h_mm = tk.DoubleVar(value=110.0)
        self.auto_aspect = tk.BooleanVar(value=True)
        self.interp = tk.StringVar(value="lanczos4")
        self.two_stage = tk.BooleanVar(value=True)
        self.oversample = tk.DoubleVar(value=2.0)
        self.sharpen_var = tk.DoubleVar(value=0.0)
        self.contrast_var = tk.BooleanVar(value=False)
        self.deskew_var = tk.BooleanVar(value=False)
        self.manual_angle_var = tk.DoubleVar(value=0.0)

        # Dane i stan
        self.ann: Dict[str, List[List[Tuple[float, float]]]] = {}
        self.current_img_bgr = None
        self.current_img_name: Optional[str] = None
        self.current_plate_index = tk.IntVar(value=0)
        self._last_rectified_bgr = None

        self._build_ui()

    def _get_safe_int(self, var: tk.IntVar, default: int = 0) -> int:
        try: return var.get()
        except: return default

    def _get_safe_float(self, var: tk.DoubleVar, default: float = 0.0) -> float:
        try: return var.get()
        except: return default

    def _build_ui(self):
        pane = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_outer = ttk.Frame(pane)
        pane.add(left_outer, weight=0)
        left_scroll = ScrollableFrame(left_outer)
        left_scroll.pack(fill=tk.BOTH, expand=True)
        left = ttk.LabelFrame(left_scroll.inner, text="Parametry rektyfikacji", padding=10)
        left.pack(fill=tk.BOTH, expand=True)

        right = ttk.LabelFrame(pane, text="Podgląd", padding=10)
        pane.add(right, weight=1)

        # --- SEKCJA PLIKÓW ---
        ttk.Label(left, text="Folder obrazów:").pack(anchor=tk.W)
        r1 = ttk.Frame(left); r1.pack(fill=tk.X, pady=2)
        ttk.Entry(r1, textvariable=self.images_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(r1, text="Wybierz", command=self._pick_images_dir).pack(side=tk.LEFT, padx=5)

        ttk.Label(left, text="CVAT XML:").pack(anchor=tk.W, pady=(5,0))
        r2 = ttk.Frame(left); r2.pack(fill=tk.X, pady=2)
        ttk.Entry(r2, textvariable=self.xml_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(r2, text="Wybierz", command=self._pick_xml).pack(side=tk.LEFT, padx=5)
        ttk.Button(left, text="Wczytaj anotacje", command=self._load_annotations).pack(fill=tk.X, pady=5)

        self.listbox = tk.Listbox(left, height=6)
        self.listbox.pack(fill=tk.X, pady=5)
        self.listbox.bind("<<ListboxSelect>>", self._on_select_image)

        idx_row = ttk.Frame(left); idx_row.pack(fill=tk.X, pady=5)
        ttk.Label(idx_row, text="Index tablicy:").pack(side=tk.LEFT)
        ttk.Spinbox(idx_row, from_=0, to=99, textvariable=self.current_plate_index, width=5, command=self._update_preview).pack(side=tk.LEFT, padx=5)
        ttk.Button(idx_row, text="Podgląd", command=self._update_preview).pack(side=tk.RIGHT)

        # --- SEKCJA ROZMIARU I SKALI ---
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        ttk.Label(left, text="Skala (Px/mm):").pack(anchor=tk.W)
        
        row_pxmm = ttk.Frame(left); row_pxmm.pack(fill=tk.X, pady=2)
        ttk.Scale(row_pxmm, from_=0.5, to=10.0, variable=self.px_per_mm, orient=tk.HORIZONTAL, 
                  command=lambda e: self._update_preview()).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent_pxmm = ttk.Entry(row_pxmm, textvariable=self.px_per_mm, width=6)
        ent_pxmm.pack(side=tk.RIGHT, padx=5)
        ent_pxmm.bind("<Return>", lambda e: self._update_preview())
        
        dim = ttk.Frame(left); dim.pack(fill=tk.X, pady=5)
        ttk.Label(dim, text="Rozmiar mm:").pack(side=tk.LEFT)
        ttk.Entry(dim, textvariable=self.plate_w_mm, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(dim, text="x").pack(side=tk.LEFT)
        ttk.Entry(dim, textvariable=self.plate_h_mm, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(left, text="Auto proporcje", variable=self.auto_aspect, command=self._update_preview).pack(anchor=tk.W)

        # --- SEKCJA JAKOŚCI ---
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        ttk.Label(left, text="Interpolacja:").pack(anchor=tk.W)
        cb = ttk.Combobox(left, textvariable=self.interp, values=["nearest", "linear", "cubic", "lanczos4"], state="readonly")
        cb.pack(fill=tk.X, pady=2); cb.bind("<<ComboboxSelected>>", lambda e: self._update_preview())
        
        ttk.Label(left, text="Wyostrzanie (Sharpen):").pack(anchor=tk.W, pady=(5,0))
        row_sharp = ttk.Frame(left); row_sharp.pack(fill=tk.X, pady=2)
        ttk.Scale(row_sharp, from_=0.0, to=2.0, variable=self.sharpen_var, orient=tk.HORIZONTAL, 
                  command=lambda e: self._update_preview()).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent_sharp = ttk.Entry(row_sharp, textvariable=self.sharpen_var, width=6)
        ent_sharp.pack(side=tk.RIGHT, padx=5)
        ent_sharp.bind("<Return>", lambda e: self._update_preview())
        
        ttk.Checkbutton(left, text="Prostuj znaki (Auto Deskew)", variable=self.deskew_var, command=self._update_preview).pack(anchor=tk.W)
        
        ttk.Label(left, text="Korekta kąta:").pack(anchor=tk.W, pady=(5,0))
        ang_r = ttk.Frame(left); ang_r.pack(fill=tk.X)
        ttk.Scale(ang_r, from_=-15.0, to=15.0, variable=self.manual_angle_var, orient=tk.HORIZONTAL, 
                  command=lambda e: self._update_preview()).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent_ang = ttk.Entry(ang_r, textvariable=self.manual_angle_var, width=6)
        ent_ang.pack(side=tk.LEFT, padx=5)
        ent_ang.bind("<Return>", lambda e: self._update_preview())
        ttk.Button(ang_r, text="0", width=3, command=lambda: [self.manual_angle_var.set(0.0), self._update_preview()]).pack(side=tk.RIGHT)

        ttk.Checkbutton(left, text="Kontrast CLAHE", variable=self.contrast_var, command=self._update_preview).pack(anchor=tk.W)

        # --- SEKCJA ZAPISU ---
        ttk.Separator(left).pack(fill=tk.X, pady=10)
        ttk.Label(left, text="Folder zapisu:").pack(anchor=tk.W)
        r_out = ttk.Frame(left); r_out.pack(fill=tk.X, pady=2)
        ttk.Entry(r_out, textvariable=self.output_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(r_out, text="Wybierz", command=self._pick_output_dir).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(left, text="Zapisz bieżącą", command=self._save_current).pack(fill=tk.X, pady=2)
        ttk.Button(left, text="Zapisz wszystkie", command=self._save_all_thread).pack(fill=tk.X, pady=2)

        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(left, variable=self.progress_var, maximum=100).pack(fill=tk.X, pady=5)
        self.status = ttk.Label(left, text="Gotowy", wraplength=250); self.status.pack(anchor=tk.W)

        # Panele podglądu
        vpane = ttk.PanedWindow(right, orient=tk.VERTICAL)
        vpane.pack(fill=tk.BOTH, expand=True)
        self.lbl_left = ttk.Label(vpane, text="Oryginał", anchor="center")
        self.lbl_right = ttk.Label(vpane, text="Wynik", anchor="center")
        vpane.add(self.lbl_left, weight=1)
        vpane.add(self.lbl_right, weight=1)

    def _update_preview(self):
        if self.current_img_bgr is None or self.current_img_name not in self.ann: return
        plates = self.ann[self.current_img_name]
        idx = self._get_safe_int(self.current_plate_index, 0)
        if idx >= len(plates): return

        pts = plates[idx]
        try:
            w_px, h_px = PlateRectifier.polygon_wh_px(pts)
            h_mm = self._get_safe_float(self.plate_h_mm, 110.0)
            w_mm = h_mm * (w_px/h_px) if self.auto_aspect.get() and h_px > 0 else self._get_safe_float(self.plate_w_mm, 520.0)
            
            ppm = self._get_safe_float(self.px_per_mm, 2.0)
            out_w, out_h = max(1, int(w_mm * ppm)), max(1, int(h_mm * ppm))

            rect = PlateRectifier.rectify(
                self.current_img_bgr, pts, out_w, out_h,
                interpolation=self.interp.get(),
                sharpen=self._get_safe_float(self.sharpen_var, 0.0),
                enhance_contrast=self.contrast_var.get(),
                do_deskew=self.deskew_var.get(),
                manual_angle=self._get_safe_float(self.manual_angle_var, 0.0)
            )
            self._last_rectified_bgr = rect

            if PIL_AVAILABLE:
                # Lewo: Cienka linia 1px + punkty w rogach
                tmp_vis = self.current_img_bgr.copy()
                pts_arr = np.array(pts, np.int32)
                cv2.polylines(tmp_vis, [pts_arr], True, (0, 255, 0), 1)
                for pt in pts:
                    cv2.circle(tmp_vis, (int(pt[0]), int(pt[1])), 3, (0, 0, 255), -1)
                
                img_l = Image.fromarray(cv2.cvtColor(tmp_vis, cv2.COLOR_BGR2RGB))
                img_l.thumbnail((800, 400)); self._p1 = ImageTk.PhotoImage(img_l)
                self.lbl_left.config(image=self._p1, text="")
                
                # Prawo
                img_r = Image.fromarray(cv2.cvtColor(rect, cv2.COLOR_BGR2RGB))
                img_r.thumbnail((800, 400)); self._p2 = ImageTk.PhotoImage(img_r)
                self.lbl_right.config(image=self._p2, text="")
        except Exception as e: self.status.config(text=f"Aktualizacja...")

    def _pick_images_dir(self):
        p = filedialog.askdirectory(); 
        if p: self.images_dir.set(p)

    def _pick_xml(self):
        p = filedialog.askopenfilename(filetypes=[("XML", "*.xml")]); 
        if p: self.xml_path.set(p)

    def _pick_output_dir(self):
        p = filedialog.askdirectory(); 
        if p: self.output_dir.set(p)

    def _load_annotations(self):
        xml_path_str = self.xml_path.get().strip()
        if not xml_path_str: return
        xml = Path(xml_path_str)
        if not xml.exists(): 
            messagebox.showerror("Błąd", "Plik XML nie istnieje.")
            return
            
        try:
            tree = ET.parse(xml)
            root = tree.getroot()
            ann = {}
            
            # Słownik etykiet, które uznajemy za tablice
            valid_labels = set(CONFIG.PLATE_LABELS) 
            valid_labels.update(['plate', 'license-plate', 'rejestracja', 'tablica', 'lp'])

            for image in root.findall(".//image"):
                name = image.get("name", "")
                plates = []
                
                # Szukaj poligonów
                for poly in image.findall("polygon"):
                    label = (poly.get("label") or "").lower().strip()
                    if label in valid_labels:
                        # Oczyszczanie punktów (usuwanie spacji, nowych linii)
                        pts_raw = poly.get("points", "").replace('\n', '').replace(' ', '')
                        pts = [tuple(map(float, p.split(","))) for p in pts_raw.split(";") if "," in p]
                        if len(pts) >= 4:
                            plates.append(pts[:4])
                
                # Opcjonalnie szukaj boxów, jeśli nie ma poligonów (traktuj je jako 4 punkty)
                if not plates:
                    for box in image.findall("box"):
                        label = (box.get("label") or "").lower().strip()
                        if label in valid_labels:
                            xtl, ytl = float(box.get("xtl")), float(box.get("ytl"))
                            xbr, ybr = float(box.get("xbr")), float(box.get("ybr"))
                            # Zamień box na 4 punkty polygonu (zgodnie z ruchem wskazówek zegara)
                            plates.append([(xtl, ytl), (xbr, ytl), (xbr, ybr), (xtl, ybr)])

                if plates:
                    ann[name] = plates
            
            self.ann = ann
            self.listbox.delete(0, tk.END)
            for k in sorted(self.ann.keys()):
                self.listbox.insert(tk.END, f"{k} ({len(self.ann[k])})")
            
            self.status.config(text=f"Sukces! Wczytano {len(self.ann)} obrazów z tablicami.")
            if not self.ann:
                messagebox.showwarning("Uwaga", "W pliku XML nie znaleziono etykiet pasujących do tablic (plate, tablica itp.)")
                
        except Exception as e:
            messagebox.showerror("Błąd parsowania XML", f"Szczegóły: {e}")

    def _on_select_image(self, event=None):
        sel = self.listbox.curselection()
        if not sel: return
        img_name = self.listbox.get(sel[0]).split(" (")[0]
        img_path = Path(self.images_dir.get()) / img_name
        self.current_img_bgr = cv2.imread(str(img_path))
        self.current_img_name = img_name
        self.current_plate_index.set(0)
        self._update_preview()

    def _save_current(self):
        if self._last_rectified_bgr is None: return
        out_p = Path(self.output_dir.get()); out_p.mkdir(parents=True, exist_ok=True)
        name = f"{Path(self.current_img_name).stem}_p{self.current_plate_index.get()}.png"
        cv2.imwrite(str(out_p / name), self._last_rectified_bgr)
        self.status.config(text=f"Zapisano: {name}")

    def _save_all_thread(self):
        if not self.ann: return
        threading.Thread(target=self._save_all_worker, daemon=True).start()

    def _save_all_worker(self):
        out_p = Path(self.output_dir.get()); out_p.mkdir(parents=True, exist_ok=True)
        img_dir = Path(self.images_dir.get())
        items = list(self.ann.items()); total = len(items)
        ppm = self._get_safe_float(self.px_per_mm, 2.0)
        h_f = self._get_safe_float(self.plate_h_mm, 110.0)
        w_f = self._get_safe_float(self.plate_w_mm, 520.0)
        
        for i, (name, plates) in enumerate(items):
            img = cv2.imread(str(img_dir / name))
            if img is None: continue
            for p_idx, pts in enumerate(plates):
                w_px, h_px = PlateRectifier.polygon_wh_px(pts)
                w_mm = h_f * (w_px/h_px) if self.auto_aspect.get() and h_px > 0 else w_f
                rect = PlateRectifier.rectify(img, pts, max(1, int(w_mm*ppm)), max(1, int(h_f*ppm)),
                    interpolation=self.interp.get(), sharpen=self._get_safe_float(self.sharpen_var, 0.0),
                    enhance_contrast=self.contrast_var.get(), do_deskew=self.deskew_var.get(),
                    manual_angle=self._get_safe_float(self.manual_angle_var, 0.0))
                cv2.imwrite(str(out_p / f"{Path(name).stem}_p{p_idx}.png"), rect)
            self.frame.after(0, lambda p=((i+1)/total*100): self.progress_var.set(p))
        self.frame.after(0, lambda: messagebox.showinfo("Sukces", "Zapisano wszystko."))