import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image

from auto_annotation_tool.gui.source_filename_review_dialog import _SourceFilenameReviewDialog
from auto_annotation_tool.gui.pz3_participant_audit import ParticipantSelectionDialog
from auto_annotation_tool.registry.participant_pool_audit import ParticipantModel


class PZ3DialogInteractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "images"
        self.directory.mkdir()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.errors = self.enterContext(patch(
            "auto_annotation_tool.gui.source_filename_review_dialog.messagebox"))
        self.paths = [self.directory / name for name in ("bad10.png", "bad2.png")]
        for index, path in enumerate(self.paths):
            Image.new("RGB", (96, 64), ("red", "blue")[index]).save(path)

    def dialog(self):
        dialog = _SourceFilenameReviewDialog(self.root, self.directory,
                                              recursive=False, title="PZ3 test")
        dialog.window.update()
        return dialog

    def select(self, dialog, path):
        dialog.tree.selection_set(str(path))
        dialog.tree.focus(str(path))
        dialog.tree.focus_force()
        dialog.window.update()

    def edit(self, dialog, value):
        dialog.tree.event_generate("<Return>")
        dialog.window.update()
        self.assertIsNotNone(dialog._edit_entry)
        dialog._edit_entry.delete(0, tk.END)
        dialog._edit_entry.insert(0, value)
        dialog._edit_entry.focus_force()

    def test_keyboard_navigation_sort_inline_commit_and_cancel(self):
        dialog = self.dialog()
        self.assertEqual(Path(dialog.tree.get_children()[0]).name, "bad2.png")
        self.select(dialog, self.paths[1])
        dialog.tree.event_generate("<Down>")
        dialog.window.update()
        self.assertEqual(dialog._selected_path(), self.paths[0])
        self.assertEqual(dialog.preview_caption_var.get(), "bad10.png")
        dialog.tree.event_generate("<Up>")
        dialog.window.update()
        self.assertEqual(dialog._selected_path(), self.paths[1])
        self.edit(dialog, "IMG_004.png")
        dialog._edit_entry.event_generate("<Return>")
        dialog.window.update()
        self.assertEqual(dialog.rename_stems[str(self.paths[1])], "IMG_004")
        self.assertEqual(dialog.tree.item(str(self.paths[1]), "text"), "IMG_004.png")
        self.assertTrue(self.paths[1].exists())  # deferred until Save
        self.edit(dialog, "IMG_099.png")
        dialog._edit_entry.event_generate("<Escape>")
        dialog.window.update()
        self.assertEqual(dialog.rename_stems[str(self.paths[1])], "IMG_004")
        dialog._sort_by_column("#0")
        self.assertIn("▼", dialog.tree.heading("#0", "text"))
        dialog._reject_all()
        self.assertNotIn(str(self.paths[1]), dialog.rejected_paths)
        dialog._apply()
        self.assertTrue((self.directory / "IMG_004.png").exists())
        self.assertEqual(dialog.selection_result.renamed, 1)
        self.assertEqual(dialog.selection_result.rejected, 1)

    def test_clicking_save_commits_active_editor(self):
        self.paths[0].unlink()
        dialog = self.dialog()
        self.select(dialog, self.paths[1])
        self.edit(dialog, "IMG_004.png")
        dialog._commit_inline_edit()
        self.edit(dialog, "IMG_005.png")
        dialog._apply()
        self.assertTrue((self.directory / "IMG_005.png").exists())
        self.assertFalse((self.directory / "IMG_004.png").exists())
        self.assertTrue(dialog.result)

    def test_invalid_name_and_collision_leave_editor_open(self):
        dialog = self.dialog()
        self.select(dialog, self.paths[1])
        self.edit(dialog, "stillbad.png")
        dialog._commit_inline_edit()
        self.assertIsNotNone(dialog._edit_entry)
        existing = self.directory / "IMG_004.png"
        Image.new("RGB", (96, 64), "green").save(existing)
        dialog._edit_entry.delete(0, tk.END)
        dialog._edit_entry.insert(0, existing.name)
        dialog._commit_inline_edit()
        self.assertIsNotNone(dialog._edit_entry)
        self.errors.showerror.assert_called()
        self.assertEqual(dialog.rename_stems, {})
        dialog._cancel()

    def test_name_review_is_visible_and_distinguishes_filename_count_from_audit(self):
        self.root.geometry("1100x780+20+20")
        self.root.deiconify()
        self.root.update()
        self.root.grab_set()
        dialog = _SourceFilenameReviewDialog(
            self.root,self.directory,recursive=False,title="PZ3 names",audit_next_step=True)
        self.addCleanup(lambda: dialog._cancel() if dialog.window.winfo_exists() else None)
        dialog.window.update()
        self.assertEqual(dialog.window.state(),"normal")
        self.assertTrue(dialog.window.winfo_viewable())
        self.assertEqual(self.root.grab_current(),dialog.window)
        self.assertIn("nazwy do poprawy: 2",dialog.summary_var.get())
        self.assertIn("Sprawdź niezależność puli",dialog.summary_var.get())
        self.assertEqual(dialog.tree.heading("problem","text"),"Problem z nazwą")
        dialog.window.grab_release()
        dialog.window.iconify()
        self.root.update()
        self.assertEqual(dialog.window.state(),"iconic")
        dialog._present()
        self.root.update()
        self.assertEqual(dialog.window.state(),"normal")
        self.assertTrue(dialog.window.winfo_viewable())
        self.assertEqual(self.root.grab_current(),dialog.window)
        dialog._cancel()
        self.assertEqual(self.root.grab_current(),self.root)
        self.root.grab_release()

    def test_successful_name_review_restores_parent_grab(self):
        self.root.deiconify()
        self.root.update()
        self.root.grab_set()
        dialog=self.dialog()
        for i,path in enumerate(self.paths):
            dialog.rename_stems[str(path)]=f"GOOD_{i+1:03d}"
        dialog._apply()
        self.assertTrue(dialog.result)
        self.assertEqual(self.root.grab_current(),self.root)
        self.root.grab_release()

    def test_source_chooser_restores_parent_before_filename_review(self):
        from auto_annotation_tool.gui.pz3_source_ingest_ui import _PZ3SourceChooser
        self.root.deiconify()
        self.root.update()
        self.root.grab_set()
        chooser=_PZ3SourceChooser(self.root)
        self.assertTrue(chooser.window.winfo_viewable())
        self.assertEqual(chooser.window.state(),"normal")
        self.assertEqual(self.root.grab_current(),chooser.window)
        chooser._cancel()
        self.assertEqual(self.root.grab_current(),self.root)
        self.root.grab_release()

    def test_model_checkbox_selection_and_sort_preserve_membership(self):
        models = [
            ParticipantModel("M2", "b" * 64, "R2", "DS-PLATE-002", "plate", "YOLO26", "s", "known"),
            ParticipantModel("M1", "a" * 64, "R1", "DS-PLATE-001", "plate", "YOLO26", "n", "complete"),
        ]
        refresh = Mock(return_value=(models, "Lista odświeżona"))
        dialog = ParticipantSelectionDialog(
            self.root, models=models, selected_ids={"M1"}, track_name="test", on_refresh=refresh)
        dialog.window.update()
        x, y, width, height = dialog.tree.bbox("M2", "#1")
        dialog.tree.event_generate("<Button-1>", x=x+width//2, y=y+height//2)
        dialog.window.update()
        self.assertEqual(dialog.selected, {"M1", "M2"})
        self.assertIn("M2", dialog.profile.title.get())
        self.assertEqual(dialog.tree.item("M2", "values")[0], "☑")
        dialog._sort_models("scale")
        self.assertEqual(dialog.tree.get_children(), ("M1", "M2"))
        dialog._sort_models("scale")
        self.assertEqual(dialog.tree.get_children(), ("M2", "M1"))
        self.assertEqual(dialog.selected, {"M1", "M2"})
        dialog._refresh_registry()
        refresh.assert_called_once()
        dialog._cancel()

    def test_participant_dialog_shows_compact_origin_and_registry_values(self):
        from pz3_test_support import PZ3Fixture
        fixture = PZ3Fixture(Path(self.temp.name) / "dataset_dialog")
        with fixture.repo.database.transaction() as db:
            db.execute("UPDATE datasets SET dataset_id='DS-PLATE-001' WHERE dataset_id='D1'")
            db.execute("UPDATE datasets SET dataset_id='DS-PLATE-002' WHERE dataset_id='D2'")
            db.execute("UPDATE models SET provenance_status='known' WHERE model_id='M2'")
        models = [p for p in fixture.audit.list_participant_catalog("plate") if p.model_id in {"M1", "M2"}]
        dialog = ParticipantSelectionDialog(self.root, models=models, selected_ids={"M1", "M2"}, track_name="Dataset")
        self.addCleanup(dialog._cancel)
        dialog.window.update()
        self.assertEqual(tuple(dialog.tree["columns"]), ("sel", "model", "arch", "origin", "quality", "prov"))
        self.assertIn("DS-PLATE-001", dialog.tree.set("M1", "origin"))
        self.assertIn("DS-PLATE-002", dialog.tree.set("M2", "origin"))
        self.assertEqual(dialog.tree.set("M1", "prov"), "● Pełna")
        self.assertEqual(dialog.tree.set("M2", "prov"), "● Potwierdzona ręcznie")
        dialog._sort_models("dataset")
        self.assertEqual(dialog.tree.get_children(), ("M1", "M2"))
        dialog._sort_models("dataset")
        self.assertEqual(dialog.tree.get_children(), ("M2", "M1"))
        self.assertEqual(dialog.selected, {"M1", "M2"})
        dialog.tree.selection_set("M1")
        dialog.window.update()
        self.assertEqual(dialog.profile.values["dataset"].get(), "DS-PLATE-001")


if __name__ == "__main__":
    unittest.main()

