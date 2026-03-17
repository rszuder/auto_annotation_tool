#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka: Pomoc, Architektura i Przewodnik po systemie.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from ..config import CONFIG
from ..icons import IconManager

class HelpTab:
    """Zakładka pomocy, instrukcji i architektury systemu."""
    
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.icon_manager = IconManager
        
        self.frame = ttk.Frame(parent)
        self._create_widgets()
    
    def _create_widgets(self):
        """Tworzy responsywny interfejs z dwoma zakładkami."""
        notebook = ttk.Notebook(self.frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # ==========================================
        # ZAKŁADKA 1: INSTRUKCJE KROK PO KROKU
        # ==========================================
        instr_frame = ttk.Frame(notebook)
        notebook.add(instr_frame, text=f"{self.icon_manager.get('question')} Instrukcje")
        
        t1 = scrolledtext.ScrolledText(instr_frame, wrap=tk.WORD, bg="#fcfcfc", font=("Segoe UI", 10), padx=20, pady=20)
        t1.pack(fill=tk.BOTH, expand=True)
        self._setup_tags(t1)
        self._fill_instructions(t1)
        
        # ==========================================
        # ZAKŁADKA 2: ARCHITEKTURA I WORKSPACE
        # ==========================================
        arch_frame = ttk.Frame(notebook)
        notebook.add(arch_frame, text=f"{self.icon_manager.get('robot')} Architektura i Workspace")
        
        t2 = scrolledtext.ScrolledText(arch_frame, wrap=tk.WORD, bg="#fcfcfc", font=("Segoe UI", 10), padx=20, pady=20)
        t2.pack(fill=tk.BOTH, expand=True)
        self._setup_tags(t2)
        self._fill_architecture(t2)

    def _setup_tags(self, widget):
        """Ustawia style formatowania tekstu."""
        widget.tag_configure("H1", font=("Segoe UI", 16, "bold"), foreground="#2c3e50", spacing1=10, spacing3=15)
        widget.tag_configure("H2", font=("Segoe UI", 12, "bold"), foreground="#2980b9", spacing1=20, spacing3=5)
        widget.tag_configure("BOLD", font=("Segoe UI", 10, "bold"))
        widget.tag_configure("HIGHLIGHT", foreground="#e67e22", font=("Segoe UI", 10, "bold"))
        widget.tag_configure("CODE", font=("Consolas", 10), background="#ecf0f1", foreground="#c0392b")
        widget.tag_configure("GREEN", foreground="#27ae60", font=("Segoe UI", 10, "bold"))
        widget.tag_configure("RED", foreground="#c0392b", font=("Segoe UI", 10, "bold"))
        widget.tag_configure("LIST", lmargin1=20, lmargin2=35, spacing1=3)

    def _fill_instructions(self, t):
        t.config(state=tk.NORMAL)
        
        t.insert(tk.END, "🚀 Od surowych zdjęć do własnego modelu ALPR\n", "H1")
        t.insert(tk.END, "Poniżej znajduje się kompletny przepływ pracy (Workflow), który pozwoli Ci zbudować niezawodny system rozpoznawania tablic.\n")

        t.insert(tk.END, "\n⚠️ KROK 0: Prawidłowe nazewnictwo plików!\n", "H2")
        t.insert(tk.END, "Zanim zaczniesz, upewnij się, że Twoje zdjęcia źródłowe w folderze ", "")
        t.insert(tk.END, "1_raw_images ", "BOLD")
        t.insert(tk.END, "mają nazwy odzwierciedlające tablice na nich widoczne. Program wykorzysta to do automatycznego oceniania AI.\n")
        t.insert(tk.END, "Format: ", "")
        t.insert(tk.END, "rej1_rej2_identyfikator.jpg\n", "CODE")
        t.insert(tk.END, "Przykład: ", "")
        t.insert(tk.END, "WLS19936_KRA123_Zdjecie1.jpg\n", "CODE")

        t.insert(tk.END, "\n🎯 KROK 1: Detekcja pojazdów i tablic (Autoanotacja)\n", "H2")
        t.insert(tk.END, "• Przejdź do zakładki ", "LIST")
        t.insert(tk.END, "Autoanotacja", "BOLD")
        t.insert(tk.END, ".\n", "")
        t.insert(tk.END, "• Wybierz modele AI (zalecany Tryb C: Pojazdy + Tablice).\n", "LIST")
        t.insert(tk.END, "• Wskaż folder ze swoimi zdjęciami i kliknij START. Program znajdzie obiekty i wygeneruje główny plik ", "LIST")
        t.insert(tk.END, "annotations.xml", "CODE")
        t.insert(tk.END, ".\n", "")

        t.insert(tk.END, "\n✂️ KROK 2: Wycinanie i Pierwszy Odczyt (OCR)\n", "H2")
        t.insert(tk.END, "• Przejdź do zakładki ", "LIST")
        t.insert(tk.END, "Znaki na tablicach", "BOLD")
        t.insert(tk.END, " -> ", "")
        t.insert(tk.END, "1. Wycinanie Tablic", "BOLD")
        t.insert(tk.END, ".\n", "")
        t.insert(tk.END, "• Kliknij START. Algorytm wytnie tablice, a te przekrzywione lub pionowe położy na płasko.\n", "LIST")
        t.insert(tk.END, "• Przejdź do pod-zakładki ", "LIST")
        t.insert(tk.END, "2. Wykrywanie Znaków", "BOLD")
        t.insert(tk.END, ". Odwiedź ", "")
        t.insert(tk.END, "Laboratorium Filtrów", "HIGHLIGHT")
        t.insert(tk.END, ", aby ustawić kontrast i białą ramkę. Zapisz preset.\n", "")
        t.insert(tk.END, "• Odpal ", "LIST")
        t.insert(tk.END, "Szybki Test", "BOLD")
        t.insert(tk.END, ". Jeśli AI odczyta tekst poprawnie, tablica ląduje na liście jako ", "")
        t.insert(tk.END, "🟢 ZIELONA", "GREEN")
        t.insert(tk.END, ". Błędy zaświecą się na ", "")
        t.insert(tk.END, "🔴 CZERWONO", "RED")
        t.insert(tk.END, ".\n", "")

        t.insert(tk.END, "\n🛠️ KROK 3: Naprawa błędów w CVAT\n", "H2")
        t.insert(tk.END, "• Przejdź do pod-zakładki ", "LIST")
        t.insert(tk.END, "3. Integracje", "BOLD")
        t.insert(tk.END, ".\n", "")
        t.insert(tk.END, "• Użyj OPCJI 1, aby wyeksportować do formatu .ZIP tylko błędne tablice.\n", "LIST")
        t.insert(tk.END, "• Wgraj ZIP do programu CVAT, popraw ręcznie pomylone ramki/litery i wyeksportuj XML.\n", "LIST")
        t.insert(tk.END, "• Wgraj poprawiony XML w sekcji IMPORT. Program magicznie zamieni błędy na status ", "LIST")
        t.insert(tk.END, "🟢 Perfekcyjny!", "GREEN")
        t.insert(tk.END, "\n", "")

        t.insert(tk.END, "\n🔥 KROK 4: Mega-Dataset i Trenowanie Własnego AI\n", "H2")
        t.insert(tk.END, "• Mając dużo zielonych tablic, kliknij ", "LIST")
        t.insert(tk.END, "WYEKSPORTUJ PERFEKCYJNE TABLICE DO YOLO", "GREEN")
        t.insert(tk.END, " (Opcja 2 w Integracjach).\n", "")
        t.insert(tk.END, "• Program przeskanuje historię, usunie duplikaty i zbuduje gotowy, potężny zbiór uczący!\n", "LIST")
        t.insert(tk.END, "• Przejdź do głównej zakładki ", "LIST")
        t.insert(tk.END, "Trening i Analiza", "BOLD")
        t.insert(tk.END, ". Podziel zbiór (Train/Val) i wytrenuj swój własny model rozpoznawania znaków, pozbywając się powolnego OCR-a na zawsze!\n", "")
        
        t.config(state=tk.DISABLED)

    def _fill_architecture(self, t):
        t.config(state=tk.NORMAL)
        
        t.insert(tk.END, "🏛 Architektura MLOps i Wymuszony Porządek\n", "H1")
        t.insert(tk.END, f"{CONFIG.APP_NAME} to nie jest zwykły skrypt. To środowisko zaprojektowane według najlepszych inżynieryjnych wzorców uczenia maszynowego.\n")

        t.insert(tk.END, "\n♻️ Filozofia Active Learning (Uczenie Aktywne)\n", "H2")
        t.insert(tk.END, "Nie marnuj życia na ręczne rysowanie tysięcy ramek wokół liter. System został zbudowany tak, aby zautomatyzować 90% pracy:\n")
        t.insert(tk.END, "1. Pozwól sztucznej inteligencji czytać tablice samej.\n")
        t.insert(tk.END, "2. Jeśli AI zrobi to bezbłędnie - tablica automatycznie trafia do bazy treningowej.\n")
        t.insert(tk.END, "3. Jeśli AI się pomyli - system 'wypluwa' błąd, a Ty korygujesz go w CVAT.\n")
        t.insert(tk.END, "4. Skorygowane błędy zasilają bazę treningową. Im dłużej używasz programu, tym inteligentniejszy się on staje!\n")

        t.insert(tk.END, "\n🗂 Drzewo Katalogów Workspace\n", "H2")
        t.insert(tk.END, "Aby chronić Cię przed zgubieniem danych, program przy pierwszym uruchomieniu tworzy uporządkowane środowisko pracy. Oprzyj na nim swoją pracę:\n\n")
        
        t.insert(tk.END, "📁 Workspace/\n", "BOLD")
        
        t.insert(tk.END, " ├── ", "CODE"); t.insert(tk.END, "1_raw_images\n", "BOLD")
        t.insert(tk.END, " │    └─ Wrzuć tutaj surowe, nienaruszone zdjęcia.\n", "")
        
        t.insert(tk.END, " ├── ", "CODE"); t.insert(tk.END, "2_auto_annotations\n", "BOLD")
        t.insert(tk.END, " │    └─ Tu lądują główne pliki XML po wykryciu aut.\n", "")
        
        t.insert(tk.END, " ├── ", "CODE"); t.insert(tk.END, "3_cropped_characters\n", "BOLD")
        t.insert(tk.END, " │    └─ Tu tworzą się foldery run_XXX. Każdy run zawiera wycięte tablice\n", "")
        t.insert(tk.END, " │       i najważniejszy plik w całym systemie: ", "")
        t.insert(tk.END, "metadata.json", "HIGHLIGHT")
        t.insert(tk.END, "!\n", "")
        
        t.insert(tk.END, " ├── ", "CODE"); t.insert(tk.END, "4_training_datasets\n", "BOLD")
        t.insert(tk.END, " │    └─ Gotowe wygenerowane zbiory (Train/Val) dla Ultralytics.\n", "")
        
        t.insert(tk.END, " ├── ", "CODE"); t.insert(tk.END, "5_training_runs\n", "BOLD")
        t.insert(tk.END, " │    └─ Kiedy trenujesz model, tu lądują wykresy skuteczności i wagi (.pt).\n", "")
        
        t.insert(tk.END, " ├── ", "CODE"); t.insert(tk.END, "6_models\n", "BOLD")
        t.insert(tk.END, " │    └─ Skopiuj tu swoje najlepsze, wytrenowane sieci neuronowe.\n", "")
        
        t.insert(tk.END, " ├── ", "CODE"); t.insert(tk.END, "7_rankings\n", "BOLD")
        t.insert(tk.END, " │    └─ Raporty i testy porównawcze modeli (F1-Score).\n", "")
        
        t.insert(tk.END, " └── ", "CODE"); t.insert(tk.END, "8_ocr_presets\n", "BOLD")
        t.insert(tk.END, "      └─ Zapisane przez Ciebie konfiguracje filtrów obrazu z Laboratorium.\n", "")

        t.insert(tk.END, "\n💎 Single Source of Truth (Pojedyncze Źródło Prawdy)\n", "H2")
        t.insert(tk.END, "Wewnątrz każdego folderu z wyciętymi tablicami program utrzymuje plik ", "")
        t.insert(tk.END, "metadata.json", "CODE")
        t.insert(tk.END, ". To prawdziwy mózg operacji.\n\nZawiera on precyzyjne koordynaty X/Y dla każdej pojedynczej litery oraz jej aktualny status (Perfect/Błąd). To właśnie ten plik steruje rysowaniem zielonych ramek na ekranie w podglądzie, to on służy do eksportowania paczek do CVAT, i to z niego budowany jest przenośny zbiór YOLO. Dzięki niemu nic nigdy się nie rozjedzie!\n")

        t.config(state=tk.DISABLED)