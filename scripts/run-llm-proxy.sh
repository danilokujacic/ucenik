#!/bin/sh
# Starts the self-hosted LLM proxy for local dev (src/ucenik/llm_proxy/ -
# see its main.py module docstring for what this service is and why it
# exists as its own process). Port 4000 matches the default
# LLM_PROXY_URL=http://localhost:4000 in .env.example - the main app and
# Celery worker both talk to this over HTTP, so it needs to be running
# before either of them can make an LLM call.
#
# --host 127.0.0.1 explicitly: `fastapi run` (unlike `fastapi dev`, which
# already defaults to 127.0.0.1) defaults to 0.0.0.0 - meant for "public
# access, e.g. in a container" per its own --help text. Fine and necessary
# in docker-compose.prod.yaml (reached by sibling containers over the
# docker network, never exposed to the host - no `ports:` published
# there), wrong here: this runs as a plain process on your actual machine,
# with LLM_PROXY_API_KEY empty by default in local dev, so 0.0.0.0 would
# mean anyone who can reach this machine on port 4000 gets unauthenticated
# LLM calls billed to your real Groq/HF key. Found by actually checking
# what this bound to (`ss -ltnp`), not assumed.
set -eu
cd "$(dirname "$0")/.."
exec uv run fastapi run src/ucenik/llm_proxy/main.py --host 127.0.0.1 --port 4000
