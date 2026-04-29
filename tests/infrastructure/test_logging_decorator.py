"""Tests for LoggingDecorator — observer callbacks and delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from spectra.infrastructure.logging_decorator import LoggingDecorator


@pytest.fixture
def mock_gateway() -> AsyncMock:
    gw = AsyncMock()
    gw.analyze.return_value = "result"
    gw.analyze_with_thinking.return_value = "result-thinking"
    gw.last_usage = (200, 100)
    return gw


@pytest.fixture
def mock_observer() -> MagicMock:
    return MagicMock()


class TestLoggingDecorator:
    @pytest.mark.asyncio
    async def test_delegates_to_inner_gateway(self, mock_gateway: AsyncMock, mock_observer: MagicMock):
        decorator = LoggingDecorator(mock_gateway, mock_observer)
        result = await decorator.analyze("sys", "user", "model", 1000)
        assert result == "result"
        mock_gateway.analyze.assert_called_once()
        call_kwargs = mock_gateway.analyze.call_args.kwargs
        assert call_kwargs["system_prompt"] == "sys"
        assert call_kwargs["user_prompt"] == "user"
        assert call_kwargs["model"] == "model"
        assert call_kwargs["max_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_calls_observer_on_complete(self, mock_gateway: AsyncMock, mock_observer: MagicMock):
        decorator = LoggingDecorator(mock_gateway, mock_observer)
        await decorator.analyze("sys", "user", "model", 1000)
        mock_observer.on_stage_complete.assert_called_once()
        call_args = mock_observer.on_stage_complete.call_args
        assert call_args.kwargs["stage"] == "llm_call"
        assert "model" in call_args.kwargs["message"]
        assert "300 tokens" in call_args.kwargs["message"]

    @pytest.mark.asyncio
    async def test_error_propagation(self, mock_gateway: AsyncMock, mock_observer: MagicMock):
        mock_gateway.analyze.side_effect = RuntimeError("boom")
        decorator = LoggingDecorator(mock_gateway, mock_observer)
        with pytest.raises(RuntimeError, match="boom"):
            await decorator.analyze("sys", "user", "model", 1000)
        mock_observer.on_stage_complete.assert_not_called()

    def test_last_usage_propagated(self, mock_gateway: AsyncMock, mock_observer: MagicMock):
        decorator = LoggingDecorator(mock_gateway, mock_observer)
        assert decorator.last_usage == (200, 100)

    @pytest.mark.asyncio
    async def test_analyze_with_thinking_delegates(self, mock_gateway: AsyncMock, mock_observer: MagicMock):
        decorator = LoggingDecorator(mock_gateway, mock_observer)
        result = await decorator.analyze_with_thinking("sys", "user", "model", 1000)
        assert result == "result-thinking"
        mock_gateway.analyze_with_thinking.assert_called_once_with(
            system_prompt="sys",
            user_prompt="user",
            model="model",
            max_tokens=1000,
        )
        mock_observer.on_stage_complete.assert_called_once()
