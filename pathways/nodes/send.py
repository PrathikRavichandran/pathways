"""
send node — happy-path terminal node.

Promotes draft_response to final_response and routes to END. The actual
Twilio SMS dispatch happens in the FastAPI layer outside the graph,
gated by user HITL confirmation per CLAUDE.md.
"""

from __future__ import annotations

from typing import Any

from pathways.state import PathwaysState


def run(state: PathwaysState) -> dict[str, Any]:
    return {
        "final_response": state.draft_response,
        "next_node": "END",
    }
