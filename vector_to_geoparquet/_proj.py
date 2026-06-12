"""PROJ data path configuration helpers."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path


def _proj_db_layout_minor(proj_db: Path) -> int | None:
    """Read the PROJ database minor layout version without importing pyproj."""
    try:
        with sqlite3.connect(f"file:{proj_db}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key = 'DATABASE.LAYOUT.VERSION.MINOR'"
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _bundled_pyproj_data_dir() -> Path | None:
    spec = importlib.util.find_spec("pyproj")
    if spec is None or spec.origin is None:
        return None

    package_dir = Path(spec.origin).resolve().parent
    candidates = (
        package_dir / "proj_dir" / "share" / "proj",
        package_dir / "share" / "proj",
    )
    for candidate in candidates:
        if (candidate / "proj.db").exists():
            return candidate
    return None


def configure_proj_data() -> None:
    """Prefer pyproj's bundled PROJ database over stale global installs."""
    proj_dir = _bundled_pyproj_data_dir()
    if proj_dir is None:
        return

    bundled_minor = _proj_db_layout_minor(proj_dir / "proj.db")
    if bundled_minor is None:
        return

    for env_name in ("PROJ_DATA", "PROJ_LIB"):
        current = os.environ.get(env_name)
        current_db = Path(current) / "proj.db" if current else None
        current_minor = _proj_db_layout_minor(current_db) if current_db else None
        if current_minor != bundled_minor:
            os.environ[env_name] = str(proj_dir)
