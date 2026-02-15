"""Anthropic API adapter — implements LLMGateway Protocol with streaming.

Provides ``AnthropicAdapter`` which wraps the ``anthropic.AsyncAnthropic``
client with streaming support and maps API errors to Spectra error codes
(SPEC-002 for connection failures, SPEC-003 for rate limits).
"""

from __future__ import annotations

import logging

import anthropic
import httpx

from spectra.entities.errors import ERRORS, SpectraRetryError

_log = logging.getLogger("spectra.adapter")

_MAX_CONNECTIONS = 10


class AnthropicAdapter:
    """Async Anthropic client implementing the LLMGateway protocol.

    Uses streaming for standard calls and adaptive thinking for
    CritiqueAgent calls. Connection pooling is configured via httpx
    with a fixed limit of 10 keep-alive connections.
    """

    def __init__(self, api_key: str) -> None:
        """Initialize the adapter with an Anthropic API key.

        Args:
            api_key: Anthropic API key (``sk-ant-*``).
        """
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            http_client=httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=_MAX_CONNECTIONS,
                    max_keepalive_connections=_MAX_CONNECTIONS,
                ),
            ),
        )
        self._last_usage: tuple[int, int] = (0, 0)

    @property
    def last_usage(self) -> tuple[int, int]:
        """(input_tokens, output_tokens) from the most recent API call."""
        return self._last_usage

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        """Send a streaming inference request.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User-level content.
            model: Anthropic model identifier.
            max_tokens: Maximum response tokens.

        Returns:
            Concatenated text from all content blocks.

        Raises:
            SpectraRetryError: On connection or rate-limit errors.
        """
        return await self._call_streaming(system_prompt, user_prompt, model, max_tokens)

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        """Send a streaming request with adaptive extended thinking.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User-level content.
            model: Anthropic model identifier.
            max_tokens: Maximum response tokens.

        Returns:
            Text content only (thinking blocks are excluded).

        Raises:
            SpectraRetryError: On connection or rate-limit errors.
        """
        return await self._call_with_thinking(system_prompt, user_prompt, model, max_tokens)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()

    async def _call_streaming(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        try:
            collected_text = []
            input_tokens = 0
            output_tokens = 0
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=0.0,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                async for event in stream:
                    if hasattr(event, "type"):
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                collected_text.append(event.delta.text)
                        elif event.type == "message_delta":
                            if hasattr(event.usage, "output_tokens"):
                                output_tokens = event.usage.output_tokens
                        elif event.type == "message_start" and hasattr(event.message, "usage"):
                            input_tokens = event.message.usage.input_tokens
            self._last_usage = (input_tokens, output_tokens)
            return "".join(collected_text)
        except anthropic.APIConnectionError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc
        except anthropic.RateLimitError as exc:
            raise SpectraRetryError(ERRORS["SPEC-003"]) from exc

    async def _call_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        """Streaming call with adaptive thinking."""
        response = await self._stream_thinking(
            system_prompt,
            user_prompt,
            model,
            max_tokens,
        )
        self._last_usage = (
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return _extract_text_blocks(response)

    async def _stream_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> anthropic.types.Message:
        """Send a thinking-enabled streaming request."""
        try:
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                thinking={"type": "adaptive"},
            ) as stream:
                return await stream.get_final_message()
        except anthropic.APIConnectionError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc
        except anthropic.RateLimitError as exc:
            raise SpectraRetryError(ERRORS["SPEC-003"]) from exc
        except anthropic.BadRequestError:
            _log.exception("BadRequestError in thinking call")
            raise


def _extract_text_blocks(response: anthropic.types.Message) -> str:
    """Extract text content from response, skipping thinking blocks.

    Args:
        response: Anthropic Message with mixed content blocks.

    Returns:
        Concatenated text from all ``type="text"`` blocks.
    """
    text_parts = []
    for block in response.content:
        _log.debug("Response block: type=%s", block.type)
        if block.type == "text":
            text_parts.append(block.text)
    result = "".join(text_parts)
    if not result.strip():
        _log.warning("Thinking call returned empty text")
    return result
