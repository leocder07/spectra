"""Tests for SecretFinding entity and SPEC-011 error code."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spectra.entities.errors import ERRORS, SecretDetectedError
from spectra.entities.models import SecretFinding


class TestSecretFinding:
    def test_construct_minimum_fields(self) -> None:
        finding = SecretFinding(
            file_path=".env",
            line=1,
            pattern_name="aws_access_key",
        )
        assert finding.file_path == ".env"
        assert finding.line == 1
        assert finding.pattern_name == "aws_access_key"

    def test_frozen(self) -> None:
        finding = SecretFinding(file_path=".env", line=2, pattern_name="github_pat")
        with pytest.raises(ValidationError):
            finding.line = 5  # type: ignore[misc]

    def test_line_is_one_based(self) -> None:
        with pytest.raises(ValidationError):
            SecretFinding(file_path=".env", line=0, pattern_name="x")

    def test_equality_by_value(self) -> None:
        a = SecretFinding(file_path=".env", line=3, pattern_name="aws")
        b = SecretFinding(file_path=".env", line=3, pattern_name="aws")
        assert a == b


class TestSpec011:
    def test_registered_in_errors(self) -> None:
        assert "SPEC-011" in ERRORS
        err = ERRORS["SPEC-011"]
        assert err.code == "SPEC-011"
        assert err.retryable is False

    def test_secret_detected_error_carries_findings(self) -> None:
        findings = (
            SecretFinding(file_path=".env", line=1, pattern_name="aws_access_key"),
            SecretFinding(file_path="config.yml", line=42, pattern_name="github_pat"),
        )
        exc = SecretDetectedError(findings)
        assert exc.error.code == "SPEC-011"
        assert exc.findings == findings
