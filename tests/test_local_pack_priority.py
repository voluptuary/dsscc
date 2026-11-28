"""Regression tests for local-pack-first lookups and read-only artwork sources."""
import importlib.util
import io
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from ezflash_gba_thumbs import write_ezflash_bmp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "DS Style Thumbnail Scraper.py"
SPEC = importlib.util.spec_from_file_location("thumbnail_scraper_local_pack_priority_test", APP_PATH)
APP_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = APP_MODULE
SPEC.loader.exec_module(APP_MODULE)


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def png_bytes(color):
    stream = io.BytesIO()
    Image.new("RGB", (24, 32), color).save(stream, format="PNG")
    return stream.getvalue()


class LocalPackPriorityTests(unittest.TestCase):
    def test_local_pack_matching_preserves_unknown_bracketed_title_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            wanted = root / "Game [Lost Levels].png"
            other = root / "Game [Other Story].png"
            wanted.write_bytes(png_bytes((10, 200, 30)))
            other.write_bytes(png_bytes((200, 10, 30)))
            providers = APP_MODULE.Providers(
                SimpleNamespace(
                    local_pack_var=Value(str(root)),
                    region_allowed=lambda _title: True,
                    region_priority=lambda _title: 0,
                )
            )

            results = providers.search_local_pack_many(
                "Game [Lost Levels]", max_results=1, system="Game Boy"
            )

            self.assertEqual(results[0].image_data, wanted.read_bytes())

    def test_local_pack_rejects_oversized_image_without_unbounded_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            oversized = root / "Tetris.png"
            with oversized.open("wb") as stream:
                stream.truncate(APP_MODULE.MAX_REMOTE_IMAGE_BYTES + 1)
            providers = APP_MODULE.Providers(
                SimpleNamespace(
                    local_pack_var=Value(str(root)),
                    region_allowed=lambda _title: True,
                    region_priority=lambda _title: 0,
                )
            )

            with patch.object(Path, "read_bytes", side_effect=AssertionError("Unbounded read used")):
                with self.assertRaisesRegex(LookupError, "No local art match"):
                    providers.search_local_pack_many("Tetris", max_results=1, system="Game Boy")

    def test_return_keeps_selected_scan_game_attached_to_manual_search(self):
        game = {"title": "Crush Roller.ngc", "system": "Neo Geo Pocket", "path": "sd/Crush Roller.ngc"}
        app = SimpleNamespace(active_sd_scan_game=game)

        APP_MODULE.ThumbnailScraperApp.clear_active_sd_scan_game(
            app, SimpleNamespace(keysym="Return")
        )
        self.assertIs(app.active_sd_scan_game, game)

        APP_MODULE.ThumbnailScraperApp.clear_active_sd_scan_game(
            app, SimpleNamespace(keysym="a")
        )
        self.assertIsNone(app.active_sd_scan_game)

    def test_parent_variant_named_folders_do_not_penalize_retail_art(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            retail = root / "GBA" / "Demos" / "Tetris.png"
            demo = root / "GBA" / "Box Art" / "Tetris (Demo).png"
            retail.parent.mkdir(parents=True)
            demo.parent.mkdir(parents=True)
            retail.write_bytes(png_bytes((10, 200, 10)))
            demo.write_bytes(png_bytes((200, 10, 10)))
            app = SimpleNamespace(
                local_pack_var=Value(str(root)), region_allowed=lambda _title: True,
                region_priority=lambda _title: 0,
            )
            results = APP_MODULE.Providers(app).search_local_pack_many(
                "Tetris", max_results=2, system="Game Boy Advance"
            )
            self.assertTrue(results)
            self.assertEqual(results[0].image_data, retail.read_bytes())

    def test_local_pack_scopes_to_console_folder_through_arbitrary_nesting_and_reads_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "large media collection"
            gba = root / "GBA" / "Box Art" / "USA" / "Nested" / "Tetris (USA).png"
            nes = root / "Nintendo Entertainment System" / "Screenshots" / "Tetris (USA).png"
            gba.parent.mkdir(parents=True)
            nes.parent.mkdir(parents=True)
            gba_data = png_bytes((15, 200, 30))
            nes_data = png_bytes((220, 20, 20))
            gba.write_bytes(gba_data)
            nes.write_bytes(nes_data)
            original_files = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            app = SimpleNamespace(
                local_pack_var=Value(str(root)),
                local_pack_priority_var=Value(True),
                region_allowed=lambda _title: True,
                region_priority=lambda _title: 0,
            )
            providers = APP_MODULE.Providers(app)

            result = providers.search_local_pack_many("Tetris (USA)", max_results=1, system="Game Boy Advance")[0]

            self.assertEqual(result.provider, "Local Pack")
            self.assertIn("GBA", result.label)
            self.assertEqual(result.image_data, gba_data)
            self.assertNotIn("Nintendo Entertainment System", result.label)
            self.assertEqual({path: path.read_bytes() for path in root.rglob("*") if path.is_file()}, original_files)

    def test_release_named_folders_disambiguate_identical_local_image_filenames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            tengen = root / "Nintendo Entertainment System" / "Tetris (USA) (Tengen) (Unl)" / "Tetris.png"
            retail = root / "Nintendo Entertainment System" / "Tetris (USA)" / "Tetris.png"
            tengen.parent.mkdir(parents=True)
            retail.parent.mkdir(parents=True)
            tengen_data = png_bytes((210, 20, 20))
            retail_data = png_bytes((20, 180, 40))
            tengen.write_bytes(tengen_data)
            retail.write_bytes(retail_data)
            app = SimpleNamespace(
                local_pack_var=Value(str(root)),
                region_allowed=lambda _title: True,
                region_priority=lambda _title: 0,
            )
            providers = APP_MODULE.Providers(app)

            tengen_result = providers.search_local_pack_many(
                "Tetris (USA) (Tengen) (Unl)",
                max_results=1,
                system="Nintendo Entertainment System",
                respect_regions=False,
            )[0]
            retail_result = providers.search_local_pack_many(
                "Tetris (USA)",
                max_results=1,
                system="Nintendo Entertainment System",
                respect_regions=False,
            )[0]

            self.assertEqual(tengen_result.image_data, tengen_data)
            self.assertEqual(retail_result.image_data, retail_data)

    def test_unlicensed_tengen_local_art_does_not_fall_through_to_plain_tetris(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            variant = root / "Tetris (USA) (Tengen) (Unl).png"
            variant.write_bytes(png_bytes((210, 20, 20)))
            app = SimpleNamespace(
                local_pack_var=Value(str(root)),
                region_allowed=lambda _title: True,
                region_priority=lambda _title: 0,
            )

            with self.assertRaisesRegex(LookupError, "No local art match"):
                APP_MODULE.Providers(app).search_local_pack_many(
                    "Tetris (USA)",
                    max_results=1,
                    system="Nintendo Entertainment System",
                    respect_regions=False,
                )

    def test_status_variant_local_art_does_not_fall_through_to_plain_title(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            beta = root / "Bubble Bobble (USA) (Beta 2).png"
            beta.write_bytes(png_bytes((210, 20, 20)))
            app = SimpleNamespace(
                local_pack_var=Value(str(root)),
                region_allowed=lambda _title: True,
                region_priority=lambda _title: 0,
            )

            with self.assertRaisesRegex(LookupError, "No local art match"):
                APP_MODULE.Providers(app).search_local_pack_many(
                    "Bubble Bobble (USA)",
                    max_results=1,
                    system="Nintendo Entertainment System",
                    respect_regions=False,
                )

    def test_exact_local_variant_matching_is_not_title_specific(self):
        cases = (
            (
                "Bubble Bobble (USA) (Beta 2)",
                "Bubble Bobble (USA)",
                (210, 20, 20),
                (20, 180, 40),
            ),
            (
                "Pac-Man (USA) (Atari)",
                "Pac-Man (USA)",
                (20, 40, 210),
                (210, 180, 20),
            ),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            expected = {}
            for variant, retail, variant_color, retail_color in cases:
                variant_image = root / f"{variant}.png"
                retail_image = root / f"{retail}.png"
                expected[variant] = png_bytes(variant_color)
                expected[retail] = png_bytes(retail_color)
                variant_image.write_bytes(expected[variant])
                retail_image.write_bytes(expected[retail])
            app = SimpleNamespace(
                local_pack_var=Value(str(root)),
                region_allowed=lambda _title: True,
                region_priority=lambda _title: 0,
            )
            providers = APP_MODULE.Providers(app)

            for variant, retail, _variant_color, _retail_color in cases:
                with self.subTest(variant=variant):
                    self.assertEqual(
                        providers.search_local_pack_many(
                            variant, 1, "Nintendo Entertainment System", respect_regions=False
                        )[0].image_data,
                        expected[variant],
                    )
                    self.assertEqual(
                        providers.search_local_pack_many(
                            retail, 1, "Nintendo Entertainment System", respect_regions=False
                        )[0].image_data,
                        expected[retail],
                    )

    def test_local_pack_sd_lookup_prefers_matching_region_over_alphabetical_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            europe = root / "Nintendo Entertainment System" / "Europe" / "Tetris.png"
            usa = root / "Nintendo Entertainment System" / "USA" / "Tetris.png"
            europe.parent.mkdir(parents=True)
            usa.parent.mkdir(parents=True)
            europe_data = png_bytes((210, 20, 20))
            usa_data = png_bytes((20, 180, 40))
            europe.write_bytes(europe_data)
            usa.write_bytes(usa_data)
            app = SimpleNamespace(
                local_pack_var=Value(str(root)),
                region_allowed=lambda _title: True,
                region_priority=lambda _title: 0,
            )

            result = APP_MODULE.Providers(app).search_local_pack_many(
                "Tetris (USA)",
                max_results=1,
                system="Nintendo Entertainment System",
                respect_regions=False,
            )[0]

            self.assertEqual(result.image_data, usa_data)

    def test_priority_returns_local_art_before_selected_online_provider(self):
        app = SimpleNamespace(local_pack_priority_var=Value(True), local_pack_var=Value("unused"))
        providers = APP_MODULE.Providers(app)
        local = APP_MODULE.ProviderResult("Local Pack", "GBA/Tetris.png", png_bytes((10, 120, 10)), "Game Boy Advance")
        providers.search_local_pack_many = Mock(return_value=[local])
        providers.search_libretro_many = Mock(return_value=[])

        results = providers.search_many("Libretro", "Tetris", max_results=1, system="Game Boy Advance")

        self.assertEqual(results, [local])
        providers.search_local_pack_many.assert_called_once_with("Tetris", 1, system="Game Boy Advance")
        providers.search_libretro_many.assert_not_called()

    def test_priority_disabled_keeps_selected_provider_behavior(self):
        app = SimpleNamespace(local_pack_priority_var=Value(False), local_pack_var=Value("unused"))
        providers = APP_MODULE.Providers(app)
        online = APP_MODULE.ProviderResult("Libretro", "Tetris.png", png_bytes((10, 20, 220)), "Game Boy Advance")
        providers.search_libretro_many = Mock(return_value=[online])
        providers.search_local_pack_many = Mock(return_value=[])

        results = providers.search_many("Libretro", "Tetris", max_results=1, system="Game Boy Advance")

        self.assertEqual(results, [online])
        providers.search_libretro_many.assert_called_once()
        providers.search_local_pack_many.assert_not_called()

    def test_sd_scan_prefers_local_pack_over_existing_thumbnail_and_stale_rom_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            sd_root = temp_root / "sd"
            rom = sd_root / "Game Boy" / "T" / "Tetris (USA) (Rev 1) [!].gb"
            rom.parent.mkdir(parents=True)
            rom.write_bytes(b"sample ROM bytes")
            relative = "Game Boy/T/Tetris (USA) (Rev 1) [!].gb"

            pack_root = temp_root / "local media"
            local_source = pack_root / "Game Boy" / "Art" / "Deep" / "Tetris (USA).png"
            local_source.parent.mkdir(parents=True)
            fresh = png_bytes((25, 180, 40))
            local_source.write_bytes(fresh)
            source_before = local_source.read_bytes()

            cache_identity = f"game boy\0box art\0{relative.casefold()}"
            cache_digest = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()[:32]
            stale_cache = temp_root / "app" / "DS Style Thumbnail Scraper Cache" / "SD scan ROM artwork" / f"{cache_digest}.png"
            stale_cache.parent.mkdir(parents=True)
            stale_cache.write_bytes(png_bytes((200, 10, 10)))
            old_output = sd_root / "SYSTEM" / "IMGS2" / "Game Boy" / "T"
            old_output.mkdir(parents=True)
            write_ezflash_bmp(
                Image.new("RGB", (80, 80), (200, 10, 10)),
                old_output / "Tetris (USA) (Rev 1) [!].bmp",
            )

            class ScanProviders:
                def __init__(self):
                    self.online_calls = []
                    self.hash_calls = []

                def search_local_pack_many(self, query, max_results=1, system=APP_MODULE.DEFAULT_SYSTEM):
                    return [APP_MODULE.ProviderResult("Local Pack", str(local_source.relative_to(pack_root)), local_source.read_bytes(), system)]

                def find_libretro_art_name(self, *args):
                    self.online_calls.append("Libretro")
                    return None

                def search_fallback_many(self, *args, **kwargs):
                    self.online_calls.append("Online fallback")
                    raise LookupError("unexpected online lookup")

                def search_hash_fallback(self, *args, **kwargs):
                    self.hash_calls.append(args)
                    raise LookupError("unexpected hash lookup")

            app = object.__new__(APP_MODULE.ThumbnailScraperApp)
            app.base_dir = temp_root / "app"
            app.custom_roms = []
            app.providers = ScanProviders()
            app.local_pack_priority_var = Value(True)
            app.local_pack_var = Value(str(pack_root))
            app.after = lambda _delay, callback: callback()
            app.status_var = Value("Ready")
            app.ask_sd_download_fallback_skip = lambda *_args: "skip"

            result = APP_MODULE.ThumbnailScraperApp._scan_sd_worker(
                app, sd_root, "Box Art", ["80x80"], False, use_hash_matching=True
            )

            self.assertEqual(result["matched_files"], 1)
            self.assertEqual(len(result["additions"]), 1)
            refreshed_cache = Path(result["additions"][0].image_path)
            with Image.open(refreshed_cache) as image:
                self.assertEqual(image.convert("RGB").getpixel((0, 0)), (25, 180, 40))
            self.assertEqual(local_source.read_bytes(), source_before)
            self.assertEqual(app.providers.online_calls, [])
            self.assertEqual(app.providers.hash_calls, [])

    def test_sd_scan_uses_exact_local_filenames_even_when_fuzzy_priority_is_off(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            sd_root = base / "sd"
            rom_folder = sd_root / "Nintendo" / "T"
            rom_folder.mkdir(parents=True)
            tengen_rom = rom_folder / "Tetris (USA) (Tengen) (Unl).nes"
            retail_rom = rom_folder / "Tetris (USA).nes"
            tengen_rom.touch()
            retail_rom.touch()

            local_pack = base / "Media" / "Nintendo"
            local_pack.mkdir(parents=True)
            tengen_art = local_pack / "Tetris (USA) (Tengen) (Unl).png"
            retail_art = local_pack / "Tetris (USA).png"
            tengen_data = png_bytes((210, 20, 20))
            retail_data = png_bytes((20, 180, 40))
            tengen_art.write_bytes(tengen_data)
            retail_art.write_bytes(retail_data)

            app = object.__new__(APP_MODULE.ThumbnailScraperApp)
            app.base_dir = base / "app"
            app.custom_roms = []
            app.local_pack_priority_var = Value(False)
            app.local_pack_var = Value(str(local_pack))
            app.region_allowed = lambda _title: True
            app.region_priority = lambda _title: 0
            app.after = lambda _delay, callback: callback()
            app.status_var = Value("Ready")
            app.providers = APP_MODULE.Providers(app)
            app.providers.find_libretro_art_name = Mock(side_effect=AssertionError("Online lookup should not run"))
            app.providers.search_fallback_many = Mock(side_effect=AssertionError("Fallback should not run"))
            app.providers.search_hash_fallback = Mock(side_effect=AssertionError("Hash lookup should not run"))
            stale_cache = APP_MODULE.ThumbnailScraperApp.sd_scan_rom_cache_path(
                app,
                "Named_Boxarts",
                "Nintendo Entertainment System",
                "Nintendo/T/Tetris (USA).nes",
            )
            stale_cache.parent.mkdir(parents=True)
            stale_cache.write_bytes(png_bytes((200, 10, 10)))
            stale_output = (
                sd_root
                / "SYSTEM"
                / "IMGS2"
                / "Nintendo"
                / "T"
                / retail_rom.with_suffix(".bmp").name
            )
            write_ezflash_bmp(Image.new("RGB", (80, 80), (200, 10, 10)), stale_output)

            result = APP_MODULE.ThumbnailScraperApp._scan_sd_worker(
                app,
                sd_root,
                "Box Art",
                ["80x80"],
                True,
                use_hash_matching=True,
                auto_fallback=True,
            )

            art_by_rom = {
                Path(item.rom_path).name: Path(item.image_path).read_bytes()
                for item in result["additions"]
            }
            self.assertEqual(art_by_rom[tengen_rom.name], tengen_data)
            self.assertEqual(art_by_rom[retail_rom.name], retail_data)
            app.providers.find_libretro_art_name.assert_not_called()
            app.providers.search_fallback_many.assert_not_called()
            app.providers.search_hash_fallback.assert_not_called()

    def test_sd_scan_keeps_period_numbered_arcade_classics_titles_distinct(self):
        titles = (
            "Arcade Classic No. 1 - Asteroids & Missile Command (USA, Europe) (SGB Enhanced)",
            "Arcade Classic No. 2 - Centipede & Millipede (USA, Europe) (SGB Enhanced)",
            "Arcade Classic No. 3 - Galaga & Galaxian (USA) (SGB Enhanced)",
            "Arcade Classic No. 4 - Defender & Joust (USA, Europe) (SGB Enhanced)",
        )
        normalized_titles = {APP_MODULE.normalize_for_match(title) for title in titles}
        self.assertEqual(len(normalized_titles), len(titles))
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            sd_root = base / "sd"
            rom_folder = sd_root / "Nintendo" / "T"
            rom_folder.mkdir(parents=True)
            roms = {f"{title}.gbc": (index * 40, 255 - index * 30, index * 20)
                    for index, title in enumerate(titles, start=1)}
            for filename in roms:
                (rom_folder / filename).touch()

            local_pack = base / "Media" / "Nintendo"
            local_pack.mkdir(parents=True)
            art_data = {}
            for filename, color in roms.items():
                art = local_pack / f"{Path(filename).stem}.png"
                art_data[filename] = png_bytes(color)
                art.write_bytes(art_data[filename])

            app = object.__new__(APP_MODULE.ThumbnailScraperApp)
            app.base_dir = base / "app"
            app.custom_roms = []
            app.local_pack_priority_var = Value(False)
            app.local_pack_var = Value(str(local_pack))
            app.region_allowed = lambda _title: True
            app.region_priority = lambda _title: 0
            app.after = lambda _delay, callback: callback()
            app.status_var = Value("Ready")
            app.providers = APP_MODULE.Providers(app)
            app.providers.find_libretro_art_name = Mock(side_effect=AssertionError("Online lookup should not run"))

            result = APP_MODULE.ThumbnailScraperApp._scan_sd_worker(
                app, sd_root, "Box Art", ["80x80"], False
            )

            selected_art = {
                Path(item.rom_path).name: Path(item.image_path).read_bytes()
                for item in result["additions"]
            }
            self.assertEqual(selected_art, art_data)
            app.providers.find_libretro_art_name.assert_not_called()

    def test_overwrite_cache_refreshes_stale_copy_without_touching_source_file(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "Local Pack" / "GBA" / "Box Art" / "Tetris.png"
            source.parent.mkdir(parents=True)
            source.write_bytes(png_bytes((25, 180, 40)))
            before = source.read_bytes()
            cache = Path(temp) / "scraper cache" / "tetris.png"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(png_bytes((200, 10, 10)))
            app = object.__new__(APP_MODULE.ThumbnailScraperApp)

            APP_MODULE.ThumbnailScraperApp.cache_sd_scan_image(app, cache, before, overwrite=True)

            self.assertEqual(source.read_bytes(), before)
            with Image.open(cache) as image:
                self.assertEqual(image.convert("RGB").getpixel((0, 0)), (25, 180, 40))


if __name__ == "__main__":
    unittest.main()
