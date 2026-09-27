from __future__ import annotations

import math

CORNER_HANDLE_ORDER = ("nw", "ne", "sw", "se")


def get_corner_handle_centers(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
) -> dict[str, tuple[float, float]]:
    r = max(0.0, float(radius))
    offset = r / math.sqrt(2.0)
    return {
        "nw": (float(x1) - offset, float(y1) - offset),
        "ne": (float(x2) + offset, float(y1) - offset),
        "sw": (float(x1) - offset, float(y2) + offset),
        "se": (float(x2) + offset, float(y2) + offset),
    }


def get_box_corner_point(
    handle_name: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> tuple[float, float]:
    name = str(handle_name or "").strip().lower()
    if name == "nw":
        return float(x1), float(y1)
    if name == "ne":
        return float(x2), float(y1)
    if name == "sw":
        return float(x1), float(y2)
    if name == "se":
        return float(x2), float(y2)
    raise ValueError(f"Nieznany narożnik uchwytu: {handle_name!r}")
