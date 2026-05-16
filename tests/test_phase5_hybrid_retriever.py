"""Phase 5 tests: retriever strategy + RRF fusion.

The hybrid retriever depends on sentence-transformers + a pre-computed
sidecar at runtime. To keep these tests offline and free of the heavy
dep, we inject a stub embedder and synthesize a sidecar in tmp_path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Strategy + factory wiring
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_retriever_cache(monkeypatch):
    """Each test starts with a fresh factory cache so env changes apply."""
    monkeypatch.delenv("PATHWAYS_RETRIEVAL_BACKEND", raising=False)
    from pathways.retrieval.retriever import reset_retriever
    reset_retriever()
    yield
    reset_retriever()


def test_get_retriever_defaults_to_bm25():
    from pathways.retrieval import BM25Retriever, get_retriever
    r = get_retriever()
    assert isinstance(r, BM25Retriever)
    assert r.backend == "bm25"


def test_get_retriever_returns_hybrid_when_configured(monkeypatch):
    monkeypatch.setenv("PATHWAYS_RETRIEVAL_BACKEND", "hybrid")
    from pathways.retrieval import HybridRetriever, get_retriever
    r = get_retriever()
    assert isinstance(r, HybridRetriever)
    assert r.backend == "hybrid"


def test_get_retriever_caches_instance(monkeypatch):
    monkeypatch.setenv("PATHWAYS_RETRIEVAL_BACKEND", "bm25")
    from pathways.retrieval import get_retriever
    a = get_retriever()
    b = get_retriever()
    assert a is b


def test_unknown_backend_falls_back_to_bm25(monkeypatch):
    monkeypatch.setenv("PATHWAYS_RETRIEVAL_BACKEND", "not-a-real-backend")
    from pathways.retrieval import BM25Retriever, get_retriever
    assert isinstance(get_retriever(), BM25Retriever)


# ---------------------------------------------------------------------------
# BM25 retriever delegates to the corpus server
# ---------------------------------------------------------------------------


def test_bm25_retriever_returns_results_with_confidence():
    """End-to-end against the real corpus.json file. This verifies the
    strategy doesn't regress the existing search path."""
    from pathways.retrieval import BM25Retriever

    r = BM25Retriever()
    result = r.search(
        query="non-disclosure expunction eligibility",
        category="record_clearing",
        top_k=3,
    )
    assert result.backend == "bm25"
    assert result.query
    assert isinstance(result.confidence, float)
    assert len(result.results) >= 1
    for hit in result.results:
        assert "id" in hit


# ---------------------------------------------------------------------------
# Hybrid retriever: graceful fallback when no sidecar
# ---------------------------------------------------------------------------


def test_hybrid_falls_back_to_bm25_when_sidecar_missing(tmp_path):
    """Without the embeddings sidecar, hybrid must degrade to BM25
    so a misconfigured deploy never breaks the graph."""
    from pathways.retrieval.retriever import HybridRetriever

    r = HybridRetriever(embeddings_path=tmp_path / "missing.npy")
    result = r.search(query="public housing eligibility", category="housing", top_k=3)
    # Backend reports hybrid even though it fell back; the contract is
    # "the configured backend will try hybrid first, then BM25".
    # The actual results came from BM25. They still satisfy the shape.
    assert len(result.results) >= 1


def test_hybrid_with_synthetic_sidecar_uses_both_legs(tmp_path, monkeypatch):
    """Stub the embedder and write a synthetic sidecar with a handful
    of ids. Verify RRF actually fuses BM25 + dense rankings."""
    import numpy as np

    from pathways.retrieval.retriever import HybridRetriever

    # Synthetic embedding ids: pick a few real corpus ids and a few fake
    # ones. We only need to verify RRF math, not that the corpus picks
    # them up.
    ids = [
        "tx-occ-53-021", "tx-niccc-housing-001", "fed-snap-drug-felony",
        "tx-gov-411-072", "tx-ccp-55-01",
    ]
    rng = np.random.default_rng(seed=42)
    vectors = rng.standard_normal(size=(len(ids), 4)).astype(np.float32)
    # L2-normalize so cosine = dot product
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / norms

    sidecar = tmp_path / "embeddings.npy"
    np.save(
        sidecar,
        np.array({"ids": ids, "vectors": vectors}, dtype=object),
        allow_pickle=True,
    )

    # Stub embedder: returns the first vector so the top dense hit is
    # always the first id ("tx-occ-53-021"). Predictable for assertions.
    def stub_embed(query: str):
        return vectors[0]

    r = HybridRetriever(
        embeddings_path=sidecar,
        embed_fn=stub_embed,
        rrf_k=10,
        bm25_floor_top_k=10,
        dense_top_k=5,
    )
    result = r.search(
        query="occupational license criminal conviction Texas",
        category=None,
        top_k=5,
    )
    assert result.backend == "hybrid"
    ids_returned = [h.get("id") for h in result.results]
    # The dense top hit must appear somewhere in the fused results.
    assert "tx-occ-53-021" in ids_returned
    # Confidence is in [0, 1]
    assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# RRF math: pure unit test
# ---------------------------------------------------------------------------


def test_rrf_fusion_prefers_items_in_both_rankings(tmp_path):
    """An item ranked highly in BOTH BM25 and dense should beat an item
    ranked highly in only one."""
    import numpy as np

    from pathways.retrieval.retriever import HybridRetriever

    # Empty sidecar (just to satisfy load); we call _rrf directly.
    sidecar = tmp_path / "empty.npy"
    np.save(
        sidecar,
        np.array({"ids": [], "vectors": np.zeros((0, 4), dtype=np.float32)}, dtype=object),
        allow_pickle=True,
    )
    r = HybridRetriever(embeddings_path=sidecar, embed_fn=lambda q: np.zeros(4))

    bm25_results = [
        {"id": "A", "summary": "A"},  # rank 0
        {"id": "B", "summary": "B"},  # rank 1
        {"id": "C", "summary": "C"},  # rank 2
    ]
    dense_results = [
        ("A", 0.9),  # rank 0 too -> sum = 1/(k+1) + 1/(k+1)
        ("D", 0.8),  # rank 1
        ("B", 0.7),  # rank 2
    ]
    fused = r._rrf(bm25_results, dense_results, top_k=4)
    fused_ids = [h["id"] for h in fused]
    assert fused_ids[0] == "A", f"A should win (top in both); got {fused_ids}"
    # B should outrank C (B in both, C only in BM25)
    assert fused_ids.index("B") < fused_ids.index("C")
    # D appears (top dense but not in BM25)
    assert "D" in fused_ids


def test_rrf_returns_at_most_top_k(tmp_path):
    import numpy as np

    from pathways.retrieval.retriever import HybridRetriever

    sidecar = tmp_path / "empty.npy"
    np.save(
        sidecar,
        np.array({"ids": [], "vectors": np.zeros((0, 4), dtype=np.float32)}, dtype=object),
        allow_pickle=True,
    )
    r = HybridRetriever(embeddings_path=sidecar, embed_fn=lambda q: np.zeros(4))

    bm25 = [{"id": f"b-{i}"} for i in range(10)]
    dense = [(f"d-{i}", 0.5) for i in range(10)]
    fused = r._rrf(bm25, dense, top_k=3)
    assert len(fused) == 3
