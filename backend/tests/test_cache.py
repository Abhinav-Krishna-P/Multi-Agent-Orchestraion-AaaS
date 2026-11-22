"""The shared cache: in-process store, Redis, and what happens when Redis fails."""
import os
import time

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core import cache

real_now = time.monotonic


class RaisingRedis:
    def __init__(self):
        self.calls = 0

    async def get(self, key):
        self.calls += 1
        raise RedisConnectionError("down")

    async def set(self, key, value, ex=None):
        self.calls += 1
        raise RedisConnectionError("down")

    async def incr(self, key):
        self.calls += 1
        raise RedisConnectionError("down")


class RecordingRedis:
    def __init__(self):
        self.sets, self.values = [], {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.sets.append((key, value, ex))
        self.values[key] = value


async def test_round_trip_and_expiry(monkeypatch):
    await cache.set_json("t:a", {"x": [1, 2]}, 10)
    assert await cache.get_json("t:a") == {"x": [1, 2]}
    later = real_now() + 11
    monkeypatch.setattr(cache.time, "monotonic", lambda: later)
    assert await cache.get_json("t:a") is None


async def test_values_are_copies():
    await cache.set_json("t:b", {"x": 1}, 10)
    (await cache.get_json("t:b"))["x"] = 99
    assert await cache.get_json("t:b") == {"x": 1}


async def test_a_value_that_is_not_json_is_skipped_not_raised(caplog):
    await cache.set_json("t:odd", {"when": object()}, 10)
    assert await cache.get_json("t:odd") is None
    assert "not stored" in caplog.text and "object" in caplog.text


async def test_digest_is_stable_and_order_free():
    assert cache.digest({"b": 1, "a": 2}) == cache.digest({"a": 2, "b": 1})
    assert cache.digest("a") != cache.digest("b")


async def test_memory_is_the_backend_without_a_url():
    assert cache.backend_name() == "memory"


async def test_redis_errors_are_misses_then_skipped_for_30s(monkeypatch, caplog):
    stub = RaisingRedis()
    monkeypatch.setattr(cache, "client", stub)
    assert await cache.get_json("t:c") is None
    await cache.set_json("t:c", 1, 10)  # no raise
    assert stub.calls == 1  # the write was skipped: inside the 30 s window
    assert caplog.text.count("Redis") == 1  # one warning per outage
    later = real_now() + 31
    monkeypatch.setattr(cache.time, "monotonic", lambda: later)
    assert await cache.get_json("t:c") is None
    assert stub.calls == 2


async def test_a_long_outage_warns_once_and_a_new_one_warns_again(monkeypatch, caplog):
    down = RaisingRedis()
    monkeypatch.setattr(cache, "client", down)
    clock = [real_now()]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    for _ in range(3):  # three windows of the same outage
        await cache.get_json("t:e")
        clock[0] += 31
    assert down.calls == 3 and caplog.text.count("Redis") == 1
    monkeypatch.setattr(cache, "client", RecordingRedis())
    await cache.get_json("t:e")  # Redis is back
    monkeypatch.setattr(cache, "client", down)
    clock[0] += 31
    await cache.get_json("t:e")
    assert caplog.text.count("Redis") == 2


async def test_redis_values_get_prefix_and_expiry(monkeypatch):
    stub = RecordingRedis()
    monkeypatch.setattr(cache, "client", stub)
    await cache.set_json("t:d", {"y": 1}, 60)
    assert stub.sets == [("cap:t:d", '{"y": 1}', 60)]
    assert await cache.get_json("t:d") == {"y": 1}
    assert await cache.get_json("t:missing") is None


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="needs a real Redis")
async def test_real_redis_round_trip(monkeypatch):
    real = cache.connect(os.environ["TEST_REDIS_URL"])
    monkeypatch.setattr(cache, "client", real)
    try:
        await cache.set_json("t:real", {"z": 1}, 30)
        assert await cache.get_json("t:real") == {"z": 1}
    finally:
        await real.delete("cap:t:real")
        await real.aclose()


async def test_hit_counts_in_memory_and_expires(monkeypatch):
    assert [await cache.hit("t:h", 60) for _ in range(3)] == [1, 2, 3]
    later = real_now() + 61
    monkeypatch.setattr(cache.time, "monotonic", lambda: later)
    assert await cache.hit("t:h", 60) == 1


async def test_hit_is_none_when_redis_fails(monkeypatch):
    stub = RaisingRedis()
    monkeypatch.setattr(cache, "client", stub)
    assert await cache.hit("t:h2", 60) is None
    assert await cache.hit("t:h2", 60) is None
    assert stub.calls == 1  # skipped while Redis is marked down
