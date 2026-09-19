"""Controlled MZ benchmark: sequence-level quality on rectified plate crops."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import math
import xml.etree.ElementTree as ET

from ..campaign_ingest_planner import CHAR_ALPHABET
from ..character_recognition import CharacterDetection
from ..character_recognition.char_detector import CharacterDetector, DetectionMethod
from ..character_recognition.reading_order import sort_records_reading_order
from ..config import cv2
from .mobile_human_review import align_plate_text
from ..registry.evaluation_benchmark import benchmark_groups

CHAR_SEQUENCE_METRICS_SCHEMA = "alpr.mz_sequence_metrics.v1"
CHAR_SEQUENCE_GROUP_METRICS_SCHEMA = "alpr.mz_sequence_group_metrics.v1"
_ALLOWED = set(CHAR_ALPHABET)


def _clean_symbol(value) -> str:
    text = str(value or "").strip().upper()
    return text if len(text) == 1 and text in _ALLOWED else ""


def _shape_text(node: ET.Element) -> str:
    for attr in node.findall("attribute"):
        if str(attr.get("name") or "").strip().lower() == "text":
            return _clean_symbol(attr.text)
    return _clean_symbol(node.get("label"))


def _box_from_node(node: ET.Element):
    if node.tag == "box":
        try:
            values = tuple(float(node.get(key)) for key in ("xtl", "ytl", "xbr", "ybr"))
        except Exception:
            return None
    elif node.tag == "polygon":
        points = []
        try:
            for item in str(node.get("points") or "").split(";"):
                if not item.strip():
                    continue
                x, y = item.split(",", 1)
                points.append((float(x), float(y)))
        except Exception:
            return None
        if len(points) < 4:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        values = (min(xs), min(ys), max(xs), max(ys))
    else:
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    if values[2] <= values[0] or values[3] <= values[1]:
        return None
    return values


def parse_character_ground_truth(xml_path, *, allowed_image_names=None):
    path = Path(xml_path)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"Nie można odczytać GT znaków: {exc}") from exc

    allowed = None
    if allowed_image_names is not None:
        allowed = {
            Path(str(value or "")).name
            for value in allowed_image_names
            if str(value or "").strip()
        }

    result = {}
    duplicates = set()
    invalid = []
    for image in root.findall(".//image"):
        image_name = Path(str(image.get("name") or "")).name
        if not image_name:
            continue
        if allowed is not None and image_name not in allowed:
            continue
        if image_name in result:
            duplicates.add(image_name)
            continue
        detections = []
        for node in [*image.findall("box"), *image.findall("polygon")]:
            label = str(node.get("label") or "").strip().lower()
            if label not in {"character", "char", "char_bbox"} and not _clean_symbol(label):
                continue
            symbol = _shape_text(node)
            bbox = _box_from_node(node)
            if not symbol or bbox is None:
                invalid.append(image_name)
                continue
            detections.append(
                CharacterDetection(
                    character=symbol,
                    bbox=tuple(float(v) for v in bbox),
                    confidence=1.0,
                    method="ground_truth",
                    source_tag="controlled_gt",
                )
            )
        result[image_name] = sort_records_reading_order(detections)

    if duplicates:
        raise ValueError("GT znaków zawiera zduplikowane obrazy: " + ", ".join(sorted(duplicates)[:5]))
    if invalid:
        raise ValueError(
            "GT znaków zawiera niepoprawny symbol lub geometrię boxa: "
            + ", ".join(sorted(set(invalid))[:5])
        )
    return result


def inspect_character_ground_truth(xml_path, *, expected_image_names=None):
    expected = {
        Path(str(value or "")).name
        for value in (expected_image_names or ())
        if str(value or "").strip()
    }
    parsed = parse_character_ground_truth(
        xml_path,
        allowed_image_names=(expected if expected else None),
    )
    names = set(parsed)
    if expected:
        missing = expected - names
        extra = names - expected
        if missing or extra:
            details = []
            if missing:
                details.append("brak: " + ", ".join(sorted(missing)[:5]))
            if extra:
                details.append("nadmiar: " + ", ".join(sorted(extra)[:5]))
            raise ValueError("GT znaków nie odpowiada finalnej próbie (" + "; ".join(details) + ").")

    empty = [name for name, rows in parsed.items() if not rows]
    if empty:
        raise ValueError(
            "Każdy crop benchmarku MZ musi mieć co najmniej jeden znak GT: "
            + ", ".join(sorted(empty)[:5])
        )

    texts = {}
    char_count = 0
    for name, rows in parsed.items():
        text = "".join(_clean_symbol(row.character) for row in rows)
        if not text or len(text) != len(rows):
            raise ValueError(f"Nie można zbudować jednoznacznego tekstu GT dla {name}.")
        texts[name] = text
        char_count += len(text)

    return {
        "char_sequence_ready": bool(parsed),
        "char_sequence_count": len(parsed),
        "char_gt_character_count": char_count,
        "char_gt_texts": texts,
    }


def _prediction_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return "".join(ch for ch in value.upper() if ch in _ALLOWED)
    rows = []
    for item in list(value or []):
        if isinstance(item, CharacterDetection):
            rows.append(item)
        elif isinstance(item, dict):
            symbol = _clean_symbol(item.get("character") or item.get("text"))
            bbox = item.get("bbox")
            if symbol and isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                try:
                    rows.append(
                        CharacterDetection(
                            character=symbol,
                            bbox=tuple(float(v) for v in bbox[:4]),
                            confidence=float(item.get("confidence", 1.0) or 1.0),
                            method=str(item.get("method") or "prediction"),
                        )
                    )
                except Exception:
                    pass
    rows = sort_records_reading_order(rows)
    return "".join(_clean_symbol(row.character) for row in rows)


def _aggregate(rows):
    total = len(rows)
    exact = sum(bool(row["exact_match"]) for row in rows)
    no_read = sum(not row["prediction"] for row in rows)
    correct = sum(row["correct_characters"] for row in rows)
    incorrect = sum(row["incorrect_characters"] for row in rows)
    missing = sum(row["missing_characters"] for row in rows)
    extra = sum(row["extra_characters"] for row in rows)
    edit_distance = sum(row["edit_distance"] for row in rows)
    gt_characters = sum(len(row["ground_truth"]) for row in rows)

    precision_den = correct + incorrect + extra
    recall_den = correct + incorrect + missing
    precision = 100.0 * correct / precision_den if precision_den else 0.0
    recall = 100.0 * correct / recall_den if recall_den else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    exact_pct = 100.0 * exact / total if total else 0.0
    cer = edit_distance / gt_characters if gt_characters else 0.0

    confusion = Counter()
    for row in rows:
        for item in row["alignment"]:
            if item.get("kind") == "incorrect":
                gt = str(item.get("ground_truth") or "")
                pred = str(item.get("prediction") or "")
                if gt and pred:
                    confusion[(gt, pred)] += 1

    return {
        "sequence_metric_schema": CHAR_SEQUENCE_METRICS_SCHEMA,
        "total_images": total,
        "sequence_count": total,
        "exact_match_count": exact,
        "exact_match_pct": exact_pct,
        "cer": cer,
        "no_read_count": no_read,
        "correct_characters": correct,
        "incorrect_characters": incorrect,
        "missing_characters": missing,
        "extra_characters": extra,
        "edit_distance": edit_distance,
        "gt_characters": gt_characters,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": exact_pct,
        "metrics_source": "MZ sequence benchmark",
        "character_confusion": [
            {"ground_truth": gt, "prediction": pred, "count": count}
            for (gt, pred), count in sorted(confusion.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def evaluate_character_predictions(predictions, ground_truth_xml_path, *, allowed_image_names=None):
    gt = parse_character_ground_truth(
        ground_truth_xml_path,
        allowed_image_names=allowed_image_names,
    )
    if allowed_image_names is not None:
        allowed = {Path(str(v or "")).name for v in allowed_image_names if str(v or "").strip()}
        gt = {name: rows for name, rows in gt.items() if name in allowed}

    rows = []
    for image_name in sorted(gt):
        gt_text = "".join(_clean_symbol(item.character) for item in gt[image_name])
        pred_text = _prediction_text(predictions.get(image_name, predictions.get(Path(image_name).stem)))
        aligned = align_plate_text(gt_text, pred_text)
        rows.append(
            {
                "image_name": image_name,
                "ground_truth": aligned.ground_truth,
                "prediction": aligned.prediction,
                "exact_match": bool(aligned.exact_match),
                "correct_characters": int(aligned.correct_characters),
                "incorrect_characters": int(aligned.incorrect_characters),
                "missing_characters": int(aligned.missing_characters),
                "extra_characters": int(aligned.extra_characters),
                "edit_distance": int(aligned.edit_distance),
                "alignment": tuple(aligned.alignment),
            }
        )
    return _aggregate(rows), rows


def _group_metrics(rows, benchmark, *, selected_sha256=None):
    by_name = {row["image_name"]: row for row in rows}
    groups = []
    for group in benchmark_groups(benchmark, selected_sha256=selected_sha256):
        names = {Path(str(v or "")).name for v in group.get("image_names", []) if str(v or "").strip()}
        subset = [row for name, row in by_name.items() if name in names]
        if not subset:
            continue
        stats = _aggregate(subset)
        groups.append(
            {
                "group_id": str(group.get("group_id") or ""),
                "label_id": str(group.get("label_id") or ""),
                "label_name": str(group.get("label_name") or ""),
                "sample_count": len(subset),
                **stats,
            }
        )
    return {
        "schema": CHAR_SEQUENCE_GROUP_METRICS_SCHEMA,
        "benchmark_id": str(benchmark.get("benchmark_id") or ""),
        "benchmark_fingerprint": str(benchmark.get("fingerprint") or ""),
        "groups": groups,
        "by_group": {row["group_id"]: row for row in groups},
    }


def evaluate_character_model_on_benchmark(
    model,
    image_paths,
    ground_truth_xml_path,
    *,
    benchmark=None,
    selected_sha256=None,
    device=None,
    confidence=0.25,
    iou=0.45,
    progress=None,
):
    detector = CharacterDetector(
        method=DetectionMethod.YOLO,
        yolo_model=model,
        yolo_device=device,
        yolo_confidence=float(confidence),
        yolo_box_confidence=float(confidence),
        yolo_symbol_confidence=float(confidence),
        yolo_iou=float(iou),
    )
    paths = [Path(path) for path in image_paths]
    predictions = {}
    for index, path in enumerate(paths, 1):
        image = cv2.imread(str(path)) if cv2 is not None else None
        predictions[path.name] = "" if image is None else detector.detect(image)
        if progress is not None:
            try:
                progress(index, len(paths), path.name)
            except Exception:
                pass

    stats, rows = evaluate_character_predictions(
        predictions,
        ground_truth_xml_path,
        allowed_image_names={path.name for path in paths},
    )
    stats["char_confidence"] = float(confidence)
    stats["char_iou"] = float(iou)
    stats["split_name"] = "benchmark"
    if isinstance(benchmark, dict):
        stats["benchmark_group_metrics"] = _group_metrics(
            rows,
            benchmark,
            selected_sha256=selected_sha256,
        )
    return stats
