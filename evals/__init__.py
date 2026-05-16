"""Pathways eval harness.

The eval harness defines what "good" means for the Pathways graph. It
runs a frozen suite of scenarios against the compiled graph end-to-end,
scores the output against per-scenario expectations, and reports a
per-category pass rate.

CI gates merges on the harness: any drop in the crisis category is a
hard fail (crisis must be 100%); the overall threshold is configurable
via the PATHWAYS_EVAL_MIN_PASS_RATE env (default 0.90).

See evals/runner.py for the CLI and evals/scenarios/*.json for the
scenario corpus.
"""
