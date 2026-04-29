"""Typer CLI controller for Spectra — Layer 3 adapter.

The CLI defines commands and options but does NOT wire dependencies.
The composition root (infrastructure/main.py) sets the analyzer
callable via `set_analyzer_factory()` before the CLI runs.
"""

from __future__ import annotations

import asyncio
import logging
import re
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import typer
from rich.console import Console
from rich.table import Table

from spectra.adapters.analysis_presenter import present_scorecard
from spectra.adapters.brand import AMBER, GREEN, RED, VIOLET
from spectra.entities.errors import AgentError, GitError, SpectraRetryError
from spectra.entities.models import CacheStats
from spectra.use_cases.interfaces import CachePort, is_local_path

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

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


def _derive_display_name(source: str) -> str:
    """Pick a friendly target name for the banner from a URL or local path."""
    if is_local_path(source):
        raw = source[len("file://") :] if source.startswith("file://") else source
        return Path(raw).expanduser().resolve().name or "repo"
    return source.rstrip("/").split("/")[-1].removesuffix(".git")


_DEFAULT_OUTPUT = Path("spectra-report.html")
_OUTPUT_OPTION = typer.Option(
    _DEFAULT_OUTPUT,
    "--output",
    "-o",
    help="Report output path",
)

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
[dim #52525b]  ┌─ pipeline ───────────────────────────────────┐[/]
[dim #52525b]  │[/] [#F59E0B]1[/] MetaPrompter    [dim]sonnet-4.5  planner  [/] [dim #52525b]│[/]
[dim #52525b]  │[/] [#F59E0B]6[/] Specialists     [dim]opus-4.6    parallel [/] [dim #52525b]│[/]
[dim #52525b]  │[/] [#F59E0B]1[/] CritiqueAgent   [dim]opus-4.6    thinking [/] [dim #52525b]│[/]
[dim #52525b]  │[/] [dim]  arch · sec · qual · doc · dep · perf  [/] [dim #52525b]│[/]
[dim #52525b]  └──────────────────────────────────────────────┘[/]\
"""

_SCAN_LINE = f"[{VIOLET}]{'─' * 50}[/]"

# Injected by the composition root before CLI runs
_analyzer_factory: Callable[..., Awaitable[object]] | None = None
_cache_provider: Callable[[], CachePort] | None = None


def set_analyzer_factory(
    factory: Callable[..., Awaitable[object]],
) -> None:
    """Inject the async analyzer callable from the composition root.

    Args:
        factory: Async function accepting repo_url, output_path, etc.
    """
    global _analyzer_factory  # noqa: PLW0603
    _analyzer_factory = factory


def set_cache_provider(provider: Callable[[], CachePort]) -> None:
    """Inject the cache-port factory used by ``spectra cache *`` subcommands.

    The composition root passes a zero-arg callable that returns a fresh
    ``CachePort``. The CLI invokes it lazily so the LLM stack is never
    required when only manipulating the local cache.
    """
    global _cache_provider  # noqa: PLW0603
    _cache_provider = provider


def _print_banner() -> None:
    """Print the hacker-style ASCII banner."""
    console.print(_BANNER)
    console.print(_SCAN_LINE)


def _validate_analyze_inputs(repo_url: str, fmt: str) -> None:
    """Validate CLI inputs and exit with code 1 on any error.

    Raises:
        typer.Exit: If url is malformed, format is invalid, or the
            analyzer factory has not been injected by the composition root.
    """
    source_error = _validate_repo_source(repo_url)
    if source_error:
        console.print(f"[{RED}]✗[/] {source_error}")
        raise typer.Exit(code=1)

    if fmt not in ("html", "json", "sarif"):
        console.print(f"[{RED}]✗[/] Invalid format: use html, json, or sarif")
        raise typer.Exit(code=1)

    if _analyzer_factory is None:
        console.print(f"[{RED}]✗[/] Not initialized: run via spectra entry point")
        raise typer.Exit(code=1)


def _version_callback(value: bool) -> None:
    """Print version and exit when --version/-v is passed."""
    if value:
        console.print(f"[bold {VIOLET}]spectra[/] v0.1.0 [dim]// codebase intelligence[/]")
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
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show debug output",
    ),
) -> None:
    """Analyze a repository across 6 dimensions."""
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(name)s %(levelname)s %(message)s",
        )

    _validate_analyze_inputs(repo_url, fmt)

    _print_banner()
    repo_name = _derive_display_name(repo_url)
    console.print(f"  [{AMBER}]target:[/] {repo_name}  [dim]({repo_url})[/]")
    mode_label = "quick scan [dim](no critique)[/]" if quick else "full analysis [dim](8 agents)[/]"
    console.print(f"  [{AMBER}]mode:[/]   {mode_label}")
    console.print(f"  [{AMBER}]output:[/] {output}  [dim]({fmt})[/]")
    console.print()
    if not quick:
        console.print(_PIPELINE_INFO)
    console.print()

    try:
        report = asyncio.run(
            _analyzer_factory(
                repo_url=repo_url,
                output_path=str(output),
                skip_critique=quick,
                output_format=fmt,
                verbose=verbose,
                force=force,
                no_cache=no_cache,
            )
        )
    except KeyboardInterrupt:
        console.print(f"\n[{AMBER}]⚠[/] Analysis cancelled by user")
        raise typer.Exit(code=130) from None
    except (GitError, SpectraRetryError, AgentError) as exc:
        err = exc.error
        console.print(f"[{RED}]✗[/] {err.code}: {err.message}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print(f"[{RED}]✗[/] Unexpected error: {exc}")
        if verbose:
            console.print(traceback.format_exc())
        raise typer.Exit(code=1) from exc

    if report is None:
        raise typer.Exit(code=1)

    _print_summary(report, str(output), fmt)

    # Quality gate: exit 1 if score is below --min-score threshold
    if min_score > 0:
        sc = getattr(report, "score_card", None)
        if sc and sc.overall_score < min_score:
            console.print(f"\n[{RED}]✗[/] Quality gate FAILED: {sc.overall_score:.0f} < {min_score:.0f} threshold")
            raise typer.Exit(code=1)
        if sc:
            console.print(f"  [{GREEN}]✓[/] Quality gate passed: {sc.overall_score:.0f} >= {min_score:.0f}")


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
