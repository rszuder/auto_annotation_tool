"""Warstwa dostępu do relacyjnego rejestru Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from .database import RegistryDatabase
from .registry_rows import DatasetRegistryRows


_STATUS_RANK = {
    "known": 0,
    "complete": 0,
    "exact_hash_only": 1,
    "partial": 2,
    "legacy_partial": 3,
    "legacy_unknown": 4,
}


@dataclass(frozen=True)
class DatasetBundleWriteSummary:
    dataset_id: str
    source_rows: int
    artifact_rows: int
    member_rows: int


class RegistryRepository:
    """Jedyny moduł warstwy domenowej wykonujący SQL rejestru."""

    def __init__(self, database: RegistryDatabase) -> None:
        self.database = database

    @classmethod
    def for_workspace(cls, workspace_dir: Path | str) -> "RegistryRepository":
        workspace = Path(workspace_dir)
        return cls(
            RegistryDatabase(
                workspace / "_registry" / "alpr_registry.sqlite3"
            )
        )

    def initialize(self) -> int:
        return self.database.initialize()

    def upsert_project(
        self,
        *,
        project_id: str,
        campaign_key: str,
        folder_name: str,
        display_name: str,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        self.initialize()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    project_id,
                    campaign_key,
                    folder_name,
                    display_name,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    campaign_key = excluded.campaign_key,
                    folder_name = excluded.folder_name,
                    display_name = excluded.display_name,
                    created_at = COALESCE(projects.created_at, excluded.created_at),
                    updated_at = COALESCE(excluded.updated_at, projects.updated_at)
                """,
                (
                    project_id,
                    campaign_key,
                    folder_name,
                    display_name,
                    created_at,
                    updated_at,
                ),
            )

    def upsert_dataset_bundle(
        self,
        *,
        provenance: Mapping[str, Any],
        rows: DatasetRegistryRows,
        project_id: str | None,
        location_key: str,
        relative_path: str | None,
        external_path: str | None = None,
        is_primary: bool = False,
        discovered_at: str | None = None,
    ) -> DatasetBundleWriteSummary:
        self.initialize()
        dataset_id = str(provenance.get("dataset_id") or "").strip()
        if not dataset_id:
            raise ValueError("Dataset bez dataset_id nie może trafić do rejestru.")
        if dataset_id != rows.dataset_id:
            raise ValueError(
                "dataset_id provenance i rekordów datasetu nie są zgodne."
            )

        with self.database.transaction() as connection:
            self._upsert_dataset_row(
                connection,
                provenance=provenance,
                project_id=project_id,
                relative_path=relative_path,
                discovered_at=discovered_at,
            )
            self._upsert_dataset_location(
                connection,
                dataset_id=dataset_id,
                project_id=project_id,
                location_key=location_key,
                relative_path=relative_path,
                external_path=external_path,
                is_primary=is_primary,
                discovered_at=discovered_at,
            )

            for source_row in rows.source_images:
                self._upsert_source_image(connection, source_row)

            # Dwa przebiegi są celowe: najpierw wszystkie artefakty bez relacji
            # rodzic-dziecko, potem FK derived_from_artifact_id.
            for artifact_row in rows.image_artifacts:
                self._upsert_artifact_base(connection, artifact_row)
            for artifact_row in rows.image_artifacts:
                derived_from = artifact_row.get("derived_from_artifact_id")
                if derived_from:
                    connection.execute(
                        """
                        UPDATE image_artifacts
                        SET derived_from_artifact_id = ?
                        WHERE artifact_id = ?
                        """,
                        (
                            derived_from,
                            artifact_row["artifact_id"],
                        ),
                    )

            for member_row in rows.dataset_members:
                connection.execute(
                    """
                    INSERT INTO dataset_members (
                        dataset_id,
                        artifact_id,
                        source_image_id,
                        split,
                        relative_path,
                        file_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dataset_id, artifact_id, split) DO UPDATE SET
                        source_image_id = excluded.source_image_id,
                        relative_path = excluded.relative_path,
                        file_sha256 = excluded.file_sha256
                    """,
                    (
                        member_row["dataset_id"],
                        member_row["artifact_id"],
                        member_row["source_image_id"],
                        member_row["split"],
                        member_row.get("relative_path"),
                        member_row.get("file_sha256"),
                    ),
                )

        return DatasetBundleWriteSummary(
            dataset_id=dataset_id,
            source_rows=len(rows.source_images),
            artifact_rows=len(rows.image_artifacts),
            member_rows=len(rows.dataset_members),
        )

    def table_count(self, table_name: str) -> int:
        allowed = {
            "projects",
            "datasets",
            "dataset_locations",
            "source_images",
            "image_artifacts",
            "dataset_members",
            "training_runs",
            "models",
            "model_locations",
        }
        if table_name not in allowed:
            raise ValueError(f"Niedozwolona tabela: {table_name}")
        self.initialize()
        with self.database.read_connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()
        return int(row[0] if row else 0)

    def fetch_rows(
        self,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> list[sqlite3.Row]:
        """Pomocniczy odczyt dla diagnostyki/testów; zapis pozostaje w repozytorium."""

        self.initialize()
        with self.database.read_connection() as connection:
            return list(connection.execute(query, params).fetchall())

    def _upsert_dataset_row(
        self,
        connection: sqlite3.Connection,
        *,
        provenance: Mapping[str, Any],
        project_id: str | None,
        relative_path: str | None,
        discovered_at: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO datasets (
                dataset_id,
                owner_project_id,
                target,
                name,
                purpose,
                relative_path,
                manifest_sha256,
                split_sha256,
                provenance_status,
                created_at,
                registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                owner_project_id = COALESCE(
                    datasets.owner_project_id,
                    excluded.owner_project_id
                ),
                target = CASE
                    WHEN excluded.target <> '' THEN excluded.target
                    ELSE datasets.target
                END,
                name = CASE
                    WHEN excluded.name <> '' THEN excluded.name
                    ELSE datasets.name
                END,
                relative_path = COALESCE(
                    datasets.relative_path,
                    excluded.relative_path
                ),
                manifest_sha256 = CASE
                    WHEN excluded.manifest_sha256 <> ''
                        THEN excluded.manifest_sha256
                    ELSE datasets.manifest_sha256
                END,
                split_sha256 = CASE
                    WHEN excluded.split_sha256 <> ''
                        THEN excluded.split_sha256
                    ELSE datasets.split_sha256
                END,
                provenance_status = CASE
                    WHEN datasets.provenance_status IN ('legacy_unknown', 'legacy_partial')
                        THEN datasets.provenance_status
                    ELSE excluded.provenance_status
                END,
                registered_at = COALESCE(
                    datasets.registered_at,
                    excluded.registered_at
                )
            """,
            (
                str(provenance.get("dataset_id") or ""),
                project_id,
                str(provenance.get("target") or ""),
                str(provenance.get("name") or ""),
                "training",
                relative_path,
                str(provenance.get("manifest_sha256") or ""),
                str(provenance.get("split_sha256") or ""),
                str(provenance.get("provenance_status") or "legacy_partial"),
                None,
                discovered_at,
            ),
        )

    def _upsert_dataset_location(
        self,
        connection: sqlite3.Connection,
        *,
        dataset_id: str,
        project_id: str | None,
        location_key: str,
        relative_path: str | None,
        external_path: str | None,
        is_primary: bool,
        discovered_at: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO dataset_locations (
                dataset_id,
                location_key,
                project_id,
                relative_path,
                external_path,
                is_primary,
                discovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id, location_key) DO UPDATE SET
                project_id = excluded.project_id,
                relative_path = excluded.relative_path,
                external_path = excluded.external_path,
                is_primary = excluded.is_primary,
                discovered_at = COALESCE(
                    dataset_locations.discovered_at,
                    excluded.discovered_at
                )
            """,
            (
                dataset_id,
                location_key,
                project_id,
                relative_path,
                external_path,
                1 if is_primary else 0,
                discovered_at,
            ),
        )

    def _upsert_source_image(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
    ) -> None:
        source_id = str(row.get("source_image_id") or "").strip()
        if not source_id:
            raise ValueError("source_image_id nie może być pusty.")

        existing = connection.execute(
            """
            SELECT canonical_sha256, origin_status
            FROM source_images
            WHERE source_image_id = ?
            """,
            (source_id,),
        ).fetchone()

        canonical = str(row.get("canonical_sha256") or "").strip() or None
        status = str(row.get("origin_status") or "legacy_partial").strip()

        if existing is None:
            connection.execute(
                """
                INSERT INTO source_images (
                    source_image_id,
                    canonical_sha256,
                    origin_status,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    source_id,
                    canonical,
                    status,
                    row.get("created_at"),
                ),
            )
            return

        current_canonical = str(existing["canonical_sha256"] or "").strip() or None
        current_status = str(existing["origin_status"] or "legacy_partial")
        merged_status = self._weaker_status(current_status, status)

        connection.execute(
            """
            UPDATE source_images
            SET canonical_sha256 = ?,
                origin_status = ?
            WHERE source_image_id = ?
            """,
            (
                current_canonical or canonical,
                merged_status,
                source_id,
            ),
        )

    def _upsert_artifact_base(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO image_artifacts (
                artifact_id,
                source_image_id,
                relative_path,
                external_path,
                sha256,
                size_bytes,
                kind,
                derived_from_artifact_id,
                width,
                height,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(artifact_id) DO UPDATE SET
                source_image_id = excluded.source_image_id,
                relative_path = excluded.relative_path,
                external_path = excluded.external_path,
                sha256 = excluded.sha256,
                size_bytes = excluded.size_bytes,
                kind = excluded.kind,
                width = excluded.width,
                height = excluded.height
            """,
            (
                row["artifact_id"],
                row["source_image_id"],
                row.get("relative_path"),
                row.get("external_path"),
                row["sha256"],
                row.get("size_bytes"),
                row.get("kind") or "raw",
                row.get("width"),
                row.get("height"),
                row.get("created_at"),
            ),
        )

    @staticmethod
    def _weaker_status(left: str, right: str) -> str:
        left_rank = _STATUS_RANK.get(str(left or ""), 99)
        right_rank = _STATUS_RANK.get(str(right or ""), 99)
        return left if left_rank >= right_rank else right
