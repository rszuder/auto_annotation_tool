from __future__ import annotations

import time
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING, Any

from ..config import logger
from .z2_flow_models import (
    Z2CampaignRuntimeState,
    Z2CopyPayload,
    Z2CtaState,
    Z2LayoutState,
    Z2LeftPanelCopyContext,
)

if TYPE_CHECKING:
    from .tab_annotation import AnnotationTab


def apply_campaign_step2_workflow_preset(
    host: "AnnotationTab",
    *,
    iteration_target: str | None = None,
    manual_template: bool | None = None,
) -> None:
    if host._is_free_mode_session_context():
        return

    target = str(iteration_target or "").strip().lower()
    if target not in {"plate", "char"}:
        try:
            from ..campaign_manager import CAMPAIGN
            target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        except Exception:
            target = ""
    if target not in {"plate", "char"}:
        target = "plate"

    input_ready = bool(str(host.input_dir_var.get() or "").strip())
    campaign_default_manual = False
    try:
        from ..campaign_manager import CAMPAIGN

        campaign_default_manual = bool(
            CAMPAIGN.get_active_project_name()
            and int(CAMPAIGN.get_current_step() or 0) == 2
            and target in {"plate", "char"}
        )
    except Exception:
        campaign_default_manual = False

    if manual_template is not None:
        use_manual_route = bool(manual_template)
    else:
        use_manual_route = bool(campaign_default_manual or (target == "plate"))

    host._manual_review_active = False
    host._manual_review_from_auto = False
    host._manual_review_export_ready = False
    host._dataset_export_completed = False
    host._last_completed_workflow_route = ""
    host._auto_route_settings_pending = False
    host._reset_campaign_step2_runtime_state()

    if use_manual_route:
        host._set_workflow_route_state("manual", campaign_context=True)
        host._set_manual_entry_mode_state("new", campaign_context=True)
        host.manual_xml_template_var.set(True)
        try:
            host.manual_vehicle_assist_var.set(False)
        except Exception:
            pass
        host._set_workflow_step_state("manual_start" if input_ready else "manual_input", campaign_context=True)
    else:
        host._set_workflow_route_state("auto", campaign_context=True)
        host.manual_xml_template_var.set(False)
        try:
            auto_choice = "use" if str(host.mode_var.get() or "").strip() == "C: Pojazdy + tablice" else "skip"
            host._set_auto_vehicle_choice_state(auto_choice, campaign_context=True)
        except Exception:
            pass
        next_step = "auto_input" if not input_ready else "auto_start"
        host._set_workflow_step_state(next_step, campaign_context=True)
    try:
        host._set_screen_state("workflow", campaign_context=True)
    except Exception:
        pass

    host._refresh_left_panel_route_copy()
    host._refresh_detection_configuration_ui()
    host._refresh_step2_action_states()
    host._refresh_free_mode_workflow_ui()


def open_existing_run_for_campaign_review(
    host: "AnnotationTab",
    run_dir: Path | None = None,
    *,
    iteration_target: str | None = None,
    manual_template: bool = False,
    defer_ui_restore: bool = False,
) -> bool:
    target_run_dir = host._resolve_safe_annotation_run_dir(run_dir, require_xml=True)
    if target_run_dir is None:
        return False

    normalized_target = str(iteration_target or "").strip().lower()
    repair_mode = bool(
        (normalized_target == "char" and host._is_campaign_char_repair_return_mode())
        or (normalized_target == "plate" and host._is_campaign_plate_step4_repair_return_mode())
    )
    if defer_ui_restore:
        host.current_annotation_run_dir = target_run_dir
        host.current_annotation_xml_path = target_run_dir / "annotations.xml"
        host.last_staging_run_dir = target_run_dir
        try:
            host.plate_dataset_run_var.set(str(target_run_dir))
        except Exception:
            pass
        host._campaign_deferred_run_restore_in_progress = True
        apply_campaign_step2_workflow_preset(
            host,
            iteration_target=iteration_target,
            manual_template=manual_template,
        )
    else:
        if not host._restore_preview_from_annotation_run(
            target_run_dir,
            defer_ui_restore=False,
        ):
            return False

        apply_campaign_step2_workflow_preset(
            host,
            iteration_target=iteration_target,
            manual_template=manual_template,
        )
    if manual_template:
        host._set_workflow_route_state("manual", campaign_context=True)
        host._set_manual_entry_mode_state("continue", campaign_context=True)
        host._manual_review_active = True
        host._manual_review_from_auto = False
        host._manual_review_origin_route = "manual"
        host._manual_review_export_ready = False
        host._dataset_export_completed = False
        host._last_completed_workflow_route = ""
        host._auto_route_settings_pending = False
        host._set_workflow_step_state("manual_history", campaign_context=True)
    else:
        host._set_workflow_route_state("auto", campaign_context=True)
        host.manual_xml_template_var.set(False)
        host._set_workflow_step_state("auto_start", campaign_context=True)
        host._manual_review_active = False
        host._manual_review_from_auto = False
        host._manual_review_origin_route = ""
        host._manual_review_export_ready = False
        host._dataset_export_completed = False
        host._last_completed_workflow_route = "" if repair_mode else "auto"
        host._auto_route_settings_pending = False
    host._refresh_left_panel_route_copy()
    host._refresh_detection_configuration_ui()
    host._refresh_run_output_info()
    if not defer_ui_restore:
        host._refresh_plate_dataset_export_sources()
        host._refresh_preview_list_summary()
        host._refresh_step2_action_states()
    else:
        host._refresh_step2_action_states()
    host._refresh_free_mode_workflow_ui()
    return True


