from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tab_character_annotation import CharacterAnnotationTab


def plan_preview_canvas_info_overlay_layout(
    host: "CharacterAnnotationTab",
    canvas_width: int,
    source_line: str,
    status_text: str,
):
    canvas_w = max(40.0, float(canvas_width or 0.0))
    reset_width = host._measure_preview_overlay_text_width("Reset widoku", ("Segoe UI", 8, "bold")) + 12.0
    title_x = 10.0 + reset_width + 12.0
    result_slot_width = max(150.0, min(220.0, canvas_w * 0.20))
    file_slot_width = max(150.0, min(220.0, canvas_w * 0.20))
    badge_end_x = title_x + result_slot_width + 12.0 + file_slot_width + 6.0 + 78.0 + 6.0 + 84.0 + 6.0
    legend_x = badge_end_x + 8.0

    source_width = host._measure_preview_overlay_text_width(source_line, ("Segoe UI", 9))
    status_width = host._measure_preview_overlay_text_width(status_text, ("Segoe UI", 9, "bold"))
    source_right = canvas_w - 10.0
    source_left = source_right - source_width
    status_right = source_left - 10.0
    status_left = status_right - status_width

    legend_width = host._estimate_preview_source_legend_width()
    legend_height = host._estimate_preview_source_legend_height()
    info_text_height = host._measure_preview_overlay_font_height(("Segoe UI", 9, "bold"))
    stack_right_info = bool(status_left <= (badge_end_x + 14.0))
    available_legend_right = (canvas_w - 12.0) if stack_right_info else (status_left - 12.0)
    stack_legend = bool((legend_x + legend_width) > available_legend_right)

    legend_y = float(36.0 if stack_legend else 8.0)
    source_y = float(44.0 if stack_right_info else 16.0)
    status_y = float(44.0 if stack_right_info else 16.0)
    legend_bottom = legend_y + float(legend_height)
    right_info_bottom = max(source_y + info_text_height, status_y + info_text_height)
    min_bar_height = 60.0 if (stack_legend or stack_right_info) else 34.0
    bar_height = max(min_bar_height, legend_bottom + 8.0, right_info_bottom + 8.0)

    return {
        "title_x": float(title_x),
        "result_slot_width": float(result_slot_width),
        "file_slot_width": float(file_slot_width),
        "legend_x": float(title_x if stack_legend else legend_x),
        "legend_y": legend_y,
        "source_x": float(max(20.0, source_right)),
        "source_y": source_y,
        "status_x": float(max(20.0, status_right)),
        "status_y": status_y,
        "bar_height": float(bar_height),
    }


def focus_preview_canvas(host: "CharacterAnnotationTab"):
    canvas = getattr(host, "preview_canvas", None)
    if canvas is None:
        return
    try:
        canvas.focus_set()
    except Exception:
        pass


def resolve_preview_canvas_cursor(host: "CharacterAnnotationTab") -> str:
    if not bool(getattr(host, "_preview_render_state", None)):
        return "arrow"
    if getattr(host, "_preview_badge_drag_state", None) is not None:
        return "hand2"
    char_drag_state = getattr(host, "_preview_char_drag_state", None)
    if isinstance(char_drag_state, dict):
        mode = str(char_drag_state.get("mode", "move") or "move").lower()
        return "crosshair" if mode == "resize" else "fleur"
    if getattr(host, "_preview_pan_drag_state", None) is not None:
        return "fleur"
    if host._preview_char_add_requested():
        return "crosshair"
    return "arrow"


def apply_preview_canvas_cursor(host: "CharacterAnnotationTab", cursor: str | None = None):
    canvas = getattr(host, "preview_canvas", None)
    if canvas is None:
        return
    desired = str(cursor or resolve_preview_canvas_cursor(host) or "arrow")
    try:
        current = str(canvas.cget("cursor") or "")
    except Exception:
        current = ""
    if current == desired:
        return
    try:
        canvas.configure(cursor=desired)
    except Exception:
        pass


def on_preview_canvas_enter(host: "CharacterAnnotationTab", event=None):
    focus_preview_canvas(host)
    apply_preview_canvas_cursor(host)
    return None


