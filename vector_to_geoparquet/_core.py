"""_core.py -- main conversion function and CLI entry point."""

from __future__ import annotations

import os
import sys

import geopandas as gpd
import numpy as np

from ._constants import CRS_GEO, CRS_OUT, __version__
from ._geometry import (
    detect_family,
    enforce_homogeneity,
    normalise_crs,
    repair,
)
from ._hilbert import hilbert


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
    """Convert a Brazil-extent vector file to a DuckDB-optimized GeoParquet.

    Parameters
    ----------
    input_path : str
        Path to the input vector file (any pyogrio-supported format).
    output_path : str
        Path to the output ``.parquet`` file.
    layer : str, optional
        Layer name or index for multi-layer formats (GeoPackage, etc.).
    tile_size_m : float
        Tile edge length in metres. Default 25 000 m (25 km).
    row_group_size : int
        Rows per Parquet row group. Default 65 536.
    compression : str
        Parquet compression codec. Default ``"zstd"``.
    compression_level : int
        ZSTD compression level (1-22). Default 3.
    hilbert_p : int
        Hilbert curve resolution. Default 15 (~150 m cells over Brazil).

    Returns
    -------
    dict
        Conversion report with paths, CRS, feature counts, tile statistics,
        bounding box, and output file size.

    Notes
    -----
    **Output CRS:** EPSG:5880 (SIRGAS 2000 / Brazil Polyconic, unit: metres),
    per IBGE Resolution R.PR-1/2005. All geometry, tile IDs, and Hilbert
    ordering are in this CRS.

    **Tile assignment** uses each feature's ``representative_point``. For
    features spanning more than one 25 km tile, ``tile_id`` reflects the tile
    containing the representative point, not the full spatial extent.
    """

    # ------------------------------------------------------------------
    # 1. Read
    # ------------------------------------------------------------------
    kw: dict = {"engine": "pyogrio"}
    if layer is not None:
        kw["layer"] = layer

    gdf = gpd.read_file(input_path, **kw)
    n_in = len(gdf)
    in_crs = str(gdf.crs) if gdf.crs is not None else "undefined"

    if gdf.empty:
        raise ValueError("Input file contains no features.")

    # ------------------------------------------------------------------
    # 2. Geometry pipeline: family -> normalise -> repair -> homogeneity
    # ------------------------------------------------------------------
    family = detect_family(gdf)
    gdf = normalise_crs(gdf)        # -> EPSG:4674
    gdf = repair(gdf)
    gdf = enforce_homogeneity(gdf, family)
    n_out = len(gdf)

    # ------------------------------------------------------------------
    # 3. Reproject to output CRS (EPSG:5880 -- metres)
    # ------------------------------------------------------------------
    gdf = gdf.to_crs(CRS_OUT)

    # ------------------------------------------------------------------
    # 4. Tile IDs (25 km grid in CRS_OUT)
    # ------------------------------------------------------------------
    gp = gdf["geometry"]
    rp = gp.representative_point()
    tcol = np.floor(rp.x / tile_size_m).astype(np.int32)
    trow = np.floor(rp.y / tile_size_m).astype(np.int32)

    gdf["tile_col"] = tcol.values
    gdf["tile_row"] = trow.values
    gdf["tile_id"] = (tcol.astype(str) + "_" + trow.astype(str)).astype("category")

    # ------------------------------------------------------------------
    # 5. Hilbert sort for DuckDB row-group pruning
    # ------------------------------------------------------------------
    gdf["_h"] = hilbert(gp, gp.total_bounds, hilbert_p)
    del gp, rp, tcol, trow

    gdf = (
        gdf.sort_values("_h")
        .drop(columns=["_h"])
        .reset_index(drop=True)
    )
    gdf["tile_col"] = gdf["tile_col"].astype(np.int32)
    gdf["tile_row"] = gdf["tile_row"].astype(np.int32)

    # ------------------------------------------------------------------
    # 6. Write GeoParquet 1.1
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
        gdf.to_parquet(
            output_path, write_covering_bbox=True, schema_version="1.1.0", **_kw
        )
    except TypeError:
        try:
            gdf.to_parquet(output_path, schema_version="1.1.0", **_kw)
        except TypeError:
            gdf.to_parquet(output_path, **_kw)

    # ------------------------------------------------------------------
    # 7. Report
    # ------------------------------------------------------------------
    bounds = gdf.total_bounds
    report = dict(
        input_path=input_path,
        output_path=output_path,
        input_crs=in_crs,
        output_crs=CRS_OUT,
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
            xmin=float(bounds[0]),
            ymin=float(bounds[1]),
            xmax=float(bounds[2]),
            ymax=float(bounds[3]),
        ),
        file_size_mb=round(os.path.getsize(output_path) / 1_048_576, 3),
    )

    sep = "-" * 62
    print(
        f"\n{sep}\n vector_to_geoparquet v{__version__} -- conversion complete\n{sep}"
    )
    for k, v in report.items():
        print(f"  {k:<22}: {v}")
    print(sep)

    return report


def _cli() -> None:
    """Entry point for the ``vector-to-geoparquet`` console script."""
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
