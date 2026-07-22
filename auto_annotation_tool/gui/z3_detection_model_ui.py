from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from ..campaign_manager import CAMPAIGN
from ..config import CONFIG, logger


def get_detection_active_model_status(host) -> tuple[str, str]:
    method_key = host._get_detection_method_key()
    uses_yolo = method_key in ("YOLO", "BOTH", "YOLO_OCR")
    model_path = str(host._get_effective_yolo_model_path() or "").strip()
    path_locked = bool(getattr(host, "_step3_linear_mode", False))

    if model_path and Path(model_path).exists():
        model_name = Path(model_path).name
        version, size = host._infer_yolo_arch_from_model_path(model_path)
        if version and size:
            model_name = f"{model_name} (YOLOv{version}{size})"

        source_suffix = " z projektu" if path_locked else ""
        if uses_yolo:
            return (
                f"Model detekcji znaków w PZ2: {model_name}{source_suffix}. "
                "Służy tylko do inferencji: wykrywa/proponuje ramki i klasy znaków. "
                "Nie jest wyborem modelu do treningu.",
                "neutral",
            )
        return (
            f"Model detekcji znaków gotowy: {model_name}{source_suffix}. "
            "Aktualny pipeline OCR go nie używa; wybór nie zmienia modelu treningowego.",
            "muted",
        )

    if uses_yolo:
        return (
            "Brak modelu detekcji znaków dla PZ2. Wybierz wytrenowany .pt tylko wtedy, "
            "gdy pipeline ma korzystać z YOLO; trening wybierasz w karcie treningu.",
            "warning",
        )
    if path_locked:
        return "Model detekcji znaków jest sterowany przez projekt i nieużywany w trybie OCR.", "muted"
    return "Model detekcji znaków nie jest używany w trybie OCR.", "muted"


def has_configured_yolo_detection_model(host) -> bool:
    try:
        host._sync_yolo_model_binding()
    except Exception:
        pass

    model_path = str(host._get_effective_yolo_model_path() or "").strip()
    if not model_path:
        return False
    try:
        return Path(model_path).exists()
    except Exception:
        return False


def get_campaign_char_model_path(host) -> str:
    try:
        before_iteration = int(CAMPAIGN.get_current_iteration_num() or 1)
    except Exception:
        before_iteration = None
    try:
        model_info = dict(
            CAMPAIGN.get_effective_project_model(
                "char",
                before_iteration=before_iteration,
            )
            or {}
        )
        model_path = str(model_info.get("path") or "").strip()
        if model_path and Path(model_path).exists():
            return str(Path(model_path))
    except Exception:
        pass
    return ""


def get_effective_yolo_model_path(host) -> str:
    if getattr(host, "_step3_linear_mode", False):
        return host._get_campaign_char_model_path()

    raw = (host.yolo_model_path_var.get() or "").strip()
    if raw and raw != "Brak modelu znaków w projekcie" and Path(raw).exists():
        return raw
    return ""


def sync_yolo_model_binding(host) -> None:
    if getattr(host, "_step3_linear_mode", False):
        project_model = host._get_campaign_char_model_path()
        if project_model:
            host.yolo_model_path_var.set(project_model)
        else:
            host.yolo_model_path_var.set("Brak modelu znaków w projekcie")
    else:
        if (host.yolo_model_path_var.get() or "").strip() == "Brak modelu znaków w projekcie":
            host.yolo_model_path_var.set("")


def infer_yolo_arch_from_model_path(model_path: str):
    raw = (model_path or "").strip().lower()
    if not raw:
        return None, None

    name = Path(raw).name.lower()
    match = re.search(r"yolo(8|11|26)([nsmlx])", name)
    if not match:
        return None, None

    version = match.group(1)
    size = match.group(2)
    return version, size


def auto_device_label() -> str:
    return "auto (prefer GPU/CUDA, fallback CPU)"


def get_available_devices(host):
    devices = [host._auto_device_label(), "cpu"]
    if not bool(getattr(host, "_startup_ui_ready", False)):
        return devices
    try:
        import torch

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                name = torch.cuda.get_device_name(i)
                devices.append(f"cuda:{i} ({name})")
    except Exception:
        pass
    return devices


