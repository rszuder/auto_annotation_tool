import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import (
    LINEAGE_EXACT_HASH_ONLY,
    LINEAGE_LEGACY_PARTIAL,
    DatasetRegistryRows,
    build_dataset_registry_rows,
)


class DatasetRegistryRowsTests(unittest.TestCase):
    def _dataset(self, root: Path) -> Path:
        dataset = root / "dataset"
        for split in ("train", "val", "test"):
            (dataset / "images" / split).mkdir(parents=True)
            (dataset / "labels" / split).mkdir(parents=True)
        (dataset / "data.yaml").write_text(
            "train: images/train\n"
            "val: images/val\n"
            "test: images/test\n"
            "names: [sample]\n",
            encoding="utf-8",
        )
        return dataset

    def _pair(
        self,
        dataset: Path,
        split: str,
        stem: str,
        image_bytes: bytes,
    ) -> None:
        (dataset / "images" / split / f"{stem}.jpg").write_bytes(image_bytes)
        (dataset / "labels" / split / f"{stem}.txt").write_text(
            "0 0.5 0.5 0.5 0.5\n",
            encoding="utf-8",
        )

    def test_rows_match_registry_tables_and_link_derived_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._pair(dataset, "train", "base", b"base")
            self._pair(dataset, "train", "aug1", b"augmented")
            (dataset / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {
                                "image": "images/train/aug1.jpg",
                                "source_image": "images/train/base.jpg",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = build_dataset_registry_rows("DS-MT-TEST", dataset)

            self.assertIsInstance(rows, DatasetRegistryRows)
            self.assertEqual(len(rows.source_images), 1)
            self.assertEqual(len(rows.image_artifacts), 2)
            self.assertEqual(len(rows.dataset_members), 2)

            artifacts = {
                row["relative_path"]: row
                for row in rows.image_artifacts
            }
            base = artifacts["images/train/base.jpg"]
            augmented = artifacts["images/train/aug1.jpg"]

            self.assertEqual(base["kind"], "dataset_image")
            self.assertEqual(augmented["kind"], "derived_image")
            self.assertEqual(
                augmented["derived_from_artifact_id"],
                base["artifact_id"],
            )
            self.assertEqual(
                augmented["source_image_id"],
                base["source_image_id"],
            )

            for member in rows.dataset_members:
                self.assertEqual(member["dataset_id"], "DS-MT-TEST")
                self.assertIn(
                    member["artifact_id"],
                    {row["artifact_id"] for row in rows.image_artifacts},
                )
                self.assertIn(
                    member["source_image_id"],
                    {row["source_image_id"] for row in rows.source_images},
                )

    def test_exact_duplicate_creates_two_artifacts_but_one_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._pair(dataset, "train", "a", b"same")
            self._pair(dataset, "val", "copy", b"same")

            rows = build_dataset_registry_rows("DS-MT-DUP", dataset)

            self.assertEqual(len(rows.source_images), 1)
            self.assertEqual(len(rows.image_artifacts), 2)
            self.assertEqual(len(rows.dataset_members), 2)
            self.assertEqual(
                rows.source_images[0]["origin_status"],
                LINEAGE_EXACT_HASH_ONLY,
            )

    def test_partial_lineage_is_preserved_in_source_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._pair(dataset, "train", "aug1", b"augmented")
            (dataset / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {
                                "image": "images/train/aug1.jpg",
                                "source_image": "images/train/missing.jpg",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = build_dataset_registry_rows("DS-MT-PARTIAL", dataset)

            self.assertEqual(len(rows.source_images), 1)
            self.assertEqual(
                rows.source_images[0]["origin_status"],
                LINEAGE_LEGACY_PARTIAL,
            )
            self.assertEqual(
                rows.lineage_status_counts,
                {LINEAGE_LEGACY_PARTIAL: 1},
            )

    def test_artifact_ids_are_stable_for_same_dataset_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._pair(dataset, "train", "a", b"one")

            first = build_dataset_registry_rows("DS-MT-STABLE", dataset)
            second = build_dataset_registry_rows("DS-MT-STABLE", dataset)

            self.assertEqual(
                [row["artifact_id"] for row in first.image_artifacts],
                [row["artifact_id"] for row in second.image_artifacts],
            )

    def test_dataset_id_is_part_of_artifact_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._pair(dataset, "train", "a", b"one")

            left = build_dataset_registry_rows("DS-MT-A", dataset)
            right = build_dataset_registry_rows("DS-MT-B", dataset)

            self.assertNotEqual(
                left.image_artifacts[0]["artifact_id"],
                right.image_artifacts[0]["artifact_id"],
            )
            self.assertEqual(
                left.source_images[0]["source_image_id"],
                right.source_images[0]["source_image_id"],
            )

    def test_empty_dataset_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            with self.assertRaises(ValueError):
                build_dataset_registry_rows("", dataset)


if __name__ == "__main__":
    unittest.main()
