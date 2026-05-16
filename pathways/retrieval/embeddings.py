"""BGE-small embedding loader.

The model is loaded lazily and cached at module level: the first
call to `embed(text)` pays the SBERT model load cost (~2s on CPU),
subsequent calls are warm.

In environments where sentence-transformers isn't installed (CI without
the optional dep, or any tight runtime) the loader raises
EmbeddingsUnavailable. The HybridRetriever catches that and falls back
to BM25 so the system never breaks because of a missing optional dep.
"""

from __future__ import annotations

import os
from typing import Iterable

_MODEL = None
_DIM = 384  # BAAI/bge-small-en-v1.5


class EmbeddingsUnavailable(RuntimeError):
    """Raised when the embedding model cannot be loaded (sentence-
    transformers missing, model download blocked, etc)."""


def model_name() -> str:
    """The embedding model to load. Overridable for experiments via
    PATHWAYS_EMBED_MODEL but the schema (dim 384, cosine) assumes
    BGE-small-en-v1.5."""
    return os.environ.get("PATHWAYS_EMBED_MODEL", "BAAI/bge-small-en-v1.5")


def dim() -> int:
    return _DIM


def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise EmbeddingsUnavailable(
            "sentence-transformers not installed; "
            "pip install sentence-transformers to enable hybrid retrieval"
        ) from e
    except Exception as e:
        # Some torch CUDA/DLL issues abort import with a non-ImportError.
        raise EmbeddingsUnavailable(f"sentence-transformers load failed: {e}") from e

    try:
        _MODEL = SentenceTransformer(model_name(), device="cpu")
    except Exception as e:
        raise EmbeddingsUnavailable(f"model load failed: {e}") from e
    return _MODEL


def embed(text: str):
    """Return a 384-dim numpy float32 vector for the given text."""
    return embed_batch([text])[0]


def embed_batch(texts: Iterable[str]):
    """Return a (N, 384) numpy array of float32 embeddings."""
    try:
        import numpy as np
    except ImportError as e:
        raise EmbeddingsUnavailable("numpy not installed") from e

    model = _load_model()
    vecs = model.encode(
        list(texts),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vecs.astype(np.float32)


def reset_model_cache() -> None:
    """Test helper: drop the cached model so the next load uses the
    current env vars."""
    global _MODEL
    _MODEL = None
