"""Regression tests for per-size CUSTOM manifest capacity."""

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "DS Style Thumbnail Scraper.py"
SPEC = importlib.util.spec_from_file_location("thumbnail_scraper_custom_limits_test", APP_PATH)
APP_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = APP_MODULE
SPEC.loader.exec_module(APP_MODULE)


class CustomArtOutputLimitTests(unittest.TestCase):
    def test_rejects_windows_reserved_device_names(self):
        for name in (
            "CON", "con.bmp", "NUL.preview", "PRN", "AUX", "COM1", "lpt9.bmp",
            "CONIN$", "CONOUT$", "COM¹", "LPT³",
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "reserved Windows"):
                APP_MODULE.validate_custom_art_name(name)

    def test_allows_names_that_only_resemble_reserved_devices(self):
        for name in ("CONSOLE", "COM0", "COM10", "LPT10", "NUL artwork"):
            with self.subTest(name=name):
                self.assertEqual(APP_MODULE.validate_custom_art_name(name), name)

    def test_limit_is_independent_for_title_and_box_art(self):
        counts = {
            "120x80": {f"title-{index}" for index in range(256)},
            "80x80": {f"box-{index}" for index in range(256)},
        }

        self.assertEqual(APP_MODULE.custom_output_manifest_overflow(counts), {})

    def test_257th_file_overflows_only_its_size(self):
        counts = {
            "120x80": {f"title-{index}" for index in range(257)},
            "80x80": {f"box-{index}" for index in range(256)},
        }

        self.assertEqual(
            APP_MODULE.custom_output_manifest_overflow(counts),
            {"120x80": 257},
        )

    def test_extension_default_uses_a_custom_manifest_entry(self):
        counts = {
            "120x80": {f"title-{index}" for index in range(255)} | {"gb"},
            "80x80": set(),
        }

        self.assertEqual(APP_MODULE.custom_output_manifest_overflow(counts), {})
        counts["120x80"].add("extra-title")
        self.assertEqual(
            APP_MODULE.custom_output_manifest_overflow(counts),
            {"120x80": 257},
        )


if __name__ == "__main__":
    unittest.main()
