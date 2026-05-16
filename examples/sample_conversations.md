# Sample Conversations

Five worked end-to-end conversations through pathways. Each shows the **user message**, the **primitive activations** (which Skill loaded, which hook fired, which MCP server was called, which sub-agent audited), and the **reply** the user actually receives.

These are not aspirational — they correspond to behaviors you can reproduce against the live demo:

```bash
curl -X POST https://prathik10-pathways.hf.space/_debug/invoke \
  -H "Content-Type: application/json" \
  -d '{"message":"<paste any user message below>"}'
```

The `/_debug/invoke` endpoint returns the full final state — every node that fired, the retrieval payload, the audit verdict, and the final response. Use it as the ground-truth view into what the architecture actually did.

---

## Conversation 1 — Housing crisis (escalate path)

**User (SMS):** *"I just got out yesterday and I'm sleeping in my car tonight. I don't have anywhere to go."*

### What fires

| Stage | Primitive | Result |
|---|---|---|
| Pre-graph | **`crisis_keyword_check`** hook | Matches `housing_emergency` pattern (`"sleeping in my car tonight"`). Returns `CrisisSignal(fired=True, category="housing_emergency")`. |
| Graph node `intake` | LangGraph | Reads `state.crisis.fired=true`, routes directly to `escalate`. Skips retrieve / match / draft / audit. |
| Graph node `escalate` | LangGraph | Looks up category-matched escalation message for `housing_emergency`. |
| Skill loaded for next turn | **`crisis-response`** Skill | Trauma-informed protocol stays loaded for the rest of the session. |

### Reply (TwiML SMS back to user)

> *"Tonight comes first. Call 211 right now — they have shelter beds and can route you to one tonight. From any phone: just dial 2-1-1.*
>
> *If you can't reach 211, the Salvation Army Greater Houston intake line is (713) 752-0677 and they accept walk-ins.*
>
> *I'm here when you have a roof. Text me back tomorrow morning and we'll figure out the next step."*

### Why this matters architecturally

The user **never has to wait** for the retrieve→match→draft→audit pipeline when there's an immediate-harm signal. The crisis hook short-circuits the graph at intake. The escalation message is deterministic — no LLM call needed — because the 211 phone number is not something we want a model to "compose" under load. The `crisis-response` Skill loading for follow-up turns means the next message gets the right register, not the standard navigator chattiness.

---

## Conversation 2 — Voting eligibility (corpus citation path)

**User (SMS):** *"Can I vote in Texas if I'm on parole?"*

### What fires

| Stage | Primitive | Result |
|---|---|---|
| Pre-graph | **`crisis_keyword_check`** hook | No match. Pipeline continues. |
| Graph node `intake` | LangGraph | Extracts `top_need: civil_rights`, `subtopic: voting`. Sets `intake_complete=true`, routes to retrieve. |
| Graph node `retrieve` | **`pathways-corpus`** MCP server | Calls `search_corpus(query="voting parole Texas", category="civil_rights")`. BM25 returns top-1 match: `tx-elec-11-002` (Texas Election Code § 11.002), confidence 0.84. |
| Post-tool | **`rag_confidence_gate`** hook | Confidence (0.84) > floor (0.62). Result passes through unchanged. |
| Skill loaded | **`niccc-lookup`** Skill | Cite-or-don't-claim contract is now active. |
| Graph node `draft` | Sonnet | Composes reply citing § 11.002 with link. |
| Graph node `audit` | **`compliance-auditor`** sub-agent (Haiku, read-only) | Validates: claim has citation ✓, scope is TX ✓, no outcome promise ✓, trauma-informed tone ✓. Verdict: `pass`. |
| Graph node `send` | LangGraph | Promotes draft to `final_response`. |

### Reply

> *"In Texas you can vote again — but only after you've **fully discharged your sentence**, which means parole, probation, and any post-release supervision are all complete (Texas Election Code [§ 11.002](https://statutes.capitol.texas.gov/Docs/EL/htm/EL.11.htm#11.002)).*
>
> *So while you're still on parole, no — voting would be illegal. The day your parole officially ends, you become eligible again and you can re-register at votetexas.gov or at any county elections office.*
>
> *If you want help confirming your discharge date, the Texas Board of Pardons and Paroles can give you that in writing."*

### Why this matters architecturally

