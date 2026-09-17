"""CTA PZ3 muszą wynikać z jednej jawnej maszyny stanów."""
import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.track_readiness import track_readiness
from auto_annotation_tool.gui.pz3_workflow_view import (
    build_pz3_workflow_view_state, has_selected_sample,
)


class PZ3WorkflowViewTests(unittest.TestCase):
    def view(self, *, participants=2, members=10, audit=None, finalized=False,
             working=0, labels=0, status="DRAFT", gt=False,
             purpose="ranking", target="plate"):
        readiness = track_readiness(
            {"status": status, "target": target, "purpose": purpose},
            participant_count=participants, member_count=members, audit_state=audit,
            gt_exists=gt, verification={"manual_gt_complete": gt},
        )
        review = {
            "status": "WORKING" if working or labels else "NONE",
            "selected_count": working,
            "label_count": labels,
            "assigned_count": working if labels else 0,
            "unlabeled_count": 0 if labels else working,
        }
        return build_pz3_workflow_view_state(
            readiness, audit_state=audit, sample_selected=finalized,
            sample_review=review,
        )

    def test_models_then_images_then_audit(self):
        self.assertEqual(self.view(participants=0, members=0).primary_action, "btn_participants")
        self.assertEqual(self.view(members=0).primary_action, "btn_add_images")
        view = self.view(audit={"status": "STALE"})
        self.assertEqual(view.primary_action, "btn_audit_pool")
        self.assertTrue(view.can_audit_pool)

    def test_current_audit_disables_audit_and_opens_sample(self):
        view = self.view(audit={"status": "CURRENT", "audit_id": "A"})
        self.assertEqual(view.primary_action, "btn_sample_selection")
        self.assertTrue(view.can_edit_sample)
        self.assertFalse(view.can_audit_pool)

    def test_working_sample_is_editable_and_finalizable_without_reaudit(self):
        view = self.view(audit={"status": "CURRENT"}, working=1000, labels=4)
        self.assertEqual(view.step, "EDIT_SAMPLE")
        self.assertEqual(view.primary_action, "btn_finalize_sample")
        self.assertTrue(view.can_edit_sample)
        self.assertTrue(view.can_finalize_sample)
        self.assertFalse(view.can_audit_pool)

    def test_pool_change_reenables_only_pool_audit(self):
        view = self.view(audit={"status": "STALE", "audit_id": "A"}, working=1000, labels=4)
        self.assertEqual(view.primary_action, "btn_audit_pool")
        self.assertTrue(view.can_audit_pool)
        self.assertFalse(view.can_edit_sample)
        self.assertFalse(view.can_finalize_sample)

    def test_finalized_subset_goes_directly_to_gt(self):
        view = self.view(audit={"status": "CURRENT"}, finalized=True)
        self.assertEqual(view.step, "PREPARE_GT")
        self.assertEqual(view.primary_action, "btn_prepare_z2")
        self.assertTrue(view.can_prepare_gt)
        self.assertFalse(view.can_audit_pool)
        self.assertFalse(view.can_add_images)
        self.assertFalse(view.can_select_participants)

    def test_existing_gt_goes_to_verify(self):
        view = self.view(audit={"status": "CURRENT"}, finalized=True, gt=True)
        self.assertEqual(view.primary_action, "btn_verify")

    def test_verified_and_sealed_states(self):
        self.assertEqual(
            self.view(audit={"status": "CURRENT"}, finalized=True, gt=True, status="VERIFIED").primary_action,
            "btn_seal",
        )
        self.assertEqual(self.view(status="SEALED").primary_action, "btn_compare")
        self.assertEqual(self.view(status="RETIRED").primary_action, "")

    def test_validation_and_char_preserve_existing_routes(self):
        self.assertEqual(self.view(purpose="validation", participants=0).primary_action, "btn_prepare_z2")
        self.assertEqual(self.view(target="char", audit={"status": "CURRENT"}).primary_action, "btn_set_gt")

    def test_selected_sample_identity_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            track = {"track_id": "T", "relative_path": "track"}
            root = Path(temp) / "track"
            root.mkdir()
            selection = root / "sample_selection.json"
            data = {"schema": "alpr.experiment_sample_selection.v1",
                    "track_id": "T", "selected_member_sha256": ["a", "b"]}
            members = [{"sha256": "a"}, {"sha256": "b"}]
            self.assertFalse(has_selected_sample(temp, track, members))
            selection.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(has_selected_sample(temp, track, members))
            self.assertTrue(has_selected_sample(temp, track, members[:1]))
            self.assertFalse(has_selected_sample(temp, track, members + [{"sha256": "c"}]))


if __name__ == "__main__":
    unittest.main()
