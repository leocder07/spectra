"""Layer 4 implementation of ``SignerPort`` — Ed25519 via ``cryptography``.

Fix R3-Arch-3 — closes the dependency-rule break where
``adapters/waiver_cli.py`` reached into ``cryptography.hazmat.primitives.asymmetric.ed25519``
directly. The CLI now consumes the ``SignerPort`` Protocol and the
composition root injects this adapter (or a fake, in tests).

Hex encoding contract:
    - 32-byte raw private seed → 64-char hex.
    - 32-byte raw public key → 64-char hex.
    - 64-byte raw signature → opaque ``bytes`` returned by ``sign``;
      callers ``hex()``-encode for YAML storage.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_PRIVATE_KEY_BYTES = 32


class Ed25519SignerAdapter:
    """Concrete signer using ``cryptography``'s pure-Python Ed25519 stack.

    Stateless and re-instantiable per call — no shared state, no I/O.
    """

    def generate_keypair(self) -> tuple[str, str]:
        """Mint a fresh Ed25519 keypair.

        Returns:
            ``(private_hex, public_hex)`` — both 64-char hex strings.
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

    def derive_public_key(self, private_hex: str) -> str:
        """Recover the 64-char public hex from a 64-char private hex seed.

        Raises:
            ValueError: when ``private_hex`` is non-hex or wrong length.
        """
        priv = self._load_private(private_hex)
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return pub_bytes.hex()

    def sign(self, payload: bytes, private_hex: str) -> bytes:
        """Sign ``payload`` and return the raw 64-byte signature."""
        priv = self._load_private(private_hex)
        return priv.sign(payload)

    def verify(self, payload: bytes, signature: bytes, public_hex: str) -> bool:
        """Verify ``signature`` over ``payload``; return False on mismatch.

        Swallows ``InvalidSignature`` and ``ValueError`` (malformed hex)
        so callers can branch on a boolean without a try/except.
        """
        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
            pub.verify(signature, payload)
        except (InvalidSignature, ValueError):
            return False
        return True

    @staticmethod
    def _load_private(private_hex: str) -> Ed25519PrivateKey:
        """Validate hex + length, then build the underlying private key."""
        try:
            priv_bytes = bytes.fromhex(private_hex)
        except ValueError as exc:
            msg = "private_hex must be 64-char hex"
            raise ValueError(msg) from exc
        if len(priv_bytes) != _PRIVATE_KEY_BYTES:
            msg = f"private key must be {_PRIVATE_KEY_BYTES} bytes (64 hex chars)"
            raise ValueError(msg)
        return Ed25519PrivateKey.from_private_bytes(priv_bytes)


__all__ = ["Ed25519SignerAdapter"]
