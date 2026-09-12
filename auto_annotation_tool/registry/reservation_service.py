"""Rezerwacje źródeł torów testowych i blokada przecieku do train/val."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import CONFIG
from .dataset_inventory import (
    LINEAGE_EXACT_HASH_ONLY,
    LINEAGE_KNOWN,
    LINEAGE_LEGACY_PARTIAL,
    build_dataset_image_lineage,
)
from .repository import RegistryRepository

RESERVATION_POLICY_TRAINING = "reserve_from_training"
RESERVATION_TYPE_TRAIN_VAL = "exclude_train_val"

CHECK_PASS = "PASS"
CHECK_FAIL = "FAIL"
CHECK_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReservationOverlap:
    relative_path: str
    split: str
    source_image_id: str
    artifact_sha256: str
    track_ids: tuple[str, ...]
    match_kind: str


@dataclass(frozen=True)
class TrainingReservationCheck:
    status: str
    dataset_path: str
    scanned_count: int = 0
    unknown_count: int = 0
    overlaps: tuple[ReservationOverlap, ...] = ()
    skipped: bool = False
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.status == CHECK_FAIL

    def message(self) -> str:
        if self.skipped:
            return self.reason or "Kontrola rezerwacji pominięta."
        if self.status == CHECK_FAIL:
            preview = ", ".join(
                f"{item.split}:{item.relative_path}"
                for item in self.overlaps[:6]
            )
            suffix = (
                f" (+{len(self.overlaps) - 6})"
                if len(self.overlaps) > 6
                else ""
            )
            return (
                "ZABLOKOWANO trening: train/val zawiera źródła "
                "zarezerwowane przez zapieczętowany tor testowy"
                + (f": {preview}{suffix}" if preview else ".")
            )
        if self.status == CHECK_UNKNOWN:
            return (
                "Nie wykryto jawnego przecieku, ale rodowód części danych "
                f"train/val nie pozwala na pełne potwierdzenie ({self.unknown_count} wpisów)."
            )
        return "Brak przecieku ze zarezerwowanych torów do train/val."


class TrainingReservationService:
    """Źródło prawdy dla rezerwacji final_test/ranking."""

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

    def sync(self) -> int:
        """Uzupełnij rezerwacje także dla torów SEALED sprzed ETAPU 7."""
        return self.repository.sync_all_training_reservations(
            reservation_type=RESERVATION_TYPE_TRAIN_VAL,
        )

    def check_training_dataset(
        self,
        dataset_path: Path | str,
        *,
        protected_splits: tuple[str, ...] = ("train", "val"),
    ) -> TrainingReservationCheck:
        root = Path(dataset_path)
        self.sync()

        reservation_rows = self.repository.list_active_training_reservations(
            reservation_type=RESERVATION_TYPE_TRAIN_VAL,
        )
        if not reservation_rows:
            return TrainingReservationCheck(
                status=CHECK_PASS,
                dataset_path=str(root),
                reason="Brak aktywnych rezerwacji train/val.",
            )

        reserved_by_source: dict[str, set[str]] = {}
        for row in reservation_rows:
            source_id = str(row["source_image_id"] or "").strip()
            track_id = str(row["track_id"] or "").strip()
            if source_id and track_id:
                reserved_by_source.setdefault(source_id, set()).add(track_id)

        reserved_by_sha: dict[str, tuple[str, tuple[str, ...]]] = {}
        for row in self.repository.list_active_reserved_artifacts(
            reservation_type=RESERVATION_TYPE_TRAIN_VAL,
        ):
            sha = str(row["sha256"] or "").strip().lower()
            source_id = str(row["source_image_id"] or "").strip()
            track_ids = tuple(
                sorted(
                    item
                    for item in str(row["track_ids"] or "").split(",")
                    if item
                )
            )
            if sha and source_id and track_ids:
                reserved_by_sha[sha] = (source_id, track_ids)

        lineage = build_dataset_image_lineage(root)
        protected = {
            str(value or "").strip().lower()
            for value in protected_splits
            if str(value or "").strip()
        }
        rows = [
            row
            for row in lineage
            if str(row.split or "").strip().lower() in protected
        ]

        if not rows:
            return TrainingReservationCheck(
                status=CHECK_UNKNOWN,
                dataset_path=str(root),
                scanned_count=0,
                unknown_count=1,
                reason=(
                    "Nie udało się zidentyfikować obrazów train/val "
                    "do kontroli rezerwacji."
                ),
            )

        overlaps: list[ReservationOverlap] = []
        unknown_count = 0

        for row in rows:
            source_id = str(row.source_image_id or "").strip()
            sha = str(row.artifact_sha256 or "").strip().lower()
            match_tracks: set[str] = set()
            match_source_id = source_id
            match_kind = ""

            if source_id in reserved_by_source:
                match_tracks.update(reserved_by_source[source_id])
                match_kind = "source_image_id"

            sha_match = reserved_by_sha.get(sha)
            if sha_match is not None:
                sha_source_id, sha_tracks = sha_match
                match_tracks.update(sha_tracks)
                match_source_id = sha_source_id
                match_kind = (
                    "source_image_id+artifact_sha256"
                    if match_kind
                    else "artifact_sha256"
                )

            if match_tracks:
                overlaps.append(
                    ReservationOverlap(
                        relative_path=str(row.relative_path or ""),
                        split=str(row.split or ""),
                        source_image_id=match_source_id,
                        artifact_sha256=sha,
                        track_ids=tuple(sorted(match_tracks)),
                        match_kind=match_kind,
                    )
                )
                continue

            if row.lineage_status in {
                LINEAGE_EXACT_HASH_ONLY,
                LINEAGE_LEGACY_PARTIAL,
            }:
                unknown_count += 1

        if overlaps:
            status = CHECK_FAIL
        elif unknown_count:
            status = CHECK_UNKNOWN
        else:
            status = CHECK_PASS

        return TrainingReservationCheck(
            status=status,
            dataset_path=str(root),
            scanned_count=len(rows),
            unknown_count=unknown_count,
            overlaps=tuple(overlaps),
        )


def check_training_dataset_reservations(
    dataset_path: Path | str,
    *,
    history_dir: Path | str | None = None,
    workspace_dir: Path | str | None = None,
) -> TrainingReservationCheck:
    """Runtime guard używany przez trener.

    Historie testowe/tymczasowe poza Workspace nie dotykają rejestru użytkownika.
    """

    workspace = Path(workspace_dir or CONFIG.WORKSPACE_DIR)
    if history_dir is not None and not _is_within(
        Path(history_dir),
        workspace,
    ):
        return TrainingReservationCheck(
            status=CHECK_PASS,
            dataset_path=str(dataset_path),
            skipped=True,
            reason="Historia treningu znajduje się poza Workspace.",
        )

    return TrainingReservationService(workspace).check_training_dataset(
        dataset_path
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False
