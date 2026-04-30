"""Composition-root helpers for audit sink + receipt-key wiring (ADR-018 §3, #57).

Two responsibilities, one module so the production main.py can import a
single helper module instead of dragging in keyring + httpx for every
test that touches main:

- :func:`build_audit_adapter` parses a ``--audit-sink stdout|file:<path>|
  otlp:<url>`` spec and returns the matching adapter.
- :class:`KeyringReceiptKeyStore` is the production keystore for
  :class:`spectra.infrastructure.receipt_signer.ReceiptSigner`. The
  private key sits in the OS keyring under service ``spectra-receipt-key``;
  the public key lives at ``~/.config/spectra/receipt.pub``.

ADR references: ADR-018 (audit log + identity), capability #57 (Ed25519
signed scan receipt). See ``docs/architecture/adr/`` and
``docs/glossary.md`` for the at-a-glance index.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from spectra.infrastructure.audit import (
    JsonLinesAuditAdapter,
    OtlpAuditAdapter,
    StdoutAuditAdapter,
)
from spectra.use_cases.interfaces import AuditPort

_RECEIPT_KEYRING_SERVICE = "spectra-receipt-key"
_RECEIPT_KEYRING_ACCOUNT = "default"


# ── Audit sink parsing + factory ────────────────────────────


def parse_audit_sink_spec(spec: str) -> tuple[str, str]:
    """Split ``stdout`` / ``file:<path>`` / ``otlp:<url>`` into ``(kind, value)``."""
    if spec == "stdout":
        return ("stdout", "")
    if spec.startswith("file:"):
        return ("file", spec[len("file:") :])
    if spec.startswith("otlp:"):
        return ("otlp", spec[len("otlp:") :])
    msg = f"Unknown audit sink spec: {spec!r} (use stdout, file:<path>, or otlp:<url>)"
    raise ValueError(msg)


def build_audit_adapter(spec: str) -> AuditPort:
    """Return a Layer-4 audit adapter matching ``spec``."""
    kind, value = parse_audit_sink_spec(spec)
    if kind == "stdout":
        return StdoutAuditAdapter()
    if kind == "file":
        return JsonLinesAuditAdapter(path=Path(value))
    return OtlpAuditAdapter(endpoint=value)


def default_audit_sink_spec() -> str:
    """Return the default sink: ``file:`` in CI, ``stdout`` interactively."""
    if os.environ.get("SPECTRA_CI", "").lower() in ("1", "true", "yes"):
        return f"file:{default_audit_path()}"
    return "stdout"


def default_audit_path() -> Path:
    """Return ``${XDG_STATE_HOME:-~/.local/state}/spectra/audit.jsonl``."""
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "spectra" / "audit.jsonl"


# ── Receipt key store ───────────────────────────────────────


class _KeyringBackend(Protocol):
    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, password: str) -> None: ...


class KeyringReceiptKeyStore:
    """Production :class:`KeyStore` — private key in OS keyring, public PEM on disk."""

    def __init__(
        self,
        public_key_path: Path,
        backend: _KeyringBackend | None = None,
    ) -> None:
        """Bind the keystore to a public-key path; backend is the keyring module."""
        self._public_key_path = Path(public_key_path)
        self._backend = backend if backend is not None else _import_default_keyring()

    @property
    def public_key_path(self) -> Path:
        """Disk location of the PEM-encoded public key."""
        return self._public_key_path

    def load_private_key(self) -> Ed25519PrivateKey | None:
        """Return the keyring-stored private key, or ``None`` when unset."""
        stored = self._backend.get_password(_RECEIPT_KEYRING_SERVICE, _RECEIPT_KEYRING_ACCOUNT)
        if not stored:
            return None
        try:
            raw = bytes.fromhex(stored)
        except ValueError:
            return None
        try:
            return Ed25519PrivateKey.from_private_bytes(raw)
        except (ValueError, TypeError):
            return None

    def save_private_key(self, key: Ed25519PrivateKey) -> None:
        """Persist ``key`` to the OS keyring as hex-encoded raw bytes."""
        raw = key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self._backend.set_password(
            _RECEIPT_KEYRING_SERVICE,
            _RECEIPT_KEYRING_ACCOUNT,
            raw.hex(),
        )

    def public_key_pem(self) -> bytes | None:
        """Return the PEM bytes from disk, or ``None`` if not yet written."""
        if not self._public_key_path.exists():
            return None
        return self._public_key_path.read_bytes()

    def write_public_key(self, key: Ed25519PublicKey) -> None:
        """Serialize ``key`` to PEM and persist on disk."""
        pem = key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._public_key_path.parent.mkdir(parents=True, exist_ok=True)
        self._public_key_path.write_bytes(pem)


def _import_default_keyring() -> _KeyringBackend:
    """Import ``keyring`` lazily so tests can substitute a fake backend."""
    import keyring

    return keyring


def default_receipt_public_key_path() -> Path:
    """Return ``~/.config/spectra/receipt.pub`` (XDG-aware)."""
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "spectra" / "receipt.pub"


__all__ = [
    "KeyringReceiptKeyStore",
    "build_audit_adapter",
    "default_audit_path",
    "default_audit_sink_spec",
    "default_receipt_public_key_path",
    "parse_audit_sink_spec",
]
