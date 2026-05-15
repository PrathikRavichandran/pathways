"""
tx-resources — MCP server exposing curated Texas reentry resources.

Transport: stdio
Tools:
    find_resources(topic=None, category=None, region=None) -> list of resources
    get_resource(resource_id)                              -> single resource
    list_categories()                                      -> all categories + counts

Unlike pathways-corpus (which is retrieval over legal text), this server
serves structured directory data: organizations, hotlines, agencies.
Search is filter-based, not BM25 — recall matters more than ranking when
the data is small and curated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("FATAL: mcp not installed. Run `pip install mcp`.", file=sys.stderr)
    raise


DEFAULT_PATH = Path(__file__).parent / "resources.json"
PATH = Path(os.environ.get("TX_RESOURCES_PATH", str(DEFAULT_PATH)))


def _load() -> tuple[dict, list[dict]]:
    if not PATH.exists():
        raise FileNotFoundError(f"resources not found at {PATH}")
    payload = json.loads(PATH.read_text())
    return payload["_metadata"], payload["resources"]


METADATA, RESOURCES = _load()
RESOURCES_BY_ID = {r["id"]: r for r in RESOURCES}

mcp = FastMCP("tx-resources")


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

    Topics across the corpus include:
      employment, fair_chance, job_training, ged, fidelity_bond
      housing, shelter, transitional_housing, public_housing
      snap, medicaid, tanf, benefits_enrollment
      id_documents, state_id, social_security_card
      legal_information, civil_legal, expunction_referrals, drivers_license_restoration
      veteran_services, veteran_legal, veteran_justice
      crisis, suicide, substance_use, domestic_violence, mental_health
      advocacy, peer_support, policy
    """
    results = []
    topic_lc = topic.lower() if topic else None
    region_lc = region.lower() if region else None

    for r in RESOURCES:
        if category and r.get("category") != category:
            continue
        if topic_lc:
            topics = [t.lower() for t in r.get("topics", [])]
            if not any(topic_lc in t for t in topics):
                continue
        if region_lc:
            haystacks = [
                str(r.get("service_area", "")).lower(),
                str(r.get("regions", "")).lower(),
            ]
            if not any(region_lc in h for h in haystacks):
                continue
        results.append({
            "id": r["id"],
            "name": r["name"],
            "category": r["category"],
            "subcategory": r.get("subcategory"),
            "description": r["description"],
            "phone": r.get("phone"),
            "text": r.get("text"),
            "url": r.get("url"),
            "apply_url": r.get("apply_url"),
            "intake_url": r.get("intake_url"),
            "languages": r.get("languages", []),
            "service_area": r.get("service_area", []),
            "topics": r.get("topics", []),
        })

    return {
        "results": results,
        "count": len(results),
        "filters": {"topic": topic, "category": category, "region": region},
    }


@mcp.tool()
def get_resource(resource_id: str) -> dict[str, Any]:
    """Fetch a single resource by id."""
    r = RESOURCES_BY_ID.get(resource_id)
    if r is None:
        return {"error": f"no resource with id {resource_id!r}"}
    return {"resource": r}


@mcp.tool()
def list_categories() -> dict[str, Any]:
    """Enumerate categories and their resource counts."""
    from collections import Counter
    cats = Counter(r["category"] for r in RESOURCES)
    return {
        "categories": dict(cats),
        "total": len(RESOURCES),
        "version": METADATA.get("version"),
    }


if __name__ == "__main__":
    mcp.run()
