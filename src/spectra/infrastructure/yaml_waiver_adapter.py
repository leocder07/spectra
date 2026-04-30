"""YAML adapter for ``.spectra-waivers.yml`` + ``.spectra-approvers.yml`` (#18).

Layer 4 implementation of ``WaiverPort``. Verifies each waiver's Ed25519
signature against approver public keys; partitions verified waivers into
``(active, expired)`` based on ``expires_at``.

Schema:
    .spectra-waivers.yml::
        version: 1
        waivers:
          - repo_signature: <32-hex>
            finding_signature: <16-hex>
            reason: ">=10 chars"
            waived_by: alice
            waived_at: 2026-04-29T12:00:00+00:00
            expires_at: 2026-10-26T12:00:00+00:00
            signature: <128-hex>

    .spectra-approvers.yml::
        version: 1
        approvers:
          - name: alice
            email: alice@x.com
            public_key: <64-hex>

Failure mode:
    - Missing files → empty tuples (the policy gate degrades to no waivers).
    - Malformed YAML or schema violation → ``AgentError`` SPEC-012.
    - Per-waiver signature failure → DROP and log; never silent.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import ValidationError

from spectra.entities.errors import ERRORS, AgentError
from spectra.entities.models import Approver, Waiver

if TYPE_CHECKING:
    from pathlib import Path


_LOG = logging.getLogger("spectra.waiver")


def canonical_waiver_payload(waiver: Waiver) -> bytes:
    """Return the deterministic byte payload that gets signed.

    Excludes the ``signature`` field (it cannot reference itself) and
    serialises the remaining fields as sorted-key JSON. Datetimes are
    rendered as ISO-8601 with explicit UTC offset so cross-platform
    re-encoding round-trips bit-for-bit.

    Args:
        waiver: The waiver to canonicalize.

    Returns:
        UTF-8 encoded bytes ready for Ed25519 signing or verification.
    """
    payload = {
        "repo_signature": waiver.repo_signature,
        "finding_signature": waiver.finding_signature,
        "reason": waiver.reason,
        "waived_by": waiver.waived_by,
        "waived_at": waiver.waived_at.isoformat(),
        "expires_at": waiver.expires_at.isoformat(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_keypair() -> tuple[str, str]:
    """Mint a fresh Ed25519 keypair.

    Returns:
        ``(private_hex, public_hex)`` — both 64-char hex strings (the
        public key is always 32 bytes / 64 hex; the private key seed
        is also 32 bytes / 64 hex).
    """
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_bytes.hex(), pub_bytes.hex()


class YamlWaiverAdapter:
    """Loads + verifies signed waivers from disk.

    All public methods are deterministic and free of network or shared
    state — the adapter can be re-instantiated per call.
    """

    def load(
        self,
        waivers_path: Path,
        approvers_path: Path,
    ) -> tuple[tuple[Waiver, ...], tuple[Waiver, ...]]:
        """Return ``(active, expired)`` verified-waiver tuples.

        Behaviour:
            - Either file missing → both tuples empty (policy degrades).
            - Each waiver verified against ALL approver pubkeys; first
              match wins. No match → dropped + warning logged.
            - Verified waivers split by ``is_expired(now)``.

        Args:
            waivers_path: Path to ``.spectra-waivers.yml``.
            approvers_path: Path to ``.spectra-approvers.yml``.

        Returns:
            ``(active_tuple, expired_tuple)`` — both contain only
            signature-verified waivers.
        """
        if not waivers_path.exists() or not approvers_path.exists():
            return (), ()
        approvers = self.load_approvers(approvers_path)
        if not approvers:
            return (), ()
        waivers = self._load_waivers(waivers_path)
        verified = tuple(w for w in waivers if self.verify(w, approvers))
        return self._split_by_expiry(verified)

    def load_approvers(self, path: Path) -> tuple[Approver, ...]:
        """Read the approvers YAML; return a tuple of validated entries."""
        if not path.exists():
            return ()
        raw = self._read(path)
        data = self._parse(path, raw)
        if data is None:
            return ()
        entries = data.get("approvers", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            raise _spec_012(f"{path} 'approvers' must be a YAML list", ValueError("bad shape"))
        out: list[Approver] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(Approver.model_validate(entry))
            except ValidationError as exc:
                _LOG.warning("Dropping invalid approver entry in %s: %s", path, exc)
        return tuple(out)

    def verify(
        self,
        waiver: Waiver,
        approvers: tuple[Approver, ...],
    ) -> bool:
        """Verify ``waiver.signature`` against any approver pubkey."""
        if not waiver.signature:
            _LOG.warning(
                "Dropping unsigned waiver for finding %s by %s",
                waiver.finding_signature,
                waiver.waived_by,
            )
            return False
        try:
            sig_bytes = bytes.fromhex(waiver.signature)
        except ValueError:
            _LOG.warning(
                "Dropping waiver with non-hex signature for finding %s",
                waiver.finding_signature,
            )
            return False
        payload = canonical_waiver_payload(waiver)
        for approver in approvers:
            if self._try_verify(approver.public_key, sig_bytes, payload):
                return True
        _LOG.warning(
            "Dropping waiver with no matching approver signature: finding=%s by=%s",
            waiver.finding_signature,
            waiver.waived_by,
        )
        return False

    def sign_waiver(self, waiver: Waiver, private_hex: str) -> str:
        """Sign the canonical payload of ``waiver`` and return the hex signature.

        Args:
            waiver: The waiver to sign — its ``signature`` field is ignored.
            private_hex: 64-char hex of an Ed25519 private key seed.

        Returns:
            128-char hex Ed25519 signature.
        """
        try:
            priv_bytes = bytes.fromhex(private_hex)
        except ValueError as exc:
            msg = "private_hex must be 64-char hex"
            raise ValueError(msg) from exc
        if len(priv_bytes) != 32:
            msg = "private key must be 32 bytes (64 hex chars)"
            raise ValueError(msg)
        priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
        sig = priv.sign(canonical_waiver_payload(waiver))
        return sig.hex()

    # ── private ──────────────────────────────────────────────

    def _load_waivers(self, path: Path) -> list[Waiver]:
        """Parse + validate every entry in the waivers YAML."""
        raw = self._read(path)
        data = self._parse(path, raw)
        if data is None:
            return []
        entries = data.get("waivers", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            raise _spec_012(f"{path} 'waivers' must be a YAML list", ValueError("bad shape"))
        out: list[Waiver] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(Waiver.model_validate(entry))
            except ValidationError as exc:
                _LOG.warning("Dropping invalid waiver entry: %s", exc)
        return out

    @staticmethod
    def _split_by_expiry(
        waivers: tuple[Waiver, ...],
    ) -> tuple[tuple[Waiver, ...], tuple[Waiver, ...]]:
        """Partition into (active, expired) using current UTC time."""
        now = datetime.now(UTC)
        active: list[Waiver] = []
        expired: list[Waiver] = []
        for w in waivers:
            (expired if w.is_expired(now) else active).append(w)
        return tuple(active), tuple(expired)

    @staticmethod
    def _try_verify(public_hex: str, signature: bytes, payload: bytes) -> bool:
        """Attempt verification; swallow InvalidSignature and return False."""
        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
            pub.verify(signature, payload)
        except (InvalidSignature, ValueError):
            return False
        return True

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _spec_012(f"cannot read {path}: {exc}", exc) from exc

    @staticmethod
    def _parse(path: Path, raw: str) -> dict | None:
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise _spec_012(f"invalid YAML in {path}: {exc}", exc) from exc
        if data is None:
            return None
        if not isinstance(data, dict):
            msg = f"{path} must be a YAML mapping at the top level"
            raise _spec_012(msg, ValueError(msg))
        return data


def _spec_012(message: str, cause: BaseException) -> AgentError:
    """Wrap a parse/validation failure as :class:`AgentError` SPEC-012."""
    err = AgentError(ERRORS["SPEC-012"])
    err.args = (f"SPEC-012: {message}",)
    err.__cause__ = cause
    return err


__all__ = [
    "YamlWaiverAdapter",
    "canonical_waiver_payload",
    "generate_keypair",
]
