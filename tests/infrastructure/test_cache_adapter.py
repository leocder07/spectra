"""Tests for the SQLite cache adapter (Phase 1).

Covers schema initialization, round-trip serialization, fine-grained
invalidation by model/prompt/schema version, repo signature determinism,
WAL mode for concurrent reads, and SPEC-010 fault handling.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from spectra.entities.errors import AgentError
from spectra.entities.models import (
    CacheStats,
    FileLocation,
    Finding,
)
from spectra.infrastructure.cache_adapter import (
    SCHEMA_VERSION,
    SqliteCacheAdapter,
)


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
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
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
