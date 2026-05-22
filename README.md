# vector_to_geoparquet

> **Geographic scope: Brazil only.** Tile IDs and Hilbert curve ordering use
> EPSG:5880 (SIRGAS2000 / Brazil Polyconic), which is calibrated for Brazilian
> territory. This function is not intended for datasets outside Brazil.

Convert any vector file with coverage over **Brazilian territory** to a
DuckDB-optimized GeoParquet file following the Brazilian geodetic reference
system standard defined by **IBGE Resolution R.PR-1/2005** (SIRGAS2000,
EPSG:4674).

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
- Reprojects input data to **SIRGAS2000 geographic** (EPSG:4674), the official
  Brazilian geodetic reference system
- Repairs geometries with `shapely.make_valid`
- Enforces strict geometry-type homogeneity:
  - Polygon input → only `(Multi)Polygon` output
  - Line input → only `(Multi)LineString` output
  - Point input → only `(Multi)Point` output
- Assigns **25 x 25 km tile IDs** computed in EPSG:5880
  (SIRGAS2000 / Brazil Polyconic, unit: metres) — internal only
- Sorts rows by **Hilbert curve order** (also computed in EPSG:5880) so that
  spatially adjacent features share Parquet row groups, enabling DuckDB to
  skip row groups via per-row-group `bbox` statistics during spatial intersect
  queries
- Writes **GeoParquet 1.1** with output geometry in **EPSG:4674** and a
  covering `bbox` struct column for fast pre-filtering without WKB
  deserialization
- Uses ZSTD compression (configurable level)

---

## Installation

```
pip install geopandas pyogrio pyarrow shapely numpy
```

Python 3.10+ is required.

---

## Command-line usage

```
python vector_to_geoparquet.py <input> <output.parquet> [layer]
```

### Examples

```
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
    compression_level=3,      # ZSTD level (1-22)
    hilbert_p=15,             # Hilbert curve resolution (2^p cells per axis)
)
```

The function returns a `dict` with the conversion report:

```
------------------------------------------------------------
  vector_to_geoparquet v1.3.0 -- conversion complete
------------------------------------------------------------
  input_path              : car_imoveis.shp
  output_path             : car_imoveis.parquet
  input_crs               : EPSG:4674
  output_crs              : EPSG:4674
  geometry_family         : polygon
  n_features_in           : 6823401
  n_features_out          : 6823398
  n_dropped               : 3
  tile_size_km            : 25.0
  n_tiles                 : 4712
  hilbert_p               : 15
  row_group_size          : 65536
  compression             : zstd:3
  bbox                    : {xmin: -73.98, ymin: -33.75, xmax: -28.85, ymax: 5.27}
  file_size_mb            : 1847.3
------------------------------------------------------------
```

---

## Using the output in DuckDB

The generated GeoParquet is optimized for DuckDB spatial intersect queries.
The recommended pattern combines a `bbox` pre-filter (which prunes row groups
without touching WKB bytes) with `ST_Intersects` on the actual geometry:

```sql
LOAD spatial;

-- Intersect two GeoParquet layers
SELECT a.*, b.property_id
FROM read_parquet('deforestation.parquet') a
JOIN read_parquet('car_properties.parquet') b
  ON  a.bbox.xmin <= b.bbox.xmax   -- bbox pre-filter: no WKB deserialization
  AND a.bbox.xmax >= b.bbox.xmin
  AND a.bbox.ymin <= b.bbox.ymax
  AND a.bbox.ymax >= b.bbox.ymin
  AND ST_Intersects(
        ST_GeomFromWKB(a.geometry),
        ST_GeomFromWKB(b.geometry)
      );

-- Aggregate deforestation area by 25 km tile
SELECT tile_id, SUM(area_ha) AS total_ha
FROM read_parquet('deforestation.parquet')
GROUP BY tile_id
ORDER BY total_ha DESC;
```

### How the optimization works