def place_preview_record_overlay(
    host: "CharacterAnnotationTab",
    canvas_width: int,
    bar_height: float,
    *,
    left_x: float = 10.0,
    top_y: float = 6.0,
    right_limit: float | None = None,
):
    canvas = getattr(host, "preview_canvas", None)
    overlay = getattr(host, "preview_record_overlay", None)
    if canvas is None or overlay is None:
        return
    try:
        overlay.update_idletasks()
        overlay_w = float(max(0, int(overlay.winfo_reqwidth() or overlay.winfo_width() or 0)))
        x = float(left_x)
        if right_limit is not None and overlay_w > 0.0:
            x = min(x, max(10.0, float(right_limit) - overlay_w))
        y = float(top_y)
        overlay.place(in_=canvas, x=x, y=y, anchor="nw")
        overlay.lift()
    except Exception:
        pass


def get_preview_mode_overlay_collision_rects(host: "CharacterAnnotationTab"):
    canvas_w, canvas_h = host._get_preview_canvas_size()
    if canvas_w <= 0.0 or canvas_h <= 0.0:
        return []

    reserved_rects = []
    if bool(getattr(host, "_preview_render_state", None)):
        top_bar_height = max(38.0, float(getattr(host, "_preview_overlay_top_bar_height", 38.0) or 38.0))
        reserved_rects.append((0.0, 0.0, float(canvas_w), top_bar_height))

    legend_canvas = getattr(host, "preview_controls_canvas", None)
    legend_frame = getattr(host, "preview_hint_frame", None)
    if legend_canvas is not None and legend_frame is not None and bool(str(legend_frame.winfo_manager())):
        try:
            legend_canvas.update_idletasks()
            legend_frame.update_idletasks()
        except Exception:
            pass
        try:
            legend_x = float(max(0, int(legend_frame.winfo_x() or 0)))
            legend_y = float(max(0, int(legend_frame.winfo_y() or 0)))
            legend_w = float(max(0, int(legend_frame.winfo_width() or legend_canvas.winfo_width() or 0)))
            legend_h = float(max(0, int(legend_frame.winfo_height() or legend_canvas.winfo_height() or 0)))
        except Exception:
            legend_x = legend_y = legend_w = legend_h = 0.0
        if legend_w > 0.0 and legend_h > 0.0:
            reserved_rects.append((legend_x, legend_y, legend_x + legend_w, legend_y + legend_h))

    return reserved_rects


def resolve_preview_mode_overlay_collision_position(
    host: "CharacterAnnotationTab",
    x: float,
    y: float,
):
    clamped_x, clamped_y = host._clamp_preview_mode_overlay_position(x, y)
    overlay_w, overlay_h = host._get_preview_mode_overlay_size()
    canvas_w, canvas_h = host._get_preview_canvas_size()
    reserved_rects = get_preview_mode_overlay_collision_rects(host)
    margin = 12.0

    if overlay_w <= 0.0 or overlay_h <= 0.0 or canvas_w <= 0.0 or canvas_h <= 0.0 or not reserved_rects:
        return float(clamped_x), float(clamped_y)

    top_block_bottom = 0.0
    bottom_block_top = float(canvas_h)
    for rect in reserved_rects:
        _left, top, _right, bottom = [float(v) for v in rect]
        if top <= (margin + 2.0):
            top_block_bottom = max(top_block_bottom, bottom)
        if bottom >= (float(canvas_h) - margin - 2.0):
            bottom_block_top = min(bottom_block_top, top)

    candidate_positions = [
        (clamped_x, clamped_y),
        (float(canvas_w) - overlay_w - margin, max(margin, top_block_bottom + 8.0)),
        (margin, max(margin, top_block_bottom + 8.0)),
        (float(canvas_w) - overlay_w - margin, min(max(margin, bottom_block_top - overlay_h - 8.0), float(canvas_h) - overlay_h - margin)),
        (margin, min(max(margin, bottom_block_top - overlay_h - 8.0), float(canvas_h) - overlay_h - margin)),
    ]

    unique_candidates = []
    seen = set()
    for candidate_x, candidate_y in candidate_positions:
        safe_x, safe_y = host._clamp_preview_mode_overlay_position(candidate_x, candidate_y)
        key = (round(float(safe_x), 1), round(float(safe_y), 1))
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append((float(safe_x), float(safe_y)))

    best_candidate = (float(clamped_x), float(clamped_y))
    best_overlap = None
    for candidate_x, candidate_y in unique_candidates:
        candidate_rect = (
            float(candidate_x),
            float(candidate_y),
            float(candidate_x) + float(overlay_w),
            float(candidate_y) + float(overlay_h),
        )
        overlap_area = sum(
            host._preview_rect_intersection_area(candidate_rect, reserved_rect, padding=2.0)
            for reserved_rect in reserved_rects
        )
        if overlap_area <= 0.0:
            return float(candidate_x), float(candidate_y)
        if best_overlap is None or overlap_area < best_overlap:
            best_overlap = float(overlap_area)
            best_candidate = (float(candidate_x), float(candidate_y))

    return best_candidate


