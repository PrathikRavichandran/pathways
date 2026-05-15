"""
intake node — first-touch routing.

Responsibilities:
- Inspect the incoming user message.
- If crisis was already detected by the hook, route to escalate.
- Otherwise, extract minimum routing fields (region, top_need,
  supervision_status if mentioned) using a small Haiku call.
- Set intake.intake_complete=True so the graph doesn't loop back to
  intake on the next turn within the same conversation.

This is intentionally light. Heavy intake forms live in the
`intake-assessment` Skill which the parent session can invoke; this node
is the graph-level "have we routed yet?" decision.
"""

from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic
from pathways.state import (
    IntakeProfile,
    PathwaysState,
    SupervisionStatus,
    TopNeed,
)


_CLIENT: Anthropic | None = None


def _client() -> Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _CLIENT


INTAKE_SYSTEM_PROMPT = """You extract routing fields from a user message for a Texas reentry navigation assistant. Return ONLY a JSON object with these fields. Do not include prose.

{
  "top_need": "housing" | "employment" | "benefits" | "id_documents" | "record_clearing" | "legal_question" | "parole_reporting" | "crisis" | "unknown",
  "secondary_needs": [<same enum>],
  "city": "<TX city if user mentioned, else null>",
  "region": "<one of: Greater Houston, DFW, Austin, San Antonio, Rio Grande Valley, El Paso, East Texas, West Texas, Statewide, null>",
  "supervision_status": "off_paper" | "parole" | "probation" | "deferred_adjudication" | "unknown",
  "veteran": true | false | null,
  "language": "en" | "es"
}

Rules:
- Be conservative: when a field is not clearly indicated, use "unknown" or null.
- Do not infer language from a single word; require sustained Spanish or an explicit "español".
- Do not infer city from a region (Houston is Greater Houston; Dallas/Fort Worth is DFW)."""


def run(state: PathwaysState) -> dict[str, Any]:
    """LangGraph node entry point. Returns partial state."""

    # If crisis was already detected by hook, short-circuit to escalate.
    if state.crisis.fired:
        return {
            "next_node": "escalate",
            "escalation_reason": f"crisis_hook:{state.crisis.category}",
        }

    # If intake is already complete (continuation turn), skip directly to
    # retrieve. The graph router uses this to avoid re-doing intake.
    if state.intake_complete:
        return {"next_node": "retrieve"}

    # Extract fields. In demo mode without an API key, fall back to a tiny
    # keyword heuristic so the graph still runs end to end.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        extracted = _heuristic_extract(state.user_message)
    else:
        try:
            extracted = _llm_extract(state.user_message)
        except Exception:
            # Resilience: never let extraction failures kill the turn.
            extracted = _heuristic_extract(state.user_message)

    # Merge into the intake profile.
    profile = state.intake.model_copy()
    if extracted.get("top_need"):
        try:
            profile.top_need = TopNeed(extracted["top_need"])
        except ValueError:
            profile.top_need = TopNeed.UNKNOWN
    if extracted.get("secondary_needs"):
        sec: list[TopNeed] = []
        for n in extracted["secondary_needs"]:
            try:
                sec.append(TopNeed(n))
            except ValueError:
                continue
        profile.secondary_needs = sec
    if extracted.get("city"):
        profile.city = extracted["city"]
    if extracted.get("region"):
        profile.region = extracted["region"]
    if extracted.get("supervision_status"):
        try:
            profile.supervision_status = SupervisionStatus(extracted["supervision_status"])
        except ValueError:
            pass
    if extracted.get("veteran") is not None:
        profile.veteran = bool(extracted["veteran"])
    if extracted.get("language") in ("en", "es"):
        profile.language = extracted["language"]

    return {
        "intake": profile,
        "intake_complete": True,
        "next_node": "retrieve",
    }


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _llm_extract(user_message: str) -> dict:
    response = _client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=INTAKE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    text = response.content[0].text.strip()
    # Strip possible code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def _heuristic_extract(user_message: str) -> dict:
    """Demo-mode fallback. Keyword-based, intentionally simple."""
    msg = user_message.lower()
    need = "unknown"
    if any(k in msg for k in ["shelter", "place to stay", "nowhere to live", "homeless", "housing"]):
        need = "housing"
    elif any(k in msg for k in ["job", "work", "hire", "employment", "career"]):
        need = "employment"
    elif any(k in msg for k in ["snap", "food stamps", "medicaid", "tanf", "benefits"]):
        need = "benefits"
    elif any(k in msg for k in ["id", "social security card", "driver's license"]):
        need = "id_documents"
    elif any(k in msg for k in ["expunge", "expunction", "non-disclosure", "seal", "clear my record"]):
        need = "record_clearing"
    elif any(k in msg for k in ["can i", "am i eligible", "rule", "law"]):
        need = "legal_question"

    region = None
    city = None
    if "houston" in msg:
        city = "Houston"; region = "Greater Houston"
    elif "dallas" in msg or "fort worth" in msg:
        region = "DFW"
    elif "austin" in msg:
        city = "Austin"; region = "Austin"
    elif "san antonio" in msg:
        city = "San Antonio"; region = "San Antonio"

    supervision = "unknown"
    if "parole" in msg:
        supervision = "parole"
    elif "probation" in msg:
        supervision = "probation"

    return {
        "top_need": need,
        "secondary_needs": [],
        "city": city,
        "region": region,
        "supervision_status": supervision,
        "veteran": True if "veteran" in msg else None,
        "language": "es" if "español" in msg or "ayuda" in msg else "en",
    }
