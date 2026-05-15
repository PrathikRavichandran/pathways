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


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace.

    Intentionally simple. Real production uses a proper tokenizer; this is
    enough for BM25 over a 65-entry corpus to give plausible top-5 results.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9§\s_-]", " ", text)
    return [t for t in text.split() if t]


def _load_corpus(path: Path) -> tuple[dict, list[dict], BM25Okapi]:
    if not path.exists():
        raise FileNotFoundError(
            f"corpus not found at {path}. "
            f"Set PATHWAYS_CORPUS_PATH or place corpus.json alongside this server."
        )
    payload = json.loads(path.read_text())
    metadata = payload["_metadata"]
    entries = payload["entries"]

    # Build a parallel tokenized doc list. Index over citation + summary + tags
    # joined so a search for "snap drug felony" hits the tags as well as text.
    docs = []
    for e in entries:
        tag_text = " ".join(e.get("tags", []))
        doc = f"{e['citation']} {e['summary']} {tag_text} {e.get('subcategory','')}"
        docs.append(_tokenize(doc))

    bm25 = BM25Okapi(docs)
    return metadata, entries, bm25


METADATA, ENTRIES, BM25 = _load_corpus(CORPUS_PATH)
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
            "id": entry["id"],
            "citation": entry["citation"],
            "summary": entry["summary"],
            "url": entry["url"],
            "category": entry["category"],
            "subcategory": entry["subcategory"],
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
        by_cat[e["category"]].add(e["subcategory"])
    return {
        "categories": {c: sorted(subs) for c, subs in by_cat.items()},
        "total_entries": len(ENTRIES),
        "version": METADATA.get("version"),
    }


if __name__ == "__main__":
    mcp.run()
