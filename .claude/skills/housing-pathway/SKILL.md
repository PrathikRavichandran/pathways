---
name: housing-pathway
description: Loads when the user asks about housing, shelter, transitional living, public housing eligibility with a record, or rental denials based on criminal history. Combines tx-resources (find local housing options) with pathways-corpus (HUD rules, fair-chance housing law) and routes time-sensitive shelter needs to 211 Texas.
---

# Housing Pathway

Housing is often the first crisis a returning citizen faces and the one that compounds the fastest. Lose stable housing, lose contact info, lose a parole reporting address, lose the job interview address. The protocol below treats housing as time-staged: tonight, this week, this month.

## Triage first — what's the timescale?

Ask one question early if it isn't clear:

> "Quick check — are you looking for somewhere to stay tonight, or for a more stable place over the next few weeks?"

- **Tonight** → emergency shelter route, see "Tonight" below.
- **This week** → transitional housing + shelter waitlist + benefits navigation, see "This week."
- **This month or longer** → fair-chance rental + public housing application paths, see "Long term."

If they say "I don't know" or "all of it" → assume tonight and route accordingly; you can layer the rest on once they're stable.

## Tonight (within 24 hours)

If the user has nowhere to sleep tonight:

1. Call `tx-resources.find_resources(topic="shelter", region=<user_region>)`.
2. Surface 211 Texas first — it's the right escalation path regardless: `phone: "211"`, `text: "Text TXHELP to 898211"`.
3. If user is in Greater Houston, surface Salvation Army Greater Houston (`salvation-army-houston`). If DFW, surface comparable.
4. If you don't have a high-confidence local option, do not invent one. Say so:
   > "I don't have a verified shelter in [their town] in my data. 211 Texas (dial 211) is the right call — they're 24/7 and will know the closest open bed tonight."

Do not ask the user a long form of questions to identify shelter eligibility. The shelter intake will do that. Your job is to get them to the right phone number, fast.

## This week (3-14 day window)

If the user has a temporary place but needs something more stable:

1. Workforce + housing together — many transitional programs are tied to employment programs. Reference Goodwill Houston, Salvation Army Adult Rehabilitation Center if substance recovery is a factor.
2. If user is on parole, mention that TDCJ Reentry and Integration Division can sometimes assist with transitional placement (`tdcj-reentry`).
3. Help them get on the 211 callback list if not already.

## Long term (rental or public housing)

This is where the corpus matters. Key rules:

### Federal public housing rules

Search corpus for `public housing` and surface:

- **`hud-mandatory-denials-pha`** — Federal regulation requires Public Housing Agencies (PHAs) to deny admission to (a) persons subject to lifetime sex offender registration and (b) persons convicted of methamphetamine production on federally-assisted property. *Other criminal history is subject to PHA discretion under their written admission policies.* This is the most important corrective to misinformation: a PHA cannot simply deny everyone with a felony.
- **`hud-pih-2015-19`** — HUD guidance clarifies that an arrest alone is not sufficient to deny admission, terminate assistance, or evict. Convictions may be considered subject to individualized assessment.

Translation for the user:
> "Public housing in Texas isn't an automatic 'no' for a felony. Federal rules require denial only in two specific cases — lifetime sex offender registration or a meth production conviction on federally-assisted property. Beyond that, each Public Housing Authority sets its own policy, and federal guidance ([HUD PIH-2015-19](https://www.hud.gov/sites/documents/PIH2015-19.PDF)) says arrests alone aren't enough to deny. Worth applying."

### Private rental

There's no Texas-specific fair-chance rental law that broadly bans criminal-history-based denial in private rentals. Landlords can use criminal history in screening; many use national screening services that pull state databases.

What to tell the user:
- Private screening is allowed and common.
- The Texas Apartment Association does not require an automatic denial for criminal history; individual properties set their own rules.
- Some property managers will respond well to a "letter of explanation" — context on the offense, time elapsed, current employment, character references. Worth preparing.

### Driver's license and address

If the user is trying to rent and has no current ID, prioritize ID first. Call `find_resources(topic="state_id")` → `tx-id-recovery-program`.

## When to escalate to legal aid

If the user describes a denial they think is unlawful (e.g., a PHA denying for an arrest with no conviction, or eviction without notice), route them to legal aid:

> "What you're describing sounds like something Lone Star Legal Aid handles. Their housing line is 1-800-733-8394. They take housing cases for people in your area for free."

## What you do not do

- Do not list shelters across the entire state — the user is in one place. Match the region.
- Do not promise availability. *"Salvation Army has beds tonight"* — you can't know that. *"Salvation Army Greater Houston is one of the larger shelters in the area — they can tell you tonight if they have an open bed"* is what to say.
- Do not assume the user has internet to fill out an online application. SMS-first means voice-friendly. Phone numbers over URLs when both exist.
