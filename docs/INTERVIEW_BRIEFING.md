# Pathways — Interview Briefing

A complete study guide for explaining this project in interviews. Written for the case where the interviewer's only focus is "tell me how you used Claude Code." Read top-to-bottom once. Then re-read sections 5 and 13 until you can answer cold.

---

## 0. The 60-second pitch

> Pathways is a Texas reentry navigator. When someone leaves prison in Texas, they have about 72 hours to figure out housing, food, an ID, and benefits before things spiral. The information that resolves those questions exists, but it is fragmented across federal, state, county, and city agencies and most of it is written for lawyers. Pathways is the layer in between. A returning citizen texts a number, gets a trauma-informed conversation that collects the bare minimum, retrieves cited Texas law and a verified directory of organizations, and replies in plain language with phone numbers they can actually call.
>
> I built it as a reference architecture for Claude Code primitives in a safety-critical domain. Seven progressive-disclosure Skills handle the domain protocols. Four capability-scoped sub-agents handle the bounded work. Three deterministic hooks enforce safety properties the model cannot be trusted with. Two MCP servers wrap the data layer. All of that sits on an explicit LangGraph state machine with seven nodes so every transition has a name and every safety check has a layer. Three audiences share the same backend: a returning citizen on SMS, the same person on a PWA, and a partner caseworker on an anonymized dashboard.
>
> It is live, deployed to Hugging Face Spaces and Vercel, with 305 unit tests and 73 frozen eval scenarios gating every merge. Crisis category is held to 100% pass rate.

That paragraph is your default answer to "tell me about this project." Memorize the shape, not the words.

---

## 1. Why Pathways exists

**Problem statement.** Texas runs the largest state prison system in the country. Tens of thousands of releases per year, across 254 counties and 28 workforce regions. The first 72 hours after release are dense with decisions: where to sleep tonight, how to get an ID without an ID, how to report to parole, whether your drug felony actually disqualifies you from SNAP. The information that answers any of these exists. It is fragmented across federal CFR sections, Texas statutes, Texas Administrative Code, agency policies, and county-level procedures.

**The asymmetry that drove the design.** Confident-wrong answers cost more than honest-unknown answers. If someone is told their drug felony disqualifies them from SNAP, they walk away from food they qualify for. If someone in crisis gets a polite list of resources instead of the 988 line, that is a failure that matters. Pathways had to fail into "I am not sure, here is a human" much more often than into "here is a confident answer." That is the entire engineering posture.

**Why Texas only.** State-agnostic systems that pretend to cover all 50 states produce confidently-wrong cross-state answers because their corpus is shallow per state. Deep coverage of one state is more useful than shallow coverage of fifty. Architecture is portable to other states once the domain corpus is curated.

**Why SMS first.** The primary user is reading on whatever phone they have, possibly a basic prepaid Android with no data. SMS works on every device shipped in the last 20 years. The PWA and dashboard came later as Phase 4 and Phase 5b once the SMS path was solid.

---

## 2. System architecture at a glance

```
┌─────────────────────────────────────────────────────────────────────┐
│                       THREE AUDIENCES                                │
├─────────────────────────────────────────────────────────────────────┤
│  Returning citizen on SMS   │   Same person on PWA   │  Caseworker │
│  (Twilio webhook)           │   (React + Vite)       │  (dashboard) │
└──────────┬──────────────────┴────────────┬───────────┴──────┬──────┘
           │                                │                  │
           ▼                                ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FASTAPI INGRESS                               │
│  /sms (Twilio HMAC)   │   /web/session, /web/turn   │   /dashboard/ │
└─────────┬───────────────────────────┬───────────────────────┬───────┘
          │                           │                       │
          │ all three converge here   │                       │
          └────────────┬──────────────┘                       │
                       ▼                                      │
┌─────────────────────────────────────────────────────────────────────┐
│                   LANGGRAPH STATE MACHINE                            │
│                                                                      │
│   intake ──► retrieve ──► match ──► draft ──► audit ──► send        │
│      │                                          │                    │
│      ▼ crisis hook fired                        ▼ hard_block         │
│   escalate ◄────────────────────────────────────                     │
│                                                                      │
│   Pluggable checkpointer (memory | sqlite | postgres) keyed by      │
│   salted-SHA-256 thread_id (ph_<hash> for SMS, web_<uuid> for PWA)  │
└─────────────┬───────────────────────────────────────────────┬───────┘
              │                                               │
              ▼                                               ▼
┌─────────────────────────────────┐         ┌─────────────────────────┐
│  TWO MCP SERVERS                 │         │  ANALYTICS + AUDIT      │
│  pathways-corpus (95 entries)   │         │  conversation_events    │
│  tx-resources (18+ ingestable)  │         │  audit_events (full)    │
│  BM25 default, hybrid optional  │         │  parole_reminders       │
└─────────────────────────────────┘         └─────────────────────────┘
```

**Key invariants the diagram encodes.**

- Three input channels, one backend. The graph never knows which channel it came from beyond a `channel` field used only by the draft node for formatting.
- Every node has a name. No "agent figures it out" boxes. Every transition is testable in isolation.
- Safety lives at the layer that can actually enforce it. Crisis detection runs upstream of the model. Confidence gating runs downstream of retrieval. PII redaction runs before any write. None of these can be skipped by the model under context pressure.
- Capabilities narrow as you descend the stack. Main session has the most permissions. Sub-agents have fewer. The compliance auditor sub-agent literally cannot retrieve new citations to justify a weak claim — that is the kind of thing that ruins audits in general.

