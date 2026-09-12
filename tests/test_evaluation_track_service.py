import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryRepository
from auto_annotation_tool.registry.track_service import (
    EvaluationTrackError,
    EvaluationTrackService,
    INTEGRITY_FAIL,
    INTEGRITY_PASS,
    STATUS_DRAFT,
    STATUS_RETIRED,
    STATUS_SEALED,
    STATUS_VERIFIED,
)


class EvaluationTrackServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.service = EvaluationTrackService(self.workspace)
        self.repo = RegistryRepository.for_workspace(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def _image(self, name="one.jpg", payload=b"image"):
        path = Path(self.temp.name) / name
        path.write_bytes(payload)
        return path

    def _gt(self, names=("one.jpg",), polygons=True, bad_polygon=False):
        images = []
        for idx, name in enumerate(names):
            if polygons:
                points = "0,0;10,0;10,10" if bad_polygon else "0,0;10,0;10,10;0,10"
                shape = f'<polygon label="plate" points="{points}"/>'
            else:
                shape = '<box label="plate" xtl="0" ytl="0" xbr="10" ybr="10"/>'
            images.append(
                f'<image id="{idx}" name="{name}" width="100" height="50">{shape}</image>'
            )
        xml = "<annotations>" + "".join(images) + "</annotations>"
        path = Path(self.temp.name) / "annotations.xml"
        path.write_text(xml, encoding="utf-8")
        return path

    def _draft_with_member_and_gt(self, *, polygons=True):
        track_id = self.service.create_draft(
            name="E1A MT",
            target="plate",
            purpose="final_test",
            scope="global",
            reservation_policy="reserve_from_training",
        )
        self.service.add_member(track_id, self._image())
        self.service.set_ground_truth(
            track_id,
            self._gt(polygons=polygons),
            gt_format="cvat_xml",
        )
        return track_id

    def test_create_draft_writes_db_and_manifest(self):
        track_id = self.service.create_draft(
            name="Track A",
            target="plate",
            purpose="ranking",
        )
        track = self.service.get_track(track_id)
        self.assertEqual(track["status"], STATUS_DRAFT)
        self.assertEqual(track["version"], 1)
        manifest = (
            self.workspace
            / track["relative_path"]
            / "track_manifest.json"
        )
        self.assertTrue(manifest.exists())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["track_id"], track_id)
        self.assertEqual(payload["members"], [])

    def test_add_member_registers_source_artifact_and_member(self):
        track_id = self.service.create_draft(
            name="Track A",
            target="plate",
            purpose="ranking",
        )
        self.service.add_member(track_id, self._image())

        self.assertEqual(self.repo.table_count("source_images"), 1)
        self.assertEqual(self.repo.table_count("image_artifacts"), 1)
        self.assertEqual(self.repo.table_count("evaluation_track_members"), 1)
        members = self.service.list_members(track_id)
        self.assertEqual(members[0]["original_name"], "one.jpg")
        track = self.service.get_track(track_id)
        copied = self.workspace / track["relative_path"] / "images" / "one.jpg"
        self.assertTrue(copied.exists())

    def test_verify_cvat_xml_moves_track_to_verified(self):
        track_id = self._draft_with_member_and_gt(polygons=True)
        result = self.service.verify(track_id)
        track = self.service.get_track(track_id)

        self.assertEqual(track["status"], STATUS_VERIFIED)
        self.assertEqual(track["member_count"], 1)
        self.assertEqual(track["object_count"], 1)
        self.assertEqual(result["quad_polygon_count"], 1)
        self.assertTrue(result["pose_corner_ready"])

    def test_verify_rejects_gt_with_wrong_image_set(self):
        track_id = self.service.create_draft(
            name="Track A",
            target="plate",
            purpose="ranking",
        )
        self.service.add_member(track_id, self._image())
        self.service.set_ground_truth(
            track_id,
            self._gt(names=("other.jpg",)),
        )

        with self.assertRaises(EvaluationTrackError):
            self.service.verify(track_id)
        self.assertEqual(self.service.get_track(track_id)["status"], STATUS_DRAFT)

    def test_verify_rejects_non_quad_polygon(self):
        track_id = self.service.create_draft(
            name="Track A",
            target="plate",
            purpose="ranking",
        )
        self.service.add_member(track_id, self._image())
        self.service.set_ground_truth(
            track_id,
            self._gt(bad_polygon=True),
        )
        with self.assertRaises(EvaluationTrackError):
            self.service.verify(track_id)

    def test_seal_creates_seal_json_and_integrity_passes(self):
        track_id = self._draft_with_member_and_gt()
        self.service.verify(track_id)
        result = self.service.seal(track_id)
        track = self.service.get_track(track_id)

        self.assertEqual(track["status"], STATUS_SEALED)
        self.assertEqual(result.status, INTEGRITY_PASS)
        self.assertTrue(track["manifest_sha256"])
        seal = self.workspace / track["relative_path"] / "seal.json"
        self.assertTrue(seal.exists())

    def test_sealed_track_rejects_mutation(self):
        track_id = self._draft_with_member_and_gt()
        self.service.verify(track_id)
        self.service.seal(track_id)

        with self.assertRaises(EvaluationTrackError):
            self.service.add_member(track_id, self._image("two.jpg", b"two"))
        with self.assertRaises(EvaluationTrackError):
            self.service.set_ground_truth(track_id, self._gt())

    def test_tampering_is_detected(self):
        track_id = self._draft_with_member_and_gt()
        self.service.verify(track_id)
        self.service.seal(track_id)
        track = self.service.get_track(track_id)
        copied = self.workspace / track["relative_path"] / "images" / "one.jpg"
        copied.write_bytes(b"tampered")

        result = self.service.verify_integrity(track_id)
        self.assertEqual(result.status, INTEGRITY_FAIL)
        self.assertTrue(result.issues)

    def test_clone_creates_next_draft_version_with_parent(self):
        track_id = self._draft_with_member_and_gt()
        self.service.verify(track_id)
        self.service.seal(track_id)

        clone_id = self.service.clone_new_version(track_id)
        clone = self.service.get_track(clone_id)
        self.assertEqual(clone["status"], STATUS_DRAFT)
        self.assertEqual(clone["version"], 2)
        self.assertEqual(clone["parent_track_id"], track_id)
        self.assertEqual(len(self.service.list_members(clone_id)), 1)
        self.assertTrue(clone["gt_relative_path"])

    def test_retire_preserves_seal_and_integrity(self):
        track_id = self._draft_with_member_and_gt()
        self.service.verify(track_id)
        self.service.seal(track_id)
        before = self.service.verify_integrity(track_id)
        self.service.retire(track_id)
        after = self.service.verify_integrity(track_id)

        self.assertEqual(self.service.get_track(track_id)["status"], STATUS_RETIRED)
        self.assertEqual(before.status, INTEGRITY_PASS)
        self.assertEqual(after.status, INTEGRITY_PASS)


if __name__ == "__main__":
    unittest.main()
