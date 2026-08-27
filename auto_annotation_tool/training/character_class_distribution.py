#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Character-class balance diagnostics for YOLO MZ datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
import csv
from datetime import datetime
import json
from math import ceil
from pathlib import Path
import re
from statistics import median
from typing import Any, Mapping

from ..utils import safe_load_yaml


CHARACTER_BALANCE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHARACTER_CLASS_DISTRIBUTION_SCHEMA = "alpr.character_class_distribution.v1"
CHARACTER_BALANCE_PLAN_SCHEMA = "alpr.character_balance_plan.v1"
CHARACTER_TRAINING_VARIANT_SCHEMA = "alpr.mz_training_variant.v1"
CHARACTER_BALANCE_SPLITS = ("train", "val", "test")
CHARACTER_BALANCE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

_ANALYSIS_CACHE: dict[tuple[str, str, str], "CharacterClassDistribution"] = {}
_EXPLICIT_AUG_SUFFIX_RE = re.compile(
    r"(?i)(?:__aug[_-]?\d+|[_-]aug(?:mented)?[_-]?\d*)$"
)


@dataclass(frozen=True)
class CharacterClassMapValidation:
    ok: bool
    status: str
    expected: tuple[str, ...]
    detected: tuple[str, ...] = field(default_factory=tuple)
    first_mismatch_index: int | None = None
    message: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "status": self.status,
            "expected": list(self.expected),
            "detected": list(self.detected),
            "first_mismatch_index": self.first_mismatch_index,
            "message": self.message,
            "warnings": list(self.warnings),
        }


class CharacterClassMapValidationError(ValueError):
    """Raised when data.yaml cannot be safely interpreted as the MZ alphabet."""

    def __init__(self, validation: CharacterClassMapValidation):
        self.validation = validation
        super().__init__(validation.message or "Mapa klas datasetu nie jest zgodna ze standardem MZ.")


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
    target_count: int = 0
    deficit_count: int = 0

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
            "target_count": int(self.target_count),
            "deficit_count": int(self.deficit_count),
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


@dataclass(frozen=True)
class CharacterBalanceAugmentationCandidate:
    source_key: str
    label_path: str
    image_path: str = ""
    symbols: tuple[str, ...] = field(default_factory=tuple)
    priority: float = 0.0
    max_augmented_variants: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "label_path": self.label_path,
            "image_path": self.image_path,
            "symbols": list(self.symbols),
            "priority": float(self.priority),
            "max_augmented_variants": int(self.max_augmented_variants),
        }


@dataclass(frozen=True)
class CharacterBalancePlan:
    schema: str
    created_at: str
    base_dataset: str
    alphabet: str
    target_ratio: float
    target_count: int
    max_augmented_variants_per_source: int
    selection_policy: str = "deficit_weighted"
    deficit_by_symbol: dict[str, int] = field(default_factory=dict)
    candidates: tuple[CharacterBalanceAugmentationCandidate, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "created_at": self.created_at,
            "base_dataset": self.base_dataset,
            "alphabet": self.alphabet,
            "target_ratio": float(self.target_ratio),
            "target_count": int(self.target_count),
            "selection_policy": self.selection_policy,
            "max_augmented_variants_per_source": int(self.max_augmented_variants_per_source),
            "deficit_by_symbol": dict(self.deficit_by_symbol),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "warnings": list(self.warnings),
        }


