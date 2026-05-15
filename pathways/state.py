"""
Pydantic state types for the Pathways LangGraph state machine.

The state object is the only thing that flows between nodes. Keep it
small, typed, and serializable — LangGraph checkpoints serialize state
to its persistence backend, so anything non-JSON-friendly here breaks
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

from datetime import datetime
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


class AuditVerdict(str, Enum):
    PASS = "pass"
    SOFT_BLOCK = "soft_block"
    HARD_BLOCK = "hard_block"


# ---------------------------------------------------------------------------
# Substructures
# ---------------------------------------------------------------------------


class IntakeProfile(BaseModel):
    """Minimum routing-relevant intake state. No PII."""
    state: Literal["TX"] = "TX"  # Pathways is TX-only by deployment
    region: Optional[str] = None  # e.g. "Greater Houston"
    city: Optional[str] = None
    zipcode: Optional[str] = None
    top_need: TopNeed = TopNeed.UNKNOWN
    secondary_needs: list[TopNeed] = Field(default_factory=list)
    supervision_status: SupervisionStatus = SupervisionStatus.UNKNOWN
    time_since_release_days: Optional[int] = None
    veteran: Optional[bool] = None
    language: Literal["en", "es"] = "en"


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
    Don't mutate `state` in place — return new values.
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
    intake_complete: bool = False  # set true after intake.py routes

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
    next_node: Optional[
        Literal["intake", "retrieve", "match", "draft", "audit", "escalate", "send", "END"]
    ] = None
