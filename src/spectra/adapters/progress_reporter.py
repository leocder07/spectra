"""Rich Progress reporter implementing ProgressObserver — Layer 3 adapter."""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.style import Style
from rich.theme import Theme

from spectra.adapters.brand import AMBER, CYAN, GRAY, GREEN, RED, VIOLET
from spectra.entities.enums import AgentRole

SPECTRA_THEME = Theme(
    {
        "progress.description": Style(color=VIOLET, bold=True),
        "progress.percentage": Style(color=AMBER),
        "bar.complete": Style(color=VIOLET),
        "bar.finished": Style(color=GREEN),
    }
)

AGENT_DISPLAY_NAMES: dict[AgentRole, str] = {
    "meta_prompter": "MetaPrompter",
    "architecture": "ArchitectureAgent",
    "security": "SecurityAgent",
    "quality": "QualityAgent",
    "documentation": "DocumentationAgent",
    "dependency": "DependencyAgent",
    "performance": "PerformanceAgent",
    "critique": "CritiqueAgent",
}


class RichProgressReporter:
    """Rich-based implementation of ProgressObserver protocol.

    Displays stage transitions and parallel agent progress using
    Rich Progress bars and Console output.
    """

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console(theme=SPECTRA_THEME)
        self._progress: Progress | None = None
        self._agent_tasks: dict[AgentRole, TaskID] = {}

    def on_stage_start(self, stage: str, message: str) -> None:
        """Display stage start with ▸ prefix."""
        self._console.print(f"[{VIOLET}]▸[/] {stage}: {message}")

    def on_stage_complete(self, stage: str, message: str) -> None:
        """Display stage completion with ✓ prefix."""
        self._console.print(f"[{GREEN}]✓[/] {stage}: {message}")

    def on_agent_start(self, agent: AgentRole) -> None:
        """Add agent to parallel progress display."""
        display_name = AGENT_DISPLAY_NAMES.get(agent, str(agent))

        if self._progress is None:
            self._progress = Progress(
                SpinnerColumn(style=Style(color=AMBER)),
                TextColumn(
                    "[progress.description]{task.description}",
                ),
                BarColumn(
                    bar_width=20,
                    complete_style=Style(color=VIOLET),
                    finished_style=Style(color=GREEN),
                ),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=self._console,
            )
            self._progress.start()

        task_id = self._progress.add_task(
            description=f"  ├─ {display_name:<20}",
            total=100,
        )
        self._agent_tasks[agent] = task_id

    def on_agent_progress(self, agent: AgentRole, pct: float) -> None:
        """Update agent progress percentage."""
        if self._progress is not None and agent in self._agent_tasks:
            self._progress.update(
                self._agent_tasks[agent],
                completed=pct,
            )

    def on_agent_success(self, agent: AgentRole, duration: float) -> None:
        """Mark agent as successfully complete."""
        display_name = AGENT_DISPLAY_NAMES.get(agent, str(agent))

        if self._progress is not None and agent in self._agent_tasks:
            task_id = self._agent_tasks[agent]
            self._progress.update(
                task_id,
                completed=100,
                description=f"  ├─ {display_name:<20}",
            )

        self._maybe_stop_progress()
        self._console.print(
            f"[{GREEN}]  ✓[/] {display_name} complete ({duration:.1f}s)"
        )

    def on_agent_failure(self, agent: AgentRole, error: str) -> None:
        """Mark agent as failed."""
        display_name = AGENT_DISPLAY_NAMES.get(agent, str(agent))

        if self._progress is not None and agent in self._agent_tasks:
            task_id = self._agent_tasks[agent]
            self._progress.update(
                task_id,
                description=(
                    f"  ├─ [{RED}]{display_name:<20}[/]"
                ),
            )

        self._maybe_stop_progress()
        self._console.print(
            f"[{RED}]  ✗[/] {display_name} failed: {error}"
        )

    def _maybe_stop_progress(self) -> None:
        """Stop progress display if all agents are done."""
        remaining = {
            role
            for role, tid in self._agent_tasks.items()
            if self._progress is not None
            and not self._progress.tasks[tid].finished
        }
        if not remaining and self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._agent_tasks.clear()

    def on_error(self, stage: str, error: str) -> None:
        """Display error with ✗ prefix and explanation."""
        self._console.print(f"[{RED}]✗[/] {stage}: {error}")

    def stop(self) -> None:
        """Clean up progress bars if still running."""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._agent_tasks.clear()
