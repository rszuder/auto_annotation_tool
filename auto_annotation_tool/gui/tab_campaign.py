#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Panel kampanii i etapow projektu.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from textwrap import shorten
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
import xml.etree.ElementTree as ET
import shutil
import threading

from ..config import CONFIG, logger, PIL_AVAILABLE, Image, ImageTk, ImageDraw, ImageFont
from ..campaign_manager import CAMPAIGN
from ..campaign_ingest_planner import CHAR_ALPHABET, CampaignIngestPlanner
from ..validators import validate_model_file, format_yolo_model_identity
from ..icons import IconManager
from .help_manager import HELP
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors
from .z2_view_models import Step2CtaViewModel, Step2RouteChoiceViewModel, Step2ViewModel, Step3ViewModel


@dataclass
class WizardStageStatus:
    key: str
    title: str
    state: str
    summary: str = ""
    details: str = ""
    primary_label: str = ""
    primary_command: object = None
    secondary_label: str = ""
    secondary_command: object = None
    badge_action_label: str = ""
    badge_action_command: object = None
    body_mode: str = ""
    body_visible: bool = False
    visible: bool = True
    is_current: bool = False


class CampaignTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)
        self._startup_ui_ready = False

        # UI state
        self.roadmap_ui_elements = []
        self.right_panel = None
        self.right_panel_canvas = None
        self.right_content = None
        self.right_content_window = None
        self._model_status_title_labels = []
        self._model_status_meta_labels = []
        self.project_listbox = None
        self.project_list_host = None
        self.project_list_status_lbl = None
        self.project_list_status_labels = []
        self._project_name_by_index = []
        self._project_list_refreshing = False
        self.project_start_mode_var = tk.StringVar(master=self.frame, value="")
        self.ingest_master_pool_var = tk.StringVar(master=self.frame, value="")
        self.ingest_status_labels = []
        self.ingest_status_shell = None
        self.ingest_status_summary_lbl = None
        self.ingest_plan_listbox = None
        self.ingest_plan_host = None
        self.ingest_plan_items = []
        self.current_ingest_plan = {}
        self.ingest_panel_frame = None
        self.step1_panel_expanded = False
        self.step1_roadmap_item = None
        self.last_ingest_snapshot = {}
        self.ingest_start_shell = None
        self.ingest_start_panel = None
        self.ingest_start_title_lbl = None
        self.ingest_start_summary_lbl = None
        self.ingest_start_detected_lbl = None
        self.ingest_start_next_lbl = None
        self.btn_ingest_start_fresh = None
        self.btn_ingest_start_assets = None
        self.btn_ingest_import_plate_run = None
        self.btn_ingest_pick_plate_model = None
        self.btn_ingest_pick_char_model = None
        self.ingest_list_title_lbl = None
        self.ingest_logic_lbl = None
        self.ingest_selection_lbl = None
        self.ingest_balance_canvas = None
        self.ingest_balance_summary_lbl = None
        self.ingest_insights_shell = None
        self.ingest_insights_toggle_shell = None
        self.ingest_insights_toggle_btn = None
        self.ingest_insights_hint_lbl = None
        self.ingest_insights_expanded = False
        self.ingest_chart_panel = None
        self.ingest_info_panel = None
        self.campaign_banner_shell = None
        self.banner_top_row = None
        self.banner_progress_row = None
        self.wizard_header_title_lbl = None
        self.wizard_header_summary_lbl = None
        self.wizard_header_metro_canvas = None
        self.wizard_exit_button_canvas = None
        self._wizard_header_metro_photo = None
        self.project_add_button_canvas = None
        self.project_browser_footer = None
        self.project_status_top_row = None
        self._icon_button_images = {}
        self._pil_font_cache = {}
        self._icon_button_state = {
            "project_add": {"hover": False, "pressed": False, "enabled": True},
            "exit_project": {"hover": False, "pressed": False, "enabled": False},
        }
        self._scroll_inertia_jobs = {}
        self._step2_target_change_after_id = None
        self._dashboard_perf_cache = {
            "image_counts": {},
            "json_payloads": {},
            "model_created": {},
            "approved_stats": {},
            "step2_source_states": {},
            "step2_view_models": {},
        }
        self._wizard_header_metro_statuses = []
        self._wizard_step2_target_var = tk.StringVar(master=self.frame, value="")
        self.wizard_empty_state_card = None
        self.wizard_stage_cards = {}
        self.wizard_stage_cards_host = None
        self._project_open_refresh_after_id = None
        self._project_open_context_after_id = None
        self._wizard_focus_stage_request = ""
        self._wizard_focus_after_id = None
        self._iteration_advance_thread = None
        self._iteration_advance_result = None
        self._iteration_advance_mode = ""
        self._iteration_advance_poll_after_id = None

        self._build_ui()
        self._refresh_dashboard()
        self.frame.after_idle(self._mark_startup_ui_ready)

    def _mark_startup_ui_ready(self):
        self._startup_ui_ready = True

    def is_startup_ui_ready(self) -> bool:
        return bool(getattr(self, "_startup_ui_ready", False))

    def _ensure_roadmap_ui_ready(self) -> None:
        if not getattr(self, "wizard_stage_cards_host", None) or not getattr(self, "wizard_stage_cards", None):
            self._rebuild_roadmap_ui()

    def _clear_dashboard_perf_cache(self) -> None:
        cache = getattr(self, "_dashboard_perf_cache", None)
        if not isinstance(cache, dict):
            self._dashboard_perf_cache = {
                "image_counts": {},
                "json_payloads": {},
                "model_created": {},
                "approved_stats": {},
                "step2_source_states": {},
                "step2_view_models": {},
            }
            return
        for key in (
            "image_counts",
            "json_payloads",
            "model_created",
            "approved_stats",
            "step2_source_states",
            "step2_view_models",
        ):
            value = cache.get(key)
            if isinstance(value, dict):
                value.clear()
            else:
                cache[key] = {}

    @staticmethod
    def _build_cache_token_for_path(path: Path | None):
        if path is None:
            return ("missing", "")
        try:
            candidate = Path(path)
        except Exception:
            return ("invalid", str(path))
        if not candidate.exists():
            return ("missing", str(candidate))
        try:
            stat = candidate.stat()
            resolved = str(candidate.resolve())
            return (resolved, int(stat.st_mtime_ns), int(stat.st_size))
        except Exception:
            return ("exists", str(candidate))

    def _get_dashboard_cache_bucket(self, key: str) -> dict:
        cache = getattr(self, "_dashboard_perf_cache", None)
        if not isinstance(cache, dict):
            self._clear_dashboard_perf_cache()
            cache = getattr(self, "_dashboard_perf_cache", {})

        bucket = cache.get(key)
        if isinstance(bucket, dict):
            return bucket

        bucket = {}
        cache[key] = bucket
        return bucket

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        try:
            return max(0.0, (perf_counter() - float(started_at)) * 1000.0)
        except Exception:
            return 0.0

    def _log_perf(self, label: str, started_at: float, *, threshold_ms: float = 40.0, extra: str = "") -> None:
        elapsed_ms = self._elapsed_ms(started_at)
        if elapsed_ms < float(threshold_ms):
            return

        extra_text = f" | {extra}" if str(extra or "").strip() else ""
        logger.debug(f"[CampaignTab][PERF] {label}: {elapsed_ms:.1f} ms{extra_text}")

    # ======================================================
    # UI BUILD
    # ======================================================

    def _build_ui(self):
        palette = getattr(self.app, "palette", {})

        # ---------------- HEADER ----------------
        header_bg = palette.get("panel", "#252526")
        header_f = tk.Frame(self.frame, bg=header_bg, bd=0, highlightthickness=0, padx=14, pady=10)
        header_f.pack(fill=tk.X)
        header_f.columnconfigure(0, weight=1)
        header_f.columnconfigure(1, weight=1)
        header_f.columnconfigure(2, weight=0)
        self.header_frame = header_f

        self.lbl_title = tk.Label(
            header_f,
            text="PANEL KAMPANII",
            font=("Segoe UI", 14, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=header_bg
        )
        self.lbl_title.grid(row=0, column=0, sticky="w")

        proj_frame = tk.Frame(header_f, bg=header_bg, bd=0, highlightthickness=0)
        proj_frame.grid(row=0, column=1, sticky="ew")
        self.proj_frame = proj_frame

        self.btn_open_proj = ttk.Button(proj_frame, text="Otwórz projekt", command=self._open_selected_project)

        self.btn_del_proj = ttk.Button(proj_frame, text="Usuń projekt", command=self._delete_project)

        self.btn_exit_project = ttk.Button(proj_frame, text="Wyjdź z projektu", command=self._exit_project_mode)

        self.lbl_iter = tk.Label(
            header_f,
            text="Iteracja: -",
            font=("Segoe UI", 12, "bold"),
            fg=palette.get("warning", "#ffb3b3"),
            bg=header_bg,
            padx=0,
            pady=0
        )
        self.lbl_iter.grid(row=0, column=2, sticky="e", padx=(12, 0))

        # Baner aktywnego projektu z metrem etapów widocznym także przy scrollu.
        banner_bg = blend_hex_colors(
            palette.get("surface_info", palette.get("panel_alt", "#33250f")),
            palette.get("panel", "#252526"),
            0.58,
        )
        self.campaign_banner_shell = tk.Frame(
            self.frame,
            bg=banner_bg,
            bd=0,
            highlightthickness=0
        )
        self.campaign_banner_shell.pack(fill=tk.X, padx=15, pady=(0, 6))

        self.banner_top_row = tk.Frame(
            self.campaign_banner_shell,
            bg=banner_bg,
            bd=0,
            highlightthickness=0
        )
        self.banner_top_row.pack(fill=tk.X)

        self.lbl_campaign_banner = tk.Label(
            self.banner_top_row,
            text="",
            font=("Segoe UI", 8, "bold"),
            fg=palette.get("warning", "#ffd37a"),
            bg=banner_bg,
            padx=8,
            pady=2,
            anchor="w",
            justify=tk.LEFT
        )
        self.lbl_campaign_banner.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.banner_progress_row = tk.Frame(
            self.campaign_banner_shell,
            bg=banner_bg,
            bd=0,
            highlightthickness=0
        )
        self.banner_progress_row.pack(fill=tk.X, padx=8, pady=(0, 4))

        self.wizard_header_metro_canvas = tk.Canvas(
            self.banner_progress_row,
            height=84,
            bd=0,
            highlightthickness=0,
            bg=banner_bg,
        )
        self.wizard_header_metro_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.wizard_header_metro_canvas.bind("<Configure>", self._draw_wizard_stage_metro, add="+")
        HELP.bind_help(self.wizard_header_metro_canvas, "camp_open_project")

        self.wizard_exit_button_canvas = tk.Canvas(
            self.banner_progress_row,
            width=184,
            height=34,
            bd=0,
            highlightthickness=0,
            bg=banner_bg,
            cursor="hand2",
        )
        self.wizard_exit_button_canvas.pack(side=tk.RIGHT, padx=(8, 0), pady=(14, 0), anchor="n")
        HELP.bind_help(self.wizard_exit_button_canvas, "camp_exit_project")
        self._bind_icon_button(self.wizard_exit_button_canvas, role="exit_project", command=self._exit_project_mode)
        self.frame.after_idle(lambda: self._draw_icon_button("exit_project"))
        self._refresh_wizard_stage_metro()

        ttk.Separator(self.frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15)

        # ---------------- MAIN 2-COLUMN GRID ----------------
        main_container = ttk.Frame(self.frame, padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)
        self.main_container = main_container

        # Stały układ dwukolumnowy.
        main_container.columnconfigure(0, weight=1, minsize=700)
        main_container.columnconfigure(1, weight=0, minsize=420)
        main_container.rowconfigure(0, weight=1)

        # RIGHT SIDEBAR: projekty i modele
        left_panel_host = ttk.Frame(main_container, width=420)
        left_panel_host.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        try:
            left_panel_host.grid_propagate(False)
            left_panel_host.columnconfigure(0, weight=1)
            left_panel_host.rowconfigure(0, weight=1)
        except Exception:
            pass
        self.left_panel_host = left_panel_host

        left_panel = ttk.LabelFrame(
            left_panel_host,
            text=" Projekt ",
            padding=15
        )
        left_panel.grid(row=0, column=0, sticky="nsew")
        self.left_panel = left_panel
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(0, weight=1)

        self.left_scroll_host = ttk.Frame(left_panel)
        self.left_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.left_scroll_host.columnconfigure(0, weight=1)
        self.left_scroll_host.rowconfigure(0, weight=1)

        self.left_panel_canvas = tk.Canvas(
            self.left_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.left_panel_canvas.grid(row=0, column=0, sticky="nsew")

        self.left_panel_scrollbar = WebSlimScrollbar(
            self.left_scroll_host,
            command=self.left_panel_canvas.yview
        )
        self.left_panel_scrollbar.grid(row=0, column=1, sticky="ns")
        self.left_panel_canvas.configure(yscrollcommand=self.left_panel_scrollbar.set)

        self.left_content = ttk.Frame(self.left_panel_canvas)
        self.left_content_window = self.left_panel_canvas.create_window(
            (0, 0),
            window=self.left_content,
            anchor="nw"
        )
        self.left_content.bind("<Configure>", self._sync_left_panel_scrollregion, add="+")
        self.left_panel_canvas.bind("<Configure>", self._sync_left_panel_canvas_width, add="+")

        self.left_footer = ttk.Frame(left_panel)
        self.left_footer.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.left_panel_hint_lbl = tk.Label(
            self.left_content,
            text="",
            justify=tk.LEFT,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526")
        )
        self.left_panel_hint_lbl.pack(anchor=tk.W, pady=(0, 0))
        self._build_projects_browser(self.left_content)

        self._build_model_status(self.left_content, "Model Pojazdów (Detect):", "vehicle", Path(CONFIG.DIR_6_MODELS))
        self._build_model_status(self.left_content, "Model Tablic (Pose):", "plate", Path(CONFIG.DIR_6_MODELS))
        self._build_model_status(self.left_content, "Model Znaków (OCR/YOLO):", "char", Path(CONFIG.DIR_6_MODELS))

        self.btn_advance = ttk.Button(
            self.left_footer,
            text="Awansuj do Nowej Iteracji",
            command=self._advance_iteration,
            style="Accent.TButton"
        )

        self.btn_complete_project = ttk.Button(
            self.left_footer,
            text="Zakończ projekt",
            command=self._toggle_project_completion
        )
        self.btn_complete_project.pack(fill=tk.X, pady=(8, 0))

        HELP.bind_help(self.btn_open_proj, "camp_open_project")
        HELP.bind_help(self.btn_del_proj, "camp_delete_project")
        HELP.bind_help(self.btn_exit_project, "camp_exit_project")
        HELP.bind_help(left_panel, "camp_models")
        HELP.bind_help(self.btn_advance, "camp_advance")
        HELP.bind_help(self.btn_complete_project, "camp_advance")

        # LEFT MAIN PANEL: workflow
        self.right_panel = ttk.LabelFrame(
            main_container,
            text=" Etapy ",
            padding=15
        )
        self.right_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.right_panel.columnconfigure(0, weight=1)
        self.right_panel.rowconfigure(0, weight=1)

        self.right_scroll_host = ttk.Frame(self.right_panel)
        self.right_scroll_host.grid(row=0, column=0, sticky="nsew")
        self.right_scroll_host.columnconfigure(0, weight=1)
        self.right_scroll_host.rowconfigure(0, weight=1)

        self.right_panel_canvas = tk.Canvas(
            self.right_scroll_host,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0
        )
        self.right_panel_canvas.grid(row=0, column=0, sticky="nsew")

        self.right_panel_scrollbar = WebSlimScrollbar(
            self.right_scroll_host,
            command=self.right_panel_canvas.yview
        )
        self.right_panel_scrollbar.grid(row=0, column=1, sticky="ns")
        self.right_panel_canvas.configure(yscrollcommand=self.right_panel_scrollbar.set)

        self.right_content = ttk.Frame(self.right_panel_canvas)
        self.right_content_window = self.right_panel_canvas.create_window(
            (0, 0),
            window=self.right_content,
            anchor="nw"
        )
        self.right_content.bind("<Configure>", self._sync_right_panel_scrollregion, add="+")
        self.right_panel_canvas.bind("<Configure>", self._sync_right_panel_canvas_width, add="+")

        self._rebuild_roadmap_ui()
        self.frame.after_idle(self._sync_left_panel_scrollregion)
        self.frame.after_idle(self._sync_left_panel_canvas_width)
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self.frame.after_idle(self._sync_right_panel_canvas_width)
        self.frame.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
        self.frame.bind_all("<Button-4>", self._on_global_mousewheel, add="+")
        self.frame.bind_all("<Button-5>", self._on_global_mousewheel, add="+")

    def _sync_left_panel_scrollregion(self, event=None):
        if not hasattr(self, "left_panel_canvas") or self.left_panel_canvas is None:
            return

        try:
            self.left_panel_canvas.configure(scrollregion=self.left_panel_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_left_panel_canvas_width(self, event=None):
        if not hasattr(self, "left_panel_canvas") or self.left_panel_canvas is None:
            return

        try:
            width = max(50, int(self.left_panel_canvas.winfo_width()))
            self.left_panel_canvas.itemconfigure(self.left_content_window, width=width)
        except Exception:
            pass

    def _sync_right_panel_scrollregion(self, event=None):
        if not hasattr(self, "right_panel_canvas") or self.right_panel_canvas is None:
            return

        try:
            self.right_panel_canvas.configure(scrollregion=self.right_panel_canvas.bbox("all"))
        except Exception:
            pass

    def _sync_right_panel_canvas_width(self, event=None):
        if not hasattr(self, "right_panel_canvas") or self.right_panel_canvas is None:
            return

        try:
            width = max(50, int(self.right_panel_canvas.winfo_width()))
            self.right_panel_canvas.itemconfigure(self.right_content_window, width=width)
        except Exception:
            pass

    @staticmethod
    def _wizard_stage_key_from_step_num(step_num: int | None) -> str:
        try:
            normalized = int(step_num or 1)
        except Exception:
            normalized = 1
        normalized = min(max(normalized, 1), 4)
        return f"step{normalized}"

    def request_wizard_stage_focus(self, step_num: int | None = None, *, stage_key: str | None = None) -> None:
        key = str(stage_key or "").strip().lower()
        if not key:
            key = self._wizard_stage_key_from_step_num(step_num)
        if key not in {"step1", "step2", "step3", "step4"}:
            return
        self._wizard_focus_stage_request = key

    def _cancel_pending_wizard_stage_focus(self) -> None:
        pending = getattr(self, "_wizard_focus_after_id", None)
        if not pending:
            return
        try:
            self.frame.after_cancel(pending)
        except Exception:
            pass
        self._wizard_focus_after_id = None

    def _schedule_pending_wizard_stage_focus(self, *, attempts_left: int = 4) -> None:
        self._cancel_pending_wizard_stage_focus()
        if not str(getattr(self, "_wizard_focus_stage_request", "") or "").strip():
            return

        def _run():
            self._wizard_focus_after_id = None
            applied = self._apply_pending_wizard_stage_focus()
            if applied:
                self._wizard_focus_stage_request = ""
                return
            if attempts_left > 1:
                try:
                    self._wizard_focus_after_id = self.frame.after(
                        60,
                        lambda: self._schedule_pending_wizard_stage_focus(attempts_left=attempts_left - 1),
                    )
                except Exception:
                    self._wizard_focus_after_id = None

        try:
            self._wizard_focus_after_id = self.frame.after_idle(_run)
        except Exception:
            self._wizard_focus_after_id = None

    def _apply_pending_wizard_stage_focus(self) -> bool:
        stage_key = str(getattr(self, "_wizard_focus_stage_request", "") or "").strip().lower()
        if stage_key not in {"step1", "step2", "step3", "step4"}:
            return False

        canvas = getattr(self, "right_panel_canvas", None)
        card = dict(getattr(self, "wizard_stage_cards", {}) or {}).get(stage_key)
        shell = card.get("shell") if isinstance(card, dict) else None
        if canvas is None or shell is None:
            return False

        try:
            if not bool(canvas.winfo_ismapped()) or not bool(shell.winfo_ismapped()):
                return False
        except Exception:
            return False

        try:
            self.frame.update_idletasks()
            canvas.update_idletasks()
            shell.update_idletasks()
        except Exception:
            pass

        try:
            scroll_bbox = canvas.bbox("all")
        except Exception:
            scroll_bbox = None
        if not scroll_bbox:
            return False

        try:
            canvas_height = max(1, int(canvas.winfo_height() or 1))
            current_top = float(canvas.canvasy(0))
            widget_top = float(shell.winfo_rooty() - canvas.winfo_rooty()) + current_top
        except Exception:
            return False

        content_top = float(scroll_bbox[1])
        content_bottom = float(scroll_bbox[3])
        max_scroll = max(0.0, content_bottom - content_top - float(canvas_height))
        target_y = max(content_top, float(widget_top) - 10.0)
        if max_scroll <= 0.0:
            try:
                canvas.yview_moveto(0.0)
                return True
            except Exception:
                return False

        fraction = max(0.0, min(1.0, float(target_y - content_top) / float(max_scroll)))
        try:
            canvas.yview_moveto(fraction)
            return True
        except Exception:
            return False

    def _widget_contains_point(self, widget, x_root: int, y_root: int) -> bool:
        if widget is None:
            return False
        try:
            wx = int(widget.winfo_rootx())
            wy = int(widget.winfo_rooty())
            return wx <= x_root < (wx + int(widget.winfo_width())) and wy <= y_root < (wy + int(widget.winfo_height()))
        except Exception:
            return False

    def _mousewheel_units(self, event) -> int:
        event_num = getattr(event, "num", None)
        if event_num == 4:
            return -1
        if event_num == 5:
            return 1

        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            return 0
        if abs(delta) >= 120:
            units = -int(delta / 120)
        else:
            units = -1 if delta > 0 else 1
        return units if units != 0 else (-1 if delta > 0 else 1)

    def _mousewheel_magnitude(self, event) -> float:
        event_num = getattr(event, "num", None)
        if event_num in {4, 5}:
            return 1.0
        try:
            delta = abs(int(getattr(event, "delta", 0) or 0))
        except Exception:
            delta = 0
        if delta <= 0:
            return 1.0
        return max(1.0, min(3.0, float(delta) / 120.0))

    def _compute_canvas_scroll_delta(self, canvas, units: int, *, magnitude: float = 1.0) -> float:
        if canvas is None or units == 0:
            return 0.0
        try:
            first, last = canvas.yview()
            span = max(0.02, float(last) - float(first))
            base_step = max(0.0035, min(0.018, span * 0.08))
            step = base_step * max(1.0, min(3.0, float(magnitude or 1.0)))
            return float(units) * step
        except Exception:
            return 0.0

    def _compute_listbox_scroll_delta(self, listbox, units: int, *, magnitude: float = 1.0) -> float:
        if listbox is None or units == 0:
            return 0.0
        try:
            first, last = listbox.yview()
            span = max(0.02, float(last) - float(first))
            base_step = max(0.008, min(0.035, span * 0.12))
            step = base_step * max(1.0, min(3.0, float(magnitude or 1.0)))
            return float(units) * step
        except Exception:
            return 0.0

    def _apply_canvas_scroll_delta(self, canvas, delta_fraction: float) -> bool:
        if canvas is None or abs(float(delta_fraction or 0.0)) < 1e-6:
            return False
        try:
            first, last = canvas.yview()
            first = float(first)
            last = float(last)
            span = max(0.02, last - first)
            target = max(0.0, min(max(0.0, 1.0 - span), first + float(delta_fraction)))
            if abs(target - first) < 1e-6:
                return False
            canvas.yview_moveto(target)
            return True
        except Exception:
            return False

    def _apply_listbox_scroll_delta(self, listbox, delta_fraction: float) -> bool:
        if listbox is None or abs(float(delta_fraction or 0.0)) < 1e-6:
            return False
        try:
            first, last = listbox.yview()
            first = float(first)
            last = float(last)
            span = max(0.02, last - first)
            target = max(0.0, min(max(0.0, 1.0 - span), first + float(delta_fraction)))
            if abs(target - first) < 1e-6:
                return False
            listbox.yview_moveto(target)
            return True
        except Exception:
            return False

    def _queue_scroll_inertia(self, widget, *, mode: str, delta_fraction: float) -> bool:
        if widget is None:
            return False
        delta_fraction = float(delta_fraction or 0.0)
        if abs(delta_fraction) < 1e-6:
            return False

        key = f"{mode}:{str(widget)}"
        state = self._scroll_inertia_jobs.get(key)
        if not isinstance(state, dict):
            state = {
                "widget": widget,
                "mode": str(mode or "").strip().lower(),
                "velocity": 0.0,
                "after_id": None,
            }
            self._scroll_inertia_jobs[key] = state

        velocity = float(state.get("velocity", 0.0) or 0.0) + delta_fraction
        state["velocity"] = max(-0.14, min(0.14, velocity))

        if state.get("after_id") is None:
            try:
                state["after_id"] = self.frame.after(14, lambda scroll_key=key: self._advance_scroll_inertia(scroll_key))
            except Exception:
                state["after_id"] = None
                return False
        return True

    def _advance_scroll_inertia(self, key: str):
        state = self._scroll_inertia_jobs.get(str(key or "").strip())
        if not isinstance(state, dict):
            return

        state["after_id"] = None
        widget = state.get("widget")
        mode = str(state.get("mode", "") or "").strip().lower()
        velocity = float(state.get("velocity", 0.0) or 0.0)
        if abs(velocity) < 0.0007:
            self._scroll_inertia_jobs.pop(key, None)
            return

        if mode == "canvas":
            moved = self._apply_canvas_scroll_delta(widget, velocity)
        else:
            moved = self._apply_listbox_scroll_delta(widget, velocity)

        if not moved:
            self._scroll_inertia_jobs.pop(key, None)
            return

        state["velocity"] = velocity * 0.78
        if abs(float(state.get("velocity", 0.0) or 0.0)) < 0.0007:
            self._scroll_inertia_jobs.pop(key, None)
            return

        try:
            state["after_id"] = self.frame.after(14, lambda scroll_key=key: self._advance_scroll_inertia(scroll_key))
        except Exception:
            self._scroll_inertia_jobs.pop(key, None)

    def _canvas_can_scroll(self, canvas, units: int) -> bool:
        if canvas is None or units == 0:
            return False
        try:
            first, last = canvas.yview()
            if units < 0 and float(first) <= 0.0:
                return False
            if units > 0 and float(last) >= 1.0:
                return False
            return True
        except Exception:
            return False

    def _listbox_can_scroll(self, listbox, units: int) -> bool:
        if listbox is None or units == 0:
            return False
        try:
            first, last = listbox.yview()
            if units < 0 and float(first) <= 0.0:
                return False
            if units > 0 and float(last) >= 1.0:
                return False
            return True
        except Exception:
            return False

    def _on_listbox_mousewheel(self, event, listbox):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

        units = self._mousewheel_units(event)
        magnitude = self._mousewheel_magnitude(event)
        if listbox is None or units == 0:
            return None
        host_canvas = None
        if listbox is self.project_listbox:
            host_canvas = self.left_panel_canvas
        elif listbox is self.ingest_plan_listbox:
            host_canvas = self.right_panel_canvas
        if host_canvas is not None and self._canvas_can_scroll(host_canvas, units):
            try:
                delta_fraction = self._compute_canvas_scroll_delta(host_canvas, units, magnitude=magnitude)
                self._queue_scroll_inertia(host_canvas, mode="canvas", delta_fraction=delta_fraction)
            except Exception:
                pass
            return "break"
        if not self._listbox_can_scroll(listbox, units):
            return None
        try:
            delta_fraction = self._compute_listbox_scroll_delta(listbox, units, magnitude=magnitude)
            self._queue_scroll_inertia(listbox, mode="listbox", delta_fraction=delta_fraction)
        except Exception:
            pass
        return "break"

    def _on_global_mousewheel(self, event):
        try:
            if callable(getattr(self.app, "handle_help_panel_scroll_override", None)):
                result = self.app.handle_help_panel_scroll_override(event)
                if result == "break":
                    return "break"
        except Exception:
            pass

        units = self._mousewheel_units(event)
        magnitude = self._mousewheel_magnitude(event)
        if units == 0:
            return None

        try:
            x_root = int(getattr(event, "x_root", 0) or self.frame.winfo_pointerx())
            y_root = int(getattr(event, "y_root", 0) or self.frame.winfo_pointery())
        except Exception:
            return None

        for listbox in (self.ingest_plan_listbox, self.project_listbox):
            if not self._widget_contains_point(listbox, x_root, y_root):
                continue
            try:
                host_canvas = None
                if listbox is self.project_listbox:
                    host_canvas = self.left_panel_canvas
                elif listbox is self.ingest_plan_listbox:
                    host_canvas = self.right_panel_canvas

                if host_canvas is not None and self._canvas_can_scroll(host_canvas, units):
                    delta_fraction = self._compute_canvas_scroll_delta(host_canvas, units, magnitude=magnitude)
                    self._queue_scroll_inertia(host_canvas, mode="canvas", delta_fraction=delta_fraction)
                    return "break"
                if self._listbox_can_scroll(listbox, units):
                    delta_fraction = self._compute_listbox_scroll_delta(listbox, units, magnitude=magnitude)
                    self._queue_scroll_inertia(listbox, mode="listbox", delta_fraction=delta_fraction)
                return "break"
            except Exception:
                return "break"

        for canvas in (self.right_panel_canvas, self.left_panel_canvas):
            if not self._widget_contains_point(canvas, x_root, y_root):
                continue
            if not self._canvas_can_scroll(canvas, units):
                continue
            try:
                delta_fraction = self._compute_canvas_scroll_delta(canvas, units, magnitude=magnitude)
                self._queue_scroll_inertia(canvas, mode="canvas", delta_fraction=delta_fraction)
                return "break"
            except Exception:
                return None
        return None

    def _bind_icon_button(self, canvas, *, role: str, command):
        if canvas is None:
            return

        canvas.bind("<Configure>", lambda _e, r=role: self._draw_icon_button(r), add="+")
        canvas.bind("<Enter>", lambda _e, r=role: self._set_icon_button_visual(r, hover=True), add="+")
        canvas.bind("<Leave>", lambda _e, r=role: self._set_icon_button_visual(r, hover=False, pressed=False), add="+")
        canvas.bind("<ButtonPress-1>", lambda _e, r=role: self._set_icon_button_visual(r, pressed=True), add="+")
        canvas.bind(
            "<ButtonRelease-1>",
            lambda e, r=role, cmd=command: self._on_icon_button_release(e, role=r, command=cmd),
            add="+",
        )
        self._draw_icon_button(role)

    def _set_icon_button_enabled(self, role: str, enabled: bool):
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        state["enabled"] = bool(enabled)
        if not enabled:
            state["hover"] = False
            state["pressed"] = False
        self._draw_icon_button(role)

    def _set_icon_button_visual(self, role: str, *, hover: bool | None = None, pressed: bool | None = None):
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        if not state.get("enabled", True):
            hover = False
            pressed = False
        if hover is not None:
            state["hover"] = bool(hover)
        if pressed is not None:
            state["pressed"] = bool(pressed)
        self._draw_icon_button(role)
        return "break"

    def _on_icon_button_release(self, event, *, role: str, command):
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        state["pressed"] = False
        self._draw_icon_button(role)
        if not state.get("enabled", True) or command is None:
            return "break"
        try:
            if self._widget_contains_point(event.widget, int(event.x_root), int(event.y_root)):
                command()
        except Exception:
            pass
        return "break"

    def _get_pil_font(self, size: int, *, bold: bool = False):
        cache_key = (int(size), bool(bold))
        cached = self._pil_font_cache.get(cache_key)
        if cached is not None:
            return cached

        font_names = (
            ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
            if bold
            else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
        )
        for font_name in font_names:
            try:
                font = ImageFont.truetype(font_name, int(size))
                self._pil_font_cache[cache_key] = font
                return font
            except Exception:
                continue

        font = ImageFont.load_default()
        self._pil_font_cache[cache_key] = font
        return font

    @staticmethod
    def _hex_to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
        value = str(color or "").strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        if len(value) != 6:
            return (0, 0, 0, int(alpha))
        try:
            rgb = tuple(int(value[idx:idx + 2], 16) for idx in (0, 2, 4))
            return (rgb[0], rgb[1], rgb[2], int(alpha))
        except Exception:
            return (0, 0, 0, int(alpha))

    def _draw_icon_button(self, role: str):
        canvas = (
            self.project_add_button_canvas
            if role == "project_add"
            else self.wizard_exit_button_canvas
        )
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        bg = str(canvas.cget("bg") or palette.get("panel", "#252526"))
        state = self._icon_button_state.setdefault(role, {"hover": False, "pressed": False, "enabled": True})
        enabled = bool(state.get("enabled", True))
        hover = bool(state.get("hover", False))
        pressed = bool(state.get("pressed", False))
        width = max(int(canvas.winfo_width() or int(canvas.cget("width") or 34)), 24)
        height = max(int(canvas.winfo_height() or int(canvas.cget("height") or 34)), 24)

        canvas.delete("all")
        cursor = "hand2" if enabled else "arrow"
        try:
            canvas.config(cursor=cursor)
        except Exception:
            pass

        label_text = "Utworz projekt" if role == "project_add" else "Wyjdz z projektu"

        if PIL_AVAILABLE and Image is not None and ImageTk is not None and ImageDraw is not None and ImageFont is not None:
            scale = 4
            hi_w = max(width * scale, 4)
            hi_h = max(height * scale, 4)
            image = Image.new("RGBA", (hi_w, hi_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image, "RGBA")

            if role == "project_add":
                accent = palette.get("accent_hover", palette.get("accent", "#63c7ff")) if hover else palette.get("accent", "#63c7ff")
                if not enabled:
                    accent = palette.get("muted_dim", "#8c8c8c")
                outer_fill = blend_hex_colors(accent, bg, 0.32 if enabled else 0.76)
                inner_fill = blend_hex_colors(accent, bg, 0.10 if (enabled and pressed) else (0.18 if enabled else 0.84))
                outline = blend_hex_colors(accent, bg, 0.18 if enabled else 0.58)
                icon_color = palette.get("accent_text", "#ffffff") if enabled else palette.get("muted", "#c7c7c7")
                label_color = accent if enabled else palette.get("muted", "#c7c7c7")
            else:
                danger = palette.get("error", "#f48771")
                if not enabled:
                    danger = palette.get("muted_dim", "#8c8c8c")
                outer_fill = blend_hex_colors(danger, bg, 0.28 if enabled else 0.74)
                inner_fill = blend_hex_colors(danger, bg, 0.06 if (enabled and pressed) else (0.12 if enabled else 0.82))
                outline = blend_hex_colors(danger, bg, 0.14 if enabled else 0.56)
                icon_color = "#ffffff" if enabled else palette.get("muted", "#c7c7c7")
                label_color = danger if enabled else palette.get("muted", "#c7c7c7")

            circle_d = min(hi_h - (6 * scale), 28 * scale)
            circle_left = 6 * scale
            circle_top = max(scale, (hi_h - circle_d) // 2)
            circle_box = [circle_left, circle_top, circle_left + circle_d, circle_top + circle_d]
            inner_box = [circle_box[0] + scale, circle_box[1] + scale, circle_box[2] - scale, circle_box[3] - scale]

            if role == "project_add":
                shine_mix = 0.07 if enabled else 0.04
                shine_alpha = 128
            else:
                shine_mix = 0.14 if enabled else 0.08
                shine_alpha = 156

            draw.ellipse(circle_box, fill=self._hex_to_rgba(outer_fill))
            draw.ellipse(inner_box, fill=self._hex_to_rgba(inner_fill), outline=self._hex_to_rgba(outline), width=max(scale, 2))
            shine_arc_box = [inner_box[0] + scale, inner_box[1] + scale, inner_box[2] - scale, inner_box[3] - scale]
            draw.arc(
                shine_arc_box,
                start=200,
                end=340,
                fill=self._hex_to_rgba(blend_hex_colors(outline, "#ffffff", shine_mix), shine_alpha),
                width=max(scale + 1, 3),
            )

            cx = (inner_box[0] + inner_box[2]) / 2.0
            cy = (inner_box[1] + inner_box[3]) / 2.0
            if role == "project_add":
                bar_len = 6 * scale
                bar_w = max(scale + 1, 5)
                draw.rounded_rectangle(
                    [cx - bar_len, cy - bar_w / 2, cx + bar_len, cy + bar_w / 2],
                    radius=bar_w / 2,
                    fill=self._hex_to_rgba(icon_color),
                )
                draw.rounded_rectangle(
                    [cx - bar_w / 2, cy - bar_len, cx + bar_w / 2, cy + bar_len],
                    radius=bar_w / 2,
                    fill=self._hex_to_rgba(icon_color),
                )
            else:
                stop_half = 5.5 * scale
                draw.rounded_rectangle(
                    [cx - stop_half, cy - stop_half, cx + stop_half, cy + stop_half],
                    radius=2.4 * scale,
                    fill=self._hex_to_rgba(icon_color),
                )

            font = self._get_pil_font(13 * scale, bold=False)
            text_x = circle_box[2] + (8 * scale)
            try:
                text_box = draw.textbbox((0, 0), label_text, font=font)
                text_h = max(1, text_box[3] - text_box[1])
            except Exception:
                text_h = 10 * scale
            text_y = max(0, int((hi_h - text_h) / 2) - (scale // 2))
            draw.text((text_x, text_y), label_text, font=font, fill=self._hex_to_rgba(label_color))

            try:
                resampling = Image.Resampling.LANCZOS
            except Exception:
                resampling = Image.LANCZOS
            image = image.resize((width, height), resampling)
            photo = ImageTk.PhotoImage(image)
            self._icon_button_images[role] = photo
            canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            return

        if role == "project_add":
            accent = palette.get("accent_hover", palette.get("accent", "#63c7ff")) if hover else palette.get("accent", "#63c7ff")
            if not enabled:
                accent = palette.get("muted_dim", "#8c8c8c")
            outer_fill = blend_hex_colors(accent, bg, 0.32 if enabled else 0.76)
            inner_fill = blend_hex_colors(accent, bg, 0.10 if (enabled and pressed) else (0.18 if enabled else 0.84))
            outline = blend_hex_colors(accent, bg, 0.18 if enabled else 0.58)
            icon_color = palette.get("accent_text", "#ffffff") if enabled else palette.get("muted", "#c7c7c7")
            label_color = accent if enabled else palette.get("muted", "#c7c7c7")
        else:
            danger = palette.get("error", "#f48771")
            if not enabled:
                danger = palette.get("muted_dim", "#8c8c8c")
            outer_fill = blend_hex_colors(danger, bg, 0.28 if enabled else 0.74)
            inner_fill = blend_hex_colors(danger, bg, 0.06 if (enabled and pressed) else (0.12 if enabled else 0.82))
            outline = blend_hex_colors(danger, bg, 0.14 if enabled else 0.56)
            icon_color = "#ffffff" if enabled else palette.get("muted", "#c7c7c7")
            label_color = danger if enabled else palette.get("muted", "#c7c7c7")

        circle_top = max(3, int((height - 28) / 2))
        circle_box = (4, circle_top, 32, circle_top + 28)
        canvas.create_oval(*circle_box, fill=outer_fill, outline="")
        canvas.create_oval(circle_box[0], circle_box[1], circle_box[2], circle_box[3], fill=inner_fill, outline=outline, width=1)
        canvas.create_arc(
            circle_box[0] + 2,
            circle_box[1] + 2,
            circle_box[2] - 2,
            circle_box[3] - 2,
            start=20,
            extent=140,
            style=tk.ARC,
            outline=blend_hex_colors(outline, "#ffffff", 0.07 if role == "project_add" else (0.14 if enabled else 0.08)),
            width=2,
        )

        cx = (circle_box[0] + circle_box[2]) / 2.0
        cy = (circle_box[1] + circle_box[3]) / 2.0
        if role == "project_add":
            canvas.create_line(cx - 8, cy, cx + 8, cy, fill=icon_color, width=3, capstyle=tk.ROUND)
            canvas.create_line(cx, cy - 8, cx, cy + 8, fill=icon_color, width=3, capstyle=tk.ROUND)
        else:
            canvas.create_rectangle(cx - 7, cy - 7, cx + 7, cy + 7, fill=icon_color, outline=icon_color, width=1)
        canvas.create_text(42, height / 2.0, text=label_text, anchor=tk.W, fill=label_color, font=("Segoe UI", 12, "normal"))

    def _build_projects_browser(self, parent):
        palette = getattr(self.app, "palette", {})

        browser_lf = ttk.LabelFrame(parent, text=" Zapisane projekty ", padding=10)
        browser_lf.pack(fill=tk.X, pady=(0, 12))
        self.project_browser_frame = browser_lf

        status_panel = tk.Frame(
            browser_lf,
            bg=palette.get("panel", "#252526")
        )
        status_panel.pack(fill=tk.X, pady=(0, 6))
        self.project_list_status_lbl = status_panel
        self.project_list_status_labels = []
        self.project_status_top_row = tk.Frame(
            status_panel,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
        )
        self.project_status_top_row.pack(fill=tk.X)

        status_fonts = [
            ("Segoe UI", 10, "bold"),
            ("Segoe UI", 9),
            ("Segoe UI", 9),
        ]

        first_lbl = tk.Label(
            self.project_status_top_row,
            text="",
            justify=tk.LEFT,
            anchor="w",
            height=1,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
            font=status_fonts[0]
        )
        first_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.project_list_status_labels.append(first_lbl)

        self.project_add_button_canvas = tk.Canvas(
            self.project_status_top_row,
            width=196,
            height=38,
            bd=0,
            highlightthickness=0,
            bg=palette.get("panel", "#252526"),
            cursor="hand2",
        )
        self.project_add_button_canvas.pack(side=tk.RIGHT, padx=(8, 0))
        HELP.bind_help(self.project_add_button_canvas, "camp_new_project")
        self._bind_icon_button(self.project_add_button_canvas, role="project_add", command=self._add_new_project)
        self.frame.after_idle(lambda: self._draw_icon_button("project_add"))

        for font_spec in status_fonts[1:]:
            lbl = tk.Label(
                status_panel,
                text="",
                justify=tk.LEFT,
                anchor="w",
                height=1,
                fg=palette.get("muted", "#b8b8b8"),
                bg=palette.get("panel", "#252526"),
                font=font_spec
            )
            lbl.pack(fill=tk.X)
            self.project_list_status_labels.append(lbl)

        list_host = tk.Frame(
            browser_lf,
            bg=palette.get("field", "#1a1a1a"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
        )
        list_host.pack(fill=tk.X, expand=False)
        self.project_list_host = list_host

        scroll = WebSlimScrollbar(list_host, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.project_listbox = tk.Listbox(
            list_host,
            exportselection=False,
            selectmode=tk.EXTENDED,
            height=5,
            width=1,
            font=("Segoe UI", 10),
            bg=palette.get("field", "#1a1a1a"),
            fg=palette.get("fg", "#f3f3f3"),
            selectbackground=palette.get("accent", "#2980b9"),
            selectforeground="#ffffff",
            activestyle="none",
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("accent", "#2980b9"),
            takefocus=1,
            yscrollcommand=scroll.set
        )
        self.project_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.project_listbox.bind("<<ListboxSelect>>", self._on_project_changed)
        self.project_listbox.bind("<Double-Button-1>", lambda _e: self._open_selected_project())
        self.project_listbox.bind("<Button-1>", lambda _e: self.project_listbox.focus_set(), add="+")
        self.project_listbox.bind("<Button-3>", self._show_project_context_menu)
        self.project_listbox.bind("<MouseWheel>", lambda e: self._on_listbox_mousewheel(e, self.project_listbox))
        self.project_listbox.bind("<Button-4>", lambda e: self._on_listbox_mousewheel(e, self.project_listbox))
        self.project_listbox.bind("<Button-5>", lambda e: self._on_listbox_mousewheel(e, self.project_listbox))
        scroll.config(command=self.project_listbox.yview)

        self.project_context_menu = tk.Menu(self.frame, tearoff=0)
        self.project_context_menu.add_command(label="Otwórz projekt", command=self._open_selected_project)
        self.project_context_menu.add_separator()
        self.project_context_menu.add_command(label="Usuń zaznaczone projekty", command=self._delete_project)

        self.project_browser_footer = None

        HELP.bind_help(browser_lf, "camp_open_project")
        HELP.bind_help(status_panel, "camp_open_project")
        for lbl in self.project_list_status_labels:
            HELP.bind_help(lbl, "camp_open_project")
        HELP.bind_help(self.project_listbox, "camp_open_project")

    def _build_ingest_panel(self, parent):
        palette = getattr(self.app, "palette", {})
        subtle_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        ingest_lf = tk.Frame(
            parent,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border
        )
        ingest_lf.pack(fill=tk.X, pady=(4, 0))
        self.ingest_panel_frame = ingest_lf

        header_lbl = tk.Label(
            ingest_lf,
            text="Panel E1: Wybrany folder zdjęć",
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_header_lbl = header_lbl

        intro_lbl = tk.Label(
            ingest_lf,
            text="W E1 przygotowujesz paczkę wejściową iteracji i zatwierdzasz ją przed przejściem do E2.",
            justify=tk.LEFT,
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        intro_lbl.pack(anchor=tk.W, padx=10, pady=(10, 6))
        self.ingest_intro_lbl = intro_lbl

        start_shell = tk.Frame(
            ingest_lf,
            bg=palette.get("panel_alt", "#2d2d30"),
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        start_shell.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.ingest_start_shell = start_shell

        start_panel = tk.Frame(start_shell, bg=palette.get("panel_alt", "#2d2d30"))
        start_panel.pack(fill=tk.X, padx=10, pady=10)
        self.ingest_start_panel = start_panel

        self.ingest_start_title_lbl = tk.Label(
            start_panel,
            text="Start 1. iteracji",
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel_alt", "#2d2d30"),
            anchor="w",
            justify=tk.LEFT,
        )
        self.ingest_start_title_lbl.pack(fill=tk.X)

        self.ingest_start_summary_lbl = tk.Label(
            start_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel_alt", "#2d2d30"),
        )
        self.ingest_start_summary_lbl.pack(fill=tk.X, pady=(4, 8))

        start_mode_row = tk.Frame(start_panel, bg=palette.get("panel_alt", "#2d2d30"))
        start_mode_row.pack(anchor=tk.W)

        self.btn_ingest_start_fresh = ttk.Button(
            start_mode_row,
            text="Wybierz katalog zdjęć",
            command=self._start_project_from_zero,
        )
        self.btn_ingest_start_fresh.pack(side=tk.LEFT)

        self.btn_ingest_start_assets = ttk.Button(
            start_mode_row,
            text="Wskaż pozostale zasoby",
            command=self._start_project_with_assets,
        )
        self.btn_ingest_start_assets.pack(side=tk.LEFT, padx=(8, 0))

        start_assets_row = tk.Frame(start_panel, bg=palette.get("panel_alt", "#2d2d30"))
        start_assets_row.pack(anchor=tk.W, pady=(10, 0))
        self.ingest_start_assets_row = start_assets_row

        self.btn_ingest_import_plate_run = ttk.Button(
            start_assets_row,
            text="Importuj anotacje tablic",
            command=self._import_project_start_plate_run,
        )
        self.btn_ingest_import_plate_run.pack(side=tk.LEFT)

        self.btn_ingest_pick_plate_model = ttk.Button(
            start_assets_row,
            text="Model tablic",
            command=lambda: self._choose_project_start_model("plate"),
        )

        self.btn_ingest_pick_char_model = ttk.Button(
            start_assets_row,
            text="Model znaków",
            command=lambda: self._choose_project_start_model("char"),
        )

        self.ingest_start_detected_lbl = tk.Label(
            start_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=620,
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel_alt", "#2d2d30"),
        )
        self.ingest_start_detected_lbl.pack(fill=tk.X, pady=(10, 0))

        self.ingest_start_next_lbl = tk.Label(
            start_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel_alt", "#2d2d30"),
        )
        self.ingest_start_next_lbl.pack(fill=tk.X, pady=(6, 0))

        ingest_top_section = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        ingest_top_section.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.ingest_top_section = ingest_top_section

        master_row = tk.Frame(ingest_top_section, bg=palette.get("panel", "#252526"))
        master_row.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.ingest_master_row = master_row

        self.lbl_ingest_master_title = tk.Label(
            master_row,
            text="Główna pula zdjęć:",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
        )
        self.lbl_ingest_master_title.pack(anchor=tk.W)

        master_value_row = tk.Frame(ingest_top_section, bg=palette.get("panel", "#252526"))
        master_value_row.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.ingest_master_value_row = master_value_row

        self.lbl_ingest_master_value = tk.Label(
            master_value_row,
            textvariable=self.ingest_master_pool_var,
            justify=tk.LEFT,
            anchor="w",
            wraplength=260,
            fg=palette.get("accent", "#4fc1ff"),
            bg=palette.get("panel", "#252526"),
            font=("Consolas", 9),
        )
        self.lbl_ingest_master_value.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.btn_choose_master_pool = ttk.Button(
            master_value_row,
            text="Wybierz...",
            command=self._choose_master_pool_dir,
        )
        self.btn_choose_master_pool.pack(side=tk.RIGHT, padx=(8, 0))

        summary_style = self._get_ingest_summary_style()
        status_shell = tk.Frame(
            ingest_top_section,
            bg=summary_style["bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=summary_style["border"],
            highlightcolor=summary_style["border"],
        )
        status_shell.pack(fill=tk.X, padx=10, pady=(2, 6))
        self.ingest_status_shell = status_shell

        status_panel = tk.Frame(
            status_shell,
            bg=summary_style["bg"],
        )
        status_panel.pack(fill=tk.X, padx=8, pady=6)
        self.ingest_status_panel = status_panel
        self.ingest_status_labels = []
        self.ingest_status_summary_lbl = tk.Label(
            status_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            fg=summary_style["fg"],
            bg=summary_style["bg"],
            font=("Segoe UI", 10),
            wraplength=620,
        )
        self.ingest_status_summary_lbl.pack(fill=tk.X)
        self.ingest_status_labels.append(self.ingest_status_summary_lbl)

        ingest_body = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
        )
        ingest_body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        ingest_body.grid_columnconfigure(0, weight=1, minsize=300)
        ingest_body.grid_rowconfigure(0, weight=1)
        self.ingest_body = ingest_body

        left_col = tk.Frame(ingest_body, bg=palette.get("panel", "#252526"))
        left_col.config(
            bd=0,
            highlightthickness=0,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        left_col.grid(row=0, column=0, sticky="nsew")
        self.ingest_left_col = left_col

        self.ingest_right_col = None

        self.ingest_config_row = None
        self.lbl_ingest_batch_title = None
        self.spn_ingest_batch = None

        self.ingest_actions_row = None
        self.btn_refresh_ingest_stats = None
        self.btn_generate_ingest_plan = None
        self.btn_manual_ingest = None
        self.ingest_list_title_lbl = None
        self.ingest_plan_host = None
        self.ingest_plan_listbox = None
        self.ingest_footer_row = None
        self.btn_remove_ingest_item = None

        approve_row = tk.Frame(left_col, bg=palette.get("panel", "#252526"))
        self.ingest_approve_row = approve_row

        insights_toggle_shell = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
        )
        insights_toggle_shell.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.ingest_insights_toggle_shell = insights_toggle_shell

        self.ingest_insights_toggle_btn = ttk.Button(
            insights_toggle_shell,
            text="Pokaż analizę puli",
            command=self._toggle_ingest_insights,
            style="WorkflowCard.TButton",
        )
        self.ingest_insights_toggle_btn.pack(side=tk.LEFT)

        self.ingest_insights_hint_lbl = tk.Label(
            insights_toggle_shell,
            text="Histogram i rozkład znaków są dostępne jako sekcja dodatkowa.",
            justify=tk.LEFT,
            anchor="w",
            wraplength=520,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_insights_hint_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))

        self.btn_apply_ingest_plan = ttk.Button(
            insights_toggle_shell,
            text="Zatwierdź E1",
            command=self._apply_current_ingest_plan,
            style="Accent.TButton",
            width=18,
        )
        self.btn_apply_ingest_plan.pack(side=tk.RIGHT)

        self.ingest_insights_shell = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=0,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
        )
        self.ingest_insights_shell.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.ingest_insights_shell.grid_columnconfigure(0, weight=1, minsize=420)

        self.ingest_chart_panel = tk.Frame(self.ingest_insights_shell, bg=palette.get("panel", "#252526"))
        self.ingest_chart_panel.grid(row=0, column=0, sticky="nsew", pady=6)

        self.ingest_balance_title_lbl = tk.Label(
            self.ingest_chart_panel,
            text="Histogram znaków w wybranym folderze zdjęć",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_balance_title_lbl.pack(fill=tk.X, pady=(0, 2))

        self.ingest_balance_canvas = tk.Canvas(
            self.ingest_chart_panel,
            height=220,
            bg=palette.get("field", "#1a1a1a"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
        )
        self.ingest_balance_canvas.pack(fill=tk.X)
        self.ingest_balance_canvas.bind("<Configure>", lambda _e: self._refresh_ingest_balance_chart())

        self.ingest_balance_summary_lbl = tk.Label(
            self.ingest_chart_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=520,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_balance_summary_lbl.pack(fill=tk.X, pady=(6, 0))

        self.ingest_info_panel = None
        self.ingest_logic_title_lbl = None
        self.ingest_logic_lbl = None
        self.ingest_selection_title_lbl = None
        self.ingest_selection_lbl = None
        ingest_lf.bind("<Configure>", self._sync_ingest_wraps, add="+")
        self.ingest_insights_shell.bind("<Configure>", self._sync_ingest_wraps, add="+")

        for widget in (
            ingest_lf,
            header_lbl,
            intro_lbl,
            self.lbl_ingest_master_value,
        ):
            HELP.bind_help(widget, "camp_e1_panel")
        HELP.bind_help(self.lbl_ingest_master_title, "camp_e1_master_pool")
        HELP.bind_help(self.lbl_ingest_master_value, "camp_e1_master_pool")
        HELP.bind_help(self.btn_choose_master_pool, "camp_e1_master_pool")
        HELP.bind_help(self.ingest_balance_title_lbl, "camp_e1_balance_chart")
        HELP.bind_help(self.ingest_balance_canvas, "camp_e1_balance_chart")
        HELP.bind_help(self.ingest_balance_summary_lbl, "camp_e1_balance_chart")
        HELP.bind_help(self.btn_apply_ingest_plan, "camp_e1_apply")
        HELP.bind_help(self.ingest_insights_toggle_btn, "camp_e1_balance_chart")
        self._refresh_ingest_insights_visibility(mode_selected=False)

    def _sync_project_browser_wraplength(self, event=None):
        return

    def _build_model_status(self, parent, title, model_type, initial_dir: Path):
        palette = getattr(self.app, "palette", {})

        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=10)

        title_lbl = tk.Label(
            f,
            text=title,
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526")
        )
        title_lbl.pack(anchor=tk.W)
        self._model_status_title_labels.append(title_lbl)

        row = ttk.Frame(f)
        row.pack(fill=tk.X)

        lbl_val = tk.Label(
            row,
            text="Domyslny/Brak",
            fg=palette.get("accent", "#4fc1ff"),
            bg=palette.get("panel", "#252526"),
            font=("Consolas", 10)
        )
        lbl_val.pack(side=tk.LEFT, expand=True, anchor=tk.W)

        setattr(self, f"lbl_model_{model_type}", lbl_val)

        lbl_meta = tk.Label(
            f,
            text="Utworzono: -",
            fg=palette.get("muted", "#b0b0b0"),
            bg=palette.get("panel", "#252526"),
            font=("Segoe UI", 8),
        )
        lbl_meta.pack(anchor=tk.W, pady=(2, 0))
        self._model_status_meta_labels.append(lbl_meta)
        setattr(self, f"lbl_model_{model_type}_meta", lbl_meta)
        setattr(self, f"btn_model_{model_type}", None)

    def _format_model_created_label(self, model_path: str | Path | None) -> str:
        path_text = str(model_path or "").strip()
        if not path_text:
            return "Utworzono: -"

        try:
            path = Path(path_text)
        except Exception:
            return "Utworzono: -"

        if not path.exists():
            return "Utworzono: -"

        cache = getattr(self, "_dashboard_perf_cache", {})
        model_cache = cache.get("model_created", {}) if isinstance(cache, dict) else {}
        cache_token = self._build_cache_token_for_path(path)
        cache_key = ("created_label", cache_token)
        cached = model_cache.get(cache_key) if isinstance(model_cache, dict) else None
        if isinstance(cached, str):
            return cached

        try:
            created_at = datetime.fromtimestamp(path.stat().st_ctime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "Utworzono: -"
        label = f"Utworzono: {created_at}"
        if isinstance(model_cache, dict):
            if len(model_cache) > 128:
                model_cache.clear()
            model_cache[cache_key] = label
        return label

    def _get_model_identity_label(self, model_path: str | Path | None) -> str:
        path_text = str(model_path or "").strip()
        if not path_text:
            return ""

        try:
            path = Path(path_text)
        except Exception:
            return ""
        if not path.exists():
            return ""

        cache = getattr(self, "_dashboard_perf_cache", {})
        model_cache = cache.get("model_identity", {}) if isinstance(cache, dict) else {}
        cache_token = self._build_cache_token_for_path(path)
        cache_key = ("identity_label", cache_token)
        cached = model_cache.get(cache_key) if isinstance(model_cache, dict) else None
        if isinstance(cached, str):
            return cached

        try:
            _ok, _message, info = validate_model_file(path)
        except Exception:
            info = {}
        label = format_yolo_model_identity(info)
        if label and isinstance(model_cache, dict):
            if len(model_cache) > 128:
                model_cache.clear()
            model_cache[cache_key] = label
        return label

    def _format_model_meta_label(self, model_path: str | Path | None) -> str:
        identity_label = self._get_model_identity_label(model_path)
        created_label = self._format_model_created_label(model_path)
        if identity_label and created_label != "Utworzono: -":
            return f"{identity_label} | {created_label}"
        if identity_label:
            return identity_label
        return created_label

    def _count_images_in_dir(self, directory: Path | None, recursive: bool = True) -> int:
        if directory is None or not directory.exists() or not directory.is_dir():
            return 0

        cache = getattr(self, "_dashboard_perf_cache", {})
        image_cache = cache.get("image_counts", {}) if isinstance(cache, dict) else {}
        cache_key = (self._build_cache_token_for_path(directory), bool(recursive))
        cached = image_cache.get(cache_key) if isinstance(image_cache, dict) else None
        if isinstance(cached, int):
            return cached

        try:
            iterator = directory.rglob("*") if recursive else directory.iterdir()
            count = sum(
                1
                for image_path in iterator
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            )
            if isinstance(image_cache, dict):
                if len(image_cache) > 256:
                    image_cache.clear()
                image_cache[cache_key] = int(count)
            return int(count)
        except Exception:
            return 0

    @staticmethod
    def _normalize_project_start_mode(mode: str | None) -> str:
        value = str(mode or "").strip().lower()
        if not value:
            return ""
        return "assets" if value == "assets" else "fresh"

    def _is_first_iteration_start_context(self) -> bool:
        if not CAMPAIGN.get_active_project_name():
            return False
        try:
            return int(CAMPAIGN.get_current_iteration_num() or 1) == 1 and CAMPAIGN.get_step1_status() != "approved"
        except Exception:
            return False

    def _get_project_start_mode(self) -> str:
        try:
            mode = CAMPAIGN.get_project_start_mode()
        except Exception:
            mode = ""
        mode = self._normalize_project_start_mode(mode)
        if not mode and self._is_first_iteration_start_context():
            mode = "fresh"
            try:
                CAMPAIGN.set_project_start_mode(mode)
            except Exception:
                pass
        try:
            self.project_start_mode_var.set(mode)
        except Exception:
            pass
        return mode

    def _set_project_start_mode(self, mode: str | None, *, refresh: bool = True) -> None:
        normalized = self._normalize_project_start_mode(mode)
        try:
            self.project_start_mode_var.set(normalized)
        except Exception:
            pass

        try:
            CAMPAIGN.set_project_start_mode(normalized)
        except Exception:
            pass

        if refresh:
            self._refresh_ingest_panel()

    def _start_project_from_zero(self) -> None:
        previous_mode = self._get_project_start_mode()
        self._set_project_start_mode("fresh")
        if not self._choose_master_pool_dir():
            master_pool = CAMPAIGN.get_master_pool_dir()
            if previous_mode == "" and not master_pool:
                self._set_project_start_mode("")

    def _start_project_with_assets(self) -> None:
        self._set_project_start_mode("assets")
        master_pool = CAMPAIGN.get_master_pool_dir()
        if master_pool is None or not Path(master_pool).exists():
            self._choose_master_pool_dir()

    def _choose_project_start_model(self, model_type: str) -> None:
        self._set_project_start_mode("assets", refresh=False)
        self._set_model(model_type)

    @staticmethod
    def _looks_like_character_model_classes(class_names: list[str]) -> bool:
        normalized = [str(name).strip().upper() for name in class_names if str(name).strip()]
        if len(normalized) < 8:
            return False

        allowed = set(CHAR_ALPHABET)
        for token in normalized:
            if len(token) != 1 or token not in allowed:
                return False
        return True

    def _validate_project_model_selection(self, model_type: str, model_path: Path) -> tuple[bool, str]:
        ok, message, info = validate_model_file(model_path)
        if not ok:
            return False, message or "Nie udało się odczytać modelu."

        task = str(info.get("task") or "").strip().lower()
        inferred_type = str(info.get("type") or "").strip().lower()
        is_pose = bool(info.get("keypoints")) or task == "pose" or inferred_type == "pose"
        class_names = [str(name).strip() for name in (info.get("classes") or []) if str(name).strip()]
        class_names_lower = [name.lower() for name in class_names]
        joined_names = " ".join(class_names_lower)

        if model_type == "plate":
            if not is_pose:
                return False, "Model tablic musi być modelem YOLO Pose z punktami kluczowymi."
            if class_names and not any(
                (name in CONFIG.PLATE_LABELS) or ("plate" in name) or ("tablic" in name) or ("rejestr" in name)
                for name in class_names_lower
            ):
                return False, "To nie wygląda na model tablic: w klasach nie widać znacznika plate/tablica."
            return True, ""

        if model_type == "char":
            if is_pose:
                return False, "Model znaków nie może być modelem Pose."
            if not class_names:
                return False, "Nie udało się odczytać klas modelu znaków z pliku .pt."
            if not self._looks_like_character_model_classes(class_names):
                return False, "Model znaków powinien mieć klasy znaków 0-9 i A-Z."
            return True, ""

        if model_type == "vehicle":
            if is_pose:
                return False, "Model pojazdów powinien być modelem detekcyjnym, nie Pose."
            if class_names and self._looks_like_character_model_classes(class_names):
                return False, "To wygląda na model znaków, nie pojazdów."
            vehicle_markers = (
                "vehicle", "car", "truck", "bus", "motorcycle", "motorbike", "van",
                "pickup", "suv", "pojazd", "samochod", "auto"
            )
            if class_names and not any(marker in joined_names for marker in vehicle_markers):
                return False, "To nie wygląda na model pojazdów: w klasach nie widać typowych znacznikow pojazdów."
            return True, ""

        return True, ""

    def _resolve_project_start_run_images_dir(self, run_dir: Path | None) -> Path | None:
        if run_dir is None:
            return None

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return None

        try:
            manifest = annotation_tab._load_annotation_run_manifest(run_dir)
        except Exception:
            manifest = {}

        for raw_path in (
            str(manifest.get("imported_source_input_dir") or "").strip(),
            str(manifest.get("input_dir") or "").strip(),
        ):
            if not raw_path:
                continue
            try:
                candidate = Path(raw_path)
            except Exception:
                continue
            if candidate.exists() and candidate.is_dir() and self._count_images_in_dir(candidate, recursive=True) > 0:
                return candidate

        return None

    def _check_project_start_run_compatibility(
        self,
        run_dir: Path | None,
        expected_images_dir: Path | None,
    ) -> dict:
        result = {
            "ok": False,
            "checked": False,
            "total": 0,
            "matched": 0,
            "missing": 0,
            "missing_names": [],
            "images_dir": None,
        }

        if run_dir is None or expected_images_dir is None:
            return result

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return result

        try:
            safe_run_dir = annotation_tab._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
        except Exception:
            safe_run_dir = None

        if safe_run_dir is None:
            return result

        try:
            images_dir = Path(expected_images_dir)
        except Exception:
            return result

        try:
            if not images_dir.exists() or not images_dir.is_dir():
                return result
        except Exception:
            return result

        try:
            annotations = annotation_tab._parse_cvat_preview_annotations(safe_run_dir / "annotations.xml")
        except Exception:
            return result

        if not annotations:
            result["checked"] = True
            result["images_dir"] = images_dir
            return result

        resolved, missing = annotation_tab._resolve_external_run_source_images(
            annotations,
            [images_dir],
        )
        result.update(
            checked=True,
            total=len(annotations),
            matched=len(resolved),
            missing=len(missing),
            missing_names=list(missing[:5]),
            images_dir=images_dir,
        )
        result["ok"] = bool(len(missing) == 0 and len(resolved) == len(annotations))
        return result

    def _import_project_start_plate_run(self) -> None:
        if not CAMPAIGN.get_active_project_name():
            return

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            self.app.themed_error(
                "Brak Z2",
                "Nie udało się odnalezc zakładki Z2 potrzebnej do importu gotowych anotacji tablic.",
                parent=self.frame,
            )
            return

        self._set_project_start_mode("assets", refresh=False)

        try:
            initial_dir = annotation_tab._get_manual_review_import_initial_dir()
        except Exception:
            initial_dir = Path(CONFIG.get_auto_annotations_dir("plate"))

        selected_dir = filedialog.askdirectory(
            initialdir=str(initial_dir),
            title="Wskaż katalog z gotowymi anotacjami tablic (annotations.xml)",
        )
        if not selected_dir:
            return

        try:
            selected_run_dir = Path(selected_dir)
        except Exception:
            self.app.themed_error("Błąd importu", "Nieprawidłowa ścieżka gotowych anotacji tablic.", parent=self.frame)
            return

        project_images_dir = CAMPAIGN.get_master_pool_dir()
        if project_images_dir is None:
            project_images_dir = CAMPAIGN.get_iteration_raw_dir()

        try:
            safe_run_dir = annotation_tab._resolve_safe_annotation_run_dir(selected_run_dir, require_xml=True)
        except Exception:
            safe_run_dir = None

        final_run_dir = safe_run_dir
        selected_images_dir = Path(project_images_dir) if project_images_dir is not None else None
        if selected_images_dir is not None:
            try:
                if not selected_images_dir.exists() or not selected_images_dir.is_dir() or self._count_images_in_dir(selected_images_dir, recursive=True) <= 0:
                    selected_images_dir = None
            except Exception:
                selected_images_dir = None

        if final_run_dir is None:
            imported_run_dir, error_message, needs_image_dir = annotation_tab._import_external_annotation_run_to_workspace(
                selected_run_dir,
                compatible_images_dir=selected_images_dir,
            )
            if imported_run_dir is None and needs_image_dir:
                prompt_dir = selected_images_dir if selected_images_dir is not None else Path(CONFIG.DIR_1_RAW)
                compatible_dir = filedialog.askdirectory(
                    initialdir=str(prompt_dir),
                    title="Wskaż folder obrazów zgodnych z annotations.xml",
                )
                if not compatible_dir:
                    return
                selected_images_dir = Path(compatible_dir)
                imported_run_dir, error_message, _needs_image_dir = annotation_tab._import_external_annotation_run_to_workspace(
                    selected_run_dir,
                    compatible_images_dir=selected_images_dir,
                )
            if imported_run_dir is None:
                self.app.themed_error(
                    "Import anotacji tablic",
                    error_message or "Nie udało się zaimportowac wskazanych anotacji tablic.",
                    parent=self.frame,
                )
                return
            final_run_dir = imported_run_dir

        if final_run_dir is None:
            return

        compatibility = self._check_project_start_run_compatibility(final_run_dir, selected_images_dir)
        if compatibility.get("checked") and not compatibility.get("ok"):
            images_dir = compatibility.get("images_dir")
            missing_preview = "\n".join(str(name) for name in (compatibility.get("missing_names") or []))
            missing_suffix = ""
            remaining_missing = int(compatibility.get("missing", 0) or 0) - len(compatibility.get("missing_names") or [])
            if remaining_missing > 0:
                missing_suffix = f"\n... i jeszcze {remaining_missing} plikow."
            self.app.themed_error(
                "Import anotacji tablic",
                (
                    "Wybrane anotacje tablic nie pasuja do obrazów ustawionych dla tej iteracji.\n\n"
                    f"Obrazy iteracji: {Path(images_dir).name if images_dir is not None else 'brak'}\n"
                    f"Obrazy opisane w XML: {int(compatibility.get('total', 0) or 0)}\n"
                    f"Zgodne obrazy: {int(compatibility.get('matched', 0) or 0)}\n"
                    f"Brakujące obrazy: {int(compatibility.get('missing', 0) or 0)}\n\n"
                    "Najpierw wskaż zgodny zestaw obrazów albo zaimportuj run przygotowany dla tej paczki."
                    + (f"\n\nPrzyklady brakujacych plikow:\n{missing_preview}{missing_suffix}" if missing_preview else "")
                ),
                parent=self.frame,
            )
            return

        resolved_images_dir = selected_images_dir or self._resolve_project_start_run_images_dir(final_run_dir)
        if resolved_images_dir is not None and resolved_images_dir.exists() and resolved_images_dir.is_dir():
            try:
                CAMPAIGN.set_master_pool_dir(resolved_images_dir)
            except Exception:
                pass

        try:
            annotation_tab._remember_campaign_manual_plate_source(
                run_dir=final_run_dir,
                input_dir=resolved_images_dir,
            )
        except Exception as e:
            logger.debug(f"Nie udało się zapamietac importowanego runu tablic dla kampanii: {e}")

        self.current_ingest_plan = {}
        if resolved_images_dir is not None and self._get_iteration_image_count() == 0:
            self._generate_ingest_plan()
        else:
            self._refresh_dashboard()

        try:
            run_name = final_run_dir.name
        except Exception:
            run_name = "anotacje tablic"
        try:
            self.app.update_status(
                (
                    f"Podpieto gotowe anotacje tablic: {run_name}. "
                    "E2 będzie mogło użyć ich zamiast startować od zera."
                ),
                "info",
            )
        except Exception:
            pass

    def _refresh_project_start_panel(self) -> None:
        shell = getattr(self, "ingest_start_shell", None)
        if shell is None:
            return

        visible = self._is_first_iteration_start_context()
        try:
            self._set_pack_visibility(shell, visible, fill=tk.X, padx=10, pady=(0, 6))
        except Exception:
            pass
        if not visible:
            return

        mode = self._get_project_start_mode()
        palette = getattr(self.app, "palette", {})
        mode_selected = mode in {"fresh", "assets"}
        mode_is_assets = mode == "assets"

        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_exists = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        master_pool_images = self._count_images_in_dir(master_pool, recursive=True) if master_pool_exists else 0
        plate_ready_source = self._get_plate_route_ready_source()
        char_ready_source = self._get_char_route_ready_source()
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())
        char_model_ready = bool(char_model_path and Path(char_model_path).exists())

        header_text = "Panel E1: Start pierwszej iteracji"
        intro_text = "Najpierw wybierasz obrazy tej iteracji, potem zatwierdzasz E1 i dopiero wtedy przechodzisz do E2."
        master_title = "Glowne obrazy iteracji:"
        choose_label = "Wybierz obrazy"

        if mode_is_assets:
            intro_text = "Wskaż obrazy tej iteracji, a niżej opcjonalnie podepnij gotowe anotacje tablic i modele startowe."
            master_title = "Obrazy tej iteracji:"
        elif mode_selected:
            if master_pool_images > 0 and master_pool is not None:
                intro_text = (
                    f"Wybrano katalog {Path(master_pool).name} z {master_pool_images} obrazami. "
                    "Zatwierdz E1, aby przejsc dalej."
                )
            else:
                intro_text = "Wskaż katalog obrazów tej iteracji, a potem zatwierdz E1."

        try:
            self.ingest_header_lbl.config(text=header_text)
            self.ingest_intro_lbl.config(text=intro_text, fg=palette.get("muted", "#c7c7c7"))
            self.lbl_ingest_master_title.config(text=master_title)
            self.btn_choose_master_pool.config(text=choose_label)
        except Exception:
            pass

        try:
            self._set_pack_visibility(self.ingest_header_lbl, False)
            self._set_pack_visibility(
                self.ingest_intro_lbl,
                mode_selected,
                anchor=tk.W,
                padx=10,
                pady=(0, 6),
                before=self.ingest_start_shell,
            )
            self._set_pack_visibility(
                self.ingest_top_section,
                mode_selected,
                fill=tk.X,
                padx=10,
                pady=(0, 6),
                before=self.ingest_body,
            )
            self._set_pack_visibility(
                self.ingest_body,
                mode_selected,
                fill=tk.BOTH,
                expand=True,
                padx=10,
                pady=(0, 6),
                before=self.ingest_insights_toggle_shell,
            )
            self._set_pack_visibility(
                self.ingest_insights_toggle_shell,
                mode_selected,
                fill=tk.X,
                padx=10,
                pady=(0, 6),
                before=self.ingest_insights_shell,
            )
            self._set_pack_visibility(self.ingest_start_title_lbl, mode_selected and mode_is_assets, fill=tk.X)
            self._set_pack_visibility(self.ingest_start_summary_lbl, mode_selected and mode_is_assets, fill=tk.X, pady=(4, 8))
            self._set_pack_visibility(self.ingest_start_detected_lbl, mode_selected and mode_is_assets, fill=tk.X, pady=(10, 0))
            self._set_pack_visibility(self.ingest_start_next_lbl, mode_selected and mode_is_assets, fill=tk.X, pady=(6, 0))
            self._set_pack_visibility(self.btn_choose_master_pool, not self._is_first_iteration_start_context(), side=tk.RIGHT, padx=(8, 0))
        except Exception:
            pass

        try:
            if visible and self.ingest_top_section is not None:
                self.ingest_start_shell.pack_configure(before=self.ingest_top_section)
            if mode_selected and self.ingest_start_shell is not None:
                self.ingest_intro_lbl.pack_configure(before=self.ingest_start_shell)
            if mode_selected and self.ingest_body is not None:
                self.ingest_top_section.pack_configure(before=self.ingest_body)
            if mode_selected and self.ingest_insights_toggle_shell is not None:
                self.ingest_body.pack_configure(before=self.ingest_insights_toggle_shell)
            if mode_selected and self.ingest_insights_shell is not None:
                self.ingest_insights_toggle_shell.pack_configure(before=self.ingest_insights_shell)
        except Exception:
            pass

        if mode_is_assets and self.ingest_start_title_lbl is not None:
            self.ingest_start_title_lbl.config(text="Jak zaczynasz 1. iteracje?")
        if mode_is_assets and self.ingest_start_summary_lbl is not None:
            self.ingest_start_summary_lbl.config(
                text="Wskaż tylko te zasoby, które rzeczywiscie chcesz wykorzystać na starcie."
            )

        try:
            self.btn_ingest_start_fresh.config(
                text="Wybierz katalog zdjęć"
            )
            self.btn_ingest_start_assets.config(
                text=("Wskaż pozostale zasoby: aktywne" if mode_is_assets and mode_selected else "Wskaż pozostale zasoby")
            )
        except Exception:
            pass

        if self.btn_ingest_start_fresh is not None:
            try:
                self.btn_ingest_start_fresh.config(state="normal")
            except Exception:
                pass
        if self.btn_ingest_start_assets is not None:
            try:
                self.btn_ingest_start_assets.config(state=("disabled" if mode_is_assets else "normal"))
            except Exception:
                pass

        for widget, enabled in (
            (self.btn_ingest_import_plate_run, mode_selected and mode_is_assets),
            (self.btn_ingest_pick_plate_model, mode_selected and mode_is_assets),
            (self.btn_ingest_pick_char_model, mode_selected and mode_is_assets),
        ):
            if widget is None:
                continue
            try:
                widget.config(state=("normal" if enabled else "disabled"))
            except Exception:
                pass
        try:
            self._set_pack_visibility(self.ingest_start_assets_row, mode_selected and mode_is_assets, anchor=tk.W, pady=(10, 0))
        except Exception:
            pass

        if not mode_selected:
            try:
                self._sync_ingest_wraps()
            except Exception:
                pass
            return

        detected_lines = []
        if master_pool_images > 0:
            detected_lines.append(f"Aktualnie: {master_pool_images} obrazów z katalogu {Path(master_pool).name}")
        else:
            detected_lines.append("Aktualnie: nie wskazano jeszcze obrazów tej iteracji")

        if mode_is_assets:
            if plate_ready_source:
                try:
                    detected_lines.append(f"Anotacje tablic: {Path(plate_ready_source.get('restore_run_dir')).name}")
                except Exception:
                    detected_lines.append("Anotacje tablic: gotowe do użycia")
            else:
                detected_lines.append("Anotacje tablic: brak")

            if plate_model_ready:
                plate_identity = self._get_model_identity_label(plate_model_path)
                plate_text = f"Model tablic: {Path(plate_model_path).name}"
                if plate_identity:
                    plate_text += f" | {plate_identity}"
                detected_lines.append(plate_text)
            else:
                detected_lines.append("Model tablic: brak")
            if char_model_ready:
                char_identity = self._get_model_identity_label(char_model_path)
                char_text = f"Model znaków: {Path(char_model_path).name}"
                if char_identity:
                    char_text += f" | {char_identity}"
                detected_lines.append(char_text)
            else:
                detected_lines.append("Model znaków: brak")

        if mode_is_assets and self.ingest_start_detected_lbl is not None:
            self.ingest_start_detected_lbl.config(text="\n".join(detected_lines))

        next_lines = []
        if master_pool_images <= 0:
            next_lines.append(
                "Dalej: wybierz obrazy tej iteracji."
                if not mode_is_assets
                else "Dalej: wskaż obrazy tej iteracji, a potem opcjonalnie dopnij zasoby."
            )
        elif plate_ready_source and char_ready_source:
            next_lines.append("Dalej: zatwierdz E1. Tor A otworzy korekte runu, a tor B będzie mogl wejsc od razu do Z3.")
        elif plate_ready_source:
            next_lines.append("Dalej: zatwierdz E1. Tor A otworzy korekte wykrytego runu.")
            next_lines.append("Tor B odblokuje się, jesli ten run zawiera komplet tablic dla Z3.")
        elif plate_model_ready:
            next_lines.append("Dalej: zatwierdz E1. Tor A uruchomi autoanotacje tablic na modelu projektu.")
        else:
            next_lines.append("Dalej: zatwierdź E1. Tor A wystartuje od nowego XML do ręcznej anotacji tablic.")

        if char_model_ready:
            next_lines.append(
                "Model znaków jest już zapisany w projekcie i w Z3 zostanie podstawiony automatycznie, "
                "ale sam nie odblokowuje jeszcze toru B bez przygotowania tablic."
            )

        if mode_is_assets and self.ingest_start_next_lbl is not None:
            self.ingest_start_next_lbl.config(text="\n".join(next_lines))

        try:
            self._refresh_ingest_insights_visibility(mode_selected=mode_selected)
            self._sync_ingest_wraps()
        except Exception:
            pass

    def _toggle_ingest_insights(self) -> None:
        self.ingest_insights_expanded = not bool(self.ingest_insights_expanded)
        self._refresh_ingest_insights_visibility()

    def _refresh_ingest_insights_visibility(self, mode_selected: bool | None = None) -> None:
        if mode_selected is None:
            mode_selected = bool(CAMPAIGN.get_active_project_name())

        expanded = bool(self.ingest_insights_expanded) and bool(mode_selected)
        btn = getattr(self, "ingest_insights_toggle_btn", None)
        hint = getattr(self, "ingest_insights_hint_lbl", None)

        if btn is not None:
            try:
                btn.config(text=("Ukryj analizę puli" if expanded else "Pokaż analizę puli"))
            except Exception:
                pass

        if hint is not None:
            hint_text = (
                "Histogram i rozkład znaków pomagają ocenić paczkę, ale nie są wymagane do zatwierdzenia E1."
                if expanded
                else "Histogram i rozkład znaków są dostępne jako sekcja dodatkowa."
            )
            try:
                hint.config(text=hint_text)
            except Exception:
                pass

        try:
            self._set_pack_visibility(self.ingest_insights_shell, expanded, fill=tk.X, padx=10, pady=(0, 6))
        except Exception:
            pass

        if expanded:
            try:
                self._refresh_ingest_balance_chart()
            except Exception:
                pass

    def _get_ingest_summary_style(self) -> dict:
        palette = getattr(self.app, "palette", {})
        return {
            "bg": palette.get("panel", "#252526"),
            "border": palette.get("panel_border", palette.get("border", "#3c3c3c")),
            "fg": palette.get("fg", "#f3f3f3"),
            "muted": palette.get("muted", "#c7c7c7"),
        }

    def _sync_ingest_wraps(self, _event=None):
        try:
            panel_width = max(int(getattr(self, "ingest_panel_frame").winfo_width() or 0), 680)
        except Exception:
            panel_width = 680

        try:
            info_width = max(int(getattr(self, "ingest_info_panel").winfo_width() or 0) - 18, 260)
        except Exception:
            info_width = 320

        try:
            chart_width = max(int(getattr(self, "ingest_chart_panel").winfo_width() or 0) - 18, 320)
        except Exception:
            chart_width = 460

        master_wrap = max(320, panel_width - 220)
        intro_wrap = max(420, panel_width - 40)

        for widget_name, wrap_value in (
            ("lbl_ingest_master_value", master_wrap),
            ("ingest_intro_lbl", intro_wrap),
            ("ingest_start_summary_lbl", intro_wrap),
            ("ingest_start_detected_lbl", intro_wrap),
            ("ingest_start_next_lbl", intro_wrap),
            ("ingest_insights_hint_lbl", intro_wrap),
            ("ingest_logic_lbl", info_width),
            ("ingest_selection_lbl", info_width),
            ("ingest_balance_summary_lbl", chart_width),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(wraplength=wrap_value)
            except Exception:
                pass

        status_wrap = max(440, panel_width - 70)
        for lbl in getattr(self, "ingest_status_labels", []):
            try:
                lbl.config(wraplength=status_wrap)
            except Exception:
                pass

    def _set_ingest_status_lines(self, line1="", line2="", line3=""):
        lines = [str(line1 or "").strip(), str(line2 or "").strip(), str(line3 or "").strip()]
        merged = "\n".join(line for line in lines if line)
        labels = list(getattr(self, "ingest_status_labels", []) or [])
        for idx, lbl in enumerate(labels):
            try:
                lbl.config(text=(merged if idx == 0 else ""))
            except Exception:
                pass
        try:
            self._set_pack_visibility(
                getattr(self, "ingest_status_shell", None),
                bool(merged),
                fill=tk.X,
                padx=10,
                pady=(2, 6),
            )
        except Exception:
            pass

    def _get_iteration_image_count(self) -> int:
        iter_dir = CAMPAIGN.get_iteration_raw_dir()
        return self._count_images_in_dir(iter_dir, recursive=True)

    def _load_ingest_manifest_cached(self) -> dict:
        try:
            manifest_path = CAMPAIGN.get_ingest_manifest_path()
        except Exception:
            manifest_path = None

        cache = getattr(self, "_dashboard_perf_cache", {})
        json_cache = cache.get("json_payloads", {}) if isinstance(cache, dict) else {}
        cache_key = ("ingest_manifest", self._build_cache_token_for_path(manifest_path))
        cached = json_cache.get(cache_key) if isinstance(json_cache, dict) else None
        if isinstance(cached, dict):
            return dict(cached)

        try:
            manifest = CAMPAIGN.load_ingest_manifest()
        except Exception:
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}

        if isinstance(json_cache, dict):
            if len(json_cache) > 128:
                json_cache.clear()
            json_cache[cache_key] = dict(manifest)
        return dict(manifest)

    def _load_latest_ingest_plan_for_current_iteration(self) -> dict:
        try:
            plan_path = CAMPAIGN.get_latest_ingest_plan_path()
        except Exception:
            plan_path = None

        cache = getattr(self, "_dashboard_perf_cache", {})
        json_cache = cache.get("json_payloads", {}) if isinstance(cache, dict) else {}
        cache_key = ("latest_ingest_plan", self._build_cache_token_for_path(plan_path))
        cached = json_cache.get(cache_key) if isinstance(json_cache, dict) else None
        if isinstance(cached, dict):
            plan = dict(cached)
        else:
            plan = CAMPAIGN.load_latest_ingest_plan()
            if not isinstance(plan, dict):
                plan = {}
            if isinstance(json_cache, dict):
                if len(json_cache) > 128:
                    json_cache.clear()
                json_cache[cache_key] = dict(plan)
        if not isinstance(plan, dict):
            return {}
        if int(plan.get("iteration", 0) or 0) != CAMPAIGN.get_current_iteration_num():
            return {}
        if str(plan.get("project", "") or "").strip() != str(CAMPAIGN.get_active_project_name() or "").strip():
            return {}
        current_master_pool = CAMPAIGN.get_master_pool_dir()
        plan_master_pool = str(plan.get("master_pool_dir", "") or "").strip()
        if current_master_pool is None and plan_master_pool:
            return {}
        if current_master_pool is not None and plan_master_pool and plan_master_pool != str(current_master_pool):
            return {}
        return plan

    def _recalculate_current_ingest_plan(self):
        if not isinstance(self.current_ingest_plan, dict):
            self.current_ingest_plan = {}
            return

        selected_items = self.current_ingest_plan.get("selected", []) or []
        current_balance = Counter(self.current_ingest_plan.get("current_balance", {}) or {})
        selected_balance = Counter()
        for item in selected_items:
            if not isinstance(item, dict):
                continue
            selected_balance.update(item.get("char_histogram", {}) or {})

        predicted = Counter(current_balance)
        predicted.update(selected_balance)

        self.current_ingest_plan["selected_total"] = len(selected_items)
        self.current_ingest_plan["selected_balance"] = {
            ch: int(selected_balance.get(ch, 0))
            for ch in CHAR_ALPHABET
        }
        self.current_ingest_plan["predicted_balance_after"] = {
            ch: int(predicted.get(ch, 0))
            for ch in CHAR_ALPHABET
        }

    def _format_histogram_compact(self, char_hist: dict, limit: int = 5) -> str:
        if not isinstance(char_hist, dict):
            return "brak"

        items = [
            (str(ch), int(value))
            for ch, value in char_hist.items()
            if int(value or 0) > 0
        ]
        if not items:
            return "brak"

        items.sort(key=lambda entry: (-entry[1], entry[0]))
        return ", ".join(f"{ch}:{value}" for ch, value in items[:limit])

    def _get_selected_ingest_indices(self) -> list[int]:
        if self.ingest_plan_listbox is None:
            return []
        try:
            indices = []
            for raw_idx in self.ingest_plan_listbox.curselection():
                idx = int(raw_idx)
                if 0 <= idx < len(self.ingest_plan_items):
                    indices.append(idx)
            return sorted(set(indices))
        except Exception:
            return []

    def _refresh_ingest_logic_text(self):
        if self.ingest_logic_lbl is None:
            return

        plan_count = int(self.current_ingest_plan.get("selected_total", 0) or 0)
        selected_balance = Counter(self.current_ingest_plan.get("selected_balance", {}) or {})
        snapshot_balance = Counter((self.last_ingest_snapshot or {}).get("char_balance", {}) or {})
        rare_chars = [
            ch for ch in CHAR_ALPHABET
            if int(snapshot_balance.get(ch, 0)) > 0
        ]
        rare_chars.sort(key=lambda ch: (int(snapshot_balance.get(ch, 0)), ch))
        rare_preview = ", ".join(
            f"{ch}:{int(snapshot_balance.get(ch, 0))}"
            for ch in rare_chars[:6]
        ) or "brak danych"

        if plan_count > 0:
            text = (
                "Załadowany został aktualny wybrany folder zdjęć dla E1.\n"
                "1. System wczytuje wszystkie poprawne zdjęcia z głównej puli.\n"
                "2. Z nazwy każdego pliku odczytuje tekst tablic i buduje histogram znaków.\n"
                "3. Możesz zatwierdzić zestaw zdjęć jako wejście do iteracji.\n"
                f"4. Najczęstsze znaki w tej chwili: {self._format_histogram_compact(selected_balance, limit=6)}."
            )
        else:
            text = (
                "Kliknij „Wybierz...”, aby wskazać główną pulę i automatycznie wczytać wybrany folder zdjęć do E1.\n"
                "Następnie zatwierdź E1, aby skopiować zdjęcia do iteracji.\n"
                f"Najrzadsze znaki w zaakceptowanym zbiorze treningowym teraz: {rare_preview}."
            )

        try:
            self.ingest_logic_lbl.config(text=text)
        except Exception:
            pass

    def _refresh_ingest_selection_info(self):
        if self.ingest_selection_lbl is None:
            return

        if not self.current_ingest_plan or not self.ingest_plan_items:
            text = (
                "Po załadowaniu wybranego folderu zdjęć zaznacz jedno albo kilka zdjęć na liście. "
                "Panel pokaże, jaki wpływ będzie miało ich usunięcie z E1."
            )
            try:
                self.ingest_selection_lbl.config(text=text)
            except Exception:
                pass
            return

        selected_indices = self._get_selected_ingest_indices()
        if not selected_indices:
            text = (
                "Zaznacz jedno albo kilka zdjęć na liście. "
                "Możesz używać Ctrl i Shift jak w systemie Windows."
            )
            try:
                self.ingest_selection_lbl.config(text=text)
            except Exception:
                pass
            return

        selected_items = [
            self.ingest_plan_items[idx]
            for idx in selected_indices
            if 0 <= idx < len(self.ingest_plan_items)
        ]
        if not selected_items:
            return

        selected_texts = []
        removed_hist = Counter()
        for item in selected_items:
            for text_value in item.get("ground_truth_texts", []) or []:
                text_value = str(text_value).strip()
                if text_value and text_value not in selected_texts:
                    selected_texts.append(text_value)
            removed_hist.update(item.get("char_histogram", {}) or {})

        current_hist = Counter(self.current_ingest_plan.get("selected_balance", {}) or {})
        after_hist = Counter(current_hist)
        for ch, value in removed_hist.items():
            after_hist[ch] = max(0, int(after_hist.get(ch, 0)) - int(value))

        impact_rows = []
        for ch, removed_count in removed_hist.items():
            current_value = int(current_hist.get(ch, 0))
            after_value = int(after_hist.get(ch, 0))
            if removed_count > 0:
                impact_rows.append((str(ch), int(removed_count), current_value, after_value))
        impact_rows.sort(key=lambda entry: (-entry[1], entry[0]))

        zeroed_chars = [
            ch for ch, removed_count, current_value, after_value in impact_rows
            if current_value > 0 and after_value == 0
        ]

        texts_preview = ", ".join(selected_texts[:6])
        if len(selected_texts) > 6:
            texts_preview += f" +{len(selected_texts) - 6} więcej"
        if not texts_preview:
            texts_preview = "brak ground truth"

        impact_preview = ", ".join(
            f"{ch}: {before}->{after}"
            for ch, _removed, before, after in impact_rows[:6]
        ) or "brak danych"

        text = (
            f"Zaznaczono {len(selected_items)} zdjęć.\n"
            f"Tablice z nazw plików: {texts_preview}\n"
            f"Znaki w zaznaczeniu: {self._format_histogram_compact(removed_hist, limit=8)}\n"
            f"Po usunięciu z wybranego folderu zdjęć najbardziej spadną: {impact_preview}"
        )
        if zeroed_chars:
            text += f"\nPo usunięciu całkiem znikną z E1: {', '.join(zeroed_chars[:6])}."
        try:
            self.ingest_selection_lbl.config(text=text)
        except Exception:
            pass

    def _refresh_ingest_balance_chart(self):
        canvas = self.ingest_balance_canvas
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        field_bg = palette.get("field", "#1a1a1a")
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#b8b8b8")
        panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        accent_color = "#f29f05"
        top_color = "#ffbf47"

        try:
            canvas.config(
                bg=field_bg,
                highlightbackground=panel_border,
                highlightcolor=panel_border,
            )
        except Exception:
            pass
        canvas.delete("all")

        package_balance = Counter(self.current_ingest_plan.get("selected_balance", {}) or {})
        package_total = sum(int(v) for v in package_balance.values())
        package_images = int(self.current_ingest_plan.get("selected_total", 0) or 0)
        raw_package_images = int(self.current_ingest_plan.get("raw_total", package_images) or package_images)

        if package_total <= 0:
            width = max(int(canvas.winfo_width() or 280), 280)
            canvas.create_text(
                width // 2,
                95,
                text="Brak danych E1 do pokazania.\nWskaż wybrany folder zdjęć przez „Wybierz...”.",
                fill=muted,
                justify=tk.CENTER,
                font=("Segoe UI", 9),
            )
            try:
                self.ingest_balance_summary_lbl.config(
                    text=(
                        "Histogram pokazuje liczbę wystąpień każdego znaku w aktualnym wybranym folderze zdjęć E1. "
                        "Najwyższy słupek oznacza znak, który dominuje w bieżącej liście."
                    )
                )
            except Exception:
                pass
            return

        width = max(int(canvas.winfo_width() or 560), 560)
        height = max(int(canvas.winfo_height() or 220), 220)
        left_margin = 26
        right_margin = 16
        top_margin = 18
        bottom_margin = 42
        plot_height = max(height - top_margin - bottom_margin, 80)
        plot_width = max(width - left_margin - right_margin, 180)
        max_value = max([int(package_balance.get(ch, 0)) for ch in CHAR_ALPHABET] + [1])
        cell_width = plot_width / float(len(CHAR_ALPHABET))
        top_chars = {
            ch for ch, value in sorted(
                ((ch, int(package_balance.get(ch, 0))) for ch in CHAR_ALPHABET),
                key=lambda entry: (-entry[1], entry[0])
            )[:4]
            if value > 0
        }

        base_y = top_margin + plot_height
        canvas.create_line(left_margin, base_y, width - right_margin, base_y, fill=panel_border)
        for grid_ratio, label in ((1.0, str(max_value)), (0.5, str(max(1, round(max_value / 2)))), (0.0, "0")):
            y = top_margin + int((1.0 - grid_ratio) * plot_height)
            canvas.create_line(left_margin, y, width - right_margin, y, fill=panel_border)
            canvas.create_text(4, y, text=label, anchor="w", fill=muted, font=("Segoe UI", 7))

        for idx, ch in enumerate(CHAR_ALPHABET):
            count = int(package_balance.get(ch, 0))
            x0 = left_margin + (idx * cell_width) + 1
            x1 = left_margin + ((idx + 1) * cell_width) - 1
            if x1 <= x0:
                x1 = x0 + 2
            bar_height = int(plot_height * (count / max_value)) if max_value > 0 else 0
            y0 = base_y - bar_height
            fill = top_color if ch in top_chars else accent_color
            if count > 0:
                canvas.create_rectangle(x0, y0, x1, base_y, fill=fill, width=0)
            else:
                canvas.create_line(x0, base_y - 1, x1, base_y - 1, fill=panel_border)
            canvas.create_text((x0 + x1) / 2, base_y + 10, text=ch, fill=fg, font=("Consolas", 7))
            if count > 0 and ch in top_chars:
                canvas.create_text((x0 + x1) / 2, max(y0 - 8, 8), text=str(count), fill=muted, font=("Segoe UI", 7))

        dominant = [
            (ch, int(package_balance.get(ch, 0)))
            for ch in CHAR_ALPHABET
            if int(package_balance.get(ch, 0)) > 0
        ]
        dominant.sort(key=lambda entry: (-entry[1], entry[0]))
        dominant_text = ", ".join(
            f"{ch}:{count} ({(count / package_total) * 100:.1f}%)"
            for ch, count in dominant[:6]
        ) or "brak"
        missing = [ch for ch in CHAR_ALPHABET if int(package_balance.get(ch, 0)) == 0]
        missing_text = ", ".join(missing[:10]) if missing else "brak"
        summary = (
            "Wysokość słupka = liczba wystąpień danego znaku w nazwach tablic zdjęć należących do aktualnego wybranego folderu zdjęć E1.\n"
            f"Wybrany folder zdjęć E1 zawiera teraz {raw_package_images} zdjęć"
            + (
                f", z czego {package_images} weszło do planu E1"
                if raw_package_images != package_images
                else ""
            )
            + f", oraz {package_total} znaków GT w planie. "
            + f"Najczęstsze znaki: {dominant_text}.\n"
            + f"Brakujące znaki w tym wybranym folderze zdjęć: {missing_text}."
        )
        try:
            self.ingest_balance_summary_lbl.config(text=summary)
        except Exception:
            pass

    def _on_ingest_selection_changed(self, _event=None):
        self._refresh_ingest_selection_info()

    def _theme_step1_ingest_panel(self):
        palette = getattr(self.app, "palette", {})
        fallback_bg = palette.get("panel", "#252526")
        frame_bg = fallback_bg

        if self.step1_roadmap_item is not None:
            extra_frame = self.step1_roadmap_item.get("extra_actions_frame")
            if extra_frame is not None:
                try:
                    frame_bg = str(extra_frame.cget("bg") or fallback_bg)
                except Exception:
                    frame_bg = fallback_bg

        try:
            if self.ingest_panel_frame is not None:
                self.ingest_panel_frame.config(
                    bg=frame_bg,
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        for widget_name, fg_value in (
            ("ingest_header_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_intro_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_start_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_start_summary_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_start_detected_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_start_next_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_insights_hint_lbl", palette.get("muted", "#c7c7c7")),
            ("lbl_ingest_master_title", palette.get("fg", "#f3f3f3")),
            ("lbl_ingest_master_value", palette.get("accent", "#4fc1ff")),
            ("lbl_ingest_batch_title", palette.get("fg", "#f3f3f3")),
            ("ingest_list_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_logic_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_logic_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_balance_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_balance_summary_lbl", palette.get("muted", "#c7c7c7")),
            ("ingest_selection_title_lbl", palette.get("fg", "#f3f3f3")),
            ("ingest_selection_lbl", palette.get("muted", "#c7c7c7")),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(bg=frame_bg, fg=fg_value)
            except Exception:
                pass

        for widget_name in (
            "ingest_start_shell",
            "ingest_start_panel",
            "ingest_start_assets_row",
            "ingest_top_section",
            "ingest_body",
            "ingest_left_col",
            "ingest_right_col",
            "ingest_master_row",
            "ingest_master_value_row",
            "ingest_config_row",
            "ingest_actions_row",
            "ingest_approve_row",
            "ingest_footer_row",
            "ingest_insights_toggle_shell",
            "ingest_insights_shell",
            "ingest_chart_panel",
            "ingest_info_panel",
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(bg=frame_bg)
            except Exception:
                pass

        bordered_widgets = ()
        for widget_name in bordered_widgets:
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                )
            except Exception:
                pass

        try:
            if getattr(self, "ingest_insights_shell", None) is not None:
                self.ingest_insights_shell.config(
                    bg=frame_bg,
                    highlightthickness=0,
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        try:
            summary_style = self._get_ingest_summary_style()
            if getattr(self, "ingest_status_shell", None) is not None:
                self.ingest_status_shell.config(
                    bg=summary_style["bg"],
                    highlightthickness=1,
                    highlightbackground=summary_style["border"],
                    highlightcolor=summary_style["border"],
                )
            if getattr(self, "ingest_status_panel", None) is not None:
                self.ingest_status_panel.config(bg=summary_style["bg"])
            for idx, lbl in enumerate(getattr(self, "ingest_status_labels", [])):
                lbl.config(
                    bg=summary_style["bg"],
                    fg=(summary_style["fg"] if idx == 0 else summary_style["muted"]),
                    font=("Segoe UI", 10, "normal"),
                )
        except Exception:
            pass

        self._sync_ingest_wraps()
        self._refresh_ingest_balance_chart()

    def _populate_ingest_plan_list(self):
        self.ingest_plan_items = list(self.current_ingest_plan.get("selected", []) or [])
        if self.ingest_plan_listbox is None:
            return

        self.ingest_plan_listbox.delete(0, tk.END)
        for index, item in enumerate(self.ingest_plan_items, start=1):
            name = str(item.get("name", "") or "").strip()
            texts = ", ".join(item.get("ground_truth_texts", []) or [])
            left = texts if texts else "brak GT"
            label = (
                f"{index:03d}. "
                f"{shorten(left, width=28, placeholder='...')} | "
                f"{shorten(name, width=70, placeholder='...')}"
            )
            self.ingest_plan_listbox.insert(tk.END, label)

        if self.ingest_plan_items:
            try:
                self.ingest_plan_listbox.selection_clear(0, tk.END)
                self.ingest_plan_listbox.selection_set(0)
                self.ingest_plan_listbox.activate(0)
            except Exception:
                pass

    def _refresh_ingest_balance_only(self):
        if not CAMPAIGN.get_active_project_name():
            return

        snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()
        self._refresh_ingest_panel(snapshot_override=snapshot)

        try:
            self.app.update_status("Odświeżono bilans znaków dla przygotowania wybranego folderu zdjęć E1.", "info")
        except Exception:
            pass

    def _refresh_ingest_panel(self, snapshot_override: dict = None):
        has_project = bool(CAMPAIGN.get_active_project_name())
        step1_status = CAMPAIGN.get_step1_status() if has_project else "pending"
        step1_approved = step1_status == "approved"
        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_text = str(master_pool) if master_pool else "Brak ustawionej głównej puli zdjęć"
        self.ingest_master_pool_var.set(master_pool_text)
        master_pool_exists = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        self._theme_step1_ingest_panel()
        self._refresh_project_start_panel()
        project_start_mode = self._get_project_start_mode()

        snapshot = snapshot_override or CAMPAIGN.load_ingest_balance_snapshot()
        if has_project and not snapshot:
            snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()
        self.last_ingest_snapshot = snapshot or {}

        iter_image_count = self._get_iteration_image_count() if has_project else 0
        master_pool_image_count = self._count_images_in_dir(master_pool, recursive=True) if master_pool_exists else 0

        if has_project:
            current_iter = CAMPAIGN.get_current_iteration_num()
            current_proj = CAMPAIGN.get_active_project_name()
            latest_plan = self._load_latest_ingest_plan_for_current_iteration()
            if iter_image_count > 0:
                self.current_ingest_plan = {}
            elif (
                isinstance(self.current_ingest_plan, dict)
                and int(self.current_ingest_plan.get("iteration", 0) or 0) == current_iter
                and str(self.current_ingest_plan.get("project", "") or "").strip() == str(current_proj or "").strip()
                and self.current_ingest_plan.get("selected") is not None
            ):
                self._recalculate_current_ingest_plan()
            elif latest_plan:
                self.current_ingest_plan = latest_plan
                self._recalculate_current_ingest_plan()
            else:
                self.current_ingest_plan = {}
            self._populate_ingest_plan_list()
        else:
            self.current_ingest_plan = {}
            self._populate_ingest_plan_list()

        plan_count = int(self.current_ingest_plan.get("selected_total", 0) or 0)
        raw_plan_count = int(self.current_ingest_plan.get("raw_total", plan_count) or plan_count)
        manifest = self._load_ingest_manifest_cached() if has_project else {}
        step1_context = self._get_step1_manifest_context(manifest if isinstance(manifest, dict) else None)
        project_pool_total = int(step1_context.get("project_pool_total_after", step1_context.get("project_pool_total", 0)) or 0)
        source_total = int(step1_context.get("source_total", 0) or 0)
        approved_images = int(step1_context.get("approved_images", 0) or 0)
        approved_plates = int(step1_context.get("approved_plates", 0) or 0)
        current_iteration_package = int(
            step1_context.get("current_iteration_package_count", 0)
            or iter_image_count
            or plan_count
            or 0
        )
        new_to_project_count = int(step1_context.get("new_to_project_count", 0) or 0)
        skipped_approved_count = int(step1_context.get("skipped_duplicate_filenames", 0) or 0)

        if not step1_approved and plan_count > 0:
            project_pool_before = int(approved_images or 0)
            new_to_project_count = int(
                self.current_ingest_plan.get(
                    "new_to_project_total",
                    plan_count,
                ) or 0
            )
            project_pool_total = max(project_pool_total, project_pool_before + new_to_project_count)
            current_iteration_package = max(current_iteration_package, plan_count)
            skipped_approved_count = int(
                self.current_ingest_plan.get("skipped_duplicate_filenames", self.current_ingest_plan.get("skipped_used", 0)) or 0
            )
            source_total = max(source_total, raw_plan_count)

        if project_pool_total <= 0:
            project_pool_total = max(int(source_total or 0), int(raw_plan_count or 0), int(current_iteration_package or 0))

        line1 = (
            f"Łączna pula obrazów projektu: {project_pool_total} zdjęć = "
            f"{approved_images} zatwierdzonych do treningu YOLO + "
            f"{current_iteration_package} do oznaczenia w bieżącej iteracji."
        )
        line2 = f"Zatwierdzone w poprzednich iteracjach do treningu YOLO: {approved_images} zdjęć / {approved_plates} tablic."
        line3 = f"Do oznaczenia w bieżącej iteracji: {current_iteration_package} zdjęć."
        if current_iteration_package > 0 and step1_approved:
            if source_total > 0 and (new_to_project_count > 0 or skipped_approved_count > 0):
                line3 = (
                    f"{line3} Z tej paczki {new_to_project_count} jest nowych dla projektu, "
                    f"a {skipped_approved_count} było już zatwierdzonych do treningu YOLO."
                )
        elif iter_image_count > 0:
            line3 = (
                f"{line3} W folderze iteracji są już obrazy, ale E1 nie zostało jeszcze zatwierdzone. "
                "Kliknij „Zatwierdź E1”, aby odblokować E2."
            )
        elif plan_count > 0:
            skipped_invalid = int(self.current_ingest_plan.get("skipped_invalid_ground_truth", 0) or 0)
            skipped_duplicates = int(
                self.current_ingest_plan.get("skipped_duplicate_filenames", self.current_ingest_plan.get("skipped_used", 0)) or 0
            )
            if raw_plan_count > plan_count:
                line3_parts = [
                    f"{line3}",
                    f"Wybrany folder zdjęć zawiera {raw_plan_count} obrazów.",
                    f"Do planu E1 weszło {plan_count}.",
                ]
                if skipped_duplicates > 0:
                    line3_parts.append(f"Pominięto {skipped_duplicates} dubli po nazwie.")
                if skipped_invalid > 0:
                    line3_parts.append(f"Pominięto {skipped_invalid} plików bez poprawnego GT w nazwie.")
                line3 = " ".join(line3_parts)
        elif has_project and master_pool and not master_pool_exists:
            line3 = f"{line3} Zapisana główna pula zdjęć nie istnieje na dysku. Wskaż poprawny katalog albo użyj ścieżki ręcznej."
        elif has_project and master_pool_exists:
            line3 = (
                f"{line3} Główna pula zdjęć jest gotowa. Kliknij „Wybierz...”, "
                "a system automatycznie załaduje paczkę wejściową tej iteracji."
            )
        if has_project and master_pool_exists and project_start_mode == "assets" and self._is_first_iteration_start_context():
            line3 = (
                f"{line3} Obrazy tej iteracji są już wskazane. Możesz teraz zatwierdzic E1 "
                "albo dopiąć jeszcze gotowe anotacje tablic i modele startowe."
            )
        self._set_ingest_status_lines(line1, line2, line3)

        enable_apply = bool((plan_count > 0 and iter_image_count == 0) or (iter_image_count > 0 and not step1_approved))
        for widget, enabled in (
            (self.btn_choose_master_pool, has_project),
            (self.btn_apply_ingest_plan, enable_apply),
        ):
            if widget is None:
                continue
            try:
                widget.config(state="normal" if enabled else "disabled")
            except Exception:
                pass

        self._refresh_ingest_logic_text()
        self._refresh_ingest_selection_info()
        self._refresh_ingest_balance_chart()

    def _choose_master_pool_dir(self) -> bool:
        if not CAMPAIGN.get_active_project_name():
            return False

        current = CAMPAIGN.get_master_pool_dir()
        initial = current if current and current.exists() else Path(CONFIG.DIR_1_RAW)
        dialog_title = "Wybierz obrazy tej iteracji"
        if not self._is_first_iteration_start_context():
            dialog_title = "Wybierz katalog głównej puli zdjęć dla aktywnego projektu"
        selected = filedialog.askdirectory(
            initialdir=str(initial),
            title="Wybierz katalog głównej puli zdjęć dla aktywnego projektu",
        )
        if not selected:
            return False

        CAMPAIGN.set_master_pool_dir(selected)
        self.current_ingest_plan = {}
        image_count = self._count_images_in_dir(Path(selected), recursive=True)
        iter_image_count = self._get_iteration_image_count()

        if iter_image_count == 0:
            self._generate_ingest_plan()
        else:
            self._refresh_ingest_panel()

        try:
            if iter_image_count == 0:
                status_text = (
                    f"Zapisano katalog głównej puli zdjęć. Wykryto {image_count} obrazów. "
                    "Wybrany folder zdjęć został załadowany automatycznie."
                )
            else:
                status_text = (
                    f"Zapisano katalog głównej puli zdjęć. Wykryto {image_count} obrazów. "
                    "W folderze iteracji są już zdjęcia, więc aktywny pozostaje tylko etap zatwierdzenia E1."
                )
            self.app.update_status(status_text, "info")
        except Exception:
            pass
        return True

    def _build_main_pack_plan(
        self,
        master_pool_dir: Path,
        current_balance: dict | None = None,
    ) -> dict:
        master_pool_dir = Path(master_pool_dir)
        if not master_pool_dir.exists() or not master_pool_dir.is_dir():
            raise FileNotFoundError(f"Główna pula zdjęć nie istnieje: {master_pool_dir}")

        planner = CampaignIngestPlanner()
        selected_items = []
        selected_hist = Counter()
        skipped_invalid_gt = 0
        skipped_duplicate_filenames = 0
        skipped_duplicate_approved = 0
        project_overlap_filenames = 0
        approved_registry = CAMPAIGN.get_used_image_registry()
        approved_names = {
            str(name or "").strip().lower()
            for name in (approved_registry.get("filenames", []) or [])
            if str(name or "").strip()
        }

        current_counter = Counter()
        for ch in CHAR_ALPHABET:
            current_counter[ch] = int((current_balance or {}).get(ch, 0))

        image_paths = sorted(
            (
                image_path
                for image_path in master_pool_dir.rglob("*")
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ),
            key=lambda p: p.as_posix().lower(),
        )
        raw_total = int(len(image_paths))

        for image_path in image_paths:
            image_name_key = str(image_path.name or "").strip().lower()
            if image_name_key and image_name_key in approved_names:
                skipped_duplicate_filenames += 1
                skipped_duplicate_approved += 1
                continue

            gt_texts = planner.extract_true_texts_from_filename(image_path.name)
            if not gt_texts:
                skipped_invalid_gt += 1
                continue

            char_hist = planner.build_char_histogram(gt_texts)
            if not char_hist:
                skipped_invalid_gt += 1
                continue

            try:
                source_path = str(image_path.resolve())
            except Exception:
                source_path = str(image_path.absolute())

            selected_hist.update(char_hist)
            selected_items.append(
                {
                    "name": image_path.name,
                    "source_path": source_path,
                    "source_key": planner.make_source_key(image_path, master_pool_dir=master_pool_dir),
                    "ground_truth_texts": list(gt_texts),
                    "char_histogram": dict(char_hist),
                    "score": 0.0,
                    "score_details": {},
                }
            )

        predicted_counter = Counter(current_counter)
        predicted_counter.update(selected_hist)
        new_to_project_total = int(len(selected_items))

        return {
            "ok": True,
            "planner_version": "main_pack_v1",
            "generated_at": datetime.now().isoformat(),
            "project": CAMPAIGN.get_active_project_name() or "",
            "iteration": int(CAMPAIGN.get_current_iteration_num() or 1),
            "master_pool_dir": str(master_pool_dir.resolve()),
            "batch_size": 0,
            "raw_total": raw_total,
            "candidates_total": raw_total,
            "selected_total": len(selected_items),
            "new_to_project_total": new_to_project_total,
            "skipped_used": skipped_duplicate_filenames,
            "skipped_duplicate_filenames": skipped_duplicate_filenames,
            "skipped_duplicate_approved_filenames": skipped_duplicate_approved,
            "project_overlap_filenames": project_overlap_filenames,
            "skipped_invalid_ground_truth": skipped_invalid_gt,
            "current_balance": {ch: int(current_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected_balance": {ch: int(selected_hist.get(ch, 0)) for ch in CHAR_ALPHABET},
            "predicted_balance_after": {ch: int(predicted_counter.get(ch, 0)) for ch in CHAR_ALPHABET},
            "selected": selected_items,
        }

    def _generate_ingest_plan(self):
        if not CAMPAIGN.get_active_project_name():
            return

        master_pool = CAMPAIGN.get_master_pool_dir()
        if master_pool is None:
            messagebox.showwarning("Brak wybranego folderu zdjęć", "Najpierw wskaż główną pulę zdjęć.")
            return
        if not master_pool.exists() or not master_pool.is_dir():
            messagebox.showwarning("Brak wybranego folderu zdjęć", f"Katalog nie istnieje:\n{master_pool}")
            return

        snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()

        try:
            plan = self._build_main_pack_plan(
                master_pool_dir=master_pool,
                current_balance=(snapshot or {}).get("char_balance", {}),
            )
        except Exception as e:
            messagebox.showerror("Błąd ładowania wybranego folderu zdjęć E1", str(e))
            return

        if not plan.get("ok", False):
            messagebox.showwarning("Brak wybranego folderu zdjęć E1", str(plan.get("error", "Nie udało się załadować wybranego folderu zdjęć E1.")))
            return

        self.current_ingest_plan = plan
        self._recalculate_current_ingest_plan()
        selected_total = int(plan.get("selected_total", 0) or 0)
        raw_total = int(plan.get("raw_total", selected_total) or selected_total)
        skipped_invalid = int(plan.get("skipped_invalid_ground_truth", 0) or 0)
        skipped_duplicates = int(plan.get("skipped_duplicate_filenames", plan.get("skipped_used", 0)) or 0)
        try:
            CAMPAIGN.save_latest_ingest_plan(self.current_ingest_plan)
        except Exception:
            pass
        self._refresh_ingest_panel(snapshot_override=snapshot)

        if selected_total <= 0:
            if skipped_duplicates > 0 and skipped_invalid <= 0:
                messagebox.showwarning(
                    "Brak nowych zdjęć do iteracji",
                    (
                        f"Wybrany folder zawiera {raw_total} zdjęć, ale wszystkie zostały odrzucone jako duble po nazwie.\n\n"
                        "Ta paczka nie wnosi nowych obrazów do projektu."
                    ),
                )
                return
            messagebox.showwarning(
                "Brak poprawnych pozycji w wybranym folderze zdjęć",
                (
                    "Nie znaleziono zdjęć z poprawnym ground truth w nazwie pliku.\n"
                    "Sprawdź nazewnictwo plików w głównej puli."
                ),
            )
            return

        try:
            status_text = f"Załadowano wybrany folder zdjęć E1: {raw_total} zdjęć w folderze."
            if raw_total != selected_total:
                status_text += f" Do planu E1 weszło {selected_total}."
            if skipped_duplicates > 0:
                status_text += f" Pominięto {skipped_duplicates} dubli po nazwie."
            if skipped_invalid > 0:
                status_text += f" Pominięto {skipped_invalid} plików bez poprawnego GT w nazwie."
            self.app.update_status(status_text, "info")
        except Exception:
            pass

    def _remove_selected_ingest_items(self):
        if self.ingest_plan_listbox is None or not self.current_ingest_plan:
            return

        selected_indices = list(self.ingest_plan_listbox.curselection())
        if not selected_indices:
            return

        selected_indices = sorted(selected_indices, reverse=True)
        plan_items = list(self.current_ingest_plan.get("selected", []) or [])
        for idx in selected_indices:
            if 0 <= idx < len(plan_items):
                plan_items.pop(idx)

        self.current_ingest_plan["selected"] = plan_items
        self._recalculate_current_ingest_plan()
        try:
            CAMPAIGN.save_latest_ingest_plan(self.current_ingest_plan)
        except Exception:
            pass
        self._refresh_ingest_panel()

    def _approve_current_iteration_package(
        self,
        target_iter_dir: Path,
        source_dir: Path = None,
        selected_source_files=None,
        selection_mode: str = "manual",
        proposal_summary: dict = None,
    ) -> int:
        target_iter_dir = Path(target_iter_dir)
        target_iter_dir.mkdir(parents=True, exist_ok=True)

        selected_files = list(selected_source_files or [])
        if not selected_files:
            selected_files = [
                image_path for image_path in target_iter_dir.iterdir()
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ]

        summary_payload = dict(proposal_summary or {})
        package_count = int(len(selected_files) or 0)
        new_to_project_count = int(
            summary_payload.get(
                "new_to_project_count",
                package_count,
            ) or 0
        )

        approved_stats = self._get_plate_approved_set_stats() or {}
        approved_images_before = int(summary_payload.get("approved_images_before_iteration", approved_stats.get("images", 0)) or 0)
        approved_plates_before = int(summary_payload.get("approved_plates_before_iteration", approved_stats.get("plates", 0)) or 0)
        project_pool_total_before = int(
            summary_payload.get(
                "project_pool_total_before_iteration",
                approved_images_before,
            ) or 0
        )
        project_pool_total_after = int(
            summary_payload.get(
                "project_pool_total_after_iteration",
                max(project_pool_total_before, approved_images_before) + new_to_project_count,
            ) or 0
        )

        if package_count > 0 and "source_total" not in summary_payload:
            summary_payload["source_total"] = package_count
        summary_payload["current_iteration_package_count"] = package_count
        summary_payload["new_to_project_count"] = new_to_project_count
        summary_payload["project_pool_total_before_iteration"] = project_pool_total_before
        summary_payload["project_pool_total_after_iteration"] = project_pool_total_after
        summary_payload["approved_images_before_iteration"] = approved_images_before
        summary_payload["approved_plates_before_iteration"] = approved_plates_before

        source_root = Path(source_dir) if source_dir else target_iter_dir
        try:
            CAMPAIGN.record_iteration_ingest(
                source_dir=source_root,
                selected_source_files=selected_files,
                selection_mode=selection_mode,
                proposal_summary=summary_payload,
            )
        except Exception as e:
            logger.debug(f"Nie udało się zapisać manifestu E1 dla {target_iter_dir}: {e}")

        CAMPAIGN.approve_step1()
        if CAMPAIGN.get_current_step() < 2:
            CAMPAIGN.set_current_step(2)
        self.step1_panel_expanded = False
        self.current_ingest_plan = {}
        self._refresh_dashboard()
        return len(selected_files)

    def _apply_current_ingest_plan(self):
        if not CAMPAIGN.get_active_project_name():
            return
        if not self.current_ingest_plan:
            raw_dir = CAMPAIGN.get_dir("raw")
            if raw_dir is None:
                return
            iter_num = CAMPAIGN.get_current_iteration_num()
            target_iter_dir = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
            if not target_iter_dir.exists() or not target_iter_dir.is_dir():
                messagebox.showwarning("Brak wybranego folderu zdjęć E1", "Załaduj najpierw wybrany folder zdjęć E1.")
                return
            existing_images = [
                image_path for image_path in target_iter_dir.iterdir()
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ]
            if not existing_images:
                messagebox.showwarning("Brak wybranego folderu zdjęć E1", "Załaduj najpierw wybrany folder zdjęć E1.")
                return
            if CAMPAIGN.get_step1_status() != "approved":
                should_approve = self.app.themed_confirm(
                    "Zatwierdzenie E1",
                    (
                        f"Folder iteracji zawiera już {len(existing_images)} obrazów:\n{target_iter_dir}\n\n"
                        "Czy zatwierdzić ten zestaw zdjęć jako E1 i odblokować E2?"
                    ),
                    parent=self.frame,
                    confirm_label="Zatwierdź",
                    tone="info",
                )
                if not should_approve:
                    return
                self._approve_current_iteration_package(
                    target_iter_dir=target_iter_dir,
                    selection_mode="existing",
                )
            return

        selected_items = list(self.current_ingest_plan.get("selected", []) or [])
        if not selected_items:
            messagebox.showwarning("Brak wybranego folderu zdjęć E1", "Załaduj najpierw wybrany folder zdjęć E1.")
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        if raw_dir is None:
            logger.error("Brak katalogu raw dla aktywnego projektu.")
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        target_iter_dir = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
        target_iter_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        copied_source_files = []
        for item in selected_items:
            source_path = Path(str(item.get("source_path", "") or "").strip())
            if not source_path.exists() or not source_path.is_file():
                continue

            dst = target_iter_dir / source_path.name
            if dst.exists():
                continue

            shutil.copy2(source_path, dst)
            copied += 1
            copied_source_files.append(source_path)

        if copied == 0:
            existing_images = [
                image_path for image_path in target_iter_dir.iterdir()
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            ]
            if existing_images:
                if CAMPAIGN.get_step1_status() != "approved":
                    should_approve = self.app.themed_confirm(
                        "Zatwierdzenie E1",
                        (
                            f"Folder iteracji zawiera już {len(existing_images)} obrazów:\n{target_iter_dir}\n\n"
                            "Czy zatwierdzić ten zestaw zdjęć jako E1 i odblokować E2?"
                        ),
                        parent=self.frame,
                        confirm_label="Zatwierdź",
                        tone="info",
                    )
                    if not should_approve:
                        return
                    self._approve_current_iteration_package(
                        target_iter_dir=target_iter_dir,
                        selection_mode="existing",
                    )
                else:
                    if CAMPAIGN.get_current_step() < 2:
                        CAMPAIGN.set_current_step(2)
                    self.current_ingest_plan = {}
                    self._refresh_dashboard()
                try:
                    self.app.update_status(
                        f"Iteracja {iter_num:03d} zawiera już zestaw zdjęć wejściowych. Krok 2 pozostaje odblokowany.",
                        "info",
                    )
                except Exception:
                    pass
                messagebox.showinfo(
                    "Zestaw zdjęć wejściowych już gotowy",
                    f"Folder iteracji zawiera już {len(existing_images)} obrazów:\n{target_iter_dir}\n\n"
                    "Nie kopiowano nowych plików, ale krok 1 został uznany za domknięty.",
                )
                return
            messagebox.showwarning(
                "Brak nowych plików",
                "Żadne nowe zdjęcia nie zostały skopiowane do iteracji.\n\n"
                "Być może zestaw zdjęć został już wcześniej zatwierdzony.",
            )
            return

        self._approve_current_iteration_package(
            target_iter_dir=target_iter_dir,
            source_dir=CAMPAIGN.get_master_pool_dir() or target_iter_dir,
            selected_source_files=copied_source_files,
            selection_mode="planned",
            proposal_summary={
                "planner_version": self.current_ingest_plan.get("planner_version", ""),
                "generated_at": self.current_ingest_plan.get("generated_at", ""),
                "source_total": self.current_ingest_plan.get("raw_total", 0),
                "selected_total": self.current_ingest_plan.get("selected_total", 0),
                "current_iteration_package_count": self.current_ingest_plan.get("selected_total", 0),
                "batch_size": self.current_ingest_plan.get("batch_size", 0),
                "skipped_duplicate_filenames": self.current_ingest_plan.get("skipped_duplicate_filenames", self.current_ingest_plan.get("skipped_used", 0)),
                "skipped_duplicate_approved_filenames": self.current_ingest_plan.get("skipped_duplicate_approved_filenames", 0),
                "project_overlap_filenames": self.current_ingest_plan.get("project_overlap_filenames", 0),
                "new_to_project_count": self.current_ingest_plan.get("new_to_project_total", 0),
                "skipped_invalid_ground_truth": self.current_ingest_plan.get("skipped_invalid_ground_truth", 0),
            },
        )

        try:
            self.app.update_status(
                f"Skopiowano {copied} zdjęć z wybranego folderu zdjęć do Iteracji {iter_num:03d}. Odblokowano Krok 2.",
                "info",
            )
        except Exception:
            pass

        messagebox.showinfo(
            "Przygotowanie zestawu zdjęć zakończone",
            f"Skopiowano {copied} zdjęć do:\n{target_iter_dir}\n\n"
            "Zestaw zdjęć zapisano jako zaakceptowaną porcję danych tej iteracji.",
        )

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        bg = palette.get("bg", "#1e1e1e")
        panel = palette.get("panel", "#252526")
        panel_alt = palette.get("surface_info", palette.get("panel_alt", panel))
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")

        try:
            self.app.style_panel_surface(self.frame, background=panel)
        except Exception:
            pass

        try:
            if getattr(self, "header_frame", None) is not None:
                self.header_frame.config(bg=panel)
            if getattr(self, "proj_frame", None) is not None:
                self.proj_frame.config(bg=panel)
            if self.banner_top_row is not None:
                self.banner_top_row.config(bg=str(self.lbl_campaign_banner.cget("bg") or panel_alt))
        except Exception:
            pass

        try:
            self.lbl_title.config(bg=panel, fg=fg)
        except Exception:
            pass

        try:
            self.lbl_iter.config(
                bg=panel,
                fg=str(self.lbl_iter.cget("fg") or palette.get("warning", "#ffb3b3")),
            )
        except Exception:
            pass

        try:
            self._configure_campaign_banner(
                text=str(self.lbl_campaign_banner.cget("text") or ""),
                fg=str(self.lbl_campaign_banner.cget("fg") or fg),
                bg=str(self.lbl_campaign_banner.cget("bg") or panel_alt),
            )
        except Exception:
            pass

        try:
            if self.wizard_header_title_lbl is not None:
                self.wizard_header_title_lbl.config(bg=panel, fg=fg)
        except Exception:
            pass

        try:
            if self.wizard_header_summary_lbl is not None:
                self.wizard_header_summary_lbl.config(bg=panel, fg=muted)
        except Exception:
            pass

        try:
            self.left_panel_hint_lbl.config(bg=panel, fg=muted)
        except Exception:
            pass

        try:
            if getattr(self, "left_panel_canvas", None) is not None:
                self.left_panel_canvas.config(bg=panel)
        except Exception:
            pass

        try:
            if getattr(self, "right_panel_canvas", None) is not None:
                self.right_panel_canvas.config(bg=panel)
        except Exception:
            pass

        try:
            if self.project_list_status_lbl is not None:
                self.project_list_status_lbl.config(bg=panel)
            if self.project_status_top_row is not None:
                self.project_status_top_row.config(bg=panel)
            for lbl in getattr(self, "project_list_status_labels", []):
                lbl.config(bg=panel, fg=muted)
        except Exception:
            pass

        try:
            if self.project_list_host is not None:
                self.project_list_host.config(
                    bg=palette.get("field", "#1a1a1a"),
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        try:
            if self.project_listbox is not None:
                self.project_listbox.config(
                    bg=palette.get("field", "#1a1a1a"),
                    fg=fg,
                    selectbackground=palette.get("accent", "#2980b9"),
                    selectforeground="#ffffff",
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("accent", "#2980b9"),
                )
        except Exception:
            pass

        try:
            if self.project_browser_footer is not None:
                self.project_browser_footer.config(bg=panel)
            if self.project_add_button_canvas is not None:
                self.project_add_button_canvas.config(bg=panel)
            if self.wizard_exit_button_canvas is not None:
                self.wizard_exit_button_canvas.config(bg=str(self.lbl_campaign_banner.cget("bg") or panel_alt))
        except Exception:
            pass

        for widget_name in (
            "ingest_header_lbl",
            "ingest_intro_lbl",
            "lbl_ingest_master_title",
            "lbl_ingest_master_value",
            "lbl_ingest_batch_title",
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget.config(bg=panel)
            except Exception:
                pass
        self._theme_step1_ingest_panel()
        self._draw_wizard_stage_metro()
        self._draw_icon_button("project_add")
        self._draw_icon_button("exit_project")

        try:
            if self.ingest_plan_host is not None:
                self.ingest_plan_host.config(
                    bg=palette.get("field", "#1a1a1a"),
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        try:
            if self.ingest_plan_listbox is not None:
                self.ingest_plan_listbox.config(
                    bg=palette.get("field", "#1a1a1a"),
                    fg=fg,
                    selectbackground=palette.get("accent", "#2980b9"),
                    selectforeground="#ffffff",
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("accent", "#2980b9"),
                )
        except Exception:
            pass

        for lbl in getattr(self, "_model_status_title_labels", []):
            try:
                lbl.config(bg=panel, fg=fg)
            except Exception:
                pass

        for model_type in ("vehicle", "plate", "char"):
            lbl_val = getattr(self, f"lbl_model_{model_type}", None)
            if lbl_val is not None:
                try:
                    lbl_val.config(bg=panel)
                except Exception:
                    pass
            lbl_meta = getattr(self, f"lbl_model_{model_type}_meta", None)
            if lbl_meta is not None:
                try:
                    lbl_meta.config(bg=panel, fg=palette.get("muted", "#b0b0b0"))
                except Exception:
                    pass

        for item in getattr(self, "roadmap_ui_elements", []):
            self._set_roadmap_card_border(item)
            try:
                item["lbl_title"].config(
                    bg=item["content_frame"].cget("bg"),
                    fg=fg
                )
            except Exception:
                pass
            try:
                item["lbl_desc"].config(
                    bg=item["content_frame"].cget("bg"),
                    fg=muted
                )
            except Exception:
                pass

        try:
            self._refresh_dashboard()
        except Exception:
            pass

    def _ask_project_from_list(self, title="Wybierz projekt", action_label="OK"):
        """Wyświetla modalny wybór projektu i zwraca nazwę albo None."""
        projects = CAMPAIGN.get_all_projects()
        if not projects:
            self.app.themed_info("Brak projektów", "Nie ma żadnych zapisanych projektów.", parent=self.frame)
            return None

        dialog = tk.Toplevel(self.frame)
        self.app.style_dialog_window(dialog, title=title, geometry="460x300", parent=self.frame)
        palette = self.app.palette

        shell = tk.Frame(
            dialog,
            bg=palette["bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"])
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        body = tk.Frame(shell, bg=palette["panel"])
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text=title,
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 11, "bold")
        ).pack(anchor=tk.W, padx=16, pady=(16, 8))

        tk.Label(
            body,
            text="Wybierz projekt z listy:",
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 10)
        ).pack(anchor=tk.W, padx=16, pady=(0, 6))

        list_frame = tk.Frame(body, bg=palette["panel"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        scroll = WebSlimScrollbar(list_frame, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        project_list = tk.Listbox(
            list_frame,
            exportselection=False,
            font=("Segoe UI", 10),
            bg=palette["field"],
            fg=palette["fg"],
            selectbackground=palette["accent"],
            selectforeground="#ffffff",
            activestyle="none",
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"]),
            yscrollcommand=scroll.set,
        )
        project_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=project_list.yview)

        for project in projects:
            project_list.insert(tk.END, project)
        project_list.selection_set(0)
        project_list.activate(0)
        project_list.focus_set()

        result = {"value": None}

        btn_row = tk.Frame(body, bg=palette["panel"])
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 16))

        def accept():
            selection = project_list.curselection()
            if selection:
                result["value"] = project_list.get(selection[0]).strip()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        ttk.Button(btn_row, text=action_label, command=accept, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Anuluj", command=cancel).pack(side=tk.RIGHT, padx=(0, 8))

        project_list.bind("<Double-Button-1>", lambda _e: accept())
        fit_dialog = getattr(self.app, "_fit_dialog_to_content", None)
        if callable(fit_dialog):
            fit_dialog(dialog, parent=self.frame, min_width=460, min_height=300)
        dialog.bind("<Return>", lambda _e: accept())
        dialog.bind("<Escape>", lambda _e: cancel())
        dialog.wait_window()
        return result["value"]

    def _ask_iteration_advance_mode(self):
        dialog = tk.Toplevel(self.frame)
        self.app.style_dialog_window(dialog, title="Nowa iteracja", geometry="620x320", parent=self.frame)
        palette = self.app.palette

        shell = tk.Frame(
            dialog,
            bg=palette["bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"])
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        body = tk.Frame(shell, bg=palette["panel"])
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Jak rozpocząć kolejną iterację?",
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 11, "bold")
        ).pack(anchor=tk.W, padx=16, pady=(16, 6))

        tk.Label(
            body,
            text=(
                "W obu wariantach aktywne modele zapisane w projekcie pozostają dostępne. "
                "Wybierasz tylko, czy kolejna iteracja ma ruszyć na tym samym zestawie zdjęć, "
                "czy od nowego zestawu wejściowego."
            ),
            bg=palette["panel"],
            fg=palette.get("muted", palette["fg"]),
            font=("Segoe UI", 10),
            justify=tk.LEFT,
            wraplength=560
        ).pack(anchor=tk.W, padx=16, pady=(0, 12))

        result = {"value": None}

        def choose(mode: str):
            result["value"] = mode
            dialog.destroy()

        def cancel():
            dialog.destroy()

        options_host = tk.Frame(body, bg=palette["panel"])
        options_host.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        def add_option(title: str, description: str, button_text: str, mode: str, accent: bool = False):
            card = tk.Frame(
                options_host,
                bg=palette["field"],
                bd=0,
                highlightthickness=1,
                highlightbackground=palette.get("panel_border", palette["border"]),
                highlightcolor=palette.get("panel_border", palette["border"])
            )
            card.pack(fill=tk.X, pady=(0, 10))

            text_col = tk.Frame(card, bg=palette["field"])
            text_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=14, pady=12)

            tk.Label(
                text_col,
                text=title,
                bg=palette["field"],
                fg=palette["fg"],
                font=("Segoe UI", 10, "bold"),
                justify=tk.LEFT,
                anchor=tk.W
            ).pack(anchor=tk.W)

            tk.Label(
                text_col,
                text=description,
                bg=palette["field"],
                fg=palette.get("muted", palette["fg"]),
                font=("Segoe UI", 9),
                justify=tk.LEFT,
                anchor=tk.W,
                wraplength=390
            ).pack(anchor=tk.W, pady=(4, 0))

            button_style = "Accent.TButton" if accent else "TButton"
            ttk.Button(
                card,
                text=button_text,
                command=lambda: choose(mode),
                style=button_style
            ).pack(side=tk.RIGHT, padx=14, pady=14)

        add_option(
            title="Ta sama pula zdjęć",
            description=(
                "System przygotuje kolejną paczkę z tej samej puli zdjęć projektu, "
                "pomijając obrazy już zatwierdzone w projekcie. "
                "Potem od razu wrócisz do wyboru toru w E2. "
                "Aktywne modele projektu pozostaną dostępne do dalszej pracy."
            ),
            button_text="Ta sama pula -> E2",
            mode="reuse_input",
            accent=True,
        )
        add_option(
            title="Nowy zestaw zdjęć",
            description=(
                "Nowa iteracja zacznie się od E1, aby wskazać całkiem nowy "
                "zestaw zdjęć wejściowych. "
                "Aktywne modele projektu nadal pozostaną dostępne w kolejnych etapach."
            ),
            button_text="Nowy zestaw -> E1",
            mode="new_input",
        )

        btn_row = tk.Frame(body, bg=palette["panel"])
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 16))
        ttk.Button(btn_row, text="Anuluj", command=cancel).pack(side=tk.RIGHT)

        fit_dialog = getattr(self.app, "_fit_dialog_to_content", None)
        if callable(fit_dialog):
            fit_dialog(dialog, parent=self.frame, min_width=620, min_height=320)
        dialog.bind("<Escape>", lambda _e: cancel())
        dialog.wait_window()
        return result["value"]

    def _set_model(self, model_type):
        # Otwórz wybór modelu od katalogu modeli aktywnego projektu.
        initial_dir = CAMPAIGN.get_dir("models")
        if initial_dir is None:
            initial_dir = Path(CONFIG.DIR_6_MODELS)
        else:
            initial_dir = Path(initial_dir)

        p = filedialog.askopenfilename(
            initialdir=str(initial_dir),
            filetypes=[("YOLO Model", "*.pt")]
        )
        if p:
            model_path = Path(p)
            is_valid, error_message = self._validate_project_model_selection(model_type, model_path)
            if not is_valid:
                self.app.themed_error(
                    "Nieprawidlowy model",
                    error_message,
                    parent=self.frame,
                )
                return
            CAMPAIGN.set_global_model(model_type, str(model_path))
            self._refresh_dashboard()

    # ======================================================
    # ROADMAP UI
    # ======================================================

    def _set_roadmap_note(self, item, text="", tone="muted"):
        palette = getattr(self.app, "palette", {})
        lbl_desc = item.get("lbl_desc")
        if lbl_desc is None:
            return
        card_bg = palette.get("panel", "#252526")
        try:
            card_bg = str(item.get("content_frame").cget("bg") or card_bg)
        except Exception:
            pass

        note_text = (text or "").strip()
        tone_key = str(tone or "muted").strip().lower()
        note_color = {
            "muted": palette.get("muted", "#c7c7c7"),
            "info": palette.get("accent", "#2980b9"),
            "success": palette.get("success", "#27ae60"),
            "warning": palette.get("warning", "#d35400"),
            "error": palette.get("error", "#c0392b"),
        }.get(tone_key, palette.get("muted", "#c7c7c7"))

        try:
            lbl_desc.config(
                text=note_text,
                fg=note_color,
                bg=card_bg,
                anchor="w",
                bd=0,
                highlightthickness=0,
                relief=tk.FLAT,
            )
        except Exception:
            return

        if note_text:
            if not item.get("note_visible"):
                lbl_desc.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))
                item["note_visible"] = True
        else:
            if item.get("note_visible"):
                lbl_desc.pack_forget()
            item["note_visible"] = False

    def _get_roadmap_neutral_border_color(self):
        palette = getattr(self.app, "palette", {})
        theme_key = str(getattr(self.app, "current_theme_key", "") or "").lower()
        if theme_key.startswith("dark"):
            return palette.get("button_hover", palette.get("panel_alt", palette.get("panel_border", palette.get("border", "#3c3c3c"))))
        return palette.get("panel_border", palette.get("border", "#c8c8c8"))

    def _set_roadmap_card_border(self, item, color=None):
        palette = getattr(self.app, "palette", {})
        shell = item.get("shell")
        if shell is None:
            return

        card_bg = palette.get("panel", "#252526")
        border_color = color or self._get_roadmap_neutral_border_color()
        try:
            shell.config(
                bg=border_color,
                highlightthickness=0
            )
        except Exception:
            pass
        for key in ("content_frame", "frame", "text_frame", "extra_actions_frame"):
            widget = item.get(key)
            if widget is None:
                continue
            try:
                widget.config(bg=card_bg)
            except Exception:
                pass

    def _get_roadmap_item(self, step_num: int):
        for item in self.roadmap_ui_elements:
            if int(item.get("step_num", 0) or 0) == int(step_num):
                return item
        return None

    def _toggle_step1_panel(self):
        if not CAMPAIGN.get_active_project_name():
            return
        if CAMPAIGN.get_current_step() != 1:
            return

        self.step1_panel_expanded = not bool(self.step1_panel_expanded)
        self._rebuild_roadmap_ui()
        self._refresh_dashboard()

    def _build_roadmap_step(self, parent, step_num, title, desc, btn_text, command):
        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        neutral_border = self._get_roadmap_neutral_border_color()

        shell = tk.Frame(
            parent,
            bg=neutral_border,
            bd=0,
            highlightthickness=0
        )
        shell.pack(fill=tk.X, pady=(0, 6))

        content = tk.Frame(
            shell,
            bg=card_bg,
            padx=10,
            pady=8
        )
        content.pack(fill=tk.X, padx=1, pady=1)

        main_row = tk.Frame(content, bg=card_bg)
        main_row.pack(fill=tk.X)

        text_f = tk.Frame(main_row, bg=card_bg)
        text_f.pack(side=tk.LEFT, fill=tk.X, expand=True)

        lbl_title = tk.Label(
            text_f,
            text=title,
            font=("Segoe UI", 12, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=card_bg
        )
        lbl_title.pack(anchor=tk.W)

        lbl_desc = tk.Label(
            text_f,
            text="",
            fg=palette.get("muted", "#b8b8b8"),
            bg=card_bg,
            anchor="w",
            justify=tk.LEFT,
            wraplength=520
        )

        btn = ttk.Button(main_row, text=btn_text, command=command, width=25)
        btn.pack(side=tk.RIGHT, padx=(10, 0))

        # Kontener na dodatkowe akcje naprawcze kroku.
        extra_actions_frame = tk.Frame(content, bg=card_bg)

        self.roadmap_ui_elements.append({
            "step_num": step_num,
            "frame": main_row,
            "shell": shell,
            "content_frame": content,
            "text_frame": text_f,
            "original_title": title,
            "default_desc": desc,
            "orig_btn_text": btn_text,
            "lbl_title": lbl_title,
            "lbl_desc": lbl_desc,
            "btn": btn,
            "extra_actions_frame": extra_actions_frame,
            "note_visible": False
        })

    def _rebuild_roadmap_ui(self):
        roadmap_parent = self.right_content if self.right_content is not None else self.right_panel
        for widget in roadmap_parent.winfo_children():
            widget.destroy()
        self.roadmap_ui_elements = []
        self.step1_roadmap_item = None
        self.wizard_stage_cards = {}

        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")

        header_shell = tk.Frame(roadmap_parent, bg=panel_bg, bd=0, highlightthickness=0)
        header_shell.pack(fill=tk.X, pady=(0, 8))
        self.wizard_header_title_lbl = tk.Label(
            header_shell,
            text="Etapy projektu",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 13, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=panel_bg,
        )
        self.wizard_header_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.wizard_header_summary_lbl = tk.Label(
            header_shell,
            text="Stan projektu i kolejny krok.",
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
            fg=palette.get("muted", "#c7c7c7"),
            bg=panel_bg,
        )
        self.wizard_header_summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))

        self.wizard_empty_state_card = self._build_wizard_stage_card(
            roadmap_parent,
            "empty",
            help_key="camp_open_project",
        )
        self.wizard_stage_cards_host = tk.Frame(roadmap_parent, bg=panel_bg, bd=0, highlightthickness=0)
        self.wizard_stage_cards_host.pack(fill=tk.X)

        for key, help_key in (
            ("step1", "camp_step1"),
            ("step2", "camp_step2"),
            ("step3", "camp_step3"),
            ("step4", "camp_advance"),
        ):
            self.wizard_stage_cards[key] = self._build_wizard_stage_card(
                self.wizard_stage_cards_host,
                key,
                help_key=help_key,
            )

        self.step1_roadmap_item = {
            "step_num": 1,
            "extra_actions_frame": self.wizard_stage_cards["step1"]["body"],
        }
        try:
            self._build_ingest_panel(self.wizard_stage_cards["step1"]["body"])
        except Exception as e:
            logger.debug(f"Nie udało się zbudować panelu E1 w nowym wizardzie: {e}")

        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self.frame.after_idle(self._sync_right_panel_canvas_width)
        return

        self._build_roadmap_step(
            roadmap_parent, 1,
            "E1. Wybrany folder zdjęć",
            "E1. Wczytujesz pełną główną pulę zdjęć jako wybrany folder zdjęć i zatwierdzasz zestaw zdjęć wejściowych iteracji.",
            "Pokaż panel E1",
            self._toggle_step1_panel
        )

        self._build_roadmap_step(
            roadmap_parent, 2,
            "E2. Wybierz ścieżkę iteracji",
            "E2. Wizard przygotowuję tablice dla wybranego toru: prowadzi przez Z2 albo, gdy masz już dobre ręczne tablice dla tej paczki, pomija Z2 i przechodzi dalej do Z3.",
            "Skocz: Autoanotacja",
            self._step_goto_auto_annotation
        )

        self._build_roadmap_step(
            roadmap_parent, 3,
            "E3. Tor znaków",
            "E3. Wizard przechodzi do Z3, gdzie wycinasz tablice, uruchamiasz OCR, porównujesz wynik z ground truth i budujesz gold pack.",
            "Skocz: Znaki",
            self._step_goto_characters
        )

        self._build_roadmap_step(
            roadmap_parent, 4,
            "E4. Trening wybranego toru",
            "E4. Wizard przechodzi do Z4, gdzie wybierasz tor, przygotowujesz dataset iteracji i uruchamiasz trening oraz analizę modelu.",
            "Skocz: Trening",
            self._step_goto_training
        )

        self.step1_roadmap_item = self._get_roadmap_item(1)
        if self.step1_roadmap_item is not None:
            try:
                self._build_ingest_panel(self.step1_roadmap_item["extra_actions_frame"])
            except Exception as e:
                logger.debug(f"Nie udało się zbudować panelu E1 w roadmapie: {e}")

        for item in self.roadmap_ui_elements:
            help_key = f"camp_step{item['step_num']}"
            for widget in (
                item.get("shell"),
                item.get("content_frame"),
                item.get("frame"),
                item.get("lbl_title"),
                item.get("lbl_desc"),
                item.get("btn"),
                item.get("extra_actions_frame"),
            ):
                HELP.bind_help(widget, help_key)

        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self.frame.after_idle(self._sync_right_panel_canvas_width)

    def _set_pack_visibility(self, widget, visible: bool, **pack_kwargs):
        if widget is None:
            return
        try:
            manager = str(widget.winfo_manager())
        except Exception:
            manager = ""

        if visible:
            if manager != "pack":
                try:
                    widget.pack(**pack_kwargs)
                except Exception:
                    pass
            return

        if manager == "pack":
            try:
                widget.pack_forget()
            except Exception:
                pass

    def _set_grid_visibility(self, widget, visible: bool):
        if widget is None:
            return
        try:
            manager = str(widget.winfo_manager())
        except Exception:
            manager = ""

        if visible:
            if manager != "grid":
                try:
                    widget.grid()
                except Exception:
                    pass
            return

        if manager == "grid":
            try:
                widget.grid_remove()
            except Exception:
                pass

    def _cancel_wizard_stage_curtain_animation(self, card: dict):
        if not isinstance(card, dict):
            return
        pending = card.get("curtain_after_id")
        if not pending:
            return
        try:
            self.frame.after_cancel(pending)
        except Exception:
            pass
        card["curtain_after_id"] = None

    def _set_wizard_stage_curtain_height(self, card: dict, height: int):
        if not isinstance(card, dict):
            return
        clip = card.get("curtain_clip")
        toggle = card.get("curtain_toggle")
        if clip is None:
            return
        normalized_height = max(0, int(height))
        try:
            manager = str(clip.winfo_manager())
        except Exception:
            manager = ""
        if normalized_height <= 0:
            if manager == "pack":
                try:
                    clip.pack_forget()
                except Exception:
                    pass
        elif manager != "pack":
            try:
                clip.pack(fill=tk.X, pady=(0, 0), after=toggle)
            except Exception:
                pass
        try:
            clip.configure(height=normalized_height)
        except Exception:
            pass
        try:
            if normalized_height > 0:
                clip.pack_configure(pady=(6, 0))
        except Exception:
            pass
        try:
            self.frame.after_idle(self._sync_right_panel_scrollregion)
        except Exception:
            pass

    def _animate_wizard_stage_curtain(self, card: dict, expand: bool):
        if not isinstance(card, dict):
            return

        clip = card.get("curtain_clip")
        inner = card.get("curtain_inner")
        shell = card.get("curtain_shell")
        action_row = card.get("action_row")
        if clip is None or inner is None or shell is None:
            return

        self._cancel_wizard_stage_curtain_animation(card)
        self._set_pack_visibility(shell, True, fill=tk.X, pady=(10, 0), before=action_row)
        if expand:
            try:
                if str(clip.winfo_manager()) != "pack":
                    clip.pack(fill=tk.X, pady=(0, 0), after=card.get("curtain_toggle"))
            except Exception:
                pass

        try:
            inner.update_idletasks()
            clip.update_idletasks()
        except Exception:
            pass

        start_height = 0
        try:
            start_height = int(clip.cget("height") or 0)
        except Exception:
            try:
                start_height = int(clip.winfo_height() or 0)
            except Exception:
                start_height = 0

        target_height = 0
        if expand:
            try:
                target_height = max(0, int(inner.winfo_reqheight() or 0))
            except Exception:
                target_height = 0

        if start_height == target_height:
            self._set_wizard_stage_curtain_height(card, target_height)
            card["curtain_expanded"] = bool(expand)
            return

        total_steps = 10
        interval_ms = 18
        delta = target_height - start_height

        def _tick(step_index: int = 0):
            ratio = float(step_index + 1) / float(total_steps)
            eased = ratio * ratio * (3.0 - (2.0 * ratio))
            current_height = int(round(start_height + (delta * eased)))
            self._set_wizard_stage_curtain_height(card, current_height)
            if (step_index + 1) < total_steps:
                try:
                    card["curtain_after_id"] = self.frame.after(interval_ms, lambda: _tick(step_index + 1))
                except Exception:
                    card["curtain_after_id"] = None
            else:
                card["curtain_after_id"] = None
                self._set_wizard_stage_curtain_height(card, target_height)
                card["curtain_expanded"] = bool(expand)

        _tick(0)

    def _toggle_wizard_stage_curtain(self, stage_key: str):
        card = self.wizard_stage_cards.get(str(stage_key or "").strip())
        if not isinstance(card, dict):
            return "break"
        if not bool(card.get("curtain_visible", False)):
            return "break"

        card["curtain_user_touched"] = True
        expand = not bool(card.get("curtain_expanded", False))
        card["curtain_expanded"] = expand
        self._refresh_wizard_stage_curtain_style(card)
        self._animate_wizard_stage_curtain(card, expand)
        return "break"

    def _collapse_wizard_stage_curtain(self, stage_key: str, *, reset_user_touched: bool = True):
        card = self.wizard_stage_cards.get(str(stage_key or "").strip())
        if not isinstance(card, dict):
            return

        card["curtain_expanded"] = False
        if reset_user_touched:
            card["curtain_user_touched"] = False

        self._cancel_wizard_stage_curtain_animation(card)
        self._set_wizard_stage_curtain_height(card, 0)
        self._refresh_wizard_stage_curtain_style(card)

    def _collapse_all_wizard_stage_curtains(self, *, reset_user_touched: bool = True):
        for stage_key in list(getattr(self, "wizard_stage_cards", {}).keys()):
            try:
                self._collapse_wizard_stage_curtain(stage_key, reset_user_touched=reset_user_touched)
            except Exception:
                pass

    def _refresh_wizard_stage_curtain_style(self, card: dict):
        if not isinstance(card, dict):
            return

        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        muted = palette.get("muted", "#c7c7c7")
        fg = palette.get("fg", "#f3f3f3")
        border = str(card.get("curtain_border", "") or palette.get("panel_border", palette.get("border", "#3c3c3c")))
        surface = str(card.get("curtain_surface", "") or palette.get("panel_alt", card_bg))
        expanded = bool(card.get("curtain_expanded", False))
        indicator_text = "▾" if expanded else "▸"

        for widget_name in ("curtain_shell", "curtain_clip", "curtain_inner"):
            widget = card.get(widget_name)
            if widget is None:
                continue
            try:
                widget.configure(bg=card_bg)
            except Exception:
                pass

        toggle = card.get("curtain_toggle")
        if toggle is not None:
            try:
                toggle.configure(
                    bg=surface,
                    highlightbackground=border,
                    highlightcolor=border,
                )
            except Exception:
                pass

        for widget_name in ("curtain_text_col", "curtain_table"):
            widget = card.get(widget_name)
            if widget is None:
                continue
            try:
                widget.configure(bg=surface, highlightbackground=border, highlightcolor=border)
            except Exception:
                pass

        indicator = card.get("curtain_indicator")
        if indicator is not None:
            try:
                indicator.configure(text=indicator_text, bg=surface, fg=border)
            except Exception:
                pass

        title = card.get("curtain_title")
        if title is not None:
            try:
                title.configure(bg=surface, fg=fg)
            except Exception:
                pass

        meta = card.get("curtain_meta")
        if meta is not None:
            try:
                meta.configure(bg=surface, fg=muted)
            except Exception:
                pass

    def _format_campaign_summary_path(self, path_like, *, fallback: str = "—", max_len: int = 78) -> str:
        raw = str(path_like or "").strip()
        if not raw:
            return fallback

        try:
            candidate = Path(raw).expanduser()
        except Exception:
            return shorten(raw, width=max(12, int(max_len)), placeholder="…")

        display = str(candidate)
        try:
            candidate_resolved = candidate.resolve()
        except Exception:
            candidate_resolved = candidate

        project_root = None
        try:
            project_root = CAMPAIGN.get_active_project_root_dir()
        except Exception:
            project_root = None

        for base in (
            project_root,
            Path(CONFIG.WORKSPACE_DIR),
        ):
            if base is None:
                continue
            try:
                display = str(candidate_resolved.relative_to(Path(base).resolve()))
                break
            except Exception:
                continue

        display = str(display).replace("\\", "/")
        return shorten(display, width=max(16, int(max_len)), placeholder="…")

    @staticmethod
    def _format_step1_selection_mode_label(selection_mode: str) -> str:
        normalized = str(selection_mode or "").strip().lower()
        labels = {
            "planned": "Wybrano paczkę z głównego katalogu zdjęć",
            "manual": "Wskazano paczkę ręcznie",
            "existing": "Użyto gotowego katalogu iteracji",
            "iteration_reuse": "Użyto tego samego zestawu zdjęć co poprzednio",
            "pool_reuse": "Przygotowano kolejną paczkę z tej samej puli projektu",
            "stage_reuse": "Przejęto zdjęcia oczekujące w stage po poprzedniej iteracji",
        }
        return labels.get(normalized, "Tryb przygotowania nie jest jeszcze znany")

    @staticmethod
    def _format_effective_stage_reuse_label(base_count: int, manual_reuse_count: int) -> str:
        return f"Ta sama paczka pracy: stage ({int(base_count)}) + wcześniejsze ręczne korekty ({int(manual_reuse_count)})"

    @staticmethod
    def _load_plate_annotated_filenames_from_xml(xml_path: Path | None) -> set[str]:
        if xml_path is None or not xml_path.exists():
            return set()
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception:
            return set()

        filenames: set[str] = set()
        for image_el in root.findall(".//image"):
            filename = str(image_el.get("name", "") or "").strip()
            if not filename:
                continue
            has_plate = False
            for poly_el in image_el.findall("polygon"):
                label = str(poly_el.get("label", "") or "").strip().lower()
                if label in CONFIG.PLATE_LABELS:
                    has_plate = True
                    break
            if not has_plate:
                for box_el in image_el.findall("box"):
                    label = str(box_el.get("label", "") or "").strip().lower()
                    if label in CONFIG.PLATE_LABELS:
                        has_plate = True
                        break
            if has_plate:
                filenames.add(filename)
        return filenames

    def _get_effective_iteration_package_breakdown(self, manifest: dict | None = None) -> dict:
        iter_image_count = int(self._get_iteration_image_count() or 0)
        payload = {
            "base_count": iter_image_count,
            "manual_reuse_count": 0,
            "effective_total": iter_image_count,
            "source_label": "",
        }

        if not isinstance(manifest, dict):
            return payload

        manifest_mode = str(manifest.get("selection_mode", "") or "").strip().lower()
        if manifest_mode != "stage_reuse":
            return payload

        stored_manual_source = CAMPAIGN.get_last_plate_manual_source()
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)

        def _extract_iteration_num(raw_value: str) -> int:
            text = str(raw_value or "").strip()
            if not text:
                return 0
            try:
                candidate = Path(text)
                parts = list(candidate.parts)
            except Exception:
                parts = [text]
            for part in reversed(parts):
                stripped = str(part).strip()
                lowered = stripped.lower()
                if lowered.startswith("iteracja_"):
                    try:
                        return int(stripped.split("_", 1)[1])
                    except Exception:
                        return 0
            return 0

        source_label = ""
        source_iteration = 0
        for raw_path in (
            str(stored_manual_source.get("source_input_path") or "").strip(),
            str(stored_manual_source.get("source_run_path") or "").strip(),
            str(stored_manual_source.get("source_xml_path") or "").strip(),
        ):
            if not raw_path:
                continue
            try:
                candidate = Path(raw_path)
                parts = list(candidate.parts)
            except Exception:
                parts = [raw_path]
            for part in reversed(parts):
                lowered = str(part).strip().lower()
                if lowered.startswith("iteracja_"):
                    source_label = str(part)
                    source_iteration = _extract_iteration_num(source_label)
                    break
            if source_label:
                break

        if source_iteration <= 0 or source_iteration >= current_iteration:
            payload["source_label"] = source_label
            return payload

        xml_path = None
        for raw_xml in (
            str(stored_manual_source.get("source_xml_path") or "").strip(),
            str(stored_manual_source.get("source_run_path") or "").strip(),
        ):
            if not raw_xml:
                continue
            try:
                candidate = Path(raw_xml)
                if candidate.suffix.lower() == ".xml":
                    xml_candidate = candidate
                else:
                    xml_candidate = candidate / "annotations.xml"
            except Exception:
                continue
            if xml_candidate.exists():
                xml_path = xml_candidate
                break

        manual_filenames = self._load_plate_annotated_filenames_from_xml(xml_path)
        payload["manual_reuse_count"] = len(manual_filenames)
        payload["effective_total"] = int(payload["base_count"]) + int(payload["manual_reuse_count"])
        payload["source_label"] = source_label
        return payload

    def _get_step1_manifest_context(self, manifest: dict | None = None) -> dict:
        manifest = manifest if isinstance(manifest, dict) else {}
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
        iter_num = int(manifest.get("iteration", current_iteration) or current_iteration)
        manifest_mode = str(manifest.get("selection_mode", "") or "").strip().lower()
        selected_count = int(manifest.get("selected_count", 0) or 0)

        proposal_summary = manifest.get("proposal_summary", {})
        if not isinstance(proposal_summary, dict):
            proposal_summary = {}
        source_total = int(proposal_summary.get("source_total", 0) or 0)
        skipped_duplicate_filenames = int(proposal_summary.get("skipped_duplicate_filenames", 0) or 0)
        skipped_duplicate_approved = int(proposal_summary.get("skipped_duplicate_approved_filenames", 0) or 0)
        project_overlap_filenames = int(proposal_summary.get("project_overlap_filenames", 0) or 0)
        current_iteration_package_count = int(proposal_summary.get("current_iteration_package_count", selected_count) or selected_count)
        new_to_project_count = int(
            proposal_summary.get(
                "new_to_project_count",
                (
                    current_iteration_package_count
                    if manifest_mode in {"planned", "manual", "existing"}
                    else max(0, current_iteration_package_count - project_overlap_filenames)
                ),
            ) or 0
        )
        project_pool_total_before = int(proposal_summary.get("project_pool_total_before_iteration", 0) or 0)
        project_pool_total_after = int(proposal_summary.get("project_pool_total_after_iteration", 0) or 0)
        approved_images_before = int(proposal_summary.get("approved_images_before_iteration", 0) or 0)
        approved_plates_before = int(proposal_summary.get("approved_plates_before_iteration", 0) or 0)

        source_iteration = int(proposal_summary.get("source_iteration", 0) or 0)
        source_kind = str(proposal_summary.get("source_kind", "") or "").strip().lower()

        if source_iteration <= 0:
            source_dir = str(manifest.get("source_dir", "") or "").strip()
            for raw_part in reversed(str(source_dir).replace("\\", "/").split("/")):
                lowered = str(raw_part).strip().lower()
                if lowered.startswith("iteracja_"):
                    try:
                        source_iteration = int(str(raw_part).split("_", 1)[1])
                    except Exception:
                        source_iteration = 0
                    break

        source_label = f"Iteracja_{source_iteration:03d}" if source_iteration > 0 else ""

        approved_stats = {}
        try:
            approved_stats = CAMPAIGN.get_plate_approved_set_stats() or {}
        except Exception:
            approved_stats = {}
        if approved_images_before <= 0:
            approved_images_before = int(approved_stats.get("images", 0) or 0)
        if approved_plates_before <= 0:
            approved_plates_before = int(approved_stats.get("plates", 0) or 0)
        if project_pool_total_before <= 0:
            project_pool_total_before = approved_images_before
        if project_pool_total_after <= 0:
            project_pool_total_after = max(project_pool_total_before, approved_images_before) + new_to_project_count

        if manifest_mode == "stage_reuse":
            if source_label:
                source_summary = f"Stage po {source_label}"
            else:
                source_summary = "Stage po poprzedniej iteracji"
        elif manifest_mode == "pool_reuse":
            source_summary = "Ta sama pula projektu"
        elif manifest_mode == "iteration_reuse":
            source_summary = "Ten sam zestaw zdjęć co poprzednio"
        elif manifest_mode == "planned":
            source_summary = "Wybrana paczka z głównej puli projektu"
        elif manifest_mode == "manual":
            source_summary = "Ręcznie wskazana paczka wejściowa"
        elif manifest_mode == "existing":
            source_summary = "Gotowy katalog bieżącej iteracji"
        else:
            source_summary = "Źródło paczki nie jest jeszcze znane"

        return {
            "iteration": iter_num,
            "selection_mode": manifest_mode,
            "selected_count": selected_count,
            "source_kind": source_kind,
            "source_iteration": source_iteration,
            "source_label": source_label,
            "source_summary": source_summary,
            "source_total": source_total,
            "skipped_duplicate_filenames": skipped_duplicate_filenames,
            "skipped_duplicate_approved": skipped_duplicate_approved,
            "project_overlap_filenames": project_overlap_filenames,
            "project_pool_total": int(project_pool_total_after or 0),
            "project_pool_total_before": int(project_pool_total_before or 0),
            "project_pool_total_after": int(project_pool_total_after or 0),
            "current_iteration_package_count": int(current_iteration_package_count or selected_count or 0),
            "new_to_project_count": int(new_to_project_count or 0),
            "approved_images": approved_images_before,
            "approved_plates": approved_plates_before,
        }

    def _build_step1_summary_payload(self) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}

        manifest = self._load_ingest_manifest_cached()
        if not isinstance(manifest, dict) or not manifest:
            raw_dir = CAMPAIGN.get_dir("raw")
            if raw_dir is None:
                return {}
            iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
            target_dir = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
            if not target_dir.exists() or not target_dir.is_dir():
                return {}
            selected_count = sum(
                1
                for image_path in target_dir.iterdir()
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            )
            if selected_count <= 0:
                return {}
            manifest = {
                "iteration": iter_num,
                "selection_mode": "existing",
                "source_dir": str(target_dir),
                "target_dir": str(target_dir),
                "master_pool_dir": str(CAMPAIGN.get_master_pool_dir() or ""),
                "selected_count": selected_count,
                "selected_images": [],
                "char_histogram": {},
                "created_at": "",
                "proposal_summary": {},
            }

        selected_count = int(manifest.get("selected_count", 0) or 0)
        target_dir = str(manifest.get("target_dir", "") or "").strip()
        if selected_count <= 0 and not target_dir:
            return {}
        step1_context = self._get_step1_manifest_context(manifest)
        package_count = int(
            step1_context.get("current_iteration_package_count", 0)
            or self._get_iteration_image_count()
            or selected_count
            or 0
        )
        source_total = int(step1_context.get("source_total", 0) or 0)
        duplicate_count = int(step1_context.get("skipped_duplicate_filenames", 0) or 0)
        project_pool_total = int(step1_context.get("project_pool_total_after", step1_context.get("project_pool_total", 0)) or 0)
        approved_images = int(step1_context.get("approved_images", 0) or 0)
        new_to_project_count = int(step1_context.get("new_to_project_count", 0) or 0)
        source_summary = str(step1_context.get("source_summary", "") or "").strip()
        source_label = str(step1_context.get("source_label", "") or "").strip()
        if source_label and str(step1_context.get("selection_mode", "") or "").strip().lower() == "stage_reuse":
            source_summary = f"{source_summary} ({source_label})"

        manifest_mode = str(manifest.get("selection_mode", "") or "").strip().lower()
        current_iteration = int(manifest.get("iteration", CAMPAIGN.get_current_iteration_num()) or CAMPAIGN.get_current_iteration_num())
        total_pool_images = max(int(project_pool_total or 0), int(package_count or 0))
        previous_approved_images = max(0, int(approved_images or 0))
        current_iteration_package = int(package_count or 0)

        rows = [
            (
                "Łączna pula obrazów projektu",
                (
                    f"{total_pool_images} zdjęć = "
                    f"{previous_approved_images} zatwierdzonych do treningu YOLO + "
                    f"{current_iteration_package} do oznaczenia"
                ),
            ),
            ("Zatwierdzone w poprzednich iteracjach do treningu YOLO", f"{previous_approved_images} zdjęć"),
            ("Do oznaczenia w bieżącej iteracji", f"{current_iteration_package} zdjęć"),
        ]

        if manifest_mode == "stage_reuse" and current_iteration > 1:
            meta_text = f"Do bieżącej iteracji przejęto {current_iteration_package} zdjęć ze stage po poprzedniej iteracji."
        elif manifest_mode == "pool_reuse" and current_iteration > 1:
            meta_text = f"Do bieżącej iteracji przygotowano {current_iteration_package} zdjęć z tej samej puli projektu."
        elif source_total > 0:
            meta_parts = [f"Wybrana paczka źródłowa zawiera {source_total} zdjęć."]
            if new_to_project_count > 0:
                meta_parts.append(f"Do projektu dopisano {new_to_project_count} nowych.")
            meta_parts.append(f"W tej iteracji pracujesz na {current_iteration_package} zdjęciach.")
            if duplicate_count > 0:
                meta_parts.append(f"{duplicate_count} było już zatwierdzonych do treningu YOLO.")
            meta_text = " ".join(meta_parts).strip()
        else:
            meta_text = f"W tej iteracji pracujesz na {current_iteration_package} zdjęciach."

        return {
            "title": "Co wybrano w E1",
            "meta": meta_text,
            "rows": rows,
        }

    def _render_step1_stage_curtain(self, card: dict, status: WizardStageStatus, style: dict):
        if not isinstance(card, dict):
            return

        payload = {}
        state_key = str(getattr(status, "state", "") or "").strip().lower()
        if (
            str(getattr(status, "key", "") or "").strip() == "step1"
            and state_key in {"done", "needs_attention"}
        ):
            payload = self._build_step1_summary_payload()

        rows = list(payload.get("rows", []) or [])
        visible = bool(rows) and (bool(getattr(status, "is_current", False)) or state_key == "needs_attention")
        card["curtain_visible"] = visible

        shell = card.get("curtain_shell")
        clip = card.get("curtain_clip")
        inner = card.get("curtain_inner")
        table = card.get("curtain_table")
        action_row = card.get("action_row")
        content = card.get("content")
        if shell is None or clip is None or inner is None or table is None or content is None:
            return

        if not visible:
            card["curtain_expanded"] = False
            card["curtain_user_touched"] = False
            self._cancel_wizard_stage_curtain_animation(card)
            self._set_wizard_stage_curtain_height(card, 0)
            self._set_pack_visibility(shell, False)
            return

        if not bool(card.get("curtain_user_touched", False)):
            card["curtain_expanded"] = False

        border = str(style.get("border", "") or getattr(self.app, "palette", {}).get("panel_border", "#3c3c3c"))
        surface = blend_hex_colors(border, getattr(self.app, "palette", {}).get("panel", "#252526"), 0.92)
        card["curtain_border"] = border
        card["curtain_surface"] = surface

        title_lbl = card.get("curtain_title")
        meta_lbl = card.get("curtain_meta")
        if title_lbl is not None:
            try:
                title_lbl.configure(text=str(payload.get("title", "Podsumowanie etapu") or "Podsumowanie etapu"))
            except Exception:
                pass
        if meta_lbl is not None:
            try:
                meta_lbl.configure(text=str(payload.get("meta", "") or ""))
            except Exception:
                pass

        for child in list(table.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass

        palette = getattr(self.app, "palette", {})
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        panel_bg = palette.get("panel", "#252526")
        grid_border = blend_hex_colors(border, panel_bg, 0.34)
        header_bg = blend_hex_colors(surface, panel_bg, 0.18)

        try:
            table.grid_columnconfigure(0, weight=1)
        except Exception:
            pass

        table.grid_columnconfigure(1, weight=1)
        try:
            table.configure(
                bg=grid_border,
                highlightbackground=grid_border,
                highlightcolor=grid_border,
                highlightthickness=1,
            )
        except Exception:
            pass

        header_left = tk.Label(
            table,
            text="Pole",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 8, "bold"),
            fg=muted,
            bg=header_bg,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=grid_border,
            highlightcolor=grid_border,
            padx=10,
            pady=6,
        )
        header_left.grid(row=0, column=0, sticky="ew")

        header_right = tk.Label(
            table,
            text="Wartosc",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 8, "bold"),
            fg=muted,
            bg=header_bg,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground=grid_border,
            highlightcolor=grid_border,
            padx=10,
            pady=6,
        )
        header_right.grid(row=0, column=1, sticky="ew")

        for row_idx, (label_text, value_text) in enumerate(rows, start=1):
            row_bg = blend_hex_colors(surface, panel_bg, 0.10 if ((row_idx - 1) % 2 == 0) else 0.18)

            key_lbl = tk.Label(
                table,
                text=str(label_text or "").strip() or "-",
                anchor="nw",
                justify=tk.LEFT,
                width=18,
                font=("Segoe UI", 9, "bold"),
                fg=muted,
                bg=row_bg,
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground=grid_border,
                highlightcolor=grid_border,
                padx=10,
                pady=8,
            )
            key_lbl.grid(row=row_idx, column=0, sticky="nsew")

            val_lbl = tk.Label(
                table,
                text=str(value_text or "").strip() or "-",
                anchor="nw",
                justify=tk.LEFT,
                wraplength=560,
                fg=fg,
                bg=row_bg,
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground=grid_border,
                highlightcolor=grid_border,
                padx=10,
                pady=8,
            )
            val_lbl.grid(row=row_idx, column=1, sticky="nsew")

        self._set_pack_visibility(shell, True, fill=tk.X, pady=(10, 0), before=action_row)
        self._refresh_wizard_stage_curtain_style(card)
        try:
            inner.update_idletasks()
        except Exception:
            pass
        self._set_wizard_stage_curtain_height(
            card,
            int(inner.winfo_reqheight() or 0) if bool(card.get("curtain_expanded", False)) else 0,
        )

    def _refresh_wizard_stage_metro(self, statuses: list[WizardStageStatus] | None = None):
        filtered_statuses = []
        for key in ("step1", "step2", "step3", "step4"):
            matched = None
            if statuses:
                for status in statuses:
                    if getattr(status, "key", "") == key:
                        matched = status
                        break
            if matched is None:
                matched = WizardStageStatus(
                    key=key,
                    title="",
                    state="locked",
                    summary="",
                    details="",
                    is_current=False,
                )
            filtered_statuses.append(matched)

        self._wizard_header_metro_statuses = filtered_statuses
        self.frame.after_idle(self._draw_wizard_stage_metro)

    def _draw_wizard_stage_metro(self, _event=None):
        canvas = getattr(self, "wizard_header_metro_canvas", None)
        if canvas is None:
            return

        palette = getattr(self.app, "palette", {})
        panel_bg = str(canvas.cget("bg") or palette.get("panel", "#252526"))
        panel_alt = palette.get("panel_alt", "#2d2d30")
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")
        border = blend_hex_colors(
            palette.get("panel_border", palette.get("border", "#3c3c3c")),
            panel_bg,
            0.28,
        )
        accent = blend_hex_colors(
            palette.get("accent", "#2980b9"),
            palette.get("surface_info", "#213a4d"),
            0.24,
        )
        success = blend_hex_colors(
            palette.get("success", "#27ae60"),
            palette.get("accent", "#2980b9"),
            0.48,
        )
        warning = blend_hex_colors(
            palette.get("warning", "#d7ba7d"),
            palette.get("accent", "#2980b9"),
            0.12,
        )
        ready_outline = blend_hex_colors(accent, panel_alt, 0.18)
        halo_outline = blend_hex_colors(accent, success, 0.22)
        soft_label = blend_hex_colors(muted, panel_bg, 0.18)
        accent_text = palette.get("accent_text", "#ffffff")

        canvas.delete("all")

        statuses = list(getattr(self, "_wizard_header_metro_statuses", []) or [])
        if not statuses:
            statuses = [
                WizardStageStatus(key=f"step{idx}", title="", state="locked")
                for idx in range(1, 5)
            ]

        width = max(int(canvas.winfo_width() or 720), 360)
        height = max(int(canvas.winfo_height() or 84), 84)
        line_y = 31
        circle_r = 12
        halo_r = 17
        top_y = 0
        label_y = 58
        label_map = {
            "step1": "Wejście",
            "step2": "Tor",
            "step3": "Znaki",
            "step4": "Trening",
        }

        usable_left = 46
        usable_right = width - 46
        if usable_right <= usable_left:
            usable_left = 28
            usable_right = width - 28
        count = max(len(statuses), 2)
        step_gap = (usable_right - usable_left) / max(count - 1, 1)
        positions = [usable_left + idx * step_gap for idx in range(len(statuses))]

        current_index = next((idx for idx, status in enumerate(statuses) if bool(getattr(status, "is_current", False))), None)
        if current_index is None and statuses and all(str(getattr(status, "state", "") or "").strip().lower() in {"done", "skipped"} for status in statuses):
            current_index = len(statuses) - 1

        marker_text = "W TOKU"
        if current_index is not None and 0 <= current_index < len(statuses):
            current_state = str(getattr(statuses[current_index], "state", "") or "").strip().lower()
            if current_state == "skipped":
                marker_text = "POMINIETY"
            elif current_state == "done":
                marker_text = "GOTOWE"

        def station_style(status: WizardStageStatus, *, highlighted: bool) -> dict:
            state_key = str(getattr(status, "state", "") or "").strip().lower()
            if state_key == "done":
                return {"fill": success, "outline": success, "text": accent_text, "label": success, "dash": None}
            if state_key == "needs_attention":
                return {
                    "fill": (warning if highlighted else panel_alt),
                    "outline": warning,
                    "text": (accent_text if highlighted else warning),
                    "label": warning,
                    "dash": None,
                }
            if state_key == "in_progress":
                return {
                    "fill": (accent if highlighted else panel_alt),
                    "outline": accent,
                    "text": (accent_text if highlighted else accent),
                    "label": accent,
                    "dash": None,
                }
            if state_key == "ready":
                return {"fill": panel_bg, "outline": ready_outline, "text": accent, "label": accent, "dash": None}
            if state_key == "skipped":
                return {"fill": panel_bg, "outline": muted_dim, "text": muted_dim, "label": muted_dim, "dash": (3, 2)}
            return {"fill": panel_bg, "outline": border, "text": soft_label, "label": soft_label, "dash": None}

        if PIL_AVAILABLE and Image is not None and ImageTk is not None and ImageDraw is not None and ImageFont is not None:
            hi_pixel_budget = 4_500_000
            scale = 4 if (width * height) <= 180_000 else 2
            hi_w = max(width * scale, 4)
            hi_h = max(height * scale, 4)
            can_use_pil_metro = (hi_w * hi_h) <= hi_pixel_budget and width <= 2400 and height <= 280
            if can_use_pil_metro:
                try:
                    image = Image.new("RGBA", (hi_w, hi_h), self._hex_to_rgba(panel_bg))
                    draw = ImageDraw.Draw(image, "RGBA")
                    font_marker = self._get_pil_font(10 * scale, bold=False)
                    font_step = self._get_pil_font(10 * scale, bold=True)
                    font_label = self._get_pil_font(10 * scale, bold=False)
                    font_skipped = self._get_pil_font(9 * scale, bold=False)

                    def s(value: float) -> int:
                        return int(round(float(value) * scale))

                    for idx in range(len(positions) - 1):
                        segment_color = border
                        if current_index is not None:
                            if idx < current_index - 1:
                                segment_color = success
                            elif idx == current_index - 1:
                                current_state = str(getattr(statuses[current_index], "state", "") or "").strip().lower()
                                if current_state == "needs_attention":
                                    segment_color = warning
                                elif current_state in {"in_progress", "ready"}:
                                    segment_color = accent
                                else:
                                    segment_color = success
                        elif statuses and all(str(getattr(status, "state", "") or "").strip().lower() in {"done", "skipped"} for status in statuses):
                            segment_color = success

                        draw.line(
                            [(s(positions[idx] + circle_r), s(line_y)), (s(positions[idx + 1] - circle_r), s(line_y))],
                            fill=self._hex_to_rgba(segment_color),
                            width=max(2, s(4)),
                        )

                    marker_bbox = None
                    if current_index is not None and 0 <= current_index < len(positions):
                        current_status = statuses[current_index]
                        current_style = station_style(current_status, highlighted=True)
                        marker_x = s(positions[current_index])
                        marker_y = s(top_y)
                        try:
                            bbox = draw.textbbox((0, 0), marker_text, font=font_marker)
                            text_w = max(1, bbox[2] - bbox[0])
                            text_h = max(1, bbox[3] - bbox[1])
                        except Exception:
                            text_w = 24 * scale
                            text_h = 8 * scale
                        text_pos = (marker_x - text_w // 2, marker_y)
                        draw.text(text_pos, marker_text, font=font_marker, fill=self._hex_to_rgba(current_style["outline"]))
                        marker_bbox = (text_pos[0], text_pos[1], text_pos[0] + text_w, text_pos[1] + text_h)
                        marker_line_top = marker_bbox[3] + (6 * scale)
                        marker_line_bottom = s(line_y - halo_r - 4)
                        if marker_line_bottom > marker_line_top:
                            draw.line(
                                [(marker_x, marker_line_top), (marker_x, marker_line_bottom)],
                                fill=self._hex_to_rgba(current_style["outline"]),
                                width=max(2, s(2)),
                            )

                    for idx, status in enumerate(statuses):
                        state_key = str(getattr(status, "state", "") or "").strip().lower()
                        if state_key != "skipped" or idx == current_index:
                            continue
                        skipped_style = station_style(status, highlighted=False)
                        skipped_text = "POMINIETO"
                        try:
                            bbox = draw.textbbox((0, 0), skipped_text, font=font_skipped)
                            text_w = max(1, bbox[2] - bbox[0])
                        except Exception:
                            text_w = 30 * scale
                        draw.text(
                            (s(positions[idx]) - text_w // 2, s(top_y + 2)),
                            skipped_text,
                            font=font_skipped,
                            fill=self._hex_to_rgba(skipped_style["label"]),
                        )

                    for idx, status in enumerate(statuses):
                        x = positions[idx]
                        highlighted = bool(current_index == idx)
                        style = station_style(status, highlighted=highlighted)

                        if highlighted:
                            draw.ellipse(
                                [s(x - halo_r), s(line_y - halo_r), s(x + halo_r), s(line_y + halo_r)],
                                outline=self._hex_to_rgba(halo_outline if str(getattr(status, "state", "") or "").strip().lower() in {"in_progress", "ready"} else style["outline"]),
                                width=max(2, s(2)),
                            )

                        draw.ellipse(
                            [s(x - circle_r), s(line_y - circle_r), s(x + circle_r), s(line_y + circle_r)],
                            fill=self._hex_to_rgba(style["fill"]),
                            outline=self._hex_to_rgba(style["outline"]),
                            width=max(2, s(2)),
                        )

                        step_text = f"E{idx + 1}"
                        try:
                            bbox = draw.textbbox((0, 0), step_text, font=font_step)
                            step_x = s(x) - ((bbox[0] + bbox[2]) / 2.0)
                            step_y = s(line_y) - ((bbox[1] + bbox[3]) / 2.0)
                        except Exception:
                            step_x = s(x) - (7 * scale)
                            step_y = s(line_y) - (4 * scale)
                        draw.text(
                            (step_x, step_y),
                            step_text,
                            font=font_step,
                            fill=self._hex_to_rgba(style["text"]),
                        )

                        label_text_local = label_map.get(getattr(status, "key", ""), f"E{idx + 1}")
                        label_color = style["label"] if highlighted or str(getattr(status, "state", "") or "").strip().lower() in {"done", "in_progress", "needs_attention"} else soft_label
                        try:
                            bbox = draw.textbbox((0, 0), label_text_local, font=font_label)
                            label_w = max(1, bbox[2] - bbox[0])
                        except Exception:
                            label_w = 24 * scale
                        draw.text(
                            (s(x) - label_w // 2, s(label_y)),
                            label_text_local,
                            font=font_label,
                            fill=self._hex_to_rgba(label_color),
                        )

                    try:
                        resampling = Image.Resampling.LANCZOS
                    except Exception:
                        resampling = Image.LANCZOS
                    image = image.resize((width, height), resampling)
                    self._wizard_header_metro_photo = ImageTk.PhotoImage(image)
                    canvas.create_image(0, 0, anchor=tk.NW, image=self._wizard_header_metro_photo)
                    return
                except MemoryError:
                    logger.warning(
                        "Wizard metro PIL fallback po MemoryError: width=%s height=%s scale=%s hi=%sx%s",
                        width,
                        height,
                        scale,
                        hi_w,
                        hi_h,
                    )
                except Exception as exc:
                    logger.debug("Wizard metro PIL fallback do Canvas: %s", exc)

        for idx in range(len(positions) - 1):
            segment_color = border
            if current_index is not None:
                if idx < current_index - 1:
                    segment_color = success
                elif idx == current_index - 1:
                    current_state = str(getattr(statuses[current_index], "state", "") or "").strip().lower()
                    if current_state == "needs_attention":
                        segment_color = warning
                    elif current_state in {"in_progress", "ready"}:
                        segment_color = accent
                    else:
                        segment_color = success
            elif statuses and all(str(getattr(status, "state", "") or "").strip().lower() in {"done", "skipped"} for status in statuses):
                segment_color = success

            canvas.create_line(
                positions[idx] + circle_r,
                line_y,
                positions[idx + 1] - circle_r,
                line_y,
                fill=segment_color,
                width=4,
                capstyle=tk.ROUND,
            )

        if current_index is not None and 0 <= current_index < len(positions):
            current_status = statuses[current_index]
            current_style = station_style(current_status, highlighted=True)
            marker_id = canvas.create_text(
                positions[current_index],
                top_y,
                text=marker_text,
                fill=current_style["outline"],
                font=("Segoe UI", 12, "normal"),
                anchor=tk.N,
            )
            try:
                marker_bbox = canvas.bbox(marker_id)
            except Exception:
                marker_bbox = None

            marker_line_top = (marker_bbox[3] + 6) if marker_bbox else (top_y + 14)
            marker_line_bottom = line_y - halo_r - 4
            if marker_line_bottom > marker_line_top:
                canvas.create_line(
                    positions[current_index],
                    marker_line_top,
                    positions[current_index],
                    marker_line_bottom,
                    fill=current_style["outline"],
                    width=2,
                )

        for idx, status in enumerate(statuses):
            state_key = str(getattr(status, "state", "") or "").strip().lower()
            if state_key != "skipped" or idx == current_index:
                continue
            skipped_style = station_style(status, highlighted=False)
            canvas.create_text(
                positions[idx],
                top_y + 2,
                text="POMINIETO",
                fill=skipped_style["label"],
                font=("Segoe UI", 11, "normal"),
                anchor=tk.N,
            )

        for idx, status in enumerate(statuses):
            x = positions[idx]
            highlighted = bool(current_index == idx)
            style = station_style(status, highlighted=highlighted)

            if highlighted:
                canvas.create_oval(
                    x - halo_r,
                    line_y - halo_r,
                    x + halo_r,
                    line_y + halo_r,
                    outline=(halo_outline if str(getattr(status, "state", "") or "").strip().lower() in {"in_progress", "ready"} else style["outline"]),
                    width=2,
                )

            oval_id = canvas.create_oval(
                x - circle_r,
                line_y - circle_r,
                x + circle_r,
                line_y + circle_r,
                fill=style["fill"],
                outline=style["outline"],
                width=2,
            )
            if style["dash"]:
                canvas.itemconfigure(oval_id, dash=style["dash"])

            canvas.create_text(
                x,
                line_y,
                text=f"E{idx + 1}",
                fill=style["text"],
                font=("Segoe UI", 11, "bold"),
            )
            canvas.create_text(
                x,
                label_y,
                text=label_map.get(getattr(status, "key", ""), f"E{idx + 1}"),
                fill=(style["label"] if highlighted or str(getattr(status, "state", "") or "").strip().lower() in {"done", "in_progress", "needs_attention"} else soft_label),
                font=("Segoe UI", 11, ("bold" if highlighted else "normal")),
            )

    def _build_wizard_stage_card(self, parent, key: str, *, help_key: str | None = None):
        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        shell = tk.Frame(parent, bg=border, bd=0, highlightthickness=0)
        shell.pack(fill=tk.X, pady=(0, 12))

        content = tk.Frame(shell, bg=card_bg, padx=14, pady=12)
        content.pack(fill=tk.X, padx=1, pady=1)

        header_row = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)
        header_row.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_row,
            text="",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 12, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=card_bg,
        )
        title_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        header_status_col = tk.Frame(header_row, bg=card_bg, bd=0, highlightthickness=0)
        header_status_col.pack(side=tk.RIGHT, padx=(10, 0))
        header_status_col.grid_columnconfigure(0, weight=1)

        badge_lbl = tk.Label(
            header_status_col,
            text="",
            anchor="e",
            justify=tk.RIGHT,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
            bd=0,
            highlightthickness=0,
        )
        badge_lbl.grid(row=0, column=0, sticky="e")

        badge_cta_shell = tk.Frame(header_status_col, bg=card_bg, bd=0, highlightthickness=0)
        badge_cta_shell.grid(row=1, column=0, sticky="e", pady=(6, 0))
        badge_cta_shell.grid_remove()
        badge_cta_btn = tk.Label(
            badge_cta_shell,
            text="zatwierdź",
            bd=0,
            highlightthickness=1,
            padx=8,
            pady=1,
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
            anchor="center",
            justify=tk.CENTER,
        )
        badge_cta_btn.pack(anchor=tk.E)

        summary_lbl = tk.Label(
            content,
            text="",
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
            fg=palette.get("fg", "#f3f3f3"),
            bg=card_bg,
        )
        summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

        details_lbl = tk.Label(
            content,
            text="",
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
            fg=palette.get("muted", "#c7c7c7"),
            bg=card_bg,
        )
        details_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))

        action_row = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)
        action_row.pack(fill=tk.X, pady=(10, 0))

        primary_btn = ttk.Button(action_row, text="")
        secondary_btn = ttk.Button(action_row, text="")

        curtain_shell = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)

        curtain_toggle = tk.Frame(
            curtain_shell,
            bg=card_bg,
            bd=0,
            highlightthickness=1,
            cursor="hand2",
            padx=10,
            pady=8,
        )
        curtain_toggle.pack(fill=tk.X)

        curtain_indicator = tk.Label(
            curtain_toggle,
            text="▸",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
            bg=card_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        curtain_indicator.pack(side=tk.LEFT)

        curtain_text_col = tk.Frame(curtain_toggle, bg=card_bg, bd=0, highlightthickness=0, cursor="hand2")
        curtain_text_col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        curtain_title_lbl = tk.Label(
            curtain_text_col,
            text="",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 9, "bold"),
            bg=card_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        curtain_title_lbl.pack(anchor=tk.W, fill=tk.X)

        curtain_meta_lbl = tk.Label(
            curtain_text_col,
            text="",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 8),
            bg=card_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        curtain_meta_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))

        curtain_clip = tk.Frame(curtain_shell, bg=card_bg, bd=0, highlightthickness=0, height=0)
        curtain_clip.pack(fill=tk.X, pady=(6, 0))
        curtain_clip.pack_propagate(False)

        curtain_inner = tk.Frame(curtain_clip, bg=card_bg, bd=0, highlightthickness=0)
        curtain_inner.pack(fill=tk.X)

        curtain_table = tk.Frame(
            curtain_inner,
            bg=card_bg,
            bd=0,
            highlightthickness=1,
        )
        curtain_table.pack(fill=tk.X)

        body = tk.Frame(content, bg=card_bg, bd=0, highlightthickness=0)

        if help_key:
            for widget in (shell, content, header_row, header_status_col, title_lbl, summary_lbl, details_lbl, body, curtain_shell, curtain_toggle, curtain_table, badge_cta_shell, badge_cta_btn):
                HELP.bind_help(widget, help_key)

        card = {
            "key": key,
            "shell": shell,
            "content": content,
            "header_row": header_row,
            "header_status_col": header_status_col,
            "title": title_lbl,
            "badge": badge_lbl,
            "badge_cta_shell": badge_cta_shell,
            "badge_cta_btn": badge_cta_btn,
            "summary": summary_lbl,
            "details": details_lbl,
            "action_row": action_row,
            "primary_btn": primary_btn,
            "secondary_btn": secondary_btn,
            "body": body,
            "curtain_shell": curtain_shell,
            "curtain_toggle": curtain_toggle,
            "curtain_indicator": curtain_indicator,
            "curtain_text_col": curtain_text_col,
            "curtain_title": curtain_title_lbl,
            "curtain_meta": curtain_meta_lbl,
            "curtain_clip": curtain_clip,
            "curtain_inner": curtain_inner,
            "curtain_table": curtain_table,
            "curtain_visible": False,
            "curtain_expanded": False,
            "curtain_user_touched": False,
            "curtain_after_id": None,
        }

        for widget in (curtain_toggle, curtain_indicator, curtain_text_col, curtain_title_lbl, curtain_meta_lbl):
            try:
                widget.bind("<Button-1>", lambda _event, stage_key=key: self._toggle_wizard_stage_curtain(stage_key), add="+")
            except Exception:
                pass

        return card

    def _is_wizard_stage_emphasized(self, status: WizardStageStatus) -> bool:
        state_key = str(getattr(status, "state", "") or "").strip().lower()
        if bool(getattr(status, "is_current", False)):
            return True
        return state_key in {"in_progress", "needs_attention"}

    def _get_wizard_stage_state_style(self, state: str, *, is_current: bool = False, emphasized: bool = True) -> dict:
        palette = getattr(self.app, "palette", {})
        state_key = str(state or "").strip().lower()
        style_map = {
            "locked": {
                "label": "ZABLOKOWANE",
                "border": palette.get("panel_border", palette.get("border", "#3c3c3c")),
                "badge_bg": palette.get("panel_alt", "#2f3136"),
                "badge_fg": palette.get("muted", "#c7c7c7"),
                "title_fg": palette.get("muted", "#c7c7c7"),
                "summary_fg": palette.get("muted", "#c7c7c7"),
                "details_fg": palette.get("muted_dim", "#9a9a9a"),
            },
            "ready": {
                "label": "GOTOWE",
                "border": palette.get("accent", "#2980b9"),
                "badge_bg": palette.get("surface_info", palette.get("panel_alt", "#2d3640")),
                "badge_fg": palette.get("accent", "#2980b9"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "in_progress": {
                "label": "W TOKU",
                "border": palette.get("accent", "#2980b9"),
                "badge_bg": palette.get("surface_info", palette.get("panel_alt", "#2d3640")),
                "badge_fg": palette.get("accent", "#2980b9"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "needs_attention": {
                "label": "UWAGA",
                "border": palette.get("warning", "#d35400"),
                "badge_bg": palette.get("surface_warning", palette.get("panel_alt", "#3a2323")),
                "badge_fg": palette.get("warning", "#d35400"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "done": {
                "label": "GOTOWE",
                "border": blend_hex_colors(
                    palette.get("success", "#27ae60"),
                    palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    0.78,
                ),
                "badge_bg": blend_hex_colors(
                    palette.get("surface_success", palette.get("panel_alt", "#1f3320")),
                    palette.get("panel_alt", "#2f3136"),
                    0.42,
                ),
                "badge_fg": palette.get("success", "#27ae60"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
                "details_fg": palette.get("muted", "#c7c7c7"),
            },
            "skipped": {
                "label": "POMINIETE",
                "border": palette.get("panel_border", palette.get("border", "#3c3c3c")),
                "badge_bg": palette.get("panel_alt", "#2f3136"),
                "badge_fg": palette.get("muted_dim", "#9a9a9a"),
                "title_fg": palette.get("muted", "#c7c7c7"),
                "summary_fg": palette.get("muted", "#c7c7c7"),
                "details_fg": palette.get("muted_dim", "#9a9a9a"),
            },
        }
        base = dict(style_map.get(state_key, style_map["locked"]))
        if is_current and state_key in {"ready", "in_progress", "needs_attention"}:
            base["border"] = palette.get("accent", "#2980b9")
        if not emphasized:
            panel_border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
            panel_alt = palette.get("panel_alt", "#2f3136")
            base["border"] = blend_hex_colors(base.get("border", panel_border), panel_border, 0.82)
            base["badge_bg"] = blend_hex_colors(base.get("badge_bg", panel_alt), panel_alt, 0.42)
            base["badge_fg"] = palette.get("muted_dim", "#9a9a9a")
            base["title_fg"] = palette.get("muted", "#c7c7c7")
            base["summary_fg"] = palette.get("muted_dim", "#9a9a9a")
            base["details_fg"] = palette.get("muted_dim", "#9a9a9a")
        return base

    def _configure_wizard_stage_button(self, button, label: str, command, *, side=tk.LEFT, padx=(0, 0), debug_id: str = ""):
        if button is None:
            return
        label_text = str(label or "").strip()
        if not label_text or command is None:
            try:
                button.configure(text="", command=(lambda: None), state="disabled")
            except Exception:
                pass
            self._set_pack_visibility(button, False)
            return

        debug_suffix = f" ({debug_id})" if str(debug_id or "").strip() else ""
        try:
            button.configure(text=f"{label_text}{debug_suffix}", command=command, state="normal")
        except Exception:
            pass
        self._set_pack_visibility(button, True, side=side, padx=padx)

    def _configure_wizard_stage_badge_cta(self, card: dict, *, visible: bool, command=None):
        if not card:
            return
        shell = card.get("badge_cta_shell")
        button = card.get("badge_cta_btn")
        if shell is None or button is None:
            return

        if not visible or command is None:
            try:
                button.unbind("<Button-1>")
                button.unbind("<Enter>")
                button.unbind("<Leave>")
            except Exception:
                pass
            try:
                shell.grid_remove()
            except Exception:
                pass
            return

        palette = getattr(self.app, "palette", {})
        success = palette.get("success", "#27ae60")
        surface_success = palette.get("surface_success", "#1f3320")
        panel_bg = palette.get("panel", "#252526")
        glow = blend_hex_colors(success, surface_success, 0.22)
        fill = blend_hex_colors(surface_success, panel_bg, 0.18)
        text_color = palette.get("fg", "#f3f3f3")

        try:
            shell.configure(bg=glow)
        except Exception:
            pass
        try:
            button.configure(
                text="Zatwierdź etap",
                bg=fill,
                fg=text_color,
                highlightbackground=glow,
                highlightcolor=glow,
            )
        except Exception:
            pass
        try:
            button.unbind("<Button-1>")
            button.unbind("<Enter>")
            button.unbind("<Leave>")
        except Exception:
            pass
        try:
            button.bind("<Button-1>", lambda _event, cmd=command: cmd(), add="+")
            button.bind("<Enter>", lambda _event, widget=button, bg=blend_hex_colors(fill, success, 0.18): widget.configure(bg=bg), add="+")
            button.bind("<Leave>", lambda _event, widget=button, bg=fill: widget.configure(bg=bg), add="+")
        except Exception:
            pass
        try:
            shell.grid()
        except Exception:
            pass

    def _apply_wizard_stage_status(self, card: dict, status: WizardStageStatus):
        if not card:
            return

        self._set_pack_visibility(card.get("shell"), bool(status.visible), fill=tk.X, pady=(0, 12))
        if not status.visible:
            return

        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        emphasized = self._is_wizard_stage_emphasized(status)
        style = self._get_wizard_stage_state_style(status.state, is_current=status.is_current, emphasized=emphasized)

        inline_approve = bool(
            str(getattr(status, "badge_action_label", "") or "").strip()
            and getattr(status, "badge_action_command", None) is not None
        )

        try:
            card["shell"].config(bg=style["border"])
            card["content"].config(bg=card_bg)
            card["header_row"].config(bg=card_bg)
            card["header_status_col"].config(bg=card_bg)
            card["action_row"].config(bg=card_bg)
            card["body"].config(bg=card_bg)
            card["title"].config(text=status.title, fg=style["title_fg"], bg=card_bg)
            card["badge"].config(
                text=("W TOKU" if inline_approve else style["label"]),
                fg=style["badge_fg"],
                bg=style["badge_bg"],
            )
            card["summary"].config(text=str(status.summary or "").strip(), fg=style["summary_fg"], bg=card_bg)
        except Exception:
            pass

        details_text = str(status.details or "").strip()
        try:
            card["details"].config(text=details_text, bg=card_bg, fg=style.get("details_fg", palette.get("muted", "#c7c7c7")))
        except Exception:
            pass
        self._set_pack_visibility(
            card.get("details"),
            bool(details_text),
            anchor=tk.W,
            fill=tk.X,
            pady=(6, 0),
            before=card.get("action_row"),
        )

        self._render_step1_stage_curtain(card, status, style)

        stage_key = str(status.key or "").strip().upper() or "STAGE"
        row_primary_label = str(status.primary_label or "")
        row_primary_command = status.primary_command
        self._configure_wizard_stage_button(
            card.get("primary_btn"),
            row_primary_label,
            row_primary_command,
            side=tk.LEFT,
            padx=(0, 8),
            debug_id=f"{stage_key}-P1",
        )
        self._configure_wizard_stage_button(
            card.get("secondary_btn"),
            status.secondary_label,
            status.secondary_command,
            side=tk.LEFT,
            padx=(0, 0),
            debug_id=f"{stage_key}-P2",
        )
        self._configure_wizard_stage_badge_cta(
            card,
            visible=inline_approve,
            command=status.badge_action_command,
        )
        footer_actions_visible = bool(str(row_primary_label or "").strip() or str(status.secondary_label or "").strip())
        if str(getattr(status, "body_mode", "") or "").strip() == "step2_route":
            footer_actions_visible = False
        self._set_pack_visibility(
            card.get("action_row"),
            footer_actions_visible,
            fill=tk.X,
            pady=(10, 0),
        )

        body = card.get("body")
        if body is not None:
            if status.body_mode == "step2_route":
                self._render_step2_route_actions(body)
            elif status.body_mode == "step1_ingest":
                try:
                    self._theme_step1_ingest_panel()
                except Exception:
                    pass
            if status.body_mode == "step2_route":
                self._set_pack_visibility(
                    body,
                    bool(status.body_visible),
                    fill=tk.X,
                    pady=(12, 0),
                    before=card.get("action_row"),
                )
            elif status.body_mode == "step3_rework":
                self._set_pack_visibility(body, False)
            else:
                self._set_pack_visibility(body, bool(status.body_visible), fill=tk.X, pady=(12, 0))

    def _get_softened_banner_bg(self, bg: str) -> str:
        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        try:
            return blend_hex_colors(bg, panel_bg, 0.74)
        except Exception:
            return str(bg or panel_bg)

    def _configure_campaign_banner(self, *, text: str, fg: str, bg: str):
        softened_bg = self._get_softened_banner_bg(bg)

        try:
            if self.campaign_banner_shell is not None:
                self.campaign_banner_shell.config(bg=softened_bg)
        except Exception:
            pass

        try:
            if self.banner_top_row is not None:
                self.banner_top_row.config(bg=softened_bg)
        except Exception:
            pass

        try:
            if self.banner_progress_row is not None:
                self.banner_progress_row.config(bg=softened_bg)
        except Exception:
            pass

        try:
            self.lbl_campaign_banner.config(text=text, fg=fg, bg=softened_bg)
        except Exception:
            pass

        try:
            if self.wizard_header_metro_canvas is not None:
                self.wizard_header_metro_canvas.config(bg=softened_bg)
            if self.wizard_exit_button_canvas is not None:
                self.wizard_exit_button_canvas.config(bg=softened_bg)
        except Exception:
            pass

        self.frame.after_idle(self._draw_wizard_stage_metro)
        self.frame.after_idle(lambda: self._draw_icon_button("exit_project"))

    def _refresh_wizard_empty_state(self, *, projects_available: bool):
        try:
            self.wizard_header_title_lbl.config(text="Brak aktywnego projektu")
            self.wizard_header_summary_lbl.config(text="Utworz albo otwórz projekt w panelu Projekt.")
        except Exception:
            pass
        self._set_pack_visibility(self.wizard_empty_state_card.get("shell"), False)
        self._set_pack_visibility(self.wizard_stage_cards_host, False)
        self._refresh_wizard_stage_metro([])
        return

    def _build_active_project_dashboard_state(self) -> dict:
        state_started = perf_counter()
        active_proj = str(CAMPAIGN.get_active_project_name() or "").strip()
        if not active_proj:
            return {}

        curr_step = int(CAMPAIGN.get_current_step() or 1)
        step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower() or "pending"
        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower() or "pending"
        step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower() or "pending"
        iteration_target = self._get_iteration_target()
        has_saved_step3_progress = self._has_saved_step3_progress()
        project_status = str(CAMPAIGN.get_project_status() or "active").strip().lower() or "active"
        project_paused_at = CAMPAIGN.get_project_paused_at()
        project_completed_at = CAMPAIGN.get_project_completed_at()

        step1_approved = step1_status == "approved"
        if curr_step >= 2 and not step1_approved and self._get_iteration_image_count() > 0:
            CAMPAIGN.approve_step1()
            step1_status = "approved"
            step1_approved = True

        default_iteration_target = self._get_default_step2_iteration_target(
            current_step=curr_step,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
            iteration_target=iteration_target,
        )
        if default_iteration_target in {"plate", "char"} and default_iteration_target != iteration_target:
            CAMPAIGN.set_iteration_target(default_iteration_target)
            iteration_target = default_iteration_target

        if (
            curr_step <= 2
            and step2_status == "pending"
            and step3_status == "pending"
            and not iteration_target
            and has_saved_step3_progress
        ):
            try:
                CAMPAIGN.reset_step3()
                has_saved_step3_progress = False
            except Exception as e:
                logger.debug(f"Nie udało się wyczyscic przestarzalego stanu Z3 przy starcie iteracji: {e}")

        if not iteration_target and (curr_step >= 3 or step3_status != "pending" or has_saved_step3_progress):
            CAMPAIGN.set_iteration_target("char")
            iteration_target = "char"

        if iteration_target == "char" and curr_step < 3 and step2_status == "approved" and has_saved_step3_progress:
            if step2_status != "approved":
                CAMPAIGN.approve_step2()
                step2_status = "approved"
            CAMPAIGN.set_current_step(3)
            curr_step = 3

        if iteration_target == "plate" and curr_step == 3 and step2_status == "approved":
            CAMPAIGN.set_current_step(4)
            curr_step = 4

        if iteration_target == "char" and curr_step == 3 and step3_status in {"pending", "needs_rework"}:
            try:
                readiness = self._detect_campaign_char_ready_dataset_state()
                if bool(readiness.get("ok")):
                    CAMPAIGN.set_step3_ready()
                    step3_status = "ready"
            except Exception as e:
                logger.debug(f"Nie udało się zaktualizować stanu gotowosci E3 z datasetu znaków: {e}")

        self._log_perf(
            "build_active_dashboard_state",
            state_started,
            threshold_ms=20.0,
            extra=f"step={curr_step}, target={iteration_target or '-'}",
        )
        return {
            "active_project": active_proj,
            "current_step": int(curr_step),
            "step1_status": step1_status,
            "step2_status": step2_status,
            "step3_status": step3_status,
            "iteration_target": iteration_target,
            "project_status": project_status,
            "project_paused_at": project_paused_at,
            "project_completed_at": project_completed_at,
        }

    def _refresh_active_project_wizard_only(self) -> None:
        refresh_started = perf_counter()
        self._clear_dashboard_perf_cache()
        active_state = self._build_active_project_dashboard_state()
        active_project = str(active_state.get("active_project") or "").strip()
        if not active_project:
            self._refresh_dashboard()
            return

        try:
            self._ensure_roadmap_ui_ready()
        except Exception:
            pass

        palette = getattr(self.app, "palette", {})
        header_bg = palette.get("panel", "#252526")
        accent = palette.get("accent", "#2980b9")
        success = palette.get("success", "#27ae60")
        warning = palette.get("warning", "#d35400")
        surface_info = palette.get("surface_info", palette.get("panel_alt", "#252526"))
        surface_success = palette.get("surface_success", palette.get("panel_alt", "#1f3320"))
        surface_warning = palette.get("surface_warning", palette.get("panel_alt", "#3a2323"))

        curr_step = int(active_state.get("current_step", 1) or 1)
        step1_status = str(active_state.get("step1_status", "pending") or "pending")
        step2_status = str(active_state.get("step2_status", "pending") or "pending")
        step3_status = str(active_state.get("step3_status", "pending") or "pending")
        iteration_target = str(active_state.get("iteration_target", "") or "").strip().lower()
        project_status = str(active_state.get("project_status", "active") or "active").strip().lower()
        project_paused_at = str(active_state.get("project_paused_at", "") or "").strip()
        project_completed_at = str(active_state.get("project_completed_at", "") or "").strip()
        project_paused = project_status == "paused"
        project_completed = project_status == "completed"
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)

        project_title = self._format_project_iteration_title(active_project, iter_num)
        banner_text = project_title
        banner_fg = success
        banner_bg = surface_success
        if project_completed:
            completed_display = self._format_project_status_timestamp(project_completed_at)
            banner_text = f"{project_title}  |  Zakończony: {completed_display}"
            banner_fg = warning
            banner_bg = surface_warning
        elif project_paused:
            paused_display = self._format_project_status_timestamp(project_paused_at)
            banner_text = f"{project_title}  |  Odłożony: {paused_display}"
            banner_fg = accent
            banner_bg = surface_info

        self.lbl_iter.config(text=f"Iteracja: {iter_num}", fg=warning, bg=header_bg)
        self._configure_campaign_banner(text=banner_text, fg=banner_fg, bg=banner_bg)
        self._set_icon_button_enabled("exit_project", True)
        self._refresh_wizard_active_dashboard(
            active_project=active_project,
            current_step=curr_step,
            iteration_target=iteration_target,
            project_status=project_status,
            project_paused_at=project_paused_at,
            project_completed_at=project_completed_at,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
        )
        self._update_main_tabs_highlight(curr_step=curr_step, has_project=True)
        self.app.update_campaign_tab_access()
        self.frame.update_idletasks()
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self._schedule_pending_wizard_stage_focus()
        self._log_perf(
            "refresh_active_project_wizard_only",
            refresh_started,
            threshold_ms=20.0,
            extra=f"step={curr_step}, target={iteration_target or '-'}",
        )

    def _cancel_deferred_project_open_tasks(self) -> None:
        for attr_name in ("_project_open_refresh_after_id", "_project_open_context_after_id"):
            pending = getattr(self, attr_name, None)
            if not pending:
                continue
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
            setattr(self, attr_name, None)

    def _build_project_loading_stage_statuses(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
    ) -> list[WizardStageStatus]:
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        target_label = self._iteration_target_label(iteration_target) if iteration_target else "tor iteracji jest ustalany"
        clamped_step = min(max(int(current_step or 1), 1), 4)

        statuses = [
            WizardStageStatus(
                key="project",
                title=self._format_project_iteration_title(active_project, iter_num),
                state="in_progress",
                summary=f"Iteracja {iter_num}. Trwa otwieranie projektu.",
                details=f"Ładuję stan projektu, modeli i etapów. Kontekst: {target_label}.",
                is_current=True,
            ),
        ]

        stage_specs = (
            ("step1", "E1. Paczka wejściowa iteracji"),
            ("step2", "E2. Tor iteracji i przygotowanie Z2"),
            ("step3", "E3. Znaki i gold pack"),
            ("step4", "E4. Dataset i trening"),
        )

        for idx, (key, title) in enumerate(stage_specs, start=1):
            if idx < clamped_step:
                state = "ready"
                summary = "Odtwarzam zapisany stan etapu."
            elif idx == clamped_step:
                state = "in_progress"
                summary = "Ładuję bieżący stan etapu."
            else:
                state = "locked"
                summary = "Stan etapu zostanie odczytany za chwilę."

            statuses.append(
                WizardStageStatus(
                    key=key,
                    title=title,
                    state=state,
                    summary=summary,
                    details="To chwilowy stan podczas otwierania projektu.",
                    body_mode="",
                    body_visible=False,
                    is_current=bool(idx == clamped_step),
                )
            )

        return statuses

    def _show_project_loading_dashboard(self, active_project: str) -> None:
        if not active_project:
            return

        palette = getattr(self.app, "palette", {})
        header_bg = palette.get("panel", "#252526")
        info_fg = palette.get("accent", "#2980b9")
        info_bg = palette.get("surface_info", palette.get("panel_alt", "#252526"))
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")

        current_step = int(CAMPAIGN.get_current_step() or 1)
        iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)

        try:
            self._refresh_projects_list()
        except Exception:
            pass

        try:
            self._collapse_all_wizard_stage_curtains()
        except Exception:
            pass

        try:
            self.lbl_iter.config(text=f"Iteracja: {iter_num}", fg=info_fg, bg=header_bg)
            self._configure_campaign_banner(
                text=(
                    f"{self._format_project_iteration_title(active_project, iter_num)}  |  "
                    "Ładowanie kontekstu kampanii..."
                ),
                fg=info_fg,
                bg=info_bg,
            )
            self._set_icon_button_enabled("exit_project", True)
        except Exception:
            pass

        for mt in ["vehicle", "plate", "char"]:
            try:
                getattr(self, f"lbl_model_{mt}").config(text="Ładowanie...", fg=muted)
            except Exception:
                pass
            try:
                lbl_meta = getattr(self, f"lbl_model_{mt}_meta", None)
                if lbl_meta is not None:
                    lbl_meta.config(text="Utworzono: -", fg=muted_dim)
            except Exception:
                pass
            try:
                btn_model = getattr(self, f"btn_model_{mt}", None)
                if btn_model is not None:
                    btn_model.config(state="disabled")
            except Exception:
                pass

        try:
            self.btn_open_proj.config(state="normal")
            self.btn_del_proj.config(state="normal")
            self.btn_exit_project.config(state="normal")
            self.btn_complete_project.config(text="Ładowanie...", state="disabled", style="TButton")
        except Exception:
            pass

        try:
            self._set_pack_visibility(self.wizard_empty_state_card.get("shell"), False)
            self._set_pack_visibility(self.wizard_stage_cards_host, True, fill=tk.X)
            self.wizard_header_title_lbl.config(
                text=self._format_project_iteration_title(active_project, iter_num)
            )
            self.wizard_header_summary_lbl.config(
                text=(
                    f"Iteracja {iter_num}. Trwa odczyt stanu kampanii. "
                    "Za chwilę pojawi się pełny status E1-E4."
                )
            )
        except Exception:
            pass

        statuses = self._build_project_loading_stage_statuses(
            active_project=active_project,
            current_step=current_step,
            iteration_target=iteration_target,
        )
        try:
            self._refresh_wizard_stage_metro(statuses)
            for status in statuses:
                card = self.wizard_stage_cards.get(status.key)
                if card is not None:
                    self._apply_wizard_stage_status(card, status)
        except Exception:
            pass

        try:
            self._update_main_tabs_highlight(curr_step=current_step, has_project=True)
        except Exception:
            pass

        try:
            self.frame.update_idletasks()
        except Exception:
            pass

    def _refresh_wizard_active_dashboard(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
        project_status: str,
        project_paused_at: str,
        project_completed_at: str,
        step1_status: str,
        step2_status: str,
        step3_status: str,
    ):
        self._set_pack_visibility(self.wizard_empty_state_card.get("shell"), False)
        self._set_pack_visibility(self.wizard_stage_cards_host, True, fill=tk.X)

        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        target_label = self._iteration_target_label(iteration_target)
        project_status_norm = str(project_status or "active").strip().lower()
        project_completed = project_status_norm == "completed"
        project_paused = project_status_norm == "paused"
        project_suspended = bool(project_completed or project_paused)
        if not iteration_target:
            target_label = "tor iteracji nie został jeszcze wybrany"

        try:
            self.wizard_header_title_lbl.config(
                text=self._format_project_iteration_title(active_project, iter_num)
            )
            self.wizard_header_summary_lbl.config(
                text=(
                    f"Iteracja {iter_num}. Aktualny etap: E{min(max(int(current_step or 1), 1), 4)}. "
                    f"Kontekst: {target_label}."
                )
                if not project_suspended
                else (
                    f"Projekt został odłożony. Ostatnia iteracja: {iter_num}. "
                    f"Ostatni aktywny tor: {target_label}."
                )
                if project_paused
                else (
                    f"Projekt został zakończony. Ostatnia iteracja: {iter_num}. "
                    f"Ostatni aktywny tor: {target_label}."
                )
            )
        except Exception:
            pass

        try:
            summary_text = (
                f"Iteracja {iter_num}. Etap E{min(max(int(current_step or 1), 1), 4)}. {target_label}."
                if not project_suspended
                else f"Projekt odłożony. Iteracja {iter_num}. {target_label}."
                if project_paused
                else f"Projekt zakończony. Iteracja {iter_num}. {target_label}."
            )
            self.wizard_header_summary_lbl.config(text=summary_text)
        except Exception:
            pass

        statuses = self._get_wizard_stage_statuses(
            active_project=active_project,
            current_step=current_step,
            iteration_target=iteration_target,
            project_status=project_status_norm,
            project_paused_at=project_paused_at,
            project_completed_at=project_completed_at,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
        )
        self._refresh_wizard_stage_metro(statuses)

        for status in statuses:
            card = self.wizard_stage_cards.get(status.key)
            if card is not None:
                self._apply_wizard_stage_status(card, status)

    def _format_project_status_timestamp(self, raw_value: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return "brak daty"

        display = value.replace("T", " ").strip() or "brak daty"
        formatter = getattr(self.app, "_format_project_created_at", None)
        if callable(formatter):
            try:
                return str(formatter(value) or "").strip() or display
            except Exception:
                return display
        return display

    @staticmethod
    def _format_project_iteration_title(project_name: str, iteration_num: int | None = None) -> str:
        name = str(project_name or "").strip()
        if not name:
            return "Brak aktywnego projektu"
        try:
            iter_value = max(1, int(iteration_num or 1))
        except Exception:
            iter_value = 1
        return f"Projekt: {name} | Iteracja {iter_value}"

    def _get_wizard_stage_statuses(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
        project_status: str,
        project_paused_at: str,
        project_completed_at: str,
        step1_status: str,
        step2_status: str,
        step3_status: str,
    ) -> list[WizardStageStatus]:
        statuses: list[WizardStageStatus] = []
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        project_status_norm = str(project_status or "active").strip().lower()
        project_completed = project_status_norm == "completed"
        project_paused = project_status_norm == "paused"
        project_suspended = bool(project_completed or project_paused)
        target_label = self._iteration_target_label(iteration_target)
        iter_image_count = self._get_iteration_image_count()
        step1_approved = str(step1_status or "").strip().lower() == "approved"
        master_pool = CAMPAIGN.get_master_pool_dir()
        master_pool_ready = bool(master_pool and master_pool.exists() and master_pool.is_dir())
        plan_count = int(self.current_ingest_plan.get("selected_total", 0) or 0)
        plate_ready_source = self._get_plate_route_ready_source() if iteration_target == "plate" else {}
        char_ready_source = self._get_char_route_ready_source() if iteration_target == "char" else {}
        char_route_source_state = self._get_char_route_source_state() if iteration_target == "char" else {}
        plate_approved_stats = self._get_plate_approved_set_stats()
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())
        training_tab = self.app.tabs.get("training") if getattr(self.app, "tabs", None) else None
        plate_step4_gate = {
            "ok": True,
            "reason": "",
            "message": "",
            "annotated_images": 0,
            "required_images": 2,
            "source_run": "",
        }
        char_step4_gate = {
            "ok": True,
            "reason": "",
            "message": "",
            "ready_dataset": "",
            "dataset_hint": "",
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "validation_message": "",
        }
        if iteration_target == "plate" and (current_step >= 4 or str(step2_status or "").strip().lower() == "approved"):
            try:
                if training_tab is not None and hasattr(training_tab, "get_campaign_step4_readiness"):
                    plate_step4_gate = training_tab.get_campaign_step4_readiness(iteration_target="plate")
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowosci E4 dla toru tablic: {e}")

        helper_char_step4_gate = (
            self._detect_campaign_char_ready_dataset_state()
            if iteration_target == "char" and (current_step >= 3 or str(step3_status or "").strip().lower() in {"approved", "needs_rework", "ready"})
            else {}
        )

        if iteration_target == "char" and (current_step >= 3 or str(step3_status or "").strip().lower() in {"approved", "needs_rework", "ready"}):
            try:
                if training_tab is not None and hasattr(training_tab, "get_campaign_step4_readiness"):
                    char_step4_gate = training_tab.get_campaign_step4_readiness(iteration_target="char")
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowosci E4 dla toru znaków: {e}")
        if helper_char_step4_gate and bool(helper_char_step4_gate.get("ok")):
            if not bool(char_step4_gate.get("ok")) or not str(char_step4_gate.get("ready_dataset") or "").strip():
                char_step4_gate = dict(helper_char_step4_gate)
            if iteration_target == "char" and current_step == 3 and str(step3_status or "").strip().lower() in {"pending", "needs_rework"}:
                step3_status = "ready"

        char_repair_guidance = (
            self._get_char_repair_guidance(char_route_source_state)
            if iteration_target == "char"
            else {}
        )

        plate_step4_blocked = bool(
            iteration_target == "plate"
            and (current_step >= 4 or str(step2_status or "").strip().lower() == "approved")
            and not bool(plate_step4_gate.get("ok", True))
        )
        plate_step4_reason = str(plate_step4_gate.get("reason") or "").strip().lower()
        char_step4_blocked = bool(
            iteration_target == "char"
            and (current_step >= 4 or str(step3_status or "").strip().lower() == "approved")
            and not bool(char_step4_gate.get("ok", True))
        )
        step4_gate_blocked = bool(plate_step4_blocked or char_step4_blocked)
        step4_finish_state = {}
        try:
            step4_finish_state = CAMPAIGN.get_step4_finish_state() or {}
        except Exception:
            step4_finish_state = {}
        step4_finish_ready = bool(step4_finish_state.get("ready", False))
        step4_finish_target = self._normalize_iteration_target(step4_finish_state.get("target", ""))
        if not step4_finish_target:
            step4_finish_target = iteration_target
        step4_can_advance = bool(
            current_step == 4
            and not step4_gate_blocked
            and step4_finish_ready
            and step4_finish_target == iteration_target
        )

        project_summary = (
            f"Iteracja {iter_num}. {target_label.capitalize()}."
            if iteration_target
            else f"Iteracja {iter_num}. Tor iteracji nie został jeszcze wybrany."
        )
        project_details = "Wizard nie dubluje już ekranów roboczych. Pokazuje stan projektu i kieruje do właściwej zakładki."
        if project_completed:
            completed_display = self._format_project_status_timestamp(project_completed_at)
            project_details = (
                f"Projekt został oznaczony jako zakończony: {completed_display}. "
                "Możesz go wznowić albo wejść do Z4, aby przejrzeć wyniki."
            )
        elif project_paused:
            paused_display = self._format_project_status_timestamp(project_paused_at)
            project_details = (
                f"Projekt został odłożony: {paused_display}. "
                "Możesz go wznowić i wrócić później do tego samego workflow."
            )
        else:
            project_details = (
                "Ta karta pokazuje tylko kontekst projektu. "
                "Praca etapowa odbywa się niżej, przez karty E1-E4."
            )

        statuses.append(
            WizardStageStatus(
                key="project",
                title=f"Projekt {active_project}",
                state=("done" if project_completed else "ready" if project_paused else "in_progress"),
                summary=project_summary,
                details=project_details,
                primary_label=("Wznów projekt" if project_suspended else "Wyjdź z projektu"),
                primary_command=(self._toggle_project_completion if project_suspended else self._exit_project_mode),
                secondary_label="",
                secondary_command=None,
                is_current=bool(project_suspended),
            )
        )

        manifest = self._load_ingest_manifest_cached()
        manifest_mode = str((manifest or {}).get("selection_mode", "") or "").strip().lower() if isinstance(manifest, dict) else ""
        is_iteration_reuse = bool(iter_num > 1 and manifest_mode in {"iteration_reuse", "pool_reuse", "stage_reuse"})
        step1_context = self._get_step1_manifest_context(manifest if isinstance(manifest, dict) else None)
        project_pool_total = int(step1_context.get("project_pool_total_after", step1_context.get("project_pool_total", 0)) or 0)
        approved_images = int(step1_context.get("approved_images", 0) or 0)
        approved_plates = int(step1_context.get("approved_plates", 0) or 0)
        source_total = int(step1_context.get("source_total", 0) or 0)
        duplicate_count = int(step1_context.get("skipped_duplicate_filenames", 0) or 0)
        new_to_project_count = int(step1_context.get("new_to_project_count", 0) or 0)
        current_iteration_package = int(
            step1_context.get("current_iteration_package_count", 0)
            or iter_image_count
            or 0
        )
        source_label = str(step1_context.get("source_label", "") or "").strip()

        project_scope_parts: list[str] = []
        if project_pool_total > 0:
            project_scope_parts.append(f"Łączna pula projektu: {project_pool_total} zdjęć.")
        if approved_images > 0 or approved_plates > 0:
            project_scope_parts.append(
                f"Aktualnie zatwierdzone w projekcie: {approved_images} zdjęć / {approved_plates} tablic."
            )
        project_scope_text = " ".join(project_scope_parts).strip()

        if step1_approved and iter_image_count > 0:
            step1_state = "done"
            if is_iteration_reuse:
                step1_summary = f"Łączna pula projektu: {project_pool_total} zdjęć. Do tej iteracji weszło {current_iteration_package} zdjęć."
                if manifest_mode == "stage_reuse" and source_label:
                    step1_details = f"Źródło tej iteracji: stage po {source_label}."
                elif manifest_mode == "stage_reuse":
                    step1_details = "Źródło tej iteracji: stage po poprzedniej iteracji."
                elif manifest_mode == "pool_reuse":
                    step1_details = "Źródło tej iteracji: ta sama pula projektu."
                else:
                    step1_details = "Źródło tej iteracji: poprzedni zestaw wejściowy projektu."
                if project_scope_text:
                    step1_details = f"{step1_details} {project_scope_text}".strip()
            else:
                step1_summary = f"Łączna pula projektu: {project_pool_total} zdjęć. Do tej iteracji weszło {current_iteration_package} zdjęć."
                if source_total > 0:
                    step1_details = (
                        f"Wybrana paczka źródłowa: {source_total} zdjęć. "
                        f"Nowe dla projektu: {new_to_project_count}. "
                        f"Już zatwierdzone do treningu YOLO: {duplicate_count}."
                    )
                else:
                    step1_details = "E1 jest zamknięte. Jeśli chcesz pracować na nowej paczce, uruchom kolejną iterację."
        elif iter_image_count > 0:
            step1_state = "needs_attention"
            step1_summary = f"W folderze iteracji są już {iter_image_count} zdjęcia, ale E1 czeka na zatwierdzenie."
            step1_details = "Zejdź do panelu E1 i zatwierdź zestaw zdjęć, aby odblokować E2."
        elif master_pool_ready or plan_count > 0 or current_step == 1:
            step1_state = "in_progress" if current_step == 1 else "ready"
            step1_summary = "Przygotuj wybrany folder zdjęć i zatwierdź E1."
            if plan_count > 0:
                plan_project_overlap = int(self.current_ingest_plan.get("project_overlap_filenames", 0) or 0)
                plan_new_to_project = int(
                    self.current_ingest_plan.get(
                        "new_to_project_total",
                        max(0, plan_count - plan_project_overlap),
                    ) or 0
                )
                plan_skipped_approved = int(
                    self.current_ingest_plan.get("skipped_duplicate_filenames", self.current_ingest_plan.get("skipped_used", 0)) or 0
                )
                preview_pool_total = max(int(project_pool_total or 0), int((project_pool_total or 0) + plan_new_to_project))
                step1_details = (
                    f"Po zatwierdzeniu pula projektu będzie miała {preview_pool_total} zdjęć. "
                    f"Do tej iteracji wejdzie {plan_count} zdjęć, z czego {plan_new_to_project} będzie nowych dla projektu, "
                    f"a {plan_skipped_approved} było już zatwierdzonych do treningu YOLO."
                )
            elif master_pool_ready:
                step1_details = "Główna pula zdjęć jest ustawiona. Panel E1 pokaże listę wejściową oraz opcjonalną analizę puli."
            else:
                step1_details = "Najpierw wskaż główną pulę zdjęć dla projektu."
        else:
            step1_state = "ready"
            step1_summary = "E1 czeka na wskazanie głównej puli zdjęć."
            step1_details = "Po ustawieniu puli wizard zbuduje wybrany folder zdjęć dla iteracji."

        statuses.append(
            WizardStageStatus(
                key="step1",
                title="E1. Paczka wejściowa iteracji",
                state=step1_state,
                summary=step1_summary,
                details=step1_details,
                primary_label="",
                primary_command=None,
                body_mode="step1_ingest",
                body_visible=bool(not project_suspended and current_step == 1 and not step1_approved),
                is_current=bool(not project_suspended and current_step == 1),
            )
        )

        step2_vm = self._get_annotation_step2_view_model()
        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        try:
            step2_wizard_status = (
                dict(annotation_tab.get_campaign_step2_wizard_status() or {})
                if annotation_tab is not None and hasattr(annotation_tab, "get_campaign_step2_wizard_status")
                else {}
            )
        except Exception:
            step2_wizard_status = {}
        step2_title = "E2. Tor iteracji i przygotowanie Z2"
        if step2_vm is not None:
            primary_cta = getattr(step2_vm, "primary_cta", None)
            secondary_cta = getattr(step2_vm, "secondary_cta", None)
            step2_title = str(getattr(step2_vm, "title", "") or "").strip() or step2_title
            step2_state = str(getattr(step2_vm, "state", "") or "").strip() or "locked"
            step2_summary = str(getattr(step2_vm, "summary", "") or "").strip()
            step2_details = str(getattr(step2_vm, "details", "") or "").strip()
            step2_primary_label = str(getattr(primary_cta, "label", "") or "").strip()
            step2_primary_command = self._resolve_step2_wizard_action_command(
                str(getattr(primary_cta, "command_id", "") or "").strip(),
                context=dict(getattr(primary_cta, "command_context", {}) or {}),
            )
            step2_secondary_label = str(getattr(secondary_cta, "label", "") or "").strip()
            step2_secondary_command = self._resolve_step2_wizard_action_command(
                str(getattr(secondary_cta, "command_id", "") or "").strip(),
                context=dict(getattr(secondary_cta, "command_context", {}) or {}),
            )
            vm_current_step = int(getattr(step2_vm, "current_step", current_step) or current_step)
            step2_body_mode = "step2_route" if bool(not project_suspended and vm_current_step == 2) else ""
            step2_body_visible = bool(step2_body_mode)
        elif not iteration_target:
            step2_state = "in_progress" if current_step >= 2 else "locked"
            step2_summary = "Wybierz tor iteracji: tablice albo znaki."
            step2_details = (
                "To jedyna decyzja projektowa, którą wizard powinien podejmować we własnym zakresie. "
                "Dalsza praca odbywa się już w Z2, Z3 i Z4."
            )
            step2_primary_label = ""
            step2_primary_command = None
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = "step2_route"
            step2_body_visible = bool(not project_suspended and current_step == 2)
        else:
            step2_primary_label = self._get_step2_jump_button_text(iteration_target)
            step2_primary_command = self._step_goto_auto_annotation
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = "step2_route" if bool(not project_suspended and current_step == 2) else ""
            step2_body_visible = bool(step2_body_mode)

            step2_state = "locked"
            step2_summary = "E2 odblokuje się po zatwierdzeniu paczki wejściowej z E1."
            step2_details = "Najpierw domknij E1."

        if current_step == 2 and bool(step2_body_visible):
            step2_primary_label = ""
            step2_primary_command = None
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_summary = ""
            step2_details = ""

        step2_ready_for_approval = bool(step2_wizard_status.get("ready_for_approval"))
        if step2_ready_for_approval:
            approval_iteration_target = str(step2_wizard_status.get("approval_iteration_target", "") or "").strip().lower()
            next_stage_label = "E4" if approval_iteration_target == "plate" else "E3"
            step2_state = "ready"
            step2_summary = "Etap 2 jest gotowy do zamknięcia albo dalszej pracy w Z2."
            step2_details = (
                "Możesz wrócić do pracy w Z2 albo użyć badge'a „Zatwierdź etap”, "
                f"aby formalnie zamknąć E2 i odblokować {next_stage_label}."
            )
            step2_primary_label = "Wróć do pracy w Z2"
            step2_primary_command = self._step_goto_auto_annotation
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = "step2_route" if bool(not project_suspended and current_step == 2) else ""
            step2_body_visible = bool(step2_body_mode)

        if step2_state == "done":
            step2_primary_label = ""
            step2_primary_command = None
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = ""
            step2_body_visible = False

        statuses.append(
            WizardStageStatus(
                key="step2",
                title=step2_title,
                state=step2_state,
                summary=step2_summary,
                details=step2_details,
                primary_label=step2_primary_label,
                primary_command=step2_primary_command,
                secondary_label=step2_secondary_label,
                secondary_command=step2_secondary_command,
                badge_action_label=("Zatwierdź etap" if step2_ready_for_approval else ""),
                badge_action_command=(self._approve_step2_from_wizard if step2_ready_for_approval else None),
                body_mode=step2_body_mode,
                body_visible=step2_body_visible,
                is_current=bool(
                    not project_suspended
                    and (
                        current_step == 2
                        or plate_step4_reason in {"missing_plate_annotations", "insufficient_plate_annotations"}
                    )
                ),
            )
        )

        step3_vm = self._get_campaign_step3_view_model(
            current_step=current_step,
            iteration_target=iteration_target,
            project_completed=project_suspended,
            step2_status=step2_status,
            step3_status=step3_status,
            char_ready_source=char_ready_source,
            char_repair_guidance=char_repair_guidance,
            char_step4_gate=char_step4_gate,
        )
        step3_primary_cta = getattr(step3_vm, "primary_cta", None)
        step3_secondary_cta = getattr(step3_vm, "secondary_cta", None)
        step3_state = str(getattr(step3_vm, "state", "") or "").strip() or "locked"
        step3_summary = str(getattr(step3_vm, "summary", "") or "").strip()
        step3_details = str(getattr(step3_vm, "details", "") or "").strip()
        step3_primary_label = str(getattr(step3_primary_cta, "label", "") or "").strip()
        step3_primary_command = self._resolve_step3_wizard_action_command(
            str(getattr(step3_primary_cta, "command_id", "") or "").strip(),
            context=dict(getattr(step3_primary_cta, "command_context", {}) or {}),
        )
        step3_secondary_label = str(getattr(step3_secondary_cta, "label", "") or "").strip()
        step3_secondary_command = self._resolve_step3_wizard_action_command(
            str(getattr(step3_secondary_cta, "command_id", "") or "").strip(),
            context=dict(getattr(step3_secondary_cta, "command_context", {}) or {}),
        )

        if step3_state.lower() == "ready":
            step3_summary = "Etap 3 jest gotowy do zamknięcia albo dalszych poprawek."
            step3_details = (
                "Masz teraz trzy opcje: przygotować więcej tablic w Z2, wrócić do dopracowania znaków i eksportu w Z3 "
                "albo użyć badge'a „Zatwierdź etap”, aby formalnie zamknąć E3 i odblokować E4."
            )
            step3_primary_label = "Przygotuj więcej tablic w Z2"
            step3_primary_command = self._step_return_to_annotation_review
            step3_secondary_label = "Dopracuj znaki i eksport w Z3"
            step3_secondary_command = self._step_goto_characters

        statuses.append(
            WizardStageStatus(
                key="step3",
                title=str(getattr(step3_vm, "title", "") or "").strip() or "E3. Znaki i gold pack",
                state=step3_state,
                summary=step3_summary,
                details=step3_details,
                primary_label=step3_primary_label,
                primary_command=step3_primary_command,
                secondary_label=step3_secondary_label,
                secondary_command=step3_secondary_command,
                badge_action_label=(
                    "Zatwierdź etap"
                    if step3_state.lower() == "ready"
                    else ""
                ),
                badge_action_command=(
                    self._approve_step3_from_wizard
                    if step3_state.lower() == "ready"
                    else None
                ),
                body_mode=str(getattr(step3_vm, "body_mode", "") or "").strip(),
                body_visible=bool(getattr(step3_vm, "body_visible", False)),
                is_current=bool(not project_suspended and current_step == 3 and iteration_target == "char"),
            )
        )

        if project_completed:
            step4_state = "done"
            step4_summary = "Projekt został zakończony. Z4 pozostaje dostępne do przeglądu wyników i analiz."
            step4_details = "Jeśli chcesz uruchomić kolejną iterację w tym projekcie, wznów go z karty projektu."
            step4_secondary_label = "Wznów projekt"
            step4_secondary_command = self._toggle_project_completion
        elif project_paused:
            step4_state = "done"
            step4_summary = "Projekt został odłożony. Możesz wrócić do niego później bez utraty stanu iteracji."
            step4_details = "Po wznowieniu możesz wrócić do Z4 albo rozpocząć nową iterację w tym samym projekcie."
            step4_secondary_label = "Wznów projekt"
            step4_secondary_command = self._toggle_project_completion
        elif current_step >= 5:
            step4_state = "done"
            step4_summary = "Iteracja została domknięta. Możesz przejrzeć Z4 albo uruchomić nową iterację."
            step4_details = "Wizard nie prowadzi już treningu samodzielnie. Kieruje tylko do Z4 i zarządza stanem iteracji."
            step4_secondary_label = "Nowa iteracja"
            step4_secondary_command = self._advance_iteration
        elif step4_can_advance:
            step4_state = "done"
            step4_summary = "Trening tej iteracji jest zakończony. Możesz przejrzeć Z4 albo uruchomić nową iterację."
            step4_details = (
                "Wizard odtworzył zapisany stan zakończenia E4. "
                "Możesz wrócić do Z4, aby przejrzeć run treningu, albo od razu rozpocząć kolejną iterację."
            )
            step4_secondary_label = "Nowa iteracja"
            step4_secondary_command = self._advance_iteration
        elif plate_step4_blocked:
            step4_state = "needs_attention"
            if plate_step4_reason == "stale_plate_dataset":
                step4_summary = "Z4 wymaga przebudowy datasetu tablic."
                step4_details = str(plate_step4_gate.get("message") or "").strip() or (
                    "ApprovedSet projektu jest już większy niż ostatnio przygotowany dataset treningowy. "
                    "Przejdź do Z4 i przebuduj dataset w PZ1."
                )
            else:
                step4_summary = "Z4 czeka na uzupełnienie oznaczeń w Z2."
                step4_details = str(plate_step4_gate.get("message") or "").strip() or (
                    "W torze tablic potrzebujesz co najmniej 2 oznaczonych obrazów, zanim wejdziesz do Z4."
                )
            step4_secondary_label = ""
            step4_secondary_command = None
        elif current_step == 4:
            step4_state = "in_progress"
            step4_summary = "Budowa datasetu i trening odbywają się w Z4."
            if iteration_target == "plate":
                approved_images = int(plate_step4_gate.get("project_approved_images", 0) or 0)
                approved_plates = int(plate_step4_gate.get("project_approved_plates", 0) or 0)
                step4_details = (
                    "W torze tablic Z4 przygotuje dataset YOLO Pose i uruchomi trening modelu tablic. "
                    f"Źródłem jest zatwierdzony zbiór projektu: {approved_images} obraz(y), {approved_plates} tablic(e)."
                )
            else:
                step4_details = "W torze znaków Z4 zbuduje dataset znaków i uruchomi trening modelu YOLO Detect."
            step4_secondary_label = ""
            step4_secondary_command = None
        else:
            step4_state = "locked"
            if iteration_target == "plate":
                step4_summary = "Z4 odblokuje się po zakończeniu Z2 w torze tablic."
            elif iteration_target == "char":
                step4_summary = "Z4 odblokuje się po zakończeniu Z3 w torze znaków."
            else:
                step4_summary = "Najpierw wybierz tor iteracji i przejdź przez wcześniejsze etapy."
            step4_details = "Wizard pokaże Z4 jako ostatni etap, ale cała praca będzie się odbywać już w zakładce treningu."
            step4_secondary_label = ""
            step4_secondary_command = None

        if char_step4_blocked and not project_suspended and current_step < 5:
            step4_state = "needs_attention"
            step4_summary = "Z4 czeka na poprawny dataset znaków z Z3."
            gate_msg = str(char_step4_gate.get("message") or "").strip()
            repair_msg = str(char_repair_guidance.get("details") or "").strip()
            if gate_msg and repair_msg:
                step4_details = gate_msg + "\n\n" + repair_msg
            else:
                step4_details = gate_msg or repair_msg or (
                    "Wróć do Z3 i przygotuj dataset znaków gotowy do treningu."
                )
            step4_secondary_label = ""
            step4_secondary_command = None

        step4_primary_label = ""
        step4_primary_command = None
        if project_suspended or current_step >= 5 or (current_step == 4 and not step4_gate_blocked):
            step4_primary_label = "Otwórz Z4"
            step4_primary_command = self._step_goto_training
        elif plate_step4_blocked:
            plate_step4_reason = str(plate_step4_gate.get("reason") or "").strip().lower()
            if plate_step4_reason == "stale_plate_dataset":
                step4_primary_label = "Przebuduj dataset w Z4"
                step4_primary_command = self._step_goto_training_dataset
            else:
                step4_primary_label = "Wróć do Z2"
                step4_primary_command = self._step_return_to_annotation_review
        elif char_step4_blocked:
            step4_primary_label = str(char_repair_guidance.get("primary_label") or "Wróć do Z3")
            step4_primary_command = char_repair_guidance.get("primary_command") or self._step_goto_characters

        statuses.append(
            WizardStageStatus(
                key="step4",
                title="E4. Dataset i trening",
                state=step4_state,
                summary=step4_summary,
                details=step4_details,
                primary_label=step4_primary_label,
                primary_command=step4_primary_command,
                secondary_label=step4_secondary_label,
                secondary_command=step4_secondary_command,
                is_current=bool(not project_suspended and current_step >= 4),
            )
        )

        return [status for status in statuses if getattr(status, "key", "") != "project"]

    @staticmethod
    def _normalize_iteration_target(target: str | None) -> str:
        value = str(target or "").strip().lower()
        if value == "plate":
            return "plate"
        if value == "char":
            return "char"
        return ""

    def _get_iteration_target(self) -> str:
        return self._normalize_iteration_target(CAMPAIGN.get_iteration_target())

    def _get_last_iteration_target(self) -> str:
        try:
            return self._normalize_iteration_target(CAMPAIGN.get_last_iteration_target())
        except Exception:
            return ""

    def _should_default_first_iteration_step2_to_plate(
        self,
        *,
        current_step: int,
        step1_status: str,
        step2_status: str,
        step3_status: str,
        iteration_target: str,
    ) -> bool:
        if self._normalize_iteration_target(iteration_target):
            return False

        try:
            current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            current_iteration = 1
        if current_iteration != 1:
            return False

        if int(current_step or 1) != 2:
            return False
        if str(step1_status or "").strip().lower() != "approved":
            return False
        if str(step2_status or "").strip().lower() != "pending":
            return False
        if str(step3_status or "").strip().lower() != "pending":
            return False

        return True

    def _get_default_step2_iteration_target(
        self,
        *,
        current_step: int,
        step1_status: str,
        step2_status: str,
        step3_status: str,
        iteration_target: str,
    ) -> str:
        normalized_target = self._normalize_iteration_target(iteration_target)
        if normalized_target in {"plate", "char"}:
            return normalized_target

        if self._should_default_first_iteration_step2_to_plate(
            current_step=current_step,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
            iteration_target=normalized_target,
        ):
            return "plate"

        try:
            current_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
        except Exception:
            current_iteration = 1

        if (
            current_iteration > 1
            and int(current_step or 1) == 2
            and str(step1_status or "").strip().lower() == "approved"
            and str(step2_status or "").strip().lower() == "pending"
            and str(step3_status or "").strip().lower() == "pending"
        ):
            try:
                manifest = self._load_ingest_manifest_cached()
            except Exception:
                manifest = {}
            manifest_mode = str((manifest or {}).get("selection_mode", "") or "").strip().lower()
            if manifest_mode in {"stage_reuse", "pool_reuse", "iteration_reuse"}:
                return ""

        if (
            current_iteration > 1
            and int(current_step or 1) == 2
            and str(step1_status or "").strip().lower() == "approved"
            and str(step2_status or "").strip().lower() == "pending"
            and str(step3_status or "").strip().lower() == "pending"
        ):
            last_target = self._get_last_iteration_target()
            if last_target in {"plate", "char"}:
                return last_target

        return ""

    def _get_annotation_bootstrap_for_target(self, target: str) -> dict:
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return {}

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return {}

        try:
            bootstrap = annotation_tab._get_campaign_auto_annotation_bootstrap(target)
        except Exception as e:
            logger.debug(f"Nie udało się pobrac bootstrapu Z2 dla toru {target}: {e}")
            return {}

        return dict(bootstrap) if isinstance(bootstrap, dict) else {}

    def _get_annotation_step2_source_state(self, target: str) -> dict:
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return {}

        cache_key = (
            str(CAMPAIGN.get_active_project_name() or "").strip(),
            int(CAMPAIGN.get_current_iteration_num() or 1),
            int(CAMPAIGN.get_current_step() or 1),
            str(CAMPAIGN.get_step2_status() or "").strip().lower(),
            str(CAMPAIGN.get_step3_status() or "").strip().lower(),
            target,
        )
        state_cache = self._get_dashboard_cache_bucket("step2_source_states")
        cached = state_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return {}

        getter = getattr(annotation_tab, "get_campaign_step2_source_state", None)
        if not callable(getter):
            return {}

        source_started = perf_counter()
        try:
            source_state = getter(iteration_target=target)
        except Exception as e:
            logger.debug(f"Nie udało się pobrac stanu źródła E2 z Z2 dla toru {target}: {e}")
            return {}

        normalized_state = dict(source_state) if isinstance(source_state, dict) else {}
        state_cache[cache_key] = dict(normalized_state)
        self._log_perf(
            f"step2_source_state[{target}]",
            source_started,
            threshold_ms=20.0,
            extra=f"ready={bool(normalized_state.get('ready'))}, has_source={bool(normalized_state.get('has_source'))}",
        )
        return normalized_state

    def _get_plate_approved_set_stats(self) -> dict:
        try:
            manifest_path = CAMPAIGN.get_plate_approved_set_path()
        except Exception:
            manifest_path = None

        cache = getattr(self, "_dashboard_perf_cache", {})
        stats_cache = cache.get("approved_stats", {}) if isinstance(cache, dict) else {}
        cache_key = ("plate_approved_stats", self._build_cache_token_for_path(manifest_path))
        cached = stats_cache.get(cache_key) if isinstance(stats_cache, dict) else None
        if isinstance(cached, dict):
            return dict(cached)

        try:
            stats = CAMPAIGN.get_plate_approved_set_stats()
        except Exception as e:
            logger.debug(f"Nie udało się pobrac statystyk ApprovedSet tablic: {e}")
            return {}
        result = dict(stats) if isinstance(stats, dict) else {}
        if isinstance(stats_cache, dict):
            if len(stats_cache) > 64:
                stats_cache.clear()
            stats_cache[cache_key] = dict(result)
        return result

    def _resolve_step2_wizard_action_command(self, action_id: str, *, context: dict | None = None):
        normalized = str(action_id or "").strip().lower()
        if not normalized:
            return None

        if normalized == "choose_iteration_target":
            target = self._normalize_iteration_target((context or {}).get("target"))
            if target not in {"plate", "char"}:
                return None
            return lambda t=target: self._step2_choose_iteration_target(t)
        if normalized == "open_z2":
            return self._step_goto_auto_annotation
        if normalized == "return_to_z2":
            return self._step_return_to_annotation_review
        if normalized == "continue_z3":
            return lambda ctx=dict(context or {}): self._step_continue_characters_from_ready_source(ctx)
        return None

    def _approve_step2_from_wizard(self):
        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return

        try:
            ensure_context = getattr(annotation_tab, "ensure_campaign_context_ready_for_active_project", None)
            if callable(ensure_context):
                ensure_context(force=False)
        except Exception:
            pass

        try:
            wizard_status_getter = getattr(annotation_tab, "get_campaign_step2_wizard_status", None)
            wizard_status = dict(wizard_status_getter() or {}) if callable(wizard_status_getter) else {}
        except Exception:
            wizard_status = {}

        approval_action = str(wizard_status.get("approval_action", "") or "").strip().lower()
        approval_iteration_target = str(wizard_status.get("approval_iteration_target", "") or "").strip().lower()
        if approval_action == "continue_characters":
            try:
                annotation_tab._continue_characters_from_effective_source()
            except Exception as e:
                logger.error(f"Nie udało się zatwierdzić E2 z badge wizarda (char source): {e}")
            return

        try:
            approval_context_getter = getattr(annotation_tab, "_get_campaign_step2_approval_context", None)
            approval_context = dict(approval_context_getter() or {}) if callable(approval_context_getter) else {}
        except Exception:
            approval_context = {}
        approval_run_dir = approval_context.get("run_dir")

        if approval_iteration_target == "plate" and approval_run_dir is None:
            try:
                CAMPAIGN.approve_step2()
                CAMPAIGN.set_current_step(4)
                self.request_wizard_stage_focus(step_num=4)
                self._refresh_dashboard()
                self.app.open_controlled_tab("campaign")
                self.app.update_campaign_tab_access()
                self.app.update_status(
                    "E2 zostało zatwierdzone na podstawie zatwierdzonego zbioru projektu. Etap E4 jest już odblokowany.",
                    "info",
                )
            except Exception as e:
                logger.error(f"Nie udało się zatwierdzić E2 z badge wizarda (project approved set): {e}")
            return

        try:
            annotation_tab._approve_annotation_stage()
        except Exception as e:
            logger.error(f"Nie udało się zatwierdzić E2 z badge wizarda: {e}")

    def _get_annotation_step2_view_model(self):
        cache_key = (
            str(CAMPAIGN.get_active_project_name() or "").strip(),
            int(CAMPAIGN.get_current_iteration_num() or 1),
            int(CAMPAIGN.get_current_step() or 1),
            str(CAMPAIGN.get_iteration_target() or "").strip().lower(),
            str(CAMPAIGN.get_step1_status() or "").strip().lower(),
            str(CAMPAIGN.get_step2_status() or "").strip().lower(),
            str(CAMPAIGN.get_step3_status() or "").strip().lower(),
        )
        vm_cache = self._get_dashboard_cache_bucket("step2_view_models")
        cached = vm_cache.get(cache_key)
        if isinstance(cached, Step2ViewModel):
            return cached

        current_step = int(CAMPAIGN.get_current_step() or 1)
        iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        step1_status = str(CAMPAIGN.get_step1_status() or "").strip().lower()
        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
        step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower()
        if (
            current_step == 2
            and not iteration_target
            and step1_status == "approved"
            and step2_status == "pending"
            and step3_status == "pending"
        ):
            lightweight_vm = Step2ViewModel(
                stage_key="step2",
                iteration_target="",
                current_step=current_step,
                step2_status=step2_status,
                state="in_progress",
                title="E2. Wybierz tor iteracji",
                summary="",
                details="",
                route_hint="Wybierz tor tej iteracji.",
                route_lock_reason="",
                route_choices=[],
                primary_cta=None,
                secondary_cta=None,
            )
            vm_cache[cache_key] = lightweight_vm
            return lightweight_vm

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return None

        getter = getattr(annotation_tab, "get_campaign_step2_view_model", None)
        if not callable(getter):
            return None

        vm_started = perf_counter()
        try:
            view_model = getter()
        except Exception as e:
            logger.debug(f"Nie udało się pobrac modelu widoku E2 z Z2: {e}")
            return None

        if isinstance(view_model, Step2ViewModel):
            vm_cache[cache_key] = view_model

        self._log_perf(
            "step2_view_model",
            vm_started,
            threshold_ms=20.0,
            extra=f"target={str(getattr(view_model, 'iteration_target', '') or '').strip() or '-'}",
        )
        return view_model

    def _resolve_step3_wizard_action_command(self, action_id: str, *, context: dict | None = None):
        normalized = str(action_id or "").strip().lower()
        if not normalized:
            return None

        if normalized == "approve_step3":
            return self._approve_step3_from_wizard
        if normalized == "open_z3":
            return self._step_goto_characters
        if normalized == "return_to_z2":
            return self._step_return_to_annotation_review
        if normalized == "continue_z3":
            return lambda ctx=dict(context or {}): self._step_continue_characters_from_ready_source(ctx)
        if normalized == "open_z3_detect":
            return lambda ctx=dict(context or {}): self._step_goto_characters_detect(ctx)
        return None

    def _approve_step3_from_wizard(self):
        if not CAMPAIGN.get_active_project_name():
            return
        if self._get_iteration_target() != "char":
            return

        char_tab = self.app.tabs.get("characters") if getattr(self.app, "tabs", None) else None
        if char_tab is None:
            return

        readiness = {}
        try:
            getter = getattr(char_tab, "_get_campaign_step3_training_readiness", None)
            if callable(getter):
                readiness = dict(getter() or {})
        except Exception as e:
            logger.debug(f"Nie udało się sprawdzic gotowosci zatwierdzenia E3: {e}")
            readiness = {}

        has_outputs = False
        try:
            checker = getattr(char_tab, "_has_any_step3_export_outputs", None)
            if callable(checker):
                has_outputs = bool(checker())
        except Exception as e:
            logger.debug(f"Nie udało się sprawdzic artefaktow E3: {e}")
            has_outputs = False

        if not (has_outputs and bool(readiness.get("ok"))):
            message = str(readiness.get("message") or "").strip() or (
                "E3 nie jest jeszcze gotowe do zatwierdzenia. Wróć do Z3 i przygotuj poprawny dataset znaków."
            )
            try:
                self.app.update_status(message, "warning")
            except Exception:
                pass
            try:
                self.app.themed_info(
                    "E3 jeszcze niegotowe",
                    message,
                    parent=self.frame,
                    tone="warning",
                )
            except Exception:
                pass
            return

        CAMPAIGN.approve_step3()
        if int(CAMPAIGN.get_current_step() or 3) < 4:
            CAMPAIGN.set_current_step(4)

        try:
            self.request_wizard_stage_focus(step_num=4)
        except Exception:
            pass

        self._rebuild_roadmap_ui()
        self._refresh_dashboard()
        self.app.update_campaign_tab_access()

        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass

        try:
            self.app.update_status(
                "E3 zostało zatwierdzone. Etap 4 jest odblokowany i gotowy do uruchomienia z wizarda.",
                "success",
            )
        except Exception:
            pass

    def _get_campaign_step3_view_model(
        self,
        *,
        current_step: int,
        iteration_target: str,
        project_completed: bool,
        step2_status: str,
        step3_status: str,
        char_ready_source: dict | None = None,
        char_repair_guidance: dict | None = None,
        char_step4_gate: dict | None = None,
    ) -> Step3ViewModel:
        normalized_target = self._normalize_iteration_target(iteration_target)
        normalized_step2_status = str(step2_status or "").strip().lower()
        normalized_step3_status = str(step3_status or "").strip().lower()
        ready_source = dict(char_ready_source or {})
        repair_guidance = dict(char_repair_guidance or {})
        step4_gate = dict(char_step4_gate or {})
        has_ready_char_dataset = bool(
            normalized_target == "char"
            and bool(step4_gate.get("ok"))
            and (
                str(step4_gate.get("ready_dataset") or "").strip()
                or str(step4_gate.get("dataset_hint") or "").strip()
                or int(step4_gate.get("train_images", 0) or 0) > 0
                or int(step4_gate.get("val_images", 0) or 0) > 0
            )
        )
        can_approve_step3 = bool(
            normalized_target == "char"
            and (
                normalized_step3_status == "ready"
                or (int(current_step or 0) == 3 and has_ready_char_dataset)
            )
        )
        char_step4_blocked = bool(
            normalized_target == "char"
            and (int(current_step or 0) >= 4 or normalized_step3_status == "approved")
            and not bool(step4_gate.get("ok", True))
        )

        vm = Step3ViewModel(
            stage_key="step3",
            iteration_target=normalized_target,
            current_step=int(current_step or 0),
            step3_status=normalized_step3_status or "pending",
            state="locked",
            title="E3. Znaki i gold pack",
            summary="Z3 odblokuje się po przygotowaniu i zatwierdzeniu tablic w Z2.",
            details="Najpierw domknij E2.",
            body_mode="",
            body_visible=False,
            primary_cta=None,
            secondary_cta=None,
        )

        if normalized_target == "plate":
            return Step3ViewModel(
                stage_key="step3",
                iteration_target=normalized_target,
                current_step=int(current_step or 0),
                step3_status=normalized_step3_status or "pending",
                state="skipped",
                title="E3. Znaki i gold pack",
                summary="Tor tablic pomija Z3.",
                details="Po zatwierdzeniu Z2 projekt przechodzi od razu do Z4.",
            )

        if not normalized_target:
            return Step3ViewModel(
                stage_key="step3",
                iteration_target=normalized_target,
                current_step=int(current_step or 0),
                step3_status=normalized_step3_status or "pending",
                state="locked",
                title="E3. Znaki i gold pack",
                summary="Najpierw wybierz tor iteracji w E2.",
                details="Z3 dotyczy wyłącznie toru znaków.",
            )

        primary_cta = Step2CtaViewModel(
            label="Otwórz Z3",
            command_id=("continue_z3" if ready_source else "open_z3"),
            command_context=(dict(ready_source) if ready_source else {}),
        )
        secondary_cta = None
        state = "locked"
        summary = "Z3 odblokuje się po przygotowaniu i zatwierdzeniu tablic w Z2."
        details = "Najpierw domknij E2."
        body_mode = ""
        body_visible = False

        if can_approve_step3:
            state = "ready"
            summary = "Etap 3 jest gotowy do zamknięcia albo dalszych poprawek."
            details = (
                "Masz teraz trzy opcje: przygotować więcej tablic w Z2, wrócić do dopracowania znaków i eksportu w Z3 "
                "albo użyć badge'a „Zatwierdź etap”, aby formalnie zamknąć E3 i odblokować E4."
            )
            primary_cta = Step2CtaViewModel(
                label="Przygotuj więcej tablic w Z2",
                command_id="return_to_z2",
            )
            secondary_cta = Step2CtaViewModel(
                label="Dopracuj znaki i eksport w Z3",
                command_id=("continue_z3" if ready_source else "open_z3"),
                command_context=(dict(ready_source) if ready_source else {}),
                tone="secondary",
            )
        elif normalized_step3_status == "needs_rework":
            primary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else "return_to_z2"
            primary_context = dict(ready_source or {}) if primary_command_id == "open_z3_detect" else {}
            primary_cta = Step2CtaViewModel(
                label=str(repair_guidance.get("primary_label") or "Przygotuj więcej tablic w Z2"),
                command_id=primary_command_id,
                command_context=primary_context,
            )
            secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
            secondary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else ""
            secondary_context = dict(ready_source or {})
            if secondary_label:
                if secondary_label.lower().startswith("przygotuj więcej tablic"):
                    secondary_command_id = "return_to_z2"
                    secondary_context = {}
                secondary_cta = Step2CtaViewModel(
                    label=secondary_label,
                    command_id=secondary_command_id,
                    command_context=secondary_context,
                )
            state = "needs_attention"
            summary = "Paczka znaków wymaga korekty przed treningiem."
            details = str(repair_guidance.get("details") or "Najpierw przygotuj poprawna sciezke naprawy dla toru znaków.")
            body_mode = "step3_rework"
            body_visible = not bool(project_completed)
        elif normalized_step3_status == "approved" or int(current_step or 0) > 3:
            state = "done"
            summary = "Z3 zostało zatwierdzone. Dataset znaków jest gotowy do Z4."
            details = "Możesz wrócić do Z3 albo przejść dalej do budowy datasetu i treningu."
        if (normalized_step3_status == "approved" or int(current_step or 0) > 3) and char_step4_blocked:
            primary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else "return_to_z2"
            primary_context = dict(ready_source or {}) if primary_command_id == "open_z3_detect" else {}
            primary_cta = Step2CtaViewModel(
                label=str(repair_guidance.get("primary_label") or "Przygotuj więcej tablic w Z2"),
                command_id=primary_command_id,
                command_context=primary_context,
            )
            secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
            secondary_command_id = "open_z3_detect" if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair" else ""
            secondary_context = dict(ready_source or {})
            if secondary_label:
                if secondary_label.lower().startswith("przygotuj więcej tablic"):
                    secondary_command_id = "return_to_z2"
                    secondary_context = {}
                secondary_cta = Step2CtaViewModel(
                    label=secondary_label,
                    command_id=secondary_command_id,
                    command_context=secondary_context,
                )
            state = "needs_attention"
            summary = "Z3 jest formalnie zatwierdzone, ale dataset znaków nadal wymaga poprawy."
            gate_msg = str(step4_gate.get("message") or "").strip()
            repair_msg = str(repair_guidance.get("details") or "").strip()
            if gate_msg and repair_msg:
                details = gate_msg + "\n\n" + repair_msg
            else:
                details = gate_msg or repair_msg or "Wróć do Z3 i popraw dataset znaków, zanim przejdziesz do Z4."
            body_mode = ""
            body_visible = False
        elif int(current_step or 0) == 3 and not can_approve_step3:
            if ready_source:
                state = "in_progress"
                summary = "Źródło tablic jest gotowe, ale etap E3 czeka jeszcze na ponowne wejście do Z3."
                details = (
                    "Uruchom step3-p1, aby wrócić do Z3 i kontynuować wycinanie tablic, OCR oraz korektę znaków. "
                    "Jeśli chcesz, możesz też nadal powiększać zbiór tablic w Z2."
                )
                primary_cta = Step2CtaViewModel(
                    label="Kontynuuj pracę nad znakami (Z3)",
                    command_id="continue_z3",
                    command_context=dict(ready_source),
                )
                secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
                secondary_command_id = (
                    "open_z3_detect"
                    if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair"
                    else ""
                )
                secondary_context = dict(ready_source or {})
                if secondary_label:
                    if secondary_label.lower().startswith("przygotuj więcej tablic"):
                        secondary_command_id = "return_to_z2"
                        secondary_context = {}
                    secondary_cta = Step2CtaViewModel(
                        label=secondary_label,
                        command_id=secondary_command_id,
                        command_context=secondary_context,
                    )
            elif str(repair_guidance.get("primary_label") or "").strip():
                primary_command_id = (
                    "open_z3_detect"
                    if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair"
                    else "return_to_z2"
                )
                primary_context = dict(ready_source or {}) if primary_command_id == "open_z3_detect" else {}
                primary_cta = Step2CtaViewModel(
                    label=str(repair_guidance.get("primary_label") or "Przygotuj więcej tablic w Z2"),
                    command_id=primary_command_id,
                    command_context=primary_context,
                )
                secondary_label = str(repair_guidance.get("secondary_label") or "").strip()
                secondary_command_id = (
                    "open_z3_detect"
                    if str(repair_guidance.get("mode") or "").strip().lower() == "z3_pz2_repair"
                    else ""
                )
                secondary_context = dict(ready_source or {})
                if secondary_label:
                    if secondary_label.lower().startswith("przygotuj więcej tablic"):
                        secondary_command_id = "return_to_z2"
                        secondary_context = {}
                    secondary_cta = Step2CtaViewModel(
                        label=secondary_label,
                        command_id=secondary_command_id,
                        command_context=secondary_context,
                    )
                state = "needs_attention"
                summary = "Źródło tablic dla toru znaków nadal wymaga uwagi."
                details = str(
                    repair_guidance.get("details")
                    or "Najpierw przygotuj więcej tablic w Z2 albo wróć do Z3, jeśli źródło jest już wystarczające."
                )
            else:
                state = "in_progress"
                summary = "Pracujesz teraz w Z3: wycinanie tablic, OCR, korekty i eksport."
                details = "Wizard pokazuje tylko stan etapu. Cała praca dzieje się w zakładce Znaki."
        elif normalized_step2_status == "approved" or ready_source:
            state = "ready"
            summary = "Z3 jest gotowe do uruchomienia."
            details = "Źródła tablic są już przygotowane i możesz zacząć pracę nad znakami."

        if normalized_target == "char" and state in {"in_progress", "ready"} and not can_approve_step3:
            char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
            if char_model_path and Path(char_model_path).exists():
                if state == "in_progress":
                    details = (
                        "Wizard pokazuje tylko stan etapu. Cala praca dzieje się w zakładce Znaki, "
                        "a aktywny model znaków projektu jest tam podstawiany automatycznie."
                    )
                elif state == "ready":
                    details = (
                        "Źródła tablic są już przygotowane i możesz zacząć pracę nad znakami. "
                        "Po wejsciu do Z3 model znaków projektu będzie już ustawiony automatycznie."
                    )

        if normalized_target == "char" and int(current_step or 0) < 3 and normalized_step2_status != "approved":
            state = "locked"
            summary = "Z3 odblokuje się po decyzji i zatwierdzeniu E2."
            details = "Najpierw skorzystaj z prowadzenia w E2 i przygotuj albo zatwierdz tablice dla toru znaków."
            body_mode = ""
            body_visible = False
            primary_cta = None
            secondary_cta = None

        if state == "done" and not bool(char_step4_blocked):
            primary_cta = None
            secondary_cta = None
            body_mode = ""
            body_visible = False

        if (
            normalized_target == "char"
            and not bool(char_step4_blocked)
            and (int(current_step or 0) >= 4 or normalized_step3_status == "approved")
        ):
            state = "done"
            primary_cta = None
            secondary_cta = None
            body_mode = ""
            body_visible = False

        return Step3ViewModel(
            stage_key="step3",
            iteration_target=normalized_target,
            current_step=int(current_step or 0),
            step3_status=normalized_step3_status or "pending",
            state=state,
            title="E3. Znaki i gold pack",
            summary=summary,
            details=details,
            body_mode=body_mode,
            body_visible=bool(body_visible),
            primary_cta=primary_cta,
            secondary_cta=secondary_cta,
        )

    def _get_char_route_ready_source(self) -> dict:
        source_state = self._get_char_route_source_state()
        if not bool(source_state.get("ready")):
            return {}
        bootstrap = source_state.get("bootstrap")
        return dict(bootstrap) if isinstance(bootstrap, dict) else {}

    def _get_char_training_split_preview(self, total_plates: int) -> dict:
        total = max(0, int(total_plates or 0))
        train_pct = 80.0
        val_pct = 10.0
        test_pct = 10.0

        try:
            char_tab = self.app.tabs.get("characters") if getattr(self.app, "tabs", None) else None
            if char_tab is not None and hasattr(char_tab, "_get_gold_export_split_percentages"):
                train_pct, val_pct, test_pct = char_tab._get_gold_export_split_percentages()
        except Exception:
            train_pct, val_pct, test_pct = 80.0, 10.0, 10.0

        train_count = int(total * (float(train_pct) / 100.0))
        val_count = int(total * (float(val_pct) / 100.0))
        test_count = max(0, total - train_count - val_count)

        return {
            "total_plates": total,
            "train_pct": float(train_pct),
            "val_pct": float(val_pct),
            "test_pct": float(test_pct),
            "train": int(train_count),
            "val": int(val_count),
            "test": int(test_count),
            "ok": bool(total > 0 and train_count > 0 and val_count > 0),
        }

    def _detect_campaign_char_ready_dataset_state(self) -> dict:
        result = {
            "ok": False,
            "reason": "missing_char_dataset",
            "message": "",
            "ready_dataset": "",
            "dataset_hint": "",
            "train_images": 0,
            "val_images": 0,
            "test_images": 0,
            "validation_message": "",
        }

        try:
            datasets_dir = CAMPAIGN.get_dir("datasets")
        except Exception:
            datasets_dir = None
        if datasets_dir is None or not Path(datasets_dir).exists():
            return result

        try:
            candidates = sorted(
                [
                    path for path in Path(datasets_dir).iterdir()
                    if path.is_dir() and (path / "data.yaml").exists()
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return result

        for dataset_dir in candidates:
            counts = {"train": 0, "val": 0, "test": 0}
            labels_ok = True
            for split_name in ("train", "val", "test"):
                images_dir = dataset_dir / "images" / split_name
                labels_dir = dataset_dir / "labels" / split_name
                if split_name in {"train", "val"} and not labels_dir.exists():
                    labels_ok = False
                if not images_dir.exists() or not images_dir.is_dir():
                    continue
                try:
                    counts[split_name] = sum(
                        1 for path in images_dir.iterdir()
                        if path.is_file() and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
                    )
                except Exception:
                    counts[split_name] = 0

            if labels_ok and counts["train"] > 0 and counts["val"] > 0:
                dataset_str = str(dataset_dir)
                result.update(
                    ok=True,
                    reason="",
                    ready_dataset=dataset_str,
                    dataset_hint=dataset_str,
                    train_images=int(counts["train"]),
                    val_images=int(counts["val"]),
                    test_images=int(counts["test"]),
                )
                return result

        return result

    def _get_char_repair_guidance(self, source_state: dict | None = None) -> dict:
        state = dict(source_state or self._get_char_route_source_state() or {})
        images_with_plates = int(state.get("images_with_plates", 0) or 0)
        total_plates = int(state.get("total_plates", 0) or 0)
        run_name = str(state.get("run_name", "") or "").strip()
        split_preview = self._get_char_training_split_preview(total_plates)
        source_context = dict(state.get("bootstrap") or {})

        result = {
            "mode": "z2_more_tables",
            "primary_label": "Przygotuj więcej tablic w Z2",
            "primary_command": self._step_return_to_annotation_review,
            "secondary_label": "",
            "secondary_command": None,
            "details": "",
            "split_preview": split_preview,
            "images_with_plates": images_with_plates,
            "total_plates": total_plates,
        }

        if split_preview.get("ok"):
            result.update(
                mode="z3_pz2_repair",
                primary_label="Popraw anotacje znaków w Z3/PZ2",
                primary_command=(lambda ctx=dict(source_context): self._step_goto_characters_detect(ctx)),
                secondary_label="Przygotuj więcej tablic w Z2",
                secondary_command=self._step_return_to_annotation_review,
            )
            result["details"] = (
                f"Źródło {run_name} zawiera {total_plates} tablic na {images_with_plates} oznaczonych obrazach. "
                f"To wystarczy, aby po poprawie znaków w Z3/PZ2 przygotować około "
                f"train={split_preview['train']}, val={split_preview['val']}, test={split_preview['test']}."
                if run_name
                else (
                    f"Biezace źródło zawiera {total_plates} tablic na {images_with_plates} oznaczonych obrazach. "
                    f"To wystarczy, aby po poprawie znaków w Z3/PZ2 przygotować około "
                    f"train={split_preview['train']}, val={split_preview['val']}, test={split_preview['test']}."
                )
            )
            return result

        result["details"] = (
            f"Źródło {run_name} zawiera tylko {total_plates} tablic na {images_with_plates} oznaczonych obrazach. "
            f"Przy rozkladzie {split_preview['train_pct']:.0f}/{split_preview['val_pct']:.0f}/{split_preview['test_pct']:.0f} "
            f"dostaniesz tylko train={split_preview['train']}, val={split_preview['val']}, test={split_preview['test']}. "
            "To znaczy, ze sama poprawa znaków w Z3/PZ2 nie wystarczy i najpierw trzeba przygotować więcej tablic w Z2."
            if run_name
            else (
                f"Biezace źródło zawiera tylko {total_plates} tablic na {images_with_plates} oznaczonych obrazach. "
                f"Przy rozkladzie {split_preview['train_pct']:.0f}/{split_preview['val_pct']:.0f}/{split_preview['test_pct']:.0f} "
                f"dostaniesz tylko train={split_preview['train']}, val={split_preview['val']}, test={split_preview['test']}. "
                "To znaczy, ze sama poprawa znaków w Z3/PZ2 nie wystarczy i najpierw trzeba przygotować więcej tablic w Z2."
            )
        )
        return result

    def _get_char_route_source_state(self) -> dict:
        result = {
            "ready": False,
            "has_source": False,
            "needs_more_tables": False,
            "images_with_plates": 0,
            "total_plates": 0,
            "restore_run_dir": None,
            "run_name": "",
            "bootstrap": {},
        }
        source_state = self._get_annotation_step2_source_state("char")
        if not source_state:
            return result
        result.update(source_state)
        return result

    def _get_plate_route_ready_source(self) -> dict:
        if CAMPAIGN.get_step2_status() == "generated":
            return {}
        source_state = self._get_annotation_step2_source_state("plate")
        bootstrap = source_state.get("bootstrap")
        return dict(bootstrap) if isinstance(bootstrap, dict) else {}

    def _get_step2_staging_run_dir(self) -> Path | None:
        run_dir = str(CAMPAIGN.get_step2_staging_run() or "").strip()
        if not run_dir:
            return None

        try:
            candidate = Path(run_dir)
        except Exception:
            return None

        if not candidate.exists() or not candidate.is_dir():
            return None
        if not (candidate / "annotations.xml").exists():
            return None
        return candidate

    @staticmethod
    def _count_step2_images_in_dir(directory: Path | None) -> int:
        if directory is None:
            return 0
        try:
            return sum(
                1
                for image_path in Path(directory).iterdir()
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            )
        except Exception:
            return 0

    def _get_latest_project_dataset_hint(self) -> Path | None:
        datasets_dir = CAMPAIGN.get_dir("datasets")
        if datasets_dir is None:
            return None

        datasets_dir = Path(datasets_dir)
        if not datasets_dir.exists() or not datasets_dir.is_dir():
            return None

        candidates = []
        try:
            for child in datasets_dir.iterdir():
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    try:
                        has_content = any(child.iterdir())
                    except Exception:
                        has_content = False
                    if not has_content:
                        continue
                elif not child.is_file():
                    continue
                candidates.append(child)
        except Exception:
            return None

        if not candidates:
            return None

        try:
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except Exception:
            candidates.sort(key=lambda path: path.name.lower(), reverse=True)
        return candidates[0]

    @staticmethod
    def _describe_step2_bootstrap_source(source_key: str | None = None) -> str:
        key = str(source_key or "").strip().lower()
        labels = {
            "manual_source_run": "ręczne tablice dla tej paczki",
            "reused_manual_source_run": "ręczne tablice z poprzedniej iteracji",
            "reused_training_source_run": "run wykorzystany w poprzednim treningu",
            "reused_iteration_run": "run odzyskany z poprzedniej iteracji",
            "latest_approved_run": "ostatni zatwierdzony run projektu",
            "project_imported_manual_source": "run zaimportowany na starcie projektu",
            "project_imported_images": "obrazy wskazane przy starcie projektu",
            "stage_current_iteration": "stage tej iteracji",
            "stage_previous_iteration": "stage poprzedniej iteracji",
            "raw": "surowe obrazy z E1",
        }
        return labels.get(key, "zasob wykryty automatycznie")

    def _collect_step2_asset_rows(self, *, current_target: str = "") -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add_row(label: str, value: str) -> None:
            clean_label = str(label or "").strip()
            clean_value = str(value or "").strip()
            if not clean_label or not clean_value:
                return
            key = (clean_label, clean_value)
            if key in seen:
                return
            seen.add(key)
            rows.append(key)

        current_target = self._normalize_iteration_target(current_target)
        iter_dir = CAMPAIGN.get_iteration_raw_dir()
        image_count = self._count_step2_images_in_dir(iter_dir)
        if iter_dir is not None:
            iter_name = Path(iter_dir).name
            add_row("E1", f"{iter_name} | {image_count} obrazów" if image_count else f"{iter_name} | brak obrazów")

        staging_run = self._get_step2_staging_run_dir()
        if staging_run is not None:
            add_row("Aktywny Z2", staging_run.name)

        if current_target in {"", "plate"}:
            plate_ready_source = self._get_plate_route_ready_source()
            if plate_ready_source:
                run_dir = plate_ready_source.get("restore_run_dir")
                if run_dir is not None:
                    add_row(
                        "Tor A",
                        f"{Path(run_dir).name} | {self._describe_step2_bootstrap_source(plate_ready_source.get('input_source'))}",
                    )

        if current_target in {"", "char"}:
            char_ready_source = self._get_char_route_ready_source()
            if char_ready_source:
                run_dir = char_ready_source.get("restore_run_dir")
                if run_dir is not None:
                    add_row("Tor B", f"{Path(run_dir).name} | gotowe ręczne tablice")

        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        if plate_model_path and Path(plate_model_path).exists():
            plate_identity = self._get_model_identity_label(plate_model_path)
            plate_text = Path(plate_model_path).name
            if plate_identity:
                plate_text += f" | {plate_identity}"
            add_row("Model tablic", plate_text)

        dataset_hint = self._get_latest_project_dataset_hint()
        if dataset_hint is not None:
            add_row("Dataset", dataset_hint.name)

        return rows

    def _render_step2_asset_summary(self, frame, *, current_target: str = ""):
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        rows = self._collect_step2_asset_rows(current_target=current_target)
        if not rows:
            return

        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        panel_bg = blend_hex_colors(card_bg, palette.get("panel_alt", "#2d2d30"), 0.35)
        shell = tk.Frame(
            frame,
            bg=panel_bg,
            bd=0,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
        )
        shell.pack(fill=tk.X, pady=(8, 0))

        inner = tk.Frame(shell, bg=panel_bg)
        inner.pack(fill=tk.X, padx=12, pady=10)

        tk.Label(
            inner,
            text="Kontekst tej iteracji",
            fg=palette.get("fg", "#f3f3f3"),
            bg=panel_bg,
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W, fill=tk.X)

        grid = tk.Frame(inner, bg=panel_bg)
        grid.pack(fill=tk.X, pady=(6, 0))
        grid.grid_columnconfigure(0, minsize=110)
        grid.grid_columnconfigure(1, weight=1)

        for row_idx, (label, value) in enumerate(rows):
            tk.Label(
                grid,
                text=f"{label}:",
                fg=palette.get("muted", "#c7c7c7"),
                bg=panel_bg,
                anchor="nw",
                justify=tk.LEFT,
                font=("Segoe UI", 9, "bold"),
            ).grid(row=row_idx, column=0, sticky="nw", padx=(0, 8), pady=(0, 4))
            tk.Label(
                grid,
                text=value,
                fg=palette.get("fg", "#f3f3f3"),
                bg=panel_bg,
                anchor="nw",
                justify=tk.LEFT,
                wraplength=400,
            ).grid(row=row_idx, column=1, sticky="nw", pady=(0, 4))


    def _get_step2_jump_button_text(self, target: str) -> str:
        target = self._normalize_iteration_target(target)

        if target == "plate":
            if CAMPAIGN.get_step2_status() == "generated":
                return "Sprawdź i zatwierdź tablice (Z2)"
            plate_bootstrap = self._get_annotation_bootstrap_for_target("plate")
            if not bool(plate_bootstrap.get("manual_template", True)):
                return "Przygotuj tablice na modelu projektu (Z2)"
            return "Przejdź do anotacji tablic"

        if target == "char":
            if CAMPAIGN.get_step2_status() == "generated":
                return "Sprawdz i zatwierdz tablice (Z2)"
            if self._get_char_route_ready_source():
                return "Kontynuuj pracę nad znakami (Z3)"
            plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
            if plate_model_path and Path(plate_model_path).exists():
                return "Przygotuj tablice na modelu projektu (Z2)"
            return "Przejdź do anotacji tablic"

        return "Najpierw wybierz tor"

    @staticmethod
    def _iteration_target_label(target: str) -> str:
        if target == "plate":
            return "tor tablic"
        if target == "char":
            return "tor znaków"
        return "nie wybrano toru"

    def _step2_route_button_label(self, route: str, *, current_target: str = "", last_target: str = "") -> str:
        route = self._normalize_iteration_target(route)
        current_target = self._normalize_iteration_target(current_target)
        last_target = self._normalize_iteration_target(last_target)

        if route == "plate":
            if not current_target and last_target == "plate":
                return "A. Tablice (kontynuuj)"
            return "A. Tablice"

        if route == "char":
            if not current_target and last_target == "char":
                return "B. Znaki (kontynuuj)"
            return "B. Znaki"

        return ""

    def _get_iteration_target_lock_reason(self) -> str:
        current_target = self._get_iteration_target()
        if current_target not in {"plate", "char"}:
            return ""

        active_route_label = self._step2_route_button_label(current_target)
        if not active_route_label:
            active_route_label = (
                "A. Tablice"
                if current_target == "plate"
                else "B. Znaki"
            )

        current_step = int(CAMPAIGN.get_current_step() or 1)
        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
        step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower()

        if current_step > 2 or step3_status in {"needs_rework", "approved", "ready"}:
            return (
                f"Ta iteracja trwa już w „{active_route_label}”. "
                "Drugi tor będzie dostępny dopiero w nowej iteracji."
            )

        if step2_status in {"generated", "approved"}:
            return (
                f"Ta iteracja trwa już w „{active_route_label}”. "
                "Drugi tor będzie dostępny dopiero w nowej iteracji."
            )

        return ""

    def _has_saved_step3_progress(self) -> bool:
        try:
            saved_substep = int(CAMPAIGN.get_step3_substep() or 1)
        except Exception:
            saved_substep = 1

        try:
            stage1_done = bool(CAMPAIGN.is_step3_stage1_done())
        except Exception:
            stage1_done = False

        try:
            stage2_done = bool(CAMPAIGN.is_step3_stage2_done())
        except Exception:
            stage2_done = False

        try:
            extract_state = CAMPAIGN.get_step3_extract_state() or {}
        except Exception:
            extract_state = {}

        entry_mode = str(extract_state.get("entry_mode", "") or "").strip()
        workflow_step = str(extract_state.get("workflow_step", "entry") or "entry").strip().lower()
        annotation_run_dir = str(extract_state.get("annotation_run_dir", "") or "").strip()
        xml_path = str(extract_state.get("xml_path", "") or "").strip()
        images_dir = str(extract_state.get("images_dir", "") or "").strip()

        return bool(
            saved_substep > 1
            or stage1_done
            or stage2_done
            or entry_mode
            or workflow_step != "entry"
            or annotation_run_dir
            or xml_path
            or images_dir
        )

    def _get_campaign_step_title(self, step_num: int, target: str) -> str:
        if step_num == 2:
            if target == "plate":
                return "E2. Tor tablic: ręczna anotacja Z2"
            if target == "char":
                return "E2. Tor znaków: przygotuj tablice dla Z3"
            return "E2. Wybierz ścieżkę iteracji"

        if step_num == 3:
            if target == "plate":
                return "E3. Tor znaków (pominięty)"
            return "E3. Tor znaków"

        if step_num == 4:
            if target == "plate":
                return "E4. Tor tablic: dataset + trening Pose"
            if target == "char":
                return "E4. Tor znaków: dataset + trening YOLO"
            return "E4. Trening wybranego toru"

        return ""

    def _step2_choose_iteration_target(self, target: str):
        switch_started = perf_counter()
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return

        previous_target = self._normalize_iteration_target(CAMPAIGN.get_iteration_target())
        if previous_target == target:
            try:
                self._wizard_step2_target_var.set(target)
            except Exception:
                pass
            return

        plate_model = str(CAMPAIGN.get_global_model("plate") or "").strip()
        plate_model_ready = bool(plate_model and Path(plate_model).exists())
        if previous_target in {"plate", "char"} and previous_target != target:
            lock_reason = self._get_iteration_target_lock_reason()
            if lock_reason:
                messagebox.showinfo(
                    "Tor iteracji jest zablokowany",
                    lock_reason,
                )
                return

        if target == "char":
            ready_source = self._get_char_route_ready_source()
            if not ready_source and (not plate_model or not Path(plate_model).exists()):
                messagebox.showwarning(
                    "Brak modelu tablic",
                    "Tor znaków wymaga istniejącego modelu tablic Pose w projekcie.\n\n"
                    "Najpierw zbuduj tor tablic i wytrenuj model tablic, a potem wróć do E2 dla toru znaków."
                )
                return

        last_target = self._get_last_iteration_target()
        route_changed = previous_target in {"plate", "char"} and previous_target != target
        continuing_previous_iteration_route = bool(last_target and last_target == target and not route_changed)
        lightweight_route_reset = bool(
            route_changed
            and int(CAMPAIGN.get_current_step() or 0) <= 2
            and str(CAMPAIGN.get_step2_status() or "").strip().lower() in {"", "pending"}
            and str(CAMPAIGN.get_step3_status() or "").strip().lower() in {"", "pending"}
            and not str(CAMPAIGN.get_step2_staging_run() or "").strip()
        )

        CAMPAIGN.set_iteration_target(target)
        try:
            self._wizard_step2_target_var.set(target)
        except Exception:
            pass

        pending_after = getattr(self, "_step2_target_change_after_id", None)
        if pending_after is not None:
            try:
                self.frame.after_cancel(pending_after)
            except Exception:
                pass
            self._step2_target_change_after_id = None

        def _finish_target_switch():
            finish_started = perf_counter()
            self._step2_target_change_after_id = None
            if route_changed:
                cleanup_started = perf_counter()
                try:
                    annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
                    if annotation_tab is not None:
                        annotation_tab.reset_campaign_iteration_route_state(
                            new_target=target,
                            remove_persisted_runs=not lightweight_route_reset,
                        )
                except Exception as e:
                    logger.debug(f"Nie udało się wyczyscic stanu Z2 po zmianie toru E2: {e}")

                CAMPAIGN.set_current_step(2)
                CAMPAIGN.reset_step2()
                CAMPAIGN.reset_step3()
                self._log_perf(
                    "step2_route_cleanup",
                    cleanup_started,
                    threshold_ms=20.0,
                    extra=(
                        f"from={previous_target or '-'} to={target} "
                        f"lightweight={1 if lightweight_route_reset else 0}"
                    ),
                )

            self._refresh_active_project_wizard_only()
            self.app.update_campaign_tab_access()
            jump_label = self._get_step2_jump_button_text(target)
            try:
                if target == "plate":
                    self.app.update_status(
                        (
                            f"Wybrano Tryb A. Kontynuujesz tor tablic z poprzedniej iteracji; użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                            if continuing_previous_iteration_route
                            else (
                                f"Wybrano Tryb A. Pozostajesz w E2; użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                                if not route_changed
                                else f"Wybrano Tryb A. Poprzedni stan Z2 tej iteracji został zresetowany; przejdź dalej przyciskiem '{jump_label}'."
                            )
                        ),
                        "info"
                    )
                else:
                    self.app.update_status(
                        (
                            f"Wybrano Tryb B. Kontynuujesz tor znaków z poprzedniej iteracji; użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                            if continuing_previous_iteration_route
                            else (
                                (
                                    f"Wybrano Tryb B. Model tablic projektu jest już dostępny i nie trzeba go dodawać ponownie w E1; użyj przycisku '{jump_label}', aby przygotować tablice."
                                    if plate_model_ready and not self._get_char_route_ready_source()
                                    else f"Wybrano Tryb B. Pozostajesz w E2; użyj przycisku '{jump_label}', gdy chcesz przejść dalej."
                                )
                                if not route_changed
                                else f"Wybrano Tryb B. Poprzedni stan Z2 tej iteracji został zresetowany; przejdź dalej przyciskiem '{jump_label}'."
                            )
                        ),
                        "info"
                    )
            except Exception:
                pass
            self._log_perf(
                "step2_target_switch",
                finish_started,
                threshold_ms=20.0,
                extra=f"route_changed={route_changed}, target={target}",
            )
            self._log_perf(
                "step2_target_switch_total",
                switch_started,
                threshold_ms=20.0,
                extra=f"from={previous_target or '-'} to={target}",
            )

        try:
            self._step2_target_change_after_id = self.frame.after_idle(_finish_target_switch)
        except Exception:
            _finish_target_switch()

    def _render_step2_route_actions(self, frame):
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        panel_alt = palette.get("panel_alt", "#2d2d30")
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")
        accent = blend_hex_colors(palette.get("accent", "#2980b9"), palette.get("surface_info", "#213a4d"), 0.28)
        info_surface = blend_hex_colors(palette.get("surface_info", "#213a4d"), card_bg, 0.38)
        step2_vm = self._get_annotation_step2_view_model()
        target = self._get_iteration_target()
        target_locked_reason = ""
        target_locked = False
        route_hint = ""
        route_choices = []

        for widget in frame.winfo_children():
            widget.destroy()

        frame.configure(bg=card_bg)
        frame.pack(fill=tk.X, pady=(6, 0))

        if step2_vm is not None:
            route_hint = str(getattr(step2_vm, "route_hint", "") or "").strip()
            target_locked_reason = str(getattr(step2_vm, "route_lock_reason", "") or "").strip()
            target_locked = bool(target_locked_reason)
            route_choices = list(getattr(step2_vm, "route_choices", []) or [])

        if not route_hint:
            route_hint = "Wybierz tor iteracji." if not target else ""

        if route_hint:
            tk.Label(
                frame,
                text=route_hint,
                fg=muted,
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=520,
            ).pack(anchor=tk.W, pady=(0, 4))

        route_shell = tk.Frame(frame, bg=card_bg, bd=0, highlightthickness=0)
        route_shell.pack(anchor=tk.W, fill=tk.X, pady=(0, 2))

        btn_row = tk.Frame(route_shell, bg=card_bg, bd=0, highlightthickness=0)
        btn_row.pack(anchor=tk.W, fill=tk.X)

        btn_plate = None
        btn_char = None
        resolved_choices = []
        if route_choices:
            resolved_choices = [choice for choice in route_choices if bool(getattr(choice, "visible", True))]
        else:
            last_target = self._get_last_iteration_target()
            resolved_choices = [
                Step2RouteChoiceViewModel(
                    id="plate",
                    label=self._step2_route_button_label("plate", current_target=target, last_target=last_target),
                    enabled=bool(not target_locked and target != "plate"),
                    selected=bool(target == "plate"),
                    command_id="choose_iteration_target",
                    command_context={"target": "plate"},
                ),
                Step2RouteChoiceViewModel(
                    id="char",
                    label=self._step2_route_button_label("char", current_target=target, last_target=last_target),
                    enabled=bool(not target_locked and target != "char"),
                    selected=bool(target == "char"),
                    command_id="choose_iteration_target",
                    command_context={"target": "char"},
                ),
            ]
            target_locked_reason = self._get_iteration_target_lock_reason()
            target_locked = bool(target_locked_reason)

        try:
            self._wizard_step2_target_var.set(target if target in {"plate", "char"} else "")
        except Exception:
            pass

        for idx, choice in enumerate(resolved_choices):
            choice_id = str(getattr(choice, "id", "") or "").strip()
            label = str(getattr(choice, "label", "") or "").strip()
            command = self._resolve_step2_wizard_action_command(
                str(getattr(choice, "command_id", "") or "").strip(),
                context=dict(getattr(choice, "command_context", {}) or {}),
            )
            choice_enabled = bool(getattr(choice, "enabled", True)) and command is not None
            choice_selected = bool(getattr(choice, "selected", False))
            row = tk.Frame(
                btn_row,
                bg=card_bg,
                bd=1,
                highlightthickness=1,
                highlightbackground=(accent if choice_selected else panel_alt),
                highlightcolor=(accent if choice_selected else panel_alt),
                padx=10,
                pady=6,
            )
            row.pack(side=tk.LEFT, padx=(0, 8) if idx < (len(resolved_choices) - 1) else 0, fill=tk.X, expand=True)
            token = tk.Canvas(
                row,
                width=18,
                height=18,
                bd=0,
                highlightthickness=0,
                bg=card_bg,
                cursor=("hand2" if choice_enabled else ""),
            )
            token.pack(side=tk.LEFT, padx=(0, 8))
            token.create_oval(
                2,
                2,
                16,
                16,
                outline=(accent if choice_selected else muted_dim),
                width=2,
                fill=card_bg,
            )
            if choice_selected:
                token.create_oval(6, 6, 12, 12, outline=accent, fill=accent, width=1)

            label_widget = tk.Label(
                row,
                text=label,
                anchor="w",
                justify=tk.LEFT,
                font=("Segoe UI", 10, "bold"),
                fg=(fg if choice_enabled else muted_dim),
                bg=card_bg,
                cursor=("hand2" if choice_enabled else ""),
            )
            label_widget.pack(side=tk.LEFT, fill=tk.X, expand=True)

            if choice_enabled and command is not None:
                for widget in (row, token, label_widget):
                    try:
                        widget.bind("<Button-1>", lambda _e, cmd=command: cmd(), add="+")
                    except Exception:
                        pass

            if choice_id == "plate":
                btn_plate = row
            elif choice_id == "char":
                btn_char = row

        if target_locked:
            tk.Label(
                frame,
                text=target_locked_reason,
                fg=muted,
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=520,
            ).pack(anchor=tk.W, pady=(8, 0))

        action_primary_label = ""
        action_primary_command = None
        action_secondary_label = ""
        action_secondary_command = None
        if step2_vm is not None:
            primary_cta = getattr(step2_vm, "primary_cta", None)
            secondary_cta = getattr(step2_vm, "secondary_cta", None)
            if primary_cta is not None:
                action_primary_label = str(getattr(primary_cta, "label", "") or "").strip()
                action_primary_command = self._resolve_step2_wizard_action_command(
                    str(getattr(primary_cta, "command_id", "") or "").strip(),
                    context=dict(getattr(primary_cta, "command_context", {}) or {}),
                )
            if secondary_cta is not None:
                action_secondary_label = str(getattr(secondary_cta, "label", "") or "").strip()
                action_secondary_command = self._resolve_step2_wizard_action_command(
                    str(getattr(secondary_cta, "command_id", "") or "").strip(),
                    context=dict(getattr(secondary_cta, "command_context", {}) or {}),
                )

        if action_primary_command is not None or action_secondary_command is not None:
            action_row = tk.Frame(frame, bg=card_bg, bd=0, highlightthickness=0)
            action_row.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

            if action_primary_command is not None and str(action_primary_label or "").strip():
                ttk.Button(
                    action_row,
                    text=f"{action_primary_label} (STEP2-B1)",
                    command=action_primary_command,
                ).pack(side=tk.LEFT, padx=(0, 8))

            if action_secondary_command is not None and str(action_secondary_label or "").strip():
                ttk.Button(
                    action_row,
                    text=f"{action_secondary_label} (STEP2-B2)",
                    command=action_secondary_command,
                ).pack(side=tk.LEFT)

        HELP.bind_help(frame, "camp_step2")
        HELP.bind_help(btn_row, "camp_step2")
        HELP.bind_help(btn_plate, "camp_step2")
        HELP.bind_help(btn_char, "camp_step2")

    def _render_step3_rework_actions(self, frame):
        """Renderuje dodatkowe akcje naprawcze dla kroku 3."""
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        source_state = self._get_char_route_source_state()
        guidance = self._get_char_repair_guidance(source_state)
        primary_label = str(guidance.get("primary_label") or "").strip()
        primary_command = guidance.get("primary_command")
        secondary_label = str(guidance.get("secondary_label") or "").strip()
        secondary_command = guidance.get("secondary_command")
        guidance_text = str(guidance.get("details") or "").strip()

        for w in frame.winfo_children():
            w.destroy()

        frame.configure(bg=card_bg)
        frame.pack(fill=tk.X, pady=(6, 0))

        tk.Label(
            frame,
            text="Dostępne ścieżki naprawcze:",
            fg=palette.get("warning", "#d35400"),
            bg=card_bg,
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 3))

        if guidance_text:
            tk.Label(
                frame,
                text=guidance_text,
                fg=palette.get("fg", "#f3f3f3"),
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=820,
                font=("Segoe UI", 9),
            ).pack(anchor=tk.W, pady=(0, 6))

        btn_row = tk.Frame(frame, bg=card_bg)
        btn_row.pack(anchor=tk.W)

        btn_primary = None
        btn_secondary = None

        if primary_label and primary_command is not None:
            btn_primary = ttk.Button(
                btn_row,
                text=f"{primary_label} (STEP3-B1)",
                command=primary_command,
                style="Accent.TButton"
            )
            btn_primary.pack(side=tk.LEFT, padx=(0, 8))

        if secondary_label and secondary_command is not None:
            btn_secondary = ttk.Button(
                btn_row,
                text=f"{secondary_label} (STEP3-B2)",
                command=secondary_command
            )
            btn_secondary.pack(side=tk.LEFT)

        HELP.bind_help(frame, "camp_step3")
        HELP.bind_help(btn_row, "camp_step3")
        if btn_primary is not None:
            HELP.bind_help(btn_primary, "camp_step3")
        if btn_secondary is not None:
            HELP.bind_help(btn_secondary, "camp_step3")
        return

    # ======================================================
    # DASHBOARD REFRESH
    # ======================================================

    def _refresh_dashboard(self):
        refresh_started = perf_counter()
        self._clear_dashboard_perf_cache()
        try:
            self._collapse_all_wizard_stage_curtains()
        except Exception:
            pass

        self._refresh_projects_list()

        palette = getattr(self.app, "palette", {})
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")
        muted_dim = palette.get("muted_dim", "#9a9a9a")
        accent = palette.get("accent", "#2980b9")
        success = palette.get("success", "#27ae60")
        warning = palette.get("warning", "#d35400")
        surface_info = palette.get("surface_info", palette.get("panel_alt", "#252526"))
        surface_success = palette.get("surface_success", palette.get("panel_alt", "#1f3320"))
        surface_warning = palette.get("surface_warning", palette.get("panel_alt", "#3a2323"))
        header_bg = palette.get("panel", "#252526")

        active_proj = CAMPAIGN.get_active_project_name()
        has_project = bool(active_proj)
        projects_available = bool(CAMPAIGN.get_all_projects())

        # ======================================================
        # TRYB SWOBODNY / BRAK AKTYWNEGO PROJEKTU
        # ======================================================
        if not has_project:
            self.app.campaign_free_mode = True
            self.app.set_campaign_mode(False)
            self._wizard_focus_stage_request = ""
            self._cancel_pending_wizard_stage_focus()

            self.lbl_iter.config(text="Iteracja: -", fg=muted, bg=header_bg)
            self.lbl_campaign_banner.config(
                text="Brak aktywnego projektu.",
                fg=muted,
                bg=surface_info
            )

            self._configure_campaign_banner(
                text=str(self.lbl_campaign_banner.cget("text") or ""),
                fg=muted,
                bg=surface_info,
            )
            self._set_icon_button_enabled("exit_project", False)

            # Lewy panel wygaszony
            for mt in ["vehicle", "plate", "char"]:
                getattr(self, f"lbl_model_{mt}").config(text="Zablokowane", fg=muted_dim)
                lbl_meta = getattr(self, f"lbl_model_{mt}_meta", None)
                if lbl_meta is not None:
                    lbl_meta.config(text="Utworzono: -", fg=muted_dim)
                btn_model = getattr(self, f"btn_model_{mt}", None)
                if btn_model is not None:
                    btn_model.config(state="disabled")

            # Przyciski nagłówka
            self.btn_open_proj.config(state="normal" if projects_available else "disabled")
            self.btn_del_proj.config(state="normal" if projects_available else "disabled")
            self.btn_exit_project.config(state="disabled")

            # Awans nieaktywny
            self.btn_advance.config(text="Utwórz projekt ↗", state="disabled", style="TButton")
            self.btn_complete_project.config(text="Zakończ projekt", state="disabled", style="TButton")
            self._set_grid_visibility(self.left_footer, False)
            self._set_pack_visibility(self.btn_advance, False)
            self._set_pack_visibility(self.btn_complete_project, False)

            # Prawy panel wygaszony
            for item in self.roadmap_ui_elements:
                shell = item.get("shell")
                if shell is not None and str(shell.winfo_manager()) != "pack":
                    try:
                        shell.pack(fill=tk.X, pady=(0, 6))
                    except Exception:
                        pass
                self._set_roadmap_card_border(item)
                item["lbl_title"].config(text=f"🔒 {item['original_title']}", fg=muted_dim)
                self._set_roadmap_note(item, "")
                item["btn"].config(text="Zablokowane", style="TButton", state="disabled")

                extra_frame = item.get("extra_actions_frame")
                if extra_frame:
                    if int(item.get("step_num", 0) or 0) != 1:
                        for w in extra_frame.winfo_children():
                            w.destroy()
                    extra_frame.pack_forget()

            self.step1_panel_expanded = False
            self.current_ingest_plan = {}
            self._refresh_ingest_panel()
            self._refresh_wizard_empty_state(projects_available=projects_available)
            self.app.update_campaign_tab_access()
            self.frame.update_idletasks()
            self.frame.after_idle(self._sync_right_panel_scrollregion)
            self._log_perf("refresh_dashboard_free_mode", refresh_started, threshold_ms=20.0)
            return

        # ======================================================
        # TRYB AKTYWNEGO PROJEKTU
        # ======================================================
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)

        active_state = self._build_active_project_dashboard_state()
        curr_step = int(active_state.get("current_step", CAMPAIGN.get_current_step()) or CAMPAIGN.get_current_step() or 1)
        step1_status = str(active_state.get("step1_status", CAMPAIGN.get_step1_status()) or CAMPAIGN.get_step1_status() or "pending")
        step2_status = str(active_state.get("step2_status", CAMPAIGN.get_step2_status()) or CAMPAIGN.get_step2_status() or "pending")
        step3_status = str(active_state.get("step3_status", CAMPAIGN.get_step3_status()) or CAMPAIGN.get_step3_status() or "pending")
        iteration_target = str(active_state.get("iteration_target", self._get_iteration_target()) or self._get_iteration_target() or "").strip().lower()
        project_status = str(active_state.get("project_status", CAMPAIGN.get_project_status()) or CAMPAIGN.get_project_status() or "active").strip().lower()
        project_paused = project_status == "paused"
        project_completed = project_status == "completed"
        project_paused_at = str(active_state.get("project_paused_at", CAMPAIGN.get_project_paused_at()) or CAMPAIGN.get_project_paused_at() or "").strip()
        project_completed_at = str(active_state.get("project_completed_at", CAMPAIGN.get_project_completed_at()) or CAMPAIGN.get_project_completed_at() or "").strip()

        logger.debug(
            f"[CampaignTab] active_proj={active_proj}, curr_step={curr_step}, "
            f"step2_status={step2_status}, step3_status={step3_status}"
        )
        iter_num = CAMPAIGN.get_current_iteration_num()

        project_title = self._format_project_iteration_title(active_proj, iter_num)
        banner_text = project_title
        banner_fg = success
        banner_bg = surface_success

        if project_completed:
            completed_display = self._format_project_status_timestamp(project_completed_at)
            banner_text = f"{project_title}  |  Zakończony: {completed_display}"
            banner_fg = warning
            banner_bg = surface_warning
        elif project_paused:
            paused_display = self._format_project_status_timestamp(project_paused_at)
            banner_text = f"{project_title}  |  Odłożony: {paused_display}"
            banner_fg = accent
            banner_bg = surface_info

        self.lbl_iter.config(text=f"Iteracja: {iter_num}", fg=warning, bg=header_bg)
        self._configure_campaign_banner(text=banner_text, fg=banner_fg, bg=banner_bg)
        self._set_icon_button_enabled("exit_project", True)

        self._refresh_ingest_panel()
        master_pool_path = CAMPAIGN.get_master_pool_dir()
        master_pool_ready = bool(master_pool_path and master_pool_path.exists() and master_pool_path.is_dir())
        plan_ready = bool(self.current_ingest_plan.get("selected_total", 0))
        if curr_step != 1:
            self.step1_panel_expanded = False

        # Przyciski nagłówka
        self.btn_open_proj.config(state="normal")
        self.btn_del_proj.config(state="normal")
        self.btn_exit_project.config(state="normal")

        # Status aktywnych modeli projektu pozostaje tylko informacyjny.
        for mt in ["vehicle", "plate", "char"]:
            btn_model = getattr(self, f"btn_model_{mt}", None)
            if btn_model is not None:
                btn_model.config(state="normal")

        def fmt_model(p):
            return Path(p).name if p and Path(p).exists() else "Domyślny/Brak"

        vehicle_model = CAMPAIGN.get_global_model("vehicle")
        plate_model = CAMPAIGN.get_global_model("plate")
        char_model = CAMPAIGN.get_global_model("char")

        self.lbl_model_vehicle.config(text=fmt_model(vehicle_model), fg=accent)
        self.lbl_model_plate.config(text=fmt_model(plate_model), fg=accent)
        self.lbl_model_char.config(text=fmt_model(char_model), fg=accent)

        self.lbl_model_vehicle_meta.config(text=self._format_model_meta_label(vehicle_model))
        self.lbl_model_plate_meta.config(text=self._format_model_meta_label(plate_model))
        self.lbl_model_char_meta.config(text=self._format_model_meta_label(char_model))

        self._set_grid_visibility(self.left_footer, True)
        # Globalny przycisk awansu został wycofany z głównego okna wizarda.
        # Jedynym miejscem do rozpoczęcia nowej iteracji zostaje panel E4.
        self._set_pack_visibility(self.btn_advance, False)
        self._set_pack_visibility(self.btn_complete_project, True, fill=tk.X, pady=(8, 0))

        # Awans iteracji
        if project_completed or project_paused:
            self.btn_advance.config(
                text=("Projekt zakończony" if project_completed else "Projekt odłożony"),
                state="disabled",
                style="TButton"
            )
            self.btn_complete_project.config(
                text="Wznów projekt",
                state="normal",
                style="Accent.TButton"
            )
        elif curr_step >= 5:
            self.btn_complete_project.config(
                text="Opuść projekt",
                state="normal",
                style="TButton"
            )
        else:
            self.btn_advance.config(
                text=f"Awans zablokowany (Krok {curr_step})",
                state="disabled",
                style="TButton"
            )
            self.btn_complete_project.config(
                text="Zakończenie dostępne po Z4",
                state="disabled",
                style="TButton"
            )

        self._refresh_wizard_active_dashboard(
            active_project=active_proj,
            current_step=curr_step,
            iteration_target=iteration_target,
            project_status=project_status,
            project_paused_at=project_paused_at,
            project_completed_at=project_completed_at,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
        )
        self._update_main_tabs_highlight(curr_step=curr_step, has_project=True)
        self.app.update_campaign_tab_access()
        self.frame.update_idletasks()
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        self._schedule_pending_wizard_stage_focus()
        self._log_perf(
            "refresh_dashboard_active",
            refresh_started,
            threshold_ms=20.0,
            extra=f"step={curr_step}, target={iteration_target or '-'}",
        )
        return

    def _update_main_tabs_highlight(self, curr_step=None, has_project=True):
        active_tab_key = None
        if has_project:
            step_to_tab = {
                1: "campaign",
                2: "annotation",
                3: "characters",
                4: "training",
            }
            active_tab_key = step_to_tab.get(curr_step, "campaign")

        try:
            self.app.refresh_main_tab_labels(active_tab_key=active_tab_key)
        except Exception:
            pass

    # ======================================================
    # PROJECT CRUD
    # ======================================================

    def _add_new_project(self):
        new_name = self.app.themed_ask_string(
            "Nowy projekt",
            "Podaj unikalną nazwę projektu.",
            parent=self.frame,
            action_label="Utwórz"
        )
        if not new_name:
            return

        try:
            annotation_tab = self.app.tabs.get("annotation")
            if annotation_tab is not None and hasattr(annotation_tab, "capture_free_mode_snapshot_for_project_return"):
                annotation_tab.capture_free_mode_snapshot_for_project_return()
        except Exception as e:
            logger.debug(f"Nie udało się zapisać migawki free mode przed utworzeniem projektu: {e}")

        if CAMPAIGN.create_project(new_name):
            self.app.campaign_free_mode = False
            self.app.set_campaign_mode(True)
            try:
                CAMPAIGN.set_project_start_mode("fresh")
            except Exception:
                pass
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()
            self.app.update_campaign_tab_access()
            self.app.themed_info("Sukces", f"Projekt '{new_name}' został utworzony.", parent=self.frame, tone="success")
        else:
            self.app.themed_error(
                "Błąd",
                "Projekt o takiej nazwie już istnieje lub nazwa jest nieprawidłowa.",
                parent=self.frame
            )

    def _get_selected_projects_from_list(self) -> list[str]:
        if self.project_listbox is None:
            return []

        try:
            selected = []
            for raw_idx in self.project_listbox.curselection():
                idx = int(raw_idx)
                if 0 <= idx < len(self._project_name_by_index):
                    project_name = str(self._project_name_by_index[idx]).strip()
                    if project_name and project_name not in selected:
                        selected.append(project_name)
            return selected
        except Exception:
            return []

    def _get_selected_project_from_list(self) -> str:
        selected = self._get_selected_projects_from_list()
        return selected[0] if selected else ""

    def _select_project_in_list(self, project_name: str):
        if self.project_listbox is None or not project_name:
            return

        try:
            idx = self._project_name_by_index.index(project_name)
            self.project_listbox.selection_clear(0, tk.END)
            self.project_listbox.selection_set(idx)
            self.project_listbox.activate(idx)
            self.project_listbox.see(idx)
            self.project_listbox.focus_set()
        except Exception:
            pass

    def _show_project_context_menu(self, event):
        if self.project_listbox is None or not getattr(self, "project_context_menu", None):
            return "break"

        try:
            idx = int(self.project_listbox.nearest(event.y))
        except Exception:
            return "break"

        if idx < 0 or idx >= len(getattr(self, "_project_name_by_index", [])):
            return "break"

        try:
            selected_now = set(int(value) for value in self.project_listbox.curselection())
            if idx not in selected_now:
                self.project_listbox.selection_clear(0, tk.END)
                self.project_listbox.selection_set(idx)
            self.project_listbox.activate(idx)
            self.project_listbox.see(idx)
            self.project_listbox.focus_set()
            self._on_project_changed()
            selected_projects = self._get_selected_projects_from_list()
            try:
                self.project_context_menu.entryconfig(
                    0,
                    label="Otwórz projekt" if len(selected_projects) <= 1 else "Otwórz pierwszy projekt"
                )
                self.project_context_menu.entryconfig(
                    2,
                    label="Usuń zaznaczony projekt" if len(selected_projects) <= 1 else "Usuń zaznaczone projekty"
                )
            except Exception:
                pass
            self.project_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.project_context_menu.grab_release()
            except Exception:
                pass
        return "break"

    def _set_project_list_status(self, selected: str = "", project_count: int = 0):
        if self.project_list_status_lbl is None:
            return

        def compact(value: str, width: int = 54) -> str:
            text = str(value or "").replace("\n", " ").strip()
            if not text:
                return ""
            return shorten(text, width=width, placeholder="...")

        def apply_lines(*lines: str):
            labels = list(getattr(self, "project_list_status_labels", []))
            if not labels:
                return
            normalized = [compact(line) for line in lines[:3]]
            while len(normalized) < len(labels):
                normalized.append("")
            for lbl, line in zip(labels, normalized):
                lbl.config(text=line)

        selected_projects = self._get_selected_projects_from_list()
        if len(selected_projects) > 1:
            apply_lines(
                f"Zaznaczone projekty: {len(selected_projects)}",
                f"Pierwszy na liście: {selected_projects[0]}",
                "Dwuklik otwiera pierwszy projekt. PPM usuwa całe zaznaczenie."
            )
            return

        if not selected:
            if project_count > 0:
                apply_lines(
                    f"Zapisane projekty: {project_count}",
                    "Wybierz projekt z listy.",
                    "Dwuklik otwiera zaznaczony projekt."
                )
            else:
                apply_lines(
                    "Brak zapisanych projektów.",
                    "Utwórz pierwszy projekt.",
                    "Lista pojawi się po dodaniu projektu."
                )
            return

        created_at = ""
        try:
            created_raw = CAMPAIGN.get_project_created_at(selected)
            if created_raw:
                formatter = getattr(self.app, "_format_project_created_at", None)
                created_at = formatter(created_raw) if callable(formatter) else str(created_raw).replace("T", " ")
        except Exception:
            created_at = ""

        created_line = f"Utworzono: {created_at}" if created_at else "Utworzono: brak danych"

        if selected == CAMPAIGN.get_active_project_name():
            action_line = "Projekt jest już aktywny."
        else:
            action_line = "Dwuklik otwiera zaznaczony projekt."

        apply_lines(
            f"Projekt: {selected}",
            created_line,
            action_line
        )

    def _refresh_projects_list(self):
        if self.project_listbox is None:
            return

        projects = CAMPAIGN.get_all_projects()
        active_project = CAMPAIGN.get_active_project_name()
        previous_selection = self._get_selected_project_from_list()

        self._project_list_refreshing = True
        try:
            self.project_listbox.delete(0, tk.END)
            self._project_name_by_index = []

            if not projects:
                self._set_project_list_status("", 0)
                self.project_listbox.insert(tk.END, "(brak zapisanych projektów)")
                self.project_listbox.itemconfig(0, foreground="#888888")
                self.frame.after_idle(self._sync_left_panel_scrollregion)
                return

            for project_name in projects:
                display_name = f"* {project_name}" if project_name == active_project else project_name
                self.project_listbox.insert(tk.END, display_name)
                idx = len(self._project_name_by_index)
                self._project_name_by_index.append(project_name)
                if project_name == active_project:
                    self.project_listbox.itemconfig(idx, foreground="#27ae60")

            target_name = active_project or previous_selection or projects[0]
            self._select_project_in_list(target_name)
        finally:
            self._project_list_refreshing = False

        self._set_project_list_status(self._get_selected_project_from_list(), len(projects))
        self.frame.after_idle(self._sync_left_panel_scrollregion)

    def _on_project_changed(self, event=None):
        if self._project_list_refreshing:
            return

        selected_projects = self._get_selected_projects_from_list()
        if not selected_projects or self.project_list_status_lbl is None:
            return

        try:
            self._set_project_list_status(selected_projects[0], len(self._project_name_by_index))
            self.frame.after_idle(self._sync_left_panel_scrollregion)
        except Exception:
            pass

    def _open_selected_project(self):
        selected_projects = self._get_selected_projects_from_list()
        selected = selected_projects[0] if selected_projects else ""
        if not selected:
            selected = self._ask_project_from_list(
                title="Otwórz projekt",
                action_label="Otwórz"
            )
        if not selected:
            return

        open_started = perf_counter()

        try:
            annotation_tab = self.app.tabs.get("annotation")
            if annotation_tab is not None and hasattr(annotation_tab, "capture_free_mode_snapshot_for_project_return"):
                annotation_tab.capture_free_mode_snapshot_for_project_return()
        except Exception as e:
            logger.debug(f"Nie udało się zapisać migawki free mode przed otwarciem projektu: {e}")

        self._cancel_deferred_project_open_tasks()
        CAMPAIGN.set_active_project(selected)
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)
        self._clear_dashboard_perf_cache()
        self._ensure_roadmap_ui_ready()
        self._show_project_loading_dashboard(selected)
        self.app.update_campaign_tab_access()

        def _finish_project_open_refresh():
            self._project_open_refresh_after_id = None
            if str(CAMPAIGN.get_active_project_name() or "").strip() != str(selected or "").strip():
                return
            try:
                self._refresh_dashboard()
            except Exception as e:
                logger.debug(f"Nie udało się odświeżyć dashboardu po otwarciu projektu: {e}")
            self._log_perf(
                "open_selected_project_refresh",
                open_started,
                threshold_ms=20.0,
                extra=f"project={selected}",
            )

        try:
            self._project_open_refresh_after_id = self.frame.after(15, _finish_project_open_refresh)
        except Exception:
            _finish_project_open_refresh()

        try:
            self.app.update_status(
                f"Aktywowano projekt: {selected}. Trwa ładowanie kontekstu kampanii.",
                "info"
            )
        except Exception:
            pass

    def _delete_project(self):
        selected_projects = self._get_selected_projects_from_list()
        if not selected_projects:
            selected = self._ask_project_from_list(
                title="Usuń projekt",
                action_label="Usuń"
            )
            selected_projects = [selected] if selected else []
        if not selected_projects:
            return

        if len(selected_projects) == 1:
            confirm_title = "Usuwanie projektu"
            confirm_message = (
                f"Usunąć projekt '{selected_projects[0]}' wraz z całym katalogiem projektu?"
            )
        else:
            confirm_title = "Usuwanie projektów"
            preview = ", ".join(selected_projects[:4])
            if len(selected_projects) > 4:
                preview += f" +{len(selected_projects) - 4} więcej"
            confirm_message = (
                f"Usunąć {len(selected_projects)} zaznaczone projekty wraz z ich katalogami?\n\n"
                f"{preview}"
            )

        if self.app.themed_confirm(
            confirm_title,
            confirm_message,
            parent=self.frame,
            confirm_label="Usuń",
            tone="warning"
        ):
            active_project = CAMPAIGN.get_active_project_name()
            removed = []
            for project_name in selected_projects:
                if CAMPAIGN.delete_project(project_name):
                    removed.append(project_name)

            if not removed:
                return

            if active_project in removed:
                self._clear_project_contexts()
                self.app.campaign_free_mode = True
                self.app.set_campaign_mode(False)

            self._rebuild_roadmap_ui()
            self._refresh_dashboard()
            self.app.update_campaign_tab_access()

            if len(removed) == 1:
                message = f"Projekt '{removed[0]}' został usunięty."
            else:
                message = f"Usunięto {len(removed)} projektów."
            self.app.themed_info(
                "Usunięto",
                message,
                parent=self.frame,
                tone="success"
            )

    def _clear_project_contexts(self):
        tab_labels = {
            "annotation": "Autoanotacji",
            "characters": "Zakładki Znaków",
            "training": "Treningu",
        }

        for tab_key, label in tab_labels.items():
            try:
                if tab_key in self.app.tabs:
                    self.app.tabs[tab_key].clear_campaign_context()
            except Exception as e:
                logger.debug(f"Nie udało się wyczyścić kontekstu {label}: {e}")

    def _exit_project_mode(self):
        active = CAMPAIGN.get_active_project_name()
        if not active:
            return

        if self.app.themed_confirm(
            "Wyjście z projektu",
            f"Czy na pewno chcesz opuścić projekt '{active}' i przejść do trybu swobodnego?\n\n"
            "Projekt nie zostanie usunięty.",
            parent=self.frame,
            confirm_label="Wyjdź",
            tone="warning"
        ):

            # użytkownik ręcznie wymusza tryb swobodny
            self.app.campaign_free_mode = True

            # czyścimy aktywny projekt
            CAMPAIGN.clear_active_project()

            # wyłączamy tryb kampanii
            self.app.set_campaign_mode(False)

            # odświeżamy dashboard
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()

            # finalna synchronizacja dostępności zakładek
            self.app.update_campaign_tab_access()

            try:
                self.app.open_controlled_tab("campaign")
                self.app.root.update_idletasks()
            except Exception as e:
                logger.debug(f"Nie udało się przełączyć na główne okno po wyjściu z projektu: {e}")

            # czyścimy projektowy kontekst innych zakładek dopiero po przejściu do Z1,
            # żeby użytkownik nie widział chwilowego odtwarzania kafli workflow Z2.
            self._clear_project_contexts()

            try:
                self.app.update_status(
                    "Opuściłeś aktywny projekt. Aplikacja działa teraz w trybie swobodnym.",
                    "info"
                )
            except Exception:
                pass
    # ======================================================
    # STEPS
    # ======================================================

    def _step_create_raw_folder(self):
        if not CAMPAIGN.get_active_project_name():
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        if raw_dir is None:
            logger.error("Brak katalogu raw dla aktywnego projektu.")
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        target_iter_dir = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
        target_iter_dir.mkdir(parents=True, exist_ok=True)

        # Jeśli folder iteracji zawiera już zdjęcia, zestaw zdjęć wejściowych jest gotowy.
        existing_images = [f for f in target_iter_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if existing_images:
            if CAMPAIGN.get_step1_status() != "approved":
                should_approve = self.app.themed_confirm(
                    "Zatwierdzenie E1",
                    (
                        f"Folder iteracji zawiera już {len(existing_images)} obrazów:\n{target_iter_dir}\n\n"
                        "Czy zatwierdzić ten zestaw zdjęć jako E1 i odblokować E2?"
                    ),
                    parent=self.frame,
                    confirm_label="Zatwierdź",
                    tone="info"
                )
                if not should_approve:
                    return
                self._approve_current_iteration_package(
                    target_iter_dir=target_iter_dir,
                    selection_mode="existing",
                )
            else:
                if CAMPAIGN.get_current_step() < 2:
                    CAMPAIGN.set_current_step(2)
                self._refresh_dashboard()
            try:
                self.app.update_status(
                    f"✅ Iteracja {iter_num:03d} zawiera już {len(existing_images)} obrazów. Krok 1 zatwierdzony.",
                    "info"
                )
            except Exception:
                pass
            return

        # Użytkownik wskazuje folder źródłowy, a wizard kopiuje zdjęcia do projektu.
        source_dir = filedialog.askdirectory(
            initialdir=str(Path(CONFIG.DIR_1_RAW).absolute()),
            title="Wybierz folder źródłowy z NOWYM zestawem zdjęć do tej iteracji"
        )
        if not source_dir:
            return

        source_dir = Path(source_dir)
        if not source_dir.exists():
            return messagebox.showerror("Błąd", "Wskazany folder źródłowy nie istnieje.")

        image_files = [f for f in source_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if not image_files:
            return messagebox.showwarning(
                "Brak zdjęć",
                "W wybranym folderze nie znaleziono żadnych obrazów obsługiwanych przez aplikację."
            )

        approved_registry = CAMPAIGN.get_used_image_registry()
        approved_names = {
            str(name or "").strip().lower()
            for name in (approved_registry.get("filenames", []) or [])
            if str(name or "").strip()
        }

        accepted_source_files = []
        skipped_duplicate_total = 0
        skipped_duplicate_approved = 0
        for img_file in image_files:
            name_key = str(img_file.name or "").strip().lower()
            if name_key and name_key in approved_names:
                skipped_duplicate_total += 1
                skipped_duplicate_approved += 1
                continue
            accepted_source_files.append(img_file)

        accepted_total = len(accepted_source_files)
        new_to_project_total = accepted_total

        if skipped_duplicate_total > 0:
            duplicate_lines = [
                f"Wybrany folder zawiera {len(image_files)} zdjęć.",
                f"Do bieżącej iteracji trafi: {accepted_total}",
                f"Nowe dla projektu: {new_to_project_total}",
                f"Odrzucone jako już zatwierdzone do treningu YOLO: {skipped_duplicate_total}",
            ]
            if skipped_duplicate_approved > 0:
                duplicate_lines.append(f"W tym już zatwierdzone w projekcie: {skipped_duplicate_approved}")
            duplicate_lines.append("")
            duplicate_lines.append("Czy przygotować iterację z pominięciem tylko zdjęć już zatwierdzonych do treningu YOLO?")
            should_continue = self.app.themed_confirm(
                "Wykryto duble w paczce wejściowej",
                "\n".join(duplicate_lines),
                parent=self.frame,
                confirm_label="Przygotuj iterację",
                tone="info",
            )
            if not should_continue:
                return

        copied = 0
        copied_source_files = []
        for img_file in accepted_source_files:
            dst = target_iter_dir / img_file.name
            if not dst.exists():
                shutil.copy2(img_file, dst)
                copied += 1
                copied_source_files.append(img_file)

        if copied == 0:
            return messagebox.showwarning(
                "Brak nowych plików",
                "Żadne nowe zdjęcia nie zostały skopiowane.\n\n"
                "Być może ten zestaw został już wcześniej użyty w tej iteracji."
            )

        self._approve_current_iteration_package(
            target_iter_dir=target_iter_dir,
            source_dir=source_dir,
            selected_source_files=copied_source_files,
            selection_mode="manual",
            proposal_summary={
                "source_total": len(image_files),
                "accepted_total": copied,
                "current_iteration_package_count": copied,
                "skipped_duplicate_filenames": skipped_duplicate_total,
                "skipped_duplicate_approved_filenames": skipped_duplicate_approved,
                "project_overlap_filenames": 0,
                "new_to_project_count": new_to_project_total,
            },
        )

        try:
            status_suffix = (
                f" Pominięto {skipped_duplicate_total} zdjęć już zatwierdzonych do treningu YOLO."
                if skipped_duplicate_total > 0
                else ""
            )
            self.app.update_status(
                f"✅ Skopiowano {copied} nowych zdjęć do Iteracji {iter_num:03d}. Odblokowano Krok 2.{status_suffix}",
                "info"
            )
        except Exception:
            pass

        summary_lines = [
            f"Skopiowano {copied} zdjęć do:\n{target_iter_dir}",
        ]
        if skipped_duplicate_total > 0:
            summary_lines.extend(
                [
                    "",
                    f"Pominięto {skipped_duplicate_total} zdjęć już zatwierdzonych do treningu YOLO.",
                    (
                        f"Z tego już zatwierdzone w projekcie: {skipped_duplicate_approved}"
                        if skipped_duplicate_approved > 0
                        else None
                    ),
                ]
            )
        summary_lines.extend(
            [
                "",
                "Bieżąca iteracja pracuje na zdjęciach z tej paczki, z pominięciem tych, które były już zatwierdzone do treningu YOLO.",
            ]
        )
        messagebox.showinfo(
            "Przygotowanie zestawu zdjęć zakończone",
            "\n".join(line for line in summary_lines if line)
        )

    def _step_return_to_annotation_review(self):
        try:
            self.app.update_status(
                "Otwieram sprawdzanie tablic (Z2).",
                "info",
            )
        except Exception:
            pass

        iteration_target = self._get_iteration_target()
        if iteration_target in {"plate", "char"}:
            try:
                if iteration_target == "char" and CAMPAIGN.get_active_project_name():
                    CAMPAIGN.set_current_step(3)
                    CAMPAIGN.set_step3_needs_rework()
            except Exception as e:
                logger.debug(f"Nie udało się ustawić trybu naprawczego E3 przed powrotem do Z2: {e}")
            if iteration_target == "char":
                def _open_char_annotation_return():
                    try:
                        self._step_goto_auto_annotation(
                            force_annotation_tab=True,
                            open_existing_run=True,
                        )
                    except Exception as e:
                        logger.error(f"Nie udało się otworzyc kampanijnego Z2 z odroczonym startem: {e}")

                try:
                    self.app.update_status(
                        "Przygotowuję kontekst naprawczy Z2 dla tej paczki.",
                        "info",
                    )
                except Exception:
                    pass
                try:
                    self.frame.after_idle(_open_char_annotation_return)
                except Exception:
                    _open_char_annotation_return()
                return
            try:
                self._step_goto_auto_annotation(
                    force_annotation_tab=True,
                    open_existing_run=True,
                )
                return
            except Exception as e:
                logger.error(f"Nie udało się otworzyc kampanijnego Z2 z kontekstem: {e}")

        def _open_annotation_tab():
            try:
                annotation_tab = self.app.tabs.get("annotation")
                if annotation_tab is None:
                    return
                tab_widget = str(annotation_tab.frame)
                self.app.notebook.tab(tab_widget, state="normal")
                self.app.notebook.select(tab_widget)
            except Exception as e:
                logger.error(f"Nie udało się przelaczyc na Z2: {e}")

        try:
            self.frame.after_idle(_open_annotation_tab)
        except Exception:
            _open_annotation_tab()

    def _step_goto_auto_annotation(
        self,
        force_annotation_tab: bool = False,
        entry_strategy: str | None = None,
        open_existing_run: bool = True,
    ):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2:
            return

        iteration_target = self._get_iteration_target()
        if iteration_target not in {"plate", "char"}:
            try:
                self.app.update_status(
                    "Najpierw wybierz w E2 tor iteracji: tablice albo znaki.",
                    "warning"
                )
            except Exception:
                pass
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_out = CAMPAIGN.get_staging_dir("auto_ann")
        if auto_out is not None:
            Path(auto_out).mkdir(parents=True, exist_ok=True)

        if raw_dir is None or auto_out is None:
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
        input_dir = folder if folder.exists() else raw_dir
        v_mod = CAMPAIGN.get_global_model("vehicle")
        p_mod = CAMPAIGN.get_global_model("plate")
        char_source_state = {}
        char_has_existing_source = False
        if iteration_target == "char" and not force_annotation_tab:
            char_source_state = self._get_char_route_source_state()
            char_has_existing_source = bool(char_source_state.get("has_source"))

        if iteration_target == "char" and (not p_mod or not Path(p_mod).exists()):
            messagebox.showwarning(
                "Brak modelu tablic",
                "Tor znaków wymaga gotowego modelu tablic Pose przypisanego do projektu.\n\n"
                "Najpierw wytrenuj model tablic w torze A, a potem wróć do toru B."
            )
            return

        if iteration_target == "char" and not force_annotation_tab:
            ready_source = self._get_char_route_ready_source()
            if ready_source:
                self._step_continue_characters_from_ready_source(ready_source)
                return

        tab_ann = self.app.tabs.get("annotation")
        if not tab_ann:
            return

        defer_preview_load = bool(force_annotation_tab or iteration_target == "plate")

        try:
            self.app.campaign_free_mode = False
            self.app.set_campaign_mode(True)
            result = tab_ann.open_campaign_step2_entry(
                iteration_target=iteration_target,
                entry_strategy=entry_strategy,
                restore_preview=bool(not force_annotation_tab and not char_has_existing_source),
                open_existing_run=open_existing_run,
                defer_preview_load=defer_preview_load,
            )
        except Exception as e:
            logger.error(f"Nie udało się otworzyc punktu startowego Z2: {e}")
            return

        if not result.get("ok"):
            return

        input_dir = Path(result.get("input_dir") or ".")
        auto_out = Path(result.get("auto_out") or ".")
        manual_template = bool(result.get("manual_template"))
        plate_bootstrap_model = str(result.get("plate_model_path") or "").strip()
        input_source = str(result.get("input_source") or "raw").strip()
        opened_existing_run = bool(result.get("opened_existing_run"))

        try:
            if iteration_target == "plate":
                if opened_existing_run:
                    run_name = ""
                    try:
                        run_name = Path(result.get("restore_run_dir") or "").name
                    except Exception:
                        run_name = ""
                    self.app.update_status(
                        (
                            f"Otworzono Z2 bezposrednio w korekcie runu {run_name}."
                            if run_name
                            else "Otworzono Z2 bezposrednio w aktywnej korekcie wykrytego runu."
                        ),
                        "info"
                    )
                    self.app.open_controlled_tab("annotation")
                    return
                extra_hint = ""
                if not manual_template and plate_bootstrap_model:
                    extra_hint += " Aktywny model tablic projektu został podstawiony automatycznie."
                if input_source == "stage_previous_iteration":
                    extra_hint += " Jako wejście ustawiono stage z poprzedniej iteracji."
                elif input_source == "manual_source_run":
                    extra_hint += " Przywrócono ostatnie ręczne anotacje tablic dla tego zestawu zdjęć."
                elif input_source == "reused_manual_source_run":
                    extra_hint += " Przywrócono ręczne anotacje z poprzedniej iteracji dla tej samej paczki."
                elif input_source == "latest_approved_run":
                    extra_hint += " Przywrócono też ostatni zatwierdzony run anotacji tablic projektu."
                elif input_source == "reused_training_source_run":
                    extra_hint += " Przywrócono ręczne anotacje z runu anotacji Z2, który zasilił trening w poprzedniej iteracji."
                elif input_source == "reused_iteration_run":
                    extra_hint += " Przywrócono zatwierdzony run anotacji Z2 z poprzedniej iteracji dla tej samej paczki."
                if input_source == "project_imported_manual_source":
                    extra_hint += " Wykorzystano run tablic podpiety na starcie projektu."
                elif input_source == "project_imported_images":
                    extra_hint += " Jako wejście ustawiono obrazy wskazane przy starcie projektu."
                self.app.update_status(
                    f"Auto-ustawiono Z2 dla toru tablic: IN={Path(input_dir).name} | OUT={Path(auto_out).name}. "
                    + (
                        "Tryb ręczny utworzy annotations.xml, a nowe polygony zapisza się z etykieta 'plate'."
                        if manual_template
                        else "Możesz uruchomic autoanotacje tablic aktywnym modelem projektu i ręcznie poprawiać wynik."
                    )
                    + extra_hint,
                    "info"
                )
            else:
                if opened_existing_run:
                    run_name = ""
                    try:
                        run_name = Path(result.get("restore_run_dir") or "").name
                    except Exception:
                        run_name = ""
                    self.app.update_status(
                        (
                            f"Otworzono Z2 bezposrednio w korekcie runu {run_name} dla toru znaków."
                            if run_name
                            else "Otworzono Z2 bezposrednio w korekcie istniejących tablic dla toru znaków."
                        ),
                        "info"
                    )
                else:
                    self.app.update_status(
                        f"Auto-ustawiono Z2 dla toru znaków: IN={Path(input_dir).name} | OUT={Path(auto_out).name}. "
                        "Model tablic aktywnego projektu został podstawiony automatycznie. Przygotuj tablice w Z2, a po zatwierdzeniu przejdziesz do Z3.",
                        "info"
                    )
        except Exception:
            pass

        self.app.open_controlled_tab("annotation")
        if bool(result.get("deferred_existing_run_restore")):
            try:
                tab_ann._schedule_deferred_campaign_run_restore(
                    Path(str(result.get("restore_run_dir") or "").strip()),
                    status_message="Otworzono Z2. Wczytuję aktywny run i listę obrazów tej paczki...",
                )
            except Exception as e:
                logger.debug(f"Nie udało się odroczyć przywrócenia runu Z2 po otwarciu zakładki: {e}")
        if bool(result.get("deferred_preview_load")):
            try:
                deferred_input_dir = Path(str(result.get("deferred_preview_input_dir") or "").strip())
            except Exception:
                deferred_input_dir = None
            if deferred_input_dir is not None:
                try:
                    tab_ann._schedule_deferred_campaign_source_preview_load(
                        deferred_input_dir,
                        status_message="Otworzono Z2. Wczytuje liste obrazow tej paczki...",
                    )
                except Exception as e:
                    logger.debug(f"Nie udało się odroczyć wczytania paczki Z2 po otwarciu zakładki: {e}")

    def _step_continue_characters_from_ready_source(self, preferred_source_context: dict | None = None):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2:
            return

        source_state = self._get_char_route_source_state()
        if source_state.get("needs_more_tables"):
            source_images = int(source_state.get("images_with_plates", 0) or 0)
            source_plates = int(source_state.get("total_plates", 0) or 0)
            run_name = str(source_state.get("run_name", "") or "").strip()
            try:
                self.app.update_status(
                    (
                        f"Run {run_name} ma dopiero {source_images}/2 oznaczone obrazy i {source_plates} zapisanych tablic. "
                        "Najpierw przygotuj więcej tablic w Z2, a dopiero potem przejdź do znaków."
                    )
                    if run_name
                    else (
                        f"Masz dopiero {source_images}/2 oznaczone obrazy i {source_plates} zapisanych tablic. "
                        "Najpierw przygotuj więcej tablic w Z2, a dopiero potem przejdź do znaków."
                    ),
                    "warning",
                )
            except Exception:
                pass
            self._step_return_to_annotation_review()
            return

        source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}
        if not source_context:
            source_context = self._get_char_route_ready_source()
        if not source_context:
            try:
                self.app.update_status(
                    "Nie znaleziono gotowych tablic dla tej paczki. Najpierw przygotuj tablice, potem przejdź do pracy nad znakami.",
                    "warning",
                )
            except Exception:
                pass
            return

        ready_run_dir = source_context.get("restore_run_dir")
        ready_run_name = str(
            source_context.get("display_name")
            or source_context.get("run_name")
            or ""
        ).strip()
        try:
            if not ready_run_name and ready_run_dir is not None:
                ready_run_name = Path(ready_run_dir).name
        except Exception:
            ready_run_name = ""

        CAMPAIGN.approve_step2()
        if CAMPAIGN.get_current_step() < 3:
            CAMPAIGN.set_current_step(3)

        self._refresh_dashboard()
        self.app.update_campaign_tab_access()

        try:
            run_hint = f" Korzystam z runu anotacji {ready_run_name}." if ready_run_name else ""
            self.app.update_status(
                "Znaleziono gotowe ręczne tablice dla tej paczki. "
                "Otwieram od razu etap wycinania tablic, OCR i korekty znaków (Z3)."
                + run_hint,
                "info"
            )
        except Exception:
            pass

        self._step_goto_characters(preferred_source_context=source_context)

    def _step_goto_characters_detect(self, preferred_source_context: dict | None = None):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return

        self._step_goto_characters(preferred_source_context=preferred_source_context)

    def _step_goto_characters(self, preferred_source_context: dict | None = None):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return

        tab_char = self.app.tabs.get("characters")
        if not tab_char:
            return

        source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}
        if not source_context and self._get_iteration_target() == "char":
            source_context = self._get_char_route_ready_source()

        try:
            result = tab_char.open_campaign_step3_entry(preferred_source_context=source_context)
        except Exception as e:
            logger.error(f"Nie udało się otworzyc punktu startowego Z3: {e}")
            return

        if not result.get("ok"):
            return

        latest_xml = str(result.get("latest_xml") or "").strip()
        images_dir = str(result.get("images_dir") or "").strip()
        using_preferred_source = bool(result.get("using_preferred_source"))
        preferred_run_dir_raw = str(result.get("preferred_run_dir") or "").strip()
        preferred_run_dir = Path(preferred_run_dir_raw) if preferred_run_dir_raw else None
        preferred_source_name = str(
            source_context.get("display_name")
            or source_context.get("run_name")
            or ""
        ).strip()

        try:
            folder_name = Path(images_dir).name if images_dir else ""
        except Exception:
            folder_name = ""

        try:
            if latest_xml:
                if using_preferred_source and preferred_run_dir is not None:
                    source_label = preferred_source_name or preferred_run_dir.name
                    self.app.update_status(
                        f"Ustawiono Z3 na gotowe źródło tablic: {source_label}. XML={preferred_run_dir.name}/annotations.xml | IMG={folder_name}.",
                        "info"
                    )
                else:
                    self.app.update_status(
                        f"Ustawiono świeże źródła dla Zakładki Znaków: XML={Path(latest_xml).parent.name}/annotations.xml | IMG={folder_name}.",
                        "info"
                    )
            else:
                self.app.update_status(
                    "Nie znaleziono nowego pliku annotations.xml. Upewnij się, ze Autoanotacja zakończyła się sukcesem i etap został zatwierdzony.",
                    "warning"
                )
        except Exception:
            pass

        self.app.open_controlled_tab("characters")

    def _step_goto_training(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4:
            return

        try:
            iteration_target = self._get_iteration_target()
            if iteration_target not in {"plate", "char"}:
                iteration_target = "char"

            tab_train = self.app.tabs.get("training")
            if not tab_train:
                logger.error("Nie znaleziono zakładki TrainingTab w app.tabs.")
                return

            readiness = None
            try:
                if hasattr(tab_train, "get_campaign_step4_readiness"):
                    readiness = tab_train.get_campaign_step4_readiness(iteration_target=iteration_target)
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowosci wejscia do Z4: {e}")
                readiness = None

            if isinstance(readiness, dict) and not readiness.get("ok", False):
                reason = str(readiness.get("reason") or "").strip().lower()
                if reason == "stale_plate_dataset":
                    warn_msg = str(readiness.get("message") or "").strip()
                    try:
                        if warn_msg:
                            self.app.update_status(warn_msg, "warning")
                    except Exception:
                        pass
                else:
                    warn_msg = str(readiness.get("message") or "").strip() or "Z4 nie jest jeszcze gotowe do otwarcia."
                    try:
                        self.app.update_status(warn_msg, "warning")
                    except Exception:
                        pass
                    try:
                        messagebox.showwarning("Z4 jeszcze zablokowane", warn_msg, parent=self.frame)
                    except Exception:
                        pass
                    return

            try:
                result = tab_train.open_campaign_step4_entry(iteration_target=iteration_target)
            except Exception as e:
                logger.error(f"Błąd otwierania punktu startowego Z4: {e}")
                return

            if not result.get("ok"):
                warn_msg = str(result.get("message") or "").strip()
                if warn_msg:
                    try:
                        self.app.update_status(warn_msg, "warning")
                    except Exception:
                        pass
                return

            latest_source_raw = str(result.get("latest_source") or "").strip()
            latest_source = Path(latest_source_raw) if latest_source_raw else None
            dataset_hint = str(result.get("dataset_hint") or "").strip()

            try:
                if iteration_target == "plate":
                    if dataset_hint:
                        self.app.update_status(
                            f"Ustawiono tor treningu tablic: gotowy dataset = {Path(dataset_hint).name}, źródła XML z Z2 i model Pose.",
                            "info"
                        )
                    else:
                        self.app.update_status(
                            "Przelaczono do Treningu w torze tablic. Zbuduj dataset z XML CVAT i uruchom trening modelu Pose.",
                            "info"
                        )
                elif latest_source is not None:
                    self.app.update_status(
                        f"Ustawiono automatycznie Trening: źródło splittera = {latest_source.name}, wynik splitu w katalogu projektu oraz model DETECT dla znaków.",
                        "info"
                    )
                else:
                    self.app.update_status(
                        "Przelaczono do Treningu w kontekscie projektu, ale nie znaleziono jeszcze datasetu źródłowego w 4_training_datasets.",
                        "warning"
                    )
            except Exception:
                pass

            self.app.open_controlled_tab("training")
            return
        except Exception as e:
            logger.error(f"Błąd nawigacji (Krok 4): {e}")

    def _step_goto_training_dataset(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4:
            return

        try:
            iteration_target = self._get_iteration_target()
            if iteration_target not in {"plate", "char"}:
                iteration_target = "char"

            tab_train = self.app.tabs.get("training")
            if not tab_train:
                logger.error("Nie znaleziono zakładki TrainingTab w app.tabs.")
                return

            result = tab_train.open_campaign_step4_entry(
                iteration_target=iteration_target,
                preferred_subtab="dataset",
            )
        except Exception as e:
            logger.error(f"Błąd otwierania PZ1 dla Z4: {e}")
            return

        if not result.get("ok"):
            warn_msg = str(result.get("message") or "").strip()
            if warn_msg:
                try:
                    self.app.update_status(warn_msg, "warning")
                except Exception:
                    pass
            return

        try:
            self.app.update_status(
                "Przejście do Z4 otworzyło PZ1, aby przebudować albo sprawdzić dataset tej iteracji.",
                "info",
            )
        except Exception:
            pass

        self.app.open_controlled_tab("training")
        return

    def _advance_iteration(self):
        if getattr(self, "_iteration_advance_thread", None) is not None:
            return

        mode = self._ask_iteration_advance_mode()
        if not mode:
            return

        try:
            if mode == "reuse_input":
                self.app.update_status(
                    "Przygotowuję nową iterację z tej samej puli zdjęć. To może chwilę potrwać przy dużej paczce.",
                    "info",
                )
            else:
                self.app.update_status(
                    "Rozpoczynam nową iterację projektu.",
                    "info",
                )
        except Exception:
            pass
        try:
            self.frame.update_idletasks()
        except Exception:
            pass

        self._iteration_advance_mode = str(mode or "").strip().lower()
        self._iteration_advance_result = None
        self._set_iteration_advance_busy(True)

        worker = threading.Thread(
            target=self._run_iteration_advance_worker,
            args=(self._iteration_advance_mode,),
            daemon=True,
        )
        self._iteration_advance_thread = worker
        worker.start()
        self._schedule_iteration_advance_poll()

    def _set_iteration_advance_busy(self, busy: bool) -> None:
        state_cache = getattr(self, "_iteration_advance_ui_cache", None)
        if busy and not isinstance(state_cache, dict):
            state_cache = {}
            try:
                state_cache["btn_complete_project"] = {
                    "text": self.btn_complete_project.cget("text"),
                    "state": self.btn_complete_project.cget("state"),
                }
            except Exception:
                pass
            for attr_name in ("btn_open_proj", "btn_del_proj", "btn_exit_project"):
                widget = getattr(self, attr_name, None)
                if widget is None:
                    continue
                try:
                    state_cache[attr_name] = {"state": widget.cget("state")}
                except Exception:
                    pass
            self._iteration_advance_ui_cache = state_cache

        try:
            if busy:
                self.btn_complete_project.config(
                    text="Przygotowywanie iteracji...",
                    state="disabled",
                )
            elif isinstance(state_cache, dict) and "btn_complete_project" in state_cache:
                self.btn_complete_project.config(**dict(state_cache["btn_complete_project"]))
        except Exception:
            pass

        for attr_name in ("btn_open_proj", "btn_del_proj", "btn_exit_project"):
            widget = getattr(self, attr_name, None)
            if widget is None:
                continue
            try:
                if busy:
                    widget.config(state="disabled")
                elif isinstance(state_cache, dict) and attr_name in state_cache:
                    widget.config(**dict(state_cache[attr_name]))
            except Exception:
                pass

        try:
            self.frame.configure(cursor=("watch" if busy else ""))
        except Exception:
            pass
        try:
            self.app.root.configure(cursor=("watch" if busy else ""))
        except Exception:
            pass
        if not busy:
            self._iteration_advance_ui_cache = None

    def _run_iteration_advance_worker(self, mode: str) -> None:
        try:
            result = CAMPAIGN.advance_to_next_iteration(start_mode=mode)
        except Exception as exc:
            logger.exception("Błąd podczas tworzenia nowej iteracji")
            result = {
                "ok": False,
                "reason": "exception",
                "error": str(exc),
            }
        self._iteration_advance_result = dict(result or {})

    def _schedule_iteration_advance_poll(self) -> None:
        pending = getattr(self, "_iteration_advance_poll_after_id", None)
        if pending:
            try:
                self.frame.after_cancel(pending)
            except Exception:
                pass
        self._iteration_advance_poll_after_id = self.frame.after(80, self._poll_iteration_advance_worker)

    def _poll_iteration_advance_worker(self) -> None:
        self._iteration_advance_poll_after_id = None
        worker = getattr(self, "_iteration_advance_thread", None)
        if worker is not None and worker.is_alive():
            self._schedule_iteration_advance_poll()
            return

        mode = str(getattr(self, "_iteration_advance_mode", "") or "").strip().lower()
        result = dict(getattr(self, "_iteration_advance_result", {}) or {})
        self._iteration_advance_thread = None
        self._iteration_advance_result = None
        self._iteration_advance_mode = ""
        self._set_iteration_advance_busy(False)
        self._finish_iteration_advance(mode, result)

    def _finish_iteration_advance(self, mode: str, result: dict) -> None:
        if not result.get("ok"):
            reason = str(result.get("reason") or "").strip().lower()
            if reason == "step4_not_finished":
                self.app.themed_info(
                    "Najpierw domknij E4",
                    (
                        "Nie możesz rozpocząć kolejnej iteracji, dopóki etap E4 tej iteracji "
                        "nie zostanie zakończony.\n\n"
                        "Najpierw wróć do Z4, uruchom trening albo domknij etap tylko wtedy, "
                        "gdy kampania oznaczy trening jako gotowy."
                    ),
                    parent=self.frame,
                    tone="warning",
                )
            elif reason == "project_not_active":
                self.app.themed_info(
                    "Projekt nie jest aktywny",
                    "Wznów projekt, zanim rozpoczniesz kolejną iterację.",
                    parent=self.frame,
                    tone="warning",
                )
            elif reason == "missing_remaining_images":
                self.app.themed_info(
                    "Brak kolejnej paczki",
                    (
                        "Nie ma już kolejnych zdjęć do pobrania z tej samej puli projektu.\n"
                        "System pomija tu obrazy już zatwierdzone w projekcie.\n\n"
                        "Aby kontynuować, rozpocznij kolejną iterację od nowego zestawu zdjęć "
                        "albo zakończ projekt."
                    ),
                    parent=self.frame,
                    tone="warning",
                )
            elif reason == "copy_failed":
                self.app.themed_info(
                    "Nie udało się przygotować iteracji",
                    (
                        "Nie udało się skopiować kolejnej paczki zdjęć z tej samej puli.\n\n"
                        "Spróbuj ponownie albo rozpocznij iterację od nowego zestawu zdjęć."
                    ),
                    parent=self.frame,
                    tone="warning",
                )
            else:
                self.app.themed_info(
                    "Nie udało się rozpocząć iteracji",
                    "Nowa iteracja nie została utworzona. Sprawdź stan projektu i spróbuj ponownie.",
                    parent=self.frame,
                    tone="warning",
                )
            return

        try:
            annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
            next_input_dir = CAMPAIGN.get_iteration_raw_dir()
            if annotation_tab is not None and hasattr(annotation_tab, "prepare_campaign_iteration_transition"):
                annotation_tab.prepare_campaign_iteration_transition(
                    input_dir=(Path(next_input_dir) if next_input_dir else None)
                )
        except Exception as e:
            logger.debug(f"Nie udało się przygotować Z2 do nowej iteracji: {e}")

        self._rebuild_roadmap_ui()
        self._refresh_dashboard()
        self.app.update_campaign_tab_access()

        iter_num = int(result.get("next_iteration", CAMPAIGN.get_current_iteration_num()) or CAMPAIGN.get_current_iteration_num())
        effective_mode = str(result.get("effective_mode", "new_input") or "new_input").strip().lower()

        try:
            if mode == "reuse_input" and effective_mode != "reuse_input":
                self.app.update_status(
                    (
                        f"Rozpoczęto iterację {iter_num:03d}, ale nie udało się przenieść "
                        "poprzedniego zestawu zdjęć. Iteracja startuje od E1."
                    ),
                    "warning"
                )
            elif effective_mode == "reuse_input":
                copied = int(result.get("copied_images", 0) or 0)
                self.app.update_status(
                    (
                        f"Rozpoczęto iterację {iter_num:03d} na kolejnej paczce z tej samej puli zdjęć "
                        f"({copied} obrazów). E1 zostało domknięte automatycznie, więc możesz od razu przejść do E2. "
                        "Aktywne modele projektu pozostały zachowane."
                    ),
                    "info"
                )
            else:
                self.app.update_status(
                    f"Rozpoczęto iterację {iter_num:03d}. Wskaż nowy zestaw zdjęć w E1. Aktywne modele projektu pozostały zachowane.",
                    "info"
                )
        except Exception:
            pass

        try:
            self.app.open_controlled_tab("campaign")
        except Exception:
            pass

    def _toggle_project_completion(self):
        active_project = CAMPAIGN.get_active_project_name()
        if not active_project:
            return

        project_status = CAMPAIGN.get_project_status()
        if project_status in {"completed", "paused"}:
            status_label = "odłożony" if project_status == "paused" else "zakończony"
            if self.app.themed_confirm(
                "Wznowienie projektu",
                f"Czy wznowić {status_label} projekt '{active_project}'?\n\n"
                "Po wznowieniu znowu będzie można rozpocząć nową iterację.",
                parent=self.frame,
                confirm_label="Wznów",
                tone="info"
            ):
                CAMPAIGN.reopen_project()
                self._refresh_dashboard()
                self.app.update_campaign_tab_access()
                try:
                    self.app.update_status(
                        f"Projekt '{active_project}' został wznowiony. Możesz wrócić do workflow albo rozpocząć kolejną iterację.",
                        "info"
                    )
                except Exception:
                    pass
            return

        if CAMPAIGN.get_current_step() < 5:
            return

        if self.app.themed_confirm(
            "Opuszczenie projektu",
            f"Czy opuścić aktywny projekt '{active_project}'?\n\n"
            "Projekt pozostanie zapisany i będzie można wrócić do niego później.",
            parent=self.frame,
            confirm_label="Opuść projekt",
            tone="info"
        ):
            CAMPAIGN.pause_project()
            self._refresh_dashboard()
            self.app.update_campaign_tab_access()
            try:
                self.app.update_status(
                    f"Projekt '{active_project}' został odłożony. Możesz wrócić do niego później.",
                    "info"
                )
            except Exception:
                pass
