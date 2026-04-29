"""Tests for resolve_agent_configs — merging defaults with CLI overrides."""

from __future__ import annotations

import pytest

from spectra.entities.models import _DEFAULT_AGENT_CONFIGS, AgentRunConfig
from spectra.use_cases.resolve_agent_configs import resolve_agent_configs


class TestResolveAgentConfigs:
    def test_no_overrides_returns_defaults(self):
        resolved = resolve_agent_configs({})
        assert resolved == _DEFAULT_AGENT_CONFIGS

    def test_global_model_override_applies_to_all_specialists(self):
        resolved = resolve_agent_configs({"global_model": "claude-sonnet-4-6"})
        for role in ("architecture", "security", "quality", "documentation", "dependency", "performance"):
            assert resolved[role].model == "claude-sonnet-4-6"

    def test_global_effort_override_applies_to_all_specialists(self):
        # Sonnet supports low/medium/high — pick "high" to avoid Opus-only constraint
        resolved = resolve_agent_configs({"global_model": "claude-sonnet-4-6", "global_effort": "high"})
        for role in ("architecture", "security", "quality", "documentation", "dependency", "performance"):
            assert resolved[role].effort == "high"

    def test_per_role_model_override_takes_precedence_over_global(self):
        resolved = resolve_agent_configs(
            {
                "global_model": "claude-sonnet-4-6",
                "models": {"security": "claude-opus-4-6"},
            }
        )
        assert resolved["security"].model == "claude-opus-4-6"
        assert resolved["architecture"].model == "claude-sonnet-4-6"

    def test_per_role_effort_override_takes_precedence_over_global(self):
        resolved = resolve_agent_configs(
            {
                "global_model": "claude-sonnet-4-6",
                "global_effort": "low",
                "efforts": {"security": "high"},
            }
        )
        assert resolved["security"].effort == "high"
        assert resolved["architecture"].effort == "low"

    def test_meta_critique_unaffected_by_global_specialist_model(self):
        resolved = resolve_agent_configs({"global_model": "claude-sonnet-4-6"})
        assert resolved["meta_prompter"].model == "claude-opus-4-7"
        assert resolved["critique"].model == "claude-opus-4-7"

    def test_meta_critique_unaffected_by_global_specialist_effort(self):
        resolved = resolve_agent_configs(
            {"global_model": "claude-sonnet-4-6", "global_effort": "low"}
        )
        assert resolved["meta_prompter"].effort == "medium"
        assert resolved["critique"].effort == "high"

    def test_per_role_overrides_for_meta_and_critique_work(self):
        resolved = resolve_agent_configs(
            {
                "models": {"meta_prompter": "claude-haiku-4-5", "critique": "claude-opus-4-6"},
                "efforts": {"meta_prompter": "low", "critique": "max"},
            }
        )
        assert resolved["meta_prompter"].model == "claude-haiku-4-5"
        assert resolved["meta_prompter"].effort == "low"
        assert resolved["critique"].model == "claude-opus-4-6"
        assert resolved["critique"].effort == "max"

    def test_critique_task_budget_preserved_after_override(self):
        resolved = resolve_agent_configs({"models": {"critique": "claude-opus-4-6"}})
        assert resolved["critique"].task_budget_tokens == 80_000

    def test_unknown_role_in_models_overrides_raises_clear_error(self):
        with pytest.raises(ValueError, match="Unknown agent role"):
            resolve_agent_configs({"models": {"frontend": "claude-opus-4-7"}})

    def test_unknown_role_in_efforts_overrides_raises_clear_error(self):
        with pytest.raises(ValueError, match="Unknown agent role"):
            resolve_agent_configs({"efforts": {"backend": "high"}})

    def test_returns_agent_run_config_instances(self):
        resolved = resolve_agent_configs({})
        for cfg in resolved.values():
            assert isinstance(cfg, AgentRunConfig)

    def test_max_effort_on_haiku_raises_validation_error(self):
        with pytest.raises(ValueError):  # Pydantic ValidationError is a ValueError subclass
            resolve_agent_configs(
                {
                    "models": {"documentation": "claude-haiku-4-5"},
                    "efforts": {"documentation": "max"},
                }
            )
