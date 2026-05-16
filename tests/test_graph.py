"""
End-to-end graph tests. Demo mode (no API key) — relies on the deterministic
template and rule-based audit fallbacks so tests are hermetic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _force_demo_mode(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def app():
    """Stateless compiled graph for Phase 0 single-shot tests.

    Phase 1 added a checkpointer requirement to the default-compiled graph.
    These tests assert end-to-end routing behavior on a single invocation
    and pre-set intake_complete=True so slot-filling is bypassed. They use
    use_checkpointer=False so they do not need a thread_id config.

    Multi-turn slot-filling behavior is covered by tests/test_phase1_intake.py
    which uses the full checkpointer-enabled graph.
    """
    from pathways.graph import build_graph
    return build_graph(use_checkpointer=False)


def _final(state_dict_or_obj):
    """Normalize the final state into a fully-serialized dict for assertions."""
    if hasattr(state_dict_or_obj, "model_dump"):
        return state_dict_or_obj.model_dump(mode="json")
    if isinstance(state_dict_or_obj, dict):
        # Each top-level value may still be a Pydantic model — coerce.
        out = {}
        for k, v in state_dict_or_obj.items():
            if hasattr(v, "model_dump"):
                out[k] = v.model_dump(mode="json")
            elif isinstance(v, list):
                out[k] = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in v
                ]
            else:
                out[k] = v
        return out
    return state_dict_or_obj


# ---------------------------------------------------------------------------
# Crisis short-circuit
# ---------------------------------------------------------------------------


def test_crisis_short_circuits_to_escalate(app):
    from pathways.state import CrisisCategory, CrisisSignal, PathwaysState

    state = PathwaysState(
        session_id="crisis-1",
        user_message="I want to end it",
        crisis=CrisisSignal(fired=True, category=CrisisCategory.SUICIDE),
    )
    result = _final(app.invoke(state))
    assert result["escalated_to_human"] is True
    assert "988" in result["final_response"]
    # Confirm we did NOT retrieve or match in crisis path
    assert result.get("retrievals", []) == []
    assert result.get("matched_resources", []) == []


# ---------------------------------------------------------------------------
# Happy paths through retrieve → match → draft → audit → send
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected_need,expected_citation_keyword",
    [
        (
            "I need housing in Houston after release",
            "housing",
            "HUD",
        ),
        (
            "Someone told me I can't get SNAP because of my drug felony",
            "benefits",
            "SNAP",
        ),
        (
            "Can I vote after I finished my probation",
            "legal_question",
            "Election",
        ),
        (
            "I want to expunge my old misdemeanor",
            "record_clearing",
            "Expunction",
        ),
        (
            "Looking for work in Dallas with a felony from 2018",
            "employment",
            "Occupations Code",
        ),
    ],
)
def test_routing_and_citation(app, message, expected_need, expected_citation_keyword):
    from pathways.state import CrisisSignal, IntakeStage, PathwaysState

    state = PathwaysState(
        session_id="route-test",
        user_message=message,
        crisis=CrisisSignal(fired=False),
        # Bypass Phase 1 slot-filling so this test asserts the routing+citation
        # path on a single invocation (which is what it was written to test).
        intake_complete=True,
        intake_stage=IntakeStage.DONE,
    )
    result = _final(app.invoke(state))
    assert result["intake"]["top_need"] == expected_need
    # At least one retrieval should fire
    assert len(result["retrievals"]) >= 1
    # The top result's citation should contain the expected keyword
    top_cites = [
        r["citation"]
        for retrieval in result["retrievals"]
        for r in (retrieval["results"] or [])[:2]
    ]
    assert any(expected_citation_keyword in c for c in top_cites), (
        f"Expected '{expected_citation_keyword}' in one of {top_cites}"
    )
    # Final response should not be empty
    assert result["final_response"]
    # Should not be escalated for these benign queries
    assert not result["escalated_to_human"]


# ---------------------------------------------------------------------------
# Audit verdict
# ---------------------------------------------------------------------------


def test_audit_blocks_non_texas_state(app):
    """If the draft references another state, the rule-based auditor hard-blocks."""
    # We can't easily force a non-TX draft from the template path, so test the
    # audit function directly instead.
    from pathways.nodes import audit
    from pathways.state import PathwaysState, Retrieval, CrisisSignal

    state = PathwaysState(
        session_id="audit-1",
        user_message="hi",
        crisis=CrisisSignal(fired=False),
        draft_response="In California, the rules are different.",
        retrievals=[],
    )
    result = audit.run(state)
    assert result["audit"].verdict.value == "hard_block"
    assert any(i.get("type") == "non_texas" for i in result["audit"].issues)


def test_audit_blocks_likelihood_promise(app):
    from pathways.nodes import audit
    from pathways.state import PathwaysState, CrisisSignal

    state = PathwaysState(
        session_id="audit-2",
        user_message="hi",
        crisis=CrisisSignal(fired=False),
        draft_response="Don't worry, you'll probably get your record sealed.",
        retrievals=[],
    )
    result = audit.run(state)
    # likelihood phrase → soft_block
    assert result["audit"].verdict.value in ("soft_block", "hard_block")


# ---------------------------------------------------------------------------
# Resource matching
# ---------------------------------------------------------------------------


def test_houston_user_gets_regional_resource(app):
    from pathways.state import CrisisSignal, IntakeStage, PathwaysState

    state = PathwaysState(
        session_id="match-1",
        user_message="I need a shelter in Houston tonight",
        crisis=CrisisSignal(fired=False),
        intake_complete=True,
        intake_stage=IntakeStage.DONE,
    )
    result = _final(app.invoke(state))
    assert len(result["matched_resources"]) >= 1
    names = " ".join(r["name"] for r in result["matched_resources"])
    # Either Salvation Army Greater Houston or 211 Texas should appear
    assert "Houston" in names or "211" in names
