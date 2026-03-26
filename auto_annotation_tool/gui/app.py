#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Główna aplikacja GUI.
"""
print("DEBUG_LOADED_APP_PY:", __file__)

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
from datetime import datetime

from ..config import CONFIG, logger, TK_AVAILABLE, SESSION
from ..icons import IconManager

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
            "accent": "#0e639c",
            "accent_hover": "#1177bb",
            "accent_selected": "#094771",
            "button_hover": "#37373d",
            "tab_disabled_bg": "#1e1e1e",
            "tab_disabled_fg": "#6f6f6f",
            "success": "#4ec9b0",
            "warning": "#d7ba7d",
            "error": "#f48771",
            "surface_info": "#2a3947",
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
            "accent": "#3a7bd5",
            "accent_hover": "#4f8de3",
            "accent_selected": "#2d5ea3",
            "button_hover": "#3a3c43",
            "tab_disabled_bg": "#202124",
            "tab_disabled_fg": "#76797f",
            "success": "#62d2a2",
            "warning": "#e3c27a",
            "error": "#ff8e72",
            "surface_info": "#253445",
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
        self.root.title(f"{CONFIG.APP_NAME} v{CONFIG.VERSION}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self.icon_manager = IconManager
        self.icon_manager.test_emoji_support(root)
        
        self.themes = THEME_DEFINITIONS
        self.current_theme_key = self._load_theme_preference()
        self.current_theme_name = self.themes[self.current_theme_key]["label"]
        self.palette = dict(self.themes[self.current_theme_key]["palette"])
        self.theme_var = tk.StringVar(master=root, value=self.current_theme_key)
        self.menu_bar_frame = None
        self.menu_theme_badge = None
        self._menu_dropdown = None
        self._menu_dropdown_owner = None
        self._menu_outside_click_bind_id = None
        self._menu_escape_bind_id = None
        self.tabs = {}
        self._closing_in_progress = False

        self.style = ttk.Style()
        self._setup_style(self.current_theme_key)
        self.is_processing = False
        # Lokalna flaga aktywnego trybu kampanii.
        self.campaign_mode_active = False
        # Ręczne wyjście z projektu ma pierwszeństwo nad automatycznym trybem kampanii.
        self.campaign_free_mode = False
    
        self._create_menu()
        self._install_themed_dialog_hooks()

        self.default_status_message = HELP.default_message
        
        # Panel pomocy musi powstać przed notebookiem, aby poprawnie zakotwiczyć go na dole okna.
        self.info_panel_frame = tk.Frame(root, bg="#050505", bd=0, highlightthickness=0)
        self.info_panel_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_text = tk.Text(
            self.info_panel_frame, height=2, wrap=tk.WORD, 
            bg="#050505",
            bd=0,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            fg="#f7f7f7",
            insertbackground="#f7f7f7",
            highlightthickness=0
        )
        self.status_text.pack(fill=tk.X, padx=10, pady=6)
        self.status_text.insert(tk.END, self.default_status_message)
        self.status_text.config(state=tk.DISABLED)
        
        # Podpinamy globalny menedżer pomocy
        HELP.status_updater = self.update_status
        
        # 2. Tworzenie Notatnika z zakładkami
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        
        self._create_tabs()
        self._apply_theme_to_tabs()

        # główna blokada działa przez disabled tabs
        self.notebook.bind("<<NotebookTabChanged>>", self._guard_campaign_navigation)

        # początkowa synchronizacja stanów zakładek
        self.update_campaign_tab_access()

        # Po starcie pokaż informację o aktywnym projekcie, jeśli aplikacja wznawia tryb kampanii.
        try:
            from ..campaign_manager import CAMPAIGN
            active_proj = CAMPAIGN.get_active_project_name()
            if active_proj:
                self.update_status(
                    f"Aktywny projekt: {active_proj}. Aplikacja działa w trybie kampanii — aby wrócić do trybu swobodnego, użyj „Wyjdź z projektu” w Wizardzie.",
                    "warning"
                )
        except Exception:
            pass

        logger.info("GUI zainicjalizowane pomyślnie")

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

    def _is_guided_style(self, style_name: str) -> bool:
        return style_name in {
            "GuidedNeutral.TButton",
            "GuidedAccent.TButton",
            "PulseNeutral.TButton",
            "PulseAccent.TButton",
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
        pulse_style = "PulseAccent.TButton" if is_accent else "PulseNeutral.TButton"
        return style_name, emphasis_style, pulse_style

    def clear_button_pulse(self, button):
        after_id = getattr(button, "_guided_pulse_after_id", None)
        if after_id:
            try:
                button.after_cancel(after_id)
            except Exception:
                pass
        button._guided_pulse_after_id = None

    def set_button_emphasis(self, button, enabled: bool, base_style: str = None):
        if button is None:
            return

        try:
            self.clear_button_pulse(button)
            base_name, emphasis_style, _pulse_style = self._get_guided_styles_for_button(button, base_style)
            button.configure(style=(emphasis_style if enabled else base_name))
        except Exception as e:
            logger.debug(f"Nie udało się ustawić podświetlenia przycisku: {e}")

    def pulse_button(self, button, pulses: int = 8, interval_ms: int = 260, keep_emphasis: bool = True, base_style: str = None):
        if button is None:
            return

        try:
            self.clear_button_pulse(button)
            base_name, emphasis_style, pulse_style = self._get_guided_styles_for_button(button, base_style)
            final_style = emphasis_style if keep_emphasis else base_name
            button.configure(style=final_style)

            def tick(step=0):
                try:
                    if not button.winfo_exists():
                        return

                    button.configure(style=(pulse_style if step % 2 == 0 else final_style))

                    if step < (pulses * 2 - 1):
                        after_id = button.after(interval_ms, lambda: tick(step + 1))
                        button._guided_pulse_after_id = after_id
                    else:
                        button.configure(style=final_style)
                        button._guided_pulse_after_id = None
                except Exception as inner_e:
                    logger.debug(f"Nie udało się pulsować przycisku: {inner_e}")

            tick()
        except Exception as e:
            logger.debug(f"Nie udało się rozpocząć pulsowania przycisku: {e}")

    def clear_guidance_frame_pulse(self, frame):
        if frame is None:
            return

        after_id = getattr(frame, "_guided_frame_after_id", None)
        if after_id:
            try:
                frame.after_cancel(after_id)
            except Exception:
                pass
        frame._guided_frame_after_id = None

    def style_guidance_frame(self, frame, background: str = None, emphasized: bool = None):
        if frame is None:
            return

        palette = self.palette
        base_border = palette.get("panel_border", palette["border"])
        emphasis_border = palette.get("accent", palette["border"])
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
                highlightthickness=1,
                highlightbackground=border,
                highlightcolor=border
            )
        except Exception as e:
            logger.debug(f"Nie udało się wystylizować ramki prowadzenia: {e}")

    def set_frame_emphasis(self, frame, enabled: bool, background: str = None):
        if frame is None:
            return

        try:
            self.clear_guidance_frame_pulse(frame)
            self.style_guidance_frame(frame, background=background, emphasized=enabled)
        except Exception as e:
            logger.debug(f"Nie udało się ustawić podświetlenia ramki: {e}")

    def pulse_frame(self, frame, pulses: int = 8, interval_ms: int = 260, keep_emphasis: bool = True, background: str = None):
        if frame is None:
            return

        try:
            self.clear_guidance_frame_pulse(frame)
            palette = self.palette
            base_border = palette.get("panel_border", palette["border"])
            emphasis_border = palette.get("accent", palette["border"])
            pulse_border = palette.get("accent_hover", emphasis_border)
            final_border = emphasis_border if keep_emphasis else base_border
            bg = background or getattr(frame, "_guided_frame_bg", None) or palette.get("panel", palette["bg"])

            frame._guided_frame_bg = bg
            frame._guided_frame_emphasized = bool(keep_emphasis)
            self.style_guidance_frame(frame, background=bg, emphasized=keep_emphasis)

            def tick(step=0):
                try:
                    if not frame.winfo_exists():
                        return

                    border = pulse_border if step % 2 == 0 else final_border
                    frame.configure(
                        bg=bg,
                        bd=0,
                        relief=tk.FLAT,
                        highlightthickness=1,
                        highlightbackground=border,
                        highlightcolor=border
                    )

                    if step < (pulses * 2 - 1):
                        after_id = frame.after(interval_ms, lambda: tick(step + 1))
                        frame._guided_frame_after_id = after_id
                    else:
                        self.style_guidance_frame(frame, background=bg, emphasized=keep_emphasis)
                        frame._guided_frame_after_id = None
                except Exception as inner_e:
                    logger.debug(f"Nie udało się pulsować ramki: {inner_e}")

            tick()
        except Exception as e:
            logger.debug(f"Nie udało się rozpocząć pulsowania ramki: {e}")

    def set_theme(self, theme_key: str, persist: bool = True, announce: bool = True):
        if theme_key not in self.themes:
            return

        self._setup_style(theme_key)
        self._restyle_shell()

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
            self.info_panel_frame.configure(bg="#050505")
            self.status_text.configure(
                bg="#050505",
                fg="#f7f7f7",
                insertbackground="#f7f7f7"
            )
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

    def style_native_scrollbar(self, scrollbar, background: str = None, troughcolor: str = None, bordercolor: str = None):
        if scrollbar is None:
            return

        palette = getattr(self, "palette", {})
        bg = background or palette.get("panel_alt", "#2d2d30")
        trough = troughcolor or palette.get("panel", palette.get("bg", "#1e1e1e"))
        border = bordercolor or palette.get("border", "#3c3c3c")
        active_bg = palette.get("button_hover", bg)

        options = {
            "bg": bg,
            "activebackground": active_bg,
            "troughcolor": trough,
            "highlightbackground": border,
            "highlightcolor": border,
            "highlightthickness": 1,
            "bd": 0,
            "borderwidth": 0,
            "relief": tk.FLAT,
            "activerelief": tk.FLAT,
            "elementborderwidth": 1,
            "width": 12,
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

        scrollbar = getattr(widget, "vbar", None)
        if scrollbar is not None:
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

            safe_configure(
                '.',
                background=palette["bg"],
                foreground=palette["fg"],
                fieldbackground=palette["field"],
                font=('Segoe UI', 10)
            )
            safe_configure('TFrame', background=palette["bg"])
            safe_configure(
                'Card.TFrame',
                background=palette["panel"],
                bordercolor=palette.get("panel_border", palette["border"]),
                lightcolor=palette.get("panel_border", palette["border"]),
                darkcolor=palette.get("panel_border", palette["border"]),
                borderwidth=1,
                relief=tk.SOLID
            )
            safe_configure('TLabel', background=palette["bg"], foreground=palette["fg"], padding=2)
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
                padding=[15, 8],
                font=('Segoe UI', 10, 'bold')
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
                    ('disabled', [15, 8]),
                    ('selected', [15, 8]),
                    ('active', [15, 8])
                ],
                expand=[
                    ('disabled', [0, 0, 0, 0]),
                    ('selected', [0, 0, 0, 0]),
                    ('active', [0, 0, 0, 0])
                ]
            )
            safe_configure(
                'TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=palette["border"],
                lightcolor=palette["border"],
                darkcolor=palette["border"],
                padding=6
            )
            safe_map(
                'TButton',
                background=[
                    ('active', palette.get("button_hover", palette["panel_alt"])),
                    ('pressed', palette["accent_selected"]),
                    ('disabled', palette["panel"])
                ],
                foreground=[('disabled', palette["muted_dim"])]
            )
            safe_configure(
                'Accent.TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=palette["accent"],
                lightcolor=palette["accent"],
                darkcolor=palette["accent"],
                padding=6,
                borderwidth=1,
                relief=tk.SOLID
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
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'GuidedNeutral.TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=palette["accent"],
                lightcolor=palette["accent"],
                darkcolor=palette["accent"],
                padding=6,
                borderwidth=1,
                relief=tk.SOLID
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
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'GuidedAccent.TButton',
                background=palette["panel_alt"],
                foreground=palette["fg"],
                bordercolor=palette["accent"],
                lightcolor=palette["accent"],
                darkcolor=palette["accent"],
                padding=6,
                borderwidth=1,
                relief=tk.SOLID
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
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'PulseNeutral.TButton',
                background=palette.get("surface_info", palette.get("button_hover", palette["panel_alt"])),
                foreground=palette["fg"],
                bordercolor=palette["accent_hover"],
                lightcolor=palette["accent_hover"],
                darkcolor=palette["accent_hover"],
                padding=6,
                borderwidth=1,
                relief=tk.SOLID
            )
            safe_map(
                'PulseNeutral.TButton',
                background=[
                    ('active', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('pressed', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('disabled', palette["panel"])
                ],
                foreground=[('disabled', palette["muted_dim"])],
                bordercolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ]
            )
            safe_configure(
                'PulseAccent.TButton',
                background=palette.get("surface_info", palette.get("button_hover", palette["panel_alt"])),
                foreground=palette["fg"],
                bordercolor=palette["accent_hover"],
                lightcolor=palette["accent_hover"],
                darkcolor=palette["accent_hover"],
                padding=6,
                borderwidth=1,
                relief=tk.SOLID
            )
            safe_map(
                'PulseAccent.TButton',
                background=[
                    ('active', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('pressed', palette.get("surface_info", palette.get("button_hover", palette["panel_alt"]))),
                    ('disabled', palette["panel"])
                ],
                foreground=[('disabled', palette["muted_dim"])],
                bordercolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                lightcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
                    ('disabled', palette["border"])
                ],
                darkcolor=[
                    ('active', palette["accent_hover"]),
                    ('pressed', palette["accent_hover"]),
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
                    ('readonly', palette["panel_alt"]),
                    ('disabled', palette["panel"])
                ],
                foreground=[
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
                arrowsize=14
            )
            safe_map(
                'TCombobox',
                fieldbackground=[('readonly', palette["field"])],
                selectbackground=[('readonly', palette["accent"])],
                selectforeground=[('readonly', '#ffffff')],
                foreground=[('disabled', palette["muted_dim"])]
            )
            safe_configure(
                'TSpinbox',
                fieldbackground=palette["field"],
                foreground=palette["fg"],
                bordercolor=palette["border"],
                lightcolor=palette["border"],
                darkcolor=palette["border"],
                arrowsize=14
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
            safe_configure(
                'Vertical.TScrollbar',
                background=palette["panel_alt"],
                troughcolor=palette["bg"],
                bordercolor=palette["border"],
                arrowcolor=palette["fg"]
            )
            safe_map(
                'Vertical.TScrollbar',
                background=[('active', palette.get("button_hover", palette["panel_alt"]))],
                arrowcolor=[('active', palette["fg"])]
            )
            safe_configure(
                'Horizontal.TScrollbar',
                background=palette["panel_alt"],
                troughcolor=palette["bg"],
                bordercolor=palette["border"],
                arrowcolor=palette["fg"]
            )
            safe_map(
                'Horizontal.TScrollbar',
                background=[('active', palette.get("button_hover", palette["panel_alt"]))],
                arrowcolor=[('active', palette["fg"])]
            )
        except: pass

    def get_main_tab_label(self, tab_key: str) -> str:
        labels = {
            "campaign": "[Z1] Wizard",
            "annotation": "[Z2] Autoanotacja",
            "characters": "[Z3] Znaki na tablicach",
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
    
    def _create_tabs(self):
        try:
            try:
                self.tabs['campaign'] = CampaignTab(self.notebook, self)
                self.notebook.add(self.tabs['campaign'].frame, text=self.get_main_tab_label("campaign"))

            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki Kampanii: {e}")

            self.tabs['annotation'] = AnnotationTab(self.notebook, self)
            self.notebook.add(self.tabs['annotation'].frame, text=self.get_main_tab_label("annotation"))
            
            try:
                self.tabs['characters'] = CharacterAnnotationTab(self.notebook, self)
                self.notebook.add(
                    self.tabs['characters'].frame,
                    text=self.get_main_tab_label("characters")
                )
            except Exception as e:

                logger.error(f"Nie udało się załadować zakładki ZNAKI: {e}")

            
            try:
                self.tabs['training'] = TrainingTab(self.notebook, self)
                self.notebook.add(self.tabs['training'].frame, text=self.get_main_tab_label("training"))
            except Exception as e:
                logger.error(f"Nie udało się załadować zakładki TRENING: {e}")

            if HelpTab:
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
        left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=4)

        def make_menu_button(label: str, items_factory, min_width: int = 220):
            shell = tk.Frame(left, bg=palette["panel"], bd=0, highlightthickness=0)
            shell.pack(side=tk.LEFT, padx=(0, 4), pady=0)

            btn = tk.Button(
                shell,
                text=label,
                bg=palette["panel"],
                fg=palette["fg"],
                activebackground=palette["panel"],
                activeforeground=palette["fg"],
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=4,
                font=("Segoe UI", 10, "bold"),
                highlightthickness=0,
                command=lambda: self._toggle_menu_dropdown(btn, items_factory(), min_width=min_width)
            )
            btn.pack(side=tk.TOP, fill=tk.X)

            underline = tk.Frame(
                shell,
                bg=palette["panel"],
                height=2,
                bd=0,
                highlightthickness=0
            )
            underline.pack(side=tk.TOP, fill=tk.X, padx=4)

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
                {"kind": "command", "label": "Wyjście", "command": self._on_closing},
            ],
            min_width=180
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
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=6
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

    def _widget_contains_point(self, widget, x_root: int, y_root: int) -> bool:
        if widget is None:
            return False

        try:
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            return wx <= x_root < (wx + widget.winfo_width()) and wy <= y_root < (wy + widget.winfo_height())
        except Exception:
            return False

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
        clean_message = str(message or "").strip()
        if not clean_message:
            clean_message = self.default_status_message

        if clean_message == self.default_status_message:
            new_text = clean_message
        else:
            prefixes = {
                "help": "[POMOC]",
                "warning": "[UWAGA]",
                "error": "[BLAD]",
                "success": "[OK]",
                "info": "[INFO]",
            }
            prefix = prefixes.get(icon, "[INFO]")
            new_text = f"{prefix} {clean_message}"
        try:
            current_text = self.status_text.get(1.0, tk.END).strip()
            if current_text != new_text.strip():
                self.status_text.config(state=tk.NORMAL)
                self.status_text.delete(1.0, tk.END)
                self.status_text.insert(tk.END, new_text)
                self.status_text.config(state=tk.DISABLED)
                self.root.update_idletasks()
        except Exception: pass
    
    def set_processing(self, processing: bool):
        self.is_processing = processing
        self.root.config(cursor="wait" if processing else "")
        self.root.update()

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

        self.notebook.select(str(self.tabs[tab_key].frame))

    def open_controlled_tab(self, tab_key: str):
        if tab_key not in self.tabs:
            raise KeyError(f"Unknown tab key: {tab_key}")

        tab_widget = str(self.tabs[tab_key].frame)

        # Na chwilę odblokuj zakładkę, aby można ją było wybrać programowo.
        self.notebook.tab(tab_widget, state="normal")
        self.notebook.select(tab_widget)

        # po przejściu od razu zsynchronizuj dostępność zakładek
        self.update_campaign_tab_access()

    def _guard_campaign_navigation(self, event=None):
        return


    
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

            for tab_name, tab in getattr(self, "tabs", {}).items():
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
