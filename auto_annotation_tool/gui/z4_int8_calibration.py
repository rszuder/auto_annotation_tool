"""Native Z4 preparation of calibration evidence; never starts a converter."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ..exporters.int8_calibration import build_manifest
from ..exporters import exploratory_calibration as exploratory


class Int8CalibrationDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Bezpieczna kalibracja INT8 — MT / MZ")
        self.geometry("1060x760")
        self.minsize(800, 600)
        self.transient(parent.winfo_toplevel())
        self.result = None
        self._closed = self._busy = False
        self._poll_id = None
        self._events = queue.Queue()
        self._revision = 0
        root = Path(__file__).resolve().parents[2]
        self.values = {key: tk.StringVar(self, value) for key, value in {
            "role": "MT — sceny", "history_path": str(root / "Workspace/5_training_runs/plates/training_history.json"),
            "run_id": "", "eval_inventory": str(root / "Workspace/E-MZ-DN-01/evaluation_selections/E-MZ-DN-01_EVAL396_20261009/selection_manifest.json"),
            "final_inventory": "", "image_size": "640", "limit": "300", "approved_by": "",
        }.items()}
        self.approval = tk.BooleanVar(self, False)
        self.mode = tk.StringVar(self, "Ścisła kalibracja INT8 — wymaga final_test")
        self.research_approval = tk.BooleanVar(self, False)
        self.research_values = {k: tk.StringVar(self, v) for k, v in {
            "checkpoint_sha256": "", "confidence_threshold": "0.25", "iou_threshold": "0.45"}.items()}
        self.status = tk.StringVar(self, "Wybierz ukończony trening i inwentarze SHA. Brak final_test oznacza BLOCKED.")
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.mode_combo = ttk.Combobox(body, textvariable=self.mode, state="readonly", width=62,
            values=("Ścisła kalibracja INT8 — wymaga final_test", exploratory.LABEL))
        self.mode_combo.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self.role_combo = ttk.Combobox(body, textvariable=self.values["role"],
                                       values=("MT — sceny", "MZ — cropy"), state="readonly")
        ttk.Label(body, text="Tor modelu").grid(row=1, column=0, sticky="w")
        self.role_combo.grid(row=1, column=1, sticky="w")
        self.role_combo.bind("<<ComboboxSelected>>", lambda _: self._role_changed(root))
        labels = (("history_path", "Historia treningu (JSON)"), ("run_id", "Identyfikator treningu"),
                  ("eval_inventory", "Inwentarz SHA EVAL396"), ("final_inventory", "Inwentarz SHA final_test"),
                  ("image_size", "Rozmiar wejścia (imgsz)"), ("limit", "Maksymalna liczba próbek"),
                  ("approved_by", "Operator zatwierdzający"))
        for row, (key, label) in enumerate(labels, 2):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            if key == "run_id":
                self.run_combo = ttk.Combobox(body, textvariable=self.values[key], state="readonly")
                self.run_combo.grid(row=row, column=1, sticky="ew")
                ttk.Button(body, text="Wczytaj treningi", command=self.load_runs).grid(row=row, column=2, padx=(8, 0))
            else:
                ttk.Entry(body, textvariable=self.values[key]).grid(row=row, column=1, sticky="ew")
                if key.endswith("inventory") or key == "history_path":
                    ttk.Button(body, text="Wybierz JSON", command=lambda k=key: self.choose(k)).grid(row=row, column=2, padx=(8, 0))
        ttk.Checkbutton(body, variable=self.approval,
                        text="Zatwierdzam źródło treningowe i wybór wyłącznie splitu train").grid(
                            row=9, column=0, columnspan=3, sticky="w", pady=8)
        self.research_frame = ttk.LabelFrame(body, text="EXPLORATORY_ONLY — LiteRT CPU; FINAL_TEST_NOT_VERIFIED", padding=6)
        self.research_frame.grid(row=10, column=0, columnspan=3, sticky="ew")
        self.research_frame.columnconfigure(1, weight=1)
        for i, (key, label) in enumerate((("checkpoint_sha256", "SHA-256 checkpointu"),
                                        ("confidence_threshold", "conf"), ("iou_threshold", "IoU"))):
            ttk.Label(self.research_frame, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(self.research_frame, textvariable=self.research_values[key]).grid(row=i, column=1, sticky="ew")
        ttk.Button(self.research_frame, text="Oblicz SHA checkpointu", command=self.read_checkpoint_sha).grid(row=0, column=2)
        self.research_check = ttk.Checkbutton(self.research_frame, variable=self.research_approval, text=exploratory.CONFIRMATION)
        self.research_check.grid(row=3, column=0, columnspan=3, sticky="w")
        self.research_frame.grid_remove()
        ttk.Label(body, textvariable=self.status, wraplength=1000).grid(row=11, column=0, columnspan=3, sticky="ew")
        self.details = scrolledtext.ScrolledText(body, height=15, wrap="none", state="disabled")
        self.details.grid(row=12, column=0, columnspan=3, sticky="nsew", pady=8)
        body.rowconfigure(12, weight=1)
        actions = ttk.Frame(body)
        actions.grid(row=13, column=0, columnspan=3, sticky="ew")
        self.prepare_button = ttk.Button(actions, text="Sprawdź i przygotuj manifest", command=self.prepare)
        self.prepare_button.pack(side="left")
        self.save_button = ttk.Button(actions, text="Zapisz manifest / raport BLOCKED", command=self.save, state="disabled")
        self.save_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Zamknij", command=self.destroy).pack(side="right")
        for var in self.values.values():
            var.trace_add("write", self.settings_changed)
        self.approval.trace_add("write", self.invalidate)
        self.research_approval.trace_add("write", self.invalidate)
        self.mode.trace_add("write", self.mode_changed)
        for var in self.research_values.values():
            var.trace_add("write", self.settings_changed)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _role_changed(self, root):
        mt = self.values["role"].get().startswith("MT")
        self.values["history_path"].set(str(root / "Workspace/5_training_runs" / ("plates" if mt else "chars") / "training_history.json"))
        self.values["image_size"].set(("512" if mt else "320") if self.is_research() else ("640" if mt else "256"))
        self.research_values["checkpoint_sha256"].set("")
        self.values["run_id"].set("")
        self.run_combo.configure(values=())

    def invalidate(self, *_):
        self._revision += 1
        self.result = None
        self.save_button.configure(state="disabled")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")
        self.status.set("Zmieniono ustawienia — ponownie sprawdź manifest. " +
                       ("FINAL_TEST_NOT_VERIFIED; wyłącznie badania eksploracyjne." if self.is_research()
                        else "Brak inwentarza final_test blokuje kalibrację."))

    def settings_changed(self, *_):
        self.approval.set(False)
        self.research_approval.set(False)
        self.invalidate()

    def is_research(self):
        return self.mode.get() == exploratory.LABEL

    def mode_changed(self, *_):
        self.settings_changed()
        if self.is_research():
            self.research_frame.grid()
            self.values["image_size"].set("512" if self.values["role"].get().startswith("MT") else "320")
            self.values["limit"].set("")
        else:
            self.research_frame.grid_remove()

    def read_checkpoint_sha(self):
        try:
            history = exploratory.strict._read(self.values["history_path"].get())
            run = history["runs"][self.values["run_id"].get()]
            self.research_values["checkpoint_sha256"].set(exploratory.strict.file_sha256(run["best_weights"]))
        except Exception as exc:
            self.status.set("BLOCKED: " + str(exc))

    def choose(self, key):
        path = filedialog.askopenfilename(parent=self, title="Wybierz dokument SHA / historię treningu",
                                         filetypes=(("JSON", "*.json"),))
        if path:
            self.values[key].set(path)
            if key == "history_path":
                self.values["run_id"].set("")
                self.run_combo.configure(values=())

    def load_runs(self):
        try:
            payload = json.loads(Path(self.values["history_path"].get()).read_text(encoding="utf-8-sig"))
            runs = sorted(k for k, v in payload["runs"].items() if v.get("status") == "completed")
            self.run_combo.configure(values=runs)
            self.values["run_id"].set("")
            self.status.set(f"Ukończone treningi: {len(runs)}. Wybierz identyfikator; źródło nie jest zatwierdzane automatycznie.")
        except Exception as exc:
            self.status.set("BLOCKED: " + str(exc))

    def prepare(self):
        if self._busy or self._closed:
            return
        self.invalidate()
        try:
            config = {k: v.get().strip() for k, v in self.values.items()}
            config["role"] = "plate" if config["role"].startswith("MT") else "character"
            config["image_size"], config["limit"] = int(config["image_size"]), int(config["limit"])
            if not self.approval.get():
                config["approved_by"] = ""
            builder = build_manifest
            if self.is_research():
                builder = exploratory.build_manifest
                config.pop("final_inventory")
                config.update({k: v.get().strip() for k, v in self.research_values.items()})
                config["confidence_threshold"] = float(config["confidence_threshold"])
                config["iou_threshold"] = float(config["iou_threshold"])
                config["operator_confirmation"] = self.research_approval.get()
        except ValueError:
            self.status.set("BLOCKED: imgsz i liczba próbek muszą być liczbami całkowitymi.")
            return
        self._busy = True
        revision = self._revision
        self.prepare_button.configure(state="disabled")
        self.status.set("Kontrola pochodzenia, SHA i niezależności train…")
        def worker():
            try:
                self._events.put((revision, builder(**config), None))
            except Exception as exc:
                self._events.put((revision, None, str(exc)))
        threading.Thread(target=worker, name="z4-calibration-inventory", daemon=True).start()
        self._poll_id = self.after(50, self._poll)

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        try:
            revision, result, error = self._events.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(50, self._poll)
            return
        self._busy = False
        self.prepare_button.configure(state="normal")
        if revision != self._revision:
            self.status.set("Ustawienia zmieniły się podczas kontroli. Przygotuj manifest ponownie.")
            return
        if error:
            self.status.set("BLOCKED: " + error)
            return
        self.result = result
        counts = result["counts"]
        self.status.set(f"{result['status']} | train: {counts['train_candidates']}, wybrane: {counts['selected']}, "
                        f"sceny: {counts['selected_source_scenes']}, odrzucone val/test: {counts['cross_split_rejected']}, "
                        f"duplikaty: {counts['duplicates_removed']}\n" + "; ".join(result["blockers"])
                        + "\n" + "; ".join(result.get("warnings", []))
                        + "\nFingerprint wejścia: " + result["input_fingerprint"])
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", json.dumps(result, ensure_ascii=False, indent=2))
        self.details.configure(state="disabled")
        self.save_button.configure(state="normal")

    def save(self):
        if not self.result:
            return
        name = filedialog.asksaveasfilename(parent=self, title="Zapisz nowy manifest kalibracji",
                                          initialfile=f"calibration_{self.result['role']}_{self.result['status']}.json",
                                          defaultextension=".json", filetypes=(("JSON", "*.json"),))
        if not name:
            return
        try:
            p = Path(name).resolve()
            refs = self.result["source_files"] + [self.result["checkpoint"]]
            refs += [ref for exclusion in self.result["exclusions"] for ref in exclusion["files"]]
            if p.suffix.lower() != ".json" or any(p.is_relative_to(Path(ref["path"]).parent) for ref in refs):
                raise ValueError("Wybierz nowy JSON poza źródłami treningu i chronionymi zbiorami.")
            with p.open("x", encoding="utf-8") as stream:
                json.dump(self.result, stream, ensure_ascii=False, indent=2)
            self.status.set(f"Zapisano {self.result['status']}: {p}. Nie uruchomiono konwersji.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Nie zapisano manifestu", str(exc), parent=self)

    def destroy(self):
        self._closed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        super().destroy()


def open_int8_calibration_dialog(parent):
    return Int8CalibrationDialog(parent)


def calibration_request_options(variables):
    """Explicit UI mode; never infer authorization from a manifest filename."""
    def value(key, default):
        var = variables.get(key)
        return var.get() if hasattr(var, "get") else default if var is None else var
    return {"calibration_mode": value("calibration_mode", "strict"),
            "exploratory_confirmation": value("exploratory_confirmation", False)}


class CalibrationModeControl(ttk.Frame):
    """Shared by the existing single and MT+MZ export dialogs."""
    def __init__(self, parent, variables):
        super().__init__(parent)
        self.variables = variables
        variables["calibration_mode"] = tk.StringVar(self, "strict")
        variables["exploratory_confirmation"] = tk.BooleanVar(self, False)
        self.choice = tk.StringVar(self, "Ścisła — wymaga final_test")
        self.combo = ttk.Combobox(self, textvariable=self.choice, state="readonly",
                                 values=("Ścisła — wymaga final_test", exploratory.LABEL))
        self.combo.pack(fill="x")
        self.notice = ttk.Label(self, text="", wraplength=420)
        self.notice.pack(fill="x")
        self.notice.bind("<Configure>", lambda event: self.notice.configure(wraplength=max(180, event.width - 4)))
        self.check = ttk.Checkbutton(self, text="Potwierdzam wyłącznie użycie eksploracyjne",
                                     variable=variables["exploratory_confirmation"], state="disabled")
        self.check.pack(anchor="w")
        self._traces = []
        for key, var in list(variables.items()):
            if key != "exploratory_confirmation" and hasattr(var, "trace_add"):
                token = var.trace_add("write", self.invalidate)
                self._traces.append((var, token))
        self.choice.trace_add("write", self.changed_mode)

    def invalidate(self, *_):
        self.variables["exploratory_confirmation"].set(False)

    def changed_mode(self, *_):
        research = self.choice.get() == exploratory.LABEL
        self.variables["calibration_mode"].set("exploratory" if research else "strict")
        self.check.configure(state="normal" if research else "disabled")
        self.notice.configure(text=("EXPLORATORY_ONLY • FINAL_TEST_NOT_VERIFIED\n" + exploratory.CONFIRMATION
                                    if research else "Wymagany zweryfikowany final_test; ścisły manifest READY."))

    def destroy(self):
        for var, token in self._traces:
            var.trace_remove("write", token)
        super().destroy()
