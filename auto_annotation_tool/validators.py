#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Funkcje walidacji plików i datasetów.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Set, Tuple

from .config import CONFIG, logger, YOLO_AVAILABLE, YOLO
from .utils import safe_load_yaml, cleanup_gpu_memory


def validate_yolo_dataset(dataset_path: Path) -> Tuple[bool, str, Dict]:
    """Waliduje dataset YOLO."""
    stats = {
        "train_images": 0,
        "val_images": 0,
        "test_images": 0,
        "train_labels": 0,
        "val_labels": 0,
        "test_labels": 0,
        "total_images": 0,
        "total_labels": 0,
        "config": {},
        "warnings": []
    }
    
    if not dataset_path.exists():
        return False, "Folder nie istnieje", stats
    
    if not dataset_path.is_dir():
        return False, "Ścieżka nie jest folderem", stats
    
    # Znajdź data.yaml
    yaml_file = dataset_path / "data.yaml"
    if not yaml_file.exists():
        return False, "Brak pliku data.yaml", stats
    
    # Parsuj YAML
    try:
        config = safe_load_yaml(yaml_file)
        stats["config"] = config
    except Exception as e:
        stats["warnings"].append(f"Błąd parsowania data.yaml: {e}")
    
    # Sprawdź foldery
    for split in ["train", "val", "test"]:
        images_dir = dataset_path / "images" / split
        labels_dir = dataset_path / "labels" / split
        
        if images_dir.exists():
            img_count = sum(1 for f in images_dir.iterdir() 
                          if f.suffix.lower() in CONFIG.IMAGE_EXTENSIONS)
            stats[f"{split}_images"] = img_count
            stats["total_images"] += img_count
        
        if labels_dir.exists():
            lbl_count = sum(1 for f in labels_dir.iterdir() 
                          if f.suffix.lower() == '.txt')
            stats[f"{split}_labels"] = lbl_count
            stats["total_labels"] += lbl_count
    
    if stats["total_images"] == 0:
        return False, "Brak obrazów w dataset", stats
    
    if stats["total_labels"] == 0:
        return False, "Brak plików etykiet", stats
    
    return True, "Dataset OK", stats


def validate_model_file(model_path: Path) -> Tuple[bool, str, Dict]:
    """Waliduje plik modelu .pt."""
    info = {
        "type": "unknown",
        "task": "unknown",
        "classes": [],
        "num_classes": 0,
        "keypoints": False,
        "kpt_shape": None,
        "file_size_mb": 0
    }
    
    if not model_path.exists():
        return False, "Plik nie istnieje", info
    
    if model_path.suffix.lower() != ".pt":
        return False, "Plik musi mieć rozszerzenie .pt", info
    
    try:
        info["file_size_mb"] = round(model_path.stat().st_size / (1024 * 1024), 2)
    except Exception:
        pass
    
    if not YOLO_AVAILABLE:
        return False, "YOLO niedostępny", info
    
    model = None
    try:
        model = YOLO(str(model_path))
        
        if hasattr(model, 'task'):
            info["task"] = str(model.task)
            info["type"] = str(model.task)
        
        if hasattr(model, 'model') and hasattr(model.model, 'kpt_shape'):
            info["type"] = "pose"
            info["keypoints"] = True
            info["kpt_shape"] = list(model.model.kpt_shape)
        
        if hasattr(model, 'names'):
            if isinstance(model.names, dict):
                info["classes"] = list(model.names.values())
            else:
                info["classes"] = list(model.names)
            info["num_classes"] = len(info["classes"])
        
        return True, f"Model {info['type'].upper()} OK", info
        
    except Exception as e:
        return False, f"Błąd ładowania: {e}", info
        
    finally:
        if model:
            del model
        cleanup_gpu_memory()


def validate_cvat_xml(xml_path: Path) -> Tuple[bool, str, Dict]:
    """Waliduje plik CVAT XML."""
    stats = {
        "images": 0,
        "vehicles": 0,
        "plates": 0,
        "plates_with_4_points": 0,
        "boxes": 0,
        "polygons": 0,
        "labels": []
    }
    
    if not xml_path.exists():
        return False, "Plik nie istnieje", stats
    
    labels_seen: Set[str] = set()
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        for image in root.findall('.//image'):
            stats["images"] += 1
            
            for box in image.findall('box'):
                stats["boxes"] += 1
                label = box.get('label', '').lower()
                labels_seen.add(label)
                if label in CONFIG.VEHICLE_LABELS:
                    stats["vehicles"] += 1
            
            for poly in image.findall('polygon'):
                stats["polygons"] += 1
                label = poly.get('label', '').lower()
                labels_seen.add(label)
                
                if label in CONFIG.PLATE_LABELS:
                    points = poly.get('points', '').split(';')
                    if len(points) == 4:
                        stats["plates"] += 1
                        stats["plates_with_4_points"] += 1
        
        stats["labels"] = sorted(labels_seen)
        
        if stats["images"] == 0:
            return False, "Brak obrazów w pliku", stats
        
        return True, "Plik CVAT XML OK", stats
        
    except ET.ParseError as e:
        return False, f"Błąd parsowania: {e}", stats


def validate_coco_file(coco_path: Path) -> Tuple[bool, str, Dict]:
    """Waliduje plik COCO JSON."""
    stats = {
        "images": 0,
        "annotations": 0,
        "categories": {}
    }
    
    if not coco_path.exists():
        return False, "Plik nie istnieje", stats
    
    try:
        with open(coco_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        stats["images"] = len(data.get("images", []))
        stats["annotations"] = len(data.get("annotations", []))
        
        for cat in data.get("categories", []):
            name = cat.get("name", "unknown")
            stats["categories"][name] = 0
        
        for ann in data.get("annotations", []):
            cat_id = ann.get("category_id")
            for cat in data.get("categories", []):
                if cat.get("id") == cat_id:
                    name = cat.get("name", "unknown")
                    stats["categories"][name] = stats["categories"].get(name, 0) + 1
        
        if stats["images"] == 0:
            return False, "Brak obrazów", stats
        
        return True, "Plik COCO OK", stats
        
    except Exception as e:
        return False, f"Błąd: {e}", stats