import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.sample_selection import prepare_sample_selection
from auto_annotation_tool.registry.experiment_gt_workspace import prepare_gt_workspace, publish_working_gt
from auto_annotation_tool.registry.track_service import EvaluationTrackError


class RawSampleSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.f = PZ3Fixture(self.temp.name)
        self.service, self.track = self.f.service, self.f.track
        self.images = [self.f.image(f"SAMPLE_{i:03d}.png", seed=500 + i) for i in range(20)]
        report = self.f.audit.audit_paths(self.track, self.images)
        self.service.add_members_batch(self.track, self.images)
        self.f.audit.record_ingested_report(self.track, report, self.images)
        self.context = prepare_sample_selection(self.service, self.track)
        self.rows = self.service.list_members(self.track)
        self.keep = {row["sha256"] for row in self.rows[:6]}
        self.root = self.service._track_root(self.service.get_track(self.track))

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, **kwargs):
        params = dict(keep_sha256=self.keep,
                      expected_member_sha256=self.context["sample_member_sha256"],
                      expected_audit_id=self.context["sample_audit_id"])
        params.update(kwargs)
        return self.service.commit_sample_selection(self.track, **params)

    def assert_no_gt(self):
        track = self.service.get_track(self.track)
        self.assertIsNone(track["gt_relative_path"])
        self.assertIsNone(track["gt_sha256"])
        self.assertEqual(list(self.service.workspace.rglob("*.xml")), [])

    def assert_unchanged(self):
        self.assertEqual({row["sha256"] for row in self.service.list_members(self.track)},
                         {row["sha256"] for row in self.rows})
        self.assertEqual(len(list((self.root / "images").iterdir())), 20)
        self.assert_no_gt()
        self.assertFalse((self.root / "sample_selection.json").exists())

    def reaudit(self):
        paths = [self.root / row["track_relative_path"] for row in self.service.list_members(self.track)]
        report = self.f.audit.audit_paths(self.track, paths)
        self.f.audit.record_ingested_report(self.track, report, paths)

    def make_final_gt(self):
        context = prepare_gt_workspace(self.service, self.track, mode="manual")
        xml = Path(context["annotation_path"])
        tree = ET.parse(xml)
        for node in tree.getroot().findall("image"):
            ET.SubElement(node, "polygon", label="plate", points="10,10;80,10;80,40;10,40")
        tree.write(xml, encoding="utf-8", xml_declaration=True)
        self.f.mark_gt_review_complete(xml)
        publish_working_gt(self.service, self.track, xml)
        return xml

    def test_selection_opens_without_gt_or_decoding_candidate_images(self):
        with patch("auto_annotation_tool.registry.experiment_gt_workspace.prepare_gt_workspace",
                   side_effect=AssertionError("No GT during selection")) as gt, \
             patch("PIL.Image.open", side_effect=AssertionError("No eager image decoding")) as images:
            context = prepare_sample_selection(self.service, self.track)
        gt.assert_not_called()
        images.assert_not_called()
        self.assertEqual(context["purpose"], "sample_selection")
        self.assertEqual(context["candidate_count"], 20)
        self.assertEqual(len(context["sample_image_paths"]), 20)
        self.assertNotIn("annotation_path", context)
        self.assert_no_gt()

    def test_exact_raw_subset_keeps_current_audit_and_goes_to_gt(self):
        originals = {path: path.read_bytes() for path in self.images}
        result = self.commit(criteria_note="Different light and viewing angles")
        self.assertEqual(result["selected_count"], 6)
        final = self.service.list_members(self.track)
        self.assertEqual({row["sha256"] for row in final}, self.keep)
        self.assertEqual({path.name for path in (self.root / "images").iterdir()},
                         {row["original_name"] for row in final})
        self.assert_no_gt()
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "CURRENT")
        self.assertTrue(self.service.get_preparation_state(self.track).can_prepare_gt)
        gt = self.make_final_gt()
        self.assertEqual({node.get("name") for node in ET.parse(gt).getroot().findall("image")},
                         {row["original_name"] for row in final})
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
        xml = Path(self.temp.name) / "existing.xml"
        xml.write_text("<annotations/>", encoding="utf-8")
        self.commit(keep_sha256={row["sha256"] for row in self.rows})
        self.reaudit()
        self.context = prepare_sample_selection(self.service, self.track)
        self.service.set_ground_truth(self.track, xml)
        with self.assertRaises((EvaluationTrackError, ValueError)):
            self.commit()
        self.assertEqual(len(self.service.list_members(self.track)), 20)

    def test_stale_audit_blocks_selection(self):
        self.f.audit.invalidate_track_audit(self.track, reason="test")
        with self.assertRaises(EvaluationTrackError):
            self.commit()
        with self.assertRaises(EvaluationTrackError):
            prepare_sample_selection(self.service, self.track)
        self.assert_unchanged()

    def test_pool_identity_is_checked_again_inside_commit(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE evaluation_track_members SET original_name='changed.png' "
                       "WHERE track_id=? AND member_index=?", (self.track, self.rows[0]["member_index"]))
        with self.assertRaisesRegex(ValueError, "Pula"):
            self.commit()
        self.assert_unchanged()

    def test_choosing_every_image_keeps_audit_current_and_does_not_create_gt(self):
        result = self.commit(keep_sha256={row["sha256"] for row in self.rows})
        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(result["selected_count"], 20)
        self.assert_no_gt()
        self.assertTrue((self.root / "sample_selection.json").exists())
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "CURRENT")

    def test_manifest_write_failure_rolls_back_db_sources_and_audit(self):
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

    def test_thirty_candidates_ten_members_then_standard_gt(self):
        extra = [self.f.image(f"EXTRA_{i:03d}.png", seed=900 + i) for i in range(10)]
        self.service.add_members_batch(self.track, extra)
        self.reaudit()
        self.context = prepare_sample_selection(self.service, self.track)
        rows = self.service.list_members(self.track)
        keep = {row["sha256"] for row in rows[:10]}
        self.commit(keep_sha256=keep)
        self.assert_no_gt()
        self.assertEqual(len(self.service.list_members(self.track)), 10)
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "CURRENT")
        xml = self.make_final_gt()
        self.assertEqual(len(ET.parse(xml).getroot().findall("image")), 10)
        self.service.verify(self.track, manual_gt_complete=True)
        self.assertTrue(self.service.seal(self.track).ok)


if __name__ == "__main__":
    unittest.main()
