"""Bilingual deterministic-response string table.

These are the strings the FastAPI ingress and the slot-fill node ship
WITHOUT going through the LLM. They have to be exactly right in both
languages and the only safe place to keep them is in version-controlled
code that gets reviewed.

Strings produced by the model (the draft node, the audit node) stay
language-aware via the IntakeProfile.language field; the draft node
includes "respond in {language}" in its system prompt.
"""

from __future__ import annotations

from typing import Literal

Lang = Literal["en", "es"]

_TABLE: dict[str, dict[Lang, str]] = {
    # TCPA-mandated responses (do NOT change without legal review)
    "tcpa_stop_ack": {
        "en": (
            "You will not receive further messages. Reply START to resume."
        ),
        "es": (
            "No recibirá más mensajes. Responda START si desea reanudar."
        ),
    },
    "tcpa_start_ack": {
        "en": (
            "Welcome back. Send a message any time and I'll help."
        ),
        "es": (
            "Bienvenido de vuelta. Envíe un mensaje cuando quiera y le ayudo."
        ),
    },
    "tcpa_help": {
        "en": (
            "I'm Pathways, an SMS navigator for people just released in "
            "Texas. Reply with your situation and I'll find resources. "
            "Reply STOP to opt out."
        ),
        "es": (
            "Soy Pathways, una guía por SMS para personas recién liberadas "
            "en Texas. Cuénteme su situación y le ayudo a encontrar "
            "recursos. Responda STOP para no recibir más mensajes."
        ),
    },
    # Generic error fallback
    "fallback_error": {
        "en": (
            "I hit a snag on my end. For anything urgent, call 211. "
            "They're 24/7 and can help right now. Otherwise try me again "
            "in a few minutes."
        ),
        "es": (
            "Tuve un problema. Si es urgente, llame al 211. Están "
            "disponibles 24/7 y pueden ayudar ahora mismo. Si no, "
            "escríbame de nuevo en unos minutos."
        ),
    },
    # Spanish language acknowledgment when we first detect the switch
    "language_switch_es": {
        "en": "(switching to Spanish)",
        "es": "Continuamos en español.",
    },
}


def bilingual(key: str, language: Lang = "en") -> str:
    """Return the language-specific string for a known key.

    Returns the English string if the key or language is missing rather
    than raising; an empty string would be worse for the user than a
    fallback to English.
    """
    entry = _TABLE.get(key)
    if entry is None:
        return ""
    return entry.get(language) or entry.get("en") or ""


def all_keys() -> list[str]:
    """List every key in the table (used by tests to enforce parity)."""
    return sorted(_TABLE.keys())
