# Pathways: Development Journal

This is the public development journal for the Pathways project. It captures the origin, the architecture decisions, the build sequence, and the forward roadmap. Each section is dated where relevant. New entries get added to the Dev Log at the bottom as work ships.

A more personal, full length version of this journal lives outside the repo. This file is the public excerpt.

---

## 1. The setting

I moved from Oklahoma City to Houston earlier this year for an Agentic AI Systems Engineer role. A few weeks after settling in, I started looking for a personal project that would do two things at once. The first was give me a public, working artifact that demonstrated how I use Claude Code in practice. The second was to do something useful for someone who actually needed it, not just be an impressive demo.

Those motivations overlapped in the territory of safety critical AI for vulnerable populations. Where they overlapped was the interesting place to build.

## 2. Why reentry, why Texas

I considered a few directions before landing on reentry. A municipal services concierge was too generic. A small business operations agent was a crowded space. A healthcare navigator was too close to my day job. A record clearing helper was a narrower version of what eventually became the focus.

What kept rising to the top was reentry navigation. The first 30 days after release are dense with bureaucratic decisions made under time pressure. Housing, ID restoration, work authorization, parole reporting, benefits enrollment, all collide in a narrow window. The information that resolves any of these exists, but it is fragmented across federal, state, county, and city agencies and most of it is written for lawyers. The cost of bad information at this stage is unusually high. A confident wrong answer about voting eligibility can produce a new felony charge. A polite list of resources sent to a person in crisis is a failure that matters.

That asymmetry, where confident wrong costs more than honest unknown, is the exact thing a thoughtful AI architecture should be able to handle better than an uncared for chatbot. That was the technical hook.

Texas was the place to start for two reasons. First, geographic convenience: I live in Houston, I can ground truth resources against actual phone calls, and I can plausibly meet with NGOs and case managers locally as the project matures. Second, scale: Texas runs the largest state prison system in the country with tens of thousands of releases per year and severe fragmentation of support services across 254 counties and 28 workforce regions. If a navigator architecture works for Texas, it ports to smaller states with proportionally less effort.

## 3. The first sketch

The first sketch was six boxes on paper. Person leaving prison. Phone with SMS. A toll free number on a poster outside the facility. A bot that asks who they are, where they are, and what they need most. A knowledge layer that knows Texas law. A directory layer that knows Texas organizations. A response that returns by SMS in plain language with phone numbers people can actually call.

The shape of what was hard came into focus quickly. The bot had to fail in safe ways, not clever wrong ways. A person who hears that their drug felony permanently disqualifies them from SNAP (a common but factually wrong belief in Texas reentry circles) will walk away from food they qualify for. A person in crisis who gets a list of resources instead of the 988 line has been failed in a way that matters. The architecture would have to push the system into "I am not sure, here is a human" much more often than into "here is a confident answer." Getting that posture right was the whole game.

## 4. Choosing the stack

SMS first was instinct. The primary user is reading on whatever phone they have, possibly a basic prepaid Android, possibly without data. SMS works on every device that has shipped in the last twenty years. Even a cracked 2010 Nokia can receive a text. The accessibility ceiling of SMS is the highest of any channel. A web app and a PWA were noted as future surfaces for caseworkers, family members, and returning citizens who do have smartphones, but the primary entry point had to be SMS.

Texas only was deliberate. State agnostic systems that pretend to cover all fifty states without a curated per state corpus produce confidently wrong cross state answers. The safer move was to deeply support one state and make the architecture portable.

Twilio was the only realistic choice for SMS in the US on a non profit budget. Their trial gives one free local number and a fifteen dollar credit, enough to demonstrate the flow against my own verified number.

For the AI layer, Anthropic Claude was the right call for both technical and career reasons. Claude's mix of reasoning, instruction following, and structured output fit the routing and audit tasks I needed, and the project was a chance to publicly demonstrate the Claude Code primitives. I noted a provider plug interface for the future to allow Gemini Flash as a zero cost fallback in production.

For orchestration, I considered three approaches and rejected two:

A single super prompted agent with retrieve, match, audit as tools it could call in any order. Rejected because the audit step cannot be optional under context pressure. If the agent has freedom to skip audit when tokens run low, it will, and silent regressions in safety critical systems are the worst kind.

A tightly scripted Python pipeline with no agent flexibility at all. Rejected because the conversation phase genuinely benefits from model reasoning.

