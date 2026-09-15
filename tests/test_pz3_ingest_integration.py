import json
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.config import CONFIG
from auto_annotation_tool.gui.z4_evaluation_tracks import EvaluationTracksPanel
from auto_annotation_tool.gui.pz3_source_ingest_ui import PZ3SourceSelection
from auto_annotation_tool.gui.source_filename_review_dialog import SourceReviewSelectionResult
from auto_annotation_tool.gui.pz3_participant_audit import BatchProgressDialog


GUI = "auto_annotation_tool.gui.z4_evaluation_tracks."


class PZ3IngestIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PZ3Fixture(self.temp.name)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.callback_errors = []
        self.root.report_callback_exception = lambda *args: self.callback_errors.append(args)
        for name, value in {
            "WORKSPACE_DIR": self.f.workspace,
            "DIR_10_EXPERIMENTS": self.f.workspace / "10_experiments",
            "DIR_10_EXPERIMENT_SOURCES": self.f.workspace / "10_experiments" / "sources",
            "DIR_10_EXPERIMENT_STATE": self.f.workspace / "10_experiments" / "_state",
            "DIR_10_EXPERIMENT_ANNOTATIONS": self.f.workspace / "10_experiments" / "annotations",
        }.items():
            self.enterContext(patch.object(CONFIG, name, value, create=True))
        self.enterContext(patch(GUI + "CAMPAIGN.get_active_project_name", return_value=""))
        self.messages = self.enterContext(patch(GUI + "messagebox"))
        self.messages.askyesno.return_value = True
        self.messages.askokcancel.return_value = True
        self.messages.askyesnocancel.return_value = False
        self.audit_default_choice = "reject"
        self.audit_choices = {}
        self.audit_cancel = False
        self.audit_reports = []
        self.enterContext(patch(GUI + "ParticipantAuditMatrixDialog.show",
                                autospec=True, side_effect=self.resolve_dialog))
        self.panel = EvaluationTracksPanel(self.root, SimpleNamespace(app=None))
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.root.update()
        self.errors = self.enterContext(patch.object(self.panel, "_show_error"))

    def resolve_dialog(self, dialog):
        from auto_annotation_tool.registry.participant_pool_audit import STATUS_SUSPECT
        self.audit_reports.append(dialog.report)
        if self.audit_cancel:
            dialog._cancel()
        else:
            if self.audit_default_choice == "reject":
                dialog._reject_all_suspects()
            for index, item in enumerate(dialog.report.candidates):
                if item.common_status == STATUS_SUSPECT:
                    choice = self.audit_choices.get(item.filename, self.audit_default_choice)
                    if choice != "reject" or self.audit_default_choice != "reject":
                        dialog.set_decision(index, choice)
            dialog._apply()
        return dialog.result

    def tearDown(self):
        self.assertEqual(self.callback_errors, [])

    def ingest(self, paths, folder=False):
        if folder:
            import shutil
            directory = Path(self.temp.name) / "selected"
            directory.mkdir(exist_ok=True)
            for path in paths:
                shutil.copy2(path, directory / path.name)
            selection = PZ3SourceSelection("folder", (), str(directory))
        else:
            selection = PZ3SourceSelection("files", tuple(paths))
        with patch(GUI + "choose_pz3_source_candidates", return_value=selection):
            self.panel.add_images()
        self.root.update()
        return len(self.panel.member_tree.get_children())

    def success_text(self):
        messages = [c.args[1] for c in self.messages.showinfo.call_args_list
                    if c.args[0] == "Dodawanie obrazów zakończone"]
        return messages[-1] if messages else ""

    def test_mixed_folder_adds_clean_and_updates_actual_table(self):
        self.panel._layout.notebook.select(self.panel._layout.details_page)
        self.assertEqual(self.ingest(self.f.mixed(), folder=True), 1)
        self.errors.assert_not_called()
        self.messages.showerror.assert_not_called()
        self.assertIn("Dodano do toru: 1", self.success_text())
        for line in ("Duplikaty w wyborze: 1", "Pominięte zależne: 1",
                     "Pominięte nieustalone: 1", "Pominięte po weryfikacji: 1"):
            self.assertIn(line, self.success_text())
        self.assertEqual(self.panel._layout.notebook.select(), str(self.panel._layout.images_page))
        self.assertEqual(len(self.f.service.list_members(self.f.track)), 1)
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)

    def test_yes_adds_suspect_with_recorded_acknowledgement(self):
        self.audit_default_choice = "accept"
        self.assertEqual(self.ingest(self.f.mixed()), 2)
        self.assertIn("Dodano do toru: 2", self.success_text())
        state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.assertEqual(len(state["accepted_suspect_sha256"]), 1)

    def test_new_ingest_does_not_reask_about_previously_accepted_images(self):
        clean, _, suspect, *_ = self.f.mixed()
        self.audit_default_choice = "accept"
        self.ingest([suspect])
        self.messages.reset_mock()
        self.audit_default_choice = "reject"
        self.assertEqual(self.ingest([clean]), 2)
        self.assertEqual(len(self.audit_reports[-1].candidates), 1)
        self.assertEqual(self.audit_reports[-1].candidates[0].filename, clean.name)
        self.messages.askyesno.assert_not_called()
        self.messages.askyesnocancel.assert_not_called()
        self.messages.askokcancel.assert_not_called()
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)

    def test_existing_invalid_pool_does_not_block_new_clean_images(self):
        clean, dependent, *_ = self.f.mixed()
        self.f.service.add_members_batch(self.f.track, [dependent])
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.assertEqual(self.ingest([clean]), 2)
        state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.assertEqual(state["status"], "STALE")
        self.assertEqual("Audyt: nieaktualny", self.panel._layout.audit_var.get())
        self.errors.assert_not_called()

    def test_current_audit_rejects_problem_images_in_the_same_flow(self):
        paths = self.f.mixed()[:4]
        self.f.service.add_members_batch(self.f.track, paths)
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.messages.reset_mock()
        self.panel.audit_current_pool()
        self.assertEqual(len(self.f.service.list_members(self.f.track)), 1)
        self.assertEqual(len(self.panel.member_tree.get_children()), 1)
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)
        self.messages.askyesno.assert_not_called()
        self.messages.askyesnocancel.assert_not_called()
        self.messages.askokcancel.assert_not_called()
        self.messages.showwarning.assert_not_called()
        self.errors.assert_not_called()
        self.assertTrue(all(path.exists() for path in paths))

    def test_current_audit_accepts_selected_suspect_and_persists_state(self):
        paths = self.f.mixed()[:4]
        self.f.service.add_members_batch(self.f.track, paths)
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.audit_choices[paths[2].name] = "accept"
        self.panel.audit_current_pool()
        self.assertEqual(len(self.f.service.list_members(self.f.track)), 2)
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.assertEqual("Audyt: aktualny", self.panel._layout.audit_var.get())
        self.assertIn("Ręcznie zweryfikowane: 1", self.panel.detail_text.get("1.0", "end"))
        self.errors.assert_not_called()

    def test_cancel_current_pool_preserves_members_gt_and_audit(self):
        paths = self.f.mixed()[:4]
        self.f.service.add_members_batch(self.f.track, paths)
        before = self.f.service.list_members(self.f.track)
        state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.audit_cancel = True
        self.panel.audit_current_pool()
        self.assertEqual(self.f.service.list_members(self.f.track), before)
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track), state)
        self.assertEqual(self.f.repo.list_evaluation_track_audits(self.f.track), [])

    def test_cancel_suspect_decision_does_not_change_draft(self):
        before = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.audit_cancel = True
        self.assertEqual(self.ingest(self.f.mixed()), 0)
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track), before)
        self.assertEqual(self.success_text(), "")

    def test_repeated_folder_is_duplicate_and_preserves_current_audit(self):
        clean = self.f.mixed()[0]
        self.assertEqual(self.ingest([clean], folder=True), 1)
        before = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        with patch.object(self.panel, "_run_participant_pool_audit") as run_audit:
            self.assertEqual(self.ingest([clean], folder=True), 1)
        run_audit.assert_not_called()
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track), before)
        self.assertIn("Już w torze: 1", self.messages.showinfo.call_args.args[1])

    def test_no_acceptable_candidates_preserves_existing_audit(self):
        clean, dependent, *_ = self.f.mixed()
        self.ingest([clean])
        before = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.assertEqual(self.ingest([dependent]), 1)
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track), before)

    def test_review_renamed_path_is_still_audited_and_added(self):
        bad = self.f.image("bad.png")
        renamed = bad.with_name("IMG_004.png")
        def review(*args, **kwargs):
            bad.rename(renamed)
            return SourceReviewSelectionResult(True, accepted_paths=(renamed,), renamed=1)
        with patch(GUI + "review_source_image_paths", side_effect=review):
            self.assertEqual(self.ingest([bad]), 1)
        row = self.f.service.list_members(self.f.track)[0]
        self.assertEqual(row["original_name"], "IMG_004.png")
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)

    def test_logical_duplicate_does_not_block_other_clean_images(self):
        import hashlib
        clean = self.f.image("IMG_006.png")
        self.ingest([clean])
        source_id = self.f.service.list_members(self.f.track)[0]["source_image_id"]
        alias = self.f.image("IMG_007.png", seed=701)
        other = self.f.image("IMG_008.png", seed=702)
        with self.f.repo.database.transaction() as db:
            db.execute(
                "INSERT INTO image_artifacts(artifact_id, source_image_id, external_path, sha256) VALUES (?, ?, ?, ?)",
                ("ALIAS", source_id, str(alias), hashlib.sha256(alias.read_bytes()).hexdigest()),
            )
        self.assertEqual(self.ingest([alias, other]), 2)
        self.assertIn("Dodano do toru: 1", self.success_text())
        self.assertIn("Już w torze: 1", self.success_text())
        self.errors.assert_not_called()

    def test_manifest_failure_reloads_committed_rows_without_success_message(self):
        with patch.object(self.panel.service, "_write_manifest", side_effect=OSError("disk full")):
            self.assertEqual(self.ingest([self.f.image("IMG_006.png")]), 1)
        self.errors.assert_called_once()
        self.assertEqual(self.success_text(), "")

    def test_ranking_requires_participants_but_validation_can_add(self):
        ranking = self.f.service.create_draft(name="empty ranking", target="plate", purpose="ranking")
        self.panel.refresh_tracks(select_track_id=ranking)
        self.assertEqual(str(self.panel.btn_add_images["state"]), "disabled")
        self.assertEqual(str(self.panel.btn_audit_pool["state"]), "disabled")
        with patch(GUI + "choose_pz3_source_candidates") as choose:
            self.panel.add_images()
        choose.assert_not_called()
        validation = self.f.service.create_draft(name="validation", target="plate", purpose="validation")
        self.panel.refresh_tracks(select_track_id=validation)
        self.assertEqual(str(self.panel.btn_add_images["state"]), "normal")
        self.assertEqual(self.ingest([self.f.image("IMG_006.png")]), 1)

    def test_background_job_keeps_tk_timers_responsive_and_propagates_error(self):
        progress = BatchProgressDialog(self.root)
        beats = []
        timer = None
        def heartbeat():
            nonlocal timer
            beats.append(threading.get_ident())
            timer = self.root.after(10, heartbeat)
        heartbeat()
        try:
            main_thread = threading.get_ident()
            result = progress.run(lambda update: (threading.Event().wait(.2), threading.get_ident())[1])
            self.assertNotEqual(result, main_thread)
            self.assertGreater(len(beats), 4)
            self.assertEqual(set(beats), {main_thread})
            def fail(update):
                raise ValueError("worker failed")
            with self.assertRaisesRegex(ValueError, "worker failed"):
                progress.run(fail)
        finally:
            if timer:
                self.root.after_cancel(timer)
            progress.close()


    def test_resolution_write_failure_keeps_images_but_never_claims_current(self):
        import sqlite3
        with patch.object(self.panel.repository, "record_evaluation_track_audit",
                          side_effect=sqlite3.OperationalError("test write failure")):
            self.assertEqual(self.ingest([self.f.image("IMG_110.png")]), 1)
        self.errors.assert_called_once()
        self.assertEqual(self.success_text(), "")
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track)["status"], "STALE")
        self.assertEqual(self.f.repo.list_evaluation_track_audits(self.f.track), [])

    def test_missing_member_file_is_visible_as_unknown_and_can_be_removed(self):
        clean = self.f.image("IMG_110.png")
        self.f.service.add_member(self.f.track, clean)
        track = self.f.service.get_track(self.f.track)
        member = self.f.service.list_members(self.f.track)[0]
        (self.f.workspace / track["relative_path"] / member["track_relative_path"]).unlink()
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.panel.audit_current_pool()
        self.assertEqual(len(self.audit_reports[-1].candidates), 1)
        self.assertEqual(self.audit_reports[-1].unknown_count, 1)
        self.assertEqual(self.f.service.list_members(self.f.track), [])
        self.assertTrue(clean.exists())
        self.errors.assert_not_called()

    def test_partial_preflight_passes_exactly_eleven_paths_to_batch(self):
        import hashlib
        from auto_annotation_tool.registry.participant_pool_audit import (
            AUDIT_SCHEMA, ParticipantPoolAuditReport, CandidateVerdict, participant_fingerprint,
            STATUS_CLEAN, STATUS_DEPENDENT, STATUS_UNKNOWN, STATUS_SUSPECT,
        )
        paths = [self.f.image(f"IMG_{i+500:03d}.png", seed=500+i) for i in range(17)]
        statuses = [STATUS_CLEAN]*10 + [STATUS_DEPENDENT]*3 + [STATUS_UNKNOWN]*2 + [STATUS_SUSPECT]*2
        participants = self.panel.participant_audit.load_participants(self.f.track)
        report = ParticipantPoolAuditReport(
            AUDIT_SCHEMA, self.f.track, participant_fingerprint(participants), participants,
            tuple(CandidateVerdict(str(path), path.name, hashlib.sha256(path.read_bytes()).hexdigest(),
                                   "", status, ()) for path, status in zip(paths, statuses)),
            3, 2, 10, 2, "2026-09-14T12:00:00+00:00",
        )
        self.audit_choices[paths[-2].name] = "accept"
        with patch.object(self.panel.participant_audit, "audit_paths", return_value=report):
            with patch.object(self.panel.service, "add_members_batch",
                              wraps=self.panel.service.add_members_batch) as batch:
                self.assertEqual(self.ingest(paths), 11)
        self.assertEqual(len(batch.call_args.args[1]), 11)
        self.assertIn(paths[-2], batch.call_args.args[1])
        self.assertNotIn(paths[-1], batch.call_args.args[1])
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)

    def test_correction_archives_existing_ground_truth_with_members(self):
        paths = self.f.mixed()[:4]
        self.f.service.add_members_batch(self.f.track, paths)
        gt = Path(self.temp.name) / "gt.xml"
        gt.write_text("<annotations/>", encoding="utf-8")
        self.f.service.set_ground_truth(self.f.track, gt)
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.panel.audit_current_pool()
        updated = self.f.service.get_track(self.f.track)
        self.assertFalse(updated["gt_relative_path"])
        archived = list((self.f.workspace / updated["relative_path"] / "ground_truth" /
                         "_invalidated_member_change").rglob("*.xml"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), gt.read_bytes())
        self.errors.assert_not_called()

    def test_reaudit_recovers_manifest_after_late_ingest_failure(self):
        clean = self.f.image("IMG_115.png")
        with patch.object(self.panel.service, "_write_manifest", side_effect=OSError("test failure")):
            self.assertEqual(self.ingest([clean]), 1)
        track = self.f.service.get_track(self.f.track)
        manifest = self.f.workspace / track["relative_path"] / "track_manifest.json"
        self.assertEqual(len(json.loads(manifest.read_text(encoding="utf-8"))["members"]), 0)
        self.errors.reset_mock()
        self.panel.audit_current_pool()
        self.errors.assert_not_called()
        self.assertEqual(len(json.loads(manifest.read_text(encoding="utf-8"))["members"]), 1)
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)

    def test_gt_verify_and_seal_block_stale_then_accept_current_audit(self):
        clean = self.f.image("IMG_006.png")
        self.ingest([clean])
        context = self.f.service.activate_z2_context(self.f.track)
        self.assertTrue((Path(context["source_dir"]) / clean.name).exists())
        gt = Path(self.temp.name) / "gt.xml"
        gt.write_text('<annotations><image id="0" name="IMG_006.png" width="192" height="128">'
                      '<polygon label="plate" points="10,10;70,10;70,40;10,40"/>'
                      '</image></annotations>', encoding="utf-8")
        self.panel.service.set_ground_truth(self.f.track, gt)
        self.panel.verify_track()
        self.errors.assert_not_called()
        self.assertEqual(self.f.service.get_track(self.f.track)["status"], "VERIFIED")
        self.panel.participant_audit.invalidate_track_audit(self.f.track, reason="test")
        self.panel.seal_track()
        self.assertEqual(self.f.service.get_track(self.f.track)["status"], "VERIFIED")
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.assertEqual(str(self.panel.btn_audit_pool["state"]), "normal")
        self.panel.audit_current_pool()
        self.panel.seal_track()
        self.errors.assert_not_called()
        self.assertEqual(self.f.service.get_track(self.f.track)["status"], "SEALED")


if __name__ == "__main__":
    unittest.main()

