#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ulepszony silnik rektyfikacji z odpornym na szumy deskewingiem konturowym.
"""

from __future__ import annotations
from typing import List, Tuple, Dict
from ..config import CV2_AVAILABLE, cv2, np

class PlateRectifier:
    INTERPOLATIONS = {"nearest": 0, "linear": 1, "cubic": 2, "lanczos4": 4}

    @staticmethod
    def polygon_wh_px(pts: List[Tuple[float, float]]) -> Tuple[float, float]:
        if len(pts) != 4: return 0.0, 0.0
        p = np.array(pts, dtype="float32")
        w = np.linalg.norm(p[0] - p[1])
        h = np.linalg.norm(p[0] - p[3])
        return w, h

    @classmethod
    def deskew(cls, image_bgr: np.ndarray) -> np.ndarray:
        """
        Robust Deskew: Znajduje kontury liter i wyrównuje obraz do ich mediany kąta.
        """
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        # Progowanie adaptacyjne (lepiej radzi sobie z cieniami)
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                     cv2.THRESH_BINARY_INV, 11, 2)
        
        # Znajdź kontury
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        angles = []
        h_img, w_img = image_bgr.shape[:2]

        for c in contours:
            # Filtruj kontury, które są za małe lub za duże (pomiń szum i ramki)
            x, y, w, h = cv2.boundingRect(c)
            if h > h_img * 0.3 and h < h_img * 0.9 and w < w_img * 0.5:
                # Oblicz kąt nachylenia konturu
                rect = cv2.minAreaRect(c)
                angle = rect[-1]
                
                # Korekta kąta OpenCV (zależnie od wersji zwraca -90 do 0 lub 0 do 90)
                if angle < -45: angle = -(90 + angle)
                elif angle > 45: angle = 90 - angle
                
                angles.append(angle)

        if len(angles) < 3: # Za mało danych by ufać automatowi
            return image_bgr

        # Użyj mediany kątów (odporność na outlier-y)
        best_angle = np.median(angles)
        
        # Ogranicz poprawkę automatu do rozsądnych granic
        if abs(best_angle) > 15: return image_bgr

        return cls.rotate_image(image_bgr, best_angle)

    @staticmethod
    def rotate_image(image, angle):
        if abs(angle) < 0.01: return image
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    @classmethod
    def rectify(
        cls,
        image_bgr,
        pts: List[Tuple[float, float]],
        out_w_px: int,
        out_h_px: int,
        interpolation: str = "lanczos4",
        sharpen: float = 0.0,
        enhance_contrast: bool = False,
        do_deskew: bool = False,
        manual_angle: float = 0.0 # Dodano korektę ręczną
    ):
        if not CV2_AVAILABLE: return image_bgr
        
        # 1. Sortowanie punktów (Algorytm odporny na mocną perspektywę)
        p = np.array(pts, dtype="float32")
        cy = np.mean(p[:, 1])
        
        # Podział na górę i dół na podstawie środka ciężkości
        top = p[p[:, 1] < cy]
        bottom = p[p[:, 1] >= cy]
        
        if len(top) != 2 or len(bottom) != 2:
            # Fallback - sortowanie po osi Y
            p_sorted = p[np.argsort(p[:, 1])]
            top, bottom = p_sorted[:2], p_sorted[2:]
            
        # Sortowanie lewo-prawo
        top = top[np.argsort(top[:, 0])]
        bottom = bottom[np.argsort(bottom[:, 0])[::-1]] # Dół sortujemy odwrotnie: prawy, potem lewy
        
        rect_pts = np.array([top[0], top[1], bottom[0], bottom[1]], dtype="float32")
        # 2. Perspective Warp
        dst = np.array([[0, 0], [out_w_px-1, 0], [out_w_px-1, out_h_px-1], [0, out_h_px-1]], dtype="float32")
        M = cv2.getPerspectiveTransform(rect_pts, dst)
        interp_idx = cls.INTERPOLATIONS.get(interpolation, cv2.INTER_LANCZOS4)
        warped = cv2.warpPerspective(image_bgr, M, (out_w_px, out_h_px), flags=interp_idx)

        # 3. Auto Deskew
        if do_deskew:
            warped = cls.deskew(warped)
            
        # 4. Korekta ręczna (nakłada się na automat lub działa samodzielnie)
        if abs(manual_angle) > 0:
            warped = cls.rotate_image(warped, manual_angle)

        # 5. Kontrast
        if enhance_contrast:
            lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            warped = cv2.cvtColor(cv2.merge((clahe.apply(l), a, b)), cv2.COLOR_LAB2BGR)

        # 6. Wyostrzanie
        if sharpen > 0:
            blur = cv2.GaussianBlur(warped, (0, 0), 3)
            warped = cv2.addWeighted(warped, 1.0 + sharpen, blur, -sharpen, 0)

        # ✅ ZMIANA: Wymuszenie poziomej orientacji tablicy (zabezpieczenie przed pionowymi zdjęciami)
        h_out, w_out = warped.shape[:2]
        if h_out > w_out * 1.1:  # Jeśli tablica jest ewidentnie pionowa (wysokość większa od szerokości)
            # Kładziemy tablicę na płasko
            warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)

        return warped