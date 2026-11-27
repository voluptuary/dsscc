"""Regression tests for the manual Image Converter tab."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "DS Style Thumbnail Scraper.py"
SPEC = importlib.util.spec_from_file_location("thumbnail_scraper_image_converter_test", APP_PATH)
APP_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = APP_MODULE
SPEC.loader.exec_module(APP_MODULE)


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def converter_app(size="80x80"):
    app = object.__new__(APP_MODULE.ThumbnailScraperApp)
    app.converter_size_var = Value(size)
    app.converter_zoom_var = Value(1.0)
    app.converter_crop_x_var = Value(0.0)
    app.converter_crop_y_var = Value(0.0)
    app.converter_source_image = Image.new("RGBA", (200, 100), (220, 40, 40, 255))
    app.converter_source_path = Path("art.png")
    app.status_var = Value("")
    return app


class ImageConverterTests(unittest.TestCase):
    def test_size_toggle_returns_kernel_dimensions(self):
        self.assertEqual(converter_app("80x80").converter_render_size(), (80, 80))
        self.assertEqual(converter_app("120x80").converter_render_size(), (120, 80))

    def test_export_writes_expected_gba_bmp_and_marks_transparency(self):
        app = converter_app("120x80")
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "converted.bmp"
            with patch.object(
                APP_MODULE.filedialog, "asksaveasfilename", return_value=str(target)
            ), patch.object(APP_MODULE.messagebox, "showinfo"):
                app.export_converter_bmp()

            data = target.read_bytes()
            self.assertTrue(data.startswith(b"BM"))
            self.assertEqual(data[6:10], b"DST1")
            width, height = int.from_bytes(data[18:22], "little"), abs(
                int.from_bytes(data[22:26], "little", signed=True)
            )
            self.assertEqual((width, height), (120, 80))
            self.assertEqual(int.from_bytes(data[28:30], "little"), 16)

    def test_export_does_not_mark_an_opaque_image_as_transparent(self):
        app = converter_app("80x80")
        app.converter_source_image = Image.new("RGB", (80, 80), (20, 60, 180))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "opaque.bmp"
            with patch.object(
                APP_MODULE.filedialog, "asksaveasfilename", return_value=str(target)
            ), patch.object(APP_MODULE.messagebox, "showinfo"):
                app.export_converter_bmp()
            self.assertNotEqual(target.read_bytes()[6:10], b"DST1")


if __name__ == "__main__":
    unittest.main()
