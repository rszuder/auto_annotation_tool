import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.reservation_service import (
    CHECK_FAIL,
    CHECK_PASS,
    CHECK_UNKNOWN,
    RESERVATION_TYPE_TRAIN_VAL,
    TrainingReservationService,
)
from auto_annotation_tool.registry.track_service import (
    EvaluationTrackService,
)


def _write_dataset(
    root: Path,
    *,
    train: dict[str, bytes] | None = None,
    val: dict[str, bytes] | None = None,
    test: dict[str, bytes] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for split, files in (
        ("train", train or {}),
        ("val", val or {}),
        ("test", test or {}),
    ):
        image_dir = root / "images" / split
        label_dir = root / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in files.items():
            (image_dir / name).write_bytes(payload)
            (label_dir / f"{Path(name).stem}.txt").write_text(
                "0 0.5 0.5 0.2 0.2\n",
                encoding="utf-8",
            )
    (root / "data.yaml").write_text(
        "\n".join(
            (
                "path: .",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "nc: 1",
                "names: [plate]",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def _write_gt(path: Path, image_name: str) -> None:
    path.write_text(
        (
            "<annotations>"
            f'<image id="0" name="{image_name}" width="100" height="50">'
            '<box label="plate" xtl="0" ytl="0" xbr="10" ybr="10"/>'
            "</image></annotations>"
        ),
        encoding="utf-8",
    )


class TrainingReservationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.track_service = EvaluationTrackService(self.workspace)
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.reservations = TrainingReservationService(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def _seal_track(
        self,
        *,
        payload: bytes = b"reserved",
        name: str = "reserved.jpg",
        purpose: str = "final_test",
        policy: str = "reserve_from_training",
    ) -> str:
        image = Path(self.temp.name) / name
        image.write_bytes(payload)
        gt = Path(self.temp.name) / f"{Path(name).stem}.xml"
        _write_gt(gt, name)

        track_id = self.track_service.create_draft(
            name=f"track-{purpose}",
            target="plate",
            purpose=purpose,
            reservation_policy=policy,
        )
        self.track_service.add_member(track_id, image)
        self.track_service.set_ground_truth(track_id, gt)
        self.track_service.verify(track_id)
        self.track_service.seal(track_id)
        return track_id

    def test_sealing_final_track_activates_reservation(self):
        track_id = self._seal_track()
        rows = self.repo.list_active_training_reservations(
            reservation_type=RESERVATION_TYPE_TRAIN_VAL,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["track_id"], track_id)

    def test_validation_track_without_policy_does_not_reserve(self):
        self._seal_track(
            purpose="validation",
            policy="none",
        )
        rows = self.repo.list_active_training_reservations(
            reservation_type=RESERVATION_TYPE_TRAIN_VAL,
        )
        self.assertEqual(rows, [])

    def test_retired_track_keeps_reservation(self):
        track_id = self._seal_track()
        self.track_service.retire(track_id)
        rows = self.repo.list_active_training_reservations(
            reservation_type=RESERVATION_TYPE_TRAIN_VAL,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["track_id"], track_id)

    def test_sync_backfills_missing_reservation_for_old_sealed_track(self):
        track_id = self._seal_track()
        with self.repo.database.transaction() as connection:
            connection.execute(
                "DELETE FROM reservations WHERE track_id = ?",
                (track_id,),
            )
        self.assertEqual(
            self.repo.table_count("reservations"),
            0,
        )

        self.reservations.sync()
        self.assertEqual(
            self.repo.table_count("reservations"),
            1,
        )

    def test_reserved_exact_image_in_train_is_blocked(self):
        self._seal_track(payload=b"same")
        dataset = Path(self.temp.name) / "dataset_train"
        _write_dataset(
            dataset,
            train={"reserved.jpg": b"same"},
            val={"other.jpg": b"other"},
        )

        result = self.reservations.check_training_dataset(dataset)
        self.assertEqual(result.status, CHECK_FAIL)
        self.assertTrue(result.blocked)
        self.assertEqual(result.overlaps[0].split, "train")

    def test_reserved_exact_image_in_val_is_blocked(self):
        self._seal_track(payload=b"same")
        dataset = Path(self.temp.name) / "dataset_val"
        _write_dataset(
            dataset,
            train={"other.jpg": b"other"},
            val={"reserved.jpg": b"same"},
        )

        result = self.reservations.check_training_dataset(dataset)
        self.assertEqual(result.status, CHECK_FAIL)
        self.assertEqual(result.overlaps[0].split, "val")

    def test_reserved_image_only_in_test_does_not_block_training(self):
        self._seal_track(payload=b"same")
        dataset = Path(self.temp.name) / "dataset_test"
        _write_dataset(
            dataset,
            train={"train.jpg": b"train"},
            val={"val.jpg": b"val"},
            test={"reserved.jpg": b"same"},
        )

        result = self.reservations.check_training_dataset(dataset)
        self.assertFalse(result.blocked)
        self.assertIn(result.status, {CHECK_PASS, CHECK_UNKNOWN})
        self.assertEqual(result.overlaps, ())

    def test_known_augmentation_lineage_in_train_is_blocked(self):
        root_payload = b"root"
        derived_payload = b"derived"
        self._seal_track(
            payload=root_payload,
            name="root.jpg",
        )
        dataset = Path(self.temp.name) / "dataset_aug"
        _write_dataset(
            dataset,
            train={"derived.jpg": derived_payload},
            val={"val.jpg": b"val"},
            test={"root.jpg": root_payload},
        )
        (dataset / "augmentation_manifest.json").write_text(
            """
{
  "generated_files": [
    {
      "image": "images/train/derived.jpg",
      "source_image": "images/test/root.jpg"
    }
  ]
}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        result = self.reservations.check_training_dataset(dataset)
        self.assertEqual(result.status, CHECK_FAIL)
        self.assertTrue(
            any(
                item.relative_path.endswith("derived.jpg")
                and item.match_kind == "source_image_id"
                for item in result.overlaps
            )
        )

    def test_plain_non_overlapping_dataset_is_unknown_not_blocked(self):
        self._seal_track(payload=b"reserved")
        dataset = Path(self.temp.name) / "dataset_plain"
        _write_dataset(
            dataset,
            train={"train.jpg": b"train"},
            val={"val.jpg": b"val"},
        )

        result = self.reservations.check_training_dataset(dataset)
        self.assertEqual(result.status, CHECK_UNKNOWN)
        self.assertFalse(result.blocked)
        self.assertGreater(result.unknown_count, 0)

    def test_no_active_reservations_returns_pass(self):
        dataset = Path(self.temp.name) / "dataset_clear"
        _write_dataset(
            dataset,
            train={"train.jpg": b"train"},
            val={"val.jpg": b"val"},
        )
        result = self.reservations.check_training_dataset(dataset)
        self.assertEqual(result.status, CHECK_PASS)
        self.assertFalse(result.blocked)


if __name__ == "__main__":
    unittest.main()
