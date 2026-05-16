"""Dashboard router.

Mounted at /dashboard. Token-gated. Read-only.

Endpoints:
    GET /dashboard/health           liveness (no auth)
    GET /dashboard/                 HTML landing page (auth)
    GET /dashboard/api/summary      JSON summary
    GET /dashboard/api/needs        JSON needs-by-region
    GET /dashboard/api/confidence   JSON confidence histogram
    GET /dashboard/api/escalations  JSON escalation reasons
    GET /dashboard/api/recent       JSON recent conversations (anonymized)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from pathways.dashboard import analytics, writeback
from pathways.dashboard.auth import Partner, authenticate

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "module": "dashboard", "version": "0.1.0"}


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    partner: Partner = Depends(authenticate),
    days: int = Query(7, ge=1, le=90),
) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "partner_name": partner.name,
            "is_superuser": partner.is_superuser,
            "scope": partner.scope or {},
            "days": days,
            "summary": analytics.summary(scope=partner.scope, days=days),
            "needs_rows": analytics.needs_by_region(
                scope=partner.scope, days=days
            )[:25],
            "confidence_bins": analytics.confidence_distribution(
                scope=partner.scope, days=days
            ),
            "escalations": analytics.escalation_reasons(
                scope=partner.scope, days=days
            )[:10],
            "recent": analytics.recent_conversations(
                scope=partner.scope, limit=20, days=days
            ),
        },
    )


@router.get("/api/summary")
def api_summary(
    partner: Partner = Depends(authenticate),
    days: int = Query(7, ge=1, le=90),
) -> JSONResponse:
    return JSONResponse({
        "partner": partner.name,
        "scope": partner.scope or {"superuser": True},
        "summary": analytics.summary(scope=partner.scope, days=days),
    })


@router.get("/api/needs")
def api_needs(
    partner: Partner = Depends(authenticate),
    days: int = Query(30, ge=1, le=365),
) -> JSONResponse:
    return JSONResponse({
        "partner": partner.name,
        "window_days": days,
        "rows": analytics.needs_by_region(scope=partner.scope, days=days),
    })


@router.get("/api/confidence")
def api_confidence(
    partner: Partner = Depends(authenticate),
    days: int = Query(30, ge=1, le=365),
    bins: int = Query(5, ge=2, le=20),
) -> JSONResponse:
    return JSONResponse({
        "partner": partner.name,
        "window_days": days,
        "bins": analytics.confidence_distribution(
            scope=partner.scope, days=days, bins=bins,
        ),
    })


@router.get("/api/escalations")
def api_escalations(
    partner: Partner = Depends(authenticate),
    days: int = Query(30, ge=1, le=365),
) -> JSONResponse:
    return JSONResponse({
        "partner": partner.name,
        "window_days": days,
        "rows": analytics.escalation_reasons(scope=partner.scope, days=days),
    })


@router.get("/api/recent")
def api_recent(
    partner: Partner = Depends(authenticate),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(25, ge=1, le=200),
) -> JSONResponse:
    return JSONResponse({
        "partner": partner.name,
        "window_days": days,
        "rows": analytics.recent_conversations(
            scope=partner.scope, limit=limit, days=days,
        ),
    })


# ---------------------------------------------------------------------------
# Phase 6 #3 - anonymous monthly trend reports (Markdown export)
# ---------------------------------------------------------------------------


@router.get("/api/report.md", response_class=PlainTextResponse)
def api_report_markdown(
    partner: Partner = Depends(authenticate),
    days: int = Query(30, ge=1, le=365),
) -> PlainTextResponse:
    """Anonymized Markdown report partners can paste into newsletters
    or email to their board. Same data the landing page renders, in a
    format that survives without the web UI."""
    md = analytics.render_markdown_report(
        partner_name=partner.name, scope=partner.scope, days=days,
    )
    return PlainTextResponse(
        md, media_type="text/markdown; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Phase 6 #5 - NGO write-back (caseworker -> user SMS relay)
# ---------------------------------------------------------------------------


class WritebackRequest(BaseModel):
    thread_id: str = Field(
        description="Display thread id from the dashboard's recent table",
        min_length=4, max_length=128,
    )
    message: str = Field(
        description="Plain-text SMS body to relay to the user",
        min_length=1, max_length=1000,
    )


class WritebackResponse(BaseModel):
    queued_id: int
    thread_id: str
    partner: str
    note: str


@router.post("/api/writeback", response_model=WritebackResponse)
def api_writeback(
    req: WritebackRequest,
    partner: Partner = Depends(authenticate),
) -> WritebackResponse:
    """Queue an SMS to a user. The caseworker never sees the phone
    number; Pathways resolves thread_id -> phone at send time via the
    forward map (operator-wired). The message is queued in
    `relay_messages` and drained by the same daily cron that handles
    parole reminders."""
    if not req.thread_id or not req.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="thread_id and message are required",
        )
    queued_id = writeback.enqueue_message(
        thread_id=req.thread_id,
        body=req.message.strip(),
        partner_name=partner.name,
    )
    return WritebackResponse(
        queued_id=queued_id,
        thread_id=req.thread_id,
        partner=partner.name,
        note=(
            "Message queued. Delivery requires the forward phone map "
            "to be wired on the operator side; until then the message "
            "sits in relay_messages.pending."
        ),
    )
