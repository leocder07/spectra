"""Ed25519 signer + verifier for scan receipts (roadmap #57).

The signer keeps the private key out of the report by storing it in the
OS keyring (production) or an in-memory keystore (tests). Public keys are
PEM-serialized to disk so a verifier can be wholly offline given the
public-key path.

Tamper-evidence is byte-exact: ``ScanReceipt.signed_payload_bytes`` is the
canonical input to both sign + verify, so any mutation of the receipt's
non-signature fields breaks verification.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from spectra.entities.audit import new_event_id
from spectra.entities.receipt import ScanReceipt

if TYPE_CHECKING:
    from spectra.entities.models import AnalysisReport, ScoreCard

_LOG = logging.getLogger("spectra.receipt")
_FINGERPRINT_LEN = 16


# ── Keystore Protocol + in-memory implementation ─────────────


class KeyStore(Protocol):
    """Persistent home for the Ed25519 private key + public-key path."""

    @property
    def public_key_path(self) -> Path:
        """Disk path where the PEM-encoded public key is written."""
        ...

    def load_private_key(self) -> Ed25519PrivateKey | None:
        """Return the stored private key, or ``None`` if never minted."""
        ...

    def save_private_key(self, key: Ed25519PrivateKey) -> None:
        """Persist ``key`` so subsequent runs reuse it."""
        ...

    def public_key_pem(self) -> bytes | None:
        """Return the cached public-key PEM bytes, or ``None`` on first run."""
        ...

    def write_public_key(self, key: Ed25519PublicKey) -> None:
        """Serialize ``key`` to PEM and persist to ``public_key_path``."""
        ...


class InMemoryKeyStore:
    """Test-only :class:`KeyStore` — keeps the private key in process memory.

    Production keystore (keyring-backed) ships in ``main.py`` so the
    composition root owns the OS dependency.
    """

    def __init__(self, public_key_path: Path) -> None:
        """Bind to a public-key file path; the private key starts unset."""
        self._public_key_path = Path(public_key_path)
        self._private_key: Ed25519PrivateKey | None = None
        self._pub_pem: bytes | None = None

    @property
    def public_key_path(self) -> Path:
        """Disk location for the PEM public key."""
        return self._public_key_path

    def load_private_key(self) -> Ed25519PrivateKey | None:
        """Return the in-memory private key (None until first save)."""
        return self._private_key

    def save_private_key(self, key: Ed25519PrivateKey) -> None:
        """Cache the freshly-generated private key in memory."""
        self._private_key = key

    def public_key_pem(self) -> bytes | None:
        """Return the cached public-key PEM, or None until written."""
        return self._pub_pem

    def write_public_key(self, key: Ed25519PublicKey) -> None:
        """Serialize ``key`` to PEM, persist on disk + memory."""
        pem = key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._public_key_path.parent.mkdir(parents=True, exist_ok=True)
        self._public_key_path.write_bytes(pem)
        self._pub_pem = pem


# ── Signer ────────────────────────────────────────────────────


class ReceiptSigner:
    """Generate + sign :class:`ScanReceipt` instances over an Ed25519 keypair."""

    def __init__(self, keystore: KeyStore) -> None:
        """Bind to a keystore; the keypair is minted lazily on first sign."""
        self._keystore = keystore

    def sign(
        self,
        report: AnalysisReport,
        *,
        scan_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> ScanReceipt:
        """Produce a signed receipt for ``report``.

        Args:
            report: Source report — its score card is hashed into the receipt.
            scan_id: Optional pre-existing scan id to bind. When omitted
                the signer mints a new UUIDv7-shaped id.
            timestamp: Optional issue timestamp. Defaults to ``datetime.now(UTC)``.
        """
        private_key = self._ensure_keypair()
        public_key = private_key.public_key()
        sc_hash = compute_score_card_hash(report.score_card)
        repo_sig = _repo_signature(report)
        receipt = _build_unsigned(
            scan_id or new_event_id(),
            repo_sig,
            sc_hash,
            timestamp or datetime.now(UTC),
            report,
            public_key,
        )
        signature = private_key.sign(receipt.signed_payload_bytes())
        return receipt.model_copy(update={"signature": signature.hex()})

    def _ensure_keypair(self) -> Ed25519PrivateKey:
        """Load the stored keypair or mint a fresh one."""
        existing = self._keystore.load_private_key()
        if existing is not None:
            return existing
        fresh = Ed25519PrivateKey.generate()
        self._keystore.save_private_key(fresh)
        self._keystore.write_public_key(fresh.public_key())
        return fresh


def _build_unsigned(
    scan_id: str,
    repo_sig: str,
    sc_hash: str,
    ts: datetime,
    report: AnalysisReport,
    public_key: Ed25519PublicKey,
) -> ScanReceipt:
    """Assemble a placeholder receipt with a sentinel signature.

    The real signature is filled in by ``ReceiptSigner.sign`` after
    serializing the deterministic payload.
    """
    return ScanReceipt(
        scan_id=scan_id,
        repo_signature=repo_sig,
        score_card_hash=sc_hash,
        timestamp=ts,
        spectra_version=_safe_version(report),
        signature="0" * 128,  # placeholder; overwritten before return
        public_key_fingerprint=_fingerprint(public_key),
    )


def _safe_version(report: AnalysisReport) -> str:
    """Best-effort version extraction; always non-empty."""
    cached = getattr(report, "spectra_version", None)
    return str(cached) if cached else "0.0.0"


def _repo_signature(report: AnalysisReport) -> str:
    """Stable hash of the analyzed repository's URL."""
    digest = hashlib.blake2b(report.repo_url.encode("utf-8"), digest_size=16)
    return digest.hexdigest()


def _fingerprint(public_key: Ed25519PublicKey) -> str:
    """First 16 hex chars of blake2b(public_key_DER)."""
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.blake2b(der, digest_size=8).hexdigest()[:_FINGERPRINT_LEN]


# ── Hashing + verification ──────────────────────────────────


def compute_score_card_hash(score_card: ScoreCard) -> str:
    """Return a deterministic 64-hex blake2b digest of ``score_card``."""
    payload = json.dumps(
        score_card.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=32).hexdigest()


def verify_receipt(receipt: ScanReceipt, public_key_pem: bytes | None) -> bool:
    """Verify the Ed25519 signature on ``receipt`` against a public key.

    Returns ``True`` only when the signature is valid AND the fingerprint
    of ``public_key_pem`` matches the receipt's stored fingerprint —
    catching the case where a verifier was handed the wrong key.
    """
    if public_key_pem is None:
        _LOG.warning("verify_receipt: no public key supplied")
        return False
    public_key = _load_public_key(public_key_pem)
    if public_key is None:
        return False
    if _fingerprint(public_key) != receipt.public_key_fingerprint:
        _LOG.warning("verify_receipt: public-key fingerprint mismatch")
        return False
    try:
        signature_bytes = bytes.fromhex(receipt.signature)
    except ValueError:
        return False
    try:
        public_key.verify(signature_bytes, receipt.signed_payload_bytes())
    except InvalidSignature:
        return False
    return True


def _load_public_key(pem: bytes) -> Ed25519PublicKey | None:
    """Load ``pem`` as an Ed25519 public key; ``None`` on parse failure."""
    try:
        loaded = serialization.load_pem_public_key(pem)
    except (ValueError, TypeError):
        return None
    if not isinstance(loaded, Ed25519PublicKey):
        return None
    return loaded


__all__ = [
    "InMemoryKeyStore",
    "KeyStore",
    "ReceiptSigner",
    "compute_score_card_hash",
    "verify_receipt",
]
