import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.experiment_service import (
    ExperimentGuardError,
    ExperimentService,
)
from auto_annotation_tool.registry.independence_service import (
    INDEPENDENCE_PASS,
)
from auto_annotation_tool.registry.track_service import (
    EvaluationTrackService,
)


class _Audit:
    def __init__(self, model_id, sha256, track_id):
        self.status = INDEPENDENCE_PASS
        self.model_id = model_id
        self.model_sha256 = sha256
        self.track_id = track_id
        self.track_manifest_sha256 = "a" * 64
        self.track_reference_sha256 = "b" * 64
        self.checked_run_ids = ()
        self.checked_dataset_ids = ()
        self.overlaps = ()
        self.unknown_reasons = ()
        self.audited_at = "2026-01-01T00:00:00+00:00"

    @property
    def overlap_count(self):
        return 0


class _FakeIndependence:
    def __init__(self, repo, track_id):
        self.repo = repo
        self.track_id = track_id

    def audit(self, model_id, track_id):
        row = self.repo.get_model(model_id)
        return _Audit(
            model_id,
            str(row["sha256"]),
            track_id,
        )


class PoseCornerExperimentProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()
        self.tracks = EvaluationTrackService(
            self.workspace,
            repository=self.repo,
        )
        for model_id, char in (("MODEL-A", "a"), ("MODEL-B", "b")):
            self.repo.upsert_model_location(
                model_id=model_id,
                sha256=char * 64,
                project_id=None,
                run_id=None,
                target="plate",
                task_type="pose",
                yolo_family="yolo11",
                yolo_scale="n",
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

    def _sealed_track(self, *, polygon=True):
        image = Path(self.temp.name) / "one.jpg"
        image.write_bytes(b"image")
        gt = Path(self.temp.name) / "gt.xml"
        shape = (
            '<polygon label="plate" points="0,0;10,0;10,10;0,10"/>'
            if polygon
            else '<box label="plate" xtl="0" ytl="0" xbr="10" ybr="10"/>'
        )
        gt.write_text(
            (
                "<annotations>"
                '<image id="0" name="one.jpg" width="100" height="50">'
                + shape
                + "</image></annotations>"
            ),
            encoding="utf-8",
        )
        track_id = self.tracks.create_draft(
            name="E1A",
            target="plate",
            purpose="final_test",
        )
        self.tracks.add_member(track_id, image)
        self.tracks.set_ground_truth(track_id, gt)
        self.tracks.verify(
            track_id,
            manual_gt_complete=True,
        )
        self.tracks.seal(track_id)
        return track_id

    def _service(self, track_id):
        return ExperimentService(
            self.workspace,
            repository=self.repo,
            track_service=self.tracks,
            independence_service=_FakeIndependence(
                self.repo,
                track_id,
            ),
        )

    def test_require_pose_corners_is_frozen_in_protocol(self):
        track_id = self._sealed_track(polygon=True)
        service = self._service(track_id)
        plan = service.create(
            name="E1A MT-n vs MT-s",
            target="plate",
            track_id=track_id,
            model_ids=("MODEL-A", "MODEL-B"),
            protocol_options={
                "require_pose_corners": True,
            },
        )
        row = self.repo.get_experiment(plan.experiment_id)
        protocol = json.loads(row["protocol_json"])
        self.assertTrue(protocol["options"]["require_pose_corners"])
        self.assertTrue(protocol["track"]["pose_corner_ready"])
        self.assertEqual(
            protocol["track"]["pose_corner_order"],
            "tl_tr_br_bl",
        )

    def test_require_pose_corners_blocks_box_only_track(self):
        track_id = self._sealed_track(polygon=False)
        service = self._service(track_id)
        with self.assertRaises(ExperimentGuardError):
            service.create(
                name="blocked",
                target="plate",
                track_id=track_id,
                model_ids=("MODEL-A", "MODEL-B"),
                protocol_options={
                    "require_pose_corners": True,
                },
            )


if __name__ == "__main__":
    unittest.main()
