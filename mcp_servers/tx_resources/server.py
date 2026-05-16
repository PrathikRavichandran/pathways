"""
tx-resources : MCP server exposing curated Texas reentry resources.

Transport: stdio
Tools:
    find_resources(topic=None, category=None, region=None)         -> filtered list
    find_resources_nearby(near_zip, category=None, max_miles=None,
                          top_k=5)                                  -> distance-ranked
    get_resource(resource_id)                                       -> single resource
    list_categories()                                               -> categories + counts

Backends (selected by TX_RESOURCES_BACKEND env var):
    file     (default): reads mcp_servers/tx_resources/resources.json
    postgres          : reads from the resources table in DATABASE_URL

The tool contract is identical across backends so the graph nodes that
call this server do not know or care which backend is active.

For distance ranking, the user-supplied ZIP is resolved to lat/lon via
the vendored TX ZCTA centroid table (pathways/geo/), and each candidate
resource's lat/lon is compared via the haversine formula. Resources
without coordinates (statewide hotlines like 211 Texas) are surfaced
as a fallback at the bottom of the list when no distance-ranked match
clears a quality bar.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("FATAL: mcp not installed. Run `pip install mcp`.", file=sys.stderr)
    raise

from pathways.geo import haversine_miles, zip_to_coords


DEFAULT_PATH = Path(__file__).parent / "resources.json"
JSON_PATH = Path(os.environ.get("TX_RESOURCES_PATH", str(DEFAULT_PATH)))
BACKEND = os.environ.get("TX_RESOURCES_BACKEND", "file").strip().lower()

mcp = FastMCP("tx-resources")


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _load_file() -> tuple[dict, list[dict]]:
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"resources not found at {JSON_PATH}")
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    return payload.get("_metadata", {}), payload.get("resources", [])


def _load_postgres() -> tuple[dict, list[dict]]:
    """Fetch all resources from the Postgres table. Cached at module load."""
    import psycopg

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "TX_RESOURCES_BACKEND=postgres but DATABASE_URL is unset."
        )
    rows: list[dict] = []
    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, category, subcategory, description,
                       service_area, regions, lat, lon, service_radius_miles,
                       workforce_region, county,
                       phone, text_to, url, apply_url, intake_url, languages,
                       eligibility, topics, accepting_clients,
                       bed_count_last_known, serves_returning_citizens,
                       last_verified, last_verified_by, source, stale
                  FROM resources
                 WHERE stale = FALSE
                 ORDER BY id;
            """)
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                rows.append(dict(zip(cols, row)))
    metadata = {
        "name": "tx-resources",
        "backend": "postgres",
        "count": len(rows),
    }
    return metadata, rows


def _load() -> tuple[dict, list[dict]]:
    if BACKEND == "postgres":
        return _load_postgres()
    return _load_file()


METADATA, RESOURCES = _load()
RESOURCES_BY_ID = {r["id"]: r for r in RESOURCES}


def _refresh_cache() -> None:
    """Test/admin helper: re-read the backend. Not normally called at runtime."""
    global METADATA, RESOURCES, RESOURCES_BY_ID
    METADATA, RESOURCES = _load()
    RESOURCES_BY_ID = {r["id"]: r for r in RESOURCES}


# ---------------------------------------------------------------------------
# Shape normalizer (returned to callers)
# ---------------------------------------------------------------------------


