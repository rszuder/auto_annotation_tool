import tempfile
from pathlib import Path
import unittest

from auto_annotation_tool.ranking.character_benchmark_metrics import (
    evaluate_character_predictions,
    inspect_character_ground_truth,
)


def write_xml(path):
    path.write_text(
        """<annotations>
<image id="0" name="A.jpg" width="200" height="70">
<box label="character" xtl="10" ytl="10" xbr="30" ybr="60"><attribute name="text">A</attribute></box>
<box label="character" xtl="40" ytl="10" xbr="60" ybr="60"><attribute name="text">B</attribute></box>
</image>
<image id="1" name="B.jpg" width="200" height="70">
<box label="character" xtl="10" ytl="10" xbr="30" ybr="60"><attribute name="text">C</attribute></box>
<box label="character" xtl="40" ytl="10" xbr="60" ybr="60"><attribute name="text">1</attribute></box>
</image>
</annotations>""",
        encoding="utf-8",
    )


class CharacterBenchmarkMetricsTests(unittest.TestCase):
    def test_contract_and_text_order(self):
        with tempfile.TemporaryDirectory() as temp:
            xml = Path(temp) / "annotations.xml"
            write_xml(xml)
            info = inspect_character_ground_truth(xml, expected_image_names={"A.jpg", "B.jpg"})
            self.assertTrue(info["char_sequence_ready"])
            self.assertEqual(info["char_gt_texts"]["A.jpg"], "AB")
            self.assertEqual(info["char_gt_texts"]["B.jpg"], "C1")

    def test_exact_match_and_cer(self):
        with tempfile.TemporaryDirectory() as temp:
            xml = Path(temp) / "annotations.xml"
            write_xml(xml)
            stats, _ = evaluate_character_predictions({"A.jpg": "AB", "B.jpg": "C2"}, xml)
            self.assertAlmostEqual(stats["exact_match_pct"], 50.0)
            self.assertAlmostEqual(stats["cer"], 0.25)
            self.assertEqual(stats["correct_characters"], 3)
            self.assertEqual(stats["incorrect_characters"], 1)

    def test_missing_read(self):
        with tempfile.TemporaryDirectory() as temp:
            xml = Path(temp) / "annotations.xml"
            write_xml(xml)
            stats, _ = evaluate_character_predictions({"A.jpg": "AB", "B.jpg": ""}, xml)
            self.assertEqual(stats["no_read_count"], 1)
            self.assertEqual(stats["missing_characters"], 2)


if __name__ == "__main__":
    unittest.main()
