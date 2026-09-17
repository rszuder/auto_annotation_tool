"""Audit diagnosis and per-image decisions in one window."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

from .app_window_recovery import configure_minimizable_modal

from ..registry.audit_resolution import audit_path_key, resolve_audit
from ..registry.participant_pool_audit import (
    STATUS_CLEAN, STATUS_DEPENDENT, STATUS_SUSPECT, STATUS_UNKNOWN,
)

AUDIT_LABELS = {
    STATUS_CLEAN: "✓ Bez wykrytej zależności",
    STATUS_DEPENDENT: "⛔ Zależny",
    STATUS_SUSPECT: "⚠ Wymaga weryfikacji",
    STATUS_UNKNOWN: "? Nie można ustalić",
}


def format_audit_state(state, *, compact=False):
    status = state.get("status", "MISSING")
    label = {"CURRENT": "✓ AKTUALNY", "STALE": "⚠ NIEAKTUALNY"}.get(status, "BRAK AUDYTU")
    models = state.get("current_participant_count", state.get("participant_count", 0))
    members = state.get("current_member_count", state.get("member_count", 0))
    manual = len(state.get("accepted_suspect_sha256") or [])
    date = state.get("audited_at") or ""
    if date:
        try:
            date = datetime.fromisoformat(date).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            date = "—"
    else:
        date = "—"
    if compact:
        text = f"Audyt niezależności: {label}  ·  Modele: {models}  ·  Obrazy: {members}"
        if status == "CURRENT":
            return text + f"\nRęcznie zweryfikowane: {manual}  ·  Ostatni audyt: {date}"
        return text + "\nUżyj „Sprawdź niezależność puli” lub „Sprawdź finalną próbę”, aby sprawdzić aktualny skład."
    lines = [
        f"Audyt niezależności: {label}", f"Modele: {models}", f"Obrazy: {members}",
        f"Ostatni audyt: {date}",
    ]
    if status == "CURRENT":
        lines += ["Zależne w puli: 0", "Nieustalone w puli: 0",
                  f"Ręcznie zweryfikowane: {manual}"]
    else:
        reasons = {
            "participants_changed": "Zmieniono modele uczestniczące.",
            "members_added": "Dodano obrazy po ostatnim audycie.",
            "members_removed": "Usunięto obrazy po ostatnim audycie.",
            "previous_pool_requires_audit": "Nowe obrazy sprawdzono; wcześniejsza pula wymaga pełnego audytu.",
            "empty_pool": "Pula jest pusta.",
        }
        lines.append(reasons.get(state.get("reason"), "Aktualny skład puli wymaga audytu."))
    return "\n".join(lines)


def audit_reason_label(verdict, *, compact=False):
    """Explain a comparison without exposing its hash implementation."""
    if verdict.status == STATUS_CLEAN:
        return "Nie znaleziono zgodności z danymi modelu."
    if verdict.status == STATUS_DEPENDENT:
        return ("Ten sam obraz w danych modelu." if compact else
                "Ten sam obraz jest w danych treningowych lub walidacyjnych.")
    if verdict.status == STATUS_SUSPECT:
        return ("Podobny obraz w danych modelu." if compact else
                "Podobny do obrazu użytego przez model — sprawdź pochodzenie.")
    reason = str(verdict.reason or "").casefold()
    if "brak pliku" in reason:
        return "Brakuje pliku obrazu w zapisanej lokalizacji."
    if "odczytać obrazu" in reason:
        return "Nie można otworzyć zdjęcia. Sprawdź plik i jego format."
    if "brak obrazów referencyjnych" in reason:
        return "Brakuje zdjęć treningowych do porównania."
    if "brak zarejestrowanego" in reason:
        return "Nie zapisano, na jakich obrazach uczono model."
    if "historia" in reason or "pokrycie" in reason:
        return "Dane o treningu lub obrazy do porównania są niekompletne."
    return "Za mało danych, aby ocenić ten obraz."


class ParticipantAuditMatrixDialog:
    def __init__(self, parent, report, *, mode="pool", can_remove=True, has_ground_truth=False):
        if mode not in {"ingest", "pool"}:
            raise ValueError("Nieprawidłowy tryb audytu.")
        self.report = report
        self.mode = mode
        self.can_remove = can_remove
        self.has_ground_truth = has_ground_truth
        self.decisions = {}
        self._batch_undo = {}
        self._fit_job = None
        self.result = resolve_audit(report, cancelled=True)
        self._previous_grab = parent.grab_current()
        self._selected_index = None
        self._reference_models = []
        self._model_labels = {}
        for model in report.participants:
            label = " ".join(value for value in (model.family, model.scale) if value and value != "unknown")
            peers = [item for item in report.participants if (item.family, item.scale) == (model.family, model.scale)]
            if not label or len(peers) > 1:
                label = f"{label} · {model.model_id[-8:]}" if label else model.model_id
            self._model_labels[model.model_id] = label
        self.window = tk.Toplevel(parent)
        self.window.title("Audyt niezależności puli")
        # A transient dialog loses the native minimize/maximize buttons on Windows.
        configure_minimizable_modal(self.window)
        width = max(980, min(1280, self.window.winfo_screenwidth() - 80))
        height = max(680, min(860, self.window.winfo_screenheight() - 120))
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(980, 680)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.bind("<Destroy>", self._cancel_detail_fit, add="+")
        self.filter_var = tk.StringVar(self.window, STATUS_SUSPECT if report.suspect_count else "all")
        self.filter_caption = tk.StringVar(self.window)
        self.status_var = tk.StringVar(self.window)
        self.action_hint = tk.StringVar(self.window)
        self.reference_var = tk.StringVar(self.window)
        self.feedback_var = tk.StringVar(self.window, "Decyzje możesz zmieniać do chwili zapisania audytu.")
        self.selection_var = tk.StringVar(self.window)
        self.reason_var = tk.StringVar(self.window)
        self.decision_var = tk.StringVar(self.window)
        self._filter_labels = {
            STATUS_SUSPECT: f"Wymagające weryfikacji ({report.suspect_count})",
            "all": f"Wszystkie obrazy ({len(report.candidates)})",
            STATUS_DEPENDENT: f"Zależne od modeli ({report.dependent_count})",
            STATUS_UNKNOWN: f"Nie można ustalić ({report.unknown_count})",
            STATUS_CLEAN: f"Bez wykrytej zależności ({report.clean_count})",
        }
        self._build()
        self._populate()
        self.window.grab_set()

    @staticmethod
    def _wrapped_label(parent, **options):
        label = ttk.Label(parent, wraplength=300, justify=tk.LEFT, **options)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(80, event.width - 4)), add="+")
        return label

    def _build(self):
        root = ttk.Frame(self.window, padding=12)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)
        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Audyt niezależności puli", font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, sticky="w")
        self._wrapped_label(header, text=(
            "Sprawdź pochodzenie podobnych obrazów i wybierz, które "
            + ("dodać do puli." if self.mode == "ingest" else "pozostawić w puli.")
        )).grid(row=1, column=0, sticky="ew", pady=(3, 0))

        summary = ttk.Frame(root)
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.summary_vars = {}
        for index, (key, title) in enumerate((
            ("pending", "Do podjęcia decyzji"),
            ("accepted", "Do dodania" if self.mode == "ingest" else "Pozostają w puli"),
            ("rejected", "Do pominięcia" if self.mode == "ingest" else "Do usunięcia z puli"),
            ("total", "Wszystkie obrazy"),
        )):
            summary.columnconfigure(index, weight=1, uniform="summary")
            box = ttk.LabelFrame(summary, text=title, padding=(10, 4))
            box.grid(row=0, column=index, sticky="ew", padx=(0, 8 if index < 3 else 0))
            variable = self.summary_vars[key] = tk.StringVar(self.window)
            ttk.Label(box, textvariable=variable, font=("Segoe UI", 19, "bold")).pack(anchor="w")

        toolbar = ttk.Frame(root)
        toolbar.grid(row=2, column=0, sticky="ew")
        toolbar.columnconfigure(2, weight=1)
        ttk.Label(toolbar, text="Pokaż:").grid(row=0, column=0, padx=(0, 6))
        self.filter_combo = ttk.Combobox(toolbar, textvariable=self.filter_caption,
                                        values=list(self._filter_labels.values()), state="readonly", width=33)
        self.filter_combo.grid(row=0, column=1, sticky="w")
        self.filter_combo.bind("<<ComboboxSelected>>", self._choose_filter, add="+")
        self.reject_all_button = ttk.Button(toolbar, command=self._reject_all_suspects)
        self.reject_all_button.grid(row=0, column=3, padx=(12, 6))
        self.undo_batch_button = ttk.Button(toolbar, text="Cofnij odrzucenie grupy",
                                           command=self._undo_batch_rejection, state=tk.DISABLED)
        self.undo_batch_button.grid(row=0, column=4)
        self.feedback_label = self._wrapped_label(root, textvariable=self.feedback_var, font=("Segoe UI", 10, "bold"))
        self.feedback_label.grid(row=3, column=0, sticky="ew", pady=(6, 8))

        self.panes = ttk.Panedwindow(root, orient=tk.VERTICAL)
        self.panes.grid(row=4, column=0, sticky="nsew")
        self.panes.bind("<Configure>", self._schedule_detail_fit, add="+")
        table = ttk.Frame(self.panes)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.panes.add(table, weight=3)
        cols = ("file", "status", "model", "reason", "decision")
        self.tree = ttk.Treeview(table, columns=cols, displaycolumns=("file", "decision", "reason", "model"),
                                 show="headings", selectmode="browse", height=8)
        for key, title, width, minimum in (
            ("file", "Plik", 245, 150), ("status", "Wynik audytu", 180, 120),
            ("model", "Dotyczy modeli", 190, 180), ("reason", "Powód", 430, 230),
            ("decision", "Decyzja po zapisaniu", 220, 170),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=minimum)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.tree.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._select, add="+")

        self.detail_tabs = ttk.Notebook(self.panes)
        self.panes.add(self.detail_tabs, weight=2)
        review = ttk.Frame(self.detail_tabs, padding=8)
        review.columnconfigure(0, weight=1, uniform="review")
        review.columnconfigure(1, weight=1, uniform="review")
        review.rowconfigure(0, weight=1)
        self.detail_tabs.add(review, text="Ocena i porównanie")
        explanation = ttk.Frame(review, padding=(0, 0, 12, 0))
        explanation.grid(row=0, column=0, sticky="nsew")
        explanation.columnconfigure(0, weight=1)
        self._wrapped_label(explanation, textvariable=self.selection_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="ew")
        self._wrapped_label(explanation, textvariable=self.reason_var).grid(
            row=1, column=0, sticky="ew", pady=(5, 0))
        self._wrapped_label(explanation, textvariable=self.action_hint).grid(
            row=2, column=0, sticky="ew", pady=(5, 0))
        self._wrapped_label(explanation, textvariable=self.decision_var, font=("Segoe UI", 10, "bold")).grid(
            row=3, column=0, sticky="ew", pady=(7, 6))
        actions = ttk.Frame(explanation)
        actions.grid(row=4, column=0, sticky="w")
        self.accept_button = ttk.Button(actions, text="Pozostaw po weryfikacji" if self.mode == "pool" else "Dopuść po weryfikacji",
                                        command=self._accept_selected)
        self.accept_button.grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 5))
        self.reject_button = ttk.Button(actions, text="Odrzuć obraz", command=self._reject_selected)
        self.reject_button.grid(row=0, column=1, sticky="w", pady=(0, 5))
        self.reset_button = ttk.Button(actions, text="Cofnij decyzję", command=self._reset_selected)
        self.reset_button.grid(row=1, column=0, sticky="w")
        self.next_button = ttk.Button(actions, text="Następny bez decyzji →", command=self._next_pending)
        self.next_button.grid(row=1, column=1, sticky="w")

        previews = ttk.Frame(review)
        previews.grid(row=0, column=1, sticky="nsew")
        previews.columnconfigure((0, 1), weight=1, uniform="preview")
        previews.rowconfigure(2, weight=1)
        self.reference_combo = ttk.Combobox(previews, textvariable=self.reference_var, state="readonly", width=28)
        self.reference_combo.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.reference_combo.bind("<<ComboboxSelected>>", self._show_reference, add="+")
        ttk.Label(previews, text="Obraz z puli").grid(row=1, column=0)
        ttk.Label(previews, text="Obraz użyty przez model").grid(row=1, column=1)
        self.preview = ttk.Label(previews, anchor="center", wraplength=190)
        self.reference_preview = ttk.Label(previews, anchor="center", wraplength=190)
        self.preview.grid(row=2, column=0, sticky="nsew", padx=3)
        self.reference_preview.grid(row=2, column=1, sticky="nsew", padx=3)

        technical = ttk.Frame(self.detail_tabs, padding=8)
        technical.columnconfigure(0, weight=1)
        technical.rowconfigure(0, weight=1)
        self.detail_tabs.add(technical, text="Szczegóły techniczne")
        self.detail = tk.Text(technical, height=8, width=1, wrap=tk.WORD, state=tk.DISABLED)
        self.detail.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(technical, orient=tk.VERTICAL, command=self.detail.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=scroll.set)

        footer = ttk.Frame(root, padding=(0, 10, 0, 0))
        footer.grid(row=5, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_label = self._wrapped_label(footer, textvariable=self.status_var)
        self.status_label.grid(row=0, column=0, sticky="ew", padx=(0, 14))
        buttons = ttk.Frame(footer)
        buttons.grid(row=0, column=1, sticky="e")
        ttk.Button(buttons, text="Anuluj", command=self._cancel).pack(side=tk.LEFT, padx=(0, 8))
        self.apply_button = ttk.Button(buttons, command=self._apply, style="Accent.TButton")
        self.apply_button.pack(side=tk.LEFT)

    def _schedule_detail_fit(self, _event=None):
        if self._fit_job is None:
            self._fit_job = self.window.after_idle(self._fit_detail_pane)

    def _cancel_detail_fit(self, event):
        if event.widget is self.window and self._fit_job is not None:
            self.window.after_cancel(self._fit_job)
            self._fit_job = None

    def _fit_detail_pane(self):
        self._fit_job = None
        if not self.panes.winfo_exists() or self.panes.winfo_height() < 100:
            return
        # Keep decision buttons visible when the window is made smaller.
        detail_height = max(260, self.detail_tabs.winfo_reqheight())
        limit = max(80, self.panes.winfo_height() - detail_height - 6)
        if self.panes.sashpos(0) > limit:
            self.panes.sashpos(0, limit)

    def resolution(self):
        return resolve_audit(self.report, self.decisions)

    def _decision_label(self, candidate):
        if candidate.common_status == STATUS_CLEAN:
            return "Dodać do puli" if self.mode == "ingest" else "Pozostawić w puli"
        if candidate.common_status == STATUS_SUSPECT:
            choice = self.decisions.get(audit_path_key(candidate.path))
            return {"accept": "Dodać · po weryfikacji" if self.mode == "ingest" else "Pozostawić · po weryfikacji",
                    "reject": "Odrzucić · Twoja decyzja"}.get(choice, "Wybierz decyzję")
        return "Pominąć · automatycznie" if self.mode == "ingest" else "Usunąć · automatycznie"

    def _candidate_reason(self, candidate, *, compact=False):
        problems = [item for item in candidate.per_model if item.status != STATUS_CLEAN]
        reasons = list(dict.fromkeys(audit_reason_label(item, compact=compact) for item in problems))
        return " ".join(reasons) or "Nie znaleziono zgodności z danymi wybranych modeli."

    def _row_values(self, candidate):
        problems = [item for item in candidate.per_model if item.status != STATUS_CLEAN]
        return (
            candidate.filename, AUDIT_LABELS.get(candidate.common_status, AUDIT_LABELS[STATUS_UNKNOWN]),
            ", ".join(dict.fromkeys(self._model_labels.get(item.model_id, item.model_id) for item in problems)) or "—",
            self._candidate_reason(candidate, compact=True), self._decision_label(candidate),
        )

    def _choose_filter(self, _event=None):
        self.filter_var.set(next(key for key, label in self._filter_labels.items()
                                 if label == self.filter_caption.get()))
        self._populate()

    def _populate(self, select=None):
        previous = self.tree.selection()
        selected = str(select) if select is not None else previous[0] if previous else ""
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self.filter_caption.set(self._filter_labels[self.filter_var.get()])
        visible = []
        for index, candidate in enumerate(self.report.candidates):
            if self.filter_var.get() not in {"all", candidate.common_status}:
                continue
            iid = str(index)
            self.tree.insert("", tk.END, iid=iid, values=self._row_values(candidate))
            visible.append(iid)
        if visible:
            target = selected if selected in visible else visible[0]
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)
            self._show(int(target))
        else:
            self._selected_index = None
            self.selection_var.set("Brak obrazów w tym widoku.")
            self.reason_var.set("Wybierz inną grupę w polu „Pokaż”.")
            self.decision_var.set("")
            self._set_detail("Brak obrazów w tym filtrze.")
            self._load_preview(self.preview, None)
            self._load_preview(self.reference_preview, None)
            self._reference_models = []
            self.reference_combo.configure(values=())
            self.reference_var.set("")
        self._refresh_resolution()

    def set_decision(self, index, choice):
        candidate = self.report.candidates[index]
        if candidate.common_status != STATUS_SUSPECT:
            raise ValueError("Tylko obraz wymagający weryfikacji może być zaakceptowany ręcznie.")
        key = audit_path_key(candidate.path)
        if choice is None:
            self.decisions.pop(key, None)
        elif choice in {"accept", "reject"}:
            self.decisions[key] = choice
        else:
            raise ValueError("Nieprawidłowa decyzja.")
        self._batch_undo.pop(key, None)
        if self.tree.exists(str(index)):
            self.tree.item(str(index), values=self._row_values(candidate))
        description = {"accept": "Dopuszczono po Twojej weryfikacji", "reject": "Oznaczono do odrzucenia",
                       None: "Cofnięto decyzję"}[choice]
        self.feedback_var.set(f"{description}: {candidate.filename}. Zmiana czeka na zapis audytu.")
        self._refresh_resolution()

    def _accept_selected(self):
        if self._selected_index is not None:
            self.set_decision(self._selected_index, "accept")

    def _reject_selected(self):
        if self._selected_index is not None:
            candidate = self.report.candidates[self._selected_index]
            if candidate.common_status == STATUS_SUSPECT:
                self.set_decision(self._selected_index, "reject")

    def _reset_selected(self):
        if self._selected_index is not None:
            self.set_decision(self._selected_index, None)

    def _reject_all_suspects(self):
        pending = [(index, audit_path_key(item.path)) for index, item in enumerate(self.report.candidates)
                   if item.common_status == STATUS_SUSPECT and audit_path_key(item.path) not in self.decisions]
        if not pending:
            self.feedback_var.set("Wszystkie obrazy wymagające weryfikacji mają już decyzję.")
            return
        self._batch_undo = dict.fromkeys(key for _, key in pending)
        self.decisions.update({key: "reject" for _, key in pending})
        self.filter_var.set(STATUS_SUSPECT)
        self._populate(select=pending[0][0])
        self.detail_tabs.select(0)
        self.feedback_var.set(
            f"Oznaczono do odrzucenia: {len(pending)}. Zaktualizowano kolumnę „Decyzja po zapisaniu”. "
            "Zmiany zostaną zastosowane po zapisaniu audytu.")

    def _undo_batch_rejection(self):
        restored = 0
        for key in self._batch_undo:
            if self.decisions.get(key) == "reject":
                self.decisions.pop(key)
                restored += 1
        self._batch_undo.clear()
        self._populate()
        self.feedback_var.set(f"Cofnięto odrzucenie grupy: {restored}. Te obrazy ponownie wymagają decyzji.")

    def _next_pending(self):
        indices = [index for index, item in enumerate(self.report.candidates)
                   if item.common_status == STATUS_SUSPECT and audit_path_key(item.path) not in self.decisions]
        if indices:
            current = self._selected_index if self._selected_index is not None else -1
            target = next((index for index in indices if index > current), indices[0])
            self.filter_var.set(STATUS_SUSPECT)
            self._populate(select=target)
            self.detail_tabs.select(0)

    def _refresh_resolution(self):
        result = self.resolution()
        candidate = self.report.candidates[self._selected_index] if self._selected_index is not None else None
        suspect = candidate is not None and candidate.common_status == STATUS_SUSPECT
        choice = self.decisions.get(audit_path_key(candidate.path)) if candidate else None
        for button in (self.accept_button, self.reject_button):
            button.configure(state=tk.NORMAL if suspect else tk.DISABLED)
        self.reset_button.configure(state=tk.NORMAL if suspect and choice else tk.DISABLED)
        if candidate is None:
            hint = ""
        elif suspect:
            hint = "Samo podobieństwo nie dowodzi zależności. Pozostaw obraz dopiero po sprawdzeniu jego pochodzenia."
        elif candidate.common_status == STATUS_CLEAN:
            hint = "Ten obraz nie wymaga ręcznej decyzji."
        elif candidate.common_status == STATUS_DEPENDENT:
            hint = "Ten obraz zostanie wykluczony, ponieważ jest w danych użytych przez model."
        else:
            hint = "Obraz zostanie wykluczony. Uzupełnij brakujące dane lub popraw plik i ponów audyt."
        self.action_hint.set(hint)
        if candidate:
            self.decision_var.set("Decyzja: " + self._decision_label(candidate))
        accepted, rejected, pending = len(result.accepted_paths), len(result.rejected_paths), len(result.unresolved)
        for key, value in (("pending", pending), ("accepted", accepted), ("rejected", rejected),
                           ("total", len(self.report.candidates))):
            self.summary_vars[key].set(f"{value:,}".replace(",", " "))
        self.reject_all_button.configure(text=f"Odrzuć wszystkie bez decyzji ({pending})",
                                         state=tk.NORMAL if pending else tk.DISABLED)
        self.undo_batch_button.configure(state=tk.NORMAL if self._batch_undo else tk.DISABLED)
        self.next_button.configure(state=tk.NORMAL if pending else tk.DISABLED)
        blocked = self.mode == "pool" and rejected and not self.can_remove
        if pending:
            status = f"Do zapisania audytu brakuje decyzji: {pending}."
        elif blocked:
            status = "Tor zweryfikowany: zmienioną pulę przygotuj w nowym DRAFT."
        else:
            status = "Gotowe do zapisania." if accepted else "Wszystkie obrazy zostaną wykluczone."
        if self.mode == "ingest":
            status += f"\nDo dodania: {accepted}. Pominięte: {rejected}."
            self.apply_button.configure(text=f"Dodaj {accepted} obrazów do DRAFT" if accepted else "Zapisz wynik — brak nowych obrazów")
        else:
            status += f"\nPozostanie w torze: {accepted}. Do usunięcia z toru: {rejected}."
            if rejected and self.has_ground_truth:
                status += " Dotychczasowe GT zostanie zarchiwizowane; przygotuj je ponownie."
            self.apply_button.configure(text="Zapisz wynik audytu")
        self.status_var.set(status)
        self._schedule_detail_fit()
        self.apply_button.configure(state=tk.NORMAL if result.ready and not blocked else tk.DISABLED)

    def _select(self, _event=None):
        selected = self.tree.selection()
        if selected and int(selected[0]) != self._selected_index:
            self._show(int(selected[0]))
            self._refresh_resolution()

    def _set_detail(self, text):
        self.detail.configure(state=tk.NORMAL)
        self.detail.delete("1.0", tk.END)
        self.detail.insert("1.0", text)
        self.detail.configure(state=tk.DISABLED)

    def _show(self, index):
        self._selected_index = index
        candidate = self.report.candidates[index]
        self.selection_var.set(candidate.filename)
        self.reason_var.set(self._candidate_reason(candidate))
        lines = [f"Plik: {candidate.filename}", AUDIT_LABELS.get(candidate.common_status, AUDIT_LABELS[STATUS_UNKNOWN]), ""]
        priority = {STATUS_DEPENDENT: 0, STATUS_SUSPECT: 1, STATUS_UNKNOWN: 2, STATUS_CLEAN: 3}
        for item in sorted(candidate.per_model, key=lambda value: priority.get(value.status, 2)):
            lines += [f"Model: {item.model_id}", f"Status: {AUDIT_LABELS.get(item.status, AUDIT_LABELS[STATUS_UNKNOWN])}",
                      f"Powód: {item.reason}"]
            if item.training_run_id:
                lines.append(f"Run: {item.training_run_id}")
            if item.training_dataset_id:
                lines.append(f"Dataset: {item.training_dataset_id}")
            if item.training_split:
                lines.append(f"Split: {item.training_split}")
            if item.phash_distance is not None:
                lines.append(f"Odległość pHash: {item.phash_distance}")
            reference = item.reference_image_path or item.reference_path
            if reference:
                lines.append(f"Obraz referencyjny: {reference}")
            lines.append(f"Pokrycie porównania wyglądu: {item.phash_reference_coverage:.0%}\n")
        self._set_detail("\n".join(lines))
        self._load_preview(self.preview, candidate.path)
        self._reference_models = sorted(candidate.per_model, key=lambda item: priority.get(item.status, 2))
        self.reference_combo.configure(values=[self._model_labels.get(item.model_id, item.model_id)
                                                for item in self._reference_models])
        if self._reference_models:
            first = next((i for i, item in enumerate(self._reference_models) if item.reference_image_path), 0)
            self.reference_combo.current(first)
        else:
            self.reference_var.set("")
        self._show_reference()

    def _show_reference(self, _event=None):
        index = self.reference_combo.current()
        models = self._reference_models
        path = models[index].reference_image_path if 0 <= index < len(models) else ""
        self._load_preview(self.reference_preview, path)

    def _load_preview(self, label, path):
        label.image = None
        if not path:
            label.configure(image="", text="Brak obrazu do porównania.")
            return
        try:
            with Image.open(Path(path)) as raw:
                picture = ImageOps.exif_transpose(raw).convert("RGB")
                picture.thumbnail((215, 145))
                label.image = ImageTk.PhotoImage(picture, master=self.window)
            label.configure(image=label.image, text="")
        except (OSError, ValueError):
            label.configure(image="", text="Nie można otworzyć tego pliku jako zdjęcia.")

    def _apply(self):
        result = self.resolution()
        if not result.ready or (self.mode == "pool" and result.rejected_paths and not self.can_remove):
            self._refresh_resolution()
            return
        self.result = result
        self._close()

    def _cancel(self):
        self.result = resolve_audit(self.report, self.decisions, cancelled=True)
        self._close()

    def _close(self):
        self.window.grab_release()
        self.window.destroy()
        if self._previous_grab is not None and self._previous_grab.winfo_exists():
            self._previous_grab.grab_set()

    def show(self):
        self.window.deiconify()
        self.window.lift()
        self.window.focus_set()
        self.window.wait_window()
        return self.result
