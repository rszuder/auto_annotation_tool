#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Menadżer Kampanii ALPR (Active Learning Wizard) - Wersja Multi-Project.
Zarządza listą projektów, iteracjami i fizycznym czyszczeniem dysku.
"""

import hashlib
import json
import uuid
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from time import perf_counter
from typing import Dict, Any, List

from .config import CONFIG, logger


class CampaignManager:
    def __init__(self):
        self.state_file = CONFIG.WORKSPACE_DIR / "campaigns_registry.json"
        self.state = self._load_state()
        self._plate_approved_stats_cache: Dict[tuple[str, int, int], Dict[str, Any]] = {}
        self._artifact_registry_cache: Dict[tuple[str, int, int], Dict[str, Any]] = {}

    @staticmethod
    def _iter_project_workspace_dirs(root: Path) -> list[Path]:
        auto_ann_root = root / "2_auto_annotations"
        datasets_root = root / "4_training_datasets"
        runs_root = root / "5_training_runs"
        models_root = root / "6_models"
        rankings_root = root / "7_rankings"
        staging_root = root / "_staging"

        return [
            root / "1_raw_images",
            auto_ann_root,
            root / "3_cropped_characters",
            datasets_root,
            runs_root,
            models_root,
            rankings_root,
            root / "8_ocr_presets",
            staging_root,
            staging_root / "auto_annotations",
            staging_root / "plate_manual_stage",
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
            "project_start_mode": "",
            "project_start_scope_plate_run": "",
            "project_start_scope_plate_model": "",
            "project_start_scope_char_model": "",
            "step1_source_manual_clear_iteration": 0,
            "step1_restored_image_source_dir": "",
            "step1_status": "pending",
            "iteration_target": "",
            "last_iteration_target": "",
            "last_plate_manual_source_run": "",
            "last_plate_manual_source_xml": "",
            "last_plate_manual_source_input": "",
            "last_plate_training_dataset": "",
            "last_plate_training_source_run": "",
            "last_plate_training_source_xml": "",
            "step4_finish_ready": False,
            "step4_last_run_id": "",
            "step4_last_target": "",
            "step4_last_iteration": 0,
            "step3_extract_entry_mode": "",
            "step3_extract_workflow_step": "entry",
            "step3_extract_annotation_run_dir": "",
            "step3_extract_xml_path": "",
            "step3_extract_images_dir": "",
            "step3_preview_dir": "",
            "project_status": "active",
            "project_paused_at": "",
            "project_completed_at": "",
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
            "project_start_mode": "",
            "project_start_scope_plate_run": "",
            "project_start_scope_plate_model": "",
            "project_start_scope_char_model": "",
            "step1_status": "pending",
            "step2_status": "pending",
            "step2_staging_run": "",
            "iteration_target": "",
            "last_iteration_target": "",
            "last_plate_manual_source_run": "",
            "last_plate_manual_source_xml": "",
            "last_plate_manual_source_input": "",
            "last_plate_training_dataset": "",
            "last_plate_training_source_run": "",
            "last_plate_training_source_xml": "",
            "step4_finish_ready": False,
            "step4_last_run_id": "",
            "step4_last_target": "",
            "step4_last_iteration": 0,
            "best_vehicle_model": "",
            "best_plate_model": "",
            "best_char_model": "",
            "step3_status": "pending",
            "step3_substep": 1,
            "step3_stage1_done": False,
            "step3_stage2_done": False,
            "step3_extract_entry_mode": "",
            "step3_extract_workflow_step": "entry",
            "step3_extract_annotation_run_dir": "",
            "step3_extract_xml_path": "",
            "step3_extract_images_dir": "",
            "step3_preview_dir": "",
            "project_status": "active",
            "project_paused_at": "",
            "project_completed_at": "",
        }
        return self._ensure_project_defaults(data)


    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8-sig') as f:
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
            with open(path, "r", encoding="utf-8-sig") as handle:
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

    @staticmethod
    def _normalize_project_start_mode(mode: str | None) -> str:
        value = str(mode or "").strip().lower()
        if not value:
            return ""
        if value in {"assets", "import", "resource", "resources", "mam_zasoby"}:
            return "assets"
        return "fresh"

    def set_project_start_mode(self, mode: str | None, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False

        self.state["projects"][project_name]["project_start_mode"] = self._normalize_project_start_mode(mode)
        self.save_state()
        return True

    def get_project_start_mode(self, project_name: str = None) -> str:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return ""

        raw_value = self.state["projects"][project_name].get("project_start_mode", "")
        return self._normalize_project_start_mode(raw_value)

    @staticmethod
    def _normalize_project_start_asset_scope(scope: str | None) -> str:
        value = str(scope or "").strip().lower()
        if value in {"project", "freemode", "na"}:
            return value
        return ""

    @staticmethod
    def _project_start_asset_scope_state_key(row_key: str | None) -> str:
        normalized = str(row_key or "").strip().lower()
        mapping = {
            "plate_run": "project_start_scope_plate_run",
            "plate_model": "project_start_scope_plate_model",
            "char_model": "project_start_scope_char_model",
        }
        return str(mapping.get(normalized) or "").strip()

    def set_project_start_asset_scope(self, row_key: str, scope: str | None, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False

        state_key = self._project_start_asset_scope_state_key(row_key)
        if not state_key:
            return False

        normalized = self._normalize_project_start_asset_scope(scope)
        self.state["projects"][project_name][state_key] = normalized
        self.save_state()
        return True

    def get_project_start_asset_scope(self, row_key: str, project_name: str = None) -> str:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return ""

        state_key = self._project_start_asset_scope_state_key(row_key)
        if not state_key:
            return ""

        raw_value = self.state["projects"][project_name].get(state_key, "")
        return self._normalize_project_start_asset_scope(raw_value)

    @staticmethod
    def _normalize_iteration_target(target: str | None) -> str:
        value = str(target or "").strip().lower()
        if value in {"plate", "plates", "tablica", "tablice", "pose"}:
            return "plate"
        if value in {"char", "chars", "character", "characters", "znak", "znaki"}:
            return "char"
        return ""

    def set_iteration_target(self, target: str | None):
        act = self.get_active_project_name()
        if not act:
            return

        self.state["projects"][act]["iteration_target"] = self._normalize_iteration_target(target)
        self.save_state()

    def get_iteration_target(self) -> str:
        act = self.get_active_project_name()
        if not act:
            return ""
        return self._normalize_iteration_target(self.state["projects"][act].get("iteration_target", ""))

    def clear_iteration_target(self):
        self.set_iteration_target("")

    def get_last_iteration_target(self) -> str:
        act = self.get_active_project_name()
        if not act:
            return ""
        return self._normalize_iteration_target(self.state["projects"][act].get("last_iteration_target", ""))

    def get_project_status(self, project_name: str = None) -> str:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return "active"

        status = str(self.state["projects"][project_name].get("project_status", "active") or "").strip().lower()
        if status == "completed":
            return "completed"
        if status == "paused":
            return "paused"
        return "active"

    def is_project_completed(self, project_name: str = None) -> bool:
        return self.get_project_status(project_name) == "completed"

    def is_project_paused(self, project_name: str = None) -> bool:
        return self.get_project_status(project_name) == "paused"

    def get_project_paused_at(self, project_name: str = None) -> str:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return ""
        return str(self.state["projects"][project_name].get("project_paused_at", "") or "").strip()

    def get_project_completed_at(self, project_name: str = None) -> str:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return ""
        return str(self.state["projects"][project_name].get("project_completed_at", "") or "").strip()

    def pause_project(self, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False

        project_data = self.state["projects"][project_name]
        project_data["project_status"] = "paused"
        project_data["project_paused_at"] = datetime.now().isoformat()
        project_data["project_completed_at"] = ""
        self.save_state()
        return True

    def complete_project(self, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False

        project_data = self.state["projects"][project_name]
        if int(project_data.get("current_step", 1) or 1) < 5:
            project_data["current_step"] = 5
        project_data["project_status"] = "completed"
        project_data["project_paused_at"] = ""
        project_data["project_completed_at"] = datetime.now().isoformat()
        self.save_state()
        return True

    def reopen_project(self, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False

        project_data = self.state["projects"][project_name]
        project_data["project_status"] = "active"
        project_data["project_paused_at"] = ""
        project_data["project_completed_at"] = ""
        self.save_state()
        return True

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

    def set_step3_ready(self):
        """Oznacza krok 3 jako gotowy do zatwierdzenia w wizardzie."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step3_status"] = "ready"
        self.save_state()

    def approve_step3(self):
        """Oznacza krok 3 jako zakończony powodzeniem."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step3_status"] = "approved"
        self.save_state()

    def set_step3_pending(self):
        """Przywraca krok 3 do stanu w toku bez resetu zapisanej pracy."""
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step3_status"] = "pending"
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
        self.state["projects"][act]["step3_extract_entry_mode"] = ""
        self.state["projects"][act]["step3_extract_workflow_step"] = "entry"
        self.state["projects"][act]["step3_extract_annotation_run_dir"] = ""
        self.state["projects"][act]["step3_extract_xml_path"] = ""
        self.state["projects"][act]["step3_extract_images_dir"] = ""
        self.state["projects"][act]["step3_preview_dir"] = ""
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
        self.state["projects"][act]["step3_extract_entry_mode"] = ""
        self.state["projects"][act]["step3_extract_workflow_step"] = "entry"
        self.state["projects"][act]["step3_extract_annotation_run_dir"] = ""
        self.state["projects"][act]["step3_extract_xml_path"] = ""
        self.state["projects"][act]["step3_extract_images_dir"] = ""
        self.state["projects"][act]["step3_preview_dir"] = ""
        self.save_state()

    def get_step3_extract_state(self) -> Dict[str, str]:
        act = self.get_active_project_name()
        if not act:
            return {
                "entry_mode": "",
                "workflow_step": "entry",
                "annotation_run_dir": "",
                "xml_path": "",
                "images_dir": "",
            }

        project_data = self.state["projects"][act]
        return {
            "entry_mode": str(project_data.get("step3_extract_entry_mode", "") or "").strip(),
            "workflow_step": str(project_data.get("step3_extract_workflow_step", "entry") or "entry").strip(),
            "annotation_run_dir": str(project_data.get("step3_extract_annotation_run_dir", "") or "").strip(),
            "xml_path": str(project_data.get("step3_extract_xml_path", "") or "").strip(),
            "images_dir": str(project_data.get("step3_extract_images_dir", "") or "").strip(),
        }

    def get_step3_preview_dir(self) -> str:
        act = self.get_active_project_name()
        if not act:
            return ""
        value = str(self.state["projects"][act].get("step3_preview_dir", "") or "").strip()
        if value:
            return value

        try:
            if self.state_file.exists():
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                project_data = dict((loaded.get("projects") or {}).get(act) or {})
                fallback_value = str(project_data.get("step3_preview_dir", "") or "").strip()
                if fallback_value:
                    try:
                        self.state["projects"][act]["step3_preview_dir"] = fallback_value
                    except Exception:
                        pass
                    return fallback_value
        except Exception:
            pass

        return ""

    def set_step3_preview_dir(self, preview_dir: str | None) -> None:
        act = self.get_active_project_name()
        if not act:
            return
        self.state["projects"][act]["step3_preview_dir"] = str(preview_dir or "").strip()
        self.save_state()

    def set_step3_extract_state(
        self,
        *,
        entry_mode: str | None = None,
        workflow_step: str | None = None,
        annotation_run_dir: str | None = None,
        xml_path: str | None = None,
        images_dir: str | None = None,
    ) -> None:
        act = self.get_active_project_name()
        if not act:
            return

        project_data = self.state["projects"][act]

        if entry_mode is not None:
            project_data["step3_extract_entry_mode"] = str(entry_mode or "").strip()
        if workflow_step is not None:
            project_data["step3_extract_workflow_step"] = str(workflow_step or "entry").strip() or "entry"
        if annotation_run_dir is not None:
            project_data["step3_extract_annotation_run_dir"] = str(annotation_run_dir or "").strip()
        if xml_path is not None:
            project_data["step3_extract_xml_path"] = str(xml_path or "").strip()
        if images_dir is not None:
            project_data["step3_extract_images_dir"] = str(images_dir or "").strip()

        self.save_state()

    def _clone_iteration_ingest_manifest(
        self,
        source_iteration: int,
        target_iteration: int,
        target_raw_dir: Path,
        project_name: str,
    ) -> bool:
        manifest = self.load_ingest_manifest(source_iteration, project_name)
        if not manifest:
            return False

        selected_images = []
        for item in manifest.get("selected_images", []) or []:
            if not isinstance(item, dict):
                continue
            cloned_item = dict(item)
            item_name = str(cloned_item.get("name", "") or "").strip()
            if not item_name:
                target_path = str(cloned_item.get("target_path", "") or "").strip()
                if target_path:
                    item_name = Path(target_path).name
            if not item_name:
                continue
            cloned_item["target_path"] = str((target_raw_dir / item_name).resolve())
            selected_images.append(cloned_item)

        cloned_manifest = dict(manifest)
        cloned_manifest["iteration"] = int(target_iteration)
        cloned_manifest["created_at"] = datetime.now().isoformat()
        cloned_manifest["selection_mode"] = "iteration_reuse"
        cloned_manifest["reused_from_iteration"] = int(source_iteration)
        cloned_manifest["target_dir"] = str(target_raw_dir.resolve())
        cloned_manifest["selected_images"] = selected_images
        cloned_manifest["selected_count"] = int(
            len(selected_images) or manifest.get("selected_count", 0) or 0
        )

        return bool(self.save_ingest_manifest(cloned_manifest, target_iteration, project_name))

    def _carry_iteration_input_forward(
        self,
        source_iteration: int,
        target_iteration: int,
        project_name: str,
    ) -> Dict[str, Any]:
        source_raw_dir = self.get_iteration_raw_dir(source_iteration, project_name)
        target_raw_dir = self.get_iteration_raw_dir(target_iteration, project_name)
        if source_raw_dir is None or target_raw_dir is None:
            return {"ok": False, "reason": "missing_project_dirs"}

        if not source_raw_dir.exists() or not source_raw_dir.is_dir():
            return {"ok": False, "reason": "missing_source_dir"}

        image_files = [
            path for path in source_raw_dir.iterdir()
            if path.is_file() and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
        ]
        if not image_files:
            return {"ok": False, "reason": "missing_images"}

        target_raw_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for source_path in image_files:
            shutil.copy2(source_path, target_raw_dir / source_path.name)
            copied += 1

        manifest_cloned = self._clone_iteration_ingest_manifest(
            source_iteration=source_iteration,
            target_iteration=target_iteration,
            target_raw_dir=target_raw_dir,
            project_name=project_name,
        )

        return {
            "ok": True,
            "source_dir": str(source_raw_dir.resolve()),
            "target_dir": str(target_raw_dir.resolve()),
            "copied_images": int(copied),
            "manifest_cloned": bool(manifest_cloned),
        }

    def _resolve_previous_iteration_image_source_for_e1(
        self,
        *,
        project_name: str,
        current_iteration: int,
        project_data: Dict[str, Any],
    ) -> str:
        stage_state = self.get_manual_plate_stage_images_state(
            source_iteration=current_iteration,
            project_name=project_name,
        )
        if int(stage_state.get("image_count", 0) or 0) > 0:
            stage_images_dir = str(stage_state.get("images_dir") or "").strip()
            if stage_images_dir:
                return stage_images_dir
        return ""

    def get_manual_plate_stage_images_state(
        self,
        source_iteration: int = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {"ok": False, "image_count": 0, "images_dir": "", "stage_dir": ""}

        try:
            iter_value = int(source_iteration or self.state["projects"][project_name].get("current_iteration", 1) or 1)
        except Exception:
            iter_value = 1

        stage_root = self.get_staging_dir("plate_stage")
        if stage_root is None:
            return {"ok": False, "image_count": 0, "images_dir": "", "stage_dir": ""}

        stage_root = Path(stage_root)
        stage_candidates = [
            (stage_root / f"Iteracja_{iter_value:03d}", stage_root / f"Iteracja_{iter_value:03d}" / "images"),
            (stage_root, stage_root / "images"),
        ]

        for stage_dir, images_dir in stage_candidates:
            try:
                if not images_dir.exists() or not images_dir.is_dir():
                    continue
                count = 0
                for image_path in images_dir.iterdir():
                    if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS:
                        count += 1
                if count > 0:
                    return {
                        "ok": True,
                        "image_count": int(count),
                        "images_dir": str(images_dir.resolve()),
                        "stage_dir": str(stage_dir.resolve()),
                        "iteration": int(iter_value),
                    }
            except Exception:
                continue

        return {
            "ok": False,
            "image_count": 0,
            "images_dir": "",
            "stage_dir": str((stage_root / f"Iteracja_{iter_value:03d}").resolve()),
            "iteration": int(iter_value),
        }

    def ensure_step1_image_source_restored_from_previous_iteration(self, project_name: str = None) -> str:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return ""
        project_data = self.state.get("projects", {}).get(project_name)
        if not isinstance(project_data, dict):
            return ""
        try:
            current_step = int(project_data.get("current_step", 1) or 1)
            current_iteration = int(project_data.get("current_iteration", 1) or 1)
        except Exception:
            return ""
        if current_step != 1 or current_iteration <= 1:
            return ""
        if str(project_data.get("master_pool_dir", "") or "").strip():
            return ""
        try:
            manual_clear_iteration = int(project_data.get("step1_source_manual_clear_iteration", 0) or 0)
        except Exception:
            manual_clear_iteration = 0
        if manual_clear_iteration == current_iteration:
            return ""

        previous_source = self._resolve_previous_iteration_image_source_for_e1(
            project_name=project_name,
            current_iteration=current_iteration - 1,
            project_data=project_data,
        )
        if not previous_source:
            return ""

        project_data["master_pool_dir"] = previous_source
        project_data["step1_restored_image_source_dir"] = previous_source
        project_data["step1_source_manual_clear_iteration"] = 0
        self.save_state()
        return previous_source

    def _seed_iteration_from_master_pool(
        self,
        *,
        source_iteration: int,
        target_iteration: int,
        project_name: str,
    ) -> Dict[str, Any]:
        started_at = perf_counter()
        master_pool_dir = self.get_master_pool_dir(project_name)
        target_raw_dir = self.get_iteration_raw_dir(target_iteration, project_name)
        if master_pool_dir is None or target_raw_dir is None:
            return {"ok": False, "reason": "missing_project_dirs"}
        if not master_pool_dir.exists() or not master_pool_dir.is_dir():
            return {"ok": False, "reason": "missing_master_pool"}

        from .campaign_ingest_planner import CampaignIngestPlanner, CHAR_ALPHABET

        planner = CampaignIngestPlanner()
        used_registry = self.get_used_image_registry(project_name)
        balance_snapshot = self.refresh_ingest_balance_snapshot(project_name)
        source_manifest = self.load_ingest_manifest(source_iteration, project_name)

        preferred_batch_size = 0
        try:
            preferred_batch_size = int(
                source_manifest.get("selected_count", 0)
                or dict(source_manifest.get("proposal_summary") or {}).get("current_iteration_package_count", 0)
                or 0
            )
        except Exception:
            preferred_batch_size = 0

        if preferred_batch_size <= 0:
            try:
                source_raw_dir = self.get_iteration_raw_dir(source_iteration, project_name)
                if source_raw_dir is not None and source_raw_dir.exists():
                    preferred_batch_size = int(
                        len(
                            [
                                path for path in source_raw_dir.iterdir()
                                if path.is_file() and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
                            ]
                        )
                    )
            except Exception:
                preferred_batch_size = 0

        if preferred_batch_size <= 0:
            preferred_batch_size = 200

        plan = planner.plan_from_master_pool(
            master_pool_dir=master_pool_dir,
            current_balance=balance_snapshot.get("char_balance", {}),
            used_source_keys=used_registry.get("source_keys", []),
            used_filenames=used_registry.get("filenames", []),
            batch_size=preferred_batch_size,
        )

        selected_items = list(plan.get("selected", []) or [])
        if not selected_items:
            return {
                "ok": False,
                "reason": "missing_remaining_images",
                "source_dir": str(master_pool_dir.resolve()),
                "target_dir": str(target_raw_dir.resolve()),
                "copied_images": 0,
                "manifest_cloned": False,
            }

        target_raw_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        selected_images: list[Dict[str, Any]] = []
        total_hist: Dict[str, int] = {ch: 0 for ch in CHAR_ALPHABET}

        for item in selected_items:
            try:
                source_path = Path(str(item.get("source_path", "") or "").strip())
            except Exception:
                continue
            if not source_path.exists() or not source_path.is_file():
                continue

            target_path = target_raw_dir / source_path.name
            shutil.copy2(source_path, target_path)
            copied += 1

            char_hist = {
                str(ch): int(value)
                for ch, value in dict(item.get("char_histogram") or {}).items()
                if int(value or 0) > 0
            }
            for ch, value in char_hist.items():
                total_hist[ch] = total_hist.get(ch, 0) + int(value)

            selected_images.append(
                {
                    "name": source_path.name,
                    "source_path": str(source_path.resolve()),
                    "source_key": str(item.get("source_key", "") or "").strip(),
                    "target_path": str(target_path.resolve()),
                    "ground_truth_texts": list(item.get("ground_truth_texts", []) or []),
                    "char_histogram": char_hist,
                    "score": float(item.get("score", 0.0) or 0.0),
                    "score_details": dict(item.get("score_details", {}) or {}),
                }
            )

        if copied <= 0:
            return {
                "ok": False,
                "reason": "copy_failed",
                "source_dir": str(master_pool_dir.resolve()),
                "target_dir": str(target_raw_dir.resolve()),
                "copied_images": 0,
                "manifest_cloned": False,
            }

        manifest = {
            "project": project_name,
            "iteration": int(target_iteration),
            "created_at": datetime.now().isoformat(),
            "selection_mode": "pool_reuse",
            "reused_from_iteration": int(source_iteration),
            "source_dir": str(master_pool_dir.resolve()),
            "target_dir": str(target_raw_dir.resolve()),
            "master_pool_dir": str(master_pool_dir.resolve()),
            "selected_count": len(selected_images),
            "char_histogram": {k: int(v) for k, v in total_hist.items() if int(v) > 0},
            "selected_images": selected_images,
            "proposal_summary": {
                "planner_version": str(plan.get("planner_version", "") or ""),
                "generated_at": str(plan.get("generated_at", "") or ""),
                "selected_total": int(plan.get("selected_total", 0) or 0),
                "batch_size": int(plan.get("batch_size", plan.get("selected_total", 0)) or 0),
                "skipped_used": int(plan.get("skipped_used", 0) or 0),
                "source_iteration": int(source_iteration),
            },
        }

        manifest_saved = bool(self.save_ingest_manifest(manifest, target_iteration, project_name))
        try:
            plan["ok"] = True
            plan["project"] = project_name
            plan["iteration"] = int(target_iteration)
            self.save_latest_ingest_plan(plan, project_name)
        except Exception:
            pass

        elapsed_ms = max(0.0, (perf_counter() - started_at) * 1000.0)
        if elapsed_ms >= 40.0:
            logger.debug(
                "[CampaignManager][PERF] seed_iteration_from_master_pool: "
                f"{elapsed_ms:.1f} ms | batch={int(preferred_batch_size)} "
                f"candidates={int(plan.get('candidates_total', 0) or 0)} "
                f"selected={int(plan.get('selected_total', 0) or 0)}"
            )

        return {
            "ok": True,
            "source_dir": str(master_pool_dir.resolve()),
            "target_dir": str(target_raw_dir.resolve()),
            "copied_images": int(copied),
            "manifest_cloned": manifest_saved,
        }

    def _seed_iteration_from_stage(
        self,
        *,
        source_iteration: int,
        target_iteration: int,
        project_name: str,
    ) -> Dict[str, Any]:
        started_at = perf_counter()
        target_raw_dir = self.get_iteration_raw_dir(target_iteration, project_name)
        stage_root = self.get_staging_dir("plate_stage")
        if target_raw_dir is None or stage_root is None:
            return {"ok": False, "reason": "missing_project_dirs"}

        stage_root = Path(stage_root)
        stage_candidates = [
            (stage_root / f"Iteracja_{int(source_iteration):03d}", stage_root / f"Iteracja_{int(source_iteration):03d}" / "images"),
            (stage_root, stage_root / "images"),
        ]

        stage_iteration_dir = None
        stage_images_dir = None
        for candidate_dir, candidate_images_dir in stage_candidates:
            if candidate_images_dir.exists() and candidate_images_dir.is_dir():
                stage_iteration_dir = candidate_dir
                stage_images_dir = candidate_images_dir
                break

        if stage_iteration_dir is None or stage_images_dir is None:
            missing_images_dir = stage_candidates[0][1]
            return {
                "ok": False,
                "reason": "missing_stage_images",
                "source_dir": str(missing_images_dir.resolve()),
                "target_dir": str(target_raw_dir.resolve()),
                "copied_images": 0,
                "manifest_cloned": False,
            }

        stage_images = [
            path for path in stage_images_dir.iterdir()
            if path.is_file() and path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS
        ]
        if not stage_images:
            return {
                "ok": False,
                "reason": "missing_stage_images",
                "source_dir": str(stage_images_dir.resolve()),
                "target_dir": str(target_raw_dir.resolve()),
                "copied_images": 0,
                "manifest_cloned": False,
            }

        stage_image_count = int(len(stage_images))
        moved = 0
        transfer_mode = "per_file"
        fast_move_fallback = False

        target_parent = target_raw_dir.parent
        target_parent.mkdir(parents=True, exist_ok=True)

        can_use_dir_move = not target_raw_dir.exists()
        if target_raw_dir.exists():
            try:
                if any(target_raw_dir.iterdir()):
                    can_use_dir_move = False
                else:
                    target_raw_dir.rmdir()
                    can_use_dir_move = True
            except Exception:
                can_use_dir_move = False

        if can_use_dir_move:
            try:
                shutil.move(str(stage_images_dir), str(target_raw_dir))
                stage_images_dir.mkdir(parents=True, exist_ok=True)
                moved = stage_image_count
                transfer_mode = "dir_move"
            except Exception:
                fast_move_fallback = True

        if moved <= 0:
            target_raw_dir.mkdir(parents=True, exist_ok=True)
            for source_path in stage_images:
                if not source_path.exists() or not source_path.is_file():
                    continue
                target_path = target_raw_dir / source_path.name
                if target_path.exists():
                    try:
                        target_path.unlink()
                    except Exception:
                        pass
                shutil.move(str(source_path), str(target_path))
                moved += 1

        if moved <= 0:
            return {
                "ok": False,
                "reason": "copy_failed",
                "source_dir": str(stage_images_dir.resolve()),
                "target_dir": str(target_raw_dir.resolve()),
                "copied_images": 0,
                "manifest_cloned": False,
            }

        manifest = {
            "project": project_name,
            "iteration": int(target_iteration),
            "created_at": datetime.now().isoformat(),
            "selection_mode": "stage_reuse",
            "reused_from_iteration": int(source_iteration),
            "source_dir": str(stage_images_dir.resolve()),
            "target_dir": str(target_raw_dir.resolve()),
            "selected_count": int(moved),
            "selected_images": [],
            "char_histogram": {},
            "proposal_summary": {
                "source_iteration": int(source_iteration),
                "source_kind": "stage",
                "current_iteration_package_count": int(moved),
                "stage_transfer_mode": transfer_mode,
            },
        }
        manifest_saved = bool(self.save_ingest_manifest(manifest, target_iteration, project_name))

        manifest_path = stage_iteration_dir / "stage_manifest.json"
        if manifest_path.exists():
            try:
                manifest_path.write_text(
                    json.dumps(
                        {
                            "project": project_name,
                            "iteration": int(source_iteration),
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                            "pending_images": 0,
                            "stage_images_total": 0,
                            "entries": {},
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except Exception:
                pass

        elapsed_ms = max(0.0, (perf_counter() - started_at) * 1000.0)
        if elapsed_ms >= 40.0:
            logger.debug(
                "[CampaignManager][PERF] seed_iteration_from_stage: "
                f"{elapsed_ms:.1f} ms | images={int(moved)} mode={transfer_mode} "
                f"fallback={1 if fast_move_fallback else 0}"
            )

        return {
            "ok": True,
            "source_dir": str(stage_images_dir.resolve()),
            "target_dir": str(target_raw_dir.resolve()),
            "copied_images": int(moved),
            "manifest_cloned": manifest_saved,
            "source_kind": "stage",
        }

    def advance_to_next_iteration(self, start_mode: str = "new_input") -> Dict[str, Any]:
        act = self.state.get("active_project", "")
        if not act or act not in self.state.get("projects", {}):
            return {"ok": False, "reason": "missing_active_project"}

        start_mode = str(start_mode or "new_input").strip().lower()
        if start_mode not in {"new_input", "reuse_input"}:
            start_mode = "new_input"

        project_data = self.state["projects"][act]
        project_status = str(project_data.get("project_status", "active") or "active").strip().lower()
        current_step = int(project_data.get("current_step", 1) or 1)
        step4_finish_ready = bool(project_data.get("step4_finish_ready", False))
        if project_status in {"paused", "completed"}:
            return {"ok": False, "reason": "project_not_active"}
        if current_step < 5 and not step4_finish_ready:
            return {
                "ok": False,
                "reason": "step4_not_finished",
                "current_step": current_step,
                "step4_finish_ready": step4_finish_ready,
            }
        current_target = self._normalize_iteration_target(project_data.get("iteration_target", ""))
        current_iteration = int(project_data.get("current_iteration", 1) or 1)
        next_iteration = current_iteration + 1
        pending_stage_state = self.get_manual_plate_stage_images_state(
            source_iteration=current_iteration,
            project_name=act,
        )
        pending_stage_images = int(pending_stage_state.get("image_count", 0) or 0)
        previous_image_source = self._resolve_previous_iteration_image_source_for_e1(
            project_name=act,
            current_iteration=current_iteration,
            project_data=project_data,
        )

        result: Dict[str, Any] = {
            "ok": True,
            "requested_mode": start_mode,
            "effective_mode": start_mode,
            "previous_iteration": current_iteration,
            "next_iteration": next_iteration,
            "copied_images": 0,
            "manifest_cloned": False,
            "previous_image_source": previous_image_source,
            "restored_master_pool_dir": "",
            "pending_stage_images": pending_stage_images,
            "needs_new_image_source": False,
        }

        reuse_result: Dict[str, Any] | None = None
        if start_mode == "reuse_input":
            reuse_result = self._seed_iteration_from_stage(
                source_iteration=current_iteration,
                target_iteration=next_iteration,
                project_name=act,
            )
            if not reuse_result.get("ok"):
                reuse_result = self._seed_iteration_from_master_pool(
                    source_iteration=current_iteration,
                    target_iteration=next_iteration,
                    project_name=act,
                )
            if not reuse_result.get("ok"):
                result.update(reuse_result)
                result["ok"] = False
                return result

        project_data["current_iteration"] = next_iteration
        project_data["current_step"] = 1
        project_data["step1_status"] = "pending"
        project_data["step1_source_manual_clear_iteration"] = 0
        project_data["step1_restored_image_source_dir"] = ""

        if current_target in {"plate", "char"}:
            project_data["last_iteration_target"] = current_target
        project_data["iteration_target"] = ""
        project_data["step4_finish_ready"] = False
        project_data["step4_last_run_id"] = ""
        project_data["step4_last_target"] = ""

        if start_mode == "reuse_input":
            result.update(reuse_result or {})
            result["effective_mode"] = "reuse_input"
        else:
            if previous_image_source:
                project_data["master_pool_dir"] = previous_image_source
                project_data["step1_restored_image_source_dir"] = previous_image_source
                result["restored_master_pool_dir"] = previous_image_source
            else:
                project_data["master_pool_dir"] = ""
                result["needs_new_image_source"] = True

        # Nowa iteracja zaczyna się od pełnego resetu stanów etapów zależnych od danych wejściowych.
        project_data["step2_status"] = "pending"
        project_data["step2_staging_run"] = ""
        project_data["step3_status"] = "pending"
        project_data["step3_substep"] = 1
        project_data["step3_stage1_done"] = False
        project_data["step3_stage2_done"] = False
        project_data["step3_extract_entry_mode"] = ""
        project_data["step3_extract_workflow_step"] = "entry"
        project_data["step3_extract_annotation_run_dir"] = ""
        project_data["step3_extract_xml_path"] = ""
        project_data["step3_extract_images_dir"] = ""
        project_data["project_status"] = "active"
        project_data["project_paused_at"] = ""
        project_data["project_completed_at"] = ""
        self.save_state()
        try:
            self.clear_project_iteration_ui_snapshots(act)
        except Exception:
            pass
        if start_mode != "reuse_input":
            try:
                self.clear_latest_ingest_plan(act)
            except Exception:
                pass
        return result

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

    def set_last_plate_training_source(
        self,
        dataset_path: str = "",
        source_run_path: str = "",
        source_xml_path: str = "",
    ):
        act = self.get_active_project_name()
        if not act:
            return

        project_data = self.state["projects"][act]
        project_data["last_plate_training_dataset"] = str(dataset_path or "").strip()
        project_data["last_plate_training_source_run"] = str(source_run_path or "").strip()
        project_data["last_plate_training_source_xml"] = str(source_xml_path or "").strip()
        self.save_state()

    def get_last_plate_training_source(self) -> Dict[str, str]:
        act = self.get_active_project_name()
        if not act:
            return {
                "dataset_path": "",
                "source_run_path": "",
                "source_xml_path": "",
            }

        project_data = self.state["projects"].get(act, {})
        return {
            "dataset_path": str(project_data.get("last_plate_training_dataset", "") or "").strip(),
            "source_run_path": str(project_data.get("last_plate_training_source_run", "") or "").strip(),
            "source_xml_path": str(project_data.get("last_plate_training_source_xml", "") or "").strip(),
        }

    def set_step4_finish_state(
        self,
        ready: bool,
        *,
        run_id: str = "",
        target: str = "",
        iteration_num: int | None = None,
    ) -> None:
        act = self.get_active_project_name()
        if not act:
            return

        project_data = self.state["projects"][act]
        is_ready = bool(ready)
        if iteration_num is None:
            try:
                iteration_num = int(project_data.get("current_iteration", 1) or 1)
            except Exception:
                iteration_num = 1
        project_data["step4_finish_ready"] = is_ready
        project_data["step4_last_run_id"] = str(run_id or "").strip() if is_ready else ""
        project_data["step4_last_target"] = self._normalize_iteration_target(target) if is_ready else ""
        project_data["step4_last_iteration"] = int(iteration_num or 0) if is_ready else 0
        self.save_state()

    def get_step4_finish_state(self) -> Dict[str, Any]:
        act = self.get_active_project_name()
        if not act:
            return {
                "ready": False,
                "run_id": "",
                "target": "",
                "iteration": 0,
            }

        project_data = self.state["projects"].get(act, {})
        return {
            "ready": bool(project_data.get("step4_finish_ready", False)),
            "run_id": str(project_data.get("step4_last_run_id", "") or "").strip(),
            "target": self._normalize_iteration_target(project_data.get("step4_last_target", "")),
            "iteration": int(project_data.get("step4_last_iteration", 0) or 0),
        }

    def set_last_plate_manual_source(
        self,
        source_run_path: str = "",
        source_xml_path: str = "",
        source_input_path: str = "",
    ):
        act = self.get_active_project_name()
        if not act:
            return

        project_data = self.state["projects"][act]
        project_data["last_plate_manual_source_run"] = str(source_run_path or "").strip()
        project_data["last_plate_manual_source_xml"] = str(source_xml_path or "").strip()
        project_data["last_plate_manual_source_input"] = str(source_input_path or "").strip()
        self.save_state()

    def get_last_plate_manual_source(self) -> Dict[str, str]:
        act = self.get_active_project_name()
        if not act:
            return {
                "source_run_path": "",
                "source_xml_path": "",
                "source_input_path": "",
            }

        project_data = self.state["projects"].get(act, {})
        return {
            "source_run_path": str(project_data.get("last_plate_manual_source_run", "") or "").strip(),
            "source_xml_path": str(project_data.get("last_plate_manual_source_xml", "") or "").strip(),
            "source_input_path": str(project_data.get("last_plate_manual_source_input", "") or "").strip(),
        }
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

    def clear_project_iteration_ui_snapshots(self, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False

        state_dir = self.get_project_state_dir(project_name)
        if state_dir is None:
            return False

        removed_any = False
        for snapshot_name in (
            "annotation_ui_state.json",
        ):
            snapshot_path = state_dir / snapshot_name
            try:
                if snapshot_path.exists():
                    snapshot_path.unlink()
                    removed_any = True
            except Exception as e:
                logger.debug(
                    f"Nie udało się usunąć snapshotu iteracji {snapshot_path}: {e}"
                )

        return removed_any

    def get_project_ingest_state_dir(self, project_name: str = None) -> Path | None:
        state_dir = self.get_project_state_dir(project_name)
        if state_dir is None:
            return None

        ingest_dir = state_dir / "ingest"
        ingest_dir.mkdir(parents=True, exist_ok=True)
        return ingest_dir

    def get_artifact_registry_path(self, project_name: str = None) -> Path | None:
        state_dir = self.get_project_state_dir(project_name)
        if state_dir is None:
            return None
        return state_dir / "artifact_registry.json"

    @staticmethod
    def _safe_registry_path_value(path_like) -> str:
        raw_value = str(path_like or "").strip()
        if not raw_value:
            return ""
        try:
            return str(Path(raw_value).resolve())
        except Exception:
            return raw_value

    @staticmethod
    def _build_registry_path_token(path_like) -> str:
        raw_value = str(path_like or "").strip()
        if not raw_value:
            return ""
        try:
            path = Path(raw_value)
        except Exception:
            return raw_value
        try:
            resolved = str(path.resolve())
        except Exception:
            resolved = raw_value
        try:
            stat = path.stat()
            return (
                f"{resolved}|"
                f"{int(getattr(stat, 'st_mtime_ns', 0) or 0)}|"
                f"{int(getattr(stat, 'st_size', 0) or 0)}"
            )
        except Exception:
            return resolved

    @staticmethod
    def _normalize_image_set_name(name_like) -> str:
        raw_value = str(name_like or "").strip()
        if not raw_value:
            return ""
        raw_value = raw_value.replace("\\", "/")
        try:
            return str(Path(raw_value).name or "").strip().lower()
        except Exception:
            return str(raw_value.rsplit("/", 1)[-1] or "").strip().lower()

    def build_image_name_set_token(
        self,
        image_names: List[str] | None = None,
        *,
        images_dir: str | Path | None = None,
    ) -> str:
        normalized_names: list[str] = []

        for raw_name in list(image_names or []):
            normalized = self._normalize_image_set_name(raw_name)
            if normalized:
                normalized_names.append(normalized)

        if not normalized_names and images_dir:
            try:
                images_root = Path(images_dir)
            except Exception:
                images_root = None
            if images_root is not None:
                try:
                    if images_root.exists() and images_root.is_dir():
                        for image_path in images_root.rglob("*"):
                            try:
                                if image_path.is_file() and image_path.suffix.lower() in CONFIG.IMAGE_EXTENSIONS:
                                    normalized = self._normalize_image_set_name(image_path.name)
                                    if normalized:
                                        normalized_names.append(normalized)
                            except Exception:
                                continue
                except Exception:
                    pass

        unique_names = sorted(set(normalized_names))
        if not unique_names:
            return ""

        digest = hashlib.sha1("\n".join(unique_names).encode("utf-8")).hexdigest()[:20]
        return f"iset_{len(unique_names):05d}_{digest}"

    @staticmethod
    def _deep_merge_registry_dict(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in dict(updates or {}).items():
            if isinstance(value, dict):
                current = base.get(key)
                if not isinstance(current, dict):
                    current = {}
                base[key] = CampaignManager._deep_merge_registry_dict(dict(current), value)
            else:
                base[key] = value
        return base

    def load_artifact_registry(self, project_name: str = None) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {
                "project": "",
                "updated_at": "",
                "packages": {},
                "iteration_index": {},
                "iteration_state": {},
            }

        registry_path = self.get_artifact_registry_path(project_name)
        if registry_path is None or not registry_path.exists():
            return {
                "project": project_name,
                "updated_at": "",
                "packages": {},
                "iteration_index": {},
                "iteration_state": {},
            }

        cache_key = None
        try:
            stat = registry_path.stat()
            cache_key = (
                project_name,
                int(getattr(stat, "st_mtime_ns", 0) or 0),
                int(getattr(stat, "st_size", 0) or 0),
            )
        except Exception:
            cache_key = None

        if cache_key is not None:
            cached = self._artifact_registry_cache.get(cache_key)
            if isinstance(cached, dict):
                return dict(cached)

        payload = self._read_json_file(registry_path)
        if not isinstance(payload, dict):
            payload = {}
        payload["project"] = str(payload.get("project") or project_name).strip()
        if not isinstance(payload.get("packages"), dict):
            payload["packages"] = {}
        if not isinstance(payload.get("iteration_index"), dict):
            payload["iteration_index"] = {}
        if not isinstance(payload.get("iteration_state"), dict):
            payload["iteration_state"] = {}

        if cache_key is not None:
            self._artifact_registry_cache[cache_key] = dict(payload)
        return payload

    def save_artifact_registry(self, payload: Dict[str, Any], project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False
        registry_path = self.get_artifact_registry_path(project_name)
        if registry_path is None:
            return False
        safe_payload = dict(payload or {})
        safe_payload["project"] = project_name
        safe_payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if not isinstance(safe_payload.get("packages"), dict):
            safe_payload["packages"] = {}
        if not isinstance(safe_payload.get("iteration_index"), dict):
            safe_payload["iteration_index"] = {}
        if not isinstance(safe_payload.get("iteration_state"), dict):
            safe_payload["iteration_state"] = {}
        ok = self._write_json_file(registry_path, safe_payload)
        if ok:
            self._artifact_registry_cache.clear()
        return ok

    def upsert_iteration_state(
        self,
        *,
        iteration_num: int | None = None,
        updates: Dict[str, Any] | None = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {}

        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1) or 1)
        registry = self.load_artifact_registry(project_name)
        iteration_state = registry.setdefault("iteration_state", {})
        if not isinstance(iteration_state, dict):
            iteration_state = {}
            registry["iteration_state"] = iteration_state

        entry = dict(iteration_state.get(str(iter_value)) or {})
        entry.setdefault("project", project_name)
        entry.setdefault("iteration", iter_value)
        entry.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")

        updates_dict = dict(updates or {})
        if updates_dict:
            entry = self._deep_merge_registry_dict(entry, updates_dict)

        iteration_state[str(iter_value)] = entry
        if not self.save_artifact_registry(registry, project_name):
            return {}
        return dict(entry)

    def get_iteration_state(
        self,
        *,
        iteration_num: int | None = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {}
        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1) or 1)
        registry = self.load_artifact_registry(project_name)
        iteration_state = registry.get("iteration_state", {})
        if not isinstance(iteration_state, dict):
            return {}
        entry = iteration_state.get(str(iter_value))
        return dict(entry) if isinstance(entry, dict) else {}

    def build_iteration_artifact_package_id(
        self,
        images_dir: str | Path | None = None,
        *,
        iteration_num: int | None = None,
        image_set_token: str | None = None,
        project_name: str = None,
    ) -> str:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return ""
        normalized_images_dir = self._safe_registry_path_value(images_dir)
        normalized_image_set_token = str(image_set_token or "").strip()
        if normalized_images_dir and normalized_image_set_token:
            digest = hashlib.sha1(
                f"{normalized_images_dir.lower()}::{normalized_image_set_token}".encode("utf-8")
            ).hexdigest()[:16]
            return f"pkg_{digest}"
        if normalized_images_dir:
            digest = hashlib.sha1(normalized_images_dir.lower().encode("utf-8")).hexdigest()[:16]
            return f"pkg_{digest}"
        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1) or 1)
        digest = hashlib.sha1(f"{project_name.lower()}::{iter_value}".encode("utf-8")).hexdigest()[:16]
        return f"iter_{iter_value:03d}_{digest}"

    def upsert_iteration_artifact_bundle(
        self,
        *,
        images_dir: str | Path | None = None,
        iteration_num: int | None = None,
        image_set_token: str | None = None,
        updates: Dict[str, Any] | None = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {}

        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1) or 1)
        normalized_images_dir = self._safe_registry_path_value(images_dir or self.get_master_pool_dir(project_name))
        registry = self.load_artifact_registry(project_name)
        packages = registry.setdefault("packages", {})
        iteration_index = registry.setdefault("iteration_index", {})
        existing_package_id = str((iteration_index or {}).get(str(iter_value), "") or "").strip()
        existing_package = dict(packages.get(existing_package_id) or {}) if existing_package_id else {}
        updates_dict = dict(updates or {})
        updates_image_source = dict(updates_dict.get("image_source") or {})
        resolved_image_set_token = str(
            image_set_token
            or updates_image_source.get("image_set_token")
            or dict(existing_package.get("image_source") or {}).get("image_set_token")
            or ""
        ).strip()

        package_id = self.build_iteration_artifact_package_id(
            normalized_images_dir,
            iteration_num=iter_value,
            image_set_token=resolved_image_set_token,
            project_name=project_name,
        )
        if not package_id:
            return {}

        package = dict(packages.get(package_id) or existing_package or {})
        package.setdefault("package_id", package_id)
        package.setdefault("project", project_name)
        package.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        package["updated_at"] = datetime.now().isoformat(timespec="seconds")
        package["iteration_first_seen"] = int(package.get("iteration_first_seen", iter_value) or iter_value)
        package["iteration_last_seen"] = int(iter_value)
        package["images_dir"] = normalized_images_dir or str(package.get("images_dir", "") or "").strip()
        package["images_token"] = self._build_registry_path_token(package.get("images_dir"))
        iterations = {
            int(value)
            for value in list(package.get("iterations") or [])
            if str(value).strip().isdigit()
        }
        iterations.add(iter_value)
        package["iterations"] = sorted(iterations)

        if updates_dict:
            package = self._deep_merge_registry_dict(package, updates_dict)

        if existing_package_id and existing_package_id != package_id:
            try:
                packages.pop(existing_package_id, None)
            except Exception:
                pass
        packages[package_id] = package
        iteration_index[str(iter_value)] = package_id
        if not self.save_artifact_registry(registry, project_name):
            return {}
        return dict(package)

    def get_iteration_artifact_bundle(
        self,
        *,
        images_dir: str | Path | None = None,
        iteration_num: int | None = None,
        image_set_token: str | None = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {}
        registry = self.load_artifact_registry(project_name)
        packages = registry.get("packages", {})
        if not isinstance(packages, dict):
            return {}

        normalized_images_dir = self._safe_registry_path_value(images_dir)
        if normalized_images_dir:
            package_id = self.build_iteration_artifact_package_id(
                normalized_images_dir,
                iteration_num=iteration_num,
                image_set_token=image_set_token,
                project_name=project_name,
            )
            package = packages.get(package_id)
            if isinstance(package, dict):
                return dict(package)

        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1) or 1)
        package_id = str((registry.get("iteration_index") or {}).get(str(iter_value), "") or "").strip()
        package = packages.get(package_id)
        return dict(package) if isinstance(package, dict) else {}

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
            "plate_stage": staging_root / "plate_manual_stage",
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
        self.state["projects"][project_name]["step1_source_manual_clear_iteration"] = 0
        self.state["projects"][project_name]["step1_restored_image_source_dir"] = ""
        self.save_state()
        return True

    def clear_master_pool_dir(self, project_name: str = None) -> bool:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return False
        project_data = self.state["projects"][project_name]
        project_data["master_pool_dir"] = ""
        project_data["step1_restored_image_source_dir"] = ""
        try:
            project_data["step1_source_manual_clear_iteration"] = int(project_data.get("current_iteration", 1) or 1)
        except Exception:
            project_data["step1_source_manual_clear_iteration"] = 0
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

    def clear_latest_ingest_plan(self, project_name: str = None) -> bool:
        plan_path = self.get_latest_ingest_plan_path(project_name)
        if plan_path is None:
            return False
        try:
            if plan_path.exists():
                plan_path.unlink()
            return True
        except Exception:
            return False

    def get_plate_approved_set_path(self, project_name: str = None) -> Path | None:
        state_dir = self.get_project_state_dir(project_name)
        if state_dir is None:
            return None
        return state_dir / "plate_approved_set.json"

    def load_plate_approved_set(self, project_name: str = None) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {}

        manifest_path = self.get_plate_approved_set_path(project_name)
        if manifest_path is None or not manifest_path.exists():
            return {
                "project": project_name,
                "updated_at": "",
                "entries": {},
            }

        payload = self._read_json_file(manifest_path)
        if not isinstance(payload, dict):
            payload = {}

        entries = payload.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}

        return {
            "project": project_name,
            "updated_at": str(payload.get("updated_at", "") or "").strip(),
            "entries": entries,
        }

    def list_plate_approved_entries(self, project_name: str = None) -> List[Dict[str, Any]]:
        manifest = self.load_plate_approved_set(project_name)
        entries = manifest.get("entries", {})
        if not isinstance(entries, dict):
            return []

        result: List[Dict[str, Any]] = []
        for entry_key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            normalized = dict(entry)
            normalized.setdefault("entry_key", str(entry_key or "").strip())
            result.append(normalized)

        result.sort(
            key=lambda item: (
                str(item.get("approved_at", "") or "").strip(),
                str(item.get("image_name", "") or "").strip().lower(),
            )
        )
        return result

    @staticmethod
    def _load_annotation_run_manifest_file(run_dir: Path | None) -> Dict[str, Any]:
        try:
            safe_run_dir = Path(run_dir) if run_dir is not None else None
        except Exception:
            safe_run_dir = None
        if safe_run_dir is None:
            return {}
        manifest_path = safe_run_dir / "run_manifest.json"
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_preview_metadata_source_state(preview_dir: Path | None) -> Dict[str, Any]:
        try:
            safe_preview_dir = Path(preview_dir) if preview_dir is not None else None
        except Exception:
            safe_preview_dir = None
        if safe_preview_dir is None:
            return {}

        meta_path = safe_preview_dir / "metadata.json"
        images_dir = safe_preview_dir / "images"
        if not meta_path.exists() or not images_dir.exists():
            return {}

        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(loaded, dict) or not loaded:
            return {}

        total_plates = 0
        source_names: set[str] = set()
        plates_by_source: dict[str, int] = {}
        for pid, payload in loaded.items():
            pid_text = str(pid or "").strip()
            if not pid_text:
                continue
            total_plates += 1
            source_key = ""
            if isinstance(payload, dict):
                source_info = payload.get("source_info") or {}
                if not isinstance(source_info, dict):
                    source_info = {}
                source_key = str(
                    payload.get("source_image")
                    or payload.get("source_name")
                    or source_info.get("image_name")
                    or pid_text
                ).strip()
            if not source_key:
                source_key = pid_text
            normalized_source = CampaignManager._normalize_image_set_name(source_key)
            if not normalized_source:
                normalized_source = str(source_key or pid_text).strip().lower()
            if not normalized_source:
                continue
            source_names.add(normalized_source)
            plates_by_source[normalized_source] = int(plates_by_source.get(normalized_source, 0) or 0) + 1

        images_with_plates = int(len(source_names) or total_plates or 0)
        total_plates = int(total_plates or 0)
        if total_plates <= 0:
            return {}

        return {
            "source_scope": "step3_preview",
            "run_dir": str(safe_preview_dir.resolve()) if safe_preview_dir.exists() else str(safe_preview_dir),
            "run_name": str(safe_preview_dir.name or "").strip(),
            "images_with_plates": images_with_plates,
            "total_plates": total_plates,
            "source_names": set(source_names),
            "plates_by_source": dict(plates_by_source),
        }

    @staticmethod
    def _load_run_plate_counts_by_image(run_dir: Path | None, *, image_names: set[str] | None = None) -> Dict[str, int]:
        try:
            safe_run_dir = Path(run_dir) if run_dir is not None else None
        except Exception:
            safe_run_dir = None
        if safe_run_dir is None:
            return {}
        xml_path = safe_run_dir / "annotations.xml"
        if not xml_path.exists():
            return {}

        wanted_names = {
            CampaignManager._normalize_image_set_name(name)
            for name in set(image_names or set())
            if CampaignManager._normalize_image_set_name(name)
        }
        try:
            root = ET.parse(xml_path).getroot()
        except Exception:
            return {}

        counts: dict[str, int] = {}
        for image_node in root.findall(".//image"):
            image_name = CampaignManager._normalize_image_set_name(image_node.get("name", ""))
            if not image_name:
                continue
            if wanted_names and image_name not in wanted_names:
                continue
            plate_count = 0
            for tag_name in ("polygon", "box"):
                for det_node in image_node.findall(tag_name):
                    if str(det_node.get("label", "") or "").strip().lower() == "plate":
                        plate_count += 1
            if plate_count <= 0:
                continue
            counts[image_name] = int(plate_count)
        return counts

    def get_step3_char_source_state(
        self,
        *,
        iteration_num: int | None = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {}

        iter_value = int(iteration_num or self.state["projects"][project_name].get("current_iteration", 1) or 1)
        try:
            bundle = dict(self.get_iteration_artifact_bundle(iteration_num=iter_value, project_name=project_name) or {})
        except Exception:
            bundle = {}

        preview_entry = dict(bundle.get("step3_preview_source") or {})
        preview_dir_raw = str(preview_entry.get("preview_dir") or "").strip()
        if not preview_dir_raw:
            try:
                preview_dir_raw = str(self.state["projects"][project_name].get("step3_preview_dir", "") or "").strip()
            except Exception:
                preview_dir_raw = ""
        preview_state = self._load_preview_metadata_source_state(Path(preview_dir_raw) if preview_dir_raw else None)

        step2_entry = dict(bundle.get("step2_active_run") or bundle.get("plate_source") or {})
        step2_run_raw = str(step2_entry.get("run_dir") or "").strip()
        step2_run_dir = Path(step2_run_raw) if step2_run_raw else None
        step2_manifest = self._load_annotation_run_manifest_file(step2_run_dir)
        approved_names = {
            self._normalize_image_set_name(name)
            for name in list(step2_manifest.get("approved_filenames") or [])
            if self._normalize_image_set_name(name)
        }

        step2_counts = self._load_run_plate_counts_by_image(step2_run_dir, image_names=approved_names)

        approved_entries = list(self.list_plate_approved_entries(project_name) or [])
        project_approved_names = {
            self._normalize_image_set_name(entry.get("image_name", ""))
            for entry in approved_entries
            if isinstance(entry, dict) and self._normalize_image_set_name(entry.get("image_name", ""))
        }
        project_approved_plates_by_source: dict[str, int] = {}
        for entry in approved_entries:
            if not isinstance(entry, dict):
                continue
            safe_name = self._normalize_image_set_name(entry.get("image_name", ""))
            if not safe_name:
                continue
            valid_plate_count = 0
            for plate_entry in list(entry.get("plates") or []):
                if not isinstance(plate_entry, dict):
                    continue
                polygon = list(plate_entry.get("polygon") or [])
                if len(polygon) >= 4:
                    valid_plate_count += 1
            if valid_plate_count <= 0:
                valid_plate_count = int(entry.get("plate_count", 0) or 0)
            if valid_plate_count <= 0:
                continue
            project_approved_plates_by_source[safe_name] = int(valid_plate_count)

        union_source_names = {
            str(name or "").strip().lower()
            for name in set(project_approved_plates_by_source.keys())
            if str(name or "").strip()
        }
        union_plates_by_source = {
            str(name or "").strip().lower(): int(count or 0)
            for name, count in dict(project_approved_plates_by_source).items()
            if str(name or "").strip() and int(count or 0) > 0
        }

        for name in set(preview_state.get("source_names") or set()):
            safe_name = str(name or "").strip().lower()
            if safe_name:
                union_source_names.add(safe_name)
        for name, count in dict(preview_state.get("plates_by_source") or {}).items():
            safe_name = str(name or "").strip().lower()
            plate_count = int(count or 0)
            if safe_name and plate_count > 0:
                union_source_names.add(safe_name)
                union_plates_by_source[safe_name] = max(
                    int(union_plates_by_source.get(safe_name, 0) or 0),
                    plate_count,
                )

        pending_added_names: set[str] = set()
        pending_added_plates_by_source: dict[str, int] = {}
        for image_name, plate_count in dict(step2_counts or {}).items():
            safe_name = str(image_name or "").strip().lower()
            if not safe_name or plate_count <= 0:
                continue
            if safe_name in project_approved_names:
                continue
            if safe_name in union_source_names:
                continue
            union_source_names.add(safe_name)
            union_plates_by_source[safe_name] = int(plate_count)
            pending_added_names.add(safe_name)
            pending_added_plates_by_source[safe_name] = int(plate_count)

        if not union_source_names and not union_plates_by_source:
            return {}

        union_project_names = set(union_source_names) & set(project_approved_names)
        union_project_plates = int(
            sum(int(project_approved_plates_by_source.get(name, 0) or 0) for name in union_project_names)
        )
        union_total_plates = int(sum(int(count or 0) for count in union_plates_by_source.values()))
        pending_images = int(len(pending_added_names))
        pending_plates = int(sum(int(count or 0) for count in pending_added_plates_by_source.values()))
        current_images = max(0, int(len(union_source_names)) - int(len(union_project_names)))
        current_plates = max(0, int(union_total_plates) - int(union_project_plates))

        return {
            "source_scope": (
                "step3_pending_union"
                if pending_images > 0
                else (
                    "campaign_approved_set"
                    if union_project_names
                    else str(preview_state.get("source_scope") or "step3_preview")
                )
            ),
            "images_with_plates": int(len(union_source_names)),
            "total_plates": int(union_total_plates),
            "project_images_with_plates": int(len(union_project_names)),
            "project_total_plates": int(union_project_plates),
            "current_images_with_plates": int(current_images),
            "current_total_plates": int(current_plates),
            "preview_images_with_plates": int(preview_state.get("images_with_plates", 0) or 0),
            "preview_total_plates": int(preview_state.get("total_plates", 0) or 0),
            "pending_images_with_plates": int(pending_images),
            "pending_total_plates": int(pending_plates),
            "source_names": set(union_source_names),
            "preview_source_names": set(preview_state.get("source_names") or set()),
            "pending_source_names": set(pending_added_names),
            "run_name": str(preview_state.get("run_name") or "").strip(),
            "run_dir": str(preview_state.get("run_dir") or "").strip(),
            "ready": bool(int(len(union_source_names)) >= 2 and int(union_total_plates) > 0),
            "has_source": bool(int(union_total_plates) > 0),
            "needs_more_tables": bool(int(union_total_plates) > 0 and int(len(union_source_names)) < 2),
        }

    def get_plate_approved_set_stats(self, project_name: str = None) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {
                "project": "",
                "updated_at": "",
                "images": 0,
                "plates": 0,
                "manual_images": 0,
                "manual_plates": 0,
                "auto_accepted_images": 0,
                "auto_accepted_plates": 0,
            }

        cache_key = None
        manifest_path = self.get_plate_approved_set_path(project_name)
        if manifest_path is not None and manifest_path.exists():
            try:
                stat = manifest_path.stat()
                cache_key = (project_name, int(getattr(stat, "st_mtime_ns", 0) or 0), int(getattr(stat, "st_size", 0) or 0))
            except Exception:
                cache_key = None
        if cache_key is not None:
            cached = self._plate_approved_stats_cache.get(cache_key)
            if isinstance(cached, dict):
                return dict(cached)

        manifest = self.load_plate_approved_set(project_name)
        entries = manifest.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}

        stats = {
            "project": str(manifest.get("project", "") or "").strip(),
            "updated_at": str(manifest.get("updated_at", "") or "").strip(),
            "images": 0,
            "plates": 0,
            "manual_images": 0,
            "manual_plates": 0,
            "auto_accepted_images": 0,
            "auto_accepted_plates": 0,
        }

        for entry in entries.values():
            if not isinstance(entry, dict):
                continue

            valid_plate_count = 0
            for plate_entry in list(entry.get("plates") or []):
                if not isinstance(plate_entry, dict):
                    continue
                polygon = list(plate_entry.get("polygon") or [])
                if len(polygon) >= 4:
                    valid_plate_count += 1

            if valid_plate_count <= 0:
                valid_plate_count = int(entry.get("plate_count", 0) or 0)
            if valid_plate_count <= 0:
                continue

            stats["images"] += 1
            stats["plates"] += int(valid_plate_count)

            origin = str(entry.get("annotation_origin", "") or "").strip().lower()
            if origin == "auto_accepted":
                stats["auto_accepted_images"] += 1
                stats["auto_accepted_plates"] += int(valid_plate_count)
            else:
                stats["manual_images"] += 1
                stats["manual_plates"] += int(valid_plate_count)

        if cache_key is not None:
            self._plate_approved_stats_cache[cache_key] = dict(stats)

        return stats

    def get_plate_approved_set_iteration_stats(
        self,
        iteration_num: int = None,
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {
                "project": "",
                "iteration": int(iteration_num or 0),
                "images": 0,
                "plates": 0,
                "image_names": [],
            }

        try:
            iter_value = int(
                iteration_num
                or self.state["projects"][project_name].get("current_iteration", 1)
                or 1
            )
        except Exception:
            iter_value = 1

        stats = {
            "project": project_name,
            "iteration": int(iter_value),
            "images": 0,
            "plates": 0,
            "image_names": [],
        }
        image_names: set[str] = set()

        for entry in self.list_plate_approved_entries(project_name):
            if not isinstance(entry, dict):
                continue
            raw_iteration = (
                entry.get("first_approved_iteration")
                or entry.get("approved_iteration")
                or 0
            )
            try:
                entry_iteration = int(raw_iteration or 0)
            except Exception:
                entry_iteration = 0
            if entry_iteration != int(iter_value):
                continue

            valid_plate_count = 0
            for plate_entry in list(entry.get("plates") or []):
                if not isinstance(plate_entry, dict):
                    continue
                polygon = list(plate_entry.get("polygon") or [])
                if len(polygon) >= 4:
                    valid_plate_count += 1
            if valid_plate_count <= 0:
                valid_plate_count = int(entry.get("plate_count", 0) or 0)
            if valid_plate_count <= 0:
                continue

            stats["images"] += 1
            stats["plates"] += int(valid_plate_count)
            image_name = str(entry.get("image_name", "") or "").strip()
            if image_name:
                image_names.add(image_name)

        stats["image_names"] = sorted(image_names)
        return stats

    def upsert_plate_approved_entries(
        self,
        entries: List[Dict[str, Any]],
        project_name: str = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {"ok": False, "reason": "missing_project"}

        manifest_path = self.get_plate_approved_set_path(project_name)
        if manifest_path is None:
            return {"ok": False, "reason": "missing_manifest_path"}

        manifest = self.load_plate_approved_set(project_name)
        stored_entries = manifest.get("entries", {})
        if not isinstance(stored_entries, dict):
            stored_entries = {}

        added = 0
        updated = 0
        for raw_entry in list(entries or []):
            if not isinstance(raw_entry, dict):
                continue

            image_name = str(raw_entry.get("image_name", "") or "").strip()
            entry_key = str(raw_entry.get("entry_key", "") or "").strip().lower() or image_name.lower()
            if not image_name or not entry_key:
                continue

            normalized = dict(raw_entry)
            normalized["entry_key"] = entry_key
            normalized["image_name"] = image_name

            existing_entry = stored_entries.get(entry_key)
            if not isinstance(existing_entry, dict):
                existing_entry = {}

            first_iteration = (
                existing_entry.get("first_approved_iteration")
                or existing_entry.get("approved_iteration")
                or normalized.get("first_approved_iteration")
                or normalized.get("approved_iteration")
            )
            try:
                first_iteration = int(first_iteration or 0)
            except Exception:
                first_iteration = 0
            if first_iteration > 0:
                normalized["first_approved_iteration"] = int(first_iteration)

            first_approved_at = (
                str(existing_entry.get("first_approved_at", "") or "").strip()
                or str(existing_entry.get("approved_at", "") or "").strip()
                or str(normalized.get("first_approved_at", "") or "").strip()
                or str(normalized.get("approved_at", "") or "").strip()
            )
            if first_approved_at:
                normalized["first_approved_at"] = first_approved_at

            if entry_key in stored_entries:
                updated += 1
            else:
                added += 1
            stored_entries[entry_key] = normalized

        manifest["project"] = project_name
        manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["entries"] = stored_entries

        if not self._write_json_file(manifest_path, manifest):
            return {"ok": False, "reason": "save_failed"}

        return {
            "ok": True,
            "added": int(added),
            "updated": int(updated),
            "total": int(len(stored_entries)),
            "manifest_path": str(manifest_path),
        }

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
        master_pool_dir = self.get_master_pool_dir(project_name)

        try:
            from .campaign_ingest_planner import CampaignIngestPlanner

            planner = CampaignIngestPlanner()
        except Exception:
            planner = None

        for entry in self.list_plate_approved_entries(project_name):
            if not isinstance(entry, dict):
                continue

            image_name = str(entry.get("image_name", "") or "").strip().lower()
            if image_name:
                filenames.add(image_name)

            source_image_path = str(entry.get("source_image_path", "") or "").strip()
            if not source_image_path:
                continue

            try:
                source_path = Path(source_image_path)
            except Exception:
                continue

            if planner is not None:
                try:
                    source_key = planner.make_source_key(source_path, master_pool_dir=master_pool_dir)
                except Exception:
                    source_key = ""
            else:
                try:
                    source_key = str(source_path.resolve()).strip().lower()
                except Exception:
                    source_key = str(source_path).strip().lower()

            if source_key:
                source_keys.add(source_key)

        return {
            "source_keys": sorted(source_keys),
            "filenames": sorted(filenames),
            "total_source_keys": len(source_keys),
            "total_filenames": len(filenames),
        }

    def get_project_packet_filename_registry(
        self,
        project_name: str = None,
        *,
        exclude_iteration_num: int | None = None,
    ) -> Dict[str, Any]:
        project_name = self._resolve_project_name(project_name)
        if not project_name:
            return {
                "filenames": [],
                "total_filenames": 0,
            }

        filenames = set()
        raw_root = self.get_dir("raw") if project_name == self.get_active_project_name() else self.get_project_root_dir(project_name) / "1_raw_images"
        if raw_root is None:
            return {
                "filenames": [],
                "total_filenames": 0,
            }

        try:
            raw_root = Path(raw_root)
        except Exception:
            return {
                "filenames": [],
                "total_filenames": 0,
            }

        if not raw_root.exists() or not raw_root.is_dir():
            return {
                "filenames": [],
                "total_filenames": 0,
            }

        try:
            for image_path in raw_root.rglob("*"):
                if not image_path.is_file():
                    continue
                if exclude_iteration_num is not None:
                    try:
                        excluded_dir = raw_root / f"Iteracja_{int(exclude_iteration_num):03d}"
                        if excluded_dir in image_path.parents:
                            continue
                    except Exception:
                        pass
                if image_path.suffix.lower() not in CONFIG.IMAGE_EXTENSIONS:
                    continue
                filename = str(image_path.name or "").strip().lower()
                if filename:
                    filenames.add(filename)
        except Exception:
            pass

        return {
            "filenames": sorted(filenames),
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
            "image_set_token": self.build_image_name_set_token(
                [str(item.get("name") or "").strip() for item in selected_images]
            ),
            "char_histogram": {k: int(v) for k, v in total_hist.items() if int(v) > 0},
            "selected_images": selected_images,
            "proposal_summary": proposal_summary or {},
        }

        return self.save_ingest_manifest(manifest, iteration, project_name)

# Singleton Menadżera
CAMPAIGN = CampaignManager()
