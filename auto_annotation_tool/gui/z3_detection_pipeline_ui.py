from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING

from .z3_detection_controls_ui import normalize_detection_method_key
from .z3_model_metadata_dialog import show_yolo_model_metadata_dialog
from .web_slim_scrollbar import blend_hex_colors

if TYPE_CHECKING:
    from .tab_character_annotation import CharacterAnnotationTab


def get_detection_pipeline_blocks(host, method_key: str | None, method_labels: dict, key_by_label: dict) -> list[str]:
    resolved_method = normalize_detection_method_key(
        method_key or host._get_detection_method_key(),
        method_labels,
        key_by_label,
    )
    if resolved_method == "YOLO":
        return ["yolo_box", "yolo_symbol"]
    if resolved_method == "BOTH":
        blocks = ["ocr_symbol", "yolo_box"]
        if host._get_hybrid_rescue_max_chars() > 0:
            blocks.append("yolo_symbol")
        return blocks
    if resolved_method == "YOLO_OCR":
        return ["yolo_box", "ocr_symbol"]
    return ["ocr_symbol"]


def compile_detection_pipeline_blocks(blocks=None, method_card_meta: dict | None = None) -> dict:
    prepared = [
        str(block or "").strip().lower().replace("-", "_")
        for block in (blocks or [])
        if str(block or "").strip()
    ]
    valid_patterns = {
        ("ocr_symbol",): ("OCR", False),
        ("yolo_box", "yolo_symbol"): ("YOLO", False),
        ("ocr_symbol", "yolo_box"): ("BOTH", False),
        ("ocr_symbol", "yolo_box", "yolo_symbol"): ("BOTH", True),
        ("yolo_box", "ocr_symbol"): ("YOLO_OCR", False),
    }
    compiled = valid_patterns.get(tuple(prepared))
    if compiled is None:
        return {
            "valid": False,
            "blocks": prepared,
            "method_key": None,
            "rescue_enabled": False,
            "requires_yolo": any(block.startswith("yolo") for block in prepared),
            "status_text": (
                "Ten łańcuch nie jest jeszcze wspierany. "
                "Dozwolone układy: O | YB->YS | O->YB | O->YB->YS | YB->O."
            ),
        }

    method_key, rescue_enabled = compiled
    method_card_meta = method_card_meta or {}
    label = method_card_meta.get(method_key, {}).get("title", method_key)
    status_text = f"Builder złoży ten pipeline jako tryb: {label}"
    if method_key == "BOTH":
        status_text += " z rescue" if rescue_enabled else " bez rescue"
    return {
        "valid": True,
        "blocks": prepared,
        "method_key": method_key,
        "rescue_enabled": bool(rescue_enabled),
        "requires_yolo": method_key in {"YOLO", "BOTH", "YOLO_OCR"},
        "status_text": status_text,
    }


def get_detection_workflow_text(host, method_key: str | None, method_labels: dict, key_by_label: dict) -> str:
    resolved_method = normalize_detection_method_key(
        method_key or host._get_detection_method_key(),
        method_labels,
        key_by_label,
    )
    if resolved_method == "YOLO":
        return "Pipeline: YOLO wykrywa znaki i klasy."
    if resolved_method == "BOTH":
        rescue_chars = host._get_hybrid_rescue_max_chars()
        rescue_text = f"rescue max {rescue_chars}" if rescue_chars > 0 else "rescue wyłączone"
        return f"Pipeline: OCR czyta, YOLO dopasowuje; {rescue_text}."
    if resolved_method == "YOLO_OCR":
        return "Pipeline: YOLO boxy, OCR odczyt cropów."
    return "Pipeline: OCR czyta i segmentuje znaki."


def apply_detection_pipeline_blocks(host, blocks, *, save: bool = True, prompt_for_yolo_model: bool = True) -> bool:
    compiled = host._compile_detection_pipeline_blocks(blocks)
    if not bool(compiled.get("valid")):
        return False

    method_key = str(compiled.get("method_key") or "OCR")
    requires_yolo = bool(compiled.get("requires_yolo"))
    if requires_yolo and not host._has_configured_yolo_detection_model():
        if prompt_for_yolo_model:
            selected_model = str(host._pick_yolo_model() or "").strip()
            if not selected_model or not host._has_configured_yolo_detection_model():
                messagebox.showinfo(
                    "Brak modelu YOLO",
                    "Ten pipeline wymaga modelu YOLO znaków. Wskaż poprawny plik .pt, aby go zatwierdzić.",
                )
                return False
        else:
            return False

    if method_key == "BOTH":
        rescue_enabled = bool(compiled.get("rescue_enabled"))
        current_rescue = host._get_hybrid_rescue_max_chars()
        target_rescue = current_rescue if current_rescue > 0 else 2
        try:
            host.hybrid_rescue_max_chars_var.set(target_rescue if rescue_enabled else 0)
        except Exception:
            pass
        try:
            host.hybrid_yolo_box_backend_var.set(True)
        except Exception:
            pass

    host._set_detection_method_key(method_key, save=save)
    host._refresh_detection_workflow_info_label()
    return True


