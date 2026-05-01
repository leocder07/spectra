"""In-process token-bucket implementation of ``RateCoordinatorPort`` (#22, ADR-013).

This adapter is the right answer for the solo-user CLI invocation: one
process, one bucket, no infrastructure. It is also the SPEC-010
fallback for the Redis coordinator — when Redis is unreachable the
RedisRateAdapter delegates here for the rest of the run, so a fleet
operator never loses every per-process limit at once.

Token-bucket semantics:
    - The bucket starts full at ``capacity`` tokens.
    - It refills continuously at ``rate_per_minute / 60`` tokens per
      second up to ``capacity``.
    - ``acquire(n_tokens)`` waits (using ``asyncio.sleep``) until ``n``
      tokens are available, then deducts them and returns.
    - Multiple awaiters serialise through a single ``asyncio.Lock`` so
      the refill calculation never races.

Failure mode: there is no I/O — this adapter has no failure mode. The
only ``ValueError`` paths are caller bugs (``n_tokens <= 0`` or
``n > capacity``) verified at the entry point so misuse fails loud and
fast rather than silently deadlocking.
"""

from __future__ import annotations

import asyncio
import math
from time import monotonic


class InMemoryRateAdapter:
    """Per-process token bucket. Default ``RateCoordinatorPort`` implementation.

    Args:
        rate_per_minute: Refill rate in requests per minute. ``None``
            disables enforcement entirely (every ``acquire`` returns
            immediately) — the right default for solo runs without the
            ``--rate-limit-rpm`` flag.
        capacity: Maximum tokens the bucket can hold. Defaults to
            ``ceil(rate_per_minute / 60)`` with a floor of one — burst
            capacity equal to one second of refill, which is enough to
            accommodate the typical 6-specialist parallel kick-off
            without artificially serialising it.

    Raises:
        ValueError: ``rate_per_minute`` is non-positive (negative or
            zero — the latter would never refill, which is a foot-gun).

    Thread-safety: instances are single-event-loop. Multiple coroutines
    on the same loop are safe; multiple processes need the Redis
    coordinator (#22 part C).
    """

    def __init__(
        self,
        *,
        rate_per_minute: int | None,
        capacity: int | None = None,
    ) -> None:
        if rate_per_minute is not None and rate_per_minute <= 0:
            msg = f"rate_per_minute must be positive or None, got {rate_per_minute}"
            raise ValueError(msg)
        self._rate_per_minute = rate_per_minute
        self._refill_per_second = (rate_per_minute / 60.0) if rate_per_minute else 0.0
        # Default capacity is one second of refill (rounded up, floor 1).
        # Operators can override to widen the burst window.
        self._capacity: int = capacity if capacity is not None else _default_capacity(rate_per_minute)
        self._tokens: float = float(self._capacity)
        self._last_refill: float = monotonic()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        """Maximum tokens the bucket can hold (burst ceiling)."""
        return self._capacity

    @property
    def rate_per_minute(self) -> int | None:
        """Configured refill rate in requests per minute (``None`` = unlimited)."""
        return self._rate_per_minute

    async def acquire(self, n_tokens: int = 1) -> None:
        """Wait until ``n_tokens`` are available, then deduct them.

        See ``RateCoordinatorPort.acquire`` for the full contract.

        Args:
            n_tokens: Tokens to consume. Must be ``> 0`` and ``<= capacity``;
                a request that exceeds ``capacity`` would never be
                satisfied so we raise rather than block forever.
        """
        if n_tokens <= 0:
            msg = f"n_tokens must be positive, got {n_tokens}"
            raise ValueError(msg)
        # Pass-through fast path: no rate cap configured.
        if self._rate_per_minute is None:
            return
        if n_tokens > self._capacity:
            msg = f"n_tokens={n_tokens} exceeds bucket capacity {self._capacity}"
            raise ValueError(msg)
        await self._await_tokens(n_tokens)

    async def _await_tokens(self, n_tokens: int) -> None:
        """Lock + refill + deduct loop. Returns once ``n_tokens`` are reserved."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= n_tokens:
                    self._tokens -= n_tokens
                    return
                wait_seconds = self._wait_for(n_tokens)
                # Release the lock during the sleep so other awaiters can
                # contend on each refill tick — but re-acquire on wake to
                # re-evaluate the bucket atomically.
                await asyncio.sleep(wait_seconds)

    def _refill(self) -> None:
        """Add accrued tokens since the last refill, capped at ``capacity``."""
        now = monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        accrued = elapsed * self._refill_per_second
        if accrued <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + accrued)
        self._last_refill = now

    def _wait_for(self, n_tokens: int) -> float:
        """Compute the seconds-of-sleep needed before ``n_tokens`` are reservable."""
        deficit = n_tokens - self._tokens
        if deficit <= 0:
            return 0.0
        # _refill_per_second > 0 here — guarded by the rate-not-None check
        # in ``acquire``.
        return deficit / self._refill_per_second


def _default_capacity(rate_per_minute: int | None) -> int:
    """Default burst capacity = ``ceil(rate / 60)`` floor 1 (one second of refill)."""
    if rate_per_minute is None or rate_per_minute <= 0:
        return 1
    return max(1, math.ceil(rate_per_minute / 60))
