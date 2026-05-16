"""Pure scoring functions for the eval harness.

A scenario passes only if every expectation in its `expects` block (and
`expects_full_mode` when run in full mode) returns True. The runner
collects per-expectation results and turns them into a per-scenario
pass/fail plus a per-category roll-up.

Keeping this module pure (no graph imports, no env reads) makes the
scoring trivially unit-testable.
"""

from __future__ import annotations

from typing import Any, Iterable


def _as_lower_set(items: Iterable[str] | None) -> set[str]:
    return {str(x).lower() for x in (items or [])}


def _reply_text(actual: dict) -> str:
    text = actual.get("reply") or actual.get("final_response") or ""
    return str(text).lower()


def check_needs_contains(actual: dict, expected_any: list[str]) -> bool:
    """At least one of the expected need categories appears in the
    captured needs (top_need or any secondary need)."""
    expect = _as_lower_set(expected_any)
    if not expect:
        return True
    needs = _as_lower_set(actual.get("needs") or [])
    return bool(expect & needs)


def check_needs_contains_all(actual: dict, expected_all: list[str]) -> bool:
    """All expected need categories appear in the captured needs."""
    expect = _as_lower_set(expected_all)
    if not expect:
        return True
    needs = _as_lower_set(actual.get("needs") or [])
    return expect.issubset(needs)


def check_intake_stage_in(actual: dict, allowed: list[str | None]) -> bool:
    """The current intake stage is one of the allowed values."""
    if not allowed:
        return True
    stage = actual.get("intake_stage")
    norm = [s if s is None else str(s).lower() for s in allowed]
    return (stage if stage is None else str(stage).lower()) in norm


def check_must_not_escalate(actual: dict, must_not: bool) -> bool:
    if not must_not:
        return True
    return not bool(actual.get("escalated"))


def check_must_escalate(actual: dict, must: bool) -> bool:
    if not must:
        return True
    return bool(actual.get("escalated"))


def check_crisis_must_fire(actual: dict, must: bool) -> bool:
    if not must:
        return True
    return bool(actual.get("crisis_fired"))


def check_crisis_must_not_fire(actual: dict, must_not: bool) -> bool:
    if not must_not:
        return True
    return not bool(actual.get("crisis_fired"))


def check_language(actual: dict, expected: str | None) -> bool:
    if expected is None:
        return True
    return str(actual.get("language", "")).lower() == expected.lower()


def check_reply_contains_any_of(actual: dict, phrases: list[str]) -> bool:
    if not phrases:
        return True
    text = _reply_text(actual)
    return any(p.lower() in text for p in phrases)


def check_reply_contains_all_of(actual: dict, phrases: list[str]) -> bool:
    if not phrases:
        return True
    text = _reply_text(actual)
    return all(p.lower() in text for p in phrases)


def check_reply_does_not_contain_any_of(actual: dict, phrases: list[str]) -> bool:
    if not phrases:
        return True
    text = _reply_text(actual)
    return not any(p.lower() in text for p in phrases)


def check_resources_min_count(actual: dict, min_count: int) -> bool:
    if min_count <= 0:
        return True
    return len(actual.get("resources") or []) >= min_count


def check_resource_id_contains_any_of(actual: dict, ids: list[str]) -> bool:
    """At least one matched resource has an id that contains one of the
    given substrings (lowercase). Useful for asserting a known org or a
    geo-aware ranker put a regional org near the top."""
    if not ids:
        return True
    targets = [i.lower() for i in ids]
    for r in actual.get("resources") or []:
        rid = str(r.get("id", "")).lower()
        if any(t in rid for t in targets):
            return True
    return False


def check_retrieval_ids_contains_any_of(actual: dict, ids: list[str]) -> bool:
    """At least one of the expected corpus ids is in the top retrieval
    results. Useful for measuring BM25 vs hybrid: a paraphrase query
    should still surface the canonical corpus entry."""
    if not ids:
        return True
    retrieved = {str(x) for x in (actual.get("retrieval_ids") or [])}
    return any(i in retrieved for i in ids)


