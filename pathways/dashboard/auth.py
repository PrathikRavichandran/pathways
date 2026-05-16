"""Dashboard authentication and per-partner scoping.

Partners are configured via the PATHWAYS_DASHBOARD_TOKENS_JSON env
var, which carries a JSON map::

    {
      "<bearer-token>": {
        "name": "Houston Reentry Coalition",
        "workforce_regions": ["Gulf Coast"],
        "counties": ["Harris", "Fort Bend"],
        "regions": ["Greater Houston"]
      },
      "<another-token>": {
        "name": "TX Statewide Admin",
        "superuser": true
      }
    }

Bearer tokens are presented in the `Authorization: Bearer <token>`
header. Comparison is constant-time (hmac.compare_digest) so timing
attacks can't enumerate valid tokens.

A `superuser: true` partner sees all data unscoped. Otherwise the
partner sees only events whose workforce_region, county, or region
matches one of their declared filters.

If PATHWAYS_DASHBOARD_TOKENS_JSON is unset OR empty:
    Demo mode. Any non-empty bearer is accepted, scope is unrestricted,
    and the partner name shown is "Demo Partner". This is intentional:
    the dashboard URL is private-by-default (token-gated) and demo
    mode is what makes a recruiter click-through useful.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request, status


@dataclass
class Partner:
    name: str
    scope: Optional[dict]  # None = superuser / demo / unrestricted

    @property
    def is_superuser(self) -> bool:
        return self.scope is None


def _load_tokens() -> dict[str, dict]:
    raw = os.environ.get("PATHWAYS_DASHBOARD_TOKENS_JSON") or ""
    raw = raw.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in data.items()}


def _parse_partner(spec: dict) -> Partner:
    name = str(spec.get("name") or "Partner")
    if spec.get("superuser"):
        return Partner(name=name, scope=None)
    scope: dict = {}
    for key in ("workforce_regions", "counties", "regions"):
        val = spec.get(key)
        if isinstance(val, list) and val:
            scope[key] = [str(x) for x in val]
    return Partner(name=name, scope=(scope or None))


COOKIE_NAME = "pathways_dashboard_token"


def _extract_token(request: Request) -> Optional[str]:
    """Pull the bearer token from either the Authorization header or
    the dashboard login cookie. Header wins if both are present."""
    header = request.headers.get("authorization") or ""
    prefix = "bearer "
    if header.lower().startswith(prefix):
        token = header[len(prefix):].strip()
        if token:
            return token
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie.strip() or None
    return None


def authenticate(request: Request) -> Partner:
    """Validate the bearer token from either the Authorization header
    or the dashboard login cookie. Returns the matching Partner.
    Raises 401 on miss; never logs the token value."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token (use /dashboard/login or set Authorization header)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tokens = _load_tokens()

    # Demo mode: any non-empty bearer works.
    if not tokens:
        return Partner(name="Demo Partner", scope=None)

    for candidate_token, spec in tokens.items():
        if hmac.compare_digest(token, candidate_token):
            return _parse_partner(spec)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
