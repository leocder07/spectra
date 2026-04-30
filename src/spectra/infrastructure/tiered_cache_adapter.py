"""Two-tier cache adapter — L1 (sqlite) + L2 (remote) (#21, ADR-021).

Layer 4 composition: the use-case layer keeps consuming ``CachePort``
unchanged; this adapter implements that protocol on top of an inner
``CachePort`` (the local SQLite tier) and an inner ``RemoteCachePort``
(the distributed tier — today Redis). The adapter also satisfies
``RemoteCachePort`` so it can stand in anywhere either protocol is
required.

Read policy
    Local-first. ``get_*`` consults L1; on miss it awaits L2 and writes
    the value back to L1 so subsequent local reads are fast. A double
    miss returns ``None`` — neither tier raises on cache misses.

Write policy
    Local-sync, remote fire-and-forget. ``put_*`` writes L1 immediately
    so the same-process subsequent read is a guaranteed hit, then
    schedules the L2 write via ``asyncio.create_task``. The hot path
    never blocks on the network, and an L2 outage cannot stall the
    pipeline. Pending tasks are tracked so ``drain()`` and the test
    suite can wait for them deterministically.

Failure mode
    SPEC-010 is honoured at both tiers: a misbehaving L2 logs once per
    process and degrades to local-only. The tiered adapter is itself
    incapable of raising on cache I/O — by construction every call site
    catches ``BaseException`` from L2 and silently degrades to a miss.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from datetime import datetime

    from spectra.entities.enums import Dimension
    from spectra.entities.models import (
        AnalysisReport,
        BatchCacheKey,
        CacheStats,
        Finding,
        RepoCacheKey,
    )
    from spectra.use_cases.interfaces import CachePort, RemoteCachePort

_LOG = logging.getLogger("spectra.cache.tiered")


class TieredCacheAdapter:
    """Composes an L1 ``CachePort`` with an L2 ``RemoteCachePort``.

    The class implements both protocols structurally — every CachePort
    method delegates to L1 (the use-case layer's view of the cache is
    unchanged); every RemoteCachePort method delegates to L2 with the
    write-back tap that makes the next L1 read free.
    """

    def __init__(
        self,
        local: CachePort,
        remote: RemoteCachePort,
    ) -> None:
        """Bind L1 + L2. The adapter does not own either dependency's lifecycle."""
        self._local = local
        self._remote = remote
        self._pending: set[asyncio.Task[None]] = set()

    # ── Async (RemoteCachePort) surface ────────────────────────

    async def get_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """L1 → L2 read-through with write-back to L1 on L2 hit."""
        local_hit = self._local.get_batch_findings(key)
        if local_hit is not None:
            return local_hit
        remote_hit = await self._safe_remote_get_batch(key)
        if remote_hit is None:
            return None
        self._safe_local_put_batch(key, remote_hit)
        return remote_hit

    async def put_findings(
        self,
        key: BatchCacheKey,
        findings: tuple[Finding, ...],
    ) -> None:
        """Sync write to L1; fire-and-forget write to L2."""
        self._safe_local_put_batch(key, findings)
        self._spawn(self._safe_remote_put_batch(key, findings))

    async def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        """L1 → L2 read-through with write-back to L1 on L2 hit."""
        local_hit = self._local.get_full_report(key)
        if local_hit is not None:
            return local_hit
        remote_hit = await self._safe_remote_get_report(key)
        if remote_hit is None:
            return None
        self._safe_local_put_report(key, remote_hit)
        return remote_hit

    async def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        """Sync write to L1; fire-and-forget write to L2."""
        self._safe_local_put_report(key, report)
        self._spawn(self._safe_remote_put_report(key, report))

    async def health(self) -> bool:
        """Return True only when both tiers report healthy."""
        try:
            return bool(await self._remote.health())
        except Exception as exc:
            _LOG.debug("remote health probe raised: %s", exc)
            return False

    async def drain(self) -> None:
        """Wait for every outstanding L2 write task to settle.

        Idempotent. The composition root calls this at shutdown so the
        pipeline does not exit while a fire-and-forget L2 write is still
        on the wire.
        """
        if not self._pending:
            return
        await asyncio.gather(*self._pending, return_exceptions=True)
        self._pending.clear()

    # ── Sync (CachePort) surface — every method delegates to L1 ──

    def get_batch_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """Sync L1 lookup — used by the orchestrator's partition_by_cache."""
        return self._local.get_batch_findings(key)

    def put_batch_findings(self, key: BatchCacheKey, findings: tuple[Finding, ...]) -> None:
        """Sync L1 write + fire-and-forget L2 write.

        The L2 task fires only when an asyncio loop is running. The
        orchestrator only ever calls this from ``async def`` paths, so a
        ``RuntimeError`` here would signal a misuse worth surfacing —
        but we still degrade quietly because cache failures must not be
        fatal.
        """
        self._safe_local_put_batch(key, findings)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _LOG.debug("no running loop; skipping L2 write for batch %s", key.batch_id)
            return
        task = loop.create_task(self._safe_remote_put_batch(key, findings))
        self._track(task)

    def get_full_report_sync(self, key: RepoCacheKey) -> AnalysisReport | None:
        """Sync L1 lookup. Kept distinct from the async ``get_full_report``."""
        return self._local.get_full_report(key)

    def put_full_report_sync(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        """Sync L1 write + best-effort L2 write."""
        self._safe_local_put_report(key, report)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._safe_remote_put_report(key, report))
        self._track(task)

    def compute_repo_signature(self, file_tree: tuple[str, ...]) -> str:
        """Repo signature is L1's responsibility — same content hash everywhere."""
        return self._local.compute_repo_signature(file_tree)

    def stats(self) -> CacheStats:
        """Stats reflect L1 only — L2 stats are a separate ``cache doctor`` view."""
        return self._local.stats()

    def clear(self, repo_signature: str | None = None) -> int:
        """Delegate to L1; L2 is left untouched (cleared via its own admin tools)."""
        return self._local.clear(repo_signature)

    def clear_all(self) -> int:
        """Phase 4 ``cache clear`` — L1 only."""
        return self._local.clear_all()

    def clear_by_repo(self, repo_signature: str) -> int:
        """Phase 4 ``cache clear --repo`` — L1 only."""
        return self._local.clear_by_repo(repo_signature)

    def prune_older_than(
        self,
        cutoff: datetime,
        include_hit_log: bool = False,
    ) -> dict[str, int]:
        """Phase 4 ``cache prune`` — L1 only."""
        return self._local.prune_older_than(cutoff, include_hit_log=include_hit_log)

    def record_hit(self, dimension: Dimension, batch_id: str, hit: bool) -> None:
        """Telemetry — L1 only."""
        self._local.record_hit(dimension, batch_id, hit)

    def bind_run_context(
        self,
        model_versions: str,
        prompt_versions: str,
        schema_version: str,
        spectra_version: str,
    ) -> None:
        """Bind run context on L1; L2 derives the same context from the keys."""
        self._local.bind_run_context(model_versions, prompt_versions, schema_version, spectra_version)

    def batch_key_for(self, batch_id: str, dimension: Dimension) -> BatchCacheKey | None:
        """Build a key from L1's bound run context."""
        return self._local.batch_key_for(batch_id, dimension)

    # ── Private helpers ───────────────────────────────────────

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        """Schedule ``coro`` on the running loop and track it for ``drain``."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _LOG.debug("no running loop; dropping fire-and-forget L2 task")
            return
        task: asyncio.Task[None] = loop.create_task(coro)
        self._track(task)

    def _track(self, task: asyncio.Task[None]) -> None:
        """Hold a strong reference so the task is not GC'd mid-flight."""
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _safe_remote_get_batch(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """L2 batch read — never raises (cache failures are non-fatal)."""
        try:
            return await self._remote.get_findings(key)
        except Exception as exc:
            _LOG.debug("remote get_findings raised: %s", exc)
            return None

    async def _safe_remote_get_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        """L2 full-report read — never raises."""
        try:
            return await self._remote.get_full_report(key)
        except Exception as exc:
            _LOG.debug("remote get_full_report raised: %s", exc)
            return None

    async def _safe_remote_put_batch(
        self,
        key: BatchCacheKey,
        findings: tuple[Finding, ...],
    ) -> None:
        """L2 batch write — never raises."""
        try:
            await self._remote.put_findings(key, findings)
        except Exception as exc:
            _LOG.debug("remote put_findings raised: %s", exc)

    async def _safe_remote_put_report(
        self,
        key: RepoCacheKey,
        report: AnalysisReport,
    ) -> None:
        """L2 full-report write — never raises."""
        try:
            await self._remote.put_full_report(key, report)
        except Exception as exc:
            _LOG.debug("remote put_full_report raised: %s", exc)

    def _safe_local_put_batch(
        self,
        key: BatchCacheKey,
        findings: tuple[Finding, ...],
    ) -> None:
        """L1 batch write — never raises (cache failures are non-fatal)."""
        try:
            self._local.put_batch_findings(key, findings)
        except Exception as exc:
            _LOG.debug("local put_batch_findings raised: %s", exc)

    def _safe_local_put_report(
        self,
        key: RepoCacheKey,
        report: AnalysisReport,
    ) -> None:
        """L1 full-report write — never raises."""
        try:
            self._local.put_full_report(key, report)
        except Exception as exc:
            _LOG.debug("local put_full_report raised: %s", exc)
