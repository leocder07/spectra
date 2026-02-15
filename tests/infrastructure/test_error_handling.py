"""Integration tests for the error system wiring across infrastructure."""

from __future__ import annotations

import pytest

from spectra.entities.errors import ERRORS, AgentError, GitError, SpectraError, SpectraRetryError

# ── Error type hierarchy ──────────────────────────────────────


class TestErrorTypeHierarchy:
    def test_spectra_retry_error_has_error_attr(self):
        err = SpectraRetryError(ERRORS["SPEC-002"])
        assert isinstance(err.error, SpectraError)
        assert err.error.code == "SPEC-002"

    def test_git_error_has_error_attr(self):
        err = GitError(ERRORS["SPEC-001"])
        assert isinstance(err.error, SpectraError)
        assert err.error.code == "SPEC-001"

    def test_agent_error_has_error_attr(self):
        err = AgentError(ERRORS["SPEC-005"])
        assert isinstance(err.error, SpectraError)
        assert err.error.code == "SPEC-005"

    def test_all_are_exceptions(self):
        assert issubclass(SpectraRetryError, Exception)
        assert issubclass(GitError, Exception)
        assert issubclass(AgentError, Exception)

    def test_error_message_includes_code(self):
        err = SpectraRetryError(ERRORS["SPEC-002"])
        assert "SPEC-002" in str(err)

    def test_git_error_message_includes_code(self):
        err = GitError(ERRORS["SPEC-001"])
        assert "SPEC-001" in str(err)

    def test_agent_error_message_includes_code(self):
        err = AgentError(ERRORS["SPEC-005"])
        assert "SPEC-005" in str(err)


# ── Retryable error wiring ────────────────────────────────────


class TestRetryableErrorWiring:
    def test_api_unreachable_is_retryable(self):
        err = SpectraRetryError(ERRORS["SPEC-002"])
        assert err.error.retryable is True
        assert err.error.max_retries == 3

    def test_rate_limit_is_retryable(self):
        err = SpectraRetryError(ERRORS["SPEC-003"])
        assert err.error.retryable is True
        assert err.error.max_retries == 3

    def test_git_clone_is_retryable(self):
        assert ERRORS["SPEC-001"].retryable is True
        assert ERRORS["SPEC-001"].max_retries == 2

    def test_validation_failure_is_retryable(self):
        err = AgentError(ERRORS["SPEC-005"])
        assert err.error.retryable is True
        assert err.error.max_retries == 1

    def test_timeout_is_not_retryable(self):
        assert ERRORS["SPEC-006"].retryable is False
        assert ERRORS["SPEC-006"].max_retries == 0

    def test_pipeline_failure_is_not_retryable(self):
        assert ERRORS["SPEC-007"].retryable is False

    def test_critique_failure_is_not_retryable(self):
        assert ERRORS["SPEC-008"].retryable is False

    def test_report_failure_is_not_retryable(self):
        assert ERRORS["SPEC-009"].retryable is False


# ── Retry decorator catches only retryable ────────────────────


class TestRetryDecoratorErrorRouting:
    @pytest.mark.asyncio
    async def test_retries_api_error(self):
        from unittest.mock import AsyncMock

        from spectra.infrastructure.retry_decorator import RetryDecorator

        gw = AsyncMock()
        gw.analyze.side_effect = [
            SpectraRetryError(ERRORS["SPEC-002"]),
            "ok",
        ]
        gw.last_usage = (0, 0)
        retry = RetryDecorator(gw, max_retries=3, backoff_base=0.01)
        result = await retry.analyze("s", "u", "m", 100)
        assert result == "ok"
        assert gw.analyze.call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_retry_timeout_error(self):
        from unittest.mock import AsyncMock

        from spectra.infrastructure.retry_decorator import RetryDecorator

        gw = AsyncMock()
        gw.analyze.side_effect = SpectraRetryError(ERRORS["SPEC-006"])
        gw.last_usage = (0, 0)
        retry = RetryDecorator(gw, max_retries=3, backoff_base=0.01)
        with pytest.raises(SpectraRetryError):
            await retry.analyze("s", "u", "m", 100)
        gw.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_spectra_error_passes_through(self):
        from unittest.mock import AsyncMock

        from spectra.infrastructure.retry_decorator import RetryDecorator

        gw = AsyncMock()
        gw.analyze.side_effect = ValueError("bad")
        gw.last_usage = (0, 0)
        retry = RetryDecorator(gw, max_retries=3, backoff_base=0.01)
        with pytest.raises(ValueError, match="bad"):
            await retry.analyze("s", "u", "m", 100)
        gw.analyze.assert_called_once()


# ── Base agent error wiring ───────────────────────────────────


class TestBaseAgentErrorWiring:
    def test_parse_output_raises_spec005(self):
        from unittest.mock import AsyncMock

        from spectra.infrastructure.agents.base_agent import BaseAgent

        class _Stub(BaseAgent):
            def validate_input(self, user_prompt: str) -> None:
                pass

            def build_prompt(self, user_prompt: str) -> str:
                return user_prompt

            def validate_output(self, parsed):
                return ()

        gw = AsyncMock()
        gw.last_usage = (0, 0)
        agent = _Stub(
            role="architecture",
            gateway=gw,
            model="m",
            system_prompt="s",
            max_tokens=100,
        )
        with pytest.raises(AgentError) as exc_info:
            agent.parse_output("not valid json")
        assert exc_info.value.error.code == "SPEC-005"
        assert exc_info.value.error.retryable is True
