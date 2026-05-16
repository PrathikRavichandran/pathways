"""Forward phone-number resolver: thread_id -> phone.

The salted SHA-256 thread_id (see pathways.sessions.thread) is one-way
on purpose, so the LangGraph checkpoint tables never store a phone
number. But to send outbound SMS for parole reminders and NGO write-
back, we need to recover the phone from the thread. This module owns
that mapping.

Two backends, mirroring the rest of the codebase:
    memory   - in-process dict. Tests + demo mode (no encryption).
    postgres - session_phones table with Fernet-encrypted phone.
               Requires DATABASE_URL + PATHWAYS_PHONE_ENCRYPTION_KEY
               (base64-encoded 32-byte Fernet key; generate via
               `python -c "from cryptography.fernet import Fernet; \\
               print(Fernet.generate_key().decode())"`).

Failure mode: if PATHWAYS_PHONE_ENCRYPTION_KEY is unset OR malformed
when postgres backend is requested, the factory falls back to the
memory backend and logs a warning. This is intentional: a
misconfigured deploy should not crash the API path; outbound queues
will simply continue reporting skipped_no_phone until the operator
sets the key.

Write path: pathways/api/main.py SMS handler calls set_phone() after
deriving the thread_id from the incoming From.

Read path: pathways/parole_reminders/service.py and
pathways/dashboard/writeback.py call resolve() at send time.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("pathways.sessions.phone_map")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS session_phones (
    thread_id TEXT PRIMARY KEY,
    encrypted_phone BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_seen TIMESTAMPTZ DEFAULT now()
);
"""


# ---------------------------------------------------------------------------
# Memory backend (tests + demo + key-unset fallback)
# ---------------------------------------------------------------------------


class _MemoryStore:
    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._lock = threading.Lock()

    def set(self, thread_id: str, phone: str) -> None:
        with self._lock:
            self._map[thread_id] = phone

    def get(self, thread_id: str) -> Optional[str]:
        with self._lock:
            return self._map.get(thread_id)

    def clear(self) -> None:
        with self._lock:
            self._map.clear()


# ---------------------------------------------------------------------------
# Postgres backend with Fernet encryption
# ---------------------------------------------------------------------------


class _PostgresStore:
    def __init__(self, fernet_key: bytes) -> None:
        from cryptography.fernet import Fernet
        self._fernet = Fernet(fernet_key)
        self._pool = None

    def _get_pool(self):
        if self._pool is not None:
            return self._pool
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise RuntimeError(
                "DATABASE_URL is required for postgres phone_map backend"
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

    def set(self, thread_id: str, phone: str) -> None:
        token = self._fernet.encrypt(phone.encode("utf-8"))
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO session_phones (thread_id, encrypted_phone)
                    VALUES (%s, %s)
                    ON CONFLICT (thread_id) DO UPDATE
                    SET encrypted_phone = EXCLUDED.encrypted_phone,
                        last_seen = now()
                    """,
                    (thread_id, token),
                )

    def get(self, thread_id: str) -> Optional[str]:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT encrypted_phone FROM session_phones "
                    "WHERE thread_id = %s",
                    (thread_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        try:
            return self._fernet.decrypt(bytes(row["encrypted_phone"])).decode("utf-8")
        except Exception:
            logger.exception(
                "phone_map: failed to decrypt phone for thread_id=%s "
                "(wrong key?)", thread_id,
            )
            return None

    def clear(self) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM session_phones")


# ---------------------------------------------------------------------------
# Factory + public API
# ---------------------------------------------------------------------------


_STORE: Any = None


def _build_store():
    backend = os.environ.get(
        "PATHWAYS_PHONE_MAP_BACKEND",
        "postgres" if os.environ.get("DATABASE_URL") else "memory",
    ).lower()

    if backend == "postgres" and os.environ.get("DATABASE_URL"):
        key = os.environ.get("PATHWAYS_PHONE_ENCRYPTION_KEY", "").strip()
        if not key:
            logger.warning(
                "phone_map: PATHWAYS_PHONE_ENCRYPTION_KEY unset; "
                "falling back to memory backend. Outbound queues will "
                "skip due to no-phone until you set the key."
            )
            return _MemoryStore()
        try:
            return _PostgresStore(key.encode("ascii"))
        except Exception as e:
            logger.warning(
                "phone_map: failed to initialize postgres backend (%s); "
                "falling back to memory.", e,
            )
            return _MemoryStore()

    return _MemoryStore()


def get_store():
    global _STORE
    if _STORE is None:
        _STORE = _build_store()
    return _STORE


def reset_store() -> None:
    """Test helper."""
    global _STORE
    _STORE = None


def set_phone(thread_id: str, phone: str) -> None:
    """Persist the thread_id -> phone mapping. Never raises; analytics
    + outbound infra must not affect the user-facing reply path."""
    if not thread_id or not phone:
        return
    try:
        get_store().set(thread_id, phone)
    except Exception:
        logger.exception("phone_map.set_phone failed (non-fatal)")


def resolve(thread_id: str) -> Optional[str]:
    """Return the phone for this thread_id, or None if unknown.

    The send loops in pathways/parole_reminders/service.py and
    pathways/dashboard/writeback.py call this at send time."""
    if not thread_id:
        return None
    try:
        return get_store().get(thread_id)
    except Exception:
        logger.exception("phone_map.resolve failed (non-fatal)")
        return None