An explicit LangGraph state machine where every node has a defined responsibility and every transition is named. Picked, because it provides structural guarantees at the orchestration layer and model flexibility at the node layer.

The Claude Code primitives slotted into that cleanly. Skills became the domain protocols loaded into the relevant nodes. Sub agents became the bounded capability assistants. Hooks became the deterministic safety layer that runs outside the model loop entirely. MCP servers became the swappable data tools. Settings became the permission envelope.

Things considered and abandoned along the way:

Pinecone for retrieval. Dropped for the seed corpus because BM25 over 65 entries is fast, deterministic, and free, and produces identical results across runs (good for reproducibility in tests). Phase 5 will swap to pgvector inside the Postgres I will already be using for state.

A native React Native iOS and Android app. Abandoned because shipping native iOS requires Apple's ninety nine dollars per year developer subscription, which violates the zero spend constraint. A Progressive Web App installed to the home screen covers ninety percent of the use case from one codebase. Capacitor is the escape hatch later if real native demand validates the cost.

CrewAI as the orchestration framework. Real consideration since I have used it elsewhere. Rejected because the explicit node and edge model of LangGraph fit my safety posture better.

LangChain's older AgentExecutor pattern. Rejected for the same reason as the super prompted agent: audit would be optional in that model.

## 5. The design principle: safe failure

Before writing any code I committed to a single guiding principle: the system should fail into "I am not sure, let me connect you with a human" much more often than into a confident wrong answer.

This generalizes to three concrete properties that shaped everything else.

First, every safety property should be enforced at the right layer. Crisis detection cannot live inside a Skill because the model under load might reasonably interpret some message as not really crisis. It needs a hook outside the model loop. PII redaction cannot live inside a draft node because by then the PII has already been touched. It needs a PreToolUse hook on the write path. Retrieval confidence cannot be checked by the model that wrote the draft because the model has motivated reasoning to consider its sources adequate. It needs a PostToolUse hook that rewrites low confidence results before they reach the drafting node.

Second, capabilities should narrow as you descend the call stack, not widen. The main session has the most permissions. Sub agents have fewer. Specific sub agents like the compliance auditor have almost none. The narrowing model means the compliance auditor literally cannot retrieve more citations to justify a weak claim. That is the kind of behavior that ruins audits in general.

Third, every transition should have a named address. When something goes wrong, the response cannot be the only forensic artifact. The explicit graph means a low confidence retrieval is a retrieve node concern, a tone problem is a draft node concern, an uncited claim is an audit node concern. Each one can be tested and improved in isolation.

These three properties live in `CLAUDE.md` and `docs/COMPLIANCE.md` so they govern decisions instead of being retrofitted later.

## 6. The build, in order

The repo was built bottom up over a single intense session on May 15, 2026:

1. Project scaffold, settings, operating constitution.
2. Corpus ingestion: 65 Texas statutory citations from the Texas State Law Library research guide and the NICCC inventory.
3. Resource directory: 18 curated Texas reentry organizations.
4. Seven Skills (intake-assessment, niccc-lookup, housing-pathway, employment-pathway, record-clearing-tx, benefits-navigator, crisis-response) plus three cross cutting rule files.
5. Four sub agents (compliance-auditor, eligibility-checker, resource-matcher, caseload-summarizer) with frontmatter capability scoping.
6. Three deterministic safety hooks (crisis_keyword_check, pii_redact with hotline allowlist, rag_confidence_gate).
7. Explicit LangGraph state machine (seven nodes, conditional routing, bounded revision loop) plus FastAPI ingress.
8. Thirty tests covering hooks and graph end to end, all passing in demo mode without an API key.
9. Architecture and compliance documentation.
10. Dockerfile and Hugging Face Spaces metadata for the deploy.

Most of the time went into the demo mode fallbacks. Those fallbacks matter because they keep the system testable without an API key and keep the cold boot path on a fresh deploy from breaking.

## 7. Phase 0: the recruiter cut

On May 15 a Phase 0 polish pass shipped, motivated by a job opportunity that asked for a working Claude Code repo. The phase added a Try It in 30 Seconds section at the top of the README, a CI badge backed by a pytest workflow on every push (Python 3.11 and 3.12 matrix), an install as a Claude Code plugin section with the new `.claude/plugin.json` manifest, a per primitive code level walkthrough at `docs/SHOWCASE.md`, and five annotated end to end SMS dialogues at `examples/sample_conversations.md`.

