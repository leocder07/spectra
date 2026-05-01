"""Tests for ``RedisRateAdapter`` — fleet-wide token-bucket coordinator.

The adapter executes a Lua script against Redis to atomically refill
+ deduct tokens from a single bucket key per (api_key_id x model). All
runners pointed at the same Redis honour the same fleet RPM ceiling.

Failure-mode contract: SPEC-010 — when Redis is unreachable the
adapter falls back to its in-process companion (``InMemoryRateAdapter``)
for the rest of the run, logs the warning once, and keeps serving
``acquire`` calls. The pipeline never blocks indefinitely on a missing
backend.

Tests use ``fakeredis.aioredis`` so the suite stays hermetic — no
docker-compose, no live Redis. The Lua script is executed by fakeredis
in interpreted mode (the same path real redis-py takes when EVAL is
issued); the contract verified is identical.
"""

from __future__ import annotations

import asyncio
import time

import fakeredis.aioredis
import pytest

from spectra.infrastructure.inmemory_rate_adapter import InMemoryRateAdapter
from spectra.infrastructure.redis_rate_adapter import RedisRateAdapter

# ── Test fixtures ─────────────────────────────────────────────


@pytest.fixture
async def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Async fakeredis client shared across the adapter under test."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
async def adapter(fake_redis: fakeredis.aioredis.FakeRedis) -> RedisRateAdapter:
    """RedisRateAdapter pinned to the in-test bucket key + 60 RPM."""
    return RedisRateAdapter(
        client=fake_redis,
        rate_per_minute=60,
        bucket_key="spectra:test:rpm",
    )


# ── Construction ──────────────────────────────────────────────


