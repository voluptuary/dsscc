"""Offline regression tests for standalone GBA utility inputs."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import ezflash_gba_thumbs
from ezflash_gba_full_library import build_parser as build_full_library_parser
from ezflash_gba_pack_converter import build_parser as build_pack_converter_parser
from ezflash_gba_thumbs import (
    MAX_OUTPUT_DIMENSION,
    MAX_OUTPUT_PIXELS,
    build_parser as build_thumbs_parser,
    iter_gba_files,
    validate_output_size,
    write_ezflash_bmp,
)


class GbaCliValidationTests(unittest.TestCase):
    def test_libretro_http_get_caps_response_size(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"x" * 9

        with patch.object(ezflash_gba_thumbs, "MAX_HTTP_RESPONSE_BYTES", 8), patch.object(
            ezflash_gba_thumbs.urllib.request, "urlopen", return_value=response
        ):
            with self.assertRaisesRegex(ValueError, "exceeds the 25 MiB download limit"):
                ezflash_gba_thumbs.http_get("https://images.example/art.png")

        response.read.assert_called_once_with(9)

    def test_recursive_scan_finds_mixed_case_gba_extensions_deterministically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upper = root / "a" / "FIRST.GBA"
            lower = root / "b" / "second.gba"
            ignored = root / "c" / "not-a-rom.gb"
            for path in (upper, lower, ignored):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            self.assertEqual(list(iter_gba_files([root])), [upper, lower])

    def test_thumb_dimensions_reject_negative_width_and_nonpositive_height(self):
        parser = build_thumbs_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--width", "-1"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--height", "0"])
        self.assertEqual(parser.parse_args(["--width", "0"]).width, 0)

    def test_dimensions_reject_excessive_output_sizes(self):
        parser = build_thumbs_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--width", str(MAX_OUTPUT_DIMENSION + 1)])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--height", str(MAX_OUTPUT_DIMENSION + 1)])
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            validate_output_size(MAX_OUTPUT_DIMENSION + 1, 1)
        with self.assertRaisesRegex(ValueError, f"{MAX_OUTPUT_PIXELS:,} pixels"):
            validate_output_size(MAX_OUTPUT_DIMENSION, MAX_OUTPUT_DIMENSION)
        validate_output_size(120, 80)

    def test_bmp_writer_checks_size_before_allocating_pixel_data(self):
        image = Image.new("RGB", (MAX_OUTPUT_DIMENSION + 1, 1))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "cannot exceed"):
                write_ezflash_bmp(image, Path(temp) / "too-wide.bmp")
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_pack_converter_requires_positive_dimensions(self):
        parser = build_pack_converter_parser()
        for args in (("--width", "0"), ("--height", "-2")):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                parser.parse_args(list(args))

    def test_full_library_requires_positive_dimensions_and_nonnegative_limit(self):
        parser = build_full_library_parser()
        for args in (("--width", "0"), ("--height", "-2"), ("--limit", "-1")):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                parser.parse_args(list(args))
        self.assertEqual(parser.parse_args(["--limit", "0"]).limit, 0)


if __name__ == "__main__":
    unittest.main()
