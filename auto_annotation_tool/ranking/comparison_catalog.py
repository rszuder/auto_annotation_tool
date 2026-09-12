"""Wspólny katalog modeli do porównań projektowych i swobodnych."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import CONFIG
from ..registry.bootstrap import project_id_from_folder_name
from ..registry.repository import RegistryRepository

SCOPE_PROJECT = "Projekt"
SCOPE_WORKSPACE = "Globalne"


@dataclass(frozen=True)
class ModelComparisonCandidate:
    model_id: str
    sha256: str
    target: str
    path: Path
    scope: str
    owner_project_id: str = ""
    owner_project_name: str = ""
    location_project_id: str = ""
    location_project_name: str = ""
    run_id: str = ""
    yolo_family: str = ""
    yolo_scale: str = "unknown"
    provenance_status: str = "legacy_unknown"


def active_project_id_from_root(
    project_root: Path | str | None,
) -> str:
    if project_root is None:
        return ""
    try:
        folder_name = Path(project_root).name
    except Exception:
        return ""
    return project_id_from_folder_name(folder_name)


def normalize_comparison_scope(
    scope: str | None,
    *,
    has_active_project: bool,
) -> str:
    raw = str(scope or "").strip()
    if raw == SCOPE_PROJECT and has_active_project:
        return SCOPE_PROJECT
    return SCOPE_WORKSPACE


def comparison_scope_label(
    scope: str | None,
    target: str | None,
) -> str:
    normalized_target = _normalize_target(target)
    short_name = {
        "plate": "MT",
        "char": "MZ",
        "vehicle": "MP",
    }.get(normalized_target, "modeli")
    if str(scope or "").strip() == SCOPE_PROJECT:
        return f"Projektowe {short_name}"
    return f"Workspace {short_name}"


class ModelComparisonCatalog:
    """Jedno źródło kandydatów dla projektu i trybu swobodnego.

    SQLite przechowuje logiczną tożsamość modelu. Ta klasa wybiera jedną
    istniejącą fizyczną lokalizację dla każdego ``model_id``:
    - w projekcie preferuje kopię z aktywnego projektu,
    - w trybie Workspace preferuje lokalizację globalną,
    - ten sam model (ten sam SHA/model_id) pojawia się tylko raz.
    """

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        repository: RegistryRepository | None = None,
    ) -> None:
        self.workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
        self.repository = repository or RegistryRepository.for_workspace(
            self.workspace
        )
        self.repository.initialize()

    def list_candidates(
        self,
        *,
        target: str,
        scope: str = SCOPE_WORKSPACE,
        active_project_root: Path | str | None = None,
        active_project_id: str | None = None,
        include_missing: bool = False,
    ) -> list[ModelComparisonCandidate]:
        normalized_target = _normalize_target(target)
        if not normalized_target:
            return []

        resolved_project_id = str(
            active_project_id
            or active_project_id_from_root(active_project_root)
            or ""
        ).strip()

        requested_scope = str(scope or "").strip()
        if (
            requested_scope == SCOPE_PROJECT
            and not resolved_project_id
        ):
            # Jawne żądanie zakresu projektowego nie może po cichu
            # rozszerzyć się do całego Workspace.
            return []

        resolved_scope = normalize_comparison_scope(
            requested_scope,
            has_active_project=bool(resolved_project_id),
        )

        rows = self.repository.list_model_comparison_rows(
            target=normalized_target,
            project_id=(
                resolved_project_id
                if resolved_scope == SCOPE_PROJECT
                else None
            ),
        )

        grouped: dict[str, list[Any]] = {}
        for row in rows:
            model_id = str(row["model_id"] or "").strip()
            if not model_id:
                continue
            grouped.setdefault(model_id, []).append(row)

        candidates: list[ModelComparisonCandidate] = []
        for model_id, model_rows in grouped.items():
            usable: list[tuple[tuple[Any, ...], Any, Path]] = []
            for row in model_rows:
                path = self._resolve_location(row)
                exists = bool(path and path.exists() and path.is_file())
                if not exists and not include_missing:
                    continue
                if path is None:
                    continue
                usable.append(
                    (
                        self._location_priority(
                            row,
                            scope=resolved_scope,
                            active_project_id=resolved_project_id,
                            exists=exists,
                        ),
                        row,
                        path,
                    )
                )
            if not usable:
                continue
            usable.sort(key=lambda item: item[0])
            _priority, row, path = usable[0]

            candidates.append(
                ModelComparisonCandidate(
                    model_id=model_id,
                    sha256=str(row["sha256"] or "").strip().lower(),
                    target=str(row["target"] or "").strip().lower(),
                    path=path,
                    scope=resolved_scope,
                    owner_project_id=str(
                        row["owner_project_id"] or ""
                    ).strip(),
                    owner_project_name=str(
                        row["owner_project_name"] or ""
                    ).strip(),
                    location_project_id=str(
                        row["location_project_id"] or ""
                    ).strip(),
                    location_project_name=str(
                        row["location_project_name"] or ""
                    ).strip(),
                    run_id=str(row["run_id"] or "").strip(),
                    yolo_family=str(
                        row["yolo_family"] or ""
                    ).strip(),
                    yolo_scale=str(
                        row["yolo_scale"] or "unknown"
                    ).strip(),
                    provenance_status=str(
                        row["provenance_status"]
                        or "legacy_unknown"
                    ).strip(),
                )
            )

        candidates.sort(
            key=lambda item: (
                item.owner_project_name.casefold(),
                item.yolo_family.casefold(),
                item.yolo_scale.casefold(),
                item.model_id,
            )
        )
        return candidates

    def _resolve_location(self, row) -> Path | None:
        relative = str(row["relative_path"] or "").strip()
        external = str(row["external_path"] or "").strip()
        if relative:
            return self.workspace / Path(relative)
        if external:
            return Path(external)
        return None

    @staticmethod
    def _location_priority(
        row,
        *,
        scope: str,
        active_project_id: str,
        exists: bool,
    ) -> tuple[Any, ...]:
        location_project_id = str(
            row["location_project_id"] or ""
        ).strip()
        is_primary = bool(int(row["is_primary"] or 0))
        relative = str(row["relative_path"] or "")
        external = str(row["external_path"] or "")
        location_key = str(row["location_key"] or "")

        if scope == SCOPE_PROJECT:
            scope_rank = (
                0
                if location_project_id == active_project_id
                else 1
            )
        else:
            # Tryb swobodny/Workspace ma używać stabilnej kopii globalnej,
            # jeśli ta sama logiczna waga występuje też w projekcie.
            scope_rank = 0 if not location_project_id else 1

        return (
            0 if exists else 1,
            scope_rank,
            0 if is_primary else 1,
            relative.casefold(),
            external.casefold(),
            location_key.casefold(),
        )


def _normalize_target(target: str | None) -> str:
    raw = str(target or "").strip().lower()
    if raw in {"plate", "plates", "pose", "mt"}:
        return "plate"
    if raw in {"char", "chars", "character", "characters", "mz"}:
        return "char"
    if raw in {"vehicle", "vehicles", "mp"}:
        return "vehicle"
    return ""
