"""Phase 6 tests: monthly trend report Markdown + NGO write-back queue.

Covers:
    - render_markdown_report shape (headings, sections, no PII)
    - /dashboard/api/report.md auth + Markdown content type + body
    - write-back queue: enqueue, pending, mark sent/failed (memory store)
    - drain_pending sends, skips no-phone, marks failed
    - /dashboard/api/writeback auth + queue write + response shape
    - /admin/run-parole-reminders now also drains the writeback queue
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for k in [
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
        "PATHWAYS_DASHBOARD_BACKEND",
        "PATHWAYS_WRITEBACK_BACKEND",
        "DATABASE_URL",
    ]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "p6-test-salt")

    from pathways.dashboard import analytics, writeback
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod
    analytics.reset_store()
    writeback.reset_store()
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    yield
    analytics.reset_store()
    writeback.reset_store()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    return TestClient(api)


# ---------------------------------------------------------------------------
# Markdown report rendering
# ---------------------------------------------------------------------------


def _seed_events():
    from pathways.dashboard.analytics import TurnEvent, record_turn
    record_turn(TurnEvent(
        thread_id="t-a", channel="sms", language="en",
        needs=["housing"], workforce_region="Gulf Coast",
        retrieval_confidence=0.81,
    ))
    record_turn(TurnEvent(
        thread_id="t-b", channel="web", language="es",
        needs=["benefits"], workforce_region="Gulf Coast",
        retrieval_confidence=0.55,
    ))
    record_turn(TurnEvent(
        thread_id="t-c", channel="sms", language="en",
        needs=["employment"], workforce_region="Gulf Coast",
        escalated=True, escalation_reason="audit_hard_block:test",
    ))


def test_render_markdown_report_has_required_sections():
    from pathways.dashboard.analytics import render_markdown_report
    _seed_events()
    md = render_markdown_report(
        partner_name="Houston Coalition",
        scope={"workforce_regions": ["Gulf Coast"]},
        days=30,
    )
    assert "# Pathways activity report" in md
    assert "**Partner:** Houston Coalition" in md
    assert "## Activity at a glance" in md
    assert "## Needs by region" in md
    assert "## Retrieval confidence distribution" in md
    assert "## Escalation reasons" in md  # escalations seeded
    # PII never makes it in. We check for actual phone-number-shaped
    # patterns rather than the word "phone" (which the footer mentions
    # in its anonymization disclaimer).
    import re
    assert re.search(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", md) is None
    assert re.search(r"\+1\d{10}", md) is None


def test_render_markdown_report_handles_empty_window():
    from pathways.dashboard.analytics import render_markdown_report
    md = render_markdown_report(
        partner_name="Partner",
        scope=None,
        days=1,
    )
    assert "No conversations" in md or "0" in md


# ---------------------------------------------------------------------------
# /dashboard/api/report.md endpoint
# ---------------------------------------------------------------------------


def test_report_endpoint_requires_auth(client):
    r = client.get("/dashboard/api/report.md")
    assert r.status_code == 401


def test_report_endpoint_returns_markdown(client):
    _seed_events()
    r = client.get(
        "/dashboard/api/report.md?days=30",
        headers={"authorization": "Bearer demo-token"},
    )
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    body = r.text
    assert body.startswith("# Pathways activity report")
    assert "**Partner:** Demo Partner" in body


# ---------------------------------------------------------------------------
# Write-back queue store
# ---------------------------------------------------------------------------


def test_writeback_enqueue_and_pending():
    from pathways.dashboard import writeback as wb
    wb.reset_store()
    mid = wb.enqueue_message(
        thread_id="hash-x", body="Hi from Houston Coalition",
        partner_name="Houston Coalition",
    )
    assert mid > 0
    pending = wb.get_store().pending()
    assert len(pending) == 1
    assert pending[0].thread_id == "hash-x"
    assert pending[0].partner_name == "Houston Coalition"
    assert pending[0].sent_at is None


def test_drain_pending_sends_and_marks():
    from pathways.dashboard.writeback import (
        drain_pending, enqueue_message, get_store,
    )
    enqueue_message("hash-x", "body 1", "P")
    enqueue_message("hash-y", "body 2", "P")

    sent: list = []

    def fake_send(to, body):
        sent.append((to, body))
        return True

    summary = drain_pending(
        send_fn=fake_send,
        phone_for_thread=lambda t: f"+1713555000{t[-1]}",
    )
    assert summary["pending_before"] == 2
    assert summary["sent"] == 2
    assert summary["skipped_no_phone"] == 0
    pending_after = get_store().pending()
    assert pending_after == []


def test_drain_pending_skips_no_phone():
    from pathways.dashboard.writeback import drain_pending, enqueue_message
    enqueue_message("hash-x", "body 1", "P")
    summary = drain_pending(
        send_fn=lambda t, b: True,
        phone_for_thread=lambda t: None,
    )
    assert summary["pending_before"] == 1
    assert summary["sent"] == 0
    assert summary["skipped_no_phone"] == 1


def test_drain_pending_marks_failures():
    from pathways.dashboard.writeback import (
        drain_pending, enqueue_message, get_store,
    )
    enqueue_message("hash-x", "body 1", "P")
    drain_pending(
        send_fn=lambda t, b: (_ for _ in ()).throw(RuntimeError("boom")),
        phone_for_thread=lambda t: "+17135550001",
    )
    rows = get_store().all()
    assert len(rows) == 1
    assert rows[0].failed_at is not None
    assert "boom" in (rows[0].failure_reason or "")


# ---------------------------------------------------------------------------
# /dashboard/api/writeback endpoint
# ---------------------------------------------------------------------------


def test_writeback_endpoint_requires_auth(client):
    r = client.post(
        "/dashboard/api/writeback",
        json={"thread_id": "abc", "message": "hi"},
    )
    assert r.status_code == 401


def test_writeback_endpoint_queues_message(client):
    from pathways.dashboard import writeback as wb
    wb.reset_store()
    r = client.post(
        "/dashboard/api/writeback",
        json={"thread_id": "hash-abc", "message": "Please check in with us"},
        headers={"authorization": "Bearer demo-token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["thread_id"] == "hash-abc"
    assert body["partner"] == "Demo Partner"
    assert "queued_id" in body
    assert body["queued_id"] > 0
    # The row is in the store
    pending = wb.get_store().pending()
    assert len(pending) == 1
    assert pending[0].body == "Please check in with us"


def test_writeback_rejects_empty_body(client):
    r = client.post(
        "/dashboard/api/writeback",
        json={"thread_id": "abc", "message": "   "},
        headers={"authorization": "Bearer demo-token"},
    )
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Admin endpoint now drains both queues
# ---------------------------------------------------------------------------


def test_admin_endpoint_runs_parole_and_writeback(client, monkeypatch):
    from pathways.dashboard import writeback as wb
    monkeypatch.setenv("PATHWAYS_ADMIN_TOKEN", "cron-token")
    wb.enqueue_message("hash-x", "test", "P")

    r = client.post(
        "/admin/run-parole-reminders",
        headers={"authorization": "Bearer cron-token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "parole_reminders" in body
    assert "writeback" in body
    # writeback was non-empty before; phone map returns None so skipped
    assert body["writeback"]["pending_before"] >= 1
