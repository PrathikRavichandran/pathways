"""
refresh_data.py: weekly orchestrator. Runs every ingester in order,
then marks anything not refreshed in this cycle as stale.

Designed to run as a GitHub Action cron. Skips ingesters that hit a
soft error (network blip on a single source should not break the whole
cycle). Writes a short summary to stderr that the CI job picks up as a
notice on the workflow run.

Run locally:
    DATABASE_URL=postgresql://... python -m scripts.refresh_data

Run in CI (see .github/workflows/refresh-data.yml).
"""

from __future__ import annotations

import importlib
import time
from typing import Callable

from scripts._common import get_conn, log, mark_stale_older_than

# Ordered list of (module, source_tag, stale_after_days). The source tag
# is the same value used by upsert_*() so the stale-data marker can flag
# unrefreshed rows from THIS ingester only.
PIPELINE: list[tuple[str, str, int]] = [
    ("scripts.ingest_hrsa_fqhcs", "hrsa_fqhc", 30),
    ("scripts.curate_corpus", "curated_federal_and_tx", 180),
    ("scripts.curate_metro_orgs", "curated_metro", 90),
]


def _run_module(module_path: str) -> tuple[bool, str]:
    """Import the module and call its main(). Returns (ok, message)."""
    try:
        mod = importlib.import_module(module_path)
        rc = mod.main()
        return (rc == 0, f"rc={rc}")
    except Exception as exc:
        return (False, f"{type(exc).__name__}: {exc}")


def main() -> int:
    log("Pathways weekly data refresh starting...")
    ran: list[tuple[str, bool, str, float]] = []

    for module_path, _tag, _stale_days in PIPELINE:
        log(f"\n--- {module_path} ---")
        t0 = time.time()
        ok, msg = _run_module(module_path)
        dt = time.time() - t0
        ran.append((module_path, ok, msg, dt))
        log(f"--- {module_path} {'OK' if ok else 'FAIL'} ({dt:.1f}s) {msg}")

    log("\n--- stale-data marker ---")
    with get_conn() as conn:
        for _module_path, tag, days in PIPELINE:
            for table in ("resources", "corpus"):
                n = mark_stale_older_than(conn, table, tag, days)
                if n:
                    log(f"  marked stale: {n} rows in {table} (source={tag}, > {days}d)")

    log("\n--- summary ---")
    ok_count = sum(1 for _m, ok, _msg, _dt in ran if ok)
    log(f"  {ok_count} / {len(ran)} ingesters succeeded")
    for module_path, ok, msg, dt in ran:
        flag = "OK" if ok else "FAIL"
        log(f"  [{flag}] {module_path} ({dt:.1f}s) {msg}")

    return 0 if ok_count == len(ran) else 1


if __name__ == "__main__":
    raise SystemExit(main())
