from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

from ..campaign_manager import CAMPAIGN
from ..config import logger
from .z3_view_models import (
    Step3CampaignNavigationViewModel,
    Step3EntryFlowViewModel,
    Step3FinishActionViewModel,
    Step3Pz3PathSelectionViewModel,
    Step3Pz3StatusPanelViewModel,
    Step3Pz3StatusRowViewModel,
)

if TYPE_CHECKING:
    from .tab_character_annotation import CharacterAnnotationTab


def enter_campaign_step3_mode(host: "CharacterAnnotationTab"):
    """
    Start kroku 3 od początku.
    """
    CAMPAIGN.reset_step3_progress()
    host.restore_campaign_step3_mode()
    host._set_button_emphasis("btn_to_detect_frame", False)
    host._set_button_emphasis("btn_to_dataset_frame", False)
    try:
        host._sync_yolo_model_binding()
    except Exception:
        pass


def open_campaign_step3_entry(
    host: "CharacterAnnotationTab",
    preferred_source_context: dict | None = None,
) -> dict:
    if not CAMPAIGN.get_active_project_name() or int(CAMPAIGN.get_current_step() or 0) < 3:
        return {"ok": False, "reason": "campaign_inactive"}

    raw_dir = CAMPAIGN.get_dir("raw")
    auto_dir = CAMPAIGN.get_dir("auto_ann")
    chars_dir = CAMPAIGN.get_dir("chars")
    datasets_dir = CAMPAIGN.get_dir("datasets")

    if raw_dir is None or auto_dir is None:
        return {"ok": False, "reason": "missing_campaign_dirs"}

    iter_num = CAMPAIGN.get_current_iteration_num()
    default_folder = Path(raw_dir) / f"Iteracja_{iter_num:03d}"
    folder = default_folder

    source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}
    if not source_context:
        try:
            source_context = host._get_registry_preferred_step3_source_candidate() or {}
        except Exception:
            source_context = {}
    preferred_run_dir = None
    preferred_xml = ""
    preferred_input_dir = None
    using_preferred_source = False

    try:
        restore_run_dir = source_context.get("restore_run_dir")
        if restore_run_dir:
            candidate_run_dir = Path(restore_run_dir)
            candidate_xml = candidate_run_dir / "annotations.xml"
            if candidate_run_dir.exists() and candidate_run_dir.is_dir() and candidate_xml.exists():
                preferred_run_dir = candidate_run_dir
                preferred_xml = str(candidate_xml)
    except Exception:
        preferred_run_dir = None
        preferred_xml = ""

    try:
        input_dir = source_context.get("input_dir")
        if input_dir:
            candidate_input_dir = Path(input_dir)
            if candidate_input_dir.exists() and candidate_input_dir.is_dir():
                preferred_input_dir = candidate_input_dir
    except Exception:
        preferred_input_dir = None

    if preferred_input_dir is not None:
        folder = preferred_input_dir
    elif not folder.exists():
        folder = Path(raw_dir)

    latest_xml = preferred_xml
    if latest_xml:
        using_preferred_source = True
    else:
        try:
            xml_files = list(Path(auto_dir).rglob("annotations.xml"))
        except Exception:
            xml_files = []
        latest_xml = str(max(xml_files, key=lambda p: p.stat().st_mtime)) if xml_files else ""

    host._set_preview_dir_runtime_value("", persist_registry=False)
    try:
        host._cancel_preview_char_label_interaction()
    except Exception:
        pass
    host.preview_metadata = {}
    host.preview_plate_ids = []
    host._loaded_meta_path = None
    host._loaded_meta_mtime = None
    host._preview_active_pid = None
    host._pz3_selected_path = "dataset"
    host._pz3_cvat_expanded = False
    try:
        host._reset_pz3_runtime_ui(collapse_cards=False)
    except Exception:
        pass

    try:
        host.plates_listbox.delete(0, 999999)
    except Exception:
        pass

    try:
        host.preview_canvas.delete("all")
    except Exception:
        pass

    try:
        host.preview_info_lbl.config(text="Oczekuje na nowy zestaw zdjęć...", foreground="#2980b9")
    except Exception:
        pass

    for attr_name in ("annotation_run_dir_var", "images_dir_var", "xml_path_var"):
        try:
            getattr(host, attr_name).set("")
        except Exception:
            pass

    try:
        latest_run_dir = str(Path(latest_xml).parent) if latest_xml else ""
    except Exception:
        latest_run_dir = ""

    host.set_pending_z2_annotation_source(
        xml_path=latest_xml,
        images_dir=(str(folder) if folder.exists() else ""),
        run_dir=latest_run_dir,
    )

    try:
        saved_extract_state = CAMPAIGN.get_step3_extract_state() or {}
    except Exception:
        saved_extract_state = {}

    try:
        saved_substep = int(CAMPAIGN.get_step3_substep() or 1)
    except Exception:
        saved_substep = 1

    try:
        has_saved_step3_progress = bool(
            saved_substep > 1
            or bool(CAMPAIGN.is_step3_stage1_done())
            or bool(CAMPAIGN.is_step3_stage2_done())
            or str(saved_extract_state.get("entry_mode", "") or "").strip()
            or str(saved_extract_state.get("workflow_step", "entry") or "entry").strip().lower() != "entry"
            or str(saved_extract_state.get("annotation_run_dir", "") or "").strip()
            or str(saved_extract_state.get("xml_path", "") or "").strip()
            or str(saved_extract_state.get("images_dir", "") or "").strip()
        )
    except Exception:
        has_saved_step3_progress = False

    if latest_xml and not has_saved_step3_progress:
        try:
            CAMPAIGN.set_step3_extract_state(
                entry_mode="continue",
                workflow_step="start",
                annotation_run_dir=latest_run_dir,
                xml_path=latest_xml,
                images_dir=(str(folder) if folder.exists() else ""),
            )
        except Exception as exc:
            logger.debug(f"Nie udało się ustawić domyslnego wejscia do Z3/PZ1: {exc}")
        try:
            host._sync_campaign_step3_artifact_registry(
                entry_mode="continue",
                workflow_step="start",
                annotation_run_dir=latest_run_dir,
                xml_path=latest_xml,
                images_dir=(str(folder) if folder.exists() else ""),
            )
        except Exception:
            pass

    host._campaign_chars_dir = str(chars_dir) if chars_dir else None
    host._campaign_datasets_dir = str(datasets_dir) if datasets_dir else None

    registry_bundle = host._get_campaign_iteration_artifact_bundle()
    registry_char_model = dict(registry_bundle.get("char_model") or {})
    char_model_path = str(CAMPAIGN.get_global_model("char") or "").strip()
    if not char_model_path or not Path(char_model_path).exists():
        char_model_path = str(registry_char_model.get("path") or "").strip()
    if char_model_path and Path(char_model_path).exists():
        host.detection_method_var.set("BOTH")
        host.yolo_model_path_var.set(char_model_path)

        try:
            version, size = host._infer_yolo_arch_from_model_path(char_model_path)
            if version in {"8", "11", "26"}:
                host.yolo_model_version_var.set(version)
            if size in {"n", "s", "m", "l", "x"}:
                host.yolo_model_size_var.set(size)
        except Exception as exc:
            logger.debug(f"Nie udało się odczytać architektury YOLO z nazwy modelu: {exc}")

        try:
            host._sync_yolo_model_binding()
        except Exception as exc:
            logger.debug(f"Nie udało się zsynchronizowac ścieżki modelu YOLO: {exc}")

        try:
            host._update_yolo_visibility()
        except Exception as exc:
            logger.debug(f"Nie udało się odświeżyć widoku YOLO w Zakładce Znaków: {exc}")
    else:
        try:
            host.detection_method_var.set("OCR")
            host.yolo_model_path_var.set("")
            host._update_yolo_visibility()
        except Exception as exc:
            logger.debug(f"Nie udało się ustawić trybu OCR dla braku modelu znaków: {exc}")
        try:
            host._sync_yolo_model_binding()
        except Exception:
            pass

        try:
            host._update_yolo_visibility()
        except Exception:
            pass

    try:
        host._restore_preview_context_from_project()
    except Exception as exc:
        logger.debug(f"Nie udało się przywrocic preview projektu: {exc}")

    try:
        host.restore_campaign_step3_mode()
    except Exception as exc:
        logger.debug(f"Nie udało się przywrocic stanu kroku 3: {exc}")
        CAMPAIGN.reset_step3_progress()
        enter_campaign_step3_mode(host)

    try:
        host._refresh_extract_workflow_ui()
    except Exception:
        pass

    try:
        refresh_pz3_cards = getattr(host, "_refresh_pz3_cards_ui", None)
        if callable(refresh_pz3_cards):
            refresh_pz3_cards()
    except Exception:
        pass

    try:
        host._hide_campaign_detect_splash()
    except Exception:
        pass

    try:
        host._auto_progress_campaign_step3_entry(preferred_source_context=source_context)
    except Exception as exc:
        logger.debug(f"Nie udało się automatycznie ustawić wejścia kampanii do Z3: {exc}")

    return {
        "ok": True,
        "latest_xml": latest_xml,
        "images_dir": (str(folder) if folder.exists() else ""),
        "using_preferred_source": bool(using_preferred_source),
        "preferred_run_dir": str(preferred_run_dir or ""),
        "char_model_path": char_model_path,
    }


