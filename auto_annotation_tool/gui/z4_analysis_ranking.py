#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka Treningu: trening YOLO + analiza modeli.

W trybie swobodnym Z4 konsumuje gotowy dataset z Z2 lub Z3.
Pomost datasetowy pozostaje tylko na potrzeby kampanii.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import datetime
import time
import webbrowser
import csv
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..campaign_manager import CAMPAIGN
from ..config import (
    CONFIG,
    YOLO_AVAILABLE,
    AVAILABLE_POSE_MODELS,
    AVAILABLE_DETECT_MODELS,
    PIL_AVAILABLE,
    get_torch_module,
    get_yolo_class,
    is_cuda_available,
    logger,
)
from ..icons import IconManager
from ..validators import validate_model_file, format_yolo_model_identity
from ..training import YOLOPoseTrainer, TrainingHistory, TrainingStatus, DatasetCreator, DatasetSplitter
from ..training.training_report import TrainingReportGenerator
from ..ranking import ModelRanking, format_ranking_model_label, is_plate_pose_model_path
from ..utils import cleanup_gpu_memory, safe_load_yaml, get_image_files
from .help_manager import HELP
from .inertial_scroll import InertialScrollController
from .section_header_label import SectionHeaderLabel
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors
from .zoomable_canvas import ZoomableCanvas
from .z4_train_progress_bar import TrainProgressBar
from .z4_campaign_flow import (
    build_step4_campaign_navigation_view_model,
    build_step4_dataset_workflow_view_model,
    build_step4_training_inputs_view_model,
    clear_campaign_context,
    complete_campaign_project,
    finish_campaign_step4,
    get_campaign_training_target,
    open_campaign_step4_entry,
    poll_training_completion,
    restore_step4_campaign_project_state,
    set_campaign_context,
    set_campaign_training_target,
)
from .z4_flow_models import (
    CharYoloDatasetSourceAdapter,
    PlateXmlImagesSourceAdapter,
    TrainingSource,
    TrainingSourceStats,
)
from .z4_free_mode_flow import (
    refresh_free_training_route_cards,
    refresh_free_training_route_ui,
    update_step4_notebook_mode,
)
from .z4_shared_ui import (
    accept_training_input_context,
    clear_step4_guidance,
    guide_step4_builder_action,
    guide_step4_finish_action,
    guide_step4_next_action,
    guide_step4_route_selection,
    mark_step4_dataset_ready,
    open_step4_dataset_stage,
    refresh_step4_campaign_builder_inputs_ui,
    refresh_step4_analysis_tab_visibility,
    refresh_step4_campaign_navigation_ui,
    refresh_step4_dataset_mode_ui,
    refresh_step4_training_inputs_mode_ui,
    set_step4_dataset_mode,
    sync_step4_analysis_nav_buttons,
    step4_dataset_go_back,
    step4_dataset_go_next,
    step4_train_go_back,
)
from . import z4_dataset_sources
from . import z4_training_metrics
from . import z4_dataset_builder
from .z4_view_models import (
    Step4CampaignNavigationViewModel,
    Step4DatasetWorkflowViewModel,
    Step4TrainingInputsViewModel,
)

NAV_BUTTON_WIDTH = 18

if PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageFont

YOLO = None
def _collect_run_analysis_paths(self, run) -> list[Path]:
    if run is None:
        return []

    run_dir = Path(getattr(run, "output_dir", "") or "")
    if not run_dir.exists():
        return []

    train_dir = run_dir / "train"
    try:
        if (train_dir / "results.csv").exists():
            TrainingReportGenerator.generate_csv_charts(train_dir, run_dir / "plots")
    except Exception as e:
        logger.debug(f"Nie udało się odświeżyć czytelnych wykresów results.csv: {e}")

    priority_order = (
        "results_metrics_from_csv",
        "train_val_losses_from_csv",
        "train_learning_rate_from_csv",
        "results",
        "confusion_matrix",
        "pr_curve",
        "f1_curve",
        "p_curve",
        "r_curve",
        "labels",
        "val",
        "train",
    )

    candidates: list[Path] = []
    for path in run_dir.rglob("*"):
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        lower_name = path.name.lower()
        if any(token in lower_name for token in priority_order):
            candidates.append(path)

    def sort_key(path: Path):
        lower_name = path.name.lower()
        priority = next((idx for idx, token in enumerate(priority_order) if token in lower_name), len(priority_order))
        return (priority, lower_name)

    native_paths = sorted(candidates, key=sort_key)
    if native_paths:
        return native_paths

    return self._build_fallback_run_analysis_paths(run)

def _load_run_results_csv_rows(self, run) -> list[dict[str, str]]:
    if run is None:
        return []

    run_dir = Path(getattr(run, "output_dir", "") or "")
    csv_path = run_dir / "train" / "results.csv"
    if not csv_path.exists():
        return []

    rows: list[dict[str, str]] = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if isinstance(row, dict):
                    rows.append({str(k or "").strip(): str(v or "").strip() for k, v in row.items()})
    except Exception as e:
        logger.debug(f"Nie udało się odczytać results.csv dla analizy runu: {e}")
        return []
    return rows

def _run_analysis_font():
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def _wrap_run_analysis_line(self, label: str, value: str, width: int = 110) -> list[str]:
    base = f"{label}: {value}".strip()
    if not base:
        return [""]
    return textwrap.wrap(base, width=width, break_long_words=False, break_on_hyphens=False) or [base]

def _render_run_analysis_sheet(
    self,
    title: str,
    sections: list[tuple[str, list[str]]],
    out_path: Path,
    *,
    width: int = 1500,
) -> Path | None:
    if not PIL_AVAILABLE:
        return None

    font = self._run_analysis_font()
    line_height = 24
    section_gap = 18
    top_pad = 28
    left_pad = 30
    right_pad = 30
    bottom_pad = 28

    total_lines = 2
    for heading, lines in sections:
        total_lines += 1
        total_lines += max(1, len(lines))
        total_lines += 1

    height = max(420, top_pad + bottom_pad + total_lines * line_height + max(0, len(sections) - 1) * section_gap)
    img = Image.new("RGB", (int(width), int(height)), color="#1f2933")
    draw = ImageDraw.Draw(img)

    title_color = "#e8f6ef"
    heading_color = "#8fd19e"
    text_color = "#d8dee9"
    muted_color = "#94a3b8"
    accent_color = "#2d6a4f"

    y = top_pad
    draw.text((left_pad, y), title, fill=title_color, font=font)
    y += line_height + 8
    draw.line((left_pad, y, width - right_pad, y), fill=accent_color, width=2)
    y += 16

    for heading, lines in sections:
        draw.text((left_pad, y), heading, fill=heading_color, font=font)
        y += line_height
        section_lines = lines or ["Brak danych."]
        for line in section_lines:
            color = muted_color if str(line or "").strip() == "Brak danych." else text_color
            draw.text((left_pad + 10, y), str(line or ""), fill=color, font=font)
            y += line_height
        y += section_gap

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return out_path
    except Exception as e:
        logger.debug(f"Nie udało się zapisać syntetycznej planszy analizy runu: {e}")
        return None

