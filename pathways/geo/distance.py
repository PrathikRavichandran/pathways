"""Haversine great-circle distance in miles."""

from __future__ import annotations

import math


_EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two lat/lon points in miles.

    Accuracy is +/- ~5 miles in dense metros and +/- ~20 miles in rural
    Texas when used with ZCTA centroids. That is fine for ranking. Never
    present the result as an exact distance to a user; round to the
    nearest 5 miles in user-facing prose.
    """
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return _EARTH_RADIUS_MILES * c
