"""Composition root — wires all dependencies and exposes the CLI entry point.

This is the outermost layer (Layer 4) of Spectra's Clean Architecture. It is
the ONLY module that imports from all inner layers and wires the complete
dependency graph. No other module should perform dependency injection.

Dependency Injection (DI) wiring:

    1. **Decorator chain**: ``LoggingDecorator`` → ``RetryDecorator`` →
       ``AnthropicAdapter``. Each decorator wraps the next, adding
       observability and resilience without modifying the core adapter.
       The chain implements ``LLMGateway`` at every level via structural
       subtyping (Protocol compliance).

    2. **Agent factory**: ``AgentFactory`` receives the fully-decorated
       gateway and creates all 8 agents (MetaPrompter, 6 specialists,
       CritiqueAgent). The factory pattern ensures agents are constructed
       consistently with the same gateway instance.

    3. **Pipeline orchestration**: After cloning the repo (Stage 1: INGEST),
       control is handed to ``analyze_repository()`` which runs Stages 2-5.
       Stage 6 (REPORT) is handled here via ``ReportAdapter`` or JSON output.

    4. **CLI injection**: The ``cli()`` entry point injects ``_run_analysis``
       into the CLI controller via ``set_analyzer_factory()``, completing the
       inversion of control — the CLI never imports infrastructure directly.

Security:
    - Clone directories use ``tempfile.mkdtemp`` with ``0o700`` permissions.
    - Cleanup is guaranteed via ``finally`` block with ``shutil.rmtree``.
    - The Anthropic client is explicitly closed to release connection pools.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from hashlib import blake2b
from pathlib import Path
from typing import TYPE_CHECKING

from spectra import __version__ as _SPECTRA_VERSION  # noqa: N812
from spectra.adapters.cli_controller import (
    cli_entry,
    set_analyzer_factory,
    set_cache_provider,
)
from spectra.adapters.progress_reporter import RichProgressReporter
from spectra.entities.disclaimer import disclaimer_payload
from spectra.entities.errors import ERRORS, AgentError, SpectraError
from spectra.entities.models import (
    AnalysisReport,
    AnalysisRequest,
    CacheSecret,
    Codebase,
    RepoCacheKey,
)
from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.infrastructure.agents.critique_agent import _SYSTEM_PROMPT as _CRITIQUE_PROMPT
from spectra.infrastructure.agents.specialist_prompts import (
    _SHARED_GUIDANCE,
    SPECIALIST_CONFIGS,
)
from spectra.infrastructure.anthropic_adapter import AnthropicAdapter
from spectra.infrastructure.cache_adapter import (
    SCHEMA_VERSION,
    SqliteCacheAdapter,
    default_cache_path,
    migrate_legacy_cache,
)
from spectra.infrastructure.git_adapter import GitAdapter
from spectra.infrastructure.keyring_adapter import KeyringSecretAdapter
from spectra.infrastructure.logging_decorator import LoggingDecorator
from spectra.infrastructure.pathspec_filter_adapter import PathspecFilterAdapter
from spectra.infrastructure.regex_secret_scanner import RegexSecretScanner
from spectra.infrastructure.report_adapter import ReportAdapter
from spectra.infrastructure.retry_decorator import RetryDecorator
from spectra.infrastructure.tiktoken_adapter import TiktokenAdapter
from spectra.use_cases.analyze_repository import PipelineContext, analyze_repository
from spectra.use_cases.interfaces import is_local_path
from spectra.use_cases.preflight import PreflightConfig, run_preflight
from spectra.use_cases.resolve_agent_configs import resolve_agent_configs

if TYPE_CHECKING:
    from collections.abc import Callable


class ReportError(Exception):
    """Raised when report rendering fails (SPEC-009).

    Attributes:
        error: The underlying ``SpectraError`` with code and message.
    """

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


def _build_agents(
    gateway: object,
    agent_overrides: dict[str, object] | None,
    *,
    skip_critique: bool,
) -> tuple[object, list[object], object | None]:
    """Resolve per-agent configs from CLI overrides and build all 8 agents.

    Returns:
        ``(meta_prompter, specialists, critique_agent)``. ``critique_agent``
        is ``None`` when ``skip_critique`` is True.
    """
    configs = resolve_agent_configs(agent_overrides or {})
    factory = AgentFactory(gateway=gateway, configs=configs)  # type: ignore[arg-type]
    return (
        factory.create("meta_prompter"),
        factory.create_specialists(),
        None if skip_critique else factory.create("critique"),
    )


async def _run_analysis(
    repo_url: str,
    output_path: str,
    skip_critique: bool = False,
    output_format: str = "html",
    verbose: bool = False,
    force: bool = False,
    no_cache: bool = False,
    agent_overrides: dict[str, object] | None = None,
    *,
    honor_gitignore: bool = True,
    allow_secrets: bool = False,
) -> AnalysisReport:
    """Run the full pipeline: clone, plan, analyze, critique, report.

    This is the composition root's async entry point. It wires the
    decorator chain (Logging → Retry → Anthropic), creates agents
    via the factory, and delegates to ``analyze_repository``.

    Args:
        repo_url: Git HTTPS URL to analyze.
        output_path: File path for the rendered report.
        skip_critique: Skip CritiqueAgent when True.
        output_format: ``"html"`` or ``"json"``.
        verbose: Enable debug logging when True.
        force: Bypass cache reads and force a fresh run (still writes the cache).
        no_cache: Disable cache reads and writes entirely (CI-safe).
        agent_overrides: Per-agent model/effort overrides from the CLI.
        honor_gitignore: Honor ``.gitignore`` during pre-flight (default True).
            Set False for the ``--no-gitignore`` escape hatch — ``.spectraignore``
            is still applied.
        allow_secrets: Bypass SPEC-011 abort on secret detection (default False).
            When True, findings are logged as a warning and the pipeline proceeds.

    Returns:
        Completed analysis report.

    Raises:
        RuntimeError: If ``ANTHROPIC_API_KEY`` is not set.
        ReportError: If report rendering fails (SPEC-009).
        SecretDetectedError: SPEC-011 when secrets are detected and
            ``allow_secrets`` is False.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        msg = "ANTHROPIC_API_KEY environment variable is required"
        raise RuntimeError(msg)

    # ── DI Wiring: Decorator Chain ────────────────────────────────
    # The chain wraps each layer around the next (innermost → outermost):
    #   AnthropicAdapter (raw API)  ← innermost, actual HTTP calls
    #   → RetryDecorator            ← adds exponential backoff (1s/2s/4s)
    #   → LoggingDecorator          ← adds call logging + timing (outermost)
    # All three satisfy the LLMGateway protocol via structural subtyping.
    observer = RichProgressReporter()
    adapter = AnthropicAdapter(api_key=api_key)
    retry = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
    gateway = LoggingDecorator(retry, observer=observer)

    # ── DI Wiring: Infrastructure Adapters ─────────────────────────
    # GitAdapter implements GitPort (clone, file tree, read_file)
    # ReportAdapter implements ReportPort (Jinja2 HTML rendering)
    # SqliteCacheAdapter implements CachePort (additive in Phase 1 —
    # not yet consumed by analyze_repository; wired so cache state is
    # initialized once per process and closed cleanly on shutdown).
    git = GitAdapter()
    report_renderer = ReportAdapter()
    cache = _provision_cache(no_cache=no_cache)

    workspace_dir, owns_workspace = _allocate_workspace(repo_url)
    try:
        # Stage 1: INGEST — clone or use the local workspace
        ingest_msg = "Indexing local repository" if not owns_workspace else "Cloning repository"
        observer.on_stage_start("INGEST", ingest_msg)
        workspace_dir = await git.prepare_workspace(repo_url, workspace_dir)
        await git.validate_repo_size(workspace_dir)
        file_tree = await git.get_file_tree(workspace_dir)
        observer.on_stage_complete("INGEST", f"{len(file_tree)} files indexed")

        # Stage 1.5: PREFLIGHT — honor .gitignore + .spectraignore, then secret scan.
        # Filtered tree is the canonical input to every downstream stage so
        # an excluded path can never leak into a prompt or the cache key.
        file_tree = _run_preflight_stage(
            workspace_dir,
            file_tree,
            observer,
            honor_gitignore=honor_gitignore,
            allow_secrets=allow_secrets,
        )

        # Pre-read key source files by heuristic for specialist agents
        source_files = await _read_key_source_files(git, workspace_dir, file_tree)

        repo_name = _derive_repo_name(repo_url, workspace_dir)
        codebase = Codebase(
            repo_url=repo_url,
            repo_name=repo_name,
            local_path=workspace_dir,
            file_tree=tuple(file_tree),
        )

        # ── DI Wiring: Agent Factory ──────────────────────────────
        # AgentFactory creates all 8 agents with the decorated gateway.
        # CLI overrides (--model / --<role>-effort / --model-overrides JSON)
        # are merged into a per-role AgentRunConfig map and threaded through.
        meta_prompter, specialists, critique_agent = _build_agents(
            gateway, agent_overrides, skip_critique=skip_critique
        )

        # ── Pipeline Stages 2-5 ──────────────────────────────────
        # Delegates to analyze_repository() which orchestrates:
        # Stage 2: PLAN  — MetaPrompter creates focus areas
        # Stage 3: ANALYZE — 6 specialists run in parallel
        # Stage 4: MERGE — Deduplicate and validate findings
        # Stage 5: CRITIQUE — CritiqueAgent validates (if not skipped)
        request = AnalysisRequest(
            repo_url=repo_url,
            quick=skip_critique,
            output_format=output_format,
        )

        ctx = PipelineContext(
            request=request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=specialists,
            critique_agent=critique_agent,
            git_port=git,
            observer=observer,
            source_files=source_files,
            cache_port=cache,
            cache_key_factory=_make_cache_key_factory() if cache else None,
            force_cache_bypass=force,
        )
        report = await analyze_repository(ctx)

        # Stage 6: REPORT
        observer.on_stage_start("REPORT", "Rendering report")
        try:
            if output_format == "json":
                data = json.dumps(build_json_payload(report), indent=2)
                Path(output_path).write_text(data, encoding="utf-8")
            elif output_format == "sarif":
                sarif = _build_sarif(report)
                Path(output_path).write_text(
                    json.dumps(sarif, indent=2),
                    encoding="utf-8",
                )
            else:
                report_renderer.render(report, output_path)
        except Exception as exc:
            logging.getLogger("spectra").error("Report render failed: %s", exc)
            raise ReportError(ERRORS["SPEC-009"]) from exc
        observer.on_stage_complete("REPORT", "Report generated")

        return report
    finally:
        if owns_workspace:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        await adapter.close()
        _close_cache_quietly(cache)


