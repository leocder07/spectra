"""Tests for the ScanReceipt frozen entity (Layer 1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from spectra.entities.receipt import ScanReceipt


def _receipt() -> ScanReceipt:
    return ScanReceipt(
        scan_id="00000000000000000000000000000001",
        repo_signature="a" * 32,
        score_card_hash="b" * 64,
        timestamp=datetime(2026, 4, 29, 12, 0, 0, tzinfo=UTC),
        spectra_version="0.6.0",
        signature="c" * 128,
        public_key_fingerprint="d" * 16,
    )


class TestScanReceipt:
    def test_frozen(self) -> None:
        receipt = _receipt()
        with pytest.raises(ValidationError):
            receipt.signature = "tampered"  # type: ignore[misc]

    def test_signed_payload_excludes_signature(self) -> None:
        receipt = _receipt()
        payload = receipt.signed_payload()
        assert "signature" not in payload
        assert payload["scan_id"] == "00000000000000000000000000000001"

    def test_signed_payload_is_deterministic(self) -> None:
        a = _receipt().signed_payload_bytes()
        b = _receipt().signed_payload_bytes()
        assert a == b

    def test_required_fields_validated(self) -> None:
        with pytest.raises(ValidationError):
            ScanReceipt(  # type: ignore[call-arg]
                scan_id="",
                repo_signature="a" * 32,
                score_card_hash="b" * 64,
                timestamp=datetime.now(UTC),
                spectra_version="0.6.0",
                signature="c" * 128,
                public_key_fingerprint="d" * 16,
            )
