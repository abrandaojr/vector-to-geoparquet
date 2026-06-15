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


MIN_PROJ_DB_LAYOUT_MINOR = 5


def _package_data_dir(package: str, *relative_parts: str) -> Path | None:
    spec = importlib.util.find_spec(package)
    if spec is None or spec.origin is None:
        return None

    package_dir = Path(spec.origin).resolve().parent
    candidate = package_dir.joinpath(*relative_parts)
    return candidate if (candidate / "proj.db").exists() else None


def _bundled_rasterio_data_dir() -> Path | None:
    return _package_data_dir("rasterio", "proj_data")


def _bundled_pyproj_data_dir() -> Path | None:
    for relative_parts in (
        ("proj_dir", "share", "proj"),
        ("share", "proj"),
    ):
        candidate = _package_data_dir("pyproj", *relative_parts)
        if candidate is not None:
            return candidate
    return None


def _compatible_candidate_dirs() -> list[Path]:
    candidates = [
        _bundled_rasterio_data_dir(),
        _bundled_pyproj_data_dir(),
    ]
    compatible: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        minor = _proj_db_layout_minor(candidate / "proj.db")
        if minor is not None and minor >= MIN_PROJ_DB_LAYOUT_MINOR:
            compatible.append(candidate)
    return compatible


def configure_proj_data() -> None:
    """Point PROJ to a compatible bundled database when the environment is stale.

    Some geospatial wheels ship different PROJ binaries and ``proj.db`` layout
    versions. Forcing pyproj's data directory can break GDAL/pyogrio when pyproj
    bundles an older database, producing errors such as "DATABASE.LAYOUT.VERSION
    .MINOR = 4 whereas a number >= 5 is expected". Prefer Rasterio's bundled
    database when available and never replace an already-compatible setting with
    an older pyproj database.
    """
    compatible_dirs = _compatible_candidate_dirs()
    replacement = str(compatible_dirs[0]) if compatible_dirs else None

    for env_name in ("PROJ_DATA", "PROJ_LIB"):
        current = os.environ.get(env_name)
        current_db = Path(current) / "proj.db" if current else None
        current_minor = _proj_db_layout_minor(current_db) if current_db else None
        if current_minor is not None and current_minor >= MIN_PROJ_DB_LAYOUT_MINOR:
            continue
        if replacement is not None:
            os.environ[env_name] = replacement
        else:
            os.environ.pop(env_name, None)
