"""Regression checks against the real Z2 model/scope dialog; no inference."""
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.config import CONFIG, SESSION
from auto_annotation_tool.campaign_manager import CAMPAIGN
from auto_annotation_tool.gui.app import AutoAnnotationApp
from auto_annotation_tool.gui.app_style_setup import setup_style
from auto_annotation_tool.gui.app_theme_definitions import THEME_DEFINITIONS, get_theme_palette
from auto_annotation_tool.gui.tab_annotation import AnnotationTab
from auto_annotation_tool.gui.pz3_gt_route import enter_experiment_gt_workspace
from auto_annotation_tool.registry.experiment_gt_workspace import prepare_gt_workspace


MODAL = "auto_annotation_tool.gui.z2_auto_scope_modal."


class GtModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = PZ3Fixture(self.temp.name)
        original_workspace = Path(CONFIG.WORKSPACE_DIR).resolve()
        for attr in dir(CONFIG):
            if attr.startswith("_"):
                continue
            value = getattr(CONFIG, attr)
            if isinstance(value, Path):
                try:
                    relative = value.resolve().relative_to(original_workspace)
                except ValueError:
                    continue
                self.enterContext(patch.object(CONFIG, attr, self.fixture.workspace / relative))
        self.enterContext(patch.object(CONFIG, "WORKSPACE_DIR", self.fixture.workspace))
        self.enterContext(patch.object(SESSION, "get", side_effect=lambda *args, **kw: args[2] if len(args)>2 else kw.get("default")))
        self.enterContext(patch.object(SESSION, "set"))
        for method in ("save", "_save", "save_session", "flush"):
            if hasattr(SESSION, method):
                self.enterContext(patch.object(SESSION, method))
        self.enterContext(patch.object(AnnotationTab, "_queue_free_mode_session_save"))
        self.enterContext(patch.object(AnnotationTab, "_restore_preview_from_session_run", return_value=False))
        self.project_name = ""
        self.project_model = ""
        self.enterContext(patch.object(CAMPAIGN, "get_active_project_name", side_effect=lambda: self.project_name))
        self.enterContext(patch.object(CAMPAIGN, "get_global_model", side_effect=lambda target: self.project_model if target=="plate" else ""))
        self.adopt = self.enterContext(patch.object(CAMPAIGN, "set_global_model"))
        self.addCleanup(self._close_root)
        self.root.geometry("1100x800+20+20")
        self.callback_errors = []
        self.root.report_callback_exception = lambda *args: self.callback_errors.append(args)
        app = AutoAnnotationApp.__new__(AutoAnnotationApp)
        app.root = self.root
        app.themes = THEME_DEFINITIONS
        app.style = ttk.Style(self.root)
        app.palette = get_theme_palette("light_visual_cs")
        app.current_theme_key = "light_visual_cs"
        app.tabs = {}
        app.campaign_free_mode = True
        for method in ("update_status", "append_global_terminal", "set_processing", "end_exclusive_operation"):
            setattr(app, method, Mock())
        app.begin_exclusive_operation = Mock(return_value=True)
        app.try_begin_exclusive_operation = Mock(return_value=(True, ""))
        setup_style(app, "light_visual_cs")
        app.notebook = ttk.Notebook(self.root)
        app.notebook.pack(fill="both", expand=True)
        self.host = AnnotationTab(app.notebook, app)
        app.tabs["annotation"] = self.host
        app.notebook.add(self.host.frame, text="Z2")
        self.images = [self.fixture.image("UI_TEST.png", seed=1400)]
        report = self.fixture.audit.audit_paths(self.fixture.track, self.images)
        self.fixture.service.add_members_batch(self.fixture.track, self.images)
        self.fixture.audit.record_ingested_report(self.fixture.track, report, self.images)
        self.fixture.select_and_reaudit()
        context = prepare_gt_workspace(self.fixture.service, self.fixture.track)
        self.assertTrue(enter_experiment_gt_workspace(self.host, context))
        self.host.plate_custom_var.set("")
        self.host._clear_plate_model_runtime_meta()
        self.replacement = self.fixture.workspace / "replacement.pt"
        self.replacement.write_bytes(b"replacement checkpoint")
        self.original = self.fixture.workspace / "project.pt"
        self.original.write_bytes(b"project checkpoint")
        self.errors = self.enterContext(patch(MODAL + "messagebox.showerror"))
        self.settle()

    def _close_root(self):
        for job in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", job)
        for child in self.root.winfo_children():
            child.destroy()
        self.root.update_idletasks()

    def settle(self):
        done = tk.BooleanVar(self.root, False)
        self.root.after(160, lambda: done.set(True))
        self.root.wait_variable(done)

    def widgets(self, widget):
        yield widget
        for child in widget.winfo_children():
            yield from self.widgets(child)

    def button(self, dialog, label):
        return next(widget for widget in self.widgets(dialog)
                    if "text" in widget.keys() and str(widget.cget("text")) == label
                    and callable(getattr(widget, "invoke", None)))

    def visible_text(self, dialog):
        return [str(widget.cget("text")) for widget in self.widgets(dialog)
                if "text" in widget.keys() and widget.winfo_ismapped()]

    def exercise(self, interact, *, starts=False):
        failures, called = [], []
        def callback():
            dialog = self.host._plate_auto_scope_active_dialog
            try:
                called.append(True)
                interact(dialog)
            except BaseException as exc:
                failures.append(exc)
                self.button(dialog, "Anuluj").invoke()
        self.root.after(200, callback)
        payload = self.host._prompt_plate_auto_scope_choice(candidate_image_paths=self.images)
        self.assertTrue(called, "Dialog did not open")
        if failures:
            raise failures[0]
        self.assertEqual(self.callback_errors, [])
        self.errors.assert_not_called()
        if starts:
            self.assertEqual(payload["image_paths"], self.images)
            self.host._close_plate_auto_scope_progress_modal()
            self.settle()
        else:
            self.assertIsNone(payload)

    def choose_replacement(self, dialog):
        picker = self.button(dialog, "Wybierz model…")
        self.assertTrue(picker.winfo_ismapped())
        with patch(MODAL + "filedialog.askopenfilename", return_value=str(self.replacement)):
            picker.invoke()
        self.settle()
        start = self.button(dialog, "Uruchom preanotację")
        self.assertEqual(str(start["state"]), "normal")
        with patch(MODAL + "validate_model_file",
                   return_value=(True, "", {"task":"pose", "keypoints":True, "kpt_shape":[4, 3]})):
            start.invoke()

    def test_gt_without_project_model_requires_explicit_selection(self):
        def interact(dialog):
            self.assertEqual(dialog.title(), "Preanotacja Ground Truth")
            self.assertTrue(self.button(dialog, "Wybierz model…").winfo_ismapped())
            self.assertEqual(str(self.button(dialog, "Uruchom preanotację")["state"]), "disabled")
            self.choose_replacement(dialog)
        self.exercise(interact, starts=True)
        self.assertEqual(Path(self.host.plate_custom_var.get()), self.replacement)
        self.assertEqual(self.host._plate_model_runtime_meta["scope"], "run")
        self.adopt.assert_not_called()

    def test_gt_project_default_can_be_replaced_without_project_adoption(self):
        self.project_name = "Project with MT"
        self.project_model = str(self.original)
        before = self.fixture.audit.load_participants(self.fixture.track)
        def interact(dialog):
            picker = self.button(dialog, "Wybierz model…")
            self.assertTrue(picker.winfo_ismapped())
            entry = next(child for child in picker.master.winfo_children() if isinstance(child, ttk.Entry))
            self.assertEqual(entry.get(), str(self.original))
            self.assertEqual(str(entry["state"]), "normal")
            self.assertFalse(any("Zmień model projektu" in text or "awaryjn" in text for text in self.visible_text(dialog)))
            self.choose_replacement(dialog)
        with patch.object(self.host, "_apply_campaign_plate_auto_model_choice") as campaign_choice:
            self.exercise(interact, starts=True)
            campaign_choice.assert_not_called()
        self.assertEqual(Path(self.host.plate_custom_var.get()), self.replacement)
        self.assertEqual(self.host._plate_model_runtime_meta["scope"], "run")
        self.adopt.assert_not_called()
        self.assertEqual(self.project_model, str(self.original))
        self.assertEqual(self.fixture.audit.load_participants(self.fixture.track), before)

    def test_gt_picker_and_run_scope_do_not_depend_on_free_mode_flag(self):
        self.project_name = "Project with MT"
        self.project_model = str(self.original)
        with patch.object(self.host, "_is_free_mode_session_context", return_value=False), \
             patch.object(self.host, "_apply_campaign_plate_auto_model_choice") as campaign_choice:
            self.exercise(self.choose_replacement, starts=True)
            campaign_choice.assert_not_called()
        self.assertEqual(Path(self.host.plate_custom_var.get()), self.replacement)
        self.assertEqual(self.host._plate_model_runtime_meta["scope"], "run")
        self.adopt.assert_not_called()

    def test_cancel_keeps_project_default_out_of_runtime(self):
        self.project_name = "Project with MT"
        self.project_model = str(self.original)
        self.exercise(lambda dialog: self.button(dialog, "Anuluj").invoke())
        self.assertEqual(self.host.plate_custom_var.get(), "")
        self.adopt.assert_not_called()

    def test_ordinary_z2_keeps_project_and_emergency_controls(self):
        self.host._experiment_gt_context = {}
        self.host._experiment_gt_workflow_active = False
        self.project_name = "Project with MT"
        self.project_model = str(self.original)
        def interact(dialog):
            self.assertEqual(dialog.title(), "Zakres autoanotacji")
            self.assertTrue(any(text.startswith("Model projektu:") for text in self.visible_text(dialog)))
            self.assertFalse(self.button(dialog, "Wybierz").winfo_ismapped())
            self.button(dialog, "Pokaż opcje awaryjne").invoke()
            self.settle()
            self.assertIn("Wskaż model jednorazowy dla bieżącej autoanotacji", self.visible_text(dialog))
            self.button(dialog, "Anuluj").invoke()
        self.exercise(interact)
        self.adopt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
