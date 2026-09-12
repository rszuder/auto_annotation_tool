"""Bieżąca synchronizacja nowych treningów z lokalnym rejestrem SQLite.

Moduł jest celowo best-effort z punktu widzenia treningu: awaria rejestru nie
może przerwać treningu ani uszkodzić jego dotychczasowej historii JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from ..config import CONFIG
from ..training.model_provenance import build_dataset_training_provenance
from ..validators import read_model_metadata_sidecar
from .bootstrap import (
    model_id_from_sha256,
    project_id_from_folder_name,
    registry_run_id,
)
from .registry_rows import build_dataset_registry_rows
from .repository import RegistryRepository


_RUN_ID_RE = re.compile(r"(20\d{6}_\d{6})")
_YOLO_RE = re.compile(r"yolo(?:v)?(8|11|26)([nsmlx])(?:[-_ ]?(pose))?", re.IGNORECASE)
_INDEXED_DATASET_LOCATIONS: set[tuple[str, str, str]] = set()
_FILE_SHA_CACHE: dict[tuple[str, int, int], str] = {}


@dataclass(frozen=True)
class RuntimeRegistrySyncResult:
    skipped: bool = False
    registry_run_id: str = ""
    dataset_id: str = ""
    model_id: str = ""
    warnings: tuple[str, ...] = ()


def sync_training_run(
    history_dir: Path | str,
    run_like: Any,
    *,
    workspace_dir: Path | str | None = None,
) -> RuntimeRegistrySyncResult:
    """Zapisz aktualny stan jednego runu do centralnego rejestru.

    Synchronizacja obejmuje bieżący snapshot datasetu oraz ``best.pt``, jeśli
    został już zapisany. Runy spoza aktywnego Workspace są ignorowane, dzięki
    czemu testowe i tymczasowe historie nie tworzą wpisów w bazie użytkownika.
    """

    run = _run_dict(run_like)
    source_run_id = str(run.get("id") or "").strip()
    if not source_run_id:
        return RuntimeRegistrySyncResult(skipped=True)

    workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
    history = Path(history_dir)
    if not _is_within(history, workspace):
        return RuntimeRegistrySyncResult(skipped=True)

    repo = RegistryRepository.for_workspace(workspace)
    repo.initialize()
    now = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []

    project_id, project_folder = _ensure_runtime_project(
        repo,
        workspace,
        history,
        updated_at=now,
    )
    target = _infer_run_target(run, history)
    reg_run_id = registry_run_id(
        source_run_id,
        project_id=project_id,
        target=target,
    )

    snapshot = _dataset_snapshot_from_run(run)
    dataset_id = str(snapshot.get("dataset_id") or "").strip()
    if dataset_id:
        repo.upsert_dataset_snapshot(snapshot, registered_at=now)
        dataset_warning = _index_current_dataset_if_matching(
            repo,
            workspace,
            run,
            snapshot,
            target=target,
            project_id=project_id,
            registered_at=now,
        )
        if dataset_warning:
            warnings.append(dataset_warning)

    provenance_status = _run_provenance_status(run)
    repo.upsert_training_run(
        run_id=reg_run_id,
        project_id=project_id,
        target=target,
        dataset_id=dataset_id or None,
        status=str(run.get("status") or ""),
        base_model=str(run.get("base_model") or ""),
        config_sha256=_training_config_sha256(run),
        output_relative_path=_workspace_path_text(
            workspace,
            run.get("output_dir"),
        ),
        started_at=str(run.get("started_at") or "") or None,
        finished_at=str(run.get("finished_at") or "") or None,
        provenance_status=provenance_status,
        replace_provenance_status=True,
    )

    parent_source_id = _parent_source_run_id(run)
    if parent_source_id:
        parent_target = _normalize_target(run.get("parent_model_target")) or target
        parent_registry_id = registry_run_id(
            parent_source_id,
            project_id=project_id,
            target=parent_target,
        )
        repo.set_training_run_parent(reg_run_id, parent_registry_id)

    model_id = _register_best_checkpoint(
        repo,
        workspace,
        run,
        registry_run_id_value=reg_run_id,
        project_id=project_id,
        target=target,
        run_provenance_status=provenance_status,
    )

    return RuntimeRegistrySyncResult(
        skipped=False,
        registry_run_id=reg_run_id,
        dataset_id=dataset_id,
        model_id=model_id,
        warnings=tuple(warnings),
    )


def register_exported_model(
    history_dir: Path | str,
    run_like: Any,
    model_path: Path | str,
    *,
    target: str = "",
    workspace_dir: Path | str | None = None,
) -> str:
    """Dodaj lokalizację wyeksportowanej kopii modelu bez tworzenia duplikatu modelu."""

    run = _run_dict(run_like)
    workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
    history = Path(history_dir)
    path = Path(model_path)
    if not _is_within(history, workspace) or not path.exists() or not path.is_file():
        return ""

    sync_result = sync_training_run(
        history,
        run,
        workspace_dir=workspace,
    )
    if sync_result.skipped:
        return ""

    repo = RegistryRepository.for_workspace(workspace)
    now = datetime.now(timezone.utc).isoformat()
    model_project_id, _folder = _ensure_runtime_project(
        repo,
        workspace,
        history,
        updated_at=now,
    )
    resolved_target = _normalize_target(target) or _infer_run_target(run, history)
    sha = _file_sha256(path)
    if not sha:
        return ""

    provenance_status = _run_provenance_status(run)
    frozen_sha = _checkpoint_sha(run.get("output_checkpoint_snapshot"), role="best")
    if frozen_sha and frozen_sha != sha:
        provenance_status = "partial"
    elif str(run.get("status") or "").strip().casefold() == "completed" and not frozen_sha:
        provenance_status = "partial"

    info = _model_info(path)
    family, scale = _infer_yolo_identity(path, info, run)
    relative_path, external_path = _workspace_location(workspace, path)
    location_project_id = _project_id_for_path(workspace, path)

    return repo.upsert_model_location(
        model_id=model_id_from_sha256(sha),
        sha256=sha,
        project_id=model_project_id,
        location_project_id=location_project_id,
        run_id=sync_result.registry_run_id,
        target=resolved_target,
        task_type=_infer_task_type(resolved_target, info),
        yolo_family=family,
        yolo_scale=scale or "unknown",
        checkpoint_kind="trained_export",
        provenance_status=provenance_status,
        created_at=_file_timestamp_iso(path),
        location_key=_model_location_key(
            project_id=location_project_id,
            relative_path=relative_path,
            external_path=external_path,
        ),
        relative_path=relative_path,
        external_path=external_path,
        is_primary=True,
    )


def _run_dict(run_like: Any) -> dict[str, Any]:
    if isinstance(run_like, Mapping):
        return dict(run_like)
    to_dict = getattr(run_like, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        return dict(value or {}) if isinstance(value, Mapping) else {}
    try:
        return dict(vars(run_like))
    except Exception:
        return {}


def _ensure_runtime_project(
    repo: RegistryRepository,
    workspace: Path,
    history_dir: Path,
    *,
    updated_at: str,
) -> tuple[str | None, str]:
    try:
        relative = history_dir.resolve().relative_to(workspace.resolve())
    except Exception:
        return None, ""

    parts = list(relative.parts)
    if len(parts) < 2 or str(parts[0]).casefold() != "9_projects":
        return None, ""

    folder_name = str(parts[1])
    project_id = project_id_from_folder_name(folder_name)
    campaign_key = folder_name
    display_name = folder_name
    created_at = None

    registry_path = workspace / "campaigns_registry.json"
    if registry_path.exists() and registry_path.is_file():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8-sig"))
            projects = payload.get("projects") if isinstance(payload, Mapping) else None
            if isinstance(projects, Mapping):
                for name, raw in projects.items():
                    data = dict(raw or {}) if isinstance(raw, Mapping) else {}
                    if str(data.get("folder_name") or "").casefold() != folder_name.casefold():
                        continue
                    campaign_key = str(name)
                    display_name = str(name)
                    created_at = str(data.get("created_at") or "") or None
                    break
        except Exception:
            pass

    repo.upsert_project(
        project_id=project_id,
        campaign_key=campaign_key,
        folder_name=folder_name,
        display_name=display_name,
        created_at=created_at,
        updated_at=updated_at,
    )
    return project_id, folder_name


def _index_current_dataset_if_matching(
    repo: RegistryRepository,
    workspace: Path,
    run: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    target: str,
    project_id: str | None,
    registered_at: str,
) -> str:
    dataset_id = str(snapshot.get("dataset_id") or "").strip()
    root = _resolve_dataset_root(workspace, run, snapshot)
    if not dataset_id or root is None or not (root / "data.yaml").is_file():
        return ""

    relative_path, external_path = _workspace_location(workspace, root)
    location_key = _dataset_location_key(
        project_id=project_id,
        relative_path=relative_path,
        external_path=external_path,
    )
    cache_key = (_path_key(workspace), dataset_id, location_key)
    if cache_key in _INDEXED_DATASET_LOCATIONS:
        return ""

    current = build_dataset_training_provenance(
        root,
        target=target,
        include_content_fingerprint=True,
    )
    current_id = str(current.get("dataset_id") or "").strip()
    if current_id != dataset_id:
        return (
            "Bieżąca zawartość datasetu nie odpowiada zamrożonemu snapshotowi "
            f"runu: snapshot={dataset_id}, current={current_id or '[BRAK]'}; "
            "nie zapisano członkostwa plików pod historycznym dataset_id."
        )

    rows = build_dataset_registry_rows(dataset_id, root)
    repo.upsert_dataset_bundle(
        provenance=current,
        rows=rows,
        project_id=project_id,
        location_key=location_key,
        relative_path=relative_path,
        external_path=external_path,
        is_primary=True,
        discovered_at=registered_at,
    )
    _INDEXED_DATASET_LOCATIONS.add(cache_key)
    return ""


def _resolve_dataset_root(
    workspace: Path,
    run: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> Path | None:
    for raw in (
        run.get("dataset_path"),
        snapshot.get("local_path_hint"),
        snapshot.get("data_yaml"),
    ):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            path = Path(text)
        except Exception:
            continue
        if not path.is_absolute():
            workspace_candidate = workspace / path
            path = workspace_candidate if workspace_candidate.exists() else path
        if path.name.casefold() == "data.yaml":
            path = path.parent
        try:
            if path.exists() and path.is_dir():
                return path
        except Exception:
            continue
    return None


def _dataset_snapshot_from_run(run: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = run.get("training_dataset_snapshot")
    if isinstance(snapshot, Mapping) and snapshot:
        return dict(snapshot)
    snapshot = run.get("training_dataset_input_snapshot")
    if isinstance(snapshot, Mapping) and snapshot:
        return dict(snapshot)
    return {}


def _run_provenance_status(run: Mapping[str, Any]) -> str:
    dataset = _dataset_snapshot_from_run(run)
    input_snapshot = run.get("input_checkpoint_snapshot")
    output_snapshot = run.get("output_checkpoint_snapshot")

    if not dataset and not isinstance(input_snapshot, Mapping):
        return "legacy_unknown"

    dataset_status = str(dataset.get("provenance_status") or "").strip().casefold()
    dataset_ok = bool(
        str(dataset.get("dataset_id") or "").strip()
        and str(dataset.get("split_sha256") or "").strip()
        and str(dataset.get("manifest_sha256") or "").strip()
        and dataset_status not in {"partial", "legacy_partial", "legacy_unknown"}
    )
    input_ok = bool(_checkpoint_sha(input_snapshot))
    status = "complete" if dataset_ok and input_ok else "partial"

    lineage_mode = str(run.get("lineage_mode") or "new").strip().casefold()
    if lineage_mode == "fine_tune" and not _parent_source_run_id(run):
        status = "partial"

    run_status = str(run.get("status") or "").strip().casefold()
    if run_status == "completed":
        output_status = (
            str(output_snapshot.get("provenance_status") or "").strip().casefold()
            if isinstance(output_snapshot, Mapping)
            else ""
        )
        if not _checkpoint_sha(output_snapshot, role="best"):
            status = "partial"
        elif output_status in {"partial", "legacy_partial", "legacy_unknown"}:
            status = "partial"

    return status


def _parent_source_run_id(run: Mapping[str, Any]) -> str:
    explicit = str(run.get("parent_run_id") or "").strip()
    if explicit:
        return explicit
    for key in ("parent_model_path", "parent_model_name"):
        match = _RUN_ID_RE.search(str(run.get(key) or ""))
        if match:
            return match.group(1)
    return ""


def _checkpoint_sha(snapshot: Any, *, role: str = "") -> str:
    if not isinstance(snapshot, Mapping):
        return ""
    if role:
        nested = snapshot.get(role)
        if isinstance(nested, Mapping):
            value = str(nested.get("sha256") or "").strip().lower()
            if value:
                return value
    for key in (
        f"{role}_checkpoint_sha256" if role else "",
        "sha256",
        "checkpoint_sha256",
        "best_checkpoint_sha256",
    ):
        if not key:
            continue
        value = str(snapshot.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _register_best_checkpoint(
    repo: RegistryRepository,
    workspace: Path,
    run: Mapping[str, Any],
    *,
    registry_run_id_value: str,
    project_id: str | None,
    target: str,
    run_provenance_status: str,
) -> str:
    raw_path = str(run.get("best_weights") or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return ""

    sha = _file_sha256(path)
    if not sha:
        return ""

    model_status = run_provenance_status
    frozen_sha = _checkpoint_sha(run.get("output_checkpoint_snapshot"), role="best")
    if frozen_sha and frozen_sha != sha:
        model_status = "partial"
    elif str(run.get("status") or "").strip().casefold() == "completed" and not frozen_sha:
        model_status = "partial"

    info = _model_info(path)
    family, scale = _infer_yolo_identity(path, info, run)
    task_type = _infer_task_type(target, info)
    relative_path, external_path = _workspace_location(workspace, path)
    location_key = _model_location_key(
        project_id=project_id,
        relative_path=relative_path,
        external_path=external_path,
    )

    return repo.upsert_model_location(
        model_id=model_id_from_sha256(sha),
        sha256=sha,
        project_id=project_id,
        location_project_id=_project_id_for_path(workspace, path),
        run_id=registry_run_id_value,
        target=target,
        task_type=task_type,
        yolo_family=family,
        yolo_scale=scale or "unknown",
        checkpoint_kind="best_checkpoint",
        provenance_status=model_status,
        created_at=_file_timestamp_iso(path),
        location_key=location_key,
        relative_path=relative_path,
        external_path=external_path,
        is_primary=True,
    )


def _model_info(path: Path) -> dict[str, Any]:
    try:
        metadata = read_model_metadata_sidecar(path)
    except Exception:
        metadata = None
    if metadata is not None and len(metadata) >= 3 and isinstance(metadata[2], Mapping):
        return dict(metadata[2])
    return {}


def _infer_yolo_identity(
    model_path: Path,
    info: Mapping[str, Any],
    run: Mapping[str, Any],
) -> tuple[str, str]:
    family = str(info.get("yolo_family") or "").strip()
    scale = str(info.get("yolo_size") or info.get("model_scale") or "").strip().casefold()
    if family and scale in {"n", "s", "m", "l", "x"}:
        return family, scale

    texts = (
        str(info.get("architecture_label") or ""),
        str(info.get("yolo_variant") or ""),
        str(info.get("source_architecture_label") or ""),
        str(info.get("source_model_name") or ""),
        str(run.get("base_model") or ""),
        model_path.name,
    )
    for text in texts:
        match = _YOLO_RE.search(text)
        if not match:
            continue
        version = str(match.group(1))
        parsed_scale = str(match.group(2)).casefold()
        parsed_family = f"YOLOv{version}" if version == "8" else f"YOLO{version}"
        return family or parsed_family, scale or parsed_scale
    return family, scale or "unknown"


def _infer_task_type(target: str, info: Mapping[str, Any]) -> str:
    explicit = str(info.get("task") or info.get("type") or "").strip().casefold()
    if explicit in {"pose", "detect"}:
        return explicit
    if target == "plate":
        return "pose"
    if target in {"char", "vehicle"}:
        return "detect"
    return "unknown"


def _infer_run_target(run: Mapping[str, Any], history_dir: Path) -> str:
    explicit = _normalize_target(run.get("training_target"))
    if explicit:
        return explicit

    snapshot = _dataset_snapshot_from_run(run)
    snapshot_target = _normalize_target(snapshot.get("target"))
    if snapshot_target:
        return snapshot_target

    for part in reversed(history_dir.parts):
        normalized = _normalize_target(part)
        if normalized:
            return normalized

    text = " ".join(
        str(run.get(key) or "")
        for key in ("dataset_path", "base_model", "name", "output_dir")
    ).casefold()
    if "pose" in text or "plate" in text or "tablic" in text:
        return "plate"
    if "char" in text or "znak" in text or "ocr" in text:
        return "char"
    if "vehicle" in text or "pojazd" in text or "samoch" in text:
        return "vehicle"
    return "unknown"


def _normalize_target(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    if raw in {"plate", "plates", "pose", "mt"}:
        return "plate"
    if raw in {"char", "chars", "character", "characters", "mz"}:
        return "char"
    if raw in {"vehicle", "vehicles"}:
        return "vehicle"
    return ""


def _training_config_sha256(run: Mapping[str, Any]) -> str:
    payload = {
        key: run.get(key)
        for key in (
            "base_model",
            "epochs",
            "batch_size",
            "img_size",
            "device",
            "lr0",
            "lineage_mode",
            "parent_run_id",
            "parent_model_name",
            "parent_model_target",
            "training_target",
            "dataset_preparation",
            "input_checkpoint_snapshot",
        )
        if key in run
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _workspace_path_text(workspace: Path, value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw)
    except Exception:
        return raw
    relative, external = _workspace_location(workspace, path)
    return str(relative or external or raw)


def _workspace_location(workspace: Path, path: Path) -> tuple[str | None, str | None]:
    try:
        relative = path.resolve().relative_to(workspace.resolve()).as_posix()
        return relative, None
    except Exception:
        try:
            return None, str(path.resolve())
        except Exception:
            return None, str(path)


def _dataset_location_key(
    *,
    project_id: str | None,
    relative_path: str | None,
    external_path: str | None,
) -> str:
    seed = "|".join((str(project_id or "GLOBAL"), str(relative_path or ""), str(external_path or "")))
    return f"DLOC-{hashlib.sha256(seed.encode('utf-8')).hexdigest().upper()[:24]}"


def _model_location_key(
    *,
    project_id: str | None,
    relative_path: str | None,
    external_path: str | None,
) -> str:
    seed = "|".join((str(project_id or "GLOBAL"), str(relative_path or ""), str(external_path or "")))
    return f"MLOC-{hashlib.sha256(seed.encode('utf-8')).hexdigest().upper()[:24]}"


def _project_id_for_path(workspace: Path, path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(workspace.resolve())
    except Exception:
        return None
    parts = list(relative.parts)
    if len(parts) >= 2 and str(parts[0]).casefold() == "9_projects":
        return project_id_from_folder_name(str(parts[1]))
    return None


def _file_sha256(path: Path) -> str:
    try:
        resolved = str(path.resolve())
        stat = path.stat()
        cache_key = (resolved, int(stat.st_size), int(stat.st_mtime_ns))
    except Exception:
        return ""
    cached = _FILE_SHA_CACHE.get(cache_key)
    if cached:
        return cached
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except Exception:
        return ""
    value = digest.hexdigest()
    _FILE_SHA_CACHE[cache_key] = value
    return value


def _file_timestamp_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).replace("\\", "/").casefold()
    except Exception:
        return str(path).replace("\\", "/").casefold()
