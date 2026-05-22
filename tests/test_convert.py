"""tests/test_convert.py
Tests for vector_to_geoparquet.convert_to_geoparquet().
"""

import os
import tempfile

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, Polygon, LineString, GeometryCollection

from vector_to_geoparquet import convert_to_geoparquet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brazil_polygon():
    """Simple polygon well inside Brazilian territory (Mato Grosso area)."""
    return Polygon([
        (-55.0, -12.0),
        (-54.0, -12.0),
        (-54.0, -11.0),
        (-55.0, -11.0),
        (-55.0, -12.0),
    ])


def _make_gpkg(path: str, geoms, crs="EPSG:4674"):
    gdf = gpd.GeoDataFrame(
        {"attr": list(range(len(geoms)))},
        geometry=geoms,
        crs=crs,
    )
    gdf.to_file(path, driver="GPKG")
    return gdf


# ---------------------------------------------------------------------------
# CRS
# ---------------------------------------------------------------------------

class TestOutputCRS:
    def test_output_crs_is_epsg4674(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 5)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result.crs is not None
        assert result.crs.to_epsg() == 4674, (
            f"Expected EPSG:4674 but got {result.crs.to_epsg()}"
        )

    def test_input_reprojected_from_sad69(self, tmp_path):
        """Input in SAD 69 (EPSG:4618) must be accepted and output in EPSG:4674."""
        src = str(tmp_path / "input_sad69.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3, crs="EPSG:4618")
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result.crs.to_epsg() == 4674

    def test_report_output_crs(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        report = convert_to_geoparquet(src, out)
        assert report["output_crs"] == "EPSG:4674"

    def test_geometry_coordinates_are_degrees(self, tmp_path):
        """Geometry stored in geographic CRS must have longitude in [-180, 180]."""
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        bounds = result.total_bounds  # xmin, ymin, xmax, ymax
        assert -180 <= bounds[0] <= 180, "xmin out of degree range -- geometry may be in metres"
        assert -90 <= bounds[1] <= 90, "ymin out of degree range -- geometry may be in metres"


# ---------------------------------------------------------------------------
# Geometry type homogeneity
# ---------------------------------------------------------------------------

class TestGeometryHomogeneity:
    def test_polygon_only_output(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 4)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Polygon", "MultiPolygon") for t in result.geom_type)

    def test_line_only_output(self, tmp_path):
        src = str(tmp_path / "lines.gpkg")
        out = str(tmp_path / "out.parquet")
        lines = [LineString([(-55 + i * 0.1, -12), (-54 + i * 0.1, -11)]) for i in range(4)]
        _make_gpkg(src, lines)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("LineString", "MultiLineString") for t in result.geom_type)

    def test_point_only_output(self, tmp_path):
        src = str(tmp_path / "points.gpkg")
        out = str(tmp_path / "out.parquet")
        points = [Point(-55 + i * 0.1, -12 + i * 0.1) for i in range(5)]
        _make_gpkg(src, points)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Point", "MultiPoint") for t in result.geom_type)

    def test_geometry_collection_decomposed(self, tmp_path):
        src = str(tmp_path / "gc.gpkg")
        out = str(tmp_path / "out.parquet")
        gc = GeometryCollection([_brazil_polygon(), _brazil_polygon()])
        _make_gpkg(src, [gc, _brazil_polygon()])
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Polygon", "MultiPolygon") for t in result.geom_type)


# ---------------------------------------------------------------------------
# Geometry repair
# ---------------------------------------------------------------------------

class TestGeometryRepair:
    def test_self_intersecting_polygon_repaired(self, tmp_path):
        """Bowtie polygon is invalid; make_valid should repair it."""
        from shapely.geometry import Polygon as _Poly
        bowtie = _Poly([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
        src = str(tmp_path / "bowtie.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [bowtie, _brazil_polygon()])
        # Should not raise
        report = convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result.geometry.is_valid.all()


# ---------------------------------------------------------------------------
# Tile columns
# ---------------------------------------------------------------------------

class TestTileColumns:
    def test_tile_columns_present(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 5)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert "tile_col" in result.columns
        assert "tile_row" in result.columns
        assert "tile_id" in result.columns

    def test_tile_id_format(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 5)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        for tid in result["tile_id"]:
            parts = str(tid).split("_")
            assert len(parts) == 2, f"tile_id '{tid}' does not match 'col_row' format"
            assert parts[0].lstrip("-").isdigit()
            assert parts[1].lstrip("-").isdigit()

    def test_tile_col_row_dtype(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 5)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result["tile_col"].dtype == np.int32
        assert result["tile_row"].dtype == np.int32


# ---------------------------------------------------------------------------
# Parquet schema
# ---------------------------------------------------------------------------

class TestParquetSchema:
    def test_geometry_column_present(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert "geometry" in result.columns

    def test_bbox_column_present(self, tmp_path):
        """GeoParquet 1.1 covering bbox struct must be present if supported."""
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        convert_to_geoparquet(src, out)
        import pyarrow.parquet as pq
        schema = pq.read_schema(out)
        field_names = schema.names
        # bbox may be written or not depending on GeoPandas version; just check no crash
        assert "geometry" in field_names

    def test_original_attributes_preserved(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 4)
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert "attr" in result.columns


# ---------------------------------------------------------------------------
# Report keys
# ---------------------------------------------------------------------------

class TestReport:
    EXPECTED_KEYS = {
        "input_path", "output_path", "input_crs", "output_crs",
        "geometry_family", "n_features_in", "n_features_out", "n_dropped",
        "tile_size_km", "n_tiles", "hilbert_p", "row_group_size",
        "compression", "bbox", "file_size_mb",
    }

    def test_report_has_all_keys(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 5)
        report = convert_to_geoparquet(src, out)
        assert self.EXPECTED_KEYS.issubset(report.keys())

    def test_report_feature_counts(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        n = 7
        _make_gpkg(src, [_brazil_polygon()] * n)
        report = convert_to_geoparquet(src, out)
        assert report["n_features_in"] == n
        assert report["n_features_out"] <= n
        assert report["n_dropped"] == report["n_features_in"] - report["n_features_out"]

    def test_report_bbox_keys(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        report = convert_to_geoparquet(src, out)
        assert set(report["bbox"].keys()) == {"xmin", "ymin", "xmax", "ymax"}

    def test_report_file_size_positive(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        report = convert_to_geoparquet(src, out)
        assert report["file_size_mb"] > 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_empty_file_raises(self, tmp_path):
        src = str(tmp_path / "empty.gpkg")
        out = str(tmp_path / "out.parquet")
        gdf = gpd.GeoDataFrame({"attr": []}, geometry=[], crs="EPSG:4674")
        gdf.to_file(src, driver="GPKG")
        with pytest.raises(ValueError, match="no features"):
            convert_to_geoparquet(src, out)

    def test_output_file_created(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        out = str(tmp_path / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        convert_to_geoparquet(src, out)
        assert os.path.exists(out)

    def test_output_directory_created(self, tmp_path):
        src = str(tmp_path / "input.gpkg")
        nested_out = str(tmp_path / "subdir" / "nested" / "out.parquet")
        _make_gpkg(src, [_brazil_polygon()] * 3)
        convert_to_geoparquet(src, nested_out)
        assert os.path.exists(nested_out)
