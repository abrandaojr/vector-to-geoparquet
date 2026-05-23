"""_hilbert.py -- Hilbert curve distance for spatial row ordering.

Uses the vectorised Shapely 2.0 API when available; falls back to a
pure-Python implementation for older environments.
"""

from __future__ import annotations

import numpy as np

try:
    from shapely import hilbert_distance as _shapely_hilbert

    def hilbert(gs, bounds, p: int):
        """Return Hilbert distances for a GeoSeries using Shapely >= 2.0."""
        return _shapely_hilbert(gs, bounds, p=p)

except ImportError:

    def _d(n: int, x: int, y: int) -> int:
        """Compute a single Hilbert distance for grid cell (x, y)."""
        d, s = 0, n >> 1
        while s:
            rx, ry = int(bool(x & s)), int(bool(y & s))
            d += s * s * ((3 * rx) ^ ry)
            if not ry:
                if rx:
                    x, y = s - 1 - x, s - 1 - y
                x, y = y, x
            s >>= 1
        return d

    def hilbert(gs, bounds, p: int):  # type: ignore[misc]
        """Pure-Python fallback: compute Hilbert distances from geometry centroids."""
        n = 2**p
        x0, y0, x1, y1 = bounds
        dx, dy = x1 - x0 or 1.0, y1 - y0 or 1.0
        b = np.array([g.bounds for g in gs])
        cx = (b[:, 0] + b[:, 2]) / 2.0
        cy = (b[:, 1] + b[:, 3]) / 2.0
        xi = np.clip(((cx - x0) / dx * (n - 1)).astype(np.int64), 0, n - 1)
        yi = np.clip(((cy - y0) / dy * (n - 1)).astype(np.int64), 0, n - 1)
        return np.array(
            [_d(n, int(x), int(y)) for x, y in zip(xi, yi)], dtype=np.int64
        )