def open_campaign_step2_entry(
    host: "AnnotationTab",
    *,
    iteration_target: str | None = None,
    entry_strategy: str | None = None,
    restore_preview: bool = True,
    open_existing_run: bool = True,
    defer_preview_load: bool = False,
) -> dict[str, Any]:
    open_started = time.perf_counter()
    host._begin_campaign_step2_transition()
    try:
        from ..campaign_manager import CAMPAIGN

        active_project = CAMPAIGN.get_active_project_name()
        if not active_project or int(CAMPAIGN.get_current_step() or 0) < 2:
            return {"ok": False, "reason": "campaign_inactive"}

        try:
            host.app.campaign_free_mode = False
            host.app.set_campaign_mode(True)
        except Exception:
            pass

        target = str(iteration_target or CAMPAIGN.get_iteration_target() or "").strip().lower()
        if target not in {"plate", "char"}:
            return {"ok": False, "reason": "missing_iteration_target"}
        campaign_mode_text = "B: Tylko tablice"

        raw_dir = CAMPAIGN.get_dir("raw")
        auto_out = CAMPAIGN.get_staging_dir("auto_ann")
        if auto_out is not None:
            Path(auto_out).mkdir(parents=True, exist_ok=True)

        if raw_dir is None or auto_out is None:
            return {"ok": False, "reason": "missing_campaign_dirs"}

        vehicle_model_path = str(CAMPAIGN.get_global_model("vehicle") or "").strip()
        plate_model_path = str(CAMPAIGN.get_global_model("plate") or "").strip()
        char_source_state = {}
        char_has_existing_source = False
        plate_source_state = {}
        plate_model_ready = bool(plate_model_path and Path(plate_model_path).exists())
        try:
            plate_source_state = dict(host.get_campaign_step2_source_state(iteration_target="plate") or {})
        except Exception:
            plate_source_state = {}
        plate_model_ready = bool(plate_source_state.get("plate_model_ready", plate_model_ready))
        if plate_model_ready and (not plate_model_path or not Path(plate_model_path).exists()):
            try:
                plate_model_path = str(
                    (plate_source_state.get("bootstrap") or {}).get("plate_model_path") or plate_model_path or ""
                ).strip()
            except Exception:
                plate_model_path = str(plate_model_path or "").strip()
        if target == "char":
            try:
                char_source_state = dict(host.get_campaign_step2_source_state(iteration_target="char") or {})
            except Exception:
                char_source_state = {}
            char_has_existing_source = bool(char_source_state.get("has_source"))
        if target == "char" and not plate_model_ready and not char_has_existing_source:
            messagebox.showwarning(
                "Brak modelu tablic",
                "Tor znakow wymaga gotowego modelu tablic Pose przypisanego do projektu.\n\n"
                "Najpierw wytrenuj model tablic w torze A, a potem wroc do toru B."
            )
            return {"ok": False, "reason": "missing_plate_model"}

        iter_num = CAMPAIGN.get_current_iteration_num()
        folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
        input_dir = folder if folder.exists() else Path(raw_dir)
        base_input_dir = input_dir

        try:
            host._repair_campaign_step2_generated_state_for_input(base_input_dir)
        except Exception:
            pass

        strategy = str(entry_strategy or "").strip().lower()
        snapshot_state = host._load_campaign_project_snapshot()
        char_repair_return = bool(
            target == "char"
            and host._is_campaign_char_repair_return_mode()
        )
        bootstrap = {}
        if char_repair_return and open_existing_run and strategy != "raw":
            snapshot_restore_run = None
            snapshot_input_dir = None
            plate_source_bootstrap = {}
            try:
                plate_source_bootstrap = dict(host.get_campaign_step2_bootstrap(iteration_target="plate") or {})
            except Exception:
                plate_source_bootstrap = {}
            registry_active_entry = host._get_campaign_step2_active_run_entry(
                images_dir=base_input_dir,
                iteration_num=iter_num,
            )
            try:
                snapshot_restore_run = host._resolve_safe_annotation_run_dir(
                    plate_source_bootstrap.get("restore_run_dir"),
                    require_xml=True,
                )
            except Exception:
                snapshot_restore_run = None
            try:
                snapshot_input_dir = host._resolve_existing_dir(
                    plate_source_bootstrap.get("input_dir")
                )
            except Exception:
                snapshot_input_dir = None
            if snapshot_restore_run is None:
                snapshot_restore_run = host._resolve_safe_annotation_run_dir(
                    registry_active_entry.get("run_dir"),
                    require_xml=True,
                )
            if snapshot_input_dir is None:
                snapshot_input_dir = host._resolve_existing_dir(
                    registry_active_entry.get("images_dir")
                )
            if snapshot_restore_run is None:
                try:
                    snapshot_restore_run = host._resolve_safe_annotation_run_dir(
                        CAMPAIGN.get_step2_staging_run(),
                        require_xml=True,
                    )
                except Exception:
                    snapshot_restore_run = None
            if snapshot_restore_run is None:
                try:
                    stored_manual_source = CAMPAIGN.get_last_plate_manual_source()
                except Exception:
                    stored_manual_source = {}
                for raw_candidate in (
                    str((stored_manual_source or {}).get("source_run_path") or "").strip(),
                    str((stored_manual_source or {}).get("source_xml_path") or "").strip(),
                ):
                    if not raw_candidate:
                        continue
                    try:
                        run_candidate = Path(raw_candidate)
                        if run_candidate.suffix.lower() == ".xml":
                            run_candidate = run_candidate.parent
                    except Exception:
                        continue
                    snapshot_restore_run = host._resolve_safe_annotation_run_dir(
                        run_candidate,
                        require_xml=True,
                    )
                    if snapshot_restore_run is not None:
                        break
            if snapshot_restore_run is None:
                try:
                    latest_staging_run = host._find_latest_annotation_run_dir(Path(auto_out))
                except Exception:
                    latest_staging_run = None
                snapshot_restore_run = host._resolve_safe_annotation_run_dir(
                    latest_staging_run,
                    require_xml=True,
                )
            if snapshot_input_dir is None:
                try:
                    run_manifest = host._load_annotation_run_manifest(snapshot_restore_run)
                except Exception:
                    run_manifest = {}
                snapshot_input_dir = host._resolve_existing_dir(
                    run_manifest.get("input_dir")
                    or run_manifest.get("source_input_dir")
                    or run_manifest.get("imported_source_input_dir")
                )

            repair_context_matches_current_iteration = False
            if snapshot_input_dir is not None:
                try:
                    repair_context_matches_current_iteration = host._paths_equivalent(
                        snapshot_input_dir,
                        base_input_dir,
                    )
                except Exception:
                    repair_context_matches_current_iteration = False
            if not repair_context_matches_current_iteration and snapshot_restore_run is not None:
                try:
                    repair_context_matches_current_iteration = host._annotation_run_matches_expected_input_dir(
                        snapshot_restore_run,
                        base_input_dir,
                    )
                except Exception:
                    repair_context_matches_current_iteration = False

            if repair_context_matches_current_iteration:
                if snapshot_input_dir is None:
                    snapshot_input_dir = base_input_dir
            else:
                if snapshot_restore_run is not None or snapshot_input_dir is not None:
                    try:
                        logger.info(
                            "Pomijam stary kontekst Z2 przy powrocie E3 -> Z2: "
                            f"snapshot_input={snapshot_input_dir} restore_run={snapshot_restore_run} "
                            f"current_iteration_input={base_input_dir}"
                        )
                    except Exception:
                        pass
                snapshot_restore_run = None
                snapshot_input_dir = base_input_dir

            bootstrap = {
                "input_dir": (snapshot_input_dir or base_input_dir),
                "input_source": (
                    "campaign_step3_repair_snapshot"
                    if snapshot_restore_run is not None
                    else "raw"
                ),
                "manual_template": False,
                "plate_model_path": plate_model_path if plate_model_path and Path(plate_model_path).exists() else "",
                "restore_run_dir": snapshot_restore_run,
            }
        else:
            try:
                bootstrap = host._get_campaign_auto_annotation_bootstrap(target)
            except Exception:
                bootstrap = {}

        if target == "plate" and strategy == "raw":
            bootstrap = dict(bootstrap) if isinstance(bootstrap, dict) else {}
            bootstrap["input_dir"] = base_input_dir
            bootstrap["restore_run_dir"] = None
            bootstrap["input_source"] = "raw_forced"
            bootstrap["manual_template"] = bool(not (plate_model_path and Path(plate_model_path).exists()))
            bootstrap["plate_model_path"] = plate_model_path if plate_model_path and Path(plate_model_path).exists() else ""

        input_dir = Path(bootstrap.get("input_dir") or input_dir)
        manual_template = bool(bootstrap.get("manual_template", target == "plate"))
        plate_bootstrap_model = str(bootstrap.get("plate_model_path") or "").strip()
        restore_run_dir = bootstrap.get("restore_run_dir")
        input_source = str(bootstrap.get("input_source") or "raw").strip()
        if target == "plate" and restore_run_dir is not None:
            manual_template = False
            bootstrap["manual_template"] = False
        if not host._should_restore_existing_campaign_step2_run(target):
            restore_run_dir = None
            bootstrap["restore_run_dir"] = None
        elif not host._should_restore_campaign_generated_step2_run_preview(
            restore_run_dir,
            session_state=snapshot_state,
            iteration_target=target,
        ):
            restore_run_dir = None
            bootstrap["restore_run_dir"] = None
        char_repair_without_run = bool(
            target == "char"
            and host._is_campaign_char_repair_return_mode()
            and restore_run_dir is None
        )
        effective_manual_template = bool(manual_template)
        restored_snapshot = False
        open_detected_run = bool(
            open_existing_run
            and not restored_snapshot
            and restore_run_dir is not None
            and strategy != "raw"
            and (
                target == "plate"
                or (target == "char" and not restore_preview)
            )
        )
        defer_existing_run_ui_restore = bool(
            target == "char"
            and open_detected_run
            and not restore_preview
        )
        skip_project_state_restore = bool(open_detected_run or defer_existing_run_ui_restore)
        restore_preview_during_context = bool(restore_preview and not open_detected_run)
        opened_existing_run = False
        defer_initial_preview_load = bool(
            defer_preview_load
            and not open_detected_run
            and not char_repair_without_run
        )

        restored_snapshot = host.apply_campaign_context(
            input_dir,
            Path(auto_out),
            manual_template=effective_manual_template,
            mode_text=campaign_mode_text,
            restore_project_state=bool(not skip_project_state_restore),
            restore_preview=restore_preview_during_context,
            defer_preview_load=defer_initial_preview_load,
        )

        if skip_project_state_restore and isinstance(snapshot_state, dict):
            try:
                host._preview_session_restore_index = int(snapshot_state.get("last_preview_index", -1))
            except (TypeError, ValueError):
                host._preview_session_restore_index = -1
            try:
                host._preview_session_restore_filename = str(snapshot_state.get("last_preview_filename") or "").strip()
            except Exception:
                host._preview_session_restore_filename = ""

        if restored_snapshot and open_detected_run:
            open_detected_run = False
            defer_existing_run_ui_restore = False

        if not restored_snapshot and not open_detected_run:
            if vehicle_model_path and Path(vehicle_model_path).exists():
                host.vehicle_model_var.set("Custom")
                host.vehicle_custom_var.set(vehicle_model_path)
            else:
                try:
                    vehicle_values = list(host.vehicle_combo["values"]) if hasattr(host, "vehicle_combo") else []
                except Exception:
                    vehicle_values = []
                detect_values = [value for value in vehicle_values if value != "Custom"]
                default_vehicle = "yolo11s" if "yolo11s" in detect_values else (detect_values[0] if detect_values else "")
                if default_vehicle:
                    host.vehicle_model_var.set(default_vehicle)
                host.vehicle_custom_var.set("")

            if (
                target == "char" and plate_model_path and Path(plate_model_path).exists()
            ) or (
                target == "plate" and plate_bootstrap_model and Path(plate_bootstrap_model).exists()
            ):
                host.plate_custom_var.set(plate_bootstrap_model if target == "plate" else plate_model_path)
            else:
                host.plate_custom_var.set("")

            host.mode_var.set(campaign_mode_text)
            host._on_mode_change()

        if open_detected_run:
            try:
                if host._is_free_mode_session_context():
                    opened_existing_run = host._open_existing_run_for_manual_review(
                        run_dir=restore_run_dir,
                        allow_fallback=False,
                        from_auto=False,
                        show_dialog=False,
                    )
                else:
                    opened_existing_run = open_existing_run_for_campaign_review(
                        host,
                        run_dir=restore_run_dir,
                        iteration_target=target,
                        manual_template=manual_template,
                        defer_ui_restore=defer_existing_run_ui_restore,
                    )
            except Exception:
                opened_existing_run = False

        if defer_existing_run_ui_restore and opened_existing_run:
            host._campaign_step2_transition_skip_heavy_finalize = True

        if char_repair_without_run and not opened_existing_run:
            try:
                if not host.current_annotations:
                    host._prime_campaign_source_preview(Path(input_dir))
            except Exception:
                pass
            try:
                if host._ensure_campaign_preview_edit_run():
                    seeded_run_dir = host._get_active_annotation_run_dir(require_xml=True)
                else:
                    seeded_run_dir = None
            except Exception:
                seeded_run_dir = None
            if seeded_run_dir is not None:
                try:
                    opened_existing_run = open_existing_run_for_campaign_review(
                        host,
                        run_dir=seeded_run_dir,
                        iteration_target=target,
                        manual_template=False,
                    )
                except Exception:
                    opened_existing_run = False

        current_route = ""
        try:
            current_route = host._get_workflow_route()
        except Exception:
            current_route = ""

        force_campaign_preset = bool(
            not opened_existing_run
            and target == "plate"
            and effective_manual_template
            and current_route != "manual"
        )

        if not opened_existing_run and (not restored_snapshot or force_campaign_preset):
            apply_campaign_step2_workflow_preset(
                host,
                iteration_target=target,
                manual_template=effective_manual_template,
            )
        elif not opened_existing_run and not current_route:
            apply_campaign_step2_workflow_preset(
                host,
                iteration_target=target,
                manual_template=effective_manual_template,
            )

        try:
            host._refresh_free_mode_workflow_ui()
        except Exception:
            pass

        try:
            host._reset_main_pane_left_width_for_z2()
        except Exception:
            pass

        try:
            host._scroll_left_panel_to_widget(
                getattr(host, "workflow_start_section", None)
                or getattr(host, "source_section", None)
                or getattr(host, "actions_section", None)
            )
        except Exception:
            pass

        try:
            host._refresh_step2_action_states()
        except Exception:
            pass

        host._campaign_context_project_name = str(active_project or "").strip()

        deferred_preview_load = bool(
            defer_initial_preview_load
            and not restored_snapshot
            and not opened_existing_run
            and not bool(getattr(host, "current_annotations", None))
        )

        return {
            "ok": True,
            "iteration_target": target,
            "input_dir": str(input_dir),
            "auto_out": str(auto_out),
            "manual_template": bool(effective_manual_template),
            "input_source": input_source,
            "restored_snapshot": bool(restored_snapshot),
            "opened_existing_run": bool(opened_existing_run),
            "restore_run_dir": str(restore_run_dir or ""),
            "plate_model_path": plate_model_path,
            "deferred_preview_load": deferred_preview_load,
            "deferred_preview_input_dir": (str(input_dir) if deferred_preview_load else ""),
            "deferred_existing_run_restore": bool(
                defer_existing_run_ui_restore and opened_existing_run
            ),
        }
    except Exception as e:
        logger.error(f"Nie udalo sie otworzyc punktu startowego Z2: {e}")
        return {"ok": False, "reason": "exception", "error": str(e)}
    finally:
        try:
            host._end_campaign_step2_transition()
        except Exception:
            pass
        elapsed_ms = max(0.0, (time.perf_counter() - open_started) * 1000.0)
        if elapsed_ms >= 20.0:
            logger.debug(
                "[AnnotationTab][PERF] open_campaign_step2_entry: "
                f"{elapsed_ms:.1f} ms | restore_preview={int(bool(restore_preview))} "
                f"open_existing_run={int(bool(open_existing_run))} "
                f"defer_preview_load={int(bool(defer_preview_load))}"
            )


