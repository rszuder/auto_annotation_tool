#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Annotator tablic (Tryb B).
"""

from pathlib import Path
from typing import List, Tuple, Optional

from ..config import CONFIG, logger, YOLO_AVAILABLE, YOLO
from ..data_models import Detection, ImageAnnotation, AnnotationStatus
from ..utils import get_image_size, cleanup_gpu_memory
from .base import BaseAnnotator


class PlateAnnotator(BaseAnnotator):
    """
    Annotator wykrywający tylko tablice rejestracyjne.
    
    Tryb B: Używa modelu YOLO Pose z 4 keypointami.
    Wyjście: <polygon label="plate" points="x1,y1;x2,y2;x3,y3;x4,y4">
    """
    
    def __init__(self,
                 model_path: Path,
                 confidence: float = 0.25,
                 device: str = "auto"):
        super().__init__(confidence, device)
        self.model_path = Path(model_path)
        self.model: Optional[YOLO] = None
        self.is_pose_model = False
    
    def load_models(self) -> Tuple[bool, str]:
        """Ładuje model tablic."""
        if not YOLO_AVAILABLE:
            return False, "YOLO niedostępny"
        
        try:
            logger.info(f"Ładowanie modelu tablic: {self.model_path}")
            self.model = YOLO(str(self.model_path))
            
            # Sprawdź czy to model POSE
            if hasattr(self.model, 'model') and hasattr(self.model.model, 'kpt_shape'):
                self.is_pose_model = True
                kpt_shape = self.model.model.kpt_shape
                logger.info(f"Model POSE (keypoints: {kpt_shape})")
            else:
                logger.warning("Model nie jest typu POSE - użyję bbox jako polygon")
            
            return True, "Model załadowany"
            
        except Exception as e:
            return False, f"Błąd: {e}"
    
    def unload_models(self):
        """Zwalnia model."""
        if self.model:
            del self.model
            self.model = None
        cleanup_gpu_memory()
    
    def process_image(self, image_path: Path) -> ImageAnnotation:
        """Wykrywa tablice na obrazie."""
        width, height = get_image_size(image_path)
        
        annotation = ImageAnnotation(
            filename=image_path.name,
            width=width,
            height=height
        )
        
        try:
            results = self.model(
                str(image_path),
                conf=self.confidence,
                device=self.device,
                verbose=False
            )
            
            if not results or len(results) == 0 or results[0].boxes is None:
                annotation.status = AnnotationStatus.NO_PLATE
                annotation.status_message = "Nie wykryto żadnej tablicy"
                return annotation
            
            result = results[0]
            boxes = result.boxes.xyxy.cpu().numpy()
            confs = result.boxes.conf.cpu().numpy()
            
            # Keypoints
            keypoints = None
            if self.is_pose_model and hasattr(result, 'keypoints') and result.keypoints is not None:
                keypoints = result.keypoints.data.cpu().numpy()
            
            for i, (box, conf) in enumerate(zip(boxes, confs)):
                x1, y1, x2, y2 = map(float, box)
                
                polygon = None
                kpts_list = None
                
                # Pobierz keypoints jako polygon
                if keypoints is not None and i < len(keypoints):
                    kpts = keypoints[i]
                    kpts_list = [(float(kp[0]), float(kp[1]), float(kp[2])) for kp in kpts]
                    
                    if len(kpts) >= 4:
                        corners = [(float(kpts[j][0]), float(kpts[j][1])) for j in range(4)]
                        
                        # Walidacja punktów
                        valid = all(0 <= p[0] <= width and 0 <= p[1] <= height for p in corners)
                        
                        if valid:
                            polygon = self._sort_corners_clockwise(corners)
                
                # Fallback: polygon z bbox
                if polygon is None:
                    polygon = [
                        (x1, y1), (x2, y1), (x2, y2), (x1, y2)
                    ]
                
                annotation.detections.append(Detection(
                    label="plate",
                    confidence=float(conf),
                    bbox=(x1, y1, x2, y2),
                    keypoints=kpts_list,
                    polygon=polygon
                ))
            
            if annotation.detections:
                annotation.status = AnnotationStatus.SUCCESS
                annotation.status_message = f"Wykryto {len(annotation.detections)} tablic"
            else:
                annotation.status = AnnotationStatus.NO_PLATE
            
            return annotation
            
        except Exception as e:
            annotation.status = AnnotationStatus.ERROR
            annotation.status_message = str(e)
            return annotation
    
    def _sort_corners_clockwise(self, corners: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Sortuje 4 rogi: TL, TR, BR, BL."""
        if len(corners) != 4:
            return corners
        
        cx = sum(p[0] for p in corners) / 4
        cy = sum(p[1] for p in corners) / 4
        
        top = [p for p in corners if p[1] < cy]
        bottom = [p for p in corners if p[1] >= cy]
        
        if len(top) != 2 or len(bottom) != 2:
            sorted_by_y = sorted(corners, key=lambda p: p[1])
            top = sorted(sorted_by_y[:2], key=lambda p: p[0])
            bottom = sorted(sorted_by_y[2:], key=lambda p: p[0])
        else:
            top = sorted(top, key=lambda p: p[0])
            bottom = sorted(bottom, key=lambda p: p[0], reverse=True)
        
        return [top[0], top[1], bottom[0], bottom[1]]