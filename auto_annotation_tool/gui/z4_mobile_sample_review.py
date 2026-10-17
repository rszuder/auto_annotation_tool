# Z4MOBREV007_POSE_QUALITY_WITHOUT_GT_CTA_20261016
# Z4MOBREV006_STABLE_VIEW_AUTO_GT_20261016
# Z4MOBREV005_POSE_POLYGON_OVERLAY_20261016
# Z4MOBREV004_OPERATOR_FIRST_UI_20261016
# Z4MOBREV003_VIEWPORT_ZOOM_PAN_20261016
# Z4MOBREV002_FIX01_DECISIONS_UI_20261016
# Z4MOBREV001_SIMPLE_REVIEW_20261016
"""Session → subject → evidence review. File IO and metrics run off the Tk thread."""
from __future__ import annotations

import csv
import json
import math
import os
import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from ..rectification.polygon_validator import PolygonValidator

from ..ranking.mobile_human_review import MobileReviewSession, align_plate_text, normalize_registration
from ..ranking.mobile_mt_invocations import DETECTION_STATUSES, detection_box_on_mt_input
from ..ranking.mobile_pose_metrics import POSE_GT_SCHEMA, compare_mt_pose_to_gt, validate_mt_quad
from ..ranking.mobile_package_experiments import MobilePackageExperimentStore, read_mobile_report_bundle
from ..ranking.mobile_thesis_report import export_thesis_bundle
from ..ranking.mobile_scientific_review import (
    make_scientific_summary, display_scientific_summary,
    session_conditions_text, write_scientific_companion,
)

REVIEW_LABELS = {"NOT_STARTED": "Nie rozpoczęto", "IN_PROGRESS": "W toku", "COMPLETED": "Zakończona"}
MODE_LABELS = {"blinded_gt_v1": "Zaślepiona GT", "assisted": "Asystowana (diagnostyczna)"}
VISIBILITY_LABELS = {"none": "0 — brak tablic", "one": "1 — jedna tablica",
                     "multiple": "2+ — kilka tablic", "uncertain": "? — nie wiem, ile tablic"}
HIDDEN_PREDICTION = "ukryta do czasu GT"
STAGE_LABELS = {"VALID_QUAD": "Poprawny obszar", "NO_DETECTION": "Brak detekcji", "DETECTION_INVALID_QUAD": "Błędna geometria",
                "NOT_RUN": "Nie uruchomiono", "NO_CHARACTERS": "Brak znaków", "READ": "Odczyt"}


def _observation_list_label(number, state, *, cancelled=False, execution_failed=False):
    """One readable row with a text/shape marker, independently of row colour.

    This is display-only: no sidecar GT or scientific denominator is changed.
    """
    prefix = f"{int(number):02d}"
    if state in {"MT ocenione", "Ocenione MT i MZ", "Gotowa"}:
        label = "MT i MZ ocenione" if state == "Ocenione MT i MZ" else "MT ocenione"
        return f"✓  {prefix}   {label}", "review_done"
    if state == "Poza pomiarem MT":
        if cancelled:
            label = "Próba przerwana"
        elif execution_failed:
            label = "Błąd wykonania"
        else:
            label = "Poza oceną MT"
        return f"—  {prefix}   {label}", "review_excluded"
    if state.startswith("Decyzje:"):
        return f"○  {prefix}   Dokończ ocenę", "review_pending"
    return f"○  {prefix}   Do oceny MT", "review_pending"


def _cancelled_mt_explanation(group):
    """Explain Android attempt lifecycle separately from the MT model outcome."""
    reasons = {str(row.get("cancel_reason") or "").strip().lower()
               for row in (getattr(group, "records", ()) or ()) if isinstance(row, dict)}
    recorded = [row for row in (getattr(group, "records", ()) or ())
                if isinstance(row, dict) and str(row.get("mt_status") or "").upper()
                in DETECTION_STATUSES]
    if "scene_superseded" in reasons:
        reason = "Telefon zastąpił tę scenę nowszą podczas przetwarzania."
    else:
        reason = "Telefon zakończył tę próbę przed ukończeniem przetwarzania."
    if recorded:
        observed = ("MT zapisał wykrycie i jego obrys Pose." if any(
                    str(row.get("mt_pose_status") or "").upper() == "VALID_QUAD"
                    for row in recorded) else "MT zapisał wykrycie tablicy.")
    else:
        observed = "Próba nie dostarcza ukończonego wyniku wykrywania."
    return (f"{reason} {observed} Dane można obejrzeć, ale nie wliczamy "
            "tej próby do skuteczności MT ani do oceny OCR.")


def _display(value, *, rate=False):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Tak" if value else "Nie"
    if rate:
        return f"{value * 100:.2f}%"
    return f"{value:.1f}" if isinstance(value, float) else str(value)


def _review_image_sources(kind, row, attempt, group, samples, available_names):
    """Opisuj rodzaj dowodu, nie kolejny 'model MT'. Usun duplikaty sciezek."""
    seen, rows = set(), []
    available = set(available_names or ())

    def add(label, entry, payload):
        if not entry or entry in seen or entry not in available:
            return
        seen.add(entry)
        rows.append((label, payload))

    full = [] if group is None else sorted(group.evidence_entries)
    preferred = attempt.get("mt_input_evidence_entry")
    ordered_full = ([preferred] if preferred in full else []) + [item for item in full if item != preferred]
    for i, entry in enumerate(ordered_full):
        label = ("Wejście MT — bieżąca próba" if entry == preferred else
                 f"Wejście MT — dodatkowy dowód {i + 1}")
        add(label, entry, {"image_entry": entry})

    if kind == "sample":
        add("Wycięta tablica (crop)", row.get("image_entry"), row)
    add("Zdjęcie źródłowe z telefonu", attempt.get("evidence_entry"), attempt)
    if kind == "attempt":
        related = [sample for sample in samples if sample.get("attempt_id") == row.get("id")]
        for i, sample in enumerate(related, 1):
            label = "Wycięta tablica (crop)" if len(related) == 1 else f"Wycięta tablica (crop {i})"
            add(label, sample.get("image_entry"), sample)
    return rows



def _ordered_operator_gt_quad(points, width, height):
    """Canonicalize NEW operator clicks using the project's polygon sorter.

    Only the manually collected GT is reordered. Recorded MT keypoints and
    historical/frozen GT are never reindexed or rewritten. Reject bad quads
    using the stricter, convex non-crossing GT validator.
    """
    try:
        w, h = float(width), float(height)
        if not (math.isfinite(w) and math.isfinite(h) and w > 0 and h > 0):
            raise ValueError("Nieprawidłowy rozmiar wejścia MT")
        if not isinstance(points, (list, tuple)) or len(points) != 4:
            raise ValueError("Wskaż dokładnie cztery narożniki")
        raw = tuple((float(p[0]), float(p[1])) for p in points)
        if (any(not math.isfinite(v) for xy in raw for v in xy)
                or any(not (0 <= x <= w and 0 <= y <= h) for x, y in raw)):
            raise ValueError("Narożniki muszą być poprawne i znajdować się na wejściu MT")
        ordered = PolygonValidator.order_points(list(raw))
        return validate_mt_quad(ordered, w, h)
    except (TypeError, ValueError, IndexError, OverflowError) as exc:
        raise ValueError(str(exc) or "Nieprawidłowe narożniki GT") from exc


def _pose_quad_on_mt_input(attempt, sample):
    """Zapisany polygon Pose: źródłowa klatka -> ROI/letterbox -> wejście MT.

    NIGDY nie tworzymy polygonu z BBOX. Brak zweryfikowanych czterech punktów
    oznacza None. Nie zmieniamy narożników oryginału.
    """
    import math
    if not isinstance(attempt, dict) or not isinstance(sample, dict):
        return None
    attempt_id = str(attempt.get("id") or attempt.get("attempt_id") or "")
    if not attempt_id or str(sample.get("attempt_id") or "") != attempt_id:
        return None
    geometry = sample.get("plate_geometry")
    geometry = geometry if isinstance(geometry, dict) else {}
    if geometry.get("available") is False:
        return None
    raw = geometry.get("plate_corners_norm") or sample.get("plate_corners_norm")
    if isinstance(raw, str):
        try:
            raw = [list(map(float, pair.split(":"))) for pair in raw.split(";")]
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, (tuple, list)) or len(raw) != 4:
        return None
    try:
        points = [(float(pair[0]), float(pair[1])) for pair in raw
                  if isinstance(pair, (tuple, list)) and len(pair) == 2]
        source_w = float(geometry.get("source_width_px") or sample["source_width_px"])
        source_h = float(geometry.get("source_height_px") or sample["source_height_px"])
        roi_left = float(attempt["roi_left"])
        roi_top = float(attempt["roi_top"])
        roi_right = float(attempt["roi_right"])
        roi_bottom = float(attempt["roi_bottom"])
        scale = float(attempt["input_scale"])
        pad_x = float(attempt["input_pad_x"])
        pad_y = float(attempt["input_pad_y"])
        input_w = float(attempt["input_width"])
        input_h = float(attempt["input_height"])
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return None
    numbers = [value for p in points for value in p] + [source_w, source_h,
               roi_left, roi_top, roi_right, roi_bottom, scale, pad_x,
               pad_y, input_w, input_h]
    if (len(points) != 4 or not all(math.isfinite(v) for v in numbers)
            or source_w <= 0 or source_h <= 0 or input_w <= 0 or input_h <= 0
            or scale <= 0 or roi_left < 0 or roi_top < 0
            or roi_right > source_w + 1 or roi_bottom > source_h + 1
            or roi_left >= roi_right or roi_top >= roi_bottom
            or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in points)):
        return None
    # Odrzucamy czteropunktowy zapis zdegenerowany, ale nie poprawiamy
    # kolejności/współrzędnych modelu automatycznie.
    area2 = sum(points[i][0] * points[(i + 1) % 4][1]
                - points[(i + 1) % 4][0] * points[i][1] for i in range(4))
    if abs(area2) <= 1e-8:
        return None
    src = [(x * source_w, y * source_h) for x, y in points]
    # Nie łączymy narożników cropa z inną detekcją / inną klatką.
    try:
        bbox = [float(attempt[k]) for k in
                ("plate_left", "plate_top", "plate_right", "plate_bottom")]
    except (ValueError, KeyError, TypeError):
        return None
    if not all(math.isfinite(v) for v in bbox):
        return None
    envelope = [min(x for x, _ in src), min(y for _, y in src),
                max(x for x, _ in src), max(y for _, y in src)]
    tolerance = max(12.0, 0.2 * max(bbox[2] - bbox[0], bbox[3] - bbox[1]))
    if max(abs(a - b) for a, b in zip(bbox, envelope)) > tolerance:
        return None
    return tuple(((x - roi_left) * scale + pad_x,
                  (y - roi_top) * scale + pad_y) for x, y in src)


def _pose_quad_from_mt_attempt(attempt):
    """Read ONLY source-frame MT keypoints from this exact detection record.

    The explicit v1 contract prevents mixing another detection's crop/Pose,
    and forbids reconstructing an MT polygon from its BBOX. New-format records
    with missing or malformed source geometry MUST NOT fall back to crop data.
    """
    if not isinstance(attempt, dict) or attempt.get("mt_pose_status") != "VALID_QUAD":
        return None
    if (attempt.get("mt_pose_coordinate_space") != "source_frame_normalized_v1"
            or attempt.get("mt_pose_corner_order") != "TL_TR_BR_BL"):
        return None
    raw = attempt.get("mt_pose_corners_norm")
    try:
        if isinstance(raw, str):
            pairs = [part.split(":") for part in raw.split(";")]
            if len(pairs) != 4 or any(len(pair) != 2 for pair in pairs):
                return None
            points = [(float(x), float(y)) for x, y in pairs]
        elif isinstance(raw, (list, tuple)) and len(raw) == 4:
            points = [(float(pair[0]), float(pair[1])) for pair in raw]
        else:
            return None
        source_w = float(attempt["mt_pose_source_width_px"])
        source_h = float(attempt["mt_pose_source_height_px"])
        roi_left, roi_top, roi_right, roi_bottom = (
            float(attempt[k]) for k in ("roi_left", "roi_top", "roi_right", "roi_bottom"))
        scale, pad_x, pad_y, input_w, input_h = (
            float(attempt[k]) for k in ("input_scale", "input_pad_x", "input_pad_y",
                                      "input_width", "input_height"))
    except (TypeError, ValueError, IndexError, KeyError, OverflowError):
        return None
    values = ([v for pair in points for v in pair]
              + [source_w, source_h, roi_left, roi_top, roi_right, roi_bottom,
                 scale, pad_x, pad_y, input_w, input_h])
    if (not all(math.isfinite(value) for value in values)
            or source_w <= 0 or source_h <= 0 or input_w <= 0 or input_h <= 0
            or scale <= 0 or roi_left < 0 or roi_top < 0
            or roi_right > source_w + 1 or roi_bottom > source_h + 1
            or roi_left >= roi_right or roi_top >= roi_bottom
            or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in points)):
        return None
    source = [(x * source_w, y * source_h) for x, y in points]
    # The bbox is an independent MT output, NOT the source of these points.
    # A loose bbox must not invalidate a valid Pose recorded for this attempt.
    transformed = tuple(((x - roi_left) * scale + pad_x,
                         (y - roi_top) * scale + pad_y) for x, y in source)
    try:
        return validate_mt_quad(transformed, input_w, input_h)
    except (TypeError, ValueError):
        return None


def _mt_pose_contract_declared(session, attempt):
    """A new-format export must never be silently rescued by legacy MZ data."""
    if "mt_pose_status" in attempt:
        return True
    schema = getattr(getattr(session, "bundle", None), "sample_schema", {})
    capabilities = schema.get("capabilities", {}) if isinstance(schema, dict) else {}
    return bool(isinstance(capabilities, dict) and capabilities.get("mt_pose_per_detection") is True)


def _linked_pose_quad_on_mt_input(session, attempt, selected_sample=None):
    """Prefer recorded MT Pose; use a linked crop only for legacy archives."""
    if not isinstance(attempt, dict):
        return None
    # The existence of this field declares the per-detection contract.
    # A broken new record cannot be silently rescued with data from MZ.
    if _mt_pose_contract_declared(session, attempt):
        return _pose_quad_from_mt_attempt(attempt)
    attempt_id = str(attempt.get("id") or attempt.get("attempt_id") or "")
    if not attempt_id or not session:
        return None
    samples = getattr(session, "samples", {})
    candidates = [selected_sample] if isinstance(selected_sample, dict) else []
    index = getattr(session, "sample_ids_by_attempt", {}) or {}
    ids = index.get(attempt_id) or [k for k, value in samples.items()
                                    if value.get("attempt_id") == attempt_id]
    candidates.extend(samples[k] for k in ids if k in samples)
    for sample in candidates:
        quad = _pose_quad_on_mt_input(attempt, sample)
        if quad is not None:
            return quad
    return None

def _pose_source_status(session, attempt):
    """Why this exact MT attempt has or lacks an auditable four-corner polygon.

    A bounding box is NEVER promoted to a polygon. A missing linked crop may
    mean the export lacks corner evidence; it does NOT prove MT predicted a box.
    """
    if not attempt:
        return "no_attempt", "Brak powiązanej detekcji MT."
    status = str(attempt.get("mt_status") or "").upper()
    if status not in DETECTION_STATUSES:
        return "no_detection", "Ten rekord nie zawiera detekcji MT do oceny geometrii."
    if _mt_pose_contract_declared(session, attempt):
        if _pose_quad_from_mt_attempt(attempt) is not None:
            return "mt_record_pose", "Dostępne są cztery rogi zapisane bezpośrednio z MT."
        if status == "DETECTION_INVALID_QUAD" or attempt.get("mt_pose_status") == "INVALID_QUAD":
            return "mt_invalid_quad", "Model nie podał prawidłowych czterech rogów."
        if attempt.get("mt_pose_status") == "VALID_QUAD":
            return "mt_pose_record_inconsistent", "Zapis Pose tej detekcji jest niekompletny lub nieprawidłowy."
        return "mt_pose_unavailable", "W tym rekordzie nie zapisano czterech rogów modelu."
    if _linked_pose_quad_on_mt_input(session, attempt) is not None:
        return "pose_available", "Historyczny Pose odczytany z powiązanej próbki MZ."
    aid = str(attempt.get("id") or attempt.get("attempt_id") or "")
    samples = getattr(session, "samples", {}) or {}
    linked_ids = (getattr(session, "sample_ids_by_attempt", {}) or {}).get(aid) or []
    linked = [samples[key] for key in linked_ids if key in samples]
    if not linked:
        linked = [value for value in samples.values() if str(value.get("attempt_id") or "") == aid]
    if status == "DETECTION_INVALID_QUAD":
        return "mt_invalid_quad", "MT nie podało prawidłowych czterech rogów."
    if not linked:
        return "no_linked_crop", (
            "W tej starszej sesji nie zapisano czterech rogów tej detekcji. "
            "Brak cropa nie oznacza, że model ich nie wyznaczył.")
    has_raw_corners = any(
        bool((sample.get("plate_geometry") if isinstance(sample.get("plate_geometry"), dict) else {}).get("plate_corners_norm")
             or sample.get("plate_corners_norm")) for sample in linked)
    if not has_raw_corners:
        return "no_saved_corners", "Powiązany crop istnieje, ale nie zapisano przy nim czterech narożników Pose."
    return "invalid_or_unlinked_corners", (
        "Narożniki istnieją w danych cropa, lecz nie przechodzą walidacji powiązania, "
        "współrzędnych lub transformacji do wejścia MT.")


