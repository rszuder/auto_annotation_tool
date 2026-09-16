"""Read optional participant background from registered run artifacts, without scanning."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .bootstrap import registry_run_id

METRIC_FIELDS = (
    "best_map50", "best_map50_95", "box_map50", "box_map50_95",
    "pose_map50", "pose_map50_95",
)
_CSV_FIELDS = {
    "best_map50": "metrics/mAP50", "best_map50_95": "metrics/mAP50-95",
    "box_map50": "metrics/mAP50(B)", "box_map50_95": "metrics/mAP50-95(B)",
    "pose_map50": "metrics/mAP50(P)", "pose_map50_95": "metrics/mAP50-95(P)",
}


def metric_value(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _best(values) -> float | None:
    valid = [number for value in values if (number := metric_value(value)) is not None]
    return max(valid) if valid else None


class ParticipantBackgroundReader:
    """Cache each directly addressed artifact until its size or modification time changes."""
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self._files: dict[Path, tuple[Any, Any]] = {}

    def _read(self, path: Path, *, csv_file=False):
        try:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except OSError:
            return {}
        cached = self._files.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1]
        try:
            if csv_file:
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = [
                        {str(k or "").strip(): value for k, value in row.items()}
                        for row in csv.DictReader(stream)
                    ]
                result = {
                    name: _best(row.get(column) for row in rows)
                    for name, column in _CSV_FIELDS.items()
                }
            else:
                result = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(result, Mapping):
                    result = {}
        except (OSError, ValueError, csv.Error):
            result = {}
        self._files[path] = (signature, result)
        return result

    def _path(self, value) -> Path | None:
        text = str(value or "").strip()
        if not text:
            return None
        path = Path(text)
        return path if path.is_absolute() else self.workspace / path

    def _history_run(self, output: Path, row: Mapping) -> Mapping:
        # Only the registered output's nearby ancestors; no recursive discovery.
        for directory in (output, *list(output.parents)[:3]):
            payload = self._read(directory / "training_history.json")
            runs = payload.get("runs", {})
            if not isinstance(runs, Mapping):
                continue
            for key, candidate in runs.items():
                if not isinstance(candidate, Mapping):
                    continue
                candidate_id = str(candidate.get("id") or key)
                if registry_run_id(
                    candidate_id, project_id=row.get("run_project_id"),
                    target=str(row.get("run_target") or row.get("target") or ""),
                ) != row["run_id"]:
                    continue
                recorded_output = self._path(candidate.get("output_dir"))
                if recorded_output is not None and recorded_output.resolve() != output.resolve():
                    continue
                return candidate
        return {}

    def read(self, row: Mapping) -> dict[str, Any]:
        result = {field: None for field in METRIC_FIELDS}
        output = self._path(row.get("output_relative_path"))
        if output is None:
            return result
        history = self._history_run(output, row)
        metrics = history.get("metrics_history", [])
        metrics = [item for item in metrics if isinstance(item, Mapping)] if isinstance(metrics, list) else []
        for field in METRIC_FIELDS:
            # Generic history mAP has no reliable Pose/BBox type.
            alias = {"best_map50": "map50", "best_map50_95": "map50_95"}.get(field, field)
            result[field] = metric_value(history.get(field))
            if result[field] is None:
                result[field] = _best(item.get(alias) for item in metrics)
        if any(value is None for value in result.values()):
            for path in (output / "train" / "results.csv", output / "results.csv"):
                csv_metrics = self._read(path, csv_file=True)
                for field in METRIC_FIELDS:
                    if result[field] is None:
                        result[field] = csv_metrics.get(field)
        return result
