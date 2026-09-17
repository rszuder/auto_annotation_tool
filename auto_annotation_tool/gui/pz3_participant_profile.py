"""Presentation of a participant's recorded training background."""
from __future__ import annotations

from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk

from ..registry.participant_background import metric_value
from .app_theme_definitions import get_runtime_palette, normalize_theme_palette
from .app_tooltips import schedule_simple_tooltip, hide_simple_tooltip


def format_training_date(value) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d.%m.%Y · %H:%M")
    except (ValueError, TypeError):
        return "—"


def training_date_sort_value(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc).timestamp() if stamp.tzinfo is None else stamp.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def format_metric(value) -> str:
    number = metric_value(value)
    return "—" if number is None else f"{number:.3f}"


def short_identifier(value, *, limit=30) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit-7] + "…" + text[-6:]


def short_sha(value) -> str:
    text = str(value or "")
    return text[:8] + "…" + text[-4:] if len(text) > 16 else (text or "—")


def architecture_label(item) -> str:
    return f"{item.family or '—'} · {item.scale or '—'}"


def participant_eligible(item) -> bool:
    return bool(item.model_id and item.sha256) and (
        item.provenance_status not in {"complete", "known"} or bool(item.run_id and item.dataset_id)
    )


def provenance_badge(item) -> tuple[str, str]:
    if not participant_eligible(item):
        return "● Niespójna", "error"
    return {
        "complete": ("● Pełna", "success"),
        "known": ("● Potwierdzona ręcznie", "info"),
        "partial": ("● Częściowa", "warning"),
        "legacy_partial": ("● Częściowa", "warning"),
    }.get(item.provenance_status, ("● Nieustalona", "muted"))


def quality_metric(item) -> tuple[str, float | None]:
    pose = item.target == "plate" or getattr(item, "task_type", "") == "pose"
    field = "pose_map50_95" if pose else "box_map50_95"
    return ("Pose" if pose else "BBox"), metric_value(getattr(item, field, None))


def shared_run_notice(item, models) -> tuple[str, str]:
    peers = [model for model in models if item.run_id and model.run_id == item.run_id]
    if len(peers) <= 1:
        return "", "muted"
    complete = [model for model in peers if model.provenance_status == "complete"]
    if (item.provenance_status == "complete" and len({p.sha256 for p in complete}) > 1
            and len({p.scale for p in complete}) > 1):
        return ("⚠ Ten sam run z pełną historią przypisano do różnych modeli i skal. Sprawdź pochodzenie.", "warning")
    return f"Ten run jest powiązany z {len(peers)} logicznymi modelami.", "info"


