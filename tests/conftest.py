"""conftest.py -- shared fixtures for vector_to_geoparquet tests."""

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon


def _brazil_polygon(offset: float = 0.0) -> Polygon:
    """Simple polygon well inside Brazilian territory (Mato Grosso area)."""
    return Polygon(
        [
            (-55.0 + offset, -12.0),
            (-54.0 + offset, -12.0),
            (-54.0 + offset, -11.0),
            (-55.0 + offset, -11.0),
            (-55.0 + offset, -12.0),
        ]
    )


def _brazil_line(offset: float = 0.0) -> LineString:
    return LineString([(-55.0 + offset, -12.0), (-54.0 + offset, -11.0)])


def _brazil_point(offset: float = 0.0) -> Point:
    return Point(-54.5 + offset, -11.5)


def _make_gpkg(path: str, geoms, crs: str = "EPSG:4674") -> gpd.GeoDataFrame:
    gdf = gpd.GeoDataFrame(
        {"attr": list(range(len(geoms)))},
        geometry=geoms,
        crs=crs,
    )
    gdf.to_file(path, driver="GPKG")
    return gdf


@pytest.fixture
def brazil_polygon():
    return _brazil_polygon


@pytest.fixture
def brazil_line():
    return _brazil_line


@pytest.fixture
def brazil_point():
    return _brazil_point


@pytest.fixture
def make_gpkg():
    return _make_gpkg


@pytest.fixture
def polygon_gpkg(tmp_path, make_gpkg):
    """GeoPackage with 5 polygon features ready for conversion."""
    src = str(tmp_path / "polygons.gpkg")
    make_gpkg(src, [_brazil_polygon(i * 0.05) for i in range(5)])
    return src
