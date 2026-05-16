"""Slot-filling pure functions for the intake node.

Kept separate from `intake.py` so they have zero dependency on the LLM
extractor and can be unit-tested without subprocess or API calls. The
intake node imports `next_missing_slot` and `prompt_for_slot` from here
and uses them to decide whether to ask one more question or to continue
into the retrieve / match / draft / audit pipeline.

Three required slots, asked in this order:
    NAME      -> 'So I know what to call you, what's your first name?'
    LOCATION  -> 'What ZIP or city are you in or near?'
    TOP_NEED  -> 'What do you need most right now?'

Why this order and not another?
- Name first establishes a personal acknowledgment (trauma-informed
  intake guidance from SAMHSA TIP 57 prioritizes name-and-acknowledge
  before extracting structured info).
- Location second so when the user describes their need on turn 3, we
  can immediately ground the response to their region.
- Need third both because it is the most variable (sometimes already
  embedded in the first message) and because the previous two slots
  set up the warmth for an honest answer.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pathways.state import (
    IntakeProfile,
    IntakeStage,
    TopNeed,
)


class Slot(str, Enum):
    NAME = "name"
    LOCATION = "location"
    TOP_NEED = "top_need"


REQUIRED_SLOTS: list[Slot] = [Slot.NAME, Slot.LOCATION, Slot.TOP_NEED]


# ---------------------------------------------------------------------------
# Slot inspection
# ---------------------------------------------------------------------------


def next_missing_slot(profile: IntakeProfile) -> Optional[Slot]:
    """Return the first required slot that is not yet filled.

    Returns None when all required slots are filled (intake can route
    to retrieve).
    """
    if not (profile.name and profile.name.strip()):
        return Slot.NAME
    if not (profile.zipcode or profile.city):
        return Slot.LOCATION
    if profile.top_need == TopNeed.UNKNOWN:
        return Slot.TOP_NEED
    return None


def stage_for_slot(slot: Optional[Slot]) -> IntakeStage:
    """Map the slot we're collecting to the corresponding intake stage."""
    if slot is None:
        return IntakeStage.DONE
    return {
        Slot.NAME: IntakeStage.COLLECT_NAME,
        Slot.LOCATION: IntakeStage.COLLECT_LOCATION,
        Slot.TOP_NEED: IntakeStage.COLLECT_NEED,
    }[slot]


# ---------------------------------------------------------------------------
# Slot prompts (user-facing, trauma-informed, SMS-shaped)
# ---------------------------------------------------------------------------


def prompt_for_slot(slot: Slot, profile: IntakeProfile) -> str:
    """Return the SMS-shaped prompt for the slot we want next.

    Kept short (under 160 characters where possible) so Twilio does not
    split into multiple segments on basic phones. First-touch prompts
    include a one-line intro; subsequent prompts skip the intro.
    """
    language = profile.language or "en"
    name = (profile.name or "").strip()

    if language == "es":
        return _prompt_es(slot, name)
    return _prompt_en(slot, name)


def _prompt_en(slot: Slot, name: str) -> str:
    if slot == Slot.NAME:
        return (
            "Hi, I'm Pathways. I help people just released in Texas figure "
            "out next steps. So I know what to call you, what's your first "
            "name? Just a first name or nickname is fine."
        )
    if slot == Slot.LOCATION:
        you = f"{name}, " if name else ""
        return (
            f"{you}what ZIP code are you in or near? That helps me find "
            "resources close to you. If you don't know the ZIP, just the "
            "city name works."
        )
    if slot == Slot.TOP_NEED:
        you = f"{name}, " if name else ""
        return (
            f"thanks. {you}what do you need most right now? "
            "A place to stay, food, work, getting your ID back, anything. "
            "Tell me in your own words."
        )
    return ""


