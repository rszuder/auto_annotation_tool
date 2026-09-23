"""Compact, wrapping provenance legend outside the zoomable plate canvas."""

import tkinter as tk
from tkinter import font as tkfont

from .z3_preview_badges import get_preview_badge_component_style


class CharacterBadgeLegend(tk.Canvas):
    COMPONENTS = (
        "yolo_box", "generated_box", "manual_box",
        "yolo_symbol", "ocr_symbol", "manual_sign", "gt_assisted",
    )

    def __init__(self, parent, host):
        super().__init__(parent, background="#1e1e1e", height=28, width=1,
                         bd=0, highlightthickness=0, takefocus=0)
        self.host = host
        self._badge_font = tkfont.Font(root=self, family="Segoe UI", size=9, weight="bold")
        self._label_font = tkfont.Font(root=self, family="Segoe UI", size=9)
        self._last_width = None
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        if event.width != self._last_width:
            self.refresh()

    def refresh(self):
        width = max(1, self.winfo_width())
        self._last_width = width
        self.delete("all")
        x, y, margin, gap = 8, 5, 8, 14
        row_height = max(self._badge_font.metrics("linespace"), self._label_font.metrics("linespace")) + 8
        for component in self.COMPONENTS:
            style = get_preview_badge_component_style(self.host, component)
            badge_width = self._badge_font.measure(style["label"]) + 10
            label_width = self._label_font.measure(style["legend"])
            item_width = badge_width + 5 + label_width
            if x > margin and x + item_width > width - margin:
                x, y = margin, y + row_height
            tags = ("legend_item", component)
            self.create_rectangle(x, y, x + badge_width, y + row_height - 4,
                                  fill=style["badge_fill"], outline=style["badge_outline"], tags=tags)
            self.create_text(x + badge_width / 2, y + (row_height - 4) / 2,
                             text=style["label"], fill=style["badge_fg"],
                             font=self._badge_font, tags=tags)
            self.create_text(x + badge_width + 5, y + (row_height - 4) / 2,
                             text=style["legend"], fill="#e1e3e8", font=self._label_font,
                             anchor="w", tags=tags)
            x += item_width + gap
        hint = "Liczba 0–1: pewność modelu"
        if x > margin and x + self._label_font.measure(hint) > width - margin:
            x, y = margin, y + row_height
        self.create_text(x, y + (row_height - 4) / 2, text=hint, fill="#bfc4cc",
                         font=self._label_font, anchor="w", tags="legend_hint")
        self.configure(height=y + row_height + 1)