def build_z2_layout_state_campaign(
    host: "AnnotationTab",
    *,
    route: str,
    campaign_stage: int,
    campaign_iteration_target: str,
    available_primary_action_ids: list[str],
    manual_review_active: bool,
    auto_completed: bool,
    has_existing_run: bool,
) -> dict[str, Any]:
    campaign_stage2 = int(campaign_stage or 0) == 2
    show_export_followup = bool(host._manual_review_export_ready)
    show_auto_followup = bool(
        auto_completed
        and not manual_review_active
        and not show_export_followup
        and False
    )
    show_manual_review_followup = bool(manual_review_active and not show_export_followup)
    show_route_choice = bool(
        campaign_stage2
        and campaign_iteration_target in {"plate", "char"}
        and not route
        and len(available_primary_action_ids) > 1
        and not show_export_followup
    )
    show_stage_export_cta = False
    compact_export_followup = False
    show_workflow_steps = bool(
        (
            route
            and not show_manual_review_followup
            and not show_export_followup
            and (not auto_completed or (campaign_stage2 and route == "auto"))
        )
        or (
            campaign_stage2
            and not has_existing_run
            and not show_manual_review_followup
            and not show_auto_followup
            and not show_export_followup
        )
    )
    compact_single_route_layout = bool(
        campaign_stage2
        and len(available_primary_action_ids) == 1
        and show_workflow_steps
        and not show_manual_review_followup
        and not show_export_followup
    )
    compact_left_column_layout = bool(
        compact_single_route_layout
        or show_manual_review_followup
        or show_auto_followup
        or show_export_followup
    )
    show_campaign_context_header = bool(
        True
        and not show_workflow_steps
        and bool(route or manual_review_active or has_existing_run or campaign_stage >= 3)
    )
    return Z2LayoutState(
        show_export_followup=show_export_followup,
        show_auto_followup=show_auto_followup,
        show_manual_review_followup=show_manual_review_followup,
        show_route_choice=show_route_choice,
        show_stage_export_cta=show_stage_export_cta,
        compact_export_followup=compact_export_followup,
        show_workflow_steps=show_workflow_steps,
        compact_single_route_layout=compact_single_route_layout,
        compact_left_column_layout=compact_left_column_layout,
        show_campaign_context_header=show_campaign_context_header,
        show_nav_panel=False,
        show_right_panel=bool(
            (
                int(campaign_stage or 0) == 2
                or int(campaign_stage or 0) == 3
                or host._is_campaign_char_repair_return_mode()
                or host._is_campaign_plate_step4_repair_return_mode()
            )
            and not show_export_followup
        ),
    )


