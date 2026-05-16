"""Caseworker dashboard.

A read-only FastAPI sub-app mounted at /dashboard. Per-partner
bearer-token auth. Aggregated visibility into needs, retrieval
confidence, escalations, and anonymized recent conversations.

All PII is scrubbed at the write layer (conversation_events never
stores phone numbers, names, raw user text, or message bodies). The
dashboard cannot leak PII because it doesn't have any to leak.
"""
