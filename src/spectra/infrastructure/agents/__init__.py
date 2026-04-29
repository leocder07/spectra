"""Agent infrastructure — 8 AI agents forming the analysis pipeline.

This package implements Spectra's multi-agent architecture. The pipeline
deploys 8 agents across 3 stages:

Pipeline flow::

    Stage 2: MetaPrompter (Opus 4.7 medium effort, file tree ONLY, ≤5K tokens)
        ↓
    Stage 3: 6 SpecialistAgents (Opus 4.7 effort=xhigh, run in PARALLEL via asyncio.gather)
        Architecture · Security · Quality · Documentation · Dependency · Performance
        ↓
    Stage 5: CritiqueAgent (Opus 4.7, ADAPTIVE THINKING + task budget, validates ALL findings)

Key design patterns:

- **Template Method** (``BaseAgent``): All agents follow the same lifecycle:
  ``validate_input`` → ``build_prompt`` → ``execute_llm`` → ``parse_output``
  → ``validate_output`` → ``format_result``. Subclasses override specific steps.
- **Factory** (``AgentFactory``): Creates any of the 8 agents by role name,
  injecting the shared LLM gateway (with decorator chain applied).
- **Parameterized Specialist** (``SpecialistAgent``): A single class handles
  all 6 dimensions — each instance is configured with a dimension-specific
  system prompt and ID prefix from ``specialist_prompts.SPECIALIST_CONFIGS``.

Hard rules:
  1. MetaPrompter NEVER gets full code — file tree only, ≤5K tokens.
  2. Adaptive thinking: CritiqueAgent ONLY.
  3. Every agent output validated against Pydantic before merge.
  4. 120s timeout per agent via ``asyncio.wait_for``.
"""

from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.infrastructure.agents.base_agent import AgentError, BaseAgent
from spectra.infrastructure.agents.critique_agent import CritiqueAgent
from spectra.infrastructure.agents.meta_prompter import MetaPrompter
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent
from spectra.infrastructure.agents.specialist_prompts import SPECIALIST_CONFIGS

__all__ = [
    "SPECIALIST_CONFIGS",
    "AgentError",
    "AgentFactory",
    "BaseAgent",
    "CritiqueAgent",
    "MetaPrompter",
    "SpecialistAgent",
]