def get_preview_mode_overlay_default_position(
    host: "CharacterAnnotationTab",
    *,
    fullscreen: bool = False,
):
    if bool(fullscreen):
        top_bar_height = max(38.0, float(getattr(host, "_preview_overlay_top_bar_height", 38.0) or 38.0))
        return {"x": 12.0, "y": float(top_bar_height + 8.0)}

    canvas_w, _canvas_h = host._get_preview_canvas_size()
    overlay_w, _overlay_h = host._get_preview_mode_overlay_size()
    desired_x = max(12.0, canvas_w - overlay_w - 12.0)
    return {"x": float(desired_x), "y": 12.0}


def clamp_preview_controls_legend_offsets(
    host: "CharacterAnnotationTab",
    offset_x: float,
    offset_y: float,
    *,
    width: float | None = None,
    height: float | None = None,
) -> tuple[float, float]:
    host_widget = getattr(host, "preview_canvas_host", None)
    try:
        frame_w = float(host_widget.winfo_width() or host_widget.winfo_reqwidth() or 0) if host_widget is not None else 0.0
        frame_h = float(host_widget.winfo_height() or host_widget.winfo_reqheight() or 0) if host_widget is not None else 0.0
    except Exception:
        frame_w = 0.0
        frame_h = 0.0
    top_clearance = 0.0
    if bool(getattr(host, "_preview_fullscreen_active", False)) or bool(getattr(host, "_preview_render_state", None)):
        top_clearance = max(38.0, float(getattr(host, "_preview_overlay_top_bar_height", 38.0) or 38.0)) + 8.0
    safe_w = float(width or getattr(host, "_preview_controls_legend_current_width", 0.0) or 280.0)
    safe_h = float(height or getattr(host, "_preview_controls_legend_current_height", 0.0) or 120.0)
    clamped_x = min(max(0.0, float(offset_x)), max(0.0, frame_w - safe_w))
    max_y = max(0.0, frame_h - safe_h)
    min_y = min(max_y, max(0.0, top_clearance))
    clamped_y = min(max(min_y, float(offset_y)), max_y)
    return float(clamped_x), float(clamped_y)


def toggle_preview_controls_legend(host: "CharacterAnnotationTab", event=None):
    was_expanded = bool(host._is_preview_controls_legend_expanded())
    collapsed_anchor = None
    if not was_expanded:
        collapsed_anchor = {
            "x": float(getattr(host, "_preview_controls_legend_offset_x", 10.0) or 10.0),
            "y": float(getattr(host, "_preview_controls_legend_offset_y", 10.0) or 10.0),
        }
        host._preview_controls_legend_last_collapsed_offset = dict(collapsed_anchor)
    else:
        stored_anchor = getattr(host, "_preview_controls_legend_last_collapsed_offset", None)
        if isinstance(stored_anchor, dict):
            collapsed_anchor = dict(stored_anchor)

    if bool(getattr(host, "_preview_fullscreen_active", False)):
        host._preview_controls_legend_fullscreen_expanded = not bool(
            getattr(host, "_preview_controls_legend_fullscreen_expanded", False)
        )
    else:
        host._preview_controls_legend_inline_expanded = not bool(
            getattr(host, "_preview_controls_legend_inline_expanded", False)
        )
    place_preview_hint_overlay(host, refresh=True)
    if was_expanded and isinstance(collapsed_anchor, dict):
        try:
            host._preview_controls_legend_offset_x = float(collapsed_anchor.get("x", 10.0))
            host._preview_controls_legend_offset_y = float(collapsed_anchor.get("y", 10.0))
            place_preview_hint_overlay(host, refresh=False)
        except Exception:
            pass
    return "break"


