from pathlib import Path
import json
import tempfile
import unittest

from auto_annotation_tool.training.character_class_distribution import (
    CHARACTER_BALANCE_ALPHABET,
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
from auto_annotation_tool.training.dataset_augmentation import _build_balance_augmented_source_state


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
            self.assertEqual(manifest["selection_policy"], "deficit_weighted")
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
