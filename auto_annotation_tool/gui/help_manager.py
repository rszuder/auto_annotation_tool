#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontekstowy system pomocy dla całej aplikacji.
Wyświetla opis aktualnie wskazanego elementu w globalnym panelu na dole okna.
"""

import json
from pathlib import Path

from ..config import logger


class HelpSystem:
    def __init__(self):
        self.db = {}
        self.status_updater = None
        self.default_message = "Gotowy. Najedź myszką na element interfejsu, aby zobaczyć wskazówki."
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

    def bind_help(self, widget, index_key: str):
        if widget is None:
            return

        entry = self.db.get(index_key, {})
        full_text = str(entry.get("full_help", "") or "").strip()
        if not full_text:
            full_text = f"Brak opisu dla elementu: {index_key}."

        def on_enter(event=None):
            self._push_status(full_text, "help")

        def on_leave(event=None):
            self._push_status(self.default_message, "info")

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")


HELP = HelpSystem()