def auto_progress_campaign_step3_entry(
    host: "CharacterAnnotationTab",
    preferred_source_context: dict | None = None,
) -> dict:
    plan = get_campaign_step3_entry_flow_view_model(
        host,
        preferred_source_context=preferred_source_context,
    )

    result = {
        "handled": False,
        "mode": str(getattr(plan, "mode", "") or "").strip(),
        "message": str(getattr(plan, "message", "") or "").strip(),
    }

    if getattr(plan, "should_hide_splash", False):
        try:
            host._hide_campaign_detect_splash()
        except Exception:
            pass

    if getattr(plan, "should_show_splash", False):
        try:
            host._show_campaign_detect_splash(
                title=str(getattr(plan, "splash_title", "") or "").strip(),
                body=str(getattr(plan, "splash_body", "") or "").strip(),
                tone=str(getattr(plan, "splash_tone", "info") or "info"),
                progress=(0.0 if getattr(plan, "splash_show_progress", False) else None),
                show_progress=bool(getattr(plan, "splash_show_progress", False)),
                show_return=bool(getattr(plan, "splash_show_return", False)),
            )
        except Exception:
            pass

    mode = str(getattr(plan, "mode", "") or "").strip().lower()
    if mode == "source_invalid":
        return result

    if mode == "auto_extract":
        try:
            if hasattr(host.app, "update_status"):
                host.app.update_status(
                    "Przygotowuję tablice dla Z3. Wyodrębnianie uruchomi się automatycznie, a po nim otworzę PZ2.",
                    "info",
                )
        except Exception:
            pass

        def _auto_start_extraction():
            try:
                if not (getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name()):
                    return
                if getattr(host, "is_processing", False):
                    return
                host._run_extraction()
            except Exception as exc:
                logger.debug(f"Nie udało się automatycznie uruchomić PZ1 dla kampanii: {exc}")

        frame = getattr(host, "frame", None)
        if frame is not None:
            frame.after(80, _auto_start_extraction)
        else:
            _auto_start_extraction()

        result["handled"] = True
        return result

    if mode == "open_detect" or int(getattr(plan, "target_substep", 0) or 0) >= 2:
        try:
            host._set_extraction_status(
                "Wyodrębnione tablice są już gotowe. Otwieram od razu PZ2 do pracy nad znakami.",
                "success",
            )
        except Exception:
            pass
        try:
            if hasattr(host.app, "update_status"):
                host.app.update_status(
                    "Tablice dla Z3 są już przygotowane. Otwieram od razu PZ2.",
                    "info",
                )
        except Exception:
            pass

        def _auto_open_detect():
            try:
                if not (getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name()):
                    return
                host.go_to_substep_2()
            except Exception as exc:
                logger.debug(f"Nie udało się automatycznie otworzyć PZ2 dla kampanii: {exc}")

        frame = getattr(host, "frame", None)
        if frame is not None:
            frame.after(0, _auto_open_detect)
        else:
            _auto_open_detect()

        result["handled"] = True
        return result

    if mode == "restore_existing_substep":
        result["handled"] = True

    return result


