# Pathways retrieval

The retrieve node calls `get_retriever().search(query, category, top_k)` and
the rest of the graph is unchanged. Two backends ship today.

## BM25 (default)

Matches the pre-Phase-5 behavior exactly. BM25 over the
`{citation + summary + tags}` index in `mcp_servers/pathways_corpus/corpus.json`,
delegated to the in-process MCP server.

```bash
# Default; nothing to set.
unset PATHWAYS_RETRIEVAL_BACKEND
python -m evals.runner
```

## Hybrid (BM25 + dense, RRF fusion)

Adds BGE-small dense retrieval alongside BM25, fused via Reciprocal
Rank Fusion. Better for paraphrase and semantically related queries
that BM25 misses (no keyword overlap).

```bash
# 1. One-time: generate the embeddings sidecar.
python scripts/embed_corpus.py
# wrote: mcp_servers/pathways_corpus/corpus_embeddings.npy (~150 KB)

# 2. Opt in via env.
export PATHWAYS_RETRIEVAL_BACKEND=hybrid

# 3. Run.
python -m evals.runner
```

### What hybrid actually does

1. Lexical leg: BM25 over the same corpus, `top_k * 4` candidates.
2. Dense leg: encode the query with BGE-small (384 dim, normalized).
   Cosine = dot product against the precomputed sidecar matrix. Same
   `top_k * 4` candidates.
3. Fusion: Reciprocal Rank Fusion. Per id, `score = sum(1 / (k + rank))`
   across both rankings; `k = 60` (Cormack et al. 2009). Robust to
   score-scale differences between BM25 and cosine.
4. Confidence: top fused score, normalized against the maximum
   possible RRF score for an item that ranks first in both lists.

### Graceful degradation

If hybrid is requested but `sentence-transformers` isn't importable
(missing dep, torch DLL issue, etc) or the embeddings sidecar is
missing, the retriever logs a warning and falls back to BM25. The
graph never breaks because of a retrieval misconfiguration. Same
contract for the caller either way.

## Validating the delta with the eval harness

```bash
# Baseline
unset PATHWAYS_RETRIEVAL_BACKEND
python -m evals.runner --json results-bm25.json

# Hybrid (after generating the sidecar)
export PATHWAYS_RETRIEVAL_BACKEND=hybrid
python -m evals.runner --json results-hybrid.json

# Compare
python -c "import json; b=json.load(open('results-bm25.json'));
h=json.load(open('results-hybrid.json'));
print('bm25:', b['overall_pass_rate']);
print('hybrid:', h['overall_pass_rate'])"
```

Most current scenarios are structural (routing, crisis hook, intake
heuristics) and don't depend on which retriever runs. The delta shows
up most in:
- `citation` scenarios in `--mode full` (LLM cites the right statute)
- Future retrieval-specific scenarios (planned: `retrieval_ids_contains_any_of`
  scorer + 10+ paraphrase queries)

## Production deployment

The HF Space Dockerfile installs `sentence-transformers` via
`requirements.txt`. After deploy:

```bash
# One-time on the Space (or run locally and commit the .npy)
python scripts/embed_corpus.py

# Then set the Space secret PATHWAYS_RETRIEVAL_BACKEND=hybrid
# and restart. The graph picks up hybrid on the next invocation.
```

The sidecar is ~150 KB for the current 95-entry corpus, scaling
linearly. For corpora above ~10k entries, swap the sidecar for the
`corpus.embedding` pgvector column (which the embed script already
supports via `--backend postgres`).
