"""Audyt niezależności modelu od zapieczętowanego toru testowego."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..config import CONFIG
from .repository import RegistryRepository
from .track_service import (
    EvaluationTrackError,
    EvaluationTrackService,
    INDEPENDENT_ACQUISITION_ATTESTATION_SCHEMA,
    INDEPENDENT_ACQUISITION_ATTESTATION_STATEMENT,
)

INDEPENDENCE_PASS = "PASS"
INDEPENDENCE_FAIL = "FAIL"
INDEPENDENCE_UNKNOWN = "UNKNOWN"

_FULL_PROVENANCE = {"complete", "known"}
_FULL_LINEAGE = {"known"}
_PROTECTED_SPLITS = ("train", "val")


@dataclass(frozen=True)
class IndependenceOverlap:
    source_image_id: str
    track_member_index: int
    track_original_name: str
    training_run_id: str
    training_dataset_id: str
    training_split: str
    dataset_relative_path: str
    ancestor_depth: int
    reason: str


@dataclass(frozen=True)
class ModelTrackIndependenceAudit:
    status: str
    model_id: str
    model_sha256: str
    track_id: str
    track_manifest_sha256: str = ""
    track_reference_sha256: str = ""
    checked_run_ids: tuple[str, ...] = ()
    checked_dataset_ids: tuple[str, ...] = ()
    overlaps: tuple[IndependenceOverlap, ...] = ()
    unknown_reasons: tuple[str, ...] = ()
    evidence_basis: tuple[str, ...] = ()
    audited_at: str = ""

    @property
    def overlap_count(self) -> int:
        return len(self.overlaps)

    @property
    def independent(self) -> bool:
        return self.status == INDEPENDENCE_PASS


class ModelTrackIndependenceService:
    """Konserwatywny audyt train/val z uwzględnieniem ancestry fine-tune."""

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        repository: RegistryRepository | None = None,
        track_service: EvaluationTrackService | None = None,
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

    def audit(
        self,
        model_id: str,
        track_id: str,
    ) -> ModelTrackIndependenceAudit:
        model_key = str(model_id or "").strip()
        track_key = str(track_id or "").strip()
        if not model_key:
            raise ValueError("model_id nie może być pusty.")
        if not track_key:
            raise ValueError("track_id nie może być pusty.")

        model = self.repository.get_model(model_key)
        if model is None:
            raise ValueError(f"Nie znaleziono modelu: {model_key}")

        return self._audit_model_row(model, track_key)

    def audit_sha256(
        self,
        model_sha256: str,
        track_id: str,
    ) -> ModelTrackIndependenceAudit:
        sha = str(model_sha256 or "").strip().lower()
        if not sha:
            raise ValueError("SHA-256 modelu nie może być pusty.")
        model = self.repository.get_model_by_sha256(sha)
        if model is None:
            raise ValueError(
                "Nie znaleziono modelu o podanym SHA-256."
            )
        return self._audit_model_row(model, str(track_id or "").strip())

    def _audit_model_row(
        self,
        model: Mapping[str, Any],
        track_id: str,
    ) -> ModelTrackIndependenceAudit:
        audited_at = datetime.now(timezone.utc).isoformat()
        model_id = str(model["model_id"] or "")
        model_sha = str(model["sha256"] or "").lower()

        unknown_reasons: list[str] = []
        overlaps: list[IndependenceOverlap] = []
        checked_run_ids: list[str] = []
        checked_dataset_ids: list[str] = []

        track_row = self.track_service.get_track(track_id)
        model_target = str(model["target"] or "").strip().lower()
        track_target = str(track_row.get("target") or "").strip().lower()
        if model_target and track_target and model_target != track_target:
            raise ValueError(
                f"Model ma target {model_target}, a tor {track_target}."
            )

        try:
            track_ref = self.track_service.build_controlled_reference(
                track_id,
                required_target=model_target or None,
            )
        except EvaluationTrackError as exc:
            return ModelTrackIndependenceAudit(
                status=INDEPENDENCE_UNKNOWN,
                model_id=model_id,
                model_sha256=model_sha,
                track_id=track_id,
                unknown_reasons=(
                    "Tor nie jest gotowy do kontrolowanego audytu: "
                    + str(exc),
                ),
                audited_at=audited_at,
            )

        independent_acquisition_attested = bool(
            track_ref.independent_acquisition
            and track_ref.not_derived_from_training_data
            and track_ref.acquisition_source_pool
            and track_ref.independent_acquisition_attested_at
            and track_ref.independent_acquisition_attestation_schema
            == INDEPENDENT_ACQUISITION_ATTESTATION_SCHEMA
            and track_ref.independent_acquisition_attestation_statement
            == INDEPENDENT_ACQUISITION_ATTESTATION_STATEMENT
        )
        evidence_basis: list[str] = ["artifact_sha256"]
        if independent_acquisition_attested:
            evidence_basis.append(
                "sealed_independent_acquisition_attestation"
            )

        track_rows = self.repository.list_evaluation_track_member_lineage(
            track_id
        )
        if not track_rows:
            unknown_reasons.append(
                "Tor nie ma członków z rodowodem w rejestrze."
            )

        track_sources: dict[str, Mapping[str, Any]] = {}
        track_shas: dict[str, Mapping[str, Any]] = {}
        weak_track_lineage = 0
        for row in track_rows:
            source_id = str(row["source_image_id"] or "").strip()
            sha = str(row["sha256"] or "").strip().lower()
            origin_status = str(row["origin_status"] or "").strip().lower()
            if source_id:
                track_sources[source_id] = row
            if sha:
                track_shas[sha] = row
            if origin_status not in _FULL_LINEAGE:
                weak_track_lineage += 1

        if weak_track_lineage and not independent_acquisition_attested:
            unknown_reasons.append(
                "Rodowód części obrazów toru nie jest w pełni potwierdzony "
                f"({weak_track_lineage} wpisów; exact_hash_only/legacy nie daje PASS)."
            )
        elif not weak_track_lineage:
            evidence_basis.append("source_image_lineage")

        model_provenance = str(
            model["provenance_status"] or ""
        ).strip().lower()
        if model_provenance not in _FULL_PROVENANCE:
            unknown_reasons.append(
                "Pochodzenie modelu nie jest kompletne "
                f"({model_provenance or 'brak statusu'})."
            )

        run_id = str(model["run_id"] or "").strip()
        if not run_id:
            unknown_reasons.append(
                "Model nie jest powiązany z przebiegiem treningowym."
            )
        else:
            self._walk_run_ancestry(
                run_id,
                track_sources=track_sources,
                track_shas=track_shas,
                checked_run_ids=checked_run_ids,
                checked_dataset_ids=checked_dataset_ids,
                overlaps=overlaps,
                unknown_reasons=unknown_reasons,
                independent_acquisition_attested=(
                    independent_acquisition_attested
                ),
            )

        status = (
            INDEPENDENCE_FAIL
            if overlaps
            else (
                INDEPENDENCE_UNKNOWN
                if unknown_reasons
                else INDEPENDENCE_PASS
            )
        )

        return ModelTrackIndependenceAudit(
            status=status,
            model_id=model_id,
            model_sha256=model_sha,
            track_id=track_id,
            track_manifest_sha256=str(
                track_ref.manifest_sha256 or ""
            ).lower(),
            track_reference_sha256=str(
                track_ref.reference_sha256 or ""
            ).lower(),
            checked_run_ids=tuple(checked_run_ids),
            checked_dataset_ids=tuple(checked_dataset_ids),
            overlaps=tuple(overlaps),
            unknown_reasons=tuple(_dedupe(unknown_reasons)),
            evidence_basis=tuple(_dedupe(evidence_basis)),
            audited_at=audited_at,
        )

    def _walk_run_ancestry(
        self,
        start_run_id: str,
        *,
        track_sources: Mapping[str, Mapping[str, Any]],
        track_shas: Mapping[str, Mapping[str, Any]],
        checked_run_ids: list[str],
        checked_dataset_ids: list[str],
        overlaps: list[IndependenceOverlap],
        unknown_reasons: list[str],
        independent_acquisition_attested: bool,
    ) -> None:
        current_id = str(start_run_id or "").strip()
        seen: set[str] = set()
        depth = 0

        while current_id:
            if current_id in seen:
                unknown_reasons.append(
                    "W ancestry treningu wykryto cykl "
                    f"przy runie {current_id}."
                )
                return
            if depth > 128:
                unknown_reasons.append(
                    "Ancestry treningu przekroczyło bezpieczny limit 128 poziomów."
                )
                return

            seen.add(current_id)
            run = self.repository.get_training_run(current_id)
            if run is None:
                unknown_reasons.append(
                    f"Brak przebiegu treningowego w ancestry: {current_id}."
                )
                return

            checked_run_ids.append(current_id)
            run_provenance = str(
                run["provenance_status"] or ""
            ).strip().lower()
            if run_provenance not in _FULL_PROVENANCE:
                unknown_reasons.append(
                    f"Run {current_id} ma niepełne provenance "
                    f"({run_provenance or 'brak statusu'})."
                )

            dataset_id = str(run["dataset_id"] or "").strip()
            if not dataset_id:
                unknown_reasons.append(
                    f"Run {current_id} nie ma dataset_id."
                )
            else:
                if dataset_id not in checked_dataset_ids:
                    checked_dataset_ids.append(dataset_id)
                self._audit_dataset(
                    dataset_id,
                    run_id=current_id,
                    ancestor_depth=depth,
                    track_sources=track_sources,
                    track_shas=track_shas,
                    overlaps=overlaps,
                    unknown_reasons=unknown_reasons,
                    independent_acquisition_attested=(
                        independent_acquisition_attested
                    ),
                )

            parent_id = str(run["parent_run_id"] or "").strip()
            current_id = parent_id
            depth += 1

    def _audit_dataset(
        self,
        dataset_id: str,
        *,
        run_id: str,
        ancestor_depth: int,
        track_sources: Mapping[str, Mapping[str, Any]],
        track_shas: Mapping[str, Mapping[str, Any]],
        overlaps: list[IndependenceOverlap],
        unknown_reasons: list[str],
        independent_acquisition_attested: bool,
    ) -> None:
        dataset = self.repository.get_dataset(dataset_id)
        if dataset is None:
            unknown_reasons.append(
                f"Dataset {dataset_id} użyty przez run {run_id} "
                "nie istnieje w rejestrze."
            )
            return

        dataset_provenance = str(
            dataset["provenance_status"] or ""
        ).strip().lower()
        if dataset_provenance not in _FULL_PROVENANCE:
            unknown_reasons.append(
                f"Dataset {dataset_id} ma niepełne provenance "
                f"({dataset_provenance or 'brak statusu'})."
            )

        rows = self.repository.list_dataset_member_lineage(
            dataset_id,
            splits=_PROTECTED_SPLITS,
        )
        if not rows:
            unknown_reasons.append(
                f"Dataset {dataset_id} nie ma zarejestrowanego członkostwa "
                "train/val; historyczny snapshot bez members nie dowodzi braku przecieku."
            )
            return

        weak_lineage = 0
        for row in rows:
            source_id = str(row["source_image_id"] or "").strip()
            file_sha = str(row["file_sha256"] or "").strip().lower()
            origin_status = str(row["origin_status"] or "").strip().lower()
            track_row = track_sources.get(source_id)
            sha_track_row = track_shas.get(file_sha)

            if track_row is not None or sha_track_row is not None:
                matched = track_row or sha_track_row
                reason_parts: list[str] = []
                if track_row is not None:
                    reason_parts.append("source_image_id")
                if sha_track_row is not None:
                    reason_parts.append("artifact_sha256")
                overlaps.append(
                    IndependenceOverlap(
                        source_image_id=(
                            source_id
                            or str(matched["source_image_id"] or "")
                        ),
                        track_member_index=int(
                            matched["member_index"] or 0
                        ),
                        track_original_name=str(
                            matched["original_name"] or ""
                        ),
                        training_run_id=run_id,
                        training_dataset_id=dataset_id,
                        training_split=str(row["split"] or ""),
                        dataset_relative_path=str(
                            row["relative_path"] or ""
                        ),
                        ancestor_depth=int(ancestor_depth),
                        reason="+".join(reason_parts),
                    )
                )
                continue

            if origin_status not in _FULL_LINEAGE:
                weak_lineage += 1

        if weak_lineage and not independent_acquisition_attested:
            unknown_reasons.append(
                f"Dataset {dataset_id}: {weak_lineage} obrazów train/val "
                "ma rodowód exact_hash_only/legacy, więc brak overlapu "
                "nie może dać PASS bez zapieczętowanego oświadczenia "
                "o niezależnym pozyskaniu toru."
            )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
