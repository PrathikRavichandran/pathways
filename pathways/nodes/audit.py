"""
audit node — runs the compliance-auditor sub-agent on the draft response.

If the verdict is pass, route to send. If soft_block and we have revision
budget left, route back to draft for revision. If hard_block (out of
scope, names another state's rules, advice the user shouldn't act on
without a lawyer), route to escalate.

In demo mode (no API key), uses a deterministic rule-based auditor so the
graph runs end-to-end and tests pass without external services.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pathways.llm import LLMUnavailable, get_llm
from pathways.state import AuditResult, AuditVerdict, PathwaysState


AUDIT_SYSTEM = """You are the compliance-auditor sub-agent for Pathways. You receive a draft response, the retrievals it was built from, and the user's question. You produce ONLY a JSON verdict — no prose outside JSON.

{
  "verdict": "pass" | "soft_block" | "hard_block",
  "issues": [{"type": "citation_missing|out_of_scope|tone|non_texas", "claim": "...", "suggestion": "..."}],
  "rewrite_hint": "string or null"
}

Hard block if: legal advice given, clinical advice given, likelihood estimate of an outcome, suggestion to lie on a form, rules for a state other than Texas without explicit disclosure.
Soft block if: factual legal claim lacks citation, moralizing or condescending tone, false reassurance, promise of outcome.
Pass if: every factual legal claim has a corresponding retrieval citation, scope is TX, tone is trauma-informed."""


def run(state: PathwaysState) -> dict[str, Any]:
    if not state.draft_response:
        # Nothing to audit — escalate.
        return {
            "audit": AuditResult(
                verdict=AuditVerdict.HARD_BLOCK,
                issues=[{"type": "no_draft", "claim": "", "suggestion": "no draft produced"}],
            ),
            "next_node": "escalate",
            "escalation_reason": "no_draft_to_audit",
        }

    try:
        audit = _llm_audit(state)
    except LLMUnavailable:
        audit = _rule_based_audit(state)
    except Exception:
        audit = _rule_based_audit(state)

    # Decide where to route
    if audit.verdict == AuditVerdict.PASS:
        return {"audit": audit, "next_node": "send"}

    if audit.verdict == AuditVerdict.SOFT_BLOCK:
        # Try a revision if we have budget
        if state.audit_revision_attempts < state.MAX_AUDIT_REVISIONS:
            return {
                "audit": audit,
                "audit_revision_attempts": state.audit_revision_attempts + 1,
                "next_node": "draft",
            }
        # Out of revision budget — escalate
        return {
            "audit": audit,
            "next_node": "escalate",
            "escalation_reason": "audit_revisions_exhausted",
        }

    # Hard block — escalate
    return {
        "audit": audit,
        "next_node": "escalate",
        "escalation_reason": f"audit_hard_block:{[i.get('type') for i in audit.issues]}",
    }


def _llm_audit(state: PathwaysState) -> AuditResult:
    payload = {
        "draft": state.draft_response,
        "retrievals": [r.model_dump(mode="json") for r in state.retrievals],
        "user_query": state.user_message,
    }
    text = get_llm("audit").invoke(
        system=AUDIT_SYSTEM,
        user=json.dumps(payload),
        max_tokens=600,
        temperature=0.0,
    )
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    parsed = json.loads(text)
    return AuditResult(
        verdict=AuditVerdict(parsed["verdict"]),
        issues=parsed.get("issues", []),
        rewrite_hint=parsed.get("rewrite_hint"),
    )


def _rule_based_audit(state: PathwaysState) -> AuditResult:
    """Deterministic fallback. Conservative; flags more than the LLM auditor."""
    issues: list[dict] = []
    draft = state.draft_response or ""

    # Likelihood / outcome-promise phrases
    likelihood_patterns = [
        r"\byou'?ll probably\b",
        r"\byou'?ll get\b",
        r"\byou will be approved\b",
        r"\beverything will work out\b",
        r"\bdon'?t worry\b",
    ]
    for pat in likelihood_patterns:
        if re.search(pat, draft, re.I):
            issues.append({
                "type": "out_of_scope",
                "claim": pat,
                "suggestion": "Remove likelihood/outcome promise; state criteria only.",
            })

    # Non-TX state references
    for st in ["California", "Florida", "New York", "Oklahoma", "Louisiana"]:
        if st in draft:
            issues.append({
                "type": "non_texas",
                "claim": st,
                "suggestion": f"Pathways is TX-only; remove or explicitly disclose handoff for {st}.",
            })

    # Citation discipline: if the draft contains a section symbol or "§" but
    # the corpus retrievals didn't fire (all low-confidence), flag.
    has_section_ref = bool(re.search(r"§\s*\d+", draft) or "Texas Code" in draft)
    has_confident_retrieval = any(
        not r.gated_low_confidence and r.results for r in state.retrievals
    )
    if has_section_ref and not has_confident_retrieval:
        issues.append({
            "type": "citation_missing",
            "claim": "section reference without confident retrieval support",
            "suggestion": "Either remove the section reference or run retrieve again with a tighter query.",
        })

    if any(i["type"] == "non_texas" for i in issues):
        verdict = AuditVerdict.HARD_BLOCK
    elif issues:
        verdict = AuditVerdict.SOFT_BLOCK
    else:
        verdict = AuditVerdict.PASS

    return AuditResult(
        verdict=verdict,
        issues=issues,
        rewrite_hint="Restate without likelihood language and verify each cited section appears in a retrieval result." if issues else None,
    )
