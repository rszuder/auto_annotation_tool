import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.track_service import EvaluationTrackService


class EvaluationTrackBatchAddTests(unittest.TestCase):
    def test_batch_add_writes_manifest_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            service = EvaluationTrackService(workspace)
            track_id = service.create_draft(
                name="batch", target="plate", purpose="validation"
            )
            paths = []
            for index in range(5):
                path = workspace / f"IMG_{index:03d}.jpg"
                path.write_bytes(f"image-{index}".encode("ascii"))
                paths.append(path)
            original = service._write_manifest
            calls = []
            def spy(*args, **kwargs):
                calls.append(1)
                return original(*args, **kwargs)
            service._write_manifest = spy
            service.add_members_batch(track_id, paths)
            self.assertEqual(len(service.list_members(track_id)), 5)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
