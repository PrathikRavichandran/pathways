"""Outbound Twilio SMS client.

The graph itself never calls Twilio; the FastAPI ingress does. This
module is the thin wrapper used by the ingress (and, in Phase 3, by the
feedback scheduler) to push messages outbound.

Trial-mode awareness
--------------------
A Twilio trial account can only send outbound SMS to numbers that have
been explicitly verified in the Twilio console. Sending to an unverified
number returns a 400. This client checks the TWILIO_TRIAL_VERIFIED_NUMBERS
env var (comma-separated E.164 list) and logs a warning + skips when the
destination is not in the list. This prevents the FastAPI handler from
500-ing in development the first time someone tries to test outbound.

Demo mode (no auth token) prints the message to stderr instead of calling
the API, so the rest of the pipeline still works in the cold-boot path.
"""

from __future__ import annotations

import os
import sys
from typing import Optional


def _trial_verified() -> set[str]:
    raw = os.environ.get("TWILIO_TRIAL_VERIFIED_NUMBERS", "").strip()
    if not raw:
        return set()
    return {n.strip() for n in raw.split(",") if n.strip()}


def _is_trial_account() -> bool:
    return os.environ.get("TWILIO_ACCOUNT_TYPE", "trial").strip().lower() == "trial"


def send_sms(to: str, body: str) -> dict:
    """Send an SMS to `to` with `body`. Returns a status dict.

    Status keys:
        sent: bool          - True if delivered to Twilio
        sid: Optional[str]  - Twilio MessageSid on success
        skipped_reason: Optional[str] - why send was suppressed (trial,
                              demo, opt-out, missing config)
        error: Optional[str] - Twilio error if delivery failed
    """
    if not to or not body:
        return {"sent": False, "sid": None, "skipped_reason": "missing to/body"}

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "").strip()

    if not (account_sid and auth_token and from_number):
        sys.stderr.write(
            f"twilio_client.send_sms: demo-mode (missing Twilio creds). "
            f"Would have sent to {to}: {body[:80]!r}...\n"
        )
        return {"sent": False, "sid": None, "skipped_reason": "demo_mode"}

    if _is_trial_account() and to not in _trial_verified():
        sys.stderr.write(
            f"twilio_client.send_sms: trial account; {to} not in "
            f"TWILIO_TRIAL_VERIFIED_NUMBERS. Skipping.\n"
        )
        return {"sent": False, "sid": None, "skipped_reason": "trial_unverified_to"}

    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        msg = client.messages.create(to=to, from_=from_number, body=body)
        return {"sent": True, "sid": msg.sid, "skipped_reason": None, "error": None}
    except Exception as exc:
        sys.stderr.write(f"twilio_client.send_sms: Twilio API error: {exc}\n")
        return {"sent": False, "sid": None, "skipped_reason": None, "error": str(exc)}
