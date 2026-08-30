#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI for MZ character class balance diagnostics."""

from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import CONFIG, logger
from ..training import (
    CHARACTER_REPRESENTATION_THRESHOLD_POLICY,
    CharacterClassMapValidationError,
    CharacterClassDistribution,
    analyze_character_class_distribution,
    find_character_real_source_candidates,
    plan_character_train_augmentation,
    save_character_distribution_artifacts,
    save_character_class_distribution_csv,
    save_character_class_distribution_json,
)
from .dataset_display import build_dataset_display_ref


_STATUS_LABELS = {
    "OK": "OK",
    "LOW": "Mało próbek",
    "LOW_DIVERSITY": "Mała różnorodność",
    "LOW+LOW_DIVERSITY": "Mało i wąsko",
    "CRITICAL": "Brak klasy",
}

_STATUS_COLORS = {
    "OK": "#2faa66",
    "LOW": "#d89a20",
    "LOW_DIVERSITY": "#c9a521",
    "LOW+LOW_DIVERSITY": "#e0792f",
    "CRITICAL": "#d94b4b",
}


def open_character_class_distribution_dialog(
    host,
    *,
    dataset_root: Path | str | None = None,
    yaml_path: Path | str | None = None,
    read_only: bool | None = None,
    context: str = "pz2",
) -> None:
    parent = getattr(host, "frame", None) or getattr(getattr(host, "app", None), "root", None)
    if dataset_root is None:
        target = "char"
        try:
            target = CONFIG.normalize_task_target(host._get_selected_training_target())
        except Exception:
            target = "char"
        if target != "char":
            messagebox.showinfo(
                "Analiza reprezentacji MZ",
                "Ta analiza dotyczy modelu znaków MZ. Przełącz Z4 na tor znaków i wybierz wariant datasetu.",
                parent=parent,
            )
            return

        resolver = getattr(host, "_resolve_training_dataset_yaml_path", None)
        yaml_path = resolver() if callable(resolver) else None
        if yaml_path is None:
            messagebox.showwarning(
                "Brak wariantu datasetu",
                "Najpierw wybierz aktywny wariant datasetu znaków.",
                parent=parent,
            )
            return
        try:
            yaml_path = Path(yaml_path)
            dataset_root = yaml_path.parent if yaml_path.is_file() else yaml_path
        except Exception:
            messagebox.showerror(
                "Błąd datasetu",
                "Nie udało się odczytać ścieżki aktywnego wariantu datasetu.",
                parent=parent,
            )
            return
        if read_only is None:
            read_only = True
    else:
        try:
            dataset_root = Path(dataset_root)
            yaml_path = Path(yaml_path) if yaml_path is not None else dataset_root / "data.yaml"
        except Exception:
            messagebox.showerror(
                "Błąd datasetu",
                "Nie udało się odczytać ścieżki wariantu datasetu.",
                parent=parent,
            )
            return
        if read_only is None:
            read_only = False

    _CharacterClassDistributionDialog(
        host,
        Path(dataset_root),
        Path(yaml_path) if yaml_path is not None else None,
        read_only=bool(read_only),
        context=context,
    ).show()


