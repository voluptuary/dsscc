# Contributing

Thank you for helping improve DS Style Card Companion.

Repository orientation and implementation rules are in [`AGENTS.md`](AGENTS.md).

## Before Submitting Changes

- Keep generated artwork compatible with the GBA BGR555 thumbnail format used by DS Style.
- Do not commit generated executables, caches, output packs, or personal settings.
- Test both `120 x 80` and `80 x 80` output where relevant.
- Keep the application usable without provider accounts when using Libretro or a local artwork pack.
- Keep local artwork packs read-only and preserve ROM names and output folder layouts.

## Running the Tests

Run the regression suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

## Reporting Bugs

Include:

- The scraper version
- Artwork source and thumbnail size
- Game or folder name involved
- Steps to reproduce the issue
- Any displayed error message

## Pull Requests

Describe what changed, why it was needed, and how it was tested.
