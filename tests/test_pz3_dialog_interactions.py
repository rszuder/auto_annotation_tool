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

    def test_model_checkbox_selection_and_sort_preserve_membership(self):
        models = [
            ParticipantModel("M2", "b" * 64, "R2", "plate", "YOLO26", "s", "known"),
            ParticipantModel("M1", "a" * 64, "R1", "plate", "YOLO26", "n", "complete"),
        ]
        refresh = Mock(return_value=(models, "Lista odświeżona"))
        dialog = ParticipantSelectionDialog(
            self.root, models=models, selected_ids={"M1"}, track_name="test", on_refresh=refresh)
        dialog.window.update()
        x, y, width, height = dialog.tree.bbox("M2", "#1")
        dialog.tree.event_generate("<Button-1>", x=x+width//2, y=y+height//2)
        dialog.window.update()
        self.assertEqual(dialog.selected, {"M1", "M2"})
        self.assertIn("M2", dialog.registry_status.get())
        self.assertEqual(dialog.tree.item("M2", "values")[0], "☑")
        dialog._sort_models("scale")
        self.assertEqual(dialog.tree.get_children(), ("M1", "M2"))
        dialog._sort_models("scale")
        self.assertEqual(dialog.tree.get_children(), ("M2", "M1"))
        self.assertEqual(dialog.selected, {"M1", "M2"})
        dialog._refresh_registry()
        refresh.assert_called_once()
        dialog._cancel()


if __name__ == "__main__":
    unittest.main()

