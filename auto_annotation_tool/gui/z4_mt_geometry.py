"""Read-only MT geometry review inside the EVAL396 Z4 result window."""
from __future__ import annotations

import hashlib
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
from PIL import Image

from ..image_orientation import inspect_oriented_image
from ..ranking.eval396 import contained
from ..ranking.mt_geometry_review import (
    CORNER_NAMES, preflight_mt_geometry, save_operator_decision, load_operator_decision,
)
from .zoomable_canvas import ZoomableCanvas


class GeometryReviewPanel(ttk.Frame):
    def __init__(self, parent, selection_dir):
        super().__init__(parent, padding=12)
        self.selection_dir = Path(selection_dir)
        if self.selection_dir.name == "selection_manifest.json":
            self.selection_dir = self.selection_dir.parent
        self.output_root = self.selection_dir.parent.parent / "evaluation_runs"
        self.report = self.scene = self.decision = None
        self.reviewed = set()
        self.messages = queue.Queue()
        self.cancelled = threading.Event()
        self.busy = False
        self.epoch = 0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        ttk.Label(self, text="MT — lokalizacja i geometria", font=("Segoe UI", 15, "bold")).grid(row=0, sticky="w")
        self.status = tk.StringVar(value="WERYFIKACJA EXIF/GT WYMAGANA — rozpocznij kontrolę źródeł i geometrii.")
        ttk.Label(self, textvariable=self.status, wraplength=1040).grid(row=1, sticky="ew", pady=(5, 4))
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.grid(row=2, sticky="ew", pady=(0, 6))
        toolbar = ttk.Frame(self)
        toolbar.grid(row=3, sticky="ew")
        self.check_button = ttk.Button(toolbar, text="[ MT ] Sprawdź geometrię i EXIF", command=self.check)
        self.check_button.pack(side="left")
        self.preview_button = ttk.Button(toolbar, text="[ MT ] Otwórz podgląd GT", command=self.show_scene, state="disabled")
        self.preview_button.pack(side="left", padx=6)
        self.cancel_button = ttk.Button(toolbar, text="Anuluj sprawdzanie", command=self.cancelled.set, state="disabled")
        self.cancel_button.pack(side="right")
        source = ttk.Frame(self)
        source.grid(row=4, sticky="ew", pady=6)
        source.columnconfigure(1, weight=1)
        ttk.Label(source, text="Scena do odbioru:").grid(row=0, column=0, padx=(0, 8))
        self.scene_choice = ttk.Combobox(source, state="disabled")
        self.scene_choice.grid(row=0, column=1, sticky="ew")
        self.scene_choice.bind("<<ComboboxSelected>>", lambda _event: self.show_scene())
        self.plate_choice = ttk.Combobox(source, state="disabled", width=18)
        self.plate_choice.grid(row=0, column=2, padx=(8, 0))
        self.plate_choice.bind("<<ComboboxSelected>>", lambda _event: self.focus_plate())
        self.image_info = tk.StringVar(value="396 pełnych scen • 479 tablic GT, w tym 30 nieczytelnych dla MZ. GT jest tylko do odczytu.")
        ttk.Label(source, textvariable=self.image_info, wraplength=1040, justify="left").grid(row=1, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        images = ttk.Frame(self)
        images.grid(row=5, sticky="nsew")
        images.columnconfigure(0, weight=1)
        images.columnconfigure(1, weight=2)
        images.rowconfigure(1, weight=1)
        ttk.Label(images, text="Cały obraz wejściowy MT — po orientacji EXIF").grid(row=0, column=0, sticky="w")
        ttk.Label(images, text="Powiększenie GT — rolka: zoom, przeciąganie: przesuwanie").grid(row=0, column=1, sticky="w")
        self.overview = ZoomableCanvas(images, background="#101820", highlightthickness=0, width=340, height=300)
        self.detail = ZoomableCanvas(images, background="#101820", highlightthickness=0, width=620, height=300)
        for column, canvas in enumerate((self.overview, self.detail)):
            canvas.min_zoom = .01
            canvas.show_info = False
            canvas.set_overlay_renderer(self.draw_gt)
            canvas.grid(row=1, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))
        ttk.Label(self, text="Turkus: bbox GT • Zielony: TL/TR/BR/BL • Czerwony: problem kolejności, surowe P1/P2/P3/P4. Brak edycji GT.",
                  wraplength=1040).grid(row=6, sticky="w", pady=5)
        approval = ttk.LabelFrame(self, text="Odbiór operatora — granice obrazu nie potwierdzają położenia GT", padding=8)
        approval.grid(row=7, sticky="ew")
        approval.columnconfigure(1, weight=1)
        self.confirmed = tk.BooleanVar(value=False)
        self.confirm_button = ttk.Checkbutton(approval, text="Obejrzałem tę scenę: bbox i TL/TR/BR/BL pokrywają właściwą tablicę",
                                              variable=self.confirmed, command=self.confirm_scene, state="disabled")
        self.confirm_button.grid(row=0, column=0, columnspan=3, sticky="w")
        self.review_count = tk.StringVar(value="Potwierdzone sceny: 0/3")
        ttk.Label(approval, textvariable=self.review_count).grid(row=1, column=0, sticky="w", pady=4)
        self.operator = tk.StringVar()
        ttk.Label(approval, text="Podpis operatora:").grid(row=1, column=1, sticky="e", padx=8)
        ttk.Entry(approval, textvariable=self.operator, width=26).grid(row=1, column=2, sticky="e")
        self.operator.trace_add("write", lambda *_args: self.update_controls())
        ttk.Label(approval, text="Powód odrzucenia:").grid(row=2, column=0, sticky="w")
        self.reason = tk.StringVar()
        ttk.Entry(approval, textvariable=self.reason).grid(row=2, column=1, columnspan=2, sticky="ew")
        footer = ttk.Frame(self)
        footer.grid(row=8, sticky="ew", pady=(8, 0))
        self.approve_button = ttk.Button(footer, text="Zatwierdź politykę EXIF/GT", command=lambda: self.submit(True), state="disabled")
        self.approve_button.pack(side="left")
        self.reject_button = ttk.Button(footer, text="Odrzuć geometrię — STOP", command=lambda: self.submit(False), state="disabled")
        self.reject_button.pack(side="left", padx=6)
        self.measure_button = ttk.Button(footer, text="[ MT ] Uruchom pomiar", state="disabled")
        self.measure_button.pack(side="right")
        ttk.Label(self, text="Zatwierdzenie zapisuje wyłącznie kontrakt geometrii. Pomiar MT wymaga odrębnego odbioru Fazy 2B.",
                  wraplength=1040).grid(row=9, sticky="w", pady=(6, 0))
        self.bind("<Destroy>", self.on_destroy, add="+")
        self.poll_job = self.after(80, self.poll)

    def update_controls(self):
        self.check_button.configure(state="disabled" if self.busy else "normal")
        ready = self.report is not None and not self.busy
        self.preview_button.configure(state="normal" if ready else "disabled")
        self.scene_choice.configure(state="readonly" if ready else "disabled")
        self.plate_choice.configure(state="readonly" if ready and self.scene else "disabled")
        valid_scene = self.scene and not any(p["geometry_issue"] for p in self.scene["plates"])
        self.confirm_button.configure(state="normal" if ready and valid_scene else "disabled")
        signed = bool(self.operator.get().strip())
        all_seen = ready and self.report["status"] == "READY_FOR_REVIEW" and set(self.report["review_scene_hashes"]) == self.reviewed
        self.approve_button.configure(state="normal" if all_seen and signed else "disabled")
        self.reject_button.configure(state="normal" if ready and signed else "disabled")
        self.measure_button.configure(state="disabled")  # There is deliberately no inference callback in Phase 2A.
        self.cancel_button.configure(state="normal" if self.busy and self.report is None else "disabled")
        self.review_count.set(f"Potwierdzone sceny: {len(self.reviewed)}/{len(self.report['review_scene_hashes']) if self.report else 3}")

    def begin(self, text):
        self.busy = True
        self.status.set(text)
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(40)
        self.update_controls()

    def end(self, success=True):
        self.busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100 if success else 0)
        self.update_controls()

    def check(self):
        if self.busy:
            return
        self.report = self.scene = self.decision = None
        self.reviewed.clear()
        self.confirmed.set(False)
        self.epoch += 1
        self.overview.clear_image()
        self.detail.clear_image()
        self.cancelled.clear()
        self.begin("WERYFIKACJA EXIF/GT WYMAGANA — sprawdzam niezmienność źródeł…")
        def worker():
            try:
                result = preflight_mt_geometry(self.selection_dir, cancelled=self.cancelled.is_set,
                    progress=lambda text: self.messages.put(("progress", text)))
                saved = load_operator_decision(result, self.output_root)
                self.messages.put(("checked", (result, saved)))
            except Exception as exc:
                self.messages.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def show_scene(self):
        if self.busy or self.report is None or self.scene_choice.current() < 0:
            return
        sha = self.report["review_scene_hashes"][self.scene_choice.current()]
        scene = next(s for s in self.report["scenes"] if s["sha256"] == sha)
        self.scene = None
        self.epoch += 1
        epoch = self.epoch
        path = contained(self.report["source_scene_root"], scene["file"])
        self.begin("Otwieram faktyczne piksele wejściowe MT i niezmienione GT…")
        def worker():
            try:
                if hashlib.sha256(path.read_bytes()).hexdigest() != scene["sha256"]:
                    raise ValueError("PREVIEW_SOURCE_SHA_CHANGED")
                image, info = inspect_oriented_image(path)
                if info != scene["image"] or hashlib.sha256(path.read_bytes()).hexdigest() != scene["sha256"]:
                    raise ValueError("PREVIEW_PIXELS_CHANGED_SINCE_PREFLIGHT")
                preview = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                self.messages.put(("image", (epoch, scene, preview)))
            except Exception as exc:
                self.messages.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def gate_status(self):
        if self.report and self.report["geometry_issues"]:
            issue = self.report["geometry_issues"][0]
            return f"FAIL / STOP — {len(self.report['geometry_issues'])} problem GT: {issue['plate_id']} — {issue['reason']}. Podgląd pozostaje dostępny."
        if self.decision:
            return ("POLITYKA EXIF ZATWIERDZONA" if self.decision["decision"] == "APPROVED"
                    else "FAIL / STOP — " + self.decision["reason"])
        return "GOTOWE DO ODBIORU — preflight 396/396 scen i 479/479 GT. Wymagana wzrokowa akceptacja operatora."

    def draw_gt(self, canvas):
        if self.scene is None:
            return
        for plate in self.scene["plates"]:
            if not isinstance(plate["bbox"], (list, tuple)) or len(plate["bbox"]) != 4:
                continue
            x1, y1, x2, y2 = plate["bbox"]
            canvas.create_rectangle(*canvas.image_to_canvas_coords(x1, y1), *canvas.image_to_canvas_coords(x2, y2),
                                    outline="#39d9ff", width=2, dash=(5, 3), tags="preview_overlay")
            if not isinstance(plate["quad"], (list, tuple)) or len(plate["quad"]) != 4:
                continue
            xy = [canvas.image_to_canvas_coords(x, y) for x, y in plate["quad"]]
            names = tuple(f"P{i + 1}" for i in range(4)) if plate["geometry_issue"] else CORNER_NAMES
            canvas.create_line(*[v for point in xy + xy[:1] for v in point], fill="#ff8060" if plate["geometry_issue"] else "#52ff87", width=3, tags="preview_overlay")
            for index, ((x, y), name) in enumerate(zip(xy, names)):
                canvas.create_oval(x-4, y-4, x+4, y+4, fill="#fff05a", outline="#101820", tags="preview_overlay")
                dx = -9 if index in (0, 3) else 9
                dy = -13 if index in (0, 1) else 13
                anchor = "e" if dx < 0 else "w"
                label = canvas.create_text(x+dx, y+dy, text=name, anchor=anchor, fill="#fff05a",
                                           font=("Segoe UI", 10, "bold"), tags="preview_overlay")
                background = canvas.create_rectangle(*canvas.bbox(label), fill="#101820", outline="", tags="preview_overlay")
                canvas.tag_lower(background, label)

    def focus_plate(self):
        if not self.scene or self.detail.original_image is None:
            return
        index = max(0, self.plate_choice.current())
        if not isinstance(self.scene["plates"][index]["bbox"], (tuple, list)) or len(self.scene["plates"][index]["bbox"]) != 4:
            return
        x1, y1, x2, y2 = self.scene["plates"][index]["bbox"]
        margin = max(50, (x2-x1) * .20)
        zoom = min(self.detail.max_zoom, self.detail.winfo_width() / (x2-x1 + 2*margin),
                   self.detail.winfo_height() / (y2-y1 + 2*margin))
        self.detail.set_view(zoom, self.detail.winfo_width()/2 - ((x1+x2)/2)*zoom,
                             self.detail.winfo_height()/2 - ((y1+y2)/2)*zoom)

    def confirm_scene(self):
        if self.scene is not None and not self.busy and not any(p["geometry_issue"] for p in self.scene["plates"]):
            sha = self.scene["sha256"]
            self.reviewed.add(sha) if self.confirmed.get() else self.reviewed.discard(sha)
            self.update_controls()

    def submit(self, accepted):
        if self.busy or self.report is None:
            return
        operator, reason = self.operator.get().strip(), self.reason.get().strip()
        if not operator or (accepted and (self.report["status"] != "READY_FOR_REVIEW" or self.reviewed != set(self.report["review_scene_hashes"]))) or (not accepted and not reason):
            return messagebox.showwarning("Odbiór geometrii", "Wymagany podpis i potwierdzenie wszystkich scen albo powód odrzucenia.", parent=self)
        report, reviewed = self.report, set(self.reviewed)
        self.begin("Ponownie sprawdzam SHA przed zapisaniem decyzji operatora…")
        def worker():
            try:
                result = save_operator_decision(report, self.output_root, operator=operator,
                    reviewed_scenes=reviewed, accepted=accepted, reason=reason)
                self.messages.put(("decision", result))
            except Exception as exc:
                self.messages.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, data = self.messages.get_nowait()
                if kind == "progress":
                    self.status.set(data)
                elif kind == "checked":
                    self.report, saved = data
                    if saved:
                        _path, self.decision = saved
                        self.reviewed = set(self.decision["reviewed_scene_hashes"])
                    by_sha = {s["sha256"]: s for s in self.report["scenes"]}
                    self.scene_choice.configure(values=[f"{'! GT / ' if any(p['geometry_issue'] for p in by_sha[sha]['plates']) else ''}EXIF {by_sha[sha]['image']['exif_orientation']} — {by_sha[sha]['file']}"
                                                       for sha in self.report["review_scene_hashes"]])
                    self.scene_choice.current(0)
                    self.end()
                    self.show_scene()
                elif kind == "image":
                    epoch, scene, preview = data
                    if epoch != self.epoch:
                        continue
                    self.scene = scene
                    info = scene["image"]
                    self.image_info.set(f"{scene['file']}\nSHA: {scene['sha256']}\n"
                        f"EXIF={info['exif_orientation']} | raw {info['raw_size'][0]}×{info['raw_size'][1]} → "
                        f"wejście MT {info['oriented_size'][0]}×{info['oriented_size'][1]} | "
                        f"GT: {len(scene['plates'])} | MAE={info['decoder_comparison']['mae']:.2f}, p95={info['decoder_comparison']['p95']:.2f}")
                    self.confirmed.set(scene["sha256"] in self.reviewed)
                    self.plate_choice.configure(values=[p["plate_id"] + (" — ! GT" if p["geometry_issue"] else "") for p in scene["plates"]])
                    self.plate_choice.current(next((i for i, p in enumerate(scene["plates"]) if p["geometry_issue"]), 0))
                    self.overview.set_image_fit_to_view(preview)
                    self.detail.set_image(preview)
                    self.focus_plate()
                    self.end()
                    self.status.set(self.gate_status())
                elif kind == "decision":
                    path, self.decision = data
                    self.end()
                    self.status.set(self.gate_status() + " — kontrakt: " + str(path))
                elif kind == "error":
                    self.report = self.scene = self.decision = None
                    self.reviewed.clear()
                    self.epoch += 1
                    self.overview.clear_image()
                    self.detail.clear_image()
                    self.end(False)
                    self.status.set("FAIL / STOP — " + data)
        except queue.Empty:
            pass
        self.poll_job = self.after(80, self.poll)

    def on_destroy(self, event):
        if event.widget is self:
            self.cancelled.set()
            if self.progress.winfo_exists():
                self.progress.stop()
            self.after_cancel(self.poll_job)
