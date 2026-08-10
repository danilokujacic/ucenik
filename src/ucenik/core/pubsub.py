"""Redis pub/sub - progress updates for long-running background jobs
(Planner generate/refine, §Phase 6/7). One channel per plan:
`planner:{plan_id}` - every Lecture under a Plan reports progress on its
Plan's channel, so a single WebSocket connection (api/ws.py) covers a whole
plan's worth of in-flight generation/refine jobs, not one per lecture.

Publish side runs from inside a Celery task (workers/planner_tasks.py, via
its async inner function). Subscribe side is the WebSocket endpoint,
forwarding messages straight to the browser. Pub/sub has no replay or
persistence - a subscriber only sees messages published *after* it
subscribes, so the WebSocket connection has to already be open before the
task that would publish to it starts (see api/ws.py's docstring).
"""

import json
from collections.abc import AsyncIterator

from ucenik.core.redis import get_redis


def _channel(plan_id: str) -> str:
    return f"planner:{plan_id}"


async def publish_progress(plan_id: str, event: dict) -> None:
    redis = get_redis()
    await redis.publish(_channel(plan_id), json.dumps(event))


async def subscribe(plan_id: str) -> AsyncIterator[dict]:
    """Yields progress events published to `plan_id`'s channel, forever
    (until the caller stops iterating / the connection is torn down) -
    api/ws.py drives this directly into a WebSocket send loop.
    """
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(_channel(plan_id))
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue  # "subscribe" confirmation, etc. - not an actual event
            yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(_channel(plan_id))
        await pubsub.aclose()