def analyze_character_class_distribution(
    dataset_root: Path | str,
    *,
    target_ratio: float = 0.50,
) -> CharacterClassDistribution:
    """Analyze YOLO label files for the fixed MZ alphabet."""

    root, yaml_path = _normalize_dataset_root(dataset_root)
    target_ratio = _normalize_balance_target_ratio(target_ratio)
    root_key = _path_key(root)
    split_dirs, layout = _discover_label_dirs(root)
    class_map_validation = _validate_character_class_map(yaml_path, layout)
    signature = _build_label_signature(split_dirs, yaml_path)
    cache_key = (root_key, signature, f"target={target_ratio:.6f}")
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
    target_count = (
        int(ceil(float(target_ratio) * float(median_nonzero_count)))
        if median_nonzero_count > 0 and target_ratio > 0
        else 0
    )

    rows: list[CharacterClassDistributionRow] = []
    zero_classes: list[str] = []
    low_count_classes: list[str] = []
    low_diversity_classes: list[str] = []
    deficit_classes: list[str] = []
    total_deficit_count = 0

    for class_id, symbol in enumerate(alphabet):
        diagnostic_count = int(diagnostic_counts[class_id])
        diagnostic_unique = int(diagnostic_unique_counts[class_id])
        deficit_count = max(0, int(target_count) - diagnostic_count)
        if deficit_count > 0:
            deficit_classes.append(symbol)
            total_deficit_count += deficit_count
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
                target_count=target_count,
                deficit_count=deficit_count,
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
        "balance_target_ratio": float(target_ratio),
        "target_class_count": int(target_count),
        "total_deficit_count": int(total_deficit_count),
        "deficit_classes": deficit_classes,
        "deficit_policy": "max(0, target_count - diagnostic_count)",
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
        "class_map": class_map_validation.to_dict(),
        "warnings": list(class_map_validation.warnings),
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


def plan_character_train_augmentation(
    dataset_root: Path | str,
    *,
    target_ratio: float = 0.50,
    max_augmented_variants_per_source: int = 3,
) -> CharacterBalancePlan:
    """Build a train-only augmentation plan weighted by class deficits.

    The function is deliberately non-destructive: it does not create images and
    never touches val/test. It only exposes the source priority that the dataset
    builder can use before creating a training variant.
    """

    root, _yaml_path = _normalize_dataset_root(dataset_root)
    distribution = analyze_character_class_distribution(root, target_ratio=target_ratio)
    target_ratio = float(distribution.summary.get("balance_target_ratio", target_ratio) or 0.50)
    target_count = int(distribution.summary.get("target_class_count", 0) or 0)
    max_per_source = max(0, int(max_augmented_variants_per_source or 0))
    deficit_by_symbol = {
        row.symbol: int(row.deficit_count)
        for row in distribution.classes
        if int(row.deficit_count) > 0
    }

    split_dirs, layout = _discover_label_dirs(root)
    warnings: list[str] = []
    if layout != "split" or not split_dirs.get("train"):
        warnings.append("Brak jawnego splitu train; plan augmentacji train-only nie wybiera źródeł.")

    candidates: list[CharacterBalanceAugmentationCandidate] = []
    source_map = _load_augmentation_source_map(root)
    for label_dir in split_dirs.get("train", []):
        for label_path in _iter_label_files(label_dir):
            source_key = _normalize_source_plate_key(label_path.stem, source_map)
            symbols = _symbols_from_label_file(label_path)
            priority = sum(float(deficit_by_symbol.get(symbol, 0)) for symbol in symbols)
            if priority <= 0:
                continue
            image_path = _resolve_image_for_label(root, label_path)
            candidates.append(
                CharacterBalanceAugmentationCandidate(
                    source_key=source_key,
                    label_path=str(label_path),
                    image_path=str(image_path or ""),
                    symbols=symbols,
                    priority=round(priority, 4),
                    max_augmented_variants=max_per_source,
                )
            )

    candidates.sort(key=lambda item: (-item.priority, item.source_key))
    return CharacterBalancePlan(
        schema=CHARACTER_BALANCE_PLAN_SCHEMA,
        created_at=datetime.now().isoformat(timespec="seconds"),
        base_dataset=str(root),
        alphabet=CHARACTER_BALANCE_ALPHABET,
        target_ratio=target_ratio,
        target_count=target_count,
        max_augmented_variants_per_source=max_per_source,
        deficit_by_symbol=deficit_by_symbol,
        candidates=tuple(candidates),
        warnings=tuple(warnings),
    )


