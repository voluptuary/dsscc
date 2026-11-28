from __future__ import annotations

import argparse
import io
import json
import os
import re
import struct
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps
from json_cache import write_json_atomic
from rom_matching import strip_nointro_tags


LIBRETRO_API = (
    "https://api.github.com/repos/libretro-thumbnails/"
    "Nintendo_-_Game_Boy_Advance/git/trees/master?recursive=1"
)
LIBRETRO_RAW = (
    "https://raw.githubusercontent.com/libretro-thumbnails/"
    "Nintendo_-_Game_Boy_Advance/master/Named_Boxarts/{name}"
)

DEFAULT_WIDTH = 80
DEFAULT_HEIGHT = 80
TITLE_FILE_EXTENSIONS = {
    ".gba", ".agb", ".bin", ".mb", ".gb", ".gbc", ".nes", ".sms",
    ".gg", ".sg", ".pce", ".ngp", ".ngc", ".ngpc", ".ws", ".wsc",
    ".rom", ".sv", ".z80", ".col", ".arc", ".sc", ".a26",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp",
}
MAX_OUTPUT_DIMENSION = 4096
MAX_OUTPUT_PIXELS = 16_000_000
MAX_SOURCE_PIXELS = 16_000_000
GBA_TITLE_OFFSET = 0xA0
GBA_TITLE_LEN = 12
GBA_CODE_OFFSET = 0xAC
GBA_CODE_LEN = 4
MAX_HTTP_RESPONSE_BYTES = 25 * 1024 * 1024


def positive_dimension(value: str) -> int:
    """Parse a positive image dimension within the safe output bounds."""
    dimension = int(value)
    if dimension <= 0:
        raise argparse.ArgumentTypeError("dimensions must be greater than zero")
    if dimension > MAX_OUTPUT_DIMENSION:
        raise argparse.ArgumentTypeError(
            f"dimensions must be {MAX_OUTPUT_DIMENSION} pixels or smaller"
        )
    return dimension


def non_negative_dimension(value: str) -> int:
    """Parse a bounded dimension where zero retains the source aspect ratio."""
    dimension = int(value)
    if dimension < 0:
        raise argparse.ArgumentTypeError("dimensions must be zero or greater")
    if dimension > MAX_OUTPUT_DIMENSION:
        raise argparse.ArgumentTypeError(
            f"dimensions must be {MAX_OUTPUT_DIMENSION} pixels or smaller"
        )
    return dimension


def validate_output_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("Output dimensions must be greater than zero.")
    if width > MAX_OUTPUT_DIMENSION or height > MAX_OUTPUT_DIMENSION:
        raise ValueError(f"Output dimensions cannot exceed {MAX_OUTPUT_DIMENSION} pixels.")
    if width * height > MAX_OUTPUT_PIXELS:
        raise ValueError(
            f"Output images cannot exceed {MAX_OUTPUT_PIXELS:,} pixels."
        )


def non_negative_int(value: str) -> int:
    """Parse an optional count where zero means unlimited."""
    count = int(value)
    if count < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return count


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def title_filename(value: str | Path) -> str:
    """Strip a supported file extension without treating title periods as suffixes."""
    name = re.split(r"[\\/]", str(value))[-1]
    suffix = Path(name).suffix.casefold()
    if suffix in TITLE_FILE_EXTENSIONS:
        return name[:-len(suffix)]
    return name


@dataclass(frozen=True)
class RomInfo:
    path: Path
    title: str
    code: str


def clean_title(value: str) -> str:
    # Titles may legitimately contain periods (for example, "No. 1 - Game").
    # Path.stem treats the last period in any string as a file extension, which
    # silently erased everything after "No." on repeated normalization. Strip
    # only file extensions the app actually supports, and make this operation
    # safe to apply repeatedly to an already-cleaned title.
    value = title_filename(value)
    value = strip_nointro_tags(value, preserve_regions=False)
    value = re.sub(r"\b(Rev|Beta|Proto|Demo|Hack|Fixed|Trashman)\b.*", " ", value, flags=re.I)
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -_.")


def _title_match_text(value: str) -> str:
    value = clean_title(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        character for character in value if not unicodedata.combining(character)
    )
    value = (
        value.replace("&", "and")
        .replace("%", " percent ")
        .replace("!", " exclamation ")
    )
    return value


