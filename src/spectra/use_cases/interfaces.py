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
    CachePort — Per-file finding cache (Phase 1, additive).

Helpers:
    is_local_path — Pure classifier distinguishing local paths from URLs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from spectra.entities.enums import AgentRole, Dimension
from spectra.entities.models import (
    AnalysisReport,
    CacheStats,
    Finding,
    RepoCacheKey,
)

# Prefixes that unambiguously denote a local filesystem source.
_LOCAL_PREFIXES: tuple[str, ...] = ("/", "./", "../", "~", "file://")
# Schemes that unambiguously denote a remote source.
_REMOTE_SCHEMES: tuple[str, ...] = (
    "http://",
    "https://",
    "git://",
    "ssh://",
    "git@",
)


def is_local_path(source: str) -> bool:
    """Classify a source string as a local path or remote URL.

    A source is local when it:
      - starts with ``/``, ``./``, ``../``, ``~``, or ``file://``; or
      - is ``.`` (current directory shorthand); or
      - is a relative name that resolves to an existing directory.

    Remote schemes (``https://``, ``git@``, ``ssh://``, ``git://``) are
    always classified as non-local. The classifier never raises.

    Args:
        source: User-supplied repository reference.

    Returns:
        True when ``source`` is a local filesystem reference.
    """
    if not source:
        return False
    if source == ".":
        return True
    if any(source.startswith(s) for s in _REMOTE_SCHEMES):
        return False
    if any(source.startswith(p) for p in _LOCAL_PREFIXES):
        return True
    try:
        return Path(source).is_dir()
    except OSError:
        return False


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

    async def prepare_workspace(self, source: str, target_dir: str) -> str:
        """Resolve ``source`` into a usable on-disk repository directory.

        For HTTPS URLs, clones into ``target_dir`` and returns it. For
        local paths, validates the directory holds a git checkout and
        returns its absolute path (``target_dir`` is ignored).

        Implementations MUST reject path-traversal segments, symlinked
        directories, and paths missing a ``.git/`` subdirectory.

        Args:
            source: Either an HTTPS URL or a local filesystem path.
            target_dir: Destination directory for clones (URL sources).

        Returns:
            Absolute path to the prepared repository directory.

        Raises:
            GitError: SPEC-001 on any validation or clone failure.
        """
        ...

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


class CachePort(Protocol):
    """Port for the per-file finding cache.

    Implemented by ``SqliteCacheAdapter``. All methods are synchronous —
    the cache is local I/O, not networked. Lookups return ``None`` on
    miss rather than raising; serious I/O failures raise ``AgentError``
    with code ``SPEC-010`` so callers can degrade gracefully.
    """

    def get_findings(
        self,
        file_hash: str,
        dimension: Dimension,
    ) -> tuple[Finding, ...] | None:
        """Return cached findings or ``None`` on miss."""
        ...

    def put_findings(
        self,
        file_hash: str,
        dimension: Dimension,
        findings: tuple[Finding, ...],
        model_version: str,
        prompt_version: str,
    ) -> None:
        """Persist findings keyed by (file_hash, dimension)."""
        ...

    def compute_repo_signature(
        self,
        file_tree: tuple[str, ...],
    ) -> str:
        """Return a deterministic signature of the file tree."""
        ...

    def stats(self) -> CacheStats:
        """Return aggregate cache statistics."""
        ...

    def clear(self, repo_signature: str | None = None) -> int:
        """Purge entries; return the count removed."""
        ...

    def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        """Return the full ``AnalysisReport`` cached under ``key``, or ``None`` on miss.

        Phase 2 repo-level shortcut: when the file tree, model versions,
        prompt versions, schema version, and spectra version all match
        the previous successful run, callers can skip the entire ANALYZE
        + CRITIQUE pipeline and return the cached report directly.
        """
        ...

    def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        """Persist ``report`` under ``key`` for the Phase 2 short-circuit."""
        ...
