"""Stage and route state methods for ``CampaignManager``.

This module stores campaign step/status setters and getters.  Methods are bound
back to CampaignManager so callers keep using the same API while the central
manager file stays focused on orchestration.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from .campaign_iteration_paths import (
    default_iteration_path_for_target,
    iteration_path_target,
    normalize_iteration_path,
)


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
    if str(self.state["projects"][project_name].get(state_key, "") or "").strip().lower() == normalized:
        return True
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

def set_project_start_plate_source(
    self,
    source_run_path: str = "",
    source_xml_path: str = "",
    source_input_path: str = "",
    source_mode: str = "",
    project_name: str = None,
) -> bool:
    project_name = self._resolve_project_name(project_name)
    if not project_name:
        return False

    project_data = self.state["projects"][project_name]
    source_run = str(source_run_path or "").strip()
    source_xml = str(source_xml_path or "").strip()
    source_input = str(source_input_path or "").strip()
    source_mode_value = str(source_mode or "").strip().lower()
    if source_mode_value not in {"approved", "draft"}:
        source_mode_value = ""
    has_source = bool(source_run or source_xml or source_input)
    try:
        current_iteration = int(project_data.get("current_iteration", 1) or 1)
    except Exception:
        current_iteration = 1

    project_data["project_start_plate_source_run"] = source_run
    project_data["project_start_plate_source_xml"] = source_xml
    project_data["project_start_plate_source_input"] = source_input
    project_data["project_start_plate_source_mode"] = source_mode_value if has_source else ""
    project_data["project_start_plate_source_iteration"] = int(current_iteration if has_source else 0)
    self.save_state()
    return True

def clear_project_start_plate_source(self, project_name: str = None) -> bool:
    return self.set_project_start_plate_source("", "", "", project_name=project_name)

def get_project_start_plate_source(self, project_name: str = None) -> Dict[str, str]:
    project_name = self._resolve_project_name(project_name)
    if not project_name:
        return {
            "source_run_path": "",
            "source_xml_path": "",
            "source_input_path": "",
            "source_mode": "",
            "source_iteration": "",
        }

    project_data = self.state["projects"].get(project_name, {})
    try:
        source_iteration = int(project_data.get("project_start_plate_source_iteration", 0) or 0)
    except Exception:
        source_iteration = 0
    try:
        current_iteration = int(project_data.get("current_iteration", 1) or 1)
    except Exception:
        current_iteration = 1

    if source_iteration and source_iteration != current_iteration:
        return {
            "source_run_path": "",
            "source_xml_path": "",
            "source_input_path": "",
            "source_mode": "",
            "source_iteration": "",
        }

    return {
        "source_run_path": str(project_data.get("project_start_plate_source_run", "") or "").strip(),
        "source_xml_path": str(project_data.get("project_start_plate_source_xml", "") or "").strip(),
        "source_input_path": str(project_data.get("project_start_plate_source_input", "") or "").strip(),
        "source_mode": str(project_data.get("project_start_plate_source_mode", "") or "").strip().lower(),
        "source_iteration": str(source_iteration or ""),
    }

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

    normalized_target = self._normalize_iteration_target(target)
    project_data = self.state["projects"][act]
    project_data["iteration_target"] = normalized_target
    current_path = normalize_iteration_path(project_data.get("iteration_path", ""))
    if not normalized_target:
        project_data["iteration_path"] = ""
    elif current_path and iteration_path_target(current_path) != normalized_target:
        project_data["iteration_path"] = ""
    self.save_state()

def get_iteration_target(self) -> str:
    act = self.get_active_project_name()
    if not act:
        return ""
    return self._normalize_iteration_target(self.state["projects"][act].get("iteration_target", ""))

def clear_iteration_target(self):
    self.set_iteration_target("")

@staticmethod
def _normalize_iteration_path(path: str | None) -> str:
    return normalize_iteration_path(path)

def set_iteration_path(self, path: str | None):
    act = self.get_active_project_name()
    if not act:
        return
    normalized_path = normalize_iteration_path(path)
    project_data = self.state["projects"][act]
    project_data["iteration_path"] = normalized_path
    target = iteration_path_target(normalized_path)
    if target:
        project_data["iteration_target"] = target
    elif not normalized_path:
        project_data["iteration_target"] = ""
    self.save_state()

def get_iteration_path(self) -> str:
    act = self.get_active_project_name()
    if not act:
        return ""
    project_data = self.state["projects"][act]
    normalized_path = normalize_iteration_path(project_data.get("iteration_path", ""))
    target = self._normalize_iteration_target(project_data.get("iteration_target", ""))
    if normalized_path and (not target or iteration_path_target(normalized_path) == target):
        return normalized_path
    return default_iteration_path_for_target(target)

def get_explicit_iteration_path(self) -> str:
    act = self.get_active_project_name()
    if not act:
        return ""
    project_data = self.state["projects"][act]
    normalized_path = normalize_iteration_path(project_data.get("iteration_path", ""))
    target = self._normalize_iteration_target(project_data.get("iteration_target", ""))
    if normalized_path and (not target or iteration_path_target(normalized_path) == target):
        return normalized_path
    return ""

def clear_iteration_path(self):
    self.set_iteration_path("")

def set_graph_selected_edge_key(self, edge_key: str | None):
    act = self.get_active_project_name()
    if not act:
        return
    self.state["projects"][act]["graph_selected_edge_key"] = str(edge_key or "").strip()
    self.save_state()

def get_graph_selected_edge_key(self) -> str:
    act = self.get_active_project_name()
    if not act:
        return ""
    return str(self.state["projects"][act].get("graph_selected_edge_key", "") or "").strip()

def clear_graph_selected_edge_key(self):
    self.set_graph_selected_edge_key("")

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


_INSTANCE_METHODS = ('_get_active_data', 'get_safe_project_folder_name', 'get_project_created_at', 'get_current_iteration_num', 'get_current_step', 'set_current_step', 'approve_step1', 'reset_step1', 'get_step1_status', 'set_project_start_mode', 'get_project_start_mode', 'set_project_start_asset_scope', 'get_project_start_asset_scope', 'set_project_start_plate_source', 'clear_project_start_plate_source', 'get_project_start_plate_source', 'set_iteration_target', 'get_iteration_target', 'clear_iteration_target', 'set_iteration_path', 'get_iteration_path', 'get_explicit_iteration_path', 'clear_iteration_path', 'set_graph_selected_edge_key', 'get_graph_selected_edge_key', 'clear_graph_selected_edge_key', 'get_last_iteration_target', 'get_project_status', 'is_project_completed', 'is_project_paused', 'get_project_paused_at', 'get_project_completed_at', 'pause_project', 'complete_project', 'reopen_project', 'set_step2_generated', 'approve_step2', 'reset_step2', 'get_step2_status', 'get_step2_staging_run', 'set_step3_needs_rework', 'set_step3_ready', 'approve_step3', 'set_step3_pending', 'reset_step3', 'get_step3_status', 'get_step3_substep', 'set_step3_substep', 'is_step3_stage1_done', 'set_step3_stage1_done', 'is_step3_stage2_done', 'set_step3_stage2_done', 'reset_step3_progress', 'get_step3_extract_state', 'get_step3_preview_dir', 'set_step3_preview_dir', 'set_step3_extract_state')


_STATIC_METHODS = ('_normalize_project_start_mode', '_normalize_project_start_asset_scope', '_project_start_asset_scope_state_key', '_normalize_iteration_target', '_normalize_iteration_path')


def bind_campaign_stage_state_methods(manager_cls):
    for method_name in _INSTANCE_METHODS:
        setattr(manager_cls, method_name, globals()[method_name])
    for method_name in _STATIC_METHODS:
        setattr(manager_cls, method_name, staticmethod(globals()[method_name]))
    return manager_cls
