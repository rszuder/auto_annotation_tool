import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auto_annotation_tool.gui.z4_evaluation_tracks import (
    EvaluationTracksPanel,
    independent_acquisition_attestation_prompt,
    independent_acquisition_attested,
    requires_independent_acquisition_attestation,
)


class _FakeTrackService:
    def __init__(
        self,
        *,
        purpose="final_test",
        verification=None,
    ):
        self.track = {
            "track_id": "TRK-TEST",
            "target": "plate",
            "purpose": purpose,
        }
        self.verification = dict(
            verification
            or {
                "manual_gt_complete": True,
            }
        )
        self.calls = []

    def get_track(self, track_id):
        self.calls.append(("get_track", track_id))
        return dict(self.track)

    def get_verification(self, track_id):
        self.calls.append(("get_verification", track_id))
        return dict(self.verification)

    def attest_ground_truth_completeness(self, track_id):
        self.calls.append(("attest_gt", track_id))
        self.verification["manual_gt_complete"] = True
        return dict(self.verification)

    def attest_independent_acquisition(
        self,
        track_id,
        *,
        source_pool,
    ):
        self.calls.append(
            ("attest_independent", track_id, source_pool)
        )
        self.verification.update(
            {
                "independent_acquisition": True,
                "not_derived_from_training_data": True,
                "acquisition_source_pool": source_pool,
                "independent_acquisition_attested_at": (
                    "2026-09-12T20:00:00+00:00"
                ),
            }
        )
        return dict(self.verification)

    def seal(self, track_id):
        self.calls.append(("seal", track_id))
        return SimpleNamespace(status="PASS")


def _panel(service):
    panel = object.__new__(EvaluationTracksPanel)
    panel.parent = object()
    panel.service = service
    panel.current_track_id = "TRK-TEST"
    panel._require_current_track = Mock(
        return_value="TRK-TEST"
    )
    panel._show_error = Mock()
    panel.refresh_tracks = Mock()
    panel._set_status = Mock()
    return panel


class IndependentAcquisitionGuiTests(unittest.TestCase):
    def test_policy_applies_only_to_final_test_and_ranking(self):
        self.assertTrue(
            requires_independent_acquisition_attestation(
                "final_test"
            )
        )
        self.assertTrue(
            requires_independent_acquisition_attestation(
                "ranking"
            )
        )
        self.assertFalse(
            requires_independent_acquisition_attestation(
                "validation"
            )
        )

    def test_prompt_explains_new_pool_and_no_train_val_derivatives(self):
        text = independent_acquisition_attestation_prompt()
        normalized = text.lower()
        self.assertIn("niezależ", normalized)
        self.assertIn("train", normalized)
        self.assertIn("val", normalized)
        self.assertIn("pochod", normalized)

    def test_final_test_records_attestation_before_seal(self):
        service = _FakeTrackService()
        panel = _panel(service)

        with patch(
            "auto_annotation_tool.gui.z4_evaluation_tracks."
            "messagebox.askyesno",
            side_effect=[True, True],
        ) as ask:
            panel.seal_track()

        self.assertEqual(ask.call_count, 2)
        self.assertIn(
            (
                "attest_independent",
                "TRK-TEST",
                "new_independent_acquisition",
            ),
            service.calls,
        )
        self.assertLess(
            service.calls.index(
                (
                    "attest_independent",
                    "TRK-TEST",
                    "new_independent_acquisition",
                )
            ),
            service.calls.index(("seal", "TRK-TEST")),
        )
        panel._show_error.assert_not_called()

    def test_existing_attestation_is_not_requested_again(self):
        service = _FakeTrackService(
            purpose="ranking",
            verification={
                "manual_gt_complete": True,
                "independent_acquisition": True,
                "not_derived_from_training_data": True,
                "acquisition_source_pool": (
                    "new_independent_acquisition"
                ),
                "independent_acquisition_attested_at": (
                    "2026-09-12T20:00:00+00:00"
                ),
            },
        )
        panel = _panel(service)

        with patch(
            "auto_annotation_tool.gui.z4_evaluation_tracks."
            "messagebox.askyesno",
            return_value=True,
        ) as ask:
            panel.seal_track()

        self.assertEqual(ask.call_count, 1)
        self.assertFalse(
            any(
                call[0] == "attest_independent"
                for call in service.calls
            )
        )
        self.assertIn(("seal", "TRK-TEST"), service.calls)

    def test_validation_track_skips_independent_acquisition_prompt(self):
        service = _FakeTrackService(purpose="validation")
        panel = _panel(service)

        with patch(
            "auto_annotation_tool.gui.z4_evaluation_tracks."
            "messagebox.askyesno",
            return_value=True,
        ) as ask:
            panel.seal_track()

        self.assertEqual(ask.call_count, 1)
        self.assertFalse(
            any(
                call[0] == "attest_independent"
                for call in service.calls
            )
        )
        self.assertIn(("seal", "TRK-TEST"), service.calls)


if __name__ == "__main__":
    unittest.main()
