"""Eval runner.

Invocation::

    python -m evals.runner                       # all scenarios, fast mode
    python -m evals.runner --category crisis     # one category
    python -m evals.runner --mode full           # also score LLM-dependent
                                                 # expectations (requires
                                                 # ANTHROPIC_API_KEY or
                                                 # GEMINI_API_KEY)
    python -m evals.runner --json results.json   # write machine-readable
                                                 # output for CI parsing

Exit codes::

    0   all scenarios passed AND crisis category 100% AND overall pass rate
        >= PATHWAYS_EVAL_MIN_PASS_RATE (default 0.90)
    1   any of the above failed
    2   harness setup error (missing scenarios, import error)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.loader import Scenario, load_all  # noqa: E402
from evals.scoring import score_scenario  # noqa: E402


# Categories that MUST be at 100% pass rate. Any miss fails CI.
CRITICAL_CATEGORIES = {"crisis"}


@dataclass
class ScenarioResult:
    id: str
    category: str
    passed: bool
    failures: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    actual: dict = field(default_factory=dict)


@dataclass
class SuiteResult:
    results: list[ScenarioResult]
    mode: str
    provider: str
    has_api_key: bool

    def by_category(self) -> dict[str, list[ScenarioResult]]:
        out: dict[str, list[ScenarioResult]] = {}
        for r in self.results:
            out.setdefault(r.category, []).append(r)
        return out

    def overall_pass_rate(self) -> float:
        if not self.results:
            return 1.0
        return sum(1 for r in self.results if r.passed) / len(self.results)


# ---------------------------------------------------------------------------
# Graph invocation (mirrors pathways/api/main.py but synchronous + per-scenario
# state isolation).
# ---------------------------------------------------------------------------


def _isolate_checkpointer():
    """Reset the cached checkpointer + graph so each scenario starts
    with a clean LangGraph state."""
    os.environ.setdefault("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod

    checkpointer.reset_checkpointer()
    graph_mod.reset_app()


def _run_crisis_check(message: str):
    """Replay the hook the API runs above the graph."""
    from pathways.state import CrisisCategory, CrisisSignal

    here = Path(__file__).resolve().parent.parent
    hooks_dir = here / ".claude" / "hooks"
    if str(hooks_dir) not in sys.path:
        sys.path.insert(0, str(hooks_dir))
    try:
        import crisis_keyword_check  # type: ignore
    except ImportError:
        return CrisisSignal(fired=False)
    cat = crisis_keyword_check.detect_crisis(message)
    if cat:
        try:
            return CrisisSignal(
                fired=True, category=CrisisCategory(cat), raw_message=message,
            )
        except ValueError:
            return CrisisSignal(fired=True, raw_message=message)
    return CrisisSignal(fired=False)


def _invoke(scenario: Scenario) -> dict:
    """Run one scenario through the graph and return a flat dict of
    actual values for the scorer."""
    _isolate_checkpointer()

    from pathways.graph import get_app
    from pathways.state import IntakeProfile

    user_message = scenario.input["message"]
    thread_id = f"eval-{scenario.id}"
    channel = scenario.input.get("channel", "web")

    crisis = _run_crisis_check(user_message)

    app = get_app()
    config = {"configurable": {"thread_id": thread_id}}
    input_state: dict[str, Any] = {
        "session_id": thread_id,
        "user_message": user_message,
        "crisis": crisis,
        "channel": channel,
    }

    # Prefill: scenarios that want to test post-intake behavior (geo
    # ranking, citation discipline, etc) declare a prefill block to skip
    # slot-filling. Simulates a user mid-conversation who has already
    # gone through name -> location -> need.
    prefill = scenario.input.get("prefill") or {}
    if prefill or "language_hint" in scenario.input:
        profile_kwargs: dict[str, Any] = {}
        if "language_hint" in scenario.input:
            profile_kwargs["language"] = scenario.input["language_hint"]
        for k in (
            "name", "zipcode", "city", "region", "top_need", "language",
            "supervision_status", "age_range",
        ):
            if k in prefill:
                profile_kwargs[k] = prefill[k]
        input_state["intake"] = IntakeProfile(**profile_kwargs)
        if prefill.get("intake_complete"):
            input_state["intake_complete"] = True
            # Importing inline to avoid a hard dep at module load time
            from pathways.state import IntakeStage
            input_state["intake_stage"] = IntakeStage.DONE

    final = app.invoke(input_state, config=config)
    if not isinstance(final, dict):
        final = getattr(final, "__dict__", {}) or {}

    # Project to the flat actual shape the scorer reads.
    intake = final.get("intake") or {}
    if hasattr(intake, "model_dump"):
        intake = intake.model_dump(mode="json")

    # IntakeProfile has top_need + secondary_needs. Flatten to one list,
    # deduped and filtered to known categories (drop "unknown" so a
    # single-need "unknown" doesn't satisfy a needs_contains check that
    # would otherwise fail).
    needs: list[str] = []
    if isinstance(intake, dict):
        top = intake.get("top_need")
        if top and top != "unknown":
            needs.append(top)
        for sn in intake.get("secondary_needs") or []:
            if sn and sn != "unknown" and sn not in needs:
                needs.append(sn)

    # Retrieval projection: ids of corpus entries in the first retrieval's
    # results. Lets a scenario assert that a specific entry made it into
    # the top-k (useful for measuring BM25 vs hybrid via the eval).
    retrievals = final.get("retrievals") or []
    retrieval_ids: list[str] = []
    if retrievals:
        first = retrievals[0]
        if hasattr(first, "model_dump"):
            first = first.model_dump(mode="json")
        if isinstance(first, dict):
            for hit in first.get("results") or []:
                hid = hit.get("id") if isinstance(hit, dict) else None
                if hid:
                    retrieval_ids.append(str(hid))

    # Audit verdict projection
    audit = final.get("audit")
    if hasattr(audit, "model_dump"):
        audit = audit.model_dump(mode="json")
    audit_verdict = audit.get("verdict") if isinstance(audit, dict) else None

    return {
        "reply": final.get("final_response", ""),
        "language": (intake.get("language") if isinstance(intake, dict) else None) or "en",
        "needs": needs,
        "intake_stage": final.get("intake_stage"),
        "escalated": bool(final.get("escalation_reason")),
        "crisis_fired": bool(crisis.fired),
        "resources": final.get("matched_resources") or [],
        "retrieval_ids": retrieval_ids,
        "audit_verdict": audit_verdict,
        "parole_reminder_offered": (intake.get("parole_reminder_offered") if isinstance(intake, dict) else None),
        "parole_reminder_opt_in": (intake.get("parole_reminder_opt_in") if isinstance(intake, dict) else None),
        "parole_check_in_date": (intake.get("parole_check_in_date") if isinstance(intake, dict) else None),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _has_api_key() -> bool:
    provider = os.environ.get("PATHWAYS_LLM_PROVIDER", "anthropic").lower()
    if provider == "gemini":
        return bool(
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def run_suite(
    category: str | None = None,
    mode: str = "fast",
) -> SuiteResult:
    scenarios = load_all(category=category)
    if not scenarios:
        raise RuntimeError(
            f"no scenarios found (category={category!r}). "
            "evals/scenarios/ may be empty or filtered out."
        )

    has_key = _has_api_key()
    if mode == "full" and not has_key:
        print(
            "[warn] mode=full requested but no API key configured; "
            "falling back to fast mode",
            file=sys.stderr,
        )
        mode = "fast"

    results: list[ScenarioResult] = []
    for sc in scenarios:
        t0 = time.time()
        try:
            actual = _invoke(sc)
        except Exception as e:
            results.append(ScenarioResult(
                id=sc.id,
                category=sc.category,
                passed=False,
                failures=[{
                    "key": "invocation",
                    "expected": "no exception",
                    "actual_snippet": f"{type(e).__name__}: {e}",
                }],
                elapsed_ms=int((time.time() - t0) * 1000),
            ))
            continue

        passed, failures = score_scenario(actual, sc.expects)
        if mode == "full" and sc.expects_full_mode:
            full_passed, full_failures = score_scenario(actual, sc.expects_full_mode)
            passed = passed and full_passed
            failures.extend(full_failures)

        results.append(ScenarioResult(
            id=sc.id,
            category=sc.category,
            passed=passed,
            failures=failures,
            elapsed_ms=int((time.time() - t0) * 1000),
            actual=actual if not passed else {},
        ))

    return SuiteResult(
        results=results,
        mode=mode,
        provider=os.environ.get("PATHWAYS_LLM_PROVIDER", "anthropic"),
        has_api_key=has_key,
    )


def print_summary(suite: SuiteResult) -> None:
    by_cat = suite.by_category()
    print("=" * 64)
    print(f"Pathways eval suite  |  mode={suite.mode}  provider={suite.provider}  "
          f"api_key={'yes' if suite.has_api_key else 'no'}")
    print("=" * 64)

    for cat in sorted(by_cat.keys()):
        items = by_cat[cat]
        passed = sum(1 for r in items if r.passed)
        total = len(items)
        rate = passed / total if total else 1.0
        critical = " (must be 100%)" if cat in CRITICAL_CATEGORIES else ""
        marker = "PASS" if passed == total else "FAIL"
        print(f"  {cat:<14} [{passed:>3}/{total:<3}]  {rate*100:5.1f}%  {marker}{critical}")
        for r in items:
            if r.passed:
                continue
            print(f"      x {r.id} ({r.elapsed_ms}ms)")
            for f in r.failures:
                print(f"          {f['key']}: expected={f['expected']!r}")
                if f.get("actual_snippet"):
                    print(f"            actual: {f['actual_snippet']}")

    overall = suite.overall_pass_rate()
    print("-" * 64)
    print(f"OVERALL: {sum(1 for r in suite.results if r.passed)}/{len(suite.results)} "
          f"({overall * 100:.1f}%)")


def check_thresholds(suite: SuiteResult) -> tuple[bool, str]:
    """Return (passed, reason)."""
    min_rate = float(os.environ.get("PATHWAYS_EVAL_MIN_PASS_RATE", "0.90"))

    # Critical categories must be 100%.
    by_cat = suite.by_category()
    for cat in CRITICAL_CATEGORIES:
        items = by_cat.get(cat, [])
        if items and any(not r.passed for r in items):
            failed = [r.id for r in items if not r.passed]
            return False, f"critical category '{cat}' failed: {failed}"

    overall = suite.overall_pass_rate()
    if overall < min_rate:
        return False, f"overall pass rate {overall:.2%} below threshold {min_rate:.2%}"

    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(prog="evals.runner")
    parser.add_argument("--category", default=None, help="filter to one category")
    parser.add_argument(
        "--mode",
        default="fast",
        choices=["fast", "full"],
        help="fast = structural only; full = also score LLM-dependent expects",
    )
    parser.add_argument(
        "--json", default=None, help="write machine-readable results to this path"
    )
    args = parser.parse_args()

    try:
        suite = run_suite(category=args.category, mode=args.mode)
    except Exception as e:
        print(f"harness error: {e}", file=sys.stderr)
        return 2

    print_summary(suite)
    ok, reason = check_thresholds(suite)
    print("-" * 64)
    print(f"GATE: {'GREEN' if ok else 'RED'}  ({reason})")

    if args.json:
        payload = {
            "mode": suite.mode,
            "provider": suite.provider,
            "overall_pass_rate": suite.overall_pass_rate(),
            "gate_ok": ok,
            "gate_reason": reason,
            "results": [
                {
                    "id": r.id,
                    "category": r.category,
                    "passed": r.passed,
                    "elapsed_ms": r.elapsed_ms,
                    "failures": r.failures,
                }
                for r in suite.results
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"wrote {args.json}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
