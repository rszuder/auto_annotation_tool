"""Metrics sliced by reusable PZ3 benchmark labels."""

from __future__ import annotations

from pathlib import Path

from .annotation_comparator import AnnotationComparator
from .corner_metrics import evaluate_pose_corner_metrics
from ..registry.evaluation_benchmark import benchmark_groups

BENCHMARK_GROUP_METRICS_SCHEMA = "alpr.benchmark_group_metrics.v1"


def _f1(precision: float, recall: float) -> float:
    p = float(precision or 0.0)
    r = float(recall or 0.0)
    return (2.0 * p * r / (p + r)) if (p + r) > 0.0 else 0.0


def evaluate_benchmark_group_metrics(
    predicted_xml_path: Path,
    ground_truth_xml_path: Path,
    benchmark: dict,
    *,
    selected_sha256=None,
    require_prediction_pose_marker: bool = True,
) -> dict:
    comparator = AnnotationComparator()
    rows = []
    for group in benchmark_groups(
        benchmark,
        selected_sha256=selected_sha256,
    ):
        image_names = set(group.get("image_names") or [])
        if not image_names:
            continue
        stats = comparator.compare(
            Path(predicted_xml_path),
            Path(ground_truth_xml_path),
            image_names=image_names,
        )
        corner = evaluate_pose_corner_metrics(
            Path(predicted_xml_path),
            Path(ground_truth_xml_path),
            match_iou_threshold=0.5,
            require_prediction_pose_marker=require_prediction_pose_marker,
            allowed_image_names=image_names,
        )
        precision = float(stats.get("precision", 0.0) or 0.0)
        recall = float(stats.get("recall", 0.0) or 0.0)
        row = {
            "group_id": str(group.get("group_id") or ""),
            "label_id": str(group.get("label_id") or ""),
            "label_name": str(group.get("label_name") or ""),
            "sample_count": int(group.get("count") or 0),
            **stats,
            "f1": _f1(precision, recall),
            **corner,
        }
        rows.append(row)

    return {
        "schema": BENCHMARK_GROUP_METRICS_SCHEMA,
        "benchmark_id": str(benchmark.get("benchmark_id") or ""),
        "benchmark_fingerprint": str(benchmark.get("fingerprint") or ""),
        "groups": rows,
        "by_group": {
            str(row["group_id"]): row
            for row in rows
        },
    }
