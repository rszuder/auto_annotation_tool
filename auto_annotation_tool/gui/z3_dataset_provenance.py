"""Dataset provenance contract for Z3/PZ3 exports."""

from __future__ import annotations

from pathlib import Path


PROVENANCE_SCHEMA = "alpr.dataset.sample_provenance.v1"

RAW_MODEL_EXACT = "raw_model_exact"
MANUAL = "manual"
GT_ASSIST_CONFIRMED = "gt_assist_confirmed"
CVAT_IMPORT = "cvat_import"
MOBILE_HUMAN_REVIEW = "mobile_human_review"
LEGACY_UNTRACKED = "legacy_untracked"

KNOWN_CATEGORIES = (
    RAW_MODEL_EXACT,
    MANUAL,
    GT_ASSIST_CONFIRMED,
    CVAT_IMPORT,
    MOBILE_HUMAN_REVIEW,
    LEGACY_UNTRACKED,
)


def _norm(value) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _record_snapshot(record) -> tuple:
    if not isinstance(record, dict):
        return ("", ())
    character = str(record.get("character", "") or "").strip().upper()
    bbox = record.get("bbox", [])
    safe_bbox = []
    if isinstance(bbox, (list, tuple)):
        for value in list(bbox)[:4]:
            try:
                safe_bbox.append(round(float(value), 4))
            except Exception:
                safe_bbox.append(0.0)
    return character, tuple(safe_bbox)


def _final_matches_raw(data: dict) -> bool:
    raw = data.get("raw_detection")
    if not isinstance(raw, dict):
        return False

    raw_chars = raw.get("characters", [])
    final_chars = data.get("characters", [])
    if not isinstance(raw_chars, list) or not isinstance(final_chars, list):
        return False
    if len(raw_chars) != len(final_chars):
        return False

    return [
        _record_snapshot(rec)
        for rec in final_chars
    ] == [
        _record_snapshot(rec)
        for rec in raw_chars
    ]


def _has_gt_assist_confirmation(data: dict) -> bool:
    for field in ("correction_source", "review_source"):
        if _norm(data.get(field)) == GT_ASSIST_CONFIRMED:
            return True

    assist = data.get("gt_assist")
    if isinstance(assist, dict):
        if _norm(assist.get("status")) == "accepted":
            return True

    for rec in list(data.get("characters", []) or []):
        if not isinstance(rec, dict):
            continue
        if _norm(rec.get("correction_source")) == GT_ASSIST_CONFIRMED:
            return True
    return False


def _has_cvat_import(data: dict, source_bucket: str = "") -> bool:
    if _norm(source_bucket) == "cvat_manual":
        return True

    source_info = data.get("source_info")
    if isinstance(source_info, dict):
        if _norm(source_info.get("bucket")) == "cvat_manual":
            return True
        if _norm(source_info.get("origin")) == "cvat_import":
            return True

    for rec in list(data.get("characters", []) or []):
        if not isinstance(rec, dict):
            continue
        if _norm(rec.get("method")) in {"cvat", "cvat_manual", "cvat_import"}:
            return True
        if _norm(rec.get("source_kind")) == "cvat_manual":
            return True
    return False


def _has_local_manual(data: dict, source_bucket: str = "") -> bool:
    if _norm(source_bucket) == "local_manual":
        return True

    if _norm(data.get("fusion_strategy")) == "manual_correction":
        return True

    for field in ("correction_source", "review_source"):
        if _norm(data.get(field)) in {
            "manual",
            "local_manual",
            "manual_correction",
            "preview_editor",
        }:
            return True

    source_info = data.get("source_info")
    if isinstance(source_info, dict):
        if _norm(source_info.get("bucket")) == "local_manual":
            return True
        if _norm(source_info.get("origin")) in {
            "preview_editor",
            "manual_correction",
            "local_manual",
        }:
            return True

    for rec in list(data.get("characters", []) or []):
        if not isinstance(rec, dict):
            continue
        if _norm(rec.get("source_kind")) == "local_manual":
            return True
        if _norm(rec.get("method")) == "manual":
            return True
        if _norm(rec.get("box_source")) == "manual_box":
            return True
        if _norm(rec.get("sign_source")) == "manual_sign":
            return True

    return False


