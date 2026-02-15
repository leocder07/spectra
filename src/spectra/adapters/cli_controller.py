"""Typer CLI controller for Spectra — Layer 3 adapter.

The CLI defines commands and options but does NOT wire dependencies.
The composition root (infrastructure/main.py) sets the analyzer
callable via `set_analyzer_factory()` before the CLI runs.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import typer
from rich.console import Console

from spectra.adapters.analysis_presenter import present_scorecard
from spectra.adapters.brand import AMBER, GREEN, RED, VIOLET
from spectra.entities.errors import AgentError, GitError, SpectraRetryError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

app = typer.Typer(
    name="spectra",
    help="8 AI agents analyze your entire repository in 90 seconds",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()

OutputFormat = Literal["html", "json"]

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
[dim #52525b]  8 agents · 6 dimensions · 90 seconds[/]
"""

_SCAN_LINE = f"[{VIOLET}]{'─' * 50}[/]"

# Injected by the composition root before CLI runs
_analyzer_factory: Callable[..., Awaitable[object]] | None = None


def set_analyzer_factory(
    factory: Callable[..., Awaitable[object]],
) -> None:
    """Inject the async analyzer callable from the composition root."""
    global _analyzer_factory  # noqa: PLW0603
    _analyzer_factory = factory


def _print_banner() -> None:
    """Print the hacker-style ASCII banner."""
    console.print(_BANNER)
    console.print(_SCAN_LINE)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold {VIOLET}]spectra[/] v0.1.0 [dim]// codebase intelligence[/]")
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
        help="Output format: html or json",
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

    if fmt not in ("html", "json"):
        console.print(f"[{RED}]✗[/] Invalid format: use html or json")
        raise typer.Exit(code=1)

    if _analyzer_factory is None:
        console.print(f"[{RED}]✗[/] Not initialized: run via spectra entry point")
        raise typer.Exit(code=1)

    _print_banner()
    repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    console.print(f"  [{AMBER}]target:[/] {repo_name}  [dim]({repo_url})[/]")
    if quick:
        console.print(f"  [{AMBER}]mode:[/]   quick scan [dim](no critique)[/]")
    console.print()

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


def _print_summary(
    report: object,
    output_path: str,
    output_format: str,
) -> None:
    """Print final summary after analysis completes."""
    console.print(_SCAN_LINE)
    present_scorecard(report, console)

    if output_format == "html":
        console.print(f"\n  [{GREEN}]✓[/] Report saved to [bold underline]{output_path}[/]")
    else:
        console.print(f"\n  [{GREEN}]✓[/] JSON written to [bold underline]{output_path}[/]")

    console.print(f"\n[dim {VIOLET}]  // spectra analysis complete[/]\n")


def cli_entry() -> None:
    """Entry point — called by composition root after DI wiring."""
    app()
