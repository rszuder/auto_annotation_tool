"""Resource requirement reports for campaign graph transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .campaign_resource_catalog import campaign_resource_label, normalize_campaign_resource_key
from .campaign_resource_state import CampaignResourceSnapshot
from .campaign_transition_specs import CampaignTransitionSpec, TransitionResourceSpec


REQUIREMENT_PRIORITY = {
    "required": 5,
    "route_required": 5,
    "route_required_plate": 5,
    "route_required_char": 5,
    "alternative": 4,
    "optional": 3,
    "disabled": 1,
}


@dataclass(frozen=True)
class TransitionResourceReportRow:
    key: str
    canonical_key: str
    label: str
    requirement: str
    snapshot: CampaignResourceSnapshot | None = None

    @property
    def required(self) -> bool:
        return self.requirement in {"required", "route_required", "route_required_plate", "route_required_char"}

    @property
    def enabled(self) -> bool:
        return self.requirement != "disabled"

    @property
    def present(self) -> bool:
        if self.snapshot is None:
            return False
        tone = str(self.snapshot.tone or "").strip().lower()
        if self.required:
            if tone == "success":
                return True
            if tone in {"warning", "muted", "error", "danger", ""}:
                return False
        if self.key == "approved_plates":
            return tone == "success"
        if self.canonical_key == "char_dataset":
            return tone == "success"
        return bool(
            self.snapshot.has_source
            or self.snapshot.counter_value > 0
            or tone == "success"
        )

    @property
    def blocking_missing(self) -> bool:
        return bool(self.enabled and self.required and not self.present)


@dataclass(frozen=True)
class TransitionResourceReport:
    rows: tuple[TransitionResourceReportRow, ...]

    @property
    def missing_required(self) -> tuple[TransitionResourceReportRow, ...]:
        return tuple(row for row in self.rows if row.blocking_missing)

    @property
    def missing_required_labels(self) -> tuple[str, ...]:
        return tuple(row.label for row in self.missing_required)

    @property
    def required_ready(self) -> bool:
        return not self.missing_required

    def status_text(self) -> str:
        missing = self.missing_required_labels
        if not missing:
            return "Wymagane zasoby tej bramki są dostępne."
        return "Brakuje: " + ", ".join(missing) + "."

    def compact_status(self) -> str:
        missing = self.missing_required
        missing_count = len(missing)
        if missing_count <= 0:
            return "OK"
        labels = []
        for row in missing:
            label = str(row.label or row.canonical_key or row.key or "").strip()
            if " - " in label:
                label = label.split(" - ", 1)[1].strip()
            labels.append(label or "zasób")
        if missing_count == 1:
            return f"BRAK: {labels[0]}"
        visible = ", ".join(labels[:2])
        if missing_count > 2:
            visible = f"{visible} +{missing_count - 2}"
        return f"BRAK: {visible}"


def _best_resource_specs(specs: Iterable[CampaignTransitionSpec]) -> dict[str, TransitionResourceSpec]:
    result: dict[str, TransitionResourceSpec] = {}
    for spec in specs:
        for resource in spec.resources:
            canonical = normalize_campaign_resource_key(resource.key)
            previous = result.get(canonical)
            previous_priority = REQUIREMENT_PRIORITY.get(str(getattr(previous, "requirement", "") or "").lower(), 0)
            current_priority = REQUIREMENT_PRIORITY.get(str(resource.requirement or "").lower(), 0)
            if previous is None or current_priority >= previous_priority:
                result[canonical] = resource
    return result


def build_transition_resource_report(
    specs: Sequence[CampaignTransitionSpec] | Iterable[CampaignTransitionSpec],
    snapshots: Mapping[str, CampaignResourceSnapshot] | None,
) -> TransitionResourceReport:
    snapshot_map = snapshots or {}
    rows: list[TransitionResourceReportRow] = []
    for canonical, resource in _best_resource_specs(specs).items():
        if str(resource.key or "").strip() == "approved_plates":
            snapshot = snapshot_map.get(resource.key)
        else:
            snapshot = snapshot_map.get(resource.key) or snapshot_map.get(canonical)
        rows.append(
            TransitionResourceReportRow(
                key=resource.key,
                canonical_key=canonical,
                label=campaign_resource_label(resource.key, resource.label),
                requirement=str(resource.requirement or "optional").strip().lower() or "optional",
                snapshot=snapshot,
            )
        )
    return TransitionResourceReport(tuple(rows))
