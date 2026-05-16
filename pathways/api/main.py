"""
FastAPI ingress for Pathways.

Phase 1 added:
- Per-phone-number sessions: each inbound SMS is keyed to a stable
  thread_id (sha256(salt + From)) so multiple turns from the same
  number share state via the LangGraph checkpointer.
- Twilio signature verification (X-Twilio-Signature HMAC) on /sms,
  skippable in demo via PATHWAYS_SKIP_TWILIO_SIG=1.
- Idempotency on MessageSid (Postgres dedup table; in-memory fallback)
  so Twilio's automatic retries do not double-process a turn.

Endpoints:
- POST /sms          Twilio webhook receiver. Body is x-www-form-urlencoded
                     with Twilio's standard fields. We extract Body, From,
                     and MessageSid, verify the signature, dedup, run the
                     graph with the per-phone thread_id, and return TwiML.
- POST /_debug/invoke Direct invocation for debugging. Bypasses Twilio.
                      Optional `from_number` lets you simulate multi-turn
                      from the same caller; defaults to an anonymous UUID.
- GET  /health       Liveness probe.
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Form, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pathways.api.twilio_signature import verify_twilio_signature
from pathways.graph import get_app
from pathways.sessions import (
    seen_message_sid,
    thread_id_for_phone,
    thread_id_for_web,
    touch_session,
)
from pathways.sessions.idempotency import is_opted_out, mark_opted_out
from pathways.state import CrisisCategory, CrisisSignal, PathwaysState

logger = logging.getLogger("pathways.api")
logging.basicConfig(level=os.environ.get("PATHWAYS_LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Pathways API starting (backend=%s)",
        os.environ.get("PATHWAYS_CHECKPOINT_BACKEND", "memory"),
    )
    # Warm the graph on startup so the first request isn't paying compile cost
    get_app()
    logger.info("Graph compiled. Ready.")
    yield


api = FastAPI(
    title="Pathways API",
    description="Conversational AI navigator for post-incarceration reentry in Texas.",
    version="0.2.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@api.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": "0.2.0",
        "checkpoint_backend": os.environ.get("PATHWAYS_CHECKPOINT_BACKEND", "memory"),
    }


# ---------------------------------------------------------------------------
# Helpers
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


def _is_compliance_keyword(body: str) -> Optional[str]:
    """Return 'stop' / 'help' / 'start' if the body matches the TCPA-mandated
    compliance keyword for this carrier behavior. Returns None otherwise.

    Phase 3 will fully wire the outbound side; Phase 1 only handles the
    inbound replies so that opt-out is recorded immediately even before
    outbound feedback exists.
    """
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


def _public_url(request: Request) -> str:
    """The full URL Twilio used to call us, reconstructed from
    PATHWAYS_PUBLIC_BASE_URL (preferred, since the HF Spaces proxy hides the
    real host) or the request itself as fallback."""
    base = os.environ.get("PATHWAYS_PUBLIC_BASE_URL", "").rstrip("/")
    if base:
        path = request.url.path
        query = request.url.query
        return f"{base}{path}" + (f"?{query}" if query else "")
    return str(request.url)


# ---------------------------------------------------------------------------
# /sms : Twilio webhook
# ---------------------------------------------------------------------------


@api.post("/sms")
async def sms_inbound(
    request: Request,
    Body: str = Form(...),
    From: str = Form(default=""),
    MessageSid: str = Form(default=""),
) -> Response:
    """Twilio inbound SMS webhook."""

    # 1. Verify Twilio signature (HMAC-SHA1 of URL + form params with auth token).
    sig = request.headers.get("X-Twilio-Signature")
    form = await request.form()
    form_params = {k: form.get(k, "") for k in form.keys()}
    if not verify_twilio_signature(_public_url(request), form_params, sig):
        return Response(
            content="Invalid Twilio signature",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    logger.info(
        "Inbound SMS msg_sid=%s from_last4=%s len=%d",
        MessageSid, (From or "")[-4:], len(Body),
    )

    # 2. Derive the durable thread_id (sha256 of From, never raw phone).
    if not From:
        thread_id = thread_id_for_web(MessageSid or str(uuid.uuid4()))
    else:
        thread_id = thread_id_for_phone(From)

    # 3. Compliance keywords: handle STOP / START / HELP at the ingress,
    #    NOT inside the graph (TCPA requires deterministic processing).
    keyword = _is_compliance_keyword(Body)
    if keyword == "stop":
        mark_opted_out(thread_id)
        return Response(
            content=_twilio_xml(
                "You will not receive further messages. Reply START to resume."
            ),
            media_type="application/xml",
        )
    if keyword == "start":
        # Mark opted-back-in via a separate column would be ideal; for Phase 1
        # we re-touch the session and let the next inbound resume normally.
        touch_session(thread_id)
        return Response(
            content=_twilio_xml(
                "Welcome back. Send a message any time and I'll help."
            ),
            media_type="application/xml",
        )
    if keyword == "help":
        return Response(
            content=_twilio_xml(
                "I'm Pathways, an SMS navigator for people just released "
                "in Texas. Reply with your situation and I'll find resources. "
                "Reply STOP to opt out."
            ),
            media_type="application/xml",
        )

    # 4. Suppress turn if this thread has opted out (TCPA compliance).
    if is_opted_out(thread_id):
        return Response(content="", status_code=status.HTTP_204_NO_CONTENT)

    # 5. Idempotency: if Twilio retries this same MessageSid, do not re-process.
    if seen_message_sid(MessageSid, thread_id):
        logger.info("Duplicate MessageSid %s; returning empty TwiML", MessageSid)
        return Response(
            content=_twilio_xml(""),  # empty body, Twilio won't double-send
            media_type="application/xml",
        )

    # 6. Bookkeeping: bump session counters (best-effort).
    touch_session(thread_id)

    # 7. Crisis check (deterministic regex, no model in path).
    crisis = _run_crisis_check(Body)

    # 8. Invoke the graph with the thread_id config so the checkpointer
    #    restores prior state and persists post-turn state.
    reply = await _invoke_graph(
        user_message=Body,
        crisis=crisis,
        thread_id=thread_id,
        channel="sms",
    )

    return Response(content=_twilio_xml(reply), media_type="application/xml")


# ---------------------------------------------------------------------------
# /_debug/invoke : direct invocation, bypasses Twilio
# ---------------------------------------------------------------------------


class DebugInvokeRequest(BaseModel):
    message: str
    session_id: Optional[str] = None     # legacy field; mapped to from_number
    from_number: Optional[str] = None    # preferred for multi-turn debugging
    channel: Optional[str] = "web"


@api.post("/_debug/invoke")
async def debug_invoke(req: DebugInvokeRequest) -> JSONResponse:
    """Debug endpoint: run the graph and return the full final state.

    Use `from_number` to simulate a multi-turn conversation from the same
    caller. Two POSTs with the same from_number share state via the
    checkpointer. Without from_number, a fresh UUID is generated per call
    (single-turn behavior).
    """
    crisis = _run_crisis_check(req.message)

    identity = req.from_number or req.session_id or str(uuid.uuid4())
    if identity.startswith("+") or identity.replace("-", "").isdigit():
        thread_id = thread_id_for_phone(identity)
    else:
        thread_id = thread_id_for_web(identity)

    reply = await _invoke_graph(
        user_message=req.message,
        crisis=crisis,
        thread_id=thread_id,
        channel=req.channel or "web",
    )

    # For the debug endpoint, also return the full state snapshot so callers
    # can inspect intake stage, retrievals, audit verdict, etc.
    state = _read_state(thread_id)
    return JSONResponse(
        {
            "thread_id": thread_id,
            "reply": reply,
            "state": state,
        }
    )


# ---------------------------------------------------------------------------
# Graph invocation helpers
# ---------------------------------------------------------------------------


async def _invoke_graph(
    user_message: str,
    crisis: CrisisSignal,
    thread_id: str,
    channel: str,
) -> str:
    """Invoke the compiled graph with the right config and return the
    user-facing reply text."""
    app = get_app()
    config = {"configurable": {"thread_id": thread_id}}

    # Build the input PARTIAL state. The checkpointer restores the rest.
    input_state: dict[str, Any] = {
        "session_id": thread_id,
        "user_message": user_message,
        "crisis": crisis,
        "channel": channel,
    }

    try:
        final = app.invoke(input_state, config=config)
        if isinstance(final, dict):
            reply = final.get("final_response") or _fallback_reply()
        else:
            reply = getattr(final, "final_response", None) or _fallback_reply()
    except Exception as exc:
        logger.exception("Graph invocation failed: %s", exc)
        reply = _fallback_reply()
    return reply


def _read_state(thread_id: str) -> Optional[dict]:
    """Return the most recent persisted state for a thread, or None if
    no checkpoint exists (or the backend doesn't support state reads)."""
    app = get_app()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = app.get_state(config)
        values = snapshot.values if snapshot else None
        if values is None:
            return None
        # values is either a dict (most checkpointers) or a Pydantic model.
        if hasattr(values, "model_dump"):
            return values.model_dump(mode="json")
        return dict(values) if not isinstance(values, dict) else values
    except Exception:
        return None


def _fallback_reply() -> str:
    return (
        "I hit a snag on my end. For anything urgent, call 211. They're "
        "24/7 and can help right now. Otherwise try me again in a few minutes."
    )
