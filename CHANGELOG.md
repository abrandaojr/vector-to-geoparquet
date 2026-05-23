# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.4.0] - 2026-05-22

### Changed

- **Output CRS is EPSG:5880** (SIRGAS 2000 / Brazil Polyconic, metres) for
  all stored geometry, tile IDs, Hilbert ordering, and bbox values.
  The previous v1.3.0 stored geometry in EPSG:4674 (geographic degrees);
  that was inconsistent with the tile and Hilbert computations which always
  ran in EPSG:5880. The library now works entirely in a single metric CRS
  throughout the pipeline.
- **Package refactored into four submodules** for testability and readability.
  The single-file `vector_to_geoparquet.py` is replaced by a proper package:
  - `_constants.py` -- CRS strings, FAMILY dict, `__version__`
  - `_geometry.py` -- `detect_family`, `normalise_crs`, `repair`,
    `enforce_homogeneity` (each independently testable)
  - `_hilbert.py` -- `hilbert()` with Shapely 2.0 vectorised API and
    pure-Python fallback
  - `_core.py` -- `convert_to_geoparquet()` and `_cli()`
  - `__init__.py` -- public API surface

### Added

- `.gitattributes` with `* text=auto` and per-extension LF enforcement,
  eliminating LF/CRLF warnings on Windows.
- `tests/conftest.py` with shared `pytest` fixtures (`brazil_polygon`,
  `brazil_line`, `brazil_point`, `make_gpkg`, `polygon_gpkg`), removing
  duplication across test classes.
- `[tool.pytest.ini_options]` in `pyproject.toml` so `pytest` can be run
  from the repo root without arguments.

### Fixed

- `report["output_crs"]` now correctly reports `EPSG:5880`.
- Tests updated to assert EPSG:5880 output and metric coordinate ranges.

---

## [1.3.0] - 2026-05-22

### Fixed

- CRS consistency: output geometry stored in EPSG:4674 (was incorrectly
  EPSG:5880 in the code while README claimed 4674).
- Version sync: `__version__` and `pyproject.toml` both set to `1.3.0`.
- `os.makedirs` safety for bare filename output paths.

### Changed

- All imports moved to module level.
- `sys` imported at module level; `_cli` no longer imports it locally.

---

## [1.0.0] - 2026-05-15

### Added

- Initial release with `convert_to_geoparquet()` function and CLI.
- Geometry repair via `shapely.make_valid`.
- Strict geometry-type homogeneity enforcement.
- 25 x 25 km tile IDs in EPSG:5880.
- Hilbert curve row ordering for DuckDB row-group pruning.
- GeoParquet 1.1 output with covering bbox struct.
- ZSTD compression, configurable row-group size.
- Conversion report dict.
