# Pathways — Claude Code Primitive Showcase

This document is a code-level tour of every Claude Code primitive in this repo. For each one: **what it does**, **the actual file**, **a code snippet that's load-bearing**, and **why it had to be this primitive** (vs. a plain prompt).

If you've read [`ARCHITECTURE.md`](ARCHITECTURE.md) (the *why* document), this is the *show me the code* companion.

> **Recruiter shortcut.** The JD said *"a short README explaining what each piece does and why you built it is more valuable than volume."* This document is the long-form version of that pitch. Every primitive has a load-bearing reason. None are decoration.

---

## 1. Skills (`.claude/skills/`)

**7 progressive-disclosure Skills**, each a single `SKILL.md` with a frontmatter `description` that drives auto-loading.

### Why Skills, not a monolithic system prompt

A single prompt that says *"you are a TX reentry navigator who handles housing, employment, benefits, record clearing, eligibility lookup, and crisis response"* leaks across all those domains every turn. The model carries the housing protocol's tone advice into a benefits question and the benefits eligibility logic into a crisis. Skills load **only when relevant** — the housing-pathway protocol only ships into context when the user is asking about housing. Narrower context = fewer hallucinations on legal claims.

### The auto-load mechanism

Each Skill's frontmatter `description` is read by Claude Code at session start. The model decides which Skill to load based on the user's message. Example (`benefits-navigator/SKILL.md` frontmatter):

```yaml
---
name: benefits-navigator
description: Loads when the user asks about SNAP, food stamps, Medicaid, TANF, CHIP, SSI,
  SSDI, "benefits," or whether their record disqualifies them. Centered on correcting
  the single most damaging misconception in Texas reentry — the false belief that a
  drug felony permanently bars SNAP. Routes enrollment to Your Texas Benefits and
  applicable HHSC/SSA paths.
---
```

The body of the SKILL.md is the protocol — domain knowledge, the specific TX nuances, the routing rules. That body is **never loaded** until the description matches the user's question.

### The 7 Skills at a glance

