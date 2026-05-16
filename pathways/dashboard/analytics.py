"""Conversation analytics.

This is the seam where one turn's metrics get written to a queryable
store so the dashboard can render aggregates without ever having to
crack open the LangGraph checkpoint blobs.

Two backends:
    postgres : production. Writes to the conversation_events table.
    memory   : in-process list. Default when DATABASE_URL is unset.
               Used for tests + demo mode.

We deliberately strip every field that could constitute PII before
storage:
    - No raw user message text (length only)
    - No raw reply text (length only)
    - No phone numbers (thread_id is already the salted hash)
    - No name
    - No raw ZIP (we keep the WORKFORCE_REGION, which is one of 28
      coarse buckets covering all 254 TX counties; not a PII level
      of granularity)

The dashboard cannot leak PII because the writer never wrote any.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_events (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    channel TEXT,
    language TEXT,
    needs TEXT[],
    region TEXT,
    county TEXT,
    workforce_region TEXT,
    supervision_status TEXT,
    retrieval_confidence REAL,
    retrieval_results_count INT,
    audit_verdict TEXT,
    escalated BOOLEAN DEFAULT false,
    escalation_reason TEXT,
    matched_resource_count INT,
    user_message_length INT,
    reply_length INT,
    crisis_fired BOOLEAN DEFAULT false,
    intake_complete BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_events_created
    ON conversation_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_events_region
    ON conversation_events (region) WHERE region IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conv_events_workforce
    ON conversation_events (workforce_region)
    WHERE workforce_region IS NOT NULL;
"""


# ---------------------------------------------------------------------------
# Event model (post-PII-scrub projection of a turn)
# ---------------------------------------------------------------------------


