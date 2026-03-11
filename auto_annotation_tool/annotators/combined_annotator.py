#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Annotator łączony: pojazdy + tablice (Tryb C).
"""

from pathlib import Path
from typing import List, Tuple, Optional

from ..config import CONFIG, logger, YOLO_AVAILABLE, YOLO
from ..data_models import Detection, ImageAnnotation, AnnotationStatus
from ..utils import get_image_size, cleanup_gpu_memory
from .base import BaseAnnotator


class CombinedAnnotator(BaseAnnotator):
    """
    Annotator łączony: wykrywa pojazdy i tablice.
    
    Tryb C:
    - Model 1: YOLO detect (pojazdy)
    - Model 2: YOLO Pose (tablice)
    
    Logika:
    - Tablica musi być W CAŁOŚCI wewnątrz pojazdu (>95%)
    - Pojazdy bez widocznej tablicy są pomijane
    - Pojazdy z częściowo widoczną tablicą są pomijane
    
    Wyjście: <box label="vehicle"> + <polygon label="plate">
    """
    
    COCO_VEHICLE_CLASSES = {2, 3, 5, 7}
    
    def __init__(self,
                 vehicle_model_path: Path,
                 plate_model_path: Path,
                 vehicle_confidence: float = 0.25,
                 plate_confidence: float = 0.25,
                 plate_inside_threshold: float = 0.95,
                 device: str = "auto"):
        super().__init__(vehicle_confidence, device)
        
        self.vehicle_model_path = Path(vehicle_model_path)
        self.plate_model_path = Path(plate_model_path)
        self.vehicle_confidence = vehicle_confidence
        self.plate_confidence = plate_confidence
        self.plate_inside_threshold = plate_inside_threshold
        
        self.vehicle_model: Optional[YOLO] = None
        self.plate_model: Optional[YOLO] = None
        self.is_plate_pose_model = False
        self.vehicle_class_names = {}
    
    def load_models(self) -> Tuple[bool, str]:
        """Ładuje oba modele."""
        if not YOLO_AVAILABLE:
            return False, "YOLO niedostępny"
        
        try:
            # Model pojazdów
            logger.info(f"Ładowanie modelu pojazdów: {self.vehicle_model_path}")
            self.vehicle_model = YOLO(str(self.vehicle_model_path))
            
            if hasattr(self.vehicle_model, 'names'):
                self.vehicle_class_names = self.vehicle_model.names
            
            # Model tablic
            logger.info(f"Ładowanie modelu tablic: {self.plate_model_path}")
            self.plate_model = YOLO(str(self.plate_model_path))
            
            if hasattr(self.plate_model, 'model') and hasattr(self.plate_model.model, 'kpt_shape'):
                self.is_plate_pose_model = True
                logger.info(f"Model tablic: POSE")
            else:
                logger.warning("Model tablic nie jest POSE")
            
            return True, "Modele załadowane"
            
        except Exception as e:
            return False, f"Błąd: {e}"
    
    def unload_models(self):
        """Zwalnia modele."""
        if self.vehicle_model:
            del self.vehicle_model
            self.vehicle_model = None
        if self.plate_model:
            del self.plate_model
            self.plate_model = None
        cleanup_gpu_memory()
    
    def process_image(self, image_path: Path) -> ImageAnnotation:
        """Przetwarza obraz - wykrywa pojazdy i tablice."""
        width, height = get_image_size(image_path)
        
        annotation = ImageAnnotation(
            filename=image_path.name,
            width=width,
            height=height
        )
        
        try:
            # 1. Wykryj pojazdy
            vehicles = self._detect_vehicles(image_path)
            
            if not vehicles:
                annotation.status = AnnotationStatus.NO_VEHICLE
                annotation.status_message = "Nie wykryto żadnego pojazdu"
                return annotation
            
            # 2. Wykryj tablice
            plates = self._detect_plates(image_path, width, height)
            
            if not plates:
                annotation.status = AnnotationStatus.NO_PLATE
                annotation.status_message = "Nie wykryto żadnej tablicy"
                return annotation
            
            # 3. Dopasuj tablice do pojazdów
            matched_pairs = self._match_plates_to_vehicles(vehicles, plates)
            
            if not matched_pairs:
                annotation.status = AnnotationStatus.PARTIAL_PLATE
                annotation.status_message = "Tablice nie są w całości widoczne wewnątrz pojazdów"
                return annotation
            
            # 4. Dodaj dopasowane pary
            for vehicle, plate in matched_pairs:
                annotation.detections.append(vehicle)
                annotation.detections.append(plate)
            
            annotation.status = AnnotationStatus.SUCCESS
            annotation.status_message = f"Znaleziono {len(matched_pairs)} par pojazd-tablica"
            
            return annotation
            
        except Exception as e:
            annotation.status = AnnotationStatus.ERROR
            annotation.status_message = str(e)
            logger.error(f"Błąd: {image_path.name}: {e}")
            return annotation
    
    def _detect_vehicles(self, image_path: Path) -> List[Detection]:
        """Wykrywa pojazdy."""
        vehicles = []
        
        results = self.vehicle_model(
            str(image_path),
            conf=self.vehicle_confidence,
            device=self.device,
            verbose=False
        )
        
        if not results or results[0].boxes is None:
            return vehicles
        
        boxes = results[0].boxes.xyxy.cpu().numpy()
        confs = results[0].boxes.conf.cpu().numpy()
        classes = results[0].boxes.cls.cpu().numpy().astype(int)
        
        for box, conf, cls_id in zip(boxes, confs, classes):
            class_name = self.vehicle_class_names.get(cls_id, "").lower()
            is_vehicle = (cls_id in self.COCO_VEHICLE_CLASSES or 
                         class_name in CONFIG.VEHICLE_LABELS)
            
            if is_vehicle:
                x1, y1, x2, y2 = map(float, box)
                vehicles.append(Detection(
                    label="vehicle",
                    confidence=float(conf),
                    bbox=(x1, y1, x2, y2)
                ))
        
        return vehicles
    
    def _detect_plates(self, image_path: Path, width: int, height: int) -> List[Detection]:
        """Wykrywa tablice."""
        plates = []
        
        results = self.plate_model(
            str(image_path),
            conf=self.plate_confidence,
            device=self.device,
            verbose=False
        )
        
        if not results or results[0].boxes is None:
            return plates
        
        result = results[0]
        boxes = result.boxes.xyxy.cpu().numpy()
        confs = result.boxes.conf.cpu().numpy()
        
        keypoints = None
        if self.is_plate_pose_model and hasattr(result, 'keypoints') and result.keypoints is not None:
            keypoints = result.keypoints.data.cpu().numpy()
        
        for i, (box, conf) in enumerate(zip(boxes, confs)):
            x1, y1, x2, y2 = map(float, box)
            
            polygon = None
            kpts_list = None
            
            if keypoints is not None and i < len(keypoints):
                kpts = keypoints[i]
                kpts_list = [(float(kp[0]), float(kp[1]), float(kp[2])) for kp in kpts]
                
                if len(kpts) >= 4:
                    corners = [(float(kpts[j][0]), float(kpts[j][1])) for j in range(4)]
                    valid = all(0 <= p[0] <= width and 0 <= p[1] <= height for p in corners)
                    
                    if valid:
                        polygon = self._sort_corners_clockwise(corners)
            
            if polygon is None:
                polygon = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            
            plates.append(Detection(
                label="plate",
                confidence=float(conf),
                bbox=(x1, y1, x2, y2),
                keypoints=kpts_list,
                polygon=polygon
            ))
        
        return plates
    
    def _match_plates_to_vehicles(self, 
                                   vehicles: List[Detection], 
                                   plates: List[Detection]) -> List[Tuple[Detection, Detection]]:
        """Dopasowuje tablice do pojazdów."""
        matched = []
        used_plates = set()
        
        for vehicle in vehicles:
            best_plate = None
            best_plate_idx = -1
            best_conf = 0
            
            for i, plate in enumerate(plates):
                if i in used_plates:
                    continue
                
                if plate.is_inside(vehicle.bbox, threshold=self.plate_inside_threshold):
                    if plate.confidence > best_conf:
                        best_plate = plate
                        best_plate_idx = i
                        best_conf = plate.confidence
            
            if best_plate:
                matched.append((vehicle, best_plate))
                used_plates.add(best_plate_idx)
        
        return matched
    
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