def refresh_detection_workflow_info_label(host) -> None:
    label = getattr(host, "detect_workflow_info_lbl", None)
    if label is None:
        return
    try:
        label.configure(text=host._get_detection_workflow_text())
    except Exception:
        pass
    try:
        host._refresh_detection_active_model_label()
    except Exception:
        pass


def get_detection_pipeline_block_meta(block_key: str, block_library: dict) -> dict:
    normalized = str(block_key or "").strip().lower().replace("-", "_")
    fallback = block_library.get("ocr_symbol", {})
    return dict(block_library.get(normalized, fallback))


def get_detection_pipeline_block_style(host, block_key: str) -> dict:
    normalized = str(block_key or "").strip().lower().replace("-", "_")
    palette = getattr(host.app, "palette", {})
    component_style = host._get_preview_badge_component_style(normalized)
    panel = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    badge_fill = str(component_style.get("badge_fill", component_style.get("outline", "#3c3c3c")))
    badge_outline = str(component_style.get("badge_outline", badge_fill))
    fill = blend_hex_colors(badge_fill, panel_alt, 0.22)
    fill_selected = blend_hex_colors(badge_fill, panel_alt, 0.42)
    text_color = host._get_readable_text_color(fill, preferred=palette.get("fg", "#f3f3f3"))
    muted_color = host._get_readable_text_color(fill, preferred=palette.get("muted", "#c7c7c7"))
    selected_text_color = host._get_readable_text_color(fill_selected, preferred=text_color)
    selected_muted_color = host._get_readable_text_color(fill_selected, preferred=muted_color)
    return {
        "badge_fill": badge_fill,
        "badge_outline": badge_outline,
        "badge_fg": host._get_readable_text_color(
            badge_fill,
            preferred=str(component_style.get("badge_fg", "#ffffff")),
        ),
        "fill": fill,
        "fill_selected": fill_selected,
        "outline": badge_outline,
        "text": text_color,
        "muted": muted_color,
        "text_selected": selected_text_color,
        "muted_selected": selected_muted_color,
        "shadow": blend_hex_colors(badge_fill, panel, 0.55),
    }


def get_detection_pipeline_builder_blocks(host) -> list[str]:
    state = getattr(host, "_detection_pipeline_state", {}) or {}
    return list(state.get("blocks", []) or [])


def set_detection_pipeline_builder_blocks(host, blocks, *, selected_index: int | None = None) -> None:
    prepared = [
        str(block or "").strip().lower().replace("-", "_")
        for block in (blocks or [])
        if str(block or "").strip()
    ]
    if selected_index is None:
        selected_index = 0 if prepared else None
    elif prepared:
        selected_index = max(0, min(len(prepared) - 1, int(selected_index)))
    else:
        selected_index = None
    host._detection_pipeline_state = {
        "blocks": prepared,
        "selected_index": selected_index,
    }


def select_detection_pipeline_builder_block(host, index: int | None) -> None:
    blocks = host._get_detection_pipeline_builder_blocks()
    if not blocks:
        host._set_detection_pipeline_builder_blocks([], selected_index=None)
    else:
        safe_index = 0 if index is None else max(0, min(len(blocks) - 1, int(index)))
        host._set_detection_pipeline_builder_blocks(blocks, selected_index=safe_index)
    host._refresh_detection_pipeline_builder()


def set_detection_pipeline_builder_preset(host, method_key: str) -> None:
    blocks = host._get_detection_pipeline_blocks(method_key)
    host._set_detection_pipeline_builder_blocks(blocks, selected_index=0 if blocks else None)
    host._refresh_detection_pipeline_builder()


def append_detection_pipeline_builder_block(host, block_key: str) -> None:
    blocks = host._get_detection_pipeline_builder_blocks()
    blocks.append(str(block_key or "").strip().lower().replace("-", "_"))
    host._set_detection_pipeline_builder_blocks(blocks, selected_index=len(blocks) - 1)
    host._refresh_detection_pipeline_builder()


