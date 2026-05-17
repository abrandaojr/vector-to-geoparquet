# vector_to_geoparquet

> **Geographic scope: Brazil only.**
> All projections use the SIRGAS 2000 datum (IBGE Resolution R.PR-1/2005).
> This tool is not intended for datasets outside Brazil.

Convert any vector file with coverage over **Brazilian territory** to a
DuckDB-optimized GeoParquet file.

Output geometry is stored in **SIRGAS 2000 / Brazil Polyconic — EPSG:5880**
(unit: metres), the projected CRS mandated by IBGE for area calculation
across the national territory. EPSG:4674 (SIRGAS 2000 geographic) is used
only as an intermediate normalisation step before geometry repair.

Typical datasets: CAR rural properties (SICAR), PRODES deforestation
polygons, MapBiomas land-use layers, IBGE municipalities and states, ANA
hydrography, MMA conservation units, FUNAI indigenous lands, FCP quilombola
territories, DNIT road networks.

---

## Features

- Reads any format supported by [pyogrio](https://pyogrio.readthedocs.io/)
  (Shapefile, GeoPackage, GeoJSON, FlatGeobuf, and more)
- Normalises input to **EPSG:4674** → repairs geometries → reprojects to
  **EPSG:5880** (output CRS, metres)
- Repairs geometries with `shapely.make_valid` (Shapely 2.0 vectorised API)
- Enforces strict geometry-type homogeneity:
  - Polygon input → only `(Multi)Polygon` output
  - Line input → only `(Multi)LineString` output
  - Point input → only `(Multi)Point` output
- Assigns **25 × 25 km tile IDs** in EPSG:5880 using `representative_point()`
  (guaranteed inside the geometry)
- Sorts rows by **Hilbert curve order** for DuckDB row-group pruning
- Writes **GeoParquet 1.1** with a covering `bbox` struct column
- Patches `geo` metadata CRS for QGIS compatibility (some geopandas/pyarrow
  combinations write the `crs` field as `null`)
- ZSTD compression, configurable level

---

## Installation

```bash
pip install geopandas pyogrio pyarrow shapely numpy
```

Python 3.10+ is required.

---

## Command-line usage

```bash
python vector_to_geoparquet.py <input> <output.parquet> [layer]
```

### Examples

```bash
# Shapefile
python vector_to_geoparquet.py municipalities.shp municipalities.parquet

# GeoPackage with a specific layer
python vector_to_geoparquet.py data.gpkg properties.parquet car_properties

# GeoJSON
python vector_to_geoparquet.py biomes.geojson biomes.parquet
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
    compression_level=3,      # ZSTD level (1–22)
    hilbert_p=15,             # Hilbert curve resolution (2^p cells per axis)
)
```

Example report output:

```
------------------------------------------------------------
  vector_to_geoparquet v1.1.0 — conversion complete
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
  bbox                    : {xmin: -5431290, ymin: -3762185, xmax: 3287412, ymax: 2172384}
  file_size_mb            : 1847.3
------------------------------------------------------------
```

---

## Conversion pipeline

```
Input (any CRS)
    │
    ▼
Normalise → EPSG:4674          # geographic, for stable geometry repair
    │
    ▼
Repair geometries               # shapely.make_valid (vectorised)
    │
    ▼
Enforce type homogeneity        # drop/split GeometryCollections
    │
    ▼
Reproject → EPSG:5880           # OUTPUT CRS — SIRGAS 2000 / Brazil Polyconic
    │
    ▼
Compute 25 km tile IDs          # floor(x / 25000), floor(y / 25000)
    │
    ▼
Hilbert sort                    # spatial locality for DuckDB row-group pruning
    │
    ▼
Write GeoParquet 1.1            # ZSTD, covering bbox, patched CRS metadata
```

---

## Using the output in DuckDB

```sql
LOAD spatial;

-- Spatial intersect with bbox pre-filter (no WKB deserialization)
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

-- Area calculation (geometry already in metres — EPSG:5880)
SELECT property_id, ST_Area(ST_GeomFromWKB(geometry)) / 10000 AS area_ha
FROM read_parquet('car_properties.parquet');

-- Aggregate by 25 km tile
SELECT tile_id, COUNT(*) AS n, SUM(ST_Area(ST_GeomFromWKB(geometry)) / 10000) AS total_ha
FROM read_parquet('deforestation.parquet')
GROUP BY tile_id
ORDER BY total_ha DESC;
```

> **Note:** Because the output CRS is EPSG:5880 (metres), `ST_Area` returns
> values in m² directly — no unit conversion factor needed beyond `/10000`
> for hectares.

### How Hilbert sorting works

```
Without Hilbert sort                With Hilbert sort
-------------------------------     ------------------------------
Row group 1: bbox = all Brazil      Row group 1: bbox = ~150 km × 150 km
Row group 2: bbox = all Brazil      Row group 2: bbox = ~150 km × 150 km
Row group 3: bbox = all Brazil      Row group 3: bbox = ~150 km × 150 km
  → DuckDB reads all row groups       → DuckDB skips most row groups
```

---

## Output schema

| Column     | Type        | Description                                              |
|------------|-------------|----------------------------------------------------------|
| `geometry` | WKB (bytes) | Geometry in SIRGAS 2000 / Brazil Polyconic (EPSG:5880, metres) |
| `bbox`     | struct      | `{xmin, ymin, xmax, ymax}` per feature (GeoParquet 1.1) |
| `tile_col` | int32       | Tile column index (25 km grid, EPSG:5880)                |
| `tile_row` | int32       | Tile row index (25 km grid, EPSG:5880)                   |
| `tile_id`  | category    | `"col_row"` string, dictionary-encoded in Parquet        |
| `...`      | any         | All original attribute columns                           |

---

## Geodetic reference

This tool follows the official cartographic standards published by IBGE:

> **IBGE Resolution R.PR-1/2005** — *Altera a caracterização do Sistema
> Geodésico Brasileiro*, signed February 25, 2005.
> Full text: <https://geoftp.ibge.gov.br/metodos_e_outros_documentos_de_referencia/normas/rpr_01_25fev2005.pdf>

### Output CRS: EPSG:5880 — SIRGAS 2000 / Brazil Polyconic

The projected CRS used for all output geometry and area computation.

| Parameter    | Value                              |
|--------------|------------------------------------|
| Datum        | SIRGAS 2000 (GRS80 ellipsoid)      |
| Projection   | Polyconic                          |
| Unit         | Metre                              |
| Extent       | Brazil                             |
| EPSG code    | 5880                               |

### Intermediate CRS: EPSG:4674 — SIRGAS 2000 geographic

Used only as an intermediate step to normalise input data and perform
geometry repair before reprojecting to EPSG:5880. Not stored in the output.

| Parameter      | Value                   |
|----------------|-------------------------|
| Semi-major axis | 6 378 137 m            |
| Flattening     | 1/298.257 222 101       |
| Reference epoch | 2000.4                 |
| EPSG code      | 4674                    |

Input files in any CRS (including SAD 69 or Córrego Alegre) are
automatically reprojected to EPSG:4674 before geometry repair, then to
EPSG:5880 for output.

### Transformation parameters (SAD 69 → SIRGAS 2000)

| Parameter | Value    |
|-----------|----------|
| ΔX        | −67.35 m |
| ΔY        | +3.88 m  |
| ΔZ        | −38.22 m |

---

## License

MIT

---

## Getting started

```bash
git clone https://github.com/abrandaojr/vector-to-geoparquet.git
cd vector-to-geoparquet
pip install -r requirements.txt

# Run tests
pip install pytest
pytest tests/ -v

# Install as a local package (enables the console script)
pip install -e .
vector-to-geoparquet municipalities.shp municipalities.parquet
```
