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
[![Evals](https://github.com/PrathikRavichandran/pathways/actions/workflows/evals.yml/badge.svg)](https://github.com/PrathikRavichandran/pathways/actions/workflows/evals.yml)
[![Tests](https://img.shields.io/badge/tests-305%20unit%20%2B%2073%20evals-brightgreen)](https://github.com/PrathikRavichandran/pathways/actions)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![HF Space](https://img.shields.io/badge/%F0%9F%A4%97%20HF%20Space-live-yellow)](https://prathik10-pathways.hf.space/docs)
[![PWA](https://img.shields.io/badge/PWA-pathways--iota.vercel.app-7AB182)](https://pathways-iota.vercel.app/)

A conversational AI navigator for people leaving incarceration in Texas. Built as a Claude Code architecture: layered **Skills**, **sub-agents**, **hooks**, **MCP servers**, **settings**, and a distributable **plugin**, composed into one reliable workflow for a safety-critical domain.

This repo is both a real product-in-progress AND an opinionated demonstration of how Claude Code primitives compose when wrong answers cause real harm: legal misinformation, missed deadlines, lost benefits, or a missed crisis signal.

> **Status:** Phase 7 complete (2026-05-18). The system runs end-to-end across three audiences (SMS user, PWA user, caseworker dashboard) on the same FastAPI + LangGraph + Skills + MCP backend. Phase 7 added a Leaflet + OpenStreetMap map view above the PWA resource cards (with Google Maps deep-link), per-turn map-engagement analytics on the dashboard, and a CI auto-deploy workflow that mirrors `main` to the HF Space on every merge. Quality signal: **305 unit tests + 73 eval scenarios** all green; CI gates merges on a per-category pass rate with crisis at 100%. Two items remain deferred-with-design ([`docs/PHASE6_DEFERRED.md`](docs/PHASE6_DEFERRED.md)): MMS photo extraction and warm-transfer voice, both blocked by paid Twilio dependencies. The full chronological build is in [`docs/JOURNAL.md`](docs/JOURNAL.md); an interview-prep tour through every layer is in [`docs/INTERVIEW_BRIEFING.md`](docs/INTERVIEW_BRIEFING.md).

---

## ⚡ Try it in 30 seconds

| Surface | URL | Try this |
|---|---|---|
| 📱 **Live PWA** | <https://pathways-iota.vercel.app/> | Installable on iOS + Android home screens. Forest + Marigold palette, bilingual UI, four quick-start chips. Resource cards with a Leaflet map view above them on geo queries. |
| 🩺 **API health** | <https://prathik10-pathways.hf.space/health> | Returns `{"status":"ok","version":"1.0.0", "channels":["sms","web"], "modules":["dashboard","parole_reminders","writeback","audit"]}` |
| 📚 **OpenAPI / Swagger** | <https://prathik10-pathways.hf.space/docs> | Interactive. Try `/_debug/invoke` with `{"message":"Can I vote in Texas if I'm on parole?"}` |
| 📊 **Caseworker dashboard** | <https://prathik10-pathways.hf.space/dashboard/> | Token-gated. Demo mode accepts any `Authorization: Bearer <anything>`. Anonymized aggregates only; no PII ever stored. Includes per-turn map-engagement counts as of Phase 7. |
| 🧠 **Architecture deep-dive** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Why each Claude Code primitive is load-bearing in a safety-critical domain |
| 🎬 **Per-primitive walkthrough** | [`docs/SHOWCASE.md`](docs/SHOWCASE.md) | Code-trace tour: see exactly what a Skill, sub-agent, hook, and MCP server look like in practice |
| 📓 **Dev journal** | [`docs/JOURNAL.md`](docs/JOURNAL.md) | Public build log, seven phases, every shipped feature dated |
| 🎓 **Interview briefing** | [`docs/INTERVIEW_BRIEFING.md`](docs/INTERVIEW_BRIEFING.md) | Cold-readable study guide: 60-second pitch, Claude Code primitives section by section, rehearsal Q&A |
| 💬 **Sample conversations** | [`examples/sample_conversations.md`](examples/sample_conversations.md) | 5 fully-annotated SMS dialogues end-to-end |

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

## What's shipped vs. deferred

| Concern | Status |
|---|---|
| LangGraph state machine (7 nodes; intake → retrieve → match → draft → audit → send/escalate; bounded revision loop) | **Real** |
| 7 Skills + 4 sub-agents + 3 hooks (`.claude/`) | **Real**; plugin-installable via `claude plugin install .` |
| `pathways-corpus` MCP server (BM25 + optional hybrid retrieval) | **Real**, 95 curated entries (federal CFR + TX statutes + NICCC) |
| `tx-resources` MCP server (geo-aware nearby ranking) | **Real**, ~880 records after HRSA + curated orgs ingest; covers all 254 TX counties |
| Multi-turn intake with checkpointer (Phase 1) | **Real**, Postgres-backed in prod, in-memory in tests |
| Twilio webhook + signature verification + TCPA STOP/HELP/START (Phase 1) | **Real**, trial-mode aware |
| Spanish + multi-need routing + Spanish crisis hook patterns (Phase 3) | **Real** |
| PWA channel at `/web/*` + React 19 installable PWA (Phase 4) | **Real**, [live on Vercel](https://pathways-iota.vercel.app/) |
| Leaflet + OpenStreetMap resource-map view above the cards with Google Maps deep-link (Phase 7) | **Real**, self-gates when no resource has coordinates; HRSA + curated metro entries pin in production |
| Per-turn map-engagement analytics: `resources_with_coords_count` column + `map_pins_total` / `turns_with_map_view` summary aggregates + structured `web_turn_map_metrics` log line (Phase 7) | **Real** |
| CI auto-deploy of `main` to the HF Space via `.github/workflows/deploy-hf.yml` (Phase 7) | **Real**, force-push + 10-min `/health` poll, needs `HF_TOKEN` repo secret with write scope |
| Provider-pluggable LLM (`pathways/llm/`) with Anthropic default + Gemini fallback (Phase 5) | **Real** |
| Eval harness with 73 frozen scenarios + CI gate (Phase 5) | **Real**, crisis category must be 100% to merge |
| Hybrid retrieval (BM25 + BGE-small dense, RRF fusion; opt-in) | **Real**, falls back to BM25 if sidecar or sentence-transformers missing |
| Caseworker dashboard at `/dashboard/*` (Phase 5b) | **Real**, per-partner bearer auth + region scoping; demo mode for recruiter clicks |
| Opt-in parole-reporting reminder (Phase 6) | **Queued**: API + intake hook + admin cron endpoint shipped; actual SMS send waits on the forward `thread_id → phone` map (see below) |
| Anonymous monthly trend reports as Markdown export (Phase 6) | **Real**, `GET /dashboard/api/report.md` |
| NGO write-back queue (Phase 6) | **Queued**: API + queue table shipped; actual SMS send waits on the same phone map |
| MMS photo extraction of TDCJ release packet | **Deferred** ([`docs/PHASE6_DEFERRED.md`](docs/PHASE6_DEFERRED.md)): blocked on paid Twilio MMS + Claude vision spend |
| Warm-transfer voice connect | **Deferred** ([`docs/PHASE6_DEFERRED.md`](docs/PHASE6_DEFERRED.md)): blocked on paid Twilio Voice |
| Forward `thread_id → phone` resolver (encrypted) | **Deferred** ([`docs/PHASE6_DEFERRED.md`](docs/PHASE6_DEFERRED.md)): three lines from unblocking real-world send for both shipped queues |

## What's next

The technical surface is comprehensive. What it needs now is real users and real feedback.

**Operator-side wiring left to do** (~half a day):
1. Set `PATHWAYS_ADMIN_TOKEN` on the HF Space and add a daily GitHub Actions cron to POST to `/admin/run-parole-reminders`.
2. Set `HF_TOKEN` (write-scope HF access token) as a repo secret so `.github/workflows/deploy-hf.yml` can push merges to the HF Space automatically; then `gh workflow run deploy-hf.yml --ref main` once to fire the first sync.
3. Wire the forward phone map (`pathways/sessions/phone_map.py` with a small `session_phones` table; encrypt with `PATHWAYS_PHONE_ENCRYPTION_KEY`). Until this is in place, both parole reminders and NGO write-back persist in their queues and the daily cron reports `skipped_no_phone` honestly.
4. Geocode the demo seed at `mcp_servers/tx_resources/resources.json` (one-line-per-entry lat/lon enrichment for the metro-Houston and metro-DFW rows) so the Phase 7 map view also renders against the seed catalog in pure-demo mode. Production already pins via the HRSA + curated metro ingest.

**Then partner outreach.** The dashboard exists so partner NGOs can see what's flowing through their region; that conversation is what unlocks pilot users.

**Deferred-with-design.** MMS extraction and warm-transfer voice are documented in [`docs/PHASE6_DEFERRED.md`](docs/PHASE6_DEFERRED.md) with their blockers and unblock criteria. Both gate on paid Twilio features.

## Why I built this

A Claude Code architecture is most interesting when the *cost of being wrong* is high. Reentry is one of those domains. The same primitives — Skills for domain workflows, sub-agents for bounded capability, hooks for deterministic safety, MCP for swappable integration — apply directly to healthcare (where I do this professionally at MMI) and any other regulated context. This repo is the public, non-confidential expression of that architecture.

## License

Apache 2.0. See `LICENSE`. The NICCC content excerpts seeded in `mcp_servers/pathways_corpus/corpus.json` are public-domain federal data.

## Contact

Prathik Ravichandran — prathik.ravichandran.work@gmail.com — [LinkedIn](https://www.linkedin.com/in/prathik-ravichandran/)
