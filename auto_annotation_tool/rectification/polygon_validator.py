#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walidacja i naprawianie poligonów (ramek wokół tablic).
"""

import numpy as np
from typing import List, Tuple
from ..config import logger


class PolygonValidator:
    """Waliduje i naprawia poligony (ramki tablic)."""
    
    @staticmethod
    def sort_points_clockwise(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        Sortuj punkty w porządku zgodnym z ruchem wskazówek zegara.
        
        Args:
            points: Lista 4 punktów (x, y)
        
        Returns:
            Posortowana lista punktów
        """
        if len(points) != 4:
            logger.warning(f"Oczekiwano 4 punktów, otrzymano {len(points)}")
            return points
        
        # Konwertuj na numpy array
        pts = np.array(points, dtype=np.float32)
        
        # Oblicz centroid
        centroid = pts.mean(axis=0)
        
        # Oblicz kąt każdego punktu względem centroidu
        angles = np.arctan2(pts[:, 1] - centroid[1], pts[:, 0] - centroid[0])
        
        # Sortuj po kącie
        sorted_indices = np.argsort(angles)
        sorted_pts = pts[sorted_indices]
        
        return [tuple(p) for p in sorted_pts]
    
    @staticmethod
    def order_points(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        Porządkuj punkty: top-left, top-right, bottom-right, bottom-left.
        
        Args:
            points: Lista 4 punktów
        
        Returns:
            Punkty w porządku: TL, TR, BR, BL
        """
        if len(points) != 4:
            return points

        # Sortowanie po samych sumach/różnicach współrzędnych potrafi zwrócić
        # ten sam punkt dwa razy dla mocniej pochylonych czworokątów.
        # Stabilniej jest ułożyć punkty cyklicznie wokół centroidu, a potem
        # obrócić sekwencję tak, by zaczynała się od lewego górnego rogu.
        pts = np.array(points, dtype=np.float32)
        centroid = pts.mean(axis=0)
        angles = np.arctan2(pts[:, 1] - centroid[1], pts[:, 0] - centroid[0])
        ordered = pts[np.argsort(angles)]

        # Start od punktu najbardziej zbliżonego do lewego górnego rogu.
        start_idx = int(np.argmin(ordered[:, 0] + ordered[:, 1]))
        ordered = np.roll(ordered, -start_idx, axis=0)

        # Po ustawieniu startu w TL możliwe są jeszcze dwa kierunki:
        # TL, TR, BR, BL albo TL, BL, BR, TR. Wyrównujemy do wariantu
        # zgodnego z ruchem wskazówek zegara i stałą numeracją rogów.
        if ordered[1][0] < ordered[-1][0]:
            ordered = np.array([ordered[0], ordered[-1], ordered[-2], ordered[-3]], dtype=np.float32)

        return [tuple(float(v) for v in p) for p in ordered]
    
    @staticmethod
    def is_valid_quad(points: List[Tuple[float, float]]) -> bool:
        """
        Sprawdź czy cztery punkty tworzą prawidłowy czworokąt (bez kokard).
        
        Args:
            points: Lista 4 punktów
        
        Returns:
            True jeśli czworokąt jest prawidłowy
        """
        if len(points) != 4:
            return False

        unique_points = {(float(x), float(y)) for x, y in points}
        if len(unique_points) != 4:
            return False
        
        pts = np.array(points, dtype=np.float32)
        
        # Oblicz pole czworokąta (Shoelace formula)
        x = pts[:, 0]
        y = pts[:, 1]
        area = 0.5 * abs(
            x[0] * (y[1] - y[3]) +
            x[1] * (y[2] - y[0]) +
            x[2] * (y[3] - y[1]) +
            x[3] * (y[0] - y[2])
        )
        
        # Czworokąt powinien mieć dodatnie pole
        if area < 10:  # Zbyt mały czworokąt
            return False
        
        # Sprawdź czy punkty tworzą prosty wielokąt (brak przecięć)
        # Użyj cv2.contourArea
        try:
            import cv2
            poly = cv2.contourArea(pts.reshape(-1, 1, 2))
            if poly < 10:
                return False
        except:
            pass
        
        return True
    
    @staticmethod
    def fix_polygon(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        Napraw poligon (usuń kokardę).
        
        Jeśli punkty są w złej kolejności, posortuj je prawidłowo.
        
        Args:
            points: Lista punktów (może być w złej kolejności)
        
        Returns:
            Naprawiona lista punktów
        """
        if len(points) != 4:
            logger.warning(f"Poligon ma {len(points)} punktów, oczekiwano 4")
            return points
        
        # Spróbuj porządku: TL, TR, BR, BL
        ordered = PolygonValidator.order_points(points)
        
        if PolygonValidator.is_valid_quad(ordered):
            logger.debug("Poligon uporzadkowany (zmiana kolejnosci punktow)")
            return ordered
        
        # Jeśli to nie zadziała, spróbuj sortowania po kącie
        clockwise = PolygonValidator.sort_points_clockwise(points)
        
        if PolygonValidator.is_valid_quad(clockwise):
            logger.debug("Poligon uporzadkowany (sortowanie po kacie)")
            return clockwise
        
        logger.warning("Nie udało się naprawić poligonu - może być kokarda")
        return points
    
    @staticmethod
    def points_to_vector(points: List[Tuple[float, float]]) -> np.ndarray:
        """Konwertuj listę punktów na numpy array."""
        return np.array(points, dtype=np.float32)
