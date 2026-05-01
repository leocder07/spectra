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

ADR references in this module: ADR-001 (clean architecture composition
root), ADR-012 (cache HMAC + per-user namespace + legacy migration),
ADR-013 (cost tracker), ADR-018 (audit log + identity + receipt wiring).
See ``docs/architecture/adr/`` and ``docs/glossary.md`` for the
at-a-glance ADR index.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from hashlib import blake2b
from pathlib import Path
from typing import TYPE_CHECKING

from spectra import __version__ as _SPECTRA_VERSION  # noqa: N812
from spectra.adapters.cli_controller import (
    cli_entry,
    set_analyzer_factory,
    set_cache_provider,
    set_history_migrator,
    set_history_store_provider,
    set_portfolio_analyzer,
    set_portfolio_registry_provider,
    set_shred_executor,
    set_verifier,
)
from spectra.adapters.progress_reporter import RichProgressReporter
from spectra.entities.audit import new_event_id
from spectra.entities.disclaimer import disclaimer_payload
from spectra.entities.enums import AgentRole
from spectra.entities.errors import ERRORS, AgentError, PolicyGateError, SpectraError
from spectra.entities.models import (
    AgentRunConfig,
    AnalysisReport,
    AnalysisRequest,
    CacheSecret,
    Codebase,
    RepoCacheKey,
    Waiver,
)
from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.infrastructure.agents.critique_agent import _SYSTEM_PROMPT as _CRITIQUE_PROMPT
from spectra.infrastructure.agents.specialist_prompts import (
    _SHARED_GUIDANCE,
    SPECIALIST_CONFIGS,
)
from spectra.infrastructure.anthropic_adapter import AnthropicAdapter
from spectra.infrastructure.audit_wiring import (
    KeyringReceiptKeyStore,
    build_audit_adapter,
    default_audit_sink_spec,
    default_receipt_public_key_path,
)
from spectra.infrastructure.cache_adapter import (
    SCHEMA_VERSION,
    SqliteCacheAdapter,
    default_cache_path,
    migrate_legacy_cache,
    shred_cache_file,
)
from spectra.infrastructure.cost_tracker import (
    InMemoryCostTracker,
    SqliteCostTracker,
)
from spectra.infrastructure.git_adapter import GitAdapter
from spectra.infrastructure.keyring_adapter import KeyringSecretAdapter
from spectra.infrastructure.logging_decorator import LoggingDecorator
from spectra.infrastructure.observability import OtelTracerAdapter
from spectra.infrastructure.pathspec_filter_adapter import PathspecFilterAdapter
from spectra.infrastructure.receipt_signer import ReceiptSigner
from spectra.infrastructure.redis_cache_adapter import RedisCacheAdapter
from spectra.infrastructure.regex_secret_scanner import RegexSecretScanner
from spectra.infrastructure.report_adapter import ReportAdapter
from spectra.infrastructure.retry_decorator import RetryDecorator
from spectra.infrastructure.tiered_cache_adapter import TieredCacheAdapter
from spectra.infrastructure.tiktoken_adapter import TiktokenAdapter
from spectra.infrastructure.yaml_policy_adapter import YamlPolicyAdapter
from spectra.infrastructure.yaml_waiver_adapter import YamlWaiverAdapter
from spectra.use_cases.analyze_repository import PipelineContext, analyze_repository
from spectra.use_cases.identity_resolver import resolve_actor
from spectra.use_cases.interfaces import TracerPort, is_local_path
from spectra.use_cases.preflight import PreflightConfig, run_preflight
from spectra.use_cases.resolve_agent_configs import resolve_agent_configs
from spectra.use_cases.source_file_selection import (
    MAX_HEURISTIC_FILES,
    MAX_HEURISTIC_TOKENS,
    prioritize_source_files,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from spectra.use_cases.interfaces import AuditPort, CachePort, LLMGateway
    from spectra.use_cases.orchestrate_agents import AnalysisAgent

# CLI flag default — when --otel-endpoint is omitted, no tracer is wired
# (NoopTracerAdapter via PipelineContext default). This keeps the install
# overhead at zero for users who never enable observability.
_DEFAULT_TEAM = "default"


class ReportError(Exception):
    """Raised when report rendering fails (SPEC-009).

    Attributes:
        error: The underlying ``SpectraError`` with code and message.
    """

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


def _build_agents(
    gateway: LLMGateway,
    configs: dict[AgentRole, AgentRunConfig],
    *,
    skip_critique: bool,
) -> tuple[AnalysisAgent, list[AnalysisAgent], AnalysisAgent | None]:
    """Build all 8 agents from a fully resolved per-role config map.

    The ``gateway`` argument is typed against the use-case ``LLMGateway``
    Protocol (Layer 2), preserving the dependency rule via the
    ``TYPE_CHECKING`` import — no runtime cycle, no ``object`` fallback.
    Likewise the returned agents satisfy ``AnalysisAgent`` (the Protocol
    used by the orchestrator) so the seam is type-checked end-to-end.

    The ``configs`` map is the single source of truth for per-agent model +
    effort: the same map is bound onto ``RichProgressReporter`` so the
    terminal display reads the live config (no static ``AGENT_MODELS``
    dict that drifts whenever defaults change — see
    ``docs/architecture/INDEX.md#ADR-013``).

    Returns:
        ``(meta_prompter, specialists, critique_agent)``. ``critique_agent``
        is ``None`` when ``skip_critique`` is True.
    """
    factory = AgentFactory(gateway=gateway, configs=configs)
    meta: AnalysisAgent = factory.create("meta_prompter")
    specialists: list[AnalysisAgent] = list(factory.create_specialists())
    critique: AnalysisAgent | None = None if skip_critique else factory.create("critique")
    return (meta, specialists, critique)


@dataclass(frozen=True)
class _DepBundle:
    """Frozen DI bundle: gateway + observer + adapter handle for cleanup.

    The composition root assembles this once via ``_wire_dependencies``
    so the orchestrator never re-builds the decorator chain mid-run.
    ``adapter`` is held separately from ``gateway`` because the outermost
    cleanup needs the raw client to call ``close()`` on the connection
    pool — ``LoggingDecorator`` does not expose it.
    """

    observer: RichProgressReporter
    adapter: AnthropicAdapter
    gateway: LLMGateway


def _wire_dependencies(api_key: str) -> _DepBundle:
    """Build the LLM decorator chain and bundle it with the observer.

    Decorator chain (innermost → outermost):
        AnthropicAdapter (raw API)
        → RetryDecorator     (exponential backoff 1s/2s/4s, max 3)
        → LoggingDecorator   (call logging + timing)

    Each layer satisfies the ``LLMGateway`` protocol via structural
    subtyping, so the orchestrator only ever sees the outermost ``gateway``.
    The raw ``adapter`` is exposed on the bundle so the caller can release
    its httpx connection pool in the ``finally`` block.
    """
    observer = RichProgressReporter()
    adapter = AnthropicAdapter(api_key=api_key)
    retry = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
    gateway = LoggingDecorator(retry, observer=observer)
    return _DepBundle(observer=observer, adapter=adapter, gateway=gateway)


def _assemble_context(
    *,
    deps: _DepBundle,
    request: AnalysisRequest,
    codebase: Codebase,
    git: GitAdapter,
    cache: _CACHE_BACKEND | None,
    source_files: dict[str, str],
    agent_overrides: dict[str, object] | None,
    skip_critique: bool,
    force: bool,
    audit_sink: str | None,
    workspace_dir: str,
    max_cost_per_hour: float | None,
    max_cost_usd: float | None,
    run_id: str,
    tracer: TracerPort | None,
    team: str,
    rate_coordinator: object | None = None,
    notifier: object | None = None,
    drift_alert_enabled: bool = True,
    report_url: str | None = None,
) -> PipelineContext:
    """Bundle every input the use-case pipeline needs into a single ctx.

    Reads-and-resolves are concentrated here so ``_run_analysis`` only
    orchestrates the ordered sequence of phases. Side effects:
        - Creates the 8 agents via ``AgentFactory``.
        - Resolves the audit port (degraded ``None`` on sink failure).
        - Resolves the actor identity (git ⊕ env).
        - Loads + verifies signed waivers from the workspace root.
        - Builds the cost tracker (in-memory or SQLite per max-cost flags).
    """
    # Resolve per-role configs once and bind them onto the observer so
    # the terminal display reads the live model + effort (no static
    # AGENT_MODELS dict that drifts whenever defaults change).
    agent_configs = resolve_agent_configs(agent_overrides or {})
    deps.observer.set_agent_configs(agent_configs)
    meta_prompter, specialists, critique_agent = _build_agents(deps.gateway, agent_configs, skip_critique=skip_critique)
    audit_port = _build_audit_port(audit_sink)
    actor = resolve_actor()
    active_waivers, expired_waivers = _load_waivers(workspace_dir)
    cost_tracker = _build_cost_tracker(max_cost_per_hour)
    report_store = _provision_history_store_safe()
    return PipelineContext(
        request=request,
        codebase=codebase,
        meta_prompter=meta_prompter,
        specialists=specialists,
        critique_agent=critique_agent,
        git_port=git,
        observer=deps.observer,
        source_files=source_files,
        cache_port=_as_cache_port(cache),
        cache_key_factory=_make_cache_key_factory() if cache else None,
        force_cache_bypass=force,
        audit_port=audit_port,
        actor=actor,
        spectra_version=_SPECTRA_VERSION,
        run_id=run_id,
        waivers=active_waivers,
        expired_waivers=expired_waivers,
        cost_tracker=cost_tracker,
        max_cost_usd=max_cost_usd,
        report_store=report_store,  # type: ignore[arg-type]
        tracer=tracer,
        team=team,
        rate_coordinator=rate_coordinator,  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        drift_alert_enabled=drift_alert_enabled,
        report_url=report_url,
    )


def _provision_history_store_safe() -> object | None:
    """Build a history store for the pipeline; return None on any failure.

    History persistence is a side benefit, not a hard requirement: a
    misconfigured Postgres URL or a locked sqlite directory must not
    abort the analyze run.
    """
    try:
        return _provision_history_store()
    except Exception as exc:
        logging.getLogger("spectra.history").debug(
            "History store unavailable for this run: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None


async def _run_and_stamp(
    ctx: PipelineContext,
    classification: str,
    run_id: str,
) -> AnalysisReport:
    """Run the use-case pipeline, attach the receipt, and stamp classification.

    All three are post-pipeline transformations the use case must NOT
    own — receipts are signed in infrastructure, classification is a
    composition-root flag. Returns the final report ready for the policy
    gate and report-render stage.
    """
    report = await analyze_repository(ctx)
    report = _attach_receipt(report, run_id)
    # Capability #56 — stamp the chosen classification onto the frozen
    # report so every render path (HTML / JSON / SARIF) reads one field.
    if report.classification != classification:
        report = report.model_copy(update={"classification": classification})
    return report


async def _ingest_workspace(
    git: GitAdapter,
    observer: RichProgressReporter,
    repo_url: str,
    workspace_dir: str,
    *,
    owns_workspace: bool,
    honor_gitignore: bool,
    allow_secrets: bool,
) -> tuple[str, list[str], dict[str, str]]:
    """Stage 1 (INGEST) + Stage 1.5 (PREFLIGHT) + heuristic source-file read.

    Returns ``(workspace_dir, file_tree, source_files)`` ready for the
    use-case pipeline. ``workspace_dir`` may be rewritten by
    ``GitPort.prepare_workspace`` (local-path resolution).
    """
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
    source_files = await _read_key_source_files(git, workspace_dir, file_tree)
    return workspace_dir, file_tree, source_files


def _render_report(
    report: AnalysisReport,
    output_path: str,
    output_format: str,
    report_renderer: ReportAdapter,
    observer: RichProgressReporter,
) -> None:
    """Stage 6 (REPORT) — write to disk in the requested format.

    Re-raises any failure as ``ReportError`` (SPEC-009) with the original
    exception chained, so the CLI seam can surface a brand-voice message.
    """
    observer.on_stage_start("REPORT", "Rendering report")
    try:
        if output_format == "json":
            data = json.dumps(build_json_payload(report), indent=2)
            Path(output_path).write_text(data, encoding="utf-8")
        elif output_format == "sarif":
            sarif = _build_sarif(report)
            Path(output_path).write_text(json.dumps(sarif, indent=2), encoding="utf-8")
        else:
            report_renderer.render(report, output_path)
    except Exception as exc:
        logging.getLogger("spectra").error("Report render failed: %s", exc)
        raise ReportError(ERRORS["SPEC-009"]) from exc
    observer.on_stage_complete("REPORT", "Report generated")


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
    audit_sink: str | None = None,
    classification: str = "confidential",
    max_cost_usd: float | None = None,
    max_cost_per_hour: float | None = None,
    cache_remote: str | None = None,
    otel_endpoint: str | None = None,
    team: str = _DEFAULT_TEAM,
    rate_limit_rpm: int | None = None,
    rate_coordinator_url: str | None = None,
    notify_webhook: str | None = None,
    no_drift_alert: bool = False,
) -> AnalysisReport:
    """Run the full pipeline: clone, plan, analyze, critique, report.

    Composition-root orchestrator. Decomposed into helpers so the
    function body stays small and every concern (DI wiring, ctx
    assembly, run+stamp, render) reads as a single line.

    Args:
        repo_url: Git HTTPS URL or local path to analyze.
        output_path: File path for the rendered report.
        skip_critique: Skip CritiqueAgent when True.
        output_format: ``"html"``, ``"json"``, or ``"sarif"``.
        verbose: Enable debug logging when True (CLI-set, no body usage).
        force: Bypass cache reads and force a fresh run (still writes the cache).
        no_cache: Disable cache reads and writes entirely (CI-safe).
        agent_overrides: Per-agent model/effort overrides from the CLI.
        honor_gitignore: Honor ``.gitignore`` during pre-flight (default True).
        allow_secrets: Bypass SPEC-011 on secret detection (default False).
        audit_sink: Audit sink spec (``stdout``, ``file:<path>``, ``otlp:<url>``).
        classification: Report classification to stamp (``confidential``/``public``).
        max_cost_usd: Per-run USD cap.
        max_cost_per_hour: Rolling-hour USD cap (forces SqliteCostTracker).
        cache_remote: Optional ``redis://...`` URL for the L2 distributed
            cache (#21, ADR-021). When set, the local SQLite cache is
            wrapped in a ``TieredCacheAdapter`` with ``RedisCacheAdapter``
            as the L2. Falls back to ``SPECTRA_CACHE_REDIS`` env var, then
            local-only when neither is set.
        otel_endpoint: OTLP/HTTP endpoint. ``None`` (default) disables
            tracing; otherwise wires :class:`OtelTracerAdapter` so every
            stage and per-agent span is exported (#30, ADR-023).
        team: Team tag stamped on every span for cost attribution
            (#33, ADR-023 §4). Defaults to ``"default"``.
        rate_limit_rpm: Optional fleet RPM cap (#22, ADR-013). ``None``
            disables rate coordination — the orchestrator still relies
            on its in-process semaphore. When set, every Anthropic call
            awaits one token from the coordinator first.
        rate_coordinator_url: Coordinator backend selector. ``None`` or
            ``"inmemory"`` picks ``InMemoryRateAdapter`` (per-process).
            ``redis://...`` picks ``RedisRateAdapter`` (fleet-wide).
            Ignored when ``rate_limit_rpm`` is unset.
        notify_webhook: Slack/Teams incoming-webhook URL for drift +
            per-finding alerts (#27 + #34). Auto-detected by host
            substring (``hooks.slack.com`` vs ``webhook.office.com``).
            ``None`` (default) disables outbound notifications.
        no_drift_alert: When True, suppress automatic post-scan drift
            firing for this run. Per-finding critical alerts are still
            sent if a notifier is wired.

    Returns:
        Completed analysis report.

    Raises:
        RuntimeError: If ``ANTHROPIC_API_KEY`` is not set.
        ReportError: If report rendering fails (SPEC-009).
        SecretDetectedError: SPEC-011 when secrets are detected and
            ``allow_secrets`` is False.
        PolicyGateError: SPEC-013 when the policy gate rejects the report.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        msg = "ANTHROPIC_API_KEY environment variable is required"
        raise RuntimeError(msg)

    deps = _wire_dependencies(api_key)
    git = GitAdapter()
    report_renderer = ReportAdapter()
    cache = _provision_cache(no_cache=no_cache, cache_remote=cache_remote)
    tracer = _build_tracer(otel_endpoint, team)
    rate_coordinator = _build_rate_coordinator(rate_limit_rpm, rate_coordinator_url)
    notifier = _build_notifier_safe(notify_webhook)
    workspace_dir, owns_workspace = _allocate_workspace(repo_url)
    try:
        workspace_dir, file_tree, source_files = await _ingest_workspace(
            git,
            deps.observer,
            repo_url,
            workspace_dir,
            owns_workspace=owns_workspace,
            honor_gitignore=honor_gitignore,
            allow_secrets=allow_secrets,
        )
        codebase = Codebase(
            repo_url=repo_url,
            repo_name=_derive_repo_name(repo_url, workspace_dir),
            local_path=workspace_dir,
            file_tree=tuple(file_tree),
        )
        request = AnalysisRequest(repo_url=repo_url, quick=skip_critique, output_format=output_format)
        run_id = new_event_id()
        ctx = _assemble_context(
            deps=deps,
            request=request,
            codebase=codebase,
            git=git,
            cache=cache,
            source_files=source_files,
            agent_overrides=agent_overrides,
            skip_critique=skip_critique,
            force=force,
            audit_sink=audit_sink,
            workspace_dir=workspace_dir,
            max_cost_per_hour=max_cost_per_hour,
            max_cost_usd=max_cost_usd,
            run_id=run_id,
            tracer=tracer,
            team=team,
            rate_coordinator=rate_coordinator,
            notifier=notifier,
            drift_alert_enabled=not no_drift_alert,
            report_url=output_path,
        )
        report = await _run_and_stamp(ctx, classification, run_id)
        _enforce_policy(workspace_dir, report)
        _render_report(report, output_path, output_format, report_renderer, deps.observer)
        return report
    finally:
        if owns_workspace:
            # Offload to a worker thread — on big repos the rmtree walk
            # can take >100 ms and would otherwise block the event loop
            # at the very end of the pipeline (no other awaitable runs
            # during the synchronous walk).
            await asyncio.to_thread(shutil.rmtree, workspace_dir, ignore_errors=True)
        await deps.adapter.close()
        _close_cache_quietly(cache)


# ── Policy + waiver loading (Capabilities #17 + #18) ─────────


_POLICY_FILENAME = ".spectra-policy.yml"
_WAIVERS_FILENAME = ".spectra-waivers.yml"
_APPROVERS_FILENAME = ".spectra-approvers.yml"


def _load_waivers(workspace_dir: str) -> tuple[tuple[Waiver, ...], tuple[Waiver, ...]]:
    """Load + verify ``.spectra-waivers.yml`` from the workspace root.

    Returns ``((), ())`` for repos without a waivers file. Verification
    failures are logged + dropped by ``YamlWaiverAdapter``; never fatal.
    """
    waivers_path = Path(workspace_dir) / _WAIVERS_FILENAME
    approvers_path = Path(workspace_dir) / _APPROVERS_FILENAME
    return YamlWaiverAdapter().load(waivers_path, approvers_path)


def _enforce_policy(workspace_dir: str, report: AnalysisReport) -> None:
    """Run the SPEC-013 policy gate against ``report``.

    Loads ``.spectra-policy.yml`` (EmptyPolicy when absent) and raises
    ``PolicyGateError`` if any check returns a violation. The gate runs
    even with ``--quick``: governance is not a function of how many agents
    we ran.
    """
    policy_path = Path(workspace_dir) / _POLICY_FILENAME
    adapter = YamlPolicyAdapter()
    policy = adapter.load(policy_path)
    violations = adapter.evaluate(policy, report)
    if violations:
        raise PolicyGateError(violations)


# ── Tracer adapter construction (ADR-023) ────────────────────


def _build_notifier_safe(webhook_url: str | None) -> object | None:
    """Wire a Slack/Teams notifier when ``webhook_url`` is configured.

    Returns ``None`` (notifications disabled) when:
        - ``webhook_url`` is not supplied (the default);
        - the URL host is neither Slack nor Teams (logged + skipped, the
          analyze run still completes — alerts are best-effort).
    """
    if not webhook_url:
        return None
    from spectra.infrastructure.notifiers import notifier_from_url

    try:
        return notifier_from_url(webhook_url)
    except ValueError as exc:
        logging.getLogger("spectra.notifiers").warning(
            "Notifier disabled — unrecognised webhook URL: %s",
            exc,
        )
        return None


def _build_tracer(endpoint: str | None, team: str) -> TracerPort | None:
    """Wire :class:`OtelTracerAdapter` when ``endpoint`` is configured.

    Returns ``None`` (the PipelineContext default — equivalent to a
    NoopTracerAdapter via ``safe_span``) when:
        - ``endpoint`` is not supplied (the 70% case);
        - the OTel SDK fails to initialise the exporter (degrade,
          never abort — same posture as audit / receipt failures).

    Args:
        endpoint: OTLP/HTTP collector URL.
        team: Cost-attribution tag, copied onto the OTel ``Resource``
            so it surfaces on every exported span.

    Returns:
        An ``OtelTracerAdapter`` or ``None``. ``None`` keeps the
        composition root identical to pre-#30 behaviour.
    """
    if not endpoint:
        return None
    try:
        return OtelTracerAdapter(
            endpoint=endpoint,
            resource_attributes={
                "spectra.team": team,
                "spectra.version": _SPECTRA_VERSION,
            },
        )
    except (OSError, ValueError, ImportError) as exc:
        logging.getLogger("spectra.tracing").warning(
            "Tracing disabled — OTel adapter init failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None


# ── Rate coordinator construction (#22, ADR-013) ─────────────


def _build_rate_coordinator(
    rate_limit_rpm: int | None,
    coordinator_url: str | None,
) -> object | None:
    """Wire the rate-coordinator adapter from the CLI flag pair (#22, ADR-013).

    Selection rules:
        - ``rate_limit_rpm is None``     → no coordinator (fast path).
        - ``coordinator_url`` starts with ``redis://`` → ``RedisRateAdapter``.
        - Anything else (or unset)       → ``InMemoryRateAdapter``.

    Returns ``None`` when no rate cap is configured so the orchestrator
    short-circuits ``_gate_rate`` entirely. A misconfigured Redis URL
    (auth failure, DNS) does NOT abort here — the adapter degrades to
    its in-process fallback at first ``acquire`` (SPEC-010).

    Args:
        rate_limit_rpm: Per-fleet RPM ceiling. ``None`` disables.
        coordinator_url: ``redis://...`` for fleet mode, ``inmemory``
            (or ``None``) for solo mode.

    Returns:
        A ``RateCoordinatorPort``-shaped adapter, or ``None``.
    """
    if rate_limit_rpm is None:
        return None
    if coordinator_url and coordinator_url.startswith("redis://"):
        return _build_redis_rate_coordinator(rate_limit_rpm, coordinator_url)
    from spectra.infrastructure.inmemory_rate_adapter import InMemoryRateAdapter

    return InMemoryRateAdapter(rate_per_minute=rate_limit_rpm)


def _build_redis_rate_coordinator(rate_limit_rpm: int, url: str) -> object:
    """Construct a ``RedisRateAdapter``; degrade to in-process on init failure.

    Live Redis I/O happens on first ``acquire``, not at construction —
    this only fails when redis-py itself cannot parse the URL. We catch
    those config bugs and downgrade to InMemoryRateAdapter so the
    pipeline never aborts on a typo in the connection string.
    """
    from spectra.infrastructure.inmemory_rate_adapter import InMemoryRateAdapter
    from spectra.infrastructure.redis_rate_adapter import RedisRateAdapter

    try:
        return RedisRateAdapter.from_url(url, rate_per_minute=rate_limit_rpm)
    except (RuntimeError, OSError, ValueError) as exc:
        logging.getLogger("spectra.rate").warning(
            "Rate coordinator: Redis init failed (%s: %s); using in-process limit",
            type(exc).__name__,
            exc,
        )
        return InMemoryRateAdapter(rate_per_minute=rate_limit_rpm)


# ── Cache adapter construction ───────────────────────────────


_CACHE_BACKEND = SqliteCacheAdapter | TieredCacheAdapter
"""Type alias for the wired cache shape — local-only or tiered.

Both backends satisfy the *subset of* ``CachePort`` the orchestrator
calls: ``compute_repo_signature``, ``get/put_full_report``,
``get/put_batch_findings``, ``record_hit``, ``batch_key_for`` and
``bind_run_context``. The legacy Phase-1 ``get_findings`` /
``put_findings`` are dead in production paths and are therefore not
required of ``TieredCacheAdapter``.
"""


def _as_cache_port(cache: _CACHE_BACKEND | None) -> CachePort | None:
    """Cast the wired cache to ``CachePort`` for ``PipelineContext``.

    ``TieredCacheAdapter.get_findings`` is async (RemoteCachePort surface)
    while the legacy ``CachePort.get_findings`` is sync — Python cannot
    satisfy both Protocols on one class. The orchestrator has not used
    the legacy Phase-1 methods since the move to per-batch caching, so
    the structural mismatch is a paper cut, not a runtime hazard.
    """
    return cache  # type: ignore[return-value]  # see docstring


def _provision_cache(
    *,
    no_cache: bool,
    cache_remote: str | None = None,
) -> _CACHE_BACKEND | None:
    """Build the cache adapter (when enabled) and bind the Phase 3 run context.

    When ``cache_remote`` is set, the local SQLite adapter is wrapped in
    a ``TieredCacheAdapter`` with a ``RedisCacheAdapter`` as the L2 (#21,
    ADR-021). The L2 is opt-in — without the flag (or the
    ``SPECTRA_CACHE_REDIS`` env var) the wired cache is a bare local
    SqliteCacheAdapter, byte-for-byte identical to today's behaviour.
    """
    if no_cache:
        return None
    local = _build_cache_adapter()
    if local is None:
        return None
    cache = _build_cache_with_remote(
        remote_url=_resolve_cache_remote_url(cache_remote),
        local=local,
        secret=_resolve_cache_secret(),
    )
    _bind_cache_run_context(cache)
    return cache


def _resolve_cache_remote_url(arg: str | None) -> str | None:
    """Pick the L2 connection URL: explicit CLI arg beats env var.

    Returns ``None`` when neither is set — local-only mode (the default).
    """
    if arg:
        return arg
    env = os.environ.get("SPECTRA_CACHE_REDIS")
    return env if env else None


def _build_cache_with_remote(
    *,
    remote_url: str | None,
    local: SqliteCacheAdapter,
    secret: CacheSecret | None = None,
) -> _CACHE_BACKEND:
    """Wrap ``local`` in a ``TieredCacheAdapter`` when ``remote_url`` is set.

    Degrades to local-only when:
      * ``remote_url`` is ``None`` (no L2 requested), or
      * ``secret`` is ``None`` (no HMAC key — L2 cannot enforce ADR-012).

    The degradation is a one-line WARN (SPEC-010), never fatal.
    """
    if remote_url is None:
        return local
    if secret is None:
        logging.getLogger("spectra.cache").warning(
            "SPEC-010: cache HMAC secret unavailable; remote cache disabled, L1-only",
        )
        return local
    try:
        remote = RedisCacheAdapter.from_url(remote_url, secret=secret)
    except (RuntimeError, OSError, ValueError) as exc:
        logging.getLogger("spectra.cache").warning(
            "SPEC-010: remote cache disabled (%s: %s); L1-only for the rest of the run",
            type(exc).__name__,
            exc,
        )
        return local
    return TieredCacheAdapter(local=local, remote=remote)


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


def _shred_cache_and_keys() -> Path:
    """Roadmap #13 — overwrite cache.db + drop keyring entries.

    Returns the cache path that was shredded. Composes two destructive
    primitives (file shred + keyring entry deletion) so the CLI keeps
    a single ``shred_executor`` setter and never touches infrastructure.
    """
    db_path = default_cache_path()
    shred_cache_file(db_path, passes=3)
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None:
        try:
            KeyringSecretAdapter(uid=str(geteuid())).shred()
        except AgentError as exc:
            logging.getLogger("spectra").warning(
                "Cache keyring shred failed (%s); cache.db already removed",
                exc.error.code,
            )
    return db_path


def _build_cost_tracker(max_cost_per_hour: float | None) -> InMemoryCostTracker | SqliteCostTracker:
    """Pick the tracker flavour that satisfies the requested caps.

    SqliteCostTracker is required only when ``--max-cost-per-hour`` is
    set (the rolling window must survive process restarts). For per-run
    caps the in-memory ledger is sufficient and avoids a sqlite write
    per agent on the hot path.
    """
    if max_cost_per_hour is not None:
        run_id = os.urandom(8).hex()
        return SqliteCostTracker(db_path=default_cache_path(), run_id=run_id)
    return InMemoryCostTracker()


def _close_cache_quietly(cache: _CACHE_BACKEND | None) -> None:
    """Close the cache adapter, swallowing any SPEC-010 raised during close.

    For the tiered adapter the close-equivalent is just ``drain()``: the
    underlying SqliteCacheAdapter owns no socket and the RedisCacheAdapter
    closes its pool inside ``drain``'s task gather (each adapter is its
    own lifecycle). The local SqliteCacheAdapter is closed directly.
    """
    if cache is None:
        return
    try:
        if isinstance(cache, SqliteCacheAdapter):
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


@lru_cache(maxsize=1)
def _composite_model_versions() -> str:
    """Canonical sort of model IDs across all 8 agents.

    Memoized: the model IDs and ``SPECIALIST_CONFIGS`` are import-time
    constants, so the composition is deterministic for the lifetime of
    the process. Avoids repeating the sort + set-dedup on every cache
    bind / key-factory build.
    """
    models = sorted({cfg[3] for cfg in SPECIALIST_CONFIGS.values()})
    # Add MetaPrompter and Critique model IDs (both Opus 4.7 today; sort dedups).
    models.append("claude-opus-4-7")  # MetaPrompter
    models.append("claude-opus-4-7")  # CritiqueAgent
    return "|".join(sorted(set(models)))


@lru_cache(maxsize=1)
def _composite_prompt_versions() -> str:
    """blake2b digest of every prompt that affects analysis output.

    Memoized: the prompt strings are module-level constants. The digest
    is identical for every call within a process; cache it so repeated
    calls (composition root + ``_bind_cache_run_context`` + every
    ``_make_cache_key_factory`` invocation in a long-running daemon) do
    not re-hash the same bytes.
    """
    digest = blake2b(digest_size=16)
    digest.update(_SHARED_GUIDANCE.encode("utf-8"))
    for role in sorted(SPECIALIST_CONFIGS):
        digest.update(role.encode("utf-8"))
        digest.update(SPECIALIST_CONFIGS[role][2].encode("utf-8"))
    digest.update(_CRITIQUE_PROMPT.encode("utf-8"))
    return digest.hexdigest()


def _bind_cache_run_context(cache: _CACHE_BACKEND) -> None:
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
#
# The ranking heuristic itself lives in
# ``spectra.use_cases.source_file_selection`` because it is domain logic
# (which files carry the architecture / security / quality signal). The
# composition root only orchestrates the I/O loop around it.


async def _read_key_source_files(
    git_port: GitAdapter,
    clone_dir: str,
    file_tree: list[str],
) -> dict[str, str]:
    """Read up to ``MAX_HEURISTIC_FILES`` files by use-case ranking, token-capped.

    Reads run concurrently via ``asyncio.gather`` — the underlying
    ``GitPort.read_file`` already dispatches to a worker thread, so the
    speedup is the wall-clock overlap of the 20 thread calls (was a
    sequential ``await`` loop before v0.6.1). Priority order is preserved
    by zipping the ranked path list back over the gathered contents
    before we walk the per-token cap.

    Per-file failures we expect to encounter on real repos are skipped
    with a DEBUG log so the operator has a diagnostic trail without the
    pipeline aborting:
        - ``OSError`` / ``PermissionError`` — unreadable file on disk
        - ``UnicodeDecodeError`` — binary file slipped past the source-ext filter
        - ``ValueError`` — ``GitAdapter.read_file`` rejected the path
          (security check, size limit, traversal attempt)
        - ``TimeoutError`` — read exceeded the per-file deadline

    Anything else (programmer error, broken invariant) propagates so we
    don't silently mask bugs in the heuristic itself.
    """
    counter = TiktokenAdapter()
    ranked = prioritize_source_files(file_tree)[:MAX_HEURISTIC_FILES]
    contents = await _gather_source_reads(git_port, clone_dir, ranked)
    return _apply_token_cap(ranked, contents, counter)


async def _gather_source_reads(
    git_port: GitAdapter,
    clone_dir: str,
    paths: list[str],
) -> list[str | BaseException]:
    """Run every read concurrently; per-file errors are returned, not raised."""
    coros = [git_port.read_file(clone_dir, p) for p in paths]
    return await asyncio.gather(*coros, return_exceptions=True)


def _apply_token_cap(
    paths: list[str],
    contents: list[str | BaseException],
    counter: TiktokenAdapter,
) -> dict[str, str]:
    """Walk reads in priority order, dropping failures and stopping at the cap."""
    result: dict[str, str] = {}
    total_tokens = 0
    log = logging.getLogger("spectra.heuristic")
    for path, content in zip(paths, contents, strict=True):
        if isinstance(content, BaseException):
            if isinstance(content, (OSError, UnicodeDecodeError, ValueError, TimeoutError)):
                log.debug("Skipping %s during heuristic read: %s", path, content)
                continue
            raise content
        tokens = counter.count(content)
        if total_tokens + tokens > MAX_HEURISTIC_TOKENS:
            break
        result[path] = content
        total_tokens += tokens
    return result


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

    Capability #56 — when ``report.classification == "public"``, every
    individual finding and the cross-cutting insights are stripped from
    the payload before serialization. The score card, dimension counts,
    and scan metadata survive so consumers can still ingest aggregate
    metrics. Confidential mode keeps everything.

    Args:
        report: Completed analysis report.

    Returns:
        Dict ready for ``json.dumps`` — disclaimer first, then report fields.
    """
    body = report.model_dump(mode="json")
    if report.classification == "public":
        body = _redact_public_payload(body)
    return {
        "disclaimer": disclaimer_payload(),
        **body,
    }


def _redact_public_payload(body: dict[str, object]) -> dict[str, object]:
    """Drop individual findings + cross-cutting insights for public mode.

    Capability #56 §4 — public reports keep only aggregate signal:
    overall grade + per-dimension scores + counts + scan metadata. Every
    individual finding (titles, descriptions, file paths, code snippets,
    recommendations) is removed before serialization so a public report
    cannot be reverse-engineered into a vulnerability intel feed.
    """
    redacted = dict(body)
    redacted["findings"] = []
    redacted["cross_cutting_insights"] = []
    return redacted


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

    Capability #56 §7 — when ``report.classification == "public"`` the
    ``runs[0].results`` array is emptied (no findings shared in public
    mode) and the score summary surfaces under
    ``runs[0].properties.scoreCard``. Confidential SARIF is unchanged.

    Args:
        report: Completed analysis report.

    Returns:
        SARIF-compliant dictionary ready for JSON serialization.
    """
    is_public = report.classification == "public"
    results = [] if is_public else _sarif_results(report)
    run_properties = _sarif_run_properties(report)
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
                "properties": run_properties,
            }
        ],
    }


def _sarif_results(report: AnalysisReport) -> list[dict[str, object]]:
    """Map every finding to a SARIF result entry. Confidential mode only."""
    return [
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


def _sarif_run_properties(report: AnalysisReport) -> dict[str, object]:
    """Build the ``runs[0].properties`` block — classification + scoreCard.

    The score summary surfaces under ``properties.scoreCard`` so public
    reports still carry their grade for downstream ingestion (capability
    #56 §7) without exposing per-finding details.
    """
    score_card = {
        "overall_score": report.score_card.overall_score,
        "overall_grade": report.score_card.overall_grade,
        "total_findings": report.score_card.total_findings,
        "dimensions": [
            {
                "dimension": d.dimension,
                "score": d.score,
                "grade": d.grade,
                "weight": d.weight,
                "findings_count": d.findings_count,
            }
            for d in report.score_card.dimensions
        ],
    }
    return {
        "classification": report.classification,
        # Q2 #20: trust stamp surfaced in SARIF properties bag so GitHub
        # Code Scanning and other SAST consumers can tell whether the
        # adversarial CritiqueAgent check ran without parsing per-finding
        # metadata.
        "validation_status": report.validation_status,
        "scoreCard": score_card,
    }


# ── Audit + receipt wiring (ADR-018, #57) ────────────────────


def _receipt_degrade_exception_types() -> tuple[type[BaseException], ...]:
    """Return the exception classes that trigger silent receipt degradation.

    Pulled into a function so the keyring import stays lazy — the keyring
    package is an optional runtime dep and must not be required to import
    ``spectra.infrastructure.main``. ``keyring.errors.KeyringError`` is
    appended only when the import succeeds; on Windows / minimal images
    the import-time ``ImportError`` already handles the same scenarios.
    """
    from cryptography.exceptions import InvalidSignature

    base: tuple[type[BaseException], ...] = (
        OSError,
        ImportError,
        ValueError,
        TypeError,
        InvalidSignature,
    )
    try:
        import keyring.errors as _kr_errors
    except ImportError:
        return base
    return (*base, _kr_errors.KeyringError)


_RECEIPT_DEGRADE_EXCEPTIONS: tuple[type[BaseException], ...] = _receipt_degrade_exception_types()


def _build_audit_port(spec: str | None) -> AuditPort | None:
    """Construct the audit adapter from a sink spec; degrade to ``None``.

    Returns ``None`` when the spec is malformed or the sink cannot be
    opened — audit emission is best-effort and never fatal (ADR-018 §4).
    """
    sink = spec or default_audit_sink_spec()
    try:
        return build_audit_adapter(sink)
    except (ValueError, OSError) as exc:
        logging.getLogger("spectra.audit").warning("Audit disabled: failed to build sink %r: %s", sink, exc)
        return None


def _attach_receipt(report: AnalysisReport, run_id: str) -> AnalysisReport:
    """Sign ``report`` and embed the resulting receipt; degrade on failure.

    Catches the narrow set of failures the signer can realistically raise:

    - ``OSError`` — public-key file write or keyring socket failure
    - ``ImportError`` — optional ``keyring`` backend missing on this host
    - ``ValueError`` / ``TypeError`` — malformed key bytes (cryptography)
    - ``InvalidSignature`` — signature verification by the underlying
      cryptography stack (defensive; ``sign`` itself does not raise it)
    - ``keyring.errors.KeyringError`` — every keyring backend failure
      (NoKeyring, KeyringLocked, PasswordSetError, …)

    Anything else (``AttributeError``, ``RuntimeError``, etc.) signals a
    programmer bug and propagates so the operator sees the real cause
    instead of a silently missing receipt. Every swallowed exception is
    DEBUG-logged with ``run_id`` so the missing receipt can be correlated
    with the offending scan.
    """
    try:
        keystore = KeyringReceiptKeyStore(public_key_path=default_receipt_public_key_path())
        signer = ReceiptSigner(keystore=keystore)
        receipt = signer.sign(report, scan_id=run_id)
    except _RECEIPT_DEGRADE_EXCEPTIONS as exc:
        logging.getLogger("spectra.receipt").debug(
            "Receipt signing skipped for run_id=%s: %s: %s",
            run_id,
            type(exc).__name__,
            exc,
        )
        return report
    return report.model_copy(update={"receipt": receipt})


# ── #25 + ADR-022: history-store provisioning ──────────────


_HISTORY_BACKEND_ENV = "SPECTRA_HISTORY_BACKEND"
_HISTORY_POSTGRES_URL_ENV = "SPECTRA_POSTGRES_URL"


def _resolve_history_backend() -> str:
    """Pick the history backend from env vars; defaults to ``sqlite``."""
    explicit = os.environ.get(_HISTORY_BACKEND_ENV, "").strip().lower()
    if explicit:
        return explicit
    # If the user set a Postgres URL, infer they want the postgres backend
    # without needing the explicit toggle as well.
    if os.environ.get(_HISTORY_POSTGRES_URL_ENV, "").strip():
        return "postgres"
    return "sqlite"


def _provision_history_store() -> object:
    """Build the appropriate ``ReportStorePort`` for the wired backend.

    Returns a sqlite store by default; a Postgres store when the
    backend is set to ``postgres`` and ``SPECTRA_POSTGRES_URL`` is
    populated. Raises ``RuntimeError`` when Postgres is requested but no
    URL is provided — the CLI catches this and prints a brand-voice ✗.
    """
    from spectra.infrastructure.history import (
        PostgresReportStoreAdapter,
        SqliteReportStoreAdapter,
        apply_sqlite_migrations,
        build_pool,
        default_history_path,
    )

    backend = _resolve_history_backend()
    if backend == "postgres":
        url = os.environ.get(_HISTORY_POSTGRES_URL_ENV, "").strip()
        if not url:
            msg = "SPECTRA_POSTGRES_URL is required when --history-backend postgres"
            raise RuntimeError(msg)
        pool = build_pool(url)
        return PostgresReportStoreAdapter(pool=pool)
    # default: sqlite
    db_path = default_history_path()
    apply_sqlite_migrations(db_path)
    return SqliteReportStoreAdapter(db_path=db_path)


def _apply_history_migrations() -> tuple[str, ...]:
    """Apply pending migrations to the wired history backend.

    Returns the tuple of versions actually applied — empty when nothing
    was pending. Catches the missing-URL error so the CLI prints a clean
    SPEC-style message instead of a stack trace.
    """
    from spectra.infrastructure.history import (
        apply_postgres_migrations,
        apply_sqlite_migrations,
        build_pool,
        default_history_path,
    )

    backend = _resolve_history_backend()
    if backend == "postgres":
        url = os.environ.get(_HISTORY_POSTGRES_URL_ENV, "").strip()
        if not url:
            msg = "SPECTRA_POSTGRES_URL is required when --history-backend postgres"
            raise RuntimeError(msg)
        pool = build_pool(url)
        return apply_postgres_migrations(pool=pool)
    return apply_sqlite_migrations(default_history_path())


# ── #26: portfolio registry + analyzer provisioning ──────────


def _provision_portfolio_registry() -> object:
    """Build the SqliteRepoRegistry against the same ``cache.db`` path.

    The portfolio table lives on the cache file so a single backup +
    encryption story covers both subsystems. The cache adapter applies
    the table DDL on open; this factory only re-opens the same file
    through the registry-shaped API.
    """
    from spectra.infrastructure.history.sqlite_repo_registry import SqliteRepoRegistry

    return SqliteRepoRegistry(db_path=default_cache_path())


def _portfolio_analyzer(repo_url: str) -> object:
    """Adapt ``_run_analysis`` to the single-arg shape ``portfolio scan`` expects.

    Output filename is derived from the repo's last URL segment so
    multiple repos in one portfolio scan don't overwrite each other.
    Defaults match a typical portfolio overnight run: HTML output,
    confidential classification, full pipeline (no ``--quick``).
    """
    repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git") or "repo"
    output_path = f"spectra-{repo_name}.html"
    return _run_analysis(
        repo_url=repo_url,
        output_path=output_path,
        skip_critique=False,
        output_format="html",
        verbose=False,
        force=False,
        no_cache=False,
        agent_overrides=None,
    )


def cli() -> None:
    """Package entry point — wires DI then starts CLI.

    This is the ``[project.scripts]`` entry point. It injects the
    analyzer factory, the cache provider, the receipt verifier, and the
    Ed25519 signer (Fix R3-Arch-3) into their respective adapter seams
    before starting Typer. The cache provider and verifier serve the
    lightweight ``spectra cache *`` and ``spectra verify`` subcommands
    without spinning up the LLM stack.
    """
    from spectra.adapters.waiver_cli import set_signer
    from spectra.infrastructure.audit_wiring import default_receipt_public_key_path
    from spectra.infrastructure.ed25519_signer import Ed25519SignerAdapter
    from spectra.infrastructure.receipt_signer import verify_receipt

    set_analyzer_factory(_run_analysis)
    set_cache_provider(_provision_cache_only)
    set_shred_executor(_shred_cache_and_keys)
    set_verifier(verify_receipt, default_public_key_path=default_receipt_public_key_path())
    set_signer(Ed25519SignerAdapter())
    set_history_store_provider(_provision_history_store)
    set_history_migrator(_apply_history_migrations)
    set_portfolio_registry_provider(_provision_portfolio_registry)  # type: ignore[arg-type]
    set_portfolio_analyzer(_portfolio_analyzer)  # type: ignore[arg-type]
    cli_entry()
