#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka Z5: pomoc, instrukcje i architektura projektu.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext

from ..config import CONFIG


class HelpTab:
    """Zakładka pomocy, instrukcji i architektury systemu."""

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.frame = ttk.Frame(parent)
        self._create_widgets()

    def _create_widgets(self):
        palette = getattr(self.app, "palette", {})

        self.notebook = ttk.Notebook(self.frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        instr_frame = ttk.Frame(self.notebook)
        self.notebook.add(instr_frame, text="[PZ1] Instrukcje")

        self.t1 = scrolledtext.ScrolledText(
            instr_frame,
            wrap=tk.WORD,
            bg=palette.get("doc_bg", "#1f1f1f"),
            fg=palette.get("doc_fg", "#f3f3f3"),
            insertbackground=palette.get("doc_fg", "#f3f3f3"),
            font=("Segoe UI", 10),
            padx=20,
            pady=20
        )
        self.t1.pack(fill=tk.BOTH, expand=True)
        self._setup_tags(self.t1)
        self._fill_instructions(self.t1)

        arch_frame = ttk.Frame(self.notebook)
        self.notebook.add(arch_frame, text="[PZ2] Architektura i tryby pracy")

        self.t2 = scrolledtext.ScrolledText(
            arch_frame,
            wrap=tk.WORD,
            bg=palette.get("doc_bg", "#1f1f1f"),
            fg=palette.get("doc_fg", "#f3f3f3"),
            insertbackground=palette.get("doc_fg", "#f3f3f3"),
            font=("Segoe UI", 10),
            padx=20,
            pady=20
        )
        self.t2.pack(fill=tk.BOTH, expand=True)
        self._setup_tags(self.t2)
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

        t.insert(tk.END, "Przewodnik pracy z projektem ALPR\n", "H1")
        t.insert(
            tk.END,
            "System prowadzi użytkownika przez kolejne etapy iteracji. W trybie projektu Wizard (Z1) "
            "ustawia ścieżki, blokuje pola sterowane workflow i podpowiada kolejny ruch pulsowaniem.\n",
            ()
        )

        t.insert(tk.END, "\nZasada podstawowa\n", "H2")
        t.insert(tk.END, "- W trybie projektu pracujesz liniowo: Z1 -> Z2 -> Z3 -> Z4.\n", "LIST")
        t.insert(tk.END, "- W trybie swobodnym możesz korzystać z tych samych narzędzi bez Wizarda i na globalnym drzewie Workspace.\n", "LIST")
        t.insert(tk.END, "- Jeżeli wrócisz do wcześniejszego etapu, wyższe etapy tracą ważność workflow i trzeba je ponownie domknąć.\n", "LIST")

        t.insert(tk.END, "\nGround truth w nazwie pliku\n", "H2")
        t.insert(tk.END, "Program ocenia poprawność odczytu tablic na podstawie nazwy zdjęcia. Obowiązuje format:\n", ())
        t.insert(tk.END, "TAB1_TAB2_TAB3_id.jpg\n", "CODE")
        t.insert(tk.END, "Części ", ())
        t.insert(tk.END, "TAB1, TAB2, TAB3", "BOLD")
        t.insert(tk.END, " są prawdą referencyjną. OCR i detekcja znaków są porównywane z listą tablic wyciągniętą z nazwy pliku.\n", ())

        t.insert(tk.END, "\nE1 / Z1: Ingestia w Wizardzie\n", "H2")
        t.insert(tk.END, "- Utwórz lub otwórz projekt w Z1.\n", "LIST")
        t.insert(tk.END, "- Krok E1 przygotowuje folder iteracji i oczekuje na nową porcję zdjęć z dużej puli źródłowej.\n", "LIST")
        t.insert(tk.END, "- Iteracje nie startują od zera na nowym zbiorze. Iteracja 2 bierze kolejną porcję z tej samej głównej puli, a nie dane z iteracji 1.\n", "LIST")

        t.insert(tk.END, "\nE2 / Z2: Autoanotacja\n", "H2")
        t.insert(tk.END, "- W Z2 uruchamiasz detekcję pojazdów i tablic.\n", "LIST")
        t.insert(tk.END, "- W trybie projektu ścieżki wejściowe i wyjściowe są podstawiane automatycznie z drzewa projektu.\n", "LIST")
        t.insert(tk.END, "- Po pomyślnym runie sprawdzasz podgląd i zatwierdzasz etap. Dopiero wtedy Wizard odblokowuje E3.\n", "LIST")

        t.insert(tk.END, "\nE3 / Z3: Wycinanie tablic i złota paczka\n", "H2")
        t.insert(tk.END, "- [PZ1] Wycinanie tablic: system wycina tablice z oryginalnych obrazów i tworzy paczkę ", ())
        t.insert(tk.END, "run_XXX", "CODE")
        t.insert(tk.END, ".\n", ())
        t.insert(tk.END, "- [PZ2] Wykrywanie znaków i analiza: po lewej masz podgląd tablicy i listę tablic, po prawej konfigurację i panel OCR.\n", "LIST")
        t.insert(tk.END, "- Każdy run OCR może wyprodukować nową paczkę adnotacji. To celowe: różne presety potrafią odkryć różne tablice.\n", "LIST")
        t.insert(tk.END, "- Lista tablic pokazuje wykryte znaki w nawiasach kwadratowych w kolejności osi X. Zielone wpisy oznaczają zgodność z ground truth, czerwone wymagają poprawy.\n", "LIST")
        t.insert(tk.END, "- [PZ3] Integracje i dataset: eksportujesz błędne przypadki do CVAT, importujesz poprawki i budujesz gold pack YOLO bez duplikatów.\n", "LIST")

        t.insert(tk.END, "\nE4 / Z4: Trening i analiza\n", "H2")
        t.insert(tk.END, "- [PZ1] Najpierw wybierasz tor: ", ())
        t.insert(tk.END, "tablic", "BOLD")
        t.insert(tk.END, " albo ", ())
        t.insert(tk.END, "znaków", "BOLD")
        t.insert(tk.END, ".\n", ())
        t.insert(tk.END, "- Dla toru tablic tworzysz dataset z XML CVAT. Dla toru znaków dzielisz gotowy dataset na train/val.\n", "LIST")
        t.insert(tk.END, "- Po utworzeniu datasetu przycisk Dalej odblokowuje [PZ2] Trening i analiza.\n", "LIST")
        t.insert(tk.END, "- [PZ2] zawiera trening, historię runów, wykresy, walidację i ranking modeli.\n", "LIST")
        t.insert(tk.END, "- Po udanym treningu Wizard pozwala zakończyć krok 4 i wrócić do kampanii.\n", "LIST")

        t.insert(tk.END, "\nJak czytać UI\n", "H2")
        t.insert(tk.END, "- Pulsowanie przycisku oznacza następny zalecany ruch w trybie projektu.\n", "LIST")
        t.insert(tk.END, "- Chowane terminale procesu służą do diagnostyki. Jeśli nie są potrzebne, można je zostawić schowane i pracować na czystym układzie.\n", "LIST")
        t.insert(tk.END, "- Dolny panel pomocy jest dynamiczny: przesunięcie myszy nad element powinno pokazać jego rolę w aktualnym workflow.\n", "LIST")

        t.insert(tk.END, "\nTryb swobodny\n", "H2")
        t.insert(
            tk.END,
            "Tryb swobodny służy zaawansowanym użytkownikom. Korzysta z globalnego Workspace, "
            "ale nadal może używać najlepszych modeli, presetów OCR i rankingów wypracowanych w projektach.\n",
            ()
        )

        t.config(state=tk.DISABLED)

    def _fill_architecture(self, t):
        t.config(state=tk.NORMAL)

        t.insert(tk.END, "Architektura projektu i tryby pracy\n", "H1")
        t.insert(
            tk.END,
            f"{CONFIG.APP_NAME} łączy dwa porządki pracy: sterowany projektowo workflow kampanii "
            "oraz tryb swobodny dla zaawansowanych użytkowników.\n",
            ()
        )

        t.insert(tk.END, "\nDwa tryby pracy\n", "H2")
        t.insert(tk.END, "- Tryb projektu: Wizard steruje przejściami, ścieżkami i warunkami awansu między Z2, Z3 i Z4.\n", "LIST")
        t.insert(tk.END, "- Tryb swobodny: użytkownik sam wybiera katalogi i narzędzia, pracując bez blokad workflow.\n", "LIST")
        t.insert(tk.END, "- Wyjście z projektu nie może zostawiać śladów po kampanii w trybie swobodnym i odwrotnie.\n", "LIST")

        t.insert(tk.END, "\nGlobalne drzewo Workspace\n", "H2")
        t.insert(tk.END, "Główne drzewo robocze służy jako wspólna baza dla całej aplikacji:\n", ())
        t.insert(tk.END, "Workspace/\n", "CODE")
        t.insert(tk.END, "  1_raw_images\n", "CODE")
        t.insert(tk.END, "  2_auto_annotations\n", "CODE")
        t.insert(tk.END, "  3_cropped_characters\n", "CODE")
        t.insert(tk.END, "  4_training_datasets\n", "CODE")
        t.insert(tk.END, "  5_training_runs\n", "CODE")
        t.insert(tk.END, "  6_models\n", "CODE")
        t.insert(tk.END, "  7_rankings\n", "CODE")
        t.insert(tk.END, "  8_ocr_presets\n", "CODE")
        t.insert(tk.END, "- To drzewo jest podstawą trybu swobodnego.\n", "LIST")
        t.insert(tk.END, "- Najlepsze modele, rankingi i presety OCR mogą być wspólne dla wszystkich projektów.\n", "LIST")

        t.insert(tk.END, "\nDrzewo projektu\n", "H2")
        t.insert(
            tk.END,
            "Każdy projekt ma własne drzewo o tej samej strukturze co Workspace. "
            "W trybie projektu zakładki powinny pracować na ścieżkach projektowych, a nie globalnych.\n",
            ()
        )
        t.insert(tk.END, "- To rozwiązanie ogranicza mieszanie artefaktów między projektami.\n", "LIST")
        t.insert(tk.END, "- Pozwala też wracać do projektów bez ręcznego składania ścieżek.\n", "LIST")

        t.insert(tk.END, "\nIteracje i master pool\n", "H2")
        t.insert(tk.END, "- Iteracja 1 pracuje na pierwszej porcji dużej puli zdjęć.\n", "LIST")
        t.insert(tk.END, "- Iteracja 2 bierze kolejną porcję z tej samej puli, a nie kopiuje wyników iteracji 1.\n", "LIST")
        t.insert(tk.END, "- Główna paczka wejściowa jest bazą projektu. Użytkownik może ją rozszerzać w trakcie kampanii, ale nazwy plików nadal pozostają ground truth dla całego systemu.\n", "LIST")
        t.insert(tk.END, "- System powinien pamiętać, które obrazy z master pool zostały już wykorzystane w poprzednich iteracjach, aby kolejne porcje nie powielały bez potrzeby tej samej wiedzy.\n", "LIST")
        t.insert(tk.END, "- Dobór porcji do E1 nie powinien opierać się wyłącznie na ręcznej ocenie użytkownika. Rekomendowany jest tryb półautomatyczny: aplikacja proponuje paczkę, a użytkownik może ją zaakceptować albo skorygować.\n", "LIST")
        t.insert(tk.END, "- Propozycja paczki do E1 powinna być liczona na podstawie bilansu znaków 0-9 i A-Z w dotychczas zaakceptowanym materiale treningowym, a nie na podstawie surowej liczby obrazów.\n", "LIST")
        t.insert(tk.END, "- Celem nie jest idealna równość co do sztuki, ale miękki balans: kolejne iteracje mają preferować obrazy zawierające znaki niedoreprezentowane w aktualnym zbiorze gold/manual.\n", "LIST")
        t.insert(tk.END, "- Docelowo generator ingestii ma łączyć pamięć użytych zdjęć, licznik znaków, usuwanie duplikatów i możliwość późniejszego dołożenia active learning.\n", "LIST")

        t.insert(tk.END, "\nDobór danych do E1\n", "H2")
        t.insert(tk.END, "- Kandydatami do ingestii są nieużyte jeszcze obrazy z master pool, których ground truth można odczytać z nazwy pliku.\n", "LIST")
        t.insert(tk.END, "- Każdy kandydat powinien dostać ocenę przydatności zależną od tego, jak bardzo pomaga uzupełnić braki znaków w obecnym zbiorze treningowym.\n", "LIST")
        t.insert(tk.END, "- Najwyższy priorytet mają obrazy zawierające znaki najrzadsze w dotychczasowej puli gold pack + importy ręczne.\n", "LIST")
        t.insert(tk.END, "- Użytkownik nie powinien wybierać porcji całkowicie w ciemno. Najlepszy UX to: Auto-propozycja (zalecane) + możliwość ręcznego dodania lub usunięcia kilku obrazów przed zatwierdzeniem E1.\n", "LIST")
        t.insert(tk.END, "- Taki model ogranicza ryzyko złego balansu, ale pozostawia człowiekowi kontrolę nad nietypowymi przypadkami domenowymi.\n", "LIST")

        t.insert(tk.END, "\nPaczki OCR i gold pack\n", "H2")
        t.insert(tk.END, "- Każdy run OCR może stworzyć kolejną paczkę adnotacji.\n", "LIST")
        t.insert(tk.END, "- Różne presety mogą znaleźć różne tablice, dlatego paczek nie traktujemy jako duplikatów samych z siebie.\n", "LIST")
        t.insert(tk.END, "- Eksport gold packa zbiera materiał z wielu paczek, usuwa duplikaty i zostawia czyste złoto do treningu.\n", "LIST")
        t.insert(tk.END, "- Importy ręczne zgodne z formatem projektu mogą być dokładane w dowolnej iteracji. Po scaleniu z pulą gold zwiększają zasób wiedzy dla kolejnych iteracji.\n", "LIST")
        t.insert(tk.END, "- To właśnie zaakceptowany materiał gold/manual powinien być podstawą liczenia balansu znaków dla następnej ingestii, bo reprezentuje wiedzę realnie gotową do treningu.\n", "LIST")

        t.insert(tk.END, "\nSingle source of truth\n", "H2")
        t.insert(tk.END, "W runach wyciętych tablic kluczowym plikiem jest ", ())
        t.insert(tk.END, "metadata.json", "CODE")
        t.insert(tk.END, ". To on przechowuje status tablicy, znaki, ich kolejność po osi X i informacje potrzebne do eksportów, importów i podglądu.\n", ())

        t.insert(tk.END, "\nCo warto zapamiętać\n", "H2")
        t.insert(tk.END, "- Z1 to baza sterowania projektem.\n", "LIST")
        t.insert(tk.END, "- Z2 dotyczy autoanotacji pojazdów i tablic.\n", "LIST")
        t.insert(tk.END, "- Z3 dotyczy znaków na tablicach.\n", "LIST")
        t.insert(tk.END, "- Z4 jest wspólną przestrzenią treningową dla toru tablic i toru znaków.\n", "LIST")
        t.insert(tk.END, "- Pulsowanie, blokady i podpowiedzi nie są dekoracją. To część kontraktu UX całego workflow.\n", "LIST")

        t.config(state=tk.DISABLED)
