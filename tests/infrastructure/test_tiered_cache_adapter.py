"""Unit tests for ``TieredCacheAdapter`` (capability #21, ADR-021).

The tiered adapter composes a sync ``CachePort`` (L1, SQLite) with an
async ``RemoteCachePort`` (L2, Redis) and itself implements both
protocols. Tests verify:

  * Read order: L1 hit short-circuits the L2 round-trip; L1 miss falls
    through to L2 and writes back to L1 on the way out.
  * Write order: L1 is written synchronously; L2 is fire-and-forget
    via ``asyncio.create_task`` so the hot path never blocks on the
    network.
  * Health: ``True`` only when both tiers are healthy.
  * The wrapping never lifts SPEC-010 — an L2 outage is still a miss,
    not a raise.
"""

from __future__ import annotations

import asyncio

import pytest

from spectra.entities.models import (
    AnalysisReport,
    BatchCacheKey,
    DimensionScore,
    FileLocation,
    Finding,
    RepoCacheKey,
    ScoreCard,
)
from spectra.infrastructure.tiered_cache_adapter import TieredCacheAdapter

# ── Test doubles ─────────────────────────────────────────────


class _FakeLocalCache:
    """Sync in-memory stand-in for the SqliteCacheAdapter side."""

    def __init__(self) -> None:
        self.batches: dict[BatchCacheKey, tuple[Finding, ...]] = {}
        self.reports: dict[RepoCacheKey, AnalysisReport] = {}
        self.get_calls = 0
        self.put_calls = 0

    def get_batch_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        self.get_calls += 1
        return self.batches.get(key)

    def put_batch_findings(self, key: BatchCacheKey, findings: tuple[Finding, ...]) -> None:
        self.put_calls += 1
        self.batches[key] = findings

    def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        return self.reports.get(key)

    def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        self.reports[key] = report


class _FakeRemoteCache:
    """Async in-memory stand-in for the RedisCacheAdapter side."""

    def __init__(self, *, healthy: bool = True) -> None:
        self.batches: dict[BatchCacheKey, tuple[Finding, ...]] = {}
        self.reports: dict[RepoCacheKey, AnalysisReport] = {}
        self.get_calls = 0
        self.put_calls = 0
        self._healthy = healthy

    async def get_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        self.get_calls += 1
        return self.batches.get(key)

    async def put_findings(self, key: BatchCacheKey, findings: tuple[Finding, ...]) -> None:
        self.put_calls += 1
        self.batches[key] = findings

    async def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        return self.reports.get(key)

    async def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        self.reports[key] = report

    async def health(self) -> bool:
        return self._healthy


# ── Fixtures ─────────────────────────────────────────────────


def _finding() -> Finding:
    return Finding(
        id="T-1",
        dimension="security",
        severity="medium",
        title="Test",
        description="Test finding",
        location=FileLocation(file_path="src/main.py", line_start=1),
        recommendation="Fix it",
        agent_role="security",
        confidence=0.9,
    )


def _batch_key() -> BatchCacheKey:
    return BatchCacheKey(
        batch_id="b1",
        dimension="security",
        model_version="claude-opus-4-7",
        prompt_version="p1",
        schema_version="v1",
        spectra_version="0.7.0",
    )


def _repo_key() -> RepoCacheKey:
    return RepoCacheKey(
        repo_signature="r1",
        spectra_version="0.7.0",
        model_versions="m1",
        prompt_versions="p1",
        schema_version="v1",
    )


def _report() -> AnalysisReport:
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
        analysis_duration_seconds=10.0,
        total_tokens_used=100,
        total_cost_usd=0.01,
        agents_used=("security",),
    )


@pytest.fixture
def local() -> _FakeLocalCache:
    return _FakeLocalCache()


@pytest.fixture
def remote() -> _FakeRemoteCache:
    return _FakeRemoteCache()


@pytest.fixture
def tiered(local: _FakeLocalCache, remote: _FakeRemoteCache) -> TieredCacheAdapter:
    return TieredCacheAdapter(local=local, remote=remote)


# ── Read-through ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_l1_hit_short_circuits_l2(
    tiered: TieredCacheAdapter,
    local: _FakeLocalCache,
    remote: _FakeRemoteCache,
) -> None:
    """When L1 has the row, L2 is never queried."""
    key = _batch_key()
    local.batches[key] = (_finding(),)
    fetched = await tiered.get_findings(key)
    assert fetched == (_finding(),)
    assert local.get_calls == 1
    assert remote.get_calls == 0


@pytest.mark.asyncio
async def test_l1_miss_falls_through_to_l2(
    tiered: TieredCacheAdapter,
    local: _FakeLocalCache,
    remote: _FakeRemoteCache,
) -> None:
    """L1 miss → L2 hit; the value is also written back to L1."""
    key = _batch_key()
    findings = (_finding(),)
    remote.batches[key] = findings

    fetched = await tiered.get_findings(key)
    assert fetched == findings
    assert local.get_calls == 1
    assert remote.get_calls == 1
    # Write-back: the L1 cache now holds the value too.
    assert local.batches[key] == findings


