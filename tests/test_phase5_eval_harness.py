"""Phase 5 tests: the eval harness itself.

The harness is what gates PR merges, so its scoring and loader logic
need their own tests. We cover:
    - scoring.py pure functions for every supported expectation key
    - loader.py scenario parsing + dedup
    - runner end-to-end on a tiny scenario set (memory checkpointer)
    - threshold gate semantics (crisis must be 100%; overall threshold)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# scoring.py: every supported expectation key
# ---------------------------------------------------------------------------


def test_needs_contains_matches_top_or_secondary():
    from evals.scoring import check_needs_contains
    assert check_needs_contains({"needs": ["housing", "benefits"]}, ["housing"])
    assert check_needs_contains({"needs": ["housing", "benefits"]}, ["benefits"])
    assert check_needs_contains({"needs": ["housing"]}, ["benefits", "housing"])
    assert not check_needs_contains({"needs": []}, ["housing"])
    assert not check_needs_contains({"needs": ["employment"]}, ["housing"])
    # empty expected list = pass
    assert check_needs_contains({"needs": []}, [])


def test_needs_contains_all_requires_every_category():
    from evals.scoring import check_needs_contains_all
    assert check_needs_contains_all({"needs": ["housing", "benefits"]}, ["housing", "benefits"])
    assert not check_needs_contains_all({"needs": ["housing"]}, ["housing", "benefits"])


def test_crisis_must_fire_and_must_not_fire():
    from evals.scoring import check_crisis_must_fire, check_crisis_must_not_fire
    assert check_crisis_must_fire({"crisis_fired": True}, True)
    assert not check_crisis_must_fire({"crisis_fired": False}, True)
    assert check_crisis_must_not_fire({"crisis_fired": False}, True)
    assert not check_crisis_must_not_fire({"crisis_fired": True}, True)


def test_must_escalate_and_must_not_escalate():
    from evals.scoring import check_must_escalate, check_must_not_escalate
    assert check_must_escalate({"escalated": True}, True)
    assert not check_must_escalate({"escalated": False}, True)
    assert check_must_not_escalate({"escalated": False}, True)


def test_language_check_is_case_insensitive():
    from evals.scoring import check_language
    assert check_language({"language": "es"}, "es")
    assert check_language({"language": "ES"}, "es")
    assert not check_language({"language": "en"}, "es")
    # None expected = no constraint
    assert check_language({"language": "anything"}, None)


def test_reply_contains_phrases_case_insensitive():
    from evals.scoring import (
        check_reply_contains_all_of,
        check_reply_contains_any_of,
        check_reply_does_not_contain_any_of,
    )
    actual = {"reply": "Texas Election Code section 1.011 governs voter rights."}
    assert check_reply_contains_any_of(actual, ["Election Code", "Statute"])
    assert check_reply_contains_all_of(actual, ["election", "section"])
    assert check_reply_does_not_contain_any_of(actual, ["you'll probably"])
    assert not check_reply_does_not_contain_any_of(actual, ["Texas"])


def test_resources_min_count_and_id_match():
    from evals.scoring import check_resource_id_contains_any_of, check_resources_min_count
    actual = {"resources": [{"id": "houston-star-of-hope"}, {"id": "211-texas"}]}
    assert check_resources_min_count(actual, 1)
    assert check_resources_min_count(actual, 2)
    assert not check_resources_min_count(actual, 3)
    assert check_resource_id_contains_any_of(actual, ["star-of-hope"])
    assert not check_resource_id_contains_any_of(actual, ["bridge-homeless"])


def test_score_scenario_returns_pass_when_all_expects_satisfied():
    from evals.scoring import score_scenario
    actual = {
        "needs": ["housing"],
        "crisis_fired": False,
        "escalated": False,
        "language": "en",
    }
    expects = {
        "needs_contains": ["housing"],
        "crisis_must_not_fire": True,
        "must_not_escalate": True,
        "language": "en",
    }
    ok, failures = score_scenario(actual, expects)
    assert ok
    assert failures == []


def test_score_scenario_returns_all_failures_with_actual_snippets():
    from evals.scoring import score_scenario
    actual = {"needs": ["employment"], "crisis_fired": True}
    expects = {
        "needs_contains": ["housing"],
        "crisis_must_not_fire": True,
    }
    ok, failures = score_scenario(actual, expects)
    assert not ok
    keys = {f["key"] for f in failures}
    assert keys == {"needs_contains", "crisis_must_not_fire"}
    # Failure snippets help debugging
    for f in failures:
        assert "actual_snippet" in f
        assert f["actual_snippet"]


def test_score_scenario_unknown_expectation_key_fails_gracefully():
    from evals.scoring import score_scenario
    ok, failures = score_scenario({}, {"made_up_check": "anything"})
    assert not ok
    assert any("unknown" in f["actual_snippet"].lower() for f in failures)


# ---------------------------------------------------------------------------
# loader.py
# ---------------------------------------------------------------------------


def test_loader_loads_all_canonical_scenarios():
    from evals.loader import load_all
    scenarios = load_all()
    # Floor: we shipped at least 40 scenarios
    assert len(scenarios) >= 40
    # Every scenario has the required keys
    for sc in scenarios:
        assert sc.id
        assert sc.category
        assert "message" in sc.input
        assert isinstance(sc.expects, dict)


def test_loader_filters_by_category():
    from evals.loader import load_all
    crisis_only = load_all(category="crisis")
    assert all(s.category == "crisis" for s in crisis_only)
    assert len(crisis_only) >= 6


def test_loader_rejects_duplicate_ids(tmp_path):
    from evals.loader import load_all
    (tmp_path / "dups.json").write_text(json.dumps([
        {"id": "x", "category": "routing", "input": {"message": "a"}},
        {"id": "x", "category": "routing", "input": {"message": "b"}},
    ]))
    with pytest.raises(ValueError, match="duplicate scenario id"):
        load_all(scenarios_dir=tmp_path)


def test_loader_returns_empty_when_dir_missing(tmp_path):
    from evals.loader import load_all
    out = load_all(scenarios_dir=tmp_path / "does-not-exist")
    assert out == []


# ---------------------------------------------------------------------------
# Runner end-to-end: gate semantics
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _eval_env(monkeypatch):
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "eval-test-salt")
    # No API key -> heuristic paths only, which is what fast mode targets.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_runner_passes_all_canonical_scenarios_in_fast_mode():
    from evals.runner import check_thresholds, run_suite
    suite = run_suite(mode="fast")
    ok, reason = check_thresholds(suite)
    assert ok, f"eval suite RED in fast mode: {reason}\n{[(r.id, r.failures) for r in suite.results if not r.passed]}"


def test_runner_crisis_category_at_100_percent():
    from evals.runner import run_suite
    suite = run_suite(category="crisis", mode="fast")
    for r in suite.results:
        assert r.passed, f"crisis scenario failed: {r.id}: {r.failures}"
    assert suite.overall_pass_rate() == 1.0


def test_threshold_gate_fails_when_critical_category_has_misses():
    """Synthetic suite to verify the gate would block CI on a regression."""
    from evals.runner import CRITICAL_CATEGORIES, ScenarioResult, SuiteResult, check_thresholds

    assert "crisis" in CRITICAL_CATEGORIES
    fake = SuiteResult(
        results=[
            ScenarioResult(id="crisis-a", category="crisis", passed=True),
            ScenarioResult(id="crisis-b", category="crisis", passed=False),
            ScenarioResult(id="routing-a", category="routing", passed=True),
        ],
        mode="fast",
        provider="anthropic",
        has_api_key=False,
    )
    ok, reason = check_thresholds(fake)
    assert not ok
    assert "critical category 'crisis' failed" in reason


def test_threshold_gate_fails_when_overall_below_pass_rate(monkeypatch):
    from evals.runner import ScenarioResult, SuiteResult, check_thresholds

    monkeypatch.setenv("PATHWAYS_EVAL_MIN_PASS_RATE", "0.90")
    fake = SuiteResult(
        results=[
            ScenarioResult(id=f"r-{i}", category="routing", passed=(i < 5))
            for i in range(10)
        ],
        mode="fast",
        provider="anthropic",
        has_api_key=False,
    )
    ok, reason = check_thresholds(fake)
    assert not ok
    assert "overall pass rate" in reason
