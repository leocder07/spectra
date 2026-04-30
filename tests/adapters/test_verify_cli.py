"""Tests for the ``spectra verify <report.json>`` CLI command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from spectra.adapters.cli_controller import app, set_verifier
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
    verify_receipt,
)

if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _dim(name: str, score: float, weight: float) -> DimensionScore:
    return DimensionScore(
        dimension=name,  # type: ignore[arg-type]
        score=score,
        grade=score_to_grade(score),
        findings_count=0,
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
        total_findings=0,
    )


def _report_with_receipt(tmp_path: Path) -> tuple[AnalysisReport, bytes]:
    keystore = InMemoryKeyStore(public_key_path=tmp_path / "receipt.pub")
    signer = ReceiptSigner(keystore=keystore)
    sample = AnalysisReport(
        repo_url="https://example.com/r",
        repo_name="r",
        score_card=_scorecard(),
        findings=(),
        analysis_duration_seconds=1.0,
        total_tokens_used=100,
        total_cost_usd=0.01,
        agents_used=("security",),
    )
    receipt = signer.sign(sample, scan_id=new_event_id())
    signed = sample.model_copy(update={"receipt": receipt})
    return signed, keystore.public_key_pem() or b""


def _write_report(tmp_path: Path, report: AnalysisReport) -> Path:
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


class TestVerifyCli:
    def test_valid_report_exits_zero(self, tmp_path: Path) -> None:
        report, pub_pem = _report_with_receipt(tmp_path)
        report_path = _write_report(tmp_path, report)
        pub_path = tmp_path / "receipt.pub"
        pub_path.write_bytes(pub_pem)
        set_verifier(verify_receipt)
        result = runner.invoke(app, ["verify", str(report_path), "--key", str(pub_path)])
        assert result.exit_code == 0
        assert "verified" in result.stdout.lower()

    def test_tampered_report_exits_one(self, tmp_path: Path) -> None:
        report, pub_pem = _report_with_receipt(tmp_path)
        # Mutate the score card so the recomputed hash mismatches.
        new_sc = report.score_card.model_copy(update={"overall_score": 0.0})
        tampered = report.model_copy(update={"score_card": new_sc})
        report_path = _write_report(tmp_path, tampered)
        pub_path = tmp_path / "receipt.pub"
        pub_path.write_bytes(pub_pem)
        set_verifier(verify_receipt)
        result = runner.invoke(app, ["verify", str(report_path), "--key", str(pub_path)])
        assert result.exit_code == 1

    def test_report_without_receipt_exits_one(self, tmp_path: Path) -> None:
        sample = AnalysisReport(
            repo_url="https://example.com/r",
            repo_name="r",
            score_card=_scorecard(),
            findings=(),
            analysis_duration_seconds=1.0,
            total_tokens_used=100,
            total_cost_usd=0.01,
            agents_used=("security",),
        )
        report_path = _write_report(tmp_path, sample)
        set_verifier(verify_receipt)
        result = runner.invoke(app, ["verify", str(report_path)])
        assert result.exit_code == 1
        assert "no receipt" in result.stdout.lower()

    def test_signature_replay_with_different_payload_caught(self, tmp_path: Path) -> None:
        report, pub_pem = _report_with_receipt(tmp_path)
        # Splice a fake fingerprint to simulate signature transplant.
        bad_receipt = ScanReceipt(
            scan_id=report.receipt.scan_id,  # type: ignore[union-attr]
            repo_signature=report.receipt.repo_signature,  # type: ignore[union-attr]
            score_card_hash="0" * 64,
            timestamp=report.receipt.timestamp,  # type: ignore[union-attr]
            spectra_version=report.receipt.spectra_version,  # type: ignore[union-attr]
            signature=report.receipt.signature,  # type: ignore[union-attr]
            public_key_fingerprint=report.receipt.public_key_fingerprint,  # type: ignore[union-attr]
        )
        spliced = report.model_copy(update={"receipt": bad_receipt})
        report_path = _write_report(tmp_path, spliced)
        pub_path = tmp_path / "receipt.pub"
        pub_path.write_bytes(pub_pem)
        set_verifier(verify_receipt)
        result = runner.invoke(app, ["verify", str(report_path), "--key", str(pub_path)])
        assert result.exit_code == 1

    def test_invalid_json_exits_one(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        set_verifier(verify_receipt)
        result = runner.invoke(app, ["verify", str(bad)])
        assert result.exit_code == 1

    def test_uses_default_pubkey_path_when_omitted(self, tmp_path: Path) -> None:
        # Confirms that the CLI falls back to a configurable default.
        report, pub_pem = _report_with_receipt(tmp_path)
        report_path = _write_report(tmp_path, report)
        default_pub = tmp_path / "default-receipt.pub"
        default_pub.write_bytes(pub_pem)
        set_verifier(verify_receipt, default_public_key_path=default_pub)
        result = runner.invoke(app, ["verify", str(report_path)])
        assert result.exit_code == 0
        assert json.loads(report_path.read_text())["receipt"]["scan_id"]
