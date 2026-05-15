"""
FastAPI ingress for Pathways.

Two routes for the demo:
- POST /sms — Twilio webhook receiver. Body is x-www-form-urlencoded with
  Twilio's standard fields. We extract Body and From, run the graph, and
  return a Twilio XML response.
- GET /health — liveness probe.

Production additions (not in this demo, documented in ARCHITECTURE.md):
- Twilio signature verification (cryptographic)
- Rate limiting per phone number
- Idempotency on MessageSid
- Persistent state via a checkpointer (Postgres or Redis) instead of
  the in-memory default
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Form, Response
from pydantic import BaseModel

from pathways.graph import get_app
from pathways.state import CrisisCategory, CrisisSignal, PathwaysState

logger = logging.getLogger("pathways.api")
logging.basicConfig(level=os.environ.get("PATHWAYS_LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the graph on startup so the first request isn't paying compile cost
    logger.info("Pathways API starting — compiling LangGraph state machine")
    get_app()
    logger.info("Graph compiled. Ready.")
    yield


api = FastAPI(
    title="Pathways API",
    description="Conversational AI navigator for post-incarceration reentry in Texas.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# SMS webhook (Twilio)
# ---------------------------------------------------------------------------


def _twilio_xml(message: str) -> str:
    """Wrap a message in TwiML so Twilio replies to the inbound SMS."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{_escape(message)}</Message></Response>"
    )


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _run_crisis_check(message: str) -> CrisisSignal:
    """Replay the same logic the UserPromptSubmit hook would run."""
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    hooks_dir = os.path.abspath(
        os.path.join(here, "..", "..", ".claude", "hooks")
    )
    if hooks_dir not in sys.path:
        sys.path.insert(0, hooks_dir)
    try:
        import crisis_keyword_check  # type: ignore
    except ImportError:
        return CrisisSignal(fired=False)
    cat = crisis_keyword_check.detect_crisis(message)
    if cat:
        return CrisisSignal(fired=True, category=CrisisCategory(cat), raw_message=message)
    return CrisisSignal(fired=False)


@api.post("/sms")
async def sms_inbound(
    Body: str = Form(...),
    From: str = Form(default=""),
    MessageSid: str = Form(default=""),
) -> Response:
    """Twilio inbound SMS webhook."""
    logger.info("Inbound SMS msg_sid=%s from=%s len=%d", MessageSid, From[-4:], len(Body))

    crisis = _run_crisis_check(Body)
    state = PathwaysState(
        session_id=MessageSid or str(uuid.uuid4()),
        user_message=Body,
        crisis=crisis,
    )

    try:
        final_state = get_app().invoke(state)
        # invoke returns the final state as a dict
        if isinstance(final_state, dict):
            reply = final_state.get("final_response") or "I'm here. Tell me what you need most right now."
        else:
            reply = getattr(final_state, "final_response", None) or "I'm here."
    except Exception as exc:
        logger.exception("Graph invocation failed: %s", exc)
        reply = (
            "I hit a snag on my end. For anything urgent, call 211 — they're "
            "24/7 and can help right now. Otherwise try me again in a few minutes."
        )

    return Response(content=_twilio_xml(reply), media_type="application/xml")


# ---------------------------------------------------------------------------
# Direct invocation (debug)
# ---------------------------------------------------------------------------


class DebugInvokeRequest(BaseModel):
    message: str
    session_id: str | None = None


@api.post("/_debug/invoke")
def debug_invoke(req: DebugInvokeRequest) -> dict[str, Any]:
    """Debug endpoint: run the graph and return the full final state.

    Not exposed in production. Useful for inspecting how the state machine
    routed a given message — which nodes fired, what retrieval looked like,
    what the audit verdict was.
    """
    crisis = _run_crisis_check(req.message)
    state = PathwaysState(
        session_id=req.session_id or str(uuid.uuid4()),
        user_message=req.message,
        crisis=crisis,
    )
    final = get_app().invoke(state)
    if isinstance(final, dict):
        return final
    return final.model_dump(mode="json")
