"""CritiqueAgent — validates ALL findings using extended thinking."""

from __future__ import annotations

import json

from spectra.entities.models import AgentOutput, Finding
from spectra.infrastructure.agents.base_agent import BaseAgent
from spectra.use_cases.interfaces import LLMGateway

_SYSTEM_PROMPT = """You are the critique agent. Use extended thinking to carefully validate
every finding from the specialist agents.

For EACH finding, determine:
1. Is this a true positive or false positive?
2. Is the severity correctly assigned?
3. Is the recommendation actionable and correct?
4. Are there cross-cutting concerns across dimensions?

OUTPUT FORMAT (JSON):
{
  "validated_findings": [...],
  "rejected_findings": [...],
  "severity_adjustments": [...],
  "cross_cutting_insights": [...]
}

Use your extended thinking to reason through EACH finding before deciding.
Target: <5% false positive rate in validated findings."""


class CritiqueAgent(BaseAgent):
    """Validates all findings from specialists. Uses extended thinking."""

    def __init__(self, gateway: LLMGateway) -> None:
        super().__init__(
            role="critique",
            gateway=gateway,
            model="claude-opus-4-6",
            system_prompt=_SYSTEM_PROMPT,
            max_tokens=200_000,
        )

    def validate_input(self, user_prompt: str) -> None:
        if not user_prompt.strip():
            msg = "CritiqueAgent requires findings input"
            raise ValueError(msg)

    def build_prompt(self, user_prompt: str) -> str:
        return f"Specialist findings to validate:\n\n{user_prompt}"

    async def execute_llm(self, prompt: str) -> str:
        return await self._gateway.analyze_with_thinking(
            system_prompt=self._system_prompt,
            user_prompt=prompt,
            model=self._model,
            max_tokens=self._max_tokens,
        )

    def validate_output(
        self, parsed: dict[str, list[dict[str, str | int | float]]]
    ) -> tuple[Finding, ...]:
        required = {"validated_findings", "rejected_findings"}
        missing = required - set(parsed.keys())
        if missing:
            msg = f"CritiqueAgent output missing keys: {missing}"
            raise ValueError(msg)
        return ()

    def get_critique_result(
        self, raw_output: str
    ) -> dict[str, list[dict[str, str | int | float]]]:
        return self.parse_output(raw_output)