def prepare_campaign_workflow_runtime(
    host: "AnnotationTab",
    *,
    route: str,
    manual_review_active: bool,
    input_dir_ready: bool,
) -> Z2CampaignRuntimeState:
    campaign_stage = 0
    campaign_iteration_target = ""
    campaign_iteration_num = 1
    campaign_char_repair_mode = False
    campaign_plate_step4_repair_mode = False
    try:
        from ..campaign_manager import CAMPAIGN
        campaign_stage = int(CAMPAIGN.get_current_step() or 0)
        campaign_iteration_target = str(CAMPAIGN.get_iteration_target() or "").strip().lower()
        campaign_iteration_num = int(CAMPAIGN.get_current_iteration_num() or 1)
        campaign_char_repair_mode = bool(
            campaign_stage == 3
            and campaign_iteration_target == "char"
        )
        campaign_plate_step4_repair_mode = bool(
            campaign_stage == 4
            and campaign_iteration_target == "plate"
            and host._is_campaign_plate_step4_repair_return_mode()
        )
    except Exception:
        campaign_stage = 0
        campaign_iteration_target = ""
        campaign_iteration_num = 1
        campaign_char_repair_mode = False
        campaign_plate_step4_repair_mode = False
    try:
        secondary_ctx = host._build_z2_action_context()
        available_primary_action_ids = [
            action_id
            for action_id, action in (host._get_z2_primary_actions() or {}).items()
            if action is not None and action.is_available(secondary_ctx)
        ]
    except Exception:
        available_primary_action_ids = []

    current_route = str(route or "").strip().lower()
    if (
        int(campaign_stage or 0) == 2
        and campaign_iteration_target in {"plate", "char"}
        and "auto" in available_primary_action_ids
        and (
            (campaign_iteration_target == "plate" and int(campaign_iteration_num or 1) > 1)
            or campaign_iteration_target == "char"
        )
    ):
        available_primary_action_ids = ["auto"]
        if not manual_review_active and current_route != "auto":
            host._set_workflow_route_state("auto", campaign_context=True)
            host.manual_xml_template_var.set(False)
            host._set_workflow_step_state("auto_start" if input_dir_ready else "auto_input", campaign_context=True)
            host._set_auto_vehicle_choice_state(host._get_auto_vehicle_choice(), campaign_context=True)
            current_route = "auto"

    single_available_primary_route = (
        str(available_primary_action_ids[0]).strip()
        if len(available_primary_action_ids) == 1
        else ""
    )
    if (
        int(campaign_stage or 0) == 2
        and not current_route
        and not manual_review_active
        and single_available_primary_route in {"auto", "manual"}
    ):
        if single_available_primary_route == "manual":
            host._set_workflow_route_state("manual", campaign_context=True)
            host._set_manual_entry_mode_state("new", campaign_context=True)
            host.manual_xml_template_var.set(True)
            try:
                host.manual_vehicle_assist_var.set(False)
            except Exception:
                pass
            host._set_workflow_step_state("manual_start" if input_dir_ready else "manual_input", campaign_context=True)
        else:
            host._set_workflow_route_state("auto", campaign_context=True)
            host.manual_xml_template_var.set(False)
            host._set_workflow_step_state("auto_start" if input_dir_ready else "auto_input", campaign_context=True)
            host._set_auto_vehicle_choice_state(host._get_auto_vehicle_choice(), campaign_context=True)
        current_route = single_available_primary_route

    return Z2CampaignRuntimeState(
        route=current_route,
        campaign_stage=campaign_stage,
        campaign_iteration_target=campaign_iteration_target,
        campaign_iteration_num=campaign_iteration_num,
        campaign_char_repair_mode=campaign_char_repair_mode,
        campaign_plate_step4_repair_mode=campaign_plate_step4_repair_mode,
        available_primary_action_ids=available_primary_action_ids,
    )


