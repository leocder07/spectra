"""Tests for SqliteCostTracker — persistence + last-hour window correctness.

The tracker shares ``cache.db`` with ``SqliteCacheAdapter`` so that
``--max-cost-per-hour`` survives a fresh process invocation. The key
behaviour to lock down is the rolling 1-hour window: rows with
``timestamp > strftime('%s','now')-3600`` count, older rows do not.
"""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING

import pytest

from spectra.infrastructure.cost_tracker import SqliteCostTracker

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cache.db"


class TestSqliteCostTrackerBasic:
    def test_record_persists_row(self, db_path: Path):
        tracker = SqliteCostTracker(db_path=db_path, run_id="run-A")
        tracker.record("architecture", 0.05)
        # Inspect raw row with a fresh connection — proves real persistence.
        conn = sqlite3.connect(str(db_path))
        try:
            rows = list(conn.execute("SELECT agent, cost_usd FROM cost_log"))
        finally:
            conn.close()
        assert rows == [("architecture", 0.05)]

    def test_total_sums_rows(self, db_path: Path):
        tracker = SqliteCostTracker(db_path=db_path, run_id="run-A")
        tracker.record("architecture", 0.05)
        tracker.record("security", 0.02)
        assert tracker.total() == pytest.approx(0.07)

    def test_persistence_across_instances(self, db_path: Path):
        first = SqliteCostTracker(db_path=db_path, run_id="run-A")
        first.record("architecture", 0.10)
        first.close()
        second = SqliteCostTracker(db_path=db_path, run_id="run-B")
        # last-hour total is shared across instances (rolling cap is global)
        assert second.last_hour_total() == pytest.approx(0.10)

    def test_total_per_run_only_counts_current_run(self, db_path: Path):
        first = SqliteCostTracker(db_path=db_path, run_id="run-A")
        first.record("architecture", 0.10)
        first.close()
        second = SqliteCostTracker(db_path=db_path, run_id="run-B")
        # ``total()`` is per-run; rolling-hour total spans every run.
        assert second.total() == 0.0


class TestLastHourWindow:
    def test_recent_row_inside_window(self, db_path: Path):
        tracker = SqliteCostTracker(db_path=db_path, run_id="run-A")
        tracker.record("architecture", 0.05)
        assert tracker.last_hour_total() == pytest.approx(0.05)

    def test_old_row_excluded_from_window(self, db_path: Path):
        tracker = SqliteCostTracker(db_path=db_path, run_id="run-A")
        # Insert a row that is 2 hours old by writing directly.
        old_ts = int(time.time()) - (2 * 3600)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO cost_log(timestamp, run_id, agent, cost_usd) VALUES (?, ?, ?, ?)",
                (old_ts, "run-A", "architecture", 1.00),
            )
            conn.commit()
        finally:
            conn.close()
        # Now record a fresh entry — only that one should count.
        tracker.record("security", 0.05)
        assert tracker.last_hour_total() == pytest.approx(0.05)


class TestWouldExceed:
    def test_below_cap_passes(self, db_path: Path):
        tracker = SqliteCostTracker(db_path=db_path, run_id="run-A")
        tracker.record("architecture", 0.40)
        assert tracker.would_exceed(0.05, max_usd=0.50) is False

    def test_above_cap_blocks(self, db_path: Path):
        tracker = SqliteCostTracker(db_path=db_path, run_id="run-A")
        tracker.record("architecture", 0.48)
        assert tracker.would_exceed(0.05, max_usd=0.50) is True

    def test_zero_budget_blocks_any_additional(self, db_path: Path):
        tracker = SqliteCostTracker(db_path=db_path, run_id="run-A")
        assert tracker.would_exceed(0.001, max_usd=0.0) is True
