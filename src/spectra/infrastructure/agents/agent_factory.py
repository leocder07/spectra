"""Agent factory — creates configured agent instances by role."""

from __future__ import annotations

from spectra.entities.enums import AgentRole
from spectra.infrastructure.agents.base_agent import BaseAgent
from spectra.infrastructure.agents.critique_agent import CritiqueAgent
from spectra.infrastructure.agents.meta_prompter import MetaPrompter
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent
from spectra.infrastructure.agents.specialist_prompts import SPECIALIST_CONFIGS
from spectra.use_cases.interfaces import LLMGateway


class AgentFactory:
    """Creates agent instances configured with the shared LLM gateway."""

    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    def create(self, role: AgentRole) -> BaseAgent:
        if role == "meta_prompter":
            return MetaPrompter(gateway=self._gateway)
        if role == "critique":
            return CritiqueAgent(gateway=self._gateway)

        config = SPECIALIST_CONFIGS.get(role)
        if config is None:
            msg = f"Unknown agent role: {role}"
            raise ValueError(msg)

        dimension, id_prefix, system_prompt, model = config
        return SpecialistAgent(
            role=role,
            gateway=self._gateway,
            dimension=dimension,
            id_prefix=id_prefix,
            system_prompt=system_prompt,
            model=model,
        )

    def create_specialists(self) -> list[BaseAgent]:
        specialist_roles: list[AgentRole] = [
            "architecture",
            "security",
            "quality",
            "documentation",
            "dependency",
            "performance",
        ]
        return [self.create(role) for role in specialist_roles]