```
Without Hilbert sort                With Hilbert sort
-------------------------------     ------------------------------
Row group 1: bbox = all Brazil      Row group 1: bbox = ~150 km x 150 km
Row group 2: bbox = all Brazil      Row group 2: bbox = ~150 km x 150 km
Row group 3: bbox = all Brazil      Row group 3: bbox = ~150 km x 150 km
  -> DuckDB reads all row groups      -> DuckDB skips most row groups
```

`shapely.hilbert_distance` uses the **bounding box of each geometry**,
not its centroid, so polygon rings and line vertices (not tile centroids)
determine the sort key.

---

## Output schema

| Column     | Type       | Description                                              |
|------------|------------|----------------------------------------------------------|
| `geometry` | WKB (bytes)| Geometry in SIRGAS2000 **geographic** (EPSG:4674)        |
| `bbox`     | struct     | `{xmin, ymin, xmax, ymax}` per feature (GeoParquet 1.1) |
| `tile_col` | int32      | Tile column index (25 km grid, computed in EPSG:5880)    |
| `tile_row` | int32      | Tile row index (25 km grid, computed in EPSG:5880)       |
| `tile_id`  | category   | `"col_row"` string, dictionary-encoded in Parquet        |
| `...`      | any        | All original attribute columns                           |

> **Tile assignment note:** `tile_id` is derived from each feature's
> `representative_point` projected to EPSG:5880. For polygons spanning
> more than one 25 km tile, `tile_id` reflects the tile containing the
> representative point, not the full spatial extent of the feature.

---

## Geodetic reference and cartographic guidelines

This tool was built following the official cartographic guidelines published
by IBGE (Instituto Brasileiro de Geografia e Estatistica):

> **IBGE Resolution R.PR-1/2005** -- *Altera a caracterizacao do Sistema
> Geodesico Brasileiro* (Amends the characterization of the Brazilian Geodetic
> System), signed February 25, 2005.
>
> Full text (PDF): <https://geoftp.ibge.gov.br/metodos_e_outros_documentos_de_referencia/normas/rpr_01_25fev2005.pdf>

### Output CRS: SIRGAS2000 geographic -- EPSG:4674

As established by R.PR-1/2005, SIRGAS2000 (*Sistema de Referencia
Geocentrico para as Americas*, 2000 realization) is the official geodetic
reference system for Brazil, defined by the International Terrestrial
Reference System (ITRS) and realized through the GRS80 ellipsoid:

| Parameter      | Value                  |
|----------------|------------------------|
| Semi-major axis| a = 6 378 137 m        |
| Flattening     | f = 1/298.257 222 101  |
| Origin         | Earth's center of mass |
| Reference epoch| 2000.4                 |
| EPSG code      | 4674                   |

SIRGAS2000 has since become the exclusive reference system for all Brazilian
geospatial data. Output geometry is stored in EPSG:4674 for full
interoperability with DuckDB Spatial, QGIS, GeoPandas, and any GeoParquet
1.1-compliant reader.

### Internal metric CRS: EPSG:5880

Tile IDs (25 x 25 km grid) and Hilbert curve ordering are computed in
**SIRGAS2000 / Brazil Polyconic -- EPSG:5880**, the national projected
coordinate reference system maintained by IBGE for Brazil-wide mapping.
Unit: metres. This projected CRS is used only internally; all geometry
stored in the output GeoParquet is in EPSG:4674.

### Transformation parameters (SAD 69 -> SIRGAS2000)

For reference, the parameters defined in R.PR-1/2005 for converting existing
SAD 69 data to SIRGAS2000 are:

| Parameter | Value     |
|-----------|-----------|
| DX        | -67.35 m  |
| DY        | +3.88 m   |
| DZ        | -38.22 m  |

Input files in any CRS (including SAD 69 or Corrego Alegre) are automatically
reprojected to EPSG:4674 before processing.

---

## License

MIT

---

## Getting started from this repository

```
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
