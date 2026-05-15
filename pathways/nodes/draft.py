"""
draft node — composes a user-facing response from retrievals + matched
resources. This is the only node that does heavy LLM work.

Uses Sonnet for synthesis. The prompt is short and routes the work to
the right Skill via natural reference; the Skills themselves are loaded
into the Claude Code session by description match.

In demo mode without an API key, falls back to a deterministic template
so the graph still runs end-to-end and the test suite passes.
"""

from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic
from pathways.state import PathwaysState

_CLIENT: Anthropic | None = None


def _client() -> Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _CLIENT


DRAFT_SYSTEM = """You are a Pathways navigator drafting a reply to a user in Texas who is navigating post-incarceration reentry. The Skills loaded in this session encode the protocol; follow them. Hard rules from CLAUDE.md apply: cite every factual legal claim, never give legal/clinical advice, never promise outcomes, default to handoff when uncertain. SMS-shaped: two short paragraphs max, plain language, no bullets, no emojis.

You are given:
- The user's message
- The intake routing decision
- Retrieval results from pathways-corpus (with confidence scores)
- Matched resources from tx-resources

Compose a single reply. Cite statutes by section number and link the URL the corpus provides. If retrieval confidence is below 0.62, do not assert legal claims — acknowledge uncertainty and route to legal aid or 211."""


def run(state: PathwaysState) -> dict[str, Any]:
    """LangGraph node entry point."""

    if not os.environ.get("ANTHROPIC_API_KEY"):
        draft = _template_draft(state)
        return {"draft_response": draft, "next_node": "audit"}

    try:
        draft = _llm_draft(state)
    except Exception:
        draft = _template_draft(state)

    return {"draft_response": draft, "next_node": "audit"}


def _llm_draft(state: PathwaysState) -> str:
    user_content = {
        "user_message": state.user_message,
        "intake": state.intake.model_dump(mode="json"),
        "retrievals": [r.model_dump(mode="json") for r in state.retrievals],
        "matched_resources": state.matched_resources,
    }

    resp = _client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=DRAFT_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(user_content)}],
    )
    return resp.content[0].text.strip()


def _template_draft(state: PathwaysState) -> str:
    """Deterministic fallback for demo mode without an API key.

    This is deliberately simple — it shows the graph is wired and producing
    output, without pretending to be the production response quality.
    """
    intake = state.intake
    top_retrievals = []
    for r in state.retrievals:
        if r.gated_low_confidence:
            continue
        for item in r.results[:2]:
            top_retrievals.append(item)

    parts = []
    parts.append(
        f"I hear you. Based on what you shared, the most pressing piece looks like "
        f"{intake.top_need.value.replace('_', ' ')}."
    )

    if top_retrievals:
        cites = ", ".join(
            f"{r['citation']} ({r.get('url','')})" for r in top_retrievals[:2]
        )
        parts.append(f"Here are the rules that apply: {cites}.")
    elif any(r.gated_low_confidence for r in state.retrievals):
        parts.append(
            "I want to be straight with you — I don't have a confident answer on this one. "
            "I'll connect you with someone who can give you a definite answer."
        )

    if state.matched_resources:
        first = state.matched_resources[0]
        contact = first.get("phone") or first.get("url") or ""
        parts.append(
            f"For next steps, the best fit looks like {first['name']}. {contact}".strip()
        )

    return "\n\n".join(parts) if parts else (
        "I'm here. Can you tell me a bit more about what you need most right now?"
    )
