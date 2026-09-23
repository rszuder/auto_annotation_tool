"""Result rules shared by Z2's worker and the final preview merge."""

from ..config import CONFIG
import copy
from pathlib import Path


def remove_vehicle_assistance(annotations) -> int:
    """Remove auxiliary vehicle detections from a new plate-only result.

    Call only on the new result, never on the pre-run rollback snapshot.
    Imported/manual plate geometry and its attributes remain unchanged.
    """
    removed = 0
    for annotation in annotations:
        detections = list(annotation.detections or [])
        retained = [
            detection for detection in detections
            if str(detection.label or "").strip().lower() not in CONFIG.VEHICLE_LABELS
        ]
        removed += len(detections) - len(retained)
        annotation.detections = retained
    return removed


def merge_completed_view(annotations, image_map, previous_state):
    """Keep unprocessed rows before committing the run, outside the Tk thread."""
    previous = list(previous_state.get("annotations") or [])
    if not previous:
        return annotations, image_map
    by_name = {ann.filename.lower(): ann for ann in annotations}
    result, seen = [], set()
    merged_map = dict(previous_state.get("image_map") or {})
    merged_map.update(image_map)
    for old in previous:
        name = old.filename.lower()
        if name in seen:
            continue
        seen.add(name)
        result.append(by_name[name] if name in by_name else copy.deepcopy(old))
    result.extend(ann for ann in annotations if ann.filename.lower() not in seen)
    return result, merged_map


def protected_view_bundle(previous_state, protected_names):
    """Reference the single rollback copy; worker merging copies replacements."""
    paths = {str(name).lower(): path for name, path in (previous_state.get("image_map") or {}).items()}
    input_dir = previous_state.get("input_dir")
    approved = {str(name).lower() for name in previous_state.get("approved_filenames", ())}
    bundle = {}
    for ann in previous_state.get("annotations") or []:
        name = ann.filename.lower()
        if name not in protected_names:
            continue
        path = paths.get(name)
        if path is None and input_dir:
            path = Path(input_dir) / ann.filename
        if path is not None:
            ann._approved_for_training = bool(getattr(ann, "_approved_for_training", False) or name in approved)
            bundle[ann.filename] = (ann, Path(path))
    return bundle
