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
    OCR = "ocr"
    YOLO = "yolo"
    BOTH = "both"


@dataclass
class CharacterDetection:
    character: str
    bbox: Tuple[float, float, float, float]
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
        x1, y1, x2, y2 = self.bbox
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    
    def to_dict(self) -> dict:
        return {
            'character': str(self.character),
            'bbox': [float(x) for x in self.bbox],
            'confidence': float(self.confidence),
            'method': str(self.method),
        }


class CharacterDetector:
    def __init__(self, method: DetectionMethod = DetectionMethod.OCR, ocr_engine = None, yolo_model = None):
        self.method = method
        self.ocr_engine = ocr_engine
        self.yolo_model = yolo_model
    
    def detect(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        detections = []
        if self.method in [DetectionMethod.OCR, DetectionMethod.BOTH]:
            detections.extend(self._detect_with_ocr(plate_image))
        if self.method in [DetectionMethod.YOLO, DetectionMethod.BOTH]:
            detections.extend(self._detect_with_yolo(plate_image))
            
        detections.sort(key=lambda d: d.bbox[0])
        return detections
    
    def _detect_with_ocr(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        if self.ocr_engine is None or not getattr(self.ocr_engine, 'is_loaded', False):
            return []
        
        try:
            orig_h, orig_w = plate_image.shape[:2]
            
            # 1. PREPROCESSING
            prep_kwargs = getattr(self.ocr_engine, 'custom_prep_params', {})
            if hasattr(self.ocr_engine, 'preprocess_plate'):
                # Wysyłamy bez padding_pct, bo padding robimy tutaj przed samym OCR
                clean_kwargs = {k: v for k, v in prep_kwargs.items() if k != "padding_pct"}
                processed_img = self.ocr_engine.preprocess_plate(plate_image, **clean_kwargs)
            else:
                processed_img = plate_image
                
            proc_h, proc_w = processed_img.shape[:2]
            scale_x = orig_w / float(proc_w) if proc_w > 0 else 1.0
            scale_y = orig_h / float(proc_h) if proc_h > 0 else 1.0

            # 2. PADDING - Dodajemy czysto białą ramkę wokół przefiltrowanego obrazu
            padding_pct = prep_kwargs.get("padding_pct", 20)
            pad_y = int(proc_h * (padding_pct / 100.0))
            pad_x = int(proc_w * (padding_pct / 100.0))
            
            if len(processed_img.shape) == 2:
                padded_img = cv2.copyMakeBorder(processed_img, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=255)
            else:
                padded_img = cv2.copyMakeBorder(processed_img, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=[255, 255, 255])
            
            # 3. OCR READING (Na obrazku powiększonym o ramkę)
            if hasattr(self.ocr_engine, 'read_text_aggressive'):
                results = self.ocr_engine.read_text_aggressive(padded_img)
            else:
                results = self.ocr_engine.reader.readtext(
                    padded_img, 
                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    mag_ratio=1.5, text_threshold=0.2, link_threshold=0.4
                )
            
            detections = []
            
            # 4. PRZELICZANIE WYNIKÓW
            for (bbox_ocr, text, conf) in results:
                threshold = getattr(self.ocr_engine, 'confidence_threshold', 0.15)
                if conf < threshold:
                    continue
                
                text_clean = "".join([c for c in text if c.isalnum()]).upper()
                if not text_clean:
                    continue
                
                # Surowe współrzędne z OCR, odjęcie białego paddingu
                x_coords = [p[0] - pad_x for p in bbox_ocr]
                y_coords = [p[1] - pad_y for p in bbox_ocr]
                
                # Skalowanie do oryginalnego rozmiaru wyciętej tablicy na dysku
                x1_orig = int(min(x_coords) * scale_x)
                x2_orig = int(max(x_coords) * scale_x)
                y1_orig = int(min(y_coords) * scale_y)
                y2_orig = int(max(y_coords) * scale_y)
                
                # Twarde przycięcie do granic oryginalnego obrazka
                x1 = max(0, min(orig_w, x1_orig))
                x2 = max(0, min(orig_w, x2_orig))
                y1 = max(0, min(orig_h, y1_orig))
                y2 = max(0, min(orig_h, y2_orig))
                
                # Jeśli po odcięciu marginesu ramka zniknęła to był szum - ignorujemy.
                if x2 - x1 < 2 or y2 - y1 < 2:
                    continue
                
                # Dzielimy szerokość na pojedyncze litery ("Równe krojenie")
                char_width = (x2 - x1) / len(text_clean)
                
                for i, char in enumerate(text_clean):
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
        if self.yolo_model is None:
            return []
        try:
            results = self.yolo_model(plate_image, conf=0.25, verbose=False)
            if not results or len(results) == 0: return []
            result = results[0]
            if not hasattr(result, 'boxes') or result.boxes is None: return []
            
            boxes = result.boxes.xyxy.cpu().numpy()
            confs = result.boxes.conf.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy().astype(int)
            
            detections = []
            for box, conf, cls_id in zip(boxes, confs, classes):
                x1, y1, x2, y2 = map(float, box)
                class_name = self.yolo_model.names.get(int(cls_id), str(cls_id)) if hasattr(self.yolo_model, 'names') else str(cls_id)
                det = CharacterDetection(character=class_name.upper(), bbox=(x1, y1, x2, y2), confidence=float(conf), method="yolo")
                detections.append(det)
            return detections
        except Exception as e:
            logger.error(f"Błąd YOLO detection na znakach: {e}")
            return []