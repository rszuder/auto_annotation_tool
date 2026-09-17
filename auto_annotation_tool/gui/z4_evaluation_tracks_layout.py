"""Układ obszaru pracy Z4/PZ3, niezależny od operacji na torach."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, font as tkfont

from .notebook_icons import notebook_tab_icon
from .app_theme_definitions import get_runtime_palette
from .pz3_workflow_view import build_pz3_workflow_view_state


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
        self.pool_summary_var = tk.StringVar(panel.parent, "")
        self.next_step_var = tk.StringVar(panel.parent, "")
        self.feedback_var = tk.StringVar(panel.parent, "")
        self.primary_action = ""
        self._has_track = False
        self.workflow_buttons = []
        self._sample_selected = False
        self._workflow_rows = None
        self._track_title = self.title_var.get()
        self._status_tones = ("muted", "muted", "muted", "muted")

        # Data can scroll in small windows; workflow actions stay below the viewport.
        self.viewport = ttk.Frame(panel.parent)
        self.viewport.pack(fill=tk.BOTH, expand=True)
        self.viewport.rowconfigure(0, weight=1)
        self.viewport.columnconfigure(0, weight=1)
        # Avoid Tk grid retaining a stale allocation for a sole 1x1 child
        # when both the workflow and feedback are hidden by the draft form.
        self.canvas = tk.Canvas(self.viewport, highlightthickness=0, width=2, height=2)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vscroll = ttk.Scrollbar(self.viewport, orient=tk.VERTICAL, command=self.canvas.yview)
        self.hscroll = ttk.Scrollbar(self.viewport, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vscroll.set, xscrollcommand=self.hscroll.set)
        self.root = ttk.Frame(self.canvas, padding=(self.px(16), self.px(16), self.px(16), 0))
        self.window_id = self.canvas.create_window(0, 0, window=self.root, anchor="nw")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self._build_header()
        self._build_form()
        self._build_body()
        self.feedback_label = self._wrapped_label(self.viewport, textvariable=self.feedback_var)
        self.feedback_label.grid(row=3, column=0, sticky="ew", padx=self.px(16), pady=(0, self.px(12)))
        self._feedback_trace = panel.status_var.trace_add("write", self._sync_feedback)
        self._sync_feedback()
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
        kwargs.setdefault("style", "PZ3.Muted.TLabel")
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
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Eksperymenty i tory referencyjne", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self._wrapped_label(header, text="Wybierz istniejący tor lub przygotuj nowy eksperyment.").grid(
            row=1, column=0, sticky="ew", pady=(3, 0)
        )
        ttk.Button(header, text="Odśwież", command=self.panel.refresh_tracks, width=0, style="PZ3.Action.TButton").grid(
            row=0, column=1, rowspan=2, padx=(12, 8)
        )
        self.new_button = ttk.Button(header, text="+ Nowy draft", command=self.toggle_form, width=0, style="PZ3.Action.TButton")
        self.new_button.grid(row=0, column=2, rowspan=2)

    def _build_form(self):
        panel = self.panel
        self.form = ttk.Frame(self.root, padding=(0, 4, 0, 12))
        self.form.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            self.form.columnconfigure(column, weight=2 if column == 0 else 1)
        fields = (
            ("Nazwa toru", "name_entry", ttk.Entry, dict(textvariable=panel.name_var, width=18)),
            ("Typ obiektów", "target_combo", ttk.Combobox, dict(textvariable=panel.target_var, values=panel.TARGETS, state="readonly", width=12)),
            ("Przeznaczenie", "purpose_combo", ttk.Combobox, dict(textvariable=panel.purpose_var, values=panel.PURPOSES, state="readonly", width=14)),
            ("Zakres", "scope_combo", ttk.Combobox, dict(textvariable=panel.scope_var, values=("global",), state="readonly", width=12)),
        )
        for column, (label, attr, widget_class, kwargs) in enumerate(fields):
            padding = (0, 12 if column < 3 else 0)
            ttk.Label(self.form, text=label, style="PZ3.Muted.TLabel").grid(row=0, column=column, sticky="w", padx=padding, pady=(0, 4))
            widget = widget_class(self.form, **kwargs)
            widget.grid(row=1, column=column, sticky="nsew", padx=padding)
            setattr(panel, attr, widget)
        panel.purpose_combo.bind("<<ComboboxSelected>>", lambda _event: panel._sync_reservation_policy(), add="+")
        panel.name_entry.bind("<Return>", lambda _event: panel.create_draft(), add="+")
        notes = ttk.Frame(self.form)
        notes.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(5, 0))
        notes.columnconfigure(0, weight=1)
        self._wrapped_label(notes, textvariable=panel.project_hint_var).grid(row=0, column=0, sticky="ew")
        self._wrapped_label(notes, textvariable=panel.reservation_var).grid(row=1, column=0, sticky="ew")
        self.create_button = ttk.Button(self.form, text="Utwórz draft", command=panel.create_draft, style="PZ3.Primary.TButton", width=0)
        self.create_button.grid(row=1, column=4, sticky="nsew", padx=(10, 0))
        self.form.grid_remove()

    def _build_body(self):
        panel = self.panel
        self.body = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.body.grid(row=2, column=0, sticky="nsew")
        self.left = ttk.Frame(self.body, padding=(0, 0, 6, 0))
        self.left.columnconfigure(0, weight=1)
        self.left.rowconfigure(0, weight=1)
        self.body.add(self.left, weight=0)
        columns = ("name", "ver", "target", "purpose", "status", "members")
        panel.tree = ttk.Treeview(
            self.left, columns=columns, displaycolumns=("name", "status"),
            show="headings", selectmode="browse", height=3, style="PZ3.Treeview",
        )
        for key, title, width in (
            ("name", "Nazwa", 145), ("ver", "Wersja", 58), ("target", "Typ", 100),
            ("purpose", "Cel", 115), ("status", "Status", 85), ("members", "Obrazy", 58),
        ):
            panel.tree.heading(key, text=title)
            panel.tree.column(key, width=self.px(width), minwidth=self.px(95 if key == "name" else width), stretch=key == "name", anchor=tk.W if key == "name" else tk.CENTER)
        self._scrollable(self.left, panel.tree)
        panel.tree.bind("<Configure>", self._fit_track_columns, add="+")
        panel.tree.bind("<<TreeviewSelect>>", panel._on_track_selected, add="+")
        self._wrapped_label(self.left, text="Wybierz tor, aby otworzyć jego obrazy i szczegóły.").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        self.right = ttk.Frame(self.body, padding=(10, 0, 0, 0))
        self.right.columnconfigure(0, weight=1)
        self.right.rowconfigure(2, weight=1)
        self.body.add(self.right, weight=1)
        self._build_track_header()

        self.notebook = ttk.Notebook(self.right)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.images_page = ttk.Frame(self.notebook, padding=6)
        self.details_page = ttk.Frame(self.notebook, padding=6)
        self.manage_page = ttk.Frame(self.notebook, padding=10)
        for page, title, icon in ((self.images_page, "Obrazy toru", "images"), (self.details_page, "Szczegóły i GT", "checklist"), (self.manage_page, "Zarządzanie", "settings")):
            self.notebook.add(page, text=title, **notebook_tab_icon(self.notebook, icon))
            page.columnconfigure(0, weight=1)
            page.rowconfigure(0, weight=1)

        self.identifiers_var = tk.BooleanVar(self.root, False)
        panel.member_tree = ttk.Treeview(self.images_page, columns=("idx", "name", "source", "sha"),
                                        displaycolumns=("idx", "name"), show="headings", selectmode="extended", height=2, style="PZ3.Treeview")
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
        image_actions = self.image_actions = ttk.Frame(self.images_page)
        image_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        image_actions.columnconfigure(0, weight=1)
        self.image_count_label = self._wrapped_label(image_actions, textvariable=self.count_var)
        self.image_count_label.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.identifiers_check = ttk.Checkbutton(image_actions, text="Identyfikatory", variable=self.identifiers_var,
                        command=self._toggle_identifiers, padding=0)
        self.identifiers_check.grid(row=0, column=1, padx=(0, 10))
        self._button(image_actions, "btn_open_experiment_sources", "Katalog źródeł", panel.open_experiment_sources).grid(row=0, column=2, padx=(0, 6))
        self._button(image_actions, "btn_remove_images", "Usuń zaznaczone", panel.remove_selected_images).grid(row=0, column=3)

        image_actions.bind("<Configure>", self._fit_image_actions, add="+")

        panel.detail_text = tk.Text(self.details_page, width=1, height=6, wrap=tk.WORD, state=tk.DISABLED, font=("Segoe UI", 10), padx=10, pady=8, bd=0)
        self._scrollable(self.details_page, panel.detail_text, horizontal=False)
        self._build_management()
        self._build_workflow()
        self.notebook.bind("<<NotebookTabChanged>>", self._schedule_fit, add="+")

    def _fit_image_actions(self, _event=None):
        actions = self.image_actions
        required = (self.px(100) + self.identifiers_check.winfo_reqwidth()
                    + self.panel.btn_open_experiment_sources.winfo_reqwidth()
                    + self.panel.btn_remove_images.winfo_reqwidth() + self.px(22))
        narrow = actions.winfo_width() < required
        if narrow == getattr(self, "_image_actions_narrow", None):
            return
        self._image_actions_narrow = narrow
        self.image_count_label.grid_configure(columnspan=2 if narrow else 1,
                                              pady=(0, 6) if narrow else 0)
        self.identifiers_check.grid_configure(column=2 if narrow else 1,
                                             columnspan=2 if narrow else 1,
                                             sticky="e", padx=0 if narrow else (0, 10),
                                             pady=(0, 6) if narrow else 0)
        self.panel.btn_open_experiment_sources.grid_configure(row=1 if narrow else 0)
        self.panel.btn_remove_images.grid_configure(row=1 if narrow else 0)

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
        for column, variable in enumerate((self.audit_var, self.gt_var)):
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
        self.workflow = ttk.Frame(self.viewport)
        self.workflow.grid(row=2, column=0, sticky="ew", padx=self.px(16), pady=(12, 12))
        self.workflow.columnconfigure(0, weight=1)
        ttk.Separator(self.workflow).grid(row=0, column=0, sticky="ew")
        self._wrapped_label(self.workflow, textvariable=self.next_step_var,
                            style="PZ3.Text.TLabel").grid(
            row=1, column=0, sticky="ew", pady=(10, 10))
        self.workflow_grid = ttk.Frame(self.workflow)
        self.workflow_grid.grid(row=2, column=0, sticky="ew")
        self.workflow_grid.columnconfigure((0, 2, 4), weight=1, uniform="pz3_steps")
        self.workflow_grid.columnconfigure((1, 3), minsize=self.px(16))
        self.workflow_groups = []
        self.workflow_titles = []
        groups = (
            ("01   Pula obrazów", (
                ("btn_participants", "Modele…", panel.select_participant_models, 1, 0, 1),
                ("btn_add_images", "Dodaj obrazy…", panel.add_images, 1, 1, 1),
                ("btn_audit_pool", "Audyt niezależności", panel.audit_current_pool, 2, 0, 2),
            )),
            ("02   Próba i GT", (
                ("btn_sample_selection", "Wybierz próbę…", panel.select_experiment_sample_in_z2, 1, 0, 2),
                ("btn_audit_sample", "Audyt próby", panel.audit_current_pool, 1, 1, 1),
                ("btn_prepare_z2", "Przygotuj GT", panel.prepare_ground_truth_in_z2, 2, 0, 1),
                ("btn_set_gt", "Wczytaj GT…", panel.set_ground_truth, 2, 1, 1),
            )),
            ("03   Zatwierdzenie", (
                ("btn_verify", "Zweryfikuj", panel.verify_track, 1, 0, 1),
                ("btn_seal", "Zapieczętuj", panel.seal_track, 1, 1, 1),
                ("btn_compare", "Porównaj modele", panel.open_comparison, 2, 0, 2),
            )),
        )
        self._workflow_specs = groups
        for index, (title, buttons) in enumerate(groups):
            group = ttk.Frame(self.workflow_grid)
            group.grid(row=0, column=index * 2, sticky="nsew")
            group.columnconfigure((0, 2), weight=1, uniform=f"pz3_actions_{index}")
            group.columnconfigure(1, minsize=self.px(6))
            self.workflow_groups.append(group)
            heading = ttk.Label(group, text=title, style="PZ3.Step.TLabel")
            heading.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
            self.workflow_titles.append(heading)
            for attr, label, command, row, column, span in buttons:
                self.workflow_buttons.append(attr)
                self._button(group, attr, label, command).grid(
                    row=row, column=column * 2, columnspan=3 if span == 2 else 1,
                    sticky="nsew", pady=(0, 6) if row == 1 else 0)
        self.pool_note = ttk.Label(self.workflow_groups[0], text="Wybrano finalną próbę",
                                   style="PZ3.Muted.TLabel", anchor=tk.CENTER)
        self.pool_note.grid(row=2, column=0, columnspan=3, sticky="nsew")
        self.pool_note.grid_remove()
        panel.btn_audit_sample.grid_remove()

    def _fit_workflow(self, available):
        # Three columns on wide panels; aligned action rows when DPI/width
        # would otherwise force the right-hand actions off screen.
        panel = self.panel
        gap = self.px(6)
        half_buttons = ["btn_participants", "btn_add_images", "btn_prepare_z2",
                        "btn_set_gt", "btn_verify", "btn_seal"]
        if self._sample_selected:
            half_buttons += ["btn_sample_selection", "btn_audit_sample"]
        half_width = max(getattr(panel, name).winfo_reqwidth() for name in half_buttons)
        full_width = max(panel.btn_audit_pool.winfo_reqwidth(),
                         panel.btn_compare.winfo_reqwidth(),
                         panel.btn_sample_selection.winfo_reqwidth())
        rows = available < 3 * max(2 * half_width + gap, full_width) + self.px(32)
        if rows == self._workflow_rows:
            return
        self._workflow_rows = rows
        for column in range(5):
            self.workflow_grid.columnconfigure(column, weight=0, minsize=0, uniform="")
        if rows:
            self.workflow_grid.columnconfigure(0, weight=1)
        else:
            self.workflow_grid.columnconfigure((0, 2, 4), weight=1, uniform="pz3_steps")
            self.workflow_grid.columnconfigure((1, 3), minsize=self.px(16))
        title_width = max(title.winfo_reqwidth() for title in self.workflow_titles)
        for index, (_, specs) in enumerate(self._workflow_specs):
            group = self.workflow_groups[index]
            group.grid_configure(row=index if rows else 0, column=0 if rows else index*2,
                                 pady=(0, self.px(6)) if rows and index < 2 else 0)
            for column in range(9):
                group.columnconfigure(column, weight=0, minsize=0, uniform="")
            if rows:
                group.columnconfigure(0, minsize=title_width)
                group.columnconfigure(1, minsize=self.px(12))
                group.columnconfigure((2, 4, 6, 8), weight=1, uniform=f"pz3_actions_{index}")
                group.columnconfigure((3, 5, 7), minsize=gap)
            else:
                group.columnconfigure((0, 2), weight=1, uniform=f"pz3_actions_{index}")
                group.columnconfigure(1, minsize=gap)
            self.workflow_titles[index].grid_configure(
                columnspan=1 if rows else 3, pady=0 if rows else (0, 8))
            for button_index, (attr, _, _, row, column, span) in enumerate(specs):
                if rows:
                    target_column = 2 + 2*button_index
                    target_span = 3 if index != 1 and button_index == 2 else 1
                    if attr == "btn_sample_selection" and not self._sample_selected:
                        target_span = 3
                    getattr(panel, attr).grid_configure(row=0, column=target_column,
                                                       columnspan=target_span, pady=0)
                else:
                    target_span = 3 if span == 2 else 1
                    if attr == "btn_sample_selection" and self._sample_selected:
                        target_span = 1
                    getattr(panel, attr).grid_configure(
                        row=row, column=column*2, columnspan=target_span,
                        pady=(0, 6) if row == 1 else 0)
        self.pool_note.grid_configure(row=0 if rows else 2, column=6 if rows else 0,
                                      columnspan=3)
        if self._sample_selected:
            panel.btn_audit_pool.grid_remove()
        else:
            panel.btn_audit_sample.grid_remove()
            self.pool_note.grid_remove()

    def refresh_primary_action(self):
        if self._has_track and not self.form_open:
            self.workflow.grid()
        else:
            self.workflow.grid_remove()
        for attr in self.workflow_buttons:
            button = getattr(self.panel, attr)
            active = (not self.form_open and attr == self.primary_action
                      and str(button.cget("state")) != "disabled")
            button.configure(style="PZ3.Primary.TButton" if active else "PZ3.Action.TButton")
        self.new_button.configure(style="PZ3.Primary.TButton" if not self._has_track and not self.form_open else "PZ3.Action.TButton")
        self.create_button.configure(style="PZ3.Primary.TButton")

    def _button(self, parent, attr, text, command):
        button = ttk.Button(parent, text=text, command=command, width=0, style="PZ3.Action.TButton")
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
            def update_horizontal(first, last):
                xscroll.set(first, last)
                if float(first) <= 0.0 and float(last) >= 1.0:
                    xscroll.grid_remove()
                else:
                    xscroll.grid()
            widget.configure(xscrollcommand=update_horizontal)

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
        self.new_button.configure(text="Zamknij formularz" if visible else "+ Nowy draft")
        self.refresh_primary_action()
        self._schedule_fit()

    def set_track(self, track=None, *, member_count=0, audit_state=None, readiness=None,
                  workflow=None, participant_count=0):
        self._has_track = bool(track)
        self._workflow_rows = None
        if track:
            self._track_title = f"{track.get('name') or 'Bez nazwy'} · v{int(track.get('version') or 0)}"
            status = str(track.get("status") or "-").upper()
            self.lifecycle_var.set(status)
            self.lifecycle_badge.grid()
            if workflow is None:
                from ..registry.track_readiness import track_readiness
                readiness = readiness or track_readiness(
                    track, participant_count=participant_count, member_count=member_count,
                    audit_state=audit_state, gt_exists=bool(track.get("gt_relative_path")))
                workflow = build_pz3_workflow_view_state(readiness, audit_state=audit_state)
            audit_label, audit_tone = workflow.audit_label, workflow.audit_tone
            self.primary_action = workflow.primary_action
            self._sample_selected = workflow.sample_selected
            self.panel.btn_participants.configure(text=f"Modele ({participant_count})\u2026")
            self.next_step_var.set(workflow.status_text)
            self.pool_summary_var.set(f"Modele: {participant_count} wybrane  ·  Obrazy: {member_count}")
            self.panel.btn_audit_sample.configure(text="Audyt próby")
            if workflow.sample_selected:
                self.panel.btn_audit_pool.grid_remove()
                self.panel.btn_audit_sample.grid()
                self.panel.btn_sample_selection.grid_configure(columnspan=1)
                self.pool_note.grid()
            else:
                self.panel.btn_audit_pool.grid()
                self.panel.btn_audit_sample.grid_remove()
                self.panel.btn_sample_selection.grid_configure(columnspan=3)
                self.pool_note.grid_remove()
            self.audit_var.set(f"Audyt: {audit_label}")
            gt_exists = readiness.gt_exists if readiness is not None else None
            gt_verified = readiness.gt_verified if readiness is not None else None
            self.gt_var.set("Ground Truth: zweryfikowany" if gt_verified else
                            "Ground Truth: gotowy" if gt_exists else "Ground Truth: brak")
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
            self.count_var.set(f"Finalna próba: {member_count}" if workflow.sample_selected
                               else f"Obrazy: {member_count}")
        else:
            self._track_title = "Wybierz tor z listy"
            self.primary_action = ""
            self.next_step_var.set("Wybierz tor lub utwórz nowy eksperyment.")
            self.pool_summary_var.set("")
            self.panel.btn_audit_sample.grid_remove()
            self.panel.btn_audit_pool.grid()
            self.lifecycle_var.set("")
            self.audit_var.set("")
            self.gt_var.set("")
            self.verification_var.set("")
            self.lifecycle_badge.grid_remove()
            self.status_row.grid_remove()
            self.count_var.set("Obrazy toru")
        self.refresh_primary_action()
        self._fit_track_title()
        self._paint_status_badges()
        self._schedule_fit()

    def _sync_feedback(self, *_args):
        text = self.panel.status_var.get().strip()
        guidance = self.next_step_var.get()
        if guidance and text.endswith(guidance):
            text = text[:-len(guidance)].strip()
        self.feedback_var.set(text)
        if text:
            self.feedback_label.grid()
        else:
            self.feedback_label.grid_remove()
        self._schedule_fit()

    def _minimum_right_width(self):
        return self.px(360)

    def _toggle_identifiers(self):
        columns = ("idx", "name", "source", "sha") if self.identifiers_var.get() else ("idx", "name")
        self.panel.member_tree.configure(displaycolumns=columns)
        self._fit_member_columns()

    def _fit_track_columns(self, event=None):
        tree = self.panel.tree
        available = max(1, (event.width if event is not None else tree.winfo_width()) - 4)
        status_width = self.px(72)
        tree.column("status", width=status_width, minwidth=status_width, stretch=False)
        tree.column("name", width=max(self.px(95), available-status_width), stretch=True)

    def _fit_member_columns(self, event=None):
        # W widoku identyfikatorów nazwa i hash mają ograniczoną szerokość,
        # a ID źródła otrzymuje resztę również po zwężeniu panelu.
        tree = self.panel.member_tree
        available = max(1, (event.width if event is not None else tree.winfo_width()) - 4)
        index_width = self.px(32)
        if not self.identifiers_var.get():
            tree.column("idx", width=index_width, stretch=False)
            tree.column("name", width=max(self.px(84), available - index_width), stretch=True)
            return
        tree.column("name", stretch=False)
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
        if event.widget == self.root:
            self.panel.status_var.trace_remove("write", self._feedback_trace)
        if event.widget == self.root and self._fit_job is not None:
            self.root.after_cancel(self._fit_job)
            self._fit_job = None

    def _fit_viewport(self, _event=None):
        self._fit_job = None
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if self.workflow.winfo_manager():
            self._fit_workflow(width - self.px(32))
        action_width = self.workflow.winfo_reqwidth() if self.workflow.winfo_manager() else 0
        form_width = self.form.winfo_reqwidth() if self.form_open else 0
        content_width = max(width, self.px(190) + self._minimum_right_width() + self.px(32) + 6,
                            action_width + self.px(32), form_width + self.px(32))
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
        low = self.px(180)
        high = max(low, width - self._minimum_right_width() - 6)
        current = self._sash_user_position if self._sash_user_position is not None else self.px(248)
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
        style = ttk.Style(self.root)
        surface = palette["bg"]
        for name, color in (("Text", palette["fg"]), ("Muted", palette["muted"]),
                            ("Step", palette["fg"])):
            style.configure(f"PZ3.{name}.TLabel", background=surface, foreground=color,
                            font=("Segoe UI", 9, "bold") if name == "Step" else ("Segoe UI", 9),
                            padding=0)
        # All button states share geometry, including the filled primary action.
        for name, primary in (("Action", False), ("Primary", True)):
            key = f"PZ3.{name}.TButton"
            fill = palette["accent"] if primary else palette["panel_alt"]
            text = palette["accent_text"] if primary else palette["fg"]
            outline = palette["accent"] if primary else palette["border"]
            style.configure(key, background=fill, foreground=text,
                            bordercolor=outline, lightcolor=outline, darkcolor=outline,
                            borderwidth=1, relief="solid", anchor=tk.CENTER,
                            font=("Segoe UI", 9), padding=(self.px(10), self.px(5)))
            style.map(key,
                      background=[("disabled", surface),
                                  ("pressed", palette["accent_hover"] if primary else palette["selection_bg"]),
                                  ("active", palette["accent_hover"] if primary else palette["button_hover"])],
                      foreground=[("disabled", palette["muted"]), ("!disabled", text)],
                      **{part: [("disabled", palette["panel_border"]),
                                ("active", palette["accent"]), ("!active", outline)]
                         for part in ("bordercolor", "lightcolor", "darkcolor")})
        style.configure("PZ3.Treeview", rowheight=self.px(25), borderwidth=1, relief="solid")
        style.configure("PZ3.Treeview.Heading", font=("Segoe UI", 9, "bold"),
                        padding=(self.px(8), self.px(5)), borderwidth=1, relief="flat",
                        background=palette["panel_alt"], foreground=palette["fg"])
        self.canvas.configure(background=surface)
        self._paint_status_badges()
        self.panel.detail_text.configure(
            background=palette["field"], foreground=palette["fg"],
            selectbackground=palette["selection_bg"], selectforeground=palette["selection_fg"],
        )
