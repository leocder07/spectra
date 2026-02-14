"""Retry decorator — exponential backoff for transient LLM failures."""

from __future__ import annotations

import asyncio

from spectra.entities.errors import SpectraRetryError
from spectra.use_cases.interfaces import LLMGateway


class RetryDecorator:
    """Wraps an LLMGateway with exponential backoff: 1s, 2s, 4s. Max 3 retries."""

    def __init__(
        self,
        inner: LLMGateway,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
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
    ) -> str:
        return await self._retry(
            self._inner.analyze,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
        )

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        return await self._retry(
            self._inner.analyze_with_thinking,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
        )

    async def _retry(
        self,
        fn: object,
        **kwargs: str | int,
    ) -> str:
        last_error: Exception = RuntimeError("No attempts made")
        for attempt in range(self._max_retries + 1):
            try:
                return await fn(**kwargs)  # type: ignore[misc]
            except SpectraRetryError as exc:
                last_error = exc
                if not exc.error.retryable:
                    raise
                if attempt < self._max_retries:
                    delay = self._backoff_base * (2**attempt)
                    await asyncio.sleep(delay)
        raise last_error
