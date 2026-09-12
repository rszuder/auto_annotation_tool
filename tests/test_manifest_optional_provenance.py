import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.bootstrap import _run_provenance_status
from auto_annotation_tool.training.model_provenance import (
    build_dataset_training_provenance,
    build_model_training_provenance,
)


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def _dataset(root: Path) -> Path:
    dataset = root / "dataset"
    for split in ("train", "val", "test"):
        _write(
            dataset / "images" / split / f"{split}.jpg",
            f"{split}-image".encode("utf-8"),
        )
        _write(
            dataset / "labels" / split / f"{split}.txt",
            "0 0.5 0.5 0.2 0.2\n",
        )
    _write(
        dataset / "data.yaml",
        (
            "path: .\n"
            "train: images/train\n"
            "val: images/val\n"
            "test: images/test\n"
            "names:\n"
            "  0: plate\n"
        ),
    )
    return dataset


class ManifestOptionalProvenanceTests(unittest.TestCase):
    def test_dataset_without_generator_manifest_is_complete_by_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _dataset(Path(tmp))

            provenance = build_dataset_training_provenance(
                dataset,
                target="plate",
            )

            self.assertEqual(provenance["manifest_sha256"], "")
            self.assertTrue(provenance["data_yaml_sha256"])
            self.assertTrue(provenance["split_sha256"])
            self.assertEqual(
                provenance["provenance_status"],
                "complete",
            )
            self.assertEqual(
                provenance["provenance_basis"],
                "content_fingerprint",
            )

    def test_missing_split_fingerprint_is_still_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _dataset(Path(tmp))

            provenance = build_dataset_training_provenance(
                dataset,
                target="plate",
                include_content_fingerprint=False,
            )

            self.assertEqual(provenance["split_sha256"], "")
            self.assertEqual(
                provenance["provenance_status"],
                "partial",
            )

    def test_bootstrap_run_accepts_frozen_content_identity_without_manifest(self):
        run = {
            "training_dataset_snapshot": {
                "dataset_id": "DS-MT-ABC",
                "data_yaml_sha256": "1" * 64,
                "split_sha256": "2" * 64,
                "manifest_sha256": "",
                "provenance_status": "partial",
            },
            "input_checkpoint_snapshot": {
                "sha256": "3" * 64,
            },
            "output_checkpoint_snapshot": {
                "best": {
                    "sha256": "4" * 64,
                },
            },
            "lineage_mode": "new",
        }

        self.assertEqual(
            _run_provenance_status(
                run,
                parent_source_run_id="",
            ),
            "complete",
        )

    def test_legacy_partial_snapshot_is_effectively_complete_when_content_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = _dataset(root)
            dataset_snapshot = build_dataset_training_provenance(
                dataset,
                target="plate",
            )
            dataset_snapshot["provenance_status"] = "partial"
            dataset_snapshot["manifest_sha256"] = ""

            input_path = root / "yolo26n-pose.pt"
            best_path = root / "best.pt"
            _write(input_path, b"input")
            _write(best_path, b"best")
            input_sha = hashlib.sha256(b"input").hexdigest()
            best_sha = hashlib.sha256(b"best").hexdigest()

            run = {
                "id": "20260905_223437",
                "name": "MT-n",
                "status": "completed",
                "dataset_path": str(dataset),
                "training_target": "plate",
                "base_model": str(input_path),
                "best_weights": str(best_path),
                "epochs": 1,
                "current_epoch": 1,
                "lineage_mode": "new",
                "training_dataset_snapshot": dataset_snapshot,
                "input_checkpoint_snapshot": {
                    "sha256": input_sha,
                    "provenance_status": "complete",
                },
                "output_checkpoint_snapshot": {
                    "best": {
                        "sha256": best_sha,
                        "provenance_status": "complete",
                    },
                    "provenance_status": "complete",
                },
            }

            provenance = build_model_training_provenance(
                run,
                checkpoint=best_path,
                target="plate",
            )

            self.assertEqual(
                provenance["provenance_status"],
                "complete",
            )
            self.assertFalse(
                any(
                    "nie ma jawnego manifestu generatora"
                    in warning.lower()
                    and "fingerprint" not in warning.lower()
                    for warning in provenance["warnings"]
                )
            )


if __name__ == "__main__":
    unittest.main()