def move_detection_pipeline_builder_selected_block(host, direction: int) -> None:
    blocks = host._get_detection_pipeline_builder_blocks()
    state = getattr(host, "_detection_pipeline_state", {}) or {}
    selected_index = state.get("selected_index")
    if selected_index is None or not blocks:
        return
    try:
        current = int(selected_index)
        target = int(current) + int(direction)
    except Exception:
        return
    if target < 0 or target >= len(blocks):
        return
    blocks[current], blocks[target] = blocks[target], blocks[current]
    host._set_detection_pipeline_builder_blocks(blocks, selected_index=target)
    host._refresh_detection_pipeline_builder()


def remove_detection_pipeline_builder_selected_block(host) -> None:
    blocks = host._get_detection_pipeline_builder_blocks()
    state = getattr(host, "_detection_pipeline_state", {}) or {}
    selected_index = state.get("selected_index")
    if selected_index is None or not blocks:
        return
    try:
        current = int(selected_index)
    except Exception:
        return
    if current < 0 or current >= len(blocks):
        return
    blocks.pop(current)
    next_index = min(current, len(blocks) - 1) if blocks else None
    host._set_detection_pipeline_builder_blocks(blocks, selected_index=next_index)
    host._refresh_detection_pipeline_builder()


def clear_detection_pipeline_builder(host) -> None:
    host._set_detection_pipeline_builder_blocks([], selected_index=None)
    host._refresh_detection_pipeline_builder()


def close_detection_pipeline_builder(host) -> None:
    modal = getattr(host, "_detection_pipeline_modal", None)
    try:
        if modal is not None and modal.winfo_exists():
            modal.destroy()
    except Exception:
        pass
    host._detection_pipeline_modal = None
    host._detection_pipeline_canvas = None
    host._detection_pipeline_property_body = None
    host._detection_pipeline_runtime = {}
    host._detection_pipeline_confirm_btn = None
    host._detection_pipeline_status_var = None
    host._detection_pipeline_hint_var = None
    host._detection_pipeline_model_frame = None
    host._detection_pipeline_model_status_lbl = None
    host._detection_pipeline_model_btn = None
    host._detection_pipeline_model_details_btn = None


def show_detection_pipeline_model_details(host, model_path: str | None = None, *, title: str | None = None) -> None:
    resolved_path = str(model_path or host._get_effective_yolo_model_path() or "").strip()
    if not resolved_path:
        messagebox.showinfo(
            "Parametry modelu YOLO",
            "Najpierw wskaż model YOLO .pt. Parametry zostaną odczytane z pliku JSON obok modelu.",
            parent=getattr(host, "_detection_pipeline_modal", None) or getattr(host, "frame", None),
        )
        return
    show_yolo_model_metadata_dialog(host, resolved_path, title=title)


def pick_detection_pipeline_yolo_model(host) -> str:
    selected = str(host._pick_yolo_model() or "").strip()
    try:
        host._refresh_detection_pipeline_builder()
    except Exception:
        pass
    if selected:
        try:
            host._show_detection_pipeline_model_details(selected, title="Parametry wybranego modelu YOLO")
        except Exception:
            pass
    return selected


def commit_detection_pipeline_builder(host) -> None:
    blocks = host._get_detection_pipeline_builder_blocks()
    if not host._apply_detection_pipeline_blocks(blocks, save=True, prompt_for_yolo_model=True):
        host._refresh_detection_pipeline_builder()
        return
    host._close_detection_pipeline_builder()


