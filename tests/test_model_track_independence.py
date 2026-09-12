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
from auto_annotation_tool.registry.track_service import EvaluationTrackService


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


class ModelTrackIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()
        self.track_service = EvaluationTrackService(
            self.workspace,
            repository=self.repo,
        )
        self.audit = ModelTrackIndependenceService(
            self.workspace,
            repository=self.repo,
            track_service=self.track_service,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _sealed_track(
        self,
        *,
        payload: bytes = b"track",
        name: str = "track.jpg",
        lineage_status: str = "known",
    ):
        image = Path(self.temp.name) / name
        image.write_bytes(payload)
        gt = Path(self.temp.name) / "gt.xml"
        _gt(gt, name)

        track_id = self.track_service.create_draft(
            name="audit-track",
            target="plate",
            purpose="final_test",
            reservation_policy="reserve_from_training",
        )
        self.track_service.add_member(track_id, image)
        self.track_service.set_ground_truth(track_id, gt)
        self.track_service.verify(track_id)
        self.track_service.seal(track_id)

        member = self.track_service.list_members(track_id)[0]
        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                UPDATE source_images
                SET origin_status = ?
                WHERE source_image_id = ?
                """,
                (lineage_status, member["source_image_id"]),
            )
        return track_id, member

    def _dataset(
        self,
        dataset_id: str,
        members: list[dict],
        *,
        provenance_status: str = "complete",
    ):
        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    dataset_id, target, name, purpose, provenance_status
                ) VALUES (?, 'plate', ?, 'training', ?)
                """,
                (dataset_id, dataset_id, provenance_status),
            )
            for index, item in enumerate(members):
                source_id = item["source_image_id"]
                origin_status = item.get("origin_status", "known")
                payload = item.get(
                    "payload",
                    f"{dataset_id}-{index}".encode("utf-8"),
                )
                file_sha = item.get("file_sha256") or _sha(payload)
                canonical_sha = item.get("canonical_sha256") or _sha(
                    b"canonical-" + payload
                )
                connection.execute(
                    """
                    INSERT INTO source_images (
                        source_image_id, canonical_sha256, origin_status
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(source_image_id) DO UPDATE SET
                        origin_status = excluded.origin_status
                    """,
                    (source_id, canonical_sha, origin_status),
                )
                artifact_id = f"ART-{dataset_id}-{index}"
                connection.execute(
                    """
                    INSERT INTO image_artifacts (
                        artifact_id, source_image_id, relative_path,
                        sha256, size_bytes, kind
                    ) VALUES (?, ?, ?, ?, ?, 'dataset_image')
                    """,
                    (
                        artifact_id,
                        source_id,
                        item.get(
                            "relative_path",
                            f"images/{item.get('split', 'train')}/{index}.jpg",
                        ),
                        file_sha,
                        len(payload),
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
                        item.get("split", "train"),
                        item.get(
                            "relative_path",
                            f"images/{item.get('split', 'train')}/{index}.jpg",
                        ),
                        file_sha,
                    ),
                )

    def _run(
        self,
        run_id: str,
        dataset_id: str | None,
        *,
        parent_run_id: str | None = None,
        provenance_status: str = "complete",
    ):
        self.repo.upsert_training_run(
            run_id=run_id,
            project_id=None,
            target="plate",
            dataset_id=dataset_id,
            status="completed",
            base_model="yolo11n-pose.pt",
            config_sha256="cfg",
            output_relative_path=f"5_training_runs/{run_id}",
            started_at="2026-01-01T00:00:00",
            finished_at="2026-01-01T00:01:00",
            provenance_status=provenance_status,
        )
        if parent_run_id:
            self.repo.set_training_run_parent(run_id, parent_run_id)

    def _model(
        self,
        model_id: str,
        run_id: str | None,
        *,
        provenance_status: str = "complete",
        target: str = "plate",
    ):
        self.repo.upsert_model_location(
            model_id=model_id,
            sha256=_sha(model_id.encode("utf-8")),
            project_id=None,
            run_id=run_id,
            target=target,
            task_type="pose" if target == "plate" else "detect",
            yolo_family="yolo11",
            yolo_scale="n",
            checkpoint_kind="trained_export",
            provenance_status=provenance_status,
            created_at="2026-01-01T00:01:00",
            location_key="test",
            relative_path=f"6_models/{model_id}.pt",
            external_path=None,
            is_primary=True,
        )

    def test_direct_train_overlap_is_fail(self):
        track_id, member = self._sealed_track()
        self._dataset(
            "DS-1",
            [
                {
                    "source_image_id": member["source_image_id"],
                    "split": "train",
                    "origin_status": "known",
                }
            ],
        )
        self._run("RUN-1", "DS-1")
        self._model("MODEL-1", "RUN-1")

        result = self.audit.audit("MODEL-1", track_id)
        self.assertEqual(result.status, INDEPENDENCE_FAIL)
        self.assertEqual(result.overlap_count, 1)
        self.assertEqual(result.overlaps[0].training_split, "train")

    def test_direct_val_overlap_is_fail(self):
        track_id, member = self._sealed_track()
        self._dataset(
            "DS-VAL",
            [
                {
                    "source_image_id": member["source_image_id"],
                    "split": "val",
                    "origin_status": "known",
                }
            ],
        )
        self._run("RUN-VAL", "DS-VAL")
        self._model("MODEL-VAL", "RUN-VAL")

        result = self.audit.audit("MODEL-VAL", track_id)
        self.assertEqual(result.status, INDEPENDENCE_FAIL)
        self.assertEqual(result.overlaps[0].training_split, "val")

    def test_overlap_only_in_test_split_does_not_fail(self):
        track_id, member = self._sealed_track()
        self._dataset(
            "DS-TEST",
            [
                {
                    "source_image_id": member["source_image_id"],
                    "split": "test",
                    "origin_status": "known",
                },
                {
                    "source_image_id": "SRC-TRAIN",
                    "split": "train",
                    "origin_status": "known",
                },
                {
                    "source_image_id": "SRC-VAL",
                    "split": "val",
                    "origin_status": "known",
                },
            ],
        )
        self._run("RUN-TEST", "DS-TEST")
        self._model("MODEL-TEST", "RUN-TEST")

        result = self.audit.audit("MODEL-TEST", track_id)
        self.assertEqual(result.status, INDEPENDENCE_PASS)
        self.assertEqual(result.overlap_count, 0)

    def test_finetune_ancestor_overlap_is_fail(self):
        track_id, member = self._sealed_track()

        self._dataset(
            "DS-PARENT",
            [
                {
                    "source_image_id": member["source_image_id"],
                    "split": "train",
                    "origin_status": "known",
                }
            ],
        )
        self._dataset(
            "DS-CHILD",
            [
                {
                    "source_image_id": "SRC-CHILD",
                    "split": "train",
                    "origin_status": "known",
                },
                {
                    "source_image_id": "SRC-CHILD-VAL",
                    "split": "val",
                    "origin_status": "known",
                },
            ],
        )
        self._run("RUN-PARENT", "DS-PARENT")
        self._run(
            "RUN-CHILD",
            "DS-CHILD",
            parent_run_id="RUN-PARENT",
        )
        self._model("MODEL-CHILD", "RUN-CHILD")

        result = self.audit.audit("MODEL-CHILD", track_id)
        self.assertEqual(result.status, INDEPENDENCE_FAIL)
        self.assertEqual(
            result.checked_run_ids,
            ("RUN-CHILD", "RUN-PARENT"),
        )
        self.assertTrue(
            any(item.ancestor_depth == 1 for item in result.overlaps)
        )

    def test_complete_known_no_overlap_is_pass(self):
        track_id, _member = self._sealed_track()
        self._dataset(
            "DS-CLEAN",
            [
                {
                    "source_image_id": "SRC-CLEAN-TRAIN",
                    "split": "train",
                    "origin_status": "known",
                },
                {
                    "source_image_id": "SRC-CLEAN-VAL",
                    "split": "val",
                    "origin_status": "known",
                },
            ],
        )
        self._run("RUN-CLEAN", "DS-CLEAN")
        self._model("MODEL-CLEAN", "RUN-CLEAN")

        result = self.audit.audit("MODEL-CLEAN", track_id)
        self.assertEqual(result.status, INDEPENDENCE_PASS)
        self.assertTrue(result.independent)
        self.assertEqual(result.unknown_reasons, ())

    def test_exact_hash_only_training_lineage_is_unknown(self):
        track_id, _member = self._sealed_track()
        self._dataset(
            "DS-HASH",
            [
                {
                    "source_image_id": "SRC-HASH-TRAIN",
                    "split": "train",
                    "origin_status": "exact_hash_only",
                },
                {
                    "source_image_id": "SRC-HASH-VAL",
                    "split": "val",
                    "origin_status": "known",
                },
            ],
        )
        self._run("RUN-HASH", "DS-HASH")
        self._model("MODEL-HASH", "RUN-HASH")

        result = self.audit.audit("MODEL-HASH", track_id)
        self.assertEqual(result.status, INDEPENDENCE_UNKNOWN)
        self.assertTrue(result.unknown_reasons)

    def test_exact_hash_only_track_lineage_is_unknown(self):
        track_id, _member = self._sealed_track(
            lineage_status="exact_hash_only"
        )
        self._dataset(
            "DS-CLEAN2",
            [
                {
                    "source_image_id": "SRC-CLEAN2-T",
                    "split": "train",
                    "origin_status": "known",
                },
                {
                    "source_image_id": "SRC-CLEAN2-V",
                    "split": "val",
                    "origin_status": "known",
                },
            ],
        )
        self._run("RUN-CLEAN2", "DS-CLEAN2")
        self._model("MODEL-CLEAN2", "RUN-CLEAN2")

        result = self.audit.audit("MODEL-CLEAN2", track_id)
        self.assertEqual(result.status, INDEPENDENCE_UNKNOWN)

    def test_historical_snapshot_without_members_is_unknown(self):
        track_id, _member = self._sealed_track()
        self.repo.upsert_dataset_snapshot(
            {
                "dataset_id": "DS-SNAPSHOT",
                "target": "plate",
                "name": "snapshot",
                "provenance_status": "complete",
            }
        )
        self._run("RUN-SNAPSHOT", "DS-SNAPSHOT")
        self._model("MODEL-SNAPSHOT", "RUN-SNAPSHOT")

        result = self.audit.audit("MODEL-SNAPSHOT", track_id)
        self.assertEqual(result.status, INDEPENDENCE_UNKNOWN)
        self.assertTrue(
            any(
                "snapshot" in reason.lower()
                or "members" in reason.lower()
                for reason in result.unknown_reasons
            )
        )

    def test_unlinked_legacy_model_is_unknown(self):
        track_id, _member = self._sealed_track()
        self._model(
            "MODEL-LEGACY",
            None,
            provenance_status="legacy_unknown",
        )

        result = self.audit.audit("MODEL-LEGACY", track_id)
        self.assertEqual(result.status, INDEPENDENCE_UNKNOWN)
        self.assertEqual(result.checked_run_ids, ())

    def test_cycle_in_run_ancestry_makes_audit_unknown(self):
        track_id, _member = self._sealed_track()
        self._dataset(
            "DS-CYCLE-A",
            [
                {
                    "source_image_id": "SRC-CYCLE-A-T",
                    "split": "train",
                    "origin_status": "known",
                },
                {
                    "source_image_id": "SRC-CYCLE-A-V",
                    "split": "val",
                    "origin_status": "known",
                },
            ],
        )
        self._dataset(
            "DS-CYCLE-B",
            [
                {
                    "source_image_id": "SRC-CYCLE-B-T",
                    "split": "train",
                    "origin_status": "known",
                },
                {
                    "source_image_id": "SRC-CYCLE-B-V",
                    "split": "val",
                    "origin_status": "known",
                },
            ],
        )
        self._run("RUN-CYCLE-A", "DS-CYCLE-A")
        self._run("RUN-CYCLE-B", "DS-CYCLE-B")
        self.repo.set_training_run_parent("RUN-CYCLE-A", "RUN-CYCLE-B")
        self.repo.set_training_run_parent("RUN-CYCLE-B", "RUN-CYCLE-A")
        self._model("MODEL-CYCLE", "RUN-CYCLE-A")

        result = self.audit.audit("MODEL-CYCLE", track_id)
        self.assertEqual(result.status, INDEPENDENCE_UNKNOWN)
        self.assertTrue(
            any("cykl" in reason.lower() for reason in result.unknown_reasons)
        )

    def test_overlap_wins_over_unknown_provenance(self):
        track_id, member = self._sealed_track()
        self._dataset(
            "DS-MIX",
            [
                {
                    "source_image_id": member["source_image_id"],
                    "split": "train",
                    "origin_status": "exact_hash_only",
                }
            ],
            provenance_status="legacy_partial",
        )
        self._run(
            "RUN-MIX",
            "DS-MIX",
            provenance_status="legacy_partial",
        )
        self._model(
            "MODEL-MIX",
            "RUN-MIX",
            provenance_status="legacy_partial",
        )

        result = self.audit.audit("MODEL-MIX", track_id)
        self.assertEqual(result.status, INDEPENDENCE_FAIL)
        self.assertEqual(result.overlap_count, 1)

    def test_target_mismatch_is_rejected(self):
        track_id, _member = self._sealed_track()
        self._model(
            "MODEL-CHAR",
            None,
            target="char",
        )
        with self.assertRaises(ValueError):
            self.audit.audit("MODEL-CHAR", track_id)


if __name__ == "__main__":
    unittest.main()
