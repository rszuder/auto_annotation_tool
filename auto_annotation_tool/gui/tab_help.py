#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka Z5: pomoc, instrukcje i architektura projektu.
"""

import tkinter as tk
from tkinter import ttk

from ..config import CONFIG
from .web_slim_scrollbar import WebSlimScrollbar


class HelpTab:
    """Zakładka pomocy, instrukcji i architektury systemu."""

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.frame = ttk.Frame(parent)
        self._startup_ui_ready = False
        self._create_widgets()
        self.frame.after_idle(self._mark_startup_ui_ready)

    def _mark_startup_ui_ready(self):
        self._startup_ui_ready = True

    def is_startup_ui_ready(self) -> bool:
        return bool(getattr(self, "_startup_ui_ready", False))

    def _create_widgets(self):
        palette = getattr(self.app, "palette", {})

        self.notebook = ttk.Notebook(self.frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        instr_frame = ttk.Frame(self.notebook)
        self.notebook.add(instr_frame, text="[PZ1] Instrukcje")

        instr_text_host = ttk.Frame(instr_frame)
        instr_text_host.pack(fill=tk.BOTH, expand=True)
        self.t1 = tk.Text(
            instr_text_host,
            wrap=tk.WORD,
            bg=palette.get("doc_bg", "#1f1f1f"),
            fg=palette.get("doc_fg", "#f3f3f3"),
            insertbackground=palette.get("doc_fg", "#f3f3f3"),
            font=("Segoe UI", 10),
            padx=20,
            pady=20
        )
        self.t1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.t1_scrollbar = WebSlimScrollbar(
            instr_text_host,
            orient=tk.VERTICAL,
            command=self.t1.yview,
            auto_hide=False,
        )
        self.t1_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.t1.configure(yscrollcommand=self.t1_scrollbar.set)
        self.t1.web_vbar = self.t1_scrollbar
        self._setup_tags(self.t1)
        self.app.style_text_widget(self.t1, role="doc")
        self._fill_instructions(self.t1)

        arch_frame = ttk.Frame(self.notebook)
        self.notebook.add(arch_frame, text="[PZ2] Architektura i Workspace")

        arch_text_host = ttk.Frame(arch_frame)
        arch_text_host.pack(fill=tk.BOTH, expand=True)
        self.t2 = tk.Text(
            arch_text_host,
            wrap=tk.WORD,
            bg=palette.get("doc_bg", "#1f1f1f"),
            fg=palette.get("doc_fg", "#f3f3f3"),
            insertbackground=palette.get("doc_fg", "#f3f3f3"),
            font=("Segoe UI", 10),
            padx=20,
            pady=20
        )
        self.t2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.t2_scrollbar = WebSlimScrollbar(
            arch_text_host,
            orient=tk.VERTICAL,
            command=self.t2.yview,
            auto_hide=False,
        )
        self.t2_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.t2.configure(yscrollcommand=self.t2_scrollbar.set)
        self.t2.web_vbar = self.t2_scrollbar
        self._setup_tags(self.t2)
        self.app.style_text_widget(self.t2, role="doc")
        self._fill_architecture(self.t2)

    def _setup_tags(self, widget):
        palette = getattr(self.app, "palette", {})
        widget.tag_configure("H1", font=("Segoe UI", 16, "bold"), foreground=palette.get("fg", "#ffffff"), spacing1=8, spacing3=14)
        widget.tag_configure("H2", font=("Segoe UI", 12, "bold"), foreground=palette.get("accent", "#4fc1ff"), spacing1=16, spacing3=5)
        widget.tag_configure("BOLD", font=("Segoe UI", 10, "bold"))
        widget.tag_configure("CODE", font=("Consolas", 10), background=palette.get("code_bg", "#252526"), foreground=palette.get("code_fg", "#dcdcaa"))
        widget.tag_configure("LIST", lmargin1=18, lmargin2=36, spacing1=2, spacing3=2)
        widget.tag_configure("GOOD", foreground=palette.get("success", "#4ec9b0"), font=("Segoe UI", 10, "bold"))
        widget.tag_configure("WARN", foreground=palette.get("warning", "#d7ba7d"), font=("Segoe UI", 10, "bold"))
        widget.tag_configure("NOTE", foreground=palette.get("muted", "#c7c7c7"), font=("Segoe UI", 10))

    def apply_theme(self):
        try:
            palette = getattr(self.app, "palette", {})
            self.app.style_panel_surface(self.frame, background=palette.get("panel", "#252526"))
        except Exception:
            pass

        for widget_name in ("t1", "t2"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                self.app.style_text_widget(widget, role="doc")
                self._setup_tags(widget)
            except Exception:
                pass

    def _fill_instructions(self, t):
        t.config(state=tk.NORMAL)

        t.insert(tk.END, "Przewodnik pracy z aplikacją ALPR\n", "H1")
        t.insert(
            tk.END,
            "Ta karta opisuje stabilny workflow narzędzi Z2-Z4 oraz zasady pracy na globalnym Workspace. "
            "Szczegóły trybu kampanii i Wizarda zostały tutaj celowo pominięte, bo ten obszar jest obecnie przebudowywany.\n",
            ()
        )

        t.insert(tk.END, "\nZasada podstawowa\n", "H2")
        t.insert(tk.END, "- Nazwa pliku wejściowego pełni rolę ground truth dla odczytu tablic i znaków.\n", "LIST")
        t.insert(tk.END, "- Z2 tworzy run autoanotacji tablic, Z3 rozwija z niego materiał znakowy, a Z4 trenuje na gotowym datasecie YOLO.\n", "LIST")
        t.insert(tk.END, "- Ta dokumentacja skupia się na aktualnym, stabilnym sposobie pracy bez opisu kampanii.\n", "LIST")

        t.insert(tk.END, "\nGround truth w nazwie pliku\n", "H2")
        t.insert(tk.END, "Program ocenia poprawność odczytu tablic na podstawie nazwy zdjęcia. Obowiązuje format:\n", ())
        t.insert(tk.END, "TAB1_TAB2_TAB3_id.jpg\n", "CODE")
        t.insert(tk.END, "Części ", ())
        t.insert(tk.END, "TAB1, TAB2, TAB3", "BOLD")
        t.insert(tk.END, " są prawdą referencyjną. OCR i detekcja znaków są porównywane z listą tablic wyciągniętą z nazwy pliku.\n", ())

        t.insert(tk.END, "\nZ2: Autoanotacja tablic\n", "H2")
        t.insert(tk.END, "- Wskazujesz folder wejściowy ze zdjęciami i uruchamiasz detekcję pojazdów oraz tablic.\n", "LIST")
        t.insert(tk.END, "- Każdy start zapisuje nowy run autoanotacji w ", ())
        t.insert(tk.END, "Workspace/2_auto_annotations/plates/", "CODE")
        t.insert(tk.END, ". Taki run autoanotacji zawiera co najmniej ", ())
        t.insert(tk.END, "annotations.xml", "CODE")
        t.insert(tk.END, " oraz pliki pomocnicze.\n", ())
        t.insert(tk.END, "- Po zakończeniu możesz obejrzeć wyniki na liście i podglądzie, a z istniejącego runu autoanotacji zbudować gotowy dataset tablic do treningu YOLO Pose.\n", "LIST")

        t.insert(tk.END, "\nZ3: Wycinanie tablic, OCR i gold pack\n", "H2")
        t.insert(tk.END, "- [PZ1] Wycinanie tablic wymaga zgodnej pary źródeł: ", ())
        t.insert(tk.END, "annotations.xml", "CODE")
        t.insert(tk.END, " oraz folderu oryginalnych obrazów, na których ten XML powstał.\n", ())
        t.insert(tk.END, "- Wynikiem jest nowa paczka runu wycinania ", ())
        t.insert(tk.END, "run_XXX", "CODE")
        t.insert(tk.END, " w ", ())
        t.insert(tk.END, "Workspace/3_cropped_characters/", "CODE")
        t.insert(tk.END, " z wyciętymi tablicami i plikiem ", ())
        t.insert(tk.END, "metadata.json", "CODE")
        t.insert(tk.END, ".\n", ())
        t.insert(tk.END, "- [PZ2] Wykrywanie znaków i analiza pozwala porównywać OCR, YOLO i tryb hybrydowy. Lista tablic pokazuje wynik oraz zgodność z ground truth.\n", "LIST")
        t.insert(tk.END, "- [PZ3] Integracje i dataset służą do eksportu przypadków do CVAT, importu poprawek oraz budowy gold packa i datasetu znaków bez duplikatów.\n", "LIST")

        t.insert(tk.END, "\nZ4: Trening i analiza\n", "H2")
        t.insert(tk.END, "- W aktualnym workflow Z4 pracuje na gotowym datasecie YOLO. Najpierw wybierasz tor treningu: tablice albo znaki.\n", "LIST")
        t.insert(tk.END, "- Dla tablic używasz datasetu YOLO Pose przygotowanego wcześniej w Z2.\n", "LIST")
        t.insert(tk.END, "- Dla znaków używasz datasetu YOLO Detect przygotowanego wcześniej w Z3/PZ3.\n", "LIST")
        t.insert(tk.END, "- Wskazujesz katalog datasetu z plikiem ", ())
        t.insert(tk.END, "data.yaml", "CODE")
        t.insert(tk.END, ", wybierasz model bazowy lub własny checkpoint ", ())
        t.insert(tk.END, ".pt", "CODE")
        t.insert(tk.END, ", ustawiasz parametry i uruchamiasz trening.\n", ())
        t.insert(tk.END, "- Historia runów treningowych, wykresy, walidacja i ranking są odświeżane w obrębie wybranego toru treningu.\n", "LIST")

        t.insert(tk.END, "\nJak czytać UI\n", "H2")
        t.insert(tk.END, "- Chowane terminale procesu służą do diagnostyki. Jeśli nie są potrzebne, można je zostawić schowane i pracować na czystym układzie.\n", "LIST")
        t.insert(tk.END, "- Dolny panel pomocy jest dynamiczny: przesunięcie myszy nad element powinno pokazać jego rolę w aktualnym workflow.\n", "LIST")
        t.insert(tk.END, "- Gdy opis w dolnym panelu pomocy jest dłuższy, możesz przewijać go skrótem Ctrl + Alt + rolka myszy.\n", "LIST")
        t.insert(tk.END, "- Zielone statusy zwykle oznaczają zgodność z ground truth albo poprawne zakończenie operacji, a czerwone wymagają korekty albo ręcznej weryfikacji.\n", "LIST")

        t.insert(tk.END, "\nPoza zakresem tej wersji helpa\n", "H2")
        t.insert(
            tk.END,
            "Opis kampanii, iteracji i Wizarda został tutaj świadomie pominięty. "
            "W tej wersji pomocy dokumentujemy tylko te elementy, które są już stabilne po ostatnich zmianach.\n",
            ()
        )

        t.config(state=tk.DISABLED)

    def _fill_architecture(self, t):
        t.config(state=tk.NORMAL)

        t.insert(tk.END, "Architektura danych i Workspace\n", "H1")
        t.insert(
            tk.END,
            f"{CONFIG.APP_NAME} pracuje na wspólnej przestrzeni roboczej Workspace. "
            "Poniższy opis dotyczy stabilnej struktury danych i przepływu artefaktów między Z2, Z3 i Z4.\n",
            ()
        )

        t.insert(tk.END, "\nStabilny przepływ danych\n", "H2")
        t.insert(tk.END, "- Z2 bierze surowe obrazy i zapisuje run autoanotacji tablic z plikiem annotations.xml.\n", "LIST")
        t.insert(tk.END, "- Z3/PZ1 bierze annotations.xml oraz tę samą paczkę obrazów źródłowych i tworzy wycięte tablice.\n", "LIST")
        t.insert(tk.END, "- Z3/PZ2 i Z3/PZ3 rozwijają materiał znakowy: OCR, YOLO, poprawki CVAT oraz gold pack i dataset znaków.\n", "LIST")
        t.insert(tk.END, "- Z4 nie produkuje datasetu w głównym trybie pracy. Konsumuje gotowy dataset YOLO i zapisuje artefakty treningowe, walidacyjne oraz rankingowe.\n", "LIST")

        t.insert(tk.END, "\nGlobalne drzewo Workspace\n", "H2")
        t.insert(tk.END, "Poniżej logiczna struktura katalogów aplikacji w formie zbliżonej do wyniku polecenia tree:\n", ())
        t.insert(
            tk.END,
            "Workspace/\n"
            "|-- 1_raw_images/\n"
            "|-- 2_auto_annotations/\n"
            "|   |-- chars/\n"
            "|   `-- plates/\n"
            "|-- 3_cropped_characters/\n"
            "|-- 4_training_datasets/\n"
            "|   |-- chars/\n"
            "|   |-- plates/\n"
            "|   `-- vehicles/\n"
            "|-- 5_training_runs/\n"
            "|   |-- chars/\n"
            "|   |-- plates/\n"
            "|   `-- vehicles/\n"
            "|-- 6_models/\n"
            "|   |-- base/\n"
            "|   |   |-- detect/\n"
            "|   |   `-- pose/\n"
            "|   `-- trained/\n"
            "|       |-- chars/\n"
            "|       |-- plates/\n"
            "|       `-- vehicles/\n"
            "|-- 7_rankings/\n"
            "|   |-- chars/\n"
            "|   |-- plates/\n"
            "|   `-- vehicles/\n"
            "|-- 8_ocr_presets/\n"
            "`-- 9_projects/\n",
            "CODE"
        )

        t.insert(tk.END, "\nCo trafia do którego katalogu\n", "H2")
        t.insert(tk.END, "- 1_raw_images: surowe paczki zdjęć wejściowych.\n", "LIST")
        t.insert(tk.END, "- 2_auto_annotations: runy autoanotacji z Z2, przede wszystkim foldery wynikowe tablic z annotations.xml.\n", "LIST")
        t.insert(tk.END, "- 3_cropped_characters: wycięte i wyprostowane tablice oraz metadata.json z Z3/PZ1.\n", "LIST")
        t.insert(tk.END, "- 4_training_datasets: gotowe datasety YOLO z data.yaml oraz folderami images/ i labels/.\n", "LIST")
        t.insert(tk.END, "- 5_training_runs: logi, wykresy, metryki i artefakty treningów uruchamianych w Z4.\n", "LIST")
        t.insert(tk.END, "- 6_models: modele bazowe oraz checkpointy wytrenowane przez użytkownika.\n", "LIST")
        t.insert(tk.END, "- 7_rankings: wyniki porównań i rankingów modeli.\n", "LIST")
        t.insert(tk.END, "- 8_ocr_presets: zapisane presety Laboratorium OCR.\n", "LIST")
        t.insert(tk.END, "- 9_projects: katalog techniczny na osobne przestrzenie projektowe.\n", "LIST")

        t.insert(tk.END, "\nNajważniejsze zależności między etapami\n", "H2")
        t.insert(tk.END, "- Dataset tablic do treningu powstaje z materiału Z2 i powinien być zgodny z torem YOLO Pose.\n", "LIST")
        t.insert(tk.END, "- Dataset znaków do treningu powstaje z materiału Z3/PZ3 i powinien być zgodny z torem YOLO Detect.\n", "LIST")
        t.insert(tk.END, "- Z4 sprawdza zgodność wybranego toru, datasetu i modelu bazowego przed startem treningu.\n", "LIST")
        t.insert(tk.END, "- Najlepsze checkpointy, rankingi i presety OCR pozostają zasobami współdzielonymi na poziomie Workspace.\n", "LIST")

        t.insert(tk.END, "\nSingle source of truth\n", "H2")
        t.insert(tk.END, "- Nazwa pliku obrazu jest źródłem prawdy dla tekstu tablic używanego w ocenie OCR i znaków.\n", "LIST")
        t.insert(tk.END, "- W runach wyciętych tablic kluczowym plikiem jest ", ())
        t.insert(tk.END, "metadata.json", "CODE")
        t.insert(tk.END, ", bo przechowuje status tablicy, znaki, kolejność po osi X i dane potrzebne do eksportów oraz importów.\n", ())
        t.insert(tk.END, "- W treningu punktem wejścia do datasetu jest ", ())
        t.insert(tk.END, "data.yaml", "CODE")
        t.insert(tk.END, ", który opisuje splity train/val/test i listę klas YOLO.\n", ())

        t.insert(tk.END, "\nPoza zakresem tej sekcji\n", "H2")
        t.insert(
            tk.END,
            "Opis kampanii, iteracji projektu i reguł awansu między krokami został na razie wyłączony z dokumentacji Z5. "
            "Ta karta opisuje tylko to, co jest obecnie stabilne i zgodne z implementacją.\n",
            ()
        )

        t.config(state=tk.DISABLED)
