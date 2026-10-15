
"""Read-only mobile artifact browser for Z4; no model conversions/imports."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .z4_mobile_artifact_registry import library_snapshot, sha256_file
from .z4_mobile_operation_summary import summarize_operations


def verify_unchanged_mobile_package(
    package_path: Path, *, kind: str, model_validator, bundle_validator,
) -> dict:
    """Full Desktop graph validation with an immutable-by-hash observation window.

    This does NOT approve Android import, calibration or F4 final_test. The hash
    is scoped to this validation run; the exporter must revalidate before reuse.
    """
    path = Path(package_path)
    if path.suffix.lower() != ".alprmodel" or path.is_symlink() or not path.is_file():
        raise ValueError("Wskaż istniejący, zwykły plik .alprmodel (bez dowiązania).")
    validator = model_validator if kind == "MODEL" else bundle_validator if kind == "PACKAGE" else None
    if not callable(validator):
        raise ValueError("Nieobsługiwany rodzaj paczki lub brak pełnego walidatora.")
    resolved_path = path.resolve(strict=True)
    before = sha256_file(path)
    validator(path, require_precision=True)
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != resolved_path:
        raise ValueError("Ścieżka lub rodzaj pliku zmieniły się podczas weryfikacji.")
    after = sha256_file(path)
    if before != after:
        raise ValueError("SHA-256 paczki zmienił się podczas pełnej walidacji; wynik unieważniono.")
    return {
        "path": str(path), "kind": kind, "sha256": after,
        "authority": "DESKTOP_EXPORTER_FULL_PRECISION_CHECK_ONLY",
        "android_verified": False, "final_test_verified": False,
    }


class MobileArtifactLibrary:
    def __init__(self, parent, *, packages_root: Path, repo_root: Path,
                 on_choose=None, choose_role: str | None = None,
                 choose_checkpoint: Path | None = None, choose_image_size: int | None = None,
                 choose_mt_precision: str = "int8", choose_mz_precision: str = "int8"):
        self.parent = parent
        self.on_choose = on_choose
        self.choose_role = str(choose_role or "").strip().upper()
        self.choose_checkpoint = Path(choose_checkpoint) if choose_checkpoint is not None else None
        self.choose_image_size = choose_image_size
        self.choose_mt_precision = str(choose_mt_precision or "int8").lower()
        self.choose_mz_precision = str(choose_mz_precision or "int8").lower()
        self.packages_root = Path(packages_root)
        self.repo_root = Path(repo_root)
        self.rows = []
        self.history = []
        self.by_iid = {}
        self.events_by_iid = {}
        # Per-tab sort survives search filtering and reloads. None = source order.
        self.sort_state = {"artifacts": None, "events": None}
        self.sort_labels = {
            "artifacts": {"role": "Rola", "name": "Nazwa", "variants": "Runtime / precyzja",
                          "size": "Rozmiar", "date": "Data pliku (UTC)", "state": "Stan"},
            "events": {"date": "Czas (UTC)", "operation": "Operacja", "outcome": "Wynik",
                       "file": "Plik", "sha": "SHA-256"},
        }
        self.active_source = "artifact"
        self._event_view_raw = False
        self.pipe = queue.Queue()
        self.busy = False
        self._verification_seq = 0
        self._verification_active = None
        self._verified_selection_path = None
        self.window = tk.Toplevel(parent)
        self.show_raw_events = tk.BooleanVar(master=self.window, value=False)
        self.event_view_status = tk.StringVar(
            master=self.window, value="Widok operacji: jeden wpis na eksport lub konwersję"
        )
        self.window.title("Biblioteka modeli mobilnych — Z4")
        self.window.geometry("1300x790")
        self.window.minsize(940, 570)
        # Z4LIB002: an independent, modeless tool window must keep normal Win32
        # minimize/maximize/restore controls; a transient dialog can hide them.
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        shell = ttk.Frame(self.window, padding=14)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Biblioteka modeli mobilnych", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(shell, text="Wykryte paczki ≠ zatwierdzona konwersja. Badawcze TFLite nie są paczkami .alprmodel.",
                  wraplength=1000).pack(anchor="w", pady=(1, 8))

        controls = ttk.Frame(shell)
        controls.pack(fill="x", pady=(0, 9))
        ttk.Label(controls, text="Filtr:").pack(side="left")
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(controls, textvariable=self.filter_var, width=36)
        ent.pack(side="left", padx=(6, 12))
        self.filter_var.trace_add("write", lambda *_: self.refresh_views())
        self.refresh_button = ttk.Button(controls, text="Odśwież z dysku", command=self.refresh)
        self.refresh_button.pack(side="left")
        ttk.Label(controls, text=str(self.packages_root)).pack(side="right")

        notebook = ttk.Notebook(shell)
        notebook.pack(fill="both", expand=True)
        self.packages_tab = ttk.Frame(notebook, padding=(0, 9, 0, 0))
        self.events_tab = ttk.Frame(notebook, padding=(0, 9, 0, 0))
        notebook.add(self.packages_tab, text="Pakiety i modele")
        notebook.add(self.events_tab, text="Historia konwersji i eksportów")
        self.notebook = notebook
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")
        event_controls = ttk.Frame(self.events_tab)
        event_controls.pack(fill="x", pady=(0, 7))
        ttk.Checkbutton(
            event_controls, text="Pokaż każde zdarzenie (audyt)",
            variable=self.show_raw_events, command=self.refresh_views,
        ).pack(side="left")
        ttk.Label(event_controls, textvariable=self.event_view_status).pack(side="left", padx=(14, 0))
        self.art_tree = self.build_tree(self.packages_tab,
            ("role", "name", "variants", "size", "date", "state"),
            ("Rola", "Nazwa", "Runtime / precyzja", "Rozmiar", "Data pliku (UTC)", "Stan"),
            (105, 310, 280, 96, 150, 200),
            on_sort=lambda column: self.sort_column("artifacts", column))
        self.art_tree.bind("<<TreeviewSelect>>", self.artifact_selected)
        self.event_tree = self.build_tree(self.events_tab,
            ("date", "operation", "outcome", "file", "sha"),
            ("Czas (UTC)", "Operacja", "Wynik", "Plik", "SHA-256"),
            (180, 175, 110, 410, 290),
            on_sort=lambda column: self.sort_column("events", column))
        self.event_tree.bind("<<TreeviewSelect>>", self.event_selected)

        details = ttk.LabelFrame(shell, text="Szczegóły i proweniencja", padding=9)
        details.pack(fill="both", pady=(9, 3))
        self.detail = tk.Text(details, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(details, command=self.detail.yview)
        self.detail.configure(yscrollcommand=scroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        actions = ttk.Frame(shell)
        actions.pack(fill="x", pady=(5, 1))
        ttk.Button(actions, text="Otwórz lokalizację", command=self.open_location).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Kopiuj ścieżkę", command=self.copy_path).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Sprawdź paczkę (pełna kontrola)", command=self.validate_selected).pack(side="left")
        if self.on_choose is not None:
            ttk.Button(
                actions, text=f"Wybierz jako {self.choose_role} (kontrola przed eksportem)",
                command=self.choose_for_export,
            ).pack(side="left", padx=(9, 0))
        ttk.Button(actions, text="Zamknij", command=self.close).pack(side="right")
        self.status = tk.StringVar(value="Gotowe. Odświeżam katalog zarządzanych pakietów.")
        ttk.Label(shell, textvariable=self.status, wraplength=1160).pack(anchor="w", pady=(6, 0))
        self.window.after(90, self.poll)
        self.refresh()

    @staticmethod
    def build_tree(parent, cols, headings, widths, *, on_sort=None):
        host = ttk.Frame(parent)
        host.pack(fill="both", expand=True)
        tree = ttk.Treeview(host, columns=cols, show="headings", selectmode="browse", height=10)
        for key, title, width in zip(cols, headings, widths):
            if on_sort is None:
                tree.heading(key, text=title)
            else:
                tree.heading(key, text=title, command=lambda column=key: on_sort(column))
            tree.column(key, width=width, minwidth=68, stretch=(key in ("name", "variants", "file")))
        y = ttk.Scrollbar(host, command=tree.yview)
        x = ttk.Scrollbar(host, command=tree.xview, orient="horizontal")
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)
        return tree

    @staticmethod
    def _sort_value(source: str, column: str, item):
        """Use the actual metadata rather than formatted cells (especially MB/date)."""
        if source == "artifacts":
            fields = {
                "role": item.role, "name": item.name, "variants": item.variants,
                "size": item.size_bytes, "date": item.modified_utc, "state": item.state,
            }
            value = fields.get(column, "")
        elif source == "events":
            fields = {
                "date": item.get("observed_utc", ""),
                "operation": item.get("operation", ""), "outcome": item.get("outcome", ""),
                "file": Path(str(item.get("artifact_path") or "-")).name,
                "sha": item.get("artifact_sha256") or "-",
            }
            value = fields.get(column, "")
        else:
            return ""
        if source == "artifacts" and column == "size":
            return int(value)
        # Both timestamps are generated in UTC ISO-8601 by the artifact registry.
        # The full value is used; the UI renders a shortened 19-char timestamp.
        return str(value or "").casefold()

    def sort_column(self, source: str, column: str) -> None:
        """Click heading: ascending, then descending. Does not change selection."""
        if source not in self.sort_state or column not in self.sort_labels[source]:
            return
        previous = self.sort_state[source]
        descending = bool(previous is not None and previous[0] == column and not previous[1])
        self.sort_state[source] = (column, descending)
        self._apply_sort(source)

    def _apply_sort(self, source: str) -> None:
        state = self.sort_state.get(source)
        if state is None:
            return
        column, descending = state
        tree = self.art_tree if source == "artifacts" else self.event_tree
        lookup = self.by_iid if source == "artifacts" else self.events_by_iid
        for key, label in self.sort_labels[source].items():
            marker = " ↓" if descending else " ↑"
            tree.heading(key, text=label + marker if key == column else label)
        ordered = sorted(
            tree.get_children(""),
            key=lambda iid: self._sort_value(source, column, lookup[iid]),
            reverse=descending,
        )
        for position, iid in enumerate(ordered):
            tree.move(iid, "", position)

    def close(self):
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.refresh_button.configure(state="disabled")
        self.status.set("Czytam manifesty paczek i historię eksportów (bez konwersji)...")
        def work():
            try:
                self.pipe.put(("scan", library_snapshot(self.packages_root, self.repo_root)))
            except Exception as exc:
                self.pipe.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True, name="z4-artifact-library-readonly-scan").start()

    def poll(self):
        try:
            while True:
                kind, value = self.pipe.get_nowait()
                if kind == "scan":
                    self.rows, self.history, note = value
                    self.busy = False
                    self.refresh_button.configure(state="normal")
                    self.refresh_views()
                    self.status.set(f"Znaleziono {len(self.rows)} artefaktów; {len(self.history)} zapisanych zdarzeń. {note}")
                elif kind == "verified":
                    # The background result may arrive after a tab/row/filter change.
                    ticket = value if isinstance(value, dict) else {}
                    active = self._verification_active
                    if not isinstance(active, dict) or any(
                        ticket.get(key) != active.get(key) for key in ("token", "path", "kind")
                    ):
                        # A stale worker must NOT unlock a newer ongoing verification.
                        continue
                    current = self.selected_artifact() if self._active_tab_source() == "artifact" else None
                    still_selected = (
                        current is not None
                        and str(current.path) == ticket.get("path")
                        and current.kind == ticket.get("kind")
                    )
                    self._verification_active = None
                    self.busy = False
                    self.refresh_button.configure(state="normal")
                    if not still_selected:
                        self._verified_selection_path = None
                        self.status.set(
                            "Kontrola zakończona dla innego zaznaczenia — nie zmieniono szczegółów "
                            "ani nie przypisano wyniku do bieżącej paczki."
                        )
                    elif ticket.get("ok"):
                        self._verified_selection_path = ticket["path"]
                        self.status.set("WALIDACJA PASS (Desktop): " + Path(ticket["path"]).name)
                        self.show_text(
                            f"PEŁNA KONTROLA DESKTOP: PASS\n"
                            f"Plik: {ticket['path']}\nSHA-256: {ticket['sha256']}\n"
                            "Zakres: ZIP, warianty i graf według walidatora eksportera.\n"
                            "NIE POTWIERDZA zgodności z Androidem ani wyników F4/final_test."
                        )
                    else:
                        self._verified_selection_path = None
                        self.status.set("WALIDACJA FAILED: " + str(ticket.get("detail") or "brak szczegółów"))
                else:
                    self.busy = False
                    self.refresh_button.configure(state="normal")
                    self.status.set("Błąd odczytu: " + str(value))
        except queue.Empty:
            pass
        try:
            self.window.after(150, self.poll)
        except tk.TclError:
            return

    @staticmethod
    def _selection_row(tree, lookup):
        """Resolve the selected OBJECT before Treeview rows are rebuilt."""
        try:
            selected = tree.selection()
            return lookup.get(selected[0]) if selected else None
        except (AttributeError, IndexError, tk.TclError):
            return None

    @staticmethod
    def _history_selection_key(event, *, raw: bool):
        if not isinstance(event, dict):
            return None
        if raw:
            event_id = str(event.get("event_id") or "").strip()
            return ("event", event_id) if event_id else None
        operation = str(event.get("operation") or "").strip()
        operation_id = str(event.get("operation_id") or "").strip()
        return ("operation", operation, operation_id) if operation and operation_id else None

    @staticmethod
    def _restore_row_by_identity(tree, lookup: dict, identity, key_fn):
        """Never restore by positional e0/a0: fresh scans may insert new rows."""
        if identity is None:
            return
        matches = [iid for iid, row in lookup.items() if key_fn(row) == identity]
        if len(matches) != 1:
            return
        try:
            tree.selection_set(matches[0])
            tree.focus(matches[0])
        except (AttributeError, tk.TclError):
            pass

    def refresh_views(self):
        phrase = self.filter_var.get().strip().casefold()
        current_artifact = self._selection_row(self.art_tree, self.by_iid)
        artifact_path = current_artifact.path if current_artifact is not None else None
        raw_view = bool(getattr(getattr(self, "show_raw_events", None), "get", lambda: False)())
        was_raw = bool(getattr(self, "_event_view_raw", raw_view))
        current_event = self._selection_row(self.event_tree, self.events_by_iid)
        event_key = (self._history_selection_key(current_event, raw=raw_view)
                     if raw_view == was_raw else None)
        self.by_iid.clear()
        for item in self.art_tree.get_children():
            self.art_tree.delete(item)
        for index, row in enumerate(self.rows):
            if phrase not in (row.role + " " + row.name + " " + row.model_id + " " + row.variants + " " + row.state + " " + row.path).casefold():
                continue
            iid = f"a{index}"
            self.by_iid[iid] = row
            size = f"{row.size_bytes / 1024 / 1024:.2f} MB"
            self.art_tree.insert("", "end", iid=iid, values=(row.role, row.name, row.variants,
                                size, row.modified_utc[:19], row.state))
        self.events_by_iid.clear()
        for item in self.event_tree.get_children():
            self.event_tree.delete(item)
        visible_history = self.history if raw_view else summarize_operations(self.history)
        view_status = getattr(self, "event_view_status", None)
        if view_status is not None:
            view_status.set(
                f"{len(visible_history)} pozycji / {len(self.history)} zdarzeń"
                + (" — pełny audyt" if raw_view else " — ostatni stan każdej operacji")
            )
        for index, event in enumerate(visible_history):
            if phrase not in json.dumps(event, ensure_ascii=False).casefold():
                continue
            iid = f"e{event.get('_source_index', index) if not raw_view else index}"
            self.events_by_iid[iid] = event
            operation_label = event.get("operation", "")
            if operation_label == "MODEL_CONVERSION":
                role = str((event.get("conversion") or {}).get("role") or "?")
                operation_label = f"Konwersja {role}"
            elif operation_label == "COMPLETE_PACKAGE_EXPORT":
                operation_label = "Eksport zestawu ALPR"
            elif operation_label == "SINGLE_MODEL_EXPORT":
                operation_label = "Eksport modelu"
            event_count = int(event.get("_event_count") or 0)
            if event_count > 1 and not raw_view:
                operation_label += f" ({event_count} zdarzeń)"
            outcome_label = {
                "STARTED_NO_RESULT": "BRAK WYNIKU",
                "INCONSISTENT_HISTORY": "SPRZECZNOŚĆ",
                "UNCONFIRMED": "NIEPOTWIERDZONE",
                "SUCCEEDED": "ZAKOŃCZONO",
                "FAILED": "BŁĄD",
                "STARTED": "ROZPOCZĘTO",
            }.get(str(event.get("outcome") or ""), str(event.get("outcome") or ""))
            self.event_tree.insert("", "end", iid=iid, values=(event.get("observed_utc", "")[:19],
                 operation_label, outcome_label,
                 Path(event.get("artifact_path") or "-").name,
                 event.get("artifact_sha256") or "-"))
        # Refreshing/filtering rebuilds the Treeviews; reapply the user's sort.
        self._apply_sort("artifacts")
        self._apply_sort("events")
        self._event_view_raw = raw_view
        self._restore_row_by_identity(self.art_tree, self.by_iid, artifact_path,
                                      lambda row: row.path)
        self._restore_row_by_identity(self.event_tree, self.events_by_iid, event_key,
                                      lambda row: self._history_selection_key(row, raw=raw_view))
        if getattr(self, "detail", None) is not None:
            self._on_tab_changed()

    def selected_artifact(self):
        return self._selection_row(self.art_tree, self.by_iid)

    def selected_event(self):
        return self._selection_row(self.event_tree, self.events_by_iid)

    def _active_tab_source(self) -> str:
        notebook = getattr(self, "notebook", None)
        if notebook is not None:
            try:
                selected = str(notebook.select())
                if selected == str(self.events_tab):
                    return "event"
                if selected == str(self.packages_tab):
                    return "artifact"
            except (AttributeError, tk.TclError):
                pass
        return "event" if getattr(self, "active_source", "artifact") == "event" else "artifact"

    def _on_tab_changed(self, _event=None):
        """Commands and details always follow the VISIBLE tab, not the last click."""
        self.active_source = self._active_tab_source()
        if self.active_source == "event":
            if self.selected_event() is not None:
                self.event_selected()
            else:
                self.show_text("Wybierz operację, aby wyświetlić jej historię i dowody.")
        elif self.selected_artifact() is not None:
            self.artifact_selected()
        else:
            self.show_text("Wybierz paczkę, aby zobaczyć manifest i proweniencję.")

    def _choice_problem(self, row) -> str:
        """Fast, read-only selection gate. NOT equivalent to full graph validation."""
        if not callable(self.on_choose) or self.choose_role not in {"MT", "MZ"}:
            return "Biblioteka nie jest w trybie wyboru modelu."
        if row is None or row.kind != "MODEL" or row.role != self.choose_role:
            return f"Wybierz pojedynczy model {self.choose_role} (.alprmodel), nie pakiet złożony."
        if row.state in {"REGISTERED_SHA_MISMATCH", "RESEARCH_SHA_MISMATCH"} or row.error:
            return "Pakiet ma błąd integralności lub manifestu."
        source = row.manifest.get("source") if isinstance(row.manifest, dict) else None
        declared_sha = str(source.get("checkpoint_sha256") or "").lower() if isinstance(source, dict) else ""
        if self.choose_checkpoint is None or not self.choose_checkpoint.is_file():
            return "Brak checkpointu wybranego w Centrum eksportu."
        try:
            checkpoint_sha = sha256_file(self.choose_checkpoint)
        except OSError:
            return "Nie można odczytać checkpointu do kontroli SHA."
        if not declared_sha or declared_sha != checkpoint_sha:
            return "SHA checkpointu pakietu nie odpowiada wybranemu modelowi w Centrum eksportu."
        input_spec = row.manifest.get("input") if isinstance(row.manifest, dict) else None
        if not isinstance(input_spec, dict) or self.choose_image_size is None:
            return "Nie można potwierdzić rozmiaru wejścia modelu."
        try:
            if int(input_spec.get("width") or 0) != int(self.choose_image_size) or int(input_spec.get("height") or 0) != int(self.choose_image_size):
                return "Rozmiar wejścia (imgsz) pakietu różni się od wybranego checkpointu."
        except (TypeError, ValueError):
            return "Błędny rozmiar wejścia w manifeście."
        if self.choose_role == "MT":
            # The operator explicitly chooses which variant to reuse. No silent
            # FP32 fallback when INT8 was requested (or vice versa).
            expected = getattr(self, 'choose_mt_precision', 'int8')
            if expected not in {'int8', 'fp32'}:
                return "MT: wybierz jawnie INT8 albo FP32."
            variants = row.manifest.get("variants")
            if (not isinstance(variants, list) or len(variants) != 1
                    or not isinstance(variants[0], dict) or variants[0].get("runtime") != "tflite"
                    or variants[0].get("precision") != expected):
                return f"MT: ponowne użycie wymaga pojedynczego wariantu TFLite {expected.upper()}."
            data_type = str(input_spec.get('data_type') or '').upper()
            if expected == 'fp32' and data_type != 'FLOAT32':
                return "MT: FP32 wymaga wejścia FLOAT32."
            if expected == 'int8' and data_type and data_type != 'INT8':
                return "MT: INT8 wymaga wejścia signed INT8."
        if self.choose_role == "MZ":
            expected = getattr(self, "choose_mz_precision", "int8")
            if expected not in {"int8", "fp32"}:
                return "MZ: wybierz jawnie INT8 albo FP32."
            variants = row.manifest.get("variants")
            if (not isinstance(variants, list) or len(variants) != 1
                    or not isinstance(variants[0], dict) or variants[0].get("runtime") != "tflite"
                    or str(variants[0].get("precision") or "").lower() != expected):
                return f"MZ: dla F4 wymagany pojedynczy wariant TFLite {expected.upper()}."
            input_type = str(input_spec.get("data_type") or "").upper()
            # Discovery is a prefilter: legacy INT8 manifests may omit data_type.
            # The mandatory exporter full-graph validator rejects incorrect dtype.
            if ((expected == "fp32" and input_type != "FLOAT32")
                    or (expected == "int8" and input_type and input_type != "INT8")):
                return f"MZ: {expected.upper()} wymaga zgodnego typu wejścia grafu."
        return ""

    def choose_for_export(self):
        if self._active_tab_source() == "event":
            return messagebox.showwarning(
                "Wybór modelu z biblioteki", "Wybierz paczkę w zakładce Pakiety i modele.",
                parent=self.window,
            )
        row = self.selected_artifact()
        problem = self._choice_problem(row)
        if problem:
            return messagebox.showwarning("Wybór modelu z biblioteki", problem, parent=self.window)
        try:
            # UI binds only the path. Export preflight owns authoritative validation.
            self.on_choose(Path(row.path))
        except Exception as exc:
            return messagebox.showerror("Wybór modelu z biblioteki", str(exc), parent=self.window)
        self.close()

    def show_text(self, value: str):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", value)
        self.detail.configure(state="disabled")

    def artifact_selected(self, _event=None):
        if self._active_tab_source() != "artifact":
            return
        self.active_source = "artifact"
        row = self.selected_artifact()
        previous = getattr(self, "_verified_selection_path", None)
        if previous and (row is None or str(row.path) != previous):
            self._verified_selection_path = None
            if getattr(self, "status", None) is not None:
                self.status.set("Zmieniono wybór. Nowa paczka nie przeszła jeszcze pełnej kontroli.")
        if row:
            data = {
                "UWAGA": "ODCZYT Z MANIFESTU — NIE JEST CERTYFIKATEM PRECISION ANI ANDROID",
                "state": row.state, "error": row.error, "path": row.path,
                "size_bytes": row.size_bytes, "schema": row.schema,
                "role": row.role, "model_id": row.model_id, "variants": row.variants,
                "manifest": row.manifest,
                "child_metadata": row.child_metadata,
                "child_metadata_authority": "SHA manifestu potomnego, nie pełna walidacja TFLite",
            }
            self.show_text(json.dumps(data, ensure_ascii=False, indent=2)[:160000])

    def event_selected(self, _event=None):
        if self._active_tab_source() != "event":
            return
        self.active_source = "event"
        event = self.selected_event()
        if event:
            self.show_text(json.dumps(event, ensure_ascii=False, indent=2))

    def active_path(self) -> Path | None:
        if self._active_tab_source() == "event":
            event = self.selected_event()
            return Path(event["artifact_path"]) if event and event.get("artifact_path") else None
        row = self.selected_artifact()
        return Path(row.path) if row else None

    def copy_path(self):
        path = self.active_path()
        if not path:
            return messagebox.showinfo("Biblioteka", "Najpierw wybierz plik lub zdarzenie.", parent=self.window)
        self.window.clipboard_clear()
        self.window.clipboard_append(str(path))
        self.status.set("Skopiowano ścieżkę: " + str(path))

    def open_location(self):
        path = self.active_path()
        if not path or not path.exists():
            return messagebox.showwarning("Biblioteka", "Brak istniejącego pliku do otwarcia.", parent=self.window)
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", "/select,", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError as exc:
            messagebox.showerror("Biblioteka", str(exc), parent=self.window)

    def validate_selected(self):
        if self._active_tab_source() == "event":
            return messagebox.showwarning(
                "Biblioteka", "Wybierz paczkę w zakładce Pakiety i modele.", parent=self.window,
            )
        row = self.selected_artifact()
        if not row or row.kind not in ("MODEL", "PACKAGE"):
            return messagebox.showwarning("Biblioteka", "Wskaż właściwy pakiet .alprmodel.", parent=self.window)
        if self.busy:
            return
        self.busy = True
        self.refresh_button.configure(state="disabled")
        self.status.set("Waliduję rzeczywistą paczkę i jej SHA-256. Może to chwilę potrwać...")
        self._verification_seq = int(getattr(self, "_verification_seq", 0)) + 1
        token = self._verification_seq
        path, selected_kind = str(row.path), row.kind
        self._verification_active = {"token": token, "path": path, "kind": selected_kind}
        self._verified_selection_path = None

        def work():
            try:
                from ..exporters.mobile_model_exporter import MobileModelExporter, MobileAlprPackageExporter
                proof = verify_unchanged_mobile_package(
                    Path(path), kind=selected_kind,
                    model_validator=MobileModelExporter().validate_package,
                    bundle_validator=MobileAlprPackageExporter().validate_package,
                )
                self.pipe.put(("verified", {
                    "token": token, "path": path, "kind": selected_kind, "ok": True,
                    "sha256": proof["sha256"], "detail": "Weryfikator Desktop: PASS",
                }))
            except Exception as exc:
                self.pipe.put(("verified", {
                    "token": token, "path": path, "kind": selected_kind, "ok": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }))
        threading.Thread(target=work, daemon=True, name="z4-artifact-full-verifier").start()


def open_mobile_artifact_library(parent, *, packages_root=None, repo_root=None,
                                 on_choose=None, choose_role=None,
                                 choose_checkpoint=None, choose_image_size=None,
                                 choose_mt_precision="int8", choose_mz_precision="int8"):
    from ..config import CONFIG
    root = Path(packages_root) if packages_root else Path(CONFIG.DIR_6_MODELS_MOBILE_PACKAGES)
    repo = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    return MobileArtifactLibrary(
        parent, packages_root=root, repo_root=repo,
        on_choose=on_choose, choose_role=choose_role,
        choose_checkpoint=choose_checkpoint, choose_image_size=choose_image_size,
        choose_mt_precision=choose_mt_precision, choose_mz_precision=choose_mz_precision,
    ).window
