"""UX wyboru i preflight kandydatów źródłowych PZ3."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable, Mapping, Sequence

from ..config import CONFIG


@dataclass(frozen=True)
class PZ3SourceSelection:
    mode: str
    paths: tuple[Path, ...]
    source_dir: str = ""


@dataclass(frozen=True)
class CandidateSkip:
    path: Path
    reason: str
    duplicate_of: str = ""


@dataclass(frozen=True)
class CandidatePreflightResult:
    candidates: tuple[Path, ...]
    already_in_track: tuple[CandidateSkip, ...] = ()
    batch_duplicates: tuple[CandidateSkip, ...] = ()
    name_collisions: tuple[CandidateSkip, ...] = ()
    hash_errors: tuple[CandidateSkip, ...] = ()

    @property
    def skipped_count(self) -> int:
        return (
            len(self.already_in_track)
            + len(self.batch_duplicates)
            + len(self.name_collisions)
            + len(self.hash_errors)
        )


def _allowed_extensions() -> set[str]:
    return {
        str(ext or "").strip().lower()
        for ext in CONFIG.IMAGE_EXTENSIONS
        if str(ext or "").strip()
    }


def collect_folder_candidates(root: Path | str) -> tuple[Path, ...]:
    path = Path(root)
    if not path.exists() or not path.is_dir():
        return ()
    allowed = _allowed_extensions()
    try:
        return tuple(
            sorted(
                (
                    item
                    for item in path.iterdir()
                    if item.is_file()
                    and item.suffix.lower() in allowed
                ),
                key=lambda item: item.name.casefold(),
            )
        )
    except Exception:
        return ()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def _row_value(row, key: str, default=""):
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return getattr(row, key, default)


def preflight_deduplicate_candidates(
    paths: Iterable[Path | str],
    existing_members: Sequence | None = None,
    *,
    source_ids_for_sha: Callable[[str], Iterable[str]] | None = None,
) -> CandidatePreflightResult:
    existing_members = list(existing_members or [])
    existing_sha: dict[str, str] = {}
    existing_names: dict[str, str] = {}
    existing_source_ids: set[str] = set()

    for row in existing_members:
        sha = str(_row_value(row, "sha256", "") or "").strip().lower()
        name = str(_row_value(row, "original_name", "") or "").strip()
        source_id = str(_row_value(row, "source_image_id", "") or "").strip()
        if sha:
            existing_sha.setdefault(sha, name or sha[:12])
        if name:
            existing_names.setdefault(name.casefold(), name)
        if source_id:
            existing_source_ids.add(source_id)

    candidates: list[Path] = []
    already: list[CandidateSkip] = []
    batch: list[CandidateSkip] = []
    collisions: list[CandidateSkip] = []
    hash_errors: list[CandidateSkip] = []
    seen: dict[str, Path] = {}

    for raw in paths:
        path = Path(raw)
        try:
            sha = _sha256(path)
        except Exception as exc:
            hash_errors.append(
                CandidateSkip(path, f"nie można policzyć SHA-256: {exc}")
            )
            continue

        if sha in existing_sha:
            already.append(
                CandidateSkip(
                    path,
                    "ten sam SHA-256 jest już w torze",
                    existing_sha[sha],
                )
            )
            continue

        if source_ids_for_sha is not None and existing_source_ids:
            try:
                known_ids = {
                    str(item or "").strip()
                    for item in source_ids_for_sha(sha)
                    if str(item or "").strip()
                }
            except Exception:
                known_ids = set()
            overlap = known_ids & existing_source_ids
            if overlap:
                already.append(
                    CandidateSkip(
                        path,
                        "to samo logiczne source_image_id jest już w torze",
                        sorted(overlap)[0],
                    )
                )
                continue

        if sha in seen:
            batch.append(
                CandidateSkip(
                    path,
                    "duplikat w bieżącym wyborze (ten sam SHA-256)",
                    seen[sha].name,
                )
            )
            continue

        key = path.name.casefold()
        if key in existing_names:
            collisions.append(
                CandidateSkip(
                    path,
                    "tor zawiera już tę nazwę, ale z inną zawartością",
                    existing_names[key],
                )
            )
            continue

        seen[sha] = path
        candidates.append(path)

    return CandidatePreflightResult(
        candidates=tuple(candidates),
        already_in_track=tuple(already),
        batch_duplicates=tuple(batch),
        name_collisions=tuple(collisions),
        hash_errors=tuple(hash_errors),
    )


def format_candidate_preflight_summary(
    result: CandidatePreflightResult,
    *,
    max_examples: int = 8,
) -> str:
    lines = [
        "Kontrola bieżącego toru:",
        f"• już obecne w torze: {len(result.already_in_track)}",
        f"• duplikaty w bieżącym wyborze: {len(result.batch_duplicates)}",
        f"• kolizje nazw z istniejącym torem: {len(result.name_collisions)}",
        f"• błędy SHA-256: {len(result.hash_errors)}",
        f"• nowe kandydaty do audytu train/val: {len(result.candidates)}",
    ]
    examples: list[CandidateSkip] = []
    for bucket in (
        result.already_in_track,
        result.batch_duplicates,
        result.name_collisions,
        result.hash_errors,
    ):
        examples.extend(bucket)
    if examples:
        lines.extend(["", "Pominięte pozycje:"])
        for item in examples[: max(0, int(max_examples))]:
            suffix = f" [{item.duplicate_of}]" if item.duplicate_of else ""
            lines.append(f"• {item.path.name} — {item.reason}{suffix}")
        if len(examples) > max_examples:
            lines.append(f"• … i {len(examples) - max_examples} kolejnych")
    return "\n".join(lines)


def prepend_candidate_preflight_summary(
    preflight_summary: str,
    audit_summary: str,
) -> str:
    first = str(preflight_summary or "").strip()
    second = str(audit_summary or "").strip()
    if first and second:
        return first + "\n\nAudyt względem train/val:\n" + second
    return first or second


class _PZ3SourceChooser:
    def __init__(self, parent) -> None:
        self.parent = parent
        self.result: PZ3SourceSelection | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Dodaj obrazy do toru PZ3")
        # Pełnoprawne okno systemowe: min/max/X.
        self.window.geometry("620x330")
        self.window.minsize(540, 290)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        try:
            self.window.wait_visibility()
            self.window.grab_set()
        except Exception:
            pass

    def _build(self) -> None:
        root = ttk.Frame(self.window, padding=18)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)

        ttk.Label(
            root,
            text="Jak chcesz dodać materiał?",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            root,
            text=(
                "Obie ścieżki trafiają do tego samego kontraktu nazw, "
                "kontroli duplikatów i audytu train/val."
            ),
            justify=tk.LEFT,
            wraplength=560,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 18))

        folder = ttk.LabelFrame(root, text="Katalog", padding=14)
        folder.grid(row=2, column=0, sticky="nsew", padx=(0, 7))
        ttk.Label(
            folder,
            text=(
                "Dodaj wszystkie obsługiwane obrazy znajdujące się "
                "bezpośrednio w wybranym katalogu."
            ),
            justify=tk.LEFT,
            wraplength=250,
        ).pack(anchor="w", fill=tk.X)
        ttk.Button(
            folder,
            text="Wybierz katalog",
            command=self._choose_folder,
        ).pack(anchor="w", pady=(14, 0))

        files = ttk.LabelFrame(root, text="Pliki", padding=14)
        files.grid(row=2, column=1, sticky="nsew", padx=(7, 0))
        ttk.Label(
            files,
            text=(
                "Wybierz jedno zdjęcie albo zaznacz wiele zdjęć "
                "w katalogu (Ctrl/Shift)."
            ),
            justify=tk.LEFT,
            wraplength=250,
        ).pack(anchor="w", fill=tk.X)
        ttk.Button(
            files,
            text="Wybierz pliki",
            command=self._choose_files,
        ).pack(anchor="w", pady=(14, 0))

        footer = ttk.Frame(root)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(20, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text="Anuluj", command=self._cancel).grid(row=0, column=1, sticky="e")

    def _initial_dir(self) -> str:
        try:
            raw = Path(CONFIG.DIR_1_RAW)
            if raw.exists() and raw.is_dir():
                return str(raw)
        except Exception:
            pass
        return str(Path.cwd())

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.window,
            title="Wybierz katalog obrazów",
            initialdir=self._initial_dir(),
        )
        if not selected:
            return
        paths = collect_folder_candidates(selected)
        if not paths:
            messagebox.showwarning(
                "Brak obrazów",
                "Wybrany katalog nie zawiera obsługiwanych obrazów.",
                parent=self.window,
            )
            return
        self.result = PZ3SourceSelection("folder", paths, str(Path(selected)))
        self._close()

    def _choose_files(self) -> None:
        extensions = " ".join(
            f"*{ext}" for ext in sorted(CONFIG.IMAGE_EXTENSIONS)
        )
        selected = filedialog.askopenfilenames(
            parent=self.window,
            title="Wybierz jedno lub wiele zdjęć",
            initialdir=self._initial_dir(),
            filetypes=[
                ("Obrazy", extensions),
                ("Wszystkie pliki", "*.*"),
            ],
        )
        if not selected:
            return
        self.result = PZ3SourceSelection(
            "files",
            tuple(Path(item) for item in selected),
            "",
        )
        self._close()

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def show(self) -> PZ3SourceSelection | None:
        self.window.wait_window()
        return self.result


def choose_pz3_source_candidates(parent) -> PZ3SourceSelection | None:
    return _PZ3SourceChooser(parent).show()
