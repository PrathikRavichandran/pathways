# Pathways — Architecture

This document explains the *why* behind the structure of this repo. The README covers the *what* and the quickstart; this file is for someone who wants to understand the design decisions.

## 1. Problem framing

Pathways is a conversational AI navigator for post-incarceration reentry in Texas. A returning citizen has, within roughly the first 30 days after release, a stack of overlapping problems on a short clock: where to sleep tonight, how to get a state ID, whether their felony rules out a job they want, whether they can vote, how to make their parole reporting appointment, and which agency speaks to which.

The system that surrounds them is fragmented across federal, state, county, and municipal layers. The information they need exists, but it's not in one place, it changes, and most of it is written in a register that requires a lawyer to interpret. The cost of bad information at this stage is high — missed appointments, ineligible applications, wasted bus fare, lost trust.

That framing drives the architectural decisions below. The goal is not "a chatbot that can answer questions about reentry." It is **"a navigator that can be wrong in safe ways."**

## 2. The "safe failure" design principle

Most of the architectural complexity in this repo exists because the failure modes of a confident, hallucination-prone LLM are unacceptable in this domain. A user who hears "you can get your record expunged" when they cannot will spend money and time on a doomed petition. A user who hears "you can vote" before fully discharging their sentence may be guilty of illegal voting. A user in crisis who gets a polite list of resources instead of 988 has been failed in a way that matters.

So the system is designed around three layers of constraint:

1. **Hooks** — deterministic Python code that runs outside the model loop. They detect crisis, redact PII, and gate retrieval below a confidence floor. The model cannot "decide this turn it's okay to log a SSN" — the hook runs regardless.

2. **Skills + Sub-agents** — bounded capabilities. Each Skill has a defined scope and the `compliance-auditor` sub-agent validates every draft response for citation discipline, tone, and scope before it ships. Sub-agents have explicit tool allow-lists in their frontmatter.

3. **Explicit graph** — the orchestrator is a LangGraph state machine where every transition is named. Failure modes have addresses: low retrieval confidence is a retrieve-node concern; tone drift is a draft-node concern; uncited claims are an audit-node concern. We iterate one node at a time, with one eval at a time.

Together these layers mean the system fails into "I'm not certain — let me connect you with a human" much more often than into a confidently-wrong answer. That's the right asymmetry for this domain.

## 3. Why Claude Code primitives, not just an SDK

The same logical pipeline (retrieve → match → draft → audit → send) could be written as a plain Python program against the Anthropic SDK. We deliberately did not.

The Claude Code primitives — Skills, sub-agents, hooks, MCP servers, settings — each express a constraint that's hard to enforce in a plain SDK script:

| Primitive | What it gives us |
|---|---|
| **Skills (`.claude/skills/`)** | Modular protocols loaded by description match. The `niccc-lookup` skill encodes the cite-or-don't-claim contract. The `crisis-response` skill encodes the trauma-informed protocol. These can be developed and evaluated independently. |
| **Sub-agents (`.claude/agents/`)** | Bounded-capability scopes. The `caseload-summarizer` has read-only PG access and cannot send SMS; the `compliance-auditor` is read-only and JSON-only-output. The runtime enforces these via `disallowedTools` in agent frontmatter. |
| **Hooks (`.claude/hooks/`)** | Code that runs outside the model loop. Crisis detection, PII redaction, and retrieval confidence gating are deterministic. They don't depend on the model's mood or context. |
| **MCP servers (`mcp_servers/`)** | Knowledge contracts at the tool layer. We can swap `pathways-corpus` from a BM25-over-JSON demo to a Pinecone-backed hybrid retriever in production without changing a single Skill. |
| **Settings (`.claude/settings.json`)** | The permission boundary. `permissions.allow/deny/ask`, `allowManagedHooksOnly: true`, and explicit hook matchers are the runtime's enforcement points. |

The plain-SDK version would either reimplement these (badly) or skip them and absorb the cost in eval failures.

## 4. Runtime topology

