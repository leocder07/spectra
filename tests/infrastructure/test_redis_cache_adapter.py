"""Unit tests for ``RedisCacheAdapter`` (capability #21, ADR-021).

The adapter is exercised against ``fakeredis`` so the test suite stays
hermetic — no Docker, no live Redis. The HMAC contract, the
SPEC-010 degrade-to-no-cache behaviour, and the per-row tamper
detection are the load-bearing invariants verified here.
"""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from spectra.entities.models import (
    AnalysisReport,
    BatchCacheKey,
    CacheSecret,
    DimensionScore,
    FileLocation,
    Finding,
    RepoCacheKey,
    ScoreCard,
)
from spectra.infrastructure.redis_cache_adapter import (
    RedisCacheAdapter,
    _redis_module,
)

# ── Test fixtures ─────────────────────────────────────────────


@pytest.fixture
def secret() -> CacheSecret:
    """A deterministic 32-byte HMAC secret for reproducible tests."""
    return CacheSecret(value=b"\x01" * 32)


@pytest.fixture
def alt_secret() -> CacheSecret:
    """A second secret for cross-secret tamper tests."""
    return CacheSecret(value=b"\x02" * 32)


@pytest.fixture
async def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Async fakeredis client shared across the adapter under test."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
async def adapter(
    secret: CacheSecret,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> RedisCacheAdapter:
    """RedisCacheAdapter wired to the fake client + deterministic secret."""
    return RedisCacheAdapter(client=fake_redis, secret=secret)


def _make_finding(file_path: str = "src/main.py") -> Finding:
    return Finding(
        id="TEST-1",
        dimension="security",
        severity="high",
        title="Hardcoded API key",
        description="An API key is committed to version control.",
        location=FileLocation(file_path=file_path, line_start=10),
        recommendation="Rotate the key and load it from the environment.",
        agent_role="security",
        confidence=0.9,
    )


def _batch_key() -> BatchCacheKey:
    return BatchCacheKey(
        batch_id="batch-1",
        dimension="security",
        model_version="claude-opus-4-7",
        prompt_version="p1",
        schema_version="v1",
        spectra_version="0.7.0",
    )


def _repo_key() -> RepoCacheKey:
    return RepoCacheKey(
        repo_signature="repo-sig-1",
        spectra_version="0.7.0",
        model_versions="claude-opus-4-7",
        prompt_versions="p-digest",
        schema_version="v1",
    )


def _empty_report() -> AnalysisReport:
    return AnalysisReport(
        repo_url="https://example.com/repo.git",
        repo_name="repo",
        score_card=ScoreCard(
            overall_score=80.0,
            overall_grade="B",
            total_findings=0,
            dimensions=(
                DimensionScore(dimension="architecture", score=80.0, grade="B", weight=0.25, findings_count=0),
                DimensionScore(dimension="security", score=80.0, grade="B", weight=0.25, findings_count=0),
                DimensionScore(dimension="quality", score=80.0, grade="B", weight=0.20, findings_count=0),
                DimensionScore(dimension="documentation", score=80.0, grade="B", weight=0.10, findings_count=0),
                DimensionScore(dimension="maintainability", score=80.0, grade="B", weight=0.10, findings_count=0),
                DimensionScore(dimension="performance", score=80.0, grade="B", weight=0.10, findings_count=0),
            ),
        ),
        findings=(),
        analysis_duration_seconds=12.5,
        total_tokens_used=1000,
        total_cost_usd=0.05,
        agents_used=("security",),
        cross_cutting_insights=(),
    )


# ── Health + connectivity ─────────────────────────────────────


@pytest.mark.asyncio
async def test_health_returns_true_when_redis_is_up(adapter: RedisCacheAdapter) -> None:
    """``health()`` is True when the fake client responds to PING."""
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_health_returns_false_when_redis_raises(secret: CacheSecret) -> None:
    """A broken client surfaces as False — no exception leaks."""

    class _Broken:
        async def ping(self) -> bool:
            raise ConnectionError("nope")

    broken = RedisCacheAdapter(client=_Broken(), secret=secret)
    assert await broken.health() is False


# ── Batch findings round-trip ────────────────────────────────


@pytest.mark.asyncio
async def test_get_findings_miss_returns_none(adapter: RedisCacheAdapter) -> None:
    """A cold cache returns None on the first lookup."""
    assert await adapter.get_findings(_batch_key()) is None


@pytest.mark.asyncio
async def test_round_trip_batch_findings(adapter: RedisCacheAdapter) -> None:
    """Findings written under a key come back unchanged on the next read."""
    key = _batch_key()
    findings = (_make_finding(),)
    await adapter.put_findings(key, findings)
    fetched = await adapter.get_findings(key)
    assert fetched == findings


@pytest.mark.asyncio
async def test_round_trip_empty_findings(adapter: RedisCacheAdapter) -> None:
    """Empty tuples are valid cache entries (no findings ≠ no analysis)."""
    key = _batch_key()
    await adapter.put_findings(key, ())
    assert await adapter.get_findings(key) == ()


# ── Full report round-trip ───────────────────────────────────


@pytest.mark.asyncio
async def test_round_trip_full_report(adapter: RedisCacheAdapter) -> None:
    """A persisted ``AnalysisReport`` round-trips byte-equal."""
    key = _repo_key()
    report = _empty_report()
    await adapter.put_full_report(key, report)
    fetched = await adapter.get_full_report(key)
    assert fetched == report


@pytest.mark.asyncio
async def test_full_report_miss_returns_none(adapter: RedisCacheAdapter) -> None:
    """Repo cache miss returns None — never raises."""
    assert await adapter.get_full_report(_repo_key()) is None


# ── HMAC tamper detection ────────────────────────────────────


@pytest.mark.asyncio
async def test_tampered_findings_payload_drops_row(
    fake_redis: fakeredis.aioredis.FakeRedis,
    secret: CacheSecret,
) -> None:
    """If the value bytes are mutated under us, the next read returns miss + drops the key."""
    adapter = RedisCacheAdapter(client=fake_redis, secret=secret)
    key = _batch_key()
    await adapter.put_findings(key, (_make_finding(),))

    # Find the raw redis key the adapter wrote and tamper with the value.
    raw_keys = await fake_redis.keys("*")
    assert raw_keys, "adapter must have written at least one redis key"
    target = raw_keys[0]
    await fake_redis.set(target, b"corrupted-bytes")

    assert await adapter.get_findings(key) is None
    # The tampered key was dropped — a follow-up SCAN finds nothing.
    assert await fake_redis.get(target) is None


@pytest.mark.asyncio
async def test_findings_written_under_one_secret_invisible_to_another(
    fake_redis: fakeredis.aioredis.FakeRedis,
    secret: CacheSecret,
    alt_secret: CacheSecret,
) -> None:
    """Adapter B with a different secret must never read adapter A's rows."""
    writer = RedisCacheAdapter(client=fake_redis, secret=secret)
    reader = RedisCacheAdapter(client=fake_redis, secret=alt_secret)
    key = _batch_key()
    await writer.put_findings(key, (_make_finding(),))
    assert await reader.get_findings(key) is None


# ── SPEC-010 degrade-to-no-cache ─────────────────────────────


@pytest.mark.asyncio
async def test_get_findings_degrades_on_redis_error(secret: CacheSecret) -> None:
    """Connection errors on read return None — pipeline keeps running."""

    class _ExplodingGet:
        async def get(self, _key: bytes) -> bytes | None:
            raise ConnectionError("boom")

        async def ping(self) -> bool:
            return True

    adapter = RedisCacheAdapter(client=_ExplodingGet(), secret=secret)
    assert await adapter.get_findings(_batch_key()) is None


@pytest.mark.asyncio
async def test_put_findings_silently_drops_on_redis_error(secret: CacheSecret) -> None:
    """Connection errors on write are swallowed — fire-and-forget."""

    class _ExplodingSet:
        async def set(self, *_a: object, **_k: object) -> bool:
            raise ConnectionError("boom")

        async def ping(self) -> bool:
            return True

    adapter = RedisCacheAdapter(client=_ExplodingSet(), secret=secret)
    # Must not raise.
    await adapter.put_findings(_batch_key(), (_make_finding(),))


@pytest.mark.asyncio
async def test_repeated_failures_log_spec010_only_once(
    secret: CacheSecret,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SPEC-010 surfaces once per process — the operator should not see N copies."""

    class _Always500:
        async def get(self, _key: bytes) -> bytes | None:
            raise ConnectionError("boom")

        async def ping(self) -> bool:
            return False

    adapter = RedisCacheAdapter(client=_Always500(), secret=secret)
    caplog.set_level("WARNING", logger="spectra.cache.redis")
    for _ in range(5):
        await adapter.get_findings(_batch_key())
    spec010_warnings = [r for r in caplog.records if "SPEC-010" in r.getMessage()]
    assert len(spec010_warnings) == 1


# ── Connection from URL ──────────────────────────────────────


def test_from_url_creates_redis_client(secret: CacheSecret) -> None:
    """``from_url`` builds a real ``redis.asyncio`` client when redis-py is installed."""
    redis_mod = _redis_module()
    if redis_mod is None:  # pragma: no cover — gated by dev install
        pytest.skip("redis-py not installed")
    adapter = RedisCacheAdapter.from_url("redis://localhost:6379/0", secret=secret)
    assert adapter.url == "redis://localhost:6379/0"


# ── HMAC orthogonality with the local cache ──────────────────


@pytest.mark.asyncio
async def test_remote_mac_differs_from_local_mac(
    secret: CacheSecret,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Same secret + same payload must produce DIFFERENT MACs at L1 vs L2.

    The local and remote ports are siblings, not extensions: the HMAC
    must be domain-separated by port name so a row stolen from L1 can
    never authenticate against L2 (and vice versa).
    """
    from spectra.infrastructure.cache_adapter import _compute_mac as local_mac
    from spectra.infrastructure.redis_cache_adapter import _compute_remote_mac

    key_parts = ("k1", "security", "m1", "p1", "v1", "0.7.0")
    payload = "[]"
    assert local_mac(secret, key_parts, payload) != _compute_remote_mac(secret, key_parts, payload)


# ── Read-after-write under concurrency ───────────────────────


@pytest.mark.asyncio
async def test_concurrent_writes_do_not_corrupt(adapter: RedisCacheAdapter) -> None:
    """Many writers against the same key resolve to a clean readable value."""
    key = _batch_key()
    findings = (_make_finding(),)
    await asyncio.gather(*(adapter.put_findings(key, findings) for _ in range(10)))
    assert await adapter.get_findings(key) == findings
