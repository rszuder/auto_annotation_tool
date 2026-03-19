#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menadżer Kampanii ALPR (Active Learning Wizard) - Wersja Multi-Project.
Zarządza listą projektów, iteracjami i fizycznym czyszczeniem dysku.
"""

import json
import uuid
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from .config import CONFIG, logger

class CampaignManager:
    def __init__(self):
        self.state_file = CONFIG.WORKSPACE_DIR / "campaigns_registry.json"
        self.state = self._load_state()

    def _get_default_project_template(self, name: str) -> Dict[str, Any]:
        clean_name = re.sub(r'[^A-Za-z0-9_\-]', '_', name)
        proj_id = uuid.uuid4().hex[:6].upper()
        return {
            "folder_name": f"{clean_name}_{proj_id}",
            "created_at": datetime.now().isoformat(),
            "current_iteration": 1,
            "current_step": 1, # ✅ ZMIANA: Zapisujemy, na którym kroku jesteśmy!
            "best_vehicle_model": "",
            "best_plate_model": "",
            "best_char_model": ""
        }


    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "projects" in data and "active_project" in data:
                        return data
            except Exception as e:
                logger.error(f"Błąd czytania rejestru kampanii: {e}")
                
        # ZMIANA: Zaczynamy z całkowicie pustym rejestrem
        return {
            "active_project": "",
            "projects": {}
        }

    def save_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Błąd zapisu rejestru kampanii: {e}")

    # --- ZARZĄDZANIE PROJEKTAMI ---

    def get_all_projects(self) -> List[str]:
        return list(self.state["projects"].keys())

    def get_active_project_name(self) -> str:
        return self.state["active_project"]

    def set_active_project(self, name: str):
        if name in self.state["projects"]:
            self.state["active_project"] = name
            self.save_state()

    def create_project(self, name: str) -> bool:
        name = name.strip()
        if not name: return False
        if name in self.state["projects"]:
            return False # Projekt o tej nazwie już istnieje!
            
        self.state["projects"][name] = self._get_default_project_template(name)
        self.state["active_project"] = name
        self.save_state()
        return True

    def delete_project(self, name: str) -> bool:
        if name not in self.state["projects"]: return False
        
        folder_name = self.state["projects"][name]["folder_name"]
        target_dir = Path(CONFIG.DIR_1_RAW) / folder_name
        if target_dir.exists():
            try: shutil.rmtree(target_dir)
            except Exception as e: logger.error(f"Nie można usunąć {target_dir}: {e}")

        del self.state["projects"][name]
        
        # ZMIANA: Jeśli usuniemy ostatni projekt, zostaje pusto.
        if self.state["active_project"] == name:
            remaining = list(self.state["projects"].keys())
            if remaining:
                self.state["active_project"] = remaining[0]
            else:
                self.state["active_project"] = ""
                
        self.save_state()
        return True

    # --- GETTERY I SETTERY (dla AKTYWNEGO projektu) ---

    def _get_active_data(self) -> Dict[str, Any]:
        act = self.state.get("active_project", "")
        return self.state["projects"].get(act, {})

    def get_safe_project_folder_name(self) -> str:
        data = self._get_active_data()
        return data.get("folder_name", "UNNAMED_PROJECT")

    def get_current_iteration_num(self) -> int:
        return self._get_active_data().get("current_iteration", 1)
        
    def get_current_step(self) -> int:
        return self._get_active_data().get("current_step", 1)

    def set_current_step(self, step: int):
        act = self.state.get("active_project", "")
        if not act or act not in self.state.get("projects", {}): return
        self.state["projects"][act]["current_step"] = step
        self.save_state()

    def advance_to_next_iteration(self):
        act = self.state.get("active_project", "")
        if not act or act not in self.state.get("projects", {}): return
        current = self.state["projects"][act].get("current_iteration", 1)
        self.state["projects"][act]["current_iteration"] = current + 1
        self.state["projects"][act]["current_step"] = 1
        self.save_state()

    def set_global_model(self, model_type: str, model_path: str):
        act = self.state.get("active_project", "")
        if not act or act not in self.state.get("projects", {}): return
        key = f"best_{model_type}_model"
        self.state["projects"][act][key] = str(model_path)
        self.save_state()

    def get_global_model(self, model_type: str) -> str:
        act = self.state.get("active_project", "")
        if not act or act not in self.state.get("projects", {}): return ""
        key = f"best_{model_type}_model"
        return self.state["projects"][act].get(key, "")

# Singleton Menadżera
CAMPAIGN = CampaignManager()