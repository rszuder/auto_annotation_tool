import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.independence_service import (
    INDEPENDENCE_FAIL,
    INDEPENDENCE_PASS,
    INDEPENDENCE_UNKNOWN,
    ModelTrackIndependenceService,
)
from auto_annotation_tool.registry.track_service import (
    EvaluationTrackError,
    EvaluationTrackService,
    INDEPENDENT_ACQUISITION_ATTESTATION_SCHEMA,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


class IndependentAcquisitionAttestationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()
        self.tracks = EvaluationTrackService(
            self.workspace,
            repository=self.repo,
        )
        self.audit = ModelTrackIndependenceService(
            self.workspace,
            repository=self.repo,
            track_service=self.tracks,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _track(self, *, attest: bool, payload: bytes = b"track-image"):
        image = Path(self.temp.name) / "track.jpg"
        image.write_bytes(payload)
        gt = Path(self.temp.name) / "gt.xml"
        _gt(gt, image.name)

        track_id = self.tracks.create_draft(
            name="E1A independent",
            target="plate",
            purpose="final_test",
            reservation_policy="reserve_from_training",
        )
        self.tracks.add_member(track_id, image)
        self.tracks.set_ground_truth(track_id, gt)
        self.tracks.verify(track_id, manual_gt_complete=True)
        if attest:
            self.tracks.attest_independent_acquisition(
                track_id,
                source_pool="new_independent_acquisition",
            )
        self.tracks.seal(track_id)
        return track_id, self.tracks.list_members(track_id)[0]

    def _dataset(self, dataset_id: str, *, train_sha: str) -> None:
        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    dataset_id, target, name, purpose, provenance_status
                ) VALUES (?, 'plate', ?, 'training', 'complete')
                """,
                (dataset_id, dataset_id),
            )
            for split, suffix in (("train", "T"), ("val", "V")):
                source_id = f"SRC-{dataset_id}-{suffix}"
                file_sha = (
                    train_sha
                    if split == "train"
                    else _sha(f"{dataset_id}-val".encode("utf-8"))
                )
                existing_source = connection.execute(
                    """
                    SELECT source_image_id
                    FROM source_images
                    WHERE canonical_sha256 = ?
                    """,
                    (file_sha,),
                ).fetchone()
                if existing_source is not None:
                    source_id = str(existing_source[0])
                else:
                    connection.execute(
                        """
                        INSERT INTO source_images (
                            source_image_id, canonical_sha256, origin_status
                        ) VALUES (?, ?, 'exact_hash_only')
                        """,
                        (source_id, file_sha),
                    )
                artifact_id = f"ART-{dataset_id}-{suffix}"
                relative_path = f"images/{split}/{suffix}.jpg"
                connection.execute(
                    """
                    INSERT INTO image_artifacts (
                        artifact_id, source_image_id, relative_path,
                        sha256, size_bytes, kind
                    ) VALUES (?, ?, ?, ?, 1, 'dataset_image')
                    """,
                    (
                        artifact_id,
                        source_id,
                        relative_path,
                        file_sha,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO dataset_members (
                        dataset_id, artifact_id, source_image_id,
                        split, relative_path, file_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_id,
                        artifact_id,
                        source_id,
                        split,
                        relative_path,
                        file_sha,
                    ),
                )

    def _model(self, dataset_id: str) -> str:
        run_id = f"RUN-{dataset_id}"
        model_id = f"MODEL-{dataset_id}"
        self.repo.upsert_training_run(
            run_id=run_id,
            project_id=None,
            target="plate",
            dataset_id=dataset_id,
            status="completed",
            base_model="yolo26n-pose.pt",
            config_sha256="cfg",
            output_relative_path=f"5_training_runs/{run_id}",
            started_at="2026-01-01T00:00:00",
            finished_at="2026-01-01T00:01:00",
            provenance_status="complete",
        )
        self.repo.upsert_model_location(
            model_id=model_id,
            sha256=_sha(model_id.encode("utf-8")),
            project_id=None,
            run_id=run_id,
            target="plate",
            task_type="pose",
            yolo_family="YOLO26",
            yolo_scale="n",
            checkpoint_kind="trained_export",
            provenance_status="complete",
            created_at="2026-01-01T00:01:00",
            location_key="test",
            relative_path=f"6_models/{model_id}.pt",
            external_path=None,
            is_primary=True,
        )
        return model_id

    def test_attestation_is_frozen_in_controlled_reference(self):
        track_id, _member = self._track(attest=True)

        reference = self.tracks.build_controlled_reference(track_id)

        self.assertTrue(reference.independent_acquisition)
        self.assertTrue(reference.not_derived_from_training_data)
        self.assertEqual(
            reference.acquisition_source_pool,
            "new_independent_acquisition",
        )
        self.assertTrue(reference.independent_acquisition_attested_at)
        self.assertEqual(
            reference.independent_acquisition_attestation_schema,
            INDEPENDENT_ACQUISITION_ATTESTATION_SCHEMA,
        )
        with self.assertRaises(EvaluationTrackError):
            self.tracks.attest_independent_acquisition(track_id)

    def test_exact_hash_only_without_attestation_remains_unknown(self):
        track_id, _member = self._track(attest=False)
        self._dataset(
            "DS-NO-ATTEST",
            train_sha=_sha(b"different-training-image"),
        )
        model_id = self._model("DS-NO-ATTEST")

        result = self.audit.audit(model_id, track_id)

        self.assertEqual(result.status, INDEPENDENCE_UNKNOWN)
        self.assertTrue(result.unknown_reasons)

    def test_attestation_allows_pass_when_sha_has_no_overlap(self):
        track_id, _member = self._track(attest=True)
        self._dataset(
            "DS-ATTEST-CLEAN",
            train_sha=_sha(b"different-training-image"),
        )
        model_id = self._model("DS-ATTEST-CLEAN")

        result = self.audit.audit(model_id, track_id)

        self.assertEqual(result.status, INDEPENDENCE_PASS)
        self.assertEqual(result.unknown_reasons, ())
        self.assertIn(
            "sealed_independent_acquisition_attestation",
            result.evidence_basis,
        )

    def test_exact_sha_overlap_still_fails_despite_attestation(self):
        track_id, member = self._track(attest=True)
        self._dataset(
            "DS-ATTEST-OVERLAP",
            train_sha=str(member["sha256"]),
        )
        model_id = self._model("DS-ATTEST-OVERLAP")

        result = self.audit.audit(model_id, track_id)

        self.assertEqual(result.status, INDEPENDENCE_FAIL)
        self.assertEqual(result.overlap_count, 1)


if __name__ == "__main__":
    unittest.main()
