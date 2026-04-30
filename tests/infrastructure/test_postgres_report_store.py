"""Unit tests for ``PostgresReportStoreAdapter`` — connection pool + SQL shape (#25).

Real Postgres is exercised by the gated integration test in
``tests/integration/test_postgres_history_integration.py``. These unit
tests stub the psycopg pool so they always run on CI without infra.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from spectra.entities.models import (
    DimensionScore,
    ReportSummary,
    ScoreCard,
    score_to_grade,
)


def _scorecard(overall: float = 82.5) -> ScoreCard:
    dims = (
        DimensionScore(dimension="architecture", score=85.0, grade="B", findings_count=3, weight=0.25),
        DimensionScore(
            dimension="security", score=overall, grade=score_to_grade(overall), findings_count=2, weight=0.25
        ),
        DimensionScore(dimension="quality", score=78.0, grade="C+", findings_count=5, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C-", findings_count=4, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=3, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    weighted = sum(d.score * d.weight for d in dims)
    return ScoreCard(
        overall_score=weighted,
        overall_grade=score_to_grade(weighted),
        dimensions=dims,
        total_findings=18,
    )


def _summary(scan_id: str = "abc123") -> ReportSummary:
    return ReportSummary(
        scan_id=scan_id,
        repo_signature="deadbeef" * 4,
        repo_url="https://github.com/octocat/spoon-knife",
        repo_name="spoon-knife",
        timestamp=datetime(2026, 4, 30, tzinfo=UTC),
        overall_score=82.5,
        overall_grade="B",
        score_card=_scorecard(),
        total_findings=18,
        finding_count_by_severity={"critical": 1, "high": 4, "medium": 8, "low": 3, "info": 2},
        finding_count_by_dimension={
            "architecture": 3,
            "security": 2,
            "quality": 5,
            "documentation": 4,
            "maintainability": 3,
            "performance": 1,
        },
        model_versions="claude-opus-4-7",
        prompt_versions="abcd1234",
        spectra_version="0.7.0",
        is_degraded=False,
        validation_status="validated",
        duration_seconds=142.7,
        cost_usd=0.42,
    )


class _FakeCursor:
    """Stand-in for psycopg cursor."""

    def __init__(self, fetchone_result: Any = None, fetchall_result: list[Any] | None = None) -> None:
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result or []
        self.executed: list[tuple[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        self.executed.append((sql, params))
        return self

    def fetchone(self) -> Any:
        return self._fetchone_result

    def fetchall(self) -> list[Any]:
        return self._fetchall_result


class _FakeConn:
    """Stand-in for a pooled psycopg connection."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_args: object) -> None:
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _FakePool:
    """Mimic psycopg_pool.ConnectionPool's context-manager API."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn
        self.opened = True
        self.closed = False

    def connection(self) -> _FakeConn:
        return self._conn

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_cursor() -> _FakeCursor:
    return _FakeCursor()


@pytest.fixture
def fake_pool(fake_cursor: _FakeCursor) -> _FakePool:
    return _FakePool(_FakeConn(fake_cursor))


class TestPostgresAdapterImports:
    """The adapter import + construction works with the fake pool injected."""

    def test_adapter_module_importable(self) -> None:
        # The adapter should NOT raise ImportError at module-load time
        # even when psycopg is missing — only at construction time.
        import spectra.infrastructure.history.postgres_report_store as mod

        assert hasattr(mod, "PostgresReportStoreAdapter")
        assert hasattr(mod, "build_pool")

    def test_construct_with_injected_pool(self, fake_pool: _FakePool) -> None:
        from spectra.infrastructure.history.postgres_report_store import (
            PostgresReportStoreAdapter,
        )

        adapter = PostgresReportStoreAdapter(pool=fake_pool)  # type: ignore[arg-type]
        assert adapter is not None


@pytest.mark.asyncio
class TestPostgresAdapterStoresAndQueries:
    """Verify the SQL shape the adapter sends to the pool."""

    async def test_store_executes_insert_with_summary_payload(
        self, fake_pool: _FakePool, fake_cursor: _FakeCursor
    ) -> None:
        from spectra.infrastructure.history.postgres_report_store import (
            PostgresReportStoreAdapter,
        )

        adapter = PostgresReportStoreAdapter(pool=fake_pool)  # type: ignore[arg-type]
        await adapter.store(_summary(scan_id="A1"))

        # First execute is the report INSERT; subsequent are dim+sev rows.
        sql_texts = [s for s, _ in fake_cursor.executed]
        assert any("INSERT INTO reports" in s for s in sql_texts)
        assert any("INSERT INTO report_dimension_scores" in s for s in sql_texts)
        assert any("INSERT INTO report_severity_counts" in s for s in sql_texts)
        # Postgres uses %s placeholders — verify we are not using sqlite ?s.
        assert all("?" not in s for s in sql_texts)

    async def test_latest_returns_summary_when_row_present(self, fake_cursor: _FakeCursor) -> None:
        from spectra.infrastructure.history.postgres_report_store import (
            PostgresReportStoreAdapter,
        )

        s = _summary(scan_id="A2")
        cursor_with_row = _FakeCursor(fetchone_result=(s.model_dump_json(),))
        pool = _FakePool(_FakeConn(cursor_with_row))

        adapter = PostgresReportStoreAdapter(pool=pool)  # type: ignore[arg-type]
        result = await adapter.latest(s.repo_signature)

        assert result is not None
        assert result.scan_id == "A2"

    async def test_latest_returns_none_when_no_row(self, fake_pool: _FakePool) -> None:
        from spectra.infrastructure.history.postgres_report_store import (
            PostgresReportStoreAdapter,
        )

        adapter = PostgresReportStoreAdapter(pool=fake_pool)  # type: ignore[arg-type]
        result = await adapter.latest("never-seen")

        assert result is None

    async def test_history_returns_tuple_of_summaries(self) -> None:
        from spectra.infrastructure.history.postgres_report_store import (
            PostgresReportStoreAdapter,
        )

        a = _summary(scan_id="A1")
        b = _summary(scan_id="A2")
        cursor = _FakeCursor(fetchall_result=[(a.model_dump_json(),), (b.model_dump_json(),)])
        pool = _FakePool(_FakeConn(cursor))

        adapter = PostgresReportStoreAdapter(pool=pool)  # type: ignore[arg-type]
        result = await adapter.history(
            "any",
            since=datetime(2026, 1, 1, tzinfo=UTC),
            until=datetime(2027, 1, 1, tzinfo=UTC),
        )

        assert len(result) == 2
        assert result[0].scan_id == "A1"
        assert result[1].scan_id == "A2"


class TestBuildPoolGuard:
    """When psycopg is missing, ``build_pool`` raises a clear error."""

    def test_build_pool_uses_provided_factory(self) -> None:
        from spectra.infrastructure.history.postgres_report_store import build_pool

        sentinel: list[str] = []

        def _factory(url: str, *, min_size: int, max_size: int) -> MagicMock:
            sentinel.append(url)
            return MagicMock()

        pool = build_pool("postgresql://user:pass@localhost/spectra", pool_factory=_factory)

        assert sentinel == ["postgresql://user:pass@localhost/spectra"]
        assert pool is not None


class TestPostgresMigrations:
    """The Postgres migration runner uses the same SQL files as SQLite."""

    def test_apply_migrations_runs_each_migration_once(self) -> None:
        from spectra.infrastructure.history.postgres_report_store import (
            apply_postgres_migrations,
        )

        cursor = _FakeCursor(fetchall_result=[])  # No prior migrations.
        pool = _FakePool(_FakeConn(cursor))

        applied = apply_postgres_migrations(pool=pool)  # type: ignore[arg-type]

        # At least the initial migration must run.
        assert "001_initial_schema" in applied
        # CREATE TABLE schema_migrations + initial schema script.
        sql_texts = [s for s, _ in cursor.executed]
        assert any("schema_migrations" in s for s in sql_texts)
        assert any("CREATE TABLE" in s for s in sql_texts)