@dataclass
class TurnEvent:
    thread_id: str
    channel: Optional[str] = None
    language: Optional[str] = None
    needs: list[str] = field(default_factory=list)
    region: Optional[str] = None
    county: Optional[str] = None
    workforce_region: Optional[str] = None
    supervision_status: Optional[str] = None
    retrieval_confidence: Optional[float] = None
    retrieval_results_count: Optional[int] = None
    audit_verdict: Optional[str] = None
    escalated: bool = False
    escalation_reason: Optional[str] = None
    matched_resource_count: Optional[int] = None
    user_message_length: Optional[int] = None
    reply_length: Optional[int] = None
    crisis_fired: bool = False
    intake_complete: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def event_from_state(final_state: dict | object, thread_id: str, channel: str,
                     user_message: str, reply: str,
                     crisis_fired: bool) -> TurnEvent:
    """Project a LangGraph final state into a PII-scrubbed TurnEvent.

    Tolerant of partial state (graph may have routed to escalate or END
    before some fields were populated). Resolves county/workforce_region
    from the ZIP via pathways.geo when possible.
    """
    # Allow either a dict or a Pydantic-like object
    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    intake = _get(final_state, "intake") or {}
    if hasattr(intake, "model_dump"):
        intake = intake.model_dump(mode="json")
    if not isinstance(intake, dict):
        intake = {}

    needs: list[str] = []
    top = intake.get("top_need")
    if top and top != "unknown":
        needs.append(str(top))
    for sn in intake.get("secondary_needs") or []:
        if sn and sn != "unknown" and sn not in needs:
            needs.append(str(sn))

    region = intake.get("region")
    zipcode = intake.get("zipcode")
    county = None
    workforce_region = None
    try:
        from pathways.geo import county_for_zip, workforce_region_for_zip
        if zipcode:
            county = county_for_zip(zipcode)
            workforce_region = workforce_region_for_zip(zipcode)
    except Exception:
        pass

    retrievals = _get(final_state, "retrievals") or []
    if retrievals:
        first = retrievals[0]
        if hasattr(first, "model_dump"):
            first = first.model_dump(mode="json")
        conf = float(first.get("confidence", 0.0)) if isinstance(first, dict) else 0.0
        rcount = len(first.get("results", []) if isinstance(first, dict) else [])
    else:
        conf = None
        rcount = None

    audit = _get(final_state, "audit")
    if audit and hasattr(audit, "model_dump"):
        audit = audit.model_dump(mode="json")
    audit_verdict = audit.get("verdict") if isinstance(audit, dict) else None

    matched = _get(final_state, "matched_resources") or []

    return TurnEvent(
        thread_id=thread_id,
        channel=channel,
        language=intake.get("language") or "en",
        needs=needs,
        region=region,
        county=county,
        workforce_region=workforce_region,
        supervision_status=intake.get("supervision_status"),
        retrieval_confidence=conf,
        retrieval_results_count=rcount,
        audit_verdict=audit_verdict,
        escalated=bool(_get(final_state, "escalation_reason")),
        escalation_reason=_get(final_state, "escalation_reason"),
        matched_resource_count=len(matched),
        user_message_length=len(user_message or ""),
        reply_length=len(reply or ""),
        crisis_fired=bool(crisis_fired),
        intake_complete=bool(_get(final_state, "intake_complete")),
    )


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class _MemoryStore:
    """Thread-safe in-process ring of TurnEvents. Tests + demo mode."""

    def __init__(self, max_events: int = 1000):
        self._events: list[TurnEvent] = []
        self._lock = threading.Lock()
        self._max = max_events

    def append(self, event: TurnEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max:
                self._events = self._events[-self._max:]

    def all(self) -> list[TurnEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class _PostgresStore:
    """Persistent backend. Uses the existing psycopg-pool if available."""

    def __init__(self):
        self._pool = None

    def _get_pool(self):
        if self._pool is not None:
            return self._pool
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL is required for postgres dashboard backend")
        self._pool = ConnectionPool(
            conninfo=db_url,
            min_size=1,
            max_size=int(os.environ.get("PATHWAYS_DASHBOARD_PG_MAX", "5")),
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

    def append(self, event: TurnEvent) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_events
                        (thread_id, channel, language, needs, region, county,
                         workforce_region, supervision_status,
                         retrieval_confidence, retrieval_results_count,
                         audit_verdict, escalated, escalation_reason,
                         matched_resource_count, user_message_length,
                         reply_length, crisis_fired, intake_complete,
                         created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s)
                    """,
                    (
                        event.thread_id,
                        event.channel,
                        event.language,
                        event.needs or None,
                        event.region,
                        event.county,
                        event.workforce_region,
                        event.supervision_status,
                        event.retrieval_confidence,
                        event.retrieval_results_count,
                        event.audit_verdict,
                        event.escalated,
                        event.escalation_reason,
                        event.matched_resource_count,
                        event.user_message_length,
                        event.reply_length,
                        event.crisis_fired,
                        event.intake_complete,
                        event.created_at,
                    ),
                )

    def all(self) -> list[TurnEvent]:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM conversation_events ORDER BY created_at DESC"
                )
                rows = cur.fetchall()
        return [
            TurnEvent(
                thread_id=r["thread_id"],
                channel=r["channel"],
                language=r["language"],
                needs=r["needs"] or [],
                region=r["region"],
                county=r["county"],
                workforce_region=r["workforce_region"],
                supervision_status=r["supervision_status"],
                retrieval_confidence=r["retrieval_confidence"],
                retrieval_results_count=r["retrieval_results_count"],
                audit_verdict=r["audit_verdict"],
                escalated=bool(r["escalated"]),
                escalation_reason=r["escalation_reason"],
                matched_resource_count=r["matched_resource_count"],
                user_message_length=r["user_message_length"],
                reply_length=r["reply_length"],
                crisis_fired=bool(r["crisis_fired"]),
                intake_complete=bool(r["intake_complete"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def clear(self) -> None:
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM conversation_events")


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------


_STORE: Any = None


def get_store():
    """Return the configured analytics store (singleton).

    Backend selected by PATHWAYS_DASHBOARD_BACKEND (memory | postgres).
    Falls back to memory if postgres is selected but DATABASE_URL is
    unset, so a misconfigured deploy doesn't break the API path.
    """
    global _STORE
    if _STORE is not None:
        return _STORE

    backend = os.environ.get(
        "PATHWAYS_DASHBOARD_BACKEND",
        # If DATABASE_URL is set, default to postgres; else memory.
        "postgres" if os.environ.get("DATABASE_URL") else "memory",
    ).lower()

    if backend == "postgres" and os.environ.get("DATABASE_URL"):
        try:
            _STORE = _PostgresStore()
            return _STORE
        except Exception:
            # Soft-fail to memory; dashboard works, just non-persistent.
            pass

    _STORE = _MemoryStore()
    return _STORE


def reset_store() -> None:
    """Drop the cached store. Test-only helper."""
    global _STORE
    _STORE = None


def record_turn(event: TurnEvent) -> None:
    """Append a turn event to the configured store. Never raises:
    analytics failures must not crash the API path."""
    try:
        get_store().append(event)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Aggregate queries
# ---------------------------------------------------------------------------


def _filter_scope(events: list[TurnEvent], scope: Optional[dict]) -> list[TurnEvent]:
    """Apply a partner's scope filter to an event list.

    Scope is a dict like {"workforce_regions": [...], "counties": [...],
    "regions": [...]} or None for unscoped (superuser).
    """
    if not scope:
        return events
    wf = set(scope.get("workforce_regions") or [])
    counties = set(scope.get("counties") or [])
    regions = set(scope.get("regions") or [])
    if not (wf or counties or regions):
        return events
    out = []
    for e in events:
        if wf and e.workforce_region in wf:
            out.append(e); continue
        if counties and e.county in counties:
            out.append(e); continue
        if regions and e.region in regions:
            out.append(e); continue
    return out


def _filter_window(events: list[TurnEvent], days: int) -> list[TurnEvent]:
    if days <= 0:
        return events
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [e for e in events if e.created_at >= cutoff]


def summary(scope: Optional[dict] = None, days: int = 7) -> dict:
    """High-level numbers for the landing page."""
    all_events = get_store().all()
    in_window = _filter_window(_filter_scope(all_events, scope), days)

    total_turns = len(in_window)
    distinct_threads = len({e.thread_id for e in in_window})
    escalated = sum(1 for e in in_window if e.escalated)
    crisis = sum(1 for e in in_window if e.crisis_fired)
    spanish = sum(1 for e in in_window if (e.language or "en") == "es")
    avg_conf = 0.0
    confs = [e.retrieval_confidence for e in in_window if e.retrieval_confidence is not None]
    if confs:
        avg_conf = sum(confs) / len(confs)
    matched_resources = sum((e.matched_resource_count or 0) for e in in_window)

    return {
        "window_days": days,
        "total_turns": total_turns,
        "distinct_threads": distinct_threads,
        "escalated": escalated,
        "crisis_fired": crisis,
        "spanish_share": (spanish / total_turns) if total_turns else 0.0,
        "avg_retrieval_confidence": round(avg_conf, 3),
        "matched_resources_total": matched_resources,
    }


def needs_by_region(scope: Optional[dict] = None, days: int = 30) -> list[dict]:
    """List of (region, need, count) rows for the needs table."""
    in_window = _filter_window(_filter_scope(get_store().all(), scope), days)
    counts: dict[tuple[str, str], int] = {}
    for e in in_window:
        region_label = e.workforce_region or e.region or "Statewide"
        for need in (e.needs or []):
            key = (region_label, need)
            counts[key] = counts.get(key, 0) + 1
    rows = [
        {"region": k[0], "need": k[1], "count": v}
        for k, v in counts.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["region"], r["need"]))
    return rows


def confidence_distribution(scope: Optional[dict] = None, days: int = 30,
                            bins: int = 5) -> list[dict]:
    """Coarse histogram of retrieval confidence in N equal-width bins."""
    in_window = _filter_window(_filter_scope(get_store().all(), scope), days)
    confs = [e.retrieval_confidence for e in in_window
             if e.retrieval_confidence is not None]
    if not confs:
        return []
    bin_size = 1.0 / bins
    counts = [0] * bins
    for c in confs:
        idx = min(int(c / bin_size), bins - 1)
        counts[idx] += 1
    out = []
    for i, count in enumerate(counts):
        out.append({
            "bin_low": round(i * bin_size, 2),
            "bin_high": round((i + 1) * bin_size, 2),
            "count": count,
        })
    return out


def recent_conversations(scope: Optional[dict] = None, limit: int = 25,
                         days: int = 7) -> list[dict]:
    """Anonymized recent turns. thread_id is already the salted hash, so
    we further truncate it for display."""
    in_window = _filter_window(_filter_scope(get_store().all(), scope), days)
    in_window.sort(key=lambda e: e.created_at, reverse=True)
    rows = []
    for e in in_window[:limit]:
        display_id = (e.thread_id or "")[:12]
        rows.append({
            "thread_id_display": display_id,
            "created_at": e.created_at.isoformat(),
            "channel": e.channel,
            "language": e.language,
            "needs": e.needs,
            "region": e.workforce_region or e.region,
            "supervision_status": e.supervision_status,
            "retrieval_confidence": e.retrieval_confidence,
            "matched_resource_count": e.matched_resource_count,
            "escalated": e.escalated,
            "escalation_reason": e.escalation_reason,
            "audit_verdict": e.audit_verdict,
            "crisis_fired": e.crisis_fired,
        })
    return rows


def escalation_reasons(scope: Optional[dict] = None, days: int = 30) -> list[dict]:
    """Frequency table of escalation reasons. Useful for spotting hotspots
    (e.g., audit hard-blocks on a specific claim type)."""
    in_window = _filter_window(_filter_scope(get_store().all(), scope), days)
    counts: dict[str, int] = {}
    for e in in_window:
        if not e.escalated:
            continue
        key = e.escalation_reason or "unspecified"
        counts[key] = counts.get(key, 0) + 1
    rows = [{"reason": k, "count": v} for k, v in counts.items()]
    rows.sort(key=lambda r: -r["count"])
    return rows


def render_markdown_report(
    partner_name: str,
    scope: Optional[dict] = None,
    days: int = 30,
) -> str:
    """Compose an anonymized monthly trend report (Markdown).

    Partner NGOs paste this into newsletters, email it to their board,
    or save to disk. Same data the dashboard renders, in a format that
    survives without the web UI. All PII-free by construction.
    """
    s = summary(scope=scope, days=days)
    needs = needs_by_region(scope=scope, days=days)
    confs = confidence_distribution(scope=scope, days=days)
    escs = escalation_reasons(scope=scope, days=days)

    out: list[str] = []
    out.append(f"# Pathways activity report")
    out.append("")
    out.append(f"**Partner:** {partner_name}")
    out.append(f"**Window:** last {days} day{'s' if days != 1 else ''}")
    out.append(f"**Scope:** "
               f"{', '.join(sorted((scope or {}).get('workforce_regions') or [])) or 'unscoped'}")
    out.append("")
    out.append("## Activity at a glance")
    out.append("")
    out.append(f"- Conversations: {s['distinct_threads']}")
    out.append(f"- Turns: {s['total_turns']}")
    out.append(f"- Escalations: {s['escalated']}")
    out.append(f"- Crisis flags: {s['crisis_fired']}")
    out.append(f"- Spanish share: {s['spanish_share'] * 100:.0f}%")
    out.append(f"- Average retrieval confidence: {s['avg_retrieval_confidence']:.2f}")
    out.append(f"- Resources surfaced: {s['matched_resources_total']}")
    out.append("")

    out.append("## Needs by region")
    out.append("")
    if needs:
        out.append("| Region | Need | Count |")
        out.append("|---|---|---:|")
        for row in needs[:30]:
            need = str(row['need']).replace('_', ' ')
            out.append(f"| {row['region']} | {need} | {row['count']} |")
    else:
        out.append("_No conversations in the window._")
    out.append("")

    out.append("## Retrieval confidence distribution")
    out.append("")
    if confs:
        out.append("| Bin | Count |")
        out.append("|---|---:|")
        for b in confs:
            out.append(f"| {b['bin_low']:.2f}-{b['bin_high']:.2f} | {b['count']} |")
        out.append("")
        out.append(
            "_Confidence floor is 0.62. Bars below that threshold trigger "
            "a human handoff instead of a citation._"
        )
    else:
        out.append("_No retrievals in the window._")
    out.append("")

    if escs:
        out.append("## Escalation reasons")
        out.append("")
        out.append("| Reason | Count |")
        out.append("|---|---:|")
        for row in escs[:20]:
            out.append(f"| `{row['reason']}` | {row['count']} |")
        out.append("")

    out.append("---")
    out.append(
        "_Generated by Pathways. All metrics are anonymized; the underlying "
        "events carry no phone numbers, names, ZIPs, or message bodies._"
    )
    return "\n".join(out)
