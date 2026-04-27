#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Główna aplikacja GUI.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
from datetime import datetime
import threading
import time
import faulthandler

from ..config import CONFIG, logger, TK_AVAILABLE, SESSION
from ..icons import IconManager
from .web_slim_scrollbar import WebSlimScrollbar, blend_hex_colors

# Importy zakładek
from .tab_annotation import AnnotationTab
from .tab_character_annotation import CharacterAnnotationTab
from .tab_training import TrainingTab
from .tab_campaign import CampaignTab
from .help_manager import HELP

try:
    from .tab_help import HelpTab
except ImportError:
    HelpTab = None


APP_AUTHOR = "rszuder"
THEME_DEFINITIONS = {
    "dark_visual_cs": {
        "label": "Dark Visual CS",
        "palette": {
            "bg": "#1e1e1e",
            "panel": "#252526",
            "panel_alt": "#2d2d30",
            "field": "#1a1a1a",
            "border": "#3c3c3c",
            "panel_border": "#313131",
            "fg": "#f3f3f3",
            "muted": "#c7c7c7",
            "muted_dim": "#9a9a9a",
            "accent": "#63c7ff",
            "accent_hover": "#89d7ff",
            "accent_selected": "#2c607d",
            "button_hover": "#37373d",
            "tab_disabled_bg": "#1e1e1e",
            "tab_disabled_fg": "#6f6f6f",
            "success": "#4ec9b0",
            "warning": "#d7ba7d",
            "error": "#f48771",
            "surface_info": "#213a4d",
            "surface_success": "#1f3320",
            "surface_warning": "#3a2323",
            "guide": "#f0b44c",
            "guide_pulse": "#ffd37a",
            "guide_text": "#111111",
            "accent_text": "#ffffff",
            "console_bg": "#252526",
            "console_fg": "#f3f3f3",
            "console_border": "#3c3c3c",
            "doc_bg": "#1f1f1f",
            "doc_fg": "#f3f3f3",
            "code_bg": "#2d2d30",
            "code_fg": "#dcdcaa",
        },
    },
    "dark_graphite": {
        "label": "Dark Graphite",
        "palette": {
            "bg": "#202124",
            "panel": "#2a2b2f",
            "panel_alt": "#32343a",
            "field": "#191a1d",
            "border": "#404349",
            "panel_border": "#37393f",
            "fg": "#f5f5f5",
            "muted": "#d0d0d0",
            "muted_dim": "#9b9b9b",
            "accent": "#66b4ff",
            "accent_hover": "#8ac7ff",
            "accent_selected": "#355f86",
            "button_hover": "#3a3c43",
            "tab_disabled_bg": "#202124",
            "tab_disabled_fg": "#76797f",
            "success": "#62d2a2",
            "warning": "#e3c27a",
            "error": "#ff8e72",
            "surface_info": "#2b3f54",
            "surface_success": "#22362c",
            "surface_warning": "#3b2f1e",
            "guide": "#f3c96b",
            "guide_pulse": "#ffe29a",
            "guide_text": "#111111",
            "accent_text": "#ffffff",
            "console_bg": "#2a2b2f",
            "console_fg": "#f5f5f5",
            "console_border": "#404349",
            "doc_bg": "#25262a",
            "doc_fg": "#f5f5f5",
            "code_bg": "#32343a",
            "code_fg": "#f6d28b",
        },
    },
    "light_visual_cs": {
        "label": "Light Visual CS",
        "palette": {
            "bg": "#f3f3f3",
            "panel": "#ffffff",
            "panel_alt": "#e7e7e7",
            "field": "#ffffff",
            "border": "#c8c8c8",
            "panel_border": "#dcdcdc",
            "fg": "#1f1f1f",
            "muted": "#4f4f4f",
            "muted_dim": "#7a7a7a",
            "accent": "#006bb3",
            "accent_hover": "#0b7dcd",
            "accent_selected": "#00548c",
            "button_hover": "#e1edf7",
            "tab_disabled_bg": "#e3e3e3",
            "tab_disabled_fg": "#989898",
            "success": "#1f8f6b",
            "warning": "#b57900",
            "error": "#c7422f",
            "surface_info": "#eaf3ff",
            "surface_success": "#e8f6ef",
            "surface_warning": "#fff4d9",
            "guide": "#ffd86b",
            "guide_pulse": "#ffebad",
            "guide_text": "#1f1f1f",
            "accent_text": "#ffffff",
            "console_bg": "#ffffff",
            "console_fg": "#1f1f1f",
            "console_border": "#c8c8c8",
            "doc_bg": "#ffffff",
            "doc_fg": "#1f1f1f",
            "code_bg": "#f3f3f3",
            "code_fg": "#8b3f00",
        },
    },
}