@pytest.mark.asyncio
async def test_double_miss_returns_none(
    tiered: TieredCacheAdapter,
    local: _FakeLocalCache,
    remote: _FakeRemoteCache,
) -> None:
    """When both tiers miss, the tiered cache returns None."""
    assert await tiered.get_findings(_batch_key()) is None
    assert local.get_calls == 1
    assert remote.get_calls == 1


# ── Write-through ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_lands_on_both_tiers(
    tiered: TieredCacheAdapter,
    local: _FakeLocalCache,
    remote: _FakeRemoteCache,
) -> None:
    """A put writes synchronously to L1 and fires a task to L2."""
    key = _batch_key()
    findings = (_finding(),)
    await tiered.put_findings(key, findings)
    # L1 is synchronous — already there.
    assert local.batches[key] == findings
    # Drain the L2 fire-and-forget task scheduled on the loop.
    await asyncio.sleep(0)
    await tiered.drain()
    assert remote.batches[key] == findings


@pytest.mark.asyncio
async def test_l2_failure_does_not_block_write(
    local: _FakeLocalCache,
) -> None:
    """An L2 write failure is silently swallowed — L1 still gets the row."""

    class _ExplodingRemote(_FakeRemoteCache):
        async def put_findings(
            self,
            _key: BatchCacheKey,
            _findings: tuple[Finding, ...],
        ) -> None:
            raise ConnectionError("boom")

    remote = _ExplodingRemote()
    tiered = TieredCacheAdapter(local=local, remote=remote)
    key = _batch_key()
    await tiered.put_findings(key, (_finding(),))
    await tiered.drain()
    assert local.batches[key] == (_finding(),)


# ── Full report ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_report_l1_first_then_l2(
    tiered: TieredCacheAdapter,
    local: _FakeLocalCache,
    remote: _FakeRemoteCache,
) -> None:
    """L1 hit short-circuits the L2 round-trip for the full report path."""
    key = _repo_key()
    local.reports[key] = _report()
    fetched = await tiered.get_full_report(key)
    assert fetched == _report()


@pytest.mark.asyncio
async def test_full_report_write_back_from_l2(
    tiered: TieredCacheAdapter,
    local: _FakeLocalCache,
    remote: _FakeRemoteCache,
) -> None:
    """L1 miss + L2 hit on get_full_report writes back to L1."""
    key = _repo_key()
    remote.reports[key] = _report()
    fetched = await tiered.get_full_report(key)
    assert fetched == _report()
    assert local.reports[key] == _report()


@pytest.mark.asyncio
async def test_put_full_report_goes_to_both(
    tiered: TieredCacheAdapter,
    local: _FakeLocalCache,
    remote: _FakeRemoteCache,
) -> None:
    """Full-report writes hit L1 sync and L2 fire-and-forget."""
    key = _repo_key()
    await tiered.put_full_report(key, _report())
    await tiered.drain()
    assert local.reports[key] == _report()
    assert remote.reports[key] == _report()


# ── Health ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_requires_both_tiers(local: _FakeLocalCache) -> None:
    """Health returns True only when both L1 and L2 are healthy."""
    healthy_remote = _FakeRemoteCache(healthy=True)
    sick_remote = _FakeRemoteCache(healthy=False)

    assert await TieredCacheAdapter(local=local, remote=healthy_remote).health() is True
    assert await TieredCacheAdapter(local=local, remote=sick_remote).health() is False


# ── HMAC: end-to-end through both tiers (using real RedisCacheAdapter) ──


@pytest.mark.asyncio
async def test_end_to_end_with_real_redis_adapter(local: _FakeLocalCache) -> None:
    """End-to-end: tiered + real RedisCacheAdapter + fakeredis."""
    import fakeredis.aioredis

    from spectra.entities.models import CacheSecret
    from spectra.infrastructure.redis_cache_adapter import RedisCacheAdapter

    secret = CacheSecret(value=b"\x05" * 32)
    fake = fakeredis.aioredis.FakeRedis()
    redis_adapter = RedisCacheAdapter(client=fake, secret=secret)
    tiered = TieredCacheAdapter(local=local, remote=redis_adapter)

    key = _batch_key()
    await tiered.put_findings(key, (_finding(),))
    await tiered.drain()

    # Drop the L1 copy so the next read MUST traverse L2 + verify the MAC.
    local.batches.clear()
    fetched = await tiered.get_findings(key)
    assert fetched == (_finding(),)
    # Write-back populated L1 again.
    assert key in local.batches

    await fake.aclose()
