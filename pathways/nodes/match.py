"""
match node: pulls matching resources from tx-resources MCP server based
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

    See retrieve.py for the rationale (both MCP servers in this repo are
    named server.py, so plain `import server` collides).
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


def _all_needs_ordered(state: PathwaysState) -> list[str]:
    """Combine top_need + secondary_needs into a unique ordered list.
    Drops UNKNOWN. Returns canonical order (top first)."""
    seen: set[str] = set()
    out: list[str] = []
    candidates = [state.intake.top_need] + list(state.intake.secondary_needs or [])
    for c in candidates:
        key = _need_key(c)
        if key and key != TopNeed.UNKNOWN.value and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def run(state: PathwaysState) -> dict[str, Any]:
    server = _import_resources_server()
    region = state.intake.region
    zipcode = state.intake.zipcode

    # Phase 3: iterate over EVERY need the intake captured. Dedupe matched
    # orgs across needs by id so the same FQHC does not appear twice if
    # it serves both medical AND benefits-enrollment categories. Cap per-
    # need fetches small so multi-need responses do not blow the SMS
    # length budget.
    all_needs = _all_needs_ordered(state)
    matched: list[dict] = []
    seen_ids: set[str] = set()

    def _add(orgs: list[dict]) -> None:
        for o in orgs:
            if o.get("id") and o["id"] not in seen_ids:
                seen_ids.add(o["id"])
                matched.append(o)

    for need_key in all_needs:
        filters = NEED_TO_FILTERS.get(need_key)
        if not filters:
            continue
        category, topic = filters

        # Distance-ranked nearby (preferred when ZIP is set).
        if zipcode:
            try:
                near = server.find_resources_nearby(
                    near_zip=zipcode, category=category, top_k=3,
                )
                _add(near.get("ranked", []))
            except Exception:
                pass

        # Region-substring filter; catches statewide entries with `regions` tag.
        if region:
            try:
                result = server.find_resources(category=category, region=region)
                _add(result.get("results", []))
            except Exception:
                pass

        # Drop the region filter (still need at least one match per need).
        try:
            result = server.find_resources(category=category)
            _add(result.get("results", []))
        except Exception:
            pass

        # Topic fallback if category alone was empty.
        if topic:
            try:
                result = server.find_resources(topic=topic)
                _add(result.get("results", []))
            except Exception:
                pass

    # Always include 211 Texas as a fallback for housing/benefits OR when
    # we still have zero matches (the safety-net invariant: every reply
    # has at least one phone number the user can call).
    needs_211 = (
        TopNeed.HOUSING.value in all_needs
        or TopNeed.BENEFITS.value in all_needs
        or not matched
    )
    if needs_211:
        try:
            r = server.get_resource("211-texas")
            if r.get("resource") and r["resource"].get("id") not in seen_ids:
                matched.append(r["resource"])
                seen_ids.add(r["resource"]["id"])
        except Exception:
            pass

    # Veterans get TVC when employment or legal is among their needs.
    if state.intake.veteran and (
        TopNeed.EMPLOYMENT.value in all_needs
        or TopNeed.LEGAL_QUESTION.value in all_needs
    ):
        try:
            r = server.get_resource("tx-veterans-commission")
            if r.get("resource") and r["resource"].get("id") not in seen_ids:
                matched.append(r["resource"])
                seen_ids.add(r["resource"]["id"])
        except Exception:
            pass

    # Cap matched resources at 6 to keep responses SMS-segmented friendly.
    # Multi-need users get more diverse coverage; single-need users get the
    # top regional matches.
    return {
        "matched_resources": matched[:6],
        "next_node": "draft",
    }
