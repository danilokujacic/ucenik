# ucenik

AI-assisted tutoring and lecture planning - RAG-backed Tutor chat over
uploaded course material, plus an AI-drafted lecture planner.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** - Python package/venv manager this
  project uses instead of plain `pip`/`venv`. Also provisions the right
  Python version for you (see `.python-version`, currently `3.14`) - no
  separate Python install needed.
- **Docker + Docker Compose v2** - runs the infra (Mongo, Redis, Chroma,
  MinIO, Loki/Promtail/Grafana).
- **[pnpm](https://pnpm.io/)** (`packageManager` in `frontend/package.json`
  pins the version) - for the frontend.

## 1. Clone and configure

```bash
git clone <this repo> && cd ucenik
cp .env.example .env
```

`.env.example` is annotated inline with what every value means and why -
worth a skim. Nothing needs filling in to get a working local dev setup
*except* `GROQ_API_KEY` (get one at [console.groq.com](https://console.groq.com))
- without it, ingestion/chat/Planner will all fail the moment they actually
try to call an LLM, since there's no key to authenticate with. Everything
else in `.env.example`'s defaults already matches what `docker-compose.yaml`
provisions.

## 2. Start infra

```bash
docker compose up -d
```

Brings up Mongo, Redis, Chroma, MinIO, and the Loki/Promtail/Grafana
logging stack. This is the *only* thing `docker compose up` starts locally
- the app itself runs directly on your host for fast reload (see below),
not as a container; `docker-compose.prod.yaml` is a separate overlay that
adds those for the actual deploy target, not used here.

## 3. Install dependencies

```bash
uv sync              # backend - creates .venv/, installs everything from pyproject.toml/uv.lock
cd frontend && pnpm install && cd ..
```

## 4. Seed a user

There's no self-service signup (a deliberate product decision, not a gap -
see the backend's own permission model). Create a demo teacher + student
account directly:

```bash
uv run ucenik-seed
```

Creates (or, on a re-run, resets the password of) `teacher@ucenik.dev` /
`student@ucenik.dev`, both with password `ucenik123` - idempotent, safe to
run again any time.

## 5. Start the backend services

Four separate processes, each in its own terminal (or run them backgrounded
- whatever your workflow prefers). Each wraps a documented, single-purpose
command - see the `Makefile`/`scripts/` if you want the exact invocation
without going through `make`.

```bash
# Terminal 1 - the API itself
uv run fastapi dev --reload-dir src --port 8080
```

**`--port 8080`, not the default 8000**: `fastapi dev` defaults to port
8000, which collides with Chroma's own docker-published port (also 8000,
see `docker-compose.yaml`) - confirmed directly (`ERROR: Address already
in use` if you try the default with Chroma already up from step 2). 8080
matches `.vscode/launch.json`'s existing debug config, so it's consistent
with how this project already runs the API, not an arbitrary choice.

```bash
# Terminal 2 - Planner background jobs (generate/refine a lecture)
make celery
```

```bash
# Terminal 3 - the self-hosted LLM relay (Groq, Hugging Face fallback)
make llm-proxy
```

```bash
# Terminal 4 - the embedding service (loads BGE-M3 once; see its own
# module docstring for why this is a separate process from the API/worker)
make embedding-service
```

`--reload-dir src` on the API matters now that `frontend/` exists alongside
`src/` - without it, `--reload`'s default watch scope is the whole current
working directory, and it would restart the backend on every frontend file
save too.

`--reload-dir` (and `--port`) aside, `.vscode/launch.json`'s "FastAPI:
ucenik (debug, no reload)" run configuration is an alternative to the
`uv run fastapi dev` command above if you want to run/debug through VS
Code's debugger instead of a terminal - same port (8080), no
`--reload` (a debugger and file-watcher reload don't mix well together).

**Startup order matters a little**: the API and worker both call out to the
LLM proxy and embedding service the moment a real request needs them (chat,
ingest, Planner) - if those aren't up yet, you'll get a clean `503`/error
rather than a hang, but it's simplest to just have all four running before
you start clicking around.

## 6. Start the frontend

```bash
cd frontend
cp .env.example .env.local   # already points at localhost:8080, matching the API port above
pnpm dev
```

See `frontend/README.md` for the frontend's own stack/layout notes.

## Everything running, at a glance

| Service | Command | Port | Purpose |
|---|---|---|---|
| API | `uv run fastapi dev --reload-dir src --port 8080` | 8080 | The backend itself |
| Celery worker | `make celery` | - | Planner generate/refine jobs |
| LLM proxy | `make llm-proxy` | 4000 | Self-hosted relay to Groq/Hugging Face |
| Embedding service | `make embedding-service` | 4001 | Self-hosted BGE-M3, loaded once |
| Frontend | `pnpm dev` (from `frontend/`) | 3000 | Next.js app |
| Mongo | `docker compose up -d` | 27017 | Primary datastore |
| Redis | `docker compose up -d` | 6379 | Quota/rate-limit/cache/Celery broker |
| Chroma | `docker compose up -d` | 8000 (Chroma's own) | Vector store |
| MinIO | `docker compose up -d` | 9000 / 9001 (console) | S3-compatible document storage |
| Grafana | `docker compose up -d` | 3001 | Logs (Loki-backed) |

## Running tests

```bash
uv run pytest -q
```

Mongo and Redis are provisioned automatically per test run via
[testcontainers](https://testcontainers.com/) (throwaway containers, torn
down after) and the embedding service is spun up automatically too (a real
subprocess, `tests/conftest.py` manages its lifecycle) - **you don't need
`make celery`/`make llm-proxy`/`make embedding-service` running to run the
test suite**, only Docker itself needs to be available. Chroma and MinIO
still come from `docker compose up -d` (step 2 above) - not yet
containerized per-test-run the way Mongo/Redis are.

```bash
uv run ruff check .   # lint
```

## Everyday commands

```bash
make celery              # Celery worker
make llm-proxy           # LLM proxy
make embedding-service   # Embedding service
uv run pytest -q         # backend tests
uv run ruff check .      # backend lint
pnpm --dir frontend build  # frontend production build + typecheck
pnpm --dir frontend lint   # frontend lint
```
