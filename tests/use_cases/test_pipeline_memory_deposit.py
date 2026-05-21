"""Tests for the Stage-6 MemoryPort deposit hook (v0.9.1, ADR-025 wiring §5).

Pipeline behavior:
  - When ``ctx.memory_port`` is set, after Stage 6 completes the call
    site appends exactly one ``scan_completed`` event with payload per
    design doc §5.1.
  - When ``ctx.memory_port`` is None, no append, no error.
  - When ``append_event`` raises, the call site catches, logs WARN, and
    the scan still completes (writes degrade per ADR-025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from spectra.entities.memory import MemoryEvent
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
)


class _FakeMemoryPort:
    def __init__(self, *, raise_on_write: Exception | None = None) -> None:
        self.appended: list[MemoryEvent] = []
        self.raise_on_write = raise_on_write

    async def append_event(self, event: MemoryEvent) -> None:
        if self.raise_on_write is not None:
            raise self.raise_on_write
        self.appended.append(event)

    async def query_events(
        self,
        *,
        kind: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[MemoryEvent, ...]:
        return ()

    async def search(self, query: str, *, kind: str | None = None, limit: int = 100) -> tuple[MemoryEvent, ...]:
        return ()


def _fake_report(score: float = 84.5, grade: str = "B+", findings_count: int = 5) -> AnalysisReport:
    dims = ("architecture", "security", "quality", "documentation", "maintainability", "performance")
    dimensions = tuple(
        DimensionScore(dimension=dim, score=88.0, grade="A-", findings_count=0, weight=0.166)  # type: ignore[arg-type]
        for dim in dims
    )
    findings = tuple(
        Finding(
            id=f"f-{i}",
            title=f"finding {i}",
            description="d",
            dimension="security",
            severity="medium",
            location=FileLocation(file_path=f"src/x{i}.py", line_start=1),
            confidence=0.9,
            recommendation="fix",
            agent_role="security",
        )
        for i in range(findings_count)
    )
    score_card = ScoreCard(
        overall_score=score,
        overall_grade=grade,  # type: ignore[arg-type]
        dimensions=dimensions,
        total_findings=len(findings),
    )
    return AnalysisReport(
        repo_url="https://github.com/foo/bar",
        repo_name="bar",
        score_card=score_card,
        findings=findings,
        analysis_duration_seconds=218.4,
        total_tokens_used=12345,
        total_cost_usd=1.2347,
        agents_used=("security",),
    )


class _FakePipelineCtx:
    def __init__(self, *, memory_port: Any, run_id: str = "run-abc", actor: Any = None) -> None:
        self.memory_port = memory_port
        self.run_id = run_id
        self.actor = actor


class _FakeActor:
    actor = "spectra-cli"


class TestSafeDepositScanCompleted:
    @pytest.mark.asyncio
    async def test_no_op_when_no_port(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_deposit_scan_completed

        ctx = _FakePipelineCtx(memory_port=None)
        await _safe_deposit_scan_completed(ctx, _fake_report())
        # No raise, no side effect — function returns

    @pytest.mark.asyncio
    async def test_appends_scan_completed_event_when_port_wired(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_deposit_scan_completed

        port = _FakeMemoryPort()
        ctx = _FakePipelineCtx(memory_port=port, run_id="run-abc", actor=_FakeActor())
        await _safe_deposit_scan_completed(ctx, _fake_report())
        assert len(port.appended) == 1
        evt = port.appended[0]
        assert evt.kind == "scan_completed"
        assert evt.id == "scan:run-abc"

    @pytest.mark.asyncio
    async def test_event_payload_carries_score_grade_findings_cost(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_deposit_scan_completed

        port = _FakeMemoryPort()
        ctx = _FakePipelineCtx(memory_port=port, run_id="r", actor=_FakeActor())
        await _safe_deposit_scan_completed(ctx, _fake_report(score=84.5, grade="B+", findings_count=5))
        evt = port.appended[0]
        assert evt.payload["overall_score"] == 84.5
        assert evt.payload["overall_grade"] == "B+"
        # 5 medium findings
        counts = evt.payload["finding_counts_by_severity"]
        assert counts["medium"] == 5  # type: ignore[index]
        assert evt.payload["cost_usd"] == 1.2347

    @pytest.mark.asyncio
    async def test_write_failure_is_non_fatal(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_deposit_scan_completed

        port = _FakeMemoryPort(raise_on_write=OSError("disk full"))
        ctx = _FakePipelineCtx(memory_port=port, run_id="r", actor=_FakeActor())
        # MUST NOT raise — writes degrade per ADR-025
        await _safe_deposit_scan_completed(ctx, _fake_report())
        assert port.appended == []

    @pytest.mark.asyncio
    async def test_repo_url_from_report(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_deposit_scan_completed

        port = _FakeMemoryPort()
        ctx = _FakePipelineCtx(memory_port=port, run_id="r", actor=_FakeActor())
        await _safe_deposit_scan_completed(ctx, _fake_report())
        assert port.appended[0].repo_url == "https://github.com/foo/bar"

    @pytest.mark.asyncio
    async def test_actor_defaults_when_missing(self) -> None:
        from spectra.use_cases.analyze_repository import _safe_deposit_scan_completed

        port = _FakeMemoryPort()
        ctx = _FakePipelineCtx(memory_port=port, run_id="r", actor=None)
        await _safe_deposit_scan_completed(ctx, _fake_report())
        # Falls back to a non-empty actor string
        assert port.appended[0].actor != ""
