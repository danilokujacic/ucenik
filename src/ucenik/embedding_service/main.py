"""Self-hosted embedding service - loads BGE-M3 exactly once and serves it
over a tiny internal HTTP API, instead of letting every process that needs
an embedding load its own independent copy into memory.

Why this exists: rag/embedder.py used to load `SentenceTransformer(BAAI/
bge-m3)` directly, in-process. That's fine for a single process, but `app`
and the Celery `worker` are separate OS processes (docker-compose.prod.yaml
- own container, own command, same image), each with its own Python
interpreter and its own module-level model singleton - the model (~2.3GB on
disk, 2-4GB in RAM once loaded, CPU-only inference here - no GPU anywhere in
this stack) got loaded TWICE, once per process, for zero benefit: two
identical copies of the same weights sitting in RAM doing nothing but
existing. Pulling it out into its own service - same "own container, own
port, callers never load the real thing themselves" shape already used for
llm_proxy/ - means exactly one process ever loads the model, no matter how
many other processes need embeddings, and no matter how many more get added
later.

rag/embedder.py is now a thin HTTP client calling this service (mirrors
llm/proxy_client.py's relationship to llm_proxy) - its public
embed_documents()/embed_query() signatures are unchanged, so nothing that
calls them (rag/ingest.py, rag/retriever.py, scripts/rag_explain.py) needed
to change.

Unlike llm_proxy, this isn't a relay to a third-party provider - the model
runs right here, self-hosted, no external API/cost per call. So the
contract is this service's own, not an OpenAI-compatible passthrough.

Run it: `uv run fastapi run src/ucenik/embedding_service/main.py --port 4001`
(matches the default `EMBEDDING_SERVICE_URL=http://localhost:4001` in
.env.example) - or `make embedding-service` / `scripts/run-embedding-service.sh`.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from ucenik.core.logging_config import configure_logging
from ucenik.embedding_service.config import embedding_service_settings

configure_logging()

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Loaded eagerly at startup, not lazily on first request - the whole
    # point of this service is paying the load cost exactly once, up
    # front; doing it lazily would just move that cost onto whichever
    # request happens to arrive first (and everything queued behind it).
    global _model
    logger.info(
        "embedding_service.loading_model",
        extra={"event": "embedding_service.loading_model", "model": embedding_service_settings.embedding_model},
    )
    _model = SentenceTransformer(embedding_service_settings.embedding_model)
    logger.info("embedding_service.model_loaded", extra={"event": "embedding_service.model_loaded"})
    yield


app = FastAPI(title="ucenik-embedding-service", lifespan=lifespan)


async def _require_shared_secret(authorization: str | None = Header(default=None)) -> None:
    if not embedding_service_settings.embedding_service_api_key:
        return
    if authorization != f"Bearer {embedding_service_settings.embedding_service_api_key}":
        raise HTTPException(status_code=401, detail="invalid or missing embedding service API key")


class EmbedRequest(BaseModel):
    texts: list[str]
    # Kept explicit rather than inferred, same reasoning rag/embedder.py's
    # docstring already gives for embed_documents/embed_query being two
    # functions instead of one: mixing query/document prompts doesn't
    # error, it just silently produces worse retrieval.
    prompt_name: Literal["document", "query"]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model_loaded": _model is not None}


@app.post("/embed", response_model=EmbedResponse, dependencies=[Depends(_require_shared_secret)])
async def embed(payload: EmbedRequest) -> EmbedResponse:
    if _model is None:
        # Only reachable if a request lands during the brief lifespan
        # startup window before the model finishes loading - not a normal
        # operating state, but honest about it rather than a raw 500.
        raise HTTPException(status_code=503, detail="model not loaded yet")

    # SentenceTransformer.encode() is a blocking CPU-bound call - offloaded
    # to a thread so it doesn't block this service's event loop, same
    # reasoning rag/embedder.py used to have before this refactor.
    vectors = await asyncio.to_thread(
        _model.encode, payload.texts, prompt_name=payload.prompt_name, normalize_embeddings=True
    )
    return EmbedResponse(embeddings=vectors.tolist())
