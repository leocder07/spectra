"""End-to-end integration: ``_enforce_policy`` reads YAML and raises SPEC-013.

This proves the wiring at the composition root: a ``.spectra-policy.yml``
in the workspace root triggers the gate and surfaces violations through
``PolicyGateError``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spectra.adapters.cli_controller import PolicyGateError
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)
from spectra.infrastructure.main import _enforce_policy


def _report(critical_finding: bool = False) -> AnalysisReport:
    findings = ()
    if critical_finding:
        findings = (
            Finding(
                id="F-1",
                dimension="security",
                severity="critical",
                title="t",
                description="d",
                location=FileLocation(file_path="src/x.py", line_start=1),
                recommendation="r",
                agent_role="security",
                confidence=0.9,
            ),
        )
    sc = ScoreCard(
        overall_score=80.0,
        overall_grade=score_to_grade(80.0),
        dimensions=(
            DimensionScore(
                dimension="security",
                score=80.0,
                grade=score_to_grade(80.0),
                findings_count=len(findings),
                weight=1.0,
            ),
        ),
        total_findings=len(findings),
    )
    return AnalysisReport(
        repo_url="x",
        repo_name="y",
        score_card=sc,
        findings=findings,
        analysis_duration_seconds=0.0,
        total_tokens_used=0,
        total_cost_usd=0.0,
        agents_used=(),
    )


class TestEnforcePolicy:
    def test_no_policy_file_passes(self, tmp_path: Path) -> None:
        # No .spectra-policy.yml → EmptyPolicy → no violations
        _enforce_policy(str(tmp_path), _report(critical_finding=True))

    def test_policy_with_critical_gate_blocks_critical_finding(self, tmp_path: Path) -> None:
        (tmp_path / ".spectra-policy.yml").write_text("severity_gate: critical\n", encoding="utf-8")
        with pytest.raises(PolicyGateError) as exc:
            _enforce_policy(str(tmp_path), _report(critical_finding=True))
        assert exc.value.error.code == "SPEC-013"
        assert len(exc.value.violations) == 1

    def test_policy_passes_when_no_violation(self, tmp_path: Path) -> None:
        (tmp_path / ".spectra-policy.yml").write_text("severity_gate: critical\n", encoding="utf-8")
        # No critical finding → passes
        _enforce_policy(str(tmp_path), _report(critical_finding=False))

    def test_min_score_violation_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".spectra-policy.yml").write_text("min_score_overall: 95.0\n", encoding="utf-8")
        with pytest.raises(PolicyGateError):
            _enforce_policy(str(tmp_path), _report())
