"""Retriever strategy: BM25 (default) and Hybrid (BM25 + dense, RRF).

The retrieve node calls get_retriever().search(query, category, top_k)
and inspects the returned RetrievalResult. Both backends return the
same shape, so swapping is a single env var:

    PATHWAYS_RETRIEVAL_BACKEND = bm25 | hybrid    (default: bm25)

Hybrid retriever notes
----------------------
- Lexical leg: delegates to the same BM25 path the bm25 retriever uses,
  via the pathways-corpus MCP server's in-process API.
- Dense leg: BGE-small embeddings (384 dim, cosine on L2-normalized
  vectors). Embeddings are pre-computed once via
  scripts/embed_corpus.py and persisted as a `.npy` sidecar next to the
  corpus.json file. Loaded once at process start.
- Fusion: Reciprocal Rank Fusion. For each hit, the fused score is
    sum over rankings of 1 / (k + rank)
  where k defaults to 60 (Cormack et al. 2009). Robust to score-scale
  differences between BM25 and cosine similarity.

If the embeddings sidecar or sentence-transformers is missing, the
hybrid retriever falls back to BM25 and logs a warning. Same contract,
the caller doesn't have to care.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class RetrievalHit:
    """One result row from a retriever."""
    id: str
    citation: str
    summary: str
    url: str
    score: float
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_corpus_entry(cls, entry: dict, score: float) -> "RetrievalHit":
        return cls(
            id=str(entry.get("id", "")),
            citation=str(entry.get("citation", "") or ""),
            summary=str(entry.get("summary", "") or ""),
            url=str(entry.get("url", "") or ""),
            score=float(score),
            category=entry.get("category"),
            tags=list(entry.get("tags", []) or []),
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "citation": self.citation,
            "summary": self.summary,
            "url": self.url,
            "score": self.score,
            "category": self.category,
            "tags": self.tags,
        }


@dataclass
class RetrievalResult:
    query: str
    confidence: float
    backend: str
    results: list[dict]

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "confidence": self.confidence,
            "backend": self.backend,
            "results": self.results,
        }


class Retriever(Protocol):
    backend: str

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> RetrievalResult: ...


# ---------------------------------------------------------------------------
# BM25 retriever (default, current behavior)
# ---------------------------------------------------------------------------


class BM25Retriever:
    """Delegates to the pathways-corpus MCP server's in-process search.

    This is the baseline; we keep it intact so the existing graph
    behavior is identical when PATHWAYS_RETRIEVAL_BACKEND is unset.
    """

    backend = "bm25"

    def __init__(self) -> None:
        self._server = None

    def _get_server(self):
        if self._server is not None:
            return self._server
        import importlib.util
        here = Path(__file__).resolve().parent.parent.parent
        server_path = here / "mcp_servers" / "pathways_corpus" / "server.py"
        spec = importlib.util.spec_from_file_location(
            "pathways_corpus_server", str(server_path)
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load corpus server at {server_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._server = module
        return module

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> RetrievalResult:
        server = self._get_server()
        raw = server.search_corpus(query=query, category=category, top_k=top_k)
        return RetrievalResult(
            query=query,
            confidence=float(raw.get("confidence", 0.0)),
            backend=self.backend,
            results=list(raw.get("results", [])),
        )


# ---------------------------------------------------------------------------
# Hybrid retriever (BM25 + dense, RRF fusion)
# ---------------------------------------------------------------------------


class HybridRetriever:
    """BM25 + BGE-small dense, fused via Reciprocal Rank Fusion.

    Falls back to BM25 if sentence-transformers is unavailable or the
    embeddings sidecar is missing.
    """

    backend = "hybrid"

    def __init__(
        self,
        embeddings_path: Optional[Path] = None,
        rrf_k: int = 60,
        bm25_floor_top_k: int = 20,
        dense_top_k: int = 20,
        embed_fn=None,
    ) -> None:
        self._bm25 = BM25Retriever()
        self._embeddings_path = embeddings_path or (
            Path(__file__).resolve().parent.parent.parent
            / "mcp_servers" / "pathways_corpus" / "corpus_embeddings.npy"
        )
        self._rrf_k = rrf_k
        self._bm25_top_k = bm25_floor_top_k
        self._dense_top_k = dense_top_k
        self._embed_fn = embed_fn  # for tests
        self._embeddings = None
        self._embedding_ids: list[str] = []
        self._loaded = False
        self._fallback = False

    # ---- one-time load --------------------------------------------------

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return not self._fallback
        self._loaded = True

        try:
            import numpy as np
        except ImportError:
            logger.warning("hybrid: numpy missing, falling back to BM25")
            self._fallback = True
            return False

        path = self._embeddings_path
        if not path.exists():
            logger.warning(
                "hybrid: embeddings sidecar not found at %s; "
                "run `python scripts/embed_corpus.py`. Falling back to BM25.",
                path,
            )
            self._fallback = True
            return False

        try:
            data = np.load(path, allow_pickle=True)
        except Exception as e:
            logger.warning("hybrid: failed to load %s: %s. BM25 fallback.", path, e)
            self._fallback = True
            return False

        # The sidecar is a structured object array: {ids: [...], vectors: ndarray}
        try:
            payload = data.item() if data.shape == () else data
            self._embedding_ids = list(payload["ids"])
            self._embeddings = np.asarray(payload["vectors"], dtype=np.float32)
        except Exception as e:
            logger.warning("hybrid: malformed sidecar at %s: %s. BM25 fallback.", path, e)
            self._fallback = True
            return False

        return True

    # ---- query --------------------------------------------------------

    def _query_vector(self, query: str):
        if self._embed_fn is not None:
            return self._embed_fn(query)
        from pathways.retrieval.embeddings import EmbeddingsUnavailable, embed
        try:
            return embed(query)
        except EmbeddingsUnavailable as e:
            raise RuntimeError(f"embedding query failed: {e}") from e

    def _dense_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        import numpy as np
        qv = self._query_vector(query)
        qv = np.asarray(qv, dtype=np.float32)
        # Normalize the query in case caller didn't (BGE convention is to
        # cosine over L2-normalized vectors).
        n = float(np.linalg.norm(qv))
        if n > 0:
            qv = qv / n
        # Cosine over already-normalized corpus vectors = dot product.
        scores = self._embeddings @ qv
        idxs = np.argsort(-scores)[:top_k]
        return [(self._embedding_ids[i], float(scores[i])) for i in idxs]

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> RetrievalResult:
        bm25 = self._bm25.search(
            query=query, category=category, top_k=max(top_k, self._bm25_top_k),
        )

        if not self._ensure_loaded():
            # Fall through to BM25 directly. Trim to the caller's top_k.
            bm25.results = bm25.results[:top_k]
            return bm25

        try:
            dense = self._dense_search(query, self._dense_top_k)
        except Exception as e:
            logger.warning("hybrid: dense leg failed (%s); BM25 only.", e)
            bm25.results = bm25.results[:top_k]
            return bm25

        # Optional category filter: drop dense hits whose id has a category
        # the BM25 results expose (best-effort; we look up category via the
        # BM25 server's entry cache).
        if category:
            allowed_ids = self._ids_in_category(category)
            if allowed_ids:
                dense = [(i, s) for (i, s) in dense if i in allowed_ids]

        fused = self._rrf(bm25.results, dense, top_k)

        # Confidence: top hit's fused score, normalized to [0,1] using the
        # idealized maximum RRF score for two complete rankings (2 / (k+1)).
        max_score = 2.0 / (self._rrf_k + 1)
        top_conf = (fused[0]["score"] / max_score) if fused else 0.0
        return RetrievalResult(
            query=query,
            confidence=float(min(1.0, max(0.0, top_conf))),
            backend=self.backend,
            results=fused,
        )

    # ---- helpers ------------------------------------------------------

    def _ids_in_category(self, category: str) -> set[str]:
        try:
            server = self._bm25._get_server()
            entries = getattr(server, "ENTRIES", None) or []
            return {
                str(e.get("id"))
                for e in entries
                if e.get("category") == category and e.get("id")
            }
        except Exception:
            return set()

    def _rrf(
        self,
        bm25_results: list[dict],
        dense_results: list[tuple[str, float]],
        top_k: int,
    ) -> list[dict]:
        """Reciprocal Rank Fusion across BM25 and dense rankings."""
        k = self._rrf_k
        scores: dict[str, float] = {}
        entries_by_id: dict[str, dict] = {}

        for rank, hit in enumerate(bm25_results):
            hid = str(hit.get("id"))
            if not hid:
                continue
            scores[hid] = scores.get(hid, 0.0) + 1.0 / (k + rank + 1)
            entries_by_id.setdefault(hid, dict(hit))

        for rank, (hid, _dense_score) in enumerate(dense_results):
            if not hid:
                continue
            scores[hid] = scores.get(hid, 0.0) + 1.0 / (k + rank + 1)
            if hid not in entries_by_id:
                entry = self._lookup_entry(hid)
                if entry:
                    entries_by_id[hid] = dict(entry)

        ranked_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
        out: list[dict] = []
        for hid in ranked_ids[:top_k]:
            entry = entries_by_id.get(hid, {"id": hid})
            row = dict(entry)
            row["score"] = scores[hid]
            out.append(row)
        return out

    def _lookup_entry(self, citation_id: str) -> Optional[dict]:
        try:
            server = self._bm25._get_server()
            entries = getattr(server, "ENTRIES", None) or []
            for e in entries:
                if str(e.get("id")) == citation_id:
                    return e
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_RETRIEVER: Optional[Retriever] = None


def get_retriever() -> Retriever:
    global _RETRIEVER
    if _RETRIEVER is not None:
        return _RETRIEVER

    backend = os.environ.get("PATHWAYS_RETRIEVAL_BACKEND", "bm25").lower()
    if backend == "hybrid":
        _RETRIEVER = HybridRetriever()
    else:
        _RETRIEVER = BM25Retriever()
    return _RETRIEVER


def reset_retriever() -> None:
    """Test helper: drop the cached retriever."""
    global _RETRIEVER
    _RETRIEVER = None
