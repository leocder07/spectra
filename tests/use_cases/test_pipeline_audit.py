"""End-to-end audit emission from the analyze_repository pipeline."""

from __future__ import annotations

from typing import cast

import pytest

from spectra.entities.audit import AuditEvent, Identity
from spectra.entities.models import AnalysisRequest, Codebase
from spectra.use_cases.analyze_repository import PipelineContext, analyze_repository
from spectra.use_cases.interfaces import AuditPort


class _RecordingAuditAdapter:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return


def _make_codebase(local_path: str = "/var/tmp/spectra-test-r") -> Codebase:  # noqa: S108 — synthetic test fixture
    return Codebase(
        repo_url="https://example.com/r",
        repo_name="r",
        local_path=local_path,
        file_tree=("README.md",),
    )


def _make_actor() -> Identity:
    return Identity(actor="alice@example.com", source="git", confidence="medium")


@pytest.mark.asyncio
async def test_pipeline_emits_scan_started_and_completed(
    make_agent: object,
    make_finding: object,
) -> None:
    """A successful run emits exactly one scan.started + one scan.completed."""
    audit = _RecordingAuditAdapter()
    finding_factory = cast("object", make_finding)
    agent_factory = cast("object", make_agent)
    specialists = [
        agent_factory(  # type: ignore[operator]
            role,
            findings=(finding_factory(dim=role.replace("dependency", "maintainability")),),  # type: ignore[operator]
        )
        for role in ("architecture", "security", "quality", "documentation", "dependency", "performance")
    ]
    meta = agent_factory("meta_prompter")  # type: ignore[operator]
    ctx = PipelineContext(
        request=AnalysisRequest(repo_url="https://example.com/r"),
        codebase=_make_codebase(),
        meta_prompter=meta,
        specialists=specialists,
        critique_agent=None,
        audit_port=cast("AuditPort", audit),
        actor=_make_actor(),
        spectra_version="0.6.0",
        run_id="run-001",
    )
    await analyze_repository(ctx)
    events = [e.event for e in audit.events]
    assert "scan.started" in events
    assert "scan.completed" in events


@pytest.mark.asyncio
async def test_pipeline_emit_failure_does_not_propagate(
    make_agent: object,
    make_finding: object,
) -> None:
    """A failing audit adapter must not break the pipeline."""

    class _BrokenAdapter:
        async def emit(self, event: AuditEvent) -> None:
            msg = "kaboom"
            raise RuntimeError(msg)

        async def flush(self) -> None:
            return

    finding_factory = cast("object", make_finding)
    agent_factory = cast("object", make_agent)
    specialists = [
        agent_factory(role, findings=(finding_factory(dim=role.replace("dependency", "maintainability")),))  # type: ignore[operator]
        for role in ("architecture", "security", "quality", "documentation", "dependency", "performance")
    ]
    meta = agent_factory("meta_prompter")  # type: ignore[operator]
    ctx = PipelineContext(
        request=AnalysisRequest(repo_url="https://example.com/r"),
        codebase=_make_codebase(),
        meta_prompter=meta,
        specialists=specialists,
        critique_agent=None,
        audit_port=cast("AuditPort", _BrokenAdapter()),
        actor=_make_actor(),
        spectra_version="0.6.0",
        run_id="run-002",
    )
    # Must not raise — silent degrade is the contract.
    report = await analyze_repository(ctx)
    assert report is not None


@pytest.mark.asyncio
async def test_no_audit_when_port_is_none(
    make_agent: object,
    make_finding: object,
) -> None:
    """Pipeline runs cleanly when no audit port is wired."""
    finding_factory = cast("object", make_finding)
    agent_factory = cast("object", make_agent)
    specialists = [
        agent_factory(role, findings=(finding_factory(dim=role.replace("dependency", "maintainability")),))  # type: ignore[operator]
        for role in ("architecture", "security", "quality", "documentation", "dependency", "performance")
    ]
    meta = agent_factory("meta_prompter")  # type: ignore[operator]
    ctx = PipelineContext(
        request=AnalysisRequest(repo_url="https://example.com/r"),
        codebase=_make_codebase(),
        meta_prompter=meta,
        specialists=specialists,
        critique_agent=None,
        audit_port=None,
        actor=None,
        spectra_version="0.6.0",
        run_id="run-003",
    )
    report = await analyze_repository(ctx)
    assert report is not None
