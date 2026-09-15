import tempfile
import tkinter as tk
import unittest

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.gui.pz3_audit_resolution_dialog import ParticipantAuditMatrixDialog
from auto_annotation_tool.registry.participant_pool_audit import STATUS_DEPENDENT, STATUS_SUSPECT, STATUS_UNKNOWN


class AuditDecisionDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.report = self.f.audit.audit_paths(self.f.track, self.f.mixed()[:4])

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def dialog(self, **options):
        self.root.deiconify()
        self.root.update()
        dialog = ParticipantAuditMatrixDialog(self.root, self.report, **options)
        dialog.window.update()
        return dialog

    def test_filters_details_and_decisions_stay_in_one_window(self):
        dialog = self.dialog(mode="ingest")
        self.assertEqual(len(dialog.tree.get_children()), 4)
        self.assertEqual(str(dialog.apply_button["state"]), "disabled")
        dialog.filter_var.set(STATUS_SUSPECT)
        dialog._populate()
        dialog.window.update()
        self.assertEqual(dialog.tree.get_children(), ("2",))
        detail = dialog.detail.get("1.0", "end")
        self.assertIn("Model: M2", detail)
        self.assertIn("Dataset: D2", detail)
        self.assertIn("Run: R2", detail)
        distance = self.report.candidates[2].per_model[1].phash_distance
        self.assertIn(f"Odległość pHash: {distance}", detail)
        self.assertIn(str(self.f.references["M2"]), detail)
        self.assertIsNotNone(dialog.reference_preview.image)
        dialog.accept_button.invoke()
        self.assertEqual(len(dialog.resolution().accepted_suspects), 1)
        self.assertEqual(str(dialog.apply_button["state"]), "normal")
        self.assertIn("Dodaj 2", str(dialog.apply_button["text"]))
        dialog.apply_button.invoke()
        self.assertFalse(dialog.result.cancelled)
        self.assertEqual(len(dialog.result.accepted_paths), 2)

    def test_unknown_and_dependent_have_no_accept_override(self):
        dialog = self.dialog(mode="ingest")
        for status in (STATUS_DEPENDENT, STATUS_UNKNOWN):
            dialog.filter_var.set(status)
            dialog._populate()
            dialog.window.update()
            self.assertEqual(str(dialog.accept_button["state"]), "disabled")
            self.assertEqual(len(dialog.tree.get_children()), 1)
        dialog._cancel()

    def test_batch_rejection_and_reset_update_apply_state(self):
        dialog = self.dialog(mode="ingest")
        dialog._reject_all_suspects()
        self.assertTrue(dialog.resolution().ready)
        self.assertEqual(len(dialog.resolution().rejected_suspects), 1)
        dialog.filter_var.set(STATUS_SUSPECT)
        dialog._populate()
        dialog.reset_button.invoke()
        self.assertFalse(dialog.resolution().ready)
        self.assertEqual(str(dialog.apply_button["state"]), "disabled")
        dialog._cancel()

    def test_cancel_after_decision_does_not_write_members_or_decisions(self):
        dialog = self.dialog(mode="ingest")
        dialog.set_decision(2, "accept")
        dialog._cancel()
        self.assertTrue(dialog.result.cancelled)
        self.assertEqual(self.f.service.list_members(self.f.track), [])
        self.assertEqual(self.f.repo.list_evaluation_track_audits(self.f.track), [])

    def test_pool_mode_discloses_removal_and_ground_truth_invalidation(self):
        dialog = self.dialog(mode="pool", has_ground_truth=True)
        dialog._reject_all_suspects()
        self.assertEqual(str(dialog.apply_button["text"]), "Zapisz wynik audytu")
        self.assertIn("Do usunięcia z toru: 3", dialog.status_var.get())
        self.assertIn("GT", dialog.status_var.get())
        dialog.window.geometry("980x680")
        dialog.window.update()
        self.assertLessEqual(int(dialog.status_label["wraplength"]), dialog.status_label.winfo_width())
        self.assertLessEqual(
            dialog.apply_button.winfo_rootx() + dialog.apply_button.winfo_width(),
            dialog.window.winfo_rootx() + dialog.window.winfo_width(),
        )
        self.assertLessEqual(
            dialog.apply_button.winfo_rooty() + dialog.apply_button.winfo_height(),
            dialog.window.winfo_rooty() + dialog.window.winfo_height(),
        )
        dialog._cancel()

    def test_verified_track_cannot_remove_images_through_audit(self):
        dialog = self.dialog(mode="pool", can_remove=False)
        dialog._reject_all_suspects()
        self.assertEqual(str(dialog.apply_button["state"]), "disabled")
        self.assertIn("zweryfikowany", dialog.status_var.get())
        dialog._cancel()


if __name__ == "__main__":
    unittest.main()