# ── Cache adapter construction ───────────────────────────────


def _provision_cache(*, no_cache: bool) -> SqliteCacheAdapter | None:
    """Build the cache adapter (when enabled) and bind the Phase 3 run context."""
    if no_cache:
        return None
    cache = _build_cache_adapter()
    if cache is not None:
        _bind_cache_run_context(cache)
    return cache


def _build_cache_adapter() -> SqliteCacheAdapter | None:
    """Construct the SQLite cache adapter, or return None on I/O failure.

    ADR-012 wires the per-user keyring secret in here: ``KeyringSecretAdapter``
    fetches (or generates) the 32-byte HMAC key, and ``SqliteCacheAdapter``
    enforces it on every read/write. If the keyring is unavailable the
    cache is disabled for the run (SPEC-010 — never fatal).

    Legacy cache rescue: any pre-ADR-012 ``cache.db`` at the unscoped
    path is removed before the new adapter opens. The next run cold-caches.
    """
    if migrate_legacy_cache():
        logging.getLogger("spectra").info(
            "Legacy cache.db removed; new per-user cache will be cold-warmed",
        )
    secret = _resolve_cache_secret()
    try:
        return SqliteCacheAdapter(db_path=default_cache_path(), secret=secret)
    except AgentError as exc:
        logging.getLogger("spectra").warning(
            "Cache disabled (%s); analysis will proceed without caching",
            exc.error.code,
        )
        return None


