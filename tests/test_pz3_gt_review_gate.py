
from pathlib import Path
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.sample_selection import (
    prepare_sample_selection,
)
from auto_annotation_tool.registry.experiment_gt_workspace import (
    prepare_gt_workspace,
    publish_working_gt,
    get_gt_review_state,
)
from auto_annotation_tool.registry.track_service import (
    EvaluationTrackError,
)


class Pz3GtReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)
        self.service = self.f.service
        self.track = self.f.track

        images = [
            self.f.image("A.png", seed=7101),
            self.f.image("B.png", seed=7102),
        ]
        self.service.add_members_batch(
            self.track,
            images,
        )

        root = self.service._track_root(
            self.service.get_track(self.track)
        )
        paths = [
            root / row["track_relative_path"]
            for row in self.service.list_members(
                self.track
            )
        ]
        report = self.f.audit.audit_paths(
            self.track,
            paths,
        )
        self.f.audit.record_ingested_report(
            self.track,
            report,
            paths,
        )

        context = prepare_sample_selection(
            self.service,
            self.track,
        )
        rows = self.service.list_members(self.track)
        self.service.commit_sample_selection(
            self.track,
            keep_sha256={
                row["sha256"] for row in rows
            },
            expected_member_sha256=(
                context["sample_member_sha256"]
            ),
            expected_audit_id=(
                context["sample_audit_id"]
            ),
        )

        self.context = prepare_gt_workspace(
            self.service,
            self.track,
            mode="manual",
        )
        self.xml = Path(
            self.context["annotation_path"]
        )
        self.manifest = (
            self.xml.parent / "run_manifest.json"
        )

    def _write_manifest(
        self,
        *,
        approved=(),
        empty=(),
    ):
        payload = json.loads(
            self.manifest.read_text(
                encoding="utf-8"
            )
        )
        payload["approved_filenames"] = list(
            approved
        )
        payload[
            "gt_verified_empty_filenames"
        ] = list(empty)
        self.manifest.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _add_plate(self, filename):
        tree = ET.parse(self.xml)
        node = next(
            n
            for n in tree.getroot().findall(
                "image"
            )
            if Path(
                n.get("name", "")
            ).name == filename
        )
        ET.SubElement(
            node,
            "polygon",
            label="plate",
            points=(
                "10,10;80,10;80,40;10,40"
            ),
        )
        tree.write(
            self.xml,
            encoding="utf-8",
            xml_declaration=True,
        )

    def test_publish_requires_every_member_reviewed(
        self,
    ):
        self._add_plate("A.png")
        self._write_manifest(
            approved=("a.png",),
        )

        state = get_gt_review_state(
            self.service,
            self.track,
            self.xml,
        )
        self.assertEqual(
            state["positive_ready"],
            1,
        )
        self.assertEqual(
            state["negative_ready"],
            0,
        )
        self.assertEqual(
            state["pending"],
            1,
        )

        with self.assertRaisesRegex(
            EvaluationTrackError,
            "nie jest kompletne",
        ):
            publish_working_gt(
                self.service,
                self.track,
                self.xml,
            )

        self._write_manifest(
            approved=("a.png",),
            empty=("b.png",),
        )
        state = get_gt_review_state(
            self.service,
            self.track,
            self.xml,
        )
        self.assertTrue(state["complete"])
        self.assertEqual(
            state["negative_ready"],
            1,
        )
        self.assertTrue(
            publish_working_gt(
                self.service,
                self.track,
                self.xml,
            ).is_file()
        )

    def test_negative_marker_invalid_if_plate_exists(
        self,
    ):
        self._add_plate("A.png")
        self._add_plate("B.png")
        self._write_manifest(
            approved=("a.png",),
            empty=("b.png",),
        )

        state = get_gt_review_state(
            self.service,
            self.track,
            self.xml,
        )
        self.assertFalse(state["complete"])
        self.assertEqual(state["pending"], 1)
        self.assertIn(
            "B.png",
            state["stale_negative_names"],
        )


if __name__ == "__main__":
    unittest.main()
