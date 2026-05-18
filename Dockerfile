# Pathways — FastAPI ingress (Twilio webhook + debug invoke)
# Hugging Face Spaces convention: app must listen on $PORT (7860).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATHWAYS_DEPLOY_MODE=demo \
    PATHWAYS_LOG_LEVEL=INFO

# Build essentials only if any dep needs them; keep image lean.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer caching: requirements first.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Application code.
COPY . .

# Pre-generate the corpus_embeddings.npy sidecar so the HybridRetriever
# can boot without a runtime download. This downloads BAAI/bge-small-en-v1.5
# (~130 MB) once at build time, embeds the 95 corpus entries (~3 seconds),
# and writes a small (~150 KB) .npy file alongside corpus.json. Without
# this step the HybridRetriever logs a warning and falls back to BM25
# even when PATHWAYS_RETRIEVAL_BACKEND=hybrid is set.
#
# The model weights are cached in /root/.cache/huggingface so the
# runtime container doesn't re-download. Build is idempotent: re-runs
# write the same sidecar.
RUN python scripts/embed_corpus.py --backend file \
    && ls -lh mcp_servers/pathways_corpus/corpus_embeddings.npy

# HF Spaces injects PORT=7860; default for local Docker runs too.
ENV PORT=7860
EXPOSE 7860

# Python module path: pathways.api.main exposes `api` (a FastAPI app)
CMD ["sh", "-c", "uvicorn pathways.api.main:api --host 0.0.0.0 --port ${PORT:-7860}"]
