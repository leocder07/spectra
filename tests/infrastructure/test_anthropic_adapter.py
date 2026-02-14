"""Tests for AnthropicAdapter — mocked Anthropic API interactions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra.entities.errors import SpectraRetryError
from spectra.infrastructure.anthropic_adapter import AnthropicAdapter


def _mock_response(text: str = "response text", input_tokens: int = 100, output_tokens: int = 50):
    """Build a fake Anthropic API response object."""
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[block], usage=usage)


def _mock_thinking_response(
    thinking_text: str = "thinking...",
    response_text: str = "final answer",
    input_tokens: int = 200,
    output_tokens: int = 100,
):
    """Build a fake Anthropic response with thinking + text blocks."""
    thinking_block = SimpleNamespace(type="thinking", thinking=thinking_text)
    text_block = SimpleNamespace(type="text", text=response_text)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[thinking_block, text_block], usage=usage)


@pytest.fixture
def adapter():
    """Create adapter with mocked client."""
    with patch("spectra.infrastructure.anthropic_adapter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        a = AnthropicAdapter(api_key="test-key")
        a._client = mock_client
        yield a, mock_client


class TestAnalyze:
    @pytest.mark.asyncio
    async def test_returns_response_text(self, adapter):
        a, client = adapter
        client.messages.create = AsyncMock(return_value=_mock_response("hello world"))
        result = await a.analyze("system", "user", "model-1", 1000)
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_passes_params_to_client(self, adapter):
        a, client = adapter
        client.messages.create = AsyncMock(return_value=_mock_response())
        await a.analyze("sys prompt", "user prompt", "claude-test", 2000)
        client.messages.create.assert_called_once_with(
            model="claude-test",
            max_tokens=2000,
            system="sys prompt",
            messages=[{"role": "user", "content": "user prompt"}],
        )

    @pytest.mark.asyncio
    async def test_updates_last_usage(self, adapter):
        a, client = adapter
        client.messages.create = AsyncMock(
            return_value=_mock_response(input_tokens=150, output_tokens=75)
        )
        await a.analyze("sys", "user", "model", 1000)
        assert a.last_usage == (150, 75)


class TestAnalyzeWithThinking:
    @pytest.mark.asyncio
    async def test_returns_text_block(self, adapter):
        a, client = adapter
        client.messages.create = AsyncMock(
            return_value=_mock_thinking_response(response_text="final answer")
        )
        result = await a.analyze_with_thinking("sys", "user", "model", 4000)
        assert result == "final answer"

    @pytest.mark.asyncio
    async def test_enables_thinking_param(self, adapter):
        a, client = adapter
        client.messages.create = AsyncMock(
            return_value=_mock_thinking_response()
        )
        await a.analyze_with_thinking("sys", "user", "model", 4000)
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2000}

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_string(self, adapter):
        a, client = adapter
        # Response with only a thinking block, no text block
        thinking_only = SimpleNamespace(type="thinking", thinking="hmm")
        usage = SimpleNamespace(input_tokens=50, output_tokens=25)
        response = SimpleNamespace(content=[thinking_only], usage=usage)
        client.messages.create = AsyncMock(return_value=response)
        result = await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert result == ""

    @pytest.mark.asyncio
    async def test_updates_last_usage(self, adapter):
        a, client = adapter
        client.messages.create = AsyncMock(
            return_value=_mock_thinking_response(input_tokens=300, output_tokens=150)
        )
        await a.analyze_with_thinking("sys", "user", "model", 4000)
        assert a.last_usage == (300, 150)


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_api_connection_error_becomes_spec002(self, adapter):
        import anthropic

        a, client = adapter
        client.messages.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.analyze("sys", "user", "model", 1000)
        assert exc_info.value.error.code == "SPEC-002"

    @pytest.mark.asyncio
    async def test_rate_limit_error_becomes_spec003(self, adapter):
        import anthropic

        a, client = adapter
        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited",
                response=response,
                body=None,
            )
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.analyze("sys", "user", "model", 1000)
        assert exc_info.value.error.code == "SPEC-003"

    @pytest.mark.asyncio
    async def test_api_connection_error_in_thinking_mode(self, adapter):
        import anthropic

        a, client = adapter
        client.messages.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert exc_info.value.error.code == "SPEC-002"

    @pytest.mark.asyncio
    async def test_rate_limit_error_in_thinking_mode(self, adapter):
        import anthropic

        a, client = adapter
        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited",
                response=response,
                body=None,
            )
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert exc_info.value.error.code == "SPEC-003"


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_client_close(self, adapter):
        a, client = adapter
        await a.close()
        client.close.assert_called_once()


class TestLastUsage:
    def test_initial_usage_is_zero(self):
        with patch("spectra.infrastructure.anthropic_adapter.anthropic.AsyncAnthropic"):
            a = AnthropicAdapter(api_key="test")
            assert a.last_usage == (0, 0)