def get_campaign_step3_entry_flow_view_model(
    host: "CharacterAnnotationTab",
    preferred_source_context: dict | None = None,
) -> Step3EntryFlowViewModel:
    try:
        if not (getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name()):
            return Step3EntryFlowViewModel()
    except Exception:
        return Step3EntryFlowViewModel()

    try:
        saved_substep = int(CAMPAIGN.get_step3_substep() or 1)
    except Exception:
        saved_substep = 1

    refresh_state = get_campaign_step3_source_refresh_state(
        host,
        preferred_source_context=preferred_source_context,
    )

    if bool(refresh_state.get("needs_reextract")):
        prepare_campaign_step3_reextract_from_current_source(
            host,
            preferred_source_context=preferred_source_context,
        )
        try:
            host._set_subtab_state(host.tab_extract, "disabled")
            host._set_subtab_state(host.tab_detect, "normal")
            host._set_subtab_state(host.tab_dataset, "disabled")
            host._select_subtab(host.tab_detect)
        except Exception:
            pass

        validation = host._refresh_source_binding_status(allow_autofind=True)
        if not bool(validation.get("ok")):
            msg = str(
                validation.get("message")
                or refresh_state.get("message")
                or "Źródło tablic nie jest jeszcze gotowe do automatycznego wycinania."
            ).strip()
            return Step3EntryFlowViewModel(
                mode="source_invalid",
                message=msg,
                should_show_splash=True,
                splash_title="Nie mogę przygotować tablic dla Z3",
                splash_body=msg,
                splash_tone="error",
                splash_show_progress=False,
                splash_show_return=True,
            )

        return Step3EntryFlowViewModel(
            mode="auto_extract",
            message="Uruchamiam wyodrębnianie tablic do PZ2.",
            target_substep=2,
            should_show_splash=True,
            splash_title="Przygotowuję wycięte tablice dla Z3",
            splash_body=(
                "To automatyczny krok pośredni przed pracą nad znakami. "
                "Gdy wycinanie się zakończy, od razu otworzę PZ2."
            ),
            splash_tone="info",
            splash_show_progress=True,
            splash_show_return=False,
        )

    if saved_substep >= 2 and host.can_restore_step3_substep(saved_substep):
        return Step3EntryFlowViewModel(
            mode="restore_existing_substep",
            message="Przywracam zapisany etap pracy w Z3.",
            target_substep=int(saved_substep),
            should_hide_splash=True,
        )

    if host.can_restore_step3_substep(2):
        return Step3EntryFlowViewModel(
            mode="open_detect",
            message="Otwieram PZ2 na gotowej paczce tablic.",
            target_substep=2,
            should_hide_splash=True,
        )

    return Step3EntryFlowViewModel()


