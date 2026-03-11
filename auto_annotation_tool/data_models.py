#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modele danych aplikacji.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from enum import Enum


class AnnotationStatus(Enum):
    """Status anotacji dla obrazu."""
    SUCCESS = "success"
    NO_VEHICLE = "no_vehicle"
    NO_PLATE = "no_plate"
    PARTIAL_PLATE = "partial_plate"
    MULTIPLE_VEHICLES = "multiple_vehicles"
    ERROR = "error"


@dataclass
class Detection:
    """Pojedyncza detekcja obiektu."""
    label: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    keypoints: Optional[List[Tuple[float, float, float]]] = None
    polygon: Optional[List[Tuple[float, float]]] = None
    
    def is_inside(self, other_bbox: Tuple[float, float, float, float], 
                  threshold: float = 0.95) -> bool:
        """Sprawdza czy ta detekcja jest wewnątrz innego bbox."""
        x1, y1, x2, y2 = self.bbox
        ox1, oy1, ox2, oy2 = other_bbox
        
        # Część wspólna
        inter_x1 = max(x1, ox1)
        inter_y1 = max(y1, oy1)
        inter_x2 = min(x2, ox2)
        inter_y2 = min(y2, oy2)
        
        if inter_x1 >= inter_x2 or inter_y1 >= inter_y2:
            return False
        
        inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        self_area = (x2 - x1) * (y2 - y1)
        
        if self_area == 0:
            return False
        
        return (inter_area / self_area) >= threshold
    
    def get_area(self) -> float:
        """Oblicza powierzchnię bbox."""
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])


@dataclass
class ImageAnnotation:
    """Anotacje dla pojedynczego obrazu."""
    filename: str
    width: int
    height: int
    detections: List[Detection] = field(default_factory=list)
    status: AnnotationStatus = AnnotationStatus.SUCCESS
    status_message: str = ""
    
    @property
    def vehicles(self) -> List[Detection]:
        return [d for d in self.detections if d.label.lower() == "vehicle"]
    
    @property
    def plates(self) -> List[Detection]:
        return [d for d in self.detections if d.label.lower() == "plate"]
    
    @property
    def num_vehicles(self) -> int:
        return len(self.vehicles)
    
    @property
    def num_plates(self) -> int:
        return len(self.plates)
    
    @property
    def is_successful(self) -> bool:
        return self.status == AnnotationStatus.SUCCESS


@dataclass
class AnnotationReport:
    """Raport z auto-anotacji."""
    total_images: int = 0
    successful: int = 0
    no_vehicle: int = 0
    no_plate: int = 0
    partial_plate: int = 0
    errors: int = 0
    
    # Liczniki detekcji
    total_vehicles: int = 0
    total_plates: int = 0
    
    # Listy obrazów
    successful_images: List[str] = field(default_factory=list)
    no_vehicle_images: List[str] = field(default_factory=list)
    no_plate_images: List[str] = field(default_factory=list)
    partial_plate_images: List[str] = field(default_factory=list)
    error_images: List[str] = field(default_factory=list)
    
    # Szczegóły błędów
    error_details: Dict[str, str] = field(default_factory=dict)
    
    def add_result(self, annotation: 'ImageAnnotation'):
        """Dodaje wynik dla obrazu."""
        self.total_images += 1
        self.total_vehicles += annotation.num_vehicles
        self.total_plates += annotation.num_plates
        
        status = annotation.status
        filename = annotation.filename
        
        if status == AnnotationStatus.SUCCESS:
            self.successful += 1
            self.successful_images.append(filename)
        elif status == AnnotationStatus.NO_VEHICLE:
            self.no_vehicle += 1
            self.no_vehicle_images.append(filename)
        elif status == AnnotationStatus.NO_PLATE:
            self.no_plate += 1
            self.no_plate_images.append(filename)
        elif status == AnnotationStatus.PARTIAL_PLATE:
            self.partial_plate += 1
            self.partial_plate_images.append(filename)
        else:
            self.errors += 1
            self.error_images.append(filename)
            if annotation.status_message:
                self.error_details[filename] = annotation.status_message
    
    @property
    def success_rate(self) -> float:
        if self.total_images == 0:
            return 0.0
        return (self.successful / self.total_images) * 100
    
    def to_text(self) -> str:
        """Generuje tekstowy raport."""
        report = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                           RAPORT AUTO-ANOTACJI                              ║
╠══════════════════════════════════════════════════════════════════════════════╣

  📊 PODSUMOWANIE
  ────────────────
  Obrazów ogółem:              {self.total_images:5d}
  ✅ Udane anotacje:            {self.successful:5d}  ({self.success_rate:.1f}%)
  ⚠️  Brak pojazdu:              {self.no_vehicle:5d}
  ⚠️  Brak tablicy:              {self.no_plate:5d}
  ⚠️  Tablica częściowa:         {self.partial_plate:5d}
  ❌ Błędy:                      {self.errors:5d}

  📈 DETEKCJE
  ────────────
  Pojazdów wykrytych:          {self.total_vehicles:5d}
  Tablic wykrytych:            {self.total_plates:5d}

╚══════════════════════════════════════════════════════════════════════════════╝
"""
        
        if self.no_vehicle_images:
            report += "\n📋 OBRAZY BEZ WYKRYTEGO POJAZDU:\n"
            report += "─" * 50 + "\n"
            for img in self.no_vehicle_images[:20]:
                report += f"  • {img}\n"
            if len(self.no_vehicle_images) > 20:
                report += f"  ... i {len(self.no_vehicle_images) - 20} więcej\n"
        
        if self.no_plate_images:
            report += "\n📋 OBRAZY BEZ WYKRYTEJ TABLICY:\n"
            report += "─" * 50 + "\n"
            for img in self.no_plate_images[:20]:
                report += f"  • {img}\n"
            if len(self.no_plate_images) > 20:
                report += f"  ... i {len(self.no_plate_images) - 20} więcej\n"
        
        if self.partial_plate_images:
            report += "\n📋 OBRAZY Z CZĘŚCIOWO WIDOCZNĄ TABLICĄ:\n"
            report += "─" * 50 + "\n"
            for img in self.partial_plate_images[:20]:
                report += f"  • {img}\n"
            if len(self.partial_plate_images) > 20:
                report += f"  ... i {len(self.partial_plate_images) - 20} więcej\n"
        
        if self.error_images:
            report += "\n❌ OBRAZY Z BŁĘDAMI:\n"
            report += "─" * 50 + "\n"
            for img in self.error_images[:10]:
                error_msg = self.error_details.get(img, "Nieznany błąd")
                report += f"  • {img}: {error_msg}\n"
        
        return report