```
                                  ┌────────────────────────────────────┐
                                  │ Twilio SMS / claude.ai / API       │
                                  └──────────────┬─────────────────────┘
                                                 │
                       ┌─────────────────────────▼─────────────────────────┐
                       │ FastAPI ingress (pathways/api/main.py)            │
                       │ • signature verification (prod)                   │
                       │ • Twilio webhook parsing                          │
                       │ • crisis_keyword_check replay                     │
                       └────────────────────────┬──────────────────────────┘
                                                │
                       ┌────────────────────────▼──────────────────────────┐
                       │ LangGraph state machine (pathways/graph.py)       │
                       │                                                   │
                       │   intake ──▶ retrieve ──▶ match ──▶ draft         │
                       │     │                                  │          │
                       │     │                                  ▼          │
                       │     │                                audit        │
                       │     │                                  │          │
                       │     │           ◀──── revision loop ───┤          │
                       │     ▼                                  ▼          │
                       │   escalate ◀──────────────────────── send         │
                       │     │                                  │          │
                       │     ▼                                  ▼          │
                       │   END                                 END         │
                       └─────────────────────────┬─────────────────────────┘
                                                 │
            ┌────────────────────┬───────────────┴───────────────┬────────────────────┐
            │                    │                               │                    │
   ┌────────▼─────────┐  ┌───────▼────────┐           ┌──────────▼───────┐  ┌─────────▼────────┐
   │ pathways-corpus  │  │  tx-resources  │           │  twilio-sms       │  │ pathways-postgres │
   │ (MCP stdio)      │  │  (MCP stdio)   │           │  (MCP http, prod)│  │ (MCP postgres)    │
   │ BM25 / Pinecone  │  │ TX directory   │           │ HITL-gated send  │  │ case-mgr views   │
   └──────────────────┘  └────────────────┘           └──────────────────┘  └──────────────────┘
```

**Inside** Claude Code sessions (or behind the FastAPI ingress), each node is a small focused function. **Outside** is the MCP server fleet — knowledge, directory, messaging, persistence — each behind a stable tool contract.

## 5. Node-by-node design rationale

### `intake`

Extracts the minimum routing-relevant fields from a user's message — region, top need, supervision status if mentioned. Uses Haiku for extraction with a deterministic heuristic fallback so the system runs in demo mode without an API key.

Crisis short-circuit: if the `crisis_keyword_check` hook fired upstream of the graph, intake routes directly to `escalate`. No retrieval, no draft, no audit — the user in crisis is not made to wait for a 5-stage pipeline.

### `retrieve`

