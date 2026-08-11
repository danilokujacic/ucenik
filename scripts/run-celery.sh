#!/bin/sh
# Starts the Celery worker for local dev (Planner background jobs - see
# workers/celery_app.py's docstring). --pool=solo is not optional here:
# that docstring explains why (this codebase is async-native throughout,
# and prefork's forking breaks an asyncio event loop set up before the
# fork) - don't drop it to get concurrency, run multiple `solo` workers
# instead if that's ever needed.
#
# Needs the infra in docker-compose.yaml running first (Mongo/Redis at
# minimum - see docker-compose.yaml at repo root).
set -eu
cd "$(dirname "$0")/.."
exec uv run celery -A ucenik.workers.celery_app worker --pool=solo --loglevel=info
