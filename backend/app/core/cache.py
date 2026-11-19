"""The shared cache: JSON values with an expiry, in Redis when REDIS_URL is set.

Without Redis each process keeps its own in-memory store (what the app did before). Redis
failing never breaks a caller: a read becomes a miss, a write is dropped, and Redis is left
alone for SKIP_SECONDS so a dead server doesn't add its timeout to every call.
"""
import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

PREFIX = "cap:"
TIMEOUT_SECONDS = 0.3
SKIP_SECONDS = 30
MEMORY_MAX = 2000

client: Redis | None = None  # built on first use from REDIS_URL; tests may put a stand-in here
_memory: dict[str, tuple[float, str]] = {}
_down_until = 0.0
_outage = False


def digest(*parts) -> str:
    """A stable hash of the parts, for keys: no raw text or secret ever goes into a key."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def connect(url: str) -> Redis:
    # protocol=2: the client's default handshake (HELLO 3) needs Redis 6+; the owner runs 5.0.
    return from_url(
        url, socket_timeout=TIMEOUT_SECONDS, socket_connect_timeout=TIMEOUT_SECONDS, decode_responses=True, protocol=2
    )


def _redis() -> Redis | None:
    global client
    if client is None and get_settings().redis_url:
        client = connect(get_settings().redis_url)
    return client


def backend_name() -> str:
    return "redis" if _redis() is not None else "memory"


def _failed(error: BaseException) -> None:
    global _down_until, _outage
    if not _outage:  # one warning per outage; only the error's type, never a key or value
        logger.warning("Redis could not be used (%s); caching is skipped for now", type(error).__name__)
    _outage = True
    _down_until = time.monotonic() + SKIP_SECONDS


def _worked() -> None:
    global _outage
    _outage = False


def _usable() -> bool:
    return time.monotonic() >= _down_until


async def get_json(key: str) -> Any | None:
    redis = _redis()
    if redis is None:
        entry = _memory.get(key)
        return json.loads(entry[1]) if entry and entry[0] > time.monotonic() else None
    if not _usable():
        return None
    try:
        raw = await redis.get(PREFIX + key)
    except (RedisError, OSError, asyncio.TimeoutError) as error:
        _failed(error)
        return None
    _worked()
    return None if raw is None else json.loads(raw)


async def set_json(key: str, value: Any, seconds: int) -> None:
    try:
        raw = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as error:  # a value JSON can't hold is not cached, and never breaks the caller
        logger.warning("A value was not stored in the cache (%s)", error)
        return
    redis = _redis()
    if redis is None:
        if len(_memory) >= MEMORY_MAX:
            _memory.clear()
        _memory[key] = (time.monotonic() + seconds, raw)
        return
    if not _usable():
        return
    try:
        await redis.set(PREFIX + key, raw, ex=seconds)
    except (RedisError, OSError, asyncio.TimeoutError) as error:
        _failed(error)
        return
    _worked()


async def hit(key: str, seconds: int) -> int | None:
    """Counts one hit on `key` for a window of `seconds` and returns the count, or None if Redis failed."""
    redis = _redis()
    if redis is None:
        count, expires = 1, time.monotonic() + seconds
        if (entry := _memory.get(key)) and entry[0] > time.monotonic():
            count, expires = int(entry[1]) + 1, entry[0]
        elif len(_memory) >= MEMORY_MAX:
            _memory.clear()
        _memory[key] = (expires, str(count))
        return count
    if not _usable():
        return None
    try:
        count = await redis.incr(PREFIX + key)
        if count == 1:
            await redis.expire(PREFIX + key, seconds)
    except (RedisError, OSError, asyncio.TimeoutError) as error:
        _failed(error)
        return None
    _worked()
    return count


async def close() -> None:
    global client
    if client is not None:
        await client.aclose()
        client = None


def reset() -> None:
    """Empties the in-process store and forgets any Redis outage (tests)."""
    global _down_until, _outage
    _memory.clear()
    _down_until, _outage = 0.0, False
