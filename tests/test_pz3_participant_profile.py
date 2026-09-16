from dataclasses import replace
import tkinter as tk
import unittest
from unittest.mock import patch

from auto_annotation_tool.gui.app_theme_definitions import get_theme_palette
from auto_annotation_tool.gui.pz3_participant_audit import ParticipantSelectionDialog
from auto_annotation_tool.gui.pz3_participant_profile import provenance_badge
from auto_annotation_tool.registry.participant_pool_audit import ParticipantModel
from auto_annotation_tool.registry.participant_background import ParticipantBackgroundReader


class ParticipantProfileGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.a = ParticipantModel("MODEL-A", "81f3a4c9" + "a"*52 + "e02b",
            "RUN-20260912-1432", "DS-PLATE-202609-VERY-LONG-FULL-IDENTIFIER", "plate", "YOLO26", "n", "complete",
            training_finished_at="2026-09-12T18:47:00+02:00", pose_map50_95=0.901,
            pose_map50=0.965, box_map50_95=0.934, box_map50=0.982, checkpoint_kind="trained_export")
        self.b = replace(self.a, model_id="MODEL-B", sha256="b"*64, run_id="RUN-2",
                         dataset_id="DS-2", scale="s", provenance_status="known", pose_map50_95=None)
        self.dialog = ParticipantSelectionDialog(self.root, models=[self.a, self.b],
            selected_ids={"MODEL-A"}, track_name="Profile", palette=get_theme_palette("light_visual_cs"))
        self.addCleanup(self.dialog._cancel)
        self.dialog.window.update()

    def select(self, *ids):
        self.dialog.tree.selection_set(ids)
        self.dialog.window.update()
        return self.dialog.profile

    def test_participant_dialog_compact_columns(self):
        self.assertEqual(tuple(self.dialog.tree["columns"]), ("sel","model","arch","origin","quality","prov"))
        self.assertIn("Dataset", self.dialog._sort_fields)
        self.assertIn("Data zakończenia", self.dialog._sort_fields)

    def test_participant_dialog_shows_dataset_and_run_origin(self):
        origin = self.dialog.tree.set("MODEL-A", "origin")
        self.assertIn(self.a.run_id, origin)
        self.assertIn("DS-PLATE", origin)
        self.assertIn("…", origin)
        self.assertEqual(self.dialog.tree.set("MODEL-A", "arch"), "YOLO26 · n")
        self.assertEqual(self.dialog.tree.set("MODEL-A", "quality"), "Pose 0.901")

    def test_details_panel_updates_without_changing_participation_or_reading_artifacts(self):
        with patch.object(ParticipantBackgroundReader, "read", side_effect=AssertionError("No IO on selection")):
            profile = self.select("MODEL-B")
            self.assertIn("MODEL-B", profile.title.get())
            self.assertEqual(self.dialog.selected, {"MODEL-A"})
            self.select("MODEL-A", "MODEL-B")
            self.assertEqual(profile.title.get(), "Wybrano 2 modele.")
            self.assertEqual(profile.values["dataset"].get(), "—")
            self.select()
            self.assertIn("Wybierz model", profile.title.get())

    def test_details_formats_date_map_and_keeps_full_dataset_and_short_sha(self):
        profile = self.select("MODEL-A")
        self.assertEqual(profile.values["finished"].get(), "12.09.2026 · 18:47")
        self.assertEqual(profile.values["pose_map50_95"].get(), "0.901")
        self.assertEqual(profile.values["pose_map50"].get(), "0.965")
        self.assertEqual(profile.values["dataset"].get(), self.a.dataset_id)
        self.assertEqual(profile.values["run"].get(), self.a.run_id)
        self.assertEqual(profile.values["sha"].get(), "81f3a4c9…e02b")
        with patch.object(profile.root, "clipboard_clear") as clear, patch.object(profile.root, "clipboard_append") as append:
            profile.copy_sha()
            clear.assert_called_once()
            append.assert_called_once_with(self.a.sha256)

    def test_provenance_badge_uses_semantic_tone_and_map_stays_neutral(self):
        profile = self.select("MODEL-A")
        self.assertEqual(profile.tones["provenance"], "success")
        self.assertEqual(str(profile.widgets["provenance"].cget("foreground")), profile.palette["success"])
        self.assertEqual(profile.tones["pose_map50_95"], "fg")
        self.select("MODEL-B")
        self.assertEqual(profile.tones["provenance"], "info")
        self.assertEqual(provenance_badge(replace(self.a, provenance_status="partial"))[1], "warning")

    def test_missing_metric_is_muted_not_error(self):
        profile = self.select("MODEL-B")
        self.assertEqual(profile.values["pose_map50_95"].get(), "—")
        self.assertEqual(profile.tones["pose_map50_95"], "muted")
        self.assertTrue(self.b.eligible)

    def test_inconsistent_model_can_be_inspected_but_never_enabled(self):
        bad = replace(self.b, dataset_id="")
        self.dialog._replace_models([self.a, bad])
        profile = self.select("MODEL-B")
        self.assertEqual(profile.tones["provenance"], "error")
        self.assertIn("Niespójna", profile.values["provenance"].get())
        self.assertEqual(self.dialog.tree.set("MODEL-B","sel"), "—")
        self.dialog._toggle()
        self.assertNotIn("MODEL-B", self.dialog.selected)
        self.assertIn("Nie można", profile.notice.get())

    def test_duplicate_complete_run_warns_without_changing_membership(self):
        other = replace(self.b, run_id=self.a.run_id, provenance_status="complete")
        self.dialog._replace_models([self.a, other])
        profile = self.select("MODEL-A")
        self.assertIn("Sprawdź pochodzenie", profile.notice.get())
        self.assertEqual(str(profile.notice_label.cget("foreground")), profile.palette["warning"])
        self.assertEqual(self.dialog.selected, {"MODEL-A"})

    def test_quality_sort_keeps_missing_at_end_in_both_directions(self):
        third = replace(self.a, model_id="MODEL-C", sha256="c"*64, pose_map50_95=0.5)
        self.dialog._replace_models([self.a, self.b, third])
        self.dialog._sort_models("quality")
        self.assertEqual(self.dialog.tree.get_children(), ("MODEL-C","MODEL-A","MODEL-B"))
        self.dialog._sort_models("quality")
        self.assertEqual(self.dialog.tree.get_children(), ("MODEL-A","MODEL-C","MODEL-B"))

    def test_row_click_updates_profile_and_checkbox_changes_only_participation(self):
        x,y,width,height = self.dialog.tree.bbox("MODEL-B","model")
        self.dialog.tree.event_generate("<Button-1>",x=x+10,y=y+height//2)
        self.dialog.window.update()
        self.assertIn("MODEL-B",self.dialog.profile.title.get())
        self.assertEqual(self.dialog.selected,{"MODEL-A"})
        x,y,width,height = self.dialog.tree.bbox("MODEL-B","sel")
        self.dialog.tree.event_generate("<Button-1>",x=x+width//2,y=y+height//2)
        self.dialog.window.update()
        self.assertEqual(self.dialog.selected,{"MODEL-A","MODEL-B"})


if __name__ == "__main__":
    unittest.main()
