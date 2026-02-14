"""Typer CLI controller for Spectra — Layer 3 adapter.

The CLI defines commands and options but does NOT wire dependencies.
The composition root (infrastructure/main.py) sets the analyzer
callable via `set_analyzer_factory()` before the CLI runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console

from spectra.adapters.analysis_presenter import present_scorecard
from spectra.infrastructure.agents.base_agent import AgentError
from spectra.infrastructure.git_adapter import GitError
from spectra.infrastructure.retry_decorator import SpectraRetryError

app = typer.Typer(
    name="spectra",
    help="8 AI agents analyze your entire repository in 90 seconds",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()

OutputFormat = Literal["html", "json"]

# Injected by the composition root before CLI runs
_analyzer_factory: Callable[..., Awaitable[object]] | None = None


def set_analyzer_factory(
    factory: Callable[..., Awaitable[object]],
) -> None:
    """Inject the async analyzer callable from the composition root."""
    global _analyzer_factory  # noqa: PLW0603
    _analyzer_factory = factory


def _version_callback(value: bool) -> None:
    if value:
        console.print("[bold #7C3AED]Spectra[/] v0.1.0")
        raise typer.Exit()


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
    output: Path = typer.Option(
        Path("spectra-report.html"),
        "--output",
        "-o",
        help="Report output path",
    ),
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
        help="Output format: html or json",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show debug output",
    ),
) -> None:
    """Analyze a repository across 6 dimensions."""
    if fmt not in ("html", "json"):
        console.print("[#EF4444]✗[/] Invalid format: use html or json")
        raise typer.Exit(code=1)

    if _analyzer_factory is None:
        console.print(
            "[#EF4444]✗[/] Not initialized: run via spectra entry point"
        )
        raise typer.Exit(code=1)

    console.print(
        "[bold #7C3AED]Spectra[/] — The full spectrum of your codebase\n"
    )

    try:
        report = asyncio.run(
            _analyzer_factory(
                repo_url=repo_url,
                output_path=str(output),
                skip_critique=quick,
                output_format=fmt,
                verbose=verbose,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[#F59E0B]⚠[/] Analysis cancelled by user")
        raise typer.Exit(code=130)
    except (GitError, SpectraRetryError, AgentError) as exc:
        err = exc.error
        console.print(
            f"[#EF4444]✗[/] {err.code}: {err.message}"
        )
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[#EF4444]✗[/] Unexpected error: {exc}")
        raise typer.Exit(code=1)

    if report is None:
        raise typer.Exit(code=1)

    _print_summary(report, str(output), fmt)


def _print_summary(
    report: object,
    output_path: str,
    output_format: str,
) -> None:
    """Print final summary after analysis completes."""
    present_scorecard(report, console)

    if output_format == "html":
        console.print(f"[#22C55E]✓[/] Report saved to {output_path}")
    else:
        console.print(f"[#22C55E]✓[/] JSON written to {output_path}")


def cli_entry() -> None:
    """Entry point — called by composition root after DI wiring."""
    app()
