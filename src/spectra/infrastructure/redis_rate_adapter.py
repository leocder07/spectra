"""Redis-backed token-bucket implementation of ``RateCoordinatorPort`` (#22, ADR-013).

Layer 4 adapter — the use-case layer never imports ``redis``. The
composition root selects this adapter when ``--rate-coordinator
redis://...`` is passed (or its env-var equivalent), then wires it
behind the same ``RateCoordinatorPort`` the orchestrator awaits.

ADR-013 §3 — fleet rate limiting:
    Every CLI / runner that points at the same Redis instance honours
    the same per-(api_key x model) RPM ceiling. The bucket key is
    ``spectra:rpm:{tag}`` (operator-supplied tag, default ``global``).
    A short Lua script atomically refills + deducts on every call so
    50 concurrent runners cannot collectively exceed the configured
    RPM by racing past the check.

Failure mode (SPEC-010):
    Redis errors during ``acquire`` route the call through an
    in-process companion (``InMemoryRateAdapter``) for the rest of
    the run. The first failure logs a single SPEC-010 warning;
    subsequent failures are silent so the operator never sees
    N copies of the same warning. The pipeline keeps running with
    the per-process limit only — fleet coordination is best-effort.

Reuses the same Redis client family as ``RedisCacheAdapter`` (#21):
    redis-py 5.x ``redis.asyncio.Redis``. No new runtime dependency.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from spectra.infrastructure.inmemory_rate_adapter import InMemoryRateAdapter

if TYPE_CHECKING:
    from spectra.use_cases.interfaces import RateCoordinatorPort

_LOG = logging.getLogger("spectra.rate.redis")

_DEFAULT_BUCKET_PREFIX = "spectra:rpm:"
"""All adapter keys share this namespace so a future v2 layout can
co-exist on the same Redis without collision."""

_LUA_SCRIPT = """
-- KEYS[1] = bucket hash key
-- ARGV[1] = capacity (max tokens)
-- ARGV[2] = refill_per_second (float)
-- ARGV[3] = now_milliseconds (integer)
-- ARGV[4] = n_tokens to consume
--
-- Returns: { granted (0/1), wait_ms (integer) }
-- - granted=1 + wait_ms=0:    tokens deducted; caller proceeds
-- - granted=0 + wait_ms=N>0:  caller sleeps N ms then retries

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'last_refill_ms')
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local need = tonumber(ARGV[4])

local tokens = tonumber(bucket[1])
local last_refill_ms = tonumber(bucket[2])
if tokens == nil then
  tokens = capacity
  last_refill_ms = now_ms
end

-- Refill: accrued = elapsed_seconds * refill_per_second, capped at capacity.
local elapsed_ms = now_ms - last_refill_ms
if elapsed_ms < 0 then elapsed_ms = 0 end
local accrued = (elapsed_ms / 1000.0) * refill_per_sec
tokens = math.min(capacity, tokens + accrued)
last_refill_ms = now_ms

local granted = 0
local wait_ms = 0
if tokens >= need then
  tokens = tokens - need
  granted = 1
else
  -- Compute the milliseconds the caller must sleep before `need` tokens
  -- are reservable. Floor at 1ms so we never spin.
  local deficit = need - tokens
  wait_ms = math.ceil((deficit / refill_per_sec) * 1000.0)
  if wait_ms < 1 then wait_ms = 1 end
end

redis.call('HSET', KEYS[1],
  'tokens', tostring(tokens),
  'last_refill_ms', tostring(last_refill_ms))
-- Auto-expire idle buckets after 1h so a forgotten tag does not pin memory.
redis.call('PEXPIRE', KEYS[1], 3600000)

