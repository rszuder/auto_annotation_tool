# Stała przestrzeń robocza eksperymentów i kontekst Z2.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping

EXPERIMENT_Z2_CONTEXT_SCHEMA = "alpr.experiment_z2_context.v1"

@dataclass(frozen=True)
class ExperimentWorkspacePaths:
    root: Path
    sources_root: Path
    annotations_root: Path
    tracks_root: Path
    runs_root: Path
    results_root: Path
    state_root: Path
    source_images: Path
    annotation_runs: Path
    experiment_runs: Path
    experiment_results: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "sources_root": str(self.sources_root),
            "annotations_root": str(self.annotations_root),
            "tracks_root": str(self.tracks_root),
            "runs_root": str(self.runs_root),
            "results_root": str(self.results_root),
            "state_root": str(self.state_root),
            "source_images": str(self.source_images),
            "annotation_runs": str(self.annotation_runs),
            "experiment_runs": str(self.experiment_runs),
            "experiment_results": str(self.experiment_results),
        }

def experiment_roots(workspace_dir: Path | str) -> dict[str, Path]:
    workspace = Path(workspace_dir)
    root = workspace / "10_experiments"
    return {
        "root": root,
        "sources": root / "sources",
        "annotations": root / "annotations",
        "tracks": root / "tracks",
        "runs": root / "runs",
        "results": root / "results",
        "state": root / "_state",
    }

def experiment_workspace_for_track(
    workspace_dir: Path | str,
    track: Mapping[str, Any],
) -> ExperimentWorkspacePaths:
    workspace = Path(workspace_dir)
    roots = experiment_roots(workspace)
    relative = str(track.get("relative_path") or "").strip()
    target = _safe_segment(str(track.get("target") or "unknown"))
    folder = _safe_segment(Path(relative).name if relative else "")
    if not folder:
        folder = _safe_segment(str(track.get("track_id") or "track")) or "track"
    return ExperimentWorkspacePaths(
        root=roots["root"],
        sources_root=roots["sources"],
        annotations_root=roots["annotations"],
        tracks_root=roots["tracks"],
        runs_root=roots["runs"],
        results_root=roots["results"],
        state_root=roots["state"],
        source_images=roots["sources"] / target / folder / "images",
        annotation_runs=roots["annotations"] / target / folder,
        experiment_runs=roots["runs"] / target / folder,
        experiment_results=roots["results"] / target / folder,
    )

def ensure_experiment_workspace(paths: ExperimentWorkspacePaths) -> ExperimentWorkspacePaths:
    for path in (
        paths.root, paths.sources_root, paths.annotations_root,
        paths.tracks_root, paths.runs_root, paths.results_root,
        paths.state_root, paths.source_images, paths.annotation_runs,
        paths.experiment_runs, paths.experiment_results,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return paths

def active_z2_context_path(workspace_dir: Path | str) -> Path:
    return experiment_roots(workspace_dir)["state"] / "active_z2_context.json"

def activate_z2_experiment_context(
    workspace_dir: Path | str,
    track: Mapping[str, Any],
) -> dict[str, Any]:
    workspace = Path(workspace_dir)
    paths = ensure_experiment_workspace(experiment_workspace_for_track(workspace, track))
    track_id = str(track.get("track_id") or "").strip()
    if not track_id:
        raise ValueError("Kontekst Z2 wymaga track_id.")
    payload = {
        "schema": EXPERIMENT_Z2_CONTEXT_SCHEMA,
        "track_id": track_id,
        "name": str(track.get("name") or "").strip(),
        "target": str(track.get("target") or "").strip().lower(),
        "purpose": str(track.get("purpose") or "").strip().lower(),
        "source_relative_path": _workspace_relative(workspace, paths.source_images),
        "annotation_relative_path": _workspace_relative(workspace, paths.annotation_runs),
        "run_relative_path": _workspace_relative(workspace, paths.experiment_runs),
        "result_relative_path": _workspace_relative(workspace, paths.experiment_results),
        "training_dataset_export_allowed": False,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    context_path = active_z2_context_path(workspace)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(context_path, payload)
    return _resolve_context_paths(workspace, payload)

def load_active_z2_experiment_context(workspace_dir: Path | str) -> dict[str, Any]:
    workspace = Path(workspace_dir)
    context_path = active_z2_context_path(workspace)
    if not context_path.is_file():
        return {}
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    if str(payload.get("schema") or "") != EXPERIMENT_Z2_CONTEXT_SCHEMA:
        return {}
    if bool(payload.get("training_dataset_export_allowed", True)):
        return {}
    resolved = _resolve_context_paths(workspace, payload)
    root = experiment_roots(workspace)["root"]
    for field in ("source_dir", "annotation_dir", "experiment_run_dir", "experiment_result_dir"):
        if not _is_within(Path(str(resolved.get(field) or "")), root):
            return {}
    return resolved

def clear_active_z2_experiment_context(
    workspace_dir: Path | str,
    *,
    track_id: str | None = None,
) -> bool:
    context_path = active_z2_context_path(workspace_dir)
    if not context_path.exists():
        return False
    if track_id:
        current = load_active_z2_experiment_context(workspace_dir)
        if str(current.get("track_id") or "") != str(track_id):
            return False
    try:
        context_path.unlink()
    except FileNotFoundError:
        return False
    return True

def _resolve_context_paths(workspace: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    resolved = dict(payload)
    resolved["source_dir"] = str(workspace / str(payload.get("source_relative_path") or ""))
    resolved["annotation_dir"] = str(workspace / str(payload.get("annotation_relative_path") or ""))
    resolved["experiment_run_dir"] = str(workspace / str(payload.get("run_relative_path") or ""))
    resolved["experiment_result_dir"] = str(workspace / str(payload.get("result_relative_path") or ""))
    return resolved

def _workspace_relative(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except Exception as exc:
        raise ValueError("Ścieżka eksperymentu musi leżeć w Workspace.") from exc

def _safe_segment(value: str) -> str:
    safe = [
        char if (char.isalnum() or char in {"-", "_", "."}) else "_"
        for char in str(value or "").strip()
    ]
    return "".join(safe).strip("._-")[:120]

def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False

def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)
