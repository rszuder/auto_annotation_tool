from types import SimpleNamespace
import gc
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

import test_pz3_sample_review_gui as raw_support
import test_z2_gt_model_selection as real_support
from auto_annotation_tool.data_models import ImageAnnotation
from auto_annotation_tool.gui import pz3_sample_route as route
from auto_annotation_tool.gui import pz3_sample_labels_ui as ui
from auto_annotation_tool.gui import z2_canvas_interaction as interaction
from auto_annotation_tool.registry.sample_labels import SampleLabels
from auto_annotation_tool.registry.sample_selection import prepare_sample_selection


class SampleLabelsGuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close_widgets)
        self.host = raw_support.SampleSelectionGuiTests().host()
        host = self.host
        host.frame = self.root
        host.preview_listbox = tk.Listbox(self.root, selectmode=tk.EXTENDED, exportselection=False)
        host.preview_listbox.pack(fill="both", expand=True)
        host._sample_filter_var = tk.StringVar(self.root, "Wszystkie")
        host._preview_list_display_indices = list(range(3))
        host._preview_list_display_index_map = {i: i for i in range(3)}
        host._sample_actual_by_sha = {"a": 0, "b": 1, "c": 2}
        host._sample_label_state = SampleLabels(host._experiment_sample_selected_sha256)
        host._sample_labels_panel = ui.SampleLabelsPanel(host, self.root)
        host._sample_labels_panel.pack(fill="x")
        host._refresh_preview_list = Mock(side_effect=AssertionError("No full list rebuild"))
        for ann in host.current_annotations:
            host.preview_listbox.insert(tk.END, route.sample_list_text(host, ann))
        host._get_selected_preview_actual_indices = lambda: [host._preview_list_display_indices[i]
                                                            for i in host.preview_listbox.curselection()]

    def close_widgets(self):
        # Release the host/panel callback cycle on the Tk thread, before a later
        # background-worker test can trigger collection of the old interpreter.
        self.root.destroy()
        self.host = self.root = None
        gc.collect()

    def test_add_custom_sample_label_with_real_dialog(self):
        def complete():
            dialog = next(child for child in self.host._sample_labels_panel.winfo_children()
                          if isinstance(child, ui.LabelNameDialog))
            dialog.entry.insert(0, "  Nietypowa tablica  ")
            dialog.ok()
        self.root.after(30, complete)
        self.host._sample_labels_panel.add_button.invoke()
        state = ui.label_state(self.host)
        self.assertEqual(list(state.labels.values()), ["Nietypowa tablica"])
        self.assertEqual(state.labels[state.active_id], "Nietypowa tablica")

    def test_only_one_sample_label_can_be_active(self):
        first = ui.add_sample_label(self.host, "Dzień")
        second = ui.add_sample_label(self.host, "Noc")
        panel = self.host._sample_labels_panel
        panel.rows[first][2].invoke()
        self.assertTrue(panel.rows[first][0].get())
        self.assertFalse(panel.rows[second][0].get())
        panel.rows[first][2].invoke()
        self.assertEqual(ui.label_state(self.host).active_id, "")

    def test_space_without_active_label_preserves_old_behavior(self):
        host = self.host
        interaction._on_preview_toggle_image_approval_shortcut(host, SimpleNamespace(keysym="space"))
        self.assertEqual(host._experiment_sample_selected_sha256, {"c"})
        self.assertEqual(ui.label_state(host).assignments, {})
        self.assertEqual(host._preview_approved_filenames, {"regular.png"})

    def test_space_with_active_label_adds_sample_and_label_then_removal_clears_label(self):
        host = self.host
        label = ui.add_sample_label(host, "Noc")
        host.current_preview_index = 1
        interaction._on_preview_toggle_image_approval_shortcut(host, SimpleNamespace(keysym="space"))
        state = ui.label_state(host)
        self.assertIn("b", host._experiment_sample_selected_sha256)
        self.assertEqual(state.assignments["b"], label)
        self.assertEqual(state.counts[label], 1)
        route.toggle_sample_badge(host)
        self.assertNotIn("b", state.assignments)
        self.assertNotIn("b", state.selected)
        self.assertEqual(state.counts[label], 0)

    def test_batch_add_uses_active_label_including_existing_members(self):
        host = self.host
        first = ui.add_sample_label(host, "Dzień")
        ui.assign_sample_label(host, first, [0])
        second = ui.add_sample_label(host, "Noc")
        host.preview_listbox.selection_set(0, 2)
        route.set_sample_selection(host, True)
        self.assertEqual(ui.label_state(host).assignments, dict.fromkeys(("a", "b", "c"), second))
        self.assertEqual(ui.label_state(host).counts[first], 0)
        self.assertEqual(ui.label_state(host).counts[second], 3)
        route.set_sample_selection(host, False)
        self.assertEqual(ui.label_state(host).assignments, {})
        self.assertEqual(ui.label_state(host).unlabeled_count, 0)

    def test_context_menu_changes_label_without_membership_change(self):
        host = self.host
        label = ui.add_sample_label(host, "Mocna perspektywa")
        host.preview_listbox.selection_set(0, 2)
        parent = tk.Menu(self.root, tearoff=False)
        menu = ui.build_label_menu(host, parent)
        self.root.tk.call(menu.cget("postcommand"))
        before = set(host._experiment_sample_selected_sha256)
        menu.invoke("Mocna perspektywa")
        self.assertEqual(host._experiment_sample_selected_sha256, before)
        self.assertEqual(ui.label_state(host).assignments, {"a": label, "c": label})
        menu.invoke("Usuń etykietę")
        self.assertEqual(ui.label_state(host).assignments, {})

    def test_label_counter_tracks_selected_members_only_and_unlabeled_counter(self):
        host = self.host
        label = ui.add_sample_label(host, "Deszcz")
        ui.assign_sample_label(host, label, [0, 1])
        state = ui.label_state(host)
        self.assertEqual(state.counts[label], 1)
        self.assertEqual(state.unlabeled_count, 1)
        self.assertEqual(host._sample_labels_panel.rows[label][1].get(), "1")
        self.assertEqual(host._sample_labels_panel.unlabeled.cget("text"), "Bez etykiety: 1")

    def test_rename_and_delete_update_rows_without_changing_membership(self):
        host = self.host
        label = ui.add_sample_label(host, "Noc")
        ui.assign_sample_label(host, label, [0, 2])
        ui.rename_sample_label(host, label, "Zmierzch")
        self.assertIn("Zmierzch", host.preview_listbox.get(0))
        self.assertNotIn("Zmierzch", host.preview_listbox.get(1))
        ui.delete_sample_label(host, label)
        self.assertEqual(host._experiment_sample_selected_sha256, {"a", "c"})
        self.assertEqual(ui.label_state(host).unlabeled_count, 2)

    def test_single_label_assignment_does_not_rebuild_10000_rows_and_preserves_scroll_selection(self):
        host = self.host
        names = [f"{i}.png" for i in range(10000)]
        host.current_annotations = [ImageAnnotation(name, 1, 1, detections=[]) for name in names]
        host._pz3_sample_selection_context.update(candidate_count=10000, sample_member_sha256={name: name for name in names})
        host._experiment_sample_selected_sha256 = set(names)
        host._sample_label_state = SampleLabels(host._experiment_sample_selected_sha256)
        host._sample_actual_by_sha = {name: i for i, name in enumerate(names)}
        host._preview_list_display_indices = list(range(10000))
        host._preview_list_display_index_map = {i: i for i in range(10000)}
        host._get_preview_display_index = Mock(side_effect=AssertionError("No copied global lookup"))
        host.preview_listbox.delete(0, tk.END)
        host.preview_listbox.insert(tk.END, *names)
        host.preview_listbox.selection_set(1000, 1005)
        host.preview_listbox.selection_anchor(1001)
        host.preview_listbox.activate(1003)
        host.preview_listbox.yview_moveto(0.5)
        before = host.preview_listbox.yview()
        label = ui.add_sample_label(host, "Noc")
        with patch.object(host.preview_listbox, "delete", wraps=host.preview_listbox.delete) as delete, \
             patch.object(host.preview_listbox, "insert", wraps=host.preview_listbox.insert) as insert, \
             patch("PIL.Image.open", side_effect=AssertionError("No image decoding")):
            ui.assign_sample_label(host, label, [4321])
        self.assertEqual(delete.call_count, 1)
        self.assertEqual(insert.call_count, 1)
        self.assertEqual(host.preview_listbox.curselection(), tuple(range(1000, 1006)))
        self.assertEqual(host.preview_listbox.index(tk.ANCHOR), 1001)
        self.assertEqual(host.preview_listbox.index(tk.ACTIVE), 1003)
        self.assertEqual(host.preview_listbox.yview(), before)
        self.assertEqual(ui.label_state(host).counts[label], 1)
        host._refresh_preview_list.assert_not_called()

    def test_filtered_membership_updates_rows_without_reload_or_decoding(self):
        host = self.host
        host._sample_filter_var.set("W próbie")
        host._preview_list_display_indices = [0, 2]
        host._preview_list_display_index_map = {0: 0, 2: 1}
        host.preview_listbox.delete(0, tk.END)
        host.preview_listbox.insert(tk.END, "one", "three")
        host.preview_listbox.selection_set(1)
        with patch("PIL.Image.open", side_effect=AssertionError("No decoding on membership change")):
            route.set_sample_selection(host, False, [0])
            self.assertEqual(host._preview_list_display_indices, [2])
            self.assertEqual(host.preview_listbox.curselection(), (0,))
            route.set_sample_selection(host, True, [0])
            self.assertEqual(host._preview_list_display_indices, [0, 2])
            self.assertEqual(host.preview_listbox.curselection(), (1,))
        host._refresh_preview_list.assert_not_called()

    def test_return_keeps_working_sample_outside_final_membership_commit(self):
        host = self.host
        ui.add_sample_label(host, "Noc")
        with patch.object(route, "persist_sample_review_draft", return_value=True),              patch.object(route, "EvaluationTrackService") as service,              patch.object(route, "_return_to_pz3") as back:
            route.return_sample_to_pz3(host)
        service.assert_not_called()
        back.assert_called_once()

    def test_working_autosave_carries_labels_and_selected_sha(self):
        host = self.host
        host._pz3_sample_selection_context["workspace"] = "WORKSPACE"
        label = ui.add_sample_label(host, "Noc")
        ui.assign_sample_label(host, label, [0])
        with patch.object(route, "EvaluationTrackService") as service,              patch.object(route, "save_sample_review_draft") as save:
            self.assertTrue(route.persist_sample_review_draft(host))
        service.assert_called_once_with("WORKSPACE")
        kwargs = save.call_args.kwargs
        self.assertEqual(kwargs["selected_sha256"], {"a", "c"})
        self.assertEqual(kwargs["sample_labels"]["assignments"], {"a": label})
        self.assertEqual(kwargs["active_label"], label)

    def test_lock_button_freezes_whole_label_class_and_unlock_restores_editing(self):
        host = self.host
        night = ui.add_sample_label(host, "Noc")
        ui.assign_sample_label(host, night, [0])
        day = ui.add_sample_label(host, "Dzień")

        ui.toggle_sample_label_lock(host, night)
        state = ui.label_state(host)
        self.assertTrue(state.is_label_locked(night))
        self.assertEqual(
            str(host._sample_labels_panel.rows[night][2]["state"]),
            "disabled",
        )
        self.assertEqual(
            host._sample_labels_panel.rows[night][3].cget("text"),
            "🔒",
        )

        before = dict(state.assignments)
        ui.assign_sample_label(host, day, [0, 2])
        self.assertEqual(state.assignments["a"], night)
        self.assertEqual(state.assignments["c"], day)
        self.assertIn(
            "Pominięto zablokowane: 1",
            host._sample_lock_notice,
        )

        ui.toggle_sample_label_lock(host, night)
        self.assertFalse(state.is_label_locked(night))
        ui.assign_sample_label(host, day, [0])
        self.assertEqual(state.assignments["a"], day)

    def test_unlabeled_lock_blocks_membership_and_assignment_until_unlock(self):
        host = self.host
        day = ui.add_sample_label(host, "Dzień")
        ui.toggle_unlabeled_lock(host)
        state = ui.label_state(host)
        self.assertTrue(state.unlabeled_locked)
        self.assertEqual(
            host._sample_labels_panel.unlabeled_lock.cget("text"),
            "🔒",
        )

        ui.assign_sample_label(host, day, [2])
        self.assertNotIn("c", state.assignments)
        route.set_sample_selection(host, False, [2])
        self.assertIn("c", state.selected)

        ui.toggle_unlabeled_lock(host)
        ui.assign_sample_label(host, day, [2])
        self.assertEqual(state.assignments["c"], day)

