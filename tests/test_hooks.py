"""
Tests for the deterministic safety hooks.

These hooks are the layer that doesn't depend on model judgment. They get
the strictest testing in the suite because their failure modes are the
hardest to detect at runtime.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_CRISIS = REPO_ROOT / ".claude" / "hooks" / "crisis_keyword_check.py"
HOOK_PII = REPO_ROOT / ".claude" / "hooks" / "pii_redact.py"
HOOK_RAG = REPO_ROOT / ".claude" / "hooks" / "rag_confidence_gate.py"


def _run_hook(hook_path: Path, payload: dict, env: dict | None = None) -> dict:
    """Run a hook subprocess with given JSON payload, parse JSON stdout."""
    proc = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, **(env or {})},
    )
    if not proc.stdout.strip():
        return {}
    try:
        return json.loads(proc.stdout.strip().split("\n")[-1])
    except json.JSONDecodeError as e:
        pytest.fail(
            f"Hook returned non-JSON output.\nstdout: {proc.stdout!r}\n"
            f"stderr: {proc.stderr!r}\nerror: {e}"
        )
        return {}  # unreachable


# ---------------------------------------------------------------------------
# crisis_keyword_check
# ---------------------------------------------------------------------------


class TestCrisisKeywordCheck:
    def test_suicide_keyword_fires(self):
        out = _run_hook(HOOK_CRISIS, {"prompt": "I want to kill myself"})
        assert out.get("continue") is True
        assert "systemMessage" in out
        assert out["hookMetadata"]["category"] == "suicide"

    def test_overdose_keyword_fires(self):
        out = _run_hook(HOOK_CRISIS, {"prompt": "I overdosed last night"})
        assert out.get("continue") is True
        assert out["hookMetadata"]["category"] == "substance"

    def test_domestic_violence_fires(self):
        out = _run_hook(
            HOOK_CRISIS, {"prompt": "he's hitting me right now please help"}
        )
        assert out.get("continue") is True
        assert out["hookMetadata"]["category"] == "domestic_violence"

    def test_housing_emergency_fires(self):
        out = _run_hook(
            HOOK_CRISIS, {"prompt": "I have nowhere safe to go tonight"}
        )
        assert out.get("continue") is True
        assert out["hookMetadata"]["category"] == "housing_emergency"

    def test_false_positive_celebration(self):
        """'I killed it on that interview' is not crisis."""
        out = _run_hook(
            HOOK_CRISIS, {"prompt": "I killed it on that job interview today"}
        )
        # No match → empty output (silent pass)
        assert out == {}

    def test_false_positive_venting(self):
        out = _run_hook(
            HOOK_CRISIS, {"prompt": "this rental application process is killing me lol"}
        )
        assert out == {}

    def test_normal_request_no_fire(self):
        out = _run_hook(
            HOOK_CRISIS,
            {"prompt": "Hi, can you help me find housing in Houston?"},
        )
        assert out == {}

    def test_empty_prompt(self):
        out = _run_hook(HOOK_CRISIS, {"prompt": ""})
        assert out == {}

    def test_malformed_input_does_not_block(self):
        # We pass a string that's not valid JSON; hook should exit cleanly
        # without writing a continue=false response.
        proc = subprocess.run(
            [sys.executable, str(HOOK_CRISIS)],
            input="not json at all",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        # No JSON written → don't block
        assert not proc.stdout.strip()


# ---------------------------------------------------------------------------
# pii_redact
# ---------------------------------------------------------------------------


class TestPIIRedact:
    def test_ssn_redacted(self):
        out = _run_hook(
            HOOK_PII,
            {"tool_input": {"content": "My SSN is 123-45-6789"}},
        )
        assert out["continue"] is True
        assert "123-45-6789" not in json.dumps(out["tool_input"])
        assert "[SSN_REDACTED]" in json.dumps(out["tool_input"])
        assert "ssn" in out["hookMetadata"]["redactions"]

    def test_phone_redacted(self):
        out = _run_hook(
            HOOK_PII,
            {"tool_input": {"note": "call me at 713-555-0123"}},
        )
        assert "713-555-0123" not in json.dumps(out["tool_input"])
        assert "phone" in out["hookMetadata"]["redactions"]

    def test_crisis_hotlines_preserved(self):
        """211, 988, and named hotline numbers must NOT be redacted."""
        out = _run_hook(
            HOOK_PII,
            {"tool_input": {"note": "Call 988 or 211 or 1-800-799-7233"}},
        )
        # Either:
        # (a) no redactions, so hook returned just {"continue": true} without
        #     a rewritten tool_input, OR
        # (b) hook rewrote tool_input but preserved the hotline numbers.
        assert out.get("continue") is True
        if "tool_input" in out:
            text = json.dumps(out["tool_input"])
            assert "988" in text
            assert "211" in text
            assert "800-799-7233" in text
        # If no tool_input in output, the hook left input untouched — which is
        # what we want for allowlisted hotlines.

    def test_email_redacted(self):
        out = _run_hook(
            HOOK_PII,
            {"tool_input": {"note": "Reach me at user@example.com please"}},
        )
        text = json.dumps(out["tool_input"])
        assert "user@example.com" not in text
        assert "[EMAIL_REDACTED]" in text

    def test_tdcj_id_redacted(self):
        out = _run_hook(
            HOOK_PII,
            {"tool_input": {"note": "TDCJ 1234567 was released yesterday"}},
        )
        text = json.dumps(out["tool_input"])
        assert "TDCJ 1234567" not in text
        assert "[TDCJ_ID_REDACTED]" in text

    def test_dob_iso_redacted(self):
        out = _run_hook(
            HOOK_PII,
            {"tool_input": {"note": "DOB 1982-04-15"}},
        )
        assert "1982-04-15" not in json.dumps(out["tool_input"])

    def test_clean_input_passes_through(self):
        out = _run_hook(
            HOOK_PII,
            {"tool_input": {"note": "Find me housing in Houston please"}},
        )
        assert out["continue"] is True
        # No redactions → tool_input not rewritten
        assert "tool_input" not in out or out.get("tool_input", {}).get(
            "note"
        ) == "Find me housing in Houston please"

    def test_nested_structure_redacted(self):
        out = _run_hook(
            HOOK_PII,
            {
                "tool_input": {
                    "records": [
                        {"ssn": "987-65-4321", "name": "Jane Doe"},
                        {"phone": "832-555-0100"},
                    ]
                }
            },
        )
        text = json.dumps(out["tool_input"])
        assert "987-65-4321" not in text
        assert "832-555-0100" not in text


# ---------------------------------------------------------------------------
# rag_confidence_gate
# ---------------------------------------------------------------------------


class TestRAGConfidenceGate:
    def test_high_confidence_passes(self):
        payload = {
            "tool_name": "mcp__pathways-corpus__search_corpus",
            "tool_result": {
                "confidence": 0.92,
                "results": [{"citation": "Tex. Code"}],
            },
        }
        out = _run_hook(HOOK_RAG, payload)
        assert out.get("continue") is True
        assert out["hookMetadata"]["action"] == "pass"
        assert "tool_result" not in out  # no rewrite

    def test_low_confidence_rewritten(self):
        payload = {
            "tool_name": "mcp__pathways-corpus__search_corpus",
            "tool_result": {"confidence": 0.31, "results": [{"citation": "weak"}]},
        }
        out = _run_hook(HOOK_RAG, payload)
        assert out.get("continue") is True
        assert out["hookMetadata"]["action"] == "gated"
        rewritten = out["tool_result"]
        assert rewritten["gated"] is True
        assert rewritten["reason"] == "low_confidence"
        assert rewritten["results"] == []
        # Original preserved for auditor
        assert rewritten["_original_low_confidence"]["confidence"] == 0.31

    def test_no_confidence_field_passes(self):
        payload = {
            "tool_name": "mcp__tx-resources__find_resources",
            "tool_result": {"results": [{"id": "211-texas"}]},
        }
        out = _run_hook(HOOK_RAG, payload)
        # No confidence to gate on → silent pass
        assert out == {}

    def test_custom_floor_via_env(self):
        payload = {
            "tool_name": "mcp__pathways-corpus__search_corpus",
            "tool_result": {"confidence": 0.55, "results": [{}]},
        }
        # Floor at 0.7 → 0.55 is gated
        out = _run_hook(HOOK_RAG, payload, env={"PATHWAYS_CONFIDENCE_FLOOR": "0.7"})
        assert out["hookMetadata"]["action"] == "gated"
        # Floor at 0.5 → 0.55 passes
        out = _run_hook(HOOK_RAG, payload, env={"PATHWAYS_CONFIDENCE_FLOOR": "0.5"})
        assert out["hookMetadata"]["action"] == "pass"
