---
title: Pathways
emoji: 🛤️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: AI navigator for post-incarceration reentry in Texas
---

# Pathways

[![CI](https://github.com/PrathikRavichandran/pathways/actions/workflows/ci.yml/badge.svg)](https://github.com/PrathikRavichandran/pathways/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-30%2F30%20passing-brightgreen)](https://github.com/PrathikRavichandran/pathways/actions)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![HF Space](https://img.shields.io/badge/%F0%9F%A4%97%20HF%20Space-live-yellow)](https://prathik10-pathways.hf.space/docs)

A conversational AI navigator for people leaving incarceration in Texas. Built as a Claude Code architecture: layered **Skills**, **sub-agents**, **hooks**, **MCP servers**, **settings**, and a distributable **plugin** — composed into one reliable workflow for a safety-critical domain.

This repo is both a real product-in-progress *and* an opinionated demonstration of how Claude Code primitives compose when wrong answers cause real harm — legal misinformation, missed deadlines, lost benefits, or a missed crisis signal.

> **Status:** Active development. The architecture is complete and the demo flow runs end-to-end against real Texas statutory data. Tests: **30/30 passing** (hooks + LangGraph end-to-end across 6 conversation paths). Twilio dispatch and live Pinecone are stubbed behind interfaces and documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## ⚡ Try it in 30 seconds

| Surface | URL | Try this |
|---|---|---|
| 🩺 **API health** | <https://prathik10-pathways.hf.space/health> | Returns `{"status":"ok","version":"0.1.0"}` |
| 📚 **OpenAPI / Swagger** | <https://prathik10-pathways.hf.space/docs> | Interactive — try `/_debug/invoke` with `{"message":"Can I vote in Texas if I'm on parole?"}` |
| 🧠 **Architecture deep-dive** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Why each Claude Code primitive is load-bearing in a safety-critical domain |
| 🎬 **Per-primitive walkthrough** | [`docs/SHOWCASE.md`](docs/SHOWCASE.md) | Code-trace tour: see exactly what a Skill, sub-agent, hook, and MCP server look like in practice |
| 💬 **Sample conversations** | [`examples/sample_conversations.md`](examples/sample_conversations.md) | 5 fully-annotated SMS dialogues end-to-end (housing crisis, voting eligibility, multi-need, etc.) |

### Install as a Claude Code plugin (loads all 7 Skills + 4 sub-agents + 3 hooks into your own session)

```bash
git clone https://github.com/PrathikRavichandran/pathways.git
cd pathways && claude plugin install .
```

Then open any Claude Code session and ask a Texas-reentry question — the right Skill auto-loads, the safety hooks fire, the `compliance-auditor` sub-agent audits the response, and the MCP servers serve the corpus + resources. No model setup, no infra. The `.claude/plugin.json` manifest is the recruiter's quickest path to "this person actually shipped something I can install and run."

---

## The problem this exists to solve

The first 72 hours after release are the highest-risk window for a returning citizen. Housing, ID documents, work authorization, parole reporting, mental health continuity, and benefits all collide in a narrow window — and the information that resolves them is fragmented across federal databases (NICCC), state agencies (TWC, HHSC), county courts, and local non-profits. Caseworkers spend most of their time looking things up rather than working with people.

Pathways is an SMS-first navigator (Twilio in prod, web for demo) that answers concrete questions — *"can I get my driver's license back if my felony was a state jail felony from 2018?"* — with cited answers, escalation gates, and a humane handoff to a real navigator when the model isn't certain.

## Why this is a Claude Code project, not just a LangGraph app

The naive build is a LangGraph state machine with a few RAG tools. The reason that's not enough:

- **Deterministic guardrails belong outside the agent loop.** Crisis-keyword detection cannot depend on the model deciding to be careful. It runs as a `UserPromptSubmit` hook.
- **Domain workflows shouldn't be inlined into a monolithic prompt.** Each phase of a navigator's day — intake, eligibility check, resource matching, record-clearing eligibility, benefits navigation — is its own progressive-disclosure Skill, loaded only when relevant.
- **Specialized agents need narrowed capability, not broader.** The `compliance-auditor` sub-agent is read-only and can only see retrieval outputs; the `caseload-summarizer` can read PostgreSQL views but cannot write back. Sub-agents here aren't about parallelism, they're about *bounding what each part of the system can do*.
- **External integrations want to be tools, not glue code.** NICCC retrieval, Texas resource directories, and Twilio are MCP servers, so they're swappable and individually auditable.

The result: a system where every safety property is enforced at the right layer, and where every architectural choice has an explicit reason a human auditor can follow.

---

## Architecture at a glance

```
                  ┌──────────────────────────────┐
   User (SMS) ───▶│  FastAPI ingress (Twilio webhook)  │
                  └──────────────┬───────────────┘
                                 │
                  ┌──────────────▼───────────────┐
                  │   UserPromptSubmit hook:      │  ◀── deterministic
                  │   crisis_keyword_check.py     │     (no model in path)
                  └──────────────┬───────────────┘
                                 │
                  ┌──────────────▼───────────────┐
                  │   LangGraph state machine     │
                  │   (pathways/graph.py)         │
                  │                               │
                  │   Claude Sonnet — routing &   │
                  │   synthesis. Haiku for        │
                  │   classification. Opus for    │
                  │   complex policy reasoning.   │
                  └────┬──────────────────────┬──┘
                       │                      │
        Skills auto-load by description       │
        ┌──────────────┼──────────────┐       │
        ▼              ▼              ▼       ▼
  intake-       niccc-         crisis-  record-clearing-tx
  assessment    lookup         response  benefits-navigator
                                          housing-pathway
                                          employment-pathway
                       │
        Sub-agents spawn for bounded work
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  eligibility-   resource-     compliance-
  checker        matcher       auditor

                                 │
                       MCP servers (JSON-RPC)
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  pathways-      tx-resources   twilio-sms
  corpus         (211 TX, TWC,  (sandbox in
  (NICCC RAG)     HUD, courts)  public repo)

  PostToolUse hook (rag_confidence_gate.py):
    blocks responses below confidence threshold,
    forces human-handoff phrasing.

  PreToolUse hook (pii_redact.py):
    redacts PII before any write to logs.
```

---

## What each Claude Code primitive does in this repo, and why

This section is the one I'd want a screener to read carefully. The JD said *"a short README explaining what each piece does and why you built it is more valuable than volume"* — this is that.

### Skills (`.claude/skills/`)

Seven Skills, each a single SKILL.md with progressive disclosure. Auto-loaded by description match.

| Skill | Loads when | Why it's a Skill not a prompt |
|---|---|---|
| `intake-assessment` | New conversation, no prior state | Standardizes the first 5 minutes. Without it, the model improvises and skips trauma-informed protocol. |
| `niccc-lookup` | User asks about reentry rights or restrictions | Hard requirement: outputs must cite NICCC sections. A Skill enforces the citation contract; a one-shot prompt doesn't. |
| `housing-pathway` | Housing, shelter, transitional living | Felony-record exclusions are state-specific. Skill encapsulates the Texas-specific decision tree. |
| `employment-pathway` | Jobs, work, fair-chance | Bundles fair-chance employer lookup + TWC reentry programs + ban-the-box context. |
| `record-clearing-tx` | Expungement, non-disclosure, sealing | Texas non-disclosure eligibility is genuinely complex (Code of Criminal Procedure Ch. 411). Skill is a structured worksheet. |
| `benefits-navigator` | SNAP, Medicaid, SSI, SSDI | Texas drug-felony bans on SNAP were lifted in 2015; getting this wrong sends people away from food they're eligible for. |
| `crisis-response` | Crisis keywords detected (hook-triggered) | Skill captures the trauma-informed escalation script. Loaded by hook, not by model judgment. |

### Sub-agents (`.claude/agents/`)

Four sub-agents, each with **narrowed** permissions vs. the parent session — not broader.

| Sub-agent | Permission profile | Why it's a sub-agent |
|---|---|---|
| `eligibility-checker` | Read-only on intake state, no MCP, no Write | Eligibility logic should be reproducible from a single input record. Isolation forces that. |
| `resource-matcher` | Can call `tx-resources` and `pathways-corpus`; cannot call `twilio-sms` | Matching is read-side. Sending is a separate concern that must HITL-confirm. |
| `compliance-auditor` | Read-only. Sees the draft response + the retrieved citations. | Validates every legal claim has a citation. Runs in isolated context so its judgment isn't polluted by the conversational pressure to be helpful. |
| `caseload-summarizer` | Read-only on PostgreSQL views; runs only on `--agent` invocation, not from the main session | Generates weekly summaries for case managers. Lives in its own context so it can't accidentally leak client data into a user-facing conversation. |

### Hooks (`.claude/hooks/`)

Three hooks. The pattern: hooks enforce safety properties that **cannot** depend on model judgment.

| Hook | Event | What it enforces |
|---|---|---|
| `crisis_keyword_check.py` | `UserPromptSubmit` | Matches a curated keyword list (suicide, self-harm, OD, immediate violence). On match, injects a system instruction routing to `crisis-response` Skill before any other processing. |
| `pii_redact.py` | `PreToolUse` (matcher: Write, Bash, log-writing MCP tools) | Redacts names, DOBs, case numbers, SSN-pattern strings before anything leaves the trust boundary. Blocks on redaction failure. |
| `rag_confidence_gate.py` | `PostToolUse` (matcher: retrieval tools) | If retrieval confidence falls below threshold, rewrites the tool result to force a "I'm not certain — let me connect you to a navigator" response. |

### MCP servers (`.mcp.json` + `mcp_servers/`)

Two real, two stubbed. The two real ones run locally with seeded data so the repo runs end-to-end without external credentials.

| Server | Transport | What it exposes | State |
|---|---|---|---|
| `pathways-corpus` | stdio | `search_corpus(query, category)`, `get_citation(id)`, `list_categories()` over a 65-entry real-TX corpus harvested from sll.texas.gov | Real, BM25 retrieval |
| `tx-resources` | stdio | `find_resources(topic, category, region)`, `get_resource(id)`, `list_categories()` over 18 curated TX reentry orgs | Real, region-aware filter |
| `twilio-sms` | http | `send_sms`, `receive_webhook` | Stubbed; interface defined, sandbox creds in `.env.example` |
| `pathways-postgres` | stdio | Read-only views for `caseload-summarizer` | Stubbed; SQL views documented in `docs/ARCHITECTURE.md` |

### Settings (`.claude/settings.json`)

The production posture in one file. Model tiering (Haiku for routing, Sonnet for synthesis, Opus reserved for complex policy reasoning), permission allow/deny lists scoping every write, `allowManagedHooksOnly: true` so the safety posture can't be silently relaxed.

### CLAUDE.md

The operating constitution. Tight (under 80 lines). Always cite NICCC for legal claims. Never give legal advice. HITL gate on anything financial or legal. Texas-only scope.

---

## Run it locally in 60 seconds

```bash
git clone https://github.com/PrathikRavichandran/pathways.git
cd pathways
cp .env.example .env        # no real keys needed for demo mode
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
claude                       # .claude/ auto-loads; .mcp.json connects local servers
```

Then in the Claude Code session:

```
I'm a 32yo just released from TDCJ Beto Unit two days ago. 2018 state jail
felony for possession. I need housing and I want to know if I can get my
license back.
```

You'll see: `intake-assessment` Skill auto-loads → routes to `housing-pathway` and `record-clearing-tx` → calls `pathways-corpus` and `tx-resources` MCP servers → `compliance-auditor` sub-agent validates citations → final response cites NICCC sections and offers SMS handoff to a real navigator.

## What's mocked vs. real

| Concern | Status |
|---|---|
| LangGraph state machine | **Real, runs.** 7 nodes wired (intake → retrieve → match → draft → audit → send/escalate), bounded revision loop |
| All 7 Skills | Real, with realistic content (not stubs) |
| All 4 sub-agents | Real definitions with frontmatter-enforced capability scoping |
| All 3 hooks | Real, executable Python; **30/30 hook + graph tests passing** |
| `pathways-corpus` MCP server | **Real**, 65 entries fetched from sll.texas.gov and NICCC, BM25 retrieval, tested |
| `tx-resources` MCP server | **Real**, 18 curated TX reentry orgs, region-aware filter, tested |
| `twilio-sms` MCP server | Interface defined, send is stubbed |
| `pathways-postgres` MCP server | Interface defined, SQL views documented |
| Pinecone | Local BM25 equivalent in demo; production upgrade path documented |
| FastAPI ingress | **Real**, `/sms`, `/health`, `/_debug/invoke` routes, lifespan warm-up |
| Tests | **30/30 passing**: 18 hook tests + 12 graph tests covering 6 conversation paths |

## What I'd build next, in order

1. **Real NICCC ingestion pipeline.** Currently 40 hand-curated excerpts. Production needs the full NICCC corpus chunked, embedded, and indexed with state filters.
2. **Eval harness.** A 50-question Texas reentry rubric with ground-truth citations. LLM-as-judge for citation correctness, exact-match for eligibility outcomes. Run on every PR.
3. **Twilio production wiring.** Webhook receiver, opt-in/opt-out compliance, message threading.
4. **Multi-language.** Spanish first. The Texas reentry population includes a meaningful Spanish-monolingual subset.
5. **Caseworker UI.** Next.js PWA wrapping the same backend, for navigators managing 30+ clients each.
6. **B2B SaaS packaging.** Multi-tenant, per-org NICCC corpora (some orgs have state-specific addenda), org-scoped analytics.

## Why I built this

A Claude Code architecture is most interesting when the *cost of being wrong* is high. Reentry is one of those domains. The same primitives — Skills for domain workflows, sub-agents for bounded capability, hooks for deterministic safety, MCP for swappable integration — apply directly to healthcare (where I do this professionally at MMI) and any other regulated context. This repo is the public, non-confidential expression of that architecture.

## License

Apache 2.0. See `LICENSE`. The NICCC content excerpts seeded in `mcp_servers/pathways_corpus/corpus.json` are public-domain federal data.

## Contact

Prathik Ravichandran — prathik.ravichandran.work@gmail.com — [LinkedIn](https://www.linkedin.com/in/prathik-ravichandran/)
