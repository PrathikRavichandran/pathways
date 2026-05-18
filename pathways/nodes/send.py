"""
send node — happy-path terminal node.

Promotes draft_response to final_response and routes to END. The actual
Twilio SMS dispatch happens in the FastAPI layer outside the graph,
gated by user HITL confirmation per CLAUDE.md.

Also commits the durable `parole_reminder_offered` flag once the
parole reminder offer makes it into the final reply. Draft handles
appending the offer (which may run twice during an audit revision
loop); send is the single place where we mark the offer as
"delivered" so subsequent turns know not to re-offer.
"""

from __future__ import annotations

from typing import Any

from pathways.nodes.draft import PAROLE_OFFER_MARKER_EN, PAROLE_OFFER_MARKER_ES
from pathways.state import PathwaysState


def run(state: PathwaysState) -> dict[str, Any]:
    out: dict[str, Any] = {
        "final_response": state.draft_response,
        "next_node": "END",
    }
    draft = state.draft_response or ""
    offer_in_reply = (
        PAROLE_OFFER_MARKER_EN in draft or PAROLE_OFFER_MARKER_ES in draft
    )
    if offer_in_reply and not state.intake.parole_reminder_offered:
        out["intake"] = state.intake.model_copy(
            update={"parole_reminder_offered": True}
        )
    return out
