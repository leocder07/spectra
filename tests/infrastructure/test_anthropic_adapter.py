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
            message=SimpleNamespace(usage=SimpleNamespace(input_tokens=input_tokens)),
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
    with patch("spectra.infrastructure.anthropic_adapter.anthropic.AsyncAnthropic") as mock_cls:
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
        # Check only load-bearing kwargs; tolerate optional kwargs added by
        # adapter (output_config, cache_control, extra_headers, etc.).
        client.messages.stream.assert_called_once()
        call_kwargs = client.messages.stream.call_args.kwargs
        assert call_kwargs["model"] == "claude-test"
        assert call_kwargs["max_tokens"] == 2000
        assert call_kwargs["system"] == "sys prompt"
        assert call_kwargs["messages"] == [{"role": "user", "content": "user prompt"}]

    @pytest.mark.asyncio
    async def test_updates_last_usage(self, adapter):
        a, client = adapter
        events = _make_events(input_tokens=150, output_tokens=75)
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        await a.analyze("sys", "user", "model", 1000)
        assert a.last_usage == (150, 75)


def _mock_thinking_response(
    text: str = "final answer",
    input_tokens: int = 200,
    output_tokens: int = 100,
):
    """Build a fake response with thinking + text blocks."""
    thinking_block = SimpleNamespace(type="thinking", thinking="reasoning...")
    text_block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[thinking_block, text_block], usage=usage)


class _FakeThinkingStream:
    """Mock stream that returns a final message via get_final_message()."""

    def __init__(self, response, error=None):
        self._response = response
        self._error = error

    async def __aenter__(self):
        if self._error:
            raise self._error
        return self

    async def __aexit__(self, *args):
        pass

    async def get_final_message(self):
        return self._response


