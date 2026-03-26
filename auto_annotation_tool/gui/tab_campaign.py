#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Rozkład Jazdy (Dashboard Kampanii MLOps)..
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from textwrap import shorten
import os

from ..config import CONFIG, logger
from ..campaign_manager import CAMPAIGN
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
        self._model_status_title_labels = []
        self.project_listbox = None
        self.project_list_host = None
        self.project_list_status_lbl = None
        self.project_list_status_labels = []
        self._project_name_by_index = []
        self._project_list_refreshing = False

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
        main_container.columnconfigure(0, weight=0, minsize=420)
        main_container.columnconfigure(1, weight=1, minsize=700)
        main_container.rowconfigure(0, weight=1)

        # LEFT PANEL
        left_panel_host = ttk.Frame(main_container, width=420)
        left_panel_host.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
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

        # RIGHT PANEL
        self.right_panel = ttk.LabelFrame(
            main_container,
            text=" Rozkład Jazdy (Cykl Active Learningu) ",
            padding=15
        )
        self.right_panel.grid(row=0, column=1, sticky="nsew")

        self._rebuild_roadmap_ui()
        self.frame.after_idle(self._sync_left_panel_scrollregion)
        self.frame.after_idle(self._sync_left_panel_canvas_width)

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
            height=5,
            width=1,
            font=("Segoe UI", 10),
            bg=palette.get("field", "#1a1a1a"),
            fg=palette.get("fg", "#f3f3f3"),
            selectbackground=palette.get("accent", "#2980b9"),
            selectforeground="#ffffff",
            activestyle="none",
            bd=0,
            highlightthickness=0,
            yscrollcommand=scroll.set
        )
        self.project_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.project_listbox.bind("<<ListboxSelect>>", self._on_project_changed)
        self.project_listbox.bind("<Double-Button-1>", lambda _e: self._open_selected_project())
        scroll.config(command=self.project_listbox.yview)

        HELP.bind_help(browser_lf, "camp_open_project")
        HELP.bind_help(status_panel, "camp_open_project")
        for lbl in self.project_list_status_labels:
            HELP.bind_help(lbl, "camp_open_project")
        HELP.bind_help(self.project_listbox, "camp_open_project")

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
                    selectforeground="#ffffff"
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
        for key in ("lbl_title", "lbl_desc"):
            widget = item.get(key)
            if widget is None:
                continue
            try:
                widget.config(bg=card_bg)
            except Exception:
                pass

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
        for widget in self.right_panel.winfo_children():
            widget.destroy()
        self.roadmap_ui_elements = []

        self._build_roadmap_step(
            self.right_panel, 1,
            "1. Ingestia danych",
            "E1. Wskazujesz nową porcję zdjęć dla aktywnej iteracji. Wizard kopiuje obrazy do drzewa projektu i przygotowuje bazę dla kolejnych etapów.",
            "Wybierz i skopiuj zdjęcia",
            self._step_create_raw_folder
        )

        self._build_roadmap_step(
            self.right_panel, 2,
            "2. Detekcja kaskadowa (Autoanotacja)",
            "E2. Wizard przechodzi do Z2, podstawia ścieżki projektowe i prowadzi przez autoanotację pojazdów oraz tablic.",
            "Skocz: Autoanotacja",
            self._step_goto_auto_annotation
        )

        self._build_roadmap_step(
            self.right_panel, 3,
            "3. Wycinanie tablic + Złota paczka",
            "E3. Wizard przechodzi do Z3, gdzie wycinasz tablice, uruchamiasz OCR, porównujesz wynik z ground truth i budujesz gold pack.",
            "Skocz: Znaki",
            self._step_goto_characters
        )

        self._build_roadmap_step(
            self.right_panel, 4,
            "4. Trening i analiza",
            "E4. Wizard przechodzi do Z4, gdzie wybierasz tor, przygotowujesz dataset iteracji i uruchamiasz trening oraz analizę modelu.",
            "Skocz: Trening",
            self._step_goto_training
        )

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
                self._set_roadmap_card_border(item)
                item["lbl_title"].config(text=f"🔒 {item['original_title']}", fg=muted_dim)
                self._set_roadmap_note(item, "")
                item["btn"].config(text="Zablokowane", style="TButton", state="disabled")

                extra_frame = item.get("extra_actions_frame")
                if extra_frame:
                    for w in extra_frame.winfo_children():
                        w.destroy()
                    extra_frame.pack_forget()

            self.app.update_campaign_tab_access()
            self.frame.update_idletasks()
            return

        # ======================================================
        # TRYB AKTYWNEGO PROJEKTU
        # ======================================================
        self.app.campaign_free_mode = False
        self.app.set_campaign_mode(True)


        curr_step = CAMPAIGN.get_current_step()
        step2_status = CAMPAIGN.get_step2_status()
        step3_status = CAMPAIGN.get_step3_status()

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
        raw_dir = CAMPAIGN.get_dir("raw")
        step1_folder_exists = False
        if raw_dir:
            step1_folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
            step1_folder_exists = step1_folder.exists()

        # Kroki
        for item in self.roadmap_ui_elements:
            s = item["step_num"]
            title = item["original_title"]
            orig_btn_txt = item["orig_btn_text"]
            btn = item["btn"]
            extra_frame = item.get("extra_actions_frame")

            if extra_frame:
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
                    btn.config(
                        text="Zatwierdź pliki" if step1_folder_exists else "Wybierz i skopiuj zdjęcia",
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

    def _get_selected_project_from_list(self) -> str:
        if self.project_listbox is None:
            return ""

        try:
            selection = self.project_listbox.curselection()
            if not selection:
                return ""

            idx = int(selection[0])
            if idx < 0 or idx >= len(self._project_name_by_index):
                return ""

            return str(self._project_name_by_index[idx]).strip()
        except Exception:
            return ""

    def _select_project_in_list(self, project_name: str):
        if self.project_listbox is None or not project_name:
            return

        try:
            idx = self._project_name_by_index.index(project_name)
            self.project_listbox.selection_clear(0, tk.END)
            self.project_listbox.selection_set(idx)
            self.project_listbox.activate(idx)
            self.project_listbox.see(idx)
        except Exception:
            pass

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

        selected = self._get_selected_project_from_list()
        if not selected or self.project_list_status_lbl is None:
            return

        try:
            self._set_project_list_status(selected, len(self._project_name_by_index))
            self.frame.after_idle(self._sync_left_panel_scrollregion)
        except Exception:
            pass

    def _open_selected_project(self):
        """Aktywuje projekt wybrany z listy i włącza tryb kampanii."""
        selected = self._get_selected_project_from_list()
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
        selected = self._get_selected_project_from_list()
        if not selected:
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

    def _open_selected_project(self):
        selected = self._get_selected_project_from_list()
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
        selected = self._get_selected_project_from_list()
        if not selected:
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

        # Jeśli folder iteracji zawiera już zdjęcia, etap ingestii można uznać za gotowy.
        existing_images = [f for f in target_iter_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if existing_images:
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

        import shutil

        image_files = [f for f in source_dir.iterdir() if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS]
        if not image_files:
            return messagebox.showwarning(
                "Brak zdjęć",
                "W wybranym folderze nie znaleziono żadnych obrazów obsługiwanych przez aplikację."
            )

        copied = 0
        for img_file in image_files:
            dst = target_iter_dir / img_file.name
            if not dst.exists():
                shutil.copy2(img_file, dst)
                copied += 1

        if copied == 0:
            return messagebox.showwarning(
                "Brak nowych plików",
                "Żadne nowe zdjęcia nie zostały skopiowane.\n\n"
                "Być może ten zestaw został już wcześniej użyty w tej iteracji."
            )

        CAMPAIGN.set_current_step(2)
        self._refresh_dashboard()

        try:
            self.app.update_status(
                f"✅ Skopiowano {copied} nowych zdjęć do Iteracji {iter_num:03d}. Odblokowano Krok 2.",
                "info"
            )
        except Exception:
            pass

        messagebox.showinfo(
            "Ingestia zakończona",
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
                tab_ann.plate_model_var.set("Custom")
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
            self._rebuild_roadmap_ui()
            self._refresh_dashboard()
