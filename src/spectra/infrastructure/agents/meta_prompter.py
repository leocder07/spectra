"""MetaPrompter agent — Sonnet 4.5, planning from file tree only."""

from __future__ import annotations

import json

from spectra.entities.models import AgentOutput, Finding
from spectra.infrastructure.agents.base_agent import BaseAgent
from spectra.use_cases.interfaces import LLMGateway

_SYSTEM_PROMPT = """You are a code analysis planning agent. Given a repository file tree,
create an analysis plan that tells specialist agents what to focus on.

OUTPUT FORMAT (JSON):
{
  "repo_language": "python|typescript|java|...",
  "repo_framework": "fastapi|express|spring|...",
  "focus_areas": [
    {"agent": "architecture", "files": [...], "concerns": [...]},
    {"agent": "security", "files": [...], "concerns": [...]},
    {"agent": "quality", "files": [...], "concerns": [...]},
    {"agent": "documentation", "files": [...], "concerns": [...]},
    {"agent": "dependency", "files": [...], "concerns": [...]},
    {"agent": "performance", "files": [...], "concerns": [...]}
  ],
  "token_allocation": {"architecture": N, "security": N, ...}
}

CONSTRAINTS:
- Analyze the file tree ONLY. You will NOT see file contents.
- Budget: 5K tokens max for your response.
- Allocate tokens proportionally to repo complexity per dimension."""


class MetaPrompter(BaseAgent):
    """Plans analysis from file tree. Sonnet 4.5, never sees full code."""

    def __init__(self, gateway: LLMGateway) -> None:
        super().__init__(
            role="meta_prompter",
            gateway=gateway,
            model="claude-sonnet-4-5-20250929",
            system_prompt=_SYSTEM_PROMPT,
            max_tokens=5_000,
        )

    def validate_input(self, user_prompt: str) -> None:
        if not user_prompt.strip():
            msg = "MetaPrompter requires a non-empty file tree"
            raise ValueError(msg)

    def build_prompt(self, user_prompt: str) -> str:
        return f"Repository file tree:\n\n{user_prompt}"

    def validate_output(
        self, parsed: dict[str, list[dict[str, str | int | float]]]
    ) -> tuple[Finding, ...]:
        required = {"repo_language", "focus_areas", "token_allocation"}
        missing = required - set(parsed.keys())
        if missing:
            msg = f"MetaPrompter output missing keys: {missing}"
            raise ValueError(msg)
        return ()

    def get_plan(self, raw_output: str) -> dict[str, list[dict[str, str | int | float]]]:
        return self.parse_output(raw_output)
