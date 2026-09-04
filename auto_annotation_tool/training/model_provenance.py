#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Training provenance builder for exported ALPR models.

The desktop application owns the training lineage.  Android stores and reports
this payload, but must not reconstruct parent runs or epoch totals.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..config import CONFIG
from ..utils import safe_load_yaml


PROVENANCE_VERSION = 1
TOTAL_EPOCHS_SCOPE = "project_training_after_pretrained_base"
_RUN_ID_RE = re.compile(r"(20\d{6}_\d{6})")
_IMAGE_SUFFIXES = {str(ext).lower() for ext in getattr(CONFIG, "IMAGE_EXTENSIONS", (".jpg", ".jpeg", ".png", ".bmp", ".webp"))}
_SIDE_CAR_NAMES = (
    "{stem}{suffix}.metadata.json",
    "{stem}.metadata.json",
    "{stem}_metadata.json",
    "model_metadata.json",
    "metadata.json",
)
_DATASET_MANIFEST_NAMES = (
    "training_variant_manifest.json",
    "dataset_manifest.json",
    "augmentation_manifest.json",
    "stage_manifest.json",
    "manifest.json",
)


@dataclass
class _EpochLineageResult:
    total_epochs: int | None
    known_epochs_minimum: int
    total_epochs_known: bool
    provenance_status: str
    lineage: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_model_training_provenance(
    run_like: Any,
    *,
    history_index: Mapping[str, Any] | None = None,
    checkpoint: Path | str | None = None,
    dataset_path: Path | str | None = None,
    target: str = "",
    model_sidecar: Mapping[str, Any] | None = None,
    include_dataset_fingerprint: bool = True,
) -> dict[str, Any]:
    """Return the canonical training/provenance payload for a model manifest."""

    run = _run_like_dict(run_like)
    sidecar = dict(model_sidecar or {}) if isinstance(model_sidecar, Mapping) else {}
    if not run:
        run = _legacy_run_from_sidecar(sidecar)

    resolved_target = _normalize_target(target or _value(run, "parent_model_target") or _infer_target_from_text(
        " ".join(str(_value(run, key, "")) for key in ("dataset_path", "base_model", "name", "output_dir"))
    ))
    resolved_dataset_path = str(dataset_path or _value(run, "dataset_path", "") or "").strip()
    dataset = build_dataset_training_provenance(
        resolved_dataset_path,
        target=resolved_target,
        include_content_fingerprint=include_dataset_fingerprint,
    )

    checkpoint_path = Path(checkpoint) if checkpoint else _path_or_none(_value(run, "best_weights") or _value(run, "last_weights"))
    index = _normalize_history_index(history_index)
    lineage_result = _lineage_total_epochs(
        run,
        history_index=index,
        current_checkpoint=checkpoint_path,
        visited=set(),
    ) if run else _EpochLineageResult(
        total_epochs=None,
        known_epochs_minimum=0,
        total_epochs_known=False,
        provenance_status="legacy_unknown",
        lineage=[],
        warnings=["Brak historii runu treningowego dla modelu."],
    )

    run_epochs_completed = _completed_epoch_count(run)
    run_epochs_planned = _int_or_none(_value(run, "epochs"))
    lineage_mode = _normalize_lineage_mode(_value(run, "lineage_mode", "new"))
    pretrained_origin = _pretrained_origin(run)
    status = lineage_result.provenance_status
    warnings = list(lineage_result.warnings)
    if resolved_dataset_path and not dataset.get("manifest_sha256"):
        status = _weaken_status(status)
        warnings.append("Dataset treningowy nie ma jawnego manifestu generatora.")
    if include_dataset_fingerprint and resolved_dataset_path and not dataset.get("split_sha256"):
        status = _weaken_status(status)
        warnings.append("Nie udało się policzyć fingerprintu splitu datasetu treningowego.")

    parent_run_id = _explicit_parent_run_id(run)
    payload = {
        "provenance_version": PROVENANCE_VERSION,
        "run_id": str(_value(run, "id", "") or ""),
        "run_name": str(_value(run, "name", "") or ""),
        "mode": "fine_tune" if lineage_mode == "fine_tune" else ("legacy_unknown" if not run else "new"),
        "lineage_mode": lineage_mode,
        "run_epochs_planned": run_epochs_planned,
        "run_epochs_completed": run_epochs_completed if run else None,
        "epochs": run_epochs_planned,
        "current_epoch": run_epochs_completed if run else None,
        "total_epochs": lineage_result.total_epochs,
        "total_epochs_known": bool(lineage_result.total_epochs_known),
        "total_epochs_scope": TOTAL_EPOCHS_SCOPE,
        "known_epochs_minimum": int(lineage_result.known_epochs_minimum or 0),
        "pretrained": bool(pretrained_origin),
        "pretrained_origin": pretrained_origin,
        "parent_run_id": parent_run_id,
        "parent_model_path": str(_value(run, "parent_model_path", "") or ""),
        "parent_model_name": str(_value(run, "parent_model_name", "") or ""),
        "lineage_depth": len(lineage_result.lineage),
        "lineage": lineage_result.lineage,
        "dataset": dataset,
        "dataset_id": str(dataset.get("dataset_id") or ""),
        "dataset_path": str(dataset.get("local_path_hint") or resolved_dataset_path),
        "base_model": str(_value(run, "base_model", "") or ""),
        "img_size": _int_or_none(_value(run, "img_size")),
        "batch_size": _int_or_none(_value(run, "batch_size")),
        "started_at": str(_value(run, "started_at", "") or ""),
        "finished_at": str(_value(run, "finished_at", "") or ""),
        "created_at": str(_value(run, "created_at", "") or ""),
        "provenance_status": status,
        "warnings": warnings,
    }
    return _json_safe(payload)


