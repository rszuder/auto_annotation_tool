"""Text-only plate context, anchored to the canvas in both preview modes."""
from pathlib import Path
import tkinter.font as tkfont

from .z2_inline_hud import fit_text


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
    items = [{"text": f"Tablica {number}/{total}", "outline": "#b6f5ce"}]
    items.extend(status_layout.get("neutral_badges", []))
    items.extend(status_layout.get("badges", []))
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
