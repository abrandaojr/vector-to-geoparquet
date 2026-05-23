# vector_to_geoparquet

> **Geographic scope: Brazil only.** Tile IDs and Hilbert curve ordering use
> EPSG:5880 (SIRGAS2000 / Brazil Polyconic), calibrated for Brazilian territory.
> This package is not intended for datasets outside Brazil.

Convert any vector file with coverage over **Brazilian territory** to a
DuckDB-optimized GeoParquet file following the Brazilian geodetic reference
system standard defined by **IBGE Resolution R.PR-1/2005**.

**Output CRS: EPSG:5880** (SIRGAS2000 / Brazil Polyconic, unit: metres).
All stored geometry, tile IDs, Hilbert ordering, and bbox values use this CRS.

Typical Brazilian datasets this tool handles well: CAR rural properties
(SICAR), PRODES deforestation polygons, MapBiomas land-use layers, IBGE
municipalities and states, ANA hydrography, MMA conservation units, FUNAI
indigenous lands, FCP quilombola territories, DNIT road networks, and similar
public or institutional geospatial datasets distributed in Shapefile,
GeoPackage, or GeoJSON format.

---

## Features

- Reads any format supported by [pyogrio](https://pyogrio.readthedocs.io/)
  (Shapefile, GeoPackage, GeoJSON, FlatGeobuf, and more)
- Reprojects all inputs to **SIRGAS2000 / Brazil Polyconic** (EPSG:5880)
- Repairs geometries with `shapely.make_valid`
- Enforces strict geometry-type homogeneity:
  - Polygon input -> only `(Multi)Polygon` output
  - Line input -> only `(Multi)LineString` output
  - Point input -> only `(Multi)Point` output
- Assigns **25 x 25 km tile IDs** on the EPSG:5880 grid
- Sorts rows by **Hilbert curve order** so spatially adjacent features
  share Parquet row groups, enabling DuckDB to skip row groups via
  per-row-group `bbox` statistics during spatial intersect queries
- Writes **GeoParquet 1.1** with a covering `bbox` struct column for fast
  pre-filtering without WKB deserialization
- Uses ZSTD compression (configurable level)

---

## Package structure

```
vector_to_geoparquet/
├── __init__.py      # public API: convert_to_geoparquet, __version__
├── _constants.py    # CRS strings, FAMILY dict, version
├── _geometry.py     # detect_family, normalise_crs, repair, enforce_homogeneity
├── _hilbert.py      # hilbert() with Shapely 2.0 API and pure-Python fallback
└── _core.py         # convert_to_geoparquet() + _cli()
```

---

## Installation

```
pip install geopandas pyogrio pyarrow shapely numpy
```

Python 3.10+ is required.

---

## Command-line usage

```
python -m vector_to_geoparquet <input> <output.parquet> [layer]
```

Or via the installed console script:

```
vector-to-geoparquet <input> <output.parquet> [layer]
```

### Examples

```
vector-to-geoparquet municipalities.shp municipalities.parquet
vector-to-geoparquet data.gpkg properties.parquet car_properties
vector-to-geoparquet biomes.geojson biomes.parquet
```

---

## Python API

```python
from vector_to_geoparquet import convert_to_geoparquet

report = convert_to_geoparquet(
    input_path="car_imoveis.shp",
    output_path="car_imoveis.parquet",
)
```

All parameters with their defaults:

```python
report = convert_to_geoparquet(
    input_path="car_imoveis.shp",
    output_path="car_imoveis.parquet",
    layer=None,               # layer name/index for multi-layer formats
    tile_size_m=25_000.0,     # tile edge length in metres (default: 25 km)
    row_group_size=65_536,    # rows per Parquet row group
    compression="zstd",       # Parquet compression codec
    compression_level=3,      # ZSTD level (1-22)
    hilbert_p=15,             # Hilbert curve resolution (2^p cells per axis)
)
```

The function returns a `dict` with the conversion report:

```
------------------------------------------------------------
  vector_to_geoparquet v1.4.0 -- conversion complete
------------------------------------------------------------
  input_path              : car_imoveis.shp
  output_path             : car_imoveis.parquet
  input_crs               : EPSG:4674
  output_crs              : EPSG:5880
  geometry_family         : polygon
  n_features_in           : 6823401
  n_features_out          : 6823398
  n_dropped               : 3
  tile_size_km            : 25.0
  n_tiles                 : 4712
  hilbert_p               : 15
  row_group_size          : 65536
  compression             : zstd:3
  bbox                    : {xmin: -3412000.0, ymin: -3800000.0, xmax: 2910000.0, ymax: 570000.0}
  file_size_mb            : 1847.3
------------------------------------------------------------
```

---

## Using the output in DuckDB

```sql
LOAD spatial;

-- Intersect two GeoParquet layers (both in EPSG:5880)
SELECT a.*, b.property_id
FROM read_parquet('deforestation.parquet') a
JOIN read_parquet('car_properties.parquet') b
  ON  a.bbox.xmin <= b.bbox.xmax
  AND a.bbox.xmax >= b.bbox.xmin
  AND a.bbox.ymin <= b.bbox.ymax
  AND a.bbox.ymax >= b.bbox.ymin
  AND ST_Intersects(
        ST_GeomFromWKB(a.geometry),
        ST_GeomFromWKB(b.geometry)
      );

-- Area calculation (unit: m2, native for EPSG:5880)
SELECT property_id, ST_Area(ST_GeomFromWKB(geometry)) / 10000 AS area_ha
FROM read_parquet('car_properties.parquet');

-- Aggregate deforestation area by 25 km tile
SELECT tile_id, SUM(area_ha) AS total_ha
FROM read_parquet('deforestation.parquet')
GROUP BY tile_id
ORDER BY total_ha DESC;
```

---

## Output schema

| Column     | Type        | Description                                               |
|------------|-------------|-----------------------------------------------------------|
| `geometry` | WKB (bytes) | Geometry in EPSG:5880 (SIRGAS2000 / Brazil Polyconic, m)  |
| `bbox`     | struct      | `{xmin, ymin, xmax, ymax}` per feature (GeoParquet 1.1)   |
| `tile_col` | int32       | Tile column index (25 km grid, EPSG:5880)                 |
| `tile_row` | int32       | Tile row index (25 km grid, EPSG:5880)                    |
| `tile_id`  | category    | `"col_row"` string, dictionary-encoded in Parquet         |
| `...`      | any         | All original attribute columns                            |

> **Tile assignment note:** `tile_id` is derived from each feature's
> `representative_point`. For features spanning more than one 25 km tile,
> `tile_id` reflects the tile of the representative point, not the full extent.

---

## Geodetic reference

This tool follows IBGE Resolution R.PR-1/2005:

> Full text (PDF): <https://geoftp.ibge.gov.br/metodos_e_outros_documentos_de_referencia/normas/rpr_01_25fev2005.pdf>

| CRS        | EPSG  | Role                                      |
|------------|-------|-------------------------------------------|
| SIRGAS2000 geographic | 4674 | Intermediate normalisation only |
| SIRGAS2000 / Brazil Polyconic | 5880 | Output CRS -- all stored data |

Input files in any CRS (SAD 69, Corrego Alegre, WGS 84, etc.) are
automatically reprojected.

---

## License

MIT

---

## Getting started

```
git clone https://github.com/abrandaojr/vector-to-geoparquet.git
cd vector-to-geoparquet
pip install -r requirements.txt

# Run tests
pip install pytest
pytest

# Install as a local package
pip install -e .
vector-to-geoparquet municipalities.shp municipalities.parquet
```
