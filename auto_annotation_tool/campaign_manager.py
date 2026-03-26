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
            "current_step": 1,
            "step2_status": "pending",
            "step2_staging_run": "",
            "best_vehicle_model": "",
            "best_plate_model": "",
            "best_char_model": "",
            "step3_status": "pending",
            "step3_substep": 1,
            "step3_stage1_done": False,
            "step3_stage2_done": False,
        }


    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "projects" in data and "active_project" in data:
                        data["active_project"] = ""
                        return data
            except Exception as e:
                logger.error(f"Błąd czytania rejestru kampanii: {e}")
                
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
        # Zwracaj aktywny projekt tylko wtedy, gdy nadal istnieje w rejestrze.
        act = self.state.get("active_project", "")
        if not act:
            return ""
        if act not in self.state.get("projects", {}):
            return ""
        return act

    def set_active_project(self, name: str):
        if name in self.state["projects"]:
            self.state["active_project"] = name
            self.save_state()

    def clear_active_project(self):
        """Czyści aktywny projekt i przełącza aplikację do trybu swobodnego."""
        self.state["active_project"] = ""
        self.save_state()

    def create_project(self, name: str) -> bool:
        name = name.strip()
        if not name:
            return False
        if name in self.state["projects"]:
            return False

        self.state["projects"][name] = self._get_default_project_template(name)
        self.state["active_project"] = name
        
        self.save_state()

        # Buduj pełne drzewo katalogów projektu.
        root = self.get_project_root_dir(name)
        for p in [
            root / "1_raw_images",
            root / "2_auto_annotations",
            root / "3_cropped_characters",
            root / "4_training_datasets",
            root / "5_training_runs",
            root / "6_models",
            root / "7_rankings",
            root / "8_ocr_presets",
        ]:
            p.mkdir(parents=True, exist_ok=True)

        return True

    def delete_project(self, name: str) -> bool:
        if name not in self.state["projects"]:
            return False

        # Usuń cały katalog projektu z dysku.
        root = self.get_project_root_dir(name)
        try:
            if root.exists():
                shutil.rmtree(root)
        except Exception as e:
            logger.error(f"Nie można usunąć projektu {root}: {e}")

        del self.state["projects"][name]

        if self.state.get("active_project") == name:
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

    def get_project_created_at(self, name: str = None) -> str:
        project_name = (name or self.get_active_project_name() or "").strip()
        if not project_name:
            return ""

        project_data = self.state.get("projects", {}).get(project_name, {})
        return str(project_data.get("created_at", "") or "").strip()

    def get_current_iteration_num(self) -> int:
        return self._get_active_data().get("current_iteration", 1)
        
    def get_current_step(self) -> int:
        return self._get_active_data().get("current_step", 1)

    def set_current_step(self, step: int):
        act = self.state.get("active_project", "")
        if not act or act not in self.state.get("projects", {}): return
        self.state["projects"][act]["current_step"] = step
        self.save_state()

    def set_step2_generated(self, staging_run_path: str):
        """Zapisuje informację, że krok 2 został wykonany, ale niezatwierdzony."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step2_status"] = "generated"
        self.state["projects"][act]["step2_staging_run"] = str(staging_run_path)
        self.save_state()

    def approve_step2(self):
        """Oznacza krok 2 jako zatwierdzony."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step2_status"] = "approved"
        self.save_state()

    def reset_step2(self):
        """Resetuje stan Kroku 2 (Autoanotacja) do oczekiwania na nowe zatwierdzenie."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step2_status"] = "pending"
        self.state["projects"][act]["step2_staging_run"] = ""
        self.save_state()

    def get_step2_status(self) -> str:
        act = self.get_active_project_name()
        if not act:
            return "pending"
        return self.state["projects"][act].get("step2_status", "pending")

    def get_step2_staging_run(self) -> str:
        act = self.get_active_project_name()
        if not act:
            return ""
        return self.state["projects"][act].get("step2_staging_run", "")
    
    def set_step3_needs_rework(self):
        """Oznacza krok 3 jako wymagający poprawy."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step3_status"] = "needs_rework"
        self.save_state()

    def approve_step3(self):
        """Oznacza krok 3 jako zakończony powodzeniem."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step3_status"] = "approved"
        self.save_state()

    def reset_step3(self):
        """Resetuje stan kroku 3."""
        act = self.get_active_project_name()
        if not act:
            return

        self.state["projects"][act]["step3_status"] = "pending"
        self.state["projects"][act]["step3_substep"] = 1
        self.state["projects"][act]["step3_stage1_done"] = False
        self.state["projects"][act]["step3_stage2_done"] = False
        self.save_state()

    def get_step3_status(self) -> str:
        act = self.get_active_project_name()
        if not act:
            return "pending"
        return self.state["projects"][act].get("step3_status", "pending")
    
    def get_step3_substep(self) -> int:
        act = self.get_active_project_name()
        if not act:
            return 1
        return int(self.state["projects"][act].get("step3_substep", 1))


    def set_step3_substep(self, value: int):
        act = self.get_active_project_name()
        if not act:
            return

        value = int(value)
        if value < 1:
            value = 1
        if value > 3:
            value = 3

        self.state["projects"][act]["step3_substep"] = value
        self.save_state()


    def is_step3_stage1_done(self) -> bool:
        act = self.get_active_project_name()
        if not act:
            return False
        return bool(self.state["projects"][act].get("step3_stage1_done", False))


    def set_step3_stage1_done(self, done: bool):
        act = self.get_active_project_name()
        if not act:
            return

        self.state["projects"][act]["step3_stage1_done"] = bool(done)
        self.save_state()


    def is_step3_stage2_done(self) -> bool:
        act = self.get_active_project_name()
        if not act:
            return False
        return bool(self.state["projects"][act].get("step3_stage2_done", False))


    def set_step3_stage2_done(self, done: bool):
        act = self.get_active_project_name()
        if not act:
            return

        self.state["projects"][act]["step3_stage2_done"] = bool(done)
        self.save_state()


    def reset_step3_progress(self):
        act = self.get_active_project_name()
        if not act:
            return

        self.state["projects"][act]["step3_substep"] = 1
        self.state["projects"][act]["step3_stage1_done"] = False
        self.state["projects"][act]["step3_stage2_done"] = False
        self.save_state()

    def advance_to_next_iteration(self):
        act = self.state.get("active_project", "")
        if not act or act not in self.state.get("projects", {}): return
        current = self.state["projects"][act].get("current_iteration", 1)
        self.state["projects"][act]["current_iteration"] = current + 1
        self.state["projects"][act]["current_step"] = 1
        # Nowa iteracja zaczyna się od pełnego resetu stanów etapów zależnych od danych wejściowych.
        self.state["projects"][act]["step2_status"] = "pending"
        self.state["projects"][act]["step2_staging_run"] = ""
        self.state["projects"][act]["step3_status"] = "pending"
        self.state["projects"][act]["step3_substep"] = 1
        self.state["projects"][act]["step3_stage1_done"] = False
        self.state["projects"][act]["step3_stage2_done"] = False
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
    def get_project_root_dir(self, project_name: str) -> Path:
        folder_name = self.state["projects"][project_name]["folder_name"]
        return Path(CONFIG.DIR_9_PROJECTS) / folder_name

    def get_active_project_root_dir(self) -> Path | None:
        act = self.get_active_project_name()
        if not act:
            return None
        return self.get_project_root_dir(act)

    def get_dir(self, key: str) -> Path | None:
        """Zwraca katalog dla aktywnego projektu."""
        root = self.get_active_project_root_dir()
        if root is None:
            return None

        mapping = {
            "raw": root / "1_raw_images",
            "auto_ann": root / "2_auto_annotations",
            "chars": root / "3_cropped_characters",
            "datasets": root / "4_training_datasets",
            "runs": root / "5_training_runs",
            "models": root / "6_models",
            "rankings": root / "7_rankings",
            "presets": root / "8_ocr_presets",
        }
        return mapping.get(key) 

    def get_staging_dir(self, key: str):
        """
        Zwraca katalog tymczasowy aktywnego projektu.
        Obecnie wykorzystywany jest staging dla autoanotacji.
        """
        root = self.get_active_project_root_dir()
        if root is None:
            return None

        staging_root = root / "_staging"
        mapping = {
            "auto_ann": staging_root / "auto_annotations",
        }
        return mapping.get(key)   

# Singleton Menadżera
CAMPAIGN = CampaignManager()
