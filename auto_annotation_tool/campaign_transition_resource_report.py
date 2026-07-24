"""Resource requirement reports for campaign graph transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .campaign_iteration_paths import normalize_iteration_path
from .campaign_resource_contracts import resource_contract_ready
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
        return resource_contract_ready(self.snapshot, required=bool(self.required))

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


def _snapshot_ready(snapshot: CampaignResourceSnapshot | None) -> bool:
    return resource_contract_ready(snapshot, required=True)


def _effective_requirement(
    resource: TransitionResourceSpec,
    *,
    specs: Sequence[CampaignTransitionSpec],
    snapshots: Mapping[str, CampaignResourceSnapshot],
    selected_path: str = "",
) -> str:
    requirement = str(resource.requirement or "optional").strip().lower() or "optional"
    if not any(str(getattr(spec, "key", "") or "") == "e1_to_e2_prepare_plate_annotations" for spec in specs):
        return requirement

    path = normalize_iteration_path(selected_path)
    canonical = normalize_campaign_resource_key(resource.key)
    image_snapshot = snapshots.get("images")
    plate_snapshot = snapshots.get("plate_run") or snapshots.get("approved_plates")
    images_ready = _snapshot_ready(image_snapshot)
    plates_ready = _snapshot_ready(plate_snapshot)

    if canonical == "images":
        if path == "plate_training":
            return "route_required_plate"
        if path == "char_from_images":
            return "alternative" if plates_ready else "route_required_char"
        return requirement
    if canonical == "plate_run":
        if path == "char_from_images":
            return "route_required_char" if plates_ready and not images_ready else "alternative"
        return requirement
    return requirement


def build_transition_resource_report(
    specs: Sequence[CampaignTransitionSpec] | Iterable[CampaignTransitionSpec],
    snapshots: Mapping[str, CampaignResourceSnapshot] | None,
    *,
    selected_path: str = "",
) -> TransitionResourceReport:
    snapshot_map = snapshots or {}
    spec_list = tuple(specs or ())
    rows: list[TransitionResourceReportRow] = []
    for canonical, resource in _best_resource_specs(spec_list).items():
        if str(resource.key or "").strip() == "approved_plates":
            snapshot = snapshot_map.get(resource.key)
        else:
            snapshot = snapshot_map.get(resource.key) or snapshot_map.get(canonical)
        requirement = _effective_requirement(
            resource,
            specs=spec_list,
            snapshots=snapshot_map,
            selected_path=selected_path,
        )
        rows.append(
            TransitionResourceReportRow(
                key=resource.key,
                canonical_key=canonical,
                label=campaign_resource_label(resource.key, resource.label),
                requirement=requirement,
                snapshot=snapshot,
            )
        )
    return TransitionResourceReport(tuple(rows))
