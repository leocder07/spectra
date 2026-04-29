"""Tests for the SQLite cache adapter (Phase 1 + Phase 2).

Covers schema initialization, round-trip serialization, fine-grained
invalidation by model/prompt/schema version, repo signature determinism,
WAL mode for concurrent reads, SPEC-010 fault handling, and Phase 2's
full-report storage keyed by ``RepoCacheKey``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from spectra.entities.errors import AgentError
from spectra.entities.models import (
    AnalysisReport,
    BatchCacheKey,
    CacheStats,
    DimensionScore,
    FileLocation,
    Finding,
    RepoCacheKey,
    ScoreCard,
    score_to_grade,
)
from spectra.infrastructure.cache_adapter import (
    SCHEMA_VERSION,
    SqliteCacheAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path

# ── Helpers ────────────────────────────────────────────────────


def _make_finding(
    file_path: str = "src/auth.py",
    line: int = 10,
    fid: str = "F-001",
) -> Finding:
    return Finding(
        id=fid,
        dimension="security",
        severity="high",
        title="A finding",
        description="Description",
        location=FileLocation(file_path=file_path, line_start=line),
        recommendation="Fix it",
        agent_role="security",
        confidence=0.9,
    )


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    """Return a tmp SQLite path so tests do not pollute ~/.cache."""
    return tmp_path / "cache.db"


@pytest.fixture
def adapter(cache_path: Path) -> SqliteCacheAdapter:
    return SqliteCacheAdapter(db_path=cache_path)


# ── Schema initialization ──────────────────────────────────────


class TestInitSchema:
    def test_init_creates_schema(self, cache_path: Path):
        SqliteCacheAdapter(db_path=cache_path)
        assert cache_path.exists()
        with sqlite3.connect(str(cache_path)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "findings_cache" in tables
        assert "hit_log" in tables

    def test_concurrent_reads_via_wal(self, cache_path: Path):
        SqliteCacheAdapter(db_path=cache_path)
        with sqlite3.connect(str(cache_path)) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_creates_parent_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "cache.db"
        SqliteCacheAdapter(db_path=nested)
        assert nested.exists()


# ── Round-trip get / put ───────────────────────────────────────


class TestRoundTrip:
    def test_put_then_get_round_trip(self, adapter: SqliteCacheAdapter):
        adapter.set_model_version("claude-opus-4-7")
        adapter.set_prompt_version("security", "security-v1")
        findings = (_make_finding(), _make_finding(line=99, fid="F-002"))
        adapter.put_findings(
            file_hash="hash-abc",
            dimension="security",
            findings=findings,
            model_version="claude-opus-4-7",
            prompt_version="security-v1",
        )
        got = adapter.get_findings(
            file_hash="hash-abc",
            dimension="security",
        )
        assert got == findings

    def test_get_miss_returns_none(self, adapter: SqliteCacheAdapter):
        assert adapter.get_findings("missing", "security") is None

    def test_put_overwrites_same_key(self, adapter: SqliteCacheAdapter):
        adapter.set_model_version("m")
        adapter.set_prompt_version("security", "p")
        adapter.put_findings(
            file_hash="h",
            dimension="security",
            findings=(_make_finding(),),
            model_version="m",
            prompt_version="p",
        )
        adapter.put_findings(
            file_hash="h",
            dimension="security",
            findings=(_make_finding(line=200, fid="F-NEW"),),
            model_version="m",
            prompt_version="p",
        )
        got = adapter.get_findings("h", "security")
        assert got is not None
        assert len(got) == 1
        assert got[0].id == "F-NEW"


# ── Invalidation ──────────────────────────────────────────────


class TestInvalidation:
    def test_invalidation_on_model_version_mismatch(
        self,
        adapter: SqliteCacheAdapter,
    ):
        adapter.set_model_version("claude-opus-4-7")
        adapter.set_prompt_version("security", "v1")
        adapter.put_findings(
            file_hash="h",
            dimension="security",
            findings=(_make_finding(),),
            model_version="claude-opus-4-7",
            prompt_version="v1",
        )
        # Sanity check: row is readable under the same model.
        assert adapter.get_findings("h", "security") is not None

        adapter.set_model_version("claude-opus-4-8")
        assert adapter.get_findings("h", "security") is None

    def test_invalidation_on_prompt_version_mismatch(
        self,
        adapter: SqliteCacheAdapter,
    ):
        adapter.set_model_version("m")
        adapter.set_prompt_version("security", "security-v1")
        adapter.put_findings(
            file_hash="h",
            dimension="security",
            findings=(_make_finding(),),
            model_version="m",
            prompt_version="security-v1",
        )
        assert adapter.get_findings("h", "security") is not None

        adapter.set_prompt_version("security", "security-v2")
        assert adapter.get_findings("h", "security") is None

    def test_invalidation_on_schema_version_mismatch(
        self,
        adapter: SqliteCacheAdapter,
    ):
        adapter.set_model_version("m")
        adapter.set_prompt_version("security", "p")
        adapter.put_findings(
            file_hash="h",
            dimension="security",
            findings=(_make_finding(),),
            model_version="m",
            prompt_version="p",
        )
        assert adapter.get_findings("h", "security") is not None

        adapter.set_schema_version("v2")
        assert adapter.get_findings("h", "security") is None


# ── Clear ──────────────────────────────────────────────────────


def _prime_versions(adapter: SqliteCacheAdapter) -> None:
    """Configure the adapter so subsequent put/get round-trip cleanly."""
    adapter.set_model_version("m")
    for dim in ("security", "quality", "performance", "architecture"):
        adapter.set_prompt_version(dim, "p")  # type: ignore[arg-type]


class TestClear:
    def test_clear_specific_repo_returns_count(
        self,
        adapter: SqliteCacheAdapter,
    ):
        _prime_versions(adapter)
        sig_a = adapter.compute_repo_signature(("a.py", "b.py"))
        sig_b = adapter.compute_repo_signature(("c.py",))
        adapter.set_repo_signature(sig_a)
        adapter.put_findings("h1", "security", (_make_finding(),), "m", "p")
        adapter.put_findings("h2", "quality", (_make_finding(),), "m", "p")
        adapter.set_repo_signature(sig_b)
        adapter.put_findings("h3", "security", (_make_finding(),), "m", "p")

        removed = adapter.clear(repo_signature=sig_a)

        assert removed == 2
        adapter.set_repo_signature(sig_b)
        assert adapter.get_findings("h3", "security") is not None

    def test_clear_all_returns_total_count(self, adapter: SqliteCacheAdapter):
        _prime_versions(adapter)
        adapter.put_findings("h1", "security", (_make_finding(),), "m", "p")
        adapter.put_findings("h2", "quality", (_make_finding(),), "m", "p")
        adapter.put_findings("h3", "performance", (_make_finding(),), "m", "p")

        removed = adapter.clear(repo_signature=None)

        assert removed == 3
        assert adapter.get_findings("h1", "security") is None


# ── Stats ──────────────────────────────────────────────────────


class TestStats:
    def test_stats_reports_aggregate(self, adapter: SqliteCacheAdapter):
        sig = adapter.compute_repo_signature(("a.py",))
        adapter.set_repo_signature(sig)
        adapter.put_findings("h1", "security", (_make_finding(),), "m", "p")
        adapter.put_findings("h2", "quality", (_make_finding(),), "m", "p")

        stats = adapter.stats()

        assert isinstance(stats, CacheStats)
        assert stats.total_entries == 2
        assert stats.total_repos == 1
        assert stats.db_size_bytes > 0

    def test_stats_empty_cache(self, adapter: SqliteCacheAdapter):
        stats = adapter.stats()
        assert stats.total_entries == 0
        assert stats.total_repos == 0
        assert stats.oldest_entry_at is None


# ── Repo signature ─────────────────────────────────────────────


class TestRepoSignature:
    def test_compute_repo_signature_deterministic(
        self,
        adapter: SqliteCacheAdapter,
    ):
        tree = ("src/main.py", "tests/test_main.py", "README.md")
        sig1 = adapter.compute_repo_signature(tree)
        sig2 = adapter.compute_repo_signature(tree)
        assert sig1 == sig2
        assert isinstance(sig1, str)
        assert len(sig1) == 32  # blake2b digest_size=16 → 32 hex chars

    def test_compute_repo_signature_changes_with_tree(
        self,
        adapter: SqliteCacheAdapter,
    ):
        sig_a = adapter.compute_repo_signature(("a.py", "b.py"))
        sig_b = adapter.compute_repo_signature(("a.py", "c.py"))
        assert sig_a != sig_b


# ── I/O failure → SPEC-010 ─────────────────────────────────────


class TestIoFailure:
    def test_io_failure_raises_spec_010(self, tmp_path: Path):
        # Force put against a closed connection by pointing at a path the
        # OS will refuse — a directory used as a file.
        bad_path = tmp_path / "is_a_dir"
        bad_path.mkdir()
        with pytest.raises(AgentError) as exc_info:
            SqliteCacheAdapter(db_path=bad_path)
        assert exc_info.value.error.code == "SPEC-010"


# ── Schema version constant ────────────────────────────────────


class TestSchemaVersionConstant:
    def test_schema_version_is_v1(self):
        assert SCHEMA_VERSION == "v1"


# ── Full-report storage (Phase 2) ──────────────────────────────


def _scorecard(overall: float = 80.0) -> ScoreCard:
    """Build a minimal ScoreCard so we can construct AnalysisReport in tests."""
    dim = DimensionScore(
        dimension="security",
        score=overall,
        grade=score_to_grade(overall),
        findings_count=0,
        weight=1.0,
    )
    return ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=(dim,),
        total_findings=0,
    )


def _report(repo_url: str = "https://github.com/test/repo") -> AnalysisReport:
    return AnalysisReport(
        repo_url=repo_url,
        repo_name="repo",
        score_card=_scorecard(),
        findings=(_make_finding(),),
        analysis_duration_seconds=12.3,
        total_tokens_used=1234,
        total_cost_usd=0.01,
        agents_used=("security",),
    )


def _key(**overrides: object) -> RepoCacheKey:
    base: dict[str, object] = {
        "repo_signature": "deadbeefdeadbeefdeadbeefdeadbeef",
        "spectra_version": "0.1.0",
        "model_versions": "claude-opus-4-7|claude-opus-4-7",
        "prompt_versions": "prompt-hash-v1",
        "schema_version": "v1",
    }
    base.update(overrides)
    return RepoCacheKey(**base)  # type: ignore[arg-type]


class TestFullReportRoundTrip:
    def test_full_report_round_trip(self, adapter: SqliteCacheAdapter):
        key = _key()
        report = _report()
        adapter.put_full_report(key, report)
        loaded = adapter.get_full_report(key)
        assert loaded == report

    def test_full_report_miss_returns_none(self, adapter: SqliteCacheAdapter):
        assert adapter.get_full_report(_key()) is None

    def test_full_report_invalidates_on_spectra_version(self, adapter: SqliteCacheAdapter):
        adapter.put_full_report(_key(), _report())
        assert adapter.get_full_report(_key(spectra_version="0.2.0")) is None

    def test_full_report_invalidates_on_model_version(self, adapter: SqliteCacheAdapter):
        adapter.put_full_report(_key(), _report())
        bumped = _key(model_versions="claude-opus-5-0|claude-opus-5-0")
        assert adapter.get_full_report(bumped) is None

    def test_full_report_invalidates_on_prompt_version(self, adapter: SqliteCacheAdapter):
        adapter.put_full_report(_key(), _report())
        assert adapter.get_full_report(_key(prompt_versions="other-hash")) is None

    def test_full_report_invalidates_on_schema_version(self, adapter: SqliteCacheAdapter):
        adapter.put_full_report(_key(), _report())
        assert adapter.get_full_report(_key(schema_version="v2")) is None

    def test_full_report_invalidates_on_repo_signature(self, adapter: SqliteCacheAdapter):
        adapter.put_full_report(_key(), _report())
        assert adapter.get_full_report(_key(repo_signature="00000000")) is None

    def test_put_overwrites_same_key(self, adapter: SqliteCacheAdapter):
        adapter.put_full_report(_key(), _report(repo_url="https://github.com/old/old"))
        adapter.put_full_report(_key(), _report(repo_url="https://github.com/new/new"))
        loaded = adapter.get_full_report(_key())
        assert loaded is not None
        assert loaded.repo_url == "https://github.com/new/new"


# ── Phase 3: per-batch findings + hit_log ──────────────────────


def _batch_key(**overrides: object) -> BatchCacheKey:
    base: dict[str, object] = {
        "batch_id": "batch-1",
        "dimension": "security",
        "model_version": "claude-opus-4-7",
        "prompt_version": "prompt-hash-v1",
        "schema_version": "v1",
        "spectra_version": "0.2.0",
    }
    base.update(overrides)
    return BatchCacheKey(**base)  # type: ignore[arg-type]


def _bind_default_context(adapter: SqliteCacheAdapter) -> None:
    """Bind a default run context so subsequent get/put calls scope correctly."""
    adapter.bind_run_context(
        model_versions="claude-opus-4-7",
        prompt_versions="prompt-hash-v1",
        schema_version="v1",
        spectra_version="0.2.0",
    )


class TestPhase3Schema:
    def test_init_schema_creates_findings_cache_and_hit_log_tables(
        self,
        cache_path: Path,
    ):
        SqliteCacheAdapter(db_path=cache_path)
        with sqlite3.connect(str(cache_path)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "findings_cache" in tables
        assert "hit_log" in tables

    def test_phase_2_full_report_still_works_after_phase_3_schema_extension(
        self,
        adapter: SqliteCacheAdapter,
    ):
        # Backward compat: full_report_cache survives the new tables.
        adapter.put_full_report(_key(), _report())
        assert adapter.get_full_report(_key()) is not None


class TestBindRunContext:
    def test_bind_run_context_is_atomic(self, adapter: SqliteCacheAdapter):
        adapter.bind_run_context(
            model_versions="claude-opus-4-7",
            prompt_versions="prompt-hash-v1",
            schema_version="v1",
            spectra_version="0.2.0",
        )
        # Atomic: a single call configures every dimension's lookup.
        adapter.put_batch_findings(_batch_key(), (_make_finding(),))
        assert adapter.get_batch_findings(_batch_key()) is not None


class TestBatchFindingsRoundTrip:
    def test_get_batch_findings_round_trip(self, adapter: SqliteCacheAdapter):
        _bind_default_context(adapter)
        findings = (_make_finding(), _make_finding(line=99, fid="F-002"))
        adapter.put_batch_findings(_batch_key(), findings)
        assert adapter.get_batch_findings(_batch_key()) == findings

    def test_get_batch_findings_miss_returns_none(
        self,
        adapter: SqliteCacheAdapter,
    ):
        _bind_default_context(adapter)
        assert adapter.get_batch_findings(_batch_key()) is None


class TestBatchInvalidation:
    def test_invalidation_on_model_version_change(
        self,
        adapter: SqliteCacheAdapter,
    ):
        _bind_default_context(adapter)
        adapter.put_batch_findings(_batch_key(), (_make_finding(),))
        bumped = _batch_key(model_version="claude-opus-5-0")
        assert adapter.get_batch_findings(bumped) is None

    def test_invalidation_on_prompt_version_change(
        self,
        adapter: SqliteCacheAdapter,
    ):
        # Critique-prompt edits hash through into prompt_version.
        _bind_default_context(adapter)
        adapter.put_batch_findings(_batch_key(), (_make_finding(),))
        bumped = _batch_key(prompt_version="prompt-hash-v2-after-critique-edit")
        assert adapter.get_batch_findings(bumped) is None

    def test_invalidation_on_schema_version_change(
        self,
        adapter: SqliteCacheAdapter,
    ):
        _bind_default_context(adapter)
        adapter.put_batch_findings(_batch_key(), (_make_finding(),))
        assert adapter.get_batch_findings(_batch_key(schema_version="v2")) is None

    def test_invalidation_on_spectra_version_change(
        self,
        adapter: SqliteCacheAdapter,
    ):
        _bind_default_context(adapter)
        adapter.put_batch_findings(_batch_key(), (_make_finding(),))
        bumped = _batch_key(spectra_version="0.3.0")
        assert adapter.get_batch_findings(bumped) is None


class TestHitLogTelemetry:
    def test_record_hit_appends_to_hit_log(self, adapter: SqliteCacheAdapter, cache_path: Path):
        adapter.record_hit("security", "batch-1", hit=True)
        adapter.record_hit("security", "batch-1", hit=False)
        with sqlite3.connect(str(cache_path)) as conn:
            rows = conn.execute("SELECT hit FROM hit_log").fetchall()
        assert len(rows) == 2

    def test_record_hit_does_not_slow_get(
        self,
        adapter: SqliteCacheAdapter,
    ):
        # Perf smoke: a typical lookup must stay under 5ms even when hit_log is written.
        import time as _time

        _bind_default_context(adapter)
        adapter.put_batch_findings(_batch_key(), (_make_finding(),))
        start = _time.perf_counter()
        adapter.get_batch_findings(_batch_key())
        adapter.record_hit("security", "batch-1", hit=True)
        elapsed = _time.perf_counter() - start
        assert elapsed < 0.005

    def test_stats_hit_rate_last_100_reads_from_hit_log(
        self,
        adapter: SqliteCacheAdapter,
    ):
        for _ in range(60):
            adapter.record_hit("security", "b", hit=True)
        for _ in range(40):
            adapter.record_hit("security", "b", hit=False)
        stats = adapter.stats()
        assert abs(stats.hit_rate_last_100 - 0.6) < 0.01

    def test_stats_hit_rate_last_100_zero_when_no_log_entries(
        self,
        adapter: SqliteCacheAdapter,
    ):
        stats = adapter.stats()
        assert stats.hit_rate_last_100 == 0.0


# ── Phase 4: hit_log dimension/batch_id migration ──────────────


class TestHitLogSchemaMigration:
    def test_hit_log_schema_has_dimension_and_batch_id_columns(
        self,
        cache_path: Path,
    ):
        """hit_log gains dimension + batch_id columns at fresh-install time."""
        SqliteCacheAdapter(db_path=cache_path)
        with sqlite3.connect(str(cache_path)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(hit_log)")}
        assert "dimension" in cols
        assert "batch_id" in cols

    def test_record_hit_persists_dimension_and_batch_id(
        self,
        adapter: SqliteCacheAdapter,
        cache_path: Path,
    ):
        """record_hit writes dimension and batch_id, not just (ts, hit)."""
        adapter.record_hit("security", "batch-42", hit=True)
        adapter.record_hit("quality", "batch-99", hit=False)
        with sqlite3.connect(str(cache_path)) as conn:
            rows = conn.execute(
                "SELECT dimension, batch_id, hit FROM hit_log ORDER BY ts"
            ).fetchall()
        assert rows[0] == ("security", "batch-42", 1)
        assert rows[1] == ("quality", "batch-99", 0)

    def test_hit_log_existing_rows_default_to_empty_strings_after_migration(
        self,
        cache_path: Path,
    ):
        """Pre-Phase-4 hit_log rows survive the ALTER TABLE migration."""
        # Simulate a Phase 3 install: create the table with the OLD shape
        # BEFORE the adapter touches the DB.
        with sqlite3.connect(str(cache_path)) as conn:
            conn.execute(
                "CREATE TABLE hit_log (ts TIMESTAMP NOT NULL, hit INTEGER NOT NULL)"
            )
            conn.execute(
                "INSERT INTO hit_log (ts, hit) VALUES (?, ?)",
                ("2026-01-01T00:00:00+00:00", 1),
            )
            conn.commit()
        # The adapter must run an ALTER TABLE migration and tolerate the
        # legacy row, defaulting its dimension/batch_id to "".
        SqliteCacheAdapter(db_path=cache_path)
        with sqlite3.connect(str(cache_path)) as conn:
            rows = conn.execute(
                "SELECT dimension, batch_id, hit FROM hit_log"
            ).fetchall()
        assert rows == [("", "", 1)]


# ── Phase 4: clear_all / clear_by_repo / prune_older_than ──────


def _bind_and_seed(adapter: SqliteCacheAdapter, sig: str = "sig-a") -> None:
    """Seed every cache table for the given repo signature."""
    _bind_default_context(adapter)
    adapter.set_repo_signature(sig)
    adapter.set_model_version("m")
    adapter.set_prompt_version("security", "p")
    adapter.put_findings("h1", "security", (_make_finding(),), "m", "p")
    adapter.put_full_report(_key(repo_signature=sig), _report())
    adapter.put_batch_findings(_batch_key(), (_make_finding(),))
    adapter.record_hit("security", "batch-1", hit=True)


class TestClearAll:
    def test_clear_all_deletes_all_cache_tables_and_returns_count(
        self,
        adapter: SqliteCacheAdapter,
        cache_path: Path,
    ):
        _bind_and_seed(adapter)
        removed = adapter.clear_all()
        # 1 findings_cache + 1 full_report_cache + 1 findings_batches + 1 hit_log
        assert removed == 4
        with sqlite3.connect(str(cache_path)) as conn:
            for table in (
                "findings_cache",
                "full_report_cache",
                "findings_batches",
                "hit_log",
            ):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                assert count == 0, f"{table} not cleared"

    def test_clear_all_does_not_drop_schema(
        self,
        adapter: SqliteCacheAdapter,
        cache_path: Path,
    ):
        _bind_and_seed(adapter)
        adapter.clear_all()
        # Tables must still exist after clear_all (DELETE not DROP).
        with sqlite3.connect(str(cache_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        for required in (
            "findings_cache",
            "full_report_cache",
            "findings_batches",
            "hit_log",
        ):
            assert required in tables


class TestClearByRepo:
    def test_clear_by_repo_deletes_only_matching_rows(
        self,
        adapter: SqliteCacheAdapter,
    ):
        sig_a = adapter.compute_repo_signature(("a.py",))
        sig_b = adapter.compute_repo_signature(("b.py",))
        adapter.set_model_version("m")
        adapter.set_prompt_version("security", "p")
        adapter.set_repo_signature(sig_a)
        adapter.put_findings("h1", "security", (_make_finding(),), "m", "p")
        adapter.put_full_report(_key(repo_signature=sig_a), _report())
        adapter.set_repo_signature(sig_b)
        adapter.put_findings("h2", "security", (_make_finding(),), "m", "p")
        adapter.put_full_report(_key(repo_signature=sig_b), _report())

        removed = adapter.clear_by_repo(sig_a)

        # 1 findings_cache row + 1 full_report_cache row for sig_a
        assert removed == 2
        # sig_b rows untouched
        adapter.set_repo_signature(sig_b)
        assert adapter.get_findings("h2", "security") is not None

    def test_clear_by_repo_returns_zero_for_unknown_signature(
        self,
        adapter: SqliteCacheAdapter,
    ):
        removed = adapter.clear_by_repo("never-seen-this-sig")
        assert removed == 0


# ── Phase 4: prune_older_than ─────────────────────────────────


def _set_row_age(cache_path: Path, table: str, age_iso: str) -> None:
    """Backdate every row's computed_at column to a specific timestamp."""
    with sqlite3.connect(str(cache_path)) as conn:
        # Test helper — table comes from a hard-coded literal at the call site.
        conn.execute(f"UPDATE {table} SET computed_at = ?", (age_iso,))  # noqa: S608
        conn.commit()


