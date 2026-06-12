"""Base agent ABC — Template Method pattern for agent lifecycle.

All 8 agents inherit from ``BaseAgent`` and implement the lifecycle:
``validate_input`` → ``build_prompt`` → ``execute_llm`` →
``parse_output`` → ``validate_output`` → ``format_result``.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, cast

from spectra.entities.enums import AgentRole
from spectra.entities.errors import ERRORS, AgentError, strip_code_fence
from spectra.entities.models import AgentOutput, CacheUsage, Finding
from spectra.use_cases.interfaces import LLMGateway

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["AgentError", "BaseAgent"]

_log = logging.getLogger("spectra.parse")


class BaseAgent(ABC):
    """Template Method: validate → build_prompt → execute → parse → validate → format.

    Subclasses must implement ``validate_input``, ``build_prompt``,
    and ``validate_output``. The ``run`` method orchestrates the full
    lifecycle and returns a validated ``AgentOutput``.
    """

    def __init__(
        self,
        role: AgentRole,
        gateway: LLMGateway,
        model: str,
        system_prompt: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> None:
        """Initialize the base agent.

        Args:
            role: Agent role identifier.
            gateway: LLM gateway (possibly wrapped with decorators).
            model: Anthropic model ID.
            system_prompt: System prompt defining agent behavior.
            max_tokens: Maximum response tokens.
            effort: Optional ``output_config.effort`` (Opus 4.7: ``xhigh``
                recommended for coding/agentic; ``high`` is the default).
        """
        self._role = role
        self._gateway = gateway
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._effort = effort
        # ADR-024: every agent's system prompt is stable per release. The
        # entire system prompt is therefore the cacheable prefix; the
        # dynamic per-call payload sits in the user message and is never
        # cached. Subclasses that need a different breakpoint (e.g. a
        # version-stamped suffix) override this property.
        self._cache_breakpoint_index: int | None = len(system_prompt)

    @property
    def role(self) -> AgentRole:
        return self._role

    async def run(self, user_prompt: str) -> AgentOutput:
        """Execute the full agent lifecycle and return validated output.

        Args:
            user_prompt: Content to analyze (file tree or source code).

        Returns:
            Validated ``AgentOutput`` with findings and metadata.

        Raises:
            AgentError: If output fails Pydantic validation (SPEC-005).
        """
        self.validate_input(user_prompt)
        prompt = self.build_prompt(user_prompt)
        start = time.monotonic()
        raw_output = await self.execute_llm(prompt)
        duration = time.monotonic() - start
        tokens = self._get_tokens_used()
        cache_usage = self._get_cache_usage()
        parsed = self.parse_output(raw_output)
        findings = self.validate_output(parsed)
        dim_score = self._extract_dimension_score(parsed)
        return self.format_result(
            findings,
            raw_output,
            duration,
            tokens,
            dim_score,
            cache_usage,
        )

    @abstractmethod
    def validate_input(self, user_prompt: str) -> None: ...

    @abstractmethod
    def build_prompt(self, user_prompt: str) -> str: ...

    async def execute_llm(self, prompt: str) -> str:
        return await self._gateway.analyze(
            system_prompt=self._system_prompt,
            user_prompt=prompt,
            model=self._model,
            max_tokens=self._max_tokens,
            effort=self._effort,
            cache_breakpoint_index=self._cache_breakpoint_index,
        )

    def parse_output(self, raw: str) -> dict[str, list[dict[str, str | int | float]]]:
        """Parse JSON from raw LLM output, with fallback extraction."""
        cleaned = strip_code_fence(raw)
        try:
            return cast("dict[str, list[dict[str, str | int | float]]]", json.loads(cleaned))
        except json.JSONDecodeError as e:
            _log.debug("JSON parse failed for %s: %s", self._role, e)
        result = _extract_json_object(cleaned)
        if result is not None:
            return result
        _log.warning(
            "All JSON extraction failed for %s (raw=%d, cleaned=%d)",
            self._role,
            len(raw),
            len(cleaned),
        )
        raise AgentError(ERRORS["SPEC-005"])

    @abstractmethod
    def validate_output(self, parsed: dict[str, list[dict[str, str | int | float]]]) -> tuple[Finding, ...]: ...

    def _get_tokens_used(self) -> int:
        """Get actual token usage from the gateway's last API call."""
        usage: tuple[int, int] = getattr(self._gateway, "last_usage", (0, 0))
        inp, out = usage
        return inp + out if (inp + out) > 0 else 0

    def _get_cache_usage(self) -> CacheUsage:
        """Get prompt-cache token counters from the gateway's last call.

        Defaults to a zero-valued ``CacheUsage`` so test doubles and
        legacy adapters that do not surface the property never break
        the pipeline. Only real ``CacheUsage`` instances are propagated;
        anything else (e.g. ``MagicMock`` from un-spec'd test doubles)
        degrades silently to the empty default.
        """
        usage = getattr(self._gateway, "last_cache_usage", None)
        return usage if isinstance(usage, CacheUsage) else CacheUsage()

    def _extract_dimension_score(self, parsed: Mapping[str, object]) -> float | None:
        """Extract the LLM's holistic dimension score from parsed output."""
        score = parsed.get("dimension_score")
        if isinstance(score, (int, float)) and 0 <= score <= 100:
            return float(score)
        return None

    def format_result(
        self,
        findings: tuple[Finding, ...],
        raw_response: str,
        duration: float,
        tokens_used: int = 0,
        dimension_score: float | None = None,
        cache_usage: CacheUsage | None = None,
    ) -> AgentOutput:
        """Build an AgentOutput from a completed LLM call."""
        final_tokens = tokens_used if tokens_used > 0 else max(len(raw_response) // 4, 1)
        return AgentOutput(
            agent_role=self._role,
            findings=findings,
            tokens_used=final_tokens,
            duration_seconds=round(duration, 2),
            raw_response=raw_response,
            dimension_score=dimension_score,
            cache_usage=cache_usage if cache_usage is not None else CacheUsage(),
        )


def _extract_json_object(
    text: str,
) -> dict[str, list[dict[str, str | int | float]]] | None:
    """Fallback: find the outermost JSON object in text."""
    start = text.find("{")
    if start == -1:
        return None
    end = text.rfind("}")
    if end <= start:
        return None
    try:
        return cast("dict[str, list[dict[str, str | int | float]]]", json.loads(text[start : end + 1]))
    except json.JSONDecodeError:
        return None
