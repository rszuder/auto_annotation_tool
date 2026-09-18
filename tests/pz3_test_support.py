"""Small isolated Workspace with real images and a real SQLite registry."""
from pathlib import Path
import hashlib

import numpy as np
from PIL import Image

from auto_annotation_tool.registry.track_service import EvaluationTrackService
from auto_annotation_tool.registry.participant_pool_audit import ParticipantPoolAuditService


class PZ3Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.workspace = self.root / "Workspace"
        self.sources = self.root / "sources"
        self.sources.mkdir(parents=True, exist_ok=True)
        self.service = EvaluationTrackService(self.workspace)
        self.repo = self.service.repository
        self.audit = ParticipantPoolAuditService(self.workspace, repository=self.repo)
        self.references = {}
        for number in (1, 2, 3):
            path = self.image(f"REF_{number:03d}.png", seed=number)
            self.references[f"M{number}"] = path
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.repo.database.transaction() as db:
                db.execute("INSERT INTO source_images(source_image_id, canonical_sha256) VALUES (?, ?)",
                           (f"S{number}", sha))
                db.execute("INSERT INTO image_artifacts(artifact_id, source_image_id, external_path, sha256) VALUES (?, ?, ?, ?)",
                           (f"A{number}", f"S{number}", str(path), sha))
                db.execute("INSERT INTO datasets(dataset_id, target, provenance_status) VALUES (?, 'plate', 'complete')",
                           (f"D{number}",))
                db.execute("INSERT INTO dataset_members(dataset_id, artifact_id, source_image_id, split, file_sha256) VALUES (?, ?, ?, 'train', ?)",
                           (f"D{number}", f"A{number}", f"S{number}", sha))
                db.execute("INSERT INTO training_runs(run_id, target, dataset_id, provenance_status) VALUES (?, 'plate', ?, 'complete')",
                           (f"R{number}", f"D{number}"))
                db.execute("INSERT INTO models(model_id, run_id, target, yolo_family, yolo_scale, sha256, provenance_status) VALUES (?, ?, 'plate', 'YOLO26', ?, ?, 'complete')",
                           (f"M{number}", f"R{number}", ("n", "s", "m")[number - 1],
                            hashlib.sha256(f"M{number}".encode()).hexdigest()))
        self.track = self.service.create_draft(name="PZ3 integration", target="plate", purpose="ranking")
        self.audit.save_participants(self.track, ["M1", "M2"])

    def select_and_reaudit(self, track_id=None):
        """Commit the current pool as a final sample through the production services."""
        from auto_annotation_tool.registry.sample_selection import prepare_sample_selection
        track_id = track_id or self.track
        context = prepare_sample_selection(self.service, track_id)
        self.service.commit_sample_selection(
            track_id, keep_sha256=set(context["sample_member_sha256"].values()),
            expected_member_sha256=context["sample_member_sha256"],
            expected_audit_id=context["sample_audit_id"],
        )
        root = self.workspace / self.service.get_track(track_id)["relative_path"]
        paths = [root / row["track_relative_path"] for row in self.service.list_members(track_id)]
        report = self.audit.audit_paths(track_id, paths)
        self.audit.record_ingested_report(track_id, report, paths)


    def mark_gt_review_complete(self, xml_path):
        """Simulate completed manual GT review in a test fixture."""
        import json
        import xml.etree.ElementTree as ET

        xml_path = Path(xml_path)
        root = ET.parse(xml_path).getroot()

        approved = set()
        verified_empty = set()

        for node in root.findall("image"):
            name = str(
                Path(
                    str(node.get("name", "") or "").replace("\\", "/")
                ).name
                or ""
            ).strip().lower()
            if not name:
                continue

            has_plate = any(
                str(poly.get("label", "") or "").strip().lower()
                in {"plate", "license_plate", "numberplate"}
                for poly in node.findall("polygon")
            )

            if has_plate:
                approved.add(name)
            else:
                verified_empty.add(name)

        manifest_path = xml_path.parent / "run_manifest.json"
        payload = {}
        if manifest_path.is_file():
            payload = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            if not isinstance(payload, dict):
                payload = {}

        payload["approved_filenames"] = sorted(approved)
        payload["gt_verified_empty_filenames"] = sorted(verified_empty)

        manifest_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "approved_filenames": sorted(approved),
            "gt_verified_empty_filenames": sorted(verified_empty),
        }

    def image(self, name, seed=100, size=(192, 128)):
        path = self.sources / name
        pixels = np.random.default_rng(seed).integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
        Image.fromarray(pixels).save(path)
        return path

    def mixed(self):
        clean = self.image("IMG_001.png", seed=100)
        dependent = self.sources / "IMG_002.png"
        dependent.write_bytes(self.references["M1"].read_bytes())
        suspect = self.sources / "IMG_003.bmp"
        with Image.open(self.references["M2"]) as image:
            image.save(suspect)
        unknown = self.sources / "IMG_004.png"
        unknown.write_bytes(b"unreadable image")
        duplicate = self.sources / "IMG_005.png"
        duplicate.write_bytes(clean.read_bytes())
        return clean, dependent, suspect, unknown, duplicate

