"""Compact optional label controls for the RAW sample workspace."""
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, font as tkfont

from ..registry.sample_labels import SampleLabels, MAX_LABEL_LENGTH
from .app_theme_definitions import get_runtime_palette


def label_state(host):
    selected = host._experiment_sample_selected_sha256
    state = getattr(host, "_sample_label_state", None)
    if not isinstance(state, SampleLabels) or state.selected is not selected:
        state = host._sample_label_state = SampleLabels(selected)
    return state


def _changed(host, shas, *, rebuild=False):
    from .pz3_sample_route import refresh_sample_rows, refresh_sample_ui
    lookup = getattr(host, "_sample_actual_by_sha", None)
    if lookup is None:
        context = host._pz3_sample_selection_context
        lookup = host._sample_actual_by_sha = {
            context["sample_member_sha256"][ann.filename]: index
            for index, ann in enumerate(host.current_annotations)}
    refresh_sample_rows(host, [lookup[sha] for sha in shas if sha in lookup])
    panel = getattr(host, "_sample_labels_panel", None)
    if panel is not None and rebuild:
        panel.rebuild()
    refresh_sample_ui(host)
    host.preview_canvas.focus_set()


def add_sample_label(host, name):
    state = label_state(host)
    label_id = state.add(name)
    state.activate(label_id)
    _changed(host, (), rebuild=True)
    return label_id


def activate_sample_label(host, label_id):
    label_state(host).activate(label_id)
    from .pz3_sample_route import refresh_sample_ui
    refresh_sample_ui(host)
    # Space now acts on the image, rather than toggling the focused checkbox.
    host.preview_canvas.focus_set()


def rename_sample_label(host, label_id, name):
    _changed(host, label_state(host).rename(label_id, name), rebuild=True)


def delete_sample_label(host, label_id):
    _changed(host, label_state(host).delete(label_id), rebuild=True)


def assign_sample_label(host, label_id, actual_indices=None):
    from .pz3_sample_route import sample_context
    context = sample_context(host)
    if not context or getattr(host, "is_processing", False):
        return
    indices = host._get_selected_preview_actual_indices() if actual_indices is None else actual_indices
    shas = (context["sample_member_sha256"].get(host.current_annotations[int(i)].filename)
            for i in indices if 0 <= int(i) < len(host.current_annotations))
    _changed(host, label_state(host).assign(shas, label_id))


class LabelNameDialog(simpledialog.Dialog):
    def __init__(self, parent, state, label_id=""):
        self.state, self.label_id = state, label_id
        super().__init__(parent, "Zmień nazwę etykiety" if label_id else "Dodaj etykietę")

    def body(self, master):
        ttk.Label(master, text=f"Nazwa etykiety · maks. {MAX_LABEL_LENGTH} znaków").pack(anchor="w")
        self.entry = ttk.Entry(master, width=38)
        self.entry.pack(fill="x", pady=(6, 4))
        self.entry.insert(0, self.state.labels.get(self.label_id, ""))
        self.entry.selection_range(0, tk.END)
        self.error = ttk.Label(master, wraplength=340)
        self.error.pack(fill="x")
        return self.entry

    def buttonbox(self):
        buttons = ttk.Frame(self, padding=8)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Anuluj", command=self.cancel).pack(side="right")
        ttk.Button(buttons, text="Zapisz" if self.label_id else "Dodaj",
                   command=self.ok).pack(side="right", padx=6)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        try:
            self.result = self.state.validate_name(self.entry.get(), except_id=self.label_id)
            return True
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return False


