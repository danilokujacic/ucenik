#!/bin/sh
# Starts the embedding service for local dev (src/ucenik/embedding_service/
# - see its main.py module docstring for what it is and why it exists as
# its own process). Port 4001 matches the default
# EMBEDDING_SERVICE_URL=http://localhost:4001 in .env.example - the main
# app and Celery worker both talk to this over HTTP for embeddings, so it
# needs to be running before either of them ingests a document or runs a
# Tutor/Planner retrieval.
#
# --host 127.0.0.1 explicitly: see scripts/run-llm-proxy.sh's comment on
# this exact flag - same reasoning, same fix. `fastapi run` defaults to
# 0.0.0.0, EMBEDDING_SERVICE_API_KEY is empty by default in local dev, and
# this runs as a plain process on your actual machine (not isolated inside
# docker-compose.prod.yaml's network the way the prod deployment is).
set -eu
cd "$(dirname "$0")/.."
exec uv run fastapi run src/ucenik/embedding_service/main.py --host 127.0.0.1 --port 4001
