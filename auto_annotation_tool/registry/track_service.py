"""Wersjonowane i pieczętowane tory testowe dla kontrolowanych eksperymentów."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from ..config import CONFIG
from ..pose_corners import (
    CORNER_ORDER_TL_TR_BR_BL,
    is_canonical_quad_tl_tr_br_bl,
    parse_quad_points,
    quad_is_non_degenerate,
)
from .repository import RegistryRepository
from .experiment_workspace import (
    activate_z2_experiment_context,
    clear_active_z2_experiment_context,
    ensure_experiment_workspace,
    experiment_workspace_for_track,
)

TRACK_SCHEMA = "alpr.evaluation_track.v1"
SEAL_SCHEMA = "alpr.evaluation_track_seal.v1"
GT_COMPLETENESS_ATTESTATION_SCHEMA = "alpr.gt_completeness_attestation.v1"
GT_COMPLETENESS_ATTESTATION_STATEMENT = (
    "Ręcznie sprawdzono wszystkie obrazy toru i "
    "potwierdzono, że Ground Truth zawiera wszystkie "
    "widoczne obiekty docelowe."
)
INDEPENDENT_ACQUISITION_ATTESTATION_SCHEMA = (
    "alpr.independent_acquisition_attestation.v1"
)
INDEPENDENT_ACQUISITION_ATTESTATION_STATEMENT = (
    "Wszystkie obrazy toru pochodzą z niezależnie pozyskanej puli, "
    "która nie była użyta w train/val ocenianych modeli, i nie są "
    "pochodnymi danych treningowych ani walidacyjnych tych modeli."
)

STATUS_DRAFT = "DRAFT"
STATUS_VERIFIED = "VERIFIED"
STATUS_SEALED = "SEALED"
STATUS_RETIRED = "RETIRED"

INTEGRITY_PASS = "PASS"
INTEGRITY_FAIL = "FAIL"
INTEGRITY_UNKNOWN = "UNKNOWN"


class EvaluationTrackError(RuntimeError):
    """Błąd domenowy toru testowego."""


@dataclass(frozen=True)
class TrackIntegrityResult:
    status: str
    track_id: str
    issues: tuple[str, ...] = ()
    manifest_sha256: str = ""

    @property
    def ok(self) -> bool:
        return self.status == INTEGRITY_PASS


CONTROLLED_REFERENCE_SCHEMA = "alpr.evaluation_track_reference.v1"


@dataclass(frozen=True)
class ControlledTrackReference:
    """Niemutowalny uchwyt toru gotowego do kontrolowanego eksperymentu."""

    schema: str
    track_id: str
    version: int
    target: str
    purpose: str
    scope: str
    manifest_sha256: str
    seal_sha256: str
    gt_format: str
    gt_sha256: str
    member_count: int
    object_count: int
    source_image_ids: tuple[str, ...]
    member_sha256: tuple[str, ...]
    pose_corner_ready: bool
    pose_corner_order: str = ""
    manual_gt_complete: bool = False
    manual_gt_attested_at: str = ""
    manual_gt_attestation_schema: str = ""
    manual_gt_attestation_statement: str = ""
    independent_acquisition: bool = False
    not_derived_from_training_data: bool = False
    acquisition_source_pool: str = ""
    independent_acquisition_attested_at: str = ""
    independent_acquisition_attestation_schema: str = ""
    independent_acquisition_attestation_statement: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "track_id": self.track_id,
            "version": self.version,
            "target": self.target,
            "purpose": self.purpose,
            "scope": self.scope,
            "manifest_sha256": self.manifest_sha256,
            "seal_sha256": self.seal_sha256,
            "gt_format": self.gt_format,
            "gt_sha256": self.gt_sha256,
            "member_count": self.member_count,
            "object_count": self.object_count,
            "source_image_ids": list(self.source_image_ids),
            "member_sha256": list(self.member_sha256),
            "pose_corner_ready": self.pose_corner_ready,
            "pose_corner_order": self.pose_corner_order,
            "manual_gt_complete": self.manual_gt_complete,
            "manual_gt_attested_at": self.manual_gt_attested_at,
            "manual_gt_attestation_schema": self.manual_gt_attestation_schema,
            "manual_gt_attestation_statement": self.manual_gt_attestation_statement,
            "independent_acquisition": self.independent_acquisition,
            "not_derived_from_training_data": self.not_derived_from_training_data,
            "acquisition_source_pool": self.acquisition_source_pool,
            "independent_acquisition_attested_at": self.independent_acquisition_attested_at,
            "independent_acquisition_attestation_schema": self.independent_acquisition_attestation_schema,
            "independent_acquisition_attestation_statement": self.independent_acquisition_attestation_statement,
        }

    @property
    def reference_sha256(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

class EvaluationTrackService:
    """Tworzy, weryfikuje i pieczętuje samowystarczalne tory testowe."""

    def __init__(
        self,
        workspace_dir: Path | str | None = None,
        *,
        repository: RegistryRepository | None = None,
    ) -> None:
        self.workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
        self.experiments_root = self.workspace / "10_experiments"
        self.root = self.experiments_root / "tracks"
        self.legacy_root = self.workspace / "10_evaluation_tracks"
        self.repository = repository or RegistryRepository.for_workspace(self.workspace)
        self.repository.initialize()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_draft(
        self,
        *,
        name: str,
        target: str,
        purpose: str,
        scope: str = "global",
        owner_project_id: str | None = None,
        reservation_policy: str = "none",
        parent_track_id: str | None = None,
        version: int = 1,
    ) -> str:
        clean_name = str(name or "").strip()
        clean_target = self._normalize_target(target)
        clean_purpose = str(purpose or "").strip().lower()
        clean_scope = str(scope or "").strip().lower() or "global"
        if not clean_name:
            raise EvaluationTrackError("Nazwa toru nie może być pusta.")
        if not clean_target:
            raise EvaluationTrackError(f"Nieobsługiwany target toru: {target!r}.")
        if not clean_purpose:
            raise EvaluationTrackError("Purpose toru nie może być pusty.")
        if int(version or 0) < 1:
            raise EvaluationTrackError("Wersja toru musi być >= 1.")

        if parent_track_id:
            parent = self.repository.get_evaluation_track(parent_track_id)
            if parent is None:
                raise EvaluationTrackError("Nie znaleziono toru nadrzędnego.")

        track_id = f"TRK-{uuid.uuid4().hex[:20].upper()}"
        slug = self._safe_slug(clean_name)
        folder = f"{slug}__v{int(version):03d}__{track_id[-8:]}"
        track_root = self.root / clean_target / folder
        images_dir = track_root / "images"
        gt_dir = track_root / "ground_truth"
        images_dir.mkdir(parents=True, exist_ok=False)
        gt_dir.mkdir(parents=True, exist_ok=True)

        relative_path = self._workspace_relative(track_root)
        created_at = self._utc_now()
        try:
            self.repository.create_evaluation_track(
                track_id=track_id,
                owner_project_id=owner_project_id,
                name=clean_name,
                target=clean_target,
                purpose=clean_purpose,
                scope=clean_scope,
                status=STATUS_DRAFT,
                version=int(version),
                parent_track_id=parent_track_id,
                relative_path=relative_path,
                reservation_policy=reservation_policy,
                created_at=created_at,
            )
            self._write_manifest(track_id)
            created = self.repository.get_evaluation_track(track_id)
            if created is None:
                raise EvaluationTrackError(
                    "Nie udało się odczytać nowo utworzonego toru."
                )
            ensure_experiment_workspace(
                experiment_workspace_for_track(
                    self.workspace,
                    dict(created),
                )
            )
        except Exception:
            try:
                if self.repository.get_evaluation_track(track_id) is not None:
                    self.repository.delete_draft_evaluation_track(track_id)
            except Exception:
                pass
            shutil.rmtree(track_root, ignore_errors=True)
            try:
                staging = experiment_workspace_for_track(
                    self.workspace,
                    {
                        "track_id": track_id,
                        "target": clean_target,
                        "relative_path": relative_path,
                    },
                )
                for candidate in (
                    staging.source_images.parent,
                    staging.annotation_runs,
                    staging.experiment_runs,
                    staging.experiment_results,
                ):
                    shutil.rmtree(candidate, ignore_errors=True)
            except Exception:
                pass
            raise
        return track_id

    def add_member(
        self,
        track_id: str,
        source_path: Path | str,
        *,
        source_image_id: str | None = None,
        source_artifact_id: str | None = None,
        original_name: str | None = None,
    ) -> int:
        track = self._require_status(track_id, STATUS_DRAFT)
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise EvaluationTrackError(f"Brak pliku źródłowego: {source}")

        name = str(original_name or source.name).strip()
        if not name or Path(name).name != name:
            raise EvaluationTrackError("Nazwa obrazu toru musi być samą nazwą pliku.")
        existing_members = self.repository.list_evaluation_track_members(track_id)
        existing_names = {
            str(row["original_name"] or "")
            for row in existing_members
        }
        if name in existing_names:
            raise EvaluationTrackError(f"Tor zawiera już obraz o nazwie: {name}")

        sha = self._sha256(source)
        if not sha:
            raise EvaluationTrackError(f"Nie udało się policzyć SHA-256: {source}")

        if not source_image_id and not source_artifact_id:
            known_artifact = self.repository.find_unique_image_artifact_by_sha256(sha)
            if known_artifact is not None:
                source_image_id = str(known_artifact["source_image_id"] or "") or None
                source_artifact_id = str(known_artifact["artifact_id"] or "") or None

        resolved_source_id = self.repository.resolve_or_create_source_image(
            sha256=sha,
            source_image_id=source_image_id,
            origin_status="exact_hash_only" if not source_image_id else "known",
        )
        for row in existing_members:
            if (
                str(row["source_image_id"] or "") == resolved_source_id
                or str(row["sha256"] or "").strip().lower() == sha
            ):
                raise EvaluationTrackError(
                    "Tor zawiera już to samo logiczne źródło obrazu."
                )
        member_index = self.repository.next_evaluation_track_member_index(track_id)

        track_root = self._track_root(track)
        destination = track_root / "images" / name
        shutil.copy2(source, destination)
        if self._sha256(destination) != sha:
            destination.unlink(missing_ok=True)
            raise EvaluationTrackError("Kopia obrazu toru nie zgadza się z plikiem źródłowym.")

        artifact_seed = f"{track_id}|{member_index}|{sha}|{name}".encode("utf-8")
        track_artifact_id = (
            "ART-TRACK-" + hashlib.sha256(artifact_seed).hexdigest().upper()[:32]
        )
        artifact_relative = self._workspace_relative(destination)
        try:
            self.repository.add_evaluation_track_member(
                track_id=track_id,
                member_index=member_index,
                source_image_id=resolved_source_id,
                source_artifact_id=source_artifact_id,
                track_artifact_id=track_artifact_id,
                original_name=name,
                track_relative_path=f"images/{name}",
                sha256=sha,
                artifact_relative_path=artifact_relative,
                artifact_size_bytes=destination.stat().st_size,
            )
            self._write_manifest(track_id)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return member_index


    def remove_members(
        self,
        track_id: str,
        member_indices: list[int] | tuple[int, ...] | set[int],
    ) -> dict[str, Any]:
        """Usuń zaznaczone obrazy wyłącznie z toru DRAFT."""
        track = self._require_status(track_id, STATUS_DRAFT)
        requested = sorted({int(value) for value in member_indices})
        if not requested:
            raise EvaluationTrackError("Nie wybrano obrazów do usunięcia.")

        members = self.repository.list_evaluation_track_members(track_id)
        by_index = {int(row["member_index"]): row for row in members}
        missing = [value for value in requested if value not in by_index]
        if missing:
            raise EvaluationTrackError(
                "Nie znaleziono obrazów o indeksach: "
                + ", ".join(str(value) for value in missing)
            )

        selected = [by_index[value] for value in requested]
        track_root = self._track_root(track)
        transaction_root = (
            track_root / ".member_remove_staging" / uuid.uuid4().hex
        )
        staged_members: list[tuple[Path, Path]] = []
        gt_staged: tuple[Path, Path] | None = None

        gt_relative = str(track["gt_relative_path"] or "").strip()
        gt_invalidated = bool(gt_relative)

        try:
            for row in selected:
                relative = str(row["track_relative_path"] or "").strip()
                if not relative:
                    continue
                source = track_root / relative
                if not source.exists() or not source.is_file():
                    continue
                destination = (
                    transaction_root
                    / "members"
                    / str(int(row["member_index"]))
                    / source.name
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                staged_members.append((source, destination))

            if gt_invalidated:
                gt_path = self.workspace / gt_relative
                if gt_path.exists() and gt_path.is_file():
                    staged_gt_path = (
                        transaction_root / "ground_truth" / gt_path.name
                    )
                    staged_gt_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(gt_path), str(staged_gt_path))
                    gt_staged = (gt_path, staged_gt_path)

            removed_rows = self.repository.remove_evaluation_track_members(
                track_id,
                requested,
                invalidate_ground_truth=gt_invalidated,
            )
        except Exception:
            for original, staged in reversed(staged_members):
                try:
                    if staged.exists():
                        original.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(staged), str(original))
                except Exception:
                    pass
            if gt_staged is not None:
                original, staged = gt_staged
                try:
                    if staged.exists():
                        original.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(staged), str(original))
                except Exception:
                    pass
            shutil.rmtree(transaction_root, ignore_errors=True)
            raise

        invalidated_gt_path = ""
        if gt_staged is not None:
            _old, staged = gt_staged
            archive = (
                track_root
                / "ground_truth"
                / "_invalidated_member_change"
                / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                / staged.name
            )
            try:
                archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged), str(archive))
                invalidated_gt_path = str(archive)
            except Exception:
                invalidated_gt_path = str(staged)

        shutil.rmtree(transaction_root, ignore_errors=True)

        quarantined_sources: list[str] = []
        try:
            configured = getattr(CONFIG, "DIR_10_EXPERIMENT_SOURCES", None)
            source_root = (
                Path(configured)
                if configured
                else self.workspace / "10_experiments" / "sources"
            )
            target = self._normalize_target(str(track["target"] or ""))
            target_root = source_root / target
            if target_root.exists():
                track_dirs = [
                    path
                    for path in target_root.iterdir()
                    if path.is_dir()
                    and (
                        path.name == str(track_id)
                        or str(track_id).casefold() in path.name.casefold()
                    )
                ]
                for track_dir in track_dirs:
                    images_dir = track_dir / "images"
                    if not images_dir.exists():
                        continue
                    for row in removed_rows:
                        name = str(row.get("original_name") or "").strip()
                        expected_sha = str(row.get("sha256") or "").strip().lower()
                        if not name:
                            continue
                        candidate = images_dir / name
                        if not candidate.exists() or not candidate.is_file():
                            continue
                        if expected_sha and self._sha256(candidate) != expected_sha:
                            continue
                        quarantine = (
                            track_dir
                            / "_removed_members"
                            / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                            / name
                        )
                        quarantine.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(candidate), str(quarantine))
                        quarantined_sources.append(str(quarantine))
        except Exception:
            pass

        context_invalidated = False
        try:
            configured_state = getattr(CONFIG, "DIR_10_EXPERIMENT_STATE", None)
            state_root = (
                Path(configured_state)
                if configured_state
                else self.workspace / "10_experiments" / "_state"
            )
            active_context = state_root / "active_z2_context.json"
            if active_context.exists():
                payload = json.loads(active_context.read_text(encoding="utf-8"))
                if str(payload.get("track_id") or "").strip() == str(track_id):
                    archive = (
                        state_root
                        / "invalidated_contexts"
                        / (
                            datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                            + "_"
                            + str(track_id)
                            + ".json"
                        )
                    )
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(active_context), str(archive))
                    context_invalidated = True
        except Exception:
            pass

        from .participant_pool_audit import ParticipantPoolAuditService
        ParticipantPoolAuditService(
            self.workspace, repository=self.repository
        ).invalidate_track_audit(track_id, reason="members_removed")
        self._write_manifest(track_id)

        return {
            "track_id": str(track_id),
            "removed_count": len(removed_rows),
            "removed_member_indices": [
                int(row["member_index"]) for row in removed_rows
            ],
            "removed_names": [
                str(row.get("original_name") or "") for row in removed_rows
            ],
            "ground_truth_invalidated": gt_invalidated,
            "invalidated_gt_path": invalidated_gt_path,
            "experiment_sources_quarantined": quarantined_sources,
            "z2_context_invalidated": context_invalidated,
        }


    def add_members_batch(
        self,
        track_id: str,
        source_paths: list[Path | str] | tuple[Path | str, ...],
        *,
        sha256_by_path: Mapping[str, str] | None = None,
        progress=None,
    ) -> list[int]:
        track = self._require_status(track_id, STATUS_DRAFT)
        paths = [Path(value) for value in source_paths]
        if not paths:
            return []
        existing = self.repository.list_evaluation_track_members(track_id)
        existing_names = {str(row["original_name"] or "").casefold() for row in existing}
        existing_shas = {str(row["sha256"] or "").lower() for row in existing}
        supplied = {str(k): str(v or "").lower() for k, v in dict(sha256_by_path or {}).items()}
        prepared, batch_names, batch_shas = [], set(), set()
        for path in paths:
            if not path.exists() or not path.is_file():
                raise EvaluationTrackError(f"Brak pliku źródłowego: {path}")
            name = path.name
            if name.casefold() in existing_names or name.casefold() in batch_names:
                raise EvaluationTrackError(f"Tor zawiera już obraz o nazwie: {name}")
            sha = supplied.get(str(path)) or supplied.get(str(path.resolve())) or self._sha256(path)
            if sha in existing_shas or sha in batch_shas:
                raise EvaluationTrackError("Tor zawiera już ten sam plik (SHA-256).")
            prepared.append({"path": path, "name": name, "sha": sha, "size": int(path.stat().st_size)})
            batch_names.add(name.casefold())
            batch_shas.add(sha)
        if progress:
            progress("Identyfikacja źródeł", 0, len(prepared))
        identities = self.repository.resolve_track_member_sources_batch(
            [item["sha"] for item in prepared]
        )
        existing_sources = {str(row["source_image_id"] or "") for row in existing}
        batch_sources = set()
        for item in prepared:
            identity = identities[item["sha"]]
            source_id = str(identity["source_image_id"])
            if source_id in existing_sources or source_id in batch_sources:
                raise EvaluationTrackError("Tor zawiera już to samo logiczne źródło obrazu.")
            batch_sources.add(source_id)
            item["source_id"] = source_id
            item["source_artifact_id"] = identity.get("source_artifact_id")
        track_root = self._track_root(track)
        start = self.repository.next_evaluation_track_member_index(track_id)
        copied, rows, indices = [], [], []
        committed = False
        try:
            for offset, item in enumerate(prepared):
                index = start + offset
                destination = track_root / "images" / item["name"]
                if destination.exists():
                    raise EvaluationTrackError(f"Plik docelowy już istnieje: {destination}")
                copied.append(destination)
                shutil.copy2(item["path"], destination)
                if int(destination.stat().st_size) != item["size"]:
                    raise EvaluationTrackError(f"Kopia ma inny rozmiar: {item['name']}")
                if self._sha256(destination) != item["sha"]:
                    raise EvaluationTrackError(f"Plik zmienił się po audycie: {item['name']}")
                artifact_seed = f"{track_id}|{index}|{item['sha']}|{item['name']}".encode("utf-8")
                artifact_id = "ART-TRACK-" + hashlib.sha256(artifact_seed).hexdigest().upper()[:32]
                rows.append(
                    {
                        "member_index": index,
                        "source_image_id": item["source_id"],
                        "source_artifact_id": item["source_artifact_id"],
                        "track_artifact_id": artifact_id,
                        "original_name": item["name"],
                        "track_relative_path": f"images/{item['name']}",
                        "sha256": item["sha"],
                        "artifact_relative_path": self._workspace_relative(destination),
                        "artifact_size_bytes": int(destination.stat().st_size),
                    }
                )
                indices.append(index)
                if progress and (offset % 25 == 0 or offset + 1 == len(prepared)):
                    progress("Kopiowanie obrazów", offset + 1, len(prepared))
            if progress:
                progress("Zapis rejestru", 0, 1)
            self.repository.add_evaluation_track_members_batch(track_id, rows)
            committed = True
            from .participant_pool_audit import ParticipantPoolAuditService
            ParticipantPoolAuditService(
                self.workspace, repository=self.repository
            ).invalidate_track_audit(track_id, reason="members_added")
            if progress:
                progress("Zapis manifestu", 0, 1)
            self._write_manifest(track_id)
            if progress:
                progress("Zakończono", len(prepared), len(prepared))
        except Exception:
            # Once rows are committed their image files must remain available.
            if not committed:
                for path in copied:
                    path.unlink(missing_ok=True)
            raise
        return indices

    def set_ground_truth(
        self,
        track_id: str,
        source_path: Path | str,
        *,
        gt_format: str = "cvat_xml",
    ) -> Path:
        track = self._require_status(track_id, STATUS_DRAFT)
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise EvaluationTrackError(f"Brak pliku GT: {source}")

        normalized_format = str(gt_format or "").strip().lower()
        if normalized_format != "cvat_xml":
            raise EvaluationTrackError(
                "ETAP 5 obsługuje weryfikację GT w formacie cvat_xml."
            )

        track_root = self._track_root(track)
        gt_dir = track_root / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)
        destination = gt_dir / ("annotations" + (source.suffix or ".xml"))
        shutil.copy2(source, destination)
        gt_sha = self._sha256(destination)

        old_relative = str(track["gt_relative_path"] or "").strip()
        if old_relative and old_relative != self._workspace_relative(destination):
            old_path = self.workspace / old_relative
            if old_path.exists() and self._is_within(old_path, track_root):
                old_path.unlink(missing_ok=True)

        self.repository.update_evaluation_track(
            track_id,
            gt_format=normalized_format,
            gt_relative_path=self._workspace_relative(destination),
            gt_sha256=gt_sha,
        )
        try:
            from .gt_preannotation import (
                maybe_compute_preannotation_metrics_for_track,
            )
            maybe_compute_preannotation_metrics_for_track(
                track_root,
                destination,
            )
        except Exception:
            # Metryka dodatkowa nie może unieważnić poprawnego FINAL GT.
            pass

        self._write_manifest(track_id)
        return destination

    def verify(
        self,
        track_id: str,
        *,
        manual_gt_complete: bool = False,
    ) -> dict[str, Any]:
        track = self._require_status(track_id, STATUS_DRAFT)
        members = self.repository.list_evaluation_track_members(track_id)
        if not members:
            raise EvaluationTrackError(
                "Nie można zweryfikować pustego toru."
            )

        gt_format = str(track["gt_format"] or "").strip().lower()
        gt_relative = str(track["gt_relative_path"] or "").strip()
        gt_sha = str(track["gt_sha256"] or "").strip().lower()
        if not gt_format or not gt_relative or not gt_sha:
            raise EvaluationTrackError(
                "Tor nie ma kompletnego Ground Truth."
            )

        gt_path = self.workspace / gt_relative
        if not gt_path.exists() or self._sha256(gt_path) != gt_sha:
            raise EvaluationTrackError(
                "Plik GT nie istnieje albo zmienił zawartość."
            )

        for member in members:
            member_path = (
                self._track_root(track)
                / str(member["track_relative_path"])
            )
            expected = str(
                member["sha256"] or ""
            ).strip().lower()
            if (
                not member_path.exists()
                or self._sha256(member_path) != expected
            ):
                raise EvaluationTrackError(
                    "Obraz toru zmienił zawartość: "
                    f"{member['original_name']}"
                )

        if gt_format != "cvat_xml":
            raise EvaluationTrackError(
                f"Brak walidatora GT dla formatu: {gt_format}"
            )

        verification = self._verify_cvat_xml(
            track,
            members,
            gt_path,
        )
        verified_at = self._utc_now()
        self._apply_manual_gt_attestation(
            verification,
            complete=bool(manual_gt_complete),
            attested_at=(
                verified_at
                if manual_gt_complete
                else ""
            ),
        )

        self._write_manifest(
            track_id,
            verification=verification,
            status_override=STATUS_VERIFIED,
            verified_at_override=verified_at,
            object_count_override=int(
                verification["object_count"]
            ),
        )
        self.repository.update_evaluation_track(
            track_id,
            status=STATUS_VERIFIED,
            member_count=len(members),
            object_count=int(verification["object_count"]),
            verified_at=verified_at,
        )
        return verification

    def get_verification(
        self,
        track_id: str,
    ) -> dict[str, Any]:
        track = self._require_track(track_id)
        manifest_path = (
            self._track_root(track)
            / "track_manifest.json"
        )
        if not manifest_path.exists():
            return {}
        manifest = self._read_json(manifest_path)
        verification = manifest.get("verification")
        if not isinstance(verification, Mapping):
            return {}
        return dict(verification)

    def attest_ground_truth_completeness(
        self,
        track_id: str,
    ) -> dict[str, Any]:
        """Dodaj ręczne potwierdzenie kompletności GT do VERIFIED."""

        self._require_status(track_id, STATUS_VERIFIED)
        preflight = self._content_integrity(track_id)
        if not preflight.ok:
            raise EvaluationTrackError(
                "Nie można potwierdzić kompletności GT: "
                + "; ".join(preflight.issues)
            )

        verification = self.get_verification(track_id)
        if bool(verification.get("manual_gt_complete")):
            return verification

        self._apply_manual_gt_attestation(
            verification,
            complete=True,
            attested_at=self._utc_now(),
        )
        self._write_manifest(
            track_id,
            verification=verification,
        )
        return verification

    def attest_independent_acquisition(
        self,
        track_id: str,
        *,
        source_pool: str = "new_independent_acquisition",
    ) -> dict[str, Any]:
        """Zapisz ręczne oświadczenie o niezależnym pochodzeniu toru."""

        self._require_status(track_id, STATUS_VERIFIED)
        preflight = self._content_integrity(track_id)
        if not preflight.ok:
            raise EvaluationTrackError(
                "Nie można potwierdzić niezależnego pozyskania: "
                + "; ".join(preflight.issues)
            )

        clean_pool = str(source_pool or "").strip()
        if not clean_pool:
            raise EvaluationTrackError(
                "Oświadczenie o niezależnym pozyskaniu wymaga nazwy puli źródłowej."
            )

        verification = self.get_verification(track_id)
        verification["independent_acquisition"] = True
        verification["not_derived_from_training_data"] = True
        verification["acquisition_source_pool"] = clean_pool
        verification["independent_acquisition_attestation_schema"] = (
            INDEPENDENT_ACQUISITION_ATTESTATION_SCHEMA
        )
        verification["independent_acquisition_attestation_statement"] = (
            INDEPENDENT_ACQUISITION_ATTESTATION_STATEMENT
        )
        verification["independent_acquisition_attested_at"] = self._utc_now()
        self._write_manifest(
            track_id,
            verification=verification,
        )
        return verification

    @staticmethod
    def _apply_manual_gt_attestation(
        verification: dict[str, Any],
        *,
        complete: bool,
        attested_at: str,
    ) -> None:
        is_complete = bool(complete)
        verification["manual_gt_complete"] = is_complete
        verification["manual_gt_attestation_schema"] = (
            GT_COMPLETENESS_ATTESTATION_SCHEMA
            if is_complete
            else ""
        )
        verification["manual_gt_attestation_statement"] = (
            GT_COMPLETENESS_ATTESTATION_STATEMENT
            if is_complete
            else ""
        )
        verification["manual_gt_attested_at"] = (
            str(attested_at or "").strip()
            if is_complete
            else ""
        )

    def seal(self, track_id: str) -> TrackIntegrityResult:
        track = self._require_status(track_id, STATUS_VERIFIED)
        preflight = self._content_integrity(track_id)
        if not preflight.ok:
            raise EvaluationTrackError(
                "Nie można zapieczętować toru: " + "; ".join(preflight.issues)
            )

        sealed_at = self._utc_now()
        # Najpierw zapisujemy finalny manifest i seal, dopiero potem lifecycle w DB.
        # W razie błędu DB tor nadal jest VERIFIED i pieczętowanie można powtórzyć.
        manifest_path = self._write_manifest(
            track_id,
            status_override=STATUS_SEALED,
            sealed_at_override=sealed_at,
        )
        manifest_sha = self._sha256(manifest_path)

        track = self._require_track(track_id)
        members = self.repository.list_evaluation_track_members(track_id)
        files = [
            {
                "path": str(row["track_relative_path"]),
                "sha256": str(row["sha256"] or "").lower(),
            }
            for row in members
        ]
        gt_relative = str(track["gt_relative_path"] or "")
        if gt_relative:
            gt_path = self.workspace / gt_relative
            files.append(
                {
                    "path": gt_path.relative_to(self._track_root(track)).as_posix(),
                    "sha256": str(track["gt_sha256"] or "").lower(),
                }
            )

        seal_payload = {
            "schema": SEAL_SCHEMA,
            "track_id": track_id,
            "version": int(track["version"]),
            "sealed_at": sealed_at,
            "manifest_sha256": manifest_sha,
            "algorithm": "sha256",
            "files": files,
        }
        seal_path = self._track_root(track) / "seal.json"
        self._atomic_json(seal_path, seal_payload)
        seal_sha = self._sha256(seal_path)
        if not seal_sha:
            raise EvaluationTrackError("Nie udało się policzyć SHA-256 seal.json.")
        self.repository.seal_evaluation_track_with_reservations(
            track_id,
            sealed_at=sealed_at,
            manifest_sha256=manifest_sha,
            seal_sha256=seal_sha,
        )
        clear_active_z2_experiment_context(
            self.workspace,
            track_id=track_id,
        )
        return self.verify_integrity(track_id)

    def verify_integrity(self, track_id: str) -> TrackIntegrityResult:
        """Porównaj SQLite, manifest, seal i faktyczny zestaw plików toru."""

        track = self._require_track(track_id)
        status = str(track["status"] or "")
        if status not in {STATUS_SEALED, STATUS_RETIRED}:
            return TrackIntegrityResult(
                status=INTEGRITY_UNKNOWN,
                track_id=track_id,
                issues=("Tor nie jest zapieczętowany.",),
            )

        track_root = self._track_root(track)
        manifest_path = track_root / "track_manifest.json"
        seal_path = track_root / "seal.json"
        hard_issues: list[str] = []
        unknown_issues: list[str] = []

        if not manifest_path.exists():
            hard_issues.append("Brak track_manifest.json.")
        if not seal_path.exists():
            hard_issues.append("Brak seal.json.")
        if hard_issues:
            return TrackIntegrityResult(
                status=INTEGRITY_FAIL,
                track_id=track_id,
                issues=tuple(hard_issues),
            )

        try:
            manifest = self._read_json(manifest_path)
        except EvaluationTrackError as exc:
            hard_issues.append(str(exc))
            manifest = {}
        try:
            seal = self._read_json(seal_path)
        except EvaluationTrackError as exc:
            hard_issues.append(str(exc))
            seal = {}

        manifest_sha = self._sha256(manifest_path)
        seal_sha = self._sha256(seal_path)
        db_manifest_sha = str(track["manifest_sha256"] or "").strip().lower()
        db_seal_sha = str(track["seal_sha256"] or "").strip().lower()

        if not db_manifest_sha:
            unknown_issues.append(
                "Brak zakotwiczonego SHA-256 manifestu w SQLite."
            )
        elif manifest_sha != db_manifest_sha:
            hard_issues.append(
                "SHA-256 track_manifest.json nie zgadza się z rejestrem SQLite."
            )

        if not db_seal_sha:
            unknown_issues.append(
                "Brak zakotwiczonego SHA-256 seal.json w SQLite."
            )
        elif seal_sha != db_seal_sha:
            hard_issues.append(
                "SHA-256 seal.json nie zgadza się z rejestrem SQLite."
            )

        if manifest:
            if str(manifest.get("schema") or "") != TRACK_SCHEMA:
                hard_issues.append(
                    "Nieobsługiwany schema track_manifest.json."
                )
            if str(manifest.get("track_id") or "") != track_id:
                hard_issues.append(
                    "track_id manifestu nie zgadza się z rejestrem."
                )
            try:
                if int(manifest.get("version")) != int(track["version"]):
                    hard_issues.append(
                        "Wersja manifestu nie zgadza się z rejestrem."
                    )
            except Exception:
                hard_issues.append(
                    "Niepoprawna wersja w track_manifest.json."
                )

            # RETIRED jest wyłącznie stanem lifecycle w DB; zamrożony manifest
            # pozostaje SEALED.
            if str(manifest.get("status") or "") != STATUS_SEALED:
                hard_issues.append(
                    "Manifest zapieczętowanego toru nie ma statusu SEALED."
                )

            top_level_pairs = (
                ("name", str(track["name"])),
                ("target", str(track["target"])),
                ("purpose", str(track["purpose"])),
                ("scope", str(track["scope"])),
                ("parent_track_id", track["parent_track_id"]),
                ("reservation_policy", track["reservation_policy"]),
                ("created_at", track["created_at"]),
                ("verified_at", track["verified_at"]),
                ("sealed_at", track["sealed_at"]),
            )
            for field, expected in top_level_pairs:
                if manifest.get(field) != expected:
                    hard_issues.append(
                        f"Manifest i rejestr różnią się w polu: {field}."
                    )
            try:
                if int(manifest.get("object_count")) != int(
                    track["object_count"] or 0
                ):
                    hard_issues.append(
                        "object_count manifestu nie zgadza się z rejestrem."
                    )
            except Exception:
                hard_issues.append(
                    "Niepoprawny object_count w manifeście."
                )

        if seal:
            if str(seal.get("schema") or "") != SEAL_SCHEMA:
                hard_issues.append("Nieobsługiwany schema seal.json.")
            if str(seal.get("track_id") or "") != track_id:
                hard_issues.append(
                    "track_id seal.json nie zgadza się z rejestrem."
                )
            try:
                if int(seal.get("version")) != int(track["version"]):
                    hard_issues.append(
                        "Wersja seal.json nie zgadza się z rejestrem."
                    )
            except Exception:
                hard_issues.append("Niepoprawna wersja w seal.json.")
            if seal.get("sealed_at") != track["sealed_at"]:
                hard_issues.append(
                    "sealed_at seal.json nie zgadza się z rejestrem."
                )
            if (
                str(seal.get("manifest_sha256") or "").strip().lower()
                != manifest_sha
            ):
                hard_issues.append(
                    "SHA-256 manifestu zapisany w seal.json jest niepoprawny."
                )

        db_members = self.repository.list_evaluation_track_members(track_id)
        manifest_members = (
            manifest.get("members")
            if isinstance(manifest.get("members"), list)
            else []
        )
        manifest_by_index: dict[int, Mapping[str, Any]] = {}
        for raw in manifest_members:
            if not isinstance(raw, Mapping):
                hard_issues.append(
                    "Manifest zawiera niepoprawny wpis members."
                )
                continue
            try:
                index = int(raw.get("member_index"))
            except Exception:
                hard_issues.append(
                    "Manifest zawiera member_index niebędący liczbą."
                )
                continue
            if index in manifest_by_index:
                hard_issues.append(
                    "Manifest zawiera zduplikowany member_index."
                )
                continue
            manifest_by_index[index] = raw

        if len(manifest_members) != len(db_members):
            hard_issues.append(
                "Liczba członków manifestu nie zgadza się z rejestrem SQLite."
            )
        try:
            if int(manifest.get("member_count")) != len(db_members):
                hard_issues.append(
                    "member_count manifestu nie zgadza się z rejestrem SQLite."
                )
        except Exception:
            hard_issues.append(
                "Niepoprawny member_count w manifeście."
            )

        seal_files = (
            seal.get("files") if isinstance(seal.get("files"), list) else []
        )
        seal_by_path: dict[str, str] = {}
        for raw in seal_files:
            if not isinstance(raw, Mapping):
                hard_issues.append(
                    "seal.json zawiera niepoprawny wpis files."
                )
                continue
            relative = str(raw.get("path") or "").strip().replace("\\", "/")
            expected = str(raw.get("sha256") or "").strip().lower()
            if not relative or not expected:
                hard_issues.append(
                    "seal.json zawiera niekompletny wpis files."
                )
                continue
            candidate = track_root / relative
            if not self._is_within(candidate, track_root):
                hard_issues.append(
                    f"Ścieżka w seal.json wychodzi poza tor: {relative}"
                )
                continue
            if relative in seal_by_path:
                hard_issues.append(
                    f"seal.json zawiera zduplikowaną ścieżkę: {relative}"
                )
                continue
            seal_by_path[relative] = expected

        expected_content: dict[str, str] = {}
        seen_sources: set[str] = set()
        for row in db_members:
            index = int(row["member_index"])
            source_id = str(row["source_image_id"] or "")
            if source_id in seen_sources:
                hard_issues.append(
                    f"Logiczne źródło obrazu występuje w torze więcej niż raz: "
                    f"{source_id}"
                )
            seen_sources.add(source_id)

            relative = str(
                row["track_relative_path"] or ""
            ).replace("\\", "/")
            expected_sha = str(row["sha256"] or "").strip().lower()
            manifest_row = manifest_by_index.get(index)
            if manifest_row is None:
                hard_issues.append(
                    f"Brak członka {index} w track_manifest.json."
                )
            else:
                pairs = (
                    ("source_image_id", source_id),
                    ("source_artifact_id", row["source_artifact_id"]),
                    ("track_artifact_id", row["track_artifact_id"]),
                    ("original_name", str(row["original_name"] or "")),
                    ("track_relative_path", relative),
                    ("sha256", expected_sha),
                )
                for field, db_value in pairs:
                    manifest_value = manifest_row.get(field)
                    if field == "sha256":
                        manifest_value = str(
                            manifest_value or ""
                        ).lower()
                    elif field == "track_relative_path":
                        manifest_value = str(
                            manifest_value or ""
                        ).replace("\\", "/")
                    if manifest_value != db_value:
                        hard_issues.append(
                            "Manifest i rejestr różnią się dla "
                            f"członka {index}: {field}."
                        )

            expected_content[relative] = expected_sha
            if seal_by_path.get(relative) != expected_sha:
                hard_issues.append(
                    "seal.json nie zgadza się z rejestrem dla: "
                    f"{relative}"
                )
            candidate = track_root / relative
            if not self._is_within(candidate, track_root):
                hard_issues.append(
                    f"Ścieżka członka wychodzi poza tor: {relative}"
                )
            elif not candidate.exists():
                hard_issues.append(
                    f"Brak pliku toru: {relative}"
                )
            elif self._sha256(candidate) != expected_sha:
                hard_issues.append(
                    f"Zmieniła się zawartość pliku: {relative}"
                )

        gt_relative_db = str(track["gt_relative_path"] or "").strip()
        gt_sha_db = str(track["gt_sha256"] or "").strip().lower()
        gt_format_db = str(track["gt_format"] or "").strip().lower()
        manifest_gt = (
            manifest.get("ground_truth")
            if isinstance(manifest.get("ground_truth"), Mapping)
            else {}
        )
        if not gt_relative_db or not gt_sha_db:
            hard_issues.append(
                "Rejestr nie zawiera kompletnego GT."
            )
        else:
            gt_path = self.workspace / gt_relative_db
            try:
                gt_track_relative = gt_path.resolve().relative_to(
                    track_root.resolve()
                ).as_posix()
            except Exception:
                hard_issues.append(
                    "Ścieżka GT wychodzi poza tor."
                )
                gt_track_relative = ""

            if gt_track_relative:
                expected_content[gt_track_relative] = gt_sha_db
                if seal_by_path.get(gt_track_relative) != gt_sha_db:
                    hard_issues.append(
                        "seal.json nie zgadza się z rejestrem "
                        "dla Ground Truth."
                    )
                if not gt_path.exists():
                    hard_issues.append(
                        "Brak pliku Ground Truth."
                    )
                elif self._sha256(gt_path) != gt_sha_db:
                    hard_issues.append(
                        "Zmieniła się zawartość Ground Truth."
                    )

                if (
                    str(
                        manifest_gt.get("relative_path") or ""
                    ).replace("\\", "/")
                    != gt_track_relative
                ):
                    hard_issues.append(
                        "Ścieżka GT manifestu nie zgadza się z rejestrem."
                    )
            if (
                str(manifest_gt.get("sha256") or "").lower()
                != gt_sha_db
            ):
                hard_issues.append(
                    "SHA-256 GT manifestu nie zgadza się z rejestrem."
                )
            if (
                str(manifest_gt.get("format") or "").lower()
                != gt_format_db
            ):
                hard_issues.append(
                    "Format GT manifestu nie zgadza się z rejestrem."
                )

        if set(seal_by_path) != set(expected_content):
            missing_from_seal = sorted(
                set(expected_content) - set(seal_by_path)
            )
            extra_in_seal = sorted(
                set(seal_by_path) - set(expected_content)
            )
            if missing_from_seal:
                hard_issues.append(
                    "seal.json nie obejmuje plików: "
                    + ", ".join(missing_from_seal[:10])
                )
            if extra_in_seal:
                hard_issues.append(
                    "seal.json obejmuje nieznane pliki: "
                    + ", ".join(extra_in_seal[:10])
                )

        actual_content: set[str] = set()
        for candidate in track_root.rglob("*"):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(
                track_root
            ).as_posix()
            if relative in {
                "track_manifest.json",
                "seal.json",
            }:
                continue
            actual_content.add(relative)

        extra_files = sorted(
            actual_content - set(expected_content)
        )
        missing_files = sorted(
            set(expected_content) - actual_content
        )
        if extra_files:
            hard_issues.append(
                "Zapieczętowany tor zawiera plik nieujęty "
                "w pieczęci: "
                + ", ".join(extra_files[:10])
            )
        if missing_files:
            hard_issues.append(
                "Zapieczętowany tor utracił plik: "
                + ", ".join(missing_files[:10])
            )

        if hard_issues:
            result_status = INTEGRITY_FAIL
            issues = tuple(hard_issues + unknown_issues)
        elif unknown_issues:
            result_status = INTEGRITY_UNKNOWN
            issues = tuple(unknown_issues)
        else:
            result_status = INTEGRITY_PASS
            issues = ()

        return TrackIntegrityResult(
            status=result_status,
            track_id=track_id,
            issues=issues,
            manifest_sha256=manifest_sha,
        )


    def get_experiment_workspace(
        self,
        track_id: str,
        *,
        create: bool = True,
    ) -> dict[str, str]:
        track = self._require_track(track_id)
        paths = experiment_workspace_for_track(
            self.workspace,
            dict(track),
        )
        if create:
            ensure_experiment_workspace(paths)
        return paths.as_dict()

    def ingest_member_source(
        self,
        track_id: str,
        source_path: Path | str,
        *,
        original_name: str | None = None,
    ) -> int:
        """Wprowadź obraz przez kontrolowany katalog źródeł eksperymentu."""

        track = self._require_status(
            track_id,
            STATUS_DRAFT,
        )
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise EvaluationTrackError(
                f"Brak pliku źródłowego: {source}"
            )

        name = str(original_name or source.name).strip()
        if not name or Path(name).name != name:
            raise EvaluationTrackError(
                "Nazwa obrazu musi być samą nazwą pliku."
            )

        source_sha = self._sha256(source)
        if not source_sha:
            raise EvaluationTrackError(
                f"Nie udało się policzyć SHA-256: {source}"
            )

        paths = ensure_experiment_workspace(
            experiment_workspace_for_track(
                self.workspace,
                dict(track),
            )
        )
        destination = paths.source_images / name
        created_staging_copy = False

        if destination.exists():
            destination_sha = self._sha256(destination)
            if destination_sha != source_sha:
                raise EvaluationTrackError(
                    "Katalog źródeł eksperymentu zawiera już "
                    f"inny plik o nazwie: {name}"
                )
        else:
            shutil.copy2(source, destination)
            created_staging_copy = True
            if self._sha256(destination) != source_sha:
                destination.unlink(missing_ok=True)
                raise EvaluationTrackError(
                    "Kopia źródłowa eksperymentu nie zgadza się "
                    "z wybranym plikiem."
                )

        try:
            return self.add_member(
                track_id,
                destination,
                original_name=name,
            )
        except Exception:
            if created_staging_copy:
                destination.unlink(missing_ok=True)
            raise

    def _sync_experiment_sources_from_members(
        self,
        track_id: str,
    ) -> int:
        """Uzupełnij staging źródeł dla DRAFT utworzonego starszą ścieżką."""

        track = self._require_status(
            track_id,
            STATUS_DRAFT,
        )
        members = self.repository.list_evaluation_track_members(
            track_id
        )
        if not members:
            return 0

        paths = ensure_experiment_workspace(
            experiment_workspace_for_track(
                self.workspace,
                dict(track),
            )
        )
        track_root = self._track_root(track)
        synced = 0

        for member in members:
            name = str(member["original_name"] or "").strip()
            expected_sha = str(
                member["sha256"] or ""
            ).strip().lower()
            relative = str(
                member["track_relative_path"] or ""
            ).strip()
            if not name or not relative or not expected_sha:
                raise EvaluationTrackError(
                    "Członek DRAFT-u ma niekompletne metadane."
                )

            source = track_root / relative
            if (
                not source.is_file()
                or self._sha256(source) != expected_sha
            ):
                raise EvaluationTrackError(
                    "Nie można odtworzyć źródła eksperymentu: "
                    f"{name}"
                )

            destination = paths.source_images / name
            if destination.exists():
                if self._sha256(destination) != expected_sha:
                    raise EvaluationTrackError(
                        "Źródło eksperymentu ma inną zawartość "
                        f"niż członek toru: {name}"
                    )
                continue

            shutil.copy2(source, destination)
            if self._sha256(destination) != expected_sha:
                destination.unlink(missing_ok=True)
                raise EvaluationTrackError(
                    "Nie udało się zsynchronizować źródła "
                    f"eksperymentu: {name}"
                )
            synced += 1

        return synced

    def activate_z2_context(
        self,
        track_id: str,
    ) -> dict[str, Any]:
        track = self._require_status(
            track_id,
            STATUS_DRAFT,
        )
        if str(track["target"] or "").strip().lower() != "plate":
            raise EvaluationTrackError(
                "Integracja eksperymentalna Z2 jest obecnie dostępna "
                "dla targetu plate/MT."
            )

        members = self.repository.list_evaluation_track_members(
            track_id
        )
        if not members:
            raise EvaluationTrackError(
                "Najpierw użyj „Dodaj obrazy”. "
                "Z2 może zostać uruchomione dopiero dla ustalonej "
                "puli obrazów eksperymentu."
            )

        self._sync_experiment_sources_from_members(track_id)
        return activate_z2_experiment_context(
            self.workspace,
            dict(track),
        )

    def deactivate_z2_context(
        self,
        *,
        track_id: str | None = None,
    ) -> bool:
        return clear_active_z2_experiment_context(
            self.workspace,
            track_id=track_id,
        )

    def delete_draft(self, track_id: str) -> None:
        # Usuń roboczy DRAFT wraz ze stagingiem eksperymentalnym.
        track = self._require_status(track_id, STATUS_DRAFT)
        track_root = self._track_root(track)
        staging = experiment_workspace_for_track(
            self.workspace,
            dict(track),
        )
        managed_paths = [
            track_root,
            staging.source_images.parent,
            staging.annotation_runs,
            staging.experiment_runs,
            staging.experiment_results,
        ]
        renamed: list[tuple[Path, Path]] = []

        try:
            for candidate in managed_paths:
                if not candidate.exists():
                    continue
                if not candidate.is_dir():
                    raise EvaluationTrackError(
                        f"Ścieżka robocza nie jest katalogiem: {candidate}"
                    )
                tombstone = candidate.with_name(
                    ".deleting__"
                    + candidate.name
                    + "__"
                    + uuid.uuid4().hex[:8]
                )
                candidate.rename(tombstone)
                renamed.append((candidate, tombstone))
        except Exception as exc:
            for original, tombstone in reversed(renamed):
                if tombstone.exists() and not original.exists():
                    try:
                        tombstone.rename(original)
                    except OSError:
                        pass
            if isinstance(exc, EvaluationTrackError):
                raise
            raise EvaluationTrackError(
                "Nie udało się przygotować DRAFT do bezpiecznego usunięcia."
            ) from exc

        try:
            self.repository.delete_draft_evaluation_track(track_id)
        except Exception as exc:
            for original, tombstone in reversed(renamed):
                if tombstone.exists() and not original.exists():
                    try:
                        tombstone.rename(original)
                    except OSError:
                        pass
            raise EvaluationTrackError(
                f"Nie udało się usunąć DRAFT: {exc}"
            ) from exc

        clear_active_z2_experiment_context(
            self.workspace,
            track_id=track_id,
        )

        leftovers = []
        for _original, tombstone in renamed:
            if not tombstone.exists():
                continue
            try:
                shutil.rmtree(tombstone)
            except OSError:
                leftovers.append(str(tombstone))
        if leftovers:
            raise EvaluationTrackError(
                "DRAFT usunięto z rejestru, ale pozostały katalogi robocze: "
                + "; ".join(leftovers)
            )

    def retire(self, track_id: str) -> None:
        self._require_status(track_id, STATUS_SEALED)
        integrity = self.verify_integrity(track_id)
        if not integrity.ok:
            raise EvaluationTrackError(
                "Nie można wycofać toru z uszkodzoną pieczęcią."
            )
        # Manifest i seal pozostają nietknięte: retirement jest stanem lifecycle w DB.
        self.repository.update_evaluation_track(track_id, status=STATUS_RETIRED)

    def clone_new_version(
        self,
        track_id: str,
        *,
        name: str | None = None,
    ) -> str:
        parent = self._require_track(track_id)
        if str(parent["status"] or "") not in {STATUS_SEALED, STATUS_RETIRED}:
            raise EvaluationTrackError(
                "Nową wersję można tworzyć tylko z toru SEALED/RETIRED."
            )
        integrity = self.verify_integrity(track_id)
        if not integrity.ok:
            raise EvaluationTrackError("Nie można klonować toru z uszkodzoną pieczęcią.")

        new_id = self.create_draft(
            name=str(name or parent["name"]),
            target=str(parent["target"]),
            purpose=str(parent["purpose"]),
            scope=str(parent["scope"]),
            owner_project_id=parent["owner_project_id"],
            reservation_policy=str(parent["reservation_policy"] or "none"),
            parent_track_id=track_id,
            version=int(parent["version"]) + 1,
        )

        parent_root = self._track_root(parent)
        for member in self.repository.list_evaluation_track_members(track_id):
            source_artifact_id = (
                str(member["source_artifact_id"] or "")
                or str(member["track_artifact_id"] or "")
                or None
            )
            self.add_member(
                new_id,
                parent_root / str(member["track_relative_path"]),
                source_image_id=str(member["source_image_id"]),
                source_artifact_id=source_artifact_id,
                original_name=str(member["original_name"]),
            )

        gt_relative = str(parent["gt_relative_path"] or "").strip()
        if gt_relative:
            self.set_ground_truth(
                new_id,
                self.workspace / gt_relative,
                gt_format=str(parent["gt_format"] or "cvat_xml"),
            )
        return new_id

    def build_controlled_reference(
        self,
        track_id: str,
        *,
        required_target: str | None = None,
        require_pose_corners: bool = False,
        require_manual_gt_complete: bool = False,
        require_independent_acquisition: bool = False,
    ) -> ControlledTrackReference:
        """Zbuduj zamrożony uchwyt tylko dla poprawnego toru SEALED."""

        track = self._require_status(track_id, STATUS_SEALED)
        integrity = self.verify_integrity(track_id)
        if not integrity.ok:
            raise EvaluationTrackError(
                "Tor nie może być użyty w eksperymencie kontrolowanym: "
                + "; ".join(
                    integrity.issues
                    or (integrity.status,)
                )
            )

        if required_target:
            normalized = self._normalize_target(required_target)
            if not normalized:
                raise EvaluationTrackError(
                    "Nieobsługiwany wymagany target: "
                    f"{required_target!r}."
                )
            if str(track["target"]) != normalized:
                raise EvaluationTrackError(
                    f"Tor ma target {track['target']}, "
                    f"wymagany jest {normalized}."
                )

        manifest = self._read_json(
            self._track_root(track)
            / "track_manifest.json"
        )
        verification = manifest.get("verification")
        if not isinstance(verification, Mapping):
            verification = {}

        pose_corner_ready = bool(
            verification.get("pose_corner_ready")
        )
        pose_corner_order = str(
            verification.get("pose_corner_order") or ""
        ).strip().lower()
        if require_pose_corners and (
            not pose_corner_ready
            or pose_corner_order
            != CORNER_ORDER_TL_TR_BR_BL
        ):
            raise EvaluationTrackError(
                "Tor nie ma zweryfikowanego GT z dokładnie "
                "czterema narożnikami zapisanymi w kolejności "
                "TL, TR, BR, BL."
            )

        manual_gt_complete = bool(
            verification.get("manual_gt_complete")
        )
        manual_gt_attestation_schema = str(
            verification.get(
                "manual_gt_attestation_schema"
            )
            or ""
        ).strip()
        manual_gt_attestation_statement = str(
            verification.get(
                "manual_gt_attestation_statement"
            )
            or ""
        ).strip()
        manual_gt_attested_at = str(
            verification.get("manual_gt_attested_at")
            or ""
        ).strip()

        independent_acquisition = bool(
            verification.get("independent_acquisition")
        )
        not_derived_from_training_data = bool(
            verification.get("not_derived_from_training_data")
        )
        acquisition_source_pool = str(
            verification.get("acquisition_source_pool") or ""
        ).strip()
        independent_acquisition_attestation_schema = str(
            verification.get(
                "independent_acquisition_attestation_schema"
            )
            or ""
        ).strip()
        independent_acquisition_attestation_statement = str(
            verification.get(
                "independent_acquisition_attestation_statement"
            )
            or ""
        ).strip()
        independent_acquisition_attested_at = str(
            verification.get("independent_acquisition_attested_at")
            or ""
        ).strip()
        independent_acquisition_valid = bool(
            independent_acquisition
            and not_derived_from_training_data
            and acquisition_source_pool
            and independent_acquisition_attestation_schema
            == INDEPENDENT_ACQUISITION_ATTESTATION_SCHEMA
            and independent_acquisition_attestation_statement
            == INDEPENDENT_ACQUISITION_ATTESTATION_STATEMENT
            and independent_acquisition_attested_at
        )

        if require_independent_acquisition and not independent_acquisition_valid:
            raise EvaluationTrackError(
                "Tor nie ma zapieczętowanego oświadczenia o niezależnym "
                "pozyskaniu obrazów i braku pochodzenia z train/val."
            )

        if require_manual_gt_complete and (
            not manual_gt_complete
            or manual_gt_attestation_schema
            != GT_COMPLETENESS_ATTESTATION_SCHEMA
            or manual_gt_attestation_statement
            != GT_COMPLETENESS_ATTESTATION_STATEMENT
            or not manual_gt_attested_at
        ):
            raise EvaluationTrackError(
                "Tor nie ma ręcznego, zapieczętowanego "
                "potwierdzenia kompletności Ground Truth. "
                "Przed eksperymentem controlled trzeba ręcznie "
                "sprawdzić wszystkie obrazy i potwierdzić, że GT "
                "zawiera wszystkie widoczne obiekty docelowe."
            )

        members = self.repository.list_evaluation_track_members(
            track_id
        )
        source_ids = tuple(
            str(row["source_image_id"] or "")
            for row in members
        )
        member_sha = tuple(
            str(row["sha256"] or "").lower()
            for row in members
        )
        if (
            not members
            or len(members)
            != int(track["member_count"] or 0)
            or any(not value for value in source_ids)
            or any(not value for value in member_sha)
        ):
            raise EvaluationTrackError(
                "Rejestr członków toru jest niekompletny."
            )

        return ControlledTrackReference(
            schema=CONTROLLED_REFERENCE_SCHEMA,
            track_id=track_id,
            version=int(track["version"]),
            target=str(track["target"]),
            purpose=str(track["purpose"]),
            scope=str(track["scope"]),
            manifest_sha256=str(
                track["manifest_sha256"] or ""
            ).lower(),
            seal_sha256=str(
                track["seal_sha256"] or ""
            ).lower(),
            gt_format=str(track["gt_format"] or ""),
            gt_sha256=str(
                track["gt_sha256"] or ""
            ).lower(),
            member_count=len(members),
            object_count=int(
                track["object_count"] or 0
            ),
            source_image_ids=source_ids,
            member_sha256=member_sha,
            pose_corner_ready=pose_corner_ready,
            pose_corner_order=pose_corner_order,
            manual_gt_complete=manual_gt_complete,
            manual_gt_attested_at=manual_gt_attested_at,
            manual_gt_attestation_schema=(
                manual_gt_attestation_schema
            ),
            manual_gt_attestation_statement=(
                manual_gt_attestation_statement
            ),
            independent_acquisition=independent_acquisition,
            not_derived_from_training_data=(
                not_derived_from_training_data
            ),
            acquisition_source_pool=acquisition_source_pool,
            independent_acquisition_attested_at=(
                independent_acquisition_attested_at
            ),
            independent_acquisition_attestation_schema=(
                independent_acquisition_attestation_schema
            ),
            independent_acquisition_attestation_statement=(
                independent_acquisition_attestation_statement
            ),
        )

    def list_tracks(
        self,
        *,
        target: str | None = None,
        purpose: str | None = None,
        status: str | None = None,
        include_retired: bool = False,
    ) -> list[dict[str, Any]]:
        normalized_target = (
            self._normalize_target(target)
            if str(target or "").strip()
            else None
        )
        if target and not normalized_target:
            raise EvaluationTrackError(
                f"Nieobsługiwany target toru: {target!r}."
            )
        rows = self.repository.list_evaluation_tracks(
            target=normalized_target,
            purpose=str(purpose or "").strip().lower() or None,
            status=str(status or "").strip().upper() or None,
            include_retired=bool(include_retired),
        )
        return [dict(row) for row in rows]

    def get_track(self, track_id: str) -> dict[str, Any]:
        row = self._require_track(track_id)
        return dict(row)

    def list_members(self, track_id: str) -> list[dict[str, Any]]:
        self._require_track(track_id)
        return [dict(row) for row in self.repository.list_evaluation_track_members(track_id)]

    def _verify_cvat_xml(
        self,
        track: Mapping[str, Any],
        members: list[Any],
        gt_path: Path,
    ) -> dict[str, Any]:
        try:
            root = ET.parse(gt_path).getroot()
        except (OSError, ET.ParseError) as exc:
            raise EvaluationTrackError(
                f"Nie można odczytać CVAT XML: {exc}"
            ) from exc

        image_nodes = root.findall(".//image")
        xml_names = [
            Path(str(node.get("name") or "")).name
            for node in image_nodes
        ]
        if len(xml_names) != len(set(xml_names)):
            raise EvaluationTrackError(
                "CVAT XML zawiera zduplikowane nazwy obrazów."
            )

        member_names = [
            str(row["original_name"] or "")
            for row in members
        ]
        missing = sorted(set(member_names) - set(xml_names))
        extra = sorted(set(xml_names) - set(member_names))
        if missing or extra:
            details = []
            if missing:
                details.append(
                    "brak w GT: " + ", ".join(missing[:10])
                )
            if extra:
                details.append(
                    "nadmiarowe w GT: " + ", ".join(extra[:10])
                )
            raise EvaluationTrackError(
                "Zestaw obrazów GT nie odpowiada torowi ("
                + "; ".join(details)
                + ")."
            )

        object_count = 0
        box_count = 0
        polygon_count = 0
        quad_polygon_count = 0
        ordered_quad_polygon_count = 0
        invalid_polygon_count = 0
        invalid_coordinate_polygon_count = 0
        degenerate_polygon_count = 0
        unordered_quad_polygon_count = 0
        images_without_objects = 0

        for node in image_nodes:
            boxes = node.findall("box")
            polygons = node.findall("polygon")
            box_count += len(boxes)
            polygon_count += len(polygons)
            shapes = len(boxes) + len(polygons)
            object_count += shapes
            if shapes == 0:
                images_without_objects += 1

            for polygon in polygons:
                raw_points = [
                    point
                    for point in str(
                        polygon.get("points") or ""
                    ).split(";")
                    if point.strip()
                ]
                if len(raw_points) != 4:
                    invalid_polygon_count += 1
                    continue

                quad_polygon_count += 1
                points = parse_quad_points(
                    str(polygon.get("points") or "")
                )
                if points is None:
                    invalid_coordinate_polygon_count += 1
                    continue
                if not quad_is_non_degenerate(points):
                    degenerate_polygon_count += 1
                    continue
                if is_canonical_quad_tl_tr_br_bl(points):
                    ordered_quad_polygon_count += 1
                else:
                    unordered_quad_polygon_count += 1

        if object_count <= 0:
            raise EvaluationTrackError(
                "GT nie zawiera żadnego obiektu."
            )
        if invalid_polygon_count:
            raise EvaluationTrackError(
                "GT zawiera polygon(y) o liczbie narożników "
                "innej niż 4."
            )
        if invalid_coordinate_polygon_count:
            raise EvaluationTrackError(
                "GT zawiera polygon(y) z niepoprawnymi lub "
                "nieskończonymi współrzędnymi."
            )
        if degenerate_polygon_count:
            raise EvaluationTrackError(
                "GT zawiera zdegenerowany polygon tablicy."
            )

        pose_corner_ready = bool(
            str(track["target"]) == "plate"
            and polygon_count > 0
            and box_count == 0
            and polygon_count == quad_polygon_count
            and polygon_count == ordered_quad_polygon_count
            and unordered_quad_polygon_count == 0
        )

        return {
            "format": "cvat_xml",
            "member_count": len(members),
            "object_count": object_count,
            "box_count": box_count,
            "polygon_count": polygon_count,
            "quad_polygon_count": quad_polygon_count,
            "ordered_quad_polygon_count": (
                ordered_quad_polygon_count
            ),
            "unordered_quad_polygon_count": (
                unordered_quad_polygon_count
            ),
            "invalid_coordinate_polygon_count": (
                invalid_coordinate_polygon_count
            ),
            "degenerate_polygon_count": (
                degenerate_polygon_count
            ),
            "images_without_objects": images_without_objects,
            "pose_corner_ready": pose_corner_ready,
            "pose_corner_order": (
                CORNER_ORDER_TL_TR_BR_BL
                if pose_corner_ready
                else ""
            ),
        }

    def _content_integrity(self, track_id: str) -> TrackIntegrityResult:
        track = self._require_track(track_id)
        track_root = self._track_root(track)
        issues: list[str] = []
        for member in self.repository.list_evaluation_track_members(track_id):
            path = track_root / str(member["track_relative_path"])
            if not path.exists():
                issues.append(f"Brak obrazu: {member['original_name']}")
                continue
            if self._sha256(path) != str(member["sha256"] or "").lower():
                issues.append(f"Zmieniono obraz: {member['original_name']}")
        gt_relative = str(track["gt_relative_path"] or "").strip()
        gt_sha = str(track["gt_sha256"] or "").strip().lower()
        if not gt_relative or not gt_sha:
            issues.append("Brak GT.")
        else:
            gt_path = self.workspace / gt_relative
            if not gt_path.exists():
                issues.append("Brak pliku GT.")
            elif self._sha256(gt_path) != gt_sha:
                issues.append("Zmieniono plik GT.")
        return TrackIntegrityResult(
            status=INTEGRITY_FAIL if issues else INTEGRITY_PASS,
            track_id=track_id,
            issues=tuple(issues),
        )

    def _write_manifest(
        self,
        track_id: str,
        *,
        verification: Mapping[str, Any] | None = None,
        status_override: str | None = None,
        verified_at_override: str | None = None,
        sealed_at_override: str | None = None,
        object_count_override: int | None = None,
    ) -> Path:
        track = self._require_track(track_id)
        track_root = self._track_root(track)
        manifest_path = track_root / "track_manifest.json"

        preserved_verification: dict[str, Any] = {}
        if verification is None and manifest_path.exists():
            try:
                old = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(old.get("verification"), Mapping):
                    preserved_verification = dict(old["verification"])
            except Exception:
                preserved_verification = {}

        members = [
            {
                "member_index": int(row["member_index"]),
                "source_image_id": str(row["source_image_id"]),
                "source_artifact_id": row["source_artifact_id"],
                "track_artifact_id": row["track_artifact_id"],
                "original_name": str(row["original_name"] or ""),
                "track_relative_path": str(row["track_relative_path"] or ""),
                "sha256": str(row["sha256"] or "").lower(),
            }
            for row in self.repository.list_evaluation_track_members(track_id)
        ]

        gt_relative = str(track["gt_relative_path"] or "").strip()
        gt_track_relative = ""
        if gt_relative:
            gt_path = self.workspace / gt_relative
            try:
                gt_track_relative = gt_path.relative_to(track_root).as_posix()
            except Exception:
                gt_track_relative = gt_relative

        payload = {
            "schema": TRACK_SCHEMA,
            "track_id": track_id,
            "name": str(track["name"]),
            "target": str(track["target"]),
            "purpose": str(track["purpose"]),
            "scope": str(track["scope"]),
            "status": str(status_override or track["status"]),
            "version": int(track["version"]),
            "parent_track_id": track["parent_track_id"],
            "reservation_policy": track["reservation_policy"],
            "member_count": int(track["member_count"] or len(members)),
            "object_count": int(
                object_count_override
                if object_count_override is not None
                else (track["object_count"] or 0)
            ),
            "created_at": track["created_at"],
            "verified_at": (
                verified_at_override
                if verified_at_override is not None
                else track["verified_at"]
            ),
            "sealed_at": (
                sealed_at_override
                if sealed_at_override is not None
                else track["sealed_at"]
            ),
            "ground_truth": {
                "format": str(track["gt_format"] or ""),
                "relative_path": gt_track_relative,
                "sha256": str(track["gt_sha256"] or "").lower(),
            },
            "members": members,
            "verification": dict(verification or preserved_verification),
        }
        self._atomic_json(manifest_path, payload)
        return manifest_path

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise EvaluationTrackError(
                f"Nie można odczytać {path.name}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise EvaluationTrackError(
                f"{path.name} nie zawiera obiektu JSON."
            )
        return payload

    def _require_track(self, track_id: str):
        row = self.repository.get_evaluation_track(str(track_id or "").strip())
        if row is None:
            raise EvaluationTrackError(f"Nie znaleziono toru: {track_id}")
        return row

    def _require_status(self, track_id: str, expected: str):
        row = self._require_track(track_id)
        actual = str(row["status"] or "")
        if actual != expected:
            raise EvaluationTrackError(
                f"Operacja wymaga statusu {expected}; aktualny status: {actual}."
            )
        return row

    def _track_root(self, track: Mapping[str, Any]) -> Path:
        relative = str(track["relative_path"] or "").strip()
        path = self.workspace / relative
        if self._is_within(path, self.root):
            return path
        if self._is_within(path, self.legacy_root):
            return path
        raise EvaluationTrackError(
            "Ścieżka toru wychodzi poza 10_experiments/tracks "
            "oraz legacy 10_evaluation_tracks."
        )

    def _workspace_relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.workspace.resolve()).as_posix()
        except Exception as exc:
            raise EvaluationTrackError(
                f"Artefakt toru musi znajdować się w Workspace: {path}"
            ) from exc

    @staticmethod
    def _normalize_target(target: str) -> str:
        raw = str(target or "").strip().lower()
        if raw in {"plate", "plates", "pose", "mt"}:
            return "plate"
        if raw in {"char", "chars", "character", "characters", "mz"}:
            return "char"
        if raw in {"vehicle", "vehicles"}:
            return "vehicle"
        return ""

    @staticmethod
    def _safe_slug(value: str) -> str:
        chars = []
        for char in str(value or "").strip():
            if char.isalnum() or char in {"-", "_"}:
                chars.append(char)
            elif char.isspace():
                chars.append("_")
            else:
                chars.append("_")
        result = "".join(chars).strip("_-")
        return result[:80] or "track"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except Exception:
            return ""
        return digest.hexdigest()

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    @staticmethod
    def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name("." + path.name + ".tmp")
        data = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        temp.write_bytes(data)
        temp.replace(path)
