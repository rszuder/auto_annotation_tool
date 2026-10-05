#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ultralytics import YOLO

from auto_annotation_tool.ranking.mz_whole_plate_evaluation import evaluate_mz_test_split

EXPECTED_CONTRACT_SHA256 = "f4e5ecec141d728301587f49172f3b3c51839d3c71b3c557cb11617769ccb7d7"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen whole-plate evaluation for E-MZ-NS-01.")
    parser.add_argument("--contract", default="output/E-MZ-NS-01_whole_plate_inference_contract.json")
    parser.add_argument("--output-dir", default="output/E-MZ-NS-01_whole_plate_results")
    args = parser.parse_args()

    repo_root = Path.cwd()
    contract_path = (repo_root / args.contract).resolve()
    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not contract_path.is_file():
        raise FileNotFoundError(f"Contract not found: {contract_path}")

    contract_sha = sha256_file(contract_path)
    if contract_sha != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError(f"Frozen contract SHA mismatch: expected {EXPECTED_CONTRACT_SHA256}, actual {contract_sha}")

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema") != "alpr.mz_whole_plate_inference_contract.v1":
        raise RuntimeError(f"Unexpected contract schema: {contract.get('schema')}")
    if contract.get("experiment_id") != "E-MZ-NS-01":
        raise RuntimeError(f"Unexpected experiment_id: {contract.get('experiment_id')}")

    inference = dict(contract["inference"])
    expected_inference = {
        "imgsz": 320,
        "confidence": 0.25,
        "iou": 0.45,
        "max_det": 300,
        "device": 0,
        "end2end": True,
        "augment": False,
        "half": False,
    }
    if inference != expected_inference:
        raise RuntimeError(f"Frozen inference settings changed: expected {expected_inference}, actual {inference}")

    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    expected_head = str(contract["code"]["git_head"]).strip()
    if current_head != expected_head:
        raise RuntimeError(f"Git HEAD differs from frozen contract: expected {expected_head}, actual {current_head}")

    evaluator_path = repo_root / "auto_annotation_tool" / "ranking" / "mz_whole_plate_evaluation.py"
    evaluator_sha = sha256_file(evaluator_path)
    expected_evaluator_sha = str(contract["code"]["evaluator_sha256"]).strip()
    if evaluator_sha != expected_evaluator_sha:
        raise RuntimeError(f"Evaluator SHA mismatch: expected {expected_evaluator_sha}, actual {evaluator_sha}")

    dataset_dir = Path(contract["dataset"]["path"])
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset not found: {dataset_dir}")

    assignment = json.loads((dataset_dir / "split_assignment_manifest.json").read_text(encoding="utf-8"))
    actual_assignment_sha = str(assignment.get("assignment_sha256") or "")
    expected_assignment_sha = str(contract["dataset"]["assignment_sha256"])
    if actual_assignment_sha != expected_assignment_sha:
        raise RuntimeError(f"Assignment SHA mismatch: expected {expected_assignment_sha}, actual {actual_assignment_sha}")

    summaries = {}
    run_order = ("MZ-n", "MZ-s")

    print("=== E-MZ-NS-01 WHOLE-PLATE EVALUATION ===")
    print(f"Contract SHA256:  {contract_sha}")
    print(f"Git HEAD:         {current_head}")
    print(f"Evaluator SHA256: {evaluator_sha}")
    print(f"Assignment SHA:   {actual_assignment_sha}")
    print(f"Inference:        {json.dumps(inference, ensure_ascii=False)}")
    print()

    for variant in run_order:
        model_info = dict(contract["models"][variant])
        checkpoint = Path(model_info["checkpoint"])
        if not checkpoint.is_file():
            raise FileNotFoundError(f"{variant} checkpoint not found: {checkpoint}")

        actual_model_sha = sha256_file(checkpoint)
        expected_model_sha = str(model_info["checkpoint_sha256"])
        if actual_model_sha != expected_model_sha:
            raise RuntimeError(f"{variant} checkpoint SHA mismatch: expected {expected_model_sha}, actual {actual_model_sha}")

        print(f"[{variant}] loading {checkpoint}")
        model = YOLO(str(checkpoint))
        summary, rows = evaluate_mz_test_split(model, dataset_dir, inference)

        expected_test_images = int(contract["dataset"]["test_images"])
        if int(summary.get("plates", 0) or 0) != expected_test_images:
            raise RuntimeError(f"{variant}: expected {expected_test_images} test plates, got {summary.get('plates')}")

        result = {
            "schema": "alpr.mz_whole_plate_result.v1",
            "experiment_id": contract["experiment_id"],
            "variant": variant,
            "run_id": model_info["run_id"],
            "contract_sha256": contract_sha,
            "checkpoint_sha256": actual_model_sha,
            "evaluator_sha256": evaluator_sha,
            "git_head": current_head,
            "dataset_display_id": contract["dataset"]["display_id"],
            "dataset_provenance_id": contract["dataset"]["provenance_id"],
            "assignment_sha256": actual_assignment_sha,
            "split": "test",
            "inference": inference,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "metrics": summary,
        }
        summaries[variant] = result

        summary_path = output_dir / f"{variant}_summary.json"
        rows_path = output_dir / f"{variant}_rows.jsonl"
        write_json(summary_path, result)
        with rows_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        print(
            f"[{variant}] plates={summary['plates']} exact={summary['exact_matches']} "
            f"exact_match_rate={summary['exact_match_rate']:.6f} CER={summary['cer']:.6f} "
            f"no_read={summary['no_read']} edit_distance={summary['edit_distance']}"
        )
        print(f"[{variant}] summary: {summary_path}")
        print(f"[{variant}] rows:    {rows_path}")
        print()

    comparison = {
        "schema": "alpr.mz_whole_plate_comparison.v1",
        "experiment_id": contract["experiment_id"],
        "contract_sha256": contract_sha,
        "split": "test",
        "variants": {variant: summaries[variant]["metrics"] for variant in run_order},
    }
    comparison_path = output_dir / "comparison.json"
    write_json(comparison_path, comparison)

    print("=== COMPARISON ===")
    for variant in run_order:
        m = summaries[variant]["metrics"]
        print(
            f"{variant}: Exact Match={m['exact_match_rate']:.6f} "
            f"({m['exact_matches']}/{m['plates']}), CER={m['cer']:.6f}, "
            f"no_read={m['no_read']}, correct={m['correct_characters']}, "
            f"incorrect={m['incorrect_characters']}, missing={m['missing_characters']}, "
            f"extra={m['extra_characters']}"
        )

    print(f"\nComparison JSON: {comparison_path}")
    print(f"Comparison SHA256: {sha256_file(comparison_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
