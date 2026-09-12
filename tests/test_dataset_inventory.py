import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.training import (
    DatasetFileInventoryEntry,
    build_dataset_file_inventory,
    build_dataset_training_provenance,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _legacy_json_sha256(entries) -> str:
    data = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class DatasetInventoryTests(unittest.TestCase):
    def _make_dataset(self, root: Path) -> Path:
        dataset = root / "dataset"
        for split in ("train", "val", "test"):
            (dataset / "images" / split).mkdir(parents=True, exist_ok=True)
            (dataset / "labels" / split).mkdir(parents=True, exist_ok=True)

        (dataset / "images" / "train" / "a.jpg").write_bytes(b"train-image")
        (dataset / "labels" / "train" / "a.txt").write_text(
            "0 0.5 0.5 0.4 0.4\n",
            encoding="utf-8",
        )
        (dataset / "images" / "val" / "b.jpg").write_bytes(b"val-image")
        (dataset / "labels" / "val" / "b.txt").write_text(
            "0 0.4 0.4 0.3 0.3\n",
            encoding="utf-8",
        )
        (dataset / "images" / "test" / "c.jpg").write_bytes(b"test-image")
        (dataset / "labels" / "test" / "c.txt").write_text(
            "0 0.3 0.3 0.2 0.2\n",
            encoding="utf-8",
        )

        # Historyczny fingerprint włącza plik listy oraz wskazane przez niego obrazy.
        (dataset / "train.txt").write_text(
            "images/train/a.jpg\n",
            encoding="utf-8",
        )
        (dataset / "data.yaml").write_text(
            "train: train.txt\n"
            "val: images/val\n"
            "test: images/test\n"
            "names: [sample]\n",
            encoding="utf-8",
        )
        return dataset

    def _legacy_reference_entries(self, dataset: Path) -> list[dict]:
        paths = [
            ("train", dataset / "train.txt"),
            ("train", dataset / "images" / "train" / "a.jpg"),
            ("train", dataset / "labels" / "train" / "a.txt"),
            ("val", dataset / "images" / "val" / "b.jpg"),
            ("val", dataset / "labels" / "val" / "b.txt"),
            ("test", dataset / "images" / "test" / "c.jpg"),
            ("test", dataset / "labels" / "test" / "c.txt"),
        ]
        entries = [
            {
                "split": split,
                "relative_path": path.relative_to(dataset).as_posix(),
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
            for split, path in paths
        ]
        entries.sort(
            key=lambda item: (
                str(item.get("split")),
                str(item.get("relative_path")),
            )
        )
        return entries

    def test_public_inventory_preserves_legacy_split_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._make_dataset(Path(tmp))
            legacy_entries = self._legacy_reference_entries(dataset)
            expected_sha = _legacy_json_sha256(legacy_entries)

            provenance = build_dataset_training_provenance(
                dataset,
                target="plate",
                include_content_fingerprint=True,
            )
            inventory = build_dataset_file_inventory(dataset)

            self.assertEqual(provenance["split_sha256"], expected_sha)
            self.assertEqual(
                [entry.fingerprint_payload() for entry in inventory],
                legacy_entries,
            )
            self.assertEqual(provenance["split_file_count"], len(legacy_entries))

    def test_inventory_exposes_roles_without_changing_fingerprint_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._make_dataset(Path(tmp))
            inventory = build_dataset_file_inventory(dataset)

            self.assertTrue(
                all(isinstance(entry, DatasetFileInventoryEntry) for entry in inventory)
            )
            roles = {entry.relative_path: entry.role for entry in inventory}
            self.assertEqual(roles["train.txt"], "image_list")
            self.assertEqual(roles["images/train/a.jpg"], "image")
            self.assertEqual(roles["labels/train/a.txt"], "label")

            image_entry = next(
                entry
                for entry in inventory
                if entry.relative_path == "images/train/a.jpg"
            )
            label_entry = next(
                entry
                for entry in inventory
                if entry.relative_path == "labels/train/a.txt"
            )

            self.assertTrue(image_entry.is_image)
            self.assertFalse(label_entry.is_image)
            self.assertEqual(
                set(image_entry.fingerprint_payload()),
                {"split", "relative_path", "sha256", "size"},
            )

    def test_inventory_accepts_dataset_root_or_data_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._make_dataset(Path(tmp))
            from_root = build_dataset_file_inventory(dataset)
            from_yaml = build_dataset_file_inventory(dataset / "data.yaml")

            self.assertEqual(
                [entry.fingerprint_payload() for entry in from_root],
                [entry.fingerprint_payload() for entry in from_yaml],
            )

    def test_inventory_changes_when_dataset_member_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self._make_dataset(Path(tmp))
            before = build_dataset_training_provenance(
                dataset,
                target="plate",
                include_content_fingerprint=True,
            )["split_sha256"]

            (dataset / "images" / "train" / "a.jpg").write_bytes(
                b"changed-train-image"
            )

            after = build_dataset_training_provenance(
                dataset,
                target="plate",
                include_content_fingerprint=True,
            )["split_sha256"]

            self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
