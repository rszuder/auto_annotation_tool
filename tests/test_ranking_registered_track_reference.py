import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.config import CONFIG
from auto_annotation_tool.gui.tab_training import TrainingTab
from auto_annotation_tool.registry.track_service import EvaluationTrackService


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def _gt(path: Path, image_name: str):
    path.write_text(
        (
            "<annotations>"
            f'<image id="0" name="{image_name}" width="100" height="50">'
            '<box label="plate" xtl="0" ytl="0" xbr="10" ybr="10"/>'
            "</image></annotations>"
        ),
        encoding="utf-8",
    )


class RankingRegisteredTrackReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.old_workspace = CONFIG.WORKSPACE_DIR
        CONFIG.WORKSPACE_DIR = self.workspace

        service = EvaluationTrackService(self.workspace)
        image = Path(self.temp.name) / "one.jpg"
        image.write_bytes(b"track-image")
        gt = Path(self.temp.name) / "gt.xml"
        _gt(gt, image.name)
        self.track_id = service.create_draft(
            name="E1A",
            target="plate",
            purpose="final_test",
            reservation_policy="reserve_from_training",
        )
        service.add_member(self.track_id, image)
        service.set_ground_truth(self.track_id, gt)
        service.verify(self.track_id)
        service.seal(self.track_id)
        track = service.get_track(self.track_id)
        self.track_root = self.workspace / track["relative_path"]

    def tearDown(self):
        CONFIG.WORKSPACE_DIR = self.old_workspace
        self.temp.cleanup()

    def _host(self):
        host = TrainingTab.__new__(TrainingTab)
        host.rank_data_dir = _Var(str(self.track_root))
        host._get_ranking_task_target = lambda: "plate"
        return host

    def test_pz3_track_uses_track_root_and_ground_truth(self):
        info = TrainingTab._resolve_ranking_reference_source(
            self._host()
        )
        self.assertTrue(info["ok"])
        self.assertEqual(info["track_id"], self.track_id)
        self.assertEqual(
            Path(info["reference_dir"]).resolve(),
            self.track_root.resolve(),
        )
        self.assertEqual(
            Path(info["xml_path"]).resolve(),
            (
                self.track_root
                / "ground_truth"
                / "annotations.xml"
            ).resolve(),
        )
        self.assertEqual(info["image_count"], 1)

    def test_tampered_pz3_track_is_rejected(self):
        (
            self.track_root
            / "images"
            / "one.jpg"
        ).write_bytes(b"tampered")
        info = TrainingTab._resolve_ranking_reference_source(
            self._host()
        )
        self.assertFalse(info["ok"])
        self.assertIn(
            "integral",
            str(info["message"]).lower(),
        )


if __name__ == "__main__":
    unittest.main()
