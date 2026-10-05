"""Checks the Supabase sign-in token. The user ID is only ever taken from here."""
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt

from app.core.config import get_settings
from app.core.errors import ApiError

AUDIENCE = "authenticated"


@dataclass(frozen=True)
class Claims:
    sub: uuid.UUID
    email: str
    name: str | None
    avatar_url: str | None


def unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", "Your session expired. Sign in again.")


@lru_cache
def _jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_jwk_set=True, lifespan=3600
    )


def uses_shared_secret() -> bool:
    return bool(get_settings().supabase_jwt_secret)


def verify_token(token: str) -> Claims:
    """Returns the token's claims, or raises a 401 ApiError for any problem with it.

    With a shared secret configured this is pure computation; otherwise it may fetch
    Supabase's public keys over the network, so call it off the event loop.
    """
    settings = get_settings()
    try:
        if settings.supabase_jwt_secret:
            payload = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience=AUDIENCE)
        else:
            signing_key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token).key
            payload = jwt.decode(token, signing_key, algorithms=["ES256", "RS256"], audience=AUDIENCE)
        metadata = payload.get("user_metadata") or {}
        return Claims(
            sub=uuid.UUID(payload["sub"]),
            email=payload["email"],
            name=metadata.get("full_name") or metadata.get("name"),
            avatar_url=metadata.get("avatar_url") or metadata.get("picture"),
        )
    except Exception as exc:
        raise unauthorized() from exc
