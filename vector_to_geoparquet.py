"""vector_to_geoparquet.py
=========================
**Brazil-specific** utility to convert any vector file with coverage over
Brazilian territory to a DuckDB-optimized GeoParquet file.

Geographic scope
----------------
Output CRS : SIRGAS 2000 / Brazil Polyconic -- EPSG:5880  (metres, IBGE-mandated
             for area calculation per Resolution R.PR-1/2005)
Input norm : SIRGAS 2000 geographic -- EPSG:4674  (intermediate step only)

    pip install geopandas pyogrio pyarrow shapely numpy
    python vector_to_geoparquet.py <input> <output.parquet> [layer]
"""

from __future__ import annotations

__version__ = "1.2.0"


def convert_to_geoparquet(
    input_path: str,
    output_path: str,
    layer:             str | None = None,
    tile_size_m:       float      = 25_000.0,
    row_group_size:    int        = 65_536,
    compression:       str        = "zstd",
    compression_level: int        = 3,
    hilbert_p:         int        = 15,
) -> dict:
    """Convert a Brazil-extent vector file to a DuckDB-optimized GeoParquet.

    Parameters
    ----------
    input_path : str
        Path to the input vector file (any pyogrio-supported format).
    output_path : str
        Path to the output ``.parquet`` file.
    layer : str, optional
        Layer name for multi-layer formats (GeoPackage, etc.).
    tile_size_m : float
        Tile edge length in metres.  Default 25 000 m (25 km).
    row_group_size : int
        Rows per Parquet row group.  Default 65 536.
    compression : str
        Parquet compression codec.  Default ``"zstd"``.
    compression_level : int
        ZSTD compression level (1–22).  Default 3.
    hilbert_p : int
        Hilbert curve resolution.  Default 15 (~150 m cells over Brazil).

    Returns
    -------
    dict
        Conversion report with paths, CRS, feature counts, tile count,
        bounding box, and output file size.
    """

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------
    import os
    import warnings

    import numpy as np
    import geopandas as gpd
    from shapely import make_valid
    from shapely.geometry import (
        LineString, MultiLineString,
        Point, MultiPoint,
        Polygon, MultiPolygon,
    )

    # Hilbert distance: Shapely ≥ 2.0 vectorised API; NumPy fallback otherwise.
    try:
        from shapely import hilbert_distance

        def _hilbert(gs, bounds, p):
            return hilbert_distance(gs, bounds, p=p)

    except ImportError:

        def _d(n: int, x: int, y: int) -> int:
            d, s = 0, n >> 1
            while s:
                rx, ry = int(bool(x & s)), int(bool(y & s))
                d += s * s * ((3 * rx) ^ ry)
                if not ry:
                    if rx:
                        x, y = s - 1 - x, s - 1 - y
                    x, y = y, x
                s >>= 1
            return d

        def _hilbert(gs, bounds, p):  # type: ignore[misc]
            n = 2 ** p
            x0, y0, x1, y1 = bounds
            dx, dy = x1 - x0 or 1.0, y1 - y0 or 1.0
            b  = np.array([g.bounds for g in gs])
            cx = (b[:, 0] + b[:, 2]) / 2.0
            cy = (b[:, 1] + b[:, 3]) / 2.0
            xi = np.clip(((cx - x0) / dx * (n - 1)).astype(np.int64), 0, n - 1)
            yi = np.clip(((cy - y0) / dy * (n - 1)).astype(np.int64), 0, n - 1)
            return np.array(
                [_d(n, int(x), int(y)) for x, y in zip(xi, yi)], dtype=np.int64
            )

    # ------------------------------------------------------------------
    # Constants
    # ------------------------------------------------------------------
    CRS_GEO    = "EPSG:4674"   # SIRGAS 2000 geographic (input normalisation only)
    CRS_METRIC = "EPSG:5880"   # SIRGAS 2000 / Brazil Polyconic — OUTPUT CRS
                               # IBGE R.PR-1/2005: mandatory for area calculation

    FAMILY = {
        "Point": "point",          "MultiPoint": "point",
        "LineString": "line",      "MultiLineString": "line",
        "Polygon": "polygon",      "MultiPolygon": "polygon",
    }
    GEOM_TYPES = {
        "point":   ("Point",      "MultiPoint",      Point,      MultiPoint),
        "line":    ("LineString", "MultiLineString",  LineString, MultiLineString),
        "polygon": ("Polygon",    "MultiPolygon",     Polygon,    MultiPolygon),
    }

    # ------------------------------------------------------------------
    # 1. Read
    # ------------------------------------------------------------------
    kw: dict = {"engine": "pyogrio"}
    if layer is not None:
        kw["layer"] = layer

    gdf    = gpd.read_file(input_path, **kw)
    n_in   = len(gdf)
    in_crs = str(gdf.crs) if gdf.crs is not None else "undefined"

    if gdf.empty:
        raise ValueError("Input file contains no features.")

    # ------------------------------------------------------------------
    # 2. Dominant geometry family
    # ------------------------------------------------------------------
    counts = (
        gdf.geom_type.dropna()
        .map(lambda t: FAMILY.get(t, "other"))
        .value_counts()
    )
    counts = counts[counts.index != "other"]
    if counts.empty:
        raise ValueError("Cannot determine geometry type.")
    family: str = counts.index[0]

    # ------------------------------------------------------------------
    # 3. Normalise to EPSG:4674 → repair → reproject to EPSG:5880
    #
    # Geometry repair (make_valid) is applied in geographic space
    # (EPSG:4674) before the final reproject to the output CRS
    # (EPSG:5880 — SIRGAS 2000 / Brazil Polyconic, unit: metres).
    # ------------------------------------------------------------------
    if gdf.crs is None:
        warnings.warn("No CRS defined — assuming EPSG:4674.", UserWarning, stacklevel=2)
        gdf = gdf.set_crs(CRS_GEO)
    elif not gdf.crs.equals(CRS_GEO):
        gdf = gdf.to_crs(CRS_GEO)

    # ------------------------------------------------------------------
    # 4. Repair geometries (Shapely 2.0 vectorised)
    # ------------------------------------------------------------------
    gdf = gdf.copy()
    gdf["geometry"] = make_valid(gdf["geometry"].values)
    gdf = gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty].copy()

    # ------------------------------------------------------------------
    # 5. Enforce geometry-type homogeneity
    # ------------------------------------------------------------------
    sname, mname, _, mcls = GEOM_TYPES[family]

    def _extract(geom):
        if geom is None or geom.is_empty:
            return None
        gt = geom.geom_type
        if gt in (sname, mname):
            return geom
        if gt == "GeometryCollection":
            parts   = [_extract(g) for g in geom.geoms]
            singles = []
            for p in (p for p in parts if p is not None and not p.is_empty):
                singles.extend(p.geoms) if p.geom_type == mname else singles.append(p)
            if not singles:
                return None
            return singles[0] if len(singles) == 1 else mcls(singles)
        return None

    gdf["geometry"] = gdf["geometry"].apply(_extract)
    gdf = gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty].copy()
    n_out = len(gdf)

    # Reproject to output CRS (EPSG:5880) after repair is complete.
    gdf = gdf.to_crs(CRS_METRIC)

    # ------------------------------------------------------------------
    # 6. 25 km tile IDs (EPSG:5880)
    # Geometries are already in CRS_METRIC — no additional projection.
    # ------------------------------------------------------------------
    gp   = gdf["geometry"]
    rp   = gp.representative_point()
    tcol = np.floor(rp.x / tile_size_m).astype(np.int32)
    trow = np.floor(rp.y / tile_size_m).astype(np.int32)
    gdf["tile_col"] = tcol.values
    gdf["tile_row"] = trow.values
    gdf["tile_id"]  = (tcol.astype(str) + "_" + trow.astype(str)).astype("category")

    # ------------------------------------------------------------------
    # 7. Hilbert sort (spatial locality for DuckDB row-group pruning)
    # ------------------------------------------------------------------
    gdf["_h"] = _hilbert(gp, gp.total_bounds, hilbert_p)
    del gp, rp, tcol, trow
    gdf = (
        gdf.sort_values("_h")
           .drop(columns=["_h"])
           .reset_index(drop=True)
    )
    gdf["tile_col"] = gdf["tile_col"].astype(np.int32)
    gdf["tile_row"] = gdf["tile_row"].astype(np.int32)

    # ------------------------------------------------------------------
    # 8. Write GeoParquet
    # ------------------------------------------------------------------
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    _kw = dict(
        engine="pyarrow",
        compression=compression,
        compression_level=compression_level,
        index=False,
        row_group_size=row_group_size,
    )
    try:
        gdf.to_parquet(output_path, write_covering_bbox=True,
                       schema_version="1.1.0", **_kw)
    except TypeError:
        try:
            gdf.to_parquet(output_path, schema_version="1.1.0", **_kw)
        except TypeError:
            gdf.to_parquet(output_path, **_kw)

    # ------------------------------------------------------------------
    # 9. Report
    # ------------------------------------------------------------------
    bounds = gdf.total_bounds
    report = dict(
        input_path=input_path,
        output_path=output_path,
        input_crs=in_crs,
        output_crs=CRS_METRIC,
        geometry_family=family,
        n_features_in=n_in,
        n_features_out=n_out,
        n_dropped=n_in - n_out,
        tile_size_km=tile_size_m / 1_000,
        n_tiles=int(gdf["tile_id"].nunique()),
        hilbert_p=hilbert_p,
        row_group_size=row_group_size,
        compression=f"{compression}:{compression_level}",
        bbox=dict(
            xmin=float(bounds[0]), ymin=float(bounds[1]),
            xmax=float(bounds[2]), ymax=float(bounds[3]),
        ),
        file_size_mb=round(os.path.getsize(output_path) / 1_048_576, 3),
    )

    sep = "-" * 62
    print(f"\n{sep}\n  vector_to_geoparquet v{__version__} — conversion complete\n{sep}")
    for k, v in report.items():
        print(f"  {k:<22}: {v}")
    print(sep)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    """Entry point for the ``vector-to-geoparquet`` console script."""
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: vector-to-geoparquet <input> <output.parquet> [layer]\n\n"
            "Examples:\n"
            "  vector-to-geoparquet municipalities.shp municipalities.parquet\n"
            "  vector-to-geoparquet data.gpkg properties.parquet car_properties\n"
            "  vector-to-geoparquet biomes.geojson biomes.parquet\n"
        )
        sys.exit(1)

    convert_to_geoparquet(
        input_path=sys.argv[1],
        output_path=sys.argv[2],
        layer=sys.argv[3] if len(sys.argv) > 3 else None,
    )


if __name__ == "__main__":
    _cli()
