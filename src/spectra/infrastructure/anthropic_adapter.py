"""Anthropic API adapter — implements LLMGateway Protocol."""

from __future__ import annotations

import anthropic

from spectra.entities.errors import ERRORS
from spectra.infrastructure.retry_decorator import SpectraRetryError


class AnthropicAdapter:
    """Async Anthropic client implementing the LLMGateway protocol."""

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
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
        return await self._call_standard(
            system_prompt, user_prompt, model, max_tokens
        )

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        return await self._call_with_thinking(
            system_prompt, user_prompt, model, max_tokens
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()

    async def _call_standard(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIConnectionError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc
        except anthropic.RateLimitError as exc:
            raise SpectraRetryError(ERRORS["SPEC-003"]) from exc
        self._last_usage = (
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return response.content[0].text

    async def _call_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                thinking={
                    "type": "enabled",
                    "budget_tokens": max_tokens // 2,
                },
            )
        except anthropic.APIConnectionError as exc:
            raise SpectraRetryError(ERRORS["SPEC-002"]) from exc
        except anthropic.RateLimitError as exc:
            raise SpectraRetryError(ERRORS["SPEC-003"]) from exc
        self._last_usage = (
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""
