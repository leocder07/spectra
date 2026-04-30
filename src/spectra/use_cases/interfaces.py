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
    RemoteCachePort — Distributed L2 cache (ADR-021, capability #21).
    WorkspaceFilterPort — ``.gitignore`` + ``.spectraignore`` honor (Capability #6).
    SecretScannerPort — Pre-flight regex secret scan (Capability #6).
    TracerPort — Span lifecycle for distributed tracing (ADR-023, #30 + #33).

Helpers:
    is_local_path — Pure classifier distinguishing local paths from URLs.

ADR references in this module: ADR-001 (clean architecture / port pattern),
ADR-006 (cache port), ADR-013 (cost tracker), ADR-018 (audit port),
ADR-021 (distributed cache port), ADR-023 (tracer port). See ``docs/architecture/adr/`` and
``docs/glossary.md`` for the at-a-glance ADR index.
"""

from __future__ import annotations

from contextlib import AbstractContextManager  # noqa: TC003 — used by Protocol signatures at runtime
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
    ReportSummary,
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
        cache_breakpoint_index: int | None = None,
    ) -> str:
        """Send a standard inference request.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User-level content to analyze.
            model: Anthropic model identifier.
            max_tokens: Maximum response tokens.
            effort: Optional ``output_config.effort`` (``low|medium|high|xhigh|max``).
                Opus 4.7 supports ``xhigh``; ``max`` is Opus-tier only.
            cache_breakpoint_index: Optional byte index into ``system_prompt``
                marking the end of the cacheable prefix (ADR-024). When set,
                Anthropic-backed adapters add a ``cache_control: ephemeral``
                marker on the prefix; other adapters silently ignore the hint.

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
        cache_breakpoint_index: int | None = None,
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
            cache_breakpoint_index: See :meth:`analyze` (ADR-024).

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


class RemoteCachePort(Protocol):
    """Distributed L2 cache backend (ADR-021, capability #21).

    A sibling of ``CachePort`` — same composite-key contract, different
    operational profile. ``CachePort`` is sync-friendly, single-machine,
    ~50µs per call. ``RemoteCachePort`` is async-mandatory, networked,
    eventually consistent across writers, and carries its own failure
    model (connection refused / timeout / auth → SPEC-010 + degrade to
    no-cache for the remainder of the run; never fatal).

    The two protocols share entities — every ``BatchCacheKey`` /
    ``RepoCacheKey`` carries the six-component composite signature so a
    stale row at L2 never matches a current-context lookup. Per-row
    HMAC verification (ADR-012) is enforced at this tier as well; the
    same per-user keyring secret derives both MACs but with a port-name
    domain separator so the local and remote MACs cannot coincide for
    the same payload bytes.

    Implementations: ``RedisCacheAdapter`` (capability #21).
    Composition: ``TieredCacheAdapter`` wraps a ``CachePort`` (L1) plus
    a ``RemoteCachePort`` (L2) and itself implements both protocols.
    """

    async def get_findings(self, key: BatchCacheKey) -> tuple[Finding, ...] | None:
        """Return cached batch findings or ``None`` on miss."""
        ...

    async def put_findings(self, key: BatchCacheKey, findings: tuple[Finding, ...]) -> None:
        """Persist findings for a batch under the composite ``key``."""
        ...

    async def get_full_report(self, key: RepoCacheKey) -> AnalysisReport | None:
        """Return the cached full report or ``None`` on miss (Phase 2 short-circuit)."""
        ...

    async def put_full_report(self, key: RepoCacheKey, report: AnalysisReport) -> None:
        """Persist the full ``AnalysisReport`` under ``key`` (write-back path)."""
        ...

    async def health(self) -> bool:
        """Liveness probe — ``False`` triggers downgrade to L1-only for the run."""
        ...


class CostTrackerPort(Protocol):
    """Port for per-run + rolling-hour cost tracking (SPEC-014).

    Implemented by ``InMemoryCostTracker`` (default for solo runs) and
    ``SqliteCostTracker`` (shared ``cache.db`` for ``--max-cost-per-hour``
    enforcement that persists across processes). The orchestrator gates
    each agent call against ``would_exceed`` and records the actual cost
    after a successful return.
    """

    def record(self, agent: str, cost_usd: float) -> None:
        """Append the agent's actual cost to the current run's ledger."""
        ...

    def total(self) -> float:
        """Return total USD recorded for the current run."""
        ...

    def would_exceed(self, additional: float, max_usd: float) -> bool:
        """Return True when ``total() + additional > max_usd``.

        ``additional == 0`` and ``max_usd == 0`` returns False — a
        zero-budget run with no projected cost is technically valid
        (e.g. a fully cached run).
        """
        ...

    def last_hour_total(self) -> float:
        """Return USD recorded across all runs in the rolling 1-hour window."""
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


class SignerPort(Protocol):
    """Port for Ed25519 keypair generation and signing (Fix R3-Arch-3).

    Closes the dependency-rule break in ``adapters/waiver_cli.py`` where
    the CLI subcommand imported ``cryptography.hazmat.primitives.asymmetric.ed25519``
    directly. Implemented by ``Ed25519SignerAdapter`` (Layer 4) and
    injected via ``set_signer`` at composition time.

    Hex encoding contract:
        - ``private_hex`` and ``public_hex`` are 64-char (32-byte) hex strings.
        - ``signature`` is raw bytes (the CLI ``hex()``-encodes for storage).

    Errors:
        Implementations raise ``ValueError`` for malformed hex, wrong-length
        keys, or non-hex digits. Verification failures return ``False``
        rather than raising — the adapter swallows ``InvalidSignature`` so
        callers can branch cleanly without a try/except.
    """

    def generate_keypair(self) -> tuple[str, str]:
        """Mint a fresh Ed25519 keypair as ``(private_hex, public_hex)``."""
        ...

    def derive_public_key(self, private_hex: str) -> str:
        """Derive the public key from a 64-char private hex seed."""
        ...

    def sign(self, payload: bytes, private_hex: str) -> bytes:
        """Sign ``payload`` and return the raw 64-byte signature."""
        ...

    def verify(self, payload: bytes, signature: bytes, public_hex: str) -> bool:
        """Verify ``signature`` over ``payload``; return False on mismatch."""
        ...


class ReportStorePort(Protocol):
    """Append-only history store for scan summaries (#25, ADR-022).

    Powers ``spectra history latest|trend``, the portfolio dashboard,
    Slack drift alerts, and the leaderboard endpoint. Implementations
    persist ``ReportSummary`` rows keyed by ``repo_signature`` and ``ts``
    so range queries are index-only scans.

    The port is async because the production backend (Postgres) issues
    network I/O. The SQLite single-user fallback wraps a synchronous
    sqlite3 connection in ``asyncio.to_thread`` so the contract is the
    same regardless of backend.

    Failure mode: every method swallows transient I/O errors internally
    and surfaces them as logged warnings. Callers wrap the integration
    point in the same ``safe_*`` pattern used for the audit port — a
    history-store outage MUST never abort the analysis pipeline.
    """

    async def store(self, report: ReportSummary) -> None:
        """Persist one scan summary. Latest write wins on duplicate ``scan_id``.

        Idempotent — replaying the same summary is a no-op.
        """
        ...

    async def latest(self, repo_signature: str) -> ReportSummary | None:
        """Return the most recent summary for ``repo_signature`` or ``None``.

        ``None`` is the legitimate "first scan ever" answer; callers
        should treat it as a non-error.
        """
        ...

    async def history(
        self,
        repo_signature: str,
        since: datetime,
        until: datetime,
    ) -> tuple[ReportSummary, ...]:
        """Return summaries for ``repo_signature`` whose ``timestamp`` is in ``[since, until]``.

        Ordered most-recent-first. Half-open interval semantics —
        ``since`` is inclusive, ``until`` is exclusive — mirror the
        ``LAG()`` window query in the drift detector (ADR-022 §6).
        """
        ...


class Span(Protocol):
    """Single span lifecycle (ADR-023). Structural — adapters supply concrete spans.

    The Protocol mirrors a deliberately small subset of OpenTelemetry's
    ``Span`` so adapters stay thin and the use-case layer never imports
    ``opentelemetry.*``. ``set_attribute`` accepts only scalar types
    that round-trip through OTLP without lossy coercion.

    Attribute key discipline (enforced by ``OtelTracerAdapter``):
        - ``cost.usd``, ``tokens.input``, ``tokens.output`` — cost attribution.
        - ``agent.role``, ``agent.model``, ``agent.effort`` — per-agent spans.
        - ``spectra.team``, ``spectra.repo_signature`` — fleet-wide queries.
    Sensitive keys (``*key*``, ``*secret*``, ``*token*``, ``*body*``,
    ``*content*``, ``*code*``) are dropped at attribute set-time by the
    OTel adapter — see ADR-023 §5 (sensitive-attribute boundary).
    """

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """Attach a scalar attribute to this span."""
        ...

    def add_event(self, name: str, attributes: dict[str, object] | None = None) -> None:
        """Append a named event to this span (point-in-time annotation)."""
        ...

    def record_exception(self, exc: BaseException) -> None:
        """Record an exception under the standard OTel ``exception`` event."""
        ...


class TracerPort(Protocol):
    """Port for distributed-tracing span lifecycle (ADR-023, #30 + #33).

    Implemented by ``OtelTracerAdapter`` (Layer 4) when an OTLP endpoint
    is configured, ``InMemoryTracerAdapter`` for tests, and
    ``NoopTracerAdapter`` (default zero-overhead fallback). The use-case
    layer imports this Protocol; it never imports OpenTelemetry.

    The single ``span`` method returns a context manager so the typical
    call site is one ``with`` block — span lifecycle (start, status,
    end) is owned by the adapter. Exceptions inside the block are
    recorded by the adapter and re-raised; tracing must never swallow a
    pipeline failure.
    """

    def span(
        self,
        name: str,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> AbstractContextManager[Span]:
        """Open a span as a context manager.

        Args:
            name: Dotted span name (``spectra.stage.analyze``,
                ``spectra.agent.security``).
            attributes: Optional initial attribute set, applied before
                the span body executes.

        Returns:
            A context manager yielding a :class:`Span` whose
            ``set_attribute``/``add_event``/``record_exception`` methods
            survive even when tracing is disabled (no-op fallback).
        """
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
