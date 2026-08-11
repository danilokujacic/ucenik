# syntax=docker/dockerfile:1
FROM python:3.14-slim

# uv, straight from its own published image - fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# System deps, installed as root before dropping to appuser below:
# - tesseract-ocr(-eng): OCR fallback for scanned/image-based PDFs with no
#   text layer (rag/extractor.py's _ocr_pdf_text). Add more tesseract-ocr-*
#   language packs here if documents aren't all English.
# - poppler-utils: pdf2image renders PDF pages to images via poppler before
#   handing them to Tesseract - this is that renderer's actual binary.
# Nothing else needed for pypdf/chonkie/chromadb-client; kept minimal on
# purpose otherwise. Add build-essential here if a future dependency needs
# compiling from source instead of installing a prebuilt wheel.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Create the non-root user first and run everything as them from here on -
# files land with the right ownership as they're written (COPY --chown,
# `uv sync` running as appuser), instead of a bulk `chown -R` at the end
# walking the entire ~2.3GB model cache after the fact.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
RUN chown appuser:appuser /app
USER appuser

# Install dependencies first (separate layer from app code, so editing
# source doesn't invalidate the dependency-install cache).
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY --chown=appuser:appuser . .
RUN uv sync --frozen --no-dev

# HF cache lives under /app, already owned by appuser from WORKDIR setup above.
ENV HF_HOME=/app/.cache/huggingface

# Pre-download the embedding model at build time, not at first request -
# a cold container shouldn't depend on reaching Hugging Face at runtime.
# See rag/embedder.py; ~2.3GB, baked into the image layer.
RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# Same reasoning for the chunker's tokenizer (small, but same principle -
# see rag/chunker.py).
RUN uv run python -c "from chonkie import RecursiveChunker; RecursiveChunker(tokenizer='BAAI/bge-m3')"

EXPOSE 8000

# --forwarded-allow-ips="*": `fastapi run` already trusts X-Forwarded-For/
# -Proto/-Port by default (--proxy-headers is on unless disabled), but only
# from peers in --forwarded-allow-ips, which itself defaults to just
# "127.0.0.1" - the nginx-certbot container that actually sits in front of
# this in prod (docker-compose.prod.yaml) connects over the docker-internal
# network under its own container IP, not 127.0.0.1, so that default quietly
# never matched and every request's X-Forwarded-For was ignored: every
# request looked like it came from nginx's own container IP
# (core/rate_limit.py's _client_ip(), keyed off request.client.host, was
# rate-limiting "nginx" instead of the real client - see docs/security-
# hardening.md). "*" is safe specifically because `app` has no other public
# route in - no `ports:` published on the docker-internal network beyond a
# 127.0.0.1-bound debug port (docker-compose.prod.yaml), so the only things
# that can ever connect here to begin with are already-trusted containers on
# this same host. A literal container IP would be more precise but isn't
# stable across restarts, and there's no separate untrusted path this would
# need to defend against.
CMD ["uv", "run", "fastapi", "run", "src/ucenik/main.py", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips=*"]
