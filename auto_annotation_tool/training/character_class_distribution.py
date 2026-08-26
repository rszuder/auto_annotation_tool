#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Character-class balance diagnostics for YOLO MZ datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
import csv
from datetime import datetime
import json
from pathlib import Path
import re
from statistics import median
from typing import Any


CHARACTER_BALANCE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHARACTER_CLASS_DISTRIBUTION_SCHEMA = "alpr.character_class_distribution.v1"
CHARACTER_BALANCE_SPLITS = ("train", "val", "test")

_ANALYSIS_CACHE: dict[tuple[str, str], "CharacterClassDistribution"] = {}
_EXPLICIT_AUG_SUFFIX_RE = re.compile(
    r"(?i)(?:__aug[_-]?\d+|[_-]aug(?:mented)?[_-]?\d*)$"
)


@dataclass(frozen=True)
class CharacterClassDistributionRow:
    class_id: int
    symbol: str
    train_count: int = 0
    val_count: int = 0
    test_count: int = 0
    total_count: int = 0
    train_share: float = 0.0
    unique_train_plate_count: int = 0
    unique_val_plate_count: int = 0
    unique_test_plate_count: int = 0
    unique_total_plate_count: int = 0
    count_status: str = "OK"
    diversity_status: str = "OK"
    status: str = "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": int(self.class_id),
            "symbol": self.symbol,
            "train_count": int(self.train_count),
            "val_count": int(self.val_count),
            "test_count": int(self.test_count),
            "total_count": int(self.total_count),
            "train_share": float(self.train_share),
            "unique_train_plate_count": int(self.unique_train_plate_count),
            "unique_val_plate_count": int(self.unique_val_plate_count),
            "unique_test_plate_count": int(self.unique_test_plate_count),
            "unique_total_plate_count": int(self.unique_total_plate_count),
            "count_status": self.count_status,
            "diversity_status": self.diversity_status,
            "status": self.status,
        }


@dataclass(frozen=True)
class CharacterClassDistribution:
    schema: str
    dataset_root: str
    dataset_yaml: str
    generated_at: str
    alphabet: str
    layout: str
    diagnostic_split: str
    summary: dict[str, Any] = field(default_factory=dict)
    classes: list[CharacterClassDistributionRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "dataset_root": self.dataset_root,
            "dataset_yaml": self.dataset_yaml,
            "generated_at": self.generated_at,
            "alphabet": self.alphabet,
            "layout": self.layout,
            "diagnostic_split": self.diagnostic_split,
            "summary": dict(self.summary),
            "classes": [row.to_dict() for row in self.classes],
        }

    def csv_rows(self) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self.classes]