class AutoAnnotationApp:
    def __init__(self, root):
        self.root = root
        self._faulthandler_stream = None
        self.root.title(f"{CONFIG.APP_NAME} v{CONFIG.VERSION}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._enable_fatal_crash_logging()
        
        self.icon_manager = IconManager
        self.icon_manager.test_emoji_support(root)
        
        self.themes = THEME_DEFINITIONS
        self.current_theme_key = self._load_theme_preference()
        self.current_theme_name = self.themes[self.current_theme_key]["label"]
        self.palette = dict(self.themes[self.current_theme_key]["palette"])
        self.theme_var = tk.StringVar(master=root, value=self.current_theme_key)
        self.global_yolo_device_var = tk.StringVar(
            master=root,
            value=self._load_global_yolo_device_preference(),
        )
        self.menu_bar_frame = None
        self.menu_theme_badge = None
        self._menu_dropdown = None
        self._menu_dropdown_owner = None
        self._menu_outside_click_bind_id = None
        self._menu_escape_bind_id = None
        self._theme_refresh_after_id = None
        self._help_scroll_ctrl_down = False
        self._help_scroll_alt_down = False
        self._help_panel_default_height = 1
        self._help_panel_expanded = False
        self._help_panel_apply_in_progress = False
        self._help_overlay_place_after_id = None
        self._help_overlay_forced_visible = False
        self._help_overlay_forced_text = ""
        self._help_panel_message_prefix = "HELP:"
        self._status_full_text = ""
        self._global_terminal_lines = ["[APP] Terminal globalny gotowy. Tutaj trafiaja logi procesow z Z2, PZ2 i Z4."]
        self._global_terminal_entries = [
            {
                "text": "[APP] Terminal globalny gotowy. Tutaj trafiaja logi procesow z Z2, PZ2 i Z4.",
                "tag": "terminal_info",
            }
        ]
        self._global_terminal_max_lines = 1600
        self._global_terminal_window = None
        self._global_terminal_shell = None
        self._global_terminal_header = None
        self._global_terminal_title_lbl = None
        self._global_terminal_clear_btn = None
        self._global_terminal_close_btn = None
        self._global_terminal_body = None
        self._global_terminal_text = None
        self._global_terminal_scrollbar = None
        self._global_terminal_hscrollbar = None
        self._global_terminal_toggle_btn = None
        self._global_terminal_visible = False
        self._global_terminal_geometry_initialized = False
        self.tabs = {}
        self._closing_in_progress = False
        self.startup_overlay_frame = None
        self.startup_overlay_card = None
        self.startup_overlay_title_lbl = None
        self.startup_overlay_status_lbl = None
        self.startup_overlay_progress = None
        self.startup_overlay_window = None
        self.startup_overlay_shown_at = None
        self.startup_progress_var = tk.DoubleVar(master=root, value=0.0)
        self.startup_status_var = tk.StringVar(master=root, value="Przygotowanie aplikacji...")
        self._startup_finalize_after_id = None
        self._startup_finalize_attempts = 0
        self._startup_ready_streak = 0
        self._startup_tabs_present_since = None
        self._startup_tabs_prewarmed = False
        self._startup_progress_peak = 0.0
        self._main_window_hidden_for_startup = False
        self._main_window_revealed = False

        self.style = ttk.Style()
        self._setup_style(self.current_theme_key)
        self._prepare_main_window_for_startup()
        self._show_startup_overlay()
        self._set_startup_progress(8, "Uruchamianie interfejsu...")
        self.is_processing = False
        self._manual_processing = False
        self._exclusive_operation = None
        self._processing_state_lock = threading.RLock()
        # Lokalna flaga aktywnego trybu kampanii.
        self.campaign_mode_active = False
        # Ręczne wyjście z projektu ma pierwszeństwo nad automatycznym trybem kampanii.
        self.campaign_free_mode = False
    
        self._set_startup_progress(16, "Budowanie menu...")
        self._create_menu()
        self._set_startup_progress(24, "Konfiguracja okien dialogowych...")
        self._install_themed_dialog_hooks()

        self.default_status_message = HELP.default_message
        
        # Panel pomocy musi powstać przed notebookiem, aby poprawnie zakotwiczyć go na dole okna.
        self._set_startup_progress(34, "Inicjalizacja panelu pomocy...")
        self.info_panel_frame = tk.Frame(root, bg="#050505", bd=0, highlightthickness=0)
        self.info_panel_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self._global_terminal_toggle_btn = tk.Button(
            self.info_panel_frame,
            text=">_",
            command=self.toggle_global_terminal,
            width=3,
            cursor="hand2",
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
            padx=6,
            pady=2,
            font=("Consolas", 9, "bold"),
            bg="#050505",
            activebackground="#050505",
            fg=self.palette.get("guide", self.palette.get("warning", "#f0b44c")),
            activeforeground=self.palette.get("guide", self.palette.get("warning", "#f0b44c")),
        )
        self._global_terminal_toggle_btn.pack(side=tk.LEFT, padx=(8, 0), pady=4)

        self.status_text = tk.Text(
            self.info_panel_frame, height=1, wrap=tk.NONE, 
            bg="#050505",
            bd=0,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            fg="#f7f7f7",
            insertbackground="#f7f7f7",
            highlightthickness=0
        )
        self.status_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 10), pady=4)
        self.status_text.insert(tk.END, self._format_help_panel_message(self.default_status_message))
        self.status_text.config(state=tk.DISABLED)
        self.status_text.bind("<Configure>", self._on_help_panel_text_configure, add="+")
        self.help_overlay_frame = tk.Frame(
            root,
            bg="#112235",
            bd=0,
            highlightthickness=1,
            highlightbackground="#4aa3ff",
            highlightcolor="#4aa3ff"
        )
        self.help_overlay_title_lbl = tk.Label(
            self.help_overlay_frame,
            text="Rozwinieta pomoc  |  CTRL + ALT lub PPM",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 9, "bold"),
            bg="#112235",
            fg="#dcefff",
            bd=0,
            highlightthickness=0
        )
        self.help_overlay_title_lbl.pack(fill=tk.X, padx=12, pady=(10, 4))
        self.help_overlay_text = tk.Message(
            self.help_overlay_frame,
            text=self._format_help_panel_message(self.default_status_message),
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 10),
            bg="#112235",
            fg="#f7f7f7",
            width=560,
            padx=0,
            pady=0
        )
        self.help_overlay_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        for widget in (self.help_overlay_frame, self.help_overlay_title_lbl, self.help_overlay_text):
            try:
                widget.bind("<ButtonPress-1>", self._on_help_overlay_primary_click, add="+")
            except Exception:
                pass
        self._status_full_text = self._format_help_panel_message(self.default_status_message)
        self._bind_help_panel_shortcuts()
        self._apply_help_panel_visual_state()
        
        # Podpinamy globalny menedżer pomocy
        HELP.status_updater = self.update_status
        HELP.overlay_presenter = self.show_context_help_overlay
        HELP.overlay_dismisser = self.hide_context_help_overlay
        
        # 2. Tworzenie Notatnika z zakładkami
        self._set_startup_progress(48, "Tworzenie struktury zakładek...")
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 0))
        
        self._create_tabs(progress_callback=self._set_startup_progress)
        self._set_startup_progress(92, "Nakładanie motywu...")
        self._apply_theme_to_tabs()

        # główna blokada działa przez disabled tabs
        self.notebook.bind("<<NotebookTabChanged>>", self._on_main_notebook_tab_changed)

        # początkowa synchronizacja stanów zakładek
        self.update_campaign_tab_access()
        self._restore_active_main_tab_preference()

        # Po starcie pokaż informację o aktywnym projekcie, jeśli aplikacja wznawia tryb kampanii.
        try:
            from ..campaign_manager import CAMPAIGN
            active_proj = CAMPAIGN.get_active_project_name()
            if active_proj:
                try:
                    annotation_tab = getattr(self, "tabs", {}).get("annotation")
                    ensure_context = (
                        getattr(annotation_tab, "ensure_campaign_context_ready_for_active_project", None)
                        if annotation_tab is not None
                        else None
                    )
                    if callable(ensure_context) and self._get_selected_tab_key() == "annotation":
                        self.root.after_idle(ensure_context)
                except Exception as restore_err:
                    logger.debug(f"Nie udalo sie przywrocic kontekstu Z2 dla aktywnego projektu po starcie: {restore_err}")

                self.update_status(
                    f"Aktywny projekt: {active_proj}. Aplikacja działa w trybie kampanii — aby wrócić do trybu swobodnego, użyj „Wyjdź z projektu” w Wizardzie.",
                    "warning"
                )
        except Exception:
            pass

        self._schedule_startup_finalize()

    def _enable_fatal_crash_logging(self):
        try:
            crash_log_path = Path(CONFIG.WORKSPACE_DIR) / "fatal_crash.log"
            crash_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._faulthandler_stream = open(crash_log_path, "a", encoding="utf-8")
            faulthandler.enable(self._faulthandler_stream, all_threads=True)
        except Exception as e:
            logger.debug(f"Nie udało się włączyć fatal crash log dla GUI: {e}")

    def _raise_startup_overlay(self):
        overlay_window = getattr(self, "startup_overlay_window", None)
        overlay = getattr(self, "startup_overlay_frame", None)
        card = getattr(self, "startup_overlay_card", None)
        if overlay is None:
            return

        try:
            self.root.update_idletasks()
        except Exception:
            pass

        if overlay_window is not None:
            try:
                splash_w = max(380, min(560, int(card.winfo_reqwidth() or 460)))
                splash_h = max(112, min(180, int(card.winfo_reqheight() or 132)))
                screen_w = max(1, int(self.root.winfo_screenwidth() or 1))
                screen_h = max(1, int(self.root.winfo_screenheight() or 1))
                pos_x = max(0, int((screen_w - splash_w) / 2))
                pos_y = max(0, int((screen_h - splash_h) / 2))
                overlay_window.geometry(f"{splash_w}x{splash_h}+{pos_x}+{pos_y}")
                overlay_window.lift()
                overlay_window.attributes("-topmost", True)
            except Exception:
                pass
        else:
            try:
                overlay.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception:
                pass

            try:
                overlay.lift()
            except Exception:
                pass

            for widget_name in ("menu_bar_frame", "notebook", "info_panel_frame", "help_overlay_frame"):
                widget = getattr(self, widget_name, None)
                if widget is None:
                    continue
                try:
                    overlay.lift(widget)
                except Exception:
                    pass

        if card is not None:
            try:
                card.lift()
            except Exception:
                pass

    def _flush_startup_overlay(self):
        self._raise_startup_overlay()
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass
        self._raise_startup_overlay()

    def _consume_startup_overlay_event(self, event=None):
        return "break"

    def _prepare_main_window_for_startup(self):
        try:
            self.root.withdraw()
            self._main_window_hidden_for_startup = True
            self._main_window_revealed = False
        except Exception:
            self._main_window_hidden_for_startup = False
            self._main_window_revealed = False

    def _reveal_main_window_after_startup(self):
        if bool(getattr(self, "_main_window_revealed", False)):
            return

        try:
            self.root.deiconify()
        except Exception:
            pass

        try:
            self.root.update_idletasks()
        except Exception:
            pass

        try:
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-fullscreen", True)
            except Exception:
                pass

        try:
            self.root.lift()
        except Exception:
            pass

        try:
            self.root.focus_force()
        except Exception:
            try:
                self.root.focus_set()
            except Exception:
                pass

        self._main_window_hidden_for_startup = False
        self._main_window_revealed = True

        try:
            self.root.after_idle(lambda: self._refresh_adaptive_wraps(self.root))
        except Exception:
            pass

    def _show_startup_overlay(self):
        if self.startup_overlay_frame is not None:
            return

        palette = self.palette
        self.startup_overlay_shown_at = time.monotonic()
        self._startup_progress_peak = 0.0
        overlay_parent = self.root

        try:
            overlay_window = tk.Toplevel(self.root)
            overlay_window.withdraw()
            overlay_window.overrideredirect(True)
            try:
                overlay_window.attributes("-topmost", True)
            except Exception:
                pass
            try:
                overlay_window.resizable(False, False)
            except Exception:
                pass
            overlay_window.configure(bg=palette.get("bg", "#1e1e1e"))
            self.startup_overlay_window = overlay_window
            overlay_parent = overlay_window
        except Exception:
            self.startup_overlay_window = None
            overlay_parent = self.root

        self.startup_overlay_frame = tk.Frame(
            overlay_parent,
            bg=palette.get("bg", "#1e1e1e"),
            bd=0,
            highlightthickness=0,
        )
        self.startup_overlay_frame.pack(fill=tk.BOTH, expand=True)

        self.startup_overlay_card = tk.Frame(
            self.startup_overlay_frame,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            padx=18,
            pady=16,
        )
        self.startup_overlay_card.pack(fill=tk.BOTH, expand=True)

        self.startup_overlay_title_lbl = tk.Label(
            self.startup_overlay_card,
            text="Ładowanie danych aplikacji",
            font=("Segoe UI", 11, "bold"),
            fg=palette.get("fg", "#f3f3f3"),
            bg=palette.get("panel", "#252526"),
            anchor="w",
        )
        self.startup_overlay_title_lbl.pack(fill=tk.X, pady=(0, 8))

        self.startup_overlay_progress = ttk.Progressbar(
            self.startup_overlay_card,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
            variable=self.startup_progress_var,
            length=420,
            style="Horizontal.TProgressbar",
        )
        self.startup_overlay_progress.pack(fill=tk.X)

        self.startup_overlay_status_lbl = tk.Label(
            self.startup_overlay_card,
            textvariable=self.startup_status_var,
            font=("Segoe UI", 9),
            fg=palette.get("muted", "#c7c7c7"),
            bg=palette.get("panel", "#252526"),
            anchor="w",
        )
        self.startup_overlay_status_lbl.pack(fill=tk.X, pady=(8, 0))

        for widget in (
            self.startup_overlay_card,
            self.startup_overlay_title_lbl,
            self.startup_overlay_status_lbl,
            self.startup_overlay_progress,
        ):
            if widget is None:
                continue
            for sequence in (
                "<ButtonPress-1>",
                "<ButtonRelease-1>",
                "<Double-Button-1>",
                "<MouseWheel>",
                "<Button-4>",
                "<Button-5>",
                "<KeyPress>",
                "<KeyRelease>",
                "<Tab>",
            ):
                try:
                    widget.bind(sequence, self._consume_startup_overlay_event, add="+")
                except Exception:
                    pass

        if self.startup_overlay_window is not None:
            try:
                self._raise_startup_overlay()
                self.startup_overlay_window.deiconify()
            except Exception:
                pass
        else:
            try:
                self.startup_overlay_frame.lift()
                self.startup_overlay_card.lift()
            except Exception:
                pass
        try:
            self.root.after_idle(self._raise_startup_overlay)
        except Exception:
            pass
        try:
            if self.startup_overlay_window is not None:
                self.startup_overlay_window.grab_set()
            else:
                self.startup_overlay_frame.grab_set()
        except Exception:
            pass
        try:
            if self.startup_overlay_window is not None:
                self.startup_overlay_window.focus_force()
            else:
                self.startup_overlay_frame.focus_force()
        except Exception:
            try:
                if self.startup_overlay_window is not None:
                    self.startup_overlay_window.focus_set()
                else:
                    self.startup_overlay_frame.focus_set()
            except Exception:
                pass
        self._flush_startup_overlay()

    def _set_startup_progress(self, value: int | float, message: str = None):
        if self.startup_overlay_frame is None:
            return
        try:
            requested = max(0.0, min(100.0, float(value or 0.0)))
            peak = max(float(getattr(self, "_startup_progress_peak", 0.0) or 0.0), requested)
            self._startup_progress_peak = peak
            self.startup_progress_var.set(peak)
        except Exception:
            pass
        if message is not None:
            try:
                self.startup_status_var.set(str(message))
            except Exception:
                pass
        self._flush_startup_overlay()

    def _hide_startup_overlay(self):
        overlay_window = getattr(self, "startup_overlay_window", None)
        overlay = getattr(self, "startup_overlay_frame", None)
        if overlay is None and overlay_window is None:
            return
        try:
            if overlay_window is not None:
                overlay_window.grab_release()
            elif overlay is not None:
                overlay.grab_release()
        except Exception:
            pass
        try:
            if overlay_window is not None:
                overlay_window.destroy()
            elif overlay is not None:
                overlay.destroy()
        except Exception:
            pass
        self.startup_overlay_window = None
        self.startup_overlay_frame = None
        self.startup_overlay_card = None
        self.startup_overlay_title_lbl = None
        self.startup_overlay_status_lbl = None
        self.startup_overlay_progress = None

    def _wait_for_startup_marker(self, *, delay_ms: int = 0, timeout_ms: int = 4000) -> bool:
        flag = {"done": False}

        def mark_done():
            flag["done"] = True

        try:
            if delay_ms > 0:
                self.root.after(int(delay_ms), mark_done)
            else:
                self.root.after_idle(mark_done)
        except Exception:
            return False

        deadline = time.monotonic() + max(0.1, float(timeout_ms) / 1000.0)
        while not flag["done"] and time.monotonic() < deadline:
            try:
                self.root.update_idletasks()
                self.root.update()
            except Exception:
                break

        return bool(flag["done"])

    def _drain_startup_pending_events(self):
        if self.startup_overlay_frame is None:
            return

        # Najpierw opróżnij bieżące after_idle z konstruktorów zakładek,
        # a potem poczekaj na krótkie after(...) używane podczas startu.
        for _ in range(3):
            self._wait_for_startup_marker(delay_ms=0, timeout_ms=1500)

        for _ in range(2):
            self._wait_for_startup_marker(delay_ms=160, timeout_ms=2500)
            self._wait_for_startup_marker(delay_ms=0, timeout_ms=1500)

    def _get_expected_startup_tab_keys(self) -> list[str]:
        expected = ["campaign", "annotation", "characters", "training"]
        if HelpTab:
            expected.append("help")
        return expected

    def _startup_tabs_ready(self) -> tuple[bool, list[str]]:
        expected = self._get_expected_startup_tab_keys()
        missing = [key for key in expected if key not in self.tabs]
        if missing:
            return False, missing

        try:
            notebook_tabs = list(self.notebook.tabs()) if getattr(self, "notebook", None) is not None else []
        except Exception:
            notebook_tabs = []

        if len(notebook_tabs) < len(expected):
            return False, []

        try:
            notebook_width = int(
                (self.notebook.winfo_reqwidth() if self._main_window_hidden_for_startup else self.notebook.winfo_width()) or 0
            )
            notebook_height = int(
                (self.notebook.winfo_reqheight() if self._main_window_hidden_for_startup else self.notebook.winfo_height()) or 0
            )
            if notebook_width < 120 or notebook_height < 120:
                return False, []
        except Exception:
            return False, []

        try:
            root_width = int((self.root.winfo_reqwidth() if self._main_window_hidden_for_startup else self.root.winfo_width()) or 0)
            root_height = int((self.root.winfo_reqheight() if self._main_window_hidden_for_startup else self.root.winfo_height()) or 0)
            if root_width < 240 or root_height < 180:
                return False, []
        except Exception:
            return False, []

        for key in expected:
            try:
                frame = getattr(self.tabs.get(key), "frame", None)
                if frame is None or str(frame) not in notebook_tabs:
                    return False, [key]
                if not bool(frame.winfo_exists()):
                    return False, [key]
                tab_obj = self.tabs.get(key)
                if tab_obj is not None:
                    startup_ready_getter = getattr(tab_obj, "is_startup_ui_ready", None)
                    if callable(startup_ready_getter):
                        try:
                            if not bool(startup_ready_getter()):
                                return False, [key]
                        except Exception:
                            return False, [key]
                try:
                    if frame.winfo_reqwidth() <= 1 or frame.winfo_reqheight() <= 1:
                        return False, [key]
                except Exception:
                    return False, [key]
            except Exception:
                return False, [key]

        return True, []

    def _prewarm_startup_tabs(self):
        if bool(getattr(self, "_startup_tabs_prewarmed", False)):
            return

        notebook = getattr(self, "notebook", None)
        if notebook is None:
            return

        expected = self._get_expected_startup_tab_keys()
        try:
            original_widget = str(notebook.select() or "")
        except Exception:
            original_widget = ""

        state_by_widget = {}
        try:
            for key in expected:
                tab = self.tabs.get(key)
                frame = getattr(tab, "frame", None)
                if frame is None:
                    continue

                widget_name = str(frame)
                try:
                    state_by_widget[widget_name] = str(notebook.tab(widget_name, "state") or "normal")
                except Exception:
                    state_by_widget[widget_name] = "normal"

                try:
                    if state_by_widget[widget_name] == "disabled":
                        notebook.tab(widget_name, state="normal")
                except Exception:
                    pass

                try:
                    notebook.select(widget_name)
                except Exception:
                    continue

                try:
                    self.root.update_idletasks()
                except Exception:
                    pass

                self._wait_for_startup_marker(delay_ms=90, timeout_ms=2000)

                try:
                    self.root.update_idletasks()
                except Exception:
                    pass
        finally:
            for widget_name, state in state_by_widget.items():
                try:
                    notebook.tab(widget_name, state=state)
                except Exception:
                    pass

            if original_widget:
                try:
                    notebook.select(original_widget)
                except Exception:
                    pass

            try:
                self.root.update_idletasks()
            except Exception:
                pass

        self._startup_tabs_prewarmed = True

    def _schedule_startup_finalize(self, delay_ms: int = 0):
        pending = getattr(self, "_startup_finalize_after_id", None)
        if pending:
            try:
                self.root.after_cancel(pending)
            except Exception:
                pass
        if int(delay_ms or 0) == 0 and self._startup_finalize_attempts == 0:
            self._startup_ready_streak = 0
            self._startup_tabs_present_since = None
            self._startup_tabs_prewarmed = False
        try:
            self._startup_finalize_after_id = self.root.after(
                max(0, int(delay_ms)),
                self._finalize_startup_after_tabs_ready
            )
        except Exception:
            self._startup_finalize_after_id = None
            self._finalize_startup_after_tabs_ready()

    def _finalize_startup_after_tabs_ready(self):
        self._startup_finalize_after_id = None
        if self.startup_overlay_frame is None:
            return

        self._startup_finalize_attempts += 1
        self._set_startup_progress(96, "Finalizacja inicjalizacji zakładek...")
        self._drain_startup_pending_events()

        ready, missing = self._startup_tabs_ready()
        if ready:
            if not bool(getattr(self, "_startup_tabs_prewarmed", False)):
                self._set_startup_progress(97, "Domykam renderowanie zakładek...")
                self._prewarm_startup_tabs()
                self._startup_ready_streak = 0
                self._startup_tabs_present_since = time.monotonic()
                self._schedule_startup_finalize(350)
                return

            now = time.monotonic()
            if self._startup_tabs_present_since is None:
                self._startup_tabs_present_since = now
            self._startup_ready_streak += 1
            settled_for = now - float(self._startup_tabs_present_since or now)
            shown_for = now - float(getattr(self, "startup_overlay_shown_at", now) or now)
            if self._startup_ready_streak >= 5 and settled_for >= 1.8 and shown_for >= 2.5:
                self._set_startup_progress(100, "Ładowanie danych zakończone")
                self._reveal_main_window_after_startup()
                self._hide_startup_overlay()
                logger.info("GUI zainicjalizowane pomyślnie")
                return
            self._set_startup_progress(97, "Domykam renderowanie zakładek...")
            self._schedule_startup_finalize(250)
            return

        self._startup_ready_streak = 0
        self._startup_tabs_present_since = None

        if self._startup_finalize_attempts < 120:
            if missing:
                self._set_startup_progress(
                    96,
                    "Czekam na pełne załadowanie zakładek: " + ", ".join(missing)
                )
            else:
                self._set_startup_progress(96, "Czekam na pełne załadowanie zakładek...")
            self._schedule_startup_finalize(200)
            return

        missing_text = ", ".join(missing) if missing else "nieustalony stan notebooka"
        self._set_startup_progress(
            96,
            f"Błąd ładowania zakładek: {missing_text}. Overlay pozostaje aktywny."
        )
        logger.error(f"Startup GUI nie domknął wszystkich zakładek: {missing_text}")

    def _load_theme_preference(self) -> str:
        try:
            if SESSION:
                saved = SESSION.get("ui", "theme", "dark_visual_cs")
                if saved in self.themes:
                    return saved
        except Exception:
            pass
        return "dark_visual_cs"

    def _save_theme_preference(self, theme_key: str):
        try:
            if SESSION:
                SESSION.set("ui", "theme", theme_key)
                SESSION.save_session()
        except Exception:
            pass

    def _auto_device_label(self) -> str:
        return "auto (prefer GPU/CUDA, fallback CPU)"

    def get_available_yolo_devices(self) -> list[str]:
        devices = [self._auto_device_label(), "cpu"]
        try:
            import torch

            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    name = torch.cuda.get_device_name(i)
                    devices.append(f"cuda:{i} ({name})")
        except Exception:
            pass
        return devices

    def normalize_global_yolo_device_choice(
        self,
        raw_value: str | None = None,
        devices: list[str] | None = None,
    ) -> str:
        available = list(devices or self.get_available_yolo_devices())
        current = str(
            raw_value if raw_value is not None else self.global_yolo_device_var.get() or ""
        ).strip()
        current_lower = current.lower()

        if not current or current_lower.startswith("auto"):
            return available[0] if available else "auto"
        if current_lower.startswith("cpu"):
            return "cpu"
        if current_lower.startswith("cuda:"):
            prefix = current.split()[0]
            for option in available:
                if option.startswith(prefix):
                    return option

        return current if current in available else (available[0] if available else "auto")

    def _load_global_yolo_device_preference(self) -> str:
        try:
            saved = SESSION.get("ui", "global_yolo_device", "auto") if SESSION else "auto"
        except Exception:
            saved = "auto"
        return self.normalize_global_yolo_device_choice(saved)

    def _save_global_yolo_device_preference(self, value: str):
        try:
            if not SESSION:
                return
            SESSION.set("ui", "global_yolo_device", value)
            SESSION.save_session()
        except Exception:
            pass

    def get_global_yolo_device_choice(self) -> str:
        normalized = self.normalize_global_yolo_device_choice()
        try:
            if self.global_yolo_device_var.get() != normalized:
                self.global_yolo_device_var.set(normalized)
        except Exception:
            pass
        return normalized

    def set_global_yolo_device_choice(self, value: str, *, persist: bool = True):
        normalized = self.normalize_global_yolo_device_choice(value)
        try:
            self.global_yolo_device_var.set(normalized)
        except Exception:
            pass

        if persist:
            self._save_global_yolo_device_preference(normalized)

        for tab_key in ("annotation", "characters", "training"):
            try:
                tab = self.tabs.get(tab_key)
                if tab is not None and hasattr(tab, "apply_global_yolo_device_choice"):
                    tab.apply_global_yolo_device_choice(normalized)
            except Exception:
                pass

        try:
            self.update_status(f"Globalne urzadzenie YOLO: {normalized}", "info")
        except Exception:
            pass

    def _is_free_mode_session_context(self) -> bool:
        try:
            from ..campaign_manager import CAMPAIGN
            active_project = CAMPAIGN.get_active_project_name()
        except Exception:
            active_project = None

        return bool(self.campaign_free_mode) or not active_project

    def _load_active_main_tab_preference(self) -> str:
        try:
            if not SESSION:
                return "annotation"
            saved = str(SESSION.get("ui", "active_main_tab", "annotation") or "").strip()
            return saved if saved in self.tabs else "annotation"
        except Exception:
            return "annotation"

    def _save_active_main_tab_preference(self, tab_key: str | None = None):
        try:
            if not SESSION or not self._is_free_mode_session_context():
                return

            selected_key = tab_key or self._get_selected_tab_key()
            if not selected_key or selected_key not in self.tabs:
                return

            SESSION.set("ui", "active_main_tab", selected_key)
            SESSION.save_session()
        except Exception as e:
            logger.debug(f"Nie udalo sie zapisac ostatniej zakladki: {e}")

    def _restore_active_main_tab_preference(self):
        if not self._is_free_mode_session_context():
            return

        tab_key = self._load_active_main_tab_preference()
        if tab_key not in self.tabs:
            return

        try:
            self.notebook.select(str(self.tabs[tab_key].frame))
        except Exception as e:
            logger.debug(f"Nie udalo sie przywrocic ostatniej zakladki: {e}")

    def _is_guided_style(self, style_name: str) -> bool:
        return style_name in {
            "GuidedNeutral.TButton",
            "GuidedAccent.TButton",
        }

    def _remember_guided_base_style(self, button, base_style: str = None) -> str:
        style_name = base_style or getattr(button, "_guided_base_style", None) or str(button.cget("style") or "").strip() or "TButton"
        if self._is_guided_style(style_name):
            style_name = getattr(button, "_guided_base_style", "TButton")
        button._guided_base_style = style_name
        return style_name

    def _get_guided_styles_for_button(self, button, base_style: str = None):
        style_name = self._remember_guided_base_style(button, base_style)
        is_accent = ("Accent" in style_name) or style_name == "Accent.TButton"
        emphasis_style = "GuidedAccent.TButton" if is_accent else "GuidedNeutral.TButton"
        return style_name, emphasis_style

    def set_button_emphasis(self, button, enabled: bool, base_style: str = None):
        if button is None:
            return

        try:
            base_name, emphasis_style = self._get_guided_styles_for_button(button, base_style)
            button.configure(style=(emphasis_style if enabled else base_name))
        except Exception as e:
            logger.debug(f"Nie udało się ustawić podświetlenia przycisku: {e}")

    def style_guidance_frame(self, frame, background: str = None, emphasized: bool = None):
        if frame is None:
            return

        palette = self.palette
        base_border = palette.get("panel_border", palette["border"])
        emphasis_border = blend_hex_colors(
            palette.get("success", "#4ec9b0"),
            palette.get("panel_border", palette["border"]),
            0.18,
        )
        bg = background or getattr(frame, "_guided_frame_bg", None) or palette.get("panel", palette["bg"])
        is_emphasized = getattr(frame, "_guided_frame_emphasized", False) if emphasized is None else bool(emphasized)
        border = emphasis_border if is_emphasized else base_border

        frame._guided_frame_bg = bg
        frame._guided_frame_emphasized = is_emphasized

        try:
            frame.configure(
                bg=bg,
                bd=0,
                relief=tk.FLAT,
                highlightthickness=(1 if is_emphasized else 0),
                highlightbackground=border,
                highlightcolor=border
            )
        except Exception as e:
            logger.debug(f"Nie udało się wystylizować ramki prowadzenia: {e}")

    def set_frame_emphasis(self, frame, enabled: bool, background: str = None):
        if frame is None:
            return

        try:
            self.style_guidance_frame(frame, background=background, emphasized=enabled)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić podświetlenia ramki: {e}")

    def set_theme(self, theme_key: str, persist: bool = True, announce: bool = True):
        if theme_key not in self.themes:
            return

        self._setup_style(theme_key)
        self._restyle_shell()
        self._schedule_theme_refresh_finalize()

        if persist:
            self._save_theme_preference(theme_key)

        if announce:
            self.update_status(
                f"Aktywny styl: {self.current_theme_name}.",
                "info"
            )

    def _restyle_shell(self):
        palette = self.palette

        try:
            self.root.configure(bg=palette["bg"])
        except Exception:
            pass

        try:
            self._create_menu()
        except Exception:
            pass

        try:
            self._apply_help_panel_visual_state()
        except Exception:
            pass

        try:
            self.refresh_window_title()
        except Exception:
            pass

        self._apply_theme_to_tabs()

    def _apply_theme_to_tabs(self):
        try:
            for tab in getattr(self, "tabs", {}).values():
                apply_theme = getattr(tab, "apply_theme", None)
                if callable(apply_theme):
                    apply_theme()
        except Exception:
            pass

    def _apply_theme_to_widget_tree(self, root):
        if root is None:
            return

        visited: set[int] = set()

        def walk(widget):
            if widget is None:
                return

            widget_id = id(widget)
            if widget_id in visited:
                return
            visited.add(widget_id)

            apply_theme = getattr(widget, "apply_theme", None)
            if callable(apply_theme):
                try:
                    apply_theme()
                except Exception:
                    pass

            try:
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass

        walk(root)

    def _finalize_theme_refresh(self):
        self._theme_refresh_after_id = None

        try:
            self._apply_theme_to_widget_tree(self.root)
        except Exception:
            pass

        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _schedule_theme_refresh_finalize(self):
        pending = getattr(self, "_theme_refresh_after_id", None)
        if pending is not None:
            try:
                self.root.after_cancel(pending)
            except Exception:
                pass
            self._theme_refresh_after_id = None

        self._finalize_theme_refresh()

        try:
            self._theme_refresh_after_id = self.root.after_idle(self._finalize_theme_refresh)
        except Exception:
            self._theme_refresh_after_id = None

    def style_native_scrollbar(self, scrollbar, background: str = None, troughcolor: str = None, bordercolor: str = None):
        if scrollbar is None:
            return

        palette = getattr(self, "palette", {})
        bg = background or blend_hex_colors(
            palette.get("accent_hover", palette.get("accent", "#0e639c")),
            palette.get("accent_text", "#ffffff"),
            0.30,
        )
        trough = troughcolor or palette.get("panel", palette.get("bg", "#1e1e1e"))
        border = bordercolor or palette.get("panel_border", palette.get("border", "#3c3c3c"))
        active_bg = blend_hex_colors(bg, palette.get("accent_text", "#ffffff"), 0.18)

        options = {
            "bg": bg,
            "activebackground": active_bg,
            "troughcolor": trough,
            "highlightbackground": border,
            "highlightcolor": border,
            "highlightthickness": 0,
            "bd": 0,
            "borderwidth": 0,
            "relief": tk.FLAT,
            "activerelief": tk.FLAT,
            "elementborderwidth": 0,
            "width": 8,
        }

        for option_name, option_value in options.items():
            try:
                scrollbar.configure(**{option_name: option_value})
            except Exception:
                pass

    def style_text_widget(self, widget, role: str = "default"):
        if widget is None:
            return

        palette = getattr(self, "palette", {})
        role_key = str(role or "default").strip().lower()

        if role_key == "console":
            bg = palette.get("console_bg", "#252526")
            fg = palette.get("console_fg", "#f3f3f3")
            border = palette.get("console_border", palette.get("border", "#3c3c3c"))
        elif role_key == "doc":
            bg = palette.get("doc_bg", "#1f1f1f")
            fg = palette.get("doc_fg", "#f3f3f3")
            border = palette.get("console_border", palette.get("border", "#3c3c3c"))
        else:
            bg = palette.get("field", "#1a1a1a")
            fg = palette.get("fg", "#f3f3f3")
            border = palette.get("border", "#3c3c3c")

        options = {
            "bg": bg,
            "fg": fg,
            "insertbackground": fg,
            "bd": 0,
            "relief": tk.FLAT,
            "highlightthickness": 1,
            "highlightbackground": border,
            "highlightcolor": border,
        }

        for option_name, option_value in options.items():
            try:
                widget.configure(**{option_name: option_value})
            except Exception:
                pass

        seen_scrollbars: set[int] = set()
        for attr_name in ("vbar", "web_vbar"):
            scrollbar = getattr(widget, attr_name, None)
            if scrollbar is None:
                continue

            scrollbar_id = id(scrollbar)
            if scrollbar_id in seen_scrollbars:
                continue
            seen_scrollbars.add(scrollbar_id)

            if isinstance(scrollbar, WebSlimScrollbar):
                self.style_web_scrollbar(scrollbar, track_color=bg)
            else:
                self.style_native_scrollbar(
                    scrollbar,
                    background=palette.get("panel_alt", "#2d2d30"),
                    troughcolor=bg,
                    bordercolor=border
                )

    def style_listbox_widget(self, widget, bordercolor: str = None):
        if widget is None:
            return

        palette = getattr(self, "palette", {})
        border = bordercolor or palette.get("panel_border", palette.get("border", "#3c3c3c"))

        options = {
            "bg": palette.get("field", "#1a1a1a"),
            "fg": palette.get("fg", "#f3f3f3"),
            "selectbackground": palette.get("accent", "#3498db"),
            "selectforeground": palette.get("accent_text", "#ffffff"),
            "disabledforeground": palette.get("muted_dim", "#9a9a9a"),
            "highlightthickness": 1,
            "highlightbackground": border,
            "highlightcolor": border,
            "bd": 0,
            "relief": tk.FLAT,
        }

        for option_name, option_value in options.items():
            try:
                widget.configure(**{option_name: option_value})
            except Exception:
                pass

    def style_web_scrollbar(self, scrollbar, track_color: str = None):
        if scrollbar is None or not isinstance(scrollbar, WebSlimScrollbar):
            return

        palette = getattr(self, "palette", {})
        track = track_color or palette.get("panel", palette.get("bg", "#1e1e1e"))
        thumb = blend_hex_colors(
            palette.get("accent_hover", palette.get("accent", "#0e639c")),
            palette.get("accent_text", "#ffffff"),
            0.30,
        )
        thumb_hover = blend_hex_colors(thumb, palette.get("accent_text", "#ffffff"), 0.18)

        try:
            scrollbar.configure_style(
                track_color=track,
                thumb_color=thumb,
                thumb_hover_color=thumb_hover,
            )
        except Exception:
            pass

    def style_canvas_widget(self, widget, background: str = None, bordercolor: str = None):
        if widget is None:
            return

        palette = getattr(self, "palette", {})
        bg = background or palette.get("panel", "#252526")
        border = bordercolor or palette.get("panel_border", palette.get("border", "#3c3c3c"))

        options = {
            "bg": bg,
            "highlightthickness": 1,
            "highlightbackground": border,
            "highlightcolor": border,
            "bd": 0,
            "relief": tk.FLAT,
        }

        for option_name, option_value in options.items():
            try:
                widget.configure(**{option_name: option_value})
            except Exception:
                pass

    def _get_scale_colors(self, background: str = None) -> tuple[str, str, str, str, str]:
        palette = getattr(self, "palette", {})
        bg = self._coerce_color_hex(
            background,
            fallback=palette.get("panel", palette.get("bg", "#252526")),
        )
        success = palette.get("success", "#4ec9b0")
        track = blend_hex_colors(success, bg, 0.45)
        thumb = success
        thumb_hover = blend_hex_colors(thumb, palette.get("accent_text", "#ffffff"), 0.18)
        # Keep disabled sliders visually consistent with enabled ones; the non-interactive
        # state is conveyed by behavior, not by washing out the green marker.
        thumb_disabled = thumb
        return bg, track, thumb, thumb_hover, thumb_disabled

    @staticmethod
    def _paint_scale_track_image(image, color: str):
        if image is None:
            return
        try:
            image.blank()
            image.put(str(color), to=(0, 0, int(image.width()), int(image.height())))
        except Exception:
            pass

    @staticmethod
    def _paint_scale_thumb_image(image, fill_color: str, outline_color: str = None):
        if image is None:
            return

        try:
            image.blank()
            width = int(image.width())
            height = int(image.height())
            cx = (width - 1) / 2.0
            cy = (height - 1) / 2.0
            radius = max(2.0, (min(width, height) / 2.0) - 1.0)
            outline_threshold = radius - 1.15

            for y in range(height):
                for x in range(width):
                    dist = ((float(x) - cx) ** 2 + (float(y) - cy) ** 2) ** 0.5
                    if dist > radius:
                        continue
                    color = outline_color if outline_color and dist >= outline_threshold else fill_color
                    image.put(str(color), to=(x, y, x + 1, y + 1))
        except Exception:
            pass

    @staticmethod
    def _style_token(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "default"
        return "".join(ch if ch.isalnum() else "_" for ch in raw) or "default"

    def _coerce_color_hex(self, color: str = None, fallback: str = None) -> str:
        palette = getattr(self, "palette", {})
        default = str(fallback or palette.get("panel", palette.get("bg", "#252526")) or "#252526").strip()
        raw = str(color or "").strip() or default

        def _normalize_hex(value: str):
            candidate = str(value or "").strip()
            if not candidate.startswith("#"):
                return None
            token = candidate[1:]
            if len(token) == 3:
                token = "".join(ch * 2 for ch in token)
            if len(token) != 6:
                return None
            try:
                int(token, 16)
            except Exception:
                return None
            return f"#{token.lower()}"

        normalized = _normalize_hex(raw)
        if normalized:
            return normalized

        try:
            red, green, blue = self.root.winfo_rgb(raw)
            return f"#{red // 256:02x}{green // 256:02x}{blue // 256:02x}"
        except Exception:
            pass

        normalized_default = _normalize_hex(default)
        if normalized_default:
            return normalized_default
        return "#252526"

    def _resolve_widget_background(self, widget, fallback: str = None) -> str:
        palette = getattr(self, "palette", {})
        default_bg = self._coerce_color_hex(fallback, fallback=palette.get("panel", "#252526"))
        current = widget
        visited: set[int] = set()

        while current is not None:
            current_id = id(current)
            if current_id in visited:
                break
            visited.add(current_id)

            for option_name in ("bg", "background"):
                try:
                    value = str(current.cget(option_name) or "").strip()
                except Exception:
                    value = ""
                if value:
                    resolved = self._coerce_color_hex(value, fallback=None)
                    if resolved:
                        return resolved

            try:
                class_name = str(current.winfo_class() or "")
            except Exception:
                class_name = ""
            if class_name.startswith("T"):
                style_name = ""
                try:
                    style_name = str(current.cget("style") or "").strip()
                except Exception:
                    style_name = ""
                for lookup_style in (style_name, class_name):
                    if not lookup_style:
                        continue
                    try:
                        value = str(self.style.lookup(lookup_style, "background") or "").strip()
                    except Exception:
                        value = ""
                    if value:
                        resolved = self._coerce_color_hex(value, fallback=None)
                        if resolved:
                            return resolved

            current = getattr(current, "master", None)

        return default_bg

    def _ensure_horizontal_scale_style_assets(self, background: str = None, style_name: str = "Horizontal.TScale"):
        if not hasattr(self, "_horizontal_scale_style_assets"):
            self._horizontal_scale_style_assets = {}

        normalized_style = str(style_name or "Horizontal.TScale").strip() or "Horizontal.TScale"
        style_token = self._style_token(normalized_style)
        assets = self._horizontal_scale_style_assets.setdefault(normalized_style, {})
        if not assets:
            assets["track"] = tk.PhotoImage(master=self.root, width=16, height=4)
            assets["thumb"] = tk.PhotoImage(master=self.root, width=14, height=14)
            assets["thumb_active"] = tk.PhotoImage(master=self.root, width=14, height=14)
            assets["thumb_disabled"] = tk.PhotoImage(master=self.root, width=14, height=14)
            assets["trough_element"] = f"{style_token}.Horizontal.Scale.trough"
            assets["slider_element"] = f"{style_token}.Horizontal.Scale.slider"

            try:
                self.style.element_create(
                    assets["trough_element"],
                    "image",
                    assets["track"],
                    border=0,
                    sticky="ew",
                )
            except Exception:
                pass

            try:
                self.style.element_create(
                    assets["slider_element"],
                    "image",
                    assets["thumb"],
                    ("active", assets["thumb_active"]),
                    ("pressed", assets["thumb_active"]),
                    ("disabled", assets["thumb_disabled"]),
                    border=0,
                    sticky="",
                )
            except Exception:
                pass

        bg, track, thumb, thumb_hover, thumb_disabled = self._get_scale_colors(background)
        thumb_outline = blend_hex_colors(thumb, bg, 0.35)
        thumb_disabled_outline = blend_hex_colors(thumb_disabled, bg, 0.45)

        self._paint_scale_track_image(assets.get("track"), track)
        self._paint_scale_thumb_image(assets.get("thumb"), thumb, thumb_outline)
        self._paint_scale_thumb_image(assets.get("thumb_active"), thumb_hover, thumb_outline)
        self._paint_scale_thumb_image(assets.get("thumb_disabled"), thumb_disabled, thumb_disabled_outline)

        try:
            self.style.layout(
                normalized_style,
                [
                    (
                        assets["trough_element"],
                        {
                            "sticky": "ew",
                            "children": [
                                (assets["slider_element"], {"side": "left", "sticky": ""})
                            ],
                        },
                    )
                ],
            )
        except Exception:
            pass

        try:
            self.style.configure(
                normalized_style,
                background=bg,
                borderwidth=0,
                relief=tk.FLAT,
                sliderlength=14,
                troughcolor=track,
                lightcolor=track,
                darkcolor=track,
            )
        except Exception:
            pass

        try:
            self.style.map(
                normalized_style,
                background=[
                    ("disabled", bg),
                    ("active", bg),
                ],
                troughcolor=[
                    ("disabled", track),
                    ("active", track),
                ],
                lightcolor=[
                    ("disabled", track),
                    ("active", track),
                ],
                darkcolor=[
                    ("disabled", track),
                    ("active", track),
                ],
            )
        except Exception:
            pass

    def style_ttk_scale_widget(self, widget, background: str = None, base_style: str = None) -> str:
        if widget is None:
            return str(base_style or "Horizontal.TScale")

        try:
            current_style = str(widget.cget("style") or "").strip()
        except Exception:
            current_style = ""

        resolved_base_style = str(
            base_style
            or getattr(widget, "_base_ttk_scale_style", "")
            or current_style
            or "Horizontal.TScale"
        ).strip() or "Horizontal.TScale"
        if ".AutoBg_" in resolved_base_style:
            resolved_base_style = resolved_base_style.split(".AutoBg_", 1)[0] or "Horizontal.TScale"

        resolved_bg = self._coerce_color_hex(
            background,
            fallback=self._resolve_widget_background(getattr(widget, "master", None), fallback=background),
        )
        style_name = f"{resolved_base_style}.AutoBg_{self._style_token(resolved_bg)}"
        self._ensure_horizontal_scale_style_assets(background=resolved_bg, style_name=style_name)

        try:
            widget._base_ttk_scale_style = resolved_base_style
        except Exception:
            pass

        try:
            widget.configure(style=style_name, cursor="hand2", takefocus=0)
        except Exception:
            pass

        return style_name

    def style_ttk_frame_widget(self, widget, background: str = None, base_style: str = None) -> str:
        if widget is None:
            return str(base_style or "TFrame")

        try:
            current_style = str(widget.cget("style") or "").strip()
        except Exception:
            current_style = ""

        resolved_base_style = str(
            base_style
            or getattr(widget, "_base_ttk_frame_style", "")
            or current_style
            or "TFrame"
        ).strip() or "TFrame"
        if resolved_base_style.startswith("AutoBg_") and "." in resolved_base_style:
            resolved_base_style = resolved_base_style.split(".", 1)[1] or "TFrame"

        resolved_bg = self._coerce_color_hex(
            background,
            fallback=self._resolve_widget_background(getattr(widget, "master", None), fallback=background),
        )
        style_name = f"AutoBg_{self._style_token(resolved_bg)}.{resolved_base_style}"

        try:
            self.style.configure(style_name, background=resolved_bg)
        except Exception:
            pass

        try:
            widget._base_ttk_frame_style = resolved_base_style
        except Exception:
            pass

        try:
            widget.configure(style=style_name)
        except Exception:
            pass

        return style_name

    def style_ttk_panedwindow_widget(self, widget, background: str = None, base_style: str = None) -> str:
        if widget is None:
            return str(base_style or "TPanedwindow")

        try:
            current_style = str(widget.cget("style") or "").strip()
        except Exception:
            current_style = ""

        resolved_base_style = str(
            base_style
            or getattr(widget, "_base_ttk_panedwindow_style", "")
            or current_style
            or "TPanedwindow"
        ).strip() or "TPanedwindow"
        if resolved_base_style.startswith("AutoBg_") and "." in resolved_base_style:
            resolved_base_style = resolved_base_style.split(".", 1)[1] or "TPanedwindow"

        resolved_bg = self._coerce_color_hex(
            background,
            fallback=self._resolve_widget_background(getattr(widget, "master", None), fallback=background),
        )
        style_name = f"AutoBg_{self._style_token(resolved_bg)}.{resolved_base_style}"

        try:
            self.style.configure(style_name, background=resolved_bg)
        except Exception:
            pass

        try:
            widget._base_ttk_panedwindow_style = resolved_base_style
        except Exception:
            pass

        try:
            widget.configure(style=style_name)
        except Exception:
            pass

        return style_name

    def style_ttk_labelframe_widget(self, widget, background: str = None, base_style: str = None) -> str:
        if widget is None:
            return str(base_style or "TLabelframe")

        try:
            current_style = str(widget.cget("style") or "").strip()
        except Exception:
            current_style = ""

        resolved_base_style = str(
            base_style
            or getattr(widget, "_base_ttk_labelframe_style", "")
            or current_style
            or "TLabelframe"
        ).strip() or "TLabelframe"
        if resolved_base_style.startswith("AutoBg_") and "." in resolved_base_style:
            resolved_base_style = resolved_base_style.split(".", 1)[1] or "TLabelframe"

        resolved_bg = self._coerce_color_hex(
            background,
            fallback=self._resolve_widget_background(getattr(widget, "master", None), fallback=background),
        )
        palette = getattr(self, "palette", {})
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("fg", "#f3f3f3")
        style_name = f"AutoBg_{self._style_token(resolved_bg)}.{resolved_base_style}"
        label_style_name = f"{style_name}.Label"

        try:
            self.style.configure(
                style_name,
                background=resolved_bg,
                bordercolor=border,
                lightcolor=border,
                darkcolor=border,
                borderwidth=1,
                relief=tk.SOLID,
            )
        except Exception:
            pass

        try:
            current_font = self.style.lookup(f"{resolved_base_style}.Label", "font") or ("Segoe UI", 10, "bold")
        except Exception:
            current_font = ("Segoe UI", 10, "bold")

        try:
            self.style.configure(
                label_style_name,
                background=resolved_bg,
                foreground=fg,
                font=current_font,
            )
        except Exception:
            pass

        try:
            widget._base_ttk_labelframe_style = resolved_base_style
        except Exception:
            pass

        try:
            widget.configure(style=style_name)
        except Exception:
            pass

        return style_name

    def _update_adaptive_wraplength(self, widget):
        if widget is None:
            return

        if bool(getattr(self, "_main_window_hidden_for_startup", False)) and not bool(getattr(self, "_main_window_revealed", False)):
            return

        try:
            base_wrap = int(float(getattr(widget, "_adaptive_wrap_base", 0) or 0))
        except Exception:
            base_wrap = 0
        if base_wrap <= 0:
            return

        container = getattr(widget, "_adaptive_wrap_container", None) or getattr(widget, "master", None)
        mapped = False
        for candidate in (container, widget):
            if candidate is None:
                continue
            try:
                if bool(candidate.winfo_ismapped()):
                    mapped = True
                    break
            except Exception:
                pass
        if not mapped:
            return

        width = 0
        for candidate in (container, widget):
            if candidate is None:
                continue
            try:
                width = int(candidate.winfo_width() or 0)
            except Exception:
                width = 0
            if width > 1:
                break

        if width <= 1:
            return

        try:
            padding = int(getattr(widget, "_adaptive_wrap_padding", 18))
        except Exception:
            padding = 18
        try:
            min_wrap = int(getattr(widget, "_adaptive_wrap_min", 80))
        except Exception:
            min_wrap = 80
        try:
            max_wrap = int(getattr(widget, "_adaptive_wrap_max", base_wrap) or base_wrap)
        except Exception:
            max_wrap = base_wrap

        target = max(min_wrap, int(width) - padding)
        if max_wrap > 0:
            target = min(max_wrap, target)

        try:
            current_wrap = int(float(widget.cget("wraplength") or 0))
        except Exception:
            current_wrap = 0

        if abs(current_wrap - target) <= 2:
            return

        try:
            widget.configure(wraplength=target)
        except Exception:
            pass

    def _refresh_adaptive_wraps(self, root):
        if root is None:
            return

        visited: set[int] = set()

        def walk(widget):
            if widget is None:
                return

            widget_id = id(widget)
            if widget_id in visited:
                return
            visited.add(widget_id)

            if hasattr(widget, "_adaptive_wrap_base"):
                try:
                    self._update_adaptive_wraplength(widget)
                except Exception:
                    pass

            try:
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass

        walk(root)

    def _refresh_adaptive_wraps_for_container(self, container):
        if container is None:
            return

        try:
            container._adaptive_wrap_after_id = None
        except Exception:
            pass

        targets = list(getattr(container, "_adaptive_wrap_targets", []) or [])
        seen: set[int] = set()
        for widget in targets:
            if widget is None:
                continue
            widget_id = id(widget)
            if widget_id in seen:
                continue
            seen.add(widget_id)
            try:
                if bool(widget.winfo_exists()):
                    self._update_adaptive_wraplength(widget)
            except Exception:
                pass

    def _schedule_adaptive_wrap_refresh(self, container):
        if container is None:
            return

        pending = getattr(container, "_adaptive_wrap_after_id", None)
        if pending is not None:
            return

        try:
            container._adaptive_wrap_after_id = container.after_idle(
                lambda target=container: self._refresh_adaptive_wraps_for_container(target)
            )
        except Exception:
            try:
                container._adaptive_wrap_after_id = None
            except Exception:
                pass

    def ensure_adaptive_wrap(self, widget, container=None, *, padding: int = 18, min_wrap: int = 80):
        if widget is None:
            return

        try:
            configured_wrap = int(float(widget.cget("wraplength") or 0))
        except Exception:
            configured_wrap = 0
        if configured_wrap <= 0:
            return

        if not hasattr(widget, "_adaptive_wrap_base"):
            try:
                widget._adaptive_wrap_base = int(configured_wrap)
            except Exception:
                return
        try:
            widget._adaptive_wrap_max = max(int(getattr(widget, "_adaptive_wrap_max", 0) or 0), int(configured_wrap))
        except Exception:
            widget._adaptive_wrap_max = int(configured_wrap)
        widget._adaptive_wrap_container = container or getattr(widget, "master", None)
        widget._adaptive_wrap_padding = int(padding)
        widget._adaptive_wrap_min = int(min_wrap)

        container_widget = getattr(widget, "_adaptive_wrap_container", None)
        if container_widget is not None:
            targets = list(getattr(container_widget, "_adaptive_wrap_targets", []) or [])
            if all(existing is not widget for existing in targets):
                targets.append(widget)
                try:
                    container_widget._adaptive_wrap_targets = targets
                except Exception:
                    pass
            if not bool(getattr(container_widget, "_adaptive_wrap_bound", False)):
                try:
                    container_widget.bind(
                        "<Configure>",
                        lambda _event, target=container_widget: self._schedule_adaptive_wrap_refresh(target),
                        add="+",
                    )
                    container_widget._adaptive_wrap_bound = True
                except Exception:
                    pass
            self._schedule_adaptive_wrap_refresh(container_widget)

        self._update_adaptive_wraplength(widget)

    def style_classic_scale_widget(self, widget, background: str = None):
        if widget is None:
            return

        bg, track, thumb, thumb_hover, thumb_disabled = self._get_scale_colors(background)
        is_disabled = False
        try:
            is_disabled = str(widget.cget("state") or "").lower() == "disabled"
        except Exception:
            is_disabled = False

        thumb_color = thumb_disabled if is_disabled else thumb
        active_thumb = thumb_disabled if is_disabled else thumb_hover

        options = {
            "bg": bg,
            "troughcolor": track,
            "activebackground": active_thumb,
            "highlightbackground": bg,
            "highlightcolor": bg,
            "highlightthickness": 0,
            "bd": 0,
            "relief": tk.FLAT,
            "sliderrelief": tk.FLAT,
            "sliderlength": 14,
            "width": 4,
            "fg": thumb_color,
        }

        for option_name, option_value in options.items():
            try:
                widget.configure(**{option_name: option_value})
            except Exception:
                pass

    def _get_panel_label_style(self, style_name: str | None) -> str | None:
        style_name = str(style_name or "").strip()
        if style_name.startswith("Panel"):
            return style_name

        mapping = {
            "": "Panel.TLabel",
            "TLabel": "Panel.TLabel",
            "Muted.TLabel": "PanelMuted.TLabel",
            "Info.TLabel": "PanelInfo.TLabel",
        }
        return mapping.get(style_name)

    def _get_panel_control_style(self, class_name: str, style_name: str | None) -> str | None:
        current_style = str(style_name or "").strip()
        if current_style.startswith("Panel"):
            return current_style

        mappings = {
            "TCheckbutton": {
                "": "Panel.TCheckbutton",
                "TCheckbutton": "Panel.TCheckbutton",
            },
            "TRadiobutton": {
                "": "Panel.TRadiobutton",
                "TRadiobutton": "Panel.TRadiobutton",
            },
        }
        return mappings.get(str(class_name or "").strip(), {}).get(current_style)

    def style_panel_surface(self, root, background: str = None):
        if root is None:
            return

        palette = getattr(self, "palette", {})
        bg = self._coerce_color_hex(
            background,
            fallback=palette.get("panel", "#252526"),
        )
        visited: set[int] = set()

        def walk(widget):
            if widget is None:
                return

            widget_id = id(widget)
            if widget_id in visited:
                return
            visited.add(widget_id)

            try:
                class_name = str(widget.winfo_class())
            except Exception:
                class_name = ""

            if widget is root:
                local_bg = bg
            else:
                local_bg = self._resolve_widget_background(getattr(widget, "master", None), fallback=bg)

            if isinstance(widget, WebSlimScrollbar):
                self.style_web_scrollbar(widget, track_color=local_bg)
            elif class_name == "TScale":
                self.style_ttk_scale_widget(widget, background=local_bg)
            elif class_name == "Scale":
                self.style_classic_scale_widget(widget, background=local_bg)
            elif class_name == "TFrame":
                try:
                    current_style = str(widget.cget("style") or "").strip()
                except Exception:
                    current_style = ""
                self.style_ttk_frame_widget(widget, background=local_bg, base_style=(current_style or "TFrame"))
            elif class_name == "TPanedwindow":
                try:
                    current_style = str(widget.cget("style") or "").strip()
                except Exception:
                    current_style = ""
                self.style_ttk_panedwindow_widget(widget, background=local_bg, base_style=(current_style or "TPanedwindow"))
            elif class_name == "TLabelframe":
                try:
                    current_style = str(widget.cget("style") or "").strip()
                except Exception:
                    current_style = ""
                self.style_ttk_labelframe_widget(widget, background=local_bg, base_style=(current_style or "TLabelframe"))
            elif class_name == "TLabel":
                try:
                    current_style = str(widget.cget("style") or "").strip()
                except Exception:
                    current_style = ""
                target_style = self._get_panel_label_style(current_style)
                if target_style and target_style != current_style:
                    try:
                        widget.configure(style=target_style)
                    except Exception:
                        pass
            elif class_name in {"TCheckbutton", "TRadiobutton"}:
                try:
                    current_style = str(widget.cget("style") or "").strip()
                except Exception:
                    current_style = ""
                target_style = self._get_panel_control_style(class_name, current_style)
                if target_style and target_style != current_style:
                    try:
                        widget.configure(style=target_style)
                    except Exception:
                        pass
            elif class_name == "Frame":
                try:
                    widget.configure(bg=local_bg)
                except Exception:
                    pass
            elif class_name == "Label":
                try:
                    widget.configure(bg=local_bg)
                except Exception:
                    pass
            elif class_name == "Canvas":
                try:
                    widget.configure(bg=local_bg)
                except Exception:
                    pass
            elif class_name == "Labelframe":
                try:
                    widget.configure(
                        bg=local_bg,
                        fg=palette.get("fg", "#f3f3f3"),
                        highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                        highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    )
                except Exception:
                    pass

            try:
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass

        walk(root)

    def style_dialog_window(self, dialog, title: str = "", geometry: str = None, parent=None):
        palette = self.palette
        dialog.configure(bg=palette["bg"])
        if title:
            dialog.title(title)
        if geometry:
            dialog.geometry(geometry)
        dialog.transient(parent or self.root)
        dialog.resizable(False, False)
        try:
            dialog.grab_set()
        except Exception:
            pass
        return dialog

    def _fit_dialog_to_content(
        self,
        dialog,
        parent=None,
        min_width: int = 520,
        min_height: int = 220,
        margin: int = 24,
    ):
        try:
            dialog.update_idletasks()

            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            final_width = max(min_width, dialog.winfo_reqwidth())
            final_height = max(min_height, dialog.winfo_reqheight())

            max_width = max(min_width, screen_width - (margin * 2))
            max_height = max(min_height, screen_height - (margin * 2))
            final_width = min(final_width, max_width)
            final_height = min(final_height, max_height)

            anchor = parent or self.root
            x = (screen_width - final_width) // 2
            y = (screen_height - final_height) // 2

            try:
                anchor.update_idletasks()
                if anchor.winfo_ismapped():
                    x = anchor.winfo_rootx() + max(0, (anchor.winfo_width() - final_width) // 2)
                    y = anchor.winfo_rooty() + max(0, (anchor.winfo_height() - final_height) // 2)
            except Exception:
                pass

            x = max(margin, min(x, screen_width - final_width - margin))
            y = max(margin, min(y, screen_height - final_height - margin))

            dialog.minsize(min_width, min_height)
            dialog.geometry(f"{final_width}x{final_height}+{x}+{y}")
        except Exception:
            pass

    def themed_message_dialog(
        self,
        title: str,
        message: str,
        parent=None,
        buttons=None,
        default_button: str = None,
        tone: str = "info",
        wraplength: int = 440,
    ):
        buttons = list(buttons or ["OK"])
        default_button = default_button or buttons[0]
        palette = self.palette
        tone_colors = {
            "info": palette["accent"],
            "warning": palette["warning"],
            "error": palette["error"],
            "success": palette["success"],
        }
        header_color = tone_colors.get(tone, palette["accent"])

        dialog = tk.Toplevel(self.root)
        self.style_dialog_window(dialog, title=title, geometry="520x240", parent=parent)

        shell = tk.Frame(dialog, bg=palette["bg"], bd=1, highlightthickness=1, highlightbackground=palette["border"])
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        header = tk.Frame(shell, bg=header_color, height=8)
        header.pack(fill=tk.X)

        body = tk.Frame(shell, bg=palette["panel"])
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text=title,
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(16, 8))

        tk.Label(
            body,
            text=message,
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 10),
            wraplength=wraplength,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

        result = {"value": None}

        btn_row = tk.Frame(body, bg=palette["panel"])
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 16))

        def close_with(value):
            result["value"] = value
            dialog.destroy()

        for label in reversed(buttons):
            style_name = "Accent.TButton" if label == default_button else "TButton"
            ttk.Button(
                btn_row,
                text=label,
                command=lambda value=label: close_with(value),
                style=style_name,
            ).pack(side=tk.RIGHT, padx=(8, 0))

        self._fit_dialog_to_content(dialog, parent=parent, min_width=520, min_height=240)
        dialog.bind("<Escape>", lambda _e: close_with(None))
        dialog.bind("<Return>", lambda _e: close_with(default_button))
        dialog.wait_window()
        return result["value"]

    def themed_confirm(
        self,
        title: str,
        message: str,
        parent=None,
        confirm_label: str = "OK",
        cancel_label: str = "Anuluj",
        tone: str = "warning"
    ) -> bool:
        result = self.themed_message_dialog(
            title=title,
            message=message,
            parent=parent,
            buttons=[cancel_label, confirm_label],
            default_button=confirm_label,
            tone=tone,
        )
        return result == confirm_label

    def themed_info(self, title: str, message: str, parent=None, tone: str = "info"):
        self.themed_message_dialog(
            title=title,
            message=message,
            parent=parent,
            buttons=["OK"],
            default_button="OK",
            tone=tone,
        )

    def themed_error(self, title: str, message: str, parent=None):
        self.themed_info(title=title, message=message, parent=parent, tone="error")

    def _install_themed_dialog_hooks(self):
        def _extract_parent(kwargs):
            return kwargs.get("parent", self.root)

        def showinfo(title, message, **kwargs):
            self.themed_info(title, message, parent=_extract_parent(kwargs), tone="info")
            return "ok"

        def showwarning(title, message, **kwargs):
            self.themed_info(title, message, parent=_extract_parent(kwargs), tone="warning")
            return "ok"

        def showerror(title, message, **kwargs):
            self.themed_error(title, message, parent=_extract_parent(kwargs))
            return "ok"

        def askyesno(title, message, **kwargs):
            return self.themed_confirm(
                title,
                message,
                parent=_extract_parent(kwargs),
                confirm_label="Tak",
                cancel_label="Nie",
                tone="warning"
            )

        def askokcancel(title, message, **kwargs):
            return self.themed_confirm(
                title,
                message,
                parent=_extract_parent(kwargs),
                confirm_label="OK",
                cancel_label="Anuluj",
                tone="warning"
            )

        def askstring(title, prompt, **kwargs):
            return self.themed_ask_string(
                title,
                prompt,
                parent=_extract_parent(kwargs),
                action_label="OK",
                initial_value=kwargs.get("initialvalue", "") or ""
            )

        messagebox.showinfo = showinfo
        messagebox.showwarning = showwarning
        messagebox.showerror = showerror
        messagebox.askyesno = askyesno
        messagebox.askokcancel = askokcancel
        simpledialog.askstring = askstring

    def themed_ask_string(
        self,
        title: str,
        prompt: str,
        parent=None,
        action_label: str = "OK",
        initial_value: str = "",
    ):
        palette = self.palette
        dialog = tk.Toplevel(self.root)
        self.style_dialog_window(dialog, title=title, geometry="520x240", parent=parent)

        shell = tk.Frame(dialog, bg=palette["bg"], bd=1, highlightthickness=1, highlightbackground=palette["border"])
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        body = tk.Frame(shell, bg=palette["panel"])
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text=title,
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(16, 8))

        tk.Label(
            body,
            text=prompt,
            bg=palette["panel"],
            fg=palette["fg"],
            font=("Segoe UI", 10),
            wraplength=440,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

        value_var = tk.StringVar(value=initial_value)
        entry = ttk.Entry(body, textvariable=value_var)
        entry.pack(fill=tk.X, padx=16, pady=(0, 16))
        entry.focus_set()
        entry.selection_range(0, tk.END)

        result = {"value": None}

        def accept():
            result["value"] = value_var.get().strip()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        btn_row = tk.Frame(body, bg=palette["panel"])
        btn_row.pack(fill=tk.X, padx=16, pady=(0, 16))
        ttk.Button(btn_row, text=action_label, command=accept, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Anuluj", command=cancel).pack(side=tk.RIGHT, padx=(0, 8))

        self._fit_dialog_to_content(dialog, parent=parent, min_width=520, min_height=240)
        dialog.bind("<Return>", lambda _e: accept())
        dialog.bind("<Escape>", lambda _e: cancel())
        dialog.wait_window()
        return result["value"]

    def show_about_dialog(self):
        details = (
            f"{CONFIG.APP_NAME}\n"
            f"Wersja: {CONFIG.VERSION}\n"
            f"Autor: {APP_AUTHOR}\n"
            f"Styl: {self.current_theme_name}"
        )
        self.themed_info("O aplikacji", details, parent=self.root, tone="info")
    
    def _setup_style(self, theme_key: str = None):
        try:
            theme_key = theme_key or self.current_theme_key
            if theme_key not in self.themes:
                theme_key = "dark_visual_cs"

            self.current_theme_key = theme_key
            self.current_theme_name = self.themes[theme_key]["label"]
            self.palette = dict(self.themes[theme_key]["palette"])
            if hasattr(self, "theme_var"):
                self.theme_var.set(theme_key)
            palette = self.palette

            self.root.configure(bg=palette["bg"])

            named_fonts = {
                "TkDefaultFont": ("Segoe UI", 10, "normal"),
                "TkTextFont": ("Segoe UI", 10, "normal"),
                "TkMenuFont": ("Segoe UI", 10, "normal"),
                "TkHeadingFont": ("Segoe UI", 10, "bold"),
                "TkCaptionFont": ("Segoe UI", 10, "bold"),
                "TkSmallCaptionFont": ("Segoe UI", 9, "normal"),
                "TkIconFont": ("Segoe UI", 10, "normal"),
                "TkTooltipFont": ("Segoe UI", 10, "normal"),
                "TkFixedFont": ("Consolas", 10, "normal"),
            }
            for font_name, (family, size, weight) in named_fonts.items():
                try:
                    font_obj = tkfont.nametofont(font_name)
                    font_obj.configure(family=family, size=size, weight=weight, slant="roman")
                except Exception:
                    pass

            self.root.option_add("*Font", "{Segoe UI} 10")
            self.root.option_add("*Menu.Font", "{Segoe UI} 10")
            self.root.option_add("*Label.background", palette["bg"])
            self.root.option_add("*Label.foreground", palette["fg"])
            self.root.option_add("*Frame.background", palette["bg"])
            self.root.option_add("*Canvas.background", palette["panel"])
            self.root.option_add("*Entry.background", palette["field"])
            self.root.option_add("*Entry.foreground", palette["fg"])
            self.root.option_add("*Entry.insertBackground", palette["fg"])
            self.root.option_add("*Listbox.background", palette["field"])
            self.root.option_add("*Listbox.foreground", palette["fg"])
            self.root.option_add("*Listbox.selectBackground", palette["accent"])
            self.root.option_add("*Listbox.selectForeground", "#ffffff")
            self.root.option_add("*Text.background", palette["field"])
            self.root.option_add("*Text.foreground", palette["fg"])
            self.root.option_add("*Text.insertBackground", palette["fg"])
            self.root.option_add("*Menu.background", palette["panel"])
            self.root.option_add("*Menu.foreground", palette["fg"])
            self.root.option_add("*Menu.activeBackground", palette["accent"])
            self.root.option_add("*Menu.activeForeground", "#ffffff")

            self.style.theme_use('clam')

            def safe_configure(style_name, **kwargs):
                try:
                    self.style.configure(style_name, **kwargs)
                except Exception:
                    pass

            def safe_map(style_name, **kwargs):
                try:
                    self.style.map(style_name, **kwargs)
                except Exception:
                    pass

            control_arrow = palette.get("success", palette.get("accent", palette["fg"]))
            control_arrow_disabled = palette.get("muted_dim", palette["fg"])

            safe_configure(
                '.',
                background=palette["bg"],
                foreground=palette["fg"],
                fieldbackground=palette["field"],
                font=('Segoe UI', 10)
            )
            safe_configure('TFrame', background=palette["bg"])
            safe_configure('Panel.TFrame', background=palette["panel"])
            safe_configure(
                'Card.TFrame',
                background=palette["panel"],
                bordercolor=palette.get("panel_border", palette["border"]),
                lightcolor=palette.get("panel_border", palette["border"]),
                darkcolor=palette.get("panel_border", palette["border"]),
                borderwidth=1,
                relief=tk.SOLID
            )
            safe_configure('TPanedwindow', background=palette["panel"])
            safe_configure('TLabel', background=palette["bg"], foreground=palette["fg"], padding=2)
            safe_configure(
                'Panel.TLabel',
                background=palette["panel"],
                foreground=palette["fg"],
                padding=2
            )
            safe_configure(
                'TCheckbutton',
                background=palette["bg"],
                foreground=palette["fg"],
                focuscolor=palette["bg"],
                indicatorcolor=palette["field"],
            )
            safe_map(
                'TCheckbutton',
                background=[
                    ('active', palette["bg"]),
                    ('disabled', palette["bg"]),
                ],
                foreground=[('disabled', palette["muted_dim"])],
                indicatorcolor=[
                    ('selected', palette.get("success", palette.get("accent", "#4ec9b0"))),
                    ('active', palette["field"]),
                    ('!selected', palette["field"]),
                    ('disabled', palette["panel_alt"]),
                ]
            )
            safe_configure(
                'Panel.TCheckbutton',
                background=palette["panel"],
                foreground=palette["fg"],
                focuscolor=palette["panel"],
                indicatorcolor=palette["field"],
            )
            safe_map(
                'Panel.TCheckbutton',
                background=[
                    ('active', palette["panel"]),
                    ('disabled', palette["panel"]),
                ],
                foreground=[('disabled', palette["muted_dim"])],
                indicatorcolor=[
                    ('selected', palette.get("success", palette.get("accent", "#4ec9b0"))),
                    ('active', palette["field"]),
                    ('!selected', palette["field"]),
                    ('disabled', palette["panel_alt"]),
                ]
            )
            safe_configure(
                'TRadiobutton',
                background=palette["bg"],
                foreground=palette["fg"],
                focuscolor=palette["bg"],
                indicatorcolor=palette["field"],
            )
            safe_map(
                'TRadiobutton',
                background=[
                    ('active', palette["bg"]),
                    ('disabled', palette["bg"]),
                ],
                foreground=[('disabled', palette["muted_dim"])],
                indicatorcolor=[
                    ('selected', palette.get("success", palette.get("accent", "#4ec9b0"))),
                    ('active', palette["field"]),
                    ('!selected', palette["field"]),
                    ('disabled', palette["panel_alt"]),
                ]
            )
            safe_configure(
                'Panel.TRadiobutton',
                background=palette["panel"],
                foreground=palette["fg"],
                focuscolor=palette["panel"],
                indicatorcolor=palette["field"],
            )
            safe_map(
                'Panel.TRadiobutton',
                background=[
                    ('active', palette["panel"]),
                    ('disabled', palette["panel"]),
                ],
                foreground=[('disabled', palette["muted_dim"])],
                indicatorcolor=[
                    ('selected', palette.get("success", palette.get("accent", "#4ec9b0"))),
                    ('active', palette["field"]),
                    ('!selected', palette["field"]),
                    ('disabled', palette["panel_alt"]),
                ]
            )
            safe_configure(
                'Info.TLabel',
                background=palette["bg"],
                foreground=palette.get("info", palette["accent"]),
                padding=2
            )
            safe_configure(
                'Muted.TLabel',
                background=palette["bg"],
                foreground=palette["muted"],
                padding=2
            )
            safe_configure(
                'PanelInfo.TLabel',
                background=palette["panel"],
                foreground=palette.get("info", palette["accent"]),
                padding=2
            )
            safe_configure(
                'PanelSuccess.TLabel',
                background=palette["panel"],
                foreground=palette["success"],
                padding=2
            )
            safe_configure(
                'PanelError.TLabel',
                background=palette["panel"],
                foreground=palette["error"],
                padding=2
            )
            safe_configure(
                'PanelMuted.TLabel',
                background=palette["panel"],
                foreground=palette["muted"],
                padding=2
            )
            safe_configure(
                'PanelStatusNeutral.TLabel',
                background=palette["panel"],
                foreground=palette["muted"],
                padding=2,
                font=('Segoe UI', 10, 'bold')
            )
            safe_configure(
                'PanelStatusInfo.TLabel',
                background=palette["panel"],
                foreground=palette.get("info", palette["accent"]),
                padding=2,
                font=('Segoe UI', 10, 'bold')
            )
            safe_configure(
                'PanelStatusSuccess.TLabel',
                background=palette["panel"],
                foreground=palette["success"],
                padding=2,
                font=('Segoe UI', 10, 'bold')
            )
            safe_configure(
                'PanelStatusWarning.TLabel',
                background=palette["panel"],
                foreground=palette["warning"],
                padding=2,
                font=('Segoe UI', 10, 'bold')
            )
            safe_configure(
                'PanelStatusError.TLabel',
                background=palette["panel"],
                foreground=palette["error"],
                padding=2,
                font=('Segoe UI', 10, 'bold')
            )
            safe_configure(
                'TLabelframe',
                background=palette["panel"],
                bordercolor=palette.get("panel_border", palette["border"]),
                lightcolor=palette.get("panel_border", palette["border"]),
                darkcolor=palette.get("panel_border", palette["border"]),
                borderwidth=1,
                relief=tk.SOLID
            )
            safe_configure(
                'TLabelframe.Label',
                background=palette["panel"],
                foreground=palette["fg"],
                font=('Segoe UI', 10, 'bold')
            )
            safe_configure(
                'AccentPanel.Horizontal.TSeparator',
                background=palette.get("surface_info", palette.get("accent", "#0e639c")),
                troughcolor=palette.get("panel", "#252526"),
                bordercolor=palette.get("surface_info", palette.get("accent", "#0e639c")),
                lightcolor=palette.get("surface_info", palette.get("accent", "#0e639c")),
                darkcolor=palette.get("surface_info", palette.get("accent", "#0e639c")),
            )
            safe_configure(
                'TNotebook',
                background=palette["panel"],
                borderwidth=1,
                bordercolor=palette.get("panel_border", palette["border"]),
                lightcolor=palette.get("panel_border", palette["border"]),
                darkcolor=palette.get("panel_border", palette["border"]),
                tabmargins=[0, 0, 0, 0]
            )
            safe_configure(
                'TNotebook.Tab',
                background=palette["panel_alt"],
                foreground=palette["muted"],
                borderwidth=1,
                bordercolor=palette.get("panel_border", palette["border"]),
                lightcolor=palette.get("panel_border", palette["border"]),
                darkcolor=palette.get("panel_border", palette["border"]),
                relief=tk.SOLID,
                padding=[12, 5],
                font=('Segoe UI', 9, 'normal')
            )
            safe_map(
                'TNotebook.Tab',
                background=[
                    ('disabled', palette.get("tab_disabled_bg", palette["bg"])),
                    ('selected', palette["panel"]),
                    ('active', palette["panel_alt"])
                ],
                foreground=[
                    ('disabled', palette.get("tab_disabled_fg", palette["muted_dim"])),
                    ('selected', palette["fg"]),
                    ('active', palette["fg"])
                ],
                bordercolor=[
                    ('disabled', palette.get("panel_border", palette["border"])),
                    ('selected', palette["accent"]),
                    ('active', palette.get("panel_border", palette["border"]))
                ],
                lightcolor=[
                    ('disabled', palette.get("panel_border", palette["border"])),
                    ('selected', palette["accent"]),
                    ('active', palette.get("panel_border", palette["border"]))
                ],
                darkcolor=[
                    ('disabled', palette.get("panel_border", palette["border"])),
                    ('selected', palette["accent"]),
                    ('active', palette.get("panel_border", palette["border"]))
                ],
                padding=[
                    ('disabled', [12, 5]),
                    ('selected', [12, 5]),
                    ('active', [12, 5])
                ],
                expand=[
                    ('disabled', [0, 0, 0, 0]),
                    ('selected', [0, 0, 0, 0]),
                    ('active', [0, 0, 0, 0])
                ]
            )
            nav_button_font = ('Segoe UI Semibold', 10)
            cta_outline = blend_hex_colors(
                palette.get("success", "#4ec9b0"),
                palette.get("panel_border", palette["border"]),
                0.18,
            )
            cta_outline_hover = blend_hex_colors(
                palette.get("success", "#4ec9b0"),
                palette.get("accent_hover", palette.get("accent", "#63c7ff")),
                0.24,
            )
            safe_configure(
                'TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=cta_outline,
                lightcolor=cta_outline,
                darkcolor=cta_outline,
                padding=6,
                borderwidth=1,
                relief=tk.SOLID,
            )
            safe_map(
                'TButton',
                background=[
                    ('active', palette.get("button_hover", palette["panel_alt"])),
                    ('pressed', palette["accent_selected"]),
                    ('disabled', palette["panel"])
                ],
                foreground=[('disabled', palette["muted_dim"])],
                bordercolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'Accent.TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=cta_outline,
                lightcolor=cta_outline,
                darkcolor=cta_outline,
                padding=6,
                borderwidth=1,
                relief=tk.SOLID,
                font=nav_button_font,
            )
            safe_map(
                'Accent.TButton',
                background=[
                    ('active', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('pressed', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('disabled', palette["panel"])
                ],
                foreground=[('disabled', palette["muted_dim"])],
                bordercolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'GuidedNeutral.TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=cta_outline,
                lightcolor=cta_outline,
                darkcolor=cta_outline,
                padding=6,
                borderwidth=1,
                relief=tk.SOLID,
                font=nav_button_font,
            )
            safe_map(
                'GuidedNeutral.TButton',
                background=[
                    ('active', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('pressed', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('disabled', palette["panel"])
                ],
                foreground=[('disabled', palette["muted_dim"])],
                bordercolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'GuidedAccent.TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=cta_outline,
                lightcolor=cta_outline,
                darkcolor=cta_outline,
                padding=6,
                borderwidth=1,
                relief=tk.SOLID,
                font=nav_button_font,
            )
            safe_map(
                'GuidedAccent.TButton',
                background=[
                    ('active', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('pressed', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('disabled', palette["panel"])
                ],
                foreground=[('disabled', palette["muted_dim"])],
                bordercolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', cta_outline_hover),
                    ('pressed', cta_outline_hover),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'TEntry',
                fieldbackground=palette["field"],
                foreground=palette["fg"],
                bordercolor=palette["border"],
                lightcolor=palette["border"],
                darkcolor=palette["border"]
            )
            safe_map(
                'TEntry',
                fieldbackground=[
                    ('readonly', palette["field"]),
                    ('disabled', palette["panel"])
                ],
                foreground=[
                    ('readonly', palette["fg"]),
                    ('disabled', palette["muted_dim"])
                ],
                selectbackground=[
                    ('readonly', palette["field"]),
                    ('disabled', palette["panel"])
                ],
                selectforeground=[
                    ('readonly', palette["fg"]),
                    ('disabled', palette["muted_dim"])
                ]
            )
            safe_configure(
                'TCombobox',
                fieldbackground=palette["field"],
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=palette["border"],
                lightcolor=palette["border"],
                darkcolor=palette["border"],
                arrowsize=14,
                arrowcolor=control_arrow,
            )
            safe_map(
                'TCombobox',
                fieldbackground=[('readonly', palette["field"])],
                selectbackground=[('readonly', palette["accent"])],
                selectforeground=[('readonly', '#ffffff')],
                foreground=[('disabled', palette["muted_dim"])],
                arrowcolor=[
                    ('readonly', control_arrow),
                    ('active', control_arrow),
                    ('disabled', control_arrow_disabled),
                ],
            )
            safe_configure(
                'TSpinbox',
                fieldbackground=palette["field"],
                foreground=palette["fg"],
                bordercolor=palette["border"],
                lightcolor=palette["border"],
                darkcolor=palette["border"],
                arrowsize=14,
                arrowcolor=control_arrow,
            )
            safe_map(
                'TSpinbox',
                arrowcolor=[
                    ('active', control_arrow),
                    ('disabled', control_arrow_disabled),
                ],
            )
            safe_configure(
                'Treeview',
                background=palette["field"],
                fieldbackground=palette["field"],
                foreground=palette["fg"],
                bordercolor=palette["border"],
                rowheight=24
            )
            safe_map(
                'Treeview',
                background=[('selected', palette["accent_selected"])],
                foreground=[('selected', '#ffffff')]
            )
            safe_configure(
                'Treeview.Heading',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=palette["border"],
                font=('Segoe UI', 10, 'bold')
            )
            safe_map(
                'Treeview.Heading',
                background=[('active', '#37373d')]
            )
            safe_configure(
                'Horizontal.TProgressbar',
                background=palette["accent"],
                troughcolor=palette["panel_alt"],
                bordercolor=palette["border"],
                lightcolor=palette["accent"],
                darkcolor=palette["accent"]
            )
            self._ensure_horizontal_scale_style_assets(background=palette.get("panel", palette["bg"]))
            safe_configure(
                'Vertical.TScrollbar',
                background=palette["panel_alt"],
                troughcolor=palette["bg"],
                bordercolor=palette["border"],
                arrowcolor=control_arrow
            )
            safe_map(
                'Vertical.TScrollbar',
                background=[('active', palette.get("button_hover", palette["panel_alt"]))],
                arrowcolor=[('active', control_arrow), ('disabled', control_arrow_disabled)]
            )
            safe_configure(
                'Horizontal.TScrollbar',
                background=palette["panel_alt"],
                troughcolor=palette["bg"],
                bordercolor=palette["border"],
                arrowcolor=control_arrow
            )
            safe_map(
                'Horizontal.TScrollbar',
                background=[('active', palette.get("button_hover", palette["panel_alt"]))],
                arrowcolor=[('active', control_arrow), ('disabled', control_arrow_disabled)]
            )
        except: pass

    def get_main_tab_label(self, tab_key: str) -> str:
        labels = {
            "campaign": "[Z1] Wizard",
            "annotation": "[Z2] Anotacja tablic",
            "characters": "[Z3] Autoanotacja znaków tablic",
            "training": "[Z4] Trening i analiza",
            "help": "[Z5] Instrukcja i architektura",
        }
        return labels.get(tab_key, tab_key)

    def refresh_main_tab_labels(self, active_tab_key: str = None):
        for key, tab in self.tabs.items():
            try:
                label = self.get_main_tab_label(key)
                self.notebook.tab(str(tab.frame), text=label)
            except Exception:
                pass

    def _format_project_created_at(self, created_at: str) -> str:
        value = str(created_at or "").strip()
        if not value:
            return ""

        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return value.replace("T", " ")

    def refresh_window_title(self):
        base_title = f"{CONFIG.APP_NAME} v{CONFIG.VERSION}"

        try:
            from ..campaign_manager import CAMPAIGN

            active_project = CAMPAIGN.get_active_project_name()
            if not active_project:
                self._refresh_menu_badge()
                self.root.title(base_title)
                return

            created_at = CAMPAIGN.get_project_created_at(active_project)
            created_label = self._format_project_created_at(created_at)

            title = f"{base_title} | Projekt: {active_project}"
            if created_label:
                title += f" | Utworzono: {created_label}"

            self._refresh_menu_badge()
            self.root.title(title)
        except Exception:
            self._refresh_menu_badge()
            self.root.title(base_title)
    
    def _create_tabs(self, progress_callback=None):
        def _progress(value, message):
            if callable(progress_callback):
                try:
                    progress_callback(value, message)
                except Exception:
                    pass
        try:
            try:
                _progress(56, "Ładowanie zakładki Z1...")
                self.tabs['campaign'] = CampaignTab(self.notebook, self)
                self.notebook.add(self.tabs['campaign'].frame, text=self.get_main_tab_label("campaign"))

            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki Kampanii: {e}")

            _progress(66, "Ładowanie zakładki Z2...")
            self.tabs['annotation'] = AnnotationTab(self.notebook, self)
            self.notebook.add(self.tabs['annotation'].frame, text=self.get_main_tab_label("annotation"))
            
            try:
                _progress(76, "Ładowanie zakładki Z3...")
                self.tabs['characters'] = CharacterAnnotationTab(self.notebook, self)
                self.notebook.add(
                    self.tabs['characters'].frame,
                    text=self.get_main_tab_label("characters")
                )
            except Exception as e:

                logger.error(f"Nie udało się załadować zakładki ZNAKI: {e}")

            
            try:
                _progress(84, "Ładowanie zakładki Z4...")
                self.tabs['training'] = TrainingTab(self.notebook, self)
                self.notebook.add(self.tabs['training'].frame, text=self.get_main_tab_label("training"))
            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki TRENING: {e}")

            if HelpTab:
                _progress(89, "Ładowanie zakładki Z5...")
                self.tabs['help'] = HelpTab(self.notebook, self)
                self.notebook.add(self.tabs['help'].frame, text=self.get_main_tab_label("help"))

            self.notebook.select(0)
        except Exception as e:
            logger.error(f"Krytyczny błąd budowania zakładek GUI: {e}")
    
    def _create_menu(self):
        palette = self.palette

        self._close_menu_dropdown()

        try:
            self.root.config(menu="")
        except Exception:
            pass

        if self.menu_bar_frame is not None:
            try:
                self.menu_bar_frame.destroy()
            except Exception:
                pass

        self.menu_bar_frame = tk.Frame(
            self.root,
            bg=palette["panel"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette["border"]
        )
        pack_kwargs = {"side": tk.TOP, "fill": tk.X}
        if getattr(self, "notebook", None) is not None:
            pack_kwargs["before"] = self.notebook
        self.menu_bar_frame.pack(**pack_kwargs)
        try:
            self.menu_bar_frame.lift()
        except Exception:
            pass

        left = tk.Frame(self.menu_bar_frame, bg=palette["panel"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=1)

        def make_menu_button(label: str, items_factory, min_width: int = 220):
            shell = tk.Frame(left, bg=palette["panel"], bd=0, highlightthickness=0)
            shell.pack(side=tk.LEFT, padx=(0, 2), pady=0)

            btn = tk.Button(
                shell,
                text=label,
                bg=palette["panel"],
                fg=palette["fg"],
                activebackground=palette["panel"],
                activeforeground=palette["fg"],
                relief=tk.FLAT,
                bd=0,
                padx=8,
                pady=2,
                font=("Segoe UI", 9, "normal"),
                highlightthickness=0,
                command=lambda: self._toggle_menu_dropdown(btn, items_factory(), min_width=min_width)
            )
            btn.pack(side=tk.TOP, fill=tk.X)

            underline = tk.Frame(
                shell,
                bg=palette["panel"],
                height=1,
                bd=0,
                highlightthickness=0
            )
            underline.pack(side=tk.TOP, fill=tk.X, padx=3)

            def _set_hover_line(active: bool):
                try:
                    underline.configure(bg=(palette["accent"] if active else palette["panel"]))
                except Exception:
                    pass

            def _sync_hover_on_enter(_event=None):
                _set_hover_line(True)

            def _sync_hover_on_leave(_event=None):
                _set_hover_line(False)

            for widget in (shell, btn):
                try:
                    widget.bind("<Enter>", _sync_hover_on_enter, add="+")
                    widget.bind("<Leave>", _sync_hover_on_leave, add="+")
                except Exception:
                    pass

            return btn

        make_menu_button(
            "Plik",
            lambda: [
                {"kind": "command", "label": "Wyjdź z projektu / trybu kampanii", "command": self._exit_campaign_mode_anytime},
                {"kind": "separator"},
                {"kind": "command", "label": "Wyjście", "command": self._on_closing},
            ],
            min_width=260
        )

        make_menu_button(
            "Konfiguracja",
            lambda: [
                {
                    "kind": "radio",
                    "label": device_label,
                    "selected": (device_label == self.get_global_yolo_device_choice()),
                    "command": (
                        lambda value=device_label: self.set_global_yolo_device_choice(value)
                    ),
                }
                for device_label in self.get_available_yolo_devices()
            ],
            min_width=320
        )

        make_menu_button(
            "Styl",
            lambda: [
                {
                    "kind": "radio",
                    "label": theme_data["label"],
                    "selected": (theme_key == self.current_theme_key),
                    "command": (lambda value=theme_key: self.set_theme(value)),
                }
                for theme_key, theme_data in self.themes.items()
            ],
            min_width=240
        )

        make_menu_button(
            "Pomoc",
            lambda: [
                {"kind": "command", "label": f"Wersja: {CONFIG.VERSION}", "command": self.show_about_dialog},
                {"kind": "command", "label": f"Autor: {APP_AUTHOR}", "command": self.show_about_dialog},
                {"kind": "separator"},
                {"kind": "command", "label": "O programie", "command": self.show_about_dialog},
            ],
            min_width=220
        )

        self.menu_theme_badge = tk.Label(
            self.menu_bar_frame,
            text=self._get_menu_badge_text(),
            bg=palette["panel"],
            fg=palette["muted"],
            font=("Segoe UI", 8, "normal"),
            padx=8,
            pady=3
        )
        self.menu_theme_badge.pack(side=tk.RIGHT)

    def _get_menu_badge_text(self) -> str:
        try:
            from ..campaign_manager import CAMPAIGN
            active_project = (CAMPAIGN.get_active_project_name() or "").strip()
        except Exception:
            active_project = ""

        if active_project:
            return f"Projekt: {active_project}"
        return "Projekt: tryb swobodny"

    def _refresh_menu_badge(self):
        badge = getattr(self, "menu_theme_badge", None)
        if badge is None:
            return

        try:
            badge.configure(text=self._get_menu_badge_text())
        except Exception:
            pass

    def _exit_campaign_mode_anytime(self):
        try:
            from ..campaign_manager import CAMPAIGN
            active_project = (CAMPAIGN.get_active_project_name() or "").strip()
        except Exception:
            active_project = ""

        if not active_project:
            self.themed_info(
                "Tryb swobodny",
                "Nie ma aktywnego projektu. Aplikacja działa już w trybie swobodnym.",
                parent=self.root,
                tone="info",
            )
            return

        campaign_tab = self.tabs.get("campaign")
        if campaign_tab is not None and hasattr(campaign_tab, "_exit_project_mode"):
            try:
                campaign_tab._exit_project_mode()
                return
            except Exception as e:
                logger.error(f"Nie udało się wyjść z projektu przez menu główne: {e}")

        self.themed_info(
            "Wyjście z projektu",
            "Nie udało się uruchomić wyjścia z projektu z poziomu menu. Spróbuj użyć przycisku „Wyjdź z projektu” w wizardzie.",
            parent=self.root,
            tone="warning",
        )

    def _widget_contains_point(self, widget, x_root: int, y_root: int) -> bool:
        if widget is None:
            return False

        try:
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            return wx <= x_root < (wx + widget.winfo_width()) and wy <= y_root < (wy + widget.winfo_height())
        except Exception:
            return False

    def _bind_help_panel_shortcuts(self):
        modifier_bindings = (
            ("<KeyPress-Control_L>", lambda _e: self._set_help_scroll_modifier_state("ctrl", True)),
            ("<KeyPress-Control_R>", lambda _e: self._set_help_scroll_modifier_state("ctrl", True)),
            ("<KeyRelease-Control_L>", lambda _e: self._set_help_scroll_modifier_state("ctrl", False)),
            ("<KeyRelease-Control_R>", lambda _e: self._set_help_scroll_modifier_state("ctrl", False)),
            ("<KeyPress-Alt_L>", lambda _e: self._set_help_scroll_modifier_state("alt", True)),
            ("<KeyPress-Alt_R>", lambda _e: self._set_help_scroll_modifier_state("alt", True)),
            ("<KeyRelease-Alt_L>", lambda _e: self._set_help_scroll_modifier_state("alt", False)),
            ("<KeyRelease-Alt_R>", lambda _e: self._set_help_scroll_modifier_state("alt", False)),
        )
        for sequence, handler in modifier_bindings:
            try:
                self.root.bind_all(sequence, handler, add="+")
            except Exception:
                pass

        try:
            self.root.bind("<FocusOut>", self._reset_help_scroll_modifier_state, add="+")
        except Exception:
            pass

        try:
            self.root.bind_all("<ButtonPress-1>", self._dismiss_forced_help_overlay, add="+")
        except Exception:
            pass

        try:
            self.root.bind_all("<Escape>", self._dismiss_forced_help_overlay, add="+")
        except Exception:
            pass

    def _set_help_scroll_modifier_state(self, modifier: str, pressed: bool):
        if modifier == "ctrl":
            self._help_scroll_ctrl_down = bool(pressed)
        elif modifier == "alt":
            self._help_scroll_alt_down = bool(pressed)
        self._apply_help_panel_visual_state()

    def _reset_help_scroll_modifier_state(self, event=None):
        self._help_scroll_ctrl_down = False
        self._help_scroll_alt_down = False
        self._apply_help_panel_visual_state()

    def _dismiss_forced_help_overlay(self, event=None):
        if bool(getattr(self, "_help_overlay_forced_visible", False)):
            self.hide_context_help_overlay()
            return "break"

    def _on_help_overlay_primary_click(self, event=None):
        if not bool(getattr(self, "_help_overlay_forced_visible", False)):
            return None
        self.hide_context_help_overlay()
        return "break"

    def show_context_help_overlay(self, message: str, icon: str = "help"):
        formatted_message = self._format_help_panel_message(message, icon=icon)
        self._status_full_text = formatted_message
        self._help_overlay_forced_text = formatted_message
        self._help_overlay_forced_visible = True
        self._apply_help_panel_visual_state()
        try:
            self.help_overlay_frame.grab_set()
        except Exception:
            pass

    def hide_context_help_overlay(self):
        if not bool(getattr(self, "_help_overlay_forced_visible", False)):
            return

        self._help_overlay_forced_visible = False
        self._help_overlay_forced_text = ""
        try:
            current_grab = self.root.grab_current()
        except Exception:
            current_grab = None

        try:
            if current_grab is self.help_overlay_frame:
                self.help_overlay_frame.grab_release()
        except Exception:
            pass
        self._apply_help_panel_visual_state()

    @staticmethod
    def _get_help_scroll_modifiers_from_event(event=None):
        if event is None or not hasattr(event, "state"):
            return False, False, False

        state = int(getattr(event, "state", 0) or 0)
        ctrl_mask = 0x0004
        alt_masks = (0x0008, 0x0080)
        ctrl_down = bool(state & ctrl_mask)
        alt_down = any(state & mask for mask in alt_masks)
        return ctrl_down, alt_down, True

    def is_help_scroll_override_active(self, event=None) -> bool:
        event_ctrl_down, event_alt_down, has_event_state = self._get_help_scroll_modifiers_from_event(event)
        tracked_ctrl_down = bool(getattr(self, "_help_scroll_ctrl_down", False))
        tracked_alt_down = bool(getattr(self, "_help_scroll_alt_down", False))

        if has_event_state:
            # Gdy event mówi, że oba modyfikatory są puszczone, natychmiast oddaj kontrolę panelom.
            if not event_ctrl_down and not event_alt_down:
                self._reset_help_scroll_modifier_state()
                return False

            # Ctrl z eventu jest zwykle wiarygodny; Alt bywa mniej stabilny przy kółku myszy,
            # więc dopuszczamy fallback do zapamiętanego stanu klawisza.
            effective_ctrl_down = bool(event_ctrl_down)
            effective_alt_down = bool(event_alt_down or tracked_alt_down)

            self._help_scroll_ctrl_down = bool(event_ctrl_down or tracked_ctrl_down)
            self._help_scroll_alt_down = bool(event_alt_down or tracked_alt_down)
            return bool(effective_ctrl_down and effective_alt_down)

        return bool(tracked_ctrl_down and tracked_alt_down)

    def _format_help_panel_message(self, message: str, icon: str | None = None) -> str:
        base_prefix = str(getattr(self, "_help_panel_message_prefix", "HELP:")).strip()
        clean_message = str(message or "").strip()
        default_message = str(getattr(self, "default_status_message", "") or "").strip()

        if not clean_message:
            clean_message = default_message

        if clean_message.startswith(base_prefix):
            return clean_message

        return f"{base_prefix} {clean_message}".strip()

    def _should_show_help_context_ppm_hint(self) -> bool:
        try:
            hover_widget = getattr(HELP, "_hover_widget", None)
            if hover_widget is None:
                return False

            current_cursor = ""
            try:
                current_cursor = str(hover_widget.cget("cursor") or "").strip().lower()
            except Exception:
                current_cursor = str(getattr(hover_widget, "_help_context_cursor", "") or "").strip().lower()

            if current_cursor not in ("question_arrow", "help"):
                return False

            try:
                if HELP._widget_has_explicit_right_click(hover_widget):
                    return False
            except Exception:
                pass

            return True
        except Exception:
            return False

    def _get_help_strip_available_width(self) -> int:
        widget = getattr(self, "status_text", None)
        if widget is None:
            return 320

        try:
            self.root.update_idletasks()
        except Exception:
            pass

        try:
            width = int(widget.winfo_width())
        except Exception:
            width = 0

        return max(180, width - 24)

    def _measure_help_text_width(self, text: str) -> int:
        widget = getattr(self, "status_text", None)
        if widget is None:
            return len(str(text or "")) * 7

        try:
            font_obj = tkfont.Font(font=widget.cget("font"))
        except Exception:
            font_obj = tkfont.Font(self.root, family="Segoe UI", size=10)

        return int(font_obj.measure(str(text or "")))

    def _build_help_strip_text(self, text: str) -> str:
        full_text = str(text or "").replace("\r", " ").replace("\n", " ").strip()
        if not full_text:
            return ""

        if self._should_show_help_context_ppm_hint():
            full_text = f"{full_text} | PPM"

        compact_prefix = str(getattr(self, "_help_panel_message_prefix", "HELP:")).strip()
        hint_suffix = "..."
        available_width = self._get_help_strip_available_width()
        full_width = self._measure_help_text_width(full_text)
        if full_width <= available_width:
            return full_text

        suffix = hint_suffix
        suffix_width = self._measure_help_text_width(suffix)
        if suffix_width >= available_width:
            return compact_prefix

        low = 0
        high = len(full_text)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            candidate = full_text[:mid].rstrip() + suffix
            if self._measure_help_text_width(candidate) <= available_width:
                best = candidate
                low = mid + 1
            else:
                high = mid - 1

        return best or compact_prefix

    def _set_help_overlay_visible(self, visible: bool):
        overlay = getattr(self, "help_overlay_frame", None)
        if overlay is None:
            return

        if visible:
            self._schedule_help_overlay_placement()
        else:
            try:
                overlay.place_forget()
            except Exception:
                pass

    def _schedule_help_overlay_placement(self):
        pending = getattr(self, "_help_overlay_place_after_id", None)
        if pending:
            try:
                self.root.after_cancel(pending)
            except Exception:
                pass
        try:
            self._help_overlay_place_after_id = self.root.after_idle(self._place_help_overlay)
        except Exception:
            self._help_overlay_place_after_id = None

    def _place_help_overlay(self):
        self._help_overlay_place_after_id = None
        overlay = getattr(self, "help_overlay_frame", None)
        message = getattr(self, "help_overlay_text", None)
        info_panel = getattr(self, "info_panel_frame", None)
        if overlay is None or message is None or info_panel is None:
            return

        if not bool(getattr(self, "_help_panel_expanded", False)):
            try:
                overlay.place_forget()
            except Exception:
                pass
            return

        try:
            self.root.update_idletasks()
        except Exception:
            pass

        root_w = max(640, int(self.root.winfo_width() or 0))
        overlay_w = min(760, max(420, int(root_w * 0.52)))
        wrap_w = max(320, overlay_w - 24)

        try:
            message.configure(width=wrap_w)
        except Exception:
            pass

        try:
            overlay.update_idletasks()
        except Exception:
            pass

        try:
            overlay_h = int(overlay.winfo_reqheight())
        except Exception:
            overlay_h = 180

        try:
            info_panel_h = int(info_panel.winfo_height() or 0)
        except Exception:
            info_panel_h = 0

        x = max(12, int((root_w - overlay_w) / 2))
        y = max(12, int(self.root.winfo_height() - info_panel_h - overlay_h - 14))

        try:
            overlay.place(x=x, y=y, width=overlay_w, height=overlay_h)
            overlay.lift()
        except Exception:
            pass

    def _render_help_panel_text(self):
        widget = getattr(self, "status_text", None)
        if widget is None:
            return

        display_text = self._build_help_strip_text(getattr(self, "_status_full_text", ""))
        try:
            current_text = widget.get("1.0", tk.END).strip()
        except Exception:
            current_text = None

        try:
            if current_text != display_text:
                widget.config(state=tk.NORMAL)
                widget.delete("1.0", tk.END)
                widget.insert(tk.END, display_text)
                widget.yview_moveto(0.0)
                widget.config(state=tk.DISABLED)
        except Exception:
            pass

    def _apply_help_panel_visual_state(self):
        widget = getattr(self, "status_text", None)
        frame = getattr(self, "info_panel_frame", None)
        overlay = getattr(self, "help_overlay_frame", None)
        overlay_title = getattr(self, "help_overlay_title_lbl", None)
        overlay_text = getattr(self, "help_overlay_text", None)
        if widget is None or frame is None or overlay is None or bool(getattr(self, "_help_panel_apply_in_progress", False)):
            return

        self._help_panel_apply_in_progress = True
        expanded = bool(
            (self._help_scroll_ctrl_down and self._help_scroll_alt_down)
            or getattr(self, "_help_overlay_forced_visible", False)
        )
        self._help_panel_expanded = expanded

        panel_bg = "#07111a" if expanded else "#050505"
        text_fg = "#f7f7f7"
        try:
            try:
                frame.configure(bg=panel_bg)
            except Exception:
                pass

            try:
                widget.configure(
                    bg=panel_bg,
                    fg=text_fg,
                    insertbackground=text_fg,
                    height=max(1, int(self._help_panel_default_height)),
                )
                widget.yview_moveto(0.0)
            except Exception:
                pass

            try:
                overlay.configure(
                    bg="#112235",
                    highlightbackground="#4aa3ff",
                    highlightcolor="#4aa3ff",
                )
            except Exception:
                pass

            try:
                if overlay_title is not None:
                    overlay_title.configure(
                        bg="#112235",
                        fg="#dcefff",
                        text="Rozwinieta pomoc  |  PPM lub ESC"
                        if bool(getattr(self, "_help_overlay_forced_visible", False))
                        else "Rozwinieta pomoc  |  CTRL + ALT lub PPM",
                    )
            except Exception:
                pass

            try:
                if overlay_text is not None:
                    overlay_body = str(
                        getattr(self, "_help_overlay_forced_text", "")
                        if bool(getattr(self, "_help_overlay_forced_visible", False))
                        else (getattr(self, "_status_full_text", "") or self.default_status_message)
                    )
                    overlay_text.configure(
                        bg="#112235",
                        fg="#f7f7f7",
                        text=overlay_body,
                    )
            except Exception:
                pass

            self._sync_global_terminal_toggle_state()
            self._apply_global_terminal_visual_state()
            self._render_help_panel_text()
            self._set_help_overlay_visible(expanded)
        finally:
            self._help_panel_apply_in_progress = False

    def _sync_global_terminal_toggle_state(self):
        btn = getattr(self, "_global_terminal_toggle_btn", None)
        if btn is None:
            return

        palette = getattr(self, "palette", {})
        base_bg = "#050505"
        border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
        fg = palette.get("guide", palette.get("warning", "#f0b44c"))

        try:
            btn.configure(
                bg=base_bg,
                fg=fg,
                activebackground=base_bg,
                activeforeground=fg,
                highlightbackground=border,
                highlightcolor=border,
                relief=tk.FLAT,
            )
        except Exception:
            pass

    def _apply_global_terminal_visual_state(self):
        palette = getattr(self, "palette", {})
        window = getattr(self, "_global_terminal_window", None)
        shell = getattr(self, "_global_terminal_shell", None)
        header = getattr(self, "_global_terminal_header", None)
        body = getattr(self, "_global_terminal_body", None)
        title_lbl = getattr(self, "_global_terminal_title_lbl", None)
        clear_btn = getattr(self, "_global_terminal_clear_btn", None)
        close_btn = getattr(self, "_global_terminal_close_btn", None)
        text_widget = getattr(self, "_global_terminal_text", None)
        scrollbar = getattr(self, "_global_terminal_scrollbar", None)
        hscrollbar = getattr(self, "_global_terminal_hscrollbar", None)

        if window is not None:
            try:
                window.configure(bg=palette.get("bg", "#1e1e1e"))
            except Exception:
                pass

        if shell is not None:
            try:
                shell.configure(
                    bg=palette.get("panel", "#252526"),
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                )
            except Exception:
                pass

        for widget in (header, body):
            if widget is None:
                continue
            try:
                widget.configure(bg=palette.get("panel", "#252526"))
            except Exception:
                pass

        if title_lbl is not None:
            try:
                title_lbl.configure(
                    bg=palette.get("panel", "#252526"),
                    fg=palette.get("fg", "#f3f3f3"),
                )
            except Exception:
                pass

        for button in (clear_btn, close_btn):
            if button is None:
                continue
            try:
                button.configure(
                    bg=palette.get("panel_alt", "#2d2d30"),
                    fg=palette.get("fg", "#f3f3f3"),
                    activebackground=palette.get("button_hover", "#37373d"),
                    activeforeground=palette.get("fg", "#f3f3f3"),
                    highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                    highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
                )
            except Exception:
                pass

        if text_widget is not None:
            self.style_text_widget(text_widget, role="console")
            self._configure_global_terminal_tags(text_widget)

        if scrollbar is not None:
            try:
                self.style_web_scrollbar(
                    scrollbar,
                    track_color=palette.get("console_bg", palette.get("panel", "#252526")),
                )
            except Exception:
                pass
        if hscrollbar is not None:
            try:
                self.style_web_scrollbar(
                    hscrollbar,
                    track_color=palette.get("console_bg", palette.get("panel", "#252526")),
                )
            except Exception:
                pass

    def _normalize_global_terminal_entry(self, entry, default_tag: str = "terminal_default"):
        text = ""
        tag = default_tag

        if isinstance(entry, dict):
            text = str(entry.get("text", "") or "")
            tag = str(entry.get("tag", default_tag) or default_tag)
        elif isinstance(entry, (tuple, list)):
            if entry:
                text = str(entry[0] or "")
            if len(entry) > 1:
                tag = str(entry[1] or default_tag)
        else:
            text = str(entry or "")

        return {"text": text, "tag": tag}

    def _refresh_global_terminal_plain_lines(self):
        entries = list(getattr(self, "_global_terminal_entries", []) or [])
        self._global_terminal_lines = [str(entry.get("text", "") or "") for entry in entries]

    def _configure_global_terminal_tags(self, text_widget):
        if text_widget is None:
            return

        palette = getattr(self, "palette", {})
        default_fg = palette.get("console_fg", palette.get("fg", "#f3f3f3"))
        muted_fg = palette.get("muted", "#b9b9b9")
        info_fg = palette.get("accent", "#4aa3ff")
        success_fg = palette.get("success", "#2ecc71")
        warning_fg = palette.get("guide", palette.get("warning", "#f0b44c"))
        error_fg = palette.get("error", "#ff6b6b")
        header_fg = palette.get("accent_selected", info_fg)
        border_fg = palette.get("panel_border", palette.get("border", "#3c3c3c"))

        try:
            text_widget.tag_configure("terminal_default", foreground=default_fg)
            text_widget.tag_configure("terminal_muted", foreground=muted_fg)
            text_widget.tag_configure("terminal_info", foreground=info_fg)
            text_widget.tag_configure("terminal_success", foreground=success_fg)
            text_widget.tag_configure("terminal_warning", foreground=warning_fg)
            text_widget.tag_configure("terminal_error", foreground=error_fg)
            text_widget.tag_configure("terminal_header", foreground=header_fg, font=("Consolas", 9, "bold"))
            text_widget.tag_configure("terminal_border", foreground=border_fg)
        except Exception:
            pass

    def _insert_global_terminal_entry(self, text_widget, entry):
        if text_widget is None:
            return

        normalized = self._normalize_global_terminal_entry(entry)
        text = str(normalized.get("text", "") or "")
        tag = str(normalized.get("tag", "terminal_default") or "terminal_default")

        try:
            text_widget.insert(tk.END, text + "\n", (tag,))
        except Exception:
            try:
                text_widget.insert(tk.END, text + "\n")
            except Exception:
                pass

    def _populate_global_terminal_widget(self):
        text_widget = getattr(self, "_global_terminal_text", None)
        if text_widget is None:
            return

        try:
            text_widget.configure(state=tk.NORMAL)
            text_widget.delete("1.0", tk.END)
            self._configure_global_terminal_tags(text_widget)
            entries = list(getattr(self, "_global_terminal_entries", []) or [])
            if not entries and getattr(self, "_global_terminal_lines", None):
                entries = [self._normalize_global_terminal_entry(line) for line in self._global_terminal_lines]
                self._global_terminal_entries = entries
            for entry in entries:
                self._insert_global_terminal_entry(text_widget, entry)
            text_widget.see(tk.END)
        except Exception:
            pass
        finally:
            try:
                text_widget.configure(state=tk.DISABLED)
            except Exception:
                pass

    def _position_global_terminal_window(self, force: bool = False):
        window = getattr(self, "_global_terminal_window", None)
        if window is None:
            return
        if self._global_terminal_geometry_initialized and not force:
            return

        try:
            self.root.update_idletasks()
            root_x = int(self.root.winfo_rootx() or 0)
            root_y = int(self.root.winfo_rooty() or 0)
            root_w = max(900, int(self.root.winfo_width() or self.root.winfo_reqwidth() or 900))
            root_h = max(640, int(self.root.winfo_height() or self.root.winfo_reqheight() or 640))
        except Exception:
            root_x = 80
            root_y = 80
            root_w = 1200
            root_h = 760

        width = min(1080, max(780, int(root_w * 0.78)))
        height = min(420, max(260, int(root_h * 0.36)))
        pos_x = max(8, root_x + int((root_w - width) / 2))
        pos_y = max(8, root_y + int((root_h - height) / 2))

        try:
            window.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
            self._global_terminal_geometry_initialized = True
        except Exception:
            pass

    def _ensure_global_terminal_window(self):
        window = getattr(self, "_global_terminal_window", None)
        try:
            if window is not None and window.winfo_exists():
                return window
        except Exception:
            pass

        palette = getattr(self, "palette", {})
        window = tk.Toplevel(self.root)
        window.withdraw()
        window.title("Terminal procesu")
        try:
            window.transient(self.root)
        except Exception:
            pass
        window.configure(bg=palette.get("bg", "#1e1e1e"))
        window.protocol("WM_DELETE_WINDOW", self.hide_global_terminal)
        try:
            window.bind("<Escape>", lambda _event: self.hide_global_terminal(), add="+")
        except Exception:
            pass

        shell = tk.Frame(
            window,
            bg=palette.get("panel", "#252526"),
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette.get("border", "#3c3c3c")),
            highlightcolor=palette.get("panel_border", palette.get("border", "#3c3c3c")),
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        header = tk.Frame(shell, bg=palette.get("panel", "#252526"), bd=0, highlightthickness=0)
        header.pack(fill=tk.X, padx=12, pady=(12, 6))

        title_lbl = tk.Label(
            header,
            text="Terminal procesu",
            anchor="w",
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
            bg=palette.get("panel", "#252526"),
            fg=palette.get("fg", "#f3f3f3"),
            bd=0,
            highlightthickness=0,
        )
        title_lbl.pack(side=tk.LEFT)

        close_btn = tk.Button(
            header,
            text="Zwin",
            command=self.hide_global_terminal,
            cursor="hand2",
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            padx=10,
            pady=3,
            font=("Segoe UI", 9),
        )
        close_btn.pack(side=tk.RIGHT)

        clear_btn = tk.Button(
            header,
            text="Wyczysc",
            command=self.clear_global_terminal,
            cursor="hand2",
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            padx=10,
            pady=3,
            font=("Segoe UI", 9),
        )
        clear_btn.pack(side=tk.RIGHT, padx=(0, 6))

        body = tk.Frame(shell, bg=palette.get("panel", "#252526"), bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        text_widget = tk.Text(
            body,
            wrap=tk.NONE,
            font=("Consolas", 9),
            bd=0,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        hscrollbar = WebSlimScrollbar(
            body,
            orient=tk.HORIZONTAL,
            command=text_widget.xview,
            auto_hide=False,
        )
        hscrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = WebSlimScrollbar(
            body,
            orient=tk.VERTICAL,
            command=text_widget.yview,
            auto_hide=False,
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.configure(yscrollcommand=scrollbar.set, xscrollcommand=hscrollbar.set)
        text_widget.web_vbar = scrollbar
        text_widget.web_hbar = hscrollbar

        self._global_terminal_window = window
        self._global_terminal_shell = shell
        self._global_terminal_header = header
        self._global_terminal_title_lbl = title_lbl
        self._global_terminal_clear_btn = clear_btn
        self._global_terminal_close_btn = close_btn
        self._global_terminal_body = body
        self._global_terminal_text = text_widget
        self._global_terminal_scrollbar = scrollbar
        self._global_terminal_hscrollbar = hscrollbar

        self._apply_global_terminal_visual_state()
        self._populate_global_terminal_widget()
        self._position_global_terminal_window(force=True)
        return window

    def is_global_terminal_visible(self) -> bool:
        window = getattr(self, "_global_terminal_window", None)
        if window is None:
            return False
        try:
            return bool(window.winfo_exists()) and str(window.state()) != "withdrawn"
        except Exception:
            return False

    def show_global_terminal(self):
        window = self._ensure_global_terminal_window()
        self._position_global_terminal_window()
        try:
            window.deiconify()
            window.lift()
            window.focus_force()
        except Exception:
            pass
        self._global_terminal_visible = True
        self._sync_global_terminal_toggle_state()

    def hide_global_terminal(self):
        window = getattr(self, "_global_terminal_window", None)
        if window is not None:
            try:
                window.withdraw()
            except Exception:
                pass
        self._global_terminal_visible = False
        self._sync_global_terminal_toggle_state()

    def toggle_global_terminal(self):
        if self.is_global_terminal_visible():
            self.hide_global_terminal()
        else:
            self.show_global_terminal()

    def clear_global_terminal(self):
        self._global_terminal_entries = []
        self._global_terminal_lines = []
        self._populate_global_terminal_widget()

    def append_global_terminal_entries(self, entries):
        normalized_entries = []
        for entry in list(entries or []):
            normalized = self._normalize_global_terminal_entry(entry)
            text = str(normalized.get("text", "") or "")
            if text == "":
                normalized_entries.append(normalized)
            elif text.strip():
                normalized_entries.append(normalized)

        if not normalized_entries:
            return

        current_entries = list(getattr(self, "_global_terminal_entries", []) or [])
        current_entries.extend(normalized_entries)
        overflow = len(current_entries) - int(self._global_terminal_max_lines)
        if overflow > 0:
            current_entries = current_entries[overflow:]
        self._global_terminal_entries = current_entries
        self._refresh_global_terminal_plain_lines()

        def update():
            text_widget = getattr(self, "_global_terminal_text", None)
            if text_widget is None:
                return

            try:
                text_widget.configure(state=tk.NORMAL)
                self._configure_global_terminal_tags(text_widget)
                if overflow > 0:
                    text_widget.delete("1.0", tk.END)
                    for entry in self._global_terminal_entries:
                        self._insert_global_terminal_entry(text_widget, entry)
                else:
                    for entry in normalized_entries:
                        self._insert_global_terminal_entry(text_widget, entry)
                text_widget.see(tk.END)
            except Exception:
                pass
            finally:
                try:
                    text_widget.configure(state=tk.DISABLED)
                except Exception:
                    pass

        try:
            self.root.after(0, update)
        except Exception:
            pass

    def append_global_terminal(self, message: str, source: str = None, tag: str = "terminal_default"):
        text = "" if message is None else str(message)
        if not text:
            return

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        prefix = f"[{str(source).strip()}] " if str(source or "").strip() else ""
        new_entries = []
        for line in normalized.split("\n"):
            if line == "":
                continue
            new_entries.append({"text": f"{prefix}{line}", "tag": tag})

        self.append_global_terminal_entries(new_entries)

    def _on_help_panel_text_configure(self, event=None):
        if bool(getattr(self, "_help_panel_apply_in_progress", False)):
            return
        self._render_help_panel_text()
        if bool(getattr(self, "_help_panel_expanded", False)):
            self._schedule_help_overlay_placement()

    def handle_help_panel_scroll_override(self, event=None):
        if not self.is_help_scroll_override_active(event):
            return None
        return "break"

    def _close_menu_dropdown(self, event=None):
        bind_id = getattr(self, "_menu_outside_click_bind_id", None)
        if bind_id:
            try:
                self.root.unbind("<ButtonPress-1>", bind_id)
            except Exception:
                pass
        self._menu_outside_click_bind_id = None

        bind_id = getattr(self, "_menu_escape_bind_id", None)
        if bind_id:
            try:
                self.root.unbind("<Escape>", bind_id)
            except Exception:
                pass
        self._menu_escape_bind_id = None

        popup = getattr(self, "_menu_dropdown", None)
        self._menu_dropdown = None
        self._menu_dropdown_owner = None

        if popup is not None:
            try:
                if popup.winfo_exists():
                    popup.destroy()
            except Exception:
                pass

    def _toggle_menu_dropdown(self, owner_widget, items, min_width: int = 220):
        current_owner = getattr(self, "_menu_dropdown_owner", None)
        current_popup = getattr(self, "_menu_dropdown", None)
        if current_popup is not None and current_owner is owner_widget:
            self._close_menu_dropdown()
            return

        self._open_menu_dropdown(owner_widget, items, min_width=min_width)

    def _open_menu_dropdown(self, owner_widget, items, min_width: int = 220):
        self._close_menu_dropdown()

        palette = self.palette
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.configure(bg=palette["bg"])

        shell = tk.Frame(
            popup,
            bg=palette["panel"],
            bd=0,
            highlightthickness=1,
            highlightbackground=palette.get("panel_border", palette["border"]),
            highlightcolor=palette.get("panel_border", palette["border"])
        )
        shell.pack(fill=tk.BOTH, expand=True)

        body = tk.Frame(shell, bg=palette["panel"])
        body.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        def close_then_call(command):
            self._close_menu_dropdown()
            if callable(command):
                self.root.after(0, command)

        def make_item_row(item):
            kind = item.get("kind", "command")
            if kind == "separator":
                sep = tk.Frame(body, bg=palette.get("panel_border", palette["border"]), height=1, bd=0, highlightthickness=0)
                sep.pack(fill=tk.X, padx=6, pady=4)
                return

            is_selected = bool(item.get("selected"))
            prefix = "✓  " if is_selected else "   "
            text = f"{prefix}{item.get('label', '').strip()}"

            row = tk.Button(
                body,
                text=text,
                anchor="w",
                justify=tk.LEFT,
                bg=palette["panel"],
                fg=(palette["accent"] if is_selected else palette["fg"]),
                activebackground=palette.get("surface_info", palette.get("button_hover", palette["panel_alt"])),
                activeforeground=palette["fg"],
                relief=tk.FLAT,
                bd=0,
                highlightthickness=0,
                padx=12,
                pady=7,
                font=("Segoe UI", 10, "bold" if is_selected else "normal"),
                command=lambda cmd=item.get("command"): close_then_call(cmd)
            )
            row.pack(fill=tk.X)

        for item in items:
            make_item_row(item)

        popup.update_idletasks()

        popup_width = max(min_width, shell.winfo_reqwidth())
        popup_height = shell.winfo_reqheight()

        try:
            self.root.update_idletasks()
            self.menu_bar_frame.update_idletasks()
            root_y = self.root.winfo_rooty()
            menu_bar_bottom = root_y + self.menu_bar_frame.winfo_y() + self.menu_bar_frame.winfo_height()
            x = owner_widget.winfo_rootx()
        except Exception:
            x = owner_widget.winfo_rootx()
            menu_bar_bottom = owner_widget.winfo_rooty() + owner_widget.winfo_height()

        y = menu_bar_bottom + 6

        screen_w = popup.winfo_screenwidth()
        screen_h = popup.winfo_screenheight()
        x = max(8, min(x, screen_w - popup_width - 8))
        y = max(8, min(y, screen_h - popup_height - 8))

        popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")
        popup.lift()

        self._menu_dropdown = popup
        self._menu_dropdown_owner = owner_widget

        def handle_outside_click(event):
            if self._widget_contains_point(popup, event.x_root, event.y_root):
                return
            if self._widget_contains_point(owner_widget, event.x_root, event.y_root):
                return
            self._close_menu_dropdown()

        try:
            self._menu_outside_click_bind_id = self.root.bind("<ButtonPress-1>", handle_outside_click, add="+")
        except Exception:
            self._menu_outside_click_bind_id = None

        try:
            self._menu_escape_bind_id = self.root.bind("<Escape>", self._close_menu_dropdown, add="+")
        except Exception:
            self._menu_escape_bind_id = None
    
    def update_status(self, message: str, icon: str = "info"):
        """Aktualizuje główny panel wskazówek (zapobiega migotaniu)."""
        new_text = self._format_help_panel_message(message, icon=icon)
        try:
            previous_text = str(getattr(self, "_status_full_text", "") or "")
            self._status_full_text = new_text
            if previous_text != new_text:
                self.root.update_idletasks()
        except Exception:
            pass
        try:
            self._apply_help_panel_visual_state()
        except Exception:
            pass
    
    def set_processing(self, processing: bool):
        with self._processing_state_lock:
            self._manual_processing = bool(processing)
        self._refresh_processing_state()

    def _refresh_processing_state(self):
        with self._processing_state_lock:
            processing = bool(self._manual_processing or self._exclusive_operation)
            self.is_processing = processing

        def update():
            try:
                self.root.config(cursor="wait" if processing else "")
            except Exception:
                pass

        try:
            self.root.after(0, update)
        except Exception:
            try:
                update()
            except Exception:
                pass

    def get_active_exclusive_operation_label(self) -> str:
        with self._processing_state_lock:
            active = dict(self._exclusive_operation or {})
        return str(active.get("label") or "").strip()

    def try_begin_exclusive_operation(self, owner: str, label: str) -> tuple[bool, str]:
        owner_key = str(owner or "").strip()
        label_text = str(label or "").strip() or owner_key or "operacja"
        denial_message = ""
        started = False

        with self._processing_state_lock:
            active = dict(self._exclusive_operation or {})
            active_owner = str(active.get("owner") or "").strip()
            active_label = str(active.get("label") or "").strip()

            if active_owner:
                denial_message = (
                    f"W aplikacji trwa juz: {active_label or 'inna operacja'}.\n\n"
                    f"Poczekaj na jej zakonczenie, zanim uruchomisz: {label_text}."
                )
            else:
                self._exclusive_operation = {"owner": owner_key, "label": label_text}
                started = not active_owner

        if denial_message:
            try:
                self.append_global_terminal(
                    f"[BUSY] Odrzucono start: {label_text}. Trwa: {active_label or 'inna operacja'}.",
                    source="APP",
                    tag="terminal_warning",
                )
            except Exception:
                pass
            self._refresh_processing_state()
            return False, denial_message

        self._refresh_processing_state()
        if started:
            try:
                self.append_global_terminal(
                    f"[LOCK] Rozpoczeto: {label_text}. Pozostale procesy sa chwilowo zablokowane.",
                    source="APP",
                    tag="terminal_info",
                )
            except Exception:
                pass
        return True, ""

    def end_exclusive_operation(self, owner: str):
        owner_key = str(owner or "").strip()
        finished_label = ""
        with self._processing_state_lock:
            active = dict(self._exclusive_operation or {})
            active_owner = str(active.get("owner") or "").strip()
            if active_owner and active_owner == owner_key:
                finished_label = str(active.get("label") or "").strip()
                self._exclusive_operation = None
        self._refresh_processing_state()
        if finished_label:
            try:
                self.append_global_terminal(
                    f"[LOCK] Zakonczono: {finished_label}. Mozesz uruchomic kolejny proces.",
                    source="APP",
                    tag="terminal_info",
                )
            except Exception:
                pass

    def set_campaign_mode(self, active: bool):
        """
        Przełącza tryb kampanii.
        Uwaga: jeśli użytkownik ręcznie wszedł w tryb swobodny, nie nadpisujemy tego automatem.
        """
        self.campaign_mode_active = bool(active)
        self.update_campaign_tab_access()

    def _get_selected_tab_key(self):
        try:
            selected_widget = str(self.notebook.select())
        except Exception:
            return None

        for key, tab in self.tabs.items():
            try:
                if str(tab.frame) == selected_widget:
                    return key
            except Exception:
                pass

        return None


    def update_campaign_tab_access(self):
        """
        Steruje dostępnością głównych zakładek.

        Zasada:
        - tryb swobodny: wszystko dostępne
        - tryb aktywnego projektu: ręcznie klikalne są tylko:
        * Wizard kampanii
        * Help
        * aktualnie OTWARTA zakładka robocza (jeśli weszliśmy tam z wizarda)
        """

        from ..campaign_manager import CAMPAIGN

        active = CAMPAIGN.get_active_project_name()
        active_step_tab_key = None

        # ręczny free mode albo brak aktywnego projektu = pełna swoboda
        if self.campaign_free_mode or not active:
            self.campaign_mode_active = False

            for key, tab in self.tabs.items():
                try:
                    self.notebook.tab(str(tab.frame), state="normal")
                except Exception:
                    pass

            self.refresh_main_tab_labels()
            self.refresh_window_title()
            return

        # aktywny projekt
        self.campaign_mode_active = True
        step_to_tab = {
            1: "campaign",
            2: "annotation",
            3: "characters",
            4: "training",
        }
        active_step_tab_key = step_to_tab.get(CAMPAIGN.get_current_step(), "campaign")

        selected_key = self._get_selected_tab_key()

        allowed = {"campaign", "help"}

        # jeżeli użytkownik jest już w zakładce roboczej, zostaw ją aktywną
        # ale nie odblokowuj innych roboczych tabów
        if selected_key in {"annotation", "characters", "training"}:
            allowed.add(selected_key)

        for key, tab in self.tabs.items():
            try:
                state = "normal" if key in allowed else "disabled"
                self.notebook.tab(str(tab.frame), state=state)
            except Exception:
                pass

        self.refresh_main_tab_labels(active_tab_key=active_step_tab_key)
        self.refresh_window_title()

    def get_tab_index(self, tab_key: str) -> int:
        if tab_key not in self.tabs:
            raise KeyError(f"Unknown tab key: {tab_key}")

        target_widget = str(self.tabs[tab_key].frame)

        for i, widget_name in enumerate(self.notebook.tabs()):
            if str(widget_name) == target_widget:
                return i

        raise KeyError(f"Tab widget not found in notebook for key: {tab_key}")


    def select_tab(self, tab_key: str):
        if tab_key not in self.tabs:
            raise KeyError(f"Unknown tab key: {tab_key}")

        if tab_key == "campaign":
            self._allow_campaign_tab_once = True
        self.notebook.select(str(self.tabs[tab_key].frame))

    def open_controlled_tab(self, tab_key: str):
        if tab_key not in self.tabs:
            raise KeyError(f"Unknown tab key: {tab_key}")

        tab_widget = str(self.tabs[tab_key].frame)

        # Na chwilę odblokuj zakładkę, aby można ją było wybrać programowo.
        self.notebook.tab(tab_widget, state="normal")
        if tab_key == "campaign":
            self._allow_campaign_tab_once = True
        self.notebook.select(tab_widget)

        # po przejściu od razu zsynchronizuj dostępność zakładek
        self.update_campaign_tab_access()

    def _guard_campaign_navigation(self, event=None):
        try:
            from ..campaign_manager import CAMPAIGN
        except Exception:
            return

        if self.campaign_free_mode or not CAMPAIGN.get_active_project_name():
            return

        if bool(getattr(self, "_campaign_nav_guard_in_progress", False)):
            return

        selected_key = self._get_selected_tab_key()
        if selected_key != "campaign":
            return

        if bool(getattr(self, "_allow_campaign_tab_once", False)):
            self._allow_campaign_tab_once = False
            return

        fallback_key = str(getattr(self, "_last_allowed_main_tab_key", "") or "").strip()
        if fallback_key not in {"annotation", "characters", "training"}:
            step_to_tab = {
                2: "annotation",
                3: "characters",
                4: "training",
            }
            try:
                fallback_key = step_to_tab.get(int(CAMPAIGN.get_current_step() or 0), "annotation")
            except Exception:
                fallback_key = "annotation"

        if fallback_key not in self.tabs or fallback_key == "campaign":
            return

        def _restore_previous_tab():
            self._campaign_nav_guard_in_progress = True
            try:
                self.notebook.select(str(self.tabs[fallback_key].frame))
                self.update_status(
                    "Do wizarda kampanii wracaj przez dedykowany przycisk w module, a nie przez klikniecie zakladki Z1.",
                    "warning",
                )
            except Exception:
                pass
            finally:
                self._campaign_nav_guard_in_progress = False

        try:
            self.notebook.after_idle(_restore_previous_tab)
        except Exception:
            _restore_previous_tab()

    def _on_main_notebook_tab_changed(self, event=None):
        self._guard_campaign_navigation(event)
        selected_key = self._get_selected_tab_key()
        if selected_key == "annotation":
            try:
                from ..campaign_manager import CAMPAIGN
                if not self.campaign_free_mode and CAMPAIGN.get_active_project_name():
                    annotation_tab = getattr(self, "tabs", {}).get("annotation")
                    ensure_context = (
                        getattr(annotation_tab, "ensure_campaign_context_ready_for_active_project", None)
                        if annotation_tab is not None
                        else None
                    )
                    if callable(ensure_context):
                        self.root.after_idle(ensure_context)
            except Exception:
                pass
        if selected_key in {"annotation", "characters", "training"}:
            self._last_allowed_main_tab_key = selected_key
        self._save_active_main_tab_preference()


    
    def _on_closing(self):
        if getattr(self, "_closing_in_progress", False):
            return

        self._closing_in_progress = True

        try:
            busy = bool(getattr(self, "is_processing", False))
            for tab in getattr(self, "tabs", {}).values():
                try:
                    if getattr(tab, "is_processing", False):
                        busy = True
                        break
                    trainer = getattr(tab, "trainer", None)
                    if trainer is not None and getattr(trainer, "is_training", False):
                        busy = True
                        break
                except Exception:
                    pass

            if busy:
                if not messagebox.askokcancel("Zamknij", "Przetwarzanie w toku. Na pewno zamknąć?"):
                    self._closing_in_progress = False
                    return

            try:
                self._save_active_main_tab_preference()
            except Exception:
                pass

            for tab_name, tab in getattr(self, "tabs", {}).items():
                try:
                    flush_session = getattr(tab, "flush_free_mode_session_state", None)
                    if callable(flush_session):
                        flush_session()
                except Exception as e:
                    logger.debug(f"Nie udalo sie zapisac stanu zakladki {tab_name}: {e}")

                try:
                    if hasattr(tab, "is_processing"):
                        tab.is_processing = False
                except Exception:
                    pass

                try:
                    stop_event = getattr(tab, "fast_test_stop", None)
                    if stop_event is not None:
                        stop_event.set()
                except Exception:
                    pass

                try:
                    trainer = getattr(tab, "trainer", None)
                    if trainer is not None and hasattr(trainer, "stop_training"):
                        trainer.stop_training()
                except Exception:
                    pass

                try:
                    annotator = getattr(tab, "annotator", None)
                    if annotator:
                        annotator.stop()
                        annotator.unload_models()
                except Exception:
                    pass

            for widget in list(self.root.winfo_children()):
                try:
                    if isinstance(widget, tk.Toplevel):
                        try:
                            widget.grab_release()
                        except Exception:
                            pass
                        widget.destroy()
                except Exception:
                    pass

            try:
                self.root.grab_release()
            except Exception:
                pass

            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception:
                    pass

            try:
                self.root.update_idletasks()
            except Exception:
                pass

            try:
                self.root.quit()
            except Exception:
                pass

            try:
                self.root.destroy()
            except Exception:
                pass
        finally:
            try:
                if self.root.winfo_exists():
                    self._closing_in_progress = False
            except Exception:
                self._closing_in_progress = False
