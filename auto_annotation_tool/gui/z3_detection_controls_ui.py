#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Kontrolki, statusy i style panelu detekcji znaków Z3/PZ2."""

import json
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from .web_slim_scrollbar import blend_hex_colors

def set_test_status(host, text: str, tone: str = "neutral") -> None:
    label = getattr(host, "test_status_lbl", None)
    fixed_tone = "neutral"
    if not host._set_inline_status_label_state(label, text=text, tone=fixed_tone, emphasis=False):
        host._set_themed_label_state(label, text=text, tone=fixed_tone, emphasis=False)


def get_detection_method_status_label(host) -> str:
    method_key = str(host._get_detection_method_key() or "OCR").strip().upper()
    if method_key == "YOLO":
        return "YOLO"
    if method_key == "BOTH":
        return "Hybryda OCR+YOLO"
    if method_key == "YOLO_OCR":
        return "YOLO boxy + OCR"
    return "OCR"


def compose_detection_method_status(host, detail: str | None = None) -> str:
    base = f"Tryb pracy: {host._get_detection_method_status_label()}"
    detail_text = str(detail or "").strip()
    if not detail_text:
        return base
    return f"{base} | {detail_text}"


def get_detection_pipeline_short_label(host, method_key: str | None = None) -> str:
    block_labels = {
        "ocr_symbol": "O",
        "yolo_box": "YB",
        "yolo_symbol": "YS",
    }
    try:
        blocks = host._get_detection_pipeline_blocks(method_key)
    except Exception:
        blocks = []
    labels: list[str] = []
    for block in blocks or []:
        key = str(block or "").strip().lower()
        label = block_labels.get(key)
        if label:
            labels.append(label)
    if labels:
        return " -> ".join(labels)
    try:
        return host._get_detection_method_status_label()
    except Exception:
        return "OCR"


def get_last_detection_summary_path(host, preview_dir: str | Path | None = None) -> Path | None:
    try:
        base = Path(preview_dir or host.preview_dir_var.get().strip())
    except Exception:
        return None
    if not str(base).strip():
        return None
    return base / "last_detection_summary.json"


def load_last_detection_summary(host, preview_dir: str | Path | None = None) -> dict:
    path = get_last_detection_summary_path(host, preview_dir)
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_last_detection_summary(host, summary: dict, preview_dir: str | Path | None = None) -> None:
    path = get_last_detection_summary_path(host, preview_dir)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(summary if isinstance(summary, dict) else {}, ensure_ascii=False, indent=2)
        path.write_text(payload + "\n", encoding="utf-8")
    except Exception:
        pass


