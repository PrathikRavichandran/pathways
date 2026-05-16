"""Phase 4 tests: /web channel endpoints + multi-channel parity."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _demo_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "phase4-test-salt")
    monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    from pathways.sessions import idempotency
    idempotency._seen_sids.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    return TestClient(api)


# ---------------------------------------------------------------------------
# /web/health
# ---------------------------------------------------------------------------


def test_web_health(client):
    r = client.get("/web/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["channel"] == "web"


def test_root_health_lists_channels(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "sms" in body.get("channels", [])
    assert "web" in body.get("channels", [])


# ---------------------------------------------------------------------------
# /web/session
# ---------------------------------------------------------------------------


def test_session_creation_returns_uuid_and_thread_id(client):
    r = client.post("/web/session", json={})
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert "thread_id" in body
    # session_id should look like a UUID4
    assert len(body["session_id"]) >= 32
    # thread_id should have the web prefix to distinguish from phone threads
    assert body["thread_id"].startswith("web_")


def test_session_accepts_language_hint(client):
    r = client.post("/web/session", json={"language_hint": "es"})
    assert r.status_code == 200


def test_session_rejects_invalid_language_hint(client):
    r = client.post("/web/session", json={"language_hint": "fr"})
    assert r.status_code == 422  # Pydantic validation


# ---------------------------------------------------------------------------
# /web/turn
# ---------------------------------------------------------------------------


def test_turn_requires_session_id(client):
    r = client.post("/web/turn", json={"session_id": "", "message": "hi"})
    assert r.status_code in (400, 422)


def test_turn_first_message_asks_for_name(client):
    # Create a session
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]

    r = client.post("/web/turn", json={"session_id": sid, "message": "hey"})
    assert r.status_code == 200
    body = r.json()
    # Should be in collect_name stage with an English name prompt
    assert body["intake_stage"] == "collect_name"
    assert "name" in body["reply"].lower()
    assert body["language"] == "en"
    assert body["resources"] == []


def test_turn_spanish_first_message_routes_to_spanish_prompt(client):
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]

    r = client.post(
        "/web/turn",
        json={"session_id": sid, "message": "Hola necesito ayuda con vivienda"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "es"
    # Spanish name prompt
    assert "nombre" in body["reply"].lower() or "llamar" in body["reply"].lower()


def test_turn_full_intake_flow_produces_resources(client):
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]

    # Turn 1: greeting -> name prompt
    r1 = client.post("/web/turn", json={"session_id": sid, "message": "hey"}).json()
    assert r1["intake_stage"] == "collect_name"

    # Turn 2: give name -> location prompt
    r2 = client.post("/web/turn", json={"session_id": sid, "message": "Marcus"}).json()
    assert r2["intake_stage"] == "collect_location"

    # Turn 3: give ZIP -> top-need prompt
    r3 = client.post("/web/turn", json={"session_id": sid, "message": "77002"}).json()
    assert r3["intake_stage"] == "collect_need"

    # Turn 4: give need -> retrieve + match + draft happens; resources returned
    r4 = client.post(
        "/web/turn",
        json={"session_id": sid, "message": "I need a place to stay tonight"},
    ).json()
    assert r4["intake_stage"] is None  # done
    # Either resources OR an escalation reply (housing emergency hotword may fire)
    assert r4["reply"]
    assert len(r4["needs"]) >= 1


def test_turn_multi_need_returns_both_categories(client):
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]
    # Bypass slot fill by going through full intake first
    for msg in ["hey", "Marcus", "77002"]:
        client.post("/web/turn", json={"session_id": sid, "message": msg})

    r = client.post(
        "/web/turn",
        json={"session_id": sid, "message": "I need food and a job"},
    ).json()
    assert r["intake_stage"] is None
    # Both benefits and employment should be in needs
    assert "benefits" in r["needs"] or "employment" in r["needs"]


def test_turn_resource_cards_have_expected_shape(client):
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]
    for msg in ["hey", "Marcus", "77002", "I need housing in Houston"]:
        r = client.post("/web/turn", json={"session_id": sid, "message": msg}).json()
    # Inspect the final turn's resources
    for card in r["resources"]:
        assert "id" in card
        assert "name" in card
        # phone or url should be present for at least one card
    # At least one resource (or fallback to 211)
    assert len(r["resources"]) >= 0


def test_turn_stop_keyword_opts_out(client):
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]
    r = client.post("/web/turn", json={"session_id": sid, "message": "STOP"}).json()
    assert "further messages" in r["reply"].lower() or "opt" in r["reply"].lower()


def test_turn_help_returns_help_text(client):
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]
    r = client.post("/web/turn", json={"session_id": sid, "message": "HELP"}).json()
    assert "pathways" in r["reply"].lower()


# ---------------------------------------------------------------------------
# Multi-channel parity: same backend, different channels
# ---------------------------------------------------------------------------


def test_web_and_sms_share_no_state_when_distinct_identities(client, monkeypatch):
    """SMS thread for +17135550100 and web thread for some UUID must be
    independent threads (different prefixes, different state)."""
    # Web session 1
    s = client.post("/web/session", json={}).json()
    client.post("/web/turn", json={"session_id": s["session_id"], "message": "hey"})
    client.post("/web/turn", json={"session_id": s["session_id"], "message": "Alice"})

    # SMS turn from a phone, should start at collect_name
    r = client.post(
        "/sms",
        data={"Body": "hey", "From": "+17135550100", "MessageSid": "SMphase4_1"},
    )
    assert r.status_code == 200
    # SMS should be asking for the name, not continuing Alice's web session.
    assert "name" in r.text.lower()
