"""Agent infrastructure — BaseAgent, factory, and specialist agents.

Pipeline flow:
  MetaPrompter (Sonnet) → 6 SpecialistAgents (Opus, parallel) → CritiqueAgent (Opus, extended thinking)

All agents follow the BaseAgent Template Method lifecycle:
  validate_input → build_prompt → execute_llm → parse_output → validate_output → format_result
"""

from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.infrastructure.agents.base_agent import AgentError, BaseAgent
from spectra.infrastructure.agents.critique_agent import CritiqueAgent
from spectra.infrastructure.agents.meta_prompter import MetaPrompter
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent

__all__ = [
    "AgentError",
    "AgentFactory",
    "BaseAgent",
    "CritiqueAgent",
    "MetaPrompter",
    "SpecialistAgent",
]
