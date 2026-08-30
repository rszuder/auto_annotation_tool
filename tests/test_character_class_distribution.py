from pathlib import Path
import json
import os
import random
import tempfile
import unittest

from auto_annotation_tool.training.character_class_distribution import (
    CHARACTER_BALANCE_ALPHABET,
    CHARACTER_REPRESENTATION_THRESHOLD_POLICY,
    CHARACTER_TRAINING_VARIANT_SCHEMA,
    CharacterClassMapValidationError,
    analyze_character_class_distribution,
    build_character_training_variant_manifest,
    build_character_dataset_file_fingerprint,
    compare_character_val_test_unchanged,
    find_character_real_source_candidates,
    plan_character_train_augmentation,
    save_character_distribution_artifacts,
    save_character_class_distribution_csv,
    save_character_class_distribution_json,
)
from auto_annotation_tool.training.dataset_augmentation import (
    _build_balance_augmented_source_state,
    _finalize_train_augmentation_result,
    _select_augmentation_sample_pool,
)


def _names_list_yaml() -> str:
    lines = ["path: .", "names:"]
    lines.extend(f"  - \"{symbol}\"" for symbol in CHARACTER_BALANCE_ALPHABET)
    return "\n".join(lines) + "\n"


def _names_dict_yaml() -> str:
    lines = ["path: .", "names:"]
    lines.extend(f"  {index}: \"{symbol}\"" for index, symbol in enumerate(CHARACTER_BALANCE_ALPHABET))
    return "\n".join(lines) + "\n"