Three primitives composed: corpus MCP returned a real citation, the confidence-gate hook decided the citation was strong enough to ship, and the compliance-auditor sub-agent validated the draft cited the source rather than asserting from memory. If retrieval confidence had been below 0.62, the hook would have rewritten the result and the user would have received "*Voting after a conviction in Texas depends on whether you've fully discharged your sentence — I'd rather connect you with a real navigator at Texas Civil Rights Project than guess on this one.*" instead.

---

## Conversation 3 — Driver license restoration (the SNAP-style misinformation pattern)

**User (SMS):** *"My felony was 2018 state jail for possession. Can I get my driver's license back or is it permanent?"*

### What fires

| Stage | Primitive | Result |
|---|---|---|
| Pre-graph | **`crisis_keyword_check`** hook | No match. |
| Graph node `intake` | LangGraph | Extracts `top_need: drivers_license`, `subtopic: reinstatement_after_drug_offense`. |
| Graph node `retrieve` | **`pathways-corpus`** MCP server | `search_corpus(query="drug felony driver license suspension Texas")` returns `tx-trans-521-372` (Transportation Code § 521.372 — drug offense suspension), confidence 0.79. |
| Graph node `match` | **`tx-resources`** MCP server | `find_resources(category="id_documents", region="statewide")` returns Texas DPS Driver License Division + TDCJ ID assistance + a regional Goodwill that has helped clients with reinstatement. |
| Skill loaded | **`niccc-lookup`** Skill | (Could also load `record-clearing-tx` if the user asked about clearing it.) |
| Graph node `draft` | Sonnet | Composes reply correcting the "permanent" misconception, explaining the 180-day administrative suspension that ended years ago, and giving the steps to reinstate. |
| Graph node `audit` | **`compliance-auditor`** sub-agent | Verdict: `pass`. |

### Reply

> *"It's not permanent. A 2018 drug-possession conviction in Texas triggered a **180-day** administrative suspension under [Transportation Code § 521.372](https://statutes.capitol.texas.gov/Docs/TN/htm/TN.521.htm#521.372). That suspension ran out years ago.*
>
> *To actually get the license back you need: (1) pay any outstanding reinstatement fees at the TX DPS, (2) clear any old tickets/warrants in the counties they were issued, and (3) if you've been off insurance for a while, get an SR-22 from any insurer.*
>
> *The DPS Driver License Division can confirm exactly what's outstanding on your record. Their main line is (512) 424-2600, or you can use the office locator at dps.texas.gov. Want me to find the closest DPS office to your zip?"*

### Why this matters architecturally

This is the same misinformation pattern as the SNAP drug-felony myth in the [`benefits-navigator`](../.claude/skills/benefits-navigator/SKILL.md) Skill. The model could easily echo "yes, your license is permanently suspended" because that's a common belief. The Skill encodes the correct rule + the corpus citation, the auditor verifies it shipped with the cite, and the model can never confidently say "permanent" without evidence — because evidence comes from `pathways-corpus`, and the corpus says otherwise.

The reply also exemplifies the architecture's offer-the-next-step pattern: it ends with *"Want me to find the closest DPS office to your zip?"* — turning a one-shot Q&A into a multi-turn navigator interaction (which Phase 1 of the roadmap makes stateful).

---

## Conversation 4 — Multi-need stack (housing + employment + ID)

**User (SMS):** *"I just got out a week ago. I need a place to stay, I need to get my Texas ID back, and I want to find work. I'm in Houston."*

### What fires (in current single-turn mode)

| Stage | Primitive | Result |
|---|---|---|
| Pre-graph | **`crisis_keyword_check`** hook | No match. |
| Graph node `intake` | LangGraph | Extracts three needs but routes on the first time-critical: `housing`. (Phase 3 of the roadmap fixes this to route on all three.) |
| Graph node `retrieve` | **`pathways-corpus`** MCP | Returns HUD eligibility rules. |
| Graph node `match` | **`tx-resources`** MCP | `find_resources(category="housing", region="Houston")` returns Star of Hope + Salvation Army Greater Houston + 211 Texas. |
| Skill loaded | **`housing-pathway`** Skill (time-staged triage) | |
| Graph node `audit` | **`compliance-auditor`** | `pass`. |

### Reply (today — Phase 0)