class ParticipantProfilePanel:
    def __init__(self, parent, *, palette=None):
        self.root = parent.winfo_toplevel()
        self.palette = normalize_theme_palette(palette) if palette else get_runtime_palette()
        self.frame = ttk.LabelFrame(parent, text="Profil zaznaczonego modelu", padding=(12, 8))
        self.frame.columnconfigure(0, weight=1)
        self.title = tk.StringVar(self.root)
        ttk.Label(self.frame, textvariable=self.title, font=("Segoe UI", 10, "bold"), padding=0).grid(
            row=0, column=0, sticky="w", pady=(0, 8))
        body = ttk.Frame(self.frame)
        body.grid(row=1, column=0, sticky="ew")
        self.values, self.widgets, self.full_values, self.tones = {}, {}, {}, {}
        self.captions = {}
        groups = [
            ("Trening", [("run", "Run"), ("dataset", "Dataset"), ("finished", "Zakończono")]),
            ("Jakość walidacyjna treningu", [
                ("pose_map50_95", "mAP50–95 Pose"), ("pose_map50", "mAP50 Pose"),
                ("box_map50_95", "mAP50–95 BBox"), ("box_map50", "mAP50 BBox"),
                ("best_map50_95", "mAP50–95 · historia"), ("best_map50", "mAP50 · historia"),
            ]),
            ("Pochodzenie", [("provenance", "Historia"), ("checkpoint", "Checkpoint"), ("sha", "SHA-256")]),
        ]
        for column, (title, fields) in enumerate(groups):
            body.columnconfigure(column, weight=1, uniform="profile")
            group = ttk.Frame(body, padding=(0 if column == 0 else 12, 0, 10, 0))
            group.grid(row=0, column=column, sticky="nsew")
            group.columnconfigure(1, weight=1)
            ttk.Label(group, text=title, font=("Segoe UI", 9, "bold"), padding=0).grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
            for index, (key, caption) in enumerate(fields, 1):
                caption_widget = self.captions[key] = ttk.Label(group, text=caption, foreground=self.palette["muted"], padding=0)
                caption_widget.grid(row=index, column=0, sticky="w", padx=(0, 8), pady=1)
                var = self.values[key] = tk.StringVar(self.root, "—")
                if key in {"run", "dataset"}:
                    widget = ttk.Entry(group, textvariable=var, state="readonly", width=20)
                else:
                    widget = ttk.Label(group, textvariable=var, padding=0,
                                       font=("Segoe UI", 9, "bold") if "map50" in key else ("Segoe UI", 9))
                widget.grid(row=index, column=1, sticky="ew", pady=1)
                self.widgets[key] = widget
                widget.bind("<Enter>", lambda event, key=key: schedule_simple_tooltip(
                    self, event.widget, self.full_values.get(key, "")), add="+")
                widget.bind("<Leave>", lambda _event: hide_simple_tooltip(self), add="+")
                widget.bind("<ButtonPress-1>", lambda _event: hide_simple_tooltip(self), add="+")
            if column == 2:
                self.copy_button = ttk.Button(group, text="Kopiuj pełny SHA-256", command=self.copy_sha)
                self.copy_button.grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.notice = tk.StringVar(self.root)
        self.notice_label = ttk.Label(self.frame, textvariable=self.notice, wraplength=1000)
        self.notice_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.frame.bind("<Configure>", lambda event: self.notice_label.configure(
            wraplength=max(300, event.width - 30)), add="+")
        self.frame.bind("<Destroy>", lambda _event: hide_simple_tooltip(self), add="+")
        self.show([], [])

    def _set(self, key, value, *, full="", tone="fg"):
        self.values[key].set(value)
        self.full_values[key] = full or value
        self.tones[key] = tone
        if key not in {"run", "dataset"}:
            self.widgets[key].configure(foreground=self.palette[tone])

    def show(self, selected, models):
        hide_simple_tooltip(self)
        self.full_values.clear()
        self.copy_button.state(["disabled"])
        for key in self.values:
            self._set(key, "—", tone="muted")
        self.notice.set("")
        self.notice_label.grid_remove()
        for key in ("best_map50_95", "best_map50"):
            self.captions[key].grid_remove()
            self.widgets[key].grid_remove()
        if len(selected) != 1:
            count = len(selected)
            noun = "modele" if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14} else "modeli"
            self.title.set("Wybierz model, aby zobaczyć szczegóły." if not selected
                           else f"Wybrano {count} {noun}.")
            return
        item = selected[0]
        self.title.set(f"{item.model_id} · {architecture_label(item)}")
        self._set("run", item.run_id or "—")
        self._set("dataset", item.dataset_id or "—")
        date = format_training_date(item.training_finished_at)
        self._set("finished", date, full=item.training_finished_at, tone="muted" if date == "—" else "fg")
        for key in ("pose_map50_95", "pose_map50", "box_map50_95", "box_map50", "best_map50_95", "best_map50"):
            value = metric_value(getattr(item, key, None))
            generic = key.startswith("best")
            if generic and value is not None:
                self.captions[key].grid()
                self.widgets[key].grid()
            self._set(key, format_metric(value), tone="muted" if value is None else "fg",
                      full=("Brak zapisanej metryki." if value is None else
                            "Najlepsza zapisana metryka walidacyjna treningu; nie wynik rankingu.")
                      + (" Historia nie określa, czy ta metryka dotyczy Pose czy BBox." if generic else ""))
        badge, tone = provenance_badge(item)
        self._set("provenance", badge, tone=tone, full=(
            "Znane pochodzenie model → run → dataset." if participant_eligible(item) else
            "Model nie ma pełnego identyfikatora, SHA lub wymaganego powiązania run/dataset. Nie może uczestniczyć."))
        self._set("checkpoint", item.checkpoint_kind or "—", tone="fg" if item.checkpoint_kind else "muted")
        self._set("sha", short_sha(item.sha256), full=item.sha256)
        if item.sha256:
            self.copy_button.state(["!disabled"])
        notice, tone = shared_run_notice(item, models)
        if not participant_eligible(item):
            notice, tone = "Nie można wybrać tego modelu do eksperymentu: niespójne pochodzenie.", "error"
        self.notice.set(notice)
        if notice:
            self.notice_label.grid()
        self.notice_label.configure(foreground=self.palette[tone])

    def copy_sha(self):
        sha = self.full_values.get("sha", "")
        if sha and sha != "—":
            self.root.clipboard_clear()
            self.root.clipboard_append(sha)
