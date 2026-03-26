#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ranking modeli.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from ..config import CONFIG, logger


@dataclass
class ModelRankingEntry:
    """Wpis rankingu."""
    model_name: str
    model_path: str
    date_evaluated: str
    
    task_type: str = "Tablice (Pose)" 
    
    total_images: int = 0
    total_auto_plates: int = 0
    total_corrected_plates: int = 0
    
    plates_unchanged: int = 0
    plates_minor_fix: int = 0
    plates_major_fix: int = 0
    plates_added: int = 0
    plates_removed: int = 0
    
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    
    @property
    def f1_score(self) -> float:
        p = self.precision
        r = self.recall
        if p + r == 0:
            return 0.0
        return 2 * (p * r) / (p + r)
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d["f1_score"] = round(self.f1_score, 2)
        return d
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ModelRankingEntry':
        data = {k: v for k, v in data.items() if k != "f1_score"}
        return cls(**data)


class ModelRanking:
    """Zarządza rankingiem modeli."""
    
    RANKING_FILE = "model_ranking.json"
    
    def __init__(self, ranking_dir: Path = None):
        self.ranking_dir = Path(ranking_dir) if ranking_dir else Path(CONFIG.DEFAULT_RANKING_DIR)
        self.ranking_file = self.ranking_dir / self.RANKING_FILE
        self.entries: List[ModelRankingEntry] = []
        
        self.ranking_dir.mkdir(parents=True, exist_ok=True)
        self._load()
    
    def _load(self):
        if self.ranking_file.exists():
            try:
                with open(self.ranking_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.entries = [
                    ModelRankingEntry.from_dict(e) 
                    for e in data.get("entries", [])
                ]
                
                self._sort()
                logger.info(f"Załadowano ranking: {len(self.entries)} modeli")
                
            except Exception as e:
                logger.error(f"Błąd: {e}")
                self.entries = []
    
    def _save(self):
        data = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "entries": [e.to_dict() for e in self.entries]
        }
        
        with open(self.ranking_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _sort(self):
        self.entries.sort(key=lambda e: e.f1_score, reverse=True)
    
    def add_entry(self, 
                  model_name: str,
                  model_path: str,
                  comparison_stats: Dict,
                  task_type: str = "Tablice (Pose)") -> ModelRankingEntry:
        """Dodaje wpis do bazy, obsługując kategorie zadań."""
        entry = ModelRankingEntry(
            model_name=model_name,
            model_path=model_path,
            date_evaluated=datetime.now().isoformat(),
            task_type=task_type,  # ZAPISUJE ZADANIE
            total_images=comparison_stats.get("total_images", 0),
            total_auto_plates=comparison_stats.get("total_auto_plates", 0),
            total_corrected_plates=comparison_stats.get("total_corrected_plates", 0),
            plates_unchanged=comparison_stats.get("plates_unchanged", 0),
            plates_minor_fix=comparison_stats.get("plates_minor_fix", 0),
            plates_major_fix=comparison_stats.get("plates_major_fix", 0),
            plates_added=comparison_stats.get("plates_added", 0),
            plates_removed=comparison_stats.get("plates_removed", 0),
            accuracy=comparison_stats.get("accuracy", 0),
            precision=comparison_stats.get("precision", 0),
            recall=comparison_stats.get("recall", 0)
        )
        
        self.entries.append(entry)
        self._sort()
        self._save()
        
        return entry
    
    def get_ranking(self) -> List[ModelRankingEntry]:
        return self.entries
    
    def get_best_model(self) -> Optional[ModelRankingEntry]:
        if not self.entries:
            return None
        return self.entries[0]
    
    def delete_entry(self, index: int):
        if 0 <= index < len(self.entries):
            del self.entries[index]
            self._save()
    
    def generate_report(self) -> str:
        report = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                              RANKING MODELI                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
"""
        
        if not self.entries:
            report += "║  Brak danych                                                                ║\n"
        else:
            report += "║  #   Model                Kategoria             Precyzja  Czułość   F1 Score     ║\n"
            report += "║  ──────────────────────────────────────────────────────────────────────────────  ║\n"
            
            for i, e in enumerate(self.entries[:10], 1):
                name = e.model_name[:20].ljust(20)
                cat = e.task_type[:18].ljust(18)
                report += f"║  {i:2d}. {name} {cat} {e.precision:6.1f}%   {e.recall:6.1f}%   {e.f1_score:6.1f}%    ║\n"
        
        report += "╚══════════════════════════════════════════════════════════════════════════════╝\n"
        
        return report