def refresh_detection_pipeline_builder(host) -> None:
    modal = getattr(host, "_detection_pipeline_modal", None)
    if modal is None:
        return
    try:
        if not modal.winfo_exists():
            host._close_detection_pipeline_builder()
            return
    except Exception:
        host._close_detection_pipeline_builder()
        return

    blocks = host._get_detection_pipeline_builder_blocks()
    compiled = host._compile_detection_pipeline_blocks(blocks)
    if (
        bool(compiled.get("valid"))
        and bool(compiled.get("requires_yolo"))
        and not host._has_configured_yolo_detection_model()
    ):
        compiled["status_text"] = (
            str(compiled.get("status_text") or "")
            + " | Brak modelu YOLO: zatwierdzenie poprosi o wskazanie pliku .pt."
        )
    status_var = getattr(host, "_detection_pipeline_status_var", None)
    if status_var is not None:
        try:
            status_var.set(str(compiled.get("status_text") or ""))
        except Exception:
            pass

    hint_var = getattr(host, "_detection_pipeline_hint_var", None)
    if hint_var is not None:
        if blocks:
            badges = [host._get_detection_pipeline_block_meta(block).get("badge", "?") for block in blocks]
            hint_text = "Aktualny łańcuch: " + " -> ".join(badges)
        else:
            hint_text = "Dodaj klocki O, YB i YS, aby złożyć metodę detekcji."
        try:
            hint_var.set(hint_text)
        except Exception:
            pass

    host._refresh_detection_pipeline_model_row(compiled)

    confirm_btn = getattr(host, "_detection_pipeline_confirm_btn", None)
    if confirm_btn is not None:
        host._set_widget_state(confirm_btn, "normal" if bool(compiled.get("valid")) else "disabled")

    host._draw_detection_pipeline_builder_canvas()
    host._refresh_detection_pipeline_builder_property_panel()


def refresh_detection_pipeline_model_row(host, compiled: dict | None = None) -> None:
    frame = getattr(host, "_detection_pipeline_model_frame", None)
    status_lbl = getattr(host, "_detection_pipeline_model_status_lbl", None)
    browse_btn = getattr(host, "_detection_pipeline_model_btn", None)
    details_btn = getattr(host, "_detection_pipeline_model_details_btn", None)
    if frame is None:
        return

    compiled = compiled if isinstance(compiled, dict) else {}
    requires_yolo = bool(compiled.get("requires_yolo"))
    try:
        if requires_yolo:
            frame.grid()
        elif str(frame.winfo_manager()):
            frame.grid_remove()
    except Exception:
        pass

    if not requires_yolo:
        return

    project_mode = bool(getattr(host, "_step3_linear_mode", False))
    model_path = str(host._get_effective_yolo_model_path() or "").strip()
    yolo_ready = bool(model_path and Path(model_path).exists())

    if yolo_ready:
        model_name = Path(model_path).name
        version, size = host._infer_yolo_arch_from_model_path(model_path)
        if version and size:
            model_name = f"{model_name} (YOLOv{version}{size})"
        text = (
            f"Model YOLO z projektu: {model_name}"
            if project_mode
            else f"Model YOLO dla całego pipeline: {model_name}"
        )
        tone = "neutral"
    elif project_mode:
        text = "Projekt nie ma przypiętego modelu znaków. Wskaż model YOLO .pt dla PZ2."
        tone = "warning"
    else:
        text = "Ten pipeline używa YOLO. Wybierz jeden model znaków .pt dla całego pipeline."
        tone = "warning"

    if status_lbl is not None:
        if not host._set_inline_status_label_state(status_lbl, text=text, tone=tone, emphasis=False):
            host._set_themed_label_state(status_lbl, text=text, tone=tone, emphasis=False)

    if browse_btn is not None:
        try:
            browse_btn.configure(text=("Zmień model YOLO" if yolo_ready else "Wybierz model YOLO"))
        except Exception:
            pass
        try:
            browse_btn.grid()
        except Exception:
            pass
        host._set_widget_state(browse_btn, "normal")

    if details_btn is not None:
        try:
            details_btn.grid()
        except Exception:
            pass
        host._set_widget_state(details_btn, "normal" if yolo_ready else "disabled")


