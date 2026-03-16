#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import tkinter as tk
import traceback
from pathlib import Path

def main():
    try:
        # Importujemy Twoją aplikację jako zewnętrzny moduł
        from auto_annotation_tool.gui.app import AutoAnnotationApp
        from auto_annotation_tool.config import CONFIG
        
        # Inicjalizacja głównego okna
        root = tk.Tk()
        
        # Ustawienia początkowe okna
        root.geometry("1400x900")
        root.minsize(1024, 768)
        root.title(f"{CONFIG.APP_NAME} v{CONFIG.VERSION}")
        
        # Odpalenie interfejsu
        app = AutoAnnotationApp(root)
        
        # Start pętli zdarzeń
        root.mainloop()
        
    except Exception as e:
        print("\n" + "="*60)
        print("❌ KRYTYCZNY BŁĄD URUCHOMIENIA APLIKACJI ❌")
        print("="*60)
        traceback.print_exc()
        print("="*60)
        input("Naciśnij ENTER, aby zamknąć...")

if __name__ == "__main__":
    main()