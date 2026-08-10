import json
from unittest.mock import AsyncMock, patch

from tests.conftest import auth_headers, fake_completion, fake_stream_completion, login
from ucenik.enum.user_role import UserRole
from ucenik.errors.service import QuotaExceededError
from ucenik.llm.proxy_client import LLMProxyError


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
    return events


async def _ready_subject(client, headers, name="Biology") -> str:
    """Real end-to-end ingest (real chunking/embedding/Chroma storage, only
    the LLM contextualizer call mocked) - same pattern as test_documents.py's
    test_full_ingest_pipeline_end_to_end, so chat retrieval has something
    real to search against.
    """
    create = await client.post("/subjects", json={"name": name}, headers=headers)
    subject_id = create.json()["id"]
    text = (
        b"Mitosis is the process by which a single cell divides into two identical "
        b"daughter cells. It occurs in four main stages: prophase, metaphase, "
        b"anaphase, and telophase."
    )
    with patch(
        "ucenik.rag.contextualizer.complete",
        AsyncMock(return_value=fake_completion("A biology chapter on mitosis.")),
    ):
        upload = await client.post(
            f"/subjects/{subject_id}/documents",
            files={"file": ("mitosis.txt", text, "text/plain")},
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
    return subject_id


async def test_not_enrolled_student_cannot_create_session(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    await make_user("outsider@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")
    outsider_tokens = await login(client, "outsider@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(t_tokens))

    response = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(outsider_tokens))

    assert response.status_code == 403


async def test_ask_question_streams_answer_and_persists_messages(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))

    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    assert session.status_code == 201
    session_id = session.json()["id"]

    with patch(
        "ucenik.rag.generator.stream_complete",
        AsyncMock(return_value=fake_stream_completion(["Mitosis ", "has four ", "stages."])),
    ):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    token_events = [data["content"] for event, data in events if event == "token"]
    assert token_events == ["Mitosis ", "has four ", "stages."]

    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    assert done_events[0]["usage"]["total_tokens"] == 42
    assert done_events[0]["sources"], "should cite at least one source chunk"
    assert done_events[0]["sources"][0]["source_filename"] == "mitosis.txt"

    history = await client.get(
        f"/subjects/{subject_id}/chat/sessions/{session_id}/messages", headers=auth_headers(tokens)
    )
    assert history.status_code == 200
    body = history.json()
    assert [m["role"] for m in body] == ["user", "assistant"]
    assert body[0]["content"] == "What are the stages of mitosis?"
    assert body[1]["content"] == "Mitosis has four stages."
    assert body[1]["sources"][0]["source_filename"] == "mitosis.txt"

    listing = await client.get(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    assert listing.json()[0]["title"] == "What are the stages of mitosis?"


async def test_quota_exceeded_returns_429_before_streaming(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    with patch(
        "ucenik.services.chat.check_quota",
        AsyncMock(side_effect=QuotaExceededError("u", 1, 1, retry_after_seconds=3600)),
    ):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "anything"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"


async def test_llm_failure_surfaces_as_sse_error_and_saves_no_answer(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    with patch("ucenik.rag.generator.stream_complete", AsyncMock(side_effect=LLMProxyError("proxy down"))):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0][0] == "error"

    history = await client.get(
        f"/subjects/{subject_id}/chat/sessions/{session_id}/messages", headers=auth_headers(tokens)
    )
    # the question is saved (so a retry has history), but no assistant
    # message - nothing coherent was generated to persist
    assert [m["role"] for m in history.json()] == ["user"]


async def test_sessions_are_private_to_their_owner(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    student_a = await make_user("student-a@x.com", UserRole.STUDENT)
    student_b = await make_user("student-b@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")
    a_tokens = await login(client, "student-a@x.com", "password123")
    b_tokens = await login(client, "student-b@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(t_tokens))

    for student in (student_a, student_b):
        enroll = await client.post(
            f"/subjects/{subject_id}/enrollments",
            json={"student_id": str(student.id)},
            headers=auth_headers(t_tokens),
        )
        assert enroll.status_code == 201

    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(a_tokens))
    session_id = session.json()["id"]

    # student B (also enrolled, but not the owner) cannot read A's session
    forbidden = await client.get(
        f"/subjects/{subject_id}/chat/sessions/{session_id}/messages", headers=auth_headers(b_tokens)
    )
    assert forbidden.status_code == 404

    # nor can the owning teacher - Tutor sessions have no admin/teacher bypass
    forbidden_teacher = await client.get(
        f"/subjects/{subject_id}/chat/sessions/{session_id}/messages", headers=auth_headers(t_tokens)
    )
    assert forbidden_teacher.status_code == 404


async def test_delete_session_removes_it_and_its_messages(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    with patch("ucenik.rag.generator.stream_complete", AsyncMock(return_value=fake_stream_completion(["Hi."]))):
        await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "hello"},
            headers=auth_headers(tokens),
        )

    delete = await client.delete(f"/subjects/{subject_id}/chat/sessions/{session_id}", headers=auth_headers(tokens))
    assert delete.status_code == 204

    from ucenik.models.chat_messages import ChatMessage

    remaining = await ChatMessage.find(ChatMessage.session_id == session_id).to_list()
    assert remaining == []

    get_after = await client.get(
        f"/subjects/{subject_id}/chat/sessions/{session_id}/messages", headers=auth_headers(tokens)
    )
    assert get_after.status_code == 404


async def test_repeated_first_question_across_sessions_hits_cache(client, make_user):
    """docs/backlog.md item 8: a verbatim-same first question in a new
    session should skip retrieval + generation entirely.
    """
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))

    session1 = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session1_id = session1.json()["id"]

    mock_stream = AsyncMock(return_value=fake_stream_completion(["Mitosis ", "has four ", "stages."]))
    with patch("ucenik.rag.generator.stream_complete", mock_stream):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session1_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )
    assert response.status_code == 200
    done = [d for e, d in _parse_sse(response.text) if e == "done"][0]
    assert done["cached"] is False
    assert mock_stream.call_count == 1

    # A different session, same question modulo whitespace/case - the
    # cache key is normalized (cache/chat_cache.py).
    session2 = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session2_id = session2.json()["id"]

    with patch("ucenik.rag.generator.stream_complete", mock_stream):
        response2 = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session2_id}/messages",
            json={"question": "  what ARE the stages of mitosis?  "},
            headers=auth_headers(tokens),
        )
    assert response2.status_code == 200
    events2 = _parse_sse(response2.text)
    done2 = [d for e, d in events2 if e == "done"][0]
    assert done2["cached"] is True
    assert mock_stream.call_count == 1  # not called a second time
    token_events2 = [d["content"] for e, d in events2 if e == "token"]
    assert token_events2 == ["Mitosis has four stages."]

    # persisted like any other assistant message, so history reads normally
    history = await client.get(
        f"/subjects/{subject_id}/chat/sessions/{session2_id}/messages", headers=auth_headers(tokens)
    )
    assert [m["role"] for m in history.json()] == ["user", "assistant"]
    assert history.json()[1]["content"] == "Mitosis has four stages."


