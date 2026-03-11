#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zarządzanie ikonami z fallback do tekstu.
"""

from typing import Optional, Tuple, Dict


class IconManager:
    """Zarządzanie ikonami z automatycznym fallback do tekstu."""
    
    ICONS: Dict[str, Tuple[str, str]] = {
        # Pliki/Foldery
        "folder": ("📁", "[DIR]"),
        "file": ("📄", "[FILE]"),
        "image": ("🖼️", "[IMG]"),
        
        # Akcje
        "play": ("▶️", "[>]"),
        "stop": ("⏹️", "[X]"),
        "pause": ("⏸️", "[||]"),
        "refresh": ("🔄", "[REF]"),
        "save": ("💾", "[SAVE]"),
        "load": ("📂", "[LOAD]"),
        "export": ("📤", "[EXP]"),
        "import": ("📥", "[IMP]"),
        
        # Status
        "check": ("✅", "[OK]"),
        "error": ("❌", "[ERR]"),
        "warning": ("⚠️", "[!]"),
        "info": ("ℹ️", "[i]"),
        "success": ("✅", "[OK]"),
        "question": ("❓", "[?]"),
        
        # Obiekty
        "model": ("🧠", "[MODEL]"),
        "car": ("🚗", "[CAR]"),
        "plate": ("🔢", "[PLATE]"),
        "robot": ("🤖", "[AUTO]"),
        "chart": ("📊", "[STATS]"),
        "trophy": ("🏆", "[RANK]"),
        
        # Narzędzia
        "settings": ("⚙️", "[SET]"),
        "search": ("🔍", "[?]"),
        "help": ("❓", "[?]"),
        "training": ("🎯", "[TRAIN]"),
        
        # Sprzęt
        "gpu": ("🎮", "[GPU]"),
        "cpu": ("💻", "[CPU]"),
        "clock": ("🕐", "[TIME]"),
    }
    
    _use_emoji: bool = True
    _tested: bool = False
    
    @classmethod
    def test_emoji_support(cls, widget=None) -> bool:
        """Testuje czy system obsługuje emoji."""
        if cls._tested:
            return cls._use_emoji
        
        cls._tested = True
        
        if widget is None:
            cls._use_emoji = True
            return True
        
        try:
            import tkinter as tk
            test_label = tk.Label(widget, text="🔍")
            test_label.update_idletasks()
            width = test_label.winfo_reqwidth()
            test_label.destroy()
            cls._use_emoji = width > 8
        except Exception:
            cls._use_emoji = False
        
        return cls._use_emoji
    
    @classmethod
    def get(cls, name: str) -> str:
        """Pobiera ikonę (emoji lub tekst fallback)."""
        if name not in cls.ICONS:
            return f"[{name.upper()}]"
        
        emoji, fallback = cls.ICONS[name]
        return emoji if cls._use_emoji else fallback
    
    @classmethod
    def force_text_mode(cls):
        """Wymusza tryb tekstowy."""
        cls._use_emoji = False
        cls._tested = True
    
    @classmethod
    def force_emoji_mode(cls):
        """Wymusza tryb emoji."""
        cls._use_emoji = True
        cls._tested = True