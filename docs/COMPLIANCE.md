# Compliance Posture

Pathways is built for a regulated domain (post-incarceration reentry navigation in Texas) where the cost of bad information at the wrong moment is high. This document is for the operator who needs to know what Pathways does and does not do at a compliance level — what's enforced where, what's deferred to humans, and what's intentionally out of scope.

## What this document is not

This is not a SOC 2 attestation. It is not a HIPAA security policy. It is not legal advice on what compliance posture a *production* deployment of Pathways would need — that depends on which partner orgs are integrated, what data flows where, and what jurisdictions are in scope.

It is a *posture statement*: how the system is structured to behave compliantly, where the enforcement points are, and what the deployment team needs to make decisions about before going live.

## Threat model (abbreviated)

Pathways' top concerns, ranked:

1. **Wrong legal information given confidently.** A user acts on it, suffers consequences. → Mitigated by citation discipline + audit + confidence gating + handoff defaults.
2. **Crisis missed or mishandled.** A user in active crisis gets a polite resource list instead of 988. → Mitigated by `crisis_keyword_check` upstream of the graph and crisis short-circuit routing.
3. **PII leaked into logs, transcripts, or analytics.** → Mitigated by `pii_redact` PreToolUse hook + database view-layer name masking + no-PII intake fields.
4. **Cross-client data leakage.** One client's data surfaced in another client's conversation. → Mitigated by sub-agent isolation (caseload-summarizer cannot run from a user-facing session).
5. **Outcome promises that aren't deliverable.** → Mitigated by rule-based audit checks for likelihood phrases + Skill-level "never promise outcomes" guidance.

## Where enforcement happens

| Concern | Primary enforcement layer | Secondary layer | Notes |
|---|---|---|---|
| Crisis detection | `crisis_keyword_check.py` hook (UserPromptSubmit) | LangGraph routing in intake node | Hook fires deterministically; graph routes appropriately |
| Citation discipline | `compliance-auditor` sub-agent (audit node) | Skill protocol (`niccc-lookup`) | Audit gates ship; Skill encourages |
| Confidence floor on retrieval | `rag_confidence_gate.py` hook (PostToolUse) | `niccc-lookup` Skill's gate language | Configurable via `PATHWAYS_CONFIDENCE_FLOOR` |
| PII redaction in writes | `pii_redact.py` hook (PreToolUse) | DB view-layer name masking | Hook covers logs; DB views cover persisted state |
| Scope (TX-only) | `compliance-auditor` audit node | All Skills' "if other state" language | Hard-block in audit if non-TX state mentioned |
| Outcome promises | `compliance-auditor` rule check | Skill protocol | Rule-based fallback catches likelihood phrases |
| Tool capability scoping | `.claude/settings.json` allow/deny lists + agent `disallowedTools` | LangGraph node-level boundaries | Settings enforce; graph topology reinforces |
| Crisis hotline preservation in PII redactor | Allowlist in `pii_redact._PHONE_ALLOWLIST_DIGITS` | Tested in `test_hooks.py` | 988, 211, DV/SAMHSA/RAINN/988-legacy hotlines pass through |

## What is *not* enforced at the hook layer (deliberate)

### Names

The `pii_redact` hook redacts SSN, driver license, state ID, TDCJ inmate number, phone, email, DOB, street address, and county-prefixed case numbers. It does **not** redact names.

Why: name redaction is high-false-positive. Statute authors, public officials, place names (e.g., "Travis County" contains "Travis"), and well-known orgs (e.g., "Lone Star Legal Aid") all show up legitimately in Pathways' output. A redactor aggressive enough to catch names of real users would also redact "Salvation Army Houston" and "Texas Workforce Commission."

Name protection happens instead at the database view layer: when `caseload-summarizer` queries `view_client_interactions`, that view returns pseudonymized client identifiers (e.g., `client_8e2a`) rather than real names. The view is the choke point; the model never sees a raw name unless the user typed one into the current conversation.

This is documented here, and in `pii_redact.py`, so a future operator does not assume "the hook handles names" when it doesn't.

### Free-form addresses without street suffix

Conservative pattern matching. A user typing "I'm at 123 main near the gas station" won't be caught. Trade-off accepted: false negatives on informal addresses, near-zero false positives on common phrases.

### Financial account numbers

Pathways does not need or accept financial account information for any of its flows. The `prohibited_actions` policy in CLAUDE.md and the corresponding `settings.json` permission denies prevent the assistant from collecting or storing this category. The PII redactor doesn't include a credit-card pattern because credit cards should never appear in input in the first place; if they do, that's a system bug to fix at the ingress layer, not patch over with regex.

## Compliance behaviors by user flow

### A user asks about a legal restriction (employment, voting, housing, record clearing)

