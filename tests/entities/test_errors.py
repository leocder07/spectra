"""Tests for error taxonomy in spectra.entities.errors."""

from __future__ import annotations

import pytest

from spectra.entities.errors import (
    ERRORS,
    AgentError,
    GitError,
    SpectraError,
    SpectraRetryError,
    strip_code_fence,
)

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


# ── AgentError ─────────────────────────────────────────────────


class TestAgentError:
    def test_is_exception(self):
        err = AgentError(ERRORS["SPEC-005"])
        assert isinstance(err, Exception)

    def test_has_error_attribute(self):
        err = AgentError(ERRORS["SPEC-005"])
        assert err.error.code == "SPEC-005"

    def test_message_contains_code(self):
        err = AgentError(ERRORS["SPEC-005"])
        assert "SPEC-005" in str(err)

    def test_message_contains_description(self):
        err = AgentError(ERRORS["SPEC-005"])
        assert "validation failed" in str(err).lower()


# ── GitError ───────────────────────────────────────────────────


class TestGitError:
    def test_is_exception(self):
        err = GitError(ERRORS["SPEC-001"])
        assert isinstance(err, Exception)

    def test_has_error_attribute(self):
        err = GitError(ERRORS["SPEC-001"])
        assert err.error.code == "SPEC-001"

    def test_message_contains_code(self):
        err = GitError(ERRORS["SPEC-001"])
        assert "SPEC-001" in str(err)


# ── SpectraRetryError ─────────────────────────────────────────


class TestSpectraRetryError:
    def test_is_exception(self):
        err = SpectraRetryError(ERRORS["SPEC-002"])
        assert isinstance(err, Exception)

    def test_has_error_attribute(self):
        err = SpectraRetryError(ERRORS["SPEC-002"])
        assert err.error.code == "SPEC-002"

    def test_message_contains_code(self):
        err = SpectraRetryError(ERRORS["SPEC-003"])
        assert "SPEC-003" in str(err)


# ── strip_code_fence ──────────────────────────────────────────


class TestStripCodeFence:
    def test_plain_json(self):
        result = strip_code_fence('{"key": "value"}')
        assert result == '{"key": "value"}'

    def test_json_code_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = strip_code_fence(raw)
        assert result == '{"key": "value"}'

    def test_plain_code_fence(self):
        raw = '```\n{"key": "value"}\n```'
        result = strip_code_fence(raw)
        assert result == '{"key": "value"}'

    def test_json_with_surrounding_text(self):
        raw = 'Here is the result:\n{"key": "value"}\nDone.'
        result = strip_code_fence(raw)
        assert '{"key": "value"}' in result

    def test_whitespace_stripped(self):
        raw = '   \n  {"key": "value"}  \n  '
        result = strip_code_fence(raw)
        assert '{"key": "value"}' in result

    def test_no_json_returns_cleaned(self):
        result = strip_code_fence("just text")
        assert result == "just text"

    def test_empty_string(self):
        result = strip_code_fence("")
        assert result == ""

    def test_multiple_code_blocks_returns_first(self):
        raw = '```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```'
        result = strip_code_fence(raw)
        assert '"a"' in result

    def test_code_fence_with_language_tag(self):
        raw = '```json\n{"findings": []}\n```'
        result = strip_code_fence(raw)
        assert "findings" in result

    def test_nested_braces_preserved(self):
        raw = '{"outer": {"inner": [1, 2]}}'
        result = strip_code_fence(raw)
        assert result == '{"outer": {"inner": [1, 2]}}'

    def test_braces_in_text(self):
        raw = 'Text before {"key": "val"} text after'
        result = strip_code_fence(raw)
        assert '{"key": "val"}' in result

    def test_no_closing_brace(self):
        raw = '{"key": "value"'
        result = strip_code_fence(raw)
        # Should return something, even if partial
        assert len(result) > 0


# ── strip_code_fence edge cases ──────────────────────────────


class TestStripCodeFenceEdgeCases:
    def test_only_backticks(self):
        result = strip_code_fence("```\n```")
        assert isinstance(result, str)

    def test_triple_backtick_no_newline(self):
        with pytest.raises(IndexError):
            strip_code_fence("```json{}```")

    def test_deeply_nested_json(self):
        nested = '{"a": {"b": {"c": {"d": 1}}}}'
        result = strip_code_fence(nested)
        assert "d" in result

    def test_json_array_top_level(self):
        raw = '[{"id": 1}, {"id": 2}]'
        result = strip_code_fence(raw)
        assert "id" in result

    def test_json_with_unicode(self):
        raw = '{"name": "\u00e9\u00e8\u00ea"}'
        result = strip_code_fence(raw)
        assert "\u00e9" in result

    def test_whitespace_only(self):
        result = strip_code_fence("   \n  \t  ")
        assert isinstance(result, str)


# ── SpectraError edge cases ──────────────────────────────────


class TestSpectraErrorEdgeCases:
    def test_non_retryable_zero_retries(self):
        err = SpectraError(code="X-001", message="test", retryable=False)
        assert err.max_retries == 0

    def test_retryable_default_retries_still_zero(self):
        err = SpectraError(code="X-002", message="test", retryable=True)
        assert err.max_retries == 0

    def test_custom_max_retries(self):
        err = SpectraError(code="X-003", message="test", retryable=True, max_retries=5)
        assert err.max_retries == 5

    def test_error_str_representation(self):
        err = SpectraError(code="X-004", message="something broke", retryable=False)
        assert "something broke" in str(err) or "X-004" in str(err)


# ── Error subclasses can be caught ────────────────────────────


class TestErrorCatchability:
    def test_git_error_caught_as_exception(self):
        with pytest.raises(GitError):
            raise GitError(ERRORS["SPEC-001"])

    def test_agent_error_caught_as_exception(self):
        with pytest.raises(AgentError):
            raise AgentError(ERRORS["SPEC-005"])

    def test_retry_error_caught_as_exception(self):
        with pytest.raises(SpectraRetryError):
            raise SpectraRetryError(ERRORS["SPEC-002"])

    @pytest.mark.parametrize(
        "code",
        ["SPEC-001", "SPEC-002", "SPEC-003", "SPEC-004", "SPEC-005", "SPEC-006", "SPEC-007", "SPEC-008", "SPEC-009"],
    )
    def test_all_error_codes_have_message(self, code):
        err = ERRORS[code]
        assert len(err.message) > 0
        assert len(err.code) == 8

    @pytest.mark.parametrize(
        "code",
        ["SPEC-001", "SPEC-002", "SPEC-003", "SPEC-004", "SPEC-005", "SPEC-006", "SPEC-007", "SPEC-008", "SPEC-009"],
    )
    def test_all_errors_are_frozen(self, code):
        err = ERRORS[code]
        with pytest.raises(AttributeError):
            err.code = "CHANGED"
