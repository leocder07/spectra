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
    WorkspaceFilterPort — ``.gitignore`` + ``.spectraignore`` honor (Capability #6).
    SecretScannerPort — Pre-flight regex secret scan (Capability #6).

Helpers:
    is_local_path — Pure classifier distinguishing local paths from URLs.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — used by Protocol signatures at runtime
from pathlib import Path
from typing import Protocol

from spectra.entities.audit import AuditEvent
from spectra.entities.enums import AgentRole, Dimension
from spectra.entities.models import (
    AnalysisReport,
    Approver,
    BatchCacheKey,
    CacheStats,
    Finding,
    Policy,
    RepoCacheKey,
    SecretFinding,
    Violation,
    Waiver,
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

    def on_cache_lookup(self, dimension: Dimension, hits: int, total: int) -> None:
        """Report per-dimension batch-cache lookup tally (Phase 3).

        Called once per dimension after ``partition_by_cache`` to surface
        the killer-feature signal — e.g. ``security cache 7/8 hits``.
        """
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

    def clear_all(self) -> int:
        """Purge every cache table and return the total rows deleted (Phase 4)."""
        ...

    def clear_by_repo(self, repo_signature: str) -> int:
        """Purge rows tagged with ``repo_signature``; return rows deleted (Phase 4)."""
        ...

    def prune_older_than(
        self,
        cutoff: datetime,
        include_hit_log: bool = False,
    ) -> dict[str, int]:
        """GC rows whose ``computed_at`` is older than ``cutoff`` (Phase 4).

        Returns a ``{table_name: rows_deleted}`` map for the data tables;
        ``hit_log`` is included only when ``include_hit_log=True``.
        """
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

    def get_batch_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """Return cached findings for a batch, or ``None`` on miss (Phase 3)."""
        ...

    def put_batch_findings(
        self,
        key: BatchCacheKey,
        findings: tuple[Finding, ...],
    ) -> None:
        """Persist findings for a batch under the composite key (Phase 3)."""
        ...

    def record_hit(
        self,
        dimension: Dimension,
        batch_id: str,
        hit: bool,
    ) -> None:
        """Append a row to ``hit_log`` — fire-and-forget telemetry."""
        ...

    def bind_run_context(
        self,
        model_versions: str,
        prompt_versions: str,
        schema_version: str,
        spectra_version: str,
    ) -> None:
        """Atomically bind the four versions used by every cache key."""
        ...

    def batch_key_for(
        self,
        batch_id: str,
        dimension: Dimension,
    ) -> BatchCacheKey | None:
        """Build a ``BatchCacheKey`` from the bound run context.

        Returns ``None`` when ``bind_run_context`` has not been called —
        callers short-circuit per-batch caching for that run.
        """
        ...


class WorkspaceFilterPort(Protocol):
    """Port for excluding files from analysis based on ignore patterns.

    Implemented by ``PathspecFilterAdapter``. The adapter reads
    ``.gitignore`` (root + nested) and ``.spectraignore`` from the
    workspace root and returns the input file list with matched paths
    removed. Bypassing ``.gitignore`` is a constructor decision in the
    adapter — the port itself is policy-free.
    """

    def filter_files(self, repo_dir: str, file_paths: list[str]) -> list[str]:
        """Return the subset of ``file_paths`` that pass every active ignore filter.

        Args:
            repo_dir: Absolute path to the workspace root. Used to locate
                ignore files; never written to.
            file_paths: Repository-relative paths to evaluate.

        Returns:
            Paths kept after applying ``.gitignore`` (when honored) and
            ``.spectraignore``. Input order is preserved.
        """
        ...


class AuditPort(Protocol):
    """Append-only audit-event sink (ADR-018).

    Implementations route to JSONL files, OTLP collectors, stdout, or
    cloud-native log services. Every method is best-effort: emit failures
    must NEVER abort the analysis pipeline. Callers wrap calls with
    :func:`spectra.use_cases.audit.safe_emit` to enforce that contract.
    """

    async def emit(self, event: AuditEvent) -> None:
        """Persist a single audit event.

        Implementations swallow transient I/O errors internally where
        possible; outright exceptions are caught by ``safe_emit`` so the
        pipeline keeps running.
        """
        ...

    async def flush(self) -> None:
        """Force any buffered events to the sink.

        Called once at pipeline shutdown. Adapters with no buffer return
        immediately.
        """
        ...


class PolicyPort(Protocol):
    """Port for ``.spectra-policy.yml`` loading and evaluation (Capability #17).

    Implemented by ``YamlPolicyAdapter``. ``load`` returns ``EmptyPolicy``
    for missing files (no-op gate); malformed YAML raises ``AgentError``
    SPEC-012 with the failing field path baked into the message.
    """

    def load(self, path: Path) -> Policy:
        """Read ``.spectra-policy.yml`` from ``path``; return a frozen ``Policy``."""
        ...

    def evaluate(
        self,
        policy: Policy,
        report: AnalysisReport,
    ) -> tuple[Violation, ...]:
        """Run every gate; return a tuple of ``Violation`` (empty = pass)."""
        ...


class WaiverPort(Protocol):
    """Port for ``.spectra-waivers.yml`` loading and signature verification (#18).

    Implemented by ``YamlWaiverAdapter``. Waivers without a valid Ed25519
    signature (against the approver public keys in ``.spectra-approvers.yml``)
    are silently dropped — never a soft fail. Expired waivers are kept but
    surfaced via the ``expired_waivers`` channel so callers can warn.
    """

    def load(
        self,
        waivers_path: Path,
        approvers_path: Path,
    ) -> tuple[tuple[Waiver, ...], tuple[Waiver, ...]]:
        """Return ``(active, expired)`` tuples of validated waivers.

        Both tuples contain only signature-verified waivers; ``active``
        excludes any waiver past ``expires_at``.
        """
        ...

    def load_approvers(self, path: Path) -> tuple[Approver, ...]:
        """Read ``.spectra-approvers.yml``; empty file → empty tuple."""
        ...

    def verify(
        self,
        waiver: Waiver,
        approvers: tuple[Approver, ...],
    ) -> bool:
        """Verify ``waiver.signature`` against any approver public key."""
        ...


class SecretScannerPort(Protocol):
    """Port for the pre-flight secret scan.

    Implemented by ``RegexSecretScanner``. The scanner reads each file
    once and returns a tuple of matches; it never raises on per-file
    I/O errors (an unreadable file simply yields no matches), so the
    pipeline can never be blocked by a transient read failure.
    """

    def scan(
        self,
        repo_dir: str,
        file_paths: list[str],
    ) -> tuple[SecretFinding, ...]:
        """Scan ``file_paths`` (relative to ``repo_dir``) for known secret patterns.

        Args:
            repo_dir: Absolute path to the workspace root.
            file_paths: Repository-relative paths already filtered by
                ``WorkspaceFilterPort``. Scanning a filtered-out file
                would defeat the .gitignore guarantee.

        Returns:
            Tuple of ``SecretFinding`` matches. Empty tuple means clean.
        """
        ...
