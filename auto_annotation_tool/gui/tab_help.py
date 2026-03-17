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
        
        # ==========================================
        # 1. INSTRUKCJE OGÓLNE (Oryginał)
        # ==========================================
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
        
        # ==========================================
        # 2. INSTRUKCJE CVAT (Oryginał)
        # ==========================================
        cvat_frame = ttk.Frame(notebook)
        notebook.add(cvat_frame, text=f"{self.icon_manager.get('robot')} Format CVAT")
        
        cvat_text = scrolledtext.ScrolledText(cvat_frame, wrap=tk.WORD)
        cvat_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        cvat_content = CVATExporter.get_import_instructions() + "\n\n" + DatasetCreator.get_required_format()
        cvat_text.insert(tk.END, cvat_content.strip())
        cvat_text.config(state=tk.DISABLED)
        
        # ==========================================
        # 3. WORKFLOW: POJAZDY I TABLICE (Oryginał)
        # ==========================================
        help_frame = ttk.Frame(notebook)
        notebook.add(help_frame, text=f"{self.icon_manager.get('question')} Detekcja: Auta i Tablice")
        
        help_text = scrolledtext.ScrolledText(help_frame, wrap=tk.WORD)
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        help_content = """
WORKFLOW: OD SUROWYCH ZDJĘĆ DO WYTRENOWANEGO MODELU (YOLO POSE)

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

        # ==========================================
        # 4. NOWOŚĆ! WORKFLOW: OCR & ZNAKI 
        # ==========================================
        ocr_frame = ttk.Frame(notebook)
        notebook.add(ocr_frame, text=f"{self.icon_manager.get('cut')} Rozpoznawanie Znaków (ALPR)")
        
        ocr_text = scrolledtext.ScrolledText(ocr_frame, wrap=tk.WORD, bg="#fcfcfc", font=("Segoe UI", 10))
        ocr_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Style
        ocr_text.tag_configure("H1", font=("Segoe UI", 12, "bold"), foreground="#2c3e50", spacing1=10, spacing3=5)
        ocr_text.tag_configure("H2", font=("Segoe UI", 10, "bold"), foreground="#2980b9", spacing1=15, spacing3=2)
        ocr_text.tag_configure("BOLD", font=("Segoe UI", 10, "bold"))
        ocr_text.tag_configure("CODE", font=("Consolas", 10), background="#ecf0f1", foreground="#c0392b")
        ocr_text.tag_configure("GREEN", foreground="#27ae60", font=("Segoe UI", 10, "bold"))
        ocr_text.tag_configure("RED", foreground="#c0392b", font=("Segoe UI", 10, "bold"))
        
        ocr_text.insert(tk.END, "OSTATECZNY CEL: Wytrenowanie własnego modelu YOLO do czytania znaków\n", "H1")
        ocr_text.insert(tk.END, "Domyślny silnik OCR ma problem z hologramami i śrubkami. System oparty na Active Learningu pozwala pół-automatycznie zbudować idealny zestaw uczący (Dataset) dla YOLO.\n")

        ocr_text.insert(tk.END, "\n🎯 KROK 1: Prawidłowe nazwy plików wejściowych\n", "H2")
        ocr_text.insert(tk.END, "Zanim zaczniesz wycinać tablice, upewnij się, że Twoje duże zdjęcia mają nazwy odzwierciedlające tablice na nich widoczne. Format to:\n")
        ocr_text.insert(tk.END, "rej1_rej2_identyfikator.jpg  (np. WLS19936_KRA123_moj_test.jpg)\n", "CODE")
        ocr_text.insert(tk.END, "Program odczytuje to i na tej podstawie ocenia skuteczność algorytmów.\n")

        ocr_text.insert(tk.END, "\n🔬 KROK 2: Laboratorium i Szybki Test\n", "H2")
        ocr_text.insert(tk.END, "• Wytnij tablice w zakładce 1. Przejdź do zakładki 2 (Wykrywanie Znaków).\n")
        ocr_text.insert(tk.END, "• Otwórz ", "")
        ocr_text.insert(tk.END, "Laboratorium Filtrów", "BOLD")
        ocr_text.insert(tk.END, " i pobaw się suwakami (np. dodaj białą ramkę). Zapisz Preset.\n")
        ocr_text.insert(tk.END, "• Odpal ", "")
        ocr_text.insert(tk.END, "Szybki Test", "BOLD")
        ocr_text.insert(tk.END, ". Jeśli AI odczyta tekst poprawnie, tablica ląduje na liście jako ")
        ocr_text.insert(tk.END, "🟢 ZIELONA (Perfekcyjna)", "GREEN")
        ocr_text.insert(tk.END, ".\nJeśli popełni błąd – świeci się jako ")
        ocr_text.insert(tk.END, "🔴 CZERWONA (Do poprawy)", "RED")
        ocr_text.insert(tk.END, ".\n")

        ocr_text.insert(tk.END, "\n🤖 KROK 3: Pętla Active Learning (Zamykanie luki)\n", "H2")
        ocr_text.insert(tk.END, "W trzeciej pod-zakładce (Integracje) masz dwie ścieżki:\n")
        ocr_text.insert(tk.END, "1. Ręczna poprawa: ", "BOLD")
        ocr_text.insert(tk.END, "Eksportujesz do formatu CVAT tylko błędy (🔴). Poprawiasz je na stronie, pobierasz XML i wgrywasz do bazy. Program magicznie zamienia je na 🟢!\n")
        ocr_text.insert(tk.END, "2. Fabryka Datasetów: ", "BOLD")
        ocr_text.insert(tk.END, "Kiedy masz już w systemie setki tablic 🟢 (część zrobiło AI, część poprawiłeś Ty), klikasz ")
        ocr_text.insert(tk.END, "WYEKSPORTUJ PERFEKCYJNE TABLICE DO YOLO", "GREEN")
        ocr_text.insert(tk.END, ". Program przeszukuje dysk, zbiera wszystkie pewniaki, tworzy dla nich precyzyjne pliki .txt i buduje gotowy folder szkoleniowy!\n")

        ocr_text.insert(tk.END, "\n🔥 KROK 4: Trenowanie YOLO i ostateczny sukces\n", "H2")
        ocr_text.insert(tk.END, "Z wygenerowanym folderem idziesz do Głównej Zakładki 'Trening'. Dzielisz zbiór w Splitterze, odpalasz uczenie... i gotowe! Możesz teraz podpiąć ten mały, szybki model YOLO w zakładce Znaków, wyłączając wolny OCR na stałe.\n")
        
        ocr_text.config(state=tk.DISABLED)