class SampleLabelsRealWorkspaceTests(unittest.TestCase):
    def test_leave_and_reopen_restores_labels_membership_and_active_label(self):
        real_support.GtModelSelectionTests.setUpClass()
        def close_root():
            real_support.GtModelSelectionTests.tearDownClass()
            real_support.GtModelSelectionTests.root = None
            gc.collect()
        self.addCleanup(close_root)
        case = real_support.GtModelSelectionTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        host = case.host
        original_context = dict(host._experiment_gt_context)
        context = prepare_sample_selection(case.fixture.service, case.fixture.track)
        self.assertTrue(route.enter_sample_selection(host, context))
        case.settle()
        label = ui.add_sample_label(host, "Noc")
        route.set_sample_selection(host, True, [0])
        expected = set(host._experiment_sample_selected_sha256)
        persisted = prepare_sample_selection(case.fixture.service, case.fixture.track)
        self.assertIsNotNone(persisted.get("sample_labels"))
        self.assertEqual(set(persisted["sample_initial_selected_sha256"]), expected)
        self.assertEqual(persisted["sample_active_label"], label)

        route.leave_sample_selection(host)
        self.assertEqual(host._experiment_gt_context, original_context)
        # Simulate process/UI-session loss: no in-memory fallback.
        host._sample_sessions = {}
        context = prepare_sample_selection(case.fixture.service, case.fixture.track)
        self.assertTrue(route.enter_sample_selection(host, context))
        case.settle()
        self.assertEqual(host._experiment_sample_selected_sha256, expected)
        self.assertEqual(ui.label_state(host).active_id, label)
        self.assertEqual(ui.label_state(host).counts[label], 1)
        self.assertEqual(ui.label_state(host).label_for(next(iter(expected))), "Noc")
        route.leave_sample_selection(host)
        self.assertEqual(case.callback_errors, [])

    def test_leave_and_reopen_restores_locked_groups(self):
        real_support.GtModelSelectionTests.setUpClass()

        def close_root():
            real_support.GtModelSelectionTests.tearDownClass()
            real_support.GtModelSelectionTests.root = None
            gc.collect()

        self.addCleanup(close_root)
        case = real_support.GtModelSelectionTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        host = case.host

        context = prepare_sample_selection(
            case.fixture.service, case.fixture.track
        )
        self.assertTrue(route.enter_sample_selection(host, context))
        case.settle()

        label = ui.add_sample_label(host, "Noc")
        route.set_sample_selection(host, True, [0])
        ui.toggle_sample_label_lock(host, label)
        ui.toggle_unlabeled_lock(host)

        route.leave_sample_selection(host)
        host._sample_sessions = {}

        context = prepare_sample_selection(
            case.fixture.service, case.fixture.track
        )
        self.assertEqual(
            set(context["sample_locked_label_ids"]), {label}
        )
        self.assertTrue(context["sample_unlabeled_locked"])

        self.assertTrue(route.enter_sample_selection(host, context))
        case.settle()
        state = ui.label_state(host)
        self.assertTrue(state.is_label_locked(label))
        self.assertTrue(state.unlabeled_locked)
        route.leave_sample_selection(host)
        self.assertEqual(case.callback_errors, [])


if __name__ == "__main__":
    unittest.main()