def normalize_selected_device(host, raw_value: str | None = None, devices=None) -> str:
    available = list(devices or [])
    current = str(raw_value if raw_value is not None else host.yolo_device_var.get() or "").strip()
    current_lower = current.lower()

    if not current or current_lower.startswith("auto"):
        return available[0] if available else host._auto_device_label()
    if current_lower.startswith("cpu"):
        return "cpu"
    if current_lower.startswith("cuda:"):
        prefix = current.split()[0]
        for option in available:
            if option.startswith(prefix):
                return option
        return prefix

    return current if (not available or current in available) else (available[0] if available else host._auto_device_label())


def get_effective_detection_device_choice(host) -> str:
    raw_choice = None
    try:
        app_device_getter = getattr(host.app, "get_global_yolo_device_choice", None)
        if callable(app_device_getter):
            raw_choice = app_device_getter()
    except Exception:
        raw_choice = None

    normalized = host._normalize_selected_device(raw_value=raw_choice or host.yolo_device_var.get())
    try:
        if normalized and host.yolo_device_var.get() != normalized:
            host.yolo_device_var.set(normalized)
    except Exception:
        pass
    return normalized


def refresh_device_options(host) -> None:
    devices = host._get_available_devices()
    if hasattr(host, "det_device_combo"):
        try:
            host.det_device_combo.configure(values=devices)
        except Exception:
            pass

    normalized = host._normalize_selected_device(devices=devices)
    if normalized:
        host.yolo_device_var.set(normalized)

    host._update_device_hint()


def device_to_ultralytics(host, s: str):
    raw = str(s or "").strip().lower()
    if not raw or raw.startswith("auto"):
        try:
            import torch

            if torch.cuda.is_available():
                return 0
        except Exception:
            pass
        return "cpu"
    if raw.startswith("cpu"):
        return "cpu"
    if raw.startswith("cuda:"):
        try:
            return int(str(s).split(":")[1].split()[0])
        except Exception:
            return 0
    return "cpu"


def device_to_ocr(host, s: str) -> str:
    return "cuda" if host._device_to_ultralytics(s) != "cpu" else "cpu"


def update_device_hint(host, event=None) -> None:
    label = getattr(host, "det_device_hint_lbl", None)
    if label is None:
        return

    devices = host._get_available_devices()
    normalized = host._normalize_selected_device(devices=devices)
    current = str(host.yolo_device_var.get() or "").strip()
    if normalized != current:
        host.yolo_device_var.set(normalized)
        current = normalized

    gpu_devices = [item for item in devices if item.startswith("cuda:")]
    current_lower = current.lower()

    if current_lower.startswith("auto"):
        if gpu_devices:
            text = f"Auto najpierw spróbuje akceleracji na {gpu_devices[0]}. Gdy GPU/CUDA nie będzie dostępne, system spadnie do CPU."
            tone = "info"
        else:
            text = "Auto nie wykryło karty CUDA, więc zostanie użyty CPU."
            tone = "warning"
    elif current_lower.startswith("cpu"):
        text = "CPU wymusza pracę bez akceleracji GPU. To wolniejsze, ale przewidywalne."
        tone = "muted"
    else:
        text = f"Wybrana karta: {current}. YOLO i OCR spróbują użyć tej akceleracji."
        tone = "success"

    host._set_themed_label_state(label, text=text, tone=tone)


def apply_global_yolo_device_choice(host, value: str) -> None:
    normalized = host._normalize_selected_device(raw_value=value)
    try:
        host.yolo_device_var.set(normalized)
    except Exception:
        pass
    try:
        host._update_device_hint()
    except Exception:
        pass


def set_button_emphasis(host, frame_attr: str, enabled: bool, color: str = "#f39c12") -> None:
    btn = host._resolve_guidance_button(frame_attr)
    if btn is None:
        return

    try:
        host.app.set_button_emphasis(btn, enabled)
    except Exception as exc:
        logger.debug(f"Nie udało się ustawić podświetlenia przycisku dla {frame_attr}: {exc}")


