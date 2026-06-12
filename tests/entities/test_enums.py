"""Tests for Literal type aliases in spectra.entities.enums."""

from __future__ import annotations

from typing import get_args

from spectra.entities.enums import (
    AgentRole,
    Dimension,
    Grade,
    PipelineState,
    Severity,
    coerce_severity,
)


class TestSeverity:
    def test_all_values(self):
        values = get_args(Severity)
        assert set(values) == {"critical", "high", "medium", "low", "info"}

    def test_count(self):
        assert len(get_args(Severity)) == 5


class TestCoerceSeverity:
    def test_exact_values_pass_through(self):
        for sev in get_args(Severity):
            assert coerce_severity(sev) == sev

    def test_case_variants_normalize(self):
        # A severity downgrade would let `--fail-on high` pass on a real
        # finding — realistic LLM casing must map to the canonical value.
        assert coerce_severity("High") == "high"
        assert coerce_severity("CRITICAL") == "critical"
        assert coerce_severity("Medium") == "medium"

    def test_surrounding_whitespace_normalizes(self):
        assert coerce_severity("critical ") == "critical"
        assert coerce_severity("  high\n") == "high"

    def test_genuinely_unknown_falls_to_default(self):
        assert coerce_severity("banana") == "info"
        assert coerce_severity("") == "info"

    def test_custom_default_is_honored(self):
        assert coerce_severity("nonsense", default="low") == "low"


class TestDimension:
    def test_all_values(self):
        values = get_args(Dimension)
        expected = {
            "architecture",
            "security",
            "quality",
            "documentation",
            "maintainability",
            "performance",
        }
        assert set(values) == expected

    def test_count(self):
        assert len(get_args(Dimension)) == 6


class TestGrade:
    def test_all_values(self):
        values = get_args(Grade)
        expected = {
            "A+",
            "A",
            "A-",
            "B+",
            "B",
            "B-",
            "C+",
            "C",
            "C-",
            "D+",
            "D",
            "D-",
            "F",
        }
        assert set(values) == expected

    def test_count(self):
        assert len(get_args(Grade)) == 13

    def test_ordering_preserved(self):
        values = get_args(Grade)
        assert values[0] == "A+"
        assert values[-1] == "F"


class TestAgentRole:
    def test_all_values(self):
        values = get_args(AgentRole)
        expected = {
            "meta_prompter",
            "architecture",
            "security",
            "quality",
            "documentation",
            "dependency",
            "performance",
            "critique",
        }
        assert set(values) == expected

    def test_count(self):
        assert len(get_args(AgentRole)) == 8

    def test_six_specialists(self):
        values = set(get_args(AgentRole))
        specialists = values - {"meta_prompter", "critique"}
        assert len(specialists) == 6


class TestPipelineState:
    def test_all_values(self):
        values = get_args(PipelineState)
        expected = {
            "pending",
            "ingesting",
            "meta_prompting",
            "analyzing",
            "merging",
            "critiquing",
            "reporting",
            "complete",
            "degraded",
            "failed",
            "compromised",
        }
        assert set(values) == expected

    def test_count(self):
        assert len(get_args(PipelineState)) == 11

    def test_terminal_states(self):
        values = set(get_args(PipelineState))
        terminal = {"complete", "degraded", "failed", "compromised"}
        assert terminal.issubset(values)

    def test_compromised_is_a_terminal_state(self):
        # ADR-011 §2: a run flagged with SPEC-PROMPT-INJECTION-DETECTED
        # is marked compromised; the report must surface this terminal
        # outcome alongside complete/degraded/failed.
        assert "compromised" in get_args(PipelineState)
