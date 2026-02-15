"""Logging decorator — records model, tokens, duration, cost per LLM call.

Security: prompt/response content truncated to _MAX_LOG_CHARS and
API key patterns (sk-ant-*) are redacted before logging.
"""

from __future__ import annotations

import re
import time

from spectra.use_cases.interfaces import LLMGateway, ProgressObserver

_MAX_LOG_CHARS = 500
_SECRET_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]+"  # Anthropic API keys
    r"|sk-[A-Za-z0-9]{20,}"  # OpenAI-style keys
    r"|ghp_[A-Za-z0-9]{36}"  # GitHub personal access tokens
    r"|github_pat_[A-Za-z0-9_]+"  # GitHub fine-grained tokens
)


def _sanitize(text: str) -> str:
    """Truncate and redact secrets from text before logging."""
    redacted = _SECRET_RE.sub("[REDACTED]", text)
    if len(redacted) > _MAX_LOG_CHARS:
        return redacted[:_MAX_LOG_CHARS] + "...[truncated]"
    return redacted


class LoggingDecorator:
    """Wraps an LLMGateway and logs call metadata to a ProgressObserver."""

    def __init__(self, inner: LLMGateway, observer: ProgressObserver) -> None:
        self._inner = inner
        self._observer = observer

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
        start = time.monotonic()
        result = await self._inner.analyze(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
        )
        self._log_call(model, start)
        return result

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        start = time.monotonic()
        result = await self._inner.analyze_with_thinking(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
        )
        self._log_call(model, start)
        return result

    def _log_call(self, model: str, start: float) -> None:
        duration = time.monotonic() - start
        inp, out = self.last_usage
        total_tokens = inp + out
        self._observer.on_stage_complete(
            stage="llm_call",
            message=_sanitize(f"{model} | {duration:.1f}s | {total_tokens} tokens"),
        )
