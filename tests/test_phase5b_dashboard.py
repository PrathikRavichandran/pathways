"""Phase 5b tests: caseworker dashboard.

Covers:
    - PII scrubbing at the write layer (event_from_state never carries
      raw user text, name, phone, etc; only metrics)
    - Per-partner bearer token auth (missing/invalid/valid; constant-time)
    - Region scoping: a partner sees only their declared regions/counties
    - Aggregate queries (summary, needs_by_region, confidence histogram,
      escalation_reasons, recent_conversations) return expected shape
    - Demo mode (no PATHWAYS_DASHBOARD_TOKENS_JSON) accepts any token
    - End-to-end: the API path writes an event after each turn and the
      dashboard surfaces it
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Reset analytics store + env between tests."""
    for k in [
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
        "PATHWAYS_DASHBOARD_BACKEND",
        "DATABASE_URL",  # keep dashboard on memory backend
    ]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "dashboard-test-salt")
    monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")

    # Reset the cached analytics store + the cached graph/checkpointer
    from pathways.dashboard import analytics
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod
    analytics.reset_store()
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    from pathways.sessions import idempotency
    idempotency._seen_sids.clear()
    yield
    analytics.reset_store()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    return TestClient(api)


# ---------------------------------------------------------------------------
# PII scrubbing at the write layer
# ---------------------------------------------------------------------------


def test_event_from_state_never_carries_raw_message_text():
    """The whole PII argument relies on event_from_state stripping the
    user message body and the reply body to length-only ints."""
    from pathways.dashboard.analytics import event_from_state
    from pathways.state import IntakeProfile, PathwaysState, TopNeed

    state = PathwaysState(
        session_id="t1",
        user_message="I am Marcus, 32, SSN 123-45-6789, please help",
        intake=IntakeProfile(
            name="Marcus", top_need=TopNeed.HOUSING, zipcode="77002",
        ),
    )
    event = event_from_state(
        final_state=state, thread_id="t1", channel="sms",
        user_message="I am Marcus, 32, SSN 123-45-6789, please help",
        reply="Here are some shelters in Houston",
        crisis_fired=False,
    )
    # PII fields must NEVER appear in the event
    assert "Marcus" not in str(event.__dict__)
    assert "123-45-6789" not in str(event.__dict__)
    assert "shelters" not in str(event.__dict__)
    # Length metrics are kept
    assert event.user_message_length == len(
        "I am Marcus, 32, SSN 123-45-6789, please help"
    )
    assert event.reply_length == len("Here are some shelters in Houston")
    # Needs are kept (not PII)
    assert "housing" in event.needs


def test_event_from_state_handles_missing_intake_gracefully():
    """When the graph short-circuits to escalate before intake runs,
    event_from_state should not crash."""
    from pathways.dashboard.analytics import event_from_state

    final = {"escalation_reason": "crisis_hook:suicide"}
    event = event_from_state(
        final_state=final, thread_id="hash-x", channel="web",
        user_message="...", reply="...", crisis_fired=True,
    )
    assert event.escalated is True
    assert event.crisis_fired is True
    assert event.escalation_reason == "crisis_hook:suicide"
    assert event.needs == []


# ---------------------------------------------------------------------------
# Auth: missing / invalid / valid / demo-mode
# ---------------------------------------------------------------------------


def test_dashboard_missing_token_returns_401(client):
    r = client.get("/dashboard/api/summary")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_dashboard_empty_bearer_returns_401(client):
    r = client.get("/dashboard/api/summary", headers={"authorization": "Bearer "})
    assert r.status_code == 401


