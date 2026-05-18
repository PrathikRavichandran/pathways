"""
send node — happy-path terminal node.

Promotes draft_response to final_response and routes to END. The actual
Twilio SMS dispatch happens in the FastAPI layer outside the graph,
gated by user HITL confirmation per CLAUDE.md.

Also appends the parole reminder opt-in offer when the user is on
parole and we have not yet offered. The append happens AFTER audit so
the offer cannot be stripped by an audit soft-block + revision loop or
by a hard-block escalation. The offer is fixed text with no legal
claim, no outcome promise; it does not need audit review.

Once the offer is in the final reply, this node also commits the
durable `intake.parole_reminder_offered = True` flag so future turns
know not to re-offer.
"""

from __future__ import annotations

from typing import Any

from pathways.nodes.draft import (
    PAROLE_OFFER_MARKER_EN,
    PAROLE_OFFER_MARKER_ES,
    append_parole_offer,
    should_offer_parole_reminder,
)
from pathways.state import PathwaysState


def run(state: PathwaysState) -> dict[str, Any]:
    draft = state.draft_response or ""

    # Append the parole reminder offer (if applicable). The audit node
    # never sees this text, so it can't strip it.
    if should_offer_parole_reminder(state):
        language = state.intake.language or "en"
        draft = append_parole_offer(draft, language=language)

    out: dict[str, Any] = {
        "final_response": draft,
        "next_node": "END",
    }

    # If the offer made it into the reply, commit the durable flag so
    # we don't re-offer on the user's next turn.
    offer_in_reply = (
        PAROLE_OFFER_MARKER_EN in draft or PAROLE_OFFER_MARKER_ES in draft
    )
    if offer_in_reply and not state.intake.parole_reminder_offered:
        out["intake"] = state.intake.model_copy(
            update={"parole_reminder_offered": True}
        )
    return out