def normalize_for_match(value: str) -> str:
    value = _title_match_text(value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def tokens_for_match(value: str) -> set[str]:
    value = _title_match_text(value)
    return set(re.findall(r"[a-z0-9]+", value))


def region_tokens(value: str) -> set[str]:
    regions = {
        "usa",
        "europe",
        "japan",
        "australia",
        "france",
        "germany",
        "spain",
        "italy",
    }
    return set(re.findall(r"[a-z0-9]+", value.lower())) & regions


def http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ezflash-gba-thumbs/1.0",
            "Accept": "application/vnd.github+json,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
    if len(data) > MAX_HTTP_RESPONSE_BYTES:
        raise ValueError("The HTTP response exceeds the 25 MiB download limit.")
    return data


def load_libretro_index(cache_path: Path, refresh: bool = False) -> list[str]:
    if cache_path.exists() and not refresh:
        try:
            cached_names = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached_names, list) and len(cached_names) > 1000 and all(
                isinstance(name, str) and name.lower().endswith(".png") for name in cached_names
            ):
                return cached_names
        except (OSError, ValueError, TypeError):
            pass

    data = json.loads(http_get(LIBRETRO_API).decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
        raise ValueError("Libretro returned an invalid thumbnail index")
    names = sorted(
        Path(item["path"]).name
        for item in data.get("tree", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item["path"].startswith("Named_Boxarts/")
        and item["path"].lower().endswith(".png")
    )
    if len(names) <= 1000:
        raise LookupError("Libretro returned an incomplete GBA thumbnail index")
    write_json_atomic(cache_path, names)
    return names


def title_match_score(raw_query: str, candidate: str) -> float:
    query_tokens = tokens_for_match(raw_query)
    candidate_tokens = tokens_for_match(candidate)
    query_regions = region_tokens(raw_query)
    candidate_regions = region_tokens(candidate)
    overlap = query_tokens & candidate_tokens
    if not query_tokens or not candidate_tokens or not overlap:
        return 0.0

    score = (len(overlap) / len(query_tokens)) * 3 + (len(overlap) / len(candidate_tokens))
    if query_regions and query_regions & candidate_regions:
        score += 0.6
    elif query_regions and candidate_regions and not (query_regions & candidate_regions):
        score -= 0.2
    if normalize_for_match(raw_query) in normalize_for_match(candidate):
        score += 0.5
    if candidate_tokens <= query_tokens:
        score += 0.25
    return score


SEARCH_IGNORED_TITLE_TOKENS = {
    "the",
    "of",
    "a",
    "an",
    "and",
    "version",
    "edition",
}


def title_search_compatible(raw_query: str, candidate: str) -> bool:
    """Reject look-alike releases that only share a title prefix.

    Unlike the fuzzy scorer, this requires the same meaningful title tokens, or
    a candidate whose only extra words are filler such as "Version" or "Edition".
    It stops a regional/unlicensed variant like "Tetris (USA) (Tengen) (Unl)"
    from supplying artwork for plain "Tetris (USA)" and vice versa.
    """
    query_tokens = {
        token
        for token in tokens_for_match(raw_query)
        if token not in SEARCH_IGNORED_TITLE_TOKENS and len(token) > 1
    }
    candidate_tokens = {
        token
        for token in tokens_for_match(candidate)
        if token not in SEARCH_IGNORED_TITLE_TOKENS and len(token) > 1
    }
    if not query_tokens or not candidate_tokens:
        return False
    if query_tokens == candidate_tokens:
        return True

    normalized_query = normalize_for_match(raw_query)
    normalized_candidate = normalize_for_match(candidate)
    if normalized_query == normalized_candidate:
        return True

    if normalized_query and normalized_candidate.startswith(normalized_query):
        suffix = normalized_candidate[len(normalized_query):]
        suffix_tokens = set(re.findall(r"[a-z0-9]+", suffix.lower()))
        return bool(suffix_tokens) and suffix_tokens <= SEARCH_IGNORED_TITLE_TOKENS

    return False


def regions_conflict(raw_query: str, candidate: str) -> bool:
    query_regions = region_tokens(raw_query)
    candidate_regions = region_tokens(candidate)
    return bool(query_regions and candidate_regions and not (query_regions & candidate_regions))


def _choose_exact_candidate(raw_query: str, names: list[str]) -> str:
    """Prefer a matching-region filename when several normalize to one title."""
    query_regions = region_tokens(raw_query)

    def preference(name: str) -> int:
        candidate_regions = region_tokens(name)
        if query_regions and candidate_regions:
            return 0 if query_regions & candidate_regions else 1
        return 0

    return min(names, key=preference)


def find_boxart_name(rom: RomInfo, index: Iterable[str]) -> str | None:
    candidates = [(normalize_for_match(name), name) for name in index]

    for raw_query in (rom.path.name, rom.title):
        query = normalize_for_match(raw_query)
        if not query:
            continue
        exact = [name for normalized, name in candidates if normalized == query]
        if exact:
            return _choose_exact_candidate(raw_query, exact)

    best_score = 0.0
    best_name: str | None = None
    for raw_query in (rom.path.name, rom.title):
        if not tokens_for_match(raw_query):
            continue

        for _, name in candidates:
            if not title_search_compatible(raw_query, name):
                continue
            if regions_conflict(raw_query, name):
                continue
            score = title_match_score(raw_query, name)

            if score > best_score:
                best_score = score
                best_name = name

    if best_score >= 2.2:
        return best_name
    return None


def read_rom_info(path: Path) -> RomInfo:
    with path.open("rb") as rom:
        rom.seek(GBA_TITLE_OFFSET)
        title = rom.read(GBA_TITLE_LEN).decode("ascii", errors="ignore").strip("\0 ")
        rom.seek(GBA_CODE_OFFSET)
        code = rom.read(GBA_CODE_LEN).decode("ascii", errors="ignore").strip("\0 ")

    if not re.fullmatch(r"[A-Z0-9]{4}", code):
        raise ValueError(f"{path.name}: could not read a valid 4-character GBA game code")

    return RomInfo(path=path, title=title, code=code)


def output_path_for_code(output_root: Path, code: str) -> Path:
    return output_root / code[0] / code[1] / f"{code}.bmp"


def prepare_image(
    image_data: bytes,
    width: int | None,
    height: int,
    fit: str,
    centering: tuple[float, float],
) -> Image.Image:
    with Image.open(io.BytesIO(image_data)) as image:
        if image.width * image.height > MAX_SOURCE_PIXELS:
            raise ValueError(
                f"Source images cannot exceed {MAX_SOURCE_PIXELS:,} pixels."
            )
        if width is None:
            ratio = height / image.height
            scaled_width = max(1, round(image.width * ratio))
            validate_output_size(scaled_width, height)
            image = image.convert("RGB")
            return image.resize((scaled_width, height), Image.Resampling.LANCZOS)

        validate_output_size(width, height)
        image = image.convert("RGB")
        size = (width, height)
        if fit == "contain":
            return ImageOps.pad(image, size, method=Image.Resampling.LANCZOS, color=(0, 0, 0))
        return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=centering)


TRANSPARENT_THUMBNAIL_MARKER = b"DST1"


def write_ezflash_bmp(image: Image.Image, path: Path, *, mark_transparency: bool | None = None) -> None:
    """Write an Omega-style top-down 16-bit BMP with GBA BGR555 pixel words.

    If the image has transparent pixels, mark it with ``DST1`` in the BMP's
    reserved header bytes so the compatible DS Style kernel knows that RGB555
    zero is an intentional transparency key. Opaque legacy/GBA artwork remains
    unmarked, preserving its existing black pixels and rendering behavior.
    ``mark_transparency`` can be set explicitly by callers that need to force
    or suppress the marker; by default it follows the image's alpha channel.
    """
    width, height = image.size
    validate_output_size(width, height)
    if mark_transparency is None:
        mark_transparency = False
        if "A" in image.getbands():
            mark_transparency = image.getchannel("A").getextrema()[0] < 128
    row_bytes = width * 2
    padding = (4 - row_bytes % 4) % 4
    pixel_data_size = (row_bytes + padding) * height
    file_size = 54 + pixel_data_size

    header = bytearray()
    header.extend(b"BM")
    header.extend(struct.pack("<IHHI", file_size, 0, 0, 54))
    if mark_transparency:
        # The compatible kernel recognizes only explicitly tagged artwork.
        # Offsets 6..9 are the two reserved words in a standard BMP file header.
        header[6:10] = TRANSPARENT_THUMBNAIL_MARKER
    header.extend(
        struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            -height,
            1,
            16,
            0,
            pixel_data_size,
            2834,
            2834,
            0,
            0,
        )
    )

    pixels = bytearray()
    for y in range(height):
        for pixel in (image.getpixel((x, y)) for x in range(width)):
            if len(pixel) >= 4 and pixel[3] < 128:
                # The DS Style kernel uses RGB555 word 0 (pure black) as the
                # color-key transparent pixel in generated thumbnail BMPs.
                gba_bgr555 = 0x0000
            else:
                r, g, b = pixel[:3]
                red5, green5, blue5 = r >> 3, g >> 3, b >> 3
                # Because RGB555 discards the low three bits, e.g. #010101
                # would also encode as the transparent zero word. Lift those
                # visible near-black pixels to RGB555 (1,1,1), i.e. #080808.
                if red5 == 0 and green5 == 0 and blue5 == 0:
                    red5 = green5 = blue5 = 1
                gba_bgr555 = (blue5 << 10) | (green5 << 5) | red5
            pixels.extend(struct.pack("<H", gba_bgr555))
        if padding:
            pixels.extend(b"\0" * padding)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + bytes(pixels))


