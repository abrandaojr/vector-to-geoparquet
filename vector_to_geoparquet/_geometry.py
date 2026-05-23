"""_geometry.py -- geometry helpers for vector_to_geoparquet.

Provides four independent, testable steps:
  1. detect_family   -- dominant geometry type (polygon / line / point)
  2. normalise_crs   -- reproject any input to CRS_GEO (EPSG:4674)
  3. repair          -- fix invalid geometries with shapely.make_valid
  4. enforce_homogeneity -- drop or decompose mixed / collection geometries
"""

from __future__ import annotations

import warnings

import geopandas as gpd
from shapely import make_valid
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from ._constants import CRS_GEO, FAMILY

# Maps family name to (single_type, multi_type, single_cls, multi_cls).
GEOM_TYPES: dict[str, tuple] = {
    "point": ("Point", "MultiPoint", Point, MultiPoint),
    "line": ("LineString", "MultiLineString", LineString, MultiLineString),
    "polygon": ("Polygon", "MultiPolygon", Polygon, MultiPolygon),
}


def detect_family(gdf: gpd.GeoDataFrame) -> str:
    """Return the dominant geometry family ('polygon', 'line', or 'point').

    Raises
    ------
    ValueError
        If no recognisable geometry type is present.
    """
    counts = (
        gdf.geom_type.dropna()
        .map(lambda t: FAMILY.get(t, "other"))
        .value_counts()
    )
    counts = counts[counts.index != "other"]
    if counts.empty:
        raise ValueError(
            "Cannot determine geometry type: no Point, Line, or Polygon geometries found."
        )
    return str(counts.index[0])


def normalise_crs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject *gdf* to CRS_GEO (EPSG:4674).

    If the input has no CRS, EPSG:4674 is assumed with a warning.
    """
    if gdf.crs is None:
        warnings.warn(
            "Input has no CRS -- assuming EPSG:4674 (SIRGAS 2000 geographic).",
            UserWarning,
            stacklevel=3,
        )
        return gdf.set_crs(CRS_GEO)
    if not gdf.crs.equals(CRS_GEO):
        return gdf.to_crs(CRS_GEO)
    return gdf


def repair(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Repair invalid geometries and drop empty / null results.

    Uses ``shapely.make_valid`` (vectorised, Shapely 2.0+).
    """
    gdf = gdf.copy()
    gdf["geometry"] = make_valid(gdf["geometry"].values)
    return gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty].copy()


def enforce_homogeneity(gdf: gpd.GeoDataFrame, family: str) -> gpd.GeoDataFrame:
    """Keep only geometries that belong to *family*; decompose GeometryCollections.

    Parameters
    ----------
    gdf : GeoDataFrame
        Input data (may contain mixed geometry types).
    family : str
        Target family: ``'polygon'``, ``'line'``, or ``'point'``.

    Returns
    -------
    GeoDataFrame
        Filtered / decomposed GeoDataFrame with only the target geometry type.
    """
    sname, mname, _, mcls = GEOM_TYPES[family]

    def _extract(geom):
        if geom is None or geom.is_empty:
            return None
        gt = geom.geom_type
        if gt in (sname, mname):
            return geom
        if gt == "GeometryCollection":
            parts = [_extract(g) for g in geom.geoms]
            singles: list = []
            for p in (p for p in parts if p is not None and not p.is_empty):
                singles.extend(p.geoms) if p.geom_type == mname else singles.append(p)
            if not singles:
                return None
            return singles[0] if len(singles) == 1 else mcls(singles)
        return None

    gdf = gdf.copy()
    gdf["geometry"] = gdf["geometry"].apply(_extract)
    return gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty].copy()
