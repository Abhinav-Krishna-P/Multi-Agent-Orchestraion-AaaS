"""The details dialog: the agent asks for filters through a form, and results offer a refine."""
import httpx

from tests.fakes import scripted
from tests.test_api_tools import _stays, web  # noqa: F401  (fixture)
from tests.test_chat import live_chat, read_events, send, tokens, use_model  # noqa: F401  (fixtures)
from tests.test_documents import paste, rag  # noqa: F401  (fixtures)
from tests.test_tool_loop import call, enable, saved_rows

DEFAULT_TEXT = "A few details will help me find the right results."


def ask(target: str, known: dict | None = None) -> dict:
    """A scripted model turn that calls ask_for_details."""
    return {"tool": "ask_for_details", "args": {"tool": target, **({"known": known} if known is not None else {})}}


async def test_asking_for_details_ends_the_turn_and_saves_the_form(client, user_a, live_chat, use_model, db):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays")
    model = scripted(ask("search_stays", {"location": "Goa", "guests": 2, "bogus": "x", "check_in": ""}))
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "Find me a place to stay in Goa next month"})
    events = read_events(r.text)
    assert [name for name, _ in events] == ["tool_start", "tool_end", "token", "done"]
    assert events[0][1]["label"] == "Asking for details…" and events[1][1]["ok"] is True
    assert tokens(events) == DEFAULT_TEXT
    assert len(model.received) == 1  # the model was not called again: the turn waits for the user

    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.content == DEFAULT_TEXT
    form = assistant.form
    assert form["kind"] == "ask" and form["tool"] == "search_stays" and form["title"] == "Stays search (Airbnb)"
    assert form["values"] == {"location": "Goa", "guests": 2}  # unknown and empty values are dropped
    assert [field["name"] for field in form["fields"]] == ["location", "check_in", "check_out", "guests", "room_type", "min_price", "max_price"]
    assert form["fields"][0] == {"name": "location", "label": "Where", "type": "text", "options": [], "required": True}
    assert form["fields"][4]["options"][1] == {"value": "entire_home", "label": "Entire home"}

    returned = (await client.get(f"/sessions/{session['id']}/messages", headers=user_a)).json()
    assert returned[0]["form"] is None and returned[1]["form"] == form


async def test_the_models_own_words_are_kept_when_it_asks(client, user_a, live_chat, use_model, db):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays")
    use_model(scripted(["Sure. When are you travelling?", ask("search_stays", {"location": "Goa"})]))
    await send(client, user_a, session["id"], {"message": "A stay in Goa please"})
    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.content == "Sure. When are you travelling?" and assistant.form["kind"] == "ask"


async def test_asking_about_a_tool_without_a_form_gets_an_error_and_continues(client, user_a, live_chat, use_model, db):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays", "calculator")
    model = scripted(ask("calculator"), ["What would you like to calculate?"])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "hmm"})
    events = read_events(r.text)
    assert events[1][1]["ok"] is False
    assert "no details form" in model.received[1][-1].content and "search_stays" in model.received[1][-1].content
    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.content == "What would you like to calculate?" and assistant.form is None


async def test_a_filtered_search_offers_a_refine_with_the_values_used(client, user_a, live_chat, use_model, db, web):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays")
    web.replies["serpapi.com"] = _stays
    use_model(scripted(call("search_stays", location="Goa", guests=2), ["Here are five stays in Goa."]))
    r = await send(client, user_a, session["id"], {"message": "rooms in Goa for two"})
    assert [name for name, _ in read_events(r.text)] == ["tool_start", "tool_end", "token", "done"]
    form = (await saved_rows(db, session["id"]))[-1].form
    assert form["kind"] == "refine" and form["tool"] == "search_stays"
    assert form["values"] == {"location": "Goa", "guests": 2}


