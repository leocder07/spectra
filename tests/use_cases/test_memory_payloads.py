"""Tests for memory payload builders (v0.9.1, ADR-025 wiring §5).

Three builder functions in ``spectra.use_cases.memory_payloads``:
  - ``build_scan_completed_event(report, scan_id, repo_url, actor)``
  - ``build_waiver_added_event(...)`` (reader exercises this in v0.9.1; writer ships later)
  - ``build_adr_ingested_event(adr_path, title, status, date, body_excerpt, repo_url, actor)``

Each returns a frozen :class:`MemoryEvent` with deterministic ``id`` so the
adapter's ``INSERT OR IGNORE`` makes replays a free no-op (ADR-025).
"""

from __future__ import annotations

import hashlib
from datetime import UTC

import pytest

from spectra.entities.memory import MemoryEvent
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
)
from spectra.use_cases.memory_payloads import (
    build_adr_ingested_event,
    build_scan_completed_event,
    build_waiver_added_event,
)


def _fake_report(
    *,
    score: float = 84.5,
    grade: str = "B+",
    findings: tuple[Finding, ...] = (),
    cost: float = 1.2347,
    duration: float = 218.4,
    degraded: bool = False,
) -> AnalysisReport:
    dims = ("architecture", "security", "quality", "documentation", "maintainability", "performance")
    dimensions = tuple(
        DimensionScore(dimension=dim, score=88.0, grade="A-", findings_count=0, weight=0.166)  # type: ignore[arg-type]
        for dim in dims
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
        analysis_duration_seconds=duration,
        total_tokens_used=12345,
        total_cost_usd=cost,
        agents_used=("architecture", "security"),
        is_degraded=degraded,
    )


