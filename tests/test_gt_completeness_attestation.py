import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.track_service import (
    EvaluationTrackError,
    EvaluationTrackService,
    GT_COMPLETENESS_ATTESTATION_SCHEMA,
    GT_COMPLETENESS_ATTESTATION_STATEMENT,
)


class GroundTruthCompletenessAttestationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.service = EvaluationTrackService(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def _draft(self, *, name="one.jpg", payload=b"image"):
        image = Path(self.temp.name) / name
        image.write_bytes(payload)
        gt = Path(self.temp.name) / f"{Path(name).stem}.xml"
        gt.write_text(
            (
                "<annotations>"
                f'<image id="0" name="{name}" width="100" height="50">'
                '<polygon label="plate" '
                'points="0,0;10,0;10,10;0,10"/>'
                "</image></annotations>"
            ),
            encoding="utf-8",
        )
        track_id = self.service.create_draft(
            name=f"track-{Path(name).stem}",
            target="plate",
            purpose="final_test",
            reservation_policy="reserve_from_training",
        )
        self.service.add_member(track_id, image)
        self.service.set_ground_truth(track_id, gt)
        return track_id

    def test_verify_without_attestation_records_explicit_false(self):
        track_id = self._draft()
        result = self.service.verify(track_id)

        self.assertFalse(result["manual_gt_complete"])
        self.assertEqual(result["manual_gt_attested_at"], "")
        self.assertEqual(
            self.service.get_verification(track_id)[
                "manual_gt_complete"
            ],
            False,
        )

    def test_verify_with_attestation_records_meaning_and_time(self):
        track_id = self._draft()
        result = self.service.verify(
            track_id,
            manual_gt_complete=True,
        )

        self.assertTrue(result["manual_gt_complete"])
        self.assertTrue(result["manual_gt_attested_at"])
        self.assertEqual(
            result["manual_gt_attestation_schema"],
            GT_COMPLETENESS_ATTESTATION_SCHEMA,
        )
        self.assertEqual(
            result["manual_gt_attestation_statement"],
            GT_COMPLETENESS_ATTESTATION_STATEMENT,
        )

    def test_attested_sealed_track_is_valid_controlled_reference(self):
        track_id = self._draft()
        self.service.verify(
            track_id,
            manual_gt_complete=True,
        )
        self.service.seal(track_id)

        ref = self.service.build_controlled_reference(
            track_id,
            required_target="plate",
            require_manual_gt_complete=True,
        )
        self.assertTrue(ref.manual_gt_complete)
        self.assertTrue(ref.manual_gt_attested_at)
        self.assertEqual(
            ref.manual_gt_attestation_schema,
            GT_COMPLETENESS_ATTESTATION_SCHEMA,
        )
        self.assertEqual(
            ref.manual_gt_attestation_statement,
            GT_COMPLETENESS_ATTESTATION_STATEMENT,
        )

    def test_unattested_sealed_track_is_blocked_for_controlled_use(self):
        track_id = self._draft()
        self.service.verify(track_id)
        self.service.seal(track_id)

        with self.assertRaises(EvaluationTrackError):
            self.service.build_controlled_reference(
                track_id,
                required_target="plate",
                require_manual_gt_complete=True,
            )

    def test_verified_legacy_track_can_be_attested_before_seal(self):
        track_id = self._draft()
        self.service.verify(track_id)

        verification = self.service.attest_ground_truth_completeness(
            track_id
        )
        self.assertTrue(verification["manual_gt_complete"])
        self.service.seal(track_id)

        ref = self.service.build_controlled_reference(
            track_id,
            required_target="plate",
            require_manual_gt_complete=True,
        )
        self.assertTrue(ref.manual_gt_complete)

    def test_sealed_track_attestation_is_immutable(self):
        track_id = self._draft()
        self.service.verify(track_id)
        self.service.seal(track_id)

        with self.assertRaises(EvaluationTrackError):
            self.service.attest_ground_truth_completeness(track_id)

    def test_clone_does_not_inherit_human_attestation(self):
        track_id = self._draft()
        self.service.verify(
            track_id,
            manual_gt_complete=True,
        )
        self.service.seal(track_id)

        clone_id = self.service.clone_new_version(track_id)
        verification = self.service.get_verification(clone_id)
        self.assertFalse(
            bool(verification.get("manual_gt_complete"))
        )
        self.assertEqual(
            str(verification.get("manual_gt_attested_at") or ""),
            "",
        )


if __name__ == "__main__":
    unittest.main()
