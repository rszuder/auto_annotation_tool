"""Bootstrap istniejącego Workspace do centralnego rejestru SQLite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..training.model_provenance import build_dataset_training_provenance
from .registry_rows import build_dataset_registry_rows
from .repository import RegistryRepository


@dataclass(frozen=True)
class RegisteredProject:
    project_id: str
    campaign_key: str
    folder_name: str
    display_name: str
    root: Path
    created_at: str = ""


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
            "warnings": list(self.warnings),
        }


def project_id_from_folder_name(folder_name: str) -> str:
    """Stabilny identyfikator projektu dla istniejącej struktury Workspace."""

    normalized = str(folder_name or "").strip().replace("\\", "/").casefold()
    if not normalized:
        return ""
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest().upper()
    return f"PRJ-{digest[:20]}"


def bootstrap_workspace_registry(
    workspace_dir: Path | str,
    *,
    repository: RegistryRepository | None = None,
) -> RegistryBootstrapReport:
    """Zindeksuj istniejące projekty i datasety w rejestrze SQLite.

    Operacja jest idempotentna. Nie przenosi ani nie modyfikuje datasetów.
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


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).replace("\\", "/").casefold()
    except Exception:
        return str(path).replace("\\", "/").casefold()
