#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zakładka Z5: przewodnik użytkownika, kampania i architektura danych.
"""

import tkinter as tk
from tkinter import ttk

from ..config import CONFIG
from .inertial_scroll import InertialScrollController
from .web_slim_scrollbar import WebSlimScrollbar


class HelpTab:
    """Zakładka pomocy, instrukcji i architektury systemu."""

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.frame = ttk.Frame(parent)
        self._startup_ui_ready = False
        self._doc_widgets = []
        self._inertial_scroll = InertialScrollController(self.frame, decay=0.80, interval_ms=14)
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
            "[PZ1] Jak pracować",
            palette=palette,
            filler=self._fill_workflow,
        )
        self.t2 = self._create_text_page(
            "[PZ2] Kampania",
            palette=palette,
            filler=self._fill_campaign,
        )
        self.t3 = self._create_text_page(
            "[PZ3] Dane i architektura",
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
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            text.bind(sequence, self._on_doc_text_mousewheel, add="+")

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

    @staticmethod
    def _text_widget_can_scroll(widget, units: int) -> bool:
        if widget is None or units == 0:
            return False
        try:
            first, last = widget.yview()
            if units < 0 and float(first) <= 0.0:
                return False
            if units > 0 and float(last) >= 1.0:
                return False
            return True
        except Exception:
            return False

    def _on_doc_text_mousewheel(self, event=None):
        widget = getattr(event, "widget", None)
        units = self._inertial_scroll.mousewheel_units(event)
        if units == 0 or not self._text_widget_can_scroll(widget, units):
            return None
        self._inertial_scroll.queue_canvas_by_units(
            widget,
            units,
            magnitude=self._inertial_scroll.mousewheel_magnitude(event),
        )
        return "break"

    def _fill_workflow(self, widget):
        self._clear_and_enable(widget)

        widget.insert(tk.END, "Z5. Przewodnik pracy w aktualnej aplikacji\n", "H1")
        self._paragraph(
            widget,
            "Ta karta jest mapą pracy użytkownika, a nie opisem starej historii refaktorów. "
            "Pokazuje, gdzie powstają dane, kiedy są tylko robocze, kiedy stają się trwałym artefaktem "
            "i które zakładki są właściwym miejscem do kolejnego kroku.",
        )

        self._section(widget, "Najważniejsza zasada")
        self._paragraph(
            widget,
            "Z1 prowadzi kampanię, ale nie wykonuje pracy merytorycznej. Realna praca odbywa się w Z2, Z3 i Z4. "
            "Z5 ma pomóc zrozumieć, dlaczego aplikacja czasem prosi o powrót do konkretnej podzakładki zamiast "
            "pozwalać przeskoczyć dalej na skróty.",
        )
        self._bullet_list(
            widget,
            [
                "Z2 odpowiada za tablice na obrazach: anotację, korektę, status [OK] i eksport.",
                "Z3 odpowiada za znaki z tablic: wycinanie tablic, OCR/YOLO/hybrydę, CVAT, perfecty i dataset znaków.",
                "Z4 odpowiada za wariant datasetu, split, trening, walidację, historię i ranking modeli.",
                "Z5 odpowiada za orientację: wyjaśnia flow, dane, pojęcia i relacje między zakładkami.",
            ],
        )

        self._section(widget, "Dwa tryby pracy")
        self._bullet_list(
            widget,
            [
                "Tryb swobodny (F): sam wybierasz źródła, runy, datasety i modele. To tryb eksperymentów, napraw, testów i pracy poza kampanią.",
                "Tryb kampanii (C): projekt ma iterację, tor, bramki E1, E2, E3, E4T/E4Z i własne katalogi. Wizard pilnuje kolejności oraz spójności artefaktów.",
                "Nie mieszaj założeń tych trybów. W trybie F elastyczność jest zaletą, a w trybie C ważniejsza jest przewidywalność i powtarzalność.",
            ],
        )

        self._section(widget, "Mapa zakładek")
        self._bullet_list(
            widget,
            [
                "[Z1] Wizard kampanii: wybór projektu, iteracja, E1, E2, E3, E4T/E4Z, tor tablic albo tor znaków, powroty do zakładek roboczych.",
                "[Z2] Tablice: ręczny run XML, autoanotacja z modalem modeli, korekta, status [OK], eksport anotacji i eksport YOLO tablic.",
                "[Z3/PZ1] Wycinanie tablic: wybór zgodnego XML i folderu obrazów albo kontynuacja na runie, a potem produkcja cropów tablic.",
                "[Z3/PZ2] Przegląd znaków: OCR, YOLO, hybryda, ręczna poprawa boxów znaków, kompas skrótów i lista przypadków.",
                "[Z3/PZ3] Dataset znaków i CVAT: review pack, import poprawek, gold pack, perfecty i budowa datasetu znaków.",
                "[Z4/PZ1] Źródło treningu: wybór toru, wskazanie źródła i tworzenie wariantów datasetu lub splitu.",
                "[Z4/PZ2] Trening i wyniki: wybór gotowego wariantu, model startowy treningu, parametry, walidacja, historia i ranking.",
            ],
        )

        self._section(widget, "Typowy flow tablic")
        self._bullet_list(
            widget,
            [
                "1. W Z2 wybierasz folder obrazów i tworzysz run ręczny albo uruchamiasz autoanotację.",
                "2. Jeżeli używasz autoanotacji, model tablic jest wybierany w modalu startu procesu. Model pojazdów jest tylko wsparciem lokalizacji tablic.",
                "3. W Z2 poprawiasz polygony tablic i oznaczasz obrazy jako [OK]. Obraz bez ramki nie powinien być zatwierdzany.",
                "4. Eksport anotacji wymaga statusu [OK]. Pozycje bez [OK] nie są pełnoprawnym materiałem do domknięcia etapu.",
                "5. Gotowy eksport może prowadzić do Z4, gdzie tworzysz wariant YOLO Pose tablic i uruchamiasz trening.",
            ],
        )

        self._section(widget, "Typowy flow znaków")
        self._bullet_list(
            widget,
            [
                "1. Najpierw potrzebujesz poprawnych tablic z Z2: XML musi pasować do tego samego folderu obrazów.",
                "2. W Z3/PZ1 wycinasz tablice. Przed startem użytkownik powinien wiedzieć, ile tablic zostanie wyciętych.",
                "3. W Z3/PZ2 analizujesz cropy tablic: OCR czyta tekst, YOLO wykrywa znaki, a hybryda łączy oba podejścia.",
                "4. Błędne przypadki poprawiasz ręcznie albo wysyłasz jako review pack do CVAT i importujesz wynik w tym samym obiegu.",
                "5. W Z3/PZ3 budujesz dataset znaków. Ten dataset trafia dalej do Z4/PZ1 jako źródło wariantu treningowego.",
            ],
        )

        self._section(widget, "Ground truth i nazwy plików")
        self._paragraph(
            widget,
            "Dla znaków bardzo ważna jest nazwa pliku obrazu wejściowego. Z niej aplikacja potrafi wyciągać oczekiwany tekst tablicy, "
            "czyli ground truth używany później do oceny OCR, YOLO, hybrydy i perfectów.",
        )
        self._code_block(
            widget,
            "Przykłady nazw:\n"
            "PO12345_001.jpg\n"
            "DW5AB12_007.jpg\n"
            "PO12345_DW5AB12_008.jpg",
        )
        self._bullet_list(
            widget,
            [
                "Jeżeli nazwy są niespójne, aplikacja może technicznie działać, ale ocena jakości znaków będzie myląca.",
                "Jeden katalog zdjęć wejściowych powinien mieć jedną konwencję nazewnictwa.",
                "Najczytelniej trzymać katalogi zdjęć wejściowych w Workspace/1_raw_images/<nazwa_katalogu>/.",
            ],
        )

        self._section(widget, "Kiedy artefakt jest roboczy, a kiedy trwały")
        self._bullet_list(
            widget,
            [
                "Robocze są stany miniflow, ścieżki tymczasowe, overlaye postępu i niewyeksportowane wyniki procesu.",
                "Trwałe są zapisane XML, zatwierdzone eksporty, gotowe datasety, warianty splitu, runy treningowe i checkpointy modeli.",
                "Wyjście do wyboru toru albo jawne zakończenie pracy powinno czyścić kontekst roboczy, ale nie usuwać już wyeksportowanych artefaktów.",
                "Jeżeli po powrocie widzisz starą ścieżkę albo stary dataset w miejscu nowego flow, to prawdopodobnie trzeba szukać wycieku stanu.",
            ],
        )

        self._section(widget, "Słownik najczęstszych pojęć")
        self._bullet_list(
            widget,
            [
                "Artefakt: plik lub katalog wyprodukowany przez aplikację, np. XML, cropy, dataset, split albo model .pt.",
                "Crop: wycięty fragment obrazu, zwykle sama tablica przygotowana do OCR lub detekcji znaków.",
                "Box: prostokąt obiektu, np. pojazdu albo znaku. Box pojazdu wspiera detekcję tablic, ale nie powinien trafiać do finalnego YOLO tablic.",
                "Polygon: wielopunktowy obrys tablicy używany w Z2 i w YOLO Pose tablic.",
                "Dataset: uporządkowany zestaw images/labels z plikiem data.yaml albo innym manifestem wymaganym przez dany proces.",
                "Split: podział datasetu na train, val i test. Test może być pusty, jeśli świadomie przesuniesz wszystko do train/val.",
                "Checkpoint: zapisany model, zwykle plik .pt, używany do autoanotacji, walidacji albo dalszego treningu.",
                "CVAT: zewnętrzne narzędzie do ręcznej korekty anotacji. W Z3 eksport review pack i import poprawek muszą być ze sobą zgodne.",
            ],
        )

        self._callout(
            widget,
            "Ważne:",
            "Jeżeli nie wiesz, gdzie jesteś, patrz na nazwę zakładki, podzakładkę i cel aktualnej karty. Z5 opisuje aktualny model pracy: cienki Wizard, mocne zakładki robocze i jawne artefakty między etapami.",
            "WARN",
        )

        self._disable(widget)

    def _fill_campaign(self, widget):
        self._clear_and_enable(widget)

        widget.insert(tk.END, "Kampania i iteracje Z1\n", "H1")
        self._paragraph(
            widget,
            "Kampania jest trybem uporządkowanym. Jej celem nie jest maksymalna swoboda, tylko powtarzalny proces: "
            "ten sam zestaw zdjęć iteracji, jasny tor iteracji, kontrolowane bramki i czytelna decyzja, kiedy artefakt może iść dalej.",
        )

        self._section(widget, "Rola Wizarda")
        self._bullet_list(
            widget,
            [
                "Wizard jest nawigatorem i strażnikiem stanu kampanii.",
                "Wizard nie powinien dublować pełnego UI Z2, Z3 ani Z4.",
                "Wizard otwiera właściwą zakładkę roboczą, odbiera status i zapisuje decyzje iteracji.",
                "Jeżeli zakładka robocza i Wizard pokazują coś innego, źródłem prawdy jest stan kampanii oraz trwałe artefakty projektu.",
            ],
        )

        self._section(widget, "E1. Katalog zdjęć wejściowych")
        self._bullet_list(
            widget,
            [
                "E1 wybiera i zatwierdza katalog zdjęć albo manifestowy zestaw obrazów iteracji.",
                "Samo istnienie plików w katalogu nie oznacza jeszcze, że E1 jest zamknięte.",
                "Po zatwierdzeniu E1 kolejne kroki powinny korzystać z tego samego zestawu zdjęć, chyba że użytkownik jawnie zacznie nową iterację.",
                "Histogram i podgląd puli pomagają ocenić materiał, ale nie zastępują decyzji użytkownika.",
            ],
        )

        self._section(widget, "E2. Tablice i wybór toru")
        self._paragraph(
            widget,
            "E2 ustala, czy iteracja idzie torem tablic, czy torem znaków. Ten wybór ma konsekwencje dla Z3 i Z4, dlatego po zatwierdzeniu nie powinien być swobodnie przełączany w połowie pracy.",
        )
        self._bullet_list(
            widget,
            [
                "Tor tablic: celem jest poprawny zbiór anotacji tablic i późniejszy trening modelu YOLO Pose tablic.",
                "Tor znaków: tablice z Z2 są materiałem wejściowym do Z3, gdzie powstaje dataset znaków.",
                "Z2 może startować ręcznie albo przez autoanotację. W autoanotacji wybór modelu tablic następuje w modalu startowym.",
                "Domknięcie E2 powinno opierać się na zatwierdzonych anotacjach, a nie na samym fakcie uruchomienia procesu.",
            ],
        )

        self._section(widget, "E3. Znaki")
        self._bullet_list(
            widget,
            [
                "E3 występuje tylko w torze znaków.",
                "Z3/PZ1 bierze tablice z Z2 i tworzy cropy tablic.",
                "Z3/PZ2 pozwala przejrzeć znaki, OCR, YOLO, hybrydę i ręczne poprawki.",
                "Z3/PZ3 odpowiada za review pack do CVAT, import poprawek i budowę datasetu znaków.",
                "Jeżeli zmieniło się źródło tablic w Z2, stary preview-run znaków może być nieaktualny i trzeba wrócić do PZ1.",
            ],
        )

        self._section(widget, "E4T/E4Z. Dataset, trening i model")
        self._bullet_list(
            widget,
            [
                "W torze tablic E4T pracuje na zatwierdzonym materiale tablic z projektu.",
                "W torze znaków E4Z pracuje na datasecie znaków z Z3/PZ3.",
                "Z4/PZ1 przygotowuje lub wybiera wariant datasetu. Z4/PZ2 uruchamia trening i analizuje wyniki.",
                "Promocja modelu do projektu jest osobną decyzją. Dobry wynik treningu nie powinien automatycznie zamykać iteracji.",
                "Po przejściu z Z2 do Z4 po eksporcie kontekst Z2 powinien być wyczyszczony, a Z4 powinno dostać gotowy, konkretny dataset.",
            ],
        )

        self._section(widget, "Powroty i poprawki")
        self._bullet_list(
            widget,
            [
                "Powrót do wcześniejszej zakładki jest dozwolony, ale powinien być jawny i zrozumiały dla użytkownika.",
                "Jeżeli poprawiasz Z2 po tym, jak Z3 już wycięło tablice, rozważ przebudowanie PZ1 w Z3.",
                "Jeżeli poprawiasz dataset po treningu, traktuj go jako nowy wariant, a nie cichą podmianę starego wyniku.",
                "Jeżeli zamykasz miniflow albo wracasz do wyboru toru, stan roboczy powinien zostać wyczyszczony.",
            ],
        )

        self._section(widget, "Co powinno być widoczne dla użytkownika")
        self._bullet_list(
            widget,
            [
                "Cel minimum: ile anotacji, cropów albo elementów brakuje do odblokowania kolejnej bramki.",
                "Status źródeł: czy XML, obrazy, dataset, split i model są zgodne z aktualnym torem.",
                "Skutek akcji: czy przycisk tylko wybiera ścieżkę, czy rzeczywiście ładuje, kopiuje, eksportuje albo trenuje.",
                "Ryzyko wyjścia: modal powinien ostrzec przed utratą stanu roboczego albo brakiem wymaganego minimum.",
            ],
        )

        self._section(widget, "Źródła prawdy kampanii")
        self._bullet_list(
            widget,
            [
                "campaigns_registry.json: lista projektów i podstawowy stan aktywnego projektu.",
                "9_projects/<projekt>/_campaign_state: lokalny stan kampanii, iteracji, toru i bramek.",
                "ApprovedSet tablic: zatwierdzony materiał tablic dla projektu.",
                "Dataset znaków z Z3/PZ3: materiał wejściowy dla toru znaków w Z4.",
                "Checkpoint modelu projektu: aktywny model używany jako punkt startu kolejnych iteracji.",
            ],
        )

        self._callout(
            widget,
            "Uwaga:",
            "Tryb kampanii ma prawo być mniej elastyczny niż tryb swobodny. To nie wada, tylko zabezpieczenie przed mieszaniem źródeł, runów i splitów z różnych etapów.",
            "WARN",
        )

        self._disable(widget)

    def _fill_architecture(self, widget):
        self._clear_and_enable(widget)

        widget.insert(tk.END, "Architektura danych, Workspace i stabilizacja\n", "H1")
        self._paragraph(
            widget,
            f"{CONFIG.APP_NAME} pracuje na globalnym Workspace oraz na katalogach projektów kampanii. "
            "Po ostatnim rozdzieleniu flow najważniejsze jest pilnowanie granic: Z2, Z3 i Z4 mogą wymieniać artefakty, "
            "ale nie powinny ukrycie przejmować swoich stanów roboczych.",
        )

        self._section(widget, "Globalny Workspace")
        self._code_block(
            widget,
            "Workspace/\n"
            "|-- 1_raw_images/\n"
            "|-- 2_auto_annotations/\n"
            "|-- 3_cropped_characters/\n"
            "|-- 4_training_datasets/\n"
            "|   |-- plates/\n"
            "|   |-- chars_yolo/\n"
            "|   `-- chars_ocr/\n"
            "|-- 5_training_runs/\n"
            "|-- 6_models/\n"
            "|-- 7_rankings/\n"
            "|-- 8_ocr_presets/\n"
            "`-- 9_projects/\n",
        )
        self._paragraph(
            widget,
            "Nazwy katalogów 1-9 są częścią stałego drzewa Workspace. Tryb swobodny najczęściej korzysta z globalnego drzewa, "
            "a tryb kampanii powinien preferować katalog konkretnego projektu.",
        )

        self._section(widget, "Workspace projektu")
        self._code_block(
            widget,
            "Workspace/9_projects/<projekt>/\n"
            "|-- 1_raw_images/\n"
            "|-- 2_auto_annotations/\n"
            "|-- 3_cropped_characters/\n"
            "|-- 4_training_datasets/\n"
            "|-- 5_training_runs/\n"
            "|-- _campaign_state/\n"
            "`-- _staging/\n",
        )
        self._bullet_list(
            widget,
            [
                "Katalog projektu izoluje iteracje kampanii od globalnych eksperymentów.",
                "_staging przechowuje materiał roboczy przed zatwierdzeniem.",
                "_campaign_state przechowuje decyzje i wskaźniki, których nie powinien nadpisywać pojedynczy widget.",
            ],
        )

        self._section(widget, "Najważniejsze artefakty")
        self._bullet_list(
            widget,
            [
                "annotations.xml: wynik Z2, czyli anotacje tablic powiązane z konkretnym folderem obrazów.",
                "Run Z2: katalog pracy tablic, lista obrazów, XML i metadane procesu anotacji.",
                "Run wycinania Z3/PZ1: cropy tablic przygotowane z pary XML + obrazy.",
                "metadata.json Z3: statusy cropów, wyniki OCR/YOLO/hybrydy, perfecty, poprawki i dane do eksportów.",
                "Review pack CVAT: zestaw eksportowany z Z3/PZ3 do ręcznej korekty poza aplikacją.",
                "Dataset YOLO: folder images/labels z data.yaml, gotowy do Z4.",
                "training_history.json: historia runów treningowych dla danego obszaru treningu.",
                "Checkpoint .pt: wynik treningu albo model startowy używany do dalszej pracy.",
            ],
        )

        self._section(widget, "Relacje Z2-Z3-Z4")
        self._bullet_list(
            widget,
            [
                "Z2 produkuje XML tablic i ewentualnie dataset tablic.",
                "Z3 konsumuje XML tablic oraz obrazy, produkuje cropy tablic i dataset znaków.",
                "Z4 konsumuje gotowy dataset tablic albo znaków i produkuje run treningowy oraz checkpoint modelu.",
                "Przejście między zakładkami powinno przekazywać artefakt, nie cały stan ekranu poprzedniej zakładki.",
                "Jeżeli użytkownik zmienia źródło, wariant albo tor, niezgodne ścieżki powinny zostać wyczyszczone.",
            ],
        )

        self._section(widget, "Aktualny kierunek architektury")
        self._bullet_list(
            widget,
            [
                "Flow kampanii i flow swobodny są rozdzielane fizycznie w osobnych modułach.",
                "View modele mają opisywać treść widoku, żeby logika nie musiała bezpośrednio mieszać tekstów z layoutem.",
                "Shared UI powinno zawierać tylko wspólne klocki, nie ukryte decyzje biznesowe.",
                "Dispatcher i route state powinny odpowiadać za przejścia, a nie za budowanie całego UI.",
                "Canvas overlay jest wspólnym obiektem postępu/blokady dla procesów związanych z canvasem.",
            ],
        )

        self._section(widget, "Granice, których warto pilnować")
        self._bullet_list(
            widget,
            [
                "Z2 nie powinno zostawiać załadowanego kontekstu po przejściu do treningu.",
                "Z3/PZ2 nie powinno automatycznie zmieniać źródła PZ1 bez jawnego wyboru użytkownika.",
                "Z4/PZ2 nie powinno ręcznie podmieniać źródła datasetu, jeżeli PZ1 jest miejscem tworzenia wariantów.",
                "Tryb kampanii nie powinien korzystać z elastyczności trybu swobodnego tam, gdzie bramki E1, E2, E3 i E4T/E4Z wymagają spójności.",
                "Teksty UI powinny mówić, co użytkownik ma zrobić teraz, a nie opisywać wewnętrzną historię procesu.",
            ],
        )

        self._section(widget, "Diagnostyka problemów")
        self._bullet_list(
            widget,
            [
                "Najpierw sprawdź: aktywną zakładkę, podzakładkę, tryb F/C, tor tablic/znaków i aktualne źródło.",
                "Potem sprawdź artefakt: XML, folder obrazów, run wycinania, dataset, data.yaml albo checkpoint .pt.",
                "Jeżeli przycisk jest nieaktywny, zwykle brakuje zgodności źródła, statusu [OK], poprawnego splitu albo modelu.",
                "Jeżeli UI pokazuje starą ścieżkę, szukaj nieczyszczonego stanu miniflow albo zapamiętanego wariantu z poprzedniego wejścia.",
                "Jeżeli proces trwa długo, powinien mieć overlay albo modal postępu. Ciche lagi są błędem UX.",
            ],
        )

        self._section(widget, "Minimalny słownik plików")
        self._bullet_list(
            widget,
            [
                "XML: anotacje tablic z Z2 albo korekty CVAT zależnie od kontekstu.",
                "YAML: konfiguracja datasetu YOLO, najczęściej data.yaml.",
                "JSON: metadane procesu, manifesty, historia albo stan kampanii.",
                "PT: checkpoint modelu PyTorch/YOLO.",
                "images/labels: standardowy układ datasetu YOLO.",
                "train/val/test: podział datasetu do treningu, walidacji i końcowej oceny.",
            ],
        )

        self._callout(
            widget,
            "Nota architektoniczna:",
            "Obecny fundament jest lepszy niż wcześniej, ale stabilizacja wymaga konsekwencji: małe poprawki, jawne artefakty, czyszczone stany robocze i brak cichych skrótów między zakładkami.",
            "NOTE",
        )

        self._disable(widget)
