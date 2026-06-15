"""_constants.py -- shared constants for vector_to_geoparquet."""

from __future__ import annotations

__version__ = "1.4.1"

# Intermediate CRS: all inputs are normalised here before reprojection.
CRS_GEO = "EPSG:4674"  # SIRGAS 2000 geographic

# Output CRS: SIRGAS 2000 / Brazil Polyconic (unit: metres).
# IBGE-mandated for area calculation per Resolution R.PR-1/2005.
# Tile IDs, Hilbert ordering, and stored geometry all use this CRS.
CRS_OUT = "EPSG:5880"

# Maps each Shapely geometry type string to its canonical family name.
FAMILY: dict[str, str] = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "line",
    "MultiLineString": "line",
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
}
