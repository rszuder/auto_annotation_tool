#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontekstowy System Pomocy - Global Hover Edition
Wstrzykuje tekst bezpośrednio do globalnego Panelu na dole programu.
"""

import json
from pathlib import Path
from ..config import logger

class HelpSystem:
    def __init__(self):
        self.db = {}
        self.status_updater = None
        self._load_database()

    def _load_database(self):
        db_path = Path(__file__).parent.parent / "help_db.json"
        if db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    self.db = json.load(f)
            except Exception as e:
                logger.error(f"Nie udało się załadować bazy pomocy: {e}")

    def bind_help(self, widget, index_key: str):
        if index_key not in self.db:
            return

        entry = self.db[index_key]
        full_text = entry.get("full_help", "")

        def on_enter(event=None):
            if self.status_updater and full_text:
                self.status_updater(f"💡 {full_text}")

        def on_leave(event=None):
            if self.status_updater:
                self.status_updater("Gotowy. Najedź myszką na element interfejsu, aby zobaczyć wskazówki.")

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")

HELP = HelpSystem()
