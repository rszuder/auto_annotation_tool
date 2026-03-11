#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka pomocy.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from ..config import CONFIG, CVAT_IMPORT_INFO
from ..icons import IconManager
from ..training.dataset_creator import DatasetCreator
from ..exporters.cvat_exporter import CVATExporter


class HelpTab:
    """Zakładka pomocy i instrukcji."""
    
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        
        self.frame = ttk.Frame(parent)
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Tworzy responsywny interfejs z notebookiem wewnątrz."""
        notebook = ttk.Notebook(self.frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # -- Instrukcje ogólne --
        general_frame = ttk.Frame(notebook)
        notebook.add(general_frame, text=f"{self.icon_manager.get('info')} O programie")
        
        general_text = scrolledtext.ScrolledText(general_frame, wrap=tk.WORD)
        general_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        general_content = f"""
{CONFIG.APP_NAME} v{CONFIG.VERSION}
======================================================
Narzędzie do automatycznej anotacji pojazdów i tablic rejestracyjnych.

GŁÓWNE FUNKCJE:
• Anotacja: Wykrywanie pojazdów i tablic (tryby A/B/C)
• Obsługa Modeli: Od YOLOv8 po najnowsze YOLOv11 oraz najnowocześniejsze YOLOv26! 
  Zapewnione jest także wsparcie dla własnych plików .pt (Custom Models).
• Trening: Tworzenie i trenowanie modeli YOLO Pose dla tablic.
• Eksport: Do formatu CVAT for Images 1.1 (XML).
• Ranking: Obliczanie mAP / F1-score pomiędzy AI a człowiekiem.
• Walidacja: Błyskawiczne sprawdzanie plików (XML, Datasets, .pt).

ZALEŻNOŚCI (Wymagania):
• Python 3.8+ (Zalecany 3.10 - 3.12)
• ultralytics (Pakiet pobierze niezbędne architektury YOLO)
• Pillow (PIL)
• OpenCV, PyYAML (Opcjonalne, ale wysoce zalecane do wydajności)

PRZYDATNE INFORMACJE:
W przypadku wyboru modelu, którego fizycznie brakuje w folderze `./models`, pakiet ultralytics
spróbuje automatycznie pobrać go z internetu w momencie uruchomienia predykcji/treningu.
Dotyczy to w pełni wspieranych architektur (np. yolo11s-pose.pt, yolo26m-pose.pt).
Dla modeli Custom, musisz jawnie wskazać ścieżkę do pliku.
        """
        general_text.insert(tk.END, general_content.strip())
        general_text.config(state=tk.DISABLED)
        
        # -- Instrukcje CVAT --
        cvat_frame = ttk.Frame(notebook)
        notebook.add(cvat_frame, text=f"{self.icon_manager.get('robot')} Format CVAT")
        
        cvat_text = scrolledtext.ScrolledText(cvat_frame, wrap=tk.WORD)
        cvat_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        cvat_content = CVATExporter.get_import_instructions() + "\n\n" + DatasetCreator.get_required_format()
        cvat_text.insert(tk.END, cvat_content.strip())
        cvat_text.config(state=tk.DISABLED)
        
        # -- Szybka pomoc (Kroki) --
        help_frame = ttk.Frame(notebook)
        notebook.add(help_frame, text=f"{self.icon_manager.get('question')} Workflow - Krok po Kroku")
        
        help_text = scrolledtext.ScrolledText(help_frame, wrap=tk.WORD)
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        help_content = """
WORKFLOW: OD SUROWYCH ZDJĘĆ DO WYTRENOWANEGO MODELU

1. ANOTACJA AUTOMATYCZNA (AI-Assisted)
   - Przejdź do zakładki "Anotacja".
   - Wybierz Tryb C (Pojazdy + tablice). Ograniczy to fałszywe tablice na tle.
   - Wskaż folder ze swoimi zdjęciami z kamer.
   - Z listy modeli wybierz np. najnowszy YOLOv26m-pose (lub yolo11s-pose dla szybkości).
   - Kliknij "Rozpocznij". Narzędzie wygeneruje w folderze Output plik 'annotations.xml'.

2. POPRAWIANIE (Human-in-the-loop)
   - Otwórz platformę CVAT (lokalnie lub w chmurze).
   - Utwórz Task wg instrukcji w zakładce "Format CVAT" (utwórz odpowiednie Labels!).
   - Zaimportuj wygenerowany wyżej plik XML (CVAT 1.1).
   - Przejrzyj klatki: usuń fałszywe poligony, popraw niedokładne rogi, dodaj brakujące.
   - Wyeksportuj Task ponownie do pliku XML. Masz teraz "Ground Truth".

3. RANKING (Opcjonalny krok oceny)
   - Przejdź do zakładki "Ranking".
   - Wskaż model, surowy XML z pkt. 1 oraz poprawiony XML z pkt. 2.
   - Zobaczysz jak bardzo model AI mylił się względem Twoich ręcznych poprawek (F1-score).

4. TRENOWANIE NOWEGO MODELU
   - Mając poprawiony XML z CVAT, zbuduj Dataset struktury YOLO (używając DatasetCreator w skryptach).
   - W zakładce "Trening" wskaż folder z Datasetem.
   - Wybierz model startowy (Base Model), z którego wiedzy transferujesz (np. yolo26s-pose.pt).
   - Ustaw epoki (np. 150) i rozpocznij trening. Gotowe wagi zapiszą się w folderze /training_runs!
        """
        help_text.insert(tk.END, help_content.strip())
        help_text.config(state=tk.DISABLED)