"""Prominent, checkpoint-bound source locations for the mobile export profile."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk


def candidate_source_paths(candidate: dict | None) -> dict[str, Path | None]:
    candidate = candidate or {}
    run = candidate.get("run")
    run_dataset = run.get("dataset_path") if isinstance(run, dict) else getattr(run, "dataset_path", None)
    values = {
        "model": candidate.get("best_weights"),
        "dataset": candidate.get("dataset_path") or run_dataset,
    }
    paths = {}
    for key, value in values.items():
        raw = str(value or "").strip().strip('"')
        # Use the same working directory as the export request. Never substitute
        # the active project's dataset, a base model or another checkpoint copy.
        paths[key] = Path(os.path.abspath(raw)) if raw else None
    return paths


def reveal_source_path(path: Path) -> None:
    """Open a directory, or select the exact source file without executing it."""
    if not path.exists():
        raise FileNotFoundError(f"Nie znaleziono na dysku: {path}")
    if sys.platform == "win32":
        if path.is_dir():
            os.startfile(str(path))
        else:
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)] if path.is_dir() else ["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])


class MobileExportSourceLocations(tk.Frame):
    def __init__(self, master, *, bg: str, fg: str, muted: str, accent: str):
        super().__init__(master, bg=bg)
        self.paths: dict[str, Path | None] = {}
        self.path_labels = {}
        self.open_buttons = {}
        self.copy_buttons = {}
        self._fg = fg
        self._muted = muted
        self.grid_columnconfigure(0, weight=1)
        for index, (key, title) in enumerate((
            ("model", "Plik modelu (.pt)"),
            ("dataset", "Dataset treningowy"),
        )):
            header = tk.Frame(self, bg=bg)
            header.grid(row=index * 2, column=0, sticky="ew", pady=(0 if index == 0 else 8, 3))
            header.grid_columnconfigure(0, weight=1)
            tk.Label(header, text=title, bg=bg, fg=fg, anchor="w",
                     font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
            copy_button = ttk.Button(header, text="Kopiuj", width=7,
                                     command=lambda source=key: self.copy_path(source))
            copy_button.grid(row=0, column=1, padx=(4, 5))
            open_button = ttk.Button(header, text="Pokaż w folderze", width=17,
                                     command=lambda source=key: self.open_path(source))
            open_button.grid(row=0, column=2)
            label = tk.Label(self, text="", bg=bg, fg=fg, anchor="nw", justify="left",
                             font=("Segoe UI", 9), width=1, padx=6, pady=5,
                             highlightthickness=1, highlightbackground=accent)
            label.grid(row=index * 2 + 1, column=0, sticky="ew")
            label.bind("<Configure>", lambda event, item=label: item.configure(
                wraplength=max(1, event.width - 16)))
            self.path_labels[key] = label
            self.copy_buttons[key] = copy_button
            self.open_buttons[key] = open_button
        self.set_candidate(None)

    def set_candidate(self, candidate: dict | None) -> None:
        self.paths = candidate_source_paths(candidate)
        for key, path in self.paths.items():
            self.path_labels[key].configure(
                text=str(path) if path else "Brak ścieżki w metadanych",
                fg=self._fg if path else self._muted,
            )
            self.copy_buttons[key].configure(state="normal" if path else "disabled")
            self._update_open_button(key)

    def _update_open_button(self, key: str) -> bool:
        path = self.paths.get(key)
        exists = False
        is_dir = False
        if path:
            try:
                is_dir = path.is_dir()
                exists = path.is_file() or (key == "dataset" and is_dir)
            except (OSError, ValueError):
                pass
        self.open_buttons[key].configure(
            state="normal" if exists else "disabled",
            text=("Otwórz folder" if is_dir else "Pokaż w folderze") if exists
                 else ("Brak na dysku" if path else "Brak ścieżki"),
        )
        return exists

    def copy_path(self, key: str) -> None:
        path = self.paths.get(key)
        if path:
            self.clipboard_clear()
            self.clipboard_append(str(path))

    def open_path(self, key: str) -> None:
        path = self.paths.get(key)
        if path is None:
            return
        try:
            reveal_source_path(path)
        except (OSError, ValueError) as exc:
            self._update_open_button(key)
            messagebox.showerror("Nie można otworzyć lokalizacji", str(exc), parent=self.winfo_toplevel())
