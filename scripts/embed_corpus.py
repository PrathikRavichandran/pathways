"""One-shot: compute BGE-small embeddings for the corpus.

Reads the entries from mcp_servers/pathways_corpus/corpus.json (or the
Postgres backend, depending on PATHWAYS_CORPUS_BACKEND) and writes a
sidecar `corpus_embeddings.npy` that the HybridRetriever loads on
process start.

Usage::

    python scripts/embed_corpus.py
    python scripts/embed_corpus.py --backend postgres
    python scripts/embed_corpus.py --out path/to/embeddings.npy

The script is idempotent: re-running overwrites the sidecar. Run it
after any corpus refresh.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_entries_from_file(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("entries", []))


def _load_entries_from_postgres() -> list[dict]:
    """Fetch entries from the corpus table (Phase 2 schema)."""
    import psycopg

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "PATHWAYS_CORPUS_BACKEND=postgres but DATABASE_URL is unset."
        )
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, citation, summary, category, tags FROM corpus"
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _build_doc_text(entry: dict) -> str:
    """The text we embed per entry. Keep this stable across runs."""
    parts = [
        str(entry.get("citation", "") or ""),
        str(entry.get("summary", "") or ""),
        " ".join(str(t) for t in (entry.get("tags") or [])),
    ]
    return "\n".join(p for p in parts if p).strip()


def main() -> int:
    parser = argparse.ArgumentParser(prog="embed_corpus")
    parser.add_argument(
        "--backend",
        default=os.environ.get("PATHWAYS_CORPUS_BACKEND", "file"),
        choices=["file", "postgres"],
    )
    parser.add_argument(
        "--corpus-path",
        default=str(REPO_ROOT / "mcp_servers" / "pathways_corpus" / "corpus.json"),
    )
    parser.add_argument(
        "--out",
        default=str(
            REPO_ROOT / "mcp_servers" / "pathways_corpus" / "corpus_embeddings.npy"
        ),
    )
    args = parser.parse_args()

    if args.backend == "postgres":
        entries = _load_entries_from_postgres()
        print(f"loaded {len(entries)} entries from postgres")
    else:
        path = Path(args.corpus_path)
        if not path.exists():
            print(f"corpus file not found: {path}", file=sys.stderr)
            return 2
        entries = _load_entries_from_file(path)
        print(f"loaded {len(entries)} entries from {path}")

    if not entries:
        print("no entries to embed", file=sys.stderr)
        return 2

    # Drop entries without an id (defensive; corpus is curated, but the
    # postgres view may include nulls if the ingester misbehaved).
    entries = [e for e in entries if e.get("id")]
    ids = [str(e["id"]) for e in entries]
    docs = [_build_doc_text(e) for e in entries]

    try:
        from pathways.retrieval.embeddings import embed_batch
    except ImportError as e:
        print(f"sentence-transformers not installed: {e}", file=sys.stderr)
        return 2

    print(f"embedding {len(docs)} entries with BGE-small ...")
    vectors = embed_batch(docs)
    print(f"got matrix shape={vectors.shape} dtype={vectors.dtype}")

    import numpy as np

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(
        out_path,
        np.array({"ids": ids, "vectors": vectors}, dtype=object),
        allow_pickle=True,
    )
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