def get_campaign_step3_source_refresh_state(
    host: "CharacterAnnotationTab",
    preferred_source_context: dict | None = None,
) -> dict:
    result = {
        "needs_reextract": False,
        "reason": "",
        "message": "",
        "source_xml": "",
        "source_run_dir": "",
        "preview_dir": "",
    }

    try:
        if not (getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name()):
            return result
    except Exception:
        return result

    source_context = preferred_source_context if isinstance(preferred_source_context, dict) else {}

    source_xml_raw = str(
        source_context.get("xml_path")
        or (host.xml_path_var.get() if hasattr(host, "xml_path_var") else "")
        or ""
    ).strip()
    source_run_raw = str(
        source_context.get("restore_run_dir")
        or source_context.get("run_dir")
        or (host.annotation_run_dir_var.get() if hasattr(host, "annotation_run_dir_var") else "")
        or ""
    ).strip()
    preview_dir_raw = str(
        host.preview_dir_var.get() if hasattr(host, "preview_dir_var") else ""
    ).strip()

    result["source_xml"] = source_xml_raw
    result["source_run_dir"] = source_run_raw
    result["preview_dir"] = preview_dir_raw

    if not source_xml_raw:
        return result

    try:
        source_xml = Path(source_xml_raw)
    except Exception:
        return result

    if not source_xml.exists() or not source_xml.is_file():
        return result

    if not preview_dir_raw:
        result.update(
            needs_reextract=True,
            reason="missing_preview",
            message="Tablice z Z2 są gotowe, ale w Z3 nie ma jeszcze aktualnej paczki tablic. Najpierw uruchom wycinanie w PZ1.",
        )
        return result

    try:
        preview_dir = Path(preview_dir_raw)
    except Exception:
        result.update(
            needs_reextract=True,
            reason="invalid_preview_dir",
            message="Poprzednia paczka tablic nie jest już dostępna. Najpierw uruchom ponowne wycinanie w PZ1.",
        )
        return result

    meta_path = preview_dir / "metadata.json"
    images_dir = preview_dir / "images"
    if not preview_dir.exists() or not preview_dir.is_dir() or not meta_path.exists() or not images_dir.exists():
        result.update(
            needs_reextract=True,
            reason="incomplete_preview",
            message="Poprzednia paczka tablic jest niepelna. Najpierw uruchom ponowne wycinanie w PZ1.",
        )
        return result

    try:
        saved_state = CAMPAIGN.get_step3_extract_state() or {}
    except Exception:
        saved_state = {}

    saved_xml_raw = str(saved_state.get("xml_path", "") or "").strip()
    saved_run_raw = str(saved_state.get("annotation_run_dir", "") or "").strip()

    def _safe_path_key(raw_value: str) -> str:
        raw_value = str(raw_value or "").strip()
        if not raw_value:
            return ""
        try:
            return str(Path(raw_value).resolve())
        except Exception:
            return raw_value

    source_xml_key = _safe_path_key(source_xml_raw)
    saved_xml_key = _safe_path_key(saved_xml_raw)
    source_run_key = _safe_path_key(source_run_raw)
    saved_run_key = _safe_path_key(saved_run_raw)

    if saved_xml_key and source_xml_key and saved_xml_key != source_xml_key:
        result.update(
            needs_reextract=True,
            reason="source_xml_changed",
            message="Zmienilo się źródło anotacji tablic z Z2. Najpierw uruchom ponowne wycinanie w PZ1.",
        )
        return result

    if saved_run_key and source_run_key and saved_run_key != source_run_key:
        result.update(
            needs_reextract=True,
            reason="source_run_changed",
            message="Zmienil się run tablic z Z2. Najpierw uruchom ponowne wycinanie w PZ1.",
        )
        return result

    try:
        source_mtime = float(source_xml.stat().st_mtime)
        preview_mtime = float(meta_path.stat().st_mtime)
        if source_mtime > (preview_mtime + 0.001):
            result.update(
                needs_reextract=True,
                reason="source_xml_newer_than_preview",
                message="Anotacje tablic w Z2 zostały rozszerzone po ostatnim wycinaniu. Najpierw uruchom ponowne wycinanie w PZ1.",
            )
            return result
    except Exception:
        pass

    return result


