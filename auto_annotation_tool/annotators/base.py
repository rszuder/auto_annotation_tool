#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazowa klasa annotatora.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Callable, Tuple
import threading

from ..config import CONFIG, logger, YOLO_AVAILABLE, CUDA_AVAILABLE
from ..data_models import ImageAnnotation, AnnotationReport
from ..utils import get_image_files, cleanup_gpu_memory


class BaseAnnotator(ABC):
    """Bazowa klasa dla annotatorów."""
    
    def __init__(self, 
                 confidence: float = 0.25,
                 device: str = "auto"):
        self.confidence = confidence
        self.device = device if device != "auto" else ("cuda" if CUDA_AVAILABLE else "cpu")
        self.report = AnnotationReport()
        
        self._stop_event = threading.Event()
    
    @abstractmethod
    def load_models(self) -> Tuple[bool, str]:
        """Ładuje modele."""
        pass
    
    @abstractmethod
    def unload_models(self):
        """Zwalnia modele."""
        pass
    
    @abstractmethod
    def process_image(self, image_path: Path) -> ImageAnnotation:
        """Przetwarza pojedynczy obraz."""
        pass
    
    def stop(self):
        """Zatrzymuje przetwarzanie."""
        logger.info("⏹️ Sygnał zatrzymania wysłany do annotatora")
        self._stop_event.set()
    
    def is_stopped(self) -> bool:
        """Sprawdza czy przetwarzanie zostało zatrzymane."""
        return self._stop_event.is_set()
    
    def reset_stop(self):
        """Resetuje flagę zatrzymania."""
        self._stop_event.clear()
    
    def _normalize_keypoints(self, raw_keypoints) -> list[tuple[float, float, float]]:
        """
        Normalizuje wynik keypointow YOLO do postaci (x, y, conf).

        Ultralytics potrafi zwracac keypointy jako (x, y) albo (x, y, conf).
        """
        normalized: list[tuple[float, float, float]] = []
        if raw_keypoints is None:
            return normalized

        for kp in raw_keypoints:
            try:
                if len(kp) < 2:
                    continue
                x = float(kp[0])
                y = float(kp[1])
                conf = float(kp[2]) if len(kp) >= 3 else 1.0
                normalized.append((x, y, conf))
            except Exception:
                continue

        return normalized

    def process_directory(self,
                          images_dir: Path,
                          progress_callback: Optional[Callable[..., None]] = None
                          ) -> Tuple[List[ImageAnnotation], AnnotationReport]:
        """Przetwarza wszystkie obrazy w folderze."""
        self.report = AnnotationReport()
        annotations = []
        
        self.reset_stop()
        
        image_files = get_image_files(images_dir)
        
        if not image_files:
            logger.warning(f"Brak obrazów w {images_dir}")
            return annotations, self.report
        
        logger.info(f"Przetwarzanie {len(image_files)} obrazów...")
        
        for i, img_path in enumerate(image_files):
            if self.is_stopped():
                logger.warning(f"⏹️ Przetwarzanie przerwane na obrazie {i+1}/{len(image_files)}")
                break
            
            ann = self.process_image(img_path)
            annotations.append(ann)
            self.report.add_result(ann)

            if progress_callback:
                try:
                    progress_callback(i + 1, len(image_files), img_path.name, self.report.successful)
                except TypeError:
                    progress_callback(i + 1, len(image_files), img_path.name)
        
        logger.info(f"Zakończono: {self.report.successful}/{self.report.total_images} udanych")
        
        return annotations, self.report
