"""Participant dataset lineage, live audit invalidation and frozen compatibility."""
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry import participant_pool_audit as audit_module
from auto_annotation_tool.registry.participant_pool_audit import participant_fingerprint
from auto_annotation_tool.registry.participant_model_registry import register_existing_participant_model
from auto_annotation_tool.registry.experiment_gt_workspace import prepare_gt_workspace, publish_working_gt
from auto_annotation_tool.registry.track_service import EvaluationTrackError


def legacy_fingerprint(participants):
    payload = "\n".join(
        f"{p.model_id}|{p.sha256}|{p.run_id}|{p.provenance_status}"
        for p in sorted(participants, key=lambda p: p.model_id)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def legacy_asdict(value):
    row = asdict(value)
    if isinstance(value, audit_module.ParticipantModel):
        row.pop("dataset_id")
    return row


class ParticipantDatasetLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)

    def _eligible_ids(self):
        return {p.model_id for p in self.f.audit.list_eligible_models("plate")}

    def _current_audit(self):
        image = self.f.image("TEST_001.png", seed=987)
        report = self.f.audit.audit_paths(self.f.track, [image])
        self.f.service.add_member(self.f.track, image)
        self.f.audit.record_ingested_report(self.f.track, report, [image])
        self.f.audit.assert_track_audit_ready(self.f.track)
        return image

    def test_participant_model_contains_dataset_id(self):
        participant = self.f.audit.load_participants(self.f.track)[0]
        self.assertEqual(participant.dataset_id, "D1")

    def test_list_eligible_models_resolves_dataset_from_training_run(self):
        with patch.object(self.f.repo, "get_training_run", side_effect=AssertionError("N+1 query")), \
             patch.object(self.f.repo, "list_models_for_target", wraps=self.f.repo.list_models_for_target) as query:
            participants = self.f.audit.list_eligible_models("plate")
        query.assert_called_once_with("plate")
        self.assertEqual({p.run_id: p.dataset_id for p in participants},
                         {"R1": "D1", "R2": "D2", "R3": "D3"})
        self.assertEqual(self.f.audit.list_eligible_models("char"), [])

    def test_complete_model_without_dataset_is_not_eligible(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE training_runs SET dataset_id=NULL WHERE run_id='R1'")
        self.assertNotIn("M1", self._eligible_ids())
        with self.assertRaisesRegex(EvaluationTrackError, "lineage"):
            self.f.audit.save_participants(self.f.track, ["M1"])

    def test_known_model_without_dataset_is_not_eligible(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE models SET provenance_status='known' WHERE model_id='M1'")
            db.execute("UPDATE training_runs SET dataset_id=NULL WHERE run_id='R1'")
        self.assertNotIn("M1", self._eligible_ids())

    def test_complete_and_known_without_run_are_not_eligible(self):
        for status in ("complete", "known"):
            with self.subTest(status=status):
                with self.f.repo.database.transaction() as db:
                    db.execute("UPDATE models SET run_id=NULL, provenance_status=? WHERE model_id='M1'", (status,))
                self.assertNotIn("M1", self._eligible_ids())

    def test_empty_checkpoint_sha_is_not_eligible(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE models SET sha256=' ' WHERE model_id='M1'")
        self.assertNotIn("M1", self._eligible_ids())

    def test_weaker_provenance_remains_available_for_unknown_verdict(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE models SET run_id=NULL, provenance_status='partial' WHERE model_id='M1'")
        self.assertIn("M1", self._eligible_ids())

    def test_participant_fingerprint_changes_when_dataset_changes(self):
        participant = self.f.audit.load_participants(self.f.track)[0]
        self.assertNotEqual(participant_fingerprint([participant]),
                            participant_fingerprint([replace(participant, dataset_id="D2")]))

    def test_save_participants_persists_dataset_id(self):
        self.f.audit.save_participants(self.f.track, ["M2", "M1"])
        payload = json.loads(self.f.audit.participants_path(self.f.track).read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "alpr.evaluation_track_participants.v2")
        self.assertEqual({p["model_id"]: p["dataset_id"] for p in payload["participants"]},
                         {"M1": "D1", "M2": "D2"})

    def test_load_participants_restores_saved_dataset_without_live_enrichment(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE training_runs SET dataset_id='D3' WHERE run_id='R1'")
        participants = self.f.audit.load_participants(self.f.track)
        self.assertEqual(participants[0].dataset_id, "D1")

    def test_changed_lineage_blocks_audit_until_reselection_and_reaudit(self):
        image = self._current_audit()
        participants = self.f.audit.load_participants(self.f.track)
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE training_runs SET dataset_id='D3' WHERE run_id='R1'")
        with self.assertRaisesRegex(EvaluationTrackError, "lineage"):
            self.f.audit._assert_registered_participants(self.f.track, participants)
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "STALE")
        with self.assertRaises(EvaluationTrackError):
            self.f.audit.assert_track_audit_ready(self.f.track)
        with self.assertRaises(EvaluationTrackError):
            self.f.audit.audit_paths(self.f.track, [image])
        with self.assertRaises(EvaluationTrackError):
            prepare_gt_workspace(self.f.service, self.f.track)
        self.f.audit.save_participants(self.f.track, ["M1", "M2"])
        self.assertEqual(self.f.audit.load_participants(self.f.track)[0].dataset_id, "D3")
        report = self.f.audit.audit_paths(self.f.track, [image])
        self.f.audit.record_ingested_report(self.f.track, report, [image])
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "CURRENT")

    def test_legacy_draft_requires_reselection_and_new_audit_without_rewriting_on_read(self):
        self._current_audit()
        path = self.f.audit.participants_path(self.f.track)
        participants = self.f.audit.load_participants(self.f.track)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema"] = "alpr.evaluation_track_participants.v1"
        payload["participant_fingerprint"] = legacy_fingerprint(participants)
        for row in payload["participants"]:
            row.pop("dataset_id")
        path.write_text(json.dumps(payload), encoding="utf-8")
        original = path.read_bytes()
        state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        state["participant_fingerprint"] = payload["participant_fingerprint"]
        self.f.repo.save_evaluation_track_audit_state(self.f.track, state)
        self.assertTrue(all(not p.dataset_id for p in self.f.audit.load_participants(self.f.track)))
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "STALE")
        self.assertEqual(path.read_bytes(), original)

    def test_manual_registration_resolves_dataset_and_keeps_known_status(self):
        path = self.f.workspace / "yolo26s.pt"
        path.write_bytes(b"manual checkpoint")
        registration = register_existing_participant_model(
            self.f.workspace, path, run_id="R2", target="plate", repository=self.f.repo)
        participant = next(p for p in self.f.audit.list_eligible_models("plate")
                           if p.model_id == registration.model_id)
        self.assertEqual((participant.run_id, participant.dataset_id, participant.provenance_status),
                         ("R2", "D2", "known"))

    def _seal(self, *, legacy):
        with ExitStack() as stack:
            if legacy:
                stack.enter_context(patch.object(audit_module, "PARTICIPANT_SCHEMA", "alpr.evaluation_track_participants.v1"))
                # Produce a genuine old-format sealed fixture, including artifact hashes,
                # without altering anything after the seal has been written.
                stack.enter_context(patch.object(audit_module, "participant_fingerprint", legacy_fingerprint))
                stack.enter_context(patch.object(audit_module, "asdict", legacy_asdict))
                stack.enter_context(patch("dataclasses.asdict", legacy_asdict))
            self.f.audit.save_participants(self.f.track, ["M1", "M2"])
            self._current_audit()
            context = prepare_gt_workspace(self.f.service, self.f.track)
            path = Path(context["annotation_path"])
            tree = ET.parse(path)
            ET.SubElement(tree.getroot().find("image"), "polygon",
                          label="plate", points="10,10;80,10;80,40;10,40")
            tree.write(path, encoding="utf-8", xml_declaration=True)
            publish_working_gt(self.f.service, self.f.track, path)
            self.f.service.verify(self.f.track, manual_gt_complete=True)
            self.assertTrue(self.f.service.seal(self.f.track).ok)

    def _assert_frozen_survives_registry_change(self, *, legacy):
        self._seal(legacy=legacy)
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE training_runs SET dataset_id='D3' WHERE run_id='R1'")
        for status in ("SEALED", "RETIRED"):
            with self.subTest(status=status):
                if status == "RETIRED":
                    self.f.service.retire(self.f.track)
                root = self.f.audit.participants_path(self.f.track).parent
                before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                db_state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
                participants = self.f.audit.load_participants(self.f.track)
                self.assertEqual(participants[0].dataset_id, "" if legacy else "D1")
                with patch.object(self.f.audit, "list_eligible_models",
                                  side_effect=AssertionError("Frozen lineage must not consult registry")):
                    self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "CURRENT")
                    self.f.audit.assert_track_audit_ready(self.f.track)
                    self.f.service.get_preparation_state(self.f.track)
                integrity = self.f.service.verify_integrity(self.f.track)
                self.assertTrue(integrity.ok, integrity.issues)
                self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track), db_state)
                self.assertEqual({p: p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)

    def test_load_legacy_participants_without_dataset_does_not_break_sealed_track(self):
        self._assert_frozen_survives_registry_change(legacy=True)

    def test_new_sealed_and_retired_tracks_keep_frozen_dataset(self):
        self._assert_frozen_survives_registry_change(legacy=False)


if __name__ == "__main__":
    unittest.main()
