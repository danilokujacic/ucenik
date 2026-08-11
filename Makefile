# Local dev process runners. Each backend service (main API, Celery worker,
# LLM proxy, embedding service) runs as its own foreground process in its
# own terminal - see README.md for the main API (`uv run fastapi dev`, not
# duplicated here since it's the one already documented there). These wrap
# the exact commands documented in workers/celery_app.py's,
# llm_proxy/main.py's, and embedding_service/main.py's own docstrings, so
# there's one obvious way to start them instead of everyone retyping (and
# inevitably drifting from) the same long command.

.PHONY: celery llm-proxy embedding-service

celery:
	./scripts/run-celery.sh

llm-proxy:
	./scripts/run-llm-proxy.sh

embedding-service:
	./scripts/run-embedding-service.sh
