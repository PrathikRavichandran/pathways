"""Geo utilities for distance-based resource ranking.

All functions in this module are pure and do not touch the network or
the database. The underlying data (TX ZIP centroids, TWC workforce
region map, TDCJ facility list) is vendored under
mcp_servers/tx_resources/ as small static CSVs.

The module exists at the pathways package level (not inside the MCP
server directory) because both the match node and the MCP server need
it; co-locating it with either would create an import cycle.
"""

from pathways.geo.distance import haversine_miles
from pathways.geo.zips import (
    county_for_zip,
    workforce_region_for_county,
    workforce_region_for_zip,
    zip_to_coords,
)

__all__ = [
    "haversine_miles",
    "county_for_zip",
    "workforce_region_for_county",
    "workforce_region_for_zip",
    "zip_to_coords",
]
