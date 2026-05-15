"""
tests/test_convert.py
=====================
Unit tests for convert_to_geoparquet.

Run with:
    pip install pytest geopandas pyogrio pyarrow shapely numpy
    pytest tests/
"""

import os
import tempfile

import numpy as np
import pytest
import geopandas as gpd
import pyarrow.parquet as pq
from shapely.geometry import (
    Point, MultiPoint,
    LineString, MultiLineString,
    Polygon, MultiPolygon,
    GeometryCollection,
)

# Add parent directory to path so the module is importable without install
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vector_to_geoparquet import convert_to_geoparquet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIRGAS2000 = "EPSG:4674"

def _write_tmp(gdf: gpd.GeoDataFrame, suffix: str = ".gpkg") -> str:
    """Write a GeoDataFrame to a temporary file and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    gdf.to_file(tmp.name, driver="GPKG" if suffix == ".gpkg" else "GeoJSON")
    return tmp.name


def _read_report(output_path: str) -> gpd.GeoDataFrame:
    """Read output GeoParquet back into a GeoDataFrame."""
    return gpd.read_parquet(output_path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def polygon_gdf():
    geoms = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(2, 2), (3, 2), (3, 3), (2, 3)]),
        MultiPolygon([
            Polygon([(4, 4), (5, 4), (5, 5), (4, 5)]),
            Polygon([(6, 6), (7, 6), (7, 7), (6, 7)]),
        ]),
    ]
    return gpd.GeoDataFrame({"id": [1, 2, 3], "geometry": geoms}, crs=SIRGAS2000)


@pytest.fixture()
def line_gdf():
    geoms = [
        LineString([(0, 0), (1, 1), (2, 0)]),
        MultiLineString([[(3, 0), (4, 1)], [(5, 0), (6, 1)]]),
    ]
    return gpd.GeoDataFrame({"id": [1, 2], "geometry": geoms}, crs=SIRGAS2000)


@pytest.fixture()
def point_gdf():
    geoms = [Point(-50, -15), Point(-45, -10), MultiPoint([(-40, -5), (-35, 0)])]
    return gpd.GeoDataFrame({"id": [1, 2, 3], "geometry": geoms}, crs=SIRGAS2000)


@pytest.fixture()
def invalid_polygon_gdf():
    """Self-intersecting (bowtie) polygon that requires make_valid."""
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    valid  = Polygon([(5, 5), (6, 5), (6, 6), (5, 6)])
    return gpd.GeoDataFrame(
        {"id": [1, 2], "geometry": [bowtie, valid]}, crs=SIRGAS2000
    )


@pytest.fixture()
def mixed_gdf():
    """Mixed geometry types -- polygon should dominate."""
    geoms = [
        Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        Polygon([(2, 2), (3, 2), (3, 3), (2, 3)]),
        Point(-50, -15),                               # minority type
    ]
    return gpd.GeoDataFrame({"id": [1, 2, 3], "geometry": geoms}, crs=SIRGAS2000)


@pytest.fixture()
def reprojection_gdf():
    """GeoDataFrame in WGS84 (EPSG:4326) to test reprojection."""
    geoms = [Polygon([(-50, -15), (-49, -15), (-49, -14), (-50, -14)])]
    return gpd.GeoDataFrame({"id": [1], "geometry": geoms}, crs="EPSG:4326")


# ---------------------------------------------------------------------------
# Tests: output CRS
# ---------------------------------------------------------------------------

def test_output_crs_is_sirgas2000(polygon_gdf):
    src = _write_tmp(polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result.crs.to_epsg() == 4674
    finally:
        os.unlink(src)
        os.unlink(out)


def test_reprojection_from_wgs84(reprojection_gdf):
    src = _write_tmp(reprojection_gdf, suffix=".geojson")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result.crs.to_epsg() == 4674
    finally:
        os.unlink(src)
        os.unlink(out)


# ---------------------------------------------------------------------------
# Tests: geometry type homogeneity
# ---------------------------------------------------------------------------

def test_polygon_output_only_polygons(polygon_gdf):
    src = _write_tmp(polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Polygon", "MultiPolygon") for t in result.geom_type)
    finally:
        os.unlink(src)
        os.unlink(out)


def test_line_output_only_lines(line_gdf):
    src = _write_tmp(line_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("LineString", "MultiLineString") for t in result.geom_type)
    finally:
        os.unlink(src)
        os.unlink(out)


def test_point_output_only_points(point_gdf):
    src = _write_tmp(point_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Point", "MultiPoint") for t in result.geom_type)
    finally:
        os.unlink(src)
        os.unlink(out)


def test_mixed_keeps_dominant_type(mixed_gdf):
    """Point minority feature must be dropped; polygons must survive."""
    src = _write_tmp(mixed_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        report = convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert report["geometry_family"] == "polygon"
        assert all(t in ("Polygon", "MultiPolygon") for t in result.geom_type)
        assert len(result) == 2   # the Point feature was dropped
    finally:
        os.unlink(src)
        os.unlink(out)


# ---------------------------------------------------------------------------
# Tests: geometry repair
# ---------------------------------------------------------------------------

def test_invalid_geometry_is_repaired(invalid_polygon_gdf):
    """Bowtie polygon should be repaired and produce polygon output."""
    src = _write_tmp(invalid_polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        report = convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        # All output geometries must be valid
        assert result.is_valid.all()
        # Must have produced some output
        assert len(result) > 0
    finally:
        os.unlink(src)
        os.unlink(out)


# ---------------------------------------------------------------------------
# Tests: tile columns
# ---------------------------------------------------------------------------

def test_tile_columns_present(polygon_gdf):
    src = _write_tmp(polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        for col in ("tile_id", "tile_col", "tile_row"):
            assert col in result.columns, f"Column '{col}' is missing"
    finally:
        os.unlink(src)
        os.unlink(out)


def test_tile_id_format(polygon_gdf):
    """tile_id must follow the 'col_row' pattern."""
    src = _write_tmp(polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        tile_ids = result["tile_id"].astype(str)
        assert tile_ids.str.match(r"^-?\d+_-?\d+$").all()
    finally:
        os.unlink(src)
        os.unlink(out)


# ---------------------------------------------------------------------------
# Tests: Parquet schema / DuckDB optimization
# ---------------------------------------------------------------------------

def test_parquet_has_row_groups(polygon_gdf):
    src = _write_tmp(polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        convert_to_geoparquet(src, out)
        pf = pq.ParquetFile(out)
        assert pf.metadata.num_row_groups >= 1
    finally:
        os.unlink(src)
        os.unlink(out)


def test_report_keys(polygon_gdf):
    src = _write_tmp(polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        report = convert_to_geoparquet(src, out)
        expected = {
            "input_path", "output_path", "input_crs", "output_crs",
            "geometry_family", "n_features_in", "n_features_out",
            "n_dropped", "tile_size_km", "n_tiles", "hilbert_p",
            "row_group_size", "compression", "bbox", "file_size_mb",
        }
        assert expected.issubset(report.keys())
    finally:
        os.unlink(src)
        os.unlink(out)


def test_feature_count_preserved(polygon_gdf):
    src = _write_tmp(polygon_gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        report = convert_to_geoparquet(src, out)
        assert report["n_features_out"] == len(polygon_gdf)
        assert report["n_dropped"] == 0
    finally:
        os.unlink(src)
        os.unlink(out)


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

def test_raises_on_empty_file():
    gdf = gpd.GeoDataFrame({"geometry": []}, crs=SIRGAS2000)
    src = _write_tmp(gdf)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        out = f.name
    try:
        with pytest.raises(ValueError, match="no features"):
            convert_to_geoparquet(src, out)
    finally:
        os.unlink(src)
        os.unlink(out)
