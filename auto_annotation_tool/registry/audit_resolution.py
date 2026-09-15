"""Pure, per-image decisions for a participant-relative audit."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from .participant_pool_audit import (
    ParticipantPoolAuditReport, STATUS_CLEAN, STATUS_DEPENDENT,
    STATUS_SUSPECT, STATUS_UNKNOWN,
)


def audit_path_key(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(path))


@dataclass(frozen=True)
class AuditResolution:
    cancelled: bool
    accepted_clean: tuple[Path, ...]
    accepted_suspects: tuple[Path, ...]
    rejected_dependent: tuple[Path, ...]
    rejected_unknown: tuple[Path, ...]
    rejected_suspects: tuple[Path, ...]
    unresolved: tuple[Path, ...]
    report: ParticipantPoolAuditReport

    @property
    def accepted_paths(self) -> tuple[Path, ...]:
        keys = {audit_path_key(path) for path in self.accepted_clean + self.accepted_suspects}
        return tuple(Path(item.path) for item in self.report.candidates
                     if audit_path_key(item.path) in keys)

    @property
    def rejected_paths(self) -> tuple[Path, ...]:
        return self.rejected_dependent + self.rejected_unknown + self.rejected_suspects

    @property
    def ready(self) -> bool:
        return not self.cancelled and not self.unresolved

    def decision_rows(self) -> list[dict]:
        actions = {}
        for paths, action in (
            (self.accepted_clean, "accept_clean"),
            (self.accepted_suspects, "manual_accept_suspect"),
            (self.rejected_suspects, "manual_reject_suspect"),
            (self.rejected_dependent, "reject_dependent"),
            (self.rejected_unknown, "reject_unknown"),
            (self.unresolved, "unresolved"),
        ):
            actions.update({audit_path_key(path): action for path in paths})
        return [
            {"path": item.path, "sha256": item.sha256, "status": item.common_status,
             "decision": actions[audit_path_key(item.path)]}
            for item in self.report.candidates
        ]

    def validate(self) -> None:
        choices = {audit_path_key(path): "accept" for path in self.accepted_suspects}
        choices.update({audit_path_key(path): "reject" for path in self.rejected_suspects})
        if self != resolve_audit(self.report, choices, cancelled=self.cancelled):
            raise ValueError("Decyzje nie odpowiadają diagnozie audytu.")
        if not self.ready:
            raise ValueError("Audyt anulowano lub pozostały obrazy bez decyzji.")


def resolve_audit(
    report: ParticipantPoolAuditReport,
    decisions: Mapping[Path | str, str] | None = None,
    *,
    cancelled: bool = False,
) -> AuditResolution:
    choices = {audit_path_key(path): action for path, action in (decisions or {}).items()}
    candidates = {audit_path_key(item.path): item for item in report.candidates}
    for key, choice in choices.items():
        if key not in candidates or candidates[key].common_status != STATUS_SUSPECT:
            raise ValueError("Ręczna akceptacja/odrzucenie dotyczy tylko obrazów wymagających weryfikacji.")
        if choice not in {"accept", "reject"}:
            raise ValueError("Nieprawidłowa decyzja dla obrazu.")
    clean, accepted, dependent, unknown, rejected, unresolved = [], [], [], [], [], []
    for item in report.candidates:
        path = Path(item.path)
        if item.common_status == STATUS_CLEAN:
            clean.append(path)
        elif item.common_status == STATUS_DEPENDENT:
            dependent.append(path)
        elif item.common_status == STATUS_SUSPECT:
            choice = choices.get(audit_path_key(path))
            (accepted if choice == "accept" else rejected if choice == "reject" else unresolved).append(path)
        else:
            unknown.append(path)
    return AuditResolution(cancelled, tuple(clean), tuple(accepted), tuple(dependent),
                           tuple(unknown), tuple(rejected), tuple(unresolved), report)
