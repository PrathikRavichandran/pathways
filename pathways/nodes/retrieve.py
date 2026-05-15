"""
retrieve node — pulls from pathways-corpus based on intake.top_need.

This is the seam where the graph talks to the pathways-corpus MCP server.
In LangGraph, the MCP call can go through Claude Code's tool layer (when
running inside a Claude Code session) or be invoked directly via subprocess
(when running standalone as a FastAPI service).

For the demo run, we import the corpus server's tool functions directly
and call them in-process. This avoids spawning an MCP stdio subprocess
from inside an async FastAPI handler, which is fragile. In production
behind FastAPI, swap _direct_call for an HTTP MCP client. The contract is
identical.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from pathways.state import PathwaysState, Retrieval, TopNeed


def _import_corpus_server():
    """Load mcp_servers/pathways_corpus/server.py under a unique module name.

    Both MCP servers in this repo are named server.py. Plain `import server`
    caches the first one imported under sys.modules['server'] and breaks the
    second. Use importlib to load each under its own namespace.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", ".."))
    server_path = os.path.join(
        repo_root, "mcp_servers", "pathways_corpus", "server.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pathways_corpus_server", server_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load corpus server at {server_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Map TopNeed value → corpus category filter and a query phrase. Keyed by
# the enum *value* (string) because LangGraph reserializes enums between
# nodes and dict-lookup-by-enum may miss after a round trip.
NEED_TO_CORPUS: dict[str, tuple[str | None, str]] = {
    TopNeed.HOUSING.value: ("housing", "public housing eligibility with criminal record"),
    TopNeed.EMPLOYMENT.value: ("employment", "occupational license criminal conviction"),
    TopNeed.BENEFITS.value: ("benefits", "SNAP food stamps drug felony Texas"),
    TopNeed.RECORD_CLEARING.value: ("record_clearing", "non-disclosure expunction eligibility"),
    TopNeed.LEGAL_QUESTION.value: (None, ""),  # Use the user message directly
    TopNeed.PAROLE_REPORTING.value: ("supervision", "parole conditions Texas"),
    TopNeed.ID_DOCUMENTS.value: (None, "Texas state ID social security card after release"),
}


def _need_key(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def run(state: PathwaysState) -> dict[str, Any]:
    """LangGraph node entry point."""
    need_key = _need_key(state.intake.top_need)

    # Some needs don't require corpus retrieval (id_documents is resource-only)
    if need_key == TopNeed.UNKNOWN.value:
        return {"next_node": "match"}

    corpus = _import_corpus_server()

    category, default_query = NEED_TO_CORPUS.get(need_key, (None, ""))
    # Prefer the actual user message for the query — it's more specific
    # than a category-default.
    query = (
        state.user_message
        if need_key == TopNeed.LEGAL_QUESTION.value
        else (default_query or state.user_message)
    )

    try:
        result = corpus.search_corpus(query=query, category=category, top_k=5)
    except Exception as exc:
        # Resilience: corpus error shouldn't kill the turn.
        return {
            "retrievals": state.retrievals + [
                Retrieval(
                    source="pathways-corpus",
                    query=query,
                    confidence=0.0,
                    results=[],
                    gated_low_confidence=True,
                )
            ],
            "next_node": "match",
        }

    confidence = float(result.get("confidence", 0.0))
    floor = float(os.environ.get("PATHWAYS_CONFIDENCE_FLOOR", "0.62"))

    retrieval = Retrieval(
        source="pathways-corpus",
        query=query,
        confidence=confidence,
        results=result.get("results", []),
        gated_low_confidence=(confidence < floor),
    )

    return {
        "retrievals": state.retrievals + [retrieval],
        "next_node": "match",
    }
