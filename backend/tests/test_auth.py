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
    if kind == "no_expiry":
        return {"Authorization": f"Bearer {make_token(expires_in=None)}"}
    raise ValueError(kind)


@pytest.mark.parametrize(
    "kind",
    ["missing", "malformed", "not_bearer", "expired", "wrong_secret", "wrong_audience", "sub_not_uuid", "no_expiry"],
)
async def test_bad_tokens_get_401(client, db, kind):
    r = await client.get("/me", headers=_bad_headers(kind))
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthorized"
    assert r.json()["detail"]["message"] == "Your session expired. Sign in again."
    assert await _user_count(db) == 0


# --- public-key (JWKS) mode: what a real Supabase project uses ---------------------------


@pytest.fixture
def jwks_mode(monkeypatch):
    """Switches verification to public keys, served by a local keypair instead of Supabase."""
    from types import SimpleNamespace

    from cryptography.hazmat.primitives.asymmetric import ec

    from app.core import security
    from app.core.config import get_settings

    private_key = ec.generate_private_key(ec.SECP256R1())
    client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key()))
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", None)
    monkeypatch.setattr(security, "_jwks_client", lambda url: client)
    return SimpleNamespace(private_key=private_key, client=client)


def _payload(**overrides):
    import time

    now = int(time.time())
    return {"sub": USER_A_ID, "email": "a@example.com", "aud": "authenticated", "exp": now + 600, **overrides}


def test_public_key_token_is_accepted(jwks_mode):
    import jwt

    from app.core.security import verify_token

    claims = verify_token(jwt.encode(_payload(), jwks_mode.private_key, algorithm="ES256"))
    assert str(claims.sub) == USER_A_ID


def test_shared_secret_token_is_refused_in_public_key_mode(jwks_mode):
    import jwt

    from app.core.errors import ApiError
    from app.core.security import verify_token

    with pytest.raises(ApiError) as caught:
        verify_token(jwt.encode(_payload(), "any-shared-secret-0123456789-0123456789", algorithm="HS256"))
    assert caught.value.status == 401


def test_key_server_outage_is_not_a_sign_out(jwks_mode):
    import jwt

    from app.core.errors import ApiError
    from app.core.security import verify_token

    def unreachable(token):
        raise jwt.PyJWKClientConnectionError("cannot reach key server")

    jwks_mode.client.get_signing_key_from_jwt = unreachable
    with pytest.raises(ApiError) as caught:
        verify_token(jwt.encode(_payload(), jwks_mode.private_key, algorithm="ES256"))
    assert caught.value.status == 503
    assert caught.value.code == "auth_unavailable"


def test_app_refuses_to_start_without_a_way_to_verify_tokens(monkeypatch):
    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", None)
    monkeypatch.setattr(get_settings(), "supabase_url", "")
    with pytest.raises(RuntimeError):
        create_app()
