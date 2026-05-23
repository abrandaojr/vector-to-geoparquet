"""vector_to_geoparquet -- Brazil-specific vector-to-GeoParquet converter.

Output CRS: EPSG:5880 (SIRGAS 2000 / Brazil Polyconic, metres).
"""

from ._constants import __version__
from ._core import _cli, convert_to_geoparquet

__all__ = ["convert_to_geoparquet", "__version__"]
