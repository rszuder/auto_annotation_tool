#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Rozkład Jazdy (Dashboard Kampanii MLOps)..
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from textwrap import shorten
from collections import Counter
from datetime import datetime
import os
import shutil
import webbrowser

from ..config import CONFIG, logger
from ..campaign_manager import CAMPAIGN
from ..campaign_ingest_planner import CHAR_ALPHABET, CampaignIngestPlanner
from ..icons import IconManager
from .help_manager import HELP
from .web_slim_scrollbar import WebSlimScrollbar


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
        self.ingest_list_title_lbl = None
        self.ingest_logic_lbl = None
        self.ingest_selection_lbl = None
        self.ingest_balance_canvas = None
        self.ingest_balance_summary_lbl = None
        self.ingest_insights_shell = None
        self.ingest_chart_panel = None
        self.ingest_info_panel = None

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
        header_f = ttk.Frame(self.frame, padding=15)
        header_f.pack(fill=tk.X)
        header_f.columnconfigure(0, weight=0)
        header_f.columnconfigure(1, weight=1)
        header_f.columnconfigure(2, weight=0)

        self.lbl_title = tk.Label(
            header_f,
            text="MENEDŻER KAMPANII (PROJEKTY)",
            font=("Segoe UI", 16, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("bg", "#1e1e1e")
        )
        self.lbl_title.grid(row=0, column=0, sticky="w")

        proj_frame = ttk.Frame(header_f)
        proj_frame.grid(row=0, column=1, sticky="w", padx=(20, 0))

        self.btn_add_proj = ttk.Button(proj_frame, text="Nowy projekt", command=self._add_new_project)
        self.btn_add_proj.pack(side=tk.LEFT, padx=5)

        self.btn_open_proj = ttk.Button(proj_frame, text="Otwórz projekt", command=self._open_selected_project)
        self.btn_open_proj.pack(side=tk.LEFT, padx=5)

        self.btn_del_proj = ttk.Button(proj_frame, text="Usuń projekt", command=self._delete_project)
        self.btn_del_proj.pack(side=tk.LEFT, padx=5)

        self.btn_exit_project = ttk.Button(proj_frame, text="Wyjdź z projektu", command=self._exit_project_mode)
        self.btn_exit_project.pack(side=tk.LEFT, padx=5)

        self.lbl_iter = tk.Label(
            header_f,
            text="Iteracja: -",
            font=("Segoe UI", 14, "bold"),
            fg=palette.get("warning", "#ffb3b3"),
            bg=palette.get("surface_warning", palette.get("panel_alt", "#3a2323")),
            padx=10,
            pady=5
        )
        self.lbl_iter.grid(row=0, column=2, sticky="e", padx=(12, 0))

        # Baner aktywnego projektu.
        self.lbl_campaign_banner = tk.Label(
            self.frame,
            text="",
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("warning", "#ffd37a"),
            bg=palette.get("surface_info", palette.get("panel_alt", "#33250f")),
            padx=10,
            pady=6,
            anchor="w",
            justify=tk.LEFT
        )
        self.lbl_campaign_banner.pack(fill=tk.X, padx=15, pady=(0, 8))

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
            text=" Wiedza Algorytmów (Aktywny Projekt) ",
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
            text="Mózg projektu (aktualizuje się automatycznie po treningu).\n"
                 "Przycisk 'Zmień' to ręczna korekta.",
            justify=tk.LEFT,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526")
        )
        self.left_panel_hint_lbl.pack(anchor=tk.W, pady=(0, 15))
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
        self.project_assets_row.pack(fill=tk.X, pady=(8, 0))

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

        HELP.bind_help(self.btn_add_proj, "camp_new_project")
        HELP.bind_help(self.btn_open_proj, "camp_open_project")
        HELP.bind_help(self.btn_del_proj, "camp_delete_project")
        HELP.bind_help(self.btn_exit_project, "camp_exit_project")
        HELP.bind_help(left_panel, "camp_models")
        HELP.bind_help(self.btn_advance, "camp_advance")
        HELP.bind_help(self.btn_complete_project, "camp_advance")
        HELP.bind_help(self.btn_review_training, "camp_advance")
        HELP.bind_help(self.btn_open_project_models, "camp_models")
        HELP.bind_help(self.btn_open_project_datasets, "camp_advance")

        # LEFT MAIN PANEL: workflow
        self.right_panel = ttk.LabelFrame(
            main_container,
            text=" Rozkład Jazdy (Cykl Active Learningu) ",
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
            return "break"
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

        status_fonts = [
            ("Segoe UI", 9, "bold"),
            ("Segoe UI", 9),
            ("Segoe UI", 9),
        ]
        for font_spec in status_fonts:
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
            line3 = "Najpierw wskaż główną pulę zdjęć."
        else:
            line3 = ""
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

    def _choose_master_pool_dir(self):
        if not CAMPAIGN.get_active_project_name():
            return

        current = CAMPAIGN.get_master_pool_dir()
        initial = current if current and current.exists() else Path(CONFIG.DIR_1_RAW)
        selected = filedialog.askdirectory(
            initialdir=str(initial),
            title="Wybierz katalog głównej puli zdjęć dla aktywnego projektu",
        )
        if not selected:
            return

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
            self.lbl_title.config(bg=bg, fg=fg)
        except Exception:
            pass

        try:
            self.lbl_iter.config(bg=palette.get("surface_warning", panel_alt))
        except Exception:
            pass

        try:
            self.lbl_campaign_banner.config(bg=panel_alt)
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
                "Możesz kontynuować pracę na tym samym zestawie zdjęć "
                "albo zacząć nową iterację od wskazania nowego zestawu zdjęć."
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
            title="Ten sam zestaw zdjęć",
            description=(
                "System przeniesie wejściowy zestaw zdjęć z poprzedniej iteracji "
                "i od razu wrócisz do wyboru toru w E2."
            ),
            button_text="Ten sam zestaw -> E2",
            mode="reuse_input",
            accent=True,
        )
        add_option(
            title="Nowy zestaw zdjęć",
            description=(
                "Nowa iteracja zacznie się od E1, aby wskazać całkiem nowy "
                "zestaw zdjęć wejściowych."
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
            CAMPAIGN.set_global_model(model_type, p)
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
            "E2. Wizard przygotowuje tablice dla wybranego toru: prowadzi przez Z2 albo, gdy masz już dobre ręczne tablice dla tej paczki, pomija Z2 i przechodzi dalej do Z3.",
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
            logger.debug(f"Nie udalo sie pobrac bootstrapu Z2 dla toru {target}: {e}")
            return {}

        return dict(bootstrap) if isinstance(bootstrap, dict) else {}

    def _get_char_route_ready_source(self) -> dict:
        if CAMPAIGN.get_step2_status() == "generated":
            return {}

        bootstrap = self._get_annotation_bootstrap_for_target("char")
        if not bootstrap:
            return {}

        restore_run_dir = bootstrap.get("restore_run_dir")
        if restore_run_dir is None:
            return {}

        try:
            restore_run_dir = Path(restore_run_dir)
        except Exception:
            return {}

        if not restore_run_dir.exists() or not restore_run_dir.is_dir():
            return {}
        if not (restore_run_dir / "annotations.xml").exists():
            return {}

        annotation_tab = getattr(self.app, "tabs", {}).get("annotation")
        if annotation_tab is None:
            return {}

        try:
            manifest = annotation_tab._load_annotation_run_manifest(restore_run_dir)
            manual_ready = bool(annotation_tab._annotation_run_manifest_has_manual_value(manifest))
        except Exception:
            manual_ready = False

        if not manual_ready:
            return {}

        bootstrap["restore_run_dir"] = restore_run_dir
        return bootstrap

    def _get_step2_jump_button_text(self, target: str) -> str:
        target = self._normalize_iteration_target(target)

        if target == "plate":
            bootstrap = self._get_annotation_bootstrap_for_target("plate")
            manual_template = bool(bootstrap.get("manual_template", True))
            return "Skocz: Z2 ręczna anotacja" if manual_template else "Skocz: Z2 autoanotacja tablic"

        if target == "char":
            if CAMPAIGN.get_step2_status() == "generated":
                return "Skocz: Sprawdz tablice w Z2"
            if self._get_char_route_ready_source():
                return "Skocz: Z3 z gotowych tablic"
            return "Skocz: Przygotuj tablice w Z2"

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
                return "A. Kontynuuj tor tablic -> dotrenuj model YOLO Pose"
            return "A. Tablice -> reczna anotacja + trening modelu YOLO Pose"

        if route == "char":
            if not current_target and last_target == "char":
                return "B. Kontynuuj tor znakow -> dotrenuj model YOLO Detect"
            return "B. Znaki -> przygotuj tablice + Z3 + trening modelu YOLO Detect"

        return ""

    def _get_step2_status_content(
        self,
        *,
        current_target: str = "",
        last_target: str = "",
        plate_model_ready: bool = False,
        char_manual_ready: bool = False,
    ) -> dict:
        palette = getattr(self.app, "palette", {})
        current_target = self._normalize_iteration_target(current_target)
        last_target = self._normalize_iteration_target(last_target)

        status = {
            "title": "Status E2",
            "text": "Nie wybrano jeszcze trybu iteracji. Wybierz Tryb A albo Tryb B.",
            "bg": palette.get("surface_info", palette.get("panel_alt", "#2d3640")),
            "border": palette.get("accent", "#2980b9"),
            "title_fg": palette.get("fg", "#f3f3f3"),
            "body_fg": palette.get("muted", "#c7c7c7"),
        }

        if current_target == "plate":
            status.update(
                title="Wybrano tryb A",
                text=(
                    "Kontynuujesz tor tablic z poprzedniej iteracji. Z2 moze posluzyc do dalszej anotacji i dotrenowania modelu YOLO Pose."
                    if last_target == "plate"
                    else "Tor tablic: Z2 utworzy pusty annotations.xml dla surowego zestawu zdjęć, a po zatwierdzeniu E2 wizard przejdzie od razu do E4."
                ),
                bg=palette.get("surface_success", palette.get("panel_alt", "#1f3320")),
                border=palette.get("success", "#27ae60"),
                body_fg=palette.get("fg", "#f3f3f3"),
            )
            return status

        if current_target == "char":
            status.update(
                title="Wybrano tryb B",
                text=(
                    "Kontynuujesz tor znakow z poprzedniej iteracji. Wizard wykorzysta gotowe reczne anotacje tablic i przejdzie od razu do Z3, gdzie przygotujesz kolejna pule danych do dotrenowania modelu YOLO Detect."
                    if char_manual_ready and last_target == "char"
                    else (
                        "Masz juz gotowe reczne anotacje tablic dla tej paczki. Wizard moze pominac Z2 i przejsc od razu do Z3, gdzie zaczniesz prace nad znakami."
                        if char_manual_ready
                        else "Tor znakow: najpierw przygotuj tablice aktywnym modelem projektu, potem E3 zbuduje dane znakow, a E4 uruchomi trening YOLO Detect."
                    )
                ),
                bg=palette.get("surface_success", palette.get("panel_alt", "#1f3320")),
                border=palette.get("success", "#27ae60"),
                body_fg=palette.get("fg", "#f3f3f3"),
            )
            return status

        if last_target == "plate":
            status.update(
                title="Poprzednia iteracja: tryb A",
                text=(
                    "W poprzedniej iteracji budowales model tablic. Mozesz kontynuowac ten tor i dotrenowac model YOLO Pose albo swiadomie przelaczyc sie na tor znakow."
                    + (" Projekt ma juz aktywny model tablic, wiec Z2 moze wystartowac od autoanotacji i korekt." if plate_model_ready else "")
                ),
                body_fg=palette.get("fg", "#f3f3f3"),
            )
            return status

        if last_target == "char":
            status.update(
                title="Poprzednia iteracja: tryb B",
                text="W poprzedniej iteracji budowales model znakow. Mozesz kontynuowac ten tor albo zmienic go teraz na tor tablic dla tej iteracji.",
                body_fg=palette.get("fg", "#f3f3f3"),
            )
            return status

        if not plate_model_ready:
            status.update(
                title="Tryb B jeszcze niedostepny",
                text="Tor znakow odblokuje sie, gdy projekt bedzie mial gotowy model tablic Pose.",
                bg=palette.get("surface_warning", palette.get("panel_alt", "#3a2323")),
                border=palette.get("warning", "#d35400"),
                body_fg=palette.get("warning", "#d35400"),
            )

        return status

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

        if target == "char":
            plate_model = str(CAMPAIGN.get_global_model("plate") or "").strip()
            if not plate_model or not Path(plate_model).exists():
                messagebox.showwarning(
                    "Brak modelu tablic",
                    "Tor znaków wymaga istniejącego modelu tablic Pose w projekcie.\n\n"
                    "Najpierw zbuduj tor tablic i wytrenuj model tablic, a potem wróć do E2 dla toru znaków."
                )
                return

        previous_target = self._normalize_iteration_target(CAMPAIGN.get_iteration_target())
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
                logger.debug(f"Nie udalo sie wyczyscic stanu Z2 po zmianie toru E2: {e}")

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
                        f"Wybrano Tryb A. Kontynuujesz tor tablic z poprzedniej iteracji; uzyj przycisku '{jump_label}', gdy chcesz przejsc dalej."
                        if continuing_previous_iteration_route
                        else (
                            f"Wybrano Tryb A. Pozostajesz w E2; uzyj przycisku '{jump_label}', gdy chcesz przejsc dalej."
                            if not route_changed
                            else f"Wybrano Tryb A. Poprzedni stan Z2 tej iteracji zostal zresetowany; przejdz dalej przyciskiem '{jump_label}'."
                        )
                    ),
                    "info"
                )
            else:
                self.app.update_status(
                    (
                        f"Wybrano Tryb B. Kontynuujesz tor znakow z poprzedniej iteracji; uzyj przycisku '{jump_label}', gdy chcesz przejsc dalej."
                        if continuing_previous_iteration_route
                        else (
                            f"Wybrano Tryb B. Pozostajesz w E2; uzyj przycisku '{jump_label}', gdy chcesz przejsc dalej."
                            if not route_changed
                            else f"Wybrano Tryb B. Poprzedni stan Z2 tej iteracji zostal zresetowany; przejdz dalej przyciskiem '{jump_label}'."
                        )
                    ),
                    "info"
                )
        except Exception:
            pass

    def _render_step2_route_actions_legacy(self, frame):
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        target = self._get_iteration_target()
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())

        for w in frame.winfo_children():
            w.destroy()

        frame.configure(bg=card_bg)
        frame.pack(fill=tk.X, pady=(6, 0))

        intro_text = (
            "Wybierz cel tej iteracji. Ten wybór ustawia domyślne ścieżki Z2, dalszy krok wizarda "
            "i docelowy tor treningu."
            if not target
            else f"Wybrany cel iteracji: {self._iteration_target_label(target)}. Możesz jeszcze zmienić wybór przed zatwierdzeniem E2."
        )
        tk.Label(
            frame,
            text=intro_text,
            fg=palette.get("muted", "#c7c7c7"),
            bg=card_bg,
            justify=tk.LEFT,
            wraplength=520
        ).pack(anchor=tk.W, pady=(0, 4))

        btn_row = tk.Frame(frame, bg=card_bg)
        btn_row.pack(anchor=tk.W, fill=tk.X)

        btn_plate = ttk.Button(
            btn_row,
            text="A. Tablice → ręczna anotacja + trening Pose",
            command=lambda: self._step2_choose_iteration_target("plate")
        )
        btn_plate.pack(side=tk.LEFT, padx=(0, 8))

        btn_char = ttk.Button(
            btn_row,
            text="B. Znaki → Z2 + Z3 + trening DETECT",
            command=lambda: self._step2_choose_iteration_target("char")
        )
        btn_char.pack(side=tk.LEFT)

        if target == "plate":
            btn_plate.configure(state=tk.DISABLED)
        elif target == "char":
            btn_char.configure(state=tk.DISABLED)
        elif not plate_model_ready:
            btn_char.configure(state=tk.DISABLED)

        if target == "plate":
            tk.Label(
                frame,
                text="Tor A: Z2 utworzy pusty annotations.xml dla surowego zestawu zdjęć, a po zatwierdzeniu E2 wizard przejdzie od razu do E4.",
                fg=palette.get("muted", "#c7c7c7"),
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=520
            ).pack(anchor=tk.W, pady=(4, 0))
        elif target == "char":
            tk.Label(
                frame,
                text="Tor B: Z2 przygotuje anotacje tablic, potem E3 zbuduje dane znaków, a E4 uruchomi trening YOLO Detect.",
                fg=palette.get("muted", "#c7c7c7"),
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=520
            ).pack(anchor=tk.W, pady=(4, 0))

        if not plate_model_ready and target != "char":
            tk.Label(
                frame,
                text="Tor znaków odblokuje się, gdy projekt będzie miał gotowy model tablic Pose.",
                fg=palette.get("warning", "#d35400"),
                bg=card_bg,
                justify=tk.LEFT,
                wraplength=520
            ).pack(anchor=tk.W, pady=(4, 0))

        HELP.bind_help(frame, "camp_step2")
        HELP.bind_help(btn_row, "camp_step2")
        HELP.bind_help(btn_plate, "camp_step2")
        HELP.bind_help(btn_char, "camp_step2")

    def _render_step2_route_actions(self, frame):
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))
        target = self._get_iteration_target()
        last_target = self._get_last_iteration_target()
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())

        for widget in frame.winfo_children():
            widget.destroy()

        frame.configure(bg=card_bg)
        frame.pack(fill=tk.X, pady=(6, 0))

        intro_text = (
            "Wybierz cel tej iteracji. Ten wybor ustawia domyslne sciezki Z2, dalszy krok wizarda i docelowy tor treningu."
            if not target
            else f"Wybrany cel iteracji: {self._iteration_target_label(target)}. Mozesz jeszcze zmienic wybor przed zatwierdzeniem E2."
        )
        tk.Label(
            frame,
            text=intro_text,
            fg=palette.get("muted", "#c7c7c7"),
            bg=card_bg,
            justify=tk.LEFT,
            wraplength=520,
        ).pack(anchor=tk.W, pady=(0, 4))

        btn_row = tk.Frame(frame, bg=card_bg)
        btn_row.pack(anchor=tk.W, fill=tk.X)

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

        if target == "plate":
            btn_plate.configure(state=tk.DISABLED)
        elif target == "char":
            btn_char.configure(state=tk.DISABLED)
        elif not plate_model_ready:
            btn_char.configure(state=tk.DISABLED)

        status_cfg = self._get_step2_status_content(
            current_target=target,
            last_target=last_target,
            plate_model_ready=plate_model_ready,
            char_manual_ready=bool(target == "char" and self._get_char_route_ready_source()),
        )
        status_title = status_cfg["title"]
        status_text = status_cfg["text"]
        status_bg = status_cfg["bg"]
        status_border = status_cfg["border"]
        status_title_fg = status_cfg["title_fg"]
        status_body_fg = status_cfg["body_fg"]

        status_shell = tk.Frame(
            frame,
            bg=status_bg,
            bd=0,
            highlightthickness=1,
            highlightbackground=status_border,
            highlightcolor=status_border,
        )
        status_shell.pack(fill=tk.X, pady=(8, 0))

        status_panel = tk.Frame(status_shell, bg=status_bg, bd=0, highlightthickness=0)
        status_panel.pack(fill=tk.X, padx=12, pady=10)

        tk.Label(
            status_panel,
            text=status_title,
            fg=status_title_fg,
            bg=status_bg,
            justify=tk.LEFT,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W, fill=tk.X)

        tk.Label(
            status_panel,
            text=status_text,
            fg=status_body_fg,
            bg=status_bg,
            justify=tk.LEFT,
            anchor="w",
            wraplength=520,
        ).pack(anchor=tk.W, fill=tk.X, pady=(4, 0))

        if target == "char" and self._get_char_route_ready_source():
            action_row = tk.Frame(status_panel, bg=status_bg)
            action_row.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

            ttk.Button(
                action_row,
                text="Przejdz od razu do Z3",
                command=self._step_goto_auto_annotation,
            ).pack(side=tk.LEFT)

            ttk.Button(
                action_row,
                text="Kontynuuj reczna anotacje w Z2",
                command=lambda: self._step_goto_auto_annotation(force_annotation_tab=True),
            ).pack(side=tk.LEFT, padx=(8, 0))

        HELP.bind_help(frame, "camp_step2")
        HELP.bind_help(btn_row, "camp_step2")
        HELP.bind_help(btn_plate, "camp_step2")
        HELP.bind_help(btn_char, "camp_step2")

    def _render_step3_rework_actions(self, frame):
        """Renderuje dodatkowe akcje naprawcze dla kroku 3."""
        palette = getattr(self.app, "palette", {})
        card_bg = str(frame.cget("bg") or palette.get("panel", "#252526"))

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

        btn_row = tk.Frame(frame, bg=card_bg)
        btn_row.pack(anchor=tk.W)

        btn_auto = ttk.Button(
            btn_row,
            text="↩ Autoanotacja",
            command=self._rework_step3_via_auto_annotation
        )
        btn_auto.pack(side=tk.LEFT, padx=(0, 8))

        btn_ocr = ttk.Button(
            btn_row,
            text=" Popraw OCR",
            command=self._rework_step3_via_ocr
        )
        btn_ocr.pack(side=tk.LEFT)

        HELP.bind_help(frame, "camp_step3")
        HELP.bind_help(btn_row, "camp_step3")
        HELP.bind_help(btn_auto, "camp_step3")
        HELP.bind_help(btn_ocr, "camp_step3")

    def _rework_step3_via_auto_annotation(self):
        """
        Uruchamia ścieżkę naprawczą przez ponowną autoanotację.
        Cofnij workflow do kroku 2 i unieważnij krok 3.
        """
        try:
            CAMPAIGN.set_current_step(2)
            CAMPAIGN.reset_step3()

            self._refresh_dashboard()
            self.app.update_campaign_tab_access()

            try:
                self.app.update_status(
                    "Wybrano ścieżkę naprawczą przez Autoanotację. Workflow cofnięto do Kroku 2.",
                    "warning"
                )
            except Exception:
                pass

            self._step_goto_auto_annotation()

        except Exception as e:
            logger.error(f"Błąd przejścia do ścieżki naprawczej Autoanotacji: {e}")

    def _rework_step3_via_ocr(self):
        """
        Ścieżka naprawcza OCR dla Kroku 3.
        Ma zawsze prowadzić do z3/pz2, a nie do ostatnio zapamiętanego pz3.
        """
        try:
            CAMPAIGN.set_current_step(3)
            CAMPAIGN.set_step3_needs_rework()
            CAMPAIGN.set_step3_substep(2)
            CAMPAIGN.set_step3_stage1_done(True)
            CAMPAIGN.set_step3_stage2_done(False)

            self._refresh_dashboard()
            self.app.update_campaign_tab_access()

            try:
                self.app.update_status(
                    "Wybrano ścieżkę naprawczą OCR. Przechodzę do Kroku 3 / pz2.",
                    "warning"
                )
            except Exception:
                pass

            self._step_goto_characters()

        except Exception as e:
            logger.error(f"Błąd przejścia do ścieżki naprawczej OCR: {e}")

    # ======================================================
    # DASHBOARD REFRESH
    # ======================================================

    def _refresh_dashboard(self):
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

        active_proj = CAMPAIGN.get_active_project_name()
        has_project = bool(active_proj)
        projects_available = bool(CAMPAIGN.get_all_projects())

        # ======================================================
        # TRYB SWOBODNY / BRAK AKTYWNEGO PROJEKTU
        # ======================================================
        if not has_project:
            self.app.campaign_free_mode = True
            self.app.set_campaign_mode(False)

            self.lbl_iter.config(text="Iteracja: -", fg=muted, bg=surface_info)
            self.lbl_campaign_banner.config(
                text="TRYB SWOBODNY — brak aktywnego projektu. Wybierz projekt z listy i kliknij „Otwórz projekt” albo utwórz nowy.",
                fg=muted,
                bg=surface_info
            )

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
        project_completed = CAMPAIGN.is_project_completed()
        project_completed_at = CAMPAIGN.get_project_completed_at()
        step1_approved = step1_status == "approved"
        if curr_step >= 2 and not step1_approved and self._get_iteration_image_count() > 0:
            CAMPAIGN.approve_step1()
            step1_status = "approved"
            step1_approved = True

        if not iteration_target and (curr_step >= 3 or step3_status != "pending"):
            CAMPAIGN.set_iteration_target("char")
            iteration_target = "char"

        if iteration_target == "plate" and curr_step == 3 and step2_status == "approved":
            CAMPAIGN.set_current_step(4)
            curr_step = 4

        logger.debug(
            f"[CampaignTab] active_proj={active_proj}, curr_step={curr_step}, "
            f"step2_status={step2_status}, step3_status={step3_status}"
        )
        iter_num = CAMPAIGN.get_current_iteration_num()

        banner_text = (
            f"AKTYWNY PROJEKT: {active_proj}  |  TRYB KAMPANII WŁĄCZONY\n"
            "Masz włączone sterowanie workflow. Aby wrócić do trybu swobodnego, kliknij „Wyjdź z projektu”."
        )
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
            banner_text = (
                f"AKTYWNY PROJEKT: {active_proj}  |  PROJEKT ZAKOŃCZONY\n"
                f"Projekt został oznaczony jako zakończony: {completed_display}. "
                "Masz nadal dostęp do Z4 oraz folderów modeli i datasetów. "
                "Możesz go też wznowić, jeśli chcesz uruchomić kolejną iterację."
            )
            banner_fg = warning
            banner_bg = surface_warning

        self.lbl_iter.config(text=f"Iteracja: {iter_num}", fg=warning, bg=surface_warning)
        self.lbl_campaign_banner.config(text=banner_text, fg=banner_fg, bg=banner_bg)

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
                text="🎉 Cykl zakończony → Nowa iteracja",
                state="normal",
                style="Accent.TButton"
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
                        btn.config(text=step_btn_txt, style="TButton", state="disabled")
                    else:
                        if iteration_target == "plate":
                            if step2_status == "generated":
                                note_text = (
                                    "Utworzono już run ręcznej anotacji. Przejdź do Autoanotacji, dodaj lub popraw polygony tablic "
                                    "i zatwierdź E2. Ręcznie dodane tablice zapisują się w XML z etykietą 'plate'."
                                )
                                tone = "warning"
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
                                    f"Wizard może pominąć Z2 i przejść od razu do Z3 z runem {source_run.name}."
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
                        btn.config(text=step_btn_txt, style="Accent.TButton", state="normal")
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

        if CAMPAIGN.create_project(new_name):
            self.app.campaign_free_mode = False
            self.app.set_campaign_mode(True)
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

    def _step_goto_auto_annotation(self, force_annotation_tab: bool = False):
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
                ready_run_dir = ready_source.get("restore_run_dir")
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
                    run_hint = f" Korzystam z runu {ready_run_name}." if ready_run_name else ""
                    self.app.update_status(
                        "Znaleziono gotowe reczne anotacje tablic dla tej paczki. "
                        "Pomijam Z2 i przechodze od razu do Z3."
                        + run_hint,
                        "info"
                    )
                except Exception:
                    pass

                self._step_goto_characters(preferred_source_context=ready_source)
                return

        tab_ann = self.app.tabs.get("annotation")
        manual_template = (iteration_target == "plate")
        plate_bootstrap_model = ""
        restore_run_dir = None
        input_source = "raw"
        if tab_ann:
            bootstrap = {}
            try:
                bootstrap = tab_ann._get_campaign_auto_annotation_bootstrap(iteration_target)
            except Exception:
                bootstrap = {}

            input_dir = Path(bootstrap.get("input_dir") or input_dir)
            manual_template = bool(bootstrap.get("manual_template", manual_template))
            plate_bootstrap_model = str(bootstrap.get("plate_model_path") or "").strip()
            restore_run_dir = bootstrap.get("restore_run_dir")
            input_source = str(bootstrap.get("input_source") or "raw").strip()

            restored_snapshot = tab_ann.apply_campaign_context(
                input_dir,
                auto_out,
                manual_template=manual_template,
                mode_text="C: Pojazdy + tablice",
            )

            if not restored_snapshot:
                if v_mod and Path(v_mod).exists():
                    tab_ann.vehicle_model_var.set("Custom")
                    tab_ann.vehicle_custom_var.set(v_mod)
                else:
                    try:
                        vehicle_values = list(tab_ann.vehicle_combo["values"]) if hasattr(tab_ann, "vehicle_combo") else []
                    except Exception:
                        vehicle_values = []
                    detect_values = [value for value in vehicle_values if value != "Custom"]
                    default_vehicle = "yolo11s" if "yolo11s" in detect_values else (detect_values[0] if detect_values else "")
                    if default_vehicle:
                        tab_ann.vehicle_model_var.set(default_vehicle)
                    tab_ann.vehicle_custom_var.set("")

                if (
                    iteration_target == "char" and p_mod and Path(p_mod).exists()
                ) or (
                    iteration_target == "plate" and plate_bootstrap_model and Path(plate_bootstrap_model).exists()
                ):
                    tab_ann.plate_custom_var.set(plate_bootstrap_model if iteration_target == "plate" else p_mod)
                else:
                    tab_ann.plate_custom_var.set("")

                tab_ann.mode_var.set("C: Pojazdy + tablice")
                tab_ann._on_mode_change()

                if restore_run_dir is not None:
                    tab_ann._restore_preview_from_annotation_run(restore_run_dir)

        try:
            if iteration_target == "plate":
                extra_hint = ""
                if not manual_template and plate_bootstrap_model:
                    extra_hint += " Aktywny model tablic projektu zostal podstawiony automatycznie."
                if input_source == "stage_previous_iteration":
                    extra_hint += " Jako wejscie ustawiono stage z poprzedniej iteracji."
                elif input_source == "manual_source_run":
                    extra_hint += " Przywrocono ostatnie reczne anotacje tablic dla tego zestawu zdjec."
                elif input_source == "reused_manual_source_run":
                    extra_hint += " Przywrocono reczne anotacje z poprzedniej iteracji dla tej samej paczki."
                elif input_source == "latest_approved_run":
                    extra_hint += " Przywrocono tez ostatni zatwierdzony run tablic projektu."
                elif input_source == "reused_training_source_run":
                    extra_hint += " Przywrocono reczne anotacje z runu Z2, ktory zasilił trening w poprzedniej iteracji."
                elif input_source == "reused_iteration_run":
                    extra_hint += " Przywrocono zatwierdzony run Z2 z poprzedniej iteracji dla tej samej paczki."
                self.app.update_status(
                    f"Auto-ustawiono Z2 dla toru tablic: IN={Path(input_dir).name} | OUT={Path(auto_out).name}. "
                    + (
                        "Tryb reczny utworzy annotations.xml, a nowe polygony zapisza sie z etykieta 'plate'."
                        if manual_template
                        else "Mozesz uruchomic autoanotacje tablic aktywnym modelem projektu i recznie poprawiac wynik."
                    )
                    + extra_hint,
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

    def _step_goto_characters(self, preferred_source_context: dict | None = None):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return      

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_dir = CAMPAIGN.get_dir("auto_ann")
        chars_dir = CAMPAIGN.get_dir("chars")
        datasets_dir = CAMPAIGN.get_dir("datasets")

        if raw_dir is None or auto_dir is None:
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        default_folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
        folder = default_folder

        source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}
        if not source_context and self._get_iteration_target() == "char":
            source_context = self._get_char_route_ready_source()

        preferred_run_dir = None
        preferred_xml = ""
        preferred_input_dir = None
        using_preferred_source = False

        try:
            restore_run_dir = source_context.get("restore_run_dir")
            if restore_run_dir:
                candidate_run_dir = Path(restore_run_dir)
                candidate_xml = candidate_run_dir / "annotations.xml"
                if candidate_run_dir.exists() and candidate_run_dir.is_dir() and candidate_xml.exists():
                    preferred_run_dir = candidate_run_dir
                    preferred_xml = str(candidate_xml)
        except Exception:
            preferred_run_dir = None
            preferred_xml = ""

        try:
            input_dir = source_context.get("input_dir")
            if input_dir:
                candidate_input_dir = Path(input_dir)
                if candidate_input_dir.exists() and candidate_input_dir.is_dir():
                    preferred_input_dir = candidate_input_dir
        except Exception:
            preferred_input_dir = None

        if preferred_input_dir is not None:
            folder = preferred_input_dir
        elif not folder.exists():
            folder = Path(raw_dir)

        latest_xml = preferred_xml
        if latest_xml:
            using_preferred_source = True
        else:
            # Wybierz najnowszy XML z zatwierdzonych autoanotacji projektu.
            xml_files = list(Path(auto_dir).rglob("annotations.xml"))
            latest_xml = str(max(xml_files, key=lambda p: p.stat().st_mtime)) if xml_files else ""

        tab_char = self.app.tabs.get("characters")
        if tab_char:
            # Wyczyść poprzedni kontekst zakładki znaków przed podaniem nowych źródeł.
            tab_char.preview_dir_var.set("")
            tab_char.preview_metadata = {}
            tab_char.preview_plate_ids = []
            tab_char._loaded_meta_path = None
            tab_char._loaded_meta_mtime = None

            # wyczyść listę i canvas, jeśli istnieją
            try:
                tab_char.plates_listbox.delete(0, tk.END)
            except Exception:
                pass

            try:
                tab_char.preview_canvas.delete("all")
            except Exception:
                pass

            try:
                tab_char.preview_info_lbl.config(text="Oczekuję na nowy zestaw zdjęć...", foreground="#2980b9")
            except Exception:
                pass

            # Podstaw źródła z najnowszej zatwierdzonej próby.
            if folder.exists():
                tab_char.images_dir_var.set(str(folder))
            if latest_xml:
                tab_char.xml_path_var.set(latest_xml)

            # projektowe katalogi wyjściowe
            tab_char._campaign_chars_dir = str(chars_dir) if chars_dir else None
            tab_char._campaign_datasets_dir = str(datasets_dir) if datasets_dir else None

            c_mod = CAMPAIGN.get_global_model("char")
            if c_mod and Path(c_mod).exists():
                # Jeśli projekt ma już model znaków, kolejna iteracja startuje w trybie hybrydowym.
                tab_char.detection_method_var.set("BOTH")
                tab_char.yolo_model_path_var.set(c_mod)

                try:
                    version, size = tab_char._infer_yolo_arch_from_model_path(c_mod)
                    if version in {"8", "11", "26"}:
                        tab_char.yolo_model_version_var.set(version)
                    if size in {"n", "s", "m", "l", "x"}:
                        tab_char.yolo_model_size_var.set(size)
                except Exception as e:
                    logger.debug(f"Nie udało się odczytać architektury YOLO z nazwy modelu: {e}")

                try:
                    tab_char._sync_yolo_model_binding()
                except Exception as e:
                    logger.debug(f"Nie udało się zsynchronizować ścieżki modelu YOLO: {e}")

                try:
                    tab_char._update_yolo_visibility()
                except Exception as e:
                    logger.debug(f"Nie udało się odświeżyć widoku YOLO w Zakładce Znaków: {e}")
            else:
                # Brak modelu znaków oznacza bootstrap wyłącznie przez OCR.
                try:
                    tab_char.detection_method_var.set("OCR")
                    tab_char.yolo_model_path_var.set("")
                    tab_char._update_yolo_visibility()
                except Exception as e:
                    logger.debug(f"Nie udało się ustawić trybu OCR dla braku modelu znaków: {e}")
                try:
                    tab_char._sync_yolo_model_binding()
                except Exception:
                    pass

                try:
                    tab_char._update_yolo_visibility()
                except Exception:
                    pass

            try:
                tab_char._restore_preview_context_from_project()
            except Exception as e:
                logger.debug(f"Nie udało się przywrócić preview projektu: {e}")

        try:
            if latest_xml:
                if using_preferred_source and preferred_run_dir is not None:
                    self.app.update_status(
                        f"Ustawiono Z3 na gotowe ręczne tablice: XML={preferred_run_dir.name}/annotations.xml | IMG={folder.name}.",
                        "info"
                    )
                else:
                    self.app.update_status(
                        f"Ustawiono świeże źródła dla Zakładki Znaków: XML={Path(latest_xml).parent.name}/annotations.xml | IMG={folder.name}.",
                        "info"
                    )
            else:
                self.app.update_status(
                    "Nie znaleziono nowego pliku annotations.xml. Upewnij się, że Autoanotacja zakończyła się sukcesem i etap został zatwierdzony.",
                    "warning"
                )
        except Exception:
            pass

        if tab_char:
            try:
                saved_substep = CAMPAIGN.get_step3_substep()

                should_restore = (
                    saved_substep > 1
                    or CAMPAIGN.is_step3_stage1_done()
                    or CAMPAIGN.is_step3_stage2_done()
                )

                if should_restore:
                    tab_char.restore_campaign_step3_mode()
                else:
                    tab_char.enter_campaign_step3_mode()

            except Exception as e:
                logger.debug(f"Nie udało się przywrócić stanu kroku 3: {e}")
                CAMPAIGN.reset_step3_progress()
                tab_char.enter_campaign_step3_mode()
        self.app.open_controlled_tab("characters")

    def _step_goto_training(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 4:
            return

        try:
            iteration_target = self._get_iteration_target()
            if iteration_target not in {"plate", "char"}:
                iteration_target = "char"

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
                        f"Rozpoczęto iterację {iter_num:03d} na tym samym zestawie zdjęć "
                        f"({copied} obrazów). Krok 1 został domknięty, możesz przejść do E2."
                    ),
                    "info"
                )
            else:
                self.app.update_status(
                    f"Rozpoczęto iterację {iter_num:03d}. Wskaż nowy zestaw zdjęć w E1.",
                    "info"
                )
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
