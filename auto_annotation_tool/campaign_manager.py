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

    @staticmethod
    def _iter_project_workspace_dirs(root: Path) -> list[Path]:
        auto_ann_root = root / "2_auto_annotations"
        datasets_root = root / "4_training_datasets"
        runs_root = root / "5_training_runs"
        models_root = root / "6_models"
        models_base_root = models_root / "base"
        models_trained_root = models_root / "trained"
        rankings_root = root / "7_rankings"

        return [
            root / "1_raw_images",
            auto_ann_root,
            auto_ann_root / "plates",
            auto_ann_root / "chars",
            root / "3_cropped_characters",
            datasets_root,
            datasets_root / "plates",
            datasets_root / "chars",
            datasets_root / "vehicles",
            runs_root,
            runs_root / "plates",
            runs_root / "chars",
            runs_root / "vehicles",
            models_root,
            models_base_root,
            models_base_root / "pose",
            models_base_root / "detect",
            models_trained_root,
            models_trained_root / "plates",
            models_trained_root / "chars",
            models_trained_root / "vehicles",
            rankings_root,
            rankings_root / "plates",
            rankings_root / "chars",
            rankings_root / "vehicles",
            root / "8_ocr_presets",
            root / "_campaign_state",
            root / "_campaign_state" / "ingest",
        ]

    def _ensure_project_workspace_tree(self, root: Path) -> None:
        for path in self._iter_project_workspace_dirs(root):
            path.mkdir(parents=True, exist_ok=True)

    def _get_project_default_fields(self) -> Dict[str, Any]:
        return {
            "master_pool_dir": "",
            "ingest_batch_size": 200,
            "step1_status": "pending",
        }

    def _ensure_project_defaults(self, project_data: Dict[str, Any]) -> Dict[str, Any]:
        if "step1_status" not in project_data:
            try:
                inferred_step = int(project_data.get("current_step", 1) or 1)
            except Exception:
                inferred_step = 1
            project_data["step1_status"] = "approved" if inferred_step >= 2 else "pending"
        for key, value in self._get_project_default_fields().items():
            project_data.setdefault(key, value)
        return project_data

    def _get_default_project_template(self, name: str) -> Dict[str, Any]:
        clean_name = re.sub(r'[^A-Za-z0-9_\-]', '_', name)
        proj_id = uuid.uuid4().hex[:6].upper()
        data = {
            "folder_name": f"{clean_name}_{proj_id}",
            "created_at": datetime.now().isoformat(),
            "current_iteration": 1,
            "current_step": 1,
            "step1_status": "pending",
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
        return self._ensure_project_defaults(data)


    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "projects" in data and "active_project" in data:
                        for project_name, project_data in list(data.get("projects", {}).items()):
                            if isinstance(project_data, dict):
                                data["projects"][project_name] = self._ensure_project_defaults(project_data)
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

    def _resolve_project_name(self, name: str = None) -> str:
        project_name = str(name or self.get_active_project_name() or "").strip()
        if not project_name:
            return ""
        if project_name not in self.state.get("projects", {}):
            return ""
        return project_name

    def _read_json_file(self, path: Path) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_json_file(self, path: Path, payload: Dict[str, Any]) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Nie udało się zapisać pliku {path}: {e}")
            return False

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
        self._ensure_project_workspace_tree(root)

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

    def approve_step1(self):
        """Oznacza krok 1 jako zatwierdzony."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step1_status"] = "approved"
        self.save_state()

    def reset_step1(self):
        """Resetuje stan Kroku 1 dla nowej iteracji."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step1_status"] = "pending"
        self.save_state()

    def get_step1_status(self) -> str:
        act = self.get_active_project_name()
        if not act:
            return "pending"
        return self.state["projects"][act].get("step1_status", "pending")

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
        self.state["projects"][act]["step1_status"] = "pending"
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
        root = Path(CONFIG.DIR_9_PROJECTS) / folder_name
        self._ensure_project_workspace_tree(root)
        return root

    def get_project_state_dir(self, project_name: str = None) -> Path | None:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return None

        state_dir = self.get_project_root_dir(project_name) / "_campaign_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir

    def get_project_ingest_state_dir(self, project_name: str = None) -> Path | None:
        state_dir = self.get_project_state_dir(project_name)
        if state_dir is None:
            return None

        ingest_dir = state_dir / "ingest"
        ingest_dir.mkdir(parents=True, exist_ok=True)
        return ingest_dir

    def get_active_project_root_dir(self) -> Path | None:
        act = self.get_active_project_name()
        if not act:
            return None
        return self.get_project_root_dir(act)

    def get_iteration_raw_dir(self, iteration_num: int = None, project_name: str = None) -> Path | None:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return None

        raw_dir = self.get_project_root_dir(project_name) / "1_raw_images"
        raw_dir.mkdir(parents=True, exist_ok=True)
        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1))
        return raw_dir / f"Iteracja_{iter_value:03d}"

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

    # --- INGESTIA / MASTER POOL ---

    def get_master_pool_dir(self, project_name: str = None) -> Path | None:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return None

        path_value = str(self.state["projects"][project_name].get("master_pool_dir", "") or "").strip()
        if not path_value:
            return None
        return Path(path_value)

    def set_master_pool_dir(self, path: str | Path, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False

        target = Path(path).expanduser()
        self.state["projects"][project_name]["master_pool_dir"] = str(target)
        self.save_state()
        return True

    def get_ingest_batch_size(self, project_name: str = None) -> int:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return 200
        try:
            value = int(self.state["projects"][project_name].get("ingest_batch_size", 200))
        except Exception:
            value = 200
        return max(1, value)

    def set_ingest_batch_size(self, batch_size: int, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False
        try:
            value = max(1, int(batch_size))
        except Exception:
            value = 200
        self.state["projects"][project_name]["ingest_batch_size"] = value
        self.save_state()
        return True

    def get_ingest_manifest_path(self, iteration_num: int = None, project_name: str = None) -> Path | None:
        ingest_dir = self.get_project_ingest_state_dir(project_name)
        if ingest_dir is None:
            return None
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return None
        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1))
        return ingest_dir / f"iter_{iter_value:03d}_manifest.json"

    def get_ingest_balance_snapshot_path(self, project_name: str = None) -> Path | None:
        ingest_dir = self.get_project_ingest_state_dir(project_name)
        if ingest_dir is None:
            return None
        return ingest_dir / "balance_snapshot.json"

    def get_latest_ingest_plan_path(self, project_name: str = None) -> Path | None:
        ingest_dir = self.get_project_ingest_state_dir(project_name)
        if ingest_dir is None:
            return None
        return ingest_dir / "latest_plan.json"

    def load_latest_ingest_plan(self, project_name: str = None) -> Dict[str, Any]:
        plan_path = self.get_latest_ingest_plan_path(project_name)
        if plan_path is None or not plan_path.exists():
            return {}
        return self._read_json_file(plan_path)

    def save_latest_ingest_plan(self, plan: Dict[str, Any], project_name: str = None) -> Path | None:
        plan_path = self.get_latest_ingest_plan_path(project_name)
        if plan_path is None:
            return None
        if self._write_json_file(plan_path, plan):
            return plan_path
        return None

    def load_ingest_manifest(self, iteration_num: int = None, project_name: str = None) -> Dict[str, Any]:
        manifest_path = self.get_ingest_manifest_path(iteration_num, project_name)
        if manifest_path is None or not manifest_path.exists():
            return {}
        return self._read_json_file(manifest_path)

    def save_ingest_manifest(
        self,
        manifest: Dict[str, Any],
        iteration_num: int = None,
        project_name: str = None,
    ) -> Path | None:
        manifest_path = self.get_ingest_manifest_path(iteration_num, project_name)
        if manifest_path is None:
            return None
        if self._write_json_file(manifest_path, manifest):
            return manifest_path
        return None

    def save_ingest_balance_snapshot(self, snapshot: Dict[str, Any], project_name: str = None) -> Path | None:
        snapshot_path = self.get_ingest_balance_snapshot_path(project_name)
        if snapshot_path is None:
            return None
        if self._write_json_file(snapshot_path, snapshot):
            return snapshot_path
        return None

    def load_ingest_balance_snapshot(self, project_name: str = None) -> Dict[str, Any]:
        snapshot_path = self.get_ingest_balance_snapshot_path(project_name)
        if snapshot_path is None or not snapshot_path.exists():
            return {}
        return self._read_json_file(snapshot_path)

    def get_used_image_registry(self, project_name: str = None) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {
                "source_keys": [],
                "filenames": [],
                "total_source_keys": 0,
                "total_filenames": 0,
            }

        source_keys = set()
        filenames = set()

        ingest_dir = self.get_project_ingest_state_dir(project_name)
        if ingest_dir is not None and ingest_dir.exists():
            for manifest_path in ingest_dir.glob("iter_*_manifest.json"):
                manifest = self._read_json_file(manifest_path)
                for item in manifest.get("selected_images", []) or []:
                    if not isinstance(item, dict):
                        continue
                    source_key = str(item.get("source_key", "") or "").strip().lower()
                    if source_key:
                        source_keys.add(source_key)
                    name = str(item.get("name", "") or "").strip().lower()
                    if name:
                        filenames.add(name)

        raw_dir = self.get_project_root_dir(project_name) / "1_raw_images"
        if raw_dir.exists() and raw_dir.is_dir():
            for image_path in raw_dir.rglob("*"):
                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS:
                    filenames.add(image_path.name.lower())

        return {
            "source_keys": sorted(source_keys),
            "filenames": sorted(filenames),
            "total_source_keys": len(source_keys),
            "total_filenames": len(filenames),
        }

    def refresh_ingest_balance_snapshot(self, project_name: str = None) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {}

        project_root = self.get_project_root_dir(project_name)
        used_registry = self.get_used_image_registry(project_name)

        from .campaign_ingest_planner import CampaignIngestPlanner

        planner = CampaignIngestPlanner()
        balance_info = planner.collect_project_training_balance(project_root)
        snapshot = {
            "project": project_name,
            "generated_at": datetime.now().isoformat(),
            "iteration": int(self.state["projects"][project_name].get("current_iteration", 1)),
            "master_pool_dir": str(self.get_master_pool_dir(project_name) or ""),
            "used_source_images": int(used_registry.get("total_source_keys", 0)),
            "used_filenames": int(used_registry.get("total_filenames", 0)),
            **balance_info,
        }
        self.save_ingest_balance_snapshot(snapshot, project_name)
        return snapshot

    def build_ingest_plan(
        self,
        batch_size: int = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {"ok": False, "error": "Brak aktywnego projektu."}

        master_pool_dir = self.get_master_pool_dir(project_name)
        if master_pool_dir is None:
            return {"ok": False, "error": "Nie skonfigurowano master pool dla projektu."}
        if not master_pool_dir.exists() or not master_pool_dir.is_dir():
            return {"ok": False, "error": f"Master pool nie istnieje: {master_pool_dir}"}

        from .campaign_ingest_planner import CampaignIngestPlanner

        planner = CampaignIngestPlanner()
        used_registry = self.get_used_image_registry(project_name)
        balance_snapshot = self.refresh_ingest_balance_snapshot(project_name)
        effective_batch = max(1, int(batch_size or self.get_ingest_batch_size(project_name)))

        plan = planner.plan_from_master_pool(
            master_pool_dir=master_pool_dir,
            current_balance=balance_snapshot.get("char_balance", {}),
            used_source_keys=used_registry.get("source_keys", []),
            used_filenames=used_registry.get("filenames", []),
            batch_size=effective_batch,
        )
        plan["ok"] = True
        plan["project"] = project_name
        plan["iteration"] = int(self.state["projects"][project_name].get("current_iteration", 1))

        self.save_latest_ingest_plan(plan, project_name)

        return plan

    def record_iteration_ingest(
        self,
        source_dir: str | Path,
        selected_source_files: List[str | Path],
        selection_mode: str = "manual",
        proposal_summary: Dict[str, Any] | None = None,
        project_name: str = None,
    ) -> Path | None:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return None

        source_dir = Path(source_dir)
        if not source_dir.exists() or not source_dir.is_dir():
            return None

        iteration = int(self.state["projects"][project_name].get("current_iteration", 1))
        target_dir = self.get_iteration_raw_dir(iteration, project_name)
        if target_dir is None:
            return None
        target_dir.mkdir(parents=True, exist_ok=True)

        from .campaign_ingest_planner import CampaignIngestPlanner

        planner = CampaignIngestPlanner()
        master_pool_dir = self.get_master_pool_dir(project_name)

        selected_images = []
        total_hist: Dict[str, int] = {ch: 0 for ch in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"}

        for item in selected_source_files:
            source_path = Path(item)
            if not source_path.is_absolute():
                source_path = source_dir / source_path.name
            if not source_path.exists() or not source_path.is_file():
                continue

            true_texts = planner.extract_true_texts_from_filename(source_path.name)
            char_hist = planner.build_char_histogram(true_texts)
            for ch, value in char_hist.items():
                total_hist[ch] = total_hist.get(ch, 0) + int(value)

            selected_images.append({
                "name": source_path.name,
                "source_path": str(source_path.resolve()),
                "source_key": planner.make_source_key(source_path, master_pool_dir=master_pool_dir),
                "target_path": str((target_dir / source_path.name).resolve()),
                "ground_truth_texts": true_texts,
                "char_histogram": char_hist,
            })

        manifest = {
            "project": project_name,
            "iteration": iteration,
            "created_at": datetime.now().isoformat(),
            "selection_mode": str(selection_mode or "manual").strip() or "manual",
            "source_dir": str(source_dir.resolve()),
            "target_dir": str(target_dir.resolve()),
            "master_pool_dir": str(master_pool_dir.resolve()) if master_pool_dir else "",
            "selected_count": len(selected_images),
            "char_histogram": {k: int(v) for k, v in total_hist.items() if int(v) > 0},
            "selected_images": selected_images,
            "proposal_summary": proposal_summary or {},
        }

        return self.save_ingest_manifest(manifest, iteration, project_name)

# Singleton Menadżera
CAMPAIGN = CampaignManager()
