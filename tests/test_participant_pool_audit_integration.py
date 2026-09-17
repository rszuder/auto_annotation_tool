import json
import tempfile
import unittest
from dataclasses import replace

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.track_service import EvaluationTrackError
from auto_annotation_tool.registry.participant_pool_audit import (
    STATUS_CLEAN, STATUS_DEPENDENT, STATUS_SUSPECT, STATUS_UNKNOWN, common_status,
)


class ParticipantAuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)

    def test_real_hashes_classify_mixed_pool_relative_to_participants(self):
        paths = self.f.mixed()
        report = self.f.audit.audit_paths(self.f.track, paths)
        self.assertEqual([c.common_status for c in report.candidates],
                         [STATUS_CLEAN, STATUS_DEPENDENT, STATUS_SUSPECT, STATUS_UNKNOWN, STATUS_CLEAN])
        unrelated = self.f.audit.audit_paths(self.f.track, [self.f.references["M3"]])
        self.assertEqual(unrelated.candidates[0].common_status, STATUS_CLEAN)

    def test_unicode_candidate_paths_preserve_audit_verdicts_and_hashes(self):
        paths = self.f.mixed()
        baseline = self.f.audit.audit_paths(self.f.track, paths)
        folder = self.f.root / "Por\u00f3wnanie_jako\u015bci" / "obrazy"
        folder.mkdir(parents=True)
        copies = []
        for path in paths:
            copied = folder / ("Za\u017c\u00f3\u0142\u0107_" + path.name)
            copied.write_bytes(path.read_bytes())
            copies.append(copied)
        report = self.f.audit.audit_paths(self.f.track, copies)
        for expected, actual in zip(baseline.candidates, report.candidates):
            with self.subTest(file=actual.filename):
                self.assertEqual(actual.common_status, expected.common_status)
                self.assertEqual(actual.sha256, expected.sha256)
                self.assertEqual(actual.phash64, expected.phash64)
                self.assertEqual(actual.per_model, expected.per_model)

    def test_unicode_training_paths_keep_full_reference_coverage(self):
        candidate = self.f.image("IMG_006.png")
        baseline = self.f.audit.audit_paths(self.f.track, [candidate])
        folder = self.f.root / "Dane_treningowe_\u017c\u00f3\u0142\u0107"
        folder.mkdir()
        for number in (1, 2):
            original = self.f.references[f"M{number}"]
            copied = folder / ("Zdj\u0119cie_" + original.name)
            copied.write_bytes(original.read_bytes())
            with self.f.repo.database.transaction() as db:
                db.execute("UPDATE image_artifacts SET external_path=? WHERE artifact_id=?",
                           (str(copied), f"A{number}"))
        report = self.f.audit.audit_paths(self.f.track, [candidate])
        self.assertEqual(report.candidates, baseline.candidates)
        self.assertEqual(report.candidates[0].common_status, STATUS_CLEAN)
        self.assertTrue(all(item.phash_reference_coverage == 1.0
                            for item in report.candidates[0].per_model))

    def test_incomplete_phash_coverage_is_unknown(self):
        with self.f.repo.database.transaction() as db:
            db.execute("INSERT INTO dataset_members(dataset_id, artifact_id, source_image_id, split, file_sha256) "
                       "SELECT 'D1', artifact_id, source_image_id, 'val', sha256 FROM image_artifacts WHERE artifact_id = 'A3'")
        self.f.references["M3"].unlink()
        report = self.f.audit.audit_paths(self.f.track, [self.f.image("IMG_006.png")])
        self.assertEqual(report.candidates[0].common_status, STATUS_UNKNOWN)
        self.assertEqual(report.candidates[0].per_model[0].phash_reference_coverage, 0.5)

    def test_missing_ancestor_dataset_is_unknown(self):
        with self.f.repo.database.transaction() as db:
            db.execute("INSERT INTO training_runs(run_id, target, provenance_status) VALUES ('PARENT', 'plate', 'partial')")
            db.execute("UPDATE training_runs SET parent_run_id='PARENT' WHERE run_id='R1'")
        report = self.f.audit.audit_paths(self.f.track, [self.f.image("IMG_006.png")])
        self.assertEqual(report.candidates[0].common_status, STATUS_UNKNOWN)

    def test_finetune_protects_parent_train_data(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE training_runs SET parent_run_id='R3' WHERE run_id='R1'")
        report = self.f.audit.audit_paths(self.f.track, [self.f.references["M3"]])
        self.assertEqual(report.candidates[0].common_status, STATUS_DEPENDENT)

    def test_shared_dataset_in_ancestry_does_not_reduce_coverage(self):
        with self.f.repo.database.transaction() as db:
            db.execute("INSERT INTO training_runs(run_id, target, dataset_id, provenance_status) VALUES ('PARENT', 'plate', 'D1', 'complete')")
            db.execute("UPDATE training_runs SET parent_run_id='PARENT' WHERE run_id='R1'")
        report = self.f.audit.audit_paths(self.f.track, [self.f.image("IMG_006.png")])
        self.assertEqual(report.candidates[0].common_status, STATUS_CLEAN)

    def test_partial_model_history_is_unknown_even_with_readable_references(self):
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE models SET provenance_status='partial' WHERE model_id='M1'")
        self.f.audit.save_participants(self.f.track, ["M1", "M2"])
        report = self.f.audit.audit_paths(self.f.track, [self.f.image("IMG_006.png")])
        self.assertEqual(report.candidates[0].common_status, STATUS_UNKNOWN)

    def test_record_requires_report_to_cover_every_retained_member(self):
        clean, dependent, suspect, unknown, duplicate = self.f.mixed()
        report = self.f.audit.audit_paths(self.f.track, [clean])
        self.f.service.add_members_batch(self.f.track, [clean, unknown])
        with self.assertRaises(EvaluationTrackError):
            self.f.audit.record_ingested_report(self.f.track, report, [clean])
        self.assert_stale()

    def test_dependent_and_unknown_cannot_be_recorded_as_current(self):
        for index, path in enumerate(self.f.mixed()[1:4]):
            if index == 1:  # suspected derivatives require an explicit GUI choice
                continue
            with self.subTest(path=path.name):
                report = self.f.audit.audit_paths(self.f.track, [path])
                with self.assertRaises(EvaluationTrackError):
                    self.f.audit.record_ingested_report(self.f.track, report, [path])

    def test_participant_or_member_changes_require_new_audit(self):
        clean = self.f.image("IMG_006.png")
        report = self.f.audit.audit_paths(self.f.track, [clean])
        indices = self.f.service.add_members_batch(self.f.track, [clean])
        self.f.audit.record_ingested_report(self.f.track, report, [clean])
        self.f.audit.assert_track_audit_ready(self.f.track)
        self.f.service.remove_members(self.f.track, indices)
        self.assert_stale()
        self.f.audit.save_participants(self.f.track, ["M2"])
        self.assert_stale()

    def test_replaced_registry_checkpoint_blocks_old_audit(self):
        clean = self.f.image("IMG_006.png")
        report = self.f.audit.audit_paths(self.f.track, [clean])
        self.f.service.add_members_batch(self.f.track, [clean])
        self.f.audit.record_ingested_report(self.f.track, report, [clean])
        with self.f.repo.database.transaction() as db:
            db.execute("UPDATE models SET sha256=? WHERE model_id='M1'", ("f" * 64,))
        with self.assertRaises(EvaluationTrackError):
            self.f.audit.assert_track_audit_ready(self.f.track)

    def test_cache_survives_service_restart(self):
        from auto_annotation_tool.registry.participant_pool_audit import ParticipantPoolAuditService
        clean = self.f.image("IMG_006.png")
        self.f.audit.audit_paths(self.f.track, [clean])
        fresh = ParticipantPoolAuditService(self.f.workspace, repository=self.f.repo)
        report = fresh.audit_paths(self.f.track, [clean])
        self.assertEqual(report.cache_misses_sha, 0)
        self.assertEqual(report.cache_misses_phash, 0)
        self.assertEqual(report.cache_hits_sha, 1)

    def test_empty_or_unrecognized_verdicts_are_unknown(self):
        self.assertEqual(common_status([]), STATUS_UNKNOWN)
        self.assertEqual(common_status(["unexpected"]), STATUS_UNKNOWN)

    def test_changed_file_does_not_reuse_old_phash_after_sha_refresh(self):
        from auto_annotation_tool.registry.participant_pool_audit import _sha256_file
        path = self.f.image("IMG_006.png")
        self.f.audit.cache.put(path, sha256=_sha256_file(path), phash64="0123456789abcdef")
        path.write_bytes(b"changed bytes")
        self.f.audit.fingerprint_paths([path])
        self.assertNotIn("phash64", self.f.audit.cache.get(path))

    def test_ingested_copies_reuse_audited_fingerprints(self):
        clean = self.f.image("IMG_006.png")
        report = self.f.audit.audit_paths(self.f.track, [clean])
        self.f.service.add_members_batch(self.f.track, [clean])
        self.f.audit.record_ingested_report(self.f.track, report, [clean])
        member = self.f.service.list_members(self.f.track)[0]
        copied = self.f.workspace / self.f.service.get_track(self.f.track)["relative_path"] / member["track_relative_path"]
        repeated = self.f.audit.audit_paths(self.f.track, [copied])
        self.assertEqual(repeated.cache_misses_sha, 0)
        self.assertEqual(repeated.cache_misses_phash, 0)

    def assert_stale(self):
        state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.assertEqual(state["status"], "STALE")
        with self.assertRaises(EvaluationTrackError):
            self.f.audit.assert_track_audit_ready(self.f.track)


if __name__ == "__main__":
    unittest.main()

