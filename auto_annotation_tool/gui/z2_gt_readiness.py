"""Ground-truth readiness helpers for the Z2 -> character-model path."""

from __future__ import annotations

from typing import Any

from ..campaign_manager import CAMPAIGN
from ..plate_ground_truth import normalize_plate_ground_truth_text


def _entry_identity(entry: dict, fallback_index: int) -> str:
    key = str(entry.get("entry_key") or "").strip()
    if key:
        return f"key:{key}"

    image_name = str(entry.get("image_name") or "").strip().lower()
    source_path = str(entry.get("source_image_path") or "").strip().lower()
    if image_name or source_path:
        return f"image:{image_name}|{source_path}"
    return f"fallback:{fallback_index}"


def _plate_entry_ground_truth(plate_entry: dict) -> str:
    if not isinstance(plate_entry, dict):
        return ""

    direct = normalize_plate_ground_truth_text(
        plate_entry.get("ground_truth_text")
    )
    if direct:
        return direct

    attrs = plate_entry.get("attributes")
    if isinstance(attrs, dict):
        return normalize_plate_ground_truth_text(
            attrs.get("ground_truth_text")
        )
    return ""


def summarize_char_gt_entries(
    project_entries,
    run_entries=None,
) -> dict[str, Any]:
    """Summarize GT completeness.

    Entries from ``run_entries`` override project entries with the same
    identity so a correction in the current Z2 run wins over older project
    metadata.
    """
    merged: dict[str, dict] = {}

    for group in (list(project_entries or []), list(run_entries or [])):
        for index, raw_entry in enumerate(group):
            if not isinstance(raw_entry, dict):
                continue
            merged[_entry_identity(raw_entry, index)] = raw_entry

    total_plates = 0
    gt_plates = 0
    missing_images: list[str] = []

    for entry in merged.values():
        image_name = str(entry.get("image_name") or "").strip()
        entry_missing = 0

        for plate_entry in list(entry.get("plates") or []):
            if not isinstance(plate_entry, dict):
                continue
            polygon = list(plate_entry.get("polygon") or [])
            if polygon and len(polygon) < 4:
                continue

            total_plates += 1
            if _plate_entry_ground_truth(plate_entry):
                gt_plates += 1
            else:
                entry_missing += 1

        if entry_missing > 0 and image_name:
            missing_images.append(image_name)

    missing_gt = max(0, int(total_plates) - int(gt_plates))
    return {
        "total_plates": int(total_plates),
        "gt_plates": int(gt_plates),
        "missing_gt": int(missing_gt),
        "ready": bool(total_plates > 0 and missing_gt == 0),
        "missing_images": list(dict.fromkeys(missing_images)),
    }


def build_char_gt_readiness(
    host,
    *,
    run_dir=None,
    force_parse_xml: bool = False,
) -> dict[str, Any]:
    """Build GT readiness for the effective character-source pool."""
    try:
        project_entries = list(
            CAMPAIGN.list_plate_approved_entries() or []
        )
    except Exception:
        project_entries = []

    run_entries = []
    if run_dir is not None:
        builder = getattr(
            host,
            "_build_campaign_plate_approved_entries_from_run",
            None,
        )
        if callable(builder):
            try:
                run_entries = list(
                    builder(
                        run_dir,
                        force_parse_xml=bool(force_parse_xml),
                    )
                    or []
                )
            except TypeError:
                try:
                    run_entries = list(builder(run_dir) or [])
                except Exception:
                    run_entries = []
            except Exception:
                run_entries = []

    return summarize_char_gt_entries(project_entries, run_entries)
