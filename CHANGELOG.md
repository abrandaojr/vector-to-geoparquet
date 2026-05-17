# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.1.0] - 2026-05-17

### Changed

- **Output CRS changed from EPSG:4674 to EPSG:5880** (SIRGAS 2000 / Brazil
  Polyconic, unit: metres). EPSG:5880 is the projected CRS mandated by IBGE
  for area calculation across the national territory. EPSG:4674 is now used
  only as an intermediate normalisation step before geometry repair.
- Geometry repair (`shapely.make_valid`) is now applied in EPSG:4674
  (geographic space) before reprojecting to EPSG:5880, ensuring stable
  repair of degenerate geometries prior to projection.
- Step 6 (tile IDs) no longer reprojects geometries — they are already in
  EPSG:5880 after step 3, eliminating a redundant `.to_crs()` call.
- `_OUTPUT_CRS_ENTRY` constant updated to `ProjectedCRS / EPSG:5880` for
  correct QGIS CRS metadata patching.
- `output_crs` field in the conversion report now shows `EPSG:5880`.
- Module docstring and all inline comments updated to reflect the new CRS
  pipeline.

### Added

- `_patch_crs_metadata()`: patches the `geo` metadata of the output
  GeoParquet to embed the correct CRS authority/code reference
  (`EPSG:5880`). Some geopandas/pyarrow version combinations write the
  `crs` field as `null`, causing GIS clients (notably QGIS) to display
  "Unknown CRS". The patch is skipped if the CRS is already present, so
  there is no performance cost for well-formed files.
- `_OUTPUT_CRS_ENTRY` module-level constant: canonical PROJJSON authority/
  code entry for EPSG:5880, used by `_patch_crs_metadata`.
- `__version__ = "1.1.0"` module attribute.

## [1.0.0] - 2026-05-15

### Added

- Initial release.
- `convert_to_geoparquet()` function: converts any pyogrio-readable vector
  format to GeoParquet with SIRGAS 2000 (EPSG:4674) as the output CRS,
  following IBGE Resolution R.PR-1/2005.
- Geometry repair via `shapely.make_valid`.
- Strict geometry-type homogeneity enforcement (polygon / line / point).
- 25 × 25 km tile ID columns (`tile_id`, `tile_col`, `tile_row`) computed
  in EPSG:5880 (SIRGAS 2000 / Brazil Polyconic) using `representative_point`
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
