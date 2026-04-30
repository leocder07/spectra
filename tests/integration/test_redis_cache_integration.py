"""Integration test: exercise ``RedisCacheAdapter`` against a live Redis.

Gated on the ``SPECTRA_CACHE_REDIS`` env var so the default ``pytest``
invocation stays hermetic (no Docker, no networked services). Run with:

    SPECTRA_CACHE_REDIS=redis://localhost:6379/15 \
        pytest tests/integration/test_redis_cache_integration.py -m integration

Use a non-default DB index (``/15``) so the test cannot collide with a
shared cache. The fixture flushes the DB on entry + exit.
"""

from __future__ import annotations

import os

import pytest

from spectra.entities.models import (
    BatchCacheKey,
    CacheSecret,
    FileLocation,
    Finding,
)
from spectra.infrastructure.redis_cache_adapter import RedisCacheAdapter, _redis_module

_REDIS_URL = os.environ.get("SPECTRA_CACHE_REDIS")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(_REDIS_URL is None, reason="set SPECTRA_CACHE_REDIS to run"),
]


@pytest.fixture
async def adapter() -> RedisCacheAdapter:
    """Live Redis adapter wired to ``$SPECTRA_CACHE_REDIS``; flushes on enter+exit."""
    assert _REDIS_URL is not None  # narrowed by skipif
    redis_mod = _redis_module()
    assert redis_mod is not None, "redis-py not installed"
    raw_client = redis_mod.from_url(_REDIS_URL, decode_responses=False)
    await raw_client.flushdb()
    secret = CacheSecret(value=b"\xab" * 32)
    yield RedisCacheAdapter(client=raw_client, secret=secret, url=_REDIS_URL)
    await raw_client.flushdb()
    await raw_client.aclose()


@pytest.mark.asyncio
async def test_live_round_trip(adapter: RedisCacheAdapter) -> None:
    """Round-trip a finding through a real Redis instance."""
    key = BatchCacheKey(
        batch_id="int-1",
        dimension="security",
        model_version="claude-opus-4-7",
        prompt_version="p1",
        schema_version="v1",
        spectra_version="0.7.0",
    )
    finding = Finding(
        id="INT-1",
        dimension="security",
        severity="medium",
        title="Sample",
        description="Integration sample",
        location=FileLocation(file_path="src/main.py", line_start=1),
        recommendation="None",
        agent_role="security",
        confidence=0.5,
    )
    await adapter.put_findings(key, (finding,))
    fetched = await adapter.get_findings(key)
    assert fetched == (finding,)


@pytest.mark.asyncio
async def test_live_health(adapter: RedisCacheAdapter) -> None:
    """Health probe returns True against a healthy live Redis."""
    assert await adapter.health() is True