Phase 0 shipped zero new features and zero behavior change. It was pure narrative and packaging on top of the existing architecture. The bet was that for the audience in question, a clear five minute story is more valuable than another Skill or another sub agent.

## 8. The forward roadmap

**Phase 1: Multi turn stateful intake.** The biggest functional gap today is that the FastAPI ingress is stateless across SMS turns. Each Twilio webhook creates a fresh state. That breaks the multi turn intake flow (name, then ZIP, then top need, then question) that the user vision requires. Phase 1 wires a LangGraph PostgresSaver checkpointer keyed by a hash of the phone number, adds Twilio signature verification, adds idempotency on the MessageSid, and introduces a slot filling intake node that iterates until name, ZIP, and top need are populated.

**Phase 2: Real data.** The corpus grows from 65 entries to around 1,200 (full NICCC Texas, all relevant Texas Statute chapters, the Texas Admin Code, all licensing boards, federal CFR sections, TDCJ release procedures, the Board of Pardons and Paroles rules, the DPS DL rules, HHSC benefits detail, SSA reinstatement procedures, Pell Grant reentry rules, county courthouse filing procedures). The resource directory grows from 18 orgs to around 5,000 (211 Texas HSDS feed, all TWC Workforce Solutions offices, all HHSC benefit offices, all TX DPS DL offices, SSA Texas offices, NICCC TX org directory, Feeding Texas food banks, HRSA FQHCs, VA Texas facilities, TCFV DV shelters, county reentry coordinators, manually curated faith based and metro shelter networks, all 254 county courthouses). Both servers migrate from JSON files to Postgres tables. Distance ranking using vendored USPS ZCTA centroids replaces substring region match.

**Phase 3: Spanish, multi need, feedback.** Spanish sibling Skills for each of the seven existing Skills with human review of every translation. Intake schema changes from a single top_need to a list of needs. A 24 hour post referral feedback SMS asks "did this help" and writes to a `referral_outcomes` table. STOP, HELP, START handling for TCPA compliance.

**Phase 4: Progressive Web App.** A PWA at a public URL, installable to iOS and Android home screens, served on Vercel free tier. The PWA shares the same FastAPI plus LangGraph plus Skills plus MCP backend; only the channel field on state changes. Native iOS and Android were rejected explicitly because the Apple developer subscription violates the zero spend constraint, and a PWA covers ninety percent of the value at one percent of the cost.

**Phase 5: Production grade.** Hybrid retrieval (pgvector dense plus BM25 lexical with RRF fusion), Twilio Voice IVR for landline only callers, a read only caseworker dashboard for partner NGOs, and an eval harness with around 150 frozen scenarios that gates every PR. The provider plug interface for LLM calls (Anthropic default, Gemini fallback) ships here.

**Phase 6: Higher leverage ideas.** Opt in parole reporting reminder. MMS based photo extraction of the TDCJ release packet. Anonymous monthly trend reports to partner NGOs. Warm transfer voice connect to a live navigator. NGO write back through the dashboard so caseworkers can text the user through Pathways while keeping the phone number hidden. None of these is in scope yet; Phase 1 through 5 stable first.

## 9. Known gaps

A few things deserve to be written down so they do not get forgotten.

Real user feedback. The project is currently informed by reading rather than by talking to actual returning citizens. This is the largest gap, and closing it should happen as soon as the system is far enough along to be worth testing on a real person.

Partner NGO conversations. The organizations whose phone numbers appear in the resource directory have not yet been contacted for feedback or partnership. Phase 2 expansion and Phase 4's web URL will be the moment to start that outreach.

Long term sustainability. Aim is not to monetize. Aim is to help. That said, the project needs some path to keep running long term. Directions under research: non profit status and grants, the DOJ Second Chance Act program, foundation funding for reentry work, partner organization fees for premium features like write back and trend reports, individual donations through Open Collective.

Real time bed counts and capacity. Most organizations do not publish their real time availability. Phase 2's stale data safety net handles the worst case (refuse to surface entries older than 180 days), but the underlying gap is real.

Texas state ID restoration coverage. The TDCJ release packet includes a temporary ID card that is supposed to make this easier, but the actual path is famously confusing. A specific Skill for this should land after speaking with someone who has actually walked it recently.

## 10. Lessons so far

