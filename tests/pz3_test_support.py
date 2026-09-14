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

