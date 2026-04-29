"""Tests for RetryDecorator — exponential backoff for transient failures."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spectra.entities.errors import ERRORS, SpectraRetryError
from spectra.infrastructure.retry_decorator import RetryDecorator


@pytest.fixture
def mock_gateway() -> AsyncMock:
    gw = AsyncMock()
    gw.analyze.return_value = "ok"
    gw.analyze_with_thinking.return_value = "ok-thinking"
    gw.last_usage = (100, 50)
    return gw


class TestRetryDecorator:
    @pytest.mark.asyncio
    async def test_success_no_retry(self, mock_gateway: AsyncMock):
        retry = RetryDecorator(mock_gateway, max_retries=3, backoff_base=0.01)
        result = await retry.analyze("sys", "user", "model", 1000)
        assert result == "ok"
        mock_gateway.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self, mock_gateway: AsyncMock):
        mock_gateway.analyze.side_effect = [
            SpectraRetryError(ERRORS["SPEC-002"]),
            "ok",
        ]
        retry = RetryDecorator(mock_gateway, max_retries=3, backoff_base=0.01)
        result = await retry.analyze("sys", "user", "model", 1000)
        assert result == "ok"
        assert mock_gateway.analyze.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self, mock_gateway: AsyncMock):
        mock_gateway.analyze.side_effect = [
            SpectraRetryError(ERRORS["SPEC-003"]),
            "ok",
        ]
        retry = RetryDecorator(mock_gateway, max_retries=3, backoff_base=0.01)
        result = await retry.analyze("sys", "user", "model", 1000)
        assert result == "ok"
        assert mock_gateway.analyze.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_retries(self, mock_gateway: AsyncMock):
        mock_gateway.analyze.side_effect = SpectraRetryError(ERRORS["SPEC-002"])
        retry = RetryDecorator(mock_gateway, max_retries=2, backoff_base=0.01)
        with pytest.raises(SpectraRetryError):
            await retry.analyze("sys", "user", "model", 1000)
        assert mock_gateway.analyze.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_non_retryable_error_passes_through(self, mock_gateway: AsyncMock):
        mock_gateway.analyze.side_effect = ValueError("bad input")
        retry = RetryDecorator(mock_gateway, max_retries=3, backoff_base=0.01)
        with pytest.raises(ValueError, match="bad input"):
            await retry.analyze("sys", "user", "model", 1000)
        mock_gateway.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_retryable_spectra_error_not_retried(self, mock_gateway: AsyncMock):
        mock_gateway.analyze.side_effect = SpectraRetryError(ERRORS["SPEC-006"])
        retry = RetryDecorator(mock_gateway, max_retries=3, backoff_base=0.01)
        with pytest.raises(SpectraRetryError):
            await retry.analyze("sys", "user", "model", 1000)
        mock_gateway.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_with_thinking_delegates(self, mock_gateway: AsyncMock):
        retry = RetryDecorator(mock_gateway, max_retries=1, backoff_base=0.01)
        result = await retry.analyze_with_thinking("sys", "user", "model", 1000)
        assert result == "ok-thinking"
        mock_gateway.analyze_with_thinking.assert_called_once()
        call_kwargs = mock_gateway.analyze_with_thinking.call_args.kwargs
        assert call_kwargs["system_prompt"] == "sys"
        assert call_kwargs["user_prompt"] == "user"
        assert call_kwargs["model"] == "model"
        assert call_kwargs["max_tokens"] == 1000

    def test_last_usage_propagated(self, mock_gateway: AsyncMock):
        retry = RetryDecorator(mock_gateway, max_retries=3)
        assert retry.last_usage == (100, 50)

    def test_last_usage_default(self):
        inner = AsyncMock(spec=[])  # no last_usage attribute
        retry = RetryDecorator(inner)
        assert retry.last_usage == (0, 0)

    @pytest.mark.asyncio
    async def test_analyze_with_thinking_retries(self, mock_gateway: AsyncMock):
        mock_gateway.analyze_with_thinking.side_effect = [
            SpectraRetryError(ERRORS["SPEC-002"]),
            SpectraRetryError(ERRORS["SPEC-003"]),
            "ok-thinking",
        ]
        retry = RetryDecorator(mock_gateway, max_retries=3, backoff_base=0.01)
        result = await retry.analyze_with_thinking("sys", "user", "model", 1000)
        assert result == "ok-thinking"
        assert mock_gateway.analyze_with_thinking.call_count == 3

    @pytest.mark.asyncio
    async def test_zero_retries_fails_immediately(self, mock_gateway: AsyncMock):
        mock_gateway.analyze.side_effect = SpectraRetryError(ERRORS["SPEC-002"])
        retry = RetryDecorator(mock_gateway, max_retries=0, backoff_base=0.01)
        with pytest.raises(SpectraRetryError):
            await retry.analyze("sys", "user", "model", 1000)
        mock_gateway.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_on_last_retry(self, mock_gateway: AsyncMock):
        mock_gateway.analyze.side_effect = [
            SpectraRetryError(ERRORS["SPEC-002"]),
            SpectraRetryError(ERRORS["SPEC-003"]),
            SpectraRetryError(ERRORS["SPEC-002"]),
            "ok",
        ]
        retry = RetryDecorator(mock_gateway, max_retries=3, backoff_base=0.01)
        result = await retry.analyze("sys", "user", "model", 1000)
        assert result == "ok"
        assert mock_gateway.analyze.call_count == 4

    def test_default_max_retries(self, mock_gateway: AsyncMock):
        retry = RetryDecorator(mock_gateway)
        assert retry._max_retries == 3

    def test_default_backoff_base(self, mock_gateway: AsyncMock):
        retry = RetryDecorator(mock_gateway)
        assert retry._backoff_base == 1.0

    def test_custom_max_retries(self, mock_gateway: AsyncMock):
        retry = RetryDecorator(mock_gateway, max_retries=5)
        assert retry._max_retries == 5

    def test_custom_backoff_base(self, mock_gateway: AsyncMock):
        retry = RetryDecorator(mock_gateway, backoff_base=2.0)
        assert retry._backoff_base == 2.0
