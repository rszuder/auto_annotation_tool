"""Elegancka prezentacja wyników audytu zależności puli źródłowej PZ3."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Any, Iterable, Mapping


_STATUS_ORDER = {
    "DEPENDENT": 0,
    "SUSPECT_DERIVATIVE": 1,
    "UNKNOWN": 2,
    "NO_DETECTED_DEPENDENCE": 3,
}

_STATUS_LABELS = {
    "DEPENDENT": "ZALEŻNY",
    "SUSPECT_DERIVATIVE": "PODEJRZANA POCHODNA",
    "NO_DETECTED_DEPENDENCE": "BRAK WYKRYTEJ ZALEŻNOŚCI",
    "UNKNOWN": "NIEUSTALONE",
}

_STATUS_SYMBOLS = {
    "DEPENDENT": "⛔",
    "SUSPECT_DERIVATIVE": "⚠",
    "NO_DETECTED_DEPENDENCE": "✓",
    "UNKNOWN": "?",
}

_STATUS_EXPLANATIONS = {
    "DEPENDENT": (
        "Wykryto bezpośrednią zależność od chronionego train/val "
        "(np. to samo źródło lub SHA-256). Ten obraz nie powinien wejść "
        "do niezależnego toru rankingowego/testowego."
    ),
    "SUSPECT_DERIVATIVE": (
        "Nie wykryto exact overlap, ale podobieństwo pHash wskazuje, że obraz "
        "może być pochodną train/val (np. resize, rekompresja lub ponowny eksport)."
    ),
    "NO_DETECTED_DEPENDENCE": (
        "Nie znaleziono zależności metodami użytymi w tym audycie. "
        "To nie jest formalny dowód niezależności."
    ),
    "UNKNOWN": (
        "Audyt nie ma wystarczających danych, aby wiarygodnie sklasyfikować obraz."
    ),
}


def _to_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        try:
            return asdict(value)
        except Exception:
            pass
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            if isinstance(result, Mapping):
                return dict(result)
        except Exception:
            pass
    try:
        return dict(vars(value))
    except Exception:
        return {}


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], (), {}):
            return value
    return default


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _report_items(report: Any) -> list[Any]:
    data = _to_mapping(report)
    for key in (
        "items",
        "audit_items",
        "results",
        "candidates",
        "candidate_results",
    ):
        value = data.get(key)
        if value is not None:
            return _as_sequence(value)
    for key in (
        "items",
        "audit_items",
        "results",
        "candidates",
        "candidate_results",
    ):
        value = getattr(report, key, None)
        if value is not None:
            return _as_sequence(value)
    return []


def normalize_audit_status(value: Any) -> str:
    raw = str(value or "").strip().upper()
    aliases = {
        "DEPENDENT": "DEPENDENT",
        "EXACT_OVERLAP": "DEPENDENT",
        "SUSPECT": "SUSPECT_DERIVATIVE",
        "SUSPECT_DERIVATIVE": "SUSPECT_DERIVATIVE",
        "NO_DETECTED_DEPENDENCE": "NO_DETECTED_DEPENDENCE",
        "NO_DEPENDENCE_DETECTED": "NO_DETECTED_DEPENDENCE",
        "INDEPENDENT": "NO_DETECTED_DEPENDENCE",
        "UNKNOWN": "UNKNOWN",
    }
    return aliases.get(raw, raw or "UNKNOWN")


def audit_status_label(value: Any) -> str:
    status = normalize_audit_status(value)
    return _STATUS_LABELS.get(status, status.replace("_", " "))


def _format_list(value: Any) -> str:
    items = [str(item or "").strip() for item in _as_sequence(value)]
    return ", ".join(item for item in items if item)


def _reference_summary(matches: list[Any]) -> str:
    parts: list[str] = []
    for raw in matches[:3]:
        match = _to_mapping(raw)
        dataset = str(
            _first(
                match,
                "dataset_id",
                "training_dataset_id",
                "reference_dataset_id",
                default="",
            )
            or ""
        ).strip()
        split = str(_first(match, "split", "training_split", default="") or "").strip()
        run_ids = _format_list(
            _first(match, "training_run_ids", "run_ids", "training_run_id", default="")
        )
        model_ids = _format_list(
            _first(match, "model_ids", "training_model_ids", "model_id", default="")
        )
        source_id = str(
            _first(match, "source_image_id", "reference_source_image_id", default="")
            or ""
        ).strip()

        primary = "/".join(item for item in (dataset, split) if item)
        if not primary:
            primary = source_id or run_ids or model_ids
        if primary:
            parts.append(primary)
    if len(matches) > 3:
        parts.append(f"+{len(matches) - 3}")
    return " | ".join(parts)


def _extract_distance(item: Mapping[str, Any], matches: list[Any]) -> str:
    for mapping in [item] + [_to_mapping(match) for match in matches]:
        value = _first(
            mapping,
            "phash_distance",
            "hamming_distance",
            "distance",
            "min_phash_distance",
            "phash_hamming_distance",
            default="",
        )
        if value not in (None, ""):
            try:
                numeric = float(value)
                return str(int(numeric)) if numeric.is_integer() else f"{numeric:.2f}"
            except Exception:
                return str(value)
    return "—"


def _item_reason(item: Mapping[str, Any], status: str) -> str:
    value = _first(
        item,
        "reason",
        "message",
        "detail",
        "explanation",
        "reasons",
        default="",
    )
    if isinstance(value, (list, tuple, set)):
        text = "; ".join(str(part) for part in value if str(part).strip())
    else:
        text = str(value or "").strip()
    return text or _STATUS_EXPLANATIONS.get(status, "")


def build_audit_table_rows(report: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_item in _report_items(report):
        item = _to_mapping(raw_item)
        status = normalize_audit_status(
            _first(
                item,
                "status",
                "result",
                "classification",
                "decision",
                default="UNKNOWN",
            )
        )
        path_value = _first(
            item,
            "candidate_path",
            "path",
            "source_path",
            "file_path",
            "filename",
            "name",
            default="",
        )
        path_text = str(path_value or "").strip()
        filename = Path(path_text).name if path_text else "—"
        matches = _as_sequence(
            _first(
                item,
                "reference_matches",
                "matches",
                "references",
                "training_matches",
                default=[],
            )
        )
        rows.append(
            {
                "filename": filename,
                "path": path_text,
                "status": status,
                "status_label": audit_status_label(status),
                "status_symbol": _STATUS_SYMBOLS.get(status, "•"),
                "reason": _item_reason(item, status),
                "reference": _reference_summary(matches) or "—",
                "phash_distance": _extract_distance(item, matches),
                "matches": [_to_mapping(match) for match in matches],
                "raw": item,
            }
        )

    rows.sort(
        key=lambda row: (
            _STATUS_ORDER.get(row["status"], 9),
            row["filename"].casefold(),
        )
    )
    return rows


def audit_summary_counts(report: Any) -> dict[str, int]:
    rows = build_audit_table_rows(report)
    derived = {
        "total": len(rows),
        "dependent": sum(row["status"] == "DEPENDENT" for row in rows),
        "suspect": sum(row["status"] == "SUSPECT_DERIVATIVE" for row in rows),
        "no_detected": sum(
            row["status"] == "NO_DETECTED_DEPENDENCE" for row in rows
        ),
        "unknown": sum(row["status"] == "UNKNOWN" for row in rows),
    }
    data = _to_mapping(report)

    aliases = {
        "total": ("total_count", "candidate_count", "count"),
        "dependent": ("dependent_count", "exact_overlap_count"),
        "suspect": ("suspect_derivative_count", "suspect_count"),
        "no_detected": (
            "no_detected_dependence_count",
            "no_dependence_detected_count",
        ),
        "unknown": ("unknown_count",),
    }
    for target, keys in aliases.items():
        for key in keys:
            value = data.get(key, getattr(report, key, None))
            if value not in (None, ""):
                try:
                    derived[target] = int(value)
                    break
                except Exception:
                    pass
    return derived


def compact_source_pool_audit_followup_text(report: Any) -> str:
    counts = audit_summary_counts(report)
    if counts["dependent"] or counts["unknown"]:
        return (
            "Szczegóły audytu pokazano w tabeli wyników. "
            f"Zależne: {counts['dependent']}, nieustalone: {counts['unknown']}. "
            "Te pozycje nie mogą zostać automatycznie zaakceptowane."
        )
    if counts["suspect"]:
        return (
            "Szczegóły audytu pokazano w tabeli wyników. "
            f"Podejrzane pochodne: {counts['suspect']}. "
            "Zdecyduj, czy odrzucić je z bieżącego dodawania."
        )
    return (
        "Szczegóły audytu pokazano w tabeli wyników. "
        "Nie wykryto zależności od chronionego train/val dla nowych kandydatów."
    )


def _match_detail_text(match: Mapping[str, Any]) -> str:
    fields = (
        ("Dataset", ("dataset_id", "training_dataset_id")),
        ("Split", ("split", "training_split")),
        ("Run", ("training_run_ids", "run_ids", "training_run_id")),
        ("Model", ("model_ids", "training_model_ids", "model_id")),
        ("source_image_id", ("source_image_id", "reference_source_image_id")),
        ("SHA-256", ("sha256", "file_sha256", "reference_sha256")),
        ("pHash Δ", ("phash_distance", "hamming_distance", "distance")),
        ("Typ dopasowania", ("match_type", "reason", "kind")),
    )
    lines: list[str] = []
    for label, keys in fields:
        value = _first(match, *keys, default="")
        text = _format_list(value) if isinstance(value, (list, tuple, set)) else str(value or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


class SourcePoolAuditResultsDialog:
    def __init__(
        self,
        parent,
        report: Any,
        *,
        preflight_summary: str = "",
        title: str = "Wynik kontroli zależności obrazów",
    ) -> None:
        self.parent = parent
        self.report = report
        self.rows = build_audit_table_rows(report)
        self.counts = audit_summary_counts(report)
        self.preflight_summary = str(preflight_summary or "").strip()

        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("1180x720")
        self.window.minsize(900, 560)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._close)

        self._build()
        self._populate()
        try:
            self.window.wait_visibility()
            self.window.grab_set()
        except Exception:
            pass

    def _build(self) -> None:
        root = ttk.Frame(self.window, padding=14)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        ttk.Label(
            root,
            text="Kontrola zależności względem train/val",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text=(
                "Najpierw sprawdzono duplikaty bieżącego toru, a następnie "
                "nowych kandydatów względem zarejestrowanej historii train/val."
            ),
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))

        cards = ttk.Frame(root)
        cards.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        for index in range(5):
            cards.columnconfigure(index, weight=1)

        card_data = (
            ("Sprawdzono", self.counts["total"]),
            ("Zależne", self.counts["dependent"]),
            ("Podejrzane", self.counts["suspect"]),
            ("Brak wykrytej zależności", self.counts["no_detected"]),
            ("Nieustalone", self.counts["unknown"]),
        )
        for index, (label, value) in enumerate(card_data):
            frame = ttk.LabelFrame(cards, text=label, padding=(10, 8))
            frame.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0 if index == 0 else 5, 0),
            )
            ttk.Label(
                frame,
                text=str(value),
                font=("Segoe UI", 16, "bold"),
                anchor="center",
            ).pack(fill=tk.X)

        body = ttk.PanedWindow(root, orient=tk.VERTICAL)
        body.grid(row=3, column=0, sticky="nsew")

        table_frame = ttk.Frame(body)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        body.add(table_frame, weight=3)

        columns = ("file", "status", "reason", "reference", "phash")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "file": "Plik",
            "status": "Wynik",
            "reason": "Podstawa klasyfikacji",
            "reference": "Odniesienie train/val",
            "phash": "pHash Δ",
        }
        widths = {
            "file": 190,
            "status": 235,
            "reason": 390,
            "reference": 230,
            "phash": 80,
        }
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(
                key,
                width=widths[key],
                minwidth=60,
                stretch=(key in {"file", "reason", "reference"}),
                anchor=tk.W if key != "phash" else tk.CENTER,
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(
            table_frame,
            orient=tk.VERTICAL,
            command=self.tree.yview,
        )
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select, add="+")

        detail_frame = ttk.LabelFrame(
            body,
            text="Szczegóły zaznaczonego obrazu",
            padding=8,
        )
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        body.add(detail_frame, weight=2)

        self.detail = tk.Text(
            detail_frame,
            height=9,
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.FLAT,
            bd=0,
        )
        self.detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(
            detail_frame,
            orient=tk.VERTICAL,
            command=self.detail.yview,
        )
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=detail_scroll.set)

        if self.preflight_summary:
            ttk.Label(
                root,
                text=self.preflight_summary,
                justify=tk.LEFT,
                wraplength=1120,
            ).grid(row=4, column=0, sticky="ew", pady=(10, 0))

        ttk.Label(
            root,
            text=(
                "Metodologia: ZALEŻNY = exact source/SHA overlap; "
                "PODEJRZANA POCHODNA = podobieństwo pHash; "
                "BRAK WYKRYTEJ ZALEŻNOŚCI nie oznacza formalnego dowodu niezależności; "
                "NIEUSTALONE = niewystarczające dane."
            ),
            justify=tk.LEFT,
            wraplength=1120,
        ).grid(row=5, column=0, sticky="ew", pady=(10, 8))

        footer = ttk.Frame(root)
        footer.grid(row=6, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Button(
            footer,
            text="Zamknij",
            command=self._close,
        ).grid(row=0, column=1, sticky="e")

    def _populate(self) -> None:
        for index, row in enumerate(self.rows):
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    row["filename"],
                    f'{row["status_symbol"]} {row["status_label"]}',
                    row["reason"],
                    row["reference"],
                    row["phash_distance"],
                ),
            )
        if self.rows:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._show_detail(self.rows[0])
        else:
            self._set_detail(
                "Brak wierszy szczegółowych w raporcie audytu."
            )

    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        try:
            row = self.rows[int(selected[0])]
        except Exception:
            return
        self._show_detail(row)

    def _show_detail(self, row: Mapping[str, Any]) -> None:
        lines = [
            f'Plik: {row.get("filename") or "—"}',
        ]
        if row.get("path"):
            lines.append(f'Ścieżka: {row["path"]}')
        lines.extend(
            [
                f'Wynik: {row.get("status_label") or "—"}',
                "",
                str(row.get("reason") or ""),
                "",
                _STATUS_EXPLANATIONS.get(str(row.get("status") or ""), ""),
            ]
        )

        matches = list(row.get("matches") or [])
        if matches:
            lines.extend(["", "Dopasowania referencyjne:"])
            for index, match in enumerate(matches, start=1):
                detail = _match_detail_text(match)
                lines.append(f"\n[{index}]")
                lines.append(detail or str(match))

        self._set_detail("\n".join(lines).strip())

    def _set_detail(self, text: str) -> None:
        self.detail.configure(state=tk.NORMAL)
        self.detail.delete("1.0", tk.END)
        self.detail.insert("1.0", str(text or ""))
        self.detail.configure(state=tk.DISABLED)

    def _close(self) -> None:
        try:
            self.window.grab_release()
        except Exception:
            pass
        self.window.destroy()

    def show(self) -> None:
        self.window.wait_window()


def show_source_pool_audit_results(
    parent,
    report: Any,
    *,
    preflight_summary: str = "",
    title: str = "Wynik kontroli zależności obrazów",
) -> None:
    SourcePoolAuditResultsDialog(
        parent,
        report,
        preflight_summary=preflight_summary,
        title=title,
    ).show()