def _pose_geometry_rows(session):
    """One audit row per MT attempt; numeric metrics only with independent manual GT.

    A crop or an incomplete GT never silently enters the denominator. No data is
    modified here and historical subjective pose_quality remains only in sidecar.
    """
    rows = []
    for attempt_id, row in session.attempts.items():
        decision = session.review.attempt_annotations.get(attempt_id, {})
        group = session.mt_invocations.get(str(row.get("mt_invocation_id") or ""))
        active = bool(group and group.executed and not group.cancelled and not group.execution_failed
                      and not session.cancelled(row))
        pred = (_linked_pose_quad_on_mt_input(session, row) if active and
                str(row.get("mt_status", "")).upper() in DETECTION_STATUSES else None)
        true_plate = decision.get("is_plate") is True and decision.get("evaluable") is not False
        image_entry = row.get("mt_input_evidence_entry")
        evidence_present = (image_entry in session.entry_names if hasattr(session, "entry_names") else bool(image_entry))
        pose_source_status, _ = _pose_source_status(session, row)
        unavailable_reason = str(decision.get("pose_gt_unavailable_reason") or "")
        eligible = bool(pred is not None and true_plate and evidence_present and not unavailable_reason)
        raw_gt = decision.get("pose_gt_quad_mt_input_px")
        status, metrics = "not_evaluable", None
        try:
            size = (float(row["input_width"]), float(row["input_height"]))
            pred_valid = validate_mt_quad(pred, *size) if pred is not None else None
        except (ValueError, TypeError, KeyError):
            pred_valid = None
        if not active:
            status = "source_not_evaluable"
        elif (str(row.get("mt_status") or "").upper() == "NO_DETECTION" and
              raw_gt and decision.get("pose_gt_schema") == POSE_GT_SCHEMA):
            try:
                invocation = session.invocation_annotation(str(row.get("mt_invocation_id") or ""))
                if (invocation.get("visible_plate_count") != "one" or
                        invocation.get("evaluable") is False):
                    status = "missed_detection_gt_cardinality_conflict"
                elif (size is None or decision.get("pose_gt_image_entry") != image_entry or
                        decision.get("pose_gt_input_size_px") != list(size)):
                    status = "missed_detection_gt_provenance_mismatch"
                else:
                    validate_mt_quad(raw_gt, *size)
                    status = "missed_detection_gt_saved"
            except (ValueError, TypeError, KeyError):
                status = "missed_detection_gt_invalid"
        elif pred_valid is None:
            status = "no_valid_pose"
        elif not evidence_present:
            status = "no_mt_input_evidence"
        elif not true_plate:
            status = "not_confirmed_plate"
        elif unavailable_reason and raw_gt:
            status = "gt_exclusion_conflict"
        elif unavailable_reason:
            status = "manual_gt_unavailable"
        elif not raw_gt:
            status = "missing_manual_gt"
        elif (decision.get("pose_gt_schema") != POSE_GT_SCHEMA or
              decision.get("pose_gt_image_entry") != row.get("mt_input_evidence_entry") or
              decision.get("pose_gt_input_size_px") != list(size)):
            status = "gt_provenance_mismatch"
        else:
            try:
                metrics = compare_mt_pose_to_gt(pred_valid, raw_gt, *size)
                status = "measured"
            except (ValueError, TypeError):
                status = "invalid_manual_gt"
        rows.append({
            "session_id": session.session_id,
            "source_archive_sha256": session.review.source_archive_sha256,
            "attempt_id": attempt_id,
            "mt_invocation_id": row.get("mt_invocation_id", ""),
            "mt_status": row.get("mt_status", ""),
            "mt_input_evidence_entry": row.get("mt_input_evidence_entry", ""),
            "pose_source_status": pose_source_status,
            "pose_gt_unavailable_reason": unavailable_reason,
            "eligible": eligible and pred_valid is not None,
            "metric_status": status,
            "gt_schema": decision.get("pose_gt_schema") or "",
            "pose_gt_review_mode": decision.get("pose_gt_review_mode") or "",
            "gt_quad_mt_input_px": json.dumps(raw_gt, ensure_ascii=False) if raw_gt else "",
            "pred_quad_mt_input_px": json.dumps(pred, ensure_ascii=False) if pred else "",
            "nmce_pct": metrics["nmce_pct"] if metrics else None,
            "polygon_iou": metrics["polygon_iou"] if metrics else None,
            "polygon_iou_pct": metrics["polygon_iou_pct"] if metrics else None,
            "mean_corner_error_px": metrics["mean_corner_error_px"] if metrics else None,
            "per_corner_errors_px": json.dumps(metrics["per_corner_errors_px"]) if metrics else "",
            "gt_envelope_diagonal_px": metrics["gt_envelope_diagonal_px"] if metrics else None,
        })
    return rows


def _pose_geometry_summary(session):
    rows = _pose_geometry_rows(session)
    measured = [row for row in rows if row["metric_status"] == "measured"]
    eligible = [row for row in rows if row["eligible"]]
    return {
        "pose_eligible": len(eligible),
        "pose_measured": len(measured),
        "pose_pending": len(eligible) - len(measured),
        "pose_manual_unavailable": sum(row["metric_status"] == "manual_gt_unavailable" for row in rows),
        "pose_nmce_mean_pct": sum(row["nmce_pct"] for row in measured) / len(measured) if measured else None,
        "pose_iou_mean_pct": sum(row["polygon_iou_pct"] for row in measured) / len(measured) if measured else None,
        "pose_no_geometry": sum(row["metric_status"] in {"no_valid_pose", "missed_detection_gt_saved",
                                  "missed_detection_gt_invalid", "missed_detection_gt_provenance_mismatch",
                                  "missed_detection_gt_cardinality_conflict"}
                                for row in rows),
        "missed_detection_manual_gt": sum(row["metric_status"] == "missed_detection_gt_saved" for row in rows),
    }


def _review_color_mix(base, foreground, amount=0.05):
    """Very subtle, theme-neutral Tk card tint; never hardcode a light-only palette."""
    try:
        a, b = (str(color).lstrip("#") for color in (base, foreground))
        if len(a) != 6 or len(b) != 6:
            return base
        x = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
        y = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
        return "#" + "".join(f"{round(p * (1 - amount) + q * amount):02x}" for p, q in zip(x, y))
    except (ValueError, TypeError):
        return base



def _primary_review_image_index(image_rows, attempt, group):
    """One unambiguous image for one attempt; never choose another MT record's frame."""
    if not isinstance(attempt, dict):
        return None
    entries = set(getattr(group, "evidence_entries", ()) or ())
    preferred = str(attempt.get("mt_input_evidence_entry") or "")
    if preferred and preferred in entries:
        for index, (_, item) in enumerate(image_rows or ()):
            if item.get("image_entry") == preferred:
                return index
    fallback = str(attempt.get("evidence_entry") or "")
    if fallback:
        for index, (_, item) in enumerate(image_rows or ()):
            if item.get("image_entry") == fallback or item.get("evidence_entry") == fallback:
                return index
    return None


