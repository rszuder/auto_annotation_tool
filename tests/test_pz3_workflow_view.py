"""User-facing guidance must follow, and never replace, backend readiness."""
import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.track_readiness import track_readiness
from auto_annotation_tool.gui.pz3_workflow_view import build_pz3_workflow_view_state, has_selected_sample


class PZ3WorkflowViewTests(unittest.TestCase):
    def view(self, *, participants=2, members=10, audit=None, sample=False,
             status="DRAFT", gt=False, purpose="ranking", target="plate"):
        readiness = track_readiness(
            {"status": status, "target": target, "purpose": purpose},
            participant_count=participants, member_count=members, audit_state=audit,
            gt_exists=gt, verification={"manual_gt_complete": gt},
        )
        return build_pz3_workflow_view_state(readiness, audit_state=audit, sample_selected=sample)

    def test_audit_ui_waits_for_models(self):
        view = self.view(participants=0, members=0, audit={"status": "STALE"})
        self.assertEqual(view.audit_label, "czeka na wybór modeli")
        self.assertEqual(view.primary_action, "btn_participants")
        self.assertEqual(view.step, "SELECT_MODELS")

    def test_audit_ui_waits_for_images(self):
        view = self.view(members=0, audit={"status": "STALE"})
        self.assertEqual(view.audit_label, "czeka na pulę obrazów")
        self.assertEqual(view.primary_action, "btn_add_images")
        self.assertEqual(view.step, "ADD_IMAGES")

    def test_audit_ui_first_run_is_to_be_done(self):
        view = self.view(audit={"status": "STALE", "reason": "members_changed"})
        self.assertEqual(view.audit_label, "do wykonania")
        self.assertEqual(view.primary_action, "btn_audit_pool")
        self.assertEqual(view.step, "AUDIT_POOL")

    def test_audit_ui_invalidated_is_requires_repeat(self):
        view = self.view(audit={"status": "STALE", "audit_id": "A1"})
        self.assertEqual(view.audit_label, "wymaga ponowienia")
        self.assertEqual(view.audit_tone, "warning")

    def test_audit_ui_current_is_current(self):
        view = self.view(audit={"status": "CURRENT", "audit_id": "A1"})
        self.assertEqual(view.audit_label, "aktualny")
        self.assertEqual(view.primary_action, "btn_sample_selection")
        self.assertEqual(view.step, "SELECT_SAMPLE")

    def test_primary_cta_reaudit_after_sample_commit(self):
        view = self.view(audit={"status": "STALE", "audit_id": "A1"}, sample=True)
        self.assertEqual(view.step, "REAUDIT_SAMPLE")
        self.assertEqual(view.primary_action, "btn_audit_sample")
        self.assertEqual(view.audit_button_label, "Sprawdź finalną próbę")
        self.assertIn("Finalna próba wymaga ponownego sprawdzenia", view.status_text)

    def test_primary_cta_prepare_gt_after_reaudit(self):
        view = self.view(audit={"status": "CURRENT"}, sample=True)
        self.assertEqual(view.step, "PREPARE_GT")
        self.assertEqual(view.primary_action, "btn_prepare_z2")

    def test_existing_gt_goes_to_verify_without_forcing_sample_selection(self):
        view = self.view(audit={"status": "CURRENT"}, gt=True)
        self.assertEqual(view.step, "VERIFY")
        self.assertEqual(view.primary_action, "btn_verify")

    def test_verified_goes_to_seal(self):
        view = self.view(audit={"status": "CURRENT"}, gt=True, status="VERIFIED")
        self.assertEqual(view.primary_action, "btn_seal")

    def test_verified_with_invalidated_audit_returns_to_check(self):
        view = self.view(audit={"status": "STALE", "audit_id": "A"}, gt=True, status="VERIFIED", sample=True)
        self.assertEqual(view.primary_action, "btn_audit_sample")

    def test_frozen_states_do_not_restart_preparation(self):
        self.assertEqual(self.view(status="SEALED").primary_action, "btn_compare")
        self.assertEqual(self.view(status="RETIRED").primary_action, "")
        self.assertEqual(self.view(status="").primary_action, "")

    def test_validation_and_char_preserve_existing_routes(self):
        self.assertEqual(self.view(purpose="validation", participants=0).primary_action, "btn_prepare_z2")
        self.assertEqual(self.view(target="char", audit={"status": "CURRENT"}).primary_action, "btn_set_gt")

    def test_selected_sample_survives_reload_and_audit_removals_but_not_new_images(self):
        with tempfile.TemporaryDirectory() as temp:
            track = {"track_id": "T", "relative_path": "track"}
            root = Path(temp)/"track"
            root.mkdir()
            selection = root/"sample_selection.json"
            data = {"schema": "alpr.experiment_sample_selection.v1",
                    "track_id": "T", "selected_member_sha256": ["a", "b"]}
            members = [{"sha256": "a"}, {"sha256": "b"}]
            self.assertFalse(has_selected_sample(temp, track, members))
            selection.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(has_selected_sample(temp, track, members))
            self.assertTrue(has_selected_sample(temp, track, members[:1]))
            self.assertFalse(has_selected_sample(temp, track, members+[{"sha256": "c"}]))
            self.assertFalse(has_selected_sample(temp, track, []))
            data["track_id"] = "OTHER"
            selection.write_text(json.dumps(data), encoding="utf-8")
            self.assertFalse(has_selected_sample(temp, track, members))
            selection.write_text("broken", encoding="utf-8")
            self.assertFalse(has_selected_sample(temp, track, members))


if __name__ == "__main__":
    unittest.main()