def _analysis_plot_info(self, path: Path | str) -> tuple[str, str]:
    name = Path(path).name
    lower = name.lower()
    if lower.startswith("00_podsumowanie") or "podsumowanie" in lower:
        return (
            "Podsumowanie runu",
            "Syntetyczna karta z najważniejszymi ustawieniami i metrykami. To pierwszy punkt kontroli: czy run dotyczy właściwego datasetu, modelu i toru.",
        )
    if "results_metrics_from_csv" in lower:
        return (
            "Czytelne metryki walidacyjne",
            "Wykres z results.csv. B oznacza ramki obiektów, P punkty/narożniki modelu pose. Precision mówi, ile predykcji było trafnych, recall ile obiektów model odnalazł. mAP50 jest łagodniejszą oceną, a mAP50-95 surowszą miarą jakości.",
        )
    if "train_val_losses_from_csv" in lower:
        return (
            "Czytelne straty train/val",
            "Wykres z results.csv. Train to błąd na zbiorze treningowym, val na walidacyjnym. Box dotyczy położenia ramki, cls klasy, dfl granic ramki, pose narożników. Loss powinien maleć; rozjazd train/val może oznaczać przeuczenie.",
        )
    if "train_learning_rate_from_csv" in lower:
        return (
            "Learning rate w czasie treningu",
            "Wykres pokazuje harmonogram współczynnika uczenia. pg0, pg1 i pg2 to grupy parametrów optymalizatora. To nie jest miara jakości modelu, tylko kontekst wyjaśniający tempo zmian metryk i ewentualne skoki loss.",
        )
    if lower.startswith("01_przebieg") or "results" in lower:
        return (
            "Przebieg treningu: loss i mAP",
            "Patrz na trend: loss powinien maleć, a mAP50 oraz mAP50-95 rosnąć lub stabilizować się. Nagłe skoki, spadki albo rozjazd metryk sugerują za mały zbiór, przeuczenie albo niestabilny trening.",
        )
    if "confusion_matrix" in lower:
        return (
            "Macierz pomyłek",
            "Pokazuje, które klasy model myli ze sobą. Najlepiej, gdy dominują wartości na przekątnej. Mocne pola poza przekątną wskazują klasy wymagające lepszych danych lub korekty etykiet.",
        )
    if "pr_curve" in lower:
        return (
            "Krzywa Precision-Recall",
            "Pokazuje kompromis między precyzją a czułością. Im bliżej prawego górnego obszaru, tym stabilniejszy model. Słaba krzywa oznacza, że model gubi obiekty albo generuje dużo fałszywych trafień.",
        )
    if "f1_curve" in lower:
        return (
            "F1 względem progu pewności",
            "Pomaga dobrać próg confidence. Szczyt krzywej pokazuje okolice najlepszego kompromisu między precision i recall.",
        )
    if "p_curve" in lower:
        return (
            "Precision względem progu pewności",
            "Pokazuje, jak rośnie czystość predykcji po podnoszeniu progu confidence. Wysoka precyzja oznacza mniej fałszywych trafień.",
        )
    if "r_curve" in lower:
        return (
            "Recall względem progu pewności",
            "Pokazuje, ile właściwych obiektów model odnajduje przy różnych progach confidence. Spadek recall przy wysokim progu jest normalny.",
        )
    if "labels" in lower:
        return (
            "Rozkład etykiet w datasecie",
            "Kontrola danych wejściowych: liczność klas, położenia i rozmiary anotacji. Nierówny rozkład może tłumaczyć słabsze wyniki wybranych klas.",
        )
    if "val" in lower and "pred" in lower:
        return (
            "Predykcje na walidacji",
            "Podgląd tego, co model faktycznie przewiduje na obrazach walidacyjnych. Szukaj przesuniętych ramek, braków i podwójnych detekcji.",
        )
    if "val" in lower and ("label" in lower or "labels" in lower):
        return (
            "Etykiety walidacyjne",
            "Materiał odniesienia dla predykcji walidacyjnych. Porównaj z widokiem predykcji, aby zrozumieć, czy problem leży w modelu czy w danych.",
        )
    if "train" in lower:
        return (
            "Próbka treningowa",
            "Podgląd obrazów używanych w treningu. Sprawdź, czy anotacje wyglądają poprawnie i czy augmentacje nie zniekształcają materiału.",
        )
    return (
        name,
        "Artefakt zapisany przez trening. Jeśli nie jest jasny, porównaj go z results.csv i podglądem predykcji walidacyjnych.",
    )

def _analysis_plot_list_label(self, path: Path | str) -> str:
    title, _description = _analysis_plot_info(self, path)
    name = Path(path).name
    if title == name:
        return name
    return f"{title}  |  {name}"

def _build_fallback_run_analysis_paths(self, run) -> list[Path]:
    if run is None or not PIL_AVAILABLE:
        return []

    run_dir = Path(getattr(run, "output_dir", "") or "")
    if not run_dir.exists():
        return []

    cache_dir = run_dir / "_analysis_cache"
    detail_rows = self._build_training_run_detail_rows(run)
    metric_rows = self._build_training_run_metric_rows(run)
    csv_rows = self._load_run_results_csv_rows(run)

    sections_summary: list[tuple[str, list[str]]] = [
        (
            "Podsumowanie runu",
            [
                line
                for label, value in detail_rows
                for line in self._wrap_run_analysis_line(label, value, width=118)
            ] or ["Brak danych."],
        ),
        (
            "Najważniejsze metryki",
            [
                f"{label}: ostatnia {current} | najlepsza {best} | ocena {band}"
                for label, current, best, band in metric_rows
            ] or ["Brak danych."],
        ),
    ]

    epoch_lines: list[str] = []
    if csv_rows:
        for row in csv_rows[-12:]:
            epoch_value = str(row.get("epoch", "") or row.get("Epoch", "") or "-").strip()
            loss_value = str(
                row.get("train/box_loss", "")
                or row.get("train/loss", "")
                or row.get("loss", "")
                or "-"
            ).strip()
            map50_value = str(
                row.get("metrics/mAP50(B)", "")
                or row.get("metrics/mAP50", "")
                or row.get("map50", "")
                or "-"
            ).strip()
            map95_value = str(
                row.get("metrics/mAP50-95(B)", "")
                or row.get("metrics/mAP50-95", "")
                or row.get("map50_95", "")
                or "-"
            ).strip()
            epoch_lines.append(
                f"Epoka {epoch_value}: loss {loss_value} | mAP50 {map50_value} | mAP50-95 {map95_value}"
            )
    else:
        history = list(getattr(run, "metrics_history", []) or [])
        for item in history[-12:]:
            epoch_lines.append(
                "Epoka "
                f"{int(item.get('epoch', 0) or 0)}: "
                f"loss {float(item.get('loss', 0.0) or 0.0):.4f} | "
                f"mAP50 {float(item.get('map50', 0.0) or 0.0):.4f} | "
                f"mAP50-95 {float(item.get('map50_95', 0.0) or 0.0):.4f}"
            )

    sections_epochs: list[tuple[str, list[str]]] = [
        (
            "Przebieg epok",
            epoch_lines or ["Brak danych epok w results.csv ani metrics_history."],
        ),
        (
            "Artefakty runu",
            [
                f"Folder runu: {self._format_workspace_relative_path(run_dir)}",
                f"Plik wyników CSV: {self._format_workspace_relative_path(run_dir / 'train' / 'results.csv') if (run_dir / 'train' / 'results.csv').exists() else 'brak'}",
                f"Najlepsze wagi: {self._format_workspace_relative_path(getattr(run, 'best_weights', '') or '-')}",
                f"Checkpoint last.pt: {self._format_workspace_relative_path(getattr(run, 'last_weights', '') or '-')}",
            ],
        ),
    ]

    generated: list[Path] = []
    summary_path = cache_dir / "00_podsumowanie_runu.png"
    epochs_path = cache_dir / "01_przebieg_epok.png"

    rendered_summary = self._render_run_analysis_sheet(
        "Analiza runu treningowego",
        sections_summary,
        summary_path,
    )
    if rendered_summary is not None:
        generated.append(rendered_summary)

    rendered_epochs = self._render_run_analysis_sheet(
        "Przebieg treningu i artefakty",
        sections_epochs,
        epochs_path,
    )
    if rendered_epochs is not None:
        generated.append(rendered_epochs)

    return generated

