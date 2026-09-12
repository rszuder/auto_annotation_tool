import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.experiment_service import (
    ExperimentGuardError,
    ExperimentService,
    MODE_CONTROLLED,
    MODE_WORKING,
    STATUS_COMPLETED,
    STATUS_READY,
    STATUS_READY_WITH_WARNINGS,
    STATUS_RUNNING,
)
from auto_annotation_tool.registry.independence_service import (
    INDEPENDENCE_FAIL,
    INDEPENDENCE_PASS,
    INDEPENDENCE_UNKNOWN,
)
from auto_annotation_tool.registry.track_service import EvaluationTrackService


def _gt(path: Path, image_name: str) -> None:
    path.write_text(
        (
            "<annotations>"
            f'<image id="0" name="{image_name}" width="100" height="50">'
            '<box label="plate" xtl="0" ytl="0" xbr="10" ybr="10"/>'
            "</image></annotations>"
        ),
        encoding="utf-8",
    )


class _Audit:
    def __init__(
        self,
        *,
        model_id,
        status,
        model_sha256,
        track_id,
        overlaps=(),
        unknown_reasons=(),
    ):
        self.status = status
        self.model_id = model_id
        self.model_sha256 = model_sha256
        self.track_id = track_id
        self.track_manifest_sha256 = "a" * 64
        self.track_reference_sha256 = "b" * 64
        self.checked_run_ids = (f"RUN-{model_id}",)
        self.checked_dataset_ids = (f"DS-{model_id}",)
        self.overlaps = tuple(overlaps)
        self.unknown_reasons = tuple(unknown_reasons)
        self.audited_at = "2026-01-01T00:00:00+00:00"

    @property
    def overlap_count(self):
        return len(self.overlaps)


class _Overlap:
    def __init__(self, model_id, source_image_id):
        self.source_image_id = source_image_id
        self.track_member_index = 0
        self.track_original_name = "one.jpg"
        self.training_run_id = f"RUN-{model_id}"
        self.training_dataset_id = f"DS-{model_id}"
        self.training_split = "train"
        self.dataset_relative_path = "images/train/one.jpg"
        self.ancestor_depth = 0
        self.reason = "source_image_id"


class _FakeIndependence:
    def __init__(self, audits):
        self.audits = dict(audits)

    def audit(self, model_id, track_id):
        return self.audits[model_id]


class ExperimentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()
        self.track_service = EvaluationTrackService(
            self.workspace,
            repository=self.repo,
        )
        self.track_id = self._sealed_track()

        for model_id in ("MODEL-A", "MODEL-B", "MODEL-C"):
            self.repo.upsert_model_location(
                model_id=model_id,
                sha256=(model_id[-1].lower() * 64),
                project_id=None,
                run_id=None,
                target="plate",
                task_type="pose",
                yolo_family="yolo11",
                yolo_scale="n",
                checkpoint_kind="trained_export",
                provenance_status="complete",
                created_at="2026-01-01T00:00:00",
                location_key="test",
                relative_path=f"6_models/{model_id}.pt",
                external_path=None,
                is_primary=True,
            )

    def tearDown(self):
        self.temp.cleanup()

    def _sealed_track(self):
        image = Path(self.temp.name) / "one.jpg"
        image.write_bytes(b"track")
        gt = Path(self.temp.name) / "gt.xml"
        _gt(gt, image.name)

        track_id = self.track_service.create_draft(
            name="experiment-track",
            target="plate",
            purpose="final_test",
            reservation_policy="reserve_from_training",
        )
        self.track_service.add_member(track_id, image)
        self.track_service.set_ground_truth(track_id, gt)
        self.track_service.verify(track_id)
        self.track_service.seal(track_id)
        return track_id

    def _service(self, statuses):
        audits = {}
        track_source_id = self.track_service.list_members(
            self.track_id
        )[0]["source_image_id"]
        for model_id, status in statuses.items():
            overlaps = (
                (_Overlap(model_id, track_source_id),)
                if status == INDEPENDENCE_FAIL
                else ()
            )
            unknown = (
                ("provenance niepełne",)
                if status == INDEPENDENCE_UNKNOWN
                else ()
            )
            model = self.repo.get_model(model_id)
            audits[model_id] = _Audit(
                model_id=model_id,
                status=status,
                model_sha256=str(model["sha256"]),
                track_id=self.track_id,
                overlaps=overlaps,
                unknown_reasons=unknown,
            )

        return ExperimentService(
            self.workspace,
            repository=self.repo,
            track_service=self.track_service,
            independence_service=_FakeIndependence(audits),
        )

    def test_controlled_all_pass_creates_ready_experiment(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_PASS,
            }
        )
        plan = service.create(
            name="E1A MT-n vs MT-s",
            target="plate",
            track_id=self.track_id,
            model_ids=("MODEL-A", "MODEL-B"),
            mode=MODE_CONTROLLED,
            protocol_options={"metric": "mAP"},
        )

        self.assertEqual(plan.status, STATUS_READY)
        self.assertTrue(plan.controlled_ready)
        self.assertTrue(plan.independence_confirmed)
        self.assertEqual(len(plan.protocol_sha256), 64)

        row = self.repo.get_experiment(plan.experiment_id)
        self.assertEqual(row["mode"], MODE_CONTROLLED)
        self.assertEqual(row["status"], STATUS_READY)
        self.assertEqual(
            row["track_manifest_sha256"],
            plan.track_manifest_sha256,
        )

        participants = self.repo.list_experiment_participants(
            plan.experiment_id
        )
        self.assertEqual(
            [row["model_id"] for row in participants],
            ["MODEL-A", "MODEL-B"],
        )
        self.assertTrue(
            all(
                row["independence_status"] == INDEPENDENCE_PASS
                for row in participants
            )
        )

    def test_controlled_unknown_blocks_and_writes_nothing(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_UNKNOWN,
            }
        )
        with self.assertRaises(ExperimentGuardError):
            service.create(
                name="blocked",
                target="plate",
                track_id=self.track_id,
                model_ids=("MODEL-A", "MODEL-B"),
                mode=MODE_CONTROLLED,
            )

        self.assertEqual(
            self.repo.table_count("experiments"),
            0,
        )

    def test_controlled_fail_blocks_and_writes_nothing(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_FAIL,
            }
        )
        with self.assertRaises(ExperimentGuardError):
            service.create(
                name="blocked",
                target="plate",
                track_id=self.track_id,
                model_ids=("MODEL-A", "MODEL-B"),
                mode=MODE_CONTROLLED,
            )
        self.assertEqual(
            self.repo.table_count("experiments"),
            0,
        )

    def test_working_unknown_is_allowed_with_warning(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_UNKNOWN,
            }
        )
        plan = service.create(
            name="working",
            target="plate",
            track_id=self.track_id,
            model_ids=("MODEL-A", "MODEL-B"),
            mode=MODE_WORKING,
        )
        self.assertEqual(
            plan.status,
            STATUS_READY_WITH_WARNINGS,
        )
        self.assertFalse(plan.independence_confirmed)
        self.assertTrue(plan.warnings)

        row = self.repo.get_experiment(plan.experiment_id)
        protocol = json.loads(row["protocol_json"])
        self.assertFalse(protocol["independence_confirmed"])
        self.assertEqual(
            protocol["participants"][1]["independence_status"],
            INDEPENDENCE_UNKNOWN,
        )

    def test_working_fail_is_blocked_and_writes_nothing(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_FAIL,
            }
        )
        with self.assertRaises(ExperimentGuardError):
            service.create(
                name="working-overlap",
                target="plate",
                track_id=self.track_id,
                model_ids=("MODEL-A", "MODEL-B"),
                mode=MODE_WORKING,
            )
        self.assertEqual(
            self.repo.table_count("experiments"),
            0,
        )

    def test_draft_track_cannot_be_used(self):
        draft = self.track_service.create_draft(
            name="draft",
            target="plate",
            purpose="final_test",
        )
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_PASS,
            }
        )
        with self.assertRaises(ExperimentGuardError):
            service.create(
                name="bad track",
                target="plate",
                track_id=draft,
                model_ids=("MODEL-A", "MODEL-B"),
            )

    def test_tampered_track_cannot_be_used(self):
        track = self.track_service.get_track(self.track_id)
        root = self.workspace / track["relative_path"]
        (root / "images" / "one.jpg").write_bytes(b"tampered")

        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_PASS,
            }
        )
        with self.assertRaises(ExperimentGuardError):
            service.create(
                name="tampered",
                target="plate",
                track_id=self.track_id,
                model_ids=("MODEL-A", "MODEL-B"),
            )

    def test_two_distinct_models_are_required(self):
        service = self._service(
            {"MODEL-A": INDEPENDENCE_PASS}
        )
        with self.assertRaises(ExperimentGuardError):
            service.create(
                name="one",
                target="plate",
                track_id=self.track_id,
                model_ids=("MODEL-A", "MODEL-A"),
            )

    def test_protocol_hash_changes_with_protocol_options(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_PASS,
            }
        )
        first = service.create(
            name="first",
            target="plate",
            track_id=self.track_id,
            model_ids=("MODEL-A", "MODEL-B"),
            protocol_options={"imgsz": 640},
        )
        second = service.create(
            name="second",
            target="plate",
            track_id=self.track_id,
            model_ids=("MODEL-A", "MODEL-B"),
            protocol_options={"imgsz": 960},
        )
        self.assertNotEqual(
            first.protocol_sha256,
            second.protocol_sha256,
        )

    def test_participant_model_sha_is_frozen(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_PASS,
            }
        )
        plan = service.create(
            name="sha snapshot",
            target="plate",
            track_id=self.track_id,
            model_ids=("MODEL-A", "MODEL-B"),
        )
        rows = self.repo.list_experiment_participants(
            plan.experiment_id
        )
        self.assertEqual(rows[0]["model_sha256"], "a" * 64)
        self.assertEqual(rows[1]["model_sha256"], "b" * 64)

    def test_start_record_results_and_finish_lifecycle(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_PASS,
            }
        )
        plan = service.create(
            name="lifecycle",
            target="plate",
            track_id=self.track_id,
            model_ids=("MODEL-A", "MODEL-B"),
        )

        service.start(plan.experiment_id)
        self.assertEqual(
            service.get_experiment(plan.experiment_id)["status"],
            STATUS_RUNNING,
        )

        service.record_result(
            plan.experiment_id,
            "MODEL-A",
            metrics={"mAP50": 0.75, "samples": 10},
            result_relative_path="7_rankings/a.json",
        )
        result = self.repo.get_experiment_result(
            plan.experiment_id,
            "MODEL-A",
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            json.loads(result["metrics_json"])["samples"],
            10,
        )

        service.finish(plan.experiment_id)
        self.assertEqual(
            service.get_experiment(plan.experiment_id)["status"],
            STATUS_COMPLETED,
        )

    def test_result_for_non_participant_is_rejected(self):
        service = self._service(
            {
                "MODEL-A": INDEPENDENCE_PASS,
                "MODEL-B": INDEPENDENCE_PASS,
            }
        )
        plan = service.create(
            name="result guard",
            target="plate",
            track_id=self.track_id,
            model_ids=("MODEL-A", "MODEL-B"),
        )
        service.start(plan.experiment_id)
        with self.assertRaises(ExperimentGuardError):
            service.record_result(
                plan.experiment_id,
                "MODEL-C",
                metrics={"x": 1},
            )


if __name__ == "__main__":
    unittest.main()
