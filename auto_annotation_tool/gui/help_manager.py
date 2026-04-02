#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontekstowy system pomocy dla całej aplikacji.
Wyświetla opis aktualnie wskazanego elementu w globalnym panelu na dole okna.
"""

import json
import tkinter as tk
from pathlib import Path

from ..config import logger


class HelpSystem:
    def __init__(self):
        self.db = {}
        self.status_updater = None
        self.overlay_presenter = None
        self.overlay_dismisser = None
        self.default_message = "Gotowy. Najedź myszką na element interfejsu, aby zobaczyć wskazówki."
        self._hover_widget = None
        self._hover_help_key = ""
        self._hover_full_text = ""
        self._load_database()

    def _load_database(self):
        db_path = Path(__file__).parent.parent / "help_db.json"
        if not db_path.exists():
            return

        try:
            with open(db_path, "r", encoding="utf-8") as f:
                self.db = json.load(f)
        except Exception as e:
            logger.error(f"Nie udało się załadować bazy pomocy: {e}")

    def _push_status(self, message: str, icon: str):
        if not self.status_updater:
            return

        try:
            self.status_updater(message, icon)
        except TypeError:
            self.status_updater(message)

    def _show_overlay(self, message: str, icon: str = "help"):
        if not self.overlay_presenter:
            return

        try:
            self.overlay_presenter(message, icon)
        except TypeError:
            try:
                self.overlay_presenter(message)
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def _get_widget_cursor(widget) -> str:
        try:
            return str(widget.cget("cursor") or "")
        except Exception:
            return ""

    @staticmethod
    def _should_show_help_cursor(widget) -> bool:
        try:
            return not isinstance(widget, tk.Canvas)
        except Exception:
            return True

    def _set_help_cursor(self, widget, enabled: bool):
        if widget is None:
            return

        if enabled and not self._should_show_help_cursor(widget):
            return

        if enabled:
            if not hasattr(widget, "_help_original_cursor"):
                try:
                    widget._help_original_cursor = self._get_widget_cursor(widget)
                except Exception:
                    widget._help_original_cursor = ""

            for candidate in ("question_arrow", "help", "hand2"):
                try:
                    widget.configure(cursor=candidate)
                    widget._help_context_cursor = candidate
                    return
                except Exception:
                    continue
            return

        try:
            widget.configure(cursor=str(getattr(widget, "_help_original_cursor", "") or ""))
        except Exception:
            pass

    @staticmethod
    def _widget_has_explicit_right_click(widget) -> bool:
        if widget is None:
            return False

        for sequence in ("<Button-3>", "<ButtonRelease-3>"):
            try:
                if str(widget.bind(sequence) or "").strip():
                    return True
            except Exception:
                pass
        return False

    def bind_help(self, widget, index_key: str):
        if widget is None:
            return

        entry = self.db.get(index_key, {})
        full_text = str(entry.get("full_help", "") or "").strip()
        if not full_text:
            full_text = f"Brak opisu dla elementu: {index_key}."

        def on_enter(event=None):
            self._hover_widget = widget
            self._hover_help_key = str(index_key or "")
            self._hover_full_text = full_text
            self._set_help_cursor(widget, True)
            self._push_status(full_text, "help")

        def on_leave(event=None):
            if self._hover_widget is widget:
                self._hover_widget = None
                self._hover_help_key = ""
                self._hover_full_text = ""
            self._set_help_cursor(widget, False)
            self._push_status(self.default_message, "info")

        def on_destroy(event=None):
            if self._hover_widget is widget:
                self._hover_widget = None
                self._hover_help_key = ""
                self._hover_full_text = ""

        def on_secondary_help(event=None):
            self._hover_widget = widget
            self._hover_help_key = str(index_key or "")
            self._hover_full_text = full_text
            self._push_status(full_text, "help")
            self._show_overlay(full_text, "help")

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")
        widget.bind("<Destroy>", on_destroy, add="+")

        # Nie nadpisujemy widgetów, które mają już własną logikę PPM.
        if not self._widget_has_explicit_right_click(widget):
            widget.bind("<Button-3>", on_secondary_help, add="+")


HELP = HelpSystem()
