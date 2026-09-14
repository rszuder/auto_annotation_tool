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


class _SourceFilenameReviewDialog:
    def __init__(
        self,
        parent,
        root: Path,
        *,
        recursive: bool,
        title: str,
        selected_paths: Iterable[Path | str] | None = None,
    ) -> None:
        self.parent = parent
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
        self._sort_column = "#0"
        self._sort_reverse = False
        self._edit_entry = None
        self._edit_iid = ""
        self._review_rows_by_iid = {}

        self.window = tk.Toplevel(parent)
        self.window.title(title)
        # Pełne okno systemowe: bez transient/overrideredirect.
        self.window.geometry("1040x690")
        self.window.minsize(820, 560)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        self._reload()
        try:
            self.window.wait_visibility()
            self.window.grab_set()
        except Exception:
            pass

    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(2, weight=1)

        ttk.Label(
            outer,
            text="Podgląd i korekta nazw zasobu O",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.summary_var = tk.StringVar()
        ttk.Label(
            outer,
            textvariable=self.summary_var,
            wraplength=950,
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 10))

        left = ttk.Frame(outer)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            left,
            columns=("problem", "action"),
            show="tree headings",
            selectmode="browse",
        )
        self._heading_titles = {
            "#0": "Plik",
            "problem": "Walidacja",
            "action": "Decyzja",
        }
        for column, title in self._heading_titles.items():
            self.tree.heading(
                column,
                text=title,
                command=lambda col=column: self._sort_by_column(col),
            )
        self.tree.column("#0", width=280)
        self.tree.column("problem", width=340)
        self.tree.column("action", width=180)
        self.tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.bind("<<TreeviewSelect>>", self._on_select, add="+")
        self.tree.bind("<Return>", self._begin_inline_edit, add="+")
        self.tree.bind("<F2>", self._begin_inline_edit, add="+")
        self.tree.bind("<Up>", lambda _e: self._move_selection(-1), add="+")
        self.tree.bind("<Down>", lambda _e: self._move_selection(1), add="+")
        self.tree.bind("<Double-1>", self._on_tree_double_click, add="+")

        right = ttk.Frame(outer)
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self.preview = ttk.Label(
            right,
            text="Wybierz plik z listy.",
            anchor="center",
        )
        self.preview.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(
            right,
            text=(
                "Edycja nazwy odbywa się bezpośrednio na liście.\n"
                "Enter / F2 — edycja nazwy\n"
                "Enter — zatwierdź zmianę\n"
                "Esc — anuluj edycję\n"
                "↑ / ↓ — poprzedni / następny plik"
            ),
            justify=tk.LEFT,
            wraplength=360,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        ttk.Button(
            right,
            text="Odrzuć z zasobu",
            command=self._reject_selected,
        ).grid(row=2, column=0, sticky="w")

        ttk.Separator(right).grid(row=3, column=0, sticky="ew", pady=12)

        ttk.Button(
            right,
            text="Odrzuć wszystkie błędne",
            command=self._reject_all,
        ).grid(row=4, column=0, sticky="w")

        ttk.Label(
            right,
            text=(
                "„Odrzuć” nie usuwa pliku. Zaplanowana poprawna zmiana "
                "nazwy pozostaje widoczna na liście aż do końcowego "
                "„Zastosuj”. Kliknij nagłówek kolumny, aby posortować listę."
            ),
            wraplength=360,
            justify=tk.LEFT,
        ).grid(row=5, column=0, sticky="ew", pady=(10, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar()
        ttk.Label(
            footer,
            textvariable=self.status_var,
            wraplength=680,
            justify=tk.LEFT,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Anuluj", command=self._cancel).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(footer, text="Zastosuj", command=self._apply).grid(
            row=0, column=2, padx=(8, 0)
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
        self._review_rows_by_iid = {str(row.path): row for row in rows}

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                iid=str(row.path),
                text=self._display_name_for_row(row),
                values=(row.problem, row.action),
            )

        unresolved = sum(1 for row in rows if row.unresolved)
        self.summary_var.set(
            f"Źródło: {self.root}\n"
            f"Obrazów w zakresie: {len(paths)} | "
            f"wymagających decyzji: {unresolved} | "
            f"zmiany nazw: {len(self.rename_stems)} | "
            f"odrzucenia: {len(self.rejected_paths)}"
        )
        self.status_var.set(
            "Każdy błędny plik musi zostać poprawiony albo odrzucony."
            if unresolved
            else "Wszystkie problematyczne pliki mają decyzję. Kliknij „Zastosuj”."
        )
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
            self._preview_photo = None
            self.preview.configure(
                image="",
                text="Brak plików wymagających decyzji.",
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
        if path is None:
            return

        if (
            getattr(self, "_edit_entry", None) is not None
            and getattr(self, "_edit_iid", "")
            and self._edit_iid != str(path)
        ):
            self._cancel_inline_edit(refocus=False)

        self._show_preview(path)

    def _show_preview(self, path: Path) -> None:
        if Image is None or ImageTk is None or ImageOps is None:
            self.preview.configure(text=path.name, image="")
            return
        try:
            with Image.open(path) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
                resampling = getattr(Image, "Resampling", Image)
                image.thumbnail((360, 260), resampling.LANCZOS)
                self._preview_photo = ImageTk.PhotoImage(image)
            self.preview.configure(image=self._preview_photo, text=path.name, compound=tk.TOP)
        except Exception as exc:
            self._preview_photo = None
            self.preview.configure(image="", text=f"{path.name}\nNie można wyświetlić podglądu: {exc}")

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
        for row in build_source_review_rows(
            self._iter_current_images(),
            root=self.root,
        ):
            key = str(row.path)
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
        rows = build_source_review_rows(
            self._iter_current_images(),
            rename_stems=self.rename_stems,
            rejected_paths=self.rejected_paths,
            root=self.root,
        )
        unresolved = [row for row in rows if row.unresolved]
        if unresolved:
            messagebox.showwarning(
                "Nieukończona korekta",
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
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.selection_result = SourceReviewSelectionResult(False)
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def show(self) -> bool:
        self.window.wait_window()
        return self.result

    def show_selection(self) -> SourceReviewSelectionResult:
        self.window.wait_window()
        return self.selection_result


def review_source_image_directory(
    parent,
    root: Path | str,
    *,
    recursive: bool = True,
    title: str = "Podgląd i korekta zasobu O",
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
    ).show()


def review_source_image_paths(
    parent,
    paths: Iterable[Path | str],
    *,
    title: str = "Podgląd i korekta wybranych obrazów",
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
    ).show_selection()
