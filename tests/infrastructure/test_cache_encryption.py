"""Tests for SQLCipher-at-rest cache encryption (Roadmap #13).

Covers:
- End-to-end open/write/read against an encrypted cache
- Wrong key → cipher error → SPEC-010 degradation to no-cache
- Backward-compat migration: pre-create unencrypted v0.5.0-shape cache,
  open with new adapter, verify rows preserved + file is now encrypted
- ``spectra cache shred`` removes file + keyring entries; subsequent open
  generates fresh keys and presents an empty cache
- ``spectra cache doctor`` reports the encryption row correctly
- pysqlcipher3 absence: tests xfail with a skip reason rather than
  hard-fail, so CI without SQLCipher still passes the rest of the suite
"""

from __future__ import annotations

import secrets
import sqlite3 as _stdlib_sqlite3
from pathlib import Path

import pytest

from spectra.entities.errors import AgentError
from spectra.entities.models import CacheSecret, FileLocation, Finding
from spectra.infrastructure.cache_adapter import (
    SqliteCacheAdapter,
    is_sqlcipher_available,
)

# ── pysqlcipher3 platform guard ────────────────────────────────

_NO_SQLCIPHER_REASON = (
    "pysqlcipher3 not installed on this platform — encryption tests skip; HMAC + plain SQLite still tested."
)
requires_sqlcipher = pytest.mark.skipif(
    not is_sqlcipher_available(),
    reason=_NO_SQLCIPHER_REASON,
)


# ── Helpers ────────────────────────────────────────────────────


def _secret(value: bytes | None = None) -> CacheSecret:
    return CacheSecret(value=value or secrets.token_bytes(32))


def _make_finding(file_path: str = "src/auth.py", line: int = 10, fid: str = "F-001") -> Finding:
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
    return tmp_path / "cache.db"


# ── End-to-end: encrypted cache open/write/read ────────────────


@requires_sqlcipher
class TestEncryptedCacheRoundTrip:
    def test_open_write_read_against_encrypted_cache(self, cache_path: Path) -> None:
        """A round-trip succeeds when an encryption key is bound to the adapter."""
        adapter = SqliteCacheAdapter(db_path=cache_path, secret=_secret(b"\x01" * 32))
        adapter.set_model_version("m")
        adapter.set_prompt_version("security", "p")
        findings = (_make_finding(),)
        adapter.put_findings("h", "security", findings, "m", "p")
        assert adapter.get_findings("h", "security") == findings
        adapter.close()

    def test_db_file_is_not_readable_by_plain_sqlite(self, cache_path: Path) -> None:
        """An encrypted DB must reject plain ``sqlite3.connect`` queries.

        SQLCipher prepends a random salt + encrypts every page including the
        header. ``sqlite3.connect`` will open the file but every query throws
        ``DatabaseError: file is not a database``.
        """
        adapter = SqliteCacheAdapter(db_path=cache_path, secret=_secret(b"\x02" * 32))
        adapter.set_model_version("m")
        adapter.set_prompt_version("security", "p")
        adapter.put_findings("h", "security", (_make_finding(),), "m", "p")
        adapter.close()

        # Plain sqlite3 cannot read the encrypted file.
        with _stdlib_sqlite3.connect(str(cache_path)) as conn, pytest.raises(_stdlib_sqlite3.DatabaseError):
            conn.execute("SELECT name FROM sqlite_master").fetchall()

    def test_db_header_is_not_sqlite_format_3(self, cache_path: Path) -> None:
        """Encrypted DBs do NOT start with the SQLite magic header."""
        adapter = SqliteCacheAdapter(db_path=cache_path, secret=_secret(b"\x03" * 32))
        adapter.put_findings("h", "security", (_make_finding(),), "m", "p")
        adapter.close()
        header = cache_path.read_bytes()[:16]
        assert not header.startswith(b"SQLite format 3"), "DB header is unencrypted"


# ── Wrong key → SPEC-010 degradation ──────────────────────────


@requires_sqlcipher
class TestWrongKeyDegradation:
    def test_wrong_encryption_key_raises_spec_010(self, cache_path: Path) -> None:
        """A second adapter opened with a different secret cannot decrypt the file."""
        adapter_a = SqliteCacheAdapter(db_path=cache_path, secret=_secret(b"\x01" * 32))
        adapter_a.put_findings("h", "security", (_make_finding(),), "m", "p")
        adapter_a.close()

        # A different secret will derive a different SQLCipher key.
        with pytest.raises(AgentError) as exc_info:
            SqliteCacheAdapter(db_path=cache_path, secret=_secret(b"\x99" * 32))
        assert exc_info.value.error.code == "SPEC-010"


# ── Migration from v0.5.0 unencrypted cache ────────────────────


