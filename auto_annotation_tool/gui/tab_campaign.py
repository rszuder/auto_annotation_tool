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
import shutil

from ..config import CONFIG, logger
from ..campaign_manager import CAMPAIGN
from ..campaign_ingest_planner import CHAR_ALPHABET
from ..icons import IconManager
from .help_manager import HELP


class CampaignTab:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        self.frame = ttk.Frame(parent)

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
        self.ingest_batch_size_var = tk.IntVar(master=self.frame, value=200)
        self.ingest_status_labels = []
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

        self.left_panel_scrollbar = ttk.Scrollbar(
            self.left_scroll_host,
            orient=tk.VERTICAL,
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

        HELP.bind_help(self.btn_add_proj, "camp_new_project")
        HELP.bind_help(self.btn_open_proj, "camp_open_project")
        HELP.bind_help(self.btn_del_proj, "camp_delete_project")
        HELP.bind_help(self.btn_exit_project, "camp_exit_project")
        HELP.bind_help(left_panel, "camp_models")
        HELP.bind_help(self.btn_advance, "camp_advance")

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

        self.right_panel_scrollbar = ttk.Scrollbar(
            self.right_scroll_host,
            orient=tk.VERTICAL,
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
        units = self._mousewheel_units(event)
        if listbox is None or units == 0:
            return "break"
        try:
            listbox.yview_scroll(units, "units")
        except Exception:
            pass
        return "break"

    def _on_global_mousewheel(self, event):
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

        scroll = ttk.Scrollbar(list_host, orient=tk.VERTICAL)
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
            text="Panel E1: Dobór paczki zdjęć",
            font=("Segoe UI", 10, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        header_lbl.pack(fill=tk.X, padx=10, pady=(10, 4))
        self.ingest_header_lbl = header_lbl

        intro_lbl = tk.Label(
            ingest_lf,
            text="Tu ustawiasz główną pulę zdjęć, odświeżasz bilans znaków i przygotowujesz paczkę wejściową dla bieżącej iteracji.",
            justify=tk.LEFT,
            wraplength=620,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        intro_lbl.pack(anchor=tk.W, padx=10, pady=(0, 8))
        self.ingest_intro_lbl = intro_lbl

        ingest_top_section = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        ingest_top_section.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.ingest_top_section = ingest_top_section

        master_row = tk.Frame(ingest_top_section, bg=palette.get("panel", "#252526"))
        master_row.pack(fill=tk.X, padx=10, pady=(10, 6))
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

        status_panel = tk.Frame(
            ingest_top_section,
            bg=palette.get("panel", "#252526"),
        )
        status_panel.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.ingest_status_panel = status_panel
        self.ingest_status_labels = []

        for font_spec in (("Segoe UI", 9, "bold"), ("Segoe UI", 9), ("Segoe UI", 9)):
            lbl = tk.Label(
                status_panel,
                text="",
                justify=tk.LEFT,
                anchor="w",
                height=1,
                fg=palette.get("muted", "#b8b8b8"),
                bg=palette.get("panel", "#252526"),
                font=font_spec,
            )
            lbl.pack(fill=tk.X)
            self.ingest_status_labels.append(lbl)

        ingest_body = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
        )
        ingest_body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        ingest_body.grid_columnconfigure(0, weight=0, minsize=300)
        ingest_body.grid_columnconfigure(1, weight=1, minsize=540)
        ingest_body.grid_rowconfigure(0, weight=1)
        self.ingest_body = ingest_body

        left_col = tk.Frame(ingest_body, bg=palette.get("panel", "#252526"))
        left_col.config(
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.ingest_left_col = left_col

        right_col = tk.Frame(ingest_body, bg=palette.get("panel", "#252526"))
        right_col.config(
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=subtle_border,
        )
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.grid_columnconfigure(0, weight=1)
        right_col.grid_rowconfigure(1, weight=1)
        self.ingest_right_col = right_col

        config_row = tk.Frame(left_col, bg=palette.get("panel", "#252526"))
        config_row.pack(fill=tk.X, padx=10, pady=(10, 8))
        self.ingest_config_row = config_row

        self.lbl_ingest_batch_title = tk.Label(
            config_row,
            text="Rozmiar paczki:",
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_ingest_batch_title.pack(side=tk.LEFT)

        try:
            self.spn_ingest_batch = ttk.Spinbox(
                config_row,
                from_=1,
                to=5000,
                increment=1,
                width=8,
                textvariable=self.ingest_batch_size_var,
            )
        except Exception:
            self.spn_ingest_batch = ttk.Entry(config_row, width=8, textvariable=self.ingest_batch_size_var)
        self.spn_ingest_batch.pack(side=tk.LEFT, padx=(8, 0))

        actions_row = tk.Frame(left_col, bg=palette.get("panel", "#252526"))
        actions_row.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.ingest_actions_row = actions_row

        self.btn_refresh_ingest_stats = ttk.Button(
            actions_row,
            text="Odśwież bilans",
            command=self._refresh_ingest_balance_only,
        )
        self.btn_refresh_ingest_stats.pack(side=tk.LEFT)

        self.btn_generate_ingest_plan = ttk.Button(
            actions_row,
            text="Wygeneruj paczkę E1",
            command=self._generate_ingest_plan,
            style="Accent.TButton",
        )
        self.btn_generate_ingest_plan.pack(side=tk.LEFT, padx=(8, 0))

        self.btn_manual_ingest = ttk.Button(
            actions_row,
            text="Skopiuj ręcznie",
            command=self._step_create_raw_folder,
        )
        self.btn_manual_ingest.pack(side=tk.RIGHT)

        self.ingest_list_title_lbl = tk.Label(
            right_col,
            text="Aktualna paczka E1",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_list_title_lbl.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        list_host = tk.Frame(
            right_col,
            bg=palette.get("field", "#1a1a1a"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
        )
        list_host.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        self.ingest_plan_host = list_host

        scroll = ttk.Scrollbar(list_host, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.ingest_plan_listbox = tk.Listbox(
            list_host,
            exportselection=False,
            selectmode=tk.EXTENDED,
            height=8,
            width=1,
            font=("Segoe UI", 9),
            bg=palette.get("field", "#1a1a1a"),
            fg=palette.get("fg", "#f3f3f3"),
            selectbackground=palette.get("accent", "#2980b9"),
            selectforeground="#ffffff",
            activestyle="none",
            bd=0,
            highlightthickness=1,
            highlightbackground=subtle_border,
            highlightcolor=palette.get("accent", "#2980b9"),
            takefocus=1,
            yscrollcommand=scroll.set,
        )
        self.ingest_plan_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.ingest_plan_listbox.bind("<<ListboxSelect>>", self._on_ingest_selection_changed)
        self.ingest_plan_listbox.bind("<Button-1>", lambda _e: self.ingest_plan_listbox.focus_set(), add="+")
        self.ingest_plan_listbox.bind("<MouseWheel>", lambda e: self._on_listbox_mousewheel(e, self.ingest_plan_listbox))
        self.ingest_plan_listbox.bind("<Button-4>", lambda e: self._on_listbox_mousewheel(e, self.ingest_plan_listbox))
        self.ingest_plan_listbox.bind("<Button-5>", lambda e: self._on_listbox_mousewheel(e, self.ingest_plan_listbox))
        scroll.config(command=self.ingest_plan_listbox.yview)

        footer_row = tk.Frame(right_col, bg=palette.get("panel", "#252526"))
        footer_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.ingest_footer_row = footer_row
        footer_row.grid_columnconfigure(0, weight=1)
        footer_row.grid_columnconfigure(1, weight=0)

        self.btn_remove_ingest_item = ttk.Button(
            footer_row,
            text="Usuń zaznaczone",
            command=self._remove_selected_ingest_items,
        )
        self.btn_remove_ingest_item.grid(row=0, column=0, sticky="w")

        self.btn_apply_ingest_plan = ttk.Button(
            footer_row,
            text="Zatwierdź E1",
            command=self._apply_current_ingest_plan,
            style="Accent.TButton",
            width=18,
        )
        self.btn_apply_ingest_plan.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.ingest_insights_shell = tk.Frame(
            ingest_lf,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
        )
        self.ingest_insights_shell.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.ingest_insights_shell.grid_columnconfigure(0, weight=3, minsize=420)
        self.ingest_insights_shell.grid_columnconfigure(1, weight=2, minsize=300)

        self.ingest_chart_panel = tk.Frame(self.ingest_insights_shell, bg=palette.get("panel", "#252526"))
        self.ingest_chart_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=10)

        self.ingest_info_panel = tk.Frame(self.ingest_insights_shell, bg=palette.get("panel", "#252526"))
        self.ingest_info_panel.grid(row=0, column=1, sticky="nsew", pady=10)

        self.ingest_balance_title_lbl = tk.Label(
            self.ingest_chart_panel,
            text="Histogram znaków w aktualnej paczce E1",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_balance_title_lbl.pack(fill=tk.X, pady=(0, 4))

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
        self.ingest_balance_summary_lbl.pack(fill=tk.X, pady=(8, 0))

        self.ingest_logic_title_lbl = tk.Label(
            self.ingest_info_panel,
            text="Jak system tworzy paczkę E1?",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_logic_title_lbl.pack(fill=tk.X, pady=(0, 4))

        self.ingest_logic_lbl = tk.Label(
            self.ingest_info_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=340,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_logic_lbl.pack(fill=tk.X, pady=(0, 12))

        self.ingest_selection_title_lbl = tk.Label(
            self.ingest_info_panel,
            text="Co się stanie po usunięciu zaznaczonych zdjęć?",
            font=("Segoe UI", 9, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w"
        )
        self.ingest_selection_title_lbl.pack(fill=tk.X, pady=(0, 4))

        self.ingest_selection_lbl = tk.Label(
            self.ingest_info_panel,
            text="",
            justify=tk.LEFT,
            anchor="w",
            wraplength=340,
            fg=palette.get("muted", "#b8b8b8"),
            bg=palette.get("panel", "#252526"),
        )
        self.ingest_selection_lbl.pack(fill=tk.X)
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
        HELP.bind_help(self.lbl_ingest_batch_title, "camp_e1_panel")
        HELP.bind_help(self.btn_refresh_ingest_stats, "camp_e1_balance")
        HELP.bind_help(self.btn_generate_ingest_plan, "camp_e1_generate")
        HELP.bind_help(self.btn_manual_ingest, "camp_e1_manual")
        HELP.bind_help(self.ingest_logic_title_lbl, "camp_e1_logic")
        HELP.bind_help(self.ingest_logic_lbl, "camp_e1_logic")
        HELP.bind_help(self.ingest_balance_title_lbl, "camp_e1_balance_chart")
        HELP.bind_help(self.ingest_balance_canvas, "camp_e1_balance_chart")
        HELP.bind_help(self.ingest_balance_summary_lbl, "camp_e1_balance_chart")
        HELP.bind_help(self.ingest_list_title_lbl, "camp_e1_plan_list")
        HELP.bind_help(self.ingest_plan_listbox, "camp_e1_plan_list")
        HELP.bind_help(self.ingest_selection_title_lbl, "camp_e1_plan_list")
        HELP.bind_help(self.ingest_selection_lbl, "camp_e1_plan_list")
        HELP.bind_help(self.btn_remove_ingest_item, "camp_e1_plan_list")
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

    def _get_current_ingest_batch_size(self) -> int:
        try:
            value = int(self.ingest_batch_size_var.get())
        except Exception:
            value = CAMPAIGN.get_ingest_batch_size()
        value = max(1, value)
        batch_limit = self._get_ingest_batch_upper_limit()
        if batch_limit > 0:
            value = min(value, batch_limit)
        self.ingest_batch_size_var.set(value)
        return value

    def _get_ingest_batch_upper_limit(self) -> int:
        master_pool = CAMPAIGN.get_master_pool_dir()
        if master_pool is None or not master_pool.exists() or not master_pool.is_dir():
            return 0
        return self._count_images_in_dir(master_pool, recursive=True)

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

    def _set_ingest_status_lines(self, line1="", line2="", line3=""):
        lines = [line1, line2, line3]
        for idx, lbl in enumerate(getattr(self, "ingest_status_labels", [])):
            try:
                lbl.config(text=lines[idx] if idx < len(lines) else "")
            except Exception:
                pass

    def _get_iteration_image_count(self) -> int:
        iter_dir = CAMPAIGN.get_iteration_raw_dir()
        return self._count_images_in_dir(iter_dir, recursive=True)

    def _format_ingest_source_label(self, snapshot: dict) -> str:
        source_type = str(snapshot.get("source_type", "") or "").strip()
        source_path = snapshot.get("source_path", "")

        if source_type == "merged_dataset":
            return "Źródło bilansu: scalony dataset znaków"
        if source_type == "dataset":
            return f"Źródło bilansu: {Path(str(source_path)).name}"
        if source_type == "metadata_pools":
            return "Źródło bilansu: pule manual/gold"
        return "Źródło bilansu: brak zaakceptowanego materiału"

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
                "Lista po prawej pokazuje aktualną paczkę E1. System przygotowuje jej pierwszy szkic automatycznie, "
                "a Ty możesz go ręcznie skorygować.\n"
                "1. System bierze tylko nieużyte zdjęcia z głównej puli.\n"
                "2. Z nazwy każdego pliku odczytuje znaki tablic.\n"
                "3. Wyżej ocenia zdjęcia ze znakami, których jest najmniej w zaakceptowanym zbiorze treningowym.\n"
                f"4. W tej chwili najczęstsze znaki w paczce E1 to: {self._format_histogram_compact(selected_balance, limit=6)}.\n"
                "Histogram niżej pokazuje już wyłącznie rozkład znaków w tej bieżącej paczce E1."
            )
        else:
            text = (
                "Po kliknięciu „Wygeneruj paczkę E1” system tworzy pierwszy szkic zdjęć dla tej iteracji.\n"
                "To nie jest osobny plan projektu, tylko bieżąca lista zdjęć proponowanych do kroku E1.\n"
                f"Najrzadsze znaki w zaakceptowanym zbiorze treningowym to teraz: {rare_preview}.\n"
                "Jeśli w histogramie paczki zobaczysz dominację jednego znaku, możesz usunąć część takich zdjęć "
                "albo dołożyć ręcznie materiał z brakującymi znakami."
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
                "Po wygenerowaniu paczki E1 zaznacz jedno albo kilka zdjęć na liście. "
                "Panel pokaże wtedy, jakie znaki wnosi to zaznaczenie i co osłabisz po jego usunięciu z paczki."
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
        score_items = Counter()
        for item in selected_items:
            for text_value in item.get("ground_truth_texts", []) or []:
                text_value = str(text_value).strip()
                if text_value and text_value not in selected_texts:
                    selected_texts.append(text_value)
            removed_hist.update(item.get("char_histogram", {}) or {})
            for ch, value in (item.get("score_details", {}) or {}).items():
                try:
                    score_items[str(ch)] += float(value or 0.0)
                except Exception:
                    continue

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
        support_preview = ", ".join(
            f"{ch}:{value:.1f}"
            for ch, value in sorted(score_items.items(), key=lambda entry: (-entry[1], entry[0]))[:5]
            if value > 0
        ) or "brak danych"

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
            f"Najsilniej wspierane przez system znaki: {support_preview}\n"
            f"Po usunięciu z paczki E1 najbardziej spadną: {impact_preview}"
        )
        if zeroed_chars:
            text += f"\nPo usunięciu całkiem znikną z paczki: {', '.join(zeroed_chars[:6])}."
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
        accent_color = palette.get("accent", "#4fc1ff")
        top_color = palette.get("surface_warning", "#d0a437")

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
                text="Brak paczki E1 do pokazania.\nWygeneruj paczkę albo przygotuj ją ręcznie.",
                fill=muted,
                justify=tk.CENTER,
                font=("Segoe UI", 9),
            )
            try:
                self.ingest_balance_summary_lbl.config(
                    text=(
                        "Histogram pokaże liczbę wystąpień każdego znaku w aktualnej paczce E1. "
                        "Najwyższy słupek oznacza znak, który dominuje w tej paczce."
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
            "Wysokość słupka = liczba wystąpień danego znaku w nazwach tablic zdjęć należących do aktualnej paczki E1.\n"
            f"Paczka E1 zawiera teraz {package_images} zdjęć i {package_total} znaków. "
            f"Najczęstsze znaki: {dominant_text}.\n"
            f"Brakujące znaki w tej paczce: {missing_text}."
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

        bordered_widgets = (
            "ingest_top_section",
            "ingest_left_col",
            "ingest_right_col",
            "ingest_insights_shell",
            "ingest_plan_host",
        )
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
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c"))
                )
        except Exception:
            pass

        try:
            if getattr(self, "ingest_status_panel", None) is not None:
                self.ingest_status_panel.config(bg=frame_bg)
            for lbl in getattr(self, "ingest_status_labels", []):
                lbl.config(bg=frame_bg, fg=palette.get("muted", "#c7c7c7"))
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
            self.app.update_status("Odświeżono bilans znaków dla przygotowania paczki iteracji.", "info")
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

        try:
            self.ingest_batch_size_var.set(CAMPAIGN.get_ingest_batch_size())
        except Exception:
            pass

        snapshot = snapshot_override or CAMPAIGN.load_ingest_balance_snapshot()
        if has_project and not snapshot:
            snapshot = CAMPAIGN.refresh_ingest_balance_snapshot()
        self.last_ingest_snapshot = snapshot or {}

        used_count = int((snapshot or {}).get("used_filenames", 0) or 0)
        total_chars = int((snapshot or {}).get("total_characters", 0) or 0)
        balance_source = self._format_ingest_source_label(snapshot or {})
        iter_image_count = self._get_iteration_image_count() if has_project else 0
        master_pool_image_count = self._count_images_in_dir(master_pool, recursive=True) if master_pool_exists else 0
        batch_limit = master_pool_image_count if master_pool_exists else 0

        try:
            if self.spn_ingest_batch is not None:
                self.spn_ingest_batch.config(from_=1, to=max(1, batch_limit or 5000))
        except Exception:
            pass
        if batch_limit > 0:
            try:
                current_batch_size = int(self.ingest_batch_size_var.get())
            except Exception:
                current_batch_size = CAMPAIGN.get_ingest_batch_size()
            self.ingest_batch_size_var.set(max(1, min(current_batch_size, batch_limit)))

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
        candidates_total = int(self.current_ingest_plan.get("candidates_total", 0) or 0)
        iter_num = CAMPAIGN.get_current_iteration_num() if has_project else 0

        try:
            if self.ingest_list_title_lbl is not None:
                if plan_count > 0:
                    self.ingest_list_title_lbl.config(
                        text=f"Aktualna paczka E1 ({plan_count} zdjęć z {candidates_total} kandydatów)"
                    )
                else:
                    self.ingest_list_title_lbl.config(text="Aktualna paczka E1")
        except Exception:
            pass

        if has_project:
            line1 = (
                f"Iteracja {iter_num:03d}: folder iteracji {iter_image_count} zdjęć | "
                f"główna pula {master_pool_image_count} zdjęć | paczka E1 {plan_count} zdjęć."
            )
        else:
            line1 = "Brak aktywnego projektu."
        line2 = f"{balance_source} | znaków w zaakceptowanym zbiorze: {total_chars} | użytych nazw: {used_count}"
        requested_batch = 0
        try:
            requested_batch = int(self.ingest_batch_size_var.get() or 0)
        except Exception:
            requested_batch = 0
        if iter_image_count > 0 and step1_approved:
            line3 = "Bieżąca iteracja ma już zatwierdzoną paczkę wejściową. E1 jest zamknięte."
        elif iter_image_count > 0:
            line3 = (
                "W folderze iteracji są już obrazy, ale E1 nie zostało jeszcze zatwierdzone. "
                "Potwierdź tę paczkę ręcznie, aby odblokować E2."
            )
        elif plan_count > 0:
            if candidates_total > 0 and requested_batch > candidates_total:
                line3 = (
                    f"System ułożył paczkę z {plan_count} zdjęć, bo tylko {candidates_total} kandydatów "
                    "spełniało warunki doboru. Zdjęcia trafią do iteracji dopiero po zatwierdzeniu E1."
                )
            else:
                line3 = (
                    f"Lista po prawej to bieżąca paczka E1: {plan_count} zdjęć gotowych do zatwierdzenia. "
                    "Zdjęcia zostaną skopiowane do iteracji dopiero po zatwierdzeniu E1."
                )
        elif has_project and master_pool and not master_pool_exists:
            line3 = "Zapisana główna pula zdjęć nie istnieje na dysku. Wskaż poprawny katalog albo użyj ścieżki ręcznej."
        elif has_project and master_pool_exists:
            line3 = (
                "Główna pula zdjęć jest gotowa. Ustaw rozmiar paczki i kliknij „Wygeneruj paczkę E1”, "
                "albo skopiuj zdjęcia ręcznie."
            )
        elif has_project:
            line3 = "Najpierw wskaż główną pulę zdjęć albo skopiuj zdjęcia ręcznie do iteracji."
        else:
            line3 = ""
        self._set_ingest_status_lines(line1, line2, line3)

        enable_generate = bool(has_project and master_pool_exists and iter_image_count == 0)
        enable_apply = bool(enable_generate and plan_count > 0)
        enable_remove = bool(enable_apply)
        enable_manual = bool(has_project and (iter_image_count == 0 or not step1_approved))

        try:
            self.btn_manual_ingest.config(
                text="Zatwierdź istniejącą paczkę"
                if iter_image_count > 0 and not step1_approved
                else "Skopiuj ręcznie"
            )
        except Exception:
            pass

        for widget, enabled in (
            (self.btn_choose_master_pool, has_project),
            (self.btn_refresh_ingest_stats, has_project),
            (self.btn_generate_ingest_plan, enable_generate),
            (self.btn_manual_ingest, enable_manual),
            (self.btn_remove_ingest_item, enable_remove),
            (self.btn_apply_ingest_plan, enable_apply),
        ):
            try:
                widget.config(state="normal" if enabled else "disabled")
            except Exception:
                pass

        try:
            self.spn_ingest_batch.config(state="normal" if has_project else "disabled")
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
        self._refresh_ingest_panel()
        image_count = self._count_images_in_dir(Path(selected), recursive=True)

        try:
            self.app.update_status(
                f"Zapisano katalog głównej puli zdjęć dla aktywnego projektu. Wykryto {image_count} obrazów.",
                "info"
            )
        except Exception:
            pass

    def _generate_ingest_plan(self):
        if not CAMPAIGN.get_active_project_name():
            return

        batch_size = self._get_current_ingest_batch_size()
        CAMPAIGN.set_ingest_batch_size(batch_size)

        try:
            plan = CAMPAIGN.build_ingest_plan(batch_size=batch_size)
        except Exception as e:
            messagebox.showerror("Błąd generatora paczki E1", str(e))
            return

        if not plan.get("ok", False):
            messagebox.showwarning("Brak paczki E1", str(plan.get("error", "Nie udało się wygenerować paczki E1.")))
            return

        self.current_ingest_plan = plan
        self._recalculate_current_ingest_plan()
        candidates_total = int(plan.get("candidates_total", 0) or 0)
        selected_total = int(plan.get("selected_total", 0) or 0)
        if candidates_total > 0 and batch_size > candidates_total:
            self.ingest_batch_size_var.set(candidates_total)
        self._refresh_ingest_panel()

        try:
            if candidates_total > 0 and selected_total < batch_size:
                status_text = (
                    f"Wygenerowano paczkę E1: {selected_total} zdjęć. "
                    f"Tylu kandydatów było dostępnych w głównej puli."
                )
            else:
                status_text = f"Wygenerowano paczkę E1: {selected_total} zdjęć."
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
            return

        selected_items = list(self.current_ingest_plan.get("selected", []) or [])
        if not selected_items:
            messagebox.showwarning("Brak paczki E1", "Wygeneruj najpierw paczkę E1.")
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
                            "Czy zatwierdzić tę paczkę jako E1 i odblokować E2?"
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
                        f"Iteracja {iter_num:03d} zawiera już paczkę wejściową. Krok 2 pozostaje odblokowany.",
                        "info",
                    )
                except Exception:
                    pass
                messagebox.showinfo(
                    "Paczka wejściowa już gotowa",
                    f"Folder iteracji zawiera już {len(existing_images)} obrazów:\n{target_iter_dir}\n\n"
                    "Nie kopiowano nowych plików, ale krok 1 został uznany za domknięty.",
                )
                return
            messagebox.showwarning(
                "Brak nowych plików",
                "Żadne nowe zdjęcia nie zostały skopiowane do iteracji.\n\n"
                "Być może paczka została już wcześniej zatwierdzona.",
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
                f"Skopiowano {copied} zdjęć z propozycji paczki do Iteracji {iter_num:03d}. Odblokowano Krok 2.",
                "info",
            )
        except Exception:
            pass

        messagebox.showinfo(
            "Przygotowanie paczki zakończone",
            f"Skopiowano {copied} zdjęć do:\n{target_iter_dir}\n\n"
            "Paczkę zapisano jako zaakceptowaną porcję danych tej iteracji.",
        )

    def apply_theme(self):
        palette = getattr(self.app, "palette", {})
        bg = palette.get("bg", "#1e1e1e")
        panel = palette.get("panel", "#252526")
        panel_alt = palette.get("surface_info", palette.get("panel_alt", panel))
        fg = palette.get("fg", "#f3f3f3")
        muted = palette.get("muted", "#c7c7c7")

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

        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
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

    # ======================================================
    # ROADMAP UI
    # ======================================================

    def _set_roadmap_note(self, item, text="", tone="muted"):
        palette = getattr(self.app, "palette", {})
        lbl_desc = item.get("lbl_desc")
        if lbl_desc is None:
            return

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
            lbl_desc.config(text=note_text, fg=note_color)
        except Exception:
            return

        if note_text:
            if not item.get("note_visible"):
                lbl_desc.pack(anchor=tk.W, pady=(4, 0))
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

        card_bg = palette.get("surface_info", palette.get("panel", "#252526")) if color else palette.get("panel", "#252526")
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
            "E1. Dobór paczki zdjęć",
            "E1. Przygotowujesz paczkę wejściową dla aktywnej iteracji. Wizard może zaproponować zdjęcia z głównej puli albo przyjąć paczkę wskazaną ręcznie.",
            "Pokaż panel E1",
            self._toggle_step1_panel
        )

        self._build_roadmap_step(
            roadmap_parent, 2,
            "E2. Detekcja kaskadowa (Autoanotacja)",
            "E2. Wizard przechodzi do Z2, podstawia ścieżki projektowe i prowadzi przez autoanotację pojazdów oraz tablic.",
            "Skocz: Autoanotacja",
            self._step_goto_auto_annotation
        )

        self._build_roadmap_step(
            roadmap_parent, 3,
            "E3. Wycinanie tablic + Złota paczka",
            "E3. Wizard przechodzi do Z3, gdzie wycinasz tablice, uruchamiasz OCR, porównujesz wynik z ground truth i budujesz gold pack.",
            "Skocz: Znaki",
            self._step_goto_characters
        )

        self._build_roadmap_step(
            roadmap_parent, 4,
            "E4. Trening i analiza",
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
        step1_approved = step1_status == "approved"
        if curr_step >= 2 and not step1_approved and self._get_iteration_image_count() > 0:
            CAMPAIGN.approve_step1()
            step1_status = "approved"
            step1_approved = True

        logger.debug(
            f"[CampaignTab] active_proj={active_proj}, curr_step={curr_step}, "
            f"step2_status={step2_status}, step3_status={step3_status}"
        )
        iter_num = CAMPAIGN.get_current_iteration_num()

        self.lbl_iter.config(text=f"Iteracja: {iter_num}", fg=warning, bg=surface_warning)
        self.lbl_campaign_banner.config(
            text=(
                f"AKTYWNY PROJEKT: {active_proj}  |  TRYB KAMPANII WŁĄCZONY\n"
                "Masz włączone sterowanie workflow. Aby wrócić do trybu swobodnego, kliknij „Wyjdź z projektu”."
            ),
            fg=success,
            bg=surface_success
        )

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

        # Awans iteracji
        if curr_step >= 5:
            self.btn_advance.config(
                text="🎉 Cykl zakończony → Nowa iteracja",
                state="normal",
                style="Accent.TButton"
            )
        else:
            self.btn_advance.config(
                text=f"Awans zablokowany (Krok {curr_step})",
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
                item["lbl_title"].config(text=f"✅ {title}", fg=success)
                self._set_roadmap_note(item, "")

                if s == 1:
                    btn.config(text="Wykonano", style="TButton", state="disabled")
                else:
                    btn.config(text="Wykonano", style="TButton", state="disabled")

            elif s == curr_step:
                self._set_roadmap_card_border(item, accent)
                item["lbl_title"].config(text=f"🔵 {title}", fg=accent)

                if s == 2 and step2_status == "generated":
                    self._set_roadmap_note(
                        item,
                        (
                            "Autoanotacja została wykonana, ale etap nie został jeszcze zatwierdzony.\n"
                            "Przejdź do zakładki Autoanotacja, sprawdź wynik i kliknij „Zatwierdź etap autoanotacji”."
                        ),
                        "warning"
                    )

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

                else:
                    self._set_roadmap_note(item, "")

                if s == 1:
                    if step1_folder_exists and step1_approved:
                        self.step1_panel_expanded = False
                        self._set_roadmap_note(
                            item,
                            "Folder iteracji zawiera już paczkę wejściową. Możesz przejść dalej do autoanotacji.",
                            "success"
                        )
                    elif step1_folder_exists:
                        self._set_roadmap_note(
                            item,
                            "Folder iteracji zawiera już obrazy, ale E1 nadal czeka na jawne zatwierdzenie. Rozwiń panel E1 i potwierdź paczkę, aby odblokować E2.",
                            "warning"
                        )
                    elif plan_ready:
                        self._set_roadmap_note(
                            item,
                            "Po rozwinięciu panelu E1 zobaczysz gotową propozycję paczki zdjęć. Możesz usunąć wybrane pozycje albo zatwierdzić ją do iteracji.",
                            "info"
                        )
                    elif master_pool_ready:
                        self._set_roadmap_note(
                            item,
                            "Główna pula zdjęć jest ustawiona. Kliknij przycisk karty E1, aby rozwinąć panel i wygenerować propozycję paczki.",
                            "info"
                        )
                    else:
                        self._set_roadmap_note(
                            item,
                            "Kliknij przycisk karty E1, aby rozwinąć panel i wskazać główną pulę zdjęć albo skopiować paczkę ręcznie.",
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
                else:
                    btn.config(text=orig_btn_txt, style="Accent.TButton", state="normal")

            else:
                self._set_roadmap_card_border(item)
                item["lbl_title"].config(text=f"⚪ {title}", fg=muted)
                self._set_roadmap_note(item, "")
                btn.config(text=orig_btn_txt, style="TButton", state="disabled")

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

        # Jeśli folder iteracji zawiera już zdjęcia, paczka wejściowa jest gotowa.
        existing_images = [f for f in target_iter_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if existing_images:
            if CAMPAIGN.get_step1_status() != "approved":
                should_approve = self.app.themed_confirm(
                    "Zatwierdzenie E1",
                    (
                        f"Folder iteracji zawiera już {len(existing_images)} obrazów:\n{target_iter_dir}\n\n"
                        "Czy zatwierdzić tę paczkę jako E1 i odblokować E2?"
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
            title="Wybierz folder źródłowy z NOWĄ paczką zdjęć do tej iteracji"
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
            "Przygotowanie paczki zakończone",
            f"Skopiowano {copied} zdjęć do:\n{target_iter_dir}\n\n"
            f"Każda iteracja pracuje tylko na swojej NOWEJ paczce wejściowej."
        )

    def _step_goto_auto_annotation(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 2:
            return

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_out = CAMPAIGN.get_staging_dir("auto_ann")
        if auto_out is not None:
            Path(auto_out).mkdir(parents=True, exist_ok=True)

        if raw_dir is None or auto_out is None:
            return

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"

        tab_ann = self.app.tabs.get("annotation")
        if tab_ann:
            if folder.exists():
                tab_ann.apply_campaign_context(folder, auto_out)
            else:
                tab_ann.apply_campaign_context(raw_dir, auto_out)

            v_mod = CAMPAIGN.get_global_model("vehicle")
            p_mod = CAMPAIGN.get_global_model("plate")

            if v_mod and Path(v_mod).exists():
                tab_ann.vehicle_model_var.set("Custom")
                tab_ann.vehicle_custom_var.set(v_mod)
            if p_mod and Path(p_mod).exists():
                tab_ann.plate_custom_var.set(p_mod)

            tab_ann.mode_var.set("C: Pojazdy + tablice")
            tab_ann._on_mode_change()

        try:
            self.app.update_status(
                f"Auto-ustawiono: IN={folder.name} | OUT={Path(auto_out).name}. Kliknij START.",
                "info"
            )
        except Exception:
            pass

        self.app.open_controlled_tab("annotation")

    def _step_goto_characters(self):
        if not CAMPAIGN.get_active_project_name() or CAMPAIGN.get_current_step() < 3:
            return      

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_dir = CAMPAIGN.get_dir("auto_ann")
        chars_dir = CAMPAIGN.get_dir("chars")
        datasets_dir = CAMPAIGN.get_dir("datasets")

        if raw_dir is None or auto_dir is None:
            return

        # Wybierz najnowszy XML z zatwierdzonych autoanotacji projektu.
        xml_files = list(Path(auto_dir).rglob("annotations.xml"))
        latest_xml = str(max(xml_files, key=lambda p: p.stat().st_mtime)) if xml_files else ""

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"

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
                tab_char.preview_info_lbl.config(text="Oczekuję na nową paczkę...", foreground="#2980b9")
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
            datasets_dir = CAMPAIGN.get_dir("datasets")
            runs_dir = CAMPAIGN.get_dir("runs")

            if datasets_dir is None:
                logger.error("Brak katalogu datasets dla aktywnego projektu.")
                return

            tab_train = self.app.tabs.get("training")
            if not tab_train:
                logger.error("Nie znaleziono zakładki TrainingTab w app.tabs.")
                return

            # Przełącz TrainingTab na kontekst aktywnego projektu.
            tab_train.set_campaign_context(
                runs_dir=str(runs_dir) if runs_dir is not None else None,
                datasets_dir=str(datasets_dir)
            )

            datasets_dir = Path(datasets_dir)

            source_candidates = [
                p for p in datasets_dir.iterdir()
                if p.is_dir()
                and "_Split_" not in p.name
                and (p / "images").exists()
            ]

            latest_source = None
            if source_candidates:
                latest_source = max(source_candidates, key=lambda p: p.stat().st_mtime)

            if latest_source is not None:
                tab_train.split_src_var.set(str(latest_source))
                tab_train.split_out_var.set(
                    str(datasets_dir / f"{latest_source.name}_Split_[DATA_I_CZAS]")
                )
            else:
                tab_train.split_src_var.set("")
                tab_train.split_out_var.set(str(datasets_dir / "[BRAK_DATASETU_ZRODLOWEGO]"))

            char_model = CAMPAIGN.get_global_model("char")
            if char_model and Path(char_model).exists():
                tab_train.base_model_var.set("Custom")
                tab_train.base_custom_var.set(char_model)
            else:
                tab_train.base_model_var.set("yolo11n")
                tab_train.base_custom_var.set("")

            tab_train._on_base_model_change()

            try:
                tab_train.imgsz_var.set(256)
            except Exception:
                pass

            try:
                if latest_source is not None:
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
        if self.app.themed_confirm(
            "Nowa iteracja",
            "Zamknąć obecną iterację i rozpocząć nową?",
            parent=self.frame,
            confirm_label="Rozpocznij",
            tone="warning"
        ):
            CAMPAIGN.advance_to_next_iteration()
            CAMPAIGN.reset_step1()
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()
