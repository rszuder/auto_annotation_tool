from pathlib import Path
import tempfile
import unittest

from auto_annotation_tool.training.character_class_distribution import (
    analyze_character_class_distribution,
    save_character_class_distribution_csv,
    save_character_class_distribution_json,
)


class CharacterClassDistributionTests(unittest.TestCase):
    def test_split_counts_invalid_lines_and_unique_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "labels" / "train").mkdir(parents=True)
            (root / "labels" / "val").mkdir(parents=True)
            (root / "labels" / "test").mkdir(parents=True)
            (root / "data.yaml").write_text("path: .\nnames: []\n", encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
