import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.track_service import (
    EvaluationTrackService,
    STATUS_DRAFT,
    STATUS_RETIRED,
    STATUS_SEALED,
    STATUS_VERIFIED,
)
from auto_annotation_tool.gui.z4_evaluation_tracks import (
    action_state_for_status,
    purpose_label,
    reservation_policy_for_purpose,
    target_label,
)


class EvaluationTrackGuiLogicTests(unittest.TestCase):
    def test_action_states_follow_track_lifecycle(self):
        draft = action_state_for_status(STATUS_DRAFT)
        self.assertTrue(draft.can_add_images)
        self.assertTrue(draft.can_set_ground_truth)
        self.assertTrue(draft.can_verify)
        self.assertFalse(draft.can_seal)

        verified = action_state_for_status(STATUS_VERIFIED)
        self.assertFalse(verified.can_add_images)
        self.assertTrue(verified.can_seal)
        self.assertFalse(verified.can_clone)

        sealed = action_state_for_status(STATUS_SEALED)
        self.assertTrue(sealed.can_check_integrity)
        self.assertTrue(sealed.can_clone)
        self.assertTrue(sealed.can_retire)

        retired = action_state_for_status(STATUS_RETIRED)
        self.assertTrue(retired.can_check_integrity)
        self.assertTrue(retired.can_clone)
        self.assertFalse(retired.can_retire)

    def test_final_and_ranking_tracks_default_to_training_reservation(self):
        self.assertEqual(
            reservation_policy_for_purpose("final_test"),
            "reserve_from_training",
        )
        self.assertEqual(
            reservation_policy_for_purpose("ranking"),
            "reserve_from_training",
        )
        self.assertEqual(
            reservation_policy_for_purpose("validation"),
            "none",
        )

    def test_display_labels_are_stable(self):
        self.assertEqual(target_label("plate"), "MT / tablice")
        self.assertEqual(target_label("char"), "MZ / znaki")
        self.assertEqual(purpose_label("final_test"), "test końcowy")

    def test_service_lists_tracks_for_gui(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            service = EvaluationTrackService(workspace)
            first = service.create_draft(
                name="A",
                target="plate",
                purpose="final_test",
            )
            second = service.create_draft(
                name="B",
                target="char",
                purpose="validation",
            )

            rows = service.list_tracks(include_retired=True)
            ids = {row["track_id"] for row in rows}
            self.assertEqual(ids, {first, second})

            plate = service.list_tracks(
                target="plate",
                include_retired=True,
            )
            self.assertEqual(
                [row["track_id"] for row in plate],
                [first],
            )

    def test_add_member_reuses_registered_artifact_lineage_by_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "Workspace"
            service = EvaluationTrackService(workspace)
            repo = service.repository

            payload = b"known-artifact"
            sha = hashlib.sha256(payload).hexdigest()
            image = Path(tmp) / "known.jpg"
            image.write_bytes(payload)

            with repo.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO source_images (
                        source_image_id, canonical_sha256, origin_status
                    ) VALUES (?, ?, ?)
                    """,
                    ("SRC-KNOWN", "f" * 64, "known"),
                )
                connection.execute(
                    """
                    INSERT INTO image_artifacts (
                        artifact_id, source_image_id, relative_path,
                        sha256, size_bytes, kind
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ART-KNOWN",
                        "SRC-KNOWN",
                        "known.jpg",
                        sha,
                        len(payload),
                        "dataset_image",
                    ),
                )

            track_id = service.create_draft(
                name="Lineage",
                target="plate",
                purpose="ranking",
            )
            service.add_member(track_id, image)
            member = service.list_members(track_id)[0]

            self.assertEqual(member["source_image_id"], "SRC-KNOWN")
            self.assertEqual(member["source_artifact_id"], "ART-KNOWN")


if __name__ == "__main__":
    unittest.main()
