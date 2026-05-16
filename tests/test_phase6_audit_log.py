"""Phase 6 wire: operator-side audit log.

Covers:
    - AuditEvent build from a LangGraph final state (captures full
      user message + reply + retrievals + matched resources + verdict)
    - Memory store round-trip + query filters (thread_id, since, limit)
    - Postgres backend's Fernet path: encrypt/decrypt round-trip
    - Falls back to memory when key missing
    - Hooks fire on /web/turn and /sms (writes one row per turn)
    - GET /admin/audit-log requires bearer; returns rows; respects filters
    - POST /admin/purge-audit-log purges older-than rows
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for k in [
        "PATHWAYS_AUDIT_BACKEND",
        "PATHWAYS_AUDIT_ENCRYPTION_KEY",
        "DATABASE_URL",
        "PATHWAYS_DASHBOARD_TOKENS_JSON",
    ]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "audit-test-salt")
    monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")

    from pathways.audit import reset_store as reset_audit
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod
    from pathways.dashboard import analytics
    from pathways.dashboard import writeback as wb

    reset_audit()
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    analytics.reset_store()
    wb.reset_store()
    from pathways.sessions import idempotency, phone_map
    idempotency._seen_sids.clear()
    phone_map.reset_store()
    yield
    reset_audit()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    return TestClient(api)


# ---------------------------------------------------------------------------
# event_from_state captures full content (the whole point)
# ---------------------------------------------------------------------------


def test_event_from_state_captures_full_user_message_and_reply():
    from pathways.audit.service import event_from_state
    from pathways.state import IntakeProfile, PathwaysState, TopNeed

    state = PathwaysState(
        session_id="t-1",
        user_message="I need housing tonight, ZIP 77002",
        intake=IntakeProfile(
            name="Marcus",
            top_need=TopNeed.HOUSING,
            zipcode="77002",
            language="en",
        ),
    )
    event = event_from_state(
        final_state=state,
        thread_id="t-1",
        channel="sms",
        user_message="I need housing tonight, ZIP 77002",
        reply="Here are nearby Houston shelters: ...",
        crisis_fired=False,
    )
    # Distinct from the dashboard analytics event: this DOES carry text
    assert event.user_message == "I need housing tonight, ZIP 77002"
    assert event.reply == "Here are nearby Houston shelters: ..."
    assert event.needs == ["housing"]
    assert event.zipcode == "77002"


def test_event_from_state_captures_retrievals_and_audit():
    from pathways.audit.service import event_from_state
    from pathways.state import (
        AuditResult, AuditVerdict, IntakeProfile, PathwaysState,
        Retrieval, TopNeed,
    )

    retrieval = Retrieval(
        source="pathways-corpus",
        query="public housing eligibility",
        confidence=0.81,
        results=[{"id": "hud-pih-2015-19", "citation": "HUD PIH-2015-19"}],
    )
    audit = AuditResult(verdict=AuditVerdict.PASS, issues=[])
    state = PathwaysState(
        session_id="t-2",
        user_message="section 8 question",
        intake=IntakeProfile(top_need=TopNeed.HOUSING),
        retrievals=[retrieval],
        audit=audit,
    )
    event = event_from_state(
        final_state=state, thread_id="t-2", channel="web",
        user_message="section 8 question", reply="cited reply",
        crisis_fired=False,
    )
    assert len(event.retrievals) == 1
    assert event.retrievals[0]["query"] == "public housing eligibility"
    assert event.retrievals[0]["confidence"] == 0.81
    assert event.audit_verdict == "pass"


# ---------------------------------------------------------------------------
# Memory store round-trip + filters
# ---------------------------------------------------------------------------


def test_memory_store_append_and_query():
    from pathways.audit import get_store, record_turn
    from pathways.audit.store import AuditEvent

    record_turn(AuditEvent(thread_id="A", user_message="hi", reply="hello"))
    record_turn(AuditEvent(thread_id="B", user_message="hola", reply="hola back"))
    rows = get_store().query(limit=10)
    assert len(rows) == 2


def test_memory_store_filter_by_thread_id():
    from pathways.audit import get_store, record_turn
    from pathways.audit.store import AuditEvent

    record_turn(AuditEvent(thread_id="X", user_message="msg1"))
    record_turn(AuditEvent(thread_id="Y", user_message="msg2"))
    record_turn(AuditEvent(thread_id="X", user_message="msg3"))
    rows = get_store().query(thread_id="X", limit=10)
    assert len(rows) == 2
    assert all(r.thread_id == "X" for r in rows)


def test_memory_store_filter_by_since_and_limit():
    from pathways.audit import get_store, record_turn
    from pathways.audit.store import AuditEvent

    old_ts = datetime.now(timezone.utc) - timedelta(days=10)
    record_turn(AuditEvent(thread_id="X", user_message="old", ts=old_ts))
    record_turn(AuditEvent(thread_id="X", user_message="new"))
    record_turn(AuditEvent(thread_id="X", user_message="newer"))

    since = datetime.now(timezone.utc) - timedelta(days=1)
    rows = get_store().query(since=since, limit=10)
    assert len(rows) == 2  # excludes 'old'

    rows = get_store().query(limit=1)
    assert len(rows) == 1


def test_memory_store_purge_older_than():
    from pathways.audit import get_store, record_turn
    from pathways.audit.store import AuditEvent

    old_ts = datetime.now(timezone.utc) - timedelta(days=200)
    record_turn(AuditEvent(thread_id="X", ts=old_ts))
    record_turn(AuditEvent(thread_id="Y"))

    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    removed = get_store().purge_older_than(cutoff)
    assert removed == 1
    assert len(get_store().query(limit=10)) == 1


# ---------------------------------------------------------------------------
# Postgres backend Fernet round-trip (no DB; we test the encrypt/decrypt branch)
# ---------------------------------------------------------------------------


def test_postgres_backend_fernet_round_trip():
    """Confirm the encryption/decryption path is symmetric without
    needing a live DB. Instantiate the class, call .encrypt + .decrypt
    on its internal Fernet."""
    import json

    from cryptography.fernet import Fernet
    from pathways.audit.store import AuditEvent, _PostgresStore

    key = Fernet.generate_key()
    store = _PostgresStore(key)
    event = AuditEvent(
        thread_id="hash-x", user_message="contains SSN 123-45-6789",
        reply="here is help", needs=["housing"],
    )
    payload = json.dumps(event.to_payload_dict(), default=str).encode("utf-8")
    token = store._fernet.encrypt(payload)
    decrypted = store._fernet.decrypt(token).decode("utf-8")
    data = json.loads(decrypted)
    assert data["user_message"] == "contains SSN 123-45-6789"


def test_postgres_backend_falls_back_to_memory_without_key(monkeypatch):
    """Postgres requested + DATABASE_URL set + key missing = memory."""
    monkeypatch.setenv("PATHWAYS_AUDIT_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgres://fake")
    monkeypatch.delenv("PATHWAYS_AUDIT_ENCRYPTION_KEY", raising=False)
    from pathways.audit import reset_store
    from pathways.audit.store import _MemoryStore, get_store
    reset_store()
    assert isinstance(get_store(), _MemoryStore)


# ---------------------------------------------------------------------------
# End-to-end: /web/turn writes one audit row per turn
# ---------------------------------------------------------------------------


def test_web_turn_writes_audit_row(client):
    from pathways.audit import get_store

    s = client.post("/web/session", json={}).json()
    r = client.post(
        "/web/turn", json={"session_id": s["session_id"], "message": "I need housing"},
    )
    assert r.status_code == 200

    rows = get_store().query(limit=5)
    assert len(rows) == 1
    assert rows[0].user_message == "I need housing"
    assert rows[0].channel == "web"


def test_sms_writes_audit_row(client):
    from pathways.audit import get_store

    r = client.post(
        "/sms",
        data={"Body": "section 8 question", "From": "+17135550700",
              "MessageSid": "SMaudit1"},
    )
    assert r.status_code == 200
    rows = get_store().query(limit=5)
    assert len(rows) == 1
    assert rows[0].channel == "sms"
    assert rows[0].user_message == "section 8 question"


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


def test_admin_audit_log_requires_token(client):
    r = client.get("/admin/audit-log")
    assert r.status_code == 401


def test_admin_audit_log_returns_rows(client, monkeypatch):
    monkeypatch.setenv("PATHWAYS_ADMIN_TOKEN", "admin-secret")
    from pathways.audit import record_turn
    from pathways.audit.store import AuditEvent
    record_turn(AuditEvent(thread_id="hash-x", user_message="m1", reply="r1"))
    record_turn(AuditEvent(thread_id="hash-y", user_message="m2", reply="r2"))

    r = client.get(
        "/admin/audit-log?days=30&limit=10",
        headers={"authorization": "Bearer admin-secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    # Full content present (this is the operator-side property)
    msgs = [row["user_message"] for row in body["rows"]]
    assert "m1" in msgs and "m2" in msgs


def test_admin_audit_log_filters_by_thread_id(client, monkeypatch):
    monkeypatch.setenv("PATHWAYS_ADMIN_TOKEN", "admin-secret")
    from pathways.audit import record_turn
    from pathways.audit.store import AuditEvent
    record_turn(AuditEvent(thread_id="hash-x", user_message="m1"))
    record_turn(AuditEvent(thread_id="hash-y", user_message="m2"))

    r = client.get(
        "/admin/audit-log?thread_id=hash-x",
        headers={"authorization": "Bearer admin-secret"},
    )
    body = r.json()
    assert body["count"] == 1
    assert body["rows"][0]["user_message"] == "m1"


def test_admin_purge_audit_log(client, monkeypatch):
    monkeypatch.setenv("PATHWAYS_ADMIN_TOKEN", "admin-secret")
    from pathways.audit import record_turn
    from pathways.audit.store import AuditEvent
    old_ts = datetime.now(timezone.utc) - timedelta(days=300)
    record_turn(AuditEvent(thread_id="hash-x", user_message="old", ts=old_ts))
    record_turn(AuditEvent(thread_id="hash-y", user_message="new"))

    r = client.post(
        "/admin/purge-audit-log?older_than_days=180",
        headers={"authorization": "Bearer admin-secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] == 1