async def test_no_form_when_the_search_failed_or_the_tool_has_none(client, user_a, live_chat, use_model, db, web):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays", "calculator")
    web.replies["serpapi.com"] = httpx.Response(500, text="down")
    use_model(scripted(call("search_stays", location="Goa"), ["I couldn't search right now."], call("calculator", expression="1+1"), ["Two."]))
    await send(client, user_a, session["id"], {"message": "rooms in Goa"})
    assert (await saved_rows(db, session["id"]))[-1].form is None
    await send(client, user_a, session["id"], {"message": "1+1?"})
    assert (await saved_rows(db, session["id"]))[-1].form is None


async def test_ask_tool_and_instruction_only_when_a_form_tool_is_on(client, user_a, live_chat, use_model):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "calculator", "web_search")
    model = scripted(["Hello."], ["Hello again."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    assert model.bound == ["calculator", "web_search"]
    assert "ask_for_details" not in model.received[0][0].content
    await enable(client, user_a, agent, "calculator", "search_news")
    await send(client, user_a, session["id"], {"message": "Hi again"})
    assert model.bound == ["calculator", "search_news", "ask_for_details"]
    system = model.received[1][0].content
    assert "ask_for_details" in system and "News search" in system


async def test_details_and_knowledge_base_instructions_sit_together(client, user_a, live_chat, use_model, rag):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays")
    await client.patch(f"/agents/{agent['id']}", json={"kb_enabled": True}, headers=user_a)
    await paste(client, user_a, agent["id"])
    model = scripted(["Hello."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    system = model.received[0][0].content
    assert "ask_for_details" in system and "Answer only from what your tools return" in system
    assert "your other tools" in system  # a documents-only agent may still answer from its other tools
    assert set(model.bound) == {"search_stays", "ask_for_details", "search_knowledge_base", "read_document"}


def test_form_values_are_kept_only_when_they_fit_their_field():
    """The model fills `known` freely; the card can only show values of the right kind."""
    from app.tools.forms import form_spec
    from app.tools.registry import REGISTRY

    known = {
        "location": "Goa", "check_in": "next month", "check_out": "2026-12-20", "guests": "two",
        "room_type": "castle", "min_price": "2000", "max_price": {"amount": 5000},
    }
    assert form_spec(REGISTRY["search_stays"], known, "ask")["values"] == {
        "location": "Goa", "check_out": "2026-12-20", "min_price": 2000,
    }
    known = {"location": ["Goa"], "guests": 2.0, "room_type": "entire_home", "check_in": "2026-13-45", "min_price": -3}
    assert form_spec(REGISTRY["search_stays"], known, "ask")["values"] == {"guests": 2, "room_type": "entire_home"}
    assert form_spec(REGISTRY["search_stays"], {"location": "x" * 201}, "ask")["values"] == {}


async def test_asking_after_the_search_already_ran_is_refused_so_results_are_shown(client, user_a, live_chat, use_model, db, web):  # noqa: F811
    """Found in the browser: the model searched, then opened the dialog in the same reply,
    which threw the results away. Once a search has run, its results must reach the user."""
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays", "search_news")
    web.replies["serpapi.com"] = _stays
    model = scripted(call("search_stays", location="Goa"), ask("search_stays", {"location": "Goa"}), ["Here are stays in Goa."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "rooms in Goa"})
    events = read_events(r.text)
    assert [(name, data.get("ok")) for name, data in events if name == "tool_end"] == [("tool_end", True), ("tool_end", False)]
    refusal = model.received[2][-1].content
    assert "already searched" in refusal and "Refine" in refusal
    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.content == "Here are stays in Goa."
    assert assistant.form["kind"] == "refine" and assistant.form["values"] == {"location": "Goa"}


async def test_asking_about_a_different_tool_after_a_search_is_still_allowed(client, user_a, live_chat, use_model, db, web):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays", "search_news")
    web.replies["serpapi.com"] = _stays
    use_model(scripted(call("search_stays", location="Goa"), ask("search_news", {"query": "Goa"})))
    await send(client, user_a, session["id"], {"message": "rooms in Goa and some news"})
    assistant = (await saved_rows(db, session["id"]))[-1]
    assert assistant.form["kind"] == "ask" and assistant.form["tool"] == "search_news"