def ensure_yolo_model_checkpoint(host) -> str:
    """
    Zwraca ścieżkę do wytrenowanego checkpointu YOLO znaków.
    Z3/PZ2 nie korzysta z niewytrenowanych wariantów architektury.
    """
    effective_model = host._get_effective_yolo_model_path()
    if effective_model and Path(effective_model).exists():
        model_path = Path(effective_model)
        if model_path.suffix.lower() != ".pt":
            raise RuntimeError("Model YOLO znaków musi mieć rozszerzenie .pt.")
        host._log(host.test_log_text, f"[INFO] Używam lokalnego modelu: {model_path}", "INFO")
        return str(model_path)

    if getattr(host, "_step3_linear_mode", False):
        raise RuntimeError(
            "Brak wytrenowanego modelu znaków przypiętego do projektu. "
            "Najpierw przygotuj i wytrenuj model w Z4."
        )

    raise RuntimeError(
        "Wskaż wytrenowany model YOLO znaków (.pt). "
        "W Z3/PZ2 nie korzystamy z niewytrenowanych wariantów architektury."
    )


def pick_yolo_model(host) -> str:
    initial_dir = CONFIG.get_trained_models_dir("char")
    if not initial_dir.exists():
        initial_dir = CONFIG.DIR_6_MODELS
    p = filedialog.askopenfilename(
        initialdir=str(Path(initial_dir).absolute()),
        title="Wybierz model detekcji YOLO znaków (.pt)",
        filetypes=[("PyTorch", "*.pt")]
    )
    if not p:
        return ""

    try:
        chosen = Path(p)
    except Exception:
        return ""

    if chosen.suffix.lower() != ".pt" or not chosen.exists():
        messagebox.showwarning(
            "Błędny model YOLO",
            "Wskaż poprawny, wytrenowany model YOLO znaków z rozszerzeniem .pt.",
        )
        return ""

    if getattr(host, "_step3_linear_mode", False):
        try:
            CAMPAIGN.set_global_model("char", str(chosen))
        except Exception as exc:
            logger.debug(f"Nie udało się zapisać modelu znaków w projekcie: {exc}")

    host.yolo_model_path_var.set(str(chosen))
    try:
        host._force_save_all()
    except Exception:
        pass
    host._refresh_detect_mode_cards()
    host._update_yolo_visibility()
    try:
        host._refresh_detection_pipeline_builder()
    except Exception:
        pass
    return str(chosen)


def update_yolo_visibility(host):
    self = host
    if not hasattr(self, "yolo_panel"):
        return

    try:
        self._sync_yolo_model_binding()
    except Exception:
        pass

    method = self._get_detection_method_key()
    has_yolo_model = self._has_configured_yolo_detection_model()
    if method in ("YOLO", "BOTH", "YOLO_OCR") and not has_yolo_model:
        method = "OCR"
        try:
            self.detection_method_var.set(method)
        except Exception:
            pass

    is_ocr = method == "OCR"
    is_yolo = method == "YOLO"
    is_hybrid = method == "BOTH"
    is_yolo_ocr = method == "YOLO_OCR"

    if hasattr(self, "hybrid_rescue_frame"):
        if is_hybrid:
            self.hybrid_rescue_frame.pack(fill=tk.X, pady=(0, 8))
        else:
            self.hybrid_rescue_frame.pack_forget()

    if not str(self.yolo_panel.winfo_manager()):
        self.yolo_panel.pack(fill=tk.X, pady=(5, 0))

    for attr_name in (
        "yolo_conf_spin",
        "yolo_iou_spin",
        "yolo_overlap_spin",
        "yolo_seq_center_y_scale",
        "yolo_seq_min_h_scale",
        "yolo_seq_max_h_scale",
        "yolo_seq_max_w_scale",
        "yolo_seq_soft_overlap_scale",
        "yolo_seq_hard_overlap_scale",
    ):
        widget = getattr(self, attr_name, None)
        if widget is not None:
            self._set_widget_state(widget, "normal")

    for attr_name in ("hybrid_rescue_scale",):
        widget = getattr(self, attr_name, None)
        if widget is not None:
            self._set_widget_state(widget, "normal" if is_hybrid else "disabled")

    if hasattr(self, "hybrid_yolo_box_backend_row_info"):
        self.hybrid_yolo_box_backend_row_info["enabled"] = bool(is_hybrid)
        self._refresh_selection_row(self.hybrid_yolo_box_backend_row_info)

    if hasattr(self, "yolo_agnostic_row_info"):
        self.yolo_agnostic_row_info["enabled"] = True
        self._refresh_selection_row(self.yolo_agnostic_row_info)

    if hasattr(self, "det_yolo_model_entry"):
        self._set_widget_state(self.det_yolo_model_entry, "readonly")

    if hasattr(self, "det_yolo_model_browse_btn"):
        self._set_widget_state(self.det_yolo_model_browse_btn, "normal")

    try:
        self._refresh_yolo_model_picker_state()
    except Exception:
        pass

    if hasattr(self, "btn_ocr_lab"):
        self._set_widget_state(self.btn_ocr_lab, "disabled" if is_yolo else "normal")

    if hasattr(self, "btn_rank_presets"):
        self._set_widget_state(self.btn_rank_presets, "normal" if is_ocr else "disabled")

    if hasattr(self, "winner_name_lbl") and hasattr(self, "winner_acc_lbl"):
        if is_ocr:
            self._update_winner_label()
        elif is_yolo:
            self._set_winner_name("Brak rankingu OCR", "neutral")
            self._set_winner_acc("Tryb YOLO nie bierze udziału w turnieju OCR", "muted")
        elif is_yolo_ocr:
            self._set_winner_name("Brak rankingu OCR", "neutral")
            self._set_winner_acc("Tryb YOLO boxy + OCR nie ustala zwycięzcy turnieju OCR", "muted")
        else:
            self._set_winner_name("Brak rankingu OCR", "neutral")
            self._set_winner_acc("Tryb hybrydowy nie ustala zwycięzcy turnieju OCR", "muted")

    if hasattr(self, "test_status_lbl"):
        if is_yolo:
            self._set_test_status(
                self._compose_detection_method_status(
                    "wskaż wytrenowany model znaków .pt i uruchom detekcję"
                ),
                "muted",
            )
        elif is_yolo_ocr:
            self._set_test_status(
                self._compose_detection_method_status(self._get_yolo_box_ocr_status_text()),
                "info",
            )
        elif is_hybrid:
            self._set_test_status(
                self._compose_detection_method_status(self._get_hybrid_detection_status_text()),
                "info",
            )
        else:
            self._set_test_status(
                self._compose_detection_method_status("gotowa do uruchomienia"),
                "success",
            )

    self._refresh_detect_mode_cards()
    self._refresh_detection_workflow_info_label()
    self._refresh_detection_advanced_sections()


