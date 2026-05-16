"""Shared helpers for the Phase 2 ingestion scripts.

Goals:
- One place for Postgres connection management so every ingester does not
  reinvent it. Reads DATABASE_URL from the env; raises a clear error if
  it is unset.
- Idempotent UPSERTs against the resources and corpus tables. Each ingester
  computes a stable `id` for every record and the UPSERT logic does the
  rest.
- Per-row geo enrichment when the record carries an address or ZIP we can
  resolve via the vendored TX ZIP centroid table.
- Source tagging + last_verified bookkeeping so the weekly refresh job can
  flag drift.

Usage from an ingester:
    from scripts._common import (
        upsert_resource, upsert_corpus_entry, today_iso,
        get_conn, enrich_geo,
    )

    with get_conn() as conn:
        for record in fetch_records():
            enriched = enrich_geo(record)
            upsert_resource(conn, enriched, source="hrsa_fqhc")
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import sys
from contextlib import contextmanager
from typing import Iterable, Optional

from pathways.geo import (
    county_for_zip,
    haversine_miles,
    workforce_region_for_county,
    zip_to_coords,
)


def today_iso() -> str:
    return _dt.date.today().isoformat()


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Either export it or write a .env file."
            " The ingesters need a real Postgres to write to."
        )
    return url


@contextmanager
def get_conn():
    """Context-managed psycopg connection with autocommit off; commits at exit."""
    import psycopg

    url = get_database_url()
    conn = psycopg.connect(url, connect_timeout=20)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def extract_zip(text: Optional[str]) -> Optional[str]:
    """Pull a 5-digit ZIP out of an address / description string."""
    if not text:
        return None
    m = _ZIP_RE.search(text)
    return m.group(1) if m else None


def enrich_geo(record: dict) -> dict:
    """Mutate record in place to add lat/lon/county/workforce_region when
    derivable from `zipcode`, `zip`, or any address string in `description`
    or `address`. Returns the record."""
    zip5 = record.get("zip") or record.get("zipcode")
    if not zip5:
        for k in ("address", "street_address", "description"):
            zip5 = extract_zip(record.get(k))
            if zip5:
                break

    if zip5 and not (record.get("lat") and record.get("lon")):
        coords = zip_to_coords(zip5)
        if coords:
            record["lat"], record["lon"] = coords
        county = county_for_zip(zip5)
        if county:
            record["county"] = county
            wr = workforce_region_for_county(county)
            if wr:
                record["workforce_region"] = wr
        record.setdefault("zipcode", zip5)
    return record


def _array(value) -> list:
    """Coerce a single value or comma string to a list for Postgres array cols."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return [str(value)]


def upsert_resource(conn, record: dict, source: str) -> bool:
    """UPSERT one record into the resources table. Returns True on insert,
    False on update.

    `record` must include at minimum: id, name, category. Other fields are
    optional and will be set to NULL / default if absent.
    """
    if not (record.get("id") and record.get("name") and record.get("category")):
        raise ValueError(
            f"upsert_resource: missing required id/name/category: "
            f"{ {k: record.get(k) for k in ('id', 'name', 'category')} }"
        )

    cols = {
        "id":                    record["id"],
        "name":                  record["name"],
        "category":              record["category"],
        "subcategory":           record.get("subcategory"),
        "description":           record.get("description"),
        "service_area":          _array(record.get("service_area")),
        "regions":               _array(record.get("regions")),
        "lat":                   record.get("lat"),
        "lon":                   record.get("lon"),
        "service_radius_miles":  record.get("service_radius_miles") or 50,
        "workforce_region":      record.get("workforce_region"),
        "county":                record.get("county"),
        "phone":                 record.get("phone"),
        "text_to":               record.get("text") or record.get("text_to"),
        "url":                   record.get("url"),
        "apply_url":             record.get("apply_url"),
        "intake_url":            record.get("intake_url"),
        "languages":             _array(record.get("languages")) or ["English"],
        "eligibility":           record.get("eligibility"),
        "topics":                _array(record.get("topics")),
        "accepting_clients":     record.get("accepting_clients"),
        "accepting_verified_at": record.get("accepting_verified_at"),
        "bed_count_last_known":  record.get("bed_count_last_known"),
        "serves_returning_citizens": record.get("serves_returning_citizens"),
        "last_verified":         record.get("last_verified") or today_iso(),
        "last_verified_by":      record.get("last_verified_by") or source,
        "source":                record.get("source") or source,
        "stale":                 False,
    }

    sql = """
    INSERT INTO resources (
        id, name, category, subcategory, description,
        service_area, regions, lat, lon, service_radius_miles,
        workforce_region, county,
        phone, text_to, url, apply_url, intake_url, languages,
        eligibility, topics, accepting_clients, accepting_verified_at,
        bed_count_last_known, serves_returning_citizens,
        last_verified, last_verified_by, source, stale
    ) VALUES (
        %(id)s, %(name)s, %(category)s, %(subcategory)s, %(description)s,
        %(service_area)s, %(regions)s, %(lat)s, %(lon)s, %(service_radius_miles)s,
        %(workforce_region)s, %(county)s,
        %(phone)s, %(text_to)s, %(url)s, %(apply_url)s, %(intake_url)s, %(languages)s,
        %(eligibility)s, %(topics)s, %(accepting_clients)s, %(accepting_verified_at)s,
        %(bed_count_last_known)s, %(serves_returning_citizens)s,
        %(last_verified)s, %(last_verified_by)s, %(source)s, %(stale)s
    )
    ON CONFLICT (id) DO UPDATE SET
        name                      = EXCLUDED.name,
        category                  = EXCLUDED.category,
        subcategory               = EXCLUDED.subcategory,
        description               = EXCLUDED.description,
        service_area              = EXCLUDED.service_area,
        regions                   = EXCLUDED.regions,
        lat                       = COALESCE(EXCLUDED.lat, resources.lat),
        lon                       = COALESCE(EXCLUDED.lon, resources.lon),
        service_radius_miles      = EXCLUDED.service_radius_miles,
        workforce_region          = COALESCE(EXCLUDED.workforce_region, resources.workforce_region),
        county                    = COALESCE(EXCLUDED.county, resources.county),
        phone                     = COALESCE(EXCLUDED.phone, resources.phone),
        text_to                   = COALESCE(EXCLUDED.text_to, resources.text_to),
        url                       = COALESCE(EXCLUDED.url, resources.url),
        apply_url                 = COALESCE(EXCLUDED.apply_url, resources.apply_url),
        intake_url                = COALESCE(EXCLUDED.intake_url, resources.intake_url),
        languages                 = EXCLUDED.languages,
        eligibility               = COALESCE(EXCLUDED.eligibility, resources.eligibility),
        topics                    = EXCLUDED.topics,
        accepting_clients         = EXCLUDED.accepting_clients,
        accepting_verified_at     = EXCLUDED.accepting_verified_at,
        bed_count_last_known      = EXCLUDED.bed_count_last_known,
        serves_returning_citizens = EXCLUDED.serves_returning_citizens,
        last_verified             = EXCLUDED.last_verified,
        last_verified_by          = EXCLUDED.last_verified_by,
        source                    = EXCLUDED.source,
        stale                     = FALSE
    RETURNING (xmax = 0) AS inserted;
    """
    with conn.cursor() as cur:
        cur.execute(sql, cols)
        row = cur.fetchone()
        return bool(row[0]) if row else False


