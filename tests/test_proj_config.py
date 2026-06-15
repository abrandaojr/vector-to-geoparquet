"""Tests for PROJ data path configuration."""

from __future__ import annotations

import os
import sqlite3

import vector_to_geoparquet._proj as proj_config


def _make_proj_dir(path, minor):
    path.mkdir()
    with sqlite3.connect(path / "proj.db") as conn:
        conn.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        conn.execute(
            "INSERT INTO metadata VALUES (?, ?)",
            ("DATABASE.LAYOUT.VERSION.MINOR", str(minor)),
        )
    return path


def test_configure_proj_data_replaces_stale_proj_lib(monkeypatch, tmp_path):
    stale_dir = _make_proj_dir(tmp_path / "stale_proj", 2)
    rasterio_dir = _make_proj_dir(tmp_path / "rasterio_proj", 5)

    monkeypatch.setattr(proj_config, "_bundled_rasterio_data_dir", lambda: rasterio_dir)
    monkeypatch.setattr(proj_config, "_bundled_pyproj_data_dir", lambda: None)

    monkeypatch.setenv("PROJ_LIB", str(stale_dir))
    monkeypatch.delenv("PROJ_DATA", raising=False)

    proj_config.configure_proj_data()

    expected = str(rasterio_dir)
    assert os.environ["PROJ_LIB"] == expected
    assert os.environ["PROJ_DATA"] == expected


def test_configure_proj_data_does_not_downgrade_compatible_env(monkeypatch, tmp_path):
    compatible_dir = _make_proj_dir(tmp_path / "compatible_proj", 5)
    old_pyproj_dir = _make_proj_dir(tmp_path / "old_pyproj_proj", 4)

    monkeypatch.setattr(proj_config, "_bundled_rasterio_data_dir", lambda: None)
    monkeypatch.setattr(proj_config, "_bundled_pyproj_data_dir", lambda: old_pyproj_dir)

    monkeypatch.setenv("PROJ_LIB", str(compatible_dir))
    monkeypatch.setenv("PROJ_DATA", str(compatible_dir))

    proj_config.configure_proj_data()

    assert os.environ["PROJ_LIB"] == str(compatible_dir)
    assert os.environ["PROJ_DATA"] == str(compatible_dir)


def test_configure_proj_data_unsets_stale_env_without_compatible_candidate(monkeypatch, tmp_path):
    stale_dir = _make_proj_dir(tmp_path / "stale_proj", 2)
    old_pyproj_dir = _make_proj_dir(tmp_path / "old_pyproj_proj", 4)

    monkeypatch.setattr(proj_config, "_bundled_rasterio_data_dir", lambda: None)
    monkeypatch.setattr(proj_config, "_bundled_pyproj_data_dir", lambda: old_pyproj_dir)

    monkeypatch.setenv("PROJ_LIB", str(stale_dir))
    monkeypatch.setenv("PROJ_DATA", str(stale_dir))

    proj_config.configure_proj_data()

    assert "PROJ_LIB" not in os.environ
    assert "PROJ_DATA" not in os.environ
