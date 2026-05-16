"""Audit event construction + write entry point.

Mirror of dashboard/analytics.py's event_from_state, but captures the
full content (user message, reply, retrieval payload, audit issues)
because this log is operator-side, not partner-facing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pathways.audit.store import AuditEvent, get_store

logger = logging.getLogger("pathways.audit")


def event_from_state(
    final_state: Any,
    thread_id: str,
    channel: str,
    user_message: str,
    reply: str,
    crisis_fired: bool,
    crisis_category: Optional[str] = None,
) -> AuditEvent:
    """Build an AuditEvent from the LangGraph final state. Tolerates
    partial state (graph may have escalated before some fields filled)."""

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

    # Geo enrichment from ZIP (same path as dashboard analytics)
    county = None
    workforce_region = None
    try:
        from pathways.geo import county_for_zip, workforce_region_for_zip
        z = intake.get("zipcode")
        if z:
            county = county_for_zip(z)
            workforce_region = workforce_region_for_zip(z)
    except Exception:
        pass

    # Retrievals: capture the full payload (query, confidence, top results)
    retrievals_dump: list[dict] = []
    for r in _get(final_state, "retrievals") or []:
        if hasattr(r, "model_dump"):
            r = r.model_dump(mode="json")
        if isinstance(r, dict):
            retrievals_dump.append(r)

    # Matched resources: keep the id + name + category (full record could
    # be large; trim to the partner-facing card shape)
    matched_dump: list[dict] = []
    for m in _get(final_state, "matched_resources") or []:
        if isinstance(m, dict):
            matched_dump.append({
                "id": m.get("id"),
                "name": m.get("name"),
                "category": m.get("category"),
                "phone": m.get("phone"),
                "distance_miles": m.get("distance_miles"),
            })

    audit = _get(final_state, "audit")
    if hasattr(audit, "model_dump"):
        audit = audit.model_dump(mode="json")
    audit_verdict = audit.get("verdict") if isinstance(audit, dict) else None
    audit_issues = (
        list(audit.get("issues") or []) if isinstance(audit, dict) else []
    )

    return AuditEvent(
        thread_id=thread_id,
        channel=channel,
        user_message=user_message or "",
        reply=reply or "",
        needs=needs,
        language=intake.get("language") or "en",
        region=intake.get("region"),
        county=county,
        workforce_region=workforce_region,
        zipcode=intake.get("zipcode"),
        supervision_status=intake.get("supervision_status"),
        intake_complete=bool(_get(final_state, "intake_complete")),
        intake_stage=str(_get(final_state, "intake_stage") or "") or None,
        retrievals=retrievals_dump,
        matched_resources=matched_dump,
        audit_verdict=audit_verdict,
        audit_issues=audit_issues,
        escalated=bool(_get(final_state, "escalation_reason")),
        escalation_reason=_get(final_state, "escalation_reason"),
        crisis_fired=bool(crisis_fired),
        crisis_category=crisis_category,
    )


def record_turn(event: AuditEvent) -> None:
    """Append the event to the configured store. Never raises:
    audit-log failures must not crash the API path."""
    try:
        get_store().append(event)
    except Exception:
        logger.exception("audit.record_turn failed (non-fatal)")