A short list of observations, written as observations rather than rules so they can be revised later.

Architecture upfront pays for itself fast in safety critical domains. The two days on paper before opening an editor were the most leveraged hours in the project.

The Claude Code primitives are not interchangeable. Skills, sub agents, and hooks each solve a specific class of problem. Picking the right primitive per concern is the whole skill.

Demo mode without an API key is a feature, not a fallback. The deterministic templates in intake, draft, and audit let me write integration tests that run in six seconds and pass on a fresh checkout.

Progressive disclosure of Skills is real. The model behavior is meaningfully different between loading all seven Skills at session start and loading only the relevant one or two by description match.

The PWA versus native decision is a cost discipline question, not a UX question. For a non profit zero spend project, PWA is the only honest answer.

Pattern: every primitive should have a one sentence answer to "what failure mode does this prevent?" If I cannot produce that sentence, the primitive is decoration and should be removed.

## 11. Dev log

Chronological entries appended as work ships.

**2026-05-15.** Initial build day. Settings, CLAUDE.md, corpus, resources, seven Skills, four sub agents, three hooks, LangGraph state machine, FastAPI ingress, 30 tests, ARCHITECTURE and COMPLIANCE docs. Dockerfile and HF Spaces YAML committed. Deployed to https://prathik10-pathways.hf.space/. Health endpoint returns ok. Swagger live at /docs.

**2026-05-15 (later).** Phase 0 recruiter cut shipped. README rewrite with Try It in 30 Seconds, CI badge, plugin install instructions. New `.claude/plugin.json` for distributable Claude Code plugin packaging. New `docs/SHOWCASE.md` per primitive walkthrough. New `examples/sample_conversations.md` annotated dialogues. New `.github/workflows/ci.yml` runs pytest on every push, Python 3.11 plus 3.12. CI passes green. 30/30 tests still passing.

**2026-05-15 (latest).** Plan committed for Phases 1 through 6. Data inventory drafted covering the corpus expansion path (about 1,200 entries) and resource directory expansion path (about 5,000 records) with explicit free tier sourcing for each. Phase 4 expanded to include a PWA installable on iOS and Android via Add to Home Screen, deployed to Vercel. This journal written and committed.

**2026-05-16.** Crisis hook regex bugs found by acting as a user and fixed before Phase 1 starts. Live testing against `/_debug/invoke` showed three real bugs in the keyword list rather than a Docker path issue as initially suspected. The pattern `kill\s*myself` did not match the more common progressive form "killing myself"; fixed by adding `(ing|s|ed)?` to the verb. The pattern `don'?t want to live` only matched the contracted form; fixed by adding `do not` and `does not` alternates. The pattern `nowhere ... tonight` did not include the most common phrasing "nowhere to sleep tonight"; fixed by adding `(sleep|stay|go)` alternates. Eleven new parametrized regression tests added to `tests/test_hooks.py` covering the missed cases plus false-positive guards (idiomatic "kill some time" and the third-party threat routing to violence_to_others not suicide). Test suite grew from 30 to 41 tests, all passing.