def test_construction_requires_positive_rate(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    """Negative or zero RPM is a config bug — fail at construction time."""
    with pytest.raises(ValueError):
        RedisRateAdapter(client=fake_redis, rate_per_minute=0, bucket_key="x")
    with pytest.raises(ValueError):
        RedisRateAdapter(client=fake_redis, rate_per_minute=-1, bucket_key="x")


# ── Single-process happy path ─────────────────────────────────


@pytest.mark.asyncio
async def test_first_acquire_returns_immediately_when_bucket_full(adapter: RedisRateAdapter) -> None:
    """A freshly-keyed bucket is full — the first call never blocks."""
    start = time.monotonic()
    await adapter.acquire(1)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_second_acquire_against_drained_bucket_waits_for_refill(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """At 60 RPM (1 RPS) the second call waits ~1s for the next refill tick."""
    adapter = RedisRateAdapter(
        client=fake_redis,
        rate_per_minute=60,
        bucket_key="spectra:test:rpm:drain",
        capacity=1,
    )
    await adapter.acquire(1)  # drains the bucket
    start = time.monotonic()
    await adapter.acquire(1)
    elapsed = time.monotonic() - start
    assert 0.85 <= elapsed <= 1.6, f"expected ~1s refill wait, got {elapsed:.2f}s"


# ── Caller misuse ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_n_tokens_zero_raises_value_error(adapter: RedisRateAdapter) -> None:
    with pytest.raises(ValueError):
        await adapter.acquire(0)


@pytest.mark.asyncio
async def test_n_tokens_exceeding_capacity_raises(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    adapter = RedisRateAdapter(
        client=fake_redis,
        rate_per_minute=60,
        bucket_key="spectra:test:rpm:cap",
        capacity=2,
    )
    with pytest.raises(ValueError):
        await adapter.acquire(3)


# ── Fleet stampede across multiple "processes" ────────────────


@pytest.mark.asyncio
async def test_fleet_stampede_five_workers_share_one_bucket(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """5 distinct adapter instances against the same Redis serialise as one fleet.

    This is the headline acceptance test from the brief: 5 mock workers
    under the same Redis show 1 acquires + 4 waiters. Each adapter is a
    separate Python instance (modeling 5 separate runner processes)
    pointing at the same shared bucket key. The Lua script is the
    fleet-wide coordination point.
    """
    bucket_key = "spectra:test:rpm:stampede"
    adapters = [
        RedisRateAdapter(client=fake_redis, rate_per_minute=60, bucket_key=bucket_key, capacity=1) for _ in range(5)
    ]
    completion_times: list[float] = []
    start = time.monotonic()

    async def _worker(coord: RedisRateAdapter) -> None:
        await coord.acquire(1)
        completion_times.append(time.monotonic() - start)

    await asyncio.gather(*(_worker(a) for a in adapters))

    completion_times.sort()
    # Worker 0 acquires immediately (shared bucket starts full, capacity=1).
    assert completion_times[0] < 0.2
    # Workers 1..4 each wait one refill tick (~1s) past the previous;
    # this is the load-bearing fleet-wide guarantee.
    for i in range(1, 5):
        gap = completion_times[i] - completion_times[i - 1]
        assert 0.85 <= gap <= 1.8, f"gap {i} = {gap:.2f}s outside [0.85, 1.8]"


@pytest.mark.asyncio
async def test_two_adapters_share_bucket_state(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Adapter B observes the bucket state Adapter A drained."""
    bucket_key = "spectra:test:rpm:shared"
    a = RedisRateAdapter(client=fake_redis, rate_per_minute=60, bucket_key=bucket_key, capacity=1)
    b = RedisRateAdapter(client=fake_redis, rate_per_minute=60, bucket_key=bucket_key, capacity=1)

    await a.acquire(1)  # A drains the shared bucket
    start = time.monotonic()
    await b.acquire(1)  # B observes the drained state, waits for refill
    elapsed = time.monotonic() - start
    assert 0.85 <= elapsed <= 1.6


# ── SPEC-010 fallback ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_unreachable_falls_back_to_in_memory(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When Redis raises, the adapter degrades to its in-process companion.

    SPEC-010 contract: pipeline never blocks indefinitely on a missing
    backend. After the first failure the adapter routes every subsequent
    ``acquire`` through the in-memory fallback for the rest of the run.
    """

    class _Broken:
        async def eval(self, *_a: object, **_k: object) -> object:
            raise ConnectionError("redis down")

    fallback = InMemoryRateAdapter(rate_per_minute=600)  # generous so test is fast
    adapter = RedisRateAdapter(
        client=_Broken(),
        rate_per_minute=60,
        bucket_key="spectra:test:rpm:broken",
        fallback=fallback,
    )
    caplog.set_level("WARNING", logger="spectra.rate.redis")
    # First acquire triggers fallback + logs SPEC-010 once.
    start = time.monotonic()
    await adapter.acquire(1)
    elapsed = time.monotonic() - start
    assert elapsed < 0.2  # fallback is fast (generous bucket)
    spec010 = [r for r in caplog.records if "SPEC-010" in r.getMessage()]
    assert len(spec010) == 1
    # Subsequent calls also flow through fallback — no extra warnings.
    for _ in range(3):
        await adapter.acquire(1)
    spec010 = [r for r in caplog.records if "SPEC-010" in r.getMessage()]
    assert len(spec010) == 1


@pytest.mark.asyncio
async def test_no_fallback_supplied_uses_default_in_memory_with_same_rate() -> None:
    """When no fallback is wired, the adapter builds an in-memory one matching the rate."""

    class _Broken:
        async def eval(self, *_a: object, **_k: object) -> object:
            raise ConnectionError("redis down")

    adapter = RedisRateAdapter(
        client=_Broken(),
        rate_per_minute=600,
        bucket_key="spectra:test:rpm:default-fallback",
    )
    # Should not raise; adapter built its own InMemoryRateAdapter.
    await adapter.acquire(1)


# ── from_url constructor ──────────────────────────────────────


def test_from_url_creates_redis_client() -> None:
    """``from_url`` builds a real ``redis.asyncio`` client when redis-py is installed."""
    from spectra.infrastructure.redis_cache_adapter import _redis_module

    if _redis_module() is None:  # pragma: no cover — gated by dev install
        pytest.skip("redis-py not installed")
    adapter = RedisRateAdapter.from_url(
        "redis://localhost:6379/0",
        rate_per_minute=60,
    )
    assert adapter.bucket_key.startswith("spectra:rpm:")
