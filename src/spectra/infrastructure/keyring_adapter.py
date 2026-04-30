"""Keyring-backed implementation of the per-user cache HMAC secret (ADR-012).

The composition root constructs ``KeyringSecretAdapter`` once at startup
and threads the resulting :class:`CacheSecret` into ``SqliteCacheAdapter``.
The adapter never touches the keyring on the hot path — it caches the
loaded secret in memory for the process lifetime.

Failure model:
    Any keyring backend failure (no daemon, locked keychain, missing
    library) raises :class:`AgentError` carrying ``SPEC-010``. The
    composition root catches this once and degrades the entire run to
    no-cache mode — never fatal.
"""

from __future__ import annotations

import logging
import secrets as _secrets
from typing import Protocol

from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.models import CacheSecret

_LOG = logging.getLogger("spectra.cache.keyring")
_SERVICE = "spectra-cache-hmac"
_SECRET_BYTES = 32
_HEX_LEN = _SECRET_BYTES * 2


class KeyringBackend(Protocol):
    """Subset of the ``keyring`` module surface area used by this adapter.

    Defined as a Protocol so tests can substitute an in-memory fake
    without importing the real keyring stack.
    """

    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, password: str) -> None: ...

    def delete_password(self, service: str, account: str) -> None: ...


class KeyringSecretAdapter:
    """Per-user :class:`CacheSecret` provider backed by the OS keyring.

    Service name ``spectra-cache-hmac``; account is the effective UID
    rendered as a decimal string. Secrets are 32 bytes from
    :func:`secrets.token_bytes`, hex-encoded for keyring storage.
    """

    def __init__(self, uid: str, backend: KeyringBackend | None = None) -> None:
        """Bind to a specific UID; optionally inject a custom backend."""
        self._uid = uid
        self._backend = backend if backend is not None else _import_default_backend()
        self._cached: CacheSecret | None = None

    def get(self) -> CacheSecret:
        """Return the per-user secret, generating + storing if absent.

        The secret is cached in memory after the first call. Backend
        failures bubble up as :class:`AgentError` SPEC-010.
        """
        if self._cached is not None:
            return self._cached
        self._cached = self._load_or_generate()
        return self._cached

    def _load_or_generate(self) -> CacheSecret:
        """Read existing secret from the keyring or mint a fresh one."""
        existing = self._read_existing()
        if existing is not None:
            return existing
        return self._mint_and_store()

    def _read_existing(self) -> CacheSecret | None:
        """Return the keyring-stored secret if present + well-formed."""
        try:
            stored = self._backend.get_password(_SERVICE, self._uid)
        except Exception as exc:
            raise _spec_010_keyring(exc) from exc
        if stored is None:
            return None
        try:
            value = bytes.fromhex(stored)
        except ValueError:
            _LOG.warning("Stored keyring value malformed; regenerating per-user secret")
            return None
        if len(value) != _SECRET_BYTES:
            _LOG.warning("Stored keyring value wrong length; regenerating per-user secret")
            return None
        return CacheSecret(value=value)

    def _mint_and_store(self) -> CacheSecret:
        """Generate a fresh 32-byte secret and persist it under ``$UID``."""
        value = _secrets.token_bytes(_SECRET_BYTES)
        try:
            self._backend.set_password(_SERVICE, self._uid, value.hex())
        except Exception as exc:
            raise _spec_010_keyring(exc) from exc
        return CacheSecret(value=value)

    @property
    def backend_name(self) -> str:
        """Return a friendly backend label for ``spectra cache doctor``."""
        return getattr(self._backend, "backend_name", type(self._backend).__name__)

    def shred(self) -> None:
        """Drop the per-user secret from the keyring + the in-memory cache.

        Called by ``spectra cache shred`` so the next adapter open has to
        cold-mint a fresh secret. The same encryption key (HKDF-derived
        from the secret) regenerates with the new bytes — old encrypted
        cache rows would no longer decrypt, which is the point.

        Idempotent: missing entries are tolerated (the keyring contract
        does not specify whether ``delete_password`` raises when the
        target row is absent; we accept either behaviour).
        """
        delete = getattr(self._backend, "delete_password", None)
        if delete is None:
            self._cached = None
            return
        try:
            delete(_SERVICE, self._uid)
        except KeyError:
            # Entry never existed — idempotent shred.
            pass
        except Exception as exc:
            self._cached = None
            raise _spec_010_keyring(exc) from exc
        self._cached = None


def _import_default_backend() -> KeyringBackend:
    """Import the real ``keyring`` module; raise SPEC-010 on import failure."""
    try:
        import keyring  # late import keeps optional dep cheap
    except ImportError as exc:
        raise _spec_010_keyring(exc) from exc
    return keyring


def _spec_010_keyring(cause: BaseException) -> AgentError:
    """Wrap a keyring failure as :class:`AgentError` SPEC-010."""
    err = AgentError(ERRORS["SPEC-010"])
    err.__cause__ = cause
    return err