class TestAnalyzeWithThinking:
    @pytest.mark.asyncio
    async def test_returns_text_block(self, adapter):
        a, client = adapter
        resp = _mock_thinking_response("final answer")
        client.messages.stream = MagicMock(return_value=_FakeThinkingStream(resp))
        result = await a.analyze_with_thinking("sys", "user", "model", 4000)
        assert result == "final answer"

    @pytest.mark.asyncio
    async def test_enables_adaptive_thinking(self, adapter):
        a, client = adapter
        resp = _mock_thinking_response()
        client.messages.stream = MagicMock(return_value=_FakeThinkingStream(resp))
        await a.analyze_with_thinking("sys", "user", "model", 4000)
        call_kwargs = client.messages.stream.call_args.kwargs
        # Adaptive thinking is enabled; display mode (e.g. "summarized")
        # may also be configured but is not load-bearing for this test.
        assert call_kwargs["thinking"]["type"] == "adaptive"

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty(self, adapter):
        a, client = adapter
        thinking_only = SimpleNamespace(type="thinking", thinking="hmm")
        usage = SimpleNamespace(input_tokens=50, output_tokens=25)
        resp = SimpleNamespace(content=[thinking_only], usage=usage)
        client.messages.stream = MagicMock(return_value=_FakeThinkingStream(resp))
        result = await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert result == ""

    @pytest.mark.asyncio
    async def test_updates_last_usage(self, adapter):
        a, client = adapter
        resp = _mock_thinking_response(input_tokens=300, output_tokens=150)
        client.messages.stream = MagicMock(return_value=_FakeThinkingStream(resp))
        await a.analyze_with_thinking("sys", "user", "model", 4000)
        assert a.last_usage == (300, 150)


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_api_connection_error_becomes_spec002(self, adapter):
        import anthropic

        a, client = adapter
        client.messages.stream = MagicMock(
            return_value=_FakeStream([], error=anthropic.APIConnectionError(request=MagicMock()))
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
            return_value=_FakeThinkingStream(None, error=anthropic.APIConnectionError(request=MagicMock()))
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
            return_value=_FakeThinkingStream(
                None,
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
        with patch("spectra.infrastructure.anthropic_adapter.anthropic.AsyncAnthropic"):
            a = AnthropicAdapter(api_key="test")
            assert a.last_usage == (0, 0)


# ── Empty / malformed response edge cases ────────────────────


class TestEmptyResponse:
    @pytest.mark.asyncio
    async def test_no_content_blocks_returns_empty(self, adapter):
        a, client = adapter
        events = [
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(usage=SimpleNamespace(input_tokens=10)),
            ),
            SimpleNamespace(
                type="message_delta",
                usage=SimpleNamespace(output_tokens=0),
            ),
        ]
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        result = await a.analyze("sys", "user", "model", 1000)
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_text_delta(self, adapter):
        a, client = adapter
        events = _make_events(text="")
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        result = await a.analyze("sys", "user", "model", 1000)
        assert result == ""

    @pytest.mark.asyncio
    async def test_whitespace_only_response(self, adapter):
        a, client = adapter
        events = _make_events(text="   \n  ")
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        result = await a.analyze("sys", "user", "model", 1000)
        assert result.strip() == ""

    @pytest.mark.asyncio
    async def test_zero_input_tokens(self, adapter):
        a, client = adapter
        events = _make_events(input_tokens=0, output_tokens=0)
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        await a.analyze("sys", "user", "model", 1000)
        assert a.last_usage == (0, 0)


class TestThinkingEmptyResponse:
    @pytest.mark.asyncio
    async def test_no_text_blocks_returns_empty(self, adapter):
        a, client = adapter
        thinking_only = SimpleNamespace(type="thinking", thinking="deep thought")
        usage = SimpleNamespace(input_tokens=50, output_tokens=25)
        resp = SimpleNamespace(content=[thinking_only], usage=usage)
        client.messages.stream = MagicMock(return_value=_FakeThinkingStream(resp))
        result = await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_content_list(self, adapter):
        a, client = adapter
        usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        resp = SimpleNamespace(content=[], usage=usage)
        client.messages.stream = MagicMock(return_value=_FakeThinkingStream(resp))
        result = await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert result == ""

    @pytest.mark.asyncio
    async def test_text_block_empty_string(self, adapter):
        a, client = adapter
        text_block = SimpleNamespace(type="text", text="")
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        resp = SimpleNamespace(content=[text_block], usage=usage)
        client.messages.stream = MagicMock(return_value=_FakeThinkingStream(resp))
        result = await a.analyze_with_thinking("sys", "user", "model", 2000)
        assert result == ""


class TestAuthenticationError:
    @pytest.mark.asyncio
    async def test_authentication_error_raises_value_error(self, adapter):
        """AuthenticationError from Anthropic API raises ValueError with 'Invalid API key'."""
        import anthropic

        a, client = adapter
        response = MagicMock()
        response.status_code = 401
        response.headers = {}
        client.messages.stream = MagicMock(
            return_value=_FakeStream(
                [],
                error=anthropic.AuthenticationError(
                    message="invalid api key",
                    response=response,
                    body=None,
                ),
            )
        )
        with pytest.raises(ValueError, match="Invalid API key"):
            await a.analyze("sys", "user", "model", 1000)

    @pytest.mark.asyncio
    async def test_internal_server_error_raises_retry_error(self, adapter):
        """InternalServerError from Anthropic API raises SpectraRetryError (SPEC-002)."""
        import anthropic

        a, client = adapter
        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        client.messages.stream = MagicMock(
            return_value=_FakeStream(
                [],
                error=anthropic.InternalServerError(
                    message="internal server error",
                    response=response,
                    body=None,
                ),
            )
        )
        with pytest.raises(SpectraRetryError) as exc_info:
            await a.analyze("sys", "user", "model", 1000)
        assert exc_info.value.error.code == "SPEC-002"


class TestMultipleContentBlocks:
    @pytest.mark.asyncio
    async def test_multiple_text_deltas_concatenated(self, adapter):
        a, client = adapter
        events = [
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(usage=SimpleNamespace(input_tokens=50)),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text="hello "),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text="world"),
            ),
            SimpleNamespace(
                type="message_delta",
                usage=SimpleNamespace(output_tokens=10),
            ),
        ]
        client.messages.stream = MagicMock(return_value=_FakeStream(events))
        result = await a.analyze("sys", "user", "model", 1000)
        assert result == "hello world"