---

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph (explicit StateGraph, 7 nodes) | Auditability and targeted intervention. Rejected: single super-prompted agent (audit step can't be optional), tight Python pipeline (no model reasoning), CrewAI (less explicit edge model). |
| Backend | FastAPI + Pydantic | One server hosts SMS webhook + PWA backend + caseworker dashboard. Pydantic models double as state contracts. |
| LLM | Claude (Anthropic) primary, Gemini fallback | Pluggable via `get_llm(role)`; three roles (`fast`, `smart`, `audit`) each pick a model. Demo mode runs deterministic templates when no API key is set. |
| Retrieval | BM25 default; BM25 + BGE-small hybrid optional | BM25 over 95 entries is fast, deterministic, and free. Hybrid swaps in semantic match via Reciprocal Rank Fusion when paraphrase queries hit. |
| Embeddings | BAAI/bge-small-en-v1.5 (384-dim, cosine) | Pre-embedded at Docker build time into a `.npy` sidecar so the container boots without a runtime model download. |
| State persistence | LangGraph PostgresSaver | Memory / sqlite / postgres backends selected by `PATHWAYS_CHECKPOINT_BACKEND`. Salted SHA-256 thread IDs. |
| Database | Supabase Postgres (free tier) | Hosts checkpoints, audit log, conversation analytics, parole reminders, phone map (encrypted). pgvector extension enabled for the hybrid path. |
| SMS | Twilio (free trial) | HMAC-SHA1 webhook signature verification, MessageSid idempotency, TCPA STOP/HELP/START handling. |
| Frontend | React 19 + Vite 6 + Tailwind 3 + Framer Motion + Leaflet + vite-plugin-pwa | Single-page PWA installable on iOS / Android home screens. Offline-first via Workbox NetworkFirst on `/web/turn`. |
| Backend host | Hugging Face Spaces (Docker SDK, free) | One container exposes port 7860. Auto-deploy from `main` via the new `deploy-hf.yml` workflow. |
| Frontend host | Vercel (Hobby, free) | Auto-deploys from `main` and produces PR previews. |
| CI | GitHub Actions (5 workflows) | ci.yml (pytest matrix), evals.yml (gating evals), daily-cron.yml (admin endpoint hits), refresh-data.yml (weekly ingester), deploy-hf.yml (auto-push to HF). |

The principle behind every choice: zero spend. Pathways is a non-profit demonstration funded personally; nothing in the stack costs money to run.

---

## 4. The Claude Code primitives (the interview gold mine)

This is the section to memorize. The interviewer will ask about each of these specifically. The pattern for every answer: name the primitive, name the problem it solves, name the trade-off it bought.

### 4.1 Skills (7 progressive-disclosure protocols)

Skills are not just prompts. They are domain protocols that load by description match, not by being baked into a system prompt. Loading them on demand keeps the active context small and the behavior predictable. All seven Skills live under `.claude/skills/<name>/SKILL.md`.

| Skill | Loads when | What it does | Why it's its own Skill |
|---|---|---|---|
| `intake-assessment` | New conversation, no prior state | Trauma-informed first touch. Collects minimum routing info (name, ZIP, top need) across multiple turns. Explicitly avoids asking for legal name, SSN, DOB, full address in the first three exchanges. | First-touch protocol is high-leverage and bears no resemblance to the downstream Skills. Separating it lets the intake node load only this Skill and not pull in 6 unrelated playbooks. |
| `crisis-response` | Hook-triggered (never user-triggered) | Suspends normal navigator workflows, routes to 988 / 211 / DV-hotline based on crisis category. Shorter messages, sustained presence, no resource list dumps. | Crisis must override every other Skill regardless of what the user said before. Hook-forced loading is the cleanest way. |
| `niccc-lookup` | Legal rule / eligibility / "can I" questions | Wraps the `pathways-corpus` MCP server with citation discipline, confidence gating, and explicit handoff when retrieval is weak. Every factual claim cites a corpus entry. | The Skill encodes the discipline ("don't claim what you can't cite"). The MCP server is the data; the Skill is the policy. |
| `housing-pathway` | Housing / shelter / public housing / fair-chance | Cross-references `tx-resources` (find local options) with `pathways-corpus` (HUD rules, fair-chance housing law). Routes time-sensitive shelter to 211. | Housing is the most time-pressured of the categories. A separate Skill lets the model load specific urgency cues. |
| `employment-pathway` | Jobs / who-hires / occupational licensing | Distinguishes three different employment questions (job search, license eligibility, fair-chance employer list) and routes each correctly. | Three failure modes (recommend the wrong path, miss a license disqualifier, mislead on TWC programs); having a Skill makes the disambiguation explicit. |
| `record-clearing-tx` | Expungement / sealing / non-disclosure | Walks the Texas eligibility structure (CCP Ch. 55 expunction vs. Gov Code Ch. 411 non-disclosure). Always routes to legal aid for the final determination. | Easy to make confident-wrong claims here ("you'll probably get yours granted"). Separate Skill forces criteria-not-prediction language. |
| `benefits-navigator` | SNAP / Medicaid / TANF / SSI / SSDI | Corrects the single most damaging misconception in Texas reentry: the false belief that a drug felony permanently bars SNAP (Texas opted out of the federal lifetime ban in 2015). | The misconception is so common that a separate Skill exists specifically to surface the correction. |

**The non-obvious design choice that impresses interviewers.** Skills load by description match, not by routing logic in code. The router does not call `load_skill("housing-pathway")`. Instead, the Claude session sees descriptions for all seven Skills, and the model decides which to load based on the conversation. Domain experts can ship a new Skill (write the SKILL.md, give it a good description) without touching the routing code.

**The skill body shape.** Every SKILL.md has:
- YAML frontmatter (name, description, optional `allowed-tools` to scope what the Skill can call)
- A trigger description (what user messages should match)
- A protocol body (what to do step by step)
- Stigma-aware language guidance and SMS-shaping rules

### 4.2 Sub-agents (4 capability-scoped assistants)

Sub-agents are bounded assistants that run with a narrower permission envelope than the main session. They live at `.claude/agents/<name>.md`. Each gets a fresh context, a stated input, a stated output, and a stated set of allowed tools.

| Sub-agent | Spawned by | Input | Output | Why isolated |
|---|---|---|---|---|
| `compliance-auditor` | The audit node, before any reply touching legal or eligibility content ships | Draft reply text + the retrievals that should back it | Verdict: `pass` / `soft_block` (with rewrite hint) / `hard_block` (with reason) + issues list | The auditor literally cannot fetch new citations. If a claim isn't backed by the retrievals already in state, soft_block. Forces the upstream draft to do the right thing the first time. |
| `eligibility-checker` | The graph when a specific named program is in scope | Intake state + program name | Deterministic eligibility verdict (`eligible` / `ineligible` / `unclear`) with the rule cited | Pulls one Skill (`niccc-lookup`) and one MCP tool (`get_citation`). Cannot phrase outcomes as predictions. |
| `resource-matcher` | Match node when the rule-based ranker needs a second pass | Client profile (need + location + supervision status) | Ranked list of local resources | Read-only on `tx-resources`. No corpus access, no writes. |
| `caseload-summarizer` | Only when a partner caseworker asks for aggregate data | Time window + scope filter (workforce_region / county) | Anonymized aggregate (counts, percentages, no names) | The ONLY path to cross-conversation data. Runs in isolation from any user session. Cannot read individual conversations. |

**The narrowing principle.** Main session > Skills > sub-agents > specific tools. Permissions narrow as you descend. The compliance auditor cannot retrieve more citations to justify a weak claim. The resource matcher cannot read the corpus. The caseload summarizer cannot read any single conversation. This is what makes the audit story believable.

### 4.3 Hooks (3 deterministic safety enforcers)

Hooks are the things that cannot be trusted to the model. They are Python scripts that the harness runs at specific lifecycle events. They live at `.claude/hooks/*.py` and are bound via `.claude/settings.json`.

| Hook | Event | What it does | Why outside the model loop |
|---|---|---|---|
| `crisis_keyword_check.py` | `UserPromptSubmit` (matcher: `.*`) | Regex-scans every user message for crisis signals: suicide, self-harm, substance, domestic violence, violence to others, sexual violence, housing emergency. English + Spanish patterns with accent tolerance. Sets a state flag that the intake node short-circuits on. | The model under context load might rationalize away a crisis signal as "not really a crisis." Regex cannot rationalize. Misses cost lives. |
| `pii_redact.py` | `PreToolUse` (matcher: `Write\|Bash\|mcp__pathways-postgres__.*`) | Redacts SSN, driver license, state ID, TDCJ inmate number, phone, email, DOB, street address, case number before any write path executes. Includes an allowlist for crisis hotlines (988, 211, SAMHSA, RAINN) so those aren't redacted from outbound replies. | Once PII reaches the draft node, it has already been touched. Redaction has to happen before the write. The hook is the only place that fires before every write. |
| `rag_confidence_gate.py` | `PostToolUse` (matcher: `mcp__pathways-corpus__search_corpus\|mcp__tx-resources__.*`) | Reads the confidence score on every retrieval. If below `PATHWAYS_CONFIDENCE_FLOOR` (0.62), rewrites the tool output to a structured handoff payload that forces the drafting node to say "I don't know this one, let me connect you to legal aid." | The model that drafted the query is biased toward considering its retrieval good. A separate layer evaluates the score and gates the downstream node. |

**Why settings.json matters.** The hook binding lives in `.claude/settings.json`:

```json
"hooks": {
  "UserPromptSubmit": [
    { "matcher": ".*", "hooks": [{ "type": "command",
        "command": "python .claude/hooks/crisis_keyword_check.py" }] }
  ],
  "PreToolUse": [
    { "matcher": "Write|Bash|mcp__pathways-postgres__.*",
      "hooks": [{ "type": "command",
        "command": "python .claude/hooks/pii_redact.py" }] }
  ],
  "PostToolUse": [
    { "matcher": "mcp__pathways-corpus__search_corpus|mcp__tx-resources__.*",
      "hooks": [{ "type": "command",
        "command": "python .claude/hooks/rag_confidence_gate.py" }] }
  ]
}
```

The matcher is the contract. Crisis fires on every prompt. PII redaction fires on every write path. Confidence gating fires after every retrieval call. The model cannot bypass any of these.

**Deterministic vs. probabilistic.** All three hooks are deterministic Python regex / arithmetic. There is no LLM in the safety path. That is the single most important design decision in the project.

### 4.4 MCP servers (2 domain-bounded data tools)

MCP (Model Context Protocol) is how Claude integrates with external services. Pathways has two MCP servers, both stdio-transport, both running as subprocesses spawned by the Claude session. They live at `mcp_servers/pathways_corpus/server.py` and `mcp_servers/tx_resources/server.py`.

**pathways-corpus** — the knowledge base.
- Tools exposed: `search_corpus(query, category=None, top_k=5)`, `get_citation(citation_id)`, `list_categories()`.
- Data: 95 hand-curated corpus entries (Texas statutes, NICCC collateral consequences, federal CFR sections relevant to reentry).
- Sources: Texas State Law Library research guide, NICCC inventory, Texas statutes via statutes.capitol.texas.gov, U.S. Code, HUD regulations.
- Backend switch: `BACKEND=file` reads `corpus.json`; `BACKEND=postgres` reads the `corpus` table.
- Returns confidence-scored results that the `rag_confidence_gate` hook evaluates.

**tx-resources** — the directory.
- Tools exposed: `find_resources(topic=None, category=None, region=None)`, `find_resources_nearby(near_zip, category=None, top_k=5)`, `get_resource(resource_id)`, `list_categories()`.
- Data: hand-curated reentry organizations, plus 832 active Texas FQHCs (federally qualified health centers) ingestible via `scripts/ingest_hrsa_fqhcs.py`.
- Geo: `find_resources_nearby` haversine-ranks resources from the user's ZIP centroid (2,600 TX ZIPs vendored from GeoNames), with a statewide fallback (211 Texas always reachable) so every reply has at least one phone number.

**Why MCP servers instead of direct DB clients.** The MCP boundary is what lets the same Skill code run in a development session (with mocked tools), in production (against Postgres), in tests (against in-process file backends), and from another agent's session entirely. Same tool contract, different backend. The graph never knows or cares.

### 4.5 Settings, rules, and CLAUDE.md (the policy layer)

**`.claude/settings.json`** — capability envelope and hook bindings.

The permissions block has three buckets:
- `allow`: things the model can do freely (`Read`, `Grep`, `Glob`, specific WebFetch domains for ground-truth verification, the two MCP servers' tools).
- `deny`: things the model cannot do regardless of permission prompts (`rm`, `curl`, `wget`, `Write` on `/etc/**`, `.ssh`, `.env*` files).
- `ask`: things that require explicit confirmation (`Write`, `Edit`, `Bash`, and crucially `mcp__twilio-sms__send_sms` — the HITL gate on any outbound SMS).

`allowManagedHooksOnly: true` means only the hooks declared in this settings file can run; user-installed hooks are ignored.

**`.claude/rules/*.md`** — three rule files loaded into every Claude turn as policy:
- `citations.md`: citation formatting (inline § references, hyperlinked when the corpus entry has a URL, never invent a section number).
- `compliance.md`: hard constraints (citation discipline, TX-only scope, roles you do not occupy, no outcome predictions, PII handling, handoff posture).
- `tone-and-trauma-informed.md`: SMS-shape, sixth-grade reading level, stigma-aware language, no moralizing / minimizing / false reassurance.

**`CLAUDE.md`** — the operating constitution at repo root. Five hard rules at the top:
1. Cite or don't claim.
2. You are not a lawyer.
3. You are not a clinician.
4. Texas only.
5. HITL gate on anything financial or legal.

Plus a routing table (which Skill loads for which user intent) and sub-agent capability descriptions.

**Why this matters in interviews.** Most CLAUDE.md files are documentation. This one is enforcement. The hard rules tie back to specific architectural mechanisms: rule 1 is enforced by the compliance-auditor sub-agent and `rag_confidence_gate` hook; rule 5 is enforced by the `ask` permission on `mcp__twilio-sms__send_sms`. The constitution is wired to the harness.

### 4.6 The plugin manifest (the distribution story)

`.claude/plugin.json` packages everything above as a redistributable Claude Code plugin. One command (`claude plugin install .`) loads:
- 7 Skills
- 4 sub-agents
- 3 hooks
- 2 MCP servers
- 3 rule files
- The settings.json policy envelope

This is what lets the Pathways architecture port to another organization's deployment. The plugin is the unit of distribution.

---

## 5. The LangGraph state machine (node-by-node)

The graph is built with `StateGraph(PathwaysState)`. Seven nodes, three conditional edges. Every node has a stated input, a stated output, and a stated failure mode.

```
START → intake ─┬─► (crisis fired) ────────► escalate ─► END
                ├─► (slot missing)  ────────► END  (slot prompt shipped)
                └─► (all slots done) ──► retrieve ─► match ─► draft ─► audit
                                                                       │
                            ┌──────────────────────────────────────────┤
                            │                                          │
              (soft_block, budget left) (pass)            (hard_block)│
                            │             │                            │
                            ▼             ▼                            ▼
                          draft           send → END                 escalate → END
```

**1. intake.** Multi-turn slot-filling. Three required slots: name, location (ZIP or city), top need. Asks one per turn. Merges extracted fields into a persistent `IntakeProfile` with one strict rule: never overwrite a filled field with `unknown`. Crisis hook short-circuit: if `state.crisis.fired`, immediately route to escalate with no slot-filling.

**2. retrieve.** Maps the top need to a corpus category and query. Calls the hybrid or BM25 retriever (selected by env var). Sets `retrieval.gated_low_confidence = True` if confidence is below 0.62 so the draft node knows to handoff.

**3. match.** Multi-need-aware resource matching. Iterates over `top_need` plus `secondary_needs`. For each, tries nearby (with ZIP) → regional → statewide → topic fallback. Dedupes by org ID across needs. Always appends 211 Texas as a safety net so every reply has at least one phone number. Caps at 6 for SMS readability.

**4. draft.** Generates the user-facing reply. LLM call when API key is present, deterministic template otherwise. Bilingual (EN / ES). Channel-aware: reads `state.channel` and formats plaintext for SMS, markdown + resource cards for web.

**5. audit.** Compliance check. LLM-based when API key is present, rule-based fallback otherwise. Returns `pass` / `soft_block` (rewrite hint included) / `hard_block` (escalate). Soft block loops back to draft with a revision budget of 2; if exhausted or hard block, route to escalate.

**6. escalate.** Category-specific crisis messages (988 for suicide, 211 for housing emergency, etc.) or generic handoff (TRLA + 211). Sets `escalated_to_human = True`.

**7. send.** Promotes `draft_response` to `final_response`. Appends the parole reminder offer if supervision is parole and the offer hasn't been made yet. The graph terminates here on the happy path.

**The non-obvious design choice.** Soft-block loop has a hard budget of 2 revisions. Why a budget? Because without it, an audit-draft cycle could thrash indefinitely on a borderline claim. With it, after 2 failed revisions the system gives up and hands off to a human. That is the safe-failure principle made concrete.

---

## 6. Data pipeline

### 6.1 The corpus

`mcp_servers/pathways_corpus/corpus.json` has 95 hand-curated entries. Each entry:

```json
{
  "id": "tx-occ-53-021",
  "citation": "Texas Occupations Code § 53.021",
  "summary": "Plain-language paraphrase of when a license can be denied for a prior conviction.",
  "url": "https://statutes.capitol.texas.gov/...",
  "category": "employment",
  "subcategory": "occupational_licensing",
  "tags": ["license", "conviction", "denial"],
  "state": "TX",
  "source": "tx_statute",
  "last_verified": "2026-05-15"
}
```

**Sources.** Texas State Law Library research guide, NICCC inventory, Texas statutes (statutes.capitol.texas.gov), U.S. Code (uscode.house.gov), HUD regulations. Four entries are flagged `source=general_knowledge_tx_statute` — author's best-effort summaries pending re-verification.

**Disclaimer baked in.** Every corpus response carries: "This corpus is for navigation purposes only and is not legal advice. Statutory text changes; verify current language at the cited source before relying on any entry."

### 6.2 The resource directory

`mcp_servers/tx_resources/resources.json` has 18 hand-curated reentry organizations as the demo seed. The production deploy ingests 832 active Texas FQHCs from the HRSA public dataset via `scripts/ingest_hrsa_fqhcs.py`, plus 30 hand-verified metro orgs filling gaps (Austin: ARCH, Caritas, Goodwill CTX; San Antonio: Haven for Hope, SA Food Bank; El Paso: Opportunity Center; RGV: Food Bank RGV; DFW: The Bridge, North TX Food Bank; etc.).

Each resource entry has phone, URL, eligibility text, languages, topics, lat/lon (sparse — statewide hotlines have none), county, workforce region, `accepting_clients` flag, `last_verified`, `stale` flag.

### 6.3 Embeddings + hybrid retrieval

The retriever has two backends, picked by `PATHWAYS_RETRIEVAL_BACKEND`:

**BM25 (default).** BM25Okapi over `{citation + summary + tags + subcategory}`. Lowercase tokenize, strip punctuation, split on whitespace. Deterministic, fast, no embeddings overhead.

**Hybrid (opt-in).** BM25 (top 20) + BGE-small dense (top 20), fused via Reciprocal Rank Fusion. RRF params: `k=60` (Cormack et al. 2009). Confidence is the top fused score normalized against the idealized maximum (`2 / (k+1)`).

Embeddings are pre-computed via `scripts/embed_corpus.py` and persisted as `mcp_servers/pathways_corpus/corpus_embeddings.npy` (~150 KB for 95 entries). The Dockerfile runs this step at build time so the container boots without a runtime model download.

If sentence-transformers is missing or the sidecar doesn't exist, the hybrid retriever silently falls back to BM25. The caller never knows.

**Why hybrid matters.** BM25 wins exact-keyword queries ("Tex. Gov. Code 411.072"). The dense leg wins paraphrases ("how do I clear my record" should match the expunction corpus entry even though the words don't overlap with the statutory phrasing). For users who don't know the legal vocabulary, the dense leg catches what BM25 drops.

### 6.4 Geo

`pathways/geo/zips.py` loads a vendored CSV of ~2,600 Texas ZIP centroids (from GeoNames), cached with `lru_cache`. Three public functions:
- `zip_to_coords(zip5) → (lat, lon)`
- `county_for_zip(zip5) → "Harris"`
- `workforce_region_for_zip(zip5) → "Gulf Coast"`

The third composes through a hand-curated map of all 254 Texas counties to the 28 Texas Workforce Commission regions. Why does that matter? Different workforce regions have different programs, different reentry coordinators, and different intake offices. ZIP-aware routing is the difference between "here is a phone number 200 miles away" and "here is the office in your county."

### 6.5 Refresh + stale handling

`.github/workflows/refresh-data.yml` runs `python -m scripts.refresh_data` weekly (Monday 09:00 UTC). The orchestrator runs each ingester in order:
1. `scripts.ingest_hrsa_fqhcs` (source: `hrsa_fqhc`, stale after 30 days)
2. `scripts.curate_corpus` (source: `curated_federal_and_tx`, stale after 180 days)
3. `scripts.curate_metro_orgs` (source: `curated_metro`, stale after 90 days)

After all ingesters run, any row not refreshed in THIS cycle is marked `stale = TRUE`. The Postgres MCP backends filter on `WHERE stale = FALSE` at read time. That means a row whose source went silent for two refresh cycles automatically disappears from the user-facing path without anyone noticing. Safety property: never surface a phone number that hasn't been verified recently.

### 6.6 Postgres schema

| Table | Purpose | Notes |
|---|---|---|
| `langgraph_checkpoints` + `langgraph_checkpoint_blobs` | LangGraph state per `thread_id` | Created by `PostgresSaver.setup()`. Allows multi-turn resume across restarts. |
| `corpus` | Searchable Texas law corpus | Includes a pgvector embedding column for hybrid retrieval. `stale` flag for retention. |
| `resources` | Reentry organization directory | 31 columns including lat/lon/county/workforce_region/accepting_clients/stale. |
| `conversation_events` | Per-turn analytics (PII-scrubbed) | thread_id, channel, language, needs, region, county, supervision_status, retrieval_confidence, audit_verdict, escalated, matched_resource_count, **`resources_with_coords_count`** (new in PR #1), user_message_length (int only), reply_length (int only), crisis_fired, intake_complete. |
| `audit_events` | Operator-side full-content log | Fernet-encrypted payload. Schema: `(thread_id TEXT, ts TIMESTAMPTZ, payload BYTEA)`. Indexes for `(thread_id, ts DESC)` and `(ts)` for retention purge. 180-day default retention. |
| `inbound_message_dedup` | Twilio MessageSid dedup | PRIMARY KEY on MessageSid. INSERT ... ON CONFLICT DO NOTHING. |
| `parole_reminders` | Opt-in reminder queue | thread_id + check_in_date + reminder_state. |
| `session_phones` | Encrypted thread_id → phone map | Fernet at rest. Currently scaffolded; populated by SMS handler when wired. |

---

## 7. Multi-channel implementation

### 7.1 SMS path (`POST /sms`)

The order of operations matters and is worth memorizing:
1. **Twilio HMAC-SHA1 verification.** `X-Twilio-Signature` header + form params + auth token. Fail → 403. Bypass via `PATHWAYS_SKIP_TWILIO_SIG=1` in tests.
2. **Field extraction.** `Body`, `From`, `MessageSid`.
3. **Thread ID derivation.** `thread_id_for_phone(From)` → `ph_<first-32-hex-of-sha256(salt + normalized_phone)>`. Raw phone never persisted as a primary key.
4. **Compliance keywords.** STOP / STOPALL / UNSUBSCRIBE / CANCEL / END / QUIT → mark opted-out, return static TwiML. START / UNSTOP / YES → clear opt-out. HELP → return help text. All deterministic regex; no model in this path (TCPA requirement).
5. **Opt-out check.** Skip everything else if opted out.
6. **Idempotency.** `seen_message_sid(MessageSid)` → atomic INSERT … ON CONFLICT DO NOTHING. Twilio retries within seconds; without this, the graph runs twice.
7. **Crisis check.** Replay the same `crisis_keyword_check.py` regex above the graph so the hook fires identically in production as in tests.
8. **Graph invocation.** `app.invoke({"session_id": thread_id, "user_message": Body, "crisis": crisis, "channel": "sms"}, config={"configurable": {"thread_id": thread_id}})`.
9. **Response.** TwiML XML wrapping the reply.

### 7.2 PWA path (`POST /web/session`, `POST /web/turn`)

**Session creation.** Client POSTs to `/web/session`. Server mints a UUID, derives `web_<uuid>` as the thread_id, returns both. Client persists `session_id` in localStorage (survives browser refresh).

**Turn.** Client POSTs `{session_id, message}` to `/web/turn`. Server validates session, runs opt-out / STOP / crisis check / graph invocation in the same order as SMS, then projects the final state into a typed `TurnResponse`:

```python
class TurnResponse(BaseModel):
    reply: str                          # markdown
    language: str                       # "en" | "es"
    intake_stage: Optional[str]         # None when intake is done
    needs: list[str]                    # top + secondary, dedup'd
    resources: list[ResourceCard]       # capped at 6
    escalated: bool
    escalation_reason: Optional[str]

class ResourceCard(BaseModel):
    id: str
    name: str
    description: Optional[str]
    phone: Optional[str]
    url: Optional[str]
    category: Optional[str]
    distance_miles: Optional[float]
    languages: list[str]
    lat: Optional[float]                # new in PR #1
    lon: Optional[float]                # new in PR #1
```

After shaping, the handler emits a structured log line: `web_turn_map_metrics thread=ph_abc... cards_total=N cards_with_coords=N map_renders=0|1 language=en`. This is the operator's per-turn signal for how often the map view actually renders.

### 7.3 PWA frontend (`web/`)

React 19 + Vite 6 + Tailwind 3 + Framer Motion + Leaflet + vite-plugin-pwa. Single-page chat with sticky header, install prompt (captures `beforeinstallprompt`, remembers dismissal), welcome screen on first load, animated message bubbles, resource cards with tap-to-call and visit-website actions, and the new map view above the cards when any resource has lat/lon.

**The map view (`src/components/ResourceMap.tsx`).** Self-gates on `pins.length === 0` returning null. Uses Leaflet `MapContainer` + `TileLayer` (OpenStreetMap tiles, no API key, no billing). Custom marigold drop-pin SVG via `L.divIcon`. `FitBounds` child component snaps the map to enclose all pins on mount. Popup on pin tap shows name + distance + "Open in Google Maps" CTA that deep-links via `https://www.google.com/maps/search/?api=1&query=...`. On iOS Safari / Android Chrome the URL opens the native Google Maps app when installed; otherwise the maps.google.com web page. No detection logic in the code.

**Service worker.** Workbox NetworkFirst on `/web/turn` — cache up to 50 entries for 24 hours so the user can reopen the PWA offline and see their last conversation.

### 7.4 Dashboard (`pathways/dashboard/`)

Read-only sub-app mounted at `/dashboard`, token-gated per partner NGO. The dashboard exists so partner organizations can see what is coming through Pathways in their region without having any access to individual conversations.

**The privacy property is load-bearing.** The dashboard cannot leak PII because the writer never persisted any in the first place. `event_from_state()` strips name, phone, raw ZIP, raw message text, and raw reply text before writing to `conversation_events`. The dashboard only reads from that table. PII-free by construction, not by access control.

**Auth.** Per-partner bearer tokens via `PATHWAYS_DASHBOARD_TOKENS_JSON` mapping each token to a name + scope. `hmac.compare_digest` for constant-time comparison. Demo mode accepts any bearer if no tokens are configured.

**Endpoints.** HTML landing page at `/dashboard/`; JSON endpoints at `/dashboard/api/summary`, `/dashboard/api/needs`, `/dashboard/api/confidence`, `/dashboard/api/escalations`, `/dashboard/api/recent`, `/dashboard/api/report.md` (the Markdown trend report partners can paste into a board newsletter).

### 7.5 The shared-backend pattern

The same `PathwaysState` flows through the same graph for SMS, PWA, and dashboard. Only `state.channel` differs. The draft node reads that field and picks plaintext-SMS or markdown-web formatting. Three audiences, one backend, zero code duplication. That is the architectural payoff for the upfront state-machine investment.

---

## 8. Safety architecture

Memorize this section. It is the single most differentiated part of the project.

**The principle.** The system should fail into "I am not sure, let me connect you with a human" much more often than into a confident wrong answer.

**The five layers, from upstream to downstream.**

| Layer | Mechanism | Failure mode it prevents |
|---|---|---|
| 1. Crisis | `crisis_keyword_check.py` hook on `UserPromptSubmit` | Crisis message rationalized away by the model as "not really a crisis." |
| 2. Confidence | `rag_confidence_gate.py` hook on `PostToolUse` for retrieval calls | Drafting node leaning on a weak retrieval to make a confident legal claim. |
| 3. PII | `pii_redact.py` hook on `PreToolUse` for writes | PII (SSN, DL, DOB, phone, address) reaching the database. |
| 4. Citation | `compliance-auditor` sub-agent + `audit` node + `rules/citations.md` | Statute claim shipped without a citation, or a citation that doesn't actually support the claim. |
| 5. HITL | `settings.json` `ask` block on `mcp__twilio-sms__send_sms` | Outbound SMS sent without explicit user confirmation. |

**Layered enforcement.** Each safety property is enforced at multiple layers. Citation discipline is enforced by the Skill protocol (loaded prompt), the audit node (graph), the compliance-auditor sub-agent (capability scope), the `rag_confidence_gate` hook (deterministic), and the `rules/citations.md` policy (always loaded). Five overlapping enforcement points. Any one of them missing the violation is fine because the others catch it.

**The audit trail.**
- Every hook returns metadata (name, action, inputs).
- LangGraph captures per-node state transitions.
- The compliance-auditor produces a verdict + issues list.
- The audit module persists full-content events (Fernet-encrypted) to a queryable Postgres table.
- The dashboard analytics module persists PII-scrubbed events to a separate table.

**Why deterministic and not LLM for crisis.** A returning citizen texts "I'm thinking about taking too many pills tonight." An LLM under context pressure might classify that as "ambiguous, ask a clarifying question." A regex cannot. Regex misses are deterministic and fixable (and have been fixed; see the dev journal for "took too many pills" being added after a live test caught the gap). LLM misses are stochastic and slow to detect.

---

## 9. Testing + evals

### 9.1 Unit tests

305 tests across 14 phase files (`tests/test_phase*.py`). Every phase test sets `PATHWAYS_CHECKPOINT_BACKEND=memory`, deletes `ANTHROPIC_API_KEY`, sets `PATHWAYS_SKIP_TWILIO_SIG=1`, and resets the checkpointer + graph + dedup ring + analytics store between tests. This is what makes the suite hermetic.

Phases are roughly:
- Phase 1: stateful intake + sessions
- Phase 2: geo + matching
- Phase 3: i18n + multi-need
- Phase 4: PWA web channel
- Phase 5: LLM provider switching + hybrid retrieval + eval harness
- Phase 5b: caseworker dashboard
- Phase 6: parole reminders + audit log + phone map
- Phase 7: map view (the work we just shipped)

### 9.2 Eval framework

`evals/runner.py` is the source of truth for "good." 73 scenarios across 11 categories. Two execution modes:
- **fast** (CI default): deterministic checks only, no API key needed.
- **full**: also evaluates LLM-judged checks (reply text, citation presence).

**Gating logic.** Crisis category must be 100% (single miss = merge blocked, because crisis is the safety floor). Overall pass rate must clear `PATHWAYS_EVAL_MIN_PASS_RATE` (CI: 0.95, local default: 0.90).

**The harness caught real bugs on its first run.** Crisis hook missed "took too many pills" → added the verb-form regex. Intake heuristic missed "report to my PO" → added the variant. Intake never extracted ZIP from message text → added the 5-digit TX-ZIP regex. The runner's projection read `intake.needs` which doesn't exist → fixed to combine `top_need + secondary_needs`. Four real bugs fixed in the first commit after the harness shipped. That is the entire point of an eval harness.

### 9.3 CI workflows

| Workflow | Trigger | Gates | Notes |
|---|---|---|---|
| `ci.yml` | push to main, PR to main | pytest across Python 3.11 + 3.12 | Demo mode, no API key |
| `evals.yml` | push to main, PR to main | crisis 100% AND overall >= 0.95 | Uploads `eval-results.json` artifact, retained 30 days |
| `deploy-hf.yml` | push to main, manual dispatch | Force-pushes to HF Space, polls /health for 10 min | Needs `HF_TOKEN` secret with write scope |
| `daily-cron.yml` | 14:00 UTC daily | Hits `/admin/run-parole-reminders` and `/admin/purge-audit-log` on the live Space | Needs `PATHWAYS_ADMIN_TOKEN` secret |
| `refresh-data.yml` | 09:00 UTC Mondays | Runs `scripts.refresh_data` (corpus + resources + HRSA) | Gated on `ENABLE_REFRESH=true` repo variable |

---

## 10. Deployment + ops

**Backend.** Hugging Face Spaces, Docker SDK, free tier, no cold starts. The Dockerfile pre-runs `scripts/embed_corpus.py --backend file` at build time so the BAAI/bge-small-en-v1.5 model (~130 MB) downloads once during build and the runtime container starts in seconds with a ~150 KB `corpus_embeddings.npy` sidecar. The container exposes port 7860 (HF Spaces convention) and runs `uvicorn pathways.api.main:api --host 0.0.0.0 --port ${PORT:-7860}`.

**Frontend.** Vercel Hobby tier. Auto-deploys from `main` and creates PR previews on every commit. Bundle is ~516 KB raw / ~161 KB gzipped including Leaflet.

**Database.** Supabase Postgres free tier. Hosts checkpoints, audit, analytics, parole reminders, phone map (encrypted). pgvector extension enabled.

**Auto-deploy pipeline (as of 2026-05-18).** Merge to `main` → Vercel rebuilds the PWA (~30 sec) + the new `deploy-hf.yml` workflow force-pushes to the HF Space (~5 min for Docker rebuild). Both surfaces refresh without manual intervention. One-time setup: `gh secret set HF_TOKEN` with a write-scope token.

**Admin endpoints.** `/admin/run-parole-reminders` (drains parole + writeback queues), `/admin/audit-log` (operator query), `/admin/purge-audit-log` (retention). All Bearer-token auth via `PATHWAYS_ADMIN_TOKEN` with `hmac.compare_digest` for constant-time comparison.

---

## 11. Future roadmap

**Shipped in Phase 6** (already live):
- Opt-in parole-reporting reminder (intake detects supervision=parole, draft appends offer, next turn parses YES + date, daily cron sends SMS day before)
- Anonymous monthly trend reports (`GET /dashboard/api/report.md`)
- NGO write-back queue (caseworker queues SMS to user by thread_id; phone never visible to caseworker)
- Caseworker dashboard with PII-scrubbed analytics

**Shipped in Phase 7** (already live):
- Map view above resource cards in the PWA, Leaflet + OpenStreetMap, Google Maps deep-link

**Deferred with documented design** (in `docs/PHASE6_DEFERRED.md`):

1. **MMS photo extraction of the TDCJ release packet.** User texts a photo of their release packet, Claude vision extracts structured fields, intake pre-fills in one shot instead of asking name → ZIP → need across four turns. Blocked: Twilio inbound MMS is paid ($0.01/msg) and vision API calls add ~$0.01 per parse. Unblock: partner sponsorship of Twilio + vision spend, or pilot evidence justifying the cost. Effort: ~4 days.

2. **Warm-transfer voice connect.** User replies CALL to an escalation, Pathways bridges the user and the partner NGO into a live call via Twilio Voice. Literature shows warm-transfer conversion is 2-3x cold referral conversion for reentry services. Blocked: Twilio Voice paid (~$50-130/mo at 100 transfers). Unblock: partner sponsorship. Effort: ~4 days.

3. **Forward phone map (dependency for both shipped queues).** Both parole reminders and writeback queue messages by `thread_id`, but neither can actually transmit until a `thread_id → phone` map is wired at the SMS handler. Schema is scaffolded (`session_phones` table with Fernet-encrypted phone). Three lines of code to wire. Currently both queues report `skipped_no_phone` in the daily cron.

**Sustainability (the personal-bill problem).** Pathways is funded out of pocket. Long-term paths under research: DOJ Second Chance Act grants, Reentry 2030 federal initiative, partner-organization fees for premium features (write-back, trend reports), individual donations via Open Collective, foundation funding (Arnold Ventures, Open Society, MacArthur), 501(c)(3) filing. No fundraising work starts until partner conversations are real.

---

## 12. The interview Q&A (the rehearsal section)

Read these out loud. Adjust the wording to your voice. The shape of the answer matters more than the exact words.

### 12.1 Opening questions

**"Tell me about Pathways."**
Use the 60-second pitch in section 0. End with: "Happy to go deeper on any layer — the Claude Code primitives, the safety architecture, the eval framework, or the deployment pipeline."

**"Why did you build this?"**
Two reasons that overlap. First, after moving to Houston for an Agentic AI Systems Engineer role at Medical Metrics, I wanted a public artifact that demonstrated how I use Claude Code in practice. Second, I wanted to build something useful for a population that needed it, not just an impressive demo. Reentry navigation in Texas was the territory where those overlapped. The first 72 hours after release are dense with bureaucratic decisions made under time pressure; the cost of confident-wrong information at that stage is unusually high. That asymmetry — where confident-wrong costs more than honest-unknown — is the exact thing a thoughtful AI architecture should handle better than an uncared-for chatbot.

**"Walk me through the architecture."**
Three audiences share one backend: a returning citizen on SMS, the same person on a PWA, and a partner caseworker on an anonymized dashboard. All three converge at a FastAPI ingress, which calls into an explicit LangGraph state machine — seven nodes: intake, retrieve, match, draft, audit, escalate, send. State is persisted by salted-SHA-256 thread ID via a pluggable checkpointer (memory, sqlite, postgres). The graph calls into two MCP servers — pathways-corpus for Texas law citations and tx-resources for the verified organization directory. Three deterministic Python hooks wrap the model with safety properties the model cannot be trusted with: crisis detection upstream, RAG confidence gating downstream of retrieval, PII redaction before any write. Seven Skills act as the domain protocols loaded on demand, four sub-agents handle bounded work like compliance auditing.

### 12.2 Claude Code specific questions

**"How did you use Skills?"**
Seven Skills, each a domain protocol. Intake-assessment is the trauma-informed first touch. Crisis-response is hook-triggered for crisis signals. Niccc-lookup wraps the corpus with citation discipline. Housing-pathway, employment-pathway, record-clearing-tx, and benefits-navigator each handle one domain category. The non-obvious part: Skills load by description match, not by routing logic in code. The router does not call `load_skill("housing-pathway")`. The Claude session sees descriptions for all seven, and the model decides which to load based on the conversation. Domain experts can ship a new Skill — write the SKILL.md, give it a good description — without touching the routing code. That is the value of progressive disclosure: the active context stays small but the available behavior set is wide.

**"How did you use sub-agents?"**
Four of them, each with a narrower capability envelope than the main session. Compliance-auditor sees draft text and retrievals but cannot fetch new citations. Eligibility-checker takes intake state plus a program name and returns a deterministic verdict citing the rule. Resource-matcher is read-only against tx-resources. Caseload-summarizer is the only path to cross-conversation data and it runs in complete isolation from any user session. The principle: capabilities narrow as you descend the call stack. The compliance auditor literally cannot retrieve more citations to justify a weak claim. That is what makes the audit story believable instead of vibes-based.

**"How did you use hooks?"**
Three hooks, all deterministic Python, all enforcing properties the model cannot be trusted with. Crisis-keyword-check runs on UserPromptSubmit — regex scan for suicide / self-harm / substance / DV / housing emergency in English and Spanish. PII-redact runs on PreToolUse for writes — strips SSN / DL / DOB / phone / email / street address with an allowlist for crisis hotlines so 988 isn't redacted from outbound replies. RAG-confidence-gate runs on PostToolUse after every retrieval — if confidence is below 0.62 it rewrites the tool output to a structured handoff payload. The hooks live in `.claude/hooks/`, the bindings live in `.claude/settings.json` with matchers like `"Write|Bash|mcp__pathways-postgres__.*"`. The model cannot skip them under context pressure because they run outside the model loop entirely.

**"Why deterministic hooks instead of LLM-based safety?"**
Because LLMs under context pressure rationalize. A user texts "I'm thinking about taking too many pills tonight." An LLM might classify that as ambiguous and ask a clarifying question. A regex cannot. Regex misses are deterministic and fixable — I caught one for "took too many pills" in a live test, added a regex variant, and shipped 11 new regression tests in the same commit. LLM misses are stochastic and slow to detect. For a property where the failure mode is missing a real crisis, the safety floor has to be deterministic.

**"How did you use MCP servers?"**
Two MCP servers, both stdio transport, both spawned as subprocesses by the Claude session. Pathways-corpus exposes `search_corpus`, `get_citation`, `list_categories` over 95 hand-curated Texas law entries. Tx-resources exposes `find_resources`, `find_resources_nearby`, `get_resource`, `list_categories` over the reentry organization directory plus 832 ingestible Texas FQHCs. The point of the MCP boundary: the same Skill code runs in a development session against mocked tools, in production against Postgres, in tests against in-process file backends, and from another agent's session entirely. Same tool contract, different backend. The graph never knows or cares which backend is active.

**"Why two MCP servers instead of one?"**
Because they serve different data, change on different schedules, and have different safety requirements. The corpus is hand-curated, low-churn, citation-disciplined. The resources are higher-churn, mixed-source, geo-aware. Keeping them separate means a resource refresh doesn't touch corpus code, and a corpus correction doesn't risk a typo in the directory. They also have different downstream hooks — the rag_confidence_gate fires after both, but the confidence floor is calibrated against the corpus, not the directory.

**"How does CLAUDE.md fit in?"**
It's the operating constitution at repo root. Five hard rules at the top: cite or don't claim, you are not a lawyer, you are not a clinician, Texas only, HITL gate on anything financial or legal. Plus a routing table mapping user intent to Skills, and capability descriptions for sub-agents. The unusual property: this CLAUDE.md is enforcement, not documentation. Rule 1 is enforced by the compliance-auditor sub-agent and the rag_confidence_gate hook. Rule 5 is enforced by the `ask` permission on `mcp__twilio-sms__send_sms` in settings.json. The constitution is wired to the harness.

**"What's in your plugin manifest?"**
`.claude/plugin.json` packages all of the above as a redistributable Claude Code plugin. One command — `claude plugin install .` — loads the seven Skills, four sub-agents, three hooks, two MCP servers, three rule files, and the settings.json policy envelope into someone else's Claude session. That's the unit of distribution. Another organization could install the Pathways plugin and immediately have the Texas reentry navigator capability available in their own Claude Code workflow.

### 12.3 System design questions

**"Why LangGraph instead of CrewAI or a single super-prompted agent?"**
I considered all three. A single super-prompted agent with retrieve, match, audit as tools it could call in any order — rejected because the audit step cannot be optional under context pressure. If the agent has freedom to skip audit when tokens run low, it will, and silent regressions in safety-critical systems are the worst kind. A tightly scripted Python pipeline with no agent flexibility — rejected because the conversation phase genuinely benefits from model reasoning. LangGraph's explicit state machine, where every node has a defined responsibility and every transition is named — picked because it provides structural guarantees at the orchestration layer and model flexibility at the node layer. CrewAI I have used elsewhere; rejected here because the explicit node-and-edge model of LangGraph fit my safety posture better.

**"Walk me through what happens when a user sends a message."**
On the SMS path: Twilio webhook hits `/sms`. The handler verifies the HMAC-SHA1 signature, extracts Body / From / MessageSid, derives the salted-SHA-256 thread ID, checks for STOP/HELP keywords and opt-out state, dedupes on MessageSid via Postgres ON CONFLICT, runs the crisis-keyword-check regex above the graph, then invokes the LangGraph app with `{"configurable": {"thread_id": tid}}`. Inside the graph: intake runs first — if crisis fired, route immediately to escalate. Otherwise check slots; if one missing, ship the prompt and end. If all slots are filled, route to retrieve. Retrieve picks BM25 or hybrid based on env, calls the corpus, sets a confidence-gated flag. Match iterates over all needs, hits tx-resources with nearby / regional / statewide fallbacks, dedupes by org ID, caps at six. Draft synthesizes the reply (LLM if API key present, deterministic template otherwise). Audit checks the draft against the retrievals; pass → send, soft_block → loop back to draft with revision budget decrement, hard_block or budget exhausted → escalate. Send promotes draft to final_response, appends parole-reminder offer if applicable, persists state via the checkpointer, returns. Handler wraps in TwiML and returns 200 to Twilio.

**"How does state persist across turns?"**
LangGraph's checkpointer. Three backends selectable by `PATHWAYS_CHECKPOINT_BACKEND`: memory (tests / cold demo), sqlite (local dev), postgres (production). The checkpointer is keyed by thread_id — `ph_<sha256-hash>` for SMS, `web_<uuid>` for the PWA. After every graph invocation, the full PathwaysState snapshots to the backend. On the next turn for the same thread, the checkpointer restores the prior state before the graph runs. Multi-turn intake works because the IntakeProfile is part of the state and survives between turns.

**"How do you handle Twilio retries?"**
Idempotency on `MessageSid`. A separate Postgres table `inbound_message_dedup` with MessageSid as the primary key. INSERT ... ON CONFLICT DO NOTHING. If the row inserted, this is a fresh message; if it didn't, it's a retry and we return 200 with an empty TwiML so Twilio stops retrying. The dedup check happens before graph invocation. In-memory fallback for demo mode with a 24-hour TTL.

**"How is PII protected?"**
Multiple layers. Phone numbers never persisted as a primary key — only the salted SHA-256 hash. Conversation analytics scrub at the write seam — `event_from_state()` strips name, raw phone, raw ZIP, raw message text, raw reply text before writing to `conversation_events`. The dashboard cannot leak PII because the writer never persisted any. PII redaction hook strips SSN / DL / DOB / phone / email / street address before any write path. The audit log carries full content (for operator forensics) but Fernet-encrypted at rest with a separate key from the phone map. The forward phone map (thread_id → phone) is its own Fernet-encrypted table that only the parole-reminder sender and the writeback sender touch.

**"How do you handle Spanish?"**
Lightweight trigram language detector at `pathways/i18n/`, deliberately conservative — no API calls, doesn't infer language from a single Spanish word in an English context. Five Spanish crisis patterns in the hook covering suicide, self-harm, substance, DV in progress, housing emergency, all accent-tolerant because basic phone keyboards skip accents. Intake heuristic extractor has parallel Spanish keyword coverage for each need category. Draft node has full English and Spanish templates with multi-need synthesis ordered by trauma-informed urgency: housing tonight first, then food, then ID/parole, then benefits, then employment, then legal. The seven full Spanish sibling Skill bodies are explicitly deferred because raw machine translation does not survive the trauma-informed register; each needs human review by a native Spanish speaker before shipping.

### 12.4 Trade-off and judgment questions

**"What would you do differently?"**
Three things. First, talk to actual returning citizens earlier. The project is currently informed by reading rather than user interviews; that is the largest gap and closing it should happen as soon as the system is far enough along to test on a real person. Second, get partner NGOs into the loop before deploying. The organizations whose phone numbers appear in the resource directory haven't been contacted for feedback or partnership yet. Third, I would have shipped the eval harness in Phase 1, not Phase 5. The harness immediately caught four real bugs on first run that had been latent for weeks. Earlier eval gates would have caught them earlier.

**"What's the biggest risk in this system?"**
Confident-wrong legal information. The whole architecture exists to push the failure mode toward honest-unknown instead of confident-wrong, but no architecture eliminates the risk entirely. The eval gate on crisis being 100% is the floor; the citation-discipline layers are the second floor; the audit revision budget plus escalation is the third. If any one of those fails, the next layer catches it. The single point of failure I worry about most is the corpus itself going stale — a Texas statute changes, the corpus doesn't update, the citation is now wrong even though the audit passes because the audit only verifies the citation exists in the corpus, not that the corpus is current. The weekly refresh + stale-marking mitigates but doesn't eliminate.

**"How did you decide what NOT to build?"**
Same way I decided what to build: cost discipline plus failure-mode analysis. Native iOS / Android was rejected because Apple's $99/year subscription violates the zero-spend constraint; a PWA covers 90% of the value at 1% of the cost. MMS photo extraction would be powerful but Twilio MMS is paid, and at meaningful volume the vision API calls add real cost; deferred until a partner sponsors. Warm-transfer voice has 2-3x the conversion rate of cold referral per the reentry services literature, but Twilio Voice is paid; deferred. Phase 5 had voice IVR in scope; pushed to "Phase 5b when there's reason" because the caseworker dashboard was higher-value for the same engineering cost. The pattern: every primitive should have a one-sentence answer to "what failure mode does this prevent?" If I cannot produce that sentence, the primitive is decoration.

**"How do you know it works?"**
305 unit tests covering hooks and graph end-to-end, all green in demo mode with no API key needed. 73 frozen eval scenarios across 11 categories — crisis (12, must be 100%), routing (10), multi_need (5), spanish (6), geo (5), citation (6), handoff (4), parole_reminder (5), retrieval_quality (6), audit (6), intake_edge (8). CI gates merges on crisis 100% and overall pass rate above 0.95. The harness caught four real bugs on its first run, which is the entire point. Live deploy at https://pathways-iota.vercel.app/ and https://prathik10-pathways.hf.space/docs; anyone can walk through it.

**"What did you learn?"**
A few things. Architecture upfront pays for itself fast in safety-critical domains — the two days on paper before opening an editor were the most leveraged hours in the project. The Claude Code primitives are not interchangeable; Skills, sub-agents, hooks each solve a specific class of problem and picking the right primitive per concern is the whole skill. Demo mode without an API key is a feature, not a fallback — the deterministic templates in intake, draft, and audit let me write integration tests that run in six seconds and pass on a fresh checkout. The PWA-versus-native decision is a cost-discipline question, not a UX question. And the pattern: every primitive should have a one-sentence answer to "what failure mode does this prevent?" If I cannot produce that sentence, the primitive is decoration and should be removed.

### 12.5 Code-walk questions

If the interviewer asks you to walk through a specific file or function, the highest-leverage ones to memorize:

- **`pathways/state.py`** — `PathwaysState`, `IntakeProfile`, the enums (TopNeed, CrisisCategory, IntakeStage, AuditVerdict, SupervisionStatus).
- **`pathways/graph.py`** — `build_graph`, `_route_after_intake`, `_route_after_audit`, the singleton pattern with `get_app` / `reset_app`.
- **`pathways/nodes/intake.py`** — the merge-without-overwrite rule, the crisis short-circuit.
- **`pathways/nodes/audit.py`** — the verdict types, the rule-based fallback in demo mode.
- **`pathways/sessions/thread.py`** — `thread_id_for_phone` with the salted SHA-256.
- **`pathways/sessions/idempotency.py`** — the MessageSid dedup table with `ON CONFLICT DO NOTHING`.
- **`pathways/api/main.py`** — the `/sms` handler step order.
- **`pathways/api/web.py`** — the `/web/turn` handler, the `_log_map_metrics` structured line.
- **`.claude/settings.json`** — the permissions allow / deny / ask buckets, the hook matchers.
- **`.claude/hooks/crisis_keyword_check.py`** — the regex coverage and the bilingual patterns.
- **`evals/runner.py`** — the gating logic (crisis 100% AND overall >= threshold).

---

## 13. The five things to memorize for any answer

Distilled. If you can name these in any interview answer, you sound like you actually built it.

1. **The asymmetry that drove the design.** Confident-wrong costs more than honest-unknown. Every architectural decision optimizes for "fail into 'I don't know, here's a human.'"
2. **The right primitive for the right concern.** Skills are domain protocols. Sub-agents are bounded capability workers. Hooks are deterministic safety enforcement outside the model loop. MCP servers are swappable data tools. Settings is the permission envelope. Mixing these up is the most common mistake.
3. **Narrowing capabilities as you descend the stack.** Main session > Skills > sub-agents > specific tools. The compliance auditor cannot retrieve new citations. The caseload summarizer cannot read individual conversations. The dashboard cannot leak PII because the writer never persisted any.
4. **The layered safety story.** Crisis (upstream hook), confidence (downstream hook), PII (write-path hook), citation (rule file + Skill + sub-agent + audit node), HITL (settings.json `ask` block). Five overlapping layers. Any single layer missing a violation is fine because the others catch it.
5. **The shared-backend / multi-channel payoff.** Three audiences (SMS, PWA, dashboard) share one LangGraph state machine. Only `state.channel` differs. Architectural payoff for the upfront state-machine investment.

---

## 14. Common mistakes to avoid

- **Don't conflate Skills with prompts.** Skills are progressive-disclosure protocols loaded by description match. They are not a single mega system prompt with sections.
- **Don't claim the model handles safety.** The model does not enforce crisis detection, PII redaction, or confidence gating. Hooks do.
- **Don't say "the agent decides." Say "the graph routes."** Pathways is an explicit state machine, not an autonomous agent. Every transition has a name.
- **Don't undersell the eval harness.** It is what makes "I know it works" defensible. 73 scenarios, crisis-100%-required, blocks merges. Mention that it caught four real bugs on first run.
- **Don't claim Texas-only is a limitation.** It's a deliberate scope choice. State-agnostic systems produce confidently wrong cross-state answers. Deep coverage of one state is more useful than shallow coverage of fifty.
- **Don't apologize for the demo seed having no lat/lon.** Acknowledge it as a known follow-up. The production ingest from HRSA includes 832 geocoded FQHCs. The contract works end-to-end either way.

---

## 15. Quick reference: file paths to cite cold

| Concept | Path |
|---|---|
| Operating constitution | `CLAUDE.md` |
| Settings (permissions + hook bindings) | `.claude/settings.json` |
| Plugin manifest | `.claude/plugin.json` |
| Always-loaded rule files | `.claude/rules/{citations,compliance,tone-and-trauma-informed}.md` |
| Skills | `.claude/skills/<name>/SKILL.md` |
| Sub-agents | `.claude/agents/<name>.md` |
| Hooks | `.claude/hooks/{crisis_keyword_check,pii_redact,rag_confidence_gate}.py` |
| MCP corpus server | `mcp_servers/pathways_corpus/server.py` |
| MCP resources server | `mcp_servers/tx_resources/server.py` |
| State + enums | `pathways/state.py` |
| Graph construction | `pathways/graph.py` |
| Nodes | `pathways/nodes/{intake,retrieve,match,draft,audit,escalate,send}.py` |
| Thread ID derivation | `pathways/sessions/thread.py` |
| Checkpointer factory | `pathways/sessions/checkpointer.py` |
| MessageSid idempotency | `pathways/sessions/idempotency.py` |
| Retrieval strategy + RRF | `pathways/retrieval/__init__.py` |
| Embeddings | `pathways/retrieval/embeddings.py` |
| Geo helpers | `pathways/geo/{zips,workforce_regions}.py` |
| LLM provider plug | `pathways/llm/provider.py` |
| SMS handler | `pathways/api/main.py` |
| PWA handler | `pathways/api/web.py` |
| Caseworker dashboard | `pathways/dashboard/{app,analytics,auth,writeback}.py` |
| Audit log | `pathways/audit/{service,store}.py` |
| Parole reminders | `pathways/parole_reminders/service.py` |
| Eval runner + scoring | `evals/{runner,loader,scoring}.py` |
| Eval scenarios | `evals/scenarios/*.json` |
| Tests | `tests/test_phase*.py` |
| CI workflows | `.github/workflows/{ci,evals,deploy-hf,daily-cron,refresh-data}.yml` |
| HF Space metadata | `README.md` frontmatter (YAML at top) |
| Dockerfile | `Dockerfile` |
| Dev journal (full build history) | `docs/JOURNAL.md` |
| Architecture deep-dive | `docs/ARCHITECTURE.md` |
| Per-primitive walkthrough | `docs/SHOWCASE.md` |
| Compliance posture | `docs/COMPLIANCE.md` |
| Deferred Phase 6 with unblock criteria | `docs/PHASE6_DEFERRED.md` |
| This briefing | `docs/INTERVIEW_BRIEFING.md` |

---

## 16. Three things you should be able to demo live

If the interview shifts to "show me," these are the three highest-leverage live demos:

1. **The PWA at https://pathways-iota.vercel.app/.** Walk through the welcome screen, hit a quick-prompt chip, give a name, give 77002 as the ZIP, ask for housing. Show the chat-bubble animations, the resource cards, the map view above the cards (once the demo seed is geocoded), and the language toggle.

2. **The /docs Swagger UI at https://prathik10-pathways.hf.space/docs.** Open `/_debug/invoke`, paste `{"message":"Can I vote in Texas if I am on parole?"}`, run it, walk through the response showing the retrieval citations, the matched resources, the audit verdict, the final reply.

3. **The eval gate.** Pull up `evals.yml` in the GitHub Actions tab on a recent commit, show the green check, click in, show the `GATE: GREEN 73/73` line. Then open the dev journal and show the entry about the four bugs the harness caught on first run.

---

*Written 2026-05-18. Re-read sections 4 and 12 the night before any interview.*
