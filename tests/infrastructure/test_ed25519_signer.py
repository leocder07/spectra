"""Tests for the Layer 4 ``Ed25519SignerAdapter`` (Fix R3-Arch-3).

The adapter implements the use-case ``SignerPort`` so the CLI subcommands
in ``adapters/waiver_cli.py`` no longer reach into ``cryptography``
directly. End-to-end seam coverage lives in ``test_waiver_cli.py``;
here we pin the adapter contract.
"""

from __future__ import annotations

import pytest

from spectra.infrastructure.ed25519_signer import Ed25519SignerAdapter
from spectra.use_cases.interfaces import SignerPort


class TestEd25519SignerAdapter:
    def test_implements_signer_port_protocol(self) -> None:
        signer: SignerPort = Ed25519SignerAdapter()
        # All four port methods are callable on the concrete adapter.
        assert callable(signer.generate_keypair)
        assert callable(signer.derive_public_key)
        assert callable(signer.sign)
        assert callable(signer.verify)

    def test_generate_keypair_returns_two_64char_hex_strings(self) -> None:
        signer = Ed25519SignerAdapter()
        priv_hex, pub_hex = signer.generate_keypair()
        assert len(priv_hex) == 64
        assert len(pub_hex) == 64
        # Both decode as valid hex.
        assert bytes.fromhex(priv_hex)
        assert bytes.fromhex(pub_hex)

    def test_derive_public_key_matches_generated_pub(self) -> None:
        signer = Ed25519SignerAdapter()
        priv_hex, pub_hex = signer.generate_keypair()
        # Deriving from the priv must reproduce the pub bit-for-bit.
        assert signer.derive_public_key(priv_hex) == pub_hex

    def test_derive_public_key_rejects_non_hex(self) -> None:
        signer = Ed25519SignerAdapter()
        with pytest.raises(ValueError):
            signer.derive_public_key("not-hex-at-all")

    def test_derive_public_key_rejects_wrong_length(self) -> None:
        signer = Ed25519SignerAdapter()
        with pytest.raises(ValueError):
            signer.derive_public_key("00" * 16)  # 32 hex chars = 16 bytes (needs 32)

    def test_sign_then_verify_roundtrip_succeeds(self) -> None:
        signer = Ed25519SignerAdapter()
        priv_hex, pub_hex = signer.generate_keypair()
        payload = b"payload bytes to sign"
        sig = signer.sign(payload, priv_hex)
        assert isinstance(sig, bytes)
        assert signer.verify(payload, sig, pub_hex) is True

    def test_verify_rejects_tampered_payload(self) -> None:
        signer = Ed25519SignerAdapter()
        priv_hex, pub_hex = signer.generate_keypair()
        sig = signer.sign(b"original", priv_hex)
        assert signer.verify(b"tampered", sig, pub_hex) is False

    def test_verify_rejects_wrong_public_key(self) -> None:
        signer = Ed25519SignerAdapter()
        priv_a, _pub_a = signer.generate_keypair()
        _priv_b, pub_b = signer.generate_keypair()
        sig = signer.sign(b"payload", priv_a)
        assert signer.verify(b"payload", sig, pub_b) is False
