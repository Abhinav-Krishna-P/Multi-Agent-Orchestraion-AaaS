import uuid

from sqlalchemy import func, select

from tests.conftest import new_id
from tests.test_agents import create_agent


async def live_agent(client, headers, name="Support Bot") -> dict:
    agent = await create_agent(client, headers, name=name)
    await client.patch(f"/agents/{agent['id']}", json={"persona_key": "friend"}, headers=headers)
    r = await client.post(f"/agents/{agent['id']}/deploy", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def create_session(client, headers, agent_id: str) -> dict:
    r = await client.post(f"/agents/{agent_id}/sessions", headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def add_message(db, session_id: str, role: str, content: str):
    from app.db.models import Message

    db.add(Message(session_id=uuid.UUID(session_id), role=role, content=content))
    await db.commit()


async def test_create_session_on_live_agent(client, user_a):
    agent = await live_agent(client, user_a)
    session = await create_session(client, user_a, agent["id"])
    assert session["title"] == "New chat"
    assert session["agent_id"] == agent["id"]
    assert session["summary"] is None


async def test_create_session_on_draft_409(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.post(f"/agents/{agent['id']}/sessions", headers=user_a)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "agent_not_live"


async def test_create_session_on_stopped_409(client, user_a):
    agent = await live_agent(client, user_a)
    await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    r = await client.post(f"/agents/{agent['id']}/sessions", headers=user_a)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "agent_not_live"


async def test_sessions_newest_activity_first(client, user_a, db):
    from app.db.models import ChatSession

    agent = await live_agent(client, user_a)
    first = await create_session(client, user_a, agent["id"])
    second = await create_session(client, user_a, agent["id"])
    row = await db.get(ChatSession, uuid.UUID(first["id"]))
    row.last_message_at = func.now() + func.make_interval(0, 0, 0, 0, 1)
    await db.commit()
    listed = (await client.get(f"/agents/{agent['id']}/sessions", headers=user_a)).json()
    assert [s["id"] for s in listed] == [first["id"], second["id"]]


async def test_sessions_of_stopped_agent_stay_readable(client, user_a, db):
    agent = await live_agent(client, user_a)
    session = await create_session(client, user_a, agent["id"])
    await add_message(db, session["id"], "user", "Hi")
    await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    assert len((await client.get(f"/agents/{agent['id']}/sessions", headers=user_a)).json()) == 1
    messages = (await client.get(f"/sessions/{session['id']}/messages", headers=user_a)).json()
    assert [m["content"] for m in messages] == ["Hi"]


async def test_session_detail_includes_agent_status(client, user_a):
    agent = await live_agent(client, user_a)
    session = await create_session(client, user_a, agent["id"])
    r = await client.get(f"/sessions/{session['id']}", headers=user_a)
    assert r.status_code == 200
    assert r.json()["id"] == session["id"]
    assert r.json()["agent"] == {
        "id": agent["id"], "name": "Support Bot", "status": "live", "llm_provider": None, "llm_model": None,
    }


async def test_messages_oldest_first(client, user_a, db):
    agent = await live_agent(client, user_a)
    session = await create_session(client, user_a, agent["id"])
    await add_message(db, session["id"], "user", "one")
    await add_message(db, session["id"], "assistant", "two")
    await add_message(db, session["id"], "user", "three")
    messages = (await client.get(f"/sessions/{session['id']}/messages", headers=user_a)).json()
    assert [(m["role"], m["content"]) for m in messages] == [("user", "one"), ("assistant", "two"), ("user", "three")]
    assert set(messages[0]) == {"id", "role", "content", "created_at", "tools", "sources", "form", "approval"}


async def test_delete_session_removes_messages(client, user_a, db):
    from app.db.models import Message

    agent = await live_agent(client, user_a)
    session = await create_session(client, user_a, agent["id"])
    await add_message(db, session["id"], "user", "one")
    assert (await client.delete(f"/sessions/{session['id']}", headers=user_a)).status_code == 204
    assert (await client.get(f"/sessions/{session['id']}", headers=user_a)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Message)) == 0


async def test_delete_agent_removes_sessions_and_messages(client, user_a, db):
    from app.db.models import ChatSession, Message

    agent = await live_agent(client, user_a)
    session = await create_session(client, user_a, agent["id"])
    await add_message(db, session["id"], "user", "one")
    assert (await client.delete(f"/agents/{agent['id']}", headers=user_a)).status_code == 204
    assert await db.scalar(select(func.count()).select_from(ChatSession)) == 0
    assert await db.scalar(select(func.count()).select_from(Message)) == 0
    assert (await client.get(f"/sessions/{session['id']}/messages", headers=user_a)).status_code == 404


async def test_other_user_gets_404(client, user_a, user_b, db):
    agent = await live_agent(client, user_a)
    session = await create_session(client, user_a, agent["id"])
    await add_message(db, session["id"], "user", "private")
    responses = [
        await client.get(f"/agents/{agent['id']}/sessions", headers=user_b),
        await client.post(f"/agents/{agent['id']}/sessions", headers=user_b),
        await client.get(f"/sessions/{session['id']}", headers=user_b),
        await client.get(f"/sessions/{session['id']}/messages", headers=user_b),
        await client.delete(f"/sessions/{session['id']}", headers=user_b),
    ]
    assert [r.status_code for r in responses] == [404] * 5
    assert all("private" not in r.text for r in responses)
    assert (await client.get(f"/sessions/{session['id']}", headers=user_a)).status_code == 200


async def test_missing_session_404(client, user_a):
    assert (await client.get(f"/sessions/{new_id()}", headers=user_a)).status_code == 404
