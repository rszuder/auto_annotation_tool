import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.training.model_provenance import (
    TOTAL_EPOCHS_SCOPE,
    build_model_training_provenance,
)


def _write_file(path: Path, data: bytes | str = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def _make_dataset(root: Path, name: str = "dataset") -> Path:
    dataset = root / name
    for split in ("train", "val", "test"):
        _write_file(dataset / "images" / split / f"{split}_001.jpg", b"image")
        _write_file(dataset / "labels" / split / f"{split}_001.txt", "0 0.5 0.5 0.2 0.2\n")
    _write_file(
        dataset / "data.yaml",
        "path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: plate\n",
    )
    _write_file(
        dataset / "training_variant_manifest.json",
        json.dumps(
            {
                "source_images": 3,
                "source_objects": 3,
                "offline_augmentation_train_added": 0,
                "split_seed": 42,
            },
            ensure_ascii=False,
        ),
    )
    return dataset


def _run(
    run_id: str,
    dataset: Path,
    *,
    epochs: int,
    current_epoch: int | None = None,
    lineage_mode: str = "new",
    parent_run_id: str = "",
    base_model: str = "yolo26n.pt",
) -> dict:
    return {
        "id": run_id,
        "name": f"Run {run_id}",
        "status": "completed",
        "dataset_path": str(dataset),
        "base_model": base_model,
        "epochs": epochs,
        "current_epoch": epochs if current_epoch is None else current_epoch,
        "lineage_mode": lineage_mode,
        "parent_run_id": parent_run_id,
        "best_weights": str(dataset.parent / f"{run_id}_best.pt"),
    }


class ModelTrainingProvenanceTests(unittest.TestCase):
    def test_new_pretrained_run_counts_project_epochs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _make_dataset(Path(tmp))
            run = _run("20260901_090000", dataset, epochs=30)

            provenance = build_model_training_provenance(run, history_index={}, target="plate")

            self.assertEqual(provenance["run_epochs_completed"], 30)
            self.assertEqual(provenance["total_epochs"], 30)
            self.assertTrue(provenance["total_epochs_known"])
            self.assertEqual(provenance["total_epochs_scope"], TOTAL_EPOCHS_SCOPE)
            self.assertEqual(provenance["provenance_status"], "complete")

    def test_fine_tune_sums_parent_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _make_dataset(Path(tmp))
            parent = _run("20260901_090000", dataset, epochs=30)
            child = _run(
                "20260902_100000",
                dataset,
                epochs=10,
                lineage_mode="fine_tune",
                parent_run_id=parent["id"],
                base_model=str(dataset.parent / "parent_best.pt"),
            )

            provenance = build_model_training_provenance(
                child,
                history_index={parent["id"]: parent},
                target="plate",
            )

            self.assertEqual(provenance["run_epochs_completed"], 10)
            self.assertEqual(provenance["total_epochs"], 40)
            self.assertTrue(provenance["total_epochs_known"])
            self.assertEqual(provenance["lineage_depth"], 2)

    def test_three_generation_fine_tune_sums_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _make_dataset(Path(tmp))
            run_a = _run("20260901_090000", dataset, epochs=30)
            run_b = _run("20260902_100000", dataset, epochs=10, lineage_mode="fine_tune", parent_run_id=run_a["id"])
            run_c = _run("20260903_110000", dataset, epochs=5, lineage_mode="fine_tune", parent_run_id=run_b["id"])

            provenance = build_model_training_provenance(
                run_c,
                history_index={run_a["id"]: run_a, run_b["id"]: run_b},
                target="plate",
            )

            self.assertEqual(provenance["total_epochs"], 45)
            self.assertEqual(provenance["known_epochs_minimum"], 45)
            self.assertEqual([row["epochs_completed"] for row in provenance["lineage"]], [30, 10, 5])

    def test_resume_is_not_summed_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _make_dataset(Path(tmp))
            run = _run("20260904_120000", dataset, epochs=100, current_epoch=100, lineage_mode="resume")

            provenance = build_model_training_provenance(run, history_index={}, target="char")

            self.assertEqual(provenance["run_epochs_completed"], 100)
            self.assertEqual(provenance["total_epochs"], 100)
            self.assertEqual(provenance["lineage_depth"], 1)

    def test_missing_legacy_parent_keeps_only_known_minimum(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _make_dataset(Path(tmp))
            run = _run(
                "20260905_130000",
                dataset,
                epochs=10,
                lineage_mode="fine_tune",
                parent_run_id="20260801_090000",
                base_model=str(Path(tmp) / "external_best.pt"),
            )

            provenance = build_model_training_provenance(run, history_index={}, target="char")

            self.assertIsNone(provenance["total_epochs"])
            self.assertFalse(provenance["total_epochs_known"])
            self.assertEqual(provenance["known_epochs_minimum"], 10)
            self.assertEqual(provenance["provenance_status"], "partial")

    def test_cycle_in_lineage_is_partial_not_infinite(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = _make_dataset(Path(tmp))
            run_a = _run("20260906_140000", dataset, epochs=7, lineage_mode="fine_tune", parent_run_id="20260906_150000")
            run_b = _run("20260906_150000", dataset, epochs=8, lineage_mode="fine_tune", parent_run_id=run_a["id"])

            provenance = build_model_training_provenance(
                run_a,
                history_index={run_a["id"]: run_a, run_b["id"]: run_b},
                target="plate",
            )

            self.assertIsNone(provenance["total_epochs"])
            self.assertFalse(provenance["total_epochs_known"])
            self.assertEqual(provenance["provenance_status"], "partial")
            self.assertTrue(any("cykl" in warning.lower() for warning in provenance["warnings"]))


if __name__ == "__main__":
    unittest.main()
