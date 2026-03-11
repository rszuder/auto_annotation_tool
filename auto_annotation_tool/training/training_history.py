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
    
    def __init__(self, history_dir: Path = None):
        self.history_dir = Path(history_dir) if history_dir else Path(CONFIG.DEFAULT_TRAINING_DIR)
        self.history_file = self.history_dir / self.HISTORY_FILE
        self.runs: Dict[str, TrainingRun] = {}
        
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._load()
    
    def _load(self):
        """Ładuje historię."""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.runs = {}
                for run_id, run_data in data.get("runs", {}).items():
                    self.runs[run_id] = TrainingRun.from_dict(run_data)
                
                logger.info(f"Załadowano {len(self.runs)} treningów")
                
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