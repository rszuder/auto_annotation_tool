"""Utilities for ordering character boxes in human reading order.

The old flow sorted every character only by X coordinate. That is correct for
long one-row plates, but it breaks square/two-row plates where the top and
bottom rows share similar X ranges.
"""

from __future__ import annotations

from statistics import median
from typing import Any, Iterable, List, Sequence, Tuple


BBox = Tuple[float, float, float, float]


def record_bbox(record: Any) -> BBox | None:
    if isinstance(record, dict):
        raw_bbox = record.get("bbox")
    else:
        raw_bbox = getattr(record, "bbox", None)

    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4:
        return None

    try:
        x1, y1, x2, y2 = (float(value) for value in raw_bbox[:4])
    except Exception:
        return None

    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def _center_x(bbox: BBox) -> float:
    return (float(bbox[0]) + float(bbox[2])) / 2.0


def _center_y(bbox: BBox) -> float:
    return (float(bbox[1]) + float(bbox[3])) / 2.0


def _height(bbox: BBox) -> float:
    return max(1.0, float(bbox[3]) - float(bbox[1]))


def group_records_into_reading_rows(
    records: Iterable[Any],
    *,
    y_tolerance_ratio: float = 0.68,
    min_y_tolerance: float = 6.0,
) -> List[List[Any]]:
    indexed = []
    unpositioned = []

    for original_index, record in enumerate(list(records or [])):
        bbox = record_bbox(record)
        if bbox is None:
            unpositioned.append((original_index, record))
            continue
        indexed.append(
            {
                "index": int(original_index),
                "record": record,
                "bbox": bbox,
                "cx": _center_x(bbox),
                "cy": _center_y(bbox),
                "height": _height(bbox),
            }
        )

    if not indexed:
        return [[record for _index, record in unpositioned]] if unpositioned else []

    heights = [float(item["height"]) for item in indexed]
    median_height = max(1.0, float(median(heights)))
    y_tolerance = max(float(min_y_tolerance), median_height * float(y_tolerance_ratio))

    min_center_y = min(float(item["cy"]) for item in indexed)
    max_center_y = max(float(item["cy"]) for item in indexed)
    if max_center_y - min_center_y <= y_tolerance:
        row = sorted(indexed, key=lambda item: (float(item["cx"]), int(item["index"])))
        rows = [[item["record"] for item in row]]
    else:
        row_buckets: list[dict[str, Any]] = []
        for item in sorted(indexed, key=lambda value: (float(value["cy"]), float(value["cx"]), int(value["index"]))):
            best_bucket = None
            best_distance = None
            for bucket in row_buckets:
                distance = abs(float(item["cy"]) - float(bucket["center_y"]))
                bucket_tolerance = max(y_tolerance, float(bucket["median_height"]) * float(y_tolerance_ratio))
                if distance > bucket_tolerance:
                    continue
                if best_distance is None or distance < best_distance:
                    best_bucket = bucket
                    best_distance = distance

            if best_bucket is None:
                row_buckets.append(
                    {
                        "items": [item],
                        "center_y": float(item["cy"]),
                        "median_height": float(item["height"]),
                    }
                )
                continue

            best_bucket["items"].append(item)
            best_bucket["center_y"] = float(median([float(row_item["cy"]) for row_item in best_bucket["items"]]))
            best_bucket["median_height"] = float(median([float(row_item["height"]) for row_item in best_bucket["items"]]))

        rows = []
        for bucket in sorted(row_buckets, key=lambda value: float(value["center_y"])):
            ordered = sorted(bucket["items"], key=lambda item: (float(item["cx"]), int(item["index"])))
            rows.append([item["record"] for item in ordered])

    if unpositioned:
        if not rows:
            rows.append([])
        rows[-1].extend(record for _index, record in sorted(unpositioned, key=lambda item: item[0]))

    return rows


def sort_records_single_row(records: Sequence[Any] | Iterable[Any]) -> List[Any]:
    positioned = []
    unpositioned = []
    for original_index, record in enumerate(list(records or [])):
        bbox = record_bbox(record)
        if bbox is None:
            unpositioned.append((original_index, record))
            continue
        positioned.append((float(_center_x(bbox)), int(original_index), record))

    ordered = [record for _cx, _index, record in sorted(positioned, key=lambda item: (item[0], item[1]))]
    ordered.extend(record for _index, record in sorted(unpositioned, key=lambda item: item[0]))
    return ordered


def rows_for_reading_order(
    records: Sequence[Any] | Iterable[Any],
    *,
    forced_layout: str | None = None,
) -> List[List[Any]]:
    if str(forced_layout or "").strip().lower() == "single_row":
        row = sort_records_single_row(records)
        return [row] if row else []
    return group_records_into_reading_rows(records)


def sort_records_reading_order(
    records: Sequence[Any] | Iterable[Any],
    *,
    forced_layout: str | None = None,
) -> List[Any]:
    rows = rows_for_reading_order(records, forced_layout=forced_layout)
    ordered: list[Any] = []
    for row in rows:
        ordered.extend(row)
    return ordered


def annotate_records_reading_order(
    records: Sequence[Any] | Iterable[Any],
    *,
    forced_layout: str | None = None,
) -> List[Any]:
    rows = rows_for_reading_order(records, forced_layout=forced_layout)
    annotated: list[Any] = []
    reading_index = 1

    for row_index, row in enumerate(rows, start=1):
        for col_index, record in enumerate(row, start=1):
            if isinstance(record, dict):
                prepared = dict(record)
                prepared["reading_row"] = int(row_index)
                prepared["reading_col"] = int(col_index)
                prepared["reading_index"] = int(reading_index)
                annotated.append(prepared)
            else:
                try:
                    setattr(record, "reading_row", int(row_index))
                    setattr(record, "reading_col", int(col_index))
                    setattr(record, "reading_index", int(reading_index))
                except Exception:
                    pass
                annotated.append(record)
            reading_index += 1

    return annotated


def infer_plate_layout_from_records(
    records: Sequence[Any] | Iterable[Any],
    *,
    square_hint: bool | None = None,
) -> dict[str, Any]:
    rows = [row for row in group_records_into_reading_rows(records) if row]
    row_count = len(rows)

    if row_count >= 2:
        return {
            "plate_layout": "two_row",
            "layout_row_count": int(row_count),
            "layout_confidence": 0.9,
            "layout_source": "boxes",
        }

    if row_count == 1:
        if square_hint:
            return {
                "plate_layout": "two_row_candidate",
                "layout_row_count": 1,
                "layout_confidence": 0.45,
                "layout_source": "square_hint",
            }
        return {
            "plate_layout": "single_row",
            "layout_row_count": 1,
            "layout_confidence": 0.8,
            "layout_source": "boxes",
        }

    if square_hint:
        return {
            "plate_layout": "two_row_candidate",
            "layout_row_count": 0,
            "layout_confidence": 0.35,
            "layout_source": "square_hint",
        }

    return {
        "plate_layout": "unknown",
        "layout_row_count": 0,
        "layout_confidence": 0.0,
        "layout_source": "none",
    }
