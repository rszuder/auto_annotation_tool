"""Warunki przygotowania toru wyliczane z istniejącego rejestru."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TrackReadiness:
    status: str
    target: str
    requires_audit: bool
    participants_ready: bool
    members_present: bool
    audit_current: bool
    gt_exists: bool
    gt_verified: bool
    sealed: bool

    @property
    def pool_ready(self):
        return self.members_present and (
            not self.requires_audit or (self.participants_ready and self.audit_current)
        )

    @property
    def can_add_images(self):
        return self.status == "DRAFT" and (not self.requires_audit or self.participants_ready)

    @property
    def can_audit(self):
        return self.status in {"DRAFT", "VERIFIED"} and self.members_present and self.participants_ready

    @property
    def can_prepare_gt(self):
        return self.status == "DRAFT" and self.pool_ready

    @property
    def can_verify(self):
        return self.can_prepare_gt and self.gt_exists

    @property
    def can_seal(self):
        return self.status == "VERIFIED" and self.pool_ready and self.gt_verified

    @property
    def next_step(self):
        if not self.status:
            return "Wybierz tor lub utwórz nowy eksperyment."
        if self.sealed:
            return "Eksperyment zamrożony. Możesz uruchomić porównanie uczestników."
        if self.status == "RETIRED":
            return "Tor wycofany; wyniki pozostają w historii."
        if self.requires_audit and not self.participants_ready:
            return "Wybierz modele uczestniczące w eksperymencie."
        if not self.members_present:
            return "Dodaj wspólną pulę obrazów."
        if self.requires_audit and not self.audit_current:
            return "Audyt wymaga odświeżenia. Użyj „Audytuj pulę” przed pracą nad GT."
        if not self.gt_exists:
            return "Przygotuj Ground Truth i zapisz je w torze."
        if not self.gt_verified:
            return "Sprawdź kompletność GT i uruchom weryfikację."
        return "GT zweryfikowane. Zapieczętuj eksperyment."


def track_readiness(track, *, participant_count=0, member_count=0,
                    audit_state=None, gt_exists=False, verification=None):
    track = track or {}
    status = str(track.get("status") or "").upper()
    requires_audit = str(track.get("purpose") or "").lower() in {"ranking", "final_test"}
    return TrackReadiness(
        status=status, target=str(track.get("target") or "").lower(),
        requires_audit=requires_audit,
        participants_ready=participant_count > 0,
        members_present=member_count > 0,
        audit_current=(audit_state or {}).get("status") == "CURRENT",
        gt_exists=bool(gt_exists),
        gt_verified=bool(gt_exists and status in {"VERIFIED", "SEALED", "RETIRED"}
                         and (not requires_audit or (verification or {}).get("manual_gt_complete"))),
        sealed=status == "SEALED",
    )
