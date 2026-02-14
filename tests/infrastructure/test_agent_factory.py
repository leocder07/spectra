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

    @pytest.mark.parametrize("role", [
        "architecture", "security", "quality",
        "documentation", "dependency", "performance",
    ])
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
            "architecture", "security", "quality",
            "documentation", "dependency", "performance",
        }