def build_z2_cta_state_campaign(
    host: "AnnotationTab",
    *,
    route: str,
    current_step: str,
    show_workflow_steps: bool,
    show_export_followup: bool,
    auto_completed: bool,
    manual_run_already_created: bool,
    input_dir_ready: bool,
    auto_setup_pending: bool,
    auto_vehicle_choice: str,
    manual_setup: bool,
    campaign_reused_manual_count: int,
) -> Z2CtaState:
    show_start_controls = bool(
        show_workflow_steps
        and (
            current_step in {"auto_start", "manual_start"}
            or current_step in {"auto_input", "manual_input"}
        )
    )
    if route == "auto" and auto_completed and not show_export_followup:
        show_start_controls = True
    if route == "manual" and manual_run_already_created and not host.is_processing:
        show_start_controls = False

    start_enabled = not host.is_processing and bool(route)
    start_command = host._start_annotation
    start_text = "Wybierz tor"
    if route == "auto":
        if not input_dir_ready:
            start_enabled = not host.is_processing
            start_text = "Wybierz obrazy do autoanotacji" if auto_setup_pending else "Wybierz obrazy"
            start_command = host._select_input_dir
        elif auto_setup_pending:
            start_text = "Start autoanotacji"
        elif auto_vehicle_choice == "skip":
            start_text = "Start autoanotacji tablic"
        else:
            start_text = "Start autoanotacji tablic i pojazdów"
    elif manual_setup:
        if manual_run_already_created:
            start_enabled = False
            start_text = "Run istnieje"
        elif not input_dir_ready:
            start_enabled = not host.is_processing
            start_text = "Wybierz obrazy"
            start_command = host._select_input_dir
        else:
            if campaign_reused_manual_count > 0:
                start_text = (
                    "Przygotuj XML + boxy"
                    if host._manual_vehicle_assist_enabled()
                    else "Przygotuj XML paczki"
                )
            else:
                start_text = (
                    "Utwórz XML + boxy"
                    if host._manual_vehicle_assist_enabled()
                    else "Utwórz XML"
                )

    return Z2CtaState(
        show_start_controls=show_start_controls,
        show_nav_controls=False,
        start_enabled=start_enabled,
        start_command=start_command,
        start_text=start_text,
        back_enabled=False,
        next_enabled=False,
        next_text="Dalej",
        suppress_duplicate_start_cta=bool(
            not host.is_processing and start_text in {"Wybierz tor", "Run istnieje"}
        ),
    )


def _apply_campaign_char_repair_copy_payload(
    payload: Z2CopyPayload,
    *,
    manual_review_active: bool = False,
) -> Z2CopyPayload:
    payload["run_title"] = "Przygotowanie większej liczby tablic"
    payload["badge_text"] = "Aktywny tor: świadomy powrót z E3 do Z2"
    payload["badge_tone"] = "success"
    payload["run_intro_text"] = (
        "Wróciłeś do Z2, żeby świadomie powiększyć projektowy zbiór tablic. "
        "Więcej poprawnych ramek daje lepszy materiał do treningu znaków. "
        "Zatwierdzone anotacje tablic [OK] wchodzą do wspólnej puli przyszłych iteracji "
        "w torze tablic bądź znaków, zgodnie z wyborem użytkownika. "
        "Pamiętaj o zatwierdzeniu uznanych za poprawnie anotowane obrazy na liście wyników: "
        "prawy przycisk myszy PPM na pozycji lub zaznaczonej grupie."
    )
    payload["route_text"] = (
        "Uzupełnij ramki na podglądzie. Poprawne zdjęcia zatwierdzaj z menu listy "
        "otwieranym prawym przyciskiem myszy: wybierz „Oznacz zaznaczone jako OK”."
    )
    payload["action_text"] = ""
    payload["workflow_start_title"] = ""
    payload["workflow_start_intro"] = ""
    payload["auto_plate_model_hint_text"] = (
        "W tym powrocie możesz użyć aktywnego modelu projektu albo podmienić model tylko dla tego runu Z2. "
        "Jeśli wolisz, możesz też pominąć autoanotację i poprawiać tablice ręcznie."
    )
    payload["auto_plate_model_hint_tone"] = "muted"

    if manual_review_active:
        payload["manual_hint"] = (
            "Ten powrót otwiera pełne Z2 dla tej samej paczki: możesz użyć autoanotacji aktywnym modelem projektu, "
            "podmienić model tylko dla tego runu albo poprawiać tablice ręcznie."
        )
        payload["manual_hint_tone"] = "muted"
        payload["workflow_input_title"] = "Aktywny run źródłowy"
        payload["workflow_input_hint"] = (
            "Bieżący run tablic jest już wczytany i gotowy do ręcznej poprawy przed powrotem do E3."
        )

    return payload