return {granted, wait_ms}
"""


class RedisRateAdapter:
    """``RateCoordinatorPort`` backed by Redis (>=5.0, ``redis.asyncio``).

    Constructed with a live async client; ``from_url`` is the
    convenience factory the composition root reaches for. Falls back
    to ``InMemoryRateAdapter`` on any Redis failure (SPEC-010) so the
    pipeline never blocks indefinitely.

    Args:
        client: An async Redis client (``redis.asyncio.Redis``-shaped).
            Anything answering ``async eval`` works, so the test suite
            can swap a fake without subclassing.
        rate_per_minute: Bucket refill rate (RPM). Must be positive.
        bucket_key: The Redis key holding the shared bucket state. All
            adapters pointing at the same key share one fleet-wide
            bucket. Operators typically scope this by api_key_id and
            model (``spectra:rpm:{api_key_id}:{model}``).
        capacity: Maximum tokens the bucket can hold. Defaults to
            ``ceil(rpm / 60)``, floor 1 (one second of refill).
        fallback: SPEC-010 in-process companion. Defaults to a fresh
            ``InMemoryRateAdapter(rate_per_minute=rpm)`` so degraded
            mode still enforces the same per-process limit.

    Raises:
        ValueError: ``rate_per_minute`` is non-positive (config bug).
    """

    def __init__(
        self,
        *,
        client: Any,  # noqa: ANN401 — redis.asyncio.Redis at runtime
        rate_per_minute: int,
        bucket_key: str,
        capacity: int | None = None,
        fallback: RateCoordinatorPort | None = None,
        url: str | None = None,
    ) -> None:
        if rate_per_minute <= 0:
            msg = f"rate_per_minute must be positive, got {rate_per_minute}"
            raise ValueError(msg)
        self._client = client
        self._rate_per_minute = rate_per_minute
        self._refill_per_second = rate_per_minute / 60.0
        self._bucket_key = bucket_key
        # Default capacity = one second of refill, floor 1; same shape as
        # ``InMemoryRateAdapter`` so the two adapters agree on burst window.
        self._capacity: int = capacity if capacity is not None else max(1, _ceil_div(rate_per_minute, 60))
        self._fallback: RateCoordinatorPort = fallback or InMemoryRateAdapter(rate_per_minute=rate_per_minute)
        self._fallback_active = False
        self._url = url
        # Production Redis supports EVAL; some test backends (fakeredis
        # without the optional ``[lua]`` extra) do not. We optimistically
        # try Lua and downgrade to the primitive emulation on the first
        # "no scripting" error — see ``_eval``.
        self._scripting_supported = True

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        rate_per_minute: int,
        tag: str = "global",
        capacity: int | None = None,
        socket_timeout: float = 2.0,
    ) -> RedisRateAdapter:
        """Construct an adapter from a ``redis://...`` connection string.

        The default 2s socket timeout caps the worst-case latency a
        rate-limit lookup can add to a scan — beyond that we degrade to
        the in-process fallback rather than block the pipeline.

        Args:
            url: Redis connection string (``redis://host:port/db``).
            rate_per_minute: Bucket refill rate.
            tag: Suffix appended to the namespaced bucket key. Operators
                scope by api_key_id and model — the composition root
                builds this from the resolved API-key digest at wire
                time.
            capacity: Override for the burst-capacity ceiling.
            socket_timeout: redis-py socket timeout (seconds).
        """
        from spectra.infrastructure.redis_cache_adapter import _redis_module

        redis_mod = _redis_module()
        if redis_mod is None:  # pragma: no cover — gated by dev install
            msg = "redis>=5.0 is required for RedisRateAdapter; install with 'pip install redis'"
            raise RuntimeError(msg)
        client = redis_mod.from_url(
            url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            decode_responses=False,
        )
        return cls(
            client=client,
            rate_per_minute=rate_per_minute,
            bucket_key=f"{_DEFAULT_BUCKET_PREFIX}{tag}",
            capacity=capacity,
            url=url,
        )

    @property
    def bucket_key(self) -> str:
        """The Redis key the bucket state lives under (for diagnostics)."""
        return self._bucket_key

    @property
    def url(self) -> str | None:
        """Connection URL the adapter was built with (diagnostics only)."""
        return self._url

    @property
    def rate_per_minute(self) -> int:
        """Configured refill rate in requests per minute."""
        return self._rate_per_minute

    async def acquire(self, n_tokens: int = 1) -> None:
        """Reserve ``n_tokens`` from the fleet-wide bucket; degrade on Redis failure.

        See ``RateCoordinatorPort.acquire`` for the contract.

        Implementation: in a loop, run the Lua script once per attempt.
        ``granted=1`` deducts the tokens and returns. ``granted=0``
        sleeps ``wait_ms`` ms then retries. The loop terminates because
        the deficit shrinks every refill tick — there is no starvation
        path under steady state.

        Once the adapter has fallen back to its in-process companion
        (SPEC-010), every subsequent ``acquire`` flows through the
        fallback; we do not retry the broken Redis on every call.
        """
        if n_tokens <= 0:
            msg = f"n_tokens must be positive, got {n_tokens}"
            raise ValueError(msg)
        if n_tokens > self._capacity:
            msg = f"n_tokens={n_tokens} exceeds bucket capacity {self._capacity}"
            raise ValueError(msg)
        if self._fallback_active:
            await self._fallback.acquire(n_tokens)
            return
        try:
            await self._acquire_via_redis(n_tokens)
        except Exception as exc:
            self._activate_fallback(exc)
            await self._fallback.acquire(n_tokens)

    async def _acquire_via_redis(self, n_tokens: int) -> None:
        """Run the refill/deduct loop until ``granted=1`` is observed.

        Production path is the Lua script (atomic refill+deduct in one
        round-trip). Servers without scripting support (fakeredis without
        the optional ``[lua]`` extra) auto-route through the primitive-
        based fallback (HMGET + HMSET, single round-trip per attempt).
        Both paths return the same (granted, wait_ms) shape, so the
        caller is path-agnostic.
        """
        import time as _time

        while True:
            now_ms = int(_time.time() * 1000)
            granted, wait_ms = await self._eval(now_ms, n_tokens)
            if granted == 1:
                return
            await asyncio.sleep(wait_ms / 1000.0)

    async def _eval(self, now_ms: int, n_tokens: int) -> tuple[int, int]:
        """Execute the Lua script and unpack the ``(granted, wait_ms)`` reply.

        On servers without Lua scripting (fakeredis without ``[lua]``)
        we degrade to a primitive-based emulation that issues the same
        refill+deduct logic over HMGET+HMSET. Real Redis always takes
        the Lua path; the emulation is hermetic-test infrastructure.
        """
        if not self._scripting_supported:
            return await self._eval_via_primitives(now_ms, n_tokens)
        try:
            raw = await self._client.eval(
                _LUA_SCRIPT,
                1,  # number of KEYS
                self._bucket_key,
                str(self._capacity),
                f"{self._refill_per_second:.6f}",
                str(now_ms),
                str(n_tokens),
            )
        except Exception as exc:
            if _is_no_scripting_error(exc):
                self._scripting_supported = False
                return await self._eval_via_primitives(now_ms, n_tokens)
            raise
        # redis-py returns a list of ints (or bytes/strs depending on
        # decode_responses). Coerce defensively.
        granted = int(raw[0])
        wait_ms = int(raw[1])
        return granted, wait_ms

    async def _eval_via_primitives(self, now_ms: int, n_tokens: int) -> tuple[int, int]:
        """Python-level refill+deduct using HMGET / HMSET / PEXPIRE.

        Atomicity here is weaker than the Lua path — two concurrent
        primitives-mode adapters against the same key can race. The
        path exists only for hermetic tests against fakeredis without
        the optional ``[lua]`` extra; production runs against real
        Redis always take the Lua path.
        """
        bucket = await self._client.hmget(self._bucket_key, "tokens", "last_refill_ms")
        tokens = float(_to_str(bucket[0])) if bucket[0] is not None else float(self._capacity)
        last_refill_ms = float(_to_str(bucket[1])) if bucket[1] is not None else float(now_ms)

        elapsed_ms = max(0.0, now_ms - last_refill_ms)
        accrued = (elapsed_ms / 1000.0) * self._refill_per_second
        tokens = min(float(self._capacity), tokens + accrued)
        last_refill_ms = float(now_ms)

        granted = 0
        wait_ms = 0
        if tokens >= n_tokens:
            tokens -= n_tokens
            granted = 1
        else:
            deficit = n_tokens - tokens
            wait_ms = max(1, round((deficit / self._refill_per_second) * 1000.0))

        await self._client.hset(
            self._bucket_key,
            mapping={"tokens": str(tokens), "last_refill_ms": str(last_refill_ms)},
        )
        await self._client.pexpire(self._bucket_key, 3600000)
        return granted, wait_ms

    def _activate_fallback(self, exc: BaseException) -> None:
        """Flip the SPEC-010 latch and log once.

        Once flipped, every subsequent ``acquire`` skips Redis entirely
        and uses the in-process fallback. This matches the
        SqliteCacheAdapter / RedisCacheAdapter precedent: cache failures
        degrade for the rest of the run rather than retrying every call.
        """
        if self._fallback_active:
            return
        self._fallback_active = True
        _LOG.warning(
            "SPEC-010: redis rate coordinator unavailable; degrading to in-process "
            "rate limit for the rest of the run: %s: %s",
            type(exc).__name__,
            exc,
        )

    async def aclose(self) -> None:
        """Close the underlying redis connection — best-effort."""
        try:
            close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        except Exception as exc:
            _LOG.debug("redis client close failed: %s", exc)


def _ceil_div(numerator: int, denominator: int) -> int:
    """Integer ceiling division — floor 0 produces 0 (caller guards)."""
    return -(-numerator // denominator)


def _is_no_scripting_error(exc: BaseException) -> bool:
    """True when the redis client reports it cannot run Lua (fakeredis sans lupa).

    The error message shape is provider-specific; we look for the well-
    known fragments without binding to a single exception class so the
    test path works against both ``redis.exceptions.ResponseError`` and
    fakeredis's emulation of it.
    """
    msg = str(exc).lower()
    return "unknown command" in msg and "eval" in msg


def _to_str(value: object) -> str:
    """Decode a redis hash field value to ``str`` regardless of decode mode."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
