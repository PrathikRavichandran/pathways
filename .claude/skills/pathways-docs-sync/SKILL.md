---
name: pathways-docs-sync
description: Loads when the user merges a PR in the Pathways repo and wants the existing project documentation re-synced to match what was just shipped. Triggers on phrases like "PR merged update docs", "sync the pathways docs", "docs out of date after the merge", "we just shipped X, refresh the docs", or proactively right after any `gh pr merge` / merge-commit in this working directory. The Skill walks a fixed checklist of doc files (README.md, STATUS.md, docs/JOURNAL.md, docs/ARCHITECTURE.md, docs/SHOWCASE.md, docs/COMPLIANCE.md, docs/PHASE6_DEFERRED.md, docs/INTERVIEW_BRIEFING.md) and applies the right edit to each so the Pathways narrative stays internally consistent across the public surface. Does NOT trigger on PRs in other repos, on doc edits unrelated to a merge, or on first-time doc creation; for those use a generic write-docs flow. Standing instruction from the operator (2026-05-18): run this Skill after every Pathways PR merge.
---

# pathways-docs-sync

Project-specific Skill for the Pathways repo. Codifies the repetitive after-every-PR documentation update so the narrative across README, STATUS, JOURNAL, ARCHITECTURE, SHOWCASE, COMPLIANCE, PHASE6_DEFERRED, and INTERVIEW_BRIEFING stays consistent without manual diff hunting.

## When to fire

Triggers:
- Operator says something like "PR merged, sync the docs" / "update the docs after that merge" / "the docs are out of date" while in the Pathways working directory.
- Operator merges a PR via `gh pr merge` and the surface area of the change touches code, tests, workflows, or dependencies (not just doc-only PRs).
- Operator explicitly invokes `/pathways-docs-sync` or otherwise asks for a "post-merge sync."

Do NOT fire on:
- PRs in unrelated repos. This Skill is scoped to Pathways only.
- Doc-only PRs whose ONLY changes are inside `docs/` or `README.md` — the merge IS the update; running again would loop.
- Branches that have not been merged yet. Use the normal PR-prep flow instead.

## Standing operator instruction

From 2026-05-18: the operator wants this Skill run after every merged PR in the Pathways repo. When a merge happens in this working directory and any of the trigger phrases appear, run without asking for confirmation. Always open a PR with the updates rather than committing directly to `main` so the doc updates have their own review surface.

## Protocol

### Step 1: Establish what changed

```bash
# What just merged?
gh pr list --state merged --limit 5 --json number,title,mergedAt,body

# What files did each PR touch?
gh pr view <number> --json files,title,body
```

Read the merged PR titles + bodies. The PR body usually states the user-visible change ("adds X", "fixes Y"). Use it to decide whether each doc file actually needs an edit. If a PR only touched test plumbing or formatting, most docs do NOT need updating; only `docs/JOURNAL.md` does.

### Step 2: Decide which doc files need to be touched

Walk this fixed checklist. For each file: open if relevant, skip if not, never blind-rewrite.

| File | Update when | What to edit |
|---|---|---|
| `README.md` | Test counts changed, version moved, a new feature shipped, deploy pipeline changed, or a new top-level doc was added | The Tests badge, the `> Status:` line, the `## ⚡ Try it in 30 seconds` table (esp. the `/health` row), the `## What's shipped vs. deferred` table, the `## What's next` operator-side wiring list |
| `STATUS.md` | Any user-visible subsystem changed state, test counts moved, version moved, or operator setup steps changed | The Live URLs table, the "What's running right now" table (add the new row), the Quality signal block (test counts), the Operator setup commands |
| `docs/JOURNAL.md` | Always, for any non-trivial merged PR | Append one dated entry per merged PR right above the closing `Entries continue from here as work progresses.` line. Follow the existing voice: dense paragraph, file paths and counts inline, document what shipped AND what was deferred-with-rationale |
| `docs/ARCHITECTURE.md` | A new architectural seam was touched, or a new subsystem joined the topology | Add a numbered section (or extend §11 "Phase N additions") describing what was added without restructuring the existing sections. Architecture changes are rare; most PRs do not touch this file |
| `docs/SHOWCASE.md` | A new Claude Code primitive was added, or an existing primitive's worked example changed | Add or extend the "Phase N additions" appendix at the end. Don't rewrite the primitive sections in place — append |
| `docs/COMPLIANCE.md` | A new audit / observability stream was added, or a safety property's enforcement layer changed | Extend the Audit trail bullet list. Update Known gaps if the merge closed one |
| `docs/PHASE6_DEFERRED.md` | A previously-deferred item shipped, or a new deferred item was identified with a documented unblock criterion | Add a note at the top mentioning the shipped items by phase + JOURNAL pointer. Don't delete the deferred entries; they're a historical record of why we made the call we made |
| `docs/INTERVIEW_BRIEFING.md` | A new feature changes what's true in §4 (Claude Code primitives), §11 (future roadmap), or §15 (file paths to cite cold) | Surgical edits only. The briefing is a study artifact tuned for cold-readability; don't bloat it with every internal detail. Update test counts in §9. Update the roadmap in §11 if an item moved deferred → shipped |

