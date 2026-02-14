"""Tests for BaseAgent — template method lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spectra.entities.errors import AgentError
from spectra.entities.models import Finding
from spectra.infrastructure.agents.base_agent import BaseAgent


class StubAgent(BaseAgent):
    """Concrete BaseAgent for testing the template method flow."""

    def validate_input(self, user_prompt: str) -> None:
        if not user_prompt.strip():
            raise ValueError("empty input")

    def build_prompt(self, user_prompt: str) -> str:
        return f"ANALYZE:\n{user_prompt}"

    def validate_output(
        self, parsed: dict[str, list[dict[str, str | int | float]]]
    ) -> tuple[Finding, ...]:
        return ()


@pytest.fixture
def mock_gateway() -> AsyncMock:
    gw = AsyncMock()
    gw.analyze.return_value = '{"findings": []}'
    gw.last_usage = (100, 50)
    return gw


@pytest.fixture
def agent(mock_gateway: AsyncMock) -> StubAgent:
    return StubAgent(
        role="architecture",
        gateway=mock_gateway,
        model="test-model",
        system_prompt="You are a test agent.",
        max_tokens=1000,
    )


class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_run_template_method_flow(self, agent: StubAgent, mock_gateway: AsyncMock):
        output = await agent.run("source code here")
        assert output.agent_role == "architecture"
        assert output.findings == ()
        assert output.tokens_used > 0
        assert output.duration_seconds >= 0
        assert output.raw_response == '{"findings": []}'
        mock_gateway.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_input_called(self, agent: StubAgent):
        with pytest.raises(ValueError, match="empty input"):
            await agent.run("")

    @pytest.mark.asyncio
    async def test_build_prompt_formats_input(self, agent: StubAgent, mock_gateway: AsyncMock):
        await agent.run("test code")
        call_args = mock_gateway.analyze.call_args
        assert "ANALYZE:\ntest code" in call_args.kwargs["user_prompt"]

    def test_parse_output_valid_json(self, agent: StubAgent):
        result = agent.parse_output('{"findings": []}')
        assert result == {"findings": []}

    def test_parse_output_code_fence(self, agent: StubAgent):
        raw = '```json\n{"findings": []}\n```'
        result = agent.parse_output(raw)
        assert result == {"findings": []}

    def test_parse_output_invalid_json(self, agent: StubAgent):
        with pytest.raises(AgentError) as exc_info:
            agent.parse_output("not json at all")
        assert exc_info.value.error.code == "SPEC-005"

    def test_format_result_tokens_estimation(self, agent: StubAgent):
        result = agent.format_result((), "a" * 400, 1.5)
        assert result.tokens_used == 100  # 400 // 4
        assert result.duration_seconds == 1.5

    def test_format_result_minimum_one_token(self, agent: StubAgent):
        result = agent.format_result((), "", 0.1)
        assert result.tokens_used >= 1

    def test_role_property(self, agent: StubAgent):
        assert agent.role == "architecture"

    @pytest.mark.asyncio
    async def test_execute_llm_passes_params(self, agent: StubAgent, mock_gateway: AsyncMock):
        await agent.execute_llm("test prompt")
        mock_gateway.analyze.assert_called_once_with(
            system_prompt="You are a test agent.",
            user_prompt="test prompt",
            model="test-model",
            max_tokens=1000,
        )
