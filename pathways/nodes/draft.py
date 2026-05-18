"""
draft node: composes a user-facing response from retrievals + matched
resources. This is the only node that does heavy LLM work.

Uses Sonnet for synthesis. The prompt is short and routes the work to
the right Skill via natural reference; the Skills themselves are loaded
into the Claude Code session by description match.

In demo mode without an API key, falls back to a deterministic template
so the graph still runs end-to-end and the test suite passes.
"""

from __future__ import annotations

import json
from typing import Any

from pathways.llm import LLMUnavailable, get_llm
from pathways.state import PathwaysState


DRAFT_SYSTEM_EN = """You are a Pathways navigator drafting a reply to a user in Texas who is navigating post-incarceration reentry. The Skills loaded in this session encode the protocol; follow them. Hard rules from CLAUDE.md apply: cite every factual legal claim, never give legal/clinical advice, never promise outcomes, default to handoff when uncertain. SMS-shaped: two short paragraphs max, plain language, no bullets, no emojis.

You are given:
- The user's message
- The intake routing decision (may include multiple needs)
- Retrieval results from pathways-corpus (with confidence scores)
- Matched resources from tx-resources

Compose a single reply. Cite statutes by section number and link the URL the corpus provides. If retrieval confidence is below 0.62, do not assert legal claims; acknowledge uncertainty and route to legal aid or 211.

If the user has multiple needs, acknowledge each one but lead with the most time-critical (housing tonight > food > id/parole > benefits > employment > legal/record-clearing). Keep multi-need replies one short paragraph longer than single-need, not double.

The user is reading on a basic phone. Avoid em dashes; use commas, periods, or parentheses instead."""

DRAFT_SYSTEM_ES = """Eres un guía de Pathways respondiendo a una persona en Texas que está navegando su reintegración después de salir de la cárcel. Las Skills cargadas en esta sesión codifican el protocolo; síguelas. Reglas duras de CLAUDE.md aplican: cita toda afirmación legal con su sección, nunca des consejo legal o clínico, nunca prometas resultados, en duda conecta con un humano.

Formato SMS: máximo dos párrafos cortos, lenguaje sencillo, sin viñetas, sin emojis. La persona está leyendo en un teléfono básico.

Te dan:
- El mensaje de la persona
- La decisión de intake (puede tener múltiples necesidades)
- Resultados de retrieval de pathways-corpus (con puntaje de confianza)
- Recursos coincidentes de tx-resources

Compón una sola respuesta. Cita estatutos por número de sección y enlaza la URL que el corpus provee. Si la confianza de retrieval es menor a 0.62, no afirmes claims legales; reconoce la incertidumbre y refiere a legal aid o al 211.

Si la persona tiene múltiples necesidades, reconoce cada una pero comienza con la más urgente en tiempo (vivienda esta noche > comida > id/libertad condicional > beneficios > empleo > legal/limpiar récord)."""


def run(state: PathwaysState) -> dict[str, Any]:
    """LangGraph node entry point.

    Calls the smart-tier LLM for synthesis. On LLMUnavailable (no API
    key, SDK error, content filter, etc) falls back to a deterministic
    bilingual template so the graph still produces a valid reply.
    """
    try:
        draft = _llm_draft(state)
    except LLMUnavailable:
        draft = _template_draft(state)
    except Exception:
        draft = _template_draft(state)

    # Phase 6: parole reminder opt-in offer. Append a one-line offer
    # when the user is on parole and we have not yet offered. The
    # auditor sees the appended text and clears it (no legal claim,
    # no outcome promise; it's an operational opt-in question).
    #
    # Important: we do NOT set intake.parole_reminder_offered=True here.
    # That commit happens in the send node, after audit has finished
    # revising. If we set it here, an audit soft-block + revision would
    # gate this function out on the second draft pass and the user
    # would receive a reply without the offer. The offer-append itself
    # is idempotent (checks for the marker phrase first) so re-running
    # draft within a turn cannot duplicate it.
    if _should_offer_parole_reminder(state):
        draft = _append_parole_offer(draft, language=state.intake.language or "en")

    return {"draft_response": draft, "next_node": "audit"}


def _should_offer_parole_reminder(state: PathwaysState) -> bool:
    intake = state.intake
    if intake.parole_reminder_offered:
        # Already delivered in a previous turn (durable state set by send).
        return False
    if intake.parole_reminder_opt_in is not None:
        # User already accepted or declined; never re-offer.
        return False
    supervision = intake.supervision_status
    val = supervision.value if hasattr(supervision, "value") else str(supervision)
    return val == "parole"


# Marker substrings the send node uses to detect that the offer made it
# into the final reply and the draft node uses for idempotency.
PAROLE_OFFER_MARKER_EN = "Reply YES with the date"
PAROLE_OFFER_MARKER_ES = "Responde SI con la fecha"


def _append_parole_offer(draft: str, language: str) -> str:
    """Append the EN or ES parole reminder offer to the draft.

    Idempotent within a single turn: if the marker phrase is already
    present (e.g., from a prior pass during an audit revision loop),
    the draft is returned unchanged.
    """
    draft = draft or ""
    marker = PAROLE_OFFER_MARKER_ES if language == "es" else PAROLE_OFFER_MARKER_EN
    if marker in draft:
        return draft
    if language == "es":
        offer = (
            "\n\nUna ultima cosa: si quieres, te puedo enviar un mensaje el dia "
            "antes de cada cita de libertad condicional. Responde SI con la fecha "
            "(por ejemplo, SI marzo 5)."
        )
    else:
        offer = (
            "\n\nOne more thing: if you want, I can text you the day before each "
            "parole check-in. Reply YES with the date (e.g., YES March 5)."
        )
    return draft.rstrip() + offer


