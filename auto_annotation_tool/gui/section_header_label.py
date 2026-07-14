#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wspolny naglowek sekcji z gradientem wygasajacym do koloru tla motywu.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from .web_slim_scrollbar import blend_hex_colors


class SectionHeaderLabel(tk.Canvas):
    def __init__(
        self,
        master,
        app,
        *,
        text: str = "",
        font=("Segoe UI", 10, "bold"),
        padx: int = 12,
        pady: int = 2,
        fade_ratio: float = 0.78,
        min_height: int = 26,
        **kwargs,
    ):
        self.app = app
        self._text = str(text or "")
        self._font = font
        self._padx = max(0, int(padx))
        self._pady = max(0, int(pady))
        self._fade_ratio = max(0.25, min(1.0, float(fade_ratio)))
        self._min_height = max(18, int(min_height))
        self._background_image = None
        self._background_size = (0, 0)
        self._render_after_id = None

        palette = getattr(self.app, "palette", {})
        kwargs.setdefault("bg", palette.get("panel", "#252526"))
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("relief", tk.FLAT)
        kwargs.setdefault("takefocus", 0)
        kwargs.setdefault("height", self._get_target_height())

        super().__init__(master, **kwargs)

        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._text_item = self.create_text(
            self._padx,
            max(1, self._pady),
            anchor="nw",
            text=self._text,
            font=self._font,
        )

        self.bind("<Configure>", lambda _event: self._schedule_render(), add="+")
        self._schedule_render()

    @staticmethod
    def _hex_to_rgb(color: str) -> tuple[int, int, int]:
        value = str(color or "").strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        if len(value) != 6:
            return (0, 0, 0)
        try:
            return tuple(int(value[idx:idx + 2], 16) for idx in (0, 2, 4))
        except Exception:
            return (0, 0, 0)

    @classmethod
    def _relative_luminance(cls, color: str) -> float:
        red, green, blue = cls._hex_to_rgb(color)
        return ((0.2126 * red) + (0.7152 * green) + (0.0722 * blue)) / 255.0

    def _get_font_object(self):
        try:
            return tkfont.Font(font=self._font)
        except Exception:
            return tkfont.nametofont("TkDefaultFont")

    def _get_target_height(self) -> int:
        try:
            font_obj = self._get_font_object()
            line_height = int(font_obj.metrics("linespace") or 0)
        except Exception:
            line_height = 16
        return max(self._min_height, line_height + (self._pady * 2) + 2)

    def _get_colors(self) -> tuple[str, str, str]:
        palette = getattr(self.app, "palette", {})
        panel = palette.get("panel", palette.get("bg", "#252526"))
        success = palette.get("success", "#4ec9b0")
        surface_success = palette.get("surface_success", blend_hex_colors(success, panel, 0.82))
        panel_luminance = self._relative_luminance(panel)
        gradient_strength = 0.62 if panel_luminance < 0.68 else 0.34
        gradient_start = blend_hex_colors(surface_success, success, gradient_strength)
        # Probe the color close to the left edge because the caption starts there.
        text_probe = blend_hex_colors(gradient_start, panel, 0.12 if panel_luminance >= 0.68 else 0.28)
        if self._relative_luminance(text_probe) >= 0.57:
            text_color = palette.get("guide_text", palette.get("fg", "#1f1f1f"))
        else:
            text_color = palette.get("accent_text", "#ffffff")
        return panel, gradient_start, text_color

    def _cancel_pending_render(self):
        pending = self._render_after_id
        if pending is None:
            return
        try:
            self.after_cancel(pending)
        except Exception:
            pass
        self._render_after_id = None

    def _schedule_render(self, force: bool = False):
        if force:
            self._cancel_pending_render()
            try:
                if self.winfo_exists():
                    self._render()
            except Exception:
                pass
            return
        if self._render_after_id is not None:
            return
        try:
            self._render_after_id = self.after_idle(self._render)
        except Exception:
            self._render_after_id = None

    def _render(self):
        self._render_after_id = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        try:
            width = max(1, int(self.winfo_width() or self.winfo_reqwidth() or 1))
        except tk.TclError:
            return
        base_height = self._get_target_height()
        height = base_height
        panel, gradient_start, text_color = self._get_colors()

        try:
            super().configure(bg=panel)
        except Exception:
            pass

        if self._background_image is None or self._background_size != (width, height):
            self._background_image = tk.PhotoImage(master=self, width=width, height=height)
            self._background_size = (width, height)

        image = self._background_image
        try:
            image.blank()
            fade_width = max(1, min(width, int(round(float(width) * self._fade_ratio))))
            denominator = max(1, fade_width - 1)

            for x in range(width):
                if x >= fade_width:
                    column_color = panel
                else:
                    ratio = float(x) / float(denominator)
                    eased = ratio * ratio * (3.0 - (2.0 * ratio))
                    column_color = blend_hex_colors(gradient_start, panel, eased)
                image.put(str(column_color), to=(x, 0, x + 1, height))

                if height >= 3 and x < fade_width:
                    shine = max(0.0, 1.0 - (float(x) / float(denominator)))
                    shine = 0.24 * (shine ** 1.45)
                    if shine > 0.0:
                        row_color = blend_hex_colors(column_color, "#ffffff", shine)
                        image.put(str(row_color), to=(x, 1, x + 1, 2))
        except Exception:
            pass

        text_width = max(1, width - (self._padx * 2))
        try:
            self.itemconfigure(self._bg_item, image=image)
            self.coords(self._bg_item, 0, 0)
        except Exception:
            pass

        try:
            self.itemconfigure(
                self._text_item,
                text=self._text,
                fill=text_color,
                font=self._font,
                width=text_width,
            )
            self.coords(self._text_item, self._padx, self._pady)
        except Exception:
            pass

        try:
            bbox = self.bbox(self._text_item)
            if bbox:
                text_height = max(0, int(bbox[3]) - int(bbox[1]))
                height = max(base_height, text_height + (self._pady * 2) + 2)
        except Exception:
            height = base_height

        try:
            if int(self.cget("height") or 0) != height:
                super().configure(height=height)
        except Exception:
            pass

        try:
            if self._background_size != (width, height):
                self._background_image = tk.PhotoImage(master=self, width=width, height=height)
                self._background_size = (width, height)
                image = self._background_image
                image.blank()
                fade_width = max(1, min(width, int(round(float(width) * self._fade_ratio))))
                denominator = max(1, fade_width - 1)
                for x in range(width):
                    if x >= fade_width:
                        column_color = panel
                    else:
                        ratio = float(x) / float(denominator)
                        eased = ratio * ratio * (3.0 - (2.0 * ratio))
                        column_color = blend_hex_colors(gradient_start, panel, eased)
                    image.put(str(column_color), to=(x, 0, x + 1, height))
                    if height >= 3 and x < fade_width:
                        shine = max(0.0, 1.0 - (float(x) / float(denominator)))
                        shine = 0.24 * (shine ** 1.45)
                        if shine > 0.0:
                            row_color = blend_hex_colors(column_color, "#ffffff", shine)
                            image.put(str(row_color), to=(x, 1, x + 1, 2))
                self.itemconfigure(self._bg_item, image=image)
                self.coords(self._bg_item, 0, 0)
        except Exception:
            pass

    def apply_theme(self):
        self._schedule_render(force=True)

    def configure(self, cnf=None, **kwargs):
        if cnf is not None and not isinstance(cnf, dict):
            return super().configure(cnf, **kwargs)

        merged = {}
        if isinstance(cnf, dict):
            merged.update(cnf)
        merged.update(kwargs)

        if "text" in merged:
            self._text = str(merged.pop("text") or "")
        if "font" in merged:
            self._font = merged.pop("font")
        if "padx" in merged:
            self._padx = max(0, int(merged.pop("padx")))
        if "pady" in merged:
            self._pady = max(0, int(merged.pop("pady")))
        if "fade_ratio" in merged:
            self._fade_ratio = max(0.25, min(1.0, float(merged.pop("fade_ratio"))))

        result = super().configure(**merged) if merged else None
        self._schedule_render()
        return result

    config = configure

    def cget(self, key):
        normalized = str(key or "").strip().lower()
        if normalized == "text":
            return self._text
        if normalized == "font":
            return self._font
        if normalized == "padx":
            return self._padx
        if normalized == "pady":
            return self._pady
        if normalized == "fade_ratio":
            return self._fade_ratio
        return super().cget(key)

    def destroy(self):
        self._cancel_pending_render()
        super().destroy()
