"""
escalate node — terminal node for handoff to human navigator.

Sets final_response to a humane handoff message, sets escalated_to_human=True,
and routes to END. The actual Twilio send happens in the API layer outside
the graph (gated by user HITL confirmation per the prohibited_actions list).
"""

from __future__ import annotations

from typing import Any

from pathways.state import CrisisCategory, PathwaysState


CRISIS_MESSAGES = {
    CrisisCategory.SUICIDE: (
        "I hear you, and I want to make sure you have someone you can talk to "
        "right now. The 988 Suicide & Crisis Lifeline is free, confidential, "
        "and available 24/7 — call or text 988. I'm still here too."
    ),
    CrisisCategory.SELF_HARM: (
        "Thank you for telling me. The 988 line (call or text 988) has people "
        "available right now who can help. I'm staying with you."
    ),
    CrisisCategory.SUBSTANCE: (
        "I'm glad you reached out. SAMHSA's helpline is 1-800-662-4357 — "
        "free, 24/7, and they can find a treatment option near you tonight if "
        "you want one. I'm here."
    ),
    CrisisCategory.DOMESTIC_VIOLENCE: (
        "I want to make sure you're safe. The National Domestic Violence "
        "Hotline is 1-800-799-7233, or you can text START to 88788. They can "
        "help with a safety plan tonight."
    ),
    CrisisCategory.VIOLENCE_TO_OTHERS: (
        "I can tell you're carrying something heavy. If anyone is in danger "
        "right now, please call 911. SAMHSA's line at 1-800-662-4357 can also "
        "help with what you're feeling."
    ),
    CrisisCategory.SEXUAL_VIOLENCE: (
        "I'm sorry. RAINN's confidential hotline is 1-800-656-4673 — they have "
        "people who can help you decide what to do next, on your timeline."
    ),
    CrisisCategory.HOUSING_EMERGENCY: (
        "Tonight matters. Call 211 (or text TXHELP to 898211) — Texas 211 is "
        "free and 24/7 and they'll know the closest open bed in your area."
    ),
}

GENERIC_ESCALATION = (
    "Let me connect you with a navigator who can help with this. Texas 211 "
    "(dial 211, or text TXHELP to 898211) can route you to the right resource "
    "tonight. For legal questions, Texas RioGrande Legal Aid at "
    "1-888-988-9996 is a good next call."
)


def run(state: PathwaysState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.crisis.fired and state.crisis.category:
        msg = CRISIS_MESSAGES.get(state.crisis.category, GENERIC_ESCALATION)
    else:
        msg = GENERIC_ESCALATION

    out: dict[str, Any] = {
        "final_response": msg,
        "escalated_to_human": True,
        "next_node": "END",
    }

    # Parole reminder opt-in offer: also append on the escalation path
    # if supervision=parole. The audit revision loop or a hard-block can
    # send us here without ever calling send, and we still want the
    # opt-in offer to reach the user. Skip when crisis fired (the
    # crisis reply is the wrong moment to ask about reminders).
    if not state.crisis.fired:
        from pathways.nodes.draft import (
            PAROLE_OFFER_MARKER_EN,
            PAROLE_OFFER_MARKER_ES,
            append_parole_offer,
            should_offer_parole_reminder,
        )
        if should_offer_parole_reminder(state):
            language = state.intake.language or "en"
            msg = append_parole_offer(msg, language=language)
            out["final_response"] = msg
            marker = PAROLE_OFFER_MARKER_ES if language == "es" else PAROLE_OFFER_MARKER_EN
            if marker in msg and not state.intake.parole_reminder_offered:
                out["intake"] = state.intake.model_copy(
                    update={"parole_reminder_offered": True}
                )

    return out
