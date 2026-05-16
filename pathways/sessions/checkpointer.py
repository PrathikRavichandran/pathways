"""LangGraph checkpointer factory.

The checkpointer is what makes multi-turn conversations possible. When
the graph is compiled with a checkpointer and invoked with a `thread_id`
config, LangGraph persists the post-turn state and restores it on the
next invocation of the same thread.

Three backends, selected by PATHWAYS_CHECKPOINT_BACKEND:
    memory   (default): in-process MemorySaver. Lost on restart.
                        Fine for unit tests and the cold demo path.
    sqlite : on-disk SqliteSaver. Survives restart on the same host
                        but not multi-instance. Useful for local dev.
    postgres: PostgresSaver against DATABASE_URL. Production.
                        Survives restart, supports multi-instance,
                        queryable for the Phase 5 caseworker dashboard.
"""

from __future__ import annotations

import os
from typing import Optional

_CHECKPOINTER = None


def get_checkpointer():
    """Return the configured checkpointer (singleton).

    Selected by the PATHWAYS_CHECKPOINT_BACKEND env var. The selection
    is cached after the first call; in tests, call `reset_checkpointer()`
    between cases that need different backends.
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    backend = os.environ.get("PATHWAYS_CHECKPOINT_BACKEND", "memory").lower()

    if backend == "postgres":
        _CHECKPOINTER = _make_postgres_checkpointer()
    elif backend == "sqlite":
        _CHECKPOINTER = _make_sqlite_checkpointer()
    else:
        # The default MemorySaver uses msgpack which cannot serialize
        # arbitrary Pydantic models (the project's state carries Retrieval,
        # IntakeProfile, AuditResult, etc.). JsonPlusSerializer with the
        # pickle fallback round-trips Pydantic objects correctly.
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        _CHECKPOINTER = MemorySaver(serde=JsonPlusSerializer(pickle_fallback=True))

    return _CHECKPOINTER


def reset_checkpointer() -> None:
    """Drop the cached checkpointer. Test-only helper."""
    global _CHECKPOINTER
    _CHECKPOINTER = None


def _make_postgres_checkpointer():
    """Build a PostgresSaver backed by a connection pool.

    Use a ConnectionPool (not from_conn_string) so the connection survives
    the lifetime of the FastAPI process. from_conn_string returns a context
    manager that closes its connection as soon as the entering context
    finishes, which kills the saver as soon as the constructor exits.

    pickle_fallback on the serializer is needed because the project's state
    carries Pydantic models (Retrieval, IntakeProfile, AuditResult). The
    default msgpack-backed serializer cannot round-trip them.

    Creates the langgraph checkpoint tables on first call (idempotent).
    """
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "PATHWAYS_CHECKPOINT_BACKEND=postgres but DATABASE_URL is unset."
        )

    pool = ConnectionPool(
        conninfo=db_url,
        min_size=1,
        max_size=int(os.environ.get("PATHWAYS_PG_POOL_MAX", "10")),
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=True,
    )
    saver = PostgresSaver(pool)
    saver.serde = JsonPlusSerializer(pickle_fallback=True)
    saver.setup()
    return saver


def _make_sqlite_checkpointer():
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    sqlite_path = os.environ.get(
        "PATHWAYS_SQLITE_PATH", "pathways_checkpoints.sqlite"
    )
    cm = SqliteSaver.from_conn_string(sqlite_path)
    saver = cm.__enter__()
    saver.serde = JsonPlusSerializer(pickle_fallback=True)
    return saver