def _close_analysis_dialog(self):
    dialog = getattr(self, "_analysis_dialog", None)
    if dialog is not None:
        try:
            dialog.destroy()
        except Exception:
            pass
    self._analysis_dialog = None
    self._analysis_dialog_shell = None
    self._analysis_plot_paths = []
    self._analysis_plot_canvas = None
    self._analysis_plots_list = None
    self._analysis_plot_title_lbl = None
    self._analysis_plot_hint_lbl = None

def _style_analysis_dialog(self):
    dialog = getattr(self, "_analysis_dialog", None)
    if dialog is None:
        return
    try:
        if not dialog.winfo_exists():
            return
    except Exception:
        return

    palette = getattr(self.app, "palette", {})
    try:
        dialog.configure(bg=palette.get("bg", "#1e1e1e"))
    except Exception:
        pass
    try:
        self.app.style_panel_surface(
            getattr(self, "_analysis_dialog_shell", None),
            background=palette.get("panel", "#252526"),
        )
    except Exception:
        pass
    try:
        self.app.style_listbox_widget(
            getattr(self, "_analysis_plots_list", None),
            bordercolor=palette.get("console_border", palette.get("border", "#3c3c3c")),
        )
    except Exception:
        pass
    try:
        self.app.style_canvas_widget(
            getattr(self, "_analysis_plot_canvas", None),
            background=palette.get("panel", "#252526"),
            bordercolor=palette.get("console_border", palette.get("border", "#3c3c3c")),
        )
    except Exception:
        pass

def _populate_analysis_dialog(self, plot_paths: list[Path]):
    self._analysis_plot_paths = list(plot_paths or [])
    listbox = getattr(self, "_analysis_plots_list", None)
    if listbox is None:
        return

    try:
        listbox.delete(0, tk.END)
    except Exception:
        pass

    for path in self._analysis_plot_paths:
        try:
            listbox.insert(tk.END, self._analysis_plot_list_label(path))
        except Exception:
            continue

    if self._analysis_plot_paths:
        try:
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(0)
            listbox.activate(0)
        except Exception:
            pass
        self._show_analysis_plot(self._analysis_plot_paths[0])

