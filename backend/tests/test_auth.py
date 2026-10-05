import pytest
from sqlalchemy import func, select

from tests.conftest import USER_A_ID, make_token


async def _user_count(db) -> int:
    from app.db.models import User

    return await db.scalar(select(func.count()).select_from(User))


async def test_me_creates_user(client, user_a, db):
    r = await client.get("/me", headers=user_a)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == USER_A_ID
    assert body["email"] == "a@example.com"
    assert body["name"] == "User A"
    assert body["avatar_url"] == "https://example.com/a.png"
    assert await _user_count(db) == 1


async def test_me_twice_keeps_one_row(client, user_a, db):
    await client.get("/me", headers=user_a)
    await client.get("/me", headers=user_a)
    assert await _user_count(db) == 1


async def test_me_updates_changed_name(client, headers_for, db):
    await client.get("/me", headers=headers_for(USER_A_ID, "a@example.com", "Old Name"))
    r = await client.get("/me", headers=headers_for(USER_A_ID, "a@example.com", "New Name"))
    assert r.json()["name"] == "New Name"
    assert await _user_count(db) == 1


def _bad_headers(kind: str) -> dict:
    if kind == "missing":
        return {}
    if kind == "malformed":
        return {"Authorization": "Bearer not-a-token"}
    if kind == "not_bearer":
        return {"Authorization": make_token()}
    if kind == "expired":
        return {"Authorization": f"Bearer {make_token(expires_in=-60)}"}
    if kind == "wrong_secret":
        return {"Authorization": f"Bearer {make_token(secret='another-secret-0123456789-0123456789-abc')}"}
    if kind == "wrong_audience":
        return {"Authorization": f"Bearer {make_token(audience='anon')}"}
    if kind == "sub_not_uuid":
        return {"Authorization": f"Bearer {make_token(sub='not-a-uuid')}"}
    raise ValueError(kind)


@pytest.mark.parametrize(
    "kind", ["missing", "malformed", "not_bearer", "expired", "wrong_secret", "wrong_audience", "sub_not_uuid"]
)
async def test_bad_tokens_get_401(client, db, kind):
    r = await client.get("/me", headers=_bad_headers(kind))
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthorized"
    assert r.json()["detail"]["message"] == "Your session expired. Sign in again."
    assert await _user_count(db) == 0
