#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historia treningów.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

from ..config import CONFIG, logger
from ..utils import safe_load_yaml


class TrainingStatus(Enum):
    """Status treningu."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TrainingRun:
    """Pojedynczy przebieg treningu."""
    id: str
    name: str
    created_at: str
    status: str = "pending"
    
    # Konfiguracja
    dataset_path: str = ""
    base_model: str = "yolo11s-pose.pt"
    epochs: int = 100
    batch_size: int = 16
    img_size: int = 640
    device: str = "auto"
    lr0: float = 0.01
    
    # Postęp
    current_epoch: int = 0
    best_map50: float = 0.0
    best_map50_95: float = 0.0
    
    # Ścieżki
    output_dir: str = ""
    best_weights: str = ""
    last_weights: str = ""
    
    # Czasy
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    paused_at: Optional[str] = None
    
    # Metryki
    metrics_history: List[Dict] = field(default_factory=list)
    
    # Błędy
    error_message: str = ""

    # Raporty
    report_html: str = ""
    plots_dir: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TrainingRun':
        # Filtruj tylko znane pola
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)
    
    @property
    def duration_str(self) -> str:
        """Czas trwania."""
        if not self.started_at:
            return "-"
        
        start = datetime.fromisoformat(self.started_at)
        
        if self.finished_at:
            end = datetime.fromisoformat(self.finished_at)
        elif self.paused_at:
            end = datetime.fromisoformat(self.paused_at)
        else:
            end = datetime.now()
        
        delta = end - start
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    @property
    def progress_percent(self) -> float:
        if self.epochs == 0:
            return 0.0
        return (self.current_epoch / self.epochs) * 100


class TrainingHistory:
    """Zarządza historią treningów."""
    
    HISTORY_FILE = "training_history.json"
    TARGET_DIRS = {
        "chars": "char",
        "plates": "plate",
        "vehicles": "vehicle",
    }
    
    def __init__(self, history_dir: Path = None):
        self.history_dir = Path(history_dir) if history_dir else Path(CONFIG.DEFAULT_TRAINING_DIR)
        self.history_file = self.history_dir / self.HISTORY_FILE
        self.runs: Dict[str, TrainingRun] = {}
        
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def _get_target_scope(self) -> str:
        return self.TARGET_DIRS.get(self.history_dir.name.lower(), "")

    def _load_runs_from_file(self, history_file: Path) -> Dict[str, TrainingRun]:
        runs: Dict[str, TrainingRun] = {}
        if not history_file.exists():
            return runs

        with open(history_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for run_id, run_data in data.get("runs", {}).items():
            runs[run_id] = TrainingRun.from_dict(run_data)

        return runs

    def _get_legacy_history_files(self) -> List[Path]:
        target_scope = self._get_target_scope()
        if not target_scope:
            return []

        parent_history = self.history_dir.parent / self.HISTORY_FILE
        if parent_history == self.history_file or not parent_history.exists():
            return []

        return [parent_history]

    @staticmethod
    def _infer_target_from_text(text: str) -> str:
        text = str(text or "").strip().lower()
        if not text:
            return ""

        if "pose" in text or any(token in text for token in ("plate", "plates", "tablica", "tablic", "rejestr")):
            return "plate"
        if any(token in text for token in ("char", "chars", "character", "characters", "ocr", "znak", "znaki")):
            return "char"
        if any(token in text for token in ("vehicle", "vehicles", "pojazd", "pojazdy", "samochod", "car", "cars")):
            return "vehicle"
        return ""

    def _infer_target_from_args_file(self, output_dir: str) -> str:
        args_path = Path(output_dir) / "train" / "args.yaml"
        if not args_path.exists():
            return ""

        try:
            args_cfg = safe_load_yaml(args_path)
        except Exception:
            return ""

        task = str(args_cfg.get("task", "") or "").strip().lower()
        model = str(args_cfg.get("model", "") or "")
        data = str(args_cfg.get("data", "") or "")
        project = str(args_cfg.get("project", "") or "")
        merged = " ".join((task, model, data, project))

        if task == "pose":
            return "plate"

        inferred = self._infer_target_from_text(merged)
        if inferred:
            return inferred

        if task == "detect":
            return "char"

        return ""

    def _infer_run_target(self, run: TrainingRun) -> str:
        inferred = self._infer_target_from_args_file(getattr(run, "output_dir", ""))
        if inferred:
            return inferred

        merged = " ".join(
            str(value or "")
            for value in (
                getattr(run, "dataset_path", ""),
                getattr(run, "base_model", ""),
                getattr(run, "name", ""),
                getattr(run, "output_dir", ""),
            )
        )
        return self._infer_target_from_text(merged)

    def _matches_current_scope(self, run: TrainingRun) -> bool:
        target_scope = self._get_target_scope()
        if not target_scope:
            return True

        run_target = self._infer_run_target(run)
        return bool(run_target == target_scope)
    
    def _load(self):
        """Ładuje historię."""
        try:
            self.runs = self._load_runs_from_file(self.history_file)

            imported_legacy = 0
            for legacy_file in self._get_legacy_history_files():
                for run_id, run in self._load_runs_from_file(legacy_file).items():
                    if run_id in self.runs or not self._matches_current_scope(run):
                        continue
                    self.runs[run_id] = run
                    imported_legacy += 1

            if imported_legacy:
                logger.info(
                    f"Zaimportowano {imported_legacy} treningów ze starszej struktury do: {self.history_dir}"
                )
                self._save()

            logger.info(f"Załadowano {len(self.runs)} treningów z: {self.history_dir}")

        except Exception as e:
            logger.error(f"Błąd ładowania historii: {e}")
            self.runs = {}
    
    def _save(self):
        """Zapisuje historię."""
        try:
            data = {
                "version": "1.0",
                "updated_at": datetime.now().isoformat(),
                "runs": {rid: run.to_dict() for rid, run in self.runs.items()}
            }
            
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Błąd zapisywania: {e}")
    
    def create_run(self, name: str, **kwargs) -> TrainingRun:
        """Tworzy nowy trening."""
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        output_dir = self.history_dir / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        run = TrainingRun(
            id=run_id,
            name=name,
            created_at=datetime.now().isoformat(),
            output_dir=str(output_dir),
            **kwargs
        )
        
        self.runs[run_id] = run
        self._save()
        
        logger.info(f"Utworzono trening: {run_id}")
        return run
    
    def update_run(self, run_id: str, **kwargs):
        """Aktualizuje trening."""
        if run_id not in self.runs:
            return
        
        run = self.runs[run_id]
        for key, value in kwargs.items():
            if hasattr(run, key):
                setattr(run, key, value)
        
        self._save()
    
    def add_metrics(self, run_id: str, epoch: int, metrics: Dict):
        """Dodaje metryki."""
        if run_id not in self.runs:
            return
        
        run = self.runs[run_id]
        run.metrics_history.append({
            "epoch": epoch,
            "timestamp": datetime.now().isoformat(),
            **metrics
        })
        run.current_epoch = epoch
        
        if metrics.get("map50", 0) > run.best_map50:
            run.best_map50 = metrics["map50"]
        if metrics.get("map50_95", 0) > run.best_map50_95:
            run.best_map50_95 = metrics["map50_95"]
        
        self._save()
    
    def get_run(self, run_id: str) -> Optional[TrainingRun]:
        return self.runs.get(run_id)
    
    def get_all_runs(self) -> List[TrainingRun]:
        return sorted(self.runs.values(), key=lambda r: r.created_at, reverse=True)
    
    def get_resumable_runs(self) -> List[TrainingRun]:
        return [
            run for run in self.runs.values()
            if run.status in [TrainingStatus.PAUSED.value, TrainingStatus.FAILED.value]
            and run.last_weights and Path(run.last_weights).exists()
        ]
    
    def delete_run(self, run_id: str, delete_files: bool = False):
        """Usuwa trening."""
        if run_id not in self.runs:
            return
        
        run = self.runs[run_id]
        
        if delete_files and run.output_dir:
            import shutil
            output_path = Path(run.output_dir)
            if output_path.exists():
                shutil.rmtree(output_path)
        
        del self.runs[run_id]
        self._save()