### Step 3: Classify the PR + bump the version

**Operator standing instruction (2026-05-18):** every merged PR bumps the version unless the operator says otherwise. The Skill picks the bump size by classifying the PR, then proposes it to the operator before committing.

**SemVer classification rules.** Read the merged PR's title, body, and `gh pr view <N> --json files` to pick the bump size:

| Bump | Trigger | Examples |
|---|---|---|
| **PATCH** (`X.Y.Z → X.Y.(Z+1)`) | Bug fix, doc-only change, internal refactor, dependency bump, ops automation, CI workflow change, test additions, observability additions (logs / metrics that don't change user-visible behavior). Anything that doesn't add a new capability the user can see. | Docs sync, `actions/checkout` bump, adding tests, the `pathways-docs-sync` Skill itself (no user-visible change), structured logging additions, demo-seed enrichment. |
| **MINOR** (`X.Y.Z → X.(Y+1).0`) | New user-visible feature, backward compatible. A user can do something they couldn't do before. | Map view above resource cards (PR #1), CI auto-deploy workflow (PR #2 — debatable, MINOR is defensible because it changes operator workflow), a new Skill loaded by users, a new MCP tool. |
| **MAJOR** (`X.Y.Z → (X+1).0.0`) | Breaking change to the public API contract. A previously-working integration breaks. | Removing a `/web/turn` field, changing the salted-hash thread-ID derivation salt (breaks existing session resume), changing the SMS reply shape, deleting an MCP tool. Rare. Hold for genuinely breaking changes; do NOT use for milestone marketing. The operator explicitly bumped to 1.0.0 on 2026-05-18 as a one-time milestone — that's an override, not the default rule. |

**Defaults that resolve ambiguity:** when in doubt between PATCH and MINOR, prefer PATCH. Better to under-bump and correct on the next PR than to inflate the version. When in doubt between MINOR and MAJOR, ALWAYS pick MINOR unless the operator explicitly authorizes MAJOR — wrong major bumps look like marketing inflation.

**Compute the next version:**
1. Read the current version from `pathways/api/main.py` (search for `"version":`).
2. Parse as `X.Y.Z`.
3. Apply the bump based on the classification above.
4. Propose to the operator: "PR #N looks like a {patch|minor|major} change. Bumping {current} → {next}. OK to proceed, or override?"
5. After confirmation (or after a clear yes-by-default in the operator's standing instruction), continue with the update.

### Step 4: Apply consistent values

These values change together. Update them everywhere they appear in one pass.

| Value | Where it appears |
|---|---|
| Test count (currently 305 unit + 73 evals) | README badge, README `> Status:` line, STATUS Quality signal, INTERVIEW_BRIEFING §9 |
| Version string | `pathways/api/main.py:110` (source of truth — search for `"version":`), README `/health` example, STATUS `/health` row. Also mention the new version in the JOURNAL entry for this merge. Re-run `grep -rn "<old-version>" .` after the bump to catch any references this Skill didn't anticipate. |
| Phase number (currently Phase 7 complete) | README `> Status:` line, JOURNAL new entry, ARCHITECTURE §11 heading if extended, SHOWCASE §9 heading if extended |
| Modules list in `/health` | README `/health` example, STATUS `/health` row. Currently `["dashboard","parole_reminders","writeback","audit"]` |
| Workflow inventory | README "What's next" operator-setup numbering, STATUS Operator setup block. Currently 5 workflows: ci, evals, daily-cron, refresh-data, deploy-hf |
| Pinned action versions in workflows | All four workflow files under `.github/workflows/`. Currently `actions/checkout@v5`. Bump together when GitHub deprecates an action version (the deploy-hf logs surface a `::warning::` when a workflow uses a deprecated action). |

### Step 5: Write the JOURNAL entry

The JOURNAL has a specific voice — dense paragraph form, no bullet lists inside an entry, file paths inline as `path/to/file.py`, counts inline as parenthetical asides ("305 unit tests (241 → 305 from ...)"). One entry per merged PR. Format:

```
**YYYY-MM-DD (short title).** Shipped as PR #<N> against main: <one-sentence summary>. <Backend / Frontend / Tests / Ops paragraphs as needed>. <Quality signal in numbers>. <Known follow-ups flagged in PR body, if any>.
```

Append above the closing `Entries continue from here as work progresses.` line. Date matches the merge date, not the open date.

### Step 6: Open a single PR for all doc updates

```bash
git checkout main
git pull origin main
git checkout -b docs/sync-after-pr-<N>
# apply edits across all relevant files in one go
git add README.md STATUS.md docs/
git commit -m "$(cat <<'EOF'
docs: sync after PR #<N> (<short title>)

<one-paragraph summary of which docs were touched and why>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push -u origin docs/sync-after-pr-<N>
gh pr create --title "docs: sync after PR #<N>" --body "$(cat <<'EOF'
## Summary
- Re-syncs the public doc surface to match what shipped in PR #<N>.
- Files touched: <list>.
- No code changes.

## Verification
Visual diff of each updated file confirms the test counts, version, status line, and feature mentions are all internally consistent across README / STATUS / JOURNAL / ARCHITECTURE / SHOWCASE / COMPLIANCE / PHASE6_DEFERRED / INTERVIEW_BRIEFING.
EOF
)"
```

### Step 7: Report back

After opening the PR, hand back to the operator with a tight summary:
- Number of files touched
- The PR URL (wrapped in `<pr-created>` tags so the harness renders the status card)
- Any doc that was intentionally NOT touched and why (so the operator can override if needed)
- The standing instruction reminder: this Skill should fire automatically after the next merge; the operator does not need to type the prompt each time, just confirm.

## What this Skill is NOT for

- Creating new documentation from scratch (use a different write-docs flow or just write it directly).
- Reviewing a PR's code (use `/review` or the security-review Skill).
- Bumping the version in `pathways/api/main.py::/health` (currently a manual operator call; revisit if a release process emerges).
- Cross-repo doc sync (this Skill knows only about the Pathways layout).

## Notes for future me

- The doc files have **distinct voices**: README is recruiter-facing and prose-tight, STATUS is operator-facing and table-dense, JOURNAL is dense narrative, ARCHITECTURE and SHOWCASE are technical-reader oriented, COMPLIANCE is auditor-oriented, INTERVIEW_BRIEFING is cold-readable rehearsal material. Match the voice when editing. Don't paste the same paragraph into all of them.
- The JOURNAL grows linearly. Never delete or reorder old entries; they are the project's memory.
- ARCHITECTURE has a §10 iteration roadmap that was written before Phase 4. Don't try to edit that roadmap retroactively; the roadmap is wrong by design (it was a snapshot of intent at the time) and the §11+ appendix is where shipped truth lives.
- The deploy-hf.yml workflow auto-deploys merged main to the HF Space within ~5 minutes. Doc PRs go through the same pipeline. Be mindful that landing a doc-only PR triggers a Docker rebuild on HF; if you're doing many small doc commits, batch them into one PR to avoid spinning HF unnecessarily.
- The deploy-hf logs surface GitHub Actions deprecation warnings near the bottom of every run. When you see `::warning::Node.js NN actions are deprecated`, that is the signal to open a chore PR bumping the affected `uses: actions/<name>@vN` lines across all four workflows. Treat this as a recurring housekeeping task — small but real, easy to forget until something breaks.
- The version-bump rule (Step 3) was added 2026-05-18 after the operator noted that 0.7.0 stayed pinned across two big PRs. The default is PATCH; reach for MINOR only when the merged change adds a capability the user can see. Wrong-direction bumps are very visible because the version is in the README, the live `/health`, and the JOURNAL, so they get caught.
