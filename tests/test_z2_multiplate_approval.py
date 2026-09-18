from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from auto_annotation_tool.data_models import Detection, ImageAnnotation
from auto_annotation_tool.gui import z2_manifest_runtime as manifest
from auto_annotation_tool.gui import z2_canvas_interaction as interaction


def make_plate():
    return Detection(
        label="plate", confidence=0.9, bbox=(0.0, 0.0, 20.0, 10.0),
        polygon=[(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)],
    )


def make_ann(name="multi.jpg", count=2):
    return ImageAnnotation(
        filename=name, width=100, height=50,
        detections=[make_plate() for _ in range(count)],
    )


class Host(SimpleNamespace):
    def _is_free_mode_session_context(self):
        return True
    def _get_plate_detections(self, annotation):
        return list(annotation.detections)
    def _get_preview_approved_filenames_base(self):
        return set(getattr(self, "_preview_approved_filenames", set()) or set())
    def _preview_annotation_can_be_approved_for_export(self, annotation):
        return bool(self._get_plate_detections(annotation))
    def _preview_annotation_is_explicitly_approved(self, annotation, approved_names=None):
        return manifest._preview_annotation_is_explicitly_approved(
            self, annotation, approved_names=approved_names
        )
    def _preview_plate_frame_is_approved(self, annotation, det, approved_names=None):
        return manifest._preview_plate_frame_is_approved(
            self, annotation, det, approved_names=approved_names
        )
    def _preview_annotation_plate_approval_summary(self, annotation, approved_names=None):
        return manifest._preview_annotation_plate_approval_summary(
            self, annotation, approved_names=approved_names
        )
    def _set_preview_plate_frame_approved(self, det, approved):
        return manifest._set_preview_plate_frame_approved(self, det, approved)
    def _materialize_legacy_plate_frame_approvals(self, annotation, approved_names=None):
        return manifest._materialize_legacy_plate_frame_approvals(
            self, annotation, approved_names=approved_names
        )
    def _reconcile_preview_approved_runtime_from_frames(self):
        return manifest._reconcile_preview_approved_runtime_from_frames(self)
    def _invalidate_preview_runtime_caches(self):
        pass


class Z2MultiPlateApprovalTests(unittest.TestCase):
    def test_two_frames_require_both_before_image_ok(self):
        image = make_ann()
        host = Host(current_annotations=[image], _preview_approved_filenames=set(), _preview_approval_version=0)
        first, second = image.detections
        self.assertFalse(manifest._preview_annotation_is_explicitly_approved(host, image))
        manifest._set_preview_plate_frame_approved(host, first, True)
        summary = manifest._preview_annotation_plate_approval_summary(host, image)
        self.assertEqual(summary["approved"], 1)
        self.assertFalse(summary["all_approved"])
        manifest._set_preview_plate_frame_approved(host, second, True)
        self.assertTrue(manifest._preview_annotation_is_explicitly_approved(host, image))

    def test_legacy_ok_materializes_before_one_frame_is_revoked(self):
        image = make_ann("legacy.jpg")
        image._approved_for_training = True
        host = Host(current_annotations=[image], _preview_approved_filenames={"legacy.jpg"}, _preview_approval_version=0)
        self.assertTrue(manifest._preview_annotation_is_explicitly_approved(host, image))
        self.assertEqual(
            manifest._materialize_legacy_plate_frame_approvals(host, image, {"legacy.jpg"}), 2
        )
        manifest._set_preview_plate_frame_approved(host, image.detections[0], False)
        host._preview_approved_filenames = set()
        image._approved_for_training = False
        summary = manifest._preview_annotation_plate_approval_summary(host, image)
        self.assertEqual(summary["approved"], 1)
        self.assertFalse(summary["all_approved"])

    def test_bulk_helper_sets_all_frames(self):
        image = make_ann()
        host = Host(current_annotations=[image], _preview_approved_filenames=set(), _preview_approval_version=0)
        self.assertEqual(manifest._set_all_preview_plate_frames_approved(host, image, True), 2)
        self.assertTrue(manifest._preview_annotation_is_explicitly_approved(host, image))
        self.assertEqual(manifest._set_all_preview_plate_frames_approved(host, image, False), 2)
        self.assertFalse(manifest._preview_annotation_is_explicitly_approved(host, image))

    def test_runtime_reconcile_tracks_frame_truth(self):
        image = make_ann("reconcile.jpg")
        host = Host(current_annotations=[image], _preview_approved_filenames=set(), _preview_approval_version=0)
        manifest._set_all_preview_plate_frames_approved(host, image, True)
        self.assertEqual(manifest._reconcile_preview_approved_runtime_from_frames(host), {"reconcile.jpg"})
        manifest._set_preview_plate_frame_approved(host, image.detections[0], False)
        self.assertEqual(manifest._reconcile_preview_approved_runtime_from_frames(host), set())

    def _space_host(self, image):
        return Host(
            current_annotations=[image], current_preview_index=0,
            _preview_draw_mode=False, _preview_approved_filenames=set(), _preview_approval_version=0,
            preview_canvas=SimpleNamespace(focus_set=Mock()),
            _preview_shortcuts_enabled=lambda *a, **k: True,
            _preview_shortcut_is_duplicate=lambda *a, **k: False,
            _get_preview_annotation=lambda: image,
            _get_selected_plate_index_for_ann=lambda _ann: 0,
            _push_preview_history_snapshot=Mock(),
            _mark_preview_image_dirty=Mock(),
            _refresh_preview_list_row_for_actual_index=Mock(),
            _update_preview_toolbar_state=Mock(),
            _update_preview_approval_badge_fast=Mock(),
            _refresh_preview_canvas_light=Mock(),
            _schedule_preview_autosave=Mock(),
            _update_preview_edit_status=Mock(),
        )

    def test_space_toggles_only_selected_frame(self):
        image = make_ann("space.jpg")
        host = self._space_host(image)
        self.assertEqual(interaction._on_preview_toggle_image_approval_shortcut(host), "break")
        self.assertEqual(image.detections[0].attributes[manifest.PLATE_FRAME_APPROVAL_ATTR], "true")
        self.assertNotIn(manifest.PLATE_FRAME_APPROVAL_ATTR, image.detections[1].attributes)
        self.assertFalse(manifest._preview_annotation_is_explicitly_approved(host, image))

    def test_single_plate_space_still_makes_image_ok(self):
        image = make_ann("single.jpg", 1)
        host = self._space_host(image)
        interaction._on_preview_toggle_image_approval_shortcut(host)
        self.assertTrue(manifest._preview_annotation_is_explicitly_approved(host, image))
        self.assertEqual(host._preview_approved_filenames, {"single.jpg"})


if __name__ == "__main__":
    unittest.main()
