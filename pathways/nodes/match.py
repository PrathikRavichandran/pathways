"""
match node — pulls matching resources from tx-resources MCP server based
on intake.top_need + region. Adds them to state.matched_resources.

Like retrieve.py, this calls the tx-resources tool functions directly in
demo mode. Production wraps these as MCP HTTP calls.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from pathways.state import PathwaysState, TopNeed


def _import_resources_server():
    """Load mcp_servers/tx_resources/server.py under a unique module name.

    See retrieve.py for the rationale — both MCP servers in this repo are
    named server.py, so plain `import server` collides.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", ".."))
    server_path = os.path.join(
        repo_root, "mcp_servers", "tx_resources", "server.py"
    )
    spec = importlib.util.spec_from_file_location(
        "tx_resources_server", server_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load tx-resources server at {server_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Each need maps to a (category, topic) pair. Category is more reliable than
# topic because resources are tagged for one category but may carry several
# topics. We try category first, fall back to topic if nothing matches.
# Keyed by the enum *value* (string) because LangGraph may reserialize the
# state between nodes and enum identity is not preserved.
NEED_TO_FILTERS: dict[str, tuple[str, str | None]] = {
    TopNeed.HOUSING.value: ("housing", "shelter"),
    TopNeed.EMPLOYMENT.value: ("employment", "fair_chance"),
    TopNeed.BENEFITS.value: ("benefits", "snap"),
    TopNeed.ID_DOCUMENTS.value: ("id_documents", "state_id"),
    TopNeed.RECORD_CLEARING.value: ("legal_aid", "expunction_referrals"),
    TopNeed.LEGAL_QUESTION.value: ("legal_aid", "civil_legal"),
    TopNeed.PAROLE_REPORTING.value: ("supervision", "state_reentry"),
}


def _need_key(value) -> str:
    """Coerce a TopNeed (enum or its string value) to its string."""
    return value.value if hasattr(value, "value") else str(value)


def run(state: PathwaysState) -> dict[str, Any]:
    server = _import_resources_server()
    need_key = _need_key(state.intake.top_need)
    filters = NEED_TO_FILTERS.get(need_key)
    region = state.intake.region
    zipcode = state.intake.zipcode

    matched: list[dict] = []

    if filters:
        category, topic = filters

        # Phase 2: distance-ranked nearby is preferred when the user gave a ZIP.
        # The nearby call returns both `ranked` (distance-sorted, capped by
        # max_miles when set) and `fallback` (statewide hotlines for safety).
        if zipcode:
            try:
                near = server.find_resources_nearby(
                    near_zip=zipcode,
                    category=category,
                    top_k=5,
                )
                matched.extend(near.get("ranked", []))
                # Save the safety-net fallback for the always-include block below.
            except Exception:
                pass

        # Region-substring filter as the secondary path. Catches orgs that the
        # nearby ranker missed (e.g., the seed JSON statewide entries that
        # have no lat/lon but do carry a `regions` tag matching the user's metro).
        if not matched:
            try:
                result = server.find_resources(category=category, region=region)
                matched.extend(result.get("results", []))
            except Exception:
                pass

        # Drop the region filter when nothing matches regionally.
        if not matched:
            try:
                result = server.find_resources(category=category)
                matched.extend(result.get("results", []))
            except Exception:
                pass

        # Topic fallback if category was too narrow
        if not matched and topic:
            try:
                result = server.find_resources(topic=topic)
                matched.extend(result.get("results", []))
            except Exception:
                pass

    # Always include 211 Texas as a fallback for housing/benefits
    if state.intake.top_need in (TopNeed.HOUSING, TopNeed.BENEFITS, TopNeed.UNKNOWN):
        try:
            r = server.get_resource("211-texas")
            if r.get("resource") and not any(
                m.get("id") == "211-texas" for m in matched
            ):
                matched.append(r["resource"])
        except Exception:
            pass

    # Veterans get TVC for employment/legal
    if state.intake.veteran and state.intake.top_need in (
        TopNeed.EMPLOYMENT, TopNeed.LEGAL_QUESTION
    ):
        try:
            r = server.get_resource("tx-veterans-commission")
            if r.get("resource") and not any(
                m.get("id") == "tx-veterans-commission" for m in matched
            ):
                matched.append(r["resource"])
        except Exception:
            pass

    return {
        "matched_resources": matched[:6],  # cap to prevent choice paralysis
        "next_node": "draft",
    }
