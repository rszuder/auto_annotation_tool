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
    def __init__(
        self,
        method: DetectionMethod = DetectionMethod.OCR,
        ocr_engine = None,
        yolo_model = None,
        yolo_device = None,
        yolo_confidence: float = 0.25,
        yolo_iou: float = 0.45,
        yolo_agnostic_nms: bool = False,
        yolo_overlap_threshold: float = 0.70,
    ):
        self.method = method
        self.ocr_engine = ocr_engine
        self.yolo_model = yolo_model
        self.yolo_device = yolo_device
        self.yolo_confidence = float(yolo_confidence)
        self.yolo_iou = float(yolo_iou)
        self.yolo_agnostic_nms = bool(yolo_agnostic_nms)
        self.yolo_overlap_threshold = float(yolo_overlap_threshold)
        self.last_ocr_detections: List[CharacterDetection] = []
        self.last_yolo_raw_detections: List[CharacterDetection] = []
        self.last_yolo_detections: List[CharacterDetection] = []
    
    def detect(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        detections = []
        self.last_ocr_detections = []
        self.last_yolo_raw_detections = []
        self.last_yolo_detections = []

        if self.method in [DetectionMethod.OCR, DetectionMethod.BOTH]:
            self.last_ocr_detections = self._detect_with_ocr(plate_image)
            detections.extend(self.last_ocr_detections)
        if self.method in [DetectionMethod.YOLO, DetectionMethod.BOTH]:
            self.last_yolo_detections = self._detect_with_yolo(plate_image)
            detections.extend(self.last_yolo_detections)
            
        detections.sort(key=lambda d: d.bbox[0])
        return detections
    
    def _detect_with_ocr(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        if self.ocr_engine is None or not getattr(self.ocr_engine, 'is_loaded', False):
            return []
        
        try:
            orig_h, orig_w = plate_image.shape[:2]
            
            prep_kwargs = getattr(self.ocr_engine, 'custom_prep_params', {})
            if hasattr(self.ocr_engine, 'preprocess_plate'):
                clean_kwargs = {k: v for k, v in prep_kwargs.items() if k != "padding_pct"}
                processed_img = self.ocr_engine.preprocess_plate(plate_image, **clean_kwargs)
            else:
                processed_img = plate_image
                
            proc_h, proc_w = processed_img.shape[:2]
            scale_x = orig_w / float(proc_w) if proc_w > 0 else 1.0
            scale_y = orig_h / float(proc_h) if proc_h > 0 else 1.0

            padding_pct = prep_kwargs.get("padding_pct", 20)
            pad_y = int(proc_h * (padding_pct / 100.0))
            pad_x = int(proc_w * (padding_pct / 100.0))
            
            if len(processed_img.shape) == 2:
                padded_img = cv2.copyMakeBorder(processed_img, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=255)
            else:
                padded_img = cv2.copyMakeBorder(processed_img, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=[255, 255, 255])
            
            if hasattr(self.ocr_engine, 'read_text_aggressive'):
                results = self.ocr_engine.read_text_aggressive(padded_img)
            else:
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
                
                x_coords = [p[0] - pad_x for p in bbox_ocr]
                y_coords = [p[1] - pad_y for p in bbox_ocr]
                
                x1_orig = int(min(x_coords) * scale_x)
                x2_orig = int(max(x_coords) * scale_x)
                y1_orig = int(min(y_coords) * scale_y)
                y2_orig = int(max(y_coords) * scale_y)
                
                # Zabezpieczenie przed ujemnymi ramkami
                x1 = max(0, min(orig_w, x1_orig))
                x2 = max(0, min(orig_w, x2_orig))
                y1 = max(0, min(orig_h, y1_orig))
                y2 = max(0, min(orig_h, y2_orig))
                
                # USUNIĘTE AGRESYWNE ODCIĘCIE: Jeśli ramka ma 0 pikseli, po prostu wymuszamy żeby miała chociaż 1 piksel szerokości
                if x2 <= x1: x2 = x1 + 1
                if y2 <= y1: y2 = y1 + 1
                
                char_width = (x2 - x1) / len(text_clean)
                for i, char in enumerate(text_clean):
                    char_x1 = x1 + (i * char_width)
                    char_x2 = char_x1 + char_width
                    det = CharacterDetection(character=char, bbox=(char_x1, y1, char_x2, y2), confidence=float(conf), method="ocr")
                    detections.append(det)
            
            return detections
        
        except Exception as e:
            logger.error(f"Błąd OCR detection: {e}")
            return []
        
    def _detect_with_yolo(self, plate_image: np.ndarray) -> List[CharacterDetection]:
        if self.yolo_model is None:
            return []
        try:
            conf = max(0.0, min(float(self.yolo_confidence), 1.0))
            iou = max(0.01, min(float(self.yolo_iou), 0.99))
            predict_kwargs = {
                "conf": conf,
                "iou": iou,
                "agnostic_nms": bool(self.yolo_agnostic_nms),
                "verbose": False,
            }
            if self.yolo_device is not None:
                predict_kwargs["device"] = self.yolo_device

            results = self.yolo_model(plate_image, **predict_kwargs)
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
            self.last_yolo_raw_detections = list(detections)
            return self._suppress_overlapping_yolo_detections(detections)
        except Exception as e:
            logger.error(f"Błąd YOLO detection na znakach: {e}")
            return []

    def _bbox_area(self, bbox: Tuple[float, float, float, float]) -> float:
        x1, y1, x2, y2 = bbox
        return max(0.0, float(x2) - float(x1)) * max(0.0, float(y2) - float(y1))

    def _smaller_box_overlap(
        self,
        bbox1: Tuple[float, float, float, float],
        bbox2: Tuple[float, float, float, float]
    ) -> float:
        x1 = max(float(bbox1[0]), float(bbox2[0]))
        y1 = max(float(bbox1[1]), float(bbox2[1]))
        x2 = min(float(bbox1[2]), float(bbox2[2]))
        y2 = min(float(bbox1[3]), float(bbox2[3]))

        if x1 >= x2 or y1 >= y2:
            return 0.0

        inter_area = (x2 - x1) * (y2 - y1)
        smaller_area = min(self._bbox_area(bbox1), self._bbox_area(bbox2))
        if smaller_area <= 0.0:
            return 0.0

        return inter_area / smaller_area

    def _bbox_iou(
        self,
        bbox1: Tuple[float, float, float, float],
        bbox2: Tuple[float, float, float, float]
    ) -> float:
        x1 = max(float(bbox1[0]), float(bbox2[0]))
        y1 = max(float(bbox1[1]), float(bbox2[1]))
        x2 = min(float(bbox1[2]), float(bbox2[2]))
        y2 = min(float(bbox1[3]), float(bbox2[3]))

        if x1 >= x2 or y1 >= y2:
            return 0.0

        inter_area = (x2 - x1) * (y2 - y1)
        area1 = self._bbox_area(bbox1)
        area2 = self._bbox_area(bbox2)
        union = area1 + area2 - inter_area
        if union <= 0.0:
            return 0.0

        return inter_area / union

    def _normalized_center_distance(
        self,
        bbox1: Tuple[float, float, float, float],
        bbox2: Tuple[float, float, float, float]
    ) -> Tuple[float, float]:
        cx1 = (float(bbox1[0]) + float(bbox1[2])) / 2.0
        cy1 = (float(bbox1[1]) + float(bbox1[3])) / 2.0
        cx2 = (float(bbox2[0]) + float(bbox2[2])) / 2.0
        cy2 = (float(bbox2[1]) + float(bbox2[3])) / 2.0

        width_norm = max(1.0, min(abs(float(bbox1[2]) - float(bbox1[0])), abs(float(bbox2[2]) - float(bbox2[0]))))
        height_norm = max(1.0, min(abs(float(bbox1[3]) - float(bbox1[1])), abs(float(bbox2[3]) - float(bbox2[1]))))

        return abs(cx1 - cx2) / width_norm, abs(cy1 - cy2) / height_norm

    def _looks_like_duplicate_detection(
        self,
        candidate: CharacterDetection,
        kept: CharacterDetection,
        threshold: float
    ) -> bool:
        overlap = self._smaller_box_overlap(candidate.bbox, kept.bbox)
        if overlap >= threshold:
            return True

        iou = self._bbox_iou(candidate.bbox, kept.bbox)
        dx_ratio, dy_ratio = self._normalized_center_distance(candidate.bbox, kept.bbox)

        close_centers = dx_ratio <= 0.35 and dy_ratio <= 0.45
        moderate_overlap = overlap >= max(0.18, threshold * 0.45)
        moderate_iou = iou >= max(0.12, threshold * 0.35)

        return close_centers and (moderate_overlap or moderate_iou)

    def _suppress_overlapping_yolo_detections(self, detections: List[CharacterDetection]) -> List[CharacterDetection]:
        threshold = max(0.0, min(float(self.yolo_overlap_threshold), 1.0))
        if threshold <= 0.0 or len(detections) <= 1:
            return detections

        ordered = sorted(
            detections,
            key=lambda det: (-float(det.confidence), float(det.bbox[0]), float(det.bbox[1]))
        )

        filtered: List[CharacterDetection] = []
        for candidate in ordered:
            skip_candidate = False
            for kept in filtered:
                if self._looks_like_duplicate_detection(candidate, kept, threshold):
                    skip_candidate = True
                    break
            if not skip_candidate:
                filtered.append(candidate)

        filtered.sort(key=lambda det: float(det.bbox[0]))
        return filtered