class CharacterClassDistributionTests(unittest.TestCase):
    def test_split_counts_invalid_lines_and_unique_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "labels" / "val").mkdir(parents=True)
            (root / "labels" / "test").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "plate_a.txt").write_text(
                "0 0.5 0.5 0.1 0.1\n"
                "0 0.6 0.5 0.1 0.1\n"
                "10 0.1 0.1 0.1 0.1\n",
                encoding="utf-8",
            )
            (root / "labels" / "train" / "plate_b.txt").write_text(
                "1 0.2 0.2 0.1 0.1\n36 0 0 0 0\nbad line\n",
                encoding="utf-8",
            )
            (root / "labels" / "val" / "plate_c.txt").write_text(
                "10 0.2 0.2 0.1 0.1\n",
                encoding="utf-8",
            )
            (root / "labels" / "test" / "plate_d.txt").write_text(
                "35 0.2 0.2 0.1 0.1\n",
                encoding="utf-8",
            )

            dist = analyze_character_class_distribution(root)
            rows = {row.symbol: row for row in dist.classes}

            self.assertEqual(dist.layout, "split")
            self.assertEqual(rows["0"].train_count, 2)
            self.assertEqual(rows["0"].unique_train_plate_count, 1)
            self.assertEqual(rows["A"].train_count, 1)
            self.assertEqual(rows["A"].val_count, 1)
            self.assertEqual(rows["Z"].test_count, 1)
            self.assertEqual(dist.summary["invalid_class_ids"], 1)
            self.assertEqual(dist.summary["invalid_label_lines"], 1)

            csv_path = save_character_class_distribution_csv(dist, root / "balance.csv")
            json_path = save_character_class_distribution_json(dist, root / "balance.json")
            self.assertTrue(csv_path.exists())
            self.assertTrue(json_path.exists())

    def test_flat_layout_uses_total_without_faking_train(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels").mkdir()
            (root / "labels" / "flat.txt").write_text(
                "2 0.5 0.5 0.1 0.1\n2 0.6 0.5 0.1 0.1\n",
                encoding="utf-8",
            )

            dist = analyze_character_class_distribution(root)
            rows = {row.symbol: row for row in dist.classes}

            self.assertEqual(dist.layout, "flat")
            self.assertEqual(dist.diagnostic_split, "total")
            self.assertEqual(rows["2"].train_count, 0)
            self.assertEqual(rows["2"].total_count, 2)
            self.assertEqual(rows["2"].unique_total_plate_count, 1)

    def test_augmentation_manifest_preserves_source_diversity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_dict_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "plate_001.txt").write_text(
                "4 0.5 0.5 0.1 0.1\n",
                encoding="utf-8",
            )
            (root / "labels" / "train" / "plate_002.txt").write_text(
                "4 0.5 0.5 0.1 0.1\n",
                encoding="utf-8",
            )
            (root / "augmentation_manifest.json").write_text(
                '{"generated_files":[{"label":"labels/train/plate_002.txt",'
                '"source_label":"labels/train/plate_001.txt"}]}',
                encoding="utf-8",
            )

            dist = analyze_character_class_distribution(root)
            rows = {row.symbol: row for row in dist.classes}

            self.assertEqual(rows["4"].train_count, 2)
            self.assertEqual(rows["4"].unique_train_plate_count, 1)

    def test_data_yaml_dict_names_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_dict_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "plate.txt").write_text("10 0 0 0 0\n", encoding="utf-8")

            dist = analyze_character_class_distribution(root)

            self.assertEqual(dist.summary["class_map"]["status"], "OK")

    def test_target_count_and_deficit_use_half_median_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "zeros.txt").write_text(
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n",
                encoding="utf-8",
            )
            (root / "labels" / "train" / "ones.txt").write_text(
                "1 0 0 0 0\n"
                "1 0 0 0 0\n"
                "1 0 0 0 0\n"
                "1 0 0 0 0\n",
                encoding="utf-8",
            )
            (root / "labels" / "train" / "twos.txt").write_text("2 0 0 0 0\n", encoding="utf-8")

            dist = analyze_character_class_distribution(root)
            rows = {row.symbol: row for row in dist.classes}

            self.assertEqual(dist.summary["target_class_count"], 2)
            self.assertEqual(rows["0"].deficit_count, 0)
            self.assertEqual(rows["1"].deficit_count, 0)
            self.assertEqual(rows["2"].deficit_count, 1)
            self.assertIn("2", dist.summary["deficit_classes"])

    def test_target_ratio_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "zeros.txt").write_text("0 0 0 0 0\n0 0 0 0 0\n", encoding="utf-8")
            (root / "labels" / "train" / "ones.txt").write_text("1 0 0 0 0\n", encoding="utf-8")

            dist = analyze_character_class_distribution(root, target_ratio=1.0)
            rows = {row.symbol: row for row in dist.classes}

            self.assertEqual(dist.summary["target_class_count"], 2)
            self.assertEqual(rows["1"].deficit_count, 1)

    def test_train_augmentation_plan_uses_deficit_priority_and_ignores_val_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "labels" / "val").mkdir(parents=True)
            (root / "images" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "zeros.txt").write_text(
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n"
                "0 0 0 0 0\n",
                encoding="utf-8",
            )
            (root / "labels" / "train" / "ones.txt").write_text(
                "1 0 0 0 0\n"
                "1 0 0 0 0\n"
                "1 0 0 0 0\n"
                "1 0 0 0 0\n",
                encoding="utf-8",
            )
            (root / "labels" / "train" / "twos.txt").write_text("2 0 0 0 0\n", encoding="utf-8")
            (root / "images" / "train" / "twos.jpg").write_bytes(b"fake")
            (root / "labels" / "val" / "threes_val.txt").write_text("3 0 0 0 0\n", encoding="utf-8")

            plan = plan_character_train_augmentation(root, max_augmented_variants_per_source=2)

            self.assertEqual(plan.target_count, 2)
            self.assertEqual(plan.deficit_by_symbol["2"], 1)
            self.assertTrue(plan.candidates)
            self.assertEqual(plan.candidates[0].source_key, "twos")
            self.assertEqual(plan.candidates[0].priority, 1.0)
            self.assertEqual(plan.candidates[0].max_augmented_variants, 2)
            self.assertTrue(plan.candidates[0].image_path.endswith("twos.jpg"))
            self.assertFalse(any("threes_val" in candidate.label_path for candidate in plan.candidates))

    def test_training_variant_manifest_carries_before_after_and_source_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "plate.txt").write_text("0 0 0 0 0\n", encoding="utf-8")
            before = analyze_character_class_distribution(root)
            plan = plan_character_train_augmentation(root, max_augmented_variants_per_source=4)
            refs = save_character_distribution_artifacts(before, root / "analysis", prefix="character_class_distribution_before")
            after_path = root / "analysis" / "character_class_distribution_after.json"
            after_path.write_text('{"after": true}', encoding="utf-8")
            base_fingerprint = build_character_dataset_file_fingerprint(root)
            val_test_guard = compare_character_val_test_unchanged(
                build_character_dataset_file_fingerprint(root, splits=("val", "test")),
                build_character_dataset_file_fingerprint(root, splits=("val", "test")),
            )

            manifest = build_character_training_variant_manifest(
                base_dataset=root,
                before_distribution=refs["json"]["path"],
                after_distribution=after_path,
                plan=plan,
                sources={"real": 7, "added_real": 2, "augmented_real": 3},
                base_dataset_sha_or_fingerprint=base_fingerprint,
                val_test_unchanged=val_test_guard,
            )

            self.assertEqual(manifest["schema"], CHARACTER_TRAINING_VARIANT_SCHEMA)
            self.assertEqual(manifest["alphabet"], CHARACTER_BALANCE_ALPHABET)
            self.assertEqual(manifest["selection_policy"], "deficit_progressive_reuse_v1")
            self.assertEqual(manifest["threshold_policy"], CHARACTER_REPRESENTATION_THRESHOLD_POLICY)
            self.assertEqual(manifest["planned_images"], plan.planned_images)
            self.assertEqual(manifest["predicted_deficit_after"], plan.predicted_deficit_after)
            self.assertEqual(manifest["unique_real_sources_used"], plan.unique_real_sources_used)
            self.assertEqual(manifest["reuse_rounds_used"], plan.reuse_rounds_used)
            self.assertEqual(manifest["sources"]["real"], 7)
            self.assertEqual(manifest["sources"]["added_real"], 2)
            self.assertEqual(manifest["sources"]["augmented_real"], 3)
            self.assertEqual(manifest["sources"]["synthetic"], 0)
            self.assertEqual(manifest["max_augmented_variants_per_source"], 4)
            self.assertEqual(manifest["augmentation"]["max_variants_per_source"], 4)
            self.assertTrue(manifest["before_distribution"]["path"].endswith("character_class_distribution_before.json"))
            self.assertRegex(manifest["before_distribution"]["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(manifest["after_distribution"]["path"].endswith("character_class_distribution_after.json"))
            self.assertRegex(manifest["after_distribution"]["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(manifest["val_test_unchanged"])
            self.assertRegex(manifest["base_dataset_sha_or_fingerprint"]["sha256"], r"^[0-9a-f]{64}$")

    def test_plan_deduplicates_augmented_source_key_and_prefers_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "images" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "heavy.txt").write_text("0 0 0 0 0\n" * 8, encoding="utf-8")
            for stem in ("plate_001", "plate_001_aug1", "plate_001_aug2"):
                (root / "labels" / "train" / f"{stem}.txt").write_text("16 0 0 0 0\n", encoding="utf-8")
                (root / "images" / "train" / f"{stem}.jpg").write_bytes(b"fake")
            (root / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {"label": "labels/train/plate_001_aug1.txt", "source_label": "labels/train/plate_001.txt"},
                            {"label": "labels/train/plate_001_aug2.txt", "source_label": "labels/train/plate_001.txt"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            plan = plan_character_train_augmentation(root, target_ratio=1.0)
            source_candidates = [candidate for candidate in plan.candidates if candidate.source_key == "plate_001"]

            self.assertEqual(len(source_candidates), 1)
            self.assertTrue(source_candidates[0].label_path.endswith("plate_001.txt"))

    def test_plan_warns_when_only_augmented_representatives_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "heavy.txt").write_text("0 0 0 0 0\n" * 8, encoding="utf-8")
            (root / "labels" / "train" / "plate_001_aug1.txt").write_text("16 0 0 0 0\n", encoding="utf-8")
            (root / "labels" / "train" / "plate_001_aug2.txt").write_text("16 0 0 0 0\n", encoding="utf-8")

            plan = plan_character_train_augmentation(root, target_ratio=1.0)

            self.assertEqual(sum(1 for candidate in plan.candidates if candidate.source_key == "plate_001"), 1)
            self.assertTrue(any("tylko kopie augmentowane" in warning for warning in plan.warnings))

    def test_plan_uses_symbol_multiplicity_for_planned_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "images" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            zero_id = CHARACTER_BALANCE_ALPHABET.index("0")
            one_id = CHARACTER_BALANCE_ALPHABET.index("1")
            q_id = CHARACTER_BALANCE_ALPHABET.index("Q")
            (root / "labels" / "train" / "zeros.txt").write_text(f"{zero_id} 0 0 0 0\n" * 10, encoding="utf-8")
            (root / "labels" / "train" / "ones.txt").write_text(f"{one_id} 0 0 0 0\n" * 10, encoding="utf-8")
            (root / "labels" / "train" / "qq1.txt").write_text(
                f"{q_id} 0 0 0 0\n{q_id} 0 0 0 0\n{one_id} 0 0 0 0\n",
                encoding="utf-8",
            )
            (root / "images" / "train" / "qq1.jpg").write_bytes(b"fake")

            plan = plan_character_train_augmentation(root, target_ratio=1.0)

            self.assertEqual(plan.target_count, 10)
            self.assertEqual(plan.deficit_by_symbol["Q"], 8)
            self.assertEqual(plan.planned_images, 4)
            self.assertEqual(plan.predicted_deficit_after.get("Q", 0), 0)
            self.assertEqual(plan.candidates[0].source_key, "qq1")
            self.assertEqual(plan.candidates[0].planned_variants, 4)

    def test_plan_reports_not_feasible_when_deficit_has_no_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            zero_id = CHARACTER_BALANCE_ALPHABET.index("0")
            one_id = CHARACTER_BALANCE_ALPHABET.index("1")
            (root / "labels" / "train" / "zeros.txt").write_text(f"{zero_id} 0 0 0 0\n" * 10, encoding="utf-8")
            (root / "labels" / "train" / "ones.txt").write_text(f"{one_id} 0 0 0 0\n" * 10, encoding="utf-8")

            plan = plan_character_train_augmentation(root, target_ratio=1.0)

            self.assertFalse(plan.feasible)
            self.assertEqual(plan.completion_status, "PLAN_NOT_FEASIBLE")
            self.assertEqual(plan.planned_images, 0)
            self.assertGreater(plan.predicted_deficit_after.get("Q", 0), 0)

    def test_manual_augmentation_state_has_no_balance_limit_without_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records, limits, _initial, stats = _build_balance_augmented_source_state(
                root,
                [(root / "images" / "train" / "a.jpg", root / "labels" / "train" / "a.txt")],
                balance_plan=None,
            )

            self.assertEqual(len(records), 1)
            self.assertFalse(stats["balance_plan_enabled"])
            self.assertIsNone(limits["a"])
            self.assertIsNone(stats["max_augmented_variants_per_source"])

    def test_executor_balance_state_respects_max_variants_per_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "images" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            for stem in ("plate_001", "plate_001__aug_0001", "plate_001__aug_0002"):
                label = root / "labels" / "train" / f"{stem}.txt"
                image = root / "images" / "train" / f"{stem}.jpg"
                label.write_text("16 0 0 0 0\n", encoding="utf-8")
                image.write_bytes(b"fake")
            (root / "augmentation_manifest.json").write_text(
                json.dumps(
                    {
                        "generated_files": [
                            {"label": "labels/train/plate_001__aug_0001.txt", "source_label": "labels/train/plate_001.txt"},
                            {"label": "labels/train/plate_001__aug_0002.txt", "source_label": "labels/train/plate_001.txt"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            plan = {
                "base_dataset": str(root),
                "max_augmented_variants_per_source": 3,
                "candidates": [
                    {
                        "source_key": "plate_001",
                        "label_path": str(root / "labels" / "train" / "plate_001.txt"),
                        "priority": 10,
                        "max_augmented_variants": 3,
                    }
                ],
            }

            records, limits, initial, stats = _build_balance_augmented_source_state(root, [
                (root / "images" / "train" / "plate_001.jpg", root / "labels" / "train" / "plate_001.txt"),
                (root / "images" / "train" / "plate_001__aug_0001.jpg", root / "labels" / "train" / "plate_001__aug_0001.txt"),
                (root / "images" / "train" / "plate_001__aug_0002.jpg", root / "labels" / "train" / "plate_001__aug_0002.txt"),
            ], balance_plan=plan)

            self.assertEqual(len(records), 1)
            self.assertEqual(limits["plate_001"], 3)
            self.assertEqual(initial["plate_001"], 2)
            self.assertEqual(stats["max_augmented_variants_per_source"], 3)

    def test_val_test_fingerprint_detects_untouched_and_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "val").mkdir(parents=True)
            (root / "images" / "val").mkdir(parents=True)
            (root / "labels" / "test").mkdir(parents=True)
            (root / "images" / "test").mkdir(parents=True)
            (root / "labels" / "val" / "a.txt").write_text("0 0 0 0 0\n", encoding="utf-8")
            (root / "images" / "val" / "a.jpg").write_bytes(b"a")

            before = build_character_dataset_file_fingerprint(root, splits=("val", "test"))
            after = build_character_dataset_file_fingerprint(root, splits=("val", "test"))
            self.assertTrue(compare_character_val_test_unchanged(before, after)["unchanged"])

            (root / "labels" / "test" / "b.txt").write_text("1 0 0 0 0\n", encoding="utf-8")
            changed = build_character_dataset_file_fingerprint(root, splits=("val", "test"))
            self.assertFalse(compare_character_val_test_unchanged(before, changed)["unchanged"])

    def test_val_test_fingerprint_excludes_data_yaml_but_full_dataset_includes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "val").mkdir(parents=True)
            (root / "images" / "val").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "val" / "a.txt").write_text("0 0 0 0 0\n", encoding="utf-8")
            (root / "images" / "val" / "a.jpg").write_bytes(b"image")

            val_before = build_character_dataset_file_fingerprint(root, splits=("val", "test"))
            full_before = build_character_dataset_file_fingerprint(root)
            (root / "data.yaml").write_text("path: .\nnames:\n  0: changed\n", encoding="utf-8")
            val_after = build_character_dataset_file_fingerprint(root, splits=("val", "test"))
            full_after = build_character_dataset_file_fingerprint(root)

            self.assertFalse(val_before["includes_config"])
            self.assertTrue(full_before["includes_config"])
            self.assertTrue(compare_character_val_test_unchanged(val_before, val_after)["unchanged"])
            self.assertNotEqual(full_before["sha256"], full_after["sha256"])

    def test_val_test_fingerprint_supports_split_first_yolo_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "val" / "labels").mkdir(parents=True)
            (root / "val" / "images").mkdir(parents=True)
            (root / "val" / "labels" / "a.txt").write_text("0 0 0 0 0\n", encoding="utf-8")
            (root / "val" / "images" / "a.jpg").write_bytes(b"image")

            fingerprint = build_character_dataset_file_fingerprint(root, splits=("val", "test"))

            self.assertEqual(fingerprint["mode"], "content_sha256")
            self.assertEqual(fingerprint["file_count"], 2)
            self.assertTrue(any(entry["relative_path"] == "val/labels/a.txt" for entry in fingerprint["entries"]))

    def test_val_test_fingerprint_detects_same_size_same_mtime_content_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            label_dir = root / "labels" / "val"
            label_dir.mkdir(parents=True)
            label_path = label_dir / "a.txt"
            label_path.write_text("0 0 0 0 0\n", encoding="utf-8")
            stamp = 1_700_000_000_000_000_000
            os.utime(label_path, ns=(stamp, stamp))

            before = build_character_dataset_file_fingerprint(root, splits=("val", "test"))
            label_path.write_text("1 0 0 0 0\n", encoding="utf-8")
            os.utime(label_path, ns=(stamp, stamp))
            after = build_character_dataset_file_fingerprint(root, splits=("val", "test"))

            self.assertEqual(before["entries"][0]["size"], after["entries"][0]["size"])
            self.assertNotEqual(before["sha256"], after["sha256"])

    def test_executor_empty_balance_plan_does_not_fall_back_to_random_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "base_dataset": str(root),
                "max_augmented_variants_per_source": 3,
                "candidates": [],
            }

            records, _limits, _initial, stats = _build_balance_augmented_source_state(
                root,
                [(root / "images" / "train" / "a.jpg", root / "labels" / "train" / "a.txt")],
                balance_plan=plan,
            )

            self.assertEqual(records, [])
            self.assertTrue(stats["balance_plan_enabled"])
            self.assertEqual(stats["balance_plan_candidates"], 0)
            self.assertEqual(stats["balance_pool"], 0)

    def test_balance_sample_size_preserves_target_priorities(self):
        pool = [
            {"source_key": "low", "label_key": "labels/train/low.txt", "priority": 1},
            {"source_key": "high", "label_key": "labels/train/high.txt", "priority": 100},
            {"source_key": "mid", "label_key": "labels/train/mid.txt", "priority": 10},
        ]

        selected = _select_augmentation_sample_pool(
            random.Random(42),
            list(pool),
            2,
            balance_plan_enabled=True,
        )

        self.assertEqual([row["source_key"] for row in selected], ["high", "mid"])

    def test_partial_train_augmentation_is_not_success(self):
        ok, message = _finalize_train_augmentation_result(
            {
                "generated": 357,
                "skipped": 4,
                "stop_reason": "wyczerpano limit kandydatów",
            },
            1000,
        )

        self.assertFalse(ok)
        self.assertIn("357 z 1000", message)
        self.assertIn("nie zostanie oznaczony jako gotowy", message)

    def test_real_source_search_counts_unused_sources_for_deficit_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            pool = Path(tmp) / "pool"
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            (root / "labels" / "train" / "many.txt").write_text("0 0 0 0 0\n" * 8, encoding="utf-8")
            (root / "labels" / "train" / "used_q.txt").write_text("26 0 0 0 0\n26 0 0 0 0\n", encoding="utf-8")
            pool.mkdir()
            records = [{"source_key": "used_q", "source_expected_text": "Q0"}]
            records.extend({"source_key": f"unused_q_{index}", "source_expected_text": f"AQ{index}"} for index in range(5))
            (pool / "metadata.json").write_text(json.dumps({"plates": records}), encoding="utf-8")

            result = find_character_real_source_candidates(root, (pool,), target_ratio=1.0)

            self.assertEqual(result["Q"]["current_unique_train"], 1)
            self.assertEqual(result["Q"]["available_unused_real_sources"], 5)

    def test_real_source_search_includes_low_diversity_without_deficit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            pool = Path(tmp) / "pool"
            (root / "labels" / "train").mkdir(parents=True)
            (root / "data.yaml").write_text(_names_list_yaml(), encoding="utf-8")
            for class_id in range(10):
                for index in range(5):
                    (root / "labels" / "train" / f"c{class_id}_{index}.txt").write_text(
                        f"{class_id} 0 0 0 0\n",
                        encoding="utf-8",
                    )
            (root / "labels" / "train" / "used_q.txt").write_text("26 0 0 0 0\n" * 6, encoding="utf-8")
            pool.mkdir()
            (pool / "metadata.json").write_text(
                json.dumps({"plates": [{"source_key": "unused_q", "source_expected_text": "AQ1"}]}),
                encoding="utf-8",
            )

            dist = analyze_character_class_distribution(root, target_ratio=0.5)
            q_row = {row.symbol: row for row in dist.classes}["Q"]
            result = find_character_real_source_candidates(root, (pool,), target_ratio=0.5)

            self.assertEqual(q_row.deficit_count, 0)
            self.assertEqual(q_row.diversity_status, "LOW_DIVERSITY")
            self.assertIn("Q", result)
            self.assertEqual(result["Q"]["available_unused_real_sources"], 1)

    def test_swapped_class_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            names = list(CHARACTER_BALANCE_ALPHABET)
            names[10], names[11] = names[11], names[10]
            yaml_text = "path: .\nnames:\n" + "".join(f"  - \"{symbol}\"\n" for symbol in names)
            (root / "data.yaml").write_text(yaml_text, encoding="utf-8")

            with self.assertRaises(CharacterClassMapValidationError) as ctx:
                analyze_character_class_distribution(root)

            self.assertEqual(ctx.exception.validation.first_mismatch_index, 10)

    def test_missing_class_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            names = list(CHARACTER_BALANCE_ALPHABET[:-1])
            yaml_text = "path: .\nnames:\n" + "".join(f"  - \"{symbol}\"\n" for symbol in names)
            (root / "data.yaml").write_text(yaml_text, encoding="utf-8")

            with self.assertRaises(CharacterClassMapValidationError) as ctx:
                analyze_character_class_distribution(root)

            self.assertEqual(ctx.exception.validation.first_mismatch_index, 35)

    def test_extra_class_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            names = list(CHARACTER_BALANCE_ALPHABET) + ["EXTRA"]
            yaml_text = "path: .\nnames:\n" + "".join(f"  - \"{symbol}\"\n" for symbol in names)
            (root / "data.yaml").write_text(yaml_text, encoding="utf-8")

            with self.assertRaises(CharacterClassMapValidationError) as ctx:
                analyze_character_class_distribution(root)

            self.assertEqual(ctx.exception.validation.first_mismatch_index, 36)

    def test_missing_data_yaml_is_allowed_only_for_flat_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels").mkdir()
            (root / "labels" / "flat.txt").write_text("0 0 0 0 0\n", encoding="utf-8")

            dist = analyze_character_class_distribution(root)

            self.assertEqual(dist.layout, "flat")
            self.assertEqual(dist.summary["class_map"]["status"], "WARNING")

    def test_missing_data_yaml_is_rejected_for_split_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)

            with self.assertRaises(CharacterClassMapValidationError):
                analyze_character_class_distribution(root)


if __name__ == "__main__":
    unittest.main()
