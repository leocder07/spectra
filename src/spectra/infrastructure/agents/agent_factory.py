"""Agent factory — creates configured agent instances by role.

Implements the Factory pattern to centralize agent construction. The
composition root (``infrastructure/main.py``) creates a single
``AgentFactory`` instance with the decorated LLM gateway, then uses
it to create all 8 agents without knowing their concrete classes.

Factory dispatch logic:
    - ``"meta_prompter"`` → ``MetaPrompter`` (Sonnet 4.5, file tree only)
    - ``"critique"`` → ``CritiqueAgent`` (Opus 4.6, extended thinking)
    - Any specialist role → ``SpecialistAgent`` parameterized with config
      from ``specialist_prompts.SPECIALIST_CONFIGS``

The ``create_specialists()`` convenience method returns all 6 specialist
agents in canonical order for parallel execution via ``asyncio.gather``.

Dependencies:
    - Imports from ``entities/`` (AgentRole enum) and ``use_cases/``
      (LLMGateway protocol) — respects the dependency rule.
    - Imports sibling agent classes from the same ``agents/`` package.
"""

from __future__ import annotations

from spectra.entities.enums import AgentRole
from spectra.infrastructure.agents.base_agent import BaseAgent
from spectra.infrastructure.agents.critique_agent import CritiqueAgent
from spectra.infrastructure.agents.meta_prompter import MetaPrompter
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent
from spectra.infrastructure.agents.specialist_prompts import SPECIALIST_CONFIGS
from spectra.use_cases.interfaces import LLMGateway


class AgentFactory:
    """Creates agent instances configured with the shared LLM gateway.

    Supports creating any of the 8 agents by role name.
    """

    def __init__(self, gateway: LLMGateway) -> None:
        """Initialize the factory.

        Args:
            gateway: Shared LLM gateway (with decorators applied).
        """
        self._gateway = gateway

    def create(self, role: AgentRole) -> BaseAgent:
        """Create a single agent by role.

        Args:
            role: Agent role identifier.

        Returns:
            Configured agent instance.

        Raises:
            ValueError: If the role is unknown.
        """
        # Factory dispatch: special agents first, then parameterized specialists
        if role == "meta_prompter":
            # MetaPrompter uses Sonnet 4.5, receives ONLY file tree (≤5K tokens)
            return MetaPrompter(gateway=self._gateway)
        if role == "critique":
            # CritiqueAgent uses Opus 4.6 with extended thinking
            return CritiqueAgent(gateway=self._gateway)

        # All 6 specialist roles use the same SpecialistAgent class,
        # parameterized by dimension-specific config from SPECIALIST_CONFIGS
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
        """Create all 6 specialist agents for parallel execution.

        Returns:
            List of specialist agents in canonical order.
        """
        specialist_roles: list[AgentRole] = [
            "architecture",
            "security",
            "quality",
            "documentation",
            "dependency",
            "performance",
        ]
        return [self.create(role) for role in specialist_roles]