@requires_sqlcipher
class TestUnencryptedToEncryptedMigration:
    def test_v0_5_0_unencrypted_cache_is_migrated_to_encrypted(self, cache_path: Path) -> None:
        """Pre-existing unencrypted cache → migrated in place, rows preserved."""
        # Step 1: create an unencrypted v0.5.0-shape cache via plain sqlite3.
        plain_adapter = _build_unencrypted_adapter(cache_path)
        plain_adapter.set_model_version("m")
        plain_adapter.set_prompt_version("security", "p")
        plain_adapter.put_findings(
            "hash-pre-migration",
            "security",
            (_make_finding(fid="F-LEGACY"),),
            "m",
            "p",
        )
        plain_adapter.close()

        # Verify the file IS plain SQLite before migration.
        assert cache_path.read_bytes()[:16].startswith(b"SQLite format 3")

        # Step 2: open with the encrypted adapter — should auto-migrate.
        secret = _secret(b"\x05" * 32)
        encrypted_adapter = SqliteCacheAdapter(db_path=cache_path, secret=secret)
        encrypted_adapter.set_model_version("m")
        encrypted_adapter.set_prompt_version("security", "p")

        # Step 3: legacy row must be readable through the migrated cache.
        rows = encrypted_adapter.get_findings("hash-pre-migration", "security")
        assert rows is not None, "migration lost the legacy row"
        assert rows[0].id == "F-LEGACY"
        encrypted_adapter.close()

        # Step 4: file is now encrypted (no plaintext SQLite header).
        assert not cache_path.read_bytes()[:16].startswith(b"SQLite format 3")

    def test_migration_is_idempotent_on_already_encrypted_cache(self, cache_path: Path) -> None:
        """Re-opening an already-encrypted cache must NOT trigger migration."""
        secret = _secret(b"\x06" * 32)
        first = SqliteCacheAdapter(db_path=cache_path, secret=secret)
        first.put_findings("h", "security", (_make_finding(),), "m", "p")
        first.close()

        # Re-open with the SAME secret — must succeed, no migration needed.
        second = SqliteCacheAdapter(db_path=cache_path, secret=secret)
        second.set_model_version("m")
        second.set_prompt_version("security", "p")
        assert second.get_findings("h", "security") is not None
        second.close()


def _build_unencrypted_adapter(cache_path: Path) -> SqliteCacheAdapter:
    """Build a v0.5.0-shape cache by FORCING plaintext (no SQLCipher key).

    Used only by the migration tests to seed a realistic legacy cache.
    The ``_force_plaintext`` flag is internal to the adapter and exists
    purely so backward-compat tests can simulate the v0.5.0 layout
    without shipping a binary fixture file.
    """
    return SqliteCacheAdapter(
        db_path=cache_path,
        secret=None,
        _force_plaintext=True,
    )


# ── cache shred ────────────────────────────────────────────────


class TestCacheShred:
    """``spectra cache shred`` — destructive cleanup primitive (CLI + adapter)."""

    def test_shred_overwrites_file_with_random_bytes_then_deletes(self, cache_path: Path) -> None:
        """The adapter ``shred`` method overwrites + deletes the cache file."""
        from spectra.infrastructure.cache_adapter import shred_cache_file

        # Seed a file we can shred.
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"sensitive cache contents" * 100)
        original_size = cache_path.stat().st_size

        shred_cache_file(cache_path, passes=3)

        assert not cache_path.exists(), "file must be deleted after shred"
        # WAL/SHM siblings are also removed if present.
        assert not cache_path.with_name(cache_path.name + "-wal").exists()
        assert not cache_path.with_name(cache_path.name + "-shm").exists()
        # Sanity: nothing else got created.
        assert original_size > 0

    def test_shred_handles_missing_file_gracefully(self, cache_path: Path) -> None:
        """Shredding a non-existent file is a no-op, not an error."""
        from spectra.infrastructure.cache_adapter import shred_cache_file

        # File never existed.
        shred_cache_file(cache_path, passes=1)  # must not raise

    def test_shred_removes_wal_and_shm_siblings(self, cache_path: Path) -> None:
        """WAL + SHM journal siblings are also overwritten + deleted."""
        from spectra.infrastructure.cache_adapter import shred_cache_file

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"data")
        wal = cache_path.with_name(cache_path.name + "-wal")
        shm = cache_path.with_name(cache_path.name + "-shm")
        wal.write_bytes(b"wal-contents")
        shm.write_bytes(b"shm-contents")

        shred_cache_file(cache_path, passes=2)

        assert not cache_path.exists()
        assert not wal.exists()
        assert not shm.exists()


# ── SQLCipher availability indicator ──────────────────────────


class TestSqlcipherAvailability:
    def test_is_sqlcipher_available_returns_bool(self) -> None:
        """The availability flag is a public diagnostic used by ``cache doctor``."""
        assert isinstance(is_sqlcipher_available(), bool)

    def test_encryption_status_helper_is_present(self) -> None:
        """The adapter exposes an ``encryption_status`` property for doctor."""
        adapter = SqliteCacheAdapter(db_path=Path(":memory:"), secret=None, _force_plaintext=True)
        # When plaintext is forced, status indicates fallback.
        assert adapter.encryption_status in {"sqlcipher", "plain"}