def build_dataset_training_provenance(
    dataset_path: Path | str | None,
    *,
    target: str = "",
    include_content_fingerprint: bool = True,
) -> dict[str, Any]:
    """Describe the training dataset without using local paths as the identity."""

    root = _dataset_root(dataset_path)
    if root is None:
        return {
            "dataset_id": "",
            "name": "",
            "target": _normalize_target(target),
            "provenance_status": "legacy_unknown",
        }
    yaml_path = root / "data.yaml"
    cfg = _safe_yaml(yaml_path)
    resolved_target = _normalize_target(target) or _infer_dataset_target(root, cfg)
    counts = _dataset_split_counts(root, cfg)
    data_yaml_sha = _file_sha256(yaml_path)
    manifests = _dataset_manifest_refs(root)
    manifest_sha = _json_sha256(manifests) if manifests else ""
    split_sha = ""
    split_file_count = 0
    if include_content_fingerprint:
        split_fingerprint = _dataset_split_fingerprint(root, cfg)
        split_sha = str(split_fingerprint.get("sha256") or "")
        split_file_count = int(split_fingerprint.get("file_count", 0) or 0)
    augmentation_meta = _dataset_augmentation_summary(root, manifests)
    identity_seed = manifest_sha or data_yaml_sha or split_sha or str(root.resolve() if root.exists() else root)
    dataset_id = f"DS-{_target_code(resolved_target)}-{identity_seed[:10].upper()}" if identity_seed else ""
    total_images = int(counts.get("train", 0) or 0) + int(counts.get("val", 0) or 0) + int(counts.get("test", 0) or 0)
    return _json_safe(
        {
            "dataset_id": dataset_id,
            "name": root.name,
            "target": resolved_target or "unknown",
            "manifest_sha256": manifest_sha,
            "data_yaml_sha256": data_yaml_sha,
            "split_sha256": split_sha,
            "split_file_count": split_file_count,
            "train_images": int(counts.get("train", 0) or 0),
            "val_images": int(counts.get("val", 0) or 0),
            "test_images": int(counts.get("test", 0) or 0),
            "total_images": total_images,
            "source_images": int(augmentation_meta.get("source_images", 0) or total_images),
            "source_objects": int(augmentation_meta.get("source_objects", 0) or 0),
            "offline_augmentation_train_added": int(augmentation_meta.get("offline_augmentation_train_added", 0) or 0),
            "split_seed": augmentation_meta.get("split_seed"),
            "manifests": manifests,
            "local_path_hint": str(root),
            "data_yaml": str(yaml_path) if yaml_path.exists() else "",
            "provenance_status": "complete" if manifest_sha and split_sha else "partial",
        }
    )


