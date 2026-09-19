import tempfile
from pathlib import Path
import unittest

from auto_annotation_tool.registry.track_service import EvaluationTrackService, EvaluationTrackError
from auto_annotation_tool.ranking.model_ranking import ModelRankingEntry


class CharacterTrackContractTests(unittest.TestCase):
    def test_char_verification_sets_sequence_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xml = root / "annotations.xml"
            xml.write_text(
                """<annotations><image id="0" name="A.jpg" width="100" height="40">
<box label="character" xtl="1" ytl="1" xbr="10" ybr="30"><attribute name="text">A</attribute></box>
<box label="character" xtl="20" ytl="1" xbr="30" ybr="30"><attribute name="text">1</attribute></box>
</image></annotations>""",
                encoding="utf-8",
            )
            service = EvaluationTrackService(root / "Workspace")
            verification = service._verify_cvat_xml(
                {"target": "char"}, [{"original_name": "A.jpg"}], xml
            )
            self.assertTrue(verification["char_sequence_ready"])
            self.assertEqual(verification["char_sequence_count"], 1)

    def test_invalid_symbol_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xml = root / "annotations.xml"
            xml.write_text(
                """<annotations><image id="0" name="A.jpg" width="100" height="40">
<box label="character" xtl="1" ytl="1" xbr="10" ybr="30"><attribute name="text">?</attribute></box>
</image></annotations>""",
                encoding="utf-8",
            )
            service = EvaluationTrackService(root / "Workspace")
            with self.assertRaises(EvaluationTrackError):
                service._verify_cvat_xml(
                    {"target": "char"}, [{"original_name": "A.jpg"}], xml
                )

    def test_sequence_ranking_uses_exact_match(self):
        entry = ModelRankingEntry(
            model_name="mz.pt",
            model_path="mz.pt",
            date_evaluated="now",
            task_type="Znaki (Detect)",
            precision=99.0,
            recall=99.0,
            map50_95=99.0,
            metrics_source="MZ sequence benchmark",
            exact_match_pct=87.5,
            cer=0.04,
        )
        self.assertAlmostEqual(entry.ranking_score, 87.5)


if __name__ == "__main__":
    unittest.main()