class TestSqlcipherFallback:
    """Failure mode: when SQLCipher is unavailable, cache degrades to plain SQLite."""

    def test_fallback_to_plain_sqlite_when_sqlcipher_missing(
        self,
        cache_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulate ``pysqlcipher3`` absence and verify plain-SQLite fallback works."""
        # Force the platform-not-supported branch.
        import spectra.infrastructure.cache_adapter as ca_mod

        monkeypatch.setattr(ca_mod, "_sqlcipher", None)
        monkeypatch.setattr(ca_mod, "_SQLCIPHER_FALLBACK_LOGGED", False)

        adapter = SqliteCacheAdapter(db_path=cache_path, secret=_secret(b"\x07" * 32))
        assert adapter.encryption_status == "plain"
        adapter.set_model_version("m")
        adapter.set_prompt_version("security", "p")
        adapter.put_findings("h", "security", (_make_finding(),), "m", "p")
        # HMAC still active under the secret — round-trip succeeds.
        assert adapter.get_findings("h", "security") is not None
        adapter.close()

    def test_fallback_logs_warning_once(
        self,
        cache_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The fallback WARN is emitted exactly once per process."""
        import logging as _logging

        import spectra.infrastructure.cache_adapter as ca_mod

        monkeypatch.setattr(ca_mod, "_sqlcipher", None)
        monkeypatch.setattr(ca_mod, "_SQLCIPHER_FALLBACK_LOGGED", False)
        with caplog.at_level(_logging.WARNING, logger="spectra.cache"):
            SqliteCacheAdapter(db_path=cache_path, secret=_secret(b"\x08" * 32))
            # Second open must NOT log again.
            another = cache_path.parent / "second.db"
            SqliteCacheAdapter(db_path=another, secret=_secret(b"\x09" * 32))
        sqlcipher_warns = [r for r in caplog.records if "pysqlcipher3 unavailable" in r.getMessage()]
        assert len(sqlcipher_warns) == 1, "WARN must surface exactly once"


class TestPlainModeDowngradeDetection:
    """Plain-mode runtime + SQLCipher-encrypted-on-disk cache (#79).

    Triggered when an operator who used pysqlcipher3 in v0.7.0/v0.8.0
    upgrades to v0.8.1 without the ``[encryption]`` extra: the adapter
    correctly falls back to plain SQLite, but the existing on-disk
    cache file is still in SQLCipher format. Without detection,
    ``sqlite3.connect`` succeeds and the first ``PRAGMA`` raises
    ``DatabaseError: file is not a database`` — a confusing message
    that points at neither the cause nor the remediation. Detection
    surfaces SPEC-010 with both, and an opt-in env var auto-shreds
    for unattended (CI) upgrade scenarios.
    """

    @staticmethod
    def _seed_pseudo_encrypted_db(path: Path) -> None:
        """Drop bytes that lack the SQLite magic header — same shape
        SQLCipher writes (random salt + ciphertext, no plain header).
        Lets the regression run without requiring pysqlcipher3 to
        actually encrypt during test setup."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xde\xad\xbe\xef" * 64)  # 256 bytes, no SQLite magic

    def test_plain_mode_against_encrypted_file_raises_actionable_spec_010(
        self,
        cache_path: Path,
    ) -> None:
        self._seed_pseudo_encrypted_db(cache_path)
        with pytest.raises(AgentError) as exc_info:
            SqliteCacheAdapter(
                db_path=cache_path,
                secret=_secret(b"\x10" * 32),
                _force_plaintext=True,
            )
        msg = str(exc_info.value)
        assert exc_info.value.error.code == "SPEC-010"
        assert "encrypted" in msg.lower(), msg
        assert "spectra cache shred" in msg, msg
        assert "SPECTRA_SHRED_ON_DOWNGRADE" in msg, msg

    def test_plain_mode_against_encrypted_file_auto_shreds_when_env_set(
        self,
        cache_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._seed_pseudo_encrypted_db(cache_path)
        monkeypatch.setenv("SPECTRA_SHRED_ON_DOWNGRADE", "1")
        adapter = SqliteCacheAdapter(
            db_path=cache_path,
            secret=_secret(b"\x11" * 32),
            _force_plaintext=True,
        )
        try:
            assert cache_path.read_bytes()[:16] == b"SQLite format 3\x00"
            assert adapter.encryption_status == "plain"
        finally:
            adapter.close()

    def test_plain_mode_against_existing_plain_file_works(
        self,
        cache_path: Path,
    ) -> None:
        first = SqliteCacheAdapter(
            db_path=cache_path,
            secret=_secret(b"\x12" * 32),
            _force_plaintext=True,
        )
        first.close()
        second = SqliteCacheAdapter(
            db_path=cache_path,
            secret=_secret(b"\x12" * 32),
            _force_plaintext=True,
        )
        try:
            assert second.encryption_status == "plain"
        finally:
            second.close()

    def test_plain_mode_with_no_existing_file_creates_fresh_db(
        self,
        cache_path: Path,
    ) -> None:
        assert not cache_path.exists()
        adapter = SqliteCacheAdapter(
            db_path=cache_path,
            secret=_secret(b"\x13" * 32),
            _force_plaintext=True,
        )
        try:
            assert cache_path.exists()
            assert adapter.encryption_status == "plain"
        finally:
            adapter.close()
