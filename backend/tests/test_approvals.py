"""Actions that change things: the agent asks, the user approves or rejects, then it runs (or not)."""
from tests.conftest import USER_A_ID
from tests.fakes import scripted
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_chat import live_chat, read_events, send, use_model  # noqa: F401  (fixtures)
from tests.test_integration_api import connect
from tests.test_integrations import composio  # noqa: F401  (fixture)
from tests.test_tool_loop import call, saved_rows

EMAIL = {"recipient_email": "me@example.com", "subject": "Hi", "body": "Hello from the agent"}


async def switch_on(client, headers, agent_id: str, *actions: str) -> None:
    await connect(client, headers, agent_id)
    r = await client.put(f"/agents/{agent_id}/integrations/gmail/actions", json={"actions": list(actions)}, headers=headers)
    assert r.status_code == 200, r.text


def executed(composio, slug: str = "GMAIL_SEND_EMAIL") -> list[dict]:
    return composio.made("POST", f"/tools/execute/{slug}")


# --- asking ----------------------------------------------------------------------------------


async def test_a_write_action_asks_instead_of_running(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, session = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL")
    model = scripted(call("gmail_send_email", **EMAIL))
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "Email me a hello"})
    events = read_events(r.text)
    assert [name for name, _ in events] == ["tool_start", "tool_end", "token", "approval_required", "done"]
    assert executed(composio) == []  # nothing ran
    assert len(model.received) == 1  # the reply ended at the request: the model was not asked again
    approval = (await saved_rows(db, session["id"]))[-1].approval
    assert approval == {
        "app": "gmail", "app_name": "Gmail", "logo": "https://logos.composio.dev/api/gmail",
        "action": "GMAIL_SEND_EMAIL", "action_name": "Gmail Send Email", "arguments": EMAIL,
        "labels": {"recipient_email": "Recipient Email", "subject": "Subject", "body": "body"},
        "order": ["recipient_email", "subject", "body"], "status": "pending",
    }
    assert events[3][1] == {"approval": approval}
    saved = (await client.get(f"/sessions/{session['id']}/messages", headers=user_a)).json()[-1]
    assert saved["content"] == "This needs your approval before I do it." and saved["approval"] == approval


async def test_a_read_next_to_a_write_runs_and_the_write_waits(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, session = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS", "GMAIL_SEND_EMAIL")
    use_model(scripted([{"tool": "gmail_fetch_emails", "args": {"query": "x"}}, {"tool": "gmail_send_email", "args": EMAIL}]))
    await send(client, user_a, session["id"], {"message": "Read then email"})
    assert len(executed(composio, "GMAIL_FETCH_EMAILS")) == 1 and executed(composio) == []
    assert (await saved_rows(db, session["id"]))[-1].approval["status"] == "pending"


async def test_two_writes_in_one_reply_keep_only_the_first(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, session = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL")
    second = {**EMAIL, "subject": "Second"}
    use_model(scripted([{"tool": "gmail_send_email", "args": EMAIL}, {"tool": "gmail_send_email", "args": second}]))
    await send(client, user_a, session["id"], {"message": "Two emails"})
    assert (await saved_rows(db, session["id"]))[-1].approval["arguments"] == EMAIL
    assert executed(composio) == []


async def test_the_instruction_comes_with_write_actions(client, user_a, live_chat, use_model, composio):  # noqa: F811
    from app.tools.registry import APPROVAL_INSTRUCTION

    agent, session = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS")
    model = scripted(["Hi."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    assert APPROVAL_INSTRUCTION not in model.received[0][0].content
    await client.put(f"/agents/{agent['id']}/integrations/gmail/actions", json={"actions": ["GMAIL_SEND_EMAIL"]}, headers=user_a)
    model = scripted(["Hi."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi again"})
    assert APPROVAL_INSTRUCTION in model.received[0][0].content


async def test_the_users_own_id_is_never_in_an_approval(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, session = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL")
    use_model(scripted(call("gmail_send_email", **EMAIL)))
    await send(client, user_a, session["id"], {"message": "Email me"})
    approval = (await saved_rows(db, session["id"]))[-1].approval
    assert "ca_1" not in str(approval) and USER_A_ID not in str(approval)  # the browser sees this record
