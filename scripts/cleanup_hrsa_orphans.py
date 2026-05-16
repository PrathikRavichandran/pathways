"""Delete orphan HRSA rows from the resources table.

Use this once after upgrading from the pre-Phase-3 HRSA ingester (which
used a buggy dedup key that collapsed multiple sites of one operator
into a single row). Running this before re-ingesting wipes the old
~414 rows so the new ingester writes ~832 fresh per-site rows.

Idempotent: running on an empty source set just prints `deleted 0`.

Run:
    DATABASE_URL=postgresql://... python -m scripts.cleanup_hrsa_orphans
"""

from __future__ import annotations

from scripts._common import get_conn, log


def main() -> int:
    log("Deleting all rows with source='hrsa_fqhc' from resources...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM resources WHERE source = 'hrsa_fqhc'")
            count = cur.rowcount
            log(f"  deleted {count} rows")
    log("Now run: python -m scripts.ingest_hrsa_fqhcs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
