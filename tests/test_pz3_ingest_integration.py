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
        from auto_annotation_tool.gui.pz3_audit_resolution_dialog import ParticipantAuditMatrixDialog
        self._real_audit_show = ParticipantAuditMatrixDialog.show
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

    def test_import_after_name_correction_restores_hidden_app_and_finishes(self):
        from auto_annotation_tool.gui.source_filename_review_dialog import _SourceFilenameReviewDialog
        bad=self.f.image("bad-name.png",seed=10001)
        other=self.f.image("READY_002.png",seed=10002)
        self.root.geometry("1100x780+20+20")
        self.root.deiconify()
        self.root.update()
        failures=[]
        real_show=_SourceFilenameReviewDialog.show_selection

        def show(dialog):
            def correct_and_save():
                try:
                    dialog.tree.selection_set(str(bad))
                    dialog.rename_button.invoke()
                    dialog._edit_entry.delete(0,"end")
                    dialog._edit_entry.insert(0,"READY_001.png")
                    dialog._commit_inline_edit()
                    self.root.withdraw()
                    self.root.update_idletasks()
                    dialog.apply_button.invoke()
                except BaseException as exc:
                    failures.append(exc)
                    dialog._cancel()
            dialog.window.after(25,correct_and_save)
            return real_show(dialog)

        with patch.object(_SourceFilenameReviewDialog,"show_selection",new=show):
            self.assertEqual(self.ingest([bad,other]),2)
        self.assertFalse(failures,failures)
        self.assertTrue(self.root.winfo_viewable())
        self.assertIn(self.root.state(),{"normal","zoomed"})
        self.assertIsNone(self.root.grab_current())
        self.assertEqual({row["original_name"] for row in self.f.service.list_members(self.f.track)},
                         {"READY_001.png","READY_002.png"})
        self.errors.assert_not_called()

    def success_text(self):
        messages = [c.args[1] for c in self.messages.showinfo.call_args_list
                    if c.args[0] == "Dodawanie obrazów zakończone"]
        return messages[-1] if messages else ""

    def test_mixed_folder_adds_candidates_then_explicit_audit_filters_pool(self):
        self.panel._layout.notebook.select(self.panel._layout.details_page)
        with patch.object(self.panel, "_run_participant_pool_audit",
                          wraps=self.panel._run_participant_pool_audit) as audit:
            self.assertEqual(self.ingest(self.f.mixed(), folder=True), 4)
            audit.assert_not_called()
        self.errors.assert_not_called()
        self.messages.showerror.assert_not_called()
        self.assertIn("Dodano do toru: 4", self.success_text())
        self.assertIn("Duplikaty w wyborze: 1", self.success_text())
        self.assertIn("Następny krok", self.success_text())
        self.assertEqual(self.panel._layout.notebook.select(), str(self.panel._layout.images_page))
        self.assertFalse(self.f.service.get_preparation_state(self.f.track).can_prepare_gt)
        self.panel.audit_current_pool()
        self.assertEqual(len(self.panel.member_tree.get_children()), 1)
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)
        self.errors.assert_not_called()


    def test_explicit_audit_accepts_suspect_with_recorded_acknowledgement(self):
        self.audit_default_choice = "accept"
        self.assertEqual(self.ingest(self.f.mixed()), 4)
        self.panel.audit_current_pool()
        self.assertEqual(len(self.f.service.list_members(self.f.track)), 2)
        state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.assertEqual(len(state["accepted_suspect_sha256"]), 1)


    def test_new_ingest_invalidates_previous_audit_without_starting_another(self):
        clean, _, suspect, *_ = self.f.mixed()
        self.audit_default_choice = "accept"
        self.ingest([suspect])
        self.panel.audit_current_pool()
        before = len(self.audit_reports)
        self.messages.reset_mock()
        self.assertEqual(self.ingest([clean]), 2)
        self.assertEqual(len(self.audit_reports), before)
        self.assertEqual(self.f.audit.get_track_audit_state(self.f.track)["status"], "STALE")
        self.assertEqual(self.panel._layout.audit_var.get(), "Audyt: wymaga ponowienia")
        self.assertFalse(self.f.service.get_preparation_state(self.f.track).can_prepare_gt)
        self.messages.askyesno.assert_not_called()
        self.messages.askyesnocancel.assert_not_called()
        self.messages.askokcancel.assert_not_called()


    def test_existing_invalid_pool_does_not_block_new_clean_images(self):
        clean, dependent, *_ = self.f.mixed()
        self.f.service.add_members_batch(self.f.track, [dependent])
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.assertEqual(self.ingest([clean]), 2)
        state = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.assertEqual(state["status"], "STALE")
        self.assertEqual("Audyt: do wykonania", self.panel._layout.audit_var.get())
        self.errors.assert_not_called()

    def test_current_audit_cta_is_disabled_after_current_result(self):
        self.ingest([self.f.image("RECHECK_001.png", seed=1900)])
        self.panel.audit_current_pool()
        self.assertEqual(
            self.f.audit.get_track_audit_state(self.f.track)["status"],
            "CURRENT",
        )
        self.panel.refresh_tracks(select_track_id=self.f.track)
        self.assertEqual(str(self.panel.btn_audit_pool["state"]), "disabled")

        before = len(self.f.repo.list_evaluation_track_audits(self.f.track))
        self.panel.btn_audit_pool.invoke()
        self.assertEqual(
            len(self.f.repo.list_evaluation_track_audits(self.f.track)),
            before,
        )
        self.assertEqual(
            self.f.audit.get_track_audit_state(self.f.track)["status"],
            "CURRENT",
        )
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
        self.assertIn("Audyt anulowany", self.panel.status_var.get())

    def test_cancel_explicit_audit_preserves_imported_candidates(self):
        self.assertEqual(self.ingest(self.f.mixed()), 4)
        before = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        self.audit_cancel = True
        self.panel.audit_current_pool()
        self.assertEqual(len(self.f.service.list_members(self.f.track)), 4)
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track), before)
        self.assertEqual(self.f.repo.list_evaluation_track_audits(self.f.track), [])


    def test_repeated_folder_is_duplicate_and_preserves_current_audit(self):
        clean = self.f.mixed()[0]
        self.assertEqual(self.ingest([clean], folder=True), 1)
        self.panel.audit_current_pool()
        before = self.f.repo.get_evaluation_track_audit_state(self.f.track)
        with patch.object(self.panel, "_run_participant_pool_audit") as run_audit:
            self.assertEqual(self.ingest([clean], folder=True), 1)
        run_audit.assert_not_called()
        self.assertEqual(self.f.repo.get_evaluation_track_audit_state(self.f.track), before)
        self.assertIn("Już w torze: 1", self.messages.showinfo.call_args.args[1])

    def test_imported_dependent_image_requires_audit_before_gt(self):
        clean, dependent, *_ = self.f.mixed()
        self.ingest([clean])
        self.panel.audit_current_pool()
        self.assertEqual(self.ingest([dependent]), 2)
        self.assertFalse(self.f.service.get_preparation_state(self.f.track).can_prepare_gt)
        self.panel.audit_current_pool()
        self.assertEqual(len(self.f.service.list_members(self.f.track)), 1)
        self.panel.participant_audit.assert_track_audit_ready(self.f.track)


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
        self.panel.audit_current_pool()
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
        self.assertEqual(self.ingest([self.f.image("IMG_110.png")]), 1)
        with patch.object(self.panel.repository, "record_evaluation_track_audit",
                          side_effect=sqlite3.OperationalError("test write failure")):
            self.panel.audit_current_pool()
        self.errors.assert_called_once()
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

    def test_import_defers_all_independence_decisions_until_explicit_audit(self):
        paths = [self.f.image(f"IMG_{i+500:03d}.png", seed=500+i) for i in range(17)]
        with patch.object(self.panel.participant_audit, "audit_paths",
                          side_effect=AssertionError("Audit must be explicit")) as audit:
            with patch.object(self.panel.service, "add_members_batch",
                              wraps=self.panel.service.add_members_batch) as batch:
                self.assertEqual(self.ingest(paths), 17)
        self.assertEqual(list(batch.call_args.args[1]), paths)
        audit.assert_not_called()
        self.assertEqual(self.f.repo.list_evaluation_track_audits(self.f.track), [])
        self.assertFalse(self.f.service.get_preparation_state(self.f.track).can_prepare_gt)
        self.assertEqual(str(self.panel.btn_prepare_z2["state"]), "disabled")
        self.assertEqual(str(self.panel.btn_verify["state"]), "disabled")
        self.assertEqual(str(self.panel.btn_seal["state"]), "disabled")


    def test_correction_archives_existing_ground_truth_with_members(self):
        paths = self.f.mixed()[:4]
        self.f.service.add_members_batch(self.f.track, paths)
        gt = Path(self.temp.name) / "gt.xml"
        gt.write_text("<annotations/>", encoding="utf-8")
        # Historical GT can predate both the sample selection and its audit.
        track = self.f.service.get_track(self.f.track)
        stored_gt = self.f.workspace / track["relative_path"] / "ground_truth" / "annotations.xml"
        stored_gt.parent.mkdir(parents=True, exist_ok=True)
        stored_gt.write_bytes(gt.read_bytes())
        self.f.repo.update_evaluation_track(
            self.f.track, gt_relative_path=self.f.service._workspace_relative(stored_gt),
            gt_format="cvat_xml", gt_sha256=self.f.service._sha256(stored_gt))
        self.f.service.ensure_audit_manifest(self.f.track)
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

    def test_stale_audit_after_gt_blocks_seal_without_reopening_audit_cta(self):
        clean = self.f.image("IMG_006.png")
        self.ingest([clean])
        self.panel.audit_current_pool()

        context = self.f.service.activate_z2_context(self.f.track)
        self.assertTrue((Path(context["source_dir"]) / clean.name).exists())

        gt = Path(self.temp.name) / "gt.xml"
        gt.write_text(
            '<annotations><image id="0" name="IMG_006.png" width="192" height="128">'
            '<polygon label="plate" points="10,10;70,10;70,40;10,40"/>'
            '</image></annotations>',
            encoding="utf-8",
        )

        self.f.select_and_reaudit()
        self.panel.service.set_ground_truth(self.f.track, gt)
        self.panel.verify_track()
        self.errors.assert_not_called()
        self.assertEqual(
            self.f.service.get_track(self.f.track)["status"],
            "VERIFIED",
        )

        # Stan wymuszony sztucznie po finalizacji. Nie wracamy do etapu
        # audytu próbki; SEAL pozostaje zablokowany fail-closed.
        self.panel.participant_audit.invalidate_track_audit(
            self.f.track,
            reason="test",
        )
        self.panel.refresh_tracks(select_track_id=self.f.track)

        self.assertEqual(str(self.panel.btn_audit_pool["state"]), "disabled")
        self.assertEqual(str(self.panel.btn_seal["state"]), "disabled")

        self.panel.seal_track()
        self.assertEqual(
            self.f.service.get_track(self.f.track)["status"],
            "VERIFIED",
        )
        self.messages.showwarning.assert_called()

    def test_guided_flow_reloads_sample_and_highlights_exactly_one_enabled_action(self):
        from auto_annotation_tool.registry.sample_selection import prepare_sample_selection

        def expect(step, primary):
            self.panel.refresh_tracks(select_track_id=self.f.track)
            self.root.update()
            self.assertEqual(self.panel._workflow_view.step, step)

            accented = [
                name
                for name in self.panel._layout.workflow_buttons
                if getattr(self.panel, name).cget("style")
                == "PZ3.Primary.TButton"
            ]
            self.assertEqual(accented, [primary])
            self.assertEqual(
                str(getattr(self.panel, primary).cget("state")),
                "normal",
            )
            self.assertNotEqual(
                self.panel._layout.new_button.cget("style"),
                "PZ3.Primary.TButton",
            )

        self.f.track = self.f.service.create_draft(
            name="Guided flow",
            target="plate",
            purpose="ranking",
        )
        expect("SELECT_MODELS", "btn_participants")

        self.f.audit.save_participants(self.f.track, ["M1", "M2"])
        expect("ADD_IMAGES", "btn_add_images")

        paths = [
            self.f.image("FLOW_001.png", seed=1221),
            self.f.image("FLOW_002.png", seed=1222),
        ]
        self.ingest(paths)
        expect("AUDIT_POOL", "btn_audit_pool")

        self.panel.btn_audit_pool.invoke()
        expect("SELECT_SAMPLE", "btn_sample_selection")

        # Backend commit reprezentuje finalizację podzbioru.
        context = prepare_sample_selection(self.f.service, self.f.track)
        keep = [context["sample_member_sha256"]["FLOW_001.png"]]
        self.f.service.commit_sample_selection(
            self.f.track,
            keep_sha256=keep,
            expected_member_sha256=context["sample_member_sha256"],
            expected_audit_id=context["sample_audit_id"],
        )

        self.assertEqual(
            self.f.audit.get_track_audit_state(self.f.track)["status"],
            "CURRENT",
        )
        expect("PREPARE_GT", "btn_prepare_z2")
        self.assertEqual(str(self.panel.btn_audit_pool["state"]), "disabled")

        gt = Path(self.temp.name) / "guided.xml"
        gt.write_text(
            '<annotations><image id="0" name="FLOW_001.png" width="192" height="128">'
            '<polygon label="plate" points="10,10;70,10;70,40;10,40"/>'
            '</image></annotations>',
            encoding="utf-8",
        )

        self.f.service.set_ground_truth(self.f.track, gt)
        expect("VERIFY", "btn_verify")

        self.panel.btn_verify.invoke()
        expect("SEAL", "btn_seal")

        self.panel.btn_seal.invoke()
        expect("COMPARE", "btn_compare")
        self.errors.assert_not_called()
