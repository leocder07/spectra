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
from pathlib import Path

from spectra.adapters.cli_controller import cli_entry, set_analyzer_factory
from spectra.adapters.progress_reporter import RichProgressReporter
from spectra.entities.errors import ERRORS, SpectraError
from spectra.entities.models import AnalysisReport, AnalysisRequest, Codebase
from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.infrastructure.anthropic_adapter import AnthropicAdapter
from spectra.infrastructure.git_adapter import GitAdapter
from spectra.infrastructure.logging_decorator import LoggingDecorator
from spectra.infrastructure.report_adapter import ReportAdapter
from spectra.infrastructure.retry_decorator import RetryDecorator
from spectra.infrastructure.tiktoken_adapter import TiktokenAdapter
from spectra.use_cases.analyze_repository import analyze_repository


class ReportError(Exception):
    """Raised when report rendering fails (SPEC-009).

    Attributes:
        error: The underlying ``SpectraError`` with code and message.
    """

    def __init__(self, error: SpectraError) -> None:
        self.error = error
        super().__init__(f"{error.code}: {error.message}")


async def _run_analysis(
    repo_url: str,
    output_path: str,
    skip_critique: bool = False,
    output_format: str = "html",
    verbose: bool = False,
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

    Returns:
        Completed analysis report.

    Raises:
        RuntimeError: If ``ANTHROPIC_API_KEY`` is not set.
        ReportError: If report rendering fails (SPEC-009).
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
    git = GitAdapter()
    report_renderer = ReportAdapter()

    clone_dir = tempfile.mkdtemp(prefix="spectra-")
    os.chmod(clone_dir, 0o700)
    try:
        # Stage 1: INGEST — clone repo
        observer.on_stage_start("INGEST", "Cloning repository")
        await git.clone(repo_url, clone_dir)
        await git.validate_repo_size(clone_dir)
        file_tree = await git.get_file_tree(clone_dir)
        observer.on_stage_complete("INGEST", f"{len(file_tree)} files indexed")

        # Pre-read key source files by heuristic for specialist agents
        source_files = await _read_key_source_files(git, clone_dir, file_tree)

        repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        codebase = Codebase(
            repo_url=repo_url,
            repo_name=repo_name,
            local_path=clone_dir,
            file_tree=tuple(file_tree),
        )

        # ── DI Wiring: Agent Factory ──────────────────────────────
        # AgentFactory creates all 8 agents with the decorated gateway.
        # MetaPrompter (Opus 4.7, medium effort) plans from file tree only.
        # 6 specialists (Opus 4.7, effort=xhigh) run in parallel via asyncio.gather.
        # CritiqueAgent (Opus 4.7, adaptive thinking + task budget) validates findings.
        factory = AgentFactory(gateway=gateway)
        meta_prompter = factory.create("meta_prompter")
        specialists = factory.create_specialists()
        critique_agent = None if skip_critique else factory.create("critique")

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

        report = await analyze_repository(
            request=request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=specialists,
            critique_agent=critique_agent,
            source_files=source_files,
            git_port=git,
            observer=observer,
        )

        # Stage 6: REPORT
        observer.on_stage_start("REPORT", "Rendering report")
        try:
            if output_format == "json":
                data = json.dumps(report.model_dump(mode="json"), indent=2)
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
        shutil.rmtree(clone_dir, ignore_errors=True)
        await adapter.close()


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
                        "version": "0.1.0",
                        "informationUri": "https://github.com/leocder07/spectra",
                        "rules": [],
                    },
                },
                "results": results,
            }
        ],
    }


def cli() -> None:
    """Package entry point — wires DI then starts CLI.

    This is the ``[project.scripts]`` entry point. It injects the
    analyzer factory into the CLI controller before starting Typer.
    """
    set_analyzer_factory(_run_analysis)
    cli_entry()
