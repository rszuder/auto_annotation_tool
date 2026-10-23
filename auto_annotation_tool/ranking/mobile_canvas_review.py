"""Canvas-first, source-ROI review with immutable MT parents (P2B2).

Coordinates are verified pre-ROI Bitmap pixels, never screen pixels. The
SHA-bound sidecar owns editable children and manual plates. Nothing writes
predictions, source images, or the legacy review. Metrics are ASSISTED, not
independent/blind ground truth. A scene must be explicitly checked before
its provisional inventory becomes an evaluation denominator.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import uuid
from pathlib import Path

from .mobile_source_frame_roi import source_invocation_context, source_pose_quad
from .mobile_pose_metrics import validate_mt_quad, compare_mt_pose_to_gt
from ..rectification.polygon_validator import PolygonValidator

SCHEMA = "alpr.mobile.canvas_review.v1"
KEY = "canvas_review_v1"
PROVENANCE = "ASSISTED_CANVAS_SOURCE_ROI"
MAX_OBJECTS = 128
DETECTION_STATUSES = frozenset({"VALID_QUAD", "DETECTION_INVALID_QUAD"})


def has_scene(session, gid):
    return KEY in session.review.invocation_annotations.get(gid, {})


def context(session, gid, image_size=None):
    group = session.mt_invocations.get(gid)
    if not group or not group.executed or group.cancelled or group.execution_failed:
        return None
    return source_invocation_context(group.records, gid, session.entry_names, image_size)


def _prediction(session, aid):
    attempt = session.attempts.get(aid, {})
    samples = [session.samples[sid] for sid in session.sample_ids_by_attempt.get(aid, ())
               if sid in session.samples and not session.cancelled(session.samples[sid])]
    # An attempt is one inference event, not an OCR consensus or a subject.
    values = {str(s.get("raw_prediction", s.get("prediction", "")) or "") for s in samples}
    status = str(attempt.get("mz_status") or "").upper()
    if not status and samples:
        statuses = {str(s.get("mz_status") or "").upper() for s in samples}
        if len(statuses) == 1:
            status = next(iter(statuses))
    if status == "NOT_RUN":
        return "", "NOT_RUN", False
    if len(values) > 1:
        return str(attempt.get("raw_prediction", attempt.get("prediction", "")) or ""), "AMBIGUOUS_SAMPLES", True
    value = (next(iter(values)) if values else
             str(attempt.get("raw_prediction", attempt.get("prediction", "")) or ""))
    return value, status or "UNKNOWN", status not in ("", "UNKNOWN") or bool(value)


def _parents(session, ctx):
    result = []
    for row in ctx["records"]:
        if str(row.get("mt_status") or "").upper() not in DETECTION_STATUSES:
            continue
        aid = str(row.get("id") or row.get("attempt_id") or "")
        if not aid or aid not in session.attempts or any(p["attempt_id"] == aid for p in result):
            raise ValueError("Niespójny identyfikator wskazania MT")
        quad = source_pose_quad(row, ctx["size"])
        pred, status, ran = _prediction(session, aid)
        result.append(dict(parent_id="MT:" + aid, attempt_id=aid,
            detection_index=row.get("mt_detection_index"),
            quad=[list(p) for p in quad] if quad else None,
            mz_prediction=pred, mz_status=status, mz_ran=ran))
    indices = []
    for parent in result:
        try:
            index = int(parent["detection_index"])
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Brak jednoznacznego indeksu detekcji MT") from None
        if index < 0 or index in indices:
            raise ValueError("Powielony lub nieprawidłowy indeks detekcji MT")
        indices.append(index)
    group = session.mt_invocations[ctx["invocation_id"]]
    declared = getattr(group, "detection_count", None)
    if declared is not None and int(declared) != len(result):
        raise ValueError("Niepełny wykaz wyników inferencji MT")
    return result


def _binding(session, ctx, parents):
    payload = dict(source_archive_sha256=session.review.source_archive_sha256,
        mt_invocation_id=ctx["invocation_id"], image_entry=ctx["entry"],
        image_size=list(ctx["size"]), roi=list(ctx["roi"]),
        source_sequence=ctx["source_sequence"], source_timestamp_nanos=ctx["source_timestamp_nanos"],
        parents=parents)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _post_nms_proof(session, gid, parents):
    """Trust only the trace-backed Android 2->1 proof, never bbox overlap alone.

    This is not a physical-plate counter. An additional physical plate missed
    by the final MT is still entered manually by the operator.
    """
    from .mobile_mt_postdedup import post_nms_proof
    proof = post_nms_proof(session, gid)
    aids = {p["attempt_id"] for p in parents}
    if (not isinstance(proof, dict) or len(parents) != 2
            or proof.get("raw") != 2 or proof.get("after_dedup") != 1
            or proof.get("suppressed") != 1
            or proof.get("primary_id") not in aids
            or proof.get("suppressed_id") not in aids
            or proof.get("primary_id") == proof.get("suppressed_id")):
        return None
    return copy.deepcopy(proof)


def _pending_nms_review(s, proof):
    """Unmigrated reviews remain intact and must be reconciled explicitly."""
    if not proof:
        return
    suppressed_id = proof["suppressed_id"]
    objects = [o for o in s["objects"] if o["attempt_id"] == suppressed_id]
    if len(objects) == 1 and not objects[0].get("post_nms_suppressed", False):
        s["_post_nms_pending"] = suppressed_id  # transient; never store this hint


def _verify_nms_review(s, proof):
    flagged = [o for o in s["objects"] if o.get("post_nms_suppressed", False)]
    if not flagged:
        return
    if (proof is None or len(flagged) != 1
            or flagged[0]["attempt_id"] != proof["suppressed_id"]
            or s.get("post_nms_evidence") != proof):
        raise ValueError("Brak zgodnego dowodu NMS dla wyłączenia surowego MT")


def _new_object(oid, parent=None, quad=None):
    return dict(object_id=oid, parent_id=parent["parent_id"] if parent else None,
        attempt_id=parent["attempt_id"] if parent else "", kind="child" if parent else "manual",
        quad=copy.deepcopy(parent["quad"] if parent else quad),
        geometry_state="unconfirmed" if parent else "operator_drawn",
        error=False, gt_text="", text_exclusion_reason="", text_confirmed=False)


def _legacy_to_source(points, attempt, ctx):
    """Convert only a declared, proven MT-input transform. Never guess size."""
    try:
        scale, px, py = (float(attempt[k]) for k in ("input_scale", "input_pad_x", "input_pad_y"))
        roi = tuple(float(attempt[k]) for k in ("roi_left", "roi_top", "roi_right", "roi_bottom"))
        if roi != tuple(ctx["roi"]) or scale <= 0 or not all(math.isfinite(v) for v in (scale, px, py)):
            return None
        quad = [((float(x)-px)/scale + roi[0], (float(y)-py)/scale + roi[1]) for x,y in points]
        return [list(p) for p in validate_mt_quad(quad, *ctx["size"])]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _seed(session, ctx, parents):
    objects = [_new_object("GT:"+p["attempt_id"], parent=p) for p in parents]
    old = session.invocation_annotation(ctx["invocation_id"]).get("multi_plate_v1", {})
    old_plates = old.get("plates", []) if isinstance(old, dict) else []
    warnings = []
    for obj, parent in zip(objects, parents):
        aid = parent["attempt_id"]
        annotation = session.review.attempt_annotations.get(aid, {})
        obj["error"] = annotation.get("is_plate") is False
        # Restore a real saved correction, not a visual "imprecise" label.
        correction = annotation.get("pose_mt_correction_v1")
        if correction:
            from .mobile_pose_correction import correction_for_attempt
            attempt = session.attempts[aid]
            try:
                scale,px,py = (float(attempt[k]) for k in ("input_scale","input_pad_x","input_pad_y"))
                l,t,_,_ = ctx["roi"]
                model = [((x-l)*scale+px,(y-t)*scale+py) for x,y in parent["quad"]]
                points = correction_for_attempt(annotation, attempt_id=aid,
                    source_sha=session.review.source_archive_sha256,
                    image_entry=attempt["mt_input_evidence_entry"],
                    size=(float(attempt["input_width"]),float(attempt["input_height"])), prediction=model)
                mapped = _legacy_to_source(points, attempt, ctx)
                if mapped is None:
                    raise ValueError("Brak zgodnej transformacji historycznej korekty")
                obj.update(quad=mapped,geometry_state="operator_corrected",
                    legacy_geometry_source="pose_mt_correction_v1")
            except (KeyError, TypeError, ValueError, OverflowError):
                warnings.append("Historyczna korekta nie ma zgodnej proweniencji: " + aid)
        matches = [p for p in old_plates if p.get("attempt_id") == aid]
        if len(matches) == 1:
            source = matches[0]
            obj.update(gt_text=str(source.get("gt_text") or ""),
                text_exclusion_reason=str(source.get("text_exclusion_reason") or ""))
            obj["text_confirmed"] = bool(obj["gt_text"] or obj["text_exclusion_reason"])
            obj["legacy_text_source"] = str(source.get("plate_id") or "")
        elif len(parents) == 1 and not old_plates:
            subject = session.review.subjects.get(session.attempts[aid].get("subject_key"), {})
            if subject.get("evaluable") is True and subject.get("ground_truth"):
                obj.update(gt_text=subject["ground_truth"], text_confirmed=True,
                    legacy_text_source="single_subject_confirmed")
    # Old unmatched rectangles can be displayed, but remain rectangles, NOT
    # four independently annotated corners. Their old IDs remain auditable.
    for plate in old_plates:
        if plate.get("attempt_id"):
            continue
        box = plate.get("bbox_mt_px")
        transformed = None
        if isinstance(box, (list, tuple)) and len(box) == 4:
            x1,y1,x2,y2 = box
            for record in ctx["records"]:
                if record.get("mt_input_evidence_entry") != plate.get("bbox_image_entry"):
                    continue
                transformed = _legacy_to_source([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], record, ctx)
                if transformed:
                    break
        if transformed:
            obj = _new_object("LEGACY:"+str(plate["plate_id"]), quad=transformed)
            obj.update(geometry_state="legacy_bbox", gt_text=str(plate.get("gt_text") or ""),
                text_exclusion_reason=str(plate.get("text_exclusion_reason") or ""),
                text_confirmed=bool(plate.get("gt_text") or plate.get("text_exclusion_reason")),
                legacy_plate_id=plate["plate_id"])
            objects.append(obj)
        else:
            warnings.append("Historyczna tablica bez zgodnej geometrii: " + str(plate.get("plate_id")))
    result = dict(schema=SCHEMA, provenance=PROVENANCE,
        source_archive_sha256=session.review.source_archive_sha256,
        mt_invocation_id=ctx["invocation_id"], image_entry=ctx["entry"],
        image_size=list(ctx["size"]), roi=list(ctx["roi"]),
        source_binding=_binding(session, ctx, parents), parents=parents, objects=objects,
        checked=False, exclusion_reason="", migration_warnings=warnings, events=[])
    proof = _post_nms_proof(session, ctx["invocation_id"], parents)
    if proof:
        raw = next(o for o in objects if o["attempt_id"] == proof["suppressed_id"])
        # A legacy GT, corrected geometry or error flag is operator evidence.
        # Never hide it automatically or change past decisions.
        untouched = (not raw["error"] and not raw["gt_text"]
            and not raw["text_exclusion_reason"] and not raw["text_confirmed"]
            and raw["geometry_state"] == "unconfirmed"
            and not raw.get("legacy_geometry_source")
            and not raw.get("legacy_text_source"))
        if untouched:
            raw["post_nms_suppressed"] = True
            result["post_nms_evidence"] = proof
        else:
            _pending_nms_review(result, proof)
    return result


def scene(session, gid):
    ctx = context(session, gid)
    if ctx is None:
        raise ValueError("Brak zweryfikowanej pełnej klatki z ROI tego wywołania MT")
    parents = _parents(session, ctx)
    saved = session.invocation_annotation(gid).get(KEY)
    if saved is None:
        return _seed(session, ctx, parents)
    if not isinstance(saved, dict) or saved.get("schema") != SCHEMA:
        raise ValueError("Nieobsługiwany zapis weryfikacji canvas")
    if (saved.get("source_binding") != _binding(session, ctx, parents)
            or saved.get("parents") != parents or saved.get("mt_invocation_id") != gid
            or saved.get("source_archive_sha256") != session.review.source_archive_sha256
            or saved.get("image_entry") != ctx["entry"] or saved.get("image_size") != list(ctx["size"])
            or saved.get("roi") != list(ctx["roi"])):
        raise ValueError("Weryfikacja canvas nie odpowiada źródłowej inferencji/ROI")
    _validate_objects(saved)
    proof = _post_nms_proof(session, gid, parents)
    _verify_nms_review(saved, proof)
    result = copy.deepcopy(saved)
    _pending_nms_review(result, proof)
    return result


def _validate_objects(s):
    objects = s.get("objects")
    if type(s.get("checked")) is not bool:
        raise ValueError("Nieprawidłowe potwierdzenie obrazu")
    reason = s.get("exclusion_reason", "")
    if not isinstance(reason, str) or len(reason) > 240 or (reason and not s["checked"]):
        raise ValueError("Niespójny stan sprawdzenia / wyłączenia obrazu")
    if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ValueError("Nieprawidłowy wykaz ramek canvas")
    ids = [o.get("object_id") for o in objects if isinstance(o, dict)]
    if len(ids) != len(objects) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Powielone lub brakujące identyfikatory ramek")
    parents = {p["parent_id"]:p for p in s["parents"]}
    seen = set()
    for obj in objects:
        parent = obj.get("parent_id")
        if parent:
            if parent not in parents or parent in seen or obj.get("attempt_id") != parents[parent]["attempt_id"] or obj.get("kind") != "child":
                raise ValueError("Korekta musi mieć dokładnie jednego, niezmiennego rodzica MT")
            seen.add(parent)
        elif obj.get("kind") != "manual" or obj.get("attempt_id"):
            raise ValueError("Ręczna ramka nie może udawać wyniku MT")
        if type(obj.get("error")) is not bool or type(obj.get("text_confirmed")) is not bool:
            raise ValueError("Nieprawidłowa flaga ramki")
        suppressed = obj.get("post_nms_suppressed", False)
        if type(suppressed) is not bool or (suppressed and not parent):
            raise ValueError("Nieprawidłowy stan RAW odrzuconego przez NMS")
        if not all(isinstance(obj.get(k), str) for k in ("gt_text","text_exclusion_reason","geometry_state")):
            raise ValueError("Nieprawidłowe GT ramki")
        if len(obj["gt_text"]) > 256 or len(obj["text_exclusion_reason"]) > 240 or (obj["gt_text"] and obj["text_exclusion_reason"]):
            raise ValueError("Niespójne GT numeru i przyczyna nieczytelności")
        if obj.get("quad") is not None:
            quad = validate_mt_quad(obj["quad"], *s["image_size"])
            if not parent:
                l,t,r,b=s["roi"]
                if any(not (l <= x <= r and t <= y <= b) for x,y in quad):
                    raise ValueError("Ręczna tablica poza analizowanym ROI")
    if seen != set(parents):
        raise ValueError("Brak ramki potomnej dla wskazania MT")
    suppressed_objects = [o for o in objects if o.get("post_nms_suppressed", False)]
    if suppressed_objects:
        evidence = s.get("post_nms_evidence")
        if (len(suppressed_objects) != 1 or not isinstance(evidence, dict)
                or evidence.get("suppressed_id") != suppressed_objects[0]["attempt_id"]
                or evidence.get("raw") != 2 or evidence.get("after_dedup") != 1
                or evidence.get("suppressed") != 1):
            raise ValueError("Wyłączenie RAW wymaga jednoznacznego dowodu 2→1 NMS")


def _object(s, oid):
    hits = [o for o in s["objects"] if o["object_id"] == oid]
    if len(hits) != 1:
        raise ValueError("Nieznana ramka canvas")
    return hits[0]


def ordered_quad(points, size, roi=None):
    if len(points) != 4:
        raise ValueError("Wskaż cztery narożniki")
    # Same polygon ordering utility as Z2; never apply it to MT parents.
    raw = [(float(x),float(y)) for x,y in points]
    ordered = PolygonValidator.order_points(raw)
    quad = validate_mt_quad(ordered, *size)
    if roi is not None:
        l,t,r,b = roi
        if any(not (l <= x <= r and t <= y <= b) for x,y in quad):
            raise ValueError("Brakującą tablicę zaznacz wyłącznie wewnątrz analizowanego ROI")
    return [list(p) for p in quad]


def counts(s):
    # RAW rejected by proven Android NMS is neither a physical GT nor a final FP.
    # It remains in `parents` and `objects` as immutable/auditable evidence.
    scored = [o for o in s["objects"] if not o.get("post_nms_suppressed", False)]
    active = [o for o in scored if not o["error"]]
    return dict(expected=len(active), mt=len(s["parents"]),
        linked=sum(bool(o["parent_id"]) for o in active),
        missed=sum(not o["parent_id"] for o in active),
        false_positive=sum(bool(o["parent_id"]) and o["error"] for o in scored),
        operator_errors=sum(not o["parent_id"] and o["error"] for o in scored),
        raw_suppressed=len(s["objects"]) - len(scored))


def _store(session, gid, s, action, oid="", *, object_before=None):
    _validate_objects(s)
    # Source/trace binding is checked on *every* write, also on undo/redo.
    _verify_nms_review(s, _post_nms_proof(session, gid, s["parents"]))
    s.pop("_post_nms_pending", None)
    changed = copy.deepcopy(session.review)
    inv = dict(changed.invocation_annotations.get(gid, {}))
    from .mobile_human_review import _utc_now_iso
    s["events"].append(dict(action=action, object_id=oid, saved_at=_utc_now_iso(),
        object_after=copy.deepcopy(next((o for o in s["objects"] if o["object_id"] == oid), None)),
        review_revision_before=session.review.review_revision))
    if object_before is not None:
        s["events"][-1]["object_before"] = copy.deepcopy(object_before)
    s["expected_plate_count"] = counts(s)["expected"]
    inv[KEY] = s
    # Old forms/GT are retained untouched for history. Canvas has its own
    # verification path; never feed this derived count into legacy denominators.
    changed.invocation_annotations[gid] = inv
    changed.review_status = "IN_PROGRESS"
    session._save_change(changed)


def _edit(session, gid, oid, action, modify):
    s = scene(session, gid)
    if _object(s, oid).get("post_nms_suppressed", False):
        raise ValueError("RAW odrzucone przez NMS nie jest osobną tablicą GT; użyj D dla pominiętej tablicy")
    modify(_object(s, oid), s)
    s.update(checked=False, exclusion_reason="")
    _store(session, gid, s, action, oid)


def add_plate(session, gid, points):
    s = scene(session, gid)
    if len(s["objects"]) >= MAX_OBJECTS:
        raise ValueError("Osiągnięto limit ramek canvas")
    quad = ordered_quad(points, s["image_size"], s["roi"])
    oid = "MANUAL:" + uuid.uuid4().hex
    s["objects"].append(_new_object(oid, quad=quad))
    s.update(checked=False, exclusion_reason="")
    _store(session, gid, s, "add_manual_plate", oid)
    return oid


def correct_plate(session, gid, oid, points):
    def edit(obj, s):
        # Dragging an indexed corner keeps its correspondence with its MT
        # parent; sorting on every drag would silently swap corner identities.
        quad = validate_mt_quad(points, *s["image_size"])
        if not obj["parent_id"]:
            l,t,r,b=s["roi"]
            if any(not (l <= x <= r and t <= y <= b) for x,y in quad):
                raise ValueError("Ręczna tablica poza analizowanym ROI")
        obj["quad"] = [list(p) for p in quad]
        obj["geometry_state"] = "operator_corrected" if obj["parent_id"] else "operator_drawn"
    _edit(session, gid, oid, "correct_child_geometry", edit)



def remove_operator_geometry(session, gid, oid):
    """Remove a manual object or reset ONLY a child's geometry to its MT parent.

    MT evidence is immutable. A reset keeps the per-plate GT and error decision.
    Deleted manual objects live only in the audit events, not in metrics or view.
    """
    s = scene(session, gid)
    obj = _object(s, oid)
    if obj.get("post_nms_suppressed", False):
        raise ValueError("Odrzuconego RAW nie można edytować ani usuwać; pozostaje dowodem MT")
    before = copy.deepcopy(obj)
    if obj["parent_id"]:
        parent = next(p for p in s["parents"] if p["parent_id"] == obj["parent_id"])
        obj.update(quad=copy.deepcopy(parent["quad"]), geometry_state="unconfirmed")
        obj.pop("legacy_geometry_source", None)
        action = "reset_child_to_mt_original"
    else:
        s["objects"].remove(obj)
        action = "remove_manual_plate"
    s.update(checked=False, exclusion_reason="")
    _store(session, gid, s, action, oid, object_before=before)
    return action


def accept_post_nms_raw_only(session, gid):
    """Explicit operator reconciliation of an old canvas scene with trace 2->1.

    History, GT, geometry, and error flags of the suppressed raw attempt remain
    stored. The old `checked` decision is invalidated for reinspection; no
    physical plate count is inferred from the Android trace alone.
    """
    s = scene(session, gid)
    proof = _post_nms_proof(session, gid, s["parents"])
    if not proof or s.get("_post_nms_pending") != proof["suppressed_id"]:
        raise ValueError("Brak nierozstrzygniętej ramki RAW z dowodem NMS 2→1")
    obj = next(o for o in s["objects"] if o["attempt_id"] == proof["suppressed_id"])
    before = copy.deepcopy(obj)
    obj["post_nms_suppressed"] = True
    s["post_nms_evidence"] = proof
    s.update(checked=False, exclusion_reason="")
    _store(session, gid, s, "operator_accept_trace_proven_nms_raw_only", obj["object_id"], object_before=before)
    return obj["object_id"]


def set_scene_review_state(session, gid, *, checked, exclusion_reason=""):
    """Inspected is distinct from complete/evaluable; validation remains mandatory.

    A user can inspect an image with incomplete GT. Such an image stays pending
    in group_issues and outside metric denominators until the data are complete.
    An exclusion must also be inspected. Unchecking it does not erase any GT.
    """
    if type(checked) is not bool:
        raise ValueError("Stan sprawdzenia musi być logiczny")
    reason = " ".join(str(exclusion_reason or "").split())
    if len(reason) > 240 or (reason and not checked):
        raise ValueError("Obraz nie do oceny musi być również sprawdzony; opis do 240 znaków")
    s = scene(session, gid)
    if checked and not reason:
        for obj in s["objects"]:
            if not obj["error"] and not obj.get("post_nms_suppressed", False) and obj.get("quad") and obj["geometry_state"] == "unconfirmed":
                obj["geometry_state"] = "operator_confirmed_unchanged"
    s.update(checked=checked, exclusion_reason=reason)
    _store(session, gid, s, "set_roi_review_checkboxes")


def merge_review_cells(rows):
    """Merge per-image/per-plate presence states, without turning gaps into success."""
    rows = list(rows)
    def cell(values):
        values = [v for v in values if v != "—"]
        if not values:
            return "—"
        if all(v in ("✓", "×") for v in values):
            return "✓"
        return "○" if all(v == "○" for v in values) else "◐"
    return tuple(cell(row[i] for row in rows) for i in range(5))


def object_review_cells(s, obj):
    """ROI inspected, frame decision, text GT, corners, completion."""
    inspected = "✓" if s["checked"] else "○"
    if obj.get("post_nms_suppressed", False):
        return (inspected, "—", "—", "—", inspected)
    if s.get("exclusion_reason") and s["checked"]:
        return ("✓", "—", "—", "—", "✓")
    if obj["error"]:
        return (inspected, "×", "—", "—", inspected)
    parent = next((p for p in s["parents"] if p["parent_id"] == obj["parent_id"]), None)
    corners = bool(obj.get("quad")) and obj["geometry_state"] != "unconfirmed"
    text = ("✓" if obj["text_confirmed"] and obj["gt_text"] else
            "—" if obj["text_confirmed"] and obj["text_exclusion_reason"] else
            "○" if parent and parent["mz_ran"] else "—")
    ready = (s["checked"] and bool(obj.get("quad")) and text != "○" and
             not (parent and parent["mz_status"] == "AMBIGUOUS_SAMPLES"))
    return (inspected, "✓" if corners else "○", text,
            "✓" if corners else "○", "✓" if ready else "○")


def scene_review_cells(s):
    if s.get("exclusion_reason") and s["checked"]:
        return ("✓", "—", "—", "—", "✓")
    rows = [object_review_cells(s, obj) for obj in s["objects"]]
    cells = list(merge_review_cells(rows))
    cells[0] = "✓" if s["checked"] else "○"
    if not rows:
        cells[1] = cells[0]  # Explicitly inspected zero, never an inferred zero.
    cells[-1] = "✓" if s["checked"] and not _content_issues(s) else "○"
    return tuple(cells)


def toggle_error(session, gid, oid):
    def edit(obj, s):
        obj["error"] = not obj["error"]
    _edit(session, gid, oid, "toggle_error_flag", edit)


def set_text(session, gid, oid, text, reason=""):
    from .mobile_human_review import normalize_registration
    gt = normalize_registration(text)
    reason = " ".join(str(reason or "").split())
    if len(gt) > 256 or len(reason) > 240 or (gt and reason):
        raise ValueError("Wpisz numer GT albo przyczynę nieczytelności, nie oba naraz")
    def edit(obj, s):
        obj.update(gt_text=gt, text_exclusion_reason=reason, text_confirmed=bool(gt or reason))
    _edit(session, gid, oid, "edit_plate_gt", edit)


def _content_issues(s):
    issues = []
    if s.get("_post_nms_pending"):
        issues.append("Uzgodnij dodatkowy surowy MT odrzucony przez NMS przed oceną ROI")
    parents = {p["parent_id"]:p for p in s["parents"]}
    for obj in s["objects"]:
        if obj.get("post_nms_suppressed", False) or obj["error"]:
            continue
        oid = obj["object_id"]
        if not obj.get("quad"):
            issues.append(f"Brak czterech rogów: {oid}")
        parent = parents.get(obj["parent_id"])
        if parent and parent["mz_ran"] and not (obj["text_confirmed"] and (obj["gt_text"] or obj["text_exclusion_reason"])):
            issues.append(f"Brak GT numeru albo przyczyny nieczytelności: {oid}")
        if parent and parent["mz_status"] == "AMBIGUOUS_SAMPLES":
            issues.append(f"Sprzeczne odczyty MZ przypisane do jednej detekcji: {oid}")
    if s.get("migration_warnings"):
        issues.append("Historyczne dane wymagają sprawdzenia na obrazie")
    return issues


def check_scene(session, gid):
    s = scene(session, gid)
    issues = _content_issues(s)
    if issues:
        raise ValueError(issues[0])
    for obj in s["objects"]:
        if not obj.get("post_nms_suppressed", False) and not obj["error"] and obj["geometry_state"] == "unconfirmed":
            obj["geometry_state"] = "operator_confirmed_unchanged"
    s.update(checked=True, exclusion_reason="")
    _store(session, gid, s, "confirm_complete_roi_review")


def exclude_scene(session, gid, reason):
    reason = " ".join(str(reason or "").split())
    if not reason or len(reason) > 240:
        raise ValueError("Podaj przyczynę wyłączenia obrazu (maksymalnie 240 znaków)")
    s = scene(session, gid)
    s.update(checked=True, exclusion_reason=reason)
    _store(session, gid, s, "exclude_roi_review")


def group_issues(session, gid):
    try:
        s = scene(session, gid)
    except (ValueError, TypeError, KeyError) as e:
        return [f"Canvas {gid}: {e}"]
    if s.get("checked") is True and str(s.get("exclusion_reason") or "").strip():
        return []
    issues = _content_issues(s)
    if s.get("checked") is not True:
        issues.insert(0, "Sprawdź cały obszar ROI i oznacz obraz jako sprawdzony")
    return [f"Canvas {gid}: {i}" for i in issues]


def subject_issues(session, subject_key):
    ids = {session.invocation_by_attempt.get(aid) for aid in session.subjects.get(subject_key, {}).get("attempts", ())}
    return [i for gid in ids if gid and has_scene(session, gid) for i in group_issues(session, gid)]


def summary(session):
    from .mobile_human_review import align_plate_text
    result = dict(schema=SCHEMA, provenance=PROVENANCE,
        independent_gt=False, source_archive_sha256=session.review.source_archive_sha256,
        review_revision=session.review.review_revision, scene_count=0, checked_scenes=0,
        inspected_scenes=0, incomplete_checked_scenes=0,
        pending_scenes=0, excluded_scenes=0, expected_plates=0, linked_plates=0,
        missed_plates=0, false_positive_mt=0, operator_errors=0, raw_suppressed_mt=0, gt_characters=0,
        text_errors=0, evaluated_reads=0, exact_reads=0, geometry_n=0,
        polygon_iou_mean_pct=None, nmce_mean_pct=None, cer=None,
        note="Ocena asystowana, powiązania operatora; nie niezależny test ślepy ani automatyczny matching po progu IoU.",
        scenes=[], rows=[])
    geom = []
    for gid in session.mt_invocations:
        if not has_scene(session, gid):
            continue
        result["scene_count"] += 1
        try:
            s = scene(session, gid)
        except (ValueError, TypeError, KeyError) as e:
            result["pending_scenes"] += 1
            result["scenes"].append(dict(mt_invocation_id=gid, status="INVALID", reason=str(e)))
            continue
        issues = group_issues(session, gid)
        excluded = bool(s.get("exclusion_reason")) and s.get("checked") is True
        evaluable = not issues and not excluded
        result["inspected_scenes"] += int(s.get("checked") is True)
        result["incomplete_checked_scenes"] += int(s.get("checked") is True and bool(issues) and not excluded)
        result["excluded_scenes" if excluded else "checked_scenes" if evaluable else "pending_scenes"] += 1
        tally = counts(s)
        result["scenes"].append(dict(mt_invocation_id=gid, image_entry=s["image_entry"],
            status="EXCLUDED" if excluded else "CHECKED" if evaluable else "PENDING",
            roi=s["roi"], counts=tally, issues=issues, exclusion_reason=s.get("exclusion_reason", "")))
        if evaluable:
            result["raw_suppressed_mt"] += tally["raw_suppressed"]
            for dst,src in (("expected_plates","expected"),("linked_plates","linked"),
                    ("missed_plates","missed"),("false_positive_mt","false_positive"),("operator_errors","operator_errors")):
                result[dst] += tally[src]
        parents = {p["parent_id"]:p for p in s["parents"]}
        for obj in s["objects"]:
            parent = parents.get(obj["parent_id"])
            raw_only = obj.get("post_nms_suppressed", False)
            row = dict(mt_invocation_id=gid, image_entry=s["image_entry"],
                object_id=obj["object_id"], parent_id=obj["parent_id"], attempt_id=obj["attempt_id"],
                object_kind=obj["kind"], error_flag=obj["error"], included=evaluable and not raw_only,
                post_nms_suppressed_raw=raw_only,
                outcome="RAW_SUPPRESSED_POST_NMS" if raw_only else
                    (("FALSE_POSITIVE_MT" if parent else "OPERATOR_ERROR") if obj["error"] else ("LINKED_MT" if parent else "MISSED_MT")),
                original_mt_quad=parent["quad"] if parent else None, operator_quad=obj["quad"],
                geometry_state=obj["geometry_state"], gt_text=obj["gt_text"],
                text_exclusion_reason=obj["text_exclusion_reason"],
                mz_prediction=parent["mz_prediction"] if parent else "",
                mz_status=parent["mz_status"] if parent else "NOT_RUN",
                polygon_iou_pct=None, nmce_pct=None, cer=None, provenance=PROVENANCE)
            if evaluable and not raw_only and not obj["error"]:
                if parent and parent["quad"] and obj["quad"] and obj["geometry_state"] != "unconfirmed":
                    m = compare_mt_pose_to_gt(parent["quad"], obj["quad"], *s["image_size"])
                    row.update(polygon_iou_pct=m["polygon_iou_pct"], nmce_pct=m["nmce_pct"])
                    geom.append(m)
                if parent and parent["mz_ran"] and obj["text_confirmed"] and obj["gt_text"]:
                    a = align_plate_text(obj["gt_text"], parent["mz_prediction"])
                    row["cer"] = a.cer
                    result["gt_characters"] += len(a.ground_truth)
                    result["text_errors"] += a.edit_distance
                    result["evaluated_reads"] += 1
                    result["exact_reads"] += int(a.exact_match)
            result["rows"].append(row)
    if result["gt_characters"]:
        result["cer"] = result["text_errors"] / result["gt_characters"]
    if geom:
        result.update(geometry_n=len(geom),
            polygon_iou_mean_pct=sum(m["polygon_iou_pct"] for m in geom)/len(geom),
            nmce_mean_pct=sum(m["nmce_pct"] for m in geom)/len(geom))
    result["mt_precision_operator"] = (result["linked_plates"] / (result["linked_plates"] + result["false_positive_mt"])
        if result["linked_plates"] + result["false_positive_mt"] else None)
    result["mt_recall_operator"] = (result["linked_plates"] / result["expected_plates"] if result["expected_plates"] else None)
    return result


def export(session, directory):
    from .mobile_human_review import _atomic_write
    data = summary(session)
    directory = Path(directory)
    names = ["canvas_review_summary.json", "canvas_review_plates.csv", "canvas_review_report.md"]
    paths = [directory/n for n in names]
    _atomic_write(paths[0], json.dumps(data, ensure_ascii=False, indent=2))
    output = io.StringIO(newline="")
    rows = data["rows"]
    fields = list(rows[0]) if rows else ["mt_invocation_id", "object_id", "provenance"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    _atomic_write(paths[1], "\ufeff"+output.getvalue())
    def val(n):
        return "nie dotyczy" if n is None else f"{n:.4f}" if isinstance(n,float) else str(n)
    text = "# Weryfikacja ALPR na canvasie\n\n" + data["note"] + "\n\n"
    text += f"Źródło SHA-256: `{data['source_archive_sha256']}`. Rewizja: {data['review_revision']}.\n\n"
    text += "| Miara | Wynik |\n|---|---:|\n"
    for label,key in (("Obrazy przejrzane (w tym nie do oceny)","inspected_scenes"),
        ("Sprawdzone i ocenialne","checked_scenes"),("Sprawdzone z brakami danych","incomplete_checked_scenes"),
        ("Obrazy oczekujące na komplet decyzji","pending_scenes"),
        ("Obrazy wyłączone","excluded_scenes"),("Tablice oczekiwane w ROI","expected_plates"),
        ("Powiązane wskazania MT","linked_plates"),("Pominięte tablice","missed_plates"),
        ("Fałszywe wskazania MT","false_positive_mt"),("RAW odrzucone przez NMS","raw_suppressed_mt"),
        ("Błędy ramek operatora","operator_errors"),
        ("CER znaków","cer"),("IoU polygonów, średnia [%]","polygon_iou_mean_pct"),
        ("NMCE narożników, średnia [%]","nmce_mean_pct")):
        text += f"| {label} | {val(data[key])} |\n"
    text += "\nOryginał MT jest porównywany z potwierdzoną ramką potomną. Korekta nie jest nową tablicą. "
    text += "RAW odrzucone na podstawie zweryfikowanego śladu NMS pozostaje dowodem, nie jest drugim GT ani FP. "
    text += "Ramka ręczna bez rodzica oznacza pominięcie; jej odrzucenie nie jest fałszywą detekcją MT. "
    text += "Brak odczytu MZ/NOT_RUN i wyłączony numer GT nie są zastępowane sztuczną predykcją. "
    text += "Niepotwierdzone obrazy nie wchodzą do mianowników. Szczegóły i obie geometrie: canvas_review_plates.csv.\n"
    _atomic_write(paths[2], text)
    return paths
