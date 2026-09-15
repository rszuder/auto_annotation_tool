from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from auto_annotation_tool.gui import pz3_sample_route as route


class SampleReviewGuiTests(unittest.TestCase):
    def host(self):
        return SimpleNamespace(
            _experiment_gt_context={
                "source": "pz3", "track_id": "TRK", "sample_selection": True,
                "candidate_count": 3, "sample_member_sha256": {"ONE.png": "a", "two.png": "b", "three.png": "c"},
                "sample_audit_id": "AUDIT",
            },
            _get_preview_approved_filenames_base=Mock(return_value={"one.png", "three.png"}),
            is_processing=False, frame=object(), app=SimpleNamespace(root=object()),
            _save_preview_edits=Mock(return_value=True),
            _get_current_annotation_xml_path=Mock(return_value=Path("working/annotations.xml")),
            _open_existing_run_for_manual_review=Mock(return_value=True),
        )

    def test_counter_keeps_all_approvals_across_navigation_and_filters(self):
        host = self.host()
        for current, visible in ((0, [0, 1, 2]), (1, [1]), (2, [])):
            host.current_preview_index = current
            host._preview_list_display_indices = visible
            self.assertEqual(route.approved_sample_names(host), {"ONE.png", "three.png"})
            self.assertEqual(route.sample_counter(host), "Zatwierdzone: 2 / 3")

    def test_commit_uses_member_shas_and_returns_after_success(self):
        host = self.host()
        expected_map = dict(host._experiment_gt_context["sample_member_sha256"])
        with patch.object(route.messagebox, "askyesno", return_value=True), \
             patch.object(route, "BatchProgressDialog") as dialog, \
             patch.object(route, "EvaluationTrackService") as service, \
             patch.object(route, "_return_to_pz3") as back:
            update = Mock()
            dialog.return_value.run.side_effect = lambda operation: operation(update)
            service.return_value.commit_reviewed_sample.return_value = {
                "selected_count": 2, "candidate_count": 3}
            route.return_sample_to_pz3(host)
        service.return_value.commit_reviewed_sample.assert_called_once_with(
            "TRK", keep_sha256={"a", "c"}, expected_member_sha256=expected_map,
            expected_audit_id="AUDIT", working_xml=Path("working/annotations.xml"), progress=update)
        dialog.return_value.close.assert_called_once()
        back.assert_called_once()
        host._save_preview_edits.assert_called_once_with(interactive=True)

    def test_cancelled_confirmation_and_empty_selection_do_not_write_draft(self):
        for empty in (False, True):
            host = self.host()
            if empty:
                host._get_preview_approved_filenames_base.return_value = set()
            with self.subTest(empty=empty), \
                 patch.object(route.messagebox, "askyesno", return_value=False), \
                 patch.object(route.messagebox, "showwarning"), \
                 patch.object(route, "EvaluationTrackService") as service:
                route.return_sample_to_pz3(host)
                service.assert_not_called()
                host._save_preview_edits.assert_not_called()
                self.assertTrue(host._experiment_gt_context["sample_selection"])

    def test_commit_failure_keeps_review_open_and_shows_error(self):
        host = self.host()
        with patch.object(route.messagebox, "askyesno", return_value=True), \
             patch.object(route.messagebox, "showerror") as error, \
             patch.object(route, "BatchProgressDialog") as dialog, \
             patch.object(route, "EvaluationTrackService") as service, \
             patch.object(route, "_return_to_pz3") as back:
            dialog.return_value.run.side_effect = lambda operation: operation(Mock())
            service.return_value.commit_reviewed_sample.side_effect = OSError("disk full")
            route.return_sample_to_pz3(host)
        back.assert_not_called()
        error.assert_called_once()
        self.assertTrue(host._experiment_gt_context["sample_selection"])
        dialog.return_value.close.assert_called_once()

    def test_return_without_commit_preserves_draft_and_saves_review_for_resume(self):
        host = self.host()
        with patch.object(route, "EvaluationTrackService") as service, \
             patch.object(route, "_return_to_pz3") as back:
            route.cancel_sample_review(host)
        service.return_value.commit_reviewed_sample.assert_not_called()
        service.return_value.deactivate_z2_context.assert_called_once_with(track_id="TRK")
        host._save_preview_edits.assert_called_once_with(interactive=True)
        back.assert_called_once()



    def test_fullscreen_badge_keeps_large_counter_visible_with_drawer_hidden(self):
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
                for hidden in (False, True):
                    with self.subTest(scaling=scaling, hidden=hidden):
                        for previous in root.pack_slaves():
                            previous.destroy()
                        surface = tk.Frame(root)
                        surface.pack(fill="both", expand=True)
                        canvas = tk.Canvas(surface)
                        canvas.original_image = object()
                        canvas.pack(fill="both", expand=True)
                        panel = tk.Frame(surface, width=174, height=150)
                        if not hidden:
                            panel.place(x=310, y=46, width=174, height=150)
                        frame = tk.Frame(surface, highlightthickness=1)
                        label = tk.Label(frame, padx=7, pady=4)
                        label.pack(fill="both", expand=True)
                        names = {f"{i}.png" for i in range(10000)}
                        host = SimpleNamespace(
                            app=SimpleNamespace(palette={}), canvas_frame=surface, preview_canvas=canvas,
                            preview_overlay_dock=panel, preview_image_status_frame=frame,
                            preview_image_status_lbl=label, _preview_fullscreen_active=True,
                            _get_preview_annotation=lambda: SimpleNamespace(filename="0.png"),
                            _preview_annotation_is_explicitly_approved=lambda ann: True,
                            _get_preview_legend_theme=lambda: {}, _legend_color_is_light=lambda fill: False,
                            _get_preview_approved_filenames_base=lambda: names,
                            _experiment_gt_context={
                                "source": "pz3", "track_id": "TRK", "sample_selection": True,
                                "candidate_count": 10000, "sample_member_sha256": {name: name for name in names},
                            },
                        )
                        host._render_preview_image_status_overlay = lambda **kwargs: dock.render_preview_image_status_overlay(host, **kwargs)
                        root.update()
                        overlays._place_preview_image_status_overlay(host, force_render=True)
                        root.update()
                        self.assertTrue(label.winfo_ismapped())
                        font = tkfont.Font(root, font=label.cget("font"))
                        self.assertLessEqual(font.measure("Zatwierdzone: 10000 / 10000") + 14,
                                             label.winfo_width())
                        self.assertLessEqual(label.winfo_reqheight(), frame.winfo_height())
                        self.assertIn("10000 / 10000", label.cget("text"))
                        surface.destroy()
        finally:
            root.tk.call("tk", "scaling", old_scaling)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