def build_z2_left_panel_copy_payload_campaign(
    host: "AnnotationTab",
    ctx: Z2LeftPanelCopyContext,
    payload: Z2CopyPayload,
) -> Z2CopyPayload:
    route = str(ctx.route or "")
    actual_route = str(ctx.actual_route or "")
    manual_entry_mode = str(ctx.manual_entry_mode or "")
    manual_setup = bool(ctx.manual_setup)
    manual_import = bool(ctx.manual_import)
    vehicle_assist_enabled = bool(ctx.vehicle_assist_enabled)
    auto_vehicle_choice = str(ctx.auto_vehicle_choice or "")
    current_step = str(ctx.current_step or "")
    plate_model_selected = bool(ctx.plate_model_selected)
    campaign_iteration_target = str(ctx.campaign_iteration_target or "")
    campaign_stage = int(ctx.campaign_stage or 0)
    campaign_iteration_num = int(ctx.campaign_iteration_num or 0)
    campaign_reused_manual_count = int(ctx.campaign_reused_manual_count or 0)
    campaign_char_repair_mode = bool(ctx.campaign_char_repair_mode)
    campaign_manual_skip_count = int(ctx.campaign_manual_skip_count or 0)
    has_existing_run = bool(ctx.has_existing_run)
    manual_review_active = bool(ctx.manual_review_active)
    has_manual_history = bool(ctx.has_manual_history)
    auto_completed = bool(ctx.auto_completed)
    current_batch_images = max(
        int(len(host.current_annotations or [])),
        int(dict(getattr(host, "_campaign_pending_batch_summary", {}) or {}).get("pending_count", 0) or 0),
    )

    if not route and campaign_stage == 2 and campaign_iteration_target == "char":
        payload["run_title"] = "Anotacja i korekta tablic"
        payload["badge_text"] = "Aktywny tor: przygotowanie źródła dla znaków"
        payload["badge_tone"] = "success"
        payload["route_text"] = (
            "Ten etap przygotowuje anotacje tablic potrzebne później w torze znaków. "
            "Jeśli uruchomisz autoanotację, domyślnie użyje aktywnego modelu tablic projektu."
        )
        payload["action_text"] = (
            "Możesz od razu przejść do anotacji ręcznych tablic i nadać im status [OK]. "
            "Jeśli chcesz, możesz też uruchomić autoanotację na modelu projektu albo podmienić model tylko dla tego runu Z2. "
            "Obrazy edytowane ręcznie i/lub ze statusem [OK] nie będą procesowane przez autoanotację - "
            "model raczej nie poprawi ręcznej korekty."
        )
        payload["workflow_start_title"] = "Anotacja i korekta tablic"
        payload["workflow_start_intro"] = (
            "Możesz od razu przejść do anotacji ręcznych tablic i nadać im status [OK]. "
            "Jeśli chcesz, możesz też uruchomić autoanotację na modelu projektu albo podmienić model tylko dla tego runu Z2. "
            "Obrazy edytowane ręcznie i/lub ze statusem [OK] nie będą procesowane przez autoanotację - "
            "model raczej nie poprawi ręcznej korekty."
        )
    if not plate_model_selected:
        payload["route_text"] = (
            "Na tym etapie dostępna jest ręczna anotacja tablic. "
            "Autoanotacja pojawi się, gdy projekt będzie miał aktywny model tablic."
        )
        payload["action_text"] = (
            "Przygotuj pierwszy zatwierdzony zestaw ręcznie. Po treningu modelu Z2 pokaże też tor autoanotacji."
        )

    if route == "auto":
        payload["run_title"] = (
            "Anotacja i korekta tablic"
            if campaign_iteration_target == "char"
            else "Autoanotacja i korekta tablic"
        )
        payload["badge_text"] = "Aktywny tor: przygotowanie tablic"
        payload["badge_tone"] = "success"
        payload["route_tone"] = "muted"
        payload["workflow_conf_title"] = "Ustaw pewność detekcji"
        payload["workflow_conf_hint"] = (
            "Ten próg dotyczy bieżącego runu anotacji Z2. Po wyborze modelu tablic możesz od razu go dopasować."
        )
        payload["workflow_vehicle_title"] = "Wskaż model pojazdów (YOLO Box)"
        payload["workflow_vehicle_hint"] = (
            "Ten model jest opcjonalny. Jeśli go pominiesz, run autoanotacji Z2 wykona tylko autoanotację tablic."
        )
        payload["workflow_input_title"] = "Wskaż folder obrazów"
        payload["workflow_input_hint"] = (
            "To jest paczka obrazów bieżącej iteracji. Opcjonalnie możesz też dołączyć ręcznie anotowane zdjęcia z wcześniejszych iteracji, które mają pozostać widoczne na liście Z2. Model tablic, confidence i opcjonalne boxy pojazdów ustawisz przy starcie autoanotacji w modalu."
        )
        payload["workflow_start_title"] = "Start autoanotacji bieżącego runu"
        payload["workflow_start_intro"] = (
            "Uruchom run na bieżącej paczce. Przy starcie wybierzesz w modalu zakres, model tablic, confidence "
            "i ewentualne boxy pojazdów, a po zakończeniu od razu sprawdzisz wynik w tym samym Z2. "
            "Zdjęcia już poprawione ręcznie albo oznaczone jako [OK] pozostaną na liście, ale nie będą ponownie przetwarzane."
        )
        payload["auto_plate_model_hint_text"] = (
            "Aktywny model projektu został już podstawiony do tego kroku. "
            "Możesz zostawić go bez zmian albo wskazać inny model tylko dla bieżącego runu Z2. "
            "Sama podmiana w Z2 nie zmieni modelu projektu."
        )

        if campaign_iteration_target == "char":
            payload["workflow_start_title"] = "Anotacja i korekta tablic"
            payload["workflow_start_intro"] = (
                "Możesz od razu przejść do anotacji ręcznych tablic i nadać im status [OK]. "
                "Jeśli chcesz, możesz też uruchomić autoanotację na modelu projektu albo podmienić model tylko dla tego runu Z2. "
                "Obrazy edytowane ręcznie i/lub ze statusem [OK] nie będą procesowane przez autoanotację - "
                "model raczej nie poprawi ręcznej korekty."
            )

        if not plate_model_selected:
            payload["route_text"] = "Model tablic wybierzesz przy starcie autoanotacji."
            payload["action_text"] = "Kliknij Start, a w modalu wskażesz zakres pracy i model dla bieżącego runu Z2."
            payload["workflow_start_intro"] = (
                "Start otworzy modal ustawień bieżącego runu Z2. Wybierzesz tam zakres obrazów, wymagany model tablic, "
                "confidence oraz opcjonalne wsparcie modelem pojazdów. Po zatwierdzeniu modala program uruchomi autoanotację, "
                "a wynik sprawdzisz i poprawisz na liście oraz podglądzie Z2."
            )
            payload["auto_plate_model_hint_text"] = (
                "Na tym etapie możesz wskazać aktywny model projektu albo podmienić go na inny model dla bieżącego runu Z2. "
                "Sama podmiana w Z2 nie zmieni modelu projektu."
            )
        elif auto_vehicle_choice == "skip":
            payload["route_text"] = "Najpierw uruchomisz autoanotację samych tablic na obrazach widocznych na liście wyników anotacji, a potem sprawdzisz i poprawisz wynik ręcznie w tym samym Z2."
            payload["action_text"] = "Po zapisaniu runu Z2 od razu otworzy listę wyników anotacji i podgląd do ręcznej korekty polygonów tablic dla obrazów z bieżącego katalogu. Jeśli wolisz, możesz też pominąć autoanotację i przejść od razu do ręcznej anotacji tych obrazów."
            if campaign_iteration_target == "char":
                payload["action_text"] += " W tym torze domyślnie użyty zostanie aktywny model tablic projektu, ale w kroku wyboru modelu możesz wskazać inny tylko dla tego runu."
        else:
            payload["route_text"] = "Najpierw uruchomisz autoanotację tablic i pojazdów na obrazach widocznych na liście wyników anotacji, a potem sprawdzisz i poprawisz wynik ręcznie w tym samym Z2."
            payload["action_text"] = "Po zapisaniu runu Z2 od razu otworzy listę wyników anotacji i podgląd do ręcznej korekty polygonów tablic dla obrazów z bieżącego katalogu. Jeśli wolisz, możesz też pominąć autoanotację i przejść od razu do ręcznej anotacji tych obrazów."
            if campaign_iteration_target == "char":
                payload["action_text"] += " W tym torze domyślnie użyty zostanie aktywny model tablic projektu, ale w kroku wyboru modelu możesz wskazać inny tylko dla tego runu."
            payload["auto_choice_hint"] = "Odznaczone pole oznacza wariant: pojazdy + tablice."

        payload["followup_title"] = "Po uruchomieniu przejdziesz do ręcznej korekty"
        payload["followup_text"] = (
            "Ten tor nie kończy się na samym uruchomieniu modeli. Po zapisaniu runu Z2 od razu sprawdzisz wynik, "
            "poprawisz polygony tablic ręcznie i dopiero potem domkniesz E2. To obejmuje również zdjęcia dołączone checkboxem z wcześniejszych iteracji."
        )
        payload["workflow_vehicle_title"] = "Wskaz model pojazdow do wsparcia tablic (YOLO Box)"
        payload["workflow_vehicle_hint"] = (
            "Ten model jest opcjonalny. Sluzy tylko do zawezenia szukania tablic do obszaru pojazdu. "
            "Boxy pojazdow sa pomocnicze i nie trafiaja do finalnego eksportu YOLO."
        )
        if auto_vehicle_choice == "skip":
            payload["auto_choice_hint"] = "Zaznaczone pole oznacza wariant: tylko tablice."
        else:
            payload["route_text"] = "Najpierw uruchomisz autoanotacje tablic ze wsparciem wykrywania pojazdow na obrazach widocznych na liscie wynikow anotacji, a potem sprawdzisz i poprawisz wynik recznie w tym samym Z2."
            payload["action_text"] = "W tym wariancie najpierw wykrywany jest pojazd, a model tablic szuka tablic tylko w jego obrebie. Boxy pojazdow pozostaja pomocnicze i nie trafiaja do finalnego YOLO."
            if campaign_iteration_target == "char":
                payload["action_text"] += " W tym torze domyslnie uzyty zostanie aktywny model tablic projektu, ale w kroku wyboru modelu mozesz wskazac inny tylko dla tego runu."
            payload["auto_choice_hint"] = "Odznaczone pole oznacza wariant: wsparcie pojazdami dla tablic."

        live_manual_skip_count = max(
            int(campaign_manual_skip_count or 0),
            len(host._collect_preview_manually_touched_filenames()),
        )
        if live_manual_skip_count > 0:
            payload["followup_text"] += (
                f" Obrazy już poprawione ręcznie w tym Z2 są automatycznie pomijane przy autoanotacji ({live_manual_skip_count})."
            )
        payload["export_text"] = "Split i eksport datasetu są kolejnym krokiem dopiero na gotowym, sprawdzonym runie Z2."

        if campaign_char_repair_mode:
            _apply_campaign_char_repair_copy_payload(payload)

    elif route == "manual":
        payload["run_title"] = (
            "Ręczna anotacja tablic" if manual_setup and not manual_review_active else "Korekta ręczna tablic"
        )
        payload["badge_text"] = "Aktywny tor: anotacja ręczna tablic"
        payload["badge_tone"] = "warning"
        payload["route_tone"] = "muted"
        payload["followup_title"] = "3. Ręczna korekta i stage"
        payload["followup_text"] = (
            "W tym torze pracujesz bez mieszania z autoanotacją. Po otwarciu runu anotacji możesz kasować obrazy, przenosić je do stage i poprawiać polygony."
        )
        payload["export_text"] = "Po zapisaniu zmian domkniesz E2, a dataset i trening wykonasz potem w [Z4]."
        payload["workflow_input_title"] = "2. Wskaż folder obrazów"
        payload["workflow_input_hint"] = "Najpierw wybierz folder obrazów. Ten folder będzie bazą nowego ręcznego runu anotacji Z2."

        if manual_review_active:
            if campaign_char_repair_mode:
                _apply_campaign_char_repair_copy_payload(payload, manual_review_active=True)
            else:
                payload["route_text"] = "Korygujesz bieżący run Z2 tej iteracji."
                payload["action_text"] = "Po prawej poprawiasz polygony aktywnego runu i po zakończeniu zmian domykasz E2."
                payload["workflow_start_intro"] = "Tutaj wracasz do aktywnego runu tej iteracji i poprawiasz jego wynik ręcznie."
                payload["manual_hint"] = "To nie jest osobny mini-workflow. Z2 jest już otwarte w trybie korekty aktywnego runu kampanii."
                payload["manual_hint_tone"] = "muted"
                payload["workflow_start_title"] = "Aktywna korekta runu Z2"
                payload["workflow_input_title"] = "Aktywny run kampanii"
                payload["workflow_input_hint"] = "Bieżący run Z2 jest już wczytany i gotowy do poprawiania."
        elif current_step == "manual_entry":
            if manual_import:
                payload["manual_hint"] = (
                    "Po kliknięciu Dalej wskażesz dowolny run Z2 do korekty. "
                    "Jeśli leży poza workspace, program bezpiecznie skopiuje go do lokalnego importu."
                )
            elif manual_entry_mode == "continue":
                payload["manual_hint"] = (
                    "Po kliknięciu Dalej przejdziesz do historii lokalnych runów Z2 "
                    "i wybierzesz run do wznowienia korekty."
                )
            else:
                payload["manual_hint"] = (
                    "Po kliknięciu Dalej przejdziesz do tworzenia nowego runu ręcznego Z2."
                )
            payload["manual_hint_tone"] = "muted"

        if manual_entry_mode == "continue":
            if current_step == "manual_history":
                payload["workflow_start_title"] = "Otwórz run anotacji do korekty"
                payload["route_text"] = "Na tym etapie wybierasz run Z2 z lokalnej historii i otwierasz go do dalszej pracy ręcznej."
                payload["action_text"] = (
                    "Zaznacz run Z2 z historii i kliknij Dalej, aby otworzyć go w edytorze."
                    if has_manual_history
                    else "Historia jest pusta. Wróć i wybierz nowy run ręczny albo wskaż dowolny run Z2."
                )
                payload["manual_hint"] = (
                    "Podgląd pozostaje wyłączony, dopóki nie otworzysz konkretnego runu Z2 z historii."
                    if has_manual_history
                    else "Jeśli nie masz jeszcze lokalnej historii runów, cofnij się i wybierz inny sposób wejścia."
                )
                payload["manual_hint_tone"] = "muted" if has_manual_history else "warning"
                payload["manual_template_hint"] = (
                    "Run Z2 do kontynuacji to katalog z annotations.xml i zgodnymi obrazami. "
                    f"Domyślny katalog runów Z2: {host._get_annotation_run_storage_display_path()}."
                )
                payload["manual_template_tone"] = "muted"
        elif manual_import:
            payload["route_text"] = "Wybrano tor wskazania dowolnego runu Z2 do korekty."
            payload["action_text"] = "Kliknij Dalej, aby wskazać run Z2 i ewentualnie zaimportować go do lokalnego workspace."
            payload["manual_hint"] = (
                "Program przyjmie tylko run Z2 z annotations.xml i zgodnymi obrazami. "
                "Jeśli taki run leży poza workspace, zostanie bezpiecznie skopiowany do lokalnego runu import_*."
            )
            payload["manual_hint_tone"] = "muted"
            payload["manual_template_hint"] = (
                f"Domyślny katalog runów Z2: {host._get_annotation_run_storage_display_path()}."
            )
            payload["manual_template_tone"] = "muted"
        else:
            payload["workflow_input_title"] = "Wskaż folder obrazów i opcje pomocy"
            payload["workflow_input_hint"] = (
                "Tutaj wybierasz obrazy dla nowego runu ręcznej anotacji Z2 oraz opcjonalnie włączasz pomocnicze boxy pojazdów."
            )
            payload["workflow_start_title"] = (
                "Przejdź do pracy na bieżącej paczce"
                if campaign_reused_manual_count > 0
                else "Rozpocznij pracę na bieżącej paczce"
            )
            payload["workflow_start_intro"] = (
                f"BIEŻĄCA PACZKA ZDJĘĆ WEJŚCIOWYCH ({current_batch_images}) ITERACJI {campaign_iteration_num} jest już wczytana do Z2. Utwórz plik anotacji tablic XML przyciskiem poniżej, aby rozpocząć oznaczanie tablic i zapisywać wynik w runie tej iteracji."
                if campaign_iteration_num > 0
                else f"BIEŻĄCA PACZKA ZDJĘĆ WEJŚCIOWYCH ({current_batch_images}) tej iteracji jest już wczytana do Z2. Utwórz plik anotacji tablic XML przyciskiem poniżej, aby rozpocząć oznaczanie tablic."
            )
            payload["route_text"] = (
                "Pracujesz bezpośrednio na paczce tej iteracji. Wcześniejsze ręczne korekty zostaną zachowane."
                if campaign_reused_manual_count > 0
                else "Paczka tej iteracji jest już gotowa do pracy. Nie musisz otwierać dodatkowego runu ani wskazywać nowego źródła."
            )
            payload["action_text"] = (
                "Kliknij przycisk poniżej, aby wejść do pracy na tej paczce. Wcześniejsze poprawki pozostaną zachowane."
                if campaign_reused_manual_count > 0
                else "Kliknij przycisk poniżej, aby zacząć oznaczać tablice na tej paczce. Gdy zapiszesz poprawne wyniki i oznaczysz obrazy jako [OK], odblokujesz domknięcie E2."
            )
            payload["manual_hint"] = (
                "Ten tor pracuje już na jednym runie tej iteracji, więc nie wymaga ręcznego zarządzania osobnym XML-em."
                if campaign_reused_manual_count > 0
                else "Z2 zapisuje wynik tej paczki w runie iteracji w tle. Użytkownik nie musi tworzyć ani otwierać dodatkowego runu ręcznie."
            )
            payload["manual_hint_tone"] = "muted"
            payload["manual_template_hint"] = (
                "Po wejściu do pracy na tej paczce wcześniejsze ręczne oznaczenia pozostają zachowane, a dalsze zmiany zapiszą się już w XML tej iteracji."
                if campaign_reused_manual_count > 0
                else "Wynik tej paczki zapisze się w workspace Z2 dla tej iteracji. Nie musisz ręcznie zarządzać plikami runu."
            )
            payload["manual_template_tone"] = "muted"
            payload["manual_vehicle_hint"] = "Opcjonalne boxy pojazdów są tylko pomocą przy ręcznej pracy."
            payload["manual_vehicle_tone"] = "muted"
            if campaign_iteration_num == 1 and not campaign_reused_manual_count:
                payload["run_intro_text"] = (
                    f"BIEŻĄCA PACZKA ZDJĘĆ WEJŚCIOWYCH ({current_batch_images}) ITERACJI 1 jest już wczytana do Z2 i gotowa do pracy. "
                    "To jest pierwsze bazowe przygotowanie tablic w projekcie. "
                    "Na niej przygotujesz pierwsze poprawne tablice potrzebne do odblokowania E2."
                )
                payload["route_text"] = (
                    "To jest pierwszy bazowy zestaw tablic dla projektu. "
                    "W tej iteracji pracujesz na już załadowanej paczce i przygotowujesz pierwsze poprawne tablice do odblokowania E2."
                )
                payload["action_text"] = (
                    "Przejdź do pracy na tej paczce, narysuj lub popraw tablice ręcznie i oznacz poprawne obrazy jako [OK]. "
                    "To otworzy bramkę dalszego etapu."
                )
            if vehicle_assist_enabled:
                payload["workflow_conf_title"] = "Pewność pomocniczych boxów pojazdów"
                payload["workflow_conf_hint"] = (
                    "Ten próg dotyczy tylko pomocniczego boxowania pojazdów w nowym XML."
                )
                payload["workflow_vehicle_title"] = "Model pojazdów do pomocniczego boxowania"
                payload["workflow_vehicle_hint"] = (
                    "Model pojazdów posłuży tylko jako wsparcie przy ręcznym rysowaniu tablic."
                )

        if not str(payload.route_text or "").strip():
            payload["route_text"] = (
                "Pracujesz ręcznie na bieżącej paczce tej iteracji. "
                "Możesz przygotować nowe oznaczenia albo poprawiać aktywny run Z2."
            )
        if not str(payload.action_text or "").strip():
            payload["action_text"] = (
                "Po prawej stronie wykonujesz właściwą pracę ręczną na obrazach tej iteracji, "
                "a zatwierdzone wyniki zasilą projektowy zbiór danych do treningu."
            )
        if not str(payload.workflow_start_intro or "").strip():
            payload["workflow_start_intro"] = "To jest główny krok roboczy tej części Z2."
        if (
            not str(payload.run_intro_text or "").strip()
            and route == "manual"
            and not manual_review_active
            and manual_setup
            and int(campaign_iteration_num or 0) <= 1
        ):
            payload["run_intro_text"] = (
                "Tutaj przygotowujesz pierwszy bazowy zestaw tablic dla projektu. "
                "Na tej paczce ręcznie ustawiasz rogi tablic i budujesz startowy run Z2, "
                "który później zatwierdzi E2 i posłuży do dalszego treningu."
            )

    return payload
