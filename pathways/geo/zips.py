"""ZIP-to-coords + county + workforce-region lookups for Texas.

Reads the vendored CSV at mcp_servers/tx_resources/zcta_centroids.csv
(GeoNames extract for TX, ~2,600 ZIPs across all 254 counties) and the
TWC county-to-region map at pathways/geo/workforce_regions.py.

The CSV is loaded lazily on first call and cached for process lifetime.
That keeps test startup fast and avoids paying I/O cost in modules that
import this one but never call its functions.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pathways.geo.workforce_regions import COUNTY_TO_REGION

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ZIP_CSV = _REPO_ROOT / "mcp_servers" / "tx_resources" / "zcta_centroids.csv"


@lru_cache(maxsize=1)
def _zip_table() -> dict[str, dict]:
    """Load the TX ZIP centroid table from CSV. Cached after first call."""
    table: dict[str, dict] = {}
    if not _ZIP_CSV.exists():
        return table
    with _ZIP_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            zip5 = (row.get("zip") or "").strip()
            if not zip5 or not zip5.isdigit():
                continue
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, ValueError):
                continue
            table[zip5] = {
                "zip": zip5,
                "lat": lat,
                "lon": lon,
                "city": (row.get("city") or "").strip(),
                "county": (row.get("county") or "").strip(),
            }
    return table


def zip_to_coords(zip5: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) for a Texas 5-digit ZIP, or None if not in the table."""
    if not zip5:
        return None
    z = str(zip5).strip()
    if len(z) > 5:
        z = z.split("-", 1)[0]  # accept ZIP+4 form
    if not (len(z) == 5 and z.isdigit()):
        return None
    row = _zip_table().get(z)
    if not row:
        return None
    return (row["lat"], row["lon"])


def county_for_zip(zip5: str) -> Optional[str]:
    """Return the Texas county name for a ZIP, or None if not in the table."""
    if not zip5:
        return None
    z = str(zip5).strip()
    if len(z) > 5:
        z = z.split("-", 1)[0]
    row = _zip_table().get(z)
    if not row:
        return None
    county = row["county"]
    return county or None


def workforce_region_for_county(county: str) -> Optional[str]:
    """Return the TWC workforce region for a TX county name (title-cased)."""
    if not county:
        return None
    return COUNTY_TO_REGION.get(county.strip().title())


def workforce_region_for_zip(zip5: str) -> Optional[str]:
    """Compose: ZIP -> county -> TWC workforce region."""
    county = county_for_zip(zip5)
    if not county:
        return None
    return workforce_region_for_county(county)
