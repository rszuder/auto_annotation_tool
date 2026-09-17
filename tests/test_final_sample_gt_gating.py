"""New plate GT requires a finalized subset of the already audited pool."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.config import CONFIG
from auto_annotation_tool.registry.experiment_gt_workspace import prepare_gt_workspace, working_gt_path
from auto_annotation_tool.registry.final_sample_policy import final_sample_ready_for_gt
from auto_annotation_tool.registry.sample_selection import prepare_sample_selection
from auto_annotation_tool.registry.track_service import EvaluationTrackError
from auto_annotation_tool.gui.z4_evaluation_tracks import EvaluationTracksPanel

GUI = "auto_annotation_tool.gui.z4_evaluation_tracks."


class FinalSampleSetup:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)
        self.service, self.track = self.f.service, self.f.track
        self.images = [self.f.image(f"POOL_{i:03}.png", seed=1300+i) for i in range(3)]
        self.service.add_members_batch(self.track, self.images)
        self.audit()

    def audit(self):
        root = self.service._track_root(self.service.get_track(self.track))
        paths = [root / row["track_relative_path"] for row in self.service.list_members(self.track)]
        report = self.f.audit.audit_paths(self.track, paths)
        self.f.audit.record_ingested_report(self.track, report, paths)

    def commit(self, count=2):
        context = prepare_sample_selection(self.service, self.track)
        rows = self.service.list_members(self.track)
        self.service.commit_sample_selection(
            self.track, keep_sha256={row["sha256"] for row in rows[:count]},
            expected_member_sha256=context["sample_member_sha256"],
            expected_audit_id=context["sample_audit_id"],
        )

    def xml(self):
        root = ET.Element("annotations")
        for i, row in enumerate(self.service.list_members(self.track)):
            node = ET.SubElement(root, "image", id=str(i), name=row["original_name"], width="192", height="128")
            ET.SubElement(node, "polygon", label="plate", points="10,10;80,10;80,40;10,40")
        path = Path(self.temp.name) / "import.xml"
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        return path

    def ready(self):
        return final_sample_ready_for_gt(
            self.f.workspace, self.service.get_track(self.track),
            self.service.list_members(self.track), self.f.audit.get_track_audit_state(self.track))

    def assert_both_blocked(self, message):
        with self.assertRaisesRegex(EvaluationTrackError, message):
            prepare_gt_workspace(self.service, self.track)
        with self.assertRaisesRegex(EvaluationTrackError, message):
            self.service.set_ground_truth(self.track, self.xml())
        self.assertFalse(working_gt_path(self.service, self.track).exists())
        self.assertIsNone(self.service.get_track(self.track)["gt_relative_path"])


class FinalSampleGtBackendTests(FinalSampleSetup, unittest.TestCase):
    def test_prepare_gt_backend_rejects_before_sample_selection(self):
        with patch.object(self.service, "_sync_experiment_sources_from_members") as sync:
            with self.assertRaisesRegex(EvaluationTrackError, "finalną próbę"):
                prepare_gt_workspace(self.service, self.track)
        sync.assert_not_called()
        self.assertFalse(self.ready())

    def test_set_gt_backend_rejects_before_sample_selection(self):
        with self.assertRaisesRegex(EvaluationTrackError, "finalną próbę"):
            self.service.set_ground_truth(self.track, self.xml())
        self.assertIsNone(self.service.get_track(self.track)["gt_relative_path"])

    def test_gt_enabled_immediately_after_finalizing_audited_subset(self):
        self.commit()
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "CURRENT")
        self.assertTrue(self.ready())
        self.assertTrue(Path(prepare_gt_workspace(self.service, self.track)["annotation_path"]).is_file())

    def test_selecting_whole_pool_preserves_current_audit(self):
        self.commit(count=3)
        self.assertEqual(len(self.service.list_members(self.track)), 3)
        self.assertEqual(self.f.audit.get_track_audit_state(self.track)["status"], "CURRENT")
        self.assertTrue(self.ready())

    def test_gt_enabled_after_sample_finalization_without_second_audit(self):
        self.commit()
        self.assertTrue(self.ready())
        context = prepare_gt_workspace(self.service, self.track)
        self.assertEqual(len(ET.parse(context["annotation_path"]).getroot().findall("image")), 2)

    def test_import_gt_allowed_after_finalization_without_second_audit(self):
        self.assert_both_blocked("finalną próbę")
        self.commit()
        destination = self.service.set_ground_truth(self.track, self.xml())
        self.assertTrue(destination.is_file())
        self.assertEqual(len(ET.parse(destination).getroot().findall("image")), 2)

    def test_final_test_has_the_same_gate(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE evaluation_tracks SET purpose=? WHERE track_id=?", ("final_test", self.track))
        self.assert_both_blocked("finalną próbę")
        self.commit()
        self.assertTrue(self.service.set_ground_truth(self.track, self.xml()).is_file())

    def test_validation_flow_not_forced_through_sample_selection(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE evaluation_tracks SET purpose=? WHERE track_id=?", ("validation", self.track))
        self.f.audit.invalidate_track_audit(self.track, reason="test")
        self.assertTrue(self.ready())
        context = prepare_gt_workspace(self.service, self.track)
        self.assertTrue(Path(context["annotation_path"]).is_file())
        self.assertTrue(self.service.set_ground_truth(self.track, self.xml()).is_file())

    def test_char_gt_flow_not_forced_through_plate_sample_selection(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE evaluation_tracks SET target=? WHERE track_id=?", ("char", self.track))
        self.assertTrue(self.ready())
        self.assertTrue(self.service.set_ground_truth(self.track, self.xml()).is_file())

    def test_vehicle_gt_flow_not_forced_through_plate_sample_selection(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE evaluation_tracks SET target=? WHERE track_id=?", ("vehicle", self.track))
        self.assertTrue(self.ready())
        self.assertTrue(self.service.set_ground_truth(self.track, self.xml()).is_file())

    def test_existing_gt_does_not_require_reselecting_sample(self):
        # Reproduce a GT registered by an older version, without a sample record.
        path = self.f.workspace / "legacy.xml"
        path.write_bytes(self.xml().read_bytes())
        self.f.repo.update_evaluation_track(
            self.track, gt_relative_path="legacy.xml", gt_format="cvat_xml",
            gt_sha256=self.service._sha256(path))
        self.assertTrue(self.ready())
        context = prepare_gt_workspace(self.service, self.track)
        self.assertTrue(context["gt_existing"])
        self.assertTrue(self.service.set_ground_truth(self.track, self.xml()).is_file())

    def test_missing_or_modified_existing_gt_does_not_bypass_sample_guard(self):
        path = self.f.workspace / "legacy.xml"
        path.write_bytes(self.xml().read_bytes())
        self.f.repo.update_evaluation_track(
            self.track, gt_relative_path="legacy.xml", gt_format="cvat_xml",
            gt_sha256=self.service._sha256(path))
        path.write_text("changed", encoding="utf-8")
        self.assertFalse(self.ready())
        with self.assertRaises(EvaluationTrackError):
            self.service.set_ground_truth(self.track, self.xml())
        path.unlink()
        self.assertFalse(self.ready())

    def test_reaudited_subset_is_allowed_but_new_image_requires_new_selection(self):
        self.commit()
        rows = self.service.list_members(self.track)
        self.service.remove_members(self.track, [rows[-1]["member_index"]])
        self.audit()
        self.assertTrue(self.ready())
        self.service.add_members_batch(self.track, [self.images[-1]])
        self.audit()
        self.assert_both_blocked("finalną próbę")

    def test_deleted_or_malformed_selection_cannot_be_replaced_by_current_audit(self):
        self.commit()
        self.audit()
        root = self.service._track_root(self.service.get_track(self.track))
        selection = root / "sample_selection.json"
        for content in ("{}", "[]", "broken"):
            with self.subTest(content=content):
                selection.write_text(content, encoding="utf-8")
                self.assert_both_blocked("finalną próbę")
        selection.unlink()
        self.assert_both_blocked("finalną próbę")


class FinalSampleGtGuiTests(FinalSampleSetup, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.enterContext(patch.object(CONFIG, "WORKSPACE_DIR", self.f.workspace))
        self.enterContext(patch(GUI + "CAMPAIGN.get_active_project_name", return_value=""))
        self.panel = EvaluationTracksPanel(self.root, SimpleNamespace(app=None))
        self.errors = self.enterContext(patch.object(self.panel, "_show_error"))
        self.refresh()

    def refresh(self):
        self.panel.refresh_tracks(select_track_id=self.track)
        self.root.update()

    def test_prepare_gt_disabled_before_sample_selection(self):
        self.assertEqual(str(self.panel.btn_prepare_z2["state"]), "disabled")
        self.assertEqual(str(self.panel.btn_sample_selection["state"]), "normal")
        self.assertEqual(str(self.panel.btn_sample_selection["style"]), "PZ3.Primary.TButton")

    def test_set_gt_disabled_before_sample_selection(self):
        self.assertEqual(str(self.panel.btn_set_gt["state"]), "disabled")

    def test_direct_prepare_entry_cannot_bypass_disabled_button(self):
        with patch("auto_annotation_tool.registry.experiment_gt_workspace.prepare_gt_workspace") as prepare:
            self.panel.prepare_ground_truth_in_z2()
        prepare.assert_not_called()
        self.assertIn("finalną próbę", str(self.errors.call_args.args[1]))

    def test_direct_import_entry_cannot_open_picker_before_sample(self):
        with patch(GUI + "filedialog.askopenfilename") as picker, patch.object(self.service, "set_ground_truth") as save:
            self.panel.set_ground_truth()
        picker.assert_not_called()
        save.assert_not_called()
        self.assertIn("finalną próbę", str(self.errors.call_args.args[1]))

    def test_buttons_follow_finalization_without_second_audit(self):
        self.commit()
        self.refresh()
        for button in (self.panel.btn_prepare_z2, self.panel.btn_set_gt):
            self.assertEqual(str(button["state"]), "normal")
        self.assertEqual(str(self.panel.btn_audit_pool["state"]), "disabled")
        self.assertEqual(str(self.panel.btn_finalize_sample["state"]), "disabled")
        self.assertEqual(str(self.panel.btn_prepare_z2["style"]), "PZ3.Primary.TButton")
        with patch(GUI + "filedialog.askopenfilename", return_value=str(self.xml())):
            self.panel.set_ground_truth()
        self.errors.assert_not_called()
        self.assertIsNotNone(self.service.get_track(self.track)["gt_relative_path"])


if __name__ == "__main__":
    unittest.main()
