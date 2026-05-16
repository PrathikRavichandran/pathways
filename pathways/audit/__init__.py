"""Operator-side audit log.

A queryable, full-content record of every turn. Distinct from the
caseworker-dashboard analytics (which is PII-scrubbed and partner-
facing): this is for YOU as the operator, gated behind the same
admin token as the daily cron.

What it captures, per turn:
    timestamp, thread_id, channel
    user_message (full text)
    reply (full text)
    needs detected (list)
    retrievals (full list of {query, confidence, top results})
    matched resources (id + name)
    audit verdict (pass/soft_block/hard_block/None)
    escalation reason (if any)
    crisis_fired (bool)
    intake snapshot (language, supervision_status, region, ZIP, etc)

Storage backends mirror the rest of the codebase:
    memory   - in-process list. Tests + demo + key-missing fallback.
    postgres - audit_log table with the whole payload Fernet-encrypted
               as a single BYTEA blob. Indexed by (thread_id, ts).

Required env for production:
    DATABASE_URL                       # postgres connection
    PATHWAYS_AUDIT_ENCRYPTION_KEY      # base64 32-byte Fernet key
                                        (separate from the phone map
                                        key so audit access can be
                                        revoked without breaking
                                        outbound)

Read access: GET /admin/audit-log (Bearer auth via PATHWAYS_ADMIN_TOKEN).
"""

from pathways.audit.service import event_from_state, record_turn
from pathways.audit.store import (
    AuditEvent,
    get_store,
    reset_store,
)

__all__ = [
    "AuditEvent",
    "event_from_state",
    "get_store",
    "record_turn",
    "reset_store",
]
