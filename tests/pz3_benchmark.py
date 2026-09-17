"""Run a controlled PZ3 benchmark on 1000 real local photographs.

No source files or production registry records are changed. Participant metadata
belongs to the temporary test fixture; this is a performance test, not a model evaluation.
"""
import argparse
from collections import defaultdict
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pz3_ingest_integration import PZ3IngestIntegrationTests, GUI
from auto_annotation_tool.gui.pz3_source_ingest_ui import PZ3SourceSelection
from auto_annotation_tool.gui.source_filename_review_dialog import SourceReviewSelectionResult
from pz3_gui_capture import capture_window


def run(source_dir, output):
    case = PZ3IngestIntegrationTests("test_mixed_folder_adds_candidates_then_explicit_audit_filters_pool")
    case.setUp()
    try:
        paths = sorted(p.resolve() for p in source_dir.iterdir()
                       if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"})[:1000]
        if len(paths) != 1000:
            raise RuntimeError(f"Need 1000 images, found {len(paths)}")
        sha_by_path = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        candidate_shas = set(sha_by_path.values())
        references = paths[:100]
        seen_shas = {sha_by_path[p] for p in references}
        for path in Path("Workspace/1_raw_images").rglob("*"):
            if len(references) >= 1000:
                break
            if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
                continue
            path = path.resolve()
            if path in sha_by_path:
                continue
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if sha in candidate_shas or sha in seen_shas:
                continue
            seen_shas.add(sha)
            sha_by_path[path] = sha
            references.append(path)
        with case.f.repo.database.transaction() as db:
            db.execute("DELETE FROM dataset_members WHERE dataset_id IN ('D1', 'D2')")
            for index, path in enumerate(references):
                source, artifact = f"BENCH-S-{index}", f"BENCH-A-{index}"
                db.execute("INSERT INTO source_images(source_image_id) VALUES (?)", (source,))
                db.execute("INSERT INTO image_artifacts(artifact_id, source_image_id, external_path, sha256) VALUES (?, ?, ?, ?)",
                           (artifact, source, str(path), sha_by_path[path]))
                db.execute("INSERT INTO dataset_members(dataset_id, artifact_id, source_image_id, split, file_sha256) VALUES (?, ?, ?, ?, ?)",
                           (f"D{1 + index % 2}", artifact, source, "train" if index % 3 else "val", sha_by_path[path]))

        case.root.geometry("1200x850+30+30")
        case.root.deiconify()
        case.root.update()
        timings = defaultdict(float)
        calls = defaultdict(int)
        reports = []
        pass_results = []
        beats = []
        timer = None

        def heartbeat():
            nonlocal timer
            beats.append(time.perf_counter())
            timer = case.root.after(20, heartbeat)

        def measured(label, original):
            def call(*args, **kwargs):
                started = time.perf_counter()
                try:
                    result = original(*args, **kwargs)
                    if label == "audit_total":
                        reports.append(result)
                    return result
                finally:
                    timings[label] += time.perf_counter() - started
                    calls[label] += 1
            return call

        with ExitStack() as stack:
            audit = case.panel.participant_audit
            service = case.panel.service
            repository = case.panel.repository
            for obj, method, label in [
                (audit, "_ensure_sha", "sha_seconds"),
                (audit, "_ensure_phash", "phash_seconds"),
                (audit, "audit_paths", "audit_total"),
                (repository, "list_participant_training_members", "lineage_sql_seconds"),
                (repository, "find_source_ids_by_sha256_batch", "dedup_sql_seconds"),
                (repository, "resolve_track_member_sources_batch", "resolve_sql_seconds"),
                (repository, "add_evaluation_track_members_batch", "insert_sql_seconds"),
                (service, "add_members_batch", "batch_ingest_seconds"),
                (service, "_write_manifest", "manifest_seconds"),
            ]:
                stack.enter_context(patch.object(obj, method, measured(label, getattr(obj, method))))
            stack.enter_context(patch(GUI + "choose_pz3_source_candidates",
                return_value=PZ3SourceSelection("files", tuple(paths))))
            stack.enter_context(patch(GUI + "review_source_image_paths",
                return_value=SourceReviewSelectionResult(True, accepted_paths=tuple(paths))))
            for attempt in (1, 2):
                timings.clear()
                calls.clear()
                reports.clear()
                beats.clear()
                case.messages.reset_mock()
                case.errors.reset_mock()
                before = len(service.list_members(case.f.track))
                heartbeat()
                start = time.perf_counter()
                case.panel.add_images()
                case.panel.audit_current_pool()
                case.root.update()
                elapsed = time.perf_counter() - start
                case.root.after_cancel(timer)
                case.errors.assert_not_called()
                case.messages.showerror.assert_not_called()
                members = service.list_members(case.f.track)
                displayed = len(case.panel.member_tree.get_children())
                assert displayed == len(members)
                report = reports[-1].to_dict() if reports else {}
                result = {
                    "attempt": attempt, "elapsed_seconds": elapsed,
                    "added": len(members) - before, "displayed_rows": displayed,
                    "timings": dict(timings), "calls": dict(calls),
                    "cache": {key: value for key, value in report.items() if key.startswith("cache_")},
                    "verdicts": {key: report.get(key) for key in
                                 ("clean_count", "dependent_count", "suspect_count", "unknown_count")},
                    "tk_heartbeat_count": len(beats),
                    "max_tk_heartbeat_gap_seconds": max(
                        (b-a for a,b in zip(beats, beats[1:])), default=0),
                }
                pass_results.append(result)
                print(json.dumps(result, ensure_ascii=True), flush=True)
                if attempt == 1:
                    case.root.lift()
                    case.root.update()
                    capture_window(case.root, output.with_suffix(".png"))
            assert pass_results[0]["added"] > 0
            assert pass_results[1]["added"] == 0
            audit.assert_track_audit_ready(case.f.track)

        output.write_text(json.dumps({
            "scenario": "Controlled temporary registry; real photographs; suspects skipped",
            "source_dir": str(source_dir.resolve()), "input_images": len(paths),
            "total_input_bytes": sum(path.stat().st_size for path in paths),
            "participants": 2, "reference_images": len(references),
            "passes": pass_results,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print("REPORT:", output, flush=True)
    finally:
        case.doCleanups()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path("Workspace/1_raw_images/sample_1000"))
    parser.add_argument("--output", type=Path, default=Path("output/pz3_benchmark_report.json"))
    args = parser.parse_args()
    run(args.source_dir, args.output)

