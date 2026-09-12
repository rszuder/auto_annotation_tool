"""Metryka lokalizacji narożników dla kontrolowanego eksperymentu MT."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from ..config import CONFIG
from ..pose_corners import (
    CORNER_ORDER_TL_TR_BR_BL,
    parse_quad_points,
    quad_bbox,
    quad_bbox_diagonal,
    quad_is_non_degenerate,
)
from ..utils import calculate_iou

CORNER_METRIC_SCHEMA = "alpr.mt_corner_error.v1"
CORNER_NORMALIZER = "gt_polygon_bbox_diagonal"
CORNER_MATCHING = "greedy_bbox_iou"
DEFAULT_CORNER_MATCH_IOU = 0.5


@dataclass(frozen=True)
class _PlatePolygon:
    image_name: str
    points: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]
    bbox: tuple[float, float, float, float]
    attributes: dict[str, str]


def corner_metric_protocol_descriptor(
    *,
    match_iou_threshold: float = DEFAULT_CORNER_MATCH_IOU,
) -> dict:
    return {
        "schema": CORNER_METRIC_SCHEMA,
        "formula": (
            "E_corner=(1/4)*sum_i(||pred_i-gt_i||_2/d_GT), i=0..3"
        ),
        "corner_order": (
            CORNER_ORDER_TL_TR_BR_BL + "_fixed_no_permutation"
        ),
        "normalizer": CORNER_NORMALIZER,
        "matching": CORNER_MATCHING,
        "matching_iou_threshold": float(match_iou_threshold),
        "aggregates": ["mean", "p50", "p90", "p95", "max"],
    }


def evaluate_pose_corner_metrics(
    predicted_xml_path: Path,
    ground_truth_xml_path: Path,
    *,
    match_iou_threshold: float = DEFAULT_CORNER_MATCH_IOU,
    require_prediction_pose_marker: bool = False,
) -> dict:
    """Policz błąd narożników na dopasowanych tablicach.

    Punkty nie są permutowane. Punkt ``i`` predykcji jest zawsze porównywany
    z punktem ``i`` GT. ``d_GT`` to przekątna obwiedni polygonu GT.
    """

    threshold = float(match_iou_threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("match_iou_threshold musi należeć do [0, 1].")

    predicted, predicted_invalid = _parse_cvat_plate_polygons(
        Path(predicted_xml_path)
    )
    ground_truth, gt_invalid = _parse_cvat_plate_polygons(
        Path(ground_truth_xml_path)
    )

    image_names = sorted(set(predicted) | set(ground_truth))
    values: list[float] = []
    matched_pairs = 0
    skipped_pairs = 0
    missing_pose_pairs = 0
    degenerate_gt_pairs = 0

    for image_name in image_names:
        pred_shapes = predicted.get(image_name, [])
        gt_shapes = ground_truth.get(image_name, [])
        matched_gt: set[int] = set()

        for pred in pred_shapes:
            best_index = None
            best_iou = 0.0
            for gt_index, gt in enumerate(gt_shapes):
                if gt_index in matched_gt:
                    continue
                iou = float(calculate_iou(pred.bbox, gt.bbox))
                if iou > best_iou:
                    best_iou = iou
                    best_index = gt_index

            if best_index is None or best_iou < threshold:
                continue

            matched_gt.add(best_index)
            matched_pairs += 1
            gt = gt_shapes[best_index]

            if require_prediction_pose_marker:
                corner_source = str(
                    pred.attributes.get("corner_source") or ""
                ).strip().lower()
                corner_order = str(
                    pred.attributes.get("corner_order") or ""
                ).strip().lower()
                if (
                    corner_source != "pose"
                    or corner_order != CORNER_ORDER_TL_TR_BR_BL
                ):
                    missing_pose_pairs += 1
                    skipped_pairs += 1
                    continue

            diagonal = quad_bbox_diagonal(gt.points)
            if (
                not quad_is_non_degenerate(gt.points)
                or diagonal <= 1e-12
            ):
                degenerate_gt_pairs += 1
                skipped_pairs += 1
                continue

            normalized_errors = [
                math.hypot(
                    pred.points[index][0] - gt.points[index][0],
                    pred.points[index][1] - gt.points[index][1],
                )
                / diagonal
                for index in range(4)
            ]
            values.append(sum(normalized_errors) / 4.0)

    status = "OK" if values else "NO_VALID_CORNERS"
    return {
        "corner_metric_schema": CORNER_METRIC_SCHEMA,
        "corner_metric_status": status,
        "corner_order": CORNER_ORDER_TL_TR_BR_BL,
        "corner_normalizer": CORNER_NORMALIZER,
        "corner_matching": CORNER_MATCHING,
        "corner_match_iou_threshold": threshold,
        "corner_error_count": len(values),
        "corner_error_mean": (
            sum(values) / len(values)
            if values
            else 0.0
        ),
        "corner_error_p50": _percentile(values, 0.50),
        "corner_error_p90": _percentile(values, 0.90),
        "corner_error_p95": _percentile(values, 0.95),
        "corner_error_max": max(values) if values else 0.0,
        "corner_matched_pairs": matched_pairs,
        "corner_skipped_pairs": skipped_pairs,
        "corner_missing_pose_pairs": missing_pose_pairs,
        "corner_degenerate_gt_pairs": degenerate_gt_pairs,
        "corner_invalid_prediction_shapes": predicted_invalid,
        "corner_invalid_gt_shapes": gt_invalid,
    }


def _parse_cvat_plate_polygons(
    xml_path: Path,
) -> tuple[dict[str, list[_PlatePolygon]], int]:
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(
            f"Nie można odczytać CVAT XML {xml_path}: {exc}"
        ) from exc

    data: dict[str, list[_PlatePolygon]] = {}
    invalid = 0

    for image in root.findall(".//image"):
        image_name = Path(
            str(image.get("name") or "")
        ).name
        data.setdefault(image_name, [])

        for polygon in image.findall("polygon"):
            label = str(
                polygon.get("label") or ""
            ).strip().lower()
            if label not in CONFIG.PLATE_LABELS and label != "plate":
                continue

            points = parse_quad_points(
                str(polygon.get("points") or "")
            )
            if points is None:
                invalid += 1
                continue

            attributes: dict[str, str] = {}
            for attr in polygon.findall("attribute"):
                name = str(attr.get("name") or "").strip()
                if name:
                    attributes[name] = str(
                        attr.text or ""
                    ).strip()

            data[image_name].append(
                _PlatePolygon(
                    image_name=image_name,
                    points=points,
                    bbox=quad_bbox(points),
                    attributes=attributes,
                )
            )

    return data, invalid


def _percentile(
    values: list[float],
    quantile: float,
) -> float:
    if not values:
        return 0.0
    q = min(1.0, max(0.0, float(quantile)))
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return (
        ordered[low] * (1.0 - weight)
        + ordered[high] * weight
    )
