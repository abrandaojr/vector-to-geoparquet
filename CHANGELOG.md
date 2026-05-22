# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.3.0] - 2026-05-22

### Fixed

- **CRS consistency (breaking fix):** output geometry is now stored in
  EPSG:4674 (SIRGAS2000 geographic, degrees) as documented in the README and
  schema table. Previous versions incorrectly stored geometry in EPSG:5880
  (SIRGAS2000 / Brazil Polyconic, metres). Tile IDs and Hilbert ordering
  continue to be computed internally in EPSG:5880 for correct metric-distance
  calculations, but the GeoDataFrame is not reprojected for storage.
  Users querying previous outputs with tools that expect EPSG:4674 (DuckDB
  Spatial, QGIS, etc.) should re-run the conversion.
- **Version sync:** `__version__` in `vector_to_geoparquet.py` and `version`
  in `pyproject.toml` are now aligned (both `1.3.0`). Previous versions had
  `__version__ = "1.2.0"` in the module and `version = "1.0.0"` in
  `pyproject.toml`.
- **`os.makedirs` safety:** the output directory is now resolved via
  `os.path.abspath` before calling `os.makedirs`, ensuring correct behaviour
  when `output_path` is a bare filename with no directory component.

### Changed

- **Module-level imports:** all imports (`os`, `sys`, `warnings`, `numpy`,
  `geopandas`, `shapely`, etc.) are now at the top of the module instead of
  inside `convert_to_geoparquet()`. This improves IDE analysis, autocomplete,
  and readability without affecting runtime behaviour for typical usage.
- `report["output_crs"]` now correctly reports `EPSG:4674` instead of
  `EPSG:5880`.
- `sys` is now imported at module level; the `_cli` function no longer
  imports it locally.

### Documentation

- Module docstring updated to accurately describe the two-CRS design:
  EPSG:4674 for output geometry, EPSG:5880 for internal metric calculations.
- `convert_to_geoparquet()` docstring expanded with a Notes section
  explaining the tile-assignment behaviour for large polygons spanning
  multiple 25 km tiles.

---

## [1.0.0] - 2026-05-15

### Added

- Initial release.
- `convert_to_geoparquet()` function: converts any pyogrio-readable vector
  format to GeoParquet with SIRGAS2000 (EPSG:4674) as the output CRS,
  following IBGE Resolution R.PR-1/2005.
- Geometry repair via `shapely.make_valid`.
- Strict geometry-type homogeneity enforcement (polygon / line / point).
- 25 x 25 km tile ID columns (`tile_id`, `tile_col`, `tile_row`) computed
  in EPSG:5880 (SIRGAS2000 / Brazil Polyconic) using `representative_point`
  for correct assignment in concave polygons and curved lines.
- Hilbert curve row ordering (`shapely.hilbert_distance`, `p=15`) for
  spatial locality: DuckDB skips row groups via per-row-group bbox
  statistics during spatial intersect queries.
- GeoParquet 1.1 output with `write_covering_bbox=True` for per-row
  `bbox` struct column used by DuckDB Spatial.
- ZSTD compression with configurable level.
- Configurable row-group size (default 65 536).
- Conversion report dict with feature counts, tile stats, bbox, and
  file size.
- Command-line interface: `python vector_to_geoparquet.py` and
  `vector-to-geoparquet` console script (via `pyproject.toml`).
- Unit tests covering CRS output, geometry type homogeneity, geometry
  repair, tile column format, Parquet schema, report keys, and error
  handling.
