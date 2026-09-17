"""Deleting a draft must not teach future audits to accept/reject images."""
from dataclasses import asdict
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.audit_resolution import resolve_audit
from auto_annotation_tool.registry.participant_pool_audit import (
    ParticipantPoolAuditService, STATUS_CLEAN, STATUS_DEPENDENT, STATUS_SUSPECT, STATUS_UNKNOWN,
)
from auto_annotation_tool.gui.source_filename_review_dialog import build_source_review_rows, apply_source_review_actions


def repeated_pool(fixture, *, clean_count=3, suspect_count=14):
    paths = [fixture.image(f"CLEAN_{i:05d}.png", seed=700+i, size=(32,32)) for i in range(clean_count)]
    for i in range(suspect_count):
        path=fixture.sources/f"NEAR_{i:03d}.bmp"
        with Image.open(fixture.references["M2"]) as picture:
            picture.save(path)
        # Distinct bytes, same decoded pixels: all require a visual decision.
        with path.open("ab") as stream:
            stream.write(f"fixture-{i}".encode())
        paths.append(path)
    dependent=fixture.sources/"EXACT_001.png"
    dependent.write_bytes(fixture.references["M1"].read_bytes())
    unknown=fixture.sources/"BROKEN_001.png"
    unknown.write_bytes(b"invalid image")
    return paths+[dependent,unknown]


def verdicts(report):
    result=[]
    for item in report.candidates:
        row=asdict(item)
        row.pop("path")
        result.append(row)
    return sorted(result,key=lambda row:row["filename"])


def track_paths(fixture,track):
    root=fixture.workspace/fixture.service.get_track(track)["relative_path"]
    return [root/row["track_relative_path"] for row in fixture.service.list_members(track)]


def recreate_and_compare(fixture, paths, *, check_cold=True):
    service=fixture.service
    original={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    models=[item.model_id for item in fixture.audit.load_participants(fixture.track)]
    service.add_members_batch(fixture.track,paths)
    before=fixture.audit.audit_paths(fixture.track,track_paths(fixture,fixture.track))
    choices={item.path:"reject" for item in before.candidates if item.common_status==STATUS_SUSPECT}
    resolution=resolve_audit(before,choices)
    rejected={str(path) for path in resolution.rejected_paths}
    root=fixture.workspace/service.get_track(fixture.track)["relative_path"]
    indices=[row["member_index"] for row in service.list_members(fixture.track)
             if str(root/row["track_relative_path"]) in rejected]
    service.remove_members(fixture.track,indices)
    service.ensure_audit_manifest(fixture.track)
    fixture.audit.record_resolution(fixture.track,resolution,mode="pool")
    fixture.audit.assert_track_audit_ready(fixture.track)
    deleted=fixture.track
    service.delete_draft(deleted)
    assert fixture.repo.list_evaluation_track_audits(deleted)==[]
    assert original=={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    new=service.create_draft(name="Same models and full pool",target="plate",purpose="ranking")
    audit=ParticipantPoolAuditService(fixture.workspace,repository=fixture.repo)
    audit.save_participants(new,models)
    service.add_members_batch(new,paths)
    assert fixture.repo.list_evaluation_track_audits(new)==[]
    assert audit.get_track_audit_state(new)["status"]=="STALE"
    after=audit.audit_paths(new,track_paths(fixture,new))
    assert before.participant_fingerprint==after.participant_fingerprint
    assert verdicts(before)==verdicts(after)
    assert len(resolve_audit(after).unresolved)==after.suspect_count
    warm=audit.audit_paths(new,track_paths(fixture,new))
    assert verdicts(warm)==verdicts(after)
    assert warm.cache_misses_sha==0 and warm.cache_hits_phash>0
    # The deliberately unreadable image is retried, never cached as a successful pHash.
    assert warm.cache_misses_phash==1
    if check_cold:
        with patch.object(audit.cache,"get",return_value=None):
            cold=audit.audit_paths(new,track_paths(fixture,new))
        assert verdicts(cold)==verdicts(after)
    return {"images":len(paths),"suspects_before":before.suspect_count,
            "suspects_after":after.suspect_count,"dependent":after.dependent_count,
            "unknown":after.unknown_count,"clean":after.clean_count}


class RecreatedDraftAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture=PZ3Fixture(self.temp.name)

    def test_rejected_images_return_for_decision_in_new_draft_with_same_pool(self):
        result=recreate_and_compare(self.fixture,repeated_pool(self.fixture))
        self.assertEqual(result,dict(images=19,suspects_before=14,suspects_after=14,
                                     dependent=1,unknown=1,clean=3))

    def test_one_bad_filename_is_independent_of_fourteen_suspect_images(self):
        paths=repeated_pool(self.fixture)
        bad=self.fixture.image("bad.png",seed=919)
        paths.append(bad)
        rows=build_source_review_rows(paths)
        self.assertEqual([row.path for row in rows],[bad])
        before=self.fixture.audit.audit_paths(self.fixture.track,paths)
        self.assertEqual(before.suspect_count,14)
        result=apply_source_review_actions(self.fixture.sources,rename_stems={str(bad):"FIXED_001"})
        self.assertTrue(result.ok,result.error)
        paths[-1]=bad.with_name("FIXED_001.png")
        self.assertEqual(build_source_review_rows(paths),())
        after=self.fixture.audit.audit_paths(self.fixture.track,paths)
        self.assertEqual(after.suspect_count,14)
        self.assertEqual([(c.sha256,c.common_status) for c in before.candidates],
                         [(c.sha256,c.common_status) for c in after.candidates])


if __name__=="__main__":
    unittest.main()
