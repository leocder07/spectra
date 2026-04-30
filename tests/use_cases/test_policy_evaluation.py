"""Tests for ``evaluate_policy`` — the pure policy gate (RICE-65).

The gate runs after scoring and returns a tuple of ``Violation`` for the
caller to surface as SPEC-013 (or pass when empty).
"""

from __future__ import annotations

import pytest

from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    EmptyPolicy,
    FileLocation,
    Finding,
    Policy,
    ScoreCard,
    score_to_grade,
)
from spectra.use_cases.policy_evaluation import evaluate_policy


def _scorecard(
    overall: float = 85.0,
    dims: tuple[str, ...] = (
        "architecture",
        "security",
        "quality",
        "documentation",
        "maintainability",
        "performance",
    ),
) -> ScoreCard:
    dimensions = tuple(
        DimensionScore(
            dimension=d,
            score=overall,
            grade=score_to_grade(overall),
            findings_count=0,
            weight=round(1.0 / len(dims), 3),
        )
        for d in dims
    )
    return ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dimensions,
        total_findings=0,
    )


def _finding(
    *,
    fid: str = "F-001",
    severity: str = "high",
    rule_id: str = "",
    dimension: str = "security",
) -> Finding:
    return Finding(
        id=fid,
        dimension=dimension,
        severity=severity,
        title="t",
        description="d",
        location=FileLocation(file_path="src/x.py", line_start=1),
        recommendation="r",
        agent_role="security",
        confidence=0.9,
        rule_id=rule_id,
    )


def _report(findings: tuple[Finding, ...] = (), overall: float = 85.0) -> AnalysisReport:
    return AnalysisReport(
        repo_url="https://x/y",
        repo_name="y",
        score_card=_scorecard(overall),
        findings=findings,
        analysis_duration_seconds=1.0,
        total_tokens_used=0,
        total_cost_usd=0.0,
        agents_used=(),
    )


class TestEmptyPolicy:
    def test_empty_policy_yields_no_violations(self) -> None:
        report = _report(findings=(_finding(severity="critical"),))
        assert evaluate_policy(EmptyPolicy(), report) == ()


class TestSeverityGate:
    def test_critical_finding_violates_critical_gate(self) -> None:
        report = _report(findings=(_finding(severity="critical"),))
        violations = evaluate_policy(Policy(severity_gate="critical"), report)
        assert len(violations) == 1
        assert violations[0].kind == "severity_gate"
        assert violations[0].finding_id == "F-001"

    def test_high_finding_passes_critical_gate(self) -> None:
        report = _report(findings=(_finding(severity="high"),))
        assert evaluate_policy(Policy(severity_gate="critical"), report) == ()

    def test_high_finding_violates_high_gate(self) -> None:
        report = _report(findings=(_finding(severity="high"),))
        violations = evaluate_policy(Policy(severity_gate="high"), report)
        assert len(violations) == 1

    def test_low_gate_blocks_medium(self) -> None:
        report = _report(findings=(_finding(severity="medium"),))
        violations = evaluate_policy(Policy(severity_gate="low"), report)
        assert len(violations) == 1

    def test_none_gate_disables_severity_check(self) -> None:
        report = _report(findings=(_finding(severity="critical"),))
        assert evaluate_policy(Policy(severity_gate="none"), report) == ()


class TestForbiddenRuleIds:
    def test_forbidden_rule_id_violates_even_if_low_severity(self) -> None:
        report = _report(findings=(_finding(severity="low", rule_id="SEC-AUTH-101"),))
        violations = evaluate_policy(
            Policy(severity_gate="none", forbidden_rule_ids=("SEC-AUTH-101",)),
            report,
        )
        assert len(violations) == 1
        assert violations[0].kind == "forbidden_rule_id"
        assert violations[0].rule_id == "SEC-AUTH-101"

    def test_unforbidden_rule_id_passes(self) -> None:
        report = _report(findings=(_finding(rule_id="SEC-AUTH-999"),))
        violations = evaluate_policy(
            Policy(forbidden_rule_ids=("SEC-AUTH-101",)),
            report,
        )
        assert violations == ()


class TestMinScoreOverall:
    def test_below_min_score_violates(self) -> None:
        report = _report(overall=70.0)
        violations = evaluate_policy(Policy(min_score_overall=80.0), report)
        assert len(violations) == 1
        assert violations[0].kind == "min_score_overall"

    def test_at_or_above_min_score_passes(self) -> None:
        report = _report(overall=80.0)
        assert evaluate_policy(Policy(min_score_overall=80.0), report) == ()


class TestRequiredDimensions:
    def test_missing_required_dimension_violates(self) -> None:
        # Build report where 'security' dimension is missing
        sc = _scorecard(dims=("architecture", "quality"))
        report = AnalysisReport(
            repo_url="https://x/y",
            repo_name="y",
            score_card=sc,
            findings=(),
            analysis_duration_seconds=1.0,
            total_tokens_used=0,
            total_cost_usd=0.0,
            agents_used=(),
        )
        violations = evaluate_policy(Policy(required_dimensions=("security",)), report)
        assert len(violations) == 1
        assert violations[0].kind == "required_dimension"
        assert violations[0].dimension == "security"

    def test_present_required_dimension_passes(self) -> None:
        report = _report()
        violations = evaluate_policy(
            Policy(required_dimensions=("security", "architecture")),
            report,
        )
        assert violations == ()


class TestMultipleViolations:
    def test_returns_all_violations_in_one_call(self) -> None:
        report = _report(
            findings=(
                _finding(severity="critical", fid="F-A"),
                _finding(severity="high", fid="F-B", rule_id="SEC-AUTH-101"),
            ),
            overall=50.0,
        )
        policy = Policy(
            severity_gate="critical",
            forbidden_rule_ids=("SEC-AUTH-101",),
            min_score_overall=80.0,
        )
        violations = evaluate_policy(policy, report)
        # 1 sev gate + 1 forbidden + 1 min_score = 3
        assert len(violations) == 3
        kinds = {v.kind for v in violations}
        assert kinds == {"severity_gate", "forbidden_rule_id", "min_score_overall"}


# Marker test: pytest happy without async
@pytest.mark.unit
def test_module_imports() -> None:
    from spectra.use_cases import policy_evaluation

    assert hasattr(policy_evaluation, "evaluate_policy")
