"""Przygotowanie rekordów datasetu do zapisu w rejestrze SQLite."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from .dataset_inventory import (
    LINEAGE_EXACT_HASH_ONLY,
    LINEAGE_KNOWN,
    LINEAGE_LEGACY_PARTIAL,
    DatasetImageLineage,
    build_dataset_image_lineage,
)


_STATUS_PRIORITY = {
    LINEAGE_KNOWN: 0,
    LINEAGE_EXACT_HASH_ONLY: 1,
    LINEAGE_LEGACY_PARTIAL: 2,
}


@dataclass(frozen=True)
class DatasetRegistryRows:
    """Rekordy gotowe do zapisania w tabelach rejestru.

    Pola odpowiadają bezpośrednio tabelom:
    ``source_images``, ``image_artifacts`` i ``dataset_members``.
    """

    dataset_id: str
    source_images: tuple[dict[str, Any], ...]
    image_artifacts: tuple[dict[str, Any], ...]
    dataset_members: tuple[dict[str, Any], ...]
    lineage_status_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source_images": [dict(row) for row in self.source_images],
            "image_artifacts": [dict(row) for row in self.image_artifacts],
            "dataset_members": [dict(row) for row in self.dataset_members],
            "lineage_status_counts": dict(self.lineage_status_counts),
        }


def build_dataset_registry_rows(
    dataset_id: str,
    dataset_path: Path | str | None,
) -> DatasetRegistryRows:
    """Zbuduj relacyjne rekordy obrazów datasetu bez zapisywania ich do SQLite."""

    dataset_id_text = str(dataset_id or "").strip()
    if not dataset_id_text:
        raise ValueError("dataset_id nie może być pusty.")

    lineage = build_dataset_image_lineage(dataset_path)
    artifact_ids = {
        row.relative_path: _artifact_id(
            dataset_id_text,
            row.relative_path,
            row.artifact_sha256,
        )
        for row in lineage
    }

    source_rows: dict[str, dict[str, Any]] = {}
    artifacts: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}

    for row in lineage:
        status_counts[row.lineage_status] = (
            int(status_counts.get(row.lineage_status, 0) or 0) + 1
        )

        existing_source = source_rows.get(row.source_image_id)
        candidate_status = row.lineage_status
        if existing_source is None:
            source_rows[row.source_image_id] = {
                "source_image_id": row.source_image_id,
                "canonical_sha256": row.source_sha256 or None,
                "origin_status": candidate_status,
                "created_at": None,
            }
        else:
            existing_status = str(existing_source.get("origin_status") or "")
            if _status_priority(candidate_status) > _status_priority(existing_status):
                existing_source["origin_status"] = candidate_status
            if not existing_source.get("canonical_sha256") and row.source_sha256:
                existing_source["canonical_sha256"] = row.source_sha256

        artifact_id = artifact_ids[row.relative_path]
        derived_from_artifact_id = artifact_ids.get(row.parent_reference)

        artifacts.append(
            {
                "artifact_id": artifact_id,
                "source_image_id": row.source_image_id,
                "relative_path": row.relative_path,
                "external_path": None,
                "sha256": row.artifact_sha256,
                "size_bytes": int(row.artifact_size),
                "kind": "derived_image" if row.is_derived else "dataset_image",
                "derived_from_artifact_id": derived_from_artifact_id,
                "width": None,
                "height": None,
                "created_at": None,
            }
        )

        members.append(
            {
                "dataset_id": dataset_id_text,
                "artifact_id": artifact_id,
                "source_image_id": row.source_image_id,
                "split": row.split,
                "relative_path": row.relative_path,
                "file_sha256": row.artifact_sha256,
            }
        )

    ordered_sources = tuple(
        source_rows[key]
        for key in sorted(source_rows)
    )
    ordered_artifacts = tuple(
        sorted(
            artifacts,
            key=lambda item: (
                str(item.get("relative_path") or ""),
                str(item.get("artifact_id") or ""),
            ),
        )
    )
    ordered_members = tuple(
        sorted(
            members,
            key=lambda item: (
                str(item.get("split") or ""),
                str(item.get("relative_path") or ""),
                str(item.get("artifact_id") or ""),
            ),
        )
    )

    return DatasetRegistryRows(
        dataset_id=dataset_id_text,
        source_images=ordered_sources,
        image_artifacts=ordered_artifacts,
        dataset_members=ordered_members,
        lineage_status_counts=dict(sorted(status_counts.items())),
    )


def _artifact_id(dataset_id: str, relative_path: str, sha256: str) -> str:
    """Identyfikator fizycznego artefaktu w kontekście konkretnego datasetu."""

    seed = (
        f"{dataset_id}|{relative_path}|{sha256}"
        .encode("utf-8", errors="replace")
    )
    digest = hashlib.sha256(seed).hexdigest().upper()
    return f"ART-{digest}"


def _status_priority(status: str) -> int:
    return int(_STATUS_PRIORITY.get(str(status or ""), 99))
