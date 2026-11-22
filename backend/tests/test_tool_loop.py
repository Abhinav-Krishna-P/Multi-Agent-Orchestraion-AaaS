import uuid

import pytest
from langchain_core.messages import SystemMessage, ToolMessage

from tests.fakes import scripted
from tests.test_chat import live_chat, read_events, send, stored, tokens, use_model  # noqa: F401  (fixtures)


def call(tool: str, **args) -> dict:
    return {"tool": tool, "args": args}


async def enable(client, headers, agent, *tools):
    r = await client.put(f"/agents/{agent['id']}/tools", json={"tools": list(tools)}, headers=headers)
    assert r.status_code == 200, r.text


async def saved_rows(db, session_id: str):
    from sqlalchemy import select

    from app.db.models import Message

    rows = await db.scalars(
        select(Message).where(Message.session_id == uuid.UUID(session_id)).order_by(Message.created_at)
    )
    return rows.all()


async def test_tool_runs_and_answer_streams(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    model = scripted(call("calculator", expression="6*7"), ["It is ", "42."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "What is 6 times 7?"})
    events = read_events(r.text)
    names = [name for name, _ in events]
    assert names == ["tool_start", "tool_end", "token", "token", "done"]
    start, end = events[0][1], events[1][1]
    assert start["label"] == "Calculating…"
    assert end == {"id": start["id"], "ok": True, "card": {"kind": "calculation", "service": "Calculator", "expression": "6*7", "result": "42"}}
    assert tokens(events) == "It is 42."
    assert model.bound == ["calculator"]
    tool_result = model.received[1][-1]
    assert isinstance(tool_result, ToolMessage) and tool_result.content == "42"
    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.content == "It is 42."
    assert assistant.tool_calls == [{"label": "Calculating…", "ok": True, "card": {"kind": "calculation", "service": "Calculator", "expression": "6*7", "result": "42"}}]
    assert not assistant.sources


async def test_messages_endpoint_returns_tools_and_sources(client, user_a, live_chat, use_model):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    use_model(scripted(call("calculator", expression="1+1"), ["Two."]))
    await send(client, user_a, session["id"], {"message": "1+1?"})
    user_row, assistant_row = (await client.get(f"/sessions/{session['id']}/messages", headers=user_a)).json()
    assert user_row["tools"] == [] and user_row["sources"] == []
    assert assistant_row["tools"] == [{"label": "Calculating…", "ok": True, "card": {"kind": "calculation", "service": "Calculator", "expression": "1+1", "result": "2"}}]
    assert assistant_row["sources"] == []


async def test_only_enabled_tools_are_offered(client, user_a, live_chat, use_model):
    agent, session = live_chat
    await enable(client, user_a, agent, "get_current_datetime")
    model = scripted(["Hello."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    assert model.bound == ["get_current_datetime"]


async def test_no_tools_behaves_like_stage_1(client, user_a, live_chat, use_model):
    _, session = live_chat
    model = scripted(["Hello."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "Hi"})
    assert [name for name, _ in read_events(r.text)] == ["token", "done"]
    assert model.bound is None


async def test_unknown_tool_call_gets_error_and_reply_finishes(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    model = scripted(call("launch_rocket", target="moon"), ["I can't do that."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "Launch"})
    events = read_events(r.text)
    assert [name for name, _ in events] == ["tool_start", "tool_end", "token", "done"]
    assert events[1][1]["ok"] is False
    assert (await saved_rows(db, session["id"]))[-1].content == "I can't do that."


async def test_bad_arguments_get_error_and_reply_finishes(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    model = scripted(call("calculator", wrong_name="2+2"), ["Sorry, something went wrong."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "2+2?"})
    events = read_events(r.text)
    assert events[1] == ("tool_end", {"id": events[0][1]["id"], "ok": False})
    assert events[-1][0] == "done" and events[-1][1]["message_id"]
    error_seen_by_model = model.received[1][-1]
    assert isinstance(error_seen_by_model, ToolMessage) and error_seen_by_model.status == "error"


async def test_endless_tool_calls_end_as_model_error(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    use_model(scripted(*[call("calculator", expression="1+1")] * 8))
    r = await send(client, user_a, session["id"], {"message": "Loop"})
    events = read_events(r.text)
    assert [name for name, _ in events[-2:]] == ["error", "done"]
    assert events[-2][1]["code"] == "model_error"
    assert [name for name, _ in events].count("tool_start") == 6
    assert [m.role for m in await saved_rows(db, session["id"])] == ["user"]


async def test_six_tool_rounds_are_allowed(client, user_a, live_chat, use_model):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    use_model(scripted(*[call("calculator", expression="1+1")] * 6, ["Done."]))
    r = await send(client, user_a, session["id"], {"message": "Six"})
    assert read_events(r.text)[-1][1]["message_id"]


async def test_text_before_a_tool_call_is_kept(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    use_model(scripted(["Let me work that out. ", {"tool": "calculator", "args": {"expression": "2+2"}}], ["It is 4."]))
    r = await send(client, user_a, session["id"], {"message": "2+2?"})
    assert tokens(read_events(r.text)) == "Let me work that out. It is 4."
    assert (await saved_rows(db, session["id"]))[-1].content == "Let me work that out. It is 4."


def test_extra_instruction_is_appended_to_system_prompt():
    from types import SimpleNamespace

    from app.agent.context import build_messages

    rows = [SimpleNamespace(role="user", content="Hi")]
    out = build_messages("You are helpful.", "S", rows, extra_instruction="Only use the documents.")
    assert isinstance(out[0], SystemMessage)
    assert out[0].content == (
        "You are helpful.\n\nSummary of the conversation so far:\nS\n\nOnly use the documents."
    )
    assert build_messages("P", None, rows)[0].content == "P"


async def test_stop_mid_tool_turn_saves_partial_text_and_tools(live_chat, db):
    import asyncio

    from app.agent import runner
    from app.db.models import Message
    from app.tools.registry import REGISTRY

    _, session = live_chat
    session_id = uuid.UUID(session["id"])
    db.add(Message(session_id=session_id, role="user", content="Hi"))
    await db.commit()
    gate = asyncio.Event()
    model = scripted(call("calculator", expression="2+2"), ["Partial", " never sent"], gate=gate)
    turn = runner.run_turn(
        session_id=session_id, system_prompt="P", summary=None, model=model,
        tools=[REGISTRY["calculator"].tool], labels={"calculator": "Calculating…"},
    )
    seen = []
    async for event in turn:
        seen.append(read_events(event)[0])
        if seen[-1][0] == "token":
            break
    await turn.aclose()
    await runner.wait_for_background()
    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.role == "assistant" and assistant.content == "Partial"
    assert assistant.tool_calls == [{"label": "Calculating…", "ok": True, "card": {"kind": "calculation", "service": "Calculator", "expression": "2+2", "result": "4"}}]
