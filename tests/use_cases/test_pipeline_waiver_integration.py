"""End-to-end pipeline integration: waivers + inline pragmas suppress findings.

Verifies that ``analyze_repository`` honours both ``ctx.waivers`` and
inline ``# spectra: ignore-next-line`` pragmas — the suppression count
is reflected on the final ``AnalysisReport``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from spectra.entities.models import (
    AgentOutput,
    AnalysisRequest,
    Codebase,
    FileLocation,
    Finding,
    Waiver,
    compute_finding_signature,
)
from spectra.use_cases.analyze_repository import PipelineContext, analyze_repository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _finding(
    *,
    fid: str = "F-1",
    file_path: str = "src/x.py",
    line: int = 10,
    rule_id: str = "SEC-AUTH-101",
    severity: str = "high",
) -> Finding:
    return Finding(
        id=fid,
        dimension="security",
        severity=severity,
        title="t",
        description="d",
        location=FileLocation(file_path=file_path, line_start=line),
        recommendation="r",
        agent_role="security",
        confidence=0.9,
        rule_id=rule_id,
    )


def _signed_waiver_for(finding: Finding) -> Waiver:
    sig = compute_finding_signature(
        finding.location.file_path,
        finding.rule_id,
        finding.severity,
    )
    return Waiver(
        repo_signature="r" * 32,
        finding_signature=sig,
        reason="documented bypass",
        waived_by="alice",
        waived_at=_now(),
        expires_at=_now() + timedelta(days=30),
        signature="x" * 128,  # not verified at this layer; loader handled it
    )


@pytest.fixture
def codebase() -> Codebase:
    return Codebase(
        repo_url="https://x/y",
        repo_name="y",
        local_path="/tmp/y",  # noqa: S108
        file_tree=("src/x.py",),
    )


@pytest.fixture
def request_obj() -> AnalysisRequest:
    return AnalysisRequest(repo_url="https://x/y", quick=True)


def _make_agent(role: str, findings: tuple[Finding, ...] = ()) -> AsyncMock:
    agent = AsyncMock()
    agent.role = role
    agent.run.return_value = AgentOutput(
        agent_role=role,
        findings=findings,
        tokens_used=100,
        duration_seconds=0.1,
        raw_response="{}",
    )
    return agent


@pytest.mark.asyncio
async def test_waiver_suppresses_matching_finding_in_pipeline(codebase, request_obj) -> None:
    finding = _finding(file_path="src/x.py", line=10)
    specialists = [_make_agent("security", findings=(finding,))]
    # Other 5 specialists return nothing — declared so partition_by_cache
    # / scoring still works
    for role in ("architecture", "quality", "documentation", "dependency", "performance"):
        specialists.append(_make_agent(role))

    waiver = _signed_waiver_for(finding)

    ctx = PipelineContext(
        request=request_obj,
        codebase=codebase,
        meta_prompter=_make_agent("meta_prompter"),
        specialists=specialists,
        waivers=(waiver,),
    )
    report = await analyze_repository(ctx)
    assert report.findings == ()
    assert report.waived_finding_count == 1


@pytest.mark.asyncio
async def test_pragma_suppresses_matching_finding_in_pipeline(
    codebase, request_obj
) -> None:
    finding = _finding(file_path="src/x.py", line=42, rule_id="SEC-AUTH-101")
    specialists = [_make_agent("security", findings=(finding,))]
    for role in ("architecture", "quality", "documentation", "dependency", "performance"):
        specialists.append(_make_agent(role))

    # Source content with pragma on line 41 → suppresses line 42
    source = (
        "\n" * 40
        + "# spectra: ignore-next-line SEC-AUTH-101\n"
        + "vulnerable_call()\n"
    )

    ctx = PipelineContext(
        request=request_obj,
        codebase=codebase,
        meta_prompter=_make_agent("meta_prompter"),
        specialists=specialists,
        source_files={"src/x.py": source},
    )
    report = await analyze_repository(ctx)
    assert report.findings == ()
    assert report.waived_finding_count == 1


@pytest.mark.asyncio
async def test_no_waivers_keeps_findings_intact(codebase, request_obj) -> None:
    finding = _finding()
    specialists = [_make_agent("security", findings=(finding,))]
    for role in ("architecture", "quality", "documentation", "dependency", "performance"):
        specialists.append(_make_agent(role))

    ctx = PipelineContext(
        request=request_obj,
        codebase=codebase,
        meta_prompter=_make_agent("meta_prompter"),
        specialists=specialists,
    )
    report = await analyze_repository(ctx)
    assert len(report.findings) == 1
    assert report.waived_finding_count == 0


@pytest.mark.asyncio
async def test_expired_waiver_count_propagates_to_report(codebase, request_obj) -> None:
    finding = _finding()
    specialists = [_make_agent("security", findings=(finding,))]
    for role in ("architecture", "quality", "documentation", "dependency", "performance"):
        specialists.append(_make_agent(role))

    expired = Waiver(
        repo_signature="r" * 32,
        finding_signature="dead" * 4,
        reason="long enough reason",
        waived_by="alice",
        waived_at=_now() - timedelta(days=200),
        expires_at=_now() - timedelta(days=20),
        signature="x" * 128,
    )

    ctx = PipelineContext(
        request=request_obj,
        codebase=codebase,
        meta_prompter=_make_agent("meta_prompter"),
        specialists=specialists,
        expired_waivers=(expired,),
    )
    report = await analyze_repository(ctx)
    assert report.expired_waiver_count == 1
    # Expired waiver does NOT suppress
    assert len(report.findings) == 1
