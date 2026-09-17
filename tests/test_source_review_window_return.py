"""Real Tk return from source review, including the subsequent progress modal."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from PIL import Image
from auto_annotation_tool.gui.source_filename_review_dialog import _SourceFilenameReviewDialog
from auto_annotation_tool.gui.pz3_participant_audit import BatchProgressDialog
from auto_annotation_tool.gui.app_window_recovery import restore_parent_after_modal
from auto_annotation_tool.gui import app_window_recovery as recovery


class SourceReviewWindowReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _clear_window_state(self):
        for event in ("<Map>","<Unmap>","<FocusIn>"):
            self.root.unbind(event)
        for job in self.root.tk.splitlist(self.root.tk.call("after","info")):
            self.root.after_cancel(job)
        grabbed=self.root.grab_current()
        if grabbed is not None:
            grabbed.grab_release()
        for child in self.root.winfo_children():
            child.destroy()
        self.root.withdraw()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.bad=self.folder/"bad.png"
        Image.new("RGB",(180,120),"gray").save(self.bad)
        self.root.deiconify()
        self.root.geometry("1000x720")
        self.addCleanup(self._clear_window_state)
        self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.root.update()

    def dialog(self,parent=None):
        dialog=_SourceFilenameReviewDialog(parent or self.root,self.folder,recursive=False,title="Review",audit_next_step=True)
        self.addCleanup(lambda:dialog._cancel() if dialog.window.winfo_exists() else None)
        return dialog

    def apply_name(self,dialog):
        dialog.rename_stems[str(self.bad)]="GOOD_001"
        dialog._reload()
        dialog._apply()
        self.root.update()
        self.assertTrue(dialog.result)
        self.assertTrue((self.folder/"GOOD_001.png").is_file())
        self.assertFalse(self.errors,self.errors)

    def test_save_restores_minimized_main_window(self):
        dialog=self.dialog()
        self.root.iconify()
        self.root.update()
        self.assertEqual(self.root.state(),"iconic")
        self.apply_name(dialog)
        self.assertEqual(self.root.state(),"normal")
        self.assertTrue(self.root.winfo_viewable())
        self.assertIsNone(self.root.grab_current())

    def test_save_restores_withdrawn_main_window_before_progress(self):
        # Install the same event handlers as the actual app.
        app=SimpleNamespace(root=self.root,_iter_loaded_tabs=lambda:[])
        self.root.bind("<Map>",lambda event:recovery.on_root_map(app,event),add="+")
        self.root.bind("<Unmap>",lambda event:recovery.on_root_unmap(app,event),add="+")
        self.root.bind("<FocusIn>",lambda event:recovery.on_root_focus_in(app,event),add="+")
        dialog=self.dialog()
        self.root.withdraw()
        self.root.update()
        self.apply_name(dialog)
        self.assertEqual(self.root.state(),"normal")
        progress=BatchProgressDialog(self.root,title="Import")
        self.root.update()
        self.assertTrue(progress.window.winfo_viewable())
        result=progress.run(lambda update:(time.sleep(.12),update("Ready",1,1),True)[-1])
        progress.close()
        self.root.update()
        self.assertTrue(result)
        self.assertTrue(self.root.winfo_viewable())
        self.assertIsNone(self.root.grab_current())
        clicks=[]
        button=ttk.Button(self.root,text="Continue",command=lambda:clicks.append(True))
        button.pack()
        self.root.update()
        button.event_generate("<ButtonPress-1>",x=5,y=5)
        button.event_generate("<ButtonRelease-1>",x=5,y=5)
        self.root.update()
        self.assertEqual(clicks,[True])

    def test_hidden_previous_dialog_does_not_recapture_input(self):
        previous=tk.Toplevel(self.root)
        previous.update()
        previous.grab_set()
        dialog=self.dialog()
        self.assertIs(dialog._previous_grab,previous)
        previous.withdraw()
        dialog._cancel()
        self.root.update()
        self.assertEqual(previous.state(),"withdrawn")
        self.assertIsNone(self.root.grab_current())
        self.assertTrue(self.root.winfo_viewable())

    def test_visible_nested_parent_keeps_its_grab(self):
        previous=tk.Toplevel(self.root)
        frame=ttk.Frame(previous)
        frame.pack()
        previous.update()
        previous.grab_set()
        dialog=self.dialog(frame)
        dialog._cancel()
        self.root.update()
        self.assertIs(self.root.grab_current(),previous)
        previous.grab_release()

    def test_new_visible_dialog_is_not_displaced_on_return(self):
        dialog=self.dialog()
        other=tk.Toplevel(self.root)
        other.update()
        other.grab_set()
        dialog._cancel()
        self.root.update()
        self.assertIs(self.root.grab_current(),other)
        other.grab_release()

    def test_progress_close_does_not_restore_hidden_grab(self):
        previous=tk.Toplevel(self.root)
        previous.update()
        previous.grab_set()
        progress=BatchProgressDialog(self.root)
        previous.withdraw()
        progress.close()
        self.root.update()
        self.assertIsNone(self.root.grab_current())

    def test_minimized_independent_tool_stays_minimized_but_main_app_returns(self):
        owner=tk.Toplevel(self.root)
        owner._aat_skip_window_recovery=True
        owner.update()
        owner.iconify()
        self.root.withdraw()
        self.root.update()
        self.assertTrue(restore_parent_after_modal(owner,owner))
        self.root.update()
        self.assertEqual(owner.state(),"iconic")
        self.assertEqual(self.root.state(),"normal")
        self.assertIsNone(self.root.grab_current())


if __name__=="__main__":
    unittest.main()
