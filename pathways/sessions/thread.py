"""Thread ID derivation.

The thread_id is the durable identifier that ties multiple SMS turns from
the same phone number together. Crucial property: the raw phone number is
NEVER persisted as a primary key. We hash it with a per-deployment salt
so that a database leak does not expose phone numbers.

Why SHA-256 and not a UUID?
---------------------------
We need the SAME phone number to map to the SAME thread_id deterministically
across server restarts and across multiple webhook deliveries. A UUID per
phone would require a lookup table from phone to UUID, which would itself
need the phone in plaintext. The salted hash gives determinism without
storing the phone anywhere.

Why a per-deployment salt?
--------------------------
Rotating the salt is the project's nuclear option for anonymizing every
thread_id at once if a leak is ever suspected. It also prevents cross-
deployment correlation (test vs prod thread IDs do not match for the same
phone number).
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

DEFAULT_SALT_PLACEHOLDER = (
    "pathways-DEV-only-salt-set-PATHWAYS_THREAD_SALT-in-production"
)


def _get_salt() -> str:
    salt = os.environ.get("PATHWAYS_THREAD_SALT", "").strip()
    if not salt:
        return DEFAULT_SALT_PLACEHOLDER
    return salt


def _normalize_phone(from_number: str) -> str:
    """Strip whitespace and punctuation so '+1 713-555-0100' and
    '+17135550100' hash to the same thread."""
    return "".join(c for c in from_number if c.isalnum() or c == "+")


def thread_id_for_phone(from_number: str, salt: Optional[str] = None) -> str:
    """Return a stable, salted-SHA-256-derived thread_id for a phone number.

    Format: 'ph_' + first 32 hex chars of sha256(salt + normalized_phone).
    The 'ph_' prefix lets us distinguish phone-keyed threads from web-keyed
    threads (`web_` prefix) in logs and dashboard queries without revealing
    the source.
    """
    if not from_number or not from_number.strip():
        raise ValueError("from_number must be a non-empty string")
    salt = salt if salt is not None else _get_salt()
    normalized = _normalize_phone(from_number)
    digest = hashlib.sha256((salt + normalized).encode("utf-8")).hexdigest()
    return "ph_" + digest[:32]


def thread_id_for_web(session_uuid: str) -> str:
    """Stable thread_id for a browser session UUID (used by Phase 4 PWA)."""
    if not session_uuid or not session_uuid.strip():
        raise ValueError("session_uuid must be a non-empty string")
    return "web_" + session_uuid.strip()
