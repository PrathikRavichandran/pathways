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

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from pathways.dashboard import analytics
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