def prepare_campaign_step3_reextract_from_current_source(
    host: "CharacterAnnotationTab",
    preferred_source_context: dict | None = None,
) -> dict:
    refresh_state = get_campaign_step3_source_refresh_state(host, preferred_source_context=preferred_source_context)
    if not bool(refresh_state.get("needs_reextract")):
        return refresh_state

    try:
        host._campaign_step3_reextract_seed_metadata = host._capture_preview_reextract_seed_metadata()
    except Exception:
        host._campaign_step3_reextract_seed_metadata = {}

    try:
        host._set_preview_dir_runtime_value("", persist_registry=False)
    except Exception:
        pass

    try:
        CAMPAIGN.set_step3_preview_dir("")
    except Exception:
        pass

    host.preview_metadata = {}
    host.preview_plate_ids = []
    host._loaded_meta_path = None
    host._loaded_meta_mtime = None

    try:
        host._reset_preview_cache()
    except Exception:
        pass

    try:
        host.plates_listbox.delete(0, tk.END)
    except Exception:
        pass

    try:
        host.preview_canvas.delete("all")
    except Exception:
        pass

    try:
        host.preview_info_lbl.config(
            text="Źródło z Z2 zmienilo się. Najpierw uruchom ponowne wycinanie tablic w PZ1.",
            foreground="#b9770e",
        )
    except Exception:
        pass

    try:
        host._set_extraction_status(
            "Źródło z Z2 zmienilo się. Uruchom ponowne wycinanie tablic.",
            "warning",
        )
    except Exception:
        pass

    try:
        CAMPAIGN.set_step3_needs_rework()
        CAMPAIGN.set_step3_stage1_done(False)
        CAMPAIGN.set_step3_stage2_done(False)
        CAMPAIGN.set_step3_substep(1)
    except Exception:
        pass

    try:
        host._extract_workflow_step = "start"
        host._persist_step3_extract_state()
    except Exception:
        pass

    try:
        host._set_subtab_state(host.tab_extract, "normal")
        host._set_subtab_state(host.tab_detect, "disabled")
        host._set_subtab_state(host.tab_dataset, "disabled")
        host._set_button_state("btn_to_detect", False)
        host._set_button_state("btn_to_dataset", False)
        host._set_button_emphasis("btn_to_detect_frame", False)
        host._set_button_emphasis("btn_to_dataset_frame", False)
    except Exception:
        pass

    try:
        host._select_subtab(host.tab_extract)
    except Exception:
        pass

    try:
        host._refresh_extract_workflow_ui()
    except Exception:
        pass

    try:
        host._persist_step3_progress()
    except Exception:
        pass

    try:
        host._update_step3_finish_button_state()
    except Exception:
        pass

    return refresh_state


def unlock_detection_subtab(host: "CharacterAnnotationTab"):
    host._set_button_state("btn_to_detect", True)
    host._set_button_emphasis("btn_to_detect_frame", False)
    try:
        host._refresh_extract_workflow_ui()
    except Exception:
        pass

    if getattr(host, "_step3_linear_mode", False):
        CAMPAIGN.set_step3_stage1_done(True)
        host._persist_step3_progress()


def unlock_dataset_subtab(host: "CharacterAnnotationTab"):
    host._set_button_state("btn_to_dataset", True)
    host._set_button_emphasis("btn_run_detection_frame", False)
    host._set_button_emphasis("btn_to_dataset_frame", True)

    if getattr(host, "_step3_linear_mode", False):
        CAMPAIGN.set_step3_stage2_done(True)
        host._persist_step3_progress()


