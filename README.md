# vector-to-geoparquet

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![GeoParquet 1.1](https://img.shields.io/badge/GeoParquet-1.1-green.svg)](https://geoparquet.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Brazil-specific converter from common vector geospatial formats to
DuckDB-optimized GeoParquet.

The package reads Shapefile, GeoPackage, GeoJSON, FlatGeobuf, and other
`pyogrio`-supported vector formats, normalizes geometries, reprojects features
to SIRGAS 2000 / Brazil Polyconic, assigns 25 km tile IDs, Hilbert-sorts rows,
and writes GeoParquet 1.1 with row-group-friendly spatial metadata.

## Scope

This tool is intentionally calibrated for Brazilian territory.

- Output CRS: `EPSG:5880` - SIRGAS 2000 / Brazil Polyconic, metres.
- Intermediate normalization CRS: `EPSG:4674` - SIRGAS 2000 geographic.
- Geodetic reference: IBGE Resolution R.PR-1/2005.
- Tile IDs, Hilbert ordering, bbox values, and stored geometries use EPSG:5880.

It is a good fit for Brazilian datasets such as CAR/SICAR rural properties,
PRODES deforestation polygons, MapBiomas land-cover layers, IBGE administrative
boundaries, ANA hydrography, MMA conservation units, FUNAI indigenous lands,
FCP quilombola territories, and DNIT road networks.

## Why This Exists

Large vector layers are often distributed as Shapefiles or GeoPackages that are
awkward to query repeatedly. This package creates GeoParquet files designed for
fast analytical reads in DuckDB and other modern columnar tools:

- geometry stored in a consistent projected CRS;
- invalid geometries repaired before export;
- homogeneous point, line, or polygon output;
- per-feature `bbox` struct for spatial pre-filtering;
- 25 km `tile_id` for coarse spatial partitioning;
- Hilbert ordering for better row-group locality;
- ZSTD-compressed Parquet with configurable row-group size.

## Installation

```bash
pip install geopandas pyogrio pyarrow shapely numpy
pip install git+https://github.com/abrandaojr/vector-to-geoparquet.git
```

For local development:

```bash
git clone https://github.com/abrandaojr/vector-to-geoparquet.git
cd vector-to-geoparquet
pip install -r requirements.txt
pip install -e .
```

Python 3.10 or newer is required.

## Command Line

```bash
vector-to-geoparquet <input> <output.parquet> [layer]
```

Equivalent module form:

```bash
python -m vector_to_geoparquet <input> <output.parquet> [layer]
```

Examples:

```bash
vector-to-geoparquet municipalities.shp municipalities.parquet
vector-to-geoparquet data.gpkg car_properties.parquet car_properties
vector-to-geoparquet biomes.geojson biomes.parquet
```

## Python API

```python
from vector_to_geoparquet import convert_to_geoparquet

report = convert_to_geoparquet(
    input_path="car_imoveis.shp",
    output_path="car_imoveis.parquet",
)
```

Full parameter set:

```python
report = convert_to_geoparquet(
    input_path="car_imoveis.shp",
    output_path="car_imoveis.parquet",
    layer=None,
    tile_size_m=25_000.0,
    row_group_size=65_536,
    compression="zstd",
    compression_level=3,
    hilbert_p=15,
)
```

The function returns a conversion report with CRS, feature counts, tile
statistics, output size, and bounding box metadata.

## Output Schema

| Column | Type | Description |
| --- | --- | --- |
| `geometry` | WKB bytes | Geometry in EPSG:5880 |
| `bbox` | struct | `{xmin, ymin, xmax, ymax}` per feature |
| `tile_col` | int32 | 25 km grid column |
| `tile_row` | int32 | 25 km grid row |
| `tile_id` | category | `"col_row"` tile identifier |
| `...` | original types | Original attribute columns |

`tile_id` is assigned from each feature's representative point. Features that
span multiple 25 km tiles keep one representative tile ID; use `bbox` or full
geometry predicates for exact spatial filtering.

## DuckDB Example

```sql
LOAD spatial;

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
```

Area calculations are native to the projected output CRS:

```sql
SELECT tile_id, SUM(ST_Area(ST_GeomFromWKB(geometry)) / 10000) AS area_ha
FROM read_parquet('deforestation.parquet')
GROUP BY tile_id
ORDER BY area_ha DESC;
```

## Package Layout

```text
vector_to_geoparquet/
  __init__.py      # public API
  _constants.py    # CRS strings and package version
  _core.py         # conversion function and CLI
  _geometry.py     # CRS normalization, repair, homogeneity checks
  _hilbert.py      # Hilbert ordering
  _proj.py         # PROJ data-path configuration
tests/
  test_convert.py
  test_proj_config.py
```

## Quality Checks

```bash
python -m pytest
python -m compileall -q vector_to_geoparquet tests
```

## Geodetic Reference

This tool follows IBGE Resolution R.PR-1/2005:

<https://geoftp.ibge.gov.br/metodos_e_outros_documentos_de_referencia/normas/rpr_01_25fev2005.pdf>

| CRS | EPSG | Role |
| --- | ---: | --- |
| SIRGAS 2000 geographic | 4674 | Intermediate normalization |
| SIRGAS 2000 / Brazil Polyconic | 5880 | Output CRS |

## License

MIT. See `LICENSE`.
