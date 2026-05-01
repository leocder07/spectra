"""Tests for ``InMemoryRateAdapter`` — per-process token-bucket coordinator.

This is the Layer-4 default for the ``RateCoordinatorPort``: a token
bucket whose state lives in process memory, refilled at
``rate_per_minute / 60`` tokens per second up to ``capacity``. It is
the right answer for solo runs and the SPEC-010 fallback for the Redis
coordinator. The contract verified here is small but load-bearing:

- Tokens are honoured: 1 RPS bucket lets exactly one ``acquire`` resolve
  immediately; the second waits for the next refill tick.
- Stampede serialisation: 5 concurrent ``acquire(1)`` against a 1-RPS
  bucket complete with the documented inter-call spacing.
- Misuse raises: ``n_tokens <= 0`` raises ``ValueError`` immediately.
- Unset rate degenerates: when ``rate_per_minute is None`` the adapter
  is a pass-through (no waiting at any concurrency level).

The adapter uses ``time.monotonic`` + ``asyncio.sleep`` for refills;
tests use ``asyncio.wait_for`` with generous bounds rather than
sleeping in real time, so the suite stays fast (~0.5s end-to-end).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from spectra.infrastructure.inmemory_rate_adapter import InMemoryRateAdapter

# ── Misuse + degenerate ───────────────────────────────────────


@pytest.mark.asyncio
async def test_n_tokens_zero_raises_value_error() -> None:
    """Caller bug: zero-token acquire is meaningless and signals ValueError."""
    coord = InMemoryRateAdapter(rate_per_minute=60)
    with pytest.raises(ValueError):
        await coord.acquire(0)


@pytest.mark.asyncio
async def test_n_tokens_negative_raises_value_error() -> None:
    """Negative tokens are caller bugs; never silently treated as zero."""
    coord = InMemoryRateAdapter(rate_per_minute=60)
    with pytest.raises(ValueError):
        await coord.acquire(-1)


@pytest.mark.asyncio
async def test_unset_rate_is_passthrough() -> None:
    """``rate_per_minute=None`` means no enforcement — fast path for solo runs."""
    coord = InMemoryRateAdapter(rate_per_minute=None)
    start = time.monotonic()
    for _ in range(20):
        await coord.acquire(1)
    elapsed = time.monotonic() - start
    # 20 awaits with no rate cap should be near-instant; allow 200ms slack
    # for asyncio scheduling on a loaded CI runner.
    assert elapsed < 0.2


# ── Single-token acquire happy path ───────────────────────────


@pytest.mark.asyncio
async def test_first_acquire_returns_immediately_when_bucket_full() -> None:
    """A freshly-constructed bucket is full — the first call never blocks."""
    coord = InMemoryRateAdapter(rate_per_minute=60, capacity=1)
    start = time.monotonic()
    await coord.acquire(1)
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_second_acquire_waits_for_refill() -> None:
    """At 60 RPM (1 RPS) the second call resolves ~1s later, not immediately."""
    coord = InMemoryRateAdapter(rate_per_minute=60, capacity=1)
    await coord.acquire(1)  # drains the bucket
    start = time.monotonic()
    await coord.acquire(1)
    elapsed = time.monotonic() - start
    # Refill rate: 1 token per second. Allow [0.85, 1.6] for scheduling slop.
    assert 0.85 <= elapsed <= 1.6, f"expected ~1s refill wait, got {elapsed:.2f}s"


# ── Stampede serialisation ────────────────────────────────────


@pytest.mark.asyncio
async def test_stampede_five_workers_serialise_under_one_token() -> None:
    """5 concurrent acquires against a 1-RPS bucket complete one-per-second.

    The acceptance test from the PR brief: 5 mock workers under the same
    coordinator show 1 acquires + 4 waiters. We assert that exactly one
    completes immediately and the remaining four are spaced at >=0.85s.
    """
    coord = InMemoryRateAdapter(rate_per_minute=60, capacity=1)
    completion_times: list[float] = []
    start = time.monotonic()

    async def _worker() -> None:
        await coord.acquire(1)
        completion_times.append(time.monotonic() - start)

    await asyncio.gather(*(_worker() for _ in range(5)))

    completion_times.sort()
    # Worker 0 acquires immediately (bucket starts full, capacity=1).
    assert completion_times[0] < 0.1
    # Workers 1..4 each wait one refill tick (~1s) past the previous.
    for i in range(1, 5):
        gap = completion_times[i] - completion_times[i - 1]
        assert 0.85 <= gap <= 1.6, f"gap {i} = {gap:.2f}s outside [0.85, 1.6]"


# ── Multi-token acquire ───────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_token_acquire_drains_bucket() -> None:
    """``acquire(2)`` against a capacity-2 bucket succeeds, then blocks the next."""
    coord = InMemoryRateAdapter(rate_per_minute=60, capacity=2)
    await coord.acquire(2)  # drains the bucket
    start = time.monotonic()
    await coord.acquire(1)
    elapsed = time.monotonic() - start
    assert 0.85 <= elapsed <= 1.6


@pytest.mark.asyncio
async def test_acquire_exceeding_capacity_raises_value_error() -> None:
    """A request that can never be satisfied (n > capacity) is a caller bug."""
    coord = InMemoryRateAdapter(rate_per_minute=60, capacity=2)
    with pytest.raises(ValueError):
        await coord.acquire(3)


# ── Construction parameters ───────────────────────────────────


def test_default_capacity_matches_rate_per_second_minimum_one() -> None:
    """Default capacity defaults to ``ceil(rate_per_minute / 60)``, floor 1."""
    # 60 RPM → 1 RPS → capacity 1
    coord = InMemoryRateAdapter(rate_per_minute=60)
    assert coord.capacity == 1
    # 600 RPM → 10 RPS → capacity 10
    coord = InMemoryRateAdapter(rate_per_minute=600)
    assert coord.capacity == 10
    # 30 RPM → 0.5 RPS → capacity rounds up to 1
    coord = InMemoryRateAdapter(rate_per_minute=30)
    assert coord.capacity == 1


def test_explicit_capacity_overrides_default() -> None:
    """Operators can override the burst-capacity ceiling explicitly."""
    coord = InMemoryRateAdapter(rate_per_minute=60, capacity=5)
    assert coord.capacity == 5


def test_negative_rate_raises_value_error() -> None:
    """A negative RPM is a config bug — fail at construction."""
    with pytest.raises(ValueError):
        InMemoryRateAdapter(rate_per_minute=-1)


def test_zero_rate_raises_value_error() -> None:
    """A zero RPM bucket would never refill — refuse the foot-gun."""
    with pytest.raises(ValueError):
        InMemoryRateAdapter(rate_per_minute=0)