def update_preview_controls_legend_cursor(
    host: "CharacterAnnotationTab",
    local_x: float | None = None,
    local_y: float | None = None,
):
    cursor = "hand2"
    if isinstance(getattr(host, "_preview_controls_legend_drag_state", None), dict):
        cursor = "fleur"
    elif local_x is not None and local_y is not None and host._is_preview_controls_legend_grab_hit(local_x, local_y):
        cursor = "fleur"
    for widget_name in ("preview_hint_frame", "preview_controls_canvas"):
        widget = getattr(host, widget_name, None)
        if widget is None:
            continue
        try:
            widget.configure(cursor=cursor)
        except Exception:
            pass


def on_preview_controls_legend_press(host: "CharacterAnnotationTab", event=None):
    if event is None:
        return None
    try:
        local_x = float(getattr(event, "x", 0.0) or 0.0)
        local_y = float(getattr(event, "y", 0.0) or 0.0)
        root_x = float(getattr(event, "x_root", 0.0) or 0.0)
        root_y = float(getattr(event, "y_root", 0.0) or 0.0)
    except Exception:
        return "break"
    if host._is_preview_controls_legend_grab_hit(local_x, local_y):
        host._preview_controls_legend_drag_state = {
            "press_root_x": root_x,
            "press_root_y": root_y,
            "start_x": float(getattr(host, "_preview_controls_legend_offset_x", 10.0) or 10.0),
            "start_y": float(getattr(host, "_preview_controls_legend_offset_y", 10.0) or 10.0),
        }
        host._preview_controls_legend_click_state = None
        update_preview_controls_legend_cursor(host, local_x, local_y)
        return "break"
    host._preview_controls_legend_drag_state = None
    host._preview_controls_legend_click_state = {
        "press_root_x": root_x,
        "press_root_y": root_y,
    }
    return "break"


def on_preview_controls_legend_drag(host: "CharacterAnnotationTab", event=None):
    drag_state = getattr(host, "_preview_controls_legend_drag_state", None)
    if not isinstance(drag_state, dict) or event is None:
        return None
    try:
        root_x = float(getattr(event, "x_root", 0.0) or 0.0)
        root_y = float(getattr(event, "y_root", 0.0) or 0.0)
    except Exception:
        return "break"
    next_x = float(drag_state.get("start_x", 10.0)) + (root_x - float(drag_state.get("press_root_x", root_x)))
    next_y = float(drag_state.get("start_y", 10.0)) + (root_y - float(drag_state.get("press_root_y", root_y)))
    clamped_x, clamped_y = clamp_preview_controls_legend_offsets(host, next_x, next_y)
    host._preview_controls_legend_offset_x = clamped_x
    host._preview_controls_legend_offset_y = clamped_y
    place_preview_hint_overlay(host, refresh=False)
    return "break"


def on_preview_controls_legend_motion(host: "CharacterAnnotationTab", event=None):
    if event is None:
        return None
    try:
        update_preview_controls_legend_cursor(
            host,
            float(getattr(event, "x", 0.0) or 0.0),
            float(getattr(event, "y", 0.0) or 0.0),
        )
    except Exception:
        update_preview_controls_legend_cursor(host)
    return None


def on_preview_controls_legend_leave(host: "CharacterAnnotationTab", event=None):
    for widget_name in ("preview_hint_frame", "preview_controls_canvas"):
        widget = getattr(host, widget_name, None)
        if widget is None:
            continue
        try:
            widget.configure(cursor="arrow")
        except Exception:
            pass
    return None


def on_preview_controls_legend_release(host: "CharacterAnnotationTab", event=None):
    drag_state = getattr(host, "_preview_controls_legend_drag_state", None)
    click_state = getattr(host, "_preview_controls_legend_click_state", None)
    host._preview_controls_legend_drag_state = None
    host._preview_controls_legend_click_state = None
    update_preview_controls_legend_cursor(host)
    if isinstance(drag_state, dict):
        return "break"
    if not isinstance(click_state, dict) or event is None:
        return None
    try:
        root_x = float(getattr(event, "x_root", 0.0) or 0.0)
        root_y = float(getattr(event, "y_root", 0.0) or 0.0)
    except Exception:
        return "break"
    if abs(root_x - float(click_state.get("press_root_x", root_x))) > 4.0 or abs(root_y - float(click_state.get("press_root_y", root_y))) > 4.0:
        return "break"
    return toggle_preview_controls_legend(host, event)


