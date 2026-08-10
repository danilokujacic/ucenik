import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import auth_headers, fake_completion, login
from ucenik.enum.user_role import UserRole
from ucenik.errors.service import QuotaExceededError
from ucenik.errors.user_messages import safe_job_error_message
from ucenik.llm.proxy_client import LLMProxyError
from ucenik.workers.planner_tasks import _MAX_RETRIES, generate_lecture, refine_lecture


async def _ready_subject(client, headers, name="History") -> str:
    """Real end-to-end ingest (only the LLM contextualizer call mocked) - so
    Planner generation has something real to retrieve from, same pattern as
    test_chat.py's _ready_subject.
    """
    create = await client.post("/subjects", json={"name": name}, headers=headers)
    subject_id = create.json()["id"]
    text = b"The French Revolution began in 1789 and ended the age of absolute monarchy in France."
    with patch(
        "ucenik.rag.contextualizer.complete",
        AsyncMock(return_value=fake_completion("A history chapter on the French Revolution.")),
    ):
        upload = await client.post(
            f"/subjects/{subject_id}/documents",
            files={"file": ("revolution.txt", text, "text/plain")},
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
    return subject_id


async def _create_plan(client, headers, subject_id: str) -> str:
    response = await client.post(f"/subjects/{subject_id}/plans", json={"title": "Semester 1"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_lecture(client, headers, subject_id: str, plan_id: str) -> str:
    """Creates a lecture via the real API (dispatch mocked - see
    workers/planner_tasks.py's module docstring for why tests never go
    through .delay()) and returns its id.
    """
    with patch("ucenik.services.lectures.generate_lecture_task"):
        response = await client.post(
            f"/subjects/{subject_id}/plans/{plan_id}/lectures",
            json={"title": "Intro", "topic": "Causes of the French Revolution", "order": 1},
            headers=headers,
        )
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def test_non_owner_cannot_create_plan(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    await make_user("student@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")
    s_tokens = await login(client, "student@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(t_tokens))

    response = await client.post(
        f"/subjects/{subject_id}/plans", json={"title": "Semester 1"}, headers=auth_headers(s_tokens)
    )

    assert response.status_code == 403


async def test_create_lecture_dispatches_generation_task_and_returns_202(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)

    with patch("ucenik.services.lectures.generate_lecture_task") as mock_task:
        response = await client.post(
            f"/subjects/{subject_id}/plans/{plan_id}/lectures",
            json={"title": "Intro", "topic": "Causes of the French Revolution", "order": 1},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["content"] is None
    mock_task.delay.assert_called_once_with(body["id"])


async def test_generate_lecture_produces_a_real_version(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch(
        "ucenik.rag.refiner.complete",
        AsyncMock(return_value=fake_completion("# The French Revolution\n\nIt began in 1789.")),
    ):
        await generate_lecture(lecture_id)

    detail = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}", headers=auth_headers(tokens)
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "ready", body
    assert body["current_version"] == 1
    assert "French Revolution" in body["content"]


async def test_generation_failure_marks_lecture_failed_not_500(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.workers.planner_tasks.check_quota", AsyncMock(side_effect=QuotaExceededError("u", 1, 1))):
        await generate_lecture(lecture_id)

    detail = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}", headers=auth_headers(tokens)
    )
    body = detail.json()
    assert body["status"] == "failed"
    assert "quota" in body["error"].lower()
    assert body["current_version"] == 0


async def test_refine_creates_new_version_and_preserves_old_ones(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Full lecture content."))):
        await generate_lecture(lecture_id)

    with patch("ucenik.services.lectures.refine_lecture_task") as mock_task:
        refine_response = await client.post(
            f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/refine",
            json={"transform": "shorten"},
            headers=auth_headers(tokens),
        )
    assert refine_response.status_code == 202, refine_response.text
    mock_task.delay.assert_called_once_with(lecture_id, "shorten", None)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Shortened content."))):
        await refine_lecture(lecture_id, "shorten")

    versions = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/versions", headers=auth_headers(tokens)
    )
    assert versions.status_code == 200
    body = versions.json()
    assert [v["version"] for v in body] == [1, 2]
    assert body[0]["source"] == "ai_generated"
    assert body[1]["source"] == "ai_refined"
    assert body[1]["content"] == "Shortened content."

    detail = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}", headers=auth_headers(tokens)
    )
    assert detail.json()["current_version"] == 2
    assert detail.json()["content"] == "Shortened content."


async def test_translate_requires_target_language(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Content."))):
        await generate_lecture(lecture_id)

    response = await client.post(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/refine",
        json={"transform": "translate"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 422


async def test_translate_transform_calls_translation_module(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Content."))):
        await generate_lecture(lecture_id)

    with patch(
        "ucenik.rag.translation.complete", AsyncMock(return_value=fake_completion("Contenu en francais."))
    ) as mock_translate:
        await refine_lecture(lecture_id, "translate", "French")

    mock_translate.assert_called_once()
    detail = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}", headers=auth_headers(tokens)
    )
    assert detail.json()["content"] == "Contenu en francais."


async def test_cannot_refine_lecture_with_no_version_yet(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)  # still "pending"

    response = await client.post(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/refine",
        json={"transform": "shorten"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 409


async def test_manual_edit_creates_a_version_with_no_llm_call(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("AI content."))):
        await generate_lecture(lecture_id)

    # deliberately no LLM patch here - a manual edit must never call the proxy
    response = await client.patch(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}",
        json={"content": "Hand-written replacement content."},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_version"] == 2
    assert body["content"] == "Hand-written replacement content."

    versions = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/versions", headers=auth_headers(tokens)
    )
    assert versions.json()[1]["source"] == "manual_edit"


async def test_rollback_creates_new_version_copying_old_content(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Version one content."))):
        await generate_lecture(lecture_id)
    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Version two content."))):
        await refine_lecture(lecture_id, "regenerate")

    rollback = await client.post(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/versions/1/rollback",
        headers=auth_headers(tokens),
    )

    assert rollback.status_code == 200
    body = rollback.json()
    assert body["current_version"] == 3  # rollback is a new version, not a revert-in-place
    assert body["content"] == "Version one content."

    versions = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/versions", headers=auth_headers(tokens)
    )
    assert [v["source"] for v in versions.json()] == ["ai_generated", "ai_refined", "rollback"]


async def test_delete_plan_cascades_lectures_and_versions(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Content."))):
        await generate_lecture(lecture_id)

    delete = await client.delete(f"/subjects/{subject_id}/plans/{plan_id}", headers=auth_headers(tokens))
    assert delete.status_code == 204

    from ucenik.models.lecture_versions import LectureVersion
    from ucenik.models.lectures import Lecture

    assert await Lecture.get(lecture_id) is None
    assert await LectureVersion.find(LectureVersion.lecture_id == lecture_id).to_list() == []


async def test_generate_lecture_publishes_progress_over_pubsub(client, make_user):
    """Real Redis pub/sub round trip - a subscriber connected before
    generate_lecture() runs should see its progress events, exactly the
    contract api/ws.py relies on (see core/pubsub.py's docstring on why the
    subscriber has to connect first: no replay).
    """
    from ucenik.core.pubsub import subscribe

    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    received: list[dict] = []

    async def _listen():
        async for event in subscribe(plan_id):
            received.append(event)
            if event["type"] == "lecture.ready":
                break

    listener = asyncio.create_task(_listen())
    await asyncio.sleep(0.2)  # let the subscribe() call actually register with Redis before publishing

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Content."))):
        await generate_lecture(lecture_id)

    await asyncio.wait_for(listener, timeout=5)

    event_types = [e["type"] for e in received]
    assert event_types == ["lecture.generating", "lecture.ready"]
    assert received[-1]["version"] == 1


async def test_llm_proxy_error_reraises_for_retry_while_attempts_remain(client, make_user):
    """docs/backlog.md item 7: a transient upstream failure with retry
    budget left must re-raise (so the Celery task wrapper can schedule a
    retry) rather than immediately marking the lecture failed.
    """
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    from ucenik.core.pubsub import subscribe

    received: list[dict] = []

    async def _listen():
        async for event in subscribe(plan_id):
            received.append(event)
            if event["type"] == "lecture.retrying":
                break

    listener = asyncio.create_task(_listen())
    await asyncio.sleep(0.2)

    with patch("ucenik.rag.refiner.complete", AsyncMock(side_effect=LLMProxyError("proxy down"))):
        with pytest.raises(LLMProxyError):
            await generate_lecture(lecture_id, attempt=0)

    await asyncio.wait_for(listener, timeout=5)
    assert received[-1] == {
        "type": "lecture.retrying",
        "lecture_id": lecture_id,
        "attempt": 1,
        "max_attempts": _MAX_RETRIES,
    }

    from ucenik.models.lectures import Lecture, LectureStatus

    lecture = await Lecture.get(lecture_id)
    assert lecture.status == LectureStatus.GENERATING  # not failed - still awaiting the scheduled retry
    assert lecture.current_version == 0


async def test_llm_proxy_error_marks_failed_once_retries_exhausted(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(side_effect=LLMProxyError("proxy down"))):
        await generate_lecture(lecture_id, attempt=_MAX_RETRIES)  # no raise - budget's spent

    detail = await client.get(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}", headers=auth_headers(tokens)
    )
    body = detail.json()
    assert body["status"] == "failed"
    # The raw proxy error ("proxy down") is a logged internal detail, not
    # something the end user sees - see errors/user_messages.py.
    assert body["error"] == safe_job_error_message(LLMProxyError("proxy down"))
    assert "proxy down" not in body["error"]


async def test_retry_endpoint_rejects_lecture_that_is_not_failed(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)  # still "pending"

    response = await client.post(
        f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/retry", headers=auth_headers(tokens)
    )

    assert response.status_code == 409


async def test_retry_endpoint_redispatches_generation_for_zero_version_lecture(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.workers.planner_tasks.check_quota", AsyncMock(side_effect=QuotaExceededError("u", 1, 1))):
        await generate_lecture(lecture_id)  # lands as "failed", current_version still 0

    with patch("ucenik.services.lectures.generate_lecture_task") as mock_generate_task:
        response = await client.post(
            f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/retry", headers=auth_headers(tokens)
        )

    assert response.status_code == 202, response.text
    mock_generate_task.delay.assert_called_once_with(lecture_id)


async def test_retry_endpoint_redispatches_last_refine_transform(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    plan_id = await _create_plan(client, auth_headers(tokens), subject_id)
    lecture_id = await _create_lecture(client, auth_headers(tokens), subject_id, plan_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(return_value=fake_completion("Content."))):
        await generate_lecture(lecture_id)

    with patch("ucenik.rag.refiner.complete", AsyncMock(side_effect=LLMProxyError("proxy down"))):
        await refine_lecture(lecture_id, "shorten", attempt=_MAX_RETRIES)  # exhausts retries, lands "failed"

    with patch("ucenik.services.lectures.refine_lecture_task") as mock_refine_task:
        response = await client.post(
            f"/subjects/{subject_id}/plans/{plan_id}/lectures/{lecture_id}/retry", headers=auth_headers(tokens)
        )

    assert response.status_code == 202, response.text
    mock_refine_task.delay.assert_called_once_with(lecture_id, "shorten", None)
