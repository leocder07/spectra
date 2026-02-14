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
        return self.format_result(findings, raw_output, duration, tokens)

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
        try:
            return json.loads(strip_code_fence(raw))
        except json.JSONDecodeError as exc:
            raise AgentError(ERRORS["SPEC-005"]) from exc

    @abstractmethod
    def validate_output(
        self, parsed: dict[str, list[dict[str, str | int | float]]]
    ) -> tuple[Finding, ...]:
        ...

    def _get_tokens_used(self) -> int:
        """Get actual token usage from the gateway's last API call.

        Falls back to len // 4 approximation if the gateway doesn't
        expose usage metadata (e.g. in tests with mocks).
        """
        usage: tuple[int, int] = getattr(
            self._gateway, "last_usage", (0, 0)
        )
        inp, out = usage
        return inp + out if (inp + out) > 0 else 0

    def format_result(
        self,
        findings: tuple[Finding, ...],
        raw_response: str,
        duration: float,
        tokens_used: int = 0,
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
        )
