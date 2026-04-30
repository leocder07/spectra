"""Cost-tracker adapters — Layer 4 implementations of ``CostTrackerPort``.

Two flavours, one port:

- ``InMemoryCostTracker`` — process-local ledger; default when no
  ``--max-cost-per-hour`` rolling cap is requested. Cheap, zero I/O.
- ``SqliteCostTracker`` — persists rows in the existing ``cache.db``
  (table ``cost_log``) so the rolling 1-hour window survives across
  invocations. Uses ``strftime('%s','now')-3600`` for the window so the
  DB does the time math; no Python-side clock skew.

Both honour the contract: ``would_exceed`` is a pure projection,
``record`` is monotone, and ``last_hour_total`` includes only entries
inside the rolling window.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


_HOUR_SECONDS = 3600


def _validate_cost(cost_usd: float) -> None:
    """Reject negative spend — the ledger is monotone."""
    if cost_usd < 0:
        msg = f"cost_usd must be >= 0, got {cost_usd}"
        raise ValueError(msg)


# ── In-memory tracker ────────────────────────────────────────


class InMemoryCostTracker:
    """Process-local cost ledger satisfying ``CostTrackerPort``.

    Two parallel data structures:
    - ``_total``: running sum (O(1) ``total``).
    - ``_per_agent``: dict aggregator for the breakdown surfaced on
      ``BudgetExceededError``.
    - ``_recent``: list of (timestamp, cost) tuples used by
      ``last_hour_total`` — pruned lazily on each query so ``record``
      stays O(1).
    """

    def __init__(self) -> None:
        self._total: float = 0.0
        self._per_agent: dict[str, float] = defaultdict(float)
        self._recent: list[tuple[float, float]] = []

    def record(self, agent: str, cost_usd: float) -> None:
        """Add ``cost_usd`` to the ledger under ``agent``."""
        _validate_cost(cost_usd)
        self._total += cost_usd
        self._per_agent[agent] += cost_usd
        self._recent.append((time.time(), cost_usd))

    def total(self) -> float:
        """Return cumulative USD recorded this run."""
        return self._total

    def would_exceed(self, additional: float, max_usd: float) -> bool:
        """Return True iff ``total + additional > max_usd``."""
        return (self._total + additional) > max_usd

    def last_hour_total(self) -> float:
        """Return USD recorded in the last 3600 seconds."""
        cutoff = time.time() - _HOUR_SECONDS
        # Lazy prune: drop stale entries so the list stays bounded.
        self._recent = [(ts, c) for ts, c in self._recent if ts > cutoff]
        return sum(c for _, c in self._recent)

    def per_agent(self) -> dict[str, float]:
        """Return ``{agent: cost_usd}`` snapshot for the run."""
        return dict(self._per_agent)


# ── SQLite tracker ───────────────────────────────────────────


_CREATE_COST_LOG = """
CREATE TABLE IF NOT EXISTS cost_log (
    timestamp INTEGER NOT NULL,
    run_id    TEXT NOT NULL,
    agent     TEXT NOT NULL,
    cost_usd  REAL NOT NULL
)
"""

_CREATE_COST_LOG_INDEX = "CREATE INDEX IF NOT EXISTS idx_cost_ts ON cost_log(timestamp)"


class SqliteCostTracker:
    """SQLite-backed tracker for ``--max-cost-per-hour`` durability.

    Shares the existing ``cache.db`` file so operators don't accumulate
    a second on-disk artefact. ``run_id`` scopes ``total()`` to the
    current invocation while ``last_hour_total()`` aggregates across
    every run in the rolling window.
    """

    def __init__(self, db_path: Path, run_id: str) -> None:
        self._db_path = db_path
        self._run_id = run_id
        self._per_agent: dict[str, float] = defaultdict(float)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_COST_LOG)
        self._conn.execute(_CREATE_COST_LOG_INDEX)

    def record(self, agent: str, cost_usd: float) -> None:
        """Insert a row tagged with the current ``run_id`` + ``time()``."""
        _validate_cost(cost_usd)
        self._per_agent[agent] += cost_usd
        self._conn.execute(
            "INSERT INTO cost_log(timestamp, run_id, agent, cost_usd) VALUES (?, ?, ?, ?)",
            (int(time.time()), self._run_id, agent, cost_usd),
        )

    def total(self) -> float:
        """Return per-run cumulative USD (scoped to ``run_id``)."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM cost_log WHERE run_id = ?",
            (self._run_id,),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def would_exceed(self, additional: float, max_usd: float) -> bool:
        """Return True iff ``total + additional > max_usd``."""
        return (self.total() + additional) > max_usd

    def last_hour_total(self) -> float:
        """Return USD in the rolling 1-hour window across every run."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM cost_log WHERE timestamp > strftime('%s','now')-3600",
        ).fetchone()
        return float(row[0]) if row else 0.0

    def per_agent(self) -> dict[str, float]:
        """Return ``{agent: cost_usd}`` snapshot for the current run."""
        return dict(self._per_agent)

    def close(self) -> None:
        """Close the SQLite connection — safe to call multiple times.

        Mirrors SqliteCacheAdapter: cache I/O failures are never fatal.
        """
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()