def test_dashboard_invalid_token_returns_401_when_tokens_configured(
    client, monkeypatch,
):
    monkeypatch.setenv(
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
        json.dumps({"valid-token": {"name": "Partner A", "superuser": True}}),
    )
    r = client.get(
        "/dashboard/api/summary",
        headers={"authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401


def test_dashboard_valid_token_returns_200(client, monkeypatch):
    monkeypatch.setenv(
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
        json.dumps({"valid-token": {"name": "Partner A", "superuser": True}}),
    )
    r = client.get(
        "/dashboard/api/summary",
        headers={"authorization": "Bearer valid-token"},
    )
    assert r.status_code == 200
    assert r.json()["partner"] == "Partner A"


def test_dashboard_demo_mode_accepts_any_bearer(client):
    """When PATHWAYS_DASHBOARD_TOKENS_JSON is unset, any bearer works.
    The dashboard URL is private-by-default (token-gated), and demo mode
    is what makes a recruiter click-through useful without spinning up
    a real partner config."""
    r = client.get(
        "/dashboard/api/summary",
        headers={"authorization": "Bearer anything-goes"},
    )
    assert r.status_code == 200
    assert r.json()["partner"] == "Demo Partner"


def test_dashboard_health_does_not_require_auth(client):
    r = client.get("/dashboard/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Region scoping
# ---------------------------------------------------------------------------


def _seed_events():
    from pathways.dashboard.analytics import TurnEvent, record_turn, reset_store
    reset_store()

    record_turn(TurnEvent(
        thread_id="t-houston-1", channel="sms", language="en",
        needs=["housing"], workforce_region="Gulf Coast", county="Harris",
        region="Greater Houston",
    ))
    record_turn(TurnEvent(
        thread_id="t-dallas-1", channel="sms", language="en",
        needs=["employment"], workforce_region="North Central",
        county="Dallas", region="DFW",
    ))
    record_turn(TurnEvent(
        thread_id="t-el-paso-1", channel="web", language="es",
        needs=["benefits"], workforce_region="Upper Rio",
        county="El Paso", region="El Paso",
    ))


def test_scoping_houston_partner_sees_only_houston(monkeypatch):
    monkeypatch.setenv(
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
        json.dumps({
            "tok": {
                "name": "Houston Coalition",
                "workforce_regions": ["Gulf Coast"],
            }
        }),
    )
    _seed_events()
    from fastapi.testclient import TestClient
    from pathways.api.main import api

    client = TestClient(api)
    r = client.get(
        "/dashboard/api/needs?days=90",
        headers={"authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    regions = {row["region"] for row in rows}
    assert "Gulf Coast" in regions
    assert "North Central" not in regions
    assert "Upper Rio" not in regions


def test_superuser_sees_all(monkeypatch):
    monkeypatch.setenv(
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
        json.dumps({"tok": {"name": "TX Admin", "superuser": True}}),
    )
    _seed_events()
    from fastapi.testclient import TestClient
    from pathways.api.main import api

    client = TestClient(api)
    r = client.get(
        "/dashboard/api/needs?days=90",
        headers={"authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    regions = {row["region"] for row in r.json()["rows"]}
    assert {"Gulf Coast", "North Central", "Upper Rio"}.issubset(regions)


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def test_summary_counts_distinct_threads_and_turns():
    from pathways.dashboard.analytics import (
        TurnEvent, record_turn, reset_store, summary,
    )
    reset_store()
    # Two turns on one thread + one turn on another
    record_turn(TurnEvent(thread_id="A", needs=["housing"], retrieval_confidence=0.8))
    record_turn(TurnEvent(thread_id="A", needs=["benefits"], retrieval_confidence=0.6))
    record_turn(TurnEvent(thread_id="B", needs=["employment"], escalated=True))

    s = summary(days=30)
    assert s["total_turns"] == 3
    assert s["distinct_threads"] == 2
    assert s["escalated"] == 1
    assert s["avg_retrieval_confidence"] == pytest.approx(0.7, abs=0.01)


def test_confidence_distribution_has_expected_bins():
    from pathways.dashboard.analytics import (
        TurnEvent, confidence_distribution, record_turn, reset_store,
    )
    reset_store()
    for c in [0.1, 0.15, 0.5, 0.55, 0.65, 0.75, 0.9, 0.95]:
        record_turn(TurnEvent(thread_id="x", retrieval_confidence=c))

    bins = confidence_distribution(days=30, bins=5)
    assert len(bins) == 5
    # Bins cover [0, 1) so total counted = 8
    assert sum(b["count"] for b in bins) == 8


def test_escalation_reasons_aggregates_correctly():
    from pathways.dashboard.analytics import (
        TurnEvent, escalation_reasons, record_turn, reset_store,
    )
    reset_store()
    for reason in ["crisis_hook:suicide", "crisis_hook:suicide", "audit_hard_block:[...]"]:
        record_turn(TurnEvent(
            thread_id="x", escalated=True, escalation_reason=reason,
        ))
    rows = escalation_reasons(days=30)
    by_reason = {r["reason"]: r["count"] for r in rows}
    assert by_reason["crisis_hook:suicide"] == 2
    assert by_reason["audit_hard_block:[...]"] == 1


def test_recent_conversations_returns_anonymized_rows():
    from pathways.dashboard.analytics import (
        TurnEvent, recent_conversations, record_turn, reset_store,
    )
    reset_store()
    record_turn(TurnEvent(
        thread_id="very-long-salted-hash-of-phone-1234567890abcdef",
        channel="sms", language="en", needs=["housing"],
        workforce_region="Gulf Coast",
    ))
    rows = recent_conversations(days=30, limit=5)
    assert len(rows) == 1
    row = rows[0]
    # display id is truncated, never full
    assert len(row["thread_id_display"]) <= 12
    # No raw phone, no name field
    assert "phone" not in row
    assert "name" not in row
    # Region, needs, channel ARE present (not PII)
    assert row["region"] == "Gulf Coast"


def test_time_window_filter_excludes_old_events():
    from pathways.dashboard.analytics import (
        TurnEvent, record_turn, reset_store, summary,
    )
    reset_store()
    old = datetime.now(timezone.utc) - timedelta(days=60)
    record_turn(TurnEvent(thread_id="old", created_at=old))
    record_turn(TurnEvent(thread_id="new"))
    s = summary(days=7)
    assert s["total_turns"] == 1  # only the new one counts


# ---------------------------------------------------------------------------
# End-to-end: API path writes events, dashboard reads them
# ---------------------------------------------------------------------------


def test_web_turn_writes_event_to_dashboard(client):
    """One /web/turn call should produce one event readable via /dashboard."""
    from pathways.dashboard import analytics

    analytics.reset_store()

    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]
    r = client.post(
        "/web/turn", json={"session_id": sid, "message": "hello there"},
    )
    assert r.status_code == 200

    events = analytics.get_store().all()
    assert len(events) == 1
    e = events[0]
    assert e.thread_id == s["thread_id"]
    assert e.channel == "web"
    # The raw message text is never stored
    assert e.user_message_length == len("hello there")


def test_dashboard_recent_lists_a_web_turn_event(client):
    s = client.post("/web/session", json={}).json()
    client.post(
        "/web/turn", json={"session_id": s["session_id"], "message": "I need housing"},
    )

    r = client.get(
        "/dashboard/api/recent?days=1",
        headers={"authorization": "Bearer demo-token"},
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) >= 1
    # No PII leaked into the response
    body = r.text.lower()
    assert "i need housing" not in body  # raw user text never appears


def test_dashboard_landing_page_renders_html(client):
    r = client.get(
        "/dashboard/",
        headers={"authorization": "Bearer demo-token"},
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "Caseworker dashboard" in body
    assert "Pathways" in body


# ---------------------------------------------------------------------------
# Browser-friendly login (cookie auth)
# ---------------------------------------------------------------------------


def test_login_form_renders(client):
    r = client.get("/dashboard/login")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Bearer token" in r.text


def test_login_post_with_demo_mode_token_sets_cookie_and_redirects(client):
    r = client.post(
        "/dashboard/login",
        data={"token": "anything-works-in-demo-mode"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard/"
    # Cookie set
    set_cookie = r.headers.get("set-cookie", "")
    assert "pathways_dashboard_token=" in set_cookie
    assert "Path=/dashboard" in set_cookie or "path=/dashboard" in set_cookie.lower()


def test_login_post_rejects_empty_token(client):
    r = client.post(
        "/dashboard/login",
        data={"token": "   "},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "empty" in r.text.lower()


def test_login_post_rejects_wrong_token_when_tokens_configured(client, monkeypatch):
    import json
    monkeypatch.setenv(
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
        json.dumps({"correct-token": {"name": "Houston", "superuser": True}}),
    )
    r = client.post(
        "/dashboard/login",
        data={"token": "wrong-token"},
        follow_redirects=False,
    )
    assert r.status_code == 401
    assert "didn" in r.text.lower() or "match" in r.text.lower()


def test_cookie_authenticates_subsequent_requests(client):
    """After login, the cookie alone should authenticate /dashboard/."""
    login = client.post(
        "/dashboard/login",
        data={"token": "demo-cookie-test"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    # The TestClient keeps the cookie. Visit landing without Authorization header.
    r = client.get("/dashboard/")
    assert r.status_code == 200
    assert "Caseworker dashboard" in r.text


def test_unauthenticated_landing_redirects_to_login_not_401(client):
    """Browser visitors get sent to the login form rather than a 401."""
    fresh = client.__class__(client.app)  # cookie-free client
    r = fresh.get("/dashboard/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard/login"


def test_logout_clears_cookie_and_redirects(client):
    # First, sign in.
    client.post(
        "/dashboard/login",
        data={"token": "demo-logout-test"},
        follow_redirects=False,
    )
    # Then sign out.
    r = client.post("/dashboard/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard/login"
    # Cookie cleared (empty value + Max-Age=0)
    set_cookie = r.headers.get("set-cookie", "")
    assert "pathways_dashboard_token=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


def test_api_endpoints_still_accept_header_auth_only(client):
    """JSON API endpoints don't need the cookie path; header bearer
    still works for programmatic clients (curl, partner backends)."""
    r = client.get(
        "/dashboard/api/summary",
        headers={"authorization": "Bearer demo-api-token"},
    )
    assert r.status_code == 200
