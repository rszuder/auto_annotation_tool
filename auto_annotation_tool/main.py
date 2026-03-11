#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-Annotation Tool dla CVAT v3.0
==================================
Punkt wejścia aplikacji.

Uruchomienie:
    Windows: python -m auto_annotation_tool.main
    Linux:   python3 -m auto_annotation_tool.main
"""

import sys
import os

# Dodaj ścieżkę do pakietu (nadrzędny katalog)
parent_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, parent_dir)

from auto_annotation_tool.config import (
    CONFIG, TK_AVAILABLE, YOLO_AVAILABLE, CUDA_AVAILABLE,
    PIL_AVAILABLE, CV2_AVAILABLE, YAML_AVAILABLE, logger
)


def main():
    """Punkt wejścia aplikacji."""
    
    print("=" * 70)
    print(f"  {CONFIG.APP_NAME} v{CONFIG.VERSION}")
    print("=" * 70)
    print(f"  YOLO:      {'[OK]' if YOLO_AVAILABLE else '[X] pip install ultralytics'}")
    print(f"  CUDA/GPU:  {'[OK]' if CUDA_AVAILABLE else '[X] CPU mode'}")
    print(f"  PIL:       {'[OK]' if PIL_AVAILABLE else '[X] pip install Pillow'}")
    print(f"  OpenCV:    {'[OK]' if CV2_AVAILABLE else '[?] Opcjonalny'}")
    print(f"  PyYAML:    {'[OK]' if YAML_AVAILABLE else '[?] Opcjonalny'}")
    print("=" * 70)
    
    if not TK_AVAILABLE:
        print("\nBŁĄD: Tkinter jest wymagany!")
        print("Windows: Tkinter powinien być wbudowany")
        print("Linux:   sudo apt-get install python3-tk")
        input("\nNaciśnij Enter aby zamknąć...")
        sys.exit(1)
    
    if not YOLO_AVAILABLE:
        print("\nOSTRZEŻENIE: YOLO niedostępny!")
        print("Funkcje detekcji i treningu będą wyłączone.")
        print("Instalacja: pip install ultralytics\n")
    
    # Import GUI
    import tkinter as tk
    from tkinter import ttk, messagebox
    from auto_annotation_tool.gui import AutoAnnotationApp
    
    # Utwórz okno
    root = tk.Tk()
    
    # Responsywność okna
    root.geometry("1200x800")
    root.minsize(800, 600)
    root.resizable(True, True)
    
    # Styl
    try:
        style = ttk.Style()
        for theme in ['clam', 'vista', 'xpnative', 'winnative']:
            if theme in style.theme_names():
                style.theme_use(theme)
                break
    except Exception:
        pass
    
    # Aplikacja
    app = AutoAnnotationApp(root)
    
    # Zamknięcie
    def on_closing():
        if hasattr(app, 'is_processing') and app.is_processing:
            if messagebox.askokcancel("Zamknij", "Przetwarzanie w toku. Zamknąć?"):
                app.is_processing = False
                root.after(500, root.destroy)
        else:
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    logger.info("Uruchamianie GUI...")
    root.mainloop()


if __name__ == "__main__":
    main()