def format_detection_datetime(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "brak daty"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y, %H:%M")
    except Exception:
        return raw


def format_last_detection_summary_line(host, summary: dict | None = None) -> str:
    data = summary if isinstance(summary, dict) else host._load_last_detection_summary()
    if not data:
        return "Ostatnia detekcja: brak zapisanego przebiegu"

    when = format_detection_datetime(data.get("finished_at") or data.get("started_at"))
    plates = int(data.get("processed_plates", data.get("plates", 0)) or 0)
    total = int(data.get("plates", plates) or 0)
    chars = int(data.get("characters", 0) or 0)
    perfect = int(data.get("perfect", 0) or 0)
    pipeline = str(data.get("pipeline") or data.get("method_label") or "OCR").strip()
    plate_text = f"{plates}/{total} tablic" if total and total != plates else f"{plates} tablic"
    return f"Ostatnia detekcja: {when} | {plate_text} | {pipeline} | znaki {chars} | perfect {perfect}"


def format_plate_last_detection_line(host, data: dict | None) -> str:
    if not isinstance(data, dict):
        return ""
    last = data.get("last_detection")
    if not isinstance(last, dict) or not last:
        return ""
    when = format_detection_datetime(last.get("finished_at") or last.get("started_at"))
    pipeline = str(last.get("pipeline") or last.get("method_label") or last.get("method") or "OCR").strip()
    chars = int(last.get("characters", 0) or 0)
    result = str(last.get("result") or last.get("status") or "").strip()
    result_suffix = f" | wynik: {result}" if result else ""
    return f"ta tablica: ostatnia detekcja {when} | {pipeline} | znaki {chars}{result_suffix}"


def refresh_last_detection_status_label(host, summary: dict | None = None) -> None:
    label = getattr(host, "detect_last_run_lbl", None)
    if label is None:
        return
    data = summary if isinstance(summary, dict) else host._load_last_detection_summary()
    text = host._format_last_detection_summary_line(data)
    tone = "info" if data else "muted"
    if not host._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
        host._set_themed_label_state(label, text=text, tone=tone, emphasis=False)
    button = getattr(host, "btn_detection_last_details", None)
    if button is not None:
        try:
            button.configure(state="normal" if data else "disabled")
        except Exception:
            pass


def show_last_detection_details(host) -> None:
    summary = host._load_last_detection_summary()
    if not summary:
        return messagebox.showinfo("Ostatnia detekcja", "Brak zapisanego podsumowania ostatniej detekcji.")

    rows = [
        ("Zakończono", format_detection_datetime(summary.get("finished_at") or summary.get("started_at"))),
        ("Pipeline", str(summary.get("pipeline") or summary.get("method_label") or "OCR")),
        ("Tablice", f"{int(summary.get('processed_plates', summary.get('plates', 0)) or 0)}/{int(summary.get('plates', 0) or 0)}"),
        ("Znaki", str(int(summary.get("characters", 0) or 0))),
        ("Perfect", str(int(summary.get("perfect", 0) or 0))),
        ("Urządzenie", str(summary.get("device") or "brak danych")),
    ]
    model = str(summary.get("model") or "").strip()
    if model:
        rows.append(("Model", Path(model).name))
    body = "\n".join(f"{label}: {value}" for label, value in rows)
    return messagebox.showinfo("Ostatnia detekcja", body)


def normalize_detection_method_key(raw_value=None, method_labels: dict | None = None, key_by_label: dict | None = None) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return "OCR"

    method_labels = method_labels or {}
    key_by_label = key_by_label or {}
    upper_value = value.upper()
    if upper_value in method_labels:
        return upper_value

    exact_match = key_by_label.get(value)
    if exact_match:
        return exact_match

    compact_value = "".join(ch for ch in upper_value if ch.isalnum())
    compact_aliases = {
        "OCRYOLO": "BOTH",
        "HYBRYDAOCRYOLO": "BOTH",
        "HYBRYDAOCRODCZYTYOLORAMKI": "BOTH",
        "YOLOBOXYOCR": "YOLO_OCR",
        "YOLOOCR": "YOLO_OCR",
        "HYBRYDAYOLOBOXYOCRODCZYT": "YOLO_OCR",
    }
    alias = compact_aliases.get(compact_value)
    if alias:
        return alias

    return "OCR"


def get_detection_method_key(host, method_labels: dict, key_by_label: dict) -> str:
    raw_value = getattr(host, "detection_method_var", None).get() if hasattr(host, "detection_method_var") else "OCR"
    return normalize_detection_method_key(raw_value, method_labels, key_by_label)


def get_hybrid_rescue_max_chars(host) -> int:
    try:
        value = int(host.hybrid_rescue_max_chars_var.get())
    except Exception:
        value = 2
    return max(0, min(5, value))


def use_hybrid_yolo_box_backend(host) -> bool:
    try:
        return bool(host.hybrid_yolo_box_backend_var.get())
    except Exception:
        return True


def get_hybrid_detection_status_text(host) -> str:
    rescue_chars = host._get_hybrid_rescue_max_chars()
    backend_state = "ON" if host._use_hybrid_yolo_box_backend() else "OFF"
    rescue_text = "OFF" if rescue_chars <= 0 else f"YOLO rescue <= {rescue_chars}"
    return (
        f"odczyt: OCR | dopasowanie pozycji: YOLO | rescue: {rescue_text} | "
        f"końcowe ramki z YOLO: {backend_state}"
    )


def get_yolo_box_ocr_status_text() -> str:
    return "boxy: YOLO | odczyt cropów: OCR | końcowe ramki z YOLO"


def set_detection_method_key(host, method_key: str, method_labels: dict, *, save: bool = True) -> None:
    normalized = host._normalize_detection_method_key(method_key)
    try:
        host.detection_method_var.set(normalized)
    except Exception:
        pass

    host._update_yolo_visibility()
    if save:
        try:
            host._force_save_all()
        except Exception:
            pass


def refresh_detection_active_model_label(host) -> None:
    label = getattr(host, "detect_active_model_lbl", None)
    if label is None:
        return
    text, tone = host._get_detection_active_model_status()
    host._set_themed_label_state(label, text=text, tone=tone)
    refresh_detection_refiner_guard_label(host)


def get_detection_refiner_guard_status(host) -> tuple[str, str]:
    method_key = str(host._get_detection_method_key() or "OCR").strip().upper()
    method_has_yolo = method_key in {"YOLO", "BOTH", "YOLO_OCR"}
    if not method_has_yolo:
        return (
            "Refiner perfect: niedostępny w pipeline OCR. Poprawki boxów wymagają modelu YOLO.",
            "muted",
        )

    try:
        yolo_ready = bool(host._has_configured_yolo_detection_model())
    except Exception:
        yolo_ready = False
    if not yolo_ready:
        return (
            "Refiner perfect: czeka na model YOLO znaków.",
            "warning",
        )

    try:
        protect_perfect = bool(host.detect_protect_perfect_var.get())
    except Exception:
        protect_perfect = True
    if not protect_perfect:
        return (
            "Refiner perfect: wygaszony, bo ochrona tablic perfect jest wyłączona.",
            "muted",
        )

    try:
        refiner_enabled = bool(host.detect_refine_perfect_yolo_var.get())
    except Exception:
        refiner_enabled = False
    if refiner_enabled:
        try:
            continuity_guard = bool(host.detect_refiner_continuity_guard_var.get())
        except Exception:
            continuity_guard = True
        if continuity_guard:
            return (
                "Refiner perfect: aktywny dla pipeline z YOLO, pilnuje ciągłości znaku.",
                "success",
            )
        return (
            "Refiner perfect: aktywny dla pipeline z YOLO.",
            "success",
        )
    return (
        "Refiner perfect: wyłączony w ustawieniach ochrony przed detekcją.",
        "muted",
    )


def refresh_detection_refiner_guard_label(host) -> None:
    label = getattr(host, "detect_refiner_guard_lbl", None)
    if label is None:
        return
    text, tone = get_detection_refiner_guard_status(host)
    if not host._set_inline_status_label_state(label, text=text, tone=tone, emphasis=False):
        host._set_themed_label_state(label, text=text, tone=tone, emphasis=False)


def on_yolo_option_var_write(host, *_args) -> None:
    host._apply_yolo_option_check_style()
    try:
        host._save_local_setting("char_yolo_agnostic_nms", bool(host.yolo_agnostic_nms_var.get()))
    except Exception:
        pass
    try:
        host._save_local_setting("char_hybrid_yolo_box_backend", bool(host.hybrid_yolo_box_backend_var.get()))
    except Exception:
        pass
    if host._get_detection_method_key() == "BOTH" and hasattr(host, "test_status_lbl"):
        host._set_test_status(
            host._compose_detection_method_status(host._get_hybrid_detection_status_text()),
            "info",
        )


def set_detection_process_log_visibility(host, visible: bool) -> None:
    host._detection_log_visible = bool(visible)
    try:
        host.detection_log_frame.grid_remove()
    except Exception:
        pass

    if host._detection_log_visible:
        try:
            if hasattr(host.app, "show_global_terminal"):
                host.app.show_global_terminal()
        except Exception:
            pass

    try:
        host.btn_toggle_detection_log.config(text="Terminal")
    except Exception:
        pass


def toggle_detection_process_log(host) -> None:
    try:
        if hasattr(host.app, "toggle_global_terminal"):
            host.app.toggle_global_terminal()
            return
    except Exception:
        pass
    host._set_detection_process_log_visibility(
        not getattr(host, "_detection_log_visible", False)
    )


def set_test_progress_counter(
    host,
    current: int | None = None,
    total: int | None = None,
    perfect_count: int | None = None,
) -> None:
    label = getattr(host, "test_progress_count_lbl", None)
    if label is None:
        return

    if current is None or total is None or total <= 0:
        host._set_test_progress_detail("")
        return
    current = max(0, min(int(current), int(total)))
    perfect_value = max(0, min(int(perfect_count or 0), current))
    text = f"OK {perfect_value} | {current}/{int(total)}"
    tone = "muted" if current < int(total) else "success"

    if not host._set_inline_status_label_state(label, text=text, tone=tone, emphasis=True):
        host._set_themed_label_state(label, text=text, tone=tone, emphasis=True)


def set_test_progress_detail(
    host,
    text: str | None = None,
    tone: str = "muted",
    emphasis: bool = True,
) -> None:
    label = getattr(host, "test_progress_count_lbl", None)
    if label is None:
        return

    detail_text = str(text or "").strip()
    if not host._set_inline_status_label_state(label, text=detail_text, tone=tone, emphasis=emphasis):
        host._set_themed_label_state(label, text=detail_text, tone=tone, emphasis=emphasis)


def update_detection_progress_ui(host, current: int, total: int, perfect_count: int = 0, session_token=None) -> None:
    if session_token is not None and session_token != host._project_reset_token:
        return

    pct = ((max(0, int(current)) / max(1, int(total))) * 100.0) if total else 0.0

    try:
        host.test_progress.config(value=pct)
    except Exception:
        pass

    host._set_test_progress_counter(current, total, perfect_count=perfect_count)
    host._set_test_status(host._compose_detection_method_status("detekcja w toku"), "warning")
    try:
        host._update_preview_processing_overlay_progress(
            pct=pct,
            current=current,
            total=total,
            meta_text=f"{int(round(pct))}% | OK {int(perfect_count or 0)} | {int(current)}/{int(total)} tablic",
        )
    except Exception:
        pass


def apply_detection_advanced_section_style(host):
    self = host
    palette = getattr(self.app, "palette", {})
    panel_bg = palette.get("panel", "#252526")
    success_fg = palette.get("success", "#2ecc71")
    border_color = blend_hex_colors(success_fg, panel_bg, 0.42)

    frame_configs = (
        ("yolo_advanced_shell", {"bg": panel_bg, "highlightbackground": border_color, "highlightcolor": border_color}),
        ("actions_lf", {"bg": panel_bg, "highlightbackground": border_color, "highlightcolor": border_color}),
        ("hybrid_rescue_frame", {"bg": panel_bg, "highlightbackground": panel_bg, "highlightcolor": panel_bg}),
        ("ocr_summary_store", {"bg": panel_bg, "highlightbackground": panel_bg, "highlightcolor": panel_bg}),
    )
    for name, config in frame_configs:
        widget = getattr(self, name, None)
        if widget is None:
            continue
        try:
            widget.configure(**config)
        except Exception:
            pass

    self._apply_detection_param_row_style()


def apply_detection_param_row_style(host):
    self = host
    palette = getattr(self.app, "palette", {})
    panel_bg = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", panel_bg)
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    accent = palette.get("accent_hover", palette.get("accent", "#4f8de3"))
    fg = palette.get("fg", "#f3f3f3")
    success_fg = palette.get("success", "#2ecc71")
    row_bg = blend_hex_colors(accent, panel_alt, 0.92)
    row_hover_bg = blend_hex_colors(accent, row_bg, 0.74)
    row_border = blend_hex_colors(accent, border, 0.72)
    section_label_fg = blend_hex_colors(success_fg, fg, 0.18)
    section_divider = blend_hex_colors(success_fg, panel_bg, 0.78)

    for row_entry in getattr(self, "_detection_param_rows", []):
        frame = row_entry.get("frame")
        if frame is None:
            continue
        try:
            frame.configure(bg=row_bg, highlightbackground=row_border, highlightcolor=row_border)
        except Exception:
            pass
        for container in row_entry.get("containers", []):
            try:
                container.configure(bg=row_bg)
            except Exception:
                pass
        for label in row_entry.get("labels", []):
            try:
                label.configure(bg=row_bg, fg=fg)
            except Exception:
                pass
        for scale in row_entry.get("scales", []):
            try:
                self.app.style_ttk_scale_widget(scale, background=row_bg)
            except Exception:
                pass

    for row_info in getattr(self, "yolo_option_rows", []):
        if not isinstance(row_info, dict):
            continue
        row_info["base_bg"] = row_bg
        row_info["hover_bg"] = row_hover_bg
        row_info["border_color"] = row_border
        row_info["fg"] = fg

    for section_entry in getattr(self, "_detection_section_widgets", []):
        for label in section_entry.get("labels", []):
            try:
                label.configure(bg=panel_bg, fg=section_label_fg, font=("Segoe UI", 9, "bold"))
            except Exception:
                pass
        for divider in section_entry.get("dividers", []):
            try:
                divider.configure(bg=section_divider)
            except Exception:
                pass

    label_configs = (
        ("detect_yolo_advanced_title_lbl", {"bg": panel_bg, "fg": fg, "font": ("Segoe UI", 10, "bold")}),
        ("detect_ocr_title_lbl", {"bg": panel_bg, "fg": fg, "font": ("Segoe UI", 10, "bold")}),
        ("hybrid_rescue_title_lbl", {"bg": panel_bg, "fg": fg, "font": ("Segoe UI", 10, "bold")}),
    )
    for name, config in label_configs:
        widget = getattr(self, name, None)
        if widget is None:
            continue
        try:
            widget.configure(**config)
        except Exception:
            pass


def bind_detect_mode_card(host, widget, mode_key: str):
    self = host
    widgets = self._detect_mode_cards.get(mode_key, {})

    def _select(_event=None, target_mode=mode_key):
        self._handle_detect_mode_selection(target_mode)
        return "break"

    def _hover(enabled: bool):
        self._detect_mode_hover_key = mode_key if enabled else None
        self._refresh_detect_mode_cards()

    enabled = bool(widgets.get("enabled", True))
    cursor = "hand2" if enabled else "arrow"
    try:
        widget.configure(cursor=cursor)
    except Exception:
        pass

    if enabled:
        try:
            widget.bind("<Button-1>", _select)
        except Exception:
            pass
    else:
        try:
            widget.unbind("<Button-1>")
        except Exception:
            pass

    try:
        widget.bind("<Enter>", lambda _event: _hover(True))
        widget.bind("<Leave>", lambda _event: _hover(False))
    except Exception:
        pass

    for child in getattr(widget, "winfo_children", lambda: [])():
        bind_detect_mode_card(self, child, mode_key)


def handle_detect_mode_selection(host, mode_key: str, method_labels: dict):
    self = host
    normalized_mode = str(mode_key or "").strip().upper()
    if normalized_mode not in method_labels:
        return

    self._open_detection_pipeline_builder(initial_method=normalized_mode)


def refresh_detect_mode_cards(host, card_meta: dict):
    self = host
    cards = getattr(self, "_detect_mode_cards", {}) or {}
    if not cards:
        return

    palette = getattr(self.app, "palette", {})
    current_method = self._get_detection_method_key()
    hover_key = str(getattr(self, "_detect_mode_hover_key", "") or "").strip().upper()
    panel = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    hover_bg = palette.get("button_hover", panel_alt)
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    fg = palette.get("fg", "#f3f3f3")
    muted = palette.get("muted", "#c7c7c7")
    selected_bg = blend_hex_colors(panel_alt, hover_bg, 0.42)
    yolo_model_path = str(self._get_effective_yolo_model_path() or "").strip()
    yolo_ready = bool(yolo_model_path and Path(yolo_model_path).exists())

    for mode_key, widgets in cards.items():
        meta = card_meta.get(mode_key, {})
        is_selected = mode_key == current_method
        requires_yolo = mode_key in ("YOLO", "BOTH", "YOLO_OCR")
        is_enabled = not (requires_yolo and getattr(self, "_step3_linear_mode", False) and not yolo_ready)
        is_hovered = hover_key == mode_key
        card_bg = selected_bg if is_selected else (hover_bg if is_hovered else panel_alt)
        border_color = border
        title_fg = fg
        desc_fg = fg if is_selected else muted
        description = str(meta.get("desc", widgets.get("default_desc", "")) or "")

        if requires_yolo:
            if yolo_ready:
                if mode_key == "YOLO":
                    description = "YOLO sam wykrywa boxy i przypisuje klasy znaków. Kliknij kartę, aby otworzyć builder pipeline."
                elif mode_key == "BOTH":
                    description = "OCR pilnuje tekstu, a YOLO dopasowuje pozycje i może przejąć końcowe ramki. Kliknij kartę, aby otworzyć builder pipeline."
                else:
                    description = "YOLO wyznacza boxy znaków, a OCR czyta już pojedyncze cropy. Kliknij kartę, aby otworzyć builder pipeline."
            elif getattr(self, "_step3_linear_mode", False):
                description = "Tryb odblokuje się po przypięciu modelu YOLO znaków do projektu."
            else:
                description = "Kliknij, aby otworzyć builder pipeline i wskazać wytrenowany model YOLO znaków (.pt)."
        elif mode_key == "OCR":
            description = "OCR odczytuje cały napis i dzieli go na techniczne segmenty znaków. Kliknij kartę, aby otworzyć builder pipeline."

        widgets["enabled"] = is_enabled

        frame = widgets.get("frame")
        indicator = widgets.get("indicator")
        title = widgets.get("title")
        desc = widgets.get("desc")

        for widget in (frame, title, desc):
            if widget is None:
                continue
            try:
                widget.configure(bg=card_bg, highlightbackground=border_color, highlightcolor=border_color)
            except Exception:
                pass

        if title is not None:
            try:
                title.configure(fg=title_fg, text=str(meta.get("title", mode_key) or mode_key))
            except Exception:
                pass

        if desc is not None:
            try:
                desc.configure(text=description, fg=desc_fg)
            except Exception:
                pass

        if indicator is not None:
            self._draw_selection_indicator(indicator, "check", bool(is_selected and is_enabled), card_bg)

        if frame is not None:
            self._bind_detect_mode_card(frame, mode_key)
    self._refresh_detection_workflow_info_label()
    self._refresh_detection_refiner_guard_label()


def toggle_detection_advanced_panel(host):
    host._detection_advanced_expanded = not bool(getattr(host, "_detection_advanced_expanded", False))
    host._refresh_detection_advanced_sections()


def get_detection_advanced_toggle_label(host, visible_icon, hidden_icon) -> str:
    expanded = bool(getattr(host, "_detection_advanced_expanded", False))
    icon = visible_icon if expanded else hidden_icon
    return f"Zaawansowane YOLO i OCR  {icon}"


def refresh_detection_advanced_sections(host, visible_icon, hidden_icon):
    advanced_expanded = bool(getattr(host, "_detection_advanced_expanded", False))

    advanced_toggle = getattr(host, "detection_advanced_toggle_btn", None)
    if advanced_toggle is not None:
        try:
            advanced_toggle.configure(text=get_detection_advanced_toggle_label(host, visible_icon, hidden_icon))
        except Exception:
            pass

    yolo_section = getattr(host, "yolo_advanced_shell", None)
    if yolo_section is not None:
        try:
            if advanced_expanded:
                yolo_section.grid(row=3, column=0, sticky="ew", pady=(0, 10), padx=(12, 12))
            elif str(yolo_section.winfo_manager()):
                yolo_section.grid_remove()
        except Exception:
            pass

    ocr_section = getattr(host, "actions_lf", None)
    if ocr_section is not None:
        try:
            if advanced_expanded:
                ocr_section.grid()
            else:
                ocr_section.grid_remove()
        except Exception:
            pass