class TestBuildScanCompletedEvent:
    def test_returns_frozen_memory_event(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        report = _fake_report()
        event = build_scan_completed_event(
            report=report,
            scan_id="01963a72e9c8721e9aa7c5b94c2f1a3b",
            repo_url="https://github.com/foo/bar",
            actor="spectra-cli",
        )
        assert isinstance(event, MemoryEvent)
        assert event.kind == "scan_completed"
        with pytest.raises(PydanticValidationError):
            event.id = "mutated"  # type: ignore[misc]

    def test_id_is_stable_for_same_scan_id(self) -> None:
        report = _fake_report()
        a = build_scan_completed_event(report=report, scan_id="run-1", repo_url="r", actor="x")
        b = build_scan_completed_event(report=report, scan_id="run-1", repo_url="r", actor="x")
        assert a.id == b.id == "scan:run-1"

    def test_payload_carries_score_grade_findings_cost_duration(self) -> None:
        # Findings hash by (file_path, line_start, dimension) — vary line to avoid dedup
        findings = (
            _finding(severity="critical", line=10),
            _finding(severity="high", line=20),
            _finding(severity="high", line=30),
        )
        report = _fake_report(
            score=84.5,
            grade="B+",
            findings=findings,
            cost=1.2347,
            duration=218.4,
        )
        event = build_scan_completed_event(
            report=report,
            scan_id="run-1",
            repo_url="https://github.com/foo/bar",
            actor="spectra-cli",
        )
        payload = event.payload
        assert payload["overall_score"] == 84.5
        assert payload["overall_grade"] == "B+"
        assert payload["finding_counts_by_severity"] == {
            "critical": 1,
            "high": 2,
            "medium": 0,
            "low": 0,
            "info": 0,
        }
        assert payload["cost_usd"] == 1.2347
        assert payload["duration_seconds"] == 218.4
        assert payload["is_degraded"] is False
        assert payload["scan_id"] == "run-1"

    def test_payload_dimension_scores_keyed_by_dimension(self) -> None:
        report = _fake_report()
        event = build_scan_completed_event(report=report, scan_id="r", repo_url="r", actor="x")
        dims = event.payload["dimension_scores"]
        assert set(dims) == {
            "architecture",
            "security",
            "quality",
            "documentation",
            "maintainability",
            "performance",
        }

    def test_occurred_at_is_utc_aware(self) -> None:
        report = _fake_report()
        event = build_scan_completed_event(report=report, scan_id="r", repo_url="r", actor="x")
        assert event.occurred_at.tzinfo == UTC

    def test_payload_is_json_serializable(self) -> None:
        import json

        report = _fake_report()
        event = build_scan_completed_event(report=report, scan_id="r", repo_url="r", actor="x")
        # Must serialise without TypeError — adapter relies on this
        json.dumps(event.payload)


class TestBuildWaiverAddedEvent:
    def test_id_is_stable_for_same_waiver_id(self) -> None:
        a = build_waiver_added_event(
            waiver_id="w-001",
            rule_id="sec/SSRF-001",
            file_path="src/x.py",
            line_start=42,
            reason="behind mTLS",
            approved_by="vivek",
            expires_at=None,
            repo_url="r",
            actor="x",
        )
        b = build_waiver_added_event(
            waiver_id="w-001",
            rule_id="sec/SSRF-001",
            file_path="src/x.py",
            line_start=42,
            reason="behind mTLS",
            approved_by="vivek",
            expires_at=None,
            repo_url="r",
            actor="x",
        )
        assert a.id == b.id == "waiver:w-001"

    def test_payload_carries_full_waiver_metadata(self) -> None:
        event = build_waiver_added_event(
            waiver_id="w-001",
            rule_id="sec/SSRF-001",
            file_path="src/api/proxy.py",
            line_start=142,
            reason="Internal-only endpoint behind mTLS",
            approved_by="vivek@spectra-ai",
            expires_at="2026-08-12T00:00:00+00:00",
            repo_url="https://github.com/foo/bar",
            actor="spectra-cli",
        )
        assert event.kind == "waiver_added"
        payload = event.payload
        assert payload["waiver_id"] == "w-001"
        assert payload["rule_id"] == "sec/SSRF-001"
        assert payload["file_path"] == "src/api/proxy.py"
        assert payload["line_start"] == 142
        assert payload["reason"] == "Internal-only endpoint behind mTLS"
        assert payload["approved_by"] == "vivek@spectra-ai"
        assert payload["expires_at"] == "2026-08-12T00:00:00+00:00"


class TestBuildAdrIngestedEvent:
    def test_id_is_sha256_of_adr_path(self) -> None:
        path = "docs/architecture/adr/ADR-025-memory-port.md"
        event = build_adr_ingested_event(
            adr_path=path,
            title="ADR-025: Memory Port",
            status="Proposed",
            date="2026-05-04",
            body_excerpt="...",
            repo_url="r",
            actor="x",
        )
        expected = f"adr:{hashlib.sha256(path.encode('utf-8')).hexdigest()[:16]}"
        assert event.id == expected

    def test_id_stable_across_calls_with_same_path(self) -> None:
        a = build_adr_ingested_event(
            adr_path="docs/architecture/adr/ADR-001.md",
            title="A",
            status="Accepted",
            date="2026-01-01",
            body_excerpt="",
            repo_url="r",
            actor="x",
        )
        b = build_adr_ingested_event(
            adr_path="docs/architecture/adr/ADR-001.md",
            title="A different title",  # title change does NOT change id
            status="Superseded",
            date="2026-02-02",
            body_excerpt="...",
            repo_url="r",
            actor="x",
        )
        assert a.id == b.id

    def test_payload_carries_path_title_status_date_excerpt(self) -> None:
        event = build_adr_ingested_event(
            adr_path="docs/architecture/adr/ADR-025-memory-port-and-managed-store-adapter.md",
            title="ADR-025: Memory Port + Managed Memory Store Adapter",
            status="Proposed (2026-05-04)",
            date="2026-05-04",
            body_excerpt="Q3 made Spectra fleet-operable...",
            repo_url="https://github.com/foo/bar",
            actor="spectra-cli",
        )
        assert event.kind == "adr_ingested"
        payload = event.payload
        assert payload["adr_path"] == "docs/architecture/adr/ADR-025-memory-port-and-managed-store-adapter.md"
        assert payload["title"] == "ADR-025: Memory Port + Managed Memory Store Adapter"
        assert payload["status"] == "Proposed (2026-05-04)"
        assert payload["date"] == "2026-05-04"
        assert payload["body_excerpt"] == "Q3 made Spectra fleet-operable..."

    def test_date_can_be_none(self) -> None:
        event = build_adr_ingested_event(
            adr_path="docs/adr/no-date.md",
            title="t",
            status="s",
            date=None,
            body_excerpt="",
            repo_url="r",
            actor="x",
        )
        assert event.payload["date"] is None


def _finding(*, severity: str, line: int = 1) -> Finding:
    return Finding(
        id=f"f-{severity}-{line}",
        title=f"a {severity} finding",
        description="d",
        dimension="security",
        severity=severity,  # type: ignore[arg-type]
        location=FileLocation(file_path="src/x.py", line_start=line),
        confidence=0.9,
        recommendation="fix it",
        agent_role="security",
    )
