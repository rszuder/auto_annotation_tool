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

_UNSET = object()


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

    def upsert_dataset_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        registered_at: str | None = None,
    ) -> str:
        """Zarejestruj historyczną tożsamość datasetu bez udawania członkostwa plików."""

        dataset_id = str(snapshot.get("dataset_id") or "").strip()
        if not dataset_id:
            return ""

        payload = {
            "dataset_id": dataset_id,
            "target": str(snapshot.get("target") or ""),
            "name": str(snapshot.get("name") or ""),
            "manifest_sha256": str(snapshot.get("manifest_sha256") or ""),
            "split_sha256": str(snapshot.get("split_sha256") or ""),
            "provenance_status": str(
                snapshot.get("provenance_status") or "legacy_partial"
            ),
        }

        self.initialize()
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT target, name, manifest_sha256, split_sha256,
                       provenance_status, registered_at
                FROM datasets
                WHERE dataset_id = ?
                """,
                (dataset_id,),
            ).fetchone()

            if existing is None:
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
                    ) VALUES (?, NULL, ?, ?, 'training', NULL, ?, ?, ?, NULL, ?)
                    """,
                    (
                        dataset_id,
                        payload["target"],
                        payload["name"],
                        payload["manifest_sha256"],
                        payload["split_sha256"],
                        payload["provenance_status"],
                        registered_at,
                    ),
                )
                return dataset_id

            merged_status = self._stronger_status(
                str(existing["provenance_status"] or "legacy_partial"),
                payload["provenance_status"],
            )
            connection.execute(
                """
                UPDATE datasets
                SET target = CASE
                        WHEN COALESCE(target, '') = '' THEN ?
                        ELSE target
                    END,
                    name = CASE
                        WHEN COALESCE(name, '') = '' THEN ?
                        ELSE name
                    END,
                    manifest_sha256 = CASE
                        WHEN COALESCE(manifest_sha256, '') = '' THEN ?
                        ELSE manifest_sha256
                    END,
                    split_sha256 = CASE
                        WHEN COALESCE(split_sha256, '') = '' THEN ?
                        ELSE split_sha256
                    END,
                    provenance_status = ?,
                    registered_at = COALESCE(registered_at, ?)
                WHERE dataset_id = ?
                """,
                (
                    payload["target"],
                    payload["name"],
                    payload["manifest_sha256"],
                    payload["split_sha256"],
                    merged_status,
                    registered_at,
                    dataset_id,
                ),
            )

        return dataset_id

    def upsert_training_run(
        self,
        *,
        run_id: str,
        project_id: str | None,
        target: str,
        dataset_id: str | None,
        status: str,
        base_model: str,
        config_sha256: str,
        output_relative_path: str,
        started_at: str | None,
        finished_at: str | None,
        provenance_status: str,
        replace_provenance_status: bool = False,
    ) -> None:
        self.initialize()
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT provenance_status
                FROM training_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            merged_status = provenance_status
            if existing is not None and not replace_provenance_status:
                merged_status = self._stronger_status(
                    str(existing["provenance_status"] or "legacy_unknown"),
                    provenance_status,
                )

            connection.execute(
                """
                INSERT INTO training_runs (
                    run_id,
                    project_id,
                    target,
                    dataset_id,
                    parent_run_id,
                    status,
                    base_model,
                    config_sha256,
                    output_relative_path,
                    started_at,
                    finished_at,
                    provenance_status
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    project_id = COALESCE(training_runs.project_id, excluded.project_id),
                    target = CASE
                        WHEN COALESCE(training_runs.target, '') = '' THEN excluded.target
                        ELSE training_runs.target
                    END,
                    dataset_id = CASE
                        WHEN COALESCE(excluded.dataset_id, '') <> ''
                            THEN excluded.dataset_id
                        ELSE training_runs.dataset_id
                    END,
                    status = CASE
                        WHEN COALESCE(excluded.status, '') <> '' THEN excluded.status
                        ELSE training_runs.status
                    END,
                    base_model = CASE
                        WHEN COALESCE(training_runs.base_model, '') = '' THEN excluded.base_model
                        ELSE training_runs.base_model
                    END,
                    config_sha256 = CASE
                        WHEN COALESCE(excluded.config_sha256, '') <> '' THEN excluded.config_sha256
                        ELSE training_runs.config_sha256
                    END,
                    output_relative_path = CASE
                        WHEN COALESCE(excluded.output_relative_path, '') <> ''
                            THEN excluded.output_relative_path
                        ELSE training_runs.output_relative_path
                    END,
                    started_at = COALESCE(training_runs.started_at, excluded.started_at),
                    finished_at = COALESCE(excluded.finished_at, training_runs.finished_at),
                    provenance_status = ?
                """,
                (
                    run_id,
                    project_id,
                    target,
                    dataset_id,
                    status,
                    base_model,
                    config_sha256,
                    output_relative_path,
                    started_at,
                    finished_at,
                    provenance_status,
                    merged_status,
                ),
            )

    def set_training_run_parent(
        self,
        run_id: str,
        parent_run_id: str | None,
    ) -> None:
        if not parent_run_id:
            return
        self.initialize()
        with self.database.transaction() as connection:
            parent_exists = connection.execute(
                "SELECT 1 FROM training_runs WHERE run_id = ?",
                (parent_run_id,),
            ).fetchone()
            if parent_exists is None:
                return
            connection.execute(
                """
                UPDATE training_runs
                SET parent_run_id = ?
                WHERE run_id = ?
                """,
                (parent_run_id, run_id),
            )

    def upsert_model_location(
        self,
        *,
        model_id: str,
        sha256: str,
        project_id: str | None,
        run_id: str | None,
        target: str,
        task_type: str,
        yolo_family: str,
        yolo_scale: str,
        checkpoint_kind: str,
        provenance_status: str,
        created_at: str | None,
        location_key: str,
        relative_path: str | None,
        external_path: str | None,
        is_primary: bool,
        location_project_id: Any = _UNSET,
    ) -> str:
        """Zarejestruj logiczny model i jedną jego fizyczną lokalizację."""

        resolved_location_project_id = (
            project_id
            if location_project_id is _UNSET
            else location_project_id
        )
        sha = str(sha256 or "").strip().lower()
        if not sha:
            raise ValueError("Model bez SHA-256 nie może trafić do rejestru.")

        self.initialize()
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT model_id, project_id, run_id, target, task_type,
                       yolo_family, yolo_scale, checkpoint_kind,
                       provenance_status, created_at
                FROM models
                WHERE sha256 = ?
                """,
                (sha,),
            ).fetchone()

            actual_model_id = model_id
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO models (
                        model_id,
                        project_id,
                        run_id,
                        target,
                        task_type,
                        yolo_family,
                        yolo_scale,
                        checkpoint_kind,
                        sha256,
                        provenance_status,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model_id,
                        project_id,
                        run_id,
                        target,
                        task_type,
                        yolo_family,
                        yolo_scale or "unknown",
                        checkpoint_kind,
                        sha,
                        provenance_status,
                        created_at,
                    ),
                )
            else:
                actual_model_id = str(existing["model_id"])
                merged_status = self._stronger_status(
                    str(existing["provenance_status"] or "legacy_unknown"),
                    provenance_status,
                )
                connection.execute(
                    """
                    UPDATE models
                    SET project_id = COALESCE(project_id, ?),
                        run_id = COALESCE(run_id, ?),
                        target = CASE
                            WHEN COALESCE(target, '') = '' OR target = 'unknown'
                                THEN ?
                            ELSE target
                        END,
                        task_type = CASE
                            WHEN COALESCE(task_type, '') = '' OR task_type = 'unknown'
                                THEN ?
                            ELSE task_type
                        END,
                        yolo_family = CASE
                            WHEN COALESCE(yolo_family, '') = '' THEN ?
                            ELSE yolo_family
                        END,
                        yolo_scale = CASE
                            WHEN COALESCE(yolo_scale, '') = '' OR yolo_scale = 'unknown'
                                THEN ?
                            ELSE yolo_scale
                        END,
                        checkpoint_kind = CASE
                            WHEN COALESCE(checkpoint_kind, '') = '' THEN ?
                            ELSE checkpoint_kind
                        END,
                        provenance_status = ?,
                        created_at = COALESCE(created_at, ?)
                    WHERE model_id = ?
                    """,
                    (
                        project_id,
                        run_id,
                        target,
                        task_type,
                        yolo_family,
                        yolo_scale or "unknown",
                        checkpoint_kind,
                        merged_status,
                        created_at,
                        actual_model_id,
                    ),
                )

            connection.execute(
                """
                INSERT INTO model_locations (
                    model_id,
                    location_key,
                    project_id,
                    relative_path,
                    external_path,
                    is_primary,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id, location_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    relative_path = excluded.relative_path,
                    external_path = excluded.external_path,
                    is_primary = excluded.is_primary,
                    created_at = COALESCE(
                        model_locations.created_at,
                        excluded.created_at
                    )
                """,
                (
                    actual_model_id,
                    location_key,
                    resolved_location_project_id,
                    relative_path,
                    external_path,
                    1 if is_primary else 0,
                    created_at,
                ),
            )

        return actual_model_id


    def resolve_or_create_source_image(
        self,
        *,
        sha256: str,
        source_image_id: str | None = None,
        origin_status: str = "exact_hash_only",
    ) -> str:
        sha = str(sha256 or "").strip().lower()
        requested_id = str(source_image_id or "").strip()
        if not sha:
            raise ValueError("SHA-256 obrazu nie może być pusty.")

        self.initialize()
        with self.database.transaction() as connection:
            if requested_id:
                existing_id = connection.execute(
                    """
                    SELECT source_image_id, canonical_sha256
                    FROM source_images
                    WHERE source_image_id = ?
                    """,
                    (requested_id,),
                ).fetchone()
                if existing_id is not None:
                    canonical = str(existing_id["canonical_sha256"] or "").strip().lower()
                    if canonical and canonical != sha:
                        raise ValueError(
                            "source_image_id istnieje, ale ma inny canonical_sha256."
                        )
                    return requested_id

            existing_sha = connection.execute(
                """
                SELECT source_image_id
                FROM source_images
                WHERE canonical_sha256 = ?
                """,
                (sha,),
            ).fetchone()
            if existing_sha is not None:
                existing_source_id = str(existing_sha["source_image_id"])
                if requested_id and existing_source_id != requested_id:
                    raise ValueError(
                        "Podany source_image_id koliduje z istniejącą tożsamością SHA-256."
                    )
                return existing_source_id

            resolved_id = requested_id or f"SRC-SHA256-{sha.upper()}"
            connection.execute(
                """
                INSERT INTO source_images (
                    source_image_id,
                    canonical_sha256,
                    origin_status,
                    created_at
                ) VALUES (?, ?, ?, NULL)
                """,
                (resolved_id, sha, origin_status),
            )
            return resolved_id

    def create_evaluation_track(
        self,
        *,
        track_id: str,
        owner_project_id: str | None,
        name: str,
        target: str,
        purpose: str,
        scope: str,
        status: str,
        version: int,
        parent_track_id: str | None,
        relative_path: str,
        reservation_policy: str,
        created_at: str | None,
    ) -> None:
        self.initialize()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_tracks (
                    track_id,
                    owner_project_id,
                    name,
                    target,
                    purpose,
                    scope,
                    status,
                    version,
                    parent_track_id,
                    relative_path,
                    member_count,
                    object_count,
                    reservation_policy,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    track_id,
                    owner_project_id,
                    name,
                    target,
                    purpose,
                    scope,
                    status,
                    int(version),
                    parent_track_id,
                    relative_path,
                    reservation_policy,
                    created_at,
                ),
            )

    def get_evaluation_track(self, track_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self.database.read_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM evaluation_tracks
                WHERE track_id = ?
                """,
                (track_id,),
            ).fetchone()

    def list_evaluation_track_members(
        self,
        track_id: str,
    ) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM evaluation_track_members
                    WHERE track_id = ?
                    ORDER BY member_index
                    """,
                    (track_id,),
                ).fetchall()
            )

    def next_evaluation_track_member_index(self, track_id: str) -> int:
        self.initialize()
        with self.database.read_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(member_index), -1) + 1
                FROM evaluation_track_members
                WHERE track_id = ?
                """,
                (track_id,),
            ).fetchone()
        return int(row[0] if row else 0)

    def add_evaluation_track_member(
        self,
        *,
        track_id: str,
        member_index: int,
        source_image_id: str,
        source_artifact_id: str | None,
        track_artifact_id: str,
        original_name: str,
        track_relative_path: str,
        sha256: str,
        artifact_relative_path: str,
        artifact_size_bytes: int | None,
    ) -> None:
        self.initialize()
        with self.database.transaction() as connection:
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
                ) VALUES (?, ?, ?, NULL, ?, ?, 'evaluation_track_image', NULL, NULL, NULL, NULL)
                """,
                (
                    track_artifact_id,
                    source_image_id,
                    artifact_relative_path,
                    sha256,
                    artifact_size_bytes,
                ),
            )
            connection.execute(
                """
                INSERT INTO evaluation_track_members (
                    track_id,
                    member_index,
                    source_image_id,
                    source_artifact_id,
                    track_artifact_id,
                    original_name,
                    track_relative_path,
                    sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    track_id,
                    int(member_index),
                    source_image_id,
                    source_artifact_id,
                    track_artifact_id,
                    original_name,
                    track_relative_path,
                    sha256,
                ),
            )
            connection.execute(
                """
                UPDATE evaluation_tracks
                SET member_count = (
                    SELECT COUNT(*)
                    FROM evaluation_track_members
                    WHERE track_id = ?
                )
                WHERE track_id = ?
                """,
                (track_id, track_id),
            )

    def update_evaluation_track(
        self,
        track_id: str,
        **fields: Any,
    ) -> None:
        allowed = {
            "status",
            "gt_format",
            "gt_relative_path",
            "gt_sha256",
            "manifest_sha256",
            "member_count",
            "object_count",
            "reservation_policy",
            "verified_at",
            "sealed_at",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(
                "Niedozwolone pola evaluation_tracks: " + ", ".join(unknown)
            )
        if not fields:
            return

        assignments = ", ".join(f"{name} = ?" for name in fields)
        params = tuple(fields[name] for name in fields) + (track_id,)
        self.initialize()
        with self.database.transaction() as connection:
            connection.execute(
                f"""
                UPDATE evaluation_tracks
                SET {assignments}
                WHERE track_id = ?
                """,
                params,
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
            "evaluation_track_members",
            "evaluation_tracks",
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

    @staticmethod
    def _stronger_status(left: str, right: str) -> str:
        left_rank = _STATUS_RANK.get(str(left or ""), 99)
        right_rank = _STATUS_RANK.get(str(right or ""), 99)
        return left if left_rank <= right_rank else right
