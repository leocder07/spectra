"""Signed-scan-receipt domain entity (Layer 1).

Implements roadmap capability #57: every successful scan produces a
tamper-evident receipt that downstream consumers (CI gates, compliance
collectors) can verify offline against the public key.

The receipt itself is a frozen Pydantic model; signing + verification
live in Layer 4 (``infrastructure/receipt_signer.py``) where the
``cryptography`` dependency belongs.
"""

from __future__ import annotations

import json
from datetime import datetime  # noqa: TC003 — used by Pydantic at runtime

from pydantic import BaseModel, Field


class ScanReceipt(BaseModel, frozen=True):
    """Tamper-evident receipt for a completed scan.

    Attributes:
        scan_id: 32-char hex (UUIDv7 or v4); matches the audit ``run_id``.
        repo_signature: 32-hex blake2b digest of the file tree.
        score_card_hash: 64-hex blake2b digest of the canonical score-card
            JSON. A consumer recomputes this from the report's score card
            and compares — any mutation of scores breaks the match.
        timestamp: UTC instant the receipt was issued.
        spectra_version: Version string of the producing CLI.
        signature: 128-char hex Ed25519 signature over ``signed_payload_bytes``.
        public_key_fingerprint: First 16 hex chars of the public key digest;
            lets a verifier discover which key was used without shipping the
            full key inline.
    """

    scan_id: str = Field(min_length=16, max_length=64)
    repo_signature: str = Field(min_length=16, max_length=128)
    score_card_hash: str = Field(min_length=32, max_length=128)
    timestamp: datetime
    spectra_version: str = Field(min_length=1, max_length=64)
    signature: str = Field(min_length=64, max_length=256)
    public_key_fingerprint: str = Field(min_length=8, max_length=64)

    def signed_payload(self) -> dict[str, str]:
        """Return the canonical, signature-free payload as a sorted dict.

        Used by both the signer (input to Ed25519 sign) and the verifier.
        Excluding ``signature`` is critical: a verifier must reconstruct
        the exact bytes the signer produced.
        """
        return {
            "public_key_fingerprint": self.public_key_fingerprint,
            "repo_signature": self.repo_signature,
            "scan_id": self.scan_id,
            "score_card_hash": self.score_card_hash,
            "spectra_version": self.spectra_version,
            "timestamp": self.timestamp.isoformat(),
        }

    def signed_payload_bytes(self) -> bytes:
        """Serialize ``signed_payload`` deterministically for signing/verifying."""
        return json.dumps(
            self.signed_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


__all__ = ["ScanReceipt"]
