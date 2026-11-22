import pytest

from tests.conftest import new_id

GEMINI_MODEL = "gemini-3.8-flash"


async def create_agent(client, headers, name="Support Bot", description="Answers questions") -> dict:
    r = await client.post("/agents", json={"name": name, "description": description}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_agent_is_draft(client, user_a):
    agent = await create_agent(client, user_a)
    assert agent["status"] == "draft"
    assert agent["name"] == "Support Bot"
    assert agent["description"] == "Answers questions"
    assert agent["system_prompt"] == ""
    assert agent["persona_key"] is None
    assert agent["llm_provider"] is None and agent["llm_model"] is None


async def test_description_is_optional(client, user_a):
    r = await client.post("/agents", json={"name": "Bot"}, headers=user_a)
    assert r.status_code == 201
    assert r.json()["description"] == ""


async def test_name_is_trimmed(client, user_a):
    r = await client.post("/agents", json={"name": "  Bot  "}, headers=user_a)
    assert r.json()["name"] == "Bot"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_bad_name_rejected(client, user_a, name):
    r = await client.post("/agents", json={"name": name}, headers=user_a)
    assert r.status_code == 422


async def test_description_over_500_rejected(client, user_a):
    r = await client.post("/agents", json={"name": "Bot", "description": "x" * 501}, headers=user_a)
    assert r.status_code == 422


async def test_prompt_over_20000_rejected(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.patch(f"/agents/{agent['id']}", json={"system_prompt": "x" * 20001}, headers=user_a)
    assert r.status_code == 422


async def test_choose_persona_fills_prompt(client, user_a):
    from app.agent.personas import get_persona

    agent = await create_agent(client, user_a)
    r = await client.patch(f"/agents/{agent['id']}", json={"persona_key": "teacher"}, headers=user_a)
    assert r.status_code == 200
    assert r.json()["persona_key"] == "teacher"
    assert r.json()["system_prompt"] == get_persona("teacher").prompt
    assert r.json()["custom_prompt"] is None


async def test_edit_prompt_keeps_persona(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.patch(
        f"/agents/{agent['id']}", json={"persona_key": "teacher", "system_prompt": "Edited text"}, headers=user_a
    )
    assert r.json()["persona_key"] == "teacher"
    assert r.json()["system_prompt"] == "Edited text"


async def test_custom_prompt_mirrors(client, user_a):
    agent = await create_agent(client, user_a)
    await client.patch(f"/agents/{agent['id']}", json={"persona_key": "teacher"}, headers=user_a)
    r = await client.patch(
        f"/agents/{agent['id']}", json={"persona_key": None, "system_prompt": "My own rules"}, headers=user_a
    )
    assert r.json()["persona_key"] is None
    assert r.json()["system_prompt"] == "My own rules"
    assert r.json()["custom_prompt"] == "My own rules"


async def test_unknown_persona_422(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.patch(f"/agents/{agent['id']}", json={"persona_key": "pirate"}, headers=user_a)
    assert r.status_code == 422


async def test_patch_only_changes_sent_fields(client, user_a):
    agent = await create_agent(client, user_a)
    await client.patch(f"/agents/{agent['id']}", json={"persona_key": "teacher"}, headers=user_a)
    r = await client.patch(f"/agents/{agent['id']}", json={"name": "Renamed"}, headers=user_a)
    assert r.json()["name"] == "Renamed"
    assert r.json()["persona_key"] == "teacher"
    assert r.json()["description"] == "Answers questions"


async def test_set_model(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.patch(
        f"/agents/{agent['id']}", json={"llm_provider": "gemini", "llm_model": GEMINI_MODEL}, headers=user_a
    )
    assert r.status_code == 200
    assert (r.json()["llm_provider"], r.json()["llm_model"]) == ("gemini", GEMINI_MODEL)


@pytest.mark.parametrize(
    "body",
    [
        {"llm_provider": "openai", "llm_model": GEMINI_MODEL},
        {"llm_provider": "claude", "llm_model": "x"},
        {"llm_provider": "gemini"},
        {"llm_model": GEMINI_MODEL},
    ],
)
async def test_model_must_match_provider(client, user_a, body):
    agent = await create_agent(client, user_a)
    r = await client.patch(f"/agents/{agent['id']}", json=body, headers=user_a)
    assert r.status_code == 422


async def test_deploy_needs_prompt(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.post(f"/agents/{agent['id']}/deploy", headers=user_a)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "agent_incomplete"


async def test_deploy_without_model_or_key_allowed(client, user_a):
    agent = await create_agent(client, user_a)
    await client.patch(f"/agents/{agent['id']}", json={"persona_key": "friend"}, headers=user_a)
    r = await client.post(f"/agents/{agent['id']}/deploy", headers=user_a)
    assert r.status_code == 200
    assert r.json()["status"] == "live"


async def test_lifecycle_live_stopped_live(client, user_a):
    agent = await create_agent(client, user_a)
    await client.patch(f"/agents/{agent['id']}", json={"persona_key": "friend"}, headers=user_a)
    assert (await client.post(f"/agents/{agent['id']}/deploy", headers=user_a)).json()["status"] == "live"
    assert (await client.post(f"/agents/{agent['id']}/stop", headers=user_a)).json()["status"] == "stopped"
    assert (await client.post(f"/agents/{agent['id']}/deploy", headers=user_a)).json()["status"] == "live"
    assert (await client.get(f"/agents/{agent['id']}", headers=user_a)).json()["status"] == "live"


async def test_stop_draft_409(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "agent_not_live"


async def test_delete_agent(client, user_a):
    agent = await create_agent(client, user_a)
    assert (await client.delete(f"/agents/{agent['id']}", headers=user_a)).status_code == 204
    assert (await client.get(f"/agents/{agent['id']}", headers=user_a)).status_code == 404


async def test_other_user_gets_404(client, user_a, user_b):
    agent = await create_agent(client, user_a)
    await client.patch(f"/agents/{agent['id']}", json={"persona_key": "friend"}, headers=user_a)
    url = f"/agents/{agent['id']}"
    responses = [
        await client.get(url, headers=user_b),
        await client.patch(url, json={"name": "Stolen"}, headers=user_b),
        await client.delete(url, headers=user_b),
        await client.post(f"{url}/deploy", headers=user_b),
        await client.post(f"{url}/stop", headers=user_b),
    ]
    assert [r.status_code for r in responses] == [404] * 5
    assert all(r.json()["detail"]["code"] == "not_found" for r in responses)
    assert (await client.get(url, headers=user_a)).json()["name"] == "Support Bot"


async def test_missing_agent_404(client, user_a):
    assert (await client.get(f"/agents/{new_id()}", headers=user_a)).status_code == 404


async def test_list_only_own_agents_newest_first(client, user_a, user_b):
    await create_agent(client, user_a, name="First")
    await create_agent(client, user_a, name="Second")
    await create_agent(client, user_b, name="Other")
    names = [a["name"] for a in (await client.get("/agents", headers=user_a)).json()]
    assert names == ["Second", "First"]


async def test_personas_has_twelve_with_prompts(client, user_a):
    r = await client.get("/personas", headers=user_a)
    assert r.status_code == 200
    personas = r.json()
    assert [p["key"] for p in personas] == [
        "customer_care", "developer", "tester", "friend", "store_owner", "teacher",
        "doctor", "career_guidance", "writer", "research_assistant", "sales_assistant", "personal_coach",
    ]
    for p in personas:
        assert p["name"] and p["description"]
        assert 80 <= len(p["prompt"].split()) <= 150, p["key"]


def test_doctor_persona_sends_people_to_a_real_doctor():
    from app.agent.personas import get_persona

    prompt = get_persona("doctor").prompt.lower()
    assert "general health information" in prompt
    assert "not a substitute" in prompt
    assert "emergenc" in prompt