def check_audit_verdict_in(actual: dict, allowed: list[str]) -> bool:
    """The audit node's verdict is one of the allowed values."""
    if not allowed:
        return True
    verdict = actual.get("audit_verdict")
    if verdict is None:
        # No audit ran (graph short-circuited). Don't fail if "none" is
        # explicitly allowed.
        return "none" in [a.lower() for a in allowed]
    return str(verdict).lower() in [a.lower() for a in allowed]


def check_parole_offer_present(actual: dict, expected: bool) -> bool:
    """Reply contains the parole reminder offer (EN or ES sentence)."""
    text = _reply_text(actual)
    has_offer = ("reply yes" in text) or ("responde si" in text)
    return has_offer == bool(expected)


def check_parole_opt_in_is(actual: dict, expected) -> bool:
    """parole_reminder_opt_in on the projected state. None/True/False."""
    return actual.get("parole_reminder_opt_in") == expected


def check_parole_date_iso_is(actual: dict, expected: str) -> bool:
    val = actual.get("parole_check_in_date")
    if val is None:
        return expected in (None, "")
    return str(val) == expected


# Mapping from expectation key to scorer fn. Adding a new check is one line.
SCORERS = {
    "needs_contains": check_needs_contains,
    "needs_contains_all": check_needs_contains_all,
    "intake_stage_in": check_intake_stage_in,
    "must_not_escalate": check_must_not_escalate,
    "must_escalate": check_must_escalate,
    "crisis_must_fire": check_crisis_must_fire,
    "crisis_must_not_fire": check_crisis_must_not_fire,
    "language": check_language,
    "reply_contains_any_of": check_reply_contains_any_of,
    "reply_contains_all_of": check_reply_contains_all_of,
    "reply_does_not_contain_any_of": check_reply_does_not_contain_any_of,
    "resources_min_count": check_resources_min_count,
    "resource_id_contains_any_of": check_resource_id_contains_any_of,
    "retrieval_ids_contains_any_of": check_retrieval_ids_contains_any_of,
    "audit_verdict_in": check_audit_verdict_in,
    "parole_offer_present": check_parole_offer_present,
    "parole_opt_in_is": check_parole_opt_in_is,
    "parole_date_iso_is": check_parole_date_iso_is,
}


def score_scenario(
    actual: dict,
    expects: dict[str, Any],
) -> tuple[bool, list[dict]]:
    """Run every expectation in `expects` against `actual`.

    Returns (passed, failures) where failures is a list of dicts:
        {"key": str, "expected": any, "actual_snippet": str}
    """
    failures: list[dict] = []
    for key, expected in (expects or {}).items():
        scorer = SCORERS.get(key)
        if scorer is None:
            failures.append({
                "key": key,
                "expected": expected,
                "actual_snippet": f"<unknown expectation key '{key}'>",
            })
            continue
        try:
            ok = bool(scorer(actual, expected))
        except Exception as e:
            ok = False
            failures.append({
                "key": key,
                "expected": expected,
                "actual_snippet": f"<scorer raised: {e}>",
            })
            continue
        if not ok:
            failures.append({
                "key": key,
                "expected": expected,
                "actual_snippet": _failure_snippet(key, actual),
            })
    return (len(failures) == 0, failures)


def _failure_snippet(key: str, actual: dict) -> str:
    if key.startswith("needs"):
        return f"needs={actual.get('needs')!r}"
    if key.startswith("reply"):
        text = (actual.get("reply") or actual.get("final_response") or "")[:120]
        return f"reply={text!r}"
    if key == "intake_stage_in":
        return f"intake_stage={actual.get('intake_stage')!r}"
    if key.startswith("crisis"):
        return f"crisis_fired={actual.get('crisis_fired')!r}"
    if key.startswith("must"):
        return f"escalated={actual.get('escalated')!r}"
    if key == "language":
        return f"language={actual.get('language')!r}"
    if key.startswith("resource"):
        ids = [r.get("id") for r in (actual.get("resources") or [])]
        return f"resource_ids={ids!r}"
    return ""
