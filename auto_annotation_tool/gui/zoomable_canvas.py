#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canvas z obsługą zoom'u i pan'u dla podglądu obrazów.
Zastosowanie: Podgląd w zakładce Prostowania Tablic.
"""

import tkinter as tk
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
        
        # Pan'u - przesuwanie widoku
        self.pan_data = {
            'x': 0,
            'y': 0,
            'press_x': None,
            'press_y': None
        }
        
        # Flaga pokazania tekstu Info
        self.show_info = True
        
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
    
    def set_image(self, pil_image):
        """Ustaw nowy obraz (PIL.Image) i wyczyść zoom/pan."""
        self.original_image = pil_image
        self.zoom_level = 1.0
        self.pan_data = {'x': 0, 'y': 0, 'press_x': None, 'press_y': None}
        self._update_display()
    
    def _on_mousewheel(self, event):
        """Obsługa zoom'u kółkiem myszy."""
        if self.original_image is None:
            return
        
        # Określ kierunek
        delta = event.delta if hasattr(event, 'delta') else (-event.num + 5) * 120
        
        if delta < 0:  # Scroll down
            self.zoom_level /= self.zoom_step
        else:  # Scroll up
            self.zoom_level *= self.zoom_step
        
        # Ogranicz zoom
        self.zoom_level = max(self.min_zoom, min(self.max_zoom, self.zoom_level))
        
        self._update_display()
    
    def _on_pan_press(self, event):
        """Początek przeciągania (naciśnięcie LPM)."""
        self.pan_data['press_x'] = event.x
        self.pan_data['press_y'] = event.y
        self.config(cursor="hand2")
    
    def _on_pan_motion(self, event):
        """Przeciąganie widoku (ruch myszy z LPM)."""
        if self.pan_data['press_x'] is None:
            return
        
        # Oblicz deltę
        dx = event.x - self.pan_data['press_x']
        dy = event.y - self.pan_data['press_y']
        
        # Aktualizuj pan
        self.pan_data['x'] += dx
        self.pan_data['y'] += dy
        
        # Aktualizuj pozycję
        self.pan_data['press_x'] = event.x
        self.pan_data['press_y'] = event.y
        
        self._update_display()
    
    def _on_pan_release(self, event):
        """Koniec przeciągania (zwolnienie LPM)."""
        self.pan_data['press_x'] = None
        self.pan_data['press_y'] = None
        self.config(cursor=self.current_cursor)
    
    def _on_reset_view(self, event):
        """Reset zoom i pan (naciśnięcie Home lub R)."""
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
        
        # Skaluj obraz
        new_width = int(self.original_image.width * self.zoom_level)
        new_height = int(self.original_image.height * self.zoom_level)
        
        if new_width <= 0 or new_height <= 0:
            return
        
        # ✅ ZMIANA: Zmiana z LANCZOS na BILINEAR przyspiesza zoom kilkudziesięciokrotnie, likwidując zacinanie UI.
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
        
        # Opcjonalnie: wyświetl info na canvas
        if self.show_info:
            vx = self.canvasx(10)
            vy = self.canvasy(10)
            
            info_text = f"Zoom: {self.zoom_level:.2f}x"
            help_text = "[Scroll: Zoom] [Drag: Pan] [R: Reset] [I: Ukryj]"
            vy_help = self.canvasy(30)

            # ✅ ZMIANA: Zamiast "cienia", robimy pełny "Outline" (Obrys) w 8 kierunkach!
            # Gruby, czarny obrys zagwarantuje 100% czytelność na KAŻDYM kolorze tła.
            offsets = [(-2,-2), (0,-2), (2,-2), (-2,0), (2,0), (-2,2), (0,2), (2,2)]
            
            # 1. Rysujemy czarną ramkę dla informacji o Zoomie
            for dx, dy in offsets:
                self.create_text(vx + dx, vy + dy, text=info_text, fill="black", font=("Arial", 11, "bold"), anchor="nw", tags="info")
            # Główny napis na wierzch (Zoom)
            self.create_text(vx, vy, text=info_text, fill="#f1c40f", font=("Arial", 11, "bold"), anchor="nw", tags="info")
            
            # 2. Rysujemy czarną ramkę dla Pomocy
            for dx, dy in offsets:
                self.create_text(vx + dx, vy_help + dy, text=help_text, fill="black", font=("Arial", 9, "bold"), anchor="nw", tags="info")
            # Główny napis na wierzch (Pomoc)
            self.create_text(vx, vy_help, text=help_text, fill="white", font=("Arial", 9, "bold"), anchor="nw", tags="info")
    
    def get_zoom_level(self):
        """Zwróć obecny poziom zoom'u."""
        return self.zoom_level
    
    def set_zoom_level(self, level):
        """Ustaw poziom zoom'u bezpośrednio."""
        self.zoom_level = max(self.min_zoom, min(self.max_zoom, level))
        self._update_display()
    
    def reset_view(self):
        """Reset widoku (zoom + pan)."""
        self._on_reset_view(None)
        
    def update_image_preserve_zoom(self, pil_image):
        """
        Aktualizuj obraz, zachowując obecny zoom i pan.
        
        Args:
            pil_image: Nowy obraz (PIL.Image)
        """
        self.original_image = pil_image
        self._update_display()