#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Runtime uruchamiania detekcji znaków Z3/PZ2."""

import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import cv2

from ..campaign_manager import CAMPAIGN
from ..config import get_yolo_class, logger
from ..character_recognition import CharacterDetector, DetectionMethod
from ..ocr import PlateOCR
from ..utils import cleanup_gpu_memory

def run_detection_stage(host):
    self = host
    method = self._get_detection_method_key()
    try:
        self.detection_method_var.set(method)
    except Exception:
        pass
    all_plate_ids = self._get_sorted_preview_plate_ids(list(getattr(self, "preview_metadata", {}).keys()))
    if not all_plate_ids:
        return messagebox.showinfo("Brak", "Wczytaj katalog wyodrębnionych tablic.")

    guard_options = self._prompt_pz2_detection_guard_options(method)
    if guard_options is None:
        return

    effective_device_choice = self._get_effective_detection_device_choice()
    effective_yolo_device = self._device_to_ultralytics(effective_device_choice)
    effective_ocr_device = self._device_to_ocr(effective_device_choice)

    if method in ("YOLO", "BOTH", "YOLO_OCR"):
        try:
            yolo_runtime = self._get_yolo_runtime_settings()
        except Exception as e:
            messagebox.showwarning("Błędne parametry YOLO", str(e))
            return

        try:
            resolved_model = self._ensure_yolo_model_checkpoint()
            self.yolo_model_path_var.set(resolved_model)
            version, size = self._infer_yolo_arch_from_model_path(resolved_model)
            model_name = Path(resolved_model).name
            model_desc = f"{model_name} (YOLOv{version}{size})" if version and size else model_name

            self._log(
                self.test_log_text,
                f"[INFO] Model detekcji znaków: {model_desc}",
                "INFO"
            )
            self._log(
                self.test_log_text,
                f"[INFO] Model gotowy do użycia: {resolved_model}",
                "INFO"
            )
            self._log(
                self.test_log_text,
                "[INFO] Urzadzenie: "
                f"{effective_device_choice} | "
                f"YOLO={effective_yolo_device} | "
                f"OCR={effective_ocr_device}",
                "INFO"
            )
            self._log(
                self.test_log_text,
                "[INFO] Parametry YOLO: "
                f"conf={yolo_runtime['conf']:.2f}, "
                f"nms_iou={yolo_runtime['iou']:.2f}, "
                f"overlap={yolo_runtime['overlap']:.2f}, "
                f"agnostic_nms={yolo_runtime['agnostic_nms']}, "
                f"seq_y={yolo_runtime['seq_center_y']:.2f}, "
                f"seq_h_min={yolo_runtime['seq_min_h']:.2f}, "
                f"seq_h_max={yolo_runtime['seq_max_h']:.2f}, "
                f"seq_w_max={yolo_runtime['seq_max_w']:.2f}, "
                f"seq_soft={yolo_runtime['seq_soft_overlap']:.2f}, "
                f"seq_hard={yolo_runtime['seq_hard_overlap']:.2f}",
                "INFO"
            )
        except Exception as e:
            messagebox.showwarning(
                "Błąd modelu YOLO",
                f"Nie udało się przygotować modelu YOLO:\n{e}"
            )
            self._log(self.test_log_text, f"[ERROR] {e}", "ERROR")
            return

    self._run_fast_ocr_test(guard_options=guard_options)