class _CharacterClassDistributionDialog:
    def __init__(
        self,
        host,
        dataset_root: Path,
        yaml_path: Path | None,
        *,
        read_only: bool = True,
        context: str = "pz2",
    ):
        self.host = host
        self.dataset_root = Path(dataset_root)
        self.yaml_path = Path(yaml_path) if yaml_path is not None else None
        self.read_only = bool(read_only)
        self.context = str(context or "pz2")
        self.app = getattr(host, "app", None)
        self.palette = getattr(self.app, "palette", {}) if self.app is not None else {}
        self.window: tk.Toplevel | None = None
        self.progress: ttk.Progressbar | None = None
        self.status_var = tk.StringVar(value="Przygotowuję analizę reprezentacji znaków MZ...")
        self.dataset_var = tk.StringVar(value=self._dataset_label())
        self.target_ratio_var = tk.StringVar(value="0.50")
        self.threshold_policy_var = tk.StringVar(value=f"AUTO ({CHARACTER_REPRESENTATION_THRESHOLD_POLICY})")
        self.result: CharacterClassDistribution | None = None
        self.summary_value_labels: dict[str, tk.Label] = {}
        self.table: ttk.Treeview | None = None
        self.chart: tk.Canvas | None = None
        self.save_before_btn: ttk.Button | None = None
        self.plan_btn: ttk.Button | None = None
        self.export_csv_btn: ttk.Button | None = None
        self.export_json_btn: ttk.Button | None = None

    def show(self) -> None:
        parent = getattr(self.host, "frame", None)
        root = getattr(self.app, "root", None) or (parent.winfo_toplevel() if parent is not None else None)
        self.window = tk.Toplevel(root or parent)
        title_suffix = "raport" if self.read_only else "plan PZ1"
        self.window.title(f"Analiza reprezentacji MZ - {title_suffix}")
        self.window.minsize(980, 620)
        self.window.geometry("1160x740")
        try:
            self.window.transient(root)
        except Exception:
            pass

        self._build()
        self._center()
        self._start_analysis()

    def _build(self) -> None:
        assert self.window is not None
        bg = self.palette.get("bg", "#1e1f22")
        fg = self.palette.get("fg", "#f3f3f3")
        muted = self.palette.get("muted", "#b7bcc6")
        panel = self.palette.get("panel", "#25262b")
        panel_alt = self.palette.get("panel_alt", "#2c2d33")

        self.window.configure(bg=bg)
        self.window.grid_rowconfigure(0, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        root = tk.Frame(self.window, bg=bg, padx=14, pady=12)
        root.grid(row=0, column=0, sticky="nsew")
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(3, weight=1)

        title = tk.Label(
            root,
            text="Analiza reprezentacji znaków MZ",
            bg=bg,
            fg=fg,
            font=("Segoe UI Semibold", 15),
            anchor=tk.W,
        )
        title.grid(row=0, column=0, sticky="ew")

        intro = tk.Label(
            root,
            text=(
                "Sprawdzamy, czy klasy 0-9 i A-Z mają wystarczającą reprezentację w train. "
                "W PZ1 można z tego utworzyć plan AUTO, a w PZ2 ten widok jest tylko raportem."
            ),
            bg=bg,
            fg=muted,
            font=("Segoe UI", 9),
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=980,
        )
        intro.grid(row=1, column=0, sticky="ew", pady=(3, 10))

        meta = tk.Frame(root, bg=panel_alt, highlightthickness=1, highlightbackground=self._border())
        meta.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        meta.grid_columnconfigure(1, weight=1)
        tk.Label(
            meta,
            text="Dataset",
            bg=panel_alt,
            fg=muted,
            font=("Segoe UI Semibold", 9),
            padx=8,
            pady=6,
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            meta,
            textvariable=self.dataset_var,
            bg=panel_alt,
            fg=fg,
            font=("Segoe UI", 9),
            anchor=tk.W,
            padx=8,
            pady=6,
        ).grid(row=0, column=1, sticky="ew")
        tk.Label(
            meta,
            text="Próg reprezentacji",
            bg=panel_alt,
            fg=muted,
            font=("Segoe UI Semibold", 9),
            padx=8,
            pady=6,
        ).grid(row=1, column=0, sticky="w")
        target_shell = tk.Frame(meta, bg=panel_alt)
        target_shell.grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(0, 6))
        tk.Label(
            target_shell,
            textvariable=self.threshold_policy_var,
            bg=panel_alt,
            fg=fg,
            font=("Segoe UI Semibold", 9),
            padx=8,
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            target_shell,
            text="liczony automatycznie z bieżącego train",
            bg=panel_alt,
            fg=muted,
            font=("Segoe UI", 8),
            padx=8,
        ).grid(row=0, column=1, sticky="w")
        ttk.Button(target_shell, text="Przelicz", command=self._restart_analysis).grid(row=0, column=2, sticky="w")

        content = tk.Frame(root, bg=bg)
        content.grid(row=3, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=0, minsize=290)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=0)
        content.grid_rowconfigure(1, weight=1)

        summary = tk.LabelFrame(
            content,
            text=" Podsumowanie ",
            bg=panel,
            fg=fg,
            padx=8,
            pady=8,
            font=("Segoe UI Semibold", 9),
            highlightthickness=1,
            highlightbackground=self._border(),
        )
        summary.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10))
        summary.grid_columnconfigure(1, weight=1)
        self._build_summary_rows(summary)

        chart_shell = tk.LabelFrame(
            content,
            text=" Wykres train ",
            bg=panel,
            fg=fg,
            padx=8,
            pady=8,
            font=("Segoe UI Semibold", 9),
            highlightthickness=1,
            highlightbackground=self._border(),
        )
        chart_shell.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        chart_shell.grid_columnconfigure(0, weight=1)
        self.chart = tk.Canvas(
            chart_shell,
            height=210,
            bg=panel,
            highlightthickness=0,
            bd=0,
        )
        self.chart.grid(row=0, column=0, sticky="nsew")
        self.chart.bind("<Configure>", lambda _event: self._draw_chart())

        table_shell = tk.LabelFrame(
            content,
            text=" Klasy znaków ",
            bg=panel,
            fg=fg,
            padx=8,
            pady=8,
            font=("Segoe UI Semibold", 9),
            highlightthickness=1,
            highlightbackground=self._border(),
        )
        table_shell.grid(row=1, column=1, sticky="nsew")
        table_shell.grid_rowconfigure(0, weight=1)
        table_shell.grid_columnconfigure(0, weight=1)
        self._build_table(table_shell)

        footer = tk.Frame(root, bg=bg)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        footer.grid_columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, sticky="e", padx=(8, 8))
        self.save_before_btn = ttk.Button(
            footer,
            text="Zapisz before",
            command=self._save_before_artifacts,
            state=tk.DISABLED,
        )
        self.save_before_btn.grid(row=0, column=2, sticky="e", padx=(0, 6))
        self.plan_btn = ttk.Button(
            footer,
            text="Przygotuj plan AUTO",
            command=self._show_balance_plan,
            state=tk.DISABLED,
        )
        if not self.read_only:
            self.plan_btn.grid(row=0, column=3, sticky="e", padx=(0, 6))
        self.export_csv_btn = ttk.Button(
            footer,
            text="Zapisz CSV",
            command=self._export_csv,
            state=tk.DISABLED,
        )
        self.export_csv_btn.grid(row=0, column=4, sticky="e", padx=(0, 6))
        self.export_json_btn = ttk.Button(
            footer,
            text="Zapisz JSON",
            command=self._export_json,
            state=tk.DISABLED,
        )
        self.export_json_btn.grid(row=0, column=5, sticky="e", padx=(0, 6))
        ttk.Button(footer, text="Zamknij", command=self.window.destroy).grid(row=0, column=6, sticky="e")

    def _build_summary_rows(self, parent: tk.Widget) -> None:
        labels = [
            ("layout", "Układ danych"),
            ("class_map", "Mapa klas"),
            ("diagnostic_split", "Kryterium"),
            ("total_labels", "Etykiety"),
            ("range", "Min / mediana / max"),
            ("target", "Cel / deficyt"),
            ("ratio", "Stosunek max/min"),
            ("zero", "Braki krytyczne"),
            ("low", "Mało próbek"),
            ("diversity", "Mała różnorodność"),
            ("files", "Pliki / błędy"),
        ]
        for row_index, (key, label) in enumerate(labels):
            tk.Label(
                parent,
                text=label,
                bg=self.palette.get("panel", "#25262b"),
                fg=self.palette.get("muted", "#b7bcc6"),
                font=("Segoe UI Semibold", 8),
                anchor=tk.W,
                padx=4,
                pady=5,
            ).grid(row=row_index, column=0, sticky="nw")
            value_lbl = tk.Label(
                parent,
                text="-",
                bg=self.palette.get("panel", "#25262b"),
                fg=self.palette.get("fg", "#f3f3f3"),
                font=("Segoe UI", 8),
                anchor=tk.W,
                justify=tk.LEFT,
                wraplength=165,
                padx=4,
                pady=5,
            )
            value_lbl.grid(row=row_index, column=1, sticky="ew")
            self.summary_value_labels[key] = value_lbl

    def _build_table(self, parent: tk.Widget) -> None:
        columns = (
            "symbol",
            "train",
            "unique_train",
            "count_status",
            "diversity_status",
            "target",
            "deficit",
            "val",
            "test",
            "total",
            "share",
            "status",
        )
        self.table = ttk.Treeview(parent, columns=columns, show="headings", height=16)
        headings = {
            "symbol": "Znak",
            "train": "Train",
            "unique_train": "Unikalne tablice train",
            "count_status": "Liczebność",
            "diversity_status": "Różnorodność",
            "target": "Cel",
            "deficit": "Deficyt",
            "val": "Val",
            "test": "Test",
            "total": "Razem",
            "share": "Udział train",
            "status": "Status",
        }
        widths = {
            "symbol": 54,
            "train": 76,
            "unique_train": 150,
            "count_status": 110,
            "diversity_status": 125,
            "target": 70,
            "deficit": 76,
            "val": 70,
            "test": 70,
            "total": 78,
            "share": 92,
            "status": 145,
        }
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], minwidth=42, stretch=column in {"unique_train", "status"})
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        for status, color in _STATUS_COLORS.items():
            tag = _status_tag(status)
            try:
                self.table.tag_configure(tag, foreground=color)
            except Exception:
                pass

    def _start_analysis(self) -> None:
        target_ratio = self._target_ratio()
        if self.progress is not None:
            try:
                self.progress.grid()
            except Exception:
                pass
            self.progress.start(12)

        def worker() -> None:
            try:
                result = analyze_character_class_distribution(
                    self.dataset_root,
                    target_ratio=target_ratio,
                )
            except CharacterClassMapValidationError as exc:
                logger.warning("Analiza MZ zatrzymana przez niezgodną mapę klas: %s", exc)
                self._after(lambda: self._show_error(str(exc)))
                return
            except Exception as exc:
                logger.exception("Nie udało się przeanalizować rozkładu klas MZ")
                self._after(lambda: self._show_error(str(exc)))
                return
            self._after(lambda: self._apply_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _restart_analysis(self) -> None:
        self.result = None
        if self.save_before_btn is not None:
            self.save_before_btn.configure(state=tk.DISABLED)
        if self.plan_btn is not None:
            self.plan_btn.configure(state=tk.DISABLED)
        if self.export_csv_btn is not None:
            self.export_csv_btn.configure(state=tk.DISABLED)
        if self.export_json_btn is not None:
            self.export_json_btn.configure(state=tk.DISABLED)
        if self.table is not None:
            self.table.delete(*self.table.get_children())
        self.status_var.set("Przeliczam analizę rozkładu klas...")
        self._draw_chart()
        self._start_analysis()

    def _target_ratio(self) -> float:
        raw = str(self.target_ratio_var.get() or "0.50").strip().replace(",", ".")
        try:
            value = float(raw)
        except Exception:
            value = 0.50
        if value > 1.0:
            value /= 100.0
        value = max(0.0, min(2.0, value))
        self.target_ratio_var.set(f"{value:.2f}")
        return value

    def _apply_result(self, result: CharacterClassDistribution) -> None:
        self.result = result
        if self.progress is not None:
            self.progress.stop()
            self.progress.grid_remove()
        if self.save_before_btn is not None:
            self.save_before_btn.configure(state=tk.NORMAL)
        if self.plan_btn is not None:
            self.plan_btn.configure(state=(tk.DISABLED if self.read_only else tk.NORMAL))
        if self.export_csv_btn is not None:
            self.export_csv_btn.configure(state=tk.NORMAL)
        if self.export_json_btn is not None:
            self.export_json_btn.configure(state=tk.NORMAL)
        if self.read_only:
            self.status_var.set("Raport gotowy. PZ2 nie zmienia planu augmentacji MZ.")
        else:
            self.status_var.set("Analiza gotowa. W PZ1 możesz przygotować plan AUTO dla train.")
        self._fill_summary(result)
        self._fill_table(result)
        self._draw_chart()

    def _show_error(self, error_text: str) -> None:
        if self.progress is not None:
            self.progress.stop()
            self.progress.grid_remove()
        self.status_var.set("Nie udało się wykonać analizy.")
        if self.window is not None and self.window.winfo_exists():
            messagebox.showerror("Błąd analizy rozkładu klas", error_text, parent=self.window)

    def _fill_summary(self, result: CharacterClassDistribution) -> None:
        summary = dict(result.summary or {})
        range_text = (
            f"{int(summary.get('minimum_class_count', 0) or 0)} / "
            f"{_format_float(summary.get('median_class_count'))} / "
            f"{int(summary.get('maximum_class_count', 0) or 0)}"
        )
        ratio_value = summary.get("max_min_ratio")
        ratio_text = "nieokreślony przy brakach" if ratio_value is None else _format_float(ratio_value)
        file_errors = int(summary.get("invalid_label_lines", 0) or 0) + int(summary.get("invalid_class_ids", 0) or 0)
        target_count = int(summary.get("target_class_count", 0) or 0)
        total_deficit = int(summary.get("total_deficit_count", 0) or 0)
        class_map = dict(summary.get("class_map") or {})
        class_map_status = str(class_map.get("status") or "-")
        if class_map_status == "OK":
            class_map_text = "Zgodna z MZ"
        elif class_map_status == "WARNING":
            class_map_text = "Ostrzeżenie: brak data.yaml"
        else:
            class_map_text = class_map.get("message") or "Nie sprawdzono"
        values = {
            "layout": _layout_label(result.layout),
            "class_map": class_map_text,
            "diagnostic_split": "train" if result.diagnostic_split == "train" else "razem",
            "total_labels": str(int(summary.get("total_labels", 0) or 0)),
            "range": range_text,
            "target": f"{target_count} na klasę, brakuje {total_deficit}",
            "ratio": ratio_text,
            "zero": _symbols(summary.get("zero_classes")),
            "low": _symbols(summary.get("low_count_classes")),
            "diversity": _symbols(summary.get("low_diversity_classes")),
            "files": f"{int(summary.get('files_read', 0) or 0)} plików, błędy: {file_errors}",
        }
        for key, value in values.items():
            label = self.summary_value_labels.get(key)
            if label is None:
                continue
            color = self.palette.get("fg", "#f3f3f3")
            if key == "zero" and value != "brak":
                color = _STATUS_COLORS["CRITICAL"]
            elif key == "target" and total_deficit > 0:
                color = _STATUS_COLORS["LOW"]
            elif key == "class_map" and str(class_map_status) == "WARNING":
                color = _STATUS_COLORS["LOW"]
            elif key in {"low", "diversity"} and value != "brak":
                color = _STATUS_COLORS["LOW"]
            try:
                label.configure(text=value, fg=color)
            except Exception:
                label.configure(text=value)

    def _fill_table(self, result: CharacterClassDistribution) -> None:
        if self.table is None:
            return
        self.table.delete(*self.table.get_children())
        for row in result.classes:
            self.table.insert(
                "",
                tk.END,
                values=(
                    row.symbol,
                    row.train_count,
                    row.unique_train_plate_count,
                    _STATUS_LABELS.get(row.count_status, row.count_status),
                    _STATUS_LABELS.get(row.diversity_status, row.diversity_status),
                    row.target_count,
                    row.deficit_count,
                    row.val_count,
                    row.test_count,
                    row.total_count,
                    _format_percent(row.train_share),
                    _STATUS_LABELS.get(row.status, row.status),
                ),
                tags=(_status_tag(row.status),),
            )

    def _draw_chart(self) -> None:
        if self.chart is None:
            return
        self.chart.delete("all")
        width = max(320, int(self.chart.winfo_width() or 760))
        height = max(160, int(self.chart.winfo_height() or 210))
        panel = self.palette.get("panel", "#25262b")
        fg = self.palette.get("fg", "#f3f3f3")
        muted = self.palette.get("muted", "#b7bcc6")
        grid = self._border()
        self.chart.configure(bg=panel)

        if self.result is None:
            self.chart.create_text(width / 2, height / 2, text="Liczenie klas...", fill=muted, font=("Segoe UI", 10))
            return

        result = self.result
        use_train = result.diagnostic_split == "train"
        values = [row.train_count if use_train else row.total_count for row in result.classes]
        max_value = max(values) if values else 0
        left = 42
        right = 14
        top = 30
        bottom = 34
        plot_w = max(1, width - left - right)
        plot_h = max(1, height - top - bottom)
        base_y = top + plot_h
        self.chart.create_line(left, top, left, base_y, fill=grid)
        self.chart.create_line(left, base_y, width - right, base_y, fill=grid)
        title = "Liczba etykiet w train" if use_train else "Liczba etykiet razem"
        self.chart.create_text(left, 10, anchor=tk.W, text=title, fill=fg, font=("Segoe UI Semibold", 9))
        self.chart.create_text(width - right, 10, anchor=tk.E, text=f"max: {max_value}", fill=muted, font=("Segoe UI", 8))

        if max_value <= 0:
            self.chart.create_text(width / 2, height / 2, text="Brak etykiet do pokazania.", fill=muted, font=("Segoe UI", 10))
            return

        slot = plot_w / max(1, len(values))
        bar_w = max(4, slot * 0.64)
        for index, row in enumerate(result.classes):
            value = values[index]
            bar_h = (float(value) / float(max_value)) * plot_h if max_value else 0
            x_mid = left + slot * index + slot / 2
            x0 = x_mid - bar_w / 2
            x1 = x_mid + bar_w / 2
            y0 = base_y - bar_h
            color = _STATUS_COLORS.get(row.status, _STATUS_COLORS["OK"])
            self.chart.create_rectangle(x0, y0, x1, base_y, fill=color, outline="")
            self.chart.create_text(x_mid, base_y + 12, text=row.symbol, fill=muted, font=("Segoe UI", 7))
        self.chart.create_text(8, top, anchor=tk.W, text=str(max_value), fill=muted, font=("Segoe UI", 7))
        self.chart.create_text(8, base_y, anchor=tk.W, text="0", fill=muted, font=("Segoe UI", 7))

    def _save_before_artifacts(self) -> None:
        if self.result is None or self.window is None:
            return
        try:
            refs = save_character_distribution_artifacts(
                self.result,
                self.dataset_root / "analysis",
                prefix="character_class_distribution_before",
            )
        except Exception as exc:
            messagebox.showerror("Błąd zapisu before", str(exc), parent=self.window)
            return
        json_ref = refs.get("json", {})
        self.status_var.set(f"Zapisano before: {json_ref.get('path', '')}")

    def _show_balance_plan(self) -> None:
        if self.window is None:
            return
        if self.read_only:
            self.status_var.set("PZ2 pokazuje tylko raport reprezentacji MZ. Plan tworzymy w PZ1.")
            return
        target_ratio = self._target_ratio()
        self.status_var.set("Przygotowuję plan uzupełnienia MZ...")
        if self.plan_btn is not None:
            self.plan_btn.configure(state=tk.DISABLED)

        def worker() -> None:
            try:
                plan = plan_character_train_augmentation(
                    self.dataset_root,
                    target_ratio=target_ratio,
                )
                try:
                    real_sources = find_character_real_source_candidates(
                        self.dataset_root,
                        (self.dataset_root.parent,),
                        target_ratio=target_ratio,
                        candidate_limit_per_symbol=50,
                    )
                except Exception as exc:
                    logger.debug(f"Nie udało się wyszukać dodatkowych realnych źródeł MZ: {exc}")
                    real_sources = {}
            except Exception as exc:
                self._after(lambda: self._show_plan_error(str(exc)))
                return
            self._after(lambda: self._open_plan_dialog(plan, real_sources))

        threading.Thread(target=worker, daemon=True).start()

    def _show_plan_error(self, error_text: str) -> None:
        if self.plan_btn is not None:
            self.plan_btn.configure(state=tk.NORMAL if self.result is not None else tk.DISABLED)
        self.status_var.set("Nie udało się przygotować planu.")
        if self.window is not None and self.window.winfo_exists():
            messagebox.showerror("Błąd planu uzupełnienia", error_text, parent=self.window)

    def _open_plan_dialog(self, plan, real_sources: dict[str, dict]) -> None:
        if self.plan_btn is not None:
            self.plan_btn.configure(state=tk.NORMAL if self.result is not None else tk.DISABLED)
        if self.window is None or not self.window.winfo_exists():
            return
        self.status_var.set("Plan uzupełnienia gotowy do podglądu.")
        bg = self.palette.get("bg", "#1e1f22")
        fg = self.palette.get("fg", "#f3f3f3")
        muted = self.palette.get("muted", "#b7bcc6")
        panel = self.palette.get("panel", "#25262b")
        dialog = tk.Toplevel(self.window)
        dialog.title("Plan AUTO reprezentacji MZ")
        dialog.minsize(820, 520)
        dialog.geometry("940x600")
        dialog.configure(bg=bg)
        try:
            dialog.transient(self.window)
        except Exception:
            pass
        root = tk.Frame(dialog, bg=bg, padx=14, pady=12)
        root.pack(fill=tk.BOTH, expand=True)
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(2, weight=1)
        tk.Label(
            root,
            text="Plan AUTO dla reprezentacji znaków MZ",
            bg=bg,
            fg=fg,
            font=("Segoe UI Semibold", 13),
            anchor=tk.W,
        ).grid(row=0, column=0, sticky="ew")
        total_deficit = sum(int(value or 0) for value in dict(plan.deficit_by_symbol or {}).values())
        deficient_symbols = list(dict(plan.deficit_by_symbol or {}).keys())
        real_total = sum(int(row.get("available_unused_real_sources", 0) or 0) for row in real_sources.values())
        planned_images = int(getattr(plan, "planned_images", 0) or 0)
        summary = (
            f"Próg AUTO: {int(getattr(plan, 'target_count', 0) or 0)} na klasę  |  "
            f"Niedoreprezentowane: {', '.join(deficient_symbols) if deficient_symbols else 'brak'}  |  "
            f"Brakuje łącznie: {total_deficit}  |  "
            f"Plan wstępny: +{planned_images} obrazów train  |  "
            f"Dodatkowe realne źródła do rozważenia: {real_total}"
        )
        tk.Label(
            root,
            text=summary,
            bg=bg,
            fg=muted,
            font=("Segoe UI", 9),
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=880,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10))
        table = ttk.Treeview(
            root,
            columns=("symbol", "train", "target", "missing_before", "missing_after", "status"),
            show="headings",
            height=16,
        )
        headings = {
            "symbol": "Znak",
            "train": "Train",
            "target": "Próg AUTO",
            "missing_before": "Brakuje teraz",
            "missing_after": "Po planie",
            "status": "Prognoza",
        }
        widths = {
            "symbol": 70,
            "train": 90,
            "target": 100,
            "missing_before": 120,
            "missing_after": 110,
            "status": 210,
        }
        for column in headings:
            table.heading(column, text=headings[column])
            table.column(column, width=widths[column], minwidth=60, stretch=column == "status")
        yscroll = ttk.Scrollbar(root, orient=tk.VERTICAL, command=table.yview)
        table.configure(yscrollcommand=yscroll.set)
        table.grid(row=2, column=0, sticky="nsew")
        yscroll.grid(row=2, column=1, sticky="ns")
        result_rows = {str(row.symbol): row for row in (getattr(self.result, "classes", []) or [])}
        predicted_after = dict(getattr(plan, "predicted_deficit_after", {}) or {})
        target_count = int(getattr(plan, "target_count", 0) or 0)
        for symbol in deficient_symbols:
            row = result_rows.get(str(symbol))
            before = int(dict(plan.deficit_by_symbol or {}).get(symbol, 0) or 0)
            after = int(predicted_after.get(symbol, 0) or 0)
            status = "OK po planie" if after <= 0 else f"Zostanie brak: {after}"
            table.insert(
                "",
                tk.END,
                values=(
                    symbol,
                    int(getattr(row, "train_count", 0) or 0) if row is not None else "-",
                    target_count,
                    before,
                    max(0, after),
                    status,
                ),
            )
        footer = tk.Frame(root, bg=bg)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        footer.grid_columnconfigure(0, weight=1)
        tk.Label(
            footer,
            text="Plan dotyczy tylko syntetycznego powiększenia train. Val i test pozostają bez zmian.",
            bg=bg,
            fg=muted,
            font=("Segoe UI", 8),
            anchor=tk.W,
        ).grid(row=0, column=0, sticky="ew")
        plan_feasible = bool(getattr(plan, "feasible", True))
        ttk.Button(
            footer,
            text=("Użyj planu w PZ1" if plan_feasible else "Plan niewykonalny"),
            command=lambda: self._accept_balance_plan(dialog, plan, real_sources),
            state=(tk.NORMAL if plan_feasible else tk.DISABLED),
        ).grid(row=0, column=1, sticky="e", padx=(8, 6))
        ttk.Button(footer, text="Zamknij", command=dialog.destroy).grid(row=0, column=2, sticky="e")
        try:
            self.window.update_idletasks()
            dialog.update_idletasks()
            width = int(dialog.winfo_width() or 940)
            height = int(dialog.winfo_height() or 600)
            x = int(self.window.winfo_rootx()) + max(20, (int(self.window.winfo_width()) - width) // 2)
            y = int(self.window.winfo_rooty()) + max(20, (int(self.window.winfo_height()) - height) // 2)
            dialog.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            pass

    def _accept_balance_plan(self, dialog: tk.Toplevel, plan, real_sources: dict[str, dict]) -> None:
        if self.read_only:
            self.status_var.set("PZ2 jest raportem: nie zapisuję planu augmentacji.")
            return
        planned_images = max(0, int(getattr(plan, "planned_images", 0) or 0))
        try:
            setattr(self.host, "_pending_character_balance_plan", plan)
            setattr(self.host, "_pending_character_balance_real_sources", dict(real_sources or {}))
            try:
                train = float(getattr(self.host, "train_pct").get())
                val = float(getattr(self.host, "val_pct").get())
                test = max(5.0, 100.0 - train - val)
                setattr(self.host, "_pending_character_balance_ratio_key", (round(train, 4), round(val, 4), round(test, 4)))
            except Exception:
                pass
            enabled_var = getattr(self.host, "split_aug_enabled_var", None)
            extra_var = getattr(self.host, "split_aug_extra_var", None)
            sample_var = getattr(self.host, "split_aug_sample_var", None)
            if enabled_var is not None:
                enabled_var.set(planned_images > 0)
            if extra_var is not None:
                extra_var.set(planned_images)
            if sample_var is not None:
                sample_var.set(max(1, planned_images))
            status_var = getattr(self.host, "split_mz_representation_status_var", None)
            if status_var is not None:
                target_count = int(getattr(plan, "target_count", 0) or 0)
                deficits = dict(getattr(plan, "deficit_by_symbol", {}) or {})
                status_var.set(
                    f"Próg AUTO: {target_count}. "
                    f"Niedoreprezentowane: {', '.join(deficits.keys()) if deficits else 'brak'}. "
                    f"Plan wstępny: +{planned_images} obrazów train. "
                    "Finalny plan zostanie przeliczony na tworzonym wariancie."
                )
            refresher = getattr(self.host, "_refresh_step4_augmentation_summary", None)
            if callable(refresher):
                refresher("char")
        except Exception:
            pass
        self.status_var.set("Plan wstępny MZ zapisany dla PZ1.")
        try:
            dialog.destroy()
        except Exception:
            pass

    def _export_csv(self) -> None:
        if self.result is None or self.window is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=self.window,
            title="Zapisz analizę rozkładu klas jako CSV",
            initialdir=str(self.dataset_root),
            initialfile="mz_class_distribution.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Wszystkie pliki", "*.*")],
        )
        if not selected:
            return
        try:
            output = save_character_class_distribution_csv(self.result, selected)
        except Exception as exc:
            messagebox.showerror("Błąd zapisu CSV", str(exc), parent=self.window)
            return
        self.status_var.set(f"Zapisano CSV: {output}")

    def _export_json(self) -> None:
        if self.result is None or self.window is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=self.window,
            title="Zapisz analizę rozkładu klas jako JSON",
            initialdir=str(self.dataset_root),
            initialfile="mz_class_distribution.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Wszystkie pliki", "*.*")],
        )
        if not selected:
            return
        try:
            output = save_character_class_distribution_json(self.result, selected)
        except Exception as exc:
            messagebox.showerror("Błąd zapisu JSON", str(exc), parent=self.window)
            return
        self.status_var.set(f"Zapisano JSON: {output}")

    def _dataset_label(self) -> str:
        try:
            counts = self.host._get_dataset_split_image_counts(self.dataset_root)
        except Exception:
            counts = {}
        try:
            ref = build_dataset_display_ref(self.dataset_root, target_hint="char", counts=counts)
            return ref.detail_label
        except Exception:
            return str(self.dataset_root)

    def _center(self) -> None:
        if self.window is None:
            return
        center = getattr(self.app, "_center_dialog_window", None)
        if callable(center):
            try:
                center(self.window, parent=getattr(self.app, "root", None), width=1160, height=740)
                return
            except Exception:
                pass
        try:
            self.window.update_idletasks()
            width = int(self.window.winfo_width() or 1160)
            height = int(self.window.winfo_height() or 740)
            screen_w = int(self.window.winfo_screenwidth())
            screen_h = int(self.window.winfo_screenheight())
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 2)
            self.window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            pass

    def _border(self) -> str:
        return self.palette.get("panel_border", self.palette.get("border", "#3b3d46"))

    def _after(self, callback) -> None:
        window = self.window
        if window is None:
            return
        try:
            if window.winfo_exists():
                window.after(0, callback)
        except Exception:
            pass


def _status_tag(status: str) -> str:
    return "class_balance_" + str(status or "OK").lower().replace("+", "_").replace("-", "_")


def _format_percent(value: float) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "0.00%"


def _format_float(value) -> str:
    try:
        numeric = float(value)
    except Exception:
        return "-"
    if abs(numeric - round(numeric)) < 0.0001:
        return str(int(round(numeric)))
    return f"{numeric:.2f}"


def _symbols(values) -> str:
    if not values:
        return "brak"
    try:
        items = [str(item) for item in values if str(item)]
    except Exception:
        items = []
    return ", ".join(items) if items else "brak"


def _layout_label(layout: str) -> str:
    if layout == "split":
        return "train / val / test"
    if layout == "flat":
        return "niesplitowany: liczymy razem"
    return "brak etykiet"
