"""
ingest_hrsa_fqhcs.py: pull all active TX FQHC sites from HRSA into the
resources table.

Source: data.hrsa.gov public download (no auth required, refreshed daily).
  https://data.hrsa.gov/data/download

FQHCs (Federally Qualified Health Centers) provide sliding-scale primary
care to low-income patients regardless of insurance status. They are the
backbone of medical access for the population pathways serves. Texas has
about 830 active FQHC service sites operated by roughly 80 grantee
organizations.

Why this ingester matters:
- The seed resource directory has zero health-care entries; a returning
  citizen with a chronic condition (very common post-release) had no
  routing option before this.
- HRSA publishes daily-refreshed canonical data with geo coordinates,
  so the freshness and accuracy are higher than any third-party scrape.

Run:
    DATABASE_URL=postgresql://... python -m scripts.ingest_hrsa_fqhcs
"""

from __future__ import annotations

import csv
import io
import urllib.request
from typing import Iterable

from pathways.geo import workforce_region_for_county
from scripts._common import enrich_geo, get_conn, log, today_iso, upsert_resource

HRSA_URL = (
    "https://data.hrsa.gov/DataDownload/DD_Files/"
    "Health_Center_Service_Delivery_and_LookAlike_Sites.csv"
)
SOURCE = "hrsa_fqhc"


def _fetch_csv() -> str:
    log(f"  GET {HRSA_URL}")
    with urllib.request.urlopen(HRSA_URL, timeout=180) as r:
        raw = r.read()
    log(f"  downloaded {len(raw) / 1024 / 1024:.1f} MB")
    return raw.decode("utf-8", errors="replace")


def _parse_float(value: str) -> float | None:
    try:
        f = float(value)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _parse_zip(postal: str) -> str | None:
    if not postal:
        return None
    z = postal.split("-", 1)[0].strip()
    return z if len(z) == 5 and z.isdigit() else None


def _record_from_row(row: dict) -> dict | None:
    if (row.get("Site State Abbreviation") or "").strip() != "TX":
        return None
    if (row.get("Site Status Description") or "").strip() != "Active":
        return None

    site_name = (row.get("Site Name") or "").strip()
    health_center = (row.get("Health Center Name") or "").strip()
    name = site_name or health_center
    if not name:
        return None

    bhcmis = (row.get("BHCMIS Organization Identification Number") or "").strip()
    site_loc_id = (row.get("Health Center Location Identification Number") or "1").strip()
    npi = (row.get("FQHC Site NPI Number") or "").strip()

    # Deterministic stable id: bhcmis + site loc id + npi if present.
    rec_id = f"hrsa-{bhcmis}-{site_loc_id}"
    if npi:
        rec_id = f"{rec_id}-{npi}"

    address = (row.get("Site Address") or "").strip()
    city = (row.get("Site City") or "").strip()
    zip5 = _parse_zip(row.get("Site Postal Code") or "")
    phone = (row.get("Site Telephone Number") or "").strip()
    url = (row.get("Site Web Address") or "").strip() or None
    hours = (row.get("Operating Hours per Week") or "").strip()

    county = (row.get("Complete County Name") or row.get("County Description") or "").strip()
    # HRSA returns "Harris County"; our county->workforce-region map uses bare
    # county names ("Harris"). Strip the suffix so workforce_region derives.
    if county.lower().endswith(" county"):
        county = county[:-7].strip()
    lat = _parse_float(row.get("Geocoding Artifact Address Primary Y Coordinate") or "")
    lon = _parse_float(row.get("Geocoding Artifact Address Primary X Coordinate") or "")

    # Build a useful description string.
    pieces = []
    if site_name and health_center and site_name != health_center:
        pieces.append(f"Operated by {health_center}.")
    pieces.append(
        "Federally Qualified Health Center. Sliding-scale primary care, "
        "regardless of insurance status."
    )
    if address:
        loc = ", ".join(p for p in (address, city, "TX") if p)
        if zip5:
            loc += f" {zip5}"
        pieces.append(loc)
    if hours and hours not in ("0.00", "0", ""):
        pieces.append(f"~{hours} hours per week.")
    description = " ".join(pieces)

    return {
        "id": rec_id,
        "name": name,
        "category": "medical",
        "subcategory": "fqhc",
        "description": description,
        "service_area": [f"county:{county}"] if county else ["TX"],
        "workforce_region": workforce_region_for_county(county) if county else None,
        "regions": [],  # workforce_region resolves via geo lookup
        "phone": phone or None,
        "url": url,
        "languages": ["English", "Spanish"],  # FQHCs are required to offer language access
        "eligibility": (
            "All welcome regardless of insurance, immigration status, or ability to "
            "pay. Sliding-scale fees based on household income; no one is turned "
            "away for inability to pay."
        ),
        "topics": ["medical", "primary_care", "sliding_scale", "uninsured", "low_income"],
        "lat": lat,
        "lon": lon,
        "county": county or None,
        "serves_returning_citizens": True,  # FQHCs serve everyone
        "last_verified": today_iso(),
    }


def _yield_records(csv_text: str) -> Iterable[dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        rec = _record_from_row(row)
        if rec:
            yield rec


def main() -> int:
    log("HRSA FQHC ingester starting...")
    text = _fetch_csv()

    inserted = 0
    updated = 0
    skipped = 0
    with get_conn() as conn:
        for rec in _yield_records(text):
            enrich_geo(rec)  # ensures workforce_region from county if it wasn't set above
            try:
                if upsert_resource(conn, rec, source=SOURCE):
                    inserted += 1
                else:
                    updated += 1
            except Exception as exc:
                skipped += 1
                log(f"  skip {rec.get('id', '?')}: {exc}")
            if (inserted + updated) % 100 == 0 and (inserted + updated) > 0:
                log(f"  ... {inserted + updated} rows processed")

    log(f"HRSA FQHC ingest complete: {inserted} inserted, {updated} updated, {skipped} skipped")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM resources WHERE source = %s AND stale = FALSE",
                (SOURCE,),
            )
            log(f"  total live HRSA FQHC rows: {cur.fetchone()[0]}")
            cur.execute(
                "SELECT COUNT(*) FROM resources WHERE source = %s "
                "AND lat IS NOT NULL AND lon IS NOT NULL",
                (SOURCE,),
            )
            log(f"  with geo coords          : {cur.fetchone()[0]}")
            cur.execute(
                "SELECT COUNT(DISTINCT county) FROM resources WHERE source = %s",
                (SOURCE,),
            )
            log(f"  counties covered         : {cur.fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
