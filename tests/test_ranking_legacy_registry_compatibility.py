import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.ranking.legacy_compatibility import (
    EVIDENCE_CONTROLLED,
    EVIDENCE_CONTROLLED_LEGACY,
    EVIDENCE_LEGACY,
    EVIDENCE_MISMATCH,
    EVIDENCE_ORPHANED,
    EVIDENCE_REGISTERED_INCOMPLETE,
    EVIDENCE_WORKING,
)
from auto_annotation_tool.ranking.model_ranking import (
    ModelRanking,
    ModelRankingEntry,
)
from auto_annotation_tool.registry import RegistryRepository


class RankingLegacyRegistryCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.ranking_dir = self.workspace / "7_rankings" / "plates"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()

        for model_id, char in (
            ("MODEL-A", "a"),
            ("MODEL-B", "b"),
        ):
            self.repo.upsert_model_location(
                model_id=model_id,
                sha256=char * 64,
                project_id=None,
                run_id=None,
                target="plate",
                task_type="pose",
                yolo_family="yolo11",
                yolo_scale=char,
                checkpoint_kind="trained_export",
                provenance_status="complete",
                created_at="2026-01-01T00:00:00",
                location_key=model_id,
                relative_path=f"6_models/{model_id}.pt",
                external_path=None,
                is_primary=True,
            )

    def tearDown(self):
        self.temp.cleanup()

    def _protocol(self, *, final_contract=True):
        track = {
            "track_id": "TRK-1",
            "manual_gt_complete": bool(final_contract),
            "manual_gt_attested_at": (
                "2026-09-12T10:00:00+00:00"
                if final_contract
                else ""
            ),
            "manual_gt_attestation_schema": (
                "alpr.gt_completeness_attestation.v1"
                if final_contract
                else ""
            ),
            "manual_gt_attestation_statement": (
                "checked"
                if final_contract
                else ""
            ),
        }
        return {
            "schema": "alpr.experiment_protocol.v1",
            "track": track,
            "options": {
                "require_manual_gt_complete": bool(
                    final_contract
                ),
            },
        }

    def _registry_result(
        self,
        *,
        experiment_id="EXP-1",
        model_id="MODEL-A",
        mode="controlled",
        status="COMPLETED",
        independence="PASS",
        final_contract=True,
        result_schema="alpr.ranking_experiment_result.v1",
        entry_overrides=None,
    ):
        protocol = self._protocol(
            final_contract=final_contract
        )
        protocol_json = json.dumps(
            protocol,
            sort_keys=True,
        )
        protocol_sha = (
            "c" * 64
            if final_contract
            else "d" * 64
        )
        model = self.repo.get_model(model_id)
        model_sha = str(model["sha256"])

        self.repo.create_experiment_bundle(
            experiment={
                "experiment_id": experiment_id,
                "owner_project_id": None,
                "name": experiment_id,
                "target": "plate",
                "mode": mode,
                "track_id": None,
                "status": status,
                "protocol_json": protocol_json,
                "protocol_sha256": protocol_sha,
                "track_manifest_sha256": "e" * 64,
                "created_at": "2026-09-12T10:00:00+00:00",
                "sealed_at": "2026-09-12T10:00:00+00:00",
                "started_at": "2026-09-12T10:01:00+00:00",
                "finished_at": (
                    "2026-09-12T10:02:00+00:00"
                    if status == "COMPLETED"
                    else None
                ),
            },
            participants=[
                {
                    "model_id": model_id,
                    "position": 0,
                    "model_sha256": model_sha,
                    "independence_status": independence,
                    "overlap_count": 0,
                }
            ],
            overlaps=[],
        )

        entry = {
            "model_name": f"{model_id}.pt",
            "model_path": str(
                self.workspace
                / "6_models"
                / f"{model_id}.pt"
            ),
            "date_evaluated": "2026-09-12T10:02:00+00:00",
            "reference_name": "track",
            "reference_path": str(
                self.workspace / "10_evaluation_tracks" / "track"
            ),
            "task_type": "Tablice (Pose)",
            "precision": 90,
            "recall": 80,
            "experiment_id": experiment_id,
            "experiment_mode": mode,
            "model_id": model_id,
            "model_sha256": model_sha,
            "track_id": "",
            "protocol_sha256": protocol_sha,
            "track_manifest_sha256": "e" * 64,
            "independence_status": independence,
            "comparison_scope": "Globalne",
        }
        entry.update(entry_overrides or {})
        metrics = {
            "schema": result_schema,
            "ranking_entry": entry,
        }
        self.repo.upsert_experiment_result(
            experiment_id=experiment_id,
            model_id=model_id,
            metrics_json=json.dumps(metrics),
            result_relative_path=(
                "7_rankings/plates/model_ranking.json"
            ),
            created_at="2026-09-12T10:02:00+00:00",
        )
        return entry

    def _reconcile(self, entries):
        ranking = ModelRanking(self.ranking_dir)
        ranking.entries = list(entries)
        report = ranking.reconcile_registry(
            self.repo,
            target="plate",
        )
        return ranking, report

    def test_plain_legacy_entry_is_never_promoted(self):
        legacy = ModelRankingEntry(
            model_name="legacy.pt",
            model_path="legacy.pt",
            date_evaluated="2025-01-01T00:00:00",
            precision=50,
            recall=50,
        )
        ranking, report = self._reconcile([legacy])

        self.assertEqual(len(ranking.entries), 1)
        self.assertEqual(
            ranking.entries[0].evidence_status,
            EVIDENCE_LEGACY,
        )
        self.assertEqual(report.legacy_entries, 1)

    def test_completed_final_controlled_result_is_recovered_from_sqlite(self):
        self._registry_result()
        ranking, report = self._reconcile([])

        self.assertEqual(report.recovered_entries, 1)
        self.assertEqual(len(ranking.entries), 1)
        entry = ranking.entries[0]
        self.assertEqual(
            entry.evidence_status,
            EVIDENCE_CONTROLLED,
        )
        self.assertEqual(entry.experiment_id, "EXP-1")
        self.assertEqual(entry.model_id, "MODEL-A")

    def test_old_registered_controlled_protocol_is_not_final_controlled(self):
        self._registry_result(final_contract=False)
        ranking, _report = self._reconcile([])

        self.assertEqual(
            ranking.entries[0].evidence_status,
            EVIDENCE_CONTROLLED_LEGACY,
        )

    def test_working_result_stays_working(self):
        self._registry_result(
            mode="working",
            independence="UNKNOWN",
        )
        ranking, _report = self._reconcile([])

        self.assertEqual(
            ranking.entries[0].evidence_status,
            EVIDENCE_WORKING,
        )

    def test_noncompleted_registered_result_is_flagged(self):
        self._registry_result(status="FAILED")
        ranking, _report = self._reconcile([])

        self.assertEqual(
            ranking.entries[0].evidence_status,
            EVIDENCE_REGISTERED_INCOMPLETE,
        )

    def test_orphaned_experiment_id_is_visible(self):
        entry = ModelRankingEntry(
            model_name="orphan.pt",
            model_path="orphan.pt",
            date_evaluated="2026-01-01T00:00:00",
            experiment_id="EXP-MISSING",
            model_id="MODEL-A",
        )
        ranking, report = self._reconcile([entry])

        self.assertEqual(
            ranking.entries[0].evidence_status,
            EVIDENCE_ORPHANED,
        )
        self.assertEqual(report.orphaned_entries, 1)

    def test_metadata_mismatch_is_not_silently_hydrated(self):
        payload = self._registry_result()
        entry = ModelRankingEntry.from_dict(payload)
        entry.protocol_sha256 = "f" * 64

        ranking, report = self._reconcile([entry])

        self.assertEqual(
            ranking.entries[0].evidence_status,
            EVIDENCE_MISMATCH,
        )
        self.assertEqual(report.mismatched_entries, 1)

    def test_missing_registry_metadata_is_hydrated(self):
        payload = self._registry_result()
        entry = ModelRankingEntry.from_dict(payload)
        entry.model_sha256 = ""
        entry.protocol_sha256 = ""
        entry.track_manifest_sha256 = ""

        ranking, _report = self._reconcile([entry])
        hydrated = ranking.entries[0]

        self.assertEqual(hydrated.model_sha256, "a" * 64)
        self.assertEqual(hydrated.protocol_sha256, "c" * 64)
        self.assertEqual(
            hydrated.track_manifest_sha256,
            "e" * 64,
        )
        self.assertEqual(
            hydrated.evidence_status,
            EVIDENCE_CONTROLLED,
        )

    def test_nonranking_experiment_result_is_not_imported(self):
        self._registry_result(
            result_schema="other.result.v1",
        )
        ranking, report = self._reconcile([])

        self.assertEqual(ranking.entries, [])
        self.assertEqual(report.recovered_entries, 0)

    def test_registered_evidence_wins_identity_dedup_over_legacy(self):
        self._registry_result()
        legacy = ModelRankingEntry(
            model_name="MODEL-A.pt",
            model_path=str(
                self.workspace
                / "6_models"
                / "MODEL-A.pt"
            ),
            date_evaluated="2099-01-01T00:00:00",
            reference_name="track",
            reference_path=str(
                self.workspace
                / "10_evaluation_tracks"
                / "track"
            ),
            task_type="Tablice (Pose)",
            precision=1,
            recall=1,
            comparison_scope="Globalne",
        )
        ranking, _report = self._reconcile([legacy])

        self.assertEqual(len(ranking.entries), 1)
        self.assertEqual(
            ranking.entries[0].evidence_status,
            EVIDENCE_CONTROLLED,
        )


if __name__ == "__main__":
    unittest.main()
