"""Warstwa dostępu do relacyjnego rejestru Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import json
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



    def list_model_locations(
        self,
        model_id: str,
    ) -> list[sqlite3.Row]:
        clean_id = str(model_id or "").strip()
        if not clean_id:
            return []
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM model_locations
                    WHERE model_id = ?
                    ORDER BY is_primary DESC, location_key
                    """,
                    (clean_id,),
                ).fetchall()
            )

    def list_model_experiment_references(
        self,
        model_id: str,
    ) -> list[sqlite3.Row]:
        clean_id = str(model_id or "").strip()
        if not clean_id:
            return []
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        participant.experiment_id,
                        experiment.name,
                        experiment.status,
                        experiment.track_id
                    FROM experiment_participants AS participant
                    JOIN experiments AS experiment
                      ON experiment.experiment_id = participant.experiment_id
                    WHERE participant.model_id = ?
                    ORDER BY experiment.created_at, participant.experiment_id
                    """,
                    (clean_id,),
                ).fetchall()
            )

    def unregister_model(
        self,
        model_id: str,
    ) -> dict[str, Any] | None:
        """Usuń logiczny model z rejestru, nigdy plik checkpointu."""
        clean_id = str(model_id or "").strip()
        if not clean_id:
            return None
        self.initialize()
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM models
                WHERE model_id = ?
                """,
                (clean_id,),
            ).fetchone()
            if existing is None:
                return None

            reference = connection.execute(
                """
                SELECT experiment_id
                FROM experiment_participants
                WHERE model_id = ?
                LIMIT 1
                """,
                (clean_id,),
            ).fetchone()
            if reference is not None:
                raise ValueError(
                    "Model jest używany przez zapisany eksperyment "
                    f"{reference['experiment_id']} i nie może zostać "
                    "wyrejestrowany."
                )

            snapshot = dict(existing)
            connection.execute(
                "DELETE FROM models WHERE model_id = ?",
                (clean_id,),
            )
            return snapshot

    def find_unique_image_artifact_by_sha256(
        self,
        sha256: str,
    ) -> sqlite3.Row | None:
        """Znajdź jednoznaczną tożsamość znanego artefaktu po dokładnym SHA-256.

        Jeśli ten sam bajtowy artefakt występuje pod więcej niż jednym
        ``source_image_id``, wynik jest niejednoznaczny i metoda zwraca ``None``.
        """

        sha = str(sha256 or "").strip().lower()
        if not sha:
            return None
        self.initialize()
        with self.database.read_connection() as connection:
            rows = list(
                connection.execute(
                    """
                    SELECT artifact_id, source_image_id, kind, relative_path
                    FROM image_artifacts
                    WHERE sha256 = ?
                    ORDER BY
                        CASE kind
                            WHEN 'dataset_image' THEN 0
                            WHEN 'raw' THEN 1
                            WHEN 'derived_image' THEN 2
                            WHEN 'evaluation_track_image' THEN 9
                            ELSE 5
                        END,
                        artifact_id
                    """,
                    (sha,),
                ).fetchall()
            )
        if not rows:
            return None
        source_ids = {
            str(row["source_image_id"] or "").strip()
            for row in rows
            if str(row["source_image_id"] or "").strip()
        }
        if len(source_ids) != 1:
            return None
        return rows[0]

    def resolve_or_create_source_image(
        self,
        *,
        sha256: str,
        source_image_id: str | None = None,
        origin_status: str = "exact_hash_only",
    ) -> str:
        """Rozwiąż logiczną tożsamość źródła dla jednego artefaktu obrazu.

        Gdy ``source_image_id`` już istnieje, jego ``canonical_sha256`` może być
        inny od SHA bieżącego artefaktu. To normalne dla resize/rekompresji/
        augmentacji należących do tego samego logicznego źródła.
        """

        sha = str(sha256 or "").strip().lower()
        requested_id = str(source_image_id or "").strip()
        if not sha:
            raise ValueError("SHA-256 obrazu nie może być pusty.")

        self.initialize()
        with self.database.transaction() as connection:
            if requested_id:
                existing_id = connection.execute(
                    """
                    SELECT source_image_id
                    FROM source_images
                    WHERE source_image_id = ?
                    """,
                    (requested_id,),
                ).fetchone()
                if existing_id is not None:
                    return requested_id

                raise ValueError(
                    "Podany source_image_id nie istnieje w rejestrze. "
                    "Dla nowego pliku pomiń source_image_id; zostanie użyta "
                    "konserwatywna tożsamość exact_hash_only."
                )

            existing_sha = connection.execute(
                """
                SELECT source_image_id
                FROM source_images
                WHERE canonical_sha256 = ?
                """,
                (sha,),
            ).fetchone()
            if existing_sha is not None:
                return str(existing_sha["source_image_id"])

            resolved_id = f"SRC-SHA256-{sha.upper()}"
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


    def list_evaluation_tracks(
        self,
        *,
        target: str | None = None,
        purpose: str | None = None,
        status: str | None = None,
        include_retired: bool = False,
    ) -> list[sqlite3.Row]:
        conditions: list[str] = []
        params: list[Any] = []

        if target:
            conditions.append("target = ?")
            params.append(str(target))
        if purpose:
            conditions.append("purpose = ?")
            params.append(str(purpose))
        if status:
            conditions.append("status = ?")
            params.append(str(status))
        elif not include_retired:
            conditions.append("status <> 'RETIRED'")

        where = (
            " WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM evaluation_tracks
                    """
                    + where
                    + """
                    ORDER BY
                        target,
                        name COLLATE NOCASE,
                        version DESC,
                        created_at DESC
                    """,
                    tuple(params),
                ).fetchall()
            )

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


    def remove_evaluation_track_members(
        self,
        track_id: str,
        member_indices: list[int] | tuple[int, ...] | set[int],
        *,
        invalidate_ground_truth: bool = False,
    ) -> list[dict[str, Any]]:
        """Atomowo usuń członków toru z rejestru."""
        clean_id = str(track_id or "").strip()
        indices = sorted({int(value) for value in member_indices})
        if not clean_id:
            raise ValueError("track_id nie może być pusty.")
        if not indices:
            return []

        self.initialize()
        placeholders = ",".join("?" for _ in indices)
        params = [clean_id, *indices]

        with self.database.transaction() as connection:
            rows = list(
                connection.execute(
                    f"""
                    SELECT *
                    FROM evaluation_track_members
                    WHERE track_id = ?
                      AND member_index IN ({placeholders})
                    ORDER BY member_index
                    """,
                    params,
                ).fetchall()
            )
            found = {int(row["member_index"]) for row in rows}
            missing = [value for value in indices if value not in found]
            if missing:
                raise ValueError(
                    "Nie znaleziono członków toru o indeksach: "
                    + ", ".join(str(value) for value in missing)
                )

            snapshots = [dict(row) for row in rows]
            artifact_ids = tuple(
                str(row["track_artifact_id"] or "").strip()
                for row in rows
                if str(row["track_artifact_id"] or "").strip()
            )

            connection.execute(
                f"""
                DELETE FROM evaluation_track_members
                WHERE track_id = ?
                  AND member_index IN ({placeholders})
                """,
                params,
            )

            for artifact_id in artifact_ids:
                connection.execute(
                    """
                    DELETE FROM image_artifacts
                    WHERE artifact_id = ?
                      AND kind = 'evaluation_track_image'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM evaluation_track_members AS member
                          WHERE member.source_artifact_id =
                                image_artifacts.artifact_id
                             OR member.track_artifact_id =
                                image_artifacts.artifact_id
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM dataset_members AS dataset_member
                          WHERE dataset_member.artifact_id =
                                image_artifacts.artifact_id
                      )
                    """,
                    (artifact_id,),
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
                (clean_id, clean_id),
            )

            if invalidate_ground_truth:
                connection.execute(
                    """
                    UPDATE evaluation_tracks
                    SET gt_format = NULL,
                        gt_relative_path = NULL,
                        gt_sha256 = NULL,
                        object_count = 0,
                        verified_at = NULL
                    WHERE track_id = ?
                    """,
                    (clean_id,),
                )

        return snapshots

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
        """Dodaj członka toru wraz z kopią-artefaktem i zachowaniem lineage."""

        member_sha = str(sha256 or "").strip().lower()
        if not member_sha:
            raise ValueError("Członek toru musi mieć SHA-256.")

        self.initialize()
        with self.database.transaction() as connection:
            track = connection.execute(
                """
                SELECT status
                FROM evaluation_tracks
                WHERE track_id = ?
                """,
                (track_id,),
            ).fetchone()
            if track is None:
                raise ValueError(f"Nie znaleziono toru: {track_id}")
            if str(track["status"] or "") != "DRAFT":
                raise ValueError(
                    "Członków można dodawać wyłącznie do toru DRAFT."
                )

            duplicate = connection.execute(
                """
                SELECT member_index
                FROM evaluation_track_members
                WHERE track_id = ? AND source_image_id = ?
                """,
                (track_id, source_image_id),
            ).fetchone()
            if duplicate is not None:
                raise ValueError(
                    "To logiczne źródło obrazu jest już członkiem toru."
                )

            if source_artifact_id:
                source_artifact = connection.execute(
                    """
                    SELECT source_image_id, sha256
                    FROM image_artifacts
                    WHERE artifact_id = ?
                    """,
                    (source_artifact_id,),
                ).fetchone()
                if source_artifact is None:
                    raise ValueError(
                        f"Nie znaleziono source_artifact_id: {source_artifact_id}"
                    )
                if str(source_artifact["source_image_id"] or "") != source_image_id:
                    raise ValueError(
                        "source_artifact_id należy do innego source_image_id."
                    )
                if (
                    str(source_artifact["sha256"] or "").strip().lower()
                    != member_sha
                ):
                    raise ValueError(
                        "SHA source_artifact_id nie odpowiada plikowi dodawanemu "
                        "do toru."
                    )

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
                ) VALUES (
                    ?, ?, ?, NULL, ?, ?, 'evaluation_track_image',
                    ?, NULL, NULL, NULL
                )
                """,
                (
                    track_artifact_id,
                    source_image_id,
                    artifact_relative_path,
                    member_sha,
                    artifact_size_bytes,
                    source_artifact_id,
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
                    member_sha,
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
            "seal_sha256",
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


    def delete_draft_evaluation_track(
        self,
        track_id: str,
    ) -> tuple[str, ...]:
        """Usuń wyłącznie roboczy DRAFT i jego kopie-artefakty.

        Tożsamości ``source_images`` pozostają w rejestrze, dzięki czemu
        późniejsze dodanie tego samego pliku nadal może zostać rozpoznane.
        """

        clean_id = str(track_id or "").strip()
        if not clean_id:
            raise ValueError("track_id nie może być pusty.")

        self.initialize()
        with self.database.transaction() as connection:
            track = connection.execute(
                """
                SELECT status
                FROM evaluation_tracks
                WHERE track_id = ?
                """,
                (clean_id,),
            ).fetchone()
            if track is None:
                raise ValueError(
                    f"Nie znaleziono toru: {clean_id}"
                )
            if str(track["status"] or "") != "DRAFT":
                raise ValueError(
                    "Fizycznie usuwać można wyłącznie tor DRAFT."
                )

            child = connection.execute(
                """
                SELECT track_id
                FROM evaluation_tracks
                WHERE parent_track_id = ?
                LIMIT 1
                """,
                (clean_id,),
            ).fetchone()
            if child is not None:
                raise ValueError(
                    "Nie można usunąć DRAFT będącego rodzicem "
                    "innej wersji toru."
                )

            experiment = connection.execute(
                """
                SELECT experiment_id
                FROM experiments
                WHERE track_id = ?
                LIMIT 1
                """,
                (clean_id,),
            ).fetchone()
            if experiment is not None:
                raise ValueError(
                    "Nie można usunąć DRAFT powiązanego "
                    "z eksperymentem."
                )

            artifact_rows = connection.execute(
                """
                SELECT DISTINCT track_artifact_id
                FROM evaluation_track_members
                WHERE track_id = ?
                  AND COALESCE(track_artifact_id, '') <> ''
                """,
                (clean_id,),
            ).fetchall()
            artifact_ids = tuple(
                str(row["track_artifact_id"])
                for row in artifact_rows
            )

            connection.execute(
                """
                DELETE FROM reservations
                WHERE track_id = ?
                """,
                (clean_id,),
            )
            connection.execute(
                """
                DELETE FROM evaluation_track_members
                WHERE track_id = ?
                """,
                (clean_id,),
            )
            connection.execute(
                """
                DELETE FROM evaluation_tracks
                WHERE track_id = ?
                """,
                (clean_id,),
            )

            removed_artifacts: list[str] = []
            for artifact_id in artifact_ids:
                cursor = connection.execute(
                    """
                    DELETE FROM image_artifacts
                    WHERE artifact_id = ?
                      AND kind = 'evaluation_track_image'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM evaluation_track_members AS member
                          WHERE member.source_artifact_id =
                                image_artifacts.artifact_id
                             OR member.track_artifact_id =
                                image_artifacts.artifact_id
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM image_artifacts AS child
                          WHERE child.derived_from_artifact_id =
                                image_artifacts.artifact_id
                      )
                    """,
                    (artifact_id,),
                )
                if int(cursor.rowcount or 0) > 0:
                    removed_artifacts.append(artifact_id)

        return tuple(removed_artifacts)



    def seal_evaluation_track_with_reservations(
        self,
        track_id: str,
        *,
        sealed_at: str,
        manifest_sha256: str,
        seal_sha256: str,
        reservation_type: str = "exclude_train_val",
    ) -> int:
        """Atomowo zapieczętuj tor i aktywuj jego rezerwacje train/val."""

        self.initialize()
        with self.database.transaction() as connection:
            track = connection.execute(
                """
                SELECT status, reservation_policy
                FROM evaluation_tracks
                WHERE track_id = ?
                """,
                (track_id,),
            ).fetchone()
            if track is None:
                raise ValueError(f"Nie znaleziono toru: {track_id}")
            if str(track["status"] or "") != "VERIFIED":
                raise ValueError(
                    "Zapieczętowanie wymaga statusu VERIFIED."
                )

            connection.execute(
                """
                UPDATE evaluation_tracks
                SET status = 'SEALED',
                    sealed_at = ?,
                    manifest_sha256 = ?,
                    seal_sha256 = ?
                WHERE track_id = ?
                """,
                (
                    sealed_at,
                    manifest_sha256,
                    seal_sha256,
                    track_id,
                ),
            )

            if str(track["reservation_policy"] or "") == "reserve_from_training":
                connection.execute(
                    """
                    INSERT INTO reservations (
                        source_image_id,
                        track_id,
                        reservation_type,
                        active,
                        created_at
                    )
                    SELECT
                        member.source_image_id,
                        member.track_id,
                        ?,
                        1,
                        ?
                    FROM evaluation_track_members AS member
                    WHERE member.track_id = ?
                    ON CONFLICT(
                        source_image_id,
                        track_id,
                        reservation_type
                    ) DO UPDATE SET
                        active = 1,
                        created_at = COALESCE(
                            reservations.created_at,
                            excluded.created_at
                        )
                    """,
                    (
                        reservation_type,
                        sealed_at,
                        track_id,
                    ),
                )

            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM reservations
                WHERE track_id = ?
                  AND reservation_type = ?
                  AND active = 1
                """,
                (track_id, reservation_type),
            ).fetchone()
        return int(row[0] if row else 0)

    def sync_all_training_reservations(
        self,
        *,
        reservation_type: str = "exclude_train_val",
    ) -> int:
        """Uzupełnij aktywne rezerwacje ze wszystkich SEALED/RETIRED torów."""

        self.initialize()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO reservations (
                    source_image_id,
                    track_id,
                    reservation_type,
                    active,
                    created_at
                )
                SELECT
                    member.source_image_id,
                    member.track_id,
                    ?,
                    1,
                    COALESCE(track.sealed_at, track.created_at)
                FROM evaluation_track_members AS member
                JOIN evaluation_tracks AS track
                  ON track.track_id = member.track_id
                WHERE track.status IN ('SEALED', 'RETIRED')
                  AND track.reservation_policy = 'reserve_from_training'
                ON CONFLICT(
                    source_image_id,
                    track_id,
                    reservation_type
                ) DO UPDATE SET active = 1
                """,
                (reservation_type,),
            )
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM reservations
                WHERE reservation_type = ?
                  AND active = 1
                """,
                (reservation_type,),
            ).fetchone()
        return int(row[0] if row else 0)

    def list_active_training_reservations(
        self,
        *,
        reservation_type: str = "exclude_train_val",
    ) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        reservation.source_image_id,
                        reservation.track_id,
                        track.name AS track_name,
                        track.target,
                        track.purpose,
                        track.status
                    FROM reservations AS reservation
                    JOIN evaluation_tracks AS track
                      ON track.track_id = reservation.track_id
                    WHERE reservation.reservation_type = ?
                      AND reservation.active = 1
                      AND track.status IN ('SEALED', 'RETIRED')
                    ORDER BY
                        reservation.source_image_id,
                        reservation.track_id
                    """,
                    (reservation_type,),
                ).fetchall()
            )

    def list_active_reserved_artifacts(
        self,
        *,
        reservation_type: str = "exclude_train_val",
    ) -> list[sqlite3.Row]:
        """Zwróć znane fizyczne SHA należące do aktywnie zarezerwowanych źródeł."""

        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        artifact.sha256,
                        artifact.source_image_id,
                        GROUP_CONCAT(
                            DISTINCT reservation.track_id
                        ) AS track_ids
                    FROM image_artifacts AS artifact
                    JOIN reservations AS reservation
                      ON reservation.source_image_id = artifact.source_image_id
                    JOIN evaluation_tracks AS track
                      ON track.track_id = reservation.track_id
                    WHERE reservation.reservation_type = ?
                      AND reservation.active = 1
                      AND track.status IN ('SEALED', 'RETIRED')
                      AND COALESCE(artifact.sha256, '') <> ''
                    GROUP BY
                        artifact.sha256,
                        artifact.source_image_id
                    ORDER BY artifact.sha256
                    """,
                    (reservation_type,),
                ).fetchall()
            )




    def list_models_for_target(self, target: str) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT model_id, project_id, run_id, target, task_type,
                           yolo_family, yolo_scale, checkpoint_kind, sha256,
                           provenance_status, created_at
                    FROM models
                    WHERE LOWER(COALESCE(target, '')) = LOWER(?)
                    ORDER BY yolo_family, yolo_scale, created_at DESC, model_id
                    """,
                    (str(target or "").strip(),),
                ).fetchall()
            )

    def list_participant_training_members(
        self,
        model_ids: list[str] | tuple[str, ...],
        *,
        splits: tuple[str, ...] = ("train", "val"),
    ) -> list[sqlite3.Row]:
        clean_models = tuple(dict.fromkeys(
            str(value or "").strip() for value in model_ids if str(value or "").strip()
        ))
        clean_splits = tuple(
            str(value or "").strip() for value in splits if str(value or "").strip()
        )
        if not clean_models or not clean_splits:
            return []
        mp = ",".join("?" for _ in clean_models)
        sp = ",".join("?" for _ in clean_splits)
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    WITH RECURSIVE ancestry(model_id, model_sha256, run_id, depth) AS (
                        SELECT model_id, sha256, run_id, 0
                        FROM models
                        WHERE model_id IN ({mp})
                          AND COALESCE(run_id, '') <> ''
                        UNION ALL
                        SELECT ancestry.model_id, ancestry.model_sha256,
                               run.parent_run_id, ancestry.depth + 1
                        FROM ancestry
                        JOIN training_runs AS run ON run.run_id = ancestry.run_id
                        WHERE COALESCE(run.parent_run_id, '') <> ''
                          AND ancestry.depth < 128
                    )
                    SELECT ancestry.model_id, ancestry.model_sha256,
                           ancestry.depth AS ancestor_depth,
                           run.run_id, run.dataset_id, run.parent_run_id,
                           run.provenance_status AS run_provenance_status,
                           dataset.provenance_status AS dataset_provenance_status,
                           dataset.relative_path AS dataset_relative_path,
                           member.split, member.source_image_id,
                           member.file_sha256,
                           member.relative_path AS member_relative_path,
                           source.origin_status,
                           artifact.relative_path AS artifact_relative_path,
                           artifact.external_path AS artifact_external_path,
                           artifact.sha256 AS artifact_sha256
                    FROM ancestry
                    LEFT JOIN training_runs AS run ON run.run_id = ancestry.run_id
                    LEFT JOIN datasets AS dataset ON dataset.dataset_id = run.dataset_id
                    LEFT JOIN dataset_members AS member
                        ON member.dataset_id = run.dataset_id AND member.split IN ({sp})
                    LEFT JOIN source_images AS source ON source.source_image_id = member.source_image_id
                    LEFT JOIN image_artifacts AS artifact ON artifact.artifact_id = member.artifact_id
                    ORDER BY ancestry.model_id, ancestry.depth, run.run_id,
                             member.split, member.relative_path
                    """,
                    (*clean_models, *clean_splits),
                ).fetchall()
            )


    @staticmethod
    def _upsert_track_audit_state(connection, track_id, state):
        connection.execute(
            """INSERT INTO evaluation_track_audit_state
               (track_id, status, participant_fingerprint, member_fingerprint, audit_id, state_json)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(track_id) DO UPDATE SET
                   status=excluded.status, participant_fingerprint=excluded.participant_fingerprint,
                   member_fingerprint=excluded.member_fingerprint, audit_id=excluded.audit_id,
                   state_json=excluded.state_json""",
            (track_id, state["status"], state.get("participant_fingerprint", ""),
             state.get("member_fingerprint", ""), state.get("audit_id"),
             json.dumps(state, ensure_ascii=False, sort_keys=True)),
        )

    def save_evaluation_track_audit_state(self, track_id, state) -> None:
        self.initialize()
        with self.database.transaction() as connection:
            self._upsert_track_audit_state(connection, track_id, state)

    def get_evaluation_track_audit_state(self, track_id) -> dict | None:
        self.initialize()
        with self.database.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM evaluation_track_audit_state WHERE track_id=?", (track_id,)
            ).fetchone()
        if row is None:
            return None
        state = json.loads(row["state_json"])
        state.update({key: row[key] for key in (
            "track_id", "status", "participant_fingerprint", "member_fingerprint", "audit_id"
        )})
        return state

    def record_evaluation_track_audit(
        self, audit, decisions, *, state=None, expected_member_shas=None
    ) -> None:
        """Commit the diagnosis, operator decisions and current state together."""
        self.initialize()
        with self.database.transaction() as connection:
            if expected_member_shas is not None:
                current = {
                    str(row[0]).lower() for row in connection.execute(
                        "SELECT sha256 FROM evaluation_track_members WHERE track_id=?",
                        (audit["track_id"],),
                    )
                }
                if current != set(expected_member_shas):
                    raise ValueError("Skład toru zmienił się podczas zapisywania audytu.")
            connection.execute(
                """INSERT INTO evaluation_track_audits
                   (audit_id, track_id, mode, participant_fingerprint, member_fingerprint,
                    audited_at, applied_at, report_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (audit["audit_id"], audit["track_id"], audit["mode"],
                 audit["participant_fingerprint"], audit["member_fingerprint"],
                 audit["audited_at"], audit["applied_at"],
                 json.dumps(audit["report"], ensure_ascii=False, sort_keys=True)),
            )
            connection.executemany(
                """INSERT INTO evaluation_track_audit_decisions
                   (audit_id, path, sha256, status, decision) VALUES (?, ?, ?, ?, ?)""",
                [(audit["audit_id"], row["path"], row["sha256"], row["status"], row["decision"])
                 for row in decisions],
            )
            if state is not None:
                self._upsert_track_audit_state(connection, audit["track_id"], state)

    def list_evaluation_track_audits(self, track_id) -> list[dict]:
        self.initialize()
        with self.database.read_connection() as connection:
            rows = connection.execute(
                """SELECT audit_id, track_id, mode, participant_fingerprint, member_fingerprint,
                          audited_at, applied_at
                   FROM evaluation_track_audits WHERE track_id=? ORDER BY applied_at DESC""",
                (track_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_evaluation_track_audit(self, audit_id) -> dict | None:
        self.initialize()
        with self.database.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM evaluation_track_audits WHERE audit_id=?", (audit_id,)
            ).fetchone()
            if row is None:
                return None
            decisions = connection.execute(
                "SELECT path, sha256, status, decision FROM evaluation_track_audit_decisions "
                "WHERE audit_id=? ORDER BY path", (audit_id,),
            ).fetchall()
        result = dict(row)
        result["report"] = json.loads(result.pop("report_json"))
        result["decisions"] = [dict(item) for item in decisions]
        return result

    def find_source_ids_by_sha256_batch(self, sha256_values) -> dict[str, set[str]]:
        """Read known source identities without creating registry records."""
        shas = tuple(dict.fromkeys(str(value).strip().lower()
                                   for value in sha256_values if value))
        result: dict[str, set[str]] = {}
        self.initialize()
        with self.database.read_connection() as connection:
            for offset in range(0, len(shas), 400):
                chunk = shas[offset:offset + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""SELECT sha256, source_image_id FROM image_artifacts
                        WHERE sha256 IN ({placeholders})
                        UNION
                        SELECT canonical_sha256, source_image_id FROM source_images
                        WHERE canonical_sha256 IN ({placeholders})""",
                    (*chunk, *chunk),
                ).fetchall()
                for row in rows:
                    result.setdefault(str(row[0]).lower(), set()).add(str(row[1]))
        return result

    def resolve_track_member_sources_batch(
        self,
        sha256_values: list[str] | tuple[str, ...],
    ) -> dict[str, dict[str, str | None]]:
        shas = tuple(dict.fromkeys(
            str(value or "").strip().lower()
            for value in sha256_values if str(value or "").strip()
        ))
        if not shas:
            return {}
        result = {}
        self.initialize()
        with self.database.transaction() as connection:
            for offset in range(0, len(shas), 800):
                chunk = shas[offset: offset + 800]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""
                    SELECT sha256, artifact_id, source_image_id, kind
                    FROM image_artifacts
                    WHERE sha256 IN ({placeholders})
                    ORDER BY artifact_id
                    """,
                    chunk,
                ).fetchall()
                grouped = {}
                for row in rows:
                    sha = str(row["sha256"] or "").lower()
                    grouped.setdefault(sha, []).append(row)
                for sha, candidates in grouped.items():
                    source_ids = {
                        str(row["source_image_id"] or "").strip()
                        for row in candidates if str(row["source_image_id"] or "").strip()
                    }
                    if len(source_ids) == 1:
                        result[sha] = {
                            "source_image_id": next(iter(source_ids)),
                            "source_artifact_id": str(candidates[0]["artifact_id"] or "") or None,
                        }
                source_rows = connection.execute(
                    f"""
                    SELECT source_image_id, canonical_sha256
                    FROM source_images
                    WHERE canonical_sha256 IN ({placeholders})
                    """,
                    chunk,
                ).fetchall()
                for row in source_rows:
                    sha = str(row["canonical_sha256"] or "").lower()
                    result.setdefault(
                        sha,
                        {
                            "source_image_id": str(row["source_image_id"] or ""),
                            "source_artifact_id": None,
                        },
                    )
            for sha in shas:
                if sha in result:
                    continue
                source_id = f"SRC-SHA256-{sha.upper()}"
                connection.execute(
                    """
                    INSERT INTO source_images (
                        source_image_id, canonical_sha256, origin_status, created_at
                    ) VALUES (?, ?, 'exact_hash_only', NULL)
                    ON CONFLICT(source_image_id) DO NOTHING
                    """,
                    (source_id, sha),
                )
                result[sha] = {
                    "source_image_id": source_id,
                    "source_artifact_id": None,
                }
        return result

    def add_evaluation_track_members_batch(
        self,
        track_id: str,
        rows: list[Mapping[str, Any]],
    ) -> None:
        if not rows:
            return
        self.initialize()
        with self.database.transaction() as connection:
            track = connection.execute(
                "SELECT status FROM evaluation_tracks WHERE track_id = ?",
                (track_id,),
            ).fetchone()
            if track is None or str(track["status"] or "") != "DRAFT":
                raise ValueError("Członków można dodawać wyłącznie do toru DRAFT.")
            existing = connection.execute(
                """
                SELECT original_name, source_image_id, sha256
                FROM evaluation_track_members
                WHERE track_id = ?
                """,
                (track_id,),
            ).fetchall()
            names = {str(row["original_name"] or "") for row in existing}
            sources = {str(row["source_image_id"] or "") for row in existing}
            shas = {str(row["sha256"] or "").lower() for row in existing}
            batch_names, batch_sources, batch_shas = set(), set(), set()
            for item in rows:
                name = str(item["original_name"])
                source_id = str(item["source_image_id"])
                sha = str(item["sha256"]).lower()
                if name in names or name in batch_names:
                    raise ValueError(f"Tor zawiera już obraz o nazwie: {name}")
                if (
                    source_id in sources or source_id in batch_sources
                    or sha in shas or sha in batch_shas
                ):
                    raise ValueError("Tor zawiera już to samo logiczne źródło obrazu.")
                batch_names.add(name)
                batch_sources.add(source_id)
                batch_shas.add(sha)
            for item in rows:
                connection.execute(
                    """
                    INSERT INTO image_artifacts (
                        artifact_id, source_image_id, relative_path, external_path,
                        sha256, size_bytes, kind, derived_from_artifact_id,
                        width, height, created_at
                    ) VALUES (?, ?, ?, NULL, ?, ?, 'evaluation_track_image',
                              ?, NULL, NULL, NULL)
                    """,
                    (
                        item["track_artifact_id"], item["source_image_id"],
                        item["artifact_relative_path"], str(item["sha256"]).lower(),
                        item.get("artifact_size_bytes"), item.get("source_artifact_id"),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO evaluation_track_members (
                        track_id, member_index, source_image_id, source_artifact_id,
                        track_artifact_id, original_name, track_relative_path, sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        track_id, int(item["member_index"]), item["source_image_id"],
                        item.get("source_artifact_id"), item["track_artifact_id"],
                        item["original_name"], item["track_relative_path"],
                        str(item["sha256"]).lower(),
                    ),
                )
            connection.execute(
                """
                UPDATE evaluation_tracks
                SET member_count = (
                    SELECT COUNT(*) FROM evaluation_track_members WHERE track_id = ?
                )
                WHERE track_id = ?
                """,
                (track_id, track_id),
            )

    def get_model(self, model_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self.database.read_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM models
                WHERE model_id = ?
                """,
                (str(model_id or "").strip(),),
            ).fetchone()

    def get_model_by_sha256(self, sha256: str) -> sqlite3.Row | None:
        self.initialize()
        with self.database.read_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM models
                WHERE sha256 = ?
                """,
                (str(sha256 or "").strip().lower(),),
            ).fetchone()

    def list_training_runs_for_target(
        self,
        target: str,
    ) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM training_runs
                    WHERE LOWER(COALESCE(target, '')) = LOWER(?)
                    ORDER BY
                        COALESCE(finished_at, started_at, '') DESC,
                        run_id DESC
                    """,
                    (str(target or "").strip(),),
                ).fetchall()
            )

    def get_training_run(self, run_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self.database.read_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM training_runs
                WHERE run_id = ?
                """,
                (str(run_id or "").strip(),),
            ).fetchone()

    def get_dataset(self, dataset_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self.database.read_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM datasets
                WHERE dataset_id = ?
                """,
                (str(dataset_id or "").strip(),),
            ).fetchone()

    def list_source_image_ids_by_sha256(
        self,
        sha256: str,
    ) -> list[str]:
        sha = str(sha256 or "").strip().lower()
        if not sha:
            return []
        self.initialize()
        with self.database.read_connection() as connection:
            rows = connection.execute(
                """
                SELECT source_image_id
                FROM source_images
                WHERE LOWER(COALESCE(canonical_sha256, '')) = ?
                UNION
                SELECT source_image_id
                FROM image_artifacts
                WHERE LOWER(COALESCE(sha256, '')) = ?
                ORDER BY source_image_id
                """,
                (sha, sha),
            ).fetchall()
        return [
            str(row["source_image_id"] or "").strip()
            for row in rows
            if str(row["source_image_id"] or "").strip()
        ]

    def list_training_reference_members(
        self,
        target: str,
        *,
        splits: tuple[str, ...] = ("train", "val"),
    ) -> list[sqlite3.Row]:
        raw_target = str(target or "").strip().lower()
        normalized_target = {
            "plates": "plate",
            "pose": "plate",
            "mt": "plate",
            "chars": "char",
            "character": "char",
            "characters": "char",
            "ocr": "char",
            "mz": "char",
            "vehicles": "vehicle",
            "mp": "vehicle",
        }.get(raw_target, raw_target)

        normalized_splits = tuple(
            str(value or "").strip().lower()
            for value in splits
            if str(value or "").strip()
        )
        if not normalized_target or not normalized_splits:
            return []

        placeholders = ", ".join("?" for _ in normalized_splits)
        params: tuple[Any, ...] = (
            normalized_target,
            *normalized_splits,
        )

        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        member.dataset_id,
                        member.artifact_id,
                        member.source_image_id,
                        member.split,
                        member.relative_path AS dataset_relative_path,
                        member.file_sha256,
                        source.origin_status,
                        source.canonical_sha256,
                        dataset.target AS dataset_target,
                        dataset.purpose AS dataset_purpose,
                        dataset.provenance_status AS dataset_provenance_status,
                        dataset.relative_path AS dataset_root_relative_path,
                        artifact.relative_path AS artifact_relative_path,
                        artifact.external_path AS artifact_external_path,
                        (
                            SELECT location.relative_path
                            FROM dataset_locations AS location
                            WHERE location.dataset_id = member.dataset_id
                            ORDER BY
                                location.is_primary DESC,
                                COALESCE(location.discovered_at, '') DESC,
                                location.location_key
                            LIMIT 1
                        ) AS dataset_location_relative_path,
                        (
                            SELECT location.external_path
                            FROM dataset_locations AS location
                            WHERE location.dataset_id = member.dataset_id
                            ORDER BY
                                location.is_primary DESC,
                                COALESCE(location.discovered_at, '') DESC,
                                location.location_key
                            LIMIT 1
                        ) AS dataset_location_external_path,
                        (
                            SELECT GROUP_CONCAT(DISTINCT run.run_id)
                            FROM training_runs AS run
                            WHERE run.dataset_id = member.dataset_id
                        ) AS training_run_ids,
                        (
                            SELECT GROUP_CONCAT(DISTINCT model.model_id)
                            FROM models AS model
                            JOIN training_runs AS model_run
                              ON model_run.run_id = model.run_id
                            WHERE model_run.dataset_id = member.dataset_id
                        ) AS model_ids
                    FROM dataset_members AS member
                    JOIN datasets AS dataset
                      ON dataset.dataset_id = member.dataset_id
                    JOIN source_images AS source
                      ON source.source_image_id = member.source_image_id
                    LEFT JOIN image_artifacts AS artifact
                      ON artifact.artifact_id = member.artifact_id
                    WHERE LOWER(COALESCE(dataset.target, '')) = ?
                      AND LOWER(COALESCE(member.split, '')) IN ({placeholders})
                      AND (
                          LOWER(COALESCE(dataset.purpose, 'training')) = 'training'
                          OR EXISTS (
                              SELECT 1
                              FROM training_runs AS used_run
                              WHERE used_run.dataset_id = member.dataset_id
                          )
                      )
                    ORDER BY
                        member.dataset_id,
                        member.split,
                        member.relative_path,
                        member.artifact_id
                    """,
                    params,
                ).fetchall()
            )


    def list_dataset_member_lineage(
        self,
        dataset_id: str,
        *,
        splits: tuple[str, ...] = ("train", "val"),
    ) -> list[sqlite3.Row]:
        normalized_splits = tuple(
            str(value or "").strip()
            for value in splits
            if str(value or "").strip()
        )
        if not normalized_splits:
            return []

        placeholders = ", ".join("?" for _ in normalized_splits)
        params: tuple[Any, ...] = (
            str(dataset_id or "").strip(),
            *normalized_splits,
        )
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        member.dataset_id,
                        member.artifact_id,
                        member.source_image_id,
                        member.split,
                        member.relative_path,
                        member.file_sha256,
                        source.origin_status,
                        source.canonical_sha256
                    FROM dataset_members AS member
                    JOIN source_images AS source
                      ON source.source_image_id = member.source_image_id
                    WHERE member.dataset_id = ?
                      AND member.split IN ({placeholders})
                    ORDER BY
                        member.split,
                        member.relative_path,
                        member.artifact_id
                    """,
                    params,
                ).fetchall()
            )

    def list_evaluation_track_member_lineage(
        self,
        track_id: str,
    ) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        member.track_id,
                        member.member_index,
                        member.source_image_id,
                        member.source_artifact_id,
                        member.track_artifact_id,
                        member.original_name,
                        member.track_relative_path,
                        member.sha256,
                        source.origin_status,
                        source.canonical_sha256
                    FROM evaluation_track_members AS member
                    JOIN source_images AS source
                      ON source.source_image_id = member.source_image_id
                    WHERE member.track_id = ?
                    ORDER BY member.member_index
                    """,
                    (str(track_id or "").strip(),),
                ).fetchall()
            )



    def create_experiment_bundle(
        self,
        *,
        experiment: Mapping[str, Any],
        participants: list[Mapping[str, Any]],
        overlaps: list[Mapping[str, Any]],
    ) -> None:
        """Atomowo zapisz plan eksperymentu, uczestników i znane overlap items."""

        experiment_id = str(
            experiment.get("experiment_id") or ""
        ).strip()
        if not experiment_id:
            raise ValueError("experiment_id nie może być pusty.")
        if not participants:
            raise ValueError(
                "Eksperyment musi mieć uczestników."
            )

        self.initialize()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO experiments (
                    experiment_id,
                    owner_project_id,
                    name,
                    target,
                    mode,
                    track_id,
                    status,
                    protocol_json,
                    protocol_sha256,
                    track_manifest_sha256,
                    created_at,
                    sealed_at,
                    started_at,
                    finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    experiment.get("owner_project_id"),
                    str(experiment.get("name") or ""),
                    str(experiment.get("target") or ""),
                    str(experiment.get("mode") or ""),
                    experiment.get("track_id"),
                    str(experiment.get("status") or ""),
                    str(experiment.get("protocol_json") or ""),
                    str(experiment.get("protocol_sha256") or ""),
                    str(
                        experiment.get(
                            "track_manifest_sha256"
                        )
                        or ""
                    ),
                    experiment.get("created_at"),
                    experiment.get("sealed_at"),
                    experiment.get("started_at"),
                    experiment.get("finished_at"),
                ),
            )

            for participant in participants:
                connection.execute(
                    """
                    INSERT INTO experiment_participants (
                        experiment_id,
                        model_id,
                        position,
                        model_sha256,
                        independence_status,
                        overlap_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment_id,
                        str(participant.get("model_id") or ""),
                        int(participant.get("position") or 0),
                        str(
                            participant.get("model_sha256")
                            or ""
                        ),
                        str(
                            participant.get(
                                "independence_status"
                            )
                            or "UNKNOWN"
                        ),
                        int(
                            participant.get("overlap_count")
                            or 0
                        ),
                    ),
                )

            for overlap in overlaps:
                connection.execute(
                    """
                    INSERT INTO experiment_overlap_items (
                        experiment_id,
                        model_id,
                        source_image_id,
                        training_dataset_id,
                        training_run_id,
                        reason
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment_id,
                        str(overlap.get("model_id") or ""),
                        str(
                            overlap.get("source_image_id")
                            or ""
                        ),
                        overlap.get("training_dataset_id"),
                        overlap.get("training_run_id"),
                        str(overlap.get("reason") or ""),
                    ),
                )

    def get_experiment(
        self,
        experiment_id: str,
    ) -> sqlite3.Row | None:
        self.initialize()
        with self.database.read_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM experiments
                WHERE experiment_id = ?
                """,
                (str(experiment_id or "").strip(),),
            ).fetchone()

    def list_experiment_participants(
        self,
        experiment_id: str,
    ) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM experiment_participants
                    WHERE experiment_id = ?
                    ORDER BY position, model_id
                    """,
                    (str(experiment_id or "").strip(),),
                ).fetchall()
            )

    def list_experiment_overlap_items(
        self,
        experiment_id: str,
    ) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM experiment_overlap_items
                    WHERE experiment_id = ?
                    ORDER BY
                        model_id,
                        training_run_id,
                        training_dataset_id,
                        source_image_id
                    """,
                    (str(experiment_id or "").strip(),),
                ).fetchall()
            )

    def update_experiment_lifecycle(
        self,
        experiment_id: str,
        *,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        self.initialize()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments
                SET status = ?,
                    started_at = COALESCE(?, started_at),
                    finished_at = COALESCE(?, finished_at)
                WHERE experiment_id = ?
                """,
                (
                    str(status or ""),
                    started_at,
                    finished_at,
                    str(experiment_id or "").strip(),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"Nie znaleziono eksperymentu: {experiment_id}"
                )

    def upsert_experiment_result(
        self,
        *,
        experiment_id: str,
        model_id: str,
        metrics_json: str,
        result_relative_path: str | None,
        created_at: str | None,
    ) -> None:
        self.initialize()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO experiment_results (
                    experiment_id,
                    model_id,
                    metrics_json,
                    result_relative_path,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id, model_id) DO UPDATE SET
                    metrics_json = excluded.metrics_json,
                    result_relative_path = excluded.result_relative_path,
                    created_at = excluded.created_at
                """,
                (
                    str(experiment_id or "").strip(),
                    str(model_id or "").strip(),
                    str(metrics_json or ""),
                    result_relative_path,
                    created_at,
                ),
            )

    def get_experiment_result(
        self,
        experiment_id: str,
        model_id: str,
    ) -> sqlite3.Row | None:
        self.initialize()
        with self.database.read_connection() as connection:
            return connection.execute(
                """
                SELECT *
                FROM experiment_results
                WHERE experiment_id = ?
                  AND model_id = ?
                """,
                (
                    str(experiment_id or "").strip(),
                    str(model_id or "").strip(),
                ),
            ).fetchone()



    def list_experiment_results(
        self,
        experiment_id: str,
    ) -> list[sqlite3.Row]:
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT *
                    FROM experiment_results
                    WHERE experiment_id = ?
                    ORDER BY model_id
                    """,
                    (str(experiment_id or "").strip(),),
                ).fetchall()
            )


    def list_experiment_result_bundles(
        self,
        *,
        target: str | None = None,
    ) -> list[sqlite3.Row]:
        """Zwróć wyniki wraz z zamrożonym kontekstem eksperymentu."""

        conditions: list[str] = []
        params: list[Any] = []
        normalized_target = str(target or "").strip().lower()
        if normalized_target:
            conditions.append(
                "LOWER(COALESCE(experiment.target, '')) = ?"
            )
            params.append(normalized_target)

        where = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        experiment.experiment_id,
                        experiment.target AS experiment_target,
                        experiment.mode AS experiment_mode,
                        experiment.status AS experiment_status,
                        experiment.protocol_json,
                        experiment.protocol_sha256,
                        experiment.track_id,
                        experiment.track_manifest_sha256,
                        participant.model_id,
                        participant.model_sha256,
                        participant.independence_status,
                        participant.overlap_count,
                        result.metrics_json,
                        result.result_relative_path,
                        result.created_at AS result_created_at
                    FROM experiment_results AS result
                    JOIN experiments AS experiment
                      ON experiment.experiment_id = result.experiment_id
                    JOIN experiment_participants AS participant
                      ON participant.experiment_id = result.experiment_id
                     AND participant.model_id = result.model_id
                    {where}
                    ORDER BY
                        result.created_at,
                        experiment.experiment_id,
                        participant.position,
                        participant.model_id
                    """,
                    tuple(params),
                ).fetchall()
            )


    def list_model_comparison_rows(
        self,
        *,
        target: str,
        project_id: str | None = None,
    ) -> list[sqlite3.Row]:
        """Zwróć modele z ich lokalizacjami dla wspólnego katalogu porównań."""

        normalized_target = str(target or "").strip().lower()
        if not normalized_target:
            return []

        conditions = ["LOWER(COALESCE(model.target, '')) = ?"]
        params: list[Any] = [normalized_target]
        if project_id:
            conditions.append(
                "(model.project_id = ? OR location.project_id = ?)"
            )
            params.extend([project_id, project_id])

        where = " AND ".join(conditions)
        self.initialize()
        with self.database.read_connection() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT
                        model.model_id,
                        model.sha256,
                        model.project_id AS owner_project_id,
                        owner_project.display_name AS owner_project_name,
                        model.run_id,
                        model.target,
                        model.task_type,
                        model.yolo_family,
                        model.yolo_scale,
                        model.checkpoint_kind,
                        model.provenance_status,
                        model.created_at AS model_created_at,
                        location.location_key,
                        location.project_id AS location_project_id,
                        location_project.display_name AS location_project_name,
                        location.relative_path,
                        location.external_path,
                        location.is_primary,
                        location.created_at AS location_created_at
                    FROM models AS model
                    JOIN model_locations AS location
                      ON location.model_id = model.model_id
                    LEFT JOIN projects AS owner_project
                      ON owner_project.project_id = model.project_id
                    LEFT JOIN projects AS location_project
                      ON location_project.project_id = location.project_id
                    WHERE {where}
                    ORDER BY
                        model.model_id,
                        CASE
                            WHEN location.project_id IS NULL THEN 0
                            ELSE 1
                        END,
                        location.is_primary DESC,
                        location.location_key
                    """,
                    tuple(params),
                ).fetchall()
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
            "reservations",
            "experiment_results",
            "experiment_overlap_items",
            "experiment_participants",
            "experiments",
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
