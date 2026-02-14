"""Base agent ABC — Template Method pattern for agent lifecycle."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod

from spectra.entities.enums import AgentRole
from spectra.entities.errors import ERRORS, AgentError, strip_code_fence
from spectra.entities.models import AgentOutput, Finding
from spectra.use_cases.interfaces import LLMGateway


class BaseAgent(ABC):
    """Template Method: validate → build_prompt → execute → parse → validate → format."""

    def __init__(
        self,
        role: AgentRole,
        gateway: LLMGateway,
        model: str,
        system_prompt: str,
        max_tokens: int,
    ) -> None:
        self._role = role
        self._gateway = gateway
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens

    @property
    def role(self) -> AgentRole:
        return self._role

    async def run(self, user_prompt: str) -> AgentOutput:
        self.validate_input(user_prompt)
        prompt = self.build_prompt(user_prompt)
        start = time.monotonic()
        raw_output = await self.execute_llm(prompt)
        duration = time.monotonic() - start
        tokens = self._get_tokens_used()
        parsed = self.parse_output(raw_output)
        findings = self.validate_output(parsed)
        dim_score = self._extract_dimension_score(parsed)
        return self.format_result(findings, raw_output, duration, tokens, dim_score)

    @abstractmethod
    def validate_input(self, user_prompt: str) -> None:
        ...

    @abstractmethod
    def build_prompt(self, user_prompt: str) -> str:
        ...

    async def execute_llm(self, prompt: str) -> str:
        return await self._gateway.analyze(
            system_prompt=self._system_prompt,
            user_prompt=prompt,
            model=self._model,
            max_tokens=self._max_tokens,
        )

    def parse_output(self, raw: str) -> dict[str, list[dict[str, str | int | float]]]:
        import logging
        _log = logging.getLogger("spectra.parse")
        cleaned = strip_code_fence(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            _log.debug(
                "JSON parse failed for %s: %s | First 300 chars: %s",
                self._role, e, cleaned[:300]
            )
        # Fallback: try to find JSON object in the text
        for start in range(len(cleaned)):
            if cleaned[start] == "{":
                for end in range(len(cleaned) - 1, start, -1):
                    if cleaned[end] == "}":
                        try:
                            return json.loads(cleaned[start : end + 1])
                        except json.JSONDecodeError:
                            break
                break
        _log.warning(
            "All JSON extraction failed for %s. Raw length: %d, Cleaned length: %d, First 200: %s",
            self._role, len(raw), len(cleaned), cleaned[:200]
        )
        raise AgentError(ERRORS["SPEC-005"])

    @abstractmethod
    def validate_output(
        self, parsed: dict[str, list[dict[str, str | int | float]]]
    ) -> tuple[Finding, ...]:
        ...

    def _get_tokens_used(self) -> int:
        """Get actual token usage from the gateway's last API call."""
        usage: tuple[int, int] = getattr(
            self._gateway, "last_usage", (0, 0)
        )
        inp, out = usage
        return inp + out if (inp + out) > 0 else 0

    def _extract_dimension_score(self, parsed: dict) -> float | None:
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
    ) -> AgentOutput:
        # Use actual API tokens when available, else rough approximation
        final_tokens = tokens_used if tokens_used > 0 else max(
            len(raw_response) // 4, 1
        )
        return AgentOutput(
            agent_role=self._role,
            findings=findings,
            tokens_used=final_tokens,
            duration_seconds=round(duration, 2),
            raw_response=raw_response,
            dimension_score=dimension_score,
        )
