from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from auto_annotation_tool.data_models import ImageAnnotation
from auto_annotation_tool.gui import pz3_sample_route as route
from auto_annotation_tool.gui import z2_canvas_interaction as interaction


class SampleSelectionGuiTests(unittest.TestCase):
    def host(self):
        host = SimpleNamespace(
            _pz3_sample_selection_context={
                "source": "pz3", "purpose": "sample_selection", "track_id": "TRK",
                "candidate_count": 3, "sample_member_sha256": {"ONE.png": "a", "two.png": "b", "three.png": "c"},
                "sample_audit_id": "AUDIT",
            },
            _experiment_gt_context={}, _experiment_sample_selected_sha256={"a", "c"},
            _get_preview_approved_filenames_base=Mock(side_effect=AssertionError("No approval in RAW")),
            _preview_annotation_can_be_approved_for_export=Mock(side_effect=AssertionError("No annotation guard in RAW")),
            _preview_approved_filenames={"regular.png"}, current_preview_index=0,
            current_annotations=[ImageAnnotation(name, 1, 1, detections=[]) for name in ("ONE.png", "two.png", "three.png")],
            _refresh_preview_list=Mock(), _place_preview_image_status_overlay=Mock(),
            _preview_shortcuts_enabled=Mock(return_value=True),
            _preview_shortcut_is_duplicate=Mock(return_value=False),
            _get_selected_preview_actual_indices=Mock(return_value=[1]), preview_canvas=Mock(),
            is_processing=False, frame=object(), app=SimpleNamespace(root=object()),
            _save_preview_edits=Mock(side_effect=AssertionError("No GT save in RAW")),
            _get_current_annotation_xml_path=Mock(side_effect=AssertionError("No XML in RAW")),
        )
        host._get_preview_annotation = lambda: host.current_annotations[host.current_preview_index]
        return host

    def test_counter_keeps_selection_across_navigation_and_filters(self):
        host = self.host()
        for current, visible in ((0, [0, 1, 2]), (1, [1]), (2, [])):
            host.current_preview_index = current
            host._preview_list_display_indices = visible
            self.assertEqual(route.selected_sample_names(host), {"ONE.png", "three.png"})
            self.assertEqual(route.sample_counter(host), "Wybrano: 2 / 3")
        host._get_preview_approved_filenames_base.assert_not_called()

    def test_space_and_group_selection_work_with_zero_annotations(self):
        host = self.host()
        host._experiment_sample_selected_sha256 = set()
        interaction._on_preview_toggle_image_approval_shortcut(host, SimpleNamespace(keysym="space"))
        self.assertEqual(host._experiment_sample_selected_sha256, {"a"})
        route.set_sample_selection(host, True, [1, 2])
        self.assertEqual(host._experiment_sample_selected_sha256, {"a", "b", "c"})
        route.set_sample_selection(host, False, [1])
        self.assertEqual(host._experiment_sample_selected_sha256, {"a", "c"})
        route.toggle_sample_badge(host)
        self.assertEqual(host._experiment_sample_selected_sha256, {"c"})
        self.assertEqual(host._preview_approved_filenames, {"regular.png"})
        self.assertTrue(all(not ann.detections for ann in host.current_annotations))
        host._preview_annotation_can_be_approved_for_export.assert_not_called()
        host._get_preview_approved_filenames_base.assert_not_called()
        self.assertEqual(host._experiment_gt_context, {})

    def test_commit_uses_sha_and_never_saves_gt(self):
        host = self.host()
        expected = dict(host._pz3_sample_selection_context["sample_member_sha256"])
        with patch.object(route.messagebox, "askyesno", return_value=True), \
             patch.object(route, "BatchProgressDialog") as dialog, \
             patch.object(route, "EvaluationTrackService") as service, \
             patch.object(route, "_return_to_pz3") as back:
            update = Mock()
            dialog.return_value.run.side_effect = lambda operation: operation(update)
            service.return_value.commit_sample_selection.return_value = {"selected_count": 2, "candidate_count": 3}
            route.return_sample_to_pz3(host)
        service.return_value.commit_sample_selection.assert_called_once_with(
            "TRK", keep_sha256={"a", "c"}, expected_member_sha256=expected,
            expected_audit_id="AUDIT", progress=update)
        dialog.return_value.close.assert_called_once()
        back.assert_called_once()
        host._save_preview_edits.assert_not_called()
        host._get_current_annotation_xml_path.assert_not_called()

    def test_cancelled_confirmation_and_empty_selection_do_not_write_draft(self):
        for empty in (False, True):
            host = self.host()
            if empty:
                host._experiment_sample_selected_sha256.clear()
            with self.subTest(empty=empty), \
                 patch.object(route.messagebox, "askyesno", return_value=False), \
                 patch.object(route.messagebox, "showwarning"), \
                 patch.object(route, "EvaluationTrackService") as service:
                route.return_sample_to_pz3(host)
                service.assert_not_called()
                host._save_preview_edits.assert_not_called()
                self.assertIsNotNone(route.sample_context(host))

    def test_commit_failure_keeps_selection_open(self):
        host = self.host()
        with patch.object(route.messagebox, "askyesno", return_value=True), \
             patch.object(route.messagebox, "showerror") as error, \
             patch.object(route, "BatchProgressDialog") as dialog, \
             patch.object(route, "EvaluationTrackService") as service, \
             patch.object(route, "_return_to_pz3") as back:
            dialog.return_value.run.side_effect = lambda operation: operation(Mock())
            service.return_value.commit_sample_selection.side_effect = OSError("disk full")
            route.return_sample_to_pz3(host)
        back.assert_not_called()
        error.assert_called_once()
        self.assertEqual(host._experiment_sample_selected_sha256, {"a", "c"})
        dialog.return_value.close.assert_called_once()

    def test_cancel_does_not_save_or_change_membership(self):
        host = self.host()
        with patch.object(route, "EvaluationTrackService") as service, \
             patch.object(route, "_return_to_pz3") as back:
            route.cancel_sample_review(host)
        service.assert_not_called()
        host._save_preview_edits.assert_not_called()
        back.assert_called_once()

    def test_regular_approval_still_requires_plate_annotation(self):
        host = self.host()
        host._pz3_sample_selection_context = {}
        host._preview_draw_mode = False
        host._is_free_mode_session_context = Mock(return_value=True)
        host._preview_annotation_can_be_approved_for_export = Mock(return_value=False)
        host._update_preview_edit_status = Mock()
        host._update_preview_canvas_metrics_overlay = Mock()
        host._set_selected_preview_images_approved = Mock()
        interaction._on_preview_toggle_image_approval_shortcut(host)
        host._set_selected_preview_images_approved.assert_not_called()
        self.assertIn("najpierw dodaj ramkę", host._update_preview_edit_status.call_args.args[0])

    def test_raw_mode_blocks_annotation_export_and_geometry_actions(self):
        from auto_annotation_tool.gui import z2_annotation_process, z2_export_workflow, z2_preview_workflow
        host = self.host()
        host._update_preview_edit_status = Mock()
        host._get_workflow_route = Mock(side_effect=AssertionError("Should not enter annotation pipeline"))
        host._get_preview_annotation = Mock(side_effect=AssertionError("Should not edit annotations"))
        z2_annotation_process._start_annotation(host)
        z2_export_workflow._start_plate_dataset_export(host)
        z2_export_workflow._start_plate_annotation_package_export(host)
        interaction._toggle_preview_draw_mode(host)
        interaction._toggle_preview_delete_mode(host)
        from auto_annotation_tool.gui import z2_session_runtime
        z2_session_runtime.flush_free_mode_session_state(host)
        self.assertTrue(z2_preview_workflow._save_preview_edits(host))
        host._get_preview_annotation.assert_not_called()
        host._get_workflow_route.assert_not_called()

    def test_badge_with_10000_raw_images_at_large_scaling(self):
        import tkinter as tk
        import tkinter.font as tkfont
        from auto_annotation_tool.gui import z2_canvas_overlays as overlays
        from auto_annotation_tool.gui import z2_overlay_dock_ui as dock
        root = tk.Tk()
        root.geometry("500x420+20+20")
        old_scaling = root.tk.call("tk", "scaling")
        try:
            for scaling in (1.33, 2.0):
                root.tk.call("tk", "scaling", scaling)
                for fullscreen in (False, True):
                    with self.subTest(scaling=scaling, fullscreen=fullscreen):
                        for previous in root.pack_slaves():
                            previous.destroy()
                        surface = tk.Frame(root)
                        surface.pack(fill="both", expand=True)
                        canvas = tk.Canvas(surface)
                        canvas.original_image = object()
                        canvas.pack(fill="both", expand=True)
                        frame = tk.Frame(surface, highlightthickness=1)
                        label = tk.Label(frame, padx=7, pady=4)
                        label.pack(fill="both", expand=True)
                        names = {f"{i}.png" for i in range(10000)}
                        host = SimpleNamespace(
                            app=SimpleNamespace(palette={}), canvas_frame=surface, preview_canvas=canvas,
                            preview_image_status_frame=frame, preview_image_status_lbl=label,
                            _preview_fullscreen_active=fullscreen,
                            _get_preview_annotation=lambda: SimpleNamespace(filename="0.png"),
                            _preview_annotation_is_explicitly_approved=Mock(side_effect=AssertionError("No annotation approval")),
                            _get_preview_legend_theme=lambda: {}, _legend_color_is_light=lambda fill: False,
                            _experiment_sample_selected_sha256=names,
                            _pz3_sample_selection_context={
                                "source": "pz3", "purpose": "sample_selection", "track_id": "TRK",
                                "candidate_count": 10000, "sample_member_sha256": {name: name for name in names},
                            },
                        )
                        host._render_preview_image_status_overlay = lambda **kwargs: dock.render_preview_image_status_overlay(host, **kwargs)
                        root.update()
                        overlays._place_preview_image_status_overlay(host, force_render=True)
                        root.update()
                        self.assertTrue(label.winfo_ismapped())
                        font = tkfont.Font(root, font=label.cget("font"))
                        self.assertLessEqual(font.measure("Wybrano: 10000 / 10000") + 14, label.winfo_width())
                        self.assertLessEqual(label.winfo_reqheight(), frame.winfo_height())
                        self.assertIn("10000 / 10000", label.cget("text"))
                        surface.destroy()
        finally:
            root.tk.call("tk", "scaling", old_scaling)
            root.destroy()



    def test_main_tab_refresh_does_not_enter_gt_workflow(self):
        from auto_annotation_tool.gui import z2_panel_workflow
        host = self.host()
        with patch.object(z2_panel_workflow, "apply_pending_experiment_gt_entry",
                          side_effect=AssertionError("No GT entry during RAW")) as gt, \
             patch.object(route, "show_sample_workspace") as show:
            z2_panel_workflow._refresh_free_mode_workflow_ui(host)
        gt.assert_not_called()
        show.assert_called_once_with(host)
        self.assertEqual(host._experiment_gt_context, {})

    def test_single_toggle_in_9000_rows_preserves_group_and_scroll_without_full_reload(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            host = self.host()
            names = [f"{i}.png" for i in range(9000)]
            host.current_annotations = [ImageAnnotation(name, 1, 1, detections=[]) for name in names]
            host._pz3_sample_selection_context.update(
                candidate_count=len(names), sample_member_sha256={name: name for name in names})
            host._experiment_sample_selected_sha256 = set()
            host.current_preview_index = 4321
            host.preview_listbox = tk.Listbox(root, selectmode=tk.EXTENDED, height=10)
            host.preview_listbox.insert(tk.END, *names)
            host.preview_listbox.selection_set(1000, 1005)
            host.preview_listbox.yview_moveto(0.5)
            before = host.preview_listbox.yview()
            host._sample_filter_var = SimpleNamespace(get=lambda: "Wszystkie")
            host._get_preview_display_index = lambda index: index
            host._refresh_preview_list = Mock(side_effect=AssertionError("No full list rebuild for Space"))
            route.toggle_sample_badge(host)
            self.assertEqual(host._experiment_sample_selected_sha256, {"4321.png"})
            self.assertEqual(host.preview_listbox.curselection(), tuple(range(1000, 1006)))
            self.assertEqual(host.preview_listbox.yview(), before)
            self.assertIn("[W PRÓBIE]", host.preview_listbox.get(4321))
            host._refresh_preview_list.assert_not_called()
            host._preview_annotation_can_be_approved_for_export.assert_not_called()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