Calls `pathways-corpus` MCP server with a category filter derived from the routing decision and the user message as the query. The MCP server is a BM25 retriever over a curated 65-entry corpus of real Texas statutory citations harvested from the [Texas State Law Library's "Restrictions After a Criminal Conviction" research guide](https://guides.sll.texas.gov/criminal-conviction-restrictions) and the [NICCC inventory](https://niccc.nationalreentryresourcecenter.org/).

The retrieval returns a confidence score. The `rag_confidence_gate` PostToolUse hook runs after this node and rewrites any low-confidence result into a "do not assert, hand off" payload. This is the key safety property: the model literally cannot draft a citation it doesn't have evidence for.

### `match`

Calls `tx-resources` MCP server with a category and region filter to surface the right directory entries — Texas RioGrande Legal Aid for civil legal, Goodwill Houston for fair-chance employment, 211 for housing emergencies. Region match preferred, statewide fallback if region is sparse.

### `draft`

This is the only node that does heavy LLM work. Uses Sonnet to compose a user-facing reply that synthesizes retrievals + matched resources while obeying the Skill-encoded protocol. In demo mode without an API key, a deterministic template runs so the graph completes end-to-end.

### `audit`

Runs the `compliance-auditor` sub-agent on the draft. The auditor is Haiku-based, JSON-only-output, and checks four things:

1. Every factual legal claim has a corresponding retrieval citation
2. Scope is Texas (other states' rules require explicit handoff)
3. No likelihood/outcome promises ("you'll probably get...")
4. Trauma-informed tone (no moralizing, no false reassurance)

Verdicts are `pass`, `soft_block` (revisable), or `hard_block` (escalate to human). The draft⇄audit revision loop is bounded by `MAX_AUDIT_REVISIONS=2` — past that, the conversation escalates rather than ship marginal output.

### `escalate` and `send`

Terminal nodes. `escalate` produces a category-matched handoff message (988 for suicide, 1-800-799-7233 for DV, 211 for housing emergency). `send` promotes the audited draft to `final_response`. The actual Twilio dispatch happens outside the graph in the FastAPI layer, gated by a HITL confirmation in the production deployment.

## 6. Why explicit graph rather than thin coordinator

A common alternative is one super-prompted agent with retrieve/match/audit as tools the agent calls in its own order. That design has three weaknesses for this domain:

1. **Audit becomes optional under context pressure.** If the agent has freedom to skip the audit step under retrieval pressure or token pressure, it will. Making `audit` a required node in the graph guarantees it runs every turn, every time.
2. **No targeted intervention.** When something goes wrong, the response is the only artifact; there's no trace of which decision was responsible. The explicit graph gives every decision an address.
3. **Bounded capability per stage is lost.** Retrieval shouldn't be allowed to draft; drafting shouldn't be allowed to retrieve again. Each node having only its job is a load-bearing safety property.

The cost of the explicit graph is more code and a less-flexible orchestrator. We pay it on purpose.

## 7. The compliance triple-layer

| Layer | Where | Who enforces | Failure mode if bypassed |
|---|---|---|---|
| **Hook layer** | `.claude/hooks/` | Runtime (out of model loop) | Crisis missed; PII leaked to logs; weak retrieval used confidently |
| **Skill + sub-agent layer** | `.claude/skills/`, `.claude/agents/` | Claude Code session policy + sub-agent frontmatter | Skills' protocol drift; sub-agent capability creep |
| **Graph layer** | `pathways/graph.py` | LangGraph topology | Required audit gets skipped under context pressure |

The redundancy is intentional. If any one layer fails, the other two still gate the response.

## 8. What's mocked vs real (for the demo)

| Component | Demo mode | Production |
|---|---|---|
| `pathways-corpus` | BM25 over 65-entry JSON | Pinecone hybrid retrieval over full NICCC + TX corpus, refreshed weekly |
| `tx-resources` | Curated 18-entry JSON | Postgres-backed directory with weekly refresh from partner orgs |
| `twilio-sms` | HTTP MCP stub | Real Twilio Programmable Messaging with signature verification |
| `pathways-postgres` | Mocked views | Postgres 16 with read-only views for case managers |
| Audit verdict | Rule-based fallback when no API key | Haiku-based `compliance-auditor` sub-agent |
| Intake extraction | Keyword heuristic when no API key | Haiku extraction with structured output |
| Draft composition | Deterministic template when no API key | Sonnet synthesis through Skills |

The system runs end-to-end in demo mode — `pytest` exercises the full graph without an API key — and swap-in production components have identical tool contracts, so the upgrade path is configuration, not code.

## 9. What's deliberately out of scope

A few things this architecture *doesn't* try to do, on purpose:

- **Not a case management system.** Pathways navigates; it doesn't track. Caseload data lives in a separate Postgres reachable only by the case manager via the isolated `caseload-summarizer` sub-agent.
- **Not multi-state.** Texas-only by deployment. Adding another state means another curated corpus, another regional resource directory, another compliance review with that state's legal aid orgs. We do not pretend coverage we don't have.
- **Not a legal advice service.** Every Skill repeats this. The system surfaces citations and routes to legal aid; it never tells a user what to do in their specific case.
- **Not autonomous on irreversible actions.** Sending an SMS, modifying a case record, or accepting a benefits-form submission requires explicit user (or operator) confirmation per the prohibited-actions list. The hook layer enforces this.

## 10. Iteration roadmap

The pieces that would land first in a real production deployment:

1. **Replace BM25 with hybrid retrieval** — semantic + lexical over Pinecone with reranking. Calibrate the confidence floor against eval data instead of the demo's 0.62 default.
2. **Twilio signature verification + idempotency** in `pathways/api/main.py`. The demo only parses; production validates.
3. **Postgres checkpointer for LangGraph state.** Right now state is in-memory; production persists per `session_id` so a multi-turn conversation can span hours or days.
4. **Eval harness.** A pinned set of conversation traces with expected `top_need`, citation accuracy, and audit verdict — run on every change to the corpus, hooks, or graph topology.
5. **Spanish bilingual support.** The intake node has `language: "en" | "es"` but the Skills are English-only today.
6. **Partner-org refresh pipeline.** `tx-resources.json` is hand-curated; production runs a weekly Prefect job that pulls from partner APIs (TRLA, LSLA, TVC, TWC) and surfaces diffs for human review before merging.

Each of these is an independent vertical with its own eval surface. That's the payoff for the layered design — improvements ship one slice at a time.

## 11. Phase 7 additions (2026-05-18)

Two changes layered on the existing architecture without restructuring it.

**Resource map view in the PWA.** A new `web/src/components/ResourceMap.tsx` renders above the existing card list inside the bot bubble whenever any returned resource carries lat / lon. The architectural seam touched is the projection layer at `pathways/api/web.py::_shape_response`, which now forwards `lat` and `lon` from `matched_resources` into the `ResourceCard` Pydantic model via a defensive `_coerce_float` helper that handles psycopg `Decimal`, numeric strings, and garbage values without raising. The component self-gates: when no resource has both coordinates, it returns null and nothing renders. Statewide hotlines stay in the cards list but never pin. The dashboard's `conversation_events` table gained a `resources_with_coords_count` column with an `ALTER TABLE IF NOT EXISTS` migration, surfaced in `summary()` as `map_pins_total` + `turns_with_map_view`. A new structured log line `web_turn_map_metrics ...` emits per turn for operator tailing.

**CI auto-deploy of main to the HF Space.** A new `.github/workflows/deploy-hf.yml` force-pushes `main` to `huggingface.co/spaces/prathik10/pathways` on every merge, then polls `/health` for up to 10 minutes (fail-soft). Force-push is required because HF Spaces start from an unrelated initial commit. The deploy workflow joins the existing four (`ci.yml`, `evals.yml`, `daily-cron.yml`, `refresh-data.yml`) for a total of five GitHub Actions workflows.

Neither change altered the LangGraph state machine, the Skills / sub-agents / hooks layer, the MCP servers, or the safety architecture. They are additive: a new UI surface on the PWA side plus a new analytics column, and an ops automation that closes a manual gap.
