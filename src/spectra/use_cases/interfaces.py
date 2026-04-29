"""Protocol interfaces (ports) for dependency inversion.

Layer 2 imports only from entities. These protocols define the
boundaries between the use-case layer and the infrastructure layer,
following the Dependency Inversion Principle.

Protocols defined here:
    LLMGateway — Async LLM inference (standard + adaptive thinking).
    GitPort — Repository clone, file tree, and file read operations.
    TokenPort — Token counting and budget checks via tiktoken.
    ReportPort — Render AnalysisReport to HTML via Jinja2.
    ProgressObserver — Pipeline stage and agent lifecycle callbacks.
"""

from __future__ import annotations

from typing import Protocol

from spectra.entities.enums import AgentRole
from spectra.entities.models import AnalysisReport


class LLMGateway(Protocol):
    """Port for LLM inference calls.

    Implemented by ``AnthropicAdapter``, wrapped by ``RetryDecorator``
    and ``LoggingDecorator`` in the decorator chain.
    """

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
    ) -> str:
        """Send a standard inference request.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User-level content to analyze.
            model: Anthropic model identifier.
            max_tokens: Maximum response tokens.
            effort: Optional ``output_config.effort`` (``low|medium|high|xhigh|max``).
                Opus 4.7 supports ``xhigh``; ``max`` is Opus-tier only.

        Returns:
            Raw LLM text response.
        """
        ...

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,
    ) -> str:
        """Send an inference request with adaptive thinking enabled.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User-level content to analyze.
            model: Anthropic model identifier.
            max_tokens: Maximum response tokens (per-response cap).
            effort: Optional ``output_config.effort`` (``low|medium|high|xhigh|max``).
            task_budget_tokens: Optional cumulative loop budget (min 20_000).
                Activates the ``task-budgets-2026-03-13`` beta header.

        Returns:
            Raw LLM text response (thinking blocks excluded).
        """
        ...


class GitPort(Protocol):
    """Port for repository operations.

    Implemented by ``GitAdapter`` using GitPython.
    """

    async def clone(self, repo_url: str, target_dir: str) -> None:
        """Clone a repository to the target directory."""
        ...

    async def get_file_tree(self, repo_dir: str) -> list[str]:
        """Return sorted list of repository-relative file paths."""
        ...

    async def read_file(self, repo_dir: str, file_path: str) -> str:
        """Read a single file's contents as UTF-8 text."""
        ...

    async def validate_repo_size(self, repo_dir: str) -> None:
        """Raise ValueError if the repository exceeds size limits."""
        ...


class TokenPort(Protocol):
    """Port for token counting and budget checks.

    Implemented by ``TiktokenAdapter``.
    """

    def count(self, text: str) -> int:
        """Return the token count for the given text."""
        ...

    def fits_budget(self, text: str, budget: int) -> bool:
        """Return True if text fits within the token budget."""
        ...


class ReportPort(Protocol):
    """Port for rendering analysis reports to file.

    Implemented by ``ReportAdapter`` using Jinja2.
    """

    def render(self, report: AnalysisReport, output_path: str) -> str:
        """Render a report to the given path and return the path."""
        ...


class ProgressObserver(Protocol):
    """Port for pipeline progress updates.

    Implemented by ``RichProgressReporter`` for terminal output.
    """

    def on_stage_start(self, stage: str, message: str) -> None:
        """Called when a pipeline stage begins."""
        ...

    def on_stage_complete(self, stage: str, message: str) -> None:
        """Called when a pipeline stage completes successfully."""
        ...

    def on_agent_start(self, agent: AgentRole) -> None:
        """Called when an agent begins execution."""
        ...

    def on_agent_success(self, agent: AgentRole, duration: float) -> None:
        """Called when an agent completes successfully."""
        ...

    def on_agent_failure(self, agent: AgentRole, error: str) -> None:
        """Called when an agent fails with an error."""
        ...

    def on_error(self, stage: str, error: str) -> None:
        """Called when a stage-level error occurs."""
        ...
