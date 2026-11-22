"""Chat replies reuse a model step whose whole input was seen before; nothing else does."""
from langchain_core.messages import AIMessage, HumanMessage

from tests.fakes import scripted
from tests.test_agents import GEMINI_MODEL
from tests.test_automation_describe import conversation
from tests.test_chat import live_chat, read_events, send, stored, tokens, use_model  # noqa: F401  (fixtures)
from tests.test_sessions import create_session, live_agent
from tests.test_tool_loop import call, enable


async def other_live_agent(client, headers) -> dict:
    agent = await live_agent(client, headers, name="Other Bot")
    await client.patch(f"/agents/{agent['id']}", json={"llm_provider": "gemini", "llm_model": GEMINI_MODEL}, headers=headers)
    return agent


async def test_same_first_message_in_a_new_chat_comes_from_cache(client, user_a, live_chat, use_model, db):
    agent, session = live_chat
    model = scripted(["Hello there"])
    use_model(model)
    first = read_events((await send(client, user_a, session["id"], {"message": "hi"})).text)
    second_chat = await create_session(client, user_a, agent["id"])
    second = read_events((await send(client, user_a, second_chat["id"], {"message": "hi"})).text)
    assert tokens(first) == tokens(second) == "Hello there"
    assert second[-1][0] == "done" and second[-1][1]["message_id"]
    assert (await stored(db, second_chat["id"]))[-1] == ("assistant", "Hello there")
    assert len(model.received) == 1


async def test_a_follow_up_in_the_same_chat_asks_the_model(client, user_a, live_chat, use_model):
    _, session = live_chat
    model = scripted(["Hello there"], ["Hello again"])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "hi"})
    r = await send(client, user_a, session["id"], {"message": "hi"})
    assert tokens(read_events(r.text)) == "Hello again" and len(model.received) == 2


async def test_another_agent_does_not_share_cached_steps(client, user_a, live_chat, use_model):
    _, session = live_chat
    model = scripted(["Mine"], ["Theirs"])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "hi"})
    other = await other_live_agent(client, user_a)
    other_chat = await create_session(client, user_a, other["id"])
    r = await send(client, user_a, other_chat["id"], {"message": "hi"})
    assert tokens(read_events(r.text)) == "Theirs" and len(model.received) == 2


async def test_describe_chat_never_uses_the_cache(client, user_a, live_chat, use_model):
    agent, _ = live_chat
    model = scripted(["What should it do?"], ["What should it do?"])
    use_model(model)
    for _ in range(2):
        conv = await conversation(client, user_a, agent["id"])
        r = await send(client, user_a, conv["id"], {"message": "hi", "timezone": "UTC"})
        assert tokens(read_events(r.text)) == "What should it do?"
    assert len(model.received) == 2


async def test_graph_without_scope_never_caches():
    from app.agent.graph import build_graph

    model = scripted(["One"], ["Two"])
    graph = build_graph(model)
    for _ in range(2):
        await graph.ainvoke({"messages": [HumanMessage(content="hi")]})
    assert len(model.received) == 2


async def test_replayed_tool_calls_get_fresh_ids(client, user_a, live_chat, use_model):
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator")
    model = scripted(call("calculator", expression="6*7"), ["It is 42."])
    use_model(model)
    first = read_events((await send(client, user_a, session["id"], {"message": "6 times 7?"})).text)
    second_chat = await create_session(client, user_a, agent["id"])
    second = read_events((await send(client, user_a, second_chat["id"], {"message": "6 times 7?"})).text)
    starts = [dict(data) for name, data in first + second if name == "tool_start"]
    ends = [data for name, data in second if name == "tool_end"]
    assert len(starts) == 2 and starts[0]["id"] != starts[1]["id"]
    assert ends and ends[0]["ok"] and ends[0]["card"]["result"] == "42"  # the tool still ran
    assert tokens(second) == "It is 42." and len(model.received) == 2


async def test_failed_replies_are_not_cached(client, user_a, live_chat, use_model):
    agent, session = live_chat
    use_model(scripted(["Hel", "lo"], fail_after=1))
    await send(client, user_a, session["id"], {"message": "hi"})
    model = scripted(["Hello"])
    use_model(model)
    second_chat = await create_session(client, user_a, agent["id"])
    r = await send(client, user_a, second_chat["id"], {"message": "hi"})
    assert tokens(read_events(r.text)) == "Hello" and len(model.received) == 1


async def test_a_blank_reply_with_only_a_signature_is_not_cached():
    from langchain_core.outputs import ChatGeneration, ChatResult

    from app.agent.graph import build_graph
    from tests.fakes import ScriptedChatModel

    class SignatureOnly(ScriptedChatModel):  # Gemini's blank text part that carries only a thought signature
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.received.append(list(messages))
            blank = [{"type": "text", "text": "", "extras": {"signature": "sig"}}]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=blank))])

    model = SignatureOnly(replies=[], received=[])
    graph = build_graph(model, cache_scope="agent:gemini:m")
    for _ in range(2):
        await graph.ainvoke({"messages": [HumanMessage(content="hi")]})
    assert len(model.received) == 2


async def test_list_content_round_trips():
    from app.agent.graph import _from_cache, _to_cache
    from app.agent.runner import chunk_text

    reply = AIMessage(content=[{"type": "text", "text": "Hi"}], tool_calls=[{"name": "calculator", "args": {"expression": "1"}, "id": "c1"}])
    back = _from_cache(_to_cache(reply))
    assert chunk_text(back) == "Hi" and back.tool_calls[0]["name"] == "calculator" and back.tool_calls[0]["id"] != "c1"


async def test_step_key_ignores_ids_but_not_content():
    from app.agent.graph import step_key

    a = [HumanMessage(content="hi", id="1"), AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "x"}])]
    b = [HumanMessage(content="hi", id="2"), AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "y"}])]
    c = [HumanMessage(content="hello")]
    assert step_key("s", [], a) == step_key("s", [], b)
    assert step_key("s", [], a) != step_key("s", [], c) and step_key("s", [], a) != step_key("other", [], a)
    assert step_key("s", [], a).startswith("llm:s:")
