# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.0.3] - 2024-05-30

### Fixed

- Handling of datasets exceeding EPSG:3857 limits.

### Added

- Introduced `argparse`-based CLI for generating, writing, and serving tiles.
- `serve` method for dynamic tile serving over HTTP.
- Option for threaded tile image writing for significant speed improvement with larger quantities of output tiles.

### Changed

- Faster tile image writing with `rasterio.MemoryFile`.
- Boolean parameters changed to keyword-only per FBT001 and FBT002.
- Package manager migrated from [`Poetry`](https://github.com/python-poetry/poetry) to [`uv`](https://github.com/astral-sh/uv).
- Updated Python from 3.10 to 3.13 and `rasterio` from 1.3.9 to 1.4.3.
- Added pre-commit hooks for `mypy` and `ruff`.

## [0.0.2] - 2024-05-30

- Fix of bug affecting tiling of images entirely within the Eastern Hemisphere.

## [0.0.1] - 2024-02-02

- RasterioXYZ introduced.