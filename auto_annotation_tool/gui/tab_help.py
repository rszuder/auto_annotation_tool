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
        self._doc_widgets = []
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

        self.t1 = self._create_text_page(
            "[PZ1] Workflow i praktyka",
            palette=palette,
            filler=self._fill_workflow,
        )
        self.t2 = self._create_text_page(
            "[PZ2] Kampania i iteracje",
            palette=palette,
            filler=self._fill_campaign,
        )
        self.t3 = self._create_text_page(
            "[PZ3] Architektura i dane",
            palette=palette,
            filler=self._fill_architecture,
        )

    def _create_text_page(self, title: str, *, palette: dict, filler):
        page = ttk.Frame(self.notebook)
        self.notebook.add(page, text=title)

        host = ttk.Frame(page)
        host.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(
            host,
            wrap=tk.WORD,
            bg=palette.get("doc_bg", "#1f1f1f"),
            fg=palette.get("doc_fg", "#f3f3f3"),
            insertbackground=palette.get("doc_fg", "#f3f3f3"),
            font=("Segoe UI", 10),
            padx=20,
            pady=20,
        )
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = WebSlimScrollbar(
            host,
            orient=tk.VERTICAL,
            command=text.yview,
            auto_hide=False,
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=scrollbar.set)
        text.web_vbar = scrollbar

        self._setup_tags(text)
        self.app.style_text_widget(text, role="doc")
        filler(text)
        self._doc_widgets.append(text)
        return text

    def _setup_tags(self, widget):
        palette = getattr(self.app, "palette", {})
        widget.tag_configure(
            "H1",
            font=("Segoe UI", 16, "bold"),
            foreground=palette.get("fg", "#ffffff"),
            spacing1=8,
            spacing3=14,
        )
        widget.tag_configure(
            "H2",
            font=("Segoe UI", 12, "bold"),
            foreground=palette.get("accent", "#4fc1ff"),
            spacing1=16,
            spacing3=5,
        )
        widget.tag_configure("BOLD", font=("Segoe UI", 10, "bold"))
        widget.tag_configure(
            "CODE",
            font=("Consolas", 10),
            background=palette.get("code_bg", "#252526"),
            foreground=palette.get("code_fg", "#dcdcaa"),
        )
        widget.tag_configure("LIST", lmargin1=18, lmargin2=36, spacing1=2, spacing3=2)
        widget.tag_configure(
            "GOOD",
            foreground=palette.get("success", "#4ec9b0"),
            font=("Segoe UI", 10, "bold"),
        )
        widget.tag_configure(
            "WARN",
            foreground=palette.get("warning", "#d7ba7d"),
            font=("Segoe UI", 10, "bold"),
        )
        widget.tag_configure(
            "NOTE",
            foreground=palette.get("muted", "#c7c7c7"),
            font=("Segoe UI", 10),
        )

    def apply_theme(self):
        try:
            palette = getattr(self.app, "palette", {})
            self.app.style_panel_surface(self.frame, background=palette.get("panel", "#252526"))
        except Exception:
            pass

        for widget in list(getattr(self, "_doc_widgets", []) or []):
            try:
                self.app.style_text_widget(widget, role="doc")
                self._setup_tags(widget)
            except Exception:
                pass

    @staticmethod
    def _clear_and_enable(widget):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)

    @staticmethod
    def _disable(widget):
        widget.config(state=tk.DISABLED)

    @staticmethod
    def _paragraph(widget, text: str):
        widget.insert(tk.END, str(text).strip() + "\n", ())

    @staticmethod
    def _section(widget, title: str):
        widget.insert(tk.END, "\n" + str(title).strip() + "\n", "H2")

    @staticmethod
    def _bullet_list(widget, items):
        for item in items:
            widget.insert(tk.END, f"- {str(item).strip()}\n", "LIST")

    @staticmethod
    def _code_block(widget, text: str):
        widget.insert(tk.END, str(text).rstrip() + "\n", "CODE")

    @staticmethod
    def _callout(widget, label: str, text: str, tag: str):
        widget.insert(tk.END, str(label).strip() + " ", tag)
        widget.insert(tk.END, str(text).strip() + "\n", ())

    def _fill_workflow(self, widget):
        self._clear_and_enable(widget)

        widget.insert(tk.END, "Z5. Aktualny przewodnik pracy\n", "H1")
        self._paragraph(
            widget,
            "Ta karta opisuje dzisiejszy, rzeczywisty workflow aplikacji. "
            "Skupia się na tym, jak pracować teraz w Z1-Z4, jak czytać podział na tory "
            "tablic i znaków oraz jak nie pomylić artefaktów pochodzących z różnych etapów.",
        )

        self._section(widget, "Dwa tryby pracy")
        self._bullet_list(
            widget,
            [
                "Tryb swobodny: sam wskazujesz foldery, runy, datasety i modele. To najlepszy tryb do eksperymentów, napraw i pracy poza kampanią.",
                "Tryb kampanii: projekt ma własną iterację, własne katalogi i stan zapisany przez Wizard. Zakładki robocze wykonują pracę, a Z1 prowadzi przez E1-E4.",
                "Z5 dokumentuje oba tryby, ale zawsze w pierwszej kolejności opisuje to, co jest źródłem prawdy w aktualnej implementacji.",
            ],
        )

        self._section(widget, "Mapa aplikacji")
        self._bullet_list(
            widget,
            [
                "[Z1] Wizard: nawigacja po projekcie, decyzje kampanijne, status iteracji i przejścia do zakładek roboczych.",
                "[Z2] Anotacja tablic: autoanotacja, ręczna korekta polygonów, przegląd listy, oznaczanie [OK] i domykanie etapu E2.",
                "[Z3] Autoanotacja znaków tablic: PZ1 wyodrębnia tablice, PZ2 analizuje znaki i boxy, PZ3 robi eksporty, importy i dataset znaków.",
                "[Z4] Trening i analiza: PZ1 przygotowuje dataset lub split, PZ2 prowadzi trening, walidacje, historię i ranking modeli.",
                "[Z5] Instrukcja i architektura: zbiera zasady pracy, model kampanii i opis danych.",
            ],
        )

        self._section(widget, "Ground truth i nazwy plików")
        self._paragraph(
            widget,
            "Nazwa obrazu jest nadal najważniejszym źródłem prawdy dla tekstu tablicy. "
            "OCR, YOLO i hybryda są oceniane względem znaków odczytanych z nazwy pliku.",
        )
        self._paragraph(
            widget,
            "W trybie swobodnym najlepiej przygotowywać takie paczki obrazów jako osobne katalogi pod "
            "Workspace/1_raw_images/NazwaPaczki/. Dzięki temu łatwiej utrzymać spójność między Z2, Z3 i późniejszym "
            "ground truth opartym o nazwy plików.",
        )
        self._code_block(
            widget,
            "Przykłady:\n"
            "PO12345_001.jpg\n"
            "DW5AB12_007.jpg\n"
            "TAB1_TAB2_TAB3_id.jpg",
        )
        self._bullet_list(
            widget,
            [
                "Część przed końcowym identyfikatorem obrazu jest interpretowana jako oczekiwany napis tablicy lub lista tablic.",
                "Jeśli nazwy są niespójne, downstream będzie działał technicznie, ale porównania w Z3/PZ2 i ranking perfectów przestaną mieć wartość diagnostyczną.",
                "Nie mieszaj w jednej paczce różnych konwencji nazewniczych, jeśli chcesz uczciwie oceniać modele.",
            ],
        )

        self._section(widget, "Typowy workflow w trybie swobodnym")
        self._bullet_list(
            widget,
            [
                "1. Zanim wejdziesz do Z2, przygotowujesz paczkę obrazów najlepiej w Workspace/1_raw_images/NazwaPaczki/, tak aby nazwy plików były docelowym ground truth dla tablic.",
                "2. Z2: uruchamiasz anotację tablic na folderze obrazów. Start tworzy nowy run w Workspace/2_auto_annotations/...",
                "3. Z2: przeglądasz listę, poprawiasz polygony, zapisujesz zmiany do annotations.xml i w razie potrzeby budujesz dataset tablic.",
                "4. Z3 / PZ1: bierzesz zgodną parę źródeł, czyli annotations.xml oraz oryginalne obrazy, i wycinasz tablice do nowego runu preview.",
                "5. Z3 / PZ2: uruchamiasz OCR, YOLO lub hybrydę, porównujesz wynik z ground truth i poprawiasz błędne przypadki.",
                "6. Z3 / PZ3: eksportujesz przypadki do CVAT, importujesz poprawki i budujesz dataset znaków albo nowy split z aktywnego preview.",
                "7. Z4: wybierasz tor treningu, wskazujesz gotowy dataset YOLO, dobierasz model bazowy i uruchamiasz trening, walidacje oraz ranking.",
            ],
        )

        self._section(widget, "Co realnie robi Z2")
        self._bullet_list(
            widget,
            [
                "Z2 nie jest już tylko przyciskiem Start. To pełne miejsce pracy nad listą obrazów, podglądem i ręczną korektą polygonu tablicy.",
                "W kampanii Z2 potrafi pracować na stagingu iteracji, preview-runie kampanijnym i już zapisanym runie do poprawy.",
                "Domknięcie E2 przenosi wynik do katalogu docelowego projektu i aktualizuje ApprovedSet tablic, z którego potem korzysta E4 toru tablic.",
                "W torze znaków E2 bywa etapem przygotowawczym: jego celem nie jest wtedy sam trening tablic, tylko dostarczenie poprawnego źródła do Z3.",
            ],
        )

        self._section(widget, "Co realnie robi Z3")
        self._bullet_list(
            widget,
            [
                "PZ1 wymaga świadomie dobranej pary: annotations.xml i tych samych obrazów, na których ten XML powstał.",
                "PZ2 pracuje na preview-runie tablic. Tu porównujesz OCR, YOLO i hybrydę, sprawdzasz boxy znaków i naprawiasz przypadki problematyczne.",
                "PZ3 nie jest już dodatkiem eksportowym. To miejsce, w którym spinasz CVAT, import ręcznych poprawek, tor perfect oraz budowę datasetu znaków.",
                "W kampanii Z3 potrafi otwierać się automatycznie na gotowej paczce z PZ1 albo wracać do PZ1, gdy zmieniło się źródło tablic z Z2.",
            ],
        )

        self._section(widget, "Co realnie robi Z4")
        self._bullet_list(
            widget,
            [
                "Z4 dzisiaj ma dwa panele robocze: [PZ1] Budowa datasetu oraz [PZ2] Trening i wyniki.",
                "W trybie swobodnym najczęściej konsumuje już gotowy dataset YOLO; helpery w PZ1 są wtedy narzędziami pomocniczymi, a nie obowiązkowym etapem.",
                "W kampanii tor jest zablokowany przez E2. Dla tablic Z4 pracuje na ApprovedSecie projektu, a dla znaków na poprawnym datasecie z Z3/PZ3.",
                "Historia runów, walidacja i ranking są częścią Z4/PZ2, a nie osobnych modułów poza treningiem.",
            ],
        )

        self._section(widget, "Praktyczne zasady, które oszczędzają czas")
        self._bullet_list(
            widget,
            [
                "Nie mieszaj źródeł z różnych runów. Jeśli XML i obrazy nie są tą samą parą, wynik PZ1 będzie technicznie mylący.",
                "Przed domknięciem E2 zawsze zapisz ręczne poprawki. ApprovedSet ma odzwierciedlać to, co rzeczywiście chcesz przekazać dalej.",
                "Jeśli w kampanii zmieniło się źródło tablic z Z2, wracaj do PZ1 i przebuduj wycinanie zamiast próbować ratować stary preview-run.",
                "Terminale procesów są diagnostyczne. Do normalnej pracy można je chować, ale przy problemach z datasetem lub treningiem są pierwszym miejscem do sprawdzenia.",
                "Dolny pasek pomocy i overlay kontekstowy nadal są szybsze od szukania w kodzie: pokazują rolę aktywnego widgetu w bieżącym workflow.",
            ],
        )

        self._callout(
            widget,
            "Ważne:",
            "Z5 opisuje stan obecnej aplikacji, w którym Wizard jest nawigatorem, a cała praca merytoryczna odbywa się w Z2, Z3 i Z4.",
            "WARN",
        )

        self._disable(widget)

    def _fill_campaign(self, widget):
        self._clear_and_enable(widget)

        widget.insert(tk.END, "Kampania, iteracje i logika Z1\n", "H1")
        self._paragraph(
            widget,
            "Aktualna kampania nie kopiuje już roboczego UI z Z2-Z4. "
            "Wizard w Z1 trzyma stan projektu, pokazuje statusy E1-E4 i kieruje do "
            "właściwych narzędzi. Edycja, anotacja, eksport i trening dzieją się w "
            "zakładkach roboczych.",
        )

        self._section(widget, "Jak czytać rolę Z1")
        self._bullet_list(
            widget,
            [
                "Z1 jest panelem sterowania iteracją, a nie osobnym edytorem anotacji ani treningu.",
                "CampaignManager przechowuje stan trwały: projekt, iteracje, aktualny krok, tor iteracji, finish state E4 i ścieżki do kluczowych artefaktów.",
                "Zakładki Z2, Z3 i Z4 raportują gotowość i wynik. Wizard tylko renderuje te statusy i prowadzi do właściwego miejsca.",
            ],
        )

        self._section(widget, "E1. Paczka wejściowa iteracji")
        self._bullet_list(
            widget,
            [
                "E1 pracuje na pełnej głównej puli zdjęć. Wybierasz katalog, wczytujesz aktualny wybrany folder zdjęć i jawnie zatwierdzasz E1.",
                "Sama obecność zdjęć w folderze iteracji nie wystarcza. E2 odblokowuje się dopiero po zatwierdzeniu E1.",
                "Histogram znaków i analiza puli są pomocnicze. To narzędzia decyzyjne, nie bramka techniczna.",
            ],
        )

        self._section(widget, "E2. Tor iteracji")
        self._paragraph(
            widget,
            "W praktyce E2 jest decyzją projektową, która blokuje dalszy przebieg iteracji. "
            "W rozmowach i starszych opisach możesz jeszcze spotkać nazwy Tor A i Tor B.",
        )
        self._bullet_list(
            widget,
            [
                "Tor A = plate = tor tablic. Iteracja koncentruje się na tablicach i po Z2 przechodzi do E4.",
                "Tor B = char = tor znaków. Najpierw przygotowujesz poprawne tablice dla tej paczki, potem pracujesz w Z3 i dopiero na końcu idziesz do E4.",
                "Po zatwierdzeniu E2 tor jest zamrożony dla iteracji. Z4 dziedziczy ten wybór i nie pozwala już swobodnie przełączać toru.",
            ],
        )

        self._section(widget, "E3. Znaki i gold pack")
        self._bullet_list(
            widget,
            [
                "E3 istnieje tylko dla toru znaków. W torze tablic jest pomijane jako etap roboczy.",
                "PZ1 wyodrębnia tablice z aktualnego źródła z Z2. PZ2 analizuje znaki i boxy. PZ3 buduje dataset znaków i spina eksporty/importy.",
                "Jeśli po drodze źródło tablic z Z2 zmieniło się lub zostało rozszerzone, kampania wymusza powrót do PZ1 i ponowne wycinanie.",
            ],
        )

        self._section(widget, "E4. Dataset i trening")
        self._bullet_list(
            widget,
            [
                "W torze tablic E4 korzysta z zatwierdzonego zbioru projektu. Minimalna bramka to co najmniej 2 oznaczone obrazy w ApprovedSecie.",
                "W torze znaków E4 wymaga poprawnego datasetu z Z3/PZ3. Samo zamknięcie E3 nie wystarcza, jeśli split lub eksport są niepełne.",
                "Z4 w kampanii ma dwa obszary: PZ1 przygotowuje dataset albo split, PZ2 prowadzi trening, walidacje, historię i ranking.",
                "Promocja najlepszego modelu do projektu nie zamyka iteracji automatycznie. Stan gotowości do domknięcia E4 jest trzymany osobno.",
            ],
        )

        self._section(widget, "Powroty, naprawy i ponowne wejścia")
        self._bullet_list(
            widget,
            [
                "Po domknięciu kroku można dalej wracać do Z2, Z3 albo Z4 w trybie przeglądu albo naprawy, ale Wizard nie powinien cofnięciu robić automatycznie za Ciebie.",
                "W Z4 zwykły powrót do kampanii jest osobną akcją nawigacyjną. Nie należy go mylić z przyciskiem domknięcia E4.",
                "Jeśli E4 jest już zamknięte, Z4 nadal może służyć do przeglądu wyników, walidacji, historii i ewentualnych decyzji o kolejnej iteracji.",
            ],
        )

        self._section(widget, "Po zamknięciu iteracji")
        self._bullet_list(
            widget,
            [
                "Projekt przechodzi na current_step = 5, a Wizard oferuje rozpoczęcie nowej iteracji.",
                "Nowa iteracja może wystartować od nowej paczki z E1 albo od tego samego zestawu zdjęć i przejść od razu do E2.",
                "Aktywne modele projektu pozostają zachowane. To one stają się bazą do dalszej autoanotacji i kolejnych treningów.",
            ],
        )

        self._section(widget, "Co jest źródłem prawdy w kampanii")
        self._bullet_list(
            widget,
            [
                "Rejestr kampanii: Workspace/campaigns_registry.json przechowuje listę projektów i podstawowy stan aktywnego projektu.",
                "Stan projektu: katalog 9_projects/<projekt>/_campaign_state zawiera lokalne artefakty sterujące workflow kampanii.",
                "ApprovedSet tablic i wynikowe runy w katalogu projektu są źródłem dla kolejnych bramek E2-E4, a nie chwilowy stan jednego widgetu.",
            ],
        )

        self._callout(
            widget,
            "Ważne:",
            "Jeśli Wizard i zakładka robocza wydają się niespójne, najpierw sprawdź aktualny current_step, iteration_target i aktywne źródło danych projektu. To są trzy najczęstsze przyczyny pozornych regresji.",
            "WARN",
        )

        self._disable(widget)

    def _fill_architecture(self, widget):
        self._clear_and_enable(widget)

        widget.insert(tk.END, "Architektura danych, Workspace i artefakty\n", "H1")
        self._paragraph(
            widget,
            f"{CONFIG.APP_NAME} pracuje jednocześnie na przestrzeni globalnej Workspace "
            "oraz na lokalnych przestrzeniach projektowych w 9_projects. Zrozumienie tej "
            "różnicy oszczędza bardzo dużo czasu przy diagnozie problemów z runami, "
            "datasetami i treningiem.",
        )

        self._section(widget, "Dwie warstwy danych")
        self._bullet_list(
            widget,
            [
                "Workspace globalny: miejsce wspólne dla trybu swobodnego, modeli bazowych, presetów OCR, globalnych datasetów i historycznych runów poza kampanią.",
                "Workspace projektu: osobne drzewo katalogów dla każdego projektu kampanii w 9_projects/<nazwa_folderu_projektu>/...",
                "W kampanii preferuj zawsze ścieżki projektowe. Globalny Workspace traktuj jako zaplecze wspólne i tryb swobodny.",
            ],
        )

        self._section(widget, "Szkic globalnego Workspace")
        self._code_block(
            widget,
            "Workspace/\n"
            "|-- 1_raw_images/\n"
            "|-- 2_auto_annotations/\n"
            "|-- 3_cropped_characters/\n"
            "|-- 4_training_datasets/\n"
            "|-- 5_training_runs/\n"
            "|-- 6_models/\n"
            "|-- 7_rankings/\n"
            "|-- 8_ocr_presets/\n"
            "`-- 9_projects/\n",
        )
        self._paragraph(
            widget,
            "W trybie swobodnym katalog Workspace/1_raw_images/ jest preferowanym miejscem na paczki wejściowe. "
            "Najczytelniejszy układ to Workspace/1_raw_images/NazwaPaczki/, gdzie nazwy plików od razu niosą ground truth "
            "dla OCR, testów i rankingu znaków.",
        )

        self._section(widget, "Szkic katalogu projektu")
        self._code_block(
            widget,
            "Workspace/9_projects/<project>/\n"
            "|-- 1_raw_images/\n"
            "|-- 2_auto_annotations/\n"
            "|-- 3_cropped_characters/\n"
            "|-- 4_training_datasets/\n"
            "|-- 5_training_runs/\n"
            "|-- _campaign_state/\n"
            "`-- _staging/\n",
        )

        self._section(widget, "Najważniejsze artefakty i do czego służą")
        self._bullet_list(
            widget,
            [
                "annotations.xml: wynik anotacji tablic. To główny plik przejściowy między Z2 a Z3/PZ1 oraz źródło datasetu tablic.",
                "metadata.json: rdzeń preview-runu Z3. Trzyma odczyty, statusy, boxy znaków, perfecty i dane potrzebne do eksportu/importu.",
                "data.yaml: punkt wejścia do treningu YOLO. Opisuje klasy oraz splity train / val / test.",
                "training_history.json: historia runów treningowych w danym katalogu 5_training_runs.",
                "campaigns_registry.json + _campaign_state: stan projektu kampanijnego, iteracji, targetu i lokalnych artefaktów Wizarda.",
            ],
        )

        self._section(widget, "Jak dane przepływają między etapami")
        self._bullet_list(
            widget,
            [
                "Z2 -> Z3: annotations.xml plus oryginalne obrazy dają materiał do wycinania tablic w PZ1.",
                "Z3/PZ1 -> Z3/PZ2: run wycinania daje preview-run tablic do OCR, YOLO i hybrydy.",
                "Z3/PZ2 -> Z3/PZ3: aktywny preview-run zasila eksporty CVAT, import poprawek, tor perfect i dataset znaków.",
                "Z2 lub Z3/PZ3 -> Z4: gotowy dataset YOLO trafia do treningu, walidacji i rankingu.",
                "Z4 -> projekt: najlepszy checkpoint może zostać wypromowany do aktywnego modelu projektu i stać się bazą dla kolejnych iteracji.",
            ],
        )

        self._section(widget, "Shared vs project-local")
        self._bullet_list(
            widget,
            [
                "Modele bazowe z 6_models/base są zasobem wspólnym.",
                "Runy i datasety tworzone w kampanii powinny pozostawać wewnątrz katalogu projektu, żeby nie mieszać iteracji i ApprovedSetów.",
                "Presety OCR oraz część rankingów mają nadal charakter współdzielony, ale wynik oceny zawsze zależy od konkretnego preview-runu albo datasetu.",
            ],
        )

        self._section(widget, "Wymagania środowiska i start aplikacji")
        self._paragraph(
            widget,
            "Aplikacja zakłada uruchomienie na Pythonie z działającym Tkinterem. "
            "Przy starcie sprawdzane są najważniejsze biblioteki runtime, a wynik jest wypisywany "
            "w konsoli w formie statusów OK albo BRAK.",
        )
        self._bullet_list(
            widget,
            [
                "Biblioteki krytyczne dla startu GUI: Tkinter, NumPy, OpenCV i Pillow.",
                "Biblioteki funkcjonalne dla pełnego workflow: PyYAML, PyTorch, Ultralytics i EasyOCR.",
                "Lista pakietów pip do środowiska runtime jest utrzymywana w requirements-runtime.txt.",
                "Jeśli na nowej maszynie czegoś brakuje, bootstrap przed startem GUI pokaże raport, zaproponuje instalację i może uruchomić pip automatycznie w bieżącym interpreterze.",
                "Po udanej instalacji aplikacja może sama wykonać restart i ponownie sprawdzić środowisko.",
            ],
        )
        self._code_block(
            widget,
            "Pliki związane ze startem środowiska:\n"
            "main.py\n"
            "dependency_bootstrap.py\n"
            "requirements-runtime.txt",
        )
        self._paragraph(
            widget,
            "Tkinter nie jest instalowany z requirements-runtime.txt, bo zwykle pochodzi z samej instalacji Pythona "
            "i na Windows wymaga Pythona z komponentem Tcl/Tk.",
        )

        self._section(widget, "Gdzie najpierw patrzeć przy diagnozie problemu")
        self._bullet_list(
            widget,
            [
                "Sprawdź aktywną zakładkę i aktualne źródło danych: folder obrazów, run, preview-run albo dataset.",
                "W kampanii sprawdź current_step, iteration_target i to, czy problem dotyczy ApprovedSetu, preview-runu czy gotowego datasetu.",
                "W Z2, Z3 i Z4 ukryte terminale procesu są pierwszym miejscem do szukania technicznych przyczyn błędu.",
                "Jeśli lista, preview albo przycisk zachowują się inaczej niż oczekujesz, sprawdź najpierw czy nie pracujesz na starszym runie albo na źródle z poprzedniej iteracji.",
            ],
        )

        self._callout(
            widget,
            "Nota architektoniczna:",
            "Obecna faza rozwoju aplikacji stawia na cienki Wizard i silne zakładki robocze. Dlatego opis danych i przepływów jest ważniejszy niż opis pojedynczych kontrolek UI.",
            "NOTE",
        )

        self._disable(widget)
