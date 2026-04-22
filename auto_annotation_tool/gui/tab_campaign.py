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
import xml.etree.ElementTree as ET
import os
import shutil
import webbrowser

from ..config import CONFIG, logger, PIL_AVAILABLE, Image, ImageTk, ImageDraw, ImageFont
from ..campaign_manager import CAMPAIGN
from ..campaign_ingest_planner import CHAR_ALPHABET, CampaignIngestPlanner
from ..validators import validate_model_file
from ..icons import IconManager
from .help_manager import HELP
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors


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
        self._wizard_header_metro_statuses = []
        self.wizard_empty_state_card = None
        self.wizard_stage_cards = {}
        self.wizard_stage_cards_host = None

        self._build_ui()
        self._refresh_dashboard()
        self.frame.after_idle(self._mark_startup_ui_ready)

    def _mark_startup_ui_ready(self):
        self._startup_ui_ready = True

    def is_startup_ui_ready(self) -> bool:
        return bool(getattr(self, "_startup_ui_ready", False))

    # ======================================================
    # UI BUILD
    # ======================================================

    def _build_ui(self):
        palette = getattr(self.app, "palette", {})

        # ---------------- HEADER ----------------
        header_bg = palette.get("panel", "#252526")
        header_f = tk.Frame(self.frame, bg=header_bg, bd=0, highlightthickness=0, padx=15, pady=15)
        header_f.pack(fill=tk.X)
        header_f.columnconfigure(0, weight=1)
        header_f.columnconfigure(1, weight=1)
        header_f.columnconfigure(2, weight=0)
        self.header_frame = header_f

        self.lbl_title = tk.Label(
            header_f,
            text="MENEDZER KAMPANII",
            font=("Segoe UI", 16, "bold"),
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
            font=("Segoe UI", 14, "bold"),
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
        self.campaign_banner_shell.pack(fill=tk.X, padx=15, pady=(0, 8))

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
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("warning", "#ffd37a"),
            bg=banner_bg,
            padx=10,
            pady=4,
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
        self.banner_progress_row.pack(fill=tk.X, padx=10, pady=(0, 8))

        self.wizard_header_metro_canvas = tk.Canvas(
            self.banner_progress_row,
            height=112,
            bd=0,
            highlightthickness=0,
            bg=banner_bg,
        )
        self.wizard_header_metro_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.wizard_header_metro_canvas.bind("<Configure>", self._draw_wizard_stage_metro, add="+")
        HELP.bind_help(self.wizard_header_metro_canvas, "camp_open_project")

        self.wizard_exit_button_canvas = tk.Canvas(
            self.banner_progress_row,
            width=220,
            height=42,
            bd=0,
            highlightthickness=0,
            bg=banner_bg,
            cursor="hand2",
        )
        self.wizard_exit_button_canvas.pack(side=tk.RIGHT, padx=(10, 0), pady=(22, 0), anchor="n")
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
        self.btn_advance.pack(fill=tk.X)

        self.btn_complete_project = ttk.Button(
            self.left_footer,
            text="Zakończ projekt",
            command=self._toggle_project_completion
        )
        self.btn_complete_project.pack(fill=tk.X, pady=(8, 0))

        self.project_assets_row = ttk.Frame(self.left_footer)

        self.btn_review_training = ttk.Button(
            self.project_assets_row,
            text="Z4 / analiza",
            command=self._open_project_training_review
        )
        self.btn_review_training.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.btn_open_project_models = ttk.Button(
            self.project_assets_row,
            text="Folder modeli",
            command=lambda: self._open_project_resource_dir("models")
        )
        self.btn_open_project_models.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        self.btn_open_project_datasets = ttk.Button(
            self.project_assets_row,
            text="Folder datasetów",
            command=lambda: self._open_project_resource_dir("datasets")
        )
        self.btn_open_project_datasets.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        HELP.bind_help(self.btn_open_proj, "camp_open_project")
        HELP.bind_help(self.btn_del_proj, "camp_delete_project")
        HELP.bind_help(self.btn_exit_project, "camp_exit_project")
        HELP.bind_help(left_panel, "camp_models")
        HELP.bind_help(self.btn_advance, "camp_advance")
        HELP.bind_help(self.btn_complete_project, "camp_advance")
        HELP.bind_help(self.btn_review_training, "camp_advance")
        HELP.bind_help(self.btn_open_project_models, "camp_models")
        HELP.bind_help(self.btn_open_project_datasets, "camp_advance")

        # Skróty projektu zostały ukryte, żeby nie dublować nawigacji kart E1-E4.
        self.project_assets_row.pack_forget()

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
        if listbox is None or units == 0:
            return None
        host_canvas = None
        if listbox is self.project_listbox:
            host_canvas = self.left_panel_canvas
        elif listbox is self.ingest_plan_listbox:
            host_canvas = self.right_panel_canvas
        if host_canvas is not None and self._canvas_can_scroll(host_canvas, units):
            try:
                host_canvas.yview_scroll(units, "units")
            except Exception:
                pass
            return "break"
        if not self._listbox_can_scroll(listbox, units):
            return None
        try:
            listbox.yview_scroll(units, "units")
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
                    host_canvas.yview_scroll(units, "units")
                    return "break"
                if self._listbox_can_scroll(listbox, units):
                    listbox.yview_scroll(units, "units")
                return "break"
            except Exception:
                return "break"

        for canvas in (self.right_panel_canvas, self.left_panel_canvas):
            if not self._widget_contains_point(canvas, x_root, y_root):
                continue
            if not self._canvas_can_scroll(canvas, units):
                continue
            try:
                canvas.yview_scroll(units, "units")
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
        header_lbl.pack(fill=tk.X, padx=10, pady=(10, 4))
        self.ingest_header_lbl = header_lbl

        intro_lbl = tk.Label(
            ingest_lf,
            text="W E1 wskazujesz wybrany folder zdjęć. System od razu ładuje pełen zbiór i odświeża histogram znaków.",
            justify=tk.LEFT,
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        intro_lbl.pack(anchor=tk.W, padx=10, pady=(0, 6))
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
        start_mode_row.pack(fill=tk.X)

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
        start_assets_row.pack(fill=tk.X, pady=(10, 0))
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
        self.btn_ingest_pick_plate_model.pack(side=tk.LEFT, padx=(8, 0))

        self.btn_ingest_pick_char_model = ttk.Button(
            start_assets_row,
            text="Model znaków",
            command=lambda: self._choose_project_start_model("char"),
        )
        self.btn_ingest_pick_char_model.pack(side=tk.LEFT, padx=(8, 0))

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
        status_panel.pack(fill=tk.X, padx=10, pady=8)
        self.ingest_status_panel = status_panel
        self.ingest_status_labels = []
        self.ingest_status_summary_lbl = tk.Label(
            status_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            fg=summary_style["fg"],
            bg=summary_style["bg"],
            font=("Segoe UI", 11, "bold"),
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
        approve_row.pack(fill=tk.X, padx=10, pady=(2, 8))
        self.ingest_approve_row = approve_row

        self.btn_apply_ingest_plan = ttk.Button(
            approve_row,
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

        btn = ttk.Button(row, text="Zmień", command=lambda mt=model_type: self._set_model(mt))
        btn.pack(side=tk.RIGHT)

        setattr(self, f"lbl_model_{model_type}", lbl_val)
        setattr(self, f"btn_model_{model_type}", btn)

    def _count_images_in_dir(self, directory: Path | None, recursive: bool = True) -> int:
        if directory is None or not directory.exists() or not directory.is_dir():
            return 0

        try:
            iterator = directory.rglob("*") if recursive else directory.iterdir()
            return sum(
                1
                for image_path in iterator
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
            )
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
            self._set_pack_visibility(self.ingest_intro_lbl, mode_selected, anchor=tk.W, padx=10, pady=(0, 6))
            self._set_pack_visibility(self.ingest_top_section, mode_selected, fill=tk.X, padx=10, pady=(0, 6))
            self._set_pack_visibility(self.ingest_body, mode_selected, fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
            self._set_pack_visibility(self.ingest_insights_shell, mode_selected, fill=tk.X, padx=10, pady=(0, 6))
            self._set_pack_visibility(self.ingest_start_title_lbl, mode_selected and mode_is_assets, fill=tk.X)
            self._set_pack_visibility(self.ingest_start_summary_lbl, mode_selected and mode_is_assets, fill=tk.X, pady=(4, 8))
            self._set_pack_visibility(self.ingest_start_detected_lbl, mode_selected and mode_is_assets, fill=tk.X, pady=(10, 0))
            self._set_pack_visibility(self.ingest_start_next_lbl, mode_selected and mode_is_assets, fill=tk.X, pady=(6, 0))
            self._set_pack_visibility(self.btn_choose_master_pool, not self._is_first_iteration_start_context(), side=tk.RIGHT, padx=(8, 0))
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
            self._set_pack_visibility(self.ingest_start_assets_row, mode_selected and mode_is_assets, fill=tk.X, pady=(10, 0))
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

            detected_lines.append(
                f"Model tablic: {Path(plate_model_path).name}" if plate_model_ready else "Model tablic: brak"
            )
            detected_lines.append(
                f"Model znaków: {Path(char_model_path).name}" if char_model_ready else "Model znaków: brak"
            )

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
            self._sync_ingest_wraps()
        except Exception:
            pass

    def _get_ingest_summary_style(self) -> dict:
        palette = getattr(self.app, "palette", {})
        return {
            "bg": palette.get("panel", "#252526"),
            "border": palette.get("success", "#63b37b"),
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

    def _load_latest_ingest_plan_for_current_iteration(self) -> dict:
        plan = CAMPAIGN.load_latest_ingest_plan()
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
            f"Wybrany folder zdjęć E1 zawiera teraz {package_images} zdjęć i {package_total} znaków. "
            f"Najczęstsze znaki: {dominant_text}.\n"
            f"Brakujące znaki w tym wybranym folderze zdjęć: {missing_text}."
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
                    font=("Segoe UI", 11, "bold"),
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
            self._populate_ingest_plan_list()
        else:
            self.current_ingest_plan = {}
            self._populate_ingest_plan_list()

        plan_count = int(self.current_ingest_plan.get("selected_total", 0) or 0)

        line1 = ""
        line2 = ""
        if iter_image_count > 0 and step1_approved:
            line3 = "Bieżąca iteracja ma już zatwierdzony zestaw zdjęć wejściowych. E1 jest zamknięte."
        elif iter_image_count > 0:
            line3 = (
                "W folderze iteracji są już obrazy, ale E1 nie zostało jeszcze zatwierdzone. "
                "Kliknij „Zatwierdź E1”, aby odblokować E2."
            )
        elif plan_count > 0:
            line3 = "Zdjęcia zostaną skopiowane do iteracji dopiero po zatwierdzeniu E1."
        elif has_project and master_pool and not master_pool_exists:
            line3 = "Zapisana główna pula zdjęć nie istnieje na dysku. Wskaż poprawny katalog albo użyj ścieżki ręcznej."
        elif has_project and master_pool_exists:
            line3 = (
                "Główna pula zdjęć jest gotowa. Kliknij „Wybierz...”, "
                "a system automatycznie załaduje wybrany folder zdjęć i histogram."
            )
        elif has_project:
            line3 = ""
        else:
            line3 = ""
        if has_project and master_pool_exists and project_start_mode == "assets" and self._is_first_iteration_start_context():
            line3 = (
                "Obrazy tej iteracji są już wskazane. Możesz teraz zatwierdzic E1 "
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

        for image_path in image_paths:
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

        return {
            "ok": True,
            "planner_version": "main_pack_v1",
            "generated_at": datetime.now().isoformat(),
            "project": CAMPAIGN.get_active_project_name() or "",
            "iteration": int(CAMPAIGN.get_current_iteration_num() or 1),
            "master_pool_dir": str(master_pool_dir.resolve()),
            "batch_size": 0,
            "candidates_total": len(selected_items),
            "selected_total": len(selected_items),
            "skipped_used": 0,
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
        skipped_invalid = int(plan.get("skipped_invalid_ground_truth", 0) or 0)
        try:
            CAMPAIGN.save_latest_ingest_plan(self.current_ingest_plan)
        except Exception:
            pass
        self._refresh_ingest_panel(snapshot_override=snapshot)

        if selected_total <= 0:
            messagebox.showwarning(
                "Brak poprawnych pozycji w wybranym folderze zdjęć",
                (
                    "Nie znaleziono zdjęć z poprawnym ground truth w nazwie pliku.\n"
                    "Sprawdź nazewnictwo plików w głównej puli."
                ),
            )
            return

        try:
            status_text = f"Załadowano wybrany folder zdjęć E1: {selected_total} zdjęć."
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

        source_root = Path(source_dir) if source_dir else target_iter_dir
        try:
            CAMPAIGN.record_iteration_ingest(
                source_dir=source_root,
                selected_source_files=selected_files,
                selection_mode=selection_mode,
                proposal_summary=proposal_summary,
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
                "selected_total": self.current_ingest_plan.get("selected_total", 0),
                "batch_size": self.current_ingest_plan.get("batch_size", 0),
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
                "pomijając obrazy już użyte w poprzednich iteracjach. "
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

    def _open_path(self, path: Path):
        try:
            if os.name == "nt":
                os.startfile(str(path))
            else:
                webbrowser.open(path.as_uri())
        except Exception as e:
            messagebox.showinfo("Info", f"Nie mogę otworzyć: {path}\n\n{e}")

    def _open_project_resource_dir(self, key: str):
        if not CAMPAIGN.get_active_project_name():
            return

        target = CAMPAIGN.get_dir(key)
        if target is None:
            return

        target = Path(target)
        target.mkdir(parents=True, exist_ok=True)
        self._open_path(target)

    def _open_project_training_review(self):
        if not CAMPAIGN.get_active_project_name():
            return

        if CAMPAIGN.get_current_step() < 4:
            return

        self._step_goto_training()

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
        header_shell.pack(fill=tk.X, pady=(0, 12))
        self.wizard_header_title_lbl = tk.Label(
            header_shell,
            text="Etapy projektu",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 15, "bold"),
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
        self.wizard_header_summary_lbl.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))

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
            "pool_reuse": "Użyto kolejnej paczki z tej samej puli zdjęć",
            "stage_reuse": "Użyto zdjęć oczekujących w stage z poprzedniej iteracji",
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

    def _build_step1_summary_payload(self) -> dict:
        if not CAMPAIGN.get_active_project_name():
            return {}

        manifest = CAMPAIGN.load_ingest_manifest()
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
        effective_breakdown = self._get_effective_iteration_package_breakdown(manifest)
        effective_total = int(effective_breakdown.get("effective_total", selected_count) or selected_count)
        manual_reuse_count = int(effective_breakdown.get("manual_reuse_count", 0) or 0)
        base_count = int(effective_breakdown.get("base_count", selected_count) or selected_count)
        source_label = str(effective_breakdown.get("source_label") or "").strip()

        selection_mode = self._format_step1_selection_mode_label(manifest.get("selection_mode", "manual"))
        manifest_mode = str(manifest.get("selection_mode", "") or "").strip().lower()
        if manifest_mode == "stage_reuse" and manual_reuse_count > 0:
            selection_mode = self._format_effective_stage_reuse_label(base_count, manual_reuse_count)
        source_dir_text = self._format_campaign_summary_path(manifest.get("source_dir", ""), max_len=84)
        target_dir_text = self._format_campaign_summary_path(target_dir, max_len=84)

        extra_resources = []
        try:
            plate_ready_source = self._get_plate_route_ready_source() or {}
        except Exception:
            plate_ready_source = {}
        try:
            plate_run_name = Path(str(plate_ready_source.get("restore_run_dir") or "")).name if plate_ready_source else ""
        except Exception:
            plate_run_name = ""

        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
        current_iteration = int(manifest.get("iteration", CAMPAIGN.get_current_iteration_num()) or CAMPAIGN.get_current_iteration_num())
        if plate_ready_source:
            extra_resources.append(
                f"Importuj anotacje tablic ({plate_run_name})"
                if plate_run_name
                else "Importuj anotacje tablic"
            )
        if plate_model_path and Path(plate_model_path).exists():
            extra_resources.append(
                f"Model tablic (odziedziczony: {Path(plate_model_path).name})"
                if current_iteration > 1
                else f"Model tablic ({Path(plate_model_path).name})"
            )
        if char_model_path and Path(char_model_path).exists():
            extra_resources.append(
                f"Model znaków (odziedziczony: {Path(char_model_path).name})"
                if current_iteration > 1
                else f"Model znaków ({Path(char_model_path).name})"
            )
        extra_resources_text = ", ".join(extra_resources) if extra_resources else "Nie dołączono dodatkowych zasobów"
        is_iteration_reuse = manifest_mode in {"iteration_reuse", "pool_reuse", "stage_reuse"}

        created_display = str(manifest.get("created_at", "") or "").replace("T", " ").strip() or "brak daty"
        formatter = getattr(self.app, "_format_project_created_at", None)
        if callable(formatter) and manifest.get("created_at"):
            try:
                created_display = formatter(str(manifest.get("created_at") or ""))
            except Exception:
                pass

        rows = [
            ("Iteracja", f"Iteracja {int(manifest.get('iteration', CAMPAIGN.get_current_iteration_num()) or CAMPAIGN.get_current_iteration_num()):03d}"),
            ("Tryb wejścia", selection_mode),
            ("Skąd są zdjęcia", source_dir_text),
            (
                "Liczba zdjęć",
                (
                    f"{effective_total} (stage: {base_count} + ręczne korekty: {manual_reuse_count})"
                    if manual_reuse_count > 0
                    else f"{selected_count}"
                ),
            ),
        ]

        if current_iteration > 1:
            rows.extend(
                [
                    ("Model tablic projektu", Path(plate_model_path).name if plate_model_path and Path(plate_model_path).exists() else "brak"),
                    ("Model znaków projektu", Path(char_model_path).name if char_model_path and Path(char_model_path).exists() else "brak"),
                    ("Run tablic", plate_run_name or "brak"),
                ]
            )
        else:
            rows.append(("Jakie dodatkowe zasoby dołączono", extra_resources_text))

        rows.extend(
            [
                ("Gdzie zapisano paczkę", target_dir_text),
                ("Kiedy zatwierdzono E1", created_display),
            ]
        )

        return {
            "title": "Co wybrano w E1",
            "meta": (
                (
                    (
                        f"{effective_total} zdjęć gotowych do pracy nad tą samą paczką "
                        f"(stage: {base_count} + ręczne korekty: {manual_reuse_count})"
                        if manual_reuse_count > 0
                        else f"{selected_count} zdjęć przygotowanych z tej samej puli dla tej iteracji"
                    )
                    if manifest_mode == "pool_reuse" and current_iteration > 1
                    else (
                        f"{effective_total} zdjęć gotowych do pracy nad tą samą paczką "
                        f"(stage: {base_count} + ręczne korekty: {manual_reuse_count})"
                        if manifest_mode == "stage_reuse" and manual_reuse_count > 0
                        else f"{selected_count} odziedziczonych zdjęć gotowych do tej iteracji"
                    )
                )
                if is_iteration_reuse and current_iteration > 1
                else f"{selected_count} zdjęć gotowych do tej iteracji"
            ),
            "rows": rows,
        }

    def _render_step1_stage_curtain(self, card: dict, status: WizardStageStatus, style: dict):
        if not isinstance(card, dict):
            return

        payload = {}
        if (
            str(getattr(status, "key", "") or "").strip() == "step1"
            and str(getattr(status, "state", "") or "").strip().lower() in {"done", "needs_attention"}
        ):
            payload = self._build_step1_summary_payload()

        rows = list(payload.get("rows", []) or [])
        visible = bool(rows)
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
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        accent = palette.get("accent", "#2980b9")
        success = palette.get("success", "#27ae60")
        warning = palette.get("warning", "#d35400")
        accent_text = palette.get("accent_text", "#ffffff")

        canvas.delete("all")

        statuses = list(getattr(self, "_wizard_header_metro_statuses", []) or [])
        if not statuses:
            statuses = [
                WizardStageStatus(key=f"step{idx}", title="", state="locked")
                for idx in range(1, 5)
            ]

        width = max(int(canvas.winfo_width() or 720), 360)
        height = max(int(canvas.winfo_height() or 112), 112)
        line_y = 44
        circle_r = 15
        halo_r = 21
        top_y = 5
        label_y = 84
        label_map = {
            "step1": "Wejście",
            "step2": "Tor",
            "step3": "Znaki",
            "step4": "Trening",
        }

        usable_left = 58
        usable_right = width - 58
        if usable_right <= usable_left:
            usable_left = 32
            usable_right = width - 32
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
                return {"fill": panel_bg, "outline": accent, "text": accent, "label": accent, "dash": None}
            if state_key == "skipped":
                return {"fill": panel_bg, "outline": muted_dim, "text": muted_dim, "label": muted_dim, "dash": (3, 2)}
            return {"fill": panel_bg, "outline": border, "text": muted, "label": muted, "dash": None}

        if PIL_AVAILABLE and Image is not None and ImageTk is not None and ImageDraw is not None and ImageFont is not None:
            scale = 4
            hi_w = max(width * scale, 4)
            hi_h = max(height * scale, 4)
            image = Image.new("RGBA", (hi_w, hi_h), self._hex_to_rgba(panel_bg))
            draw = ImageDraw.Draw(image, "RGBA")
            font_marker = self._get_pil_font(12 * scale, bold=False)
            font_step = self._get_pil_font(11 * scale, bold=True)
            font_label = self._get_pil_font(12 * scale, bold=False)
            font_skipped = self._get_pil_font(11 * scale, bold=False)

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
                marker_line_top = marker_bbox[3] + (3 * scale)
                marker_line_bottom = s(line_y - halo_r - 2)
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
                        outline=self._hex_to_rgba(style["outline"]),
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
                label_color = style["label"] if highlighted or str(getattr(status, "state", "") or "").strip().lower() in {"done", "in_progress", "needs_attention"} else muted
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

            marker_line_top = (marker_bbox[3] + 3) if marker_bbox else (top_y + 12)
            marker_line_bottom = line_y - halo_r - 2
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
                    outline=style["outline"],
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
                fill=(style["label"] if highlighted or str(getattr(status, "state", "") or "").strip().lower() in {"done", "in_progress", "needs_attention"} else muted),
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

        badge_lbl = tk.Label(
            header_row,
            text="",
            anchor="e",
            justify=tk.RIGHT,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
            bd=0,
            highlightthickness=0,
        )
        badge_lbl.pack(side=tk.RIGHT, padx=(10, 0))

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
            for widget in (shell, content, header_row, title_lbl, summary_lbl, details_lbl, body, curtain_shell, curtain_toggle, curtain_table):
                HELP.bind_help(widget, help_key)

        card = {
            "key": key,
            "shell": shell,
            "content": content,
            "header_row": header_row,
            "title": title_lbl,
            "badge": badge_lbl,
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

    def _get_wizard_stage_state_style(self, state: str, *, is_current: bool = False) -> dict:
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
            },
            "ready": {
                "label": "GOTOWE",
                "border": palette.get("accent", "#2980b9"),
                "badge_bg": palette.get("surface_info", palette.get("panel_alt", "#2d3640")),
                "badge_fg": palette.get("accent", "#2980b9"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
            },
            "in_progress": {
                "label": "W TOKU",
                "border": palette.get("accent", "#2980b9"),
                "badge_bg": palette.get("surface_info", palette.get("panel_alt", "#2d3640")),
                "badge_fg": palette.get("accent", "#2980b9"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
            },
            "needs_attention": {
                "label": "UWAGA",
                "border": palette.get("warning", "#d35400"),
                "badge_bg": palette.get("surface_warning", palette.get("panel_alt", "#3a2323")),
                "badge_fg": palette.get("warning", "#d35400"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
            },
            "done": {
                "label": "GOTOWE",
                "border": palette.get("success", "#27ae60"),
                "badge_bg": palette.get("surface_success", palette.get("panel_alt", "#1f3320")),
                "badge_fg": palette.get("success", "#27ae60"),
                "title_fg": palette.get("fg", "#f3f3f3"),
                "summary_fg": palette.get("fg", "#f3f3f3"),
            },
            "skipped": {
                "label": "POMINIETE",
                "border": palette.get("panel_border", palette.get("border", "#3c3c3c")),
                "badge_bg": palette.get("panel_alt", "#2f3136"),
                "badge_fg": palette.get("muted_dim", "#9a9a9a"),
                "title_fg": palette.get("muted", "#c7c7c7"),
                "summary_fg": palette.get("muted", "#c7c7c7"),
            },
        }
        base = dict(style_map.get(state_key, style_map["locked"]))
        if is_current and state_key in {"ready", "in_progress", "needs_attention"}:
            base["border"] = palette.get("accent", "#2980b9")
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

    def _apply_wizard_stage_status(self, card: dict, status: WizardStageStatus):
        if not card:
            return

        self._set_pack_visibility(card.get("shell"), bool(status.visible), fill=tk.X, pady=(0, 12))
        if not status.visible:
            return

        palette = getattr(self.app, "palette", {})
        card_bg = palette.get("panel", "#252526")
        style = self._get_wizard_stage_state_style(status.state, is_current=status.is_current)

        try:
            card["shell"].config(bg=style["border"])
            card["content"].config(bg=card_bg)
            card["header_row"].config(bg=card_bg)
            card["action_row"].config(bg=card_bg)
            card["body"].config(bg=card_bg)
            card["title"].config(text=status.title, fg=style["title_fg"], bg=card_bg)
            card["badge"].config(text=style["label"], fg=style["badge_fg"], bg=style["badge_bg"])
            card["summary"].config(text=str(status.summary or "").strip(), fg=style["summary_fg"], bg=card_bg)
        except Exception:
            pass

        details_text = str(status.details or "").strip()
        try:
            card["details"].config(text=details_text, bg=card_bg, fg=palette.get("muted", "#c7c7c7"))
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
        self._configure_wizard_stage_button(
            card.get("primary_btn"),
            status.primary_label,
            status.primary_command,
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
        self._set_pack_visibility(
            card.get("action_row"),
            bool(str(status.primary_label or "").strip() or str(status.secondary_label or "").strip()),
            fill=tk.X,
            pady=(10, 0),
        )

        body = card.get("body")
        if body is not None:
            if status.body_mode == "step2_route":
                self._render_step2_route_actions(body)
            elif status.body_mode == "step3_rework":
                self._render_step3_rework_actions(body)
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
            else:
                self._set_pack_visibility(body, bool(status.body_visible), fill=tk.X, pady=(12, 0))

    def _get_softened_banner_bg(self, bg: str) -> str:
        palette = getattr(self.app, "palette", {})
        panel_bg = palette.get("panel", "#252526")
        try:
            return blend_hex_colors(bg, panel_bg, 0.58)
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

        try:
            self.wizard_header_title_lbl.config(text="Brak aktywnego projektu")
            self.wizard_header_summary_lbl.config(
                text=(
                    "Wizard jest teraz lekkim nawigatorem procesu. "
                    "Najpierw otwórz istniejący projekt albo utworz nowy."
                )
            )
        except Exception:
            pass

        empty_status = WizardStageStatus(
            key="empty",
            title="Projekt nie jest jeszcze otwarty",
            state="ready",
            summary="Po wejściu do projektu zobaczysz karty etapów E1-E4 oraz przejścia do Z2, Z3 i Z4.",
            details="Wizard pokazuje stan, decyzje projektowe i kolejny krok. Narzędzia robocze pozostają w zakładkach.",
            primary_label="Nowy projekt",
            primary_command=self._add_new_project,
            secondary_label=("Otwórz projekt" if projects_available else ""),
            secondary_command=(self._open_selected_project if projects_available else None),
        )
        try:
            self.wizard_header_summary_lbl.config(text="Otwórz projekt albo utworz nowy.")
        except Exception:
            pass
        empty_status = WizardStageStatus(
            key="empty",
            title="Projekt nie jest otwarty",
            state="ready",
            summary="Po otwarciu projektu zobaczysz etapy E1-E4.",
            details="Narzedzia robocze pozostają w zakladkach.",
            primary_label="Nowy projekt",
            primary_command=self._add_new_project,
            secondary_label=("Otwórz projekt" if projects_available else ""),
            secondary_command=(self._open_selected_project if projects_available else None),
        )
        self._apply_wizard_stage_status(self.wizard_empty_state_card, empty_status)
        self._set_pack_visibility(self.wizard_stage_cards_host, False)
        self._refresh_wizard_stage_metro()

    def _refresh_wizard_active_dashboard(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
        project_completed: bool,
        project_completed_at: str,
        step1_status: str,
        step2_status: str,
        step3_status: str,
    ):
        self._set_pack_visibility(self.wizard_empty_state_card.get("shell"), False)
        self._set_pack_visibility(self.wizard_stage_cards_host, True, fill=tk.X)

        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        target_label = self._iteration_target_label(iteration_target)
        if not iteration_target:
            target_label = "tor iteracji nie został jeszcze wybrany"

        try:
            self.wizard_header_title_lbl.config(text=f"Projekt: {active_project}")
            self.wizard_header_summary_lbl.config(
                text=(
                    f"Iteracja {iter_num}. Aktualny etap: E{min(max(int(current_step or 1), 1), 4)}. "
                    f"Kontekst: {target_label}."
                )
                if not project_completed
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
                if not project_completed
                else f"Projekt zakończony. Iteracja {iter_num}. {target_label}."
            )
            self.wizard_header_summary_lbl.config(text=summary_text)
        except Exception:
            pass

        statuses = self._get_wizard_stage_statuses(
            active_project=active_project,
            current_step=current_step,
            iteration_target=iteration_target,
            project_completed=project_completed,
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

    def _get_wizard_stage_statuses(
        self,
        *,
        active_project: str,
        current_step: int,
        iteration_target: str,
        project_completed: bool,
        project_completed_at: str,
        step1_status: str,
        step2_status: str,
        step3_status: str,
    ) -> list[WizardStageStatus]:
        statuses: list[WizardStageStatus] = []
        iter_num = int(CAMPAIGN.get_current_iteration_num() or 1)
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

        if iteration_target == "char" and (current_step >= 3 or str(step3_status or "").strip().lower() in {"approved", "needs_rework"}):
            try:
                if training_tab is not None and hasattr(training_tab, "get_campaign_step4_readiness"):
                    char_step4_gate = training_tab.get_campaign_step4_readiness(iteration_target="char")
            except Exception as e:
                logger.debug(f"Nie udało się sprawdzic gotowosci E4 dla toru znaków: {e}")

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
        char_step4_blocked = bool(
            iteration_target == "char"
            and (current_step >= 4 or str(step3_status or "").strip().lower() == "approved")
            and not bool(char_step4_gate.get("ok", True))
        )
        step4_gate_blocked = bool(plate_step4_blocked or char_step4_blocked)

        project_summary = (
            f"Iteracja {iter_num}. {target_label.capitalize()}."
            if iteration_target
            else f"Iteracja {iter_num}. Tor iteracji nie został jeszcze wybrany."
        )
        project_details = "Wizard nie dubluje już ekranów roboczych. Pokazuje stan projektu i kieruje do właściwej zakładki."
        if project_completed:
            completed_display = str(project_completed_at or "").replace("T", " ").strip() or "brak daty"
            formatter = getattr(self.app, "_format_project_created_at", None)
            if callable(formatter) and project_completed_at:
                try:
                    completed_display = formatter(project_completed_at)
                except Exception:
                    completed_display = str(project_completed_at or "").replace("T", " ").strip() or completed_display
            project_details = (
                f"Projekt został oznaczony jako zakończony: {completed_display}. "
                "Możesz go wznowić albo wejść do Z4, aby przejrzeć wyniki."
            )

        if not project_completed:
            project_details = (
                "Ta karta pokazuje tylko kontekst projektu. "
                "Praca etapowa odbywa się niżej, przez karty E1-E4."
            )

        statuses.append(
            WizardStageStatus(
                key="project",
                title=f"Projekt {active_project}",
                state=("done" if project_completed else "in_progress"),
                summary=project_summary,
                details=project_details,
                primary_label=("Wznów projekt" if project_completed else "Wyjdź z projektu"),
                primary_command=(self._toggle_project_completion if project_completed else self._exit_project_mode),
                secondary_label="",
                secondary_command=None,
                is_current=bool(project_completed),
            )
        )

        manifest = CAMPAIGN.load_ingest_manifest()
        manifest_mode = str((manifest or {}).get("selection_mode", "") or "").strip().lower() if isinstance(manifest, dict) else ""
        is_iteration_reuse = bool(iter_num > 1 and manifest_mode in {"iteration_reuse", "pool_reuse", "stage_reuse"})
        effective_breakdown = self._get_effective_iteration_package_breakdown(manifest if isinstance(manifest, dict) else None)
        effective_iter_image_count = int(effective_breakdown.get("effective_total", iter_image_count) or iter_image_count)
        manual_reuse_count = int(effective_breakdown.get("manual_reuse_count", 0) or 0)

        if step1_approved and iter_image_count > 0:
            step1_state = "done"
            if is_iteration_reuse:
                if manifest_mode == "pool_reuse":
                    step1_summary = f"Zdjęcia tej iteracji zostały przygotowane z tej samej puli projektu ({iter_image_count} zdjęć)."
                    step1_details = (
                        "E1 jest już domknięte. Wizard wybrał kolejną paczkę nieużytych obrazów, "
                        "a aktywne modele projektu zostały zachowane, więc możesz od razu przejść do E2."
                    )
                elif manifest_mode == "stage_reuse":
                    if manual_reuse_count > 0:
                        step1_summary = (
                            f"Ta sama paczka pracy jest gotowa do dalszej pracy "
                            f"({effective_iter_image_count} zdjęć: stage {iter_image_count} + ręczne korekty {manual_reuse_count})."
                        )
                        step1_details = (
                            "E1 jest już domknięte. Wizard przejął nieoznaczone zdjęcia odłożone wcześniej do stage "
                            "i zachował możliwość dołączenia ręcznie poprawionych zdjęć z poprzedniej iteracji, "
                            "więc możesz od razu przejść do E2."
                        )
                    else:
                        step1_summary = f"Zdjęcia tej iteracji zostały przygotowane ze stage poprzedniej iteracji ({iter_image_count} zdjęć)."
                        step1_details = (
                            "E1 jest już domknięte. Wizard przejął nieoznaczone zdjęcia odłożone wcześniej do stage, "
                            "a aktywne modele projektu zostały zachowane, więc możesz od razu przejść do E2."
                        )
                else:
                    step1_summary = f"Zdjęcia tej iteracji zostały odziedziczone z poprzedniej iteracji ({iter_image_count} zdjęć)."
                    step1_details = (
                        "E1 jest już domknięte. Aktywne modele projektu zostały zachowane, "
                        "więc możesz od razu przejść do E2 i wybrać tor tej iteracji."
                    )
            else:
                step1_summary = f"Paczka wejściowa iteracji jest zatwierdzona ({iter_image_count} zdjęć)."
                step1_details = "E1 jest zamknięte. Jeśli chcesz pracować na nowej paczce, uruchom kolejną iterację."
        elif iter_image_count > 0:
            step1_state = "needs_attention"
            step1_summary = f"W folderze iteracji są już {iter_image_count} zdjęcia, ale E1 czeka na zatwierdzenie."
            step1_details = "Zejdź do panelu E1 i zatwierdź zestaw zdjęć, aby odblokować E2."
        elif master_pool_ready or plan_count > 0 or current_step == 1:
            step1_state = "in_progress" if current_step == 1 else "ready"
            step1_summary = "Przygotuj wybrany folder zdjęć i zatwierdź E1."
            if plan_count > 0:
                step1_details = f"Obecny plan zawiera {plan_count} zdjęć gotowych do zatwierdzenia."
            elif master_pool_ready:
                step1_details = "Główna pula zdjęć jest ustawiona. Panel E1 pokaże histogram i listę wejściową."
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
                body_visible=bool(not project_completed and current_step == 1 and not step1_approved),
                is_current=bool(not project_completed and current_step == 1),
            )
        )

        step2_vm = self._get_annotation_step2_view_model()
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
            step2_body_mode = "step2_route" if bool(not project_completed and vm_current_step == 2) else ""
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
            step2_body_visible = bool(not project_completed and current_step == 2)
        else:
            step2_primary_label = self._get_step2_jump_button_text(iteration_target)
            step2_primary_command = self._step_goto_auto_annotation
            step2_secondary_label = ""
            step2_secondary_command = None
            step2_body_mode = "step2_route" if bool(not project_completed and current_step == 2) else ""
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
                body_mode=step2_body_mode,
                body_visible=step2_body_visible,
                is_current=bool(not project_completed and (current_step == 2 or plate_step4_blocked)),
            )
        )

        if iteration_target == "plate":
            step3_state = "skipped"
            step3_summary = "Tor tablic pomija Z3."
            step3_details = "Po zatwierdzeniu Z2 projekt przechodzi od razu do Z4."
            step3_primary_label = ""
            step3_primary_command = None
            step3_secondary_label = ""
            step3_secondary_command = None
            step3_body_mode = ""
            step3_body_visible = False
        elif not iteration_target:
            step3_state = "locked"
            step3_summary = "Najpierw wybierz tor iteracji w E2."
            step3_details = "Z3 dotyczy wyłącznie toru znaków."
            step3_primary_label = ""
            step3_primary_command = None
            step3_secondary_label = ""
            step3_secondary_command = None
            step3_body_mode = ""
            step3_body_visible = False
        else:
            step3_primary_label = "Otwórz Z3"
            step3_primary_command = (
                (lambda ctx=dict(char_ready_source): self._step_continue_characters_from_ready_source(ctx))
                if char_ready_source
                else self._step_goto_characters
            )
            step3_secondary_label = ""
            step3_secondary_command = None
            if step3_status == "needs_rework":
                step3_primary_label = str(char_repair_guidance.get("primary_label") or "Przygotuj więcej tablic w Z2")
                step3_primary_command = char_repair_guidance.get("primary_command") or self._step_return_to_annotation_review
                step3_secondary_label = str(char_repair_guidance.get("secondary_label") or "")
                step3_secondary_command = char_repair_guidance.get("secondary_command")
                step3_state = "needs_attention"
                step3_summary = "Paczka znaków wymaga korekty przed treningiem."
                step3_details = str(char_repair_guidance.get("details") or "Najpierw przygotuj poprawna sciezke naprawy dla toru znaków.")
                step3_body_mode = "step3_rework"
                step3_body_visible = not project_completed
            elif step3_status == "approved" or current_step > 3:
                step3_state = "done"
                step3_summary = "Z3 zostało zatwierdzone. Dataset znaków jest gotowy do Z4."
                step3_details = "Możesz wrócić do Z3 albo przejść dalej do budowy datasetu i treningu."
                step3_body_mode = ""
                step3_body_visible = False
            if (step3_status == "approved" or current_step > 3) and char_step4_blocked:
                step3_primary_label = str(char_repair_guidance.get("primary_label") or "Przygotuj więcej tablic w Z2")
                step3_primary_command = char_repair_guidance.get("primary_command") or self._step_return_to_annotation_review
                step3_secondary_label = str(char_repair_guidance.get("secondary_label") or "")
                step3_secondary_command = char_repair_guidance.get("secondary_command")
                step3_state = "needs_attention"
                step3_summary = "Z3 jest formalnie zatwierdzone, ale dataset znaków nadal wymaga poprawy."
                gate_msg = str(char_step4_gate.get("message") or "").strip()
                repair_msg = str(char_repair_guidance.get("details") or "").strip()
                if gate_msg and repair_msg:
                    step3_details = gate_msg + "\n\n" + repair_msg
                else:
                    step3_details = gate_msg or repair_msg or (
                        "Wróć do Z3 i popraw dataset znaków, zanim przejdziesz do Z4."
                    )
                step3_body_mode = ""
                step3_body_visible = False
            elif current_step == 3:
                step3_state = "in_progress"
                step3_summary = "Pracujesz teraz w Z3: wycinanie tablic, OCR, korekty i eksport."
                step3_details = "Wizard pokazuje tylko stan etapu. Cała praca dzieje się w zakładce Znaki."
                step3_body_mode = ""
                step3_body_visible = False
            elif step2_status == "approved" or char_ready_source:
                step3_state = "ready"
                step3_summary = "Z3 jest gotowe do uruchomienia."
                step3_details = "Źródła tablic są już przygotowane i możesz zacząć pracę nad znakami."
                step3_body_mode = ""
                step3_body_visible = False
            else:
                step3_state = "locked"
                step3_summary = "Z3 odblokuje się po przygotowaniu i zatwierdzeniu tablic w Z2."
                step3_details = "Najpierw domknij E2."
                step3_body_mode = ""
                step3_body_visible = False

        if iteration_target == "char" and step3_state in {"in_progress", "ready"}:
            char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
            if char_model_path and Path(char_model_path).exists():
                if step3_state == "in_progress":
                    step3_details = (
                        "Wizard pokazuje tylko stan etapu. Cala praca dzieje się w zakładce Znaki, "
                        "a aktywny model znaków projektu jest tam podstawiany automatycznie."
                    )
                elif step3_state == "ready":
                    step3_details = (
                        "Źródła tablic są już przygotowane i możesz zacząć pracę nad znakami. "
                        "Po wejsciu do Z3 model znaków projektu będzie już ustawiony automatycznie."
                    )

        if (
            iteration_target == "char"
            and current_step < 3
            and str(step2_status or "").strip().lower() != "approved"
        ):
            step3_state = "locked"
            step3_summary = "Z3 odblokuje się po decyzji i zatwierdzeniu E2."
            step3_details = "Najpierw skorzystaj z prowadzenia w E2 i przygotuj albo zatwierdz tablice dla toru znaków."
            step3_body_mode = ""
            step3_body_visible = False
            step3_primary_label = ""
            step3_primary_command = None
            step3_secondary_label = ""
            step3_secondary_command = None

        if step3_state == "done" and not bool(char_step4_blocked):
            step3_primary_label = ""
            step3_primary_command = None
            step3_secondary_label = ""
            step3_secondary_command = None
            step3_body_mode = ""
            step3_body_visible = False

        if (
            iteration_target == "char"
            and not bool(char_step4_blocked)
            and (
                current_step >= 4
                or str(step3_status or "").strip().lower() == "approved"
            )
        ):
            step3_state = "done"
            step3_primary_label = ""
            step3_primary_command = None
            step3_secondary_label = ""
            step3_secondary_command = None
            step3_body_mode = ""
            step3_body_visible = False

        statuses.append(
            WizardStageStatus(
                key="step3",
                title="E3. Znaki i gold pack",
                state=step3_state,
                summary=step3_summary,
                details=step3_details,
                primary_label=step3_primary_label,
                primary_command=step3_primary_command,
                secondary_label=step3_secondary_label,
                secondary_command=step3_secondary_command,
                body_mode=step3_body_mode,
                body_visible=bool(step3_body_visible),
                is_current=bool(not project_completed and current_step == 3 and iteration_target == "char"),
            )
        )

        if project_completed:
            step4_state = "done"
            step4_summary = "Projekt został zakończony. Z4 pozostaje dostępne do przeglądu wyników i analiz."
            step4_details = "Jeśli chcesz uruchomić kolejną iterację w tym projekcie, wznów go z karty projektu."
            step4_secondary_label = "Wznów projekt"
            step4_secondary_command = self._toggle_project_completion
        elif current_step >= 5:
            step4_state = "done"
            step4_summary = "Iteracja została domknięta. Możesz przejrzeć Z4 albo uruchomić nową iterację."
            step4_details = "Wizard nie prowadzi już treningu samodzielnie. Kieruje tylko do Z4 i zarządza stanem iteracji."
            step4_secondary_label = "Nowa iteracja"
            step4_secondary_command = self._advance_iteration
        elif plate_step4_blocked:
            step4_state = "locked"
            step4_summary = "Z4 czeka na uzupelnienie oznaczen w Z2."
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

        if char_step4_blocked and not project_completed and current_step < 5:
            step4_state = "locked"
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
        if project_completed or current_step >= 5 or (current_step == 4 and not step4_gate_blocked):
            step4_primary_label = "Otwórz Z4"
            step4_primary_command = self._step_goto_training
        elif plate_step4_blocked:
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
                is_current=bool(not project_completed and current_step >= 4 and not step4_gate_blocked),
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

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return {}

        getter = getattr(annotation_tab, "get_campaign_step2_source_state", None)
        if not callable(getter):
            return {}

        try:
            source_state = getter(iteration_target=target)
        except Exception as e:
            logger.debug(f"Nie udało się pobrac stanu źródła E2 z Z2 dla toru {target}: {e}")
            return {}

        return dict(source_state) if isinstance(source_state, dict) else {}

    def _get_plate_approved_set_stats(self) -> dict:
        try:
            stats = CAMPAIGN.get_plate_approved_set_stats()
        except Exception as e:
            logger.debug(f"Nie udało się pobrac statystyk ApprovedSet tablic: {e}")
            return {}

        return dict(stats) if isinstance(stats, dict) else {}

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

    def _get_annotation_step2_view_model(self):
        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return None

        getter = getattr(annotation_tab, "get_campaign_step2_view_model", None)
        if not callable(getter):
            return None

        try:
            return getter()
        except Exception as e:
            logger.debug(f"Nie udało się pobrac modelu widoku E2 z Z2: {e}")
            return None

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

        if CAMPAIGN.get_step2_status() == "generated":
            return result
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
            add_row("Model tablic", Path(plate_model_path).name)

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

        current_step = int(CAMPAIGN.get_current_step() or 1)
        step2_status = str(CAMPAIGN.get_step2_status() or "").strip().lower()
        step3_status = str(CAMPAIGN.get_step3_status() or "").strip().lower()

        if current_step > 2 or step3_status in {"needs_rework", "approved"}:
            return (
                "Tor tej iteracji jest już przypisany. Powrót do wizarda służy tutaj do kontynuacji pracy, "
                "a nie do przelaczania projektu na drugi tor."
            )

        if step2_status in {"generated", "approved"}:
            return (
                "Dla tej iteracji istnieja już artefakty z Z2, dlatego tor jest zablokowany. "
                "Jesli chcesz pracowac drugim torem, rozpocznij nowa iteracje."
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
        target = self._normalize_iteration_target(target)
        if target not in {"plate", "char"}:
            return

        previous_target = self._normalize_iteration_target(CAMPAIGN.get_iteration_target())
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

        CAMPAIGN.set_iteration_target(target)
        if route_changed:
            try:
                annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
                if annotation_tab is not None:
                    annotation_tab.reset_campaign_iteration_route_state(new_target=target)
            except Exception as e:
                logger.debug(f"Nie udało się wyczyscic stanu Z2 po zmianie toru E2: {e}")

            CAMPAIGN.set_current_step(2)
            CAMPAIGN.reset_step2()
            CAMPAIGN.reset_step3()

        self._refresh_dashboard()
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

    def _render_step2_route_actions(self, frame):
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
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
            route_hint = (
                "Wybierz tor tej iteracji."
                if not target
                else f"Wybrany tor: {self._iteration_target_label(target)}."
            )

        tk.Label(
            frame,
            text=route_hint,
            fg=palette.get("muted", "#c7c7c7"),
            bg=card_bg,
            justify=tk.LEFT,
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 4))

        btn_row = tk.Frame(frame, bg=card_bg)
        btn_row.pack(anchor=tk.W, fill=tk.X)

        btn_plate = None
        btn_char = None
        if route_choices:
            for idx, choice in enumerate(route_choices):
                if not bool(getattr(choice, "visible", True)):
                    continue
                label = str(getattr(choice, "label", "") or "").strip()
                command = self._resolve_step2_wizard_action_command(
                    str(getattr(choice, "command_id", "") or "").strip(),
                    context=dict(getattr(choice, "command_context", {}) or {}),
                )
                btn = ttk.Button(
                    btn_row,
                    text=label,
                    command=command,
                )
                if not bool(getattr(choice, "enabled", True)) or command is None:
                    btn.configure(state=tk.DISABLED)
                btn.pack(side=tk.LEFT, padx=(0, 8) if idx == 0 else 0)
                if str(getattr(choice, "id", "") or "").strip() == "plate":
                    btn_plate = btn
                elif str(getattr(choice, "id", "") or "").strip() == "char":
                    btn_char = btn
        else:
            last_target = self._get_last_iteration_target()
            btn_plate = ttk.Button(
                btn_row,
                text=self._step2_route_button_label("plate", current_target=target, last_target=last_target),
                command=lambda: self._step2_choose_iteration_target("plate"),
            )
            btn_plate.pack(side=tk.LEFT, padx=(0, 8))

            btn_char = ttk.Button(
                btn_row,
                text=self._step2_route_button_label("char", current_target=target, last_target=last_target),
                command=lambda: self._step2_choose_iteration_target("char"),
            )
            btn_char.pack(side=tk.LEFT)

            target_locked_reason = self._get_iteration_target_lock_reason()
            target_locked = bool(target_locked_reason)
            if target_locked:
                btn_plate.configure(state=tk.DISABLED)
                btn_char.configure(state=tk.DISABLED)
            elif target == "plate":
                btn_plate.configure(state=tk.DISABLED)
            elif target == "char":
                btn_char.configure(state=tk.DISABLED)

        if target_locked:
            tk.Label(
                frame,
                text=target_locked_reason,
                fg=palette.get("muted", "#c7c7c7"),
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=520,
            ).pack(anchor=tk.W, pady=(8, 0))

        action_primary_label = ""
        action_primary_command = None
        action_secondary_label = ""
        action_secondary_command = None
        action_details = ""

        if step2_vm is not None:
            primary_cta = getattr(step2_vm, "primary_cta", None)
            secondary_cta = getattr(step2_vm, "secondary_cta", None)
            action_details = str(getattr(step2_vm, "details", "") or "").strip()
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
            tk.Label(
                frame,
                text="Dalej",
                fg=palette.get("fg", "#f3f3f3"),
                bg=card_bg,
                justify=tk.LEFT,
                font=("Segoe UI", 9, "bold"),
                wraplength=520,
            ).pack(anchor=tk.W, pady=(8, 2))
            if action_details:
                tk.Label(
                    frame,
                    text=action_details,
                    fg=palette.get("muted", "#c7c7c7"),
                    bg=card_bg,
                    justify=tk.LEFT,
                    wraplength=520,
                ).pack(anchor=tk.W, pady=(8, 4))

            action_row = tk.Frame(frame, bg=card_bg, bd=0, highlightthickness=0)
            action_row.pack(anchor=tk.W, fill=tk.X)

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

        self._render_step2_asset_summary(frame, current_target=target)

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
                getattr(self, f"btn_model_{mt}").config(state="disabled")

            # Przyciski nagłówka
            self.btn_open_proj.config(state="normal" if projects_available else "disabled")
            self.btn_del_proj.config(state="normal" if projects_available else "disabled")
            self.btn_exit_project.config(state="disabled")

            # Awans nieaktywny
            self.btn_advance.config(text="Utwórz projekt ↗", state="disabled", style="TButton")
            self.btn_complete_project.config(text="Zakończ projekt", state="disabled", style="TButton")
            self.btn_review_training.config(state="disabled")
            self.btn_open_project_models.config(state="disabled")
            self.btn_open_project_datasets.config(state="disabled")
            self._set_grid_visibility(self.left_footer, False)
            self._set_pack_visibility(self.btn_advance, False)
            self._set_pack_visibility(self.btn_complete_project, False)
            self._set_pack_visibility(self.project_assets_row, False)

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
            return

        # ======================================================
        # TRYB AKTYWNEGO PROJEKTU
        # ======================================================
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)


        curr_step = CAMPAIGN.get_current_step()
        step1_status = CAMPAIGN.get_step1_status()
        step2_status = CAMPAIGN.get_step2_status()
        step3_status = CAMPAIGN.get_step3_status()
        iteration_target = self._get_iteration_target()
        has_saved_step3_progress = self._has_saved_step3_progress()
        project_completed = CAMPAIGN.is_project_completed()
        project_completed_at = CAMPAIGN.get_project_completed_at()
        step1_approved = step1_status == "approved"
        if curr_step >= 2 and not step1_approved and self._get_iteration_image_count() > 0:
            CAMPAIGN.approve_step1()
            step1_status = "approved"
            step1_approved = True

        if (
            curr_step <= 2
            and str(step2_status or "").strip().lower() == "pending"
            and str(step3_status or "").strip().lower() == "pending"
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

        if (
            iteration_target == "char"
            and curr_step < 3
            and str(step2_status or "").strip().lower() == "approved"
            and has_saved_step3_progress
        ):
            if str(step2_status or "").strip().lower() != "approved":
                CAMPAIGN.approve_step2()
                step2_status = "approved"
            CAMPAIGN.set_current_step(3)
            curr_step = 3

        if iteration_target == "plate" and curr_step == 3 and step2_status == "approved":
            CAMPAIGN.set_current_step(4)
            curr_step = 4

        logger.debug(
            f"[CampaignTab] active_proj={active_proj}, curr_step={curr_step}, "
            f"step2_status={step2_status}, step3_status={step3_status}"
        )
        iter_num = CAMPAIGN.get_current_iteration_num()

        banner_text = f"Projekt: {active_proj}"
        banner_fg = success
        banner_bg = surface_success

        if project_completed:
            completed_display = project_completed_at.replace("T", " ") if project_completed_at else "brak daty"
            formatter = getattr(self.app, "_format_project_created_at", None)
            if callable(formatter) and project_completed_at:
                try:
                    completed_display = formatter(project_completed_at)
                except Exception:
                    completed_display = project_completed_at.replace("T", " ")
            banner_text = f"Projekt: {active_proj}  |  Zakończony: {completed_display}"
            banner_fg = warning
            banner_bg = surface_warning

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

        # Przyciski modeli
        for mt in ["vehicle", "plate", "char"]:
            getattr(self, f"btn_model_{mt}").config(state="normal")

        def fmt_model(p):
            return Path(p).name if p and Path(p).exists() else "Domyślny/Brak"

        self.lbl_model_vehicle.config(text=fmt_model(CAMPAIGN.get_global_model("vehicle")), fg=accent)
        self.lbl_model_plate.config(text=fmt_model(CAMPAIGN.get_global_model("plate")), fg=accent)
        self.lbl_model_char.config(text=fmt_model(CAMPAIGN.get_global_model("char")), fg=accent)

        self.btn_open_project_models.config(state="normal")
        self.btn_open_project_datasets.config(state="normal")
        self.btn_review_training.config(
            state=("normal" if curr_step >= 4 else "disabled")
        )
        self._set_grid_visibility(self.left_footer, True)
        self._set_pack_visibility(self.btn_advance, True, fill=tk.X)
        self._set_pack_visibility(self.btn_complete_project, True, fill=tk.X, pady=(8, 0))

        # Awans iteracji
        if project_completed:
            self.btn_advance.config(
                text="Projekt zakończony",
                state="disabled",
                style="TButton"
            )
            self.btn_complete_project.config(
                text="Wznów projekt",
                state="normal",
                style="Accent.TButton"
            )
        elif curr_step >= 5:
            self.btn_advance.config(
                text="Cykl zakończony",
                state="disabled",
                style="TButton"
            )
            self.btn_complete_project.config(
                text="Zakończ projekt",
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
            project_completed=project_completed,
            project_completed_at=project_completed_at,
            step1_status=step1_status,
            step2_status=step2_status,
            step3_status=step3_status,
        )
        self._update_main_tabs_highlight(curr_step=curr_step, has_project=True)
        self.app.update_campaign_tab_access()
        self.frame.update_idletasks()
        self.frame.after_idle(self._sync_right_panel_scrollregion)
        return

        # Folder kroku 1
        step1_folder_exists = self._get_iteration_image_count() > 0
        collapse_following_steps = bool(curr_step == 1 and self.step1_panel_expanded)

        # Kroki
        for item in self.roadmap_ui_elements:
            s = item["step_num"]
            title = item["original_title"]
            orig_btn_txt = item["orig_btn_text"]
            step_title = self._get_campaign_step_title(s, iteration_target) or title
            step_btn_txt = orig_btn_txt
            if s == 2:
                step_btn_txt = self._get_step2_jump_button_text(iteration_target)
            elif s == 3 and iteration_target == "plate":
                step_btn_txt = "Pominięte w torze tablic"
            elif s == 4:
                if iteration_target == "plate":
                    step_btn_txt = "Skocz: Trening tablic"
                elif iteration_target == "char":
                    step_btn_txt = "Skocz: Trening znaków"
            btn = item["btn"]
            extra_frame = item.get("extra_actions_frame")
            shell = item.get("shell")

            if shell is not None:
                if collapse_following_steps and s > 1:
                    try:
                        shell.pack_forget()
                    except Exception:
                        pass
                    continue
                if str(shell.winfo_manager()) != "pack":
                    shell.pack(fill=tk.X, pady=(0, 6))

            if extra_frame:
                if s != 1:
                    for w in extra_frame.winfo_children():
                        w.destroy()
                extra_frame.pack_forget()

            if s < curr_step:
                self._set_roadmap_card_border(item)
                item["lbl_title"].config(text=f"✅ {step_title}", fg=success)

                if s == 3 and iteration_target == "plate":
                    self._set_roadmap_note(
                        item,
                        "Ten etap został pominięty, bo ta iteracja kończy się na ręcznej anotacji tablic i treningu modelu Pose.",
                        "info"
                    )
                    btn.config(text="Pominięte", style="TButton", state="disabled")
                else:
                    self._set_roadmap_note(item, "")
                    btn.config(text="Wykonano", style="TButton", state="disabled")

            elif s == curr_step:
                self._set_roadmap_card_border(item, accent)
                item["lbl_title"].config(text=f"🔵 {step_title}", fg=accent)

                if s == 1:
                    if step1_folder_exists and step1_approved:
                        self.step1_panel_expanded = False
                        self._set_roadmap_note(
                            item,
                            "Folder iteracji zawiera już zestaw zdjęć wejściowych. Możesz przejść dalej do autoanotacji.",
                            "success"
                        )
                    elif step1_folder_exists:
                        self._set_roadmap_note(
                            item,
                            "Folder iteracji zawiera już obrazy, ale E1 nadal czeka na jawne zatwierdzenie. Rozwiń panel E1 i potwierdź zestaw zdjęć, aby odblokować E2.",
                            "warning"
                        )
                    elif self.step1_panel_expanded:
                        self._set_roadmap_note(item, "")
                    elif plan_ready:
                        self._set_roadmap_note(
                            item,
                            "Po rozwinięciu panelu E1 zobaczysz załadowany wybrany folder zdjęć i histogram. Następnie zatwierdzasz go do iteracji.",
                            "info"
                        )
                    elif master_pool_ready:
                        self._set_roadmap_note(
                            item,
                            "Główna pula zdjęć jest ustawiona. Kliknij przycisk karty E1, aby rozwinąć panel i załadować wybrany folder zdjęć.",
                            "info"
                        )
                    else:
                        self._set_roadmap_note(
                            item,
                            "Kliknij przycisk karty E1, aby rozwinąć panel i wskazać główną pulę zdjęć.",
                            "info"
                        )

                    if self.step1_panel_expanded and extra_frame is not None:
                        self._theme_step1_ingest_panel()
                        extra_frame.pack(fill=tk.X, pady=(6, 0))
                    btn.config(
                        text="Ukryj panel E1" if self.step1_panel_expanded else "Pokaż panel E1",
                        style="Accent.TButton",
                        state="normal"
                    )
                elif s == 2:
                    if not iteration_target:
                        self._set_roadmap_note(
                            item,
                            "W E2 wybierasz, czy ta iteracja buduje model tablic czy model znaków. Od tego wyboru zależą domyślne ścieżki Z2, kolejny krok wizarda i tor treningu.",
                            "info"
                        )
                        if extra_frame is not None:
                            self._render_step2_route_actions(extra_frame)
                        btn.config(text="Sterowanie w module E2", style="TButton", state="disabled")
                    else:
                        if iteration_target == "plate":
                            if step2_status == "generated":
                                note_text = (
                                    "Utworzono już run ręcznej anotacji. Przejdź do Autoanotacji, dodaj lub popraw polygony tablic "
                                    "i zatwierdź E2. Ręcznie dodane tablice zapisują się w XML z etykietą 'plate'."
                                )
                                tone = "warning"
                            elif self._get_plate_route_ready_source():
                                source_run = Path(self._get_plate_route_ready_source().get("restore_run_dir"))
                                note_text = (
                                    "Dla tej paczki wykryto już run anotacji tablic. "
                                    f"Wizard może wejsc do Z2 na runie {source_run.name} i kontynuowac korekte bez startu od pustego XML."
                                )
                                tone = "success"
                            elif not bool(self._get_annotation_bootstrap_for_target("plate").get("manual_template", True)):
                                note_text = (
                                    "Tor A może ruszyć od autoanotacji, bo projekt ma już aktywny model tablic. "
                                    "W Z2 sprawdzisz wynik i ewentualnie poprawisz polygony przed treningiem Pose."
                                )
                                tone = "info"
                            else:
                                note_text = (
                                    "Tor A pracuje na surowej paczce zdjęć. Z2 utworzy pusty annotations.xml dla wszystkich obrazów, "
                                    "aby ręcznie dodać polygony tablic z etykietą 'plate'."
                                )
                                tone = "info"
                        else:
                            char_ready_source = self._get_char_route_ready_source()
                            if step2_status == "generated":
                                note_text = (
                                    "Autoanotacja tablic została wykonana, ale etap nie został jeszcze zatwierdzony.\n"
                                    "Przejdź do zakładki Autoanotacja, sprawdź wynik i kliknij „Zatwierdź krok autoanotacji”."
                                )
                                tone = "warning"
                            elif char_ready_source:
                                source_run = Path(char_ready_source.get("restore_run_dir"))
                                note_text = (
                                    "Dla tej paczki są już dostępne ręczne anotacje tablic. "
                                    f"Wizard może pominąć Z2 i przejść od razu do Z3 z runem anotacji {source_run.name}."
                                )
                                tone = "success"
                            else:
                                note_text = (
                                    "Tor B korzysta z istniejącego modelu tablic Pose. Z2 przygotuje tablice dla Z3, a po zatwierdzeniu "
                                    "przejdziesz do wycinania tablic i anotacji znaków."
                                )
                                tone = "info"

                        self._set_roadmap_note(item, note_text, tone)
                        if extra_frame is not None:
                            self._render_step2_route_actions(extra_frame)
                        btn.config(text="Sterowanie w module E2", style="TButton", state="disabled")
                elif s == 3 and step3_status == "needs_rework":
                    self._set_roadmap_note(
                        item,
                        (
                            "Nie udało się zbudować paczki YOLO z tablic perfect.\n"
                            "Wróć do Autoanotacji albo popraw OCR w zakładce Znaki.\n"
                            "Trening pozostaje zablokowany do czasu powodzenia tego etapu."
                        ),
                        "warning"
                    )
                    self._render_step3_rework_actions(extra_frame)
                    btn.config(text=step_btn_txt, style="Accent.TButton", state="normal")
                else:
                    if s == 4:
                        if iteration_target == "plate":
                            self._set_roadmap_note(
                                item,
                                "W E4 zbudujesz dataset tablic z XML CVAT i uruchomisz trening modelu YOLO Pose dla tablic rejestracyjnych.",
                                "info"
                            )
                        elif iteration_target == "char":
                            self._set_roadmap_note(
                                item,
                                "W E4 przygotujesz dataset znaków i uruchomisz trening modelu YOLO Detect dla znaków na tablicach.",
                                "info"
                            )
                        else:
                            self._set_roadmap_note(item, "")
                    else:
                        self._set_roadmap_note(item, "")
                    btn.config(text=step_btn_txt, style="Accent.TButton", state="normal")

            else:
                self._set_roadmap_card_border(item)
                item["lbl_title"].config(text=f"⚪ {step_title}", fg=muted)

                if s == 3 and iteration_target == "plate":
                    self._set_roadmap_note(
                        item,
                        "Ten etap nie będzie użyty w torze tablic. Po zatwierdzeniu E2 wizard przejdzie od razu do E4.",
                        "info"
                    )
                elif s == 3 and iteration_target == "char" and curr_step == 2:
                    if self._get_char_route_ready_source():
                        self._set_roadmap_note(
                            item,
                            "Masz już gotowe ręczne tablice dla tej paczki. Przycisk E2 może od razu przenieść Cię tutaj, aby zacząć wycinanie tablic i anotację znaków.",
                            "success"
                        )
                    else:
                        self._set_roadmap_note(
                            item,
                            "Po przygotowaniu i zatwierdzeniu tablic w E2 tutaj wytniesz tablice, uruchomisz OCR i zbudujesz dataset znaków.",
                            "info"
                        )
                elif s == 4 and iteration_target == "plate" and curr_step == 2:
                    self._set_roadmap_note(
                        item,
                        "Po ręcznej anotacji Z2 tutaj zbudujesz dataset tablic z XML CVAT i wytrenujesz model Pose.",
                        "info"
                    )
                else:
                    self._set_roadmap_note(item, "")

                btn.config(text=step_btn_txt, style="TButton", state="disabled")

        self._update_main_tabs_highlight(curr_step=curr_step, has_project=True)
        self.app.update_campaign_tab_access()
        self.frame.update_idletasks()
        self.frame.after_idle(self._sync_right_panel_scrollregion)

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

    def _refresh_projects_list(self):
        """Zachowane dla spójności API; wybór projektu odbywa się przez popup."""
        return

    def _on_project_changed(self, event=None):
        """Pozostawione dla kompatybilności; obecnie nieużywane."""
        return

    def _open_selected_project(self):
        """Aktywuje projekt wybrany z listy i włącza tryb kampanii."""
        selected = self._ask_project_from_list(
            title="Otwórz projekt",
            action_label="Otwórz"
        )
        if not selected:
            return

        CAMPAIGN.set_active_project(selected)
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)
        self._rebuild_roadmap_ui()
        self._refresh_dashboard()
        self.app.update_campaign_tab_access()
        try:
            annotation_tab = self.app.tabs.get("annotation")
            if annotation_tab is not None and hasattr(annotation_tab, "restore_campaign_context_from_project"):
                annotation_tab.restore_campaign_context_from_project()
        except Exception as e:
            logger.debug(f"Nie udało się przywrócić kontekstu Z2 po otwarciu projektu: {e}")

        try:
            self.app.update_status(
                f"Aktywowano projekt: {selected}. Aplikacja działa w trybie kampanii.",
                "info"
            )
        except Exception:
            pass
        
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

    def _delete_project(self):
        selected = self._ask_project_from_list(
            title="Usuń projekt",
            action_label="Usuń"
        )
        if not selected:
            return

        if self.app.themed_confirm(
            "Usuwanie projektu",
            f"Usunąć projekt '{selected}' wraz z całym katalogiem projektu?",
            parent=self.frame,
            confirm_label="Usuń",
            tone="warning"
        ):
            was_active = (CAMPAIGN.get_active_project_name() == selected)

            if CAMPAIGN.delete_project(selected):
                if was_active:
                    self._clear_project_contexts()
                    self.app.campaign_free_mode = True
                    self.app.set_campaign_mode(False)

                self._rebuild_roadmap_ui()
                self._refresh_dashboard()
                self.app.update_campaign_tab_access()

                self.app.themed_info(
                    "Usunięto",
                    f"Projekt '{selected}' został usunięty.",
                    parent=self.frame,
                    tone="success"
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

        try:
            annotation_tab = self.app.tabs.get("annotation")
            if annotation_tab is not None and hasattr(annotation_tab, "capture_free_mode_snapshot_for_project_return"):
                annotation_tab.capture_free_mode_snapshot_for_project_return()
        except Exception as e:
            logger.debug(f"Nie udało się zapisać migawki free mode przed otwarciem projektu: {e}")

        CAMPAIGN.set_active_project(selected)
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)
        self._rebuild_roadmap_ui()
        self._refresh_dashboard()
        self.app.update_campaign_tab_access()
        try:
            annotation_tab = self.app.tabs.get("annotation")
            if annotation_tab is not None and hasattr(annotation_tab, "restore_campaign_context_from_project"):
                annotation_tab.restore_campaign_context_from_project()
        except Exception as e:
            logger.debug(f"Nie udało się przywrócić kontekstu Z2 po otwarciu projektu: {e}")

        try:
            self.app.update_status(
                f"Aktywowano projekt: {selected}. Aplikacja działa w trybie kampanii.",
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

            # czyścimy projektowy kontekst innych zakładek
            self._clear_project_contexts()

            # odświeżamy dashboard
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()

            # finalna synchronizacja dostępności zakładek
            self.app.update_campaign_tab_access()

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

        copied = 0
        copied_source_files = []
        for img_file in image_files:
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
        )

        try:
            self.app.update_status(
                f"✅ Skopiowano {copied} nowych zdjęć do Iteracji {iter_num:03d}. Odblokowano Krok 2.",
                "info"
            )
        except Exception:
            pass

        messagebox.showinfo(
            "Przygotowanie zestawu zdjęć zakończone",
            f"Skopiowano {copied} zdjęć do:\n{target_iter_dir}\n\n"
            f"Każda iteracja pracuje tylko na swojej NOWEJ paczce wejściowej."
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
        char_source_state = self._get_char_route_source_state() if iteration_target == "char" else {}
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

        try:
            result = tab_ann.open_campaign_step2_entry(
                iteration_target=iteration_target,
                entry_strategy=entry_strategy,
                restore_preview=bool(not force_annotation_tab and not char_has_existing_source),
                open_existing_run=open_existing_run,
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
        ready_run_name = ""
        try:
            if ready_run_dir is not None:
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

        tab_char = self.app.tabs.get("characters")
        if not tab_char:
            return

        try:
            frame = getattr(tab_char, "frame", None)
            refresh_state = {}
            if hasattr(tab_char, "_prepare_campaign_step3_reextract_from_current_source"):
                refresh_state = tab_char._prepare_campaign_step3_reextract_from_current_source(
                    preferred_source_context=preferred_source_context
                ) or {}

            if bool(refresh_state.get("needs_reextract")):
                self.app.update_status(
                    str(refresh_state.get("message") or "Źródło z Z2 zmienilo się. Najpierw uruchom ponowne wycinanie tablic w PZ1."),
                    "warning",
                )
                return

            if frame is not None and hasattr(tab_char, "go_to_substep_2"):
                frame.after(0, tab_char.go_to_substep_2)
            elif hasattr(tab_char, "go_to_substep_2"):
                tab_char.go_to_substep_2()
            self.app.update_status(
                "Otwieram Z3/PZ2, aby poprawic anotacje znaków na istniejących tablicach.",
                "info",
            )
        except Exception as e:
            logger.debug(f"Nie udało się przelaczyc Z3 do PZ2: {e}")

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

        try:
            folder_name = Path(images_dir).name if images_dir else ""
        except Exception:
            folder_name = ""

        try:
            if latest_xml:
                if using_preferred_source and preferred_run_dir is not None:
                    self.app.update_status(
                        f"Ustawiono Z3 na gotowe ręczne tablice: XML={preferred_run_dir.name}/annotations.xml | IMG={folder_name}.",
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

            datasets_dir = CAMPAIGN.get_dir("datasets")
            runs_dir = CAMPAIGN.get_dir("runs")

            if datasets_dir is None:
                logger.error("Brak katalogu datasets dla aktywnego projektu.")
                return

            tab_train = self.app.tabs.get("training")
            if not tab_train:
                logger.error("Nie znaleziono zakładki TrainingTab w app.tabs.")
                return

            try:
                tab_train.set_campaign_training_target(iteration_target)
            except Exception:
                pass

            # Przełącz TrainingTab na kontekst aktywnego projektu.
            tab_train.set_campaign_context(
                runs_dir=str(runs_dir) if runs_dir is not None else None,
                datasets_dir=str(datasets_dir)
            )

            datasets_dir = Path(datasets_dir)
            source_candidates = []
            try:
                for path in tab_train._find_dataset_source_candidates(datasets_dir):
                    inferred = tab_train._infer_dataset_target(str(path))
                    if iteration_target == "char":
                        if inferred != "char":
                            continue
                    elif inferred not in {"plate", None}:
                        continue
                    source_candidates.append(path)
            except Exception:
                source_candidates = []

            latest_source = None
            if source_candidates:
                latest_source = max(source_candidates, key=lambda p: p.stat().st_mtime)

            if iteration_target == "char" and latest_source is not None:
                tab_train.split_src_var.set(str(latest_source))
                tab_train.split_out_var.set(
                    str(latest_source.parent / f"{latest_source.name}_Split_[DATA_I_CZAS]")
                )
            elif iteration_target == "char":
                tab_train.split_src_var.set("")
                tab_train.split_out_var.set(str(datasets_dir / "[BRAK_DATASETU_ZRODLOWEGO]"))

            if iteration_target == "plate":
                plate_model = CAMPAIGN.get_global_model("plate")
                preferred_pose = "yolo11s-pose"
                pose_choices = []
                try:
                    pose_choices = tab_train._get_base_model_choices_for_mode("plate")
                except Exception:
                    pose_choices = []

                if plate_model and Path(plate_model).exists():
                    tab_train.base_model_var.set("Custom")
                    tab_train.base_custom_var.set(plate_model)
                else:
                    tab_train.base_model_var.set(
                        preferred_pose if preferred_pose in pose_choices else tab_train._get_default_base_model_for_mode("plate")
                    )
                    tab_train.base_custom_var.set("")
            else:
                char_model = CAMPAIGN.get_global_model("char")
                if char_model and Path(char_model).exists():
                    tab_train.base_model_var.set("Custom")
                    tab_train.base_custom_var.set(char_model)
                else:
                    tab_train.base_model_var.set("yolo11n")
                    tab_train.base_custom_var.set("")

            tab_train._on_base_model_change()

            try:
                tab_train.imgsz_var.set(640 if iteration_target == "plate" else 256)
            except Exception:
                pass

            try:
                if iteration_target == "plate":
                    dataset_var = getattr(tab_train, "dataset_var", None)
                    dataset_hint = str(dataset_var.get() if dataset_var is not None else "").strip()
                    if dataset_hint:
                        self.app.update_status(
                            f"Ustawiono tor treningu tablic: gotowy dataset = {Path(dataset_hint).name}, źródła XML z Z2 i model Pose.",
                            "info"
                        )
                    else:
                        self.app.update_status(
                            "Przełączono do Treningu w torze tablic. Zbuduj dataset z XML CVAT i uruchom trening modelu Pose.",
                            "info"
                        )
                elif latest_source is not None:
                    self.app.update_status(
                        f"Ustawiono automatycznie Trening: źródło splittera = {latest_source.name}, wynik splitu w katalogu projektu oraz model DETECT dla znaków.",
                        "info"
                    )
                else:
                    self.app.update_status(
                        "Przełączono do Treningu w kontekście projektu, ale nie znaleziono jeszcze datasetu źródłowego w 4_training_datasets.",
                        "warning"
                    )
            except Exception:
                pass

            self.app.open_controlled_tab("training")

        except Exception as e:
            logger.error(f"Błąd nawigacji (Krok 4): {e}")

    def _advance_iteration(self):
        mode = self._ask_iteration_advance_mode()
        if not mode:
            return

        result = CAMPAIGN.advance_to_next_iteration(start_mode=mode)
        if not result.get("ok"):
            reason = str(result.get("reason") or "").strip().lower()
            if reason == "missing_remaining_images":
                self.app.themed_info(
                    "Brak kolejnej paczki",
                    (
                        "Nie ma już nieużytych zdjęć w tej samej puli projektu.\n\n"
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

        if CAMPAIGN.is_project_completed():
            if self.app.themed_confirm(
                "Wznowienie projektu",
                f"Czy wznowić projekt '{active_project}'?\n\n"
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
                        f"Projekt '{active_project}' został wznowiony. Możesz rozpocząć kolejną iterację.",
                        "info"
                    )
                except Exception:
                    pass
            return

        if CAMPAIGN.get_current_step() < 5:
            return

        if self.app.themed_confirm(
            "Zakończenie projektu",
            f"Czy oznaczyć projekt '{active_project}' jako zakończony?\n\n"
            "Projekt pozostanie dostępny do podglądu i można go będzie później wznowić.",
            parent=self.frame,
            confirm_label="Zakończ projekt",
            tone="info"
        ):
            CAMPAIGN.complete_project()
            self._refresh_dashboard()
            self.app.update_campaign_tab_access()
            try:
                self.app.update_status(
                    f"Projekt '{active_project}' został oznaczony jako zakończony.",
                    "info"
                )
            except Exception:
                pass