class MobileSampleReviewWindow:
    def __init__(self, browser, report, bundle=None):
        self.browser, self.report = browser, report
        self.session = None
        self.stats = {}
        self.subject_key = ""
        self.current_record = None
        self.current_invocation = ""
        self._subject_ids = {}
        self._record_ids = {}
        self._closed = False
        self._saving = False
        self._close_requested = False
        self._pending_subject = ""
        self._retained_image_on_refresh = None
        self._rendering = False
        self._autosave_id = None
        self._image_token = 0
        self._image = None
        self._image_source_size = None
        self._image_entry = ""
        self._photo = None
        self._view_zoom = 1.0
        self._view_center = None
        self._view_fit_scale = 1.0
        self._view_pixel_scale = 1.0
        self._view_drag_at = None
        self._zoom_to_mt_pending = False
        self._pose_gt_cache_token = None
        self._pose_gt_points = []
        self._pose_gt_drag_index = None
        self._pose_gt_before_drag = None
        # One guided entry per selected MT image. Cancelling must not reopen
        # the editor on the next asynchronous refresh/autosave.
        self._pose_auto_token = None
        self._results = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mobile-review")
        palette = browser.palette
        self.bg = palette.get("panel", "#162013")
        self.fg = palette.get("fg", "#e9efdf")
        self.muted = palette.get("muted", self.fg)
        self.accent = palette.get("accent", self.fg)
        self.review_card_bg = _review_color_mix(self.bg, self.fg, 0.035)
        self.review_border = _review_color_mix(self.bg, self.fg, 0.19)
        self.window = tk.Toplevel(browser.window)
        self.window._aat_skip_window_recovery = True
        self.window.title("Weryfikacja próbek z telefonu")
        width = min(1680, self.window.winfo_screenwidth() - 60)
        height = min(960, self.window.winfo_screenheight() - 85)
        self.window.geometry(f"{width}x{height}+25+25")
        self.window.minsize(min(1050, self.window.winfo_screenwidth() - 60), 670)
        self.window.configure(bg=self.bg)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Destroy>", self._destroyed, add="+")
        self.actions = []
        self._build()
        self._poll_id = self.window.after(40, self._poll)
        source = Path(bundle.path if bundle and bundle.source_archive_sha256 == report.source_archive_sha256 else report.source_path)
        expected_hash = report.source_archive_sha256
        def load():
            # Revalidate on opening; the stored report may outlive its archive.
            fresh = read_mobile_report_bundle(source)
            if expected_hash and fresh.source_archive_sha256 != expected_hash:
                raise ValueError("Plik źródłowy nie odpowiada SHA-256 zapisanego raportu. Zaimportuj właściwą sesję.")
            session = MobileReviewSession(fresh)
            # Operator wybrał jednolitą ocenę asystowaną.
            # Historyczne decyzje i GT zostają; blokowany tryb przechodzi przez
            # audytowaną, jednostronną migrację (review_mode_origin).
            converted = False
            if session.review.review_mode == "blinded_gt_v1":
                if session.review.review_mode_locked:
                    session.reveal_predictions_for_review()
                else:
                    session.set_review_mode("assisted")
                converted = True
            store = MobilePackageExperimentStore(browser.store.root_dir)
            store.apply_human_review(session)
            return session, session.statistics(), converted
        self._submit(load, self._loaded)

    def _label(self, parent, text="", **kwargs):
        # Inherit the parent surface so labels do not punch rectangular holes
        # into the softly shaded review cards on Windows / both app themes.
        bg = kwargs.pop("bg", None)
        fg = kwargs.pop("fg", self.fg)
        if bg is None:
            try:
                bg = parent.cget("bg")
            except (tk.TclError, AttributeError, KeyError):
                bg = self.bg
        return tk.Label(parent, text=text, bg=bg, fg=fg,
                        anchor="w", justify="left", **kwargs)

    def _review_section(self, parent):
        return tk.Frame(parent, bg=self.review_card_bg, padx=13, pady=11,
                        highlightthickness=1, highlightbackground=self.review_border, bd=0)

    def _button(self, parent, text, command, **grid):
        button = ttk.Button(parent, text=text, command=command, state="disabled")
        button.grid(**grid, padx=3, pady=3)
        self.actions.append(button)
        return button

    def _table(self, parent, columns, widths, *, height=8):
        frame = ttk.Frame(parent)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height,
                            selectmode="browse", style="MobileReview.Treeview")
        for name, width in zip(columns, widths):
            tree.heading(name, text=name)
            tree.column(name, width=width, minwidth=45, stretch=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return frame, tree

    def _build(self):
        # Older GUI probes construct the window without calling __init__.
        # Resolve the same theme defaults here as well (no global style reset).
        self.accent = getattr(self, "accent", (getattr(self.browser, "palette", {}) or {}).get("accent", self.fg))
        self.review_card_bg = getattr(self, "review_card_bg", _review_color_mix(self.bg, self.fg, 0.035))
        self.review_border = getattr(self, "review_border", _review_color_mix(self.bg, self.fg, 0.19))
        style = None
        try:
            style = ttk.Style(self.window)
            style.configure("MobileReview.Treeview", rowheight=28, font=("Segoe UI", 9))
            style.configure("MobileReview.Treeview.Heading", font=("Segoe UI", 9, "bold"))
            style.configure("MobileReview.TRadiobutton", background=self.review_card_bg,
                            foreground=self.fg, font=("Segoe UI", 10))
            style.map("MobileReview.TRadiobutton", background=[("active", self.review_card_bg)])
        except tk.TclError:
            pass
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)
        header = tk.Frame(self.window, bg=self.bg, padx=12, pady=8)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.session_label = self._label(header, "Wczytywanie sesji…", font=("Segoe UI", 12, "bold"))
        self.session_label.grid(row=0, column=0, sticky="ew")
        self.progress_label = self._label(header, font=("Segoe UI", 9))
        self.progress_label.grid(row=1, column=0, sticky="ew")
        self._button(header, "Eksport wyników", self.export, row=0, column=1)
        self._button(header, "Zakończ pełną ocenę", self.complete, row=0, column=2)
        self.notice_label = self._label(self.window, wraplength=1150, font=("Segoe UI", 9))
        self.notice_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))

        tabs = ttk.Notebook(self.window)
        tabs.grid(row=2, column=0, sticky="nsew", padx=10)
        review = tk.Frame(tabs, bg=self.bg)
        review.columnconfigure(0, weight=0, minsize=225)
        review.columnconfigure(1, weight=1, minsize=360)
        review.columnconfigure(2, weight=0, minsize=415)
        review.rowconfigure(0, weight=1)
        tabs.add(review, text="Weryfikacja")

        left = tk.Frame(review, bg=self.review_card_bg, padx=8, pady=8,
                        highlightthickness=1, highlightbackground=self.review_border)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        self._label(left, "OBSERWACJE", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(3, 3))
        self._label(left, "✓ Oceniona   ○ Do oceny   — Wyłączona",
                    font=("Segoe UI", 8), fg=self.muted, wraplength=245).grid(
                        row=1, column=0, sticky="ew", pady=(0, 8))
        # GT text is assessed in its own panel. A redundant, mostly empty GT
        # column made the short state labels unreadable on ordinary screens.
        frame, self.subject_tree = self._table(
            left, ("Obserwacja · ocena",), (246,), height=18)
        frame.grid(row=2, column=0, sticky="nsew")
        try:
            if style is not None:
                style.configure("MobileReview.Observations.Treeview", rowheight=32,
                                font=("Segoe UI", 10))
                style.configure("MobileReview.Observations.Treeview.Heading",
                                font=("Segoe UI", 9, "bold"))
                self.subject_tree.configure(style="MobileReview.Observations.Treeview")
        except tk.TclError:
            pass
        self.subject_tree.bind("<<TreeviewSelect>>", self._select_subject)
        self._button(left, "Następna do oceny", self.next_pending, row=3, column=0, sticky="ew")

        viewer = tk.Frame(review, bg=self.bg)
        viewer.grid(row=0, column=1, sticky="nsew", padx=(0, 9))
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(4, weight=1)
        image_bar = tk.Frame(viewer, bg=self.bg)
        image_bar.grid(row=0, column=0, sticky="ew")
        image_bar.columnconfigure(0, weight=1)
        self.record_label = self._label(image_bar, "Wybrany zapis: —", font=("Segoe UI", 9))
        self.record_label.grid(row=0, column=0, sticky="ew")
        # Internal source-index controller only. A technical list of evidence
        # entries is not an operator choice and must not appear in the UI.
        self.image_choice = ttk.Combobox(image_bar, state="readonly", width=24)
        self.target_nav = tk.Frame(image_bar, bg=self.bg)
        self.target_nav.grid(row=1, column=0, sticky="w", pady=(2, 1))
        self.target_previous = ttk.Button(self.target_nav, text="← Poprzedni obszar",
                                          command=lambda: self._switch_detected_area(-1))
        self.target_previous.pack(side="left")
        self.target_position = self._label(self.target_nav, "Obszar 1 z 1", font=("Segoe UI", 9, "bold"))
        self.target_position.pack(side="left", padx=10)
        self.target_next = ttk.Button(self.target_nav, text="Następny obszar →",
                                      command=lambda: self._switch_detected_area(1))
        self.target_next.pack(side="left")
        self.target_nav.grid_remove()
        self.image_help = self._label(viewer,
            "Zdjęcie przypisane do ocenianego obszaru. Niebieski obrys wskazał telefon.",
            font=("Segoe UI", 9), wraplength=700)
        self.image_help.grid(row=1, column=0, sticky="ew", pady=(1, 3))
        zoom_bar = tk.Frame(viewer, bg=self.bg)
        zoom_bar.grid(row=2, column=0, sticky="ew", pady=(3, 1))
        ttk.Button(zoom_bar, text="−", width=4, command=lambda: self.zoom_image(1 / 1.5)).pack(side="left", padx=2)
        ttk.Button(zoom_bar, text="+", width=4, command=lambda: self.zoom_image(1.5)).pack(side="left", padx=2)
        ttk.Button(zoom_bar, text="Dopasuj", command=self.fit_image).pack(side="left", padx=(5, 3))
        ttk.Button(zoom_bar, text="Zbliż do tablicy", command=self.zoom_to_mt_detection).pack(side="left", padx=(4, 8))
        self.zoom_value = self._label(zoom_bar, "×1.0", font=("Segoe UI", 9, "bold"))
        self.zoom_value.pack(side="left")
        self.canvas = tk.Canvas(viewer, height=520, bg="#101820", highlightthickness=0, cursor="hand2")
        self.canvas.grid(row=4, column=0, sticky="nsew", pady=3)
        self.canvas.bind("<Configure>", lambda event: self._paint_image())
        self.canvas.bind("<MouseWheel>", self._wheel_zoom)
        self.canvas.bind("<Button-4>", self._wheel_zoom)
        self.canvas.bind("<Button-5>", self._wheel_zoom)
        self.canvas.bind("<ButtonPress-1>", self._pan_begin)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._pan_end)
        self.canvas.bind("<Double-Button-1>", lambda event: "break" if self.pose_edit_var.get() else self.fit_image())
        self.canvas.bind("<ButtonPress-3>", lambda event: self._pan_begin(event, force_pan=True))
        self.canvas.bind("<B3-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-3>", self._pan_end)
        self._label(viewer, "Kółko: powiększ  •  prawy przycisk: przesuń  •  podwójne kliknięcie: dopasuj",
                    font=("Segoe UI", 9), fg=self.muted).grid(row=5, column=0, sticky="w", pady=(1, 3))

        right_host = tk.Frame(review, bg=self.bg)
        right_host.grid(row=0, column=2, sticky="nsew")
        right_host.columnconfigure(0, weight=1)
        right_host.rowconfigure(0, weight=1)
        sidebar_scroll = tk.Canvas(right_host, bg=self.bg, bd=0, highlightthickness=0)
        sidebar_scroll.grid(row=0, column=0, sticky="nsew")
        self.review_sidebar_scroll = sidebar_scroll
        sidebar_bar = ttk.Scrollbar(right_host, orient="vertical", command=sidebar_scroll.yview)
        sidebar_bar.grid(row=0, column=1, sticky="ns")
        sidebar_scroll.configure(yscrollcommand=sidebar_bar.set)
        right = tk.Frame(sidebar_scroll, bg=self.bg, padx=5, pady=5)
        right.columnconfigure(0, weight=1)
        inside = sidebar_scroll.create_window((0, 0), window=right, anchor="nw")
        right.bind("<Configure>", lambda event: sidebar_scroll.configure(scrollregion=sidebar_scroll.bbox("all")))
        sidebar_scroll.bind("<Configure>", lambda event: sidebar_scroll.itemconfigure(inside, width=event.width))
        self.subject_label = self._label(right, font=("Segoe UI", 11, "bold"), wraplength=370)
        self.subject_label.grid(row=0, column=0, sticky="ew", pady=(4, 11), padx=(3, 0))

        # MT: zawsze te same dwie proste oceny, bez dropdownow nieznanej funkcji.
        mt = self._review_section(right)
        mt.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        mt.columnconfigure(0, weight=1)
        self._label(mt, "01  ·  WYKRYCIE TABLICY", font=("Segoe UI", 10, "bold"),
                    fg=self.accent).grid(row=0, column=0, sticky="ew")
        self.invocation_label = self._label(mt, "—", font=("Segoe UI", 9),
                                            fg=self.muted, wraplength=370)
        self.invocation_label.grid(row=1, column=0, sticky="ew", pady=(3, 4))
        self.show_input_button = self._button(mt, "Pokaż całe zdjęcie", self.show_invocation_input,
                                               row=2, column=0, sticky="w")
        self.show_input_button.grid_remove()
        self.mt_count_question = self._label(mt, "Ile tablic widzisz na zdjęciu?",
                    font=("Segoe UI", 10, "bold"), wraplength=370)
        self.mt_count_question.grid(row=3, column=0, sticky="ew", pady=(9, 2))
        self.mt_count_hint = self._label(mt, "Policz tablice, nie zaznaczenia modelu.",
                    font=("Segoe UI", 9), fg=self.muted, wraplength=370)
        self.mt_count_hint.grid(row=4, column=0, sticky="ew")
        self.invocation_count_value = tk.StringVar(value="")
        self.invocation_count_radios = []
        count_group = tk.Frame(mt, bg=self.review_card_bg)
        count_group.grid(row=5, column=0, sticky="ew", pady=(3, 5))
        for index, (value, label) in enumerate(VISIBILITY_LABELS.items()):
            radio = ttk.Radiobutton(count_group, text=label, variable=self.invocation_count_value,
                                    value=value, command=self.choose_visible_plate_count,
                                    style="MobileReview.TRadiobutton")
            radio.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 12), pady=1)
            self.invocation_count_radios.append(radio)
        self.mt_count_group = count_group
        # Nie rysujemy starego dropdownu. Zostaje tylko jako zgodny odczyt dla diagnostyki/testow.
        self.invocation_choice = ttk.Combobox(mt, state="disabled", values=list(VISIBILITY_LABELS.values()))
        self.invocation_error_label = self._label(mt, font=("Segoe UI", 9), wraplength=350)
        self.invocation_error_label.grid(row=6, column=0, sticky="ew")
        self.invocation_error_label.grid_remove()
        self.mt_section_separator = ttk.Separator(mt, orient="horizontal")
        self.mt_section_separator.grid(row=7, column=0, sticky="ew", pady=(7, 9))
        self.detection_question = self._label(mt,
            "Czy zaznaczony obszar jest tablicą?",
            font=("Segoe UI", 10, "bold"), wraplength=370)
        self.detection_question.grid(row=8, column=0, sticky="ew", pady=(2, 2))
        self.detection_context = self._label(mt, "Oceń niebieskie zaznaczenie na zdjęciu.",
                                              font=("Segoe UI", 9), fg=self.muted,
                                              wraplength=370)
        self.detection_context.grid(row=9, column=0, sticky="ew")
        self.detection_choice = tk.StringVar(value="")
        self.detection_radios = []
        decision_group = tk.Frame(mt, bg=self.review_card_bg)
        self.mt_detection_group = decision_group
        decision_group.grid(row=10, column=0, sticky="ew", pady=(3, 1))
        for index, (label, value) in enumerate((("Tak, to tablica", "yes"),
                ("Nie, to nie tablica", "no"), ("Nie mogę ustalić, czy to tablica", "skip"))):
            radio = ttk.Radiobutton(decision_group, text=label, variable=self.detection_choice,
                                     value=value, command=self.save_detection_choice,
                                     style="MobileReview.TRadiobutton")
            radio.grid(row=index, column=0, sticky="w", pady=1)
            self.detection_radios.append(radio)
        self._mt_scored_controls = (
            self.mt_count_question, self.mt_count_hint, self.mt_count_group,
            self.mt_section_separator, self.detection_question,
            self.detection_context, self.mt_detection_group)

        # The second question is answered independently from the first.
        # Only an explicit positive answer here starts the one-shot drawing.
        # Absence of Pose permits detection assessment, but not corner metrics.
        self.pose_gt_host = self._review_section(right)
        self.pose_gt_host.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.pose_gt_host.columnconfigure(0, weight=1)
        self.pose_gt_title = self._label(self.pose_gt_host,
            "02  ·  OBRYS TABLICY", font=("Segoe UI", 10, "bold"),
            fg=self.accent, wraplength=370)
        self.pose_gt_title.grid(row=0, column=0, sticky="ew")
        self.pose_gt_question = self._label(self.pose_gt_host,
            "Czy możesz wskazać cztery rogi tablicy?",
            font=("Segoe UI", 10, "bold"), wraplength=370)
        self.pose_gt_question.grid(row=1, column=0, sticky="ew", pady=(8, 3))
        self.pose_gt_hint = self._label(self.pose_gt_host,
            "Zaznacz własny obrys, aby sprawdzić wskazanie modelu.",
            font=("Segoe UI", 9), fg=self.muted, wraplength=370)
        self.pose_gt_hint.grid(row=2, column=0, sticky="ew", pady=(0, 3))
        self.pose_edit_var = tk.BooleanVar(value=False)
        self.pose_gt_answer = tk.StringVar(value="")
        self.pose_gt_radios = []
        answer_group = tk.Frame(self.pose_gt_host, bg=self.review_card_bg)
        self.pose_answer_group = answer_group
        answer_group.grid(row=3, column=0, sticky="ew", pady=(2, 4))
        for value, label in (
                ("mark", "Tak, zaznaczę cztery rogi"),
                ("unavailable", "Nie mam pewności — pomiń ocenę obrysu")):
            radio = ttk.Radiobutton(answer_group, text=label,
                variable=self.pose_gt_answer, value=value, command=self._choose_pose_gt_answer,
                style="MobileReview.TRadiobutton")
            radio.pack(anchor="w", pady=2)
            self.pose_gt_radios.append(radio)
        # Compatibility: older synthetic GUI probes inspect this widget by name.
        self.pose_gt_unavailable_button = self.pose_gt_radios[1]
        # A button is useful only for correction of existing GT or cancellation
        # of an active draft. Initial drawing requires no additional CTA.
        self.pose_edit_button = ttk.Button(self.pose_gt_host,
            text="Popraw zaznaczenie", command=self._toggle_pose_gt_edit)
        self.pose_edit_button.grid(row=4, column=0, sticky="w", pady=(2, 3))
        self.pose_edit_button.grid_remove()
        self.pose_gt_reset = ttk.Button(self.pose_gt_host,
            text="Usuń zapisany obrys", command=self._clear_pose_gt)
        self.pose_gt_reset.grid(row=5, column=0, sticky="w", pady=(0, 3))
        self.pose_gt_reset.grid_remove()
        self.pose_gt_progress = self._label(self.pose_gt_host, "", font=("Segoe UI", 9), fg=self.muted)
        self.pose_gt_progress.grid(row=6, column=0, sticky="ew")
        self.pose_gt_metric = self._label(self.pose_gt_host, "",
                                          font=("Segoe UI", 10, "bold"), wraplength=370)
        self.pose_gt_metric.grid(row=7, column=0, sticky="ew", pady=(2, 0))
        self.pose_gt_instruction = self._label(self.pose_gt_host,
            "Kliknij cztery rogi w dowolnej kolejności. Program sam uporządkuje punkty "
            "i zapisze obrys po czwartym kliknięciu.",
            font=("Segoe UI", 9), fg=self.muted, wraplength=370)
        self.pose_gt_instruction.grid(row=8, column=0, sticky="ew", pady=(4, 0))
        self.pose_gt_instruction.grid_remove()

        # MZ: zawsze widoczna predykcja (o ile mozna), GT i wyjasnienie.
        mz = self._review_section(right)
        mz.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        mz.columnconfigure(0, weight=1)
        self._label(mz, "03  ·  ODCZYT NUMERU", font=("Segoe UI", 10, "bold"),
                    fg=self.accent).grid(row=0, column=0, sticky="ew")
        self.result_context = self._label(mz, "Telefon odczytał:", font=("Segoe UI", 9), fg=self.muted)
        self.result_context.grid(row=1, column=0, sticky="ew")
        self.prediction_label = self._label(mz, "—", font=("Segoe UI", 16, "bold"))
        self.prediction_label.grid(row=2, column=0, sticky="ew", pady=(1, 5))
        self.crop_preview_button = ttk.Button(mz, text="Pokaż wyciętą tablicę",
                                               command=self._show_crop_preview)
        self.crop_preview_button.grid(row=3, column=0, sticky="w", pady=(0, 5))
        self.crop_preview_button.grid_remove()
        self._crop_preview_row = None
        self._crop_preview_window = None
        self.gt_prompt_label = self._label(mz,
            "Numer tablicy — GT operatora (nie wynik MZ)", font=("Segoe UI", 10, "bold"))
        self.gt_prompt_label.grid(row=4, column=0, sticky="ew")
        self.gt_var = tk.StringVar()
        self.gt_entry = ttk.Entry(mz, textvariable=self.gt_var, font=("Segoe UI", 14), width=15)
        self.gt_entry.grid(row=5, column=0, sticky="ew")
        # Jedyna akcja operatora to wpisanie GT; zapis bez dodatkowego CTA.
        # Wynik MZ nie staje się GT bez niezależnego odczytania tablicy.
        self.gt_entry.bind("<Return>", lambda event: self.save_gt())
        self.gt_entry.bind("<FocusOut>", lambda event: self.save_gt())
        self.subject_eval_choice = tk.StringVar(value="assess")
        self.subject_eval_radios = []
        evaluable_group = tk.Frame(mz, bg=self.review_card_bg)
        evaluable_group.grid(row=6, column=0, sticky="ew", pady=(3, 5))
        for label, value in (("Oceń odczyt numeru", "assess"),
                             ("Pomiń ocenę odczytu numeru", "exclude")):
            radio = ttk.Radiobutton(evaluable_group, text=label,
                    variable=self.subject_eval_choice, value=value,
                    command=self.save_subject_eval_choice,
                    style="MobileReview.TRadiobutton")
            radio.pack(anchor="w", pady=1)
            self.subject_eval_radios.append(radio)
        self._label(mz, "Pominięcie odczytu nie zmienia oceny wykrycia i obrysu.",
                    font=("Segoe UI", 9), fg=self.muted,
                    wraplength=370).grid(row=7, column=0, sticky="ew", pady=(2, 6))
        self._label(mz, "Notatka (opcjonalna)").grid(row=8, column=0, sticky="w")
        self.note_var = tk.StringVar()
        self.note_entry = ttk.Entry(mz, textvariable=self.note_var)
        self.note_entry.grid(row=9, column=0, sticky="ew", pady=(0, 3))
        self.gt_var.trace_add("write", self._schedule_autosave)
        self.note_var.trace_add("write", self._schedule_autosave)

        comparison = tk.Frame(right, bg=self.bg)
        comparison.grid(row=4, column=0, sticky="ew", pady=(1, 4))
        comparison.columnconfigure(0, weight=1)
        self.alignment_label = self._label(comparison, font=("Segoe UI", 9), wraplength=350)
        self.alignment_label.grid(row=0, column=0, sticky="ew")
        self.alignment_text = tk.Text(comparison, height=2, width=27, font=("Consolas", 10), bg=self.bg, fg=self.fg,
                                     bd=0, highlightthickness=0, wrap="none", state="disabled", takefocus=False)
        self.alignment_text.grid(row=1, column=0, sticky="ew")
        self.alignment_text.tag_configure("incorrect", foreground=self.browser.error)
        self.alignment_text.tag_configure("missing", foreground=self.browser.warning)
        self.alignment_text.tag_configure("extra", foreground=self.browser.warning)

        self._details_open = False
        self.record_details_toggle = ttk.Button(right, text="Pokaż zapisy techniczne (detekcje i cropy)",
                                                 command=self._toggle_record_details)
        self.record_details_toggle.grid(row=5, column=0, sticky="ew", pady=(3, 2))
        self.record_detail_host = tk.Frame(right, bg=self.bg)
        self.record_detail_host.grid(row=6, column=0, sticky="ew", pady=(0, 3))
        frame, self.record_tree = self._table(self.record_detail_host,
            ("Rodzaj", "Id", "MT / MZ", "Predykcja", "Ocena"), (55, 62, 85, 98, 81), height=3)
        frame.grid(row=0, column=0, sticky="ew")
        self.record_detail_host.grid_remove()
        self.record_tree.bind("<<TreeviewSelect>>", self._select_record)

        # Kazda kontrolka panelu odbiera rolke, niezaleznie od focusu; zoom obrazu osobno.
        self._bind_sidebar_wheel(sidebar_scroll)
        self._bind_sidebar_wheel(right)

        # Scientific results first; the legacy/raw tables remain available on demand.
        summary = tk.Frame(tabs, bg=self.bg)
        summary.rowconfigure(1, weight=1)
        summary.rowconfigure(2, weight=1)
        summary.columnconfigure(0, weight=1)
        tabs.add(summary, text="Wyniki naukowe")
        science_top = tk.Frame(summary, bg=self.bg)
        science_top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        science_top.columnconfigure(0, weight=1)
        self.science_caption = self._label(science_top, "Podsumowanie pomiaru i jego ograniczenia",
                                           font=("Segoe UI", 11, "bold"))
        self.science_caption.grid(row=0, column=0, sticky="ew")
        self.science_toggle = ttk.Button(science_top, text="Pokaż tabelę techniczną",
                                         command=self._toggle_scientific_details)
        self.science_toggle.grid(row=0, column=1, sticky="e")
        self.science_view = tk.Text(summary, wrap="word", font=("Segoe UI", 10),
                                    relief="flat", padx=22, pady=12, bg=self.review_card_bg,
                                    fg=self.fg, insertbackground=self.fg, state="disabled",
                                    highlightthickness=1, highlightbackground=self.review_border,
                                    selectbackground=self.accent)
        self.science_view.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(12, 0), pady=(3, 12))
        self.science_scrollbar = ttk.Scrollbar(summary, orient="vertical", command=self.science_view.yview)
        self.science_scrollbar.grid(row=1, column=1, rowspan=2, sticky="ns", padx=(0, 12), pady=(3, 12))
        self.science_view.configure(yscrollcommand=self.science_scrollbar.set)
        self.science_view.tag_configure("title", font=("Segoe UI", 15, "bold"), spacing3=8)
        self.science_view.tag_configure("heading", font=("Segoe UI", 11, "bold"),
                                         foreground=self.accent, spacing1=10, spacing3=4)
        self.science_view.tag_configure("metric", font=("Segoe UI", 11, "bold"), spacing3=2)
        self.science_view.tag_configure("normal", spacing3=3)
        self.science_view.tag_configure("caption", foreground=self.muted, spacing3=7)
        self.science_view.tag_configure("warning", foreground=self.fg, spacing3=4)
        self.science_view.tag_configure("subtitle", foreground=self.accent, spacing3=5)
        frame, self.stats_tree = self._table(summary, ("Zakres", "Miara", "Wynik"), (150, 480, 150), height=20)
        self._science_raw_host = frame
        self._science_raw_open = False
        # Only one of overview/raw technical tree is visible.
        details = tk.Frame(tabs, bg=self.bg)
        details.rowconfigure(1, weight=1)
        details.columnconfigure(0, weight=1)
        tabs.add(details, text="Warunki i źródła")
        reviewer = tk.Frame(details, bg=self.bg)
        reviewer.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self._label(reviewer, "Osoba weryfikująca (opcjonalny identyfikator)").grid(row=0, column=0, padx=5)
        self.reviewer_var = tk.StringVar()
        ttk.Entry(reviewer, textvariable=self.reviewer_var).grid(row=0, column=1)
        self._button(reviewer, "Zapisz", self.save_reviewer, row=0, column=2)
        self.mode_choice = ttk.Combobox(reviewer, state="disabled", values=list(MODE_LABELS.values()))
        details_top = tk.Frame(details, bg=self.bg)
        details_top.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        details_top.columnconfigure(0, weight=1)
        details_top.rowconfigure(1, weight=1)
        self._label(details_top, "Najważniejsze parametry eksperymentu",
                    font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="ew", pady=(4, 8))
        self.conditions_view = tk.Text(details_top, wrap="word", height=11,
                                        font=("Segoe UI", 10), bg=self.review_card_bg,
                                        fg=self.fg, relief="flat", padx=16, pady=13,
                                        highlightthickness=1, highlightbackground=self.review_border,
                                        state="disabled")
        self.conditions_view.grid(row=1, column=0, sticky="nsew")
        self.details_toggle = ttk.Button(details_top, text="Pokaż pełną proweniencję techniczną",
                                         command=self._toggle_provenance_details)
        self.details_toggle.grid(row=2, column=0, sticky="w", pady=(9, 5))
        frame, self.details_tree = self._table(details, ("Pole", "Wartość"), (340, 750), height=20)
        self._provenance_raw_host = frame
        self._provenance_raw_open = False
        self.status_var = tk.StringVar(value="Odczyt pełnego indeksu i kontrola SHA-256…")
        self._label(self.window, textvariable=self.status_var, font=("Segoe UI", 9), wraplength=1250).grid(
            row=3, column=0, sticky="ew", padx=12, pady=8)

    def _bind_sidebar_wheel(self, widget):
        """Lokalne zdarzenia potomkow: bez bind_all i bez przechwytywania zoomu obrazu."""
        widget.bind("<MouseWheel>", self._on_sidebar_wheel, add="+")
        widget.bind("<Button-4>", self._on_sidebar_wheel, add="+")
        widget.bind("<Button-5>", self._on_sidebar_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_sidebar_wheel(child)

    def _on_sidebar_wheel(self, event):
        if getattr(event, "num", 0) in (4, 5):
            steps = -1 if event.num == 4 else 1
        else:
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return "break"
            steps = -max(1, round(delta / 120)) if delta > 0 else max(1, round(-delta / 120))
        self.review_sidebar_scroll.yview_scroll(steps, "units")
        return "break"

    def _toggle_record_details(self):
        self._details_open = not self._details_open
        if self._details_open:
            self.record_detail_host.grid()
        else:
            self.record_detail_host.grid_remove()
        self.record_details_toggle.configure(text=(
            "Ukryj zapisy techniczne" if self._details_open else
            "Pokaż zapisy techniczne (detekcje i cropy)"))

    def _submit(self, work, done, *, saving=False):
        if self._closed:
            return
        if saving:
            self._saving = True
            self.gt_entry.configure(state="disabled")
            self.note_entry.configure(state="disabled")
            self.mode_choice.configure(state="disabled")
            self.invocation_choice.configure(state="disabled")
            self.pose_edit_button.configure(state="disabled")
            for radio in getattr(self, "pose_gt_radios", ()):
                radio.configure(state="disabled")
            self.pose_gt_reset.configure(state="disabled")
            for radio in self.subject_eval_radios + self.detection_radios + self.invocation_count_radios:
                radio.configure(state="disabled")
            for button in self.actions:
                button.configure(state="disabled")
        def task():
            try:
                self._results.put((done, work(), None, saving))
            except Exception as error:
                self._results.put((done, None, str(error), saving))
        self._executor.submit(task)

    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                done, result, error, saving = self._results.get_nowait()
                if saving:
                    self._saving = False
                    self.gt_entry.configure(state="normal")
                    self.note_entry.configure(state="normal")
                    for button in self.actions:
                        button.configure(state="normal")
                if error:
                    self.status_var.set(error)
                    self._close_requested = False
                else:
                    done(result)
                    if saving and self._close_requested:
                        self.close()
                        return
                if self.session:
                    self._sync_review_controls()
        except queue.Empty:
            pass
        self._poll_id = self.window.after(40, self._poll)

    def _loaded(self, result):
        self.session, self.stats, self._review_was_converted = result
        for button in self.actions:
            button.configure(state="normal")
        session = self.session
        self.reviewer_var.set(session.review.reviewer_id)
        self.session_label.configure(text=f"Sesja: {session.session_id}")
        context = dict(session.bundle.metadata, **session.bundle.report_payload)
        context.update(session.bundle.collection_session or context.get("research_collection", {}))
        state = str(context.get("state") or context.get("session_state") or context.get("status") or
                    session.bundle.experiment_session.get("status") or "").upper()
        notices = list(session.warnings)
        if state in {"PARTIAL", "ERROR"}:
            notices.insert(0, f"Sesja niekompletna: {state}. Wyniki obejmują wyłącznie zapisane dowody.")
        elif session.bundle.manifest.get("collection_complete") is False:
            notices.insert(0, "Sesja niekompletna. Wyniki obejmują wyłącznie zapisane dowody.")
        self._source_notices = notices
        self.notice_label.configure(
            text="\n".join(notices) if notices else "Wybierz obserwację, a następnie odpowiedz na pytania po prawej. Zapis jest automatyczny.",
            fg=self.browser.warning if notices else self.muted)
        self._subject_ids = {f"subject-{index}": key for index, key in enumerate(session.subjects)}
        self._refresh_subject_rows()
        self._refresh_stats()
        self._populate_details()
        self._sync_review_controls()
        self.status_var.set("Ocena asystowana: GT zapisuje się automatycznie. MT i MZ oceniaj na wybranym obrazie."
                            + (" Zmieniono tryb historycznej oceny na asystowaną; GT zachowano." if self._review_was_converted else ""))
        if self._subject_ids:
            first = next(iter(self._subject_ids))
            self.subject_tree.selection_set(first)
            self.subject_tree.focus(first)

    def _refresh_subject_rows(self):
        self._subject_stats = {row["subject_key"]: row for row in self.stats["subjects"]}
        self._science_data = make_scientific_summary(self.session, self.stats, _pose_geometry_rows(self.session))
        for index, (iid, key) in enumerate(self._subject_ids.items(), 1):
            decision = self.session.review.subjects.get(key, {})
            state = "Odczyt pominięty" if decision.get("evaluable") is False else "Gotowa" if decision.get("ground_truth") else "Oczekuje"
            if decision.get("draft_ground_truth") and not self.session.predictions_visible(key):
                state = "Szkic GT"
            pending = self._subject_stats.get(key, {}).get("pending_decisions", 0)
            stage = self._science_data["subjects"].get(key, {})
            if stage.get("mt_complete"):
                state = stage["label"]
            elif stage.get("mt_status") == "Poza pomiarem MT":
                state = "Poza pomiarem MT"
            elif stage.get("mt_pending"):
                state = "MT do oceny"
            elif pending and decision.get("ground_truth"):
                state = f"Decyzje: {pending}"
            # A single full-width row: explicit marker + observation number +
            # meaningful status, not colour or the unrelated OCR draft.
            groups = [self.session.mt_invocations.get(self.session.invocation_by_attempt.get(aid))
                      for aid in self.session.subjects[key].get("attempts", ())]
            groups = [group for group in groups if group is not None]
            cancelled = bool(groups) and all(group.cancelled for group in groups)
            failed = bool(groups) and all(group.execution_failed for group in groups)
            label, tag = _observation_list_label(index, state, cancelled=cancelled,
                                                  execution_failed=failed)
            if self.subject_tree.exists(iid):
                self.subject_tree.item(iid, values=(label,), tags=(tag,))
            else:
                self.subject_tree.insert("", "end", iid=iid, values=(label,), tags=(tag,))

    def _select_subject(self, event=None):
        selected = self.subject_tree.selection()
        key = self._subject_ids.get(selected[0]) if selected else None
        if not key or key == self.subject_key:
            return
        if self._saving:
            self._pending_subject = key
            return
        self.save_gt()
        if self._saving:
            self._pending_subject = key
            return
        self._leave_pose_gt_edit_on_navigation()
        self._close_crop_preview()
        self._pose_auto_token = None
        self.subject_key = key
        self._render_subject()
        # Selecting a DIFFERENT observation starts a new questionnaire at the
        # first question. Autosave/refresh of the same record keeps scroll.
        try:
            self.review_sidebar_scroll.yview_moveto(0)
        except (tk.TclError, AttributeError):
            pass

    def _render_subject(self):
        key = self.subject_key
        if not key:
            return
        subject = self.session.subjects[key]
        decision = self.session.review.subjects.get(key, {})
        self._rendering = True
        self.gt_var.set(self.session.subject_draft(key))
        self.note_var.set(decision.get("note", ""))
        self._rendering = False
        number = list(self.session.subjects).index(key) + 1
        legacy = " • tożsamość legacy" if subject["legacy_identity"] else ""
        stats = self._subject_stats.get(key, {})
        invocations = {self.session.invocation_by_attempt[item] for item in subject["attempts"]}
        invocation_count = sum(self.session.mt_invocations[item].executed for item in invocations) if self.session.attempts_available else None
        self.subject_label.configure(text=f"Obserwacja {number} z {len(self.session.subjects)}")
        visible = self.session.predictions_visible(key)
        self._sync_review_controls()
        if not visible:
            self.alignment_label.configure(text="Ocena zaślepiona: wynik MZ pozostaje ukryty. Aby przejść na prostą ocenę z predykcjami, użyj przycisku u góry.")
            self.alignment_text.configure(state="normal")
            self.alignment_text.delete("1.0", "end")
            self.alignment_text.configure(state="disabled")
        old = self.current_record
        # Odbudowa tabeli po radiobuttonie NIE moze resetowac kadru ani zoomu.
        self._retained_image_on_refresh = ((old, self._image_entry)
            if old and self._image is not None and self._image_entry else None)
        self.record_tree.delete(*self.record_tree.get_children())
        self._record_ids = {}
        for kind, keys, records in (("attempt", subject["attempts"], self.session.attempts), ("sample", subject["samples"], self.session.samples)):
            for record_id in keys:
                row = records[record_id]
                iid = f"record-{len(self._record_ids)}"
                self._record_ids[iid] = (kind, record_id)
                annotation = (self.session.review.attempt_annotations if kind == "attempt" else self.session.review.sample_annotations).get(record_id, {})
                state = "Nie tablica" if annotation.get("is_plate") is False else "Pominięta" if annotation.get("evaluable") is False else annotation.get("plate_visibility", "GT zapisane" if kind == "sample" and decision.get("ground_truth") else "Do oceny")
                state = {"visible": "Widoczna", "invisible": "Niewidoczna", "uncertain": "Niejednoznaczna"}.get(state, state)
                if self.session.cancelled(row):
                    state = "Próba przerwana"
                invocation = self.session.invocation_by_attempt.get(record_id if kind == "attempt" else row.get("attempt_id"), "")
                group = self.session.mt_invocations.get(invocation)
                if group and group.execution_failed and not group.cancelled:
                    state = "Błąd wykonania MT"
                index = row.get("mt_detection_index")
                label = f"Detekcja {int(index) + 1}" if kind == "attempt" and index not in (None, "") else "Rekord MT" if kind == "attempt" else "Crop"
                identity = f"{invocation} / {record_id}" if invocation and invocation != record_id else record_id
                self.record_tree.insert("", "end", iid=iid, values=(label, identity,
                    self._record_stages(row, group), (row.get("prediction") or "brak odczytu") if visible else HIDDEN_PREDICTION, state))
        if self._record_ids:
            default = next((iid for iid, value in self._record_ids.items() if value[0] == "sample"), next(iter(self._record_ids)))
            iid = next((iid for iid, value in self._record_ids.items() if value == old), default)
            if self._record_ids[iid] != old:
                self._retained_image_on_refresh = None
            self.current_record = None
            self.record_tree.selection_set(iid)
            self.record_tree.focus(iid)
        else:
            self.current_record = None
            self.prediction_label.configure(text="Brak zapisanego wyniku MZ")
            self._image = None
            self._paint_image()

    def _record_stages(self, row, group):
        mt = ("Próba przerwana" if group and group.cancelled else
              "Błąd wykonania MT" if group and group.execution_failed else STAGE_LABELS.get(row.get("mt_status"), ""))
        # MZ status itself can disclose a no-read before GT, even with OCR hidden.
        mz = STAGE_LABELS.get(row.get("mz_status"), "") if self.session.predictions_visible(self.subject_key) else ""
        return " / ".join(stage for stage in (mt, mz) if stage)

    def _select_record(self, event=None):
        selected = self.record_tree.selection()
        record = self._record_ids.get(selected[0]) if selected else None
        if not record or record == self.current_record:
            return
        retained = self._retained_image_on_refresh
        self._retained_image_on_refresh = None
        # A real record change ends GT editing. A refresh of the SAME record
        # (after autosave) must preserve the edit state and Zoom/Pan.
        if not retained or retained[0] != record:
            self._leave_pose_gt_edit_on_navigation()
            self._close_crop_preview()
            self._pose_auto_token = None
        self.current_record = record
        kind, key = record
        row = (self.session.attempts if kind == "attempt" else self.session.samples)[key]
        self._image_rows = []
        attempt = row if kind == "attempt" else self.session.attempts.get(row.get("attempt_id"), {})
        self.current_invocation = self.session.invocation_by_attempt.get(attempt.get("id"), "")
        group = self.session.mt_invocations.get(self.current_invocation)
        self._image_rows = _review_image_sources(
            kind, row, attempt, group,
            [self.session.samples[sid] for sid in self.session.subjects[self.subject_key]["samples"]],
            self.session.entry_names,
        )
        self.image_choice.configure(values=[title for title, _ in self._image_rows])
        source_index = _primary_review_image_index(self._image_rows, attempt, group)
        if source_index is not None:
            self.image_choice.current(source_index)
        else:
            self.image_choice.set("Brak zdjęcia powiązanego z obszarem")
        self._sync_detected_area_navigation()
        self._sync_crop_preview_source(attempt, row if kind == "sample" else None)
        self.record_label.configure(text="Zdjęcie do oceny")
        # Ocena odczytu MZ nie znika tylko dlatego, ze operator wybral rekord MT.
        # Przy probie MT pokazujemy powiazany crop, jesli istnieje.
        result_row = row
        if kind == "attempt":
            for candidate in (self.session.samples[sid]
                              for sid in self.session.subjects[self.subject_key]["samples"]):
                if candidate.get("attempt_id") == key:
                    result_row = candidate
                    break
        self._result_row = result_row
        gt = self.session.review.subjects.get(self.subject_key, {}).get("ground_truth", "")
        prediction = str(result_row.get("prediction") or "").strip()
        mz_status = str(result_row.get("mz_status", "")).upper()
        self._result_prediction = prediction if mz_status != "NOT_RUN" else ""
        if not self.session.predictions_visible(self.subject_key):
            self.prediction_label.configure(text="Ukryta — ocena zaślepiona")
        elif self.session.cancelled(result_row):
            self.prediction_label.configure(text="Próba przerwana")
        elif mz_status == "NOT_RUN":
            self.prediction_label.configure(text="MZ nie uruchomiono")
        else:
            self.prediction_label.configure(text=prediction or "Brak odczytu")
        self.result_context.configure(text=(
            "MZ — brak ukończonego pomiaru w przerwanej próbie" if self.session.cancelled(result_row) else
            "MZ nie uruchomiono — poniżej wpisz niezależny GT" if mz_status == "NOT_RUN" else
            "Wynik powiązanego cropa MZ" if result_row is not row else
            "Wynik wybranego zapisu MZ"))
        self.gt_prompt_label.configure(text=(
            "Numer z tablicy (GT operatora; MZ nie uruchomiono)" if mz_status == "NOT_RUN" else
            "Numer z tablicy (GT operatora, niezależny od MZ)"))
        self.alignment_text.configure(state="normal")
        self.alignment_text.delete("1.0", "end")
        if not self.session.predictions_visible(self.subject_key):
            self.alignment_label.configure(text="Wpisz GT z obrazu — zapis jest automatyczny.")
        elif self.session.cancelled(result_row):
            self.alignment_label.configure(text=(
                "Próba przerwana. Wyniku OCR nie oceniamy (CER/Exact nie dotyczy); "
                "ewentualny GT służy tylko dokumentacji."))
        elif mz_status == "NOT_RUN":
            self.alignment_label.configure(text="MZ nie został uruchomiony w tej próbie. Oceń widoczność tablicy dla MT.")
        elif self.session.review.subjects.get(self.subject_key, {}).get("evaluable") is False:
            self.alignment_label.configure(text=(
                "Znaki nieczytelne — odczyt MZ/CER i skuteczność ALPR poza oceną. "
                "Detekcja i polygon MT pozostają do osobnej oceny."))
        elif gt:
            match = align_plate_text(gt, prediction)
            outcome = "Brak odczytu" if not match.prediction else "Poprawny odczyt" if match.exact_match else "Niepoprawny odczyt"
            self.alignment_label.configure(text=f"{outcome} • predykcja: {prediction or '—'}\n"
                f"Poprawnie rozpoznane: {match.correct_characters} • błędnie rozpoznane: {match.incorrect_characters} • "
                f"brakujące: {match.missing_characters} • nadmiarowe: {match.extra_characters} • CER: {_display(match.cer, rate=True)}")
            for prefix, field in (("GT    : ", "ground_truth"), ("Odczyt: ", "prediction")):
                self.alignment_text.insert("end", prefix)
                for item in match.alignment:
                    self.alignment_text.insert("end", (item[field] or "·") + " ", item["kind"])
                self.alignment_text.insert("end", "\n")
        else:
            self.alignment_label.configure(text=f"Predykcja: {prediction or 'brak odczytu'} • wpisz GT dla tej tablicy.")
        self.alignment_text.configure(state="disabled")
        self._sync_review_controls()
        if retained and retained[0] == record and self._image is not None:
            # Rewizja GT/MT nie zmienia obrazu ani transformacji Zoom/Pan.
            for index, (_, candidate) in enumerate(self._image_rows):
                entry = candidate.get("image_entry") or candidate.get("evidence_entry")
                if (entry == retained[1] == self._image_entry and
                        index == _primary_review_image_index(self._image_rows, attempt, group)):
                    self.image_choice.current(index)
                    self._set_image_help()
                    self._paint_image()
                    return
        self._load_image()

    def _sync_review_controls(self):
        if not self.session:
            return
        intro = ("Sprawdź, czy telefon znalazł tablicę. Jeśli możesz rozpoznać jej rogi, "
                 "wskaż je, aby ocenić dokładność obrysu. Na końcu sprawdź odczyt numeru.")
        warnings = getattr(self, "_source_notices", [])
        self.notice_label.configure(text=intro + ("\n" + "\n".join(warnings) if warnings else ""),
                                    fg=self.browser.warning if warnings else self.fg)
        can_show = bool(self.subject_key and self.session.predictions_visible(self.subject_key))
        # Brak CTA kopiującego MZ do GT. Jedynym źródłem GT pozostaje operator.
        self._sync_subject_eval_choice()
        self.invocation_error_label.grid_remove()
        if self.current_invocation:
            group = self.session.mt_invocations[self.current_invocation]
            if group.cancelled:
                self.invocation_label.configure(text="Status próby: przerwana — poza oceną skuteczności MT")
                self.invocation_error_label.configure(
                    text=_cancelled_mt_explanation(group), fg=self.muted)
                self.invocation_error_label.grid()
            elif not group.executed:
                self.invocation_label.configure(text="MT nie uruchomiono — poza oceną skuteczności")
                self.invocation_error_label.configure(
                    text="Brak ukończonego wywołania modelu. Nie przypisuj mu błędu wykrywania.",
                    fg=self.muted)
                self.invocation_error_label.grid()
            elif group.execution_failed:
                self.invocation_label.configure(text="Błąd wykonania MT — poza oceną skuteczności")
                error = " ".join("; ".join(group.execution_errors).split())
                error = error[:157] + "…" if len(error) > 160 else error
                self.invocation_error_label.configure(
                    text=f"Wywołanie technicznie nieukończone; nie jest to wynik jakości modelu. {error}",
                    fg=self.browser.warning)
                self.invocation_error_label.grid()
            else:
                self.invocation_label.configure(
                    text=f"Wynik MT: {group.detection_count} "
                         f"{'wykryta tablica' if group.detection_count == 1 else 'wykrytych tablic'}")
            annotation = self.session.invocation_annotation(self.current_invocation)
            self.invocation_choice.set("Brak dawnej oceny liczby tablic" if annotation.get("decision_source") == "legacy_cardinality_unknown"
                                       else VISIBILITY_LABELS.get(annotation.get("visible_plate_count"), "Oceń całe wejście MT"))
            self.invocation_count_value.set(annotation.get("visible_plate_count", ""))
            if group.execution_failed:
                self.invocation_choice.set("Nie wymaga oceny MT")
            allowed = not (self._saving or group.cancelled or not group.executed or group.execution_failed)
            self.invocation_choice.configure(state="readonly" if allowed else "disabled")
            for radio in self.invocation_count_radios:
                radio.configure(state="normal" if allowed else "disabled")
            # No phantom questions that are disabled and can never be answered:
            # display a lifecycle explanation instead for excluded invocations.
            for widget in getattr(self, "_mt_scored_controls", ()):
                if allowed:
                    widget.grid()
                else:
                    widget.grid_remove()
        else:
            self.invocation_label.configure(text="MT: nie ma zapisu wywołania dla tego obrazu")
            self.invocation_choice.set("")
            self.invocation_choice.configure(state="disabled")
            self.invocation_count_value.set("")
            for radio in self.invocation_count_radios:
                radio.configure(state="disabled")
            for widget in getattr(self, "_mt_scored_controls", ()):
                widget.grid_remove()
        self._sync_detection_choice()
        self._sync_pose_gt_controls()

    def save_detection_choice(self):
        """Zapis jednej czytelnej oceny operatora dla detekcji/cropa.
        Nie zastępuje ona pytania o liczbę tablic na całym wejściu MT.
        """
        if not self.session or not self.current_record or self._saving:
            return
        kind, record_id = self._active_detection_target()
        row = (self.session.attempts if kind == "attempt" else self.session.samples).get(record_id, {})
        if kind == "attempt" and str(row.get("mt_status", "")).upper() not in DETECTION_STATUSES:
            return  # Bez detekcji nie ma obszaru, który można uznać za tablicę.
        choices = {
            "yes": {"plate_visibility": "visible", "is_plate": True, "evaluable": True},
            "no": {"plate_visibility": "invisible", "is_plate": False, "evaluable": False},
            "skip": {"plate_visibility": "uncertain", "is_plate": None, "evaluable": False},
        }
        answer = self.detection_choice.get()
        decision = choices.get(answer)
        if decision is None:
            return
        # Answering the presence question merely unlocks the next question.
        # Never hide the predicted outline before the operator has *explicitly*
        # answered that the corners are identifiable on this image.
        def after_save():
            if answer == "yes" and kind == "attempt":
                self.status_var.set("Tablica potwierdzona. Odpowiedz teraz na pytanie 2 o jej rogi.")
        if answer != "yes":
            self._leave_pose_gt_edit_on_navigation()
        saved = (self.session.review.attempt_annotations if kind == "attempt"
                 else self.session.review.sample_annotations).get(record_id, {})
        if all(saved.get(name) == value for name, value in decision.items()):
            after_save()
            self._sync_review_controls()
            return
        self._change(lambda: self.session.annotate(kind, record_id, **decision), after=after_save)

    def _active_detection_target(self):
        """Na obrazie MT oceń próbę MT, a na cropie — sam crop MZ."""
        kind, record_id = self.current_record or (None, None)
        if kind == "sample" and self.session:
            sample = self.session.samples.get(record_id, {})
            attempt_id = str(sample.get("attempt_id") or "")
            group = self.session.mt_invocations.get(self.current_invocation)
            if (attempt_id in self.session.attempts and group
                    and self._image_entry in group.evidence_entries):
                return "attempt", attempt_id
        return kind, record_id

    def _pose_attempt_context(self):
        """Ocena polygonu zawsze należy do attempt_id, nigdy do cropa MZ."""
        if not self.session or not self.current_record or not self.current_invocation:
            return None
        kind, record_id = self.current_record
        sample = self.session.samples.get(record_id, {}) if kind == "sample" else None
        attempt_id = (str(sample.get("attempt_id") or "") if sample is not None else record_id)
        attempt = self.session.attempts.get(attempt_id)
        group = self.session.mt_invocations.get(self.current_invocation)
        if not attempt or not group or self.session.cancelled(attempt):
            return None
        if group.cancelled or not group.executed or group.execution_failed:
            return None
        if self._image_entry not in group.evidence_entries:
            return None
        if self._image_entry not in {entry.get("mt_input_evidence_entry") for entry in group.records}:
            return None
        try:
            valid_size = self._image_source_size == (
                float(attempt["input_width"]), float(attempt["input_height"]))
        except (KeyError, ValueError, TypeError):
            return None
        if not valid_size or str(attempt.get("mt_status") or "").upper() not in DETECTION_STATUSES:
            return None
        # Manual GT is independent of a four-corner MT prediction. BBOX is
        # never used as a synthetic model polygon.
        return attempt_id

    def _missed_plate_attempt_context(self):
        """One real missed plate: exact MT input, not a fictitious detection.

        One no-detection invocation has exactly one record; multiple visible
        plates need a separate future multi-GT annotation model. We do not
        guess which plate an unindexed GT belongs to.
        """
        if not self.session or not self.current_record or not self.current_invocation:
            return None
        kind, attempt_id = self.current_record
        if kind != "attempt":
            return None
        attempt = self.session.attempts.get(attempt_id)
        group = self.session.mt_invocations.get(self.current_invocation)
        if not attempt or not group or str(attempt.get("mt_status") or "").upper() != "NO_DETECTION":
            return None
        if (group.cancelled or not group.executed or group.execution_failed or
                group.detection_count != 0 or len(group.records) != 1 or
                str(group.records[0].get("id")) != attempt_id or
                self.session.cancelled(attempt)):
            return None
        getter = getattr(self.session, "invocation_annotation", None)
        if not callable(getter):
            return None
        verdict = getter(self.current_invocation)
        if (verdict.get("visible_plate_count") != "one" or verdict.get("evaluable") is False):
            return None
        entry = str(attempt.get("mt_input_evidence_entry") or "")
        if not entry or entry != self._image_entry or entry not in group.evidence_entries:
            return None
        try:
            size = float(attempt["input_width"]), float(attempt["input_height"])
        except (ValueError, TypeError, KeyError):
            return None
        if size[0] <= 0 or size[1] <= 0 or self._image_source_size != size or self._image is None:
            return None
        return attempt_id

    def _gt_target_is_confirmed(self, attempt_id):
        """Positive detected region OR one operator-confirmed missed plate."""
        if not attempt_id or not self.session:
            return False
        if self._missed_plate_attempt_context() == attempt_id:
            return True
        decision = self.session.review.attempt_annotations.get(attempt_id, {})
        return decision.get("is_plate") is True and decision.get("evaluable") is not False

    def _pose_gt_attempt_context(self):
        """Exact original MT input for the *same* attempt; never annotate a crop.

        The parent helper validates link, 4 Pose corners, status and dimensions.
        Here we additionally require the attempt's own explicit input evidence,
        not a different frame from the same MT invocation.
        """
        try:
            attempt_id = self._missed_plate_attempt_context() or self._pose_attempt_context()
        except (AttributeError, KeyError, TypeError):
            return None  # Synthetic older GUI probes may not have a complete session.
        if not attempt_id:
            return None
        attempt = self.session.attempts.get(attempt_id, {})
        if not attempt.get("mt_input_evidence_entry") or self._image_entry != attempt["mt_input_evidence_entry"]:
            return None
        decision = self.session.review.attempt_annotations.get(attempt_id, {})
        if decision.get("is_plate") is False or decision.get("evaluable") is False:
            return None
        return attempt_id

    def _ensure_pose_gt_points(self, attempt_id):
        """Load only manually annotated GT bound to the exact source/input size."""
        if not attempt_id:
            self._pose_gt_cache_token = None
            self._pose_gt_points = []
            return
        attempt = self.session.attempts[attempt_id]
        token = (attempt_id, str(attempt.get("mt_input_evidence_entry")))
        if self._pose_gt_cache_token == token:
            return
        self._pose_gt_cache_token = token
        self._pose_gt_points = []
        decision = self.session.review.attempt_annotations.get(attempt_id, {})
        try:
            width, height = float(attempt["input_width"]), float(attempt["input_height"])
            if (decision.get("pose_gt_schema") == POSE_GT_SCHEMA
                    and decision.get("pose_gt_image_entry") == token[1]
                    and decision.get("pose_gt_input_size_px") == [width, height]):
                self._pose_gt_points = list(validate_mt_quad(
                    decision.get("pose_gt_quad_mt_input_px"), width, height))
        except (ValueError, TypeError, KeyError):
            self._pose_gt_points = []

    def _sync_pose_gt_controls(self):
        if not self.session:
            return
        attempt_id = self._pose_gt_attempt_context()
        self._ensure_pose_gt_points(attempt_id)
        decision = self.session.review.attempt_annotations.get(attempt_id, {}) if attempt_id else {}
        # For an MT input with no Pose, the record decision is still relevant.
        if not attempt_id and self.current_record:
            kind, key = self._active_detection_target()
            if kind == "attempt":
                decision = self.session.review.attempt_annotations.get(key, {})
        confirmed = self._gt_target_is_confirmed(attempt_id)
        if not confirmed:
            if self.pose_edit_var.get():
                self._leave_pose_gt_edit_on_navigation()
                self._paint_image()
            # Keep step 02 visible so the questionnaire never jumps 01 -> 03.
            # This panel is informational only; cancellation is NOT a negative
            # model prediction or an invitation to fabricate matching GT.
            self.pose_gt_host.grid()
            self.pose_gt_title.configure(text="02  ·  OBRYS TABLICY")
            group = self.session.mt_invocations.get(self.current_invocation)
            if group and group.cancelled:
                question = "Nie oceniamy obrysu w przerwanej próbie"
                hint = ("Obrys zapisany przez MT możesz obejrzeć na zdjęciu. "
                        "Próba nie weszła do pomiaru jakości; GT, IoU i NMCE "
                        "nie są wymagane.")
            elif group and (not group.executed or group.execution_failed):
                question = "Obrys poza oceną — brak ukończonego MT"
                hint = "Nie ma wyniku MT, który można porównać z GT."
            else:
                question = "Najpierw potwierdź tablicę w kroku 01"
                hint = "Jeśli MT wskazał tablicę, po jej potwierdzeniu możesz zaznaczyć cztery rogi GT."
            self.pose_gt_question.configure(text=question)
            self.pose_gt_hint.configure(text=hint)
            for widget in (self.pose_answer_group, self.pose_edit_button, self.pose_gt_reset,
                           self.pose_gt_progress, self.pose_gt_metric,
                           self.pose_gt_instruction):
                widget.grid_remove()
            return
        self.pose_gt_host.grid()
        self.pose_answer_group.grid()
        self.pose_gt_progress.grid()
        self.pose_gt_metric.grid()
        missed = (str(self.session.attempts[attempt_id].get("mt_status") or "").upper()
                  == "NO_DETECTION")
        self.pose_gt_title.configure(text=("02  ·  OBRYS POMINIĘTEJ TABLICY" if missed
                                      else "02  ·  OBRYS TABLICY"))
        self.pose_gt_question.configure(text=(
            "Czy możesz zaznaczyć cztery rogi tablicy pominiętej przez MT?" if missed
            else "Czy możesz wskazać cztery rogi tablicy?"))
        unavailable = bool(decision.get("pose_gt_unavailable_reason"))
        can_edit = bool(attempt_id and self._image is not None and not self._saving and not unavailable)
        if self.pose_edit_var.get() and not can_edit:
            self._leave_pose_gt_edit_on_navigation()
            self._paint_image()
        count = len(self._pose_gt_points)
        self.pose_gt_answer.set("unavailable" if unavailable else
                                "mark" if attempt_id and (count == 4 or self.pose_edit_var.get()) else "")
        for radio in self.pose_gt_radios:
            radio.configure(state="normal" if attempt_id and not self._saving else "disabled")
        show_edit = bool(can_edit and (count == 4 or self.pose_edit_var.get()))
        self.pose_edit_button.configure(state="normal" if show_edit else "disabled",
            text="Anuluj oznaczanie" if self.pose_edit_var.get() else
                 "Popraw zaznaczenie")
        if show_edit:
            self.pose_edit_button.grid()
        else:
            self.pose_edit_button.grid_remove()
        if can_edit and count == 4:
            self.pose_gt_reset.configure(state="normal")
            self.pose_gt_reset.grid()
        else:
            self.pose_gt_reset.configure(state="disabled")
            self.pose_gt_reset.grid_remove()
        if not attempt_id:
            source_row = None
            if self.current_record:
                kind, record_id = self.current_record
                if kind == "attempt":
                    source_row = self.session.attempts.get(record_id)
                elif kind == "sample":
                    sample = self.session.samples.get(record_id, {})
                    source_row = self.session.attempts.get(sample.get("attempt_id"))
            if source_row and self._image_entry == source_row.get("mt_input_evidence_entry"):
                _, reason = _pose_source_status(self.session, source_row)
                self.pose_gt_hint.configure(text=("Porównanie obrysów jest niedostępne dla tego zapisu. "
                    "Nadal możesz ocenić wykrycie i odczyt numeru."))
            else:
                self.pose_gt_hint.configure(text=(
                    "Obrys ocenisz na pełnym zdjęciu. Wybierz «Wejście MT — bieżąca próba»."))
            self.pose_gt_progress.configure(text="Brak danych do oceny obrysu")
            self.pose_gt_metric.configure(text="Porównanie obrysów niedostępne")
            return
        attempt = self.session.attempts[attempt_id]
        has_pose = _linked_pose_quad_on_mt_input(self.session, attempt) is not None
        if unavailable:
            self.pose_gt_hint.configure(text=(
                "Pominięto ręczne oznaczanie narożników. Ocena wykrycia MT pozostaje niezależna."))
        elif missed:
            self.pose_gt_hint.configure(text=(
                "Rzeczywisty obrys GT został zapisany. MT nie wykrył tej tablicy." if count == 4 else
                "Wskaż rogi tablicy na zdjęciu. MT jej nie wykrył; nie będzie porównania IoU/NMCE."))
        elif count == 4:
            self.pose_gt_hint.configure(text=(
                "Zapisano cztery rogi. Możesz poprawić zaznaczenie." if has_pose else
                "Zapisano cztery rogi GT. Brak obrysu modelu MT do porównania."))
        elif self.pose_edit_var.get():
            self.pose_gt_hint.configure(text=(
                "Zaznacz cztery rogi. Obrys modelu jest chwilowo ukryty, "
                "aby nie sugerować położenia punktów."))
        elif has_pose:
            self.pose_gt_hint.configure(text=(
                "Wskaż własne rogi GT, a porównamy je z obrysem MT."))
        else:
            self.pose_gt_hint.configure(text=(
                "Możesz zapisać prawdziwe rogi GT również bez obrysu modelu MT."))
        self.pose_gt_progress.configure(text=(
            "Obrys: bez oceny (wybór operatora)" if unavailable else
            f"Zaznaczone rogi: {count}/4" + (
                " • przeciągnij punkt, aby poprawić" if count == 4 and self.pose_edit_var.get() else
                " • zapisano" if count == 4 else
                " • kliknij kolejny róg na zdjęciu" if self.pose_edit_var.get() else "")))
        instruction = getattr(self, "pose_gt_instruction", None)
        if instruction is not None:
            if self.pose_edit_var.get():
                instruction.grid()
            else:
                instruction.grid_remove()
        if hasattr(self, "pose_gt_title"):
            self.pose_gt_title.configure(fg=self.accent if self.pose_edit_var.get() else self.fg)
        if count == 4:
            if not has_pose:
                self.pose_gt_metric.configure(text=(
                    "GT zapisane • MT nie wykrył tablicy • IoU/NMCE: —" if missed else
                    "GT zapisane • brak obrysu Pose MT • IoU/NMCE: —"))
            else:
                try:
                    width, height = float(attempt["input_width"]), float(attempt["input_height"])
                    pred = _linked_pose_quad_on_mt_input(self.session, attempt)
                    measured = compare_mt_pose_to_gt(pred, self._pose_gt_points, width, height)
                    self.pose_gt_metric.configure(text=(
                        f"Błąd położenia rogów: {measured['nmce_pct']:.2f}%  •  "
                        f"Zgodność obrysu: {measured['polygon_iou_pct']:.2f}%"))
                except (ValueError, TypeError, KeyError):
                    self.pose_gt_metric.configure(text="Nie można porównać obrysów")
        else:
            self.pose_gt_metric.configure(text="")
        # Keep this card focused: show drawing help and results only when relevant.
        if unavailable or count == 4 or self.pose_edit_var.get():
            self.pose_gt_progress.grid()
        else:
            self.pose_gt_progress.grid_remove()
        if count == 4:
            self.pose_gt_metric.grid()
        else:
            self.pose_gt_metric.grid_remove()

    def _maybe_begin_guided_pose_gt(self):
        """Enter drawing only after an explicit response to the corner question.

        This helper must never be invoked on load/refresh/selection; the saved
        presence decision alone is not permission to hide the model overlay.
        """
        if not self.session or self._saving or self.pose_edit_var.get():
            return False
        attempt_id = self._pose_gt_attempt_context()
        if not attempt_id or self._image is None:
            return False
        decision = self.session.review.attempt_annotations.get(attempt_id, {})
        if (not self._gt_target_is_confirmed(attempt_id)
                or decision.get("pose_gt_unavailable_reason")):
            return False
        self._ensure_pose_gt_points(attempt_id)
        if len(self._pose_gt_points) == 4:
            return False
        token = (attempt_id, self._image_entry)
        if getattr(self, "_pose_auto_token", None) == token:
            return False
        self._pose_auto_token = token
        self._toggle_pose_gt_edit()
        if self.pose_edit_var.get():
            self.status_var.set("Wskaż cztery rogi tablicy w dowolnej kolejności. Po czwartym punkcie zapis nastąpi sam.")
            return True
        return False

    def _choose_pose_gt_answer(self):
        """An operator *answers a question* instead of activating an unrelated CTA."""
        attempt_id = self._pose_gt_attempt_context()
        if not attempt_id or self._saving:
            self._sync_pose_gt_controls()
            return
        decision = self.session.review.attempt_annotations.get(attempt_id, {})
        if not self._gt_target_is_confirmed(attempt_id):
            self._sync_pose_gt_controls()
            return
        self._ensure_pose_gt_points(attempt_id)
        answer = self.pose_gt_answer.get()
        if answer == "unavailable":
            if len(self._pose_gt_points) == 4:
                self.pose_gt_answer.set("mark")
                self.status_var.set("Rogi zostały już zapisane. Najpierw usuń ten obrys, jeśli jest błędny.")
                return
            # An unfinished 1–3 point draft is not saved GT. The operator may
            # decide it is impossible to identify the remaining corners.
            if 0 < len(self._pose_gt_points) < 4:
                self._leave_pose_gt_edit_on_navigation()
                self._paint_image()
            if not decision.get("pose_gt_unavailable_reason"):
                self._set_pose_gt_unavailable()
        elif answer == "mark":
            if decision.get("pose_gt_unavailable_reason"):
                self._change(lambda: self.session.annotate("attempt", attempt_id,
                    pose_gt_unavailable_reason=None),
                    after=lambda: self._resume_pose_after_answer(attempt_id))
            else:
                self._resume_pose_after_answer(attempt_id)

    def _resume_pose_after_answer(self, attempt_id):
        if self._pose_gt_attempt_context() != attempt_id:
            return
        self._pose_auto_token = None  # explicit operator answer can resume after cancel
        self._maybe_begin_guided_pose_gt()

    def _leave_pose_gt_edit_on_navigation(self):
        """Never carry a GT edit latch onto a different observation/detection/image.

        Only an unfinished in-memory 1–3 point draft is discarded. Saved GT,
        manual decisions and underlying MT model predictions are unchanged.
        """
        control = getattr(self, "pose_edit_var", None)
        if control is None or not control.get():
            return
        control.set(False)
        self._pose_gt_drag_index = None
        self._pose_gt_before_drag = None
        self._view_drag_at = None
        if 0 < len(getattr(self, "_pose_gt_points", [])) < 4:
            self._pose_gt_points = []
            self._pose_gt_cache_token = None
        if hasattr(self, "canvas"):
            self.canvas.configure(cursor="hand2")

    def _toggle_pose_gt_edit(self):
        """One-shot action for this MT attempt, not a sticky checkbox."""
        if self.pose_edit_var.get():
            self._leave_pose_gt_edit_on_navigation()
        else:
            attempt_id = self._pose_gt_attempt_context()
            if not attempt_id or self._saving:
                return
            decision = self.session.review.attempt_annotations.get(attempt_id, {})
            if (not self._gt_target_is_confirmed(attempt_id)
                    or decision.get("pose_gt_unavailable_reason")):
                self.status_var.set("Najpierw oceń liczbę tablic albo cofnij pominięcie GT.")
                return
            self.pose_edit_var.set(True)
        self._pose_gt_drag_index = None
        self._pose_gt_before_drag = None
        self._view_drag_at = None
        if hasattr(self, "canvas"):
            self.canvas.configure(cursor="crosshair" if self.pose_edit_var.get() else "hand2")
            self._paint_image()
        self._sync_pose_gt_controls()

    def _set_pose_gt_unavailable(self):
        """Independent geometrical exclusion; never touches detection or MZ decisions."""
        attempt_id = self._pose_gt_attempt_context()
        if not attempt_id or self._saving:
            return
        decision = self.session.review.attempt_annotations.get(attempt_id, {})
        if not self._gt_target_is_confirmed(attempt_id):
            return
        self._ensure_pose_gt_points(attempt_id)
        if self._pose_gt_points:
            self.status_var.set("Najpierw usuń istniejący GT narożników, aby oznaczyć go jako nieoznaczalny.")
            return
        reason = (None if decision.get("pose_gt_unavailable_reason")
                  else "corners_not_distinguishable")
        self._leave_pose_gt_edit_on_navigation()
        self._change(lambda: self.session.annotate("attempt", attempt_id,
            pose_gt_unavailable_reason=reason))

    def _pose_canvas_to_mt_input(self, event, attempt_id):
        if self._image is None or self._image_source_size is None:
            return None
        row = self.session.attempts[attempt_id]
        w, h = float(row["input_width"]), float(row["input_height"])
        if self._image_source_size != (w, h) or not self._view_center:
            return None
        scale = max(1e-9, self._view_pixel_scale)
        cx, cy = self._view_center
        vw, vh = self.canvas.winfo_width(), self.canvas.winfo_height()
        # Exact inverse of _paint_image, including source->thumbnail scale.
        ix = cx + (event.x - vw / 2) / scale
        iy = cy + (event.y - vh / 2) / scale
        x = ix * w / self._image.width
        y = iy * h / self._image.height
        return (x, y) if 0 <= x <= w and 0 <= y <= h else None

    def _pose_mt_to_canvas(self, point, attempt_id):
        row = self.session.attempts[attempt_id]
        w, h = float(row["input_width"]), float(row["input_height"])
        cx, cy = self._view_center
        scale = self._view_pixel_scale
        vw, vh = self.canvas.winfo_width(), self.canvas.winfo_height()
        return ((point[0] * self._image.width / w - cx) * scale + vw / 2,
                (point[1] * self._image.height / h - cy) * scale + vh / 2)

    def _draw_pose_gt_overlay(self, attempt_id, to_canvas):
        self._ensure_pose_gt_points(attempt_id)
        points = self._pose_gt_points
        valid_polygon = False
        canonical_labels = False
        # In-progress clicks have no edge order. Connect only four valid
        # vertices. Saved GT is drawn AS RECORDED, never silently migrated.
        if len(points) == 4:
            try:
                attempt = self.session.attempts[attempt_id]
                w, h = attempt["input_width"], attempt["input_height"]
                if self.pose_edit_var.get():
                    points = _ordered_operator_gt_quad(points, w, h)
                else:
                    points = validate_mt_quad(points, w, h)
                canonical_labels = tuple(points) == _ordered_operator_gt_quad(points, w, h)
                valid_polygon = True
            except (ValueError, TypeError, KeyError):
                pass
        pts = [to_canvas(*xy) for xy in points]
        if valid_polygon:
            flat = [v for xy in pts for v in xy]
            self.canvas.create_polygon(*flat, fill="", outline="#40e7aa", width=2.5,
                                       tags=("pose_gt_overlay", "pose_gt_polygon"))
        for index, (x, y) in enumerate(pts):
            self.canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#40e7aa",
                                    outline="#103d32", width=2,
                                    tags=("pose_gt_overlay", "pose_gt_corner"))
            label = ("TL", "TR", "BR", "BL")[index] if canonical_labels else str(index + 1)
            self.canvas.create_text(x + 10, y - 10, text=label,
                                    fill="#40e7aa", anchor="sw", font=("Segoe UI", 10, "bold"),
                                    tags=("pose_gt_overlay", "pose_gt_corner_label"))

    def _finish_pose_gt_drag(self):
        if self._pose_gt_drag_index is None:
            return
        self._pose_gt_drag_index = None
        previous = self._pose_gt_before_drag or []
        self._pose_gt_before_drag = None
        attempt_id = self._pose_gt_attempt_context()
        if not attempt_id:
            self._pose_gt_points = previous
            return
        if len(self._pose_gt_points) < 4:
            self._sync_pose_gt_controls()
            return
        row = self.session.attempts[attempt_id]
        try:
            w, h = float(row["input_width"]), float(row["input_height"])
            quad = _ordered_operator_gt_quad(self._pose_gt_points, w, h)
            pred = _linked_pose_quad_on_mt_input(self.session, row)
            if pred is not None:
                compare_mt_pose_to_gt(pred, quad, w, h)
        except (ValueError, TypeError, KeyError) as exc:
            self._pose_gt_points = previous
            self.status_var.set(f"Nie zapisano GT: {exc}. Popraw układ narożników.")
            self._paint_image()
            self._sync_pose_gt_controls()
            return
        # The displayed edit handles and the persisted annotation now share
        # the canonical TL/TR/BR/BL order, irrespective of click sequence.
        self._pose_gt_points = list(quad)
        points = [[round(x, 4), round(y, 4)] for x, y in quad]
        current = self.session.review.attempt_annotations.get(attempt_id, {})
        # As soon as four points are valid, leave editing and show MT+GT again.
        # This is local to the current attempt and requires no extra approval.
        self.pose_edit_var.set(False)
        if hasattr(self, "canvas"):
            self.canvas.configure(cursor="hand2")
            self._paint_image()
        if (current.get("pose_gt_quad_mt_input_px") == points and
                current.get("pose_gt_schema") == POSE_GT_SCHEMA and
                current.get("pose_gt_image_entry") == self._image_entry):
            self._sync_pose_gt_controls()
            return
        is_missed = str(row.get("mt_status") or "").upper() == "NO_DETECTION"
        payload = dict(
            pose_gt_schema=POSE_GT_SCHEMA,
            pose_gt_image_entry=row["mt_input_evidence_entry"],
            pose_gt_input_size_px=[w, h],
            pose_gt_quad_mt_input_px=points,
            pose_gt_review_mode=("assisted_gt_missed_mt_detection_v1" if is_missed else
                                 "assisted_with_pred_preview_v1" if pred is not None else
                                 "assisted_gt_without_mt_pose_v1"),
            pose_gt_unavailable_reason=None)
        if not is_missed:
            payload.update(plate_visibility="visible", is_plate=True, evaluable=True)
        # A NO_DETECTION record is never promoted into a detected plate.
        # Its independent operator GT is tied to the exact attempt/MT image.
        self._change(lambda: self.session.annotate("attempt", attempt_id, **payload))
        self._sync_pose_gt_controls()

    def _clear_pose_gt(self):
        attempt_id = self._pose_gt_attempt_context()
        if not attempt_id or self._saving:
            return
        decision = self.session.review.attempt_annotations.get(attempt_id, {})
        self._pose_gt_points = []
        self._pose_gt_drag_index = None
        self._pose_gt_before_drag = None
        self.pose_edit_var.set(False)
        self.canvas.configure(cursor="hand2")
        self._paint_image()
        self._sync_pose_gt_controls()
        if decision.get("pose_gt_quad_mt_input_px") is not None:
            self._change(lambda: self.session.annotate("attempt", attempt_id,
                pose_gt_schema=None, pose_gt_image_entry=None,
                pose_gt_input_size_px=None, pose_gt_quad_mt_input_px=None,
                pose_gt_review_mode=None))

    def _sync_detection_choice(self):
        if not self.session or not hasattr(self, "detection_radios"):
            return
        current = self.current_record
        annotation = {}
        allowed = False
        if current:
            kind, record_id = self._active_detection_target()
            row = (self.session.attempts if kind == "attempt" else self.session.samples).get(record_id, {})
            cancelled = self.session.cancelled(row)
            allowed = not cancelled and (kind == "sample" or
                       str(row.get("mt_status", "")).upper() in DETECTION_STATUSES)
            annotation = (self.session.review.attempt_annotations if kind == "attempt"
                          else self.session.review.sample_annotations).get(record_id, {})
            if kind == "attempt" and not allowed:
                question = "Brak detekcji MT — oceń tablice na całym obrazie (powyżej)."
            elif kind == "sample":
                question = "Czy wycinek obrazu przedstawia tablicę?"
            else:
                question = "Oceń zaznaczenie na zdjęciu."
        else:
            question = "Ocena operatora: wybierz detekcję / crop."
        self.detection_context.configure(text=question)
        if annotation.get("is_plate") is True and annotation.get("evaluable") is not False:
            selected = "yes"
        elif annotation.get("is_plate") is False:
            selected = "no"
        elif annotation.get("evaluable") is False:
            selected = "skip"
        else:
            selected = ""  # Bez decyzji — nie zaznaczaj nic automatycznie.
        self.detection_choice.set(selected)
        for radio in self.detection_radios:
            radio.configure(state="normal" if allowed and not self._saving else "disabled")

    def show_invocation_input(self):
        attempt = self._current_mt_attempt()
        group = self.session.mt_invocations.get(self.current_invocation) if self.session else None
        index = _primary_review_image_index(getattr(self, "_image_rows", ()), attempt, group)
        if index is None:
            self.status_var.set("Brak zdjęcia przypisanego do tej próby. Nie wybieramy obrazu z innej detekcji.")
            return
        if self.image_choice.current() == index and self._image is not None:
            return  # Preserve the current zoom and GT context.
        self.image_choice.current(index)
        self._load_image()

    def choose_visible_plate_count(self):
        value = self.invocation_count_value.get()
        if value in VISIBILITY_LABELS:
            self.invocation_choice.set(VISIBILITY_LABELS[value])
            self.save_invocation_decision()

    def save_invocation_decision(self, event=None):
        key = self.current_invocation
        group = self.session.mt_invocations.get(key) if self.session else None
        if not group or group.cancelled or not group.executed or group.execution_failed:
            self._sync_review_controls()
            return
        value = next((key for key, label in VISIBILITY_LABELS.items() if label == self.invocation_choice.get()), None)
        if key and value:
            self._change(lambda: self.session.annotate_invocation(key, visible_plate_count=value, evaluable=value != "uncertain"))

    def reveal_predictions(self):
        """Jawny krok dla starych rozpoczętych ocen zaślepionych."""
        if not self.session or self._saving or self.session.review.review_mode == "assisted":
            return
        self._change(self.session.reveal_predictions_for_review,
                     after=lambda: self.status_var.set("Predykcje widoczne. Istniejące GT zachowane. Odtąd ocena jest asystowana, nie zaślepiona."))

    def change_review_mode(self, event=None):
        mode = next((key for key, label in MODE_LABELS.items() if label == self.mode_choice.get()), None)
        if mode:
            key, text, note = self.subject_key, self.gt_var.get(), self.note_var.get()
            def change():
                self.session.set_review_mode(mode)
                if key and (text or note):
                    self.session.save_subject_draft(key, ground_truth=text, note=note)
            self._change(change, save_draft=False)

    def _current_mt_attempt(self):
        if not self.session or not self.current_record:
            return {}
        kind, key = self.current_record
        if kind == "attempt":
            return self.session.attempts.get(key, {})
        sample = self.session.samples.get(key, {})
        return self.session.attempts.get(str(sample.get("attempt_id") or ""), {})

    def _review_areas(self):
        """Detectable regions linked to this observation and MT invocation."""
        if not self.session or not self.subject_key or not self.current_invocation:
            return []
        subject = self.session.subjects.get(self.subject_key, {})
        return [aid for aid in subject.get("attempts", ())
                if (self.session.invocation_by_attempt.get(aid) == self.current_invocation and
                    self.session.attempts.get(aid, {}).get("mt_status") in DETECTION_STATUSES)]

    def _sync_detected_area_navigation(self):
        if not hasattr(self, "target_nav"):
            return
        ids = self._review_areas()
        current_id = str(self._current_mt_attempt().get("id") or "")
        if len(ids) <= 1 or current_id not in ids:
            self.target_nav.grid_remove()
            return
        pos = ids.index(current_id)
        self.target_position.configure(text=f"Obszar {pos + 1} z {len(ids)}")
        self.target_previous.configure(state="normal" if pos > 0 and not self._saving else "disabled")
        self.target_next.configure(state="normal" if pos + 1 < len(ids) and not self._saving else "disabled")
        self.target_nav.grid()

    def _switch_detected_area(self, direction):
        ids = self._review_areas()
        current_id = str(self._current_mt_attempt().get("id") or "")
        if self._saving or current_id not in ids:
            return
        target = ids.index(current_id) + int(direction)
        if target < 0 or target >= len(ids):
            return
        iid = next((iid for iid, info in self._record_ids.items()
                    if info == ("attempt", ids[target])), None)
        if iid is None:
            return
        self.record_tree.selection_set(iid)
        self.record_tree.focus(iid)
        self._select_record()

    def _sync_crop_preview_source(self, attempt, current_sample=None):
        self._crop_preview_row = None
        if not self.session:
            return
        attempt_id = str(attempt.get("id") or "")
        candidates = ([current_sample] if isinstance(current_sample, dict) else [])
        candidates += [self.session.samples[key] for key in
                       (getattr(self.session, "sample_ids_by_attempt", {}) or {}).get(attempt_id, ())
                       if key in self.session.samples]
        for sample in candidates:
            if (sample.get("attempt_id") == attempt_id and
                    sample.get("image_entry") in self.session.entry_names):
                self._crop_preview_row = sample
                break
        if self._crop_preview_row:
            self.crop_preview_button.configure(state="normal")
            self.crop_preview_button.grid()
        else:
            self.crop_preview_button.grid_remove()

    def _close_crop_preview(self):
        popup = getattr(self, "_crop_preview_window", None)
        self._crop_preview_window = None
        if popup is not None:
            try:
                if popup.winfo_exists():
                    popup.destroy()
            except tk.TclError:
                pass

    def _show_crop_preview(self):
        """Read-only MZ image in a separate window; never changes MT evidence or GT."""
        row = getattr(self, "_crop_preview_row", None)
        if not row or not self.session or self._saving:
            return
        self._close_crop_preview()
        popup = tk.Toplevel(self.window)
        self._crop_preview_window = popup
        popup.configure(bg=self.bg)
        popup.title("Wycięta tablica — podgląd numeru")
        popup.geometry("770x300")
        popup.minsize(340, 170)
        popup.protocol("WM_DELETE_WINDOW", self._close_crop_preview)
        caption = self._label(popup, "Wycięcie tablicy zapisane przez telefon. Podgląd pomaga odczytać numer.",
                              font=("Segoe UI", 10), wraplength=710)
        caption.pack(fill="x", padx=14, pady=(12, 5))
        picture = tk.Label(popup, text="Wczytywanie wycięcia…", bg=self.bg, fg=self.fg)
        picture.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        selected_row = dict(row)

        def work():
            img = self.session.image(selected_row)
            if img is None:
                raise ValueError("Nie znaleziono wyciętej tablicy w archiwum.")
            img = img.convert("RGB")
            max_w, max_h = 740, 480
            factor = min(5.0, max_w / max(1, img.width), max_h / max(1, img.height))
            if factor != 1.0:
                img = img.resize((max(1, round(img.width * factor)),
                                  max(1, round(img.height * factor))), Image.Resampling.LANCZOS)
            return img

        def done(image):
            if self._crop_preview_window is not popup or not popup.winfo_exists():
                return
            picture_image = ImageTk.PhotoImage(image, master=picture)
            picture.configure(image=picture_image, text="")
            picture.image = picture_image
            popup.geometry(f"{max(360, image.width + 32)}x{max(190, image.height + 80)}")

        # The standard background worker reports errors through the status bar.
        self._submit(work, done)

    def _set_image_help(self):
        index = self.image_choice.current()
        if index < 0 or not getattr(self, "_image_rows", None):
            return
        label, _ = self._image_rows[index]
        missing_mt = str(self._current_mt_attempt().get("mt_status") or "").upper() == "NO_DETECTION"
        self.image_help.configure(text=(
            "MT nie wykrył tablicy. Jeśli widzisz jedną, wybierz «1 — jedna tablica» "
            "i zaznacz jej rzeczywiste rogi GT."
            if missing_mt and label.startswith("Wejście MT —") else
            "Niebieski obrys pokazuje obszar wskazany przez MT."
            if label.startswith("Wejście MT —") else
            "Zdjęcie z telefonu. Nie ma dla niego potwierdzonego obrysu bieżącej detekcji."))

    def _load_image(self):
        # Mode is local to the exact viewed evidence, never sticky across images.
        index = self.image_choice.current()
        if getattr(self, "_image_rows", None) and 0 <= index < len(self._image_rows):
            next_row = self._image_rows[index][1]
            next_entry = next_row.get("image_entry") or next_row.get("evidence_entry") or ""
            if self._image_entry and next_entry != self._image_entry:
                self._leave_pose_gt_edit_on_navigation()
        self._image_token += 1
        self._view_zoom = 1.0
        self._view_center = None
        self._view_drag_at = None
        token = self._image_token
        self._image = None
        self._image_source_size = None
        self._image_entry = ""
        self._sync_pose_gt_controls()
        self._paint_image("Wczytywanie obrazu…")
        index = self.image_choice.current()
        if not self._image_rows or index < 0:
            self.image_help.configure(text="Nie zapisano zdjęcia powiązanego z tym obszarem.")
            self._paint_image("Brak zdjęcia dla tej detekcji. Nie wykorzystujemy obrazu z innej próby.")
            return
        _label, row = self._image_rows[index]
        self._set_image_help()
        def work():
            try:
                image = self.session.image(row)
                source_size = image.size
                image = image.convert("RGB")  # bezpieczny tryb transformacji viewportu
                image.thumbnail((3200, 2400), Image.Resampling.LANCZOS)
                return image, source_size, ""
            except Exception as error:
                return None, None, str(error)
        def done(result):
            if token == self._image_token:
                self._image, self._image_source_size, error = result
                self._image_entry = row.get("image_entry") or row.get("evidence_entry") or ""
                self._paint_image(error)
                self._sync_detection_choice()
                self._sync_pose_gt_controls()
                # Never start drawing just because a saved positive decision was restored.
                # The operator must explicitly choose that the corners can be marked.
                if self._zoom_to_mt_pending and self._image is not None:
                    self.zoom_to_mt_detection()
        self._submit(work, done)

    def _paint_image(self, message=""):
        """Jedna transformacja dla pikseli i overlay MT: zoom/pan nie rozjezdza ramki."""
        self.canvas.delete("all")
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self._image is None:
            self._photo = None
            self._view_fit_scale = 1.0
            self._view_pixel_scale = 1.0
            self.canvas.create_text(width / 2, height / 2,
                text=message or "Wybierz obserwację i obraz", fill="#edf4f6",
                width=max(50, width - 30))
            if hasattr(self, "zoom_value"):
                self.zoom_value.configure(text="—")
            return
        iw, ih = self._image.size
        self._view_fit_scale = max(0.0001, min((width - 16) / iw, (height - 16) / ih))
        self._view_pixel_scale = self._view_fit_scale * self._view_zoom
        scale = self._view_pixel_scale
        if self._view_center is None:
            self._view_center = (iw / 2.0, ih / 2.0)
        cx, cy = self._view_center
        half_x = width / (2.0 * scale)
        half_y = height / (2.0 * scale)
        cx = iw / 2.0 if iw <= 2 * half_x else max(half_x, min(iw - half_x, cx))
        cy = ih / 2.0 if ih <= 2 * half_y else max(half_y, min(ih - half_y, cy))
        self._view_center = (cx, cy)
        # Renderowanie TYLKO widocznego obszaru, bez tworzenia olbrzymich PhotoImage przy zoomie.
        # Obraz PIL jest tylko do odczytu; piksele poza nim wypelnia ciemne tlo.
        inv = 1.0 / scale
        rendered = self._image.transform((width, height), Image.Transform.AFFINE,
            (inv, 0, cx - width * inv / 2, 0, inv, cy - height * inv / 2),
            resample=Image.Resampling.BICUBIC, fillcolor=(16, 24, 32))
        self._photo = ImageTk.PhotoImage(rendered, master=self.canvas)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo, tags=("evidence_image",))
        if hasattr(self, "zoom_value"):
            self.zoom_value.configure(text=f"×{self._view_zoom:.1f}")
        self._paint_detection_overlay(width, height, 0, 0)

    def _paint_detection_overlay(self, width, height, offset_x, offset_y):
        if not self.current_record or not self.current_invocation or self._image is None:
            return
        kind, key = self.current_record
        row = self.session.attempts.get(key if kind == "attempt" else
            self.session.samples[key].get("attempt_id"), {})
        group = self.session.mt_invocations[self.current_invocation]
        explicit_inputs = {child.get("mt_input_evidence_entry") for child in group.records}
        # Overlay only on the exact recorded MT input; never on an MZ crop.
        if (not self._image_entry or self._image_entry not in group.evidence_entries or
                self._image_entry.startswith("samples/crops/")):
            return
        exact_input = row.get("mt_input_evidence_entry")
        if str(row.get("mt_status") or "").upper() == "NO_DETECTION":
            gt_id = self._pose_gt_attempt_context()
            try:
                size = float(row["input_width"]), float(row["input_height"])
            except (TypeError, ValueError, KeyError):
                return
            if gt_id and self._image_entry == exact_input and self._image_source_size == size:
                cx, cy = self._view_center
                scale = self._view_pixel_scale
                xscale = self._image.width / size[0]
                yscale = self._image.height / size[1]
                def to_canvas(x, y):
                    return ((x * xscale - cx) * scale + width / 2,
                            (y * yscale - cy) * scale + height / 2)
                self._draw_pose_gt_overlay(gt_id, to_canvas)
            return
        if row.get("mt_status") not in DETECTION_STATUSES:
            return
        box = (detection_box_on_mt_input(row) if exact_input and
               self._image_entry == exact_input and exact_input in explicit_inputs else None)
        message = ("Brak obrazu wejścia MT dla tej detekcji. Nie pokazujemy ramki z innej próby."
                   if self._image_entry != exact_input else "Brak geometrii detekcji w tej sesji.")
        try:
            input_size = (float(row["input_width"]), float(row["input_height"]))
        except (ValueError, TypeError, KeyError):
            input_size = None
        if (self._image_entry != exact_input or exact_input not in explicit_inputs or
                input_size is None or self._image_source_size != input_size):
            if self._image_source_size != input_size:
                message = "Rozmiar obrazu nie odpowiada geometrii wejścia MT."
            text_id = self.canvas.create_text(12, 12, anchor="nw", text=message,
                fill="#ffffff", width=max(50, width - 24),
                tags=("detection_geometry_notice",))
            self._canvas_text_background(text_id, "detection_geometry_notice")
            return
        # Recorded Pose and independent GT can be rendered without a BBOX;
        # never infer any four corners from the BBOX.
        cx, cy = self._view_center
        scale = self._view_pixel_scale
        ratio_x = self._image.width / input_size[0]
        ratio_y = self._image.height / input_size[1]
        def to_canvas(x, y):
            return ((x * ratio_x - cx) * scale + width / 2,
                    (y * ratio_y - cy) * scale + height / 2)

        selected_sample = self.session.samples.get(key) if kind == "sample" else None
        quad = _linked_pose_quad_on_mt_input(self.session, row, selected_sample)
        gt_attempt_id = self._pose_gt_attempt_context()
        if gt_attempt_id:
            self._ensure_pose_gt_points(gt_attempt_id)
        editing_without_complete_gt = bool(gt_attempt_id and self.pose_edit_var.get() and
                                           len(self._pose_gt_points) < 4)
        if quad is not None and not editing_without_complete_gt:
            pts = [to_canvas(x, y) for x, y in quad]
            flat = [v for xy in pts for v in xy]
            self.canvas.create_polygon(*flat, fill="", outline="#10212b", width=6,
                tags=("detection_overlay",))
            self.canvas.create_polygon(*flat, fill="", outline="#40dcff", width=3,
                tags=("detection_overlay", "detection_polygon"))
            for x, y in pts:
                self.canvas.create_oval(x - 3, y - 3, x + 3, y + 3,
                    fill="#40dcff", outline="#10212b",
                    tags=("detection_overlay", "pose_corner"))
            anchor_x = min(x for x, _ in pts)
            anchor_y = min(y for _, y in pts)
            prefix = "POSE 4 pkt"
        elif not editing_without_complete_gt:
            # BBOX is retained in the source for diagnostics/zoom, never drawn
            # as a substitute for MT Pose in the scientific review.
            _, reason = _pose_source_status(self.session, row)
            text_id = self.canvas.create_text(12, 12, anchor="nw",
                text=reason, fill="#ffffff", width=max(50, width - 24),
                tags=("detection_geometry_notice",))
            self._canvas_text_background(text_id, "detection_geometry_notice")
            if gt_attempt_id:
                self._draw_pose_gt_overlay(gt_attempt_id, to_canvas)
            return
        if not editing_without_complete_gt:
            ordinal = row.get("mt_detection_index")
            title = (f"Detekcja {int(ordinal) + 1} / {group.detection_count}"
                     if ordinal not in (None, "") else "Detekcja")
            title = f"{prefix} • {title}"
            if row.get("mt_status") == "DETECTION_INVALID_QUAD":
                title += " • błędna geometria"
            title_x = max(4, min(width - 15, anchor_x + 5))
            title_y = max(3, min(height - 22, anchor_y - 24))
            text_id = self.canvas.create_text(title_x, title_y, anchor="nw", text=title,
                fill="#ffffff", font=("Segoe UI", 10, "bold"),
                tags=("detection_overlay", "detection_label"))
            bounds = self.canvas.bbox(text_id)
            if bounds is not None:
                self.canvas.move(text_id, min(0, width - 8 - bounds[2]), 0)
            self._canvas_text_background(text_id, "detection_overlay")
        if gt_attempt_id:
            self._draw_pose_gt_overlay(gt_attempt_id, to_canvas)

    def fit_image(self):
        """Przywroc caly obraz. Dziala rowniez po zmianie rozmiaru okna."""
        if self._image is None:
            return
        self._view_zoom = 1.0
        self._view_center = (self._image.width / 2.0, self._image.height / 2.0)
        self._paint_image()

    def zoom_image(self, factor: float, anchor=None):
        """Skalowanie wzgledem wskazanego miejsca (mysz) lub srodka canvasu."""
        if self._image is None:
            return
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        ax, ay = anchor if anchor is not None else (width / 2, height / 2)
        if self._view_center is None:
            self._view_center = (self._image.width / 2, self._image.height / 2)
        prev = max(0.0001, self._view_fit_scale * self._view_zoom)
        img_x = self._view_center[0] + (ax - width / 2) / prev
        img_y = self._view_center[1] + (ay - height / 2) / prev
        newer = max(1.0, min(24.0, self._view_zoom * float(factor)))
        if abs(newer - self._view_zoom) < 0.0001:
            return
        self._view_zoom = newer
        next_scale = max(0.0001, self._view_fit_scale * self._view_zoom)
        self._view_center = (img_x - (ax - width / 2) / next_scale,
                             img_y - (ay - height / 2) / next_scale)
        self._paint_image()

    def _wheel_zoom(self, event):
        if self._image is None:
            return "break"
        delta = getattr(event, "delta", 0)
        if delta == 0:
            delta = 120 if getattr(event, "num", 0) == 4 else -120
        self.zoom_image(1.25 if delta > 0 else 1.0 / 1.25,
                        (event.x, event.y))
        return "break"

    def _pan_begin(self, event, *, force_pan=False):
        if self._image is None:
            return
        if not force_pan and self.pose_edit_var.get():
            attempt_id = self._pose_gt_attempt_context()
            if not attempt_id or self._saving:
                self.status_var.set("Wybierz obraz wejścia MT bieżącej próby, aby zaznaczyć GT.")
                return "break"
            self._ensure_pose_gt_points(attempt_id)
            pos = self._pose_canvas_to_mt_input(event, attempt_id)
            if pos is None:
                self.status_var.set("Kliknij wewnątrz obrazu wejścia MT.")
                return "break"
            self._pose_gt_before_drag = list(self._pose_gt_points)
            nearest = [(i, math.dist(
                self._pose_mt_to_canvas(p, attempt_id), (event.x, event.y)))
                for i, p in enumerate(self._pose_gt_points)]
            if len(self._pose_gt_points) < 4:
                if nearest and min(distance for _, distance in nearest) <= 2:
                    self.status_var.set("Punkt pokrywa się z poprzednim narożnikiem. Powiększ obraz kółkiem myszy.")
                    return "break"
                self._pose_gt_points.append(pos)
                self._pose_gt_drag_index = len(self._pose_gt_points) - 1
            elif nearest and min(distance for _, distance in nearest) <= 13:
                self._pose_gt_drag_index = min(nearest, key=lambda item: item[1])[0]
            else:
                self.status_var.set("Aby skorygować GT, przeciągnij jeden z czterech zielonych punktów.")
                return "break"
            self._paint_image()
            self._sync_pose_gt_controls()
            return "break"
        if self._view_center is None:
            self._view_center = (self._image.width / 2, self._image.height / 2)
        self._view_drag_at = (event.x, event.y, *self._view_center)
        self.canvas.configure(cursor="fleur")

    def _pan_move(self, event):
        if self._image is None:
            return
        if self._pose_gt_drag_index is not None:
            attempt_id = self._pose_gt_attempt_context()
            if attempt_id:
                point = self._pose_canvas_to_mt_input(event, attempt_id)
                if point is not None:
                    self._pose_gt_points[self._pose_gt_drag_index] = point
                    self._paint_image()
                    self._sync_pose_gt_controls()
            return "break"
        if self._view_drag_at is None:
            return
        mx, my, cx, cy = self._view_drag_at
        scale = max(0.0001, self._view_pixel_scale)
        self._view_center = (cx - (event.x - mx) / scale,
                             cy - (event.y - my) / scale)
        self._paint_image()

    def _pan_end(self, event=None):
        if self._pose_gt_drag_index is not None:
            self._finish_pose_gt_drag()
            self._paint_image()
        self._view_drag_at = None
        self.canvas.configure(cursor=("crosshair" if self.pose_edit_var.get() else "hand2")
                              if self._image is not None else "")

    def zoom_to_mt_detection(self):
        """Zblizenie wybranej detekcji; tylko gdy znana geometria jej wejscia MT."""
        if self._image is None or not self.current_record or not self.current_invocation:
            return
        kind, key = self.current_record
        row = self.session.attempts.get(key if kind == "attempt" else
            self.session.samples[key].get("attempt_id"), {})
        group = self.session.mt_invocations[self.current_invocation]
        exact_input = row.get("mt_input_evidence_entry")
        if not exact_input or exact_input not in group.evidence_entries:
            self._zoom_to_mt_pending = False
            self.status_var.set("Brak powiązanego zdjęcia wejściowego MT do zbliżenia.")
            return
        if self._image_entry != exact_input:
            if _primary_review_image_index(getattr(self, "_image_rows", ()), row, group) is None:
                self._zoom_to_mt_pending = False
                self.status_var.set("Brak zapisanego wejścia MT dla tej detekcji.")
                return
            if not self._zoom_to_mt_pending:
                self._zoom_to_mt_pending = True
                self.show_invocation_input()
            else:
                self._zoom_to_mt_pending = False
                self.status_var.set("Brak odpowiedniego obrazu wejścia MT dla zbliżenia.")
            return
        self._zoom_to_mt_pending = False
        box = detection_box_on_mt_input(row)
        selected_sample = self.session.samples.get(key) if kind == "sample" else None
        pose_quad = _linked_pose_quad_on_mt_input(self.session, row, selected_sample)
        if pose_quad is not None:
            # Fokus obejmuje rzeczywiste cztery narożniki Pose (nie otaczający je bbox).
            box = (min(x for x, _ in pose_quad), min(y for _, y in pose_quad),
                   max(x for x, _ in pose_quad), max(y for _, y in pose_quad))
        try:
            input_size = (float(row["input_width"]), float(row["input_height"]))
        except (ValueError, TypeError, KeyError):
            input_size = None
        if box is None or self._image_source_size != input_size:
            self.status_var.set("Zbliżenie wymaga kompletnej geometrii MT. Możesz użyć ręcznego zoomu.")
            return
        self._paint_image()
        sx = self._image.width / input_size[0]
        sy = self._image.height / input_size[1]
        x1, y1, x2, y2 = box
        box_w = max(1.0, abs(x2 - x1) * sx)
        box_h = max(1.0, abs(y2 - y1) * sy)
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        preferred_scale = min(cw * 0.60 / box_w, ch * 0.55 / box_h)
        self._view_zoom = max(1.0, min(24.0, preferred_scale / max(self._view_fit_scale, 0.0001)))
        self._view_center = ((x1 + x2) * 0.5 * sx, (y1 + y2) * 0.5 * sy)
        self._paint_image()
        self.status_var.set("Zbliżenie na wskazany obszar MT. Kółko: zoom, lewy przycisk: przesuń, Dopasuj: cały obraz.")

    def _canvas_text_background(self, text_id, tag):
        bounds = self.canvas.bbox(text_id)
        background = self.canvas.create_rectangle(bounds[0] - 4, bounds[1] - 2, bounds[2] + 4, bounds[3] + 2,
            fill="#10212b", outline="", tags=(tag,))
        self.canvas.tag_lower(background, text_id)

    def _sync_subject_eval_choice(self):
        if not self.session or not self.subject_key:
            return
        decision = self.session.review.subjects.get(self.subject_key, {})
        self.subject_eval_choice.set("exclude" if decision.get("evaluable") is False else "assess")
        for radio in self.subject_eval_radios:
            radio.configure(state="disabled" if self._saving else "normal")

    def save_subject_eval_choice(self):
        if not self.session or not self.subject_key or self._saving:
            return
        key, gt, note = self.subject_key, self.gt_var.get(), self.note_var.get()
        choice = self.subject_eval_choice.get()
        if choice not in {"assess", "exclude"}:
            return
        evaluable = False if choice == "exclude" else (True if normalize_registration(gt) else None)
        old = self.session.review.subjects.get(key, {})
        if (old.get("evaluable") is evaluable
                and normalize_registration(old.get("ground_truth")) == normalize_registration(gt)
                and old.get("note", "") == note):
            return
        self._change(lambda: self.session.set_subject(key, ground_truth=gt,
                       evaluable=evaluable, note=note), save_draft=False)

    def _schedule_autosave(self, *args):
        if self._rendering or not self.subject_key:
            return
        self.mode_choice.configure(state="disabled")
        if self._autosave_id:
            self.window.after_cancel(self._autosave_id)
        self._autosave_id = self.window.after(750, self.save_gt)

    def _persist_subject_fields(self, key, gt, note):
        """Zapisz GT bez przycisku, ale nie anuluj przypadkowo wykluczenia."""
        if not key:
            return
        old = self.session.review.subjects.get(key, {})
        normalized = normalize_registration(gt)
        if (normalize_registration(old.get("ground_truth")) == normalized
                and old.get("note", "") == note):
            return
        evaluable = (False if old.get("evaluable") is False else
                     True if normalized else None)
        self.session.set_subject(key, ground_truth=gt, note=note, evaluable=evaluable)

    def _draft_operation(self):
        key, gt, note = self.subject_key, self.gt_var.get(), self.note_var.get()
        return lambda: self._persist_subject_fields(key, gt, note)

    def _change(self, operation, *, save_draft=True, after=None):
        if not self.session or self._saving:
            return
        self.status_var.set("Zapisuję weryfikację…")
        draft = self._draft_operation()
        def work():
            if save_draft:
                draft()
            operation()
            stats = self.session.statistics()
            warning = ""
            updated_report = None
            try:
                store = MobilePackageExperimentStore(self.browser.store.root_dir)
                if store.apply_human_review(self.session):
                    updated_report = next((report for report in store.reports if report.report_id == self.report.report_id
                                           and report.source_archive_sha256 == self.session.review.source_archive_sha256), None)
            except Exception as error:
                warning = f"Decyzje zapisane; ranking wymaga odświeżenia: {error}"
            return stats, warning, updated_report
        def done(result):
            self._changed(result)
            if after:
                after()
        self._submit(work, done, saving=True)

    def _changed(self, result):
        self.stats, warning, updated_report = result
        self._refresh_subject_rows()
        self._refresh_stats()
        if self._pending_subject:
            self._leave_pose_gt_edit_on_navigation()
            self.subject_key, self._pending_subject = self._pending_subject, ""
        self._render_subject()
        self.status_var.set(warning or f"Zapisano automatycznie • rewizja {self.session.review.review_revision} • {REVIEW_LABELS[self.session.review.review_status]}")
        if updated_report is not None and self.browser.window.winfo_exists():
            self.browser.store.add_report(updated_report, save=False)
            for iid, report in self.browser.report_by_iid.items():
                if report.report_id == updated_report.report_id and report.source_archive_sha256 == updated_report.source_archive_sha256:
                    self.browser.report_by_iid[iid] = updated_report
            if (getattr(self.browser, "current_report", None) and self.browser.current_report.report_id == updated_report.report_id
                    and self.browser.current_report.source_archive_sha256 == updated_report.source_archive_sha256):
                self.browser._show_report(updated_report, self.browser.current_bundle)

    def save_gt(self, *, explicit=False):
        # explicit pozostaje dla istniejących wywołań, ale GT nie wymaga CTA.
        if self._autosave_id:
            self.window.after_cancel(self._autosave_id)
            self._autosave_id = None
        if not self.session or not self.subject_key:
            return
        if self._saving:
            self._autosave_id = self.window.after(200, self.save_gt)
            return
        key, gt, note = self.subject_key, self.gt_var.get(), self.note_var.get()
        old = self.session.review.subjects.get(key, {})
        if (normalize_registration(old.get("ground_truth")) == normalize_registration(gt)
                and old.get("note", "") == note):
            return
        self._change(lambda: self._persist_subject_fields(key, gt, note), save_draft=False)

    def exclude_subject(self):
        """Kompatybilność z wywołaniami testów; w GUI służy temu radio."""
        self.subject_eval_choice.set("exclude")
        self.save_subject_eval_choice()

    def annotate(self, decision):
        if self.current_record:
            kind, key = self.current_record
            self._change(lambda: self.session.annotate(kind, key, **decision))

    def save_reviewer(self):
        value = self.reviewer_var.get()
        self._change(lambda: self.session.set_reviewer(value))

    def complete(self):
        if self.session and hasattr(self, "_science_data"):
            science = self._science_data
            if (science["scientific_state"] == "MT_STAGE_COMPLETE_REVIEW_OPEN" and
                    science["mz"]["evaluable_reads"] == 0):
                self.status_var.set("Ocena MT może być zakończona niezależnie od MZ. Pełna ocena ALPR "
                                    "wymaga także rozpoznania znaków; możesz już wyeksportować wstępny raport MT.")
                return
        pending = _pose_geometry_summary(self.session)["pose_pending"] if self.session else 0
        if pending:
            self.status_var.set(f"Pozostało {pending} tablic bez oceny obrysu. "
                                "Wskaż ich rogi albo zaznacz, że nie da się tego zrobić.")
            return
        self._change(self.session.complete)

    def next_pending(self):
        # Stage MT takes priority; never send operator back to an already assessed
        # missed plate solely because OCR never ran in that attempt.
        stages = getattr(self, "_science_data", {}).get("subjects", {})
        for iid, key in self._subject_ids.items():
            if stages.get(key, {}).get("mt_pending"):
                self.subject_tree.selection_set(iid)
                self.subject_tree.see(iid)
                self._select_subject()
                return
        for iid, key in self._subject_ids.items():
            if stages.get(key, {}).get("mz_pending"):
                self.subject_tree.selection_set(iid)
                self.subject_tree.see(iid)
                self._select_subject()
                return
        self.status_var.set("Nie ma brakujących decyzji MT ani ocenianych odczytów MZ. "
                            "Zobacz «Wyniki naukowe»; pominięte MZ nie blokuje oceny MT.")

    def export(self):
        directory = filedialog.askdirectory(parent=self.window, title="Katalog wyników weryfikacji")
        if directory:
            paths = []
            def export_all():
                paths.extend(self.session.export(Path(directory)))
                export_path = Path(directory) / "mt_pose_geometry.csv"
                temp = export_path.with_name(export_path.name + ".tmp")
                rows = _pose_geometry_rows(self.session)
                columns = tuple(rows[0]) if rows else (
                    "session_id", "source_archive_sha256", "attempt_id", "metric_status")
                try:
                    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=columns)
                        writer.writeheader()
                        writer.writerows(rows)
                    os.replace(temp, export_path)
                finally:
                    if temp.exists():
                        temp.unlink()
                paths.append(export_path)
                # New, read-only thesis package uses the exact same exported Pose rows.
                # It is versioned per review revision and preserves native exports.
                paths.extend(export_thesis_bundle(
                    self.session, self.session.statistics(), rows, tuple(paths), Path(directory)))
                # Human-readable methodological companion; it never changes native reports.
                scientific = make_scientific_summary(self.session, self.session.statistics(), rows)
                paths.extend(write_scientific_companion(scientific, Path(directory)))
            self._change(export_all,
                         after=lambda: self.status_var.set(
                             f"Wyeksportowano {len(paths)} plików (w tym raport do pracy) do {directory}"))

    def _refresh_stats(self):
        summary = self.stats["summary"]
        progress = self._science_data["progress"]
        self.progress_label.configure(text=(
            f"Obserwacje: {progress['subjects_total']} • MT ocenione: {progress['subjects_mt_done']}/{progress['subjects_total']} • "
            f"wywołania MT z ocenioną liczbą tablic: {progress['mt_invocations_cardinality_reviewed']}/{progress['mt_executed_active']} • "
            f"pełna weryfikacja: {REVIEW_LABELS[self.session.review.review_status]}"))
        self.stats_tree.delete(*self.stats_tree.get_children())
        sections = {
            "Tablice / ALPR": {"evaluable_subjects": "Tablice do oceny", "subjects_with_exact_read": "Z poprawnym odczytem", "subjects_without_exact_read": "Bez poprawnego odczytu", "subject_success_rate": "Skuteczność systemu dla tablic"},
            "Odczyty MZ": {"evaluable_reads": "Oceniane cropy", "exact_reads": "Poprawne odczyty", "incorrect_reads": "Niepoprawne odczyty", "no_reads": "Brak odczytu", "exact_read_rate": "Udział poprawnych odczytów", "no_read_rate": "Udział braku odczytu"},
            "Znaki MZ": {"gt_characters": "Znaki GT", "correct_characters": "Poprawnie rozpoznane znaki", "incorrect_characters": "Błędnie rozpoznane znaki", "missing_characters": "Brakujące znaki", "extra_characters": "Znaki nadmiarowe", "cer": "CER — suma błędów / suma znaków GT"},
            "Lokalizacja MT": {"evaluable_mt_invocations": "Oceniane wywołania z jedną widoczną tablicą", "mt_successful_invocations": "Wywołania z poprawną lokalizacją", "mt_no_detection_invocations": "Wywołania bez detekcji", "mt_execution_error_invocations": "Wywołania z błędem wykonania", "mt_invalid_quad_invocations": "Wywołania z błędną geometrią", "mt_multi_plate_invocations": "Wywołania z wieloma tablicami", "mt_uncertain_invocations": "Wywołania niejednoznaczne", "mt_false_detections": "Fałszywe detekcje", "mt_localization_success_rate": "Skuteczność lokalizacji MT w wywołaniach z jedną tablicą"},
            "Czas i próby": {"median_time_to_first_exact_ms": "Mediana czasu do próby z poprawnym odczytem [ms]", "p90_time_to_first_exact_ms": "P90 czasu do próby z poprawnym odczytem [ms]", "median_attempts_to_first_exact": "Mediana liczby prób do poprawnego odczytu"},
        }
        for section, fields in sections.items():
            for key, label in fields.items():
                self.stats_tree.insert("", "end", values=(section, label, _display(summary.get(key), rate=key.endswith("rate") or key == "cer")))
        pose = _pose_geometry_summary(self.session)
        for key, label in (
            ("pose_eligible", "Prawdziwe tablice MT Pose do pomiaru"),
            ("pose_measured", "Polygony z ręcznie wyznaczonym GT — mianownik"),
            ("pose_pending", "Czeka na ręczne GT narożników"),
            ("pose_manual_unavailable", "GT rogów niewyznaczalne — wyłączone z pomiaru"),
            ("pose_no_geometry", "Brak zweryfikowanych 4 punktów MT w eksporcie"),
            ("missed_detection_manual_gt", "Pominięte tablice z zapisanymi rogami GT (bez IoU/NMCE)"),
            ("pose_nmce_mean_pct", "Średni znormalizowany błąd narożników NMCE [%]"),
            ("pose_iou_mean_pct", "Średnie Polygon IoU [%]"),
        ):
            value = pose[key]
            shown = f"{value:.2f}%" if key.endswith("_pct") and value is not None else _display(value)
            self.stats_tree.insert("", "end", values=("Geometria MT Pose / GT", label, shown))
        for row in self.stats["character_confusion"]:
            self.stats_tree.insert("", "end", values=("Pomyłki znaków", f"{row['ground_truth']} → {row['prediction']}", row["count"]))
        if hasattr(self, "science_view"):
            self.science_view.configure(state="normal")
            self.science_view.delete("1.0", "end")
            for tag, content in display_scientific_summary(self._science_data):
                self.science_view.insert("end", content + "\n", tag)
            self.science_view.configure(state="disabled")
            self.science_caption.configure(text=("Wyniki naukowe • pełna weryfikacja" if
                self._science_data["scientific_state"] == "FINAL_FULL_REVIEW" else
                "Wyniki naukowe • raport wstępny, z jawnymi mianownikami"))
        if hasattr(self, "conditions_view"):
            self.conditions_view.configure(state="normal")
            self.conditions_view.delete("1.0", "end")
            self.conditions_view.insert("end", session_conditions_text(self._science_data["conditions"]))
            self.conditions_view.configure(state="disabled")

    def _toggle_scientific_details(self):
        self._science_raw_open = not self._science_raw_open
        if self._science_raw_open:
            self.science_view.grid_remove()
            self.science_scrollbar.grid_remove()
            self._science_raw_host.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=12, pady=(3, 12))
            self.science_toggle.configure(text="Wróć do wyników naukowych")
        else:
            self._science_raw_host.grid_remove()
            self.science_view.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(12, 0), pady=(3, 12))
            self.science_scrollbar.grid(row=1, column=1, rowspan=2, sticky="ns", padx=(0, 12), pady=(3, 12))
            self.science_toggle.configure(text="Pokaż tabelę techniczną")

    def _toggle_provenance_details(self):
        self._provenance_raw_open = not self._provenance_raw_open
        if self._provenance_raw_open:
            self._provenance_raw_host.grid(row=2, column=0, sticky="nsew", padx=12, pady=(2, 9))
            self.details_toggle.configure(text="Ukryj pełną proweniencję techniczną")
        else:
            self._provenance_raw_host.grid_remove()
            self.details_toggle.configure(text="Pokaż pełną proweniencję techniczną")

    def _populate_details(self):
        values = {"session_id": self.session.session_id, "źródło": str(self.session.path),
                  "SHA-256": self.session.review.source_archive_sha256, "weryfikacja": str(self.session.sidecar_path),
                  "schemat próbek": self.session.bundle.sample_schema,
                  "eksperyment": self.session.bundle.experiment_session,
                  "capture": self.session.bundle.report_payload.get("capture", {}),
                  "pochodzenie modeli i warianty": self.session.review.provenance,
                  "błędy wykonania MT": {key: list(group.execution_errors) for key, group in self.session.mt_invocations.items() if group.execution_failed}}
        def append(value, prefix=""):
            for key, item in value.items():
                name = f"{prefix} / {key}" if prefix else str(key)
                if isinstance(item, dict):
                    append(item, name)
                else:
                    self.details_tree.insert("", "end", values=(name, json.dumps(item, ensure_ascii=False) if isinstance(item, list) else str(item)))
        append(values)
        if hasattr(self, "conditions_view"):
            self.conditions_view.configure(state="normal")
            self.conditions_view.delete("1.0", "end")
            self.conditions_view.insert("end", session_conditions_text(self._science_data["conditions"]))
            self.conditions_view.configure(state="disabled")

    def close(self):
        if self._closed:
            return
        self.save_gt()
        if self._saving:
            self._close_requested = True
            self.status_var.set("Kończę zapis weryfikacji przed zamknięciem…")
            return
        self._closed = True
        self._close_crop_preview()
        self.window.after_cancel(self._poll_id)
        if self._autosave_id:
            self.window.after_cancel(self._autosave_id)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.window.destroy()

    def _destroyed(self, event):
        if event.widget is self.window:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=False)


def open_mobile_sample_review(browser, report, bundle=None):
    reviews = {key: panel for key, panel in getattr(browser, "_sample_reviews", {}).items() if not panel._closed}
    key = report.source_archive_sha256 or report.source_path
    current = reviews.get(key)
    if current is not None and not current._closed:
        browser._sample_review = current
        current.window.lift()
        current.window.focus_set()
        return current
    browser._sample_review = MobileSampleReviewWindow(browser, report, bundle)
    reviews[key] = browser._sample_review
    browser._sample_reviews = reviews
    return browser._sample_review