def on_preview_controls_legend_mousewheel(host: "CharacterAnnotationTab", event=None):
    canvas = getattr(host, "preview_controls_canvas", None)
    if canvas is None or event is None:
        return None
    try:
        content_h = float(getattr(host, "_preview_controls_legend_content_height", 0.0) or 0.0)
        visible_h = float(getattr(host, "_preview_controls_legend_current_height", 0.0) or 0.0)
        if content_h <= visible_h + 1.0:
            return None
    except Exception:
        return None

    delta_units = 0
    try:
        if hasattr(event, "delta") and int(getattr(event, "delta", 0) or 0) != 0:
            delta_units = -1 if int(event.delta) > 0 else 1
        else:
            num = int(getattr(event, "num", 0) or 0)
            if num == 4:
                delta_units = -1
            elif num == 5:
                delta_units = 1
    except Exception:
        delta_units = 0
    if delta_units == 0:
        return None
    try:
        canvas.yview_scroll(delta_units, "units")
        return "break"
    except Exception:
        return None


def build_preview_legend_sections(host: "CharacterAnnotationTab"):
    return [
        {
            "title": "Nawigacja",
            "accent": "#2f80ed",
            "items": [
                {"tokens": ["Q", "E"], "connector": "/", "label": "poprz./nast. tablica"},
                {"tokens": ["F"], "label": "tablica do okna"},
                {"tokens": ["Rolka"], "label": "zoom in / out"},
                {"tokens": ["Enter"], "label": "pełny ekran / wyjście"},
            ],
        },
        {
            "title": "Boxy",
            "accent": "#22c55e",
            "items": [
                {"tokens": ["D", "LPM"], "connector": "+", "label": "nowy box"},
                {"tokens": ["S"], "label": "select / off"},
                {"tokens": ["LPM"], "label": "przesuń lub resize"},
                {"tokens": ["PPM"], "label": "usuń aktywny"},
                {"tokens": ["Ctrl+Z", "Ctrl+Y"], "connector": "/", "label": "historia"},
            ],
        },
        {
            "title": "Znaki",
            "accent": "#f59e0b",
            "items": [
                {"tokens": ["Alt+W"], "label": "tryb wpisywania"},
                {"tokens": ["LPM"], "label": "wybierz pole"},
                {"tokens": ["←", "→"], "connector": "/", "label": "pole +/-"},
                {"tokens": ["0-9/A-Z"], "label": "wpisz znak"},
                {"tokens": ["Esc"], "label": "wyjdz z wpisywania"},
            ],
        },
    ]


