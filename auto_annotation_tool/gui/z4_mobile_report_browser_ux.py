"""Presentation-only helpers for the Z4 ALPR mobile-report browser.

No edits to source .alprsession archives, predictions, GT, statistics or sidecars.
Sidecar reads are bounded, validated and used exclusively for a status preview.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _get(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def report_identity(report: Any, bundle: Any = None) -> dict[str, str]:
    """Human-readable selection labels. Never replace canonical raw identifiers."""
    index = _get(bundle, "experiment_session") if bundle is not None else None
    if not isinstance(index, dict) or not index:
        index = _get(report, "experiment_index") or {}
    if not isinstance(index, dict) or not index:
        raw = _get(report, "raw") or {}
        index = raw.get("desktop_experiment_index", {}) if isinstance(raw, dict) else {}
    if not isinstance(index, dict):
        index = {}
    experiment = _text(index.get("experiment_variant") or index.get("variant") or index.get("experiment_variant_id"))
    technical = _text(_get(report, "variant_id"))
    variant = experiment or technical or "Wariant nieokreślony"
    session_id = _text(index.get("experiment_session_id") or index.get("session_id"))
    if not session_id:
        collection = _get(bundle, "collection_session") or {}
        if isinstance(collection, dict):
            session_id = _text(collection.get("session_id"))
    device = _get(report, "device") or {}
    device_name = " ".join(x for x in (_text(_get(device, "manufacturer")), _text(_get(device, "model") or _get(device, "name"))) if x)
    package = _text(_get(report, "package_id")) or "Pakiet nieokreślony"
    measured = _text(_get(report, "measured_at"))
    compact_date = measured[:16].replace("T", " ")
    try:
        candidate = measured.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(candidate)
        compact_date = parsed.strftime("%d.%m %H:%M")
    except (ValueError, TypeError):
        pass
    report_id = _text(_get(report, "report_id"))
    scenario = _text(index.get("scenario_id"))
    series = _text(index.get("series_id"))
    return {
        "variant": variant, "variant_short": variant if len(variant) <= 21 else variant[:18] + "…",
        "technical_variant": technical, "session_id": session_id, "report_id": report_id,
        "date": compact_date or "—", "package": package,
        "device": device_name or "Telefon nieokreślony", "scenario": scenario, "series": series,
    }


def report_filter_blob(report: Any, bundle: Any = None) -> str:
    info = report_identity(report, bundle)
    return " ".join([*info.values(), _text(_get(report, "measured_at")), _text(_get(report, "source_archive_sha256"))]).casefold()


def matches_report_filter(report: Any, search: str, bundle: Any = None) -> bool:
    """All whitespace-separated tokens must appear somewhere in report metadata."""
    words = [word.casefold() for word in (search or "").split()]
    if not words:
        return True
    blob = report_filter_blob(report, bundle)
    info = report_identity(report, bundle)
    for word in words:
        # A variant identifier must not accidentally match the series ID
        # (e.g. F4-TV-FP32-A matches F4-TV-FP32-A12-... of variant B).
        if re.fullmatch(r"f4-tv-fp32-[a-d]", word, flags=re.IGNORECASE):
            if info["variant"].casefold() != word:
                return False
        elif word not in blob:
            return False
    return True


def sidecar_preview(root: Path | str, archive_sha256: str, session_id: str = "") -> dict[str, Any]:
    """Read bounded Desktop review metadata. Invalid/mismatched sidecars are NOT trusted.

    The result is display-only: total reviewed subjects, CER, NMCE and IoU require
    the canonical review backend, not these advisory sidecar counts.
    """
    empty = {"state": "none", "title": "Brak weryfikacji Desktop", "detail": "Nie znaleziono ocen operatora dla tego archiwum.", "revision": None, "gt_entries": None}
    source = _text(archive_sha256).lower()
    if not _SHA256.fullmatch(source):
        return {**empty, "state": "unverified", "title": "Weryfikacja Desktop: nieustalona", "detail": "Brak wiarygodnego SHA-256 archiwum."}
    file = Path(root) / "human_reviews" / f"{source}.review.json"
    try:
        if not file.is_file():
            return empty
        if file.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Plik weryfikacji jest zbyt duży dla podglądu.")
        payload = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Nieprawidłowa struktura weryfikacji.")
        if _text(payload.get("source_archive_sha256")).lower() != source:
            raise ValueError("SHA-256 sidecara nie zgadza się z archiwum.")
        original_session = _text(payload.get("session_id"))
        if session_id and original_session != session_id:
            raise ValueError("Identyfikator sesji w sidecarze jest niezgodny.")
        status = _text(payload.get("review_status")).upper()
        if status not in ("NOT_STARTED", "IN_PROGRESS", "COMPLETED"):
            raise ValueError("Nieznany status weryfikacji.")
        subjects = payload.get("subjects", {})
        if not isinstance(subjects, dict):
            raise ValueError("Nieprawidłowy rejestr GT w sidecarze.")
        revision = payload.get("review_revision", 0)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("Nieprawidłowy numer rewizji.")
        entered_gt = sum(1 for row in subjects.values() if isinstance(row, dict) and _text(row.get("ground_truth")))
        titles = {"NOT_STARTED": "Weryfikacja Desktop: nierozpoczęta", "IN_PROGRESS": "Weryfikacja Desktop: w toku", "COMPLETED": "Weryfikacja Desktop: ukończona"}
        return {"state": status.lower(), "title": titles[status], "detail": f"Rewizja {revision} • GT wpisane: {entered_gt} (nie liczba ukończonych ocen).", "revision": revision, "gt_entries": entered_gt}
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return {**empty, "state": "error", "title": "Weryfikacja Desktop: wymaga sprawdzenia", "detail": str(exc)[:210]}


def source_archive_sha(report: Any, bundle: Any = None) -> str:
    return _text(_get(bundle, "source_archive_sha256") or _get(report, "source_archive_sha256"))


def desktop_status(report: Any, bundle: Any, review_root: Path | str) -> dict[str, Any]:
    index = report_identity(report, bundle)
    return sidecar_preview(review_root, source_archive_sha(report, bundle), index["session_id"])


def selected_report_caption(report: Any, bundle: Any = None) -> str:
    meta = report_identity(report, bundle)
    fields = [f"Pakiet: {meta['package']}", f"Telefon: {meta['device']}"]
    if meta["scenario"]:
        fields.append(f"Scenariusz: {meta['scenario']}")
    if meta["session_id"]:
        fields.append(f"Sesja: {meta['session_id']}")
    return "\n".join(fields)
