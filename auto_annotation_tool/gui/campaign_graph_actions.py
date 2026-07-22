"""GUI-side executor for campaign graph actions.

The campaign graph and state machine stay UI-agnostic. This module is the thin
bridge that maps graph action names to existing wizard callbacks while we
gradually retire ad-hoc widget commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..campaign_manager import CAMPAIGN
from ..config import logger
from ..campaign_iteration_paths import (
    STEP1_ITERATION_PATHS,
    iteration_path_target,
    normalize_iteration_path,
)
from .z2_shared_ui import campaign_visible_gate_id


@dataclass(frozen=True)
class CampaignGraphActionResult:
    ok: bool
    action: str
    message: str = ""


def _safe_update_status(host: Any, message: str, tone: str = "info") -> None:
    try:
        app = getattr(host, "app", None)
        if app is not None:
            app.update_status(message, tone)
    except Exception:
        pass


def _safe_refresh_wizard(host: Any) -> None:
    try:
        host._refresh_active_project_wizard_only()
        return
    except Exception:
        pass
    try:
        host._refresh_dashboard()
    except Exception:
        pass


def _execute_set_iteration_path(host: Any, payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    normalized_path = normalize_iteration_path(
        payload.get("path_key")
        or payload.get("iteration_path")
        or payload.get("path")
    )
    target = iteration_path_target(normalized_path)
    if not normalized_path or target not in {"plate", "char"}:
        return CampaignGraphActionResult(False, "set_iteration_path", "Nieznana ścieżka E1.")

    try:
        previous_target = str(host._get_iteration_target() or "").strip().lower()
    except Exception:
        previous_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()

    if previous_target in {"plate", "char"} and previous_target != target:
        try:
            reason = str(host._get_iteration_target_lock_reason() or "").strip()
        except Exception:
            reason = ""
        if reason:
            _safe_update_status(host, reason, "info")
            return CampaignGraphActionResult(False, "set_iteration_path", reason)

    lightweight_refresh = bool(payload.get("refresh") is False or payload.get("lightweight") is True)

    if previous_target != target and not lightweight_refresh:
        chooser = getattr(host, "_choose_step1_iteration_target", None)
        if callable(chooser):
            chooser(target)
        else:
            CAMPAIGN.set_iteration_target(target)
    elif previous_target != target:
        CAMPAIGN.set_iteration_target(target)
        try:
            target_var = getattr(host, "_wizard_step2_target_var", None)
            if target_var is not None:
                target_var.set(target)
        except Exception:
            pass

    try:
        CAMPAIGN.set_iteration_path(normalized_path)
        if str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved":
            CAMPAIGN.set_current_step(1)
    except Exception as exc:
        logger.error(f"Nie udało się wykonać akcji grafu set_iteration_path: {exc}")
        return CampaignGraphActionResult(False, "set_iteration_path", "Nie udało się zapisać ścieżki E1.")

    if not lightweight_refresh:
        _safe_refresh_wizard(host)
    path_title = str(STEP1_ITERATION_PATHS.get(normalized_path, {}).get("title") or normalized_path)
    message = f"Wybrano ścieżkę E1: {path_title}."
    _safe_update_status(host, message, "info")
    return CampaignGraphActionResult(True, "set_iteration_path", message)


def _execute_approve_step1(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method(
        host,
        "approve_step1",
        "_approve_step1_from_wizard",
        success_message="E1 przekazano do zatwierdzenia.",
        error_message="Nie udało się zatwierdzić E1.",
    )


def _execute_approve_step1_ready_plates(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    method = getattr(host, "_approve_step1_with_existing_char_material", None)
    if not callable(method):
        return CampaignGraphActionResult(
            False,
            "approve_step1_ready_plates",
            "Brak akcji zatwierdzania T03.",
        )
    try:
        CAMPAIGN.set_iteration_path("char_from_ready_plates")
    except Exception as exc:
        logger.error(f"Nie udało się ustawić ścieżki T03 przed zatwierdzeniem: {exc}")
        return CampaignGraphActionResult(
            False,
            "approve_step1_ready_plates",
            "Nie udało się wybrać ścieżki T03. Odśwież projekt i spróbuj ponownie.",
        )
    before_step = int(CAMPAIGN.get_current_step() or 1)
    try:
        result = method()
    except Exception as exc:
        logger.error(f"Nie udało się wykonać akcji grafu approve_step1_ready_plates: {exc}")
        return CampaignGraphActionResult(
            False,
            "approve_step1_ready_plates",
            "Nie udało się zatwierdzić T03.",
        )
    after_step = int(CAMPAIGN.get_current_step() or before_step)
    if bool(result) and after_step >= 3:
        try:
            CAMPAIGN.set_iteration_path("char_from_ready_plates")
            if str(CAMPAIGN.get_step1_status() or "").strip().lower() != "approved":
                CAMPAIGN.approve_step1()
            if str(CAMPAIGN.get_step2_status() or "").strip().lower() != "approved":
                CAMPAIGN.approve_step2()
            CAMPAIGN.set_current_step(3)
            after_step = 3
        except Exception as exc:
            logger.error(f"Nie udało się znormalizować stanu po zatwierdzeniu T03: {exc}")
            return CampaignGraphActionResult(
                False,
                "approve_step1_ready_plates",
                "T03 została potwierdzona, ale nie udało się przejść do E3. Odśwież projekt i spróbuj ponownie.",
            )
    if not bool(result) or after_step < 3:
        return CampaignGraphActionResult(
            False,
            "approve_step1_ready_plates",
            "T03 nie została zatwierdzona. Najpierw potrzebne jest źródło tablic: AT z importu albo poprzedniej iteracji spełniające minimum.",
        )
    return CampaignGraphActionResult(
        True,
        "approve_step1_ready_plates",
        "T03 zatwierdzona. Potwierdzono źródło tablic i przejście dalej do znaków.",
    )


def _execute_host_method(
    host: Any,
    action: str,
    method_name: str,
    *,
    success_message: str,
    error_message: str,
) -> CampaignGraphActionResult:
    method = getattr(host, method_name, None)
    if not callable(method):
        return CampaignGraphActionResult(False, action, f"Brak akcji: {method_name}.")
    try:
        method()
    except Exception as exc:
        logger.error(f"Nie udało się wykonać akcji grafu {action}: {exc}")
        return CampaignGraphActionResult(False, action, error_message)
    return CampaignGraphActionResult(True, action, success_message)


def _graph_context_from_payload(payload: Mapping[str, Any]) -> dict:
    context = dict(payload.get("context") or payload.get("preferred_source_context") or {})
    for key in (
        "source",
        "graph_edge_key",
        "graph_gate_id",
        "graph_gate_label",
        "graph_transition_title",
        "graph_transition_source",
        "graph_transition_target",
        "graph_path_key",
    ):
        if key not in context and payload.get(key) not in (None, ""):
            context[key] = payload.get(key)
    return context


def _execute_host_method_with_context(
    host: Any,
    action: str,
    method_name: str,
    payload: Mapping[str, Any],
    *,
    success_message: str,
    error_message: str,
) -> CampaignGraphActionResult:
    method = getattr(host, method_name, None)
    if not callable(method):
        return CampaignGraphActionResult(False, action, f"Brak akcji: {method_name}.")
    context = _graph_context_from_payload(payload)
    try:
        method(context)
    except Exception as exc:
        logger.error(f"Nie udało się wykonać akcji grafu {action}: {exc}")
        return CampaignGraphActionResult(False, action, error_message)
    return CampaignGraphActionResult(True, action, success_message)


def _execute_open_z2_campaign_context(host: Any, payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    method = getattr(host, "_step_goto_auto_annotation", None)
    if not callable(method):
        return CampaignGraphActionResult(False, "open_z2_campaign_context", "Brak akcji: _step_goto_auto_annotation.")
    context = _graph_context_from_payload(payload)
    try:
        method(preferred_source_context=context)
    except Exception as exc:
        logger.error(f"Nie udało się wykonać akcji grafu open_z2_campaign_context: {exc}")
        return CampaignGraphActionResult(False, "open_z2_campaign_context", "Nie udało się otworzyć Z2.")
    return CampaignGraphActionResult(
        True,
        "open_z2_campaign_context",
        "Z2 przekazano do otwarcia w kontekście kampanii.",
    )


def _execute_open_z2_step2_review(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method_with_context(
        host,
        "open_z2_step2_review",
        "_step_open_z2_from_step2_review",
        _payload,
        success_message="Z2 przekazano do przeglądu E2.",
        error_message="Nie udało się otworzyć Z2 w przeglądzie E2.",
    )


def _execute_open_z2_step3_repair(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method_with_context(
        host,
        "open_z2_step3_repair",
        "_step_open_z2_repair_from_later_stage",
        _payload,
        success_message="Z2 przekazano do trybu uzupełniania tablic.",
        error_message="Nie udało się otworzyć Z2 w trybie uzupełniania tablic.",
    )


def _execute_return_to_z2_review(host: Any, payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    method = getattr(host, "_step_return_to_annotation_review", None)
    if not callable(method):
        return CampaignGraphActionResult(False, "return_to_z2_review", "Brak akcji powrotu do Z2.")
    mark_rework = bool(payload.get("mark_step3_rework", True))
    context = _graph_context_from_payload(payload)
    try:
        method(mark_step3_rework=mark_rework, preferred_source_context=context)
    except Exception as exc:
        logger.error(f"Nie udało się wykonać akcji grafu return_to_z2_review: {exc}")
        return CampaignGraphActionResult(False, "return_to_z2_review", "Nie udało się wrócić do Z2.")
    return CampaignGraphActionResult(True, "return_to_z2_review", "Z2 przekazano do otwarcia.")


def _execute_approve_step2(host: Any, payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    context = _graph_context_from_payload(payload)
    gate_id = str(context.get("graph_gate_id") or "").strip().upper()
    visible_gate_id = campaign_visible_gate_id(gate_id) or gate_id
    target = str(context.get("graph_transition_target") or "").strip().upper()
    success_message = "Bramka została przekazana do zatwierdzenia."
    if target == "E4T" or gate_id == "T05":
        success_message = f"Bramka {visible_gate_id} zatwierdzona. Odblokowano E4T, czyli trening modelu tablic."
    elif target == "E3" or gate_id == "T04":
        success_message = f"Bramka {visible_gate_id} zatwierdzona. Odblokowano E3, czyli pracę nad znakami."

    return _execute_host_method_with_context(
        host,
        "approve_step2",
        "_approve_step2_from_wizard",
        payload,
        success_message=success_message,
        error_message="Nie udało się zatwierdzić E2.",
    )


def _execute_validate_and_adopt_annotations(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method(
        host,
        "validate_and_adopt_annotations",
        "_import_project_start_plate_run",
        success_message="Import/adopcja anotacji została przekazana do E1.",
        error_message="Nie udało się uruchomić importu/adopcji anotacji.",
    )


def _execute_continue_z3(host: Any, payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method_with_context(
        host,
        "continue_z3",
        "_step_continue_characters_from_ready_source",
        payload,
        success_message="Z3 przekazano do kontynuacji na gotowym źródle.",
        error_message="Nie udało się kontynuować pracy w Z3.",
    )


def _execute_open_z3(host: Any, payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method_with_context(
        host,
        "open_z3",
        "_step_goto_characters",
        payload,
        success_message="Z3 przekazano do otwarcia.",
        error_message="Nie udało się otworzyć Z3.",
    )


def _execute_open_z3_detect(host: Any, payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method_with_context(
        host,
        "open_z3_detect",
        "_step_goto_characters_detect",
        payload,
        success_message="Z3/PZ2 przekazano do pracy nad znakami.",
        error_message="Nie udało się otworzyć Z3/PZ2.",
    )


def _execute_approve_step3(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method(
        host,
        "approve_step3",
        "_approve_step3_from_wizard",
        success_message="Bramka T05 zatwierdzona. Odblokowano E4Z, czyli trening modelu znaków.",
        error_message="Nie udało się zatwierdzić E3.",
    )


def _execute_open_z4(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method(
        host,
        "open_z4",
        "_step_goto_training",
        success_message="Z4/PZ2 przekazano do treningu albo do przygotowania brakującego wariantu.",
        error_message="Nie udało się otworzyć treningu w Z4.",
    )


def _execute_open_z4_dataset(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method(
        host,
        "open_z4_dataset",
        "_step_goto_training_dataset",
        success_message="Z4/PZ1 przekazano do utworzenia wariantu datasetu.",
        error_message="Nie udało się otworzyć Z4/PZ1.",
    )


def _current_step4_without_training_decision_ready() -> bool:
    try:
        decision = dict(CAMPAIGN.get_step4_without_training_decision() or {})
    except Exception:
        decision = {}
    if not bool(decision.get("ready")):
        return False
    try:
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 0)
    except Exception:
        current_iteration = 0
    try:
        decision_iteration = int(decision.get("iteration", 0) or 0)
    except Exception:
        decision_iteration = 0
    current_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
    decision_target = str(decision.get("target", "") or "").strip().lower()
    return bool(
        decision_iteration == current_iteration
        and (not decision_target or not current_target or decision_target == current_target)
    )


def _current_training_stage_label() -> str:
    target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
    if target == "plate":
        return "E4T"
    if target == "char":
        return "E4Z"
    return "E4T/E4Z"


def _current_iteration_step4_training_record() -> dict:
    try:
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 0)
    except Exception:
        current_iteration = 0
    if current_iteration <= 0:
        return {}
    try:
        synced = dict(CAMPAIGN.sync_step4_training_record_from_history(iteration_num=current_iteration) or {})
        if synced:
            return synced
    except Exception:
        pass
    try:
        iteration_state = dict(CAMPAIGN.get_iteration_state(iteration_num=current_iteration) or {})
        record = dict(iteration_state.get("step4_training") or {})
    except Exception:
        record = {}
    if record:
        return record
    try:
        bundle = dict(CAMPAIGN.get_iteration_artifact_bundle(iteration_num=current_iteration) or {})
        record = dict(bundle.get("step4_training") or {})
    except Exception:
        record = {}
    return record


def _current_step4_training_finish_ready(host: Any) -> bool:
    try:
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 0)
    except Exception:
        current_iteration = 0
    current_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
    finish_state = {}
    try:
        app = getattr(host, "app", None)
        training_tab = app.tabs.get("training") if app is not None and getattr(app, "tabs", None) else None
        getter = getattr(training_tab, "get_campaign_step4_finish_state", None)
        if callable(getter):
            finish_state = dict(getter(iteration_target=current_target) or {})
    except Exception:
        finish_state = {}
    if not finish_state:
        try:
            finish_state = dict(CAMPAIGN.get_step4_finish_state() or {})
        except Exception:
            finish_state = {}
    if not bool(finish_state.get("ready")):
        return False
    run_id = str(finish_state.get("run_id", "") or "").strip()
    if not run_id:
        return False
    try:
        finish_iteration = int(finish_state.get("iteration", 0) or 0)
    except Exception:
        finish_iteration = 0
    finish_target = str(finish_state.get("target", "") or "").strip().lower()
    if finish_iteration != current_iteration:
        return False
    if finish_target and current_target and finish_target != current_target:
        return False
    training_record = _current_iteration_step4_training_record()
    if not training_record:
        return False
    record_run_id = str(training_record.get("run_id", "") or "").strip()
    if record_run_id != run_id:
        return False
    record_target = str(training_record.get("target", "") or "").strip().lower()
    if record_target and current_target and record_target != current_target:
        return False
    record_status = str(training_record.get("status", "") or "").strip().lower()
    if record_status != "completed":
        return False
    best_weights = str(training_record.get("best_weights", "") or "").strip()
    if not best_weights:
        return False
    try:
        return bool(Path(best_weights).exists())
    except Exception:
        return False


def _execute_prepare_step4_without_training(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    if not CAMPAIGN.get_active_project_name():
        return CampaignGraphActionResult(False, "prepare_step4_without_training", "Brak aktywnego projektu.")
    try:
        current_step = int(CAMPAIGN.get_current_step() or 0)
    except Exception:
        current_step = 0
    stage_label = _current_training_stage_label()
    if current_step != 4:
        return CampaignGraphActionResult(
            False,
            "prepare_step4_without_training",
            f"Zakończenie bez treningu dotyczy wyłącznie bramki T07 w {stage_label}.",
        )
    try:
        current_iteration = int(CAMPAIGN.get_current_iteration_num() or 0)
    except Exception:
        current_iteration = 0
    target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
    try:
        CAMPAIGN.set_step4_without_training_decision(
            True,
            target=target,
            iteration_num=current_iteration,
        )
    except Exception as exc:
        logger.error(f"Nie udało się zapisać decyzji T07 bez treningu: {exc}")
        return CampaignGraphActionResult(
            False,
            "prepare_step4_without_training",
            "Nie udało się zapisać decyzji zakończenia bez treningu.",
        )
    try:
        app = getattr(host, "app", None)
        if app is not None and hasattr(app, "themed_info"):
            app.themed_info(
                "Decyzja T07",
                (
                    f"Wybrano zakończenie {stage_label} bez treningu.\n\n"
                    "To jeszcze nie przenosi projektu do E1. Bramka T07 została przygotowana do zamknięcia; "
                    "formalny skok do kolejnej iteracji wykonasz dopiero polem „ZATWIERDŹ” na bramce T07."
                ),
                parent=getattr(host, "frame", None),
                tone="warning",
            )
    except Exception:
        pass
    _safe_refresh_wizard(host)
    return CampaignGraphActionResult(
        True,
        "prepare_step4_without_training",
        f"Wybrano zakończenie {stage_label} bez treningu. Zatwierdź bramkę T07, aby przejść dalej.",
    )


def _execute_approve_step4(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    if _current_step4_without_training_decision_ready():
        return _execute_host_method(
            host,
            "approve_step4_without_training",
            "_finish_step4_without_training",
            success_message="T07 przekazano do zamknięcia bez treningu.",
            error_message="Nie udało się zamknąć T07 bez treningu.",
        )
    if not _current_step4_training_finish_ready(host):
        _safe_update_status(
            host,
            "T07 wymaga decyzji w bieżącej iteracji: uruchom trening albo wybierz świadome pominięcie treningu.",
            "warning",
        )
        _safe_refresh_wizard(host)
        return CampaignGraphActionResult(
            False,
            "approve_step4",
            "T07 nie ma bieżącego wyniku treningu ani decyzji pominięcia treningu.",
        )
    return _execute_host_method(
        host,
        "approve_step4",
        "_finish_step4_iteration",
        success_message=f"{_current_training_stage_label()} przekazano do zatwierdzenia.",
        error_message=f"Nie udało się zatwierdzić {_current_training_stage_label()}.",
    )


def _execute_approve_step4_without_training(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method(
        host,
        "approve_step4_without_training",
        "_finish_step4_without_training",
        success_message=f"{_current_training_stage_label()} przekazano do zamknięcia bez treningu.",
        error_message=f"Nie udało się zamknąć {_current_training_stage_label()} bez treningu.",
    )


def _execute_start_next_iteration(host: Any, _payload: Mapping[str, Any]) -> CampaignGraphActionResult:
    return _execute_host_method(
        host,
        "start_next_iteration",
        "_advance_iteration",
        success_message="Przejście do E1 kolejnej iteracji zostało przekazane.",
        error_message="Nie udało się przejść do E1 kolejnej iteracji.",
    )


def _record_graph_action_history(
    action: str,
    payload: Mapping[str, Any],
    result: CampaignGraphActionResult,
) -> None:
    if not CAMPAIGN.get_active_project_name():
        return

    context = dict(payload.get("context") or payload.get("preferred_source_context") or {})
    transition_id = str(
        payload.get("graph_edge_key")
        or payload.get("transition_id")
        or context.get("graph_edge_key")
        or ""
    ).strip()
    gate_id = str(
        payload.get("graph_gate_id")
        or payload.get("gate_id")
        or context.get("graph_gate_id")
        or transition_id
        or ""
    ).strip()
    transition_title = str(
        payload.get("graph_transition_title")
        or context.get("graph_transition_title")
        or payload.get("title")
        or ""
    ).strip()
    title = transition_title or str(result.message or action or "Akcja grafu").strip()
    artifacts: dict[str, Any] = {}
    resources: dict[str, Any] = {}
    if str(action or "").strip() == "approve_step2" and bool(result.ok):
        try:
            approved_stats = dict(CAMPAIGN.get_plate_approved_set_stats(None) or {})
        except Exception:
            approved_stats = {}
        try:
            approved_images = int(approved_stats.get("images", 0) or 0)
        except Exception:
            approved_images = 0
        try:
            approved_plates = int(approved_stats.get("plates", 0) or 0)
        except Exception:
            approved_plates = 0
        artifacts.update(
            {
                "approved_images": int(approved_images),
                "approved_plates": int(approved_plates),
            }
        )
        resources["AT"] = "Zatwierdzone anotacje tablic"

    try:
        CAMPAIGN.append_project_history_event(
            "graph_action",
            title,
            transition_id=transition_id,
            gate_id=gate_id,
            action=str(action or "").strip(),
            status="ok" if bool(result.ok) else "error",
            resources=resources,
            artifacts=artifacts,
            details={
                "message": str(result.message or "").strip(),
                "source": str(payload.get("source") or context.get("source") or "campaign_graph").strip(),
                "target": str(payload.get("graph_transition_target") or context.get("graph_transition_target") or "").strip(),
                "path": str(payload.get("graph_path_key") or context.get("graph_path_key") or "").strip(),
            },
        )
    except Exception:
        pass


def execute_campaign_graph_action(
    host: Any,
    action: str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> CampaignGraphActionResult:
    normalized = str(action or "").strip()
    action_payload = dict(payload or {})
    handlers = {
        "set_iteration_path": _execute_set_iteration_path,
        "approve_step1": _execute_approve_step1,
        "approve_step1_ready_plates": _execute_approve_step1_ready_plates,
        "validate_and_adopt_annotations": _execute_validate_and_adopt_annotations,
        "open_z2_campaign_context": _execute_open_z2_campaign_context,
        "open_z2_step2_review": _execute_open_z2_step2_review,
        "open_z2_step3_repair": _execute_open_z2_step3_repair,
        "return_to_z2_review": _execute_return_to_z2_review,
        "approve_step2": _execute_approve_step2,
        "continue_z3": _execute_continue_z3,
        "open_z3": _execute_open_z3,
        "open_z3_detect": _execute_open_z3_detect,
        "approve_step3": _execute_approve_step3,
        "open_z4": _execute_open_z4,
        "open_z4_dataset": _execute_open_z4_dataset,
        "prepare_step4_without_training": _execute_prepare_step4_without_training,
        "approve_step4": _execute_approve_step4,
        "approve_step4_without_training": _execute_approve_step4_without_training,
        "start_next_iteration": _execute_start_next_iteration,
    }
    handler = handlers.get(normalized)
    if handler is None:
        message = f"Akcja grafu nie jest jeszcze podłączona: {normalized or '-'}."
        logger.debug(message)
        result = CampaignGraphActionResult(False, normalized, message)
        _record_graph_action_history(normalized, action_payload, result)
        return result
    result = handler(host, action_payload)
    _record_graph_action_history(normalized, action_payload, result)
    return result


SUPPORTED_CAMPAIGN_GRAPH_ACTIONS = frozenset({
    "set_iteration_path",
    "approve_step1",
    "approve_step1_ready_plates",
    "validate_and_adopt_annotations",
    "open_z2_campaign_context",
    "open_z2_step2_review",
    "open_z2_step3_repair",
    "return_to_z2_review",
    "approve_step2",
    "continue_z3",
    "open_z3",
    "open_z3_detect",
    "approve_step3",
    "open_z4",
    "open_z4_dataset",
    "prepare_step4_without_training",
    "approve_step4",
    "approve_step4_without_training",
    "start_next_iteration",
})
