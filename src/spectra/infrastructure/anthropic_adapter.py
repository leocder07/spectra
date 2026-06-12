"""Anthropic API adapter — implements LLMGateway Protocol with streaming.

This adapter is always wrapped by ``RetryDecorator`` (exponential backoff
1s/2s/4s with jitter, max 3 retries) and ``LoggingDecorator`` in the
composition root (``infrastructure/main.py``). The decorator chain is:
``LoggingDecorator → RetryDecorator → AnthropicAdapter``. Direct use
without the decorator chain is not supported.

Version constraints: anthropic>=0.40 (streaming support), httpx (bundled).
Dependabot monitors weekly. See pyproject.toml for pinning strategy.

Provides ``AnthropicAdapter`` which wraps the ``anthropic.AsyncAnthropic``
client with streaming support and maps API errors to Spectra error codes
(SPEC-002 for connection failures, SPEC-003 for rate limits).

Performance:
    - Connection pooling: 10 keep-alive connections via httpx, reused across
      all 6 specialist calls within a single analysis run. This avoids TLS
      handshake overhead (~100ms) per API call.
    - Streaming: Responses are streamed incrementally, reducing time-to-first-
      token and memory footprint for large outputs.
    - The ``RetryDecorator`` wrapper handles transient failures (SPEC-002,
      SPEC-003) with exponential backoff + jitter to avoid thundering herd.

Security:
    - API key is accepted as a constructor argument and passed directly to
      the Anthropic SDK — it is never logged, serialized, or stored beyond
      the client instance.
    - The key is validated at construction time to reject empty or
      placeholder values before any network call is attempted.
    - ``close()`` shuts down the underlying httpx connection pool.
    - ``__del__`` provides a safety net to warn about unclosed clients.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import anthropic
import httpx

from spectra.entities.errors import ERRORS, SpectraRetryError
from spectra.entities.models import CacheUsage

if TYPE_CHECKING:
    from anthropic.types.message_create_params import MessageCreateParamsBase

_log = logging.getLogger("spectra.adapter")

_MAX_CONNECTIONS = 10
_EPHEMERAL_MARKER: dict[str, str] = {"type": "ephemeral"}


def _build_system_blocks(
    system_prompt: str,
    cache_breakpoint_index: int | None,
) -> str | list[dict[str, object]]:
    """Translate ``cache_breakpoint_index`` into the Anthropic system shape.

    Returns the plain ``system_prompt`` string when no caching is requested
    or when the requested split is degenerate (index ``<= 0`` or ``>= len``).
    Otherwise emits the two-block list with ``cache_control: ephemeral`` on
    the cacheable prefix only — the dynamic suffix is sent uncached so a
    new run never invalidates the cache by mutating the prefix.
    """
    if cache_breakpoint_index is None or cache_breakpoint_index <= 0:
        return system_prompt
    if cache_breakpoint_index >= len(system_prompt):
        return [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": _EPHEMERAL_MARKER,
            },
        ]
    prefix = system_prompt[:cache_breakpoint_index]
    suffix = system_prompt[cache_breakpoint_index:]
    return [
        {"type": "text", "text": prefix, "cache_control": _EPHEMERAL_MARKER},
        {"type": "text", "text": suffix},
    ]


def _read_cache_usage(usage: object) -> CacheUsage:
    """Extract Anthropic cache token counters from a usage block."""
    creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    return CacheUsage(creation_tokens=creation, read_tokens=read)


class AnthropicAdapter:
    """Async Anthropic client implementing the LLMGateway protocol.

    Uses streaming for standard calls and adaptive thinking for
    CritiqueAgent calls. Connection pooling is configured via httpx
    with a fixed limit of 10 keep-alive connections.

    Note: This class is NOT used directly. The composition root in
    ``main.py`` wraps it with ``LoggingDecorator → RetryDecorator``,
    providing automatic retry with exponential backoff (1s/2s/4s + jitter)
    for SPEC-002 (connection) and SPEC-003 (rate-limit) errors.
    """

    def __init__(self, api_key: str) -> None:
        """Initialize the adapter with an Anthropic API key.

        Args:
            api_key: Anthropic API key (``sk-ant-*``).

        Raises:
            ValueError: If the key is empty, whitespace-only, or a
                placeholder value from ``.env.example``.
        """
        placeholders = {"sk-ant-your-key-here", "your-key-here", ""}
        stripped = api_key.strip()
        if not stripped or stripped in placeholders:
            msg = "ANTHROPIC_API_KEY is missing or contains a placeholder value"
            raise ValueError(msg)
        self._closed = False
        # Connection pool: 10 keep-alive connections reused across all
        # agent calls. Avoids TLS handshake overhead (~100ms per call).
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
        self._last_cache_usage: CacheUsage = CacheUsage()

    @property
    def last_usage(self) -> tuple[int, int]:
        """(input_tokens, output_tokens) from the most recent API call."""
        return self._last_usage

    @property
    def last_cache_usage(self) -> CacheUsage:
        """Anthropic prompt-cache token counters for the most recent call."""
        return self._last_cache_usage

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        """Send a streaming inference request.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User-level content.
            model: Anthropic model identifier.
            max_tokens: Maximum response tokens.
            effort: Optional ``output_config.effort``. On Opus 4.7 use ``xhigh``
                for coding/agentic; ``high`` is the default sweet spot.
            cache_breakpoint_index: Optional byte index into ``system_prompt``
                marking the end of the cacheable prefix (ADR-024). When set
                the adapter sends the system block list with a ``cache_control``
                marker on the prefix; otherwise the system prompt is sent as
                a plain string (no caching).

        Returns:
            Concatenated text from all content blocks.

        Raises:
            SpectraRetryError: On connection or rate-limit errors.
        """
        return await self._call_streaming(
            system_prompt,
            user_prompt,
            model,
            max_tokens,
            effort,
            cache_breakpoint_index,
        )

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        """Send a streaming request with adaptive extended thinking.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User-level content.
            model: Anthropic model identifier.
            max_tokens: Maximum response tokens (per-response cap).
            effort: Optional ``output_config.effort``.
            task_budget_tokens: Optional cumulative loop budget (min 20_000).
            cache_breakpoint_index: See :meth:`analyze` (ADR-024).

        Returns:
            Text content only (thinking blocks are excluded).

        Raises:
            SpectraRetryError: On connection or rate-limit errors.
        """
        return await self._call_with_thinking(
            system_prompt,
            user_prompt,
            model,
            max_tokens,
            effort,
            task_budget_tokens,
            cache_breakpoint_index,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client and release connection pool."""
        self._closed = True
        await self._client.close()

    def __del__(self) -> None:
        """Warn if the client was not explicitly closed."""
        if not getattr(self, "_closed", True):
            _log.warning("AnthropicAdapter was not closed — call close() or use async with")

    async def _call_streaming(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        try:
            collected_text: list[str] = []
            input_tokens = 0
            output_tokens = 0
            cache_usage = CacheUsage()
            stream_kwargs: dict[str, object] = {
                "model": model,
                "max_tokens": max_tokens,
                "system": _build_system_blocks(system_prompt, cache_breakpoint_index),
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if effort is not None:
                stream_kwargs["output_config"] = {"effort": effort}
            typed_kwargs = cast("MessageCreateParamsBase", stream_kwargs)
            async with self._client.messages.stream(**typed_kwargs) as stream:
                async for event in stream:
                    if not hasattr(event, "type"):
                        continue
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        collected_text.append(event.delta.text)
                    elif event.type == "message_delta" and hasattr(event.usage, "output_tokens"):
                        output_tokens = event.usage.output_tokens
                    elif event.type == "message_start" and hasattr(event.message, "usage"):
                        input_tokens = event.message.usage.input_tokens
                        cache_usage = _read_cache_usage(event.message.usage)
            self._last_usage = (input_tokens, output_tokens)
            self._last_cache_usage = cache_usage
            return "".join(collected_text)
        except anthropic.APIConnectionError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc
        except anthropic.RateLimitError as exc:
            raise SpectraRetryError(ERRORS["SPEC-003"]) from exc
        except anthropic.AuthenticationError as exc:
            msg = "Invalid API key — check ANTHROPIC_API_KEY"
            raise ValueError(msg) from exc
        except anthropic.InternalServerError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc

    async def _call_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        """Streaming call with adaptive thinking."""
        response = await self._stream_thinking(
            system_prompt,
            user_prompt,
            model,
            max_tokens,
            effort,
            task_budget_tokens,
            cache_breakpoint_index,
        )
        self._last_usage = (
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        self._last_cache_usage = _read_cache_usage(response.usage)
        return _extract_text_blocks(response)

    async def _stream_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> anthropic.types.Message:
        """Send a thinking-enabled streaming request."""
        output_config: dict[str, object] = {}
        if effort is not None:
            output_config["effort"] = effort
        if task_budget_tokens is not None:
            output_config["task_budget"] = {
                "type": "tokens",
                "total": task_budget_tokens,
            }

        stream_kwargs: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": _build_system_blocks(system_prompt, cache_breakpoint_index),
            "messages": [{"role": "user", "content": user_prompt}],
            "thinking": {"type": "adaptive", "display": "summarized"},
        }
        if output_config:
            stream_kwargs["output_config"] = output_config
        # task_budget is gated behind a beta header
        if task_budget_tokens is not None:
            stream_kwargs["extra_headers"] = {
                "anthropic-beta": "task-budgets-2026-03-13",
            }

        try:
            typed_kwargs = cast("MessageCreateParamsBase", stream_kwargs)
            async with self._client.messages.stream(**typed_kwargs) as stream:
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