> *"Housing first, since it's the foundation for everything else. In Houston: Star of Hope ((713) 222-2220) and the Salvation Army Greater Houston ((713) 752-0677) both accept walk-ins for emergency shelter. 211 Texas can also route you to whichever shelter has open beds tonight — just dial 2-1-1.*
>
> *Once you have a roof, the TX state ID and the job search are 2-3 day workstreams each. Reply when you've got somewhere to sleep and I'll walk you through the ID and the job-search pieces."*

### Reply (Phase 3 of the roadmap — multi-need)

> *"That's a lot at once. Let's do them in order of urgency.*
>
> ***Tonight:*** *Star of Hope (713-222-2220) or Salvation Army Greater Houston (713-752-0677) for emergency shelter. 211 also routes to open beds — dial 2-1-1.*
>
> ***This week — TX ID:*** *Goodwill Houston's reentry program (713-692-6221) helps with ID reinstatement and they know the TDCJ-issued temporary-ID quirks.*
>
> ***Next:*** *TWC Reentry Initiative (twc.texas.gov/reentry) has fair-chance employer connections in Houston — call after you have a stable address."*

### Why this matters architecturally

The single-turn limitation today is honest: the architecture handles ONE primary need cleanly. Phase 3 extends `IntakeProfile.top_need` to `IntakeProfile.needs: list[TopNeed]`, the match node iterates, and the draft node synthesizes with the trauma-informed-literature ordering (housing > food > employment). The Phase 0 reply is honest about the constraint — *"reply when you've got somewhere to sleep"* — rather than pretending to handle everything at once.

---

## Conversation 5 — Spanish (Phase 3 preview)

**User (SMS, Spanish):** *"Salí de la cárcel ayer y no sé qué hacer. Necesito comida y un lugar para dormir."*
*("I got out of jail yesterday and I don't know what to do. I need food and a place to sleep.")*

### What fires today (Phase 0)

| Stage | Primitive | Result |
|---|---|---|
| Pre-graph | **`crisis_keyword_check`** hook | English-only patterns today; Phase 3 adds Spanish (`me quiero matar`, `acabar con todo`, etc.). No match here regardless — this isn't crisis-keyword territory. |
| Graph node `intake` | LangGraph | English Skills attempt extraction. Captures `top_need: housing` (heuristic matches "lugar para dormir" via partial-word fallback). |
| Graph node `draft` | Sonnet | Composes reply in English by default. |

**Today the reply is in English** — which is wrong for a Spanish-monolingual user. Phase 3 of the roadmap ships:

- 7 Spanish-sibling Skills (`-es` suffix), each human-reviewed (not raw machine translation)
- Spanish patterns in `crisis_keyword_check`
- `pathways/i18n/detect.py` lightweight language detection
- `compliance-auditor` rule: Spanish-in → Spanish-out

### Reply (Phase 3)

> *"Esta noche es lo primero. Llama al 2-1-1 — tienen camas en albergues y pueden conectarte con uno esta noche. Desde cualquier teléfono, marca 2-1-1.*
>
> *Para comida hoy: el Houston Food Bank (832-369-9390) tiene despensas abiertas hoy en varias zonas.*
>
> *Escríbeme mañana en la mañana y seguimos con los siguientes pasos."*

### Why this matters architecturally

Spanish is not "an option to enable" — it's a structural extension that touches every primitive: hooks gain Spanish patterns, Skills get bilingual siblings, the auditor learns the language-consistency rule, the responses table doubles in size. Phase 3 ships all of these as one coherent unit because shipping any one of them without the others produces an inconsistent experience (e.g., a Spanish-loaded Skill but an English crisis hook = the highest-stakes message in the system is in the wrong language).

---

## How these conversations relate to the roadmap

| Conversation | Phase 0 reality | Roadmap phase |
|---|---|---|
| 1 — Housing crisis | ✅ Works today | — |
| 2 — Voting eligibility | ✅ Works today | — |
| 3 — Driver license restoration | ✅ Works today | — |
| 4 — Multi-need stack | ⚠️ Single-need routing today | Phase 3 |
| 5 — Spanish | ❌ English reply today | Phase 3 |

The pattern: the architecture is sound, the Phase 0 demo is honest about what works, and every gap has a planned phase. That's the right disclosure posture for a recruiter looking at a real piece of work, not a polished but hollow demo.