def upsert_corpus_entry(conn, record: dict, source: str) -> bool:
    """UPSERT one entry into the corpus table. Returns True on insert."""
    if not (record.get("id") and record.get("citation") and record.get("summary")
            and record.get("category")):
        raise ValueError(
            f"upsert_corpus_entry: missing required field(s): "
            f"{ {k: record.get(k) for k in ('id','citation','summary','category')} }"
        )

    cols = {
        "id":              record["id"],
        "citation":        record["citation"],
        "summary":         record["summary"],
        "text_full":       record.get("text_full"),
        "url":             record.get("url"),
        "category":        record["category"],
        "subcategory":     record.get("subcategory"),
        "tags":            _array(record.get("tags")),
        "state":           record.get("state") or "TX",
        "last_verified":   record.get("last_verified") or today_iso(),
        "last_verified_by": record.get("last_verified_by") or source,
        "source":          record.get("source") or source,
        "stale":           False,
    }

    sql = """
    INSERT INTO corpus (
        id, citation, summary, text_full, url, category, subcategory,
        tags, state, last_verified, last_verified_by, source, stale
    ) VALUES (
        %(id)s, %(citation)s, %(summary)s, %(text_full)s, %(url)s,
        %(category)s, %(subcategory)s, %(tags)s, %(state)s,
        %(last_verified)s, %(last_verified_by)s, %(source)s, %(stale)s
    )
    ON CONFLICT (id) DO UPDATE SET
        citation         = EXCLUDED.citation,
        summary          = EXCLUDED.summary,
        text_full        = COALESCE(EXCLUDED.text_full, corpus.text_full),
        url              = COALESCE(EXCLUDED.url, corpus.url),
        category         = EXCLUDED.category,
        subcategory      = EXCLUDED.subcategory,
        tags             = EXCLUDED.tags,
        state            = EXCLUDED.state,
        last_verified    = EXCLUDED.last_verified,
        last_verified_by = EXCLUDED.last_verified_by,
        source           = EXCLUDED.source,
        stale            = FALSE
    RETURNING (xmax = 0) AS inserted;
    """
    with conn.cursor() as cur:
        cur.execute(sql, cols)
        row = cur.fetchone()
        return bool(row[0]) if row else False


def mark_stale_older_than(conn, table: str, source: str, days: int) -> int:
    """Flag rows older than `days` (by last_verified) from `source` as stale.
    Returns the row count. Called by the weekly refresh job after a successful
    ingester run to mark anything not refreshed in this cycle."""
    if table not in ("resources", "corpus"):
        raise ValueError(f"mark_stale_older_than: bad table {table!r}")
    sql = f"""
    UPDATE {table}
       SET stale = TRUE
     WHERE source = %(src)s
       AND last_verified < CURRENT_DATE - INTERVAL '%(days)s days'::interval
       AND stale = FALSE
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"src": source, "days": days})
        return cur.rowcount or 0


def log(msg: str) -> None:
    """Single-line ingester log to stderr."""
    sys.stderr.write(msg.rstrip() + "\n")
    sys.stderr.flush()
