"""Interaktywny przegląd nazw zasobu O."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Iterable

try:
    from PIL import Image, ImageOps, ImageTk
except Exception:  # pragma: no cover
    Image = None
    ImageOps = None
    ImageTk = None

from .zoomable_canvas import ZoomableCanvas
from .app_window_recovery import restore_parent_after_modal

from ..config import CONFIG
from ..source_filename_contract import (
    parse_source_image_filename,
    validate_source_image_directory,
    validate_source_image_paths,
)


@dataclass(frozen=True)
class SourceReviewApplyResult:
    ok: bool
    renamed: int = 0
    rejected: int = 0
    quarantine_dir: str = ""
    error: str = ""


@dataclass(frozen=True)
class SourceReviewSelectionResult:
    ok: bool
    accepted_paths: tuple[Path, ...] = ()
    renamed: int = 0
    rejected: int = 0
    quarantine_dir: str = ""


@dataclass(frozen=True)
class SourceReviewRow:
    path: Path
    display_name: str
    problem: str
    action: str
    unresolved: bool


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def apply_source_review_actions(
    root: Path | str,
    *,
    rename_stems: dict[str, str] | None = None,
    rejected_paths: set[str] | None = None,
) -> SourceReviewApplyResult:
    base = Path(root)
    rename_stems = dict(rename_stems or {})
    rejected = {str(Path(item)) for item in (rejected_paths or set())}
    quarantine = base.parent / f"{base.name}__odrzucone_nazwy"
    staged: list[tuple[Path, Path]] = []
    targets: set[str] = set()

    try:
        for raw, new_stem in rename_stems.items():
            source = Path(raw)
            if str(source) in rejected:
                continue
            if not source.exists() or not source.is_file():
                return SourceReviewApplyResult(False, error=f"Plik nie istnieje: {source}")
            target = source.with_name(str(new_stem or "").strip() + source.suffix)
            parsed = parse_source_image_filename(target.name)
            if not parsed.valid:
                return SourceReviewApplyResult(
                    False,
                    error=f"Niepoprawna nowa nazwa {target.name}: " + "; ".join(parsed.errors),
                )
            key = str(target.absolute()).casefold()
            if key in targets:
                return SourceReviewApplyResult(False, error=f"Powtórzona nazwa docelowa: {target.name}")
            targets.add(key)
            if target.exists():
                try:
                    same = target.resolve() == source.resolve()
                except Exception:
                    same = target == source
                if not same:
                    return SourceReviewApplyResult(False, error=f"Plik docelowy już istnieje: {target}")
            staged.append((source, target))

        temp_pairs: list[tuple[Path, Path]] = []
        renamed = 0
        for index, (source, target) in enumerate(staged):
            try:
                same = source.resolve() == target.resolve()
            except Exception:
                same = source == target
            if same:
                continue
            temp = _unique_destination(
                source.with_name(f".__alpr_rename_{index:04d}__{source.name}")
            )
            source.rename(temp)
            temp_pairs.append((temp, target))
        for temp, target in temp_pairs:
            temp.rename(target)
            renamed += 1

        rejected_count = 0
        for raw in sorted(rejected):
            source = Path(raw)
            if not source.exists() or not source.is_file():
                continue
            try:
                rel = source.resolve().relative_to(base.resolve())
            except Exception:
                rel = Path(source.name)
            destination = _unique_destination(quarantine / rel)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            rejected_count += 1

        return SourceReviewApplyResult(
            True,
            renamed=renamed,
            rejected=rejected_count,
            quarantine_dir=str(quarantine) if rejected_count else "",
        )
    except Exception as exc:
        return SourceReviewApplyResult(False, error=str(exc))


def build_source_review_rows(
    paths: Iterable[Path | str],
    *,
    rename_stems: dict[str, str] | None = None,
    rejected_paths: set[str] | None = None,
    root: Path | None = None,
) -> tuple[SourceReviewRow, ...]:
    rename_stems = dict(rename_stems or {})
    rejected = {str(Path(item)) for item in (rejected_paths or set())}
    rows: list[SourceReviewRow] = []

    for raw in paths:
        path = Path(raw)
        key = str(path)
        original = parse_source_image_filename(path.name)
        planned_stem = str(rename_stems.get(key) or "").strip()
        is_rejected = key in rejected
        if original.valid and not planned_stem and not is_rejected:
            continue

        display = path.name
        if root is not None:
            try:
                display = str(path.relative_to(root))
            except Exception:
                pass

        if is_rejected:
            problem = "; ".join(original.errors) or "Plik odrzucony z zasobu."
            action = "ODRZUĆ"
            unresolved = False
        elif planned_stem:
            candidate = planned_stem + path.suffix
            parsed = parse_source_image_filename(candidate)
            problem = (
                "✓ nowa nazwa spełnia kontrakt"
                if parsed.valid
                else ("; ".join(parsed.errors) or "Nowa nazwa jest błędna.")
            )
            action = f"→ {candidate}"
            unresolved = not parsed.valid
        else:
            problem = "; ".join(original.errors) or "Błędna nazwa"
            action = "DO DECYZJI"
            unresolved = True

        rows.append(SourceReviewRow(path, display, problem, action, unresolved))

    return tuple(rows)


def _natural_review_key(value) -> tuple:
    import re

    text = str(value or "").strip().casefold()
    parts = re.split(r"(\d+)", text)
    return tuple(
        int(part) if part.isdigit() else part
        for part in parts
        if part != ""
    )


def source_review_sort_key(
    row: SourceReviewRow,
    column: str,
    *,
    display_name: str | None = None,
) -> tuple:
    """Klucz sortowania tabeli podglądu/korekty nazw."""
    key = str(column or "").strip().lower()
    if key in {"#0", "file", "name"}:
        return _natural_review_key(display_name or row.display_name)
    if key == "problem":
        return (
            0 if row.unresolved else 1,
            _natural_review_key(row.problem),
            _natural_review_key(display_name or row.display_name),
        )
    if key == "action":
        action = str(row.action or "")
        upper = action.upper()
        if "DO DECYZJI" in upper:
            rank = 0
        elif action.startswith("→"):
            rank = 1
        elif "ODRZUĆ" in upper:
            rank = 2
        else:
            rank = 3
        return (
            rank,
            _natural_review_key(action),
            _natural_review_key(display_name or row.display_name),
        )
    return _natural_review_key(display_name or row.display_name)


def source_review_rejectable_paths(
    paths: Iterable[Path | str],
    *,
    rename_stems: dict[str, str] | None = None,
    rejected_paths: set[str] | None = None,
    root: Path | None = None,
) -> tuple[Path, ...]:
    """Zwróć tylko pozycje nadal nierozwiązane po uwzględnieniu planowanych zmian."""
    rows = build_source_review_rows(
        paths,
        rename_stems=rename_stems,
        rejected_paths=rejected_paths,
        root=root,
    )
    return tuple(row.path for row in rows if row.unresolved)


class _SourceFilenameReviewDialog:
    def __init__(
        self,
        parent,
        root: Path,
        *,
        recursive: bool,
        title: str,
        selected_paths: Iterable[Path | str] | None = None,
        audit_next_step: bool = False,
    ) -> None:
        self.parent = parent
        self.audit_next_step = bool(audit_next_step)
        self._previous_grab = parent.grab_current()
        self._closed = False
        self.root = Path(root)
        self.recursive = bool(recursive)
        self.result = False
        self.selection_result = SourceReviewSelectionResult(False)
        self.rename_stems: dict[str, str] = {}
        self.rejected_paths: set[str] = set()
        self._selected_paths = (
            tuple(Path(item) for item in selected_paths)
            if selected_paths is not None
            else None
        )
        self._preview_photo = None
        self._preview_zoom_job = None
        self._sort_column = "#0"
        self._sort_reverse = False
        self._edit_entry = None
        self._edit_iid = ""
        self._review_rows_by_iid = {}

        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title(title)
        # Pełne okno systemowe: bez transient/overrideredirect.
        width = min(1160, max(900, self.window.winfo_screenwidth() - 80))
        height = min(760, max(600, self.window.winfo_screenheight() - 100))
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(900, 600)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.bind("<Destroy>", self._on_window_destroy, add="+")
        self._build()
        self._reload()
        self._present()

    def _present(self) -> None:
        # A newly opened full system window must not stay iconic or behind its owner.
        self.window.deiconify()
        self.window.lift()
        self.window.update_idletasks()
        if not self.window.winfo_viewable():
            self.window.wait_visibility()
        self.window.grab_set()
        self.tree.focus_force()

    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header, text="Kontrola nazw plików", font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Zasady i skróty", style="Toolbutton",
                   command=self._show_review_help).grid(row=0, column=1, sticky="e")

        self.summary_var = tk.StringVar(self.window)
        self._wrapped_label(outer, textvariable=self.summary_var).grid(
            row=1, column=0, sticky="ew", pady=(4, 12))

        # One aligned bar: file decisions on the left, viewing tools on the right.
        toolbar = ttk.Frame(outer)
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(3, weight=1)
        self.rename_button = ttk.Button(toolbar, text="Zmień nazwę",
                                       command=self._plan_rename, state=tk.DISABLED)
        self.rename_button.grid(row=0, column=0, padx=(0, 6))
        self.reject_button = ttk.Button(toolbar, text="Odrzuć plik",
                                       command=self._reject_selected, state=tk.DISABLED)
        self.reject_button.grid(row=0, column=1, padx=(0, 6))
        self.more_menu = tk.Menu(self.window, tearoff=False)
        self.more_menu.add_command(label="Odrzuć pozostałe błędne", command=self._reject_all)
        ttk.Menubutton(toolbar, text="Więcej", menu=self.more_menu).grid(row=0, column=2)

        view_tools = ttk.Frame(toolbar)
        view_tools.grid(row=0, column=4, sticky="e")
        self.preview_zoom_var = tk.StringVar(self.window, "100%")
        ttk.Button(view_tools, text="−", width=3, style="Toolbutton",
                   command=lambda: self._preview_zoom(1 / 1.25)).pack(side=tk.LEFT)
        ttk.Label(view_tools, textvariable=self.preview_zoom_var, width=6, anchor="center").pack(side=tk.LEFT)
        ttk.Button(view_tools, text="+", width=3, style="Toolbutton",
                   command=lambda: self._preview_zoom(1.25)).pack(side=tk.LEFT)
        ttk.Button(view_tools, text="Dopasuj", style="Toolbutton",
                   command=self._preview_fit).pack(side=tk.LEFT, padx=(6, 0))

        self.panes = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        self.panes.grid(row=3, column=0, sticky="nsew")
        self._pane_fraction = 0.40
        self.panes.bind("<Configure>", self._fit_review_panes, add="+")
        self.panes.bind("<ButtonRelease-1>", self._remember_review_panes, add="+")
        left = ttk.Frame(self.panes, padding=(0, 0, 12, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        right = ttk.Frame(self.panes, padding=(12, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.panes.add(left, weight=2)
        self.panes.add(right, weight=3)

        ttk.Label(left, text="Pliki do sprawdzenia", style="PanelMuted.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.tree = ttk.Treeview(
            left, columns=("problem", "action"), displaycolumns=("action",),
            show="tree headings", selectmode="browse", height=6,
        )
        self._heading_titles = {"#0": "Plik", "problem": "Problem z nazwą", "action": "Decyzja"}
        for column, title in self._heading_titles.items():
            self.tree.heading(column, text=title, command=lambda col=column: self._sort_by_column(col))
        self.tree.column("#0", width=230, minwidth=150, stretch=True)
        self.tree.column("action", width=135, minwidth=110, stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.tree.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=horizontal.set)

        self.problem_var = tk.StringVar(self.window, "Wybierz plik, aby zobaczyć problem z nazwą.")
        self._wrapped_label(left, textvariable=self.problem_var).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.tree.bind("<<TreeviewSelect>>", self._on_select, add="+")
        self.tree.bind("<Return>", self._begin_inline_edit, add="+")
        self.tree.bind("<F2>", self._begin_inline_edit, add="+")
        self.tree.bind("<Up>", lambda _event: self._move_selection(-1), add="+")
        self.tree.bind("<Down>", lambda _event: self._move_selection(1), add="+")
        self.tree.bind("<Double-1>", self._on_tree_double_click, add="+")

        self.preview_caption_var = tk.StringVar(self.window, "Podgląd obrazu")
        self._wrapped_label(right, textvariable=self.preview_caption_var).grid(
            row=0, column=0, sticky="ew", pady=(0, 6))
        self.preview = ZoomableCanvas(right, highlightthickness=0, width=1, height=1)
        self.preview.grid(row=1, column=0, sticky="nsew")
        self.preview.show_info = False
        self.preview.reset_shortcut_enabled = True
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.preview.bind(sequence, self._on_preview_zoom_event, add="+")

        ttk.Separator(outer).grid(row=4, column=0, sticky="ew", pady=(12, 10))
        footer = ttk.Frame(outer)
        footer.grid(row=5, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(self.window)
        self._wrapped_label(footer, textvariable=self.status_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 16))
        ttk.Button(footer, text="Anuluj", command=self._cancel).grid(
            row=0, column=1, padx=(0, 8))
        self.apply_button = ttk.Button(
            footer, text="Zapisz i kontynuuj", command=self._apply, style="Accent.TButton")
        self.apply_button.grid(row=0, column=2)

    @staticmethod
    def _wrapped_label(parent, **kwargs):
        label = ttk.Label(parent, width=1, wraplength=400, justify=tk.LEFT,
                          style="PanelMuted.TLabel", **kwargs)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(80, event.width)), add="+")
        return label

    def _fit_review_panes(self, event=None):
        width = self.panes.winfo_width()
        if width > 1:
            self.panes.sashpos(0, max(260, min(width - 320, int(width * self._pane_fraction))))

    def _remember_review_panes(self, _event=None):
        width = self.panes.winfo_width()
        if width > 1:
            self._pane_fraction = self.panes.sashpos(0) / width

    def _show_review_help(self):
        messagebox.showinfo(
            "Kontrola nazw · zasady i skróty",
            f"Źródło: {self.root}\n\n"
            "Enter / F2 / dwuklik nazwy — edycja\n"
            "Enter — zatwierdź nazwę · Esc — anuluj edycję\n"
            "↑ / ↓ — poprzedni / następny plik\n"
            "Rolka / + / − — zoom · przeciąganie — przesunięcie obrazu\n"
            "Dopasuj / Home / R — cały obraz\n\n"
            "Dopiero „Zapisz i kontynuuj” zmienia nazwy plików źródłowych. "
            "Odrzucone pliki zostaną przeniesione do sąsiedniego katalogu __odrzucone_nazwy. "
            "„Odrzuć pozostałe błędne” zachowuje poprawne, zaplanowane nazwy."
            + (" Usunięcie draftu nie cofa zmian w źródłach. Audyt niezależności wykonasz "
               "po dodaniu obrazów przyciskiem „Sprawdź niezależność puli”." if self.audit_next_step else ""),
            parent=self.window,
        )

    def _iter_current_images(self) -> list[Path]:
        allowed = {str(ext).lower() for ext in CONFIG.IMAGE_EXTENSIONS}
        if self._selected_paths is not None:
            return sorted(
                [
                    path for path in self._selected_paths
                    if path.exists() and path.is_file() and path.suffix.lower() in allowed
                ],
                key=lambda item: item.as_posix().casefold(),
            )
        try:
            iterator = self.root.rglob("*") if self.recursive else self.root.iterdir()
            return sorted(
                [
                    path for path in iterator
                    if path.is_file() and path.suffix.lower() in allowed
                ],
                key=lambda item: item.as_posix().casefold(),
            )
        except Exception:
            return []

    def _reload(self, *, select_key: str | None = None) -> None:
        previous = str(select_key or "")
        if not previous:
            selected = self.tree.selection()
            previous = str(selected[0]) if selected else ""

        self._cancel_inline_edit(refocus=False)

        paths = self._iter_current_images()
        rows = list(
            build_source_review_rows(
                paths,
                rename_stems=self.rename_stems,
                rejected_paths=self.rejected_paths,
                root=self.root,
            )
        )
        rows = self._sorted_review_rows(rows)
        self._review_rows_by_iid = {
            str(row.path): row
            for row in rows
        }

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for row in rows:
            iid = str(row.path)
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                text=self._display_name_for_row(row),
                values=(row.problem, {"DO DECYZJI": "Do poprawy", "ODRZUĆ": "Odrzucony"}.get(row.action, row.action)),
            )

        unresolved = sum(1 for row in rows if row.unresolved)
        self.summary_var.set(
            f"Obrazy: {len(paths)}  ·  nazwy do poprawy: {unresolved}  ·  "
            f"Zmiany: {len(self.rename_stems)}  ·  Odrzucone: {len(self.rejected_paths)}"
            + ("\nDalej w PZ3: „Sprawdź niezależność puli”." if self.audit_next_step else "")
        )

        if unresolved:
            self.status_var.set(
                "Zmień nazwę lub odrzuć plik z błędną nazwą."
            )
            try:
                self.apply_button.configure(state=tk.DISABLED)
            except Exception:
                pass
        else:
            self.status_var.set(
                "Gotowe do zapisania zmian."
            )
            try:
                self.apply_button.configure(state=tk.NORMAL)
            except Exception:
                pass

        self._refresh_sort_headings()

        target = ""
        if previous and self.tree.exists(previous):
            target = previous
        elif rows:
            target = str(rows[0].path)

        if target:
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)
            self._on_select()
        else:
            self._on_select()
            self._preview_clear(
                "Brak problemów z nazwami plików."
            )

    def _display_name_for_row(self, row: SourceReviewRow) -> str:
        key = str(row.path)
        stem = str(self.rename_stems.get(key) or "").strip()
        if not stem:
            return row.display_name

        candidate = stem + row.path.suffix
        try:
            shown = Path(row.display_name)
            return str(shown.with_name(candidate))
        except Exception:
            return candidate

    def _sorted_review_rows(
        self,
        rows: Iterable[SourceReviewRow],
    ) -> list[SourceReviewRow]:
        return sorted(
            list(rows),
            key=lambda row: source_review_sort_key(
                row,
                self._sort_column,
                display_name=self._display_name_for_row(row),
            ),
            reverse=bool(self._sort_reverse),
        )

    def _refresh_sort_headings(self) -> None:
        for column, title in self._heading_titles.items():
            suffix = ""
            if column == self._sort_column:
                suffix = " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(
                column,
                text=title + suffix,
                command=lambda col=column: self._sort_by_column(col),
            )

    def _sort_by_column(self, column: str) -> None:
        selected = self.tree.selection()
        selected_key = str(selected[0]) if selected else ""
        self._cancel_inline_edit(refocus=False)

        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False

        self._reload(select_key=selected_key)

    def _move_selection(self, delta: int):
        if getattr(self, "_edit_entry", None) is not None:
            return None

        items = list(self.tree.get_children(""))
        if not items:
            return "break"

        selected = self.tree.selection()
        current = str(selected[0]) if selected else ""
        try:
            index = items.index(current)
        except ValueError:
            index = 0 if delta >= 0 else len(items) - 1

        target_index = max(0, min(len(items) - 1, index + int(delta)))
        target = str(items[target_index])

        self.tree.selection_set(target)
        self.tree.focus(target)
        self.tree.see(target)
        self._on_select()
        return "break"

    def _on_tree_double_click(self, event):
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        region = self.tree.identify_region(event.x, event.y)
        if not row or column != "#0" or region not in {"tree", "cell"}:
            return None

        self.tree.selection_set(row)
        self.tree.focus(row)
        self.tree.see(row)
        self._on_select()
        return self._begin_inline_edit()

    def _begin_inline_edit(self, _event=None):
        path = self._selected_path()
        if path is None:
            return "break"

        self._cancel_inline_edit(refocus=False)
        iid = str(path)

        try:
            bbox = self.tree.bbox(iid, "#0")
        except Exception:
            bbox = ()

        if not bbox:
            self.tree.see(iid)
            self.tree.update_idletasks()
            try:
                bbox = self.tree.bbox(iid, "#0")
            except Exception:
                bbox = ()

        if not bbox:
            return "break"

        x, y, width, height = bbox
        planned = str(self.rename_stems.get(iid) or "").strip()
        value = planned + path.suffix if planned else path.name

        entry = ttk.Entry(self.tree)
        entry.insert(0, value)
        entry.place(
            x=x,
            y=y,
            width=max(80, width),
            height=max(20, height),
        )
        self._edit_entry = entry
        self._edit_iid = iid

        suffix = str(path.suffix or "")
        stem_end = (
            max(0, len(value) - len(suffix))
            if suffix and value.casefold().endswith(suffix.casefold())
            else len(value)
        )
        entry.selection_range(0, stem_end)
        entry.icursor(stem_end)
        entry.focus_set()

        entry.bind("<Return>", self._commit_inline_edit, add="+")
        entry.bind("<Escape>", self._cancel_inline_edit, add="+")
        return "break"

    def _normalize_inline_candidate(
        self,
        path: Path,
        raw_value: str,
    ) -> tuple[str, str]:
        raw = str(raw_value or "").strip()
        if not raw:
            raise ValueError("Nowa nazwa nie może być pusta.")

        if Path(raw).name != raw:
            raise ValueError(
                "W polu nazwy nie podawaj ścieżki ani katalogu."
            )

        suffix = str(path.suffix or "")
        candidate = raw
        if suffix and not candidate.casefold().endswith(suffix.casefold()):
            candidate += suffix

        candidate_path = Path(candidate)
        if candidate_path.suffix.casefold() != suffix.casefold():
            raise ValueError(
                f"Rozszerzenie pliku musi pozostać {suffix}."
            )

        parsed = parse_source_image_filename(candidate)
        if not parsed.valid:
            raise ValueError(
                "; ".join(parsed.errors)
                or "Nowa nazwa nie spełnia kontraktu."
            )

        return candidate_path.stem, candidate

    def _planned_name_collision(
        self,
        path: Path,
        candidate: str,
    ) -> Path | None:
        candidate_key = str(
            path.with_name(candidate).absolute()
        ).casefold()

        for raw, stem in self.rename_stems.items():
            other = Path(raw)
            if str(other) == str(path):
                continue
            other_target = other.with_name(
                str(stem).strip() + other.suffix
            )
            if str(other_target.absolute()).casefold() == candidate_key:
                return other

        target = path.with_name(candidate)
        if target.exists():
            try:
                same = target.resolve() == path.resolve()
            except Exception:
                same = target == path
            if not same:
                return target

        return None

    def _commit_inline_edit(self, _event=None):
        entry = getattr(self, "_edit_entry", None)
        iid = str(getattr(self, "_edit_iid", "") or "")
        if entry is None or not iid:
            return "break"

        path = Path(iid)
        try:
            stem, candidate = self._normalize_inline_candidate(
                path,
                entry.get(),
            )
        except Exception as exc:
            messagebox.showerror(
                "Nazwa nadal nie spełnia kontraktu",
                str(exc),
                parent=self.window,
            )
            try:
                entry.focus_set()
                entry.selection_range(0, tk.END)
            except Exception:
                pass
            return "break"

        collision = self._planned_name_collision(path, candidate)
        if collision is not None:
            messagebox.showerror(
                "Kolizja nazwy",
                (
                    "Taka nazwa jest już używana albo zaplanowana:\n"
                    f"{candidate}"
                ),
                parent=self.window,
            )
            try:
                entry.focus_set()
                entry.selection_range(0, tk.END)
            except Exception:
                pass
            return "break"

        key = str(path)
        self.rejected_paths.discard(key)
        self.rename_stems[key] = stem
        self._cancel_inline_edit(refocus=False)
        self._reload(select_key=key)
        try:
            self.tree.focus_set()
        except Exception:
            pass
        return "break"

    def _cancel_inline_edit(
        self,
        _event=None,
        *,
        refocus: bool = True,
    ):
        entry = getattr(self, "_edit_entry", None)
        self._edit_entry = None
        self._edit_iid = ""
        if entry is not None:
            try:
                entry.destroy()
            except Exception:
                pass
        if refocus:
            try:
                self.tree.focus_set()
            except Exception:
                pass
        return "break"

    def _selected_path(self) -> Path | None:
        selected = self.tree.selection()
        return Path(selected[0]) if selected else None

    def _on_select(self, _event=None) -> None:
        path = self._selected_path()
        row = self._review_rows_by_iid.get(str(path)) if path is not None else None
        self.problem_var.set(row.problem if row is not None else "Wybierz plik z listy.")
        self.rename_button.configure(state=tk.NORMAL if path is not None else tk.DISABLED)
        self.reject_button.configure(
            state=tk.NORMAL if path is not None and str(path) not in self.rejected_paths else tk.DISABLED)
        if path is None:
            return

        if (
            getattr(self, "_edit_entry", None) is not None
            and getattr(self, "_edit_iid", "")
            and self._edit_iid != str(path)
        ):
            self._cancel_inline_edit(refocus=False)

        self._show_preview(path)

    def _preview_clear(self, message: str = "") -> None:
        try:
            self.preview.clear_image()
        except Exception:
            pass
        try:
            self.preview_zoom_var.set("—")
        except Exception:
            pass
        try:
            self.preview_caption_var.set(str(message or ""))
        except Exception:
            pass

    def _update_preview_zoom_label(self) -> None:
        try:
            if self.preview.original_image is None:
                self.preview_zoom_var.set("—")
                return
            zoom = float(self.preview.get_zoom_level())
            self.preview_zoom_var.set(f"{zoom * 100:.0f}%")
        except Exception:
            pass

    def _on_window_destroy(self, event):
        if event.widget == self.window and self._preview_zoom_job is not None:
            self.window.after_cancel(self._preview_zoom_job)
            self._preview_zoom_job = None

    def _schedule_preview_zoom_label(self, delay):
        if self._preview_zoom_job is not None:
            self.window.after_cancel(self._preview_zoom_job)

        def update():
            self._preview_zoom_job = None
            self._update_preview_zoom_label()

        self._preview_zoom_job = self.window.after(delay, update)

    def _on_preview_zoom_event(self, _event=None):
        try:
            self._schedule_preview_zoom_label(170)
        except Exception:
            pass
        return None

    def _preview_zoom(self, factor: float) -> None:
        try:
            if self.preview.original_image is None:
                return

            self.preview.update_idletasks()
            current = float(self.preview.get_zoom_level())
            target = max(
                float(self.preview.min_zoom),
                min(
                    float(self.preview.max_zoom),
                    current * float(factor),
                ),
            )

            width = max(1.0, float(self.preview.winfo_width()))
            height = max(1.0, float(self.preview.winfo_height()))
            animate = getattr(
                self.preview,
                "_animate_zoom_to",
                None,
            )
            if callable(animate):
                animate(
                    width / 2.0,
                    height / 2.0,
                    target,
                    duration_ms=120,
                )
            else:
                self.preview.set_zoom_level(target)

            self._schedule_preview_zoom_label(140)
        except Exception:
            pass

    def _preview_fit(self) -> None:
        try:
            if self.preview.original_image is None:
                return
            self.preview.fit_to_view()
            self._schedule_preview_zoom_label(30)
        except Exception:
            pass

    def _show_preview(self, path: Path) -> None:
        if Image is None or ImageOps is None:
            self._preview_clear(
                f"{path.name}\nPodgląd obrazu jest niedostępny."
            )
            return

        try:
            with Image.open(path) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB").copy()

            self.preview.update_idletasks()
            self.preview.set_image_fit_to_view(image)
            self.preview_caption_var.set(path.name)
            self._schedule_preview_zoom_label(40)
        except Exception as exc:
            self._preview_clear(
                f"{path.name}\nNie można wyświetlić podglądu: {exc}"
            )

    def _plan_rename(self) -> None:
        """Kompatybilność: edycja nazwy odbywa się teraz inline."""
        self._begin_inline_edit()

    def _reject_selected(self) -> None:
        self._cancel_inline_edit(refocus=False)
        path = self._selected_path()
        if path is None:
            return
        key = str(path)
        self.rename_stems.pop(key, None)
        self.rejected_paths.add(key)
        self._reload(select_key=key)

    def _reject_all(self) -> None:
        self._cancel_inline_edit(refocus=False)

        rejectable = source_review_rejectable_paths(
            self._iter_current_images(),
            rename_stems=self.rename_stems,
            rejected_paths=self.rejected_paths,
            root=self.root,
        )

        for path in rejectable:
            key = str(path)
            self.rename_stems.pop(key, None)
            self.rejected_paths.add(key)

        self._reload()

    def _planned_paths(self, originals: Iterable[Path]) -> tuple[Path, ...]:
        accepted = []
        for path in originals:
            key = str(path)
            if key in self.rejected_paths:
                continue
            stem = str(self.rename_stems.get(key) or "").strip()
            accepted.append(path.with_name(stem + path.suffix) if stem else path)
        return tuple(accepted)

    def _apply(self) -> None:
        # Clicking the footer must not discard an unfinished inline edit.
        if self._edit_entry is not None:
            self._commit_inline_edit()
            if self._edit_entry is not None:
                return
        rows = build_source_review_rows(
            self._iter_current_images(),
            rename_stems=self.rename_stems,
            rejected_paths=self.rejected_paths,
            root=self.root,
        )
        unresolved = [row for row in rows if row.unresolved]
        if unresolved:
            messagebox.showwarning(
                "Nie można jeszcze kontynuować",
                f"Pozostało {len(unresolved)} plików bez decyzji.",
                parent=self.window,
            )
            return

        originals = tuple(self._iter_current_images())
        planned = self._planned_paths(originals)
        result = apply_source_review_actions(
            self.root,
            rename_stems=self.rename_stems,
            rejected_paths=self.rejected_paths,
        )
        if not result.ok:
            messagebox.showerror("Nie udało się zastosować zmian", result.error, parent=self.window)
            return

        if self._selected_paths is None:
            report = validate_source_image_directory(self.root, recursive=self.recursive)
            valid = report.valid
            accepted = tuple(self._iter_current_images())
        else:
            accepted = tuple(path for path in planned if path.exists() and path.is_file())
            report = validate_source_image_paths(accepted)
            valid = report.invalid_count == 0

        if not valid:
            messagebox.showerror(
                "Zasób nadal nie spełnia kontraktu",
                f"Pozostało niepoprawnych plików: {report.invalid_count}",
                parent=self.window,
            )
            return

        self.result = True
        self.selection_result = SourceReviewSelectionResult(
            True,
            accepted_paths=accepted,
            renamed=result.renamed,
            rejected=result.rejected,
            quarantine_dir=result.quarantine_dir,
        )
        self._close()

    def _cancel(self) -> None:
        self.result = False
        self.selection_result = SourceReviewSelectionResult(False)
        self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.window.grab_release()
        self.window.destroy()
        restore_parent_after_modal(self.parent, self._previous_grab)

    def show(self) -> bool:
        self._present()
        self.window.wait_window()
        return self.result

    def show_selection(self) -> SourceReviewSelectionResult:
        self._present()
        self.window.wait_window()
        return self.selection_result


def review_source_image_directory(
    parent,
    root: Path | str,
    *,
    recursive: bool = True,
    title: str = "Podgląd i korekta zasobu O",
    audit_next_step: bool = False,
) -> bool:
    path = Path(root)
    report = validate_source_image_directory(path, recursive=recursive)
    if report.valid:
        return True
    if report.total_count <= 0:
        messagebox.showerror(
            "Nieprawidłowy zasób O",
            report.metadata_error or "Katalog nie zawiera obrazów.",
            parent=parent,
        )
        return False
    return _SourceFilenameReviewDialog(
        parent,
        path,
        recursive=recursive,
        title=title,
        audit_next_step=audit_next_step,
    ).show()


def review_source_image_paths(
    parent,
    paths: Iterable[Path | str],
    *,
    title: str = "Podgląd i korekta wybranych obrazów",
    audit_next_step: bool = False,
) -> SourceReviewSelectionResult:
    selected = tuple(Path(item) for item in paths if Path(item).exists() and Path(item).is_file())
    if not selected:
        return SourceReviewSelectionResult(True, accepted_paths=())
    report = validate_source_image_paths(selected)
    if report.invalid_count == 0:
        return SourceReviewSelectionResult(True, accepted_paths=selected)
    try:
        common = Path(os.path.commonpath([str(path.parent) for path in selected]))
    except Exception:
        common = selected[0].parent
    return _SourceFilenameReviewDialog(
        parent,
        common,
        recursive=False,
        title=title,
        selected_paths=selected,
        audit_next_step=audit_next_step,
    ).show_selection()
