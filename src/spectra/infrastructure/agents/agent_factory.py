"""Agent factory — creates configured agent instances by role.

Implements the Factory pattern to centralize agent construction. The
composition root (``infrastructure/main.py``) creates a single
``AgentFactory`` instance with the decorated LLM gateway, then uses
it to create all 8 agents without knowing their concrete classes.

The factory is called once per analysis run (not per-agent). Agent objects
are lightweight — they only store config strings and a reference to the
shared ``LLMGateway``. No heavy initialization (no model loading, no
network calls, no file I/O) occurs during agent creation.

Factory dispatch logic:
    - ``"meta_prompter"`` → ``MetaPrompter`` (Opus 4.7 medium effort, file tree only)
    - ``"critique"`` → ``CritiqueAgent`` (Opus 4.7, adaptive thinking + task budget)
    - Any specialist role → ``SpecialistAgent`` parameterized with config
      from ``specialist_prompts.SPECIALIST_CONFIGS`` (Opus 4.7, effort=xhigh)

The ``create_specialists()`` convenience method returns all 6 specialist
agents in canonical order for parallel execution via ``asyncio.gather``.

Dependencies:
    - Imports from ``entities/`` (AgentRole enum) and ``use_cases/``
      (LLMGateway protocol) — respects the dependency rule.
    - Imports sibling agent classes from the same ``agents/`` package.
"""

from __future__ import annotations

from spectra.entities.enums import AgentRole
from spectra.entities.models import AgentRunConfig
from spectra.infrastructure.agents.base_agent import BaseAgent
from spectra.infrastructure.agents.critique_agent import CritiqueAgent
from spectra.infrastructure.agents.meta_prompter import MetaPrompter
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent
from spectra.infrastructure.agents.specialist_prompts import SPECIALIST_CONFIGS
from spectra.use_cases.interfaces import LLMGateway


class AgentFactory:
    """Creates agent instances configured with the shared LLM gateway.

    Supports creating any of the 8 agents by role name. Instantiation is
    lightweight — agents store only config and a gateway reference. No
    heavy objects (model weights, connections) are created per-agent.

    When ``configs`` is provided, each agent receives the per-role model
    and effort from the resolved ``AgentRunConfig`` map (CLI overrides
    take effect here). When omitted, the legacy hardcoded defaults are
    used — kept for backward compatibility with existing tests.
    """

    def __init__(
        self,
        gateway: LLMGateway,
        configs: dict[AgentRole, AgentRunConfig] | None = None,
    ) -> None:
        """Initialize the factory.

        Args:
            gateway: Shared LLM gateway (with decorators applied).
            configs: Per-role model + effort overrides. ``None`` keeps
                the legacy hardcoded behavior of each agent class.
        """
        self._gateway = gateway
        self._configs = configs

    def create(self, role: AgentRole) -> BaseAgent:
        """Create a single agent by role.

        Args:
            role: Agent role identifier.

        Returns:
            Configured agent instance.

        Raises:
            ValueError: If the role is unknown.
        """
        cfg = self._configs.get(role) if self._configs else None
        if role == "meta_prompter":
            return self._make_meta_prompter(cfg)
        if role == "critique":
            return self._make_critique(cfg)
        return self._make_specialist(role, cfg)

    def _make_meta_prompter(self, cfg: AgentRunConfig | None) -> MetaPrompter:
        """Build the MetaPrompter, applying config overrides when present."""
        if cfg is None:
            return MetaPrompter(gateway=self._gateway)
        return MetaPrompter(gateway=self._gateway, model=cfg.model, effort=cfg.effort)

    def _make_critique(self, cfg: AgentRunConfig | None) -> CritiqueAgent:
        """Build the CritiqueAgent, applying config overrides when present."""
        if cfg is None:
            return CritiqueAgent(gateway=self._gateway)
        return CritiqueAgent(gateway=self._gateway, model=cfg.model, effort=cfg.effort)

    def _make_specialist(self, role: AgentRole, cfg: AgentRunConfig | None) -> SpecialistAgent:
        """Build a parameterized specialist, applying config overrides when present."""
        spec = SPECIALIST_CONFIGS.get(role)
        if spec is None:
            msg = f"Unknown agent role: {role}"
            raise ValueError(msg)
        dimension, id_prefix, system_prompt, default_model = spec
        model = cfg.model if cfg is not None else default_model
        effort = cfg.effort if cfg is not None else "xhigh"
        return SpecialistAgent(
            role=role,
            gateway=self._gateway,
            dimension=dimension,
            id_prefix=id_prefix,
            system_prompt=system_prompt,
            model=model,
            effort=effort,
        )

    def create_specialists(self) -> list[BaseAgent]:
        """Create all 6 specialist agents for parallel execution.

        Called once per ``analyze_repository`` invocation. Each agent is
        a lightweight object (~200 bytes) holding config + gateway ref.

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
