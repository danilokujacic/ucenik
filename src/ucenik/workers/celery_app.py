"""Celery app for Planner background jobs (§Phase 6/7 - generate/refine a
lecture). Redis doubles as both broker and result backend, reusing the same
instance docker-compose already provisions for quota/rate-limiting/caching -
no new infra service for local dev.

Run the worker with the `solo` pool specifically:

    uv run celery -A ucenik.workers.celery_app worker --pool=solo --loglevel=info

Why `solo`, not the default `prefork`: every task here needs async I/O
(Motor/Beanie for Mongo, the Chroma client, the LLM proxy, Redis pub/sub) -
there's no sync version of any of that to call instead, this whole codebase
is async-native. `prefork` forks a new OS process per worker *after* Celery
boots, which breaks any asyncio event loop / Motor connection created before
the fork (a well-known Celery+asyncio pitfall - the child process inherits a
half-open socket bound to a loop that no longer belongs to it). `solo` runs
everything in the single main process, no forking, so one event loop set up
once at worker startup (`_worker_init` below) stays valid for the worker's
whole lifetime. Scale by running multiple independent `solo` worker
processes, not by prefork's in-process concurrency.

Testing note: this file is deliberately *not* exercised by task_always_eager
in the test suite - see workers/planner_tasks.py's docstring for why, and
how the actual task logic gets tested instead.
"""

import asyncio
import logging

from celery import Celery
from celery.signals import after_setup_logger, worker_process_init, worker_process_shutdown

from ucenik.core.config import settings
from ucenik.core.logging_config import configure_logging

logger = logging.getLogger(__name__)

celery_app = Celery(
    "ucenik",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # A standalone `celery worker -A ucenik.workers.celery_app` process only
    # ever imports *this* module by default - it has no reason to know
    # workers/planner_tasks.py exists, so the @celery_app.task decorators
    # there would never run and no tasks would be registered on it (caught
    # live: worker started clean, connected fine, but its own startup
    # banner listed an empty [tasks] section). `include` tells Celery to
    # import that module too on worker boot, registering its tasks.
    include=["ucenik.workers.planner_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)

# The persistent event loop every task runs on for the life of the worker
# process - see module docstring on why `--pool=solo` makes this safe.
_worker_loop: asyncio.AbstractEventLoop | None = None


def run_async(coro):
    """Run an async coroutine to completion from inside a task's (sync)
    body, on the worker's persistent event loop.
    """
    if _worker_loop is None:
        # No real worker process behind this call (e.g. ad hoc script use,
        # or a direct call outside `celery worker`) - a fresh loop per call
        # is fine when nothing needs a connection to persist across calls.
        return asyncio.run(coro)
    return _worker_loop.run_until_complete(coro)


@after_setup_logger.connect
def _use_json_logging(**kwargs) -> None:
    """Celery installs its own colored-console logging by default, as part
    of its own worker bootstrap - calling configure_logging() at import
    time would just get clobbered right after. `after_setup_logger` is
    Celery's own extension point for exactly this (fires once Celery's
    setup has already run, so this genuinely gets the last word), and
    keeps worker logs in the same structured-JSON-to-Loki pipeline as the
    main app instead of a second, differently-shaped log format Promtail's
    JSON parsing stage wouldn't understand (see observability/promtail-config.yaml).
    """
    configure_logging()


@worker_process_init.connect
def _worker_init(**kwargs) -> None:
    """Runs once when the worker process starts, before any task - sets up
    the persistent event loop and initializes Mongo/Redis/S3 exactly like
    the FastAPI app's lifespan does, since a Celery task has no lifespan of
    its own to hook into.
    """
    global _worker_loop
    from ucenik.core.db import init_db
    from ucenik.core.redis import init_redis
    from ucenik.core.storage import init_storage
    from ucenik.models import ALL_DOCUMENT_MODELS

    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)

    async def _init() -> None:
        await init_db(document_models=ALL_DOCUMENT_MODELS)
        await init_redis()
        await init_storage()

    _worker_loop.run_until_complete(_init())
    logger.info("celery.worker_ready")


@worker_process_shutdown.connect
def _worker_shutdown(**kwargs) -> None:
    global _worker_loop
    if _worker_loop is None:
        return
    from ucenik.core.db import close_db
    from ucenik.core.redis import close_redis

    _worker_loop.run_until_complete(close_db())
    _worker_loop.run_until_complete(close_redis())
    _worker_loop.close()
    _worker_loop = None
