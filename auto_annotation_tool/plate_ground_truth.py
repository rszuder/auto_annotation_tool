"""Ground-truth contract for plate annotations.

Ground truth belongs to a concrete plate annotation (polygon), not to the
source image filename. The module deliberately contains no Z2/Z3 UI logic.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any
from uuid import uuid4

from .registration_text import normalize_registration


PLATE_ANNOTATION_ID_ATTR = "plate_annotation_id"
GROUND_TRUTH_TEXT_ATTR = "ground_truth_text"
GROUND_TRUTH_SOURCE_ATTR = "ground_truth_source"

GROUND_TRUTH_SOURCE_MANUAL_Z2 = "manual_z2"


def normalize_plate_ground_truth_text(value: Any) -> str:
    """Return canonical registration text stored as plate ground truth."""
    return normalize_registration(value)


def ensure_plate_annotation_id(
    attributes: MutableMapping[str, Any],
    *,
    id_factory=None,
) -> str:
    """Ensure that one plate polygon has a stable annotation identifier."""
    existing = str(attributes.get(PLATE_ANNOTATION_ID_ATTR) or "").strip()
    if existing:
        return existing

    factory = id_factory or (lambda: uuid4().hex)
    raw_id = str(factory() or "").strip()
    if not raw_id:
        raw_id = uuid4().hex
    annotation_id = f"plate-ann-{raw_id}"
    attributes[PLATE_ANNOTATION_ID_ATTR] = annotation_id
    return annotation_id


def get_plate_ground_truth(attributes: MutableMapping[str, Any] | None) -> str:
    if not isinstance(attributes, MutableMapping):
        return ""
    return normalize_plate_ground_truth_text(
        attributes.get(GROUND_TRUTH_TEXT_ATTR)
    )


def set_plate_ground_truth(
    attributes: MutableMapping[str, Any],
    text: Any,
    *,
    source: str = GROUND_TRUTH_SOURCE_MANUAL_Z2,
) -> str:
    """Assign or clear GT on one concrete plate annotation."""
    ensure_plate_annotation_id(attributes)
    normalized = normalize_plate_ground_truth_text(text)
    if not normalized:
        attributes.pop(GROUND_TRUTH_TEXT_ATTR, None)
        attributes.pop(GROUND_TRUTH_SOURCE_ATTR, None)
        return ""

    attributes[GROUND_TRUTH_TEXT_ATTR] = normalized
    attributes[GROUND_TRUTH_SOURCE_ATTR] = str(
        source or GROUND_TRUTH_SOURCE_MANUAL_Z2
    ).strip()
    return normalized


def ensure_plate_detection_contract(detection) -> dict[str, Any]:
    """Ensure identity and normalize already-present GT on a Detection."""
    attributes = dict(getattr(detection, "attributes", {}) or {})
    ensure_plate_annotation_id(attributes)

    if GROUND_TRUTH_TEXT_ATTR in attributes:
        normalized = normalize_plate_ground_truth_text(
            attributes.get(GROUND_TRUTH_TEXT_ATTR)
        )
        if normalized:
            attributes[GROUND_TRUTH_TEXT_ATTR] = normalized
        else:
            attributes.pop(GROUND_TRUTH_TEXT_ATTR, None)
            attributes.pop(GROUND_TRUTH_SOURCE_ATTR, None)

    detection.attributes = attributes
    return attributes
