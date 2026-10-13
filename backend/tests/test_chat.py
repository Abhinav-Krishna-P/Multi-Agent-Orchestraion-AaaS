import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from tests.fakes import scripted
from tests.test_agents import GEMINI_MODEL
from tests.test_sessions import create_session, live_agent

USER_KEY = "AIza-user-key-7777"


def read_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def tokens(events) -> str:
    return "".join(data["text"] for name, data in events if name == "token")


async def stored(db, session_id: str) -> list[tuple[str, str]]:
    from app.db.models import Message

    rows = await db.scalars(
        select(Message).where(Message.session_id == uuid.UUID(session_id)).order_by(Message.created_at)
    )
    return [(m.role, m.content) for m in rows]


@pytest.fixture
def use_model(app):
    """Makes the app build the given fake model, and records what it was asked to build."""
    from app.agent.llm import get_model_factory

    calls = []

    def _use(model):
        def factory(provider: str, model_id: str, api_key: str):
            calls.append((provider, model_id, api_key))
            return model

        app.dependency_overrides[get_model_factory] = lambda: factory
        return calls

    return _use


@pytest.fixture
async def live_chat(client, user_a, app):
    """A live agent with a model, a saved key, and one empty chat. Returns (agent, session)."""
    from app.agent.llm import get_key_validator

    async def _valid(provider, key):
        return True

    app.dependency_overrides[get_key_validator] = lambda: _valid
    agent = await live_agent(client, user_a)
    await client.patch(
        f"/agents/{agent['id']}", json={"llm_provider": "gemini", "llm_model": GEMINI_MODEL}, headers=user_a
    )
    await client.put("/llm-keys/gemini", json={"api_key": USER_KEY}, headers=user_a)
    session = await create_session(client, user_a, agent["id"])
    return agent, session


async def send(client, headers, session_id, body):
    from app.agent import runner

    response = await client.post(f"/sessions/{session_id}/chat", json=body, headers=headers)
    await runner.wait_for_background()
    return response


# --- the normal path ---------------------------------------------------------------


async def test_reply_streams_and_is_saved(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted(["Hello", " there"]))
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = read_events(r.text)
    assert tokens(events) == "Hello there"
    assert events[-1][0] == "done"
    assert uuid.UUID(events[-1][1]["message_id"])
    assert await stored(db, session["id"]) == [("user", "Hi"), ("assistant", "Hello there")]


async def test_model_is_built_with_the_users_key(client, user_a, live_chat, use_model):
    _, session = live_chat
    calls = use_model(scripted(["ok"]))
    await send(client, user_a, session["id"], {"message": "Hi"})
    assert calls == [("gemini", GEMINI_MODEL, USER_KEY)]


async def test_model_receives_prompt_and_history(client, user_a, live_chat, use_model):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from app.agent.personas import get_persona

    _, session = live_chat
    model = scripted(["first reply"], ["second reply"])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "one"})
    await send(client, user_a, session["id"], {"message": "two"})
    second_call = model.received[1]
    assert [type(m) for m in second_call] == [SystemMessage, HumanMessage, AIMessage, HumanMessage]
    assert second_call[0].content == get_persona("friend").prompt
    assert [m.content for m in second_call[1:]] == ["one", "first reply", "two"]


async def test_message_is_trimmed(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted(["ok"]))
    await send(client, user_a, session["id"], {"message": "  Hi  "})
    assert (await stored(db, session["id"]))[0] == ("user", "Hi")


async def test_first_message_sets_title(client, user_a, live_chat, use_model):
    _, session = live_chat
    use_model(scripted(["a"], ["b"]))
    long_message = "What is the latest project I am working on in GitHub and when was it updated?"
    await send(client, user_a, session["id"], {"message": long_message})
    detail = (await client.get(f"/sessions/{session['id']}", headers=user_a)).json()
    assert detail["title"] == long_message[:60]
    await send(client, user_a, session["id"], {"message": "Another question"})
    detail = (await client.get(f"/sessions/{session['id']}", headers=user_a)).json()
    assert detail["title"] == long_message[:60]


async def test_reply_moves_chat_to_top(client, user_a, live_chat, use_model):
    agent, first = live_chat
    second = await create_session(client, user_a, agent["id"])
    use_model(scripted(["ok"]))
    await send(client, user_a, first["id"], {"message": "Hi"})
    listed = (await client.get(f"/agents/{agent['id']}/sessions", headers=user_a)).json()
    assert [s["id"] for s in listed] == [first["id"], second["id"]]


async def test_list_content_chunks_are_joined(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted([[{"type": "text", "text": "Hello"}], [{"type": "text", "text": " world"}]]))
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert tokens(read_events(r.text)) == "Hello world"
    assert (await stored(db, session["id"]))[-1] == ("assistant", "Hello world")


def test_sse_format():
    from app.agent.runner import sse

    assert sse("token", {"text": "hi\nthere"}) == 'event: token\ndata: {"text": "hi\\nthere"}\n\n'


