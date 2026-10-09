"""Phase 2A: read-only MT input/GT preflight and explicit operator attestation.

No model loader, predictor, dataset builder or inference entry point lives here.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import uuid

import cv2
import numpy as np
import PIL

from ..image_orientation import ORIENTATION_POLICY, DECODER, inspect_oriented_image
from .eval396 import EvidenceReader, SELECTION_SHA, FREEZE_SHA, _read_selection, contained, digest, require

REVIEW_SCHEMA = "alpr.mt_geometry_preflight.v1"
APPROVAL_SCHEMA = "alpr.mt_geometry_operator_contract.v1"
CORNER_NAMES = ("TL", "TR", "BR", "BL")
POLICY = {"id": ORIENTATION_POLICY, "pixel_space": "EXIF-oriented original scene XY",
          "decoder": DECODER, "input_format": "BGR uint8", "gt_transform": "none",
          "gt_corner_order": list(CORNER_NAMES), "corner_reordering": "forbidden",
          "bounds_tolerance_px": 1.0, "pillow_comparison_mae_limit": 6.0, "pillow_comparison_p95_limit": 18.0}


def validate_gt_geometry(bbox, polygon, width, height):
    def number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("GT_NONFINITE_OR_NONNUMERIC_COORDINATE")
        return float(value)
    require(isinstance(bbox, (list, tuple)) and len(bbox) == 4, "GT_BBOX_MISSING_OR_INVALID")
    x1, y1, x2, y2 = box = [number(value) for value in bbox]
    require(x1 < x2 and y1 < y2, "GT_BBOX_DEGENERATE")
    require(isinstance(polygon, (list, tuple)) and len(polygon) == 4, "GT_QUAD_MISSING_OR_NOT_FOUR_CORNERS")
    points = []
    for point in polygon:
        require(isinstance(point, (list, tuple)) and len(point) == 2, "GT_INVALID_CORNER")
        points.append([number(point[0]), number(point[1])])
    tolerance = POLICY["bounds_tolerance_px"]
    for x, y in [(x1, y1), (x2, y2), *points]:
        require(-tolerance <= x <= width + tolerance and -tolerance <= y <= height + tolerance,
                "GT_OUTSIDE_ORIENTED_SCENE")
    cross = []
    for i in range(4):
        a, b, c = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
        cross.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    require(not all(value < -1e-6 for value in cross), "GT_CORNER_ORDER_REVERSED")
    require(all(value > 1e-6 for value in cross), "GT_QUAD_INVALID")
    require(points[0][0] + points[3][0] < points[1][0] + points[2][0]
            and points[0][1] + points[1][1] < points[2][1] + points[3][1], "GT_CORNER_ORDER_NOT_TL_TR_BR_BL")
    return box, points


def review_fingerprint(report):
    return digest({key: report[key] for key in ("schema", "selection_sha", "gt_freeze_sha", "policy",
                  "models", "scenes", "counts", "geometry_issues", "review_scene_hashes", "runtime", "code_sha256", "source_files")})


def preflight_mt_geometry(selection_dir, *, repo_root=None, progress=None, cancelled=None):
    repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    selection_dir = Path(selection_dir).resolve()
    if selection_dir.name == "selection_manifest.json":
        selection_dir = selection_dir.parent
    def notify(message):
        if cancelled and cancelled():
            raise InterruptedError("Sprawdzanie geometrii anulowane")
        if progress:
            progress(message)
    reader = EvidenceReader(notify)
    notify("Weryfikuję selekcję, freeze, checkpointy i niezależność źródeł…")
    manifest, selection = _read_selection(reader, selection_dir, repo_root)
    references = manifest["references"]
    scene_root = contained(repo_root, references["source_scene_root"])
    freeze = contained(repo_root, references["source_snapshot_folder"])
    metadata = reader.json(freeze / "metadata.json", references["parent_metadata_sha256"])
    by_scene = {}
    for plate in selection["included_plates.json"]:
        by_scene.setdefault(plate["source_file_sha256"], []).append(plate)
    scenes, issues = [], []
    for index, row in enumerate(selection["included_scenes.json"], 1):
        notify(f"Geometria i EXIF: scena {index}/396 — {row['file']}")
        path = contained(scene_root, row["file"])
        try:
            image, image_info = inspect_oriented_image(path)
        except (ValueError, OSError) as exc:
            raise ValueError(f"{row['file']}: {exc}") from exc
        width, height = image_info["oriented_size"]
        plates = []
        for plate in by_scene[row["sha256"]]:
            original = metadata[plate["plate_id"]]
            require(original.get("source_file_sha256") == row["sha256"], "GT_SOURCE_IDENTITY_MISMATCH")
            try:
                box, quad = validate_gt_geometry(original.get("source_bbox"), original.get("source_polygon"), width, height)
            except ValueError as exc:
                issues.append({"scene": row["file"], "sha256": row["sha256"], "plate_id": plate["plate_id"], "reason": str(exc)})
                box, quad = original.get("source_bbox"), original.get("source_polygon")
            plates.append({"plate_id": plate["plate_id"], "source_annotation_id": plate["source_annotation_id"],
                           "text_decision": plate["decision"], "bbox": box, "quad": quad,
                           "geometry_issue": next((i["reason"] for i in issues if i["plate_id"] == plate["plate_id"]), "")})
        scenes.append({**row, "image": image_info, "plates": plates})
        del image
    counts = {"scenes": len(scenes), "plates": sum(len(s["plates"]) for s in scenes),
              "scene_domains": dict(Counter(s["domain"] for s in scenes)),
              "plate_domains": {domain: sum(len(s["plates"]) for s in scenes if s["domain"] == domain)
                                for domain in ("DAY", "NIGHT")},
              "unreadable_included": sum(p["text_decision"] == "excluded_unreadable" for s in scenes for p in s["plates"])}
    require(counts == {"scenes": 396, "plates": 479, "scene_domains": {"DAY": 199, "NIGHT": 197},
                      "plate_domains": {"DAY": 235, "NIGHT": 244}, "unreadable_included": 30}, "MT_POPULATION_CHANGED")
    review = [s["sha256"] for s in scenes if s["image"]["exif_orientation"] != 1]
    # Two stable ordinary controls, including all GT plates on each chosen scene.
    for domain in ("DAY", "NIGHT"):
        control = next(s for s in scenes if s["domain"] == domain and s["image"]["exif_orientation"] == 1)
        review.append(control["sha256"])
    review = list(dict.fromkeys(review + [issue["sha256"] for issue in issues]))
    code = {}
    for name in ("image_orientation.py", "annotators/base.py", "annotators/plate_annotator.py",
                 "ranking/mt_geometry_review.py"):
        code[name] = hashlib.sha256(reader.read(repo_root / "auto_annotation_tool" / name)).hexdigest()
    report = {"schema": REVIEW_SCHEMA, "status": "FAIL" if issues else "READY_FOR_REVIEW", "selection_sha": SELECTION_SHA,
        "gt_freeze_sha": FREEZE_SHA, "policy": dict(POLICY), "source_scene_root": str(scene_root),
        "selection_dir": str(selection_dir), "freeze_dir": str(freeze),
        "models": [m for m in selection["model_lineage.json"] if m["role"] == "plate"],
        "scenes": scenes, "counts": counts, "geometry_issues": issues, "review_scene_hashes": review,
        "runtime": {"opencv": cv2.__version__, "pillow": PIL.__version__, "numpy": np.__version__},
        "code_sha256": code, "source_files": dict(reader.receipt),
        "checkpoint_tensor_contract": "NOT_INSPECTED_PHASE2A", "inference_performed": False,
        "visual_gt_approved": False, "created_at": datetime.now(timezone.utc).isoformat()}
    reader.finish()
    report["review_sha256"] = review_fingerprint(report)
    return report


def recheck_review(report, *, allow_geometry_failure=False):
    require(report.get("schema") == REVIEW_SCHEMA, "PREFLIGHT_SCHEMA_INVALID")
    ready = report.get("status") == "READY_FOR_REVIEW" and not report.get("geometry_issues")
    require(ready or (allow_geometry_failure and report.get("status") == "FAIL"), "PREFLIGHT_NOT_READY")
    require(report.get("review_sha256") == review_fingerprint(report), "PREFLIGHT_CHANGED")
    require(report["selection_sha"] == SELECTION_SHA and report["gt_freeze_sha"] == FREEZE_SHA
            and report["policy"] == POLICY, "GEOMETRY_POLICY_CHANGED")
    reader = EvidenceReader()
    reader.receipt = dict(report["source_files"])
    reader.finish()


def save_operator_decision(report, output_root, *, operator, reviewed_scenes, accepted, reason=""):
    """Called only after the operator explicitly confirms/rejects in the GUI.

    The name and SHA are a local attestation/integrity seal, not a PKI signature.
    Neither outcome invokes a model or edits a frozen data artifact.
    """
    require(isinstance(operator, str) and operator.strip(), "OPERATOR_SIGNATURE_REQUIRED")
    require(type(accepted) is bool, "EXPLICIT_DECISION_REQUIRED")
    if accepted:
        require(set(reviewed_scenes) == set(report["review_scene_hashes"]), "ALL_REVIEW_SCENES_MUST_BE_CONFIRMED")
    else:
        require(bool(reason.strip()), "REJECTION_REASON_REQUIRED")
    recheck_review(report, allow_geometry_failure=not accepted)
    output_root = Path(output_root).resolve()
    experiment_root = Path(report["selection_dir"]).parent.parent
    protected = [Path(report[key]).resolve() for key in ("selection_dir", "freeze_dir", "source_scene_root")]
    protected.append(experiment_root / "evaluation_runs/E-MZ-DN-01_EVAL396_MZ_v1")
    require(not any(output_root.is_relative_to(path) for path in protected), "PROTECTED_OUTPUT_DIRECTORY")
    decision = {"schema": APPROVAL_SCHEMA, "policy": dict(POLICY), "selection_sha": SELECTION_SHA,
                "gt_freeze_sha": FREEZE_SHA, "review_sha256": report["review_sha256"],
                "decision": "APPROVED" if accepted else "REJECTED", "operator_signature": operator.strip(),
                "signature_kind": "local_operator_attestation_with_sha256_integrity",
                "reviewed_scene_hashes": sorted(set(reviewed_scenes)), "reason": reason.strip(),
                "signed_at": datetime.now(timezone.utc).isoformat(), "measurement_status": "NOT_RUN"}
    decision["contract_sha256"] = digest(decision)
    output_root.mkdir(parents=True, exist_ok=True)
    name = "EVAL396_MT_geometry_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    stage = output_root / (name + ".partial")
    stage.mkdir()
    for filename, payload in (("preflight.json", report), ("geometry_policy.json", decision)):
        (stage / filename).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    recheck_review(report, allow_geometry_failure=not accepted)
    (stage / "status.json").write_text(json.dumps({"status": "GEOMETRY_APPROVED" if accepted else "FAIL",
        "kind": "operator_geometry_review", "measurement_status": "NOT_RUN"}), encoding="utf-8")
    destination = output_root / name
    stage.rename(destination)
    return destination, decision


def require_current_approval(report, decision):
    """Future MT runner must call this gate after its fresh preflight."""
    recheck_review(report)
    require(decision.get("schema") == APPROVAL_SCHEMA and decision.get("decision") == "APPROVED"
            and bool(str(decision.get("operator_signature") or "").strip()), "EXIF_OPERATOR_APPROVAL_REQUIRED")
    require(decision.get("contract_sha256") == digest({k: v for k, v in decision.items() if k != "contract_sha256"}),
            "OPERATOR_CONTRACT_CHANGED")
    require(decision.get("policy") == POLICY and decision.get("review_sha256") == report["review_sha256"]
            and decision.get("selection_sha") == SELECTION_SHA and decision.get("gt_freeze_sha") == FREEZE_SHA
            and set(decision.get("reviewed_scene_hashes", [])) == set(report["review_scene_hashes"]), "STALE_GEOMETRY_APPROVAL")
    return True


def load_operator_decision(report, output_root):
    for path in sorted(Path(output_root).glob("EVAL396_MT_geometry_*/geometry_policy.json"), reverse=True):
        if path.parent.name.endswith(".partial"):
            continue
        decision = json.loads(path.read_text(encoding="utf-8"))
        if decision.get("review_sha256") != report["review_sha256"]:
            continue
        require(decision.get("contract_sha256") == digest({k: v for k, v in decision.items() if k != "contract_sha256"}),
                "SAVED_OPERATOR_CONTRACT_CHANGED")
        if decision.get("decision") == "APPROVED":
            require_current_approval(report, decision)
        else:
            require(decision.get("decision") == "REJECTED", "UNKNOWN_OPERATOR_DECISION")
        return path.parent, decision
    return None
