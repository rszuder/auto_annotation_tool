"""Image loading used by RAW sample selection and the ordinary Z2 preview."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock

import cv2
import numpy as np
from PIL import Image

from auto_annotation_tool.data_models import ImageAnnotation
from auto_annotation_tool.gui import z2_preview_editor as editor, z2_preview_state as state
from auto_annotation_tool.gui.zoomable_canvas import ZoomableCanvas


class UnicodePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root_path = Path(self.temp.name)
        self.folder = self.root_path / "Porównanie_jakości_modeli" / "images"
        self.folder.mkdir(parents=True)

    def image(self, suffix=".png"):
        path = self.folder / ("Zdjęcie_001" + suffix)
        pixels = np.random.default_rng(17).integers(0, 256, (90, 160, 3), dtype=np.uint8)
        Image.fromarray(pixels).save(path)
        return path

    def test_cached_loader_reads_polish_paths_preserving_pixels_and_dimensions(self):
        for suffix in (".png", ".jpg"):
            with self.subTest(format=suffix):
                path = self.image(suffix)
                plain = self.root_path / ("plain" + suffix)
                plain.write_bytes(path.read_bytes())
                expected = cv2.cvtColor(cv2.imread(str(plain)), cv2.COLOR_BGR2RGB)
                host = SimpleNamespace()
                ann = ImageAnnotation(path.name, 1, 1, detections=[])
                loaded = state._load_preview_image_cached(host, path, ann)
                np.testing.assert_array_equal(np.asarray(loaded), expected)
                self.assertEqual((ann.width, ann.height), (160, 90))
                self.assertIs(state._load_preview_image_cached(host, path, ann), loaded)

    def test_unreadable_file_is_not_cached_as_an_image(self):
        host = SimpleNamespace()
        for content in (b"", b"<!DOCTYPE html><html>not an image</html>"):
            with self.subTest(content=content):
                path = self.folder / "BAD_001.jpg"
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    state._load_preview_image_cached(host, path)
                self.assertEqual(host._preview_render_image_cache, {})

    def test_sample_image_map_renders_on_real_canvas_with_cold_and_warm_cache(self):
        path = self.image()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(root.destroy)
        root.geometry("600x400")
        canvas = ZoomableCanvas(root, width=600, height=400)
        canvas.pack(fill=tk.BOTH, expand=True)
        root.update()
        ann = ImageAnnotation(path.name, 1, 1, detections=[])
        host = SimpleNamespace(preview_canvas=canvas, current_input_dir=self.root_path / "wrong",
                               _preview_image_path_map={path.name: path})
        host._resolve_preview_image_path = lambda value: state._resolve_preview_image_path(host, value)
        for name in ("_schedule_preview_layout_restore_after_resize", "_refresh_preview_legend_backdrop",
                     "_update_preview_canvas_metrics_overlay", "_place_preview_overlay_dock",
                     "_place_preview_campaign_gate_overlay", "_update_preview_toolbar_state"):
            setattr(host, name, Mock())
        for reset in (True, False):
            editor._render_preview_image(host, ann, reset_view=reset, fast_fullscreen=True)
            root.update()
            self.assertIsNotNone(canvas.original_image)
            self.assertEqual(canvas.original_image.size, (160, 90))
            self.assertEqual((ann.width, ann.height), (160, 90))
        self.assertEqual(len(host._preview_render_image_cache), 1)


if __name__ == "__main__":
    unittest.main()
