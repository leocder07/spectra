"""Tests for error taxonomy in spectra.entities.errors."""

from __future__ import annotations

import pytest

from spectra.entities.errors import ERRORS, SpectraError

# ── SpectraError ────────────────────────────────────────────────


class TestSpectraError:
    def test_create(self):
        err = SpectraError(
            code="TEST-001",
            message="Test error",
            retryable=True,
            max_retries=2,
        )
        assert err.code == "TEST-001"
        assert err.message == "Test error"
        assert err.retryable is True
        assert err.max_retries == 2

    def test_frozen(self):
        err = SpectraError(
            code="TEST-001",
            message="Test error",
            retryable=False,
        )
        with pytest.raises(AttributeError):
            err.code = "CHANGED"

    def test_default_max_retries(self):
        err = SpectraError(
            code="TEST-001",
            message="Test",
            retryable=False,
        )
        assert err.max_retries == 0


# ── ERRORS dict ─────────────────────────────────────────────────


class TestErrorsDict:
    def test_all_nine_codes_present(self):
        expected_codes = {f"SPEC-{i:03d}" for i in range(1, 10)}
        assert set(ERRORS.keys()) == expected_codes

    def test_code_matches_key(self):
        for key, error in ERRORS.items():
            assert error.code == key

    def test_retryable_errors(self):
        retryable = {k for k, v in ERRORS.items() if v.retryable}
        assert retryable == {"SPEC-001", "SPEC-002", "SPEC-003", "SPEC-005"}

    def test_non_retryable_errors(self):
        non_retryable = {k for k, v in ERRORS.items() if not v.retryable}
        assert non_retryable == {
            "SPEC-004",
            "SPEC-006",
            "SPEC-007",
            "SPEC-008",
            "SPEC-009",
        }

    @pytest.mark.parametrize(
        ("code", "expected_retries"),
        [
            ("SPEC-001", 2),
            ("SPEC-002", 3),
            ("SPEC-003", 3),
            ("SPEC-005", 1),
        ],
    )
    def test_retry_counts(self, code, expected_retries):
        assert ERRORS[code].max_retries == expected_retries

    def test_non_retryable_have_zero_retries(self):
        for code in ("SPEC-004", "SPEC-006", "SPEC-007", "SPEC-008", "SPEC-009"):
            assert ERRORS[code].max_retries == 0

    def test_all_have_messages(self):
        for error in ERRORS.values():
            assert len(error.message) > 0