**2026-05-16 (Phase 1 shipped).** Multi-turn stateful intake landed end to end. New module `pathways/sessions/` provides the checkpointer factory (memory / sqlite / postgres backends selected by `PATHWAYS_CHECKPOINT_BACKEND`), the salted SHA-256 `thread_id_for_phone` derivation (raw phone numbers never persisted as primary keys), and the Postgres-backed `inbound_message_dedup` table that prevents Twilio retries from double-processing a MessageSid. New `pathways/api/twilio_signature.py` wraps the official `RequestValidator` for HMAC-SHA1 verification on `/sms` with an explicit `PATHWAYS_SKIP_TWILIO_SIG` escape hatch for demo and tests. New `pathways/twilio_client.py` is a thin outbound `send_sms` wrapper that is trial-account aware (skips with a warning when the destination is not in `TWILIO_TRIAL_VERIFIED_NUMBERS`). The intake node was refactored into slot-filling: it now iterates over three required slots (name, location, top need) one prompt per turn, persists the partial profile via the checkpointer, and only routes to retrieve/match/draft/audit when all slots are filled. Backward compatibility was preserved by honoring `intake_complete=True` as a fast-path; existing single-shot tests still work without modification. State schema extended with `IntakeStage` enum, `name`, `age_range` (bucketed for PII reduction), `prison_facility`, `last_assistant_prompt`, and `channel`. The FastAPI ingress now derives the per-phone thread_id, verifies the Twilio signature, dedups MessageSid, handles TCPA `STOP / HELP / START` compliance keywords above the graph, and invokes the graph with `{"configurable": {"thread_id": tid}}`. A new test file `tests/test_phase1_intake.py` adds 34 tests across thread_id derivation, idempotency, slot extraction, multi-turn flow (turn 1 asks for name, turn 4 produces a real retrieval-backed reply), the Twilio signature verifier, and the `/sms` endpoint via `FastAPI TestClient`. Suite is now 75 tests, all green on Python 3.11 + 3.12. A Supabase free-tier Postgres project (`pathways`) was provisioned and validated end to end: the four-turn smoke test from a real phone hash persisted 17 checkpoint rows across the conversation, then cleaned them up. `psycopg-pool` was added to requirements because `from_conn_string` returns a context manager that closes the connection at exit; long-lived FastAPI processes need a pool. `JsonPlusSerializer(pickle_fallback=True)` was wired on all three backends because the default msgpack serializer cannot round-trip the Pydantic models in state (`Retrieval`, `IntakeProfile`, `AuditResult`). The plug interface for future Postgres deployments now requires only setting `DATABASE_URL` and `PATHWAYS_CHECKPOINT_BACKEND=postgres` as HF Space secrets.

**2026-05-16 (Phase 2 shipped).** Data layer scaffolded end to end. Schema work: two new Postgres tables (`resources` with 31 columns including lat/lon/county/workforce_region/accepting_clients/stale, `corpus` with 16 columns including pgvector embedding column for future hybrid retrieval) plus the `pgvector` extension enabled. Geo work: a vendored CSV of all 2,600 TX ZIP centroids from GeoNames (102 KB, all 254 TX counties represented), a hand-curated mapping of all 254 TX counties to the 28 TWC workforce regions, and a new `pathways/geo/` module exposing `zip_to_coords`, `county_for_zip`, `workforce_region_for_zip`, and `haversine_miles`. The geo helpers are pure functions with zero network or DB dependency; tests cover all major TX metros. MCP server work: both `pathways_corpus` and `tx_resources` gained a `BACKEND` env switch (file or postgres) with identical tool contracts across backends, so production can swap to Postgres without touching any node code. `tx_resources` got a new tool `find_resources_nearby(near_zip, category, top_k)` that haversine-ranks resources by distance from the user's ZIP, with a statewide fallback for safety (211 Texas, 988, etc. always reachable). The match node was wired to prefer the nearby ranker when `intake.zipcode` is set, with a graceful fallback chain to the existing region-substring filter. Ingester scaffolding: a `scripts/_common.py` module providing connection management, idempotent UPSERT helpers, automatic geo enrichment, and stale-data marking. A seed migration script moved the existing 18 resources and 65 corpus entries from JSON into Postgres with geo coords derived from a region-centroid fallback map. Real data: a `scripts/ingest_hrsa_fqhcs.py` that pulls all active TX FQHCs from the canonical HRSA public dataset and validated against the live CSV (832 active TX FQHC sites across 129 counties, 811 mapped to workforce regions across 27 of 28). The HRSA dataset includes geocoded lat/lon for every site, so a returning citizen in any TX ZIP gets distance-ranked sliding-scale healthcare options as soon as the ingester runs. Curated content: `scripts/curate_corpus.py` adds 30 hand-written federal CFR and TX statute entries covering HUD public housing rules, the SNAP drug-felony correction (the most-misunderstood TX reentry rule), Medicaid suspension during incarceration, SSI/SSDI reinstatement, the Pell Grant restoration, Federal Bonding Program, Texas expunction and non-disclosure law, the Texas occupational licensing chapter with the criminal history evaluation letter procedure, parole revocation hearing rules, driver license restoration after drug offenses, child support modification post-incarceration, voting rights, and jury disqualification. Pragmatically chose this over scraping eCFR + statutes.capitol.texas.gov because hand-written summaries are accurate and ship today; the scrapers are queued as Phase 6 work. `scripts/curate_metro_orgs.py` adds 30 hand-verified orgs filling the geographic gaps left by the seed JSON (Austin: ARCH/Caritas/Goodwill CTX/Central TX Food Bank; San Antonio: Haven for Hope/SA Food Bank/Restore Education; El Paso: Opportunity Center/Rescue Mission/Las Americas; RGV: Loaves & Fishes/Food Bank RGV/Pharr TLFP; DFW: The Bridge/UGM Tarrant/N TX Food Bank; Houston: Star of Hope/Houston Food Bank/SEARCH; Lubbock, Tyler, Beaumont, Waco, Corpus Christi, Amarillo plus statewide DV/reentry/recovery). Weekly refresh: `scripts/refresh_data.py` orchestrator runs every ingester in order and marks rows older than the per-source freshness window as `stale=true`. `.github/workflows/refresh-data.yml` runs on a Monday 09:00 UTC cron, gated by an `ENABLE_REFRESH` repo variable so it does not auto-run until the operator opts in. Tests grew from 75 to 95 (20 new tests covering geo helpers, ZIP-to-coords across all major TX metros, county and workforce-region resolution, haversine distance, the new `find_resources_nearby` tool, and end-to-end nearby ranking through the match node). All 95 green on Python 3.11 + 3.12 in CI. One important infra note: the ingesters are designed to run against the operator's own Postgres (Supabase free tier or equivalent) on demand, not as part of CI. The DATABASE_URL secret only needs to be set when the operator wants to refresh data, which is fine because the weekly cron is the only consumer once the initial backfill is done. After the operator runs the ingesters once, the data is live in Postgres and the HF Space (with `PATHWAYS_CORPUS_BACKEND=postgres` and `TX_RESOURCES_BACKEND=postgres` env vars) serves from there.

