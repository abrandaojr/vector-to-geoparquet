"""
vector_to_geoparquet.py
=======================
**Brazil-specific** utility to convert any vector file with coverage over
Brazilian territory to a DuckDB-optimized GeoParquet file.

Geographic scope
----------------
This function is designed and tested exclusively for datasets covering
**Brazil** or any of its sub-regions (biomes, states, municipalities,
river basins, rural properties, etc.). The two projected CRS used
internally are national Brazilian standards maintained by IBGE:

- Output CRS: **SIRGAS2000 geographic -- EPSG:4674**
  The official Brazilian geodetic reference system, as mandated by
  IBGE Resolution R.PR-1/2005 (February 25, 2005).
  Full text: https://geoftp.ibge.gov.br/metodos_e_outros_documentos_de_referencia/normas/rpr_01_25fev2005.pdf
- Metric CRS (tile IDs and Hilbert curve): **SIRGAS2000 / Brazil Polyconic
  -- EPSG:5880**
  Brazil's national projected coordinate reference system, unit: meters.

Using this function for datasets outside Brazil will likely produce
incorrect tile IDs and suboptimal Hilbert ordering, because EPSG:5880
is optimized for the Brazilian territory and introduces significant
distortion at higher latitudes or in other continents.

Key features
------------
- Supports any format readable by pyogrio (Shapefile, GeoPackage, GeoJSON,
  FlatGeobuf, etc.)
- Reprojects to SIRGAS2000 geographic CRS (EPSG:4674)
- Repairs geometries using ``shapely.make_valid``
- Enforces strict geometry-type homogeneity:
    - Polygon input  -> only (Multi)Polygon output
    - Line input     -> only (Multi)LineString output
    - Point input    -> only (Multi)Point output
- Assigns 25 x 25 km tile IDs computed in EPSG:5880 (Brazil Polyconic)
  using ``representative_point()`` -- guaranteed inside the geometry
- Sorts rows by Hilbert curve order so that spatially adjacent features
  land in the same Parquet row groups, enabling DuckDB to skip row groups
  via per-row-group bbox statistics during spatial intersect queries
- Writes GeoParquet 1.1 with a covering ``bbox`` struct column
  (``write_covering_bbox=True``) for fast pre-filtering without WKB
  deserialization
- Uses ZSTD compression and configurable row-group size

Typical Brazilian datasets
--------------------------
CAR rural properties (SICAR), PRODES deforestation polygons, MapBiomas
land-use rasters converted to vector, IBGE municipalities and states,
ANA hydrography, MMA conservation units, FUNAI indigenous lands,
FCP quilombola territories, road networks (DNIT), and similar.

Dependencies
------------
    pip install geopandas pyogrio pyarrow shapely numpy

Usage
-----
    python vector_to_geoparquet.py <input> <output.parquet> [layer]

    # Examples
    python vector_to_geoparquet.py municipalities.shp municipalities.parquet
    python vector_to_geoparquet.py data.gpkg properties.parquet car_properties
    python vector_to_geoparquet.py biomes.geojson biomes.parquet

DuckDB spatial intersect (recommended pattern)
----------------------------------------------
    LOAD spatial;

    SELECT a.*, b.property_id
    FROM read_parquet('deforestation.parquet') a
    JOIN read_parquet('car_properties.parquet') b
      ON  a.bbox.xmin <= b.bbox.xmax        -- bbox pre-filter (no WKB touch)
      AND a.bbox.xmax >= b.bbox.xmin
      AND a.bbox.ymin <= b.bbox.ymax
      AND a.bbox.ymax >= b.bbox.ymin
      AND ST_Intersects(
            ST_GeomFromWKB(a.geometry),
            ST_GeomFromWKB(b.geometry)
          );
"""

from __future__ import annotations


