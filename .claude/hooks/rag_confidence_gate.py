#!/usr/bin/env python3
"""
PostToolUse hook: RAG confidence gate.

Fires AFTER a retrieval tool returns. If the retrieval reports a confidence
score below PATHWAYS_CONFIDENCE_FLOOR (default 0.62), this hook rewrites
the tool result so that the model cannot draft a confident-sounding answer
on top of weak retrieval. Instead it sees a structured "low-confidence —
hand off" payload that the niccc-lookup Skill is trained to handle.

Design notes
------------
- This is the second deterministic safety layer (the first being
  crisis_keyword_check on UserPromptSubmit). It exists because a model that
  has any retrieval evidence will tend to use it confidently — even when
  the evidence is weak. A floor enforced outside the model loop is the
  cheapest insurance against a hallucinated legal citation.
- Floor is per-deployment configurable via PATHWAYS_CONFIDENCE_FLOOR env
  var. settings.json sets it to 0.62 by default; production may tune it
  against eval results.
- This hook only acts on tools listed in the settings.json matcher; it
  does not gate every tool result.
- The replacement payload preserves the original under
  `_original_low_confidence` so the compliance-auditor can audit what the
  retriever saw and confirm the gate fired correctly.

Input contract (per Claude Code hook spec)
------------------------------------------
JSON via stdin:
    {
      "hook_event_name": "PostToolUse",
      "tool_name": "mcp__pathways-corpus__search_corpus" | "mcp__tx-resources__find_resources" | ...,
      "tool_input": {...},
      "tool_result": {...},   # what the MCP server returned
      ...
    }

Output:
    JSON to stdout (always continue=true; we don't block):
        {"continue": true, "tool_result": <possibly rewritten>}
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

DEFAULT_FLOOR = 0.62


def _get_floor() -> float:
    raw = os.environ.get("PATHWAYS_CONFIDENCE_FLOOR")
    if not raw:
        return DEFAULT_FLOOR
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_FLOOR


def _extract_confidence(tool_result: Any) -> float | None:
    """Pull the 'confidence' field from a tool result if present.

    The pathways-corpus search_corpus tool returns this directly.
    Other retrieval tools may or may not — when absent, we don't gate.
    """
    if not isinstance(tool_result, dict):
        return None
    if "confidence" in tool_result:
        try:
            return float(tool_result["confidence"])
        except (TypeError, ValueError):
            return None
    # Some tool result envelopes nest the payload — check one level.
    for key in ("result", "data", "payload"):
        nested = tool_result.get(key)
        if isinstance(nested, dict) and "confidence" in nested:
            try:
                return float(nested["confidence"])
            except (TypeError, ValueError):
                return None
    return None


def _build_low_confidence_payload(
    original: Any,
    confidence: float,
    floor: float,
) -> dict[str, Any]:
    """Replace the tool_result with a structured handoff instruction."""
    return {
        "gated": True,
        "reason": "low_confidence",
        "confidence": confidence,
        "floor": floor,
        "instruction": (
            "Retrieval confidence was below the configured floor. Do not "
            "assert factual claims based on this retrieval. Acknowledge to "
            "the user that you are not certain, and route to a human "
            "navigator or legal aid resource. Use the handoff phrasing "
            "from the niccc-lookup skill: 'I'm not certain about that. "
            "I don't want to give you wrong information on something this "
            "important. Let me connect you with [navigator/legal aid] who "
            "can help.' Then call tx-resources.find_resources to surface "
            "the right legal aid or 211 referral."
        ),
        "results": [],
        "_original_low_confidence": original,
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"rag_confidence_gate: invalid JSON: {e}", file=sys.stderr)
        # On hook errors, do not block the turn. Pass through.
        return 0

    tool_result = payload.get("tool_result")
    confidence = _extract_confidence(tool_result)
    floor = _get_floor()

    if confidence is None:
        # No confidence field — nothing to gate. Pass through silently.
        return 0

    if confidence >= floor:
        # Sufficiently confident — pass through.
        print(json.dumps({
            "continue": True,
            "hookMetadata": {
                "hook": "rag_confidence_gate",
                "action": "pass",
                "confidence": confidence,
                "floor": floor,
            },
        }))
        return 0

    # Below floor — rewrite the result.
    rewritten = _build_low_confidence_payload(tool_result, confidence, floor)
    print(json.dumps({
        "continue": True,
        "tool_result": rewritten,
        "hookMetadata": {
            "hook": "rag_confidence_gate",
            "action": "gated",
            "confidence": confidence,
            "floor": floor,
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
