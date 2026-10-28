import pytest

from tests.test_agents import create_agent


def calc(expression: str) -> str:
    from app.tools.builtin import calculator

    return calculator.invoke({"expression": expression})


@pytest.mark.parametrize(
    "expression, result",
    [
        ("2+2", "4"),
        ("(3+4)*2", "14"),
        ("2**10", "1024"),
        ("sqrt(16)", "4.0"),
        ("7/2", "3.5"),
        ("-3+1", "-2"),
        ("10 % 3", "1"),
        ("7 // 2", "3"),
        ("round(3.14159, 2)", "3.14"),
        ("max(2, 9) - min(2, 9)", "7"),
        ("1234 * 5678", "7006652"),
    ],
)
def test_calculator(expression, result):
    assert calc(expression) == result


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "open('secret.txt')",
        "a + 1",
        "2 +",
        "'a' * 3",
        "",
        "(1).__class__",
        "[1, 2][0]",
        "lambda: 1",
        "sqrt",
        "1 if 2 else 3",
    ],
)
def test_calculator_refuses_non_arithmetic(expression):
    assert calc(expression) == "I can only do arithmetic."


def test_calculator_divide_by_zero():
    assert calc("1/0") == "That divides by zero."


@pytest.mark.parametrize("expression", ["10**999 * 10**999", "9**9**9", "2.0**5000"])
def test_calculator_refuses_huge_results(expression):
    assert calc(expression) == "That number is too large for me to work out."


def test_datetime_known_zone():
    from app.tools.builtin import get_current_datetime

    out = get_current_datetime.invoke({"timezone": "Asia/Kolkata"})
    assert "Asia/Kolkata" in out and "+05:30" in out
    assert any(day in out for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])


def test_datetime_defaults_to_utc():
    from app.tools.builtin import get_current_datetime

    assert "UTC" in get_current_datetime.invoke({})


def test_datetime_unknown_zone():
    from app.tools.builtin import get_current_datetime

    assert get_current_datetime.invoke({"timezone": "Mars/Olympus"}) == "I don't know the time zone 'Mars/Olympus'."


def test_registry_entries_are_complete():
    from app.tools.registry import REGISTRY

    assert {"calculator", "get_current_datetime"} <= set(REGISTRY)
    for name, spec in REGISTRY.items():
        assert spec.name == name == spec.tool.name
        assert spec.label and spec.description and spec.group and spec.activity
        assert spec.access in ("read", "write")


async def test_catalog_lists_basics(client, user_a):
    r = await client.get("/tools", headers=user_a)
    assert r.status_code == 200
    groups = r.json()["groups"]
    basics = next(g for g in groups if g["name"] == "Basics")
    assert [t["name"] for t in basics["tools"]] == ["calculator", "get_current_datetime"]
    assert basics["tools"][0] == {
        "name": "calculator",
        "label": "Calculator",
        "description": "Works out arithmetic exactly.",
        "app": "Calculator",
    }


async def test_catalog_needs_sign_in(client):
    assert (await client.get("/tools")).status_code == 401


async def test_agent_shows_kb_fields(client, user_a):
    agent = await create_agent(client, user_a)
    assert agent["kb_enabled"] is False
    assert agent["search_mode"] == "hybrid"
    assert agent["tools"] == []


async def test_set_tools(client, user_a):
    agent = await create_agent(client, user_a)
    url = f"/agents/{agent['id']}/tools"
    r = await client.put(url, json={"tools": ["get_current_datetime", "calculator"]}, headers=user_a)
    assert r.status_code == 200
    assert r.json()["tools"] == ["calculator", "get_current_datetime"]
    assert (await client.get(f"/agents/{agent['id']}", headers=user_a)).json()["tools"] == [
        "calculator", "get_current_datetime",
    ]
    r = await client.put(url, json={"tools": ["calculator", "calculator"]}, headers=user_a)
    assert r.json()["tools"] == ["calculator"]
    assert (await client.put(url, json={"tools": []}, headers=user_a)).json()["tools"] == []


async def test_unknown_tool_422(client, user_a):
    agent = await create_agent(client, user_a)
    url = f"/agents/{agent['id']}/tools"
    await client.put(url, json={"tools": ["calculator"]}, headers=user_a)
    r = await client.put(url, json={"tools": ["calculator", "launch_rocket"]}, headers=user_a)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_tools"
    assert (await client.get(f"/agents/{agent['id']}", headers=user_a)).json()["tools"] == ["calculator"]


async def test_tools_other_user_404(client, user_a, user_b):
    agent = await create_agent(client, user_a)
    r = await client.put(f"/agents/{agent['id']}/tools", json={"tools": ["calculator"]}, headers=user_b)
    assert r.status_code == 404
    assert (await client.get(f"/agents/{agent['id']}", headers=user_a)).json()["tools"] == []


async def test_agent_list_includes_tools(client, user_a):
    agent = await create_agent(client, user_a)
    await client.put(f"/agents/{agent['id']}/tools", json={"tools": ["calculator"]}, headers=user_a)
    assert (await client.get("/agents", headers=user_a)).json()[0]["tools"] == ["calculator"]


async def test_patch_kb_fields(client, user_a):
    agent = await create_agent(client, user_a)
    r = await client.patch(
        f"/agents/{agent['id']}", json={"kb_enabled": True, "search_mode": "keyword"}, headers=user_a
    )
    assert r.status_code == 200
    assert r.json()["kb_enabled"] is True and r.json()["search_mode"] == "keyword"
    r = await client.patch(f"/agents/{agent['id']}", json={"search_mode": "fuzzy"}, headers=user_a)
    assert r.status_code == 422
    r = await client.patch(f"/agents/{agent['id']}", json={"name": "Renamed"}, headers=user_a)
    assert r.json()["kb_enabled"] is True and r.json()["search_mode"] == "keyword"
