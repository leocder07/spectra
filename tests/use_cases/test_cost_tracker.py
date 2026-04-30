"""Tests for CostTrackerPort + InMemoryCostTracker (Q2 capability #5).

Capability #5 introduces a cost-tracking port consumed by the
orchestrator to gate per-agent calls against a per-run cap and a
rolling per-hour cap. The use case never knows whether the tracker is
in-memory (default for solo runs) or SQLite-backed (for shared runners).
"""

from __future__ import annotations

import pytest

from spectra.infrastructure.cost_tracker import InMemoryCostTracker


class TestInMemoryCostTrackerAccumulation:
    def test_total_starts_at_zero(self):
        tracker = InMemoryCostTracker()
        assert tracker.total() == 0.0

    def test_record_accumulates_total(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.05)
        tracker.record("security", 0.02)
        assert tracker.total() == pytest.approx(0.07)

    def test_record_zero_cost_is_noop_for_total(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.0)
        assert tracker.total() == 0.0

    def test_negative_cost_is_rejected(self):
        tracker = InMemoryCostTracker()
        with pytest.raises(ValueError):
            tracker.record("architecture", -0.01)

    def test_per_agent_breakdown(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.05)
        tracker.record("architecture", 0.03)
        tracker.record("security", 0.02)
        breakdown = tracker.per_agent()
        assert breakdown["architecture"] == pytest.approx(0.08)
        assert breakdown["security"] == pytest.approx(0.02)


class TestWouldExceed:
    def test_within_budget_returns_false(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.10)
        assert tracker.would_exceed(0.05, max_usd=0.50) is False

    def test_at_budget_returns_false(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.50)
        assert tracker.would_exceed(0.0, max_usd=0.50) is False

    def test_over_budget_returns_true(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.45)
        assert tracker.would_exceed(0.10, max_usd=0.50) is True

    def test_additional_zero_with_room_returns_false(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.10)
        assert tracker.would_exceed(0.0, max_usd=0.50) is False

    def test_max_usd_zero_means_no_room(self):
        """A budget of zero rejects any positive additional cost."""
        tracker = InMemoryCostTracker()
        assert tracker.would_exceed(0.001, max_usd=0.0) is True

    def test_max_usd_zero_with_zero_additional_returns_false(self):
        tracker = InMemoryCostTracker()
        assert tracker.would_exceed(0.0, max_usd=0.0) is False


class TestLastHourTotal:
    def test_empty_tracker_last_hour_zero(self):
        tracker = InMemoryCostTracker()
        assert tracker.last_hour_total() == 0.0

    def test_recent_cost_counts_in_last_hour(self):
        tracker = InMemoryCostTracker()
        tracker.record("architecture", 0.05)
        # Just-recorded entries fall well inside the 1-hour window.
        assert tracker.last_hour_total() == pytest.approx(0.05)
