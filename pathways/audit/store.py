"""Audit log persistence.

Memory backend stores plaintext AuditEvent objects (tests + demo).
Postgres backend stores the JSON-serialized payload encrypted with
Fernet (separate key from the phone map).

The Postgres schema keeps two columns out of the encrypted blob so
the typical filter (per-thread, per-time-range) stays indexable:
    thread_id  (TEXT)         - the salted SHA-256, same shape as
                                everywhere else in the codebase
    ts         (TIMESTAMPTZ)  - when the turn happened
    payload    (BYTEA)        - Fernet-encrypted JSON of everything else

Indexed: (thread_id, ts DESC) and (ts) for the retention purge.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("pathways.audit")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    ts TIMESTAMPTZ DEFAULT now(),
    payload BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_thread_ts
    ON audit_log (thread_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts
    ON audit_log (ts);
"""


@dataclass
class AuditEvent:
    """Full-content per-turn audit record. The store handles encryption."""
    thread_id: str
    channel: Optional[str] = None
    user_message: str = ""
    reply: str = ""
    needs: list[str] = field(default_factory=list)
    language: Optional[str] = None
    region: Optional[str] = None
    county: Optional[str] = None
    workforce_region: Optional[str] = None
    zipcode: Optional[str] = None
    supervision_status: Optional[str] = None
    intake_complete: bool = False
    intake_stage: Optional[str] = None
    retrievals: list[dict] = field(default_factory=list)
    matched_resources: list[dict] = field(default_factory=list)
    audit_verdict: Optional[str] = None
    audit_issues: list[dict] = field(default_factory=list)
    escalated: bool = False
    escalation_reason: Optional[str] = None
    crisis_fired: bool = False
    crisis_category: Optional[str] = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_payload_dict(self) -> dict:
        """Everything except thread_id + ts (those are columns)."""
        d = asdict(self)
        d.pop("thread_id", None)
        d.pop("ts", None)
        return d


# ---------------------------------------------------------------------------
# Memory backend
# ---------------------------------------------------------------------------


class _MemoryStore:
    def __init__(self) -> None:
        self._rows: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self._rows.append(event)

    def query(
        self,
        thread_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        with self._lock:
            rows = list(self._rows)
        if thread_id:
            rows = [r for r in rows if r.thread_id == thread_id]
        if since:
            rows = [r for r in rows if r.ts >= since]
        rows.sort(key=lambda r: r.ts, reverse=True)
        return rows[:limit]

    def purge_older_than(self, cutoff: datetime) -> int:
        with self._lock:
            before = len(self._rows)
            self._rows = [r for r in self._rows if r.ts >= cutoff]
            return before - len(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


# ---------------------------------------------------------------------------
# Postgres backend (Fernet-encrypted payload)
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
            raise RuntimeError("DATABASE_URL required for postgres audit backend")
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

    def append(self, event: AuditEvent) -> None:
        payload_json = json.dumps(event.to_payload_dict(), default=str)
        token = self._fernet.encrypt(payload_json.encode("utf-8"))
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (thread_id, ts, payload) "
                    "VALUES (%s, %s, %s)",
                    (event.thread_id, event.ts, token),
                )

    def query(
        self,
        thread_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        sql = "SELECT thread_id, ts, payload FROM audit_log WHERE 1=1"
        params: list = []
        if thread_id:
            sql += " AND thread_id = %s"
            params.append(thread_id)
        if since:
            sql += " AND ts >= %s"
            params.append(since)
        sql += " ORDER BY ts DESC LIMIT %s"
        params.append(limit)
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        out: list[AuditEvent] = []
        for r in rows:
            try:
                decrypted = self._fernet.decrypt(bytes(r["payload"]))
                data = json.loads(decrypted.decode("utf-8"))
            except Exception:
                logger.exception("audit_log: decrypt failed for one row; skipping")
                continue
            out.append(AuditEvent(
                thread_id=r["thread_id"],
                ts=r["ts"],
                **{k: v for k, v in data.items() if k in AuditEvent.__dataclass_fields__},
            ))
        return out

    def purge_older_than(self, cutoff: datetime) -> int:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM audit_log WHERE ts < %s", (cutoff,))
                return cur.rowcount or 0

    def clear(self) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM audit_log")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_STORE: Any = None


def _build_store():
    backend = os.environ.get(
        "PATHWAYS_AUDIT_BACKEND",
        "postgres" if os.environ.get("DATABASE_URL") else "memory",
    ).lower()
    if backend == "postgres" and os.environ.get("DATABASE_URL"):
        key = os.environ.get("PATHWAYS_AUDIT_ENCRYPTION_KEY", "").strip()
        if not key:
            logger.warning(
                "audit: PATHWAYS_AUDIT_ENCRYPTION_KEY unset; "
                "falling back to memory. Audit entries will not survive a "
                "process restart until you set the key.",
            )
            return _MemoryStore()
        try:
            return _PostgresStore(key.encode("ascii"))
        except Exception as e:
            logger.warning(
                "audit: postgres init failed (%s); falling back to memory.", e,
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
