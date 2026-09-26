"""Text-only plate context, anchored to the canvas in both preview modes."""
from pathlib import Path
import tkinter.font as tkfont

from .z2_inline_hud import fit_text


def resolve_inline_hud_plate_status(host, data: dict | None) -> tuple[str, str]:
    source = data if isinstance(data, dict) else {}
    palette = getattr(getattr(host, "app", None), "palette", {}) or {}

    gold_state = source.get("gold_state")
    if isinstance(gold_state, dict) and bool(gold_state.get("excluded", False)):
        return "N", str(palette.get("muted", "#8b949e"))

    chars = source.get("characters", [])
    if not isinstance(chars, list):
        chars = []

    try:
        presentation = host._get_preview_status_presentation(
            data=source,
            chars=chars,
            plate_id=str(
                source.get("plate_id", "")
                or getattr(host, "_preview_active_pid", "")
                or ""
            ),
        )
    except Exception:
        presentation = {}

    status = str(
        presentation.get("status", source.get("status", "unknown")) or "unknown"
    ).strip().lower()
    ready = bool(presentation.get("ready_for_approval", False))

    if status == "perfect":
        return "OK", str(palette.get("success", "#27ae60"))
    if ready:
        return "ZATWIERDŹ", str(palette.get("model_role_vehicle", "#3b82f6"))

    return "DO KOREKTY", str(palette.get("error", "#c0392b"))


def apply_inline_hud_plate_status(items, status_text: str, status_color: str):
    prepared = [dict(item) for item in list(items or [])]
    for item in prepared:
        if str(item.get("text", "") or "").startswith("Status tablicy:"):
            item["text"] = f"Status tablicy: {status_text}"
            item["outline"] = str(status_color)
            break
    return prepared


def plan_inline_hud(host, width, data, status_layout):
    fonts = getattr(host, "_preview_inline_hud_fonts", None)
    if fonts is None:
        fonts = (tkfont.Font(host.frame, family="Segoe UI", size=14, weight="bold"),
                 tkfont.Font(host.frame, family="Segoe UI", size=11, weight="bold"))
        host._preview_inline_hud_fonts = fonts
    file_font, count_font = fonts
    data = data if isinstance(data, dict) else {}
    index = host._get_current_preview_list_index()
    total = len(getattr(host, "_listbox_pid_by_index", []) or [])
    number = int(index) + 1 if index is not None and total else 0
    prefix = f"{number:0{max(2, len(str(total)))}d}. "
    filename = Path(str(data.get("source_image") or "")).name or str(data.get("plate_id") or "Brak pliku")
    left, top, right = 12, 8, max(60, width - 12)
    file_limit = max(20, right - 80 - left - file_font.measure(prefix))
    lines = [(prefix, left, top, file_font, "#ffd166", ("preview_inline_hud_number",)),
             (fit_text(filename, file_font, file_limit), left + file_font.measure(prefix), top,
              file_font, "#7ee7ff", ("preview_inline_hud_filename", "preview_overlay_action",
                                     "preview_action::edit_source_filename"))]
    attrs = data.get("plate_attributes")
    attrs = attrs if isinstance(attrs, dict) else {}
    number_source = str(
        data.get("ground_truth_source")
        or attrs.get("ground_truth_source")
        or ""
    ).strip().lower()
    try:
        saved_number = str(host._get_preview_ground_truth_text(data) or "").strip()
    except Exception:
        saved_number = str(
            data.get("ground_truth_text")
            or attrs.get("ground_truth_text")
            or ""
        ).strip()

    if saved_number and number_source == "manual_z2":
        number_text = f"Numer z Z2: {saved_number} · kliknij, aby zmienić"
    elif saved_number:
        number_text = f"Zapisany numer: {saved_number} · kliknij, aby zmienić"
    else:
        number_text = "Numer: brak · O zapisze"

    palette = getattr(getattr(host, "app", None), "palette", {}) or {}
    items = [
        {"text": f"Tablica {number}/{total}", "outline": "#b6f5ce"},
        {
            "text": number_text,
            "outline": str(palette.get("accent_alt", "#7ee7ff")),
            "tags": (
                "preview_overlay_action",
                "preview_action::edit_plate_gt",
            ),
        },
    ]
    items.extend(dict(item) for item in status_layout.get("neutral_badges", []))
    items.extend(dict(item) for item in status_layout.get("badges", []))

    hud_status, hud_color = resolve_inline_hud_plate_status(host, data)
    items = apply_inline_hud_plate_status(items, hud_status, hud_color)

    x, y = left, top + file_font.metrics("linespace") + 5
    row_height = count_font.metrics("linespace") + 5
    for item in items:
        text = fit_text(item["text"], count_font, right - left)
        text_width = count_font.measure(text)
        if x > left and x + text_width > right:
            x, y = left, y + row_height
        tags = tuple(item.get("tags", ())) + ("preview_inline_hud_counts",)
        lines.append((text, x, y, count_font, item.get("outline", "#b6f5ce"), tags))
        x += text_width + 20
    return {"lines": lines, "bar_height": float(y + row_height + 6)}


def draw_inline_hud(host, canvas, plan):
    for text, x, y, font, color, extra_tags in plan["lines"]:
        tags = ("preview_overlay", "preview_inline_hud") + extra_tags
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            canvas.create_text(x + dx, y + dy, anchor="nw", text=text, font=font,
                               fill="#101820", tags=tags + ("preview_inline_hud_outline",))
        canvas.create_text(x, y, anchor="nw", text=text, font=font, fill=color, tags=tags)
    host._preview_hud_bottom_in_view = plan["bar_height"]
