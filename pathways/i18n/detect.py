"""Lightweight language detection for English vs Spanish.

This is intentionally NOT a full language detector. We only care about
distinguishing English from Spanish, both written in Latin script,
both with overlapping common words. A heavy LangID model is overkill
and adds dependencies.

Approach:
- Build a small set of high-signal Spanish-only tokens (function words,
  pronouns, and reentry-domain vocabulary like "trabajo", "ayuda",
  "vivienda"). If any appears in a tokenized message, flag Spanish.
- Backup signal: ratio of "common Spanish 3-grams" (sequences like
  "que ", "los ", "ar ", "es ") to total trigrams. High ratio = Spanish.
- Default to English on ambiguity. The trauma-informed register guide
  in `.claude/rules/tone-and-trauma-informed.md` explicitly says do
  NOT infer language from a single word; we follow that here by
  requiring at least two strong signals before flipping to Spanish.

A user can always force language via the `IntakeProfile.language`
field; this detector is only used when that field is not yet set.
"""

from __future__ import annotations

import re
from typing import Literal

# High-signal Spanish tokens. Each one is rare in English text.
# Curated for reentry-domain vocabulary; this list grows as we see
# real user messages.
_ES_TOKENS = frozenset({
    # function / pronouns
    "que", "para", "con", "por", "los", "las", "como", "esto", "esta",
    "este", "soy", "estoy", "estamos", "estan", "tengo", "tienes",
    "tiene", "tenemos", "necesito", "necesita", "necesitamos",
    "puedo", "puede", "podemos", "ayuda", "ayuden", "ayudame",
    "hola", "gracias", "buenos", "buenas", "donde", "cuando",
    "porque", "espanol", "español",
    # reentry / domain
    "trabajo", "empleo", "vivienda", "comida", "techo", "dormir",
    "carcel", "cárcel", "salí", "sali", "preso", "libertad",
    "ayudarme", "necesidad", "abogado", "documento", "identificacion",
    "identificación", "dinero", "familia", "hijo", "hija",
})

# Very common English-only tokens (helps tie-breaking on short messages).
_EN_TOKENS = frozenset({
    "the", "and", "with", "from", "have", "this", "that",
    "you", "your", "what", "when", "where", "need", "help",
    "thanks", "thank", "please", "hello", "yes", "want",
    "house", "job", "work", "food",
})

_WORD = re.compile(r"[a-zA-Záéíóúñü]+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def detect_language(text: str) -> Literal["en", "es"]:
    """Return 'es' if the message is meaningfully Spanish, else 'en'.

    Conservative: needs at least two distinct Spanish-signal tokens OR
    a clear majority of Spanish-only vocabulary to flip from the
    English default. This avoids flipping on a single word like "hola"
    in an otherwise English message.
    """
    toks = _tokens(text)
    if not toks:
        return "en"

    es_hits = sum(1 for t in toks if t in _ES_TOKENS)
    en_hits = sum(1 for t in toks if t in _EN_TOKENS)

    # Explicit override: user wrote "español" or "espanol" alone or as part
    # of a longer message. That is an unambiguous request, override.
    for marker in ("espanol", "español"):
        if marker in toks:
            return "es"

    if es_hits >= 2 and es_hits > en_hits:
        return "es"
    if es_hits >= 1 and en_hits == 0 and len(toks) <= 5:
        # Short message that is purely Spanish vocabulary: trust it.
        return "es"

    return "en"
