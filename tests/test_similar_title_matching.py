"""Regression tests for Atari 2600 support and look-alike artwork matching."""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "DS Style Thumbnail Scraper.py"
SPEC = importlib.util.spec_from_file_location("thumbnail_scraper_similar_title_test", APP_PATH)
APP_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = APP_MODULE
SPEC.loader.exec_module(APP_MODULE)

NES = "Nintendo Entertainment System"
FOLDER = "Named_Boxarts"


def providers_for(index):
    providers = APP_MODULE.Providers(SimpleNamespace())
    providers.get_libretro_index = lambda _system, _folder: list(index)
    return providers


class Atari2600SupportTests(unittest.TestCase):
    def test_a26_extension_resolves_to_atari_2600(self):
        self.assertEqual(APP_MODULE.system_for_path(Path("Combat.a26")), "Atari 2600")

    def test_atari_2600_uses_the_libretro_2600_thumbnail_repository(self):
        self.assertEqual(
            APP_MODULE.LIBRETRO_SYSTEMS["Atari 2600"]["repo"], "Atari_-_2600"
        )

    def test_atari_2600_is_a_supported_local_pack_console(self):
        self.assertNotIn("Atari 2600", APP_MODULE.LOCAL_PACK_OTHER_CONSOLE_FOLDERS)
        owners, _broad = APP_MODULE.local_pack_folder_owners("Atari 2600")
        self.assertIn("Atari 2600", owners)


class SimilarTitleMatchingTests(unittest.TestCase):
    def test_region_variant_does_not_supply_art_for_the_plain_title(self):
        providers = providers_for(["Tetris (USA) (Tengen) (Unl).png"])
        selected = providers.find_libretro_art_name("Tetris (USA)", NES, FOLDER)
        self.assertIsNone(selected)

    def test_plain_title_does_not_supply_art_for_a_different_variant(self):
        providers = providers_for(["Tetris (USA).png"])
        selected = providers.find_libretro_art_name(
            "Tetris (USA) (Tengen) (Unl)", NES, FOLDER
        )
        self.assertIsNone(selected)

    def test_similar_titles_each_keep_their_own_artwork(self):
        providers = providers_for([
            "Tetris (USA).png",
            "Tetris (USA) (Tengen) (Unl).png",
        ])
        self.assertEqual(
            providers.find_libretro_art_name(
                "Tetris (USA) (Tengen) (Unl)", NES, FOLDER
            ),
            "Tetris (USA) (Tengen) (Unl).png",
        )
        self.assertEqual(
            providers.find_libretro_art_name("Tetris (USA)", NES, FOLDER),
            "Tetris (USA).png",
        )

    def test_region_is_not_ignored_when_picking_an_exact_title_match(self):
        providers = providers_for(["Tetris (Europe).png", "Tetris (USA).png"])
        selected = providers.find_libretro_art_name("Tetris (USA) (Rev 1)", NES, FOLDER)
        self.assertEqual(selected, "Tetris (USA).png")

    def test_naming_differences_still_match(self):
        providers = providers_for(["Pokemon - FireRed Version (USA).png"])
        selected = providers.find_libretro_art_name("Pokemon FireRed (USA)", NES, FOLDER)
        self.assertEqual(selected, "Pokemon - FireRed Version (USA).png")

    def test_period_numbered_arcade_classics_do_not_collapse_to_first_match(self):
        titles = (
            "Arcade Classic No. 1 - Asteroids & Missile Command (USA, Europe) (SGB Enhanced)",
            "Arcade Classic No. 2 - Centipede & Millipede (USA, Europe) (SGB Enhanced)",
            "Arcade Classic No. 3 - Galaga & Galaxian (USA) (SGB Enhanced)",
            "Arcade Classic No. 4 - Defender & Joust (USA, Europe) (SGB Enhanced)",
        )
        providers = providers_for([f"{title}.png" for title in reversed(titles)])

        self.assertEqual(
            len({APP_MODULE.normalize_for_match(title) for title in titles}),
            len(titles),
        )
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(
                    providers.find_libretro_art_name(title, NES, FOLDER),
                    f"{title}.png",
                )


if __name__ == "__main__":
    unittest.main()
