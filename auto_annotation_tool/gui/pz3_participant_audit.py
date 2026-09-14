"""Participant selector, audit matrix and progress window for PZ3."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

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


class RegistryRefreshProgressDialog:
    """Lekki modal postępu dla pełnego odświeżania rejestru modeli."""

    def __init__(self, parent):
        import time

        self.parent = parent
        self._time = time
        self._started = time.perf_counter()

        self.window = tk.Toplevel(parent)
        self.window.title("Odświeżanie rejestru modeli")
        self.window.geometry("560x185")
        self.window.minsize(500, 170)
        self.window.resizable(True, False)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            root,
            text="Odświeżanie rejestru modeli",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        self.stage = tk.StringVar(
            master=self.window,
            value=(
                "Skanowanie Workspace: modele, historie treningów "
                "i powiązania provenance…"
            ),
        )
        ttk.Label(
            root,
            textvariable=self.stage,
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", fill=tk.X, pady=(8, 8))

        self.bar = ttk.Progressbar(
            root,
            mode="indeterminate",
            maximum=100.0,
        )
        self.bar.pack(fill=tk.X)
        self.bar.start(12)

        self.elapsed = tk.StringVar(master=self.window, value="0.0 s")
        ttk.Label(
            root,
            textvariable=self.elapsed,
        ).pack(anchor="e", pady=(5, 0))

        try:
            self.window.grab_set()
        except Exception:
            pass

        self.window.update_idletasks()
        self._tick()

    def _tick(self):
        try:
            if not self.window.winfo_exists():
                return
            seconds = self._time.perf_counter() - self._started
            self.elapsed.set(f"{seconds:.1f} s")
            self.window.after(200, self._tick)
        except Exception:
            pass

    def close(self):
        try:
            self.bar.stop()
        except Exception:
            pass
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass
        try:
            if self.parent.winfo_exists():
                self.parent.grab_set()
        except Exception:
            pass


_TRAINING_HISTORY_LABEL = {
    "complete": "Pełna",
    "known": "Potwierdzona ręcznie",
    "partial": "Częściowa",
    "legacy_partial": "Częściowa (starszy wpis)",
    "legacy_unknown": "Nieustalona",
    "unknown": "Nieustalona",
}


def training_history_label(value) -> str:
    normalized = str(value or "").strip().lower()
    return _TRAINING_HISTORY_LABEL.get(
        normalized,
        normalized or "Nieustalona",
    )


_MODEL_SCALE_ORDER = {
    "n": 0,
    "s": 1,
    "m": 2,
    "l": 3,
    "x": 4,
    "unknown": 99,
    "": 99,
}

_TRAINING_HISTORY_SORT_ORDER = {
    "complete": 0,
    "known": 1,
    "partial": 2,
    "legacy_partial": 3,
    "legacy_unknown": 4,
    "unknown": 4,
    "": 5,
}


def _natural_sort_key(value) -> tuple:
    import re

    text = str(value or "").strip().casefold()
    parts = re.split(r"(\d+)", text)
    return tuple(
        int(part) if part.isdigit() else part
        for part in parts
        if part != ""
    )


def participant_model_sort_key(
    item,
    column: str,
    selected_ids=(),
) -> tuple:
    """Klucz sortowania tabeli modeli uczestniczących."""
    selected = set(selected_ids or ())
    column = str(column or "").strip().lower()

    if column == "sel":
        # Zaznaczone modele jako pierwsze przy sortowaniu rosnącym.
        return (
            0 if str(item.model_id) in selected else 1,
            _natural_sort_key(item.model_id),
        )

    if column == "model":
        return _natural_sort_key(item.model_id)

    if column == "family":
        value = str(item.family or "").strip()
        return (
            1 if not value else 0,
            _natural_sort_key(value),
            _natural_sort_key(item.model_id),
        )

    if column == "scale":
        value = str(item.scale or "").strip().lower()
        return (
            _MODEL_SCALE_ORDER.get(value, 50),
            _natural_sort_key(value),
            _natural_sort_key(item.model_id),
        )

    if column == "run":
        value = str(item.run_id or "").strip()
        return (
            1 if not value else 0,
            _natural_sort_key(value),
            _natural_sort_key(item.model_id),
        )

    if column == "prov":
        value = str(item.provenance_status or "").strip().lower()
        return (
            _TRAINING_HISTORY_SORT_ORDER.get(value, 50),
            _natural_sort_key(value),
            _natural_sort_key(item.model_id),
        )

    return _natural_sort_key(item.model_id)


class ParticipantSelectionDialog:
    def __init__(
        self,
        parent,
        *,
        models,
        selected_ids,
        track_name,
        on_refresh=None,
        on_register=None,
        on_unregister=None,
    ):
        self.models = list(models)
        self.selected = set(selected_ids)
        self.result = None
        self._sort_column = ""
        self._sort_reverse = False
        self._column_titles = {}
        self.on_refresh = on_refresh
        self.on_register = on_register
        self.on_unregister = on_unregister
        self.registry_status = tk.StringVar(
            master=parent,
            value=(
                f"Uczestnicy: {len(self.selected)} / {len(self.models)}"
            ),
        )
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
                    "(wraz z ancestry fine-tune). Modele spoza rankingu nie blokują puli.\n"
    "Historia treningu pokazuje, czy znamy train/val modelu potrzebne do audytu."
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
            ("sel", "Udział", 64), ("model", "Model ID", 240),
            ("family", "Rodzina", 100), ("scale", "Skala", 70),
            ("run", "Run", 220), ("prov", "Historia treningu", 170),
        ):
            self._column_titles[key] = title
            self.tree.heading(
                key,
                text=title,
                command=lambda col=key: self._sort_models(col),
            )
            self.tree.column(
                key,
                width=width,
                anchor=tk.CENTER if key == "sel" else tk.W,
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview).grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda _e: self._toggle(), add="+")
        self.tree.bind(
            "<Button-1>",
            self._toggle_participation_cell,
            add="+",
        )
        self.tree.bind(
            "<<TreeviewSelect>>",
            self._update_selection_status,
            add="+",
        )
        registry_actions = ttk.Frame(root)
        registry_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        registry_actions.columnconfigure(3, weight=1)
        ttk.Button(
            registry_actions,
            text="Odśwież listę",
            command=self._refresh_registry,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            registry_actions,
            text="Zarejestruj istniejący model…",
            command=self._register_model,
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(
            registry_actions,
            text="Wyrejestruj model…",
            command=self._unregister_model,
        ).grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Label(
            registry_actions,
            textvariable=self.registry_status,
        ).grid(row=0, column=3, sticky="e", padx=(12, 0))

        actions = ttk.Frame(root)
        actions.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Zaznacz / odznacz", command=self._toggle).pack(side=tk.LEFT)
        ttk.Button(actions, text="Wyczyść", command=self._clear).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(actions, text="Anuluj", command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Zapisz uczestników", command=self._accept).pack(side=tk.RIGHT, padx=(0, 6))

    def _replace_models(self, models, *, select_model_id=""):
        self.models = list(models or [])
        available = {item.model_id for item in self.models}
        self.selected.intersection_update(available)
        if select_model_id and select_model_id in available:
            self.selected.add(select_model_id)
        self.registry_status.set(
            f"Uczestnicy: {len(self.selected)} / {len(self.models)}"
        )
        self._populate()

    def _refresh_registry(self):
        if not callable(self.on_refresh):
            return

        self.registry_status.set("Odświeżanie listy modeli…")
        self.window.update_idletasks()

        try:
            result = self.on_refresh()
        except Exception as exc:
            self.registry_status.set(f"Błąd odświeżania: {exc}")
            messagebox.showerror(
                "Odświeżanie listy modeli",
                (
                    "Nie udało się odczytać modeli z rejestru.\n\n"
                    f"{exc}"
                ),
                parent=self.window,
            )
            return

        if not isinstance(result, (tuple, list)) or len(result) < 2:
            self.registry_status.set(
                "Odświeżanie zakończone, ale wynik miał niepoprawny format."
            )
            return

        models, message = result[0], result[1]
        self._replace_models(models)
        self.registry_status.set(
            str(
                message
                or f"Odświeżono listę modeli: {len(self.models)}."
            )
        )

    def _register_model(self):
        if not callable(self.on_register):
            return
        self.registry_status.set("Rejestracja modelu…")
        self.window.update_idletasks()
        try:
            models, model_id, message = self.on_register()
        except Exception as exc:
            self.registry_status.set(f"Błąd rejestracji: {exc}")
            return
        self._replace_models(models, select_model_id=str(model_id or ""))
        if message:
            self.registry_status.set(str(message))

    def _unregister_model(self):
        if not callable(self.on_unregister):
            return
        selected_rows = tuple(self.tree.selection())
        if len(selected_rows) != 1:
            messagebox.showinfo(
                "Wyrejestrowanie modelu",
                "Zaznacz dokładnie jeden model na liście.",
                parent=self.window,
            )
            return
        model_id = str(selected_rows[0])
        if not messagebox.askyesno(
            "Wyrejestrować model?",
            (
                f"Wyrejestrować {model_id} z puli modeli?\n\n"
                "Plik .pt NIE zostanie usunięty z dysku. "
                "Operacja dotyczy wyłącznie ręcznie dodanych modeli. "
                "Modele używane przez tor lub zapisany eksperyment są chronione."
            ),
            parent=self.window,
        ):
            return
        self.registry_status.set("Wyrejestrowywanie modelu…")
        self.window.update_idletasks()
        try:
            models, message = self.on_unregister(model_id)
        except Exception as exc:
            self.registry_status.set("Wyrejestrowanie zablokowane.")
            messagebox.showerror(
                "Nie można wyrejestrować modelu",
                str(exc),
                parent=self.window,
            )
            return
        self._replace_models(models)
        self.registry_status.set(str(message or "Model wyrejestrowany."))

    def _update_selection_status(self, _event=None):
        rows = tuple(self.tree.selection())
        if not rows:
            self.registry_status.set(
                f"Uczestnicy: {len(self.selected)} / {len(self.models)}"
            )
            return

        if len(rows) == 1:
            model_id = str(rows[0])
            state = "tak" if model_id in self.selected else "nie"
            short_id = model_id if len(model_id) <= 28 else model_id[:28] + "…"
            self.registry_status.set(
                f"Wybrany: {short_id} · uczestniczy: {state}"
            )
            return

        participating = sum(
            1 for model_id in rows if model_id in self.selected
        )
        self.registry_status.set(
            f"Zaznaczono: {len(rows)} · uczestniczy: {participating}"
        )

    def _toggle_participation_cell(self, event):
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if region != "cell" or column != "#1" or not row:
            return None

        if row in self.selected:
            self.selected.remove(row)
        else:
            self.selected.add(row)

        self._populate()
        if self.tree.exists(row):
            self.tree.selection_set(row)
            self.tree.focus(row)
            self.tree.see(row)
        self._update_selection_status()
        return "break"

    def _sorted_models(self):
        if not getattr(self, "_sort_column", ""):
            return list(self.models)
        return sorted(
            self.models,
            key=lambda item: participant_model_sort_key(
                item,
                self._sort_column,
                self.selected,
            ),
            reverse=bool(getattr(self, "_sort_reverse", False)),
        )

    def _refresh_sort_headings(self):
        titles = getattr(self, "_column_titles", {})
        active = getattr(self, "_sort_column", "")
        reverse = bool(getattr(self, "_sort_reverse", False))
        for key, title in titles.items():
            suffix = ""
            if key == active:
                suffix = " ▼" if reverse else " ▲"
            self.tree.heading(
                key,
                text=title + suffix,
                command=lambda col=key: self._sort_models(col),
            )

    def _sort_models(self, column):
        rows = tuple(self.tree.selection())
        focus = str(self.tree.focus() or "")

        if getattr(self, "_sort_column", "") == column:
            self._sort_reverse = not bool(
                getattr(self, "_sort_reverse", False)
            )
        else:
            self._sort_column = column
            self._sort_reverse = False

        self._populate()
        self._refresh_sort_headings()

        existing = [iid for iid in rows if self.tree.exists(iid)]
        if existing:
            self.tree.selection_set(existing)
        if focus and self.tree.exists(focus):
            self.tree.focus(focus)
            self.tree.see(focus)
        elif existing:
            self.tree.focus(existing[0])
            self.tree.see(existing[0])

        self._update_selection_status()

    def _populate(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for item in self._sorted_models():
            self.tree.insert(
                "", tk.END, iid=item.model_id,
                values=(
                    "☑" if item.model_id in self.selected else "☐",
                    item.model_id, item.family or "-", item.scale or "-",
                    item.run_id or "-", training_history_label(item.provenance_status),
                ),
            )
        self.registry_status.set(
            f"Uczestnicy: {len(self.selected)} / {len(self.models)}"
        )
        self._refresh_sort_headings()

    def _toggle(self):
        rows = tuple(self.tree.selection())
        for iid in rows:
            if iid in self.selected:
                self.selected.remove(iid)
            else:
                self.selected.add(iid)
        self._populate()
        existing = [iid for iid in rows if self.tree.exists(iid)]
        if existing:
            self.tree.selection_set(existing)
            self.tree.focus(existing[0])
            self.tree.see(existing[0])
        self._update_selection_status()

    def _clear(self):
        self.selected.clear()
        self._populate()
        self._update_selection_status()

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


class TrainingRunSelectionDialog:
    def __init__(self, parent, *, runs, model_name, target):
        self.runs = list(runs or [])
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.title("Pochodzenie istniejącego modelu")
        self.window.geometry("940x520")
        self.window.minsize(760, 420)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build(model_name, target)
        self.window.grab_set()

    def _build(self, model_name, target):
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        ttk.Label(
            root,
            text="Powiąż checkpoint z przebiegiem treningowym",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text=(
                f"Model: {model_name}\nTarget: {target}\n"
                "Wybierz run, z którego rzeczywiście pochodzi checkpoint. "
                "Ręczne powiązanie zostanie oznaczone jako „Potwierdzona ręcznie” "
                "wraz z oświadczeniem audytowym."
            ),
            justify=tk.LEFT,
            wraplength=890,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10))

        frame = ttk.Frame(root)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        cols = ("run", "dataset", "prov", "finished")
        self.tree = ttk.Treeview(
            frame, columns=cols, show="headings", selectmode="browse"
        )
        for key, title, width in (
            ("run", "Run", 280),
            ("dataset", "Dataset", 220),
            ("prov", "Historia treningu", 170),
            ("finished", "Zakończono", 190),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=tk.W)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        for row in self.runs:
            run_id = str(row.get("run_id") or "")
            if not run_id:
                continue
            self.tree.insert(
                "", tk.END, iid=run_id,
                values=(
                    run_id,
                    str(row.get("dataset_id") or "-"),
                    training_history_label(row.get("provenance_status")),
                    str(row.get("finished_at") or row.get("started_at") or "-"),
                ),
            )

        self.tree.bind("<Double-1>", lambda _event: self._accept(), add="+")
        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Anuluj", command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Wybierz run", command=self._accept).pack(side=tk.RIGHT, padx=(0, 6))

    def _accept(self):
        selected = self.tree.selection()
        if not selected:
            return
        self.result = str(selected[0])
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
