"""Canvas review dashboard. Presentation only; metric values are canonical."""
from __future__ import annotations

import tkinter as tk
from .mobile_canvas_ui import MetricCard, Disclosure, ScrollPane, label
from ..ranking.mobile_canvas_presentation import percent


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
        self.progress = label(self.body, "", p=p, bg=p["bg"], size=10, wrap=950)
        self.progress.pack(fill="x", padx=20, pady=(4, 3))
        self.notice = label(self.body, "", p=p, bg=p["bg"], fg=p["amber"], size=10, wrap=950)
        self.notice.pack(fill="x", padx=20, pady=(4, 3))
        self.section("GEOMETRIA MT")
        self._cards([("iou", "Pokrycie obrysów · IoU", "blue"),
                     ("nmce", "Błąd narożników · NMCE", "purple")], 2)
        self.mt_counts = label(self.body, "", p=p, bg=p["bg"], size=10, wrap=950)
        self.mt_counts.pack(fill="x", padx=20, pady=(3, 4))
        self.section("ODCZYT ZNAKÓW MZ")
        self._cards([("exact", "Poprawne pełne numery", "green"),
                     ("cer", "Błąd znaków · CER", "amber")], 2)
        self.reads = label(self.body, "", p=p, bg=p["bg"], size=10, fg=p["muted"], wrap=980)
        self.reads.pack(fill="x", padx=20, pady=(3, 7))
        technical = Disclosure(self.body, "Szczegóły postępu i wykrycia MT", p=p)
        technical.pack(fill="x", padx=18, pady=(8, 0))
        self._cards([("inspected", "Sprawdzone", "blue"), ("ready", "Gotowe do oceny", "green"),
                     ("excluded", "Nie do oceny", "purple"), ("pending", "Do sprawdzenia", "amber")], 4, host=technical.body)
        self._cards([("expected", "Oczekiwane tablice", "blue"), ("linked", "Powiązane z MT", "green"),
                     ("missed", "Pominięte przez MT", "amber"), ("false", "Fałszywe wskazania", "red")], 4, host=technical.body)
        self.detection = label(technical.body, "", p=p, bg=p["bg"], size=10, fg=p["muted"], wrap=980)
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
        for item in (self.progress, self.notice, self.mt_counts, self.reads, self.detection):
            item.bind("<Configure>", lambda e, w=item: w.configure(wraplength=max(120, e.width - 8)))
        self.bind_wheel(self)

    def section(self, text):
        label(self.body, text, p=self.p, bg=self.p["bg"], fg=self.p["muted"], size=9,
              bold=True).pack(fill="x", padx=20, pady=(12, 5))

    def _cards(self, definitions, maximum, host=None):
        grid = tk.Frame(host if host is not None else self.body, bg=self.p["bg"])
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
        n = inventory["total"]
        self.progress.configure(text=f"Postęp: sprawdzono {inventory['inspected']}/{n} · "
            f"do sprawdzenia {inventory['remaining']} · ocenialne {inventory['assessed']}")
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
        if refreshing or not d:
            for key in ("exact", "cer", "iou", "nmce", "expected", "linked", "missed", "false"):
                self.cards[key].set("—", "Przeliczanie…" if refreshing else "Brak aktualnych danych")
            self.reads.configure(text="Miary pojawią się po przeliczeniu bieżących decyzji.")
            self.detection.configure(text="")
            self.mt_counts.configure(text="Aktualizowanie oceny Canvas…" if refreshing else
                                     "Ocena Canvas niedostępna dla tej rewizji")
            return
        chars, errors = value("gt_characters"), value("text_errors")
        cer = errors / chars if chars else None
        self.cards["cer"].set(percent(cer * 100 if cer is not None else None),
            f"Operacje edycyjne / znaki GT: {errors}/{chars} · micro-CER")
        reads, exact = value("evaluated_reads"), value("exact_reads")
        self.cards["exact"].set(f"{exact}/{reads}" if reads else "—",
                               f"{reads} ocenionych odczytów MZ")
        self.cards["iou"].set(percent(value("polygon_iou_mean_pct", None)), f"n = {value('geometry_n')} par obrysów · więcej = lepiej")
        self.cards["nmce"].set(percent(value("nmce_mean_pct", None)), f"n = {value('geometry_n')} par obrysów · mniej = lepiej")
        no_read = sum(1 for row in d.get("rows", ()) if row.get("included")
                      and row.get("cer") is not None and not row.get("mz_prediction"))
        self.reads.configure(text=f"Błędne pełne odczyty: {reads - exact} · w tym brak odczytu: {no_read}\n"
            "Wyniki tylko ze sprawdzonych, ocenialnych obrazów · ocena asystowana")
        self.mt_counts.configure(text=f"Pominięte przez MT: {value('missed_plates')} · "
            f"Fałszywe wskazania: {value('false_positive_mt')} · tylko zweryfikowane ROI")
        for key, metric in (("expected", "expected_plates"), ("linked", "linked_plates"),
                            ("missed", "missed_plates"), ("false", "false_positive_mt")):
            self.cards[key].set(str(value(metric)))
        precision, recall = value("mt_precision_operator", None), value("mt_recall_operator", None)
        self.detection.configure(text=(
            f"Precyzja: {percent(precision * 100 if precision is not None else None)}   ·   "
            f"Czułość: {percent(recall * 100 if recall is not None else None)}   ·   "
            f"Oznaczone błędy operatora: {value('operator_errors')} (osobno od MT)."))
