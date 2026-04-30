"""Tests for ``analyze_repository`` writing to the history store (#25).

ADR-022 §6: after the report is built, the pipeline calls
``report_store.store(summary)`` if a store is wired. Failure is
non-fatal — same pattern as the audit port.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from spectra.entities.enums import AgentRole
from spectra.entities.models import (
    AgentOutput,
    AnalysisRequest,
    Codebase,
    FileLocation,
    Finding,
    ReportSummary,
)
from spectra.use_cases.analyze_repository import PipelineContext, analyze_repository


def _make_meta_agent() -> AsyncMock:
    """Return a stub meta-prompter that produces a minimal plan."""
    agent = AsyncMock()
    agent.role = "meta_prompter"
    agent.run.return_value = AgentOutput(
        agent_role="meta_prompter",
        findings=(),
        tokens_used=10,
        duration_seconds=0.1,
        raw_response='{"focus_areas":[]}',
    )
    return agent


def _make_specialist(role: AgentRole) -> AsyncMock:
    """Return a stub specialist that emits one Finding for ``role``."""
    role_map: dict[AgentRole, str] = {
        "architecture": "architecture",
        "security": "security",
        "quality": "quality",
        "documentation": "documentation",
        "dependency": "maintainability",
        "performance": "performance",
    }
    finding = Finding(
        id=f"F-{role}",
        dimension=role_map.get(role, "architecture"),  # type: ignore[arg-type]
        severity="low",
        title="t",
        description="d",
        location=FileLocation(file_path="src/main.py", line_start=1),
        recommendation="fix",
        agent_role=role,
        confidence=0.9,
    )
    agent = AsyncMock()
    agent.role = role
    agent.run.return_value = AgentOutput(
        agent_role=role,
        findings=(finding,),
        tokens_used=10,
        duration_seconds=0.1,
        raw_response="{}",
    )
    return agent


def _build_ctx(report_store: Any | None) -> PipelineContext:
    """Compose a minimal PipelineContext with the report_store under test."""
    return PipelineContext(
        request=AnalysisRequest(repo_url="https://github.com/octocat/spoon-knife"),
        codebase=Codebase(
            repo_url="https://github.com/octocat/spoon-knife",
            repo_name="spoon-knife",
            local_path="/tmp/spoon",
            file_tree=("src/main.py", "README.md"),
        ),
        meta_prompter=_make_meta_agent(),
        specialists=[
            _make_specialist("architecture"),
            _make_specialist("security"),
            _make_specialist("quality"),
            _make_specialist("documentation"),
            _make_specialist("dependency"),
            _make_specialist("performance"),
        ],
        critique_agent=None,  # quick mode = no critique
        report_store=report_store,
        spectra_version="0.7.0",
        run_id="test-run-001",
    )


class _CapturingStore:
    """In-memory ReportStorePort for verifying what the pipeline writes."""

    def __init__(self) -> None:
        self.stored: list[ReportSummary] = []

    async def store(self, report: ReportSummary) -> None:
        self.stored.append(report)

    async def latest(self, repo_signature: str) -> ReportSummary | None:  # noqa: ARG002
        return self.stored[-1] if self.stored else None

    async def history(
        self,
        repo_signature: str,  # noqa: ARG002
        since: datetime,  # noqa: ARG002
        until: datetime,  # noqa: ARG002
    ) -> tuple[ReportSummary, ...]:
        return tuple(self.stored)


class _FailingStore(_CapturingStore):
    """Store whose ``store`` always raises — verifies non-fatal contract."""

    async def store(self, report: ReportSummary) -> None:
        raise RuntimeError("simulated postgres outage")


@pytest.mark.asyncio
class TestPipelineHistoryStoreIntegration:
    """The pipeline writes a ReportSummary after the report is built."""

    async def test_store_called_with_summary(self) -> None:
        store = _CapturingStore()
        ctx = _build_ctx(report_store=store)
        # AnalysisRequest defaults quick=False, but no critique → quick path.
        ctx = ctx.__class__(
            **{
                **ctx.__dict__,
                "request": AnalysisRequest(
                    repo_url="https://github.com/octocat/spoon-knife", quick=True
                ),
            }
        )

        report = await analyze_repository(ctx)

        assert len(store.stored) == 1
        summary = store.stored[0]
        assert isinstance(summary, ReportSummary)
        assert summary.repo_name == report.repo_name
        assert summary.overall_score == report.score_card.overall_score

    async def test_store_failure_is_non_fatal(self) -> None:
        store = _FailingStore()
        ctx = _build_ctx(report_store=store)
        ctx = ctx.__class__(
            **{
                **ctx.__dict__,
                "request": AnalysisRequest(
                    repo_url="https://github.com/octocat/spoon-knife", quick=True
                ),
            }
        )

        # Should NOT raise — pipeline continues even when the store fails.
        report = await analyze_repository(ctx)

        assert report is not None
        assert report.repo_name == "spoon-knife"

    async def test_skip_when_no_store_wired(self) -> None:
        ctx = _build_ctx(report_store=None)
        ctx = ctx.__class__(
            **{
                **ctx.__dict__,
                "request": AnalysisRequest(
                    repo_url="https://github.com/octocat/spoon-knife", quick=True
                ),
            }
        )

        # Should NOT raise — None is the legitimate "no history wiring" state.
        report = await analyze_repository(ctx)

        assert report is not None
