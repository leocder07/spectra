"""Composition root — wires all dependencies and exposes the CLI entry point."""

from __future__ import annotations

import json
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
    """Raised when report rendering fails."""

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
    """Full pipeline: clone → plan → analyze → critique → report."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        msg = "ANTHROPIC_API_KEY environment variable is required"
        raise RuntimeError(msg)

    # Wire decorator chain: Logging → Retry → Anthropic
    observer = RichProgressReporter()
    adapter = AnthropicAdapter(api_key=api_key)
    retry = RetryDecorator(adapter, max_retries=3, backoff_base=1.0)
    gateway = LoggingDecorator(retry, observer=observer)

    # Infrastructure adapters
    git = GitAdapter()
    TiktokenAdapter()
    report_renderer = ReportAdapter()

    clone_dir = tempfile.mkdtemp(prefix="spectra-")
    try:
        # Stage 1: INGEST — clone repo
        observer.on_stage_start("INGEST", "Cloning repository")
        await git.clone(repo_url, clone_dir)
        file_tree = await git.get_file_tree(clone_dir)
        observer.on_stage_complete("INGEST", f"{len(file_tree)} files indexed")

        repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        codebase = Codebase(
            repo_url=repo_url,
            repo_name=repo_name,
            local_path=clone_dir,
            file_tree=tuple(file_tree),
        )

        # Create agents
        factory = AgentFactory(gateway=gateway)
        meta_prompter = factory.create("meta_prompter")
        specialists = factory.create_specialists()
        critique_agent = None if skip_critique else factory.create("critique")

        # Stages 2-5: PLAN → ANALYZE → MERGE → CRITIQUE
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
            observer=observer,
        )

        # Stage 6: REPORT
        observer.on_stage_start("REPORT", "Rendering report")
        try:
            if output_format == "json":
                data = json.dumps(report.model_dump(mode="json"), indent=2)
                Path(output_path).write_text(data, encoding="utf-8")
            else:
                report_renderer.render(report, output_path)
        except Exception as exc:
            raise ReportError(ERRORS["SPEC-009"]) from exc
        observer.on_stage_complete("REPORT", "Report generated")

        return report
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)
        await adapter.close()


def cli() -> None:
    """Package entry point — wires DI then starts CLI."""
    set_analyzer_factory(_run_analysis)
    cli_entry()
