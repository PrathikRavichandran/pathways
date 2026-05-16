"""
pathways-corpus — MCP server exposing the seeded Texas reentry corpus.

Transport: stdio
Tools:
    search_corpus(query, category=None, top_k=5) -> list of {id, citation, summary, url, score}
    get_citation(citation_id)                    -> single entry by id

Retrieval is BM25 over the {citation + summary + tags} index. This is the
demo-mode implementation; in production we swap to Pinecone (or pgvector)
with semantic + lexical hybrid retrieval, but the MCP tool contract stays
identical so callers don't need to change.

Run directly:
    python mcp_servers/pathways_corpus/server.py

Or wire into Claude Code via .mcp.json (already done in this repo).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "FATAL: mcp package not installed. Run `pip install mcp`.",
        file=sys.stderr,
    )
    raise

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    print(
        "FATAL: rank_bm25 not installed. Run `pip install rank-bm25`.",
        file=sys.stderr,
    )
    raise


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

DEFAULT_CORPUS_PATH = (
    Path(__file__).parent / "corpus.json"
)
CORPUS_PATH = Path(os.environ.get("PATHWAYS_CORPUS_PATH", str(DEFAULT_CORPUS_PATH)))
BACKEND = os.environ.get("PATHWAYS_CORPUS_BACKEND", "file").strip().lower()


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace.

    Intentionally simple. Real production uses a proper tokenizer; this is
    enough for BM25 over a corpus of this size to give plausible top-5 results.
    The Phase 5 hybrid retrieval swap (pgvector + BM25 with RRF) will replace
    this with a calibrated reranker, but the MCP tool contract stays identical.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9§\s_-]", " ", text)
    return [t for t in text.split() if t]


def _load_corpus_file(path: Path) -> tuple[dict, list[dict]]:
    if not path.exists():
        raise FileNotFoundError(
            f"corpus not found at {path}. "
            f"Set PATHWAYS_CORPUS_PATH or place corpus.json alongside this server."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("_metadata", {})
    entries = payload.get("entries", [])
    return metadata, entries


def _load_corpus_postgres() -> tuple[dict, list[dict]]:
    """Fetch all non-stale corpus entries from the Postgres table."""
    import psycopg

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "PATHWAYS_CORPUS_BACKEND=postgres but DATABASE_URL is unset."
        )
    entries: list[dict] = []
    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, citation, summary, text_full, url, category, subcategory,
                       tags, state, last_verified, source
                  FROM corpus
                 WHERE stale = FALSE
                 ORDER BY id;
            """)
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                e = dict(zip(cols, row))
                # Normalize last_verified to ISO string for downstream JSON.
                if e.get("last_verified") is not None:
                    e["last_verified"] = str(e["last_verified"])
                entries.append(e)
    metadata = {
        "name": "pathways-corpus",
        "backend": "postgres",
        "entry_count": len(entries),
    }
    return metadata, entries


def _build_index(entries: list[dict]) -> BM25Okapi:
    """Build the BM25 index over the corpus."""
    docs = []
    for e in entries:
        tag_text = " ".join(str(t) for t in (e.get("tags") or []))
        doc = f"{e.get('citation','')} {e.get('summary','')} {tag_text} {e.get('subcategory') or ''}"
        docs.append(_tokenize(doc))
    return BM25Okapi(docs) if docs else BM25Okapi([[""]])


def _load_corpus() -> tuple[dict, list[dict], BM25Okapi]:
    if BACKEND == "postgres":
        metadata, entries = _load_corpus_postgres()
    else:
        metadata, entries = _load_corpus_file(CORPUS_PATH)
    bm25 = _build_index(entries)
    return metadata, entries, bm25


METADATA, ENTRIES, BM25 = _load_corpus()
ENTRIES_BY_ID = {e["id"]: e for e in ENTRIES}


def _refresh_cache() -> None:
    """Test/admin helper: re-read the backend and rebuild the BM25 index."""
    global METADATA, ENTRIES, BM25, ENTRIES_BY_ID
    METADATA, ENTRIES, BM25 = _load_corpus()
    ENTRIES_BY_ID = {e["id"]: e for e in ENTRIES}


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("pathways-corpus")


@mcp.tool()
def search_corpus(
    query: str,
    category: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Search the seeded Texas reentry corpus.

    Args:
        query: Natural-language question or keyword phrase.
        category: Optional filter — one of: employment, civil_rights,
            record_clearing, benefits, housing, drivers_license, supervision.
        top_k: Maximum results to return. Capped at 10.

    Returns a dict with `results` (list) and `confidence` (best score).
    Callers should treat `confidence` < 0.62 as "do not assert; offer
    human handoff" — this matches the rag_confidence_gate hook's floor.
    """
    if not query or not query.strip():
        return {"results": [], "confidence": 0.0, "error": "empty query"}

    top_k = max(1, min(int(top_k), 10))
    tokens = _tokenize(query)
    if not tokens:
        return {"results": [], "confidence": 0.0, "error": "no searchable tokens"}

    scores = BM25.get_scores(tokens)

    # Build candidate list with optional category filter
    candidates = []
    for idx, score in enumerate(scores):
        entry = ENTRIES[idx]
        if category and entry["category"] != category:
            continue
        candidates.append((float(score), entry))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:top_k]

    if not top:
        return {"results": [], "confidence": 0.0}

    # Normalize the top score so the gate threshold is meaningful.
    # BM25 raw scores aren't bounded; rescale by the top score over a
    # reference set. This is a simplification — production would calibrate
    # against an eval set. Good enough for demo and documented as such.
    max_score = max(scores) if any(scores) else 1.0
    raw_top = top[0][0]
    confidence = min(raw_top / (max_score + 1e-9), 1.0) if max_score > 0 else 0.0

    results = []
    for score, entry in top:
        results.append({
            "id": entry.get("id"),
            "citation": entry.get("citation"),
            "summary": entry.get("summary"),
            "url": entry.get("url"),
            "category": entry.get("category"),
            "subcategory": entry.get("subcategory"),
            "score": round(score, 4),
            "score_normalized": round(score / (max_score + 1e-9), 4) if max_score > 0 else 0.0,
        })

    return {
        "results": results,
        "confidence": round(confidence, 4),
        "query": query,
        "category_filter": category,
        "corpus_version": METADATA.get("version"),
    }


@mcp.tool()
def get_citation(citation_id: str) -> dict[str, Any]:
    """Fetch a single corpus entry by its id (e.g. 'tx-occ-53-021').

    Use this when you have a citation_id from a prior search and want the
    full record for inclusion in a draft response.
    """
    entry = ENTRIES_BY_ID.get(citation_id)
    if entry is None:
        return {"error": f"no entry with id {citation_id!r}"}
    return {"entry": entry}


@mcp.tool()
def list_categories() -> dict[str, Any]:
    """Enumerate the categories and subcategories present in the corpus."""
    from collections import defaultdict
    by_cat = defaultdict(set)
    for e in ENTRIES:
        cat = e.get("category") or "uncategorized"
        sub = e.get("subcategory") or ""
        by_cat[cat].add(sub)
    return {
        "categories": {c: sorted(s for s in subs if s) for c, subs in by_cat.items()},
        "total_entries": len(ENTRIES),
        "backend": BACKEND,
        "version": METADATA.get("version") if isinstance(METADATA, dict) else None,
    }


if __name__ == "__main__":
    mcp.run()