def _has_mobile_human_review(data: dict) -> bool:
    if _norm(data.get("source_expected_text_source")) == "mobile_crop_human_review":
        return True

    acquisition = data.get("mobile_acquisition")
    if isinstance(acquisition, dict):
        for field in (
            "human_review",
            "reviewed",
            "review_id",
            "review_revision",
        ):
            if acquisition.get(field):
                return True
    return False


def _is_raw_model_exact(data: dict) -> bool:
    raw = data.get("raw_detection")
    validation = data.get("raw_validation")
    if not isinstance(raw, dict) or not isinstance(validation, dict):
        return False
    if str(raw.get("contract") or "").strip() != "gt_blind.v1":
        return False
    if _norm(validation.get("status")) != "perfect":
        return False
    if not bool(validation.get("exact_text_match")):
        return False
    if not bool(validation.get("exact_count_match")):
        return False
    if not bool(validation.get("geometry_ok")):
        return False
    return _final_matches_raw(data)


def classify_plate_dataset_provenance(
    host,
    data: dict | None,
    *,
    meta_path: Path | None = None,
    source_bucket: str = "",
) -> dict:
    source_data = data if isinstance(data, dict) else {}
    evidence: list[str] = []

    if _has_gt_assist_confirmation(source_data):
        category = GT_ASSIST_CONFIRMED
        evidence.append("gt_assist_confirmed")
    elif _has_cvat_import(source_data, source_bucket):
        category = CVAT_IMPORT
        evidence.append("cvat_import")
    elif _has_local_manual(source_data, source_bucket):
        category = MANUAL
        evidence.append("manual_review")
    elif _has_mobile_human_review(source_data):
        category = MOBILE_HUMAN_REVIEW
        evidence.append("mobile_crop_human_review")
    elif _is_raw_model_exact(source_data):
        category = RAW_MODEL_EXACT
        evidence.append("gt_blind_raw_exact")
    else:
        category = LEGACY_UNTRACKED
        evidence.append("no_trusted_provenance_contract")

    raw = source_data.get("raw_detection")
    raw_validation = source_data.get("raw_validation")
    source_info = source_data.get("source_info")

    return {
        "schema": PROVENANCE_SCHEMA,
        "category": category,
        "evidence": evidence,
        "raw_contract": (
            str(raw.get("contract") or "").strip()
            if isinstance(raw, dict)
            else ""
        ),
        "raw_validation_status": (
            str(raw_validation.get("status") or "").strip()
            if isinstance(raw_validation, dict)
            else ""
        ),
        "source_image_id": str(
            source_data.get("source_image_id") or ""
        ).strip(),
        "source_annotation_id": str(
            source_data.get("source_annotation_id")
            or source_data.get("plate_annotation_id")
            or ""
        ).strip(),
        "source_geometry_hash": str(
            source_data.get("source_geometry_hash") or ""
        ).strip(),
        "source_gt_hash": str(
            source_data.get("source_gt_hash") or ""
        ).strip(),
        "source_geometry_revision_id": str(
            source_data.get("source_geometry_revision_id") or ""
        ).strip(),
        "source_gt_revision_id": str(
            source_data.get("source_gt_revision_id") or ""
        ).strip(),
        "ground_truth_source": str(
            source_data.get("ground_truth_source") or ""
        ).strip(),
        "plate_source_bucket": str(source_bucket or "").strip(),
        "plate_source_origin": (
            str(source_info.get("origin") or "").strip()
            if isinstance(source_info, dict)
            else ""
        ),
        "meta_source": (
            str(meta_path)
            if meta_path is not None
            else ""
        ),
    }


def summarize_dataset_provenance(items) -> dict[str, int]:
    counts = {category: 0 for category in KNOWN_CATEGORIES}
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            continue
        category = str(
            provenance.get("category") or LEGACY_UNTRACKED
        ).strip()
        if category not in counts:
            category = LEGACY_UNTRACKED
        counts[category] = int(counts.get(category, 0) or 0) + 1
    return {
        key: int(value)
        for key, value in counts.items()
        if int(value) > 0
    }
