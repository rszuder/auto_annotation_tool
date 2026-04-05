#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canvas z obsługą zoom'u i pan'u dla podglądu obrazów.
Zastosowanie: Podgląd w zakładce Prostowania Tablic.
"""

import math
import tkinter as tk
from types import SimpleNamespace
from PIL import Image, ImageTk


class ZoomableCanvas(tk.Canvas):
    """Canvas z obsługą zoom'u (kółko myszy) i pan'u (LPM + przeciąganie)."""
    
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        
        # Stan zoom'u
        self.zoom_level = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 5.0
        self.zoom_step = 1.15  # 15% na każde tik
        
        # Oryginalne dane
        self.original_image = None  # PIL Image
        self.photo_image = None     # ImageTk.PhotoImage
        self.image_id = None        # Canvas image ID
        self.overlay_renderer = None
        self.interaction_delegate = None
        self._render_region = None
        self._pan_buffered_move_active = False
        
        # Pan'u - przesuwanie widoku
        self.pan_data = {
            'x': 0,
            'y': 0,
            'press_x': None,
            'press_y': None
        }
        
        # Flaga pokazania tekstu Info
        self.show_info = True
        self.reset_shortcut_enabled = True
        
        # Bind'y zdarzeń - Zoom
        self.bind("<MouseWheel>", self._on_mousewheel)  # Windows
        self.bind("<Button-4>", self._on_mousewheel)     # Linux scroll up
        self.bind("<Button-5>", self._on_mousewheel)     # Linux scroll down
        
        # Bind'y - Pan (przeciąganie LPM)
        self.bind("<Button-1>", self._on_pan_press)
        self.bind("<B1-Motion>", self._on_pan_motion)
        self.bind("<ButtonRelease-1>", self._on_pan_release)
        
        # Bind'y - klawiatura
        self.bind("<Home>", self._on_reset_view)  # Home = reset zoom i pan
        self.bind("<r>", self._on_reset_view)     # r = reset
        self.bind("<i>", self._on_toggle_info)    # i = toggle info
        
        # Kursor
        self.current_cursor = "arrow"

    def _get_canvas_size(self):
        return (
            max(1, int(self.winfo_width() or 1)),
            max(1, int(self.winfo_height() or 1)),
        )

    def _get_full_image_size(self):
        if self.original_image is None:
            return 0.0, 0.0
        return (
            max(1.0, float(self.original_image.width) * float(self.zoom_level)),
            max(1.0, float(self.original_image.height) * float(self.zoom_level)),
        )

    def _clamp_origin(self, origin_x: float, origin_y: float):
        if self.original_image is None:
            return float(origin_x), float(origin_y)

        canvas_width, canvas_height = self._get_canvas_size()
        full_width, full_height = self._get_full_image_size()
        clamped_x = float(origin_x)
        clamped_y = float(origin_y)

        if full_width <= float(canvas_width):
            clamped_x = (float(canvas_width) - full_width) / 2.0
        else:
            min_x = float(canvas_width) - full_width
            clamped_x = min(0.0, max(min_x, clamped_x))

        if full_height <= float(canvas_height):
            clamped_y = (float(canvas_height) - full_height) / 2.0
        else:
            min_y = float(canvas_height) - full_height
            clamped_y = min(0.0, max(min_y, clamped_y))

        return clamped_x, clamped_y

    def _apply_clamped_pan(self):
        clamped_x, clamped_y = self._clamp_origin(
            float(self.pan_data.get('x', 0.0)),
            float(self.pan_data.get('y', 0.0)),
        )
        self.pan_data = {
            'x': float(clamped_x),
            'y': float(clamped_y),
            'press_x': self.pan_data.get('press_x'),
            'press_y': self.pan_data.get('press_y'),
        }
        return float(clamped_x), float(clamped_y)

    def _get_exact_visible_image_bounds(self):
        if self.original_image is None:
            return None

        canvas_width, canvas_height = self._get_canvas_size()
        zoom = max(1e-9, float(self.zoom_level))
        origin_x = float(self.pan_data.get('x', 0.0))
        origin_y = float(self.pan_data.get('y', 0.0))
        image_width = int(self.original_image.width)
        image_height = int(self.original_image.height)

        visible_left = max(0.0, (0.0 - origin_x) / zoom)
        visible_top = max(0.0, (0.0 - origin_y) / zoom)
        visible_right = min(float(image_width), (float(canvas_width) - origin_x) / zoom)
        visible_bottom = min(float(image_height), (float(canvas_height) - origin_y) / zoom)

        if visible_right <= visible_left or visible_bottom <= visible_top:
            return None

        return (
            float(visible_left),
            float(visible_top),
            float(visible_right),
            float(visible_bottom),
        )

    def _get_visible_image_region(self):
        if self.original_image is None:
            return None

        canvas_width, canvas_height = self._get_canvas_size()
        zoom = max(1e-9, float(self.zoom_level))
        origin_x = float(self.pan_data.get('x', 0.0))
        origin_y = float(self.pan_data.get('y', 0.0))
        image_width = int(self.original_image.width)
        image_height = int(self.original_image.height)

        exact_bounds = self._get_exact_visible_image_bounds()
        if exact_bounds is None:
            return None

        visible_left, visible_top, visible_right, visible_bottom = exact_bounds

        buffer_canvas_x = min(max(64.0, float(canvas_width) * 0.35), 240.0)
        buffer_canvas_y = min(max(64.0, float(canvas_height) * 0.35), 240.0)
        buffer_img_x = buffer_canvas_x / zoom
        buffer_img_y = buffer_canvas_y / zoom

        crop_left = max(0, int(math.floor(visible_left - buffer_img_x)))
        crop_top = max(0, int(math.floor(visible_top - buffer_img_y)))
        crop_right = min(image_width, int(math.ceil(visible_right + buffer_img_x)))
        crop_bottom = min(image_height, int(math.ceil(visible_bottom + buffer_img_y)))

        if crop_right <= crop_left or crop_bottom <= crop_top:
            return None

        return {
            "crop_box": (crop_left, crop_top, crop_right, crop_bottom),
            "draw_x": origin_x + (float(crop_left) * zoom),
            "draw_y": origin_y + (float(crop_top) * zoom),
            "draw_width": max(1, int(math.ceil((crop_right - crop_left) * zoom))),
            "draw_height": max(1, int(math.ceil((crop_bottom - crop_top) * zoom))),
            "visible_bounds": exact_bounds,
        }
    
    def set_image(self, pil_image):
        """Ustaw nowy obraz (PIL.Image) i wyczyść zoom/pan."""
        self.original_image = pil_image
        self.zoom_level = 1.0
        self.pan_data = {'x': 0, 'y': 0, 'press_x': None, 'press_y': None}
        self._update_display()

    def clear_image(self):
        """Wyczysc aktualny obraz i zresetuj stan widoku."""
        self.original_image = None
        self.photo_image = None
        self.image_id = None
        self._render_region = None
        self._pan_buffered_move_active = False
        self.zoom_level = 1.0
        self.pan_data = {'x': 0, 'y': 0, 'press_x': None, 'press_y': None}
        try:
            self.delete("all")
        except Exception:
            pass
        try:
            self.configure(scrollregion=(0, 0, 0, 0))
        except Exception:
            pass

    def set_overlay_renderer(self, renderer):
        """Ustaw callback rysujący overlay po wyrenderowaniu obrazu."""
        self.overlay_renderer = renderer
        if self.original_image is not None:
            self._update_display()

    def set_interaction_delegate(self, delegate):
        """Ustaw delegata przejmującego zdarzenia LPM przed domyślnym panem."""
        self.interaction_delegate = delegate

    def _delegate_interaction(self, action: str, event) -> bool:
        delegate = getattr(self, "interaction_delegate", None)
        if delegate is None:
            return False

        method = getattr(delegate, f"on_zoomable_canvas_{action}", None)
        if not callable(method):
            return False

        try:
            return bool(method(self, event))
        except Exception:
            return False

    def _delegate_blocks_pan(self, event) -> bool:
        return self._delegate_interaction("should_block_pan", event)

    def _normalize_pointer_event(self, event):
        raw_x = float(getattr(event, "x", 0.0) or 0.0)
        raw_y = float(getattr(event, "y", 0.0) or 0.0)
        norm_x = raw_x
        norm_y = raw_y
        corrected = False
        norm_source = "raw"
        root_x = 0.0
        root_y = 0.0
        event_local_x = None
        event_local_y = None
        pointer_local_x = None
        pointer_local_y = None

        try:
            root_x = float(self.winfo_rootx())
            root_y = float(self.winfo_rooty())
        except Exception:
            root_x = 0.0
            root_y = 0.0

        try:
            if hasattr(event, "x_root") and hasattr(event, "y_root"):
                event_local_x = float(getattr(event, "x_root", 0.0) or 0.0) - root_x
                event_local_y = float(getattr(event, "y_root", 0.0) or 0.0) - root_y
        except Exception:
            event_local_x = None
            event_local_y = None

        try:
            pointer_local_x = float(self.winfo_pointerx()) - root_x
            pointer_local_y = float(self.winfo_pointery()) - root_y
        except Exception:
            pointer_local_x = None
            pointer_local_y = None

        if pointer_local_x is not None and pointer_local_y is not None:
            if abs(pointer_local_x - raw_x) > 1.5 or abs(pointer_local_y - raw_y) > 1.5:
                norm_x = pointer_local_x
                norm_y = pointer_local_y
                corrected = True
                norm_source = "pointer"
        elif event_local_x is not None and event_local_y is not None:
            if abs(event_local_x - raw_x) > 1.5 or abs(event_local_y - raw_y) > 1.5:
                norm_x = event_local_x
                norm_y = event_local_y
                corrected = True
                norm_source = "event_root"

        data = {}
        try:
            data.update(getattr(event, "__dict__", {}) or {})
        except Exception:
            pass

        for attr in ("widget", "type", "state", "delta", "num", "x_root", "y_root"):
            if attr not in data and hasattr(event, attr):
                try:
                    data[attr] = getattr(event, attr)
                except Exception:
                    pass

        data["x"] = norm_x
        data["y"] = norm_y
        data["raw_x"] = raw_x
        data["raw_y"] = raw_y
        data["event_local_x"] = event_local_x
        data["event_local_y"] = event_local_y
        data["pointer_local_x"] = pointer_local_x
        data["pointer_local_y"] = pointer_local_y
        data["canvas_root_x"] = root_x
        data["canvas_root_y"] = root_y
        try:
            data["canvas_x"] = float(self.canvasx(norm_x))
            data["canvas_y"] = float(self.canvasy(norm_y))
            data["canvas_offset_x"] = float(data["canvas_x"] - norm_x)
            data["canvas_offset_y"] = float(data["canvas_y"] - norm_y)
        except Exception:
            data["canvas_x"] = norm_x
            data["canvas_y"] = norm_y
            data["canvas_offset_x"] = 0.0
            data["canvas_offset_y"] = 0.0
        data["norm_source"] = norm_source
        data["normalized_from_root"] = corrected
        return SimpleNamespace(**data)
    
    def _on_mousewheel(self, event):
        """Obsługa zoom'u kółkiem myszy."""
        if self.original_image is None:
            return

        event = self._normalize_pointer_event(event)
        anchor_x = float(getattr(event, "canvas_x", getattr(event, "x", 0.0)))
        anchor_y = float(getattr(event, "canvas_y", getattr(event, "y", 0.0)))
        img_x, img_y = self.canvas_to_image_coords(anchor_x, anchor_y, clamp=False)

        raw_delta = event.delta if hasattr(event, 'delta') else (-event.num + 5) * 120
        steps = max(1, int(abs(raw_delta) / 120)) if raw_delta else 1
        zoom_factor = float(self.zoom_step) ** steps

        if raw_delta < 0:
            new_zoom = float(self.zoom_level) / zoom_factor
        else:
            new_zoom = float(self.zoom_level) * zoom_factor

        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
        if abs(new_zoom - float(self.zoom_level)) < 1e-9:
            return

        self.zoom_level = new_zoom
        self.pan_data['x'] = anchor_x - (float(img_x) * float(self.zoom_level))
        self.pan_data['y'] = anchor_y - (float(img_y) * float(self.zoom_level))
        self._apply_clamped_pan()
        self._update_display()
        self._delegate_interaction("zoom", event)
    
    def _on_pan_press(self, event):
        """Początek przeciągania (naciśnięcie LPM)."""
        event = self._normalize_pointer_event(event)
        if self._delegate_interaction("press", event):
            return
        if self._delegate_blocks_pan(event):
            self.pan_data['press_x'] = None
            self.pan_data['press_y'] = None
            return

        self.pan_data['press_x'] = event.x
        self.pan_data['press_y'] = event.y
        self.config(cursor="hand2")
    
    def _on_pan_motion(self, event):
        """Przeciąganie widoku (ruch myszy z LPM)."""
        event = self._normalize_pointer_event(event)
        if self._delegate_interaction("drag", event):
            return
        if self._delegate_blocks_pan(event):
            self.pan_data['press_x'] = None
            self.pan_data['press_y'] = None
            return

        if self.pan_data['press_x'] is None:
            return
        
        # Oblicz deltę i przytnij ruch tak, aby obraz nie wypadal poza viewport.
        dx = float(event.x - self.pan_data['press_x'])
        dy = float(event.y - self.pan_data['press_y'])
        previous_x = float(self.pan_data.get('x', 0.0))
        previous_y = float(self.pan_data.get('y', 0.0))
        next_x, next_y = self._clamp_origin(previous_x + dx, previous_y + dy)
        applied_dx = float(next_x - previous_x)
        applied_dy = float(next_y - previous_y)
        self.pan_data['x'] = float(next_x)
        self.pan_data['y'] = float(next_y)

        # Aktualizuj pozycję
        self.pan_data['press_x'] = event.x
        self.pan_data['press_y'] = event.y

        if abs(applied_dx) < 1e-9 and abs(applied_dy) < 1e-9:
            return

        if not self._apply_buffered_pan_move(applied_dx, applied_dy):
            self._update_display()
    
    def _on_pan_release(self, event):
        """Koniec przeciągania (zwolnienie LPM)."""
        event = self._normalize_pointer_event(event)
        if self._delegate_interaction("release", event):
            return
        if self._delegate_blocks_pan(event):
            self.pan_data['press_x'] = None
            self.pan_data['press_y'] = None
            return

        self.pan_data['press_x'] = None
        self.pan_data['press_y'] = None
        self.config(cursor=self.current_cursor)
        if self._pan_buffered_move_active:
            self._update_display()
    
    def _on_reset_view(self, event):
        """Reset zoom i pan (naciśnięcie Home lub R)."""
        if event is not None and not bool(getattr(self, "reset_shortcut_enabled", True)):
            return
        self.zoom_level = 1.0
        self.pan_data = {'x': 0, 'y': 0, 'press_x': None, 'press_y': None}
        self._update_display()
    
    def _on_toggle_info(self, event):
        """Toggle wyświetlania tekstu info (naciśnięcie I)."""
        self.show_info = not self.show_info
        self._update_display()
    
    def _update_display(self):
        """Aktualizuj canvas z nowym zoom'em i pan'em."""
        if self.original_image is None:
            return
        self._update_display_visible_region()
        return
        
        # Skaluj obraz
        new_width = int(self.original_image.width * self.zoom_level)
        new_height = int(self.original_image.height * self.zoom_level)
        
        if new_width <= 0 or new_height <= 0:
            return
        
        # BILINEAR zapewnia płynniejszy zoom niż LANCZOS w interaktywnym podglądzie.
        scaled = self.original_image.resize(
            (new_width, new_height),
            Image.Resampling.BILINEAR
        )
        
        # Konwertuj do PhotoImage
        self.photo_image = ImageTk.PhotoImage(scaled)
        
        # Wyczyść canvas
        self.delete("all")
        
        # Umieść obraz na canvas (z offsetem z pan'u)
        self.image_id = self.create_image(
            self.pan_data['x'],
            self.pan_data['y'],
            image=self.photo_image,
            anchor="nw"  # Northwest = górny lewy róg
        )
        
        # Aktualizuj scroll region
        self.configure(scrollregion=self.bbox("all"))

        self._draw_overlay()

    def _update_display_visible_region(self):
        """Renderuj tylko widoczny fragment obrazu zamiast skalowac calosc."""
        if self.original_image is None:
            return

        self._apply_clamped_pan()

        visible_region = self._get_visible_image_region()
        full_width, full_height = self._get_full_image_size()
        origin_x = float(self.pan_data.get('x', 0.0))
        origin_y = float(self.pan_data.get('y', 0.0))

        self.delete("all")
        self.photo_image = None
        self.image_id = None
        self._render_region = None
        self._pan_buffered_move_active = False

        if visible_region is not None:
            crop_box = visible_region["crop_box"]
            cropped = self.original_image.crop(crop_box)
            scaled = cropped.resize(
                (int(visible_region["draw_width"]), int(visible_region["draw_height"])),
                Image.Resampling.BILINEAR
            )
            self.photo_image = ImageTk.PhotoImage(scaled)
            self.image_id = self.create_image(
                float(visible_region["draw_x"]),
                float(visible_region["draw_y"]),
                image=self.photo_image,
                anchor="nw"
            )
            self._render_region = {
                "crop_box": tuple(crop_box),
                "draw_x": float(visible_region["draw_x"]),
                "draw_y": float(visible_region["draw_y"]),
                "draw_width": int(visible_region["draw_width"]),
                "draw_height": int(visible_region["draw_height"]),
                "zoom_level": float(self.zoom_level),
            }

        self.configure(
            scrollregion=(
                origin_x,
                origin_y,
                origin_x + full_width,
                origin_y + full_height,
            )
        )
        self._draw_overlay()

    def _can_reuse_buffered_pan(self):
        region = self._render_region if isinstance(self._render_region, dict) else None
        if region is None or self.image_id is None or self.photo_image is None:
            return False

        if abs(float(region.get("zoom_level", 0.0)) - float(self.zoom_level)) > 1e-9:
            return False

        exact_bounds = self._get_exact_visible_image_bounds()
        if exact_bounds is None:
            return False

        crop_left, crop_top, crop_right, crop_bottom = [float(v) for v in region.get("crop_box", (0, 0, 0, 0))]
        visible_left, visible_top, visible_right, visible_bottom = exact_bounds
        return (
            crop_left <= visible_left
            and crop_top <= visible_top
            and crop_right >= visible_right
            and crop_bottom >= visible_bottom
        )

    def _apply_buffered_pan_move(self, dx: float, dy: float) -> bool:
        if not self._can_reuse_buffered_pan():
            return False

        try:
            self.move("all", float(dx), float(dy))
        except Exception:
            return False

        if isinstance(self._render_region, dict):
            self._render_region["draw_x"] = float(self._render_region.get("draw_x", 0.0)) + float(dx)
            self._render_region["draw_y"] = float(self._render_region.get("draw_y", 0.0)) + float(dy)

        full_width = max(1.0, float(self.original_image.width) * float(self.zoom_level))
        full_height = max(1.0, float(self.original_image.height) * float(self.zoom_level))
        origin_x = float(self.pan_data.get('x', 0.0))
        origin_y = float(self.pan_data.get('y', 0.0))
        self.configure(
            scrollregion=(
                origin_x,
                origin_y,
                origin_x + full_width,
                origin_y + full_height,
            )
        )
        self._pan_buffered_move_active = True
        return True

    def _draw_overlay(self):
        if self.original_image is None:
            return

        renderer = getattr(self, "overlay_renderer", None)
        if callable(renderer):
            try:
                renderer(self)
            except Exception:
                pass

        if self.show_info:
            vx = self.canvasx(10)
            vy = self.canvasy(10)
            
            info_text = f"Zoom: {self.zoom_level:.2f}x"
            help_text = "[Scroll: Zoom] [Drag: Pan] [R: Reset] [I: Ukryj]"
            vy_help = self.canvasy(30)

            offsets = [(-2, -2), (0, -2), (2, -2), (-2, 0), (2, 0), (-2, 2), (0, 2), (2, 2)]
            
            for dx, dy in offsets:
                self.create_text(vx + dx, vy + dy, text=info_text, fill="black", font=("Arial", 11, "bold"), anchor="nw", tags="info")
            self.create_text(vx, vy, text=info_text, fill="#f1c40f", font=("Arial", 11, "bold"), anchor="nw", tags="info")
            
            for dx, dy in offsets:
                self.create_text(vx + dx, vy_help + dy, text=help_text, fill="black", font=("Arial", 9, "bold"), anchor="nw", tags="info")
            self.create_text(vx, vy_help, text=help_text, fill="white", font=("Arial", 9, "bold"), anchor="nw", tags="info")

    def refresh_overlay_only(self):
        """Przerysuj tylko overlay bez ponownego skalowania całego obrazu."""
        if self.original_image is None:
            return

        if self.image_id is None or self.photo_image is None:
            self._update_display()
            return

        self.delete("preview_overlay")
        self.delete("info")
        self._draw_overlay()
    
    def get_zoom_level(self):
        """Zwróć obecny poziom zoom'u."""
        return self.zoom_level
    
    def set_zoom_level(self, level):
        """Ustaw poziom zoom'u bezpośrednio."""
        self.zoom_level = max(self.min_zoom, min(self.max_zoom, level))
        self._update_display()

    def get_view_state(self):
        """Zwróć bieżący stan widoku (zoom + pozycja obrazu)."""
        state = {
            "zoom_level": float(self.zoom_level),
            "origin_x": float(self.pan_data.get('x', 0.0)),
            "origin_y": float(self.pan_data.get('y', 0.0)),
        }
        try:
            self.update_idletasks()
            canvas_width = max(1.0, float(self.winfo_width()))
            canvas_height = max(1.0, float(self.winfo_height()))
            center_img_x, center_img_y = self.canvas_to_image_coords(canvas_width / 2.0, canvas_height / 2.0, clamp=False)
            state["center_img_x"] = float(center_img_x)
            state["center_img_y"] = float(center_img_y)
            state["canvas_width"] = float(canvas_width)
            state["canvas_height"] = float(canvas_height)
        except Exception:
            pass
        return state

    def set_view_state(self, view_state, redraw: bool = True):
        """Ustaw kompletny stan widoku (zoom + pozycja obrazu)."""
        if not isinstance(view_state, dict):
            return False

        try:
            zoom_level = float(view_state.get("zoom_level", self.zoom_level))
        except (TypeError, ValueError):
            return False

        self.zoom_level = max(self.min_zoom, min(self.max_zoom, zoom_level))
        origin_x = float(self.pan_data.get('x', 0.0))
        origin_y = float(self.pan_data.get('y', 0.0))
        try:
            if "center_img_x" in view_state and "center_img_y" in view_state:
                self.update_idletasks()
                canvas_width = max(1.0, float(self.winfo_width()))
                canvas_height = max(1.0, float(self.winfo_height()))
                center_img_x = float(view_state.get("center_img_x", 0.0))
                center_img_y = float(view_state.get("center_img_y", 0.0))
                origin_x = (canvas_width / 2.0) - (center_img_x * self.zoom_level)
                origin_y = (canvas_height / 2.0) - (center_img_y * self.zoom_level)
            else:
                origin_x = float(view_state.get("origin_x", self.pan_data.get('x', 0.0)))
                origin_y = float(view_state.get("origin_y", self.pan_data.get('y', 0.0)))
        except (TypeError, ValueError):
            return False

        self.pan_data = {
            'x': origin_x,
            'y': origin_y,
            'press_x': None,
            'press_y': None
        }
        self._apply_clamped_pan()
        if redraw:
            self._update_display()
        return True

    def set_view(self, zoom_level: float, origin_x: float, origin_y: float, redraw: bool = True):
        """Ustaw zoom i origin obrazu w jednym kroku."""
        return self.set_view_state(
            {
                "zoom_level": float(zoom_level),
                "origin_x": float(origin_x),
                "origin_y": float(origin_y),
            },
            redraw=redraw,
        )
    
    def reset_view(self):
        """Reset widoku (zoom + pan)."""
        self._on_reset_view(None)

    def fit_to_view(self):
        """Dopasuj cały obraz do aktualnego rozmiaru canvasa i wycentruj go."""
        if self.original_image is None:
            return

        self.update_idletasks()
        canvas_width = max(1, int(self.winfo_width()))
        canvas_height = max(1, int(self.winfo_height()))

        if canvas_width <= 1 or canvas_height <= 1:
            self.after(25, self.fit_to_view)
            return

        scale_x = canvas_width / max(1, self.original_image.width)
        scale_y = canvas_height / max(1, self.original_image.height)
        fitted_zoom = min(scale_x, scale_y)
        self.zoom_level = max(self.min_zoom, min(self.max_zoom, fitted_zoom))

        scaled_width = float(self.original_image.width) * float(self.zoom_level)
        scaled_height = float(self.original_image.height) * float(self.zoom_level)

        self.pan_data = {
            'x': (float(canvas_width) - scaled_width) / 2.0,
            'y': (float(canvas_height) - scaled_height) / 2.0,
            'press_x': None,
            'press_y': None
        }
        self._apply_clamped_pan()
        self._update_display()
        
    def update_image_preserve_zoom(self, pil_image):
        """
        Aktualizuj obraz, zachowując obecny zoom i pan.
        
        Args:
            pil_image: Nowy obraz (PIL.Image)
        """
        self.original_image = pil_image
        self._apply_clamped_pan()
        self._update_display()

    def get_image_origin(self):
        """Zwróć pozycję lewego górnego rogu obrazu na canvasie."""
        return float(self.pan_data.get('x', 0.0)), float(self.pan_data.get('y', 0.0))

    def get_display_image_size(self):
        """Zwróć rozmiar obrazu po uwzględnieniu bieżącego zoomu."""
        if self.original_image is None:
            return 0.0, 0.0
        return (
            float(self.original_image.width) * float(self.zoom_level),
            float(self.original_image.height) * float(self.zoom_level),
        )

    def image_to_canvas_coords(self, x: float, y: float):
        """Przelicz współrzędne obrazu na współrzędne canvasa."""
        origin_x, origin_y = self.get_image_origin()
        return (
            origin_x + (float(x) * float(self.zoom_level)),
            origin_y + (float(y) * float(self.zoom_level)),
        )

    def canvas_to_image_coords(self, x: float, y: float, clamp: bool = False):
        """Przelicz współrzędne canvasa na współrzędne obrazu."""
        origin_x, origin_y = self.get_image_origin()
        if float(self.zoom_level) == 0.0:
            img_x, img_y = 0.0, 0.0
        else:
            img_x = (float(x) - origin_x) / float(self.zoom_level)
            img_y = (float(y) - origin_y) / float(self.zoom_level)

        if clamp and self.original_image is not None:
            img_x = min(max(0.0, img_x), max(0.0, float(self.original_image.width) - 1.0))
            img_y = min(max(0.0, img_y), max(0.0, float(self.original_image.height) - 1.0))
        return img_x, img_y

    def point_is_inside_image(self, x: float, y: float) -> bool:
        """Sprawdź, czy punkt canvasa leży na obszarze obrazu."""
        if self.original_image is None:
            return False
        img_x, img_y = self.canvas_to_image_coords(x, y, clamp=False)
        return (
            0.0 <= img_x <= max(0.0, float(self.original_image.width) - 1.0)
            and 0.0 <= img_y <= max(0.0, float(self.original_image.height) - 1.0)
        )
