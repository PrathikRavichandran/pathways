"""
Web channel endpoints for the Phase 4 PWA.

The PWA is a single-page React app served separately (Vercel free tier).
It calls these endpoints to drive the same LangGraph state machine the
SMS channel uses. The only thing that changes per channel is the
`channel` field on PathwaysState, which the draft node reads to format
output appropriately:

    sms  : plaintext, 160-segment aware, no markdown
    web  : structured JSON (markdown text + resource cards)
    voice: single sentence, no URLs (Phase 5)

Why a separate router and not just /sms with a header?
- The two channels have different idempotency and signature needs.
  /sms verifies Twilio's HMAC and dedupes by MessageSid; /web verifies
  CORS origin and dedupes by browser session UUID.
- The response shapes are different. /sms returns TwiML XML; /web
  returns structured JSON the React client renders into chat bubbles.
- Splitting the routers makes the FastAPI auto-docs (/docs) clearer.

Endpoints
- POST /web/session : create or refresh a browser session UUID
- POST /web/turn    : process one user message, return reply + resources
- GET  /web/health  : liveness for the PWA to probe
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from pathways.audit import service as audit_service
from pathways.dashboard import analytics as dashboard_analytics
from pathways.graph import get_app
from pathways.sessions import (
    thread_id_for_web,
    touch_session,
)
from pathways.sessions.idempotency import is_opted_out, mark_opted_out
from pathways.state import CrisisCategory, CrisisSignal

logger = logging.getLogger("pathways.api.web")

router = APIRouter(prefix="/web", tags=["web"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    """Optional language hint from the client (Accept-Language header parsed
    on the JS side). If absent, the language detector decides on first turn."""
    language_hint: Optional[str] = Field(
        default=None,
        description="Optional 'en' or 'es' hint from the browser",
        pattern=r"^(en|es)$",
    )


class CreateSessionResponse(BaseModel):
    session_id: str = Field(description="Opaque UUID the client persists in localStorage")
    thread_id: str = Field(description="Salted-hash thread id (for debugging only)")


class TurnRequest(BaseModel):
    session_id: str = Field(description="UUID returned by /web/session")
    message: str = Field(min_length=1, max_length=4000)


class ResourceCard(BaseModel):
    """Lightweight projection of a tx_resources entry the PWA renders.

    lat / lon are forwarded from the underlying resource record when
    present. Statewide hotlines (211 Texas, TRLA, 988) don't carry
    coordinates and arrive with both fields null; the PWA's map view
    filters those out and renders no pin for them.
    """
    id: str
    name: str
    description: Optional[str] = None
    phone: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    distance_miles: Optional[float] = None
    languages: list[str] = Field(default_factory=list)
    lat: Optional[float] = None
    lon: Optional[float] = None


class TurnResponse(BaseModel):
    reply: str = Field(description="User-facing markdown text")
    language: str = Field(description="'en' or 'es'")
    intake_stage: Optional[str] = Field(
        description="None when intake is done; otherwise the slot being collected"
    )
    needs: list[str] = Field(
        default_factory=list,
        description="Categories the intake captured for this user",
    )
    resources: list[ResourceCard] = Field(default_factory=list)
    escalated: bool = False
    escalation_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Crisis check helper (imports from main.py via shared path)
# ---------------------------------------------------------------------------


def _run_crisis_check(message: str) -> CrisisSignal:
    """Same logic the SMS path uses; deterministic regex via the hook script."""
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    hooks_dir = os.path.abspath(os.path.join(here, "..", "..", ".claude", "hooks"))
    if hooks_dir not in sys.path:
        sys.path.insert(0, hooks_dir)
    try:
        import crisis_keyword_check  # type: ignore
    except ImportError:
        return CrisisSignal(fired=False)
    cat = crisis_keyword_check.detect_crisis(message)
    if cat:
        try:
            return CrisisSignal(
                fired=True, category=CrisisCategory(cat), raw_message=message,
            )
        except ValueError:
            return CrisisSignal(fired=True, raw_message=message)
    return CrisisSignal(fired=False)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health")
def web_health() -> dict:
    return {"status": "ok", "channel": "web"}


@router.post("/session", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    """Mint a new browser session UUID + return the derived thread_id.

    The client persists `session_id` in localStorage and sends it on every
    subsequent /web/turn call. The salted thread_id is derived from it via
    the same hashing path the SMS channel uses for phone numbers, so the
    Postgres checkpoint table never stores the raw UUID."""
    session_uuid = str(uuid.uuid4())
    tid = thread_id_for_web(session_uuid)
    return CreateSessionResponse(session_id=session_uuid, thread_id=tid)


@router.post("/turn", response_model=TurnResponse)
def web_turn(req: TurnRequest) -> TurnResponse:
    """Process one user message and return structured reply + resources.

    Mirrors the SMS path's structure: crisis check first, opt-out check
    second, graph invocation third, response shaping fourth. State persists
    across turns via the LangGraph PostgresSaver keyed on the derived
    thread_id, so a user can refresh the browser and continue the same
    intake from where they left off (as long as their localStorage survives).
    """
    if not req.session_id or not req.session_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id is required (call POST /web/session first)",
        )

    thread_id = thread_id_for_web(req.session_id)

    if is_opted_out(thread_id):
        return TurnResponse(
            reply="You have opted out of messages. Click 'reset session' to start again.",
            language="en",
            intake_stage=None,
            escalated=False,
        )

    # TCPA STOP / HELP / START parity with the SMS path. Less load-bearing
    # on the web channel (there is a UI button) but keep the floor consistent.
    keyword = _compliance_keyword(req.message)
    if keyword == "stop":
        mark_opted_out(thread_id)
        return TurnResponse(
            reply="You will not receive further messages. Reload to start over.",
            language="en",
            intake_stage=None,
        )
    if keyword == "help":
        return TurnResponse(
            reply=(
                "I'm Pathways, a navigator for people just released in Texas. "
                "Tell me your situation and I'll find resources. Click 'reset "
                "session' or send 'stop' to opt out."
            ),
            language="en",
            intake_stage=None,
        )

    touch_session(thread_id)
    crisis = _run_crisis_check(req.message)

    final = _invoke_graph(req.message, crisis, thread_id)
    return _shape_response(final, default_language="en")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _compliance_keyword(body: str) -> Optional[str]:
    if not body:
        return None
    norm = body.strip().lower()
    if norm in ("stop", "stopall", "unsubscribe", "cancel", "end", "quit"):
        return "stop"
    if norm in ("start", "unstop", "yes"):
        return "start"
    if norm == "help":
        return "help"
    return None


def _invoke_graph(
    user_message: str, crisis: CrisisSignal, thread_id: str
) -> dict[str, Any]:
    """Invoke the compiled graph with web channel + thread config.

    Mirrors the SMS path's invocation pattern; the only difference is
    `channel="web"` which the draft node reads to format markdown
    instead of plaintext.
    """
    app = get_app()
    config = {"configurable": {"thread_id": thread_id}}
    input_state: dict[str, Any] = {
        "session_id": thread_id,
        "user_message": user_message,
        "crisis": crisis,
        "channel": "web",
    }
    final: Any = None
    try:
        final = app.invoke(input_state, config=config)
    except Exception as exc:
        logger.exception("graph invocation failed: %s", exc)
        final = {
            "final_response": (
                "I hit a snag. For anything urgent call 211 (any phone, 24/7). "
                "Try me again in a minute."
            ),
            "intake": {"language": "en"},
        }

    # Caseworker dashboard analytics. Never raises (record_turn swallows
    # its own exceptions); analytics must not affect the user response path.
    reply_text = ""
    if isinstance(final, dict):
        reply_text = str(final.get("final_response") or "")
    try:
        event = dashboard_analytics.event_from_state(
            final_state=final,
            thread_id=thread_id,
            channel="web",
            user_message=user_message,
            reply=reply_text,
            crisis_fired=bool(crisis.fired),
        )
        dashboard_analytics.record_turn(event)
    except Exception:
        logger.exception("dashboard analytics write failed (non-fatal)")

    # Audit log: operator-side full-content record. Same contract.
    try:
        crisis_cat = (
            crisis.category.value if crisis.category and hasattr(crisis.category, "value")
            else (str(crisis.category) if crisis.category else None)
        )
        audit_event = audit_service.event_from_state(
            final_state=final,
            thread_id=thread_id,
            channel="web",
            user_message=user_message,
            reply=reply_text,
            crisis_fired=bool(crisis.fired),
            crisis_category=crisis_cat,
        )
        audit_service.record_turn(audit_event)
    except Exception:
        logger.exception("audit write failed (non-fatal)")

    if hasattr(final, "model_dump"):
        return final.model_dump(mode="json")
    return _coerce_to_dict(final)


def _coerce_float(v: Any) -> Optional[float]:
    """Best-effort cast a resource-record field to float for the map.

    The underlying resources arrive from a mix of sources (Postgres
    returns Decimals, the seed JSON returns Python floats or ints, the
    nearby ranker injects floats). Statewide records have no coord and
    show up as None / missing. Anything that can't be cast cleanly
    returns None so the PWA's map view treats the row as un-pinable.
    """
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_to_dict(state: Any) -> dict[str, Any]:
    """LangGraph returns a dict with mixed Pydantic + primitives;
    flatten everything to JSON-friendly types."""
    if not isinstance(state, dict):
        return {"final_response": str(state)}
    out: dict[str, Any] = {}
    for k, v in state.items():
        if hasattr(v, "model_dump"):
            out[k] = v.model_dump(mode="json")
        elif isinstance(v, list):
            out[k] = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in v
            ]
        elif hasattr(v, "value"):
            out[k] = v.value
        else:
            out[k] = v
    return out


def _shape_response(final: dict[str, Any], default_language: str) -> TurnResponse:
    """Project the graph's final state into the PWA-shaped response."""
    intake = final.get("intake") or {}
    if hasattr(intake, "model_dump"):
        intake = intake.model_dump(mode="json")

    language = (intake.get("language") if isinstance(intake, dict) else None) or default_language
    intake_stage = final.get("intake_stage")
    if hasattr(intake_stage, "value"):
        intake_stage = intake_stage.value

    matched = final.get("matched_resources") or []
    cards: list[ResourceCard] = []
    for m in matched[:6]:
        if not isinstance(m, dict):
            continue
        cards.append(
            ResourceCard(
                id=str(m.get("id") or ""),
                name=str(m.get("name") or ""),
                description=m.get("description"),
                phone=m.get("phone"),
                url=m.get("url"),
                category=m.get("category"),
                distance_miles=m.get("distance_miles"),
                languages=list(m.get("languages") or []),
                lat=_coerce_float(m.get("lat")),
                lon=_coerce_float(m.get("lon")),
            )
        )

    needs: list[str] = []
    if isinstance(intake, dict):
        top = intake.get("top_need")
        if top and top != "unknown":
            needs.append(top if isinstance(top, str) else getattr(top, "value", str(top)))
        for n in (intake.get("secondary_needs") or []):
            v = n if isinstance(n, str) else getattr(n, "value", str(n))
            if v and v != "unknown" and v not in needs:
                needs.append(v)

    return TurnResponse(
        reply=final.get("final_response") or "",
        language=language,
        intake_stage=intake_stage if intake_stage != "done" else None,
        needs=needs,
        resources=cards,
        escalated=bool(final.get("escalated_to_human")),
        escalation_reason=final.get("escalation_reason"),
    )
