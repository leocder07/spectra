"""CLI tests for ``spectra cache shred`` and the cache doctor encryption row."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from spectra.adapters.cli_controller import (
    app,
    set_cache_provider,
    set_shred_executor,
)

runner = CliRunner()


# ── Stub cache port (mirrors the one in test_cli_controller) ──


class _StubCachePortForShred:
    """Minimal CachePort surface used by the shred + doctor command tests."""

    def __init__(self, *, encryption_status: str = "sqlcipher") -> None:
        self._db_path = Path("/tmp/cache.db")  # noqa: S108
        self._encryption_status = encryption_status
        self.close_called = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def has_secret(self) -> bool:
        return True

    @property
    def encryption_status(self) -> str:
        return self._encryption_status

    def count_rows(self) -> dict[str, dict[str, int]]:
        return {
            "findings_cache": {"total": 0, "verified": 0, "failed": 0},
            "full_report_cache": {"total": 0, "verified": 0, "failed": 0},
            "findings_batches": {"total": 0, "verified": 0, "failed": 0},
        }

    def close(self) -> None:
        self.close_called = True


# ── cache shred ────────────────────────────────────────────────


class TestCacheShredCommand:
    def test_shred_yes_flag_skips_prompt_and_invokes_executor(self) -> None:
        """``--yes`` skips the confirmation prompt and shreds immediately."""
        port = _StubCachePortForShred()
        set_cache_provider(lambda: port)
        calls: list[Path] = []

        def _executor() -> Path:
            shredded = Path("/tmp/cache.db")  # noqa: S108
            calls.append(shredded)
            return shredded

        set_shred_executor(_executor)
        result = runner.invoke(app, ["cache", "shred", "--yes"])
        assert result.exit_code == 0, result.output
        assert calls, "executor must run when --yes is passed"
        # Output reflects the destructive action so the user has audit feedback.
        assert "shred" in result.output.lower()

    def test_shred_without_yes_aborts_on_no_input(self) -> None:
        """Without ``--yes`` and without a confirm input, the command aborts."""
        port = _StubCachePortForShred()
        set_cache_provider(lambda: port)
        calls: list[Path] = []

        def _executor() -> Path:
            calls.append(Path("/tmp/cache.db"))  # noqa: S108
            return Path("/tmp/cache.db")  # noqa: S108

        set_shred_executor(_executor)
        result = runner.invoke(app, ["cache", "shred"], input="n\n")
        assert result.exit_code == 0
        assert not calls, "executor must NOT run when user declines"
        assert "abort" in result.output.lower() or "cancel" in result.output.lower()

    def test_shred_yes_short_flag_works_too(self) -> None:
        """``-y`` short form also bypasses the prompt."""
        port = _StubCachePortForShred()
        set_cache_provider(lambda: port)
        calls: list[Path] = []

        def _executor() -> Path:
            calls.append(Path("/tmp/cache.db"))  # noqa: S108
            return Path("/tmp/cache.db")  # noqa: S108

        set_shred_executor(_executor)
        result = runner.invoke(app, ["cache", "shred", "-y"])
        assert result.exit_code == 0
        assert calls


# ── cache doctor: Encryption row ──────────────────────────────


class TestCacheDoctorEncryptionRow:
    def test_doctor_shows_sqlcipher_enabled_when_status_is_sqlcipher(self) -> None:
        """Doctor surfaces ``SQLCipher enabled`` when encryption is active."""
        port = _StubCachePortForShred(encryption_status="sqlcipher")
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "doctor"])
        assert result.exit_code == 0, result.output
        # Brand voice: lower-case ``encryption`` label, value text matches.
        assert "encryption" in result.output.lower()
        assert "sqlcipher" in result.output.lower()

    def test_doctor_shows_fallback_when_status_is_plain(self) -> None:
        """Doctor surfaces ``fallback (plain SQLite)`` when SQLCipher is unavailable."""
        port = _StubCachePortForShred(encryption_status="plain")
        set_cache_provider(lambda: port)
        result = runner.invoke(app, ["cache", "doctor"])
        assert result.exit_code == 0, result.output
        assert "encryption" in result.output.lower()
        assert "fallback" in result.output.lower() or "plain" in result.output.lower()
