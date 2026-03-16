#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Silnik OCR dla tablic rejestracyjnych - TRYB AGRESYWNY.
"""

from pathlib import Path
from typing import Optional, List, Tuple
import numpy as np

from ..config import logger, CV2_AVAILABLE, cv2

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    easyocr = None
    logger.warning("EasyOCR niedostępny - install: pip install easyocr")


class PlateOCR:
    """
    Engine OCR do tablic. Wersja maksymalnie "wyciskająca" tekst z małych obrazków.
    """
    
    def __init__(self, 
                 languages: List[str] = ['en'],  # Zostawiamy tylko EN, bo małe PL znaki diakrytyczne na tablicach nie występują!
                 device: str = 'auto',
                 confidence_threshold: float = 0.15): # Obniżony próg, żeby łapać wszystko
        
        self.languages = languages
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.reader = None
        self.is_loaded = False
        
        # Wymuszamy tylko te znaki! Koniec z czytaniem śrubek jako przecinków.
        self.allowlist = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        
        if EASYOCR_AVAILABLE:
            self._load_reader()
        else:
            logger.error("EasyOCR nie jest zainstalowany!")
    
    def _load_reader(self):
        try:
            logger.info(f"Ładowanie EasyOCR reader (Aggressive Mode)")
            use_gpu = str(self.device).startswith('cuda')
            
            self.reader = easyocr.Reader(
                self.languages,
                gpu=use_gpu,
                verbose=False
            )
            self.is_loaded = True
        except Exception as e:
            logger.error(f"❌ Błąd ładowania EasyOCR: {e}")
            self.is_loaded = False
            
    def preprocess_plate(self, image: np.ndarray, 
                         target_height: int = 80,
                         manual_angle: float = 0.0,
                         clip_thresh: int = 255,
                         denoise_h: int = 0,
                         clahe_clip: float = 0.0,
                         use_binarization: bool = True,
                         thresh_block: int = 15,
                         thresh_c: int = 5,
                         erode_iter: int = 0,
                         interpolation: str = "lanczos4") -> np.ndarray: # <-- DODANE
        """
        Ultimate Preprocessing przyjmujący parametry z GUI.
        """
        if not CV2_AVAILABLE or image is None or image.size == 0:
            return image
            
        rotated = self._rotate_image(image, manual_angle)
            
        if len(rotated.shape) == 3:
            gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        else:
            gray = rotated.copy()
            
        # Mapowanie wyboru na stałe OpenCV
        interp_map = {
            "nearest": cv2.INTER_NEAREST,
            "linear": cv2.INTER_LINEAR,
            "cubic": cv2.INTER_CUBIC,
            "lanczos4": cv2.INTER_LANCZOS4
        }
        cv2_interp = interp_map.get(interpolation.lower(), cv2.INTER_LANCZOS4)
            
        # Skalowanie z wybraną metodą interpolacji!
        h, w = gray.shape
        if h > 0 and h != target_height:
            scale = float(target_height) / h
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2_interp)

        if clip_thresh < 255:
            gray[gray > clip_thresh] = 255
            
        if denoise_h > 0:
            denoised = cv2.fastNlMeansDenoising(gray, None, h=denoise_h, templateWindowSize=7, searchWindowSize=21)
        else:
            denoised = gray
        
        if clahe_clip > 0:
            clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
            contrasted = clahe.apply(denoised)
        else:
            contrasted = denoised
            
        if not use_binarization:
            return contrasted
            
        blurred = cv2.GaussianBlur(contrasted, (3, 3), 0)
        
        thresh_block = int(thresh_block)
        if thresh_block % 2 == 0: thresh_block += 1
        if thresh_block < 3: thresh_block = 3
            
        binary = cv2.adaptiveThreshold(
            blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=thresh_block,
            C=thresh_c
        )
        
        if erode_iter > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            final_img = cv2.erode(binary, kernel, iterations=erode_iter)
        else:
            final_img = binary
            
        return final_img
    
    def read_text_aggressive(self, image: np.ndarray):
        """
        Zwraca wyjście z EasyOCR używając agresywnych parametrów.
        """
        if not self.is_loaded: return []
        
        # mag_ratio - wewnętrzne powiększenie EasyOCR
        # text_threshold - niższy próg znalezienia tekstu
        # link_threshold - wyższy próg żeby nie łączył oddzielnych liter w bloki
        return self.reader.readtext(
            image, 
            allowlist=self.allowlist,
            mag_ratio=2.0,
            text_threshold=0.3,
            link_threshold=0.6,
            width_ths=0.8,
            decoder='beamsearch' # Dokładniejszy dekoder niż domyślny 'greedy'
        )
    def _rotate_image(self, image: np.ndarray, angle: float) -> np.ndarray:
        """Obraca obraz o podany kąt (z zachowaniem wypełnienia krawędzi)."""
        if abs(angle) < 0.1:
            return image
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)