def _prompt_es(slot: Slot, name: str) -> str:
    if slot == Slot.NAME:
        return (
            "Hola, soy Pathways. Ayudo a personas recién liberadas en Texas. "
            "¿Cómo te puedo llamar? Solo tu nombre o apodo está bien."
        )
    if slot == Slot.LOCATION:
        you = f"{name}, " if name else ""
        return (
            f"{you}¿en qué código postal estás o cerca de cuál? "
            "Si no sabes el código, dime la ciudad."
        )
    if slot == Slot.TOP_NEED:
        you = f"{name}, " if name else ""
        return (
            f"gracias. {you}¿qué necesitas más en este momento? "
            "Un lugar para dormir, comida, trabajo, recuperar tu ID, "
            "lo que sea. Dímelo con tus palabras."
        )
    return ""


# ---------------------------------------------------------------------------
# Slot extractors (consume the user's reply and update the profile)
# ---------------------------------------------------------------------------


def extract_name_from_reply(reply: str) -> Optional[str]:
    """Parse a name out of a user reply to the COLLECT_NAME prompt.

    Handles both bare answers ("Marcus", "marcus") and conversational
    answers ("My name is Marcus", "I'm Marcus", "call me Marcus", "Marcus
    Jones"). Returns a stripped first name only, max 40 chars, no leading
    punctuation. Returns None if the reply does not contain a plausible
    name (e.g., empty, or 'I dont know').
    """
    if not reply:
        return None
    text = reply.strip()

    # Strip common lead-in phrases
    lead_in_patterns = [
        r"^(my\s+name\s+is|i'?m|i\s+am|call\s+me|name'?s|the\s+name'?s)\s+",
        r"^(it'?s|its)\s+",
    ]
    for pat in lead_in_patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()

    # Skip obvious decline responses
    decline_patterns = [
        r"^(no|none|nothing|n/?a|skip|pass|don'?t\s+know|idk|prefer\s+not)",
    ]
    for pat in decline_patterns:
        if re.match(pat, text, flags=re.IGNORECASE):
            return None

    # Take the first word (first name only); strip trailing punctuation.
    first_token = text.split()[0] if text.split() else ""
    first_token = re.sub(r"[^\w'-]+$", "", first_token)
    if not first_token:
        return None
    if len(first_token) > 40:
        first_token = first_token[:40]

    # Title case for friendliness ("marcus" -> "Marcus"; preserve "Lee-Ann").
    return first_token[:1].upper() + first_token[1:]


_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def extract_zip_or_city_from_reply(reply: str) -> tuple[Optional[str], Optional[str]]:
    """Return (zipcode, city) parsed from a COLLECT_LOCATION reply.

    Zip detection is a 5-digit match. City detection is a small TX-aware
    keyword pass. Returns either or both; absence is None. If both are
    found, both are returned.
    """
    if not reply:
        return (None, None)

    zip_match = _ZIP_RE.search(reply)
    zipcode = zip_match.group(1) if zip_match else None

    city = None
    lower = reply.lower()
    # Common TX cities. This is a starter list; Phase 2 expands via the
    # vendored USPS ZCTA file so we cover all TX places without keyword work.
    tx_cities = [
        ("houston", "Houston"),
        ("dallas", "Dallas"),
        ("fort worth", "Fort Worth"),
        ("austin", "Austin"),
        ("san antonio", "San Antonio"),
        ("el paso", "El Paso"),
        ("brownsville", "Brownsville"),
        ("mcallen", "McAllen"),
        ("laredo", "Laredo"),
        ("lubbock", "Lubbock"),
        ("waco", "Waco"),
        ("corpus christi", "Corpus Christi"),
        ("amarillo", "Amarillo"),
        ("tyler", "Tyler"),
        ("beaumont", "Beaumont"),
        ("killeen", "Killeen"),
        ("plano", "Plano"),
        ("arlington", "Arlington"),
        ("garland", "Garland"),
        ("irving", "Irving"),
    ]
    for needle, formatted in tx_cities:
        if needle in lower:
            city = formatted
            break

    return (zipcode, city)
