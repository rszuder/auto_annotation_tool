"""Existing GT must match the pool; membership changes invalidate it atomically."""
from contextlib import contextmanager
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.experiment_gt_workspace import prepare_gt_workspace
from auto_annotation_tool.registry.final_sample_policy import _valid_existing_gt, final_sample_ready_for_gt
from auto_annotation_tool.registry.sample_selection import prepare_sample_selection
from auto_annotation_tool.registry.track_service import EvaluationTrackError


class ExistingGtMembershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)
        self.service, self.track = self.f.service, self.f.track
        self.images = [self.f.image(f"LEGACY_{i:03d}.png", seed=1700+i) for i in range(3)]
        self.service.add_members_batch(self.track, self.images)
        self.audit()
        self.track_root = self.service._track_root(self.service.get_track(self.track))
        self.gt = self.track_root / "ground_truth" / "annotations.xml"
        self.register_legacy_gt()
        self.original_gt = self.gt.read_bytes()
        self.original_track = self.service.get_track(self.track)

    def audit(self):
        root = self.service._track_root(self.service.get_track(self.track))
        paths = [root / row["track_relative_path"] for row in self.service.list_members(self.track)]
        report = self.f.audit.audit_paths(self.track, paths)
        self.f.audit.record_ingested_report(self.track, report, paths)

    def xml_bytes(self, names):
        root = ET.Element("annotations")
        for i, name in enumerate(names):
            node = ET.SubElement(root, "image", id=str(i), name=name, width="192", height="128")
            ET.SubElement(node, "polygon", label="plate", points="10,10;80,10;80,40;10,40")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def register_legacy_gt(self, names=None, *, content=None):
        if names is None:
            names = [row["original_name"] for row in self.service.list_members(self.track)]
        self.gt.parent.mkdir(parents=True, exist_ok=True)
        self.gt.write_bytes(content if content is not None else self.xml_bytes(names))
        self.f.repo.update_evaluation_track(
            self.track, gt_relative_path=self.service._workspace_relative(self.gt),
            gt_sha256=self.service._sha256(self.gt), gt_format="cvat_xml",
            object_count=len(names), verified_at="2026-09-01T00:00:00+00:00")
        self.service.ensure_audit_manifest(self.track)

    def ready(self):
        return final_sample_ready_for_gt(
            self.f.workspace, self.service.get_track(self.track),
            self.service.list_members(self.track), {"status": "CURRENT"})

    def assert_gate_closed(self):
        self.assertFalse(self.ready())
        with self.assertRaisesRegex(EvaluationTrackError, "finalną próbę"):
            prepare_gt_workspace(self.service, self.track)
        xml = Path(self.temp.name) / "import.xml"
        xml.write_bytes(self.gt.read_bytes())
        with self.assertRaisesRegex(EvaluationTrackError, "finalną próbę"):
            self.service.set_ground_truth(self.track, xml)

    def restore_old_gt_metadata(self):
        # Emulate an older application/migration that failed to invalidate GT.
        self.f.repo.update_evaluation_track(self.track, **{
            key: self.original_track[key] for key in
            ("gt_relative_path", "gt_sha256", "gt_format", "object_count", "verified_at")
        })

    def assert_gt_invalidated(self):
        track = self.service.get_track(self.track)
        for key in ("gt_format", "gt_relative_path", "gt_sha256", "verified_at"):
            self.assertIsNone(track[key], key)
        self.assertEqual(track["object_count"], 0)
        self.assertEqual(self.gt.read_bytes(), self.original_gt)
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "STALE")
        self.assertFalse(self.ready())

    def test_existing_gt_membership_exact_match_is_accepted(self):
        self.register_legacy_gt(["export/subdir/" + path.name for path in self.images])
        self.assertTrue(self.ready())
        self.assertFalse((self.track_root / "sample_selection.json").exists())

    def test_existing_gt_with_added_member_no_longer_bypasses_gate(self):
        self.service.add_member(self.track, self.f.image("ADDED_001.png", seed=1900))
        self.restore_old_gt_metadata()
        self.audit()
        self.assert_gate_closed()

    def test_existing_gt_with_removed_member_no_longer_bypasses_gate(self):
        row = self.service.list_members(self.track)[-1]
        # Simulate legacy membership change, retaining the old GT and its valid SHA.
        self.f.repo.remove_evaluation_track_members(
            self.track, [row["member_index"]], invalidate_ground_truth=False)
        self.audit()
        self.assert_gate_closed()

    def test_existing_gt_with_duplicate_image_names_is_rejected(self):
        names = [path.name for path in self.images]
        for duplicate in (names[0], "another_directory/" + names[0]):
            with self.subTest(duplicate=duplicate):
                self.register_legacy_gt(names + [duplicate])
                self.assert_gate_closed()

    def test_existing_gt_with_missing_member_is_rejected(self):
        self.register_legacy_gt([path.name for path in self.images[:-1]])
        self.assert_gate_closed()

    def test_existing_gt_with_extra_image_is_rejected(self):
        self.register_legacy_gt([path.name for path in self.images] + ["EXTRA_001.png"])
        self.assert_gate_closed()

    def test_existing_gt_with_invalid_xml_or_missing_image_name_is_rejected(self):
        unnamed = ET.Element("annotations")
        ET.SubElement(unnamed, "image", id="0")
        for content in (b"<annotations><image", b"<other/>", ET.tostring(unnamed),
                        b'<?xml version="1.0" encoding="invalid-encoding"?><annotations/>'):
            with self.subTest(content=content):
                self.register_legacy_gt(content=content)
                self.assert_gate_closed()

    def test_empty_gt_and_empty_membership_do_not_bypass_gate(self):
        self.register_legacy_gt([])
        self.assertFalse(_valid_existing_gt(
            self.f.workspace, self.service.get_track(self.track), []))

    def test_add_member_invalidates_existing_gt(self):
        self.service.add_member(self.track, self.f.image("ADDED_001.png", seed=1900))
        self.assert_gt_invalidated()
        self.assertEqual(len(self.service.list_members(self.track)), 4)
        manifest = json.loads((self.track_root / "track_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["ground_truth"], {"format": "", "relative_path": "", "sha256": ""})
        self.assertEqual(manifest["object_count"], 0)
        self.assertIsNone(manifest["verified_at"])

    def test_add_members_batch_invalidates_existing_gt(self):
        self.service.add_members_batch(self.track, [
            self.f.image("ADDED_001.png", seed=1900), self.f.image("ADDED_002.png", seed=1901)])
        self.assert_gt_invalidated()
        self.assertEqual(len(self.service.list_members(self.track)), 5)

    def test_unchanged_existing_gt_remains_editable_without_reselecting_sample(self):
        context = prepare_gt_workspace(self.service, self.track)
        self.assertTrue(context["gt_existing"])
        self.assertEqual(Path(context["annotation_path"]).read_bytes(), self.original_gt)
        self.assertTrue(self.ready())
        self.assertFalse((self.track_root / "sample_selection.json").exists())

    def test_existing_gt_addition_requires_selection_but_not_second_reaudit(self):
        self.service.add_member(
            self.track,
            self.f.image("ADDED_001.png", seed=1900),
        )
        self.assert_gt_invalidated()

        # Zmiana szerokiej puli unieważnia poprzedni audyt i nadal blokuje GT.
        self.assert_gate_closed()

        # Audytujemy już poszerzoną szeroką pulę.
        self.audit()
        self.assert_gate_closed()

        # Finalizacja próbki jest wyborem podzbioru tej samej,
        # już zaudytowanej puli, więc nie wymaga drugiego audytu.
        context = prepare_sample_selection(self.service, self.track)
        self.service.commit_sample_selection(
            self.track,
            keep_sha256=set(context["sample_member_sha256"].values()),
            expected_member_sha256=context["sample_member_sha256"],
            expected_audit_id=context["sample_audit_id"],
        )

        self.assertEqual(
            self.f.audit.get_track_audit_state(self.track)["status"],
            "CURRENT",
        )

        context = prepare_gt_workspace(self.service, self.track)
        xml = Path(context["annotation_path"])
        names = {
            node.get("name")
            for node in ET.parse(xml).getroot().findall("image")
        }
        self.assertEqual(
            names,
            {
                row["original_name"]
                for row in self.service.list_members(self.track)
            },
        )
        self.service.set_ground_truth(self.track, xml)
        self.assertTrue(self.ready())

    def test_empty_or_rejected_addition_keeps_existing_gt(self):
        before = self.service.get_track(self.track)
        self.assertEqual(self.service.add_members_batch(self.track, []), [])
        for action in (lambda: self.service.add_member(self.track, self.images[0]),
                       lambda: self.service.add_members_batch(self.track, [self.images[0]])):
            with self.assertRaises(EvaluationTrackError):
                action()
        self.assertEqual(self.service.get_track(self.track), before)
        self.assertEqual(self.gt.read_bytes(), self.original_gt)
        self.assertTrue(self.ready())

    def test_failed_commit_restores_gt_and_members_for_both_add_paths(self):
        real_transaction = self.f.repo.database.transaction
        invalidated_before_rollback = []
        @contextmanager
        def failing_transaction():
            with real_transaction() as connection:
                yield connection
                count = connection.execute(
                    "SELECT COUNT(*) FROM evaluation_track_members WHERE track_id=?", (self.track,)).fetchone()[0]
                if count > 3:
                    gt = connection.execute(
                        "SELECT gt_sha256 FROM evaluation_tracks WHERE track_id=?", (self.track,)).fetchone()[0]
                    invalidated_before_rollback.append(gt is None)
                    raise OSError("simulated commit failure")
        image = self.f.image("ADDED_001.png", seed=1900)
        before = self.service.get_track(self.track)
        for batch in (False, True):
            with self.subTest(batch=batch), patch.object(self.f.repo.database, "transaction", failing_transaction):
                with self.assertRaisesRegex(OSError, "commit failure"):
                    if batch:
                        self.service.add_members_batch(self.track, [image])
                    else:
                        self.service.add_member(self.track, image)
            self.assertEqual(self.service.get_track(self.track), before)
            self.assertEqual(len(self.service.list_members(self.track)), 3)
            self.assertFalse((self.track_root / "images" / image.name).exists())
            self.assertEqual(self.gt.read_bytes(), self.original_gt)
            self.assertTrue(self.ready())
        self.assertEqual(invalidated_before_rollback, [True, True])

    def test_late_manifest_failure_cannot_reactivate_old_gt(self):
        with patch.object(self.service, "_write_manifest", side_effect=OSError("manifest failure")):
            with self.assertRaisesRegex(OSError, "manifest failure"):
                self.service.add_members_batch(self.track, [self.f.image("ADDED_001.png", seed=1900)])
        self.assertEqual(len(self.service.list_members(self.track)), 4)
        self.assert_gt_invalidated()
        self.assertFalse(_valid_existing_gt(
            self.f.workspace, self.original_track, self.service.list_members(self.track)))


if __name__ == "__main__":
    unittest.main()