**2026-05-16 (Phase 3 shipped).** Bilingual support and multi-need routing landed. A Spanish-monolingual user texting "Hola, necesito ayuda con vivienda" now gets a Spanish slot-fill prompt back on turn one, and a user texting "I need food and a job" gets both pathways acknowledged in a single reply rather than only the first need being answered. The crisis hook gained 5 Spanish pattern blocks covering suicide ("me quiero matar", "ya no aguanto vivir", "acabar con todo", "no vale la pena seguir"), self-harm ("me corté", "hacerme daño"), substance crisis ("me sobredosé", "llevo toda la noche drogándome"), domestic violence in progress ("me está pegando ahora", "esconderme de él"), and housing emergency ("no tengo dónde dormir esta noche", "durmiendo en mi carro esta noche"). All accent-tolerant since basic phone keyboards often skip accents. New module `pathways/i18n/` provides a lightweight trigram language detector (no API calls, deliberately conservative per the trauma-informed rule that says not to infer language from a single word) and a bilingual string table for the deterministic TCPA STOP/HELP/START responses and the error fallback. The heuristic intake extractor was rewritten to collect ALL matching need categories instead of stopping at the first match, with parallel Spanish keyword coverage for each category. The match node iterates over the full need list (top + secondary), deduplicating matched orgs by ID across needs so an FQHC that serves both medical and benefits-enrollment does not appear twice. The draft node has full English and Spanish templates, with multi-need synthesis that leads with the most time-critical (housing > food > id/parole > benefits > employment > legal/record-clearing per trauma-informed reentry literature). Tests grew from 95 to 136 (41 new Phase 3 tests covering language detection across English and Spanish messages including single-Spanish-word-in-English-context false positive guards, bilingual table parity, Spanish crisis pattern firing plus false positive guards, multi-need heuristic extraction across single/double/triple need messages in both languages, multi-need match iteration with duplicate-ID protection, bilingual template draft output, and end-to-end Spanish multi-turn intake against the checkpointer-enabled graph). All 136 green on Python 3.11 + 3.12 in CI. Bug fix shipped alongside: the HRSA FQHC ingester's dedup key was collapsing multiple physical sites of one operator into a single row (because Health Center Location ID is a type code shared across sites, not a per-site identifier). Fixed to use Medicare Billing Number (unique per site) with NPI and address-hash fallbacks. Operator can re-run the ingester to grow resources from 462 to about 880. Deferred to Phase 3.5/Phase 6: the 7 full Spanish-sibling Skill bodies (raw machine translation does not survive the trauma-informed register; each Skill needs human review and ideally native-Spanish-speaker editing before shipping) and the outbound feedback SMS scheduler (depends on Twilio outbound config and a paid Twilio number; gating logic and queue table are scaffolded but the sender thread is not wired). Phase 4 (PWA installable on iOS + Android) is next.

Entries continue from here as work progresses.
