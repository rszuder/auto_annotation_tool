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
        self.tree.heading("#0", text="Plik")
        self.tree.heading("problem", text="Walidacja")
        self.tree.heading("action", text="Decyzja")
        self.tree.column("#0", width=250)
        self.tree.column("problem", width=340)
        self.tree.column("action", width=180)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(outer)
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self.preview = ttk.Label(right, text="Wybierz plik z listy.", anchor="center")
        self.preview.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(right, text="Nowa nazwa (bez rozszerzenia):").grid(row=1, column=0, sticky="w")
        self.rename_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.rename_var).grid(row=2, column=0, sticky="ew", pady=(4, 8))

        row = ttk.Frame(right)
        row.grid(row=3, column=0, sticky="ew")
        ttk.Button(row, text="Zmień nazwę", command=self._plan_rename).pack(side=tk.LEFT)
        ttk.Button(row, text="Odrzuć z zasobu", command=self._reject_selected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Separator(right).grid(row=4, column=0, sticky="ew", pady=12)
        ttk.Button(
            right,
            text="Odrzuć wszystkie błędne",
            command=self._reject_all,
        ).grid(row=5, column=0, sticky="w")
        ttk.Label(
            right,
            text=(
                "„Odrzuć” nie usuwa pliku. Zaplanowana poprawna zmiana nazwy "
                "pozostaje widoczna na liście aż do końcowego „Zastosuj”."
            ),
            wraplength=360,
            justify=tk.LEFT,
        ).grid(row=6, column=0, sticky="ew", pady=(10, 0))

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
        ttk.Button(footer, text="Anuluj", command=self._cancel).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(footer, text="Zastosuj", command=self._apply).grid(row=0, column=2, padx=(8, 0))

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

    def _reload(self) -> None:
        paths = self._iter_current_images()
        rows = build_source_review_rows(
            paths,
            rename_stems=self.rename_stems,
            rejected_paths=self.rejected_paths,
            root=self.root,
        )
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                iid=str(row.path),
                text=row.display_name,
                values=(row.problem, row.action),
            )
        unresolved = sum(1 for row in rows if row.unresolved)
        self.summary_var.set(
            f"Źródło: {self.root}\n"
            f"Obrazów w zakresie: {len(paths)} | wymagających decyzji: {unresolved} | "
            f"zmiany nazw: {len(self.rename_stems)} | odrzucenia: {len(self.rejected_paths)}"
        )
        self.status_var.set(
            "Każdy błędny plik musi zostać poprawiony albo odrzucony."
            if unresolved
            else "Wszystkie problematyczne pliki mają decyzję. Kliknij „Zastosuj”."
        )

    def _selected_path(self) -> Path | None:
        selected = self.tree.selection()
        return Path(selected[0]) if selected else None

    def _on_select(self, _event=None) -> None:
        path = self._selected_path()
        if path is None:
            return
        self.rename_var.set(self.rename_stems.get(str(path), path.stem))
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
        path = self._selected_path()
        if path is None:
            messagebox.showinfo("Zmiana nazwy", "Najpierw wybierz plik.", parent=self.window)
            return
        stem = str(self.rename_var.get() or "").strip()
        candidate = stem + path.suffix
        parsed = parse_source_image_filename(candidate)
        if not stem or not parsed.valid:
            messagebox.showerror(
                "Nazwa nadal nie spełnia kontraktu",
                "; ".join(parsed.errors) if stem else "Nowa nazwa nie może być pusta.",
                parent=self.window,
            )
            return
        target = path.with_name(candidate)
        if target.exists() and target != path:
            messagebox.showerror("Kolizja nazwy", f"Plik już istnieje:\n{target}", parent=self.window)
            return
        key = str(path)
        self.rejected_paths.discard(key)
        self.rename_stems[key] = stem
        self._reload()
        if self.tree.exists(key):
            self.tree.selection_set(key)
            self.tree.focus(key)
            self.tree.see(key)

    def _reject_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        key = str(path)
        self.rename_stems.pop(key, None)
        self.rejected_paths.add(key)
        self._reload()
        if self.tree.exists(key):
            self.tree.selection_set(key)
            self.tree.focus(key)
            self.tree.see(key)

    def _reject_all(self) -> None:
        for row in build_source_review_rows(self._iter_current_images(), root=self.root):
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
