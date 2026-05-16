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
from typing import Any, Optional

from pathways.llm import LLMUnavailable, get_llm
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
        profile = _apply_parole_reminder_capture(profile, state)
        return {
            "intake": profile,
            "intake_stage": IntakeStage.DONE,
            "intake_complete": True,
            "next_node": "retrieve",
        }

    # Run extraction. The merged profile carries forward what we already had.
    extracted = _extract(state)
    profile = _merge_into_profile(state.intake, extracted, state)
    profile = _apply_parole_reminder_capture(profile, state)

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
    """Run the LLM extractor; fall back to the keyword heuristic on
    LLMUnavailable (no key, model error, etc) or any parse failure."""
    try:
        return _llm_extract(state.user_message)
    except LLMUnavailable:
        return _heuristic_extract(state.user_message)
    except Exception:
        return _heuristic_extract(state.user_message)


def _llm_extract(user_message: str) -> dict:
    text = get_llm("fast").invoke(
        system=INTAKE_SYSTEM_PROMPT,
        user=user_message,
        max_tokens=500,
        temperature=0.0,
    )
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def _heuristic_extract(user_message: str) -> dict:
    """Demo-mode fallback. Keyword-based, intentionally simple.

    Phase 3 update: collect ALL matching need categories rather than
    stopping at the first. This is what enables multi-need routing
    ('I need food AND a job') to surface both pathways instead of one.
    Also adds Spanish keyword coverage for the same categories so
    Spanish-first messages get routed correctly even before the LLM
    extractor sees them.
    """
    msg = user_message.lower()

    # English + Spanish keyword sets, indexed by category.
    # Order matters only for `top_need` (first match wins); all matches
    # accumulate into `needs`.
    NEED_KEYWORDS = [
        ("housing", [
            # English
            "shelter", "place to stay", "nowhere to live", "homeless",
            "housing", "place to sleep", "bed for the night", "roof",
            "section 8", "public housing", "subsidized housing", "pha",
            "live in section 8",
            # Spanish
            "vivienda", "techo", "albergue", "donde dormir", "donde quedarme",
            "sin casa", "en la calle",
        ]),
        ("benefits", [
            # English
            "snap", "food stamps", "medicaid", "tanf", "benefits", "food",
            "ssi", "ssdi", "social security",
            # Spanish
            "estampillas", "comida", "alimentos", "beneficios",
            "seguridad social", "medicaid", "ayuda alimentaria",
        ]),
        ("employment", [
            "job", "work", "hire", "employment", "career", "fair chance",
            "trabajo", "empleo", "contratar", "contratacion", "contratación",
        ]),
        ("id_documents", [
            "id ", "state id", "social security card", "driver's license",
            "driver license", "license back", "birth certificate",
            "identificacion", "identificación", "id de texas", "licencia",
            "tarjeta", "acta", "certificado",
        ]),
        ("record_clearing", [
            "expunge", "expunction", "non-disclosure", "seal", "clear my record",
            "background check",
            "borrar", "limpiar", "antecedentes", "sellar", "expurgar",
        ]),
        ("legal_question", [
            "can i ", "am i eligible", "rule", "law", "right",
            "puedo ", "tengo derecho", "es legal", "ley",
        ]),
        ("parole_reporting", [
            "parole officer", "po appointment", "report to parole",
            "miss my report", "missed my report",
            "my po", "see my po", "see po", "report to my po", "report to po",
            "check in with parole", "check-in with parole",
            "oficial de libertad", "oficial po", "reportarme",
        ]),
    ]

    needs: list[str] = []
    for category, keywords in NEED_KEYWORDS:
        if any(k in msg for k in keywords):
            needs.append(category)
    top_need = needs[0] if needs else "unknown"
    secondary_needs = needs[1:] if len(needs) > 1 else []

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
    elif "brownsville" in msg or "mcallen" in msg or "harlingen" in msg:
        region = "Lower Rio Grande Valley"

    supervision = "unknown"
    if "parole" in msg or "libertad condicional" in msg:
        supervision = "parole"
    elif "probation" in msg or "probatoria" in msg:
        supervision = "probation"

    # ZIP extraction: pick the first 5-digit run that looks like a TX ZIP
    # (starts with 7). The current state of pathways is TX-only so any
    # non-TX-looking ZIP we just ignore; the compliance auditor handles
    # out-of-state messaging separately.
    zipcode: Optional[str] = None
    import re as _re
    for m in _re.finditer(r"(?<!\d)(\d{5})(?!\d)", user_message):
        candidate = m.group(1)
        if candidate.startswith("7"):
            zipcode = candidate
            break

    # Light language inference for heuristic-only mode. The dedicated
    # detector in pathways/i18n/detect.py is the better path; this is
    # the fallback when the detector hasn't been called yet.
    from pathways.i18n.detect import detect_language

    return {
        "name": None,
        "top_need": top_need,
        "secondary_needs": secondary_needs,
        "zipcode": zipcode,
        "city": city,
        "region": region,
        "supervision_status": supervision,
        "veteran": True if any(v in msg for v in ("veteran", "veterano")) else None,
        "language": detect_language(user_message),
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

    # Language: default is en. Two paths can upgrade to es:
    #   1. The extractor (LLM or heuristic) returns "es"
    #   2. The dedicated detector in pathways/i18n/detect.py flags Spanish
    # Either is enough. Once a profile is set to es, never downgrade to en
    # mid-conversation just because one turn happened to be in English
    # (it's normal for bilingual users to mix).
    if profile.language == "en":
        from pathways.i18n.detect import detect_language
        if extracted.get("language") == "es" or detect_language(state.user_message) == "es":
            profile.language = "es"

    if extracted.get("age_range") and not profile.age_range:
        if extracted["age_range"] in ("18-24", "25-34", "35-44", "45-54", "55-64", "65+"):
            profile.age_range = extracted["age_range"]

    if extracted.get("prison_facility") and not profile.prison_facility:
        profile.prison_facility = str(extracted["prison_facility"]).strip()

    return profile


def _apply_parole_reminder_capture(
    profile: IntakeProfile, state: PathwaysState,
) -> IntakeProfile:
    """If the draft node offered a parole reminder on a previous turn,
    check this turn's reply for a yes/no + date and persist accordingly.

    Mutates a copy of the profile, never the caller's instance.
    """
    if not profile.parole_reminder_offered:
        return profile
    if profile.parole_reminder_opt_in is not None:
        # Already captured; do nothing further.
        return profile
    supervision = profile.supervision_status
    val = supervision.value if hasattr(supervision, "value") else str(supervision)
    if val != "parole":
        return profile

    try:
        from pathways.parole_reminders.service import record_reminder_if_opt_in
    except Exception:
        return profile

    outcome = record_reminder_if_opt_in(
        thread_id=state.session_id,
        user_message=state.user_message or "",
        intake_supervision_is_parole=True,
        reminder_was_offered=True,
    )
    if outcome is None:
        return profile

    accepted, parsed_date = outcome
    return profile.model_copy(update={
        "parole_reminder_opt_in": accepted,
        "parole_check_in_date": parsed_date if accepted else None,
    })
