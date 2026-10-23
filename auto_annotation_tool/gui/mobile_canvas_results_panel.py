"""Canvas review dashboard. Presentation only; metric values are canonical."""
from __future__ import annotations

import tkinter as tk
from .mobile_canvas_ui import MetricCard, Disclosure, ScrollPane, label


class CanvasResultsPanel(ScrollPane):
    def __init__(self, parent, *, p):
        super().__init__(parent, p=p)
        self.p = p
        header = tk.Frame(self.body, bg=p["bg"])
        header.pack(fill="x", padx=18, pady=(16, 8))
        label(header, "Wyniki weryfikacji", p=p, bg=p["bg"], size=17, bold=True).pack(anchor="w")
        label(header, "OCENA ASYSTOWANA  ·  oryginał MT → korekta operatora", p=p,
              bg=p["blue_bg"], fg=p["blue"], size=9, bold=True).pack(anchor="w", pady=(5, 0), ipady=4, ipadx=7)
        self.grids = []
        self.cards = {}
        self.section("01  POSTĘP • WSZYSTKIE AKTYWNE WYWOŁANIA MT")
        self._cards([("inspected", "Sprawdzone", "blue"), ("ready", "Gotowe do oceny", "green"),
                     ("excluded", "Nie do oceny", "purple"), ("pending", "Do sprawdzenia", "amber")], 4)
        self.notice = label(self.body, "", p=p, bg=p["bg"], fg=p["amber"], size=10, wrap=950)
        self.notice.pack(fill="x", padx=20, pady=(4, 3))
        self.section("02  JAKOŚĆ • TYLKO SPRAWDZONE, OCENIALNE OBRAZY")
        self._cards([("cer", "Błąd znaków · CER", "amber"), ("iou", "Pokrycie obrysów · IoU", "blue"),
                     ("nmce", "Błąd narożników · NMCE", "purple")], 3)
        self.reads = label(self.body, "", p=p, bg=p["bg"], size=10, fg=p["muted"], wrap=980)
        self.reads.pack(fill="x", padx=20, pady=(3, 7))
        self.section("03  WYKRYCIE TABLIC • W TYCH SAMYCH OCENIALNYCH ROI")
        self._cards([("expected", "Oczekiwane tablice", "blue"), ("linked", "Powiązane z MT", "green"),
                     ("missed", "Pominięte przez MT", "amber"), ("false", "Fałszywe wskazania", "red")], 4)
        self.detection = label(self.body, "", p=p, bg=p["bg"], size=10, fg=p["muted"], wrap=980)
        self.detection.pack(fill="x", padx=20, pady=(4, 8))
        detail = Disclosure(self.body, "Metodyka i pliki raportu", p=p)
        detail.pack(fill="x", padx=18, pady=(8, 18))
        for text in (
            "Korekta jest potomkiem MT, a nie dodatkową tablicą. Oryginalna inferencja pozostaje niezmienna.",
            "GT dotyczy jednej ramki. CER = suma błędów / suma znaków GT; brak uruchomienia MZ nie tworzy błędu OCR.",
            "Precyzja i czułość korzystają z powiązań operatora, nie z niezależnego dopasowania po progu IoU.",
            "Usunięte próbne ramki pozostają w historii edycji, ale nie w widoku ani mianownikach oceny.",
            "Eksport: canvas_review_summary.json · canvas_review_plates.csv · canvas_review_report.md.",
        ):
            item = label(detail.body, text, p=p, size=10, wrap=980)
            item.pack(fill="x", pady=4)
            item.bind("<Configure>", lambda e, w=item: w.configure(wraplength=max(120, e.width - 8)))
        self.body.bind("<Configure>", self._reflow, add="+")
        self.bind_wheel(self)

    def section(self, text):
        label(self.body, text, p=self.p, bg=self.p["bg"], fg=self.p["muted"], size=9,
              bold=True).pack(fill="x", padx=20, pady=(12, 5))

    def _cards(self, definitions, maximum):
        grid = tk.Frame(self.body, bg=self.p["bg"])
        grid.pack(fill="x", padx=14)
        cards = []
        for key, title, tone in definitions:
            card = MetricCard(grid, title, p=self.p, tone=tone)
            self.cards[key] = card
            cards.append(card)
        self.grids.append((grid, cards, maximum))
        self._reflow()

    def _reflow(self, event=None):
        width = self.canvas.winfo_width()
        for grid, cards, maximum in self.grids:
            cols = min(maximum, max(1, width // 255))
            if getattr(grid, "_columns", None) == cols:
                continue
            grid._columns = cols
            for i in range(maximum):
                grid.columnconfigure(i, weight=1 if i < cols else 0, uniform="kpi" if i < cols else "", minsize=0)
            for i, card in enumerate(cards):
                card.grid(row=i // cols, column=i % cols, sticky="nsew", padx=4, pady=4)

    def render(self, data, inventory, *, refreshing=False):
        d = data or {}
        def value(key, default=0):
            return d.get(key, default)
        def percent(v):
            return "—" if v is None else f"{v:.2f}%".replace(".", ",")
        n = inventory["total"]
        self.cards["inspected"].set(f"{inventory['inspected']} / {n}", "w tym obrazy nie do oceny")
        self.cards["ready"].set(str(inventory["assessed"]), "komplet danych do pomiaru")
        self.cards["excluded"].set(str(inventory["excluded"]), "sprawdzone, poza oceną")
        self.cards["pending"].set(str(inventory["remaining"]), "jeszcze nieoznaczone jako sprawdzone")
        notices = []
        if inventory["incomplete"]:
            notices.append(f"Sprawdzone z brakującymi danymi: {inventory['incomplete']} — uzupełnij GT/obrys.")
        if inventory["unavailable"]:
            notices.append(f"Bez zweryfikowanej pełnej klatki/ROI: {inventory['unavailable']} — tylko podgląd.")
        if not inventory["assessed"]:
            notices.append("Brak obrazów gotowych do oceny. Kreska oznacza brak pomiaru, nie zerową skuteczność.")
        if refreshing:
            notices.insert(0, "Przeliczanie zapisanej rewizji… Poprzednie wyniki są chwilowo ukryte.")
        self.notice.configure(text="  ".join(notices))
        if refreshing:
            for key in ("cer", "iou", "nmce", "expected", "linked", "missed", "false"):
                self.cards[key].set("—", "Przeliczanie…")
            self.reads.configure(text="Miary pojawią się po przeliczeniu bieżących decyzji.")
            self.detection.configure(text="")
            return
        cer = value("cer", None)
        self.cards["cer"].set(percent(cer * 100 if cer is not None else None), f"n = {value('gt_characters')} znaków GT · mniej = lepiej")
        self.cards["iou"].set(percent(value("polygon_iou_mean_pct", None)), f"n = {value('geometry_n')} par obrysów · więcej = lepiej")
        self.cards["nmce"].set(percent(value("nmce_mean_pct", None)), f"n = {value('geometry_n')} par obrysów · mniej = lepiej")
        self.reads.configure(text=f"Całe numery zgodne z GT: {value('exact_reads')} / {value('evaluated_reads')} ocenionych odczytów MZ.")
        for key, metric in (("expected", "expected_plates"), ("linked", "linked_plates"),
                            ("missed", "missed_plates"), ("false", "false_positive_mt")):
            self.cards[key].set(str(value(metric)))
        precision, recall = value("mt_precision_operator", None), value("mt_recall_operator", None)
        self.detection.configure(text=(
            f"Precyzja: {percent(precision * 100 if precision is not None else None)}   ·   "
            f"Czułość: {percent(recall * 100 if recall is not None else None)}   ·   "
            f"Oznaczone błędy operatora: {value('operator_errors')} (osobno od MT)."))
