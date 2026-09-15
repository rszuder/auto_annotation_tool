import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.sample_selection import prepare_reviewed_sample
from auto_annotation_tool.registry.experiment_workspace import active_z2_context_path
from auto_annotation_tool.registry.track_service import EvaluationTrackError


class ReviewedSampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.f = PZ3Fixture(self.temp.name)
        self.service, self.track = self.f.service, self.f.track
        self.images = [self.f.image(f"SAMPLE_{i:03d}.png", seed=500 + i) for i in range(20)]
        report = self.f.audit.audit_paths(self.track, self.images)
        self.service.add_members_batch(self.track, self.images)
        self.f.audit.record_ingested_report(self.track, report, self.images)
        self.context = prepare_reviewed_sample(self.service, self.track, mode="manual")
        self.xml = Path(self.context["annotation_path"])
        tree = ET.parse(self.xml)
        for node in tree.getroot().findall("image"):
            ET.SubElement(node, "polygon", label="plate", points="10,10;80,10;80,40;10,40")
        tree.write(self.xml, encoding="utf-8", xml_declaration=True)
        self.rows = self.service.list_members(self.track)
        self.keep = {row["sha256"] for row in self.rows[:7]}
        self.root = self.service._track_root(self.service.get_track(self.track))

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, **kwargs):
        params = dict(
            keep_sha256=self.keep,
            expected_member_sha256=self.context["sample_member_sha256"],
            expected_audit_id=self.context["sample_audit_id"], working_xml=self.xml,
        )
        params.update(kwargs)
        return self.service.commit_reviewed_sample(self.track, **params)

    def assert_unchanged(self):
        self.assertEqual({row["sha256"] for row in self.service.list_members(self.track)},
                         {row["sha256"] for row in self.rows})
        self.assertEqual(len(list((self.root / "images").iterdir())), 20)
        self.assertEqual(len(ET.parse(self.xml).getroot().findall("image")), 20)
        self.assertFalse(self.service.get_track(self.track)["gt_relative_path"])
        self.assertFalse((self.root / "sample_selection.json").exists())

    def test_exact_sample_gt_and_originals_then_reaudit_verify_seal(self):
        originals = {path: path.read_bytes() for path in self.images}
        result = self.commit(criteria_note="Different light and viewing angles")
        self.assertEqual(result["selected_count"], 7)
        final = self.service.list_members(self.track)
        self.assertEqual({row["sha256"] for row in final}, self.keep)
        self.assertEqual({path.name for path in (self.root / "images").iterdir()},
                         {row["original_name"] for row in final})
        track = self.service.get_track(self.track)
        gt = self.service.workspace / track["gt_relative_path"]
        self.assertEqual({node.get("name") for node in ET.parse(gt).getroot().findall("image")},
                         {row["original_name"] for row in final})
        self.assertEqual(gt.read_bytes(), self.xml.read_bytes())
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(active_z2_context_path(self.service.workspace).exists())
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "STALE")
        with self.assertRaises(EvaluationTrackError):
            self.service.verify(self.track, manual_gt_complete=True)
        paths = [self.root / row["track_relative_path"] for row in final]
        report = self.f.audit.audit_paths(self.track, paths)
        self.f.audit.record_ingested_report(self.track, report, paths)
        self.service.verify(self.track, manual_gt_complete=True)
        sealed = self.service.seal(self.track)
        self.assertTrue(sealed.ok, sealed.issues)
        self.assertTrue(self.service.verify_integrity(self.track).ok)
        manifest = json.loads((self.root / "track_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("sample_selection.json", manifest["experiment_contract"]["artifacts"])
        self.assertEqual(manifest["sample_selection"]["sha256"],
                         self.service._sha256(self.root / "sample_selection.json"))
        (self.root / "sample_selection.json").write_text("{}", encoding="utf-8")
        self.assertFalse(self.service.verify_integrity(self.track).ok)

    def test_rejects_empty_and_foreign_selection(self):
        for keep in (set(), {"foreign"}):
            with self.subTest(keep=keep), self.assertRaises(EvaluationTrackError):
                self.commit(keep_sha256=keep)
            self.assert_unchanged()

    def test_non_draft_and_registered_gt_are_blocked(self):
        self.f.repo.update_evaluation_track(self.track, status="VERIFIED")
        with self.assertRaises((EvaluationTrackError, ValueError)):
            self.commit()
        self.f.repo.update_evaluation_track(self.track, status="DRAFT")
        self.service.set_ground_truth(self.track, self.xml)
        with self.assertRaises((EvaluationTrackError, ValueError)):
            self.commit()
        self.assertEqual(len(self.service.list_members(self.track)), 20)

    def test_stale_audit_blocks_selection(self):
        self.f.audit.invalidate_track_audit(self.track, reason="test")
        with self.assertRaises(EvaluationTrackError):
            self.commit()
        self.assert_unchanged()

    def test_pool_identity_is_checked_again_inside_commit(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE evaluation_track_members SET original_name='changed.png' "
                       "WHERE track_id=? AND member_index=?", (self.track, self.rows[0]["member_index"]))
        with self.assertRaisesRegex(ValueError, "Pula"):
            self.commit()
        self.assert_unchanged()

    def test_choosing_every_image_still_records_selection_and_requires_reaudit(self):
        result = self.commit(keep_sha256={row["sha256"] for row in self.rows})
        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(result["selected_count"], 20)
        self.assertTrue((self.root / "sample_selection.json").exists())
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "STALE")

    def test_manifest_write_failure_rolls_back_db_gt_sources_and_audit(self):
        original_replace = Path.replace
        manifest = self.root / "track_manifest.json"
        before = manifest.read_bytes()
        def fail_manifest(path, target):
            if Path(target) == manifest:
                raise OSError("disk full")
            return original_replace(path, target)
        with patch.object(Path, "replace", fail_manifest):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.commit()
        self.assert_unchanged()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "CURRENT")
        self.assertTrue(active_z2_context_path(self.service.workspace).exists())

    def test_database_commit_failure_restores_all_files(self):
        original_connect = self.f.repo.database.connect
        class FailingCommit:
            def __init__(self, db):
                self.db = db
            def __getattr__(self, name):
                return getattr(self.db, name)
            def commit(self):
                raise OSError("commit failed")
        with patch.object(self.f.repo.database, "connect",
                          side_effect=lambda: FailingCommit(original_connect())):
            with self.assertRaisesRegex(OSError, "commit failed"):
                self.commit()
        self.assert_unchanged()
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "CURRENT")



    def test_auto_metrics_cover_selected_images_and_preserve_full_snapshot(self):
        from auto_annotation_tool.registry.gt_preannotation import (
            snapshot_xml_path, metrics_path, maybe_compute_preannotation_metrics_for_track)
        snapshot = snapshot_xml_path(self.root)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        full_auto = self.xml.read_bytes()
        snapshot.write_bytes(full_auto)
        self.commit()
        self.assertEqual(snapshot.read_bytes(), full_auto)
        metrics = json.loads(metrics_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual(metrics["images"], 7)
        self.assertEqual(metrics["false_positives"], 0)
        recomputed = maybe_compute_preannotation_metrics_for_track(self.root, self.xml)
        self.assertEqual(recomputed["images"], 7)


if __name__ == "__main__":
    unittest.main()
