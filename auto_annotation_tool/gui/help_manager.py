#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontekstowy System Pomocy - Smooth Hover Edition
Aktualizuje pasek informacyjny na dole aplikacji podczas najeżdżania na kontrolki
oraz obsługuje F1 / prawy klik dla dłuższej pomocy.
"""

import tkinter as tk
from tkinter import messagebox
from ..config import logger


HELP_DATABASE = {
    "btn_wycinanie_start": {
        "tooltip": "Wycina i prostuje tablice ze zdjęć.",
        "full_help": "Ten przycisk uruchamia generator wyciętych tablic. Program odczytuje annotations.xml, znajduje polygony tablic, wycina je z dużych zdjęć pojazdów, prostuje perspektywę i zapisuje do nowego folderu run_XXX."
    },
    "btn_fast_test": {
        "tooltip": "Uruchamia szybki test obecnych ustawień OCR/YOLO.",
        "full_help": "Program uruchamia wybraną metodę rozpoznawania (OCR, YOLO lub BOTH) na całej bieżącej paczce wyciętych tablic, porównuje wyniki z nazwami plików źródłowych i oblicza True Accuracy."
    },
    "btn_rank_presets": {
        "tooltip": "Testuje wszystkie zapisane presety OCR i tworzy ranking.",
        "full_help": "Każdy zapisany preset z folderu 8_ocr_presets zostaje uruchomiony na obecnej paczce tablic. Program mierzy ich skuteczność i zapisuje wyniki do ranking_cache.json."
    },
    "lab_angle": {
        "tooltip": "Ręczna korekta kąta obrotu tablicy.",
        "full_help": "Jeśli tablica po wycięciu jest lekko przekrzywiona, tym suwakiem możesz wymusić obrót o kilka stopni. To często bardzo pomaga OCR-owi."
    },
    "lab_height": {
        "tooltip": "Wysokość obrazu wejściowego dla OCR.",
        "full_help": "OCR działa najlepiej na tekście o określonej wielkości. Zbyt mały obraz powoduje utratę detali, zbyt duży spowalnia działanie i może generować artefakty."
    },
    "lab_clip": {
        "tooltip": "Odcinanie prześwietleń i odblasków.",
        "full_help": "Piksele jaśniejsze od ustawionego progu są zamieniane na białe. Pomaga to usuwać refleksy, odblaski i przepalenia z tablic."
    },
    "lab_denoise": {
        "tooltip": "Siła usuwania szumu.",
        "full_help": "Redukuje cyfrowe ziarno i szum matrycy aparatu. Uważaj: zbyt duża wartość może rozmywać cienkie linie liter."
    },
    "lab_clahe": {
        "tooltip": "Lokalne wzmacnianie kontrastu (CLAHE).",
        "full_help": "Bardzo przydatne w przypadku tablic częściowo zacienionych albo słabo oświetlonych. Wyrównuje kontrast lokalny i wydobywa litery z tła."
    },
    "lab_block": {
        "tooltip": "Rozmiar bloku dla adaptive threshold.",
        "full_help": "To parametr binaryzacji adaptacyjnej. Musi być liczbą nieparzystą. Mniejsze wartości lepiej działają na małych detalach, większe na nierównym oświetleniu."
    },
    "lab_c": {
        "tooltip": "Stała C dla adaptive threshold.",
        "full_help": "Reguluje, jak agresywnie binaryzacja uznaje piksele za czarne lub białe. To jeden z najważniejszych parametrów strojenia OCR."
    },
    "lab_erode": {
        "tooltip": "Pogrubianie liter przez morfologię.",
        "full_help": "Działa jak lekkie 'domknięcie' cienkich lub popękanych znaków. Może pomóc na słabo kontrastowych tablicach, ale przesada zniszczy kształt liter."
    },
    "btn_export_cvat": {
        "tooltip": "Tworzy paczkę ZIP do poprawy w CVAT.",
        "full_help": "Program wyeksportuje wyłącznie błędne tablice (jeśli Smart Export jest włączony), przygotuje XML oraz obrazy i spakuje całość do ZIP gotowego do zaimportowania w CVAT."
    },
    "btn_export_yolo": {
        "tooltip": "Buduje mega-dataset YOLO z perfekcyjnych odczytów.",
        "full_help": "Program skanuje wszystkie run_XXX i zbiera tylko tablice oznaczone jako perfect. Z nich tworzy gotowy dataset YOLO Detect do treningu modelu rozpoznawania znaków."
    }
}


class ToolTip:
    """Rysuje małą chmurkę po najechaniu myszką."""
    def __init__(self, widget, text, delay=300):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tipwindow = None
        self.after_id = None

    def schedule_show(self):
        self.cancel()
        self.after_id = self.widget.after(self.delay, self.show_tip)

    def cancel(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def show_tip(self):
        if self.tipwindow or not self.text:
            return

        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8

            self.tipwindow = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tw.attributes("-topmost", True)

            label = tk.Label(
                tw,
                text=self.text,
                justify=tk.LEFT,
                background="#fff8c6",
                relief=tk.SOLID,
                borderwidth=1,
                font=("Segoe UI", 9)
            )
            label.pack(ipadx=6, ipady=3)
        except Exception:
            pass

    def hide_tip(self):
        self.cancel()
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class HelpSystem:
    """
    Zarządza kontekstową pomocą:
    - hover -> pasek pomocy + tooltip
    - F1 -> dłuższa pomoc
    - prawy klik -> dłuższa pomoc
    """
    def __init__(self):
        self.db = HELP_DATABASE
        self.status_updater = None
        self.current_hover_key = None
        self.is_f1_bound = False

    def _bind_global_f1(self, widget):
        """Podpina F1 do głównego okna aplikacji tylko raz."""
        if self.is_f1_bound:
            return
        try:
            root = widget.winfo_toplevel()
            root.bind("<F1>", self._trigger_f1_help)
            self.is_f1_bound = True
        except Exception as e:
            logger.debug(f"Nie udało się podpiąć F1: {e}")

    def _trigger_f1_help(self, event=None):
        """Pokazuje pełną pomoc dla aktualnie najechanego elementu."""
        if self.current_hover_key and self.current_hover_key in self.db:
            entry = self.db[self.current_hover_key]
            full_text = entry.get("full_help", "")
            if full_text:
                messagebox.showinfo(f"Pomoc: {self.current_hover_key}", full_text)
                return "break"

    def bind_help(self, widget, index_key: str):
        """Podpina pomoc do konkretnego widgetu."""
        if index_key not in self.db:
            return

        entry = self.db[index_key]
        tooltip_text = entry.get("tooltip", "")
        full_text = entry.get("full_help", "")

        tooltip = ToolTip(widget, tooltip_text)

        def on_enter(event=None):
            self.current_hover_key = index_key
            if self.status_updater and full_text:
                self.status_updater(f"💡 {full_text}")
            tooltip.schedule_show()

        def on_leave(event=None):
            if self.current_hover_key == index_key:
                self.current_hover_key = None
            if self.status_updater:
                self.status_updater("Gotowy")
            tooltip.hide_tip()

        widget.bind("<Enter>", on_enter, add="+")
        widget.bind("<Leave>", on_leave, add="+")
        widget.bind("<ButtonPress>", lambda e: tooltip.hide_tip(), add="+")

        # Prawy klik pokazuje pełny opis
        if full_text:
            widget.bind("<Button-3>", lambda e: messagebox.showinfo(f"Pomoc: {index_key}", full_text), add="+")

        # Globalne F1
        self._bind_global_f1(widget)


HELP = HelpSystem()