def convert_to_geoparquet(
    input_path: str,
    output_path: str,
    layer: str | None = None,
    tile_size_m: float = 25_000.0,
    row_group_size: int = 65_536,
    compression: str = "zstd",
    compression_level: int = 3,
    hilbert_p: int = 15,
) -> dict:
    """
    Convert a Brazil-extent vector file to a DuckDB-optimized GeoParquet file.

    **Geographic scope: Brazil only.**
    Tile IDs and Hilbert curve ordering are computed in EPSG:5880
    (SIRGAS2000 / Brazil Polyconic), which is optimized for the Brazilian
    territory. Results will be geometrically incorrect for datasets outside
    Brazil.

    Output geometry is always stored in SIRGAS2000 (EPSG:4674), the
    official Brazilian geodetic reference system defined by IBGE Resolution
    R.PR-1/2005 (February 25, 2005):
    https://geoftp.ibge.gov.br/metodos_e_outros_documentos_de_referencia/normas/rpr_01_25fev2005.pdf

    Rows are sorted by Hilbert curve order so that spatially adjacent
    features share Parquet row groups, allowing DuckDB to prune row groups
    efficiently during spatial intersect queries -- the actual geometry WKB
    (polygon rings, line vertices, etc.) is used for every intersect test;
    the Hilbert order and ``bbox`` column are purely for I/O pruning.

    Parameters
    ----------
    input_path : str
        Path to the input vector file. Any format supported by pyogrio
        is accepted (Shapefile, GeoPackage, GeoJSON, FlatGeobuf, etc.).
    output_path : str
        Path to the output ``.parquet`` file. Parent directories are
        created automatically if they do not exist.
    layer : str, optional
        Layer name or index for multi-layer formats such as GeoPackage.
        Ignored for single-layer formats.
    tile_size_m : float
        Tile edge length in meters for ``tile_id`` assignment.
        Default is 25 000 m (25 km). Tiles are computed in EPSG:5880
        (SIRGAS2000 / Brazil Polyconic) and stored as integer column
        indices (``tile_col``, ``tile_row``) plus a categorical
        ``tile_id`` string of the form ``"col_row"``.
    row_group_size : int
        Number of rows per Parquet row group. Smaller values improve
        spatial predicate pushdown; 65 536 is a good general default.
    compression : str
        Parquet compression codec. ``"zstd"`` offers the best
        compression-to-decompression-speed ratio for DuckDB workloads.
    compression_level : int
        ZSTD compression level (1-22). Level 3 is fast and compact.
    hilbert_p : int
        Hilbert curve resolution parameter passed to
        ``shapely.hilbert_distance``. The curve is divided into
        ``2**hilbert_p`` cells per axis. ``p=15`` yields cells of
        roughly 150 m across Brazil's national extent (~5 000 km x
        4 500 km), which is well below the 25 km tile size.

    Returns
    -------
    dict
        Conversion report containing: input/output paths, CRS, feature
        counts, geometry type, tile count, bounding box, file size, and
        row-group configuration.

    Raises
    ------
    ImportError
        If any required dependency is missing.
    ValueError
        If the input file contains no features or if the dominant
        geometry type cannot be determined.
    """

    # ------------------------------------------------------------------
    # 0. Self-contained imports
    # ------------------------------------------------------------------
    import os
    import warnings
    from importlib import import_module

    _required: dict[str, str] = {
        "geopandas": "geopandas>=0.14",
        "pyogrio":   "pyogrio>=0.7",
        "shapely":   "shapely>=2.0",
        "pyarrow":   "pyarrow>=14",
        "numpy":     "numpy>=1.24",
    }
    for _mod, _install in _required.items():
        try:
            import_module(_mod)
        except ImportError:
            raise ImportError(
                f"Required package '{_mod}' is not installed. "
                f"Install it with: pip install {_install}"
            )

    import numpy as np
    import pyarrow.parquet as pq
    import geopandas as gpd
    from shapely import make_valid
    from shapely.geometry import (
        Point, MultiPoint,
        LineString, MultiLineString,
        Polygon, MultiPolygon,
    )

    # hilbert_distance was added in Shapely 2.0. Provide a pure-Python/NumPy
    # fallback so the function works with older installations as well.
    try:
        from shapely import hilbert_distance as _shapely_hilbert
        def _hilbert_sort_key(geom_series, bounds, p: int) -> "np.ndarray":
            return _shapely_hilbert(geom_series, bounds, p=p)
    except ImportError:
        def _xy_to_d(n: int, x: int, y: int) -> int:
            """Convert (x, y) grid cell to Hilbert curve distance."""
            d = 0
            s = n >> 1
            while s:
                rx = 1 if x & s else 0
                ry = 1 if y & s else 0
                d += s * s * ((3 * rx) ^ ry)
                if ry == 0:
                    if rx == 1:
                        x = s - 1 - x
                        y = s - 1 - y
                    x, y = y, x
                s >>= 1
            return d

        def _hilbert_sort_key(geom_series, bounds, p: int) -> "np.ndarray":
            """
            Fallback Hilbert distance for Shapely < 2.0.
            Uses the bounding-box center of each geometry (same as the
            Shapely 2.0 implementation for non-point geometries).
            """
            n = 2 ** p
            minx, miny, maxx, maxy = bounds
            dx = maxx - minx or 1.0
            dy = maxy - miny or 1.0
            geom_bounds = np.array([g.bounds for g in geom_series])
            cx = (geom_bounds[:, 0] + geom_bounds[:, 2]) / 2.0
            cy = (geom_bounds[:, 1] + geom_bounds[:, 3]) / 2.0
            xi = np.clip(((cx - minx) / dx * (n - 1)).astype(np.int64), 0, n - 1)
            yi = np.clip(((cy - miny) / dy * (n - 1)).astype(np.int64), 0, n - 1)
            return np.array(
                [_xy_to_d(n, int(x), int(y)) for x, y in zip(xi, yi)],
                dtype=np.int64,
            )

    # ------------------------------------------------------------------
    # 1. Reference constants (IBGE Resolution R.PR-1/2005)
    # ------------------------------------------------------------------

    # Official Brazilian geodetic reference system -- SIRGAS2000, geographic
    SIRGAS2000_CRS = "EPSG:4674"

    # National metric projected CRS for tile and Hilbert computations
    # EPSG:5880 -- SIRGAS2000 / Brazil Polyconic, unit: meters
    BRAZIL_METRIC_CRS = "EPSG:5880"

    # Maps each geometry type string to its abstract family
    _FAMILY: dict[str, str] = {
        "Point":           "point",
        "MultiPoint":      "point",
        "LineString":      "line",
        "MultiLineString": "line",
        "Polygon":         "polygon",
        "MultiPolygon":    "polygon",
    }
    # Maps each family to the (single, multi) Shapely geometry classes
    _SINGLE_MULTI: dict[str, tuple] = {
        "point":   (Point,       MultiPoint),
        "line":    (LineString,  MultiLineString),
        "polygon": (Polygon,     MultiPolygon),
    }
    # Maps each family to the (single, multi) geometry type name strings
    _TYPE_NAMES: dict[str, tuple[str, str]] = {
        "point":   ("Point",       "MultiPoint"),
        "line":    ("LineString",  "MultiLineString"),
        "polygon": ("Polygon",     "MultiPolygon"),
    }

    # ------------------------------------------------------------------
    # 2. Read input file
    # ------------------------------------------------------------------
    read_kwargs: dict = {"engine": "pyogrio"}
    if layer is not None:
        read_kwargs["layer"] = layer

    gdf = gpd.read_file(input_path, **read_kwargs)
    n_original = len(gdf)

    if gdf.empty:
        raise ValueError("The input file contains no features.")

    input_crs = str(gdf.crs) if gdf.crs is not None else "undefined"

    # ------------------------------------------------------------------
    # 3. Determine the dominant geometry family
    # ------------------------------------------------------------------
    type_counts = (
        gdf.geom_type
        .dropna()
        .map(lambda t: _FAMILY.get(t, "other"))
        .value_counts()
    )
    type_counts = type_counts[type_counts.index != "other"]

    if type_counts.empty:
        raise ValueError(
            "Could not determine geometry type. "
            "Verify that the input file contains valid geometries."
        )

    target_family: str = type_counts.index[0]   # dominant family

    # ------------------------------------------------------------------
    # 4. Reproject to SIRGAS2000 (EPSG:4674)
    # ------------------------------------------------------------------
    if gdf.crs is None:
        warnings.warn(
            "Input file has no CRS defined. "
            "Assuming SIRGAS2000 (EPSG:4674).",
            UserWarning,
            stacklevel=2,
        )
        gdf = gdf.set_crs(SIRGAS2000_CRS)
    elif not gdf.crs.equals(SIRGAS2000_CRS):
        gdf = gdf.to_crs(SIRGAS2000_CRS)

    # ------------------------------------------------------------------
    # 5. Repair geometries
    # ------------------------------------------------------------------
    gdf = gdf.copy()
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: make_valid(g) if g is not None else None
    )
    gdf = gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty].copy()

    # ------------------------------------------------------------------
    # 6. Enforce strict geometry-type homogeneity
    # ------------------------------------------------------------------
    def _extract(geom, family: str):
        """
        Recursively extract only sub-geometries belonging to *family*
        from *geom*. Returns ``None`` if no matching part exists.

        After ``make_valid``, a self-intersecting polygon may become a
        ``GeometryCollection`` containing both valid polygons and
        degenerate points or lines. This function keeps only the parts
        that match the target family, then packs them into the
        appropriate ``Multi*`` type when there is more than one part.

        Parameters
        ----------
        geom : shapely geometry or None
            Input geometry (possibly a ``GeometryCollection``).
        family : str
            One of ``"polygon"``, ``"line"``, or ``"point"``.

        Returns
        -------
        shapely geometry or None
        """
        if geom is None or geom.is_empty:
            return None

        single_name, multi_name = _TYPE_NAMES[family]
        single_cls, multi_cls  = _SINGLE_MULTI[family]
        geom_type = geom.geom_type

        # Already the correct type
        if geom_type in (single_name, multi_name):
            return geom

        # Recursively unpack GeometryCollections (e.g., produced by make_valid)
        if geom_type == "GeometryCollection":
            parts = [_extract(sub, family) for sub in geom.geoms]
            parts = [p for p in parts if p is not None and not p.is_empty]
            if not parts:
                return None

            # Flatten all parts into a list of single geometries
            singles: list = []
            for p in parts:
                ptype = p.geom_type
                if ptype == single_name:
                    singles.append(p)
                elif ptype == multi_name:
                    singles.extend(p.geoms)

            if not singles:
                return None
            if len(singles) == 1:
                return singles[0]

            return multi_cls(singles)

        # Incompatible geometry type -- discard
        return None

    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: _extract(g, target_family)
    )
    gdf = gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty].copy()
    n_written = len(gdf)

    # ------------------------------------------------------------------
    # 7. Compute 25 x 25 km tile IDs in the metric projected CRS
    # ------------------------------------------------------------------
    # Project geometries to EPSG:5880 (meters) for tile and Hilbert
    # computations. The EPSG:4674 geometry column is untouched.
    geom_proj = gdf["geometry"].to_crs(BRAZIL_METRIC_CRS)

    # Use representative_point() instead of centroid: the representative
    # point is guaranteed to lie inside (or on the boundary of) the
    # geometry, even for concave polygons or curved lines, whereas
    # centroid may fall outside.
    rep_pts = geom_proj.representative_point()

    tile_col = np.floor(rep_pts.x / tile_size_m).astype(np.int32)
    tile_row = np.floor(rep_pts.y / tile_size_m).astype(np.int32)

    # Store tile columns as int32 and a compact categorical tile_id.
    # Categorical dtype -> dictionary encoding in Parquet -> smaller file.
    gdf["tile_col"] = tile_col.values
    gdf["tile_row"] = tile_row.values
    gdf["tile_id"]  = (
        tile_col.astype(str) + "_" + tile_row.astype(str)
    ).astype("category")

    # ------------------------------------------------------------------
    # 8. Sort rows by Hilbert curve order (spatial locality)
    # ------------------------------------------------------------------
    # Hilbert curve ordering ensures that spatially adjacent features
    # share Parquet row groups. When DuckDB evaluates a spatial intersect,
    # it first checks per-row-group bbox statistics (xmin/xmax/ymin/ymax)
    # and skips entire row groups whose bounding boxes do not overlap the
    # query geometry. With Hilbert ordering, each row group covers a small
    # spatial area, so most row groups are skipped before any WKB geometry
    # is deserialized.
    #
    # Note: _hilbert_sort_key uses the bounding box of each geometry
    # (not its centroid), so polygon rings, line vertices, and point
    # coordinates all contribute correctly to the sort key.
    total_bounds = geom_proj.total_bounds   # (minx, miny, maxx, maxy) in m
    hilbert_idx = _hilbert_sort_key(
        geom_proj,
        total_bounds,
        p=hilbert_p,
    )
    del geom_proj, rep_pts, tile_col, tile_row

    gdf["_hilbert_sort"] = hilbert_idx
    gdf = (
        gdf.sort_values("_hilbert_sort")
           .drop(columns=["_hilbert_sort"])
           .reset_index(drop=True)
    )

    # Cast tile columns after sort reset
    gdf["tile_col"] = gdf["tile_col"].astype(np.int32)
    gdf["tile_row"] = gdf["tile_row"].astype(np.int32)

    # ------------------------------------------------------------------
    # 9. Write GeoParquet
    # ------------------------------------------------------------------
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    write_kwargs: dict = dict(
        engine="pyarrow",
        compression=compression,
        index=False,
        row_group_size=row_group_size,
        schema_version="1.1.0",   # GeoParquet 1.1 -- native bbox column
    )

    # write_covering_bbox adds a per-row ``bbox`` struct column
    # {xmin, ymin, xmax, ymax} that DuckDB Spatial uses for fast
    # pre-filtering without deserializing WKB geometry bytes.
    try:
        gdf.to_parquet(output_path, write_covering_bbox=True, **write_kwargs)
    except TypeError:
        # Fallback for older geopandas versions that do not support
        # write_covering_bbox
        gdf.to_parquet(output_path, **write_kwargs)

    # Apply compression level via a pyarrow rewrite when needed, because
    # geopandas does not expose compression_level directly.
    if compression == "zstd" and compression_level != 3:
        table = pq.read_table(output_path)
        pq.write_table(
            table,
            output_path,
            compression=compression,
            compression_level=compression_level,
            row_group_size=row_group_size,
        )

    # ------------------------------------------------------------------
    # 10. Build and print conversion report
    # ------------------------------------------------------------------
    bounds = gdf.total_bounds   # (minx, miny, maxx, maxy) in EPSG:4674
    file_size_mb = os.path.getsize(output_path) / 1_048_576

    report: dict = {
        "input_path":      input_path,
        "output_path":     output_path,
        "input_crs":       input_crs,
        "output_crs":      SIRGAS2000_CRS,
        "geometry_family": target_family,
        "n_features_in":   n_original,
        "n_features_out":  n_written,
        "n_dropped":       n_original - n_written,
        "tile_size_km":    tile_size_m / 1_000,
        "n_tiles":         int(gdf["tile_id"].nunique()),
        "hilbert_p":       hilbert_p,
        "row_group_size":  row_group_size,
        "compression":     f"{compression}:{compression_level}",
        "bbox": {
            "xmin": float(bounds[0]),
            "ymin": float(bounds[1]),
            "xmax": float(bounds[2]),
            "ymax": float(bounds[3]),
        },
        "file_size_mb":    round(file_size_mb, 3),
    }

    _w = 24
    _sep = "-" * 62
    print(_sep)
    print("  vector_to_geoparquet -- conversion complete")
    print(_sep)
    for k, v in report.items():
        print(f"  {k:<{_w}}: {v}")
    print(_sep)
    print(
        "\n  DuckDB spatial intersect pattern:\n\n"
        "    LOAD spatial;\n\n"
        "    -- The bbox struct pre-filters row groups without reading WKB.\n"
        "    -- ST_Intersects is called on the actual polygon/line geometry.\n"
        f"    SELECT a.*, b.col\n"
        f"    FROM read_parquet('{output_path}') a\n"
        f"    JOIN read_parquet('other_layer.parquet') b\n"
        f"      ON  a.bbox.xmin <= b.bbox.xmax\n"
        f"      AND a.bbox.xmax >= b.bbox.xmin\n"
        f"      AND a.bbox.ymin <= b.bbox.ymax\n"
        f"      AND a.bbox.ymax >= b.bbox.ymin\n"
        f"      AND ST_Intersects(\n"
        f"            ST_GeomFromWKB(a.geometry),\n"
        f"            ST_GeomFromWKB(b.geometry)\n"
        f"          );\n"
        f"\n"
        f"    -- Aggregate by 25 km tile:\n"
        f"    -- SELECT tile_id, COUNT(*) FROM read_parquet(...) GROUP BY tile_id;\n"
    )

    return report


