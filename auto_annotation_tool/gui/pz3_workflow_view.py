"""Deterministyczna prezentacja lifecycle PZ3."""
from dataclasses import dataclass
from ..registry.final_sample_policy import has_selected_sample


@dataclass(frozen=True)
class PZ3WorkflowViewState:
    step: str
    audit_label: str
    audit_tone: str
    primary_action: str
    status_text: str
    audit_button_label: str = "Sprawdź niezależność puli"
    sample_selected: bool = False
    sample_working: bool = False
    sample_selected_count: int = 0
    label_count: int = 0
    assigned_count: int = 0
    unlabeled_count: int = 0
    can_select_participants: bool = False
    can_add_images: bool = False
    can_audit_pool: bool = False
    can_edit_sample: bool = False
    can_finalize_sample: bool = False
    can_prepare_gt: bool = False
    can_set_gt: bool = False
    can_verify: bool = False
    can_seal: bool = False
    can_compare: bool = False


def build_pz3_workflow_view_state(
    readiness,
    *,
    audit_state=None,
    sample_selected=False,
    sample_review=None,
):
    state = audit_state or {}
    review = sample_review or {}
    working = review.get("status") == "WORKING"
    selected_count = int(review.get("selected_count") or 0)
    label_count = int(review.get("label_count") or 0)
    assigned_count = int(review.get("assigned_count") or 0)
    unlabeled_count = int(review.get("unlabeled_count") or 0)

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

    draft = readiness.status == "DRAFT"
    locked_final = bool(sample_selected)
    no_gt = not readiness.gt_exists
    requires_sample = readiness.target == "plate" and readiness.requires_audit

    can_participants = draft and not locked_final and no_gt
    can_add_images = (
        draft
        and (not readiness.requires_audit or readiness.participants_ready)
        and not locked_final
        and no_gt
    )
    can_audit = (
        draft and readiness.members_present and readiness.participants_ready
        and not readiness.audit_current and not locked_final and no_gt
    )
    can_edit_sample = (
        draft and requires_sample and readiness.participants_ready
        and readiness.members_present and readiness.audit_current
        and not locked_final and no_gt
    )
    can_finalize = can_edit_sample and working and selected_count > 0
    can_gt = (
        draft and readiness.audit_current and locked_final
        if requires_sample else readiness.can_prepare_gt
    )
    can_verify = draft and readiness.gt_exists and (
        not readiness.requires_audit or readiness.audit_current
    )
    can_seal = readiness.can_seal
    can_compare = readiness.sealed

    def view(step, action, text):
        return PZ3WorkflowViewState(
            step=step,
            audit_label=audit_label,
            audit_tone=tone,
            primary_action=action,
            status_text=text,
            sample_selected=bool(sample_selected),
            sample_working=working,
            sample_selected_count=selected_count,
            label_count=label_count,
            assigned_count=assigned_count,
            unlabeled_count=unlabeled_count,
            can_select_participants=can_participants,
            can_add_images=can_add_images,
            can_audit_pool=can_audit,
            can_edit_sample=can_edit_sample,
            can_finalize_sample=can_finalize,
            can_prepare_gt=can_gt,
            can_set_gt=can_gt,
            can_verify=can_verify,
            can_seal=can_seal,
            can_compare=can_compare,
        )

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
            return view(
                "AUDIT_INCONSISTENT", "",
                "Finalna próba ma nieaktualny audyt. Nie wykonuj drugiego audytu próbki; sprawdź historię zmian draftu.",
            )
        return view(
            "AUDIT_POOL", "btn_audit_pool",
            "Następny krok: wykonaj audyt niezależności szerokiej puli, "
            "ponieważ pula lub modele zmieniły się.",
        )
    if readiness.can_seal:
        return view("SEAL", "btn_seal", "Ground Truth zweryfikowany. Następny krok: zapieczętuj eksperyment.")
    if readiness.gt_exists:
        return view("VERIFY", "btn_verify", "Ground Truth gotowy. Następny krok: zweryfikuj eksperyment.")

    if requires_sample:
        if sample_selected:
            return view("PREPARE_GT", "btn_prepare_z2", "Finalna próba jest gotowa. Następny krok: przygotuj Ground Truth.")
        if working:
            return view(
                "EDIT_SAMPLE",
                "btn_finalize_sample" if selected_count > 0 else "btn_sample_selection",
                f"Próba robocza: {selected_count} obrazów · etykiety: {label_count}. "
                "Możesz ją dalej edytować albo sfinalizować.",
            )
        return view("SELECT_SAMPLE", "btn_sample_selection", "Pula sprawdzona. Następny krok: wybierz roboczą próbę do eksperymentu.")

    return view(
        "PREPARE_GT",
        "btn_prepare_z2" if readiness.target == "plate" else "btn_set_gt",
        "Następny krok: przygotuj Ground Truth lub wczytaj gotowy plik.",
    )