def _set_hit_log_age(cache_path: Path, age_iso: str) -> None:
    with sqlite3.connect(str(cache_path)) as conn:
        conn.execute("UPDATE hit_log SET ts = ?", (age_iso,))
        conn.commit()


class TestPruneOlderThan:
    def test_prune_older_than_deletes_old_entries(
        self,
        adapter: SqliteCacheAdapter,
        cache_path: Path,
    ):

        _bind_and_seed(adapter)
        # Backdate findings_cache + full_report_cache + findings_batches to ancient.
        old = "2020-01-01T00:00:00+00:00"
        _set_row_age(cache_path, "findings_cache", old)
        _set_row_age(cache_path, "full_report_cache", old)
        _set_row_age(cache_path, "findings_batches", old)

        cutoff = datetime.now(UTC) - timedelta(days=30)
        deleted = adapter.prune_older_than(cutoff)

        assert deleted["findings_cache"] == 1
        assert deleted["full_report_cache"] == 1
        assert deleted["findings_batches"] == 1

    def test_prune_older_than_does_not_delete_recent_entries(
        self,
        adapter: SqliteCacheAdapter,
    ):

        _bind_and_seed(adapter)
        cutoff = datetime.now(UTC) - timedelta(days=30)
        deleted = adapter.prune_older_than(cutoff)
        # Just-seeded rows are younger than 30 days; nothing should drop.
        assert deleted["findings_cache"] == 0
        assert deleted["full_report_cache"] == 0
        assert deleted["findings_batches"] == 0

    def test_prune_older_than_excludes_hit_log_by_default(
        self,
        adapter: SqliteCacheAdapter,
        cache_path: Path,
    ):

        _bind_and_seed(adapter)
        _set_hit_log_age(cache_path, "2020-01-01T00:00:00+00:00")

        cutoff = datetime.now(UTC) - timedelta(days=30)
        deleted = adapter.prune_older_than(cutoff)

        assert "hit_log" not in deleted
        with sqlite3.connect(str(cache_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM hit_log").fetchone()[0]
        assert count == 1

    def test_prune_older_than_with_include_hit_log_drops_old_telemetry(
        self,
        adapter: SqliteCacheAdapter,
        cache_path: Path,
    ):

        _bind_and_seed(adapter)
        _set_hit_log_age(cache_path, "2020-01-01T00:00:00+00:00")

        cutoff = datetime.now(UTC) - timedelta(days=30)
        deleted = adapter.prune_older_than(cutoff, include_hit_log=True)

        assert deleted["hit_log"] == 1
        with sqlite3.connect(str(cache_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM hit_log").fetchone()[0]
        assert count == 0


# ── Phase 4: extended stats() breakdown ────────────────────────


class TestStatsExtendedBreakdown:
    def test_stats_reports_extended_breakdowns(
        self,
        adapter: SqliteCacheAdapter,
    ):
        _bind_and_seed(adapter)
        stats = adapter.stats()
        assert stats.full_report_entries == 1
        assert stats.batch_entries == 1
        assert stats.hit_log_entries == 1
        # most_recent_activity_at should be set after a put.
        assert stats.most_recent_activity_at is not None

    def test_stats_per_dimension_hit_rate_with_60_hits_40_misses_returns_0_6_for_that_dim(
        self,
        adapter: SqliteCacheAdapter,
    ):
        for _ in range(60):
            adapter.record_hit("security", "b", hit=True)
        for _ in range(40):
            adapter.record_hit("security", "b", hit=False)
        stats = adapter.stats()
        assert abs(stats.hit_rate_by_dimension["security"] - 0.6) < 0.01

    def test_stats_per_dimension_excludes_other_dimensions_lookups(
        self,
        adapter: SqliteCacheAdapter,
    ):
        # Security: all hits.
        for _ in range(10):
            adapter.record_hit("security", "b", hit=True)
        # Quality: all misses.
        for _ in range(10):
            adapter.record_hit("quality", "b", hit=False)
        stats = adapter.stats()
        assert stats.hit_rate_by_dimension["security"] == 1.0
        assert stats.hit_rate_by_dimension["quality"] == 0.0
