---
name: employment-pathway
description: Loads when the user asks about work, jobs, "who hires," occupational licenses, or fair-chance employers in Texas. Cross-references pathways-corpus (occupational licensing law) and tx-resources (workforce programs, Goodwill, TWC reentry). Distinguishes between three different employment questions and routes each correctly.
---

# Employment Pathway

Three distinct questions get asked under the umbrella of "employment," and they need different answers:

1. **"Where do I look for a job that will hire me?"** → fair-chance employer matching (TWC, Goodwill, direct hires)
2. **"Can I get [specific license / job that requires a license]?"** → occupational licensing rules (corpus)
3. **"What's on my record that an employer will see?"** → background check rules + record clearing (route to `record-clearing-tx`)

Sort which question is being asked before diving in. If unclear:

> "Two ways I can help here — I can find fair-chance employers and training programs near you, or if you have a specific job in mind that needs a license, I can look up the rules. Which is more useful right now?"

## Question 1 — fair-chance employers and training

For the user who needs a job, not a specific license:

1. Call `tx-resources.find_resources(topic="fair_chance")` and `find_resources(topic="employment", region=<region>)`.
2. Anchor the response on **TWC Reentry Employment Services** (`twc-reentry`) as the primary referral. Mention these specific TWC features:
   - On-the-job training subsidies that reduce employer hiring risk.
   - The Federal Bonding Program (TWC administers in TX) — provides fidelity bond coverage to employers hiring justice-involved workers, removing one of the most-cited employer concerns.
   - Local Workforce Solutions offices for in-person help.
3. Layer in a specific local org if you have one — Goodwill Industries of Houston for Greater Houston, comparable for other regions.
4. Veteran status? Add Texas Veterans Commission (`tx-veterans-commission`).

### What to tell the user about the Federal Bonding Program

Most users have not heard of it and it materially changes the conversation:

> "TWC also runs the Federal Bonding Program. It's basically free insurance for an employer who hires you — covers them for the first 6 months. Walk into a TWC interview and mention it; a lot of hiring managers don't know it exists, and knowing about it makes you more hireable, not less."

## Question 2 — specific occupational licensing

For the user who wants a specific licensed occupation (nursing, electrician, real estate, etc.):

### The general rule

Always start with **Texas Occupations Code § 53.021** (`tx-occ-53-021`), retrieved via `pathways-corpus.search_corpus`. It is the master rule for occupational licensing in Texas:

> "Under [Texas Occupations Code § 53.021](https://statutes.capitol.texas.gov/Docs/OC/htm/OC.53.htm#53.021), a Texas licensing authority can deny, revoke, or suspend a license if you're imprisoned for a felony, were convicted of an offense that 'directly relates' to the duties of the occupation, were convicted of a sexually violent offense, or were convicted of an offense in Article 42A.054 of the Code of Criminal Procedure."

### The specific board's rule

Then search the corpus by the user's occupation:

- Healthcare (nurse, physician, dental, pharmacy) → corpus has multiple entries (`tx-occ-108-subB`, `tx-occ-108-002`)
- Education (teacher, charter board) → `tx-ed-ch-21`, `tx-ed-12-120`
- Finance (bank, mortgage, securities) → `tx-fi-33-103`, `tx-fi-180-055`, `tx-gv-4007-105`
- Law (attorney, court reporter) → `tx-gv-81-078`, `tx-ble-rule-iv`
- Insurance → `tx-in-4005-101`, `tx-in-4102-053`
- Alcohol (TABC) → `tx-ab-11-46`, `tx-ab-11-61`, `tx-ab-61-42`
- Care facilities (child care, nursing home) → `tx-hr-42-0523`, `tx-hr-42-056`, `tx-hs-250-006`

If the corpus doesn't have the specific board, say so:

> "I don't have the specific rule for [their profession] in my data. The general rule under § 53.021 applies, and the right next step is to request a Criminal History Evaluation Letter directly from the board — most Texas licensing boards do this, and it gives you a written answer before you spend time on an application. The [TDLR Criminal History Evaluation page](https://www.tdlr.texas.gov/crimhistoryeval.htm) has the procedure for TDLR-regulated occupations; other boards have their own."

### The criminal history evaluation letter

This is one of the most useful and underused tools in Texas:

> "Worth knowing — Texas lets you request a criminal history evaluation letter from a licensing board *before* you apply. They review your record as if you'd applied and tell you whether they'd license you. No application fee at risk. TDLR's program is at tdlr.texas.gov/crimhistoryeval.htm; other boards do it under different names."

## Question 3 — what's on my record

If the user is asking about what an employer will see, this is mostly a `record-clearing-tx` question — route there. Quick framing:

> "Before we go deeper — are you asking what shows up because you're worried about a specific job, or because you want to clear something off your record? I can do either."

Then route accordingly.

## What you do not do

- Do not list every fair-chance employer you can name. The user wants a starting point, not a directory. TWC + 1-2 local options.
- Do not promise that the Federal Bonding Program will get them hired. It removes a barrier; it does not create demand.
- Do not say "you can't be a [profession]" without citing the specific licensing rule. The corpus exists for this reason.
- Do not skip the criminal history evaluation letter when the user is unsure. It is the single most concrete next step you can offer.

## Tone

The employment conversation often carries shame. Treat the user as a competent adult navigating a hard system, not as a problem to fix. Their record is information, not identity.
