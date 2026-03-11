#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Konfiguracja i stałe aplikacji.
"""

import logging
from dataclasses import dataclass, field
from typing import FrozenSet

# ============================================================================
# LOGOWANIE
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AutoAnnotationTool")

# ============================================================================
# SPRAWDZENIE DOSTĘPNOŚCI BIBLIOTEK
# ============================================================================

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False
    tk = None
    ttk = None
    logger.error("Tkinter niedostępny - GUI nie będzie działać")

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    logger.warning("PIL/Pillow niedostępny")

try:
    from ultralytics import YOLO
    import torch
    YOLO_AVAILABLE = True
    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    YOLO_AVAILABLE = False
    CUDA_AVAILABLE = False
    YOLO = None
    torch = None
    logger.warning("Ultralytics/PyTorch niedostępny")

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    cv2 = None
    np = None
    logger.warning("OpenCV niedostępny")

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None
    logger.warning("PyYAML niedostępny")


# ============================================================================
# KONFIGURACJA GŁÓWNA
# ============================================================================

@dataclass
class Config:
    """Centralna konfiguracja aplikacji."""
    
    # Wersja
    VERSION: str = "3.0.0"
    APP_NAME: str = "Auto-Annotation Tool dla CVAT"
    
    # Rozszerzenia plików
    IMAGE_EXTENSIONS: FrozenSet[str] = field(
        default_factory=lambda: frozenset({'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'})
    )
    
    # Kategorie
    VEHICLE_LABELS: FrozenSet[str] = field(
        default_factory=lambda: frozenset({
            'vehicle', 'car', 'truck', 'bus', 'motorcycle', 
            'motorbike', 'van', 'auto', 'samochod', 'pojazd'
        })
    )
    
    PLATE_LABELS: FrozenSet[str] = field(
        default_factory=lambda: frozenset({
            'plate', 'license_plate', 'numberplate', 'license plate',
            'tablica', 'rejestracja', 'lp', 'license-plate'
        })
    )
    
    # Parametry detekcji
    DEFAULT_CONFIDENCE: float = 0.25
    DEFAULT_IOU: float = 0.45
    DEFAULT_IMG_SIZE: int = 640
    
    # Próg dla sprawdzania czy tablica jest wewnątrz pojazdu
    PLATE_INSIDE_THRESHOLD: float = 0.95
    
    # Ścieżki domyślne
    DEFAULT_OUTPUT_DIR: str = "./output"
    DEFAULT_MODELS_DIR: str = "./models"
    DEFAULT_DATASETS_DIR: str = "./datasets"
    DEFAULT_TRAINING_DIR: str = "./training_runs"
    DEFAULT_RANKING_DIR: str = "./rankings"


# Singleton konfiguracji
CONFIG = Config()


# ============================================================================
# DOSTĘPNE MODELE YOLO POSE
# ============================================================================

AVAILABLE_POSE_MODELS = {
    # YOLOv8
    "yolov8n-pose": {
        "name": "YOLOv8 Nano Pose",
        "file": "yolov8n-pose.pt",
        "params": "3.3M",
        "speed": "Najszybszy",
        "version": "v8",
        "description": "Najmniejszy model v8, idealny do testów"
    },
    "yolov8s-pose": {
        "name": "YOLOv8 Small Pose",
        "file": "yolov8s-pose.pt",
        "params": "11.6M",
        "speed": "Szybki",
        "version": "v8",
        "description": "Dobry balans szybkości i dokładności"
    },
    "yolov8m-pose": {
        "name": "YOLOv8 Medium Pose",
        "file": "yolov8m-pose.pt",
        "params": "26.4M",
        "speed": "Średni",
        "version": "v8",
        "description": "Większa dokładność"
    },
    "yolov8l-pose": {
        "name": "YOLOv8 Large Pose",
        "file": "yolov8l-pose.pt",
        "params": "44.4M",
        "speed": "Wolny",
        "version": "v8",
        "description": "Wysoka dokładność"
    },
    "yolov8x-pose": {
        "name": "YOLOv8 XLarge Pose",
        "file": "yolov8x-pose.pt",
        "params": "69.4M",
        "speed": "Najwolniejszy",
        "version": "v8",
        "description": "Najwyższa dokładność v8"
    },
    
    # YOLOv11
    "yolo11n-pose": {
        "name": "YOLO11 Nano Pose",
        "file": "yolo11n-pose.pt",
        "params": "2.9M",
        "speed": "Błyskawiczny",
        "version": "v11",
        "description": "Najnowszy lekki model"
    },
    "yolo11s-pose": {
        "name": "YOLO11 Small Pose",
        "file": "yolo11s-pose.pt",
        "params": "9.9M",
        "speed": "Bardzo szybki",
        "version": "v11",
        "description": "Rekomendowany dla tablic"
    },
    "yolo11m-pose": {
        "name": "YOLO11 Medium Pose",
        "file": "yolo11m-pose.pt",
        "params": "20.9M",
        "speed": "Szybki",
        "version": "v11",
        "description": "Wysoka dokładność"
    },
    "yolo11l-pose": {
        "name": "YOLO11 Large Pose",
        "file": "yolo11l-pose.pt",
        "params": "26.2M",
        "speed": "Średni",
        "version": "v11",
        "description": "Bardzo wysoka dokładność"
    },
    "yolo11x-pose": {
        "name": "YOLO11 XLarge Pose",
        "file": "yolo11x-pose.pt",
        "params": "58.8M",
        "speed": "Wolny",
        "version": "v11",
        "description": "Najwyższa dokładność v11"
    },
    
    # YOLOv26 - Najnowsza wersja
    "yolo26n-pose": {
        "name": "YOLOv26 Nano Pose",
        "file": "yolo26n-pose.pt",
        "params": "3.0M",
        "speed": "Błyskawiczny",
        "version": "v26",
        "description": "Nano z v26 – ultra-lekki dla mobile/edge"
    },
    "yolo26s-pose": {
        "name": "YOLOv26 Small Pose",
        "file": "yolo26s-pose.pt",
        "params": "10.5M",
        "speed": "Bardzo szybki",
        "version": "v26",
        "description": "Small v26 – rekomendowany dla tablic"
    },
    "yolo26m-pose": {
        "name": "YOLOv26 Medium Pose",
        "file": "yolo26m-pose.pt",
        "params": "26.0M",
        "speed": "Szybki",
        "version": "v26",
        "description": "Medium v26 – idealny balans dla dokładności tablic"
    },
    "yolo26l-pose": {
        "name": "YOLOv26 Large Pose",
        "file": "yolo26l-pose.pt",
        "params": "45.0M",
        "speed": "Średni",
        "version": "v26",
        "description": "Large v26 – dla zaawansowanych zadań"
    },
    "yolo26x-pose": {
        "name": "YOLOv26 XLarge Pose",
        "file": "yolo26x-pose.pt",
        "params": "70.0M",
        "speed": "Wolny",
        "version": "v26",
        "description": "XLarge v26 – najwyższa precyzja na serwery"
    },
}

# ============================================================================
# DOSTĘPNE MODELE DO DETEKCJI POJAZDÓW (COCO)
# ============================================================================

AVAILABLE_DETECT_MODELS = {
    # YOLOv8 (COCO - pojazdy: car=2, motorcycle=3, bus=5, truck=7)
    "yolov8n": {
        "name": "YOLOv8 Nano (COCO)",
        "file": "yolov8n.pt",
        "params": "3.2M",
        "description": "Najszybszy, wykrywa pojazdy z COCO"
    },
    "yolov8s": {
        "name": "YOLOv8 Small (COCO)",
        "file": "yolov8s.pt",
        "params": "11.2M",
        "description": "Rekomendowany dla pojazdów"
    },
    "yolov8m": {
        "name": "YOLOv8 Medium (COCO)",
        "file": "yolov8m.pt",
        "params": "25.9M",
        "description": "Wyższa dokładność dla pojazdów"
    },
    "yolov8l": {
        "name": "YOLOv8 Large (COCO)",
        "file": "yolov8l.pt",
        "params": "44.0M",
        "description": "Wysoka dokładność, wolniejszy"
    },
    "yolov8x": {
        "name": "YOLOv8 XLarge (COCO)",
        "file": "yolov8x.pt",
        "params": "68.2M",
        "description": "Najwyższa dokładność v8 dla detekcji"
    },
    
    # YOLOv11
    "yolo11n": {
        "name": "YOLOv11 Nano (COCO)",
        "file": "yolo11n.pt",
        "params": "2.6M",
        "description": "Najnowszy nano, bardzo szybki"
    },
    "yolo11s": {
        "name": "YOLOv11 Small (COCO)",
        "file": "yolo11s.pt",
        "params": "9.4M",
        "description": "Najnowszy small, rekomendowany"
    },
    "yolo11m": {
        "name": "YOLOv11 Medium (COCO)",
        "file": "yolo11m.pt",
        "params": "20.1M",
        "description": "Najnowszy medium, wyższa dokładność"
    },
    "yolo11l": {
        "name": "YOLOv11 Large (COCO)",
        "file": "yolo11l.pt",
        "params": "25.3M",
        "description": "Najnowszy large, wysoka dokładność"
    },
    "yolo11x": {
        "name": "YOLOv11 XLarge (COCO)",
        "file": "yolo11x.pt",
        "params": "56.9M",
        "description": "Najwyższa dokładność v11"
    },
}


# ============================================================================
# INFORMACJE O FORMACIE CVAT
# ============================================================================

CVAT_IMPORT_INFO = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                      INSTRUKCJA IMPORTU DO CVAT                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. UTWÓRZ ZADANIE W CVAT                                                   ║
║     • Projects → Create new project (opcjonalnie)                           ║
║     • Tasks → Create new task                                               ║
║     • Załaduj TE SAME obrazy co użyte w auto-anotacji                       ║
║                                                                              ║
║  2. ZDEFINIUJ ETYKIETY (Labels)                                             ║
║     Przed importem musisz utworzyć etykiety:                                ║
║                                                                              ║
║     ┌─────────────┬─────────────┬─────────────────────────────┐             ║
║     │ Nazwa       │ Typ         │ Opis                        │             ║
║     ├─────────────┼─────────────┼─────────────────────────────┤             ║
║     │ vehicle     │ Rectangle   │ Bounding box pojazdu        │             ║
║     │ plate       │ Polygon     │ 4 rogi tablicy              │             ║
║     └─────────────┴─────────────┴─────────────────────────────┘             ║
║                                                                              ║
║  3. IMPORTUJ ANOTACJE                                                       ║
║     • Otwórz zadanie                                                        ║
║     • Menu (3 kropki) → Import annotations                                  ║
║     • Format: "CVAT 1.1"                                                    ║
║     • Wybierz wygenerowany plik .xml                                        ║
║                                                                              ║
║  4. POPRAW ANOTACJE                                                         ║
║     • Sprawdź i popraw niedokładne anotacje                                 ║
║     • Dodaj pominięte tablice/pojazdy                                       ║
║     • Usuń fałszywe detekcje                                                ║
║                                                                              ║
║  5. EKSPORTUJ POPRAWIONE ANOTACJE                                           ║
║     • Menu → Export annotations                                             ║
║     • Format: "CVAT for images 1.1"                                         ║
║     • Użyj do porównania w zakładce "Ranking"                               ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""