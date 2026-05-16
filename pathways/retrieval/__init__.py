"""Pathways retrieval strategy.

Public API: get_retriever(), Retriever, RetrievalHit, RetrievalResult.

The retrieve node calls get_retriever().search(query, category, top_k) and
the rest of the graph stays the same. Two backends ship today:

    bm25 (default): the same BM25 over corpus.json that has shipped since
                    Phase 0. Always available; zero new deps at runtime.
    hybrid        : BM25 + dense (BGE-small embeddings) fused via RRF.
                    Opt in via PATHWAYS_RETRIEVAL_BACKEND=hybrid.

If hybrid is requested but sentence-transformers isn't installed or the
embeddings sidecar is missing, the factory logs a warning and falls back
to bm25 so the graph never breaks because of a retrieval config error.
"""

from pathways.retrieval.retriever import (
    BM25Retriever,
    HybridRetriever,
    RetrievalHit,
    RetrievalResult,
    Retriever,
    get_retriever,
)

__all__ = [
    "BM25Retriever",
    "HybridRetriever",
    "RetrievalHit",
    "RetrievalResult",
    "Retriever",
    "get_retriever",
]
