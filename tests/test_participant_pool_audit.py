import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.participant_pool_audit import (
    ParticipantModel,
    STATUS_CLEAN,
    STATUS_DEPENDENT,
    STATUS_SUSPECT,
    _PersistentFingerprintCache,
    common_status,
    participant_fingerprint,
)


class ParticipantPoolAuditTests(unittest.TestCase):
    def test_common_status_uses_union_of_participant_risk(self):
        self.assertEqual(common_status([STATUS_CLEAN, STATUS_DEPENDENT]), STATUS_DEPENDENT)
        self.assertEqual(common_status([STATUS_CLEAN, STATUS_SUSPECT]), STATUS_SUSPECT)
        self.assertEqual(common_status([STATUS_CLEAN, STATUS_CLEAN]), STATUS_CLEAN)

    def test_participant_fingerprint_is_order_independent(self):
        a = ParticipantModel("M1", "a"*64, "R1", "plate", "yolo26", "n", "complete")
        b = ParticipantModel("M2", "b"*64, "R2", "plate", "yolo26", "s", "complete")
        self.assertEqual(participant_fingerprint([a, b]), participant_fingerprint([b, a]))
        self.assertNotEqual(participant_fingerprint([a]), participant_fingerprint([a, b]))

    def test_cache_reuses_unchanged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            path = workspace / "IMG_001.jpg"
            path.write_bytes(b"abc")
            cache = _PersistentFingerprintCache(workspace)
            cache.put(path, sha256="x"*64, phash64="0"*16)
            cache.save()
            cache2 = _PersistentFingerprintCache(workspace)
            self.assertEqual(cache2.get(path)["sha256"], "x"*64)
            path.write_bytes(b"abcd")
            self.assertIsNone(cache2.get(path))


if __name__ == "__main__":
    unittest.main()
