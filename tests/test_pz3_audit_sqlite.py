import hashlib
import json
import sqlite3
import tempfile
import unittest
from auto_annotation_tool.registry import SCHEMA_VERSION
from pathlib import Path
from unittest.mock import patch

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry import RegistryDatabase
from auto_annotation_tool.registry.audit_resolution import resolve_audit
from auto_annotation_tool.registry.migrations import migrate_database
from auto_annotation_tool.registry.participant_pool_audit import ParticipantPoolAuditService, STATUS_SUSPECT


class AuditSqliteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)

    def applied(self, *, suspects=False):
        paths = self.f.mixed()[:4] if suspects else [self.f.image("IMG_100.png")]
        report = self.f.audit.audit_paths(self.f.track, paths)
        choices = {item.path: "accept" for item in report.candidates if item.common_status == STATUS_SUSPECT}
        resolution = resolve_audit(report, choices)
        self.f.service.add_members_batch(self.f.track, resolution.accepted_paths)
        self.f.audit.record_resolution(self.f.track, resolution, mode="ingest")
        return resolution

    def test_decisions_and_state_survive_service_restart(self):
        self.applied(suspects=True)
        reopened = ParticipantPoolAuditService(self.f.workspace)
        reopened.assert_track_audit_ready(self.f.track)
        history = reopened.repository.list_evaluation_track_audits(self.f.track)
        self.assertEqual(len(history), 1)
        audit = reopened.repository.get_evaluation_track_audit(history[0]["audit_id"])
        self.assertEqual({row["decision"] for row in audit["decisions"]},
                         {"accept_clean", "manual_accept_suspect", "reject_dependent", "reject_unknown"})
        self.assertEqual(audit["report"]["participants"][0]["model_id"], "M1")
        self.assertEqual(len(reopened.get_track_audit_state(self.f.track)["accepted_suspect_sha256"]), 1)
        self.assertFalse(reopened.audit_state_path(self.f.track).exists())

    def test_failed_decision_transaction_leaves_no_partial_audit_or_current(self):
        path = self.f.image("IMG_100.png")
        report = self.f.audit.audit_paths(self.f.track, [path])
        self.f.service.add_members_batch(self.f.track, [path])
        audit = {
            "audit_id": "bad-audit", "track_id": self.f.track, "mode": "ingest",
            "participant_fingerprint": report.participant_fingerprint,
            "member_fingerprint": "test", "audited_at": report.audited_at,
            "applied_at": report.audited_at, "report": report.to_dict(),
        }
        bad = [{"path": str(path), "sha256": report.candidates[0].sha256,
                "status": "UNKNOWN", "decision": "force_accept_unknown"}]
        with self.assertRaises(sqlite3.IntegrityError):
            self.f.repo.record_evaluation_track_audit(audit, bad, state={"status": "CURRENT"})
        self.assertEqual(self.f.repo.list_evaluation_track_audits(self.f.track), [])
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track)["status"], "STALE")

    def test_sqlite_membership_change_rejects_audit_transaction(self):
        resolution = self.applied()
        previous = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        row = self.f.repo.list_evaluation_track_audits(self.f.track)[0]
        audit = self.f.repo.get_evaluation_track_audit(row["audit_id"])
        audit["audit_id"] = "stale-snapshot"
        with self.assertRaises(ValueError):
            self.f.repo.record_evaluation_track_audit(audit, resolution.decision_rows(),
                                                       state=previous, expected_member_shas=set())
        self.assertEqual(len(self.f.repo.list_evaluation_track_audits(self.f.track)), 1)

    def test_legacy_json_is_imported_once_and_not_a_second_source_of_truth(self):
        self.applied()
        old = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        old.pop("audit_id", None)
        with self.f.repo.database.transaction() as db:
            db.execute("DELETE FROM evaluation_track_audit_state WHERE track_id=?", (self.f.track,))
        path = self.f.audit.audit_state_path(self.f.track)
        path.write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "CURRENT")
        path.write_text('{"status":"STALE"}', encoding="utf-8")
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "CURRENT")
        self.f.audit.invalidate_track_audit(self.f.track, reason="test")
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track)["status"], "STALE")
        self.assertEqual(path.read_text(encoding="utf-8"), '{"status":"STALE"}')

    def test_pending_or_cancelled_resolution_cannot_write_current(self):
        path = self.f.mixed()[2]
        report = self.f.audit.audit_paths(self.f.track, [path])
        for result in (resolve_audit(report), resolve_audit(report, cancelled=True)):
            with self.assertRaises(ValueError):
                self.f.audit.record_resolution(self.f.track, result, mode="ingest")
        self.assertEqual(self.f.repo.list_evaluation_track_audits(self.f.track), [])

    def test_participant_and_member_mutations_invalidate_sqlite_state(self):
        self.applied()
        self.f.service.add_member(self.f.track, self.f.image("IMG_101.png", seed=101))
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track)["status"], "STALE")
        self.f.audit.save_participants(self.f.track, ["M2"])
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track)["reason"], "participants_changed")

    def test_migration_v3_preserves_existing_tracks_and_models(self):
        path = Path(self.temp.name) / "v3.sqlite"
        db = sqlite3.connect(path)
        migrate_database(db, target_version=3)
        db.execute("INSERT INTO models(model_id, sha256) VALUES ('OLD-MODEL', 'old-sha')")
        db.commit()
        db.close()
        database = RegistryDatabase(path)
        self.assertEqual(database.initialize(), SCHEMA_VERSION)
        with database.read_connection() as db:
            self.assertEqual(db.execute("SELECT model_id FROM models").fetchone()[0], "OLD-MODEL")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"evaluation_track_audits", "evaluation_track_audit_decisions",
                             "evaluation_track_audit_state"}.issubset(tables))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_deleting_draft_cascades_audits_and_decisions(self):
        self.applied()
        self.f.service.delete_draft(self.f.track)
        with self.f.repo.database.read_connection() as db:
            for table in ("evaluation_track_audits", "evaluation_track_audit_decisions", "evaluation_track_audit_state"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()

