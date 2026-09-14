import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.gt_preannotation import (
    compute_preannotation_metrics,
    normalize_profile,
)


PRE = """<annotations>
<image id="0" name="A.jpg" width="1000" height="600">
  <polygon label="plate" points="100,100;300,100;300,200;100,200"/>
  <polygon label="plate" points="600,100;700,100;700,160;600,160"/>
</image>
<image id="1" name="B.jpg" width="1000" height="600">
  <polygon label="plate" points="100,300;300,300;300,400;100,400"/>
</image>
</annotations>
"""

FINAL = """<annotations>
<image id="0" name="A.jpg" width="1000" height="600">
  <polygon label="plate" points="100,100;300,100;300,200;100,200"/>
  <polygon label="plate" points="610,105;710,105;710,165;610,165"/>
  <polygon label="plate" points="400,300;500,300;500,360;400,360"/>
</image>
<image id="1" name="B.jpg" width="1000" height="600">
</image>
</annotations>
"""


class PreannotationMetricsTests(unittest.TestCase):
    def test_profile_normalization(self):
        self.assertEqual(normalize_profile("stress_test"), "stress_test")
        self.assertEqual(normalize_profile("other"), "custom")

    def test_preannotation_to_final_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pre = root / "pre.xml"
            final = root / "final.xml"
            pre.write_text(PRE, encoding="utf-8")
            final.write_text(FINAL, encoding="utf-8")

            metrics = compute_preannotation_metrics(pre, final)

            self.assertEqual(metrics["predicted_objects"], 3)
            self.assertEqual(metrics["final_objects"], 3)
            self.assertEqual(metrics["matched_objects"], 2)
            self.assertEqual(metrics["false_positives"], 1)
            self.assertEqual(metrics["missed_objects"], 1)
            self.assertEqual(metrics["accepted_without_edit"], 1)
            self.assertEqual(metrics["geometry_corrected"], 1)
            self.assertAlmostEqual(metrics["auto_precision"], 2 / 3)
            self.assertAlmostEqual(metrics["auto_recall"], 2 / 3)
            self.assertGreater(metrics["mean_initial_corner_error"], 0.0)
            self.assertIn("niezależnego", metrics["metric_scope"])


if __name__ == "__main__":
    unittest.main()
