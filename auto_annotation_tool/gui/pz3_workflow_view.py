"""Presentation-only guidance derived from the existing PZ3 lifecycle."""
from dataclasses import dataclass
from ..registry.final_sample_policy import has_selected_sample


@dataclass(frozen=True)
class PZ3WorkflowViewState:
    step: str
    audit_label: str
    audit_tone: str
    primary_action: str
    status_text: str
    audit_button_label: str
    sample_selected: bool = False


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
