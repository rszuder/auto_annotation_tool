# -*- coding: utf-8 -*-
"""AKT87 — audited, *assisted* MT+MZ verification gate for mobile comparisons.

No mutations. Only a complete, SHA-pinned operator review, including geometry
and text/missed-object accounting, may participate in quality comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Verification:
    state: str
    label: str
    reason: str
    revision: int | None = None
    export_dir: Path | None = None

    @property
    def ready(self) -> bool:
        return self.state == "READY"


def _integer(value, *, maximum=1_000_000) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        return None
    return value


def _number(value, *, ceiling=None) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(v) or v < 0 or (ceiling is not None and v > ceiling):
        return None
    return v


def _quad(value) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(
        isinstance(point, (list, tuple)) and len(point) == 2 and
        all(_number(v) is not None for v in point) for point in value
    )


def _clean_text(text) -> str:
    return "".join(x for x in str(text or "").upper() if x.isalnum())


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1]+1, previous[j]+1,
                               previous[j-1]+(left != right)))
        previous = current
    return previous[-1]


def inspect_canvas(canvas: dict[str, Any] | None, review_status: str) -> tuple[bool, str]:
    """Check *both* MT corners and MZ GT on the same reviewed plates.

    A missed MT with manually marked four corners remains an explicit FN, not
    a fake geometry score or a CER=1.  Rejected raw NMS candidates never count.
    """
    c = canvas if isinstance(canvas, dict) else {}
    if review_status != "COMPLETED":
        return False, "Operator nie zatwierdził weryfikacji."
    if c.get("provenance") != "ASSISTED_CANVAS_SOURCE_ROI" or c.get("independent_gt") is not False:
        return False, "Niepotwierdzony tryb oceny asystowanej."
    names = ("scene_count", "checked_scenes", "pending_scenes", "excluded_scenes",
             "incomplete_checked_scenes", "expected_plates", "linked_plates", "missed_plates",
             "false_positive_mt", "operator_errors", "geometry_n", "evaluated_reads",
             "exact_reads", "gt_characters", "text_errors")
    if any(_integer(c.get(n)) is None for n in names):
        return False, "Brak licznika oceny Canvas."
    if c["scene_count"] <= 0 or c["pending_scenes"] or c["incomplete_checked_scenes"] or c["operator_errors"]:
        return False, "Nie wszystkie obrazy i ramki MT zostały sprawdzone."
    if c["checked_scenes"] + c["excluded_scenes"] != c["scene_count"]:
        return False, "Niespójny licznik obrazów GT."
    if c["expected_plates"] != c["linked_plates"] + c["missed_plates"]:
        return False, "Nie rozliczono wykryć i pominięć MT."
    if c["expected_plates"] <= 0:
        return False, "Brak referencyjnych tablic w materiale."
    scenes = c.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != c["scene_count"]:
        return False, "Brak kompletnej listy obrazów."
    for scene in scenes:
        if not isinstance(scene, dict):
            return False, "Nieprawidłowy wpis obrazu."
        if scene.get("status") == "EXCLUDED":
            if not str(scene.get("exclusion_reason") or "").strip():
                return False, "Wyłączony obraz nie ma uzasadnienia."
        elif scene.get("status") != "CHECKED":
            return False, "Obraz nie ma statusu CHECKED."
    rows = c.get("rows")
    if not isinstance(rows, list):
        return False, "Nie zapisano oceny poszczególnych tablic."
    linked = missed = geometry = read = exact = chars = false_positive = raw_suppressed = errors = 0
    for row in rows:
        if not isinstance(row, dict):
            return False, "Nieprawidłowy rekord tablicy."
        if row.get("post_nms_suppressed_raw"):
            raw_suppressed += 1
            continue
        if not row.get("included"):
            continue
        outcome = row.get("outcome")
        if outcome not in ("LINKED_MT", "MISSED_MT", "FALSE_POSITIVE_MT"):
            return False, "Nieznany wynik przypisania MT."
        if outcome == "FALSE_POSITIVE_MT":
            false_positive += 1
            continue
        if not _quad(row.get("operator_quad")):
            return False, "Brak czterech narożników referencyjnych."
        gt = _clean_text(row.get("gt_text"))
        if outcome == "MISSED_MT":
            # A confirmed MT false negative has no input crop for MZ. Its
            # reference quad accounts for FN; optional historical text GT
            # must never enter the CER denominators.
            missed += 1
            mz_status = str(row.get("mz_status") or "").upper()
            if (mz_status not in ("", "NOT_RUN") or
                    _clean_text(row.get("mz_prediction")) or row.get("cer") is not None):
                return False, "Niewykryta tablica ma nieuprawniony wynik MZ/CER."
            continue
        if not gt and not str(row.get("text_exclusion_reason") or "").strip():
            return False, "Brak GT znaków lub jawnego wyłączenia odczytu."
        linked += 1
        if not _quad(row.get("original_mt_quad")):
            return False, "Brak oryginalnych narożników MT."
        if _number(row.get("polygon_iou_pct"), ceiling=100) is None or _number(row.get("nmce_pct")) is None:
            return False, "Brak ocenionego IoU/NMCE ramki MT."
        geometry += 1
        mz_status = str(row.get("mz_status") or "").upper()
        pred = _clean_text(row.get("mz_prediction"))
        cer = _number(row.get("cer"))
        # In Canvas, a scored MZ attempt is represented by CER, *not* merely
        # mz_status == READ.  NO_CHARACTERS/NO_READ/FAILED can be actual
        # executed inferences with a known GT; their errors belong in CER.
        # Conversely, an explicitly excluded illegible GT must stay out of
        # quality denominators even if the model was executed.
        mz_ran = (mz_status not in ("", "UNKNOWN", "NOT_RUN") or bool(pred))
        if cer is not None:
            if not gt or mz_status in ("", "NOT_RUN", "AMBIGUOUS_SAMPLES") or not mz_ran:
                return False, "CER przypisano niewykonanemu lub nieocenialnemu MZ."
            distance = _edit_distance(gt, pred)
            if not math.isclose(cer, distance / len(gt), rel_tol=1e-6, abs_tol=1e-6):
                return False, "CER tablicy nie zgadza się z tekstem GT i MZ."
            read += 1
            chars += len(gt)
            errors += distance
            if pred == gt:
                exact += 1
        elif mz_ran and gt:
            return False, "Wykonano MZ i potwierdzono GT, ale brakuje CER."
        elif mz_status == "AMBIGUOUS_SAMPLES":
            return False, "Sprzeczne próbki MZ wymagają weryfikacji."
    if (linked != c["linked_plates"] or missed != c["missed_plates"] or
            geometry != c["geometry_n"] or read != c["evaluated_reads"] or
            exact != c["exact_reads"] or chars != c["gt_characters"] or
            errors != c["text_errors"] or false_positive != c["false_positive_mt"]):
        return False, "Mianowniki MT/MZ nie zgadzają się z rekordami tablic."
    if "raw_suppressed_mt" in c and c["raw_suppressed_mt"] != raw_suppressed:
        return False, "Niespójny licznik kandydatów odrzuconych przez NMS."
    if "cer" in c and chars and not math.isclose(float(c["cer"]), errors/chars, rel_tol=1e-6, abs_tol=1e-6):
        return False, "Micro-CER nie zgadza się z ocenionymi odczytami."
    return True, f"MT: {linked} ramki i {missed} pominięć; MZ: {read} odczytów; obrazy {c['checked_scenes']}/{c['scene_count']}"


def _live_review_state(review_root: Path | None, sha: str, session_id: str):
    if not review_root:
        return None
    path = Path(review_root) / "human_reviews" / (sha + ".review.json")
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("Za duży sidecar")
        d = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(d, dict) or d.get("session_id") != session_id or str(d.get("source_archive_sha256", "")).lower() != sha:
            raise ValueError("Niezgodna tożsamość sidecara")
        rev = _integer(d.get("review_revision"))
        if rev is None or d.get("review_status") not in ("NOT_STARTED", "IN_PROGRESS", "COMPLETED"):
            raise ValueError("Nieprawidłowy status/rewizja")
        return rev, d["review_status"]
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return "INVALID"


def _export_failure(error, diagnostic):
    """Preserve read/validation failures without equating access with corruption."""
    import traceback
    diagnostic.update(error_type=type(error).__name__, error=str(error),
        errno=getattr(error, "errno", None), winerror=getattr(error, "winerror", None),
        error_file=str(getattr(error, "filename", None) or diagnostic.get("file", "")),
        traceback=[dict(module_path=f.filename, function=f.name, line=f.lineno)
                   for f in traceback.extract_tb(error.__traceback__)])


def _rejected_verification(error, diagnostic, revision=None, export_dir=None):
    file = diagnostic.get("error_file") or str(export_dir or "")
    if isinstance(error, OSError):
        return Verification("UNREADABLE", "Brak odczytu",
            f"Nie można odczytać eksportu: {type(error).__name__} "
            f"(errno={getattr(error, 'errno', None)}): {file}. "
            "Integralność nie została potwierdzona.", revision, export_dir)
    return Verification("INVALID", "Wymaga kontroli",
        f"Błąd walidacji eksportu: {type(error).__name__}: {error}", revision, export_dir)


def imported_verification(session_id: str, source_sha: str, results_root: Path | None,
                          review_root: Path | None = None, *, diagnostics=None) -> Verification:
    """Latest revision wins; old completed exports cannot mask newer GT edits."""
    import re
    trace = diagnostics if diagnostics is not None else {}
    trace.update(gate_module=__name__, gate_module_path=__file__,
                 session_id=session_id, source_sha256=source_sha,
                 results_root=str(results_root) if results_root else None,
                 review_root=str(review_root) if review_root else None, exports=[])
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", str(session_id or "")) or not re.fullmatch(r"[a-f0-9]{64}", str(source_sha or "").lower()):
        return Verification("UNKNOWN", "Nieustalona", "Brak zgodnej tożsamości SHA/session_id.")
    source_sha = source_sha.lower()
    live = _live_review_state(review_root, source_sha, session_id)
    trace["live_review"] = live
    if live == "INVALID":
        return Verification("INVALID", "Wymaga kontroli", "Sidecar weryfikacji jest uszkodzony lub niespójny.")
    root = Path(results_root) if results_root else None
    folder = root / session_id if root and root.is_dir() else None
    entries = sorted((p for p in folder.iterdir() if p.is_dir() and (p / "export_manifest.json").is_file()),
                     key=lambda p: p.name) if folder and folder.is_dir() else []
    exports=[]
    from .mobile_comparison_core import InvalidExport, load_session_export
    for directory in entries:
        diagnostic = {"directory": str(directory.absolute())}
        trace["exports"].append(diagnostic)
        try:
            row = load_session_export(directory, verify=True, diagnostics=diagnostic)
        except (InvalidExport, OSError, KeyError, TypeError, ValueError) as err:
            _export_failure(err, diagnostic)
            exports.append((None, directory, (err, diagnostic)))
            continue
        finally:
            diagnostic["session_id_matches"] = (diagnostic.get("manifest_session_id") == session_id
                if "manifest_session_id" in diagnostic else None)
            diagnostic["source_sha_matches"] = (diagnostic.get("manifest_source_sha256") == source_sha
                if "manifest_source_sha256" in diagnostic else None)
        if row.session_id == session_id and row.source_sha256 == source_sha:
            exports.append((row, directory, ""))
    good=[e for e in exports if e[0] is not None]
    if good:
        selected=max(good, key=lambda e: (e[0].review_revision, e[1].name))
        item, path, _ = selected
        # Do not mask a corrupted newer export by showing an older READY one.
        import re
        for rejected, directory, why in exports:
            if rejected is not None:
                continue
            match=re.search(r"review_r(\d+)_export_",directory.name)
            if match and int(match.group(1)) >= item.review_revision:
                return _rejected_verification(*why, item.review_revision, directory)
        if live and isinstance(live, tuple) and (live[0] != item.review_revision or live[1] != "COMPLETED"):
            state = "STALE" if live[0] >= item.review_revision else "INVALID"
            return Verification(state, "Wymaga eksportu", "Bieżąca rewizja/status GT różni się od eksportu.", item.review_revision, path)
        ok, reason = inspect_canvas(item.canvas, item.review_status)
        if not ok:
            return Verification("INCOMPLETE", "Niepełna MT+MZ", reason, item.review_revision, path)
        return Verification("READY", "Zatwierdzona", reason + "; GT asystowane", item.review_revision, path)
    if exports:
        _, directory, failure = exports[-1]
        return _rejected_verification(*failure, export_dir=directory)
    if live and isinstance(live, tuple):
        if live[1] == "COMPLETED":
            return Verification("NEEDS_EXPORT", "Eksport wymagany", "Zatwierdzono ocenę, lecz nie ma aktualnego eksportu MT+MZ.", live[0])
        if live[1] == "IN_PROGRESS":
            return Verification("IN_PROGRESS", "W toku", "Weryfikacja nie została zatwierdzona.", live[0])
    return Verification("NONE", "Do weryfikacji", "Brak kompletnej oceny MT+MZ powiązanej z archiwum.")


def paired_geometry_text(canvas: dict[str, Any] | None):
    """Return same-object pairs only. No result for missing MT/MZ is fabricated."""
    for r in (canvas or {}).get("rows", ()):
        if (not isinstance(r, dict) or not r.get("included") or
                r.get("post_nms_suppressed_raw") or r.get("outcome") != "LINKED_MT" or
                str(r.get("mz_status") or "").upper() in ("", "NOT_RUN", "AMBIGUOUS_SAMPLES")):
            continue
        iou = _number(r.get("polygon_iou_pct"), ceiling=100)
        nmce = _number(r.get("nmce_pct"))
        cer = _number(r.get("cer"))
        if iou is None or nmce is None or cer is None or not _clean_text(r.get("gt_text")):
            continue
        yield {
            "image_entry": str(r.get("image_entry") or ""),
            "object_id": str(r.get("object_id") or ""),
            "iou_pct": iou, "nmce_pct": nmce, "cer_pct": cer * 100,
            "exact": _clean_text(r.get("gt_text")) == _clean_text(r.get("mz_prediction")),
        }
