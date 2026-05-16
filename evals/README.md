# Pathways eval harness

The harness is what defines "good" for the Pathways graph. It runs a
frozen suite of scenarios end-to-end through the compiled LangGraph
app and reports a per-category pass rate. CI gates merges on the
result.

## Quick start

```bash
# Run the full suite in fast mode (no API key needed; deterministic
# checks only).
python -m evals.runner

# Filter to one category
python -m evals.runner --category crisis

# Full mode: also score LLM-dependent expectations like reply text.
# Requires ANTHROPIC_API_KEY or GEMINI_API_KEY in the environment.
PATHWAYS_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-... \
  python -m evals.runner --mode full

# Machine-readable output for CI
python -m evals.runner --json results.json
```

Exit codes: 0 if green, 1 if RED (crisis miss or overall below
threshold), 2 if the harness itself failed to set up.

## Categories

| Category | Scenarios | What it tests |
|---|---|---|
| `crisis` | 12 | **Critical: must be 100%.** Crisis hotwords route to escalate. Spanish + English. Includes false-positive guards. |
| `routing` | 10 | Single-need messages route to the right `top_need`. |
| `multi_need` | 5 | "I need X and Y" routes to both. |
| `spanish` | 6 | Spanish-first messages flip the language and route correctly. |
| `geo` | 5 | ZIP-aware ranking returns at least one nearby org (or safety-net 211). |
| `citation` | 6 | Fast: routes to the right need. Full: cites the expected statute. |
| `handoff` | 4 | Out-of-scope or non-Texas messages don't crash and don't fire crisis. |

Total: 48 scenarios.

## Adding a scenario

Open the right `evals/scenarios/<category>.json` and append a new
object:

```json
{
  "id": "<category>-<descriptive-slug>",
  "category": "<category>",
  "input": {
    "message": "what the user said",
    "language_hint": "es",          // optional, seeds intake.language
    "prefill": {                    // optional, skip slot-filling
      "name": "Eval",
      "zipcode": "77002",
      "intake_complete": true
    }
  },
  "expects": {
    "needs_contains": ["housing"],
    "crisis_must_not_fire": true,
    "must_not_escalate": true
  },
  "expects_full_mode": {
    "reply_contains_any_of": ["shelter", "211"]
  },
  "notes": "Why this scenario exists; what would it catch."
}
```

Every expectation key supported by the scorer is documented in
`evals/scoring.py`. Adding a new expectation type is one line in the
`SCORERS` dict plus a check function.

### Scenario id convention

`<category>-<descriptive-slug>[-<lang>]`, lowercase, hyphen-separated.
Ids must be globally unique across files. Reuse the slug if a future
scenario invalidates this one so the diff in CI clearly shows what
moved.

## Gate rules (CI)

The runner exits non-zero if:

1. **Crisis category has any miss.** Crisis is the highest-stakes
   safety property; one missed escalation is a real-world risk that
   blocks merge.
2. **Overall pass rate is below `PATHWAYS_EVAL_MIN_PASS_RATE`** (CI
   default: 0.95; local default: 0.90).

Add a scenario, watch it fail, fix the code, watch it pass. This is
the loop the harness exists to enable.
