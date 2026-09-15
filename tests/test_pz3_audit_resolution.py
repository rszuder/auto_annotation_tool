import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from auto_annotation_tool.registry.audit_resolution import resolve_audit
from auto_annotation_tool.registry.participant_pool_audit import (
    AUDIT_SCHEMA, CandidateVerdict, ParticipantPoolAuditReport,
    STATUS_CLEAN, STATUS_DEPENDENT, STATUS_SUSPECT, STATUS_UNKNOWN,
)


def report_for(statuses):
    candidates = tuple(CandidateVerdict(str(Path(f"IMG_{i:03d}.png")), f"IMG_{i:03d}.png",
                                       f"{i:064x}", "", status, ())
                       for i, status in enumerate(statuses))
    return ParticipantPoolAuditReport(
        AUDIT_SCHEMA, "TRACK", "participants", (), candidates,
        statuses.count(STATUS_DEPENDENT), statuses.count(STATUS_SUSPECT),
        statuses.count(STATUS_CLEAN), statuses.count(STATUS_UNKNOWN), "2026-09-14T12:00:00+00:00",
    )


class AuditResolutionTests(unittest.TestCase):
    def test_clean_is_accepted(self):
        result = resolve_audit(report_for([STATUS_CLEAN]))
        self.assertEqual(result.accepted_paths, (Path("IMG_000.png"),))
        self.assertTrue(result.ready)

    def test_dependent_and_unknown_are_always_rejected(self):
        result = resolve_audit(report_for([STATUS_DEPENDENT, STATUS_UNKNOWN]))
        self.assertEqual(len(result.rejected_dependent), 1)
        self.assertEqual(len(result.rejected_unknown), 1)
        self.assertEqual(result.accepted_paths, ())

    def test_suspect_needs_an_explicit_decision(self):
        result = resolve_audit(report_for([STATUS_SUSPECT]))
        self.assertEqual(len(result.unresolved), 1)
        self.assertFalse(result.ready)
        with self.assertRaises(ValueError):
            result.validate()

    def test_accept_and_reject_suspects_individually(self):
        report = report_for([STATUS_SUSPECT, STATUS_SUSPECT])
        result = resolve_audit(report, {report.candidates[0].path: "accept",
                                        report.candidates[1].path: "reject"})
        self.assertEqual(len(result.accepted_suspects), 1)
        self.assertEqual(len(result.rejected_suspects), 1)
        self.assertTrue(result.ready)

    def test_cancel_is_never_applicable(self):
        result = resolve_audit(report_for([STATUS_CLEAN]), cancelled=True)
        self.assertFalse(result.ready)
        with self.assertRaises(ValueError):
            result.validate()

    def test_partial_ingest_yields_exactly_eleven_paths(self):
        report = report_for([STATUS_CLEAN] * 10 + [STATUS_DEPENDENT] * 3
                            + [STATUS_UNKNOWN] * 2 + [STATUS_SUSPECT] * 2)
        result = resolve_audit(report, {report.candidates[-2].path: "accept",
                                        report.candidates[-1].path: "reject"})
        result.validate()
        self.assertEqual(len(result.accepted_paths), 11)
        self.assertEqual(len(result.rejected_paths), 6)

    def test_operator_cannot_override_unknown_or_dependency(self):
        for status in (STATUS_DEPENDENT, STATUS_UNKNOWN):
            report = report_for([status])
            with self.assertRaises(ValueError):
                resolve_audit(report, {report.candidates[0].path: "accept"})

    def test_forged_resolution_does_not_bypass_validation(self):
        result = resolve_audit(report_for([STATUS_DEPENDENT]))
        forged = replace(result, accepted_clean=result.rejected_dependent, rejected_dependent=())
        with self.assertRaises(ValueError):
            forged.validate()

    def test_resolution_records_operator_actions(self):
        report = report_for([STATUS_CLEAN, STATUS_DEPENDENT, STATUS_UNKNOWN, STATUS_SUSPECT, STATUS_SUSPECT])
        result = resolve_audit(report, {report.candidates[-2].path: "accept", report.candidates[-1].path: "reject"})
        self.assertEqual([row["decision"] for row in result.decision_rows()],
                         ["accept_clean", "reject_dependent", "reject_unknown",
                          "manual_accept_suspect", "manual_reject_suspect"])


if __name__ == "__main__":
    unittest.main()
