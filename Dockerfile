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

# HF Spaces injects PORT=7860; default for local Docker runs too.
ENV PORT=7860
EXPOSE 7860

# Python module path: pathways.api.main exposes `api` (a FastAPI app)
CMD ["sh", "-c", "uvicorn pathways.api.main:api --host 0.0.0.0 --port ${PORT:-7860}"]
