"""One-shot migration: existing JSON seed data -> Postgres.

Reads:
- mcp_servers/tx_resources/resources.json (18 orgs)
- mcp_servers/pathways_corpus/corpus.json (65 entries)

For each resource, enriches with lat/lon/county/workforce_region when the
record's regions field hints at a known TX city (Houston / DFW / etc.) or
when an explicit ZIP is present anywhere in the record. Hand-picked
fallback coords for the metro-level orgs that don't have a single ZIP.

Idempotent: re-running upserts; never duplicates.

Usage:
    DATABASE_URL=postgresql://... python scripts/migrate_seed_to_postgres.py
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts._common import (
    enrich_geo,
    get_conn,
    log,
    today_iso,
    upsert_corpus_entry,
    upsert_resource,
)

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_JSON = ROOT / "mcp_servers" / "tx_resources" / "resources.json"
CORPUS_JSON = ROOT / "mcp_servers" / "pathways_corpus" / "corpus.json"

# Hand-picked metro centroid for orgs whose JSON has no specific ZIP/address
# but whose `regions` field identifies a metro. Lets the seed orgs benefit
# from distance ranking even without precise addresses. The Phase 2 ingesters
# pull real per-site addresses for org networks.
REGION_FALLBACK_COORDS = {
    "Greater Houston":     {"lat": 29.7604, "lon": -95.3698, "county": "Harris"},
    "Gulf Coast":          {"lat": 29.7604, "lon": -95.3698, "county": "Harris"},
    "DFW":                 {"lat": 32.7767, "lon": -96.7970, "county": "Dallas"},
    "Dallas":              {"lat": 32.7767, "lon": -96.7970, "county": "Dallas"},
    "Tarrant County":      {"lat": 32.7555, "lon": -97.3308, "county": "Tarrant"},
    "Austin":              {"lat": 30.2672, "lon": -97.7431, "county": "Travis"},
    "Capital Area":        {"lat": 30.2672, "lon": -97.7431, "county": "Travis"},
    "Alamo":               {"lat": 29.4241, "lon": -98.4936, "county": "Bexar"},
    "San Antonio":         {"lat": 29.4241, "lon": -98.4936, "county": "Bexar"},
    "Borderplex":          {"lat": 31.7619, "lon": -106.4850, "county": "El Paso"},
    "El Paso":             {"lat": 31.7619, "lon": -106.4850, "county": "El Paso"},
    "Lower Rio Grande Valley": {"lat": 26.2034, "lon": -98.2300, "county": "Hidalgo"},
    "Cameron County":      {"lat": 25.9018, "lon": -97.4975, "county": "Cameron"},
    "South Texas":         {"lat": 27.5063, "lon": -99.5076, "county": "Webb"},
    "Coastal Bend":        {"lat": 27.8006, "lon": -97.3964, "county": "Nueces"},
    "Golden Crescent":     {"lat": 28.8053, "lon": -97.0036, "county": "Victoria"},
    "East Texas":          {"lat": 32.3513, "lon": -95.3011, "county": "Smith"},
    "Northeast Texas":     {"lat": 33.4251, "lon": -94.0477, "county": "Bowie"},
    "Deep East Texas":     {"lat": 31.3382, "lon": -94.7291, "county": "Nacogdoches"},
    "Southeast Texas":     {"lat": 30.0860, "lon": -94.1018, "county": "Jefferson"},
    "Brazos Valley":       {"lat": 30.6280, "lon": -96.3344, "county": "Brazos"},
    "Central Texas":       {"lat": 31.1171, "lon": -97.7278, "county": "Bell"},
    "Heart of Texas":      {"lat": 31.5493, "lon": -97.1467, "county": "McLennan"},
    "Rural Capital":       {"lat": 30.5083, "lon": -97.6789, "county": "Williamson"},
    "Concho Valley":       {"lat": 31.4638, "lon": -100.4370, "county": "Tom Green"},
    "West Central":        {"lat": 32.4487, "lon": -99.7331, "county": "Taylor"},
    "Permian Basin":       {"lat": 31.9974, "lon": -102.0779, "county": "Midland"},
    "South Plains":        {"lat": 33.5779, "lon": -101.8552, "county": "Lubbock"},
    "Panhandle":           {"lat": 35.2220, "lon": -101.8313, "county": "Potter"},
    "North Texas":         {"lat": 33.9137, "lon": -98.4934, "county": "Wichita"},
    "North Central":       {"lat": 33.0198, "lon": -96.6989, "county": "Collin"},
    "Texoma":              {"lat": 33.6357, "lon": -96.6089, "county": "Grayson"},
    "Middle Rio Grande":   {"lat": 28.7091, "lon": -100.4995, "county": "Maverick"},
}


def _enrich_resource(record: dict) -> dict:
    """Add geo fields. Try ZIP-based lookup first; fall back to region centroid."""
    enrich_geo(record)  # populates from ZIP if present anywhere

    if record.get("lat") and record.get("lon"):
        return record

    # Region-centroid fallback for orgs whose JSON entry lacks an address.
    for region in record.get("regions") or []:
        if region in REGION_FALLBACK_COORDS:
            fb = REGION_FALLBACK_COORDS[region]
            record["lat"] = fb["lat"]
            record["lon"] = fb["lon"]
            record.setdefault("county", fb["county"])
            # Workforce region maps off county at lookup time.
            from pathways.geo import workforce_region_for_county
            wr = workforce_region_for_county(fb["county"])
            if wr:
                record.setdefault("workforce_region", wr)
            return record

    return record  # leave geo NULL; statewide-only orgs (like 211) are fine without it


def migrate_resources(conn) -> tuple[int, int]:
    data = json.loads(RESOURCES_JSON.read_text(encoding="utf-8"))
    items = data.get("resources", data) if isinstance(data, dict) else data
    inserted = 0
    updated = 0
    for raw in items:
        enriched = _enrich_resource(dict(raw))
        was_insert = upsert_resource(conn, enriched, source="seed")
        if was_insert:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def migrate_corpus(conn) -> tuple[int, int]:
    data = json.loads(CORPUS_JSON.read_text(encoding="utf-8"))
    items = data.get("entries", data) if isinstance(data, dict) else data
    inserted = 0
    updated = 0
    for raw in items:
        was_insert = upsert_corpus_entry(conn, dict(raw), source="seed")
        if was_insert:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def main() -> int:
    log("Migrating seed JSON into Postgres tables...")
    with get_conn() as conn:
        r_ins, r_upd = migrate_resources(conn)
        log(f"  resources: {r_ins} inserted, {r_upd} updated")
        c_ins, c_upd = migrate_corpus(conn)
        log(f"  corpus   : {c_ins} inserted, {c_upd} updated")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM resources")
            log(f"  total resources rows now: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM corpus")
            log(f"  total corpus rows now   : {cur.fetchone()[0]}")
            cur.execute(
                "SELECT COUNT(*) FROM resources WHERE lat IS NOT NULL AND lon IS NOT NULL"
            )
            log(f"  resources with geo      : {cur.fetchone()[0]}")
    log("Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
