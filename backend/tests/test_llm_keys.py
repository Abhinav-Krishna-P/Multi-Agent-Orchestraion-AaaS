import pytest
from sqlalchemy import select

SECRET = "AIza-secret-9xyz"


@pytest.fixture
def valid_keys(app):
    from app.agent.llm import get_key_validator

    async def _always_valid(provider: str, api_key: str) -> bool:
        return True

    app.dependency_overrides[get_key_validator] = lambda: _always_valid


@pytest.fixture
def invalid_keys(app):
    from app.agent.llm import get_key_validator

    async def _never_valid(provider: str, api_key: str) -> bool:
        return False

    app.dependency_overrides[get_key_validator] = lambda: _never_valid


async def _stored_keys(db):
    from app.db.models import LlmKey

    return (await db.scalars(select(LlmKey))).all()


def test_encrypt_round_trip():
    from app.core.encryption import decrypt_key, encrypt_key

    token = encrypt_key("sk-abc1234")
    assert token != "sk-abc1234"
    assert "sk-abc1234" not in token
    assert decrypt_key(token) == "sk-abc1234"


def test_key_hint_is_last_four():
    from app.core.encryption import key_hint

    assert key_hint("sk-abc1234") == "1234"


async def test_save_key_returns_hint_only(client, user_a, valid_keys):
    r = await client.put("/llm-keys/gemini", json={"api_key": SECRET}, headers=user_a)
    assert r.status_code == 200
    assert r.json()["provider"] == "gemini"
    assert r.json()["key_hint"] == "9xyz"
    assert SECRET not in r.text
    listed = await client.get("/llm-keys", headers=user_a)
    assert [k["provider"] for k in listed.json()] == ["gemini"]
    assert SECRET not in listed.text


async def test_key_is_encrypted_in_database(client, user_a, valid_keys, db):
    from app.core.encryption import decrypt_key

    await client.put("/llm-keys/gemini", json={"api_key": SECRET}, headers=user_a)
    (row,) = await _stored_keys(db)
    assert SECRET not in row.encrypted_key
    assert decrypt_key(row.encrypted_key) == SECRET


async def test_key_is_trimmed_before_saving(client, user_a, valid_keys, db):
    from app.core.encryption import decrypt_key

    await client.put("/llm-keys/gemini", json={"api_key": f"  {SECRET}\n"}, headers=user_a)
    (row,) = await _stored_keys(db)
    assert decrypt_key(row.encrypted_key) == SECRET


async def test_invalid_key_rejected(client, user_a, invalid_keys, db):
    r = await client.put("/llm-keys/openai", json={"api_key": "sk-wrong"}, headers=user_a)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_api_key"
    assert "sk-wrong" not in r.text
    assert await _stored_keys(db) == []


async def test_blank_key_rejected(client, user_a, valid_keys, db):
    r = await client.put("/llm-keys/openai", json={"api_key": "   "}, headers=user_a)
    assert r.status_code == 422
    assert await _stored_keys(db) == []


async def test_replace_key_keeps_one_row(client, user_a, valid_keys, db):
    await client.put("/llm-keys/gemini", json={"api_key": "AIza-first-1111"}, headers=user_a)
    r = await client.put("/llm-keys/gemini", json={"api_key": "AIza-second-2222"}, headers=user_a)
    assert r.json()["key_hint"] == "2222"
    assert len(await _stored_keys(db)) == 1


async def test_delete_key(client, user_a, valid_keys):
    await client.put("/llm-keys/gemini", json={"api_key": SECRET}, headers=user_a)
    r = await client.delete("/llm-keys/gemini", headers=user_a)
    assert r.status_code == 204
    assert (await client.get("/llm-keys", headers=user_a)).json() == []


async def test_keys_are_per_user(client, user_a, user_b, valid_keys):
    await client.put("/llm-keys/gemini", json={"api_key": SECRET}, headers=user_a)
    assert (await client.get("/llm-keys", headers=user_b)).json() == []
    assert (await client.delete("/llm-keys/gemini", headers=user_b)).status_code == 204
    assert len((await client.get("/llm-keys", headers=user_a)).json()) == 1


async def test_unknown_provider_404(client, user_a, valid_keys):
    r = await client.put("/llm-keys/claude", json={"api_key": "x-1234"}, headers=user_a)
    assert r.status_code == 404
    assert (await client.delete("/llm-keys/claude", headers=user_a)).status_code == 404


async def test_get_user_api_key_decrypts(client, user_a, valid_keys, db):
    import uuid

    from app.agent.llm import get_user_api_key
    from tests.conftest import USER_A_ID

    await client.put("/llm-keys/gemini", json={"api_key": SECRET}, headers=user_a)
    assert await get_user_api_key(db, uuid.UUID(USER_A_ID), "gemini") == SECRET
    assert await get_user_api_key(db, uuid.UUID(USER_A_ID), "openai") is None


async def test_model_catalog(client, user_a):
    r = await client.get("/llm-models", headers=user_a)
    assert r.status_code == 200
    providers = {p["key"]: p for p in r.json()["providers"]}
    assert set(providers) == {"gemini", "openai"}
    for provider in providers.values():
        assert provider["name"]
        assert len(provider["models"]) >= 1
        assert all(m["id"] and m["name"] for m in provider["models"])


def test_is_valid_model():
    from app.core.llm_catalog import CATALOG, is_valid_model

    gemini = next(p for p in CATALOG["providers"] if p["key"] == "gemini")
    openai = next(p for p in CATALOG["providers"] if p["key"] == "openai")
    assert is_valid_model("gemini", gemini["models"][0]["id"])
    assert not is_valid_model("openai", gemini["models"][0]["id"])
    assert not is_valid_model("claude", openai["models"][0]["id"])


async def test_llm_endpoints_need_sign_in(client):
    assert (await client.get("/llm-keys")).status_code == 401
    assert (await client.get("/llm-models")).status_code == 401