def analyze_character_class_distribution(dataset_root: Path | str) -> CharacterClassDistribution:
    """Analyze YOLO label files for the fixed MZ alphabet."""

    root, yaml_path = _normalize_dataset_root(dataset_root)
    root_key = _path_key(root)
    split_dirs, layout = _discover_label_dirs(root)
    signature = _build_label_signature(split_dirs, yaml_path)
    cache_key = (root_key, signature)
    cached = _ANALYSIS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    alphabet = CHARACTER_BALANCE_ALPHABET
    class_count = len(alphabet)
    counts = {
        split: [0 for _ in range(class_count)]
        for split in (*CHARACTER_BALANCE_SPLITS, "unsplit")
    }
    unique_sources = {
        split: [set() for _ in range(class_count)]
        for split in (*CHARACTER_BALANCE_SPLITS, "unsplit", "total")
    }
    label_files_by_split = {split: 0 for split in (*CHARACTER_BALANCE_SPLITS, "unsplit")}
    files_read = 0
    empty_label_files = 0
    invalid_label_lines = 0
    invalid_class_ids = 0
    source_map = _load_augmentation_source_map(root)

    for split_name, label_dirs in split_dirs.items():
        for label_dir in label_dirs:
            try:
                label_paths = sorted(
                    path for path in label_dir.iterdir()
                    if path.is_file() and path.suffix.lower() == ".txt"
                )
            except Exception:
                label_paths = []
            label_files_by_split[split_name] = label_files_by_split.get(split_name, 0) + len(label_paths)
            for label_path in label_paths:
                files_read += 1
                source_key = _normalize_source_plate_key(label_path.stem, source_map)
                classes_in_source: set[int] = set()
                file_had_payload = False
                try:
                    lines = label_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    invalid_label_lines += 1
                    continue
                for line in lines:
                    parsed, status = _parse_label_class_id(line, class_count)
                    if status == "skip":
                        continue
                    file_had_payload = True
                    if status == "invalid_line":
                        invalid_label_lines += 1
                        continue
                    if status == "invalid_class":
                        invalid_class_ids += 1
                        continue
                    if parsed is None:
                        continue
                    counts[split_name][parsed] += 1
                    classes_in_source.add(parsed)
                if not file_had_payload:
                    empty_label_files += 1
                for class_id in classes_in_source:
                    unique_sources[split_name][class_id].add(source_key)
                    unique_sources["total"][class_id].add(source_key)

    train_counts = counts["train"]
    val_counts = counts["val"]
    test_counts = counts["test"]
    total_counts = [
        train_counts[index] + val_counts[index] + test_counts[index] + counts["unsplit"][index]
        for index in range(class_count)
    ]
    total_train_labels = sum(train_counts)
    has_train_split = any(split_dirs.get(split) for split in CHARACTER_BALANCE_SPLITS)
    diagnostic_split = "train" if has_train_split and any(split_dirs.get("train")) else "total"
    diagnostic_counts = train_counts if diagnostic_split == "train" else total_counts
    diagnostic_unique_counts = [
        len(unique_sources["train"][index]) if diagnostic_split == "train" else len(unique_sources["total"][index])
        for index in range(class_count)
    ]

    median_nonzero_count = _median_nonzero(diagnostic_counts)
    median_nonzero_unique = _median_nonzero(diagnostic_unique_counts)
    low_count_limit = 0.25 * median_nonzero_count if median_nonzero_count > 0 else 0.0
    low_diversity_limit = 0.25 * median_nonzero_unique if median_nonzero_unique > 0 else 0.0

    rows: list[CharacterClassDistributionRow] = []
    zero_classes: list[str] = []
    low_count_classes: list[str] = []
    low_diversity_classes: list[str] = []

    for class_id, symbol in enumerate(alphabet):
        diagnostic_count = int(diagnostic_counts[class_id])
        diagnostic_unique = int(diagnostic_unique_counts[class_id])
        is_zero = diagnostic_count <= 0
        is_low_count = (
            not is_zero
            and median_nonzero_count > 0
            and diagnostic_count < low_count_limit
        )
        is_low_diversity = (
            not is_zero
            and median_nonzero_unique > 0
            and diagnostic_unique < low_diversity_limit
        )
        if is_zero:
            count_status = "CRITICAL"
            zero_classes.append(symbol)
        elif is_low_count:
            count_status = "LOW"
            low_count_classes.append(symbol)
        else:
            count_status = "OK"

        if is_zero or is_low_diversity:
            diversity_status = "LOW_DIVERSITY"
            if not is_zero:
                low_diversity_classes.append(symbol)
        else:
            diversity_status = "OK"

        if count_status == "CRITICAL":
            status = "CRITICAL"
        elif count_status == "LOW" and diversity_status == "LOW_DIVERSITY":
            status = "LOW+LOW_DIVERSITY"
        elif count_status == "LOW":
            status = "LOW"
        elif diversity_status == "LOW_DIVERSITY":
            status = "LOW_DIVERSITY"
        else:
            status = "OK"

        rows.append(
            CharacterClassDistributionRow(
                class_id=class_id,
                symbol=symbol,
                train_count=int(train_counts[class_id]),
                val_count=int(val_counts[class_id]),
                test_count=int(test_counts[class_id]),
                total_count=int(total_counts[class_id]),
                train_share=(float(train_counts[class_id]) / float(total_train_labels) if total_train_labels > 0 else 0.0),
                unique_train_plate_count=len(unique_sources["train"][class_id]),
                unique_val_plate_count=len(unique_sources["val"][class_id]),
                unique_test_plate_count=len(unique_sources["test"][class_id]),
                unique_total_plate_count=len(unique_sources["total"][class_id]),
                count_status=count_status,
                diversity_status=diversity_status,
                status=status,
            )
        )

    minimum_count = min(diagnostic_counts) if diagnostic_counts else 0
    maximum_count = max(diagnostic_counts) if diagnostic_counts else 0
    minimum_unique = min(diagnostic_unique_counts) if diagnostic_unique_counts else 0
    nonzero_min = min((value for value in diagnostic_counts if value > 0), default=0)
    max_min_ratio = (float(maximum_count) / float(nonzero_min)) if nonzero_min > 0 else None

    summary = {
        "total_labels": int(total_train_labels if diagnostic_split == "train" else sum(total_counts)),
        "total_labels_all_splits": int(sum(total_counts)),
        "minimum_class_count": int(minimum_count),
        "maximum_class_count": int(maximum_count),
        "median_class_count": float(median(diagnostic_counts)) if diagnostic_counts else 0.0,
        "median_nonzero_class_count": float(median_nonzero_count),
        "max_min_ratio": max_min_ratio,
        "zero_classes": zero_classes,
        "low_count_classes": low_count_classes,
        "minimum_unique_plate_count": int(minimum_unique),
        "median_unique_plate_count": float(median(diagnostic_unique_counts)) if diagnostic_unique_counts else 0.0,
        "median_nonzero_unique_plate_count": float(median_nonzero_unique),
        "low_diversity_classes": low_diversity_classes,
        "low_count_threshold": float(low_count_limit),
        "low_diversity_threshold": float(low_diversity_limit),
        "files_read": int(files_read),
        "empty_label_files": int(empty_label_files),
        "invalid_label_lines": int(invalid_label_lines),
        "invalid_class_ids": int(invalid_class_ids),
        "label_files": {
            split: int(label_files_by_split.get(split, 0) or 0)
            for split in (*CHARACTER_BALANCE_SPLITS, "unsplit")
        },
    }

    distribution = CharacterClassDistribution(
        schema=CHARACTER_CLASS_DISTRIBUTION_SCHEMA,
        dataset_root=str(root),
        dataset_yaml=str(yaml_path or ""),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        alphabet=alphabet,
        layout=layout,
        diagnostic_split=diagnostic_split,
        summary=summary,
        classes=rows,
    )
    if len(_ANALYSIS_CACHE) > 12:
        _ANALYSIS_CACHE.clear()
    _ANALYSIS_CACHE[cache_key] = distribution
    return distribution


