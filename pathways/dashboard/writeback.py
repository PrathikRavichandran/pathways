"""NGO write-back: caseworker queues an SMS to a user via the dashboard.

The caseworker never sees the user's phone number. They send by
thread_id (which is the salted hash they see in the dashboard's
anonymized recent-conversations table). Pathways acts as a trust-
preserving relay: the partner gets a way to reach the user; the
user's phone stays private.

Architecture:
    POST /dashboard/api/writeback enqueues a message to relay_messages.
    The same daily cron that runs parole reminders (with a small
    extension) drains the queue: resolve thread_id -> phone via the
    forward map, send via Twilio outbound, mark sent.

In MVP the forward map is not yet wired (same dependency as parole
reminders), so queued messages stay in the queue until the operator
wires a `pathways.sessions.phone_map` resolver. The API surface and
the queue table ship today so the dashboard work flows end-to-end and
the only remaining piece is the phone-map plumbing.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS relay_messages (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    partner_name TEXT,
    body TEXT NOT NULL,
    queued_at TIMESTAMPTZ DEFAULT now(),
    sent_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    failure_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_relay_messages_pending
    ON relay_messages (queued_at)
    WHERE sent_at IS NULL AND failed_at IS NULL;
"""


@dataclass
class RelayMessage:
    thread_id: str
    body: str
    partner_name: Optional[str] = None
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sent_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    id: Optional[int] = None


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class _MemoryStore:
    def __init__(self) -> None:
        self._rows: list[RelayMessage] = []
        self._lock = threading.Lock()

    def enqueue(self, msg: RelayMessage) -> int:
        with self._lock:
            msg.id = len(self._rows) + 1
            self._rows.append(msg)
            return msg.id

    def pending(self) -> list[RelayMessage]:
        with self._lock:
            return [
                r for r in self._rows
                if r.sent_at is None and r.failed_at is None
            ]

    def mark_sent(self, msg_id: int) -> None:
        with self._lock:
            for r in self._rows:
                if r.id == msg_id:
                    r.sent_at = datetime.now(timezone.utc)
                    return

    def mark_failed(self, msg_id: int, reason: str) -> None:
        with self._lock:
            for r in self._rows:
                if r.id == msg_id:
                    r.failed_at = datetime.now(timezone.utc)
                    r.failure_reason = reason
                    return

    def all(self) -> list[RelayMessage]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


class _PostgresStore:
    def __init__(self) -> None:
        self._pool = None

    def _get_pool(self):
        if self._pool is not None:
            return self._pool
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise RuntimeError(
                "DATABASE_URL is required for postgres writeback backend"
            )
        self._pool = ConnectionPool(
            conninfo=db_url, min_size=1, max_size=3,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=True,
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # psycopg prepared-statement mode rejects multi-stmt SQL;
                # run each DDL piece separately.
                for stmt in CREATE_TABLE_SQL.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)
        return self._pool

    def enqueue(self, msg: RelayMessage) -> int:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO relay_messages (thread_id, partner_name, body) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (msg.thread_id, msg.partner_name, msg.body),
                )
                row = cur.fetchone()
                return int(row["id"]) if row else -1

    def pending(self) -> list[RelayMessage]:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, thread_id, partner_name, body, queued_at, "
                    "sent_at, failed_at, failure_reason FROM relay_messages "
                    "WHERE sent_at IS NULL AND failed_at IS NULL "
                    "ORDER BY queued_at"
                )
                rows = cur.fetchall()
        return [
            RelayMessage(
                id=r["id"], thread_id=r["thread_id"], body=r["body"],
                partner_name=r["partner_name"], queued_at=r["queued_at"],
                sent_at=r["sent_at"], failed_at=r["failed_at"],
                failure_reason=r["failure_reason"],
            )
            for r in rows
        ]

    def mark_sent(self, msg_id: int) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE relay_messages SET sent_at = now() WHERE id = %s",
                    (msg_id,),
                )

    def mark_failed(self, msg_id: int, reason: str) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE relay_messages SET failed_at = now(), "
                    "failure_reason = %s WHERE id = %s",
                    (reason, msg_id),
                )

    def all(self) -> list[RelayMessage]:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, thread_id, partner_name, body, queued_at, "
                    "sent_at, failed_at, failure_reason FROM relay_messages "
                    "ORDER BY queued_at DESC"
                )
                rows = cur.fetchall()
        return [
            RelayMessage(
                id=r["id"], thread_id=r["thread_id"], body=r["body"],
                partner_name=r["partner_name"], queued_at=r["queued_at"],
                sent_at=r["sent_at"], failed_at=r["failed_at"],
                failure_reason=r["failure_reason"],
            )
            for r in rows
        ]

    def clear(self) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM relay_messages")


_STORE: Any = None


def get_store():
    global _STORE
    if _STORE is not None:
        return _STORE
    backend = os.environ.get(
        "PATHWAYS_WRITEBACK_BACKEND",
        "postgres" if os.environ.get("DATABASE_URL") else "memory",
    ).lower()
    if backend == "postgres" and os.environ.get("DATABASE_URL"):
        try:
            _STORE = _PostgresStore()
            return _STORE
        except Exception:
            pass
    _STORE = _MemoryStore()
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = None


def enqueue_message(thread_id: str, body: str, partner_name: str) -> int:
    """Queue a relay message. Returns the row id."""
    return get_store().enqueue(RelayMessage(
        thread_id=thread_id, body=body, partner_name=partner_name,
    ))


def drain_pending(send_fn=None, phone_for_thread=None) -> dict:
    """Send all pending relay messages. Returns a summary dict.

    Same shape as parole_reminders.run_send_loop so the same cron
    entrypoint can fan out to both. Skips messages whose thread_id
    cannot be resolved to a phone.
    """
    if send_fn is None:
        from pathways.twilio_client import send_sms as send_fn  # type: ignore
    if phone_for_thread is None:
        from pathways.parole_reminders.service import _resolve_phone
        phone_for_thread = _resolve_phone

    store = get_store()
    pending = store.pending()
    sent = 0
    skipped_no_phone = 0
    failed = 0
    for msg in pending:
        phone = phone_for_thread(msg.thread_id)
        if not phone:
            skipped_no_phone += 1
            continue
        try:
            ok = send_fn(phone, msg.body)
        except Exception as e:
            store.mark_failed(msg.id or 0, str(e))
            failed += 1
            continue
        if ok:
            store.mark_sent(msg.id or 0)
            sent += 1
        else:
            store.mark_failed(msg.id or 0, "send returned False")
            failed += 1
    return {
        "pending_before": len(pending),
        "sent": sent,
        "skipped_no_phone": skipped_no_phone,
        "failed": failed,
    }