def refresh_preview_controls_legend(host: "CharacterAnnotationTab"):
    canvas = getattr(host, "preview_controls_canvas", None)
    if canvas is None:
        return

    try:
        canvas.update_idletasks()
    except Exception:
        pass

    expanded = host._is_preview_controls_legend_expanded()
    fullscreen = bool(getattr(host, "_preview_fullscreen_active", False))
    compact = not bool(expanded)
    min_width = 30.0 if compact else 220.0
    try:
        configured_width = float(canvas.cget("width") or 0.0)
    except Exception:
        configured_width = 0.0
    if compact:
        width = max(min_width, configured_width)
    else:
        width = max(min_width, float(canvas.winfo_width() or configured_width or 0.0))
    canvas.delete("all")
    legend_theme = host._get_preview_legend_theme()
    bg_fill = legend_theme["panel_fill"]
    bg_outline = legend_theme["panel_outline"]
    plus_fill = legend_theme["muted_fill"]
    try:
        canvas.configure(bg=legend_theme["canvas_bg"])
    except Exception:
        pass

    host._preview_controls_legend_grab_bbox = None
    background_height = 30.0 if compact else 72.0
    if compact:
        bg_outline = str(legend_theme.get("badge_plate_outline", "#2fbf71"))
    background_id = canvas.create_rectangle(
        1,
        1,
        width - (1 if compact else 2),
        background_height - (1 if compact else 0),
        fill=bg_fill,
        outline=bg_outline,
        width=(2 if compact else 1),
        tags=("preview_legend",)
    )
    toggle_x = 3.0 if compact else 12.0
    toggle_y = 3.0 if compact else 8.0
    toggle_w, toggle_h = host._draw_preview_legend_compass_toggle(
        canvas,
        toggle_x,
        toggle_y,
        expanded=expanded,
        theme=legend_theme,
    )
    if not compact and not fullscreen:
        host._draw_preview_legend_grab_handle(
            canvas,
            max(12.0, width - 28.0),
            10.0,
            theme=legend_theme,
        )
    current_y = toggle_y + toggle_h + (6.0 if compact else 8.0)

    if expanded:
        sections = build_preview_legend_sections(host)
        outer_pad_x = 14.0
        outer_pad_y = current_y + 4.0
        section_gap_x = 10.0
        section_gap_y = 8.0
        section_pad_x = 10.0
        section_pad_y = 8.0
        title_gap_y = 6.0
        item_gap_y = 6.0
        token_gap = 5.0
        label_gap_x = 8.0
        item_row_height = 22.0
        title_font = host._get_preview_legend_font(8, "bold")
        desc_font = host._get_preview_legend_font(8, "bold")

        if width >= 920.0:
            column_count = 3
        elif width >= 620.0:
            column_count = 2
        else:
            column_count = 1

        column_count = max(1, min(column_count, len(sections)))
        section_width = max(
            180.0,
            (width - (outer_pad_x * 2.0) - (section_gap_x * (column_count - 1))) / float(column_count),
        )

        section_heights = []
        for section in sections:
            item_count = len(section.get("items", []))
            section_height = (
                section_pad_y
                + float(title_font.metrics("linespace"))
                + title_gap_y
                + max(1, item_count) * item_row_height
                + max(0, item_count - 1) * item_gap_y
                + section_pad_y
            )
            section_heights.append(section_height)

        row_heights = []
        for start_idx in range(0, len(sections), column_count):
            row_heights.append(max(section_heights[start_idx:start_idx + column_count]))

        y_offsets = []
        y_cursor = outer_pad_y
        for row_height in row_heights:
            y_offsets.append(y_cursor)
            y_cursor += row_height + section_gap_y

        max_bottom = current_y
        for idx, section in enumerate(sections):
            row_idx = idx // column_count
            col_idx = idx % column_count
            section_x = outer_pad_x + (col_idx * (section_width + section_gap_x))
            section_y = y_offsets[row_idx]
            section_height = section_heights[idx]
            accent = str(section.get("accent", "#3498db"))

            section_rect = canvas.create_rectangle(
                section_x,
                section_y,
                section_x + section_width,
                section_y + section_height,
                fill=legend_theme["section_fill"],
                outline=accent,
                width=1,
                tags=("preview_legend",)
            )
            canvas.tag_lower(section_rect)

            canvas.create_text(
                section_x + section_pad_x,
                section_y + section_pad_y,
                text=str(section.get("title", "")),
                fill=legend_theme["section_title"],
                anchor="nw",
                font=title_font,
                tags=("preview_legend",)
            )

            item_y = section_y + section_pad_y + float(title_font.metrics("linespace")) + title_gap_y
            for item in section.get("items", []):
                tokens = [str(token) for token in item.get("tokens", [])]
                connector = str(item.get("connector", "") or "")
                label = str(item.get("label", "") or "")
                token_x = section_x + section_pad_x
                prev_right = None

                for token_idx, token_text in enumerate(tokens):
                    if token_idx > 0 and connector:
                        connector_x = float(prev_right) + (token_gap / 2.0)
                        canvas.create_text(
                            connector_x,
                            item_y + 10.0,
                            text=connector,
                            fill=plus_fill,
                            anchor="center",
                            font=host._get_preview_legend_font(7, "bold"),
                            tags=("preview_legend",)
                        )
                    token_w, _token_h = host._draw_preview_legend_keycap(
                        canvas,
                        token_x,
                        item_y,
                        token_text,
                        fill=legend_theme["token_fill"],
                        outline=accent,
                        text_fill=legend_theme["token_text"],
                    )
                    prev_right = token_x + float(token_w)
                    if token_idx < (len(tokens) - 1):
                        token_x = prev_right + token_gap

                label_x = min(
                    section_x + section_width - section_pad_x - 56.0,
                    max(section_x + section_pad_x + 88.0, float(prev_right or token_x) + label_gap_x),
                )
                canvas.create_text(
                    label_x,
                    item_y + 10.0,
                    text=label,
                    fill=legend_theme["section_muted"],
                    anchor="w",
                    width=max(48.0, (section_x + section_width - section_pad_x) - label_x),
                    font=desc_font,
                    tags=("preview_legend",)
                )
                item_y += item_row_height + item_gap_y

            max_bottom = max(max_bottom, section_y + section_height)

        total_height = max(92.0, max_bottom + 12.0)
    else:
        total_height = max((30.0 if compact else 56.0), current_y + 4.0)
    canvas.coords(
        background_id,
        1,
        1,
        width - (1 if compact else 2),
        total_height - (1 if compact else 2),
    )
    try:
        canvas.configure(scrollregion=(0, 0, int(max(1.0, width)), int(max(1.0, total_height))))
    except Exception:
        pass
    host._preview_controls_legend_current_width = float(width)
    host._preview_controls_legend_content_height = float(total_height)
    try:
        host.frame.after_idle(host._place_preview_hint_overlay)
    except Exception:
        pass