class SampleLabelsPanel(ttk.Frame):
    def __init__(self, host, parent):
        super().__init__(parent, padding=(0, 4, 0, 6))
        self.host, self.rows = host, {}
        self.columnconfigure(0, weight=1)
        heading = ttk.Frame(self)
        heading.grid(row=0, column=0, sticky="ew", columnspan=2)
        heading.columnconfigure(0, weight=0)
        ttk.Label(heading, text="Etykiety próbki · opcjonalne",
                  font=("Segoe UI", 9, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.add_button = ttk.Button(heading, text="+ Dodaj etykietę", command=self.add,
                                     width=0, padding=(6, 2))
        self.add_button.grid(row=1, column=0, sticky="w", pady=(4, 4))
        self.active = ttk.Label(heading, text="", font=("Segoe UI", 8), anchor="e", width=1)
        self.active.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        heading.columnconfigure(1, weight=1)
        self.canvas = tk.Canvas(self, width=2, height=2, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="ew")
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.items = ttk.Frame(self.canvas)
        self.items.columnconfigure(0, weight=1)
        self.window = self.canvas.create_window(0, 0, window=self.items, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.items.bind("<Configure>", self._resize)
        self.unlabeled = ttk.Label(self, text="")
        self.unlabeled.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.menu = tk.Menu(self, tearoff=0)
        self.menu_label_id = ""
        self.menu.add_command(label="Zmień nazwę…", command=self.rename)
        self.menu.add_command(label="Usuń etykietę", command=self.delete)
        self.apply_theme()
        self.rebuild()

    def apply_theme(self):
        palette = get_runtime_palette(self.host)
        self.canvas.configure(background=palette["bg"])
        ttk.Style(self).configure("SampleLabel.TCheckbutton", font=("Segoe UI", 9))

    def _resize(self, event=None):
        width = max(1, self.canvas.winfo_width())
        self.canvas.itemconfigure(self.window, width=width)
        row_height = max((check.winfo_reqheight() for _, _, check in self.rows.values()), default=24) + 4
        self.canvas.configure(height=max(1, min(3, len(self.rows))) * row_height,
                              scrollregion=(0, 0, width, self.items.winfo_reqheight()))
        font = tkfont.Font(root=self, font=("Segoe UI", 9))
        for label_id, (_, _, check) in self.rows.items():
            text = label_state(self.host).labels[label_id]
            available = max(30, width - round(85 * float(self.tk.call("tk", "scaling")) / 1.333))
            shown = text
            while len(shown) > 1 and font.measure(shown) > available:
                shown = shown[:-2] + "…"
            check.configure(text=shown)

    def _wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def rebuild(self):
        for child in self.items.winfo_children():
            child.destroy()
        self.rows = {}
        state = label_state(self.host)
        for row, (label_id, name) in enumerate(state.labels.items()):
            active, count = tk.BooleanVar(self, False), tk.StringVar(self, "0")
            check = ttk.Checkbutton(self.items, text=name, variable=active, style="SampleLabel.TCheckbutton",
                                    command=lambda key=label_id, var=active:
                                    activate_sample_label(self.host, key if var.get() else ""))
            check.grid(row=row, column=0, sticky="ew", pady=2)
            number = ttk.Label(self.items, textvariable=count, width=5, anchor="e")
            number.grid(row=row, column=1, padx=(4, 6))
            more = ttk.Button(self.items, text="⋯", width=2, padding=0,
                              command=lambda key=label_id, widget=check: self.popup(key, widget))
            more.grid(row=row, column=2)
            for widget in (check, number, more):
                widget.bind("<Button-3>", lambda event, key=label_id: self.popup(key, event.widget), add="+")
                widget.bind("<MouseWheel>", self._wheel, add="+")
            self.rows[label_id] = (active, count, check)
        if self.rows:
            self.canvas.grid()
        else:
            self.canvas.grid_remove()
        if len(self.rows) > 3:
            self.scroll.grid(row=1, column=1, sticky="ns")
        else:
            self.scroll.grid_remove()
        self.refresh()

    def refresh(self):
        state = label_state(self.host)
        for label_id, (active, count, _) in self.rows.items():
            active.set(state.active_id == label_id)
            count.set(str(state.counts[label_id]))
        name = state.labels.get(state.active_id, "brak")
        self.active.configure(text="Aktywna: " + (name[:21] + "…" if len(name) > 22 else name))
        self.unlabeled.configure(text=f"Bez etykiety: {state.unlabeled_count}")

    def add(self):
        dialog = LabelNameDialog(self, label_state(self.host))
        if dialog.result is not None:
            add_sample_label(self.host, dialog.result)

    def popup(self, label_id, widget):
        self.menu_label_id = label_id
        try:
            self.menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty()+widget.winfo_height())
        finally:
            self.menu.grab_release()
        return "break"

    def rename(self):
        dialog = LabelNameDialog(self, label_state(self.host), self.menu_label_id)
        if dialog.result is not None:
            rename_sample_label(self.host, self.menu_label_id, dialog.result)

    def delete(self):
        state = label_state(self.host)
        if state.counts[self.menu_label_id] and not messagebox.askyesno(
            "Usunąć etykietę?", "Obrazy pozostaną w próbie i stracą tylko tę etykietę.", parent=self):
            return
        delete_sample_label(self.host, self.menu_label_id)


def build_label_menu(host, parent_menu):
    menu = tk.Menu(parent_menu, tearoff=0)

    def refresh():
        menu.delete(0, tk.END)
        state = label_state(host)
        context = host._pz3_sample_selection_context
        enabled = any(context["sample_member_sha256"].get(host.current_annotations[i].filename) in state.selected
                      for i in host._get_selected_preview_actual_indices())
        status = tk.NORMAL if enabled and not getattr(host, "is_processing", False) else tk.DISABLED
        for label_id, name in state.labels.items():
            menu.add_command(label=name, state=status,
                             command=lambda key=label_id: assign_sample_label(host, key))
        if state.labels:
            menu.add_separator()
        menu.add_command(label="Usuń etykietę", state=status,
                         command=lambda: assign_sample_label(host, ""))
    menu.configure(postcommand=refresh)
    parent_menu.add_cascade(label="Ustaw etykietę", menu=menu)
    return menu
