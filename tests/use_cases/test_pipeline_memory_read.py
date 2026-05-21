"""Tests for the Stage-2 MemoryPort read hook (v0.9.1, ADR-025 wiring §4).

Pipeline behavior:
  - When ``ctx.memory_port`` is set, ``_run_plan_stage`` queries 3 event
    kinds, renders the prior-context paragraph, and passes it to
    MetaPrompter as a ``prior_context`` kwarg.
  - When ``ctx.memory_port`` is None, the call site is a no-op — no
    queries, no kwarg, MetaPrompter receives only the file tree.
  - When ``query_events`` raises ``AgentError(SPEC-010)``, the call site
    catches, logs, and degrades to no prior context — pipeline continues.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.memory import MemoryEvent

if TYPE_CHECKING:
    from collections.abc import Sequence


class _FakeMemoryPort:
    """Minimal MemoryPort fake — captures queries, returns seeded events."""

    def __init__(
        self,
        *,
        scans: Sequence[MemoryEvent] = (),
        waivers: Sequence[MemoryEvent] = (),
        adrs: Sequence[MemoryEvent] = (),
        raise_on_read: Exception | None = None,
    ) -> None:
        self.scans = tuple(scans)
        self.waivers = tuple(waivers)
        self.adrs = tuple(adrs)
        self.raise_on_read = raise_on_read
        self.queries: list[tuple[str | None, datetime | None, int]] = []
        self.appended: list[MemoryEvent] = []

    async def append_event(self, event: MemoryEvent) -> None:
        self.appended.append(event)

    async def query_events(
        self,
        *,
        kind: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[MemoryEvent, ...]:
        self.queries.append((kind, since, limit))
        if self.raise_on_read is not None:
            raise self.raise_on_read
        if kind == "scan_completed":
            return self.scans
        if kind == "waiver_added":
            return self.waivers
        if kind == "adr_ingested":
            return self.adrs
        return ()

    async def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        limit: int = 100,
    ) -> tuple[MemoryEvent, ...]:
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return ()


def _scan_event() -> MemoryEvent:
    return MemoryEvent(
        id="scan:r-1",
        kind="scan_completed",
        repo_url="r",
        payload={
            "scan_id": "r-1",
            "overall_score": 84.0,
            "overall_grade": "B+",
            "finding_counts_by_severity": {"critical": 0, "high": 3, "medium": 7, "low": 2, "info": 0},
            "cost_usd": 1.0,
            "duration_seconds": 100.0,
            "is_degraded": False,
        },
        actor="x",
        occurred_at=datetime.now(UTC),
    )


class TestSafeBuildMemoryContext:
    """Direct unit tests for the helper used by _run_plan_stage."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_port(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_build_memory_context

        ctx = _FakePipelineCtx(memory_port=None)
        out = await _safe_build_memory_context(ctx)
        assert out == ""

    @pytest.mark.asyncio
    async def test_queries_all_three_event_kinds(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_build_memory_context

        port = _FakeMemoryPort(scans=(_scan_event(),))
        ctx = _FakePipelineCtx(memory_port=port)
        await _safe_build_memory_context(ctx)
        kinds = [q[0] for q in port.queries]
        assert "scan_completed" in kinds
        assert "waiver_added" in kinds
        assert "adr_ingested" in kinds

    @pytest.mark.asyncio
    async def test_returns_rendered_paragraph_when_events_exist(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_build_memory_context

        port = _FakeMemoryPort(scans=(_scan_event(),))
        ctx = _FakePipelineCtx(memory_port=port)
        out = await _safe_build_memory_context(ctx)
        assert out.startswith("Prior context:")
        assert "B+" in out

    @pytest.mark.asyncio
    async def test_returns_empty_on_read_failure(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_build_memory_context

        port = _FakeMemoryPort(raise_on_read=AgentError(ERRORS["SPEC-010"]))
        ctx = _FakePipelineCtx(memory_port=port)
        # MUST NOT raise — degrade silently
        out = await _safe_build_memory_context(ctx)
        assert out == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_streams_empty(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_build_memory_context

        port = _FakeMemoryPort()
        ctx = _FakePipelineCtx(memory_port=port)
        out = await _safe_build_memory_context(ctx)
        assert out == ""


class _FakePipelineCtx:
    """Tiny PipelineContext stand-in for unit tests."""

    def __init__(self, *, memory_port: Any) -> None:
        self.memory_port = memory_port
