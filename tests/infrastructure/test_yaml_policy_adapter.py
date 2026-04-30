"""Tests for ``YamlPolicyAdapter`` — loads and validates ``.spectra-policy.yml``.

Covers absence (returns ``EmptyPolicy``), valid load round-trip, and the
brand-voice ✗ error path for malformed YAML.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spectra.entities.errors import AgentError
from spectra.entities.models import EmptyPolicy
from spectra.infrastructure.yaml_policy_adapter import YamlPolicyAdapter


@pytest.fixture
def adapter() -> YamlPolicyAdapter:
    return YamlPolicyAdapter()


class TestLoad:
    def test_missing_file_returns_empty_policy(self, adapter, tmp_path: Path) -> None:
        loaded = adapter.load(tmp_path / "nonexistent.yml")
        assert loaded == EmptyPolicy()

    def test_valid_yaml_loads_all_fields(self, adapter, tmp_path: Path) -> None:
        path = tmp_path / ".spectra-policy.yml"
        path.write_text(
            "version: 1\n"
            "severity_gate: critical\n"
            "min_score_overall: 80.0\n"
            "forbidden_rule_ids:\n"
            "  - SEC-AUTH-101\n"
            "  - SEC-XSS-204\n"
            "required_dimensions:\n"
            "  - security\n"
            "  - architecture\n"
            "dimension_overrides:\n"
            "  security: 0.5\n",
            encoding="utf-8",
        )
        policy = adapter.load(path)
        assert policy.severity_gate == "critical"
        assert policy.min_score_overall == 80.0
        assert "SEC-AUTH-101" in policy.forbidden_rule_ids
        assert "security" in policy.required_dimensions
        assert policy.dimension_overrides["security"] == 0.5

    def test_empty_yaml_file_returns_empty_policy(self, adapter, tmp_path: Path) -> None:
        path = tmp_path / ".spectra-policy.yml"
        path.write_text("", encoding="utf-8")
        loaded = adapter.load(path)
        assert loaded == EmptyPolicy()

    def test_yaml_with_only_comments_returns_empty_policy(self, adapter, tmp_path: Path) -> None:
        path = tmp_path / ".spectra-policy.yml"
        path.write_text("# nothing here\n# just comments\n", encoding="utf-8")
        loaded = adapter.load(path)
        assert loaded == EmptyPolicy()

    def test_malformed_yaml_raises_spec_012(self, adapter, tmp_path: Path) -> None:
        path = tmp_path / ".spectra-policy.yml"
        # Unclosed bracket — invalid YAML
        path.write_text("severity_gate: [critical\n", encoding="utf-8")
        with pytest.raises(AgentError) as exc:
            adapter.load(path)
        assert exc.value.error.code == "SPEC-012"

    def test_invalid_schema_raises_spec_012(self, adapter, tmp_path: Path) -> None:
        path = tmp_path / ".spectra-policy.yml"
        path.write_text("severity_gate: catastrophic\n", encoding="utf-8")
        with pytest.raises(AgentError) as exc:
            adapter.load(path)
        assert exc.value.error.code == "SPEC-012"

    def test_evaluate_delegates_to_pure_function(self, adapter, tmp_path: Path) -> None:
        # Smoke test: verify evaluate() exists + uses the pure use case.
        from spectra.entities.models import (
            AnalysisReport,
            DimensionScore,
            FileLocation,
            Finding,
            Policy,
            ScoreCard,
            score_to_grade,
        )

        finding = Finding(
            id="F-1",
            dimension="security",
            severity="critical",
            title="t",
            description="d",
            location=FileLocation(file_path="x.py", line_start=1),
            recommendation="r",
            agent_role="security",
            confidence=0.9,
        )
        sc = ScoreCard(
            overall_score=80.0,
            overall_grade=score_to_grade(80.0),
            dimensions=(
                DimensionScore(
                    dimension="security",
                    score=80.0,
                    grade=score_to_grade(80.0),
                    findings_count=1,
                    weight=1.0,
                ),
            ),
            total_findings=1,
        )
        report = AnalysisReport(
            repo_url="x",
            repo_name="y",
            score_card=sc,
            findings=(finding,),
            analysis_duration_seconds=0.0,
            total_tokens_used=0,
            total_cost_usd=0.0,
            agents_used=(),
        )
        policy = Policy(severity_gate="critical")
        violations = adapter.evaluate(policy, report)
        assert len(violations) == 1
