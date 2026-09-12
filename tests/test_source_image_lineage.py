import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.dataset_inventory import (
    LINEAGE_EXACT_HASH_ONLY,
    LINEAGE_KNOWN,
    LINEAGE_LEGACY_PARTIAL,
    build_dataset_image_lineage,
)


class SourceImageLineageTests(unittest.TestCase):
    def _dataset(self, root: Path) -> Path:
        dataset = root / "dataset"
        (dataset / "images" / "train").mkdir(parents=True)
        (dataset / "labels" / "train").mkdir(parents=True)
        (dataset / "images" / "val").mkdir(parents=True)
        (dataset / "labels" / "val").mkdir(parents=True)
        (dataset / "images" / "test").mkdir(parents=True)
        (dataset / "labels" / "test").mkdir(parents=True)
        (dataset / "data.yaml").write_text(
            "train: images/train\n"
            "val: images/val\n"
            "test: images/test\n"
            "names: [sample]\n",
            encoding="utf-8",
        )
        return dataset

    def _write_pair(self, dataset: Path, split: str, stem: str, image_bytes: bytes) -> None:
        (dataset / "images" / split / f"{stem}.jpg").write_bytes(image_bytes)
        (dataset / "labels" / split / f"{stem}.txt").write_text(
            "0 0.5 0.5 0.5 0.5\n",
            encoding="utf-8",
        )

    def test_augmented_image_inherits_source_image_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._write_pair(dataset, "train", "plate_001", b"original")
            self._write_pair(dataset, "train", "plate_001_aug1", b"augmented")
            (dataset / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {
                                "image": "images/train/plate_001_aug1.jpg",
                                "label": "labels/train/plate_001_aug1.txt",
                                "source_image": "images/train/plate_001.jpg",
                                "source_label": "labels/train/plate_001.txt",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = {row.relative_path: row for row in build_dataset_image_lineage(dataset)}
            original = rows["images/train/plate_001.jpg"]
            augmented = rows["images/train/plate_001_aug1.jpg"]

            self.assertEqual(original.lineage_status, LINEAGE_EXACT_HASH_ONLY)
            self.assertEqual(augmented.lineage_status, LINEAGE_KNOWN)
            self.assertEqual(augmented.source_image_id, original.source_image_id)
            self.assertEqual(augmented.source_sha256, original.artifact_sha256)
            self.assertEqual(augmented.lineage_depth, 1)
            self.assertEqual(augmented.parent_reference, "images/train/plate_001.jpg")

    def test_transitive_augmentation_resolves_to_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._write_pair(dataset, "train", "base", b"base")
            self._write_pair(dataset, "train", "aug1", b"aug1")
            self._write_pair(dataset, "train", "aug2", b"aug2")
            (dataset / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {
                                "image": "images/train/aug1.jpg",
                                "source_image": "images/train/base.jpg",
                            },
                            {
                                "image": "images/train/aug2.jpg",
                                "source_image": "images/train/aug1.jpg",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = {row.relative_path: row for row in build_dataset_image_lineage(dataset)}
            self.assertEqual(rows["images/train/aug2.jpg"].source_image_id, rows["images/train/base.jpg"].source_image_id)
            self.assertEqual(rows["images/train/aug2.jpg"].lineage_depth, 2)
            self.assertEqual(rows["images/train/aug2.jpg"].lineage_status, LINEAGE_KNOWN)

    def test_label_only_legacy_manifest_can_resolve_image_by_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._write_pair(dataset, "train", "plate_001", b"source")
            self._write_pair(dataset, "train", "plate_001_aug1", b"derived")
            (dataset / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {
                                "label": "labels/train/plate_001_aug1.txt",
                                "source_label": "labels/train/plate_001.txt",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = {row.relative_path: row for row in build_dataset_image_lineage(dataset)}
            self.assertEqual(
                rows["images/train/plate_001_aug1.jpg"].source_image_id,
                rows["images/train/plate_001.jpg"].source_image_id,
            )
            self.assertEqual(rows["images/train/plate_001_aug1.jpg"].lineage_status, LINEAGE_KNOWN)

    def test_exact_duplicate_without_lineage_uses_same_hash_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._write_pair(dataset, "train", "a", b"same-bytes")
            self._write_pair(dataset, "val", "copy", b"same-bytes")

            rows = {row.relative_path: row for row in build_dataset_image_lineage(dataset)}
            self.assertEqual(rows["images/train/a.jpg"].source_image_id, rows["images/val/copy.jpg"].source_image_id)
            self.assertEqual(rows["images/train/a.jpg"].lineage_status, LINEAGE_EXACT_HASH_ONLY)
            self.assertEqual(rows["images/val/copy.jpg"].lineage_status, LINEAGE_EXACT_HASH_ONLY)

    def test_missing_manifest_source_is_marked_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._write_pair(dataset, "train", "aug1", b"augmented")
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

            row = build_dataset_image_lineage(dataset)[0]
            self.assertEqual(row.lineage_status, LINEAGE_LEGACY_PARTIAL)
            self.assertTrue(row.source_image_id.startswith("SRC-UNRESOLVED-"))
            self.assertEqual(row.source_sha256, "")

    def test_cycle_is_marked_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._dataset(Path(tmp))
            self._write_pair(dataset, "train", "a", b"a")
            self._write_pair(dataset, "train", "b", b"b")
            (dataset / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {
                                "image": "images/train/a.jpg",
                                "source_image": "images/train/b.jpg",
                            },
                            {
                                "image": "images/train/b.jpg",
                                "source_image": "images/train/a.jpg",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rows = build_dataset_image_lineage(dataset)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row.lineage_status == LINEAGE_LEGACY_PARTIAL for row in rows))
            self.assertTrue(all(row.source_image_id.startswith("SRC-UNRESOLVED-") for row in rows))


if __name__ == "__main__":
    unittest.main()
