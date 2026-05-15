# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
