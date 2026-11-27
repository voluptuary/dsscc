# DS Style Card Companion — Agent Quickstart

## Repository purpose

This repository contains DS Style Card Companion, a Windows desktop app for preparing artwork for DS Style kernels on EZ-FLASH OMEGA and OMEGA Definitive Edition. It builds GBA thumbnail packs, finds artwork for other supported systems, scans SD card ROM trees for custom art, and converts Jagoomba Color ESV and GB/GBC SAV files. The app does not download or modify ROMs. See `DS Style User Guide.pdf` for user-facing workflows and `CHANGELOG.md` for release history.

## Start here

- Main application: `DS Style Thumbnail Scraper.py` (the filename is historical).
- Windows build recipe: `DS Style Thumbnail Scraper.spec` and `build.ps1`.
- Requirements: `requirements.txt` (PyInstaller is installed by `build.ps1`).
- Tests: `tests/`; run `python -m unittest discover -s tests -v` when the user asks to run tests or verify a change.
- Release packaging: `.github/workflows/release.yml`. Pushing a `v*` tag builds the Windows executable on `windows-latest`, packages it with the source archive, and publishes the matching `CHANGELOG.md` section.
- Latest published release: https://github.com/voluptuary/dsscc/releases/latest

## Product and implementation rules

- Keep artwork matching scoped to the selected console. Local artwork packs are read-only; never rename, delete, or write into a user's source pack.
- Keep output paths and ROM filenames stable. Mirrored `IMGS`/`IMGS2` output preserves the ROM directory tree; legacy flat `CUSTOM` output remains available for compatibility.
- Preserve the app's cache-first and incremental scan behavior, image validation, and explicit provider fallback controls.
- Treat save conversion as data-sensitive: retain the app's confirmation and avoid overwriting existing saves or archives without explicit user intent.
- Keep UI work responsive for long scans/builds by following the existing worker/progress patterns.
- Preserve the exact product branding “DS Style Merkin's Mix” in the upper-right header subtitle.
- Keep user documentation and `CHANGELOG.md` aligned with behavior changes. Release notes use a `## vX.Y.Z - concise summary` heading followed by short, past-tense bullets; use the exact section for release notes.
- Build release executables on Windows using `build.ps1` or the Windows GitHub Actions workflow. A Linux PyInstaller build is not a Windows release artifact.
- Do not publish, push tags, or replace release assets unless the user explicitly asks. Inspect `git status` and existing tags/releases before release work.

## Quickstart for repository tasks

1. Check `git status`, recent history, and the relevant source/tests before editing.
2. Make the smallest change that addresses the requested behavior and preserve existing compatibility.
3. Add or update focused regression coverage for behavior changes. Run tests when the user asks for test or verification results.
4. For release work, check the tag, workflow result, release notes, and downloadable assets. Confirm the app archive contains the Windows `.exe`; never substitute a Linux executable.
5. Summarize changed files, verification performed, and any remaining limitation clearly.
