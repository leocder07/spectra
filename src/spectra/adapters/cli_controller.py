"""Typer CLI controller for Spectra — Layer 3 adapter.

The CLI defines commands and options but does NOT wire dependencies.
The composition root (infrastructure/main.py) sets the analyzer
callable via `set_analyzer_factory()` before the CLI runs.

ADR references in this module: ADR-012 (cache HMAC + ``spectra cache
doctor``). See ``docs/architecture/adr/`` and ``docs/glossary.md`` for
the at-a-glance ADR index.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import re
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import typer
from rich.console import Console
from rich.table import Table

from spectra import __version__
from spectra.adapters.analysis_presenter import present_scorecard
from spectra.adapters.brand import AMBER, GREEN, RED, VIOLET
from spectra.adapters.pr_comment_renderer import render_pr_comment
from spectra.adapters.waiver_cli import approver_app, waive_command
from spectra.entities.enums import Severity
from spectra.entities.errors import (
    ERRORS,
    AgentError,
    BudgetExceededError,
    GitError,
    PolicyGateError,
    SecretDetectedError,
    SpectraRetryError,
)
from spectra.entities.models import AnalysisReport, CacheStats, RepoRegistryEntry, ReportSummary, Violation
from spectra.use_cases.interfaces import CachePort, NotifierPort, RepoRegistryPort, ReportStorePort, is_local_path
from spectra.use_cases.manage_portfolio import (
    PortfolioScanPlan,
    PortfolioScanRunMode,
    plan_portfolio_scan,
    select_run_mode,
)
from spectra.use_cases.resolve_agent_configs import resolve_agent_configs

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from spectra.entities.receipt import ScanReceipt as _ReceiptShape
else:
    _ReceiptShape = object  # type: ignore[misc, assignment]

app = typer.Typer(
    name="spectra",
    help="8 AI agents analyze your entire repository in under 5 minutes",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()

OutputFormat = Literal["html", "json"]

_MAX_URL_LENGTH = 2048
_URL_PATTERN = re.compile(
    r"^https://[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,}"  # scheme + host
    r"(/[^\s]*)?$"  # optional path
)


def _validate_repo_url(url: str) -> str | None:
    """Validate the repository URL and return an error message or None."""
    if not url or not url.strip():
        return "Repository URL cannot be empty"
    if len(url) > _MAX_URL_LENGTH:
        return f"URL exceeds {_MAX_URL_LENGTH} character limit"
    if not url.startswith("https://"):
        return "Only HTTPS repository URLs are supported"
    if not _URL_PATTERN.match(url):
        return "Invalid URL format — expected https://host/path"
    return None


def _validate_local_path(source: str) -> str | None:
    """Validate a local repository path and return an error message or None.

    Defensive checks: reject ``..`` segments, expand ``~``, require an
    existing directory containing a ``.git/`` subdirectory, and reject
    symlinked roots to avoid TOCTOU surprises.
    """
    raw = source[len("file://") :] if source.startswith("file://") else source
    if ".." in Path(raw).parts:
        return "Path traversal segments (..) are not allowed"
    expanded = Path(raw).expanduser()
    if expanded.is_symlink():
        return f"Symlinked path is not allowed: {source}"
    if not expanded.exists():
        return f"Path does not exist: {source}"
    if not expanded.is_dir():
        return f"Not a directory: {source}"
    if not (expanded / ".git").exists():
        return f"Not a git repository (missing .git/): {source}"
    return None


def _validate_repo_source(source: str) -> str | None:
    """Validate either a local path or an HTTPS URL based on the source shape."""
    if is_local_path(source):
        return _validate_local_path(source)
    return _validate_repo_url(source)


_CLASSIFICATION_SUFFIX: dict[str, str] = {
    "confidential": "confidential",
    "public": "public",
}


def _classification_filename(output_path: str, classification: str) -> str:
    """Suffix the output path with the classification mode (capability #56 §8).

    ``spectra-report.html`` becomes ``spectra-report-confidential.html`` /
    ``spectra-report-public.html`` so both modes can coexist on disk
    without overwriting each other. Idempotent — re-suffixing a path that
    already carries one of the two suffixes strips the old one first.
    """
    suffix = _CLASSIFICATION_SUFFIX.get(classification, classification)
    path = Path(output_path)
    stem = path.stem
    for known in _CLASSIFICATION_SUFFIX.values():
        if stem.endswith(f"-{known}"):
            stem = stem[: -(len(known) + 1)]
            break
    return str(path.with_name(f"{stem}-{suffix}{path.suffix}"))


def _derive_display_name(source: str) -> str:
    """Pick a friendly target name for the banner from a URL or local path."""
    if is_local_path(source):
        raw = source[len("file://") :] if source.startswith("file://") else source
        return Path(raw).expanduser().resolve().name or "repo"
    return source.rstrip("/").split("/")[-1].removesuffix(".git")


# ── Per-agent model + effort allowed values ──────────────────
# Validation lives in the entities layer (AgentRunConfig); we duplicate
# the friendly allowed-list here only to fail fast with helpful errors
# before booting the analyzer chain.
_ALLOWED_MODELS: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)
_ALLOWED_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
_ALLOWED_CLASSIFICATIONS: tuple[str, ...] = ("confidential", "public")
_PER_AGENT_ROLES: tuple[str, ...] = (
    "meta",
    "architecture",
    "security",
    "quality",
    "documentation",
    "dependency",
    "performance",
    "critique",
)
# CLI uses "meta" but the entity layer uses "meta_prompter" — alias at the seam.
_CLI_TO_ROLE: dict[str, str] = {"meta": "meta_prompter"}


def _model_help(role: str) -> str:
    """Return ``help=`` text for a per-role ``--<role>-model`` flag.

    Includes the allowed-model list so users can discover valid choices
    without consulting the README. Validated against ``_ALLOWED_MODELS``
    so help text and validator stay in lock-step.
    """
    allowed = ", ".join(_ALLOWED_MODELS)
    return f"Override {role} model. Allowed: {allowed}"


def _effort_help(role: str) -> str:
    """Return ``help=`` text for a per-role ``--<role>-effort`` flag.

    Includes the allowed-effort list and the Opus-tier constraint
    (``xhigh``/``max`` are only valid on Opus models). Validated against
    ``_ALLOWED_EFFORTS`` so help text and validator stay in lock-step.
    """
    allowed = ", ".join(_ALLOWED_EFFORTS)
    return f"Override {role} effort. Allowed: {allowed} (xhigh/max Opus-tier only)"


_ERROR_DOCS_BASE = "https://github.com/leocder07/spectra/blob/main/docs/error-codes.md"


def _docs_link(code: str) -> str:
    """Return the user-facing docs URL anchor for a SPEC code.

    Used in brand-voice ✗ messages so users can land on the section that
    explains the failure with one click. Anchor format follows GitHub's
    auto-slug rules (lowercase, hyphenated).
    """
    return f"{_ERROR_DOCS_BASE}#{code.lower()}"


_DEFAULT_OUTPUT = Path("spectra-report.html")
_OUTPUT_OPTION = typer.Option(
    _DEFAULT_OUTPUT,
    "--output",
    "-o",
    help="Report output path",
)
_KEY_OPTION = typer.Option(
    None,
    "--key",
    "-k",
    help="Path to the Ed25519 public-key PEM (defaults to ~/.config/spectra/receipt.pub)",
)

# Q2 #19: severity gate. Ordering — worst first — drives the at-or-above check.
_FAIL_ON_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}
_FAIL_ON_CHOICES: tuple[str, ...] = ("critical", "high", "medium", "low", "none")

# ASCII banner — hacker terminal aesthetic
_BANNER = """\
[bold #7C3AED]
  ╔═╗╔═╗╔═╗╔═╗╔╦╗╦═╗╔═╗
  ╚═╗╠═╝║╣ ║   ║ ╠╦╝╠═╣
  ╚═╝╩  ╚═╝╚═╝ ╩ ╩╚═╩ ╩[/]
[dim #a78bfa]  ░▒▓ the full spectrum of your codebase ▓▒░[/]
[dim #52525b]  8 agents · 6 dimensions · under 3 minutes[/]
"""

_PIPELINE_INFO = """\
[dim #52525b]  ┌─ pipeline ────────────────────────────────────────────┐[/]
[dim #52525b]  │[/] [#F59E0B]1[/] MetaPrompter    [dim]opus-4.7  medium effort     planner  [/] [dim #52525b]│[/]
[dim #52525b]  │[/] [#F59E0B]6[/] Specialists     [dim]opus-4.7  xhigh effort      parallel [/] [dim #52525b]│[/]
[dim #52525b]  │[/] [#F59E0B]1[/] CritiqueAgent   [dim]opus-4.7  adaptive thinking validates[/] [dim #52525b]│[/]
[dim #52525b]  │[/] [dim]    arch · sec · qual · doc · dep · perf            [/] [dim #52525b]│[/]
[dim #52525b]  └───────────────────────────────────────────────────────┘[/]\
"""

_SCAN_LINE = f"[{VIOLET}]{'─' * 50}[/]"

# Injected by the composition root before CLI runs
_analyzer_factory: Callable[..., Awaitable[object]] | None = None
_cache_provider: Callable[[], CachePort] | None = None
_shred_executor: Callable[[], Path] | None = None
_verifier: Callable[[_ReceiptShape, bytes | None], bool] | None = None
_default_public_key_path: Path | None = None
_history_store_provider: Callable[[], ReportStorePort] | None = None
_history_migrator: Callable[[], tuple[str, ...]] | None = None
_portfolio_registry_provider: Callable[[], RepoRegistryPort] | None = None
_portfolio_analyzer: Callable[[str], Awaitable[object]] | None = None


def set_analyzer_factory(
    factory: Callable[..., Awaitable[object]],
) -> None:
    """Inject the async analyzer callable from the composition root.

    Args:
        factory: Async function accepting repo_url, output_path, etc.
    """
    global _analyzer_factory  # noqa: PLW0603
    _analyzer_factory = factory


def set_verifier(
    verifier: Callable[[_ReceiptShape, bytes | None], bool],
    default_public_key_path: Path | None = None,
) -> None:
    """Inject the receipt verifier callable + default public-key path.

    The composition root passes ``verify_receipt`` from the receipt-signer
    infrastructure module so this CLI never imports cryptography directly.
    """
    global _verifier, _default_public_key_path  # noqa: PLW0603
    _verifier = verifier
    _default_public_key_path = default_public_key_path


def set_cache_provider(provider: Callable[[], CachePort]) -> None:
    """Inject the cache-port factory used by ``spectra cache *`` subcommands.

    The composition root passes a zero-arg callable that returns a fresh
    ``CachePort``. The CLI invokes it lazily so the LLM stack is never
    required when only manipulating the local cache.
    """
    global _cache_provider  # noqa: PLW0603
    _cache_provider = provider


def set_history_store_provider(provider: Callable[[], ReportStorePort] | None) -> None:
    """Inject the history-store factory used by ``spectra history latest|trend``.

    The composition root passes a zero-arg callable that returns a fresh
    ``ReportStorePort``. The CLI invokes it lazily so the LLM stack is
    never required when only querying scan history. Pass ``None`` to clear
    the provider (used by the test fixture).
    """
    global _history_store_provider  # noqa: PLW0603
    _history_store_provider = provider


def set_history_migrator(migrator: Callable[[], tuple[str, ...]] | None) -> None:
    """Inject the migration runner used by ``spectra history migrate``.

    The composition root passes a zero-arg callable that applies any
    pending SQL migrations and returns the version strings actually
    applied. Pass ``None`` to clear the migrator (used by the test fixture).
    """
    global _history_migrator  # noqa: PLW0603
    _history_migrator = migrator


def set_portfolio_registry_provider(provider: Callable[[], RepoRegistryPort] | None) -> None:
    """Inject the registry factory used by ``spectra portfolio *`` subcommands (#26).

    The composition root passes a zero-arg callable that returns a fresh
    ``RepoRegistryPort``. The CLI invokes it lazily so subcommands work
    without the LLM stack. Pass ``None`` to clear the provider (used by
    the test fixture).
    """
    global _portfolio_registry_provider  # noqa: PLW0603
    _portfolio_registry_provider = provider


def set_portfolio_analyzer(
    analyzer: Callable[[str], Awaitable[object]] | None,
) -> None:
    """Inject the per-repo analyzer used by ``spectra portfolio scan`` (#26).

    The composition root passes an ``async`` callable that accepts a
    repo URL and runs the same pipeline as ``spectra analyze``. Pass
    ``None`` to clear the analyzer (used by the test fixture).
    """
    global _portfolio_analyzer  # noqa: PLW0603
    _portfolio_analyzer = analyzer


def set_shred_executor(executor: Callable[[], Path]) -> None:
    """Inject the destructive shred callable used by ``spectra cache shred``.

    The composition root passes a zero-arg callable that overwrites + deletes
    the cache file AND drops the per-user keyring entries, then returns the
    path of the file it shredded. Lives behind a setter (instead of being
    plumbed through ``cache_provider``) so the CLI never imports
    infrastructure modules directly.
    """
    global _shred_executor  # noqa: PLW0603
    _shred_executor = executor


def _print_banner() -> None:
    """Print the hacker-style ASCII banner."""
    console.print(_BANNER)
    console.print(_SCAN_LINE)


def _print_run_header(
    repo_url: str,
    output_path: str,
    fmt: str,
    classification: str,
    *,
    quick: bool,
) -> None:
    """Render the per-run banner: target, mode, classification, output."""
    _print_banner()
    repo_name = _derive_display_name(repo_url)
    console.print(f"  [{AMBER}]target:[/] {repo_name}  [dim]({repo_url})[/]")
    mode_label = "quick scan [dim](no critique)[/]" if quick else "full analysis [dim](8 agents)[/]"
    console.print(f"  [{AMBER}]mode:[/]   {mode_label}")
    if classification == "public":
        cls_label = "public [dim](redacted summary)[/]"
    else:
        cls_label = "confidential [dim](full findings)[/]"
    console.print(f"  [{AMBER}]class:[/]  {cls_label}")
    console.print(f"  [{AMBER}]output:[/] {output_path}  [dim]({fmt})[/]")
    console.print()
    if not quick:
        console.print(_PIPELINE_INFO)
    console.print()


def _validate_model(value: str | None) -> None:
    """Reject unknown model identifiers with a friendly allowed-list."""
    if value is None or value in _ALLOWED_MODELS:
        return
    allowed = ", ".join(_ALLOWED_MODELS)
    console.print(f"[{RED}]✗[/] Invalid model: {value!r}: not allowed: use one of: {allowed}")
    raise typer.Exit(code=1)


def _validate_effort(value: str | None) -> None:
    """Reject unknown effort levels with a friendly allowed-list."""
    if value is None or value in _ALLOWED_EFFORTS:
        return
    allowed = ", ".join(_ALLOWED_EFFORTS)
    console.print(f"[{RED}]✗[/] Invalid effort: {value!r}: not allowed: use one of: {allowed}")
    raise typer.Exit(code=1)


def _parse_overrides_json(spec: str | None, label: str) -> dict[str, str | None]:
    """Parse a JSON override string; exit 1 with a helpful error on failure."""
    if not spec:
        return {}
    try:
        parsed = _json.loads(spec)
    except _json.JSONDecodeError as exc:
        console.print(f"[{RED}]✗[/] Invalid JSON for --{label}: {exc.msg}")
        raise typer.Exit(code=1) from exc
    if not isinstance(parsed, dict):
        console.print(f"[{RED}]✗[/] --{label} must be a JSON object")
        raise typer.Exit(code=1)
    return {str(k): str(v) for k, v in parsed.items()}


def _validate_analyze_inputs(repo_url: str, fmt: str, fail_on: str, classification: str) -> None:
    """Validate CLI inputs and exit with code 1 on any error.

    Raises:
        typer.Exit: If url is malformed, format is invalid, ``--fail-on``
            is not one of the documented choices, classification is unknown,
            or the analyzer factory has not been injected by the
            composition root.
    """
    source_error = _validate_repo_source(repo_url)
    if source_error:
        console.print(f"[{RED}]✗[/] {source_error}")
        raise typer.Exit(code=1)

    if fmt not in ("html", "json", "sarif"):
        console.print(f"[{RED}]✗[/] Invalid format: use html, json, or sarif")
        raise typer.Exit(code=1)

    if fail_on not in _FAIL_ON_CHOICES:
        allowed = ", ".join(_FAIL_ON_CHOICES)
        console.print(f"[{RED}]✗[/] Invalid --fail-on: {fail_on!r}: use one of: {allowed}")
        raise typer.Exit(code=1)

    if classification not in _ALLOWED_CLASSIFICATIONS:
        allowed = ", ".join(_ALLOWED_CLASSIFICATIONS)
        console.print(f"[{RED}]✗[/] Invalid classification: use one of: {allowed}")
        raise typer.Exit(code=1)

    if _analyzer_factory is None:
        console.print(f"[{RED}]✗[/] Not initialized: run via spectra entry point")
        raise typer.Exit(code=1)


def _count_findings_at_or_above(report: object, threshold: str) -> int:
    """Count report findings whose severity is at or above ``threshold``.

    Returns 0 when ``threshold == "none"`` (gate disabled). Severity
    ranking lives in ``_FAIL_ON_SEVERITY_RANK`` — worst first, so a lower
    rank number means a more severe finding.
    """
    if threshold == "none":
        return 0
    cutoff = _FAIL_ON_SEVERITY_RANK[threshold]
    findings = getattr(report, "findings", ()) or ()
    return sum(1 for f in findings if _FAIL_ON_SEVERITY_RANK.get(getattr(f, "severity", ""), 99) <= cutoff)


def _gather_and_validate_overrides(
    model_effort: tuple[str | None, str | None],
    per_role_models: dict[str, str | None],
    per_role_efforts: dict[str, str | None],
    json_overrides: tuple[str | None, str | None],
) -> dict[str, object]:
    """Validate every CLI input then build the resolver-ready overrides dict.

    Calls ``resolve_agent_configs`` once eagerly to catch composite errors
    (e.g. ``--documentation-model claude-haiku-4-5 --documentation-effort max``)
    before booting the analyzer chain, so users see a friendly CLI error.
    """
    global_model, global_effort = model_effort
    json_model_str, json_effort_str = json_overrides
    _validate_model(global_model)
    _validate_effort(global_effort)
    _validate_per_role_values(per_role_models, _validate_model)
    _validate_per_role_values(per_role_efforts, _validate_effort)
    json_models = _parse_overrides_json(json_model_str, "model-overrides")
    json_efforts = _parse_overrides_json(json_effort_str, "effort-overrides")
    overrides = _collect_agent_overrides(
        global_model,
        global_effort,
        {
            "models": per_role_models,
            "efforts": per_role_efforts,
            "json_models": json_models,
            "json_efforts": json_efforts,
        },
    )
    _eager_validate_overrides(overrides)
    return overrides


def _validate_per_role_values(
    values: dict[str, str | None],
    validator: Callable[[str | None], None],
) -> None:
    """Run ``validator`` on every non-None value in the dict."""
    for value in values.values():
        validator(value)


def _eager_validate_overrides(overrides: dict[str, object]) -> None:
    """Call resolve_agent_configs eagerly so composite errors surface in the CLI."""
    try:
        resolve_agent_configs(overrides)
    except (ValueError, TypeError) as exc:
        console.print(f"[{RED}]✗[/] Invalid agent config: {exc}")
        raise typer.Exit(code=1) from exc


def _collect_agent_overrides(
    global_model: str | None,
    global_effort: str | None,
    per_role: dict[str, dict[str, str | None]],
) -> dict[str, object]:
    """Build the overrides dict consumed by ``resolve_agent_configs``.

    Args:
        global_model: Value of ``--model`` (specialists only).
        global_effort: Value of ``--effort`` (specialists only).
        per_role: Map keyed by ``{"models": {...}, "efforts": {...}, "json_models": ..., "json_efforts": ...}``.

    Returns:
        Dict ready to pass to ``resolve_agent_configs``.
    """
    models = _normalize_role_keys(per_role.get("models") or {})
    efforts = _normalize_role_keys(per_role.get("efforts") or {})
    # JSON wins over per-flag — overlay last
    models.update(_normalize_role_keys(per_role.get("json_models") or {}))
    efforts.update(_normalize_role_keys(per_role.get("json_efforts") or {}))
    return _build_overrides_dict(global_model, global_effort, models, efforts)


def _build_overrides_dict(
    global_model: str | None,
    global_effort: str | None,
    models: dict[str, str],
    efforts: dict[str, str],
) -> dict[str, object]:
    """Compose the overrides dict, omitting empty keys for cleaner test asserts."""
    out: dict[str, object] = {}
    if global_model:
        out["global_model"] = global_model
    if global_effort:
        out["global_effort"] = global_effort
    if models:
        out["models"] = models
    if efforts:
        out["efforts"] = efforts
    return out


def _normalize_role_keys(d: dict[str, str | None]) -> dict[str, str]:
    """Translate CLI role names ('meta') to entity role names; drop None values."""
    return {_CLI_TO_ROLE.get(k, k): v for k, v in d.items() if v is not None}


def _version_callback(value: bool) -> None:
    """Print version and exit when --version/-v is passed."""
    if value:
        console.print(f"[bold {VIOLET}]spectra[/] v{__version__} [dim]// codebase intelligence[/]")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Spectra — The full spectrum of your codebase."""


@app.command()
def analyze(
    repo_url: str = typer.Argument(
        ...,
        help="Git repository URL to analyze",
    ),
    output: Path = _OUTPUT_OPTION,
    quick: bool = typer.Option(
        False,
        "--quick",
        "-q",
        help="Skip CritiqueAgent for faster results",
    ),
    fmt: str = typer.Option(
        "html",
        "--format",
        "-f",
        help="Output format: html, json, or sarif",
    ),
    min_score: float = typer.Option(
        0.0,
        "--min-score",
        help="Minimum overall score to pass (exit 1 if below)",
    ),
    fail_on: str = typer.Option(
        "none",
        "--fail-on",
        help="Exit 1 when any finding is at or above this severity (critical/high/medium/low/none)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Bypass repo-level cache and re-run all 8 agents",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Neither read nor write the cache (CI-safe)",
    ),
    no_gitignore: bool = typer.Option(
        False,
        "--no-gitignore",
        help="Do not honor .gitignore (.spectraignore is still applied)",
    ),
    allow_secrets: bool = typer.Option(
        False,
        "--allow-secrets",
        help="Continue past pre-flight secret detection (WARN, not abort)",
    ),
    audit_sink: str | None = typer.Option(
        None,
        "--audit-sink",
        help="Where to send audit events: stdout|file:<path>|otlp:<url>",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show debug output",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help=f"Default model for the 6 specialists. Allowed: {', '.join(_ALLOWED_MODELS)}",
    ),
    effort: str | None = typer.Option(
        None,
        "--effort",
        help=(
            f"Default effort for the 6 specialists. Allowed: {', '.join(_ALLOWED_EFFORTS)} (xhigh/max Opus-tier only)"
        ),
    ),
    meta_model: str | None = typer.Option(None, "--meta-model", help=_model_help("MetaPrompter")),
    meta_effort: str | None = typer.Option(None, "--meta-effort", help=_effort_help("MetaPrompter")),
    critique_model: str | None = typer.Option(None, "--critique-model", help=_model_help("CritiqueAgent")),
    critique_effort: str | None = typer.Option(None, "--critique-effort", help=_effort_help("CritiqueAgent")),
    architecture_model: str | None = typer.Option(None, "--architecture-model", help=_model_help("architecture")),
    architecture_effort: str | None = typer.Option(None, "--architecture-effort", help=_effort_help("architecture")),
    security_model: str | None = typer.Option(None, "--security-model", help=_model_help("security")),
    security_effort: str | None = typer.Option(None, "--security-effort", help=_effort_help("security")),
    quality_model: str | None = typer.Option(None, "--quality-model", help=_model_help("quality")),
    quality_effort: str | None = typer.Option(None, "--quality-effort", help=_effort_help("quality")),
    documentation_model: str | None = typer.Option(None, "--documentation-model", help=_model_help("documentation")),
    documentation_effort: str | None = typer.Option(None, "--documentation-effort", help=_effort_help("documentation")),
    dependency_model: str | None = typer.Option(None, "--dependency-model", help=_model_help("dependency")),
    dependency_effort: str | None = typer.Option(None, "--dependency-effort", help=_effort_help("dependency")),
    performance_model: str | None = typer.Option(None, "--performance-model", help=_model_help("performance")),
    performance_effort: str | None = typer.Option(None, "--performance-effort", help=_effort_help("performance")),
    model_overrides: str | None = typer.Option(
        None,
        "--model-overrides",
        help=(
            'JSON map of role to model, e.g. \'{"security":"claude-opus-4-7"}\'. '
            f"Models allowed: {', '.join(_ALLOWED_MODELS)}"
        ),
    ),
    effort_overrides: str | None = typer.Option(
        None,
        "--effort-overrides",
        help=(
            'JSON map of role to effort, e.g. \'{"security":"xhigh"}\'. '
            f"Efforts allowed: {', '.join(_ALLOWED_EFFORTS)}"
        ),
    ),
    classification: str = typer.Option(
        "confidential",
        "--classification",
        help="Report classification: confidential (default, full findings) or public (redacted summary)",
    ),
    max_cost_usd: float | None = typer.Option(
        None,
        "--max-cost-usd",
        help="Per-run cost cap (USD). Pipeline aborts (SPEC-014) when exceeded.",
    ),
    max_cost_per_hour: float | None = typer.Option(
        None,
        "--max-cost-per-hour",
        help="Rolling 1-hour cost cap (USD). Persists across runs via cache.db.",
    ),
    cache_remote: str | None = typer.Option(
        None,
        "--cache-remote",
        help=(
            "Distributed L2 cache URL (capability #21, ADR-021). Example: "
            "redis://localhost:6379/0. Defaults to $SPECTRA_CACHE_REDIS, "
            "then local-only when neither is set."
        ),
    ),
    otel_endpoint: str | None = typer.Option(
        None,
        "--otel-endpoint",
        help=(
            "OTLP/HTTP endpoint for OpenTelemetry trace export "
            "(e.g. http://collector:4318/v1/traces). Omit to disable tracing."
        ),
    ),
    team: str | None = typer.Option(
        None,
        "--team",
        envvar="SPECTRA_TEAM",
        help=("Team tag stamped on every span for cost attribution (#33). Defaults to $SPECTRA_TEAM, then 'default'."),
    ),
    rate_limit_rpm: int | None = typer.Option(
        None,
        "--rate-limit-rpm",
        envvar="SPECTRA_RATE_LIMIT_RPM",
        help=(
            "Fleet RPM cap (capability #22, ADR-013). Every Anthropic call "
            "awaits one token from the coordinator. Default unset = no "
            "rate limit beyond the in-process semaphore."
        ),
    ),
    rate_coordinator: str | None = typer.Option(
        None,
        "--rate-coordinator",
        envvar="SPECTRA_RATE_COORDINATOR",
        help=(
            "Coordinator backend. 'inmemory' (default when --rate-limit-rpm "
            "is set) is per-process; 'redis://...' shares one bucket across "
            "every runner pointed at the same Redis (fleet mode)."
        ),
    ),
    notify_webhook: str | None = typer.Option(
        None,
        "--notify-webhook",
        envvar="SPECTRA_NOTIFY_WEBHOOK",
        help=(
            "Slack/Teams incoming-webhook URL for drift + per-finding "
            "alerts (#27 + #34). Auto-detected by host. Defaults to "
            "$SPECTRA_NOTIFY_WEBHOOK; omit for no notifications."
        ),
    ),
    no_drift_alert: bool = typer.Option(
        False,
        "--no-drift-alert",
        help="Suppress automatic post-scan drift firing for this run (#27)",
    ),
    memory_dir: str | None = typer.Option(
        None,
        "--memory-dir",
        envvar="SPECTRA_MEMORY_DIR",
        help=(
            "Per-repo memory directory (#50, ADR-025). Defaults to "
            "$SPECTRA_MEMORY_DIR, then $XDG_DATA_HOME/spectra/memory."
        ),
    ),
    no_memory: bool = typer.Option(
        False,
        "--no-memory",
        envvar="SPECTRA_NO_MEMORY",
        help="Skip the memory port for this run (CI-safe). No reads, writes, or ADR ingest.",
    ),
) -> None:
    """Analyze a repository across 6 dimensions."""
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(name)s %(levelname)s %(message)s",
        )

    _validate_analyze_inputs(repo_url, fmt, fail_on, classification)
    overrides = _gather_and_validate_overrides(
        model_effort=(model, effort),
        per_role_models={
            "meta": meta_model,
            "critique": critique_model,
            "architecture": architecture_model,
            "security": security_model,
            "quality": quality_model,
            "documentation": documentation_model,
            "dependency": dependency_model,
            "performance": performance_model,
        },
        per_role_efforts={
            "meta": meta_effort,
            "critique": critique_effort,
            "architecture": architecture_effort,
            "security": security_effort,
            "quality": quality_effort,
            "documentation": documentation_effort,
            "dependency": dependency_effort,
            "performance": performance_effort,
        },
        json_overrides=(model_overrides, effort_overrides),
    )

    # Capability #56 — suffix the output path so confidential and public
    # artifacts can coexist on disk (and never overwrite each other).
    suffixed_output = _classification_filename(str(output), classification)

    _print_run_header(repo_url, suffixed_output, fmt, classification, quick=quick)
    if max_cost_usd is not None:
        _emit_cost_preflight_warning(max_cost_usd)

    try:
        report = asyncio.run(
            _analyzer_factory(
                repo_url=repo_url,
                output_path=suffixed_output,
                skip_critique=quick,
                output_format=fmt,
                verbose=verbose,
                force=force,
                no_cache=no_cache,
                agent_overrides=overrides,
                honor_gitignore=not no_gitignore,
                allow_secrets=allow_secrets,
                audit_sink=audit_sink,
                classification=classification,
                max_cost_usd=max_cost_usd,
                max_cost_per_hour=max_cost_per_hour,
                cache_remote=cache_remote,
                otel_endpoint=otel_endpoint,
                team=team or "default",
                rate_limit_rpm=rate_limit_rpm,
                rate_coordinator_url=rate_coordinator,
                notify_webhook=notify_webhook,
                no_drift_alert=no_drift_alert,
                memory_dir=memory_dir,
                no_memory=no_memory,
            )
        )
    except BaseException as exc:
        _handle_pipeline_exceptions(exc, verbose=verbose)

    if report is None:
        raise typer.Exit(code=1)

    _print_summary(report, suffixed_output, fmt)

    # Quality gate: exit 1 if score is below --min-score threshold
    if min_score > 0:
        sc = getattr(report, "score_card", None)
        if sc and sc.overall_score < min_score:
            console.print(f"\n[{RED}]✗[/] Quality gate FAILED: {sc.overall_score:.0f} < {min_score:.0f} threshold")
            raise typer.Exit(code=1)
        if sc:
            console.print(f"  [{GREEN}]✓[/] Quality gate passed: {sc.overall_score:.0f} >= {min_score:.0f}")

    # Q2 #19: severity gate — exit 1 when any finding sits at or above
    # the --fail-on threshold. The Action layer flips the default to
    # 'critical' for CI; the CLI default is 'none' so existing scripts
    # never start failing without an explicit opt-in.
    offending = _count_findings_at_or_above(report, fail_on)
    if offending > 0:
        console.print(
            f"\n[{RED}]✗[/] --fail-on={fail_on}: {offending} finding(s) at or above the {fail_on} severity threshold"
        )
        raise typer.Exit(code=1)


def _print_policy_violations(violations: tuple[Violation, ...]) -> None:
    """Render the SPEC-013 brand-voice failure block listing every violation."""
    spec_013 = ERRORS["SPEC-013"]
    console.print(f"[{RED}]✗[/] {spec_013.code}: {len(violations)} policy violations")
    for v in violations:
        console.print(f"  [{RED}]•[/] [{AMBER}]{v.kind}[/] {v.message}")
    console.print(
        "  [dim]Fix the violations or update .spectra-policy.yml; see https://github.com/leocder07/spectra#policy[/]"
    )


def _handle_pipeline_exceptions(exc: BaseException, *, verbose: bool) -> None:
    """Translate any pipeline exception into a brand-voice line + ``typer.Exit``.

    Single funnel for every error class the analyzer can raise — replaces
    a duplicated try/except chain that previously lived in both
    ``analyze()`` and a never-called ``_invoke_analyzer`` helper. Always
    raises; the ``NoReturn`` semantics keep the call site terse.

    Exit codes are pinned by ``TestPipelineExceptionHandler``:

    - ``KeyboardInterrupt`` → exit 130, "cancelled" message
    - ``SecretDetectedError`` → exit 1, SPEC-011 finding block
    - ``PolicyGateError`` → exit 1, SPEC-013 violation block
    - ``BudgetExceededError`` → exit 1, SPEC-014 cost breakdown
    - ``GitError``/``SpectraRetryError``/``AgentError`` → exit 1, code + docs link
    - Anything else → exit 1, "Unexpected error: <repr>"; traceback only when
      ``verbose`` is True so CI logs stay readable

    ``BaseException`` is in the parameter type so ``KeyboardInterrupt``
    can route through here without ruff BLE001 firing on the call site.
    """
    if isinstance(exc, KeyboardInterrupt):
        console.print(f"\n[{AMBER}]⚠[/] Analysis cancelled by user")
        raise typer.Exit(code=130) from None
    if isinstance(exc, SecretDetectedError):
        _print_secret_detection(exc)
        raise typer.Exit(code=1) from exc
    if isinstance(exc, PolicyGateError):
        _print_policy_violations(exc.violations)
        raise typer.Exit(code=1) from exc
    if isinstance(exc, BudgetExceededError):
        _print_budget_exceeded(exc)
        raise typer.Exit(code=1) from exc
    if isinstance(exc, (GitError, SpectraRetryError, AgentError)):
        err = exc.error
        console.print(f"[{RED}]✗[/] {err.code}: {err.message}")
        console.print(f"  [dim]docs: {_docs_link(err.code)}[/]")
        raise typer.Exit(code=1) from exc
    if isinstance(exc, typer.Exit):
        raise exc
    console.print(f"[{RED}]✗[/] Unexpected error: {exc}")
    if verbose:
        console.print(traceback.format_exc())
    raise typer.Exit(code=1) from exc


# Conservative floor: 8 agents x ~$0.005 minimum input cost per call.
_MIN_PIPELINE_COST_USD = 0.04


def _emit_cost_preflight_warning(max_cost_usd: float) -> None:
    """Warn (don't abort) when the cap is below the 8-agent input floor.

    Brand voice: ≤80 chars, no trailing period. Warn-only — operators may
    intentionally probe with a tiny budget to verify the gate fires.
    """
    if max_cost_usd < _MIN_PIPELINE_COST_USD:
        console.print(
            f"  [{AMBER}]⚠[/] --max-cost-usd ${max_cost_usd:.4f} below ~${_MIN_PIPELINE_COST_USD:.2f} 8-agent floor"
        )


def _print_budget_exceeded(exc: BudgetExceededError) -> None:
    """Render the SPEC-014 brand-voice failure block.

    Format constraints (CLAUDE.md §Brand Voice):
      - Header line ≤80 chars, no trailing period
      - Per-agent breakdown rendered under the header
      - Closing hint suggests rerun-with-higher-cap or split-scope
    """
    console.print(
        f"[{RED}]✗[/] {exc.error.code}: budget exceeded "
        f"(${exc.spent_usd:.2f} spent, ${exc.budget_usd:.2f} limit): "
        f"rerun with --max-cost-usd <higher> or split scope"
    )
    if exc.per_agent:
        for agent, cost in sorted(exc.per_agent.items(), key=lambda kv: -kv[1]):
            console.print(f"  [{RED}]•[/] [{AMBER}]{agent}[/] ${cost:.4f}")


def _print_secret_detection(exc: SecretDetectedError) -> None:
    """Render the SPEC-011 brand-voice failure block listing every match.

    Format constraints (CLAUDE.md §Brand Voice):
      - Header line ≤80 chars, no trailing period
      - One line per finding: ``  [pattern] file:line``
      - Closing hint suggests the documented escape hatches
    """
    findings = exc.findings
    file_count = len({getattr(f, "file_path", "?") for f in findings})
    console.print(f"[{RED}]✗[/] {exc.error.code}: {len(findings)} secrets found in {file_count} files")
    for f in findings:
        path = getattr(f, "file_path", "?")
        line = getattr(f, "line", "?")
        pat = getattr(f, "pattern_name", "?")
        console.print(f"  [{RED}]•[/] [{AMBER}]{pat}[/] {path}:{line}")
    console.print("  [dim]Add to .gitignore / .spectraignore, or rerun with [/][bold]--allow-secrets[/]")


def _print_summary(
    report: object,
    output_path: str,
    output_format: str,
) -> None:
    """Print the ScoreCard and report location after analysis completes.

    Args:
        report: Completed ``AnalysisReport``.
        output_path: Path where the report was saved.
        output_format: ``"html"`` or ``"json"``.
    """
    console.print(_SCAN_LINE)
    present_scorecard(report, console)

    if output_format == "html":
        console.print(f"\n  [{GREEN}]✓[/] Report saved to [bold underline]{output_path}[/]")
    else:
        console.print(f"\n  [{GREEN}]✓[/] JSON written to [bold underline]{output_path}[/]")

    console.print(f"\n[dim {VIOLET}]  // spectra analysis complete[/]\n")


def cli_entry() -> None:
    """Start the Typer CLI app.

    Called by the composition root after DI wiring is complete.
    """
    app()


# ── spectra verify ──────────────────────────────────────────


@app.command()
def verify(
    report_path: Path = typer.Argument(  # noqa: B008 — Typer needs the default at definition time
        ...,
        help="Path to a JSON AnalysisReport with an embedded receipt",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    key: Path | None = _KEY_OPTION,
) -> None:
    """Verify the Ed25519 receipt embedded in a JSON report.

    Exits 0 when the signature matches and the score-card hash is intact;
    exits 1 with a brand-voice failure line on any mismatch.
    """
    if _verifier is None:
        console.print(f"[{RED}]✗[/] Not initialized: run via spectra entry point")
        raise typer.Exit(code=1)
    raw = _read_report_text(report_path)
    report = _parse_report(raw)
    receipt = _extract_receipt(report)
    pub_pem = _load_pub_pem(key)
    valid, hash_match = _verify_receipt(report, receipt, pub_pem)
    if valid and hash_match:
        console.print(f"  [{GREEN}]✓[/] receipt verified for scan {receipt.scan_id[:8]}")
        return
    if not hash_match:
        console.print(f"[{RED}]✗[/] score card hash mismatch: report mutated since signing")
    else:
        console.print(f"[{RED}]✗[/] receipt signature invalid")
    raise typer.Exit(code=1)


def _read_report_text(report_path: Path) -> str:
    """Read and return the report file contents; exit on I/O error."""
    try:
        return report_path.read_text(encoding="utf-8")
    except OSError as exc:
        console.print(f"[{RED}]✗[/] Failed to read report: {exc}")
        raise typer.Exit(code=1) from exc


def _parse_report(raw: str) -> AnalysisReport:
    """Parse the JSON report; exit cleanly on schema failure."""
    try:
        return AnalysisReport.model_validate_json(raw)
    except ValueError as exc:
        console.print(f"[{RED}]✗[/] Invalid report JSON: {exc}")
        raise typer.Exit(code=1) from exc


def _extract_receipt(report: AnalysisReport) -> _ReceiptShape:
    """Return the embedded receipt or exit with a clear message."""
    receipt = report.receipt
    if receipt is None:
        console.print(f"[{RED}]✗[/] No receipt found in report")
        raise typer.Exit(code=1)
    return receipt


def _load_pub_pem(key: Path | None) -> bytes | None:
    """Load the public-key PEM from the explicit path or the default."""
    chosen = key if key is not None else _default_public_key_path
    if chosen is None or not chosen.exists():
        return None
    try:
        return chosen.read_bytes()
    except OSError:
        return None


def _verify_receipt(
    report: AnalysisReport,
    receipt: _ReceiptShape,
    pub_pem: bytes | None,
) -> tuple[bool, bool]:
    """Return (signature_valid, score_card_hash_matches) for the receipt."""
    if _verifier is None:
        return (False, False)
    sig_ok = bool(_verifier(receipt, pub_pem))
    expected_hash = _compute_score_card_hash(report.score_card)
    hash_ok = expected_hash == getattr(receipt, "score_card_hash", "")
    return (sig_ok, hash_ok)


def _compute_score_card_hash(score_card: object) -> str:
    """Recompute the score-card hash (mirrors infrastructure.receipt_signer)."""
    import hashlib
    import json as _json_inner

    serialised = _json_inner.dumps(
        score_card.model_dump(mode="json"),  # type: ignore[attr-defined]
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.blake2b(serialised.encode("utf-8"), digest_size=32).hexdigest()


# ── spectra waive + approver subcommands (#18) ───────────────

app.command("waive", help="Sign and append a waiver suppressing one finding")(waive_command)
app.add_typer(approver_app, name="approver")


# ── spectra cache subcommands ─────────────────────────────────

cache_app = typer.Typer(help="Manage the analysis cache")
app.add_typer(cache_app, name="cache")

_DEFAULT_PRUNE_AGE = "30d"
_REPO_SIGNATURE_HEX_LEN = 32
# Duration suffixes accepted by --older-than
_DURATION_SUFFIXES: dict[str, int] = {
    "d": 86_400,
    "w": 604_800,
    "m": 2_592_000,  # 30 days — calendar months are intentionally approximate
}


def _get_cache() -> CachePort:
    """Return the cache instance from the injected provider, or exit cleanly."""
    if _cache_provider is None:
        console.print(f"[{RED}]✗[/] Not initialized: run via spectra entry point")
        raise typer.Exit(code=1)
    return _cache_provider()


def _resolve_repo_signature(repo: str, cache: CachePort) -> str:
    """Resolve a URL or already-hashed signature to a 32-hex repo_signature."""
    if len(repo) == _REPO_SIGNATURE_HEX_LEN and all(c in "0123456789abcdef" for c in repo):
        return repo
    # URL or path: hash the singleton "file tree" containing just the repo string.
    return cache.compute_repo_signature((repo,))


def _parse_duration(spec: str) -> timedelta:
    """Parse '30d' / '4w' / '1m' / '90d' into a timedelta. Raise on invalid."""
    text = spec.strip().lower()
    if len(text) < 2 or text[-1] not in _DURATION_SUFFIXES or not text[:-1].isdigit():
        msg = f"Invalid --older-than duration: {spec!r} (use 30d, 4w, 1m)"
        raise ValueError(msg)
    seconds = int(text[:-1]) * _DURATION_SUFFIXES[text[-1]]
    return timedelta(seconds=seconds)


@cache_app.command("stats")
def cache_stats(
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON instead of a table (CI-friendly)",
    ),
) -> None:
    """Show cache file location, size, entries, and rolling hit rates."""
    cache = _get_cache()
    stats = cache.stats()
    if as_json:
        _print_stats_json(stats)
        return
    _render_stats_table(cache, stats)


def _print_stats_json(stats: CacheStats) -> None:
    """Emit CacheStats as indent-2 JSON to stdout — no Rich formatting."""
    typer.echo(stats.model_dump_json(indent=2))


@cache_app.command("clear")
def cache_clear(
    repo: str | None = typer.Argument(
        None,
        help="Repo URL or signature; omit to clear ALL rows",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirm prompt"),
) -> None:
    """Purge cache rows; prints the count deleted."""
    cache = _get_cache()
    if repo is None:
        _do_clear_all(cache, yes=yes)
        return
    _do_clear_by_repo(cache, repo, yes=yes)


@cache_app.command("prune")
def cache_prune(
    older_than: str = typer.Option(
        _DEFAULT_PRUNE_AGE,
        "--older-than",
        help="Drop rows older than this (e.g. 30d, 4w, 1m)",
    ),
    include_hit_log: bool = typer.Option(
        False,
        "--include-hit-log",
        help="Also drop old hit_log rows (default: keep telemetry)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be deleted without doing it",
    ),
) -> None:
    """GC cache rows older than --older-than (default 30d)."""
    cache = _get_cache()
    duration = _parse_duration_or_exit(older_than)
    _do_prune(cache, duration, include_hit_log=include_hit_log, dry_run=dry_run)


def _parse_duration_or_exit(older_than: str) -> timedelta:
    """Parse the duration spec; exit 1 with a friendly error on failure."""
    try:
        return _parse_duration(older_than)
    except ValueError as exc:
        console.print(f"[{RED}]✗[/] {exc}")
        raise typer.Exit(code=1) from exc


def _do_clear_all(cache: CachePort, *, yes: bool) -> None:
    """Confirm (unless --yes) and clear every cache table."""
    if not yes and not typer.confirm("Clear ALL cache rows?", default=False):
        console.print(f"[{AMBER}]⚠[/] Aborted")
        return
    deleted = cache.clear_all()
    console.print(f"  [{GREEN}]✓[/] Cleared {deleted} rows")


def _do_clear_by_repo(cache: CachePort, repo: str, *, yes: bool) -> None:
    """Confirm (unless --yes) and clear one repo's rows."""
    sig = _resolve_repo_signature(repo, cache)
    if not yes and not typer.confirm(f"Clear cache for repo {sig[:8]}?", default=False):
        console.print(f"[{AMBER}]⚠[/] Aborted")
        return
    deleted = cache.clear_by_repo(sig)
    console.print(f"  [{GREEN}]✓[/] Cleared {deleted} rows for {sig[:8]}")


def _do_prune(
    cache: CachePort,
    duration: timedelta,
    *,
    include_hit_log: bool,
    dry_run: bool,
) -> None:
    """Run prune (or simulate) and print per-table delete counts."""
    cutoff = datetime.now(UTC) - duration
    if dry_run:
        console.print(f"  [{AMBER}]▸[/] Dry run: would prune rows older than {cutoff:%Y-%m-%d}")
        return
    deleted = cache.prune_older_than(cutoff, include_hit_log=include_hit_log)
    total = sum(deleted.values())
    console.print(f"  [{GREEN}]✓[/] Pruned {total} rows older than {cutoff:%Y-%m-%d}")
    for table, count in deleted.items():
        console.print(f"    [dim]{table}[/]: {count}")


def _render_stats_table(cache: CachePort, stats: CacheStats) -> None:
    """Render the Rich table that ``spectra cache stats`` prints."""
    db_path = getattr(cache, "db_path", Path("cache.db"))
    table = Table(title="Spectra cache stats", title_style=f"bold {VIOLET}")
    table.add_column("Field", style=f"bold {AMBER}")
    table.add_column("Value")
    for label, value in _stats_rows(stats, db_path):
        table.add_row(label, value)
    console.print(table)
    if stats.hit_rate_by_dimension:
        _render_per_dim_hit_rate(stats)


def _stats_rows(stats: CacheStats, db_path: Path) -> list[tuple[str, str]]:
    """Compose the (label, value) rows for the stats table."""
    return [
        ("Cache file", str(db_path)),
        ("Size (bytes)", f"{stats.db_size_bytes:,}"),
        ("Total entries", str(stats.total_entries)),
        ("Full-report rows", str(stats.full_report_entries)),
        ("Per-batch rows", str(stats.batch_entries)),
        ("Hit-log rows", str(stats.hit_log_entries)),
        ("Repos tracked", str(stats.total_repos)),
        ("Hit rate (last 100)", f"{stats.hit_rate_last_100:.0%}"),
        ("Oldest entry", _fmt_dt(stats.oldest_entry_at)),
        ("Most recent activity", _fmt_dt(stats.most_recent_activity_at)),
    ]


def _fmt_dt(value: datetime | None) -> str:
    """Format an optional datetime for display, '—' when missing."""
    return str(value) if value else "—"


def _render_per_dim_hit_rate(stats: CacheStats) -> None:
    """Render the per-dimension hit-rate sub-table."""
    table = Table(title="Per-dimension hit rate", title_style=f"bold {VIOLET}")
    table.add_column("Dimension", style=f"bold {AMBER}")
    table.add_column("Hit rate")
    for dim, rate in sorted(stats.hit_rate_by_dimension.items()):
        table.add_row(dim, f"{rate:.0%}")
    console.print(table)


# ── spectra render subcommands ────────────────────────────────

render_app = typer.Typer(help="Render reports for downstream tools (PR comments, etc.)")
app.add_typer(render_app, name="render")


@render_app.command("pr-comment")
def render_pr_comment_cmd(
    report_path: Path = typer.Argument(  # noqa: B008 — Typer needs the default at definition time
        ...,
        help="Path to a JSON AnalysisReport produced by `spectra analyze --format json`",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Emit a markdown-safe PR comment body to stdout.

    Reads the JSON report at ``report_path``, validates it against the
    ``AnalysisReport`` Pydantic model, and prints a sanitized markdown
    body suitable for ``gh pr comment``. Output starts with the
    ``<!-- SPECTRA -->`` sentinel so the GitHub Action's update-existing
    comment path stays idempotent across re-runs.
    """
    try:
        raw = report_path.read_text(encoding="utf-8")
        report = AnalysisReport.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        console.print(f"[{RED}]✗[/] Failed to load report: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(render_pr_comment(report))


# ── ADR-012: spectra cache doctor ────────────────────────────


@cache_app.command("doctor")
def cache_doctor() -> None:
    """Diagnose the cache: path, UID, keyring backend, MAC verification rates."""
    cache = _get_cache()
    _render_doctor_environment(cache)
    _render_doctor_row_counts(cache)


def _render_doctor_environment(cache: CachePort) -> None:
    """Render the environment table — path, UID, keyring backend, encryption."""
    db_path = getattr(cache, "db_path", Path("cache.db"))
    has_secret = bool(getattr(cache, "has_secret", False))
    backend_label = "OS keyring (HMAC enforced)" if has_secret else "disabled (no secret)"
    table = Table(title="Spectra cache doctor", title_style=f"bold {VIOLET}")
    table.add_column("Field", style=f"bold {AMBER}")
    table.add_column("Value")
    table.add_row("Cache file", str(db_path))
    table.add_row("UID", _doctor_uid_label())
    table.add_row("Keyring backend", backend_label)
    table.add_row("Encryption", _doctor_encryption_label(cache))
    console.print(table)


def _doctor_encryption_label(cache: CachePort) -> str:
    """Map the cache's ``encryption_status`` to a friendly doctor row value."""
    status = getattr(cache, "encryption_status", "plain")
    if status == "sqlcipher":
        return "SQLCipher enabled"
    return "fallback (plain SQLite)"


def _doctor_uid_label() -> str:
    """Return the effective UID label (or ``win`` on Windows)."""
    geteuid = getattr(os, "geteuid", None)
    return str(geteuid()) if geteuid else "win"


def _render_doctor_row_counts(cache: CachePort) -> None:
    """Render the per-table verified/failed table from ``count_rows``."""
    counter = getattr(cache, "count_rows", None)
    if counter is None:
        console.print(f"  [{AMBER}]▸[/] count_rows unsupported by this cache")
        return
    counts = counter()
    table = Table(title="MAC verification (per table)", title_style=f"bold {VIOLET}")
    table.add_column("Table", style=f"bold {AMBER}")
    table.add_column("Total", justify="right")
    table.add_column("Verified", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Verified %", justify="right")
    for name, c in counts.items():
        total = c["total"]
        verified = c["verified"]
        failed = c["failed"]
        pct = f"{(verified / total):.0%}" if total else "—"
        table.add_row(name, str(total), str(verified), str(failed), pct)
    console.print(table)


# ── Roadmap #13: spectra cache shred ─────────────────────────


@cache_app.command("shred")
def cache_shred(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the destructive-action confirmation prompt",
    ),
) -> None:
    """Securely overwrite + delete cache.db AND drop keyring secrets.

    This is the recovery primitive when a cache is suspected to be
    compromised, when re-keying is required after a teammate's machine
    is lost, or when cleaning up before disposal. Re-running ``spectra
    analyze`` after a shred will cold-start a fresh encrypted cache
    under freshly minted keys.
    """
    if _shred_executor is None:
        console.print(f"[{RED}]✗[/] Not initialized: run via spectra entry point")
        raise typer.Exit(code=1)
    if not yes and not typer.confirm(
        "Permanently overwrite + delete cache.db AND drop keyring secrets?",
        default=False,
    ):
        console.print(f"[{AMBER}]⚠[/] Aborted")
        return
    try:
        shredded = _shred_executor()
    except Exception as exc:
        console.print(f"[{RED}]✗[/] shred failed: {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"  [{GREEN}]✓[/] shred complete: {shredded}")
    console.print("  [dim]next analyze run will cold-mint fresh keys[/]")


# ── #25 + ADR-022: spectra history subcommands ───────────────


history_app = typer.Typer(help="Query scan history and apply schema migrations")
app.add_typer(history_app, name="history")


def _get_history_store() -> ReportStorePort:
    """Return the history store via the injected provider, or exit cleanly."""
    if _history_store_provider is None:
        console.print(f"[{RED}]✗[/] No history backend wired: set --history-backend or SPECTRA_POSTGRES_URL")
        raise typer.Exit(code=1)
    return _history_store_provider()


def _format_summary_line(summary: ReportSummary) -> str:
    """One-line representation of a ReportSummary for terminal output."""
    ts = summary.timestamp.strftime("%Y-%m-%d %H:%M")
    return (
        f"{ts}  {summary.overall_grade:>2}  "
        f"score={summary.overall_score:5.1f}  "
        f"findings={summary.total_findings:3d}  "
        f"scan={summary.scan_id}"
    )


@history_app.command("latest")
def history_latest(
    repo: str = typer.Argument(..., help="Repo URL or 32-hex repo_signature"),
) -> None:
    """Print the most recent scan summary for ``repo``."""
    store = _get_history_store()
    repo_signature = _resolve_history_signature(repo)
    summary = asyncio.run(store.latest(repo_signature))
    if summary is None:
        console.print(f"  [{AMBER}]▸[/] No scans recorded for {repo}")
        return
    console.print(f"  [{GREEN}]✓[/] {_format_summary_line(summary)}")


@history_app.command("trend")
def history_trend(
    repo: str = typer.Argument(..., help="Repo URL or 32-hex repo_signature"),
    since: str = typer.Option(
        "6w",
        "--since",
        help="Look back this far (e.g. 6w, 30d, 3m). Default: 6w",
    ),
) -> None:
    """Print scans for ``repo`` within the lookback window as a table."""
    store = _get_history_store()
    repo_signature = _resolve_history_signature(repo)
    duration = _parse_duration_or_exit(since)
    until = datetime.now(UTC)
    rows = asyncio.run(store.history(repo_signature, since=until - duration, until=until))
    if not rows:
        console.print(f"  [{AMBER}]▸[/] No scans in the last {since} for {repo}")
        return
    _render_trend_table(rows, since)


@app.command("digest")
def digest_command(
    since: str = typer.Option(
        "1w",
        "--since",
        help="Lookback window (e.g. 1w, 30d). Default: 1w",
    ),
    notify_webhook: str | None = typer.Option(
        None,
        "--notify",
        "--notify-webhook",
        help="Slack/Teams webhook URL; auto-detected. Omit to print to stdout.",
    ),
    tag: str | None = typer.Option(
        None,
        "--tag",
        help="Filter to repos whose latest scan carries this tag (e.g. team:payments)",
    ),
) -> None:
    """Compose the weekly digest from history; print or post to a webhook (#34)."""
    from spectra.use_cases.digest import compose_weekly_digest, render_digest_markdown
    from spectra.use_cases.notifications import safe_send

    if tag is not None:
        # Tag-filtered digest is reserved for the per-team plan; surface
        # a friendly notice rather than silently ignore. The flag is kept
        # so customers can wire up tomorrow without a CLI bump.
        console.print(f"  [{AMBER}]▸[/] --tag is reserved (no-op in v0.7.x); see #34")

    store = _get_history_store()
    duration = _parse_duration_or_exit(since)
    window_days = max(1, duration.days)
    digest = asyncio.run(compose_weekly_digest(history=store, window_days=window_days))  # type: ignore[arg-type]
    body = render_digest_markdown(digest)
    if notify_webhook is None:
        typer.echo(body)
        return
    notifier, severity = _build_digest_notifier(notify_webhook)
    if notifier is None:
        return
    from spectra.entities.models import NotifierMessage

    msg = NotifierMessage(
        title=f"Spectra digest ({since})",
        body_markdown=body,
        severity=severity,
    )
    asyncio.run(safe_send(notifier, msg))
    console.print(f"  [{GREEN}]✓[/] digest posted to {notify_webhook}")


def _build_digest_notifier(webhook_url: str) -> tuple[NotifierPort | None, Severity]:
    """Auto-detect Slack/Teams from the URL and return (notifier, severity)."""
    from spectra.infrastructure.notifiers import notifier_from_url

    try:
        notifier = notifier_from_url(webhook_url)
    except ValueError as exc:
        console.print(f"[{RED}]✗[/] {exc}")
        raise typer.Exit(code=1) from exc
    return notifier, "info"


@app.command("trend")
def trend_command(
    repo: str = typer.Argument(..., help="Repo URL or 32-hex repo_signature"),
    since: str = typer.Option(
        "6w",
        "--since",
        help="Look back this far (e.g. 6w, 30d, 3m). Default: 6w",
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help="Run drift detection on the latest scans and print why scores moved",
    ),
) -> None:
    """Print scan history as a table; --explain calls drift detection (#27)."""
    from spectra.use_cases.drift_detection import detect_drift

    store = _get_history_store()
    repo_signature = _resolve_history_signature(repo)
    duration = _parse_duration_or_exit(since)
    until = datetime.now(UTC)
    rows = asyncio.run(store.history(repo_signature, since=until - duration, until=until))
    if not rows:
        console.print(f"  [{AMBER}]▸[/] No scans in the last {since} for {repo}")
        return
    _render_trend_table(rows, since)
    if explain:
        events = asyncio.run(detect_drift(store, repo_signature=repo_signature))
        _print_drift_explanation(events)


def _print_drift_explanation(events: tuple[object, ...]) -> None:
    """Render drift events under the trend table; brand-voice friendly."""
    if not events:
        console.print(f"\n  [{GREEN}]✓[/] No drift detected against the previous scan")
        return
    console.print(f"\n  [{AMBER}]▸[/] drift detected on {len(events)} dimension(s):")
    for ev in events:
        dim = getattr(ev, "dimension", "?")
        prev = getattr(ev, "previous_score", 0.0)
        cur = getattr(ev, "current_score", 0.0)
        prev_g = getattr(ev, "previous_grade", "?")
        cur_g = getattr(ev, "current_grade", "?")
        delta = getattr(ev, "delta", cur - prev)
        console.print(f"    [{RED}]•[/] [{AMBER}]{dim}[/] {prev_g} → {cur_g} ({prev:.1f} → {cur:.1f}, Δ {delta:+.1f})")


@history_app.command("migrate")
def history_migrate() -> None:
    """Apply pending SQL migrations to the wired history backend."""
    if _history_migrator is None:
        console.print(f"[{RED}]✗[/] No history migrator wired: set --history-backend or SPECTRA_POSTGRES_URL")
        raise typer.Exit(code=1)
    try:
        applied = _history_migrator()
    except Exception as exc:
        console.print(f"[{RED}]✗[/] migration failed: {exc}")
        raise typer.Exit(code=1) from exc
    if not applied:
        console.print(f"  [{GREEN}]✓[/] schema is up to date — no pending migrations")
        return
    console.print(f"  [{GREEN}]✓[/] applied {len(applied)} migration(s):")
    for version in applied:
        console.print(f"    [dim]·[/] {version}")


def _resolve_history_signature(repo: str) -> str:
    """Resolve a URL or already-hashed signature to the canonical signature.

    Mirrors the cache CLI helper so users can pass either form.
    """
    if len(repo) == _REPO_SIGNATURE_HEX_LEN and all(c in "0123456789abcdef" for c in repo):
        return repo
    # Same shape as the cache helper: blake2b of singleton file tree of the URL.
    from hashlib import blake2b

    digest = blake2b(digest_size=16)
    digest.update(repo.encode("utf-8"))
    digest.update(b"\x00")
    return digest.hexdigest()


def _render_trend_table(rows: tuple[ReportSummary, ...], since: str) -> None:
    """Render the trend table — one row per scan, most recent first."""
    table = Table(
        title=f"Scan history (last {since})",
        title_style=f"bold {VIOLET}",
    )
    table.add_column("Date", style=f"bold {AMBER}")
    table.add_column("Grade", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Findings", justify="right")
    table.add_column("Scan ID", style="dim")
    for r in rows:
        table.add_row(
            r.timestamp.strftime("%Y-%m-%d %H:%M"),
            r.overall_grade,
            f"{r.overall_score:.1f}",
            str(r.total_findings),
            r.scan_id,
        )
    console.print(table)


# ── #26: spectra portfolio subcommands ────────────────────────


portfolio_app = typer.Typer(help="Manage the repo registry and run portfolio scans")
app.add_typer(portfolio_app, name="portfolio")


_DEFAULT_PORTFOLIO_SINCE = "7d"
_DASH = "—"


def _get_portfolio_registry() -> RepoRegistryPort:
    """Return the registry instance from the injected provider, or exit cleanly."""
    if _portfolio_registry_provider is None:
        console.print(f"[{RED}]✗[/] No portfolio registry wired: run via spectra entry point")
        raise typer.Exit(code=1)
    return _portfolio_registry_provider()


def _get_portfolio_analyzer() -> Callable[[str], Awaitable[object]]:
    """Return the analyzer callable from the injected provider, or exit cleanly."""
    if _portfolio_analyzer is None:
        console.print(f"[{RED}]✗[/] No portfolio analyzer wired: run via spectra entry point")
        raise typer.Exit(code=1)
    return _portfolio_analyzer


@portfolio_app.command("add")
def portfolio_add(
    repo_url: str = typer.Argument(..., help="Repository URL to register"),
    tags: list[str] = typer.Option(  # noqa: B008
        None,
        "--tag",
        "-t",
        help="Free-form tag (e.g. team:payments). Repeat for multiple tags.",
    ),
) -> None:
    """Register a repository in the portfolio."""
    registry = _get_portfolio_registry()
    tag_tuple: tuple[str, ...] = tuple(tags) if tags else ()
    entry = registry.add(repo_url, tags=tag_tuple)
    if entry.tags:
        console.print(f"  [{GREEN}]✓[/] added {repo_url} [dim](tags: {', '.join(entry.tags)})[/]")
    else:
        console.print(f"  [{GREEN}]✓[/] added {repo_url}")


@portfolio_app.command("remove")
def portfolio_remove(
    repo_url: str = typer.Argument(..., help="Repository URL to remove"),
) -> None:
    """Remove a repository from the portfolio."""
    registry = _get_portfolio_registry()
    removed = registry.remove(repo_url)
    if removed:
        console.print(f"  [{GREEN}]✓[/] removed {repo_url}")
    else:
        console.print(f"  [{AMBER}]▸[/] not found: {repo_url} (no entry to remove)")


@portfolio_app.command("list")
def portfolio_list(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Restrict to entries carrying this tag"),
) -> None:
    """List every registered repository (optionally filtered by tag)."""
    registry = _get_portfolio_registry()
    entries = registry.list(tag=tag)
    if not entries:
        if tag is None:
            console.print(f"  [{AMBER}]▸[/] no repos registered — add one with `spectra portfolio add <url>`")
        else:
            console.print(f"  [{AMBER}]▸[/] no repos with tag {tag!r}")
        return
    _render_portfolio_list_table(entries)


def _render_portfolio_list_table(entries: tuple[RepoRegistryEntry, ...]) -> None:
    """Render the portfolio list as a Rich table."""
    table = Table(title="Portfolio", title_style=f"bold {VIOLET}")
    table.add_column("Repo URL", style=f"bold {AMBER}")
    table.add_column("Tags", style="dim")
    table.add_column("Added", justify="right")
    table.add_column("Last scan", justify="right")
    for e in entries:
        last = e.last_scan_at.strftime("%Y-%m-%d %H:%M") if e.last_scan_at else _DASH
        table.add_row(
            e.repo_url,
            ", ".join(e.tags) if e.tags else _DASH,
            e.added_at.strftime("%Y-%m-%d"),
            last,
        )
    console.print(table)


@portfolio_app.command("scan")
def portfolio_scan(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Restrict to entries carrying this tag"),
    since: str = typer.Option(
        _DEFAULT_PORTFOLIO_SINCE,
        "--since",
        help="Skip repos scanned within this window (e.g. 7d, 24h, 1w). Default: 7d",
    ),
) -> None:
    """Run the full Spectra pipeline on every stale repository in the portfolio."""
    registry = _get_portfolio_registry()
    analyzer = _get_portfolio_analyzer()
    duration = _parse_duration_or_exit(since)
    entries = registry.list()
    plan = plan_portfolio_scan(
        entries=entries,
        tag=tag,
        since=duration,
        now=datetime.now(UTC),
    )
    if not plan.has_work():
        _print_empty_scan_message(plan, tag=tag, since=since)
        return
    mode = select_run_mode(repo_count=len(plan.to_scan))
    _print_scan_header(plan, mode=mode, tag=tag, since=since)
    asyncio.run(_run_portfolio_scan(registry, analyzer, plan))


def _print_empty_scan_message(plan: PortfolioScanPlan, *, tag: str | None, since: str) -> None:
    """Friendly message when the planner found nothing to scan."""
    if plan.total_known() == 0:
        if tag is None:
            console.print(f"  [{AMBER}]▸[/] no repos registered — nothing to scan")
        else:
            console.print(f"  [{AMBER}]▸[/] no repos with tag {tag!r} — nothing to scan")
        return
    skipped = len(plan.skipped)
    console.print(f"  [{GREEN}]✓[/] every repo scanned within --since {since} ({skipped} skipped)")


def _print_scan_header(
    plan: PortfolioScanPlan,
    *,
    mode: PortfolioScanRunMode,
    tag: str | None,
    since: str,
) -> None:
    """Render the per-run banner showing mode + scope before scanning starts."""
    scope = f"tag={tag}" if tag else "all repos"
    console.print(
        f"  [{AMBER}]▸[/] portfolio scan: {len(plan.to_scan)} to scan, "
        f"{len(plan.skipped)} skipped (since={since}, scope={scope}, mode={mode.value})"
    )


async def _run_portfolio_scan(
    registry: RepoRegistryPort,
    analyzer: Callable[[str], Awaitable[object]],
    plan: PortfolioScanPlan,
) -> None:
    """Iterate the analyzer over every entry; mark scanned on success.

    Per-repo failures are logged but never abort the run — the operator
    wants partial results from a 312-repo overnight scan rather than no
    results at all (q3-plan acceptance criteria).

    Note: this is a sync iteration even when ``mode == BATCH``. The
    Batch API hookup is staged separately so the portfolio scheduler
    can ship without coupling to the long-poll loop. The mode banner
    surfaces the decision so users know which dispatch path will be
    upgraded in a follow-up commit (#23 + #26 integration).
    """
    succeeded = 0
    failed = 0
    for entry in plan.to_scan:
        try:
            await analyzer(entry.repo_url)
        except Exception as exc:
            failed += 1
            console.print(f"  [{RED}]✗[/] {entry.repo_url}: {type(exc).__name__}: {exc}")
            continue
        succeeded += 1
        registry.mark_scanned(entry.repo_url, scanned_at=datetime.now(UTC))
        console.print(f"  [{GREEN}]✓[/] {entry.repo_url}")
    console.print()
    console.print(f"  portfolio scan complete: {succeeded} succeeded, {failed} failed")


@portfolio_app.command("dashboard")
def portfolio_dashboard() -> None:
    """Print a leaderboard of registered repos sorted by latest score."""
    registry = _get_portfolio_registry()
    store = _get_history_store()
    entries = registry.list()
    if not entries:
        console.print(f"  [{AMBER}]▸[/] no repos registered — nothing to render")
        return
    rows = asyncio.run(_collect_dashboard_rows(entries, store))
    _render_dashboard_table(rows)


@dataclass(frozen=True)
class _DashboardRow:
    """One leaderboard row — pre-computed so render() is pure presentation."""

    repo_name: str
    repo_url: str
    last_grade: str
    last_score: float | None
    scan_count_30d: int
    trend_arrow: str


_TREND_UP = "▲"
_TREND_DOWN = "▼"
_TREND_FLAT = "■"
_TREND_NONE = _DASH


async def _collect_dashboard_rows(
    entries: tuple[RepoRegistryEntry, ...],
    store: ReportStorePort,
) -> tuple[_DashboardRow, ...]:
    """Build one ``_DashboardRow`` per entry by querying the history store."""
    now = datetime.now(UTC)
    window_start = now - timedelta(days=30)
    rows: list[_DashboardRow] = []
    for entry in entries:
        repo_signature = _resolve_history_signature(entry.repo_url)
        recent = await store.history(repo_signature, since=window_start, until=now)
        latest = recent[0] if recent else None
        rows.append(
            _DashboardRow(
                repo_name=_dashboard_display_name(entry.repo_url),
                repo_url=entry.repo_url,
                last_grade=latest.overall_grade if latest else _DASH,
                last_score=latest.overall_score if latest else None,
                scan_count_30d=len(recent),
                trend_arrow=_trend_arrow(recent),
            )
        )
    rows.sort(key=lambda r: (r.last_score is None, -(r.last_score or 0.0)))
    return tuple(rows)


def _dashboard_display_name(repo_url: str) -> str:
    """Friendly short name for a leaderboard row."""
    return repo_url.rstrip("/").split("/")[-1].removesuffix(".git") or repo_url


def _trend_arrow(recent: tuple[ReportSummary, ...]) -> str:
    """Return the trend arrow for a leaderboard row.

    Compares the latest scan to the prior one. Difference < 2 points is
    considered flat (within stochastic noise per the Q3-A2 caveat).
    """
    if len(recent) < 2:
        return _TREND_NONE
    latest = recent[0].overall_score
    prior = recent[1].overall_score
    delta = latest - prior
    if abs(delta) < 2.0:
        return _TREND_FLAT
    return _TREND_UP if delta > 0 else _TREND_DOWN


def _render_dashboard_table(rows: tuple[_DashboardRow, ...]) -> None:
    """Render the dashboard as a Rich table sorted by score descending."""
    table = Table(title="Portfolio leaderboard", title_style=f"bold {VIOLET}")
    table.add_column("Repo", style=f"bold {AMBER}")
    table.add_column("Grade", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Scans (30d)", justify="right")
    table.add_column("Trend", justify="center")
    for r in rows:
        score_text = f"{r.last_score:.1f}" if r.last_score is not None else _DASH
        table.add_row(
            f"{r.repo_name}  [dim]{r.repo_url}[/]",
            r.last_grade,
            score_text,
            str(r.scan_count_30d),
            r.trend_arrow,
        )
    console.print(table)
