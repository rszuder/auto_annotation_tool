#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Konfiguracja i stałe aplikacji.
"""

import logging
from dataclasses import dataclass, field
from typing import FrozenSet
from pathlib import Path

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
# KONFIGURACJA GŁÓWNA I STRUKTURA KATALOGÓW
# ============================================================================

@dataclass
class Config:
    """Centralna konfiguracja aplikacji."""
    
    # Wersja
    VERSION: str = "3.1.0"
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
    
    # ==========================================
    # LOGICZNA STRUKTURA KATALOGÓW (WORKSPACE)
    # ==========================================
    WORKSPACE_DIR: Path = Path("Workspace").resolve()
    
    DIR_1_RAW: Path         = WORKSPACE_DIR / "1_raw_images"
    DIR_2_AUTO_ANN: Path    = WORKSPACE_DIR / "2_auto_annotations"
    DIR_3_CHARS: Path       = WORKSPACE_DIR / "3_cropped_characters"
    DIR_4_DATASETS: Path    = WORKSPACE_DIR / "4_training_datasets"
    DIR_5_RUNS: Path        = WORKSPACE_DIR / "5_training_runs"
    DIR_6_MODELS: Path      = WORKSPACE_DIR / "6_models"
    DIR_9_PROJECTS: Path    = WORKSPACE_DIR / "9_projects"

    # ✅ ZMIANA: Podstruktura dla modeli
    DIR_6_MODELS_BASE: Path          = DIR_6_MODELS / "base"
    DIR_6_MODELS_TRAINED: Path       = DIR_6_MODELS / "trained"
    DIR_6_MODELS_PLATES: Path        = DIR_6_MODELS_TRAINED / "plates_pose"
    DIR_6_MODELS_CHARS: Path         = DIR_6_MODELS_TRAINED / "characters_ocr"
    
    DIR_7_RANKINGS: Path    = WORKSPACE_DIR / "7_rankings"

    # Właściwości zachowujące wsteczną kompatybilność ze starym kodem GUI
    @property
    def DEFAULT_OUTPUT_DIR(self) -> str: return str(self.DIR_2_AUTO_ANN)
    
    @property
    def DEFAULT_MODELS_DIR(self) -> str: return str(self.DIR_6_MODELS)
    
    @property
    def DEFAULT_DATASETS_DIR(self) -> str: return str(self.DIR_4_DATASETS)
    
    @property
    def DEFAULT_TRAINING_DIR(self) -> str: return str(self.DIR_5_RUNS)
    
    @property
    def DEFAULT_RANKING_DIR(self) -> str: return str(self.DIR_7_RANKINGS)

    def init_workspace(self):
        """Automatycznie buduje strukturę katalogów przy starcie aplikacji."""
        directories = [
            self.DIR_1_RAW, 
            self.DIR_2_AUTO_ANN, 
            self.DIR_3_CHARS,
            self.DIR_4_DATASETS, 
            self.DIR_5_RUNS, 
            self.DIR_6_MODELS, 
            self.DIR_6_MODELS_BASE, 
            self.DIR_6_MODELS_PLATES, 
            self.DIR_6_MODELS_CHARS,
            self.DIR_7_RANKINGS, 
            self.DIR_9_PROJECTS,  # ✅ ZMIANA
            
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            
        # Generowanie pliku README z instrukcją dla użytkownika
        readme_path = self.WORKSPACE_DIR / "STRUKTURA_PROJEKTU.txt"
        if not readme_path.exists():
            readme_text = (
                "=== PRZEWODNIK PO PRZESTRZENI ROBOCZEJ (WORKSPACE) ===\n\n"
                "1_raw_images         : Wrzuć tutaj swoje surowe, nieopisane zdjęcia pojazdów.\n"
                "2_auto_annotations   : Tu trafiają wyniki z Zakładki nr 1 (Detekcja pojazdów i tablic).\n"
                "3_cropped_characters : Tu lądują wycięte tablice i wyniki OCR z Zakładki nr 2.\n"
                "4_training_datasets  : Wygenerowane, gotowe datasety YOLO (train/val/test) przed treningiem.\n"
                "5_training_runs      : Logi, wykresy z uczenia i wagi zapisywane w trakcie treningu modelu.\n"
                "6_models             : Skopiuj tutaj najlepsze wytrenowane pliki .pt, aby używać ich w programie.\n"
                "7_rankings           : Zapisane raporty z testów i walidacji.\n"
            )
            readme_path.write_text(readme_text, encoding="utf-8")


# Singleton konfiguracji
CONFIG = Config()
CONFIG.init_workspace()


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
    
    # YOLOv26
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
    # YOLOv8
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

# ============================================================================
# SESJA - Zapamiętywanie ostatnich ścieżek
# ============================================================================

try:
    from .session import SessionManager
    SESSION = SessionManager()
except ImportError as e:
    logger.warning(f"SessionManager niedostępny: {e}")
    SESSION = None