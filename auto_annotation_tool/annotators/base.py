#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bazowa klasa annotatora.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Callable, Tuple

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
    
    def process_directory(self,
                          images_dir: Path,
                          progress_callback: Optional[Callable[[int, int, str], None]] = None
                          ) -> Tuple[List[ImageAnnotation], AnnotationReport]:
        """Przetwarza wszystkie obrazy w folderze."""
        self.report = AnnotationReport()
        annotations = []
        
        image_files = get_image_files(images_dir)
        
        if not image_files:
            logger.warning(f"Brak obrazów w {images_dir}")
            return annotations, self.report
        
        logger.info(f"Przetwarzanie {len(image_files)} obrazów...")
        
        for i, img_path in enumerate(image_files):
            if progress_callback:
                progress_callback(i + 1, len(image_files), img_path.name)
            
            ann = self.process_image(img_path)
            annotations.append(ann)
            self.report.add_result(ann)
        
        logger.info(f"Zakończono: {self.report.successful}/{self.report.total_images} udanych")
        
        return annotations, self.report