async def test_second_question_in_a_session_never_uses_cache(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    mock_stream = AsyncMock(return_value=fake_stream_completion(["Answer."]))
    with patch("ucenik.rag.generator.stream_complete", mock_stream):
        await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )
        # same question again, but now it's the session's SECOND question -
        # history disqualifies it from the cache (cache/chat_cache.py).
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 200
    done = [d for e, d in _parse_sse(response.text) if e == "done"][0]
    assert done["cached"] is False
    assert mock_stream.call_count == 2


async def test_cache_hit_skips_the_quota_check(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session1 = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session1_id = session1.json()["id"]

    with patch(
        "ucenik.rag.generator.stream_complete",
        AsyncMock(return_value=fake_stream_completion(["Cached answer."])),
    ):
        await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session1_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    session2 = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session2_id = session2.json()["id"]

    # A blown quota would normally 429 before any streaming starts - a
    # cache hit must bypass that check entirely, since nothing gets billed.
    with patch(
        "ucenik.services.chat.check_quota", AsyncMock(side_effect=QuotaExceededError("u", 1, 1))
    ) as mock_check_quota:
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session2_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 200
    done = [d for e, d in _parse_sse(response.text) if e == "done"][0]
    assert done["cached"] is True
    mock_check_quota.assert_not_called()


async def test_reingest_invalidates_cached_answer(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session1 = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session1_id = session1.json()["id"]

    with patch(
        "ucenik.rag.generator.stream_complete",
        AsyncMock(return_value=fake_stream_completion(["Stale answer."])),
    ):
        await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session1_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    # a second document lands - bumps the subject's content version
    # (rag/ingest.py) and should invalidate the cached answer above
    with patch(
        "ucenik.rag.contextualizer.complete",
        AsyncMock(return_value=fake_completion("More biology.")),
    ):
        upload = await client.post(
            f"/subjects/{subject_id}/documents",
            files={"file": ("more.txt", b"Meiosis produces four genetically distinct gametes.", "text/plain")},
            headers=auth_headers(tokens),
        )
        assert upload.status_code == 201, upload.text

    session2 = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session2_id = session2.json()["id"]

    mock_stream = AsyncMock(return_value=fake_stream_completion(["Fresh answer."]))
    with patch("ucenik.rag.generator.stream_complete", mock_stream):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session2_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 200
    done = [d for e, d in _parse_sse(response.text) if e == "done"][0]
    assert done["cached"] is False  # invalidated, not served stale
    mock_stream.assert_called_once()


async def test_no_ingested_documents_yields_empty_sources_not_an_error(client, make_user):
    """No chunks to retrieve -> the LLM still gets asked (with an explicit
    "nothing relevant was found" context, see rag/generator.py) rather than
    the endpoint failing outright.
    """
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    create = await client.post("/subjects", json={"name": "Empty Subject"}, headers=auth_headers(tokens))
    subject_id = create.json()["id"]
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    with patch(
        "ucenik.rag.generator.stream_complete",
        AsyncMock(return_value=fake_stream_completion(["I don't know."])),
    ):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "anything"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done_events = [data for event, data in events if event == "done"]
    assert done_events[0]["sources"] == []


async def test_generate_title_uses_llm_and_persists_it(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    with patch("ucenik.rag.generator.stream_complete", AsyncMock(return_value=fake_stream_completion(["Hi."]))):
        await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    with patch(
        "ucenik.services.chat.generate_title",
        AsyncMock(return_value=fake_completion('"Mitosis Stages"')),
    ) as mock_title:
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/title", headers=auth_headers(tokens)
        )

    assert response.status_code == 200
    assert response.json()["title"] == "Mitosis Stages"
    mock_title.assert_awaited_once_with("What are the stages of mitosis?")

    listing = await client.get(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    assert listing.json()[0]["title"] == "Mitosis Stages"


async def test_generate_title_before_any_message_returns_409(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    response = await client.post(
        f"/subjects/{subject_id}/chat/sessions/{session_id}/title", headers=auth_headers(tokens)
    )

    assert response.status_code == 409


async def test_generate_title_llm_failure_returns_503_and_keeps_old_title(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    with patch("ucenik.rag.generator.stream_complete", AsyncMock(return_value=fake_stream_completion(["Hi."]))):
        await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    with patch("ucenik.services.chat.generate_title", AsyncMock(side_effect=LLMProxyError("proxy down"))):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/title", headers=auth_headers(tokens)
        )

    assert response.status_code == 503

    listing = await client.get(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    assert listing.json()[0]["title"] == "What are the stages of mitosis?"


async def test_generate_title_is_private_to_the_owner(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    student_a = await make_user("student-a@x.com", UserRole.STUDENT)
    student_b = await make_user("student-b@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")
    a_tokens = await login(client, "student-a@x.com", "password123")
    b_tokens = await login(client, "student-b@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(t_tokens))

    for student in (student_a, student_b):
        await client.post(
            f"/subjects/{subject_id}/enrollments",
            json={"student_id": str(student.id)},
            headers=auth_headers(t_tokens),
        )

    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(a_tokens))
    session_id = session.json()["id"]

    forbidden = await client.post(
        f"/subjects/{subject_id}/chat/sessions/{session_id}/title", headers=auth_headers(b_tokens)
    )
    assert forbidden.status_code == 404


async def test_sources_deduplicated_by_document_id(client, make_user):
    """Retrieval can return several chunks from the same document - the
    citation list should mention that document once, not once per chunk.
    """
    from ucenik.rag.retriever import RetrievedChunk

    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")
    subject_id = await _ready_subject(client, auth_headers(tokens))
    session = await client.post(f"/subjects/{subject_id}/chat/sessions", headers=auth_headers(tokens))
    session_id = session.json()["id"]

    chunks = [
        RetrievedChunk(id="c1", text="Mitosis has four stages.", document_id="doc-1", source_filename="mitosis.txt"),
        RetrievedChunk(id="c2", text="Prophase is first.", document_id="doc-1", source_filename="mitosis.txt"),
        RetrievedChunk(id="c3", text="Metaphase is next.", document_id="doc-2", source_filename="cells.txt"),
    ]

    with (
        patch("ucenik.services.chat.retrieve", AsyncMock(return_value=chunks)),
        patch(
            "ucenik.rag.generator.stream_complete",
            AsyncMock(return_value=fake_stream_completion(["Mitosis ", "has four ", "stages."])),
        ),
    ):
        response = await client.post(
            f"/subjects/{subject_id}/chat/sessions/{session_id}/messages",
            json={"question": "What are the stages of mitosis?"},
            headers=auth_headers(tokens),
        )

    assert response.status_code == 200
    done = [data for event, data in _parse_sse(response.text) if event == "done"][0]
    assert [s["document_id"] for s in done["sources"]] == ["doc-1", "doc-2"]
