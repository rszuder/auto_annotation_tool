import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from auto_annotation_tool.registry.repository import RegistryRepository
from auto_annotation_tool.registry.source_pool_audit import (
    STATUS_CLEAN,
    STATUS_DEPENDENT,
    STATUS_SUSPECT,
    SourcePoolIndependenceAuditService,
    format_source_pool_audit_summary,
)


class SourcePoolIndependenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.workspace.mkdir(parents=True)
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()
        self.dataset_root = (
            self.workspace
            / "4_training_datasets"
            / "plates"
            / "DS_REF"
        )
        self.train_dir = self.dataset_root / "images" / "train"
        self.train_dir.mkdir(parents=True)
        self.reference = self.train_dir / "ref.jpg"
        self._make_reference(self.reference)
        self.reference_sha = self._sha(self.reference)
        self._seed_training_reference()

    def tearDown(self):
        self.temp.cleanup()

    def _make_reference(self, path: Path):
        image = Image.new("RGB", (640, 480), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 40, 200, 440), fill="black")
        draw.ellipse((300, 120, 560, 380), fill="gray")
        image.save(path, quality=95)

    def _make_clean(self, path: Path):
        image = Image.new("RGB", (640, 480), "white")
        draw = ImageDraw.Draw(image)
        for y in range(0, 480, 40):
            for x in range(0, 640, 40):
                if (x // 40 + y // 40) % 2:
                    draw.rectangle(
                        (x, y, x + 39, y + 39),
                        fill="black",
                    )
        image.save(path, quality=92)

    def _seed_training_reference(self):
        dataset_rel = self.dataset_root.relative_to(
            self.workspace
        ).as_posix()
        artifact_rel = self.reference.relative_to(
            self.workspace
        ).as_posix()
        member_rel = self.reference.relative_to(
            self.dataset_root
        ).as_posix()

        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO source_images (
                    source_image_id,
                    canonical_sha256,
                    origin_status
                ) VALUES (?, ?, 'known')
                """,
                ("SRC-REF", self.reference_sha),
            )
            connection.execute(
                """
                INSERT INTO image_artifacts (
                    artifact_id,
                    source_image_id,
                    relative_path,
                    external_path,
                    sha256,
                    size_bytes,
                    kind
                ) VALUES (?, ?, ?, NULL, ?, ?, 'raw')
                """,
                (
                    "ART-REF",
                    "SRC-REF",
                    artifact_rel,
                    self.reference_sha,
                    self.reference.stat().st_size,
                ),
            )
            connection.execute(
                """
                INSERT INTO datasets (
                    dataset_id,
                    target,
                    name,
                    purpose,
                    relative_path,
                    provenance_status
                ) VALUES (
                    'DS-REF',
                    'plate',
                    'Reference',
                    'training',
                    ?,
                    'complete'
                )
                """,
                (dataset_rel,),
            )
            connection.execute(
                """
                INSERT INTO dataset_locations (
                    dataset_id,
                    location_key,
                    project_id,
                    relative_path,
                    external_path,
                    is_primary
                ) VALUES (
                    'DS-REF',
                    'loc-main',
                    NULL,
                    ?,
                    NULL,
                    1
                )
                """,
                (dataset_rel,),
            )
            connection.execute(
                """
                INSERT INTO dataset_members (
                    dataset_id,
                    artifact_id,
                    source_image_id,
                    split,
                    relative_path,
                    file_sha256
                ) VALUES (
                    'DS-REF',
                    'ART-REF',
                    'SRC-REF',
                    'train',
                    ?,
                    ?
                )
                """,
                (member_rel, self.reference_sha),
            )
            connection.execute(
                """
                INSERT INTO training_runs (
                    run_id,
                    target,
                    dataset_id,
                    status,
                    provenance_status
                ) VALUES (
                    'RUN-REF',
                    'plate',
                    'DS-REF',
                    'completed',
                    'complete'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO models (
                    model_id,
                    run_id,
                    target,
                    task_type,
                    sha256,
                    provenance_status
                ) VALUES (
                    'MODEL-REF',
                    'RUN-REF',
                    'plate',
                    'pose',
                    ?,
                    'complete'
                )
                """,
                ("f" * 64,),
            )

    @staticmethod
    def _sha(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _service(self):
        return SourcePoolIndependenceAuditService(
            self.workspace,
            repository=self.repo,
            suspect_hamming_threshold=8,
        )

    def test_exact_sha_is_dependent(self):
        candidate = Path(self.temp.name) / "same.jpg"
        candidate.write_bytes(self.reference.read_bytes())

        report = self._service().audit(
            [candidate],
            target="plate",
            purpose="ranking",
            track_id="TRK-X",
        )

        self.assertEqual(report.dependent_count, 1)
        item = report.items[0]
        self.assertEqual(item.status, STATUS_DEPENDENT)
        self.assertTrue(item.matches)
        self.assertEqual(item.matches[0].dataset_id, "DS-REF")
        self.assertEqual(item.matches[0].split, "train")

    def test_known_source_lineage_is_dependent_even_with_other_sha(self):
        candidate = Path(self.temp.name) / "derived.jpg"
        image = Image.open(self.reference)
        image.resize((320, 240)).save(candidate, quality=70)
        candidate_sha = self._sha(candidate)
        self.assertNotEqual(candidate_sha, self.reference_sha)

        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO image_artifacts (
                    artifact_id,
                    source_image_id,
                    external_path,
                    sha256,
                    size_bytes,
                    kind
                ) VALUES (?, ?, ?, ?, ?, 'derived')
                """,
                (
                    "ART-DERIVED",
                    "SRC-REF",
                    str(candidate),
                    candidate_sha,
                    candidate.stat().st_size,
                ),
            )

        report = self._service().audit(
            [candidate],
            target="plate",
            purpose="ranking",
        )

        self.assertEqual(report.items[0].status, STATUS_DEPENDENT)
        self.assertIn(
            "source_image_id",
            report.items[0].matches[0].reason,
        )

    def test_resized_recompressed_image_is_suspect(self):
        candidate = Path(self.temp.name) / "resized.jpg"
        image = Image.open(self.reference)
        image.resize((320, 240)).save(candidate, quality=68)

        report = self._service().audit(
            [candidate],
            target="plate",
            purpose="ranking",
        )

        item = report.items[0]
        self.assertEqual(item.status, STATUS_SUSPECT)
        self.assertIsNotNone(item.nearest_phash_distance)
        self.assertLessEqual(item.nearest_phash_distance, 8)

    def test_different_image_has_no_detected_dependence(self):
        candidate = Path(self.temp.name) / "clean.jpg"
        self._make_clean(candidate)

        report = self._service().audit(
            [candidate],
            target="plate",
            purpose="ranking",
        )

        self.assertEqual(report.items[0].status, STATUS_CLEAN)

    def test_report_contains_dependency_fraction_and_summary(self):
        exact = Path(self.temp.name) / "exact.jpg"
        exact.write_bytes(self.reference.read_bytes())
        clean = Path(self.temp.name) / "clean2.jpg"
        self._make_clean(clean)

        report = self._service().audit(
            [exact, clean],
            target="plate",
            purpose="ranking",
        )

        self.assertEqual(report.total_count, 2)
        self.assertEqual(report.dependent_count, 1)
        self.assertAlmostEqual(report.dependency_fraction, 0.5)
        summary = format_source_pool_audit_summary(report)
        self.assertIn("ZALEŻNE: 1", summary)
        self.assertIn("50.0%", summary)

    def test_report_is_saved_with_decision(self):
        candidate = Path(self.temp.name) / "clean3.jpg"
        self._make_clean(candidate)
        service = self._service()
        report = service.audit(
            [candidate],
            target="plate",
            purpose="ranking",
            track_id="TRK-X",
        )

        output = service.save_report(
            report,
            self.workspace / "10_experiments" / "results" / "plate" / "E1A",
            decision={
                "status": "accepted",
                "suspects_included": False,
            },
        )

        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["schema"],
            "alpr.source_pool_independence_audit.v1",
        )
        self.assertEqual(payload["decision"]["status"], "accepted")
        self.assertEqual(payload["track_id"], "TRK-X")


if __name__ == "__main__":
    unittest.main()