def _resolve_cache_secret() -> CacheSecret | None:
    """Fetch the per-user HMAC secret from the OS keyring; degrade to None."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        # Windows: per-user file isolation degraded; secret unavailable.
        return None
    uid = str(geteuid())
    try:
        return KeyringSecretAdapter(uid=uid).get()
    except AgentError as exc:
        logging.getLogger("spectra").warning(
            "Cache MAC disabled (%s); keyring unavailable for UID %s",
            exc.error.code,
            uid,
        )
        return None


def _provision_cache_only() -> SqliteCacheAdapter:
    """Build a cache adapter for the ``spectra cache *`` subcommands.

    The cache CLI must work without an Anthropic API key, git, or any
    LLM wiring — it only manipulates the local SQLite cache. This factory
    is the seam the CLI controller calls via its ``cache_provider`` getter.
    """
    secret = _resolve_cache_secret()
    return SqliteCacheAdapter(db_path=default_cache_path(), secret=secret)


def _close_cache_quietly(cache: SqliteCacheAdapter | None) -> None:
    """Close the cache adapter, swallowing any SPEC-010 raised during close."""
    if cache is None:
        return
    try:
        cache.close()
    except AgentError:
        logging.getLogger("spectra").debug("Cache close failed; ignoring")


# ── Phase 2: cache key composition ───────────────────────────


def _make_cache_key_factory() -> Callable[[str], RepoCacheKey]:
    """Return a factory binding model + prompt + spectra + schema versions.

    The factory only takes the per-run ``repo_signature``; everything
    else is computed once per process. Keeping this in the composition
    root preserves the dependency rule — the use case never imports
    ``specialist_prompts`` or ``critique_agent``.
    """
    model_versions = _composite_model_versions()
    prompt_versions = _composite_prompt_versions()

    def _factory(repo_signature: str) -> RepoCacheKey:
        return RepoCacheKey(
            repo_signature=repo_signature,
            spectra_version=_SPECTRA_VERSION,
            model_versions=model_versions,
            prompt_versions=prompt_versions,
            schema_version=SCHEMA_VERSION,
        )

    return _factory


def _composite_model_versions() -> str:
    """Canonical sort of model IDs across all 8 agents."""
    models = sorted({cfg[3] for cfg in SPECIALIST_CONFIGS.values()})
    # Add MetaPrompter and Critique model IDs (both Opus 4.7 today; sort dedups).
    models.append("claude-opus-4-7")  # MetaPrompter
    models.append("claude-opus-4-7")  # CritiqueAgent
    return "|".join(sorted(set(models)))


def _composite_prompt_versions() -> str:
    """blake2b digest of every prompt that affects analysis output."""
    digest = blake2b(digest_size=16)
    digest.update(_SHARED_GUIDANCE.encode("utf-8"))
    for role in sorted(SPECIALIST_CONFIGS):
        digest.update(role.encode("utf-8"))
        digest.update(SPECIALIST_CONFIGS[role][2].encode("utf-8"))
    digest.update(_CRITIQUE_PROMPT.encode("utf-8"))
    return digest.hexdigest()


def _bind_cache_run_context(cache: SqliteCacheAdapter) -> None:
    """Atomically bind the four versions used by every Phase 3 cache key."""
    cache.bind_run_context(
        model_versions=_composite_model_versions(),
        prompt_versions=_composite_prompt_versions(),
        schema_version=SCHEMA_VERSION,
        spectra_version=_SPECTRA_VERSION,
    )


# ── Pre-flight stage (Capability #6) ─────────────────────────


def _run_preflight_stage(
    workspace_dir: str,
    file_tree: list[str],
    observer: RichProgressReporter,
    *,
    honor_gitignore: bool,
    allow_secrets: bool,
) -> list[str]:
    """Filter the file tree, scan for secrets, and surface the result.

    Returns the filtered file list ready for downstream stages. Raises
    ``SecretDetectedError`` (SPEC-011) when secrets are detected and
    ``allow_secrets`` is False — the CLI catches that at the outer seam.

    ``--allow-secrets`` is intentionally noisy: every detection is
    rendered with severity-coloured text so the dev cannot miss it
    even when bypassing the gate.
    """
    observer.on_stage_start("PREFLIGHT", "Scanning for secrets")
    workspace_filter = PathspecFilterAdapter(honor_gitignore=honor_gitignore)
    secret_scanner = RegexSecretScanner()
    config = PreflightConfig(allow_secrets=allow_secrets)
    result = run_preflight(workspace_dir, file_tree, workspace_filter, secret_scanner, config)
    msg = _preflight_summary(file_tree, result.filtered_files, result.secret_findings)
    observer.on_stage_complete("PREFLIGHT", msg)
    if result.secret_findings:
        _log_allowed_secrets(result.secret_findings)
    return result.filtered_files


def _preflight_summary(
    original: list[str],
    filtered: list[str],
    findings: tuple[object, ...],
) -> str:
    """Compose the brand-voice ≤80-char success line for the PREFLIGHT stage."""
    excluded = len(original) - len(filtered)
    if findings:
        return f"{excluded} files excluded, {len(findings)} secrets detected (allowed)"
    return f"{excluded} files excluded, no secrets detected"


def _log_allowed_secrets(findings: tuple[object, ...]) -> None:
    """Emit a WARN log per allowed-secret finding so dev cannot miss them."""
    log = logging.getLogger("spectra.preflight")
    for finding in findings:
        log.warning(
            "SPEC-011 (allowed via --allow-secrets): %s:%s pattern=%s",
            getattr(finding, "file_path", "?"),
            getattr(finding, "line", "?"),
            getattr(finding, "pattern_name", "?"),
        )


# ── Workspace helpers ────────────────────────────────────────


def _allocate_workspace(source: str) -> tuple[str, bool]:
    """Return (workspace_dir, owns_workspace) for ``source``.

    For local sources we use an empty placeholder string — ``GitPort.prepare_workspace``
    will substitute the absolute path of the user's repo. The composition root MUST
    not delete that directory; ``owns_workspace`` is False.

    For URL sources we mint a private 0o700 tempdir, clone into it, and the
    composition root cleans it up afterwards.
    """
    if is_local_path(source):
        return "", False
    workspace = tempfile.mkdtemp(prefix="spectra-")
    os.chmod(workspace, 0o700)
    return workspace, True


def _derive_repo_name(source: str, workspace_dir: str) -> str:
    """Pick a friendly repo name from either the URL or the workspace dir."""
    if is_local_path(source):
        return Path(workspace_dir).name or "repo"
    return source.rstrip("/").split("/")[-1].removesuffix(".git")


# ── Heuristic source file reader ─────────────────────────────

_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".js",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
    }
)
_ENTRY_STEMS = frozenset(
    {
        "main",
        "app",
        "index",
        "server",
        "cli",
        "__main__",
    }
)
_CONFIG_NAMES = frozenset(
    {
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
    }
)
_SOURCE_PREFIXES = ("src/", "lib/", "app/", "pkg/", "cmd/")
_MAX_HEURISTIC_FILES = 20
_MAX_HEURISTIC_TOKENS = 100_000


async def _read_key_source_files(
    git_port: GitAdapter,
    clone_dir: str,
    file_tree: list[str],
) -> dict[str, str]:
    """Read up to 20 key source files by heuristic, capped at 100K tokens."""
    counter = TiktokenAdapter()
    ranked = _prioritize_source_files(file_tree)
    result: dict[str, str] = {}
    total_tokens = 0
    for path in ranked[:_MAX_HEURISTIC_FILES]:
        try:
            content = await git_port.read_file(clone_dir, path)
            tokens = counter.count(content)
        except Exception:  # noqa: S112
            continue
        if total_tokens + tokens > _MAX_HEURISTIC_TOKENS:
            break
        result[path] = content
        total_tokens += tokens
    return result


def _prioritize_source_files(file_tree: list[str]) -> list[str]:
    """Rank files: entry points > config > src/ source > other source."""
    tiers: tuple[list[str], ...] = ([], [], [], [])
    for path in file_tree:
        p = Path(path)
        if p.stem in _ENTRY_STEMS and p.suffix in _SOURCE_EXTENSIONS:
            tiers[0].append(path)
        elif p.name in _CONFIG_NAMES:
            tiers[1].append(path)
        elif any(path.startswith(d) for d in _SOURCE_PREFIXES) and p.suffix in _SOURCE_EXTENSIONS:
            tiers[2].append(path)
        elif p.suffix in _SOURCE_EXTENSIONS:
            tiers[3].append(path)
    return [f for tier in tiers for f in tier]


_SARIF_SEVERITY: dict[str, str] = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}


def build_json_payload(report: AnalysisReport) -> dict[str, object]:
    """Build the JSON output payload with the indicative-analysis disclaimer.

    The disclaimer is a top-level data field so SAST consumers and
    machine pipelines see it natively. It is always present and cannot
    be dismissed (UI dismissal is HTML-only).

    Args:
        report: Completed analysis report.

    Returns:
        Dict ready for ``json.dumps`` — disclaimer first, then report fields.
    """
    return {
        "disclaimer": disclaimer_payload(),
        **report.model_dump(mode="json"),
    }


def _sarif_disclaimer_notification() -> dict[str, object]:
    """SARIF ``notification`` carrying the indicative-analysis disclaimer.

    Uses level=``note`` and a ``descriptor.helpUri`` that points at the
    docs anchor — the standard SARIF mechanism for surfacing tool-level
    advisories to consumers.
    """
    payload = disclaimer_payload()
    return {
        "level": "note",
        "message": {"text": payload["text"]},
        "descriptor": {
            "id": "spectra/disclaimer/indicative-analysis",
            "name": "IndicativeAnalysis",
            "shortDescription": {"text": "Indicative analysis — not auditor-grade evidence."},
            "helpUri": payload["url"],
        },
    }


def _build_sarif(report: AnalysisReport) -> dict:
    """Build SARIF v2.1.0 output for GitHub Security tab integration.

    Args:
        report: Completed analysis report.

    Returns:
        SARIF-compliant dictionary ready for JSON serialization.
    """
    results = [
        {
            "ruleId": f"spectra/{f.dimension}/{f.id}",
            "level": _SARIF_SEVERITY.get(f.severity, "note"),
            "message": {"text": f"{f.title}: {f.description}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.location.file_path},
                        "region": {"startLine": max(1, f.location.line_start)},
                    },
                }
            ],
            "properties": {
                "severity": f.severity,
                "dimension": f.dimension,
                "recommendation": f.recommendation,
                "estimatedHours": f.estimated_hours,
            },
        }
        for f in report.findings
    ]

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Spectra",
                        "version": _SPECTRA_VERSION,
                        "informationUri": "https://github.com/leocder07/spectra",
                        "rules": [],
                    },
                },
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "notifications": [_sarif_disclaimer_notification()],
                    }
                ],
                "results": results,
            }
        ],
    }


def cli() -> None:
    """Package entry point — wires DI then starts CLI.

    This is the ``[project.scripts]`` entry point. It injects the
    analyzer factory and the cache provider into the CLI controller
    before starting Typer. The cache provider serves the lightweight
    ``spectra cache *`` subcommands without spinning up the LLM stack.
    """
    set_analyzer_factory(_run_analysis)
    set_cache_provider(_provision_cache_only)
    cli_entry()
