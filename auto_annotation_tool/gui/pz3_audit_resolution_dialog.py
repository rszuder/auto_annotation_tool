"""Audit diagnosis and per-image decisions in one window."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk

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
        return text + "\nUżyj „Audytuj pulę”, aby sprawdzić aktualny skład."
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


class ParticipantAuditMatrixDialog:
    def __init__(self, parent, report, *, mode="pool", can_remove=True, has_ground_truth=False):
        if mode not in {"ingest", "pool"}:
            raise ValueError("Nieprawidłowy tryb audytu.")
        self.report = report
        self.mode = mode
        self.can_remove = can_remove
        self.has_ground_truth = has_ground_truth
        self.decisions = {}
        self.result = resolve_audit(report, cancelled=True)
        self._previous_grab = parent.grab_current()
        self._selected_index = None
        self.window = tk.Toplevel(parent)
        self.window.title("Audyt niezależności puli")
        self.window.transient(parent.winfo_toplevel())
        self.window.geometry("1280x860")
        self.window.minsize(980, 680)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.filter_var = tk.StringVar(self.window, "all")
        self.status_var = tk.StringVar(self.window)
        self.action_hint = tk.StringVar(self.window)
        self.reference_var = tk.StringVar(self.window)
        self._build()
        self._populate()
        self.window.grab_set()

    def _build(self):
        root = ttk.Frame(self.window, padding=12)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Audyt niezależności puli", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(header, text=(
            "Nowe obrazy — wybierz, które dodać do toru."
            if self.mode == "ingest" else
            "Obrazy należące do toru — sprawdź problemy i zapisz wynik audytu."
        )).pack(anchor="w", pady=(3, 8))

        summary = ttk.Frame(root)
        summary.grid(row=1, column=0, sticky="ew")
        counts = (
            ("Bez wykrytej zależności", self.report.clean_count),
            ("Zależne", self.report.dependent_count),
            ("Wymagają weryfikacji", self.report.suspect_count),
            ("Nie można ustalić", self.report.unknown_count),
        )
        for index, (title, count) in enumerate(counts):
            summary.columnconfigure(index, weight=1, uniform="summary")
            box = ttk.LabelFrame(summary, text=title, padding=5)
            box.grid(row=0, column=index, sticky="ew", padx=(0, 6 if index < 3 else 0))
            ttk.Label(box, text=str(count), font=("Segoe UI", 15, "bold")).pack()

        filters = ttk.Frame(root)
        filters.grid(row=2, column=0, sticky="ew", pady=8)
        for title, value in (
            ("Wszystkie", "all"), ("Zależne", STATUS_DEPENDENT),
            ("Do weryfikacji", STATUS_SUSPECT), ("Nie można ustalić", STATUS_UNKNOWN),
        ):
            ttk.Radiobutton(filters, text=title, value=value, variable=self.filter_var,
                            command=self._populate).pack(side=tk.LEFT, padx=(0, 12))

        panes = ttk.Panedwindow(root, orient=tk.VERTICAL)
        panes.grid(row=3, column=0, sticky="nsew")
        table = ttk.Frame(panes)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        panes.add(table, weight=3)
        cols = ("file", "status", "model", "reason", "decision")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="browse", height=9)
        for key, title, width in (
            ("file", "Plik", 205), ("status", "Status", 215),
            ("model", "Model", 170), ("reason", "Powód", 250), ("decision", "Decyzja", 190),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=90)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.tree.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._select, add="+")

        details = ttk.Frame(panes, padding=(0, 8, 0, 0))
        panes.add(details, weight=2)
        details.columnconfigure(0, weight=3)
        details.columnconfigure(1, weight=2)
        details.rowconfigure(0, weight=1)
        detail_box = ttk.LabelFrame(details, text="Model, powód i pochodzenie", padding=6)
        detail_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        detail_box.columnconfigure(0, weight=1)
        detail_box.rowconfigure(0, weight=1)
        self.detail = tk.Text(detail_box, height=9, width=1, wrap=tk.WORD, state=tk.DISABLED)
        self.detail.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(detail_box, orient=tk.VERTICAL, command=self.detail.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=scroll.set)

        previews = ttk.LabelFrame(details, text="Porównanie obrazów", padding=6)
        previews.grid(row=0, column=1, sticky="nsew")
        previews.columnconfigure((0, 1), weight=1, uniform="preview")
        self.reference_combo = ttk.Combobox(
            previews, textvariable=self.reference_var, state="readonly", width=28)
        self.reference_combo.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        self.reference_combo.bind("<<ComboboxSelected>>", self._show_reference, add="+")
        ttk.Label(previews, text="Obraz z puli").grid(row=1, column=0)
        ttk.Label(previews, text="Dane wybranego modelu").grid(row=1, column=1)
        self.preview = ttk.Label(previews, anchor="center", wraplength=180)
        self.reference_preview = ttk.Label(previews, anchor="center", wraplength=180)
        self.preview.grid(row=2, column=0, sticky="nsew", padx=3)
        self.reference_preview.grid(row=2, column=1, sticky="nsew", padx=3)

        footer = ttk.Frame(root)
        footer.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        footer.columnconfigure(0, weight=1)
        actions = ttk.Frame(footer)
        actions.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.reject_button = ttk.Button(actions, text="Odrzuć z puli", command=self._reject_selected)
        self.reject_button.pack(side=tk.LEFT)
        self.accept_button = ttk.Button(
            actions, text="Zaakceptuj jako niezależny", command=self._accept_selected)
        self.accept_button.pack(side=tk.LEFT, padx=6)
        self.reset_button = ttk.Button(actions, text="Cofnij decyzję", command=self._reset_selected)
        self.reset_button.pack(side=tk.LEFT)
        ttk.Button(actions, text="Odrzuć wszystkie wymagające weryfikacji",
                   command=self._reject_all_suspects).pack(side=tk.RIGHT)
        ttk.Label(footer, textvariable=self.action_hint, wraplength=1100).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.status_label = ttk.Label(
            footer, textvariable=self.status_var, wraplength=860, justify=tk.LEFT)
        self.status_label.grid(row=2, column=0, sticky="ew", padx=(0, 10))
        self.status_label.bind(
            "<Configure>",
            lambda event: self.status_label.configure(wraplength=max(160, event.width - 4)),
            add="+",
        )
        buttons = ttk.Frame(footer)
        buttons.grid(row=2, column=1, sticky="e")
        ttk.Button(buttons, text="Anuluj", command=self._cancel).pack(side=tk.LEFT, padx=(0, 8))
        self.apply_button = ttk.Button(buttons, command=self._apply)
        self.apply_button.pack(side=tk.LEFT)

    def resolution(self):
        return resolve_audit(self.report, self.decisions)

    def _decision_label(self, candidate):
        if candidate.common_status == STATUS_CLEAN:
            return "Do dodania" if self.mode == "ingest" else "Pozostaje w puli"
        if candidate.common_status == STATUS_SUSPECT:
            choice = self.decisions.get(audit_path_key(candidate.path))
            return {"accept": "Zaakceptowany ręcznie", "reject": "Odrzucony"}.get(choice, "Wybierz decyzję")
        return "Zostanie pominięty" if self.mode == "ingest" else "Do usunięcia z toru"

    def _row_values(self, candidate):
        problems = [item for item in candidate.per_model if item.status != STATUS_CLEAN]
        return (
            candidate.filename, AUDIT_LABELS.get(candidate.common_status, AUDIT_LABELS[STATUS_UNKNOWN]),
            ", ".join(item.model_id for item in problems) or "—",
            "; ".join(item.reason for item in problems) or "Brak wykrytej zależności",
            self._decision_label(candidate),
        )

    def _populate(self):
        previous = self.tree.selection()
        selected = previous[0] if previous else ""
        self.tree.delete(*self.tree.get_children())
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
            self._set_detail("Brak obrazów w tym filtrze.")
            self._load_preview(self.preview, None)
            self._load_preview(self.reference_preview, None)
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
        if self.tree.exists(str(index)):
            self.tree.item(str(index), values=self._row_values(candidate))
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
        self.decisions.update({
            audit_path_key(item.path): "reject" for item in self.report.candidates
            if item.common_status == STATUS_SUSPECT
        })
        for iid in self.tree.get_children():
            self.tree.item(iid, values=self._row_values(self.report.candidates[int(iid)]))
        self._refresh_resolution()

    def _refresh_resolution(self):
        result = self.resolution()
        candidate = self.report.candidates[self._selected_index] if self._selected_index is not None else None
        suspect = candidate is not None and candidate.common_status == STATUS_SUSPECT
        for button in (self.accept_button, self.reject_button, self.reset_button):
            button.configure(state=tk.NORMAL if suspect else tk.DISABLED)
        self.action_hint.set(
            "Akceptuj dopiero po sprawdzeniu, że obraz ma niezależne pochodzenie."
            if suspect else
            "Obrazy zależne i o nieustalonym pochodzeniu są wykluczone z puli."
        )
        accepted, rejected, pending = len(result.accepted_paths), len(result.rejected_paths), len(result.unresolved)
        blocked = self.mode == "pool" and rejected and not self.can_remove
        if pending:
            status = f"Stan puli: WYMAGA DECYZJI. Do rozstrzygnięcia: {pending}."
        elif blocked:
            status = "Tor zweryfikowany: zapis audytu wymaga zachowania obrazów. Zmienioną pulę przygotuj w nowym DRAFT."
        else:
            status = "Stan puli: GOTOWA DO ZAPISU." if accepted else "Brak obrazów dopuszczonych do puli."
        if self.mode == "ingest":
            status += f"\nDo dodania: {accepted}. Pominięte: {rejected}."
            self.apply_button.configure(text=f"Dodaj {accepted} obrazów do DRAFT" if accepted else "Zapisz wynik — brak nowych obrazów")
        else:
            status += f"\nPozostanie w torze: {accepted}. Do usunięcia z toru: {rejected}."
            if rejected and self.has_ground_truth:
                status += " Zmiana puli zarchiwizuje dotychczasowe GT; trzeba przygotować je ponownie."
            self.apply_button.configure(text="Zapisz wynik audytu")
        self.status_var.set(status)
        self.apply_button.configure(state=tk.NORMAL if result.ready and not blocked else tk.DISABLED)

    def _select(self, _event=None):
        selected = self.tree.selection()
        if selected:
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
        lines = [f"Plik: {candidate.filename}", AUDIT_LABELS.get(candidate.common_status, AUDIT_LABELS[STATUS_UNKNOWN]), ""]
        guidance = []
        if candidate.common_status == STATUS_DEPENDENT:
            guidance += ["Obraz był używany przez wskazany model. Jeśli model pozostaje uczestnikiem, obraz musi zostać wykluczony.",
                      "Aby użyć obrazu z innym zestawem modeli, zmień uczestników i ponów audyt.", ""]
        elif candidate.common_status == STATUS_SUSPECT:
            guidance += ["Podobieństwo wyglądu wymaga sprawdzenia pochodzenia obrazu. Porównaj go z referencją i podejmij decyzję poniżej.", ""]
        elif candidate.common_status == STATUS_UNKNOWN:
            guidance += ["Brakuje danych potrzebnych do potwierdzenia niezależności. Obraz nie może wejść do puli.", ""]
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
        self._set_detail("\n".join(lines + guidance))
        self._load_preview(self.preview, candidate.path)
        self._reference_models = list(candidate.per_model)
        self.reference_combo.configure(values=[item.model_id for item in self._reference_models])
        if self._reference_models:
            first = next((i for i, item in enumerate(self._reference_models) if item.reference_image_path), 0)
            self.reference_combo.current(first)
        self._show_reference()

    def _show_reference(self, _event=None):
        index = self.reference_combo.current()
        models = getattr(self, "_reference_models", [])
        path = models[index].reference_image_path if 0 <= index < len(models) else ""
        self._load_preview(self.reference_preview, path)

    def _load_preview(self, label, path):
        label.image = None
        if not path:
            label.configure(image="", text="Brak obrazu referencyjnego.")
            return
        try:
            with Image.open(Path(path)) as raw:
                picture = ImageOps.exif_transpose(raw).convert("RGB")
                picture.thumbnail((190, 145))
                label.image = ImageTk.PhotoImage(picture, master=self.window)
            label.configure(image=label.image, text="")
        except (OSError, ValueError):
            label.configure(image="", text="Podgląd obrazu niedostępny.")

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
