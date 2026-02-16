"""Tests for AgentFactory — agent creation by role."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.infrastructure.agents.critique_agent import CritiqueAgent
from spectra.infrastructure.agents.meta_prompter import MetaPrompter
from spectra.infrastructure.agents.specialist_agent import SpecialistAgent


@pytest.fixture
def factory() -> AgentFactory:
    gateway = AsyncMock()
    return AgentFactory(gateway=gateway)


class TestAgentFactory:
    def test_create_meta_prompter(self, factory: AgentFactory):
        agent = factory.create("meta_prompter")
        assert isinstance(agent, MetaPrompter)
        assert agent.role == "meta_prompter"

    def test_create_critique(self, factory: AgentFactory):
        agent = factory.create("critique")
        assert isinstance(agent, CritiqueAgent)
        assert agent.role == "critique"

    @pytest.mark.parametrize(
        "role",
        [
            "architecture",
            "security",
            "quality",
            "documentation",
            "dependency",
            "performance",
        ],
    )
    def test_create_specialist(self, factory: AgentFactory, role: str):
        agent = factory.create(role)
        assert isinstance(agent, SpecialistAgent)
        assert agent.role == role

    def test_unknown_role_raises(self, factory: AgentFactory):
        with pytest.raises(ValueError, match="Unknown agent role"):
            factory.create("nonexistent")

    def test_create_specialists_returns_six(self, factory: AgentFactory):
        specialists = factory.create_specialists()
        assert len(specialists) == 6

    def test_create_specialists_roles(self, factory: AgentFactory):
        specialists = factory.create_specialists()
        roles = {s.role for s in specialists}
        assert roles == {
            "architecture",
            "security",
            "quality",
            "documentation",
            "dependency",
            "performance",
        }

    def test_specialists_are_all_specialist_agents(self, factory: AgentFactory):
        specialists = factory.create_specialists()
        for s in specialists:
            assert isinstance(s, SpecialistAgent)

    def test_meta_prompter_uses_sonnet_4_5(self, factory: AgentFactory):
        agent = factory.create("meta_prompter")
        assert agent._model == "claude-sonnet-4-5-20250929"

    def test_critique_uses_opus(self, factory: AgentFactory):
        agent = factory.create("critique")
        assert "opus" in agent._model

    def test_security_specialist_has_system_prompt(self, factory: AgentFactory):
        agent = factory.create("security")
        assert len(agent._system_prompt) > 0

    def test_architecture_specialist_has_system_prompt(self, factory: AgentFactory):
        agent = factory.create("architecture")
        assert len(agent._system_prompt) > 0

    def test_all_specialists_have_system_prompts(self, factory: AgentFactory):
        for role in ["architecture", "security", "quality", "documentation", "dependency", "performance"]:
            agent = factory.create(role)
            assert len(agent._system_prompt) > 0

    def test_factory_shares_gateway(self, factory: AgentFactory):
        a1 = factory.create("security")
        a2 = factory.create("architecture")
        assert a1._gateway is a2._gateway

    def test_create_specialists_returns_list(self, factory: AgentFactory):
        result = factory.create_specialists()
        assert isinstance(result, list)
