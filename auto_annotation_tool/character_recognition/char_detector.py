#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detekcja znaków na tablicach (OCR + YOLO).
"""

from pathlib import Path
from typing import List, Tuple, Optional
from enum import Enum
from dataclasses import dataclass
import numpy as np

from ..config import logger, CV2_AVAILABLE, cv2


class DetectionMethod(Enum):
    """Metoda detekcji znaków."""
    OCR = "ocr"
    YOLO = "yolo"
    BOTH = "both"


@dataclass
class CharacterDetection:
    """Detekcja pojedynczego znaku."""
    character: str
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    method: str = "ocr"
    
    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]
    
    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]
    
    @property
    def polygon(self) -> List[Tuple[float, float]]:
        """Konwertuj bbox do polygonu (4 rogi)."""
        x1, y1, x2, y2 = self.bbox
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    
    def to_dict(self) -> dict:
        return {
            'character': str(self.character),
            'bbox': [float(x) for x in self.bbox],  # Wymusza czystego float'a Pythona!
            'confidence': float(self.confidence),
            'method': str(self.method),
        }


class CharacterDetector:
    """
    Detekcja znaków na tablicy.
    Obsługuje OCR (EasyOCR) i YOLO (gdy będzie model).
    """
    
    def __init__(self,
                 method: DetectionMethod = DetectionMethod.OCR,
                 ocr_engine = None,
                 yolo_model = None):
        """
        Args:
            method: DetectionMethod.OCR / YOLO / BOTH
            ocr_engine: PlateOCR instance
            yolo_model: YOLO model instance
        """
        self.method = method
        self.ocr_engine = ocr_engine
        self.yolo_model = yolo_model
    
    def detect(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        """
        Wykrywa znaki na tablicy.
        """
        detections = []
        
        if self.method in [DetectionMethod.OCR, DetectionMethod.BOTH]:
            detections.extend(self._detect_with_ocr(plate_image))
        
        if self.method in [DetectionMethod.YOLO, DetectionMethod.BOTH]:
            detections.extend(self._detect_with_yolo(plate_image))
        
        # Sortuj po X (od lewej do prawej)
        detections.sort(key=lambda d: d.bbox[0])
        
        return detections
    
    def _detect_with_ocr(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        """Detekcja OCR z dynamicznym PADDINGIEM (oddechem) i inteligentnym skalowaniem."""
        if self.ocr_engine is None or not getattr(self.ocr_engine, 'is_loaded', False):
            return []
        
        try:
            orig_h, orig_w = plate_image.shape[:2]
            
            # 1. PREPROCESSING
            if hasattr(self.ocr_engine, 'preprocess_plate'):
                prep_kwargs = getattr(self.ocr_engine, 'custom_prep_params', {})
                if prep_kwargs:
                    processed_img = self.ocr_engine.preprocess_plate(plate_image, **prep_kwargs)
                else:
                    processed_img = self.ocr_engine.preprocess_plate(plate_image)
            else:
                processed_img = plate_image
                
            proc_h, proc_w = processed_img.shape[:2]
            scale_x = orig_w / float(proc_w) if proc_w > 0 else 1.0
            scale_y = orig_h / float(proc_h) if proc_h > 0 else 1.0

            # =========================================================
            # 2. PADDING (Oddech dla OCR) - KLUCZOWE!
            # Dodajemy szarą/białą ramkę dookoła obrazka (20% wysokości)
            # =========================================================
            pad_y = int(proc_h * 0.25)
            pad_x = int(proc_w * 0.10)
            
            # Jeśli obraz jest czarno-biały, dajemy białą ramkę, jeśli szary, dajemy szarą (medianę)
            if len(processed_img.shape) == 2:
                bg_val = int(np.median(processed_img))
                if bg_val < 50: bg_val = 255 # Jeśli tło wyszło czarne, wymuś białe
                padded_img = cv2.copyMakeBorder(processed_img, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=bg_val)
            else:
                padded_img = cv2.copyMakeBorder(processed_img, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=[128,128,128])
            
            # 3. CZYTANIE TEKSTU (na obrazie z ramką!)
            if hasattr(self.ocr_engine, 'read_text_aggressive'):
                results = self.ocr_engine.read_text_aggressive(padded_img)
            else:
                # Wymuszamy agresywniejsze czytanie jeśli nie ma dedykowanej metody
                results = self.ocr_engine.reader.readtext(
                    padded_img, 
                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    mag_ratio=1.5, text_threshold=0.2, link_threshold=0.4
                )
            
            detections = []
            
            for (bbox_ocr, text, conf) in results:
                threshold = getattr(self.ocr_engine, 'confidence_threshold', 0.15)
                if conf < threshold:
                    continue
                
                text_clean = "".join([c for c in text if c.isalnum()]).upper()
                if not text_clean:
                    continue
                
                xs = [p[0] for p in bbox_ocr]
                ys = [p[1] for p in bbox_ocr]
                
                # Zdejmujemy padding z koordynatów!
                x1_proc = min(xs) - pad_x
                x2_proc = max(xs) - pad_x
                y1_proc = min(ys) - pad_y
                y2_proc = max(ys) - pad_y
                
                # Zabezpieczamy przed wyjściem poza obraz
                x1_proc = max(0, min(proc_w, x1_proc))
                x2_proc = max(0, min(proc_w, x2_proc))
                y1_proc = max(0, min(proc_h, y1_proc))
                y2_proc = max(0, min(proc_h, y2_proc))
                
                if x2_proc <= x1_proc or y2_proc <= y1_proc:
                    continue
                    
                # Przeskalowanie do oryginału
                x1 = int(x1_proc * scale_x)
                x2 = int(x2_proc * scale_x)
                y1 = int(y1_proc * scale_y)
                y2 = int(y2_proc * scale_y)
                
                char_width = (x2 - x1) / len(text_clean)
                
                for i, char in enumerate(text_clean):
                    if char not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
                        continue
                        
                    char_x1 = x1 + (i * char_width)
                    char_x2 = char_x1 + char_width
                    
                    det = CharacterDetection(
                        character=char,
                        bbox=(char_x1, y1, char_x2, y2),
                        confidence=float(conf),
                        method="ocr"
                    )
                    detections.append(det)
            
            return detections
        
        except Exception as e:
            logger.error(f"Błąd OCR detection: {e}")
            return []
    
    def _detect_with_yolo(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        """Detekcja za pomocą wytrenowanego modelu YOLO."""
        if self.yolo_model is None:
            return []
        
        try:
            # Uruchom YOLO z niskim progiem ufności (potem można to wyciągnąć do ustawień)
            results = self.yolo_model(plate_image, conf=0.25, verbose=False)
            
            if not results or len(results) == 0:
                return []
            
            result = results[0]
            
            if not hasattr(result, 'boxes') or result.boxes is None:
                return []
            
            boxes = result.boxes.xyxy.cpu().numpy()
            confs = result.boxes.conf.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy().astype(int)
            
            detections = []
            
            for box, conf, cls_id in zip(boxes, confs, classes):
                x1, y1, x2, y2 = map(float, box)
                
                # Pobierz nazwę klasy (np. "A", "B", "1")
                class_name = "?"
                if hasattr(self.yolo_model, 'names'):
                    class_name = self.yolo_model.names.get(int(cls_id), str(cls_id))
                else:
                    class_name = str(cls_id)
                
                det = CharacterDetection(
                    character=class_name.upper(),
                    bbox=(x1, y1, x2, y2),
                    confidence=float(conf),
                    method="yolo"
                )
                detections.append(det)
            
            return detections
        
        except Exception as e:
            logger.error(f"Błąd YOLO detection na znakach: {e}")
            return []