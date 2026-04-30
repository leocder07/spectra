"""Resolve the actor identity for audit events (ADR-018 §2).

Precedence — first non-empty source wins:

    1. ``SPECTRA_ACTOR`` env var (alias: legacy ``SPECTRA_USER_ID``)
    2. OIDC provider claims when ``GITHUB_ACTIONS=true`` (high confidence)
    3. ``git config user.email`` (medium confidence — dev laptops)
    4. ``getpass.getuser()@hostname`` fallback (low confidence)

The use case never imports ``subprocess`` directly to read git config —
the helper is a private module function patched in tests.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import platform
import subprocess
from typing import Final

from spectra.entities.audit import Identity

HASHED_ID_LEN: Final[int] = 16
"""Length of the ``hash_actor`` digest in hex chars."""


def resolve_actor() -> Identity:
    """Return the resolved :class:`Identity` for this process.

    Pure function aside from environment / git lookups. Idempotent across
    repeated calls — use the result as a process-lifetime singleton.
    """
    env = _env_actor()
    if env is not None:
        return Identity(actor=env, source="env", confidence="medium")
    oidc = _oidc_actor()
    if oidc is not None:
        return Identity(actor=oidc, source="oidc", confidence="high")
    git = _git_email()
    if git:
        return Identity(actor=git, source="git", confidence="medium")
    return Identity(
        actor=f"{_login_user()}@{_hostname()}",
        source="hostname",
        confidence="low",
    )


def hash_actor(actor: str) -> str:
    """Return a 16-char blake2b digest of ``actor`` for privacy hashing.

    Audit events ship the raw actor (auditors need a name); telemetry +
    cache namespaces use this hashed form so per-user identifiers are
    one-way at rest.
    """
    return hashlib.blake2b(actor.encode("utf-8"), digest_size=HASHED_ID_LEN // 2).hexdigest()


# ── Source helpers (overridden in tests) ─────────────────────


def _env_actor() -> str | None:
    """Return the value of the ``SPECTRA_ACTOR`` (or legacy) env var."""
    actor = os.environ.get("SPECTRA_ACTOR") or os.environ.get("SPECTRA_USER_ID")
    return actor.strip() if actor else None


def _oidc_actor() -> str | None:
    """Return the GitHub Actions OIDC-derived actor string, if applicable."""
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return None
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    ref = os.environ.get("GITHUB_REF", "")
    if not repo:
        return None
    branch = ref.removeprefix("refs/heads/") or ref or "unknown"
    return f"ci:gh-actions:{repo}@{branch}"


def _git_email() -> str | None:
    """Return ``git config user.email`` or ``None`` when unset/missing."""
    try:
        result = subprocess.run(
            ["git", "config", "--get", "user.email"],  # noqa: S607 — git resolved on PATH
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    email = result.stdout.strip()
    return email or None


def _login_user() -> str:
    """Return the logged-in user, or ``unknown`` when unavailable."""
    try:
        return getpass.getuser()
    except OSError:
        return "unknown"


def _hostname() -> str:
    """Return the platform hostname, or ``unknown-host`` on failure."""
    try:
        node = platform.node()
    except OSError:
        return "unknown-host"
    return node or "unknown-host"


__all__ = [
    "HASHED_ID_LEN",
    "hash_actor",
    "resolve_actor",
]
