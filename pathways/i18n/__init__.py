"""Internationalization helpers for Pathways.

Phase 3 introduces Spanish support. The module is small on purpose:
- detect.py: lightweight trigram language detector, no API calls
- responses.py: bilingual string table (EN + ES) for the deterministic
  responses that ship from the FastAPI ingress (slot prompts,
  escalations, opt-in/opt-out, TCPA HELP/STOP, error fallback)

The 7 Skills themselves stay bilingual via their `language` field on
the IntakeProfile. The draft node reads that field and instructs the
model to reply in the matching language. Full -es sibling Skills are
queued as Phase 3.5 follow-up because raw machine translation does
not survive trauma-informed register; each Skill body needs human review.
"""

from pathways.i18n.detect import detect_language
from pathways.i18n.responses import bilingual

__all__ = ["detect_language", "bilingual"]
