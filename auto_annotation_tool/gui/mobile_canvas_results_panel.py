"""Canvas review dashboard. Presentation only; metric values are canonical."""
from __future__ import annotations

import tkinter as tk
from .mobile_canvas_ui import MetricCard, Disclosure, ScrollPane, label
from ..ranking.mobile_canvas_presentation import percent, progress_caption


class CanvasResultsPanel(ScrollPane):
    def __init__(self, parent, *, p, on_open_image=None):
        super().__init__(parent, p=p)
        self.p = p
        self.on_open_image=on_open_image;self.limit_buttons={};self._limits_signature=None
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
        self.limits_host=tk.Frame(self.body,bg=p['bg']);self.limits_host.pack(fill='x',padx=20,pady=(0,4))
        self.section("GEOMETRIA MT")
        self._cards([("iou", "Pokrycie obrysów · IoU", "blue"),
                     ("nmce", "Błąd narożników · NMCE", "purple")], 2)
        self.mt_counts = label(self.body, "", p=p, bg=p["bg"], size=10, wrap=950)
        self.mt_counts.pack(fill="x", padx=20, pady=(3, 4))
        self.mt_rates_frame=tk.Frame(self.body,bg=p['bg'])
        self.mt_rates_frame.pack(fill='x',padx=18,pady=(2,4))
        for column,key in enumerate(('precision','recall','f1')):
            self.mt_rates_frame.columnconfigure(column,weight=1,uniform='mt_rates')
            card=MetricCard(self.mt_rates_frame,{'precision':'Precision','recall':'Recall','f1':'F1'}[key],
                            p=p,tone='blue',compact=True)
            card.grid(row=0,column=column,sticky='nsew',padx=4)
            for widget in (card,card.title,card.value,card.note):widget.configure(takefocus=0)
            self.cards[key]=card
        self.section("ODCZYT ZNAKÓW MZ")
        self._cards([("exact", "Poprawne pełne numery", "green"),
                     ("cer", "Błąd znaków · CER", "amber")], 2)
        self.reads = label(self.body, "", p=p, bg=p["bg"], size=10, fg=p["muted"], wrap=980)
        self.reads.pack(fill="x", padx=20, pady=(3, 7))
        technical = Disclosure(self.body, "Szczegóły postępu i wykrycia MT", p=p)
        technical.pack(fill="x", padx=18, pady=(8, 0))
        self._cards([("inspected", "Przejrzane", "blue"), ("ready", "Zweryfikowane", "green"),
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
            "MT: źródłowe FINAL, BBOX IoU ≥ 0,50, greedy 1:1. Referencje operatora pozostają ASSISTED.",
            "Precision = TP/(TP+FP), Recall = TP/(TP+FN), F1 = 2TP/(2TP+FP+FN). Zerowy mianownik: —.",
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

    def render(self, data, inventory, *, refreshing=False, review_status=None):
        d = data or {}
        def value(key, default=0):
            return d.get(key, default)
        n = inventory["total"]
        ready=inventory.get('approval_ready',inventory['assessed']);remaining=inventory.get('approval_remaining',inventory['remaining'])
        self.progress.configure(text=f"Zweryfikowane obrazy: {ready}/{n} · Do uzupełnienia: {remaining}")
        self.cards["inspected"].set(f"{inventory['inspected']} / {n}", "w tym obrazy nie do oceny")
        self.cards["ready"].set(str(ready), "wymagane decyzje operatora zapisane")
        self.cards["excluded"].set(str(inventory["excluded"]), "sprawdzone, poza oceną")
        self.cards["pending"].set(str(remaining), "wymagają decyzji lub uzupełnienia danych")
        notices = []
        if review_status=='COMPLETED':notices.append('Weryfikacja zatwierdzona.')
        elif not remaining:notices.append('Wszystkie wymagane decyzje zapisane; można zatwierdzić weryfikację.')
        else:notices.append(f'Do uzupełnienia: {remaining} obrazów.')
        if inventory["unavailable"]:
            notices.append(f"Bez zweryfikowanej pełnej klatki/ROI: {inventory['unavailable']} — tylko podgląd.")
        from .mobile_measurement_availability import measurement_limits
        limits=measurement_limits(d,d.get('mt_detection_evaluation_v1')) if not refreshing else []
        if limits:notices.append('Nie wszystkie pomiary są dostępne. Poniżej wskazano obrazy i przyczyny.')
        signature=tuple((r['gid'],r['label'],tuple(r['reasons'])) for r in limits)
        if signature!=self._limits_signature:
            for w in self.limits_host.winfo_children():w.destroy()
            self.limit_buttons={}
            for row in limits:
                text=row['label']+': '+'; '.join(row['reasons'])
                if self.on_open_image:
                    w=tk.Button(self.limits_host,text=text+'  →',command=lambda gid=row['gid']:self.on_open_image(gid),
                        bg=self.p['bg'],fg=self.p['blue'],activebackground=self.p['bg'],activeforeground=self.p['blue'],
                        font=('Segoe UI',10),relief='flat',anchor='w',justify='left',cursor='hand2')
                else:w=label(self.limits_host,text,p=self.p,bg=self.p['bg'],size=10)
                w.pack(fill='x',pady=2);w.bind('<Configure>',lambda e:e.widget.configure(wraplength=max(160,e.width-12)))
                self.limit_buttons[row['gid']]=w
            self._limits_signature=signature
        if refreshing:
            notices.insert(0, "Przeliczanie zapisanej rewizji… Poprzednie wyniki są chwilowo ukryte.")
        self.notice.configure(text="  ".join(notices))
        if refreshing or not d:
            for key in ("exact", "cer", "iou", "nmce", "expected", "linked", "missed", "false",'precision','recall','f1'):
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
        mt_counts = (f"Pominięte przez MT: {value('missed_plates')} · "
            f"Fałszywe wskazania: {value('false_positive_mt')} · tylko zweryfikowane ROI")
        if d.get("decision_contract") == "mt_object_pose_v2":
            mt_counts += (f"\nPowiązane MT z błędem Pose: {value('pose_invalid_matches')} · "
                f"bez dowodu Pose: {value('pose_evidence_unavailable_matches')} — poza IoU/NMCE."
                f"\nJawne negatywne ROI: {value('negative_frames')} · TN (ROI): {value('true_negative_frames')} · "
                f"negatywne ROI z FP: {value('negative_frames_with_fp')}.")
        if d.get('physical_gt_contract'):
            physical_n=value('physical_gt_scene_n')
            mt_counts += (f"\nFizyczne tablice z jawnymi ID na scenach: {physical_n if physical_n is not None else 'nieustalone'}. "
                f"Obserwacje GT w wywołaniach: {value('expected_plates')}. "
                f"Starsze wywołania bez nowych ID: {value('physical_gt_legacy_invocations')}.")
        self.cards['expected'].title.configure(text='Obserwacje GT w wywołaniach' if d.get('physical_gt_contract') else 'Oczekiwane tablice')
        self.mt_counts.configure(text=mt_counts)
        mt=d.get('mt_detection_evaluation_v1') or {}
        if any(mt.get(k)!=d.get(k) for k in ('session_id','source_archive_sha256','review_revision')):
            mt={}
        for key,field,title in (('expected','n_gt','Tablice GT'),('linked','tp','Trafne MT (TP)'),
                                ('missed','fn','Pominięte (FN)'),('false','fp','Błędne MT (FP)')):
            self.cards[key].title.configure(text=title)
            self.cards[key].set(str(mt[field]) if mt.get(field) is not None else '—')
        qualified,total=mt.get('n_qualified',0),mt.get('n_total',0)
        scope=f'Pomiar MT dostępny dla {qualified}/{total} obrazów · ocena asystowana'
        if qualified:
            self.mt_counts.configure(text=f"GT {mt['n_gt']} · TP {mt['tp']} · FP {mt['fp']} · FN {mt['fn']}\n"+scope)
        else:self.mt_counts.configure(text='Ocena MT: — · brak ocenialnych wywołań\n'+scope)
        for key in ('precision','recall','f1'):
            from ..ranking.mobile_mt_detection_evaluation import format_rate
            number=mt.get(key)
            self.cards[key].set(format_rate(number))
        self.detection.configure(text=f"Oznaczone błędy operatora: {value('operator_errors')} (osobno od MT).")
