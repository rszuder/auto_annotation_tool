"""Preanotacja Ground Truth dla kontrolowanych torów eksperymentalnych.

PREANNOTATION jest zamrożonym wynikiem modelu przed ręczną korektą.
FINAL GT powstaje dopiero po pełnym ręcznym przeglądzie zbioru.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from .repository import RegistryRepository

GT_WORKFLOW_SCHEMA = "alpr.experiment_gt_workflow.v1"
PREANNOTATION_SNAPSHOT_SCHEMA = "alpr.gt_preannotation_snapshot.v1"
PREANNOTATION_METRICS_SCHEMA = "alpr.gt_preannotation_metrics.v1"

PROFILE_LABELS = {
    "unspecified": "nieokreślony",
    "natural_distribution": "naturalny / reprezentatywny",
    "challenge_set": "challenge set / trudne przypadki",
    "stress_test": "stress test",
    "failure_analysis": "failure set / analiza błędów",
    "ood_like": "OOD-like",
    "custom": "profil własny",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def normalize_profile(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in PROFILE_LABELS else "custom"


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {}


def resolve_track_root(workspace: Path | str, track_id: str) -> Path:
    workspace = Path(workspace)
    repo = RegistryRepository.for_workspace(workspace)
    row = repo.get_evaluation_track(str(track_id or "").strip())
    if row is None:
        raise ValueError(f"Nie znaleziono toru: {track_id}")
    rel = str(_row_dict(row).get("relative_path") or "").strip()
    if not rel:
        raise ValueError(f"Tor {track_id} nie ma relative_path.")
    root = workspace / rel
    if not root.exists():
        raise ValueError(f"Brak katalogu toru: {root}")
    return root


def workflow_dir(track_root: Path | str) -> Path:
    return Path(track_root) / "gt_workflow"


def session_path(track_root: Path | str) -> Path:
    return workflow_dir(track_root) / "session.json"


def snapshot_dir(track_root: Path | str) -> Path:
    return workflow_dir(track_root) / "preannotation"


def snapshot_xml_path(track_root: Path | str) -> Path:
    return snapshot_dir(track_root) / "annotations_preannotation.xml"


def snapshot_meta_path(track_root: Path | str) -> Path:
    return snapshot_dir(track_root) / "snapshot.json"


def metrics_path(track_root: Path | str) -> Path:
    return snapshot_dir(track_root) / "metrics.json"


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return dict(value) if isinstance(value, Mapping) else {}
    except Exception:
        return {}


def save_json_atomic(path: Path | str, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(target)
    return target


def write_gt_workflow_session(
    workspace: Path | str,
    track_id: str,
    *,
    mode: str,
    dataset_profile: str,
    custom_profile: str = "",
) -> dict[str, Any]:
    clean_mode = str(mode or "").strip().lower()
    if clean_mode not in {"manual", "preannotation"}:
        raise ValueError(f"Nieobsługiwany tryb GT: {mode!r}")
    track_root = resolve_track_root(workspace, track_id)
    previous = load_json(session_path(track_root))
    profile = normalize_profile(dataset_profile)
    label = (
        str(custom_profile or "").strip()
        if profile == "custom"
        else PROFILE_LABELS.get(profile, profile)
    )
    payload = {
        "schema": GT_WORKFLOW_SCHEMA,
        "track_id": str(track_id),
        "mode": clean_mode,
        "dataset_profile": profile,
        "dataset_profile_label": label or PROFILE_LABELS["custom"],
        "custom_profile": str(custom_profile or "").strip(),
        "created_at": str(previous.get("created_at") or _utc_now()),
        "updated_at": _utc_now(),
        "full_manual_review_required": True,
        "training_export_allowed": False,
        "preannotation_is_ground_truth": False,
        "methodology_note": (
            "Preanotacja jest propozycją modelu. Każdy obraz musi zostać "
            "ręcznie przejrzany; dopiero poprawiony wynik jest FINAL GT."
        ),
    }
    for key in ("preannotation_snapshot_sha256", "preannotation_model_sha256"):
        if previous.get(key):
            payload[key] = previous[key]
    save_json_atomic(session_path(track_root), payload)
    return payload


def create_preannotation_snapshot(
    workspace: Path | str,
    track_id: str,
    annotations_xml: Path | str,
    *,
    model_path: Path | str | None = None,
    runtime_meta: Mapping[str, Any] | None = None,
    annotation_run_dir: Path | str | None = None,
) -> dict[str, Any]:
    source = Path(annotations_xml)
    if not source.exists():
        raise ValueError(f"Brak XML preanotacji: {source}")
    track_root = resolve_track_root(workspace, track_id)
    target = snapshot_xml_path(track_root)
    meta_file = snapshot_meta_path(track_root)
    existing = load_json(meta_file)

    if target.exists() and existing:
        expected = str(existing.get("annotations_sha256") or "").lower()
        actual = sha256_file(target)
        if expected and expected != actual:
            raise RuntimeError(
                "Snapshot preanotacji istnieje, ale jego SHA-256 nie zgadza się "
                "z metadanymi. Automatyczne nadpisanie jest zablokowane."
            )
        return existing

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".xml.tmp")
    shutil.copy2(source, temp)
    if sha256_file(temp) != sha256_file(source):
        temp.unlink(missing_ok=True)
        raise RuntimeError("Kopia snapshotu preanotacji ma inne SHA-256.")
    temp.replace(target)

    model = Path(model_path) if model_path else None
    model_sha = ""
    if model and model.exists() and model.is_file():
        try:
            model_sha = sha256_file(model)
        except Exception:
            pass
    session = load_json(session_path(track_root))
    meta = {
        "schema": PREANNOTATION_SNAPSHOT_SCHEMA,
        "track_id": str(track_id),
        "created_at": _utc_now(),
        "annotations_relative_path": str(target.relative_to(track_root)).replace("\\", "/"),
        "annotations_sha256": sha256_file(target),
        "annotation_run_dir": str(annotation_run_dir or ""),
        "model_path": str(model or ""),
        "model_name": model.name if model else "",
        "model_sha256": model_sha,
        "runtime_meta": dict(runtime_meta or {}),
        "dataset_profile": str(session.get("dataset_profile") or "unspecified"),
        "dataset_profile_label": str(session.get("dataset_profile_label") or ""),
        "full_manual_review_required": True,
        "immutable": True,
    }
    save_json_atomic(meta_file, meta)
    if session:
        session["preannotation_snapshot_sha256"] = meta["annotations_sha256"]
        session["preannotation_model_sha256"] = model_sha
        session["updated_at"] = _utc_now()
        save_json_atomic(session_path(track_root), session)
    return meta


def _points(raw: str) -> tuple[tuple[float, float], ...]:
    result = []
    for pair in str(raw or "").split(";"):
        parts = pair.strip().split(",")
        if len(parts) != 2:
            continue
        try:
            result.append((float(parts[0]), float(parts[1])))
        except Exception:
            pass
    return tuple(result)


def _bbox(points):
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _parse_xml(path: Path | str) -> dict[str, list[dict[str, Any]]]:
    root = ET.parse(Path(path)).getroot()
    images: dict[str, list[dict[str, Any]]] = {}
    for image in root.findall(".//image"):
        name = str(image.get("name") or "").strip()
        if not name:
            continue
        objects = []
        for poly in image.findall("./polygon"):
            pts = _points(poly.get("points") or "")
            if len(pts) >= 3:
                objects.append({
                    "label": str(poly.get("label") or ""),
                    "kind": "polygon",
                    "points": pts,
                    "bbox": _bbox(pts),
                })
        for box in image.findall("./box"):
            try:
                x1 = float(box.get("xtl") or 0)
                y1 = float(box.get("ytl") or 0)
                x2 = float(box.get("xbr") or 0)
                y2 = float(box.get("ybr") or 0)
            except Exception:
                continue
            pts = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            objects.append({
                "label": str(box.get("label") or ""),
                "kind": "box",
                "points": pts,
                "bbox": (x1, y1, x2, y2),
            })
        images[name] = objects
    return images


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _point_delta(pred, gt) -> float | None:
    if len(pred["points"]) != len(gt["points"]) or not pred["points"]:
        return None
    values = [
        math.hypot(px - gx, py - gy)
        for (px, py), (gx, gy) in zip(pred["points"], gt["points"])
    ]
    return sum(values) / len(values)


def _corner_error(pred, gt) -> float | None:
    if len(pred["points"]) != 4 or len(gt["points"]) != 4:
        return None
    x1, y1, x2, y2 = gt["bbox"]
    diag = math.hypot(x2 - x1, y2 - y1)
    if diag <= 0:
        return None
    return (
        sum(
            math.hypot(px - gx, py - gy)
            for (px, py), (gx, gy) in zip(pred["points"], gt["points"])
        )
        / 4.0
        / diag
    )


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * 0.95
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return data[lo]
    frac = pos - lo
    return data[lo] * (1 - frac) + data[hi] * frac


def compute_preannotation_metrics(
    preannotation_xml: Path | str,
    final_gt_xml: Path | str,
    *,
    iou_threshold: float = 0.5,
    unchanged_tolerance_px: float = 1.0,
) -> dict[str, Any]:
    pred = _parse_xml(preannotation_xml)
    final = _parse_xml(final_gt_xml)
    names = sorted(set(pred) | set(final))
    tp = fp = fn = unchanged = corrected = images_clean = 0
    corner_errors: list[float] = []
    per_image = []

    for name in names:
        p_objs = list(pred.get(name, []))
        g_objs = list(final.get(name, []))
        candidates = []
        for pi, p in enumerate(p_objs):
            for gi, g in enumerate(g_objs):
                if p["label"] and g["label"] and p["label"] != g["label"]:
                    continue
                score = _iou(p["bbox"], g["bbox"])
                if score >= iou_threshold:
                    candidates.append((score, pi, gi))
        candidates.sort(reverse=True)
        used_p, used_g = set(), set()
        image_corrected = image_unchanged = 0
        for _score, pi, gi in candidates:
            if pi in used_p or gi in used_g:
                continue
            used_p.add(pi)
            used_g.add(gi)
            p, g = p_objs[pi], g_objs[gi]
            delta = _point_delta(p, g)
            if (
                p["kind"] == g["kind"]
                and p["label"] == g["label"]
                and delta is not None
                and delta <= unchanged_tolerance_px
            ):
                unchanged += 1
                image_unchanged += 1
            else:
                corrected += 1
                image_corrected += 1
            ce = _corner_error(p, g)
            if ce is not None:
                corner_errors.append(ce)

        image_tp = len(used_p)
        image_fp = len(p_objs) - image_tp
        image_fn = len(g_objs) - len(used_g)
        tp += image_tp
        fp += image_fp
        fn += image_fn
        if image_fp == 0 and image_fn == 0 and image_corrected == 0 and len(p_objs) == len(g_objs):
            images_clean += 1
        per_image.append({
            "image_name": name,
            "predicted_objects": len(p_objs),
            "final_objects": len(g_objs),
            "matched_objects": image_tp,
            "false_positives": image_fp,
            "missed_objects": image_fn,
            "accepted_without_edit": image_unchanged,
            "geometry_corrected": image_corrected,
        })

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    edit_actions = fp + fn + corrected
    denominator = max(1, tp + fp + fn)
    final_count = tp + fn

    return {
        "schema": PREANNOTATION_METRICS_SCHEMA,
        "computed_at": _utc_now(),
        "images": len(names),
        "predicted_objects": tp + fp,
        "final_objects": final_count,
        "matched_objects": tp,
        "false_positives": fp,
        "missed_objects": fn,
        "accepted_without_edit": unchanged,
        "geometry_corrected": corrected,
        "images_without_edit": images_clean,
        "auto_precision": precision,
        "auto_recall": recall,
        "auto_f1": f1,
        "human_edit_actions": edit_actions,
        "human_edit_rate": edit_actions / denominator,
        "accepted_without_edit_rate": unchanged / max(1, final_count),
        "images_without_edit_rate": images_clean / max(1, len(names)),
        "mean_initial_corner_error": statistics.fmean(corner_errors) if corner_errors else None,
        "p95_initial_corner_error": _p95(corner_errors),
        "corner_error_samples": len(corner_errors),
        "requires_independent_track": True,
        "validity": "PENDING_INDEPENDENCE",
        "metric_scope": (
            "Metryka opisuje PREANNOTATION względem ręcznie poprawionego FINAL GT "
            "dla tego toru. Interpretacja jako niezależnego testu wymaga osobnego "
            "potwierdzenia niezależności toru od train/val."
        ),
        "per_image": per_image,
    }


def maybe_compute_preannotation_metrics_for_track(
    track_root: Path | str,
    final_gt_xml: Path | str,
) -> dict[str, Any]:
    root = Path(track_root)
    snapshot = snapshot_xml_path(root)
    if not snapshot.exists():
        return {}
    meta = load_json(snapshot_meta_path(root))
    expected = str(meta.get("annotations_sha256") or "").lower()
    actual = sha256_file(snapshot)
    if expected and expected != actual:
        raise RuntimeError("Snapshot preanotacji zmienił zawartość.")
    metrics = compute_preannotation_metrics(snapshot, final_gt_xml)
    session = load_json(session_path(root))
    metrics.update({
        "track_id": str(session.get("track_id") or ""),
        "dataset_profile": str(session.get("dataset_profile") or "unspecified"),
        "dataset_profile_label": str(session.get("dataset_profile_label") or ""),
        "preannotation_model_name": str(meta.get("model_name") or ""),
        "preannotation_model_sha256": str(meta.get("model_sha256") or ""),
        "preannotation_snapshot_sha256": actual,
        "final_gt_sha256": sha256_file(final_gt_xml),
    })
    save_json_atomic(metrics_path(root), metrics)
    return metrics


def get_gt_preparation_summary(workspace: Path | str, track_id: str) -> dict[str, Any]:
    try:
        root = resolve_track_root(workspace, track_id)
    except Exception:
        return {}
    session = load_json(session_path(root))
    meta = load_json(snapshot_meta_path(root))
    metrics = load_json(metrics_path(root))
    if not session and not meta and not metrics:
        return {}
    return {
        "mode": str(session.get("mode") or ""),
        "dataset_profile": str(session.get("dataset_profile") or "unspecified"),
        "dataset_profile_label": str(session.get("dataset_profile_label") or ""),
        "snapshot_exists": snapshot_xml_path(root).exists(),
        "model_name": str(meta.get("model_name") or ""),
        "model_sha256": str(meta.get("model_sha256") or ""),
        "metrics": metrics,
    }
