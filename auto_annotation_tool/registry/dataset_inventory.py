"""Budowanie rodowodu obrazów datasetu na potrzeby rejestru eksperymentów.

Moduł nie zmienia fingerprintu datasetu. Korzysta z publicznego inwentarza
pliku treningowego i, gdy jest dostępny, z ``augmentation_manifest.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..training.model_provenance import (
    DatasetFileInventoryEntry,
    build_dataset_file_inventory,
)


LINEAGE_KNOWN = "known"
LINEAGE_EXACT_HASH_ONLY = "exact_hash_only"
LINEAGE_LEGACY_PARTIAL = "legacy_partial"


@dataclass(frozen=True)
class DatasetImageLineage:
    """Rodowód pojedynczego obrazu należącego do datasetu."""

    split: str
    relative_path: str
    artifact_sha256: str
    artifact_size: int
    source_image_id: str
    source_sha256: str
    source_reference: str
    lineage_status: str
    derivation_kind: str
    parent_reference: str = ""
    lineage_depth: int = 0

    @property
    def is_derived(self) -> bool:
        return self.lineage_depth > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "relative_path": self.relative_path,
            "artifact_sha256": self.artifact_sha256,
            "artifact_size": int(self.artifact_size),
            "source_image_id": self.source_image_id,
            "source_sha256": self.source_sha256,
            "source_reference": self.source_reference,
            "lineage_status": self.lineage_status,
            "derivation_kind": self.derivation_kind,
            "parent_reference": self.parent_reference,
            "lineage_depth": int(self.lineage_depth),
            "is_derived": self.is_derived,
        }


def source_image_id_from_sha256(sha256: str) -> str:
    """Zbuduj stabilny identyfikator logicznego obrazu źródłowego."""

    value = str(sha256 or "").strip().lower()
    if not value:
        return ""
    return f"SRC-SHA256-{value.upper()}"


def build_dataset_image_lineage(
    dataset_path: Path | str | None,
) -> list[DatasetImageLineage]:
    """Zwróć rodowód wszystkich fizycznych obrazów datasetu.

    Dla obrazów bez jawnych danych o pochodzeniu tożsamość jest oparta na
    dokładnym SHA-256 i otrzymuje status ``exact_hash_only``. Jeżeli manifest
    augmentacji wskazuje obraz źródłowy, wszystkie jego pochodne dziedziczą
    ``source_image_id`` korzenia łańcucha i otrzymują status ``known``.

    Brakujący albo cykliczny rodowód jest oznaczany jako ``legacy_partial``;
    taki wpis nie powinien później umożliwiać wyniku niezależności PASS.
    """

    root = _dataset_root(dataset_path)
    if root is None:
        return []

    inventory = [
        entry
        for entry in build_dataset_file_inventory(root)
        if entry.role == "image"
    ]
    image_index = {
        _reference_key(entry.relative_path): entry
        for entry in inventory
    }
    stem_index = _build_stem_index(inventory)
    parent_map = _load_augmentation_parent_map(
        root,
        image_index=image_index,
        stem_index=stem_index,
    )

    result = [
        _resolve_image_lineage(
            root,
            entry,
            image_index=image_index,
            parent_map=parent_map,
        )
        for entry in inventory
    ]
    result.sort(key=lambda item: (item.split, item.relative_path))
    return result


def _resolve_image_lineage(
    root: Path,
    entry: DatasetFileInventoryEntry,
    *,
    image_index: Mapping[str, DatasetFileInventoryEntry],
    parent_map: Mapping[str, str],
) -> DatasetImageLineage:
    current_reference = entry.relative_path
    direct_parent = ""
    visited: set[str] = set()
    depth = 0
    cycle = False

    while True:
        current_key = _reference_key(current_reference)
        if current_key in visited:
            cycle = True
            break
        visited.add(current_key)

        parent = str(parent_map.get(current_key) or "").strip()
        if not parent:
            break
        if depth == 0:
            direct_parent = parent
        current_reference = parent
        depth += 1

    if cycle:
        unresolved_id = _unresolved_source_id(root, current_reference, "cycle")
        return DatasetImageLineage(
            split=entry.split,
            relative_path=entry.relative_path,
            artifact_sha256=entry.sha256,
            artifact_size=entry.size,
            source_image_id=unresolved_id,
            source_sha256="",
            source_reference=current_reference,
            lineage_status=LINEAGE_LEGACY_PARTIAL,
            derivation_kind="augmentation_manifest",
            parent_reference=direct_parent,
            lineage_depth=depth,
        )

    source_entry = image_index.get(_reference_key(current_reference))
    if source_entry is not None and source_entry.sha256:
        source_sha = source_entry.sha256
        source_reference = source_entry.relative_path
    else:
        source_path = _reference_to_path(root, current_reference)
        source_sha = _file_sha256(source_path)
        source_reference = current_reference

    if source_sha:
        status = LINEAGE_KNOWN if depth > 0 else LINEAGE_EXACT_HASH_ONLY
        source_id = source_image_id_from_sha256(source_sha)
    else:
        status = LINEAGE_LEGACY_PARTIAL
        source_id = _unresolved_source_id(root, current_reference, "missing")

    return DatasetImageLineage(
        split=entry.split,
        relative_path=entry.relative_path,
        artifact_sha256=entry.sha256,
        artifact_size=entry.size,
        source_image_id=source_id,
        source_sha256=source_sha,
        source_reference=source_reference,
        lineage_status=status,
        derivation_kind="augmentation_manifest" if depth > 0 else "identity",
        parent_reference=direct_parent,
        lineage_depth=depth,
    )


def _load_augmentation_parent_map(
    root: Path,
    *,
    image_index: Mapping[str, DatasetFileInventoryEntry],
    stem_index: Mapping[tuple[str, str], tuple[str, ...]],
) -> dict[str, str]:
    manifest_path = root / "augmentation_manifest.json"
    if not manifest_path.exists() or not manifest_path.is_file():
        return {}

    try:
        payload = json.loads(
            manifest_path.read_text(encoding="utf-8-sig", errors="ignore")
        )
    except Exception:
        return {}

    generated_files = payload.get("generated_files") if isinstance(payload, Mapping) else None
    if not isinstance(generated_files, list):
        return {}

    result: dict[str, str] = {}
    for item in generated_files:
        if not isinstance(item, Mapping):
            continue

        generated = _resolve_manifest_image_reference(
            root,
            image_value=item.get("image"),
            label_value=item.get("label"),
            image_index=image_index,
            stem_index=stem_index,
            allow_missing=False,
        )
        source = _resolve_manifest_image_reference(
            root,
            image_value=item.get("source_image"),
            label_value=item.get("source_label"),
            image_index=image_index,
            stem_index=stem_index,
            allow_missing=True,
        )
        if not generated or not source:
            continue
        result[_reference_key(generated)] = source

    return result


def _resolve_manifest_image_reference(
    root: Path,
    *,
    image_value: Any,
    label_value: Any,
    image_index: Mapping[str, DatasetFileInventoryEntry],
    stem_index: Mapping[tuple[str, str], tuple[str, ...]],
    allow_missing: bool,
) -> str:
    raw_image = str(image_value or "").strip()
    if raw_image:
        normalized = _normalize_reference(root, raw_image)
        exact = image_index.get(_reference_key(normalized))
        if exact is not None:
            return exact.relative_path
        path = _reference_to_path(root, normalized)
        if path is not None and path.exists() and path.is_file():
            return normalized
        if allow_missing:
            return normalized

    raw_label = str(label_value or "").strip()
    if not raw_label:
        return ""

    normalized_label = _normalize_reference(root, raw_label)
    split = _split_from_reference(normalized_label)
    stem = Path(normalized_label).stem.casefold()
    candidates = stem_index.get((split, stem), ())
    if len(candidates) == 1:
        return candidates[0]

    # Legacy manifests sometimes omit the split in source_label.
    all_candidates: list[str] = []
    for (_candidate_split, candidate_stem), values in stem_index.items():
        if candidate_stem != stem:
            continue
        all_candidates.extend(values)
    unique = sorted(set(all_candidates))
    if len(unique) == 1:
        return unique[0]

    if allow_missing:
        return normalized_label
    return ""


def _build_stem_index(
    inventory: list[DatasetFileInventoryEntry],
) -> dict[tuple[str, str], tuple[str, ...]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for entry in inventory:
        key = (str(entry.split), Path(entry.relative_path).stem.casefold())
        grouped.setdefault(key, []).append(entry.relative_path)
    return {
        key: tuple(sorted(set(values)))
        for key, values in grouped.items()
    }


def _split_from_reference(reference: str) -> str:
    parts = [part.casefold() for part in Path(reference).parts]
    for split in ("train", "val", "test"):
        if split in parts:
            return split
    return ""


def _dataset_root(path_value: Path | str | None) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.name.lower() == "data.yaml":
        return path.parent
    return path


def _normalize_reference(root: Path, raw_value: str) -> str:
    raw = str(raw_value or "").strip().replace("\\", "/")
    if not raw:
        return ""

    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except Exception:
            try:
                return str(candidate.resolve())
            except Exception:
                return str(candidate)

    while raw.startswith("./"):
        raw = raw[2:]
    return Path(raw).as_posix()


def _reference_key(reference: str) -> str:
    return str(reference or "").replace("\\", "/").strip().lstrip("./").casefold()


def _reference_to_path(root: Path, reference: str) -> Path | None:
    raw = str(reference or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve()
    except Exception:
        return path


def _file_sha256(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except Exception:
        return ""
    return digest.hexdigest()


def _unresolved_source_id(root: Path, reference: str, reason: str) -> str:
    try:
        root_key = str(root.resolve())
    except Exception:
        root_key = str(root)
    seed = f"{root_key}|{reference}|{reason}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(seed).hexdigest().upper()
    return f"SRC-UNRESOLVED-{digest}"
