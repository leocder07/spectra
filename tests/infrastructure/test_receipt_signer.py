"""Tests for the Ed25519 receipt signer + verifier (Layer 4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from spectra.entities.audit import new_event_id
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    ScoreCard,
    score_to_grade,
)
from spectra.entities.receipt import ScanReceipt
from spectra.infrastructure.receipt_signer import (
    InMemoryKeyStore,
    ReceiptSigner,
    compute_score_card_hash,
    verify_receipt,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tmp_keystore(tmp_path: Path) -> InMemoryKeyStore:
    """Fresh in-memory keystore + tmp public-key path for each test."""
    return InMemoryKeyStore(public_key_path=tmp_path / "receipt.pub")


def _dim(name: str, score: float, weight: float) -> DimensionScore:
    return DimensionScore(
        dimension=name,  # type: ignore[arg-type]
        score=score,
        grade=score_to_grade(score),
        findings_count=1,
        weight=weight,
    )


def _scorecard() -> ScoreCard:
    dims = (
        _dim("architecture", 85.0, 0.25),
        _dim("security", 90.0, 0.25),
        _dim("quality", 78.0, 0.20),
        _dim("documentation", 70.0, 0.10),
        _dim("maintainability", 82.0, 0.10),
        _dim("performance", 88.0, 0.10),
    )
    overall = sum(d.score * d.weight for d in dims)
    return ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dims,
        total_findings=6,
    )


def _report(score_card: ScoreCard | None = None) -> AnalysisReport:
    return AnalysisReport(
        repo_url="https://example.com/repo",
        repo_name="repo",
        score_card=score_card or _scorecard(),
        findings=(),
        analysis_duration_seconds=1.0,
        total_tokens_used=100,
        total_cost_usd=0.01,
        agents_used=("security",),
    )


class TestReceiptSigner:
    def test_keypair_generated_on_first_use(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        assert tmp_keystore.public_key_pem() is None
        signer.sign(_report())
        assert tmp_keystore.public_key_pem() is not None

    def test_keypair_persisted_across_calls(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        first = signer.sign(_report())
        second = signer.sign(_report())
        assert first.public_key_fingerprint == second.public_key_fingerprint

    def test_public_key_written_to_disk(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        signer.sign(_report())
        assert tmp_keystore.public_key_path.exists()
        text = tmp_keystore.public_key_path.read_text(encoding="utf-8")
        assert "BEGIN PUBLIC KEY" in text

    def test_receipt_round_trip_verifies(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        report = _report()
        receipt = signer.sign(report)
        assert verify_receipt(receipt, tmp_keystore.public_key_pem()) is True

    def test_tampered_score_breaks_verification(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        receipt = signer.sign(_report())
        tampered = ScanReceipt(
            scan_id=receipt.scan_id,
            repo_signature=receipt.repo_signature,
            score_card_hash="0" * 64,  # mutated
            timestamp=receipt.timestamp,
            spectra_version=receipt.spectra_version,
            signature=receipt.signature,
            public_key_fingerprint=receipt.public_key_fingerprint,
        )
        assert verify_receipt(tampered, tmp_keystore.public_key_pem()) is False

    def test_tampered_signature_breaks_verification(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        receipt = signer.sign(_report())
        bogus = ScanReceipt(
            scan_id=receipt.scan_id,
            repo_signature=receipt.repo_signature,
            score_card_hash=receipt.score_card_hash,
            timestamp=receipt.timestamp,
            spectra_version=receipt.spectra_version,
            signature="0" * 128,
            public_key_fingerprint=receipt.public_key_fingerprint,
        )
        assert verify_receipt(bogus, tmp_keystore.public_key_pem()) is False

    def test_sign_uses_supplied_scan_id(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        scan_id = new_event_id()
        receipt = signer.sign(_report(), scan_id=scan_id)
        assert receipt.scan_id == scan_id

    def test_sign_uses_supplied_timestamp(self, tmp_keystore: InMemoryKeyStore) -> None:
        signer = ReceiptSigner(keystore=tmp_keystore)
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        receipt = signer.sign(_report(), timestamp=ts)
        assert receipt.timestamp == ts


class TestComputeScoreCardHash:
    def test_hash_is_64_hex(self) -> None:
        digest = compute_score_card_hash(_scorecard())
        assert len(digest) == 64

    def test_hash_deterministic(self) -> None:
        sc = _scorecard()
        assert compute_score_card_hash(sc) == compute_score_card_hash(sc)

    def test_hash_changes_with_score_change(self) -> None:
        sc = _scorecard()
        # Build an altered score card with a different overall score.
        altered = sc.model_copy(update={"overall_score": sc.overall_score + 1})
        assert compute_score_card_hash(sc) != compute_score_card_hash(altered)
