import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.bootstrap import registry_run_id
from auto_annotation_tool.registry.participant_background import ParticipantBackgroundReader
from auto_annotation_tool.registry.participant_pool_audit import participant_fingerprint
from auto_annotation_tool.registry.track_service import EvaluationTrackError


class ParticipantBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)
        self.output = self.f.workspace / "5_training_runs" / "plates" / "source-1"
        self.output.mkdir(parents=True)
        self.run_id = registry_run_id("source-1", project_id=None, target="plate")
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE training_runs SET run_id=?, output_relative_path=?, finished_at=? WHERE run_id='R1'",
                       (self.run_id, self.output.relative_to(self.f.workspace).as_posix(), "2026-09-12T18:47:00+02:00"))

    def model(self):
        return next(p for p in self.f.audit.list_participant_catalog("plate") if p.model_id == "M1")

    def history(self, **fields):
        path = self.output.parent / "training_history.json"
        path.write_text(json.dumps({"runs": {"source-1": {
            "id": "source-1", "output_dir": str(self.output), **fields,
        }}}), encoding="utf-8")
        return path

    def csv(self, contents=None):
        path = self.output / "train" / "results.csv"
        path.parent.mkdir(exist_ok=True)
        path.write_text(contents or (
            "epoch, metrics/mAP50(B), metrics/mAP50-95(B), metrics/mAP50(P), metrics/mAP50-95(P)\n"
            "1,0.960,0.900,0.950,0.850\n2,0.982,0.934,0.965,0.901\n"
        ), encoding="utf-8")
        return path

    def test_participant_background_contains_finished_at(self):
        self.assertEqual(self.model().training_finished_at, "2026-09-12T18:47:00+02:00")

    def test_participant_background_contains_pose_metrics(self):
        self.csv()
        item = self.model()
        self.assertEqual((item.pose_map50, item.pose_map50_95), (0.965, 0.901))
        self.assertEqual((item.box_map50, item.box_map50_95), (0.982, 0.934))

    def test_history_precedes_csv_and_generic_map_is_not_relabelled_pose(self):
        self.history(best_map50=0.99, best_map50_95=0.95,
                     metrics_history=[{"pose_map50": 0.80, "pose_map50_95": 0.70}])
        self.csv()
        item = self.model()
        self.assertEqual((item.pose_map50, item.pose_map50_95), (0.80, 0.70))
        self.assertEqual(item.best_map50_95, 0.95)
        self.assertEqual(item.box_map50_95, 0.934)

    def test_generic_history_only_does_not_claim_pose_or_bbox(self):
        self.history(best_map50=0.91, best_map50_95=0.80)
        item = self.model()
        self.assertEqual(item.best_map50_95, 0.80)
        self.assertIsNone(item.pose_map50_95)
        self.assertIsNone(item.box_map50_95)

    def test_box_only_csv_never_populates_pose(self):
        self.csv("metrics/mAP50(B),metrics/mAP50-95(B)\n0.98,0.91\n")
        self.assertEqual(self.model().box_map50_95, 0.91)
        self.assertIsNone(self.model().pose_map50_95)

    def test_zero_is_a_metric_invalid_and_nonfinite_values_are_missing(self):
        self.csv("metrics/mAP50(P),metrics/mAP50-95(P),metrics/mAP50(B),metrics/mAP50-95(B)\n0,nan,inf,2\n")
        item = self.model()
        self.assertEqual(item.pose_map50, 0)
        self.assertIsNone(item.pose_map50_95)
        self.assertIsNone(item.box_map50)
        self.assertIsNone(item.box_map50_95)

    def test_missing_metrics_and_date_do_not_block_complete_lineage(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE training_runs SET finished_at=NULL WHERE run_id=?", (self.run_id,))
        item = self.model()
        self.assertTrue(item.eligible)
        self.assertEqual(item.training_finished_at, "")
        self.assertIsNone(item.pose_map50_95)
        self.f.audit.save_participants(self.f.track, ["M1"])

    def test_missing_dataset_blocks_complete_or_known_but_is_visible_for_diagnostics(self):
        for status in ("complete", "known"):
            with self.subTest(status=status):
                with self.f.repo.database.transaction() as db:
                    db.execute("UPDATE training_runs SET dataset_id=NULL WHERE run_id=?", (self.run_id,))
                    db.execute("UPDATE models SET provenance_status=? WHERE model_id='M1'", (status,))
                self.assertFalse(self.model().eligible)
                self.assertNotIn("M1", {p.model_id for p in self.f.audit.list_eligible_models("plate")})
                with self.assertRaises(EvaluationTrackError):
                    self.f.audit.save_participants(self.f.track, ["M1"])

    def test_background_does_not_change_fingerprint(self):
        item = self.model()
        changed = replace(item, training_finished_at="2026-09-16", pose_map50_95=0.9,
                          best_map50=0.8, checkpoint_kind="trained_export")
        self.assertEqual(participant_fingerprint([item]), participant_fingerprint([changed]))

    def test_background_update_keeps_current_audit_and_saved_snapshot(self):
        self.csv()
        self.f.audit.save_participants(self.f.track, ["M1", "M2"])
        before = self.f.audit.load_participants(self.f.track)
        image = self.f.image("TEST_001.png", seed=987)
        report = self.f.audit.audit_paths(self.f.track, [image])
        self.f.service.add_member(self.f.track, image)
        self.f.audit.record_ingested_report(self.f.track, report, [image])
        self.history(best_map50_95=0.93, pose_map50_95=0.777)
        self.assertEqual(self.model().pose_map50_95, 0.777)
        with patch.object(ParticipantBackgroundReader, "read", side_effect=AssertionError("Audit must not read profile artifacts")):
            self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "CURRENT")
            self.f.audit.assert_track_audit_ready(self.f.track)
        self.assertEqual(self.f.audit.load_participants(self.f.track), before)
        self.assertEqual(before[0].pose_map50_95, 0.901)

    def test_cache_reuses_artifacts_and_reloads_changed_file_without_workspace_scan(self):
        path = self.history(pose_map50_95=0.81)
        self.csv()
        with patch.object(Path, "rglob", side_effect=AssertionError("No workspace scan")), \
             patch.object(Path, "glob", side_effect=AssertionError("No workspace scan")):
            self.assertEqual(self.model().pose_map50_95, 0.81)
            with patch.object(Path, "read_text", side_effect=AssertionError("Cached history")), \
                 patch.object(Path, "open", side_effect=AssertionError("Cached CSV")):
                self.assertEqual(self.model().pose_map50_95, 0.81)
            self.history(pose_map50_95=0.8222)
            self.assertEqual(self.model().pose_map50_95, 0.8222)

    def test_shared_run_background_is_prepared_once_per_catalog(self):
        self.csv()
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE models SET run_id=? WHERE model_id='M2'", (self.run_id,))
        reader = ParticipantBackgroundReader(self.f.workspace)
        self.f.audit._background_reader = reader
        with patch.object(reader, "read", wraps=reader.read) as read:
            models = self.f.audit.list_participant_catalog("plate")
        self.assertEqual(read.call_count, 2)  # shared M1/M2 plus R3
        pair = [p for p in models if p.model_id in {"M1", "M2"}]
        self.assertEqual({p.pose_map50_95 for p in pair}, {0.901})

    def test_wrong_history_output_is_not_adopted(self):
        self.history(output_dir=str(self.f.workspace / "different"), pose_map50_95=0.999)
        self.assertIsNone(self.model().pose_map50_95)

    def test_unreadable_optional_artifact_does_not_block_model(self):
        path = self.output.parent / "training_history.json"
        path.write_text("{ invalid JSON", encoding="utf-8")
        item = self.model()
        self.assertTrue(item.eligible)
        self.assertIsNone(item.pose_map50_95)


if __name__ == "__main__":
    unittest.main()
