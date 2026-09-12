"""Most między istniejącym rankingiem Z4 a rejestrem eksperymentów."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config import CONFIG
from ..registry.experiment_service import (
    ExperimentGuardError,
    ExperimentService,
    MODE_CONTROLLED,
)
from ..registry.repository import RegistryRepository
from ..registry.track_service import EvaluationTrackService


BRIDGE_SCHEMA = "alpr.ranking_experiment_bridge.v1"
RESULT_SCHEMA = "alpr.ranking_experiment_result.v1"


@dataclass(frozen=True)
class RankingExperimentParticipant:
    model_path: str
    model_id: str
    model_sha256: str
    independence_status: str = "UNKNOWN"


@dataclass(frozen=True)
class RankingExperimentContext:
    experiment_id: str
    target: str
    track_id: str
    mode: str
    protocol_sha256: str
    track_manifest_sha256: str
    track_reference_sha256: str
    independence_confirmed: bool
    participants: tuple[RankingExperimentParticipant, ...]

    def participant_for_sha256(
        self,
        sha256: str,
    ) -> RankingExperimentParticipant | None:
        value = str(sha256 or "").strip().lower()
        for participant in self.participants:
            if participant.model_sha256 == value:
                return participant
        return None


class RankingExperimentBridge:
    """Uruchamia ranking legacy jako kontrolowany eksperyment, gdy użyto toru PZ3.

    Dla starych źródeł rankingu spoza ``10_evaluation_tracks`` zwraca ``None``.
    Pozwala to zachować tryb legacy do czasu jego pełnej migracji, ale nie
    pozwala ominąć guardów dla ścieżek należących do rejestru torów.
    """

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        ranking_dir: Path | str | None = None,
        repository: RegistryRepository | None = None,
        track_service: EvaluationTrackService | None = None,
        experiment_service: ExperimentService | None = None,
    ) -> None:
        self.workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
        self.ranking_dir = Path(
            ranking_dir
            or CONFIG.get_ranking_dir("plate")
        )
        self.repository = repository or RegistryRepository.for_workspace(
            self.workspace
        )
        self.repository.initialize()
        self.track_service = track_service or EvaluationTrackService(
            self.workspace,
            repository=self.repository,
        )
        self.experiment_service = experiment_service or ExperimentService(
            self.workspace,
            repository=self.repository,
            track_service=self.track_service,
        )

    def prepare(
        self,
        *,
        name: str,
        target: str,
        reference_path: Path | str,
        model_paths: Sequence[Path | str],
        mode: str = MODE_CONTROLLED,
        protocol_options: Mapping[str, Any] | None = None,
    ) -> RankingExperimentContext | None:
        track = self._resolve_registered_track(
            reference_path,
            target=target,
        )
        if track is None:
            return None

        participants = tuple(
            self._resolve_participant(path, target=target)
            for path in model_paths
        )

        plan = self.experiment_service.create(
            name=name,
            target=target,
            track_id=str(track["track_id"]),
            model_ids=tuple(
                participant.model_id
                for participant in participants
            ),
            mode=mode,
            owner_project_id=track.get("owner_project_id"),
            protocol_options={
                "adapter_schema": BRIDGE_SCHEMA,
                **dict(protocol_options or {}),
            },
        )
        try:
            self.experiment_service.start(plan.experiment_id)
        except Exception:
            try:
                self.experiment_service.fail(plan.experiment_id)
            except Exception:
                pass
            raise

        status_by_model = {
            str(item.model_id): str(item.independence_status or "UNKNOWN")
            for item in plan.participants
        }
        frozen_participants = tuple(
            RankingExperimentParticipant(
                model_path=item.model_path,
                model_id=item.model_id,
                model_sha256=item.model_sha256,
                independence_status=status_by_model.get(
                    item.model_id,
                    "UNKNOWN",
                ),
            )
            for item in participants
        )

        return RankingExperimentContext(
            experiment_id=plan.experiment_id,
            target=plan.target,
            track_id=plan.track_id,
            mode=plan.mode,
            protocol_sha256=plan.protocol_sha256,
            track_manifest_sha256=plan.track_manifest_sha256,
            track_reference_sha256=plan.track_reference_sha256,
            independence_confirmed=plan.independence_confirmed,
            participants=frozen_participants,
        )

    def entry_metadata(
        self,
        context: RankingExperimentContext,
        model_path: Path | str,
    ) -> dict[str, str]:
        participant = self._participant_for_path(
            context,
            model_path,
        )
        return {
            "experiment_id": context.experiment_id,
            "experiment_mode": context.mode,
            "model_id": participant.model_id,
            "model_sha256": participant.model_sha256,
            "track_id": context.track_id,
            "protocol_sha256": context.protocol_sha256,
            "track_manifest_sha256": context.track_manifest_sha256,
            "independence_status": participant.independence_status,
        }

    def record_result(
        self,
        context: RankingExperimentContext,
        model_path: Path | str,
        ranking_entry,
    ) -> None:
        participant = self._participant_for_path(
            context,
            model_path,
        )
        if hasattr(ranking_entry, "to_dict"):
            entry_payload = ranking_entry.to_dict()
        elif isinstance(ranking_entry, Mapping):
            entry_payload = dict(ranking_entry)
        else:
            raise ExperimentGuardError(
                "Wynik rankingu nie ma postaci możliwej do zapisania."
            )

        self.experiment_service.record_result(
            context.experiment_id,
            participant.model_id,
            metrics={
                "schema": RESULT_SCHEMA,
                "ranking_entry": entry_payload,
            },
            result_relative_path=self._ranking_result_relative_path(),
        )

    def finish(
        self,
        context: RankingExperimentContext,
    ) -> None:
        participants = self.repository.list_experiment_participants(
            context.experiment_id
        )
        results = self.repository.list_experiment_results(
            context.experiment_id
        )
        participant_ids = {
            str(row["model_id"] or "")
            for row in participants
        }
        result_ids = {
            str(row["model_id"] or "")
            for row in results
        }
        missing = sorted(participant_ids - result_ids)
        if missing:
            self.experiment_service.fail(
                context.experiment_id
            )
            raise ExperimentGuardError(
                "Kontrolowany ranking nie ma wyników wszystkich "
                "uczestników. Brak: " + ", ".join(missing)
            )
        self.experiment_service.finish(
            context.experiment_id
        )

    def cancel(
        self,
        context: RankingExperimentContext,
    ) -> None:
        self.experiment_service.cancel(
            context.experiment_id
        )

    def fail(
        self,
        context: RankingExperimentContext,
    ) -> None:
        self.experiment_service.fail(
            context.experiment_id
        )

    def working_temp_xml_path(
        self,
        context: RankingExperimentContext | None = None,
    ) -> Path:
        experiment_key = (
            context.experiment_id
            if context is not None
            else "legacy"
        )
        root = (
            self.ranking_dir
            / "_working"
            / str(experiment_key)
        )
        root.mkdir(parents=True, exist_ok=True)
        return root / "temp_ranking_auto.xml"

    def _resolve_registered_track(
        self,
        reference_path: Path | str,
        *,
        target: str,
    ) -> dict[str, Any] | None:
        raw = str(reference_path or "").strip()
        if not raw:
            return None

        try:
            candidate = Path(raw).resolve()
        except Exception:
            candidate = Path(raw)

        track_root = self.workspace / "10_evaluation_tracks"
        under_track_root = _is_within(candidate, track_root)

        for row in self.track_service.list_tracks(
            target=target,
            include_retired=True,
        ):
            relative = str(row.get("relative_path") or "").strip()
            if not relative:
                continue
            root = self.workspace / relative
            try:
                resolved_root = root.resolve()
            except Exception:
                resolved_root = root
            if (
                candidate == resolved_root
                or _is_within(candidate, resolved_root)
            ):
                return dict(row)

        if under_track_root:
            raise ExperimentGuardError(
                "Ścieżka należy do 10_evaluation_tracks, ale nie odpowiada "
                "torowi zarejestrowanemu w SQLite."
            )
        return None

    def _resolve_participant(
        self,
        model_path: Path | str,
        *,
        target: str,
    ) -> RankingExperimentParticipant:
        path = Path(model_path)
        if not path.exists() or not path.is_file():
            raise ExperimentGuardError(
                f"Nie znaleziono modelu rankingu: {path}"
            )

        sha = _sha256(path)
        if not sha:
            raise ExperimentGuardError(
                f"Nie udało się policzyć SHA-256 modelu: {path}"
            )
        model = self.repository.get_model_by_sha256(sha)
        if model is None:
            raise ExperimentGuardError(
                "Model wybrany do kontrolowanego rankingu nie jest "
                f"zarejestrowany w SQLite: {path.name}"
            )

        model_target = str(
            model["target"] or ""
        ).strip().lower()
        expected_target = _normalize_target(target)
        if model_target and expected_target and model_target != expected_target:
            raise ExperimentGuardError(
                f"Model {path.name} ma target {model_target}, "
                f"a ranking {expected_target}."
            )

        return RankingExperimentParticipant(
            model_path=str(path),
            model_id=str(model["model_id"]),
            model_sha256=sha,
        )

    def _participant_for_path(
        self,
        context: RankingExperimentContext,
        model_path: Path | str,
    ) -> RankingExperimentParticipant:
        sha = _sha256(Path(model_path))
        participant = context.participant_for_sha256(sha)
        if participant is None:
            raise ExperimentGuardError(
                "Model nie należy do zamrożonej listy uczestników "
                f"eksperymentu {context.experiment_id}."
            )
        return participant

    def _ranking_result_relative_path(self) -> str | None:
        ranking_file = self.ranking_dir / "model_ranking.json"
        try:
            return ranking_file.resolve().relative_to(
                self.workspace.resolve()
            ).as_posix()
        except Exception:
            return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)
    except Exception:
        return ""
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _normalize_target(target: str) -> str:
    raw = str(target or "").strip().lower()
    if raw in {"plate", "plates", "pose", "mt"}:
        return "plate"
    if raw in {"char", "chars", "character", "mz"}:
        return "char"
    if raw in {"vehicle", "vehicles", "mp"}:
        return "vehicle"
    return raw
