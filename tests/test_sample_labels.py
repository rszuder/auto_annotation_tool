import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_pz3_reviewed_sample as sample_support
from auto_annotation_tool.registry.sample_labels import (
    SampleLabels, LABELS_FILE, LABELS_SCHEMA, MAX_LABEL_LENGTH, load_sample_labels,
)
from auto_annotation_tool.registry.sample_selection import (
    prepare_sample_selection, save_sample_review_draft, load_sample_review_draft,
)
from auto_annotation_tool.registry.track_service import EvaluationTrackError


class SampleLabelDataTests(unittest.TestCase):
    def setUp(self):
        self.selected = {"a", "b"}
        self.labels = SampleLabels(self.selected)
        self.night = self.labels.add(" Noc ")
        self.day = self.labels.add("Dzień")

    def test_one_label_per_selected_member(self):
        self.labels.assign(["a"], self.night)
        self.labels.assign(["a", "outside"], self.day)
        self.assertEqual(self.labels.assignments, {"a": self.day})
        self.assertEqual(self.labels.counts[self.night], 0)
        self.assertEqual(self.labels.counts[self.day], 1)

    def test_assignment_is_keyed_by_sha(self):
        self.labels.assign(["a", "renamed.jpg"], self.night)
        self.assertEqual(self.labels.payload("TRK")["assignments"], {"a": self.night})

    def test_removed_from_sample_loses_label(self):
        self.labels.assign(["a"], self.night)
        self.labels.set_membership(["a"], False)
        self.assertNotIn("a", self.selected)
        self.assertEqual(self.labels.assignments, {})
        self.assertEqual(self.labels.counts[self.night], 0)

    def test_label_change_does_not_change_sample_membership(self):
        before = set(self.selected)
        self.labels.assign(["a"], self.night)
        self.labels.assign(["a"], self.day)
        self.labels.rename(self.day, "Zmierzch")
        self.labels.delete(self.day)
        self.assertEqual(self.selected, before)
        self.assertEqual(self.labels.unlabeled_count, 2)

    def test_validation_and_rename_preserve_label_identity(self):
        for name in ("", "  ", "noc", " NOC ", "a" * (MAX_LABEL_LENGTH+1), "Noc\nDzień"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.labels.add(name)
        self.labels.assign(["a"], self.night)
        self.labels.rename(self.night, " NOC ")
        self.assertEqual(self.labels.assignments["a"], self.night)
        self.assertEqual(self.labels.labels[self.night], "NOC")
        with self.assertRaises(ValueError):
            self.labels.rename(self.night, "dzień")

    def test_label_counter_update_is_incremental(self):
        class NoScanDict(dict):
            def __iter__(self):
                raise AssertionError("No scan of all assignments")
            items = values = __iter__
        class NoScanSet(set):
            def __iter__(self):
                raise AssertionError("No scan of all selected members")
        self.labels.selected = NoScanSet(str(i) for i in range(10000))
        self.labels.assignments = NoScanDict()
        self.labels.assign(["4321"], self.night)
        self.assertEqual(self.labels.counts[self.night], 1)
        self.assertEqual(self.labels.unlabeled_count, 9999)
        self.labels.assign(["4321"], self.day)
        self.assertEqual(self.labels.counts[self.night], 0)
        self.assertEqual(self.labels.counts[self.day], 1)
        self.labels.set_membership(["4321"], False)
        self.assertEqual(self.labels.unlabeled_count, 9999)

    def test_locked_label_freezes_members_and_count_until_unlock(self):
        self.labels.assign(["a"], self.night)
        self.labels.set_label_locked(self.night, True)

        self.assertTrue(self.labels.is_sha_locked("a"))
        self.assertEqual(self.labels.assign(["a"], self.day), set())
        self.assertEqual(self.labels.set_membership(["a"], False), set())
        self.assertEqual(self.labels.assignments["a"], self.night)
        self.assertIn("a", self.selected)
        self.assertEqual(self.labels.counts[self.night], 1)

        self.labels.set_label_locked(self.night, False)
        self.assertEqual(self.labels.assign(["a"], self.day), {"a"})
        self.assertEqual(self.labels.assignments["a"], self.day)

    def test_locked_target_rejects_new_members_but_mixed_bulk_skips_only_locked(self):
        self.labels.assign(["a"], self.night)
        self.labels.assign(["b"], self.day)
        self.labels.set_label_locked(self.night, True)

        blocked = self.labels.blocked_for_assignment(["a", "b"], self.day)
        changed = self.labels.assign(["a", "b"], self.day)

        self.assertEqual(blocked, {"a"})
        self.assertEqual(changed, set())
        self.assertEqual(self.labels.assignments["a"], self.night)
        self.assertEqual(self.labels.assignments["b"], self.day)

        self.labels.set_label_locked(self.day, True)
        self.assertFalse(self.labels.can_assign("a", self.day))

    def test_unlabeled_lock_freezes_unlabeled_group(self):
        self.labels.assign(["a"], self.night)
        self.labels.set_unlabeled_locked(True)

        self.assertEqual(self.labels.assign(["b"], self.day), set())
        self.assertEqual(self.labels.set_membership(["b"], False), set())
        self.assertIn("b", self.selected)
        self.assertNotIn("b", self.labels.assignments)

        self.assertEqual(self.labels.assign(["a"], ""), set())
        self.assertEqual(self.labels.assignments["a"], self.night)

        self.labels.set_unlabeled_locked(False)
        self.assertEqual(self.labels.assign(["b"], self.day), {"b"})

    def test_locked_label_cannot_be_activated_renamed_or_deleted(self):
        self.labels.set_label_locked(self.night, True)
        with self.assertRaises(ValueError):
            self.labels.activate(self.night)
        with self.assertRaises(ValueError):
            self.labels.rename(self.night, "Noc 2")
        with self.assertRaises(ValueError):
            self.labels.delete(self.night)


class SampleLabelPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.case = sample_support.RawSampleSelectionTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.f, self.root = self.case.f, self.case.root
        self.members = self.case.context["sample_member_sha256"]
        self.labels = SampleLabels(set(self.members.values()))
        self.night = self.labels.add("Noc")
        self.labels.assign(self.members.values(), self.night)

    def commit(self):
        return self.case.commit(sample_labels=self.labels.payload(self.f.track))

    def save_labels(self, payload=None):
        members = {row["original_name"]: row["sha256"] for row in self.f.service.list_members(self.f.track)}
        return self.f.service.save_sample_labels(
            self.f.track, sample_labels=payload if payload is not None else self.labels.payload(self.f.track),
            expected_member_sha256=members)

    def test_sample_labels_are_optional(self):
        self.case.commit()
        self.assertFalse((self.root / LABELS_FILE).exists())
        self.case.reaudit()
        self.case.make_final_gt()
        self.f.service.verify(self.f.track, manual_gt_complete=True)
        self.assertTrue(self.f.service.seal(self.f.track).ok)

    def test_working_review_draft_roundtrips_and_is_removed_on_commit(self):
        selected = set(list(self.members.values())[:2])
        working = SampleLabels(selected)
        label = working.add("Noc")
        working.activate(label)
        working.assign(selected, label)
        save_sample_review_draft(
            self.f.service,
            self.f.track,
            selected_sha256=selected,
            sample_labels=working.payload(self.f.track),
            active_label=label,
            expected_member_sha256=self.members,
        )
        loaded = load_sample_review_draft(
            self.f.service,
            self.f.track,
            self.f.service.list_members(self.f.track),
        )
        self.assertEqual(set(loaded["selected_member_sha256"]), selected)
        self.assertEqual(loaded["active_label"], label)
        context = prepare_sample_selection(self.f.service, self.f.track)
        self.assertEqual(set(context["sample_initial_selected_sha256"]), selected)
        self.assertEqual(context["sample_active_label"], label)

        self.commit()
        self.assertIsNone(load_sample_review_draft(
            self.f.service,
            self.f.track,
            self.f.service.list_members(self.f.track),
        ))

    def test_sample_labels_json_roundtrip_and_commit_contains_only_retained_sha(self):
        self.commit()
        payload = load_sample_labels(self.root, self.f.track, self.case.keep)
        self.assertEqual(payload["schema"], LABELS_SCHEMA)
        self.assertEqual(set(payload["assignments"]), self.case.keep)
        self.assertEqual(payload["labels"], [{"id": self.night, "name": "Noc"}])
        selection = json.loads((self.root / "sample_selection.json").read_text(encoding="utf-8"))
        self.assertNotIn("labels", selection)
        self.assertNotIn("assignments", selection)
        self.case.reaudit()
        context = prepare_sample_selection(self.f.service, self.f.track)
        self.assertEqual(context["sample_labels"], payload)
        self.assertEqual(set(context["sample_committed_sha256"]), self.case.keep)

    def test_orphan_assignments_are_ignored_on_load(self):
        self.commit()
        payload = json.loads((self.root / LABELS_FILE).read_text(encoding="utf-8"))
        payload["assignments"]["orphan"] = self.night
        existing = next(iter(self.case.keep))
        payload["assignments"][existing] = "unknown-label"
        (self.root / LABELS_FILE).write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_sample_labels(self.root, self.f.track, self.case.keep)
        self.assertNotIn("orphan", loaded["assignments"])
        self.assertNotIn(existing, loaded["assignments"])

    def test_pool_growth_retains_known_labels_without_treating_sample_as_current(self):
        self.commit()
        extra = self.f.image("NEW_CANDIDATE.png", seed=7201)
        self.f.service.add_members_batch(self.f.track, [extra])
        self.case.reaudit()
        context = prepare_sample_selection(self.f.service, self.f.track)
        self.assertEqual(set(context["sample_initial_selected_sha256"]), self.case.keep)
        self.assertEqual(context["sample_committed_sha256"], [])
        self.assertEqual(context["candidate_count"], 7)
        labels = SampleLabels(set(context["sample_initial_selected_sha256"]), context["sample_labels"],
                              track_id=self.f.track)
        self.assertEqual(labels.counts[self.night], 6)

    def test_label_change_does_not_invalidate_audit_or_sample_commit(self):
        self.commit()
        self.case.reaudit()
        state = self.f.audit.get_track_audit_state(self.f.track)
        members = self.f.service.list_members(self.f.track)
        selection = (self.root / "sample_selection.json").read_bytes()
        self.labels.rename(self.night, "Zmierzch")
        self.save_labels()
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track), state)
        self.assertEqual(self.f.service.list_members(self.f.track), members)
        self.assertEqual((self.root / "sample_selection.json").read_bytes(), selection)
        self.assertTrue(self.f.service.get_preparation_state(self.f.track).can_prepare_gt)

    def test_deleting_last_label_removes_optional_artifact(self):
        self.commit()
        state = self.f.audit.get_track_audit_state(self.f.track)
        self.labels.delete(self.night)
        self.save_labels()
        self.assertFalse((self.root / LABELS_FILE).exists())
        manifest = self.f.service._read_json(self.root / "track_manifest.json")
        self.assertNotIn("sample_labels", manifest)
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track), state)

    def test_commit_failure_rolls_back_labels_membership_and_audit(self):
        before = (self.root / "track_manifest.json").read_bytes()
        original = Path.replace
        def fail(path, target):
            if Path(target).name == "track_manifest.json":
                raise OSError("disk full")
            return original(path, target)
        with patch.object(Path, "replace", fail), self.assertRaises(OSError):
            self.commit()
        self.case.assert_unchanged()
        self.assertFalse((self.root / LABELS_FILE).exists())
        self.assertEqual((self.root / "track_manifest.json").read_bytes(), before)
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "CURRENT")

    def test_metadata_write_failure_restores_previous_labels(self):
        self.commit()
        before = (self.root / LABELS_FILE).read_bytes()
        self.labels.rename(self.night, "Deszcz")
        original = self.f.service._atomic_json
        def fail(path, payload):
            if path.name == "track_manifest.json":
                raise OSError("disk full")
            return original(path, payload)
        with patch.object(self.f.service, "_atomic_json", side_effect=fail), self.assertRaises(OSError):
            self.save_labels()
        self.assertEqual((self.root / LABELS_FILE).read_bytes(), before)

    def test_metadata_update_rechecks_membership_and_rejects_wrong_track(self):
        self.commit()
        with self.assertRaises(EvaluationTrackError):
            self.f.service.save_sample_labels(self.f.track, sample_labels=self.labels.payload(self.f.track),
                                              expected_member_sha256=self.members)
        with self.assertRaises(ValueError):
            self.save_labels(self.labels.payload("different-track"))

    def test_database_commit_failure_restores_label_artifact(self):
        self.commit()
        before = {path: path.read_bytes() for path in (self.root / LABELS_FILE,
                                                       self.root / "track_manifest.json")}
        self.labels.rename(self.night, "Deszcz")
        original_connect = self.f.repo.database.connect
        class FailedCommit:
            def __init__(self, connection):
                self.connection = connection
            def __getattr__(self, name):
                return getattr(self.connection, name)
            def commit(self):
                raise OSError("DB commit failed")
        with patch.object(self.f.repo.database, "connect", side_effect=lambda: FailedCommit(original_connect())), \
             patch.object(self.f.service, "_atomic_json", wraps=self.f.service._atomic_json) as write, \
             self.assertRaisesRegex(OSError, "DB commit failed"):
            self.save_labels()
        self.assertEqual(write.call_count, 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_sample_labels_are_included_in_seal_and_mutation_fails_integrity(self):
        self.commit()
        self.case.reaudit()
        self.case.make_final_gt()
        self.f.service.verify(self.f.track, manual_gt_complete=True)
        sealed = self.f.service.seal(self.f.track)
        self.assertTrue(sealed.ok, sealed.issues)
        manifest = self.f.service._read_json(self.root / "track_manifest.json")
        self.assertIn(LABELS_FILE, manifest["experiment_contract"]["artifacts"])
        self.assertIn(LABELS_FILE, {row["path"] for row in self.f.service._read_json(self.root / "seal.json")["files"]})
        before = (self.root / LABELS_FILE).read_bytes()
        with self.assertRaises(EvaluationTrackError):
            self.save_labels()
        self.assertEqual((self.root / LABELS_FILE).read_bytes(), before)
        (self.root / LABELS_FILE).write_bytes(before + b" ")
        self.assertFalse(self.f.service.verify_integrity(self.f.track).ok)


    def test_remove_members_prunes_orphan_sample_label_assignments(self):
        self.commit()
        labels_path = self.root / LABELS_FILE
        before = json.loads(labels_path.read_text(encoding="utf-8"))
        self.assertTrue(before["assignments"])

        member = self.f.service.list_members(self.f.track)[0]
        removed_sha = str(member["sha256"]).lower()
        self.assertIn(removed_sha, before["assignments"])

        self.f.service.remove_members(self.f.track, [member["member_index"]])

        after = json.loads(labels_path.read_text(encoding="utf-8"))
        current = {
            str(row["sha256"]).lower()
            for row in self.f.service.list_members(self.f.track)
        }
        self.assertNotIn(removed_sha, after["assignments"])
        self.assertTrue(set(after["assignments"]).issubset(current))
        self.assertEqual(after["labels"], before["labels"])


    def test_seal_rejects_orphan_sample_label_assignment(self):
        self.commit()
        self.case.reaudit()
        self.case.make_final_gt()
        self.f.service.verify(self.f.track, manual_gt_complete=True)

        labels_path = self.root / LABELS_FILE
        payload = json.loads(labels_path.read_text(encoding="utf-8"))
        payload["assignments"]["f" * 64] = self.night
        labels_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(EvaluationTrackError, "etykiet"):
            self.f.service.seal(self.f.track)

    def test_working_review_draft_persists_label_locks(self):
        selected = set(list(self.members.values())[:2])
        working = SampleLabels(selected)
        label = working.add("Noc")
        working.assign(selected, label)
        working.set_label_locked(label, True)
        working.set_unlabeled_locked(True)

        save_sample_review_draft(
            self.f.service,
            self.f.track,
            selected_sha256=selected,
            sample_labels=working.payload(self.f.track),
            active_label="",
            locked_label_ids=working.locked_label_ids,
            unlabeled_locked=working.unlabeled_locked,
            expected_member_sha256=self.members,
        )

        loaded = load_sample_review_draft(
            self.f.service,
            self.f.track,
            self.f.service.list_members(self.f.track),
        )
        self.assertEqual(set(loaded["locked_label_ids"]), {label})
        self.assertTrue(loaded["unlabeled_locked"])

        context = prepare_sample_selection(
            self.f.service, self.f.track
        )
        self.assertEqual(
            set(context["sample_locked_label_ids"]), {label}
        )
        self.assertTrue(context["sample_unlabeled_locked"])



if __name__ == "__main__":
    unittest.main()
