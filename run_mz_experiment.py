"""Check a frozen MZ comparison protocol; --train is an explicit later step."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from auto_annotation_tool.dataset_split_assignment import canonical_sha256, validate_group_assignment
from auto_annotation_tool.training.model_provenance import build_training_dataset_snapshot, training_dataset_snapshots_match
from auto_annotation_tool.training.experiment_protocol import validate_requested_protocol


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def check_protocol(protocol, *, repo_root=None):
    repo = Path(repo_root or Path(__file__).absolute().parent)
    if protocol.get("schema")!="alpr.experiment.mz_ns.v1" or protocol.get("experiment_id")!="E-MZ-NS-01":
        raise ValueError("Unsupported experiment protocol")
    if protocol.get("protocol_sha256")!=canonical_sha256({k:v for k,v in protocol.items() if k!="protocol_sha256"}):
        raise ValueError("Experiment protocol fingerprint mismatch")
    validate_requested_protocol(protocol["training"])
    root = Path(protocol["dataset"]["path"])
    snapshot = build_training_dataset_snapshot(root,target="char")
    ok,message = training_dataset_snapshots_match(protocol["dataset"]["training_dataset_snapshot"],snapshot)
    if not ok or snapshot["dataset_id"]!=protocol["dataset"]["dataset_id"]:
        raise ValueError("Experiment input changed: "+message)
    assignment = json.loads((root/"split_assignment_manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((root/"metadata_manifest.json").read_text(encoding="utf-8"))
    validated = validate_group_assignment(assignment,source_manifest=manifest)
    if not validated["ok"] or assignment["assignment_sha256"]!=protocol["dataset"]["assignment_sha256"]:
        raise ValueError("Assignment changed or source group leakage was found")
    for name,expected in protocol["code"]["file_sha256"].items():
        path=repo/name
        if not path.resolve().is_relative_to(repo.resolve()) or file_sha256(path)!=expected:
            raise ValueError("Code changed after protocol preparation: "+name)
    for variant in ["MZ-n","MZ-s"]:
        model=protocol["models"][variant]
        if file_sha256(model["checkpoint"])!=model["checkpoint_sha256"]:
            raise ValueError("Base checkpoint changed: "+variant)
    import torch
    import ultralytics
    import albumentations
    if str(torch.__version__)!=protocol["environment"]["torch"] or str(ultralytics.__version__)!=protocol["environment"]["ultralytics"]:
        raise ValueError("Training library versions differ from the common protocol")
    if str(albumentations.__version__)!=protocol["environment"]["albumentations"]:
        raise ValueError("Augmentation library version differs from the common protocol")
    if not torch.cuda.is_available() and protocol["training"]["device"]!= "cpu":
        raise ValueError("The declared CUDA device is unavailable")
    if protocol["training"]["device"]!="cpu" and torch.cuda.get_device_name(int(protocol["training"]["device"]))!=protocol["environment"]["gpu"]:
        raise ValueError("The declared GPU differs from the common protocol")
    return {"ok":True,"dataset_id":snapshot["dataset_id"],"assignment_sha256":assignment["assignment_sha256"],
        "split_sha256":snapshot["split_sha256"],"counts":validated["counts"]}


def main(argv=None):
    parser=argparse.ArgumentParser(description="Read-only E-MZ-NS-01 preflight; --train requires separate approval of the prepared report.")
    parser.add_argument("--protocol",required=True)
    parser.add_argument("--variant",choices=["MZ-n","MZ-s"],default="MZ-n")
    parser.add_argument("--train",action="store_true",help="Start the selected full trial only after report acceptance")
    args=parser.parse_args(argv)
    protocol=json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    result=check_protocol(protocol)
    print(json.dumps(result),flush=True)
    if not args.train:
        print("Read-only protocol check passed. Training was not started.")
        return 0
    from auto_annotation_tool.campaign_manager import CAMPAIGN
    from auto_annotation_tool.training.training_history import TrainingHistory
    from auto_annotation_tool.training.trainer import YOLOPoseTrainer
    state=json.loads(CAMPAIGN.state_file.read_text(encoding="utf-8-sig"))
    if state.get("active_project")!=protocol["project"] or state["projects"][protocol["project"]]["current_iteration"]!=protocol["iteration"]:
        raise ValueError("Active project/iteration differs from the experiment protocol")
    CAMPAIGN.state=state
    history=TrainingHistory(Path(protocol["history_dir"]))
    trainer=YOLOPoseTrainer(history)
    trainer.on_progress=lambda percent,text:print(f"{percent:.1f}% {text}",flush=True)
    training=protocol["training"]
    base=protocol["models"][args.variant]
    run_id=trainer.start_training(name=protocol["experiment_id"]+"_"+args.variant,
        dataset_path=protocol["dataset"]["path"],base_model=base["checkpoint"],
        epochs=training["epochs"],batch_size=training["batch"],img_size=training["imgsz"],
        device=training["device"],lr0=training["lr0"],training_target="char",
        strict_experiment=True,experiment_id=protocol["experiment_id"],training_protocol=training)
    if not run_id:
        raise RuntimeError("The native trainer rejected experiment preflight")
    print("Native trial run_id: "+str(run_id),flush=True)
    while trainer.is_training:
        time.sleep(.25)
    run=history.get_run(run_id)
    if not run or run.status!="completed" or not run.training_protocol_snapshot.get("comparable"):
        raise RuntimeError("Trial failed or is not experimentally comparable; do not compare it to the other scale")
    print(json.dumps({"run_id":run_id,"status":run.status,"protocol":run.training_protocol_snapshot}),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
