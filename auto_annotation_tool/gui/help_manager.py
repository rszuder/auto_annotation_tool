#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontekstowy System Pomocy - Non-intrusive Edition
Aktualizuje wyłącznie pasek informacyjny na dole aplikacji.
"""

HELP_DATABASE = {
    # --- ZAKŁADKA 1: AUTOANOTACJA ---
    "tab1_mode": {
        "full_help": "Tryb C (Pojazdy + tablice) jest najbezpieczniejszy: program zignoruje 'fałszywe' tablice (np. znaki drogowe), jeśli nie znajdują się wewnątrz wykrytego pojazdu."
    },
    "tab1_conf": {
        "full_help": "Próg pewności (Confidence): Wyższa wartość (np. 0.50) zignoruje niewyraźne obiekty. Niższa (0.20) wykryje więcej, ale może złapać śmieci."
    },
    "tab1_device": {
        "full_help": "Urządzenie obliczeniowe: 'cuda:0' używa karty graficznej (NVIDIA), co przyspiesza proces kilkukrotnie. 'cpu' używa procesora (wolniej)."
    },
    "tab1_start": {
        "full_help": "Uruchamia sztuczną inteligencję (YOLO). Przeskanuje zdjęcia, znajdzie pojazdy oraz tablice, i wygeneruje plik annotations.xml."
    },
    
    # --- ZAKŁADKA 2: WYCINANIE I ANALIZA ---
    "btn_wycinanie_start": {
        "full_help": "Wycina tablice ze zdjęć na podstawie annotations.xml. Jeśli tablica jest krzywa lub pionowa, algorytm położy ją na płasko do folderu run_XXX."
    },
    "btn_fast_test": {
        "full_help": "Szybki Test: Uruchamia OCR na obecnej paczce tablic. Jeśli odczyt zgadza się z nazwą pliku, tablica staje się 'Perfekcyjna' (🟢)."
    },
    "btn_rank_presets": {
        "full_help": "Turniej Presetów: Testuje w tle wszystkie zapisane filtry z Laboratorium. Zwycięzca (najwyższe True Accuracy) pojawi się w panelu Lidera."
    },
    "btn_lab": {
        "full_help": "Laboratorium Filtrów: Otwiera studio pre-processingu. Ustawisz tu m.in. kontrast, binaryzację i białą ramkę, co drastycznie poprawia skuteczność OCR."
    },
    "tab2_method": {
        "full_help": "Metoda odczytu: Na start używaj 'OCR'. Gdy wygenerujesz Mega-Dataset i wytrenujesz własny model w Zakładce 3, zmień na 'YOLO'."
    },
    
    # --- ZAKŁADKA 2: LABORATORIUM (Suwaki) ---
    "lab_angle": {
        "full_help": "Ręczna korekta kąta: Jeśli tablica po wycięciu jest lekko przekrzywiona, wymuś obrót o kilka stopni. To bardzo pomaga OCR-owi."
    },
    "lab_height": {
        "full_help": "Wysokość (px): Skaluje obraz przed OCR. Zbyt mały obraz traci detale, zbyt duży spowalnia działanie i generuje artefakty (Zalecane: 60-80px)."
    },
    "lab_clip": {
        "full_help": "Odcinanie odblasków: Piksele jaśniejsze od progu są zamieniane na białe. Pomaga usunąć refleksy świetlne i przepalenia z tablic."
    },
    "lab_denoise": {
        "full_help": "Usuwanie szumu: Redukuje cyfrowe ziarno matrycy. Uważaj: zbyt duża wartość może zbytnio rozmyć cienkie linie liter."
    },
    "lab_clahe": {
        "full_help": "Wzmacnianie kontrastu (CLAHE): Przydatne dla tablic w cieniu. Wyrównuje kontrast lokalny i potężnie wydobywa czarne litery z tła."
    },
    "lab_block": {
        "full_help": "Rozmiar bloku: Parametr binaryzacji. Mniejsze wartości łapią drobne detale, większe lepiej radzą sobie z nierównym oświetleniem tablicy."
    },
    "lab_c": {
        "full_help": "Stała odcięcia (C): Reguluje agresywność binaryzacji. To najważniejszy suwak do 'rozpuszczania' brudu i hologramów w białym tle!"
    },
    "lab_erode": {
        "full_help": "Erozja (Pogrubianie): Lekko 'domyka' i pogrubia popękane znaki. Przesada zniszczy i zleje litery w czarne plamy."
    },
    "lab_pad": {
        "full_help": "Biała ramka (Padding): Dodaje czysty margines. 'Oślepia' OCR na krawędziach tablicy, zapobiegając czytaniu śrubek i ramek jako liter."
    },
    "lab_conf": {
        "full_help": "Próg pewności (Confidence): Ustaw np. 0.85. Słabsze odczyty wpadną jako błędy (🔴) do ręcznej weryfikacji w CVAT, gwarantując jakość datasetu."
    },
    
    # --- ZAKŁADKA 3: INTEGRACJE (Active Learning) ---
    "btn_export_cvat": {
        "full_help": "Eksport Błędów: Pakuje do ZIP-a tylko czerwone (🔴) tablice. Wgraj je do platformy CVAT, popraw ręcznie tekst lub ramki i zaimportuj z powrotem."
    },
    "btn_export_yolo": {
        "full_help": "Mega-Dataset YOLO: Skanuje CAŁY system. Zbiera wyłącznie perfekcyjne odczyty (🟢) i buduje gotowy folder treningowy dla modelu YOLO."
    },
    "btn_import_cvat": {
        "full_help": "Aktualizacja Bazy: Wgrywa poprawiony plik XML z CVAT. Tablice, które poprawiłeś ręcznie, stają się perfekcyjne (🟢) i zasilają Mega-Dataset!"
    }
}


class HelpSystem:
    def __init__(self):
        self.db = HELP_DATABASE
        self.status_updater = None

    def bind_help(self, widget, index_key: str):
        if index_key not in self.db:
            return

        entry = self.db[index_key]
        full_text = entry.get("full_help", "")

        def on_enter(event=None):
            if self.status_updater and full_text:
                self.status_updater(f"💡 {full_text}")

        def on_leave(event=None):
            if self.status_updater:
                self.status_updater("Gotowy")

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")


HELP = HelpSystem()