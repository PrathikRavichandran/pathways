"""
Pydantic state types for the Pathways LangGraph state machine.

The state object is the only thing that flows between nodes. Keep it
small, typed, and serializable (LangGraph checkpoints serialize state
to its persistence backend), so anything non-JSON-friendly here breaks
durability.

Design notes
------------
- Field names are stable; downstream nodes import and read fields by
  name. Renames require a coordinated change across nodes/.
- We carry the conversation history inside state rather than relying on
  LangGraph's MessagesState, because we want explicit control over what
  gets fed to each node (the audit node, for instance, should see the
  draft response but not the entire chat history).
- We do not carry PII fields. The intake.py node extracts a minimum
  routing-relevant slice (region, top need, supervision_status) and
  discards the rest before writing to state. Full PII handling happens
  upstream of the graph in the FastAPI ingress layer where the
  pii_redact hook also runs.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TopNeed(str, Enum):
    HOUSING = "housing"
    EMPLOYMENT = "employment"
    BENEFITS = "benefits"
    ID_DOCUMENTS = "id_documents"
    RECORD_CLEARING = "record_clearing"
    LEGAL_QUESTION = "legal_question"
    PAROLE_REPORTING = "parole_reporting"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


class SupervisionStatus(str, Enum):
    OFF_PAPER = "off_paper"
    PAROLE = "parole"
    PROBATION = "probation"
    DEFERRED_ADJUDICATION = "deferred_adjudication"
    UNKNOWN = "unknown"


class CrisisCategory(str, Enum):
    SUICIDE = "suicide"
    SELF_HARM = "self_harm"
    SUBSTANCE = "substance"
    DOMESTIC_VIOLENCE = "domestic_violence"
    VIOLENCE_TO_OTHERS = "violence_to_others"
    SEXUAL_VIOLENCE = "sexual_violence"
    HOUSING_EMERGENCY = "housing_emergency"


class IntakeStage(str, Enum):
    """Phase 1: where we are in the slot-filling intake.

    Used by the intake node to decide what to do with the next user
    message. The graph treats `done` as 'continue to retrieve'; every
    other value short-circuits intake back to END after the slot prompt
    is set on `final_response`.
    """
    GREETING = "greeting"             # first contact, no slots filled yet
    COLLECT_NAME = "collect_name"     # waiting for the user to give a name
    COLLECT_LOCATION = "collect_location"  # waiting for ZIP or city
    COLLECT_NEED = "collect_need"     # waiting for top-need free-form answer
    DONE = "done"                     # all required slots filled, route to retrieve


class AuditVerdict(str, Enum):
    PASS = "pass"
    SOFT_BLOCK = "soft_block"
    HARD_BLOCK = "hard_block"


# ---------------------------------------------------------------------------
# Substructures
# ---------------------------------------------------------------------------


class IntakeProfile(BaseModel):
    """Routing-relevant intake state collected over multiple SMS turns.

    Phase 1 added `name`, `age_range` (bucketed, not exact), and
    `prison_facility`. Name and age_range are the only fields that
    arguably qualify as PII; `age_range` is bucketed deliberately so
    we never persist an exact birth year. `name` is collected with
    consent as part of the slot-filling intake and is used only to
    address the user (never written to logs).
    """
    state: Literal["TX"] = "TX"  # Pathways is TX-only by deployment
    name: Optional[str] = None  # first name or nickname only; consent-gated
    age_range: Optional[
        Literal["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    ] = None
    region: Optional[str] = None  # e.g. "Greater Houston"
    city: Optional[str] = None
    zipcode: Optional[str] = None
    prison_facility: Optional[str] = None  # e.g. "Beto Unit", "Coffield"
    top_need: TopNeed = TopNeed.UNKNOWN
    secondary_needs: list[TopNeed] = Field(default_factory=list)
    supervision_status: SupervisionStatus = SupervisionStatus.UNKNOWN
    time_since_release_days: Optional[int] = None
    veteran: Optional[bool] = None
    language: Literal["en", "es"] = "en"

    # Phase 6: parole-reporting reminder. When supervision_status is parole
    # we offer to text the user the day before each check-in (highest
    # claimed impact on technical-violation recidivism per the literature).
    # Opt-in is explicit, never inferred.
    parole_reminder_opt_in: Optional[bool] = None
    parole_check_in_date: Optional[date] = None
    parole_reminder_offered: bool = False  # so we don't re-offer every turn


class Retrieval(BaseModel):
    """One round of retrieval against pathways-corpus or tx-resources."""
    source: Literal["pathways-corpus", "tx-resources"]
    query: str
    confidence: float
    results: list[dict]  # opaque to the graph; node-specific schemas
    gated_low_confidence: bool = False


class AuditResult(BaseModel):
    """Output of the compliance-auditor sub-agent."""
    verdict: AuditVerdict
    issues: list[dict] = Field(default_factory=list)
    rewrite_hint: Optional[str] = None


class CrisisSignal(BaseModel):
    """Detected by the crisis_keyword_check hook upstream of the graph."""
    fired: bool
    category: Optional[CrisisCategory] = None
    raw_message: Optional[str] = None


# ---------------------------------------------------------------------------
# The graph state
# ---------------------------------------------------------------------------


class PathwaysState(BaseModel):
    """
    The single state object that flows between LangGraph nodes.

    Nodes read fields they need and return a partial state dict (or full
    state) that gets merged into the running state by LangGraph's reducer.
    Don't mutate `state` in place; return new values.
    """

    # ---- Identity -----------------------------------------------------------
    session_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)

    # ---- Incoming -----------------------------------------------------------
    user_message: str
    conversation_history: list[dict] = Field(default_factory=list)
    # Each dict: {"role": "user"|"assistant", "content": "...", "ts": iso}

    # ---- Crisis (set by hook, read by graph router) ------------------------
    crisis: CrisisSignal = Field(default_factory=lambda: CrisisSignal(fired=False))

    # ---- Intake -------------------------------------------------------------
    intake: IntakeProfile = Field(default_factory=IntakeProfile)
    intake_stage: IntakeStage = IntakeStage.GREETING
    # Backward-compat shim. Existing tests + nodes read `intake_complete`;
    # we now derive it from `intake_stage == DONE` but keep the field so
    # old code paths still work without modification.
    intake_complete: bool = False
    # The prompt we sent the user on the previous turn, so the next turn's
    # extraction knows what slot the user is responding to.
    last_assistant_prompt: Optional[str] = None

    # ---- Retrieval ----------------------------------------------------------
    retrievals: list[Retrieval] = Field(default_factory=list)

    # ---- Matching -----------------------------------------------------------
    matched_resources: list[dict] = Field(default_factory=list)

    # ---- Draft and audit ----------------------------------------------------
    draft_response: Optional[str] = None
    audit: Optional[AuditResult] = None
    audit_revision_attempts: int = 0
    MAX_AUDIT_REVISIONS: int = 2  # cap retries to prevent infinite loop

    # ---- Output -------------------------------------------------------------
    final_response: Optional[str] = None
    escalated_to_human: bool = False
    escalation_reason: Optional[str] = None

    # ---- Routing -----------------------------------------------------------
    # The next node to run. The graph uses this to switch via conditional edges.
    # END is used by the intake node when it's in the middle of slot-filling
    # and wants to ship a slot prompt back to the user without running the
    # rest of the pipeline.
    next_node: Optional[
        Literal["intake", "retrieve", "match", "draft", "audit", "escalate", "send", "END"]
    ] = None

    # ---- Channel + identity (Phase 1) --------------------------------------
    # Which channel this conversation came in over. Default sms preserves
    # backward compat; Phase 4 PWA sets web; Phase 5 voice sets voice.
    channel: Literal["sms", "web", "voice"] = "sms"