def refresh_detection_pipeline_builder_property_panel(host):
    self = host
    body = getattr(self, "_detection_pipeline_property_body", None)
    if body is None:
        return
    try:
        for child in list(body.winfo_children()):
            child.destroy()
    except Exception:
        return

    blocks = self._get_detection_pipeline_builder_blocks()
    state = getattr(self, "_detection_pipeline_state", {}) or {}
    selected_index = state.get("selected_index")
    if selected_index is None or not blocks:
        ttk.Label(
            body,
            text="Wybierz klocek na canvasie, aby edytować jego właściwości.",
            style="Muted.TLabel",
            wraplength=280,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X)
        return

    try:
        block_key = blocks[int(selected_index)]
    except Exception:
        ttk.Label(
            body,
            text="Nie udało się odczytać zaznaczonego klocka.",
            style="Muted.TLabel",
            wraplength=280,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X)
        return

    meta = self._get_detection_pipeline_block_meta(block_key)
    compiled = self._compile_detection_pipeline_blocks(blocks)

    ttk.Label(
        body,
        text=f"{meta.get('badge', '?')}  {meta.get('title', block_key)}",
        style="PanelHeading.TLabel",
    ).pack(anchor=tk.W, fill=tk.X)
    ttk.Label(
        body,
        text=str(meta.get("desc", "")),
        style="PanelMuted.TLabel",
        wraplength=300,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, fill=tk.X, pady=(4, 10))

    def add_spin(parent, text, variable, from_, to_, increment, width=8):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text=text).pack(side=tk.LEFT)
        spin = ttk.Spinbox(row, from_=from_, to=to_, increment=increment, textvariable=variable, width=width)
        spin.pack(side=tk.RIGHT)
        return spin

    def add_check(parent, text, variable):
        ttk.Checkbutton(parent, text=text, variable=variable).pack(anchor=tk.W, pady=(0, 8))

    def add_hint(parent, text):
        ttk.Label(
            parent,
            text=text,
            style="PanelMuted.TLabel",
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

    if block_key == "ocr_symbol":
        add_spin(body, "Min. wysokość boxa OCR:", self.ocr_min_height_ratio_var, 0.20, 1.00, 0.05)
        add_spin(body, "Próg pewności OCR:", self.ocr_conf_var, 0.05, 0.95, 0.05)
        add_spin(body, "Wysokość OCR [px]:", self.prep_height_var, 40, 150, 1)
        add_spin(body, "Padding [%]:", self.prep_padding_var, 0, 50, 1)
        add_check(body, "Pełna binaryzacja OCR", self.prep_use_bin_var)
        add_hint(body, "Te ustawienia sterują przygotowaniem cropów dla OCR oraz progiem akceptacji odczytu.")
        add_hint(body, "Chroni znaki typu Y/1 przed zbyt niskim boxem OCR. Wyżej: ramki mocniej trzymają wysokość wiersza; niżej: są ciaśniej docięte do znaku.")
    elif block_key == "yolo_box":
        add_spin(body, "Confidence:", self.yolo_conf_var, 0.0, 1.0, 0.05)
        add_spin(body, "NMS IoU:", self.yolo_iou_var, 0.01, 0.99, 0.05)
        add_spin(body, "Nakładanie boxów:", self.yolo_overlap_var, 0.0, 1.0, 0.05)
        add_check(body, "Class agnostic NMS", self.yolo_agnostic_nms_var)
        add_spin(body, "Tolerancja osi Y:", self.yolo_seq_center_y_var, 0.10, 1.50, 0.05)
        add_hint(body, "Klocek YB odpowiada za geometrię znaku: progi detekcji i filtr wiarygodnej sekwencji. O tym, czy końcowe ramki mają pochodzić z YOLO, decyduje przełącznik „Końcowe ramki bierz z YOLO” w opcjach zaawansowanych. Model YOLO wybierasz raz dla całego pipeline w górnym wierszu buildera.")
    elif block_key == "yolo_symbol":
        if bool(compiled.get("valid")) and compiled.get("method_key") == "BOTH":
            if self._get_hybrid_rescue_max_chars() <= 0:
                try:
                    self.hybrid_rescue_max_chars_var.set(2)
                except Exception:
                    pass
            add_spin(body, "Limit rescue:", self.hybrid_rescue_max_chars_var, 1, 5, 1)
            add_hint(body, "W tej konfiguracji YS działa jako ratunek: YOLO podmienia znak tylko tam, gdzie OCR się rozjeżdża. Źródło końcowych ramek ustawiasz przełącznikiem „Końcowe ramki bierz z YOLO” w opcjach zaawansowanych.")
        else:
            add_hint(body, "W tej konfiguracji YS bierze znak bezpośrednio z klasy modelu YOLO. Progi modelu są współdzielone z klockiem YB.")
            add_spin(body, "Confidence YB/YS:", self.yolo_conf_var, 0.0, 1.0, 0.05)

    ttk.Separator(body, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(6, 10))
    ttk.Label(
        body,
        text="Pełne ustawienia YOLO i OCR nadal są dostępne w sekcji Zaawansowane YOLO i OCR w prawym panelu.",
        style="PanelMuted.TLabel",
        wraplength=300,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, fill=tk.X)


def draw_detection_pipeline_builder_canvas(host):
    self = host
    canvas = getattr(self, "_detection_pipeline_canvas", None)
    if canvas is None:
        return
    try:
        canvas.update_idletasks()
    except Exception:
        pass

    width = max(360, int(canvas.winfo_width() or 0))
    height = max(220, int(canvas.winfo_height() or 0))
    palette = getattr(self.app, "palette", {})
    panel_bg = palette.get("panel", "#252526")
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))
    muted = palette.get("muted", "#c7c7c7")
    fg = palette.get("fg", "#f3f3f3")
    canvas.configure(bg=panel_bg)
    canvas.delete("all")
    self._detection_pipeline_runtime = {}

    blocks = self._get_detection_pipeline_builder_blocks()
    state = getattr(self, "_detection_pipeline_state", {}) or {}
    selected_index = state.get("selected_index")

    canvas.create_rectangle(1, 1, width - 2, height - 2, outline=border, width=1)
    center_y = float(height // 2)
    canvas.create_line(28, center_y, width - 28, center_y, fill=blend_hex_colors(border, panel_bg, 0.35), dash=(3, 4))

    if not blocks:
        canvas.create_text(
            width / 2.0,
            center_y - 16.0,
            text="Pusty pipeline",
            fill=fg,
            font=("Segoe UI", 14, "bold"),
            anchor="center",
        )
        canvas.create_text(
            width / 2.0,
            center_y + 14.0,
            text="Dodaj klocki O, YB i YS lub kliknij preset u góry.",
            fill=muted,
            font=("Segoe UI", 10),
            anchor="center",
        )
        return

    block_w = 168.0
    block_h = 86.0
    gap = 34.0
    total_w = (len(blocks) * block_w) + (max(0, len(blocks) - 1) * gap)
    start_x = max(18.0, (float(width) - total_w) / 2.0)
    top_y = center_y - (block_h / 2.0)

    for idx, block_key in enumerate(blocks):
        meta = self._get_detection_pipeline_block_meta(block_key)
        style = self._get_detection_pipeline_block_style(block_key)
        x1 = float(start_x + idx * (block_w + gap))
        x2 = x1 + block_w
        y1 = top_y
        y2 = y1 + block_h
        is_selected = idx == selected_index
        block_fill = str(style.get("fill_selected" if is_selected else "fill", panel_bg))
        title_fill = str(style.get("text_selected" if is_selected else "text", fg))
        subtitle_fill = str(style.get("muted_selected" if is_selected else "muted", muted))

        if idx < len(blocks) - 1:
            arrow_y = center_y
            arrow_x1 = x2 + 8.0
            arrow_x2 = arrow_x1 + gap - 16.0
            canvas.create_line(
                arrow_x1,
                arrow_y,
                arrow_x2,
                arrow_y,
                fill=str(style.get("outline", border)),
                width=2,
                arrow=tk.LAST,
                arrowshape=(10, 12, 4),
            )

        if is_selected:
            canvas.create_rectangle(
                x1 - 3,
                y1 - 3,
                x2 + 3,
                y2 + 3,
                outline=str(style.get("shadow", style.get("outline", border))),
                width=2,
            )

        rect_id = canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=block_fill,
            outline=str(style.get("outline", border)),
            width=2 if is_selected else 1,
            tags=(f"det_pipeline_block::{idx}", "det_pipeline_block"),
        )
        badge_text = str(meta.get("badge", "?"))
        self._draw_preview_text_badge(
            canvas,
            x1 + 10,
            y1 + 10,
            badge_text,
            fill_color=str(style.get("badge_fill", style.get("outline", border))),
            outline_color=str(style.get("badge_outline", style.get("outline", border))),
            text_color=str(style.get("badge_fg", "#ffffff")),
            font=("Segoe UI", 9, "bold"),
            anchor=tk.NW,
            pad_x=6,
            pad_y=2,
            tags=(f"det_pipeline_block::{idx}", "det_pipeline_block"),
        )
        canvas.create_text(
            x1 + 12,
            y1 + 38,
            text=str(meta.get("title", block_key)),
            fill=title_fill,
            font=("Segoe UI", 10, "bold"),
            anchor=tk.NW,
            tags=(f"det_pipeline_block::{idx}", "det_pipeline_block"),
        )
        canvas.create_text(
            x1 + 12,
            y1 + 60,
            text=str(meta.get("subtitle", "")),
            fill=subtitle_fill,
            font=("Segoe UI", 8),
            anchor=tk.NW,
            tags=(f"det_pipeline_block::{idx}", "det_pipeline_block"),
        )
        self._detection_pipeline_runtime[idx] = {
            "bbox": (x1, y1, x2, y2),
            "rect_id": rect_id,
            "block_key": block_key,
        }

    for idx in self._detection_pipeline_runtime.keys():
        canvas.tag_bind(
            f"det_pipeline_block::{idx}",
            "<Button-1>",
            lambda _event, picked=idx: self._select_detection_pipeline_builder_block(picked),
        )