1. `crisis_keyword_check` runs; no crisis → continue.
2. `intake` extracts top_need=legal_question / employment / etc.
3. `retrieve` calls `pathways-corpus`; gets a result with a confidence score.
4. `rag_confidence_gate` fires. If confidence < 0.62, the retrieval result is rewritten to a structured handoff payload, and the model cannot draft a confident answer from it.
5. `match` adds legal aid resources (TRLA, LSLA) when the top_need is legal-flavored.
6. `draft` composes a reply that, per the `niccc-lookup` Skill, cites every legal claim by section number.
7. `audit` checks citation discipline + scope + tone. If audit fails on a soft_block issue and revision budget remains, the draft is rewritten. If hard_block (non-TX rule, outcome promise) or budget exhausted, the conversation escalates to a human navigator.
8. `send` ships the audited draft.

### A user is in crisis

1. `crisis_keyword_check` matches a category (suicide, self_harm, substance, domestic_violence, violence_to_others, sexual_violence, housing_emergency).
2. The hook returns a `systemMessage` to the parent session and sets a `category` field in `hookMetadata`.
3. The FastAPI ingress wraps this into a `CrisisSignal` on the graph state.
4. `intake` reads `state.crisis.fired` and routes directly to `escalate` — bypassing retrieval, matching, drafting, and auditing.
5. `escalate` produces the category-matched response (988, 1-800-799-7233, 211, etc.) and exits the graph.

Crisis handling is deliberately *less* configurable than the normal path. The model cannot decide to do crisis handling differently this turn.

### A case manager runs the weekly summary

1. The case manager invokes `claude --agent caseload-summarizer` from the command line. This is the *only* path; the agent is not callable from a user-facing session.
2. The sub-agent reads its configuration, calls `pathways-postgres` MCP server's read-only views (which return PII-scrubbed records).
3. It writes a single markdown summary to `.claude/cache/summaries/`. No other paths are writable.
4. It cannot call `pathways-corpus`, `tx-resources`, or `twilio-sms` — those are disallowed in its frontmatter.

## Audit trail

The system produces four streams of structured artifacts on every turn:

1. **Hook metadata.** Every hook returns a `hookMetadata` field with the hook name, action taken, and relevant inputs (e.g., crisis category, PII redaction count, confidence value). These are captured by the FastAPI ingress and persisted (in production) to the audit log.
2. **Graph state snapshots.** LangGraph emits per-node state transitions. The `_debug/invoke` endpoint exposes the final state for inspection; production wires this to a tracing backend (LangSmith, OpenTelemetry).
3. **Compliance auditor verdicts.** Every audit run produces a JSON verdict object (pass / soft_block / hard_block) with the specific issues found. The verdict is part of the graph state and can be inspected per turn.
4. **Structured per-turn log lines.** As of Phase 7, the web-channel handler emits one line per turn keyed on the truncated salted thread ID: `web_turn_map_metrics thread=... cards_total=N cards_with_coords=N map_renders=0|1 language=en`. PII-safe by construction (truncated hash, no message bodies, no PII fields). A downstream log shipper (Loki, Datadog) can group on these keys to answer "how often does the map view actually render?" without opening the dashboard.

Together these give an investigator answers to "why did the system do what it did on turn N for user X?" without exposing PII (because of the view layer + redaction hook).

## What an operator must decide before production deployment

1. **Data residency.** Where does Postgres live? Where does Twilio's data sit?
2. **Retention policy.** How long are conversation transcripts kept? Are crisis-flagged conversations retained differently?
3. **Audit log destination.** SOC 2-compliant logging endpoint (Datadog, Splunk, etc.) wired to the hook metadata streams.
4. **Case manager identity & access.** How are case managers authenticated? Is sub-agent invocation gated by an additional auth check?
5. **HIPAA scope.** If the deployment touches health information (substance use treatment referrals, mental health), the BAA scope expands. Pathways' default posture is to refer to (not store) treatment information, but specific partner integrations may shift this.
6. **Multi-county variations.** Texas is heterogeneous at the county level for some flows (court fees, expunction procedures). Production rollouts beyond Harris/Travis/Dallas counties need partner-org input.
7. **Eval and red-team cadence.** Pinned trace evaluation on every change to corpus, hooks, or graph topology; quarterly red-team exercise on the crisis path.

## Known compliance gaps the demo *does not* claim to solve

- No multi-tenancy isolation in the demo. Production needs per-case-manager workspace isolation at the Postgres layer.
- No automatic data-deletion-on-request flow. GDPR-style "right to be forgotten" is feasible given the architecture but is not implemented.
- No translated Spanish Skills. The intake captures language preference but the Skill content is English-only.
- No accessibility audit. SMS is inherently more accessible than a webapp, but voice-interface support for users with low literacy is not implemented.

These are roadmap items, not architectural blockers. The layered design (hooks + Skills/sub-agents + explicit graph) admits each of them as a localized change rather than a system rewrite.
