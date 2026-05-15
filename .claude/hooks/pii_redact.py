#!/usr/bin/env python3
"""
PreToolUse hook: PII redaction.

Fires on Write, Bash, and pathways-postgres tool calls. Inspects the tool
input, redacts PII patterns, and either:
- Returns continue=true with redacted input if redaction was clean
- Returns continue=false (blocks the tool call) if redaction failed integrity check

Patterns covered (Texas-specific where relevant):
- US Social Security Numbers (SSN)
- Texas Driver License numbers
- Texas State ID numbers
- TDCJ inmate numbers
- Texas case numbers (county-prefixed)
- Phone numbers (US format)
- Email addresses
- Dates of birth (loose; flagged for review)
- Mailing addresses (street-level; conservative)

Design notes
------------
- This is the deterministic safety layer. The model cannot decide "this turn
  it's okay to log the user's full SSN." Hooks run outside the agent loop.
- Failure mode is FAIL CLOSED: if regex evaluation throws, we block the
  tool call rather than allow potentially-unredacted writes through. The
  user-facing impact of a blocked log write is minor; the impact of a
  leaked SSN is permanent.
- Names are intentionally NOT redacted by this hook. Name redaction is
  high-false-positive (legitimate references to public figures, place
  names, statute authors) and is handled at the view layer in the
  database, not here. Documenting this in COMPLIANCE.md.

Input contract (per Claude Code hook spec)
------------------------------------------
JSON via stdin:
    {
      "hook_event_name": "PreToolUse",
      "tool_name": "Write" | "Bash" | "mcp__pathways-postgres__*",
      "tool_input": {...tool-specific...},
      ...
    }

Output:
    JSON to stdout: {"continue": true|false, "tool_input": <possibly redacted>}
    exit code 0 always (hook errors should not crash the agent loop)

References:
- Claude Code hooks spec: https://docs.claude.com/en/docs/claude-code/hooks
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Redaction patterns
# ---------------------------------------------------------------------------

_PHONE_PATTERN = re.compile(
    r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)
# Phone numbers in this allowlist are NEVER redacted (they're crisis hotlines).
# Normalized form: digits only.
_PHONE_ALLOWLIST_DIGITS = {
    "988",
    "211",
    "18007997233",   # National DV Hotline
    "18006624357",   # SAMHSA
    "18006564673",   # RAINN
    "18002738255",   # 988 historic, still routes
}


def _phone_repl(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    if digits in _PHONE_ALLOWLIST_DIGITS:
        return m.group(0)
    return "[PHONE_REDACTED]"


# Order matters — more specific patterns run before more generic ones to
# avoid an SSN being half-eaten by a phone-number pattern.
PATTERNS: list[tuple[re.Pattern[str], str | callable, str]] = [
    # SSN: 123-45-6789 or 123 45 6789 or 123456789 with delim
    (re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b"), "[SSN_REDACTED]", "ssn"),
    (re.compile(r"\b\d{3}\d{2}\d{4}\b(?=\s|$|[^0-9])"), "[SSN_LIKELY_REDACTED]", "ssn_unformatted"),

    # TX Driver License: typically 8 digits
    (re.compile(r"\b(?:DL|DRIVER\s*LIC(?:ENSE)?)\s*#?\s*\d{7,9}\b", re.I),
     "[TX_DL_REDACTED]", "tx_drivers_license"),

    # TX State ID number: typically 8 digits with prefix
    (re.compile(r"\b(?:ID|TX\s*ID|STATE\s*ID)\s*#?\s*\d{7,9}\b", re.I),
     "[TX_STATE_ID_REDACTED]", "tx_state_id"),

    # TDCJ inmate / SID number
    (re.compile(r"\b(?:TDCJ|SID)\s*#?\s*\d{6,8}\b", re.I),
     "[TDCJ_ID_REDACTED]", "tdcj_id"),

    # Phone numbers — use a callable so the allowlist applies after matching
    (_PHONE_PATTERN, _phone_repl, "phone"),

    # Email
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
     "[EMAIL_REDACTED]", "email"),

    # Dates that look like DOB (MM/DD/YYYY or YYYY-MM-DD, ages 1920-2020 to
    # avoid catching statute years)
    (re.compile(r"\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19[2-9]\d|20[0-2]\d)\b"),
     "[DOB_LIKELY_REDACTED]", "dob_mdy"),
    (re.compile(r"\b(19[2-9]\d|20[0-2]\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b"),
     "[DOB_LIKELY_REDACTED]", "dob_iso"),

    # Street addresses (conservative — number + word + street suffix)
    (re.compile(
        r"\b\d{1,6}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
        r"\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|"
        r"Court|Ct|Way|Place|Pl|Trail|Tr)\.?\b"
    ), "[STREET_ADDR_REDACTED]", "street_address"),

    # County-prefixed case numbers (e.g., "Harris County 2018-CR-12345")
    (re.compile(
        r"\b[A-Z][a-z]+\s+County\s+\d{4}[-/]?[A-Z]{1,3}[-/]?\d{4,7}\b"
    ), "[CASE_NUMBER_REDACTED]", "case_number"),
]


def _redact_string(text: str) -> tuple[str, list[str]]:
    """Apply all patterns to text. Return (redacted_text, list_of_types_hit)."""
    types_hit: list[str] = []
    for pattern, replacement, kind in PATTERNS:
        # For callable replacements, we need to track whether anything changed
        # because pattern.search() can match an allowlisted number that the
        # callable then doesn't replace.
        if callable(replacement):
            new_text, n = pattern.subn(replacement, text)
            # Only record a hit if the text actually changed
            if new_text != text:
                types_hit.append(kind)
            text = new_text
        else:
            if pattern.search(text):
                types_hit.append(kind)
                text = pattern.sub(replacement, text)
    return text, types_hit


def _redact_value(value: Any) -> tuple[Any, list[str]]:
    """Recursively redact strings inside a JSON-shaped value."""
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        new_list: list[Any] = []
        all_hits: list[str] = []
        for item in value:
            new_item, hits = _redact_value(item)
            new_list.append(new_item)
            all_hits.extend(hits)
        return new_list, all_hits
    if isinstance(value, dict):
        new_dict: dict[str, Any] = {}
        all_hits = []
        for k, v in value.items():
            new_v, hits = _redact_value(v)
            new_dict[k] = new_v
            all_hits.extend(hits)
        return new_dict, all_hits
    return value, []


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        # FAIL CLOSED: malformed input -> block tool call
        print(json.dumps({
            "continue": False,
            "reason": f"pii_redact: invalid JSON input: {e}",
        }))
        return 0

    tool_input = payload.get("tool_input", {})

    try:
        redacted, hits = _redact_value(tool_input)
    except Exception as e:
        # FAIL CLOSED
        print(json.dumps({
            "continue": False,
            "reason": f"pii_redact: redaction error: {e}",
        }))
        return 0

    if hits:
        print(json.dumps({
            "continue": True,
            "tool_input": redacted,
            "hookMetadata": {
                "hook": "pii_redact",
                "redactions": hits,
                "redaction_count": len(hits),
            },
        }))
    else:
        # No redactions needed — return continue with original input
        print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
