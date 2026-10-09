from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

from auto_annotation_tool.ranking import eval396 as adapter
from auto_annotation_tool.ranking.mz_whole_plate_evaluation import evaluate_plate_records, aggregate_plate_metrics
from auto_annotation_tool.gui import z4_eval396 as view


def write_json(path, payload):
    data = adapter.canonical(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def mz_fixture(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    plates = [{"plate_id": str(i), "decision": "approved", "domain": domain,
               "source_file_sha256": str(i) * 64, "crop_sha256": "c" * 64, "ground_truth_text": "AB"}
              for i, domain in enumerate(("DAY", "NIGHT"))]
    models = [{"label": label, "run_id": label, "checkpoint_sha256": str(i + 1) * 64}
              for i, label in enumerate(adapter.VARIANTS)]
    summaries, manifest_shas = {}, {}
    for model in models:
        label = model["label"]
        rows = []
        for plate in plates:
            value = evaluate_plate_records("AB", [{"bbox": [1, 1, 4, 8], "character": "A", "confidence": .9}])
            rows.append({**value, **{k: plate[k] for k in ("plate_id", "domain", "crop_sha256", "source_file_sha256")},
                         "checkpoint_label": label})
        rows_data = b"".join(adapter.canonical(row) + b"\n" for row in rows)
        folder = root / label
        folder.mkdir(parents=True)
        (folder / "rows.jsonl").write_bytes(rows_data)
        metrics = {domain: aggregate_plate_metrics([r for r in rows if domain == "ALL" or r["domain"] == domain])
                   for domain in adapter.DOMAINS}
        summary = {"schema": "emzdn01.eval396.mz_plate_recognition_run.v1", "model": label,
                   "run_id": label, "checkpoint_sha256": model["checkpoint_sha256"],
                   "selection_fingerprint_sha256": adapter.SELECTION_SHA,
                   "gt_freeze_fingerprint_sha256": adapter.FREEZE_SHA, "inference": adapter.INFERENCE,
                   "source": "approved_GT_crops_only_no_visual_unreadables", "per_domain": metrics}
        summary_sha = write_json(folder / "summary.json", summary)
        manifest_shas[label] = write_json(folder / "run_manifest.json", {"schema": summary["schema"], "variant": label,
            "selection_fingerprint_sha256": adapter.SELECTION_SHA, "checkpoint_sha256": model["checkpoint_sha256"],
            "files": {"summary.json": summary_sha, "rows.jsonl": hashlib.sha256(rows_data).hexdigest()}})
        summaries[label] = metrics
    sha = write_json(root / "comparison.json", {"schema": "emzdn01.eval396.mz_plate_comparison.v1",
        "selection_fingerprint_sha256": adapter.SELECTION_SHA, "inference": adapter.INFERENCE,
        "model_summaries": summaries})
    # Fixture has its own trusted comparison; production anchors are never rewritten.
    monkeypatch.setattr(adapter, "COMPARISON_SHA", sha)
    monkeypatch.setattr(adapter, "RUN_MANIFEST_SHAS", manifest_shas)
    return root, {"included_plates.json": plates, "model_lineage.json": models}


def test_result_import_recomputes_metrics_and_changes_no_files(mz_fixture):
    root, selection = mz_fixture
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    reader = adapter.EvidenceReader()
    results = adapter._read_mz_results(reader, root, selection)
    reader.finish()
    assert results["MZ-DAY"]["per_domain"]["ALL"]["cer"] == .5
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("filename", ["rows.jsonl", "summary.json", "comparison.json", "run_manifest.json"])
def test_one_changed_byte_fails(mz_fixture, filename):
    root, selection = mz_fixture
    path = root / filename if filename == "comparison.json" else root / "MZ-s" / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(adapter.EvaluationImportError, match="SHA_MISMATCH"):
        adapter._read_mz_results(adapter.EvidenceReader(), root, selection)


def test_valid_hashes_cannot_hide_changed_population_or_gt(mz_fixture):
    root, selection = mz_fixture
    path = root / "MZ-s/rows.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["ground_truth"] = "AC"
    payload = b"".join(adapter.canonical(row) + b"\n" for row in rows)
    path.write_bytes(payload)
    manifest_path = path.parent / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["rows.jsonl"] = hashlib.sha256(payload).hexdigest()
    adapter.RUN_MANIFEST_SHAS["MZ-s"] = write_json(manifest_path, manifest)
    with pytest.raises(adapter.EvaluationImportError, match="GT_MISMATCH"):
        adapter._read_mz_results(adapter.EvidenceReader(), root, selection)


def test_bad_model_or_protocol_is_rejected(mz_fixture):
    root, selection = mz_fixture
    changed = deepcopy(selection)
    changed["model_lineage.json"][0]["checkpoint_sha256"] = "f" * 64
    with pytest.raises(adapter.EvaluationImportError, match="MANIFEST"):
        adapter._read_mz_results(adapter.EvidenceReader(), root, changed)


def test_recheck_detects_change_during_read(tmp_path):
    path = tmp_path / "x"
    path.write_bytes(b"original")
    reader = adapter.EvidenceReader()
    reader.read(path)
    path.write_bytes(b"changed")
    with pytest.raises(adapter.EvaluationImportError, match="SHA_MISMATCH"):
        reader.finish()


def test_real_tk_error_clears_table_and_disables_export(tmp_path, monkeypatch):
    root = tk.Tk()
    tab = SimpleNamespace(frame=ttk.Frame(root), rank_data_dir=tk.StringVar(value=str(tmp_path)))
    def broken(*args, **kwargs):
        raise adapter.EvaluationImportError("fixture bad hash")
    monkeypatch.setattr(view, "load_eval396", broken)
    try:
        dialog = view.open_results(tab)
        deadline = time.monotonic() + 5
        while "FAIL" not in dialog.status_variable.get() and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        assert "FAIL" in dialog.status_variable.get()
        assert not dialog.result_table.get_children()
        assert dialog.verified_report is None
    finally:
        root.destroy()


def test_existing_z4_controls_dispatch_to_reader_before_inference(tmp_path, monkeypatch):
    from auto_annotation_tool.gui import z4_analysis_ranking as ranking
    (tmp_path / "selection_manifest.json").write_text("{}")
    host = SimpleNamespace(rank_data_dir=SimpleNamespace(get=lambda: str(tmp_path)))
    calls = []
    monkeypatch.setattr(view, "open_results", lambda tab, **kwargs: calls.append(kwargs))
    for function in (ranking._run_ranking_v2, ranking._open_ranking_results_modal,
                     ranking._open_ranking_report_viewer, ranking._open_ranking_participants_modal,
                     ranking._export_ranking_analysis_report):
        function(host)
    assert len(calls) == 5 and calls[-1] == {"export_after_load": True}


def test_local_evidence_import_and_export(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    selection = adapter.default_selection(repo)
    if not selection.is_dir():
        pytest.skip("Local frozen experiment not distributed in the repository")
    report = adapter.load_eval396(selection, repo_root=repo)
    metrics = report["summaries"]["MZ-DAY"]["per_domain"]["ALL"]
    assert metrics["exact_matches"] == 299 and metrics["plates"] == 449
    assert f"{100 * metrics['exact_match_rate']:.2f}" == "66.59"
    assert f"{metrics['cer']:.4f}" == "0.0927"
    destination = view.export_report(report, tmp_path / "reports")
    assert json.loads((destination / "status.json").read_text())["status"] == "PASS"
    assert "66.59" in (destination / "report.md").read_text(encoding="utf-8")
    assert "0.0927" in (destination / "cer.svg").read_text(encoding="utf-8")
    assert "Mniej = lepiej" in (destination / "cer.svg").read_text(encoding="utf-8")
    assert len((destination / "results.csv").read_text(encoding="utf-8-sig").splitlines()) == 10
