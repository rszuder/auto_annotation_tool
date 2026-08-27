from pathlib import Path
import tempfile
import unittest

from auto_annotation_tool.training.character_class_distribution import (
    CHARACTER_BALANCE_ALPHABET,
    CHARACTER_TRAINING_VARIANT_SCHEMA,
    CharacterClassMapValidationError,
    analyze_character_class_distribution,
    build_character_training_variant_manifest,
    plan_character_train_augmentation,
    save_character_class_distribution_csv,
    save_character_class_distribution_json,
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

            manifest = build_character_training_variant_manifest(
                base_dataset=root,
                before_distribution=before,
                after_distribution=root / "after.json",
                plan=plan,
                sources={"real": 7, "augmented_real": 3},
            )

            self.assertEqual(manifest["schema"], CHARACTER_TRAINING_VARIANT_SCHEMA)
            self.assertEqual(manifest["alphabet"], CHARACTER_BALANCE_ALPHABET)
            self.assertEqual(manifest["selection_policy"], "deficit_weighted")
            self.assertEqual(manifest["sources"]["real"], 7)
            self.assertEqual(manifest["sources"]["augmented_real"], 3)
            self.assertEqual(manifest["sources"]["synthetic"], 0)
            self.assertEqual(manifest["augmentation"]["max_variants_per_source"], 4)
            self.assertEqual(manifest["before_distribution"], str(root))
            self.assertTrue(manifest["after_distribution"].endswith("after.json"))

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
