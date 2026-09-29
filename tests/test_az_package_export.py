import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryDatabase
from auto_annotation_tool.registry.az_package_export import (
    AZPackageExportError,
    export_pz2_az_package,
)
from auto_annotation_tool.registry.az_package_transport import (
    analyze_az_package,
    load_az_package,
)
from auto_annotation_tool.registry.az_registry import (
    AZRegistry,
    crop_contract_sha256,
)
from auto_annotation_tool.registry.az_revision_store import (
    AZRevisionStore,
)
from auto_annotation_tool.registry.crop_identity import (
    build_pz1_crop_identity,
    compute_crop_identity_sha256,
)
from auto_annotation_tool.registry.pz2_az_adapter import (
    pz2_metadata_to_az_payload,
)


class AZPackageExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "Workspace"
        self.workspace.mkdir()

        self.db = RegistryDatabase(
            self.workspace / "_registry" / "alpr_registry.sqlite3"
        )
        self.registry = AZRegistry(
            self.db,
            workspace_dir=self.workspace,
        )
        self.registry.initialize()

        with self.db.transaction() as con:
            con.execute(
                """
                INSERT INTO projects(
                    project_id, display_name, folder_name, campaign_key
                ) VALUES (?, ?, ?, ?)
                """,
                ("PRJ-SOURCE", "Source", "Source_F00", "Source"),
            )
            con.execute(
                """
                INSERT INTO projects(
                    project_id, display_name, folder_name
                ) VALUES (?, ?, ?)
                """,
                ("PRJ-DEST", "Destination", "Dest_F00"),
            )

        self.preview = (
            self.workspace
            / "9_projects"
            / "Source_F00"
            / "3_cropped_characters"
            / "run_001"
        )
        self.images = self.preview / "images"
        self.images.mkdir(parents=True)

        self.rows = {}
        self._add_plate("plate_A", "a", "b", "A123")
        self._add_plate("plate_B", "c", "d", "B456")

        (self.preview / "metadata.json").write_text(
            json.dumps(self.rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _add_plate(
        self,
        plate_id,
        source_char,
        geometry_char,
        gt,
    ):
        source_sha = source_char * 64
        geometry_sha = geometry_char * 64
        image_identity = "img-sha256-" + source_sha

        identity = build_pz1_crop_identity(
            source_image_id=image_identity,
            source_annotation_id=f"ann-{plate_id}",
            source_geometry_hash=geometry_sha,
            interpolation="lanczos4",
            output_width=256,
            output_height=64,
        )
        identity_sha = compute_crop_identity_sha256(identity)
        contract_sha = crop_contract_sha256(
            identity["crop_contract"]
        )

        image_path = self.images / f"{plate_id}.jpg"
        image_bytes = f"crop-{plate_id}".encode("ascii")
        image_path.write_bytes(image_bytes)

        reg = self.registry.register_crop_artifact(
            crop_identity_sha256=identity_sha,
            identity_mode=identity["identity_mode"],
            source_file_sha256=source_sha,
            artifact_path=image_path,
            artifact_sha256=hashlib.sha256(
                image_bytes
            ).hexdigest(),
            size_bytes=len(image_bytes),
            width=256,
            height=64,
            source_annotation_id=f"ann-{plate_id}",
            source_geometry_hash=geometry_sha,
            crop_contract_sha256=contract_sha,
            project_id="PRJ-SOURCE",
            iteration_num=1,
            source_mode="pz1",
            source_plate_key=plate_id,
        )

        char = gt[0]
        row = {
            "source_file_sha256": source_sha,
            "source_image_id": image_identity,
            "source_annotation_id": f"ann-{plate_id}",
            "source_geometry_hash": geometry_sha,
            "crop_id": reg.crop_id,
            "crop_identity_sha256": identity_sha,
            "crop_identity_schema": identity["schema"],
            "crop_identity_mode": identity["identity_mode"],
            "crop_contract_sha256": contract_sha,
            "artifact_id": reg.artifact_id,
            "registry_source_image_id": reg.source_image_id,
            "plate_image_width": 256,
            "plate_image_height": 64,
            "plate_layout": "single_row",
            "plate_layout_override": "single_row",
            "layout_source": "manual_override",
            "characters": [{
                "character": char,
                "bbox": [20, 10, 60, 55],
                "reading_row": 1,
                "method": "manual",
                "source_kind": "local_manual",
                "confidence": 1.0,
            }],
            "ground_truth_text": gt,
            "status": "perfect",
            "gold_state": {
                "approved": True,
                "excluded": False,
                "candidate": True,
            },
            "source_info": {
                "bucket": "local_manual",
                "origin": "preview_editor",
            },
        }
        self.rows[plate_id] = row

        payload = pz2_metadata_to_az_payload(
            row,
            image_width=256,
            image_height=64,
        )
        AZRevisionStore(self.db).save_revision(
            crop_id=reg.crop_id,
            payload=payload,
            source_kind="local_manual",
            trust_state="local_manual",
            source_status="perfect",
            origin_project_id="PRJ-SOURCE",
            origin_iteration=1,
            bind_project_id="PRJ-SOURCE",
            effective_status="approved",
            created_at="2026-09-29T12:00:00+00:00",
        )

    def test_export_round_trip_is_loadable_and_importable_elsewhere(self):
        out = self.root / "export_all"

        result = export_pz2_az_package(
            self.registry,
            preview_dir=self.preview,
            project_id="PRJ-SOURCE",
            iteration_num=1,
            output_dir=out,
        )

        self.assertEqual(result.exported, 2)
        self.assertEqual(result.with_bound_revision, 2)
        self.assertTrue((out / "manifest.json").is_file())

        package = load_az_package(out)
        self.assertEqual(len(package.crops), 2)
        self.assertEqual(len(package.invalid_items), 0)

        plan = analyze_az_package(
            self.registry,
            package,
            target_project_id="PRJ-DEST",
        )
        self.assertEqual(plan.new_count, 2)
        self.assertEqual(plan.invalid_count, 0)
        self.assertEqual(plan.conflict_count, 0)

        manifest = json.loads(
            (out / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["source"]["project_id"],
            "PRJ-SOURCE",
        )
        self.assertEqual(manifest["source"]["iteration"], 1)
        self.assertEqual(
            manifest["source"]["scope"],
            "active_pz2_all",
        )

    def test_selected_scope_exports_only_requested_plate(self):
        out = self.root / "export_selected"

        result = export_pz2_az_package(
            self.registry,
            preview_dir=self.preview,
            project_id="PRJ-SOURCE",
            iteration_num=1,
            output_dir=out,
            plate_ids=["plate_B"],
        )

        self.assertEqual(result.exported, 1)
        package = load_az_package(out)
        self.assertEqual(len(package.crops), 1)
        self.assertEqual(package.crops[0].entry_id, "plate_B")

        manifest = json.loads(
            (out / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["source"]["scope"],
            "selected",
        )

    def test_export_preserves_current_az_and_revision_provenance(self):
        out = self.root / "export_provenance"

        result = export_pz2_az_package(
            self.registry,
            preview_dir=self.preview,
            project_id="PRJ-SOURCE",
            iteration_num=1,
            output_dir=out,
            plate_ids=["plate_A"],
        )

        self.assertEqual(result.with_bound_revision, 1)
        package = load_az_package(out)
        az = package.crops[0].az
        self.assertIsNotNone(az)
        self.assertEqual(az.origin_project_id, "PRJ-SOURCE")
        self.assertEqual(az.origin_iteration, 1)
        self.assertTrue(az.source_az_revision_id)
        self.assertEqual(
            az.payload["expected_text"],
            "A123",
        )

    def test_unprovable_identity_fails_without_partial_package(self):
        # Zmieniam lineage w metadata bez zmiany registry identity SHA.
        metadata_path = self.preview / "metadata.json"
        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
        metadata["plate_A"]["source_annotation_id"] = "wrong-ann"
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        out = self.root / "bad_export"
        with self.assertRaisesRegex(
            AZPackageExportError,
            "odtworzyć crop_identity",
        ):
            export_pz2_az_package(
                self.registry,
                preview_dir=self.preview,
                project_id="PRJ-SOURCE",
                iteration_num=1,
                output_dir=out,
                plate_ids=["plate_A"],
            )

        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
