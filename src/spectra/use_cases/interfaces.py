"""Protocol interfaces (ports) — Layer 2 imports only from entities."""

from __future__ import annotations

from typing import Protocol

from spectra.entities.enums import AgentRole
from spectra.entities.models import AnalysisReport


class LLMGateway(Protocol):
    """Port for LLM inference calls."""

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str: ...

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str: ...


class GitPort(Protocol):
    """Port for repository operations."""

    async def clone(self, repo_url: str, target_dir: str) -> None: ...
    async def get_file_tree(self, repo_dir: str) -> list[str]: ...
    async def read_file(self, repo_dir: str, file_path: str) -> str: ...
    async def validate_repo_size(self, repo_dir: str) -> None: ...


class TokenPort(Protocol):
    """Port for token counting and budget checks."""

    def count(self, text: str) -> int: ...
    def fits_budget(self, text: str, budget: int) -> bool: ...


class ReportPort(Protocol):
    """Port for rendering analysis reports."""

    def render(self, report: AnalysisReport, output_path: str) -> str: ...


class ProgressObserver(Protocol):
    """Port for pipeline progress updates (Rich terminal)."""

    def on_stage_start(self, stage: str, message: str) -> None: ...
    def on_stage_complete(self, stage: str, message: str) -> None: ...
    def on_agent_start(self, agent: AgentRole) -> None: ...
    def on_agent_success(self, agent: AgentRole, duration: float) -> None: ...
    def on_agent_failure(self, agent: AgentRole, error: str) -> None: ...
    def on_error(self, stage: str, error: str) -> None: ...