def refresh_yolo_model_picker_state(host):
    self = host
    row = getattr(self, "yolo_model_row", None)
    status_lbl = getattr(self, "yolo_model_status_lbl", None)
    browse_btn = getattr(self, "det_yolo_model_browse_btn", None)
    if row is None:
        return

    try:
        self._sync_yolo_model_binding()
    except Exception:
        pass

    project_mode = bool(getattr(self, "_step3_linear_mode", False))
    yolo_model_path = str(self._get_effective_yolo_model_path() or "").strip()
    yolo_ready = bool(yolo_model_path and Path(yolo_model_path).exists())
    model_name = Path(yolo_model_path).name if yolo_ready else ""
    if yolo_ready:
        version, size = self._infer_yolo_arch_from_model_path(yolo_model_path)
        if version and size:
            model_name = f"{model_name} (YOLOv{version}{size})"

    if status_lbl is not None:
        if yolo_ready and project_mode:
            text = (
                f"Model detekcji znaków z projektu: {model_name}. "
                "Używany tylko do wykrywania/proponowania ramek w PZ2, nie do treningu."
            )
            tone = "neutral"
        elif yolo_ready:
            text = (
                f"Model detekcji znaków: {model_name}. "
                "Używany tylko w pipeline OCR/YOLO PZ2; model treningowy wybierasz osobno."
            )
            tone = "neutral"
        elif project_mode:
            text = (
                "Projekt nie ma przypiętego modelu detekcji znaków dla PZ2. "
                "Wskaż wytrenowany .pt, jeśli chcesz użyć pipeline z YOLO."
            )
            tone = "warning"
        else:
            text = (
                "Model detekcji YOLO nie jest jeszcze wybrany. "
                "To model do analizy znaków w PZ2, nie model startowy treningu."
            )
            tone = "muted"
        self._set_themed_label_state(status_lbl, text=text, tone=tone)
    try:
        self._refresh_detection_active_model_label()
    except Exception:
        pass

    if browse_btn is not None:
        try:
            browse_btn.configure(text=("Zmień model detekcji" if yolo_ready else "Wybierz model detekcji"))
        except Exception:
            pass
        try:
            browse_btn.grid()
        except Exception:
            pass
        self._set_widget_state(browse_btn, "normal")


