"""Retry decorator — exponential backoff for transient LLM failures.

Wraps any ``LLMGateway`` and intercepts ``SpectraRetryError`` to apply
exponential backoff with jitter (1s, 2s, 4s). Non-retryable errors
propagate immediately.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Coroutine

from spectra.entities.errors import SpectraRetryError
from spectra.use_cases.interfaces import LLMGateway

# Async callable that accepts keyword args and returns str
_AsyncAnalyzeFn = Callable[..., Coroutine[None, None, str]]


class RetryDecorator:
    """Wraps an LLMGateway with exponential backoff: 1s, 2s, 4s.

    Only retries when ``SpectraRetryError.error.retryable`` is True.
    Non-retryable errors raise immediately.
    """

    def __init__(
        self,
        inner: LLMGateway,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        """Initialize the retry wrapper.

        Args:
            inner: Underlying LLM gateway to wrap.
            max_retries: Maximum number of retry attempts.
            backoff_base: Base delay in seconds (doubles each attempt).
        """
        self._inner = inner
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    @property
    def last_usage(self) -> tuple[int, int]:
        """Propagate token usage from the inner gateway."""
        return getattr(self._inner, "last_usage", (0, 0))

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        """Analyze with automatic retry on transient failures."""
        return await self._retry(
            self._inner.analyze,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
            effort=effort,
        )

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,
    ) -> str:
        """Analyze with thinking, with automatic retry on transient failures."""
        return await self._retry(
            self._inner.analyze_with_thinking,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
            effort=effort,
            task_budget_tokens=task_budget_tokens,
        )

    async def _retry(
        self,
        fn: _AsyncAnalyzeFn,
        **kwargs: object,
    ) -> str:
        last_error: Exception = RuntimeError("No attempts made")
        for attempt in range(self._max_retries + 1):
            try:
                return await fn(**kwargs)
            except SpectraRetryError as exc:
                last_error = exc
                if not exc.error.retryable:
                    raise
                if attempt < self._max_retries:
                    delay = self._backoff_base * (2**attempt)
                    jitter = random.uniform(0, delay * 0.5)  # noqa: S311
                    await asyncio.sleep(delay + jitter)
        raise last_error
