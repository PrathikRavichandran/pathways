"""intake node, Phase 1: stateful slot-filling first-touch.

Responsibilities:

1. If crisis was already detected by the upstream hook, route directly
   to escalate. No slot-filling, no retrieval, no waiting.

2. Otherwise, run the LLM/heuristic extractor on the user's message to
   pull whatever routing-relevant fields we can find. The extracted
   values are MERGED into the persisted IntakeProfile (never overwritten
   with `unknown` if we already have a value).

3. Inspect the merged profile. If any of the three required slots
   (name, location, top_need) is still empty, ship the prompt for that
   slot back to the user as `final_response` and route to END. The
   checkpointer persists the partial profile so the next SMS turn from
   the same phone resumes the same intake.

4. Once all three required slots are filled, set intake_stage=DONE
   (and the backward-compat intake_complete=True flag) and route to
   retrieve. The retrieve/match/draft/audit pipeline runs as before.

Phase 1 vs Phase 0
------------------
- Phase 0 intake was one-shot: extract on first message, set
  intake_complete=True, route to retrieve regardless of completeness.
- Phase 1 intake iterates over multiple SMS turns. Field merge ensures
  we never lose data we already have. The slot-filling is asked one
  question per turn, in trauma-informed order (name, location, need).
"""

from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic
from pathways.state import (
    IntakeProfile,
    IntakeStage,
    PathwaysState,
    SupervisionStatus,
    TopNeed,
)
from pathways.nodes.intake_slots import (
    REQUIRED_SLOTS,
    Slot,
    extract_name_from_reply,
    extract_zip_or_city_from_reply,
    next_missing_slot,
    prompt_for_slot,
    stage_for_slot,
)


_CLIENT: Anthropic | None = None


def _client() -> Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _CLIENT