# --- refused before any streaming -------------------------------------------------


@pytest.mark.parametrize(
    "body", [{"message": ""}, {"message": "   "}, {"message": "x" * 20001}, {}, {"retry": False}, {"message": 5}]
)
async def test_bad_message_422_saves_nothing(client, user_a, live_chat, use_model, db, body):
    _, session = live_chat
    use_model(scripted(["never used"]))
    r = await send(client, user_a, session["id"], body)
    assert r.status_code == 422
    assert await stored(db, session["id"]) == []


async def test_longest_allowed_message_accepted(client, user_a, live_chat, use_model):
    _, session = live_chat
    use_model(scripted(["ok"]))
    r = await send(client, user_a, session["id"], {"message": "x" * 20000})
    assert r.status_code == 200


async def test_stopped_agent_409(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    use_model(scripted(["never used"]))
    await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "agent_not_live"
    assert await stored(db, session["id"]) == []


async def test_no_model_409(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    use_model(scripted(["never used"]))
    await client.patch(f"/agents/{agent['id']}", json={"llm_provider": None, "llm_model": None}, headers=user_a)
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "llm_not_configured"
    assert await stored(db, session["id"]) == []


async def test_no_key_409(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted(["never used"]))
    await client.delete("/llm-keys/gemini", headers=user_a)
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "missing_api_key"
    assert "Gemini" in r.json()["detail"]["message"]
    assert await stored(db, session["id"]) == []


async def test_key_for_other_provider_does_not_count(client, user_a, live_chat, use_model):
    agent, session = live_chat
    use_model(scripted(["never used"]))
    await client.patch(
        f"/agents/{agent['id']}", json={"llm_provider": "openai", "llm_model": "gpt-6.1-sol"}, headers=user_a
    )
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "missing_api_key"
    assert "OpenAI" in r.json()["detail"]["message"]


async def test_deleted_agent_404(client, user_a, live_chat, use_model):
    agent, session = live_chat
    use_model(scripted(["never used"]))
    await client.delete(f"/agents/{agent['id']}", headers=user_a)
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 404


async def test_other_user_gets_404(client, user_a, user_b, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted(["never used"]))
    r = await send(client, user_b, session["id"], {"message": "Hi"})
    assert r.status_code == 404
    assert await stored(db, session["id"]) == []


# --- failures and retry --------------------------------------------------------------


async def test_model_failure_sends_error_then_done(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted(["Half a", " reply"], fail_after=1))
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 200
    events = read_events(r.text)
    assert events[-2] == (
        "error",
        {"code": "model_error", "message": "The model couldn't reply. Check your API key and try again."},
    )
    assert events[-1] == ("done", {"message_id": None})
    assert await stored(db, session["id"]) == [("user", "Hi")]


async def test_error_has_no_key_or_exception_text(client, user_a, live_chat, use_model, caplog):
    _, session = live_chat
    use_model(scripted(["x", "y"], fail_after=1))
    with caplog.at_level("DEBUG"):
        r = await send(client, user_a, session["id"], {"message": "Hi"})
    for leaked in ("sk-leaky", "provider exploded", USER_KEY):
        assert leaked not in r.text
        assert leaked not in caplog.text


async def test_empty_reply_is_an_error(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted([""]))
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert [name for name, _ in read_events(r.text)] == ["error", "done"]
    assert await stored(db, session["id"]) == [("user", "Hi")]


async def test_model_that_cannot_be_built_is_an_error(client, user_a, live_chat, app, db):
    from app.agent.llm import get_model_factory

    def broken_factory(provider, model_id, api_key):
        raise ValueError(f"bad config for {api_key}")

    app.dependency_overrides[get_model_factory] = lambda: broken_factory
    _, session = live_chat
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert [name for name, _ in read_events(r.text)] == ["error", "done"]
    assert USER_KEY not in r.text
    assert await stored(db, session["id"]) == [("user", "Hi")]


async def test_retry_answers_without_duplicating(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted(["x", "y"], fail_after=1))
    await send(client, user_a, session["id"], {"message": "Hi"})
    model = scripted(["Recovered"])
    use_model(model)
    r = await send(client, user_a, session["id"], {"retry": True})
    assert r.status_code == 200
    assert tokens(read_events(r.text)) == "Recovered"
    assert await stored(db, session["id"]) == [("user", "Hi"), ("assistant", "Recovered")]
    assert model.received[0][-1].content == "Hi"


@pytest.mark.parametrize("answered_first", [False, True])
async def test_retry_with_nothing_to_retry_409(client, user_a, live_chat, use_model, db, answered_first):
    _, session = live_chat
    use_model(scripted(["a"], ["never used"]))
    if answered_first:
        await send(client, user_a, session["id"], {"message": "Hi"})
    before = await stored(db, session["id"])
    r = await send(client, user_a, session["id"], {"retry": True})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "nothing_to_retry"
    assert await stored(db, session["id"]) == before


async def test_refused_retry_does_not_block_the_chat(client, user_a, live_chat, use_model):
    _, session = live_chat
    use_model(scripted(["ok"]))
    await send(client, user_a, session["id"], {"retry": True})
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert r.status_code == 200


# --- one reply at a time -------------------------------------------------------------


async def test_second_send_while_replying_409(client, user_a, live_chat, use_model, db):
    from app.agent import runner

    _, session = live_chat
    use_model(scripted(["ok"]))
    assert runner.try_begin(uuid.UUID(session["id"])) is True
    try:
        r = await send(client, user_a, session["id"], {"message": "Hi"})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "reply_in_progress"
        assert await stored(db, session["id"]) == []
    finally:
        runner.end(uuid.UUID(session["id"]))
    assert (await send(client, user_a, session["id"], {"message": "Hi"})).status_code == 200


def test_try_begin_refuses_a_second_reply_until_the_first_ends():
    from app.agent import runner

    session_id = uuid.uuid4()
    assert runner.try_begin(session_id) is True
    assert runner.try_begin(session_id) is False
    runner.end(session_id)
    assert runner.try_begin(session_id) is True
    runner.end(session_id)


async def test_claim_released_when_stream_never_starts():
    """The client vanishes before the first byte: the reply generator is never run,
    and the chat must still be free for the next message."""
    from app.agent import runner
    from app.api.chat import TurnResponse

    session_id = uuid.uuid4()
    assert runner.try_begin(session_id)
    started = []

    async def events():
        started.append(True)
        yield "never sent"

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        raise OSError("client went away")

    response = TurnResponse(events(), session_id)
    with pytest.raises(Exception):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert started == []
    assert runner.try_begin(session_id) is True
    runner.end(session_id)


async def test_two_sends_in_a_row_both_answered(client, user_a, live_chat, use_model, db):
    _, session = live_chat
    use_model(scripted(["one"], ["two"]))
    assert (await send(client, user_a, session["id"], {"message": "a"})).status_code == 200
    assert (await send(client, user_a, session["id"], {"message": "b"})).status_code == 200
    assert [content for _, content in await stored(db, session["id"])] == ["a", "one", "b", "two"]


# --- stopping a reply ------------------------------------------------------------------


async def _start_turn(db, session, model):
    """Saves a user message and starts run_turn directly, as the endpoint would."""
    from app.agent import runner
    from app.db.models import Message

    session_id = uuid.UUID(session["id"])
    db.add(Message(session_id=session_id, role="user", content="Hi"))
    await db.commit()
    return session_id, runner.run_turn(session_id=session_id, system_prompt="P", summary=None, model=model)


async def test_closing_the_stream_saves_partial_reply(live_chat, db):
    from app.agent import runner

    _, session = live_chat
    gate = asyncio.Event()
    session_id, turn = await _start_turn(db, session, scripted(["Partial", " never sent"], gate=gate))
    first = await turn.__anext__()
    assert read_events(first) == [("token", {"text": "Partial"})]
    await turn.aclose()
    await runner.wait_for_background()
    assert await stored(db, session["id"]) == [("user", "Hi"), ("assistant", "Partial")]


async def test_cancelled_request_saves_partial_reply(live_chat, db):
    from app.agent import runner

    _, session = live_chat
    gate = asyncio.Event()
    session_id, turn = await _start_turn(db, session, scripted(["Partial", " never sent"], gate=gate))
    got_first = asyncio.Event()

    async def consume():
        async for _ in turn:
            got_first.set()

    task = asyncio.create_task(consume())
    await got_first.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await runner.wait_for_background()
    assert await stored(db, session["id"]) == [("user", "Hi"), ("assistant", "Partial")]


async def test_stopping_before_any_text_saves_nothing(live_chat, db):
    from app.agent import runner

    _, session = live_chat

    class Never(asyncio.Event):
        pass

    model = scripted(["", "late"], gate=Never())
    session_id, turn = await _start_turn(db, session, model)
    task = asyncio.create_task(turn.__anext__())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await runner.wait_for_background()
    assert await stored(db, session["id"]) == [("user", "Hi")]


# --- building the real model object ---------------------------------------------------


@pytest.mark.parametrize(
    "provider, model_id, class_name",
    [("gemini", GEMINI_MODEL, "ChatGoogleGenerativeAI"), ("openai", "gpt-6.1-sol", "ChatOpenAI")],
)
def test_build_chat_model_hides_the_key(provider, model_id, class_name):
    from app.agent.llm import build_chat_model

    model = build_chat_model(provider, model_id, "secret-key-value-123")
    assert type(model).__name__ == class_name
    assert "secret-key-value-123" not in repr(model)
    assert "secret-key-value-123" not in str(model.model_dump() if hasattr(model, "model_dump") else "")