def unlock_ui_after_testing(host):
    self = host
    # NAJWAŻNIEJSZE: kończymy stan "processing"
    self.is_processing = False
    self.fast_test_running = False
    active_owner = str(getattr(self, "_active_test_operation_owner", "") or "").strip()
    self._active_test_operation_owner = None
    if active_owner and hasattr(self.app, "end_exclusive_operation"):
        self.app.end_exclusive_operation(active_owner)

    try:
        self.fast_test_stop.clear()
    except Exception:
        pass

    # lista tablic ma znowu działać zawsze po zakończeniu testu
    try:
        self.plates_listbox.config(state=tk.NORMAL)
    except Exception:
        pass

    # przyciski operacyjne
    for attr_name in ("btn_run_detection", "btn_rank_presets", "btn_ocr_lab"):
        widget = getattr(self, attr_name, None)
        if widget is not None:
            try:
                widget.config(state=tk.NORMAL)
            except Exception:
                pass

    # odśwież blokady/odblokowania pól ścieżek zgodnie z aktualnym trybem
    try:
        self._update_preview_path_lock()
    except Exception:
        pass

    try:
        self._update_step3_source_path_lock()
    except Exception:
        pass

    try:
        self._update_yolo_visibility()
    except Exception:
        pass

    # różne zachowanie dla kampanii i trybu swobodnego
    in_campaign = bool(getattr(self, "_step3_linear_mode", False) and CAMPAIGN.get_active_project_name())

    if not in_campaign:
        # w trybie swobodnym wszystko ma działać
        for attr_name in ("btn_to_detect", "btn_to_dataset"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                try:
                    widget.config(state=tk.NORMAL)
                except Exception:
                    pass

        try:
            self._set_subtab_state(self.tab_extract, "normal")
            self._set_subtab_state(self.tab_detect, "normal")
            self._set_subtab_state(self.tab_dataset, "normal")
        except Exception:
            pass
    else:
        # w kampanii zostawiamy workflow tak, jak ustawiły go wcześniejsze kroki
        pass

    try:
        self.test_progress.update_idletasks()
    except Exception:
        pass


def run_fast_ocr_test(host, guard_options: dict | None = None):
    self = host
    all_plate_ids = self._get_sorted_preview_plate_ids(list(getattr(self, "preview_metadata", {}).keys()))
    if not all_plate_ids:
        return messagebox.showinfo("Brak", "Wczytaj katalog wyodrębnionych tablic.")

    if self.fast_test_running:
        return

    guard_options = dict(guard_options or {})
    full_plate_total = len(all_plate_ids)
    process_scope = str(guard_options.get("process_scope", "all") or "all").strip().lower()
    if process_scope == "perfect_only":
        metadata = self.preview_metadata if isinstance(getattr(self, "preview_metadata", None), dict) else {}
        scoped_plate_ids: list[str] = []
        for pid in all_plate_ids:
            data = metadata.get(pid)
            chars = data.get("characters", []) if isinstance(data, dict) else []
            if not isinstance(chars, list):
                chars = []
            try:
                is_perfect = self._is_existing_plate_perfect(chars, data=data)
            except Exception:
                is_perfect = False
            if is_perfect:
                scoped_plate_ids.append(pid)
        if not scoped_plate_ids:
            return messagebox.showinfo(
                "Brak tablic perfect",
                "W aktualnym katalogu PZ2 nie ma tablic ze statusem perfect do przetworzenia.",
            )
        all_plate_ids = scoped_plate_ids

    self._force_save_all()
    out_dir = Path(self.preview_dir_var.get().strip())
    imgs_dir = out_dir / "images"
    session_token = self._project_reset_token

    self.test_log_text.delete(1.0, tk.END)
    if not self._lock_ui_for_testing("pz2.fast_test.run", "PZ2: szybki test detekcji"):
        return
    self._set_test_status(self._compose_detection_method_status("start detekcji"), "info")
    self.test_progress.config(value=0)
    self._set_test_progress_counter(0, len(all_plate_ids), perfect_count=0)
    self._set_preview_processing_overlay(
        True,
        title="Trwa detekcja znaków",
        details="Ładuję modele OCR/YOLO i przygotowuję analizę tablic. Lista oraz podgląd są zablokowane do zakończenia procesu.",
        cancel_command=lambda: self.fast_test_stop.set(),
        cancel_visible=True,
        cancel_text="Anuluj",
    )
    self._update_preview_processing_overlay_progress(
        pct=0,
        current=0,
        total=len(all_plate_ids),
        meta_text="0% | przygotowanie detekcji",
    )
    try:
        self.preview_canvas_host.update_idletasks()
    except Exception:
        pass

    self.fast_test_stop.clear()
    self.fast_test_running = True

    self._log(self.test_log_text, "=======================================================", "HEADER")
    self._log(self.test_log_text, "START - Szybki Test Celności\n", "HEADER")

    method_key = self._get_detection_method_key()
    method_str = method_key.strip().lower()
    try:
        method = DetectionMethod(method_str)
    except Exception:
        method = DetectionMethod.OCR
        method_key = "OCR"
    detection_started_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        detection_pipeline_label = self._get_detection_pipeline_short_label(method_key)
    except Exception:
        detection_pipeline_label = self._get_detection_method_status_label()
    try:
        detection_method_label = self._get_detection_method_status_label()
    except Exception:
        detection_method_label = str(method_key or "OCR")

    protect_manual_requested = bool(guard_options.get("protect_manual_boxes", True))
    protect_manual_boxes = True
    protect_perfect_plates = bool(guard_options.get("protect_perfect_plates", True))
    use_perfect_box_refiner = bool(
        guard_options.get(
            "use_perfect_box_refiner",
            guard_options.get("allow_yolo_geometry_on_perfect", True),
        )
        and method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR]
    )
    use_perfect_refiner_continuity_guard = bool(
        use_perfect_box_refiner
        and guard_options.get("use_perfect_refiner_continuity_guard", True)
    )
    allow_yolo_geometry_on_perfect = use_perfect_box_refiner
    guard_counts = dict(guard_options.get("counts", {}) or {})
    scope_log_label = "tylko perfect" if process_scope == "perfect_only" else "wszystkie tablice"
    self._log(
        self.test_log_text,
        (
            "[OCHRONA] "
            f"manual={'ON' if protect_manual_boxes else 'OFF'}"
            f"{' (wymuszone)' if not protect_manual_requested else ''}, "
            f"perfect={'ON' if protect_perfect_plates else 'OFF'}, "
            f"refiner perfect={'ON' if use_perfect_box_refiner else 'OFF'}, "
            f"ciągłość={'ON' if use_perfect_refiner_continuity_guard else 'OFF'}; "
            f"zakres={scope_log_label} ({len(all_plate_ids)}/{full_plate_total}); "
            f"perfect={int(guard_counts.get('perfect', 0) or 0)}, "
            f"manualne={int(guard_counts.get('manual', 0) or 0)}"
        ),
        "INFO",
    )

    effective_device_choice = self._get_effective_detection_device_choice()
    effective_yolo_device = self._device_to_ultralytics(effective_device_choice)
    effective_ocr_device = self._device_to_ocr(effective_device_choice)
    try:
        import torch
        cuda_state = (
            f"CUDA dostępne={bool(torch.cuda.is_available())}, "
            f"liczba GPU={int(torch.cuda.device_count())}"
        )
    except Exception as e:
        cuda_state = f"CUDA niedostępne do sprawdzenia ({e})"

    self._log(
        self.test_log_text,
        (
            "[INFO] Urządzenie detekcji: "
            f"global={effective_device_choice} | "
            f"YOLO={effective_yolo_device} | OCR={effective_ocr_device} | "
            f"{cuda_state}"
        ),
        "INFO",
    )

    yolo_model = None
    YoloClass = get_yolo_class() if method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR] else None
    if method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR] and YoloClass is not None:
        try:
            effective_model_path = self._get_effective_yolo_model_path()
            if not effective_model_path:
                raise RuntimeError("Brak aktywnej ścieżki modelu YOLO dla detekcji znaków.")
            yolo_model = YoloClass(str(effective_model_path))
        except Exception as e:
            self._log(self.test_log_text, f"Błąd YOLO: {e}", "ERROR")
            yolo_model = None

    prep_params = self._get_current_prep_params()
    ocr_engine = None
    if method in [DetectionMethod.OCR, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR]:
        try:
            ocr_engine = PlateOCR(
                device=effective_ocr_device,
                confidence_threshold=self.ocr_conf_var.get()
            )
            ocr_engine.custom_prep_params = prep_params
        except Exception as e:
            self._log(self.test_log_text, f"Błąd OCR Engine: {e}", "ERROR")
            ocr_engine = None

    try:
        yolo_runtime = self._get_yolo_runtime_settings()
    except Exception as e:
        self._log(self.test_log_text, f"Błąd parametrów YOLO: {e}", "ERROR")
        yolo_runtime = {
            "conf": 0.25,
            "iou": 0.45,
            "overlap": 0.70,
            "agnostic_nms": False,
            "seq_center_y": 0.60,
            "seq_min_h": 0.55,
            "seq_max_h": 1.80,
            "seq_max_w": 2.60,
            "seq_soft_overlap": 0.18,
            "seq_hard_overlap": 0.30,
        }

    detector = CharacterDetector(
        method=method,
        ocr_engine=ocr_engine,
        yolo_model=yolo_model,
        yolo_device=effective_yolo_device,
        yolo_confidence=yolo_runtime["conf"],
        yolo_iou=yolo_runtime["iou"],
        yolo_agnostic_nms=yolo_runtime["agnostic_nms"],
        yolo_overlap_threshold=yolo_runtime["overlap"],
        yolo_sequence_center_y_tolerance=yolo_runtime["seq_center_y"],
        yolo_sequence_min_height_ratio=yolo_runtime["seq_min_h"],
        yolo_sequence_max_height_ratio=yolo_runtime["seq_max_h"],
        yolo_sequence_max_width_ratio=yolo_runtime["seq_max_w"],
        yolo_sequence_soft_overlap=yolo_runtime["seq_soft_overlap"],
        yolo_sequence_hard_overlap=yolo_runtime["seq_hard_overlap"],
        ocr_min_height_ratio=self.ocr_min_height_ratio_var.get(),
    )

    def worker():
        local_meta = dict(self.preview_metadata) if isinstance(self.preview_metadata, dict) else {}
        total = len(all_plate_ids)
        stat_perfect = 0
        acc = 0.0
        processed_plate_ids: set[str] = set()
        detection_summary: dict = {}
        yolo_raw_total = 0
        yolo_nms_total = 0
        yolo_filtered_total = 0
        zero_backend_count = 0
        skipped_perfect_count = 0
        refined_perfect_count = 0
        perfect_refiner_box_total = 0
        perfect_refiner_failed_total = 0
        perfect_overwrite_count = 0
        manual_preserved_box_total = 0
        manual_skipped_auto_total = 0
        manual_overwrite_plate_count = 0
        yolo_runtime_device_logged = False
        try:
            detection_model_path = str(self.yolo_model_path_var.get() or "")
        except Exception:
            detection_model_path = ""

        def _mark_plate_detection(pid_value, *, result: str, characters: int = 0, status: str = "", extra: dict | None = None) -> None:
            pid_key = str(pid_value)
            if pid_key not in local_meta or not isinstance(local_meta.get(pid_key), dict):
                local_meta[pid_key] = {}
            payload = {
                "started_at": detection_started_iso,
                "method": str(method_key or "OCR"),
                "method_label": detection_method_label,
                "pipeline": detection_pipeline_label,
                "device": str(effective_device_choice or ""),
                "yolo_device": str(effective_yolo_device or ""),
                "ocr_device": str(effective_ocr_device or ""),
                "model": detection_model_path if method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR] else "",
                "characters": int(characters or 0),
                "status": str(status or ""),
                "result": str(result or ""),
            }
            if isinstance(extra, dict):
                payload.update(extra)
            local_meta[pid_key]["last_detection"] = payload
            processed_plate_ids.add(pid_key)

        try:
            for idx, pid in enumerate(all_plate_ids):
                if self.fast_test_stop.is_set() or session_token != self._project_reset_token:
                    break

                if pid not in local_meta or not isinstance(local_meta.get(pid), dict):
                    local_meta[pid] = {}

                existing_chars = list(local_meta[pid].get("characters", [])) if isinstance(local_meta[pid].get("characters"), list) else []
                existing_is_perfect = self._is_existing_plate_perfect(
                    existing_chars,
                    data=local_meta.get(pid),
                )
                existing_has_manual = any(
                    isinstance(rec, dict) and self._is_manual_character_record(rec, data=local_meta.get(pid))
                    for rec in list(existing_chars or [])
                )

                if (
                    existing_is_perfect
                    and protect_perfect_plates
                    and not allow_yolo_geometry_on_perfect
                ):
                    sorted_existing = self._sort_character_records_by_x(existing_chars)
                    sorted_existing = self._annotate_preview_character_reading_positions(
                        sorted_existing,
                        data=local_meta[pid],
                    )
                    local_meta[pid]["characters"] = self._serialize_character_records(
                        sorted_existing,
                        fusion_strategy=str(local_meta[pid].get("fusion_strategy", "") or ""),
                        fusion_details=local_meta[pid].get("fusion_details", {}) if isinstance(local_meta[pid].get("fusion_details"), dict) else None,
                    )
                    local_meta[pid]["characters"] = self._annotate_preview_character_reading_positions(
                        local_meta[pid]["characters"],
                        data=local_meta[pid],
                    )
                    local_meta[pid]["status"] = "perfect"
                    self._update_preview_plate_layout_metadata(local_meta[pid], sorted_existing)
                    _mark_plate_detection(
                        pid,
                        result="pominięta przez ochronę perfect",
                        characters=len(local_meta[pid].get("characters", []) or []),
                        status="perfect",
                    )
                    skipped_perfect_count += 1
                    stat_perfect += 1
                    self._log(
                        self.test_log_text,
                        f"[OCHRONA] {pid}: pominięto detekcję, tablica ma status perfect.",
                        "INFO"
                    )
                    self.frame.after(
                        0,
                        lambda c=idx + 1, t=total, p=stat_perfect, token=session_token: self._update_detection_progress_ui(c, t, perfect_count=p, session_token=token)
                    )
                    continue

                img_path = imgs_dir / f"{pid}.jpg"
                if not img_path.exists():
                    _mark_plate_detection(
                        pid,
                        result="brak pliku obrazu",
                        characters=0,
                        status=str(local_meta[pid].get("status", "") or ""),
                    )
                    self.frame.after(
                        0,
                        lambda c=idx + 1, t=total, p=stat_perfect, token=session_token: self._update_detection_progress_ui(c, t, perfect_count=p, session_token=token)
                    )
                    continue

                img = cv2.imread(str(img_path))
                if img is None:
                    _mark_plate_detection(
                        pid,
                        result="błąd odczytu obrazu",
                        characters=0,
                        status=str(local_meta[pid].get("status", "") or ""),
                    )
                    self.frame.after(
                        0,
                        lambda c=idx + 1, t=total, p=stat_perfect, token=session_token: self._update_detection_progress_ui(c, t, perfect_count=p, session_token=token)
                    )
                    continue

                source_image = local_meta[pid].get("source_image", "") or ""
                true_texts = self._get_true_texts_from_filename(source_image)

                chars = detector.detect(img)
                if (
                    not yolo_runtime_device_logged
                    and method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR]
                ):
                    yolo_runtime_device_logged = True
                    runtime_device = str(getattr(detector, "last_yolo_runtime_device", "") or "brak wyniku YOLO")
                    requested_device = getattr(detector, "last_yolo_requested_device", effective_yolo_device)
                    self._log(
                        self.test_log_text,
                        (
                            "[INFO] Runtime YOLO: "
                            f"żądane device={requested_device}, "
                            f"tensor wynikowy={runtime_device}"
                        ),
                        "INFO",
                    )
                if session_token != self._project_reset_token:
                    break

                ocr_chars = self._sort_character_records_by_x(list(getattr(detector, "last_ocr_detections", [])))
                yolo_nms_chars = self._sort_character_records_by_x(list(getattr(detector, "last_yolo_nms_detections", [])))
                yolo_raw_chars = self._sort_character_records_by_x(list(getattr(detector, "last_yolo_raw_detections", [])))
                if method == DetectionMethod.YOLO_OCR:
                    yolo_chars = yolo_nms_chars
                else:
                    yolo_chars = self._sort_character_records_by_x(list(getattr(detector, "last_yolo_detections", [])))
                yolo_box_backend_chars = yolo_nms_chars or yolo_chars or yolo_raw_chars
                chars, fusion_strategy, fusion_details = self._resolve_canonical_detections(
                    method,
                    chars,
                    ocr_chars,
                    yolo_chars,
                    true_texts,
                    hybrid_rescue_max_chars=self._get_hybrid_rescue_max_chars(),
                    prefer_yolo_box_positions=(method == DetectionMethod.BOTH and self._use_hybrid_yolo_box_backend()),
                    yolo_box_backend_detections=yolo_box_backend_chars,
                    plate_image=img,
                )

                c_clean = self._serialize_character_records(
                    chars,
                    fusion_strategy=fusion_strategy,
                    fusion_details=fusion_details,
                )
                yolo_clean = self._serialize_character_records(getattr(detector, "last_yolo_detections", []))
                yolo_nms_clean = self._serialize_character_records(getattr(detector, "last_yolo_nms_detections", []))
                yolo_raw_clean = self._serialize_character_records(getattr(detector, "last_yolo_raw_detections", []))

                yolo_raw_total += len(getattr(detector, "last_yolo_raw_detections", []))
                yolo_nms_total += len(getattr(detector, "last_yolo_nms_detections", []))
                yolo_filtered_total += len(getattr(detector, "last_yolo_detections", []))

                if (
                    not ocr_chars
                    and not yolo_chars
                    and not list(getattr(detector, "last_yolo_raw_detections", []) or [])
                ):
                    zero_backend_count += 1

                preserve_perfect_existing = bool(existing_is_perfect and protect_perfect_plates)

                if preserve_perfect_existing:
                    preserved_chars, preserve_details = self._preserve_existing_perfect_plate_during_detection(
                        existing_chars,
                        yolo_box_backend_chars,
                        data=local_meta.get(pid),
                        plate_image=img,
                        enable_perfect_refiner=use_perfect_box_refiner,
                        perfect_refiner_continuity_guard=use_perfect_refiner_continuity_guard,
                    )
                    refiner_box_count = 0
                    refiner_failed_count = 0
                    if isinstance(preserve_details, dict):
                        refiner_box_count = int(preserve_details.get("perfect_refiner_count", 0) or 0)
                        refiner_failed_count = int(preserve_details.get("perfect_refiner_failed_count", 0) or 0)
                    perfect_refiner_box_total += int(refiner_box_count)
                    perfect_refiner_failed_total += int(refiner_failed_count)
                    if refiner_box_count > 0:
                        refined_perfect_count += 1
                    existing_fusion_details = local_meta[pid].get("fusion_details", {})
                    preserved_details = dict(existing_fusion_details) if isinstance(existing_fusion_details, dict) else {}
                    preserved_details["auto_strategy"] = str(fusion_strategy or "")
                    preserved_details["source"] = "pz2_detect_preserve_perfect"
                    preserved_details["locked_perfect_box_count"] = int(len(existing_chars))
                    ignored_extra_boxes = max(0, int(len(c_clean)) - int(len(existing_chars)))
                    if ignored_extra_boxes > 0:
                        preserved_details["auto_ignored_extra_boxes"] = int(ignored_extra_boxes)
                    if isinstance(preserve_details, dict) and preserve_details:
                        preserved_details.update(preserve_details)

                    merge_info = {
                        "manual_preserved_count": int(
                            preserve_details.get("manual_protected_count", 0) if isinstance(preserve_details, dict) else 0
                        ),
                        "auto_appended_count": 0,
                        "auto_skipped_due_manual": 0,
                        "perfect_preserved_count": int(len(existing_chars)),
                        "auto_ignored_extra_boxes": int(ignored_extra_boxes),
                    }
                    final_chars = preserved_chars
                    final_strategy = str(local_meta[pid].get("fusion_strategy", "") or fusion_strategy or "")
                    fusion_details = preserved_details
                else:
                    if existing_is_perfect and not protect_perfect_plates:
                        perfect_overwrite_count += 1

                    if protect_manual_boxes:
                        merged_chars, merge_info = self._merge_detected_characters_preserving_manual(
                            existing_chars,
                            c_clean,
                            data=local_meta.get(pid),
                        )
                    else:
                        if existing_has_manual:
                            manual_overwrite_plate_count += 1
                        merged_chars = c_clean
                        merge_info = {
                            "manual_preserved_count": 0,
                            "auto_appended_count": int(len(c_clean)),
                            "auto_skipped_due_manual": 0,
                        }

                    if int(merge_info.get("manual_preserved_count", 0) or 0) > 0:
                        manual_preserved_box_total += int(merge_info.get("manual_preserved_count", 0) or 0)
                        manual_skipped_auto_total += int(merge_info.get("auto_skipped_due_manual", 0) or 0)
                        fusion_details = dict(fusion_details or {})
                        fusion_details["auto_strategy"] = str(fusion_strategy or "")
                        fusion_details["manual_preserved_count"] = int(merge_info.get("manual_preserved_count", 0) or 0)
                        fusion_details["auto_appended_count"] = int(merge_info.get("auto_appended_count", 0) or 0)
                        fusion_details["auto_skipped_due_manual"] = int(merge_info.get("auto_skipped_due_manual", 0) or 0)
                        fusion_details["source"] = "pz2_detect_merge"
                        final_chars = merged_chars
                        final_strategy = "manual_correction"
                    else:
                        final_chars = c_clean
                        final_strategy = str(fusion_strategy or "")

                # Ostateczny guard GT musi działać już po merge/preserve,
                # żeby stare manuale albo perfect-preserve nie przywracały
                # nadmiarowych boxów do finalnego metadata.
                final_chars, fusion_details = self._apply_final_truth_count_guard(
                    final_chars,
                    true_texts,
                    fusion_details if isinstance(fusion_details, dict) else None,
                )

                # WAŻNE: znaki trafiają do metadata w kolejności czytania.

                self._update_preview_plate_layout_metadata(local_meta[pid], final_chars)
                final_chars = self._annotate_preview_character_reading_positions(final_chars, data=local_meta[pid])
                local_meta[pid]["characters"] = final_chars
                local_meta[pid]["yolo_detections"] = yolo_clean
                local_meta[pid]["yolo_nms_detections"] = yolo_nms_clean
                local_meta[pid]["yolo_raw_detections"] = yolo_raw_clean
                local_meta[pid]["fusion_strategy"] = str(final_strategy or "")
                if isinstance(fusion_details, dict) and fusion_details:
                    local_meta[pid]["fusion_details"] = fusion_details
                else:
                    local_meta[pid].pop("fusion_details", None)

                if fusion_strategy == "yolo_exact":
                    self._log(
                        self.test_log_text,
                        f"[HYBRID] {pid}: YOLO trafiło idealnie i przejęło finalne boxy.",
                        "INFO"
                    )
                elif fusion_strategy == "yolo_box_ocr":
                    final_text = self._characters_to_text(c_clean)
                    self._log(
                        self.test_log_text,
                        f"[HYBRID] {pid}: YOLO wyznaczyło boxy, a OCR odczytał cropy -> [{final_text}]",
                        "INFO"
                    )
                elif fusion_strategy == "ocr_yolo_rescue":
                    repaired_text = self._characters_to_text(c_clean)
                    ocr_text = ""
                    if isinstance(fusion_details, dict):
                        ocr_text = str(fusion_details.get("ocr_text", "") or "")
                    self._log(
                        self.test_log_text,
                        f"[HYBRID] {pid}: OCR=[{ocr_text}] -> naprawa YOLO -> [{repaired_text}]",
                        "INFO"
                    )

                if isinstance(fusion_details, dict) and int(fusion_details.get("box_backend_count", 0) or 0) > 0:
                    self._log(
                        self.test_log_text,
                        f"[HYBRID] {pid}: YOLO poprawiło pozycje {int(fusion_details.get('box_backend_count', 0))} boxów.",
                        "INFO"
                    )

                if isinstance(fusion_details, dict) and int(fusion_details.get("trimmed_extra_boxes", 0) or 0) > 0:
                    trim_stage = str(fusion_details.get("gt_count_guard_stage", "") or "").strip().lower()
                    stage_suffix = " po merge" if trim_stage == "final_characters" else ""
                    self._log(
                        self.test_log_text,
                        f"[GT] {pid}: przycięto nadmiarowe boxy do długości GT "
                        f"{stage_suffix}"
                        f"({int(fusion_details.get('original_box_count', 0) or 0)} -> "
                        f"{int(fusion_details.get('trimmed_box_count', 0) or 0)}).",
                        "INFO"
                    )

                if int(merge_info.get("manual_preserved_count", 0) or 0) > 0:
                    self._log(
                        self.test_log_text,
                        f"[MERGE] {pid}: zachowano ręczne boxy znaków={int(merge_info.get('manual_preserved_count', 0) or 0)}, "
                        f"dodano auto={int(merge_info.get('auto_appended_count', 0) or 0)}, "
                        f"pominięto auto przez kolizję z manual={int(merge_info.get('auto_skipped_due_manual', 0) or 0)}.",
                        "INFO"
                    )
                elif preserve_perfect_existing:
                    backend_count = 0
                    backend_ref_count = 0
                    if isinstance(fusion_details, dict):
                        backend_count = int(fusion_details.get("box_backend_count", 0) or 0)
                        backend_ref_count = int(fusion_details.get("box_backend_reference_count", 0) or 0)
                        manual_protected_count = int(fusion_details.get("manual_protected_count", 0) or 0)
                    else:
                        manual_protected_count = 0
                    preserve_message = (
                        f"[MERGE] {pid}: zachowano status perfect i liczbę boxów={int(len(existing_chars))}. "
                    )
                    if backend_count > 0:
                        refiner_count = int(fusion_details.get("perfect_refiner_count", 0) or 0) if isinstance(fusion_details, dict) else 0
                        if refiner_count > 0:
                            preserve_message += (
                                f"Refiner poprawił geometrię {refiner_count} boxów "
                                f"(kandydaci po NMS={backend_ref_count}). "
                            )
                        else:
                            preserve_message += (
                                f"YOLO dopasowało geometrię {backend_count} boxów "
                                f"(kandydaci po NMS={backend_ref_count}). "
                            )
                    else:
                        preserve_message += (
                            f"YOLO nie zmieniło geometrii perfecta "
                            f"(kandydaci po NMS={backend_ref_count}). "
                        )
                    if manual_protected_count > 0:
                        preserve_message += f"Manualne boxy nietknięte={manual_protected_count}. "
                    preserve_message += f"Zignorowano nowe boxy={int(merge_info.get('auto_ignored_extra_boxes', 0) or 0)}."
                    self._log(
                        self.test_log_text,
                        preserve_message,
                        "INFO"
                    )

                if final_chars:
                    txt = "".join(str(c.get("character", "")) for c in final_chars)
                    status_probe = dict(local_meta[pid])
                    status_probe["plate_id"] = str(pid)
                    derived_status = self._derive_preview_status_from_data(status_probe, final_chars)
                    local_meta[pid]["status"] = derived_status
                    if derived_status == "perfect":
                        stat_perfect += 1
                        self._log(self.test_log_text, f"✅ [{idx+1:03d}/{total}] {pid}: {txt}", "SUCCESS")
                    else:
                        expected_texts = self._get_preview_expected_texts(status_probe)
                        expected_str = " / ".join(expected_texts) if expected_texts else "Brak"
                        self._log(
                            self.test_log_text,
                            f"❌ [{idx+1:03d}/{total}] {pid}: Odczyt=[{txt}] (Oczek: [{expected_str}])",
                            "ERROR"
                        )
                else:
                    local_meta[pid]["status"] = "needs_fix"
                    if str(final_strategy or "").strip().lower() == "no_detection":
                        self._log(
                            self.test_log_text,
                            f"❌ [{idx+1:03d}/{total}] {pid}: BRAK KANDYDATÓW (OCR=0, YOLO=0)",
                            "ERROR"
                        )
                    else:
                        self._log(
                            self.test_log_text,
                            f"❌ [{idx+1:03d}/{total}] {pid}: NIC NIE ZNALEZIONO",
                            "ERROR"
                        )

                _mark_plate_detection(
                    pid,
                    result=str(local_meta[pid].get("status", "") or "needs_fix"),
                    characters=len(final_chars or []),
                    status=str(local_meta[pid].get("status", "") or ""),
                    extra={"fusion_strategy": str(final_strategy or "")},
                )

                self._ensure_plate_source_metadata(
                    local_meta[pid],
                    plate_id=str(pid),
                    meta_path=Path(out_dir) / "metadata.json",
                    default_bucket="auto_preview",
                    default_origin="pz2_detect",
                    modified_by="system",
                )

                self.frame.after(
                    0,
                    lambda c=idx + 1, t=total, p=stat_perfect, token=session_token: self._update_detection_progress_ui(c, t, perfect_count=p, session_token=token)
                )

            if session_token != self._project_reset_token:
                return

            finished_iso = datetime.now().astimezone().isoformat(timespec="seconds")
            for detected_pid in processed_plate_ids:
                plate_data = local_meta.get(str(detected_pid))
                if isinstance(plate_data, dict) and isinstance(plate_data.get("last_detection"), dict):
                    plate_data["last_detection"]["finished_at"] = finished_iso
            plates_with_chars = sum(
                1 for pid in all_plate_ids
                if isinstance(local_meta.get(pid), dict) and local_meta[pid].get("characters")
            )
            char_total = sum(
                len(local_meta[pid].get("characters") or [])
                for pid in all_plate_ids
                if isinstance(local_meta.get(pid), dict) and isinstance(local_meta[pid].get("characters"), list)
            )
            detection_summary = {
                "started_at": detection_started_iso,
                "finished_at": finished_iso,
                "method": str(method_key or "OCR"),
                "method_label": detection_method_label,
                "pipeline": detection_pipeline_label,
                "plate_scope": str(process_scope or "all"),
                "source_plates": int(full_plate_total),
                "scope_plates": int(total),
                "plates": int(total),
                "processed_plates": int(len(processed_plate_ids)),
                "plates_with_chars": int(plates_with_chars),
                "characters": int(char_total),
                "perfect": int(stat_perfect),
                "device": str(effective_device_choice or ""),
                "yolo_device": str(effective_yolo_device or ""),
                "ocr_device": str(effective_ocr_device or ""),
                "model": detection_model_path if method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR] else "",
                "yolo_raw": int(yolo_raw_total),
                "yolo_nms": int(yolo_nms_total),
                "yolo_filtered": int(yolo_filtered_total),
            }

            meta_file = out_dir / "metadata.json"
            self._atomic_write_json(meta_file, local_meta)
            self._save_last_detection_summary(detection_summary, out_dir)

            self._log(
                self.test_log_text,
                f"\n[DIAG] Tablice z wykrytymi znakami: {plates_with_chars}/{total}",
                "INFO"
            )
            self._log(
                self.test_log_text,
                f"[DIAG] Tablice bez jakichkolwiek kandydatów OCR/YOLO: {int(zero_backend_count)}/{total}",
                "INFO"
            )

            if method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR]:
                self._log(
                    self.test_log_text,
                    f"[DIAG] YOLO boxy: raw={yolo_raw_total}, po NMS={yolo_nms_total}, po filtracji={yolo_filtered_total}",
                    "INFO"
                )

            strategy_counts = self._count_statuses_in_metadata_mapping(local_meta).get("strategy_counts", {})
            self._log(
                self.test_log_text,
                "[DIAG] Tablice perfect wg strategii: "
                f"OCR={int(strategy_counts.get('ocr_exact', 0))}, "
                f"YOLO={int(strategy_counts.get('yolo_exact', 0))}, "
                f"rescue={int(strategy_counts.get('ocr_yolo_rescue', 0))}, "
                f"yolo_box_ocr={int(strategy_counts.get('yolo_box_ocr', 0))}, "
                f"inne={int(strategy_counts.get('other_perfect', 0))}",
                "INFO"
            )
            try:
                flag_counts = {"M": 0, "O": 0, "YB": 0, "YS": 0}
                combo_counts = {}
                for plate_data in (local_meta or {}).values():
                    flags = list(self._get_plate_listbox_source_flags(plate_data))
                    if not flags:
                        continue
                    combo_key = "|".join(flags)
                    combo_counts[combo_key] = int(combo_counts.get(combo_key, 0) or 0) + 1
                    for flag in flags:
                        if flag in flag_counts:
                            flag_counts[flag] += 1
                combo_line = ", ".join(
                    f"{key}={value}"
                    for key, value in sorted(combo_counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
                ) or "brak"
                self._log(
                    self.test_log_text,
                    (
                        "[DIAG] Znaczniki listy po detekcji: "
                        f"M={flag_counts['M']}, O={flag_counts['O']}, "
                        f"YB={flag_counts['YB']}, YS={flag_counts['YS']} | "
                        f"kombinacje: {combo_line}"
                    ),
                    "INFO",
                )
                if (
                    method in [DetectionMethod.YOLO, DetectionMethod.BOTH, DetectionMethod.YOLO_OCR]
                    and (yolo_raw_total > 0 or yolo_nms_total > 0 or yolo_filtered_total > 0)
                    and int(flag_counts.get("YB", 0) or 0) <= 0
                    and int(flag_counts.get("YS", 0) or 0) <= 0
                ):
                    self._log(
                        self.test_log_text,
                        (
                            "[WARNING] YOLO zwróciło kandydatów, ale finalne etykiety listy "
                            "nie mają YB/YS. Sprawdź ochronę perfectów oraz wybrany układ pipeline."
                        ),
                        "WARNING",
                    )
            except Exception as flag_err:
                logger.debug(f"Nie udało się policzyć znaczników PZ2 po detekcji: {flag_err}")
            self._log(
                self.test_log_text,
                "[DIAG] Ochrona detekcji: "
                f"perfect pominięte={int(skipped_perfect_count)}, "
                f"perfect z refinerem={int(refined_perfect_count)}, "
                f"boxy poprawione refinerem={int(perfect_refiner_box_total)}, "
                f"próby odrzucone refinerem={int(perfect_refiner_failed_total)}, "
                f"perfect nadpisane={int(perfect_overwrite_count)}, "
                f"manualne boxy zachowane={int(manual_preserved_box_total)}, "
                f"auto pominięte przez manual={int(manual_skipped_auto_total)}, "
                f"tablice z manualem nadpisywane={int(manual_overwrite_plate_count)}",
                "INFO"
            )

            acc = (stat_perfect / total * 100) if total > 0 else 0
            self._log(
                self.test_log_text,
                f"\nSkuteczność: {acc:.1f}% ({stat_perfect}/{total} tablic)",
                "SUCCESS" if acc >= 80 else "WARNING"
            )

        except Exception as e:
            self._log(self.test_log_text, f"\n❌ BŁĄD: {e}", "ERROR")

        finally:
            try:
                if ocr_engine is not None:
                    try:
                        ocr_engine.unload()
                    except Exception:
                        pass
                detector.ocr_engine = None
            except Exception:
                pass
            try:
                detector.yolo_model = None
            except Exception:
                pass
            try:
                yolo_model = None
            except Exception:
                pass
            try:
                cleanup_gpu_memory()
            except Exception as cleanup_err:
                logger.debug(f"Nie udało się zwolnić GPU po PZ2: {cleanup_err}")

            def finalize():
                if session_token != self._project_reset_token:
                    return

                try:
                    self.fast_test_running = False
                    self.fast_test_stop.clear()

                    # Lista musi być aktywna przed przebudowa, inaczej repaint potrafi opoznic się
                    # do chwili kolejnej interakcji myszą lub klawiaturą.
                    try:
                        self.plates_listbox.config(state=tk.NORMAL)
                    except Exception:
                        pass

                    # Odśwież listę i preview na podstawie aktualnego metadata.
                    self._apply_preview_metadata_update(local_meta, preserve_selection=True)
                    self._loaded_meta_path = out_dir / "metadata.json"
                    try:
                        self._loaded_meta_mtime = self._loaded_meta_path.stat().st_mtime
                    except Exception:
                        self._loaded_meta_mtime = None

                    try:
                        method_name = self._get_detection_method_key()

                        if method_name == "OCR":
                            self._set_winner_name("Brak zwycięzcy turnieju", "neutral")
                            self._set_winner_acc("Uruchom turniej presetów OCR", "muted")
                        elif method_name == "YOLO":
                            self._set_winner_name("Brak rankingu OCR", "neutral")
                            self._set_winner_acc("Tryb YOLO nie bierze udziału w turnieju OCR", "muted")
                        elif method_name == "YOLO_OCR":
                            self._set_winner_name("Brak rankingu OCR", "neutral")
                            self._set_winner_acc("Tryb YOLO boxy + OCR nie ustala zwycięzcy turnieju OCR", "muted")
                        else:  # BOTH
                            self._set_winner_name("Brak rankingu OCR", "neutral")
                            self._set_winner_acc("Tryb hybrydowy nie ustala zwycięzcy turnieju OCR", "muted")
                    except Exception:
                        pass

                    try:
                        summary_msg = (
                            f"Podsumowanie detekcji: perfect={stat_perfect}/{total}, "
                            f"skuteczność={acc:.1f}%"
                        )
                        self._log(self.test_log_text, summary_msg, "INFO")
                    except Exception:
                        pass

                    self.test_progress.config(value=100)
                    self._set_test_progress_counter(total, total, perfect_count=stat_perfect)
                    self._update_preview_processing_overlay_progress(
                        pct=100,
                        current=total,
                        total=total,
                        meta_text=f"100% | OK {int(stat_perfect)}/{int(total)} tablic",
                    )
                    self._set_test_status(
                        self._compose_detection_method_status(
                            f"zakończona | skuteczność {acc:.1f}%"
                        ),
                        "success"
                    )
                    try:
                        self._refresh_last_detection_status_label(detection_summary)
                    except Exception:
                        pass

                    try:
                        self.frame.update_idletasks()
                    except Exception:
                        pass

                    # 7. odblokuj dalszy krok
                    self.unlock_dataset_subtab()

                except Exception as e:
                    logger.error(f"Błąd finalize() po Szybkim Teście: {e}")
                    self._set_test_status(
                        self._compose_detection_method_status("błąd odświeżania UI"),
                        "error"
                    )

                finally:
                    self._set_preview_processing_overlay(False)
                    self._unlock_ui_after_testing()

            self.frame.after(0, finalize)

    threading.Thread(target=worker, daemon=True).start()


