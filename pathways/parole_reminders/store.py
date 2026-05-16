"""parole_reminders persistence.

Two backends:
    memory   - in-process list. Default when DATABASE_URL is unset.
               Used for tests + demo mode.
    postgres - writes to the parole_reminders table. Auto-created on
               first store access (idempotent CREATE TABLE IF NOT EXISTS).

The store keys by the salted thread_id only. Phone numbers are never
written here; the sender retrieves them at send time from the
session-to-phone mapping (also salted-hash keyed).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS parole_reminders (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    check_in_date DATE NOT NULL,
    sent_at TIMESTAMPTZ,
    opted_out BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (thread_id, check_in_date)
);
CREATE INDEX IF NOT EXISTS idx_parole_reminders_due
    ON parole_reminders (check_in_date)
    WHERE sent_at IS NULL AND NOT opted_out;
"""


@dataclass
class ParoleReminder:
    thread_id: str
    check_in_date: date
    sent_at: Optional[datetime] = None
    opted_out: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class _MemoryStore:
    def __init__(self) -> None:
        self._rows: list[ParoleReminder] = []
        self._lock = threading.Lock()

    def upsert(self, reminder: ParoleReminder) -> None:
        with self._lock:
            for r in self._rows:
                if (
                    r.thread_id == reminder.thread_id
                    and r.check_in_date == reminder.check_in_date
                ):
                    r.opted_out = reminder.opted_out
                    return
            self._rows.append(reminder)

    def due_on(self, target_date: date) -> list[ParoleReminder]:
        with self._lock:
            return [
                r for r in self._rows
                if r.check_in_date == target_date
                and r.sent_at is None
                and not r.opted_out
            ]

    def mark_sent(self, thread_id: str, check_in_date: date) -> None:
        with self._lock:
            for r in self._rows:
                if (
                    r.thread_id == thread_id
                    and r.check_in_date == check_in_date
                ):
                    r.sent_at = datetime.now(timezone.utc)
                    return

    def opt_out(self, thread_id: str) -> int:
        with self._lock:
            count = 0
            for r in self._rows:
                if r.thread_id == thread_id and not r.opted_out:
                    r.opted_out = True
                    count += 1
            return count

    def all(self) -> list[ParoleReminder]:
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
                "DATABASE_URL is required for postgres parole_reminders backend"
            )
        self._pool = ConnectionPool(
            conninfo=db_url,
            min_size=1,
            max_size=int(os.environ.get("PATHWAYS_REMINDERS_PG_MAX", "3")),
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=True,
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLE_SQL)
        return self._pool

    def upsert(self, reminder: ParoleReminder) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO parole_reminders (thread_id, check_in_date, opted_out)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (thread_id, check_in_date) DO UPDATE
                    SET opted_out = EXCLUDED.opted_out
                    """,
                    (reminder.thread_id, reminder.check_in_date, reminder.opted_out),
                )

    def due_on(self, target_date: date) -> list[ParoleReminder]:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT thread_id, check_in_date, sent_at, opted_out, created_at
                    FROM parole_reminders
                    WHERE check_in_date = %s
                      AND sent_at IS NULL
                      AND NOT opted_out
                    """,
                    (target_date,),
                )
                rows = cur.fetchall()
        return [
            ParoleReminder(
                thread_id=r["thread_id"],
                check_in_date=r["check_in_date"],
                sent_at=r["sent_at"],
                opted_out=bool(r["opted_out"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def mark_sent(self, thread_id: str, check_in_date: date) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE parole_reminders
                    SET sent_at = now()
                    WHERE thread_id = %s AND check_in_date = %s
                    """,
                    (thread_id, check_in_date),
                )

    def opt_out(self, thread_id: str) -> int:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE parole_reminders SET opted_out = true
                    WHERE thread_id = %s AND NOT opted_out
                    """,
                    (thread_id,),
                )
                return cur.rowcount or 0

    def all(self) -> list[ParoleReminder]:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT thread_id, check_in_date, sent_at, opted_out, "
                    "created_at FROM parole_reminders ORDER BY check_in_date"
                )
                rows = cur.fetchall()
        return [
            ParoleReminder(
                thread_id=r["thread_id"],
                check_in_date=r["check_in_date"],
                sent_at=r["sent_at"],
                opted_out=bool(r["opted_out"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def clear(self) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM parole_reminders")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_STORE: Any = None


def get_store():
    global _STORE
    if _STORE is not None:
        return _STORE
    backend = os.environ.get(
        "PATHWAYS_REMINDERS_BACKEND",
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
    """Test helper."""
    global _STORE
    _STORE = None


def record_reminder(thread_id: str, check_in_date: date) -> None:
    """Convenience: upsert a new reminder."""
    try:
        get_store().upsert(ParoleReminder(
            thread_id=thread_id, check_in_date=check_in_date,
        ))
    except Exception:
        pass