def go_to_substep_2_campaign(host: "CharacterAnnotationTab"):
    try:
        host._hide_campaign_detect_splash()
    except Exception:
        pass
    try:
        host._cancel_preview_char_label_interaction()
    except Exception:
        pass
    btn = getattr(host, "btn_to_detect", None)
    if btn is not None and str(btn.cget("state")) != "normal":
        return

    host._set_subtab_state(host.tab_extract, "disabled")
    host._set_subtab_state(host.tab_detect, "normal")
    host._set_subtab_state(host.tab_dataset, "disabled")

    CAMPAIGN.set_step3_substep(2)
    host._select_subtab(host.tab_detect)
    host._persist_step3_progress()
    try:
        host._refresh_campaign_step3_navigation_visibility()
    except Exception:
        pass


def go_to_substep_3_campaign(host: "CharacterAnnotationTab"):
    try:
        host._hide_campaign_detect_splash()
    except Exception:
        pass
    try:
        host._cancel_preview_char_label_interaction()
    except Exception:
        pass
    btn = getattr(host, "btn_to_dataset", None)
    if btn is not None and str(btn.cget("state")) != "normal":
        return

    host._set_subtab_state(host.tab_extract, "disabled")
    host._set_subtab_state(host.tab_detect, "disabled")
    host._set_subtab_state(host.tab_dataset, "normal")

    CAMPAIGN.set_step3_substep(3)
    host._select_subtab(host.tab_dataset)
    host._persist_step3_progress()
    host._set_button_emphasis("btn_run_detection_frame", False)
    host._set_button_emphasis("btn_to_dataset_frame", False)
    try:
        host._refresh_campaign_step3_navigation_visibility()
    except Exception:
        pass


def back_to_substep_1_campaign(host: "CharacterAnnotationTab"):
    try:
        host._cancel_preview_char_label_interaction()
    except Exception:
        pass
    host._set_subtab_state(host.tab_extract, "normal")
    host._set_subtab_state(host.tab_detect, "disabled")
    host._set_subtab_state(host.tab_dataset, "disabled")
    host._set_button_state("btn_to_detect", False)
    host._set_button_state("btn_to_dataset", False)

    host._set_button_emphasis("btn_to_detect_frame", False)
    host._set_button_emphasis("btn_to_dataset_frame", False)

    CAMPAIGN.set_step3_substep(1)
    host._select_subtab(host.tab_extract)
    host._persist_step3_progress()


def back_to_substep_2_campaign(host: "CharacterAnnotationTab"):
    try:
        host._cancel_preview_char_label_interaction()
    except Exception:
        pass
    host._set_subtab_state(host.tab_extract, "disabled")
    host._set_subtab_state(host.tab_detect, "normal")
    host._set_subtab_state(host.tab_dataset, "disabled")
    host._set_button_state("btn_to_dataset", host.can_restore_step3_substep(3))

    host._set_button_emphasis("btn_to_dataset_frame", False)

    CAMPAIGN.set_step3_substep(2)
    host._select_subtab(host.tab_detect)
    host._persist_step3_progress()


def persist_step3_progress(host: "CharacterAnnotationTab"):
    if not getattr(host, "_step3_linear_mode", False):
        return

    try:
        if CAMPAIGN.get_active_project_name():
            if str(CAMPAIGN.get_step2_status() or "").strip().lower() != "approved":
                CAMPAIGN.approve_step2()
            if int(CAMPAIGN.get_current_step() or 0) < 3:
                CAMPAIGN.set_current_step(3)
    except Exception as exc:
        logger.debug(f"Nie udało się zsynchronizowac stanu kampanii z E3: {exc}")

    current_substep = 1
    try:
        selected = str(host.main_nb.select())
        if selected == str(host.tab_extract):
            current_substep = 1
        elif selected == str(host.tab_detect):
            current_substep = 2
        elif selected == str(host.tab_dataset):
            current_substep = 3
    except Exception:
        current_substep = 1

    CAMPAIGN.set_step3_substep(current_substep)

    stage1_done = False
    stage2_done = False

    try:
        btn = getattr(host, "btn_to_detect", None)
        if btn is not None:
            stage1_done = str(btn.cget("state")) == "normal"
    except Exception:
        pass

    try:
        btn = getattr(host, "btn_to_dataset", None)
        if btn is not None:
            stage2_done = str(btn.cget("state")) == "normal"
    except Exception:
        pass

    CAMPAIGN.set_step3_stage1_done(stage1_done)
    CAMPAIGN.set_step3_stage2_done(stage2_done)