| Skill | Triggers on | Encoded knowledge |
|---|---|---|
| [`intake-assessment`](../.claude/skills/intake-assessment/SKILL.md) | New conversation, no prior client state | Trauma-informed first-touch protocol; minimum-PII intake; routing decision tree |
| [`niccc-lookup`](../.claude/skills/niccc-lookup/SKILL.md) | "Can I..." eligibility/restriction questions | Cite-or-don't-claim contract; confidence gate; explicit handoff phrasing |
| [`housing-pathway`](../.claude/skills/housing-pathway/SKILL.md) | Housing, shelter, transitional living | Time-staged triage (tonight / this-week / long-term); HUD mandatory denials (narrow: sex-offender lifetime reg + meth production); fair-chance rental strategy |
| [`employment-pathway`](../.claude/skills/employment-pathway/SKILL.md) | Jobs, work, occupational licenses | Three distinct employment questions disambiguated; TX Occupations Code § 53 + per-board bars; Federal Bonding Program; criminal history evaluation letter (§ 53.102) |
| [`record-clearing-tx`](../.claude/skills/record-clearing-tx/SKILL.md) | Expungement, non-disclosure, sealing | Expunction (CCP Ch. 55) vs non-disclosure (Gov't Code Ch. 411) distinction; eligibility worksheet; routes to legal aid for final determination |
| [`benefits-navigator`](../.claude/skills/benefits-navigator/SKILL.md) | SNAP, Medicaid, TANF, SSI, SSDI | TX drug-felony SNAP correction (the #1 misinformation in TX reentry); HHSC/SSA enrollment paths |
| [`crisis-response`](../.claude/skills/crisis-response/SKILL.md) | Hook-triggered (suicidality, self-harm, DV, OD, housing emergency) | Suspends normal workflow; routes to 988/211/SAMHSA; no resource matching, no model speculation |

---

## 2. Sub-agents (`.claude/agents/`)

**4 sub-agents**, each with **narrowed** capability vs. the parent session — not broader. This is the most-misunderstood Claude Code primitive: sub-agents aren't about parallelism, they're about **bounding what each part of the system can do**.

### The capability-scoping pattern

Every sub-agent's frontmatter declares its allowed tools and explicitly disallowed tools. The runtime enforces this. Example (`compliance-auditor.md` frontmatter):

```yaml
---
name: compliance-auditor
description: Validates that a draft response containing legal or eligibility claims is
  properly cited and within scope. Read-only; cannot retrieve, write, send messages, or
  modify state. Run this before any response to the user that touches legal rights...
tools: Read
model: haiku
disallowedTools: Write, Edit, Bash, WebFetch, mcp__pathways-corpus__*,
  mcp__tx-resources__*, mcp__twilio-sms__*
---
```

That `disallowedTools` line is load-bearing. The auditor literally **cannot** retrieve more citations to justify a weak claim — it can only read the draft + the citations the upstream node already gathered, and rule pass/soft_block/hard_block. This stops the audit step from drifting into "let me find evidence for what I just said" mode.

### The 4 sub-agents

| Sub-agent | Model | Allowed | Why narrowed |
|---|---|---|---|
| [`compliance-auditor`](../.claude/agents/compliance-auditor.md) | Haiku | `Read` only | Audit must be read-only or it becomes "I'll keep searching until I find a citation that fits" |
| [`eligibility-checker`](../.claude/agents/eligibility-checker.md) | Haiku | `Read` only | Eligibility rules should be reproducible from a single input record. No MCP, no retrieval, no drift. |
| [`resource-matcher`](../.claude/agents/resource-matcher.md) | Sonnet | `Read` + corpus + resources MCP | Can read knowledge + directory. Cannot send SMS — sending is HITL-gated separately. |
| [`caseload-summarizer`](../.claude/agents/caseload-summarizer.md) | Sonnet | `Read` + PG MCP + cache `Write` | Read-only on PG views. Crucially: **never reachable from a user-facing session** — only via `claude --agent caseload-summarizer`. Stops one client's data leaking into another's conversation. |

---

## 3. Hooks (`.claude/hooks/`)

**3 deterministic Python hooks**, registered in `.claude/settings.json` under `hooks`. They run **outside the model loop** — pure Python, no LLM, no chance the model "decides this turn it's okay to skip the check."

### Why hooks, not Skill instructions

Telling the model *"if you detect a crisis keyword, route to crisis-response"* is not enforceable. Under load, the model will reasonably interpret some message as "not really a crisis" and skip the route. Hooks remove the choice. Regex hits → Skill loads. No model judgment in the path.

### The 3 hooks

#### `crisis_keyword_check.py` — `UserPromptSubmit`

```python
# .claude/hooks/crisis_keyword_check.py (excerpt)
CRISIS_PATTERNS = {
    "suicide":          [r"\b(kill myself|end my life|suicid)", ...],
    "self_harm":        [r"\b(cut myself|hurt myself)", ...],
    "violence":         [r"\b(kill (him|her|them)|going to hurt)", ...],
    "overdose":         [r"\b(took too many|overdosed)", ...],
    "domestic_violence":[r"\b(he('?s| is) hitting me|she('?s| is) hitting me)", ...],
    "housing_emergency":[r"\b(sleeping in my car tonight|nowhere to sleep)", ...],
}

def detect_crisis(message: str) -> Optional[str]:
    msg = message.lower()
    for category, patterns in CRISIS_PATTERNS.items():
        if any(re.search(p, msg) for p in patterns):
            return category
    return None
```

Returns `None` or the matched category. If matched, Claude Code injects a system instruction loading `crisis-response` Skill **before** the model sees the turn. The model literally cannot decide otherwise.

#### `pii_redact.py` — `PreToolUse` (matcher: `Write|Bash|mcp__pathways-postgres__.*`)

Runs before any write path. Redacts SSN, TX driver license numbers, TX state ID, TDCJ inmate numbers, case numbers, phone numbers (with an **allowlist** for crisis hotlines so 988/211/DV-hotline are never redacted), emails, DOBs, street addresses. **Fail-closed:** if the regex itself errors, the tool call is blocked rather than allowed through unredacted.

```python
# Hotline allowlist — these phone numbers must survive redaction
HOTLINE_ALLOWLIST = {
    "988",                  # Suicide & Crisis Lifeline
    "211",                  # United Way / TX 211
    "1-800-799-7233",       # National DV Hotline
    "1-800-662-4357",       # SAMHSA
    "1-800-656-4673",       # RAINN
}
```

#### `rag_confidence_gate.py` — `PostToolUse` (matcher: `mcp__pathways-corpus__search_corpus|mcp__tx-resources__.*`)

Reads the confidence score from the retrieval result. If below `PATHWAYS_CONFIDENCE_FLOOR` (default `0.62`, env-tunable), **rewrites** the tool result into a structured `gated: true` payload that forces a human-handoff response. Original is preserved under `_original_low_confidence` for the auditor's review.

This is how *"the model literally cannot draft a citation it doesn't have evidence for"* is enforced. The model never sees the confident-but-wrong retrieval — it sees a "handoff to a human" instruction.

---

## 4. MCP servers (`mcp_servers/`)

**2 domain-bounded MCP servers** running stdio transport locally. Each serves one knowledge contract.

### Why MCP, not direct DB calls

Direct DB calls hard-code the storage layer into the agent. MCP servers make the storage layer a **swappable interface**. The demo runs BM25 in-memory over `corpus.json`; production swaps to pgvector or Pinecone **without touching a single Skill or node** — because the tool contract (`search_corpus(query, category) -> SearchResults`) is identical across backends.

### `pathways-corpus` — legal knowledge

```python
# mcp_servers/pathways_corpus/server.py — tool surface
@mcp.tool()
def search_corpus(query: str, category: Optional[str] = None) -> dict:
    """BM25 over the curated TX legal corpus. Returns top-k with confidence scores."""

@mcp.tool()
def get_citation(citation_id: str) -> dict:
    """Fetch a single citation by ID (e.g., 'tx-occ-53-021')."""

@mcp.tool()
def list_categories() -> list[str]:
    """Returns categories: employment, civil_rights, record_clearing, benefits,
       housing, drivers_license, supervision."""
```

The 65 seed entries are real Texas statutes harvested from the [Texas State Law Library](https://guides.sll.texas.gov/criminal-conviction-restrictions) and the [NICCC inventory](https://niccc.nationalreentryresourcecenter.org/). Each entry carries `id`, `citation`, `summary`, `url`, `category`, `subcategory`, `tags`, `last_verified` — so any user-facing claim can be traced back to its source.

### `tx-resources` — TX reentry organization directory

```python
# mcp_servers/tx_resources/server.py — tool surface
@mcp.tool()
def find_resources(topic: Optional[str] = None,
                   category: Optional[str] = None,
                   region: Optional[str] = None) -> list[dict]:
    """Filter the directory by topic + category + region (substring match)."""

@mcp.tool()
def get_resource(resource_id: str) -> dict:
    """Fetch one org by ID."""
```

18 curated TX reentry orgs (Texas RioGrande Legal Aid, Lone Star Legal Aid, Goodwill Houston, Salvation Army, TWC Reentry, TX HHSC, 211 Texas, etc.). Each carries phone, URL, intake_url, languages, eligibility, region tags, and `last_verified`. Phase 2 of the roadmap expands this to ~5,000 orgs via ingestion of 211 Texas / TWC / HHSC / DPS / SSA / FQHC / NICCC org directories.

---

## 5. Settings (`.claude/settings.json`)

The production posture in one file. Every section is load-bearing:

```json
{
  "model": "sonnet",
  "permissions": {
    "allow": [
      "Read", "Grep", "Glob",
      "WebFetch(domain:niccc.nationalreentryresourcecenter.org)",
      "WebFetch(domain:www.tdcj.texas.gov)",
      "mcp__pathways-corpus__*",
      "mcp__tx-resources__*"
    ],
    "deny": [
      "Bash(rm:*)",
      "Bash(curl:*)",
      "Write(/etc/**)",
      "Write(**/.env)"
    ],
    "ask": ["Write", "Edit", "Bash", "mcp__twilio-sms__send_sms"]
  },
  "allowManagedHooksOnly": true,
  "hooks": {
    "UserPromptSubmit": [{ "matcher": ".*",
      "hooks": [{ "type": "command", "command": "python .claude/hooks/crisis_keyword_check.py" }] }],
    "PreToolUse":       [{ "matcher": "Write|Bash|mcp__pathways-postgres__.*",
      "hooks": [{ "type": "command", "command": "python .claude/hooks/pii_redact.py" }] }],
    "PostToolUse":      [{ "matcher": "mcp__pathways-corpus__search_corpus|mcp__tx-resources__.*",
      "hooks": [{ "type": "command", "command": "python .claude/hooks/rag_confidence_gate.py" }] }]
  },
  "env": {
    "PATHWAYS_STATE": "TX",
    "PATHWAYS_DEPLOY_MODE": "demo",
    "PATHWAYS_CONFIDENCE_FLOOR": "0.62"
  }
}
```

What each section does:

- **`model: "sonnet"`** — default model. Skills/sub-agents can override (Haiku for routing + audit, Sonnet for synthesis, Opus reserved for high-stakes policy reasoning per `CLAUDE.md`).
- **`permissions.allow`** — explicit allow-list. `WebFetch` is domain-scoped to the 3-4 sites the navigator ever needs; arbitrary URLs are blocked.
- **`permissions.deny`** — blast-radius prevention. `Bash(rm:*)`, `Bash(curl:*)`, `Write(/etc/**)`, `Write(**/.env)` — the model literally cannot delete files, exfiltrate via curl, write to `/etc/`, or overwrite `.env` files.
- **`permissions.ask`** — `Write`, `Edit`, `Bash`, and outbound SMS require explicit user confirmation. Irreversible actions never auto-approve.
- **`allowManagedHooksOnly: true`** — the safety posture cannot be silently relaxed by a Skill author. Only hooks registered in this settings file run; ad-hoc hooks injected from session state are ignored.
- **`hooks`** — the 3 deterministic gates registered to fire on the right events with the right matchers (so PII redaction only runs on write-path tools, confidence gating only runs on retrieval tools, crisis check runs on every user message).
- **`env`** — runtime configuration. `PATHWAYS_DEPLOY_MODE=demo` is what makes the system run without an Anthropic API key (deterministic fallbacks throughout `intake.py`, `draft.py`, `audit.py`).

---

## 6. Rules (`.claude/rules/`)

**Cross-cutting policy that applies to every turn regardless of which Skill is loaded.** Three rule files:

- [`citations.md`](../.claude/rules/citations.md) — citation formatting (inline format, link the citation to its URL, never invent a section number, what to do when the corpus disagrees with itself)
- [`compliance.md`](../.claude/rules/compliance.md) — non-negotiable constraints (TX-only scope, roles you do not occupy, outcomes you do not promise, data handling)
- [`tone-and-trauma-informed.md`](../.claude/rules/tone-and-trauma-informed.md) — register (sixth-grade reading level, no moralizing, no minimizing, no urgency theater, stigma-aware language)

These are deliberately outside any single Skill so they can't be forgotten by a Skill author. Every Skill inherits them.

---

## 7. The plugin manifest (`.claude/plugin.json`)

The whole architecture above is packaged as a single Claude Code plugin. A recruiter (or any partner reentry program) installs it with:

```bash
git clone https://github.com/PrathikRavichandran/pathways.git
cd pathways && claude plugin install .
```

After install, all 7 Skills, 4 sub-agents, 3 hooks, 2 MCP server registrations, and the rules file load into the recruiter's Claude Code session. They can ask a TX-reentry question and watch the full architecture work end-to-end with no setup beyond the install command.

This is the production-distribution story. The architecture isn't a private codebase — it's a reusable bundle. If a non-profit in another state wanted to fork this for their jurisdiction, they'd fork the repo, swap the corpus + resources MCP server contents, and have the same safety architecture for their state. No code rewrite.

---

## 8. The runtime composition (graph + nodes + Claude Code session)

The graph in `pathways/graph.py` and the Claude Code primitives are **two complementary layers**:

- The **graph** (LangGraph) is the deterministic skeleton: intake → retrieve → match → draft → audit → send/escalate. Every transition has an address. The graph guarantees the audit step runs every turn.
- The **Claude Code primitives** (Skills + sub-agents + hooks) are the **policy + safety layer** that wraps each node. Skills shape the model's behavior inside `intake` and `draft`. Hooks fire around graph nodes. Sub-agents are spawned by `audit` (compliance-auditor) and could be spawned by `match` (resource-matcher).

That layered design — explicit graph for structure, Claude Code primitives for policy — is the meta-insight of the architecture. Either alone would be weaker: a pure-graph build loses the progressive-disclosure benefit of Skills; a pure-Claude-Code build loses the "audit runs every turn" guarantee.

---

## Where to look next

| If you want to see... | Open |
|---|---|
| Design rationale + safety reasoning | [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) |
| The constitution all Skills inherit | [`CLAUDE.md`](../CLAUDE.md) |
| The graph (nodes + edges + revision loop) | [`pathways/graph.py`](../pathways/graph.py) |
| The Twilio webhook ingress | [`pathways/api/main.py`](../pathways/api/main.py) |
| Worked SMS conversations end-to-end | [`examples/sample_conversations.md`](../examples/sample_conversations.md) |
| Compliance posture (PII, HITL, scope) | [`docs/COMPLIANCE.md`](COMPLIANCE.md) |
| Live API | <https://prathik10-pathways.hf.space/docs> |

---

## 9. Phase 7 additions (2026-05-18)

Two changes landed in tight succession via PR #1 and PR #2.

**PR #1 — resource map view in the PWA.** A new `web/src/components/ResourceMap.tsx` mounts above the existing resource cards in the bot bubble whenever at least one returned card carries `lat` / `lon`. Self-gates by returning null when zero pin-able. Backend change is small: `pathways/api/web.py::ResourceCard` gained nullable `lat` / `lon` fields, and `_shape_response` now forwards them via a defensive `_coerce_float` helper that handles psycopg `Decimal`, numeric strings, and garbage values without raising. The map embed uses OpenStreetMap tiles (no API key, no billing); pin popups deep-link to Google Maps via the documented URL API so iOS Safari and Android Chrome open the native Google Maps app when installed. Dashboard analytics extended with `resources_with_coords_count` per turn and `map_pins_total` / `turns_with_map_view` aggregates. New structured log `web_turn_map_metrics ...` emits per turn so operators can grep for map-render frequency without opening the dashboard. Tests: 24 new in `tests/test_phase7_map_view.py` covering type coercion, projection, end-to-end shape, and analytics tracking.

**PR #2 — CI auto-deploy of `main` to the HF Space.** New `.github/workflows/deploy-hf.yml` force-pushes the repo to `huggingface.co/spaces/prathik10/pathways` on every merge and on `workflow_dispatch`. Polls `/health` for 10 min and reports the result, fail-soft (push success != HF rebuild completion). One-time operator setup is `gh secret set HF_TOKEN` with a write-scope token. Joins the existing four workflows for five total in `.github/workflows/`.

Both PRs reused existing primitives rather than adding new ones — the architecture didn't grow. The lesson is that a layered design pays out at the additive boundary: a new UI surface is just a new React component plus a new field in the projection model; a new ops automation is one workflow file plus a one-line operator action. No restructuring required.