def _project(r: dict, extra: Optional[dict] = None) -> dict:
    """Return the public-facing projection of a resource record.

    Strips internal-only fields and presents both Postgres and file backends
    with the same key set so node code does not care which backend is active.
    """
    out = {
        "id":            r.get("id"),
        "name":          r.get("name"),
        "category":      r.get("category"),
        "subcategory":   r.get("subcategory"),
        "description":   r.get("description"),
        "phone":         r.get("phone"),
        "text":          r.get("text") or r.get("text_to"),
        "url":           r.get("url"),
        "apply_url":     r.get("apply_url"),
        "intake_url":    r.get("intake_url"),
        "languages":     list(r.get("languages") or []),
        "service_area":  list(r.get("service_area") or []),
        "regions":       list(r.get("regions") or []),
        "topics":        list(r.get("topics") or []),
        "eligibility":   r.get("eligibility"),
        "county":        r.get("county"),
        "workforce_region": r.get("workforce_region"),
        "lat":           r.get("lat"),
        "lon":           r.get("lon"),
        "accepting_clients": r.get("accepting_clients"),
        "last_verified": str(r.get("last_verified")) if r.get("last_verified") else None,
        "source":        r.get("source"),
    }
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def find_resources(
    topic: str | None = None,
    category: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Find resources matching a topic, category, or region.

    Args:
        topic: A topic keyword (e.g., "snap", "housing", "veteran_employment",
            "fair_chance", "domestic_violence"). Matches against each resource's
            `topics` array. Case-insensitive substring match.
        category: A category (e.g., "legal_aid", "employment", "crisis",
            "housing", "benefits", "veteran_services"). Exact match.
        region: A region or service area substring (e.g., "Houston", "DFW",
            "Harris County"). Matches against `service_area` and `regions`.

    At least one filter should be passed. Returns all resources if none.
    """
    topic_lc = topic.lower() if topic else None
    region_lc = region.lower() if region else None

    results = []
    for r in RESOURCES:
        if category and r.get("category") != category:
            continue
        if topic_lc:
            topics = [str(t).lower() for t in (r.get("topics") or [])]
            if not any(topic_lc in t for t in topics):
                continue
        if region_lc:
            haystacks = [
                str(r.get("service_area") or "").lower(),
                str(r.get("regions") or "").lower(),
                str(r.get("county") or "").lower(),
                str(r.get("workforce_region") or "").lower(),
            ]
            if not any(region_lc in h for h in haystacks):
                continue
        results.append(_project(r))

    return {
        "results": results,
        "count": len(results),
        "filters": {"topic": topic, "category": category, "region": region},
    }


@mcp.tool()
def find_resources_nearby(
    near_zip: str,
    category: str | None = None,
    topic: str | None = None,
    max_miles: int | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Find resources ranked by distance from the user's ZIP.

    Distance is computed haversine between the ZIP centroid and each
    resource's lat/lon. Resources without coordinates (statewide hotlines)
    are appended at the end as a fallback so the user always sees 211 Texas
    and similar safety nets even when no nearby org is in the directory yet.

    Args:
        near_zip: 5-digit US ZIP code (assumed Texas).
        category: optional category filter (exact match).
        topic: optional topic filter (case-insensitive substring on topics).
        max_miles: cap distance. None means no cap, ranking still applies.
        top_k: how many ranked results to return (statewide fallbacks counted
            separately and not subject to the cap).

    Returns dict with `ranked` (distance-sorted, capped) and `fallback`
    (statewide-only, included for safety).
    """
    coords = zip_to_coords(near_zip)
    if not coords:
        return {
            "ranked": [],
            "fallback": [_project(r) for r in RESOURCES if not r.get("lat")][:5],
            "error": f"Could not resolve ZIP {near_zip!r} (TX only)",
            "filters": {"near_zip": near_zip, "category": category, "topic": topic},
        }

    user_lat, user_lon = coords
    topic_lc = topic.lower() if topic else None

    nearby = []
    fallback = []
    for r in RESOURCES:
        if category and r.get("category") != category:
            continue
        if topic_lc:
            topics = [str(t).lower() for t in (r.get("topics") or [])]
            if not any(topic_lc in t for t in topics):
                continue
        if r.get("lat") and r.get("lon"):
            d = haversine_miles(user_lat, user_lon, float(r["lat"]), float(r["lon"]))
            if max_miles is not None and d > max_miles:
                continue
            nearby.append(_project(r, {"distance_miles": round(d, 1)}))
        else:
            fallback.append(_project(r))

    nearby.sort(key=lambda x: x["distance_miles"])
    return {
        "ranked": nearby[:top_k],
        "fallback": fallback[:5],
        "filters": {
            "near_zip": near_zip,
            "category": category,
            "topic": topic,
            "max_miles": max_miles,
            "top_k": top_k,
        },
        "user_coords": {"lat": user_lat, "lon": user_lon},
    }


@mcp.tool()
def get_resource(resource_id: str) -> dict[str, Any]:
    """Fetch a single resource by id."""
    r = RESOURCES_BY_ID.get(resource_id)
    if r is None:
        return {"error": f"no resource with id {resource_id!r}"}
    return {"resource": _project(r)}


@mcp.tool()
def list_categories() -> dict[str, Any]:
    """Enumerate categories and their resource counts."""
    from collections import Counter
    cats = Counter(r["category"] for r in RESOURCES)
    return {
        "categories": dict(cats),
        "total": len(RESOURCES),
        "backend": BACKEND,
        "version": METADATA.get("version") if isinstance(METADATA, dict) else None,
    }


if __name__ == "__main__":
    mcp.run()
