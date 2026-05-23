"""tests/test_convert.py
Tests for vector_to_geoparquet.convert_to_geoparquet().
"""

from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import GeometryCollection, Polygon

from vector_to_geoparquet import convert_to_geoparquet


# ---------------------------------------------------------------------------
# CRS
# ---------------------------------------------------------------------------


class TestOutputCRS:
    def test_output_crs_is_epsg5880(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        assert result.crs is not None
        assert result.crs.to_epsg() == 5880, (
            f"Expected EPSG:5880 but got {result.crs.to_epsg()}"
        )

    def test_input_reprojected_from_sad69(self, tmp_path, make_gpkg, brazil_polygon):
        src = str(tmp_path / "sad69.gpkg")
        out = str(tmp_path / "out.parquet")
        make_gpkg(src, [brazil_polygon(i * 0.05) for i in range(3)], crs="EPSG:4618")
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result.crs.to_epsg() == 5880

    def test_report_output_crs(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        report = convert_to_geoparquet(polygon_gpkg, out)
        assert report["output_crs"] == "EPSG:5880"

    def test_geometry_coordinates_are_metres(self, polygon_gpkg, tmp_path):
        """Geometry in EPSG:5880 must have x values in the metre range for Brazil."""
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        bounds = result.total_bounds
        # EPSG:5880 x values for Brazil are in the range ~-3e6 to +3e6 metres
        assert abs(bounds[0]) > 1_000, (
            "xmin looks like degrees -- geometry may not be in EPSG:5880"
        )


# ---------------------------------------------------------------------------
# Geometry type homogeneity
# ---------------------------------------------------------------------------


class TestGeometryHomogeneity:
    def test_polygon_only_output(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Polygon", "MultiPolygon") for t in result.geom_type)

    def test_line_only_output(self, tmp_path, make_gpkg, brazil_line):
        src = str(tmp_path / "lines.gpkg")
        out = str(tmp_path / "out.parquet")
        make_gpkg(src, [brazil_line(i * 0.1) for i in range(4)])
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("LineString", "MultiLineString") for t in result.geom_type)

    def test_point_only_output(self, tmp_path, make_gpkg, brazil_point):
        src = str(tmp_path / "points.gpkg")
        out = str(tmp_path / "out.parquet")
        make_gpkg(src, [brazil_point(i * 0.1) for i in range(5)])
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Point", "MultiPoint") for t in result.geom_type)

    def test_geometry_collection_decomposed(self, tmp_path, make_gpkg, brazil_polygon):
        src = str(tmp_path / "gc.gpkg")
        out = str(tmp_path / "out.parquet")
        gc = GeometryCollection([brazil_polygon(), brazil_polygon(0.01)])
        make_gpkg(src, [gc, brazil_polygon(0.1)])
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert all(t in ("Polygon", "MultiPolygon") for t in result.geom_type)


# ---------------------------------------------------------------------------
# Geometry repair
# ---------------------------------------------------------------------------


class TestGeometryRepair:
    def test_self_intersecting_polygon_repaired(self, tmp_path, make_gpkg, brazil_polygon):
        bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
        src = str(tmp_path / "bowtie.gpkg")
        out = str(tmp_path / "out.parquet")
        make_gpkg(src, [bowtie, brazil_polygon()])
        convert_to_geoparquet(src, out)
        result = gpd.read_parquet(out)
        assert result.geometry.is_valid.all()


# ---------------------------------------------------------------------------
# Tile columns
# ---------------------------------------------------------------------------


class TestTileColumns:
    def test_tile_columns_present(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        assert {"tile_col", "tile_row", "tile_id"}.issubset(result.columns)

    def test_tile_id_format(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        for tid in result["tile_id"]:
            parts = str(tid).split("_")
            assert len(parts) == 2, f"tile_id '{tid}' does not match 'col_row' format"
            assert parts[0].lstrip("-").isdigit()
            assert parts[1].lstrip("-").isdigit()

    def test_tile_col_row_dtype(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        assert result["tile_col"].dtype == np.int32
        assert result["tile_row"].dtype == np.int32


# ---------------------------------------------------------------------------
# Parquet schema
# ---------------------------------------------------------------------------


class TestParquetSchema:
    def test_geometry_column_present(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        assert "geometry" in result.columns

    def test_original_attributes_preserved(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        result = gpd.read_parquet(out)
        assert "attr" in result.columns


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    EXPECTED_KEYS = {
        "input_path", "output_path", "input_crs", "output_crs",
        "geometry_family", "n_features_in", "n_features_out", "n_dropped",
        "tile_size_km", "n_tiles", "hilbert_p", "row_group_size",
        "compression", "bbox", "file_size_mb",
    }

    def test_report_has_all_keys(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        report = convert_to_geoparquet(polygon_gpkg, out)
        assert self.EXPECTED_KEYS.issubset(report.keys())

    def test_report_feature_counts(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        report = convert_to_geoparquet(polygon_gpkg, out)
        assert report["n_features_in"] == 5
        assert report["n_features_out"] <= 5
        assert report["n_dropped"] == report["n_features_in"] - report["n_features_out"]

    def test_report_bbox_keys(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        report = convert_to_geoparquet(polygon_gpkg, out)
        assert set(report["bbox"].keys()) == {"xmin", "ymin", "xmax", "ymax"}

    def test_report_file_size_positive(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        report = convert_to_geoparquet(polygon_gpkg, out)
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

    def test_output_file_created(self, polygon_gpkg, tmp_path):
        out = str(tmp_path / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, out)
        assert os.path.exists(out)

    def test_output_directory_created(self, polygon_gpkg, tmp_path):
        nested_out = str(tmp_path / "subdir" / "nested" / "out.parquet")
        convert_to_geoparquet(polygon_gpkg, nested_out)
        assert os.path.exists(nested_out)
