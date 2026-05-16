"""Inbound message idempotency + session bookkeeping.

Twilio retries webhook deliveries when it does not get a 2xx within a
narrow timeout. Without idempotency, a retry causes the graph to run
twice for the same MessageSid, charging the LLM twice and possibly
double-replying to the user.

The dedup table has a single column PRIMARY KEY on `message_sid`, so
the insert is an O(1) check. Idempotency MUST happen before graph
invocation, not after.

In demo mode (no DATABASE_URL set), an in-process dict is used with a
24-hour rolling window. This is enough for local pytest and the cold
HF Space boot path; it does not survive a process restart.
"""

from __future__ import annotations

import os
import time
from typing import Optional

# In-memory fallback when DATABASE_URL is unset
_seen_sids: dict[str, float] = {}
_IN_MEMORY_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _gc_in_memory() -> None:
    """Drop in-memory dedup entries older than the TTL."""
    cutoff = time.time() - _IN_MEMORY_TTL_SECONDS
    stale = [k for k, v in _seen_sids.items() if v < cutoff]
    for k in stale:
        del _seen_sids[k]


def seen_message_sid(message_sid: str, thread_id: Optional[str] = None) -> bool:
    """Return True if this MessageSid has been processed in the last 24h.

    Returns False (and atomically records the SID) if it is new.

    Fails open: on any database error, returns False so the turn proceeds.
    Better to occasionally double-process than to silently block a
    legitimate inbound on a transient infra hiccup.
    """
    if not message_sid:
        # No SID means we can't dedup. Twilio always sends one in production;
        # absence usually indicates a synthetic test request.
        return False

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        _gc_in_memory()
        if message_sid in _seen_sids:
            return True
        _seen_sids[message_sid] = time.time()
        return False

    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO inbound_message_dedup (message_sid, thread_id)
                    VALUES (%s, %s)
                    ON CONFLICT (message_sid) DO NOTHING
                    RETURNING message_sid;
                    """,
                    (message_sid, thread_id),
                )
                row = cur.fetchone()
                conn.commit()
        # If row is None, INSERT did nothing (conflict), meaning we've seen it.
        return row is None
    except Exception:
        # Fail open. Log to stderr in case operators are watching.
        import sys
        sys.stderr.write(
            f"idempotency: DB error checking sid={message_sid!r}; "
            f"failing open (turn proceeds)\n"
        )
        return False


def touch_session(thread_id: str) -> None:
    """Upsert into the sessions table to bump first_seen / last_seen /
    message_count. Best-effort; failures don't block the turn."""
    if not thread_id:
        return
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return  # no-op in demo mode

    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions (thread_id, first_seen, last_seen, message_count)
                    VALUES (%s, now(), now(), 1)
                    ON CONFLICT (thread_id) DO UPDATE
                      SET last_seen = now(),
                          message_count = sessions.message_count + 1;
                    """,
                    (thread_id,),
                )
                conn.commit()
    except Exception:
        pass  # never block the turn on a session-table failure


def mark_opted_out(thread_id: str) -> None:
    """Set opted_out=true for a thread (TCPA STOP handling)."""
    if not thread_id:
        return
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return
    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sessions (thread_id, opted_out, opted_out_at)
                    VALUES (%s, true, now())
                    ON CONFLICT (thread_id) DO UPDATE
                      SET opted_out = true, opted_out_at = now();
                    """,
                    (thread_id,),
                )
                conn.commit()
    except Exception:
        pass


def is_opted_out(thread_id: str) -> bool:
    """Return True if this thread has previously sent STOP."""
    if not thread_id:
        return False
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return False
    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT opted_out FROM sessions WHERE thread_id = %s",
                    (thread_id,),
                )
                row = cur.fetchone()
                return bool(row and row[0])
    except Exception:
        return False
