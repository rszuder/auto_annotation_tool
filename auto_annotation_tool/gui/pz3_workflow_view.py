"""Presentation-only guidance derived from the existing PZ3 lifecycle."""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class PZ3WorkflowViewState:
    step: str
    audit_label: str
    audit_tone: str
    primary_action: str
    status_text: str
    audit_button_label: str
    sample_selected: bool = False


def has_selected_sample(workspace, track, members):
    """Read one recorded selection; never scan images or alter the contract.

    A subset retained by the subsequent audit is still a curated sample.
    New images outside that selection require selecting the sample again.
    """
    try:
        data = json.loads((Path(workspace) / track["relative_path"] /
                           "sample_selection.json").read_text(encoding="utf-8"))
        selected = set(data["selected_member_sha256"])
        current = {row["sha256"] for row in members}
        return (data.get("track_id") == track["track_id"]
                and data.get("schema") == "alpr.experiment_sample_selection.v1"
                and bool(current) and current.issubset(selected))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def build_pz3_workflow_view_state(readiness, *, audit_state=None, sample_selected=False):
    state = audit_state or {}
    if not readiness.participants_ready:
        audit_label, tone = "czeka na wybór modeli", "muted"
    elif not readiness.members_present:
        audit_label, tone = "czeka na pulę obrazów", "muted"
    elif readiness.audit_current:
        audit_label, tone = "aktualny", "success"
    elif state.get("audit_id"):
        audit_label, tone = "wymaga ponowienia", "warning"
    else:
        audit_label, tone = "do wykonania", "info"
    audit_button = "Sprawdź finalną próbę" if sample_selected else "Sprawdź niezależność puli"

    def view(step, action, text):
        return PZ3WorkflowViewState(step, audit_label, tone, action, text,
                                   audit_button, sample_selected)

    if not readiness.status:
        return view("", "", "Wybierz tor lub utwórz nowy eksperyment.")
    if readiness.sealed:
        return view("COMPARE", "btn_compare", "Eksperyment zapieczętowany. Następny krok: porównaj modele.")
    if readiness.status == "RETIRED":
        return view("", "", "Tor wycofany. Wyniki pozostają w historii.")
    if readiness.requires_audit and not readiness.participants_ready:
        return view("SELECT_MODELS", "btn_participants", "Następny krok: wybierz modele do eksperymentu.")
    if not readiness.members_present:
        return view("ADD_IMAGES", "btn_add_images", "Następny krok: dodaj obrazy do puli testowej.")
    if readiness.requires_audit and not readiness.audit_current:
        if sample_selected:
            return view("REAUDIT_SAMPLE", "btn_audit_sample",
                        "Finalna próba wymaga ponownego sprawdzenia. Następny krok: sprawdź finalną próbę.")
        return view("AUDIT_POOL", "btn_audit_pool",
                    "Pula gotowa. Następny krok: sprawdź jej niezależność względem train/val wybranych modeli.")
    if readiness.can_seal:
        return view("SEAL", "btn_seal", "Ground Truth zweryfikowany. Następny krok: zapieczętuj eksperyment.")
    if readiness.gt_exists:
        return view("VERIFY", "btn_verify", "Ground Truth gotowy. Następny krok: zweryfikuj eksperyment.")
    if (readiness.target == "plate" and readiness.participants_ready
            and readiness.audit_current and not sample_selected):
        return view("SELECT_SAMPLE", "btn_sample_selection",
                    "Pula sprawdzona. Następny krok: wybierz próbę do eksperymentu.")
    return view("PREPARE_GT", "btn_prepare_z2" if readiness.target == "plate" else "btn_set_gt",
                "Następny krok: przygotuj Ground Truth lub wczytaj gotowy plik.")