def _lineage_total_epochs(
    run: dict[str, Any],
    *,
    history_index: Mapping[str, dict[str, Any]],
    current_checkpoint: Path | None,
    visited: set[str],
) -> _EpochLineageResult:
    run_id = _run_id(run)
    if run_id and run_id in visited:
        return _EpochLineageResult(
            total_epochs=None,
            known_epochs_minimum=0,
            total_epochs_known=False,
            provenance_status="partial",
            lineage=[],
            warnings=[f"Wykryto cykl rodowodu treningu przy runie {run_id}."],
        )
    if run_id:
        visited.add(run_id)

    completed = _completed_epoch_count(run)
    lineage_mode = _normalize_lineage_mode(_value(run, "lineage_mode", "new"))
    entry = _lineage_entry(run, completed, checkpoint=current_checkpoint)

    if lineage_mode == "fine_tune":
        parent_id = _explicit_parent_run_id(run) or _run_id_from_text(_value(run, "parent_model_path", "")) or _run_id_from_text(_value(run, "parent_model_name", ""))
        parent = dict(history_index.get(parent_id) or {}) if parent_id else {}
        if not parent:
            sidecar_total = _read_parent_sidecar_epochs(run)
            parent_total = int(sidecar_total[1] or 0)
            if sidecar_total[0]:
                return _EpochLineageResult(
                    total_epochs=parent_total + completed,
                    known_epochs_minimum=parent_total + completed,
                    total_epochs_known=True,
                    provenance_status="complete",
                    lineage=[
                        {
                            "run_id": parent_id,
                            "mode": "external_known",
                            "epochs_completed": parent_total,
                            "dataset_id": "",
                            "output_checkpoint_sha256": _file_sha256(_path_or_none(_value(run, "parent_model_path"))),
                        },
                        entry,
                    ],
                )
            if parent_total > 0:
                return _EpochLineageResult(
                    total_epochs=None,
                    known_epochs_minimum=parent_total + completed,
                    total_epochs_known=False,
                    provenance_status="partial",
                    lineage=[
                        {
                            "run_id": parent_id,
                            "mode": "external_partial",
                            "epochs_completed": parent_total,
                            "dataset_id": "",
                            "output_checkpoint_sha256": _file_sha256(_path_or_none(_value(run, "parent_model_path"))),
                        },
                        entry,
                    ],
                    warnings=[f"Rodzic fine-tune ma tylko częściowy rodowód: {parent_id or 'nieznany'}."],
                )
            return _EpochLineageResult(
                total_epochs=None,
                known_epochs_minimum=completed,
                total_epochs_known=False,
                provenance_status="partial",
                lineage=[entry],
                warnings=[f"Brak rodzica fine-tune: {parent_id or 'nieznany'}."],
            )

        parent_result = _lineage_total_epochs(
            parent,
            history_index=history_index,
            current_checkpoint=_path_or_none(_value(parent, "best_weights") or _value(parent, "last_weights")),
            visited=visited,
        )
        known_minimum = int(parent_result.known_epochs_minimum or 0) + completed
        if parent_result.total_epochs_known and parent_result.total_epochs is not None:
            total = int(parent_result.total_epochs) + completed
            known = True
            status = parent_result.provenance_status
        else:
            total = None
            known = False
            status = _weaken_status(parent_result.provenance_status)
        return _EpochLineageResult(
            total_epochs=total,
            known_epochs_minimum=known_minimum,
            total_epochs_known=known,
            provenance_status=status,
            lineage=[*parent_result.lineage, entry],
            warnings=list(parent_result.warnings),
        )

    if _pretrained_origin(run) or not _starts_from_external_or_custom_checkpoint(run):
        return _EpochLineageResult(
            total_epochs=completed,
            known_epochs_minimum=completed,
            total_epochs_known=True,
            provenance_status="complete",
            lineage=[entry],
        )

    sidecar_total = _read_parent_sidecar_epochs(run)
    parent_total = int(sidecar_total[1] or 0)
    if sidecar_total[0]:
        return _EpochLineageResult(
            total_epochs=parent_total + completed,
            known_epochs_minimum=parent_total + completed,
            total_epochs_known=True,
            provenance_status="complete",
            lineage=[entry],
        )
    if parent_total > 0:
        return _EpochLineageResult(
            total_epochs=None,
            known_epochs_minimum=parent_total + completed,
            total_epochs_known=False,
            provenance_status="partial",
            lineage=[entry],
            warnings=["Run startuje z niestandardowego checkpointu o częściowo znanym rodowodzie."],
        )
    return _EpochLineageResult(
        total_epochs=None,
        known_epochs_minimum=completed,
        total_epochs_known=False,
        provenance_status="partial",
        lineage=[entry],
        warnings=["Run startuje z niestandardowego checkpointu bez znanego rodowodu."],
    )


