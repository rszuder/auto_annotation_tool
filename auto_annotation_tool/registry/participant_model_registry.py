"""Obsługa modeli uczestniczących: odświeżanie rejestru i ręczna rejestracja checkpointu."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from ..validators import read_model_metadata_sidecar
from .bootstrap import bootstrap_workspace_registry, model_id_from_sha256
from .repository import RegistryRepository


_ATTESTATION_SCHEMA = "alpr.manual_model_run_attestation.v1"

_FULL_PROVENANCE = {"complete", "known"}
_YOLO_RE = re.compile(r"yolo(?:v)?(?P<version>8|11|26)(?P<scale>[nsmlx])", re.IGNORECASE)

@dataclass(frozen=True)
class ParticipantModelRegistration:
    model_id: str
    sha256: str
    run_id: str
    dataset_id: str
    target: str
    provenance_status: str
    model_path: str



@dataclass(frozen=True)
class ParticipantModelUnregistration:
    model_id: str
    sha256: str
    checkpoint_kind: str
    model_paths: tuple[str, ...]
    unregistered_at: str


def refresh_workspace_model_registry(
    workspace_dir: Path | str,
    *,
    repository: RegistryRepository | None = None,
):
    """Idempotentnie odśwież centralny rejestr Workspace."""
    return bootstrap_workspace_registry(
        Path(workspace_dir),
        repository=repository,
    )


def eligible_training_runs(
    repository: RegistryRepository,
    target: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in repository.list_training_runs_for_target(
        str(target or "").strip().lower()
    ):
        row = dict(raw)
        provenance = str(row.get("provenance_status") or "").strip().lower()
        if provenance not in _FULL_PROVENANCE:
            continue
        if not str(row.get("dataset_id") or "").strip():
            continue
        result.append(row)
    return result


def register_existing_participant_model(
    workspace_dir: Path | str,
    model_path: Path | str,
    *,
    run_id: str,
    target: str,
    repository: RegistryRepository | None = None,
) -> ParticipantModelRegistration:
    """Powiąż istniejący checkpoint z wybranym runem.

    Ręczne powiązanie zapisujemy jako ``known``, nie ``complete``.
    """
    workspace = Path(workspace_dir)
    path = Path(model_path)
    if not path.exists() or not path.is_file():
        raise ValueError(f"Brak pliku modelu: {path}")
    if path.suffix.lower() != ".pt":
        raise ValueError("Można rejestrować wyłącznie checkpointy .pt.")

    repo = repository or RegistryRepository.for_workspace(workspace)
    repo.initialize()

    clean_run_id = str(run_id or "").strip()
    run = repo.get_training_run(clean_run_id)
    if run is None:
        raise ValueError(f"Nie znaleziono runu: {clean_run_id}")
    run = dict(run)

    clean_target = str(target or "").strip().lower()
    run_target = str(run.get("target") or "").strip().lower()
    if run_target != clean_target:
        raise ValueError(
            f"Wybrany run ma target {run_target or '-'}, "
            f"a tor ma target {clean_target or '-'}."
        )

    provenance = str(run.get("provenance_status") or "").strip().lower()
    if provenance not in _FULL_PROVENANCE:
        raise ValueError(
            "Wybrany run nie ma wystarczającego provenance "
            f"({provenance or 'brak'}). Wymagane: complete/known."
        )

    dataset_id = str(run.get("dataset_id") or "").strip()
    if not dataset_id:
        raise ValueError(
            "Wybrany run nie ma dataset_id, więc nie można ustalić train/val."
        )

    sha = _sha256(path)
    existing = repo.get_model_by_sha256(sha)
    if existing is not None:
        existing = dict(existing)
        existing_target = str(existing.get("target") or "").strip().lower()
        existing_run = str(existing.get("run_id") or "").strip()
        if existing_target and existing_target != clean_target:
            raise ValueError("Checkpoint jest już zarejestrowany dla innego targetu.")
        if existing_run and existing_run != clean_run_id:
            raise ValueError(
                "Checkpoint jest już powiązany z innym runem. "
                "Nie nadpisujemy istniejącego lineage."
            )

    info = _model_info(path)
    family, scale = _infer_yolo_identity(path, info)
    task_type = str(info.get("task") or info.get("type") or "unknown").strip().lower()
    relative_path, external_path = _workspace_location(workspace, path)
    location_key = _location_key(relative_path, external_path)

    model_id = repo.upsert_model_location(
        model_id=model_id_from_sha256(sha),
        sha256=sha,
        project_id=run.get("project_id"),
        location_project_id=run.get("project_id"),
        run_id=clean_run_id,
        target=clean_target,
        task_type=task_type or "unknown",
        yolo_family=family,
        yolo_scale=scale or "unknown",
        checkpoint_kind="manual_registered",
        provenance_status="known",
        created_at=_file_timestamp_iso(path),
        location_key=location_key,
        relative_path=relative_path,
        external_path=external_path,
        is_primary=True,
    )

    _append_attestation(
        workspace,
        {
            "schema": "alpr.manual_model_run_attestation.v1",
            "statement": (
                "Użytkownik potwierdził, że wskazany checkpoint pochodzi "
                "z wybranego przebiegu treningowego i może dziedziczyć "
                "jego lineage train/val."
            ),
            "model_id": model_id,
            "model_sha256": sha,
            "model_path": str(path.resolve()),
            "run_id": clean_run_id,
            "dataset_id": dataset_id,
            "target": clean_target,
            "run_provenance_status": provenance,
            "registered_model_provenance_status": "known",
            "attested_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return ParticipantModelRegistration(
        model_id=model_id,
        sha256=sha,
        run_id=clean_run_id,
        dataset_id=dataset_id,
        target=clean_target,
        provenance_status="known",
        model_path=str(path.resolve()),
    )



def unregister_manual_participant_model(
    workspace_dir: Path | str,
    model_id: str,
    *,
    repository: RegistryRepository | None = None,
) -> ParticipantModelUnregistration:
    """Wyrejestruj model dodany ręcznie przez PZ3 bez usuwania pliku .pt."""
    workspace = Path(workspace_dir)
    repo = repository or RegistryRepository.for_workspace(workspace)
    repo.initialize()

    clean_id = str(model_id or "").strip()
    if not clean_id:
        raise ValueError("Wybierz model do wyrejestrowania.")

    row = repo.get_model(clean_id)
    if row is None:
        raise ValueError(f"Model {clean_id} nie istnieje w rejestrze.")
    model = dict(row)

    checkpoint_kind = str(
        model.get("checkpoint_kind") or ""
    ).strip().lower()
    if checkpoint_kind != "manual_registered":
        raise ValueError(
            "Ten model jest zarządzany automatycznie przez trening/bootstrap "
            f"(checkpoint_kind={checkpoint_kind or 'brak'}). "
            "Wyrejestrować można tutaj tylko modele dodane ręcznie przez "
            "„Zarejestruj istniejący model…”."
        )

    locations = [dict(item) for item in repo.list_model_locations(clean_id)]
    model_paths: list[str] = []
    for location in locations:
        relative_path = str(location.get("relative_path") or "").strip()
        external_path = str(location.get("external_path") or "").strip()
        if relative_path:
            normalized = relative_path.replace("\\", "/").casefold()
            parts = [part for part in normalized.split("/") if part]
            if "6_models" in parts:
                raise ValueError(
                    "Model ma lokalizację zarządzaną w 6_models. "
                    "Po wyrejestrowaniu zostałby ponownie wykryty przez bootstrap. "
                    "Dla takich modeli potrzebna jest operacja „Ukryj z puli”, "
                    "a nie wyrejestrowanie."
                )
            model_paths.append(str(workspace / relative_path))
        elif external_path:
            model_paths.append(external_path)

    track_refs = _participant_track_references(
        workspace,
        repo,
        clean_id,
    )
    if track_refs:
        details = ", ".join(
            f"{item['name']} [{item['status']}]"
            for item in track_refs[:5]
        )
        raise ValueError(
            "Model jest nadal uczestnikiem toru/torów: "
            + details
            + ". Najpierw usuń go z uczestników i zapisz zmianę."
        )

    experiment_refs = [
        dict(item)
        for item in repo.list_model_experiment_references(clean_id)
    ]
    if experiment_refs:
        details = ", ".join(
            str(item.get("experiment_id") or "-")
            for item in experiment_refs[:5]
        )
        raise ValueError(
            "Model jest częścią zapisanego eksperymentu "
            f"({details}) i nie może zostać wyrejestrowany."
        )

    deleted = repo.unregister_model(clean_id)
    if deleted is None:
        raise ValueError(
            "Model zniknął z rejestru przed zakończeniem operacji."
        )

    now = datetime.now(timezone.utc).isoformat()
    _append_attestation(
        workspace,
        {
            "schema": _ATTESTATION_SCHEMA,
            "action": "unregister",
            "statement": (
                "Użytkownik wyrejestrował ręcznie dodany model z puli "
                "uczestników. Plik checkpointu nie został usunięty."
            ),
            "model_id": clean_id,
            "model_sha256": str(model.get("sha256") or "").lower(),
            "checkpoint_kind": checkpoint_kind,
            "model_paths": model_paths,
            "unregistered_at": now,
        },
    )

    return ParticipantModelUnregistration(
        model_id=clean_id,
        sha256=str(model.get("sha256") or "").lower(),
        checkpoint_kind=checkpoint_kind,
        model_paths=tuple(model_paths),
        unregistered_at=now,
    )


def _participant_track_references(
    workspace: Path,
    repository: RegistryRepository,
    model_id: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for raw_track in repository.list_evaluation_tracks(
        include_retired=True
    ):
        track = dict(raw_track)
        relative = str(track.get("relative_path") or "").strip()
        if not relative:
            continue
        participants_path = workspace / relative / "participants.json"
        if not participants_path.exists():
            continue
        try:
            payload = json.loads(
                participants_path.read_text(encoding="utf-8")
            )
        except Exception:
            continue
        rows = (
            payload.get("participants")
            if isinstance(payload, Mapping)
            else []
        )
        found = any(
            isinstance(item, Mapping)
            and str(item.get("model_id") or "").strip() == model_id
            for item in (rows or [])
        )
        if not found:
            continue
        result.append(
            {
                "track_id": str(track.get("track_id") or ""),
                "name": str(track.get("name") or track.get("track_id") or "-"),
                "status": str(track.get("status") or "-"),
            }
        )
    return result


def _model_info(path: Path) -> dict[str, Any]:
    try:
        metadata = read_model_metadata_sidecar(path)
    except Exception:
        metadata = None
    if metadata is not None and len(metadata) >= 3:
        info = metadata[2]
        if isinstance(info, Mapping):
            return dict(info)
    return {}


def _infer_yolo_identity(path: Path, info: Mapping[str, Any]) -> tuple[str, str]:
    family = str(info.get("yolo_family") or "").strip()
    scale = str(info.get("yolo_size") or info.get("model_scale") or "").strip().lower()
    if family and scale:
        return family, scale

    match = _YOLO_RE.search(
        " ".join((
            path.name,
            str(info.get("architecture_label") or ""),
            str(info.get("yolo_variant") or ""),
        ))
    )
    if not match:
        return family or "unknown", scale or "unknown"

    version = str(match.group("version") or "")
    inferred_family = f"YOLOv{version}" if version == "8" else f"YOLO{version}"
    return family or inferred_family, scale or str(match.group("scale") or "").lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _workspace_location(
    workspace: Path,
    path: Path,
) -> tuple[str | None, str | None]:
    try:
        relative = path.resolve().relative_to(workspace.resolve())
        return relative.as_posix(), None
    except Exception:
        return None, str(path.resolve())


def _location_key(relative_path: str | None, external_path: str | None) -> str:
    raw = str(relative_path or external_path or "").strip().casefold()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()[:20]
    return f"manual:{digest}"


def _file_timestamp_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _append_attestation(workspace: Path, payload: Mapping[str, Any]) -> None:
    root = workspace / "_registry"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manual_model_run_attestations.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")
