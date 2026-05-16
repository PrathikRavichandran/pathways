"""Twilio request signature verification.

Twilio signs every webhook with an HMAC-SHA1 of the full URL + form-encoded
parameters, using the account's auth token as the key. Verifying this
header is the first line of defense against forged webhooks (an attacker
who can reach the webhook URL but does not know the auth token cannot
craft a valid signature).

In demo mode (PATHWAYS_SKIP_TWILIO_SIG=1) verification is skipped so the
/_debug/invoke flow and local tests do not need to compute signatures.
Skipping is loud: a stderr log line fires every time so it's never silent
in production.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping, Optional

try:
    from twilio.request_validator import RequestValidator
except Exception:  # pragma: no cover - twilio is in requirements
    RequestValidator = None  # type: ignore[assignment]


def signature_skipped() -> bool:
    """True if signature verification is disabled by env."""
    return os.environ.get("PATHWAYS_SKIP_TWILIO_SIG", "").strip() in (
        "1", "true", "yes", "on",
    )


def verify_twilio_signature(
    full_url: str,
    form_params: Mapping[str, str],
    signature_header: Optional[str],
    auth_token: Optional[str] = None,
) -> bool:
    """Return True if the request signature is valid.

    Args:
        full_url: The exact URL Twilio called, including query string,
                  using the public scheme + host (NOT the internal Docker
                  host). Twilio signs against the URL the client used.
                  Set PATHWAYS_PUBLIC_BASE_URL so the FastAPI ingress
                  reconstructs this correctly behind the HF Spaces proxy.
        form_params: The exact form fields Twilio sent.
        signature_header: The value of X-Twilio-Signature header.
        auth_token: Override; otherwise read from TWILIO_AUTH_TOKEN env.

    Returns False if no signature header, no auth token, or the validator
    rejects the request. Logs the failure category to stderr so operators
    can distinguish missing-config from active-attack patterns.
    """
    if signature_skipped():
        sys.stderr.write(
            "twilio_signature: SKIPPED (PATHWAYS_SKIP_TWILIO_SIG is set). "
            "Do NOT run with this flag in production.\n"
        )
        return True

    token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not token:
        sys.stderr.write(
            "twilio_signature: TWILIO_AUTH_TOKEN is unset; cannot verify.\n"
        )
        return False

    if not signature_header:
        sys.stderr.write(
            "twilio_signature: X-Twilio-Signature header missing.\n"
        )
        return False

    if RequestValidator is None:
        sys.stderr.write(
            "twilio_signature: twilio package not installed; cannot verify.\n"
        )
        return False

    validator = RequestValidator(token)
    ok = validator.validate(full_url, dict(form_params), signature_header)
    if not ok:
        sys.stderr.write(
            f"twilio_signature: validation FAILED for url={full_url!r}. "
            "If you're testing manually, set PATHWAYS_SKIP_TWILIO_SIG=1.\n"
        )
    return ok
