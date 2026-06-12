"""Tests for PROJ data path configuration."""

from __future__ import annotations

import os
import sqlite3

from vector_to_geoparquet._proj import _bundled_pyproj_data_dir, configure_proj_data


def test_configure_proj_data_replaces_stale_proj_lib(monkeypatch, tmp_path):
    stale_dir = tmp_path / "stale_proj"
    stale_dir.mkdir()
    with sqlite3.connect(stale_dir / "proj.db") as conn:
        conn.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        conn.execute(
            "INSERT INTO metadata VALUES (?, ?)",
            ("DATABASE.LAYOUT.VERSION.MINOR", "2"),
        )

    monkeypatch.setenv("PROJ_LIB", str(stale_dir))
    monkeypatch.delenv("PROJ_DATA", raising=False)

    configure_proj_data()

    expected = str(_bundled_pyproj_data_dir())
    assert os.environ["PROJ_LIB"] == expected
    assert os.environ["PROJ_DATA"] == expected
