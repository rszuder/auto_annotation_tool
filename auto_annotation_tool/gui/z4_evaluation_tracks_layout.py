"""Układ obszaru pracy Z4/PZ3, niezależny od operacji na torach."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, font as tkfont

from .app_theme_definitions import get_runtime_palette


class EvaluationTracksLayout:
    def __init__(self, panel):
        self.panel = panel
        self.scale = max(1.0, float(panel.parent.tk.call("tk", "scaling")) / (96 / 72))
        self.form_open = False
        self._sash_user_position = None
        self._fit_job = None
        self.title_var = tk.StringVar(panel.parent, "Wybierz tor z listy")
        self.count_var = tk.StringVar(panel.parent, "Obrazy toru")
        self.lifecycle_var = tk.StringVar(panel.parent, "")
        self.audit_var = tk.StringVar(panel.parent, "")
        self.gt_var = tk.StringVar(panel.parent, "")
        self.verification_var = tk.StringVar(panel.parent, "")
        self._track_title = self.title_var.get()
        self._status_tones = ("muted", "muted", "muted", "muted")

        # Przewijanie całego obszaru jest rezerwą dla małych okien / dużego DPI.
        # Zwykle przewijają się tylko listy i zakładka szczegółów.
        self.viewport = ttk.Frame(panel.parent)
        self.viewport.pack(fill=tk.BOTH, expand=True)
        self.viewport.rowconfigure(0, weight=1)
        self.viewport.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.viewport, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vscroll = ttk.Scrollbar(self.viewport, orient=tk.VERTICAL, command=self.canvas.yview)
        self.hscroll = ttk.Scrollbar(self.viewport, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)
        self.root = ttk.Frame(self.canvas, padding=12)
        self.window_id = self.canvas.create_window(0, 0, window=self.root, anchor="nw")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self._build_header()
        self._build_form()
        self._build_body()
        self._wrapped_label(self.root, textvariable=panel.status_var).grid(
            row=4, column=0, sticky="ew", pady=(8, 0)
        )
        self.canvas.bind("<Configure>", self._schedule_fit, add="+")
        self.root.bind("<Configure>", self._schedule_fit, add="+")
        self.root.bind("<Destroy>", self._destroy, add="+")
        self.body.bind("<Configure>", self._fit_panes, add="+")
        self.body.bind("<ButtonRelease-1>", self._remember_sash, add="+")
        self._bind_scroll(self.root)
        self.canvas.bind("<MouseWheel>", self._scroll_page, add="+")
        self.viewport.apply_theme = self.apply_theme
        self.apply_theme()
        panel._apply_action_state(None)

    def px(self, value):
        return round(value * self.scale)

    def _wrapped_label(self, parent, **kwargs):
        kwargs.setdefault("style", "PanelMuted.TLabel")
        label = ttk.Label(parent, width=1, wraplength=420, justify=tk.LEFT, **kwargs)
        def resize(event):
            width = max(1, event.width)
            if int(label.cget("wraplength")) != width:
                label.configure(wraplength=width)
            self._schedule_fit()
        label.bind("<Configure>", resize, add="+")
        return label

    def _build_header(self):
        header = ttk.Frame(self.root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Eksperymenty i tory referencyjne", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self._wrapped_label(header, text="Wybierz tor, przygotuj materiał i GT, a następnie zweryfikuj i zapieczętuj.").grid(
            row=1, column=0, sticky="ew", pady=(3, 0)
        )
        ttk.Button(header, text="Odśwież", command=self.panel.refresh_tracks).grid(
            row=0, column=1, rowspan=2, padx=(12, 6)
        )
        self.new_button = ttk.Button(header, text="+ Nowy tor", command=self.toggle_form, style="Accent.TButton")
        self.new_button.grid(row=0, column=2, rowspan=2)

    def _build_form(self):
        panel = self.panel
        self.form = ttk.LabelFrame(self.root, text="Nowy tor", padding=10)
        self.form.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            self.form.columnconfigure(column, weight=2 if column == 0 else 1)
        fields = (
            ("Nazwa toru", "name_entry", ttk.Entry, dict(textvariable=panel.name_var, width=24)),
            ("Typ obiektów", "target_combo", ttk.Combobox, dict(textvariable=panel.target_var, values=panel.TARGETS, state="readonly", width=12)),
            ("Przeznaczenie", "purpose_combo", ttk.Combobox, dict(textvariable=panel.purpose_var, values=panel.PURPOSES, state="readonly", width=14)),
            ("Zakres", "scope_combo", ttk.Combobox, dict(textvariable=panel.scope_var, values=("global",), state="readonly", width=12)),
        )
        for column, (label, attr, widget_class, kwargs) in enumerate(fields):
            padding = (0, 12 if column < 3 else 0)
            ttk.Label(self.form, text=label).grid(row=0, column=column, sticky="w", padx=padding, pady=(0, 4))
            widget = widget_class(self.form, **kwargs)
            widget.grid(row=1, column=column, sticky="ew", padx=padding)
            setattr(panel, attr, widget)
        panel.purpose_combo.bind("<<ComboboxSelected>>", lambda _event: panel._sync_reservation_policy(), add="+")
        panel.name_entry.bind("<Return>", lambda _event: panel.create_draft(), add="+")
        notes = ttk.Frame(self.form)
        notes.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0), padx=(0, 12))
        notes.columnconfigure(0, weight=1)
        self._wrapped_label(notes, textvariable=panel.project_hint_var).grid(row=0, column=0, sticky="ew")
        self._wrapped_label(notes, textvariable=panel.reservation_var).grid(row=1, column=0, sticky="ew")
        self.create_button = ttk.Button(self.form, text="Utwórz DRAFT", command=panel.create_draft, style="Accent.TButton")
        self.create_button.grid(row=2, column=3, sticky="e", pady=(8, 0))
        self.form.grid_remove()

    def _build_body(self):
        panel = self.panel
        self.body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.body.grid(row=2, column=0, sticky="nsew")
        self.left = ttk.LabelFrame(self.body, text="Tory", padding=8)
        self.left.columnconfigure(0, weight=1)
        self.left.rowconfigure(0, weight=1)
        self.body.add(self.left, weight=0)
        columns = ("name", "ver", "target", "purpose", "status", "members")
        panel.tree = ttk.Treeview(
            self.left, columns=columns, displaycolumns=("name", "status"),
            show="headings", selectmode="browse", height=6,
        )
        for key, title, width in (
            ("name", "Nazwa", 145), ("ver", "Wersja", 58), ("target", "Typ", 100),
            ("purpose", "Cel", 115), ("status", "Status", 85), ("members", "Obrazy", 58),
        ):
            panel.tree.heading(key, text=title)
            panel.tree.column(key, width=self.px(width), minwidth=self.px(95 if key == "name" else width), stretch=key == "name", anchor=tk.W if key == "name" else tk.CENTER)
        self._scrollable(self.left, panel.tree)
        panel.tree.bind("<<TreeviewSelect>>", panel._on_track_selected, add="+")
        self._wrapped_label(self.left, text="Wybierz tor, aby otworzyć jego obrazy i szczegóły.").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        self.right = ttk.Frame(self.body, padding=(12, 0, 0, 0))
        self.right.columnconfigure(0, weight=1)
        self.right.rowconfigure(2, weight=1)
        self.body.add(self.right, weight=1)
        self._build_track_header()

        self.notebook = ttk.Notebook(self.right)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.images_page = ttk.Frame(self.notebook, padding=8)
        self.details_page = ttk.Frame(self.notebook, padding=8)
        self.manage_page = ttk.Frame(self.notebook, padding=10)
        for page, title in ((self.images_page, "Obrazy toru"), (self.details_page, "Szczegóły i GT"), (self.manage_page, "Zarządzanie")):
            self.notebook.add(page, text=title)
            page.columnconfigure(0, weight=1)
            page.rowconfigure(0, weight=1)

        panel.member_tree = ttk.Treeview(self.images_page, columns=("idx", "name", "source", "sha"), show="headings", selectmode="extended", height=5)
        for key, title, width in (
            ("idx", "#", 32), ("name", "Plik", 84),
            ("source", "ID źródła", 110), ("sha", "SHA-256", 144),
        ):
            panel.member_tree.heading(key, text=title)
            panel.member_tree.column(
                key, width=self.px(width), minwidth=self.px(width),
                stretch=key == "source", anchor=tk.CENTER if key == "idx" else tk.W,
            )
        self._scrollable(self.images_page, panel.member_tree)
        panel.member_tree.bind("<Configure>", self._fit_member_columns, add="+")
        panel.member_tree.bind("<<TreeviewSelect>>", lambda _event: panel._refresh_remove_images_button_state(), add="+")
        image_actions = ttk.Frame(self.images_page)
        image_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        image_actions.columnconfigure(0, weight=1)
        self._wrapped_label(image_actions, textvariable=self.count_var).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._button(image_actions, "btn_open_experiment_sources", "Katalog źródeł", panel.open_experiment_sources).grid(row=0, column=1, padx=(0, 6))
        self._button(image_actions, "btn_remove_images", "Usuń zaznaczone", panel.remove_selected_images).grid(row=0, column=2)

        panel.detail_text = tk.Text(self.details_page, width=1, height=6, wrap=tk.WORD, state=tk.DISABLED, font=("Segoe UI", 10), padx=10, pady=8, bd=0)
        self._scrollable(self.details_page, panel.detail_text, horizontal=False)
        self._build_management()
        self._build_workflow()
        self.notebook.bind("<<NotebookTabChanged>>", self._schedule_fit, add="+")

    def _build_track_header(self):
        self.track_header = ttk.Frame(self.right)
        self.track_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.track_header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(
            self.track_header, textvariable=self.title_var, width=1,
            font=("Segoe UI", 12, "bold"), anchor=tk.W,
        )
        self.title_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.title_label.bind("<Configure>", self._fit_track_title, add="+")
        self.lifecycle_badge = ttk.Label(
            self.track_header, textvariable=self.lifecycle_var,
            font=("Segoe UI", 9, "bold"), padding=(8, 3),
        )
        self.lifecycle_badge.grid(row=0, column=1, sticky="e")
        self.status_row = ttk.Frame(self.track_header)
        self.status_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.status_badges = []
        for column, variable in enumerate((self.audit_var, self.gt_var, self.verification_var)):
            badge = ttk.Label(
                self.status_row, textvariable=variable, padding=(8, 3),
                font=("Segoe UI", 9),
            )
            badge.grid(row=0, column=column, padx=(0, 6 if column < 2 else 0))
            self.status_badges.append(badge)
        self.lifecycle_badge.grid_remove()
        self.status_row.grid_remove()

    def _fit_track_title(self, _event=None):
        # Długa nazwa ma jeden wiersz; pełna nazwa pozostaje w szczegółach toru.
        available = self.title_label.winfo_width() - 2
        if available <= 0:
            return
        font = tkfont.Font(font=self.title_label.cget("font"))
        title = self._track_title
        if font.measure(title) > available:
            low, high = 0, len(title)
            while low < high:
                middle = (low + high + 1) // 2
                if font.measure(title[:middle] + "…") <= available:
                    low = middle
                else:
                    high = middle - 1
            title = title[:low].rstrip() + "…"
        self.title_var.set(title)

    def _paint_status_badges(self):
        palette = get_runtime_palette(self.panel.app)
        for badge, tone in zip((self.lifecycle_badge, *self.status_badges), self._status_tones):
            badge.configure(
                background=palette["field"],
                foreground=palette.get(tone, palette["fg"]),
            )

    def _build_management(self):
        panel = self.panel
        self.manage_page.rowconfigure(0, weight=0)
        self._wrapped_label(self.manage_page, text="Operacje na wersji toru. Dostępność zależy od jego statusu.").grid(row=0, column=0, sticky="ew", pady=(0, 10))
        actions = ttk.Frame(self.manage_page)
        actions.grid(row=1, column=0, sticky="ew")
        actions.columnconfigure((0, 1), weight=1, uniform="manage")
        for index, (attr, label, command) in enumerate((
            ("btn_integrity", "Sprawdź integralność", panel.check_integrity),
            ("btn_clone", "Nowa wersja", panel.clone_track),
            ("btn_retire", "Wycofaj tor", panel.retire_track),
            ("btn_delete_draft", "Usuń DRAFT…", panel.delete_draft),
        )):
            self._button(actions, attr, label, command).grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 6 if index % 2 == 0 else 0), pady=(0, 6))

    def _build_workflow(self):
        panel = self.panel
        self.workflow = ttk.Frame(self.root)
        self.workflow.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        groups = (
            ("1 · Uczestnicy i pula", (
                ("btn_participants", "Modele uczestniczące…", panel.select_participant_models),
                ("btn_add_images", "Dodaj obrazy…", panel.add_images),
                ("btn_audit_pool", "Audytuj pulę", panel.audit_current_pool),
            )),
            ("2 · Ground Truth", (
                ("btn_prepare_z2", "Przygotuj GT w Z2", panel.prepare_ground_truth_in_z2),
                ("btn_set_gt", "Wczytaj GT (XML)…", panel.set_ground_truth),
            )),
            ("3 · Zatwierdzenie", (
                ("btn_verify", "Zweryfikuj", panel.verify_track),
                ("btn_seal", "Zapieczętuj", panel.seal_track),
                ("btn_compare", "Porównaj modele…", panel.open_comparison),
            )),
        )
        for column, (title, buttons) in enumerate(groups):
            self.workflow.columnconfigure(column, weight=1, uniform="workflow")
            group = ttk.LabelFrame(self.workflow, text=title, padding=8)
            group.grid(row=0, column=column, sticky="nsew", padx=(0, 8 if column < 2 else 0))
            group.columnconfigure(0, weight=1)
            for row, (attr, label, command) in enumerate(buttons):
                self._button(group, attr, label, command).grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 6, 0))

    def _button(self, parent, attr, text, command):
        button = ttk.Button(parent, text=text, command=command)
        setattr(self.panel, attr, button)
        return button

    @staticmethod
    def _scrollable(parent, widget, *, horizontal=True):
        widget.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=widget.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        widget.configure(yscrollcommand=yscroll.set)
        if horizontal:
            xscroll = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=widget.xview)
            xscroll.grid(row=1, column=0, sticky="ew")
            widget.configure(xscrollcommand=xscroll.set)

    def toggle_form(self):
        self.show_form(not self.form_open)

    def show_form(self, visible):
        self.form_open = visible
        if visible:
            self.form.grid()
            self.panel.name_entry.focus_set()
            self.canvas.yview_moveto(0)
        else:
            self.form.grid_remove()
        self.new_button.configure(text="Zwiń formularz" if visible else "+ Nowy tor")
        self._schedule_fit()

    def set_track(self, track=None, *, member_count=0, audit_state=None, readiness=None):
        if track:
            self._track_title = f"{track.get('name') or 'Bez nazwy'} · v{int(track.get('version') or 0)}"
            status = str(track.get("status") or "-").upper()
            self.lifecycle_var.set(status)
            self.lifecycle_badge.grid()
            audit_status = (audit_state or {}).get("status", "MISSING")
            audit_label, audit_tone = {
                "CURRENT": ("aktualny", "success"),
                "STALE": ("nieaktualny", "warning"),
            }.get(audit_status, ("brak", "muted"))
            self.audit_var.set(f"Audyt: {audit_label}")
            gt_exists = readiness.gt_exists if readiness is not None else None
            gt_verified = readiness.gt_verified if readiness is not None else None
            self.gt_var.set("GT: zapisane" if gt_exists else "GT: brak" if gt_exists is False else "GT: —")
            self.verification_var.set(
                "Weryfikacja: gotowa" if gt_verified else
                "Weryfikacja: oczekuje" if gt_exists else "Weryfikacja: —"
            )
            self._status_tones = (
                "success" if status in {"VERIFIED", "SEALED"} else "muted",
                audit_tone,
                "success" if gt_exists else "muted",
                "success" if gt_verified else "muted",
            )
            self.status_row.grid()
            self.count_var.set(f"Obrazy: {member_count}")
        else:
            self._track_title = "Wybierz tor z listy"
            self.lifecycle_var.set("")
            self.audit_var.set("")
            self.gt_var.set("")
            self.verification_var.set("")
            self.lifecycle_badge.grid_remove()
            self.status_row.grid_remove()
            self.count_var.set("Obrazy toru")
        self._fit_track_title()
        self._paint_status_badges()
        self._schedule_fit()

    def _minimum_right_width(self):
        return self.px(420)

    def _fit_member_columns(self, event):
        # Nazwa pliku ma ograniczoną szerokość. Hash zachowuje swoje miejsce,
        # a ID źródła otrzymuje resztę również po zwężeniu panelu.
        tree = self.panel.member_tree
        available = max(1, event.width - 4)
        index_width = self.px(32)
        hash_width = self.px(144)
        remaining = available - index_width - hash_width
        name_width = max(self.px(84), min(self.px(160), round(remaining * 0.35)))
        widths = {
            "idx": index_width,
            "name": name_width,
            "source": max(self.px(110), remaining - name_width),
            "sha": hash_width,
        }
        for key, width in widths.items():
            if tree.column(key, "width") != width:
                tree.column(key, width=width)

    def _schedule_fit(self, _event=None):
        if self._fit_job is None:
            self._fit_job = self.root.after_idle(self._fit_viewport)

    def _destroy(self, event):
        if event.widget == self.root and self._fit_job is not None:
            self.root.after_cancel(self._fit_job)
            self._fit_job = None

    def _fit_viewport(self, _event=None):
        self._fit_job = None
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        content_width = max(width, self.px(230) + self._minimum_right_width() + 32, self.workflow.winfo_reqwidth() + 24)
        # Ttk zapamiętuje początkowy rozmiar paneli. Aktualizujemy wysokość po
        # zawinięciu nagłówków, aby nie zachować pustego miejsca z pierwszego pomiaru.
        body_height = max(self.left.winfo_reqheight(), self.right.winfo_reqheight())
        if int(self.body.cget("height")) != body_height:
            self.body.configure(height=body_height)
            self._schedule_fit()
        content_height = max(height, self.root.winfo_reqheight())
        size = (content_width, content_height)
        if size != getattr(self, "_content_size", None):
            self._content_size = size
            self.canvas.itemconfigure(self.window_id, width=content_width, height=content_height)
            self.canvas.configure(scrollregion=(0, 0, content_width, content_height))
        if content_height > height:
            self.vscroll.grid(row=0, column=1, sticky="ns")
        else:
            self.vscroll.grid_remove()
        if content_width > width:
            self.hscroll.grid(row=1, column=0, sticky="ew")
        else:
            self.hscroll.grid_remove()

    def _fit_panes(self, _event=None):
        width = self.body.winfo_width()
        if width <= 1:
            return
        low = self.px(220)
        high = max(low, width - self._minimum_right_width() - 6)
        current = self._sash_user_position if self._sash_user_position is not None else self.px(280)
        position = max(low, min(current, high))
        if position != self.body.sashpos(0):
            self.body.sashpos(0, position)

    def _remember_sash(self, _event=None):
        self._sash_user_position = self.body.sashpos(0)
        self._fit_panes()

    def _bind_scroll(self, widget):
        if isinstance(widget, (ttk.Treeview, tk.Text, ttk.Combobox, ttk.Entry)):
            return
        widget.bind("<MouseWheel>", self._scroll_page, add="+")
        for child in widget.winfo_children():
            self._bind_scroll(child)

    def _scroll_page(self, event):
        if event.widget.winfo_toplevel() != self.viewport.winfo_toplevel():
            return
        if self.canvas.yview() != (0.0, 1.0) and event.delta:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

    def apply_theme(self):
        palette = get_runtime_palette(self.panel.app)
        self.canvas.configure(background=palette["panel"])
        self._paint_status_badges()
        self.panel.detail_text.configure(
            background=palette["field"], foreground=palette["fg"],
            selectbackground=palette["selection_bg"], selectforeground=palette["selection_fg"],
        )
