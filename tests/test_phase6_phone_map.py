"""Phase 6 wire: forward thread_id -> phone resolver.

Covers:
    - Memory backend: set, get, clear, no-key-no-error
    - Fallback when PATHWAYS_PHONE_ENCRYPTION_KEY is unset (memory backend)
    - Encryption + decryption round-trip with a real Fernet key (no DB;
      we instantiate the Postgres backend class but only exercise its
      Fernet path via the encrypt/decrypt methods)
    - SMS handler writes the mapping
    - parole reminder send loop resolves and sends
    - writeback drain resolves and sends
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
        "PATHWAYS_PHONE_MAP_BACKEND",
        "PATHWAYS_PHONE_ENCRYPTION_KEY",
        "DATABASE_URL",
    ]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "phonemap-test")
    monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")

    from pathways.sessions import phone_map, checkpointer
    from pathways.parole_reminders import reset_store as reset_rem
    from pathways.dashboard import writeback as wb
    from pathways import graph as graph_mod

    phone_map.reset_store()
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    reset_rem()
    wb.reset_store()
    from pathways.sessions import idempotency
    idempotency._seen_sids.clear()
    yield
    phone_map.reset_store()


# ---------------------------------------------------------------------------
# Memory backend
# ---------------------------------------------------------------------------


def test_memory_backend_set_and_get():
    from pathways.sessions.phone_map import resolve, set_phone
    set_phone("hash-x", "+17135550100")
    assert resolve("hash-x") == "+17135550100"


def test_resolve_returns_none_for_unknown_thread():
    from pathways.sessions.phone_map import resolve
    assert resolve("hash-unknown") is None


def test_set_phone_silently_ignores_empty_inputs():
    from pathways.sessions.phone_map import resolve, set_phone
    set_phone("", "+17135550100")
    set_phone("hash-x", "")
    # Neither should have written; both reads return None.
    assert resolve("hash-x") is None


def test_no_database_url_uses_memory_backend_safely():
    from pathways.sessions.phone_map import get_store
    from pathways.sessions.phone_map import _MemoryStore
    store = get_store()
    assert isinstance(store, _MemoryStore)


# ---------------------------------------------------------------------------
# Fernet encryption round-trip (no DB; we test the encrypt/decrypt branch)
# ---------------------------------------------------------------------------


def test_fernet_round_trip_with_valid_key():
    from cryptography.fernet import Fernet
    from pathways.sessions.phone_map import _PostgresStore

    key = Fernet.generate_key()
    store = _PostgresStore(key)
    encrypted = store._fernet.encrypt(b"+17135550100")
    decrypted = store._fernet.decrypt(encrypted).decode("utf-8")
    assert decrypted == "+17135550100"


def test_postgres_backend_with_no_db_url_falls_back_to_memory(monkeypatch):
    """If postgres is requested but DATABASE_URL is missing, the factory
    must fall back to memory rather than crashing the API path."""
    monkeypatch.setenv("PATHWAYS_PHONE_MAP_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "PATHWAYS_PHONE_ENCRYPTION_KEY",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    from pathways.sessions import phone_map
    phone_map.reset_store()
    from pathways.sessions.phone_map import _MemoryStore, get_store
    assert isinstance(get_store(), _MemoryStore)


def test_postgres_backend_with_missing_key_falls_back_to_memory(monkeypatch):
    """Postgres requested + DATABASE_URL set BUT key missing = memory
    backend + warning. Prevents accidental plaintext writes."""
    monkeypatch.setenv("PATHWAYS_PHONE_MAP_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgres://fake")
    monkeypatch.delenv("PATHWAYS_PHONE_ENCRYPTION_KEY", raising=False)
    from pathways.sessions import phone_map
    phone_map.reset_store()
    from pathways.sessions.phone_map import _MemoryStore, get_store
    assert isinstance(get_store(), _MemoryStore)


# ---------------------------------------------------------------------------
# SMS handler writes the mapping on every inbound
# ---------------------------------------------------------------------------


def test_sms_handler_writes_phone_to_map():
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    from pathways.sessions.phone_map import resolve
    from pathways.sessions import thread_id_for_phone

    client = TestClient(api)
    r = client.post(
        "/sms",
        data={"Body": "hey", "From": "+17135550199", "MessageSid": "SMphonetest1"},
    )
    assert r.status_code == 200

    tid = thread_id_for_phone("+17135550199")
    assert resolve(tid) == "+17135550199"


def test_sms_stop_keyword_still_writes_phone_map():
    """Even on opt-out, we want the phone map populated in case the
    user opts back in later. STOP only affects whether we SEND, not
    whether we KNOW the phone."""
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    from pathways.sessions.phone_map import resolve
    from pathways.sessions import thread_id_for_phone

    client = TestClient(api)
    client.post(
        "/sms",
        data={"Body": "STOP", "From": "+17135550200", "MessageSid": "SMstop1"},
    )
    tid = thread_id_for_phone("+17135550200")
    assert resolve(tid) == "+17135550200"


# ---------------------------------------------------------------------------
# Send loops now resolve phones via the map
# ---------------------------------------------------------------------------


def test_parole_send_loop_resolves_via_map_and_sends():
    """End-to-end: SMS arrives -> phone written -> parole reminder
    queued -> daily cron resolves via map and sends."""
    from datetime import date, timedelta

    from pathways.parole_reminders import record_reminder
    from pathways.parole_reminders.service import run_send_loop
    from pathways.sessions.phone_map import set_phone

    set_phone("thread-x", "+17135550111")
    today = date(2026, 5, 16)
    record_reminder("thread-x", today + timedelta(days=1))

    sent: list = []
    def fake_send(to, body):
        sent.append((to, body))
        return True

    summary = run_send_loop(today=today, send_fn=fake_send)
    assert summary["sent"] == 1
    assert summary["skipped_no_phone"] == 0
    assert sent[0][0] == "+17135550111"


def test_writeback_drain_resolves_via_map_and_sends():
    from pathways.dashboard.writeback import drain_pending, enqueue_message
    from pathways.sessions.phone_map import set_phone

    set_phone("thread-y", "+17135550222")
    enqueue_message("thread-y", "hello from caseworker", "Houston Coalition")

    sent: list = []
    def fake_send(to, body):
        sent.append((to, body))
        return True

    summary = drain_pending(send_fn=fake_send)
    assert summary["sent"] == 1
    assert summary["skipped_no_phone"] == 0
    assert sent[0] == ("+17135550222", "hello from caseworker")


def test_parole_send_loop_skips_when_phone_map_empty():
    """Defensive: even with the map module available, if no phone is
    registered for the thread, the loop counts skipped_no_phone."""
    from datetime import date, timedelta

    from pathways.parole_reminders import record_reminder
    from pathways.parole_reminders.service import run_send_loop

    today = date(2026, 5, 16)
    record_reminder("thread-empty", today + timedelta(days=1))

    summary = run_send_loop(
        today=today, send_fn=lambda t, b: True,
    )
    assert summary["sent"] == 0
    assert summary["skipped_no_phone"] == 1