def place_preview_hint_overlay(host: "CharacterAnnotationTab", refresh: bool = False):
    host_widget = getattr(host, "preview_canvas_host", None)
    overlay = getattr(host, "preview_hint_frame", None)
    canvas = getattr(host, "preview_controls_canvas", None)
    vbar = getattr(host, "preview_controls_vbar", None)
    if host_widget is None or overlay is None or canvas is None:
        return
    if not bool(getattr(host, "_preview_controls_legend_visible", True)):
        try:
            overlay.place_forget()
        except Exception:
            pass
        return

    try:
        host_widget.update_idletasks()
    except Exception:
        pass

    host_width = max(0, int(host_widget.winfo_width() or 0))
    host_height = max(0, int(host_widget.winfo_height() or 0))
    if host_width <= 0 or host_height <= 0:
        return

    expanded = host._is_preview_controls_legend_expanded()
    fullscreen = bool(getattr(host, "_preview_fullscreen_active", False))
    compact = not bool(expanded)
    if compact:
        target_width = max(30, min(30, host_width - 20))
    elif fullscreen:
        target_width = max(220, min(520, host_width - 24))
    else:
        target_width = max(220, min((620 if expanded else 340), host_width - 20))
    try:
        canvas.configure(width=int(target_width))
    except Exception:
        pass

    if refresh:
        try:
            host._refresh_preview_controls_legend()
        except Exception:
            pass
    try:
        canvas.update_idletasks()
    except Exception:
        pass

    min_overlay_width = 30.0 if compact else 220.0
    if compact:
        try:
            configured_width = float(canvas.cget("width") or 0.0)
        except Exception:
            configured_width = 0.0
        overlay_width = max(min_overlay_width, configured_width or float(target_width))
    else:
        overlay_width = max(
            min_overlay_width,
            float(
                getattr(host, "_preview_controls_legend_current_width", 0.0)
                or canvas.winfo_width()
                or target_width
            ),
        )
    min_content_height = 30.0 if compact else 56.0
    content_height = max(
        min_content_height,
        float(
            getattr(host, "_preview_controls_legend_content_height", 0.0)
            or getattr(host, "_preview_controls_legend_current_height", 0.0)
            or canvas.winfo_height()
            or min_content_height
        ),
    )
    top_clearance = 0.0
    if bool(getattr(host, "_preview_fullscreen_active", False)) or bool(getattr(host, "_preview_render_state", None)):
        top_clearance = max(38.0, float(getattr(host, "_preview_overlay_top_bar_height", 38.0) or 38.0)) + 8.0
    max_visible_height = max(56.0, float(host_height) - top_clearance - 10.0)
    overlay_height = min(content_height, max_visible_height)
    dock = getattr(host, "preview_overlay_dock", None)
    dock_mapped = False
    dock_x = dock_y = dock_w = dock_h = 0.0
    if dock is not None and str(dock.winfo_manager()):
        try:
            dock.update_idletasks()
            dock_x = float(dock.winfo_x() or 0.0)
            dock_y = float(dock.winfo_y() or 0.0)
            dock_w = float(dock.winfo_width() or dock.winfo_reqwidth() or 0.0)
            dock_h = float(dock.winfo_height() or dock.winfo_reqheight() or 0.0)
            dock_mapped = dock_w > 0.0 and dock_h > 0.0
        except Exception:
            dock_mapped = False
    if fullscreen:
        margin = 12.0
        if dock_mapped:
            offset_x = dock_x + dock_w - float(overlay_width)
            offset_y = dock_y + dock_h + 6.0
        else:
            toggle_rect = getattr(host, "_preview_fullscreen_toggle_rect", None)
            if isinstance(toggle_rect, tuple) and len(toggle_rect) == 4:
                try:
                    _icon_x1, _icon_y1, icon_x2, icon_y2 = [float(value) for value in toggle_rect]
                    offset_x = icon_x2 - float(overlay_width)
                    offset_y = icon_y2 + 6.0
                except Exception:
                    offset_x = float(host_width) - float(overlay_width) - margin
                    offset_y = top_clearance + 6.0
            else:
                offset_x = float(host_width) - float(overlay_width) - margin
                offset_y = top_clearance + 6.0
        offset_x = min(max(margin, offset_x), max(margin, float(host_width) - float(overlay_width) - margin))
        offset_y = min(max(top_clearance + 4.0, offset_y), max(top_clearance + 4.0, float(host_height) - float(overlay_height) - margin))
    else:
        if dock_mapped:
            margin = 12.0
            offset_x = dock_x + dock_w - float(overlay_width)
            offset_y = dock_y + dock_h + 6.0
            offset_x = min(max(margin, offset_x), max(margin, float(host_width) - float(overlay_width) - margin))
            offset_y = min(max(margin, offset_y), max(margin, float(host_height) - float(overlay_height) - margin))
        else:
            offset_x = float(getattr(host, "_preview_controls_legend_offset_x", 10.0) or 10.0)
            offset_y = float(getattr(host, "_preview_controls_legend_offset_y", 10.0) or 10.0)
            offset_x, offset_y = clamp_preview_controls_legend_offsets(
                host,
                offset_x,
                offset_y,
                width=overlay_width,
                height=overlay_height,
            )
            host._preview_controls_legend_offset_x = float(offset_x)
            host._preview_controls_legend_offset_y = float(offset_y)
    host._preview_controls_legend_current_height = float(overlay_height)

    try:
        canvas.configure(height=int(math.ceil(overlay_height)))
        if content_height > overlay_height + 1.0:
            if vbar is not None and not str(vbar.winfo_manager()):
                vbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        else:
            if vbar is not None and str(vbar.winfo_manager()):
                vbar.grid_remove()
            canvas.yview_moveto(0.0)
    except Exception:
        pass

    try:
        overlay.place(
            in_=host_widget,
            x=int(round(offset_x)),
            y=int(round(offset_y)),
            width=int(math.ceil(overlay_width)),
            height=int(math.ceil(overlay_height)),
            anchor="nw",
        )
        overlay.lift()
    except Exception:
        pass