def build_character_training_variant_manifest(
    *,
    base_dataset: Path | str,
    before_distribution: CharacterClassDistribution | Path | str,
    after_distribution: CharacterClassDistribution | Path | str | None = None,
    plan: CharacterBalancePlan | None = None,
    sources: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Create the research manifest skeleton for an MZ training variant."""

    max_per_source = int(getattr(plan, "max_augmented_variants_per_source", 0) or 0)
    source_counts = {
        "real": 0,
        "augmented_real": 0,
        "synthetic": 0,
        "augmented_synthetic": 0,
    }
    if sources:
        for key in source_counts:
            source_counts[key] = max(0, int(sources.get(key, 0) or 0))
    return {
        "schema": CHARACTER_TRAINING_VARIANT_SCHEMA,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "base_dataset": str(base_dataset),
        "alphabet": CHARACTER_BALANCE_ALPHABET,
        "target_count": int(getattr(plan, "target_count", 0) or 0),
        "target_ratio": float(getattr(plan, "target_ratio", 0.50) or 0.50),
        "selection_policy": str(getattr(plan, "selection_policy", "deficit_weighted") or "deficit_weighted"),
        "sources": source_counts,
        "before_distribution": _distribution_ref(before_distribution),
        "after_distribution": _distribution_ref(after_distribution) if after_distribution is not None else "",
        "augmentation": {
            "max_variants_per_source": max_per_source,
        },
        "balance_plan": plan.to_dict() if plan is not None else {},
    }


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
        "target_count",
        "deficit_count",
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


def _normalize_balance_target_ratio(value: Any) -> float:
    try:
        ratio = float(str(value).strip().replace(",", "."))
    except Exception:
        ratio = 0.50
    if ratio > 1.0:
        ratio /= 100.0
    return max(0.0, min(2.0, ratio))


def _iter_label_files(label_dir: Path) -> list[Path]:
    try:
        return sorted(
            path for path in Path(label_dir).iterdir()
            if path.is_file() and path.suffix.lower() == ".txt"
        )
    except Exception:
        return []


def _symbols_from_label_file(label_path: Path) -> tuple[str, ...]:
    class_count = len(CHARACTER_BALANCE_ALPHABET)
    class_ids: set[int] = set()
    try:
        lines = Path(label_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        lines = []
    for line in lines:
        class_id, status = _parse_label_class_id(line, class_count)
        if status != "ok" or class_id is None:
            continue
        class_ids.add(int(class_id))
    return tuple(CHARACTER_BALANCE_ALPHABET[index] for index in sorted(class_ids))


def _resolve_image_for_label(root: Path, label_path: Path) -> Path | None:
    label_path = Path(label_path)
    root = Path(root)
    relative: Path | None = None
    try:
        relative = label_path.relative_to(root)
    except Exception:
        relative = None

    candidates: list[Path] = []
    if relative is not None:
        parts = list(relative.parts)
        if len(parts) >= 3 and parts[0] == "labels":
            candidates.append(root / "images" / parts[1] / label_path.name)
        if len(parts) >= 3 and parts[1] == "labels":
            candidates.append(root / parts[0] / "images" / label_path.name)
    parent_parts = list(label_path.parent.parts)
    if "labels" in parent_parts:
        index = parent_parts.index("labels")
        image_parent = Path(*parent_parts[:index], "images", *parent_parts[index + 1 :])
        candidates.append(image_parent / label_path.name)

    for candidate in candidates:
        for suffix in CHARACTER_BALANCE_IMAGE_EXTENSIONS:
            image_path = candidate.with_suffix(suffix)
            if image_path.exists():
                return image_path
    return None


def _distribution_ref(value: CharacterClassDistribution | Path | str) -> str:
    if isinstance(value, CharacterClassDistribution):
        return str(value.dataset_root or value.dataset_yaml or "")
    return str(value or "")


def _validate_character_class_map(yaml_path: Path | None, layout: str) -> CharacterClassMapValidation:
    expected = tuple(CHARACTER_BALANCE_ALPHABET)
    if yaml_path is None or not yaml_path.exists():
        if layout == "flat":
            return CharacterClassMapValidation(
                ok=True,
                status="WARNING",
                expected=expected,
                message="Brak mapy klas; interpretacja oparta na standardowym alfabecie MZ.",
                warnings=("Brak mapy klas; interpretacja oparta na standardowym alfabecie MZ.",),
            )
        validation = CharacterClassMapValidation(
            ok=False,
            status="ERROR",
            expected=expected,
            message=(
                "Brak data.yaml. Splitowany dataset MZ musi mieć jawną mapę klas, "
                "żeby symbolika 0-9/A-Z była jednoznaczna."
            ),
        )
        raise CharacterClassMapValidationError(validation)

    payload = safe_load_yaml(yaml_path)
    detected = _extract_yaml_class_names(payload)
    if not detected:
        detected = _extract_yaml_class_names_from_text(yaml_path)
    first_mismatch = _first_class_map_mismatch(expected, detected)
    if first_mismatch is None:
        return CharacterClassMapValidation(
            ok=True,
            status="OK",
            expected=expected,
            detected=detected,
            message="Mapa klas data.yaml jest zgodna ze standardem MZ.",
        )

    validation = CharacterClassMapValidation(
        ok=False,
        status="ERROR",
        expected=expected,
        detected=detected,
        first_mismatch_index=first_mismatch,
        message=_format_class_map_error(expected, detected, first_mismatch),
    )
    raise CharacterClassMapValidationError(validation)


def _extract_yaml_class_names(payload: dict[str, Any]) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return tuple()
    names = payload.get("names")
    if isinstance(names, dict):
        items: list[tuple[int, str]] = []
        for raw_key, raw_value in names.items():
            try:
                key = int(str(raw_key).strip())
            except Exception:
                return tuple(str(value).strip() for value in names.values())
            items.append((key, str(raw_value).strip()))
        return tuple(value for _key, value in sorted(items, key=lambda item: item[0]))
    if isinstance(names, (list, tuple)):
        return tuple(str(value).strip() for value in names)
    return tuple()


def _extract_yaml_class_names_from_text(yaml_path: Path) -> tuple[str, ...]:
    try:
        lines = yaml_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return tuple()
    names_started = False
    list_values: list[str] = []
    dict_values: dict[int, str] = {}
    base_indent: int | None = None
    for raw_line in lines:
        line_without_comment = str(raw_line or "").split("#", 1)[0].rstrip()
        stripped = line_without_comment.strip()
        if not stripped:
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        if not names_started:
            if re.match(r"^names\s*:\s*$", stripped):
                names_started = True
                base_indent = indent
                continue
            inline_match = re.match(r"^names\s*:\s*\[(.*)\]\s*$", stripped)
            if inline_match:
                return tuple(_clean_yaml_scalar(item) for item in inline_match.group(1).split(",") if item.strip())
            continue
        if base_indent is not None and indent <= base_indent:
            break
        if stripped.startswith("-"):
            value = stripped[1:].strip()
            list_values.append(_clean_yaml_scalar(value))
            continue
        mapping = re.match(r"^([0-9]+)\s*:\s*(.+?)\s*$", stripped)
        if mapping:
            dict_values[int(mapping.group(1))] = _clean_yaml_scalar(mapping.group(2))
    if dict_values:
        return tuple(value for _index, value in sorted(dict_values.items(), key=lambda item: item[0]))
    return tuple(list_values)


def _clean_yaml_scalar(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _first_class_map_mismatch(expected: tuple[str, ...], detected: tuple[str, ...]) -> int | None:
    limit = max(len(expected), len(detected))
    for index in range(limit):
        expected_value = expected[index] if index < len(expected) else None
        detected_value = detected[index] if index < len(detected) else None
        if expected_value != detected_value:
            return index
    return None


def _format_class_map_error(
    expected: tuple[str, ...],
    detected: tuple[str, ...],
    first_mismatch_index: int,
) -> str:
    expected_value = expected[first_mismatch_index] if first_mismatch_index < len(expected) else "<brak>"
    detected_value = detected[first_mismatch_index] if first_mismatch_index < len(detected) else "<brak>"
    return (
        "Mapa klas datasetu nie jest zgodna ze standardem MZ.\n"
        f"Pierwsza niezgodność: indeks {first_mismatch_index}, "
        f"oczekiwano '{expected_value}', wykryto '{detected_value}'.\n"
        f"Oczekiwana mapa: {''.join(expected)}\n"
        f"Wykryta mapa: {' '.join(detected) if detected else '<brak names>'}"
    )


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