def _llm_draft(state: PathwaysState) -> str:
    user_content = {
        "user_message": state.user_message,
        "intake": state.intake.model_dump(mode="json"),
        "retrievals": [r.model_dump(mode="json") for r in state.retrievals],
        "matched_resources": state.matched_resources,
    }
    language = state.intake.language or "en"
    system = DRAFT_SYSTEM_ES if language == "es" else DRAFT_SYSTEM_EN

    return get_llm("smart").invoke(
        system=system,
        user=json.dumps(user_content),
        max_tokens=600,
        temperature=0.2,
    )


def _template_draft(state: PathwaysState) -> str:
    """Deterministic fallback for demo mode without an API key.

    Phase 3: language-aware (EN or ES), multi-need-aware (acknowledges
    every need the intake captured, lead with the most time-critical).
    """
    language = (state.intake.language or "en").lower()
    if language == "es":
        return _template_draft_es(state)
    return _template_draft_en(state)


def _human_need(need_value: str, language: str = "en") -> str:
    """Render a TopNeed enum value as user-facing prose in the right language."""
    en = {
        "housing": "a place to stay",
        "benefits": "benefits like SNAP or Medicaid",
        "employment": "work",
        "id_documents": "getting your ID back",
        "record_clearing": "clearing your record",
        "legal_question": "the legal question you asked",
        "parole_reporting": "your parole reporting",
        "unknown": "what you shared",
    }
    es = {
        "housing": "un lugar para dormir",
        "benefits": "beneficios como SNAP o Medicaid",
        "employment": "trabajo",
        "id_documents": "recuperar tu identificación",
        "record_clearing": "limpiar tu récord",
        "legal_question": "la pregunta legal",
        "parole_reporting": "tu reporte de libertad condicional",
        "unknown": "lo que compartiste",
    }
    table = es if language == "es" else en
    return table.get(need_value, need_value.replace("_", " "))


def _all_needs(state: PathwaysState) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    top = state.intake.top_need
    cands = [top] + list(state.intake.secondary_needs or [])
    for c in cands:
        v = c.value if hasattr(c, "value") else str(c)
        if v and v != "unknown" and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _template_draft_en(state: PathwaysState) -> str:
    intake = state.intake
    needs = _all_needs(state)
    top_retrievals = [
        item for r in state.retrievals if not r.gated_low_confidence
        for item in r.results[:2]
    ]
    name_prefix = f"{intake.name}, " if intake.name else ""

    parts = []
    if len(needs) == 0:
        parts.append("I'm here. Tell me what you need most right now.")
    elif len(needs) == 1:
        parts.append(
            f"{name_prefix}I hear you. The most pressing piece looks like "
            f"{_human_need(needs[0], 'en')}."
        )
    else:
        first = _human_need(needs[0], "en")
        rest = ", ".join(_human_need(n, "en") for n in needs[1:])
        parts.append(
            f"{name_prefix}I hear you. You're juggling a lot: {first}, plus {rest}. "
            f"Let's start with the first one since it's the most time-sensitive."
        )

    if top_retrievals:
        cites = ", ".join(
            f"{r['citation']} ({r.get('url','')})" for r in top_retrievals[:2]
        )
        parts.append(f"Here are the rules that apply: {cites}.")
    elif any(r.gated_low_confidence for r in state.retrievals):
        parts.append(
            "I want to be straight with you. I don't have a confident answer "
            "on this one. I'll connect you with someone who can give you a "
            "definite answer."
        )

    if state.matched_resources:
        first = state.matched_resources[0]
        contact = first.get("phone") or first.get("url") or ""
        parts.append(
            f"For next steps, the best fit looks like {first['name']}. {contact}".strip()
        )

    return "\n\n".join(parts)


def _template_draft_es(state: PathwaysState) -> str:
    intake = state.intake
    needs = _all_needs(state)
    top_retrievals = [
        item for r in state.retrievals if not r.gated_low_confidence
        for item in r.results[:2]
    ]
    name_prefix = f"{intake.name}, " if intake.name else ""

    parts = []
    if len(needs) == 0:
        parts.append("Estoy aquí. Cuéntame qué necesitas más en este momento.")
    elif len(needs) == 1:
        parts.append(
            f"{name_prefix}te escucho. Lo más urgente parece ser "
            f"{_human_need(needs[0], 'es')}."
        )
    else:
        first = _human_need(needs[0], "es")
        rest = ", ".join(_human_need(n, "es") for n in needs[1:])
        parts.append(
            f"{name_prefix}te escucho. Tienes varias cosas: {first}, además de {rest}. "
            f"Empecemos con la primera porque es la más urgente."
        )

    if top_retrievals:
        cites = ", ".join(
            f"{r['citation']} ({r.get('url','')})" for r in top_retrievals[:2]
        )
        parts.append(f"Aquí están las reglas que aplican: {cites}.")
    elif any(r.gated_low_confidence for r in state.retrievals):
        parts.append(
            "Te voy a ser honesto. No tengo una respuesta segura en este caso. "
            "Te conecto con alguien que sí te puede dar una respuesta definitiva."
        )

    if state.matched_resources:
        first = state.matched_resources[0]
        contact = first.get("phone") or first.get("url") or ""
        parts.append(
            f"Como próximo paso, el mejor encaje parece {first['name']}. {contact}".strip()
        )

    return "\n\n".join(parts)
