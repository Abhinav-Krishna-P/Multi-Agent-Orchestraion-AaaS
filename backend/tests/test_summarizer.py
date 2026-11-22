import uuid

import pytest

from tests.fakes import scripted
from tests.test_chat import USER_KEY, live_chat, read_events, send, use_model  # noqa: F401  (fixtures)

SUMMARY = "The user asked about their GitHub projects and the agent listed the most recent one."


async def add_messages(db, session_id: str, count: int, start: int = 0):
    from app.db.models import Message

    for i in range(start, start + count):
        role = "user" if i % 2 == 0 else "assistant"
        db.add(Message(session_id=uuid.UUID(session_id), role=role, content=f"message {i}"))
        await db.flush()
    await db.commit()


async def session_row(db, session_id: str):
    from app.db.models import ChatSession

    row = await db.get(ChatSession, uuid.UUID(session_id), populate_existing=True)
    return row


async def test_under_ten_messages_no_summary(live_chat, db):
    from app.agent.summarizer import maybe_update_summary

    _, session = live_chat
    await add_messages(db, session["id"], 9)
    model = scripted([SUMMARY])
    assert await maybe_update_summary(uuid.UUID(session["id"]), model=model) is False
    assert (await session_row(db, session["id"])).summary is None
    assert model.received == []


async def test_ten_messages_writes_summary(live_chat, db):
    from app.agent.summarizer import maybe_update_summary

    _, session = live_chat
    await add_messages(db, session["id"], 10)
    assert await maybe_update_summary(uuid.UUID(session["id"]), model=scripted([SUMMARY])) is True
    row = await session_row(db, session["id"])
    assert row.summary == SUMMARY
    assert row.summary_updated_at is not None


async def test_counts_only_messages_after_last_summary(live_chat, db):
    from app.agent.summarizer import maybe_update_summary

    _, session = live_chat
    await add_messages(db, session["id"], 10)
    await maybe_update_summary(uuid.UUID(session["id"]), model=scripted([SUMMARY]))
    await add_messages(db, session["id"], 9, start=10)
    later = scripted(["A newer summary."])
    assert await maybe_update_summary(uuid.UUID(session["id"]), model=later) is False
    assert (await session_row(db, session["id"])).summary == SUMMARY
    await add_messages(db, session["id"], 1, start=19)
    assert await maybe_update_summary(uuid.UUID(session["id"]), model=later) is True
    assert (await session_row(db, session["id"])).summary == "A newer summary."


async def test_previous_summary_and_new_messages_are_sent_to_model(live_chat, db):
    from app.agent.summarizer import maybe_update_summary

    _, session = live_chat
    await add_messages(db, session["id"], 10)
    await maybe_update_summary(uuid.UUID(session["id"]), model=scripted([SUMMARY]))
    await add_messages(db, session["id"], 10, start=10)
    model = scripted(["Updated."])
    await maybe_update_summary(uuid.UUID(session["id"]), model=model)
    sent = "\n".join(str(m.content) for m in model.received[0])
    assert SUMMARY in sent
    assert "message 15" in sent
    assert "message 3" not in sent
    assert "50" in sent and "100" in sent


async def test_summary_is_trimmed(live_chat, db):
    from app.agent.summarizer import maybe_update_summary

    _, session = live_chat
    await add_messages(db, session["id"], 10)
    await maybe_update_summary(uuid.UUID(session["id"]), model=scripted([f"\n  {SUMMARY}  \n"]))
    assert (await session_row(db, session["id"])).summary == SUMMARY


async def test_missing_platform_key_returns_false(live_chat, db):
    from app.agent.summarizer import maybe_update_summary

    _, session = live_chat
    await add_messages(db, session["id"], 10)
    assert await maybe_update_summary(uuid.UUID(session["id"])) is False
    assert (await session_row(db, session["id"])).summary is None


@pytest.mark.parametrize("reply", [["x", "y"], [""]])
async def test_model_error_returns_false_and_keeps_old_summary(live_chat, db, reply):
    from app.agent.summarizer import maybe_update_summary

    _, session = live_chat
    await add_messages(db, session["id"], 10)
    await maybe_update_summary(uuid.UUID(session["id"]), model=scripted([SUMMARY]))
    await add_messages(db, session["id"], 10, start=10)
    before = (await session_row(db, session["id"])).summary_updated_at
    failing = scripted(reply, fail_after=0) if reply != [""] else scripted(reply)
    assert await maybe_update_summary(uuid.UUID(session["id"]), model=failing) is False
    row = await session_row(db, session["id"])
    assert row.summary == SUMMARY
    assert row.summary_updated_at == before


async def test_deleted_chat_returns_false(db):
    from app.agent.summarizer import maybe_update_summary

    assert await maybe_update_summary(uuid.uuid4(), model=scripted([SUMMARY])) is False


async def test_reply_triggers_summary_and_next_turn_uses_it(client, user_a, live_chat, use_model, db, monkeypatch):
    """After the tenth message the chat gets a summary, and the model sees it on the next turn."""
    from app.agent import summarizer

    _, session = live_chat
    await add_messages(db, session["id"], 8)
    monkeypatch.setattr(summarizer, "_platform_model", lambda: scripted([SUMMARY]))
    chat_model = scripted(["reply one"], ["reply two"])
    use_model(chat_model)
    await send(client, user_a, session["id"], {"message": "ninth"})
    assert (await session_row(db, session["id"])).summary == SUMMARY
    await send(client, user_a, session["id"], {"message": "next"})
    assert SUMMARY in chat_model.received[1][0].content
