"""Kontrolowane i robocze eksperymenty porównawcze modeli."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

from ..config import CONFIG
from .independence_service import (
    INDEPENDENCE_FAIL,
    INDEPENDENCE_PASS,
    ModelTrackIndependenceAudit,
    ModelTrackIndependenceService,
)
from .repository import RegistryRepository
from .track_service import EvaluationTrackService

MODE_CONTROLLED = "controlled"
MODE_WORKING = "working"

STATUS_READY = "READY"
STATUS_READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
STATUS_FAILED = "FAILED"

PROTOCOL_SCHEMA = "alpr.experiment_protocol.v1"


class ExperimentGuardError(RuntimeError):
    """Warunki eksperymentu nie pozwalają utworzyć poprawnego planu."""


@dataclass(frozen=True)
class ExperimentParticipantSnapshot:
    position: int
    model_id: str
    model_sha256: str
    independence_status: str
    overlap_count: int
    unknown_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentPlan:
    experiment_id: str
    name: str
    target: str
    mode: str
    track_id: str
    status: str
    protocol_sha256: str
    track_manifest_sha256: str
    track_reference_sha256: str
    independence_confirmed: bool
    participants: tuple[ExperimentParticipantSnapshot, ...]
    warnings: tuple[str, ...] = ()

    @property
    def controlled_ready(self) -> bool:
        return (
            self.mode == MODE_CONTROLLED
            and self.status == STATUS_READY
            and self.independence_confirmed
        )


class ExperimentService:
    """Buduje niezmienny plan eksperymentu na SEALED torze.

    Oba tryby wymagają poprawnej pieczęci toru. Różnica dotyczy wyłącznie
    niezależności modeli:
    - ``controlled``: każdy model musi mieć PASS,
    - ``working``: UNKNOWN może zostać zapisany jawnie jako ostrzeżenie; FAIL blokuje.
    """

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        repository: RegistryRepository | None = None,
        track_service: EvaluationTrackService | None = None,
        independence_service: ModelTrackIndependenceService | None = None,
    ) -> None:
        self.workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
        self.repository = repository or RegistryRepository.for_workspace(
            self.workspace
        )
        self.repository.initialize()
        self.track_service = track_service or EvaluationTrackService(
            self.workspace,
            repository=self.repository,
        )
        self.independence_service = (
            independence_service
            or ModelTrackIndependenceService(
                self.workspace,
                repository=self.repository,
                track_service=self.track_service,
            )
        )

    def create(
        self,
        *,
        name: str,
        target: str,
        track_id: str,
        model_ids: Sequence[str],
        mode: str = MODE_CONTROLLED,
        owner_project_id: str | None = None,
        protocol_options: Mapping[str, Any] | None = None,
    ) -> ExperimentPlan:
        clean_name = str(name or "").strip()
        clean_target = self._normalize_target(target)
        clean_track_id = str(track_id or "").strip()
        clean_mode = str(mode or "").strip().lower()
        clean_options = dict(protocol_options or {})
        require_pose_corners = bool(
            clean_target == "plate"
            and clean_options.get("require_pose_corners")
        )

        if not clean_name:
            raise ExperimentGuardError(
                "Nazwa eksperymentu nie może być pusta."
            )
        if not clean_target:
            raise ExperimentGuardError(
                f"Nieobsługiwany target eksperymentu: {target!r}."
            )
        if clean_mode not in {MODE_CONTROLLED, MODE_WORKING}:
            raise ExperimentGuardError(
                f"Nieobsługiwany tryb eksperymentu: {mode!r}."
            )
        if not clean_track_id:
            raise ExperimentGuardError(
                "Eksperyment wymaga track_id."
            )

        participants_ids = _unique_nonempty(model_ids)
        if len(participants_ids) < 2:
            raise ExperimentGuardError(
                "Eksperyment porównawczy wymaga co najmniej dwóch "
                "różnych modeli."
            )

        # To wywołanie wymaga SEALED + integralność PASS.
        try:
            track_ref = self.track_service.build_controlled_reference(
                clean_track_id,
                required_target=clean_target,
                require_pose_corners=require_pose_corners,
            )
        except Exception as exc:
            raise ExperimentGuardError(
                "Tor nie może być użyty do eksperymentu: "
                f"{exc}"
            ) from exc

        audits: list[ModelTrackIndependenceAudit] = []
        snapshots: list[ExperimentParticipantSnapshot] = []
        warnings: list[str] = []

        for position, model_id in enumerate(participants_ids):
            model_row = self.repository.get_model(model_id)
            if model_row is None:
                raise ExperimentGuardError(
                    f"Nie znaleziono modelu: {model_id}"
                )
            model_target = str(
                model_row["target"] or ""
            ).strip().lower()
            if model_target and model_target != clean_target:
                raise ExperimentGuardError(
                    f"Model {model_id} ma target {model_target}, "
                    f"a eksperyment {clean_target}."
                )

            try:
                audit = self.independence_service.audit(
                    model_id,
                    clean_track_id,
                )
            except Exception as exc:
                raise ExperimentGuardError(
                    f"Nie udało się przeprowadzić audytu modelu "
                    f"{model_id}: {exc}"
                ) from exc

            expected_sha = str(
                model_row["sha256"] or ""
            ).strip().lower()
            if (
                str(audit.model_id or "") != model_id
                or str(audit.model_sha256 or "").strip().lower()
                != expected_sha
            ):
                raise ExperimentGuardError(
                    f"Audyt modelu {model_id} nie odpowiada aktualnej "
                    "tożsamości modelu w rejestrze."
                )

            audits.append(audit)
            snapshots.append(
                ExperimentParticipantSnapshot(
                    position=position,
                    model_id=audit.model_id,
                    model_sha256=audit.model_sha256,
                    independence_status=audit.status,
                    overlap_count=audit.overlap_count,
                    unknown_reasons=tuple(audit.unknown_reasons),
                )
            )

            if audit.status != INDEPENDENCE_PASS:
                detail = (
                    f"{audit.model_id}: niezależność={audit.status}, "
                    f"overlap={audit.overlap_count}"
                )
                if audit.unknown_reasons:
                    detail += "; " + "; ".join(
                        audit.unknown_reasons[:3]
                    )
                warnings.append(detail)

        independence_confirmed = all(
            audit.status == INDEPENDENCE_PASS
            for audit in audits
        )
        known_failures = [
            audit
            for audit in audits
            if audit.status == INDEPENDENCE_FAIL
        ]

        if known_failures:
            summary = "; ".join(
                f"{audit.model_id}: overlap={audit.overlap_count}"
                for audit in known_failures
            )
            raise ExperimentGuardError(
                "Eksperyment nie może używać modelu z potwierdzonym "
                f"przeciekiem danych (FAIL). {summary}"
            )

        if clean_mode == MODE_CONTROLLED and not independence_confirmed:
            summary = "; ".join(warnings) or (
                "co najmniej jeden model nie ma PASS"
            )
            raise ExperimentGuardError(
                "Tryb controlled wymaga niezależności PASS dla każdego "
                f"modelu. {summary}"
            )

        status = (
            STATUS_READY
            if independence_confirmed
            else STATUS_READY_WITH_WARNINGS
        )
        created_at = _utc_now()

        protocol = self._build_protocol(
            mode=clean_mode,
            target=clean_target,
            track_ref=track_ref,
            audits=audits,
            protocol_options=clean_options,
            independence_confirmed=independence_confirmed,
        )
        protocol_json = _canonical_json(protocol)
        protocol_sha256 = hashlib.sha256(
            protocol_json.encode("utf-8")
        ).hexdigest()

        experiment_id = (
            "EXP-" + uuid.uuid4().hex[:20].upper()
        )

        experiment_row = {
            "experiment_id": experiment_id,
            "owner_project_id": owner_project_id,
            "name": clean_name,
            "target": clean_target,
            "mode": clean_mode,
            "track_id": clean_track_id,
            "status": status,
            "protocol_json": protocol_json,
            "protocol_sha256": protocol_sha256,
            "track_manifest_sha256": str(
                track_ref.manifest_sha256 or ""
            ).lower(),
            "created_at": created_at,
            "sealed_at": created_at,
            "started_at": None,
            "finished_at": None,
        }

        participant_rows = [
            {
                "model_id": audit.model_id,
                "position": position,
                "model_sha256": audit.model_sha256,
                "independence_status": audit.status,
                "overlap_count": audit.overlap_count,
            }
            for position, audit in enumerate(audits)
        ]

        overlap_rows: list[dict[str, Any]] = []
        for audit in audits:
            for overlap in audit.overlaps:
                overlap_rows.append(
                    {
                        "model_id": audit.model_id,
                        "source_image_id": overlap.source_image_id,
                        "training_dataset_id": (
                            overlap.training_dataset_id or None
                        ),
                        "training_run_id": (
                            overlap.training_run_id or None
                        ),
                        "reason": (
                            f"{overlap.reason}; "
                            f"split={overlap.training_split}; "
                            f"ancestor_depth={overlap.ancestor_depth}; "
                            f"track_member={overlap.track_member_index}; "
                            f"path={overlap.dataset_relative_path}"
                        ),
                    }
                )

        self.repository.create_experiment_bundle(
            experiment=experiment_row,
            participants=participant_rows,
            overlaps=overlap_rows,
        )

        return ExperimentPlan(
            experiment_id=experiment_id,
            name=clean_name,
            target=clean_target,
            mode=clean_mode,
            track_id=clean_track_id,
            status=status,
            protocol_sha256=protocol_sha256,
            track_manifest_sha256=str(
                track_ref.manifest_sha256 or ""
            ).lower(),
            track_reference_sha256=str(
                track_ref.reference_sha256 or ""
            ).lower(),
            independence_confirmed=independence_confirmed,
            participants=tuple(snapshots),
            warnings=tuple(warnings),
        )

    def start(self, experiment_id: str) -> None:
        row = self._require_experiment(experiment_id)
        status = str(row["status"] or "")
        if status not in {
            STATUS_READY,
            STATUS_READY_WITH_WARNINGS,
        }:
            raise ExperimentGuardError(
                f"Nie można uruchomić eksperymentu ze statusu {status}."
            )
        self.repository.update_experiment_lifecycle(
            experiment_id,
            status=STATUS_RUNNING,
            started_at=_utc_now(),
        )

    def finish(self, experiment_id: str) -> None:
        row = self._require_experiment(experiment_id)
        status = str(row["status"] or "")
        if status != STATUS_RUNNING:
            raise ExperimentGuardError(
                f"Nie można zakończyć eksperymentu ze statusu {status}."
            )
        self.repository.update_experiment_lifecycle(
            experiment_id,
            status=STATUS_COMPLETED,
            finished_at=_utc_now(),
        )


    def cancel(self, experiment_id: str) -> None:
        row = self._require_experiment(experiment_id)
        status = str(row["status"] or "")
        if status == STATUS_CANCELLED:
            return
        if status not in {
            STATUS_READY,
            STATUS_READY_WITH_WARNINGS,
            STATUS_RUNNING,
        }:
            raise ExperimentGuardError(
                f"Nie można anulować eksperymentu ze statusu {status}."
            )
        self.repository.update_experiment_lifecycle(
            experiment_id,
            status=STATUS_CANCELLED,
            finished_at=_utc_now(),
        )

    def fail(self, experiment_id: str) -> None:
        row = self._require_experiment(experiment_id)
        status = str(row["status"] or "")
        if status == STATUS_FAILED:
            return
        if status not in {
            STATUS_READY,
            STATUS_READY_WITH_WARNINGS,
            STATUS_RUNNING,
        }:
            raise ExperimentGuardError(
                f"Nie można oznaczyć eksperymentu jako FAILED ze statusu {status}."
            )
        self.repository.update_experiment_lifecycle(
            experiment_id,
            status=STATUS_FAILED,
            finished_at=_utc_now(),
        )

    def record_result(
        self,
        experiment_id: str,
        model_id: str,
        *,
        metrics: Mapping[str, Any],
        result_relative_path: str | None = None,
    ) -> None:
        row = self._require_experiment(experiment_id)
        status = str(row["status"] or "")
        if status not in {STATUS_RUNNING, STATUS_COMPLETED}:
            raise ExperimentGuardError(
                "Wyniki można zapisywać dopiero po uruchomieniu eksperymentu."
            )

        participants = {
            str(item["model_id"])
            for item in self.repository.list_experiment_participants(
                experiment_id
            )
        }
        clean_model_id = str(model_id or "").strip()
        if clean_model_id not in participants:
            raise ExperimentGuardError(
                f"Model {clean_model_id} nie należy do eksperymentu."
            )

        metrics_json = _canonical_json(
            _json_safe(dict(metrics or {}))
        )
        self.repository.upsert_experiment_result(
            experiment_id=experiment_id,
            model_id=clean_model_id,
            metrics_json=metrics_json,
            result_relative_path=(
                str(result_relative_path or "").strip() or None
            ),
            created_at=_utc_now(),
        )

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        row = self._require_experiment(experiment_id)
        return dict(row)

    def _require_experiment(self, experiment_id: str):
        clean_id = str(experiment_id or "").strip()
        row = self.repository.get_experiment(clean_id)
        if row is None:
            raise ExperimentGuardError(
                f"Nie znaleziono eksperymentu: {clean_id}"
            )
        return row

    def _build_protocol(
        self,
        *,
        mode: str,
        target: str,
        track_ref,
        audits: Sequence[ModelTrackIndependenceAudit],
        protocol_options: Mapping[str, Any],
        independence_confirmed: bool,
    ) -> dict[str, Any]:
        return {
            "schema": PROTOCOL_SCHEMA,
            "mode": mode,
            "target": target,
            "track": {
                "track_id": track_ref.track_id,
                "version": int(track_ref.version),
                "manifest_sha256": track_ref.manifest_sha256,
                "seal_sha256": track_ref.seal_sha256,
                "reference_sha256": track_ref.reference_sha256,
                "gt_sha256": track_ref.gt_sha256,
                "member_count": int(track_ref.member_count),
                "object_count": int(track_ref.object_count),
                "pose_corner_ready": bool(track_ref.pose_corner_ready),
                "pose_corner_order": str(track_ref.pose_corner_order or ""),
            },
            "participants": [
                {
                    "position": position,
                    "model_id": audit.model_id,
                    "model_sha256": audit.model_sha256,
                    "independence_status": audit.status,
                    "overlap_count": audit.overlap_count,
                    "checked_run_ids": list(
                        audit.checked_run_ids
                    ),
                    "checked_dataset_ids": list(
                        audit.checked_dataset_ids
                    ),
                    "unknown_reasons": list(
                        audit.unknown_reasons
                    ),
                }
                for position, audit in enumerate(audits)
            ],
            "independence_confirmed": bool(
                independence_confirmed
            ),
            "options": _json_safe(
                dict(protocol_options or {})
            ),
        }

    @staticmethod
    def _normalize_target(target: str) -> str:
        raw = str(target or "").strip().lower()
        if raw in {"plate", "plates", "pose", "mt"}:
            return "plate"
        if raw in {"char", "chars", "character", "mz"}:
            return "char"
        if raw in {"vehicle", "vehicles", "mp"}:
            return "vehicle"
        return ""


def _unique_nonempty(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