# ----------------------------------------------------------------------
# Command-line interface
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    _USAGE = (
        "Usage:\n"
        "  python vector_to_geoparquet.py <input> <output.parquet> [layer]\n\n"
        "Examples:\n"
        "  python vector_to_geoparquet.py municipalities.shp municipalities.parquet\n"
        "  python vector_to_geoparquet.py data.gpkg properties.parquet car_properties\n"
        "  python vector_to_geoparquet.py biomes.geojson biomes.parquet\n"
    )

    if len(sys.argv) < 3:
        print(_USAGE)
        sys.exit(1)

    convert_to_geoparquet(
        input_path=sys.argv[1],
        output_path=sys.argv[2],
        layer=sys.argv[3] if len(sys.argv) > 3 else None,
    )


def _cli() -> None:
    """Entry point for the ``vector-to-geoparquet`` console script."""
    import sys

    _USAGE = (
        "Usage:\n"
        "  vector-to-geoparquet <input> <output.parquet> [layer]\n\n"
        "Examples:\n"
        "  vector-to-geoparquet municipalities.shp municipalities.parquet\n"
        "  vector-to-geoparquet data.gpkg properties.parquet car_properties\n"
        "  vector-to-geoparquet biomes.geojson biomes.parquet\n"
    )

    if len(sys.argv) < 3:
        print(_USAGE)
        sys.exit(1)

    convert_to_geoparquet(
        input_path=sys.argv[1],
        output_path=sys.argv[2],
        layer=sys.argv[3] if len(sys.argv) > 3 else None,
    )