INTAKE_SYSTEM_PROMPT = """You extract routing fields from a user message for a Texas reentry navigation assistant. Return ONLY a JSON object with these fields. Do not include prose.

{
  "name": "<first name or nickname if user shared one, else null>",
  "top_need": "housing" | "employment" | "benefits" | "id_documents" | "record_clearing" | "legal_question" | "parole_reporting" | "crisis" | "unknown",
  "secondary_needs": [<same enum>],
  "zipcode": "<5-digit US zip if mentioned, else null>",
  "city": "<TX city if user mentioned, else null>",
  "region": "<one of: Greater Houston, DFW, Austin, San Antonio, Rio Grande Valley, El Paso, East Texas, West Texas, Statewide, null>",
  "supervision_status": "off_paper" | "parole" | "probation" | "deferred_adjudication" | "unknown",
  "veteran": true | false | null,
  "language": "en" | "es",
  "age_range": "18-24" | "25-34" | "35-44" | "45-54" | "55-64" | "65+" | null,
  "prison_facility": "<TDCJ unit name if mentioned, else null>"
}

Rules:
- Be conservative: when a field is not clearly indicated, use null or "unknown".
- Do not infer language from a single word; require sustained Spanish or an explicit "español".
- Do not infer city from a region (Houston is Greater Houston; Dallas/Fort Worth is DFW).
- If the user is replying to a specific question (e.g., they were just asked for their name), pull the answer to that question."""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(state: PathwaysState) -> dict[str, Any]:
    """LangGraph node entry point. Returns partial state."""

    # Hard short-circuit on crisis signals from the upstream hook.
    if state.crisis.fired:
        return {
            "next_node": "escalate",
            "escalation_reason": f"crisis_hook:{state.crisis.category}",
        }

    # Backward-compat fast path: if the caller has set intake_complete=True
    # explicitly (Phase 0 callers + many existing tests), skip slot-filling
    # and go straight to retrieve. Phase 1 callers either leave it False
    # (default) and let slot-filling run, or set intake_stage=DONE.
    if state.intake_complete or state.intake_stage == IntakeStage.DONE:
        # Still run extraction so we capture any new info from this turn,
        # but never re-prompt for slots.
        extracted = _extract(state)
        profile = _merge_into_profile(state.intake, extracted, state)
        return {
            "intake": profile,
            "intake_stage": IntakeStage.DONE,
            "intake_complete": True,
            "next_node": "retrieve",
        }

    # Run extraction. The merged profile carries forward what we already had.
    extracted = _extract(state)
    profile = _merge_into_profile(state.intake, extracted, state)

    # Decide what to do next based on which required slot is still missing.
    missing = next_missing_slot(profile)
    if missing is not None:
        prompt = prompt_for_slot(missing, profile)
        return {
            "intake": profile,
            "intake_stage": stage_for_slot(missing),
            "intake_complete": False,
            "last_assistant_prompt": prompt,
            "final_response": prompt,
            "next_node": "END",
        }

    # All required slots are filled. Continue into retrieve/match/draft/audit.
    return {
        "intake": profile,
        "intake_stage": IntakeStage.DONE,
        "intake_complete": True,
        "last_assistant_prompt": None,
        "next_node": "retrieve",
    }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _extract(state: PathwaysState) -> dict:
    """Run the LLM extractor; fall back to the keyword heuristic on any
    error or when no API key is set (demo mode)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _heuristic_extract(state.user_message)
    try:
        return _llm_extract(state.user_message)
    except Exception:
        return _heuristic_extract(state.user_message)


def _llm_extract(user_message: str) -> dict:
    response = _client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=INTAKE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def _heuristic_extract(user_message: str) -> dict:
    """Demo-mode fallback. Keyword-based, intentionally simple."""
    msg = user_message.lower()
    need = "unknown"
    if any(k in msg for k in ["shelter", "place to stay", "nowhere to live",
                              "homeless", "housing", "place to sleep"]):
        need = "housing"
    elif any(k in msg for k in ["job", "work", "hire", "employment", "career"]):
        need = "employment"
    elif any(k in msg for k in ["snap", "food stamps", "medicaid", "tanf", "benefits", "food"]):
        need = "benefits"
    elif any(k in msg for k in ["id ", "social security card", "driver's license", "driver license"]):
        need = "id_documents"
    elif any(k in msg for k in ["expunge", "expunction", "non-disclosure", "seal", "clear my record"]):
        need = "record_clearing"
    elif any(k in msg for k in ["can i ", "am i eligible", "rule", "law"]):
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
    elif "el paso" in msg:
        city = "El Paso"; region = "El Paso"

    supervision = "unknown"
    if "parole" in msg:
        supervision = "parole"
    elif "probation" in msg:
        supervision = "probation"

    return {
        "name": None,  # the heuristic extractor never tries to pull a name
        "top_need": need,
        "secondary_needs": [],
        "zipcode": None,
        "city": city,
        "region": region,
        "supervision_status": supervision,
        "veteran": True if "veteran" in msg else None,
        "language": "es" if "español" in msg or "ayuda" in msg else "en",
        "age_range": None,
        "prison_facility": None,
    }


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------


def _merge_into_profile(
    current: IntakeProfile,
    extracted: dict,
    state: PathwaysState,
) -> IntakeProfile:
    """Merge extracted fields into the existing profile.

    Key rule: never overwrite a filled field with `unknown`/None. If the
    user said 'Houston' on turn 1 and 'I need food' on turn 2, the turn 2
    extractor shouldn't blank out city/region just because Houston isn't
    in turn 2's message.

    Additionally, use the per-stage extractors for slot-targeted replies:
    if intake_stage is COLLECT_NAME, the user's whole message is likely
    the answer ('Marcus' or 'My name is Marcus'). The LLM/heuristic
    extractor may miss it; the targeted slot extractor catches it.
    """
    profile = current.model_copy()

    # ---- Stage-targeted slot parses (capture replies to specific prompts).
    if state.intake_stage == IntakeStage.COLLECT_NAME and not profile.name:
        candidate = extract_name_from_reply(state.user_message)
        if candidate:
            profile.name = candidate
    if state.intake_stage == IntakeStage.COLLECT_LOCATION and not (
        profile.zipcode or profile.city
    ):
        zipcode, city = extract_zip_or_city_from_reply(state.user_message)
        if zipcode:
            profile.zipcode = zipcode
        if city and not profile.city:
            profile.city = city

    # ---- General extractor merge (catches multi-info first messages too).
    if extracted.get("name") and not profile.name:
        profile.name = str(extracted["name"]).strip().split()[0][:40]

    if extracted.get("top_need"):
        try:
            new_need = TopNeed(extracted["top_need"])
            if new_need != TopNeed.UNKNOWN or profile.top_need == TopNeed.UNKNOWN:
                profile.top_need = new_need
        except ValueError:
            pass

    if extracted.get("secondary_needs"):
        sec: list[TopNeed] = []
        for n in extracted["secondary_needs"]:
            try:
                sec.append(TopNeed(n))
            except ValueError:
                continue
        if sec:
            profile.secondary_needs = sec

    if extracted.get("zipcode") and not profile.zipcode:
        z = str(extracted["zipcode"]).strip()
        if len(z) == 5 and z.isdigit():
            profile.zipcode = z

    if extracted.get("city") and not profile.city:
        profile.city = str(extracted["city"]).strip()

    if extracted.get("region") and not profile.region:
        profile.region = str(extracted["region"]).strip()

    if extracted.get("supervision_status"):
        try:
            new_sup = SupervisionStatus(extracted["supervision_status"])
            if (new_sup != SupervisionStatus.UNKNOWN
                    or profile.supervision_status == SupervisionStatus.UNKNOWN):
                profile.supervision_status = new_sup
        except ValueError:
            pass

    if extracted.get("veteran") is not None and profile.veteran is None:
        profile.veteran = bool(extracted["veteran"])

    if extracted.get("language") in ("en", "es") and profile.language == "en":
        # Default is en; only upgrade to es on positive signal, never downgrade
        if extracted["language"] == "es":
            profile.language = "es"

    if extracted.get("age_range") and not profile.age_range:
        if extracted["age_range"] in ("18-24", "25-34", "35-44", "45-54", "55-64", "65+"):
            profile.age_range = extracted["age_range"]

    if extracted.get("prison_facility") and not profile.prison_facility:
        profile.prison_facility = str(extracted["prison_facility"]).strip()

    return profile
