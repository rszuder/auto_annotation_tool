"""Participant selector, audit matrix and progress window for PZ3."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..registry.participant_pool_audit import (
    STATUS_CLEAN,
    STATUS_DEPENDENT,
    STATUS_SUSPECT,
    STATUS_UNKNOWN,
)

_LABEL = {
    STATUS_CLEAN: "✓ brak zależności",
    STATUS_DEPENDENT: "⛔ zależny",
    STATUS_SUSPECT: "⚠ podejrzana pochodna",
    STATUS_UNKNOWN: "? nieustalone",
}


class ParticipantSelectionDialog:
    def __init__(self, parent, *, models, selected_ids, track_name):
        self.models = list(models)
        self.selected = set(selected_ids)
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.title("Modele uczestniczące w eksperymencie")
        self.window.geometry("900x580")
        self.window.minsize(720, 460)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build(track_name)
        self._populate()
        self.window.grab_set()

    def _build(self, track_name):
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        ttk.Label(root, text="Modele uczestniczące", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text=(
                f"Tor: {track_name}\n"
                "Audyt dotyczy wyłącznie train/val zaznaczonych modeli "
                "(wraz z ancestry fine-tune). Modele spoza rankingu nie blokują puli."
            ),
            wraplength=840,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10))
        frame = ttk.Frame(root)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        cols = ("sel", "model", "family", "scale", "run", "prov")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for key, title, width in (
            ("sel", "Udział", 70), ("model", "Model ID", 240),
            ("family", "Rodzina", 100), ("scale", "Skala", 70),
            ("run", "Run", 220), ("prov", "Provenance", 100),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=tk.W)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview).grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda _e: self._toggle(), add="+")
        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Zaznacz / odznacz", command=self._toggle).pack(side=tk.LEFT)
        ttk.Button(actions, text="Wyczyść", command=self._clear).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Anuluj", command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Zapisz uczestników", command=self._accept).pack(side=tk.RIGHT, padx=(0, 6))

    def _populate(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for item in self.models:
            self.tree.insert(
                "", tk.END, iid=item.model_id,
                values=(
                    "✓" if item.model_id in self.selected else "",
                    item.model_id, item.family or "-", item.scale or "-",
                    item.run_id or "-", item.provenance_status or "-",
                ),
            )

    def _toggle(self):
        for iid in self.tree.selection():
            if iid in self.selected:
                self.selected.remove(iid)
            else:
                self.selected.add(iid)
        self._populate()

    def _clear(self):
        self.selected.clear()
        self._populate()

    def _accept(self):
        self.result = tuple(item.model_id for item in self.models if item.model_id in self.selected)
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def show(self):
        self.window.wait_window()
        return self.result


class ParticipantAuditMatrixDialog:
    def __init__(self, parent, report):
        self.report = report
        self.window = tk.Toplevel(parent)
        self.window.title("Audyt puli względem modeli uczestniczących")
        self.window.geometry("1280x720")
        self.window.minsize(900, 520)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._populate()
        self.window.grab_set()

    def _build(self):
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        ttk.Label(root, text="Audyt niezależności puli — per model", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text=(
                "Wspólny tor odrzuca obraz, jeśli jest zależny od choć jednego "
                "uczestnika. Zależność względem modeli spoza rankingu nie wpływa na werdykt."
            ),
            wraplength=1200,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10))
        summary = ttk.Frame(root)
        summary.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for i, (label, value) in enumerate((
            ("Sprawdzono", len(self.report.candidates)),
            ("Zależne", self.report.dependent_count),
            ("Podejrzane", self.report.suspect_count),
            ("Brak wykrytej zależności", self.report.clean_count),
            ("Nieustalone", self.report.unknown_count),
        )):
            summary.columnconfigure(i, weight=1)
            box = ttk.LabelFrame(summary, text=label, padding=(8, 6))
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0))
            ttk.Label(box, text=str(value), font=("Segoe UI", 15, "bold"), anchor="center").pack(fill=tk.X)
        frame = ttk.Frame(root)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        model_cols = tuple(f"m{i}" for i in range(len(self.report.participants)))
        cols = ("file", "common") + model_cols
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("file", text="Plik")
        self.tree.heading("common", text="Werdykt wspólny")
        self.tree.column("file", width=220)
        self.tree.column("common", width=210)
        for i, participant in enumerate(self.report.participants):
            key = model_cols[i]
            self.tree.heading(key, text=f"{participant.family}-{participant.scale}\n{participant.model_id[:20]}")
            self.tree.column(key, width=185)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        x = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.detail = tk.Text(root, height=9, wrap=tk.WORD, state=tk.DISABLED)
        self.detail.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.tree.bind("<<TreeviewSelect>>", self._select, add="+")
        footer = ttk.Frame(root)
        footer.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            text=(
                f"Cache: SHA hit {self.report.cache_hits_sha}, miss {self.report.cache_misses_sha}; "
                f"pHash hit {self.report.cache_hits_phash}, miss {self.report.cache_misses_phash}; "
                f"referencje: {self.report.reference_rows}."
            ),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Zamknij", command=self._close).grid(row=0, column=1)

    def _populate(self):
        for i, candidate in enumerate(self.report.candidates):
            values = [candidate.filename, _LABEL.get(candidate.common_status, candidate.common_status)]
            values.extend(_LABEL.get(item.status, item.status) for item in candidate.per_model)
            self.tree.insert("", tk.END, iid=str(i), values=tuple(values))
        if self.report.candidates:
            self.tree.selection_set("0")
            self._show(0)

    def _select(self, _event=None):
        selected = self.tree.selection()
        if selected:
            self._show(int(selected[0]))

    def _show(self, index):
        candidate = self.report.candidates[index]
        lines = [
            f"Plik: {candidate.filename}",
            f"Wspólny werdykt: {_LABEL.get(candidate.common_status, candidate.common_status)}",
            "",
        ]
        for item in candidate.per_model:
            lines += [
                f"{item.model_id}: {_LABEL.get(item.status, item.status)}",
                f"  {item.reason}",
            ]
            if item.training_dataset_id:
                lines.append(f"  dataset/split: {item.training_dataset_id}/{item.training_split}")
            if item.training_run_id:
                lines.append(f"  run: {item.training_run_id}")
            if item.phash_distance is not None:
                lines.append(f"  pHash Δ: {item.phash_distance}")
            lines.append(f"  pokrycie pHash: {item.phash_reference_coverage:.1%}")
            lines.append("")
        self.detail.configure(state=tk.NORMAL)
        self.detail.delete("1.0", tk.END)
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state=tk.DISABLED)

    def _close(self):
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def show(self):
        self.window.wait_window()


class BatchProgressDialog:
    def __init__(self, parent, title="Dodawanie puli obrazów"):
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("560x180")
        self.window.resizable(True, False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        self.stage = tk.StringVar(master=self.window, value="Przygotowanie…")
        self.count = tk.StringVar(master=self.window, value="")
        ttk.Label(root, text="Kontrola puli obrazów", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(root, textvariable=self.stage).pack(anchor="w", pady=(8, 3))
        self.bar = ttk.Progressbar(root, maximum=100.0)
        self.bar.pack(fill=tk.X)
        ttk.Label(root, textvariable=self.count).pack(anchor="e", pady=(3, 0))
        self.window.update_idletasks()

    def update(self, stage, current, total):
        self.stage.set(stage)
        self.count.set(f"{current} / {total}" if total else "")
        self.bar.configure(value=(100.0 * current / total) if total else 0.0)
        self.window.update_idletasks()

    def close(self):
        try:
            self.window.destroy()
        except Exception:
            pass