def save_character_class_distribution_csv(
    distribution: CharacterClassDistribution,
    output_path: Path | str,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "class_id",
        "symbol",
        "train_count",
        "val_count",
        "test_count",
        "total_count",
        "train_share",
        "unique_train_plate_count",
        "unique_val_plate_count",
        "unique_test_plate_count",
        "unique_total_plate_count",
        "count_status",
        "diversity_status",
        "status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in distribution.csv_rows():
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return path


def save_character_class_distribution_json(
    distribution: CharacterClassDistribution,
    output_path: Path | str,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(distribution.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _normalize_dataset_root(dataset_root: Path | str) -> tuple[Path, Path | None]:
    root = Path(dataset_root)
    if root.is_file() and root.name.lower() == "data.yaml":
        return root.parent, root
    yaml_path = root / "data.yaml"
    return root, yaml_path if yaml_path.exists() else None


def _discover_label_dirs(root: Path) -> tuple[dict[str, list[Path]], str]:
    split_dirs: dict[str, list[Path]] = {split: [] for split in CHARACTER_BALANCE_SPLITS}
    split_dirs["unsplit"] = []

    for split_name in CHARACTER_BALANCE_SPLITS:
        for candidate in (root / "labels" / split_name, root / split_name / "labels"):
            if candidate.exists() and candidate.is_dir():
                _append_unique_path(split_dirs[split_name], candidate)

    if any(split_dirs[split] for split in CHARACTER_BALANCE_SPLITS):
        return split_dirs, "split"

    flat_labels = root / "labels"
    if flat_labels.exists() and flat_labels.is_dir():
        split_dirs["unsplit"].append(flat_labels)
        return split_dirs, "flat"

    return split_dirs, "empty"


def _append_unique_path(paths: list[Path], candidate: Path) -> None:
    candidate_key = _path_key(candidate)
    if all(_path_key(existing) != candidate_key for existing in paths):
        paths.append(candidate)


def _build_label_signature(split_dirs: dict[str, list[Path]], yaml_path: Path | None) -> str:
    parts: list[str] = []
    if yaml_path is not None:
        parts.append(_stat_token("yaml", yaml_path))
    for split_name in (*CHARACTER_BALANCE_SPLITS, "unsplit"):
        for label_dir in split_dirs.get(split_name, []):
            parts.append(_stat_token(split_name, label_dir))
            try:
                label_paths = [
                    path for path in label_dir.iterdir()
                    if path.is_file() and path.suffix.lower() == ".txt"
                ]
            except Exception:
                label_paths = []
            max_mtime = 0
            total_size = 0
            for path in label_paths:
                try:
                    stat = path.stat()
                except Exception:
                    continue
                max_mtime = max(max_mtime, int(stat.st_mtime_ns))
                total_size += int(stat.st_size or 0)
            parts.append(f"{_path_key(label_dir)}:{len(label_paths)}:{max_mtime}:{total_size}")
    return "|".join(parts)


def _stat_token(label: str, path: Path) -> str:
    try:
        stat = path.stat()
        return f"{label}:{_path_key(path)}:{int(stat.st_mtime_ns)}:{int(stat.st_size or 0)}"
    except Exception:
        return f"{label}:{_path_key(path)}:missing"


def _load_augmentation_source_map(root: Path) -> dict[str, str]:
    manifest_path = root / "augmentation_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    generated_files = payload.get("generated_files")
    if not isinstance(generated_files, list):
        return {}

    mapping: dict[str, str] = {}
    for item in generated_files:
        if not isinstance(item, dict):
            continue
        source = item.get("source_label") or item.get("source_image")
        generated = item.get("label") or item.get("image")
        if not source or not generated:
            continue
        source_stem = Path(str(source)).stem
        generated_stem = Path(str(generated)).stem
        if source_stem and generated_stem:
            mapping[generated_stem] = source_stem
    return mapping


def _normalize_source_plate_key(stem: str, source_map: dict[str, str]) -> str:
    current = str(stem or "").strip()
    seen: set[str] = set()
    while current in source_map and current not in seen:
        seen.add(current)
        current = str(source_map.get(current) or current).strip()
    while True:
        stripped = _EXPLICIT_AUG_SUFFIX_RE.sub("", current)
        if stripped == current:
            break
        current = stripped
    return current or str(stem or "")


def _parse_label_class_id(line: str, class_count: int) -> tuple[int | None, str]:
    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return None, "skip"
    parts = text.split()
    if not parts:
        return None, "skip"
    try:
        raw_value = float(parts[0])
    except Exception:
        return None, "invalid_line"
    class_id = int(raw_value)
    if raw_value != float(class_id):
        return None, "invalid_line"
    if class_id < 0 or class_id >= class_count:
        return None, "invalid_class"
    return class_id, "ok"


def _median_nonzero(values: list[int]) -> float:
    nonzero = [int(value) for value in values if int(value or 0) > 0]
    return float(median(nonzero)) if nonzero else 0.0


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)
