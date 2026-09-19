"""Participant selector, audit matrix and progress window for PZ3."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
from queue import Empty, SimpleQueue
import tkinter as tk
from tkinter import messagebox, ttk

from .pz3_participant_profile import (
    ParticipantProfilePanel, architecture_label, format_metric, participant_eligible,
    provenance_badge, quality_metric, short_identifier, training_date_sort_value,
)
from .app_tooltips import hide_simple_tooltip
from ..registry.participant_background import metric_value

from .pz3_audit_resolution_dialog import ParticipantAuditMatrixDialog

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

    if column == "arch":
        return (_natural_sort_key(item.family), _MODEL_SCALE_ORDER.get(item.scale, 50),
                _natural_sort_key(item.model_id))

    if column in {"quality", "pose_quality"}:
        value = quality_metric(item)[1] if column == "quality" else metric_value(getattr(item, "pose_map50_95", None))
        return (value is None, value if value is not None else 0, _natural_sort_key(item.model_id))

    if column == "finished":
        value = training_date_sort_value(getattr(item, "training_finished_at", ""))
        return (value is None, value or 0, _natural_sort_key(item.model_id))

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

    if column in {"run", "dataset"}:
        value = str((item.run_id if column == "run" else item.dataset_id) or "").strip()
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



def participant_target_context(target: str | None) -> dict[str, str]:
    """Czytelny kontekst typu modeli dla selektora uczestników PZ3."""
    normalized = str(target or "").strip().lower()
    if normalized == "char":
        return {
            "window_title": "Wybierz modele znakowe MZ",
            "header": "MZ / modele znakowe (char · Detect)",
            "description": (
                "Ten eksperyment dotyczy rozpoznawania znaków tablicy. "
                "Lista poniżej zawiera wyłącznie modele targetu char/MZ "
                "dopuszczone przez katalog uczestników."
            ),
            "model_column": "Model znakowy",
            "selection_label": "Wybrane modele MZ",
        }
    if normalized == "plate":
        return {
            "window_title": "Wybierz modele tablic MT",
            "header": "MT / modele tablic (plate · Pose)",
            "description": (
                "Ten eksperyment dotyczy lokalizacji tablic i ich narożników. "
                "Lista poniżej zawiera modele targetu plate/MT."
            ),
            "model_column": "Model tablic",
            "selection_label": "Wybrane modele MT",
        }
    if normalized == "vehicle":
        return {
            "window_title": "Wybierz modele pojazdów MP",
            "header": "MP / modele pojazdów (vehicle)",
            "description": (
                "Ten eksperyment dotyczy detekcji pojazdów. "
                "Lista poniżej zawiera modele targetu vehicle/MP."
            ),
            "model_column": "Model pojazdów",
            "selection_label": "Wybrane modele MP",
        }
    return {
        "window_title": "Wybierz modele do eksperymentu",
        "header": "Modele uczestniczące",
        "description": (
            "Lista modeli jest filtrowana zgodnie z targetem bieżącego toru."
        ),
        "model_column": "Model",
        "selection_label": "Wybrane modele",
    }

class ParticipantSelectionDialog:
    def __init__(
        self,
        parent,
        *,
        models,
        selected_ids,
        track_name,
        target="",
        on_refresh=None,
        on_register=None,
        on_unregister=None,
        palette=None,
    ):
        self.models = list(models)
        self.selected = set(selected_ids) & {item.model_id for item in self.models if participant_eligible(item)}
        self.result = None
        self._sort_column = ""
        self._sort_reverse = False
        self._column_titles = {}
        self.on_refresh = on_refresh
        self.on_register = on_register
        self.on_unregister = on_unregister
        self.target_context = participant_target_context(target)
        self.registry_status = tk.StringVar(
            master=parent,
            value="",
        )
        self.window = tk.Toplevel(parent)
        self.selection_status = tk.StringVar(parent)
        self.window.title(self.target_context["window_title"])
        self.window.geometry("1140x780")
        self.window.minsize(1000, 700)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.palette = palette
        self._build(track_name)
        self._populate()
        self.window.grab_set()

    def _build(self, track_name):
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        ttk.Label(
            root,
            text=f"{self.target_context['header']} · {track_name}",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        description = ttk.Label(
            root,
            text=(
                self.target_context["description"]
                + "\n"
                + "Wybierz modele, które chcesz porównać w tym eksperymencie. "
                "Kliknij model, aby zobaczyć jego szczegóły. Pochodzenie, "
                "dataset treningowy i metryki pomagają zweryfikować właściwy "
                "checkpoint przed zatwierdzeniem."
            ),
            wraplength=1080,
            justify=tk.LEFT,
        )
        description.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        root.bind(
            "<Configure>",
            lambda event: description.configure(wraplength=max(260, event.width - 28)),
            add="+",
        )
        toolbar = ttk.Frame(root)
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(toolbar, text="Sortuj:").pack(side=tk.LEFT)
        self._sort_fields = {
            "Model": "model", "Architektura": "arch", "Run": "run", "Dataset": "dataset",
            "mAP50–95 Pose": "pose_quality", "Jakość walidacyjna": "quality",
            "Historia": "prov", "Data zakończenia": "finished",
        }
        self.sort_var = tk.StringVar(self.window, "Model")
        sort_picker = ttk.Combobox(toolbar, textvariable=self.sort_var,
                                  values=tuple(self._sort_fields), state="readonly", width=24)
        sort_picker.pack(side=tk.LEFT, padx=6)
        sort_picker.bind("<<ComboboxSelected>>", lambda _event: self._sort_models(
            self._sort_fields[self.sort_var.get()]))
        ttk.Button(toolbar, text="Odwróć kolejność", command=lambda: self._sort_models(
            self._sort_fields[self.sort_var.get()])).pack(side=tk.LEFT)
        ttk.Label(toolbar, textvariable=self.selection_status, font=("Segoe UI", 9, "bold")).pack(side=tk.RIGHT)
        frame = ttk.Frame(root)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        cols = ("sel", "model", "arch", "origin", "quality", "prov")
        style = ttk.Style(self.window)
        scale = max(1.0, float(self.window.tk.call("tk", "scaling")) / (96 / 72))
        style.configure("ParticipantCatalog.Treeview", rowheight=round(46 * scale))
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended",
                                 style="ParticipantCatalog.Treeview", height=5)
        for key, title, width in (
            ("sel", "W eksperymencie", 125),
            ("model", self.target_context["model_column"], 170),
            ("arch", "Architektura", 100), ("origin", "Pochodzenie", 240),
            ("quality", "Jakość (mAP50–95)", 145), ("prov", "Historia", 150),
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
                minwidth=width,
                stretch=key in {"model", "origin"},
                anchor=tk.CENTER if key == "sel" else tk.W,
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind("<space>", lambda _event: (self._toggle(), "break")[1], add="+")
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
        self.profile = ParticipantProfilePanel(root, palette=self.palette)
        self.profile.frame.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        selection_actions = ttk.Frame(root)
        selection_actions.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.add_button = ttk.Button(selection_actions, text="Dodaj do eksperymentu",
                                     command=lambda: self._set_participation(True))
        self.add_button.pack(side=tk.LEFT)
        self.remove_button = ttk.Button(selection_actions, text="Usuń z eksperymentu",
                                        command=lambda: self._set_participation(False))
        self.remove_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(selection_actions, text="Usuń wszystkie z wyboru",
                   command=self._clear).pack(side=tk.RIGHT)
        self.registry_actions = ttk.LabelFrame(root, text="Zarządzanie katalogiem modeli", padding=(8, 6))
        self.registry_actions.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        self.registry_actions.columnconfigure(3, weight=1)
        ttk.Button(self.registry_actions, text="Odśwież modele", command=self._refresh_registry,
                   state="normal" if callable(self.on_refresh) else "disabled").grid(row=0, column=0, sticky="w")
        ttk.Button(self.registry_actions, text="Dodaj model z dysku…", command=self._register_model,
                   state="normal" if callable(self.on_register) else "disabled").grid(
            row=0, column=1, sticky="w", padx=(6, 0))
        self.catalog_menu = tk.Menu(self.window, tearoff=False)
        self.catalog_menu.add_command(label="Usuń ręcznie dodany model z katalogu…",
                                      command=self._unregister_model,
                                      state="normal" if callable(self.on_unregister) else "disabled")
        more = ttk.Menubutton(self.registry_actions, text="⋯", menu=self.catalog_menu, width=3)
        more.grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Label(self.registry_actions, textvariable=self.registry_status, width=1,
                  wraplength=380).grid(row=0, column=3, sticky="ew", padx=(12, 0))
        actions = ttk.Frame(root)
        actions.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        self.accept_button = ttk.Button(actions, text="Zatwierdź wybór", command=self._accept,
                                       style="Accent.TButton")
        self.accept_button.pack(side=tk.RIGHT)
        ttk.Button(actions, text="Anuluj", command=self._cancel).pack(side=tk.RIGHT, padx=(0, 6))

    def _replace_models(self, models, *, select_model_id=""):
        self.models = list(models or [])
        available = {item.model_id for item in self.models if participant_eligible(item)}
        self.selected.intersection_update(available)
        if select_model_id and select_model_id in available:
            self.selected.add(select_model_id)
        self.selection_status.set(
            f"{self.target_context['selection_label']}: "
            f"{len(self.selected)} z {len(self.models)}"
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
        self.registry_status.set("Dodawanie modelu do katalogu…")
        self.window.update_idletasks()
        try:
            models, model_id, message = self.on_register()
        except Exception as exc:
            self.registry_status.set(f"Błąd dodawania modelu: {exc}")
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
                "Usuwanie modelu z katalogu",
                "Kliknij jeden model, aby wskazać go w katalogu.",
                parent=self.window,
            )
            return
        model_id = str(selected_rows[0])
        if not messagebox.askyesno(
            "Usunąć model z katalogu?",
            (
                f"Usunąć {model_id} z katalogu modeli?\n\n"
                "Plik .pt NIE zostanie usunięty z dysku. "
                "Operacja dotyczy wyłącznie ręcznie dodanych modeli. "
                "Modele używane przez tor lub zapisany eksperyment są chronione."
            ),
            parent=self.window,
        ):
            return
        self.registry_status.set("Usuwanie modelu z katalogu…")
        self.window.update_idletasks()
        try:
            models, message = self.on_unregister(model_id)
        except Exception as exc:
            self.registry_status.set("Usunięcie modelu z katalogu zablokowane.")
            messagebox.showerror(
                "Nie można usunąć modelu z katalogu",
                str(exc),
                parent=self.window,
            )
            return
        self._replace_models(models)
        self.registry_status.set(str(message or "Model usunięty z katalogu."))

    def _update_selection_status(self, _event=None):
        rows = set(self.tree.selection())
        self.profile.show([item for item in self.models if item.model_id in rows], self.models)
        self.selection_status.set(f"Wybrane modele: {len(self.selected)} z {len(self.models)}")
        eligible = {item.model_id for item in self.models if participant_eligible(item)}
        self.add_button.configure(state="normal" if (rows & eligible) - self.selected else "disabled")
        self.remove_button.configure(state="normal" if rows & self.selected else "disabled")

    def _set_participation(self, enabled):
        rows = tuple(self.tree.selection())
        eligible = {item.model_id for item in self.models if participant_eligible(item)}
        if enabled:
            self.selected.update(set(rows) & eligible)
        else:
            self.selected.difference_update(rows)
        self._populate()
        self.tree.selection_set([row for row in rows if self.tree.exists(row)])
        self._update_selection_status()

    def _toggle_participation_cell(self, event):
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if region != "cell" or column != "#1" or not row:
            return None

        eligible = any(item.model_id == row and participant_eligible(item) for item in self.models)
        if eligible:
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
        column = self._sort_column
        def missing(item):
            if column == "quality":
                return quality_metric(item)[1] is None
            if column == "pose_quality":
                return metric_value(getattr(item, "pose_map50_95", None)) is None
            if column == "finished":
                return training_date_sort_value(getattr(item, "training_finished_at", "")) is None
            return False
        present = [item for item in self.models if not missing(item)]
        absent = [item for item in self.models if missing(item)]
        return sorted(present, key=lambda item: participant_model_sort_key(item, column, self.selected),
                      reverse=bool(getattr(self, "_sort_reverse", False))) + absent

    def _refresh_sort_headings(self):
        titles = getattr(self, "_column_titles", {})
        active = getattr(self, "_sort_column", "")
        reverse = bool(getattr(self, "_sort_reverse", False))
        if active in {"run", "dataset"}:
            active = "origin"
        elif active == "pose_quality":
            active = "quality"
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
        column = "run" if column == "origin" else column
        for label, field in self._sort_fields.items():
            if field == column:
                self.sort_var.set(label)
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
                    ("☑" if item.model_id in self.selected else "☐") if participant_eligible(item) else "—",
                    short_identifier(item.model_id, limit=27), architecture_label(item),
                    f"{short_identifier(item.run_id) or '—'}\n{short_identifier(item.dataset_id) or '—'}",
                    f"{quality_metric(item)[0]} {format_metric(quality_metric(item)[1])}",
                    provenance_badge(item)[0],
                ),
            )
        self.selection_status.set(
            f"{self.target_context['selection_label']}: "
            f"{len(self.selected)} z {len(self.models)}"
        )
        self._refresh_sort_headings()
        self._update_selection_status()

    def _toggle(self):
        rows = tuple(self.tree.selection())
        eligible = {item.model_id for item in self.models if participant_eligible(item)}
        for iid in rows:
            if iid not in eligible:
                continue
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
        self.result = tuple(item.model_id for item in self.models
                            if item.model_id in self.selected and participant_eligible(item))
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        hide_simple_tooltip(self.profile)
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


class BatchProgressDialog:
    def __init__(self, parent, title="Dodawanie puli obrazów"):
        self.parent = parent
        self._previous_grab = parent.grab_current()
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.transient(parent.winfo_toplevel())
        self.window.geometry("560x180")
        self.window.resizable(True, False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        self.stage = tk.StringVar(master=self.window, value="Przygotowanie…")
        self.count = tk.StringVar(master=self.window, value="")
        ttk.Label(root, text=title, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(root, textvariable=self.stage).pack(anchor="w", pady=(8, 3))
        self.bar = ttk.Progressbar(root, maximum=100.0)
        self.bar.pack(fill=tk.X)
        ttk.Label(root, textvariable=self.count).pack(anchor="e", pady=(3, 0))
        self.window.update_idletasks()
        self.window.lift()
        self.window.grab_set()

    def run(self, operation):
        """Run IO/CPU work off Tk's thread, delivering progress on the UI thread."""
        # Dispose cycles from closed Tk dialogs on their owning thread.
        gc.collect()
        updates = SimpleQueue()
        done = tk.BooleanVar(master=self.window, value=False)

        def progress(stage, current, total):
            updates.put((stage, current, total))

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(operation, progress)

            def poll():
                latest = None
                while True:
                    try:
                        latest = updates.get_nowait()
                    except Empty:
                        break
                if latest is not None:
                    self.update(*latest)
                if future.done():
                    done.set(True)
                else:
                    self.window.after(40, poll)

            self.window.after(0, poll)
            self.window.wait_variable(done)
            poll = None  # Break the recursive callback cycle while still on Tk.
            return future.result()

    def update(self, stage, current, total):
        self.stage.set(stage)
        self.count.set(f"{current} / {total}" if total else "")
        mode = "determinate" if total else "indeterminate"
        if str(self.bar.cget("mode")) != mode:
            self.bar.stop()
            self.bar.configure(mode=mode)
            if not total:
                self.bar.start(12)
        if total:
            self.bar.configure(value=100.0 * current / total)
        self.window.update_idletasks()

    def close(self):
        try:
            self.bar.stop()
            self.window.grab_release()
            self.window.destroy()
            from .app_window_recovery import restore_parent_after_modal
            restore_parent_after_modal(self.parent, self._previous_grab)
        except tk.TclError:
            pass
