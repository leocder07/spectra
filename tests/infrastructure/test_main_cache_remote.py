"""Composition-root tests for ``--cache-remote`` (#21, ADR-021).

The composition root selects between three cache layouts:

  * ``--no-cache``                            → ``None`` (cache disabled)
  * default (no flag)                         → ``SqliteCacheAdapter`` (L1 only)
  * ``--cache-remote redis://...``            → ``TieredCacheAdapter(L1, Redis)``

The tests never spin up real Redis — they assert the wiring shape only.
"""

from __future__ import annotations

import pytest

from spectra.entities.models import CacheSecret
from spectra.infrastructure.cache_adapter import SqliteCacheAdapter
from spectra.infrastructure.main import (
    _build_cache_with_remote,
    _resolve_cache_remote_url,
)
from spectra.infrastructure.tiered_cache_adapter import TieredCacheAdapter


@pytest.fixture
def secret() -> CacheSecret:
    return CacheSecret(value=b"\x07" * 32)


# ── URL resolution ──────────────────────────────────────────


def test_resolve_explicit_arg_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit CLI value beats the env var."""
    monkeypatch.setenv("SPECTRA_CACHE_REDIS", "redis://env.example/0")
    assert _resolve_cache_remote_url("redis://cli.example/0") == "redis://cli.example/0"


def test_resolve_env_used_when_arg_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env var supplies the URL when the CLI flag is absent."""
    monkeypatch.setenv("SPECTRA_CACHE_REDIS", "redis://env.example/0")
    assert _resolve_cache_remote_url(None) == "redis://env.example/0"


def test_resolve_returns_none_when_neither(monkeypatch: pytest.MonkeyPatch) -> None:
    """No flag and no env var → local-only mode."""
    monkeypatch.delenv("SPECTRA_CACHE_REDIS", raising=False)
    assert _resolve_cache_remote_url(None) is None


# ── Cache wiring ────────────────────────────────────────────


def test_build_local_only_when_remote_absent(
    tmp_path: object,
    secret: CacheSecret,
) -> None:
    """When no remote URL is supplied, the wired cache is a bare SqliteCacheAdapter."""
    cache = _build_cache_with_remote(remote_url=None, local=_make_local(tmp_path, secret))
    assert isinstance(cache, SqliteCacheAdapter)


def test_build_tiered_when_remote_set(
    tmp_path: object,
    secret: CacheSecret,
) -> None:
    """A remote URL produces a TieredCacheAdapter wrapping the L1."""
    local = _make_local(tmp_path, secret)
    cache = _build_cache_with_remote(
        remote_url="redis://localhost:6379/0",
        local=local,
        secret=secret,
    )
    assert isinstance(cache, TieredCacheAdapter)


def test_build_tiered_degrades_when_no_secret(
    tmp_path: object,
    secret: CacheSecret,
) -> None:
    """No HMAC secret → cannot enable L2; falls back to L1-only."""
    local = _make_local(tmp_path, secret)
    cache = _build_cache_with_remote(
        remote_url="redis://localhost:6379/0",
        local=local,
        secret=None,
    )
    assert isinstance(cache, SqliteCacheAdapter)


# ── Helpers ─────────────────────────────────────────────────


def _make_local(tmp_path: object, secret: CacheSecret) -> SqliteCacheAdapter:
    """Build a real on-disk SqliteCacheAdapter for the wiring tests."""
    from pathlib import Path

    db = Path(str(tmp_path)) / "cache.db"
    return SqliteCacheAdapter(db_path=db, secret=secret)