def open_detection_pipeline_builder(host, initial_method=None, detection_pipeline_preset_meta=None):
    self = host
    preset_meta = detection_pipeline_preset_meta or {}
    initial_mode = self._normalize_detection_method_key(initial_method or self._get_detection_method_key())
    existing = getattr(self, "_detection_pipeline_modal", None)
    try:
        if existing is not None and existing.winfo_exists():
            self._set_detection_pipeline_builder_preset(initial_mode)
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
    except Exception:
        self._close_detection_pipeline_builder()

    palette = getattr(self.app, "palette", {})
    panel_bg = palette.get("panel", "#252526")
    panel_alt = palette.get("panel_alt", "#2d2d30")
    border = palette.get("panel_border", palette.get("border", "#3c3c3c"))

    win = tk.Toplevel(self.frame)
    win.title("Budowniczy pipeline detekcji")
    try:
        win.geometry("1160x760")
        win.minsize(980, 680)
    except Exception:
        pass
    try:
        win.transient(self.frame.winfo_toplevel())
    except Exception:
        pass
    try:
        win.grab_set()
    except Exception:
        pass
    win.configure(bg=panel_bg)
    win.protocol("WM_DELETE_WINDOW", self._close_detection_pipeline_builder)

    self._detection_pipeline_modal = win
    self._detection_pipeline_status_var = tk.StringVar(value="")
    self._detection_pipeline_hint_var = tk.StringVar(value="")
    self._set_detection_pipeline_builder_blocks(self._get_detection_pipeline_blocks(initial_mode), selected_index=0)

    root = ttk.Frame(win, padding=14)
    root.pack(fill=tk.BOTH, expand=True)
    root.columnconfigure(0, weight=1)
    root.columnconfigure(1, weight=0)
    root.rowconfigure(4, weight=1)

    ttk.Label(root, text="Budowniczy pipeline detekcji", style="PanelHeading.TLabel").grid(
        row=0,
        column=0,
        columnspan=2,
        sticky="w",
    )
    intro = ttk.Label(
        root,
        text=(
            "Ułóż liniowy łańcuch klocków O, YB i YS. System na żywo sprawdzi, "
            "czy taki pipeline jest wspierany przez obecny backend i do jakiego trybu się mapuje. "
            "Jeżeli pipeline używa YOLO, model wybierasz raz dla całego układu."
        ),
        style="PanelMuted.TLabel",
        wraplength=960,
        justify=tk.LEFT,
    )
    intro.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))

    presets_row = ttk.Frame(root)
    presets_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
    ttk.Label(presets_row, text="Gotowe presety:").pack(side=tk.LEFT, padx=(0, 8))
    for preset_key in ("OCR", "YOLO", "BOTH", "YOLO_OCR"):
        meta = preset_meta.get(preset_key, {})
        ttk.Button(
            presets_row,
            text=str(meta.get("label", preset_key)),
            command=lambda key=preset_key: self._set_detection_pipeline_builder_preset(key),
        ).pack(side=tk.LEFT, padx=(0, 6))

    model_frame = tk.Frame(
        root,
        bg=panel_alt,
        bd=0,
        highlightthickness=1,
        highlightbackground=border,
        highlightcolor=border,
        padx=10,
        pady=8,
    )
    model_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    model_frame.grid_columnconfigure(1, weight=1)
    self._detection_pipeline_model_frame = model_frame

    model_title_lbl = tk.Label(
        model_frame,
        text="Model YOLO pipeline",
        bg=panel_alt,
        fg=palette.get("fg", "#f3f3f3"),
        font=("Segoe UI", 9, "bold"),
        anchor="w",
        justify=tk.LEFT,
        bd=0,
        highlightthickness=0,
    )
    model_title_lbl.grid(row=0, column=0, sticky="w", padx=(0, 10))

    self._detection_pipeline_model_status_lbl = tk.Label(
        model_frame,
        text="",
        bg=panel_alt,
        fg=palette.get("muted", "#c7c7c7"),
        anchor="w",
        justify=tk.LEFT,
        wraplength=780,
        bd=0,
        highlightthickness=0,
    )
    self._detection_pipeline_model_status_lbl.grid(row=0, column=1, sticky="ew")

    self._detection_pipeline_model_btn = ttk.Button(
        model_frame,
        text="Wybierz model",
        command=self._pick_detection_pipeline_yolo_model,
    )
    self._detection_pipeline_model_btn.grid(row=0, column=2, sticky="e", padx=(10, 0))

    self._detection_pipeline_model_details_btn = ttk.Button(
        model_frame,
        text="Parametry",
        command=self._show_detection_pipeline_model_details,
    )
    self._detection_pipeline_model_details_btn.grid(row=0, column=3, sticky="e", padx=(8, 0))

    main = ttk.Frame(root)
    main.grid(row=4, column=0, columnspan=2, sticky="nsew")
    main.columnconfigure(0, weight=1)
    main.columnconfigure(1, weight=0)
    main.rowconfigure(0, weight=1)

    canvas_shell = tk.Frame(main, bg=panel_bg, bd=0, highlightthickness=1, highlightbackground=border, highlightcolor=border)
    canvas_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    canvas_shell.grid_rowconfigure(1, weight=1)
    canvas_shell.grid_columnconfigure(0, weight=1)

    builder_hint_lbl = tk.Label(
        canvas_shell,
        textvariable=self._detection_pipeline_hint_var,
        anchor="w",
        justify=tk.LEFT,
        bg=panel_bg,
        fg=palette.get("fg", "#f3f3f3"),
        bd=0,
        highlightthickness=0,
        padx=12,
        pady=10,
    )
    builder_hint_lbl.grid(row=0, column=0, sticky="ew")

    self._detection_pipeline_canvas = tk.Canvas(
        canvas_shell,
        height=320,
        bg=panel_bg,
        bd=0,
        highlightthickness=0,
    )
    self._detection_pipeline_canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
    self._detection_pipeline_canvas.bind(
        "<Configure>",
        lambda _event: self._draw_detection_pipeline_builder_canvas(),
        add="+",
    )

    controls_row = ttk.Frame(canvas_shell)
    controls_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 12))
    ttk.Button(controls_row, text="+ O", command=lambda: self._append_detection_pipeline_builder_block("ocr_symbol")).pack(side=tk.LEFT)
    ttk.Button(controls_row, text="+ YB", command=lambda: self._append_detection_pipeline_builder_block("yolo_box")).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(controls_row, text="+ YS", command=lambda: self._append_detection_pipeline_builder_block("yolo_symbol")).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(controls_row, text="Przesuń w lewo", command=lambda: self._move_detection_pipeline_builder_selected_block(-1)).pack(side=tk.LEFT, padx=(16, 0))
    ttk.Button(controls_row, text="Przesuń w prawo", command=lambda: self._move_detection_pipeline_builder_selected_block(1)).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(controls_row, text="Usuń blok", command=self._remove_detection_pipeline_builder_selected_block).pack(side=tk.LEFT, padx=(16, 0))
    ttk.Button(controls_row, text="Wyczyść", command=self._clear_detection_pipeline_builder).pack(side=tk.LEFT, padx=(6, 0))

    inspector = tk.Frame(main, bg=panel_alt, bd=0, highlightthickness=1, highlightbackground=border, highlightcolor=border)
    inspector.grid(row=0, column=1, sticky="ns")
    inspector.configure(width=340)
    inspector.grid_propagate(False)
    inspector_body = ttk.Frame(inspector, padding=(12, 12))
    inspector_body.pack(fill=tk.BOTH, expand=True)
    self._detection_pipeline_property_body = inspector_body

    footer = ttk.Frame(root)
    footer.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    footer.columnconfigure(0, weight=1)

    ttk.Label(
        footer,
        textvariable=self._detection_pipeline_status_var,
        style="PanelMuted.TLabel",
        wraplength=900,
        justify=tk.LEFT,
    ).grid(row=0, column=0, sticky="w")

    footer_buttons = ttk.Frame(footer)
    footer_buttons.grid(row=0, column=1, sticky="e")
    ttk.Button(footer_buttons, text="Anuluj", command=self._close_detection_pipeline_builder).pack(side=tk.RIGHT)
    self._detection_pipeline_confirm_btn = ttk.Button(
        footer_buttons,
        text="Zatwierdź pipeline",
        command=self._commit_detection_pipeline_builder,
    )
    self._detection_pipeline_confirm_btn.pack(side=tk.RIGHT, padx=(0, 8))

    self._refresh_detection_pipeline_builder()