def _lineage_entry(run: Mapping[str, Any], completed: int, *, checkpoint: Path | None) -> dict[str, Any]:
    target = _normalize_target(_value(run, "parent_model_target", "")) or _infer_target_from_text(
        " ".join(str(_value(run, key, "")) for key in ("dataset_path", "base_model", "name", "output_dir"))
    )
    dataset = build_dataset_training_provenance(
        _value(run, "dataset_path", ""),
        target=target,
        include_content_fingerprint=False,
    )
    input_checkpoint = _path_or_none(_value(run, "parent_model_path"))
    output_checkpoint = checkpoint or _path_or_none(_value(run, "best_weights") or _value(run, "last_weights"))
    return _json_safe(
        {
            "run_id": _run_id(run),
            "mode": "fine_tune" if _normalize_lineage_mode(_value(run, "lineage_mode", "new")) == "fine_tune" else "new",
            "epochs_completed": completed,
            "dataset_id": str(dataset.get("dataset_id") or ""),
            "dataset_manifest_sha256": str(dataset.get("manifest_sha256") or ""),
            "input_checkpoint_sha256": _file_sha256(input_checkpoint),
            "output_checkpoint_sha256": _file_sha256(output_checkpoint),
        }
    )


def _completed_epoch_count(run: Mapping[str, Any]) -> int:
    values: list[int] = []
    for key in ("current_epoch", "completed_epochs", "trained_epochs"):
        value = _int_or_none(_value(run, key))
        if value is not None:
            values.append(max(0, value))
    metrics = _value(run, "metrics_history", [])
    if isinstance(metrics, list):
        metric_epochs = [
            max(0, parsed)
            for row in metrics
            if isinstance(row, Mapping)
            for parsed in (_int_or_none(row.get("epoch") or row.get("Epoch")),)
            if parsed is not None
        ]
        if metric_epochs:
            values.append(max(metric_epochs))
    status = str(_value(run, "status", "") or "").strip().lower()
    planned = _int_or_none(_value(run, "epochs"))
    if status in {"completed", "complete", "finished"} and planned is not None:
        values.append(max(0, planned))
    return max(values, default=0)


