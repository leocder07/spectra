"""Tests for Literal type aliases in spectra.entities.enums."""

from __future__ import annotations

from typing import get_args

from spectra.entities.enums import (
    AgentRole,
    Dimension,
    Grade,
    PipelineState,
    Severity,
)


class TestSeverity:
    def test_all_values(self):
        values = get_args(Severity)
        assert set(values) == {"critical", "high", "medium", "low", "info"}

    def test_count(self):
        assert len(get_args(Severity)) == 5


class TestDimension:
    def test_all_values(self):
        values = get_args(Dimension)
        expected = {
            "architecture", "security", "quality",
            "documentation", "maintainability", "performance",
        }
        assert set(values) == expected

    def test_count(self):
        assert len(get_args(Dimension)) == 6


class TestGrade:
    def test_all_values(self):
        values = get_args(Grade)
        expected = {
            "A+", "A", "A-",
            "B+", "B", "B-",
            "C+", "C", "C-",
            "D+", "D", "D-",
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
            "meta_prompter", "architecture", "security", "quality",
            "documentation", "dependency", "performance", "critique",
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
            "pending", "ingesting", "meta_prompting", "analyzing",
            "merging", "critiquing", "reporting",
            "complete", "degraded", "failed",
        }
        assert set(values) == expected

    def test_count(self):
        assert len(get_args(PipelineState)) == 10

    def test_terminal_states(self):
        values = set(get_args(PipelineState))
        terminal = {"complete", "degraded", "failed"}
        assert terminal.issubset(values)
