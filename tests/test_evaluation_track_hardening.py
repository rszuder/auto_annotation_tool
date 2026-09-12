import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import (
    RegistryDatabase,
    RegistryRepository,
    SCHEMA_VERSION,
)
from auto_annotation_tool.registry.schema import (
    SCHEMA_V1_STATEMENTS,
    SCHEMA_V2_STATEMENTS,
)
from auto_annotation_tool.registry.track_service import (
    ControlledTrackReference,
    EvaluationTrackError,
    EvaluationTrackService,
    INTEGRITY_FAIL,
    INTEGRITY_PASS,
)


class EvaluationTrackHardeningTests(unittest.TestCase):
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

    def _gt(self, *, polygon=True):
        shape = (
            '<polygon label="plate" points="0,0;10,0;10,10;0,10"/>'
            if polygon
            else '<box label="plate" xtl="0" ytl="0" xbr="10" ybr="10"/>'
        )
        xml = (
            "<annotations>"
            '<image id="0" name="one.jpg" width="100" height="50">'
            + shape
            + "</image></annotations>"
        )
        path = Path(self.temp.name) / "annotations.xml"
        path.write_text(xml, encoding="utf-8")
        return path

    def _sealed(self, *, polygon=True):
        track_id = self.service.create_draft(
            name="E1A",
            target="plate",
            purpose="final_test",
            reservation_policy="reserve_from_training",
        )
        self.service.add_member(track_id, self._image())
        self.service.set_ground_truth(
            track_id,
            self._gt(polygon=polygon),
        )
        self.service.verify(track_id)
        result = self.service.seal(track_id)
        self.assertEqual(result.status, INTEGRITY_PASS)
        return track_id

    def test_schema_v2_migrates_to_v3_with_seal_hash_column(self):
        db_path = Path(self.temp.name) / "legacy.sqlite3"
        connection = sqlite3.connect(str(db_path))
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            for statement in SCHEMA_V1_STATEMENTS:
                connection.execute(statement)
            for statement in SCHEMA_V2_STATEMENTS:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 2")
            connection.execute(
                """
                INSERT INTO evaluation_tracks (
                    track_id, name, target, purpose, scope, status,
                    version, relative_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TRK-OLD",
                    "Old",
                    "plate",
                    "ranking",
                    "global",
                    "DRAFT",
                    1,
                    "10_evaluation_tracks/plate/old",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        database = RegistryDatabase(db_path)
        self.assertEqual(database.initialize(), SCHEMA_VERSION)
        with database.read_connection() as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(evaluation_tracks)"
                ).fetchall()
            }
            count = connection.execute(
                """
                SELECT COUNT(*)
                FROM evaluation_tracks
                WHERE track_id = 'TRK-OLD'
                """
            ).fetchone()[0]

        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertIn("seal_sha256", columns)
        self.assertEqual(count, 1)

    def test_seal_hash_is_anchored_in_sqlite(self):
        track_id = self._sealed()
        track = self.service.get_track(track_id)
        root = self.workspace / track["relative_path"]
        actual = hashlib.sha256((root / "seal.json").read_bytes()).hexdigest()

        self.assertTrue(track["seal_sha256"])
        self.assertEqual(track["seal_sha256"], actual)
        self.assertEqual(
            self.service.verify_integrity(track_id).status,
            INTEGRITY_PASS,
        )

    def test_tampered_seal_json_is_detected(self):
        track_id = self._sealed()
        track = self.service.get_track(track_id)
        seal_path = self.workspace / track["relative_path"] / "seal.json"
        payload = json.loads(seal_path.read_text(encoding="utf-8"))
        payload["comment"] = "tampered"
        seal_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        result = self.service.verify_integrity(track_id)
        self.assertEqual(result.status, INTEGRITY_FAIL)
        self.assertTrue(
            any("seal.json" in issue for issue in result.issues)
        )

    def test_extra_file_inside_sealed_track_is_detected(self):
        track_id = self._sealed()
        track = self.service.get_track(track_id)
        extra = (
            self.workspace
            / track["relative_path"]
            / "images"
            / "extra.jpg"
        )
        extra.write_bytes(b"extra")

        result = self.service.verify_integrity(track_id)
        self.assertEqual(result.status, INTEGRITY_FAIL)
        self.assertTrue(
            any("nieujęty" in issue.lower() for issue in result.issues)
        )

    def test_controlled_reference_requires_sealed_track(self):
        track_id = self.service.create_draft(
            name="E1A",
            target="plate",
            purpose="final_test",
        )
        self.service.add_member(track_id, self._image())
        self.service.set_ground_truth(track_id, self._gt())
        self.service.verify(track_id)

        with self.assertRaises(EvaluationTrackError):
            self.service.build_controlled_reference(
                track_id,
                required_target="plate",
                require_pose_corners=True,
            )

        self.service.seal(track_id)
        reference = self.service.build_controlled_reference(
            track_id,
            required_target="plate",
            require_pose_corners=True,
        )
        self.assertIsInstance(reference, ControlledTrackReference)
        self.assertEqual(reference.track_id, track_id)
        self.assertEqual(reference.member_count, 1)
        self.assertEqual(len(reference.source_image_ids), 1)
        self.assertTrue(reference.pose_corner_ready)
        self.assertEqual(len(reference.reference_sha256), 64)
        self.assertEqual(len(reference.manifest_sha256), 64)
        self.assertEqual(len(reference.seal_sha256), 64)

    def test_pose_corner_requirement_blocks_box_only_gt(self):
        track_id = self._sealed(polygon=False)
        with self.assertRaises(EvaluationTrackError):
            self.service.build_controlled_reference(
                track_id,
                required_target="plate",
                require_pose_corners=True,
            )

    def test_duplicate_source_image_cannot_be_added_twice(self):
        track_id = self.service.create_draft(
            name="No duplicates",
            target="plate",
            purpose="ranking",
        )
        image = self._image()
        self.service.add_member(
            track_id,
            image,
            original_name="one.jpg",
        )

        with self.assertRaises(EvaluationTrackError):
            self.service.add_member(
                track_id,
                image,
                original_name="same-content-other-name.jpg",
            )

    def test_known_source_id_accepts_derived_artifact_sha(self):
        root_bytes = b"root-source"
        derived_bytes = b"derived-copy"
        root_sha = hashlib.sha256(root_bytes).hexdigest()
        derived_sha = hashlib.sha256(derived_bytes).hexdigest()

        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO source_images (
                    source_image_id, canonical_sha256, origin_status
                ) VALUES (?, ?, ?)
                """,
                ("SRC-KNOWN", root_sha, "known"),
            )
            connection.execute(
                """
                INSERT INTO image_artifacts (
                    artifact_id, source_image_id, relative_path,
                    sha256, size_bytes, kind
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "ART-DERIVED",
                    "SRC-KNOWN",
                    "derived.jpg",
                    derived_sha,
                    len(derived_bytes),
                    "derived_image",
                ),
            )

        derived = self._image("derived.jpg", derived_bytes)
        track_id = self.service.create_draft(
            name="Derived",
            target="plate",
            purpose="ranking",
        )
        self.service.add_member(
            track_id,
            derived,
            source_image_id="SRC-KNOWN",
            source_artifact_id="ART-DERIVED",
            original_name="derived.jpg",
        )

        member = self.service.list_members(track_id)[0]
        self.assertEqual(member["source_image_id"], "SRC-KNOWN")
        artifact = self.repo.fetch_rows(
            """
            SELECT derived_from_artifact_id
            FROM image_artifacts
            WHERE artifact_id = ?
            """,
            (member["track_artifact_id"],),
        )[0]
        self.assertEqual(
            artifact["derived_from_artifact_id"],
            "ART-DERIVED",
        )

    def test_source_artifact_must_match_copied_bytes(self):
        source_bytes = b"registered"
        different_bytes = b"different"
        source_sha = hashlib.sha256(source_bytes).hexdigest()

        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO source_images (
                    source_image_id, canonical_sha256, origin_status
                ) VALUES (?, ?, ?)
                """,
                ("SRC-A", source_sha, "known"),
            )
            connection.execute(
                """
                INSERT INTO image_artifacts (
                    artifact_id, source_image_id, relative_path,
                    sha256, size_bytes, kind
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "ART-A",
                    "SRC-A",
                    "registered.jpg",
                    source_sha,
                    len(source_bytes),
                    "dataset_image",
                ),
            )

        track_id = self.service.create_draft(
            name="Mismatch",
            target="plate",
            purpose="ranking",
        )
        with self.assertRaises((ValueError, EvaluationTrackError)):
            self.service.add_member(
                track_id,
                self._image("different.jpg", different_bytes),
                source_image_id="SRC-A",
                source_artifact_id="ART-A",
                original_name="different.jpg",
            )
        self.assertEqual(
            self.repo.table_count("evaluation_track_members"),
            0,
        )


    def test_unknown_explicit_source_id_is_rejected(self):
        track_id = self.service.create_draft(
            name="Unknown lineage",
            target="plate",
            purpose="ranking",
        )
        with self.assertRaises((ValueError, EvaluationTrackError)):
            self.service.add_member(
                track_id,
                self._image(),
                source_image_id="SRC-NOT-IN-REGISTRY",
            )
        self.assertEqual(
            self.repo.table_count("evaluation_track_members"),
            0,
        )

    def test_registry_manifest_divergence_is_detected(self):
        track_id = self._sealed()
        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                UPDATE evaluation_track_members
                SET original_name = 'changed.jpg'
                WHERE track_id = ?
                """,
                (track_id,),
            )

        result = self.service.verify_integrity(track_id)
        self.assertEqual(result.status, INTEGRITY_FAIL)
        self.assertTrue(
            any("rejestr" in issue.lower() for issue in result.issues)
        )


if __name__ == "__main__":
    unittest.main()