def restore_campaign_step3_mode(host: "CharacterAnnotationTab"):
    """
    Przywraca zapisany postęp kroku 3 aktywnego projektu.
    """
    host._step3_linear_mode = True

    try:
        host._restore_step3_extract_state_from_project()
    except Exception as exc:
        logger.debug(f"Nie udało się przywrocic stanu wejscia PZ1: {exc}")

    saved_substep = CAMPAIGN.get_step3_substep()
    stage1_done = CAMPAIGN.is_step3_stage1_done()
    stage2_done = CAMPAIGN.is_step3_stage2_done()

    if saved_substep > 1 and not (host.preview_dir_var.get() or "").strip():
        try:
            host._restore_preview_context_from_project()
        except Exception:
            pass

    try:
        if host.can_restore_step3_substep(2):
            stage1_done = True
    except Exception:
        pass

    try:
        if host._preview_dir_has_completed_detection_output():
            stage2_done = True
    except Exception:
        pass

    try:
        if stage1_done:
            CAMPAIGN.set_step3_stage1_done(True)
        if stage2_done:
            CAMPAIGN.set_step3_stage2_done(True)
    except Exception:
        pass

    try:
        if saved_substep < 2 and host.can_restore_step3_substep(2):
            saved_substep = 2
        if saved_substep < 3 and host.can_restore_step3_substep(3):
            saved_substep = 3
    except Exception:
        pass
    if not host.can_restore_step3_substep(saved_substep):
        saved_substep = 1
        stage1_done = False
        stage2_done = False

        try:
            CAMPAIGN.reset_step3_progress()
        except Exception:
            pass

    host._set_button_state("btn_to_detect", stage1_done)
    host._set_button_state("btn_to_dataset", stage2_done)

    if saved_substep <= 1:
        host._set_subtab_state(host.tab_extract, "normal")
        host._set_subtab_state(host.tab_detect, "disabled")
        host._set_subtab_state(host.tab_dataset, "disabled")
        host._select_subtab(host.tab_extract)
    elif saved_substep == 2:
        host._set_subtab_state(host.tab_extract, "disabled")
        host._set_subtab_state(host.tab_detect, "normal")
        host._set_subtab_state(host.tab_dataset, "disabled")
        host._select_subtab(host.tab_detect)
    else:
        host._set_subtab_state(host.tab_extract, "disabled")
        host._set_subtab_state(host.tab_detect, "disabled")
        host._set_subtab_state(host.tab_dataset, "normal")
        host._select_subtab(host.tab_dataset)

    host._set_button_emphasis("btn_run_detection_frame", False)
    host._set_button_emphasis("btn_to_dataset_frame", False)

    if saved_substep == 2 and not stage2_done:
        host._set_button_emphasis("btn_run_detection_frame", True)
    elif saved_substep == 2 and stage2_done:
        host._set_button_emphasis("btn_to_dataset_frame", True)
    elif saved_substep == 3:
        host._update_step3_finish_button_state()

    try:
        host._update_preview_path_lock()
    except Exception:
        pass

    try:
        host._update_step3_source_path_lock()
    except Exception:
        pass

    try:
        host._sync_yolo_model_binding()
    except Exception:
        pass

    try:
        host._update_yolo_visibility()
    except Exception:
        pass

    try:
        persist_step3_progress(host)
    except Exception:
        pass

    try:
        host._update_step3_finish_button_state()
    except Exception:
        pass

    try:
        host._refresh_step3_mode_specific_ui()
    except Exception:
        pass

    try:
        host._refresh_extract_workflow_ui()
    except Exception:
        pass


def build_step3_campaign_navigation_view_model(
    host: "CharacterAnnotationTab",
) -> Step3CampaignNavigationViewModel:
    try:
        in_campaign = bool(getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())
    except Exception:
        in_campaign = False

    splash_visible = bool(getattr(host, "_campaign_detect_splash_visible", False))
    return Step3CampaignNavigationViewModel(
        in_campaign=in_campaign,
        splash_visible=splash_visible,
        show_detect_back_to_extract=not in_campaign,
        show_detect_to_dataset=(not in_campaign) or (not splash_visible),
        show_dataset_back_to_detect=True,
    )


def build_step3_finish_action_view_model(
    host: "CharacterAnnotationTab",
) -> Step3FinishActionViewModel:
    try:
        in_campaign = bool(getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())
    except Exception:
        in_campaign = False

    if not in_campaign:
        return Step3FinishActionViewModel()

    readiness = host._get_campaign_step3_training_readiness()
    has_outputs = host._has_any_step3_export_outputs()
    ready_for_approval = bool(has_outputs and bool(readiness.get("ok")))

    try:
        current_status = str(CAMPAIGN.get_step3_status() or "").strip().lower() or "pending"
    except Exception:
        current_status = "pending"

    finish_hint = "Powrot nie zamyka etapu. Mozesz wrocic do Z3 w dowolnym momencie."
    finish_tone = "muted"
    emphasize = False

    if ready_for_approval:
        finish_hint = "Dataset znakow jest gotowy. W wizardzie zatwierdzisz E3 i odblokujesz E4."
        finish_tone = "success"
        emphasize = True
    elif current_status == "needs_rework":
        finish_hint = host._get_step3_finish_block_message(readiness)
        finish_tone = "warning"
    elif current_status == "approved":
        finish_hint = "Etap 3 jest juz zatwierdzony. Wizard otworzy sie od razu na E4."
        finish_tone = "success"
    elif not has_outputs:
        finish_hint = host._get_step3_finish_block_message(readiness) or finish_hint
        finish_tone = "warning"

    return Step3FinishActionViewModel(
        visible=True,
        label="Wroc do wizarda",
        command_id="return_to_wizard_step3",
        enabled=True,
        emphasize=emphasize,
        hint=finish_hint,
        hint_tone=finish_tone,
        back_to_wizard_enabled=True,
    )


