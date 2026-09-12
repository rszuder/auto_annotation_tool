"""Wspólny kontrakt kolejności czterech narożników tablicy."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

CORNER_ORDER_TL_TR_BR_BL = "tl_tr_br_bl"

Point = tuple[float, float]


def parse_quad_points(points_text: str) -> tuple[Point, Point, Point, Point] | None:
    """Parsuj dokładnie cztery skończone punkty ``x,y`` bez zmiany kolejności."""

    raw_points = [
        item.strip()
        for item in str(points_text or "").split(";")
        if item.strip()
    ]
    if len(raw_points) != 4:
        return None

    points: list[Point] = []
    for raw in raw_points:
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 2:
            return None
        try:
            x = float(parts[0])
            y = float(parts[1])
        except Exception:
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        points.append((x, y))

    return (points[0], points[1], points[2], points[3])


def canonicalize_quad_tl_tr_br_bl(
    corners: Sequence[Sequence[float]],
) -> list[Point]:
    """Zwróć kolejność zgodną z runtime MT: TL, TR, BR, BL.

    Algorytm jest celowo taki sam jak dotychczasowy
    ``PlateAnnotator._sort_corners_clockwise``.
    """

    if len(corners) != 4:
        return [
            (float(point[0]), float(point[1]))
            for point in corners
        ]

    points = [
        (float(point[0]), float(point[1]))
        for point in corners
    ]
    cx = sum(point[0] for point in points) / 4.0
    cy = sum(point[1] for point in points) / 4.0

    top = [point for point in points if point[1] < cy]
    bottom = [point for point in points if point[1] >= cy]

    if len(top) != 2 or len(bottom) != 2:
        sorted_by_y = sorted(points, key=lambda point: point[1])
        top = sorted(sorted_by_y[:2], key=lambda point: point[0])
        bottom = sorted(
            sorted_by_y[2:],
            key=lambda point: point[0],
            reverse=True,
        )
    else:
        top = sorted(top, key=lambda point: point[0])
        bottom = sorted(
            bottom,
            key=lambda point: point[0],
            reverse=True,
        )

    return [top[0], top[1], bottom[0], bottom[1]]


def is_canonical_quad_tl_tr_br_bl(
    corners: Sequence[Sequence[float]],
    *,
    tolerance: float = 1e-6,
) -> bool:
    """Sprawdź kolejność bez permutowania punktów wejściowych."""

    if len(corners) != 4:
        return False
    try:
        original = [
            (float(point[0]), float(point[1]))
            for point in corners
        ]
    except Exception:
        return False

    if any(
        not math.isfinite(value)
        for point in original
        for value in point
    ):
        return False

    canonical = canonicalize_quad_tl_tr_br_bl(original)
    eps = max(0.0, float(tolerance))
    return all(
        abs(original[index][0] - canonical[index][0]) <= eps
        and abs(original[index][1] - canonical[index][1]) <= eps
        for index in range(4)
    )


def quad_bbox(
    corners: Sequence[Sequence[float]],
) -> tuple[float, float, float, float]:
    xs = [float(point[0]) for point in corners]
    ys = [float(point[1]) for point in corners]
    return min(xs), min(ys), max(xs), max(ys)


def quad_bbox_diagonal(
    corners: Sequence[Sequence[float]],
) -> float:
    x1, y1, x2, y2 = quad_bbox(corners)
    return math.hypot(x2 - x1, y2 - y1)


def quad_area(
    corners: Sequence[Sequence[float]],
) -> float:
    if len(corners) != 4:
        return 0.0
    points = [
        (float(point[0]), float(point[1]))
        for point in corners
    ]
    total = 0.0
    for index in range(4):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % 4]
        total += x1 * y2 - x2 * y1
    return abs(total) * 0.5


def quad_is_non_degenerate(
    corners: Sequence[Sequence[float]],
    *,
    epsilon: float = 1e-9,
) -> bool:
    try:
        return (
            len(corners) == 4
            and quad_bbox_diagonal(corners) > float(epsilon)
            and quad_area(corners) > float(epsilon)
        )
    except Exception:
        return False
