"""Agent API keys: shown once at creation, stored only as a SHA-256 hash."""
import hashlib
import secrets


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> tuple[str, str, str]:
    """(key, hash, hint): the key itself is never stored."""
    key = "cap_" + secrets.token_urlsafe(32)
    return key, hash_key(key), key[-4:]