def build_step3_pz3_path_selection_view_model(
    host: "CharacterAnnotationTab",
) -> Step3Pz3PathSelectionViewModel:
    selected_path = str(getattr(host, "_pz3_selected_path", "") or "").strip().lower()
    selected_path = selected_path if selected_path in {"dataset", "cvat"} else ""
    try:
        in_campaign = bool(getattr(host, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())
    except Exception:
        in_campaign = False
    if not selected_path:
        selected_path = "dataset"
    return Step3Pz3PathSelectionViewModel(
        selected_path=selected_path,
        show_dataset_section=True,
        show_cvat_section=(selected_path == "cvat"),
        show_status_section=False,
        dataset_card_selected=True,
        cvat_card_selected=(selected_path == "cvat"),
        dataset_badge_text="DATASET",
        dataset_title_text="Dataset znaków",
        dataset_desc_text="Główna ścieżka PZ3: źródło pracy, opcjonalne poprawki i eksport datasetu.",
        cvat_badge_text="OPCJA",
        cvat_title_text="Review pack do CVAT",
        cvat_desc_text="Eksportuje cropy tablic z boxami znaków. Ten format jest zgodny z importem poprawek CVAT.",
    )


def build_step3_pz3_status_panel_view_model(
    host: "CharacterAnnotationTab",
) -> Step3Pz3StatusPanelViewModel:
    path_vm = build_step3_pz3_path_selection_view_model(host)
    finish_action = build_step3_finish_action_view_model(host)
    export_text, export_tone = host._get_inline_status_widget_snapshot(
        getattr(host, "export_console", None),
        fallback_text="—",
        fallback_tone="muted",
    )
    import_text, import_tone = host._get_inline_status_widget_snapshot(
        getattr(host, "import_console", None),
        fallback_text="—",
        fallback_tone="muted",
    )

    return Step3Pz3StatusPanelViewModel(
        title="Podsumowanie",
        show_section=bool(path_vm.show_status_section),
        export_row=Step3Pz3StatusRowViewModel(
            label="Eksport",
            text=export_text,
            tone=export_tone,
        ),
        import_row=Step3Pz3StatusRowViewModel(
            label="Import",
            text=import_text,
            tone=import_tone,
        ),
        finish_action=finish_action,
    )


def refresh_campaign_step3_navigation_visibility(host: "CharacterAnnotationTab"):
    view_model = build_step3_campaign_navigation_view_model(host)

    back_to_extract = getattr(host, "btn_back_to_extract", None)
    if back_to_extract is not None:
        try:
            if not bool(view_model.show_detect_back_to_extract):
                if str(back_to_extract.winfo_manager()):
                    back_to_extract.grid_remove()
            elif not str(back_to_extract.winfo_manager()):
                back_to_extract.grid(row=0, column=0, sticky="w")
        except Exception:
            pass

    to_dataset_frame = getattr(host, "btn_to_dataset_frame", None)
    if to_dataset_frame is not None:
        try:
            if not bool(view_model.show_detect_to_dataset):
                if str(to_dataset_frame.winfo_manager()):
                    to_dataset_frame.grid_remove()
            elif not str(to_dataset_frame.winfo_manager()):
                to_dataset_frame.grid(row=0, column=2, sticky="e", padx=(10, 0))
        except Exception:
            pass

    back_to_detect = getattr(host, "btn_back_to_detect", None)
    back_to_detect_frame = getattr(host, "pz3_back_to_detect_frame", None)
    if back_to_detect is not None and back_to_detect_frame is not None:
        try:
            if not bool(view_model.show_dataset_back_to_detect):
                if str(back_to_detect_frame.winfo_manager()):
                    back_to_detect_frame.pack_forget()
            elif not str(back_to_detect_frame.winfo_manager()):
                back_to_detect_frame.pack(side=tk.LEFT, fill=tk.Y)
                if not str(back_to_detect.winfo_manager()):
                    back_to_detect.pack(side=tk.BOTTOM)
        except Exception:
            pass
