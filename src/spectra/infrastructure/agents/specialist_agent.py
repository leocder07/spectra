"""Parameterized specialist agent — replaces 6 identical agent classes."""

from __future__ import annotations

from spectra.entities.enums import AgentRole, Dimension
from spectra.entities.models import FileLocation, Finding
from spectra.infrastructure.agents.base_agent import BaseAgent
from spectra.use_cases.interfaces import LLMGateway


class SpecialistAgent(BaseAgent):
    """Generic specialist agent parameterized by dimension and id_prefix."""

    def __init__(
        self,
        role: AgentRole,
        gateway: LLMGateway,
        dimension: Dimension,
        id_prefix: str,
        system_prompt: str,
    ) -> None:
        super().__init__(
            role=role,
            gateway=gateway,
            model="claude-opus-4-6",
            system_prompt=system_prompt,
            max_tokens=80_000,
        )
        self._dimension = dimension
        self._id_prefix = id_prefix

    def validate_input(self, user_prompt: str) -> None:
        if not user_prompt.strip():
            msg = f"{self._id_prefix.upper()} agent requires source code input"
            raise ValueError(msg)

    def build_prompt(self, user_prompt: str) -> str:
        return user_prompt

    def validate_output(
        self, parsed: dict[str, list[dict[str, str | int | float]]]
    ) -> tuple[Finding, ...]:
        raw_findings = parsed.get("findings", [])
        validated: list[Finding] = []

        for i, f in enumerate(raw_findings):
            confidence = float(f.get("confidence", 0.0))
            if confidence < 0.7:
                continue
            validated.append(
                Finding(
                    id=f"{self._id_prefix}-{i:03d}",
                    dimension=self._dimension,
                    severity=str(f.get("severity", "info")),
                    title=str(f.get("title", "")),
                    description=str(f.get("description", "")),
                    location=FileLocation(
                        file_path=str(f.get("file_path", "")),
                        line_start=int(f.get("line_start", 0)),
                        line_end=int(f.get("line_end", 0)) or None,
                    ),
                    recommendation=str(f.get("recommendation", "")),
                    agent_role=self._role,
                    confidence=confidence,
                )
            )
        return tuple(validated)