def _legacy_run_from_sidecar(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    raw = sidecar.get("raw") if isinstance(sidecar.get("raw"), Mapping) else sidecar
    training = raw.get("training") if isinstance(raw, Mapping) and isinstance(raw.get("training"), Mapping) else {}
    run_snapshot = raw.get("run_snapshot") if isinstance(raw, Mapping) and isinstance(raw.get("run_snapshot"), Mapping) else {}
    if run_snapshot:
        return dict(run_snapshot)
    if training:
        payload = dict(training)
        if "run_id" in payload and "id" not in payload:
            payload["id"] = payload.get("run_id")
        if "run_name" in payload and "name" not in payload:
            payload["name"] = payload.get("run_name")
        return payload
    return {}


def _read_parent_sidecar_epochs(run: Mapping[str, Any]) -> tuple[bool, int | None]:
    parent_path = _path_or_none(_value(run, "parent_model_path"))
    if parent_path is None:
        return False, None
    if parent_path.exists() and parent_path.is_file() and parent_path.suffix.lower() == ".alprmodel":
        try:
            with zipfile.ZipFile(parent_path, "r") as archive:
                payload = json.loads(archive.read("manifest.json").decode("utf-8-sig", errors="replace"))
            known, total = _training_payload_total_epochs(payload.get("training") if isinstance(payload, Mapping) else {})
            if known or total:
                return known, total
        except Exception:
            pass
    for sidecar_path in _sidecar_candidates(parent_path):
        if not sidecar_path.exists() or not sidecar_path.is_file():
            continue
        try:
            payload = json.loads(sidecar_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        training = payload.get("training") if isinstance(payload, Mapping) and isinstance(payload.get("training"), Mapping) else {}
        if not training and isinstance(payload.get("raw"), Mapping):
            raw = payload.get("raw") or {}
            training = raw.get("training") if isinstance(raw.get("training"), Mapping) else {}
        known, total = _training_payload_total_epochs(training)
        if known or total:
            return known, total
    return False, None


def _training_payload_total_epochs(training: Any) -> tuple[bool, int | None]:
    if not isinstance(training, Mapping):
        return False, None
    known_raw = training.get("total_epochs_known")
    known = known_raw is True or str(known_raw).strip().lower() in {"1", "true", "tak", "yes"}
    explicitly_unknown = known_raw is False or str(known_raw).strip().lower() in {"0", "false", "nie", "no"}
    total = _int_or_none(training.get("total_epochs"))
    minimum = _int_or_none(training.get("known_epochs_minimum"))
    if known and total is not None:
        return True, total
    if total is not None and total > 0 and not explicitly_unknown:
        return True, total
    if minimum is not None and minimum > 0:
        return False, minimum
    return False, None


def _sidecar_candidates(model_path: Path) -> list[Path]:
    suffix = "".join(model_path.suffixes) if model_path.suffixes else model_path.suffix
    stem_path = model_path.with_suffix("") if model_path.suffix else model_path
    result: list[Path] = []
    for template in _SIDE_CAR_NAMES:
        name = template.format(stem=stem_path.name, suffix=suffix)
        candidate = model_path.parent / name
        if candidate not in result:
            result.append(candidate)
    return result


def _dataset_root(path_value: Path | str | None) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.name.lower() == "data.yaml":
        return path.parent
    return path


def _dataset_split_counts(root: Path, cfg: Mapping[str, Any]) -> dict[str, int]:
    return {
        split: sum(_count_images_in_source(source) for source in _split_sources(root, cfg, split))
        for split in ("train", "val", "test")
    }


def _dataset_split_fingerprint(root: Path, cfg: Mapping[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for split in ("train", "val", "test"):
        for source in _split_sources(root, cfg, split):
            entries.extend(_fingerprint_entries_for_source(root, source, split, image=True))
        for label_dir in _label_dirs_for_split(root, split):
            entries.extend(_fingerprint_entries_for_source(root, label_dir, split, image=False))
    entries.sort(key=lambda item: (str(item.get("split")), str(item.get("relative_path"))))
    return {
        "sha256": _json_sha256(entries),
        "file_count": len(entries),
    }


def _split_sources(root: Path, cfg: Mapping[str, Any], split: str) -> list[Path]:
    raw = str(cfg.get(split) or f"images/{split}").strip() if isinstance(cfg, Mapping) else f"images/{split}"
    candidates = [Path(raw)]
    resolved_root = _yaml_root(root, cfg)
    result: list[Path] = []
    for candidate in candidates:
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        try:
            candidate = candidate.resolve()
        except Exception:
            pass
        if candidate.exists() and candidate not in result:
            result.append(candidate)
    if result:
        return result
    for candidate in (root / "images" / split, root / split / "images"):
        if candidate.exists() and candidate not in result:
            result.append(candidate)
    return result


def _label_dirs_for_split(root: Path, split: str) -> list[Path]:
    result: list[Path] = []
    for candidate in (root / "labels" / split, root / split / "labels"):
        if candidate.exists() and candidate.is_dir() and candidate not in result:
            result.append(candidate)
    return result


def _fingerprint_entries_for_source(root: Path, source: Path, split: str, *, image: bool) -> list[dict[str, Any]]:
    paths: list[Path] = []
    if source.is_file():
        paths.append(source)
        if image and source.suffix.lower() not in _IMAGE_SUFFIXES:
            try:
                for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
                    text = str(line or "").strip()
                    if not text or text.startswith("#"):
                        continue
                    child = Path(text)
                    if not child.is_absolute():
                        child = source.parent / child
                    if child.exists() and child.suffix.lower() in _IMAGE_SUFFIXES:
                        paths.append(child)
            except Exception:
                pass
    elif source.is_dir():
        suffixes = _IMAGE_SUFFIXES if image else {".txt"}
        try:
            paths.extend(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)
        except Exception:
            paths = []
    entries: list[dict[str, Any]] = []
    for path in paths:
        entries.append(
            {
                "split": split,
                "relative_path": _relative_path(root, path),
                "sha256": _file_sha256(path),
                "size": _file_size(path),
            }
        )
    return entries


def _count_images_in_source(source: Path) -> int:
    if source.is_dir():
        try:
            return sum(1 for path in source.iterdir() if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES)
        except Exception:
            return 0
    if source.is_file() and source.suffix.lower() in _IMAGE_SUFFIXES:
        return 1
    if source.is_file():
        count = 0
        try:
            for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
                text = str(line or "").strip()
                if text and not text.startswith("#"):
                    count += 1
        except Exception:
            return 0
        return count
    return 0


def _dataset_manifest_refs(root: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for name in _DATASET_MANIFEST_NAMES:
        path = root / name
        if path.exists() and path.is_file():
            refs.append({"name": name, "sha256": _file_sha256(path), "size": _file_size(path)})
    return refs


def _dataset_augmentation_summary(root: Path, manifests: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
        "source_images": 0,
        "source_objects": 0,
        "offline_augmentation_train_added": 0,
        "split_seed": None,
    }
    for ref in manifests:
        name = str(ref.get("name") or "")
        path = root / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for key in ("source_images", "base_images", "input_images"):
            value = _find_first_int(payload, key)
            if value:
                result["source_images"] = max(int(result["source_images"]), value)
        for key in ("source_objects", "source_plates", "source_labels", "char_count", "plate_count"):
            value = _find_first_int(payload, key)
            if value:
                result["source_objects"] = max(int(result["source_objects"]), value)
        for key in ("offline_augmentation_train_added", "generated_images", "planned_images", "augmentation_train_added"):
            value = _find_first_int(payload, key)
            if value:
                result["offline_augmentation_train_added"] = max(int(result["offline_augmentation_train_added"]), value)
        seed = _find_first_value(payload, "split_seed", "seed", "random_seed")
        if seed not in (None, "") and result["split_seed"] in (None, ""):
            result["split_seed"] = seed
    return result


def _find_first_int(value: Any, key: str) -> int:
    found = _find_first_value(value, key)
    parsed = _int_or_none(found)
    return int(parsed or 0)


def _find_first_value(value: Any, *keys: str) -> Any:
    wanted = {str(key) for key in keys}
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in wanted:
                return child
        for child in value.values():
            nested = _find_first_value(child, *keys)
            if nested not in (None, ""):
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _find_first_value(child, *keys)
            if nested not in (None, ""):
                return nested
    return None


def _safe_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = safe_load_yaml(path)
        return dict(payload or {}) if isinstance(payload, Mapping) else {}
    except Exception:
        return {}


def _yaml_root(root: Path, cfg: Mapping[str, Any]) -> Path:
    raw = str(cfg.get("path") or "").strip() if isinstance(cfg, Mapping) else ""
    if not raw:
        return root
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve()
    except Exception:
        return path


def _infer_dataset_target(root: Path, cfg: Mapping[str, Any]) -> str:
    if isinstance(cfg, Mapping) and cfg.get("kpt_shape"):
        return "plate"
    return _infer_target_from_text(str(root))


def _infer_target_from_text(text: str) -> str:
    lower = str(text or "").lower()
    if "pose" in lower or any(token in lower for token in ("plate", "plates", "tablica", "tablic")):
        return "plate"
    if any(token in lower for token in ("char", "chars", "character", "znak", "znaki")):
        return "char"
    if any(token in lower for token in ("vehicle", "vehicles", "pojazd", "pojazdy", "car", "cars")):
        return "vehicle"
    return ""


def _target_code(target: str) -> str:
    return {"plate": "MT", "char": "MZ", "character": "MZ", "vehicle": "MP"}.get(_normalize_target(target), "XX")


def _normalize_target(target: Any) -> str:
    raw = str(target or "").strip().lower()
    if raw in {"plate", "plates", "tablica", "tablice", "pose", "mt"}:
        return "plate"
    if raw in {"char", "chars", "character", "characters", "znak", "znaki", "mz"}:
        return "char"
    if raw in {"vehicle", "vehicles", "pojazd", "pojazdy", "car", "cars", "mp"}:
        return "vehicle"
    return raw


def _normalize_lineage_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"fine_tune", "finetune", "fine-tune", "continue", "continued"}:
        return "fine_tune"
    if raw in {"resume", "resumed"}:
        return "new"
    return "new"


def _pretrained_origin(run: Mapping[str, Any]) -> str:
    base = str(_value(run, "base_model", "") or "").strip()
    if not base:
        return ""
    name = Path(base).name.lower()
    if re.match(r"^yolo(v?\d+|\d+)[a-z0-9_-]*(?:-pose)?(?:\.pt)?$", name):
        return Path(base).name
    return ""


def _starts_from_external_or_custom_checkpoint(run: Mapping[str, Any]) -> bool:
    base = str(_value(run, "base_model", "") or "").strip()
    parent = str(_value(run, "parent_model_path", "") or "").strip()
    if parent:
        return True
    if not base:
        return False
    return not bool(_pretrained_origin(run))


def _explicit_parent_run_id(run: Mapping[str, Any]) -> str:
    return str(_value(run, "parent_run_id", "") or "").strip()


def _run_id(run: Mapping[str, Any]) -> str:
    explicit = str(_value(run, "id", "") or _value(run, "run_id", "") or "").strip()
    return explicit or _run_id_from_text(_value(run, "output_dir", "") or _value(run, "best_weights", ""))


def _run_id_from_text(text: Any) -> str:
    match = _RUN_ID_RE.search(str(text or ""))
    return str(match.group(1) or "") if match else ""


def _normalize_history_index(history_index: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(history_index, Mapping):
        return result
    for key, value in history_index.items():
        payload = _run_like_dict(value)
        run_id = str(payload.get("id") or key or "").strip()
        if run_id:
            payload.setdefault("id", run_id)
            result[run_id] = payload
    return result


def _run_like_dict(run_like: Any) -> dict[str, Any]:
    if not run_like:
        return {}
    if isinstance(run_like, Mapping):
        return dict(run_like)
    try:
        to_dict = getattr(run_like, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
            if isinstance(payload, Mapping):
                return dict(payload)
    except Exception:
        pass
    result: dict[str, Any] = {}
    for key in (
        "id",
        "name",
        "created_at",
        "status",
        "dataset_path",
        "base_model",
        "epochs",
        "batch_size",
        "img_size",
        "current_epoch",
        "best_map50",
        "best_map50_95",
        "output_dir",
        "best_weights",
        "last_weights",
        "started_at",
        "finished_at",
        "metrics_history",
        "lineage_mode",
        "parent_run_id",
        "parent_model_path",
        "parent_model_name",
        "parent_model_target",
        "parent_dataset_path",
    ):
        try:
            value = getattr(run_like, key)
        except Exception:
            continue
        result[key] = value
    return result


def _value(run: Mapping[str, Any], key: str, default: Any = None) -> Any:
    return run.get(key, default) if isinstance(run, Mapping) else default


def _int_or_none(value: Any) -> int | None:
    try:
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def _path_or_none(value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return Path(raw)
    except Exception:
        return None


def _file_sha256(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        safe_path = Path(path)
        if not safe_path.exists() or not safe_path.is_file():
            return ""
        digest = hashlib.sha256()
        with safe_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return ""


def _file_size(path: Path) -> int:
    try:
        return int(Path(path).stat().st_size)
    except Exception:
        return 0


def _relative_path(root: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except Exception:
        return str(path)


def _json_sha256(value: Any) -> str:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return ""


def _weaken_status(status: str) -> str:
    raw = str(status or "").strip().lower()
    if raw == "legacy_unknown":
        return "legacy_unknown"
    return "partial"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(child) for child in value]
    if isinstance(value, tuple):
        return [_json_safe(child) for child in value]
    if isinstance(value, Path):
        return str(value)
    return value