def _open_run_analysis_window(self, run):
    palette = getattr(self.app, "palette", {})
    plot_paths = self._collect_run_analysis_paths(run)
    if not plot_paths:
        return messagebox.showinfo(
            "Brak wykresow",
            "Dla wybranego runu nie znaleziono artefaktow analitycznych Ultralytics.",
        )

    if not PIL_AVAILABLE:
        self._open_run_folder()
        return messagebox.showinfo(
            "Brak podgladu obrazów",
            "Brakuje biblioteki PIL, wiec otworzylem folder runu zamiast podgladu wykresow.",
        )

    dialog = getattr(self, "_analysis_dialog", None)
    dialog_exists = False
    if dialog is not None:
        try:
            dialog_exists = bool(dialog.winfo_exists())
        except Exception:
            dialog_exists = False

    if not dialog_exists:
        dialog = tk.Toplevel(self.frame)
        dialog.title("Analiza treningu")
        dialog.geometry("1360x820")
        dialog.minsize(1120, 680)
        dialog.transient(self.frame.winfo_toplevel())
        dialog.resizable(True, True)
        dialog.protocol("WM_DELETE_WINDOW", self._close_analysis_dialog)
        self._analysis_dialog = dialog

        shell = ttk.Frame(dialog, padding=10, style="Panel.TFrame")
        shell.pack(fill=tk.BOTH, expand=True)
        self._analysis_dialog_shell = shell

        ttk.Label(
            shell,
            text="Artefakty treningu Ultralytics dla wybranego runu. Po lewej wybierasz wykres, po prawej masz podgląd i krótką interpretację.",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=1180,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

        pane = ttk.PanedWindow(shell, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(pane, text=" Wykresy ", padding=8)
        right = ttk.LabelFrame(pane, text=" Podgląd i interpretacja ", padding=8)
        pane.add(left, weight=2)
        pane.add(right, weight=5)

        list_shell = ttk.Frame(left, style="Panel.TFrame")
        list_shell.pack(fill=tk.BOTH, expand=True)
        self._analysis_plots_list = tk.Listbox(
            list_shell,
            height=16,
            font=("Consolas", 9),
            activestyle="none",
            exportselection=False,
        )
        self._analysis_plots_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll = WebSlimScrollbar(list_shell, orient=tk.VERTICAL, command=self._analysis_plots_list.yview)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._analysis_plots_list.configure(yscrollcommand=list_scroll.set)
        self._analysis_plots_list.bind("<<ListboxSelect>>", self._on_analysis_plot_selected)

        canvas_shell = ttk.Frame(right, style="Panel.TFrame")
        canvas_shell.pack(fill=tk.BOTH, expand=True)

        plot_info = ttk.Frame(canvas_shell, style="Panel.TFrame")
        plot_info.pack(fill=tk.X, pady=(0, 8))
        self._analysis_plot_title_lbl = ttk.Label(
            plot_info,
            text="Wybierz wykres",
            style="PanelTitle.TLabel",
            anchor=tk.W,
        )
        self._analysis_plot_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self._analysis_plot_hint_lbl = ttk.Label(
            plot_info,
            text="Po wyborze wykresu pokażę krótki opis i podpowiedź interpretacji.",
            style="PanelMuted.TLabel",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=860,
        )
        self._analysis_plot_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(3, 0))

        controls = ttk.Frame(canvas_shell, style="Panel.TFrame")
        controls.pack(fill=tk.X, pady=(0, 6))

        def _control_analysis_canvas(action: str):
            canvas = getattr(self, "_analysis_plot_canvas", None)
            if canvas is None or getattr(canvas, "original_image", None) is None:
                return "break"
            try:
                canvas.focus_set()
            except Exception:
                pass
            if action == "fit":
                canvas.fit_to_view()
            elif action == "reset":
                canvas.reset_view()
            elif action in ("zoom_in", "zoom_out"):
                try:
                    factor = 1.22 if action == "zoom_in" else (1.0 / 1.22)
                    state = canvas.get_view_state()
                    state["zoom_level"] = max(
                        float(getattr(canvas, "min_zoom", 0.1) or 0.1),
                        min(
                            float(getattr(canvas, "max_zoom", 5.0) or 5.0),
                            float(state.get("zoom_level", getattr(canvas, "zoom_level", 1.0)) or 1.0) * factor,
                        ),
                    )
                    canvas.set_view_state(state, redraw=True)
                except Exception:
                    pass
            elif action == "info":
                try:
                    canvas.show_info = not bool(getattr(canvas, "show_info", True))
                    canvas.refresh_overlay_only(skip_info=False)
                except Exception:
                    pass
            return "break"

        ttk.Label(
            controls,
            text="Podgląd:",
            style="PanelMuted.TLabel",
        ).pack(side=tk.LEFT, padx=(0, 6))
        for label, action in (
            ("Dopasuj", "fit"),
            ("Reset", "reset"),
            ("Zoom +", "zoom_in"),
            ("Zoom -", "zoom_out"),
            ("Info", "info"),
        ):
            ttk.Button(
                controls,
                text=label,
                command=lambda a=action: _control_analysis_canvas(a),
                style="WorkflowCard.TButton",
            ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(
            controls,
            text="Rolka: zoom | LPM + drag: przesuwanie | R/Home: reset | I: info",
            style="PanelMuted.TLabel",
        ).pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

        self._analysis_plot_canvas = ZoomableCanvas(
            canvas_shell,
            bg=palette.get("panel", "#252526"),
            highlightthickness=0,
        )
        try:
            self._analysis_plot_canvas.resampling_quality = Image.Resampling.LANCZOS
        except Exception:
            pass
        self._analysis_plot_canvas.pack(fill=tk.BOTH, expand=True)
        self._analysis_plot_canvas.bind("<Double-1>", lambda _event: _control_analysis_canvas("fit"), add="+")
        dialog.bind("<r>", lambda _event: _control_analysis_canvas("reset"), add="+")
        dialog.bind("<R>", lambda _event: _control_analysis_canvas("reset"), add="+")
        dialog.bind("<Home>", lambda _event: _control_analysis_canvas("reset"), add="+")
        dialog.bind("<i>", lambda _event: _control_analysis_canvas("info"), add="+")
        dialog.bind("<I>", lambda _event: _control_analysis_canvas("info"), add="+")

    try:
        self._analysis_dialog.title(f"Analiza treningu | {self._shorten_training_text(getattr(run, 'name', ''), 48)}")
        self._analysis_dialog.deiconify()
        self._analysis_dialog.lift()
        self._analysis_dialog.focus_force()
    except Exception:
        pass

    self._style_analysis_dialog()
    self._populate_analysis_dialog(plot_paths)

def _open_selected_run_analysis(self, event=None):
    if event is not None and hasattr(self, "tree") and getattr(event, "y", None) is not None:
        try:
            row_id = self.tree.identify_row(event.y)
        except Exception:
            row_id = ""
        if not row_id:
            return
        try:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
        except Exception:
            pass
        self._on_run_selected()

    run = self._selected_run()
    if run is None:
        return
    self._open_run_analysis_window(run)

def _collect_project_plate_ranking_model_candidates(self) -> list[Path]:
    if not CAMPAIGN.get_active_project_name():
        return []

    histories: list[TrainingHistory] = []
    try:
        project_root = CAMPAIGN.get_active_project_root_dir()
        if project_root is not None:
            project_runs_dir = Path(project_root) / "5_training_runs"
            if project_runs_dir.exists():
                histories.append(TrainingHistory(history_dir=project_runs_dir))
    except Exception:
        pass

    current_history = getattr(self, "history", None)
    if current_history is not None:
        try:
            current_dir = Path(getattr(current_history, "history_dir", ""))
            known_dirs = {str(Path(getattr(item, "history_dir", "")).resolve()) for item in histories}
            if str(current_dir.resolve()) not in known_dirs:
                histories.append(current_history)
        except Exception:
            histories.append(current_history)

    candidates: list[Path] = []
    seen: set[str] = set()

    def add_path(path_like) -> None:
        if not path_like:
            return
        try:
            path = Path(path_like)
        except Exception:
            return
        if not path.exists() or not path.is_file():
            return
        try:
            key = str(path.resolve()).lower()
            resolved = path.resolve()
        except Exception:
            key = str(path).lower()
            resolved = path
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    for history in histories:
        try:
            runs = list(history.get_all_runs() or [])
        except Exception:
            runs = []
        for run in runs:
            status = str(getattr(run, "status", "") or "").strip().lower()
            if status != TrainingStatus.COMPLETED.value:
                continue
            try:
                target = str(self._infer_history_run_target(run) or "").strip().lower()
            except Exception:
                target = ""
            if target != "plate":
                continue
            try:
                add_path(self._resolve_history_run_best_weights(run))
            except Exception:
                pass

    try:
        explicit_project_model = str(CAMPAIGN.get_global_model("plate") or "").strip()
        if explicit_project_model:
            add_path(explicit_project_model)
    except Exception:
        pass

    return candidates

def _collect_plate_ranking_model_candidates(self, models_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add_path(path_like, *, require_plate_name: bool = True) -> None:
        if not path_like:
            return
        try:
            path = Path(path_like)
        except Exception:
            return
        if not path.exists() or not path.is_file():
            return
        if require_plate_name and not is_plate_pose_model_path(path):
            return
        try:
            resolved = path.resolve()
            key = str(resolved).lower()
        except Exception:
            resolved = path
            key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    try:
        for path in sorted(Path(models_dir).glob("*.pt")):
            add_path(path, require_plate_name=True)
    except Exception:
        pass

    for path in _collect_project_plate_ranking_model_candidates(self):
        # Projektowe runy zwykle zapisują wagę jako best.pt, więc domenę
        # bierzemy z historii treningu, a nie z nazwy pliku.
        add_path(path, require_plate_name=False)

    return candidates

def _on_analysis_plot_selected(self, event=None):
    listbox = getattr(self, "_analysis_plots_list", None)
    if listbox is None or not self._analysis_plot_paths:
        return
    selection = listbox.curselection()
    if not selection:
        return
    index = int(selection[0])
    if 0 <= index < len(self._analysis_plot_paths):
        self._show_analysis_plot(self._analysis_plot_paths[index])

def _show_analysis_plot(self, path):
    if not PIL_AVAILABLE:
        return
    try:
        title, description = self._analysis_plot_info(path)
        title_lbl = getattr(self, "_analysis_plot_title_lbl", None)
        hint_lbl = getattr(self, "_analysis_plot_hint_lbl", None)
        if title_lbl is not None:
            title_lbl.configure(text=title)
        if hint_lbl is not None:
            hint_lbl.configure(text=description)
        img = Image.open(path)
        self._analysis_plot_canvas.set_image(img)
        self._analysis_plot_canvas.fit_to_view()
    except Exception as e:
        logger.error(f"Nie udało się wyswietlic wykresu: {e}")

def _build_ranking_panel_v2(self, parent):
    palette = getattr(self.app, "palette", {})
    shell = ttk.Frame(parent, padding=10, style="Panel.TFrame")
    shell.pack(fill=tk.BOTH, expand=True)

    ranking_intro_lbl = ttk.Label(
        shell,
        text=(
            "Ranking porównuje modele i pomaga wybrać kandydata do pracy projektowej. "
            "Uruchamianie jest tutaj; źródła porównania są w Zaawansowanych."
        ),
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=760,
    )
    ranking_intro_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

    config_box = ttk.LabelFrame(shell, text=" Ranking modeli ", padding=10)
    config_box.pack(fill=tk.X, pady=(0, 10))

    self.rank_models_dir = tk.StringVar(value=str(self._get_ranking_models_default_dir()))
    self.rank_data_dir = tk.StringVar()
    self.rank_progress_var = tk.DoubleVar(value=0.0)
    self.btn_run_rank = None
    self.btn_cancel_rank = None
    self.rank_progress = None
    self.rank_reference_hint_lbl = None
    self._rank_advanced_modal = None

    rank_config_hint_lbl = ttk.Label(
        config_box,
        text=(
            "Start przelicza ranking dla aktualnego zakresu. Katalog modeli i materiał odniesienia zmienisz w Zaawansowanych."
        ),
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=760,
    )
    rank_config_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

    rank_actions = ttk.Frame(config_box, style="Panel.TFrame")
    rank_actions.pack(fill=tk.X, pady=(0, 8))
    rank_actions.columnconfigure(0, weight=2)
    rank_actions.columnconfigure(1, weight=1)
    rank_actions.columnconfigure(2, weight=1)

    self.btn_run_rank = ttk.Button(
        rank_actions,
        text="Uruchom porównanie",
        style="Accent.TButton",
        command=self._run_ranking_v2,
    )
    self.btn_run_rank.grid(row=0, column=0, sticky="ew", padx=(0, 6), ipady=4)
    self.btn_cancel_rank = ttk.Button(
        rank_actions,
        text="Anuluj",
        command=self._cancel_ranking_v2,
        state=tk.DISABLED,
    )
    self.btn_cancel_rank.grid(row=0, column=1, sticky="ew", padx=(6, 6), ipady=4)
    self.btn_open_rank_advanced = ttk.Button(
        rank_actions,
        text="Zaawansowane",
        command=self._open_ranking_advanced_modal,
    )
    self.btn_open_rank_advanced.grid(row=0, column=2, sticky="ew", padx=(6, 0), ipady=4)

    self.rank_progress = TrainProgressBar(
        config_box,
        variable=self.rank_progress_var,
        mode="determinate",
        thickness=6,
        trough_color=palette.get("panel_alt", palette.get("panel", "#252526")),
        fill_color=palette.get("accent_hover", palette.get("accent", "#0e639c")),
        bg=palette.get("panel", "#252526"),
        height=10,
    )
    self.rank_progress.pack(fill=tk.X, pady=(0, 4))

    self.rank_status = ttk.Label(config_box, text="Gotowy", style="PanelMuted.TLabel")
    self.rank_status.pack(anchor=tk.W, fill=tk.X)

    results_scroll_host = ttk.Frame(shell, style="Panel.TFrame")
    results_scroll_host.pack(fill=tk.BOTH, expand=True)
    results_scroll_host.grid_rowconfigure(0, weight=1)
    results_scroll_host.grid_columnconfigure(0, weight=1)

    results_canvas = tk.Canvas(
        results_scroll_host,
        bg=palette.get("panel", "#252526"),
        bd=0,
        highlightthickness=0,
    )
    results_canvas.grid(row=0, column=0, sticky="nsew")
    results_scrollbar = WebSlimScrollbar(
        results_scroll_host,
        orient=tk.VERTICAL,
        command=results_canvas.yview,
        auto_hide=False,
    )
    results_scrollbar.grid(row=0, column=1, sticky="ns")
    results_canvas.configure(yscrollcommand=results_scrollbar.set)

    results_content = ttk.Frame(results_canvas, style="Panel.TFrame")
    results_window = results_canvas.create_window((0, 0), window=results_content, anchor="nw")
    self.rank_results_canvas = results_canvas
    self.rank_results_content = results_content

    def _sync_results_scrollregion(_event=None):
        try:
            results_canvas.configure(scrollregion=results_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_results_canvas_width(event=None):
        try:
            width = max(360, int(results_canvas.winfo_width() or 0) - 2)
            results_canvas.itemconfigure(results_window, width=width)
        except Exception:
            pass
        _sync_results_scrollregion()

    def _on_results_mousewheel(event):
        try:
            direction = -1 if (getattr(event, "num", None) == 4 or int(getattr(event, "delta", 0)) > 0) else 1
            results_canvas.yview_scroll(direction * 3, "units")
            return "break"
        except Exception:
            return None

    def _bind_results_scroll_children(widget):
        if widget is not None:
            try:
                widget.bind("<MouseWheel>", _on_results_mousewheel, add="+")
                widget.bind("<Button-4>", _on_results_mousewheel, add="+")
                widget.bind("<Button-5>", _on_results_mousewheel, add="+")
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            return
        for child in children:
            _bind_results_scroll_children(child)

    results_content.bind("<Configure>", _sync_results_scrollregion, add="+")
    results_canvas.bind("<Configure>", _sync_results_canvas_width, add="+")
    results_canvas.bind("<MouseWheel>", _on_results_mousewheel, add="+")
    results_canvas.bind("<Button-4>", _on_results_mousewheel, add="+")
    results_canvas.bind("<Button-5>", _on_results_mousewheel, add="+")

    ttk.Label(
        results_content,
        text="Wyniki i kandydaci",
        style="Panel.TLabel",
        anchor=tk.W,
    ).pack(anchor=tk.W, fill=tk.X, pady=(0, 6))

    scope_row = ttk.Frame(results_content, style="Panel.TFrame")
    scope_row.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(scope_row, text="Pokaż:", style="PanelMuted.TLabel").pack(side=tk.LEFT, padx=(0, 8))
    default_scope = "Projekt" if CAMPAIGN.get_active_project_name() else "Wszystkie"
    self.rank_scope_var = tk.StringVar(value=default_scope)
    for label in ("Projekt", "Globalne", "Wszystkie"):
        ttk.Radiobutton(
            scope_row,
            text=label,
            value=label,
            variable=self.rank_scope_var,
            command=self._load_ranking,
        ).pack(side=tk.LEFT, padx=(0, 10))

    ranking_decision_hint_lbl = ttk.Label(
        results_content,
        text=(
            "Wybierz zakres, porównaj metryki i dopiero potem jawnie ustaw model projektowy."
        ),
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=520,
    )
    ranking_decision_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

    ranking_metrics_hint_lbl = ttk.Label(
        results_content,
        text=(
            "Metryki: F1 pokazuje równowagę między trafnością i kompletnością; "
            "precyzja mówi, ile wykryć było poprawnych; czułość mówi, ile prawdziwych tablic model odnalazł."
        ),
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=760,
    )
    ranking_metrics_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 10))

    def _sync_ranking_copy_wraps(_event=None):
        try:
            shell_width = max(420, int(shell.winfo_width() or 0) - 30)
        except Exception:
            shell_width = 760
        try:
            config_width = max(420, int(config_box.winfo_width() or shell_width) - 28)
        except Exception:
            config_width = shell_width
        for widget, width in (
            (ranking_intro_lbl, shell_width),
            (rank_config_hint_lbl, config_width),
            (ranking_decision_hint_lbl, shell_width),
            (ranking_metrics_hint_lbl, shell_width),
        ):
            try:
                widget.configure(wraplength=width)
            except Exception:
                pass

    shell.bind("<Configure>", _sync_ranking_copy_wraps, add="+")
    config_box.bind("<Configure>", _sync_ranking_copy_wraps, add="+")

    leader_bg = blend_hex_colors(
        palette.get("success", "#2ecc71"),
        palette.get("panel", "#252526"),
        0.88,
    )
    leader_border = blend_hex_colors(
        palette.get("success", "#2ecc71"),
        palette.get("panel_border", palette.get("border", "#3c3c3c")),
        0.48,
    )
    self.rank_leader_card = tk.Frame(
        results_content,
        bg=leader_bg,
        bd=0,
        highlightthickness=1,
        highlightbackground=leader_border,
        highlightcolor=leader_border,
    )
    self.rank_leader_card.pack(fill=tk.X, pady=(0, 10))
    self.rank_leader_title = tk.Label(
        self.rank_leader_card,
        text="Brak wyników dla wybranego zakresu",
        bg=leader_bg,
        fg=palette.get("fg", "#f3f3f3"),
        font=("Segoe UI", 10, "bold"),
        anchor=tk.W,
        padx=10,
        pady=4,
    )
    self.rank_leader_title.pack(fill=tk.X)
    self.rank_leader_hint = tk.Label(
        self.rank_leader_card,
        text="Ranking podpowiada kandydata. Model projektowy wybieramy jawnie.",
        bg=leader_bg,
        fg=palette.get("muted", "#c7c7c7"),
        font=("Segoe UI", 8),
        anchor=tk.W,
        justify=tk.LEFT,
        padx=10,
        pady=4,
    )
    self.rank_leader_hint.pack(fill=tk.X)

    table_frame = ttk.Frame(results_content, style="Panel.TFrame")
    table_frame.pack(fill=tk.BOTH, expand=True)
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)

    cols = ("Lp.", "Zakres", "Model", "F1", "Precyzja", "Czułość", "Próbka", "Zestaw", "Decyzja")
    self.rank_tree = ttk.Treeview(table_frame, columns=cols, show="headings")
    for c in cols:
        self.rank_tree.heading(c, text=c)
    self.rank_tree.column("Lp.", width=42, anchor=tk.CENTER, stretch=False)
    self.rank_tree.column("Zakres", width=58, minwidth=50, anchor=tk.CENTER, stretch=False)
    self.rank_tree.column("Model", width=340, minwidth=260, anchor=tk.W, stretch=False)
    self.rank_tree.column("F1", width=56, minwidth=48, anchor=tk.CENTER, stretch=False)
    self.rank_tree.column("Precyzja", width=74, minwidth=66, anchor=tk.CENTER, stretch=False)
    self.rank_tree.column("Czułość", width=74, minwidth=66, anchor=tk.CENTER, stretch=False)
    self.rank_tree.column("Próbka", width=62, minwidth=54, anchor=tk.CENTER, stretch=False)
    self.rank_tree.column("Zestaw", width=118, minwidth=96, anchor=tk.W, stretch=False)
    self.rank_tree.column("Decyzja", width=150, minwidth=120, anchor=tk.W, stretch=False)

    try:
        self.rank_tree.tag_configure(
            "leader",
            background=blend_hex_colors(
                palette.get("success", "#2ecc71"),
                palette.get("panel", "#252526"),
                0.86,
            ),
            foreground=palette.get("fg", "#f3f3f3"),
        )
        self.rank_tree.tag_configure(
            "project",
            foreground=palette.get("fg", "#f3f3f3"),
        )
        self.rank_tree.tag_configure(
            "global",
            foreground=palette.get("muted", "#c7c7c7"),
        )
    except Exception:
        pass

    yscroll = WebSlimScrollbar(table_frame, orient=tk.VERTICAL, command=self.rank_tree.yview)
    xscroll = WebSlimScrollbar(table_frame, orient=tk.HORIZONTAL, command=self.rank_tree.xview)
    self.rank_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    self.rank_tree.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    _bind_results_scroll_children(results_content)
    try:
        self.frame.after_idle(_sync_results_canvas_width)
    except Exception:
        pass

    HELP.bind_help(self.btn_open_rank_advanced, "tr_rank_conf")
    HELP.bind_help(self.btn_run_rank, "tr_rank_btn")
    HELP.bind_help(self.btn_cancel_rank, "tr_rank_btn")
    HELP.bind_help(config_box, "tr_rank_conf")
    HELP.bind_help(self.rank_tree, "tr_rank_table")
    self.rank_models_dir.trace_add("write", self._refresh_ranking_reference_ui)
    self.rank_data_dir.trace_add("write", self._refresh_ranking_reference_ui)
    self._prefill_ranking_reference_if_empty()
    self._refresh_ranking_reference_ui()

def _open_ranking_advanced_modal(self):
    existing = getattr(self, "_rank_advanced_modal", None)
    try:
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
    except Exception:
        pass

    palette = getattr(self.app, "palette", {})
    dialog = tk.Toplevel(getattr(self, "frame", None))
    self._rank_advanced_modal = dialog
    dialog.title("Zaawansowane porównanie modeli")
    dialog.configure(bg=palette.get("panel", "#252526"))
    try:
        dialog.transient(self.frame.winfo_toplevel())
    except Exception:
        pass

    def close_dialog():
        try:
            self.rank_reference_hint_lbl = None
            self.rank_advanced_status = None
            self._rank_advanced_modal = None
        except Exception:
            pass
        try:
            dialog.destroy()
        except Exception:
            pass

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    shell = ttk.Frame(dialog, padding=14, style="Panel.TFrame")
    shell.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        shell,
        text="Zaawansowane ustawienia rankingu",
        style="Panel.TLabel",
        anchor=tk.W,
    ).pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
    ttk.Label(
        shell,
        text=(
            "Tutaj zmieniasz tylko źródła porównania. Sam ranking uruchamiasz z głównej karty, "
            "żeby decyzja była widoczna bez wchodzenia w ustawienia techniczne."
        ),
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=520,
    ).pack(anchor=tk.W, fill=tk.X, pady=(0, 12))

    form = ttk.LabelFrame(shell, text=" Dane porównania ", padding=10)
    form.pack(fill=tk.X, pady=(0, 10))

    ttk.Label(form, text="Modele do porównania:", style="Panel.TLabel").pack(anchor=tk.W)
    row1 = ttk.Frame(form, style="Panel.TFrame")
    row1.pack(fill=tk.X, pady=(4, 9))
    ttk.Entry(row1, textvariable=self.rank_models_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Button(
        row1,
        text="Wybierz",
        command=lambda: self._pick_dir(
            self.rank_models_dir,
            initialdir=self._get_ranking_models_picker_dir(),
        ),
    ).pack(side=tk.RIGHT, padx=(8, 0))

    ttk.Label(form, text="Materiał odniesienia:", style="Panel.TLabel").pack(anchor=tk.W)
    row2 = ttk.Frame(form, style="Panel.TFrame")
    row2.pack(fill=tk.X, pady=(4, 8))
    ttk.Entry(row2, textvariable=self.rank_data_dir).pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Button(
        row2,
        text="Wybierz",
        command=lambda: self._pick_dir(
            self.rank_data_dir,
            initialdir=self._get_ranking_reference_picker_dir(),
        ),
    ).pack(side=tk.RIGHT, padx=(8, 0))

    self.rank_reference_hint_lbl = ttk.Label(
        form,
        text="Materiał odniesienia to zapisany run z obrazami i annotations.xml.",
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=520,
    )
    self.rank_reference_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

    ttk.Label(
        form,
        text=f"Próg wykrycia dla nowego porównania: {float(CONFIG.DEFAULT_CONFIDENCE):.2f}.",
        style="PanelMuted.TLabel",
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=520,
    ).pack(anchor=tk.W, fill=tk.X)

    self.rank_advanced_status = ttk.Label(
        shell,
        text="Po zmianie źródeł wróć do głównej karty i uruchom porównanie.",
        style="PanelMuted.TLabel",
    )
    self.rank_advanced_status.pack(anchor=tk.W, fill=tk.X)

    bottom = ttk.Frame(shell, style="Panel.TFrame")
    bottom.pack(fill=tk.X, pady=(12, 0))
    ttk.Button(bottom, text="Zamknij", command=close_dialog).pack(side=tk.RIGHT)

    HELP.bind_help(row1, "tr_rank_models")
    HELP.bind_help(row2, "tr_rank_reference")
    HELP.bind_help(self.rank_reference_hint_lbl, "tr_rank_reference")
    HELP.bind_help(form, "tr_rank_conf")

    self._prefill_ranking_reference_if_empty()
    self._refresh_ranking_reference_ui()
    self._refresh_ranking_start_state()

    try:
        dialog.update_idletasks()
        root = self.frame.winfo_toplevel()
        width = max(540, int(dialog.winfo_reqwidth() or 540))
        height = max(360, int(dialog.winfo_reqheight() or 360))
        x = int(root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2))
        y = int(root.winfo_rooty() + max(0, (root.winfo_height() - height) // 2))
        dialog.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        dialog.geometry("560x390")

def _run_ranking_v2(self):
    if self.rank_is_running:
        return

    self._ensure_plate_ranking_engine()
    models_dir_raw = str(getattr(self, "rank_models_dir", tk.StringVar()).get() or "").strip()
    reference_raw = str(getattr(self, "rank_data_dir", tk.StringVar()).get() or "").strip()
    models_dir = Path(models_dir_raw)

    if not models_dir.exists() or not models_dir.is_dir():
        return messagebox.showerror("Błąd", "Wskaż poprawny folder z modelami .pt.")

    target_task = "Tablice (Pose)"
    if not self._begin_step4_operation("z4.ranking.run", "Z4: ranking modeli"):
        return
    self.rank_is_running = True
    self.rank_cancel_requested = False
    try:
        self.btn_run_rank.config(state=tk.DISABLED)
    except Exception:
        pass
    try:
        self.rank_progress_var.set(0)
    except Exception:
        pass
    self._set_ranking_ui_state(
        status="Przygotowuję ranking...",
        status_color="gray",
        button_text="Przygotowanie...",
        cancel_enabled=True,
        preparing=True,
        progress_value=0,
    )
    self._append_ranking_log("Start przygotowania rankingu modeli tablic.")
    self._append_ranking_log(f"Folder modeli: {models_dir}")
    if reference_raw:
        self._append_ranking_log(f"Wybrany folder runu: {reference_raw}")
    else:
        self._append_ranking_log("Nie wskazano jeszcze folderu runu do porównania.")
    self._start_ranking_watchdog("start przygotowania rankingu")

    def worker():
        from ..ranking.annotation_comparator import AnnotationComparator
        from ..annotators.runtime_factory import create_plate_annotator
        from ..exporters.cvat_exporter import CVATExporter

        try:
            ranking_started_at = time.perf_counter()
            cancelled = False
            self._touch_ranking_watchdog("sprawdzanie folderu runu i zapisanych zmian")
            self._set_ranking_ui_state(
                status="Sprawdzam folder runu i zapisane zmiany...",
                status_color="gray",
                button_text="Przygotowanie...",
                cancel_enabled=True,
                preparing=True,
            )
            reference_info = self._resolve_ranking_reference_source(reference_raw)
            if not reference_info.get("ok"):
                self._append_ranking_log(str(reference_info.get("message") or "Nie udało się przygotować folderu runu."))
                self._ui(
                    lambda: messagebox.showerror(
                        "Błąd",
                        str(reference_info.get("message") or "Wskaż poprawny folder runu po sprawdzeniu tablic."),
                    )
                )
                return
            if not self.rank_is_running:
                cancelled = True
                self._append_ranking_log("Przerwano ranking po przygotowaniu folderu runu.")
                return

            self._append_ranking_log(
                f"Run odniesienia: {reference_info.get('reference_name') or '-'} | "
                f"obrazy: {int(reference_info.get('image_count', 0) or 0)}"
            )
            self._append_ranking_log(
                f"Przygotowanie folderu runu zajelo {time.perf_counter() - ranking_started_at:.1f}s."
            )
            self._touch_ranking_watchdog("szukanie modeli tablic Pose")

            self._set_ranking_ui_state(
                status="Szukam modeli tablic Pose...",
                status_color="gray",
                button_text="Przygotowanie...",
                cancel_enabled=True,
                preparing=True,
            )
            models_to_test = self._collect_plate_ranking_model_candidates(models_dir)
            if not self.rank_is_running:
                cancelled = True
                self._append_ranking_log("Przerwano ranking po odczytaniu listy modeli.")
                return

            if not models_to_test:
                self._append_ranking_log("Nie znaleziono modeli tablic Pose w katalogu modeli ani w ukończonych runach projektu.")
                self._ui(
                    lambda: messagebox.showinfo(
                        "Info",
                        "Brak modeli tablic Pose w katalogu modeli i w ukończonych treningach projektu.",
                    )
                )
                return

            gt_xml = Path(str(reference_info.get("xml_path") or "").strip())
            images = list(reference_info.get("image_paths") or [])
            if not gt_xml.exists() or not images:
                self._append_ranking_log("Wybrany folder runu nie zawiera kompletu obrazów i zapisanych zmian tablic.")
                self._ui(
                    lambda: messagebox.showerror(
                        "Błąd",
                        "Wybrany folder nie zawiera kompletu obrazów i zapisanych zmian tablic.",
                    )
                )
                return

            comparator = AnnotationComparator()
            selected_device_display = self._normalize_training_device_choice(self.device_var.get())
            effective_device_raw, effective_device_profile = self._get_effective_training_device_profile(selected_device_display)
            device = self._device_to_ultralytics(self.device_var.get())
            if effective_device_profile is not None:
                effective_device_desc = (
                    f"{effective_device_profile.get('name', effective_device_raw)} "
                    f"({float(effective_device_profile.get('memory_gb', 0.0) or 0.0):.1f} GB VRAM)"
                )
            else:
                effective_device_desc = "CPU"
            conf_thresh = float(CONFIG.DEFAULT_CONFIDENCE)
            total_models = len(models_to_test)
            temp_xml_path = Path(str(reference_info.get("reference_dir") or models_dir)) / "temp_ranking_auto.xml"
            self._append_ranking_log(
                f"Przygotowanie zakończone. Modele pose: {total_models} | obrazy do porównania: {len(images)}"
            )
            self._append_ranking_log(
                f"Urządzenie rankingu: {selected_device_display} -> {effective_device_desc} | backend Ultralytics: {device}"
            )
            self._set_ranking_ui_state(
                status=f"Porównywanie modeli... 0/{total_models}",
                status_color="gray",
                button_text="Porównywanie...",
                cancel_enabled=True,
                preparing=False,
                progress_value=0,
            )

            for idx, model_path in enumerate(models_to_test):
                if not self.rank_is_running:
                    cancelled = True
                    break

                model_started_at = time.perf_counter()
                model_display = format_ranking_model_label(model_path.name, str(model_path), target_task)
                self._touch_ranking_watchdog(f"ladowanie modelu {model_display}")
                self._append_ranking_log(f"{idx + 1}/{total_models} | Start modelu: {model_display}")
                self._set_ranking_ui_state(
                    status=f"Ładowanie modelu {model_display} ({idx + 1}/{total_models})",
                    status_color="gray",
                )

                annotator = create_plate_annotator(model_path, conf_thresh, device)
                success, _msg = annotator.load_models()
                if not self.rank_is_running:
                    cancelled = True
                    try:
                        annotator.unload_models()
                    except Exception:
                        pass
                    break
                if not success:
                    self._append_ranking_log(f"Pominieto model {model_path.name}: nie udało się go załadować.")
                    continue
                self._append_ranking_log(
                    f"{idx + 1}/{total_models} | Model załadowany po {time.perf_counter() - model_started_at:.1f}s. "
                    f"Start analizy {len(images)} obrazów."
                )
                self._touch_ranking_watchdog(f"{model_display}: start analizy obrazów")

                auto_annotations = []
                for img_idx, img_path in enumerate(images):
                    if not self.rank_is_running:
                        cancelled = True
                        break
                    self._touch_ranking_watchdog(
                        f"{model_display}: analiza obrazu {img_idx + 1}/{len(images)}"
                    )
                    auto_annotations.append(annotator.process_image(img_path))
                    sub_pct = ((idx + ((img_idx + 1) / max(1, len(images)))) / max(1, total_models)) * 100
                    self._ui(lambda p=sub_pct: self.rank_progress_var.set(p))
                    if (img_idx == 0) or ((img_idx + 1) % 10 == 0) or (img_idx + 1 == len(images)):
                        self._set_ranking_ui_state(
                            status=(
                                f"Model {model_display} | obraz {img_idx + 1}/{len(images)} "
                                f"({idx + 1}/{total_models})"
                            ),
                            status_color="gray",
                        )
                    if ((img_idx + 1) % 25 == 0) or (img_idx + 1 == len(images)):
                        self._append_ranking_log(
                            f"{idx + 1}/{total_models} | {model_display} | obrazy: {img_idx + 1}/{len(images)}"
                        )

                annotator.unload_models()
                if cancelled:
                    break
                self._touch_ranking_watchdog(f"{model_display}: eksport i porównanie wyników")
                self._set_ranking_ui_state(
                    status=f"Analiza wyników {model_display}...",
                    status_color="gray",
                )

                exporter = CVATExporter()
                exporter.export(auto_annotations, temp_xml_path, include_confidence=True)

                stats = comparator.compare(auto_xml_path=temp_xml_path, corrected_xml_path=gt_xml)
                self.ranking_engine.add_entry(
                    model_name=model_path.name,
                    model_path=str(model_path),
                    comparison_stats=stats,
                    task_type=target_task,
                    reference_name=str(reference_info.get("reference_name") or ""),
                    reference_path=str(reference_info.get("reference_dir") or ""),
                    save=False,
                )
                precision = float(stats.get("precision", 0) or 0)
                recall = float(stats.get("recall", 0) or 0)
                f1_score = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
                self._append_ranking_log(
                    f"Zakończono {model_display} | Precision={precision:.1f}% | "
                    f"Recall={recall:.1f}% | F1={f1_score:.1f}% | czas: {time.perf_counter() - model_started_at:.1f}s"
                )

                if temp_xml_path.exists():
                    temp_xml_path.unlink()

            try:
                self._touch_ranking_watchdog("zapisywanie wyników rankingu")
                self.ranking_engine.flush()
            except Exception as save_error:
                self._append_ranking_log(f"Ostrzeżenie: nie udało się zapisać rankingu: {save_error}")
            if cancelled or self.rank_cancel_requested:
                self._append_ranking_log("Ranking anulowany przez użytkownika.")
                self._ui(lambda: self._load_ranking())
                self._set_ranking_ui_state(status="Ranking anulowany.", status_color="#d35400")
            else:
                self._append_ranking_log("Ranking zakończony.")
                self._ui(lambda: self.rank_progress_var.set(100))
                self._ui(lambda: self._load_ranking())
                self._set_ranking_ui_state(status="Ranking zakończony.", status_color="green")

        except Exception as e:
            self._append_ranking_log(f"Błąd rankingu: {e}")
            self._ui(lambda err=e: messagebox.showerror("Błąd", f"Błąd w trakcie rankingu:\n{err}"))
            self._set_ranking_ui_state(status="Błąd rankingu", status_color="red")
        finally:
            self._stop_ranking_watchdog()
            self.rank_is_running = False
            self.rank_cancel_requested = False
            self._end_step4_operation("z4.ranking.run")
            self._set_ranking_ui_state(button_text="Uruchom porównanie", cancel_enabled=False, preparing=False)
            self._ui(lambda: self._refresh_ranking_start_state())
            self._ui(self._refresh_training_start_state)

    threading.Thread(target=worker, daemon=True).start()

def _cancel_ranking_v2(self):
    if not getattr(self, "rank_is_running", False):
        return

    self.rank_cancel_requested = True
    self.rank_is_running = False
    self._touch_ranking_watchdog("przerywanie rankingu")
    self._append_ranking_log("Użytkownik zazadal przerwania rankingu. Czekam na bezpieczne zatrzymanie...")
    self._set_ranking_ui_state(
        status="Przerywanie rankingu...",
        status_color="#d35400",
        button_text="Przerywanie...",
        cancel_enabled=False,
        preparing=False,
    )
