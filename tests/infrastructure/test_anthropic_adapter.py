"""Tests for AnthropicAdapter — mocked streaming Anthropic API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra.entities.errors import SpectraRetryError
from spectra.infrastructure.anthropic_adapter import AnthropicAdapter


class _FakeStream:
    """Mock async context manager + async iterator for streaming responses."""

    def __init__(self, events: list, error: Exception | None = None):
        self._events = events
        self._error = error

    async def __aenter__(self):
        if self._error:
            raise self._error
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


def _make_events(
    text: str = "response text",
    input_tokens: int = 100,
    output_tokens: int = 50,
):
    """Build fake streaming events for a standard response."""
    return [
        SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                usage=SimpleNamespace(input_tokens=input_tokens)
            ),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(text=text),
        ),
        SimpleNamespace(
            type="message_delta",
            usage=SimpleNamespace(output_tokens=output_tokens),
        ),
    ]


@pytest.fixture
def adapter():
    """Create adapter with mocked client."""
    with patch(
        "spectra.infrastructure.anthropic_adapter.anthropic.AsyncAnthropic"
    ) as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        a = AnthropicAdapter(api_key="test-key")
        a._client = mock_client
        yield a, mock_client


class TestAnalyze:
    @pytest.mark.asyncio
    async def test_returns_response_text(self, adapter):
        a, client = adapter
        events = _make_events("hello world")
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        result = await a.analyze("system", "user", "model-1", 1000)
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_passes_params_to_client(self, adapter):
        a, client = adapter
        events = _make_events()
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        await a.analyze("sys prompt", "user prompt", "claude-test", 2000)
        client.messages.stream.assert_called_once_with(
            model="claude-test",
            max_tokens=2000,
            system="sys prompt",
            messages=[{"role": "user", "content": "user prompt"}],
        )

    @pytest.mark.asyncio
    async def test_updates_last_usage(self, adapter):
        a, client = adapter
        events = _make_events(input_tokens=150, output_tokens=75)
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        await a.analyze("sys", "user", "model", 1000)
        assert a.last_usage == (150, 75)


class TestAnalyzeWithThinking:
    @pytest.mark.asyncio
    async def test_returns_text_block(self, adapter):
        a, client = adapter
        events = _make_events("final answer", 200, 100)
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        result = await a.analyze_with_thinking("sys", "user", "model", 4000)
        assert result == "final answer"

    @pytest.mark.asyncio
    async def test_enables_thinking_param(self, adapter):
        a, client = adapter
        events = _make_events()
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        await a.analyze_with_thinking("sys", "user", "model", 4000)
        call_kwargs = client.messages.stream.call_args.kwargs
        assert call_kwargs["thinking"] == {
            "type": "adaptive",
            "budget_tokens": 2000,
        }

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty(self, adapter):
        a, client = adapter
        # Only message events, no content_block_delta with text
        events = [
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=50)
                ),
            ),
            SimpleNamespace(
                type="message_delta",
                usage=SimpleNamespace(output_tokens=25),
            ),
        ]
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        result = await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert result == ""

    @pytest.mark.asyncio
    async def test_updates_last_usage(self, adapter):
        a, client = adapter
        events = _make_events(input_tokens=300, output_tokens=150)
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        await a.analyze_with_thinking("sys", "user", "model", 4000)
        assert a.last_usage == (300, 150)


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_api_connection_error_becomes_spec002(self, adapter):
        import anthropic

        a, client = adapter
        client.messages.stream = MagicMock(
            return_value=_FakeStream(
                [], error=anthropic.APIConnectionError(request=MagicMock())
            )
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
        client.messages.stream = MagicMock(
            return_value=_FakeStream(
                [],
                error=anthropic.RateLimitError(
                    message="rate limited",
                    response=response,
                    body=None,
                ),
            )
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.analyze("sys", "user", "model", 1000)
        assert exc_info.value.error.code == "SPEC-003"

    @pytest.mark.asyncio
    async def test_api_connection_error_in_thinking_mode(self, adapter):
        import anthropic

        a, client = adapter
        client.messages.stream = MagicMock(
            return_value=_FakeStream(
                [], error=anthropic.APIConnectionError(request=MagicMock())
            )
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
        client.messages.stream = MagicMock(
            return_value=_FakeStream(
                [],
                error=anthropic.RateLimitError(
                    message="rate limited",
                    response=response,
                    body=None,
                ),
            )
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert exc_info.value.error.code == "SPEC-003"


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_client_close(self, adapter):
        a, client = adapter
        client.close = AsyncMock()
        await a.close()
        client.close.assert_called_once()


class TestLastUsage:
    def test_initial_usage_is_zero(self):
        with patch(
            "spectra.infrastructure.anthropic_adapter.anthropic.AsyncAnthropic"
        ):
            a = AnthropicAdapter(api_key="test")
            assert a.last_usage == (0, 0)
