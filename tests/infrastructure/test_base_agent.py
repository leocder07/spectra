"""Tests for BaseAgent — template method lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spectra.entities.errors import AgentError
from spectra.entities.models import Finding
from spectra.infrastructure.agents.base_agent import BaseAgent, _extract_json_object


class StubAgent(BaseAgent):
    """Concrete BaseAgent for testing the template method flow."""

    def validate_input(self, user_prompt: str) -> None:
        if not user_prompt.strip():
            raise ValueError("empty input")

    def build_prompt(self, user_prompt: str) -> str:
        return f"ANALYZE:\n{user_prompt}"

    def validate_output(self, parsed: dict[str, list[dict[str, str | int | float]]]) -> tuple[Finding, ...]:
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
        mock_gateway.analyze.assert_called_once()
        call_kwargs = mock_gateway.analyze.call_args.kwargs
        assert call_kwargs["system_prompt"] == "You are a test agent."
        assert call_kwargs["user_prompt"] == "test prompt"
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["max_tokens"] == 1000

    def test_format_result_with_actual_tokens(self, agent: StubAgent):
        result = agent.format_result((), "response", 2.0, tokens_used=500)
        assert result.tokens_used == 500

    def test_format_result_with_dimension_score(self, agent: StubAgent):
        result = agent.format_result((), "response", 1.0, 100, dimension_score=88.5)
        assert result.dimension_score == 88.5

    def test_format_result_without_dimension_score(self, agent: StubAgent):
        result = agent.format_result((), "response", 1.0, 100)
        assert result.dimension_score is None

    def test_extract_dimension_score_valid(self, agent: StubAgent):
        parsed = {"dimension_score": 75}
        assert agent._extract_dimension_score(parsed) == 75.0

    def test_extract_dimension_score_float(self, agent: StubAgent):
        parsed = {"dimension_score": 82.5}
        assert agent._extract_dimension_score(parsed) == 82.5

    def test_extract_dimension_score_out_of_range_high(self, agent: StubAgent):
        parsed = {"dimension_score": 101}
        assert agent._extract_dimension_score(parsed) is None

    def test_extract_dimension_score_negative(self, agent: StubAgent):
        parsed = {"dimension_score": -5}
        assert agent._extract_dimension_score(parsed) is None

    def test_extract_dimension_score_missing(self, agent: StubAgent):
        parsed = {"findings": []}
        assert agent._extract_dimension_score(parsed) is None

    def test_extract_dimension_score_string(self, agent: StubAgent):
        parsed = {"dimension_score": "high"}
        assert agent._extract_dimension_score(parsed) is None

    def test_extract_dimension_score_zero(self, agent: StubAgent):
        parsed = {"dimension_score": 0}
        assert agent._extract_dimension_score(parsed) == 0.0

    def test_extract_dimension_score_hundred(self, agent: StubAgent):
        parsed = {"dimension_score": 100}
        assert agent._extract_dimension_score(parsed) == 100.0

    def test_get_tokens_used_from_gateway(self, agent: StubAgent):
        # mock_gateway has last_usage = (100, 50)
        assert agent._get_tokens_used() == 150

    def test_get_tokens_used_no_attribute(self, mock_gateway: AsyncMock):
        del mock_gateway.last_usage
        agent = StubAgent(
            role="architecture",
            gateway=mock_gateway,
            model="test",
            system_prompt="test",
            max_tokens=100,
        )
        assert agent._get_tokens_used() == 0

    def test_parse_output_nested_json(self, agent: StubAgent):
        raw = '{"findings": [{"title": "test", "severity": "high"}]}'
        result = agent.parse_output(raw)
        assert len(result["findings"]) == 1

    def test_parse_output_json_with_prefix_text(self, agent: StubAgent):
        raw = 'Here is the analysis:\n{"findings": []}'
        result = agent.parse_output(raw)
        assert result == {"findings": []}

    def test_parse_output_empty_code_fence(self, agent: StubAgent):
        raw = '```\n{"findings": []}\n```'
        result = agent.parse_output(raw)
        assert "findings" in result

    @pytest.mark.asyncio
    async def test_run_records_duration(self, agent: StubAgent):
        output = await agent.run("test code")
        assert output.duration_seconds >= 0


# ── _extract_json_object ──────────────────────────────────────


class TestExtractJsonObject:
    def test_valid_json(self):
        result = _extract_json_object('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        result = _extract_json_object('text before {"key": "value"} text after')
        assert result == {"key": "value"}

    def test_no_json(self):
        assert _extract_json_object("no json here") is None

    def test_no_opening_brace(self):
        assert _extract_json_object("just text") is None

    def test_brace_before_closing(self):
        assert _extract_json_object("}bad{") is None

    def test_invalid_json_inside_braces(self):
        assert _extract_json_object("{not: valid json}") is None

    def test_empty_object(self):
        result = _extract_json_object("{}")
        assert result == {}

    def test_nested_objects(self):
        raw = '{"outer": {"inner": 1}}'
        result = _extract_json_object(raw)
        assert result == {"outer": {"inner": 1}}

    def test_empty_string(self):
        assert _extract_json_object("") is None
