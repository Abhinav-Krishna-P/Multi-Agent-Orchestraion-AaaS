"""Encrypts users' LLM keys before they reach the database."""
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_master_key.encode())


def encrypt_key(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_key(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def key_hint(plain: str) -> str:
    """The only part of a key that is ever shown again."""
    return plain[-4:]
