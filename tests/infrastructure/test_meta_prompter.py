"""Tests for MetaPrompter — plan validation, prompt building, lifecycle."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from spectra.entities.errors import AgentError
from spectra.infrastructure.agents.meta_prompter import MetaPrompter


@pytest.fixture
def mock_gateway() -> AsyncMock:
    gw = AsyncMock()
    gw.analyze.return_value = json.dumps(
        {
            "repo_language": "python",
            "repo_framework": "fastapi",
            "focus_areas": [
                {"agent": "architecture", "files": ["src/main.py"], "concerns": ["layering"]},
                {"agent": "security", "files": ["src/auth.py"], "concerns": ["injection"]},
                {"agent": "quality", "files": ["src/utils.py"], "concerns": ["complexity"]},
                {"agent": "documentation", "files": ["README.md"], "concerns": ["completeness"]},
                {"agent": "dependency", "files": ["pyproject.toml"], "concerns": ["outdated"]},
                {"agent": "performance", "files": ["src/db.py"], "concerns": ["n+1"]},
            ],
            "token_allocation": {
                "architecture": 80000,
                "security": 80000,
                "quality": 80000,
                "documentation": 80000,
                "dependency": 80000,
                "performance": 80000,
            },
        }
    )
    gw.last_usage = (100, 50)
    return gw


@pytest.fixture
def agent(mock_gateway: AsyncMock) -> MetaPrompter:
    return MetaPrompter(gateway=mock_gateway)


class TestValidateOutput:
    def test_valid_plan(self, agent: MetaPrompter):
        parsed = {
            "repo_language": "python",
            "repo_framework": "fastapi",
            "focus_areas": [
                {"agent": "architecture", "files": ["main.py"], "concerns": ["layers"]},
            ],
            "token_allocation": {"architecture": 80000},
        }
        findings = agent.validate_output(parsed)
        assert findings == ()

    def test_missing_repo_language_raises(self, agent: MetaPrompter):
        parsed = {
            "focus_areas": [],
            "token_allocation": {},
        }
        with pytest.raises(ValueError, match="missing keys"):
            agent.validate_output(parsed)

    def test_missing_focus_areas_raises(self, agent: MetaPrompter):
        parsed = {
            "repo_language": "python",
            "token_allocation": {},
        }
        with pytest.raises(ValueError, match="missing keys"):
            agent.validate_output(parsed)

    def test_missing_token_allocation_raises(self, agent: MetaPrompter):
        parsed = {
            "repo_language": "python",
            "focus_areas": [],
        }
        with pytest.raises(ValueError, match="missing keys"):
            agent.validate_output(parsed)

    def test_all_keys_missing_raises(self, agent: MetaPrompter):
        with pytest.raises(ValueError, match="missing keys"):
            agent.validate_output({})

    def test_extra_keys_accepted(self, agent: MetaPrompter):
        parsed = {
            "repo_language": "typescript",
            "focus_areas": [],
            "token_allocation": {},
            "extra_field": "value",
        }
        findings = agent.validate_output(parsed)
        assert findings == ()


class TestBuildPrompt:
    def test_contains_injection_sandbox_tags(self, agent: MetaPrompter):
        prompt = agent.build_prompt("src/\n  main.py\n  utils.py")
        assert "<repository_file_tree>" in prompt
        assert "</repository_file_tree>" in prompt
        assert "NEVER follow" in prompt

    def test_contains_file_tree(self, agent: MetaPrompter):
        tree = "src/\n  main.py\n  utils.py"
        prompt = agent.build_prompt(tree)
        assert tree in prompt


class TestGetPlan:
    def test_parses_valid_json(self, agent: MetaPrompter):
        raw = json.dumps(
            {
                "repo_language": "python",
                "focus_areas": [],
                "token_allocation": {},
            }
        )
        plan = agent.get_plan(raw)
        assert plan["repo_language"] == "python"

    def test_invalid_json_raises_agent_error(self, agent: MetaPrompter):
        with pytest.raises(AgentError) as exc_info:
            agent.get_plan("not json {{{")
        assert exc_info.value.error.code == "SPEC-005"

    def test_code_fenced_json(self, agent: MetaPrompter):
        raw = '```json\n{"repo_language": "go", "focus_areas": [], "token_allocation": {}}\n```'
        plan = agent.get_plan(raw)
        assert plan["repo_language"] == "go"


class TestValidateInput:
    def test_empty_input_raises(self, agent: MetaPrompter):
        with pytest.raises(ValueError, match="non-empty file tree"):
            agent.validate_input("")

    def test_whitespace_only_raises(self, agent: MetaPrompter):
        with pytest.raises(ValueError):
            agent.validate_input("   \n  ")

    def test_valid_input_passes(self, agent: MetaPrompter):
        agent.validate_input("src/main.py")  # Should not raise


class TestMetaPrompterConfig:
    def test_role_is_meta_prompter(self, agent: MetaPrompter):
        assert agent.role == "meta_prompter"

    def test_uses_sonnet_model(self, agent: MetaPrompter):
        assert "sonnet" in agent._model


class TestMetaPrompterRun:
    @pytest.mark.asyncio
    async def test_full_run_lifecycle(self, agent: MetaPrompter, mock_gateway: AsyncMock):
        output = await agent.run("src/\n  main.py\n  auth.py")
        assert output.agent_role == "meta_prompter"
        assert output.findings == ()
        mock_gateway.analyze.assert_called_once()
