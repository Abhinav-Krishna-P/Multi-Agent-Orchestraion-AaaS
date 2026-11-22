"""Approvals: cases found by the final review."""
import httpx
import pytest

from tests.fakes import scripted
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approval_decisions import asked, decide
from tests.test_approvals import executed
from tests.test_chat import live_chat, read_events, send, use_model  # noqa: F401  (fixtures)
from tests.test_integrations import HOST, composio  # noqa: F401  (fixture)
from tests.test_tool_loop import saved_rows


async def test_no_answer_from_the_app_is_not_called_a_failure(client, user_a, live_chat, use_model, composio, web, db):  # noqa: F811
    agent, session = live_chat
    message_id = await asked(client, user_a, agent, session, use_model)

    def slow_send(request):
        if "/tools/execute/" in request.url.path:
            raise httpx.ReadTimeout("slow")  # Gmail may well have sent it
        return composio(request)

    web.replies[HOST] = slow_send
    model = scripted(["Please check."])
    use_model(model)
    r = await decide(client, user_a, session, message_id, "approve")
    assert read_events(r.text)[-1][0] == "done"
    approval = (await saved_rows(db, session["id"]))[1].approval
    assert approval["outcome"] == "unknown" and "Check Gmail before trying again" in approval["reason"]
    assert "the platform does not know whether it was done" in model.received[0][0].content


async def test_an_unexpected_reply_still_records_an_outcome(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, session = live_chat
    message_id = await asked(client, user_a, agent, session, use_model)
    composio.result = ["not", "what", "we", "expect"]
    use_model(scripted(["Hmm."]))
    r = await decide(client, user_a, session, message_id, "approve")
    assert r.status_code == 200 and read_events(r.text)[-1][0] == "done"
    rows = await saved_rows(db, session["id"])
    assert rows[1].approval["outcome"] == "unknown" and rows[2].content.startswith("Approved:")


async def test_a_crash_after_the_claim_leaves_a_retryable_chat(client, user_a, live_chat, use_model, composio, db, monkeypatch):  # noqa: F811
    from app.api import chat

    agent, session = live_chat
    message_id = await asked(client, user_a, agent, session, use_model)

    async def crash(*args, **kwargs):
        raise RuntimeError("process died")

    monkeypatch.setattr(chat, "_run_approved", crash)
    with pytest.raises(RuntimeError):
        await decide(client, user_a, session, message_id, "approve")
    rows = await saved_rows(db, session["id"])
    # The answer was saved with the claim: the chat ends with the user's message, so Retry is offered.
    assert rows[-1].role == "user" and rows[-1].content.startswith("Approved:")
    assert rows[1].approval["status"] == "approved" and "outcome" not in rows[1].approval
    monkeypatch.undo()
    model = scripted(["Let me know if it arrived."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"retry": True})
    assert read_events(r.text)[-1][0] == "done"
    assert "the platform has no record of whether it was done" in model.received[0][0].content
    assert executed(composio) == []


async def test_the_claim_itself_refuses_a_second_answer(client, user_a, live_chat, use_model, composio, db, monkeypatch):  # noqa: F811
    from sqlalchemy import update

    from app.api import chat
    from app.db.models import Message

    agent, session = live_chat
    message_id = await asked(client, user_a, agent, session, use_model)
    stale = await chat._newest(db, session["id"])  # read while still pending, as a racing request would
    stale_approval = dict(stale.approval)
    await db.execute(update(Message).where(Message.id == stale.id).values(approval={**stale_approval, "status": "approved"}))
    await db.commit()

    class Stale:
        id, role, approval = stale.id, "assistant", stale_approval

    async def newest(*args):
        return Stale

    monkeypatch.setattr(chat, "_newest", newest)
    r = await decide(client, user_a, session, message_id, "approve")
    assert r.status_code == 409 and executed(composio) == []


async def test_the_model_sees_the_details_it_proposed(client, user_a, live_chat, use_model, composio):  # noqa: F811
    agent, session = live_chat
    message_id = await asked(client, user_a, agent, session, use_model)
    model = scripted(["Okay."])
    use_model(model)
    await decide(client, user_a, session, message_id, "reject")
    note = model.received[0][0].content
    assert "Details you proposed: Recipient Email: me@example.com, Subject: Hi, body: Hello from the agent." in note
