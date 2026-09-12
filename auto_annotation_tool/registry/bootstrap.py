"""Bootstrap istniejącego Workspace do centralnego rejestru SQLite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from ..training.model_provenance import build_dataset_training_provenance
from ..validators import read_model_metadata_sidecar
from .registry_rows import build_dataset_registry_rows
from .repository import RegistryRepository


_RUN_ID_RE = re.compile(r"(20\d{6}_\d{6})")
_YOLO_RE = re.compile(r"yolo(?:v)?(8|11|26)([nsmlx])(?:[-_ ]?(pose))?", re.IGNORECASE)


@dataclass(frozen=True)
class RegisteredProject:
    project_id: str
    campaign_key: str
    folder_name: str
    display_name: str
    root: Path
    created_at: str = ""


@dataclass(frozen=True)
class DiscoveredTrainingRun:
    registry_run_id: str
    source_run_id: str
    project_id: str | None
    target: str
    dataset_id: str
    payload: dict[str, Any]
    history_path: Path
    parent_source_run_id: str
    parent_target_hint: str
    output_best_sha256: str
    provenance_status: str


@dataclass
class RegistryBootstrapReport:
    workspace: str
    projects_discovered: int = 0
    projects_registered: int = 0
    datasets_discovered: int = 0
    datasets_registered: int = 0
    indexed_source_rows: int = 0
    indexed_artifact_rows: int = 0
    indexed_member_rows: int = 0
    training_runs_discovered: int = 0
    training_runs_registered: int = 0
    historical_dataset_snapshots_registered: int = 0
    models_discovered: int = 0
    models_registered: int = 0
    model_locations_registered: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "projects_discovered": int(self.projects_discovered),
            "projects_registered": int(self.projects_registered),
            "datasets_discovered": int(self.datasets_discovered),
            "datasets_registered": int(self.datasets_registered),
            "indexed_source_rows": int(self.indexed_source_rows),
            "indexed_artifact_rows": int(self.indexed_artifact_rows),
            "indexed_member_rows": int(self.indexed_member_rows),
            "training_runs_discovered": int(self.training_runs_discovered),
            "training_runs_registered": int(self.training_runs_registered),
            "historical_dataset_snapshots_registered": int(
                self.historical_dataset_snapshots_registered
            ),
            "models_discovered": int(self.models_discovered),
            "models_registered": int(self.models_registered),
            "model_locations_registered": int(self.model_locations_registered),
            "warnings": list(self.warnings),
        }


def project_id_from_folder_name(folder_name: str) -> str:
    """Stabilny identyfikator projektu dla istniejącej struktury Workspace."""

    normalized = str(folder_name or "").strip().replace("\\", "/").casefold()
    if not normalized:
        return ""
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest().upper()
    return f"PRJ-{digest[:20]}"


def registry_run_id(
    source_run_id: str,
    *,
    project_id: str | None,
    target: str,
) -> str:
    """Namespaced run id; timestamp ids are not globally unique across projects."""

    source = str(source_run_id or "").strip()
    if not source:
        return ""
    scope = str(project_id or "GLOBAL").strip()
    normalized_target = _normalize_target(target) or "unknown"
    seed = f"{scope}|{normalized_target}|{source}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest().upper()
    return f"RUN-{digest[:20]}"


def model_id_from_sha256(sha256: str) -> str:
    value = str(sha256 or "").strip().lower()
    if not value:
        return ""
    return f"MODEL-{value[:20].upper()}"


def bootstrap_workspace_registry(
    workspace_dir: Path | str,
    *,
    repository: RegistryRepository | None = None,
) -> RegistryBootstrapReport:
    """Zindeksuj istniejący Workspace w rejestrze SQLite.

    Operacja jest idempotentna. Nie przenosi ani nie modyfikuje datasetów,
    historii treningów ani modeli.
    """

    workspace = Path(workspace_dir)
    repo = repository or RegistryRepository.for_workspace(workspace)
    repo.initialize()

    report = RegistryBootstrapReport(workspace=str(workspace))
    now = datetime.now(timezone.utc).isoformat()

    projects = _load_registered_projects(workspace, report)
    report.projects_discovered = len(projects)

    for project in projects:
        repo.upsert_project(
            project_id=project.project_id,
            campaign_key=project.campaign_key,
            folder_name=project.folder_name,
            display_name=project.display_name,
            created_at=project.created_at or None,
            updated_at=now,
        )
        report.projects_registered += 1

    discovered = _discover_dataset_locations(workspace, projects)
    report.datasets_discovered = len(discovered)

    for root, project in discovered:
        try:
            provenance = build_dataset_training_provenance(
                root,
                target="",
                include_content_fingerprint=True,
            )
            dataset_id = str(provenance.get("dataset_id") or "").strip()
            if not dataset_id:
                report.warnings.append(
                    f"Pominięto dataset bez dataset_id: {root}"
                )
                continue

            rows = build_dataset_registry_rows(dataset_id, root)
            relative_path, external_path = _workspace_location(workspace, root)
            location_key = _dataset_location_key(
                project_id=(project.project_id if project else None),
                relative_path=relative_path,
                external_path=external_path,
            )
            summary = repo.upsert_dataset_bundle(
                provenance=provenance,
                rows=rows,
                project_id=(project.project_id if project else None),
                location_key=location_key,
                relative_path=relative_path,
                external_path=external_path,
                is_primary=True,
                discovered_at=now,
            )
            report.datasets_registered += 1
            report.indexed_source_rows += summary.source_rows
            report.indexed_artifact_rows += summary.artifact_rows
            report.indexed_member_rows += summary.member_rows
        except Exception as exc:
            report.warnings.append(
                f"Nie udało się zindeksować datasetu {root}: "
                f"{type(exc).__name__}: {exc}"
            )

    runs = _discover_training_runs(workspace, projects, report)
    report.training_runs_discovered = len(runs)

    for run in runs:
        snapshot = _dataset_snapshot_from_run(run.payload)
        if run.dataset_id and snapshot:
            try:
                repo.upsert_dataset_snapshot(snapshot, registered_at=now)
                report.historical_dataset_snapshots_registered += 1
            except Exception as exc:
                report.warnings.append(
                    f"Nie udało się zarejestrować historycznego datasetu "
                    f"{run.dataset_id}: {type(exc).__name__}: {exc}"
                )

        repo.upsert_training_run(
            run_id=run.registry_run_id,
            project_id=run.project_id,
            target=run.target,
            dataset_id=run.dataset_id or None,
            status=str(run.payload.get("status") or ""),
            base_model=str(run.payload.get("base_model") or ""),
            config_sha256=_training_config_sha256(run.payload),
            output_relative_path=_workspace_path_text(
                workspace,
                run.payload.get("output_dir"),
            ),
            started_at=str(run.payload.get("started_at") or "") or None,
            finished_at=str(run.payload.get("finished_at") or "") or None,
            provenance_status=run.provenance_status,
        )
    report.training_runs_registered = len(runs)

    _attach_training_run_parents(repo, runs)

    model_locations = _discover_model_locations(workspace, projects)
    report.models_discovered = len(model_locations)
    model_ids: set[str] = set()
    run_links_by_sha = _run_links_by_output_sha(runs)

    for model_path, project in model_locations:
        try:
            sha = _file_sha256(model_path)
            if not sha:
                report.warnings.append(
                    f"Pominięto model bez SHA-256: {model_path}"
                )
                continue

            linked_run, link_method = _resolve_model_run(
                model_path,
                project_id=(project.project_id if project else None),
                sha256=sha,
                runs=runs,
                run_links_by_sha=run_links_by_sha,
            )
            info = _model_info(model_path)
            target = (
                linked_run.target
                if linked_run is not None
                else _infer_model_target(model_path, info)
            )
            task_type = _infer_model_task(target, info)
            yolo_family, yolo_scale = _infer_yolo_identity(
                model_path,
                info,
            )
            provenance_status = "legacy_unknown"
            run_id = None
            owner_project_id = project.project_id if project else None
            if linked_run is not None:
                run_id = linked_run.registry_run_id
                owner_project_id = linked_run.project_id or owner_project_id
                provenance_status = linked_run.provenance_status
                if link_method != "sha256":
                    provenance_status = _weaken_provenance_status(
                        provenance_status
                    )

            relative_path, external_path = _workspace_location(
                workspace,
                model_path,
            )
            location_key = _model_location_key(
                project_id=(project.project_id if project else None),
                relative_path=relative_path,
                external_path=external_path,
            )
            actual_model_id = repo.upsert_model_location(
                model_id=model_id_from_sha256(sha),
                sha256=sha,
                project_id=owner_project_id,
                run_id=run_id,
                target=target or "unknown",
                task_type=task_type or "unknown",
                yolo_family=yolo_family,
                yolo_scale=yolo_scale or "unknown",
                checkpoint_kind=_checkpoint_kind(model_path),
                provenance_status=provenance_status,
                created_at=_file_timestamp_iso(model_path),
                location_key=location_key,
                relative_path=relative_path,
                external_path=external_path,
                is_primary=bool(project is not None),
            )
            model_ids.add(actual_model_id)
            report.model_locations_registered += 1
        except Exception as exc:
            report.warnings.append(
                f"Nie udało się zindeksować modelu {model_path}: "
                f"{type(exc).__name__}: {exc}"
            )

    report.models_registered = len(model_ids)
    return report


def _load_registered_projects(
    workspace: Path,
    report: RegistryBootstrapReport,
) -> list[RegisteredProject]:
    registry_path = workspace / "campaigns_registry.json"
    if not registry_path.exists() or not registry_path.is_file():
        return []

    try:
        payload = json.loads(
            registry_path.read_text(encoding="utf-8-sig")
        )
    except Exception as exc:
        report.warnings.append(
            f"Nie udało się odczytać campaigns_registry.json: {exc}"
        )
        return []

    projects_payload = (
        payload.get("projects")
        if isinstance(payload, Mapping)
        else None
    )
    if not isinstance(projects_payload, Mapping):
        report.warnings.append(
            "campaigns_registry.json nie zawiera poprawnego pola projects."
        )
        return []

    result: list[RegisteredProject] = []
    for name, raw_data in projects_payload.items():
        data = dict(raw_data or {}) if isinstance(raw_data, Mapping) else {}
        folder_name = str(data.get("folder_name") or "").strip()
        if not folder_name:
            report.warnings.append(
                f"Projekt {name!r} nie ma folder_name; pominięto."
            )
            continue

        project_id = project_id_from_folder_name(folder_name)
        root = workspace / "9_projects" / folder_name
        if not root.exists() or not root.is_dir():
            report.warnings.append(
                f"Projekt {name!r} jest zarejestrowany, ale brak katalogu: {root}"
            )

        result.append(
            RegisteredProject(
                project_id=project_id,
                campaign_key=str(name),
                folder_name=folder_name,
                display_name=str(name),
                root=root,
                created_at=str(data.get("created_at") or ""),
            )
        )

    result.sort(key=lambda item: (item.display_name.casefold(), item.folder_name.casefold()))
    return result


def _discover_dataset_locations(
    workspace: Path,
    projects: Iterable[RegisteredProject],
) -> list[tuple[Path, RegisteredProject | None]]:
    result: list[tuple[Path, RegisteredProject | None]] = []
    seen: set[str] = set()

    def add_from(base: Path, project: RegisteredProject | None) -> None:
        for root in _iter_dataset_roots(base):
            key = _path_key(root)
            if key in seen:
                continue
            seen.add(key)
            result.append((root, project))

    add_from(workspace / "4_training_datasets", None)

    for project in projects:
        add_from(project.root / "4_training_datasets", project)

    result.sort(
        key=lambda item: (
            item[1].display_name.casefold() if item[1] else "",
            _path_key(item[0]),
        )
    )
    return result


def _iter_dataset_roots(base: Path) -> Iterable[Path]:
    if not base.exists() or not base.is_dir():
        return []

    roots: list[Path] = []
    for parent, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(
            name
            for name in dirs
            if not (Path(parent) / name).is_symlink()
        )
        if "data.yaml" in files:
            roots.append(Path(parent))
    return roots


def _discover_training_runs(
    workspace: Path,
    projects: Iterable[RegisteredProject],
    report: RegistryBootstrapReport,
) -> list[DiscoveredTrainingRun]:
    records: dict[str, DiscoveredTrainingRun] = {}

    scopes: list[tuple[Path, RegisteredProject | None]] = [
        (workspace / "5_training_runs", None)
    ]
    scopes.extend(
        (project.root / "5_training_runs", project)
        for project in projects
    )

    for root, project in scopes:
        if not root.exists() or not root.is_dir():
            continue
        for history_path in sorted(root.rglob("training_history.json")):
            if history_path.is_symlink() or not history_path.is_file():
                continue
            try:
                payload = json.loads(
                    history_path.read_text(encoding="utf-8-sig")
                )
            except Exception as exc:
                report.warnings.append(
                    f"Nie udało się odczytać historii {history_path}: {exc}"
                )
                continue

            runs_payload = payload.get("runs") if isinstance(payload, Mapping) else None
            if not isinstance(runs_payload, Mapping):
                continue

            for key, raw_run in runs_payload.items():
                if not isinstance(raw_run, Mapping):
                    continue
                run = dict(raw_run)
                source_run_id = str(run.get("id") or key or "").strip()
                if not source_run_id:
                    continue
                target = _infer_run_target(run, history_path)
                project_id = project.project_id if project else None
                reg_id = registry_run_id(
                    source_run_id,
                    project_id=project_id,
                    target=target,
                )
                snapshot = _dataset_snapshot_from_run(run)
                dataset_id = str(snapshot.get("dataset_id") or "").strip()
                parent_source = _parent_source_run_id(run)
                parent_target = _normalize_target(
                    run.get("parent_model_target")
                )
                best_sha = _run_output_best_sha(run)
                status = _run_provenance_status(
                    run,
                    parent_source_run_id=parent_source,
                )

                candidate = DiscoveredTrainingRun(
                    registry_run_id=reg_id,
                    source_run_id=source_run_id,
                    project_id=project_id,
                    target=target,
                    dataset_id=dataset_id,
                    payload=run,
                    history_path=history_path,
                    parent_source_run_id=parent_source,
                    parent_target_hint=parent_target,
                    output_best_sha256=best_sha,
                    provenance_status=status,
                )
                current = records.get(reg_id)
                if current is None or _run_record_score(candidate) > _run_record_score(current):
                    records[reg_id] = candidate

    return sorted(
        records.values(),
        key=lambda item: (
            str(item.project_id or ""),
            item.target,
            item.source_run_id,
        ),
    )


def _attach_training_run_parents(
    repo: RegistryRepository,
    runs: list[DiscoveredTrainingRun],
) -> None:
    exact: dict[tuple[str, str, str], str] = {}
    broad: dict[tuple[str, str], list[str]] = {}

    for run in runs:
        scope = str(run.project_id or "GLOBAL")
        exact[(scope, run.target, run.source_run_id)] = run.registry_run_id
        broad.setdefault((scope, run.source_run_id), []).append(
            run.registry_run_id
        )

    for run in runs:
        source_parent = run.parent_source_run_id
        if not source_parent:
            continue
        scope = str(run.project_id or "GLOBAL")
        parent_id = ""
        target_hint = run.parent_target_hint or run.target
        parent_id = exact.get((scope, target_hint, source_parent), "")
        if not parent_id:
            candidates = sorted(
                set(broad.get((scope, source_parent), []))
            )
            if len(candidates) == 1:
                parent_id = candidates[0]
        if parent_id and parent_id != run.registry_run_id:
            repo.set_training_run_parent(
                run.registry_run_id,
                parent_id,
            )


def _dataset_snapshot_from_run(run: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = run.get("training_dataset_snapshot")
    if isinstance(snapshot, Mapping) and snapshot:
        return dict(snapshot)
    embedded = run.get("dataset")
    if isinstance(embedded, Mapping) and embedded:
        return dict(embedded)
    return {}


def _infer_run_target(
    run: Mapping[str, Any],
    history_path: Path,
) -> str:
    explicit = _normalize_target(run.get("training_target"))
    if explicit:
        return explicit

    snapshot = _dataset_snapshot_from_run(run)
    snapshot_target = _normalize_target(snapshot.get("target"))
    if snapshot_target:
        return snapshot_target

    parent_name = history_path.parent.name.casefold()
    parent_target = {
        "plates": "plate",
        "plate": "plate",
        "chars": "char",
        "char": "char",
        "vehicles": "vehicle",
        "vehicle": "vehicle",
    }.get(parent_name, "")
    if parent_target:
        return parent_target

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


def _run_output_best_sha(run: Mapping[str, Any]) -> str:
    output = run.get("output_checkpoint_snapshot")
    sha = _checkpoint_sha(output, role="best")
    if sha:
        return sha

    best_path = str(run.get("best_weights") or "").strip()
    if best_path:
        try:
            path = Path(best_path)
            if path.exists() and path.is_file():
                return _file_sha256(path)
        except Exception:
            pass
    return ""


def _run_provenance_status(
    run: Mapping[str, Any],
    *,
    parent_source_run_id: str,
) -> str:
    dataset = _dataset_snapshot_from_run(run)
    input_snapshot = run.get("input_checkpoint_snapshot")
    output_snapshot = run.get("output_checkpoint_snapshot")

    has_frozen_metadata = bool(
        dataset
        or isinstance(input_snapshot, Mapping)
        or isinstance(output_snapshot, Mapping)
    )
    if not has_frozen_metadata:
        return "legacy_unknown"

    dataset_id = str(dataset.get("dataset_id") or "").strip()
    dataset_split = str(dataset.get("split_sha256") or "").strip()
    dataset_manifest = str(dataset.get("manifest_sha256") or "").strip()
    dataset_yaml = str(dataset.get("data_yaml_sha256") or "").strip()
    dataset_ok = bool(
        dataset_id
        and dataset_split
        and (dataset_manifest or dataset_yaml)
    )

    input_ok = bool(_checkpoint_sha(input_snapshot))
    output_ok = bool(_checkpoint_sha(output_snapshot, role="best"))

    status = "complete" if dataset_ok and input_ok and output_ok else "partial"

    lineage_mode = str(run.get("lineage_mode") or "new").strip().casefold()
    if lineage_mode == "fine_tune" and not parent_source_run_id:
        status = "partial"
    return status


def _run_record_score(run: DiscoveredTrainingRun) -> tuple[int, int, int]:
    status_score = {
        "complete": 3,
        "partial": 2,
        "legacy_partial": 1,
        "legacy_unknown": 0,
    }.get(run.provenance_status, 0)
    return (
        status_score,
        1 if run.output_best_sha256 else 0,
        len(run.payload),
    )


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


def _discover_model_locations(
    workspace: Path,
    projects: Iterable[RegisteredProject],
) -> list[tuple[Path, RegisteredProject | None]]:
    result: list[tuple[Path, RegisteredProject | None]] = []
    seen: set[str] = set()

    scopes: list[tuple[Path, RegisteredProject | None]] = [
        (workspace / "6_models", None)
    ]
    scopes.extend(
        (project.root / "6_models", project)
        for project in projects
    )

    for root, project in scopes:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.rglob("*.pt")):
            if path.is_symlink() or not path.is_file():
                continue
            key = _path_key(path)
            if key in seen:
                continue
            seen.add(key)
            result.append((path, project))

    return result


def _run_links_by_output_sha(
    runs: list[DiscoveredTrainingRun],
) -> dict[str, list[DiscoveredTrainingRun]]:
    result: dict[str, list[DiscoveredTrainingRun]] = {}
    for run in runs:
        sha = str(run.output_best_sha256 or "").strip().lower()
        if sha:
            result.setdefault(sha, []).append(run)
    return result


def _resolve_model_run(
    model_path: Path,
    *,
    project_id: str | None,
    sha256: str,
    runs: list[DiscoveredTrainingRun],
    run_links_by_sha: Mapping[str, list[DiscoveredTrainingRun]],
) -> tuple[DiscoveredTrainingRun | None, str]:
    sha_matches = list(run_links_by_sha.get(sha256.lower(), []))
    unique_sha = {
        run.registry_run_id: run
        for run in sha_matches
    }
    if len(unique_sha) == 1:
        return next(iter(unique_sha.values())), "sha256"

    match = _RUN_ID_RE.search(model_path.name)
    if not match:
        return None, ""

    source_run_id = match.group(1)
    same_scope = [
        run
        for run in runs
        if run.source_run_id == source_run_id
        and run.project_id == project_id
    ]
    if len(same_scope) == 1:
        return same_scope[0], "filename"

    all_matches = [
        run
        for run in runs
        if run.source_run_id == source_run_id
    ]
    unique_all = {
        run.registry_run_id: run
        for run in all_matches
    }
    if len(unique_all) == 1:
        return next(iter(unique_all.values())), "filename"

    return None, ""


def _model_info(model_path: Path) -> dict[str, Any]:
    try:
        metadata = read_model_metadata_sidecar(model_path)
    except Exception:
        metadata = None
    if metadata is not None and len(metadata) >= 3:
        info = metadata[2]
        if isinstance(info, Mapping):
            return dict(info)
    return {}


def _infer_model_target(
    model_path: Path,
    info: Mapping[str, Any],
) -> str:
    parts = {str(part).casefold() for part in model_path.parts}
    name = model_path.name.casefold()

    if "plates" in parts or "plate" in parts or "pose" in parts:
        return "plate"
    if "chars" in parts or "char" in parts:
        return "char"
    if "vehicles" in parts or "vehicle" in parts:
        return "vehicle"
    if name.startswith("plate_"):
        return "plate"
    if name.startswith("char_"):
        return "char"
    if name.startswith("vehicle_"):
        return "vehicle"

    task = str(info.get("task") or info.get("type") or "").strip().casefold()
    if task == "pose":
        return "plate"
    return "unknown"


def _infer_model_task(
    target: str,
    info: Mapping[str, Any],
) -> str:
    explicit = str(info.get("task") or info.get("type") or "").strip().casefold()
    if explicit in {"pose", "detect"}:
        return explicit
    if target == "plate":
        return "pose"
    if target in {"char", "vehicle"}:
        return "detect"
    return "unknown"


def _infer_yolo_identity(
    model_path: Path,
    info: Mapping[str, Any],
) -> tuple[str, str]:
    family = str(info.get("yolo_family") or "").strip()
    scale = str(
        info.get("yolo_size")
        or info.get("model_scale")
        or ""
    ).strip().casefold()
    if family and scale in {"n", "s", "m", "l", "x"}:
        return family, scale

    texts = [
        str(info.get("architecture_label") or ""),
        str(info.get("yolo_variant") or ""),
        str(info.get("source_architecture_label") or ""),
        str(info.get("source_model_name") or ""),
        model_path.name,
    ]
    for text in texts:
        match = _YOLO_RE.search(text)
        if not match:
            continue
        version = str(match.group(1))
        parsed_scale = str(match.group(2)).casefold()
        parsed_family = f"YOLOv{version}" if version == "8" else f"YOLO{version}"
        return family or parsed_family, scale or parsed_scale

    return family, scale or "unknown"


def _checkpoint_kind(model_path: Path) -> str:
    parts = {str(part).casefold() for part in model_path.parts}
    if "base" in parts:
        return "base"
    if "trained" in parts:
        return "trained_export"
    return "model"


def _weaken_provenance_status(status: str) -> str:
    current = str(status or "").strip().casefold()
    if current == "complete":
        return "partial"
    if current in {"partial", "legacy_partial"}:
        return current
    return "legacy_unknown"


def _workspace_path_text(
    workspace: Path,
    value: Any,
) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw)
    except Exception:
        return raw
    relative, external = _workspace_location(workspace, path)
    return str(relative or external or raw)


def _workspace_location(
    workspace: Path,
    path: Path,
) -> tuple[str | None, str | None]:
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
    seed = "|".join(
        (
            str(project_id or "GLOBAL"),
            str(relative_path or ""),
            str(external_path or ""),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest().upper()
    return f"DLOC-{digest[:24]}"


def _model_location_key(
    *,
    project_id: str | None,
    relative_path: str | None,
    external_path: str | None,
) -> str:
    seed = "|".join(
        (
            str(project_id or "GLOBAL"),
            str(relative_path or ""),
            str(external_path or ""),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest().upper()
    return f"MLOC-{digest[:24]}"


def _file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except Exception:
        return ""
    return digest.hexdigest()


def _file_timestamp_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()
    except Exception:
        return None


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).replace("\\", "/").casefold()
    except Exception:
        return str(path).replace("\\", "/").casefold()
