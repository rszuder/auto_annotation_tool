#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tworzenie datasetu YOLO Pose z eksportu CVAT.
"""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass

from ..config import CONFIG, logger


@dataclass
class PlateAnnotation:
    """Anotacja tablicy."""
    image_name: str
    image_width: int
    image_height: int
    points: List[Tuple[float, float]]
    
    def to_yolo_pose(self) -> Optional[str]:
        """Konwertuje do formatu YOLO Pose."""
        if len(self.points) != 4:
            return None
        
        # Bbox z punktów
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        
        # Normalizacja
        x_center = ((x_min + x_max) / 2) / self.image_width
        y_center = ((y_min + y_max) / 2) / self.image_height
        width = (x_max - x_min) / self.image_width
        height = (y_max - y_min) / self.image_height
        
        # Keypoints (posortowane)
        sorted_points = self._sort_clockwise()
        
        keypoints = []
        for px, py in sorted_points:
            kp_x = px / self.image_width
            kp_y = py / self.image_height
            keypoints.extend([kp_x, kp_y])
        
        values = [0, x_center, y_center, width, height] + keypoints
        return " ".join([f"{v:.6f}" if isinstance(v, float) else str(v) for v in values])
    
    def _sort_clockwise(self) -> List[Tuple[float, float]]:
        """Sortuje punkty: TL, TR, BR, BL."""
        if len(self.points) != 4:
            return self.points
        
        cx = sum(p[0] for p in self.points) / 4
        cy = sum(p[1] for p in self.points) / 4
        
        top = sorted([p for p in self.points if p[1] < cy], key=lambda p: p[0])
        bottom = sorted([p for p in self.points if p[1] >= cy], key=lambda p: p[0], reverse=True)
        
        if len(top) != 2:
            sorted_by_y = sorted(self.points, key=lambda p: p[1])
            top = sorted(sorted_by_y[:2], key=lambda p: p[0])
            bottom = sorted(sorted_by_y[2:], key=lambda p: p[0], reverse=True)
        
        return [top[0], top[1], bottom[0], bottom[1]]


class DatasetCreator:
    """
    Tworzy dataset YOLO Pose z eksportu CVAT.
    
    Wymagany format CVAT:
    - Tablice jako <polygon> z dokładnie 4 punktami
    - Label: "plate", "license_plate" lub "numberplate"
    """
    
    REQUIRED_FORMAT = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                    WYMAGANY FORMAT EKSPORTU Z CVAT                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. W CVAT: Menu → Export annotations → Format: "CVAT for images 1.1"       ║
║                                                                              ║
║  2. Struktura eksportu:                                                      ║
║     📁 cvat_export/                                                          ║
║     ├── 📄 annotations.xml                                                   ║
║     └── 📁 images/                                                           ║
║         ├── img001.jpg                                                       ║
║         └── ...                                                              ║
║                                                                              ║
║  3. Format tablicy w XML:                                                    ║
║     <polygon label="plate" points="x1,y1;x2,y2;x3,y3;x4,y4"/>               ║
║                                                                              ║
║  ⚠️ UWAGI:                                                                   ║
║  • Polygon MUSI mieć dokładnie 4 punkty (4 rogi tablicy)                    ║
║  • Label: "plate", "license_plate" lub "numberplate"                        ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    
    def __init__(self):
        self.annotations: List[PlateAnnotation] = []
    
    @staticmethod
    def get_required_format() -> str:
        """Zwraca opis wymaganego formatu."""
        return DatasetCreator.REQUIRED_FORMAT
    
    def parse_cvat_xml(self, xml_path: Path) -> Tuple[bool, str, Dict]:
        """
        Parsuje plik CVAT XML.
        
        Returns:
            (success, message, stats)
        """
        stats = {
            "images": 0,
            "plates": 0,
            "skipped": 0,
            "errors": []
        }
        
        self.annotations = []
        
        if not xml_path.exists():
            return False, "Plik nie istnieje", stats
        
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            
            for image in root.findall('.//image'):
                img_name = image.get('name', '')
                img_width = int(image.get('width', 0))
                img_height = int(image.get('height', 0))
                
                if not img_name or not img_width or not img_height:
                    continue
                
                stats["images"] += 1
                
                for poly in image.findall('polygon'):
                    label = poly.get('label', '').lower()
                    
                    if label not in CONFIG.PLATE_LABELS:
                        continue
                    
                    points_str = poly.get('points', '')
                    if not points_str:
                        stats["skipped"] += 1
                        continue
                    
                    try:
                        points = []
                        for p in points_str.split(';'):
                            if ',' in p:
                                x, y = p.strip().split(',')
                                points.append((float(x), float(y)))
                        
                        if len(points) == 4:
                            self.annotations.append(PlateAnnotation(
                                image_name=img_name,
                                image_width=img_width,
                                image_height=img_height,
                                points=points
                            ))
                            stats["plates"] += 1
                        else:
                            stats["skipped"] += 1
                            stats["errors"].append(f"{img_name}: polygon ma {len(points)} punktów (wymagane 4)")
                            
                    except Exception as e:
                        stats["skipped"] += 1
                        stats["errors"].append(f"{img_name}: {e}")
            
            if stats["plates"] == 0:
                return False, "Nie znaleziono tablic z 4 punktami", stats
            
            return True, f"Znaleziono {stats['plates']} tablic", stats
            
        except ET.ParseError as e:
            return False, f"Błąd parsowania XML: {e}", stats
    
    def create_dataset(self,
                       images_dir: Path,
                       output_dir: Path,
                       split_ratios: Dict[str, float] = None,
                       progress_callback: Optional[Callable[[int, int, str], None]] = None
                       ) -> Tuple[bool, str, Dict]:
        """
        Tworzy dataset YOLO Pose.
        
        Args:
            images_dir: Folder z obrazami
            output_dir: Folder wyjściowy
            split_ratios: {"train": 0.8, "val": 0.2} lub z "test"
            progress_callback: Callback postępu
            
        Returns:
            (success, message, stats)
        """
        if not self.annotations:
            return False, "Brak anotacji - najpierw sparsuj XML", {}
        
        split_ratios = split_ratios or {"train": 0.8, "val": 0.2}
        
        stats = {
            "total": 0,
            "train": 0,
            "val": 0,
            "test": 0,
            "skipped": 0
        }
        
        # Grupuj po obrazie
        images_data = {}
        for ann in self.annotations:
            if ann.image_name not in images_data:
                images_data[ann.image_name] = []
            images_data[ann.image_name].append(ann)
        
        # Przygotuj podział
        image_names = list(images_data.keys())
        
        import random
        random.seed(42)
        random.shuffle(image_names)
        
        n_total = len(image_names)
        n_train = int(n_total * split_ratios.get("train", 0.8))
        n_val = int(n_total * split_ratios.get("val", 0.2))
        
        splits = {}
        splits["train"] = set(image_names[:n_train])
        splits["val"] = set(image_names[n_train:n_train + n_val])
        if "test" in split_ratios:
            splits["test"] = set(image_names[n_train + n_val:])
        
        # Utwórz foldery
        output_dir = Path(output_dir)
        for split in splits.keys():
            (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
            (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)
        
        # Przetwarzaj
        for i, img_name in enumerate(image_names):
            if progress_callback:
                progress_callback(i + 1, n_total, img_name)
            
            # Znajdź split
            split = None
            for s, names in splits.items():
                if img_name in names:
                    split = s
                    break
            
            if not split:
                continue
            
            # Kopiuj obraz
            src_img = images_dir / img_name
            if not src_img.exists():
                stats["skipped"] += 1
                continue
            
            dst_img = output_dir / "images" / split / img_name
            shutil.copy2(src_img, dst_img)
            
            # Zapisz etykietę
            label_name = Path(img_name).stem + ".txt"
            label_path = output_dir / "labels" / split / label_name
            
            lines = []
            for ann in images_data[img_name]:
                line = ann.to_yolo_pose()
                if line:
                    lines.append(line)
            
            with open(label_path, 'w') as f:
                f.write("\n".join(lines))
            
            stats["total"] += 1
            stats[split] += 1
        
        # Utwórz data.yaml
        self._create_data_yaml(output_dir)
        
        return True, f"Utworzono dataset: {stats['total']} obrazów", stats
    
    def _create_data_yaml(self, output_dir: Path):
        """Tworzy przenośny plik data.yaml (bez ścieżek absolutnych)."""
        content = f"""# YOLO Pose Dataset - License Plates
# Wygenerowano przez {CONFIG.APP_NAME} v{CONFIG.VERSION}
# Brak zmiennej 'path' gwarantuje, że dataset jest w 100% przenośny!
# Ścieżki train/val są relatywne do lokalizacji tego pliku.

train: images/train
val: images/val

# Klasy
nc: 1
names:
  0: plate

# Keypoints: 4 rogi tablicy
kpt_shape: [4, 2]

# Flip indexes
flip_idx: [1, 0, 3, 2]
"""
        
        with open(output_dir / "data.yaml", 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"Utworzono przenośny plik: {output_dir / 'data.yaml'}")