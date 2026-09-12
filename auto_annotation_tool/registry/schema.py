"""Schemat relacyjnego rejestru Workspace.

Duże artefakty pozostają na dysku. SQLite przechowuje wyłącznie tożsamość,
pochodzenie, relacje, sumy kontrolne i stan eksperymentów.
"""

from __future__ import annotations

SCHEMA_VERSION = 2


SCHEMA_V1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        campaign_key TEXT,
        folder_name TEXT,
        display_name TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_images (
        source_image_id TEXT PRIMARY KEY,
        canonical_sha256 TEXT,
        origin_status TEXT NOT NULL DEFAULT 'legacy_partial',
        created_at TEXT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_source_images_canonical_sha256
    ON source_images(canonical_sha256)
    WHERE canonical_sha256 IS NOT NULL AND canonical_sha256 <> ''
    """,
    """
    CREATE TABLE IF NOT EXISTS image_artifacts (
        artifact_id TEXT PRIMARY KEY,
        source_image_id TEXT NOT NULL,
        relative_path TEXT,
        external_path TEXT,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER,
        kind TEXT NOT NULL DEFAULT 'raw',
        derived_from_artifact_id TEXT,
        width INTEGER,
        height INTEGER,
        created_at TEXT,
        FOREIGN KEY(source_image_id)
            REFERENCES source_images(source_image_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(derived_from_artifact_id)
            REFERENCES image_artifacts(artifact_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_image_artifacts_source_image
    ON image_artifacts(source_image_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_image_artifacts_sha256
    ON image_artifacts(sha256)
    """,
    """
    CREATE TABLE IF NOT EXISTS datasets (
        dataset_id TEXT PRIMARY KEY,
        owner_project_id TEXT,
        target TEXT,
        name TEXT,
        purpose TEXT NOT NULL DEFAULT 'training',
        relative_path TEXT,
        manifest_sha256 TEXT,
        split_sha256 TEXT,
        provenance_status TEXT NOT NULL DEFAULT 'legacy_partial',
        created_at TEXT,
        registered_at TEXT,
        FOREIGN KEY(owner_project_id)
            REFERENCES projects(project_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_datasets_project_target
    ON datasets(owner_project_id, target)
    """,
    """
    CREATE TABLE IF NOT EXISTS dataset_members (
        dataset_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,
        source_image_id TEXT NOT NULL,
        split TEXT NOT NULL,
        relative_path TEXT,
        file_sha256 TEXT,
        PRIMARY KEY(dataset_id, artifact_id, split),
        FOREIGN KEY(dataset_id)
            REFERENCES datasets(dataset_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(artifact_id)
            REFERENCES image_artifacts(artifact_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(source_image_id)
            REFERENCES source_images(source_image_id)
            ON UPDATE CASCADE ON DELETE RESTRICT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_dataset_members_source
    ON dataset_members(source_image_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_dataset_members_dataset_split
    ON dataset_members(dataset_id, split)
    """,
    """
    CREATE TABLE IF NOT EXISTS training_runs (
        run_id TEXT PRIMARY KEY,
        project_id TEXT,
        target TEXT,
        dataset_id TEXT,
        parent_run_id TEXT,
        status TEXT,
        base_model TEXT,
        config_sha256 TEXT,
        output_relative_path TEXT,
        started_at TEXT,
        finished_at TEXT,
        provenance_status TEXT NOT NULL DEFAULT 'legacy_partial',
        FOREIGN KEY(project_id)
            REFERENCES projects(project_id)
            ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY(dataset_id)
            REFERENCES datasets(dataset_id)
            ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY(parent_run_id)
            REFERENCES training_runs(run_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_training_runs_dataset
    ON training_runs(dataset_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_training_runs_parent
    ON training_runs(parent_run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS models (
        model_id TEXT PRIMARY KEY,
        project_id TEXT,
        run_id TEXT,
        target TEXT,
        task_type TEXT,
        yolo_family TEXT,
        yolo_scale TEXT NOT NULL DEFAULT 'unknown',
        checkpoint_kind TEXT,
        sha256 TEXT NOT NULL,
        provenance_status TEXT NOT NULL DEFAULT 'legacy_partial',
        created_at TEXT,
        FOREIGN KEY(project_id)
            REFERENCES projects(project_id)
            ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY(run_id)
            REFERENCES training_runs(run_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_models_sha256
    ON models(sha256)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_models_target_project
    ON models(target, project_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS model_locations (
        model_id TEXT NOT NULL,
        location_key TEXT NOT NULL,
        project_id TEXT,
        relative_path TEXT,
        external_path TEXT,
        is_primary INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        PRIMARY KEY(model_id, location_key),
        FOREIGN KEY(model_id)
            REFERENCES models(model_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(project_id)
            REFERENCES projects(project_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_tracks (
        track_id TEXT PRIMARY KEY,
        owner_project_id TEXT,
        name TEXT NOT NULL,
        target TEXT NOT NULL,
        purpose TEXT NOT NULL,
        scope TEXT NOT NULL,
        status TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        parent_track_id TEXT,
        relative_path TEXT NOT NULL,
        gt_format TEXT,
        gt_relative_path TEXT,
        gt_sha256 TEXT,
        manifest_sha256 TEXT,
        member_count INTEGER NOT NULL DEFAULT 0,
        object_count INTEGER NOT NULL DEFAULT 0,
        reservation_policy TEXT,
        created_at TEXT,
        verified_at TEXT,
        sealed_at TEXT,
        FOREIGN KEY(owner_project_id)
            REFERENCES projects(project_id)
            ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY(parent_track_id)
            REFERENCES evaluation_tracks(track_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_evaluation_tracks_target_status
    ON evaluation_tracks(target, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_track_members (
        track_id TEXT NOT NULL,
        member_index INTEGER NOT NULL,
        source_image_id TEXT NOT NULL,
        source_artifact_id TEXT,
        track_artifact_id TEXT,
        original_name TEXT,
        track_relative_path TEXT,
        sha256 TEXT NOT NULL,
        PRIMARY KEY(track_id, member_index),
        FOREIGN KEY(track_id)
            REFERENCES evaluation_tracks(track_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(source_image_id)
            REFERENCES source_images(source_image_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(source_artifact_id)
            REFERENCES image_artifacts(artifact_id)
            ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY(track_artifact_id)
            REFERENCES image_artifacts(artifact_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_track_members_source
    ON evaluation_track_members(source_image_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS reservations (
        source_image_id TEXT NOT NULL,
        track_id TEXT NOT NULL,
        reservation_type TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT,
        PRIMARY KEY(source_image_id, track_id, reservation_type),
        FOREIGN KEY(source_image_id)
            REFERENCES source_images(source_image_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(track_id)
            REFERENCES evaluation_tracks(track_id)
            ON UPDATE CASCADE ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_reservations_active_source
    ON reservations(source_image_id, active)
    """,
    """
    CREATE TABLE IF NOT EXISTS experiments (
        experiment_id TEXT PRIMARY KEY,
        owner_project_id TEXT,
        name TEXT,
        target TEXT,
        mode TEXT NOT NULL,
        track_id TEXT,
        status TEXT NOT NULL,
        protocol_json TEXT,
        protocol_sha256 TEXT,
        track_manifest_sha256 TEXT,
        created_at TEXT,
        sealed_at TEXT,
        started_at TEXT,
        finished_at TEXT,
        FOREIGN KEY(owner_project_id)
            REFERENCES projects(project_id)
            ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY(track_id)
            REFERENCES evaluation_tracks(track_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_experiments_track_status
    ON experiments(track_id, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS experiment_participants (
        experiment_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        position INTEGER,
        model_sha256 TEXT,
        independence_status TEXT NOT NULL DEFAULT 'UNKNOWN',
        overlap_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(experiment_id, model_id),
        FOREIGN KEY(experiment_id)
            REFERENCES experiments(experiment_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(model_id)
            REFERENCES models(model_id)
            ON UPDATE CASCADE ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experiment_overlap_items (
        experiment_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        source_image_id TEXT NOT NULL,
        training_dataset_id TEXT,
        training_run_id TEXT,
        reason TEXT,
        FOREIGN KEY(experiment_id, model_id)
            REFERENCES experiment_participants(experiment_id, model_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(source_image_id)
            REFERENCES source_images(source_image_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(training_dataset_id)
            REFERENCES datasets(dataset_id)
            ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY(training_run_id)
            REFERENCES training_runs(run_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_experiment_overlap_lookup
    ON experiment_overlap_items(experiment_id, model_id, source_image_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS experiment_results (
        experiment_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        metrics_json TEXT,
        result_relative_path TEXT,
        created_at TEXT,
        PRIMARY KEY(experiment_id, model_id),
        FOREIGN KEY(experiment_id, model_id)
            REFERENCES experiment_participants(experiment_id, model_id)
            ON UPDATE CASCADE ON DELETE CASCADE
    )
    """,
)


SCHEMA_V2_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS dataset_locations (
        dataset_id TEXT NOT NULL,
        location_key TEXT NOT NULL,
        project_id TEXT,
        relative_path TEXT,
        external_path TEXT,
        is_primary INTEGER NOT NULL DEFAULT 0,
        discovered_at TEXT,
        PRIMARY KEY(dataset_id, location_key),
        FOREIGN KEY(dataset_id)
            REFERENCES datasets(dataset_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(project_id)
            REFERENCES projects(project_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_dataset_locations_project
    ON dataset_locations(project_id, dataset_id)
    """,
)