def apply_preview_fullscreen_chrome(host: "CharacterAnnotationTab"):
    preview_tools = getattr(host, "preview_tools", None)
    tools_hidden_by_design = bool(getattr(host, "_preview_tools_hidden_by_design", False))

    if bool(getattr(host, "_preview_fullscreen_active", False)):
        try:
            if preview_tools is not None:
                preview_tools.grid_remove()
        except Exception:
            pass
        try:
            host._place_preview_overlay_dock(force_render=True)
        except Exception:
            pass
        try:
            place_preview_hint_overlay(host, refresh=True)
        except Exception:
            pass
        host._sync_preview_edit_status_visibility()
        host._refresh_preview_typing_overlay_visibility()
        return

    try:
        if preview_tools is not None:
            if tools_hidden_by_design:
                preview_tools.grid_remove()
            else:
                preview_tools.grid()
    except Exception:
        pass
    try:
        host._place_preview_overlay_dock(force_render=True)
    except Exception:
        pass
    try:
        place_preview_hint_overlay(host, refresh=True)
    except Exception:
        pass
    host._sync_preview_edit_status_visibility()
    host._refresh_preview_typing_overlay_visibility()


def update_preview_toolbar_state(host: "CharacterAnnotationTab"):
    total = len(getattr(host, "_listbox_pid_by_index", []))
    current_idx = host._get_current_preview_list_index()
    has_selection = current_idx is not None and total > 0
    has_image = bool(getattr(host, "_preview_render_state", None))
    can_go_prev = has_selection and int(current_idx) > 0
    can_go_next = has_selection and int(current_idx) < (total - 1)

    button_specs = (
        ("preview_prev_btn", can_go_prev),
        ("preview_next_btn", can_go_next),
        ("preview_fit_btn", has_image),
        ("preview_fullscreen_btn", has_image),
    )
    for attr_name, enabled in button_specs:
        widget = getattr(host, attr_name, None)
        if widget is None:
            continue
        try:
            widget.configure(state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    fullscreen_btn = getattr(host, "preview_fullscreen_btn", None)
    if fullscreen_btn is not None:
        try:
            fullscreen_btn.configure(
                text=("Wyjdź z pełnego ekranu (Enter)" if host._preview_fullscreen_active else "Pełny ekran (Enter)")
            )
        except Exception:
            pass
