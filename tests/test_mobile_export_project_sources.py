import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from auto_annotation_tool.gui import z4_model_export


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self.DIR_9_PROJECTS = root / "Workspace" / "9_projects"
        self._trained_root = root / "Workspace" / "6_models" / "trained"
        self._runs_root = root / "Workspace" / "5_training_runs"
        self.DIR_5_RUNS = self._runs_root
        self.DIR_6_MODELS_BASE_POSE = root / "Workspace" / "6_models" / "base" / "pose"
        self.DIR_6_MODELS_BASE_DETECT = root / "Workspace" / "6_models" / "base" / "detect"
        self.DIR_6_MODELS_PLATES = self._trained_root / "plates"
        self.DIR_6_MODELS_CHARS = self._trained_root / "chars"

    def normalize_task_target(self, target: str) -> str:
        return {"character": "char", "chars": "char", "plates": "plate", "vehicles": "vehicle"}.get(
            str(target or "").strip().lower(),
            str(target or "").strip().lower(),
        )

    def get_trained_models_dir(self, target: str) -> Path:
        return self._trained_root / {
            "plate": "plates",
            "char": "chars",
            "vehicle": "vehicles",
        }[self.normalize_task_target(target)]

    def get_training_runs_dir(self, target: str) -> Path:
        return self._runs_root / {
            "plate": "plates",
            "char": "chars",
            "vehicle": "vehicles",
        }[self.normalize_task_target(target)]


def test_mobile_export_artifact_sources_include_all_project_model_dirs(tmp_path):
    config = _FakeConfig(tmp_path)
    for project_name in ("alpha_123", "beta_456"):
        (config.DIR_9_PROJECTS / project_name / "6_models" / "trained" / "plates").mkdir(parents=True)
        (config.DIR_9_PROJECTS / project_name / "6_models" / "trained" / "chars").mkdir(parents=True)
        (config.DIR_9_PROJECTS / project_name / "6_models" / "trained" / "vehicles").mkdir(parents=True)

    campaign = SimpleNamespace(
        get_active_project_name=lambda: "",
        get_active_project_root_dir=lambda: None,
    )

    with patch.object(z4_model_export, "CONFIG", config), patch.object(z4_model_export, "CAMPAIGN", campaign):
        sources = z4_model_export._mobile_export_artifact_sources(SimpleNamespace())

    project_sources = {
        (path.parts[-4], path.name, target, project_name)
        for path, target, _label, project_name, _project_root in sources
        if project_name
    }

    assert ("alpha_123", "plates", "plate", "alpha_123") in project_sources
    assert ("alpha_123", "chars", "char", "alpha_123") in project_sources
    assert ("alpha_123", "vehicles", "vehicle", "alpha_123") in project_sources
    assert ("beta_456", "plates", "plate", "beta_456") in project_sources
    assert ("beta_456", "chars", "char", "beta_456") in project_sources
    assert ("beta_456", "vehicles", "vehicle", "beta_456") in project_sources


def test_mobile_export_history_sources_include_all_project_training_dirs(tmp_path):
    config = _FakeConfig(tmp_path)
    for project_name in ("alpha_123", "beta_456"):
        (config.DIR_9_PROJECTS / project_name / "5_training_runs").mkdir(parents=True)

    campaign = SimpleNamespace(
        get_active_project_name=lambda: "",
        get_active_project_root_dir=lambda: None,
    )
    host = SimpleNamespace(_format_training_target_label=lambda target: target)

    with patch.object(z4_model_export, "CONFIG", config), patch.object(z4_model_export, "CAMPAIGN", campaign):
        sources = z4_model_export._mobile_export_history_sources(host)

    project_sources = {
        (path.parts[-2], project_name, project_root)
        for path, _label, project_name, project_root in sources
        if project_name
    }

    assert ("alpha_123", "alpha_123", str(config.DIR_9_PROJECTS / "alpha_123")) in project_sources
    assert ("beta_456", "beta_456", str(config.DIR_9_PROJECTS / "beta_456")) in project_sources


def test_mobile_export_collect_candidates_preserves_project_from_history(tmp_path):
    config = _FakeConfig(tmp_path)
    project_root = config.DIR_9_PROJECTS / "pisto_21600B"
    history_dir = project_root / "5_training_runs"
    history_dir.mkdir(parents=True)
    weights_path = tmp_path / "external_models" / "best.pt"
    weights_path.parent.mkdir(parents=True)
    weights_path.write_bytes(b"pt")
    (history_dir / "training_history.json").write_text(
        json.dumps(
            {
                "runs": {
                    "run_001": {
                        "id": "run_001",
                        "name": "Trening znaków",
                        "created_at": "2026-08-02T16:03:00",
                        "status": "completed",
                        "dataset_path": str(project_root / "4_training_datasets" / "chars" / "data.yaml"),
                        "base_model": "yolo26n.pt",
                        "best_weights": str(weights_path),
                        "output_dir": str(project_root / "5_training_runs" / "run_001"),
                        "img_size": 448,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    campaign = SimpleNamespace(
        get_active_project_name=lambda: "",
        get_active_project_root_dir=lambda: None,
    )

    class _Host:
        history = None

        @staticmethod
        def _format_training_target_label(target):
            return target

        def _infer_history_run_target(self, run):
            return z4_model_export._infer_history_run_target(self, run)

        def _resolve_history_run_best_weights(self, run):
            return z4_model_export._resolve_history_run_best_weights(self, run)

        def _build_history_run_metric_summary(self, run):
            return z4_model_export._build_history_run_metric_summary(self, run)

        @staticmethod
        def _training_metric_float(value):
            try:
                return float(value)
            except Exception:
                return None

        @classmethod
        def _training_metric_value(cls, mapping, keys):
            if not isinstance(mapping, dict):
                return None
            for key in keys:
                value = cls._training_metric_float(mapping.get(key))
                if value is not None:
                    return value
            return None

    with patch.object(z4_model_export, "CONFIG", config), patch.object(z4_model_export, "CAMPAIGN", campaign):
        candidates = z4_model_export._collect_mobile_export_candidates(_Host())

    project_candidates = [candidate for candidate in candidates if candidate.get("project_name") == "pisto_21600B"]
    assert len(project_candidates) == 1
    assert project_candidates[0]["project_root"] == str(project_root)


def test_mobile_export_candidate_snapshot_carries_project_fields(tmp_path):
    config = _FakeConfig(tmp_path)
    project_root = config.DIR_9_PROJECTS / "pisto_21600B"
    model_path = project_root / "6_models" / "trained" / "chars" / "best.pt"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"pt")
    candidate = {
        "role": "character",
        "task": "detect",
        "target": "char",
        "target_label": "znaki",
        "scope": "Projekt: pisto_21600B",
        "project_name": "pisto_21600B",
        "project_root": str(project_root),
        "iid": "candidate_1",
        "best_weights": model_path,
        "model_label": "MZ-test",
    }

    with patch.object(z4_model_export, "CONFIG", config):
        snapshot = z4_model_export._mobile_export_candidate_manifest_snapshot(candidate)

    assert snapshot["project_name"] == "pisto_21600B"
    assert snapshot["project_root"] == str(project_root)
    assert snapshot["project"] == {"name": "pisto_21600B", "root": str(project_root)}
