"""The real Z2 canvas must keep fullscreen controls visible and clickable."""
import unittest
import gc

import test_z2_gt_model_selection as gt_support


class FullscreenControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gt_support.GtModelSelectionTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        gt_support.GtModelSelectionTests.tearDownClass()
        gt_support.GtModelSelectionTests.root = None
        gc.collect()

    def setUp(self):
        self.case = gt_support.GtModelSelectionTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.root, self.host = self.case.root, self.case.host
        # Native hit testing must see this window, not an unrelated desktop app.
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.addCleanup(self.root.attributes, "-topmost", False)
        self.settle()

    def settle(self):
        for _ in range(3):
            self.case.settle()

    def assert_fullscreen_control_accessible(self):
        canvas = self.host.preview_canvas
        x1, y1, x2, y2 = self.host._preview_fullscreen_toggle_bbox
        for cx, cy in ((x1+2, y1+2), (x2-2, y2-2), ((x1+x2)/2, (y1+y2)/2)):
            self.assertTrue(self.host._is_preview_fullscreen_toggle_hit(cx, cy))
            vx, vy = cx-canvas.canvasx(0), cy-canvas.canvasy(0)
            self.assertTrue(0 <= vx < canvas.winfo_width())
            self.assertTrue(0 <= vy < canvas.winfo_height())
            hit = self.root.winfo_containing(
                int(canvas.winfo_rootx()+vx), int(canvas.winfo_rooty()+vy)
            )
            self.assertIs(hit, canvas, f"Fullscreen icon is covered by {hit}")
        self.assertEqual(self.case.callback_errors, [])

    def test_icon_remains_accessible_with_open_and_closed_drawer(self):
        self.host._preview_super_correction_badge_visible = True
        for fullscreen in (False, True):
            self.host._set_preview_fullscreen(fullscreen)
            self.settle()
            sizes = (None,) if fullscreen else ("1100x800+20+20", "960x640+20+20")
            for size in sizes:
                with self.subTest(fullscreen=fullscreen, size=size):
                    if size is not None:
                        self.root.geometry(size)
                    self.settle()
                    self.assertEqual(self.host._preview_fullscreen_active, fullscreen)
                    self.host.preview_canvas.refresh_overlay_only()
                    self.assert_fullscreen_control_accessible()
                    if fullscreen:
                        slide = self.host._preview_drawer_slide
                        for _ in range(2):
                            slide.toggle()
                            self.settle()
                            self.assert_fullscreen_control_accessible()

    def test_icon_click_enters_and_exits_fullscreen(self):
        for active in (True, False):
            canvas = self.host.preview_canvas
            self.assert_fullscreen_control_accessible()
            x1, y1, x2, y2 = self.host._preview_fullscreen_toggle_bbox
            x = round((x1+x2)/2 - canvas.canvasx(0))
            y = round((y1+y2)/2 - canvas.canvasy(0))
            canvas.event_generate("<ButtonPress-1>", x=x, y=y)
            canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
            self.settle()
            self.assertEqual(self.host._preview_fullscreen_active, active)
            self.assert_fullscreen_control_accessible()


if __name__ == "__main__":
    unittest.main()