def iter_gba_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_dir():
            # Keep the walk deterministic while yielding ROMs incrementally;
            # collecting and sorting a library-wide Path list scales poorly.
            for current, directories, filenames in os.walk(path):
                directories.sort(key=str.casefold)
                filenames.sort(key=str.casefold)
                current_path = Path(current)
                for filename in filenames:
                    candidate = current_path / filename
                    if candidate.suffix.casefold() == ".gba" and candidate.is_file():
                        yield candidate
        elif path.suffix.lower() == ".gba":
            yield path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create EZ Flash Omega DE GBA thumbnail BMPs from ROM headers and online box art."
    )
    parser.add_argument(
        "roms",
        nargs="*",
        type=Path,
        help="GBA ROM file(s) or folder(s) to scan. If omitted, scans the folder containing this tool.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output IMGS folder. If omitted, creates IMGS beside this tool.",
    )
    parser.add_argument(
        "--width",
        type=non_negative_dimension,
        default=DEFAULT_WIDTH,
        help="Thumbnail width. Use 0 to preserve box-art aspect ratio instead.",
    )
    parser.add_argument("--height", type=positive_dimension, default=DEFAULT_HEIGHT, help="Thumbnail height")
    parser.add_argument(
        "--fit",
        choices=("contain", "cover"),
        default="cover",
        help="Pad the full art or crop to fill. Crop keeps the left edge and centers vertically.",
    )
    parser.add_argument("--refresh-index", action="store_true", help="Refresh the online box-art index cache")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing BMPs")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(raw_argv)
    if args.width == 0:
        args.width = None
    if args.width is not None:
        try:
            validate_output_size(args.width, args.height)
        except ValueError as exc:
            parser.error(str(exc))
    base_dir = app_dir()
    scan_paths = args.roms or [base_dir]
    output_root = args.output or (base_dir / "IMGS")
    cache_path = base_dir / "DS Style Thumbnail Scraper Cache" / "libretro_gba_boxarts.json"

    rom_paths = iter(iter_gba_files(scan_paths))
    first_rom_path = next(rom_paths, None)
    if first_rom_path is None:
        print("No .gba files found.", file=sys.stderr)
        return 1

    try:
        index = load_libretro_index(cache_path, refresh=args.refresh_index)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, LookupError) as exc:
        print(f"Could not load online box-art index: {exc}", file=sys.stderr)
        return 2

    made = 0
    missed = 0
    for rom_path in chain((first_rom_path,), rom_paths):
        try:
            rom = read_rom_info(rom_path)
        except (OSError, ValueError) as exc:
            print(f"skip: {exc}")
            missed += 1
            continue

        out_path = output_path_for_code(output_root, rom.code)
        if out_path.exists() and not args.overwrite:
            print(f"exists: {rom.path.name} -> {out_path}")
            continue

        art_name = find_boxart_name(rom, index)
        if not art_name:
            print(f"miss: {rom.path.name} ({rom.code})")
            missed += 1
            continue

        try:
            url_name = urllib.parse.quote(art_name)
            image_data = http_get(LIBRETRO_RAW.format(name=url_name))
            image = prepare_image(image_data, args.width, args.height, args.fit, (0.0, 0.5))
            write_ezflash_bmp(image, out_path)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"fail: {rom.path.name} ({rom.code}): {exc}")
            missed += 1
            continue

        print(f"made: {rom.path.name} ({rom.code}) <- {art_name}")
        made += 1

    print(f"\nDone. Created {made} thumbnail(s); {missed} missing or failed.")
    return 0 if missed == 0 else 3


if __name__ == "__main__":
    used_drop_in_mode = len(sys.argv) == 1
    exit_code = main()
    if used_drop_in_mode and getattr(sys, "frozen", False):
        try:
            input("\nPress Enter to close.")
        except EOFError:
            pass
    raise SystemExit(exit_code)
